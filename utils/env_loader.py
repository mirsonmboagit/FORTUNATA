from __future__ import annotations

import os
from pathlib import Path

from utils.paths import ENV_FILE, LEGACY_ENV_FILE, resolve_path


def _resolve_dotenv_path(dotenv_path=None) -> Path:
    if dotenv_path:
        return resolve_path(dotenv_path)
    return ENV_FILE


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _load_dotenv_fallback(dotenv_path=None, override=False) -> bool:
    env_path = _resolve_dotenv_path(dotenv_path)
    if not env_path.exists() or not env_path.is_file():
        return False

    loaded_any = False
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = _strip_quotes(value)

        if override or key not in os.environ:
            os.environ[key] = value
        loaded_any = True

    return loaded_any


def load_dotenv(dotenv_path=None, override=False, **kwargs):
    env_path = _resolve_dotenv_path(dotenv_path)
    try:
        from dotenv import load_dotenv as _real_load_dotenv

        loaded = _real_load_dotenv(dotenv_path=env_path, override=override, **kwargs)
        if not loaded and dotenv_path is None and LEGACY_ENV_FILE.exists():
            return _real_load_dotenv(
                dotenv_path=LEGACY_ENV_FILE,
                override=override,
                **kwargs,
            )
        return loaded
    except Exception:
        loaded = _load_dotenv_fallback(dotenv_path=env_path, override=override)
        if not loaded and dotenv_path is None and LEGACY_ENV_FILE.exists():
            return _load_dotenv_fallback(dotenv_path=LEGACY_ENV_FILE, override=override)
        return loaded
