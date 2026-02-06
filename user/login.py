from kivymd.uix.screen import MDScreen
from kivy.properties import ObjectProperty, StringProperty
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.app import App
from database.database import Database

Builder.load_file('user/login_screen.kv')


class LoginScreen(MDScreen):
    username = ObjectProperty(None)
    password = ObjectProperty(None)

    username_error = StringProperty("")
    password_error = StringProperty("")

    DEFAULT_USERNAME = "admin"
    DEFAULT_PASSWORD = "123"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.db = Database()
        self.carousel_event = None

    def on_enter(self):
        self.carousel_event = Clock.schedule_interval(self.next_slide, 4)

    def on_leave(self):
        if self.carousel_event:
            self.carousel_event.cancel()

    def next_slide(self, dt):
        self.ids.carousel.load_next()

    def login(self):
        user = self.username.text
        pwd = self.password.text

        self.username_error = ""
        self.password_error = ""

        if not user or not pwd:
            if not user:
                self.username_error = "Usuário é obrigatório!"
            if not pwd:
                self.password_error = "Senha é obrigatória!"
            return

        if user == self.DEFAULT_USERNAME and pwd == self.DEFAULT_PASSWORD:
            self._set_current_user(user, "admin")
            self.db.log_action(user, "admin", "LOGIN", "Login padrão")
            self.reset_fields()
            self.manager.current = "admin"
            return

        role = self.db.validate_user(user, pwd)

        if role in ("admin", "manager"):
            self._set_current_user(user, role)
            self.db.log_action(user, role, "LOGIN", "Login realizado")
            self.reset_fields()
            self.manager.current = role
        else:
            self.username_error = "Credenciais inválidas!"
            self.password_error = "Credenciais inválidas!"

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

    def forgot_password(self):
        print("Recuperar senha - a implementar")

    def register(self):
        print("Cadastrar novo usuário - a implementar")
