from datetime import datetime, timedelta
import json
import os
import re
import time
import random
from collections import defaultdict
from kivy.app import App
from database.provider import get_db
from utils.env_loader import load_dotenv
from utils.i18n import normalize_language, translate

load_dotenv()

genai = None
_GENAI_IMPORT_ATTEMPTED = False

_AI_CACHE = {"ts": 0, "data": None}
_AI_FAILURE_CACHE = {"ts": 0}
_QA_CACHE = {"ts": 0, "key": None, "data": None}
_QA_API_FAILURE_CACHE = {"ts": 0, "reason": "", "until": 0, "key_sig": ""}


def _current_language_code():
    app = App.get_running_app()
    if app and getattr(app, "language", None):
        return normalize_language(getattr(app, "language"))
    try:
        from utils.app_config import get_app_settings

        return normalize_language(get_app_settings().get("language"))
    except Exception:
        return "pt"


def _current_ai_response_language():
    code = _current_language_code()
    return translate("ai.response_language_name", code, default="portugues")


def _get_ai_key_and_model():
    # Reload .env on each check so key rotation works without app restart.
    try:
        load_dotenv(override=True)
    except Exception:
        pass
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    model = (os.getenv("GEMINI_MODEL") or "models/gemini-2.5-flash").strip()
    if not api_key:
        return "", model
    lowered = api_key.lower()
    if lowered in {"changeme", "your_api_key_here", "your_gemini_key_here"}:
        return "", model
    return api_key, model


def _get_key_signature(api_key):
    key = str(api_key or "").strip()
    if not key:
        return ""
    return key[-8:]


def _sync_api_failure_cache_key(api_key):
    key_sig = _get_key_signature(api_key)
    if _QA_API_FAILURE_CACHE.get("key_sig", "") != key_sig:
        _QA_API_FAILURE_CACHE["ts"] = 0
        _QA_API_FAILURE_CACHE["reason"] = ""
        _QA_API_FAILURE_CACHE["until"] = 0
        _QA_API_FAILURE_CACHE["key_sig"] = key_sig


def _is_api_in_cooldown():
    now_ts = time.time()
    return bool(_QA_API_FAILURE_CACHE.get("until", 0) > now_ts)


def _mark_api_failure(reason, api_key=""):
    text = str(reason or "").strip()
    lower = text.lower()
    cooldown_seconds = 120
    if "bloqueada" in lower or "comprometida" in lower or "permission" in lower or "403" in lower:
        cooldown_seconds = 3600
    elif "limite" in lower or "quota" in lower or "rate" in lower or "429" in lower:
        cooldown_seconds = 600
    elif "timeout" in lower:
        cooldown_seconds = 180

    now_ts = time.time()
    _QA_API_FAILURE_CACHE["ts"] = now_ts
    _QA_API_FAILURE_CACHE["reason"] = text
    _QA_API_FAILURE_CACHE["until"] = now_ts + cooldown_seconds
    _QA_API_FAILURE_CACHE["key_sig"] = _get_key_signature(api_key)


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value, default=0):
    try:
        return int(value)
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


def _get_genai_module():
    global genai, _GENAI_IMPORT_ATTEMPTED
    if _GENAI_IMPORT_ATTEMPTED:
        return genai
    _GENAI_IMPORT_ATTEMPTED = True
    try:
        import google.genai as _genai

        genai = _genai
    except Exception:
        genai = None
    return genai


def _get_ai_client():
    api_key, model = _get_ai_key_and_model()
    _sync_api_failure_cache_key(api_key)
    genai_module = _get_genai_module()
    if not api_key or not genai_module:
        return None, None
    try:
        return genai_module.Client(api_key=api_key), model
    except Exception:
        return None, None


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


def _get_product_daily_sales(db, product_id, days=14):
    """Calcula vendas diárias médias de um produto específico"""
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    db.cursor.execute(
        "SELECT COALESCE(SUM(quantity), 0) FROM sales "
        "WHERE product_id = ? AND DATE(sale_date) >= ?",
        (product_id, start_date),
    )
    total = _safe_float(db.cursor.fetchone()[0], 0.0)
    return total / max(days, 1)


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
            "product_id": prod_id,
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


def _get_business_context():
    """Gera contexto temporal dinâmico"""
    now = datetime.now()
    hora = now.hour
    dia = now.day
    dia_semana = now.strftime("%A")
    
    # Tom baseado na hora
    if hora < 12:
        tom = "tom de início de dia - energético mas focado"
        saudacao = "Bom dia!"
    elif hora < 18:
        tom = "tom de tarde - direto e prático"
        saudacao = "Boa tarde!"
    else:
        tom = "tom de fim de dia - reflexivo, olhando para amanhã"
        saudacao = "Boa noite!"
    
    # Contexto do mês
    if dia > 25:
        contexto_mes = "Fim de mês - clientes geralmente têm mais dinheiro"
    elif dia < 5:
        contexto_mes = "Início de mês - movimento pode estar mais fraco"
    else:
        contexto_mes = "Meio de mês - movimento normal"
    
    return {
        "tom": tom,
        "saudacao": saudacao,
        "dia_semana": dia_semana,
        "contexto_mes": contexto_mes,
        "hora": hora,
    }


