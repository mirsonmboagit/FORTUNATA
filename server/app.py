import logging
import os
import sys
from atexit import register as register_atexit
from datetime import date, datetime
from pathlib import Path
from threading import Event, Lock, Thread

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, current_app, jsonify, request

from utils.app_config import get_api_config, get_app_config
from utils.logging_setup import configure_runtime_logging
from utils.paths import ROOT_DIR, ensure_runtime_dirs, set_project_cwd

set_project_cwd()
ensure_runtime_dirs()
configure_runtime_logging()

from database.database import Database


LOGGER = logging.getLogger(__name__)
AUTOMATION_STARTUP_DELAY_SECONDS = 2.0
AUTOMATION_INTERVAL_SECONDS = 60.0


# Metodos que a API aceita chamar pelo RPC.
ALLOWLIST = {
    "user_exists",
    "get_user_role",
    "get_user",
    "get_user_data_owner",
    "validate_user",
    "create_admin",
    "update_admin_credentials",
    "update_admin_profile",
    "update_user_password",
    "is_user_password_default",
    "get_admin_usernames",
    "has_admin",
    "is_admin_default",
    "create_user",
    "set_security_questions",
    "verify_security_answers",
    "get_security_record",
    "update_security_state",
    "get_products_for_sale",
    "get_products_for_sale_page",
    "get_products_for_sale_catalog_page",
    "get_products_for_sale_ids",
    "get_product_by_barcode",
    "get_products_by_barcode",
    "get_all_products",
    "get_all_products_page",
    "get_product",
    "get_vat_rules",
    "delete_product",
    "add_sale",
    "record_stock_movement",
    "restock_product",
    "get_sales_by_date",
    "get_sales_by_date_range",
    "get_all_sales",
    "get_sale_details",
    "refund_sale_item",
    "get_loss_records",
    "get_restock_records",
    "get_stock_movements",
    "get_products_with_barcodes",
    "get_products_for_losses",
    "get_products_for_restock",
    "get_products_for_stock_control",
    "get_products_for_filter",
    "get_categories",
    "get_report_data",
    "get_productivity_report_data",
    "get_admin_home_snapshot",
    "add_product",
    "update_product",
    "replace_vat_rules",
    "reset_vat_rules",
    "get_products_by_weight",
    "get_admin_insights",
    "get_admin_insights_ai",
    "calculate_loss_metrics",
    "detect_fraud_patterns",
    "get_pending_approvals",
    "approve_stock_movement",
    "log_action",
    "get_all_managers",
    "delete_manager",
    "get_user_logs",
    "clear_user_logs",
}


def _build_runtime():
    app_cfg = get_app_config(force_reload=True)
    api_cfg = get_api_config(force_reload=True)
    return {
        "app": app_cfg,
        "api": api_cfg,
        "api_key": app_cfg.get("api_key") or os.getenv("API_KEY") or "",
        "db_path": app_cfg.get("db_path"),
    }


def _unauthorized():
    return jsonify({"ok": False, "error": "unauthorized"}), 401


def _is_production(runtime):
    app_cfg = (runtime or {}).get("app") or {}
    app_env = str(app_cfg.get("app_env") or os.getenv("APP_ENV") or "").strip().lower()
    return app_env in {"prod", "production"}


def _check_key():
    runtime = current_app.config.get("RUNTIME") or {}
    api_key = runtime.get("api_key") or ""
    if not api_key:
        return True
    return request.headers.get("X-API-KEY") == api_key


