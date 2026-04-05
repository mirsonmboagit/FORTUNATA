from datetime import date, datetime


VAT_PRICE_MODE_INCLUSIVE = "INCLUSIVE"
DEFAULT_VAT_RULE_CODE = "STANDARD"


# Regras-base de IVA usadas pela app.
# Mantidas por periodo para preservar vendas historicas quando a taxa muda.
VAT_RULES = (
    {
        "code": "STANDARD",
        "label": "Taxa geral",
        "short_label": "IVA 17%",
        "rate_percent": 17.0,
        "taxable_ratio": 1.0,
        "effective_from": "1900-01-01",
        "effective_to": "2022-12-31",
        "legal_reference": "Regime anterior a Lei n. 22/2022",
        "price_mode": VAT_PRICE_MODE_INCLUSIVE,
    },
    {
        "code": "STANDARD",
        "label": "Taxa geral",
        "short_label": "IVA 16%",
        "rate_percent": 16.0,
        "taxable_ratio": 1.0,
        "effective_from": "2023-01-01",
        "effective_to": None,
        "legal_reference": "Lei n. 22/2022",
        "price_mode": VAT_PRICE_MODE_INCLUSIVE,
    },
    {
        "code": "REDUCED_5",
        "label": "Taxa reduzida",
        "short_label": "IVA 5%",
        "rate_percent": 5.0,
        "taxable_ratio": 1.0,
        "effective_from": "2023-01-01",
        "effective_to": None,
        "legal_reference": "Lei n. 22/2022",
        "description": "Servicos privados de saude e educacao.",
        "price_mode": VAT_PRICE_MODE_INCLUSIVE,
    },
    {
        "code": "EXEMPT",
        "label": "Isento",
        "short_label": "Isento",
        "rate_percent": 0.0,
        "taxable_ratio": 0.0,
        "effective_from": "1900-01-01",
        "effective_to": None,
        "legal_reference": "CIVA art. 9 / bens e servicos isentos",
        "price_mode": VAT_PRICE_MODE_INCLUSIVE,
    },
    {
        "code": "TEMP_ESSENTIAL_2025",
        "label": "Isencao temporaria",
        "short_label": "Isento 2025",
        "rate_percent": 0.0,
        "taxable_ratio": 0.0,
        "effective_from": "2023-01-01",
        "effective_to": "2025-12-31",
        "legal_reference": "Prorrogacao ate 31/12/2025",
        "description": "Acucar, oleos alimentares e saboes.",
        "price_mode": VAT_PRICE_MODE_INCLUSIVE,
    },
)


VAT_RULE_CHOICES = (
    {
        "code": "STANDARD",
        "label": "Taxa geral",
        "hint": "Aplica a taxa geral em vigor na data da venda.",
    },
    {
        "code": "REDUCED_5",
        "label": "Taxa reduzida 5%",
        "hint": "Saude e educacao privada.",
    },
    {
        "code": "EXEMPT",
        "label": "Isento",
        "hint": "Bens e servicos isentos pelo CIVA.",
    },
    {
        "code": "TEMP_ESSENTIAL_2025",
        "label": "Isencao temporaria 2025",
        "hint": "Acucar, oleos alimentares e saboes ate 31/12/2025.",
    },
)


def normalize_reference_date(value=None):
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return date.today()
    for parser in (datetime.fromisoformat,):
        try:
            return parser(text).date()
        except Exception:
            pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except Exception:
            continue
    return date.today()


def _date_in_window(reference_date, effective_from, effective_to):
    ref_date = normalize_reference_date(reference_date)
    start = normalize_reference_date(effective_from)
    if ref_date < start:
        return False
    if effective_to:
        end = normalize_reference_date(effective_to)
        if ref_date > end:
            return False
    return True


def _normalize_rule_entry(rule):
    if isinstance(rule, dict):
        return dict(rule)
    if isinstance(rule, (list, tuple)):
        return {
            "code": rule[0],
            "label": rule[1],
            "short_label": rule[2],
            "rate_percent": rule[3],
            "taxable_ratio": rule[4],
            "effective_from": rule[5],
            "effective_to": rule[6],
            "legal_reference": rule[7],
            "description": rule[8],
            "price_mode": rule[9] if len(rule) > 9 else VAT_PRICE_MODE_INCLUSIVE,
        }
    return {}


def _rules_source(rules=None):
    source = list(rules or VAT_RULES)
    normalized = [_normalize_rule_entry(rule) for rule in source]
    return [rule for rule in normalized if rule.get("code")]


