from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.factory import Factory
from kivy.properties import BooleanProperty, ListProperty, NumericProperty
from kivymd.uix.button import MDRaisedButton
from kivymd.uix.card import MDCard

from ui.components.tooltip_widgets import TooltipIconButton, TooltipRaisedButton


def _blend_color(base, accent, factor):
    base = list(base or [1, 1, 1, 1])
    accent = list(accent or base)
    while len(base) < 4:
        base.append(1)
    while len(accent) < 4:
        accent.append(base[3])
    mix = max(0.0, min(1.0, float(factor or 0.0)))
    return [
        (base[index] * (1.0 - mix)) + (accent[index] * mix)
        for index in range(4)
    ]


def _theme_color(name, fallback):
    app = App.get_running_app()
    tokens = getattr(app, "theme_tokens", {}) if app else {}
    return list(tokens.get(name, fallback))


class HoverFeedbackBehavior:
    hover_enabled = BooleanProperty(True)
    press_enabled = BooleanProperty(False)
    hover_bg_mix = NumericProperty(0.08)
    hover_line_mix = NumericProperty(0.22)
    hover_elevation_delta = NumericProperty(2.0)
    hover_duration = NumericProperty(0.16)
    press_bg_mix = NumericProperty(0.16)
    press_line_mix = NumericProperty(0.32)
    press_elevation_delta = NumericProperty(0.7)
    hover_accent_color = ListProperty([])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._normalize_shape_defaults()
        self._hover_bound = False
        self._hovered = False
        self._pressed = False
        self._hover_base_bg = None
        self._hover_base_line = None
        self._hover_base_elevation = None
        self._hover_properties = set(self.properties()) if hasattr(self, "properties") else set()

        bindings = {
            "parent": self._handle_hover_context_change,
            "disabled": self._handle_hover_context_change,
            "hover_enabled": self._handle_hover_context_change,
        }
        if "md_bg_color" in self._hover_properties:
            bindings["md_bg_color"] = self._capture_hover_base
        if "line_color" in self._hover_properties:
            bindings["line_color"] = self._capture_hover_base
        if "elevation" in self._hover_properties:
            bindings["elevation"] = self._capture_hover_base
        if "radius" in self._hover_properties:
            bindings["radius"] = self._handle_shape_property_change
        if "shadow_radius" in self._hover_properties:
            bindings["shadow_radius"] = self._handle_shape_property_change
        self.bind(**bindings)

        Clock.schedule_once(lambda _dt: self._capture_hover_base(), 0)
        Clock.schedule_once(lambda _dt: self._normalize_shape_defaults(), 0)
        Clock.schedule_once(lambda _dt: self._sync_hover_binding(), 0)

    def _normalize_shape_defaults(self):
        available_properties = set(self.properties()) if hasattr(self, "properties") else set()
        if "radius" in available_properties:
            normalized = self._normalize_radius_value(getattr(self, "radius", None))
            if normalized is not None and list(getattr(self, "radius", []) or []) != normalized:
                self.radius = normalized
        if "shadow_radius" in available_properties:
            normalized = self._normalize_radius_value(getattr(self, "shadow_radius", None))
            if normalized is not None and list(getattr(self, "shadow_radius", []) or []) != normalized:
                self.shadow_radius = normalized

    @staticmethod
    def _normalize_radius_value(value):
        if value is None:
            return [0, 0, 0, 0]
        if not isinstance(value, (list, tuple)):
            return [value, value, value, value]
        values = list(value)
        if not values:
            return [0, 0, 0, 0]
        if len(values) == 1:
            return values * 4
        if len(values) == 2:
            return [values[0], values[1], values[0], values[1]]
        if len(values) == 3:
            return [values[0], values[1], values[2], values[1]]
        return values[:4]

    def _handle_shape_property_change(self, *_args):
        self._normalize_shape_defaults()

    def on_parent(self, widget, parent):
        parent_handler = getattr(super(), "on_parent", None)
        if callable(parent_handler):
            parent_handler(widget, parent)
        self._handle_hover_context_change()

    def _handle_hover_context_change(self, *_args):
        self._sync_hover_binding()
        if self.parent is None or getattr(self, "disabled", False) or not self.hover_enabled:
            self._pressed = False
            self._set_hover_state(False, animated=False)

    def _sync_hover_binding(self):
        should_bind = self.parent is not None and self.hover_enabled
        if should_bind and not self._hover_bound:
            Window.bind(mouse_pos=self._handle_mouse_pos)
            self._hover_bound = True
        elif not should_bind and self._hover_bound:
            Window.unbind(mouse_pos=self._handle_mouse_pos)
            self._hover_bound = False

    def _capture_hover_base(self, *_args):
        if self._hovered:
            return
        if "md_bg_color" in self._hover_properties:
            self._hover_base_bg = list(getattr(self, "md_bg_color", []) or [1, 1, 1, 1])
        if "line_color" in self._hover_properties:
            self._hover_base_line = list(getattr(self, "line_color", []) or [0, 0, 0, 0])
        if "elevation" in self._hover_properties:
            self._hover_base_elevation = float(getattr(self, "elevation", 0) or 0)

    def _resolve_hover_accent(self):
        accent = list(self.hover_accent_color or [])
        if accent:
            return accent
        return _theme_color("primary", [0.10, 0.35, 0.65, 1])

    def _build_hover_targets(self, hovered):
        targets = {}
        accent = self._resolve_hover_accent()
        bg_mix = self.press_bg_mix if self._pressed else self.hover_bg_mix
        line_mix = self.press_line_mix if self._pressed else self.hover_line_mix

        if "md_bg_color" in self._hover_properties and self._hover_base_bg is not None:
            targets["md_bg_color"] = (
                _blend_color(self._hover_base_bg, accent, bg_mix)
                if hovered or self._pressed
                else list(self._hover_base_bg)
            )

        if "line_color" in self._hover_properties and self._hover_base_line is not None:
            accent_line = list(accent)
            while len(accent_line) < 4:
                accent_line.append(1)
            accent_line[3] = max(float(self._hover_base_line[3] or 0), line_mix)
            targets["line_color"] = (
                _blend_color(self._hover_base_line, accent_line, 0.65)
                if hovered or self._pressed
                else list(self._hover_base_line)
            )

        if "elevation" in self._hover_properties and self._hover_base_elevation is not None:
            elevation_delta = self.hover_elevation_delta
            if self._pressed:
                elevation_delta = min(float(self.hover_elevation_delta or 0), float(self.press_elevation_delta or 0))
            targets["elevation"] = (
                self._hover_base_elevation + float(elevation_delta or 0)
                if hovered or self._pressed
                else self._hover_base_elevation
            )

        return targets

    def _default_hover_value(self, name):
        if name == "md_bg_color":
            return list(self._hover_base_bg or [1, 1, 1, 1])
        if name == "line_color":
            return list(self._hover_base_line or [0, 0, 0, 0])
        if name == "elevation":
            return float(self._hover_base_elevation or 0)
        return None

    @staticmethod
    def _value_has_none(value):
        if value is None:
            return True
        if isinstance(value, (list, tuple)):
            return any(item is None for item in value)
        return False

    def _ensure_animatable_sources(self, targets):
        for name in targets:
            current_value = getattr(self, name, None)
            if not self._value_has_none(current_value):
                continue
            default_value = self._default_hover_value(name)
            if default_value is not None:
                setattr(self, name, default_value)

    def _set_hover_state(self, hovered, animated=True):
        self._capture_hover_base()
        if hovered == self._hovered and not self._pressed:
            return
        self._hovered = hovered

        targets = self._build_hover_targets(hovered)
        if not targets:
            return

        Animation.cancel_all(self)
        if not animated:
            for name, value in targets.items():
                setattr(self, name, value)
            return

        self._ensure_animatable_sources(targets)
        Animation(
            d=float(self.hover_duration or 0.16),
            t="out_quad",
            **targets,
        ).start(self)

    def _handle_mouse_pos(self, _window, pos):
        if (
            not self.hover_enabled
            or getattr(self, "disabled", False)
            or self.parent is None
            or not self.get_root_window()
        ):
            self._set_hover_state(False, animated=False)
            return

        local = self.to_widget(*pos)
        self._set_hover_state(self.collide_point(*local), animated=True)

    def _set_pressed_state(self, pressed, animated=True):
        if not self.press_enabled or pressed == self._pressed:
            return
        self._pressed = pressed
        targets = self._build_hover_targets(self._hovered)
        if not targets:
            return

        Animation.cancel_all(self)
        if not animated:
            for name, value in targets.items():
                setattr(self, name, value)
            return

        self._ensure_animatable_sources(targets)
        Animation(
            d=min(float(self.hover_duration or 0.16), 0.10),
            t="out_quad",
            **targets,
        ).start(self)

    def on_touch_down(self, touch):
        handled = super().on_touch_down(touch)
        if (
            self.press_enabled
            and not getattr(self, "disabled", False)
            and self.collide_point(*touch.pos)
        ):
            self._set_pressed_state(True, animated=True)
        return handled

    def on_touch_up(self, touch):
        handled = super().on_touch_up(touch)
        if self.press_enabled and self._pressed:
            hovered = False
            try:
                hovered = self.collide_point(*touch.pos)
            except Exception:
                hovered = self._hovered
            self._hovered = hovered
            self._set_pressed_state(False, animated=True)
        return handled


class HoverCard(HoverFeedbackBehavior, MDCard):
    pass


class HoverRaisedButton(HoverFeedbackBehavior, MDRaisedButton):
    pass


class HoverTooltipRaisedButton(HoverFeedbackBehavior, TooltipRaisedButton):
    pass


class HoverTooltipIconButton(HoverFeedbackBehavior, TooltipIconButton):
    pass


Factory.register("HoverCard", cls=HoverCard)
Factory.register("HoverRaisedButton", cls=HoverRaisedButton)
Factory.register("HoverTooltipRaisedButton", cls=HoverTooltipRaisedButton)
Factory.register("HoverTooltipIconButton", cls=HoverTooltipIconButton)
