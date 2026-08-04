from __future__ import annotations

import json
import os
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from utils.config.app_config import get_api_config, get_app_config
from utils.config.paths import DB_BACKUP_DIR, LOGS_DIR, relativize_to_root, resolve_path


BACKUP_STALE_HOURS = 48
DATABASE_LARGE_BYTES = 512 * 1024 * 1024


def _file_size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


def _latest_file(root: Path, suffixes: tuple[str, ...]) -> dict[str, Any] | None:
    if not root.exists():
        return None

    latest: Path | None = None
    latest_mtime = 0.0
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if latest is None or mtime > latest_mtime:
            latest = path
            latest_mtime = mtime

    if latest is None:
        return None

    return {
        "path": relativize_to_root(latest),
        "modified_at": datetime.fromtimestamp(latest_mtime).isoformat(timespec="seconds"),
        "size_bytes": _file_size(latest),
    }


def _automation_state(db: Any) -> dict[str, str]:
    cursor = getattr(db, "cursor", None)
    if cursor is None:
        return {}
    try:
        cursor.execute("SELECT state_key, state_value FROM automation_state")
        return {str(key): str(value or "") for key, value in cursor.fetchall()}
    except Exception:
        return {}


def _sqlite_integrity(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {"ok": False, "reason": "missing"}
    try:
        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        result = str((row or [""])[0]).lower()
        return {"ok": result == "ok", "reason": result or "empty"}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def _api_health(base_url: str, api_key: str = "", timeout: float = 0.8) -> dict[str, Any]:
    base_url = str(base_url or "").strip().rstrip("/")
    if not base_url:
        return {"ok": False, "reason": "missing_url"}

    request = urllib.request.Request(f"{base_url}/health")
    if api_key:
        request.add_header("X-API-KEY", api_key)

    try:
        with urllib.request.urlopen(request, timeout=float(timeout or 0.8)) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
            payload = json.loads(body) if body else {}
            return {
                "ok": bool(payload.get("ok", response.status < 400)),
                "status_code": int(response.status),
                "reason": str(payload.get("error") or "ok"),
            }
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status_code": int(exc.code), "reason": "http_error"}
    except Exception as exc:
        return {"ok": False, "status_code": None, "reason": exc.__class__.__name__}


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def assess_system_alerts(status: dict[str, Any], now: datetime | None = None) -> list[dict[str, str]]:
    now = now or datetime.now()
    alerts: list[dict[str, str]] = []

    db_info = status.get("database") or {}
    db_integrity = db_info.get("integrity") or {}
    if not db_info.get("exists"):
        alerts.append({
            "level": "critical",
            "code": "database_missing",
            "message": "Base de dados nao encontrada.",
        })
    elif db_integrity.get("ok") is False:
        alerts.append({
            "level": "critical",
            "code": "database_integrity",
            "message": "Integridade SQLite com problema.",
        })

    if int(db_info.get("size_bytes") or 0) >= DATABASE_LARGE_BYTES:
        alerts.append({
            "level": "warning",
            "code": "database_large",
            "message": "Base de dados grande; considere manutencao e backups mais frequentes.",
        })

    api_info = status.get("api") or {}
    api_health = api_info.get("health") or {}
    db_mode = str(status.get("db_mode") or "").lower()
    if db_mode in {"remote", "hybrid"} and api_health.get("ok") is False:
        alerts.append({
            "level": "warning",
            "code": "api_offline",
            "message": "API local indisponivel para o modo atual.",
        })

    if str(status.get("app_env") or "").lower() in {"prod", "production"} and not api_info.get("has_api_key"):
        alerts.append({
            "level": "critical",
            "code": "api_key_missing",
            "message": "API key ausente em ambiente de producao.",
        })

    automation = status.get("automation") or {}
    last_backup = _parse_iso_datetime(automation.get("last_backup_run"))
    latest_backup = (status.get("files") or {}).get("latest_backup") or {}
    latest_backup_time = _parse_iso_datetime(latest_backup.get("modified_at"))
    backup_reference = last_backup or latest_backup_time
    if backup_reference is None:
        alerts.append({
            "level": "warning",
            "code": "backup_missing",
            "message": "Nenhum backup encontrado ou registado.",
        })
    elif now - backup_reference > timedelta(hours=BACKUP_STALE_HOURS):
        alerts.append({
            "level": "warning",
            "code": "backup_stale",
            "message": "Backup esta antigo; crie um backup manual.",
        })

    backup_status = str(automation.get("last_backup_status") or "").strip().lower()
    if backup_status and backup_status not in {"ok"} and not backup_status.startswith("ok:"):
        alerts.append({
            "level": "warning",
            "code": "backup_status",
            "message": "Ultimo backup automatico reportou problema.",
        })

    if not alerts:
        alerts.append({
            "level": "ok",
            "code": "system_ok",
            "message": "Nenhum alerta operacional encontrado.",
        })

    return alerts


def collect_system_status(db: Any = None, include_api_health: bool = True) -> dict[str, Any]:
    app_cfg = get_app_config(force_reload=True)
    api_cfg = get_api_config(force_reload=True)

    db_path = resolve_path(getattr(db, "db_path", None) or app_cfg.get("db_path"))
    api_key = str(app_cfg.get("api_key") or os.getenv("API_KEY") or "").strip()
    automation = _automation_state(db) if db is not None else {}

    status = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "app_env": str(app_cfg.get("app_env") or "development"),
        "db_mode": str(app_cfg.get("db_mode") or "local"),
        "database": {
            "path": relativize_to_root(db_path),
            "exists": db_path.exists(),
            "size_bytes": _file_size(db_path),
            "integrity": _sqlite_integrity(db_path),
        },
        "api": {
            "base_url": str(app_cfg.get("api_base_url") or ""),
            "host": str(api_cfg.get("host") or ""),
            "port": int(api_cfg.get("port") or 0),
            "runner": str(api_cfg.get("runner") or ""),
            "has_api_key": bool(api_key),
            "health": {"ok": None, "reason": "not_checked"},
        },
        "automation": {
            "last_backup_run": automation.get("auto_backup_last_run", ""),
            "last_backup_status": automation.get("auto_backup_last_status", ""),
            "last_reconcile_run": automation.get("auto_reconcile_last_run", ""),
            "last_reconcile_status": automation.get("auto_reconcile_last_status", ""),
        },
        "files": {
            "latest_backup": _latest_file(DB_BACKUP_DIR, (".db", ".sqlite", ".sqlite3", ".bak")),
            "latest_log": _latest_file(LOGS_DIR, (".log",)),
        },
    }

    if include_api_health:
        status["api"]["health"] = _api_health(
            status["api"]["base_url"],
            api_key=api_key,
            timeout=float(app_cfg.get("health_timeout") or 0.8),
        )

    status["alerts"] = assess_system_alerts(status)
    return status
