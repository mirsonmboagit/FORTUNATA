import json
import os
import sys
from threading import Thread
from time import perf_counter
from utils.logging_setup import configure_runtime_logging

configure_runtime_logging()

from kivymd.app import MDApp
from kivy.config import Config

Config.set('kivy', 'window_icon', 'assets/icon/icon4.ico')
Config.set('kivy', 'exit_on_escape', '0')
# Forca modo janela: fullscreen estava a causar cliques desalinhados
# e quebra de layout em varias telas no ambiente atual.
Config.set('graphics', 'fullscreen', '0')
Config.set('graphics', 'minimum_width', '640')
Config.set('graphics', 'minimum_height', '420')

from kivy.core.window import Window
from kivy.metrics import dp
from kivy.properties import DictProperty
from kivy.core.text import LabelBase
from kivy.clock import Clock

from utils.theme import get_theme_tokens


if sys.platform.startswith('win'):
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            'MerceariaApp.SistemaEstoque.1.0'
        )
    except Exception:
        pass

os.environ["KIVY_NO_WM_PEN"] = "1"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Fontes customizadas
logo_font_path = os.path.join(BASE_DIR, 'assets','fonts', 'h2.ttf')
main_font_path = os.path.join(BASE_DIR, 'assets','fonts', 'yahoo.ttf')
joe_font_path = os.path.join(BASE_DIR, 'assets','fonts', 'joe.ttf')

if os.path.exists(logo_font_path):
    LabelBase.register(name='LogoFont', fn_regular=logo_font_path)
if os.path.exists(main_font_path):
    LabelBase.register(name='MainFont', fn_regular=main_font_path)
if os.path.exists(joe_font_path):
    LabelBase.register(name='JoeFont', fn_regular=joe_font_path)


DEFAULT_WINDOW_MIN_WIDTH = int(dp(920))
DEFAULT_WINDOW_MIN_HEIGHT = int(dp(560))
WINDOW_IDEAL_WIDTH = int(dp(1280))
WINDOW_IDEAL_HEIGHT = int(dp(800))
WINDOW_FLOOR_WIDTH = int(dp(680))
WINDOW_FLOOR_HEIGHT = int(dp(460))
WINDOW_MARGIN_X = int(dp(48))
WINDOW_MARGIN_Y = int(dp(56))
WINDOW_TARGET_MAX_WIDTH = int(dp(1500))
WINDOW_TARGET_MAX_HEIGHT = int(dp(920))


def _coerce_int(value, fallback):
    try:
        return int(float(value))
    except Exception:
        return int(fallback)


def _get_display_size():
    fallback = getattr(Window, "system_size", None) or Window.size or (
        DEFAULT_WINDOW_MIN_WIDTH,
        DEFAULT_WINDOW_MIN_HEIGHT,
    )
    if sys.platform.startswith("win"):
        try:
            import ctypes

            user32 = ctypes.windll.user32
            width = _coerce_int(user32.GetSystemMetrics(0), fallback[0])
            height = _coerce_int(user32.GetSystemMetrics(1), fallback[1])
            if width > 0 and height > 0:
                return width, height
        except Exception:
            pass
    return (
        max(1, _coerce_int(fallback[0], DEFAULT_WINDOW_MIN_WIDTH)),
        max(1, _coerce_int(fallback[1], DEFAULT_WINDOW_MIN_HEIGHT)),
    )


def _resolve_window_constraints():
    screen_w, screen_h = _get_display_size()

    usable_w = screen_w - WINDOW_MARGIN_X
    usable_h = screen_h - WINDOW_MARGIN_Y
    max_w = min(screen_w, max(WINDOW_FLOOR_WIDTH, usable_w))
    max_h = min(screen_h, max(WINDOW_FLOOR_HEIGHT, usable_h))
    min_w = min(DEFAULT_WINDOW_MIN_WIDTH, max_w)
    min_h = min(DEFAULT_WINDOW_MIN_HEIGHT, max_h)

    initial_w = max(min_w, min(WINDOW_IDEAL_WIDTH, WINDOW_TARGET_MAX_WIDTH, max_w))
    initial_h = max(min_h, min(WINDOW_IDEAL_HEIGHT, WINDOW_TARGET_MAX_HEIGHT, max_h))
    return {
        "screen_w": screen_w,
        "screen_h": screen_h,
        "min_w": int(min_w),
        "min_h": int(min_h),
        "max_w": int(max_w),
        "max_h": int(max_h),
        "initial_w": int(initial_w),
        "initial_h": int(initial_h),
    }


_WINDOW_CONSTRAINTS = _resolve_window_constraints()

Window.size = (
    _WINDOW_CONSTRAINTS["initial_w"],
    _WINDOW_CONSTRAINTS["initial_h"],
)
Window.minimum_width = _WINDOW_CONSTRAINTS["min_w"]
Window.minimum_height = _WINDOW_CONSTRAINTS["min_h"]
Window.fullscreen = False
try:
    Window.left = max(0, int((_WINDOW_CONSTRAINTS["screen_w"] - _WINDOW_CONSTRAINTS["initial_w"]) / 2))
    Window.top = max(0, int((_WINDOW_CONSTRAINTS["screen_h"] - _WINDOW_CONSTRAINTS["initial_h"]) / 2))
except Exception:
    pass