def _normalize(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            return bytes(value).hex()
        except Exception:
            return str(value)
    if isinstance(value, tuple):
        return [_normalize(v) for v in value]
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    return value


class _AutomationScheduler:
    # Executa tarefas automaticas do banco em segundo plano.
    def __init__(
        self,
        flask_app,
        interval_seconds=AUTOMATION_INTERVAL_SECONDS,
        startup_delay_seconds=AUTOMATION_STARTUP_DELAY_SECONDS,
    ):
        self.app = flask_app
        self.interval_seconds = max(5.0, float(interval_seconds or AUTOMATION_INTERVAL_SECONDS))
        self.startup_delay_seconds = max(0.0, float(startup_delay_seconds or 0.0))
        self._stop_event = Event()
        self._run_lock = Lock()
        self._thread = None

    def start(self):
        thread = self._thread
        if thread is not None and thread.is_alive():
            return False

        self._stop_event.clear()
        self._thread = Thread(
            target=self._loop,
            name="loja-api-automation",
            daemon=True,
        )
        self._thread.start()
        LOGGER.info(
            "automation scheduler started (delay=%.1fs interval=%.1fs)",
            self.startup_delay_seconds,
            self.interval_seconds,
        )
        return True

    def stop(self):
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        return True

    def _loop(self):
        if self._stop_event.wait(self.startup_delay_seconds):
            return
        while not self._stop_event.is_set():
            self._run_once()
            if self._stop_event.wait(self.interval_seconds):
                break

    def _run_once(self):
        if not self._run_lock.acquire(blocking=False):
            return
        try:
            db = self.app.config.get("DB_INSTANCE")
            db_lock = self.app.config.get("DB_LOCK")
            if db is None or db_lock is None or not hasattr(db, "run_automation_tasks"):
                return

            with db_lock:
                summary = db.run_automation_tasks()

            if isinstance(summary, dict):
                backup = summary.get("backup") or {}
                reconcile = summary.get("reconcile") or {}
                if backup.get("executed") or reconcile.get("executed"):
                    LOGGER.info(
                        "automation cycle executed (backup=%s reconcile=%s issues=%s)",
                        backup.get("ok"),
                        reconcile.get("ok"),
                        reconcile.get("issues"),
                    )
        except Exception:
            LOGGER.exception("automation scheduler cycle failed")
        finally:
            self._run_lock.release()


def start_background_services(flask_app):
    # Inicia servicos de apoio junto com a API.
    scheduler = flask_app.extensions.get("automation_scheduler")
    if scheduler is None:
        scheduler = _AutomationScheduler(flask_app)
        flask_app.extensions["automation_scheduler"] = scheduler
        register_atexit(scheduler.stop)
    scheduler.start()
    return scheduler


def create_app():
    # Monta o Flask, a base de dados e as rotas HTTP.
    runtime = _build_runtime()
    flask_app = Flask(__name__)
    flask_app.config["RUNTIME"] = runtime
    flask_app.config["DB_INSTANCE"] = Database(db_path=runtime["db_path"])
    flask_app.config["DB_LOCK"] = Lock()

    @flask_app.get("/health")
    def health():
        if not _check_key():
            return _unauthorized()
        payload = {
            "ok": True,
            "service": "loja-api",
            "runner": runtime["api"].get("runner") or "flask",
            "host": runtime["api"].get("host"),
            "port": runtime["api"].get("port"),
        }
        if not _is_production(runtime):
            payload["db_path"] = runtime["db_path"]
        return jsonify(payload)

    @flask_app.post("/rpc")
    def rpc():
        # Recebe chamadas remotas e executa apenas metodos permitidos.
        if not _check_key():
            return _unauthorized()

        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "error": "invalid_payload"}), 400

        method = payload.get("method")
        args = payload.get("args") or []
        kwargs = payload.get("kwargs") or {}
        session = payload.get("session") or {}

        if not isinstance(args, list):
            return jsonify({"ok": False, "error": "invalid_args"}), 400
        if not isinstance(kwargs, dict):
            return jsonify({"ok": False, "error": "invalid_kwargs"}), 400
        if not isinstance(session, dict):
            session = {}

        if method not in ALLOWLIST:
            return jsonify({"ok": False, "error": "method_not_allowed"}), 400

        db = flask_app.config["DB_INSTANCE"]
        db_lock = flask_app.config["DB_LOCK"]
        fn = getattr(db, method, None)
        if not fn:
            return jsonify({"ok": False, "error": "method_not_found"}), 400

        try:
            with db_lock:
                setter = getattr(db, "set_active_user", None)
                if callable(setter):
                    setter(session.get("username"), session.get("role"))
                result = fn(*args, **kwargs)
            return jsonify({"ok": True, "result": _normalize(result)})
        except Exception as exc:
            LOGGER.exception("RPC method failed: %s", method)
            error = "internal_error" if _is_production(runtime) else str(exc)
            return jsonify({"ok": False, "error": error}), 500

    return flask_app


app = create_app()


if __name__ == "__main__":
    runtime = _build_runtime()
    host = runtime["api"].get("host") or "0.0.0.0"
    port = int(runtime["api"].get("port") or 8080)
    start_background_services(app)
    app.run(host=host, port=port)
