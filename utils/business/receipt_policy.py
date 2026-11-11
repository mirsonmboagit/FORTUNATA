from __future__ import annotations

from typing import Any

from utils.config.app_config import get_app_settings


def can_emit_receipt(last_completed_receipt_data) -> bool:
    """Only completed sales can originate a receipt."""
    return bool(last_completed_receipt_data)


def resolve_receipt_data_for_emission(last_completed_receipt_data):
    """Returns receipt data only when there is a completed sale."""
    if not can_emit_receipt(last_completed_receipt_data):
        return None
    return last_completed_receipt_data


RECEIPT_BUSINESS_FIELDS = (
    "receipt_nuit",
    "receipt_address",
    "receipt_phone",
    "receipt_street",
)


def get_receipt_business_data(force_reload: bool = False) -> dict[str, str]:
    """Devolve os dados comerciais opcionais que aparecem no recibo."""
    settings = get_app_settings(force_reload=force_reload)
    return {
        field: str(settings.get(field) or "").strip()
        for field in RECEIPT_BUSINESS_FIELDS
    }


def apply_receipt_business_data(receipt_data: dict[str, Any] | None) -> dict[str, Any]:
    """Acrescenta os dados atuais da loja sem substituir dados historicos."""
    payload = dict(receipt_data or {})
    for field, value in get_receipt_business_data().items():
        if not str(payload.get(field) or "").strip():
            payload[field] = value
    return payload
