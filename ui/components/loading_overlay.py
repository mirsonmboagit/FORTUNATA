from collections import OrderedDict

from kivy.animation import Animation
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.floatlayout import FloatLayout
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.spinner import MDSpinner


def _theme_tokens():
    try:
        from kivy.app import App

        app = App.get_running_app()
    except Exception:
        app = None
    return getattr(app, "theme_tokens", {}) if app else {}


class ScreenLoadingOverlay(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (1, 1)
        self.opacity = 0
        self._active = False
        self._blocks_input = True

        with self.canvas.before:
            self._scrim_color = Color(0.05, 0.08, 0.14, 0.62)
            self._scrim_rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update_scrim_rect, size=self._update_scrim_rect)

        self._anchor = AnchorLayout(anchor_x="center", anchor_y="center")
        self.add_widget(self._anchor)

        self._panel = MDBoxLayout(
            orientation="vertical",
            size_hint=(None, None),
            spacing=dp(12),
            padding=[dp(24), dp(22), dp(24), dp(22)],
            adaptive_height=True,
        )
        self._panel.width = dp(336)
        self._panel.bind(
            pos=self._update_panel_canvas,
            size=self._update_panel_canvas,
            minimum_height=self._sync_panel_height,
        )
        with self._panel.canvas.before:
            self._panel_shadow_color = Color(0.02, 0.05, 0.10, 0.16)
            self._panel_shadow_rect = RoundedRectangle(radius=[dp(26)] * 4)
            self._panel_color = Color(1, 1, 1, 0.98)
            self._panel_rect = RoundedRectangle(radius=[dp(24)] * 4)

        self._spinner = MDSpinner(
            size_hint=(None, None),
            size=(dp(52), dp(52)),
            pos_hint={"center_x": 0.5},
            active=False,
        )
        self._title_label = MDLabel(
            text="A carregar...",
            halign="center",
            bold=True,
            theme_text_color="Custom",
            text_color=[0.12, 0.17, 0.24, 1],
            size_hint_y=None,
        )
        self._detail_label = MDLabel(
            text="Aguarde um instante.",
            halign="center",
            theme_text_color="Custom",
            text_color=[0.38, 0.44, 0.55, 1],
            size_hint_y=None,
        )
        self._title_label.bind(
            width=lambda inst, _value: setattr(inst, "text_size", (inst.width, None)),
            texture_size=lambda inst, size: setattr(inst, "height", size[1]),
        )
        self._detail_label.bind(
            width=lambda inst, _value: setattr(inst, "text_size", (inst.width, None)),
            texture_size=lambda inst, size: setattr(inst, "height", size[1]),
        )

        self._panel.add_widget(self._spinner)
        self._panel.add_widget(self._title_label)
        self._panel.add_widget(self._detail_label)
        self._anchor.add_widget(self._panel)

        self.bind(size=self._update_panel_width)
        self._sync_theme()
        self._update_panel_width()
        self._update_panel_canvas()

    def _update_scrim_rect(self, *_args):
        self._scrim_rect.pos = self.pos
        self._scrim_rect.size = self.size

    def _sync_panel_height(self, *_args):
        self._panel.height = max(dp(170), self._panel.minimum_height)
        self._update_panel_canvas()

    def _update_panel_width(self, *_args):
        available = max(float(self.width or 0) - dp(48), dp(260))
        self._panel.width = min(dp(380), available)
        self._update_text_widths()
        self._update_panel_canvas()

    def _update_text_widths(self):
        text_width = max(self._panel.width - dp(24), dp(180))
        self._title_label.text_size = (text_width, None)
        self._detail_label.text_size = (text_width, None)

    def _update_panel_canvas(self, *_args):
        x, y = self._panel.pos
        width, height = self._panel.size
        self._panel_shadow_rect.pos = (x, y - dp(8))
        self._panel_shadow_rect.size = (width, height + dp(8))
        self._panel_rect.pos = (x, y)
        self._panel_rect.size = (width, height)

    def _sync_theme(self):
        tokens = _theme_tokens()
        panel_color = list(tokens.get("card", [1, 1, 1, 0.98]))
        if len(panel_color) < 4:
            panel_color = (panel_color + [1, 1, 1, 1])[:4]
        panel_color[3] = 0.98
        self._panel_color.rgba = panel_color
        self._spinner.color = list(tokens.get("primary", [0.18, 0.42, 0.78, 1]))
        self._title_label.text_color = list(tokens.get("text_primary", [0.12, 0.17, 0.24, 1]))
        self._detail_label.text_color = list(tokens.get("text_secondary", [0.38, 0.44, 0.55, 1]))

    def set_active(self, active, message="", detail="", blocks_input=True):
        self._active = bool(active)
        self._blocks_input = bool(blocks_input)
        self._sync_theme()
        self._title_label.text = str(message or "A carregar...")
        detail_text = str(detail or "").strip() or "Aguarde um instante."
        self._detail_label.text = detail_text
        self._detail_label.opacity = 1 if detail_text else 0
        self._detail_label.height = self._detail_label.texture_size[1] if detail_text else 0
        self._spinner.active = self._active
        Animation.cancel_all(self)
        if self._active:
            Animation(opacity=1, d=0.18, t="out_quad").start(self)
            return
        Animation(opacity=0, d=0.16, t="out_quad").start(self)

    def on_touch_down(self, touch):
        if self._active and self._blocks_input:
            return True
        return False

    def on_touch_move(self, touch):
        if self._active and self._blocks_input:
            return True
        return False

    def on_touch_up(self, touch):
        if self._active and self._blocks_input:
            return True
        return False


class ScreenLoadingController:
    def __init__(self, host):
        self.host = host
        self.overlay = None
        self._entries = OrderedDict()

    def attach(self):
        if self.overlay is not None and self.overlay.parent is self.host:
            return self.overlay
        self.overlay = ScreenLoadingOverlay()
        self.host.add_widget(self.overlay)
        return self.overlay

    def show(self, key, message="A carregar...", detail="Aguarde um instante.", blocks_input=True):
        entry_key = str(key or "default")
        if entry_key in self._entries:
            self._entries.pop(entry_key, None)
        self._entries[entry_key] = {
            "message": str(message or "A carregar..."),
            "detail": str(detail or "Aguarde um instante."),
            "blocks_input": bool(blocks_input),
        }
        self._refresh()

    def hide(self, key):
        entry_key = str(key or "default")
        self._entries.pop(entry_key, None)
        self._refresh()

    def clear(self):
        self._entries.clear()
        self._refresh()

    def _refresh(self):
        overlay = self.attach()
        if not self._entries:
            overlay.set_active(False)
            return
        latest = next(reversed(self._entries.values()))
        overlay.set_active(
            True,
            latest.get("message"),
            latest.get("detail"),
            blocks_input=latest.get("blocks_input", True),
        )
