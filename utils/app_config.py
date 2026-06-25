from __future__ import annotations

import copy
import json
import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Any

from utils.env_loader import load_dotenv
from utils.paths import (
    API_CONFIG_FILE,
    API_STDERR_LOG,
    API_STDOUT_LOG,
    APP_CONFIG_FILE,
    APP_SETTINGS_FILE,
    ASSETS_DIR,
    CACHE_DIR,
    CONFIG_DIR,
    DB_BACKUP_DIR,
    DB_FILE,
    ENV_FILE,
    LEGACY_ENV_FILE,
    LOGS_DIR,
    RECEIPTS_DIR,
    REPORTS_DIR,
    ROOT_DIR,
    SERVICE_CONFIG_FILE,
    TEMP_DIR,
    ensure_runtime_dirs,
    relativize_to_root,
    resolve_path,
)


APP_DEFAULTS = {
    # Valores padrao usados quando os arquivos de config ainda nao existem.
    "app_env": "development",
    "db_mode": "hybrid",
    "db_path": "database/inventory.db",
    "api_base_url": "http://127.0.0.1:8080",
    "api_key": "",
    "timeout": 10,
    "health_timeout": 0.8,
    "availability_ttl": 4.0,
    "availability_cooldown": 6.0,
    "http_pool_size": 16,
    "log_level": "INFO",
    "reports_dir": "data/reports",
    "receipts_dir": "data/receipts",
    "cache_dir": "data/cache",
    "logs_dir": "logs",
    "temp_dir": "temp",
    "assets_dir": "assets",
    "ocr_tesseract_cmd": "",
}

API_DEFAULTS = {
    "host": "127.0.0.1",
    "port": 8080,
    "runner": "waitress",
    "threads": 8,
    "connection_limit": 100,
    "channel_timeout": 120,
    "cleanup_interval": 30,
    "ident": "sige-mpe-api",
}

SERVICE_DEFAULTS = {
    "name": "SIGEMPEAPI",
    "display_name": "SIGE MPE API Local",
    "description": "API local Flask/Waitress para o SIGE MPE.",
    "nssm_path": "nssm.exe",
    "python_executable": "python",
    "entrypoint": "server/run_api.py",
    "working_directory": ".",
    "stdout_log": "logs/sigempeapi-stdout.log",
    "stderr_log": "logs/sigempeapi-stderr.log",
}

APP_SETTINGS_DEFAULTS = {
    "system_name": "SIGE MPE",
    "ai_enabled": True,
    "auto_banners_enabled": True,
    "smart_monitor_enabled": True,
    "theme_style": "Light",
    "manager_theme_style": "Light",
    "language": "pt",
    "physical_scanner_enabled": True,
    "physical_scanner_min_length": 6,
    "receipt_auto_print": False,
    "receipt_printer_name": "",
    "receipt_paper_width_mm": 80,
}

INSECURE_API_KEYS = {
    "",
    "joe123",
    "changeme",
    "your_api_key_here",
}


