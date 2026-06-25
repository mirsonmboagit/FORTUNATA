import os
from threading import Thread

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
from kivy.metrics import dp
from kivy.core.window import Window

from datetime import datetime, timedelta

from kivymd.uix.screen import MDScreen
from kivymd.uix.dialog import MDDialog
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDIcon, MDLabel
from kivymd.uix.textfield import MDTextField
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.menu import MDDropdownMenu

from database.provider import get_db, uses_remote_backend
from utils.i18n import language_options, language_short, translate
from utils.security_questions import QUESTIONS

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
    registration_password_min_len = NumericProperty(4)
    login_blocked = BooleanProperty(False)
    operation_in_progress = BooleanProperty(False)
    operation_status = StringProperty("")

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
        self._forgot_dialog = None
        self._forgot_user_field = None
        self._forgot_answer_fields = []
        self._forgot_new_password = None
        self._forgot_confirm_password = None
        self._forgot_content_container = None
        self._register_dialog = None
        self._register_username = None
        self._register_password = None
        self._register_confirm = None
        self._register_answer_fields = []
        self._register_feedback = None
        self._register_content_container = None
        self._register_submit_button = None
        self._register_cancel_button = None
        self._register_submit_default_text = "CRIAR CONTA"
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

        if form_links_row is not None:
            form_links_row.orientation = "vertical" if narrow_form else "horizontal"
            form_links_row.spacing = dp(6) if narrow_form else dp(8)

        for button in (forgot_button, register_button):
            if button is None:
                continue
            if narrow_form:
                button.size_hint_x = 1
                button.width = 0
            else:
                button.size_hint_x = None
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

    def _uses_remote_db(self):
        return uses_remote_backend(self.db)

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
        if self._uses_remote_db():
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
            busy_text="A validar configuracao administrativa...",
        )

    def _open_setup_admin_dialog(self, mode='create', original_username=None):
        self._setup_mode = mode
        self._setup_original_username = original_username

        if self._setup_dialog:
            self._setup_dialog.dismiss()
            self._setup_dialog = None

        title = 'Criar Administrador' if mode == 'create' else 'Atualizar Administrador Padrao'
        label_text = 'Configure o administrador inicial' if mode == 'create' else 'Atualize o administrador padrao'
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
            hint_text='Nome de usuario',
            mode='rectangle',
            size_hint_y=None,
            height=dp(56),
        )
        if original_username:
            self._setup_username.text = original_username
        content.add_widget(self._setup_username)

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
        password = self._setup_password.text.strip()
        confirm = self._setup_confirm.text.strip()

        if not username or not password or not confirm:
            self._show_message('Erro', 'Todos os campos sao obrigatorios')
            return
        if len(password) < 6:
            self._show_message('Erro', 'A senha deve ter no minimo 6 caracteres')
            return
        if password != confirm:
            self._show_message('Erro', 'As senhas nao coincidem')
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
                    self.db.log_action(username, 'admin', 'UPDATE_ADMIN', f"Admin atualizado: {original} -> {username}")
                except Exception:
                    pass
            else:
                user_exists = self.db.user_exists(username)
                if self._db_last_error():
                    return None
                if user_exists:
                    return {"status": "user_exists"}
                created = self.db.create_admin(username, password)
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
                self._show_operation_error('Nao foi possivel concluir a configuracao do admin')
                return
            status = (result or {}).get("status")
            if status == "user_exists":
                self._show_message('Erro', 'Nome de usuario ja existe')
                return
            if status == "update_failed":
                self._show_message('Erro', 'Nao foi possivel atualizar o admin')
                return
            if status == "create_failed":
                self._show_message('Erro', 'Nao foi possivel criar o admin')
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
            busy_text="A guardar configuracao do admin...",
        )

    def _close_setup_dialog(self):
        if self._setup_dialog:
            self._setup_dialog.dismiss()
            self._setup_dialog = None

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
            title='Alteracao obrigatoria',
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
            self._show_message('Erro', 'Todos os campos sao obrigatorios')
            return
        if len(password) < 6:
            self._show_message('Erro', 'A senha deve ter no minimo 6 caracteres')
            return
        if password != confirm:
            self._show_message('Erro', 'As senhas nao coincidem')
            return

        username, role = self._pending_login or (None, None)
        if not username:
            self._show_message('Erro', 'Utilizador invalido')
            return

        def task():
            updated = self.db.update_user_password(username, password, role=role)
            if not updated and self._db_last_error():
                return None
            if not updated:
                return {"status": "update_failed"}
            try:
                self.db.log_action(username, role or 'admin', 'UPDATE_ADMIN', 'Senha do admin atualizada')
            except Exception:
                pass
            return {"status": "ok"}

        def handle_result(updated, error):
            if error:
                self._show_operation_error('Nao foi possivel atualizar a senha')
                return
            if (updated or {}).get("status") != "ok":
                self._show_message('Erro', 'Nao foi possivel atualizar a senha')
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
                self.username_error = "Usuario e obrigatorio!"
            if not pwd:
                self.password_error = "Senha e obrigatoria!"
            return

        def task():
            role = self.db.validate_user(user, pwd)
            if role is None and self._db_last_error():
                return None
            is_default = False
            if role == 'admin':
                is_default = bool(self.db.is_user_password_default(user, self.DEFAULT_PASSWORDS))
                if self._db_last_error():
                    return None
            return {"role": role, "is_default": is_default}

        def handle_login(result, error):
            if error:
                self._show_operation_error('Nao foi possivel validar o login no momento')
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
                if role == 'admin' and (result or {}).get("is_default"):
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
        app = App.get_running_app()
        if app:
            app.current_user = username
            app.current_role = role
            app._ai_notifications_seen_key = None
            app._ai_banners_shown = False
            app._ai_banners_last_key = None

    def forgot_password(self):
        # Fluxo de recuperacao por perguntas de seguranca.
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
            text='Responda as perguntas para recuperar a senha',
            theme_text_color='Secondary',
            size_hint_y=None,
            height=dp(24),
        ))

        self._forgot_user_field = MDTextField(
            hint_text='Usuario',
            mode='rectangle',
            size_hint_y=None,
            height=dp(56),
        )
        if self.username and self.username.text.strip():
            self._forgot_user_field.text = self.username.text.strip()
        content_box.add_widget(self._forgot_user_field)

        self._forgot_answer_fields = []
        for question in QUESTIONS:
            content_box.add_widget(MDLabel(
                text=question,
                theme_text_color='Secondary',
                size_hint_y=None,
                height=dp(24),
            ))
            field = MDTextField(
                hint_text='Resposta',
                password=True,
                mode='rectangle',
                size_hint_y=None,
                height=dp(56),
            )
            self._forgot_answer_fields.append(field)
            content_box.add_widget(field)

        self._forgot_new_password = MDTextField(
            hint_text='Nova senha',
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

        scroll = MDScrollView(do_scroll_x=False, size_hint=(1, 1))
        scroll.add_widget(content_box)
        dialog_height, content_height = self._calc_forgot_sizes()
        self._forgot_content_container = MDBoxLayout(
            orientation='vertical',
            size_hint=(1, None),
            height=content_height,
        )
        self._forgot_content_container.add_widget(scroll)

        self._forgot_dialog = MDDialog(
            title='Recuperacao de senha',
            type='custom',
            content_cls=self._forgot_content_container,
            size_hint=(0.7, None),
            height=dialog_height,
            buttons=[
                MDFlatButton(text='CANCELAR', on_release=self._dismiss_forgot_dialog),
                MDFlatButton(text='SALVAR', on_release=self._submit_forgot_questions),
            ],
        )
        self._forgot_dialog.open()

    def _calc_forgot_sizes(self):
        dialog_height = min(Window.height * 0.8, dp(520))
        content_height = max(dp(220), dialog_height - dp(140))
        return dialog_height, content_height

    def _update_forgot_dialog_size(self):
        dialog_height, content_height = self._calc_forgot_sizes()
        if self._forgot_dialog:
            self._forgot_dialog.size_hint = (0.7, None)
            self._forgot_dialog.height = dialog_height
        if self._forgot_content_container:
            self._forgot_content_container.height = content_height

    def _dismiss_forgot_dialog(self, *args):
        self._clear_forgot_fields()
        if self._forgot_dialog:
            self._forgot_dialog.dismiss()

    def _clear_forgot_fields(self):
        if self._forgot_user_field:
            self._forgot_user_field.text = ''
        for field in self._forgot_answer_fields:
            field.text = ''
        if self._forgot_new_password:
            self._forgot_new_password.text = ''
        if self._forgot_confirm_password:
            self._forgot_confirm_password.text = ''

    def _submit_forgot_questions(self, *args):
        username = self._forgot_user_field.text.strip() if self._forgot_user_field else ''
        answers = [field.text.strip() for field in self._forgot_answer_fields]
        new_password = self._forgot_new_password.text.strip() if self._forgot_new_password else ''
        confirm = self._forgot_confirm_password.text.strip() if self._forgot_confirm_password else ''

        if not username or any(not ans for ans in answers):
            self._show_message('Erro', 'Preencha usuario e todas as respostas')
            return
        if not new_password or not confirm:
            self._show_message('Erro', 'Preencha a nova senha')
            return
        if len(new_password) < 6:
            self._show_message('Erro', 'A senha deve ter no minimo 6 caracteres')
            return
        if new_password != confirm:
            self._show_message('Erro', 'As senhas nao coincidem')
            return

        def task():
            role = self.db.get_user_role(username)
            if not role and self._db_last_error():
                return None
            if not role:
                return {"status": "user_not_found", "username": username}

            result = self.db.verify_security_answers(username, answers)
            if not result and self._db_last_error():
                return None
            if not result or not result.get("ok"):
                return {"status": "answers_failed", "result": result or {}, "role": role}

            updated = self.db.update_user_password(username, new_password, role=role)
            if not updated and self._db_last_error():
                return None
            if not updated:
                return {"status": "password_update_failed"}

            self.db.update_security_state(username, 0, None)
            try:
                self.db.log_action(username, role or 'manager', 'RESET_PASSWORD_QA', 'Senha redefinida via perguntas')
            except Exception:
                pass
            return {"status": "ok"}

        def handle_result(result, error):
            if error:
                self._show_operation_error('Nao foi possivel processar a recuperacao')
                return

            status = (result or {}).get("status")
            if status == "user_not_found":
                self._audit_event(
                    (result or {}).get("username") or username,
                    "guest",
                    "ACCESS_ATTEMPT",
                    "Tentativa de recuperacao de senha para utilizador inexistente",
                )
                self._show_message('Erro', 'Usuario nao encontrado')
                return
            if status == "answers_failed":
                payload = (result or {}).get("result") or {}
                reason = payload.get("reason")
                audit_role = (result or {}).get("role") or "guest"
                if reason == "not_configured":
                    self._audit_event(
                        username,
                        audit_role,
                        "ACCESS_DENIED",
                        "Tentativa de recuperacao sem perguntas configuradas",
                    )
                    self._show_message('Erro', 'Perguntas nao configuradas. Fale com o admin')
                elif reason == "locked":
                    remaining = payload.get("remaining_minutes") or 15
                    self._audit_event(
                        username,
                        audit_role,
                        "SECURITY_ALERT",
                        f"Tentativa de recuperacao bloqueada | aguarde {remaining} min",
                    )
                    self._show_message('Erro', f'Tentativas excedidas. Aguarde {remaining} min')
                elif reason == "invalid":
                    remaining = payload.get("remaining")
                    attempts = payload.get("attempts")
                    details = "Respostas de recuperacao incorretas"
                    if remaining is not None:
                        details += f" | restantes: {remaining}"
                    if attempts is not None:
                        details += f" | falhas: {attempts}"
                    self._audit_event(
                        username,
                        audit_role,
                        "ACCESS_ATTEMPT",
                        details,
                    )
                    if remaining is not None:
                        self._show_message('Erro', f'Respostas incorretas. Tentativas restantes: {remaining}')
                    else:
                        self._show_message('Erro', 'Respostas incorretas')
                else:
                    self._show_message('Erro', 'Nao foi possivel validar as respostas')
                return
            if status == "password_update_failed":
                self._show_message('Erro', 'Nao foi possivel atualizar a senha')
                return

            self._show_message('Sucesso', 'Senha atualizada com sucesso!')
            self._dismiss_forgot_dialog()

        self._run_background_task(
            task,
            handle_result,
            busy_text="A validar recuperacao...",
        )

    def register(self):
        mode = self._normalized_registration_mode()
        if mode == 'disabled':
            self._show_message('Info', 'Cadastro indisponivel neste app')
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
        if not any((self._register_username, self._register_password, self._register_confirm, self._register_answer_fields)):
            return
        fields = [self._register_username, self._register_password, self._register_confirm]
        fields.extend(self._register_answer_fields or [])
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
        # Abre cadastro de novo usuario conforme o modo permitido.
        if self._register_dialog:
            self._register_dialog.dismiss()
            self._register_dialog = None

        mode = self._normalized_registration_mode()
        is_admin_setup = mode == 'admin_bootstrap'
        title = 'Criar administrador inicial' if is_admin_setup else 'Criar conta gerente'
        role_text = 'Administrador' if is_admin_setup else 'Manager'
        subtitle = (
            'Primeiro acesso para configuracao e gestao do sistema.'
            if is_admin_setup else
            'Acesso para vendas, consulta rapida e operacao diaria.'
        )
        accent = self._register_accent_color(mode)
        text_secondary = self._theme_color("text_secondary", [0.36, 0.40, 0.48, 1])
        card_alt = self._theme_color("card_alt", [0.94, 0.95, 0.97, 1])
        on_primary = self._theme_color("on_primary", [1, 1, 1, 1])
        min_len = int(self.registration_password_min_len or 4)

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
            f'A senha precisa ter no minimo {min_len} caracteres.',
            "text_secondary",
            "Caption",
        ))
        content.add_widget(tip_row)

        self._register_username = MDTextField(
            hint_text='Nome de usuario',
            icon_right='account-outline',
            mode='rectangle',
            size_hint_y=None,
            height=dp(64),
        )
        self._register_username.line_color_focus = accent
        if self.username and self.username.text:
            self._register_username.text = self.username.text.strip()
        content.add_widget(self._register_username)

        self._register_password = MDTextField(
            hint_text='Senha',
            helper_text=f'Minimo {min_len} caracteres',
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
            helper_text='Repita a senha para evitar erro de digitacao',
            helper_text_mode='on_focus',
            icon_right='lock-check-outline',
            password=True,
            mode='rectangle',
            size_hint_y=None,
            height=dp(64),
        )
        self._register_confirm.line_color_focus = accent
        content.add_widget(self._register_confirm)

        questions_title = MDBoxLayout(
            orientation='horizontal',
            spacing=dp(8),
            size_hint_y=None,
            height=dp(32),
        )
        questions_icon = MDIcon(
            icon='shield-question-outline',
            halign='center',
            valign='middle',
            theme_text_color='Custom',
            text_color=accent,
            size_hint_x=None,
            width=dp(22),
        )
        questions_icon.bind(size=lambda inst, value: setattr(inst, "text_size", value))
        questions_title.add_widget(questions_icon)
        questions_title.add_widget(self._register_text_label(
            'Perguntas de recuperacao',
            "text_primary",
            "Subtitle2",
            True,
        ))
        content.add_widget(questions_title)

        self._register_answer_fields = []
        for index, question in enumerate(QUESTIONS, start=1):
            content.add_widget(self._register_text_label(question, "text_secondary", "Caption"))
            field = MDTextField(
                hint_text=f'Resposta {index}',
                helper_text='Usada para recuperar a senha',
                helper_text_mode='on_focus',
                icon_right='key-variant',
                password=True,
                mode='rectangle',
                size_hint_y=None,
                height=dp(64),
            )
            field.line_color_focus = accent
            self._register_answer_fields.append(field)
            content.add_widget(field)

        self._register_confirm.bind(on_text_validate=lambda *args: self._focus_register_field(
            self._register_answer_fields[0] if self._register_answer_fields else None
        ))
        for index, field in enumerate(self._register_answer_fields):
            if index + 1 < len(self._register_answer_fields):
                next_field = self._register_answer_fields[index + 1]
                field.bind(on_text_validate=lambda *args, target=next_field: self._focus_register_field(target))
            else:
                field.bind(on_text_validate=self._submit_register)

        register_fields = [self._register_username, self._register_password, self._register_confirm]
        register_fields.extend(self._register_answer_fields)
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
            icon='shield-check-outline',
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
            'As respostas ficam protegidas e serao pedidas se esquecer a senha.',
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
        self._register_password = None
        self._register_confirm = None
        self._register_answer_fields = []
        self._register_feedback = None
        self._register_content_container = None
        self._register_submit_button = None
        self._register_cancel_button = None

    def _submit_register(self, *args):
        # Valida e grava a conta criada no dialogo.
        mode = self._normalized_registration_mode()
        username = self._register_username.text.strip() if self._register_username else ''
        password = self._register_password.text.strip() if self._register_password else ''
        confirm = self._register_confirm.text.strip() if self._register_confirm else ''
        answers = [field.text.strip() for field in (self._register_answer_fields or [])]

        if not username:
            self._set_register_feedback('Informe o nome de usuario.')
            self._focus_register_field(self._register_username)
            return
        if ' ' in username:
            self._set_register_feedback('O nome de usuario nao deve ter espacos.')
            self._focus_register_field(self._register_username)
            return
        if not password:
            self._set_register_feedback('Informe a senha da conta.')
            self._focus_register_field(self._register_password)
            return
        if not confirm:
            self._set_register_feedback('Confirme a senha antes de criar a conta.')
            self._focus_register_field(self._register_confirm)
            return

        min_len = int(self.registration_password_min_len or 4)
        if len(password) < min_len:
            self._set_register_feedback(f'A senha deve ter no minimo {min_len} caracteres.')
            self._focus_register_field(self._register_password)
            return
        if password != confirm:
            self._set_register_feedback('As senhas nao coincidem.')
            self._focus_register_field(self._register_confirm)
            return
        if not answers or any(not answer for answer in answers):
            self._set_register_feedback('Responda as perguntas de recuperacao.')
            for field in self._register_answer_fields or []:
                if not field.text.strip():
                    self._focus_register_field(field)
                    break
            return

        role = ''
        if mode == 'manager_self_service':
            role = 'manager'
        elif mode == 'admin_bootstrap':
            role = 'admin'
        else:
            self._show_message('Info', 'Cadastro indisponivel neste app')
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
                created = self.db.create_admin(username, password)
                if not created and self._db_last_error():
                    return None
                if not created:
                    has_admin = self.db.has_admin()
                    if self._db_last_error():
                        return None
                    if has_admin:
                        return {"status": "admin_exists"}
                    return {"status": "create_failed"}
                if not self.db.set_security_questions(username, answers):
                    return {"status": "questions_failed"}
            else:
                created = self.db.create_user(username, password, 'manager')
                if not created and self._db_last_error():
                    return None
                if not created:
                    return {"status": "create_failed"}
                if not self.db.set_security_questions(username, answers):
                    return {"status": "questions_failed"}
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
                    self._set_register_feedback('Nao foi possivel criar o administrador.')
                else:
                    self._set_register_feedback('Nao foi possivel criar a conta.')
                return

            status = (result or {}).get("status")
            if status == "user_exists":
                self._set_register_feedback('Nome de usuario ja existe.')
                self._focus_register_field(self._register_username)
                return
            if status == "admin_exists":
                self._show_message('Info', 'Ja existe um administrador. Novos administradores devem ser criados em Configuracoes.')
                self._close_register_dialog()
                return
            if status == "create_failed":
                if role == 'admin':
                    self._set_register_feedback('Nao foi possivel criar o admin.')
                else:
                    self._set_register_feedback('Nao foi possivel criar a conta.')
                return
            if status == "questions_failed":
                self._set_register_feedback('Conta criada, mas nao foi possivel salvar as perguntas de recuperacao.')
                return

            self._close_register_dialog()
            if self.username:
                self.username.text = username
            if self.password:
                self.password.text = ''
            self.username_error = ''
            self.password_error = ''
            self._show_message('Sucesso', 'Conta criada com sucesso! Faca login.')

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
        kwargs.setdefault("registration_password_min_len", 4)
        kwargs.setdefault("success_screen", "admin_home")
        super().__init__(**kwargs)


class ManagerLoginScreen(LoginScreen):
    def __init__(self, **kwargs):
        kwargs.setdefault("login_variant", "manager")
        kwargs.setdefault("allowed_roles", ["manager"])
        kwargs.setdefault("allow_admin_setup", False)
        kwargs.setdefault("registration_mode", "manager_self_service")
        kwargs.setdefault("registration_password_min_len", 4)
        kwargs.setdefault("success_screen", "manager")
        kwargs.setdefault("show_theme_toggle", True)
        super().__init__(**kwargs)
