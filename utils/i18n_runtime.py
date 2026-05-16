from __future__ import annotations

from typing import Any

from kivy.app import App
from kivy.clock import Clock

from utils.i18n import has_text_translation, normalize_language, translate_text


TRANSLATABLE_PROPERTIES = (
    "text",
    "title",
    "hint_text",
    "helper_text",
    "secondary_text",
    "tertiary_text",
    "title_text",
    "subtitle_text",
    "label_text",
    "caption_text",
    "tooltip_text",
)

_DIALOG_HOOKED = False


def _looks_translatable(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text and any(char.isalpha() for char in text) and has_text_translation(text))


def _set_localized_property(widget: Any, prop: str, value: str) -> None:
    flag = f"_i18n_setting_{prop}"
    try:
        setattr(widget, flag, True)
        setattr(widget, prop, value)
    finally:
        try:
            setattr(widget, flag, False)
        except Exception:
            pass


def _translate_changed_property(widget: Any, prop: str, value: Any) -> None:
    if getattr(widget, f"_i18n_setting_{prop}", False):
        return
    if not _looks_translatable(value):
        return
    original_attr = f"_i18n_original_{prop}"
    try:
        setattr(widget, original_attr, str(value))
    except Exception:
        return
    app = App.get_running_app()
    language = getattr(app, "language", "pt") if app else "pt"
    translated = translate_text(str(value), language)
    if translated != value:
        try:
            _set_localized_property(widget, prop, translated)
        except Exception:
            pass


def _ensure_reactive_translation(widget: Any, prop: str) -> None:
    marker = f"_i18n_bound_{prop}"
    if getattr(widget, marker, False):
        return
    binder = getattr(widget, "bind", None)
    if not callable(binder):
        return
    try:
        binder(**{prop: lambda inst, value, watched=prop: _translate_changed_property(inst, watched, value)})
        setattr(widget, marker, True)
    except Exception:
        pass


def localize_widget_tree(widget: Any, language: Any) -> None:
    if widget is None:
        return
    lang = normalize_language(language)
    stack = [widget]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)

        for prop in TRANSLATABLE_PROPERTIES:
            if not hasattr(current, prop):
                continue
            _ensure_reactive_translation(current, prop)
            try:
                value = getattr(current, prop)
            except Exception:
                continue
            original_attr = f"_i18n_original_{prop}"
            original = getattr(current, original_attr, None)
            if original is None:
                if not _looks_translatable(value):
                    continue
                original = str(value)
                try:
                    setattr(current, original_attr, original)
                except Exception:
                    continue
            translated = translate_text(original, lang)
            if translated != value:
                try:
                    _set_localized_property(current, prop, translated)
                except Exception:
                    pass

        try:
            stack.extend(list(getattr(current, "children", []) or []))
        except Exception:
            pass


def install_i18n_hooks() -> None:
    global _DIALOG_HOOKED
    if _DIALOG_HOOKED:
        return
    try:
        from kivymd.uix.dialog import MDDialog
    except Exception:
        return

    original_open = MDDialog.open
    if getattr(original_open, "_i18n_hooked", False):
        _DIALOG_HOOKED = True
        return

    def open_with_i18n(self, *args, **kwargs):
        app = App.get_running_app()
        language = getattr(app, "language", "pt") if app else "pt"
        localize_widget_tree(self, language)
        result = original_open(self, *args, **kwargs)
        if app and hasattr(app, "refresh_language"):
            Clock.schedule_once(lambda _dt: app.refresh_language(self), 0)
        return result

    open_with_i18n._i18n_hooked = True
    MDDialog.open = open_with_i18n
    _DIALOG_HOOKED = True
