import os
import re
import webbrowser
from threading import Thread
from urllib.parse import quote

from kivy.properties import (
    ObjectProperty,
    StringProperty,
    ListProperty,
    BooleanProperty,
    NumericProperty,
)
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.app import App
from kivy.metrics import dp, sp
from kivy.core.window import Window

from datetime import datetime, timedelta

from kivymd.uix.screen import MDScreen
from kivymd.uix.dialog import MDDialog
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDIcon, MDLabel
from kivymd.uix.textfield import MDTextField
from kivymd.uix.button import MDFlatButton, MDRaisedButton, MDRectangleFlatIconButton
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.menu import MDDropdownMenu

from database.provider import get_db
from licensing.offline import OfflineLicenseClient, LicenseResult, LICENSE_REQUEST_PLANS, parse_license_request
from licensing.account_provisioning import (
    AccountProvisioningError,
    validate_admin_provisioning_for_license,
)
from licensing.account_events import notify_superadmin_account_event
from licensing.offline_email import LICENSE_REQUEST_SUBJECT, license_request_body
from utils.business.email_service import EmailServiceNotConfigured, send_system_email
from utils.core.i18n import language_options, language_short, translate

LOGIN_KV_PATH = os.path.join(os.path.dirname(__file__), 'login_screen.kv')
try:
    Builder.unload_file(LOGIN_KV_PATH)
except Exception:
    pass
Builder.load_file(LOGIN_KV_PATH)


