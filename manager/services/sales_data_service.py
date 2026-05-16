from __future__ import annotations

from threading import RLock


class SalesDataService:
    def __init__(self, db) -> None:
        self.db = db
        self.local_db = getattr(db, "local_db", db)
        self.remote_db = getattr(db, "remote_db", None)
        self._lock = RLock()

    def uses_local_backend(self) -> bool:
        return self.local_db is not None

    def _call_local(self, method_name: str, *args, **kwargs):
        method = getattr(self.local_db, method_name, None)
        if not callable(method):
            raise AttributeError(f"Local backend does not implement '{method_name}'")
        with self._lock:
            return method(*args, **kwargs)

    def get_connection_status(self, force: bool = False) -> dict:
        status_getter = getattr(self.db, "get_connection_status", None)
        if callable(status_getter):
            try:
                return status_getter(force=force) or {}
            except Exception as exc:
                return {
                    "label": "Local" if self.uses_local_backend() else "API",
                    "error": str(exc),
                }

        label_getter = getattr(self.db, "get_connection_label", None)
        if callable(label_getter):
            try:
                return {"label": label_getter() or "Local"}
            except Exception:
                pass

        return {"label": "Local" if self.uses_local_backend() else "API"}

    def get_products_for_sale_page(self, **kwargs):
        return self._call_local("get_products_for_sale_page", **kwargs) or []

    def get_products_for_sale_ids(self, product_ids):
        return self._call_local("get_products_for_sale_ids", product_ids) or []

    def find_product_by_barcode(self, barcode_value, products_by_id=None):
        lookup = getattr(self.local_db, "find_product_by_barcode_fast", None)
        if not callable(lookup):
            lookup = getattr(self.local_db, "get_product_by_barcode", None)
        if not callable(lookup):
            return None

        with self._lock:
            product = lookup(barcode_value)
        if not product:
            return None

        product_id = product[0]
        live_product = (products_by_id or {}).get(product_id)
        if live_product is not None:
            return live_product

        rows = self.get_products_for_sale_ids([product_id])
        return rows[0] if rows else product

    def get_vat_rules(self):
        return self._call_local("get_vat_rules") or []

    def calculate_vat_breakdown(self, *args, **kwargs):
        calculator = getattr(self.local_db, "calculate_vat_breakdown", None)
        if not callable(calculator):
            return None
        with self._lock:
            return calculator(*args, **kwargs)

    def get_admin_home_snapshot(self, **kwargs):
        return self._call_local("get_admin_home_snapshot", **kwargs) or {}

    def add_sale(self, *args, **kwargs):
        return self._call_local("add_sale", *args, **kwargs)

    def log_action(self, *args, **kwargs):
        logger = getattr(self.local_db, "log_action", None)
        if not callable(logger):
            return None
        with self._lock:
            return logger(*args, **kwargs)
