"""Carga tardia de dependencias de visao computacional."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path


_CACHE = None
_ERROR = None


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _candidate_site_packages() -> list[Path]:
    root = _project_root()
    candidates = []
    for folder_name in (
        "loja_bak_pre_kivymd_restore",
        "loja_legacy",
        "loja_py314_broken_20260325",
        "loja",
    ):
        site_packages = root / folder_name / "Lib" / "site-packages"
        if site_packages.exists():
            candidates.append(site_packages)
    return candidates


def _append_fallback_paths() -> bool:
    appended = False
    for site_packages in _candidate_site_packages():
        site_text = str(site_packages)
        if site_text not in sys.path:
            sys.path.append(site_text)
            appended = True

        # Em Windows, alguns binarios do scanner dependem de DLLs
        # que vivem dentro do proprio pacote no ambiente de backup.
        if os.name == "nt":
            for dll_dir in (site_packages / "cv2", site_packages / "pyzbar"):
                if dll_dir.exists():
                    try:
                        os.add_dll_directory(str(dll_dir))
                    except Exception:
                        pass
    return appended


def _import_scanner_stack():
    last_error = None
    for attempt in range(2):
        try:
            cv2 = importlib.import_module("cv2")
            np = importlib.import_module("numpy")
            pyzbar_module = importlib.import_module("pyzbar.pyzbar")
            wrapper_module = importlib.import_module("pyzbar.wrapper")
            return cv2, np, pyzbar_module, wrapper_module
        except Exception as exc:
            last_error = exc
            if attempt == 0 and _append_fallback_paths():
                continue
            raise last_error


def get_vision_dependencies():
    """Retorna `cv2`, `numpy` e `decode` apenas quando o scanner e usado."""
    global _CACHE, _ERROR

    if _CACHE is not None:
        return _CACHE
    if _ERROR is not None:
        raise RuntimeError(_ERROR)

    try:
        cv2, np, pyzbar_module, wrapper_module = _import_scanner_stack()
        raw_decode = pyzbar_module.decode
        zbar_symbol = wrapper_module.ZBarSymbol

        # Exclui PDF417 para evitar asserts nativos do zbar sem perder
        # leitura dos formatos comuns usados pela aplicacao.
        default_symbols = tuple(
            symbol
            for symbol in zbar_symbol
            if symbol.name not in {"NONE", "PARTIAL", "PDF417"}
        )

        def decode(image, symbols=None):
            return raw_decode(image, symbols=symbols or default_symbols)

        _CACHE = (cv2, np, decode)
        return _CACHE
    except Exception as exc:
        _ERROR = (
            "Scanner indisponivel: "
            f"{exc}. Instale as dependencias 'opencv-python' e 'pyzbar' "
            "ou mantenha um ambiente de backup valido dentro do projeto."
        )
        raise RuntimeError(_ERROR) from exc
