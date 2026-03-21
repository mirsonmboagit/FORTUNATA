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
from kivymd.uix.label import MDLabel
from kivymd.uix.textfield import MDTextField
from kivymd.uix.button import MDFlatButton
from kivymd.uix.scrollview import MDScrollView

from database.provider import get_db
from utils.security_questions import QUESTIONS

LOGIN_KV_PATH = os.path.join(os.path.dirname(__file__), 'login_screen.kv')
try:
    Builder.unload_file(LOGIN_KV_PATH)
except Exception:
    pass
Builder.load_file(LOGIN_KV_PATH)


class LoginScreen(MDScreen):
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
    back_screen = StringProperty("")
    show_back_button = BooleanProperty(False)
    show_theme_toggle = BooleanProperty(False)
    theme_toggle_text = StringProperty("Modo escuro")
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
        self._operation_token = 0
        self._apply_variant_defaults()

    def on_kv_post(self, base_widget):
        self._apply_variant_defaults()
        self._sync_theme_toggle_text()
        self._update_responsive_layout()

    def on_size(self, *args):
        Clock.schedule_once(lambda dt: self._update_responsive_layout(), 0)

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

        if admin_highlights_grid:
            admin_highlights_grid.cols = 1 if compact else 2

        if admin_preview_card:
            admin_preview_card.opacity = 1 if show_admin_preview else 0
            admin_preview_card.disabled = not show_admin_preview
            admin_preview_card.size_hint_y = None
            admin_preview_card.height = (
                dp(252) if compact else dp(292) if medium else dp(326)
            ) if show_admin_preview else 0

        if manager_preview_card:
            manager_preview_card.opacity = 1 if show_manager_preview else 0
            manager_preview_card.disabled = not show_manager_preview
            manager_preview_card.size_hint_y = None
            manager_preview_card.height = (
                dp(244) if compact else dp(282) if medium else dp(312)
            ) if show_manager_preview else 0

        hero_shell.padding = (
            [dp(18), dp(16), dp(18), dp(16)] if compact else [dp(22), dp(20), dp(22), dp(20)]
        )
        hero_shell.spacing = dp(12) if compact else dp(14)

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

    def _apply_variant_defaults(self):
        variant = (self.login_variant or "admin").strip().lower()
        configs = {
            "admin": {
                "profile_name": "Administrador",
                "identity_badge": "Acesso Administrativo",
                "hero_title": "Controlo administrativo da operacao comercial.",
                "hero_subtitle": "Acesso ao backoffice com foco em configuracao, supervisao e leitura do negocio.",
                "feature_one": "Catalogo e stock",
                "feature_two": "Relatorios e alertas",
                "feature_three": "Utilizadores e definicoes",
                "login_heading": "Entrar no painel administrativo",
                "login_caption": "Use a sua conta para gerir produtos, indicadores e configuracoes do sistema.",
                "login_button_text": "ENTRAR NO PAINEL",
                "form_footer_text": "Credenciais administrativas com acesso ao controlo total da mercearia.",
            },
            "manager": {
                "profile_name": "Gerente",
                "identity_badge": "Acesso Operacional",
                "hero_title": "Entrada rapida para vendas e rotina da loja.",
                "hero_subtitle": "Ambiente simples para atendimento, consulta de historico e operacao diaria.",
                "feature_one": "Vendas e produtos",
                "feature_two": "Historico e perdas",
                "feature_three": "Tema e leitura",
                "login_heading": "Entrar na operacao da loja",
                "login_caption": "Acesso objetivo para atendimento, registo de vendas e consulta rapida.",
                "login_button_text": "ENTRAR PARA OPERAR",
                "form_footer_text": "Conta de gerente com foco em rapidez, leitura e estabilidade.",
            },
        }
        selected = configs.get(variant, configs["admin"])
        for key, value in selected.items():
            if not getattr(self, key):
                setattr(self, key, value)
        self.show_back_button = bool(self.back_screen)

    def _sync_theme_toggle_text(self):
        app = App.get_running_app()
        is_dark = bool(app and getattr(app, "theme_style", "Light") == "Dark")
        self.theme_toggle_text = "Modo claro" if is_dark else "Modo escuro"

    def on_enter(self):
        self._sync_theme_toggle_text()
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

    def _uses_remote_db(self):
        module_name = str(getattr(self.db.__class__, "__module__", "") or "")
        return module_name.startswith("database.client")

    def _run_background_task(self, task, callback, busy_text="A processar..."):
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

    def _find_default_admin(self):
        for username in self.db.get_admin_usernames():
            if self.db.is_admin_default(username, self.DEFAULT_PASSWORDS):
                return username
        return None

    def _ensure_admin_setup(self):
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

        title = 'Criar Admin' if mode == 'create' else 'Atualizar Admin'
        label_text = 'Configure o admin inicial' if mode == 'create' else 'Atualize o admin padrao'
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
                    self.username_error = "Acesso nao autorizado!"
                    self.password_error = "Acesso nao autorizado!"
                    return
                if role == 'admin' and (result or {}).get("is_default"):
                    self._open_force_password_dialog(user, role)
                    return
                self._complete_login(user, role)
                return

            self.username_error = "Credenciais invalidas!"
            self.password_error = "Credenciais invalidas!"

        self._run_background_task(
            task,
            handle_login,
            busy_text="A validar credenciais...",
        )

    def _complete_login(self, user, role):
        self._set_current_user(user, role)
        self._log_action_async(user, role, 'LOGIN', 'Login realizado')
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
                return {"status": "user_not_found"}

            result = self.db.verify_security_answers(username, answers)
            if not result and self._db_last_error():
                return None
            if not result or not result.get("ok"):
                return {"status": "answers_failed", "result": result or {}}

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
                self._show_message('Erro', 'Usuario nao encontrado')
                return
            if status == "answers_failed":
                reason = ((result or {}).get("result") or {}).get("reason")
                if reason == "not_configured":
                    self._show_message('Erro', 'Perguntas nao configuradas. Fale com o admin')
                elif reason == "locked":
                    remaining = ((result or {}).get("result") or {}).get("remaining_minutes") or 15
                    self._show_message('Erro', f'Tentativas excedidas. Aguarde {remaining} min')
                elif reason == "invalid":
                    remaining = ((result or {}).get("result") or {}).get("remaining")
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

    def _open_register_dialog(self):
        if self._register_dialog:
            self._register_dialog.dismiss()
            self._register_dialog = None

        mode = self._normalized_registration_mode()
        title = 'Criar Conta'
        subtitle = 'Preencha os dados para criar uma nova conta'
        if mode == 'manager_self_service':
            subtitle = 'Nova conta manager'
        elif mode == 'admin_bootstrap':
            subtitle = 'Criar admin inicial'

        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(12),
            padding=dp(20),
            adaptive_height=True,
        )
        content.add_widget(MDLabel(
            text=subtitle,
            theme_text_color='Secondary',
            size_hint_y=None,
            height=dp(24),
        ))

        self._register_username = MDTextField(
            hint_text='Nome de usuario',
            mode='rectangle',
            size_hint_y=None,
            height=dp(56),
        )
        if self.username and self.username.text:
            self._register_username.text = self.username.text.strip()
        content.add_widget(self._register_username)

        self._register_password = MDTextField(
            hint_text='Senha',
            password=True,
            mode='rectangle',
            size_hint_y=None,
            height=dp(56),
        )
        content.add_widget(self._register_password)

        self._register_confirm = MDTextField(
            hint_text='Confirmar senha',
            password=True,
            mode='rectangle',
            size_hint_y=None,
            height=dp(56),
        )
        content.add_widget(self._register_confirm)

        self._register_dialog = MDDialog(
            title=title,
            type='custom',
            content_cls=content,
            auto_dismiss=False,
            buttons=[
                MDFlatButton(text='CANCELAR', on_release=self._close_register_dialog),
                MDFlatButton(text='CRIAR', on_release=self._submit_register),
            ],
        )
        self._register_dialog.open()

    def _close_register_dialog(self, *args):
        if self._register_dialog:
            self._register_dialog.dismiss()
            self._register_dialog = None

    def _submit_register(self, *args):
        mode = self._normalized_registration_mode()
        username = self._register_username.text.strip() if self._register_username else ''
        password = self._register_password.text.strip() if self._register_password else ''
        confirm = self._register_confirm.text.strip() if self._register_confirm else ''

        if not username or not password or not confirm:
            self._show_message('Erro', 'Todos os campos sao obrigatorios')
            return

        min_len = int(self.registration_password_min_len or 4)
        if len(password) < min_len:
            self._show_message('Erro', f'A senha deve ter no minimo {min_len} caracteres')
            return
        if password != confirm:
            self._show_message('Erro', 'As senhas nao coincidem')
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
            else:
                created = self.db.create_user(username, password, 'manager')
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
                    self._show_operation_error('Nao foi possivel criar o admin')
                else:
                    self._show_operation_error('Nao foi possivel criar a conta')
                return

            status = (result or {}).get("status")
            if status == "user_exists":
                self._show_message('Erro', 'Nome de usuario ja existe')
                return
            if status == "admin_exists":
                self._show_message('Info', 'Ja existe admin. Novos admins devem ser criados em Configuracoes.')
                self._close_register_dialog()
                return
            if status == "create_failed":
                if role == 'admin':
                    self._show_message('Erro', 'Nao foi possivel criar o admin')
                else:
                    self._show_message('Erro', 'Nao foi possivel criar a conta')
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
            busy_text="A criar conta...",
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
