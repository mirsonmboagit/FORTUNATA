from kivy.uix.screenmanager import ScreenManager
from kivy.clock import Clock

from app_base import BaseApp
from database.provider import get_db
from user.login import ManagerLoginScreen
from utils.config.paths import asset_path
from version import __version__


class ManagerApp(BaseApp):
    # App do gerente: fluxo focado em vendas e historicos.
    theme_settings_key = "manager_theme_style"

    # O gerente trabalha durante longos periodos nesta tela. Mantemos, por isso,
    # texto maior que o padrao do KivyMD e contraste forte no tema claro.
    _MANAGER_LIGHT_TEXT = {
        "text_primary": [0.0, 0.0, 0.0, 1],
        "text_secondary": [0.08, 0.08, 0.08, 1],
        "text_muted": [0.18, 0.18, 0.18, 1],
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._increase_manager_typography()
        self._screen_manager = None
        self._screen_factories = {}

    def apply_theme(self, style, persist=True):
        super().apply_theme(style, persist=persist)
        if self.theme_style == "Light":
            tokens = dict(self.theme_tokens)
            tokens.update(self._MANAGER_LIGHT_TEXT)
            self.theme_tokens = tokens

    def _increase_manager_typography(self):
        """Aumenta estilos pequenos somente no processo do aplicativo Manager."""
        minimum_sizes = {
            "Body1": 17,
            "Body2": 15,
            "Button": 15,
            "Caption": 14,
            "Subtitle1": 17,
            "Subtitle2": 15,
        }
        for style_name, minimum_size in minimum_sizes.items():
            style = self.theme_cls.font_styles.get(style_name)
            if style and len(style) > 1:
                enlarged_style = list(style)
                enlarged_style[1] = max(enlarged_style[1], minimum_size)
                self.theme_cls.font_styles[style_name] = enlarged_style

    def build(self):
        self.title = f"{self.system_name} {__version__} - MANAGER"
        self.icon = str(asset_path('icon', 'manager.ico'))

        self.db = get_db()

        sm = ScreenManager()
        self._screen_manager = sm
        sm.add_widget(ManagerLoginScreen(
            db=self.db,
            name='login',
            success_screen='manager',
        ))
        # As telas secundarias ficam em factories para reduzir o arranque.
        self._screen_factories = {
            'manager': self._build_manager_screen,
            'sales_history': self._build_sales_history_screen,
            'losses': self._build_losses_screen,
            'losses_history': self._build_losses_history_screen,
        }
        sm.current = 'login'
        Clock.schedule_once(lambda _dt: self.refresh_language(sm), 0)
        return sm

    def ensure_screen(self, name):
        # Cria a tela pedida somente na primeira abertura.
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
        Clock.schedule_once(lambda _dt, target=screen: self.refresh_language(target), 0)
        return screen

    def _build_manager_screen(self):
        from manager.manager_screen import SalesScreen
        return SalesScreen(db=self.db, name='manager')

    def _build_sales_history_screen(self):
        from utils.screens.sales_history_screen import SalesHistoryScreen
        return SalesHistoryScreen(db=self.db, name='sales_history')

    def _build_losses_screen(self):
        from utils.screens.losses_screen import LossesScreen
        return LossesScreen(db=self.db, name='losses')

    def _build_losses_history_screen(self):
        from utils.screens.losses_history_screen import LossesHistoryScreen
        return LossesHistoryScreen(db=self.db, name='losses_history')


if __name__ == '__main__':
    try:
        ManagerApp().run()
    except KeyboardInterrupt:
        pass
