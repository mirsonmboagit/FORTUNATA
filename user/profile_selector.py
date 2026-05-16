from datetime import datetime

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import StringProperty
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen

from utils.i18n import language_options, language_short, translate


Builder.load_file("user/profile_selector.kv")


class ProfileSelectorScreen(MDScreen):
    datetime_text = StringProperty("")
    language_button_text = StringProperty("Idioma: PT")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._clock_ev = None
        self._language_menu = None
        self._language_bound_app = None

    def on_kv_post(self, base_widget):
        self._bind_app_language()
        self._update_datetime()
        self._sync_language_button_text()
        self._update_responsive_layout()

    def on_enter(self):
        self._bind_app_language()
        self._update_datetime()
        self._sync_language_button_text()
        if self._clock_ev:
            self._clock_ev.cancel()
        self._clock_ev = Clock.schedule_interval(lambda dt: self._update_datetime(), 30)

    def on_leave(self):
        if self._clock_ev:
            self._clock_ev.cancel()
            self._clock_ev = None

    def on_size(self, *args):
        Clock.schedule_once(lambda dt: self._update_responsive_layout(), 0)

    def _update_datetime(self):
        self.datetime_text = datetime.now().strftime("%d/%m/%Y | %H:%M")

    def _update_responsive_layout(self):
        if not self.ids:
            return
        grid = self.ids.get("profile_grid")
        if grid:
            grid.cols = 1 if self.width < dp(980) else 2

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
        self._sync_language_button_text()

    def open_admin_login(self, *args):
        self._go_to("login_admin")

    def open_manager_login(self, *args):
        self._go_to("login_manager")

    def _go_to(self, screen_name):
        if self.manager and screen_name in self.manager.screen_names:
            self.manager.current = screen_name
