from datetime import datetime

from kivy.clock import Clock
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import StringProperty
from kivymd.uix.screen import MDScreen


Builder.load_file("user/profile_selector.kv")


class ProfileSelectorScreen(MDScreen):
    datetime_text = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._clock_ev = None

    def on_kv_post(self, base_widget):
        self._update_datetime()
        self._update_responsive_layout()

    def on_enter(self):
        self._update_datetime()
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

    def open_admin_login(self, *args):
        self._go_to("login_admin")

    def open_manager_login(self, *args):
        self._go_to("login_manager")

    def _go_to(self, screen_name):
        if self.manager and screen_name in self.manager.screen_names:
            self.manager.current = screen_name
