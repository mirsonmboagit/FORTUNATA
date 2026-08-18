"""Estado persistente que pertence apenas ao cliente Manager Mobile."""

from __future__ import annotations

from uuid import uuid4

from utils.config.app_config import get_app_settings, save_app_settings


MOBILE_TERMINAL_SETTING = "manager_mobile_terminal_id"


def get_mobile_terminal_id() -> str:
    """Devolve um identificador estavel, sem usar identificadores do telefone.

    O id e privado da app e serve apenas para separar sessoes de caixa entre
    terminais. Nao recolhe IMEI, numero de telefone ou qualquer dado pessoal.
    """
    settings = get_app_settings(force_reload=False)
    current = str(settings.get(MOBILE_TERMINAL_SETTING) or "").strip().upper()
    if current.startswith("MOBILE-") and len(current) >= 12:
        return current

    terminal_id = f"MOBILE-{uuid4().hex[:8].upper()}"
    save_app_settings({MOBILE_TERMINAL_SETTING: terminal_id})
    return terminal_id
