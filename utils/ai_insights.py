from datetime import datetime, timedelta
import json
import os
import re
import time
from dotenv import load_dotenv

from database.database import Database

load_dotenv()

try:
    import google.genai as genai
except Exception:
    genai = None

_AI_CACHE = {"ts": 0, "data": None}
_AI_FAILURE_CACHE = {"ts": 0}


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _parse_date(value):
    if not value:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except Exception:
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except Exception:
            continue
    return None


def _get_ai_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or not genai:
        return None, None
    model = os.getenv("GEMINI_MODEL") or "models/gemini-2.5-flash"
    try:
        return genai.Client(api_key=api_key), model
    except Exception:
        return None, None


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _fetch_sales_velocity(db, days=14):
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    db.cursor.execute(
        "SELECT product_id, COALESCE(SUM(quantity), 0) "
        "FROM sales WHERE DATE(sale_date) >= ? "
        "GROUP BY product_id",
        (start_date,),
    )
    totals = {row[0]: _safe_float(row[1], 0.0) for row in db.cursor.fetchall()}
    velocity = {}
    for product_id, total_qty in totals.items():
        velocity[product_id] = total_qty / max(days, 1)
    return velocity


def _build_forecasts(db, days=14, limit=10):
    velocity = _fetch_sales_velocity(db, days=days)
    db.cursor.execute(
        "SELECT id, description, existing_stock, is_sold_by_weight, expiry_date, "
        "sale_price, unit_purchase_price "
        "FROM products"
    )
    forecasts = []
    expiry_risk = []
    today_date = datetime.now().date()
    for prod_id, name, stock, by_weight, expiry_date, sale_price, unit_purchase_price in db.cursor.fetchall():
        avg_daily = _safe_float(velocity.get(prod_id, 0.0), 0.0)
        stock_value = _safe_float(stock, 0.0)
        days_left = None
        recommended_qty = 0.0
        if avg_daily > 0:
            days_left = stock_value / avg_daily
            recommended_qty = max(0.0, (avg_daily * days) - stock_value)
        unit = "kg" if by_weight else "un"
        forecasts.append({
            "name": name,
            "stock": stock_value,
            "unit": unit,
            "avg_daily": avg_daily,
            "days_left": days_left,
            "recommended_qty": recommended_qty,
        })

        exp_date = _parse_date(expiry_date)
        if exp_date and avg_daily > 0:
            days_to_expiry = (exp_date - today_date).days
            if days_to_expiry >= 0:
                days_to_sell = stock_value / avg_daily
                if days_to_sell > days_to_expiry:
                    unsold_qty = max(0.0, stock_value - (avg_daily * days_to_expiry))
                    loss_revenue = unsold_qty * _safe_float(sale_price, 0.0)
                    loss_profit = unsold_qty * (
                        _safe_float(sale_price, 0.0)
                        - _safe_float(unit_purchase_price, 0.0)
                    )
                    expiry_risk.append({
                        "name": name,
                        "days_to_expiry": days_to_expiry,
                        "days_to_sell": days_to_sell,
                        "stock": stock_value,
                        "unit": unit,
                        "unsold_qty": unsold_qty,
                        "loss_revenue": loss_revenue,
                        "loss_profit": loss_profit,
                    })

    forecasts.sort(key=lambda x: (x["days_left"] is None, x["days_left"] or 9999))
    expiry_risk.sort(key=lambda x: x["days_to_expiry"])
    return forecasts[:limit], expiry_risk[:limit]


def _extract_json(text):
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def _generate_ai_insights(payload):
    client, model = _get_ai_client()
    if not client or not model:
        return None

    prompt = (
        "Voce e um analista de vendas e stock. "
        "Analise os dados e devolva apenas JSON, sem texto extra. "
        "Idioma: Portugues de Mocambique. Sem emojis. "
        "Maximo 3 itens por lista.\n\n"
        "JSON_ESPERADO:\n"
        "{\n"
        "  \"summary\": [\"...\"],\n"
        "  \"alerts\": [\"...\"],\n"
        "  \"recommendations\": [\"...\"],\n"
        "  \"stock_actions\": [\"...\"],\n"
        "  \"expiry_actions\": [\"...\"]\n"
        "}\n\n"
        "DADOS:\n"
        f"{json.dumps(payload, ensure_ascii=True)}"
    )

    try:
        response = client.models.generate_content(model=model, contents=prompt)
        data = _extract_json(getattr(response, "text", ""))
        return data
    except Exception as exc:
        msg = str(exc).lower()
        if "429" in msg or "too many requests" in msg:
            _AI_FAILURE_CACHE["ts"] = time.time()
        return None


