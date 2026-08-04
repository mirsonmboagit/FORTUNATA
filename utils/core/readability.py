from __future__ import annotations

from typing import Any

from kivy.clock import Clock
from kivy.metrics import sp


MIN_BODY_FONT_SIZE = sp(14)
MIN_CONTROL_FONT_SIZE = sp(15)
MIN_CAPTION_FONT_SIZE = sp(13)
MIN_LINE_HEIGHT = 1.20


def _has_readable_text(widget: Any) -> bool:
    """Ignora glifos puramente decorativos, mas inclui dicas e legendas."""
    for prop in ("text", "hint_text", "helper_text", "secondary_text", "tertiary_text"):
        try:
            value = getattr(widget, prop, "")
        except Exception:
            continue
        if isinstance(value, str) and any(char.isalnum() for char in value):
            return True
    return False


def _minimum_font_size(widget: Any) -> float:
    name = widget.__class__.__name__.lower()
    if any(token in name for token in ("button", "textfield", "spinner", "dropdown")):
        return MIN_CONTROL_FONT_SIZE
    if any(token in name for token in ("caption", "helper", "support")):
        return MIN_CAPTION_FONT_SIZE
    return MIN_BODY_FONT_SIZE


def _improve_widget(widget: Any) -> None:
    if hasattr(widget, "font_size") and _has_readable_text(widget):
        try:
            current = float(widget.font_size or 0)
            minimum = _minimum_font_size(widget)
            if 0 < current < minimum:
                widget.font_size = minimum
        except (TypeError, ValueError):
            pass

    if hasattr(widget, "line_height"):
        try:
            if float(widget.line_height or 0) < MIN_LINE_HEIGHT:
                widget.line_height = MIN_LINE_HEIGHT
        except (TypeError, ValueError):
            pass


def improve_readability(widget: Any) -> None:
    """Aplica limites de leitura e acompanha componentes adicionados depois."""
    if widget is None:
        return

    stack = [widget]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)
        _improve_widget(current)

        if not getattr(current, "_readability_children_bound", False):
            binder = getattr(current, "bind", None)
            if callable(binder) and hasattr(current, "children"):
                try:
                    binder(
                        children=lambda _instance, children: Clock.schedule_once(
                            lambda _dt: [improve_readability(child) for child in (children or [])],
                            0,
                        )
                    )
                    current._readability_children_bound = True
                except Exception:
                    pass

        try:
            stack.extend(list(getattr(current, "children", []) or []))
        except Exception:
            pass
