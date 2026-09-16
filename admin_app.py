from kivy.uix.screenmanager import ScreenManager
from kivy.clock import Clock
from threading import Thread

from app_base import BaseApp
from database.provider import get_db
from licensing.offline import OfflineLicenseClient
from licensing.control_inbox import poll_control_inbox
from user.login import UnifiedLoginScreen
from utils.config.paths import asset_path
from version import __version__


class StoreApp(BaseApp):
    """Aplicativo desktop unico para administradores e gerentes."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._screen_manager = None
        self._screen_factories = {}
        self.license_client = None
        self._license_control_sync_event = None
        self._license_control_sync_running = False

    def build(self):
        self.title = f"{self.system_name} {__version__}"
        self.icon = str(asset_path('icon', 'admin.ico'))

        self.db = get_db()
        # A licenca e verificada localmente antes do login. As contas de
        # administrador e gerente continuam na base SQLite da loja.
        self.license_client = OfflineLicenseClient.from_runtime()

        sm = ScreenManager()
        self._screen_manager = sm
        sm.add_widget(UnifiedLoginScreen(
            db=self.db,
            license_client=self.license_client,
            name='login',
        ))
        # Cada painel e criado apenas quando o perfil autenticado o necessita.
        self._screen_factories = {
            'admin_home': self._build_admin_home_screen,
            'admin': self._build_admin_screen,
            'manager': self._build_manager_screen,
            'settings': self._build_settings_screen,
            'reports': self._build_reports_screen,
            'sales_history': self._build_sales_history_screen,
            'losses': self._build_losses_screen,
            'losses_history': self._build_losses_history_screen,
            'restock': self._build_restock_screen,
            'restock_history': self._build_restock_history_screen,
        }
        sm.current = 'login'
        Clock.schedule_once(lambda _dt: self.refresh_language(sm), 0)
        # A caixa de controlo e consultada pela aplicacao inteira, e nao
        # apenas enquanto a tela de login esta aberta. Assim uma suspensao,
        # renovacao, reativacao ou cancelamento emitido pelo superadmin entra
        # em vigor sem qualquer passo do administrador.
        Clock.schedule_once(lambda _dt: self._sync_license_controls(), 0.5)
        self._license_control_sync_event = Clock.schedule_interval(
            lambda _dt: self._sync_license_controls(), 30
        )
        return sm

    def _sync_license_controls(self):
        if self.license_client is None or self._license_control_sync_running:
            return
        self._license_control_sync_running = True

        def worker():
            try:
                report = poll_control_inbox(self.license_client)
                applied = int(getattr(report, "applied", 0) or 0)
            except Exception:
                applied = 0
            Clock.schedule_once(
                lambda _dt: self._finish_license_control_sync(applied), 0
            )

        Thread(target=worker, daemon=True).start()

    def _finish_license_control_sync(self, applied):
        self._license_control_sync_running = False
        if applied <= 0:
            return
        manager = self._screen_manager or self.root
        if manager is None or not manager.has_screen("login"):
            return
        # Uma alteracao recebida pode revogar o acesso de uma sessao que ja
        # esta aberta. Voltamos ao login e revalidamos antes de permitir
        # qualquer outra operacao.
        manager.current = "login"
        login = manager.get_screen("login")
        login._validate_desktop_license(show_activation=True)

    def on_stop(self):
        if self._license_control_sync_event is not None:
            self._license_control_sync_event.cancel()
            self._license_control_sync_event = None
        super().on_stop()

    def ensure_screen(self, name):
        # Reutiliza a tela se ela ja existir no ScreenManager.
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

    def _build_admin_home_screen(self):
        from admin.admin_home_screen import AdminHomeScreen
        return AdminHomeScreen(db=self.db, name='admin_home')

    def _build_admin_screen(self):
        from admin.admin_screen import AdminScreen
        return AdminScreen(db=self.db, name='admin')

    def _build_manager_screen(self):
        from manager.manager_screen import SalesScreen
        return SalesScreen(db=self.db, name='manager')

    def _build_settings_screen(self):
        from utils.screens.settings import AdminSettingsScreen
        return AdminSettingsScreen(app=self, name='settings')

    def _build_reports_screen(self):
        from utils.screens.reports_screen import ReportsScreen
        return ReportsScreen(db=self.db, name='reports')

    def _build_sales_history_screen(self):
        from utils.screens.sales_history_screen import SalesHistoryScreen
        return SalesHistoryScreen(db=self.db, name='sales_history')

    def _build_losses_screen(self):
        from utils.screens.losses_screen import LossesScreen
        return LossesScreen(db=self.db, name='losses')

    def _build_losses_history_screen(self):
        from utils.screens.losses_history_screen import LossesHistoryScreen
        return LossesHistoryScreen(db=self.db, name='losses_history')

    def _build_restock_screen(self):
        from utils.screens.restock_screen import RestockScreen
        return RestockScreen(db=self.db, name='restock')

    def _build_restock_history_screen(self):
        from utils.screens.restock_history_screen import RestockHistoryScreen
        return RestockHistoryScreen(db=self.db, name='restock_history')


# Mantem o nome antigo para atalhos e imports existentes, sem voltar a criar
# uma aplicacao exclusiva do administrador.
AdminApp = StoreApp


if __name__ == '__main__':
    try:
        StoreApp().run()
    except KeyboardInterrupt:
        pass