def has_badge_alerts(insights):
    """
    Verifica se existem alertas que devem mostrar badges.
    Retorna True se houver pelo menos um tipo de alerta.
    """
    return bool(
        insights.get("low_stock")
        or insights.get("expiring_7")
        or insights.get("expiring_15")
    )


def get_badge_counts(insights):
    """
    Retorna contadores individuais para cada tipo de badge.
    Útil para mostrar notificações na UI.
    """
    return {
        "stock": len(insights.get("low_stock", [])),
        "expiry_7": len(insights.get("expiring_7", [])),
        "expiry_15": len(insights.get("expiring_15", [])),
        "total": (
            len(insights.get("low_stock", []))
            + len(insights.get("expiring_7", []))
            + len(insights.get("expiring_15", []))
        ),
    }


def build_admin_insights(db=None):
    """
    Retorna insights simples para o admin.
    Estrutura otimizada para badges independentes:
    {
        "summary": [str, ...],
        "alerts": [str, ...],
        "recommendations": [str, ...],
        "low_stock": [(name, stock, is_by_weight), ...],  # Tuplas com 3 elementos
        "expiring_15": [(name, days_left, date), ...],
        "expiring_7": [(name, days_left, date), ...],
        "alert_count": int,
        "badge_counts": {"stock": int, "expiry_7": int, "expiry_15": int, "total": int}
    }
    """
    db = db or Database()
    today_date = datetime.now().date()
    today = today_date.strftime("%Y-%m-%d")

    # Total e quantidade de vendas hoje
    db.cursor.execute(
        "SELECT COALESCE(SUM(total_price), 0), COUNT(*) "
        "FROM sales WHERE DATE(sale_date) = ?",
        (today,),
    )
    total_sales, total_count = db.cursor.fetchone()
    total_sales = _safe_float(total_sales, 0.0)
    total_count = int(total_count or 0)

    # Produto lider (por total vendido em valor) hoje
    db.cursor.execute(
        "SELECT p.description, COALESCE(SUM(s.total_price), 0) AS total_val "
        "FROM sales s JOIN products p ON s.product_id = p.id "
        "WHERE DATE(s.sale_date) = ? "
        "GROUP BY p.id ORDER BY total_val DESC LIMIT 1",
        (today,),
    )
    row = db.cursor.fetchone()
    top_product = row[0] if row else "n/d"

    # Horario mais forte hoje
    db.cursor.execute(
        "SELECT strftime('%H', sale_date) AS h, COALESCE(SUM(total_price), 0) AS total_val "
        "FROM sales WHERE DATE(sale_date) = ? "
        "GROUP BY h ORDER BY total_val DESC LIMIT 1",
        (today,),
    )
    row = db.cursor.fetchone()
    peak_hour = f"{row[0]}:00-{row[0]}:59" if row else "n/d"

    # Produtos com stock baixo - GARANTIR 3 ELEMENTOS NA TUPLA
    low_threshold = 5
    db.cursor.execute(
        "SELECT description, existing_stock, is_sold_by_weight FROM products "
        "WHERE existing_stock <= ? ORDER BY existing_stock ASC LIMIT 10",
        (low_threshold,),
    )
    low_stock = db.cursor.fetchall()

    # Produtos com lucro negativo
    db.cursor.execute(
        "SELECT description, profit_per_unit FROM products "
        "WHERE profit_per_unit < 0 ORDER BY profit_per_unit ASC LIMIT 3"
    )
    negative_profit = db.cursor.fetchall()

    # Produtos prestes a vencer
    db.cursor.execute(
        "SELECT description, expiry_date, existing_stock, is_sold_by_weight "
        "FROM products "
        "WHERE expiry_date IS NOT NULL AND expiry_date != ''"
    )
    expiring_15 = []
    expiring_7 = []
    for name, expiry_date, stock, is_by_weight in db.cursor.fetchall():
        exp_date = _parse_date(expiry_date)
        if not exp_date:
            continue
        days_left = (exp_date - today_date).days
        if days_left < 0:
            continue
        unit = "kg" if is_by_weight else "un"
        if days_left <= 7:
            expiring_7.append(
                (name, days_left, exp_date.strftime("%d/%m/%Y"), _safe_float(stock), unit)
            )
        elif days_left <= 15:
            expiring_15.append(
                (name, days_left, exp_date.strftime("%d/%m/%Y"), _safe_float(stock), unit)
            )

    expiring_7.sort(key=lambda x: x[1])
    expiring_15.sort(key=lambda x: x[1])

    forecasts, expiry_risk = _build_forecasts(db, days=14, limit=10)

    summary = [
        f"Total vendido hoje: {total_sales:.2f} MZN",
        f"Total de vendas hoje: {total_count}",
        f"Produto lider: {top_product}",
        f"Horario mais forte: {peak_hour}",
    ]

    alerts = []
    if total_count == 0:
        alerts.append("Sem vendas registradas hoje.")
    if low_stock:
        alerts.append(f"{len(low_stock)} produtos com stock baixo (<= {low_threshold}).")
    if expiring_15:
        alerts.append(f"{len(expiring_15)} produtos a vencer em ate 15 dias.")
    if expiring_7:
        alerts.append(f"{len(expiring_7)} produtos a vencer em ate 7 dias.")
    if negative_profit:
        alerts.append(f"{len(negative_profit)} produtos com lucro negativo.")

    recommendations = []
    recommendations_stock = []
    recommendations_expiry = []
    if low_stock:
        names = ", ".join([p[0] for p in low_stock[:3]])
        rec = f"Repor stock: {names}."
        recommendations.append(rec)
        recommendations_stock.append(rec)
    if expiring_7:
        names = ", ".join([p[0] for p in expiring_7[:3]])
        rec = f"Priorizar venda: {names}."
        recommendations.append(rec)
        recommendations_expiry.append(rec)
    if negative_profit:
        names = ", ".join([p[0] for p in negative_profit[:3]])
        recommendations.append(f"Rever preco de: {names}.")
    if not recommendations:
        recommendations.append("Sem recomendacoes criticas no momento.")

    alert_count = (
        (1 if total_count == 0 else 0)
        + len(low_stock)
        + len(expiring_15)
        + len(expiring_7)
        + len(negative_profit)
    )

    result = {
        "summary": summary,
        "alerts": alerts,
        "recommendations": recommendations,
        "recommendations_stock": recommendations_stock,
        "recommendations_expiry": recommendations_expiry,
        "low_stock": low_stock,
        "expiring_15": expiring_15,
        "expiring_7": expiring_7,
        "stock_forecast": forecasts,
        "expiry_risk": expiry_risk,
        "negative_profit": negative_profit,
        "alert_count": alert_count,
    }
    
    # Adicionar contadores de badges
    result["badge_counts"] = get_badge_counts(result)
    
    return result


