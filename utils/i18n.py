from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from utils.paths import ROOT_DIR


DEFAULT_LANGUAGE = "pt"
LOCALES_DIR = ROOT_DIR / "locales"
TEXT_TRANSLATIONS_FILE = LOCALES_DIR / "texts.json"

SUPPORTED_LANGUAGES = (
    {"code": "pt", "name": "Português", "native_name": "Português", "short": "PT"},
    {"code": "en", "name": "English", "native_name": "English", "short": "EN"},
    {"code": "fr", "name": "French", "native_name": "Français", "short": "FR"},
    {"code": "de", "name": "German", "native_name": "Deutsch", "short": "DE"},
    {"code": "es", "name": "Spanish", "native_name": "Español", "short": "ES"},
)

_LANGUAGE_CODES = {item["code"] for item in SUPPORTED_LANGUAGES}
_LANGUAGE_INDEX = {item["code"]: item for item in SUPPORTED_LANGUAGES}


def normalize_language(value: Any, fallback: str = DEFAULT_LANGUAGE) -> str:
    code = str(value or "").strip().lower().replace("_", "-")
    if "-" in code:
        code = code.split("-", 1)[0]
    if code in _LANGUAGE_CODES:
        return code
    return fallback if fallback in _LANGUAGE_CODES else DEFAULT_LANGUAGE


def language_options() -> list[dict[str, str]]:
    return [dict(item) for item in SUPPORTED_LANGUAGES]


def language_label(code: Any, *, include_short: bool = False) -> str:
    language = _LANGUAGE_INDEX.get(normalize_language(code), _LANGUAGE_INDEX[DEFAULT_LANGUAGE])
    if include_short:
        return f"{language['native_name']} ({language['short']})"
    return language["native_name"]


def language_short(code: Any) -> str:
    return _LANGUAGE_INDEX.get(normalize_language(code), _LANGUAGE_INDEX[DEFAULT_LANGUAGE])["short"]


@lru_cache(maxsize=None)
def _load_catalog(code: str) -> dict[str, str]:
    normalized = normalize_language(code)
    path = LOCALES_DIR / f"{normalized}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    return {str(key): str(value) for key, value in (data or {}).items()}


def reload_translations() -> None:
    _load_catalog.cache_clear()
    _load_text_catalog.cache_clear()


def translate(key: str, language: Any = None, default: str | None = None, **kwargs: Any) -> str:
    lang = normalize_language(language)
    key = str(key or "")
    catalog = _load_catalog(lang)
    fallback_catalog = _load_catalog(DEFAULT_LANGUAGE)
    text = catalog.get(key) or fallback_catalog.get(key) or default or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text


def _normalize_text_source(text: Any) -> str:
    return " ".join(
        str(text or "")
        .replace("\\n", "\n")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .split()
    )


@lru_cache(maxsize=1)
def _load_text_catalog() -> dict[str, dict[str, str]]:
    try:
        data = json.loads(TEXT_TRANSLATIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    catalog: dict[str, dict[str, str]] = {}
    for source, translations in (data or {}).items():
        normalized_source = _normalize_text_source(source)
        if not normalized_source or not isinstance(translations, dict):
            continue
        catalog[normalized_source] = {
            normalize_language(lang): str(value)
            for lang, value in translations.items()
            if str(value or "").strip()
        }
    return catalog


def has_text_translation(text: Any) -> bool:
    normalized = _normalize_text_source(text)
    return normalized in _load_text_catalog() or bool(_translate_dynamic_text(normalized, "en"))


def translate_text(text: Any, language: Any = None) -> str:
    source = str(text or "")
    lang = normalize_language(language)
    if not source.strip() or lang == DEFAULT_LANGUAGE:
        return source

    normalized_source = _normalize_text_source(source)
    translations = _load_text_catalog().get(normalized_source)
    if translations and translations.get(lang):
        translated = translations[lang]
        return translated.upper() if source.strip().isupper() else translated

    dynamic = _translate_dynamic_text(normalized_source, lang)
    if dynamic:
        return dynamic

    return source


def _translate_dynamic_text(normalized_source: str, language: str) -> str:
    alert_match = re.match(r"^(\d+)\s+alerta\(s\)\s+pendente\(s\)$", normalized_source, re.I)
    if alert_match:
        count = alert_match.group(1)
        return {
            "en": f"{count} pending alert(s)",
            "fr": f"{count} alerte(s) en attente",
            "de": f"{count} ausstehende Warnung(en)",
            "es": f"{count} alerta(s) pendiente(s)",
        }.get(language, normalized_source)

    products_match = re.match(r"^(\d+)\s+produtos?$", normalized_source, re.I)
    if products_match:
        count = products_match.group(1)
        return {
            "en": f"{count} products",
            "fr": f"{count} produits",
            "de": f"{count} Produkte",
            "es": f"{count} productos",
        }.get(language, normalized_source)

    items_match = re.match(r"^(\d+)\s+itens?$", normalized_source, re.I)
    if items_match:
        count = items_match.group(1)
        return {
            "en": f"{count} items",
            "fr": f"{count} articles",
            "de": f"{count} Artikel",
            "es": f"{count} items",
        }.get(language, normalized_source)

    return ""
