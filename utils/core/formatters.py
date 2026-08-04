from __future__ import annotations

from datetime import datetime
from typing import Any


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def format_money(value: Any, currency: str = "MZN", symbol_position: str = "suffix") -> str:
    amount = f"{safe_float(value):,.2f}".replace(",", " ")
    currency = str(currency or "").strip()
    if not currency:
        return amount
    if str(symbol_position or "").lower() == "prefix":
        return f"{currency} {amount}"
    return f"{amount} {currency}"


def format_quantity(value: Any, *, is_weight: bool = False, weight_unit: str = "kg") -> str:
    amount = safe_float(value)
    if is_weight:
        return f"{amount:.2f} {weight_unit}"
    return str(int(round(amount)))


def format_compact_number(value: Any, empty: str = "--") -> str:
    if value is None:
        return empty
    try:
        amount = float(value)
    except Exception:
        return str(value)
    if abs(amount - round(amount)) < 0.01:
        return str(int(round(amount)))
    return f"{amount:.2f}".rstrip("0").rstrip(".")


def format_display_value(value: Any, empty: str = "--") -> str:
    if value is None:
        return empty
    try:
        amount = float(value)
    except Exception:
        return str(value)
    if isinstance(value, float):
        return f"{amount:,.2f}".replace(",", " ")
    return str(int(amount))


def format_date_dmy(value: Any, empty: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        return empty
    for parser in (
        lambda raw: datetime.fromisoformat(raw),
        lambda raw: datetime.strptime(raw, "%Y-%m-%d"),
        lambda raw: datetime.strptime(raw, "%Y-%m-%d %H:%M:%S"),
    ):
        try:
            return parser(text).strftime("%d/%m/%Y")
        except Exception:
            continue
    return text