class LoginScreen(MDScreen):
    # Tela base usada pelo login de admin e gerente.
    username = ObjectProperty(None)
    password = ObjectProperty(None)

    username_error = StringProperty("")
    password_error = StringProperty("")
    login_variant = StringProperty("admin")
    profile_name = StringProperty("")
    identity_badge = StringProperty("")
    hero_title = StringProperty("")
    hero_subtitle = StringProperty("")
    feature_one = StringProperty("")
    feature_two = StringProperty("")
    feature_three = StringProperty("")
    login_heading = StringProperty("")
    login_caption = StringProperty("")
    login_button_text = StringProperty("INICIAR SESSAO")
    form_footer_text = StringProperty("")
    back_button_text = StringProperty("Voltar")
    back_screen = StringProperty("")
    show_back_button = BooleanProperty(False)
    show_theme_toggle = BooleanProperty(False)
    theme_toggle_text = StringProperty("Modo escuro")
    language_button_text = StringProperty("Idioma: PT")
    username_hint = StringProperty("Utilizador")
    password_hint = StringProperty("Palavra-passe")
    forgot_password_text = StringProperty("Esqueci a senha")
    register_text = StringProperty("Criar nova conta")
    context_label = StringProperty("")
    quick_layout_text = StringProperty("Leitura rapida e layout leve")
    allowed_roles = ListProperty([])
    allow_admin_setup = BooleanProperty(True)
    success_screen = StringProperty("")
    registration_mode = StringProperty("disabled")
    registration_password_min_len = NumericProperty(8)
    login_blocked = BooleanProperty(False)
    operation_in_progress = BooleanProperty(False)
    operation_status = StringProperty("")
    license_status = StringProperty("")
    allow_account_self_service = BooleanProperty(True)

    DEFAULT_PASSWORDS = ["123", "123456"]

    def __init__(self, **kwargs):
        db = kwargs.pop("db", None)
        super().__init__(**kwargs)
        self.db = db or get_db()
        self.carousel_event = None
        self._setup_dialog = None
        self._setup_label = None
        self._force_dialog = None
        self._login_blocked = False
        self._pending_login = None
        self._setup_mode = None
        self._setup_original_username = None
        self._setup_email = None
        self._forgot_dialog = None
        self._forgot_user_field = None
        self._forgot_code_field = None
        self._forgot_new_password = None
        self._forgot_confirm_password = None
        self._forgot_feedback = None
        self._forgot_send_button = None
        self._forgot_resend_button = None
        self._forgot_cancel_button = None
        self._forgot_recovery_button = None
        self._recovery_code_dialog = None
        self._forgot_stage = "request"
        self._forgot_content_container = None
        self._register_dialog = None
        self._register_username = None
        self._register_email = None
        self._register_password = None
        self._register_confirm = None
        self._register_feedback = None
        self._register_content_container = None
        self._register_submit_button = None
        self._register_cancel_button = None
        self._register_submit_default_text = "CRIAR CONTA"
        self._verification_dialog = None
        self._verification_username = None
        self._verification_role = None
        self._verification_code = None
        self._verification_feedback = None
        self._verification_confirm_button = None
        self._verification_resend_button = None
        self._verification_close_button = None
        self._operation_token = 0
        self._language_menu = None
        self._language_bound_app = None
        self._apply_variant_defaults()

    def on_kv_post(self, base_widget):
        # Sincroniza textos e layout depois que o KV termina de carregar.
        self._bind_app_language()
        self._apply_variant_defaults()
        self._sync_theme_toggle_text()
        self._sync_language_button_text()
        self._update_responsive_layout()

    def on_size(self, *args):
        Clock.schedule_once(lambda dt: self._update_responsive_layout(), 0)
        Clock.schedule_once(lambda dt: self._update_register_dialog_size(), 0)

    def _update_responsive_layout(self):
        if not hasattr(self, "ids") or "root_layout" not in self.ids:
            return
        compact = self.width < dp(980)
        medium = self.width < dp(1260)
        narrow_form = self.width < dp(760)
        variant = (self.login_variant or "admin").strip().lower()

        root_layout = self.ids.root_layout
        hero_anchor = self.ids.hero_anchor
        hero_column = self.ids.hero_column
        hero_shell = self.ids.hero_shell
        admin_preview_card = self.ids.admin_preview_card
        manager_preview_card = self.ids.manager_preview_card
        admin_slide_one_image = self.ids.get("admin_slide_one_image")
        admin_slide_one_summary = self.ids.get("admin_slide_one_summary")
        admin_slide_two_image = self.ids.get("admin_slide_two_image")
        admin_slide_two_summary = self.ids.get("admin_slide_two_summary")
        manager_preview_image = self.ids.get("manager_preview_image")
        manager_preview_summary = self.ids.get("manager_preview_summary")
        admin_highlights_grid = self.ids.admin_highlights_grid
        divider = self.ids.divider
        form_scroll = self.ids.form_scroll
        form_column = self.ids.form_column
        form_links_row = self.ids.get("form_links_row")
        form_top_actions = self.ids.get("form_top_actions")
        forgot_button = self.ids.get("forgot_button")
        register_button = self.ids.get("register_button")

        root_layout.orientation = "vertical" if compact else "horizontal"
        root_layout.spacing = dp(14) if compact else (dp(18) if medium else dp(20))
        root_layout.padding = (
            [dp(14), dp(14), dp(14), dp(14)]
            if narrow_form else
            [dp(18), dp(16), dp(18), dp(16)]
            if compact else
            [dp(22), dp(18), dp(22), dp(18)]
        )

        show_admin_preview = variant == "admin"
        show_manager_preview = variant == "manager"

        if compact:
            admin_preview_image_h = dp(120)
            admin_preview_summary_h = dp(76)
            manager_preview_image_h = dp(112)
            manager_preview_summary_h = dp(76)
        elif medium:
            admin_preview_image_h = dp(144)
            admin_preview_summary_h = dp(80)
            manager_preview_image_h = dp(132)
            manager_preview_summary_h = dp(80)
        else:
            admin_preview_image_h = dp(160)
            admin_preview_summary_h = dp(82)
            manager_preview_image_h = dp(148)
            manager_preview_summary_h = dp(82)

        for image in (admin_slide_one_image, admin_slide_two_image):
            if image is not None:
                image.height = admin_preview_image_h
        for summary_card in (admin_slide_one_summary, admin_slide_two_summary):
            if summary_card is not None:
                summary_card.height = admin_preview_summary_h
        if manager_preview_image is not None:
            manager_preview_image.height = manager_preview_image_h
        if manager_preview_summary is not None:
            manager_preview_summary.height = manager_preview_summary_h

        if admin_highlights_grid:
            admin_highlights_grid.cols = 1 if compact else 2

        if admin_preview_card:
            admin_preview_card.opacity = 1 if show_admin_preview else 0
            admin_preview_card.disabled = not show_admin_preview
            admin_preview_card.size_hint_y = None
            admin_preview_card.height = (
                admin_preview_image_h + admin_preview_summary_h + dp(44)
            ) if show_admin_preview else 0

        if manager_preview_card:
            manager_preview_card.opacity = 1 if show_manager_preview else 0
            manager_preview_card.disabled = not show_manager_preview
            manager_preview_card.size_hint_y = None
            manager_preview_card.height = (
                manager_preview_image_h + manager_preview_summary_h + dp(44)
            ) if show_manager_preview else 0

        hero_shell.padding = (
            [dp(16), dp(14), dp(16), dp(14)] if compact else [dp(20), dp(18), dp(20), dp(18)] if medium else [dp(22), dp(20), dp(22), dp(20)]
        )
        hero_shell.spacing = dp(10) if compact else dp(12) if medium else dp(14)

        if compact:
            hero_anchor.size_hint_x = 1
            hero_anchor.size_hint_y = None
            hero_anchor.height = hero_column.minimum_height
            hero_column.size_hint_x = 1
            hero_column.size_hint_y = None
            hero_column.height = hero_column.minimum_height

            divider.opacity = 0
            divider.size_hint_x = None
            divider.width = 0

            form_scroll.do_scroll_y = True
            form_scroll.size_hint_x = 1
            form_column.width = min(self.width - dp(28), dp(470))
        else:
            hero_anchor.size_hint_x = 0.55 if variant == "admin" else 0.51
            hero_anchor.size_hint_y = 1
            hero_anchor.height = 0
            hero_column.size_hint_x = 1
            hero_column.size_hint_y = None
            hero_column.height = hero_column.minimum_height

            divider.opacity = 1
            divider.size_hint_x = None
            divider.width = dp(1)

            form_scroll.do_scroll_y = False
            form_scroll.size_hint_x = 0.42 if variant == "admin" else 0.44
            form_column.width = dp(420) if medium else (dp(440) if variant == "admin" else dp(424))

        form_column.padding = (
            [dp(20), dp(18), dp(20), dp(18)] if narrow_form else
            [dp(24), dp(22), dp(24), dp(22)] if compact else
            [dp(26), dp(24), dp(26), dp(24)]
        )
        form_column.spacing = dp(12) if compact else dp(14)

        if form_top_actions is not None:
            form_top_actions.height = dp(34) if narrow_form else dp(38)
            form_top_actions.spacing = dp(8)

        license_actions_installed = bool(
            getattr(self, "_license_actions_installed", False)
        )
        if form_links_row is not None:
            stack_vertical = narrow_form or license_actions_installed
            form_links_row.orientation = "vertical" if stack_vertical else "horizontal"
            form_links_row.spacing = dp(6) if stack_vertical else dp(8)

        # Os links de autoatendimento (esqueci/criar conta) ficam colapsados
        # neste acesso unificado.
        for button in (forgot_button, register_button):
            if button is None:
                continue
            if license_actions_installed:
                button.size_hint_x = 0
                button.size_hint_y = None
                button.width = 0
                button.height = 0
            elif narrow_form:
                button.size_hint_x = 1
                button.size_hint_y = None
                button.width = 0
            else:
                button.size_hint_x = None
                button.size_hint_y = None
                button.width = dp(148)

    def _bind_app_language(self):
        app = App.get_running_app()
        bound_app = getattr(self, "_language_bound_app", None)
        if not app or bound_app is app:
            return
        if bound_app is not None:
            try:
                bound_app.unbind(language=self._on_app_language)
            except Exception:
                pass
        try:
            app.bind(language=self._on_app_language)
            self._language_bound_app = app
        except Exception:
            self._language_bound_app = None

    def _on_app_language(self, *args):
        self._apply_variant_defaults()
        self._sync_theme_toggle_text()
        self._sync_language_button_text()

    def _tr(self, key, **kwargs):
        app = App.get_running_app()
        if app and hasattr(app, "t"):
            return app.t(key, **kwargs)
        return translate(key, **kwargs)

    def _sync_language_button_text(self):
        app = App.get_running_app()
        current = getattr(app, "language", "pt") if app else "pt"
        self.language_button_text = self._tr(
            "login.language_button",
            code=language_short(current),
        )

    def open_language_menu(self, caller=None):
        if getattr(self, "_language_menu", None):
            self._language_menu.dismiss()
            self._language_menu = None
        if caller is None and hasattr(self, "ids"):
            caller = self.ids.get("language_button")
        if caller is None:
            return
        items = []
        for option in language_options():
            code = option["code"]
            items.append(
                {
                    "text": f"{option['native_name']} ({option['short']})",
                    "height": dp(44),
                    "on_release": lambda selected=code: self._select_language(selected),
                }
            )
        self._language_menu = MDDropdownMenu(caller=caller, items=items, width_mult=4)
        self._language_menu.open()

    def _select_language(self, language_code):
        if getattr(self, "_language_menu", None):
            self._language_menu.dismiss()
            self._language_menu = None
        app = App.get_running_app()
        if app and hasattr(app, "set_language"):
            app.set_language(language_code)
        self._on_app_language()

    def _apply_variant_defaults(self):
        variant = (self.login_variant or "admin").strip().lower()
        if variant not in ("admin", "manager"):
            variant = "admin"
        configs = {
            "admin": {
                "profile_name": self._tr("login.admin.profile_name"),
                "identity_badge": self._tr("login.admin.identity_badge"),
                "hero_title": self._tr("login.admin.hero_title"),
                "hero_subtitle": self._tr("login.admin.hero_subtitle"),
                "feature_one": self._tr("login.admin.feature_one"),
                "feature_two": self._tr("login.admin.feature_two"),
                "feature_three": self._tr("login.admin.feature_three"),
                "login_heading": self._tr("login.admin.heading"),
                "login_caption": self._tr("login.admin.caption"),
                "login_button_text": self._tr("login.admin.button"),
                "form_footer_text": self._tr("login.admin.footer"),
            },
            "manager": {
                "profile_name": self._tr("login.manager.profile_name"),
                "identity_badge": self._tr("login.manager.identity_badge"),
                "hero_title": self._tr("login.manager.hero_title"),
                "hero_subtitle": self._tr("login.manager.hero_subtitle"),
                "feature_one": self._tr("login.manager.feature_one"),
                "feature_two": self._tr("login.manager.feature_two"),
                "feature_three": self._tr("login.manager.feature_three"),
                "login_heading": self._tr("login.manager.heading"),
                "login_caption": self._tr("login.manager.caption"),
                "login_button_text": self._tr("login.manager.button"),
                "form_footer_text": self._tr("login.manager.footer"),
            },
        }
        selected = configs.get(variant, configs["admin"])
        for key, value in selected.items():
            setattr(self, key, value)
        self.context_label = self._tr(f"login.context.{variant}")
        self.quick_layout_text = self._tr("login.quick_layout")
        self.back_button_text = self._tr("login.back")
        self.username_hint = self._tr("login.username_hint")
        self.password_hint = self._tr("login.password_hint")
        self.forgot_password_text = self._tr("login.forgot_password")
        self.register_text = self._tr("login.create_account")
        self._sync_language_button_text()
        self.show_back_button = bool(self.back_screen)

    def _sync_theme_toggle_text(self):
        app = App.get_running_app()
        is_dark = bool(app and getattr(app, "theme_style", "Light") == "Dark")
        self.theme_toggle_text = self._tr("login.theme_light") if is_dark else self._tr("login.theme_dark")

    def on_enter(self):
        self._bind_app_language()
        self._apply_variant_defaults()
        self._sync_theme_toggle_text()
        self._sync_language_button_text()
        self.carousel_event = Clock.schedule_interval(self.next_slide, 4)
        Clock.schedule_once(lambda dt: self._ensure_admin_setup(), 0.05)

    def on_leave(self):
        if self.carousel_event:
            self.carousel_event.cancel()
        self._operation_token += 1
        self._set_operation_state(False)

    def next_slide(self, dt):
        carousel = self.ids.get("carousel")
        if carousel and carousel.parent and carousel.parent.height > 0:
            carousel.load_next()

    def go_back(self, *args):
        if not self.manager or not self.back_screen or self.back_screen not in self.manager.screen_names:
            return
        self.reset_fields()
        self.manager.current = self.back_screen

    def toggle_theme(self, *args):
        app = App.get_running_app()
        if not app or not hasattr(app, "apply_theme"):
            return
        current = getattr(app, "theme_style", "Light")
        app.apply_theme("Dark" if current != "Dark" else "Light")
        self._sync_theme_toggle_text()

    def _set_login_enabled(self, enabled):
        self._login_blocked = not enabled
        self.login_blocked = not enabled
        self._refresh_input_state()

    def _refresh_input_state(self):
        enabled = (not self.login_blocked) and (not self.operation_in_progress)
        if self.username:
            self.username.disabled = not enabled
        if self.password:
            self.password.disabled = not enabled

    def _set_operation_state(self, busy, status=""):
        self.operation_in_progress = bool(busy)
        self.operation_status = status if busy else ""
        self._refresh_input_state()
        self._set_register_busy(bool(busy))
        self._set_forgot_busy(bool(busy))

    @staticmethod
    def _is_valid_email(email):
        value = str(email or "").strip()
        return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value))

    def _run_background_task(self, task, callback, busy_text="A processar..."):
        # Executa operacoes de login sem bloquear a interface.
        token = self._operation_token + 1
        self._operation_token = token
        self._set_operation_state(True, busy_text)

        def worker():
            payload = None
            error = None
            try:
                payload = task()
            except Exception as exc:
                error = str(exc)
            if error is None and payload in (None, False):
                error = self._db_last_error() or None
            Clock.schedule_once(
                lambda dt, data=payload, err=error, tok=token: self._finish_background_task(data, err, callback, tok),
                0,
            )

        Thread(target=worker, daemon=True).start()

    def _finish_background_task(self, payload, error, callback, token):
        if token != self._operation_token:
            return
        self._set_operation_state(False)
        callback(payload, error)

    def _log_action_async(self, username, role, action, details):
        def worker():
            try:
                self.db.log_action(username, role, action, details)
            except Exception:
                pass

        Thread(target=worker, daemon=True).start()

    def _audit_event(self, username, role, action, details):
        actor = str(username or "").strip() or "desconhecido"
        actor_role = str(role or "").strip() or "guest"
        self._log_action_async(actor, actor_role, action, details)

    def _find_default_admin(self):
        for username in self.db.get_admin_usernames():
            if self.db.is_admin_default(username, self.DEFAULT_PASSWORDS):
                return username
        return None

    def _ensure_admin_setup(self):
        # Garante que existe um administrador antes de entrar no sistema.
        if not self.allow_admin_setup:
            self._set_login_enabled(True)
            return
        def task():
            has_admin = bool(self.db.has_admin())
            if self._db_last_error():
                return None
            if self._normalized_registration_mode() == 'admin_bootstrap' and not has_admin:
                return {"action": "enable"}
            if not has_admin:
                return {"action": "create"}
            default_admin = self._find_default_admin()
            if default_admin is None and self._db_last_error():
                return None
            if default_admin:
                return {"action": "update_default", "username": default_admin}
            return {"action": "enable"}

        def apply_setup(state, error):
            if error:
                self._set_login_enabled(True)
                return
            action = (state or {}).get("action")
            if action == "create":
                self._set_login_enabled(False)
                self._open_setup_admin_dialog(mode='create')
                return
            if action == "update_default":
                self._set_login_enabled(False)
                self._open_setup_admin_dialog(
                    mode='update_default',
                    original_username=(state or {}).get("username"),
                )
                return
            self._set_login_enabled(True)

        self._run_background_task(
            task,
            apply_setup,
            busy_text="A validar configuração administrativa...",
        )

    def _open_setup_admin_dialog(self, mode='create', original_username=None):
        self._setup_mode = mode
        self._setup_original_username = original_username

        if self._setup_dialog:
            self._setup_dialog.dismiss()
            self._setup_dialog = None

        title = 'Criar Administrador' if mode == 'create' else 'Atualizar Administrador Padrão'
        label_text = 'Configure o administrador inicial' if mode == 'create' else 'Atualize o administrador padrão'
        button_text = 'CRIAR' if mode == 'create' else 'ATUALIZAR'

        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(12),
            padding=dp(20),
            adaptive_height=True,
        )
        self._setup_label = MDLabel(
            text=label_text,
            theme_text_color='Secondary',
            size_hint_y=None,
            height=dp(24),
        )
        content.add_widget(self._setup_label)

        self._setup_username = MDTextField(
            hint_text='Nome de utilizador',
            mode='rectangle',
            size_hint_y=None,
            height=dp(56),
        )
        if original_username:
            self._setup_username.text = original_username
        content.add_widget(self._setup_username)

        self._setup_email = None
        if mode == 'create':
            self._setup_email = MDTextField(
                hint_text='E-mail',
                helper_text='Usado para confirmar a conta e recuperar a senha',
                helper_text_mode='on_focus',
                mode='rectangle',
                size_hint_y=None,
                height=dp(56),
            )
            content.add_widget(self._setup_email)

        self._setup_password = MDTextField(
            hint_text='Senha',
            password=True,
            mode='rectangle',
            size_hint_y=None,
            height=dp(56),
        )
        content.add_widget(self._setup_password)

        self._setup_confirm = MDTextField(
            hint_text='Confirmar senha',
            password=True,
            mode='rectangle',
            size_hint_y=None,
            height=dp(56),
        )
        content.add_widget(self._setup_confirm)

        self._setup_dialog = MDDialog(
            title=title,
            type='custom',
            content_cls=content,
            auto_dismiss=False,
            buttons=[
                MDFlatButton(text=button_text, on_release=self._create_admin_from_dialog),
            ],
        )
        self._setup_dialog.open()

    def _create_admin_from_dialog(self, *args):
        username = self._setup_username.text.strip()
        email = self._setup_email.text.strip() if self._setup_email is not None else ''
        password = self._setup_password.text.strip()
        confirm = self._setup_confirm.text.strip()

        if not username or not password or not confirm or (self._setup_mode == 'create' and not email):
            self._show_message('Erro', 'Todos os campos são obrigatórios')
            return
        if self._setup_mode == 'create' and not self._is_valid_email(email):
            self._show_message('Erro', 'Informe um e-mail válido')
            return
        if len(password) < 8:
            self._show_message('Erro', 'A senha deve ter no mínimo 8 caracteres')
            return
        if password != confirm:
            self._show_message('Erro', 'As senhas não coincidem')
            return

        def task():
            if self._setup_mode == 'update_default':
                original = self._setup_original_username or username
                user_exists = self.db.user_exists(username, exclude_username=original)
                if self._db_last_error():
                    return None
                if user_exists:
                    return {"status": "user_exists"}
                updated = self.db.update_admin_credentials(original, username, password)
                if not updated and self._db_last_error():
                    return None
                if not updated:
                    return {"status": "update_failed"}
                try:
                    self.db.log_action(username, 'admin', 'UPDATE_ADMIN', f"Administrador alterado: {original} -> {username}")
                except Exception:
                    pass
            else:
                user_exists = self.db.user_exists(username)
                if self._db_last_error():
                    return None
                if user_exists:
                    return {"status": "user_exists"}
                created = self.db.create_admin(username, password, email=email)
                if not created and self._db_last_error():
                    return None
                if not created:
                    return {"status": "create_failed"}
            force_password = bool(self.db.is_user_password_default(username, self.DEFAULT_PASSWORDS))
            if self._db_last_error():
                return None
            return {"status": "ok", "username": username, "force_password": force_password}

        def handle_result(result, error):
            if error:
                self._show_operation_error('Não foi possível concluir a configuração do admin')
                return
            status = (result or {}).get("status")
            if status == "user_exists":
                self._show_message('Erro', 'Nome de utilizador já existe')
                return
            if status == "update_failed":
                self._show_message('Erro', 'Não foi possível atualizar o admin')
                return
            if status == "create_failed":
                self._show_message('Erro', 'Não foi possível criar o admin')
                return

            self._close_setup_dialog()
            self._set_login_enabled(True)

            if (result or {}).get("force_password"):
                self._open_force_password_dialog((result or {}).get("username"), 'admin')
                return

            self._complete_login((result or {}).get("username"), 'admin')

        self._run_background_task(
            task,
            handle_result,
            busy_text="A guardar configuração do admin...",
        )

    def _close_setup_dialog(self):
        if self._setup_dialog:
            self._setup_dialog.dismiss()
            self._setup_dialog = None
        self._setup_email = None

    def _open_force_password_dialog(self, username, role):
        self._pending_login = (username, role)
        if self._force_dialog:
            self._force_dialog.open()
            return

        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(12),
            padding=dp(20),
            adaptive_height=True,
        )
        content.add_widget(MDLabel(
            text='Defina uma nova senha para continuar',
            theme_text_color='Secondary',
            size_hint_y=None,
            height=dp(24),
        ))

        self._force_password = MDTextField(
            hint_text='Nova senha',
            password=True,
            mode='rectangle',
            size_hint_y=None,
            height=dp(56),
        )
        content.add_widget(self._force_password)

        self._force_confirm = MDTextField(
            hint_text='Confirmar nova senha',
            password=True,
            mode='rectangle',
            size_hint_y=None,
            height=dp(56),
        )
        content.add_widget(self._force_confirm)

        self._force_dialog = MDDialog(
            title='Alteração obrigatória',
            type='custom',
            content_cls=content,
            auto_dismiss=False,
            buttons=[
                MDFlatButton(text='SALVAR', on_release=self._save_forced_password),
            ],
        )
        self._force_dialog.open()

    def _save_forced_password(self, *args):
        password = self._force_password.text.strip()
        confirm = self._force_confirm.text.strip()

        if not password or not confirm:
            self._show_message('Erro', 'Todos os campos são obrigatórios')
            return
        if len(password) < 6:
            self._show_message('Erro', 'A senha deve ter no mínimo 6 caracteres')
            return
        if password != confirm:
            self._show_message('Erro', 'As senhas não coincidem')
            return

        username, role = self._pending_login or (None, None)
        if not username:
            self._show_message('Erro', 'Utilizador inválido')
            return

        def task():
            updated = self.db.update_user_password(username, password, role=role)
            if not updated and self._db_last_error():
                return None
            if not updated:
                return {"status": "update_failed"}
            try:
                self.db.log_action(
                    username,
                    role or 'admin',
                    'UPDATE_ADMIN' if role == 'admin' else 'UPDATE_PASSWORD',
                    'Palavra-passe alterada por troca obrigatória',
                )
            except Exception:
                pass
            return {"status": "ok"}

        def handle_result(updated, error):
            if error:
                self._show_operation_error('Não foi possível atualizar a senha')
                return
            if (updated or {}).get("status") != "ok":
                self._show_message('Erro', 'Não foi possível atualizar a senha')
                return

            if self._force_dialog:
                self._force_dialog.dismiss()
                self._force_dialog = None

            self._complete_login(username, role or 'admin')

        self._run_background_task(
            task,
            handle_result,
            busy_text="A atualizar senha...",
        )

    def login(self):
        # Valida credenciais e encaminha o utilizador para a tela certa.
        if self.login_blocked or self.operation_in_progress:
            return

        user = self.username.text
        pwd = self.password.text

        self.username_error = ""
        self.password_error = ""

        if not user or not pwd:
            if not user:
                self.username_error = "Utilizador é obrigatório!"
            if not pwd:
                self.password_error = "Senha é obrigatória!"
            return

        def task():
            role = self.db.validate_user(user, pwd)
            if role is None and self._db_last_error():
                return None
            is_default = False
            must_change_password = False
            if role == 'admin':
                is_default = bool(self.db.is_user_password_default(user, self.DEFAULT_PASSWORDS))
                if self._db_last_error():
                    return None
            if role in ('admin', 'manager'):
                requires_change = getattr(self.db, 'is_password_change_required', None)
                if callable(requires_change):
                    must_change_password = bool(requires_change(user))
                    if self._db_last_error():
                        return None
            return {
                "role": role,
                "is_default": is_default,
                "must_change_password": must_change_password,
            }

        def handle_login(result, error):
            if error:
                self._show_operation_error('Não foi possível validar o login no momento')
                return

            role = (result or {}).get("role")
            if role in ("admin", "manager"):
                if self.allowed_roles and role not in self.allowed_roles:
                    self._audit_event(
                        user,
                        role,
                        "ACCESS_DENIED",
                        f"Tentativa de acesso a painel nao autorizado | permitido: {','.join(self.allowed_roles)}",
                    )
                    self.username_error = "Acesso nao autorizado!"
                    self.password_error = "Acesso nao autorizado!"
                    return
                if (result or {}).get("is_default") or (result or {}).get("must_change_password"):
                    self._open_force_password_dialog(user, role)
                    return
                self._complete_login(user, role)
                return

            self._audit_event(
                user,
                "guest",
                "ACCESS_ATTEMPT",
                "Tentativa de login com credenciais invalidas",
            )
            self.username_error = "Credenciais invalidas!"
            self.password_error = "Credenciais invalidas!"

        self._run_background_task(
            task,
            handle_login,
            busy_text="A validar credenciais...",
        )

    def _complete_login(self, user, role):
        self._set_current_user(user, role)
        self.reset_fields()
        target = self.success_screen or role
        if not self.manager:
            return
        app = App.get_running_app()
        ensure_screen = getattr(app, "ensure_screen", None) if app else None
        if target not in self.manager.screen_names and callable(ensure_screen):
            ensure_screen(target)
        if target in self.manager.screen_names:
            self.manager.current = target

    def reset_fields(self):
        self.username.text = ""
        self.password.text = ""
        self.username_error = ""
        self.password_error = ""

    def _set_current_user(self, username, role):
        setter = getattr(self.db, "set_active_user", None)
        if callable(setter):
            try:
                setter(username, role)
            except Exception:
                pass
        app = App.get_running_app()
        if app:
            app.current_user = username
            app.current_role = role
            app._ai_notifications_seen_key = None
            app._ai_banners_shown = False
            app._ai_banners_last_key = None

    def forgot_password(self):
        # O e-mail vem sempre do cadastro; nunca e pedido durante a recuperacao.
        if self._forgot_dialog:
            if self.username and self.username.text.strip() and self._forgot_user_field:
                self._forgot_user_field.text = self.username.text.strip()
            self._update_forgot_dialog_size()
            self._forgot_dialog.open()
            return

        content_box = MDBoxLayout(
            orientation='vertical',
            spacing=dp(10),
            padding=dp(16),
            adaptive_height=True,
            size_hint_x=1,
        )
        content_box.bind(minimum_height=content_box.setter('height'))
        content_box.add_widget(MDLabel(
            text='Informe o utilizador para receber um código no e-mail cadastrado.',
            theme_text_color='Secondary',
            size_hint_y=None,
            height=dp(42),
        ))

        self._forgot_user_field = MDTextField(
            hint_text='Nome de utilizador',
            helper_text='Confirme este nome antes de continuar.',
            helper_text_mode='persistent',
            mode='rectangle',
            size_hint_y=None,
            height=dp(56),
        )
        if self.username and self.username.text.strip():
            self._forgot_user_field.text = self.username.text.strip()
        content_box.add_widget(self._forgot_user_field)

        self._forgot_code_field = MDTextField(
            hint_text='Código de 6 dígitos',
            helper_text='O código expira em 10 minutos',
            helper_text_mode='on_focus',
            input_filter='int',
            max_text_length=6,
            mode='rectangle',
            size_hint_y=None,
            height=dp(56),
        )
        content_box.add_widget(self._forgot_code_field)

        self._forgot_new_password = MDTextField(
            hint_text='Nova senha (mínimo 8 caracteres)',
            password=True,
            mode='rectangle',
            size_hint_y=None,
            height=dp(56),
        )
        content_box.add_widget(self._forgot_new_password)

        self._forgot_confirm_password = MDTextField(
            hint_text='Confirmar nova senha',
            password=True,
            mode='rectangle',
            size_hint_y=None,
            height=dp(56),
        )
        content_box.add_widget(self._forgot_confirm_password)

        self._forgot_feedback = MDLabel(
            text='',
            theme_text_color='Secondary',
            size_hint_y=None,
            height=0,
            opacity=0,
        )
        self._forgot_feedback.bind(
            width=lambda inst, width: setattr(inst, 'text_size', (width, None)),
            texture_size=lambda inst, size: setattr(inst, 'height', max(dp(24), size[1]) if inst.text else 0),
        )
        content_box.add_widget(self._forgot_feedback)

        scroll = MDScrollView(do_scroll_x=False, size_hint=(1, 1))
        scroll.add_widget(content_box)
        dialog_height, content_height = self._calc_forgot_sizes()
        self._forgot_content_container = MDBoxLayout(
            orientation='vertical',
            size_hint=(1, None),
            height=content_height,
        )
        self._forgot_content_container.add_widget(scroll)

        self._forgot_cancel_button = MDFlatButton(
            text='CANCELAR',
            on_release=self._dismiss_forgot_dialog,
        )
        self._forgot_recovery_button = MDFlatButton(
            text='USAR CÓDIGO DE EMERGÊNCIA',
            on_release=self._open_recovery_code_dialog,
        )
        self._forgot_resend_button = MDFlatButton(
            text='REENVIAR',
            on_release=self._resend_password_reset,
        )
        self._forgot_send_button = MDFlatButton(
            text='ENVIAR CÓDIGO',
            on_release=self._submit_forgot,
        )

        self._forgot_dialog = MDDialog(
            title='Recuperação de senha',
            type='custom',
            content_cls=self._forgot_content_container,
            size_hint=(0.7, None),
            height=dialog_height,
            auto_dismiss=False,
            buttons=[
                self._forgot_cancel_button,
                self._forgot_recovery_button,
                self._forgot_resend_button,
                self._forgot_send_button,
            ],
        )
        self._forgot_user_field.bind(on_text_validate=self._submit_forgot)
        self._forgot_code_field.bind(
            on_text_validate=lambda *args: self._focus_register_field(self._forgot_new_password)
        )
        self._forgot_new_password.bind(
            on_text_validate=lambda *args: self._focus_register_field(self._forgot_confirm_password)
        )
        self._forgot_confirm_password.bind(on_text_validate=self._submit_forgot)
        self._forgot_stage = 'request'
        self._set_forgot_stage('request')
        self._forgot_dialog.open()

    def _calc_forgot_sizes(self):
        dialog_height = min(Window.height * 0.8, dp(520))
        content_height = max(dp(220), dialog_height - dp(140))
        return dialog_height, content_height

    def _update_forgot_dialog_size(self):
        dialog_height, content_height = self._calc_forgot_sizes()
        if self._forgot_dialog:
            width = Window.width or dp(900)
            self._forgot_dialog.size_hint = (0.92 if width < dp(620) else 0.7, None)
            self._forgot_dialog.height = dialog_height
        if self._forgot_content_container:
            self._forgot_content_container.height = content_height

    def _dismiss_forgot_dialog(self, *args):
        if self._forgot_dialog:
            self._forgot_dialog.dismiss()
        self._clear_forgot_fields()
        self._forgot_dialog = None
        self._forgot_user_field = None
        self._forgot_code_field = None
        self._forgot_new_password = None
        self._forgot_confirm_password = None
        self._forgot_feedback = None
        self._forgot_send_button = None
        self._forgot_resend_button = None
        self._forgot_cancel_button = None
        self._forgot_recovery_button = None
        self._forgot_content_container = None
        self._forgot_stage = 'request'

    def _clear_forgot_fields(self):
        if self._forgot_user_field:
            self._forgot_user_field.text = ''
        if self._forgot_code_field:
            self._forgot_code_field.text = ''
        if self._forgot_new_password:
            self._forgot_new_password.text = ''
        if self._forgot_confirm_password:
            self._forgot_confirm_password.text = ''

    def _set_forgot_feedback(self, message='', error=False):
        if self._forgot_feedback is None:
            return
        self._forgot_feedback.text = message
        self._forgot_feedback.opacity = 1 if message else 0
        self._forgot_feedback.theme_text_color = 'Error' if error else 'Secondary'

    def _set_forgot_stage(self, stage):
        self._forgot_stage = stage
        show_reset = stage == 'confirm'
        for field in (
            self._forgot_code_field,
            self._forgot_new_password,
            self._forgot_confirm_password,
        ):
            if field is not None:
                field.height = dp(56) if show_reset else 0
                field.opacity = 1 if show_reset else 0
                field.disabled = (not show_reset) or self.operation_in_progress
        if self._forgot_user_field is not None:
            # O utilizador identifica a recuperacao. Na confirmacao fica so de
            # leitura (em vez de desativado), para continuar legivel em todas as etapas.
            self._forgot_user_field.readonly = show_reset
            self._forgot_user_field.disabled = self.operation_in_progress
        if self._forgot_send_button is not None:
            self._forgot_send_button.text = 'REDEFINIR' if show_reset else 'ENVIAR CÓDIGO'
        if self._forgot_resend_button is not None:
            self._forgot_resend_button.opacity = 1 if show_reset else 0
            self._forgot_resend_button.disabled = (not show_reset) or self.operation_in_progress

    def _set_forgot_busy(self, busy):
        if self._forgot_dialog is None:
            return
        self._set_forgot_stage(self._forgot_stage)
        if self._forgot_user_field is not None:
            self._forgot_user_field.readonly = self._forgot_stage == 'confirm'
            self._forgot_user_field.disabled = bool(busy)
        for field in (
            self._forgot_code_field,
            self._forgot_new_password,
            self._forgot_confirm_password,
        ):
            if field is not None:
                field.disabled = bool(busy) or self._forgot_stage != 'confirm'
        if self._forgot_send_button is not None:
            self._forgot_send_button.disabled = bool(busy)
            if busy:
                self._forgot_send_button.text = 'A PROCESSAR...'
            else:
                self._forgot_send_button.text = (
                    'REDEFINIR' if self._forgot_stage == 'confirm' else 'ENVIAR CÓDIGO'
                )
        if self._forgot_resend_button is not None:
            self._forgot_resend_button.disabled = bool(busy) or self._forgot_stage != 'confirm'
        if self._forgot_cancel_button is not None:
            self._forgot_cancel_button.disabled = bool(busy)
        if self._forgot_recovery_button is not None:
            self._forgot_recovery_button.disabled = bool(busy)

    def _submit_forgot(self, *args):
        if self._forgot_stage == 'confirm':
            self._confirm_password_reset()
        else:
            self._request_password_reset()

    def _request_password_reset(self, resend=False):
        username = self._forgot_user_field.text.strip() if self._forgot_user_field else ''
        if not username:
            self._set_forgot_feedback('Informe o nome de utilizador.', True)
            return

        def task():
            return self.db.request_password_reset(username)

        def handle_result(result, error):
            if error:
                self._set_forgot_feedback(
                    'Não foi possível contactar o serviço de recuperação. Tente novamente.',
                    True,
                )
                return
            payload = result or {}
            if not payload.get('ok'):
                reason = payload.get('reason')
                if reason == 'email_unavailable':
                    self._set_forgot_feedback(
                        'Configure SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD e SMTP_FROM_EMAIL em config/.env.',
                        True,
                    )
                elif reason == 'rate_limited':
                    wait = payload.get('retry_after') or 60
                    self._set_forgot_feedback(f'Aguarde {wait} segundos antes de reenviar.', True)
                else:
                    self._set_forgot_feedback('Não foi possível enviar o código. Tente novamente.', True)
                return

            self._set_forgot_stage('confirm')
            wait = payload.get('retry_after')
            suffix = f' Poderá reenviar após {wait} segundos.' if wait else ''
            self._set_forgot_feedback(
                'Se existir uma conta com esse utilizador, enviámos um código ao e-mail cadastrado.' + suffix
            )
            if not resend:
                self._focus_register_field(self._forgot_code_field)

        self._run_background_task(
            task,
            handle_result,
            busy_text="A enviar código...",
        )

    def _resend_password_reset(self, *args):
        self._request_password_reset(resend=True)

    def _open_recovery_code_dialog(self, *args):
        content = MDBoxLayout(orientation='vertical', spacing=dp(10), padding=dp(16), adaptive_height=True)
        active_username = (
            self._forgot_user_field.text.strip()
            if self._forgot_user_field and self._forgot_user_field.text.strip()
            else ''
        )
        content.add_widget(MDLabel(
            text='Recuperacao sem e-mail. Confirme o nome de utilizador e use um codigo guardado.',
            theme_text_color='Secondary', size_hint_y=None, height=dp(42),
        ))
        username = MDTextField(
            hint_text='Nome de utilizador',
            helper_text='Utilizador em recuperacao',
            helper_text_mode='persistent',
            text=active_username,
            readonly=bool(active_username),
            mode='rectangle', size_hint_y=None, height=dp(56),
        )
        code = MDTextField(hint_text='Código de emergência', mode='rectangle', size_hint_y=None, height=dp(56))
        new_password = MDTextField(hint_text='Nova senha (mínimo 8 caracteres)', password=True, mode='rectangle', size_hint_y=None, height=dp(56))
        confirm = MDTextField(hint_text='Confirmar nova senha', password=True, mode='rectangle', size_hint_y=None, height=dp(56))
        feedback = MDLabel(text='', theme_text_color='Error', size_hint_y=None, height=dp(30))
        for field in (username, code, new_password, confirm):
            content.add_widget(field)
        content.add_widget(feedback)

        busy = False

        cancel_button = MDFlatButton(text='CANCELAR')
        submit_button = MDRaisedButton(text='REDEFINIR')

        def set_busy(value):
            nonlocal busy
            busy = bool(value)
            for field in (username, code, new_password, confirm):
                field.disabled = busy
            cancel_button.disabled = busy
            submit_button.disabled = busy
            submit_button.text = 'A REDEFINIR...' if busy else 'REDEFINIR'

        def submit(*_args):
            if busy or self.operation_in_progress:
                return
            user, raw_code = username.text.strip(), code.text.strip()
            password, repeated = new_password.text, confirm.text
            if not user or not raw_code:
                feedback.text = 'Informe o utilizador e o código.'; return
            if len(password) < 8:
                feedback.text = 'A nova senha deve ter no mínimo 8 caracteres.'; return
            if password != repeated:
                feedback.text = 'As senhas não coincidem.'; return

            set_busy(True)

            def task():
                return self.db.confirm_recovery_code(user, raw_code, password)

            def handle_result(result, error):
                set_busy(False)
                if error:
                    feedback.text = 'Não foi possível validar o código. Verifique a ligação e tente novamente.'
                    return
                if isinstance(result, dict) and result.get('ok'):
                    dialog.dismiss()
                    self._recovery_code_dialog = None
                    self._show_message('Sucesso', 'Senha atualizada. Já pode iniciar sessão.')
                    return
                reason = result.get('reason') if isinstance(result, dict) else ''
                if reason == 'weak_password':
                    feedback.text = 'A nova senha deve ter no mínimo 8 caracteres.'
                else:
                    feedback.text = 'Código inválido ou já utilizado.'

            self._run_background_task(
                task,
                handle_result,
                busy_text='A validar código de emergência...',
            )

        dialog = MDDialog(
            title='Recuperação offline', type='custom', content_cls=content, auto_dismiss=False,
            buttons=[cancel_button, submit_button],
        )
        cancel_button.bind(on_release=lambda *_: dialog.dismiss())
        submit_button.bind(on_release=submit)
        self._recovery_code_dialog = dialog
        dialog.open()

    def _confirm_password_reset(self):
        username = self._forgot_user_field.text.strip() if self._forgot_user_field else ''
        code = self._forgot_code_field.text.strip() if self._forgot_code_field else ''
        new_password = self._forgot_new_password.text.strip() if self._forgot_new_password else ''
        confirm = self._forgot_confirm_password.text.strip() if self._forgot_confirm_password else ''

        if len(code) != 6 or not code.isdigit():
            self._set_forgot_feedback('Informe o código de 6 dígitos enviado por e-mail.', True)
            self._focus_register_field(self._forgot_code_field)
            return
        if len(new_password) < 8:
            self._set_forgot_feedback('A nova senha deve ter no mínimo 8 caracteres.', True)
            self._focus_register_field(self._forgot_new_password)
            return
        if new_password != confirm:
            self._set_forgot_feedback('As senhas não coincidem.', True)
            self._focus_register_field(self._forgot_confirm_password)
            return

        def task():
            return self.db.confirm_password_reset(username, code, new_password)

        def handle_result(result, error):
            if error:
                self._set_forgot_feedback('Não foi possível redefinir a senha. Tente novamente.', True)
                return
            payload = result or {}
            if payload.get('ok'):
                self._dismiss_forgot_dialog()
                self._show_message('Sucesso', 'Senha atualizada com sucesso! Já pode iniciar sessão.')
                return

            reason = payload.get('reason')
            if reason == 'weak_password':
                message = 'A nova senha deve ter no mínimo 8 caracteres.'
            elif reason == 'expired':
                message = 'O código expirou. Clique em REENVIAR para receber outro.'
            elif reason == 'too_many_attempts':
                message = 'Código bloqueado após muitas tentativas. Solicite um novo código.'
            elif reason in ('invalid', 'not_found'):
                remaining = payload.get('remaining')
                message = 'Código inválido.'
                if remaining is not None:
                    message += f' Tentativas restantes: {remaining}.'
            else:
                message = 'Não foi possível validar o código. Tente novamente.'
            self._set_forgot_feedback(message, True)

        self._run_background_task(
            task,
            handle_result,
            busy_text='A redefinir senha...',
        )

    def register(self):
        mode = self._normalized_registration_mode()
        if mode == 'disabled':
            self._show_message('Info', 'Registo indisponível neste app')
            return

        self._open_register_dialog()

    def _normalized_registration_mode(self):
        return (self.registration_mode or 'disabled').strip().lower()

    def _db_last_error(self):
        # Recupera o ultimo erro da base, quando o backend fornece esse detalhe.
        getter = getattr(self.db, 'last_error', None)
        if not callable(getter):
            return ''
        try:
            return getter() or ''
        except Exception:
            return ''

    def _show_operation_error(self, fallback_message):
        detail = self._db_last_error()
        if detail:
            self._show_message('Erro', f'{fallback_message}\nDetalhe: {detail}')
            return
        self._show_message('Erro', fallback_message)

    def _theme_tokens(self):
        app = App.get_running_app()
        return getattr(app, "theme_tokens", {}) if app else {}

    def _theme_color(self, key, fallback):
        return self._theme_tokens().get(key, fallback)

    def _color_with_alpha(self, color, alpha):
        base = list(color or [0, 0, 0, 1])
        while len(base) < 3:
            base.append(0)
        return [base[0], base[1], base[2], alpha]

    def _register_accent_color(self, mode=None):
        mode = mode or self._normalized_registration_mode()
        tone = "primary" if mode == "admin_bootstrap" else "success"
        fallback = [0.12, 0.36, 0.65, 1] if tone == "primary" else [0.16, 0.62, 0.38, 1]
        return self._theme_color(tone, fallback)

    def _register_text_label(self, text, color_key="text_secondary", font_style="Caption", bold=False):
        fallback = {
            "text_primary": [0.13, 0.16, 0.22, 1],
            "text_secondary": [0.35, 0.38, 0.45, 1],
        }.get(color_key, [0.35, 0.38, 0.45, 1])
        label = MDLabel(
            text=text,
            font_style=font_style,
            bold=bold,
            theme_text_color="Custom",
            text_color=self._theme_color(color_key, fallback),
            size_hint_y=None,
            height=dp(18),
        )
        label.bind(width=lambda inst, width: setattr(inst, "text_size", (width, None)))
        label.bind(texture_size=lambda inst, size: setattr(inst, "height", max(dp(18), size[1])))
        return label

    def _calc_register_sizes(self):
        width = Window.width or dp(900)
        if width < dp(620):
            width_hint = 0.92
        elif width < dp(980):
            width_hint = 0.72
        else:
            width_hint = 0.48
        dialog_height = min(Window.height * 0.86, dp(600))
        content_height = max(dp(260), dialog_height - dp(142))
        return width_hint, dialog_height, content_height

    def _update_register_dialog_size(self):
        if not self._register_dialog:
            return
        width_hint, dialog_height, content_height = self._calc_register_sizes()
        self._register_dialog.size_hint = (width_hint, None)
        self._register_dialog.height = dialog_height
        if self._register_content_container is not None:
            self._register_content_container.height = content_height

    def _set_register_busy(self, busy):
        if not any((self._register_username, self._register_email, self._register_password, self._register_confirm)):
            return
        fields = [self._register_username, self._register_email, self._register_password, self._register_confirm]
        for field in fields:
            if field is not None:
                field.disabled = bool(busy)
        if self._register_submit_button is not None:
            self._register_submit_button.disabled = bool(busy)
            self._register_submit_button.text = "A CRIAR..." if busy else self._register_submit_default_text
        if self._register_cancel_button is not None:
            self._register_cancel_button.disabled = bool(busy)

    def _set_register_feedback(self, message="", tone="danger"):
        if self._register_feedback is None:
            return
        self._register_feedback.text = message
        self._register_feedback.opacity = 1 if message else 0
        self._register_feedback.height = dp(34) if message else 0
        fallback = [0.78, 0.22, 0.24, 1] if tone == "danger" else [0.12, 0.36, 0.65, 1]
        self._register_feedback.text_color = self._theme_color(tone, fallback)

    def _clear_register_feedback(self, *args):
        self._set_register_feedback("")

    def _focus_register_field(self, field):
        if field is None:
            return
        Clock.schedule_once(lambda dt: setattr(field, "focus", True), 0)

    def _open_register_dialog(self):
        # Abre o registo de novo utilizador conforme o modo permitido.
        if self._register_dialog:
            self._register_dialog.dismiss()
            self._register_dialog = None

        mode = self._normalized_registration_mode()
        is_admin_setup = mode == 'admin_bootstrap'
        title = 'Criar administrador inicial' if is_admin_setup else 'Criar conta de gerente'
        role_text = 'Administrador' if is_admin_setup else 'Gerente'
        subtitle = (
            'Primeiro acesso para configuração e gestão do sistema.'
            if is_admin_setup else
            'Acesso para vendas, consulta rápida e operação diária.'
        )
        accent = self._register_accent_color(mode)
        text_secondary = self._theme_color("text_secondary", [0.36, 0.40, 0.48, 1])
        card_alt = self._theme_color("card_alt", [0.94, 0.95, 0.97, 1])
        on_primary = self._theme_color("on_primary", [1, 1, 1, 1])
        min_len = max(8, int(self.registration_password_min_len or 8))

        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(12),
            padding=[dp(18), dp(14), dp(18), dp(10)],
            adaptive_height=True,
            size_hint_x=1,
        )
        content.bind(minimum_height=content.setter('height'))

        header = MDCard(
            orientation='horizontal',
            spacing=dp(12),
            padding=[dp(14), dp(12), dp(14), dp(12)],
            size_hint_y=None,
            height=dp(94),
            radius=[dp(18)],
            elevation=0,
            md_bg_color=self._color_with_alpha(accent, 0.12),
        )
        icon_slot = MDCard(
            size_hint=(None, None),
            size=(dp(46), dp(46)),
            radius=[dp(15)],
            elevation=0,
            md_bg_color=self._color_with_alpha(accent, 0.18),
        )
        icon = MDIcon(
            icon='account-key-outline' if is_admin_setup else 'account-plus',
            halign='center',
            valign='middle',
            theme_text_color='Custom',
            text_color=accent,
        )
        icon.bind(size=lambda inst, value: setattr(inst, "text_size", value))
        icon_slot.add_widget(icon)

        header_text = MDBoxLayout(
            orientation='vertical',
            spacing=dp(3),
            size_hint_x=1,
        )
        header_text.add_widget(self._register_text_label(role_text, "text_primary", "Subtitle1", True))
        header_text.add_widget(self._register_text_label(subtitle, "text_secondary", "Caption"))
        header.add_widget(icon_slot)
        header.add_widget(header_text)
        content.add_widget(header)

        tip_row = MDBoxLayout(
            orientation='horizontal',
            spacing=dp(8),
            size_hint_y=None,
            height=dp(42),
        )
        tip_icon = MDIcon(
            icon='information-outline',
            halign='center',
            valign='middle',
            theme_text_color='Custom',
            text_color=accent,
            size_hint_x=None,
            width=dp(22),
        )
        tip_icon.bind(size=lambda inst, value: setattr(inst, "text_size", value))
        tip_row.add_widget(tip_icon)
        tip_row.add_widget(self._register_text_label(
            f'A senha precisa ter no mínimo {min_len} caracteres.',
            "text_secondary",
            "Caption",
        ))
        content.add_widget(tip_row)

        self._register_username = MDTextField(
            hint_text='Nome de utilizador',
            icon_right='account-outline',
            mode='rectangle',
            size_hint_y=None,
            height=dp(64),
        )
        self._register_username.line_color_focus = accent
        if self.username and self.username.text:
            self._register_username.text = self.username.text.strip()
        content.add_widget(self._register_username)

        self._register_email = MDTextField(
            hint_text='E-mail',
            helper_text='Receberá aqui os códigos de confirmação e recuperação',
            helper_text_mode='on_focus',
            icon_right='email-outline',
            mode='rectangle',
            size_hint_y=None,
            height=dp(64),
        )
        self._register_email.line_color_focus = accent
        content.add_widget(self._register_email)

        self._register_password = MDTextField(
            hint_text='Senha',
            helper_text=f'Mínimo {min_len} caracteres',
            helper_text_mode='on_focus',
            icon_right='lock-outline',
            password=True,
            mode='rectangle',
            size_hint_y=None,
            height=dp(64),
        )
        self._register_password.line_color_focus = accent
        content.add_widget(self._register_password)

        self._register_confirm = MDTextField(
            hint_text='Confirmar senha',
            helper_text='Repita a senha para evitar erro de digitação',
            helper_text_mode='on_focus',
            icon_right='lock-check-outline',
            password=True,
            mode='rectangle',
            size_hint_y=None,
            height=dp(64),
        )
        self._register_confirm.line_color_focus = accent
        content.add_widget(self._register_confirm)

        register_fields = [
            self._register_username,
            self._register_email,
            self._register_password,
            self._register_confirm,
        ]
        self._register_confirm.bind(on_text_validate=self._submit_register)
        for field in register_fields:
            field.bind(text=self._clear_register_feedback)

        self._register_feedback = MDLabel(
            text='',
            opacity=0,
            font_style='Caption',
            theme_text_color='Custom',
            text_color=self._theme_color("danger", [0.78, 0.22, 0.24, 1]),
            size_hint_y=None,
            height=0,
            halign='left',
        )
        self._register_feedback.bind(width=lambda inst, width: setattr(inst, "text_size", (width, None)))
        content.add_widget(self._register_feedback)

        security_note = MDCard(
            orientation='horizontal',
            spacing=dp(8),
            padding=[dp(12), dp(9), dp(12), dp(9)],
            size_hint_y=None,
            height=dp(62),
            radius=[dp(14)],
            elevation=0,
            md_bg_color=card_alt,
        )
        shield_icon = MDIcon(
            icon='email-check-outline',
            halign='center',
            valign='middle',
            theme_text_color='Custom',
            text_color=accent,
            size_hint_x=None,
            width=dp(22),
        )
        shield_icon.bind(size=lambda inst, value: setattr(inst, "text_size", value))
        security_note.add_widget(shield_icon)
        security_note.add_widget(self._register_text_label(
            'O codigo de recuperacao sera enviado apenas para este e-mail cadastrado.',
            "text_secondary",
            "Caption",
        ))
        content.add_widget(security_note)

        scroll = MDScrollView(do_scroll_x=False, size_hint=(1, 1))
        scroll.add_widget(content)
        width_hint, dialog_height, content_height = self._calc_register_sizes()
        self._register_content_container = MDBoxLayout(
            orientation='vertical',
            size_hint=(1, None),
            height=content_height,
        )
        self._register_content_container.add_widget(scroll)

        self._register_cancel_button = MDFlatButton(
            text='CANCELAR',
            theme_text_color='Custom',
            text_color=text_secondary,
            on_release=self._close_register_dialog,
        )
        self._register_submit_default_text = 'CRIAR ADMIN' if is_admin_setup else 'CRIAR CONTA'
        self._register_submit_button = MDRaisedButton(
            text=self._register_submit_default_text,
            md_bg_color=accent,
            theme_text_color='Custom',
            text_color=on_primary,
            on_release=self._submit_register,
        )

        self._register_dialog = MDDialog(
            title=title,
            type='custom',
            content_cls=self._register_content_container,
            size_hint=(width_hint, None),
            height=dialog_height,
            auto_dismiss=False,
            buttons=[
                self._register_cancel_button,
                self._register_submit_button,
            ],
        )
        self._register_dialog.open()
        self._focus_register_field(self._register_password if self._register_username.text else self._register_username)

    def _close_register_dialog(self, *args):
        if self._register_dialog:
            self._register_dialog.dismiss()
            self._register_dialog = None
        self._register_username = None
        self._register_email = None
        self._register_password = None
        self._register_confirm = None
        self._register_answer_fields = []
        self._register_feedback = None
        self._register_content_container = None
        self._register_submit_button = None
        self._register_cancel_button = None

    def _submit_register(self, *args):
        # Valida e grava a conta criada no diálogo.
        mode = self._normalized_registration_mode()
        username = self._register_username.text.strip() if self._register_username else ''
        email = self._register_email.text.strip() if self._register_email else ''
        password = self._register_password.text.strip() if self._register_password else ''
        confirm = self._register_confirm.text.strip() if self._register_confirm else ''

        if not username:
            self._set_register_feedback('Informe o nome de utilizador.')
            self._focus_register_field(self._register_username)
            return
        if ' ' in username:
            self._set_register_feedback('O nome de utilizador não deve ter espaços.')
            self._focus_register_field(self._register_username)
            return
        if not email or not self._is_valid_email(email):
            self._set_register_feedback('Informe um e-mail valido para recuperar a conta.')
            self._focus_register_field(self._register_email)
            return
        if not password:
            self._set_register_feedback('Informe a senha da conta.')
            self._focus_register_field(self._register_password)
            return
        if not confirm:
            self._set_register_feedback('Confirme a senha antes de criar a conta.')
            self._focus_register_field(self._register_confirm)
            return

        min_len = max(8, int(self.registration_password_min_len or 8))
        if len(password) < min_len:
            self._set_register_feedback(f'A senha deve ter no mínimo {min_len} caracteres.')
            self._focus_register_field(self._register_password)
            return
        if password != confirm:
            self._set_register_feedback('As senhas não coincidem.')
            self._focus_register_field(self._register_confirm)
            return
        role = ''
        if mode == 'manager_self_service':
            role = 'manager'
        elif mode == 'admin_bootstrap':
            role = 'admin'
        else:
            self._show_message('Info', 'Registo indisponível neste app')
            self._close_register_dialog()
            return

        self._set_register_feedback(
            'A criar admin...' if role == 'admin' else 'A criar conta...',
            'primary' if role == 'admin' else 'success',
        )

        def task():
            user_exists = self.db.user_exists(username)
            if self._db_last_error():
                return None
            if user_exists:
                return {"status": "user_exists"}

            if role == 'admin':
                has_admin = self.db.has_admin()
                if self._db_last_error():
                    return None
                if has_admin:
                    return {"status": "admin_exists"}
                created = self.db.create_admin(username, password, email=email)
                if not created and self._db_last_error():
                    return None
                if not created:
                    has_admin = self.db.has_admin()
                    if self._db_last_error():
                        return None
                    if has_admin:
                        return {"status": "admin_exists"}
                    return {"status": "create_failed"}
            else:
                created = self.db.create_user(username, password, 'manager', email=email)
                if not created and self._db_last_error():
                    return None
                if not created:
                    return {"status": "create_failed"}
                try:
                    self.db.log_action(
                        username,
                        'manager',
                        'CREATE_USER',
                        'Auto-cadastro via login manager',
                    )
                except Exception:
                    pass
            return {"status": "ok"}

        def handle_result(result, error):
            if error:
                if role == 'admin':
                    self._set_register_feedback('Não foi possível criar o administrador.')
                else:
                    self._set_register_feedback('Não foi possível criar a conta.')
                return

            status = (result or {}).get("status")
            if status == "user_exists":
                self._set_register_feedback('Nome de utilizador já existe.')
                self._focus_register_field(self._register_username)
                return
            if status == "admin_exists":
                self._show_message('Info', 'Já existe um administrador. Novos administradores devem ser criados em Configurações.')
                self._close_register_dialog()
                return
            if status == "create_failed":
                if role == 'admin':
                    self._set_register_feedback('Não foi possível criar o admin.')
                else:
                    self._set_register_feedback('Não foi possível criar a conta.')
                return
            self._close_register_dialog()
            if self.username:
                self.username.text = username
            if self.password:
                self.password.text = ''
            self.username_error = ''
            self.password_error = ''
            self._show_message('Sucesso', 'Conta criada com sucesso! Faça login.')

        self._run_background_task(
            task,
            handle_result,
            busy_text="A criar admin..." if role == 'admin' else "A criar conta...",
        )

    def _show_message(self, title, message):
        MDDialog(
            title=title,
            text=message,
            buttons=[
                MDFlatButton(text='OK', on_release=lambda x: x.parent.parent.parent.parent.dismiss())
            ],
        ).open()


