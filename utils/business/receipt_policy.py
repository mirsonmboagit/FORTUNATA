from __future__ import annotations


def can_emit_receipt(last_completed_receipt_data) -> bool:
    """Only completed sales can originate a receipt."""
    return bool(last_completed_receipt_data)


def resolve_receipt_data_for_emission(last_completed_receipt_data):
    """Returns receipt data only when there is a completed sale."""
    if not can_emit_receipt(last_completed_receipt_data):
        return None
    return last_completed_receipt_data