def _generate_ai_insights(payload):
    """Gera insights com IA - muito mais natural e dinâmico"""
    client, model = _get_ai_client()
    if not client or not model:
        return None

    context = _get_business_context()
    language_name = _current_ai_response_language()
    
    prompt = (
        f"Responda em {language_name}.\n"
        f"Voce e um gestor experiente de micro e pequenas empresas comerciais em Mocambique, "
        f"conversando com o dono do negocio. {context['saudacao']}!\n\n"
        
        f"CONTEXTO ATUAL:\n"
        f"- Dia: {context['dia_semana']}, {datetime.now().strftime('%d/%m/%Y')}\n"
        f"- Hora: {context['hora']}h\n"
        f"- Momento: {context['contexto_mes']}\n"
        f"- Tom desejado: {context['tom']}\n\n"
        
        "PRINCÍPIOS DE COMUNICAÇÃO:\n"
        "1. SEJA HUMANO - Varie as palavras, nunca repita frases iguais\n"
        "2. SEJA ESPECÍFICO - Fale dos produtos pelo nome, use números reais\n"
        "3. SEJA PRÁTICO - Diga O QUE fazer, NÃO diga QUANTO repor (o dono sabe disso)\n"
        "4. SEJA VARIADO - Mude sempre a forma de alertar, use vocabulário diverso\n"
        "5. PRIORIZE - Comece pelo que mais importa financeiramente HOJE\n"
        "6. SEM LIMITES - Se tiver 10 problemas importantes, mencione TODOS\n"
        "7. SEJA NATURAL - Como se estivesse conversando pessoalmente\n\n"
        
        "EXEMPLOS DE COMO COMUNICAR (varie entre estes estilos):\n"
        "✅ 'Açúcar acabando - só 2 dias restam'\n"
        "✅ 'Leite vendeu muito ontem, cuidado com o stock'\n"
        "✅ 'Arroz está no fim, atenção'\n"
        "✅ 'Óleo vendendo rápido esta semana'\n"
        "✅ 'Farinha já está crítica'\n"
        "✅ 'Fim de semana chegando, cerveja pode faltar'\n"
        "✅ 'Leite vence em 5 dias, será aplicada uma redução de preço'\n"
        "✅ 'Iogurte vence amanhã, fazer promoção hoje'\n\n"
        
        "NUNCA FAÇA ASSIM:\n"
        "❌ 'Precisa repor 50kg de arroz' (NÃO mencionar quantidades)\n"
        "❌ 'Recomenda-se que...' (muito formal e robótico)\n"
        "❌ 'É aconselhável...' (muito técnico)\n"
        "❌ Sempre a mesma estrutura de frase\n"
        "❌ Limitar a 3 itens quando há mais problemas\n"
        "❌ Usar emojis\n\n"
        
        "ESTRUTURA JSON (IMPORTANTE - sem limite de itens!):\n"
        "{\n"
        "  'urgente_hoje': ['problemas que causam perda de dinheiro HOJE - listar TODOS'],\n"
        "  'atencao_proximos_dias': ['monitorar nos próximos 2-3 dias - listar TODOS'],\n"
        "  'oportunidades': ['ideias para vender/lucrar mais - listar TODAS'],\n"
        "  'observacoes': ['padrões, comparações, insights - listar TODOS']\n"
        "}\n\n"
        
        "REGRAS IMPORTANTES:\n"
        "- Cada item = uma frase curta (máximo 10 palavras)\n"
        "- Use vocabulário variado em CADA item\n"
        "- Seja direto e objetivo\n"
        "- Não repita estruturas\n"
        "- Liste TUDO que for relevante (sem limite de 3!)\n\n"
        
        "EXEMPLOS DE BOA VARIAÇÃO:\n"
        "Item 1: 'Farinha acabando em breve'\n"
        "Item 2: 'Atenção: açúcar já está baixo'\n"
        "Item 3: 'Arroz - menos de 3 dias'\n"
        "Item 4: 'Cuidado com óleo, vendendo rápido'\n"
        "Item 5: 'Sal crítico'\n\n"
        
        f"DADOS DO NEGÓCIO:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        
        "Analise TUDO e retorne JSON completo. Não economize nos insights!"
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
    """Verifica se existem alertas que devem mostrar badges"""
    expiry_levels = insights.get("expiry_levels") or {}
    return bool(
        insights.get("low_stock")
        or expiry_levels.get("vencido")
        or expiry_levels.get("critico")
        or expiry_levels.get("alto")
        or expiry_levels.get("medio")
        or expiry_levels.get("leve")
        or insights.get("expiring_90")
        or insights.get("expiring_7")
        or insights.get("expiring_15")
    )


def get_badge_counts(insights):
    """Retorna contadores individuais para cada tipo de badge"""
    existing = insights.get("badge_counts") or {}
    if existing:
        return dict(existing)
    expiry_levels = insights.get("expiry_levels") or {}
    expiry_total = (
        len(expiry_levels.get("vencido", []))
        + len(expiry_levels.get("critico", []))
        + len(expiry_levels.get("alto", []))
        + len(expiry_levels.get("medio", []))
        + len(expiry_levels.get("leve", []))
    )
    return {
        "stock": len(insights.get("low_stock", [])),
        "expiry_vencido": len(expiry_levels.get("vencido", [])),
        "expiry_critico": len(expiry_levels.get("critico", [])),
        "expiry_alto": len(expiry_levels.get("alto", [])),
        "expiry_medio": len(expiry_levels.get("medio", [])),
        "expiry_leve": len(expiry_levels.get("leve", [])),
        "expiry_total": expiry_total,
        "expiry_7": len(insights.get("expiring_7", [])),
        "expiry_15": len(insights.get("expiring_15", [])),
        "total": (
            len(insights.get("low_stock", []))
            + expiry_total
        ),
    }


def build_admin_insights(db=None):
    """
    Retorna insights completos para o admin.
    Usa o provedor de banco para suportar modo remoto.
    """
    db = db or get_db()
    return db.get_admin_insights() or {}


def build_admin_insights_ai(db=None, cache_minutes=5):
    """Gera insights enriquecidos com IA"""
    base = build_admin_insights(db)
    try:
        app = App.get_running_app()
    except Exception:
        app = None
    if app and not getattr(app, "ai_enabled", True):
        return base
    now = time.time()
    
    # Verificar falha recente da API (10min cooldown)
    if _AI_FAILURE_CACHE["ts"] and (now - _AI_FAILURE_CACHE["ts"] < 600):
        return base
    
    # Verificar cache
    if _AI_CACHE["data"] and (now - _AI_CACHE["ts"] < cache_minutes * 60):
        cached = _AI_CACHE["data"]
        return {**base, **cached}

    # Preparar payload para IA
    payload = {
        "data": datetime.now().strftime("%d/%m/%Y"),
        "hora": datetime.now().strftime("%H:%M"),
        "resumo_vendas": {
            "total_hoje": _safe_float(base.get("summary", ["0"])[0].split(":")[1].replace("MZN", "").strip() if base.get("summary") else "0"),
            "quantidade_vendas": base.get("summary", [None, "0"])[1].split(":")[1].strip() if len(base.get("summary", [])) > 1 else "0",
        },
        "stock_baixo": [
            {
                "nome": item[0],
                "stock_atual": _safe_float(item[1]),
                "unidade": "kg" if item[2] else "un",
                "dias_restantes": _safe_float(item[3]),
            }
            for item in base.get("low_stock", [])
        ],
        "vencimento_7dias": [
            {
                "nome": name,
                "dias_ate_vencer": days,
                "data_vencimento": date_str,
                "stock": stock,
                "unidade": unit,
            }
            for name, days, date_str, stock, unit in base.get("expiring_7", [])
        ],
        "vencimento_15dias": [
            {
                "nome": name,
                "dias_ate_vencer": days,
                "data_vencimento": date_str,
                "stock": stock,
                "unidade": unit,
            }
            for name, days, date_str, stock, unit in base.get("expiring_15", [])
        ],
        "vencimento_90dias": [
            {
                "nome": name,
                "dias_ate_vencer": days,
                "data_vencimento": date_str,
                "stock": stock,
                "unidade": unit,
            }
            for name, days, date_str, stock, unit in base.get("expiring_90", [])
        ],
        "previsao_stock": base.get("stock_forecast", [])[:10],
        "risco_vencimento": base.get("expiry_risk", [])[:10],
        "lucro_negativo": [
            {"nome": item[0], "lucro_unitario": _safe_float(item[1])}
            for item in base.get("negative_profit", [])
        ],
    }

    ai = _generate_ai_insights(payload)
    if not ai:
        return base

    ai_data = {
        "ai_urgente_hoje": ai.get("urgente_hoje", []),
        "ai_atencao_proximos_dias": ai.get("atencao_proximos_dias", []),
        "ai_oportunidades": ai.get("oportunidades", []),
        "ai_observacoes": ai.get("observacoes", []),
    }
    
    _AI_CACHE["ts"] = now
    _AI_CACHE["data"] = ai_data
    
    return {**base, **ai_data}


def can_use_ai_api():
    api_key, _ = _get_ai_key_and_model()
    _sync_api_failure_cache_key(api_key)
    if _is_api_in_cooldown():
        return False
    client, model = _get_ai_client()
    return bool(client and model)


def _sanitize_question(question, max_chars=320):
    text = str(question or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text[:max_chars]


def _resolve_lookback_days(question, default_days=30):
    text = _sanitize_question(question).lower()
    base = max(1, _safe_int(default_days, 30))
    if not text:
        return base

    match = re.search(r"\b(\d{1,3})\s*dias?\b", text)
    if match:
        return max(1, min(365, _safe_int(match.group(1), base)))

    if "hoje" in text:
        return 1
    if "ontem" in text:
        return 2
    if "semana" in text:
        return 7
    if "quinzena" in text:
        return 15
    if "mes" in text or "mês" in text:
        return 30
    if "trimestre" in text:
        return 90
    if "ano" in text:
        return 365
    return base


def _parse_datetime_loose(value):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    return None


def _fmt_mzn(value):
    return f"{_safe_float(value, 0.0):.2f} MZN"


def _friendly_api_error(raw_error):
    text = str(raw_error or "").strip()
    if not text:
        return "Falha desconhecida na API Gemini."
    lower = text.lower()
    if "reported as leaked" in lower or "api key was reported as leaked" in lower:
        return "A chave Gemini foi bloqueada por seguranca (comprometida). Gere uma nova API key."
    if "permission_denied" in lower or "403" in lower:
        return "Acesso negado na API Gemini (403). Verifique a chave e permissoes."
    if "429" in lower or "quota" in lower or "rate" in lower:
        return "Limite de uso da API Gemini atingido. Tente novamente mais tarde."
    if "timed out" in lower or "timeout" in lower:
        return "Timeout ao comunicar com a API Gemini."
    if "connection" in lower or "network" in lower:
        return "Falha de ligacao com a API Gemini."
    return text[:220]


def _build_management_snapshot(db, lookback_days=30):
    days = max(1, _safe_int(lookback_days, 30))
    now_dt = datetime.now()
    start_dt = now_dt - timedelta(days=days)
    start_str = start_dt.strftime("%d/%m/%Y")
    end_str = now_dt.strftime("%d/%m/%Y")
    start_str_full = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    end_str_full = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    insights = build_admin_insights(db)

    try:
        sales_rows = db.get_sales_by_date_range(start_str, end_str)
    except Exception:
        try:
            sales_rows = db.get_all_sales()
        except Exception:
            sales_rows = []

    filtered_sales = []
    for row in sales_rows or []:
        sale_dt = _parse_datetime_loose(row[5] if len(row) > 5 else None)
        if sale_dt and sale_dt < start_dt:
            continue
        filtered_sales.append(row)

    sales_count = len(filtered_sales)
    total_revenue = 0.0
    promo_count = 0
    promo_revenue = 0.0
    by_product = defaultdict(float)

    for row in filtered_sales:
        product = (row[1] if len(row) > 1 else "") or "Produto"
        unit_price = _safe_float(row[3] if len(row) > 3 else 0.0)
        total = _safe_float(row[4] if len(row) > 4 else 0.0)
        returned_qty = _safe_float(row[6] if len(row) > 6 else 0.0)
        is_promotional = bool(row[10]) if len(row) > 10 else False

        net_total = max(0.0, total - (returned_qty * unit_price))
        total_revenue += net_total
        by_product[product] += net_total

        if is_promotional:
            promo_count += 1
            promo_revenue += net_total

    top_products = sorted(by_product.items(), key=lambda item: item[1], reverse=True)[:5]

    try:
        loss_rows = db.get_loss_records(start_str_full, end_str_full, limit=500)
    except Exception:
        loss_rows = []
    loss_count = len(loss_rows or [])
    loss_cost = sum(_safe_float(row[5] if len(row) > 5 else 0.0) for row in (loss_rows or []))
    loss_revenue = sum(_safe_float(row[6] if len(row) > 6 else 0.0) for row in (loss_rows or []))
    loss_by_product = defaultdict(float)
    for row in loss_rows or []:
        pname = (row[1] if len(row) > 1 else "") or "Produto"
        loss_by_product[pname] += _safe_float(row[5] if len(row) > 5 else 0.0)
    top_loss_products = sorted(loss_by_product.items(), key=lambda item: item[1], reverse=True)[:5]

    try:
        logs = db.get_user_logs(limit=600)
    except Exception:
        logs = []
    actions_by_user = defaultdict(int)
    sales_actions_by_user = defaultdict(int)
    for row in logs or []:
        log_dt = _parse_datetime_loose(row[5] if len(row) > 5 else None)
        if log_dt and log_dt < start_dt:
            continue
        username = (row[1] if len(row) > 1 else "") or "Sistema"
        action = str(row[3] if len(row) > 3 else "").upper()
        actions_by_user[username] += 1
        if "SALE" in action:
            sales_actions_by_user[username] += 1

    top_user = None
    if actions_by_user:
        top_user = max(actions_by_user.items(), key=lambda item: item[1])
    top_seller = None
    if sales_actions_by_user:
        top_seller = max(sales_actions_by_user.items(), key=lambda item: item[1])

    return {
        "lookback_days": days,
        "insights": insights,
        "sales_count": sales_count,
        "total_revenue": total_revenue,
        "promo_count": promo_count,
        "promo_revenue": promo_revenue,
        "top_products": top_products,
        "loss_count": loss_count,
        "loss_cost": loss_cost,
        "loss_revenue": loss_revenue,
        "top_loss_products": top_loss_products,
        "actions_by_user": dict(actions_by_user),
        "sales_actions_by_user": dict(sales_actions_by_user),
        "top_user": top_user,
        "top_seller": top_seller,
        "active_users": len(actions_by_user),
    }


def _infer_focus(question):
    text = _sanitize_question(question).lower()
    keywords = {
        "sales": (
            "venda", "receita", "fatur", "ticket", "promoc", "preco", "lucro", "cliente",
        ),
        "stock": (
            "stock", "estoque", "ruptura", "repor", "repos", "invent", "produto", "disponivel",
        ),
        "losses": (
            "perda", "desperd", "venc", "expir", "quebra", "estrago", "custo perda",
        ),
        "productivity": (
            "produt", "equipe", "equipa", "usuario", "operador", "desempenho", "funcion",
        ),
    }
    scores = {"sales": 0, "stock": 0, "losses": 0, "productivity": 0}
    for key, words in keywords.items():
        for w in words:
            if w in text:
                scores[key] += 2 if " " in w else 1

    if "venc" in text or "expir" in text:
        scores["stock"] += 1
        scores["losses"] += 1
    if "promoc" in text:
        scores["sales"] += 2
    if "ruptura" in text:
        scores["stock"] += 2

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [name for name, score in ranked if score > 0]


def _is_business_context_question(question):
    text = _sanitize_question(question).lower()
    if len(text) < 3:
        return False
    business_terms = (
        "loja", "empresa", "comercio", "negocio", "venda", "receita", "fatur", "stock",
        "estoque", "produto", "perda", "desperd", "promoc", "preco", "lucro",
        "cliente", "repor", "venc", "equipa", "usuario", "operador", "operacional",
        "atividade", "produt", "caixa", "ruptura",
    )
    return any(term in text for term in business_terms)


def _short_product_list(values, limit=3):
    names = []
    for item in values or []:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("nome") or "").strip()
        elif isinstance(item, (tuple, list)):
            name = str(item[0] if item else "").strip()
        else:
            name = str(item).strip()
        if name and name not in names:
            names.append(name)
    return ", ".join(names[:limit])


def _route_business_question(question):
    text = _sanitize_question(question).lower()
    focus = _infer_focus(question)
    domain = focus[0] if focus else "general"

    if any(k in text for k in ("perda", "desperd", "quebra", "estrago")) and domain in ("general", "stock"):
        domain = "losses"
    if any(k in text for k in ("produt", "equipe", "equipa", "usuario", "operador", "operacional", "atividade")) and domain == "general":
        domain = "productivity"
    if any(k in text for k in ("venda", "receita", "fatur", "promoc", "ticket")) and domain == "general":
        domain = "sales"
    if any(k in text for k in ("stock", "estoque", "ruptura", "repor")) and domain == "general":
        domain = "stock"

    return {
        "domain": domain,
        "text": text,
        "ask_count": any(k in text for k in ("quant", "numero", "número", "qtd")),
        "ask_value": any(k in text for k in ("quanto", "valor", "receita", "fatur", "custo", "lucro", "total")),
        "ask_list": any(k in text for k in ("quais", "listar", "lista", "mostrar")),
        "ask_top": any(k in text for k in ("top", "maior", "mais vendido", "lider", "líder")),
        "ask_action": any(k in text for k in ("acao", "ação", "fazer", "devo", "suger", "priorizar", "melhorar")),
        "ask_alert": any(k in text for k in ("alert", "risco", "urg", "crit", "problema")),
        "mentions_promo": any(k in text for k in ("promo", "promocional")),
        "mentions_expiry": any(k in text for k in ("venc", "expir")),
    }


def _build_sales_answer(snapshot, route):
    lookback = snapshot["lookback_days"]
    if route["mentions_promo"]:
        if snapshot["promo_count"] <= 0:
            return [f"Nos ultimos {lookback} dias nao houve vendas promocionais."]
        return [
            f"Nos ultimos {lookback} dias tivemos {snapshot['promo_count']} vendas promocionais, com {_fmt_mzn(snapshot['promo_revenue'])}.",
        ]

    if route["ask_top"] or route["ask_list"]:
        top = snapshot.get("top_products") or []
        if not top:
            return [f"Nao ha produtos lideres identificados nos ultimos {lookback} dias."]
        formatted = ", ".join([f"{name} ({_fmt_mzn(val)})" for name, val in top[:3]])
        return [f"Top produtos por faturacao nos ultimos {lookback} dias: {formatted}."]

    if route["ask_count"] and not route["ask_value"]:
        return [f"Nos ultimos {lookback} dias registamos {snapshot['sales_count']} vendas."]

    if route["ask_value"]:
        return [f"Receita liquida nos ultimos {lookback} dias: {_fmt_mzn(snapshot['total_revenue'])}."]

    return [
        f"Nos ultimos {lookback} dias tivemos {snapshot['sales_count']} vendas com receita liquida de {_fmt_mzn(snapshot['total_revenue'])}.",
    ]


def _build_stock_answer(snapshot, route):
    lookback = snapshot["lookback_days"]
    insights = snapshot["insights"]
    low_stock = insights.get("low_stock") or []
    exp7 = insights.get("expiring_7") or []

    if route["mentions_expiry"]:
        if route["ask_list"]:
            names = _short_product_list(exp7)
            if names:
                return [f"Produtos a vencer em ate 7 dias: {names}."]
        return [f"Ha {len(exp7)} produtos com vencimento em ate 7 dias."]

    if route["ask_list"] or route["ask_top"]:
        names = _short_product_list(low_stock)
        if names:
            return [f"Itens com stock baixo agora: {names}."]
        return ["Nao ha itens com stock baixo no momento."]

    if route["ask_count"]:
        return [f"Atualmente temos {len(low_stock)} itens com stock baixo."]

    if route["ask_alert"] and low_stock:
        return [f"Risco imediato de ruptura em {len(low_stock)} itens; o mais critico e {low_stock[0][0]}."]

    return [
        f"Resumo de stock: {len(low_stock)} itens baixos e {len(exp7)} produtos a vencer em 7 dias (analise de {lookback} dias).",
    ]


def _build_losses_answer(snapshot, route):
    lookback = snapshot["lookback_days"]
    total_revenue = _safe_float(snapshot["total_revenue"], 0.0)
    loss_ratio = (snapshot["loss_cost"] / total_revenue * 100.0) if total_revenue > 0 else 0.0

    if route["ask_top"] or route["ask_list"]:
        top_loss = snapshot.get("top_loss_products") or []
        names = _short_product_list(top_loss)
        if names:
            return [f"Maiores fontes de perda nos ultimos {lookback} dias: {names}."]
        return [f"Nao ha produtos com perdas relevantes nos ultimos {lookback} dias."]

    if route["ask_count"] and not route["ask_value"]:
        return [f"Nos ultimos {lookback} dias foram registadas {snapshot['loss_count']} perdas."]

    if route["ask_value"] or route["mentions_expiry"]:
        return [
            f"Custo total das perdas nos ultimos {lookback} dias: {_fmt_mzn(snapshot['loss_cost'])} ({loss_ratio:.2f}% da receita).",
        ]

    return [f"Perdas no periodo: {snapshot['loss_count']} registos e custo de {_fmt_mzn(snapshot['loss_cost'])}."]


def _build_productivity_answer(snapshot, route):
    lookback = snapshot["lookback_days"]
    total_actions = sum(snapshot["actions_by_user"].values())
    q_text = route.get("text", "")

    if route["ask_top"] or "quem" in q_text:
        top_user = snapshot.get("top_user")
        if top_user:
            return [f"Maior atividade operacional nos ultimos {lookback} dias: {top_user[0]} ({top_user[1]} acoes)."]
        return [f"Nao ha atividade operacional suficiente para ranking nos ultimos {lookback} dias."]

    if route["ask_count"]:
        return [f"Produtividade: {snapshot['active_users']} utilizadores ativos e {total_actions} acoes no periodo."]

    if snapshot.get("top_seller"):
        return [f"Produtividade geral: {snapshot['active_users']} utilizadores ativos; maior foco em vendas: {snapshot['top_seller'][0]}."]
    return [f"Produtividade geral: {snapshot['active_users']} utilizadores ativos e {total_actions} acoes."]


def _build_direct_lines(question, snapshot, route):
    primary = route.get("domain", "general")
    if primary == "sales":
        return _build_sales_answer(snapshot, route)
    if primary == "stock":
        return _build_stock_answer(snapshot, route)
    if primary == "losses":
        return _build_losses_answer(snapshot, route)
    if primary == "productivity":
        return _build_productivity_answer(snapshot, route)

    low_count = len(snapshot["insights"].get("low_stock") or [])
    exp7 = len(snapshot["insights"].get("expiring_7") or [])
    lookback = snapshot["lookback_days"]
    lines = [
        f"Resumo rapido: {snapshot['sales_count']} vendas e {_fmt_mzn(snapshot['total_revenue'])} de receita nos ultimos {lookback} dias.",
        f"Pontos de atencao: {low_count} itens com stock baixo e {exp7} itens a vencer em 7 dias.",
    ]
    return lines


def _build_sales_lines(snapshot):
    lines = [
        f"Periodo analisado: ultimos {snapshot['lookback_days']} dias.",
        f"Total de vendas: {snapshot['sales_count']} registos.",
        f"Receita liquida estimada: {_fmt_mzn(snapshot['total_revenue'])}.",
    ]
    promo_count = snapshot["promo_count"]
    if promo_count > 0:
        promo_ratio = (promo_count / max(snapshot["sales_count"], 1)) * 100.0
        lines.append(
            f"Vendas promocionais: {promo_count} ({promo_ratio:.1f}%) e {_fmt_mzn(snapshot['promo_revenue'])}."
        )
    top_products = snapshot.get("top_products") or []
    if top_products:
        formatted = ", ".join([f"{name} ({_fmt_mzn(val)})" for name, val in top_products[:3]])
        lines.append(f"Produtos lideres: {formatted}.")
    return lines


def _build_stock_lines(snapshot):
    insights = snapshot["insights"]
    low_stock = insights.get("low_stock") or []
    exp7 = insights.get("expiring_7") or []
    exp15 = insights.get("expiring_15") or []
    lines = [
        f"Itens com stock baixo: {len(low_stock)}.",
        f"Itens a vencer em 7 dias: {len(exp7)}.",
        f"Itens a vencer em 15 dias: {len(exp15)}.",
    ]
    forecast = insights.get("stock_forecast") or []
    if forecast:
        critical = [f for f in forecast if _safe_float(f.get("days_left"), 9999) <= 5]
        lines.append(f"Risco de ruptura em ate 5 dias: {len(critical)} produtos.")
    return lines


def _build_loss_lines(snapshot):
    loss_count = snapshot["loss_count"]
    loss_cost = snapshot["loss_cost"]
    total_revenue = snapshot["total_revenue"]
    loss_ratio = (loss_cost / total_revenue * 100.0) if total_revenue > 0 else 0.0
    lines = [
        f"Perdas registadas: {loss_count}.",
        f"Custo total das perdas: {_fmt_mzn(loss_cost)}.",
        f"Impacto vs receita do periodo: {loss_ratio:.2f}%.",
    ]
    if snapshot.get("top_loss_products"):
        loss_top = ", ".join(
            [f"{name} ({_fmt_mzn(val)})" for name, val in snapshot["top_loss_products"][:3]]
        )
        lines.append(f"Maiores fontes de perda: {loss_top}.")
    return lines


def _build_productivity_lines(snapshot):
    lines = [
        f"Utilizadores ativos no periodo: {snapshot['active_users']}.",
        f"Total de acoes registadas: {sum(snapshot['actions_by_user'].values())}.",
    ]
    top_user = snapshot.get("top_user")
    if top_user:
        lines.append(f"Maior atividade: {top_user[0]} ({top_user[1]} acoes).")
    top_seller = snapshot.get("top_seller")
    if top_seller:
        lines.append(f"Maior foco em vendas: {top_seller[0]} ({top_seller[1]} acoes SALE).")
    return lines


def _build_alerts(snapshot):
    alerts = []
    if snapshot["sales_count"] == 0:
        alerts.append("Nao houve vendas no periodo analisado.")

    low_stock_count = len(snapshot["insights"].get("low_stock") or [])
    if low_stock_count >= 5:
        alerts.append(f"Quantidade elevada de stock baixo ({low_stock_count} itens).")

    exp7_count = len(snapshot["insights"].get("expiring_7") or [])
    if exp7_count > 0:
        alerts.append(f"Produtos com vencimento muito proximo: {exp7_count}.")

    total_revenue = snapshot["total_revenue"]
    loss_cost = snapshot["loss_cost"]
    if total_revenue > 0:
        loss_ratio = (loss_cost / total_revenue) * 100.0
        if loss_ratio >= 8.0:
            alerts.append(f"Perdas elevadas ({loss_ratio:.2f}% da receita).")

    promo_count = snapshot["promo_count"]
    if snapshot["sales_count"] > 0:
        promo_ratio = (promo_count / snapshot["sales_count"]) * 100.0
        if promo_ratio >= 40.0:
            alerts.append(f"Dependencia alta de venda promocional ({promo_ratio:.1f}%).")

    if snapshot["active_users"] <= 1:
        alerts.append("Produtividade concentrada em poucos utilizadores.")

    return alerts


def _build_actions(snapshot):
    actions = []
    insights = snapshot["insights"]
    for rec in (insights.get("recommendations_stock") or [])[:3]:
        actions.append(rec)
    for rec in (insights.get("recommendations_expiry") or [])[:3]:
        if rec not in actions:
            actions.append(rec)

    if snapshot["loss_count"] > 0:
        actions.append("Rever causas das perdas e reforcar checklist de registo com evidencia.")
    if snapshot["promo_count"] > 0:
        actions.append("Comparar margem de vendas promocionais com vendas normais por categoria.")
    if snapshot["active_users"] <= 1:
        actions.append("Redistribuir tarefas de venda e conferencias para reduzir dependencia operacional.")

    if not actions:
        actions.append("Operacao estavel. Manter monitoria diaria de vendas, stock e perdas.")

    # remover repetidos preservando ordem
    dedup = []
    seen = set()
    for item in actions:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            dedup.append(item)
    return dedup[:8]


def _build_general_local_lines(question):
    q = _sanitize_question(question).lower()
    now_dt = datetime.now()

    if any(word in q for word in ("ola", "olá", "oi", "bom dia", "boa tarde", "boa noite")):
        return ["Estou aqui. Pode fazer qualquer pergunta e respondo de forma direta."]

    if any(word in q for word in ("quem es", "quem és", "seu nome", "teu nome")):
        return ["Sou o assistente da loja e posso responder perguntas gerais e de gestao comercial."]

    if "hora" in q:
        return [f"Agora sao {now_dt.strftime('%H:%M')} (hora local do sistema)."]

    if any(word in q for word in ("data", "dia", "hoje")) and "venda" not in q:
        return [f"Hoje e {now_dt.strftime('%d/%m/%Y')}."]

    if any(word in q for word in ("o que podes", "o que pode", "ajuda", "como funcionas")):
        return ["Posso responder perguntas gerais e tambem analisar vendas, stock, perdas e produtividade."]

    return [
        "Entendi a sua pergunta.",
        "No modo local eu respondo de forma curta; com API Gemini ativa a resposta fica mais completa.",
    ]


def _build_local_answer(question, snapshot, is_business_question=True):
    if not is_business_question:
        lines = _build_general_local_lines(question)
        return {
            "summary": "Resposta local geral concluida.",
            "sections": [{"title": "Resposta Direta", "lines": lines[:3]}],
            "alerts": [],
            "actions": [],
            "route": {"domain": "general"},
        }

    route = _route_business_question(question)
    actions = _build_actions(snapshot)
    alerts = _build_alerts(snapshot)
    if route.get("ask_action") and actions:
        direct_lines = [f"Prioridade agora: {actions[0]}."]
    elif route.get("ask_alert") and alerts:
        direct_lines = [f"Alerta principal: {alerts[0]}."]
    else:
        direct_lines = _build_direct_lines(question, snapshot, route)

    sections = [{"title": "Resposta Direta", "lines": direct_lines[:3]}]

    wants_actions = bool(route.get("ask_action"))
    if wants_actions or route.get("domain") == "general":
        sections.append({"title": "Proximo Passo", "lines": actions[:2]})

    wants_alerts = bool(route.get("ask_alert"))
    if wants_alerts and alerts:
        sections.append({"title": "Alertas", "lines": alerts[:2]})

    summary = f"Analise local concluida com foco em {route.get('domain', 'geral')}."
    return {
        "summary": summary,
        "sections": sections[:3],
        "alerts": alerts,
        "actions": actions,
        "route": {
            "domain": route.get("domain", "general"),
            "ask_action": bool(route.get("ask_action")),
            "ask_alert": bool(route.get("ask_alert")),
            "ask_count": bool(route.get("ask_count")),
            "ask_value": bool(route.get("ask_value")),
            "ask_list": bool(route.get("ask_list")),
            "ask_top": bool(route.get("ask_top")),
        },
    }


def _build_api_overlay(question, snapshot, local_answer, is_business_question=True, route=None):
    api_key, _ = _get_ai_key_and_model()
    _sync_api_failure_cache_key(api_key)
    if _is_api_in_cooldown():
        return [], _QA_API_FAILURE_CACHE.get("reason") or "API temporariamente indisponivel."

    client, model = _get_ai_client()
    if not client or not model:
        return [], "API Gemini nao configurada. Defina GEMINI_API_KEY e GEMINI_MODEL."

    if not is_business_question:
        language_name = _current_ai_response_language()
        prompt = (
            f"Responda em {language_name}, de forma humana, curta e direta.\n"
            "Regras: sem markdown, sem listas longas, maximo 3 frases curtas.\n"
            f"Pergunta: {question}"
        )
        try:
            response = client.models.generate_content(model=model, contents=prompt)
            text = str(getattr(response, "text", "") or "").strip()
            if not text:
                return [], ""
            raw_lines = [line.strip("- ").strip() for line in text.splitlines() if line.strip()]
            if raw_lines:
                return raw_lines[:3], ""
            return [text[:280]], ""
        except Exception as exc:
            reason = _friendly_api_error(exc)
            _mark_api_failure(reason, api_key=api_key)
            return [], reason

    payload = {
        "periodo_dias": snapshot["lookback_days"],
        "question": question,
        "roteamento": route or {"domain": "general"},
        "metricas": {
            "vendas_total": snapshot["sales_count"],
            "receita_liquida": round(_safe_float(snapshot["total_revenue"]), 2),
            "vendas_promocionais": snapshot["promo_count"],
            "receita_promocional": round(_safe_float(snapshot["promo_revenue"]), 2),
            "perdas_qtd": snapshot["loss_count"],
            "perdas_custo": round(_safe_float(snapshot["loss_cost"]), 2),
            "utilizadores_ativos": snapshot["active_users"],
            "stock_baixo": len(snapshot["insights"].get("low_stock") or []),
            "vencimento_7dias": len(snapshot["insights"].get("expiring_7") or []),
        },
        "alertas_locais": local_answer.get("alerts", [])[:5],
        "acoes_locais": local_answer.get("actions", [])[:5],
    }

    language_name = _current_ai_response_language()

    prompt = (
        f"Responda em {language_name}.\n"
        "Atue como analista de gestao comercial. "
        "Com base no JSON, responda em JSON puro com:\n"
        "{'resumo':'texto curto', 'insights':['...'], 'acoes':['...']}\n"
        f"Os valores textuais devem estar em {language_name}. "
        "Sem markdown, sem codigo, tom humano e direto, maximo 2 insights e 1 acao.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )

    try:
        response = client.models.generate_content(model=model, contents=prompt)
        text = getattr(response, "text", "") or ""
        data = _extract_json(text)
        if isinstance(data, dict):
            lines = []
            resumo = str(data.get("resumo", "")).strip()
            if resumo:
                lines.append(resumo)
            for item in (data.get("insights") or [])[:2]:
                item_text = str(item).strip()
                if item_text:
                    lines.append(item_text)
            for item in (data.get("acoes") or [])[:1]:
                item_text = str(item).strip()
                if item_text:
                    lines.append(f"Acao: {item_text}")
            return lines[:3], ""

        raw_lines = [line.strip("- ").strip() for line in str(text).splitlines() if line.strip()]
        return raw_lines[:3], ""
    except Exception as exc:
        reason = _friendly_api_error(exc)
        _mark_api_failure(reason, api_key=api_key)
        return [], reason


def answer_management_question(question, db=None, use_api=False, lookback_days=30):
    clean_question = _sanitize_question(question)
    if not clean_question:
        return {
            "mode": "local",
            "summary": "Pergunta vazia. Escreva uma pergunta para analisar vendas, stock, perdas ou produtividade.",
            "sections": [],
            "alerts": [],
            "actions": [],
            "api_error": "",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "question": "",
        }

    requested_lookback = _resolve_lookback_days(clean_question, lookback_days)
    api_allowed = bool(use_api and can_use_ai_api())

    cache_key = f"{clean_question.lower()}|{int(api_allowed)}|{int(requested_lookback)}"
    now_ts = time.time()
    if _QA_CACHE["key"] == cache_key and (now_ts - _QA_CACHE["ts"]) <= 45 and _QA_CACHE["data"]:
        cached = dict(_QA_CACHE["data"])
        cached["cached"] = True
        return cached

    db = db or get_db()
    snapshot = _build_management_snapshot(db, lookback_days=requested_lookback)
    is_business_question = _is_business_context_question(clean_question)
    result = _build_local_answer(
        clean_question,
        snapshot,
        is_business_question=is_business_question,
    )
    result["mode"] = "local"

    if api_allowed:
        api_lines, api_error = _build_api_overlay(
            clean_question,
            snapshot,
            result,
            is_business_question=is_business_question,
            route=result.get("route") or {"domain": "general"},
        )
        if api_lines:
            result["mode"] = "hibrido"
            result["sections"].append(
                {"title": "Explicacao Avancada (API)", "lines": api_lines}
            )
        else:
            msg = api_error or "API indisponivel no momento. Mantendo resposta local."
            result["sections"].append(
                {
                    "title": "Explicacao Avancada (API)",
                    "lines": [msg],
                }
            )
            result["api_error"] = msg

    result["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result["question"] = clean_question
    result["cached"] = False

    _QA_CACHE["ts"] = now_ts
    _QA_CACHE["key"] = cache_key
    _QA_CACHE["data"] = dict(result)
    return result
