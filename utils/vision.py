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


def open_optimized_camera_capture(cv2, camera_index, *, width=480, height=360, preview_fps=20):
    """Abre a camera com backend e buffer mais estaveis para preview em tempo real."""
    backend_candidates = []
    if os.name == "nt":
        directshow_backend = getattr(cv2, "CAP_DSHOW", None)
        if directshow_backend is not None:
            backend_candidates.append(directshow_backend)
        media_foundation_backend = getattr(cv2, "CAP_MSMF", None)
        if media_foundation_backend is not None:
            backend_candidates.append(media_foundation_backend)
    backend_candidates.append(getattr(cv2, "CAP_ANY", 0))

    tried_default_open = False
    for backend in backend_candidates:
        capture = None
        try:
            capture = cv2.VideoCapture(camera_index, backend)
        except TypeError:
            if tried_default_open:
                continue
            capture = cv2.VideoCapture(camera_index)
            tried_default_open = True
        except Exception:
            capture = None

        if capture is None:
            continue
        if capture.isOpened():
            try:
                fourcc_builder = getattr(cv2, "VideoWriter_fourcc", None)
                if callable(fourcc_builder):
                    capture.set(cv2.CAP_PROP_FOURCC, fourcc_builder(*"MJPG"))
            except Exception:
                pass
            try:
                buffer_size_prop = getattr(cv2, "CAP_PROP_BUFFERSIZE", None)
                if buffer_size_prop is not None:
                    capture.set(buffer_size_prop, 1)
            except Exception:
                pass
            try:
                capture.set(cv2.CAP_PROP_FRAME_WIDTH, int(width))
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, int(height))
            except Exception:
                pass
            try:
                capture.set(cv2.CAP_PROP_FPS, max(int(preview_fps), 24))
            except Exception:
                pass
            return capture

        try:
            capture.release()
        except Exception:
            pass
    return None


def build_barcode_decode_frame(cv2, frame, *, alpha=1.12, beta=8, scale=1.0):
    """Prepara uma versao mais leve do frame so para o decode."""
    scan_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    scan_frame = cv2.convertScaleAbs(scan_frame, alpha=float(alpha), beta=float(beta))
    scale = float(scale)
    if 0 < scale < 1:
        scan_frame = cv2.resize(
            scan_frame,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_AREA,
        )
    return scan_frame


def normalize_barcode_value(raw_data):
    """Normaliza o texto lido pelo pyzbar sem caracteres nao imprimiveis."""
    if raw_data is None:
        return ""
    try:
        text = raw_data.decode("utf-8", errors="ignore")
    except Exception:
        text = str(raw_data)
    return "".join(char for char in text if char.isprintable()).strip()
