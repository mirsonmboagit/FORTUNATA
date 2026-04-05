import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from threading import Lock

from flask import Flask, jsonify, request

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from database.database import Database


def _load_config():
    config_path = BASE_DIR / "config.json"
    config = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            config = {}
    return config


CONFIG = _load_config()
API_KEY = CONFIG.get("api_key") or os.getenv("API_KEY") or ""
DB_PATH = CONFIG.get("db_path") or os.getenv("DB_PATH") or str(
    (ROOT_DIR / "database" / "inventory.db")
)
HOST = CONFIG.get("host") or "0.0.0.0"
PORT = int(CONFIG.get("port") or 8080)

app = Flask(__name__)
db = Database(db_path=DB_PATH)
db_lock = Lock()


ALLOWLIST = {
    "user_exists",
    "get_user_role",
    "get_user",
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
    "get_products_for_sale_ids",
    "get_product_by_barcode",
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


def _unauthorized():
    return jsonify({"ok": False, "error": "unauthorized"}), 401


def _check_key():
    if not API_KEY:
        return True
    return request.headers.get("X-API-KEY") == API_KEY


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


@app.get("/health")
def health():
    if not _check_key():
        return _unauthorized()
    return jsonify({"ok": True})


@app.post("/rpc")
def rpc():
    if not _check_key():
        return _unauthorized()

    payload = request.get_json(silent=True) or {}
    method = payload.get("method")
    args = payload.get("args") or []
    kwargs = payload.get("kwargs") or {}

    if method not in ALLOWLIST:
        return jsonify({"ok": False, "error": "method_not_allowed"}), 400

    fn = getattr(db, method, None)
    if not fn:
        return jsonify({"ok": False, "error": "method_not_found"}), 400

    try:
        with db_lock:
            try:
                if hasattr(db, "run_automation_tasks"):
                    db.run_automation_tasks()
            except Exception as auto_exc:
                print(f"[automation] warning: {auto_exc}")
            result = fn(*args, **kwargs)
        return jsonify({"ok": True, "result": _normalize(result)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host=HOST, port=PORT)
