"""Carga tardia de dependencias de visao computacional."""

from __future__ import annotations

import importlib


_CACHE = None
_ERROR = None


def get_vision_dependencies():
    """Retorna `cv2`, `numpy` e `decode` apenas quando o scanner e usado."""
    global _CACHE, _ERROR

    if _CACHE is not None:
        return _CACHE
    if _ERROR is not None:
        raise RuntimeError(_ERROR)

    try:
        cv2 = importlib.import_module("cv2")
        np = importlib.import_module("numpy")
        decode = importlib.import_module("pyzbar.pyzbar").decode
        _CACHE = (cv2, np, decode)
        return _CACHE
    except Exception as exc:
        _ERROR = f"Scanner indisponivel: {exc}"
        raise RuntimeError(_ERROR) from exc
