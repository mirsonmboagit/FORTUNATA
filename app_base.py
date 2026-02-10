import json
import os
import sys

from kivymd.app import MDApp
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.properties import DictProperty
from kivy.core.text import LabelBase
from kivy.config import Config

from utils.theme import get_theme_tokens


if sys.platform.startswith('win'):
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            'MerceariaApp.SistemaEstoque.1.0'
        )
    except Exception:
        pass

Config.set('kivy', 'window_icon', 'icon4.ico')
os.environ["KIVY_NO_WM_PEN"] = "1"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Fontes customizadas
logo_font_path = os.path.join(BASE_DIR, 'fonts', 'h2.ttf')
main_font_path = os.path.join(BASE_DIR, 'fonts', 'yahoo.ttf')
joe_font_path = os.path.join(BASE_DIR, 'fonts', 'joe.ttf')

if os.path.exists(logo_font_path):
    LabelBase.register(name='LogoFont', fn_regular=logo_font_path)
if os.path.exists(main_font_path):
    LabelBase.register(name='MainFont', fn_regular=main_font_path)
if os.path.exists(joe_font_path):
    LabelBase.register(name='JoeFont', fn_regular=joe_font_path)


screen_w, screen_h = Window.system_size
ideal_width = int(screen_w * 0.82)
ideal_height = int(screen_h * 0.82)

Window.size = (
    max(dp(1150), min(ideal_width, dp(1500))),
    max(dp(680), min(ideal_height, dp(920)))
)
Window.minimum_width = dp(1000)
Window.minimum_height = dp(580)


class BaseApp(MDApp):
    theme_tokens = DictProperty({})

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.current_user = None
        self.current_role = None
        self.db = None
        self._ai_notifications_seen_key = None
        self._ai_banners_shown = False
        self._ai_banners_last_key = None
        self.base_dir = BASE_DIR
        self._app_settings_path = os.path.join(self.base_dir, "app_settings.json")
        self.ai_enabled = True
        self.theme_style = "Light"
        self._load_app_settings()
        self.apply_theme(self.theme_style, persist=False)

        # Configuração do tema KivyMD
        self.theme_cls.primary_palette = "Orange"
        self.theme_cls.primary_hue = "700"
        self.theme_cls.accent_palette = "DeepOrange"
        self.theme_cls.accent_hue = "500"

    def _load_app_settings(self):
        try:
            if os.path.exists(self._app_settings_path):
                with open(self._app_settings_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.ai_enabled = bool(data.get("ai_enabled", True))
                theme_style = data.get("theme_style", self.theme_style)
                if theme_style in ("Light", "Dark"):
                    self.theme_style = theme_style
        except Exception:
            self.ai_enabled = True
            self.theme_style = "Light"

    def apply_theme(self, style, persist=True):
        style = "Dark" if style == "Dark" else "Light"
        self.theme_style = style
        self.theme_cls.theme_style = style
        self.theme_tokens = get_theme_tokens(style)
        if persist:
            self.save_app_settings()

    def save_app_settings(self):
        try:
            data = {
                "ai_enabled": bool(self.ai_enabled),
                "theme_style": self.theme_style,
            }
            with open(self._app_settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def on_start(self):
        if self.title:
            Window.set_title(self.title)
        if os.path.exists('icon/icon4.ico'):
            Window.set_icon('icon/icon4.ico')

    def change_screen_size(self, width, height):
        min_w, min_h = dp(1000), dp(580)

        if width < min_w or height < min_h:
            raise ValueError(
                f"Tamanho minimo permitido e {int(min_w)}x{int(min_h)}"
            )

        Window.size = (int(width), int(height))
        Window.minimum_width = min_w
        Window.minimum_height = min_h
        return True
