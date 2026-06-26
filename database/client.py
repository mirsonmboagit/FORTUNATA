import copy
import logging
import threading
import time
from datetime import date, datetime

from utils.app_config import get_runtime_config


LOGGER = logging.getLogger(__name__)


class DatabaseClient:
    # Chamadas de leitura ficam em cache por poucos segundos.
    _CACHEABLE_RPC_TTL_SECONDS = {
        "get_products_for_sale": 1.5,
        "get_products_for_sale_page": 1.2,
        "get_products_for_sale_catalog_page": 1.2,
        "get_products_for_sale_ids": 1.2,
        "get_all_products": 2.0,
        "get_all_products_page": 1.2,
        "get_products_for_losses": 2.0,
        "get_products_for_restock": 2.0,
        "get_products_for_stock_control": 2.0,
        "get_products_by_barcode": 1.5,
        "get_products_for_filter": 10.0,
        "get_categories": 30.0,
        "get_vat_rules": 30.0,
        "get_productivity_report_data": 15.0,
        "get_cash_user_report_data": 15.0,
        "get_admin_home_snapshot": 20.0,
    }
    _MUTATING_RPC_PREFIXES = (
        "add_",
        "update_",
        "delete_",
        "replace_",
        "record_",
        "restock_",
        "reset_",
        "refund_",
        "approve_",
        "reject_",
        "clear_",
    )
    _FALLBACK_SAFE_RPC_METHODS = {
        "get_products_for_sale_page",
        "get_products_for_sale_catalog_page",
        "get_products_for_sale_ids",
        "get_all_products_page",
    }

    def __init__(self, base_url=None, api_key=None, timeout=None, config=None):
        config = dict(config or self._load_config())
        self.base_url = base_url or config.get("api_base_url") or "http://127.0.0.1:8080"
        self.api_key = api_key or config.get("api_key") or ""
        self.timeout = timeout or config.get("timeout") or 10
        self._last_error = None
        self._rpc_cache = {}
        self._rpc_cache_lock = threading.Lock()
        self._unsupported_rpc_methods = set()
        self._pool_size = int(config.get("http_pool_size") or 16)
        self._session = None
        self._availability = None
        self._availability_checked_at = 0.0
        self._availability_retry_after = 0.0
        self._availability_lock = threading.Lock()
        self._availability_ttl = float(config.get("availability_ttl") or 4.0)
        self._availability_cooldown = float(config.get("availability_cooldown") or 6.0)
        self._health_timeout = float(config.get("health_timeout") or 0.8)
        self.current_user = None
        self.current_role = None

    def set_active_user(self, username=None, role=None):
        self.current_user = username
        self.current_role = role
        self._invalidate_rpc_cache()

    def _load_config(self):
        # Le a configuracao atual da API local.
        return get_runtime_config(force_reload=True)

    def _rpc(self, method, *args, **kwargs):
        # Envia a chamada remota e centraliza cache, sessao e erros.
        if method in self._unsupported_rpc_methods:
            return None

        cached = self._get_cached_rpc_result(method, args, kwargs)
        if cached is not None:
            return cached

        session = self._ensure_session()
        if session is None:
            return None

        url = f"{self.base_url.rstrip('/')}/rpc"
        headers = self._build_headers(include_content_type=True)
        payload = {
            "method": method,
            "args": self._to_json_compatible(list(args)),
            "kwargs": self._to_json_compatible(kwargs),
            "session": {
                "username": self.current_user,
                "role": self.current_role,
            },
        }
        self._last_error = None
        try:
            resp = session.post(url, json=payload, headers=headers, timeout=self.timeout)
            data = {}
            try:
                data = resp.json() or {}
            except Exception:
                data = {}

            if resp.status_code >= 400:
                err = data.get("error") if isinstance(data, dict) else None
                if (
                    resp.status_code == 400
                    and err in {"method_not_allowed", "method_not_found"}
                    and method in self._FALLBACK_SAFE_RPC_METHODS
                ):
                    self._unsupported_rpc_methods.add(method)
                    self._last_error = f"{resp.status_code} {err}"
                    return None
                if not err:
                    err = (resp.text or "").strip() or f"HTTP {resp.status_code}"
                raise RuntimeError(f"{resp.status_code} {err}")

            if not data.get("ok"):
                raise RuntimeError(data.get("error") or "RPC error")
            result = self._normalize_result(data.get("result"))
            self._mark_available()
            self._set_cached_rpc_result(method, args, kwargs, result)
            if self._is_mutating_method(method):
                self._invalidate_rpc_cache()
            return result
        except Exception as exc:
            self._last_error = str(exc)
            self._mark_unavailable(exc)
            LOGGER.warning("RPC error (%s): %s", method, exc)
            return None

    def _ensure_session(self):
        if self._session is not None:
            return self._session
        try:
            import requests
            from requests.adapters import HTTPAdapter

            session = requests.Session()
            adapter = HTTPAdapter(
                pool_connections=self._pool_size,
                pool_maxsize=self._pool_size,
            )
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            self._session = session
            return self._session
        except Exception as exc:
            self._last_error = str(exc)
            LOGGER.warning("Session init error: %s", exc)
            return None

    def _build_headers(self, include_content_type=False):
        # Monta cabecalhos de autenticacao para a API.
        headers = {}
        if include_content_type:
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
        return headers

    def _mark_available(self):
        now = time.perf_counter()
        with self._availability_lock:
            self._availability = True
            self._availability_checked_at = now
            self._availability_retry_after = now

    def _mark_unavailable(self, reason=None):
        now = time.perf_counter()
        with self._availability_lock:
            self._availability = False
            self._availability_checked_at = now
            self._availability_retry_after = now + max(0.5, self._availability_cooldown)
        if reason:
            self._last_error = str(reason)

    def is_available(self, force=False, timeout=None):
        # Verifica a API sem repetir healthcheck a cada chamada.
        now = time.perf_counter()
        with self._availability_lock:
            available = self._availability
            checked_at = self._availability_checked_at
            retry_after = self._availability_retry_after

        if not force:
            if available is True and (now - checked_at) <= self._availability_ttl:
                return True
            if available is False and now < retry_after:
                return False

        session = self._ensure_session()
        if session is None:
            self._mark_unavailable(self._last_error or "Sessao HTTP indisponivel")
            return False

        if not hasattr(session, "get"):
            return True

        url = f"{self.base_url.rstrip('/')}/health"
        try:
            health_timeout = min(float(timeout or self.timeout), self._health_timeout)
            resp = session.get(
                url,
                headers=self._build_headers(include_content_type=False),
                timeout=health_timeout,
            )
            payload = {}
            try:
                payload = resp.json() or {}
            except Exception:
                payload = {}

            if resp.status_code >= 400:
                err = payload.get("error") if isinstance(payload, dict) else None
                if not err:
                    err = (resp.text or "").strip() or f"HTTP {resp.status_code}"
                raise RuntimeError(f"{resp.status_code} {err}")

            if isinstance(payload, dict) and payload.get("ok") is False:
                raise RuntimeError(payload.get("error") or "healthcheck_failed")

            self._last_error = None
            self._mark_available()
            return True
        except Exception as exc:
            self._mark_unavailable(exc)
            return False

    def _freeze_for_cache(self, value):
        if isinstance(value, dict):
            return tuple(sorted((k, self._freeze_for_cache(v)) for k, v in value.items()))
        if isinstance(value, (list, tuple)):
            return tuple(self._freeze_for_cache(v) for v in value)
        return value

    def _cache_key(self, method, args, kwargs):
        return (
            str(method),
            self._freeze_for_cache(args),
            self._freeze_for_cache(kwargs),
        )

    def _get_cached_rpc_result(self, method, args, kwargs):
        ttl = self._CACHEABLE_RPC_TTL_SECONDS.get(method)
        if ttl is None:
            return None
        key = self._cache_key(method, args, kwargs)
        now = time.perf_counter()
        with self._rpc_cache_lock:
            cached = self._rpc_cache.get(key)
            if not cached:
                return None
            expires_at, value = cached
            if now >= expires_at:
                self._rpc_cache.pop(key, None)
                return None
            # Devolve uma copia para evitar alteracao externa do cache.
            return copy.deepcopy(value)

    def _set_cached_rpc_result(self, method, args, kwargs, value):
        ttl = self._CACHEABLE_RPC_TTL_SECONDS.get(method)
        if ttl is None:
            return
        key = self._cache_key(method, args, kwargs)
        expires_at = time.perf_counter() + float(ttl)
        with self._rpc_cache_lock:
            self._rpc_cache[key] = (expires_at, copy.deepcopy(value))

    def _invalidate_rpc_cache(self):
        with self._rpc_cache_lock:
            self._rpc_cache.clear()

    def _is_mutating_method(self, method):
        method = str(method or "")
        return method.startswith(self._MUTATING_RPC_PREFIXES)

    def _to_json_compatible(self, value):
        if isinstance(value, datetime):
            return value.isoformat(sep=" ")
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, dict):
            return {k: self._to_json_compatible(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._to_json_compatible(v) for v in value]
        return value

    def _normalize_result(self, value):
        if isinstance(value, list):
            return [self._normalize_result(v) for v in value]
        if isinstance(value, dict):
            return {k: self._normalize_result(v) for k, v in value.items()}
        return value

    def last_error(self):
        return self._last_error

    def get_connection_label(self):
        return "API" if self.is_available() else "Local"

    def get_health_status(self, force=False, timeout=None):
        ok = bool(self.is_available(force=force, timeout=timeout))
        error = str(self._last_error or "").strip()
        message = "API local ativa."
        if not ok:
            message = "API indisponivel."
            if error:
                message = f"{message} {error}"
        return {
            "ok": ok,
            "label": "API" if ok else "Local",
            "base_url": self.base_url,
            "timeout": float(timeout or self.timeout),
            "error": error,
            "message": message,
        }

    def get_connection_status(self, force=False):
        return self.get_health_status(force=force)

    def close(self):
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None
        return None

    def setup(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    # ---------- Autenticacao / Usuarios ----------
    def user_exists(self, username, exclude_username=None):
        result = self._rpc("user_exists", username, exclude_username=exclude_username)
        return bool(result) if result is not None else False

    def get_user_role(self, username):
        return self._rpc("get_user_role", username)

    def get_user(self, username):
        return self._rpc("get_user", username)

    def get_user_data_owner(self, username):
        return self._rpc("get_user_data_owner", username)

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

    def create_user(self, username, password, role, email=None, phone=None, data_owner=None):
        result = self._rpc(
            "create_user",
            username,
            password,
            role,
            email=email,
            phone=phone,
            data_owner=data_owner,
        )
        return bool(result) if result is not None else False

    # ---------- Perguntas de seguranca ----------
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

    # ---------- Produtos / Vendas ----------
    @staticmethod
    def _catalog_identity_from_sale_row(row):
        barcode = str(row[4] if len(row) > 4 and row[4] is not None else "").strip().lower()
        if barcode:
            return f"bc:{barcode}"
        description = " ".join(str(row[1] if len(row) > 1 and row[1] is not None else "").split()).lower()
        if description:
            sale_price = round(float(row[3] or 0.0), 4)
            is_weight = 1 if (len(row) > 5 and bool(row[5])) else 0
            units_per_package = (
                int(float(row[8] or 0))
                if len(row) > 8 and row[8] not in (None, "")
                else 0
            )
            allow_pack_sale = 1 if (len(row) > 9 and bool(row[9])) else 0
            vat_rule = str(row[10] or "STANDARD").strip().upper() if len(row) > 10 else "STANDARD"
            return (
                f"desc:{description}|w:{is_weight}|p:{sale_price:.4f}|"
                f"u:{units_per_package}|a:{allow_pack_sale}|v:{vat_rule}"
            )
        return f"id:{int(row[0])}"

    @classmethod
    def _group_products_for_sale_catalog(cls, rows):
        grouped = {}
        ordered_keys = []
        for row in rows or []:
            if not row:
                continue
            catalog_key = cls._catalog_identity_from_sale_row(row)
            stock_value = float(row[2] or 0.0)
            current = grouped.get(catalog_key)
            if current is None:
                grouped[catalog_key] = {
                    "id": row[0],
                    "description": row[1],
                    "stock": stock_value,
                    "sale_price": row[3],
                    "barcode": row[4] if len(row) > 4 else None,
                    "is_sold_by_weight": bool(row[5]) if len(row) > 5 else False,
                    "expiry_date": row[6] if len(row) > 6 else None,
                    "status": row[7] if len(row) > 7 else None,
                    "units_per_package": row[8] if len(row) > 8 else None,
                    "allow_pack_sale": bool(row[9]) if len(row) > 9 else False,
                    "vat_rule_code": row[10] if len(row) > 10 else "STANDARD",
                    "catalog_key": catalog_key,
                    "lot_count": 1,
                }
                ordered_keys.append(catalog_key)
                continue

            current["stock"] += stock_value
            current["lot_count"] += 1

        result = []
        for key in ordered_keys:
            item = grouped[key]
            result.append(
                (
                    item["id"],
                    item["description"],
                    item["stock"],
                    item["sale_price"],
                    item["barcode"],
                    1 if item["is_sold_by_weight"] else 0,
                    item["expiry_date"],
                    item["status"],
                    item["units_per_package"],
                    1 if item["allow_pack_sale"] else 0,
                    item["vat_rule_code"],
                    item["catalog_key"],
                    item["lot_count"],
                )
            )
        return result

    def get_products_for_sale(self):
        return self._rpc("get_products_for_sale") or []

    def get_products_for_sale_page(self, search_text="", limit=200, offset=0, refresh_statuses=False):
        result = self._rpc(
            "get_products_for_sale_page",
            search_text=search_text,
            limit=limit,
            offset=offset,
            refresh_statuses=refresh_statuses,
        )
        if result is not None:
            return result

        rows = self.get_products_for_sale() or []
        search = (search_text or "").strip().lower()
        if search:
            rows = [
                p for p in rows
                if (
                    search in str(p[0]).lower()
                    or search in str(p[1]).lower()
                    or (len(p) > 4 and p[4] and search in str(p[4]).lower())
                )
            ]
        off = max(0, int(offset or 0))
        if limit:
            return rows[off:off + int(limit)]
        return rows[off:]

    def get_products_for_sale_catalog_page(self, search_text="", limit=200, offset=0, refresh_statuses=False):
        result = self._rpc(
            "get_products_for_sale_catalog_page",
            search_text=search_text,
            limit=limit,
            offset=offset,
            refresh_statuses=refresh_statuses,
        )
        if result is not None:
            return result

        rows = self.get_products_for_sale() or []
        search = (search_text or "").strip().lower()
        if search:
            rows = [
                p for p in rows
                if (
                    search in str(p[0]).lower()
                    or search in str(p[1]).lower()
                    or (len(p) > 4 and p[4] and search in str(p[4]).lower())
                )
            ]
        grouped_rows = self._group_products_for_sale_catalog(rows)
        off = max(0, int(offset or 0))
        if limit:
            return grouped_rows[off:off + int(limit)]
        return grouped_rows[off:]

    def get_products_for_sale_ids(self, product_ids):
        result = self._rpc("get_products_for_sale_ids", product_ids)
        if result is not None:
            return result

        ids = {int(pid) for pid in (product_ids or []) if pid is not None}
        if not ids:
            return []
        rows = self.get_products_for_sale() or []
        return [row for row in rows if int(row[0]) in ids]

    def get_product_by_barcode(self, barcode):
        return self._rpc("get_product_by_barcode", barcode)

    def get_products_by_barcode(self, barcode, include_expired=False, include_zero_stock=False):
        return self._rpc(
            "get_products_by_barcode",
            barcode,
            include_expired=include_expired,
            include_zero_stock=include_zero_stock,
        ) or []

    def get_all_products(self):
        return self._rpc("get_all_products") or []

    def get_all_products_page(
        self,
        search_text="",
        category=None,
        sold_by_weight=None,
        limit=120,
        offset=0,
    ):
        result = self._rpc(
            "get_all_products_page",
            search_text=search_text,
            category=category,
            sold_by_weight=sold_by_weight,
            limit=limit,
            offset=offset,
        )
        if result is not None:
            return result

        rows = self.get_all_products() or []
        search = (search_text or "").strip().lower()
        if search:
            rows = [
                p for p in rows
                if (
                    search in str(p[0]).lower()
                    or (len(p) > 1 and search in str(p[1]).lower())
                    or (len(p) > 11 and p[11] and search in str(p[11]).lower())
                    or (len(p) > 12 and p[12] and search in str(p[12]).lower())
                    or (len(p) > 22 and p[22] and search in str(p[22]).lower())
                )
            ]
        if category and category not in ("Todas", "Todas as Categorias"):
            rows = [p for p in rows if len(p) > 11 and p[11] == category]
        if sold_by_weight is not None:
            rows = [p for p in rows if bool(len(p) > 15 and p[15]) == bool(sold_by_weight)]

        off = max(0, int(offset or 0))
        if limit:
            return rows[off:off + int(limit)]
        return rows[off:]

    def get_product(self, product_id):
        return self._rpc("get_product", product_id)

    def get_vat_rules(self):
        return self._rpc("get_vat_rules") or []

    def replace_vat_rules(self, rules):
        result = self._rpc("replace_vat_rules", rules)
        return bool(result) if result is not None else False

    def reset_vat_rules(self):
        result = self._rpc("reset_vat_rules")
        return bool(result) if result is not None else False

    def delete_product(self, product_id, username=None):
        return self._rpc("delete_product", product_id, username=username)

    def add_sale(
        self,
        product_id,
        quantity,
        price,
        username,
        role,
        is_promotional=False,
        terminal_id=None,
        vat_rule_code=None,
    ):
        return self._rpc(
            "add_sale",
            product_id,
            quantity,
            price,
            username,
            role,
            terminal_id=terminal_id,
            is_promotional=is_promotional,
            vat_rule_code=vat_rule_code,
        )

    def record_stock_movement(self, *args, **kwargs):
        return self._rpc("record_stock_movement", *args, **kwargs)

    def restock_product(self, *args, **kwargs):
        return self._rpc("restock_product", *args, **kwargs)

    def get_sales_by_date(self, date, limit=None, offset=0):
        result = self._rpc("get_sales_by_date", date, limit=limit, offset=offset)
        if result is None:
            result = self._rpc("get_sales_by_date", date)
        rows = result or []
        off = max(0, int(offset or 0))
        if limit:
            return rows[off:off + int(limit)]
        return rows[off:]

    def get_sales_by_date_range(self, start_date, end_date, limit=None, offset=0):
        result = self._rpc(
            "get_sales_by_date_range",
            start_date,
            end_date,
            limit=limit,
            offset=offset,
        )
        if result is None:
            result = self._rpc("get_sales_by_date_range", start_date, end_date)
        rows = result or []
        off = max(0, int(offset or 0))
        if limit:
            return rows[off:off + int(limit)]
        return rows[off:]

    def get_all_sales(self, limit=None, offset=0):
        result = self._rpc("get_all_sales", limit=limit, offset=offset)
        if result is None:
            result = self._rpc("get_all_sales")
        rows = result or []
        off = max(0, int(offset or 0))
        if limit:
            return rows[off:off + int(limit)]
        return rows[off:]

    def get_recent_sales(self, limit=50):
        return self.get_all_sales(limit=limit, offset=0)

    def get_sale_details(self, sale_id):
        return self._rpc("get_sale_details", sale_id)

    def refund_sale_item(self, sale_id, quantity, reason="", username=None, role=None, terminal_id=None):
        return self._rpc(
            "refund_sale_item",
            sale_id,
            quantity,
            reason=reason,
            username=username,
            role=role,
            terminal_id=terminal_id,
        ) or {"ok": False, "message": "rpc_error"}

    def get_loss_records(self, start_dt, end_dt, limit=200):
        return self._rpc("get_loss_records", start_dt, end_dt, limit=limit) or []

    def get_restock_records(self, start_dt, end_dt, limit=300):
        return self._rpc("get_restock_records", start_dt, end_dt, limit=limit) or []

    def get_stock_movements(
        self,
        start_dt,
        end_dt,
        direction=None,
        product_id=None,
        include_sales=True,
        limit=300,
    ):
        return (
            self._rpc(
                "get_stock_movements",
                start_dt,
                end_dt,
                direction=direction,
                product_id=product_id,
                include_sales=include_sales,
                limit=limit,
            )
            or []
        )

    def get_products_with_barcodes(self):
        return self._rpc("get_products_with_barcodes") or []

    def get_known_barcodes(self):
        return self._rpc("get_known_barcodes") or []

    def get_products_for_losses(self):
        return self._rpc("get_products_for_losses") or []

    def get_products_for_restock(self, include_velocity=False, velocity_days=14):
        return (
            self._rpc(
                "get_products_for_restock",
                include_velocity=include_velocity,
                velocity_days=velocity_days,
            )
            or []
        )

    def get_products_for_stock_control(self, include_velocity=False, velocity_days=14):
        return (
            self._rpc(
                "get_products_for_stock_control",
                include_velocity=include_velocity,
                velocity_days=velocity_days,
            )
            or []
        )

    def get_products_for_filter(self):
        return self._rpc("get_products_for_filter") or []

    def get_categories(self):
        return self._rpc("get_categories") or []

    def get_sales_users_for_filter(self):
        return self._rpc("get_sales_users_for_filter") or []

    def get_report_data(self, start_date, end_date, product_id=None, category=None, seller=None):
        return self._rpc(
            "get_report_data",
            start_date,
            end_date,
            product_id=product_id,
            category=category,
            seller=seller,
        ) or []

    def get_productivity_report_data(self, start_date, end_date):
        return self._rpc(
            "get_productivity_report_data",
            start_date,
            end_date,
        ) or {}

    def get_cash_user_report_data(self, start_date, end_date, seller=None):
        return self._rpc(
            "get_cash_user_report_data",
            start_date,
            end_date,
            seller=seller,
        ) or {}

    def get_admin_home_snapshot(self, lookback_days=7):
        return self._rpc("get_admin_home_snapshot", lookback_days=lookback_days) or {}

    def add_product(self, *args, **kwargs):
        return self._rpc("add_product", *args, **kwargs)

    def update_product(self, *args, **kwargs):
        return self._rpc("update_product", *args, **kwargs)

    def get_products_by_weight(self):
        return self._rpc("get_products_by_weight") or []

    # ---------- Insights / Administracao ----------
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

    def reject_stock_movement(self, movement_id, rejected_by=None):
        return self._rpc("reject_stock_movement", movement_id, rejected_by=rejected_by)

    def delete_stock_movement(self, movement_id, deleted_by=None):
        return self._rpc("delete_stock_movement", movement_id, deleted_by=deleted_by)

    def log_action(self, username, role, action, details=""):
        return self._rpc("log_action", username, role, action, details)

    # ---------- Logs / Gerentes ----------
    def get_all_managers(self):
        return self._rpc("get_all_managers") or []

    def delete_manager(self, username):
        return self._rpc("delete_manager", username)

    def get_user_logs(self, user_filter="", action_filter="", role_filter="", limit=100, offset=0):
        result = self._rpc(
            "get_user_logs",
            user_filter,
            action_filter,
            role_filter,
            limit=limit,
            offset=offset,
        )
        if result is None:
            result = self._rpc(
                "get_user_logs",
                user_filter,
                action_filter,
                role_filter,
                limit=limit,
            )
        rows = result or []
        off = max(0, int(offset or 0))
        if limit:
            return rows[off:off + int(limit)]
        return rows[off:]

    def clear_user_logs(self):
        result = self._rpc("clear_user_logs")
        return bool(result) if result is not None else False