def resolve_vat_rule(rule_code=None, reference_date=None, rules=None):
    code = (rule_code or DEFAULT_VAT_RULE_CODE or "").strip().upper()
    ref_date = normalize_reference_date(reference_date)
    source_rules = _rules_source(rules)
    candidates = [rule for rule in source_rules if rule["code"] == code]
    if not candidates and code != DEFAULT_VAT_RULE_CODE:
        candidates = [rule for rule in source_rules if rule["code"] == DEFAULT_VAT_RULE_CODE]
        code = DEFAULT_VAT_RULE_CODE

    for rule in sorted(
        candidates,
        key=lambda item: normalize_reference_date(item["effective_from"]),
        reverse=True,
    ):
        if _date_in_window(ref_date, rule["effective_from"], rule.get("effective_to")):
            resolved = dict(rule)
            resolved["code"] = code
            resolved["reference_date"] = ref_date.isoformat()
            return resolved

    fallback_pool = [rule for rule in source_rules if rule["code"] == DEFAULT_VAT_RULE_CODE] or list(VAT_RULES)
    fallback = next(rule for rule in fallback_pool if rule["code"] == DEFAULT_VAT_RULE_CODE)
    resolved = dict(fallback)
    resolved["reference_date"] = ref_date.isoformat()
    return resolved


def get_vat_choice(code):
    wanted = (code or DEFAULT_VAT_RULE_CODE or "").strip().upper()
    for choice in VAT_RULE_CHOICES:
        if choice["code"] == wanted:
            return dict(choice)
    return dict(VAT_RULE_CHOICES[0])


def get_vat_choice_label(code):
    choice = get_vat_choice(code)
    return choice["label"]


def describe_vat_choice(code, reference_date=None):
    choice = get_vat_choice(code)
    rule = resolve_vat_rule(code, reference_date=reference_date)
    rate = float(rule.get("rate_percent") or 0.0)
    if rule.get("code") != choice["code"]:
        return f"{choice['label']} | Sem vigencia nesta data; aplica taxa geral."
    if rate <= 0:
        active_text = "Ativo sem IVA na data da venda."
    else:
        active_text = f"Ativo a {rate:.2f}% na data da venda."
    return f"{choice['label']} | {active_text}"


def compute_vat_breakdown(unit_price, quantity=1.0, rule_code=None, reference_date=None, rules=None):
    rule = resolve_vat_rule(rule_code, reference_date=reference_date, rules=rules)
    qty = float(quantity or 0.0)
    price = float(unit_price or 0.0)
    rate = max(0.0, float(rule.get("rate_percent") or 0.0))
    taxable_ratio = max(0.0, float(rule.get("taxable_ratio") or 0.0))
    price_mode = str(rule.get("price_mode") or VAT_PRICE_MODE_INCLUSIVE).strip().upper()
    raw_total = round(price * qty, 2)

    if raw_total <= 0 or rate <= 0 or taxable_ratio <= 0:
        net_total = raw_total
        vat_amount = 0.0
        gross_total = raw_total
    else:
        factor = 1.0 + ((rate / 100.0) * taxable_ratio)
        if factor <= 0:
            net_total = raw_total
            vat_amount = 0.0
            gross_total = raw_total
        elif price_mode == "EXCLUSIVE":
            net_total = raw_total
            vat_amount = round(net_total * ((rate / 100.0) * taxable_ratio), 2)
            gross_total = round(net_total + vat_amount, 2)
        else:
            gross_total = raw_total
            net_total = round(gross_total / factor, 2)
            vat_amount = round(gross_total - net_total, 2)

    return {
        "rule_code": rule["code"],
        "rule_label": rule.get("label") or get_vat_choice_label(rule["code"]),
        "short_label": rule.get("short_label") or get_vat_choice_label(rule["code"]),
        "legal_reference": rule.get("legal_reference") or "",
        "reference_date": rule.get("reference_date"),
        "price_mode": price_mode or VAT_PRICE_MODE_INCLUSIVE,
        "rate_percent": round(rate, 2),
        "taxable_ratio": round(taxable_ratio, 4),
        "quantity": qty,
        "unit_price": round(price, 2),
        "net_total": net_total,
        "vat_amount": round(vat_amount, 2),
        "gross_total": gross_total,
        "is_exempt": rate <= 0 or taxable_ratio <= 0,
    }
