import importlib
import importlib.util
import io
import os
import platform
import shutil
import subprocess
import sys
from threading import Thread
from kivy.uix.popup import Popup
from ui.components.native_widgets import (
    NativeBoxLayout as MDBoxLayout, NativeButton as MDRaisedButton,
    NativeCard as MDCard, NativeDialog as MDDialog,
    NativeFlatButton as MDFlatButton, NativeIconButton as MDIconButton,
    NativeLabel as MDLabel,
)
MDRectangleFlatButton = MDFlatButton
from kivy.uix.scrollview import ScrollView
from kivy.uix.image import Image as KivyImage
from kivy.graphics import Color, RoundedRectangle
from kivy.graphics.texture import Texture
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.clock import Clock
from kivy.app import App

ZOOM_MIN = 0.25
ZOOM_MAX = 4.0
ZOOM_PRESETS = [0.25, 0.33, 0.5, 0.67, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5,
                1.75, 2.0, 2.5, 3.0, 4.0]
WHEEL_INVERT = False        # True se a roda estiver com o sentido trocado
MAX_TEXTURE = 4096          # lado máximo (px) da textura renderizada
CACHE_MAX_BYTES = 120 * 1024 * 1024
CACHE_MAX_ITEMS = 8


def _theme_color(name, fallback):
    app = App.get_running_app()
    tokens = getattr(app, "theme_tokens", {}) if app else {}
    return tokens.get(name, fallback)


def open_pdf_with_system_default(pdf_path, error_callback=None):
    if not os.path.exists(pdf_path):
        if error_callback:
            error_callback(f"Arquivo não encontrado:\n{pdf_path}")
        return False

    try:
        absolute_path = os.path.abspath(pdf_path)
        system = platform.system()

        if system == "Windows":
            os.startfile(absolute_path)
        elif system == "Darwin":
            subprocess.Popen(["open", absolute_path])
        else:
            subprocess.Popen(["xdg-open", absolute_path])
        return True
    except Exception as e:
        if error_callback:
            error_callback(f"Erro ao abrir PDF no aplicativo padrão:\n{str(e)}")
        return False


import time
from collections import OrderedDict
from threading import RLock
from kivy.uix.widget import Widget
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.textinput import TextInput
from kivy.graphics import Ellipse, Line, Rectangle, InstructionGroup


def _draw_glyph(kind, cx, cy, u, lw):
    """Desenha um ícone vetorial (chamar dentro de `with canvas`)."""
    def L(*pts):
        Line(points=list(pts), width=lw, cap='round', joint='round')

    if kind == "view":
        Line(bezier=[cx - 12*u, cy, cx - 6*u, cy + 12*u,
                     cx + 6*u, cy + 12*u, cx + 12*u, cy],
             width=lw, bezier_precision=40)
        Line(bezier=[cx - 12*u, cy, cx - 6*u, cy - 12*u,
                     cx + 6*u, cy - 12*u, cx + 12*u, cy],
             width=lw, bezier_precision=40)
        Ellipse(pos=(cx - 4*u, cy - 4*u), size=(8*u, 8*u))
    elif kind == "external":
        L(cx + 2*u, cy + 10*u, cx - 10*u, cy + 10*u, cx - 10*u, cy - 10*u,
          cx + 10*u, cy - 10*u, cx + 10*u, cy - 2*u)
        L(cx - 1*u, cy - 1*u, cx + 11*u, cy + 11*u)
        L(cx + 3*u, cy + 11*u, cx + 11*u, cy + 11*u, cx + 11*u, cy + 3*u)
    elif kind == "print":
        Line(rounded_rectangle=(cx - 12*u, cy - 6*u, 24*u, 12*u, 3*u), width=lw)
        Line(rectangle=(cx - 6*u, cy + 6*u, 12*u, 8*u), width=lw)
        Line(rectangle=(cx - 6*u, cy - 13*u, 12*u, 11*u), width=lw)
    elif kind == "prev":
        L(cx + 3*u, cy + 10*u, cx - 5*u, cy, cx + 3*u, cy - 10*u)
    elif kind == "next":
        L(cx - 3*u, cy + 10*u, cx + 5*u, cy, cx - 3*u, cy - 10*u)
    elif kind == "up":
        L(cx - 9*u, cy - 4*u, cx, cy + 5*u, cx + 9*u, cy - 4*u)
    elif kind == "down":
        L(cx - 9*u, cy + 4*u, cx, cy - 5*u, cx + 9*u, cy + 4*u)
    elif kind == "minus":
        L(cx - 9*u, cy, cx + 9*u, cy)
    elif kind == "plus":
        L(cx - 9*u, cy, cx + 9*u, cy)
        L(cx, cy - 9*u, cx, cy + 9*u)
    elif kind == "fitw":
        L(cx - 11*u, cy, cx + 11*u, cy)
        L(cx - 6*u, cy + 5*u, cx - 11*u, cy, cx - 6*u, cy - 5*u)
        L(cx + 6*u, cy + 5*u, cx + 11*u, cy, cx + 6*u, cy - 5*u)
        L(cx - 14*u, cy + 10*u, cx - 14*u, cy - 10*u)
        L(cx + 14*u, cy + 10*u, cx + 14*u, cy - 10*u)
    elif kind == "fitp":
        Line(rounded_rectangle=(cx - 8*u, cy - 11*u, 16*u, 22*u, 2*u), width=lw)
        L(cx - 4*u, cy + 4*u, cx + 4*u, cy + 4*u)
        L(cx - 4*u, cy - 2*u, cx + 4*u, cy - 2*u)
    elif kind == "search":
        Line(circle=(cx - 2*u, cy + 2*u, 8*u), width=lw)
        L(cx + 4*u, cy - 4*u, cx + 11*u, cy - 11*u)
    elif kind == "thumbs":
        Line(rounded_rectangle=(cx - 11*u, cy - 10*u, 22*u, 20*u, 2*u), width=lw)
        L(cx - 4*u, cy + 10*u, cx - 4*u, cy - 10*u)
    elif kind == "rotate":
        Line(circle=(cx, cy, 9*u, 30, 320), width=lw)
        L(cx - 6*u, cy + 13*u, cx - 5.8*u, cy + 6.9*u, cx - 12*u, cy + 7.5*u)
    elif kind == "close":
        L(cx - 8*u, cy + 8*u, cx + 8*u, cy - 8*u)
        L(cx - 8*u, cy - 8*u, cx + 8*u, cy + 8*u)


class GlyphIcon(Widget):
    """Ícone vetorial em círculo, com estados hover/pressionado/ativo/inativo."""

    def __init__(self, kind, color, bg, callback=None, hover_bg=None, **kwargs):
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (dp(40), dp(40)))
        super().__init__(**kwargs)
        self.kind = kind
        self.color = tuple(color)
        self.bg = tuple(bg)
        self.hover_bg = tuple(hover_bg) if hover_bg else self.bg
        self.callback = callback
        self.hovered = False
        self.pressed = False
        self.active = False
        self.inactive = False
        self.bind(pos=self._redraw, size=self._redraw)
        self._redraw()

    def set_hover(self, value):
        if value != self.hovered:
            self.hovered = value
            self._redraw()

    def set_active(self, value):
        if value != self.active:
            self.active = value
            self._redraw()

    def set_inactive(self, value):
        if value != self.inactive:
            self.inactive = value
            self._redraw()

    def _redraw(self, *_):
        self.canvas.clear()
        cx, cy = self.center_x, self.center_y
        u = min(self.width, self.height) / 48.0
        lw = max(1.3, 2.1 * u)
        bg = self.bg
        if not self.inactive and self.callback:
            h = self.hover_bg
            if self.pressed:
                bg = (h[0], h[1], h[2], min(1, h[3] * 1.9))
            elif self.hovered or self.active:
                bg = h
        fg = self.color
        if self.inactive:
            fg = (fg[0], fg[1], fg[2], fg[3] * 0.3)
        with self.canvas:
            Color(*bg)
            Ellipse(pos=self.pos, size=self.size)
            Color(*fg)
            _draw_glyph(self.kind, cx, cy, u, lw)

    def on_touch_down(self, touch):
        if self.callback and not self.inactive and self.collide_point(*touch.pos):
            touch.grab(self)
            self.pressed = True
            self._redraw()
            return True
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            self.pressed = False
            self._redraw()
            if self.collide_point(*touch.pos) and self.callback:
                self.callback()
            return True
        return super().on_touch_up(touch)


class _Separator(Widget):
    def __init__(self, **kwargs):
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (dp(1), dp(24)))
        kwargs.setdefault("pos_hint", {"center_y": 0.5})
        super().__init__(**kwargs)
        with self.canvas:
            Color(0.5, 0.55, 0.6, 0.35)
            self._rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *_):
        self._rect.pos = self.pos
        self._rect.size = self.size


