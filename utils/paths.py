from __future__ import annotations

import os
import sys
from pathlib import Path


def _resolve_root_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


ROOT_DIR = _resolve_root_dir()
SERVER_DIR = ROOT_DIR / "server"
DATABASE_DIR = ROOT_DIR / "database"
ASSETS_DIR = ROOT_DIR / "assets"
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
REPORTS_DIR = DATA_DIR / "reports"
RECEIPTS_DIR = DATA_DIR / "receipts"
BACKUPS_DIR = DATA_DIR / "backups"
DB_BACKUP_DIR = BACKUPS_DIR / "database"
LOGS_DIR = ROOT_DIR / "logs"
TEMP_DIR = ROOT_DIR / "temp"

DB_FILE = DATABASE_DIR / "inventory.db"

APP_CONFIG_FILE = CONFIG_DIR / "app.json"
API_CONFIG_FILE = CONFIG_DIR / "api.json"
SERVICE_CONFIG_FILE = CONFIG_DIR / "service.json"
APP_SETTINGS_FILE = CONFIG_DIR / "app_settings.json"
ENV_FILE = CONFIG_DIR / ".env"
LEGACY_ENV_FILE = ROOT_DIR / ".env"

LEGACY_REPORTS_DIR = ROOT_DIR / "Relatórios"
LEGACY_RECEIPTS_DIR = ROOT_DIR / "Recibos"

API_STDOUT_LOG = LOGS_DIR / "lojaapi-stdout.log"
API_STDERR_LOG = LOGS_DIR / "lojaapi-stderr.log"
LOSSES_LOG_FILE = LOGS_DIR / "losses.log"

RUNTIME_DIRS = (
    CONFIG_DIR,
    DATA_DIR,
    CACHE_DIR,
    REPORTS_DIR,
    RECEIPTS_DIR,
    BACKUPS_DIR,
    DB_BACKUP_DIR,
    LOGS_DIR,
    TEMP_DIR,
)


def root_path(*parts: str) -> Path:
    return ROOT_DIR.joinpath(*parts)


def asset_path(*parts: str) -> Path:
    return ASSETS_DIR.joinpath(*parts)


def config_path(*parts: str) -> Path:
    return CONFIG_DIR.joinpath(*parts)


def data_path(*parts: str) -> Path:
    return DATA_DIR.joinpath(*parts)


def temp_path(*parts: str) -> Path:
    return TEMP_DIR.joinpath(*parts)


def resolve_path(value: str | os.PathLike[str] | Path | None, base_dir: Path | None = None) -> Path:
    base = Path(base_dir or ROOT_DIR)
    if value is None:
        return base

    path = Path(str(value).strip()).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (base / path).resolve()


def relativize_to_root(path: str | os.PathLike[str] | Path) -> str:
    resolved = resolve_path(path)
    try:
        return resolved.relative_to(ROOT_DIR).as_posix()
    except ValueError:
        return resolved.as_posix()


def ensure_parent_dir(path: str | os.PathLike[str] | Path) -> Path:
    resolved = resolve_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def ensure_runtime_dirs(*extra_dirs: str | os.PathLike[str] | Path) -> tuple[Path, ...]:
    created = []
    for directory in list(RUNTIME_DIRS) + [resolve_path(item) for item in extra_dirs]:
        directory.mkdir(parents=True, exist_ok=True)
        created.append(directory)
    return tuple(created)


def set_project_cwd() -> Path:
    target = str(ROOT_DIR)
    if os.getcwd() != target:
        os.chdir(target)
    return ROOT_DIR


def report_search_dirs() -> tuple[Path, ...]:
    return tuple(directory for directory in (REPORTS_DIR, LEGACY_REPORTS_DIR) if directory.exists())


def receipt_search_dirs() -> tuple[Path, ...]:
    return tuple(directory for directory in (RECEIPTS_DIR, LEGACY_RECEIPTS_DIR) if directory.exists())
