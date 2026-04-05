from kivy.animation import Animation
from kivy.clock import Clock
from kivy.factory import Factory
from kivy.metrics import dp
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivymd.uix.button import MDFloatingActionButton, MDIconButton
from kivymd.uix.tooltip import MDTooltip

DEFAULT_TOOLTIP_DELAY = 0.18


class TooltipCleanupBehavior:
    hint_text = StringProperty("")

    def __init__(self, **kwargs):
        kwargs.setdefault("tooltip_display_delay", DEFAULT_TOOLTIP_DELAY)
        super().__init__(**kwargs)
        available_properties = set(self.properties())
        bindings = {}
        for property_name, callback in (
            ("hint_text", self._sync_tooltip_text),
            ("text", self._sync_tooltip_text),
            ("parent", self._handle_tooltip_context_change),
            ("disabled", self._handle_tooltip_context_change),
        ):
            if property_name in available_properties:
                bindings[property_name] = callback
        if bindings:
            self.bind(**bindings)
        self._sync_tooltip_text()

    def _sync_tooltip_text(self, *_args):
        if self.tooltip_text:
            return
        fallback = (self.hint_text or getattr(self, "text", "") or "").strip()
        if fallback:
            self.tooltip_text = fallback

    def _handle_tooltip_context_change(self, *_args):
        if self.parent is None or getattr(self, "disabled", False):
            self._dismiss_tooltip_immediately()

    def on_touch_down(self, touch):
        self._dismiss_tooltip_immediately()
        return super().on_touch_down(touch)

    def on_parent(self, widget, parent):
        if hasattr(super(), "on_parent"):
            super().on_parent(widget, parent)
        if parent is None:
            self._dismiss_tooltip_immediately()

    def _dismiss_tooltip_immediately(self):
        Clock.unschedule(self.display_tooltip)
        Clock.unschedule(self.animation_tooltip_show)
        Clock.unschedule(self.animation_tooltip_dismiss)
        tooltip = getattr(self, "_tooltip", None)
        if tooltip is None:
            return
        Animation.cancel_all(tooltip)
        parent = getattr(tooltip, "parent", None)
        if parent is not None:
            try:
                parent.remove_widget(tooltip)
            except Exception:
                pass
        self._tooltip = None


class TooltipIconButton(TooltipCleanupBehavior, MDIconButton, MDTooltip):
    """MDIconButton com tooltip curto para desktop."""


class TooltipFloatingActionButton(TooltipCleanupBehavior, MDFloatingActionButton, MDTooltip):
    """MDFloatingActionButton com tooltip curto para desktop."""


class DraggableTooltipFloatingActionButton(TooltipFloatingActionButton):
    """FAB com suporte a arrasto dentro do container pai."""

    drag_enabled = BooleanProperty(True)
    drag_threshold = NumericProperty(dp(8))
    drag_margin = NumericProperty(dp(8))
    is_dragging = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._drag_touch_uid = None
        self._drag_origin = None
        self._widget_origin = None

    def _clamp_to_parent(self):
        parent = self.parent
        if parent is None:
            return
        max_x = max(self.drag_margin, parent.width - self.width - self.drag_margin)
        max_y = max(self.drag_margin, parent.height - self.height - self.drag_margin)
        self.x = min(max(self.x, self.drag_margin), max_x)
        self.y = min(max(self.y, self.drag_margin), max_y)

    def on_touch_down(self, touch):
        handled = super().on_touch_down(touch)
        if (
            not self.drag_enabled
            or self.disabled
            or not self.collide_point(*touch.pos)
        ):
            return handled
        self._drag_touch_uid = touch.uid
        self._drag_origin = tuple(touch.pos)
        self._widget_origin = tuple(self.pos)
        self.is_dragging = False
        return True

    def on_touch_move(self, touch):
        if touch.uid != self._drag_touch_uid:
            return super().on_touch_move(touch)

        if self.parent is None or self._drag_origin is None or self._widget_origin is None:
            return True

        delta_x = touch.x - self._drag_origin[0]
        delta_y = touch.y - self._drag_origin[1]
        if not self.is_dragging:
            if (abs(delta_x) + abs(delta_y)) < self.drag_threshold:
                return super().on_touch_move(touch)
            Animation.cancel_all(self)
            self._dismiss_tooltip_immediately()
            self.is_dragging = True
            self.pos_hint = {}

        self.pos = (
            self._widget_origin[0] + delta_x,
            self._widget_origin[1] + delta_y,
        )
        self._clamp_to_parent()
        return True

    def on_touch_up(self, touch):
        if touch.uid == self._drag_touch_uid:
            was_dragging = self.is_dragging
            self._drag_touch_uid = None
            self._drag_origin = None
            self._widget_origin = None
            self.is_dragging = False
            if was_dragging:
                self.state = "normal"
                self._clamp_to_parent()
                return True
        return super().on_touch_up(touch)


Factory.register("TooltipIconButton", cls=TooltipIconButton)
Factory.register("TooltipFloatingActionButton", cls=TooltipFloatingActionButton)
Factory.register("DraggableTooltipFloatingActionButton", cls=DraggableTooltipFloatingActionButton)
