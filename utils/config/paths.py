from __future__ import annotations

import os
import sys
from pathlib import Path


def is_mobile_runtime() -> bool:
    """Indica se o processo esta a correr num pacote Android/iOS.

    O pacote Python do Android usa ``sys.platform == 'android'``. A variavel
    ``ANDROID_ARGUMENT`` cobre o arranque inicial do python-for-android e
    tambem deixa os testes de empacotamento explicitarem o alvo.
    """
    return sys.platform.lower() in {"android", "ios"} or bool(
        os.environ.get("ANDROID_ARGUMENT")
    )


def _resolve_root_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    current = Path(__file__).resolve()
    for candidate in (current.parent, *current.parents):
        if (
            (candidate / "admin_app.py").exists()
            and (candidate / "database").is_dir()
            and (candidate / "server").is_dir()
        ):
            return candidate
    return current.parents[2]


ROOT_DIR = _resolve_root_dir()


def _resolve_runtime_root_dir() -> Path:
    """Devolve uma pasta gravavel sem confundir recursos com dados do utilizador."""
    if not is_mobile_runtime():
        return ROOT_DIR

    override = str(os.environ.get("SIGEMPE_MOBILE_DATA_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()

    # Em Android, a pasta do APK e de apenas leitura. O armazenamento privado
    # da app e estavel entre arranques e nao exige permissao de ficheiros.
    try:
        from android.storage import app_storage_path  # type: ignore

        return Path(app_storage_path()).resolve()
    except Exception:
        # Fallback usado apenas por simuladores/ambientes de testes sem o
        # modulo android instalado.
        return (Path.home() / ".sigempe-manager-mobile").resolve()


RUNTIME_ROOT_DIR = _resolve_runtime_root_dir()
SERVER_DIR = ROOT_DIR / "server"
DATABASE_DIR = ROOT_DIR / "database"
ASSETS_DIR = ROOT_DIR / "assets"
CONFIG_DIR = RUNTIME_ROOT_DIR / "config"
DATA_DIR = RUNTIME_ROOT_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
REPORTS_DIR = DATA_DIR / "reports"
RECEIPTS_DIR = DATA_DIR / "receipts"
BACKUPS_DIR = DATA_DIR / "backups"
DB_BACKUP_DIR = BACKUPS_DIR / "database"
LOGS_DIR = RUNTIME_ROOT_DIR / "logs"
TEMP_DIR = RUNTIME_ROOT_DIR / "temp"

DB_FILE = DATABASE_DIR / "inventory.db"

APP_CONFIG_FILE = CONFIG_DIR / "app.json"
API_CONFIG_FILE = CONFIG_DIR / "api.json"
SERVICE_CONFIG_FILE = CONFIG_DIR / "service.json"
APP_SETTINGS_FILE = CONFIG_DIR / "app_settings.json"
ENV_FILE = CONFIG_DIR / ".env"
LEGACY_ENV_FILE = RUNTIME_ROOT_DIR / ".env"

LEGACY_REPORTS_DIR = ROOT_DIR / "Relatórios"
LEGACY_RECEIPTS_DIR = ROOT_DIR / "Recibos"

API_STDOUT_LOG = LOGS_DIR / "sigempeapi-stdout.log"
API_STDERR_LOG = LOGS_DIR / "sigempeapi-stderr.log"
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
    return RUNTIME_ROOT_DIR.joinpath(*parts)


def asset_path(*parts: str) -> Path:
    return ASSETS_DIR.joinpath(*parts)


def config_path(*parts: str) -> Path:
    return CONFIG_DIR.joinpath(*parts)


def data_path(*parts: str) -> Path:
    return DATA_DIR.joinpath(*parts)


def temp_path(*parts: str) -> Path:
    return TEMP_DIR.joinpath(*parts)


def resolve_path(value: str | os.PathLike[str] | Path | None, base_dir: Path | None = None) -> Path:
    base = Path(base_dir or RUNTIME_ROOT_DIR)
    if value is None:
        return base

    path = Path(str(value).strip()).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (base / path).resolve()


def relativize_to_root(path: str | os.PathLike[str] | Path) -> str:
    resolved = resolve_path(path)
    try:
        return resolved.relative_to(RUNTIME_ROOT_DIR).as_posix()
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
    if is_mobile_runtime():
        # O bundle Android nao e uma pasta de trabalho gravavel. Os dados de
        # runtime ja sao resolvidos contra RUNTIME_ROOT_DIR.
        return RUNTIME_ROOT_DIR
    target = str(ROOT_DIR)
    if os.getcwd() != target:
        os.chdir(target)
    return ROOT_DIR


def report_search_dirs() -> tuple[Path, ...]:
    return tuple(directory for directory in (REPORTS_DIR, LEGACY_REPORTS_DIR) if directory.exists())


def receipt_search_dirs() -> tuple[Path, ...]:
    return tuple(directory for directory in (RECEIPTS_DIR, LEGACY_RECEIPTS_DIR) if directory.exists())
