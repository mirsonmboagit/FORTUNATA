import logging
import os

from utils.app_config import get_app_config


_LOGGING_CONFIGURED = False

def _resolve_level(level_name, fallback):
    if not level_name:
        return fallback
    return getattr(logging, str(level_name).upper(), fallback)


def configure_runtime_logging():
    """Configure console logging once, with sane defaults for dev/prod."""
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    cfg = get_app_config()
    app_env = (
        os.getenv("APP_ENV")
        or cfg.get("app_env")
        or "development"
    ).strip().lower()
    is_production = app_env in {"prod", "production"}

    default_level = logging.WARNING if is_production else logging.INFO
    level = _resolve_level(
        os.getenv("LOG_LEVEL") or cfg.get("log_level"),
        default_level,
    )

    # Set defaults before Kivy starts so we do not get DEBUG spam.
    os.environ.setdefault("KIVY_LOG_MODE", "MIXED")
    os.environ.setdefault("KIVY_LOG_LEVEL", "warning" if is_production else "info")

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    else:
        root_logger.setLevel(level)

    # Keep useful app logs, but silence noisy HTTP connection DEBUG traces.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("kivy").setLevel(logging.WARNING if is_production else logging.INFO)

    _LOGGING_CONFIGURED = True
