from __future__ import annotations

from typing import Any

from utils.app_config import get_app_settings, save_app_settings


DEFAULT_SYSTEM_NAME = "SIGE MPE"
MAX_SYSTEM_NAME_LENGTH = 48


def normalize_system_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return DEFAULT_SYSTEM_NAME
    return " ".join(text.split())[:MAX_SYSTEM_NAME_LENGTH]


def get_system_name(force_reload: bool = False) -> str:
    settings = get_app_settings(force_reload=force_reload)
    return normalize_system_name(settings.get("system_name"))


def save_system_name(value: Any) -> str:
    name = normalize_system_name(value)
    save_app_settings({"system_name": name})
    return name
