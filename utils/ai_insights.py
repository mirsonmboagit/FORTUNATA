from datetime import datetime, timedelta
import json
import os
import re
import time
import random
from dotenv import load_dotenv
from kivy.app import App
from database.provider import get_db

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


def _get_ai_client():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or not genai:
        return None, None
    model = os.getenv("GEMINI_MODEL") or "models/gemini-2.5-flash"
    try:
        return genai.Client(api_key=api_key), model
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
    
    prompt = (
        f"Você é um gestor experiente de mercearia em Moçambique, "
        f"conversando com o dono do negócio. {context['saudacao']}!\n\n"
        
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
        "✅ 'Leite vence em 5 dias, pense numa promoção'\n"
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
    return bool(
        insights.get("low_stock")
        or insights.get("expiring_7")
        or insights.get("expiring_15")
    )


def get_badge_counts(insights):
    """Retorna contadores individuais para cada tipo de badge"""
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
