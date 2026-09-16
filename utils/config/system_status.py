"""Diagnostico local do aplicativo desktop."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from utils.config.app_config import get_app_config
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
            latest, latest_mtime = path, mtime

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


def _parse_iso_datetime(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or "").strip())
    except (TypeError, ValueError):
        return None


def assess_system_alerts(status: dict[str, Any], now: datetime | None = None) -> list[dict[str, str]]:
    """Avalia apenas a base SQLite, os backups e os registos locais."""
    now = now or datetime.now()
    alerts: list[dict[str, str]] = []
    db_info = status.get("database") or {}
    integrity = db_info.get("integrity") or {}

    if not db_info.get("exists"):
        alerts.append({"level": "critical", "code": "database_missing", "message": "Base de dados nao encontrada."})
    elif integrity.get("ok") is False:
        alerts.append({"level": "critical", "code": "database_integrity", "message": "Integridade SQLite com problema."})

    if int(db_info.get("size_bytes") or 0) >= DATABASE_LARGE_BYTES:
        alerts.append({
            "level": "warning",
            "code": "database_large",
            "message": "Base de dados grande; considere manutencao e backups mais frequentes.",
        })

    automation = status.get("automation") or {}
    last_backup = _parse_iso_datetime(automation.get("last_backup_run"))
    latest_backup = (status.get("files") or {}).get("latest_backup") or {}
    backup_reference = last_backup or _parse_iso_datetime(latest_backup.get("modified_at"))
    if backup_reference is None:
        alerts.append({"level": "warning", "code": "backup_missing", "message": "Nenhum backup encontrado ou registado."})
    elif now - backup_reference > timedelta(hours=BACKUP_STALE_HOURS):
        alerts.append({"level": "warning", "code": "backup_stale", "message": "Backup esta antigo; crie um backup manual."})

    backup_status = str(automation.get("last_backup_status") or "").strip().lower()
    if backup_status and backup_status != "ok" and not backup_status.startswith("ok:"):
        alerts.append({"level": "warning", "code": "backup_status", "message": "Ultimo backup automatico reportou problema."})

    return alerts or [{"level": "ok", "code": "system_ok", "message": "Sem alertas."}]


def collect_system_status(db: Any = None) -> dict[str, Any]:
    """Recolhe o estado do sistema local."""
    app_cfg = get_app_config(force_reload=True)
    db_path = resolve_path(getattr(db, "db_path", None) or app_cfg.get("db_path"))
    automation = _automation_state(db) if db is not None else {}

    status = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "app_env": str(app_cfg.get("app_env") or "development"),
        "db_mode": "local",
        "database": {
            "path": relativize_to_root(db_path),
            "exists": db_path.exists(),
            "size_bytes": _file_size(db_path),
            "integrity": _sqlite_integrity(db_path),
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
    status["alerts"] = assess_system_alerts(status)
    return status
