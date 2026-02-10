from kivy.uix.screenmanager import ScreenManager

from app_base import BaseApp
from database.provider import get_db
from manager.manager_screen import SalesScreen
from user.login import LoginScreen
from utils.sales_history_screen import SalesHistoryScreen
from utils.losses_screen import LossesScreen
from utils.losses_history_screen import LossesHistoryScreen


class ManagerApp(BaseApp):
    def build(self):
        self.title = 'MERCEARIA - MANAGER'
        self.icon = 'icon/icon4.ico'

        self.db = get_db()

        sm = ScreenManager()
        sm.add_widget(LoginScreen(
            name='login',
            allowed_roles=['manager'],
            allow_admin_setup=False,
            success_screen='manager',
        ))
        sm.add_widget(SalesScreen(name='manager'))
        sm.add_widget(SalesHistoryScreen(db=self.db, name='sales_history'))
        sm.add_widget(LossesScreen(db=self.db, name='losses'))
        sm.add_widget(LossesHistoryScreen(db=self.db, name='losses_history'))
        sm.current = 'login'
        return sm


if __name__ == '__main__':
    ManagerApp().run()
