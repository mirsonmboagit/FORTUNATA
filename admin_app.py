from kivy.uix.screenmanager import ScreenManager

from app_base import BaseApp
from database.provider import get_db
from admin.admin_screen import AdminScreen
from user.login import LoginScreen
from utils.reports_screen import ReportsScreen
from utils.sales_history_screen import SalesHistoryScreen
from utils.losses_screen import LossesScreen
from utils.losses_history_screen import LossesHistoryScreen
from utils.restock_screen import RestockScreen
from utils.restock_history_screen import RestockHistoryScreen
from utils.settings import AdminSettingsScreen


class AdminApp(BaseApp):
    def build(self):
        self.title = 'MERCEARIA - ADMIN'
        self.icon = 'icon/icon4.ico'

        self.db = get_db()

        sm = ScreenManager()
        sm.add_widget(LoginScreen(
            name='login',
            allowed_roles=['admin'],
            allow_admin_setup=True,
            success_screen='admin',
        ))
        sm.add_widget(AdminScreen(name='admin'))
        sm.add_widget(AdminSettingsScreen(app=self, name='settings'))
        sm.add_widget(ReportsScreen(name='reports'))
        sm.add_widget(SalesHistoryScreen(db=self.db, name='sales_history'))
        sm.add_widget(LossesScreen(db=self.db, name='losses'))
        sm.add_widget(LossesHistoryScreen(db=self.db, name='losses_history'))
        sm.add_widget(RestockScreen(db=self.db, name='restock'))
        sm.add_widget(RestockHistoryScreen(db=self.db, name='restock_history'))
        sm.current = 'login'
        return sm


if __name__ == '__main__':
    AdminApp().run()
