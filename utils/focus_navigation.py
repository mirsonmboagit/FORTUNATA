from kivy.clock import Clock
from kivy.core.window import Window


class FormKeyboardController:
    """Shared TAB traversal and shortcuts for modal forms."""

    _active_controllers = []

    def __init__(
        self,
        fields=None,
        *,
        host=None,
        initial_field=None,
        on_escape=None,
        on_submit=None,
        shortcuts=None,
    ):
        self.host = host
        self.on_escape = on_escape
        self.on_submit = on_submit
        self._initial_field = initial_field
        self._fields = []
        self._shortcuts = {}
        self._bound = False
        self.set_fields(fields or [])
        self.set_shortcuts(shortcuts or {})

    def set_fields(self, fields):
        self._fields = [field for field in fields if field is not None]

    def set_shortcuts(self, shortcuts):
        normalized = {}
        for combo, callback in (shortcuts or {}).items():
            key = self._normalize_shortcut(combo)
            if key is not None and callable(callback):
                normalized[key] = callback
        self._shortcuts = normalized

    def activate(self, focus_initial=False):
        self._promote()
        if not self._bound:
            Window.bind(on_key_down=self._on_window_key_down)
            self._bound = True
        if focus_initial:
            self.focus_initial()

    def deactivate(self, *_args):
        if self in self.__class__._active_controllers:
            self.__class__._active_controllers.remove(self)
        if self._bound:
            Window.unbind(on_key_down=self._on_window_key_down)
            self._bound = False

    def focus_initial(self, *_args, delay=0.05):
        target = self._resolve_initial_field()
        if target is None:
            fields = self._get_focusable_fields()
            target = fields[0] if fields else None
        if target is None:
            return
        Clock.schedule_once(lambda _dt, widget=target: self._focus_widget(widget), delay)

    def focus_next(self, reverse=False):
        fields = self._get_focusable_fields()
        if not fields:
            return False

        current_index = -1
        for index, field in enumerate(fields):
            if getattr(field, "focus", False):
                current_index = index
                break

        if current_index == -1:
            target = fields[-1] if reverse else fields[0]
        else:
            step = -1 if reverse else 1
            target = fields[(current_index + step) % len(fields)]

        self._focus_widget(target)
        return True

    def _on_window_key_down(self, _window, keycode, _scancode, text, modifiers):
        if not self._can_handle_keyboard():
            return False

        key_name = self._normalize_key(keycode, text)
        modifier_tuple = self._normalize_modifiers(modifiers)
        shortcut = self._shortcuts.get((modifier_tuple, key_name))
        if shortcut:
            shortcut()
            return True

        if key_name == "tab":
            return self.focus_next(reverse="shift" in modifier_tuple)

        if key_name == "escape" and callable(self.on_escape):
            self.on_escape()
            return True

        if key_name in {"enter", "numpadenter"} and "ctrl" in modifier_tuple and callable(self.on_submit):
            self.on_submit()
            return True

        return False

    def _can_handle_keyboard(self):
        active = self.__class__._active_controllers
        if active and active[-1] is not self:
            return False

        host = self.host
        if host is not None and host in getattr(Window, "children", []):
            return Window.children[0] is host
        return True

    def _promote(self):
        if self in self.__class__._active_controllers:
            self.__class__._active_controllers.remove(self)
        self.__class__._active_controllers.append(self)

    def _resolve_initial_field(self):
        target = self._initial_field() if callable(self._initial_field) else self._initial_field
        return target if self._is_focusable(target) else None

    def _get_focusable_fields(self):
        return [field for field in self._fields if self._is_focusable(field)]

    @staticmethod
    def _focus_widget(widget):
        if widget is None:
            return
        try:
            widget.focus = True
        except Exception:
            pass

    @staticmethod
    def _is_focusable(widget):
        if widget is None:
            return False
        if getattr(widget, "disabled", False):
            return False
        if getattr(widget, "readonly", False):
            return False
        if hasattr(widget, "opacity") and widget.opacity == 0:
            return False
        return hasattr(widget, "focus")

    @staticmethod
    def _normalize_modifiers(modifiers):
        aliases = {
            "control": "ctrl",
            "lctrl": "ctrl",
            "rctrl": "ctrl",
            "alt-gr": "alt",
            "altgr": "alt",
            "super": "meta",
        }
        normalized = []
        for modifier in modifiers or []:
            name = aliases.get(str(modifier).strip().lower(), str(modifier).strip().lower())
            if name not in normalized:
                normalized.append(name)
        normalized.sort()
        return tuple(normalized)

    @staticmethod
    def _normalize_key(keycode, text=""):
        special = {
            9: "tab",
            13: "enter",
            27: "escape",
            271: "numpadenter",
        }
        if keycode in special:
            return special[keycode]

        raw_text = str(text or "").strip().lower()
        if len(raw_text) == 1:
            return raw_text

        if isinstance(keycode, int) and 32 <= keycode <= 126:
            return chr(keycode).lower()

        return str(keycode).strip().lower()

    @classmethod
    def _normalize_shortcut(cls, combo):
        if not combo:
            return None

        if isinstance(combo, (list, tuple)):
            parts = [str(part).strip().lower() for part in combo if str(part).strip()]
        else:
            parts = [part.strip().lower() for part in str(combo).split("+") if part.strip()]

        if not parts:
            return None

        key = cls._normalize_shortcut_key(parts[-1])
        modifiers = cls._normalize_modifiers(parts[:-1])
        return modifiers, key

    @staticmethod
    def _normalize_shortcut_key(key):
        aliases = {
            "esc": "escape",
            "return": "enter",
        }
        return aliases.get(str(key).strip().lower(), str(key).strip().lower())