class PageThumb(Widget):
    """Miniatura de página com moldura de seleção."""

    def __init__(self, index, callback, accent, **kwargs):
        kwargs.setdefault("size_hint", (None, None))
        super().__init__(**kwargs)
        self.index = index
        self.callback = callback
        self.accent = tuple(accent)
        self.texture = None
        self.selected = False
        self.bind(pos=self._redraw, size=self._redraw)
        self._redraw()

    def set_texture(self, tex):
        self.texture = tex
        self._redraw()

    def set_selected(self, value):
        if value != self.selected:
            self.selected = value
            self._redraw()

    def _redraw(self, *_):
        self.canvas.clear()
        x, y = self.pos
        w, h = self.size
        with self.canvas:
            if self.selected:
                Color(*self.accent)
                RoundedRectangle(pos=(x - dp(3), y - dp(3)),
                                 size=(w + dp(6), h + dp(6)), radius=[dp(5)])
            Color(0, 0, 0, 0.25)
            Rectangle(pos=(x + dp(1), y - dp(1)), size=(w, h))
            Color(1, 1, 1, 1)
            Rectangle(pos=self.pos, size=self.size)
            if self.texture is not None:
                Rectangle(texture=self.texture, pos=self.pos, size=self.size)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and not getattr(touch, "is_mouse_scrolling", False):
            touch.grab(self)
            return True
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            if self.collide_point(*touch.pos) and self.callback:
                self.callback(self.index)
            return True
        return super().on_touch_up(touch)


class PDFScrollView(ScrollView):
    """ScrollView com Ctrl+roda = zoom e roda na borda = trocar de página."""

    def __init__(self, ctrl_cb=None, edge_cb=None, dbl_cb=None, **kwargs):
        super().__init__(**kwargs)
        self.ctrl_cb = ctrl_cb
        self.edge_cb = edge_cb
        self.dbl_cb = dbl_cb
        self._last_wheel = 0.0
        self._burst_edge = False

    def _at_edge(self, direction):
        if not self.children:
            return False
        if self.children[0].height <= self.height + 1:
            return True
        if direction < 0:                  # roda para baixo
            return self.scroll_y <= 0.001
        return self.scroll_y >= 0.999      # roda para cima

    def on_touch_down(self, touch):
        if (self.dbl_cb and getattr(touch, "is_double_tap", False)
                and self.collide_point(*touch.pos)
                and not getattr(touch, "is_mouse_scrolling", False)):
            self.dbl_cb()
            return True
        if self.collide_point(*touch.pos) and getattr(touch, "is_mouse_scrolling", False):
            direction = {"scrollup": 1, "scrolldown": -1}.get(touch.button, 0)
            if WHEEL_INVERT:
                direction = -direction
            if direction:
                if self.ctrl_cb and self.ctrl_cb(direction):
                    return True
                # Uma "rajada" é uma sequência contínua de giros da roda.
                # Só troca de página se a rajada começou já na borda da página
                # (assim, rolar até o fim de uma página grande não a troca
                # sem querer; é preciso um novo giro).
                now = time.monotonic()
                new_burst = (now - self._last_wheel) > 0.3
                self._last_wheel = now
                at_edge = self._at_edge(direction)
                if new_burst:
                    self._burst_edge = at_edge
                if (self.edge_cb and at_edge and self._burst_edge
                        and self.edge_cb(direction)):
                    return True
        return super().on_touch_down(touch)


