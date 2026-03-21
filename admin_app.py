from kivy.uix.screenmanager import ScreenManager

from app_base import BaseApp
from database.provider import get_db
from user.login import AdminLoginScreen


class AdminApp(BaseApp):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._screen_manager = None
        self._screen_factories = {}

    def build(self):
        self.title = 'MERCEARIA - ADMIN'
        self.icon = 'assets/icon/icon4.ico'

        self.db = get_db()

        sm = ScreenManager()
        self._screen_manager = sm
        sm.add_widget(AdminLoginScreen(
            db=self.db,
            name='login',
        ))
        self._screen_factories = {
            'admin_home': self._build_admin_home_screen,
            'admin': self._build_admin_screen,
            'settings': self._build_settings_screen,
            'reports': self._build_reports_screen,
            'sales_history': self._build_sales_history_screen,
            'losses': self._build_losses_screen,
            'losses_history': self._build_losses_history_screen,
            'restock': self._build_restock_screen,
            'restock_history': self._build_restock_history_screen,
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

    def _build_admin_home_screen(self):
        from admin.admin_home_screen import AdminHomeScreen
        return AdminHomeScreen(db=self.db, name='admin_home')

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

    def _build_losses_history_screen(self):
        from utils.losses_history_screen import LossesHistoryScreen
        return LossesHistoryScreen(db=self.db, name='losses_history')

    def _build_restock_screen(self):
        from utils.restock_screen import RestockScreen
        return RestockScreen(db=self.db, name='restock')

    def _build_restock_history_screen(self):
        from utils.restock_history_screen import RestockHistoryScreen
        return RestockHistoryScreen(db=self.db, name='restock_history')


if __name__ == '__main__':
    try:
        AdminApp().run()
    except KeyboardInterrupt:
        pass