class BaseApp(MDApp):
    theme_tokens = DictProperty({})
    theme_settings_key = "theme_style"

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
        self.smart_monitor_enabled = True
        self.auto_banners_enabled = True
        self.theme_style = "Light"
        self._automation_ev = None
        self._automation_running = False
        self._screen_warmup_ev = None
        self._screen_warmup_queue = []
        self._startup_started_at = perf_counter()
        self._ignored_early_close = False
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
                self.smart_monitor_enabled = bool(data.get("smart_monitor_enabled", True))
                self.auto_banners_enabled = bool(data.get("auto_banners_enabled", True))
                theme_key = getattr(self, "theme_settings_key", "theme_style") or "theme_style"
                theme_style = data.get(theme_key, data.get("theme_style", self.theme_style))
                if theme_style in ("Light", "Dark"):
                    self.theme_style = theme_style
        except Exception:
            self.ai_enabled = True
            self.smart_monitor_enabled = True
            self.auto_banners_enabled = True
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
            theme_key = getattr(self, "theme_settings_key", "theme_style") or "theme_style"
            data = {}
            if os.path.exists(self._app_settings_path):
                try:
                    with open(self._app_settings_path, "r", encoding="utf-8") as f:
                        data = json.load(f) or {}
                except Exception:
                    data = {}
            data.update({
                "ai_enabled": bool(self.ai_enabled),
                "smart_monitor_enabled": bool(self.smart_monitor_enabled),
                "auto_banners_enabled": bool(self.auto_banners_enabled),
                theme_key: self.theme_style,
            })
            with open(self._app_settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def on_start(self):
        if self.title:
            Window.set_title(self.title)
        if os.path.exists('assets/icon/icon4.ico'):
            Window.set_icon('assets/icon/icon4.ico')
        Window.bind(on_request_close=self._handle_window_request_close)
        self._start_automation_tasks()

    def on_stop(self):
        if self._automation_ev:
            self._automation_ev.cancel()
            self._automation_ev = None
        if self._screen_warmup_ev:
            self._screen_warmup_ev.cancel()
            self._screen_warmup_ev = None
        try:
            Window.unbind(on_request_close=self._handle_window_request_close)
        except Exception:
            pass

    def _handle_window_request_close(self, *args):
        elapsed = perf_counter() - self._startup_started_at
        if elapsed < 8.0 and not self._ignored_early_close:
            self._ignored_early_close = True
            print(f"[BaseApp] Ignored early close request at {elapsed:.2f}s")
            return True
        return False

    def _run_automation_tasks(self, *args):
        if self._automation_running:
            return False
        if not self.db or not hasattr(self.db, "run_automation_tasks"):
            return False

        # Antes isto corria no arranque diretamente na thread da UI e deixava
        # a aplicacao lenta logo nos primeiros cliques.
        self._automation_running = True

        def worker():
            try:
                self.db.run_automation_tasks()
            except Exception as e:
                print(f"Erro ao executar automacoes locais: {e}")
            finally:
                self._automation_running = False

        Thread(target=worker, daemon=True).start()
        return True

    def _start_automation_tasks(self):
        if not self.db or not hasattr(self.db, "run_automation_tasks"):
            return
        Clock.schedule_once(self._run_automation_tasks, 0.35)
        if self._automation_ev:
            self._automation_ev.cancel()
        # Checagem leve a cada minuto; execução real respeita intervalos internos do DB.
        self._automation_ev = Clock.schedule_interval(self._run_automation_tasks, 60)

    def warmup_screens(self, screen_names, delay=0.14):
        ensure_screen = getattr(self, "ensure_screen", None)
        manager = getattr(self, "_screen_manager", None) or getattr(self, "root", None)
        if manager is None or not callable(ensure_screen):
            return False

        known = set(getattr(manager, "screen_names", []) or [])
        queued = set(self._screen_warmup_queue)
        added = False
        for screen_name in screen_names or []:
            if not screen_name or screen_name in known or screen_name in queued:
                continue
            self._screen_warmup_queue.append(screen_name)
            queued.add(screen_name)
            added = True

        if added and self._screen_warmup_ev is None:
            self._schedule_screen_warmup(delay)
        return added

    def _schedule_screen_warmup(self, delay):
        if self._screen_warmup_ev or not self._screen_warmup_queue:
            return
        wait = max(0.04, float(delay or 0.0))
        self._screen_warmup_ev = Clock.schedule_once(
            lambda dt, next_delay=wait: self._consume_screen_warmup(next_delay),
            wait,
        )

    def _consume_screen_warmup(self, delay):
        self._screen_warmup_ev = None
        if not self._screen_warmup_queue:
            return

        screen_name = self._screen_warmup_queue.pop(0)
        ensure_screen = getattr(self, "ensure_screen", None)
        if callable(ensure_screen):
            try:
                ensure_screen(screen_name)
            except Exception:
                pass

        if self._screen_warmup_queue:
            self._schedule_screen_warmup(delay)

    def change_screen_size(self, width, height):
        constraints = _resolve_window_constraints()
        min_w = constraints["min_w"]
        min_h = constraints["min_h"]
        max_w = constraints["max_w"]
        max_h = constraints["max_h"]

        if width < min_w or height < min_h:
            raise ValueError(
                f"Tamanho minimo permitido e {int(min_w)}x{int(min_h)}"
            )

        Window.size = (int(min(width, max_w)), int(min(height, max_h)))
        Window.minimum_width = min_w
        Window.minimum_height = min_h
        return True
