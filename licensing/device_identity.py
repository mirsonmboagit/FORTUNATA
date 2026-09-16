"""Identidade local e estavel do computador, sem enviar identificadores crus."""

from __future__ import annotations

import hashlib
import os
import platform
import uuid


def _windows_machine_guid() -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
            value, _kind = winreg.QueryValueEx(key, "MachineGuid")
            return str(value or "").strip()
    except Exception:
        return ""


def device_fingerprint() -> str:
    """Devolve um resumo que muda quando a instalacao vai para outra maquina.

    O resumo e incluido no pedido de licenca offline. Nem o nome do computador
    nem o MachineGuid sao transmitidos automaticamente.
    """

    machine_anchor = _windows_machine_guid()
    if not machine_anchor:
        machine_anchor = "|".join((platform.node(), str(uuid.getnode()), platform.platform()))
    payload = f"SIGE-MPE-LICENSE-V1|{machine_anchor}".encode("utf-8", errors="ignore")
    return hashlib.sha256(payload).hexdigest()


def device_label(fingerprint: str | None = None) -> str:
    """Nome neutro mostrado ao superadmin, sem expor o hostname do cliente."""

    value = str(fingerprint or device_fingerprint())
    return f"Computador {value[:8].upper()}"
