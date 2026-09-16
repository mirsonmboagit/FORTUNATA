from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_desktop_entrypoints_open_the_same_store_app():
    admin_source = (ROOT / "admin_app.py").read_text(encoding="utf-8")
    manager_source = (ROOT / "manager_app.py").read_text(encoding="utf-8")
    legacy_source = (ROOT / "MERCEARIA.py").read_text(encoding="utf-8")

    assert "class StoreApp(BaseApp)" in admin_source
    assert "UnifiedLoginScreen(" in admin_source
    assert "license_client=self.license_client" in admin_source
    assert "from licensing.offline import OfflineLicenseClient" in admin_source
    assert "OfflineLicenseClient.from_runtime()" in admin_source
    assert "from licensing.client import LicenseClient" not in admin_source
    assert "def _validate_active_license" not in admin_source
    assert "'manager': self._build_manager_screen" in admin_source
    assert "from admin_app import StoreApp" in manager_source
    assert "ManagerApp = StoreApp" in manager_source
    assert "MainApp = StoreApp" in legacy_source


def test_unified_login_routes_by_authenticated_role():
    source = (ROOT / "user" / "login.py").read_text(encoding="utf-8")
    unified_source = source.split("class UnifiedLoginScreen(LoginScreen):", 1)[1].split(
        "class ManagerLoginScreen(LoginScreen):", 1
    )[0]

    assert "class UnifiedLoginScreen(LoginScreen)" in source
    assert 'kwargs.setdefault("allowed_roles", [])' in unified_source
    assert 'kwargs.setdefault("allow_admin_setup", False)' in unified_source
    assert 'kwargs.setdefault("registration_mode", "disabled")' in unified_source
    assert "def _submit_admin_provisioning" in unified_source
    assert "validate_admin_provisioning_for_license(" in unified_source
    assert '"create_provisioned_admin"' in unified_source
    assert 'self.success_screen = "admin_home" if role == "admin" else "manager"' in unified_source
    assert "def _validate_desktop_license" in unified_source
    assert "def _submit_license_activation" in unified_source
    assert "def _calc_license_dialog_sizes" in unified_source
    assert "max_height=dp(72)" in source
    assert "size_hint=(width_hint, None)" in source
    assert "def _send_license_request_email" in unified_source
    assert "def _retry_license_request_email" in unified_source
    assert 'text="REENVIAR PEDIDO"' in unified_source
    assert '"Pedido pendente"' in unified_source
    assert "send_system_email(" in unified_source
    assert "LICENSE_REQUEST_SUBJECT" in unified_source
    assert "mailto:" in unified_source
    assert 'text="PEDIR RENOVACAO" if is_renewal else "PEDIR LICENCA"' in unified_source
    assert 'text="COPIAR PEDIDO"' in unified_source
    assert "super(UnifiedLoginScreen, self).login()" in unified_source
    assert "_login_with_control_plane" not in unified_source
    assert 'license_import_states = {"activation_required", "expired"}' in unified_source
    assert "UserAuthenticationResult" not in source


def test_license_controls_are_received_automatically_without_admin_buttons():
    source = (ROOT / "user" / "login.py").read_text(encoding="utf-8")
    unified_source = source.split("class UnifiedLoginScreen(LoginScreen):", 1)[1].split(
        "class ManagerLoginScreen(LoginScreen):", 1
    )[0]
    app_source = (ROOT / "admin_app.py").read_text(encoding="utf-8")

    assert 'text="APLICAR CODIGO"' not in unified_source
    assert "def _sync_license_controls" not in unified_source
    assert "poll_control_inbox" in app_source
    assert "Clock.schedule_interval" in app_source
    assert 'manager.current = "login"' in app_source
    assert "_validate_desktop_license(show_activation=True)" in app_source


def test_android_manager_does_not_bypass_the_license_policy():
    source = (ROOT / "manager_mobile_app.py").read_text(encoding="utf-8")

    assert "MobileLicenseRequiredScreen" in source
    assert "if is_mobile_runtime():" in source
