from datetime import date, datetime


ALERT_LEVEL_NONE = "none"
ALERT_LEVEL_LEVE = "leve"
ALERT_LEVEL_MEDIO = "medio"
ALERT_LEVEL_ALTO = "alto"
ALERT_LEVEL_CRITICO = "critico"
ALERT_LEVEL_VENCIDO = "vencido"


EXPIRY_ALERT_WINDOW_DAYS = 90


_DEFAULT_ALERT = {
    "level": ALERT_LEVEL_NONE,
    "label": "Sem alerta",
    "short_label": "--",
    "days_left": None,
    "is_alert": False,
    "is_expired": False,
    "color_rgba": (0.45, 0.50, 0.55, 1),
    "color_hex": "#73808C",
}


ALERT_COLORS = {
    ALERT_LEVEL_NONE: {"rgba": (0.45, 0.50, 0.55, 1), "hex": "#73808C"},
    ALERT_LEVEL_LEVE: {"rgba": (0.50, 0.50, 0.50, 1), "hex": "#808080"},
    ALERT_LEVEL_MEDIO: {"rgba": (0.92, 0.76, 0.10, 1), "hex": "#EBC21A"},
    ALERT_LEVEL_ALTO: {"rgba": (0.95, 0.53, 0.10, 1), "hex": "#F2861A"},
    ALERT_LEVEL_CRITICO: {"rgba": (0.86, 0.22, 0.20, 1), "hex": "#DB3833"},
    ALERT_LEVEL_VENCIDO: {"rgba": (0.45, 0.07, 0.07, 1), "hex": "#731212"},
}


def _parse_expiry_date(value):
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except Exception:
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except Exception:
            continue
    return None


def evaluate_expiry_alert(expiry_date, today=None):
    """
    Calcula nivel de alerta de vencimento baseado em dias restantes.

    Regras:
    - 90-61 dias: leve
    - 60-31 dias: medio
    - 30-8 dias: alto
    - 7-1 dias: critico
    - <= 0 dias: vencido
    """
    expiry = _parse_expiry_date(expiry_date)
    if not expiry:
        return dict(_DEFAULT_ALERT)

    today_date = today or date.today()
    days_left = (expiry - today_date).days

    if days_left <= 0:
        level = ALERT_LEVEL_VENCIDO
        label = "Vencido"
        short = "Vencido"
    elif days_left <= 7:
        level = ALERT_LEVEL_CRITICO
        label = "Critico"
        short = f"Critico ({days_left}d)"
    elif days_left <= 30:
        level = ALERT_LEVEL_ALTO
        label = "Alto"
        short = f"Alto ({days_left}d)"
    elif days_left <= 60:
        level = ALERT_LEVEL_MEDIO
        label = "Medio"
        short = f"Medio ({days_left}d)"
    elif days_left <= EXPIRY_ALERT_WINDOW_DAYS:
        level = ALERT_LEVEL_LEVE
        label = "Leve"
        short = f"Leve ({days_left}d)"
    else:
        return {
            "level": ALERT_LEVEL_NONE,
            "label": "Sem alerta",
            "short_label": f"{days_left}d",
            "days_left": days_left,
            "is_alert": False,
            "is_expired": False,
            "color_rgba": ALERT_COLORS[ALERT_LEVEL_NONE]["rgba"],
            "color_hex": ALERT_COLORS[ALERT_LEVEL_NONE]["hex"],
        }

    color = ALERT_COLORS[level]
    return {
        "level": level,
        "label": label,
        "short_label": short,
        "days_left": days_left,
        "is_alert": True,
        "is_expired": level == ALERT_LEVEL_VENCIDO,
        "color_rgba": color["rgba"],
        "color_hex": color["hex"],
    }


def get_expiry_level_counts(alerts):
    counts = {
        ALERT_LEVEL_LEVE: 0,
        ALERT_LEVEL_MEDIO: 0,
        ALERT_LEVEL_ALTO: 0,
        ALERT_LEVEL_CRITICO: 0,
        ALERT_LEVEL_VENCIDO: 0,
        "total": 0,
    }
    for alert in alerts or []:
        level = (alert or {}).get("level")
        if level in counts:
            counts[level] += 1
            if level != ALERT_LEVEL_NONE:
                counts["total"] += 1
    return counts
