import os
import sys
import json
from utils.logging_setup import configure_runtime_logging

configure_runtime_logging()

from kivymd.app import MDApp

from kivy.uix.screenmanager import ScreenManager
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import DictProperty

from kivy.core.text import LabelBase
from database.provider import get_db
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
Config.set('graphics', 'fullscreen', '0')
Config.set('graphics', 'minimum_width', '640')
Config.set('graphics', 'minimum_height', '420')

os.environ["KIVY_NO_WM_PEN"] = "1"

Builder.load_string(
    """
<MDIcon>:
    halign: "center"
    valign: "middle"
    text_size: self.size
"""
)

from user.login import AdminLoginScreen, ManagerLoginScreen
from user.profile_selector import ProfileSelectorScreen


# ✅ Registrar fontes customizadas

# Obter o diretório base do projeto
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Construir caminhos absolutos para as fontes
logo_font_path = os.path.join(BASE_DIR, 'fonts', 'h2.ttf')
main_font_path = os.path.join(BASE_DIR, 'fonts', 'yahoo.ttf')
joe_font_path = os.path.join(BASE_DIR, 'fonts', 'joe.ttf')

# Verificar se as fontes existem e registrá-las
if os.path.exists(logo_font_path):
    LabelBase.register(name='LogoFont', fn_regular=logo_font_path)
    print(f"✓ LogoFont carregada: {logo_font_path}")
else:
    print(f"⚠ Fonte não encontrada: {logo_font_path}")
    print("  Usando Roboto como fallback para LogoFont")

if os.path.exists(main_font_path):
    LabelBase.register(name='MainFont', fn_regular=main_font_path)
    print(f"✓ MainFont carregada: {main_font_path}")
else:
    print(f"⚠ Fonte não encontrada: {main_font_path}")
    print("  Usando Roboto como fallback para MainFont")

if os.path.exists(joe_font_path):
    LabelBase.register(name='JoeFont', fn_regular=joe_font_path)
    print(f"✓ JoeFont carregada: {joe_font_path}")
else:
    print(f"⚠ Fonte não encontrada: {joe_font_path}")
    print("  Usando Roboto como fallback para JoeFont")


# ✅ KivyMD App


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
        "screen_w": int(screen_w),
        "screen_h": int(screen_h),
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
try:
    Window.left = max(0, int((_WINDOW_CONSTRAINTS["screen_w"] - _WINDOW_CONSTRAINTS["initial_w"]) / 2))
    Window.top = max(0, int((_WINDOW_CONSTRAINTS["screen_h"] - _WINDOW_CONSTRAINTS["initial_h"]) / 2))
except Exception:
    pass


