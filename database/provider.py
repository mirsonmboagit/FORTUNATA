from utils.app_config import get_database_path, get_runtime_config

_MISSING = object()


def _load_config():
    # Carrega a configuracao atual do backend.
    return get_runtime_config(force_reload=True)


class HybridDatabase:
    # Usa API quando estiver disponivel e SQLite local como fallback.
    def __init__(self, config=None, remote_db=None, local_db=None):
        config = dict(config or _load_config())
        self.config = config

        from database.client import DatabaseClient
        from database.database import Database

        db_path = config.get("db_path") or str(get_database_path())
        self.remote_db = remote_db if remote_db is not None else DatabaseClient(config=config)
        if local_db is not None:
            self.local_db = local_db
        elif db_path:
            self.local_db = Database(db_path=db_path)
        else:
            self.local_db = Database()

        self.connection_mode = "hybrid"
        self._last_error = ""
        self._last_backend = None

    def _remote_last_error(self):
        getter = getattr(self.remote_db, "last_error", None)
        if not callable(getter):
            return ""
        try:
            return str(getter() or "").strip()
        except Exception:
            return ""

    def _remote_available(self):
        checker = getattr(self.remote_db, "is_available", None)
        if not callable(checker):
            return True
        try:
            return bool(checker())
        except Exception:
            return False

    def using_remote(self):
        return self._remote_available()

    def get_connection_label(self):
        return self.get_connection_status().get("label") or "Local"

    def get_connection_status(self, force=False):
        # Resume o estado da ligacao para mostrar na interface.
        remote_status = {}
        getter = getattr(self.remote_db, "get_health_status", None)
        if callable(getter):
            try:
                remote_status = getter(force=force) or {}
            except Exception as exc:
                remote_status = {"ok": False, "error": str(exc)}

        remote_available = bool(remote_status.get("ok")) if remote_status else self._remote_available()
        error = str(remote_status.get("error") or self._remote_last_error() or "").strip()

        if remote_available:
            return {
                "mode": "hybrid",
                "label": "API",
                "remote_available": True,
                "error": "",
                "message": "API local ativa. O fallback SQLite continua disponivel.",
                "base_url": remote_status.get("base_url") or self.config.get("api_base_url") or "",
            }

        message = "API indisponivel. Sistema em modo local."
        if error:
            message = f"{message} {error}"
        return {
            "mode": "local",
            "label": "Local",
            "remote_available": False,
            "error": error,
            "message": message,
            "base_url": remote_status.get("base_url") or self.config.get("api_base_url") or "",
        }

    def last_error(self):
        if self._last_error:
            return self._last_error
        if self._last_backend == "local":
            return ""
        return self._remote_last_error()

    def close(self):
        self._last_error = ""
        for db in (self.remote_db, self.local_db):
            closer = getattr(db, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception as exc:
                    self._last_error = str(exc)
        return None

    def set_active_user(self, username=None, role=None):
        for db in (self.remote_db, self.local_db):
            setter = getattr(db, "set_active_user", None)
            if callable(setter):
                try:
                    setter(username, role)
                except Exception:
                    pass
        return None

    def setup(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _call_remote(self, remote_callable, *args, **kwargs):
        # Tenta executar no backend remoto e guarda o erro se falhar.
        try:
            result = remote_callable(*args, **kwargs)
        except Exception as exc:
            self._last_error = str(exc)
            marker = getattr(self.remote_db, "_mark_unavailable", None)
            if callable(marker):
                try:
                    marker(exc)
                except Exception:
                    pass
            return _MISSING

        remote_error = self._remote_last_error()
        if remote_error:
            self._last_error = remote_error
            return _MISSING

        self._last_error = ""
        self._last_backend = "remote"
        return result

    def _call_local(self, local_callable, *args, **kwargs):
        result = local_callable(*args, **kwargs)
        self._last_error = ""
        self._last_backend = "local"
        return result

    def _dispatch(self, method_name, *args, **kwargs):
        # Encaminha cada metodo para API ou banco local.
        remote_callable = getattr(self.remote_db, method_name, None)
        local_callable = getattr(self.local_db, method_name, None)

        if callable(remote_callable) and self._remote_available():
            result = self._call_remote(remote_callable, *args, **kwargs)
            if result is not _MISSING:
                return result

        if callable(local_callable):
            return self._call_local(local_callable, *args, **kwargs)

        if callable(remote_callable):
            result = self._call_remote(remote_callable, *args, **kwargs)
            return None if result is _MISSING else result

        raise AttributeError(f"'HybridDatabase' object has no attribute '{method_name}'")

    def __getattr__(self, name):
        local_attr = getattr(self.local_db, name, _MISSING)
        remote_attr = getattr(self.remote_db, name, _MISSING)

        if callable(local_attr) or callable(remote_attr):
            return lambda *args, **kwargs: self._dispatch(name, *args, **kwargs)

        if local_attr is not _MISSING:
            return local_attr
        if remote_attr is not _MISSING:
            return remote_attr
        raise AttributeError(f"'HybridDatabase' object has no attribute '{name}'")


def uses_remote_backend(db):
    if db is None:
        return False

    checker = getattr(db, "using_remote", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return False

    checker = getattr(db, "is_available", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return False

    module_name = str(getattr(db.__class__, "__module__", "") or "")
    return module_name.startswith("database.client")


def get_db():
    cfg = _load_config()
    mode = (cfg.get("db_mode") or "hybrid").lower()
    if mode in {"remote", "hybrid", "auto"}:
        return HybridDatabase(config=cfg)
    if mode == "remote_strict":
        from database.client import DatabaseClient
        return DatabaseClient(config=cfg)
    from database.database import Database
    db_path = cfg.get("db_path") or str(get_database_path())
    if db_path:
        return Database(db_path=db_path)
    return Database()
