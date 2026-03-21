import os
from time import perf_counter


def _env_flag(name):
    value = str(os.environ.get(name, "")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def should_log_perf():
    if _env_flag("MERCEARIA_PERF_LOGS"):
        return True
    try:
        from kivy.app import App

        app = App.get_running_app()
    except Exception:
        app = None
    return bool(app and getattr(app, "debug_mode", False))


def should_log_debug():
    return _env_flag("MERCEARIA_DEBUG_LOGS") or should_log_perf()


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