class MainApp(MDApp):
    theme_tokens = DictProperty({})

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.current_user = None
        self.current_role = None
        self.db = get_db()
        self._screen_manager = None
        self._screen_factories = {}
        self._screen_warmup_ev = None
        self._screen_warmup_queue = []
        self._ai_notifications_seen_key = None
        self._ai_banners_shown = False
        self._ai_banners_last_key = None
        self.base_dir = BASE_DIR
        self._app_settings_path = os.path.join(self.base_dir, "app_settings.json")
        self.ai_enabled = True
        self.smart_monitor_enabled = True
        self.auto_banners_enabled = True
        self.theme_style = "Light"
        self._load_app_settings()
        self.apply_theme(self.theme_style, persist=False)
        
        # ============================================
        # CONFIGURAÇÃO DO TEMA KIVYMD
        # ============================================
        
        # Paleta de cores primária (laranja)
        self.theme_cls.primary_palette = "Orange"
        self.theme_cls.primary_hue = "700"  # Tons disponíveis: 50-900, A100-A700
        
        # Paleta de cores de destaque (opcional - complementa o laranja)
        self.theme_cls.accent_palette = "DeepOrange"
        self.theme_cls.accent_hue = "500"
        
        # Cor de fundo da aplicação (opcional)
        # self.theme_cls.backgroundColor = [0.95, 0.95, 0.95, 1]
        
        # ============================================
        # CONFIGURAÇÕES ADICIONAIS DE MATERIAL DESIGN
        # ============================================
        
        # Usar Material Design 3 (opcional - mais moderno)
        # self.theme_cls.material_style = "M3"
        
        # Duração dos efeitos ripple (opcional)
        # self.theme_cls.ripple_duration_in = 0.3
        # self.theme_cls.ripple_duration_out = 0.6

    def _load_app_settings(self):
        try:
            if os.path.exists(self._app_settings_path):
                with open(self._app_settings_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.ai_enabled = bool(data.get("ai_enabled", True))
                self.smart_monitor_enabled = bool(data.get("smart_monitor_enabled", True))
                self.auto_banners_enabled = bool(data.get("auto_banners_enabled", True))
                theme_style = data.get("theme_style", self.theme_style)
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
            data = {
                "ai_enabled": bool(self.ai_enabled),
                "smart_monitor_enabled": bool(self.smart_monitor_enabled),
                "auto_banners_enabled": bool(self.auto_banners_enabled),
                "theme_style": self.theme_style,
            }
            with open(self._app_settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def build(self):
        self.title = 'MERCEARIA'
        self.icon = 'icon/icon4.ico'

        sm = ScreenManager()
        self._screen_manager = sm
        sm.add_widget(ProfileSelectorScreen(name='login'))
        sm.add_widget(AdminLoginScreen(
            db=self.db,
            name='login_admin',
            back_screen='login',
            success_screen='admin_home',
        ))
        sm.add_widget(ManagerLoginScreen(
            db=self.db,
            name='login_manager',
            back_screen='login',
            success_screen='manager',
        ))
        self._screen_factories = {
            'admin_home': self._build_admin_home_screen,
            'manager': self._build_manager_screen,
            'admin': self._build_admin_screen,
            'settings': self._build_settings_screen,
            'reports': self._build_reports_screen,
            'sales_history': self._build_sales_history_screen,
            'losses': self._build_losses_screen,
            'restock': self._build_restock_screen,
            'losses_history': self._build_losses_history_screen,
            'restock_history': self._build_restock_history_screen,
        }
        sm.current = 'login'
        return sm

    def on_stop(self):
        if self._screen_warmup_ev:
            self._screen_warmup_ev.cancel()
            self._screen_warmup_ev = None

    def ensure_screen(self, name):
        manager = self._screen_manager or self.root
        if manager is None:
            return None
        if name in manager.screen_names:
            return manager.get_screen(name)
        factory = self._screen_factories.get(name)
        if factory is None:
            return None
        screen = factory()
        if screen is None:
            return None
        manager.add_widget(screen)
        return screen

    def warmup_screens(self, screen_names, delay=0.14):
        manager = self._screen_manager or self.root
        if manager is None:
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
        try:
            self.ensure_screen(screen_name)
        except Exception:
            pass
        if self._screen_warmup_queue:
            self._schedule_screen_warmup(delay)

    def _build_admin_home_screen(self):
        from admin.admin_home_screen import AdminHomeScreen
        return AdminHomeScreen(db=self.db, name='admin_home')

    def _build_manager_screen(self):
        from manager.manager_screen import SalesScreen
        return SalesScreen(db=self.db, name='manager')

    def _build_admin_screen(self):
        from admin.admin_screen import AdminScreen
        return AdminScreen(db=self.db, name='admin')

    def _build_settings_screen(self):
        from utils.settings import AdminSettingsScreen
        return AdminSettingsScreen(app=self, name='settings')

    def _build_reports_screen(self):
        from utils.reports_screen import ReportsScreen
        return ReportsScreen(db=self.db, name='reports')

    def _build_sales_history_screen(self):
        from utils.sales_history_screen import SalesHistoryScreen
        return SalesHistoryScreen(db=self.db, name='sales_history')

    def _build_losses_screen(self):
        from utils.losses_screen import LossesScreen
        return LossesScreen(db=self.db, name='losses')

    def _build_restock_screen(self):
        from utils.restock_screen import RestockScreen
        return RestockScreen(db=self.db, name='restock')

    def _build_losses_history_screen(self):
        from utils.losses_history_screen import LossesHistoryScreen
        return LossesHistoryScreen(db=self.db, name='losses_history')

    def _build_restock_history_screen(self):
        from utils.restock_history_screen import RestockHistoryScreen
        return RestockHistoryScreen(db=self.db, name='restock_history')

    def on_start(self):
        Window.set_title('MERCEARIA')

        if os.path.exists('icon/icon4.ico'):
            Window.set_icon('icon/icon4.ico')

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


# ============================================
# PALETAS DE CORES ALTERNATIVAS
# ============================================
"""
Para mudar as cores do app, você pode modificar as configurações
no __init__ do MainApp. Aqui estão algumas sugestões:

TEMA AZUL (Profissional):
    self.theme_cls.primary_palette = "Blue"
    self.theme_cls.primary_hue = "700"
    self.theme_cls.accent_palette = "LightBlue"

TEMA VERDE (Natural):
    self.theme_cls.primary_palette = "Green"
    self.theme_cls.primary_hue = "600"
    self.theme_cls.accent_palette = "LightGreen"

TEMA VERMELHO (Vibrante):
    self.theme_cls.primary_palette = "Red"
    self.theme_cls.primary_hue = "700"
    self.theme_cls.accent_palette = "Pink"

TEMA ROXO (Elegante):
    self.theme_cls.primary_palette = "DeepPurple"
    self.theme_cls.primary_hue = "500"
    self.theme_cls.accent_palette = "Purple"

TEMA ESCURO (Dark Mode):
    self.theme_cls.theme_style = "Dark"
    self.theme_cls.primary_palette = "Teal"
    self.theme_cls.primary_hue = "400"

Paletas disponíveis:
Red, Pink, Purple, DeepPurple, Indigo, Blue, LightBlue, Cyan,
Teal, Green, LightGreen, Lime, Yellow, Amber, Orange, DeepOrange,
Brown, Gray, BlueGray
"""


# ============================================
# FONTES CUSTOMIZADAS
# ============================================
"""
As fontes foram registradas no início do arquivo:

- LogoFont (fonts/h2.ttf): Use para o texto "MERCEARIA" e outros logos
- MainFont (fonts/yahoo.ttf): Use para todo o resto do texto
- JoeFont (fonts/joe.ttf): Fonte customizada Joe

Para usar nos arquivos .kv:
    MDLabel:
        text: "MERCEARIA"
        font_name: "LogoFont"
    
    MDLabel:
        text: "Outros textos"
        font_name: "MainFont"
    
    MDLabel:
        text: "Texto especial"
        font_name: "JoeFont"

As fontes também podem ser usadas diretamente no código Python:
    label = MDLabel(text="Texto", font_name="MainFont")
    label_joe = MDLabel(text="Texto especial", font_name="JoeFont")

IMPORTANTE: Se as fontes não forem encontradas, o sistema usará
Roboto (fonte padrão) automaticamente como fallback.

Estrutura esperada:
    seu_projeto/
    ├── MERCEARIA.py
    └── fonts/
        ├── h2.ttf
        ├── yahoo.ttf
        └── joe.ttf  ← NOVA FONTE
"""


if __name__ == '__main__':
    try:
        MainApp().run()
    except KeyboardInterrupt:
        pass
