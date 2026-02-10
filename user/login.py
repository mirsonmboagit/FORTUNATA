from kivy.properties import ObjectProperty, StringProperty
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

from database.database import Database
from utils.security_questions import QUESTIONS, check_answer

Builder.load_file('user/login_screen.kv')


class LoginScreen(MDScreen):
    username = ObjectProperty(None)
    password = ObjectProperty(None)

    username_error = StringProperty("")
    password_error = StringProperty("")

    DEFAULT_PASSWORDS = ["123", "123456"]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.db = Database()
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

    def on_enter(self):
        self.carousel_event = Clock.schedule_interval(self.next_slide, 4)
        Clock.schedule_once(lambda dt: self._ensure_admin_setup(), 0.05)

    def on_leave(self):
        if self.carousel_event:
            self.carousel_event.cancel()

    def next_slide(self, dt):
        self.ids.carousel.load_next()

    def _set_login_enabled(self, enabled):
        self._login_blocked = not enabled
        if self.username:
            self.username.disabled = not enabled
        if self.password:
            self.password.disabled = not enabled

    def _find_default_admin(self):
        for username in self.db.get_admin_usernames():
            if self.db.is_admin_default(username, self.DEFAULT_PASSWORDS):
                return username
        return None

    def _ensure_admin_setup(self):
        if not self.db.has_admin():
            self._set_login_enabled(False)
            self._open_setup_admin_dialog(mode='create')
            return

        default_admin = self._find_default_admin()
        if default_admin:
            self._set_login_enabled(False)
            self._open_setup_admin_dialog(mode='update_default', original_username=default_admin)
            return

        self._set_login_enabled(True)

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

        if self._setup_mode == 'update_default':
            original = self._setup_original_username or username
            self.db.cursor.execute(
                "SELECT COUNT(*) FROM users WHERE username = ? AND username != ?",
                (username, original),
            )
            if self.db.cursor.fetchone()[0] > 0:
                self._show_message('Erro', 'Nome de usuario ja existe')
                return

            if not self.db.update_admin_credentials(original, username, password):
                self._show_message('Erro', 'Nao foi possivel atualizar o admin')
                return

            self.db.log_action(username, 'admin', 'UPDATE_ADMIN', f"Admin atualizado: {original} -> {username}")
        else:
            self.db.cursor.execute("SELECT COUNT(*) FROM users WHERE username = ?", (username,))
            if self.db.cursor.fetchone()[0] > 0:
                self._show_message('Erro', 'Nome de usuario ja existe')
                return

            if not self.db.create_admin(username, password):
                self._show_message('Erro', 'Nao foi possivel criar o admin')
                return

        self._close_setup_dialog()
        self._set_login_enabled(True)

        if self.db.is_user_password_default(username, self.DEFAULT_PASSWORDS):
            self._open_force_password_dialog(username, 'admin')
            return

        self._complete_login(username, 'admin')

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

        if not self.db.update_user_password(username, password, role=role):
            self._show_message('Erro', 'Nao foi possivel atualizar a senha')
            return

        self.db.log_action(username, role or 'admin', 'UPDATE_ADMIN', 'Senha do admin atualizada')

        if self._force_dialog:
            self._force_dialog.dismiss()
            self._force_dialog = None

        self._complete_login(username, role or 'admin')

    def login(self):
        if self._login_blocked:
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

        role = self.db.validate_user(user, pwd)

        if role in ("admin", "manager"):
            if role == 'admin' and self.db.is_user_password_default(user, self.DEFAULT_PASSWORDS):
                self._open_force_password_dialog(user, role)
                return
            self._complete_login(user, role)
        else:
            self.username_error = "Credenciais invalidas!"
            self.password_error = "Credenciais invalidas!"

    def _complete_login(self, user, role):
        self._set_current_user(user, role)
        self.db.log_action(user, role, 'LOGIN', 'Login realizado')
        self.reset_fields()
        self.manager.current = role

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

        self.db.cursor.execute('SELECT role FROM users WHERE username = ?', (username,))
        row = self.db.cursor.fetchone()
        if not row:
            self._show_message('Erro', 'Usuario nao encontrado')
            return
        role = row[0]

        record = self._get_security_record(username)
        if not record:
            self._show_message('Erro', 'Perguntas nao configuradas. Fale com o admin')
            return

        now = datetime.now()
        lock_until = record.get('lock_until')
        if lock_until and now < lock_until:
            remaining = int((lock_until - now).total_seconds() / 60) + 1
            self._show_message('Erro', f'Tentativas excedidas. Aguarde {remaining} min')
            return
        if lock_until and now >= lock_until:
            self._update_security_state(username, 0, None)
            record['attempts'] = 0
            record['lock_until'] = None

        hashes = record.get('hashes', [])
        if len(hashes) < len(answers):
            self._show_message('Erro', 'Perguntas nao configuradas. Fale com o admin')
            return

        hashes = hashes[:len(answers)]
        all_ok = True
        for ans, hashed in zip(answers, hashes):
            if not check_answer(ans, hashed):
                all_ok = False
                break

        if not all_ok:
            attempts = (record.get('attempts') or 0) + 1
            if attempts >= 5:
                lock_until = now + timedelta(minutes=15)
                self._update_security_state(username, attempts, lock_until)
                self._show_message('Erro', 'Muitas tentativas. Aguarde 15 minutos')
                return
            self._update_security_state(username, attempts, None)
            remaining = 5 - attempts
            self._show_message('Erro', f'Respostas incorretas. Tentativas restantes: {remaining}')
            return

        if not self.db.update_user_password(username, new_password, role=role):
            self._show_message('Erro', 'Nao foi possivel atualizar a senha')
            return

        self._update_security_state(username, 0, None)
        self.db.log_action(username, role or 'manager', 'RESET_PASSWORD_QA', 'Senha redefinida via perguntas')
        self._show_message('Sucesso', 'Senha atualizada com sucesso!')
        self._dismiss_forgot_dialog()

    def _get_security_record(self, username):
        self.db.cursor.execute(
            'SELECT q1_hash, q2_hash, q3_hash, q4_hash, attempts, lock_until '
            'FROM user_security_questions WHERE username = ?',
            (username,)
        )
        row = self.db.cursor.fetchone()
        if not row:
            return None
        q1, q2, q3, _q4, attempts, lock_until = row
        lock_dt = None
        if lock_until:
            try:
                lock_dt = datetime.fromisoformat(lock_until)
            except Exception:
                lock_dt = None
        return {
            'hashes': [q1, q2, q3],
            'attempts': attempts or 0,
            'lock_until': lock_dt,
        }

    def _update_security_state(self, username, attempts, lock_until):
        lock_value = lock_until.isoformat() if lock_until else None
        self.db.cursor.execute(
            'UPDATE user_security_questions SET attempts = ?, lock_until = ? WHERE username = ?',
            (attempts, lock_value, username)
        )
        self.db.conn.commit()

    def register(self):
        if not self.db.has_admin():
            self._open_setup_admin_dialog(mode='create')
            return

        default_admin = self._find_default_admin()
        if default_admin:
            self._open_setup_admin_dialog(mode='update_default', original_username=default_admin)
            return

        self._show_message('Info', 'Contacte o admin para criar contas')

    def _show_message(self, title, message):
        MDDialog(
            title=title,
            text=message,
            buttons=[
                MDFlatButton(text='OK', on_release=lambda x: x.parent.parent.parent.parent.dismiss())
            ],
        ).open()