class AdminLoginScreen(LoginScreen):
    def __init__(self, **kwargs):
        kwargs.setdefault("login_variant", "admin")
        kwargs.setdefault("allowed_roles", ["admin"])
        kwargs.setdefault("allow_admin_setup", True)
        kwargs.setdefault("registration_mode", "admin_bootstrap")
        kwargs.setdefault("registration_password_min_len", 8)
        kwargs.setdefault("success_screen", "admin_home")
        super().__init__(**kwargs)


class UnifiedLoginScreen(LoginScreen):
    """Login unico que encaminha cada conta para o seu proprio painel."""

    def __init__(self, **kwargs):
        # Mantemos o estilo visual administrativo como base, mas sem restringir
        # o acesso a uma funcao antes de validar as credenciais.
        license_client = kwargs.pop("license_client", None)
        kwargs.setdefault("login_variant", "admin")
        kwargs.setdefault("allowed_roles", [])
        # A primeira conta admin nunca e criada pela propria instalacao. Ela
        # precisa ser provisionada pelo superadmin e importada com um codigo
        # assinado, depois de a licenca local ser confirmada.
        kwargs.setdefault("allow_admin_setup", False)
        kwargs.setdefault("registration_mode", "disabled")
        kwargs.setdefault("registration_password_min_len", 8)
        kwargs.setdefault("allow_account_self_service", False)
        kwargs.setdefault("show_theme_toggle", True)
        self.license_client = license_client
        self._license_access_confirmed = self.license_client is None
        self._license_dialog = None
        self._license_content_container = None
        self._license_code_field = None
        self._license_feedback = None
        self._license_request_code = ""
        self._license_request_recipient = ""
        self._license_request_submitted = False
        self._desktop_license_state = ""
        # Estes atributos permanecem apenas para compatibilidade com sessoes
        # antigas; os controlos de licenca sao recebidos e aplicados pela app.
        self._license_revocation_action = None
        self._license_revocation_dialog = None
        self._license_revocation_code_field = None
        self._license_revocation_feedback = None
        # A suspensao e reversivel; a reativacao so aparece quando o proprio
        # cofre local confirma que SIGE-SUS1 foi importado nesta instalacao.
        self._license_suspension_action = None
        self._license_reactivation_action = None
        self._license_restoration_action = None
        self._license_control_dialog = None
        self._license_control_code_field = None
        self._license_control_feedback = None
        self._license_control_kind = ""
        self._admin_provision_dialog = None
        self._admin_provision_code_field = None
        self._admin_provision_feedback = None
        self._admin_provision_content_container = None
        super().__init__(**kwargs)

    def on_kv_post(self, base_widget):
        super().on_kv_post(base_widget)

    def on_size(self, *args):
        super().on_size(*args)
        Clock.schedule_once(lambda _dt: self._update_license_dialog_size(), 0)
        Clock.schedule_once(lambda _dt: self._update_admin_provision_dialog_size(), 0)

    def on_enter(self):
        super().on_enter()
        if self.license_client is not None:
            self._set_login_enabled(False)
            Clock.schedule_once(lambda _dt: self._validate_desktop_license(), 0.01)

    def _ensure_admin_setup(self):
        # O provisionamento local somente abre depois de este computador ter
        # uma licenca offline valida. Nao ha fallback para criar um admin sem
        # o codigo assinado do superadmin.
        if self.license_client is not None and not self._license_access_confirmed:
            return

        if self.license_client is None:
            self._set_login_enabled(False)
            return

        def task():
            has_admin = bool(self.db.has_admin())
            if self._db_last_error():
                return None
            return {"has_admin": has_admin}

        def apply_setup(state, error):
            # Uma revogacao pode ser importada enquanto esta verificacao da
            # base local ainda esta a decorrer. Nunca deixe esse retorno
            # tardio voltar a libertar o botao de login.
            if self.license_client is not None and not self._license_access_confirmed:
                self._set_login_enabled(False)
                return
            if error:
                self._set_login_enabled(False)
                self._show_message(
                    "Configuração indisponível",
                    "Não foi possível verificar a conta administrativa local.",
                )
                return
            if (state or {}).get("has_admin"):
                self._close_admin_provision_dialog()
                self._set_login_enabled(True)
                return
            self._set_login_enabled(False)
            self._open_admin_provision_dialog()

        self._run_background_task(
            task,
            apply_setup,
            busy_text="A verificar conta administrativa...",
        )

    def _calc_admin_provision_dialog_sizes(self):
        width = Window.width or dp(900)
        height = Window.height or dp(620)
        if width < dp(620):
            width_hint = 0.94
        elif width < dp(980):
            width_hint = 0.76
        else:
            width_hint = 0.58
        dialog_height = min(max(dp(440), height * 0.82), dp(540))
        content_height = max(dp(250), dialog_height - dp(142))
        return width_hint, dialog_height, content_height

    def _update_admin_provision_dialog_size(self):
        if not self._admin_provision_dialog:
            return
        width_hint, dialog_height, content_height = self._calc_admin_provision_dialog_sizes()
        self._admin_provision_dialog.size_hint = (width_hint, None)
        self._admin_provision_dialog.height = dialog_height
        if self._admin_provision_content_container is not None:
            self._admin_provision_content_container.height = content_height

    def _open_admin_provision_dialog(self):
        """Pede o unico codigo assinado capaz de criar o admin local."""
        if self._admin_provision_dialog:
            self._update_admin_provision_dialog_size()
            self._admin_provision_dialog.open()
            return

        accent = self._theme_color("primary", [0.10, 0.33, 0.58, 1])
        card_alt = self._theme_color("card_alt", [0.94, 0.95, 0.97, 1])
        on_primary = self._theme_color("on_primary", [1, 1, 1, 1])
        text_secondary = self._theme_color("text_secondary", [0.35, 0.38, 0.45, 1])

        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(10),
            padding=[dp(16), dp(10), dp(16), dp(10)],
            adaptive_height=True,
            size_hint_x=1,
        )
        content.bind(minimum_height=content.setter("height"))

        status_card = MDCard(
            orientation="horizontal",
            spacing=dp(12),
            padding=[dp(14), dp(11), dp(14), dp(11)],
            size_hint_y=None,
            height=dp(92),
            radius=[dp(16)],
            elevation=0,
            md_bg_color=self._color_with_alpha(accent, 0.12),
        )
        icon_slot = MDCard(
            size_hint=(None, None),
            size=(dp(48), dp(48)),
            radius=[dp(15)],
            elevation=0,
            md_bg_color=self._color_with_alpha(accent, 0.18),
        )
        status_icon = MDIcon(
            icon="account-key-outline",
            halign="center",
            valign="middle",
            theme_text_color="Custom",
            text_color=accent,
        )
        status_icon.bind(size=lambda instance, value: setattr(instance, "text_size", value))
        icon_slot.add_widget(status_icon)
        status_text = MDBoxLayout(orientation="vertical", spacing=dp(3), size_hint_x=1)
        status_text.add_widget(self._register_text_label(
            "Conta administrativa necessária",
            "text_primary",
            "Subtitle1",
            True,
        ))
        status_text.add_widget(self._register_text_label(
            "A licença deste computador está ativa. Importe o código assinado enviado pelo superadmin para criar a única conta admin.",
            "text_secondary",
            "Caption",
        ))
        status_card.add_widget(icon_slot)
        status_card.add_widget(status_text)
        content.add_widget(status_card)

        steps_card = MDCard(
            orientation="horizontal",
            spacing=dp(9),
            padding=[dp(12), dp(8), dp(12), dp(8)],
            size_hint_y=None,
            height=dp(58),
            radius=[dp(14)],
            elevation=0,
            md_bg_color=card_alt,
        )
        steps_icon = MDIcon(
            icon="format-list-numbered",
            halign="center",
            valign="middle",
            theme_text_color="Custom",
            text_color=accent,
            size_hint_x=None,
            width=dp(22),
        )
        steps_icon.bind(size=lambda instance, value: setattr(instance, "text_size", value))
        steps_card.add_widget(steps_icon)
        steps_card.add_widget(self._register_text_label(
            "1. Receba o código SIGE-ADM1  2. Cole-o aqui  3. Entre com a senha temporária e altere-a.",
            "text_secondary",
            "Caption",
        ))
        content.add_widget(steps_card)

        content.add_widget(self._register_text_label(
            "CÓDIGO ADMINISTRATIVO RECEBIDO",
            "text_primary",
            "Caption",
            True,
        ))
        self._admin_provision_code_field = MDTextField(
            hint_text="Cole o código completo SIGE-ADM1 enviado pelo superadmin",
            helper_text="Pode colar todas as linhas do e-mail; o código pertence apenas a esta licença e computador.",
            helper_text_mode="on_focus",
            multiline=True,
            mode="rectangle",
            size_hint_y=None,
            height=dp(110),
        )
        self._admin_provision_code_field.line_color_focus = accent
        content.add_widget(self._admin_provision_code_field)

        self._admin_provision_feedback = MDLabel(
            text="",
            opacity=0,
            font_style="Caption",
            theme_text_color="Custom",
            text_color=self._theme_color("danger", [0.78, 0.22, 0.24, 1]),
            size_hint_y=None,
            height=dp(0),
        )
        self._admin_provision_feedback.bind(
            width=lambda instance, width: setattr(instance, "text_size", (width, None))
        )
        content.add_widget(self._admin_provision_feedback)

        security_card = MDCard(
            orientation="horizontal",
            spacing=dp(9),
            padding=[dp(12), dp(9), dp(12), dp(9)],
            size_hint_y=None,
            height=dp(64),
            radius=[dp(14)],
            elevation=0,
            md_bg_color=card_alt,
        )
        security_icon = MDIcon(
            icon="shield-lock-outline",
            halign="center",
            valign="middle",
            theme_text_color="Custom",
            text_color=accent,
            size_hint_x=None,
            width=dp(22),
        )
        security_icon.bind(size=lambda instance, value: setattr(instance, "text_size", value))
        security_card.add_widget(security_icon)
        security_card.add_widget(self._register_text_label(
            "O código expira e só pode criar uma conta admin nesta instalação. A senha temporária não é guardada nem mostrada por este ecrã.",
            "text_secondary",
            "Caption",
        ))
        content.add_widget(security_card)

        scroll = MDScrollView(do_scroll_x=False, size_hint=(1, 1))
        scroll.add_widget(content)
        width_hint, dialog_height, content_height = self._calc_admin_provision_dialog_sizes()
        self._admin_provision_content_container = MDBoxLayout(
            orientation="vertical",
            size_hint=(1, None),
            height=content_height,
        )
        self._admin_provision_content_container.add_widget(scroll)

        submit_button = MDRaisedButton(
            text="IMPORTAR E CRIAR ADMIN",
            md_bg_color=accent,
            theme_text_color="Custom",
            text_color=on_primary,
            on_release=lambda _button: self._submit_admin_provisioning(),
        )
        self._admin_provision_dialog = MDDialog(
            title="Configuração administrativa",
            type="custom",
            content_cls=self._admin_provision_content_container,
            size_hint=(width_hint, None),
            height=dialog_height,
            auto_dismiss=False,
            buttons=[
                MDFlatButton(
                    text="AGUARDAR CÓDIGO",
                    theme_text_color="Custom",
                    text_color=text_secondary,
                    on_release=lambda _button: self._set_admin_provision_feedback(
                        "A instalação continuará bloqueada até o código administrativo ser importado."
                    ),
                ),
                submit_button,
            ],
        )
        # Este botão não fecha o diálogo: a instalação continua bloqueada até
        # o proprietário entregar o código assinado, evitando um bypass de
        # configuração por clique acidental.
        self._admin_provision_dialog.open()

    def _close_admin_provision_dialog(self):
        if self._admin_provision_code_field is not None:
            self._admin_provision_code_field.text = ""
        if self._admin_provision_dialog:
            self._admin_provision_dialog.dismiss()
        self._admin_provision_dialog = None
        self._admin_provision_code_field = None
        self._admin_provision_feedback = None
        self._admin_provision_content_container = None

    def _set_admin_provision_feedback(self, message=""):
        if not self._admin_provision_feedback:
            return
        self._admin_provision_feedback.text = str(message or "")
        self._admin_provision_feedback.opacity = 1 if message else 0
        self._admin_provision_feedback.height = dp(42) if message else dp(0)

    def _submit_admin_provisioning(self):
        if self.license_client is None or self.operation_in_progress:
            return
        raw_code = str(
            self._admin_provision_code_field.text if self._admin_provision_code_field else ""
        )
        # E-mails podem inserir quebras de linha visuais; o código assinado
        # não admite espaços, portanto removê-los não altera o seu conteúdo.
        code = "".join(raw_code.split())
        if not code:
            self._set_admin_provision_feedback("Cole o código administrativo recebido por e-mail.")
            return

        def task():
            license_result = self.license_client.validate()
            if not license_result or not license_result.allowed:
                return {
                    "status": "license_invalid",
                    "message": "A licença deste computador precisa estar ativa antes de importar a conta.",
                }
            try:
                state = self.license_client.credential_store.load()
                active_license_code = str(state.get("license_code") or "")
                if not active_license_code:
                    return {
                        "status": "license_invalid",
                        "message": "Não foi possível localizar a licença ativa deste computador.",
                    }
                payload = validate_admin_provisioning_for_license(
                    code,
                    self.license_client.public_key,
                    active_license_code,
                )
            except AccountProvisioningError as error:
                return {"status": "invalid_code", "message": str(error)}
            except Exception:
                return {
                    "status": "invalid_code",
                    "message": "Não foi possível validar o código administrativo.",
                }

            create_admin = getattr(self.db, "create_provisioned_admin", None)
            if not callable(create_admin):
                return {
                    "status": "unsupported",
                    "message": "Esta instalação ainda não suporta a importação segura da conta admin. Atualize o sistema.",
                }
            try:
                created = create_admin(
                    payload["username"],
                    payload["password_hash"],
                    email=payload.get("email"),
                    provisioning_id=payload["provisioning_id"],
                )
            except Exception:
                return {
                    "status": "create_failed",
                    "message": "Não foi possível criar a conta administrativa local.",
                }

            if isinstance(created, dict):
                created_ok = bool(
                    created.get("success", created.get("ok", created.get("created", False)))
                )
                failure_reason = str(created.get("message") or created.get("reason") or "")
            else:
                created_ok = bool(created)
                failure_reason = ""
            if not created_ok:
                return {
                    "status": "create_failed",
                    "message": failure_reason or "A conta admin já existe ou não pôde ser criada.",
                }
            # O aviso e apenas uma auditoria adicional. A conta ja foi criada
            # de forma atomica e nao pode depender de rede ou SMTP para ser
            # valida; o e-mail tambem nunca leva senha, hash ou codigo.
            notified = notify_superadmin_account_event(
                payload["username"],
                "ADMIN_CREATED",
            )
            return {
                "status": "ok",
                "username": payload["username"],
                "notified": notified,
            }

        def handle_result(result, error):
            if error:
                self._set_admin_provision_feedback(
                    "Não foi possível importar a conta administrativa neste momento."
                )
                return
            if (result or {}).get("status") != "ok":
                self._set_admin_provision_feedback(
                    (result or {}).get("message") or "Não foi possível importar a conta administrativa."
                )
                return
            username = (result or {}).get("username")
            self._close_admin_provision_dialog()
            if self.username:
                self.username.text = str(username or "")
            self._set_login_enabled(True)
            self._show_message(
                "Conta criada",
                "Entre com a palavra-passe temporária fornecida pelo superadmin. Será obrigatório alterá-la no primeiro acesso.",
            )

        self._run_background_task(
            task,
            handle_result,
            busy_text="A validar e criar conta administrativa...",
        )

    def _install_license_revocation_action(self):
        """Acrescenta uma unica acao visivel apenas para licenca ativa.

        O formulario unificado nao permite autoatendimento de contas, logo os
        links existentes ficam invisiveis. Reutilizar essa faixa evita mudar o
        layout KV e deixa a acao de cancelamento sempre ao alcance antes do
        utilizador tentar iniciar sessao.
        """
        if self.license_client is None or self._license_revocation_action is not None:
            return
        links_row = self.ids.get("form_links_row") if hasattr(self, "ids") else None
        if links_row is None:
            return

        # Estes dois botoes ja nao sao usados pelo login unificado. Sao
        # colapsados (largura e altura) para deixar toda a largura do cartao
        # disponivel para os comandos de licenca.
        for widget_id in ("forgot_button", "register_button"):
            widget = self.ids.get(widget_id)
            if widget is not None:
                widget.size_hint_x = 0
                widget.size_hint_y = None
                widget.width = 0
                widget.height = 0

        accent = self._theme_color("primary", [0.10, 0.33, 0.58, 1])
        # Passamos a empilhar os comandos de licenca na vertical (largura total
        # do cartao) para que os rotulos longos nunca transbordem para a
        # direita. Cada botao reserva altura fixa e colapsa quando escondido.
        self._license_actions_installed = True

        self._license_revocation_action = MDFlatButton(
            text="APLICAR CODIGO DE CANCELAMENTO",
            size_hint_x=1,
            size_hint_y=None,
            height=dp(40),
            font_size=sp(12),
            theme_text_color="Custom",
            text_color=accent,
            opacity=0,
            disabled=True,
            on_release=lambda _button: self._open_license_revocation_dialog(),
        )
        self._license_suspension_action = MDFlatButton(
            text="APLICAR CODIGO DE SUSPENSAO",
            size_hint_x=1,
            size_hint_y=None,
            height=dp(40),
            font_size=sp(12),
            theme_text_color="Custom",
            text_color=accent,
            opacity=0,
            disabled=True,
            on_release=lambda _button: self._open_license_control_dialog("suspension"),
        )
        self._license_reactivation_action = MDFlatButton(
            text="APLICAR CODIGO DE REATIVACAO",
            size_hint_x=1,
            size_hint_y=None,
            height=dp(40),
            font_size=sp(12),
            theme_text_color="Custom",
            text_color=accent,
            opacity=0,
            disabled=True,
            on_release=lambda _button: self._open_license_control_dialog("reactivation"),
        )
        self._license_restoration_action = MDFlatButton(
            text="APLICAR CODIGO DE RECUPERACAO",
            size_hint_x=1,
            size_hint_y=None,
            height=dp(40),
            font_size=sp(12),
            theme_text_color="Custom",
            text_color=accent,
            opacity=0,
            disabled=True,
            on_release=lambda _button: self._open_license_control_dialog("restoration"),
        )
        for action in (
            self._license_revocation_action,
            self._license_suspension_action,
            self._license_reactivation_action,
            self._license_restoration_action,
        ):
            links_row.add_widget(action)

        links_row.orientation = "vertical"
        links_row.spacing = dp(6)

        self.bind(
            operation_in_progress=lambda *_args: self._refresh_license_control_actions()
        )
        self._refresh_license_control_actions()
        self._update_responsive_layout()

    def _refresh_license_revocation_action(self):
        action = self._license_revocation_action
        if action is None:
            return
        visible = bool(self.license_client is not None and self._license_access_confirmed)
        self._set_license_action_visibility(action, visible)

    def _set_license_action_visibility(self, action, visible):
        if action is None:
            return
        action.opacity = 1 if visible else 0
        action.disabled = (not visible) or bool(self.operation_in_progress)
        # Largura sempre total e colapso apenas na altura: o comando de licenca
        # permanece alinhado com a largura do cartao quando visivel e nao
        # ocupa espaco quando escondido.
        action.size_hint_x = 1
        action.size_hint_y = None
        action.height = dp(40) if visible else 0

    def _refresh_license_suspension_action(self):
        visible = bool(self.license_client is not None and self._license_access_confirmed)
        self._set_license_action_visibility(self._license_suspension_action, visible)

    def _refresh_license_reactivation_action(self):
        visible = bool(
            self.license_client is not None
            and self._desktop_license_state == "suspended"
        )
        self._set_license_action_visibility(self._license_reactivation_action, visible)

    def _refresh_license_restoration_action(self):
        visible = bool(
            self.license_client is not None
            and (self._license_access_confirmed or self._desktop_license_state == "revoked")
        )
        self._set_license_action_visibility(self._license_restoration_action, visible)

    def _refresh_license_control_actions(self):
        self._refresh_license_revocation_action()
        self._refresh_license_suspension_action()
        self._refresh_license_reactivation_action()
        self._refresh_license_restoration_action()

    def _open_license_revocation_dialog(self):
        """Pede um SIGE-REV1, sem confundir cancelamento com renovacao."""
        if self.license_client is None or self.operation_in_progress:
            return
        if not self._license_access_confirmed:
            self._show_message(
                "Licenca indisponivel",
                "A licenca deste computador ja nao esta ativa. Atualize a verificacao antes de importar um codigo de cancelamento.",
            )
            return
        if self._license_revocation_dialog:
            self._license_revocation_dialog.open()
            return

        accent = self._theme_color("primary", [0.10, 0.33, 0.58, 1])
        card_alt = self._theme_color("card_alt", [0.94, 0.95, 0.97, 1])
        danger = self._theme_color("danger", [0.78, 0.22, 0.24, 1])
        text_secondary = self._theme_color("text_secondary", [0.35, 0.38, 0.45, 1])
        on_primary = self._theme_color("on_primary", [1, 1, 1, 1])

        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(10),
            padding=[dp(16), dp(10), dp(16), dp(10)],
            adaptive_height=True,
            size_hint_x=1,
        )
        content.bind(minimum_height=content.setter("height"))

        warning_card = MDCard(
            orientation="horizontal",
            spacing=dp(10),
            padding=[dp(12), dp(10), dp(12), dp(10)],
            size_hint_y=None,
            height=dp(82),
            radius=[dp(14)],
            elevation=0,
            md_bg_color=self._color_with_alpha(danger, 0.10),
        )
        warning_icon = MDIcon(
            icon="shield-alert-outline",
            halign="center",
            valign="middle",
            theme_text_color="Custom",
            text_color=danger,
            size_hint_x=None,
            width=dp(26),
        )
        warning_icon.bind(size=lambda instance, value: setattr(instance, "text_size", value))
        warning_card.add_widget(warning_icon)
        warning_card.add_widget(self._register_text_label(
            "Use somente o codigo SIGE-REV1 enviado pelo superadmin para este computador. Depois de aplicado, o acesso desta instalacao fica bloqueado definitivamente.",
            "text_secondary",
            "Caption",
        ))
        content.add_widget(warning_card)

        details_card = MDCard(
            orientation="horizontal",
            spacing=dp(9),
            padding=[dp(12), dp(8), dp(12), dp(8)],
            size_hint_y=None,
            height=dp(56),
            radius=[dp(14)],
            elevation=0,
            md_bg_color=card_alt,
        )
        details_icon = MDIcon(
            icon="lock-check-outline",
            halign="center",
            valign="middle",
            theme_text_color="Custom",
            text_color=accent,
            size_hint_x=None,
            width=dp(22),
        )
        details_icon.bind(size=lambda instance, value: setattr(instance, "text_size", value))
        details_card.add_widget(details_icon)
        details_card.add_widget(self._register_text_label(
            "O codigo e validado localmente pela assinatura e pelo vinculo desta licenca; um codigo de outro computador sera recusado.",
            "text_secondary",
            "Caption",
        ))
        content.add_widget(details_card)

        content.add_widget(self._register_text_label(
            "CODIGO DE CANCELAMENTO RECEBIDO",
            "text_primary",
            "Caption",
            True,
        ))
        self._license_revocation_code_field = MDTextField(
            hint_text="Cole o codigo completo SIGE-REV1. recebido por e-mail",
            helper_text="Pode colar todas as linhas do codigo de cancelamento.",
            helper_text_mode="on_focus",
            multiline=True,
            mode="rectangle",
            size_hint_y=None,
            height=dp(100),
        )
        self._license_revocation_code_field.line_color_focus = accent
        content.add_widget(self._license_revocation_code_field)

        self._license_revocation_feedback = MDLabel(
            text="",
            opacity=0,
            font_style="Caption",
            theme_text_color="Custom",
            text_color=danger,
            size_hint_y=None,
            height=dp(0),
        )
        self._license_revocation_feedback.bind(
            width=lambda instance, width: setattr(instance, "text_size", (width, None))
        )
        content.add_widget(self._license_revocation_feedback)

        close_button = MDFlatButton(
            text="FECHAR",
            theme_text_color="Custom",
            text_color=text_secondary,
        )
        submit_button = MDRaisedButton(
            text="VALIDAR CANCELAMENTO",
            md_bg_color=danger,
            theme_text_color="Custom",
            text_color=on_primary,
            on_release=lambda _button: self._confirm_license_revocation(),
        )
        self._license_revocation_dialog = MDDialog(
            title="Aplicar cancelamento definitivo",
            type="custom",
            content_cls=content,
            size_hint=(0.64, None),
            height=min(max(dp(420), (Window.height or dp(620)) * 0.72), dp(520)),
            auto_dismiss=False,
            buttons=[close_button, submit_button],
        )
        close_button.bind(on_release=lambda _button: self._close_license_revocation_dialog())
        self._license_revocation_dialog.open()

    def _close_license_revocation_dialog(self):
        if self._license_revocation_code_field is not None:
            self._license_revocation_code_field.text = ""
        if self._license_revocation_dialog:
            self._license_revocation_dialog.dismiss()
        self._license_revocation_dialog = None
        self._license_revocation_code_field = None
        self._license_revocation_feedback = None

    def _set_license_revocation_feedback(self, message=""):
        if not self._license_revocation_feedback:
            return
        self._license_revocation_feedback.text = str(message or "")
        self._license_revocation_feedback.opacity = 1 if message else 0
        self._license_revocation_feedback.height = dp(42) if message else dp(0)

    def _confirm_license_revocation(self):
        if self.license_client is None or self.operation_in_progress:
            return
        raw_code = str(
            self._license_revocation_code_field.text if self._license_revocation_code_field else ""
        )
        # Quebras de linha visuais do e-mail nao pertencem ao codigo assinado.
        code = "".join(raw_code.split())
        if not code:
            self._set_license_revocation_feedback(
                "Cole o codigo de cancelamento recebido do superadmin."
            )
            return
        if not code.startswith("SIGE-REV1."):
            self._set_license_revocation_feedback(
                "Este nao e um codigo de cancelamento. O codigo deve iniciar por SIGE-REV1."
            )
            return

        cancel_button = MDFlatButton(text="VOLTAR")
        confirm_button = MDRaisedButton(
            text="CONFIRMAR CANCELAMENTO",
            md_bg_color=self._theme_color("danger", [0.78, 0.22, 0.24, 1]),
        )
        confirmation = MDDialog(
            title="Confirmar cancelamento definitivo?",
            text=(
                "Esta acao validara o codigo e bloqueara o login neste computador de forma definitiva. "
                "Para um bloqueio reversivel, use o codigo SIGE-SUS1 de suspensao."
            ),
            auto_dismiss=False,
            buttons=[cancel_button, confirm_button],
        )

        def submit(_button):
            confirmation.dismiss()
            self._submit_license_revocation(code)

        cancel_button.bind(on_release=lambda _button: confirmation.dismiss())
        confirm_button.bind(on_release=submit)
        confirmation.open()

    def _submit_license_revocation(self, code):
        """Aplica somente uma revogacao confirmada para a licenca ativa."""
        if self.license_client is None or self.operation_in_progress:
            return

        def task():
            active_result = self.license_client.validate()
            if not active_result or not active_result.allowed:
                return {"status": "license_not_active", "result": active_result}
            apply_revocation = getattr(self.license_client, "apply_revocation", None)
            if not callable(apply_revocation):
                return {
                    "status": "unsupported",
                    "message": "Esta versao do sistema ainda nao suporta importar codigos de cancelamento.",
                }
            result = apply_revocation(code)
            if getattr(result, "state", "") != "revoked":
                return {"status": "not_revoked", "result": result}
            return {"status": "revoked", "result": result}

        def handle_result(payload, error):
            if error:
                self._set_license_revocation_feedback(
                    "Nao foi possivel validar o codigo de cancelamento neste momento."
                )
                return
            result = (payload or {}).get("result")
            status = str((payload or {}).get("status") or "")
            if status != "revoked":
                message = (payload or {}).get("message") or self._license_message(result)
                self._set_license_revocation_feedback(message)
                if status == "license_not_active":
                    self._license_access_confirmed = False
                    self._desktop_license_state = str(getattr(result, "state", "") or "")
                    self.license_status = self._license_message(result)
                    self._set_login_enabled(False)
                    self._refresh_license_control_actions()
                return

            # O resultado de revogacao nunca e uma autorizacao. O bloqueio e
            # aplicado na interface imediatamente, antes de o utilizador poder
            # tentar uma nova sessao ou reutilizar campos ja preenchidos.
            self._license_access_confirmed = False
            self._desktop_license_state = "revoked"
            self.license_status = self._license_message(result)
            self._set_login_enabled(False)
            self._refresh_license_control_actions()
            if self.password is not None:
                self.password.text = ""
            self._close_license_revocation_dialog()
            self._close_license_dialog()
            self._show_message(
                "Licenca cancelada definitivamente",
                "O codigo de cancelamento foi aplicado. O acesso a este sistema ficou bloqueado neste computador.",
            )

        self._run_background_task(
            task,
            handle_result,
            busy_text="A validar codigo de cancelamento...",
        )

    def _open_license_control_dialog(self, kind):
        """Importa suspensao, reativacao ou recuperacao sem misturar fluxos."""
        if self.license_client is None or self.operation_in_progress:
            return
        if kind not in {"suspension", "reactivation", "restoration"}:
            return
        if kind == "suspension" and not self._license_access_confirmed:
            self._show_message(
                "Licenca indisponivel",
                "A licenca precisa estar ativa antes de importar uma suspensao.",
            )
            return
        if kind == "reactivation" and self._desktop_license_state != "suspended":
            self._show_message(
                "Reativacao indisponivel",
                "Este computador nao possui uma suspensao ativa que possa ser reativada.",
            )
            return
        if kind == "restoration" and not (
            self._license_access_confirmed or self._desktop_license_state == "revoked"
        ):
            self._show_message(
                "Recuperacao indisponivel",
                "Este computador nao possui um cancelamento ativo que possa ser recuperado.",
            )
            return
        if self._license_control_dialog:
            if self._license_control_kind == kind:
                self._license_control_dialog.open()
                return
            self._close_license_control_dialog()

        self._license_control_kind = kind
        is_suspension = kind == "suspension"
        is_restoration = kind == "restoration"
        prefix = "SIGE-SUS1" if is_suspension else "SIGE-RST1" if is_restoration else "SIGE-RES1"
        title = (
            "Aplicar suspensao de licenca" if is_suspension
            else "Aplicar recuperacao de cancelamento" if is_restoration
            else "Aplicar reativacao de licenca"
        )
        heading = (
            "SUSPENSAO DE LICENCA" if is_suspension
            else "RECUPERACAO DE CANCELAMENTO" if is_restoration
            else "REATIVACAO DE LICENCA"
        )
        details = (
            "A suspensao bloqueia o acesso neste computador, mas podera ser removida somente por um novo codigo assinado do superadmin."
            if is_suspension
            else "A recuperacao reverte somente o cancelamento indicado pelo superadmin. Ela nao altera o prazo contratado nem autoriza outro computador."
            if is_restoration
            else "A reativacao remove somente a suspensao correspondente. Ela nao anula cancelamentos definitivos e a licenca continua sujeita ao prazo contratado."
        )
        accent = self._theme_color("primary", [0.10, 0.33, 0.58, 1])
        danger = self._theme_color("danger", [0.78, 0.22, 0.24, 1])
        text_secondary = self._theme_color("text_secondary", [0.35, 0.38, 0.45, 1])
        on_primary = self._theme_color("on_primary", [1, 1, 1, 1])
        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(10),
            padding=[dp(16), dp(12), dp(16), dp(12)],
            adaptive_height=True,
            size_hint_x=1,
        )
        content.bind(minimum_height=content.setter("height"))
        card = MDCard(
            orientation="horizontal",
            spacing=dp(10),
            padding=[dp(12), dp(10), dp(12), dp(10)],
            size_hint_y=None,
            height=dp(88),
            radius=[dp(14)],
            elevation=0,
            md_bg_color=self._color_with_alpha(danger if is_suspension else accent, 0.10),
        )
        icon = MDIcon(
            icon="pause-circle-outline" if is_suspension else "backup-restore" if is_restoration else "play-circle-outline",
            halign="center",
            valign="middle",
            theme_text_color="Custom",
            text_color=danger if is_suspension else accent,
            size_hint_x=None,
            width=dp(28),
        )
        icon.bind(size=lambda instance, value: setattr(instance, "text_size", value))
        card.add_widget(icon)
        card.add_widget(self._register_text_label(details, "text_secondary", "Caption"))
        content.add_widget(card)
        content.add_widget(self._register_text_label(heading, "text_primary", "Caption", True))
        self._license_control_code_field = MDTextField(
            hint_text=f"Cole o codigo completo {prefix}. recebido por e-mail",
            helper_text="Pode colar todas as linhas do codigo assinado enviado pelo superadmin.",
            helper_text_mode="on_focus",
            multiline=True,
            mode="rectangle",
            size_hint_y=None,
            height=dp(100),
        )
        self._license_control_code_field.line_color_focus = accent
        content.add_widget(self._license_control_code_field)
        self._license_control_feedback = MDLabel(
            text="",
            opacity=0,
            font_style="Caption",
            theme_text_color="Custom",
            text_color=danger,
            size_hint_y=None,
            height=dp(0),
        )
        self._license_control_feedback.bind(
            width=lambda instance, width: setattr(instance, "text_size", (width, None))
        )
        content.add_widget(self._license_control_feedback)
        close_button = MDFlatButton(
            text="FECHAR",
            theme_text_color="Custom",
            text_color=text_secondary,
        )
        submit_button = MDRaisedButton(
            text="VALIDAR SUSPENSAO" if is_suspension else "VALIDAR RECUPERACAO" if is_restoration else "VALIDAR REATIVACAO",
            md_bg_color=danger if is_suspension else accent,
            theme_text_color="Custom",
            text_color=on_primary,
            on_release=lambda _button: self._confirm_license_control(),
        )
        self._license_control_dialog = MDDialog(
            title=title,
            type="custom",
            content_cls=content,
            size_hint=(0.64, None),
            height=min(max(dp(385), (Window.height or dp(620)) * 0.66), dp(490)),
            auto_dismiss=False,
            buttons=[close_button, submit_button],
        )
        close_button.bind(on_release=lambda _button: self._close_license_control_dialog())
        self._license_control_dialog.open()

    def _close_license_control_dialog(self):
        if self._license_control_code_field is not None:
            self._license_control_code_field.text = ""
        if self._license_control_dialog:
            self._license_control_dialog.dismiss()
        self._license_control_dialog = None
        self._license_control_code_field = None
        self._license_control_feedback = None
        self._license_control_kind = ""

    def _set_license_control_feedback(self, message=""):
        if not self._license_control_feedback:
            return
        self._license_control_feedback.text = str(message or "")
        self._license_control_feedback.opacity = 1 if message else 0
        self._license_control_feedback.height = dp(42) if message else dp(0)

    def _confirm_license_control(self):
        if self.license_client is None or self.operation_in_progress:
            return
        kind = self._license_control_kind
        prefix = "SIGE-SUS1." if kind == "suspension" else "SIGE-RST1." if kind == "restoration" else "SIGE-RES1."
        raw_code = str(self._license_control_code_field.text if self._license_control_code_field else "")
        code = "".join(raw_code.split())
        if not code:
            self._set_license_control_feedback("Cole o codigo recebido do superadmin.")
            return
        if not code.startswith(prefix):
            self._set_license_control_feedback(
                f"Este nao e o codigo esperado. O codigo deve iniciar por {prefix[:-1]}."
            )
            return
        is_suspension = kind == "suspension"
        is_restoration = kind == "restoration"
        cancel_button = MDFlatButton(text="VOLTAR")
        confirm_button = MDRaisedButton(
            text="CONFIRMAR SUSPENSAO" if is_suspension else "CONFIRMAR RECUPERACAO" if is_restoration else "CONFIRMAR REATIVACAO",
            md_bg_color=self._theme_color("danger", [0.78, 0.22, 0.24, 1]) if is_suspension else self._theme_color("primary", [0.10, 0.33, 0.58, 1]),
        )
        confirmation = MDDialog(
            title="Confirmar suspensao?" if is_suspension else "Confirmar recuperacao?" if is_restoration else "Confirmar reativacao?",
            text=(
                "Esta acao bloqueara o login neste computador ate receber um codigo de reativacao do superadmin."
                if is_suspension
                else "Esta acao reverte o cancelamento indicado pelo superadmin e podera voltar a permitir o login se a licenca ainda estiver valida."
                if is_restoration
                else "Esta acao removera a suspensao correspondente e permitira voltar a iniciar sessao se a licenca ainda estiver valida."
            ),
            auto_dismiss=False,
            buttons=[cancel_button, confirm_button],
        )

        def submit(_button):
            confirmation.dismiss()
            self._submit_license_control(kind, code)

        cancel_button.bind(on_release=lambda _button: confirmation.dismiss())
        confirm_button.bind(on_release=submit)
        confirmation.open()

    def _submit_license_control(self, kind, code):
        if self.license_client is None or self.operation_in_progress:
            return

        def task():
            current = self.license_client.validate()
            if kind == "suspension":
                if not current or not current.allowed:
                    return {"status": "license_not_active", "result": current}
                apply_suspension = getattr(self.license_client, "apply_suspension", None)
                if not callable(apply_suspension):
                    return {"status": "unsupported", "message": "Esta versao ainda nao suporta importar codigos de suspensao."}
                result = apply_suspension(code)
                if getattr(result, "state", "") != "suspended":
                    return {"status": "not_suspended", "result": result}
                return {"status": "suspended", "result": result}
            if kind == "restoration":
                if not current or not (
                    getattr(current, "allowed", False)
                    or getattr(current, "state", "") == "revoked"
                ):
                    return {"status": "license_not_recoverable", "result": current}
                apply_restoration = getattr(self.license_client, "apply_restoration", None)
                if not callable(apply_restoration):
                    return {"status": "unsupported", "message": "Esta versao ainda nao suporta importar codigos de recuperacao."}
                result = apply_restoration(code)
                if not result or not getattr(result, "allowed", False):
                    return {"status": "not_restored", "result": result}
                return {"status": "restored", "result": result}
            if not current or getattr(current, "state", "") != "suspended":
                return {"status": "license_not_suspended", "result": current}
            apply_reactivation = getattr(self.license_client, "apply_reactivation", None)
            if not callable(apply_reactivation):
                return {"status": "unsupported", "message": "Esta versao ainda nao suporta importar codigos de reativacao."}
            result = apply_reactivation(code)
            if not result or not getattr(result, "allowed", False):
                return {"status": "not_reactivated", "result": result}
            return {"status": "reactivated", "result": result}

        def handle_result(payload, error):
            if error:
                self._set_license_control_feedback("Nao foi possivel validar este codigo de controlo neste momento.")
                return
            result = (payload or {}).get("result")
            status = str((payload or {}).get("status") or "")
            if status == "suspended":
                self._license_access_confirmed = False
                self._desktop_license_state = "suspended"
                self.license_status = self._license_message(result)
                self._set_login_enabled(False)
                self._refresh_license_control_actions()
                if self.password is not None:
                    self.password.text = ""
                self._close_license_control_dialog()
                self._close_license_dialog()
                self._show_message(
                    "Licenca suspensa",
                    "A suspensao foi aplicada. Este computador so voltara a funcionar depois de importar um codigo SIGE-RES1 do superadmin.",
                )
                return
            if status in {"reactivated", "restored"}:
                self._close_license_control_dialog()
                self._close_license_dialog()
                self._grant_license_access(result)
                self._show_message(
                    "Licenca recuperada" if status == "restored" else "Licenca reativada",
                    self._license_message(result),
                )
                return
            message = (payload or {}).get("message") or self._license_message(result)
            self._set_license_control_feedback(message)
            if status in {"license_not_active", "license_not_suspended", "license_not_recoverable"}:
                self._license_access_confirmed = False
                self._desktop_license_state = str(getattr(result, "state", "") or "")
                self.license_status = self._license_message(result)
                self._set_login_enabled(False)
                self._refresh_license_control_actions()

        busy = (
            "A validar codigo de suspensao..." if kind == "suspension"
            else "A validar codigo de recuperacao..." if kind == "restoration"
            else "A validar codigo de reativacao..."
        )
        self._run_background_task(task, handle_result, busy_text=busy)

    @staticmethod
    def _license_message(result):
        expiry = str(getattr(result, "expires_at", "") or "")
        if getattr(result, "allowed", False) and expiry == "9999-12-31T23:59:59+00:00":
            return "Licenca vitalicia ativa."
        if getattr(result, "allowed", False) and expiry:
            visible_expiry = expiry.replace("T", " ").replace("+00:00", " UTC")
            return f"Licenca ativa ate {visible_expiry}."
        return str(getattr(result, "message", "Nao foi possivel validar a licenca."))

    def _grant_license_access(self, result):
        # Uma licenca pode ter chegado pela sincronizacao automatica enquanto
        # o dialogo de pedido ainda estava aberto. Feche-o para que o
        # administrador nao tenha de o dispensar manualmente.
        self._close_license_dialog()
        self._license_access_confirmed = True
        self._desktop_license_state = str(getattr(result, "state", "active") or "active")
        self.license_status = self._license_message(result)
        self._refresh_license_control_actions()
        # O login so e libertado quando existir uma conta administrativa
        # local valida ou o codigo assinado for importado com sucesso.
        self._set_login_enabled(False)
        Clock.schedule_once(lambda _dt: self._ensure_admin_setup(), 0)

    def _deny_license_access(self, result, *, show_activation=False):
        self._license_access_confirmed = False
        self._desktop_license_state = str(getattr(result, "state", "") or "")
        self.license_status = self._license_message(result)
        self._set_login_enabled(False)
        self._refresh_license_control_actions()
        if show_activation:
            self._open_license_dialog(result)

    def _validate_desktop_license(self, *, continue_login=False, show_activation=True):
        if self.license_client is None:
            self._license_access_confirmed = True
            if continue_login:
                super().login()
            return
        if self.operation_in_progress:
            return

        def task():
            return self.license_client.validate()

        def handle_result(result, error):
            if error:
                result = LicenseResult(False, "storage_error", "Nao foi possivel validar a licenca local.")
            if result and result.allowed:
                self._grant_license_access(result)
                if continue_login:
                    super(UnifiedLoginScreen, self).login()
                return
            self._deny_license_access(result or LicenseResult(False, "storage_error", "Nao foi possivel validar a licenca local."), show_activation=show_activation)

        self._run_background_task(task, handle_result, busy_text="A validar licenca do computador...")

    def _calc_license_dialog_sizes(self):
        width = Window.width or dp(900)
        height = Window.height or dp(620)
        if width < dp(620):
            width_hint = 0.94
        elif width < dp(980):
            width_hint = 0.76
        else:
            width_hint = 0.64
        dialog_height = min(max(dp(380), height * 0.65), dp(460))
        content_height = max(dp(220), dialog_height - dp(150))
        return width_hint, dialog_height, content_height

    def _update_license_dialog_size(self):
        if not self._license_dialog:
            return
        width_hint, dialog_height, content_height = self._calc_license_dialog_sizes()
        self._license_dialog.size_hint = (width_hint, None)
        self._license_dialog.height = dialog_height
        if self._license_content_container is not None:
            self._license_content_container.height = content_height

    def _open_license_dialog(self, result):
        if self._license_dialog:
            self._license_dialog.open()
            return

        license_import_states = {"activation_required", "expired"}
        can_activate = getattr(result, "state", "") in license_import_states
        is_renewal = getattr(result, "state", "") == "expired"
        request_ready = False
        self._license_request_code = ""
        self._license_request_recipient = ""
        self._license_request_submitted = False
        if can_activate:
            try:
                (
                    self._license_request_recipient,
                    self._license_request_code,
                    self._license_request_submitted,
                ) = self.license_client.pending_license_request()
                request_ready = True
            except Exception:
                request_ready = False
        accent = self._theme_color("primary", [0.10, 0.33, 0.58, 1])
        card_alt = self._theme_color("card_alt", [0.94, 0.95, 0.97, 1])
        text_secondary = self._theme_color("text_secondary", [0.35, 0.38, 0.45, 1])
        on_primary = self._theme_color("on_primary", [1, 1, 1, 1])
        dialog_title = (
            "Renovacao da licenca" if is_renewal
            else "Ativacao da licenca" if can_activate
            else "Licenca suspensa" if getattr(result, "state", "") == "suspended"
            else "Licenca cancelada" if getattr(result, "state", "") == "revoked"
            else "Licenca indisponivel"
        )
        status_title = (
            "Pedido pendente" if can_activate and self._license_request_submitted
            else "Renovacao necessaria" if is_renewal
            else "Ativacao necessaria" if can_activate
            else "Reativacao necessaria" if getattr(result, "state", "") == "suspended"
            else "Recuperacao necessaria" if getattr(result, "state", "") == "revoked"
            else "Verificacao necessaria"
        )
        status_message = self._license_message(result)
        if can_activate and self._license_request_submitted:
            status_message = "Pedido enviado. Aguarde a resposta do responsavel."
        elif is_renewal and request_ready:
            status_message = "Selecione o plano e peca a renovacao."
        elif can_activate and not request_ready:
            status_message = "Pode copiar o pedido e envia-lo ao responsavel."

        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(10),
            padding=[dp(16), dp(10), dp(16), dp(10)],
            adaptive_height=True,
            size_hint_x=1,
        )
        content.bind(minimum_height=content.setter("height"))

        status_card = MDCard(
            orientation="horizontal",
            spacing=dp(12),
            padding=[dp(14), dp(11), dp(14), dp(11)],
            size_hint_y=None,
            height=dp(92),
            radius=[dp(16)],
            elevation=0,
            md_bg_color=self._color_with_alpha(accent, 0.12),
        )
        icon_slot = MDCard(
            size_hint=(None, None),
            size=(dp(48), dp(48)),
            radius=[dp(15)],
            elevation=0,
            md_bg_color=self._color_with_alpha(accent, 0.18),
        )
        status_icon = MDIcon(
            icon="email-check-outline" if can_activate and self._license_request_submitted else "shield-sync" if is_renewal else "shield-key-outline" if can_activate else "shield-alert-outline",
            halign="center",
            valign="middle",
            theme_text_color="Custom",
            text_color=accent,
        )
        status_icon.bind(size=lambda instance, value: setattr(instance, "text_size", value))
        icon_slot.add_widget(status_icon)
        status_text = MDBoxLayout(orientation="vertical", spacing=dp(3), size_hint_x=1)
        status_text.add_widget(self._register_text_label(status_title, "text_primary", "Subtitle1", True))
        status_text.add_widget(self._register_text_label(status_message, "text_secondary", "Caption"))
        status_card.add_widget(icon_slot)
        status_card.add_widget(status_text)
        content.add_widget(status_card)

        if can_activate:
            self._license_selected_plan = "" if is_renewal else "Mensal"
            saved_details = {}
            try:
                saved_details = parse_license_request(self.license_client.activation_request()).get("request_details") or {}
            except Exception:
                pass
            if saved_details:
                self._license_selected_plan = (
                    "" if saved_details.get("plan_choice") == "Manter plano atual"
                    else saved_details.get("requested_plan", "")
                )
            self._license_plan_button = MDRectangleFlatIconButton(
                icon="menu-down",
                text="Plano: " + (self._license_selected_plan or "Manter plano atual"),
                theme_text_color="Custom", text_color=accent,
                disabled=bool(saved_details),
                on_release=lambda caller: self._open_license_plan_menu(caller, is_renewal),
            )
            content.add_widget(self._license_plan_button)
            content.add_widget(self._register_text_label(
                "O pedido usa os dados desta instalacao. Quando o superadmin emitir a licenca, o sistema recebe e aplica-a automaticamente.",
                "text_secondary", "Caption",
            ))
        else:
            support_card = MDCard(
                orientation="horizontal",
                spacing=dp(9),
                padding=[dp(12), dp(10), dp(12), dp(10)],
                size_hint_y=None,
                height=dp(64),
                radius=[dp(14)],
                elevation=0,
                md_bg_color=card_alt,
            )
            support_icon = MDIcon(
                icon="information-outline",
                halign="center",
                valign="middle",
                theme_text_color="Custom",
                text_color=accent,
                size_hint_x=None,
                width=dp(22),
            )
            support_icon.bind(size=lambda instance, value: setattr(instance, "text_size", value))
            support_card.add_widget(support_icon)
            support_message = (
                "A reativacao sera aplicada automaticamente assim que o superadmin a emitir."
                if getattr(result, "state", "") == "suspended"
                else "A recuperacao sera aplicada automaticamente assim que o superadmin a emitir."
                if getattr(result, "state", "") == "revoked"
                else "Confirme a data e hora do computador e tente novamente. Se o problema continuar, contacte o superadmin."
            )
            support_card.add_widget(self._register_text_label(
                support_message,
                "text_secondary",
                "Caption",
            ))
            content.add_widget(support_card)

        scroll = MDScrollView(do_scroll_x=False, size_hint=(1, 1))
        scroll.add_widget(content)
        width_hint, dialog_height, content_height = self._calc_license_dialog_sizes()
        self._license_content_container = MDBoxLayout(
            orientation="vertical",
            size_hint=(1, None),
            height=content_height,
        )
        self._license_content_container.add_widget(scroll)

        close_button = MDFlatButton(
            text="FECHAR",
            theme_text_color="Custom",
            text_color=text_secondary,
        )
        buttons = [close_button]
        if can_activate:
            if request_ready and self._license_request_submitted:
                buttons.insert(
                    0,
                    MDFlatButton(
                        text="REENVIAR PEDIDO",
                        theme_text_color="Custom",
                        text_color=accent,
                        on_release=lambda _button: self._retry_license_request_email(),
                    ),
                )
            else:
                buttons.insert(
                    0,
                    MDRaisedButton(
                        text="PEDIR RENOVACAO" if is_renewal else "PEDIR LICENCA",
                        md_bg_color=accent,
                        theme_text_color="Custom",
                        text_color=on_primary,
                        on_release=lambda _button: self._confirm_license_request_email(),
                    ),
                )
        elif getattr(result, "state", "") != "not_configured":
            buttons.insert(0, MDRaisedButton(text="TENTAR NOVAMENTE", on_release=lambda _button: self._retry_license_validation()))
        self._license_dialog = MDDialog(
            title=dialog_title,
            type="custom",
            content_cls=self._license_content_container,
            size_hint=(width_hint, None),
            height=dialog_height,
            auto_dismiss=False,
            buttons=buttons,
        )
        close_button.bind(on_release=lambda _button: self._close_license_dialog())
        self._license_dialog.open()

    def _open_license_plan_menu(self, caller, is_renewal):
        choices = [("", "Manter plano atual")] if is_renewal else []
        choices.extend((plan, plan) for plan in LICENSE_REQUEST_PLANS)
        self._license_plan_menu = MDDropdownMenu(
            caller=caller,
            items=[{
                "viewclass": "OneLineListItem", "text": label,
                "on_release": lambda value=plan: self._select_license_plan(value),
            } for plan, label in choices],
            width_mult=4,
        )
        self._license_plan_menu.open()

    def _select_license_plan(self, plan):
        self._license_selected_plan = plan
        self._license_plan_button.text = "Plano: " + (plan or "Manter plano atual")
        self._license_plan_menu.dismiss()

    def _retry_license_validation(self):
        self._close_license_dialog()
        self._validate_desktop_license(show_activation=True)

    def _switch_to_reactivation_dialog(self):
        self._close_license_dialog()
        Clock.schedule_once(lambda _dt: self._open_license_control_dialog("reactivation"), 0)

    def _switch_to_restoration_dialog(self):
        self._close_license_dialog()
        Clock.schedule_once(lambda _dt: self._open_license_control_dialog("restoration"), 0)

    def _close_license_dialog(self):
        if getattr(self, "_license_plan_menu", None):
            self._license_plan_menu.dismiss()
        self._license_plan_menu = None
        self._license_plan_button = None
        if self._license_dialog:
            self._license_dialog.dismiss()
        self._license_dialog = None
        self._license_content_container = None
        self._license_code_field = None
        self._license_feedback = None
        self._license_request_code = ""
        self._license_request_recipient = ""
        self._license_request_submitted = False

    def _set_license_feedback(self, message=""):
        if not self._license_feedback:
            return
        self._license_feedback.text = str(message or "")
        self._license_feedback.opacity = 1 if message else 0
        self._license_feedback.height = dp(42) if message else 0

    def _retry_license_request_email(self):
        """Permite reenviar o pedido salvo, sem gerar uma nova licenca."""
        if self.license_client is None or self.operation_in_progress:
            return
        try:
            self.license_client.retry_license_request()
            self._license_request_submitted = False
        except Exception:
            self._set_license_feedback("Nao foi possivel preparar o reenvio deste pedido.")
            return
        self._confirm_license_request_email()

    def _confirm_license_request_email(self):
        if self.license_client is None or self.operation_in_progress:
            return
        try:
            _recipient, _request_code, already_submitted = self.license_client.pending_license_request()
        except Exception as error:
            if str(error) == "request_email_not_configured":
                try:
                    code = self.license_client.prepare_license_request(
                        username=self.username.text.strip() if self.username else "",
                        plan=getattr(self, "_license_selected_plan", ""),
                    )
                except Exception:
                    self._set_license_feedback("Nao foi possivel preparar o pedido. Tente novamente.")
                    return
                if getattr(self, "_license_plan_button", None):
                    self._license_plan_button.disabled = True
                self._show_license_request_fallback("", code)
            else:
                self._set_license_feedback("Nao foi possivel preparar o pedido de licenca deste computador.")
            return
        if already_submitted:
            self._set_license_feedback("Este computador ja realizou o pedido de licenca.")
            return

        try:
            self.license_client.prepare_license_request(
                username=self.username.text.strip() if self.username else "",
                plan=getattr(self, "_license_selected_plan", ""),
            )
        except Exception:
            self._set_license_feedback("Nao foi possivel preparar o pedido. Tente novamente.")
            return
        if getattr(self, "_license_plan_button", None):
            self._license_plan_button.disabled = True
        self._send_license_request_email()

    def _send_license_request_email(self, confirmation=None):
        if confirmation is not None:
            confirmation.dismiss()
        try:
            recipient, request_code, already_submitted = self.license_client.pending_license_request()
            if already_submitted:
                self._set_license_feedback("Este computador ja realizou o pedido de licenca.")
                return
        except Exception:
            self._set_license_feedback("Nao foi possivel preparar o pedido de licenca deste computador.")
            return

        def task():
            try:
                send_system_email(
                    recipient,
                    LICENSE_REQUEST_SUBJECT,
                    license_request_body(request_code),
                )
                return "sent"
            except EmailServiceNotConfigured:
                # Uma instalacao sem SMTP nao recebe credenciais do dono. Como
                # alternativa segura, abre o cliente de e-mail do proprio
                # utilizador com a mesma mensagem preenchida.
                return "mail_client"

        def handle_result(mode, error):
            if error:
                self._set_license_feedback(
                    "O envio direto falhou. Vamos abrir o pedido no seu e-mail."
                )
                self._open_prepared_license_request_email(recipient, request_code)
                return
            if mode == "mail_client":
                self._open_prepared_license_request_email(recipient, request_code)
                return
            self._finish_license_request_submission(
                "Pedido enviado",
                "Aguarde a resposta do responsavel. Depois, cole o codigo recebido e clique em APLICAR CODIGO.",
            )

        self._run_background_task(task, handle_result, busy_text="A enviar pedido de licenca...")

    def _open_prepared_license_request_email(self, recipient, request_code):
        try:
            subject = quote(LICENSE_REQUEST_SUBJECT)
            body = quote(license_request_body(request_code))
            mailto_url = f"mailto:{quote(recipient, safe='@')}?subject={subject}&body={body}"
            if not webbrowser.open(mailto_url):
                raise RuntimeError("Nao foi possivel abrir o aplicativo de e-mail deste computador.")
        except Exception:
            self._show_license_request_fallback(recipient, request_code)
            return
        # Abrir o editor de e-mail nao comprova que a mensagem foi enviada.
        self._set_license_feedback("Pedido aberto no seu e-mail. Clique em Enviar nessa janela.")

    def _show_license_request_fallback(self, recipient, request_code):
        close = MDFlatButton(text="FECHAR")
        copy = MDRaisedButton(text="COPIAR PEDIDO")
        dialog = MDDialog(
            title="Enviar pedido ao responsavel",
            text="O envio automatico nao esta disponivel. Copie o pedido e envie ao responsavel por mensagem ou e-mail.",
            buttons=[close, copy],
        )
        def copy_request(*_args):
            from kivy.core.clipboard import Clipboard
            try:
                Clipboard.copy((f"Para: {recipient}\n\n" if recipient else "") + license_request_body(request_code))
            except Exception:
                self._set_license_feedback("Nao foi possivel copiar o pedido. Tente novamente.")
                return
            dialog.dismiss()
            self._set_license_feedback("Pedido copiado. Envie-o ao responsavel para receber a licenca.")
        close.bind(on_release=lambda *_args: dialog.dismiss())
        copy.bind(on_release=copy_request)
        dialog.open()

    def _finish_license_request_submission(self, title, message):
        try:
            if not self.license_client.mark_license_request_submitted():
                self._set_license_feedback("Este computador ja realizou o pedido de licenca.")
                return
        except Exception:
            self._set_license_feedback("O pedido foi enviado, mas nao foi possivel guardar a confirmacao local.")
            return
        self._license_request_submitted = True
        self._close_license_dialog()
        self._show_message(title, message)

    def _submit_license_activation(self):
        if self.license_client is None or self.operation_in_progress:
            return
        code = str(self._license_code_field.text if self._license_code_field else "").strip()
        if not code:
            self._set_license_feedback("Informe o codigo de ativacao.")
            return

        def task():
            return self.license_client.activate(code)

        def handle_result(result, error):
            if error:
                result = LicenseResult(False, "storage_error", "Nao foi possivel ativar a licenca local.")
            if result and result.allowed:
                self._close_license_dialog()
                self._grant_license_access(result)
                self._show_message("Licenca ativada", self._license_message(result))
                return
            failed = result or LicenseResult(False, "storage_error", "Nao foi possivel ativar a licenca local.")
            self.license_status = self._license_message(failed)
            self._set_license_feedback(self._license_message(failed))

        self._run_background_task(task, handle_result, busy_text="A ativar este computador...")

    def login(self):
        if self.license_client is not None and not self._license_access_confirmed:
            self._validate_desktop_license(continue_login=True, show_activation=True)
            return
        super().login()

    def _apply_variant_defaults(self):
        super()._apply_variant_defaults()
        self.profile_name = self._tr("login.unified.profile_name")
        self.identity_badge = self._tr("login.unified.identity_badge")
        self.hero_title = self._tr("login.unified.hero_title")
        self.hero_subtitle = self._tr("login.unified.hero_subtitle")
        self.feature_one = self._tr("login.unified.feature_one")
        self.feature_two = self._tr("login.unified.feature_two")
        self.feature_three = self._tr("login.unified.feature_three")
        self.login_heading = self._tr("login.unified.heading")
        self.login_caption = self._tr("login.unified.caption")
        self.login_button_text = self._tr("login.unified.button")
        self.form_footer_text = self._tr("login.unified.footer")
        self.context_label = self._tr("login.unified.context")

    def _complete_login(self, user, role):
        self.success_screen = "admin_home" if role == "admin" else "manager"
        super()._complete_login(user, role)


class ManagerLoginScreen(LoginScreen):
    def __init__(self, **kwargs):
        kwargs.setdefault("login_variant", "manager")
        kwargs.setdefault("allowed_roles", ["manager"])
        kwargs.setdefault("allow_admin_setup", False)
        kwargs.setdefault("registration_mode", "manager_self_service")
        kwargs.setdefault("registration_password_min_len", 8)
        kwargs.setdefault("success_screen", "manager")
        kwargs.setdefault("show_theme_toggle", True)
        super().__init__(**kwargs)
