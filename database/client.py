import json
import os

import requests


class DatabaseClient:
    def __init__(self, base_url=None, api_key=None, timeout=None, config=None):
        config = config or self._load_config()
        self.base_url = base_url or config.get("api_base_url") or "http://127.0.0.1:8080"
        self.api_key = api_key or config.get("api_key") or ""
        self.timeout = timeout or config.get("timeout") or 10
        self._last_error = None

    def _load_config(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_dir, "config.json")
        if not os.path.exists(config_path):
            return {}
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def _rpc(self, method, *args, **kwargs):
        url = f"{self.base_url.rstrip('/')}/rpc"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
        payload = {"method": method, "args": list(args), "kwargs": kwargs}
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(data.get("error") or "RPC error")
            return self._normalize_result(data.get("result"))
        except Exception as exc:
            self._last_error = str(exc)
            print(f"[DatabaseClient] RPC error ({method}): {exc}")
            return None

    def _normalize_result(self, value):
        if isinstance(value, list):
            return [self._normalize_result(v) for v in value]
        if isinstance(value, dict):
            return {k: self._normalize_result(v) for k, v in value.items()}
        return value

    def last_error(self):
        return self._last_error

    def close(self):
        return None

    def setup(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    # ---------- Auth / Users ----------
    def user_exists(self, username, exclude_username=None):
        result = self._rpc("user_exists", username, exclude_username=exclude_username)
        return bool(result) if result is not None else False

    def get_user_role(self, username):
        return self._rpc("get_user_role", username)

    def get_user(self, username):
        return self._rpc("get_user", username)

    def validate_user(self, username, password):
        return self._rpc("validate_user", username, password)

    def create_admin(self, username, password):
        result = self._rpc("create_admin", username, password)
        return bool(result) if result is not None else False

    def update_admin_credentials(self, old_username, new_username, new_password):
        result = self._rpc("update_admin_credentials", old_username, new_username, new_password)
        return bool(result) if result is not None else False

    def update_admin_profile(self, current_username, new_username=None, new_password=None):
        result = self._rpc(
            "update_admin_profile",
            current_username,
            new_username=new_username,
            new_password=new_password,
        )
        return bool(result) if result is not None else False

    def update_user_password(self, username, new_password, role=None):
        result = self._rpc("update_user_password", username, new_password, role=role)
        return bool(result) if result is not None else False

    def is_user_password_default(self, username, defaults=None):
        result = self._rpc("is_user_password_default", username, defaults=defaults)
        return bool(result) if result is not None else False

    def get_admin_usernames(self):
        result = self._rpc("get_admin_usernames")
        return result or []

    def has_admin(self):
        result = self._rpc("has_admin")
        return bool(result) if result is not None else False

    def is_admin_default(self, username, defaults=None):
        result = self._rpc("is_admin_default", username, defaults=defaults)
        return bool(result) if result is not None else False

    def create_user(self, username, password, role, email=None, phone=None):
        result = self._rpc("create_user", username, password, role, email=email, phone=phone)
        return bool(result) if result is not None else False

    # ---------- Security questions ----------
    def set_security_questions(self, username, answers):
        result = self._rpc("set_security_questions", username, answers)
        return bool(result) if result is not None else False

    def verify_security_answers(self, username, answers, max_attempts=5, lock_minutes=15):
        result = self._rpc(
            "verify_security_answers",
            username,
            answers,
            max_attempts=max_attempts,
            lock_minutes=lock_minutes,
        )
        return result or {"ok": False, "reason": "rpc_error"}

    def get_security_record(self, username):
        return self._rpc("get_security_record", username) or None

    def update_security_state(self, username, attempts, lock_until):
        result = self._rpc(
            "update_security_state",
            username,
            attempts,
            lock_until,
        )
        return bool(result) if result is not None else False

    # ---------- Products / Sales ----------
    def get_products_for_sale(self):
        return self._rpc("get_products_for_sale") or []

    def get_product_by_barcode(self, barcode):
        return self._rpc("get_product_by_barcode", barcode)

    def get_all_products(self):
        return self._rpc("get_all_products") or []

    def get_product(self, product_id):
        return self._rpc("get_product", product_id)

    def delete_product(self, product_id, username=None):
        return self._rpc("delete_product", product_id, username=username)

    def add_sale(self, product_id, quantity, price, username, role):
        return self._rpc("add_sale", product_id, quantity, price, username, role)

    def record_stock_movement(self, *args, **kwargs):
        return self._rpc("record_stock_movement", *args, **kwargs)

    def restock_product(self, *args, **kwargs):
        return self._rpc("restock_product", *args, **kwargs)

    def get_sales_by_date(self, date):
        return self._rpc("get_sales_by_date", date) or []

    def get_sales_by_date_range(self, start_date, end_date):
        return self._rpc("get_sales_by_date_range", start_date, end_date) or []

    def get_all_sales(self):
        return self._rpc("get_all_sales") or []

    def get_loss_records(self, start_dt, end_dt, limit=200):
        return self._rpc("get_loss_records", start_dt, end_dt, limit=limit) or []

    def get_restock_records(self, start_dt, end_dt, limit=300):
        return self._rpc("get_restock_records", start_dt, end_dt, limit=limit) or []

    def get_products_with_barcodes(self):
        return self._rpc("get_products_with_barcodes") or []

    def get_products_for_losses(self):
        return self._rpc("get_products_for_losses") or []

    def get_products_for_restock(self):
        return self._rpc("get_products_for_restock") or []

    def get_products_for_filter(self):
        return self._rpc("get_products_for_filter") or []

    def get_categories(self):
        return self._rpc("get_categories") or []

    def get_report_data(self, start_date, end_date, product_id=None, category=None):
        return self._rpc(
            "get_report_data",
            start_date,
            end_date,
            product_id=product_id,
            category=category,
        ) or []

    def add_product(self, *args, **kwargs):
        return self._rpc("add_product", *args, **kwargs)

    def update_product(self, *args, **kwargs):
        return self._rpc("update_product", *args, **kwargs)

    def get_products_by_weight(self):
        return self._rpc("get_products_by_weight") or []

    # ---------- Insights / Admin ----------
    def get_admin_insights(self):
        return self._rpc("get_admin_insights") or {}

    def get_admin_insights_ai(self):
        return self.get_admin_insights()

    def calculate_loss_metrics(self, start_date, end_date):
        return self._rpc("calculate_loss_metrics", start_date, end_date) or {}

    def detect_fraud_patterns(self, days_lookback=30):
        return self._rpc("detect_fraud_patterns", days_lookback=days_lookback) or []

    def get_pending_approvals(self):
        return self._rpc("get_pending_approvals") or []

    def approve_stock_movement(self, movement_id, approved_by):
        return self._rpc("approve_stock_movement", movement_id, approved_by)

    def log_action(self, username, role, action, details=""):
        return self._rpc("log_action", username, role, action, details)

    # ---------- Logs / Managers ----------
    def get_all_managers(self):
        return self._rpc("get_all_managers") or []

    def delete_manager(self, username):
        return self._rpc("delete_manager", username)

    def get_user_logs(self, user_filter="", action_filter="", role_filter="", limit=100):
        return self._rpc(
            "get_user_logs",
            user_filter,
            action_filter,
            role_filter,
            limit=limit,
        ) or []

    def clear_user_logs(self):
        result = self._rpc("clear_user_logs")
        return bool(result) if result is not None else False
