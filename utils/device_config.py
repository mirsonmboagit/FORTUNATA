from __future__ import annotations

from typing import Any

from utils.app_config import get_app_settings, save_app_settings


DEVICE_SETTINGS_DEFAULTS = {
    "physical_scanner_enabled": True,
    "physical_scanner_min_length": 6,
    "receipt_auto_print": False,
    "receipt_printer_name": "",
    "receipt_paper_width_mm": 80,
}


def _coerce_bool(value: Any, fallback: bool) -> bool:
    if value in (None, ""):
        return bool(fallback)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "sim"}


def _coerce_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(float(value))
    except Exception:
        parsed = int(fallback)
    return max(minimum, min(maximum, parsed))


def normalize_device_settings(raw_settings: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(raw_settings or {})
    normalized = dict(DEVICE_SETTINGS_DEFAULTS)
    normalized.update(raw)

    normalized["physical_scanner_enabled"] = _coerce_bool(
        normalized.get("physical_scanner_enabled"),
        DEVICE_SETTINGS_DEFAULTS["physical_scanner_enabled"],
    )
    normalized["physical_scanner_min_length"] = _coerce_int(
        normalized.get("physical_scanner_min_length"),
        DEVICE_SETTINGS_DEFAULTS["physical_scanner_min_length"],
        4,
        32,
    )
    normalized["receipt_auto_print"] = _coerce_bool(
        normalized.get("receipt_auto_print"),
        DEVICE_SETTINGS_DEFAULTS["receipt_auto_print"],
    )
    normalized["receipt_printer_name"] = str(
        normalized.get("receipt_printer_name") or ""
    ).strip()
    paper_width = _coerce_int(
        normalized.get("receipt_paper_width_mm"),
        DEVICE_SETTINGS_DEFAULTS["receipt_paper_width_mm"],
        58,
        80,
    )
    normalized["receipt_paper_width_mm"] = 58 if paper_width <= 58 else 80
    return normalized


def get_device_settings(force_reload: bool = False) -> dict[str, Any]:
    return normalize_device_settings(get_app_settings(force_reload=force_reload))


def save_device_settings(**updates: Any) -> dict[str, Any]:
    current = get_device_settings(force_reload=True)
    current.update(updates)
    normalized = normalize_device_settings(current)
    save_app_settings(normalized)
    return normalized
