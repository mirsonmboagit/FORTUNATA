import os
import sys
from time import perf_counter


def _env_flag(name, legacy_name=None):
    value = str(os.environ.get(name, "")).strip().lower()
    if not value and legacy_name:
        value = str(os.environ.get(legacy_name, "")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _is_server_process():
    if _env_flag("SIGEMPE_SERVER_MODE", "MERCEARIA_SERVER_MODE"):
        return True
    argv = " ".join(str(arg).strip().lower() for arg in sys.argv[1:] if arg)
    if not argv:
        return False
    markers = (
        "waitress",
        "uvicorn",
        "gunicorn",
        "--listen",
        "--port",
        "server.app:app",
    )
    return any(marker in argv for marker in markers)


def should_log_perf():
    if _env_flag("SIGEMPE_PERF_LOGS", "MERCEARIA_PERF_LOGS"):
        return True
    if _is_server_process():
        return False
    # Nao importe Kivy apenas para decidir se um log deve ser escrito. A
    # primeira importacao inicializa providers e atrasava a primeira consulta.
    kivy_app_module = sys.modules.get("kivy.app")
    app_class = getattr(kivy_app_module, "App", None) if kivy_app_module else None
    try:
        app = app_class.get_running_app() if app_class is not None else None
    except Exception:
        app = None
    return bool(app and getattr(app, "debug_mode", False))


def should_log_debug():
    return _env_flag("SIGEMPE_DEBUG_LOGS", "MERCEARIA_DEBUG_LOGS") or should_log_perf()


def perf_start():
    return perf_counter()


def perf_log(label, started_at, details=""):
    elapsed_ms = (perf_counter() - started_at) * 1000.0
    if not should_log_perf():
        return elapsed_ms
    if details:
        print(f"PERF: {label} took {elapsed_ms:.1f}ms | {details}")
        return elapsed_ms
    print(f"PERF: {label} took {elapsed_ms:.1f}ms")
    return elapsed_ms
