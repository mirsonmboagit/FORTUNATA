"""Ponto de entrada exclusivo do APK SIGE MPE Manager Mobile."""

from __future__ import annotations

from kivy.clock import Clock
from kivy.uix.screenmanager import ScreenManager

from app_base import BaseApp
from database.client import DatabaseClient
from mobile.manager.connection_screen import MobileConnectionScreen
from mobile.manager.sales_screen import MobileManagerSalesScreen
from user.login import ManagerLoginScreen
from utils.config.app_config import get_runtime_config, has_remote_connection
from utils.config.paths import is_mobile_runtime
from version import __version__


class MobileManagerApp(BaseApp):
    """Cliente Android do gerente; usa sempre a API, nunca SQLite local."""

    theme_settings_key = "manager_theme_style"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._screen_manager = None

    @staticmethod
    def _create_remote_client():
        """Nunca deixa o Manager Mobile abrir um SQLite de fallback."""
        return DatabaseClient(config=get_runtime_config(force_reload=True))

    def build(self):
        self.title = f"{self.system_name} {__version__} - MANAGER MOBILE"
        if not is_mobile_runtime():
            # Apenas facilita a demonstracao local; Android recebe o icone do
            # manifesto/Buildozer e nao deve tentar usar um .ico Windows.
            from utils.config.paths import asset_path

            self.icon = str(asset_path("icon", "manager.ico"))

        self.db = self._create_remote_client()
        manager = ScreenManager()
        self._screen_manager = manager
        manager.add_widget(MobileConnectionScreen(name="mobile_connection"))
        manager.add_widget(ManagerLoginScreen(
            db=self.db,
            name="login",
            success_screen="mobile_manager",
        ))
        manager.add_widget(MobileManagerSalesScreen(
            db=self.db,
            name="mobile_manager",
        ))
        manager.current = "login" if has_remote_connection(force_reload=True) else "mobile_connection"
        Clock.schedule_once(lambda _dt: self.refresh_language(manager), 0)
        return manager

    def apply_mobile_connection(self):
        """Recria o cliente depois de o onboarding validar e guardar a API."""
        previous_db = self.db
        self.db = self._create_remote_client()
        if previous_db is not self.db:
            closer = getattr(previous_db, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    pass

        manager = self._screen_manager or self.root
        if not manager:
            return
        login = manager.get_screen("login")
        sales = manager.get_screen("mobile_manager")
        login.db = self.db
        sales.set_database(self.db)
        self.current_user = None
        self.current_role = None
        login.reset_fields()
        manager.current = "login"

    def open_mobile_connection(self):
        """Abre o onboarding e encerra a sessao actual antes de trocar API."""
        manager = self._screen_manager or self.root
        if not manager:
            return
        sales = manager.get_screen("mobile_manager")
        sales.clear_cart()
        setter = getattr(self.db, "set_active_user", None)
        if callable(setter):
            try:
                setter(None, None)
            except Exception:
                pass
        self.current_user = None
        self.current_role = None
        manager.get_screen("login").reset_fields()
        manager.current = "mobile_connection"

    def on_pause(self):
        # Mantem a sessao Kivy enquanto o Android abre outro app para o
        # pagamento; nenhum scanner/camera permanece activo nesta versao.
        return True

    def on_resume(self):
        manager = self._screen_manager or self.root
        if manager and manager.current == "mobile_manager":
            manager.get_screen("mobile_manager").refresh_cash_session()

    def on_stop(self):
        closer = getattr(self.db, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass
        super().on_stop()


if __name__ == "__main__":
    MobileManagerApp().run()
