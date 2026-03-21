from kivy.uix.screenmanager import ScreenManager

from app_base import BaseApp
from database.provider import get_db
from user.login import ManagerLoginScreen


class ManagerApp(BaseApp):
    theme_settings_key = "manager_theme_style"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._screen_manager = None
        self._screen_factories = {}

    def build(self):
        self.title = 'MERCEARIA - MANAGER'
        self.icon = 'icon/icon4.ico'

        self.db = get_db()

        sm = ScreenManager()
        self._screen_manager = sm
        sm.add_widget(ManagerLoginScreen(
            db=self.db,
            name='login',
            success_screen='manager',
        ))
        self._screen_factories = {
            'manager': self._build_manager_screen,
            'sales_history': self._build_sales_history_screen,
            'losses': self._build_losses_screen,
            'losses_history': self._build_losses_history_screen,
        }
        sm.current = 'login'
        return sm

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

    def _build_manager_screen(self):
        from manager.manager_screen import SalesScreen
        return SalesScreen(db=self.db, name='manager')

    def _build_sales_history_screen(self):
        from utils.sales_history_screen import SalesHistoryScreen
        return SalesHistoryScreen(db=self.db, name='sales_history')

    def _build_losses_screen(self):
        from utils.losses_screen import LossesScreen
        return LossesScreen(db=self.db, name='losses')

    def _build_losses_history_screen(self):
        from utils.losses_history_screen import LossesHistoryScreen
        return LossesHistoryScreen(db=self.db, name='losses_history')


if __name__ == '__main__':
    try:
        ManagerApp().run()
    except KeyboardInterrupt:
        pass
