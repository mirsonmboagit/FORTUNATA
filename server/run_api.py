import sys
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.app_config import get_api_config
from utils.logging_setup import configure_runtime_logging
from utils.paths import ensure_runtime_dirs, set_project_cwd

set_project_cwd()
ensure_runtime_dirs()
configure_runtime_logging()

from server.app import app, start_background_services

LOGGER = logging.getLogger(__name__)


def main():
    api_cfg = get_api_config(force_reload=True)
    host = api_cfg.get("host") or "0.0.0.0"
    port = int(api_cfg.get("port") or 8080)
    runner = str(api_cfg.get("runner") or "waitress").strip().lower()
    LOGGER.info("starting sige-mpe-api runner=%s host=%s port=%s", runner, host, port)
    start_background_services(app)
    LOGGER.info("background services ready")

    if runner == "flask":
        LOGGER.info("starting flask server on http://%s:%s", host, port)
        print(f"[sige-mpe-api] flask em http://{host}:{port}", flush=True)
        app.run(host=host, port=port)
        return

    try:
        from waitress import serve
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Waitress nao esta instalado. Instale o pacote 'waitress' "
            "ou altere 'runner' para 'flask' em config/api.json durante o desenvolvimento."
        ) from exc

    LOGGER.info("starting waitress server on http://%s:%s", host, port)
    print(f"[sige-mpe-api] waitress em http://{host}:{port}", flush=True)
    serve(
        app,
        host=host,
        port=port,
        threads=int(api_cfg.get("threads") or 8),
        connection_limit=int(api_cfg.get("connection_limit") or 100),
        channel_timeout=int(api_cfg.get("channel_timeout") or 120),
        cleanup_interval=int(api_cfg.get("cleanup_interval") or 30),
        ident=str(api_cfg.get("ident") or "sige-mpe-api"),
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