def _load_json(path: Path) -> dict[str, Any]:
    # Le JSON com fallback seguro para dicionario vazio.
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _write_json_if_missing(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _is_insecure_api_key(value: Any) -> bool:
    return str(value or "").strip().lower() in INSECURE_API_KEYS


def _upsert_env_value(path: Path, key: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    existing_lines: list[str] = []
    if path.exists():
        try:
            existing_lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            existing_lines = []

    prefix = f"{key}="
    updated = False
    new_lines: list[str] = []
    for raw_line in existing_lines:
        line = str(raw_line)
        stripped = line.strip()
        if stripped.startswith("export "):
            candidate = stripped[7:].strip()
        else:
            candidate = stripped
        if candidate.startswith(prefix):
            new_lines.append(f"{key}={value}")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append(f"{key}={value}")

    path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")


def _ensure_runtime_api_key(app_payload: dict[str, Any]) -> None:
    # Gera uma chave local quando a configuracao ainda esta insegura.
    current_env_key = str(os.getenv("API_KEY") or "").strip()
    current_file_key = str(app_payload.get("api_key") or "").strip()

    if not _is_insecure_api_key(current_env_key):
        return
    if not _is_insecure_api_key(current_file_key):
        return

    generated_key = secrets.token_urlsafe(32)
    _upsert_env_value(ENV_FILE, "API_KEY", generated_key)
    os.environ["API_KEY"] = generated_key


def bootstrap_config_files() -> None:
    # Cria arquivos de configuracao iniciais sem apagar os existentes.
    ensure_runtime_dirs()
    _write_json_if_missing(APP_CONFIG_FILE, copy.deepcopy(APP_DEFAULTS))
    _write_json_if_missing(API_CONFIG_FILE, copy.deepcopy(API_DEFAULTS))
    _write_json_if_missing(SERVICE_CONFIG_FILE, copy.deepcopy(SERVICE_DEFAULTS))
    _write_json_if_missing(APP_SETTINGS_FILE, copy.deepcopy(APP_SETTINGS_DEFAULTS))


def _coerce_int(value: Any, fallback: int) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(fallback)


def _coerce_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(fallback)


def _clamp_number(value: int | float, minimum: int | float, maximum: int | float):
    return max(minimum, min(maximum, value))


def _coerce_choice(value: Any, allowed: set[str], fallback: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else fallback


def _coerce_bool(value: Any, fallback: bool) -> bool:
    if value in (None, ""):
        return fallback
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "sim"}


def _env_override(payload: dict[str, Any], env_name: str, key: str, caster=None) -> None:
    raw = os.getenv(env_name)
    if raw in (None, ""):
        return
    payload[key] = caster(raw, payload.get(key)) if caster else raw


def _normalize_app_config(payload: dict[str, Any], api_cfg: dict[str, Any]) -> dict[str, Any]:
    # Normaliza tipos e caminhos usados pela app.
    normalized = copy.deepcopy(APP_DEFAULTS)
    normalized.update(payload)

    if not normalized.get("api_base_url"):
        api_host = str(api_cfg.get("host") or "127.0.0.1").strip()
        api_port = _coerce_int(api_cfg.get("port"), 8080)
        if api_host in {"0.0.0.0", "::"}:
            api_host = "127.0.0.1"
        normalized["api_base_url"] = f"http://{api_host}:{api_port}"

    normalized["db_path"] = str(resolve_path(normalized.get("db_path"), ROOT_DIR))
    normalized["reports_dir"] = str(resolve_path(normalized.get("reports_dir"), ROOT_DIR))
    normalized["receipts_dir"] = str(resolve_path(normalized.get("receipts_dir"), ROOT_DIR))
    normalized["cache_dir"] = str(resolve_path(normalized.get("cache_dir"), ROOT_DIR))
    normalized["logs_dir"] = str(resolve_path(normalized.get("logs_dir"), ROOT_DIR))
    normalized["temp_dir"] = str(resolve_path(normalized.get("temp_dir"), ROOT_DIR))
    normalized["assets_dir"] = str(resolve_path(normalized.get("assets_dir"), ROOT_DIR))
    normalized["timeout"] = _clamp_number(
        _coerce_float(normalized.get("timeout"), APP_DEFAULTS["timeout"]),
        1.0,
        120.0,
    )
    normalized["health_timeout"] = _coerce_float(
        normalized.get("health_timeout"),
        APP_DEFAULTS["health_timeout"],
    )
    normalized["health_timeout"] = _clamp_number(normalized["health_timeout"], 0.2, 10.0)
    normalized["availability_ttl"] = _coerce_float(
        normalized.get("availability_ttl"),
        APP_DEFAULTS["availability_ttl"],
    )
    normalized["availability_ttl"] = _clamp_number(normalized["availability_ttl"], 0.2, 300.0)
    normalized["availability_cooldown"] = _coerce_float(
        normalized.get("availability_cooldown"),
        APP_DEFAULTS["availability_cooldown"],
    )
    normalized["availability_cooldown"] = _clamp_number(
        normalized["availability_cooldown"],
        0.2,
        300.0,
    )
    normalized["http_pool_size"] = _coerce_int(
        normalized.get("http_pool_size"),
        APP_DEFAULTS["http_pool_size"],
    )
    normalized["http_pool_size"] = int(_clamp_number(normalized["http_pool_size"], 1, 128))
    normalized["app_env"] = str(normalized.get("app_env") or "development").strip().lower()
    normalized["db_mode"] = _coerce_choice(
        normalized.get("db_mode"),
        {"local", "remote", "hybrid", "auto", "remote_strict"},
        APP_DEFAULTS["db_mode"],
    )
    normalized["api_key"] = str(normalized.get("api_key") or "").strip()
    normalized["log_level"] = str(normalized.get("log_level") or "INFO").strip().upper()
    normalized["ocr_tesseract_cmd"] = str(normalized.get("ocr_tesseract_cmd") or "").strip()
    return normalized


def _normalize_api_config(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(API_DEFAULTS)
    normalized.update(payload)
    normalized["host"] = str(normalized.get("host") or API_DEFAULTS["host"]).strip()
    normalized["port"] = int(
        _clamp_number(
            _coerce_int(normalized.get("port"), API_DEFAULTS["port"]),
            1,
            65535,
        )
    )
    normalized["threads"] = int(
        _clamp_number(
            _coerce_int(normalized.get("threads"), API_DEFAULTS["threads"]),
            1,
            64,
        )
    )
    normalized["connection_limit"] = _coerce_int(
        normalized.get("connection_limit"),
        API_DEFAULTS["connection_limit"],
    )
    normalized["connection_limit"] = int(_clamp_number(normalized["connection_limit"], 1, 10000))
    normalized["channel_timeout"] = _coerce_int(
        normalized.get("channel_timeout"),
        API_DEFAULTS["channel_timeout"],
    )
    normalized["channel_timeout"] = int(_clamp_number(normalized["channel_timeout"], 1, 3600))
    normalized["cleanup_interval"] = _coerce_int(
        normalized.get("cleanup_interval"),
        API_DEFAULTS["cleanup_interval"],
    )
    normalized["cleanup_interval"] = int(_clamp_number(normalized["cleanup_interval"], 1, 3600))
    normalized["runner"] = _coerce_choice(
        normalized.get("runner"),
        {"waitress", "flask"},
        API_DEFAULTS["runner"],
    )
    normalized["ident"] = str(normalized.get("ident") or API_DEFAULTS["ident"]).strip()
    return normalized


def _normalize_service_config(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(SERVICE_DEFAULTS)
    normalized.update(payload)
    for key in ("nssm_path", "entrypoint", "working_directory", "stdout_log", "stderr_log"):
        normalized[key] = relativize_to_root(normalized.get(key) or SERVICE_DEFAULTS[key])
    normalized["python_executable"] = str(
        normalized.get("python_executable") or SERVICE_DEFAULTS["python_executable"]
    ).strip()
    normalized["name"] = str(normalized.get("name") or SERVICE_DEFAULTS["name"]).strip()
    normalized["display_name"] = str(
        normalized.get("display_name") or SERVICE_DEFAULTS["display_name"]
    ).strip()
    normalized["description"] = str(
        normalized.get("description") or SERVICE_DEFAULTS["description"]
    ).strip()
    return normalized


@lru_cache(maxsize=1)
def _load_all_configs() -> dict[str, dict[str, Any]]:
    bootstrap_config_files()
    load_dotenv(override=False)

    app_payload = copy.deepcopy(APP_DEFAULTS)
    app_payload.update(_load_json(APP_CONFIG_FILE))
    _ensure_runtime_api_key(app_payload)

    api_payload = copy.deepcopy(API_DEFAULTS)
    api_payload.update(_load_json(API_CONFIG_FILE))

    service_payload = copy.deepcopy(SERVICE_DEFAULTS)
    service_payload.update(_load_json(SERVICE_CONFIG_FILE))

    settings_payload = copy.deepcopy(APP_SETTINGS_DEFAULTS)
    settings_payload.update(_load_json(APP_SETTINGS_FILE))

    _env_override(app_payload, "APP_ENV", "app_env")
    _env_override(app_payload, "LOG_LEVEL", "log_level")
    _env_override(app_payload, "DB_MODE", "db_mode")
    _env_override(app_payload, "DB_PATH", "db_path")
    _env_override(app_payload, "API_BASE_URL", "api_base_url")
    _env_override(app_payload, "API_KEY", "api_key")
    _env_override(app_payload, "TIMEOUT", "timeout", _coerce_float)
    _env_override(app_payload, "HEALTH_TIMEOUT", "health_timeout", _coerce_float)
    _env_override(app_payload, "AVAILABILITY_TTL", "availability_ttl", _coerce_float)
    _env_override(app_payload, "AVAILABILITY_COOLDOWN", "availability_cooldown", _coerce_float)
    _env_override(app_payload, "HTTP_POOL_SIZE", "http_pool_size", _coerce_int)
    _env_override(app_payload, "OCR_TESSERACT_CMD", "ocr_tesseract_cmd")

    _env_override(api_payload, "API_HOST", "host")
    _env_override(api_payload, "API_PORT", "port", _coerce_int)
    _env_override(api_payload, "API_RUNNER", "runner")
    _env_override(api_payload, "API_THREADS", "threads", _coerce_int)
    _env_override(api_payload, "API_CONNECTION_LIMIT", "connection_limit", _coerce_int)
    _env_override(api_payload, "API_CHANNEL_TIMEOUT", "channel_timeout", _coerce_int)
    _env_override(api_payload, "API_CLEANUP_INTERVAL", "cleanup_interval", _coerce_int)

    _env_override(service_payload, "NSSM_PATH", "nssm_path")
    _env_override(service_payload, "SERVICE_NAME", "name")
    _env_override(service_payload, "SERVICE_DISPLAY_NAME", "display_name")
    _env_override(service_payload, "SERVICE_DESCRIPTION", "description")

    normalized_api = _normalize_api_config(api_payload)
    normalized_app = _normalize_app_config(app_payload, normalized_api)
    normalized_service = _normalize_service_config(service_payload)

    return {
        "app": normalized_app,
        "api": normalized_api,
        "service": normalized_service,
        "app_settings": settings_payload,
    }


def reload_configs() -> None:
    _load_all_configs.cache_clear()


def get_app_config(force_reload: bool = False) -> dict[str, Any]:
    if force_reload:
        reload_configs()
    return copy.deepcopy(_load_all_configs()["app"])


def get_api_config(force_reload: bool = False) -> dict[str, Any]:
    if force_reload:
        reload_configs()
    return copy.deepcopy(_load_all_configs()["api"])


def get_service_config(force_reload: bool = False) -> dict[str, Any]:
    if force_reload:
        reload_configs()
    return copy.deepcopy(_load_all_configs()["service"])


def get_app_settings(force_reload: bool = False) -> dict[str, Any]:
    if force_reload:
        reload_configs()
    return copy.deepcopy(_load_all_configs()["app_settings"])


def save_app_settings(data: dict[str, Any]) -> Path:
    ensure_runtime_dirs()
    merged = copy.deepcopy(APP_SETTINGS_DEFAULTS)
    merged.update(get_app_settings(force_reload=True))
    merged.update(data or {})
    APP_SETTINGS_FILE.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    reload_configs()
    return APP_SETTINGS_FILE


def get_database_path(force_reload: bool = False) -> Path:
    return Path(get_app_config(force_reload=force_reload)["db_path"])


def get_api_base_url(force_reload: bool = False) -> str:
    return str(get_app_config(force_reload=force_reload).get("api_base_url") or "").strip()


def get_runtime_config(force_reload: bool = False) -> dict[str, Any]:
    app_cfg = get_app_config(force_reload=force_reload)
    api_cfg = get_api_config(force_reload=force_reload)
    runtime = copy.deepcopy(app_cfg)
    runtime.update(api_cfg)
    runtime["db_path"] = app_cfg["db_path"]
    runtime["api_base_url"] = app_cfg["api_base_url"]
    runtime["api_key"] = app_cfg["api_key"]
    return runtime


def get_runtime_paths(force_reload: bool = False) -> dict[str, str]:
    _ = force_reload
    return {
        "root_dir": str(ROOT_DIR),
        "config_dir": str(CONFIG_DIR),
        "assets_dir": str(ASSETS_DIR),
        "cache_dir": str(CACHE_DIR),
        "reports_dir": str(REPORTS_DIR),
        "receipts_dir": str(RECEIPTS_DIR),
        "logs_dir": str(LOGS_DIR),
        "temp_dir": str(TEMP_DIR),
        "db_path": str(DB_FILE),
        "db_backup_dir": str(DB_BACKUP_DIR),
        "app_settings": str(APP_SETTINGS_FILE),
        "env_file": str(ENV_FILE),
        "legacy_env_file": str(LEGACY_ENV_FILE),
        "api_stdout_log": str(API_STDOUT_LOG),
        "api_stderr_log": str(API_STDERR_LOG),
    }