def build_admin_insights_ai(db=None, cache_minutes=5):
    base = build_admin_insights(db)
    now = time.time()
    if _AI_FAILURE_CACHE["ts"] and (now - _AI_FAILURE_CACHE["ts"] < 600):
        return base
    if _AI_CACHE["data"] and (now - _AI_CACHE["ts"] < cache_minutes * 60):
        cached = _AI_CACHE["data"]
        return {**base, **cached}

    payload = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "summary": base.get("summary", []),
        "alerts": base.get("alerts", []),
        "low_stock": [
            {
                "name": item[0],
                "stock": _safe_float(item[1]),
                "unit": "kg" if (len(item) > 2 and item[2]) else "un",
            }
            for item in base.get("low_stock", [])
        ],
        "expiring_7": [
            {
                "name": name,
                "days_left": days,
                "date": date_str,
                "stock": stock,
                "unit": unit,
            }
            for name, days, date_str, stock, unit in base.get("expiring_7", [])
        ],
        "expiring_15": [
            {
                "name": name,
                "days_left": days,
                "date": date_str,
                "stock": stock,
                "unit": unit,
            }
            for name, days, date_str, stock, unit in base.get("expiring_15", [])
        ],
        "stock_forecast": base.get("stock_forecast", []),
        "expiry_risk": base.get("expiry_risk", []),
        "negative_profit": [
            {"name": item[0], "profit": _safe_float(item[1])}
            for item in base.get("negative_profit", [])
        ],
    }

    ai = _generate_ai_insights(payload)
    if not ai:
        return base

    ai_data = {
        "ai_summary": ai.get("summary", []),
        "ai_alerts": ai.get("alerts", []),
        "ai_recommendations": ai.get("recommendations", []),
        "ai_stock_notes": ai.get("stock_actions", []),
        "ai_expiry_notes": ai.get("expiry_actions", []),
    }
    _AI_CACHE["ts"] = now
    _AI_CACHE["data"] = ai_data
    return {**base, **ai_data}