class PDFViewer:
    """
    Visualizador de PDFs com popup de opções redesenhado, navegação por
    teclado e renderização assíncrona.
    """

    def __init__(self, error_callback=None):
        self.error_callback = error_callback
        self.current_popup = None
        self.pdf_document = None
        self.page_state = {'current': 0, 'zoom': 1.0, 'fit': 'page'}
        self.pdf_image = None
        self.pdf_container = None
        self.page_label = None
        self.options_dialog = None
        self.pymupdf_dialog = None
        self.install_dialog = None
        self._installing_pymupdf = False
        self._pdf_path = None
        self._pdf_total_pages = 0
        self._document_open_token = 0
        self._render_token = 0
        self._page_texture = None
        self._page_texture_size = None
        self._key_bound = False
        self.last_print_message = ""
        # --- visualizador interno ---
        self._doc = None
        self._doc_lock = RLock()
        self._render_cache = OrderedDict()
        self._scroll = None
        self._stage = None
        self._page_widget = None
        self._hl_group = None
        self._tools = {}
        self._tool_list = []
        self._page_input = None
        self._total_label = None
        self._zoom_label = None
        self._status_label = None
        self._search_bar = None
        self._search_input = None
        self._search_count = None
        self._search_visible = False
        self._search_hits = []
        self._search_index = -1
        self._search_query = ""
        self._search_token = 0
        self._scroll_hit_pending = False
        self._pending_scroll = None
        self._disp_scale = 1.0
        self._ctrl_down = False
        self._last_flip = 0.0
        self._tex_rect = None
        self._hit_matrix = None
        self._thumb_panel = None
        self._thumb_scroll = None
        self._thumb_box = None
        self._thumb_items = []
        self._thumb_sel = -1
        self._thumbs_visible = False
        self._thumb_token = 0
        self._prefetching = False
        self._init_tries = 0

    # ------------------------------------------------------------------
    # Entrada
    # ------------------------------------------------------------------
    def view_pdf(self, pdf_path, prefer_direct=False):
        if not os.path.exists(pdf_path):
            if self.error_callback:
                self.error_callback(f'Arquivo não encontrado:\n{pdf_path}')
            return

        if prefer_direct and self._open_preferred_viewer(pdf_path):
            return

        self._show_viewer_options(pdf_path)

    def _open_preferred_viewer(self, pdf_path):
        if not self._has_pymupdf():
            return self._open_in_browser(pdf_path)

        self._view_internal(pdf_path)
        return True

    def _has_pymupdf(self):
        try:
            return importlib.util.find_spec("fitz") is not None
        except Exception:
            return False

    def _can_install_pymupdf(self):
        return (not getattr(sys, "frozen", False)) and bool(getattr(sys, "executable", None))

    # ------------------------------------------------------------------
    # Impressão
    # ------------------------------------------------------------------
    @staticmethod
    def _windows_has_pdf_print_handler():
        """Return whether Windows exposes a print action for PDF files."""
        try:
            import winreg

            file_class = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, ".pdf")
            if not file_class:
                return False
            print_key = rf"{file_class}\shell\print\command"
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, print_key) as key:
                command, _value_type = winreg.QueryValueEx(key, "")
                return bool(command)
        except (ImportError, OSError):
            return False

    def print_pdf(self, pdf_path):
        self.last_print_message = ""
        if not os.path.exists(pdf_path):
            self.last_print_message = "O PDF já não está disponível. Gere-o novamente."
            if self.error_callback:
                self.error_callback(self.last_print_message)
            return False

        system = platform.system()
        try:
            absolute_path = os.path.abspath(pdf_path)

            if system == 'Windows':
                if not self._windows_has_pdf_print_handler():
                    self.last_print_message = (
                        "A impressão automática não está configurada neste computador."
                    )
                    return False
                os.startfile(absolute_path, 'print')
            elif shutil.which('lp'):
                # macOS e Linux: envia direto para a impressora padrão.
                subprocess.Popen(['lp', absolute_path])
            elif system == 'Darwin':
                subprocess.Popen(['open', absolute_path])
            else:
                subprocess.Popen(['xdg-open', absolute_path])
            return True
        except OSError as exc:
            if system == 'Windows' and getattr(exc, 'winerror', None) == 1155:
                self.last_print_message = (
                    "A impressão automática não está configurada neste computador."
                )
            else:
                self.last_print_message = "Não foi possível enviar o PDF para impressão."
            return False
        except Exception:
            self.last_print_message = "Não foi possível enviar o PDF para impressão."
            return False

    def _print_from_ui(self, pdf_path):
        """Imprime e mostra o motivo caso falhe (antes o erro era silencioso)."""
        if not self.print_pdf(pdf_path) and self.last_print_message and self.error_callback:
            if "já não está disponível" not in self.last_print_message:
                self.error_callback(self.last_print_message)

    # ------------------------------------------------------------------
    # Popup de opções (redesenhado)
    # ------------------------------------------------------------------
    @staticmethod
    def _lighten(color, amount=0.06):
        r, g, b, a = (tuple(color) + (1,))[:4]
        return (min(1, r + amount), min(1, g + amount), min(1, b + amount), a)

    def _make_option_card(self, icon, title, description, callback,
                          primary=False, badge=None):
        """Cartão compacto: ícone em círculo + título + descrição curta."""
        base = _theme_color('primary', (0.15, 0.52, 0.76, 1))
        if primary:
            bg = base
            fg = _theme_color('on_primary', (1, 1, 1, 1))
            fg_soft = (fg[0], fg[1], fg[2], 0.85)
            icon_bg = (1, 1, 1, 0.22)
            icon_fg = fg
        else:
            bg = _theme_color('card_alt', (0.17, 0.21, 0.27, 1))
            fg = _theme_color('text_primary', (0.93, 0.95, 0.97, 1))
            fg_soft = _theme_color('text_secondary', (0.66, 0.70, 0.75, 1))
            icon_bg = (base[0], base[1], base[2], 0.22)
            icon_fg = (min(1, base[0] + 0.25), min(1, base[1] + 0.25),
                       min(1, base[2] + 0.25), 1)

        card = MDCard(
            orientation="vertical",
            padding=[dp(14), dp(12), dp(14), dp(10)],
            spacing=dp(6),
            radius=[dp(14)],
            elevation=3 if primary else 1,
            md_bg_color=bg,
        )
        card._base_bg = bg
        card._hover_bg = self._lighten(bg, 0.07)

        top = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40))
        top.add_widget(GlyphIcon(icon, icon_fg, icon_bg))
        top.add_widget(MDBoxLayout())  # espaçador
        if badge:
            chip = MDLabel(
                text=badge,
                font_style="Caption",
                bold=True,
                halign="right",
                valign="top",
                theme_text_color="Custom",
                text_color=fg_soft,
                size_hint=(None, 1),
                width=dp(80),
            )
            # sem text_size => sem quebra de linha; largura segue o texto
            chip.bind(texture_size=lambda inst, ts: setattr(inst, "width", ts[0] + dp(4)))
            top.add_widget(chip)
        card.add_widget(top)

        title_label = MDLabel(
            text=title,
            font_style="Subtitle2",
            bold=True,
            halign="left",
            valign="middle",
            theme_text_color="Custom",
            text_color=fg,
            size_hint_y=None,
            height=dp(22),
        )
        title_label.bind(size=lambda inst, _: setattr(inst, "text_size", inst.size))
        card.add_widget(title_label)

        desc_label = MDLabel(
            text=description,
            font_style="Caption",
            halign="left",
            valign="top",
            theme_text_color="Custom",
            text_color=fg_soft,
        )
        desc_label.bind(size=lambda inst, _: setattr(inst, "text_size", (inst.width, None)))
        card.add_widget(desc_label)

        def on_touch_up(instance, touch):
            if getattr(touch, "is_mouse_scrolling", False):
                return False
            if instance.collide_point(*touch.pos) and touch.grab_current is None:
                callback()
                return True
            return False

        card.bind(on_touch_up=on_touch_up)
        return card

    def _on_option_hover(self, _window, pos):
        if not self.options_dialog:
            Window.unbind(mouse_pos=self._on_option_hover)
            return
        for card in getattr(self, "_option_cards", []):
            hovered = card.collide_point(*pos)
            card.md_bg_color = card._hover_bg if hovered else card._base_bg

    def _close_options(self):
        try:
            Window.unbind(mouse_pos=self._on_option_hover)
        except Exception:
            pass
        self._option_cards = []
        if self.options_dialog:
            self.options_dialog.dismiss()
            self.options_dialog = None

    def _run_option(self, action, pdf_path):
        """Fecha o popup primeiro e só então executa a ação escolhida."""
        self._close_options()
        Clock.schedule_once(lambda _dt: action(pdf_path), 0.05)

    def _show_viewer_options(self, pdf_path):
        """Popup horizontal com cartões de ação (empilha em telas estreitas)."""
        self._close_options()

        filename = os.path.basename(pdf_path)
        try:
            size_kb = os.path.getsize(pdf_path) / 1024
            size_text = f"{size_kb / 1024:.1f} MB" if size_kb >= 1024 else f"{size_kb:.0f} KB"
        except OSError:
            size_text = ""

        narrow = Window.width < dp(620)
        primary_color = _theme_color('primary', (0.15, 0.52, 0.76, 1))

        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(12),
            padding=[dp(18), dp(6), dp(18), dp(6)],
            size_hint_y=None,
        )
        content.bind(minimum_height=content.setter("height"))

        # Cabeçalho do arquivo: ícone + nome + metadados
        file_row = MDCard(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(56),
            padding=[dp(12), dp(6)],
            spacing=dp(10),
            radius=[dp(12)],
            elevation=0,
            md_bg_color=_theme_color('surface_alt', (0.12, 0.15, 0.20, 1)),
        )
        file_row.add_widget(MDIconButton(
            icon="file-pdf-box",
            theme_text_color="Custom",
            text_color=_theme_color('error', (0.90, 0.30, 0.30, 1)),
            md_bg_color=(0, 0, 0, 0),
            size_hint=(None, None),
            size=(dp(40), dp(40)),
            pos_hint={"center_y": 0.5},
        ))
        file_info = MDBoxLayout(orientation="vertical", spacing=dp(2))
        name_label = MDLabel(
            text=filename,
            font_style="Subtitle1",
            bold=True,
            halign="left",
            valign="bottom",
            theme_text_color="Custom",
            text_color=_theme_color('text_primary', (0.93, 0.95, 0.97, 1)),
            shorten=True,
            shorten_from="center",
        )
        name_label.bind(size=lambda inst, _: setattr(inst, "text_size", inst.size))
        meta_label = MDLabel(
            text="Documento PDF" + (f"  •  {size_text}" if size_text else ""),
            font_style="Caption",
            halign="left",
            valign="top",
            theme_text_color="Custom",
            text_color=_theme_color('text_secondary', (0.66, 0.70, 0.75, 1)),
        )
        meta_label.bind(size=lambda inst, _: setattr(inst, "text_size", inst.size))
        file_info.add_widget(name_label)
        file_info.add_widget(meta_label)
        file_row.add_widget(file_info)
        content.add_widget(file_row)

        # Pergunta
        question = MDLabel(
            text="Como deseja visualizar o PDF?",
            font_style="Body1",
            halign="left",
            valign="middle",
            theme_text_color="Custom",
            text_color=_theme_color('text_secondary', (0.66, 0.70, 0.75, 1)),
            size_hint_y=None,
            height=dp(22),
        )
        question.bind(size=lambda inst, _: setattr(inst, "text_size", inst.size))
        content.add_widget(question)

        # Cartões de ação
        cards_box = MDBoxLayout(
            orientation="vertical" if narrow else "horizontal",
            spacing=dp(10),
            size_hint_y=None,
            height=dp(3 * 100 + 2 * 10) if narrow else dp(124),
        )
        self._option_cards = [
            self._make_option_card(
                "view",
                "Visualizador interno",
                "Abre aqui, com zoom e atalhos de teclado.",
                lambda: self._run_option(self._view_internal, pdf_path),
                primary=True,
                badge="Recomendado",
            ),
            self._make_option_card(
                "external",
                "Aplicativo padrão",
                "Usa o leitor de PDF do computador.",
                lambda: self._run_option(self._open_in_browser, pdf_path),
            ),
            self._make_option_card(
                "print",
                "Imprimir agora",
                "Envia para a impressora padrão.",
                lambda: self._run_option(self._print_from_ui, pdf_path),
            ),
        ]
        for card in self._option_cards:
            cards_box.add_widget(card)
        content.add_widget(cards_box)

        dialog_width = min(dp(680), Window.width * 0.94)
        dialog_height = min(
            dp(520) if narrow else dp(370),
            Window.height * 0.94,
        )
        self.options_dialog = MDDialog(
            title="Visualizar PDF",
            type="custom",
            content_cls=content,
            size_hint=(None, None),
            size=(dialog_width, dialog_height),
            buttons=[
                MDFlatButton(
                    text="Cancelar",
                    on_release=lambda *_: self._close_options(),
                ),
            ],
        )
        self.options_dialog.open()
        Window.bind(mouse_pos=self._on_option_hover)

    def _open_in_browser(self, pdf_path):
        """Abre o PDF no aplicativo/navegador padrão do sistema."""
        return open_pdf_with_system_default(pdf_path, self.error_callback)

    # ------------------------------------------------------------------
    # Janela do visualizador interno
    # ------------------------------------------------------------------
    def _viewer_dark(self):
        c = _theme_color('card', (0.1, 0.12, 0.15, 1))
        return (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) < 0.5

    def _input_style(self):
        text = _theme_color('text_primary', (0.93, 0.95, 0.97, 1))
        sec = _theme_color('text_secondary', (0.66, 0.70, 0.75, 1))
        primary = _theme_color('primary', (0.15, 0.52, 0.76, 1))
        return dict(
            background_normal='', background_active='',
            background_color=_theme_color('card', (0.1, 0.12, 0.15, 1)),
            foreground_color=text, cursor_color=primary,
            hint_text_color=(sec[0], sec[1], sec[2], 0.7),
            selection_color=(primary[0], primary[1], primary[2], 0.4),
            padding=[dp(10), dp(8), dp(10), dp(6)],
            font_size=dp(15), multiline=False, write_tab=False,
        )

    def _tool(self, kind, callback, name=None, size=38):
        fg = _theme_color('text_primary', (0.93, 0.95, 0.97, 1))
        primary = _theme_color('primary', (0.15, 0.52, 0.76, 1))
        icon = GlyphIcon(
            kind, fg, (0, 0, 0, 0), callback=callback,
            hover_bg=(primary[0], primary[1], primary[2], 0.24),
            size=(dp(size), dp(size)), pos_hint={"center_y": 0.5},
        )
        self._tool_list.append(icon)
        if name:
            self._tools[name] = icon
        return icon

    def _small_label(self, text, width=None, halign='left', bold=False):
        lbl = MDLabel(
            text=text, font_style='Caption', bold=bold, halign=halign,
            valign='middle', theme_text_color='Custom',
            text_color=_theme_color('text_secondary', (0.66, 0.70, 0.75, 1)),
        )
        if width:
            lbl.size_hint_x = None
            lbl.width = width
        lbl.bind(size=lambda inst, _: setattr(inst, 'text_size', inst.size))
        return lbl

    def _create_pdf_viewer_window(self, pdf_path, total_pages):
        popup = Popup(
            title='', separator_height=0, size_hint=(0.97, 0.97),
            background='', background_color=(0, 0, 0, 0.35), auto_dismiss=False,
        )
        self.current_popup = popup
        self._tools = {}
        self._tool_list = []
        self._search_hits = []
        self._search_index = -1
        self._search_query = ""
        self._search_visible = False
        self._init_tries = 0
        self._prefetching = False

        primary = _theme_color('primary', (0.15, 0.52, 0.76, 1))
        on_primary = _theme_color('on_primary', (1, 1, 1, 1))

        main_layout = MDBoxLayout(orientation='vertical', padding=[dp(8), dp(8)])
        container = MDCard(
            orientation='vertical', spacing=0, padding=[0, 0], elevation=4,
            radius=[dp(14)], md_bg_color=_theme_color('card', (1, 1, 1, 1)),
        )

        header = MDCard(
            orientation='horizontal', size_hint_y=None, height=dp(48),
            padding=[dp(16), 0, dp(8), 0], spacing=dp(8),
            radius=[dp(14), dp(14), 0, 0], elevation=0, md_bg_color=primary,
        )
        title = MDLabel(
            text=os.path.basename(pdf_path), font_style='Subtitle1', bold=True,
            halign='left', valign='middle', theme_text_color='Custom',
            text_color=on_primary, shorten=True, shorten_from='center',
        )
        title.bind(size=lambda inst, _: setattr(inst, 'text_size', inst.size))
        close_icon = GlyphIcon(
            'close', on_primary, (0, 0, 0, 0),
            callback=lambda: self._close_viewer(popup),
            hover_bg=(1, 1, 1, 0.20), size=(dp(36), dp(36)),
            pos_hint={'center_y': 0.5},
        )
        self._tool_list.append(close_icon)
        header.add_widget(title)
        header.add_widget(close_icon)

        body = MDBoxLayout(orientation='vertical', spacing=dp(8),
                           padding=[dp(10), dp(10), dp(10), dp(10)])
        body.add_widget(self._create_controls(pdf_path))
        body.add_widget(self._create_search_bar())
        row = MDBoxLayout(orientation='horizontal', spacing=dp(8))
        row.add_widget(self._create_thumb_panel())
        row.add_widget(self._create_pdf_display_area())
        body.add_widget(row)

        container.add_widget(header)
        container.add_widget(body)
        main_layout.add_widget(container)
        popup.content = main_layout
        popup.open()

        Window.bind(mouse_pos=self._on_viewer_hover,
                    on_key_down=self._on_key_down,
                    on_key_up=self._on_key_up)
        self._key_bound = True
        self._update_toolbar_state()
        Clock.schedule_once(self._initial_render, 0.15)
        Clock.schedule_once(lambda _dt: self._build_thumbnails(), 0.4)

    def _initial_render(self, _dt):
        if not self._pdf_path or not self._scroll:
            return
        self._init_tries += 1
        if self._scroll.width < dp(200) and self._init_tries < 15:
            Clock.schedule_once(self._initial_render, 0.1)
            return
        self._render_current(scroll_to=(0.5, 1))

    def _create_controls(self, pdf_path):
        controls = MDCard(
            orientation='horizontal', size_hint_y=None, height=dp(52),
            padding=[dp(10), dp(6)], spacing=dp(4), elevation=1,
            radius=[dp(10)],
            md_bg_color=_theme_color('surface_alt', (0.97, 0.97, 0.97, 1)),
        )

        controls.add_widget(self._tool('thumbs', lambda: self._toggle_thumbs(
            not self._thumbs_visible), 'thumbs'))
        controls.add_widget(_Separator())
        controls.add_widget(self._tool('prev', lambda: self._nav_page(-1), 'prev'))

        self._page_input = TextInput(
            text='1', size_hint=(None, None), size=(dp(52), dp(34)),
            pos_hint={'center_y': 0.5}, halign='center', input_filter='int',
            **self._input_style())
        self._page_input.bind(on_text_validate=self._on_page_input_validate,
                              focus=self._on_page_input_focus)
        controls.add_widget(self._page_input)

        self._total_label = self._small_label('/ 1', width=dp(54))
        controls.add_widget(self._total_label)
        controls.add_widget(self._tool('next', lambda: self._nav_page(1), 'next'))
        controls.add_widget(_Separator())

        controls.add_widget(self._tool('minus', lambda: self._zoom_step(-1), 'minus'))
        self._zoom_label = self._small_label('100%', width=dp(54),
                                             halign='center', bold=True)
        controls.add_widget(self._zoom_label)
        controls.add_widget(self._tool('plus', lambda: self._zoom_step(1), 'plus'))
        controls.add_widget(_Separator())

        controls.add_widget(self._tool('fitw', lambda: self._fit('width'), 'fitw'))
        controls.add_widget(self._tool('fitp', lambda: self._fit('page'), 'fitp'))
        controls.add_widget(self._tool('rotate', self._rotate, 'rotate'))

        self._status_label = self._small_label('', halign='right')
        controls.add_widget(self._status_label)

        controls.add_widget(self._tool('search', lambda: self._toggle_search(
            not self._search_visible), 'search'))
        controls.add_widget(self._tool('print', lambda: self._print_from_ui(pdf_path)))
        controls.add_widget(self._tool('external', lambda: self._open_in_browser(pdf_path)))
        return controls

    def _create_search_bar(self):
        bar = MDCard(
            orientation='horizontal', size_hint_y=None, height=0, opacity=0,
            disabled=True, padding=[dp(10), dp(5)], spacing=dp(6),
            radius=[dp(10)], elevation=0,
            md_bg_color=_theme_color('surface_alt', (0.97, 0.97, 0.97, 1)),
        )
        self._search_input = TextInput(
            hint_text='Pesquisar no documento…', size_hint=(1, None),
            height=dp(34), pos_hint={'center_y': 0.5}, **self._input_style())
        self._search_input.bind(on_text_validate=self._on_search_validate)
        self._search_count = self._small_label('', width=dp(120), halign='center')
        bar.add_widget(self._search_input)
        bar.add_widget(self._search_count)
        bar.add_widget(self._tool('up', lambda: self._step_hit(-1), size=34))
        bar.add_widget(self._tool('down', lambda: self._step_hit(1), size=34))
        bar.add_widget(self._tool('close', lambda: self._toggle_search(False), size=34))
        self._search_bar = bar
        return bar

    def _create_pdf_display_area(self):
        dark = self._viewer_dark()
        backdrop = (0.09, 0.10, 0.12, 1) if dark else (0.82, 0.83, 0.85, 1)
        primary = _theme_color('primary', (0.15, 0.52, 0.76, 1))

        scroll = PDFScrollView(
            ctrl_cb=self._on_ctrl_wheel, edge_cb=self._on_edge_wheel,
            dbl_cb=self._on_double_tap,
            size_hint=(1, 1), do_scroll_x=True, do_scroll_y=True,
            bar_width=dp(10), bar_color=[primary[0], primary[1], primary[2], 0.85],
            bar_inactive_color=[0.6, 0.6, 0.6, 0.35],
            scroll_type=['bars', 'content'],
        )
        with scroll.canvas.before:
            Color(*backdrop)
            bg = Rectangle(pos=scroll.pos, size=scroll.size)

        def upd_bg(*_):
            bg.pos = scroll.pos
            bg.size = scroll.size
        scroll.bind(pos=upd_bg, size=upd_bg)

        # Widgets simples: sem layouts aninhados; tudo é desenhado no canvas
        # da página e a página é centrada manualmente no "stage".
        stage = Widget(size_hint=(None, None), size=(dp(100), dp(100)))
        page = Widget(size_hint=(None, None), size=(dp(10), dp(10)))
        shadows = []
        with page.canvas.before:
            for grow, alpha in ((10, 0.04), (6, 0.06), (3, 0.09), (1, 0.12)):
                Color(0, 0, 0, alpha)
                shadows.append((grow, RoundedRectangle(
                    pos=page.pos, size=page.size, radius=[dp(4)])))
            Color(1, 1, 1, 1)
            paper = Rectangle(pos=page.pos, size=page.size)
        with page.canvas:
            Color(1, 1, 1, 1)
            self._tex_rect = Rectangle(pos=page.pos, size=page.size)

        def upd_page(*_):
            for grow, rect in shadows:
                g = dp(grow)
                rect.pos = (page.x - g, page.y - g - dp(2))
                rect.size = (page.width + 2 * g, page.height + 2 * g)
            paper.pos = page.pos
            paper.size = page.size
            if self._tex_rect is not None:
                self._tex_rect.pos = page.pos
                self._tex_rect.size = page.size
            self._draw_highlights()
        page.bind(pos=upd_page, size=upd_page)

        self._hl_group = InstructionGroup()
        page.canvas.after.add(self._hl_group)

        stage.add_widget(page)
        scroll.add_widget(stage)
        stage.bind(pos=self._place_page, size=self._place_page)
        scroll.bind(size=self._on_viewport_size)

        self._scroll = scroll
        self._stage = stage
        self._page_widget = page
        self.pdf_image = page          # compatibilidade
        self.pdf_container = stage
        return scroll

    # ------------------------------------------------------------------
    # Estado visual da barra de ferramentas
    # ------------------------------------------------------------------
    def _set_status(self, text):
        if self._status_label:
            self._status_label.text = text

    def _sync_page_input(self):
        if self._page_input and not self._page_input.focus:
            self._page_input.text = str(int(self.page_state.get('current', 0)) + 1)

    def _update_toolbar_state(self):
        t = self._tools
        if not t:
            return
        cur = int(self.page_state.get('current', 0))
        total = int(self._pdf_total_pages or 0)
        zoom = float(self.page_state.get('zoom', 1.0))
        fit = self.page_state.get('fit')
        if 'prev' in t:
            t['prev'].set_inactive(cur <= 0)
            t['next'].set_inactive(cur >= total - 1)
            t['minus'].set_inactive(zoom <= ZOOM_MIN + 0.001)
            t['plus'].set_inactive(zoom >= ZOOM_MAX - 0.001)
            t['fitw'].set_active(fit == 'width')
            t['fitp'].set_active(fit == 'page')
            t['search'].set_active(self._search_visible)
            t['thumbs'].set_active(self._thumbs_visible)
            t['thumbs'].set_inactive(total <= 1)
        if self._zoom_label:
            self._zoom_label.text = f"{int(round(zoom * 100))}%"
        if self._total_label:
            self._total_label.text = f"/ {total}"
        self._sync_page_input()
        self._sync_thumbs()

    def _on_page_input_focus(self, inst, focused):
        if focused:
            Clock.schedule_once(lambda _dt: inst.select_all(), 0)
        else:
            self._sync_page_input()

    def _on_page_input_validate(self, inst):
        try:
            number = int(inst.text)
        except (TypeError, ValueError):
            self._sync_page_input()
            return
        inst.focus = False
        self._go_to_page(number - 1)

    def _on_viewer_hover(self, _window, pos):
        if not self.current_popup:
            return
        for icon in self._tool_list:
            icon.set_hover(icon.collide_point(*pos))

    # ------------------------------------------------------------------
    # Atalhos de teclado
    # ------------------------------------------------------------------
    def _on_key_up(self, _window, key, *_args):
        if key in (305, 306, 309, 310):
            self._ctrl_down = False
        return False

    def _on_key_down(self, _window, key, _scancode, _codepoint, modifiers):
        if not self.current_popup:
            return False
        if key in (305, 306, 309, 310):
            self._ctrl_down = True
            return False
        ctrl = 'ctrl' in modifiers or 'meta' in modifiers
        self._ctrl_down = ctrl
        typing = bool((self._page_input and self._page_input.focus) or
                      (self._search_input and self._search_input.focus))

        if key == 27:  # Esc
            if self._search_visible:
                self._toggle_search(False)
            elif typing:
                self._page_input.focus = False
            else:
                self._close_viewer(self.current_popup)
            return True
        if key == 284:  # F3 / Shift+F3
            self._step_hit(-1 if 'shift' in modifiers else 1)
            return True
        if ctrl:
            if key == 102:                    # Ctrl+F
                self._toggle_search(True)
            elif key == 112 and self._pdf_path:  # Ctrl+P
                self._print_from_ui(self._pdf_path)
            elif key == 103 and self._page_input:  # Ctrl+G
                self._page_input.focus = True
            elif key in (43, 61, 270):
                self._zoom_step(1)
            elif key in (45, 269):
                self._zoom_step(-1)
            elif key == 48:
                self._fit('page')
            else:
                return False
            return True
        if typing:
            return False

        total = int(self._pdf_total_pages or 0)
        if key in (275, 281):        # → / PageDown
            self._nav_page(1)
        elif key in (276, 280):      # ← / PageUp
            self._nav_page(-1)
        elif key == 278:             # Home
            self._go_to_page(0)
        elif key == 279:             # End
            self._go_to_page(total - 1)
        elif key in (43, 61, 270):
            self._zoom_step(1)
        elif key in (45, 269):
            self._zoom_step(-1)
        elif key == 48:
            self._fit('page')
        elif key == 119:             # w
            self._fit('width')
        elif key == 114:             # r
            self._rotate()
        elif key == 116:             # t
            self._toggle_thumbs(not self._thumbs_visible)
        else:
            return False
        return True

    # ------------------------------------------------------------------
    # Roda do rato
    # ------------------------------------------------------------------
    def _on_ctrl_wheel(self, direction):
        if not self._ctrl_down:
            return False
        self._zoom_step(direction)
        return True

    def _on_edge_wheel(self, direction):
        now = time.monotonic()
        cur = int(self.page_state.get('current', 0))
        total = int(self._pdf_total_pages or 0)
        sx = self._scroll.scroll_x if self._scroll else 0.5
        if direction < 0 and cur < total - 1:
            if now - self._last_flip > 0.2:
                self._last_flip = now
                self._go_to_page(cur + 1, scroll_to=(sx, 1))
            return True
        if direction > 0 and cur > 0:
            if now - self._last_flip > 0.2:
                self._last_flip = now
                self._go_to_page(cur - 1, scroll_to=(sx, 0))
            return True
        return False

    # ------------------------------------------------------------------
    # Abertura do documento
    # ------------------------------------------------------------------
    def _view_internal(self, pdf_path):
        if not self._has_pymupdf():
            self._show_pymupdf_install_message(pdf_path)
            return

        open_token = self._document_open_token + 1
        self._document_open_token = open_token

        def worker():
            doc = None
            total_pages = 0
            error = None
            try:
                import fitz

                doc = fitz.open(pdf_path)
                if doc.needs_pass:
                    error = 'O PDF está protegido por senha.'
                else:
                    total_pages = len(doc)
                    if total_pages <= 0:
                        error = 'O PDF está vazio ou corrompido.'
            except ImportError:
                error = "__missing_pymupdf__"
            except Exception as exc:
                error = str(exc)

            if error and doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass
                doc = None

            Clock.schedule_once(
                lambda _dt, d=doc, pages=total_pages, err=error, tok=open_token:
                    self._finish_open_document(pdf_path, pages, err, tok, d),
                0,
            )

        Thread(target=worker, daemon=True).start()

    def _finish_open_document(self, pdf_path, total_pages, error, token, doc=None):
        if token != self._document_open_token:
            if doc is not None:
                Thread(target=self._dispose_doc, args=(doc,), daemon=True).start()
            return
        if error == "__missing_pymupdf__":
            self._show_pymupdf_install_message(pdf_path)
            return
        if error:
            if self.error_callback:
                self.error_callback(f'Erro ao visualizar PDF:\n{error}')
            return

        self._pdf_path = pdf_path
        self._pdf_total_pages = int(total_pages or 0)
        self._doc = doc
        with self._doc_lock:
            self._render_cache.clear()
        self.page_state = {'current': 0, 'zoom': 1.0, 'fit': 'page', 'rot': 0}
        self._create_pdf_viewer_window(pdf_path, self._pdf_total_pages)

    def _dispose_doc(self, doc):
        with self._doc_lock:
            try:
                doc.close()
            except Exception:
                pass
            self._render_cache.clear()

    # ------------------------------------------------------------------
    # Renderização (com cache e pré-carregamento)
    # ------------------------------------------------------------------
    def _render_payload(self, page_num, zoom, fit, vw, vh, rot=0):
        import fitz

        with self._doc_lock:
            doc = self._doc
            if doc is None:
                raise RuntimeError("closed")
            page = doc[page_num]
            base_rot = page.rotation
            m_base = fitz.Matrix(page.rotation_matrix)
            if rot:
                page.set_rotation((base_rot + rot) % 360)
            try:
                dw, dh = page.rect.width, page.rect.height
                hit_matrix = None
                if rot:
                    hit_matrix = tuple(~m_base * fitz.Matrix(page.rotation_matrix))

                base = (96.0 / 72.0) * dp(1)
                if fit:
                    margin = dp(32)
                    zw = max(10, vw - margin) / (dw * base)
                    zh = max(10, vh - margin) / (dh * base)
                    zoom = zw if fit == 'width' else min(zw, zh)
                zoom = max(ZOOM_MIN, min(ZOOM_MAX, zoom))

                key = (page_num, round(zoom, 3), rot)
                cached = self._render_cache.get(key)
                if cached is not None:
                    self._render_cache.move_to_end(key)
                    return cached

                disp_scale = base * zoom
                render_scale = min(disp_scale * 1.5, MAX_TEXTURE / max(dw, dh))
                render_scale = max(render_scale, 0.1)
                pix = page.get_pixmap(
                    matrix=fitz.Matrix(render_scale, render_scale), alpha=False)
            finally:
                if rot:
                    page.set_rotation(base_rot)

            samples = pix.samples
            row = pix.width * 3
            if pix.stride != row:
                samples = b"".join(samples[i * pix.stride:i * pix.stride + row]
                                   for i in range(pix.height))
            payload = {
                "error": None, "page_num": page_num, "total_pages": len(doc),
                "zoom": zoom, "tex_w": pix.width, "tex_h": pix.height,
                "samples": bytes(samples), "disp_w": dw * disp_scale,
                "disp_h": dh * disp_scale, "dw": dw, "hit_matrix": hit_matrix,
            }
            self._render_cache[key] = payload
            total = sum(len(p["samples"]) for p in self._render_cache.values())
            while len(self._render_cache) > 1 and (
                    len(self._render_cache) > CACHE_MAX_ITEMS or total > CACHE_MAX_BYTES):
                _k, old = self._render_cache.popitem(last=False)
                total -= len(old["samples"])
            return payload

    def _current_scroll(self):
        if not self._scroll:
            return (0.5, 1)
        return (self._scroll.scroll_x, self._scroll.scroll_y)

    def _render_current(self, scroll_to=None):
        if not self._pdf_path or self._doc is None or not self._scroll:
            return
        page_num = int(self.page_state.get('current', 0))
        zoom = float(self.page_state.get('zoom', 1.0))
        fit = self.page_state.get('fit')
        rot = int(self.page_state.get('rot', 0))
        vw, vh = self._scroll.size
        self._pending_scroll = scroll_to
        token = self._render_token + 1
        self._render_token = token
        self._set_status('A renderizar…')

        def worker():
            try:
                payload = self._render_payload(page_num, zoom, fit, vw, vh, rot)
            except Exception as exc:
                payload = {"error": str(exc)}
            Clock.schedule_once(
                lambda _dt, d=payload, t=token: self._apply_rendered_page(d, t), 0)

        Thread(target=worker, daemon=True).start()

    def _apply_rendered_page(self, payload, token):
        if token != self._render_token:
            return
        if payload.get("error"):
            self._set_status('')
            if payload["error"] != "closed" and self.error_callback:
                self.error_callback(f'Erro ao renderizar página:\n{payload["error"]}')
            return
        if not self._page_widget or self._tex_rect is None:
            return

        self._pdf_total_pages = int(payload["total_pages"])
        self.page_state['current'] = int(payload["page_num"])
        self.page_state['zoom'] = float(payload["zoom"])

        size = (int(payload["tex_w"]), int(payload["tex_h"]))
        if self._page_texture is None or self._page_texture_size != size:
            self._page_texture = Texture.create(size=size, colorfmt='rgb')
            self._page_texture.flip_vertical()
            self._page_texture.min_filter = 'linear'
            self._page_texture.mag_filter = 'linear'
            self._page_texture_size = size
        self._page_texture.blit_buffer(payload["samples"], colorfmt='rgb',
                                       bufferfmt='ubyte')
        self._tex_rect.texture = self._page_texture

        self._page_widget.size = (payload["disp_w"], payload["disp_h"])
        self._disp_scale = payload["disp_w"] / payload["dw"]
        self._hit_matrix = payload.get("hit_matrix")
        self._relayout_stage()
        self._page_widget.canvas.ask_update()
        self._set_status('')
        self._update_toolbar_state()
        self._draw_highlights()

        if self._scroll_hit_pending:
            self._scroll_hit_pending = False
            Clock.schedule_once(lambda _dt: self._scroll_to_current_hit(), 0.05)
        elif self._pending_scroll:
            sx, sy = self._pending_scroll
            Clock.schedule_once(lambda _dt: self._set_scroll(sx, sy), 0.03)

        self._prefetch(payload["page_num"], payload["zoom"],
                       self.page_state.get('fit'))

    def _prefetch(self, page_num, zoom, fit):
        if self._prefetching or not self._scroll:
            return
        self._prefetching = True
        vw, vh = self._scroll.size
        rot = int(self.page_state.get('rot', 0))
        doc_token = self._document_open_token

        def worker():
            try:
                for n in (page_num + 1, page_num - 1):
                    if n < 0 or n >= self._pdf_total_pages:
                        continue
                    if doc_token != self._document_open_token or self._doc is None:
                        return
                    self._render_payload(n, zoom, fit, vw, vh, rot)
            except Exception:
                pass
            finally:
                self._prefetching = False

        Thread(target=worker, daemon=True).start()

    def _relayout_stage(self):
        if not (self._stage and self._page_widget and self._scroll):
            return
        m = dp(24)
        pw, ph = self._page_widget.size
        vw, vh = self._scroll.size
        # Se a página cabe na janela, o conteúdo tem exatamente o tamanho da
        # janela (sem rolagem); senão ganha uma margem para respirar.
        stage_w = vw if pw <= vw - dp(2) else pw + 2 * m
        stage_h = vh if ph <= vh - dp(2) else ph + 2 * m
        self._stage.size = (stage_w, stage_h)
        self._place_page()

    def _place_page(self, *_):
        st, pg = self._stage, self._page_widget
        if not st or not pg:
            return
        pg.pos = (round(st.x + (st.width - pg.width) / 2),
                  round(st.y + (st.height - pg.height) / 2))

    def _set_scroll(self, sx, sy):
        if not self._scroll:
            return
        self._scroll.scroll_x = max(0, min(1, sx))
        self._scroll.scroll_y = max(0, min(1, sy))

    def _on_viewport_size(self, *_):
        if not self._pdf_path:
            return
        self._relayout_stage()
        if self.page_state.get('fit') and self._doc is not None:
            Clock.unschedule(self._refit_cb)
            Clock.schedule_once(self._refit_cb, 0.25)

    def _refit_cb(self, _dt):
        if self._pdf_path and self.page_state.get('fit'):
            self._render_current(scroll_to=self._current_scroll())

    # ------------------------------------------------------------------
    # Navegação e zoom
    # ------------------------------------------------------------------
    def _go_to_page(self, number, scroll_to=None):
        total = int(self._pdf_total_pages or 0)
        if total <= 0:
            return
        number = max(0, min(total - 1, int(number)))
        if number == int(self.page_state.get('current', 0)) and scroll_to is None:
            self._sync_page_input()
            return
        self.page_state['current'] = number
        sx = self._scroll.scroll_x if self._scroll else 0.5
        self._render_current(scroll_to=scroll_to or (sx, 1))

    def _nav_page(self, direction, total_pages=None):
        self._go_to_page(int(self.page_state.get('current', 0)) + direction)

    def _zoom_step(self, direction):
        current = float(self.page_state.get('zoom', 1.0))
        if direction > 0:
            options = [z for z in ZOOM_PRESETS if z > current + 0.005]
            new = min(options) if options else None
        else:
            options = [z for z in ZOOM_PRESETS if z < current - 0.005]
            new = max(options) if options else None
        if new is None:
            return
        self.page_state['zoom'] = new
        self.page_state['fit'] = None
        self._render_current(scroll_to=self._current_scroll())

    def _zoom_page(self, amount):
        self._zoom_step(1 if amount > 0 else -1)

    def _fit(self, mode):
        self.page_state['fit'] = mode
        self._render_current(scroll_to=(0.5, 1))

    def _fit_to_window(self):
        self._fit('page')

    def _rotate(self):
        self.page_state['rot'] = (int(self.page_state.get('rot', 0)) + 90) % 360
        self._render_current(scroll_to=(0.5, 1))

    def _on_double_tap(self):
        self._fit('width' if self.page_state.get('fit') == 'page' else 'page')

    # ------------------------------------------------------------------
    # Painel de miniaturas
    # ------------------------------------------------------------------
    def _create_thumb_panel(self):
        show = Window.width > dp(900) and int(self._pdf_total_pages or 0) > 1
        primary = _theme_color('primary', (0.15, 0.52, 0.76, 1))
        panel = MDCard(
            orientation='vertical', size_hint_x=None,
            width=dp(132) if show else 0, opacity=1 if show else 0,
            disabled=not show, padding=[dp(4), dp(6)], radius=[dp(10)],
            elevation=0,
            md_bg_color=_theme_color('surface_alt', (0.97, 0.97, 0.97, 1)),
        )
        scroll = ScrollView(
            do_scroll_x=False, bar_width=dp(5), scroll_type=['bars'],
            bar_color=[primary[0], primary[1], primary[2], 0.8],
        )
        box = MDBoxLayout(orientation='vertical', size_hint_y=None,
                          spacing=dp(8), padding=[dp(4), dp(6)])
        box.bind(minimum_height=box.setter('height'))
        scroll.add_widget(box)
        panel.add_widget(scroll)
        self._thumb_panel, self._thumb_scroll, self._thumb_box = panel, scroll, box
        self._thumbs_visible = show
        self._thumb_items = []
        self._thumb_sel = -1
        return panel

    def _toggle_thumbs(self, show):
        panel = self._thumb_panel
        if not panel or int(self._pdf_total_pages or 0) <= 1:
            return
        self._thumbs_visible = bool(show)
        panel.width = dp(132) if show else 0
        panel.opacity = 1 if show else 0
        panel.disabled = not show
        self._thumb_sel = -1
        self._update_toolbar_state()

    def _on_thumb_click(self, index):
        self._go_to_page(index)

    def _build_thumbnails(self):
        box = self._thumb_box
        if not box or self._doc is None:
            return
        total = int(self._pdf_total_pages or 0)
        primary = _theme_color('primary', (0.15, 0.52, 0.76, 1))
        tw = dp(92)
        box.clear_widgets()
        self._thumb_items = []
        for n in range(total):
            thumb = PageThumb(n, self._on_thumb_click, primary,
                              size=(tw, tw * 1.414), pos_hint={'center_x': 0.5})
            label = self._small_label(str(n + 1), halign='center')
            label.size_hint_y = None
            label.height = dp(16)
            entry = MDBoxLayout(orientation='vertical', size_hint_y=None,
                                height=tw * 1.414 + dp(24), spacing=dp(4))
            entry.add_widget(thumb)
            entry.add_widget(label)
            box.add_widget(entry)
            self._thumb_items.append((entry, thumb))
        self._thumb_token += 1
        token = self._thumb_token
        doc_token = self._document_open_token
        cur = int(self.page_state.get('current', 0))
        order = sorted(range(total), key=lambda n: abs(n - cur))
        self._thumb_sel = -1
        self._sync_thumbs()

        def worker():
            import fitz
            for n in order:
                if token != self._thumb_token or doc_token != self._document_open_token:
                    return
                try:
                    with self._doc_lock:
                        doc = self._doc
                        if doc is None:
                            return
                        page = doc[n]
                        pw, ph = page.rect.width, page.rect.height
                        scale = (tw * 1.5) / pw
                        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale),
                                              alpha=False)
                        samples = pix.samples
                        row = pix.width * 3
                        if pix.stride != row:
                            samples = b"".join(
                                samples[i * pix.stride:i * pix.stride + row]
                                for i in range(pix.height))
                        samples = bytes(samples)
                        w, h = pix.width, pix.height
                except Exception:
                    continue
                Clock.schedule_once(
                    lambda _dt, n=n, w=w, h=h, s=samples, pw=pw, ph=ph:
                        self._apply_thumb(n, w, h, s, pw, ph, token), 0)
                time.sleep(0.01)

        Thread(target=worker, daemon=True).start()

    def _apply_thumb(self, n, w, h, samples, pw, ph, token):
        if token != self._thumb_token or n >= len(self._thumb_items):
            return
        entry, thumb = self._thumb_items[n]
        tex = Texture.create(size=(w, h), colorfmt='rgb')
        tex.flip_vertical()
        tex.min_filter = 'linear'
        tex.mag_filter = 'linear'
        tex.blit_buffer(samples, colorfmt='rgb', bufferfmt='ubyte')
        thumb.size = (dp(92), dp(92) * ph / pw)
        entry.height = thumb.height + dp(24)
        thumb.set_texture(tex)

    def _sync_thumbs(self):
        items = self._thumb_items
        if not items:
            return
        cur = int(self.page_state.get('current', 0))
        if cur == self._thumb_sel or not (0 <= cur < len(items)):
            return
        if 0 <= self._thumb_sel < len(items):
            items[self._thumb_sel][1].set_selected(False)
        items[cur][1].set_selected(True)
        self._thumb_sel = cur
        if self._thumbs_visible and self._thumb_scroll:
            try:
                self._thumb_scroll.scroll_to(items[cur][0], padding=dp(16),
                                             animate=False)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Pesquisa de texto
    # ------------------------------------------------------------------
    def _toggle_search(self, show):
        bar = self._search_bar
        if not bar:
            return
        self._search_visible = bool(show)
        bar.height = dp(46) if show else 0
        bar.opacity = 1 if show else 0
        bar.disabled = not show
        if show:
            def focus(_dt):
                if self._search_input:
                    self._search_input.focus = True
                    self._search_input.select_all()
            Clock.schedule_once(focus, 0.05)
        else:
            if self._search_input:
                self._search_input.focus = False
            self._clear_search()
        self._update_toolbar_state()

    def _clear_search(self):
        self._search_token += 1
        self._search_hits = []
        self._search_index = -1
        self._search_query = ""
        if self._search_count:
            self._search_count.text = ''
        self._draw_highlights()

    def _on_search_validate(self, inst):
        query = (inst.text or "").strip()
        Clock.schedule_once(lambda _dt: setattr(inst, 'focus', True), 0.02)
        if query and query == self._search_query and self._search_hits:
            self._step_hit(1)
        else:
            self._run_search(query)

    def _run_search(self, query):
        self._search_token += 1
        token = self._search_token
        self._search_hits = []
        self._search_index = -1
        self._search_query = query
        self._draw_highlights()
        if not query or self._doc is None:
            if self._search_count:
                self._search_count.text = ''
            return
        if self._search_count:
            self._search_count.text = 'A pesquisar…'
        doc_token = self._document_open_token

        def worker():
            hits = []
            error = None
            try:
                total = int(self._pdf_total_pages or 0)
                for pn in range(total):
                    if token != self._search_token or doc_token != self._document_open_token:
                        return
                    with self._doc_lock:
                        if self._doc is None:
                            return
                        rects = self._doc[pn].search_for(query)
                    for r in rects:
                        hits.append((pn, (r.x0, r.y0, r.x1, r.y1)))
                    if len(hits) >= 1000:
                        break
            except Exception as exc:
                error = str(exc)
            Clock.schedule_once(
                lambda _dt: self._apply_search(hits, error, token), 0)

        Thread(target=worker, daemon=True).start()

    def _apply_search(self, hits, error, token):
        if token != self._search_token:
            return
        if error:
            if self._search_count:
                self._search_count.text = 'Erro na pesquisa'
            return
        self._search_hits = hits
        if not hits:
            self._search_index = -1
            if self._search_count:
                self._search_count.text = 'Sem resultados'
            self._draw_highlights()
            return
        cur = int(self.page_state.get('current', 0))
        start = next((i for i, h in enumerate(hits) if h[0] >= cur), 0)
        self._goto_hit(start)

    def _step_hit(self, direction):
        if not self._search_hits:
            return
        idx = (self._search_index + direction) % len(self._search_hits)
        self._goto_hit(idx)

    def _goto_hit(self, idx):
        self._search_index = idx
        if self._search_count:
            self._search_count.text = f"{idx + 1} de {len(self._search_hits)}"
        page_num = self._search_hits[idx][0]
        if page_num != int(self.page_state.get('current', 0)):
            self._scroll_hit_pending = True
            self.page_state['current'] = page_num
            self._render_current(scroll_to=(0.5, 1))
        else:
            self._draw_highlights()
            Clock.schedule_once(lambda _dt: self._scroll_to_current_hit(), 0)

    def _map_rect(self, r):
        """Retângulo do resultado -> coordenadas (pt) da página exibida."""
        x0, y0, x1, y1 = r
        m = self._hit_matrix
        if not m:
            return (x0, y0, x1, y1)
        a, b, c, d, e, f = m
        pts = [(a * x + c * y + e, b * x + d * y + f)
               for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))

    def _draw_highlights(self):
        grp = self._hl_group
        page = self._page_widget
        if grp is None or page is None:
            return
        grp.clear()
        if not self._search_hits:
            return
        s = self._disp_scale
        cur = int(self.page_state.get('current', 0))
        active = (self._search_hits[self._search_index]
                  if 0 <= self._search_index < len(self._search_hits) else None)
        for hit in self._search_hits:
            if hit[0] != cur:
                continue
            x0, y0, x1, y1 = self._map_rect(hit[1])
            grp.add(Color(1, 0.5, 0, 0.50) if hit is active
                    else Color(1, 0.85, 0, 0.38))
            grp.add(Rectangle(
                pos=(page.x + x0 * s, page.y + page.height - y1 * s),
                size=((x1 - x0) * s, (y1 - y0) * s)))

    def _scroll_to_current_hit(self):
        if not (self._scroll and self._stage and self._page_widget):
            return
        if not (0 <= self._search_index < len(self._search_hits)):
            return
        x0, y0, x1, y1 = self._map_rect(self._search_hits[self._search_index][1])
        s = self._disp_scale
        stage, page, scroll = self._stage, self._page_widget, self._scroll
        if stage.height > scroll.height:
            top = (stage.height - page.height) / 2
            target = top + ((y0 + y1) / 2) * s - scroll.height / 2
            frac = target / (stage.height - scroll.height)
            scroll.scroll_y = 1 - max(0, min(1, frac))
        if stage.width > scroll.width:
            left = (stage.width - page.width) / 2
            target = left + ((x0 + x1) / 2) * s - scroll.width / 2
            scroll.scroll_x = max(0, min(1, target / (stage.width - scroll.width)))

    # ------------------------------------------------------------------
    # Fechar
    # ------------------------------------------------------------------
    def _close_viewer(self, popup):
        self._document_open_token += 1
        self._render_token += 1
        self._search_token += 1
        self._thumb_token += 1
        if self._key_bound:
            Window.unbind(mouse_pos=self._on_viewer_hover,
                          on_key_down=self._on_key_down,
                          on_key_up=self._on_key_up)
            self._key_bound = False
        Clock.unschedule(self._refit_cb)
        Clock.unschedule(self._initial_render)

        doc, self._doc = self._doc, None
        if doc is not None:
            Thread(target=self._dispose_doc, args=(doc,), daemon=True).start()

        self._pdf_path = None
        self._pdf_total_pages = 0
        self._page_texture = None
        self._page_texture_size = None
        self.pdf_document = None
        self.pdf_image = None
        self.pdf_container = None
        self.page_label = None
        self._scroll = self._stage = self._page_widget = self._hl_group = None
        self._tex_rect = None
        self._hit_matrix = None
        self._thumb_panel = self._thumb_scroll = self._thumb_box = None
        self._thumb_items = []
        self._thumb_sel = -1
        self._thumbs_visible = False
        self._page_input = self._total_label = self._zoom_label = None
        self._status_label = self._search_bar = None
        self._search_input = self._search_count = None
        self._tools = {}
        self._tool_list = []
        self._search_hits = []
        self._search_visible = False
        self._ctrl_down = False
        self.current_popup = None
        popup.dismiss()

    # ------------------------------------------------------------------
    # Instalação do PyMuPDF
    # ------------------------------------------------------------------
    def _show_pymupdf_install_message(self, pdf_path):
        if getattr(self, "pymupdf_dialog", None):
            self.pymupdf_dialog.dismiss()

        if self._can_install_pymupdf():
            instructions = (
                "O visualizador interno usa a biblioteca PyMuPDF.\n\n"
                "Posso instalar esta dependência agora e abrir o PDF automaticamente."
            )
        else:
            instructions = (
                "Esta versão do app foi iniciada sem suporte para instalar novas "
                "bibliotecas em tempo real.\n\n"
                "Inclua PyMuPDF na instalação ou na build do projeto para ativar o "
                "visualizador interno."
            )

        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(10),
            padding=[dp(16), dp(12), dp(16), dp(8)],
            size_hint_y=None,
        )
        content.bind(minimum_height=content.setter('height'))

        content.add_widget(MDLabel(
            text='Biblioteca PyMuPDF não instalada',
            font_style='Subtitle1',
            bold=True,
            halign='left',
            theme_text_color='Custom',
            text_color=_theme_color('warning', (0.9, 0.5, 0.1, 1)),
            size_hint_y=None,
            height=dp(24),
        ))

        message = MDLabel(
            text=instructions,
            font_style='Body2',
            halign='left',
            valign='middle',
            theme_text_color='Custom',
            text_color=_theme_color('text_primary', (0.3, 0.3, 0.3, 1)),
            size_hint_y=None,
        )
        message.bind(size=lambda inst, _: setattr(inst, 'text_size', (inst.width, None)))
        message.bind(texture_size=lambda inst, value: setattr(inst, 'height', value[1]))
        content.add_widget(message)

        self.pymupdf_dialog = MDDialog(
            title='Dependência necessária',
            type='custom',
            content_cls=content,
            size_hint=(None, None),
            size=(min(dp(580), Window.width * 0.9), dp(300)),
            buttons=self._build_pymupdf_dialog_buttons(pdf_path),
        )
        self.pymupdf_dialog.open()

    def _build_pymupdf_dialog_buttons(self, pdf_path):
        buttons = [
            MDFlatButton(
                text='Fechar',
                on_release=lambda x: self.pymupdf_dialog.dismiss(),
            ),
            MDRectangleFlatButton(
                text='Abrir no app padrão',
                on_release=lambda x: [
                    self._open_in_browser(pdf_path),
                    self.pymupdf_dialog.dismiss(),
                ],
            ),
        ]

        if self._can_install_pymupdf():
            buttons.append(
                MDRaisedButton(
                    text='Instalar e abrir',
                    md_bg_color=_theme_color('primary', (0.15, 0.52, 0.76, 1)),
                    on_release=lambda x: self._install_pymupdf_async(pdf_path),
                )
            )

        return buttons

    def _install_pymupdf_async(self, pdf_path):
        if self._installing_pymupdf:
            return

        if getattr(self, "pymupdf_dialog", None):
            self.pymupdf_dialog.dismiss()
            self.pymupdf_dialog = None

        if not self._can_install_pymupdf():
            self._show_pymupdf_install_message(pdf_path)
            return

        self._installing_pymupdf = True
        self._show_install_progress_dialog()

        def worker():
            error_message = None

            for command in self._build_pymupdf_install_commands():
                try:
                    completed = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        timeout=300,
                    )
                except Exception as exc:
                    error_message = str(exc)
                    continue

                if completed.returncode == 0:
                    importlib.invalidate_caches()
                    error_message = None
                    break

                error_message = self._summarize_install_output(
                    completed.stderr or completed.stdout,
                    completed.returncode,
                )

            Clock.schedule_once(
                lambda _dt, err=error_message: self._finish_pymupdf_install(pdf_path, err),
                0,
            )

        Thread(target=worker, daemon=True).start()

    def _build_pymupdf_install_commands(self):
        base_command = [
            sys.executable, "-m", "pip", "install",
            "--disable-pip-version-check", "PyMuPDF",
        ]
        commands = [base_command]

        base_prefix = getattr(sys, "base_prefix", sys.prefix)
        real_prefix = getattr(sys, "real_prefix", None)
        in_virtualenv = bool(real_prefix) or (base_prefix != sys.prefix)

        if not in_virtualenv:
            commands.append(base_command[:-1] + ["--user", "PyMuPDF"])

        return commands

    def _summarize_install_output(self, raw_output, returncode):
        text = (raw_output or "").strip()
        if not text:
            return f"pip terminou com código {returncode}."

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        summary = " ".join(lines[-3:])
        if len(summary) > 320:
            summary = summary[:317].rstrip() + "..."
        return summary

    def _show_install_progress_dialog(self):
        if getattr(self, "install_dialog", None):
            self.install_dialog.dismiss()

        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(10),
            padding=[dp(16), dp(12), dp(16), dp(10)],
            size_hint_y=None,
        )
        content.bind(minimum_height=content.setter('height'))

        content.add_widget(MDLabel(
            text='A instalar PyMuPDF...',
            font_style='Subtitle1',
            bold=True,
            halign='left',
            theme_text_color='Custom',
            text_color=_theme_color('primary', (0.15, 0.52, 0.76, 1)),
            size_hint_y=None,
            height=dp(24),
        ))

        message = MDLabel(
            text=(
                'Isto pode demorar alguns segundos.\n'
                'Assim que a instalação terminar, o PDF será aberto automaticamente.'
            ),
            font_style='Body2',
            halign='left',
            valign='middle',
            theme_text_color='Custom',
            text_color=_theme_color('text_primary', (0.3, 0.3, 0.3, 1)),
            size_hint_y=None,
        )
        message.bind(size=lambda inst, _: setattr(inst, 'text_size', (inst.width, None)))
        message.bind(texture_size=lambda inst, value: setattr(inst, 'height', value[1]))
        content.add_widget(message)

        self.install_dialog = MDDialog(
            title='Preparando visualizador interno',
            type='custom',
            content_cls=content,
            size_hint=(None, None),
            size=(min(dp(560), Window.width * 0.9), dp(220)),
        )
        self.install_dialog.open()

    def _finish_pymupdf_install(self, pdf_path, error_message):
        self._installing_pymupdf = False

        if getattr(self, "install_dialog", None):
            self.install_dialog.dismiss()
            self.install_dialog = None

        importlib.invalidate_caches()

        if self._has_pymupdf():
            self._view_internal(pdf_path)
            return

        if error_message and self.error_callback:
            self.error_callback(f'Não foi possível instalar PyMuPDF:\n{error_message}')

        self._show_pymupdf_install_message(pdf_path)