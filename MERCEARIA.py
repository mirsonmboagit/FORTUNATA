import os
import sys

if sys.platform.startswith('win'):
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            'MerceariaApp.SistemaEstoque.1.0'
        )
    except Exception:
        pass


from kivy.config import Config
Config.set('kivy', 'window_icon', 'icon4.ico')

os.environ["KIVY_NO_WM_PEN"] = "1"


# ✅ Registrar fontes customizadas
from kivy.core.text import LabelBase

# Obter o diretório base do projeto
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Construir caminhos absolutos para as fontes
logo_font_path = os.path.join(BASE_DIR, 'fonts', 'h2.ttf')
main_font_path = os.path.join(BASE_DIR, 'fonts', 'yahoo.ttf')

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


# ✅ KivyMD App
from kivymd.app import MDApp

from kivy.uix.screenmanager import ScreenManager
from kivy.core.window import Window
from kivy.metrics import dp

from database.database import Database
from admin.admin_screen import AdminScreen
from manager.manager_screen import SalesScreen
from user.login import LoginScreen
from utils.reports_screen import ReportsScreen
from utils.sales_history_screen import SalesHistoryScreen
from utils.settings import AdminSettingsScreen


screen_w, screen_h = Window.system_size

ideal_width  = int(screen_w * 0.82)
ideal_height = int(screen_h * 0.82)

Window.size = (
    max(dp(1150), min(ideal_width,  dp(1500))),
    max(dp(680),  min(ideal_height, dp(920)))
)

Window.minimum_width  = dp(1000)
Window.minimum_height = dp(580)


db = Database()
db.setup()


class MainApp(MDApp):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.current_user = None
        self.current_role = None
        self.db = db
        self._ai_notifications_seen_key = None
        self._ai_banners_shown = False
        
        # ============================================
        # CONFIGURAÇÃO DO TEMA KIVYMD
        # ============================================
        
        # Tema claro/escuro
        self.theme_cls.theme_style = "Light"  # "Light" ou "Dark"
        
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

    def build(self):
        self.title = 'MERCEARIA'
        self.icon = 'icon/icon4.ico'

        sm = ScreenManager()
        sm.add_widget(LoginScreen(name='login'))
        sm.add_widget(AdminScreen(name='admin'))
        sm.add_widget(SalesScreen(name='manager'))
        sm.add_widget(AdminSettingsScreen(app=self, name='settings'))
        sm.add_widget(ReportsScreen(name='reports'))
        sm.add_widget(SalesHistoryScreen(db=self.db, name='sales_history'))
       

        return sm

    def on_start(self):
        Window.set_title('MERCEARIA')

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

Para usar nos arquivos .kv:
    MDLabel:
        text: "MERCEARIA"
        font_name: "LogoFont"
    
    MDLabel:
        text: "Outros textos"
        font_name: "MainFont"

As fontes também podem ser usadas diretamente no código Python:
    label = MDLabel(text="Texto", font_name="MainFont")

IMPORTANTE: Se as fontes não forem encontradas, o sistema usará
Roboto (fonte padrão) automaticamente como fallback.

Estrutura esperada:
    seu_projeto/
    ├── MERCEARIA.py
    └── fonts/
        ├── h2.ttf
        └── yahoo.ttf
"""


if __name__ == '__main__':
    MainApp().run()
