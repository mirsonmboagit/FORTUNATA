from kivy.uix.screenmanager import Screen
import os
import sys
import math
import unicodedata
from kivy.properties import ObjectProperty, ListProperty, BooleanProperty, NumericProperty
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.app import App
from kivy.graphics import Color, Line, RoundedRectangle
from kivy.animation import Animation
from collections import deque
from threading import Thread
import time
from datetime import datetime, timedelta
from ui.components.native_widgets import (
    NativeBoxLayout as MDBoxLayout,
    NativeButton as MDRaisedButton,
    NativeCard as MDCard,
    NativeDialog as MDDialog,
    NativeDropdownMenu as MDDropdownMenu,
    NativeFlatButton as MDFlatButton,
    NativeGridLayout as MDGridLayout,
    NativeIcon as MDIcon,
    NativeLabel as MDLabel,
    NativeSnackbar as MDSnackbar,
    NativeTextField as MDTextField,
)

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database.provider import get_db
from ui.components.hover_widgets import HoverCard, HoverRaisedButton
from utils.core.i18n import correct_portuguese_text, translate_text
from utils.core.formatters import format_money
from ui.components.tooltip_widgets import TooltipFloatingActionButton, TooltipIconButton, set_attention_shake
from utils.business.expiry_alerts import evaluate_expiry_alert, get_expiry_level_counts
from utils.business.purchase_suggestions import (
    build_demand_purchase_candidates,
    load_product_api_context,
    normalize_barcode,
)
from utils.ai.ai_insights import build_ai_purchase_suggestions


_PRODUCT_FORM_CLASS = None


def _get_ai_popup_helpers():
    from utils.ai.ai_popups import (
        build_auto_banner_data,
        build_banner_details_sections,
        build_positive_banner,
        render_auto_banners,
    )
    return (
        build_auto_banner_data,
        build_banner_details_sections,
        build_positive_banner,
        render_auto_banners,
    )


def _get_detail_popup_class():
    try:
        from .detail_popup import DetailPopup
    except ImportError:
        from admin.detail_popup import DetailPopup
    return DetailPopup


def _describe_loader_error(exc, prefix):
    missing_name = getattr(exc, "name", "")
    if missing_name:
        return f"{prefix}: dependencia em falta ({missing_name})"
    text = str(exc or "").strip()
    if not text:
        text = exc.__class__.__name__
    return f"{prefix}: {text}"


def _build_unavailable_product_form_class(error):
    message = _describe_loader_error(error, "Formulario de produto indisponivel")

    class UnavailableProductForm:
        def __init__(self, admin_screen, *args, **kwargs):
            self._dialog = MDDialog(
                title="Erro ao abrir produto",
                text=message,
                buttons=[MDFlatButton(text="Fechar")],
            )
            if self._dialog.buttons:
                self._dialog.buttons[0].bind(on_release=lambda *_: self._dialog.dismiss())

        def open(self):
            self._dialog.open()

    return UnavailableProductForm


def _get_product_form_class():
    global _PRODUCT_FORM_CLASS
    if _PRODUCT_FORM_CLASS is not None:
        return _PRODUCT_FORM_CLASS
    try:
        from .product_form import ProductForm
        _PRODUCT_FORM_CLASS = ProductForm
        return _PRODUCT_FORM_CLASS
    except ImportError:
        try:
            from admin.product_form import ProductForm
            _PRODUCT_FORM_CLASS = ProductForm
            return _PRODUCT_FORM_CLASS
        except Exception as exc:
            return _build_unavailable_product_form_class(exc)
    except Exception as exc:
        return _build_unavailable_product_form_class(exc)


Builder.load_file(os.path.join(CURRENT_DIR, 'admin_screen.kv'))


COL_HINTS = [0.06, 0.18, 0.09, 0.09, 0.07, 0.11, 0.11, 0.15, 0.14]
LOSS_LABELS = {
    "DAMAGE": "Danificado",
    "EXPIRED": "Expirado",
    "THEFT": "Roubo",
    "ADJUSTMENT": "Ajuste",
}

# -- Tamanho do lote de widgets criados por frame durante render paginado --
_TABLE_BATCH_SIZE = 6
# -- Intervalo entre lotes (segundos) — mantem o UI responsivo --
_TABLE_BATCH_INTERVAL = 0.016   # ~1 frame a 60 fps


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


class ProductTableCell(MDBoxLayout):
    hover_growth = NumericProperty(0)
    hover_glow_alpha = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._hover_glow_rgba = [0.15, 0.52, 0.76, 1]
        with self.canvas.after:
            self._hover_glow_color = Color(0.15, 0.52, 0.76, 0)
            self._hover_glow_rect = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[dp(4)],
            )
            self._hover_outline_color = Color(0.15, 0.52, 0.76, 0)
            self._hover_outline = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, dp(4)),
                width=dp(1.1),
            )
        self.bind(
            pos=self._sync_hover_glow,
            size=self._sync_hover_glow,
            hover_growth=self._sync_hover_glow,
            hover_glow_alpha=self._sync_hover_glow,
        )

    def set_hover_glow_color(self, rgba):
        color = list(rgba or self._hover_glow_rgba)
        while len(color) < 4:
            color.append(1)
        self._hover_glow_rgba = color[:4]
        self._sync_hover_glow()

    def _sync_hover_glow(self, *_args):
        color = list(self._hover_glow_rgba or [0.15, 0.52, 0.76, 1])
        alpha = float(self.hover_glow_alpha or 0)
        color[3] = alpha
        self._hover_glow_color.rgba = color
        inset = dp(1)
        self._hover_glow_rect.pos = (self.x + inset, self.y + inset)
        self._hover_glow_rect.size = (
            max(0, self.width - (inset * 2)),
            max(0, self.height - (inset * 2)),
        )
        self._hover_glow_rect.radius = [dp(5)]
        outline = list(color)
        outline[3] = min(alpha * 2.2, 0.78)
        self._hover_outline_color.rgba = outline
        self._hover_outline.rounded_rectangle = (
            self.x + inset,
            self.y + inset,
            max(0, self.width - (inset * 2)),
            max(0, self.height - (inset * 2)),
            dp(5),
        )

    def animate_inner_growth(self, active):
        scale = 1.18 if active else 1.0
        for widget in self._iter_content_widgets():
            for attr in ("font_size", "icon_size"):
                if not hasattr(widget, attr):
                    continue
                base_attr = f"_product_cell_base_{attr}"
                base = getattr(widget, base_attr, None)
                if base is None:
                    try:
                        base = float(getattr(widget, attr))
                    except Exception:
                        continue
                    setattr(widget, base_attr, base)
                Animation.cancel_all(widget, attr)
                Animation(**{attr: base * scale, "d": 0.12, "t": "out_quad"}).start(widget)
            self._animate_inner_shake(widget, active)

    def _animate_inner_shake(self, widget, active):
        if not hasattr(widget, "x"):
            return
        base_x = getattr(widget, "_product_cell_base_x", None)
        if base_x is None or active:
            try:
                base_x = float(widget.x)
            except Exception:
                return
            widget._product_cell_base_x = base_x
        Animation.cancel_all(widget, "x")
        if not active:
            Animation(x=base_x, d=0.08, t="out_quad").start(widget)
            return
        wobble = dp(2)
        (
            Animation(x=base_x + wobble, d=0.035, t="out_quad")
            + Animation(x=base_x - wobble, d=0.045, t="out_quad")
            + Animation(x=base_x + (wobble * 0.45), d=0.035, t="out_quad")
            + Animation(x=base_x, d=0.045, t="out_quad")
        ).start(widget)

    def _iter_content_widgets(self):
        stack = list(getattr(self, "children", []) or [])
        while stack:
            widget = stack.pop()
            yield widget
            stack.extend(list(getattr(widget, "children", []) or []))


class RecycleAdminProductRow(RecycleDataViewBehavior, MDBoxLayout):
    """One reusable Admin table row.

    The previous grid rebuilt 9 cells and their hover handlers for every search
    character.  This row is retained by ``RecycleView`` and only its values are
    updated, like the Manager product list.
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("orientation", "horizontal")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(56))
        kwargs.setdefault("padding", [dp(8), 0])
        super().__init__(**kwargs)
        self.admin_screen = None
        self.product_data = None
        self.row_index = 0
        self.palette = {}
        self._base_bg_color = [1, 1, 1, 1]
        self._hover_active = False
        # Linha horizontal inferior da linha
        with self.canvas.after:
            self._row_line_color = Color(0.5, 0.55, 0.62, 0.28)
            self._row_hline = Line(points=[], width=1)
        self.bind(pos=self._sync_row_hline, size=self._sync_row_hline)
        self._build_cells()

    def _sync_row_hline(self, *_args):
        y = self.y + 0.5
        self._row_hline.points = [self.x, y, self.right, y]

    def _make_cell(self, width_hint, align="center", with_divider=True):
        cell = MDBoxLayout(size_hint_x=width_hint, padding=[dp(5), 0])
        if with_divider:
            with cell.canvas.after:
                cell._div_color = Color(0.5, 0.55, 0.62, 0.22)
                cell._div_line = Line(points=[], width=1)
            def _sync_div(*_a, c=cell):
                # linha vertical à direita da célula (altura total)
                x = c.right - 0.5
                c._div_line.points = [x, c.y, x, c.top]
            cell.bind(pos=_sync_div, size=_sync_div)
        label = MDLabel(
            halign=align,
            valign="middle",
            shorten=True,
            shorten_from="right",
            theme_text_color="Custom",
            font_style="Body1",
            font_size=sp(16),
        )
        cell.add_widget(label)
        self.add_widget(cell)
        return label

    def _build_cells(self):
        sequence_cell = FloatLayout(size_hint_x=COL_HINTS[0])
        with sequence_cell.canvas.after:
            sequence_cell._div_color = Color(0.5, 0.55, 0.62, 0.22)
            sequence_cell._div_line = Line(points=[], width=1)
        def _sync_seq_div(*_a, c=sequence_cell):
            x = c.right - 0.5
            c._div_line.points = [x, c.y, x, c.top]
        sequence_cell.bind(pos=_sync_seq_div, size=_sync_seq_div)
        self.sequence_label = MDLabel(
            halign="center", valign="middle", theme_text_color="Custom", bold=True,
            font_size=sp(16), size_hint=(1, 1), pos_hint={"x": 0, "y": 0},
        )
        self.sequence_button = HoverRaisedButton(
            size_hint=(1, 1), pos_hint={"x": 0, "y": 0}, font_size=sp(15),
        )
        self.sequence_button.bind(on_release=self._select_lot)
        sequence_cell.add_widget(self.sequence_label)
        sequence_cell.add_widget(self.sequence_button)
        self.add_widget(sequence_cell)

        self.name_label = self._make_cell(COL_HINTS[1], "left")
        self.stock_label = self._make_cell(COL_HINTS[2])
        self.sold_label = self._make_cell(COL_HINTS[3])
        self.type_label = self._make_cell(COL_HINTS[4])
        self.price_label = self._make_cell(COL_HINTS[5])
        self.profit_label = self._make_cell(COL_HINTS[6])
        self.expiry_label = self._make_cell(COL_HINTS[7])

        actions_cell = AnchorLayout(size_hint_x=COL_HINTS[8], anchor_x="center", anchor_y="center")
        actions = MDBoxLayout(size_hint=(None, None), size=(dp(124), dp(36)), spacing=dp(8))
        action_size = {"size_hint": (None, None), "size": (dp(36), dp(36)), "radius": [dp(18)], "elevation": 0}
        self.detail_button = TooltipIconButton(icon="information", icon_size=sp(19), hint_text="Ver detalhes", **action_size)
        self.edit_button = TooltipIconButton(icon="pencil", icon_size=sp(19), hint_text="Editar produto", **action_size)
        self.delete_button = TooltipIconButton(icon="delete", icon_size=sp(19), hint_text="Eliminar produto", **action_size)
        self.detail_button.bind(on_release=self._show_details)
        self.edit_button.bind(on_release=self._edit_product)
        self.delete_button.bind(on_release=self._delete_product)
        for button in (self.detail_button, self.edit_button, self.delete_button):
            actions.add_widget(button)
        actions_cell.add_widget(actions)
        self.add_widget(actions_cell)

    def refresh_view_attrs(self, rv, index, data):
        if getattr(self, "_inline_field", None):
            self.cancel_inline_edit(restore=True)
        result = super().refresh_view_attrs(rv, index, data)
        self.admin_screen = data.get("admin_screen")
        self.product_data = data.get("product_data")
        self.row_index = data.get("row_index", index)
        self.palette = data.get("palette") or {}
        self.height = data.get("row_height", dp(56))
        self.set_product_payload()
        return result

    def set_product_payload(self):
        screen = self.admin_screen
        product = self.product_data
        if screen is None or not product:
            return

        palette = self.palette
        tokens = palette.get("tokens", {})
        text_primary = palette.get("text_primary", [0.25, 0.30, 0.40, 1])
        text_secondary = palette.get("text_secondary", [0.2, 0.25, 0.35, 1])
        info_color = palette.get("info_color", [0.1, 0.45, 0.75, 1])
        success_color = palette.get("success_color", [0.10, 0.55, 0.25, 1])
        warning_color = palette.get("warning_color", [0.75, 0.45, 0.10, 1])
        danger_color = palette.get("danger_color", [0.8, 0.2, 0.2, 1])
        self._base_bg_color = list(
            palette.get("row_even", [0.97, 0.98, 0.99, 1])
            if self.row_index % 2 == 0
            else palette.get("row_odd", [1, 1, 1, 1])
        )
        self._hover_active = False
        self.md_bg_color = self._base_bg_color

        lot_count = screen._get_group_lot_count(product)
        selected_lot_id = screen._get_group_selected_lot_id(product)
        selected_lot_position = screen._get_group_selected_lot_position(product)
        display_id = screen._get_display_id(product)
        self.sequence_label.text = str(display_id)
        self.sequence_label.text_color = text_primary
        self.sequence_button.text = str(display_id)
        self.sequence_button.disabled = lot_count <= 1
        self.sequence_button.opacity = 1 if lot_count > 1 else 0
        self.sequence_button.md_bg_color = tokens.get("info", info_color)
        self.sequence_button.theme_text_color = "Custom"
        self.sequence_button.text_color = tokens.get("on_primary", [1, 1, 1, 1])
        self.sequence_button.hint_text = "Selecionar lote"

        self.name_label.text = (
            f"{product[1]} (Lote {selected_lot_position} de {lot_count})"
            if lot_count > 1 and selected_lot_position is not None
            else f"{product[1]} ({lot_count} lotes)" if lot_count > 1 else str(product[1])
        )
        self.name_label.text_color = text_primary
        self.name_label.bold = True

        is_weight = bool(product[15]) if len(product) > 15 else False
        unit_label = "KG" if is_weight else ""
        stock_value = _safe_float(product[2] if len(product) > 2 else 0.0)
        sold_value = _safe_float(product[3] if len(product) > 3 else 0.0)
        self.stock_label.text = f"{stock_value:.2f} {unit_label}" if is_weight else f"{int(stock_value)}"
        self.stock_label.text_color = danger_color if stock_value < 10 else text_primary
        self.stock_label.bold = stock_value < 10
        self.sold_label.text = f"{sold_value:.2f} {unit_label}" if is_weight else f"{int(sold_value)}"
        self.sold_label.text_color = text_primary
        self.type_label.text = "KG" if is_weight else "UN"
        self.type_label.text_color = warning_color if is_weight else info_color
        self.type_label.bold = True
        self.price_label.text = f"{_safe_float(product[4] if len(product) > 4 else 0.0):.2f} MT"
        self.price_label.text_color = success_color
        self.price_label.bold = True
        self.profit_label.text = f"{_safe_float(product[8] if len(product) > 8 else 0.0):.2f} MT"
        self.profit_label.text_color = info_color
        self.profit_label.bold = True

        expiry_alert = screen._get_expiry_alert(product)
        expiry_date = str(product[13]) if len(product) > 13 and product[13] else "N/A"
        expiry_text = f"{screen.format_date(expiry_date)} | {expiry_alert.get('short_label', '--')}" if expiry_date != "N/A" else "Sem validade"
        if lot_count > 1 and selected_lot_position is not None:
            expiry_text = f"{expiry_text} | Lote {selected_lot_position}"
        elif lot_count > 1:
            expiry_text = f"{expiry_text} | {lot_count} lotes"
        self.expiry_label.text = expiry_text
        self.expiry_label.text_color = expiry_alert.get("color_rgba", text_secondary) if expiry_alert.get("is_alert") else text_secondary

        card_color = tokens.get("card_alt", [0.92, 0.95, 1, 1])
        for button, color in (
            (self.detail_button, info_color),
            (self.edit_button, success_color),
            (self.delete_button, danger_color),
        ):
            button.theme_text_color = "Custom"
            button.text_color = color
            button.md_bg_color = card_color
        self.detail_button.hint_text = "Ver lote selecionado" if lot_count > 1 and selected_lot_id is not None else "Ver detalhes"
        self.edit_button.hint_text = "Selecionar lote para editar" if lot_count > 1 and selected_lot_id is None else "Editar lote selecionado" if lot_count > 1 else "Editar produto"
        self.delete_button.hint_text = "Selecionar lote para eliminar" if lot_count > 1 and selected_lot_id is None else "Eliminar lote selecionado" if lot_count > 1 else "Eliminar produto"
        if getattr(screen, "_active_recycle_product_row", None) is self:
            self.set_hover(True)

    def set_hover(self, active):
        """Apply a small, row-level highlight without rebuilding child widgets."""
        active = bool(active)
        if self._hover_active == active:
            return
        self._hover_active = active
        accent = (self.palette.get("tokens", {}) or {}).get("primary", [0.15, 0.52, 0.76, 1])
        target = (
            AdminScreen._blend_rgba(self._base_bg_color, accent, 0.15)
            if active else self._base_bg_color
        )
        Animation.cancel_all(self, "md_bg_color")
        Animation(md_bg_color=target, d=0.10, t="out_quad").start(self)

    def on_touch_down(self, touch):
        """Clique nas colunas Produto / Stock / Preço / Validade → input na própria célula."""
        if not self.collide_point(*touch.pos) or getattr(touch, "is_mouse_scrolling", False):
            return super().on_touch_down(touch)
        if not self.admin_screen or not self.product_data:
            return super().on_touch_down(touch)
        if getattr(self, "_inline_field", None):
            # Já a editar — deixa o TextInput tratar o toque
            return super().on_touch_down(touch)
        try:
            for btn in (self.detail_button, self.edit_button, self.delete_button, self.sequence_button):
                if btn is not None and btn.opacity > 0 and btn.collide_point(*touch.pos):
                    return super().on_touch_down(touch)
        except Exception:
            pass
        width = float(self.width) or 1.0
        rel = (touch.x - self.x) / width
        fields = [None, "description", "stock", None, None, "price", None, "expiry", None]
        acc = 0.0
        for hint, field in zip(COL_HINTS, fields):
            acc += float(hint)
            if rel <= acc + 1e-6:
                if field:
                    self.start_inline_edit(field)
                    return True
                break
        return super().on_touch_down(touch)

    def start_inline_edit(self, field):
        """Substitui o label da coluna por um TextInput real na célula."""
        from kivy.uix.textinput import TextInput

        field = str(field or "").strip().lower()
        label_map = {
            "description": self.name_label,
            "stock": self.stock_label,
            "price": self.price_label,
            "expiry": self.expiry_label,
        }
        label = label_map.get(field)
        if label is None or not self.product_data:
            return
        parent = label.parent
        if parent is None:
            return

        # Multi-lote: exigir seleção
        try:
            lot_count = self.admin_screen._get_group_lot_count(self.product_data)
            selected_id = self.admin_screen._get_group_selected_lot_id(self.product_data)
            if lot_count > 1 and selected_id is None:
                self.admin_screen._open_group_lot_selector(
                    self.product_data, requested_action="edit"
                )
                self.admin_screen.show_snackbar("Selecione o lote antes de editar")
                return
        except Exception:
            selected_id = None

        # Valor atual
        product = self.product_data
        is_weight = bool(product[15]) if len(product) > 15 else False
        if field == "description":
            value = str(product[1] if len(product) > 1 else "")
        elif field == "stock":
            stock_v = float(product[2] if len(product) > 2 else 0)
            value = f"{stock_v:.2f}" if is_weight else str(int(stock_v))
        elif field == "price":
            value = f"{float(product[4] if len(product) > 4 else 0):.2f}"
        elif field == "expiry":
            raw = product[13] if len(product) > 13 else None
            if raw:
                try:
                    value = self.admin_screen.format_date(str(raw))
                except Exception:
                    value = str(raw)
            else:
                value = ""
        else:
            return

        # Cancelar edição anterior nesta linha
        self.cancel_inline_edit(restore=True)

        app = App.get_running_app()
        tokens = getattr(app, "theme_tokens", {}) if app else {}
        fg = tokens.get("text_primary", [0.95, 0.96, 0.98, 1])
        bg = tokens.get("surface_alt", [0.16, 0.18, 0.22, 1])
        accent = tokens.get("primary", [0.15, 0.55, 0.85, 1])

        ti = TextInput(
            text=value,
            multiline=False,
            font_size=sp(14),
            padding=[dp(6), dp(8)],
            foreground_color=fg,
            cursor_color=accent,
            # background_normal/active são caminhos de imagem (str), não cores
            background_normal="",
            background_active="",
            background_disabled_normal="",
            background_color=bg,
            write_tab=False,
            size_hint=(1, 1),
        )
        # Destaque visual da célula em edição
        try:
            parent.md_bg_color = (*accent[:3], 0.22)
        except Exception:
            pass

        # Esconder label, mostrar input
        label.opacity = 0
        label.disabled = True
        parent.add_widget(ti)
        self._inline_field = field
        self._inline_input = ti
        self._inline_label = label
        self._inline_parent = parent
        self._inline_product_id = selected_id or product[0]
        self._inline_is_weight = is_weight

        def _on_validate(*_a):
            self.commit_inline_edit()

        def _on_focus(instance, focused):
            if not focused:
                # Pequeno atraso para não conflitar com o clique noutro sítio
                Clock.schedule_once(lambda dt: self.commit_inline_edit(), 0.05)

        ti.bind(on_text_validate=_on_validate, focus=_on_focus)
        Clock.schedule_once(lambda *_: setattr(ti, "focus", True), 0)
        Clock.schedule_once(lambda *_: setattr(ti, "select_all", True) if hasattr(ti, "select_all") else None, 0.02)
        try:
            ti.select_text(0, len(ti.text or ""))
        except Exception:
            pass

    def cancel_inline_edit(self, restore=True):
        ti = getattr(self, "_inline_input", None)
        label = getattr(self, "_inline_label", None)
        parent = getattr(self, "_inline_parent", None)
        if ti is not None and parent is not None:
            try:
                parent.remove_widget(ti)
            except Exception:
                pass
        if label is not None:
            label.opacity = 1
            label.disabled = False
        if parent is not None:
            try:
                # restaurar fundo neutro (será reaplicado no próximo refresh)
                parent.md_bg_color = [0, 0, 0, 0]
            except Exception:
                pass
        self._inline_field = None
        self._inline_input = None
        self._inline_label = None
        self._inline_parent = None

    def commit_inline_edit(self):
        field = getattr(self, "_inline_field", None)
        ti = getattr(self, "_inline_input", None)
        if not field or ti is None or not self.admin_screen or not self.product_data:
            self.cancel_inline_edit()
            return
        value = (ti.text or "").strip()
        product_id = getattr(self, "_inline_product_id", None) or self.product_data[0]
        is_weight = bool(getattr(self, "_inline_is_weight", False))
        # Limpar UI primeiro para evitar loops de focus
        self.cancel_inline_edit(restore=True)
        self.admin_screen._apply_inline_product_edit(
            self.product_data, product_id, field, value, is_weight
        )


    def _select_lot(self, instance):
        if self.admin_screen and self.product_data:
            self.admin_screen._open_group_lot_selector(self.product_data, caller=instance, requested_action="select")

    def _show_details(self, _instance):
        if self.admin_screen and self.product_data:
            self.admin_screen._open_product_details(self.product_data)

    def _edit_product(self, instance):
        if not self.admin_screen or not self.product_data:
            return
        if self.admin_screen._get_group_lot_count(self.product_data) > 1 and self.admin_screen._get_group_selected_lot_id(self.product_data) is None:
            self.admin_screen._open_group_lot_selector(self.product_data, caller=instance, requested_action="edit")
            return
        self.admin_screen._open_product_editor(self.product_data)

    def _delete_product(self, instance):
        if not self.admin_screen or not self.product_data:
            return
        if self.admin_screen._get_group_lot_count(self.product_data) > 1 and self.admin_screen._get_group_selected_lot_id(self.product_data) is None:
            self.admin_screen._open_group_lot_selector(self.product_data, caller=instance, requested_action="delete")
            return
        self.admin_screen._prompt_delete_product(self.product_data[0])


class AdminScreen(Screen):
    LOSS_METRICS_LOOKBACK_DAYS = 365
    PRODUCTS_PAGE_SIZE = 7
    product_table = ObjectProperty(None)
    search_input = ObjectProperty(None)
    category_spinner = ObjectProperty(None)
    products = ListProperty([])
    shopping_list_busy = BooleanProperty(False)

    # -- Token para descartar resultados de filtros obsoletos ------------------
    _filter_token = 0

    def __init__(self, **kwargs):
        db = kwargs.pop("db", None)
        # ``on_kv_post`` runs inside the base constructor, so these values must
        # exist before Kivy builds the product table.
        self._recycle_hover_bound = False
        self._active_recycle_product_row = None
        self._selected_category = None
        super(AdminScreen, self).__init__(**kwargs)
        self.db = db or get_db()
        self.category_menu = None
        self._manual_categories = set()
        self._filter_ev = None
        self._pending_search = ""
        self._compact_layout = None  # "wide" | "medium" | "narrow"

        self.swing_event = None
        self.notification_count = 0
        self.recommendation_count = 0
        self.fraud_notification_count = 0
        self._products_load_token = 0
        self._products_loading = False
        self._pending_products_load = False
        self._products_loaded_once = False
        self._last_products_load_at = 0.0
        self._products_page_offset = 0
        self._products_has_more = False
        self._products_total_count = None
        self._active_products_token = 0
        self._queued_products_request = None
        self._search_ev = None
        self._catalog_categories = set()
        # Never use the translated caption as a database filter.  ``None`` is
        # the stable value for "all categories" in every UI language.
        self._categories_loading = False
        self._products_table_dirty = True
        self._resize_rebuild_ev = None
        self._product_form_preload_ev = None

        # -- Render de tabela em lotes ----------------------------------------
        self._table_render_ev = None
        self._table_render_token = 0
        self._pending_table_rows = deque()   # deque de (idx, product) aguardando render
        self._product_row_hover_handlers = []
        self._table_row_height = dp(56)
        self._table_palette = {}

        self._current_display = []
        self._current_filtered_products = []
        self._aggregated_products_cache = []
        self._product_search_index = {}
        self._product_page_index = 0
        self._display_ids_by_product_id = {}
        self._selected_lot_ids_by_catalog_key = {}
        self._alerts_refresh_token = 0
        self._ai_popup_token = 0
        self._async_actions = set()
        self._cached_admin_insights = {}
        self._expiry_alerts_by_id = {}
        self._last_expiry_summary_at = 0.0
        self._expiry_summary_cooldown = 120.0
        self.loss_report = None
        self.shopping_list_report = None
        self.pdf_viewer = None
        self._shopping_list_dialog = None
        self._shopping_list_payload = None
        self._loss_metrics_dialog = None
        self._loss_details_dialog = None
        self._lot_menu = None
        self._lot_selector_dialog = None
        self._ai_button_rest_pos = None
        self._keyboard_shortcuts_bound = False
        self._last_shortcut_signature = None
        self._last_shortcut_at = 0.0
        self._shortcut_help_dialog = None

        # -- Snackbar reutilizável ---------------------------------------------
        self._snackbar = None

        self._intelligence = None

        Window.bind(on_resize=self._on_window_resize)

    def _get_intelligence(self):
        if self._intelligence is None:
            from AI.controller import ProactiveIntelligenceController
            self._intelligence = ProactiveIntelligenceController(
                screen=self,
                db=self.db,
                history_title="Historico de avisos",
                banner_columns=1,
                auto_batch_size=2,
                auto_stagger_seconds=2.0,
                auto_present_enabled=True,
                auto_present_as_history=False,
            )
        return self._intelligence

    def on_kv_post(self, base_widget):
        self._update_responsive_layout()
        self._bind_recycle_product_hover()

    def _set_loading_overlay(self, key, active, message="", detail=""):
        """Não bloqueia a tela de produtos enquanto uma tarefa é executada."""
        return None

    def _clear_loading_overlay(self):
        return None

    def _is_current_screen(self):
        return bool(self.manager and self.manager.current == self.name)

    def _bind_recycle_product_hover(self):
        if getattr(self, "_recycle_hover_bound", False) or not self.product_table:
            return
        Window.bind(mouse_pos=self._on_recycle_product_table_mouse_pos)
        self._recycle_hover_bound = True

    def _unbind_recycle_product_hover(self):
        if getattr(self, "_recycle_hover_bound", False):
            Window.unbind(mouse_pos=self._on_recycle_product_table_mouse_pos)
        self._recycle_hover_bound = False
        self._set_active_recycle_product_row(None)

    def _set_active_recycle_product_row(self, row):
        if getattr(self, "_active_recycle_product_row", None) is row:
            return
        previous = getattr(self, "_active_recycle_product_row", None)
        self._active_recycle_product_row = row
        if previous is not None:
            previous.set_hover(False)
        if row is not None:
            row.set_hover(True)

    def _on_recycle_product_table_mouse_pos(self, _window, pos):
        if not self._is_current_screen() or not self.product_table:
            self._set_active_recycle_product_row(None)
            return
        layout = getattr(self.product_table, "layout_manager", None)
        if layout is None:
            return
        try:
            local_pos = layout.to_widget(*pos)
        except Exception:
            self._set_active_recycle_product_row(None)
            return
        hovered = next(
            (
                child for child in list(getattr(layout, "children", []) or [])
                if isinstance(child, RecycleAdminProductRow) and child.collide_point(*local_pos)
            ),
            None,
        )
        self._set_active_recycle_product_row(hovered)

    def _cancel_clock_event_attr(self, attr_name):
        event = getattr(self, attr_name, None)
        if event is None:
            return False
        try:
            event.cancel()
        except Exception:
            try:
                Clock.unschedule(event)
            except Exception:
                pass
        setattr(self, attr_name, None)
        return True

    def _cancel_enter_events(self):
        for attr_name in (
            "_resize_rebuild_ev",
            "_product_form_preload_ev",
        ):
            self._cancel_clock_event_attr(attr_name)

    def _schedule_product_form_preload(self, delay=0.05):
        if _PRODUCT_FORM_CLASS is not None:
            return
        if self._product_form_preload_ev is not None:
            return
        self._product_form_preload_ev = Clock.schedule_once(self._preload_product_form_class, delay)

    def _preload_product_form_class(self, *_args):
        self._product_form_preload_ev = None
        _get_product_form_class()

    def _bind_keyboard_shortcuts(self):
        if self._keyboard_shortcuts_bound:
            return
        Window.bind(on_keyboard=self._handle_window_keyboard)
        Window.bind(on_key_down=self._handle_window_key_down)
        self._keyboard_shortcuts_bound = True

    def _unbind_keyboard_shortcuts(self):
        if not self._keyboard_shortcuts_bound:
            return
        Window.unbind(on_keyboard=self._handle_window_keyboard)
        Window.unbind(on_key_down=self._handle_window_key_down)
        self._keyboard_shortcuts_bound = False

    def _has_open_modal(self):
        return any(isinstance(child, ModalView) for child in Window.children)

    @staticmethod
    def _normalize_key_name(key, codepoint=""):
        if isinstance(key, (tuple, list)):
            numeric_key = key[0] if len(key) > 0 else None
            string_key = str(key[1] or "").strip().lower() if len(key) > 1 else ""
            if string_key:
                return string_key
            key = numeric_key

        if isinstance(key, str):
            key_name = key.strip().lower()
            if key_name:
                return key_name

        key_name = str(codepoint or "").strip().lower()
        if key_name:
            return key_name

        special_keys = {
            13: "enter",
            27: "escape",
            271: "enter",
        }
        if key in special_keys:
            return special_keys[key]

        try:
            if 32 <= int(key) <= 126:
                return chr(int(key)).lower()
        except Exception:
            pass
        return ""

    def _should_skip_duplicate_shortcut(self, signature):
        now = time.perf_counter()
        if signature == self._last_shortcut_signature and (now - self._last_shortcut_at) < 0.20:
            return True
        self._last_shortcut_signature = signature
        self._last_shortcut_at = now
        return False

    def _focus_text_field(self, field_id, select_all=False):
        if not self.ids:
            return False
        field = self.ids.get(field_id)
        if field is None or getattr(field, "disabled", False):
            return False
        field.focus = True
        if select_all and hasattr(field, "select_all"):
            Clock.schedule_once(lambda _dt, widget=field: widget.select_all(), 0)
        return True

    def _dismiss_dialog_attribute(self, attr_name):
        dialog = getattr(self, attr_name, None)
        if dialog is None:
            return False
        try:
            dialog.dismiss()
        except Exception:
            pass
        setattr(self, attr_name, None)
        return True

    def _close_transient_panels(self):
        if self._dismiss_lot_menu():
            return True
        if self.category_menu:
            try:
                self.category_menu.dismiss()
            except Exception:
                pass
            self.category_menu = None
            return True
        for attr_name in (
            "_lot_selector_dialog",
            "dialog",
            "_shopping_list_dialog",
            "_loss_metrics_dialog",
            "_loss_details_dialog",
            "_shortcut_help_dialog",
        ):
            if self._dismiss_dialog_attribute(attr_name):
                return True
        return False

    def _show_keyboard_shortcuts(self):
        dialog = self._shortcut_help_dialog
        if dialog is None:
            help_text = (
                "/ ou Ctrl+F: focar pesquisa\n"
                "Ctrl+L: limpar pesquisa\n"
                "Ctrl+R: atualizar lista\n"
                "Ctrl+N: adicionar produto\n"
                "Ctrl+H: ver atalhos\n"
                "Alt+C: abrir categorias\n"
                "Alt+F: alternar filtro KG/unidade/todos\n"
                "Alt+1: pagina inicial\n"
                "Esc: fechar menus, dialogs e paineis"
            )
            dialog = MDDialog(
                title="Atalhos do Admin",
                text=help_text,
                buttons=[MDFlatButton(text="Fechar")],
            )
            if dialog.buttons:
                dialog.buttons[0].bind(on_release=lambda *_: dialog.dismiss())
            dialog.bind(on_dismiss=lambda *_: setattr(self, "_shortcut_help_dialog", None))
            self._shortcut_help_dialog = dialog
        dialog.open()

    def _dispatch_keyboard_shortcut(self, key, codepoint="", modifiers=None):
        if not self.manager or self.manager.current != self.name:
            return False

        key_name = self._normalize_key_name(key, codepoint)
        modifiers = {str(modifier or "").lower() for modifier in (modifiers or [])}
        signature = (key_name, tuple(sorted(modifiers)))
        if self._should_skip_duplicate_shortcut(signature):
            return False

        if key_name == "escape" and self._close_transient_panels():
            return True
        if self._has_open_modal():
            return False

        if not modifiers and key_name == "/":
            search_field = self.ids.get("search_input") if self.ids else None
            if search_field is not None and getattr(search_field, "focus", False):
                return False
            return self._focus_text_field("search_input", select_all=True)
        if "ctrl" in modifiers and key_name == "f":
            return self._focus_text_field("search_input", select_all=True)
        if "ctrl" in modifiers and key_name == "l":
            self.clear_search()
            return True
        if "ctrl" in modifiers and key_name == "r":
            self.refresh_products_panel()
            return True
        if "ctrl" in modifiers and key_name == "n":
            self.add_product()
            return True
        if "ctrl" in modifiers and key_name == "h":
            self._show_keyboard_shortcuts()
            return True
        if "alt" in modifiers and key_name == "c":
            button = self.ids.get("category_spinner") if self.ids else None
            if button is None:
                return False
            self.show_category_menu(button)
            return True
        if "alt" in modifiers and key_name == "f":
            self.toggle_kg_products()
            return True
        if "alt" in modifiers and key_name == "1":
            self.go_home()
            return True
        return False

    def _handle_window_keyboard(self, _window, key, scancode=None, codepoint=None, modifiers=None):
        return self._dispatch_keyboard_shortcut(
            key,
            codepoint=codepoint or "",
            modifiers=modifiers or [],
        )

    def _handle_window_key_down(self, _window, key, scancode=None, codepoint=None, modifiers=None):
        return self._dispatch_keyboard_shortcut(
            key,
            codepoint=codepoint or "",
            modifiers=modifiers or [],
        )

    def _run_async_action(self, key, task, on_success=None, busy_message=None, error_message=None):
        action_key = str(key or "")
        if action_key and action_key in self._async_actions:
            return False
        if action_key:
            self._async_actions.add(action_key)
        if busy_message:
            self.show_snackbar(busy_message)
        self._set_loading_overlay(
            action_key or "admin_task",
            True,
            busy_message or "A processar operacao do admin...",
            "A preparar dados.",
        )

        def worker():
            result = None
            error = None
            try:
                result = task()
            except Exception as exc:
                error = exc
            Clock.schedule_once(
                lambda dt, res=result, err=error, action=action_key: self._finish_async_action(
                    action,
                    res,
                    err,
                    on_success,
                    error_message,
                ),
                0,
            )

        Thread(target=worker, daemon=True).start()
        return True

    def _finish_async_action(self, key, result, error, on_success, error_message):
        self._set_loading_overlay(key or "admin_task", False)
        if key:
            self._async_actions.discard(key)
        if error is not None:
            print(f"Erro em acao assincrona ({key}): {error}")
            if error_message:
                self.show_snackbar(error_message)
            return
        if callable(on_success):
            on_success(result)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def _on_window_resize(self, instance, width, height):
        if not self._is_current_screen():
            self._products_table_dirty = True
            return
        self._update_responsive_layout(width)
        self._cancel_clock_event_attr("_resize_rebuild_ev")
        self._resize_rebuild_ev = Clock.schedule_once(self._deferred_rebuild, 0.15)

    def _deferred_rebuild(self, dt):
        self._resize_rebuild_ev = None
        if not self._is_current_screen():
            self._products_table_dirty = True
            return
        self._render_current_product_page()

    def _tr(self, text):
        app = App.get_running_app()
        return translate_text(text, getattr(app, "language", "pt"))

    def _all_categories_label(self):
        return self._tr("Todas as Categorias")

    def apply_translations(self):
        """Refresh product-screen labels without changing product filters."""
        if not self.ids:
            return
        self._compact_layout = None
        self._update_responsive_layout()
        text_values = {
            "header_bar": ("title", "Gestao de produtos"),
            "search_input": ("hint_text", "Pesquisar produto..."),
            "refresh_btn": ("tooltip_text", "Atualizar lista de produtos (Ctrl+R)"),
            "add_btn": ("tooltip_text", "Adicionar produto (Ctrl+N)"),
            "archived_btn": ("tooltip_text", "Consultar e restaurar produtos arquivados"),
            "shopping_list_btn": ("tooltip_text", "Ver sugestões de compras com IA"),
            "inventory_btn": ("tooltip_text", "Iniciar ou continuar inventario fisico"),
        }
        for widget_id, (attribute, source) in text_values.items():
            widget = self.ids.get(widget_id)
            if widget is not None:
                setattr(widget, attribute, self._tr(source))
        if self.category_spinner is not None:
            self.category_spinner.text = self._selected_category or self._all_categories_label()
        # A request started by an earlier version could have used the visible
        # caption (for example "All Categories") as its SQL category.  Reload
        # from the stable internal selection after a language switch.
        if self._is_current_screen() and self._products_loaded_once:
            Clock.schedule_once(
                lambda _dt: self._request_products_page(
                    reset=False,
                    search_text=self._current_search_text(),
                    offset=self._products_page_offset,
                    force=True,
                ),
                0,
            )

    def _update_responsive_layout(self, width=None):
        """Adapta a barra de ferramentas e a tabela a diferentes larguras.

        Breakpoints (com estrutura de 2 linhas no KV):
          - wide     (>= 1100): textos completos
          - medium   (820-1099): textos curtos
          - narrow   (< 820): textos mínimos / prioridade a ícones
        """
        if not self.ids:
            return
        width = float(width or Window.width or 0)

        if width >= dp(1100):
            mode = "wide"
        elif width >= dp(820):
            mode = "medium"
        else:
            mode = "narrow"

        if mode == getattr(self, "_compact_layout", None):
            return
        self._compact_layout = mode

        toolbar_card = self.ids.get("toolbar_card")
        search_row = self.ids.get("toolbar_search_row")
        actions_row = self.ids.get("toolbar_actions_row")
        search_input = self.ids.get("search_input")
        category_spinner = self.ids.get("category_spinner")
        filter_btn = self.ids.get("filter_btn")
        refresh_btn = self.ids.get("refresh_btn")
        add_btn = self.ids.get("add_btn")
        archived_btn = self.ids.get("archived_btn")
        shopping_list_btn = self.ids.get("shopping_list_btn")
        inventory_btn = self.ids.get("inventory_btn")

        if not toolbar_card:
            return

        label_map = {
            "wide": {
                "category": "Todas as Categorias", "refresh": "Atualizar", "add": "Adicionar",
                "archived": "Arquivados", "shopping": "Sugestões de Compras", "inventory": "Inventário",
            },
            "medium": {
                "category": "Categorias",
                "refresh": "Atualizar",
                "add": "Adicionar",
                "archived": "Arquivados",
                "shopping": "Compras",
                "inventory": "Inventário",
            },
            "narrow": {
                "category": "Categorias",
                "refresh": "Atualizar",
                "add": "Novo",
                "archived": "Arquivo",
                "shopping": "Compras",
                "inventory": "Stock",
            },
        }
        labels = label_map[mode]

        def _set_text(widget, value):
            if widget is None:
                return
            try:
                widget.text = value
            except Exception:
                pass

        _set_text(category_spinner, self._selected_category or self._tr(labels["category"]))
        _set_text(refresh_btn, self._tr(labels["refresh"]))
        _set_text(add_btn, self._tr(labels["add"]))
        _set_text(archived_btn, self._tr(labels["archived"]))
        _set_text(shopping_list_btn, self._tr(labels["shopping"]))
        _set_text(inventory_btn, self._tr(labels["inventory"]))
        if filter_btn is not None:
            try:
                filter_btn.text = ""
            except Exception:
                pass

        row_h = dp(46)
        gap = dp(8)
        pad_y = dp(10) * 2

        if search_row is not None:
            search_row.height = row_h
            search_row.spacing = dp(8)
        if actions_row is not None:
            actions_row.height = row_h
            actions_row.spacing = dp(6 if mode == "narrow" else 8)

        # Proporções da linha de pesquisa
        if search_input is not None:
            search_input.size_hint_x = 0.58 if mode == "wide" else (0.55 if mode == "medium" else 0.50)
        if category_spinner is not None:
            category_spinner.size_hint_x = 0.32 if mode == "wide" else (0.35 if mode == "medium" else 0.38)
        if filter_btn is not None:
            filter_btn.size_hint_x = None
            filter_btn.width = dp(46)

        # Proporções da linha de ações (somam ~1.0)
        if mode == "wide":
            hints = (0.16, 0.16, 0.16, 0.30, 0.18)
        elif mode == "medium":
            hints = (0.18, 0.18, 0.18, 0.24, 0.18)
        else:
            hints = (0.20, 0.18, 0.18, 0.22, 0.18)

        for btn, hint in zip(
            (refresh_btn, add_btn, archived_btn, shopping_list_btn, inventory_btn),
            hints,
        ):
            if btn is None:
                continue
            btn.size_hint_x = hint
            btn.size_hint_y = None
            btn.height = row_h

        toolbar_card.padding = [
            dp(14 if mode != "narrow" else 10),
            dp(10 if mode != "narrow" else 8),
        ]
        toolbar_card.size_hint_y = None
        toolbar_card.height = row_h * 2 + gap + pad_y

        # Tabela: largura mínima + scroll horizontal
        table_scroll_content = self.ids.get("table_scroll_content")
        if table_scroll_content is not None:
            min_table_w = {
                "wide": dp(980),
                "medium": dp(920),
                "narrow": dp(860),
            }[mode]
            try:
                table_scroll_content.width = max(float(self.width or 0), float(min_table_w))
            except Exception:
                pass

        # Paginação compacta em ecrãs estreitos
        prev_btn = self.ids.get("admin_prev_btn")
        next_btn = self.ids.get("admin_next_btn")
        page_label = self.ids.get("admin_page_label")
        if mode == "narrow":
            if prev_btn is not None:
                prev_btn.width = dp(108)
                _set_text(prev_btn, self._tr("Ant."))
            if next_btn is not None:
                next_btn.width = dp(108)
                _set_text(next_btn, self._tr("Seg."))
            if page_label is not None:
                page_label.width = dp(150)
        else:
            if prev_btn is not None:
                prev_btn.width = dp(130)
                _set_text(prev_btn, self._tr("Anterior"))
            if next_btn is not None:
                next_btn.width = dp(130)
                _set_text(next_btn, self._tr("Seguinte"))
            if page_label is not None:
                page_label.width = dp(204)

    # ------------------------------------------------------------------
    # Sistema de Notificações e Animação de Abanar
    # ------------------------------------------------------------------
    def _init_badge(self, dt):
        if not self._is_current_screen():
            return
        for badge_id in (
            'ai_badge',
            'recommendations_badge',
            'fraud_alerts_badge',
            'loss_metrics_badge',
        ):
            badge = self.ids.get(badge_id)
            if badge is not None:
                badge.opacity = 1
                badge_size = dp(22) if badge_id in ('fraud_alerts_badge', 'loss_metrics_badge') else dp(26)
                badge.size = (badge_size, badge_size)

    def add_notification(self):
        self.notification_count += 1
        self.update_notification_badge(self.notification_count)

    def clear_notifications(self):
        self.notification_count = 0
        self.update_notification_badge(0)

    def update_notification_badge(self, count):
        self.notification_count = max(0, int(count or 0))

        if not hasattr(self.ids, 'ai_badge') or not hasattr(self.ids, 'ai_badge_label'):
            return

        self.ids.ai_badge_label.text = str(self.notification_count)

        if self.notification_count > 0:
            self._show_badge()
            set_attention_shake(self.ids.get('ai_button'), True)
        else:
            self.ids.ai_badge.opacity = 1
            self.ids.ai_badge.size = (dp(26), dp(26))
            set_attention_shake(self.ids.get('ai_button'), False)

    def update_recommendation_badge(self, count):
        self.recommendation_count = max(0, int(count or 0))
        badge = self.ids.get('recommendations_badge') if hasattr(self, 'ids') else None
        label = self.ids.get('recommendations_badge_label') if hasattr(self, 'ids') else None
        if badge is None or label is None:
            return
        label.text = str(self.recommendation_count)
        Animation.cancel_all(badge)
        if self.recommendation_count > 0:
            badge.opacity = 1
            badge.size = (dp(0), dp(0))
            Animation(size=(dp(26), dp(26)), duration=0.25, transition='out_back').start(badge)
            set_attention_shake(self.ids.get('recommendations_button'), True)
            return
        badge.opacity = 1
        badge.size = (dp(26), dp(26))
        set_attention_shake(self.ids.get('recommendations_button'), False)

    def update_loss_alert_badges(self, count):
        """Mostra o total atual de alertas de fraude nos dois atalhos de perdas."""
        self.fraud_notification_count = max(0, int(count or 0))
        if not hasattr(self, 'ids'):
            return

        for badge_id, label_id, button_id in (
            ('fraud_alerts_badge', 'fraud_alerts_badge_label', 'fraud_alerts_button'),
            ('loss_metrics_badge', 'loss_metrics_badge_label', 'loss_metrics_button'),
        ):
            badge = self.ids.get(badge_id)
            label = self.ids.get(label_id)
            if badge is None or label is None:
                continue
            label.text = str(self.fraud_notification_count)
            Animation.cancel_all(badge)
            badge.opacity = 1
            if self.fraud_notification_count > 0:
                badge.size = (dp(0), dp(0))
                Animation(
                    size=(dp(22), dp(22)),
                    duration=0.25,
                    transition='out_back',
                ).start(badge)
                set_attention_shake(self.ids.get(button_id), True)
            else:
                badge.size = (dp(22), dp(22))
                set_attention_shake(self.ids.get(button_id), False)

    def _show_badge(self):
        if not hasattr(self.ids, 'ai_badge'):
            return

        self.ids.ai_badge.size = (dp(0), dp(0))
        self.ids.ai_badge.opacity = 1

        anim = Animation(
            size=(dp(26), dp(26)),
            duration=0.3,
            transition='out_back'
        )
        anim.start(self.ids.ai_badge)

    def _hide_badge(self):
        if not hasattr(self.ids, 'ai_badge'):
            return

        anim = Animation(
            opacity=0,
            size=(dp(0), dp(0)),
            duration=0.2
        )
        anim.start(self.ids.ai_badge)

    def _start_swing_animation(self):
        if not hasattr(self.ids, 'ai_button'):
            return

        self._stop_swing_animation()

        # -- CORRECAO: Animation reutilizada — criada uma única vez -----------
        def swing_cycle(dt):
            if self.notification_count <= 0:
                return False
            button = self.ids.ai_button
            bx, by = button.pos
            self._ai_button_rest_pos = (bx, by)
            d = dp(4)

            swing = (
                Animation(pos=(bx + d,     by + d),     duration=0.15, transition='out_sine') +
                Animation(pos=(bx - d,     by - d*0.75),duration=0.30, transition='in_out_sine') +
                Animation(pos=(bx + d*0.75,by + d*0.5), duration=0.25, transition='in_out_sine') +
                Animation(pos=(bx - d*0.75,by - d*0.5), duration=0.25, transition='in_out_sine') +
                Animation(pos=(bx + d*0.5, by + d*0.25),duration=0.20, transition='out_sine') +
                Animation(pos=(bx - d*0.5, by - d*0.25),duration=0.20, transition='in_out_sine') +
                Animation(pos=(bx, by),                  duration=0.15, transition='out_sine')
            )
            swing.start(button)
            return True

        self.swing_event = Clock.schedule_interval(swing_cycle, 2.5)
        swing_cycle(0)

    def _stop_swing_animation(self):
        if hasattr(self, 'swing_event') and self.swing_event:
            self.swing_event.cancel()
            self.swing_event = None

        if hasattr(self.ids, 'ai_button'):
            button = self.ids.ai_button
            Animation.cancel_all(button)
            if self._ai_button_rest_pos:
                Animation(
                    pos=self._ai_button_rest_pos,
                    duration=0.2,
                    transition='out_sine'
                ).start(button)

    def _format_money(self, value):
        return format_money(value, currency="MZN")

    def _loss_type_label(self, code):
        return LOSS_LABELS.get(str(code or "").upper(), str(code or "Sem tipo"))

    def _bind_wrapped_label_height(self, label, min_height=None):
        min_height = dp(18) if min_height is None else min_height

        def _sync(*_args):
            label.text_size = (max(float(label.width or 0), 1.0), None)
            try:
                label.texture_update()
            except Exception:
                pass
            label.height = max(float(min_height), float(label.texture_size[1] or 0))

        label.bind(width=_sync, text=_sync)
        Clock.schedule_once(lambda _dt: _sync(), 0)
        return label

    def _build_bounded_scroll(self, content, max_height_ratio=0.58, max_height_dp=560, min_height_dp=180):
        from kivy.uix.scrollview import ScrollView

        max_height = min(float(Window.height or dp(max_height_dp)) * float(max_height_ratio), dp(max_height_dp))
        max_height = max(max_height, dp(min_height_dp))
        scroll = ScrollView(
            do_scroll_x=False,
            do_scroll_y=True,
            bar_width=dp(6),
            size_hint=(1, None),
            height=max_height,
        )
        content.size_hint_x = None

        def _sync(*_args):
            content.width = max(float(scroll.width or 0) - dp(4), dp(260))
            content.height = max(float(content.minimum_height or 0), dp(1))
            target_height = min(max(content.height + dp(4), dp(min_height_dp)), max_height)
            scroll.height = target_height
            scroll.do_scroll_y = content.height > target_height + dp(2)
            scroll.bar_width = dp(6) if scroll.do_scroll_y else 0

        content.bind(minimum_height=_sync)
        scroll.bind(width=_sync)
        scroll.add_widget(content)
        Clock.schedule_once(lambda _dt: _sync(), 0)
        return scroll

    def _get_banner_target(self):
        if not hasattr(self, "ids") or "ai_banner_container" not in self.ids:
            return None
        target = self.ids.ai_banner_container
        ensure_center = getattr(self._get_intelligence(), "_ensure_banner_center", None)
        if callable(ensure_center):
            try:
                target = ensure_center()
            except Exception:
                target = self.ids.ai_banner_container
        return target

    def _render_status_banners(self, banners, auto_dismiss_seconds=None):
        banners = [banner for banner in list(banners or []) if banner]
        if not banners:
            return False
        target = self._get_banner_target()
        if target is None:
            return False
        *_, render_auto_banners = _get_ai_popup_helpers()
        render_auto_banners(
            target,
            banners,
            insights=None,
            auto_dismiss_seconds=auto_dismiss_seconds,
            show_timer=False,
        )
        return True

    def _severity_label(self, severity):
        try:
            severity = int(severity or 0)
        except Exception:
            severity = 0
        return {3: "ALTO", 2: "MEDIO", 1: "BAIXO"}.get(severity, "INFO")

    def _build_fraud_alerts_banner(self, alerts, days_lookback=30):
        alerts = list(alerts or [])
        if not alerts:
            return {
                "kind": "fraud_ok",
                "variant": "success",
                "icon": "shield-check-outline",
                "bg_color": (0.74, 0.92, 0.78, 1),
                "title": "Sem alertas de fraude",
                "messages": [
                    f"Nenhum padrao suspeito encontrado nos ultimos {int(days_lookback)} dias.",
                    "Sem perdas acima do limite definido.",
                ],
                "all_messages": [],
                "count": 0,
                "urgency": 999,
                "details_sections": [
                    ("Estado atual", ["Nao ha alertas para rever neste periodo."]),
                ],
            }

        sorted_alerts = sorted(
            alerts,
            key=lambda item: int(item.get("severity") or 0),
            reverse=True,
        )
        high_count = sum(1 for item in sorted_alerts if int(item.get("severity") or 0) == 3)
        medium_count = sum(1 for item in sorted_alerts if int(item.get("severity") or 0) == 2)
        low_count = sum(1 for item in sorted_alerts if int(item.get("severity") or 0) == 1)
        max_severity = int(sorted_alerts[0].get("severity") or 0)
        variant = "danger" if max_severity >= 3 else "warning" if max_severity == 2 else "info"
        icon = "shield-alert-outline" if max_severity >= 3 else "shield-search-outline"

        messages = []
        detail_lines = []
        for alert in sorted_alerts[:10]:
            label = self._severity_label(alert.get("severity"))
            title = str(alert.get("title") or alert.get("alert_type") or "Alerta")
            description = str(alert.get("description") or "").strip()
            user = str(alert.get("related_user") or "").strip()
            messages.append(f"{label}: {title}")
            detail = f"{label} - {title}"
            if description:
                detail += f": {description}"
            if user:
                detail += f" | Utilizador: {user}"
            detail_lines.append(detail)
        if len(sorted_alerts) > len(detail_lines):
            detail_lines.append(f"Mais {len(sorted_alerts) - len(detail_lines)} alerta(s) no periodo.")

        return {
            "kind": "fraud",
            "variant": variant,
            "icon": icon,
            "bg_color": (0.93, 0.34, 0.34, 1) if variant == "danger" else (0.98, 0.76, 0.34, 1),
            "title": "Alertas de fraude",
            "messages": messages[:5],
            "all_messages": messages,
            "count": len(sorted_alerts),
            "urgency": 0 if max_severity >= 3 else 10 if max_severity == 2 else 30,
            "details_sections": [
                (
                    "Resumo",
                    [
                        f"Alta prioridade: {high_count}",
                        f"Media prioridade: {medium_count}",
                        f"Baixa prioridade: {low_count}",
                    ],
                ),
                ("Alertas encontrados", detail_lines),
            ],
        }

    def _build_pending_approvals_banner(self, pending):
        pending = list(pending or [])
        if not pending:
            return {
                "kind": "approval_ok",
                "variant": "success",
                "icon": "clipboard-check-outline",
                "bg_color": (0.74, 0.92, 0.78, 1),
                "title": "Aprovacoes em dia",
                "messages": [
                    "Nao existem perdas pendentes de aprovacao.",
                    "Os movimentos registados nao exigem validacao administrativa neste momento.",
                ],
                "all_messages": [],
                "count": 0,
                "urgency": 999,
                "details_sections": [
                    ("Estado atual", ["Fila de aprovacoes pendentes vazia."]),
                ],
            }

        messages = []
        detail_lines = []
        for row in pending[:10]:
            values = list(row) + [""] * 14
            mov_id, _prod_id, description, mov_type, qty, unit, cost, _price, reason, _note, evidence, created_at, user, role = values[:14]
            product_name = str(description or "Produto")
            cost_text = self._format_money(cost)
            messages.append(f"#{mov_id} {product_name}: {qty} {unit or 'un'} | {cost_text}")
            detail_lines.append(
                f"#{mov_id} {mov_type}: {product_name}, {qty} {unit or 'un'}, {cost_text}, por {user or 'sistema'} ({role or 'sem perfil'}), {created_at or 'sem data'}, {'com evidencia' if evidence else 'sem evidencia'}, motivo: {str(reason or 'nao informado')}"
            )
        if len(pending) > len(detail_lines):
            detail_lines.append(f"Mais {len(pending) - len(detail_lines)} aprovacao(oes) pendente(s).")

        variant = "danger" if len(pending) >= 5 else "warning"
        return {
            "kind": "approvals",
            "variant": variant,
            "icon": "clipboard-alert-outline",
            "bg_color": (0.93, 0.34, 0.34, 1) if variant == "danger" else (0.98, 0.76, 0.34, 1),
            "title": "Aprovacoes pendentes",
            "messages": messages[:5],
            "all_messages": messages,
            "count": len(pending),
            "urgency": 5 if variant == "danger" else 15,
            "details_sections": [
                ("Movimentos aguardando decisao", detail_lines),
            ],
        }

    def _ensure_loss_report(self):
        if self.loss_report is None:
            from pdfs.loss_report import LossReport
            self.loss_report = LossReport()
        return self.loss_report

    def _ensure_shopping_list_report(self):
        if self.shopping_list_report is None:
            from pdfs.shopping_list_report import ShoppingListReport
            self.shopping_list_report = ShoppingListReport()
        return self.shopping_list_report

    def _ensure_pdf_viewer(self):
        if self.pdf_viewer is None:
            from pdfs.pdf_viewer import PDFViewer
            self.pdf_viewer = PDFViewer(
                error_callback=lambda msg: self.show_snackbar(str(msg))
            )
        return self.pdf_viewer

    def _get_default_loss_metrics_period(self, end_date=None):
        end_date = end_date or datetime.now()
        start_date = end_date - timedelta(days=self.LOSS_METRICS_LOOKBACK_DAYS)
        return start_date, end_date

    def _build_loss_metric_card(self, title, value, subtitle, icon_name, tone):
        app = App.get_running_app()
        tokens = getattr(app, "theme_tokens", {}) if app else {}
        tone_color = tokens.get(
            tone,
            tokens.get("info", [0.15, 0.45, 0.75, 1]),
        )

        card = MDCard(
            orientation="vertical",
            size_hint_y=None,
            height=dp(98),
            padding=dp(12),
            spacing=dp(5),
            radius=[dp(8)],
            elevation=0,
            md_bg_color=tokens.get("card_alt", [0.96, 0.97, 0.99, 1]),
        )

        header = MDBoxLayout(
            size_hint_y=None,
            height=dp(22),
            spacing=dp(8),
        )
        header.add_widget(
            MDIcon(
                icon=icon_name,
                theme_text_color="Custom",
                text_color=tone_color,
                size_hint=(None, None),
                size=(dp(18), dp(18)),
            )
        )
        header.add_widget(
            MDLabel(
                text=title,
                font_style="Caption",
                theme_text_color="Secondary",
                shorten=True,
                shorten_from="right",
            )
        )
        card.add_widget(header)
        card.add_widget(
            MDLabel(
                text=value,
                font_style="H6",
                bold=True,
                theme_text_color="Custom",
                text_color=tokens.get("text_primary", [0.12, 0.18, 0.26, 1]),
            )
        )
        card.add_widget(
            MDLabel(
                text=subtitle,
                font_size=dp(10.5),
                theme_text_color="Secondary",
                shorten=True,
                shorten_from="right",
            )
        )
        return card

    def _build_loss_section_card(self, title, lines, icon_name="text-box-outline", tone="info"):
        app = App.get_running_app()
        tokens = getattr(app, "theme_tokens", {}) if app else {}
        tone_color = tokens.get(
            tone,
            tokens.get("info", [0.15, 0.45, 0.75, 1]),
        )

        card = MDCard(
            orientation="vertical",
            size_hint_y=None,
            padding=dp(14),
            spacing=dp(8),
            radius=[dp(8)],
            elevation=0,
            md_bg_color=tokens.get("card", [1, 1, 1, 1]),
        )
        card.bind(minimum_height=card.setter("height"))

        header = MDBoxLayout(
            size_hint_y=None,
            height=dp(24),
            spacing=dp(8),
        )
        header.add_widget(
            MDIcon(
                icon=icon_name,
                theme_text_color="Custom",
                text_color=tone_color,
                size_hint=(None, None),
                size=(dp(18), dp(18)),
            )
        )
        header.add_widget(
            MDLabel(
                text=title,
                bold=True,
                font_style="Subtitle1",
                theme_text_color="Primary",
            )
        )
        card.add_widget(header)

        section_lines = list(lines or []) or ["Sem dados nesta secao."]
        for line in section_lines:
            item = MDLabel(
                text=str(line),
                size_hint_y=None,
                font_size=dp(11.5),
                theme_text_color="Secondary",
                halign="left",
                valign="top",
            )
            self._bind_wrapped_label_height(item, min_height=dp(18))
            card.add_widget(item)

        return card

    def _build_loss_metrics_content(self, metrics, start_date, end_date, detailed=False):
        content = MDBoxLayout(
            orientation="vertical",
            padding=dp(6),
            spacing=dp(12),
            size_hint_y=None,
        )
        content.bind(minimum_height=content.setter("height"))

        header_lines = [
            f"Periodo analisado: {start_date.strftime('%d/%m/%Y')} ate {end_date.strftime('%d/%m/%Y')}",
            f"{int(metrics.get('loss_count') or 0)} perdas registadas com impacto total de {self._format_money(metrics.get('total_cost'))}.",
        ]
        if metrics.get("total_sales", 0):
            header_lines.append(
                f"As perdas representam {float(metrics.get('loss_percentage') or 0):.2f}% das vendas do periodo."
            )
        loss_count = int(metrics.get("loss_count") or 0)
        content.add_widget(
            self._build_loss_section_card(
                "Resumo Executivo",
                header_lines,
                icon_name="chart-areaspline",
                tone="info" if loss_count else "success",
            )
        )

        if loss_count <= 0:
            content.add_widget(
                self._build_loss_section_card(
                    "Sem perdas aprovadas no periodo",
                    [
                        "Nao foram encontradas perdas aprovadas e aplicadas para entrar nas metricas.",
                        "Perdas pendentes, rejeitadas ou removidas nao entram neste painel de impacto financeiro.",
                        "Use Aprovacoes Pendentes para validar perdas em aberto ou Historico de Perdas para rever registos.",
                    ],
                    icon_name="shield-check-outline",
                    tone="success",
                )
            )
            return self._build_bounded_scroll(content, max_height_ratio=0.44, max_height_dp=420, min_height_dp=220)

        metrics_grid = MDGridLayout(
            cols=1 if Window.width < dp(740) else 2 if Window.width < dp(1280) else 3,
            spacing=dp(10),
            size_hint_y=None,
        )
        metrics_grid.bind(minimum_height=metrics_grid.setter("height"))

        metrics_grid.add_widget(
            self._build_loss_metric_card(
                "Eventos de perda",
                str(int(metrics.get("loss_count") or 0)),
                "Ocorrencias aprovadas no periodo",
                "package-variant-closed-remove",
                "warning",
            )
        )
        metrics_grid.add_widget(
            self._build_loss_metric_card(
                "Custo total",
                self._format_money(metrics.get("total_cost")),
                "Valor de custo absorvido pelas perdas",
                "cash-remove",
                "danger",
            )
        )
        metrics_grid.add_widget(
            self._build_loss_metric_card(
                "Receita perdida",
                self._format_money(metrics.get("total_revenue_lost")),
                "Quanto deixamos de faturar",
                "trending-down",
                "warning",
            )
        )
        metrics_grid.add_widget(
            self._build_loss_metric_card(
                "Lucro perdido",
                self._format_money(metrics.get("total_profit_lost")),
                "Impacto estimado na margem",
                "chart-waterfall",
                "danger",
            )
        )
        metrics_grid.add_widget(
            self._build_loss_metric_card(
                "Perdas vs vendas",
                f"{float(metrics.get('loss_percentage') or 0):.2f}%",
                f"Sobre {self._format_money(metrics.get('total_sales'))} em vendas",
                "percent-outline",
                "info",
            )
        )
        metrics_grid.add_widget(
            self._build_loss_metric_card(
                "Media por evento",
                self._format_money(metrics.get("avg_loss_value")),
                "Valor medio por registo de perda",
                "calculator-variant-outline",
                "success",
            )
        )
        content.add_widget(metrics_grid)

        by_type = metrics.get("by_type") or {}
        type_lines = [
            f"{self._loss_type_label(loss_type)}: {self._format_money(data.get('total_cost'))} em {int(data.get('count') or 0)} registos"
            for loss_type, data in by_type.items()
        ]
        content.add_widget(
            self._build_loss_section_card(
                "Distribuicao por tipo",
                type_lines,
                icon_name="shape-outline",
                tone="warning",
            )
        )

        limit = 8 if detailed else 5
        by_user = metrics.get("by_user") or []
        user_lines = []
        for user_data in by_user[:limit]:
            username = user_data[0] if len(user_data) > 0 else "Sistema"
            cost = float(user_data[1] or 0) if len(user_data) > 1 else 0.0
            revenue = float(user_data[2] or 0) if len(user_data) > 2 else 0.0
            events = int(user_data[3] or 0) if len(user_data) > 3 else 0
            user_lines.append(
                f"{username or 'Sistema'}: {self._format_money(cost)} de custo, {self._format_money(revenue)} de receita perdida, {events} eventos"
            )
        content.add_widget(
            self._build_loss_section_card(
                "Utilizadores com maior impacto",
                user_lines,
                icon_name="account-alert-outline",
                tone="info",
            )
        )

        by_product = metrics.get("by_product") or []
        product_lines = []
        for product_data in by_product[:limit]:
            name = product_data[1] if len(product_data) > 1 else "Produto"
            count = int(product_data[2] or 0) if len(product_data) > 2 else 0
            cost = float(product_data[3] or 0) if len(product_data) > 3 else 0.0
            product_lines.append(
                f"{name}: {self._format_money(cost)} em {count} ocorrencias"
            )
        content.add_widget(
            self._build_loss_section_card(
                "Produtos mais afetados",
                product_lines,
                icon_name="package-variant",
                tone="danger",
            )
        )

        if detailed:
            content.add_widget(
                self._build_loss_section_card(
                    "Leitura rapida",
                    [
                        "Use o botao PDF para guardar uma versao imprimivel deste painel.",
                        "A secao por utilizador ajuda a identificar concentracao de perdas por atendente.",
                        "A secao por produto ajuda a decidir reposicao, promocao ou revisao de manuseio.",
                    ],
                    icon_name="lightbulb-on-outline",
                    tone="success",
                )
            )

        return self._build_bounded_scroll(
            content,
            max_height_ratio=0.62 if detailed else 0.54,
            max_height_dp=620 if detailed else 520,
            min_height_dp=260,
        )

    def _show_pdf_success(self, pdf_path):
        tokens = self._theme_tokens()
        primary = tokens.get("primary", [0.12, 0.46, 0.78, 1])
        success = tokens.get("success", [0.2, 0.7, 0.3, 1])
        muted = tokens.get("text_secondary", [0.55, 0.58, 0.63, 1])
        foreground = tokens.get("text_primary", [0.92, 0.94, 0.97, 1])
        card_alt = tokens.get("card_alt", [0.16, 0.19, 0.24, 1])

        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(12),
            padding=[dp(4), dp(8), dp(4), 0],
            size_hint_y=None,
        )
        content.bind(minimum_height=content.setter("height"))

        header = MDBoxLayout(size_hint_y=None, height=dp(26), spacing=dp(8))
        header.add_widget(
            MDIcon(
                icon="check-circle-outline",
                theme_text_color="Custom",
                text_color=success,
                size_hint=(None, None),
                size=(dp(20), dp(20)),
            )
        )
        header.add_widget(
            MDLabel(
                text="Arquivo criado com sucesso",
                bold=True,
                font_style="Body2",
                theme_text_color="Custom",
                text_color=foreground,
            )
        )
        content.add_widget(header)

        path_card = MDCard(
            orientation="vertical",
            padding=[dp(10), dp(8)],
            size_hint_y=None,
            radius=[dp(8)],
            elevation=0,
            md_bg_color=card_alt,
        )
        path_card.bind(minimum_height=path_card.setter("height"))
        path_label = MDLabel(
            text=str(pdf_path or ""),
            theme_text_color="Custom",
            text_color=muted,
            font_style="Caption",
            halign="left",
            valign="top",
            size_hint_y=None,
        )
        self._bind_wrapped_label_height(path_label, min_height=dp(18))
        path_card.add_widget(path_label)
        content.add_widget(path_card)

        def _sync_dialog_height(*_args):
            dialog.height = min(
                max(dp(190), header.height + path_card.height + dp(120)),
                Window.height * 0.6,
            )

        path_card.bind(height=_sync_dialog_height)

        close_btn = MDFlatButton(
            text="FECHAR",
            theme_text_color="Custom",
            text_color=muted,
            radius=[dp(10)],
        )
        open_btn = MDRaisedButton(
            text="ABRIR PDF",
            md_bg_color=primary,
            radius=[dp(10)],
        )

        dialog = MDDialog(
            title="PDF Gerado",
            type="custom",
            content_cls=content,
            size_hint=(None, None),
            size=(min(dp(560), Window.width - dp(48)), dp(190)),
            buttons=[close_btn, open_btn],
        )
        close_btn.bind(on_release=lambda _x: dialog.dismiss())
        open_btn.bind(on_release=lambda _x: self._open_pdf(dialog, pdf_path))
        _sync_dialog_height()
        dialog.open()
    def _open_pdf(self, dialog, pdf_path):
        dialog.dismiss()
        self._ensure_pdf_viewer().view_pdf(pdf_path)

    def _generate_loss_metrics_pdf(self, start_date, end_date, metrics=None):
        snapshot_metrics = dict(metrics or {})

        def task():
            export_metrics = snapshot_metrics or (self.db.calculate_loss_metrics(start_date, end_date) or {})
            records = self.db.get_loss_records(start_date, end_date, limit=300) or []
            data = {
                "metrics": export_metrics,
                "records": records,
            }
            filters = {
                "start_date": start_date,
                "end_date": end_date,
                "product": "Todos os Produtos",
                "category": "Todas as Categorias",
            }
            return self._ensure_loss_report().generate(data, filters)

        def on_success(pdf_path):
            if not pdf_path:
                self.show_snackbar("Falha ao gerar PDF de perdas")
                return
            self._show_pdf_success(pdf_path)

        self._run_async_action(
            "loss-metrics-pdf",
            task,
            on_success=on_success,
            busy_message="A gerar PDF das metricas de perdas...",
            error_message="Erro ao gerar PDF das metricas de perdas",
        )

    def _open_loss_details_from_metrics(self, dialog, metrics, start_date, end_date):
        if dialog is not None:
            dialog.dismiss()
        self.show_detailed_loss_report(metrics=metrics, start_date=start_date, end_date=end_date)

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------
    def _set_back_target(self, screen_name, target):
        if not self.manager:
            return None
        app = App.get_running_app()
        ensure_screen = getattr(app, "ensure_screen", None)
        if screen_name not in self.manager.screen_names and callable(ensure_screen):
            ensure_screen(screen_name)
        if screen_name not in self.manager.screen_names:
            return None
        screen = self.manager.get_screen(screen_name)
        setattr(screen, "back_target", target)
        return screen

    def go_home(self):
        if self.manager and "admin_home" in self.manager.screen_names:
            self.manager.current = "admin_home"

    def go_to_definitions(self):
        screen = self._set_back_target("settings", "admin")
        if not screen:
            return
        self.manager.current = 'settings'

    def logout(self):
        app = App.get_running_app()
        setter = getattr(self.db, "set_active_user", None)
        if callable(setter):
            try:
                setter(None, None)
            except Exception:
                pass
        if app and app.current_user:
            app.current_user = None
            app.current_role = None
        if app:
            app._ai_banners_shown = False
            app._ai_notifications_seen_key = None
            app._ai_banners_last_key = None
        self.manager.current = "login"

    # ------------------------------------------------------------------
    # Category Menu
    # ------------------------------------------------------------------
    def get_categories(self):
        categories = set(self._manual_categories) | set(self._catalog_categories)
        for p in self.products:
            if len(p) > 11 and p[11]:
                categories.add(p[11])
        return sorted(categories)

    def register_category(self, category):
        if category:
            self._manual_categories.add(category)
        if self.category_menu:
            self.category_menu.dismiss()
            self.category_menu = None

    def show_category_menu(self, button):
        menu_items = [
            {
                "text": self._all_categories_label(),
                "on_release": lambda x="Todas": self.set_category(x),
            }
        ]

        for cat in self.get_categories():
            menu_items.append({
                "text": cat,
                "on_release": lambda x=cat: self.set_category(x),
            })

        if self.category_menu:
            self.category_menu.dismiss()

        self.category_menu = MDDropdownMenu(
            caller=button,
            items=menu_items,
            width_mult=4,
        )

        self.category_menu.open()

    def set_category(self, category):
        value = str(category or "").strip()
        self._selected_category = None if value in ("", "Todas", "Todas as Categorias", self._all_categories_label()) else value
        self.category_spinner.text = self._selected_category or self._all_categories_label()
        if self.category_menu:
            self.category_menu.dismiss()
        self.filter_products(self.search_input.text if self.search_input else "")

    # --------------------------------------------------------------------------
    # CORRECAO 1 — queue_filter
    # Pesquisa aplicada no proximo frame, usando cache em memoria.
    # --------------------------------------------------------------------------
    def queue_filter(self, search_text):
        self._pending_search = search_text or ""
        self._filter_token += 1
        if not self._is_current_screen():
            self._products_table_dirty = True
            return

        # Keep the current page responsive immediately while the debounced
        # server-side catalogue query is being prepared.
        self._show_local_filter_preview(self._pending_search)
        if self._filter_ev:
            self._filter_ev.cancel()
        self._filter_ev = Clock.schedule_once(self._apply_queued_filter, 0.18)

    def _apply_queued_filter(self, dt):
        self._filter_ev = None
        if not self._is_current_screen():
            self._products_table_dirty = True
            return
        self._request_products_page(reset=True, search_text=self._pending_search)

    @staticmethod
    def _normalize_product_id(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_group_date(value):
        text = str(value or "").strip()
        if not text:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(text)
        except Exception:
            return None

    @staticmethod
    def _get_group_lot_count(product):
        if not product:
            return 1
        if len(product) > 27:
            try:
                return max(1, int(product[27]))
            except Exception:
                return 1
        return 1

    def _get_group_source_ids(self, product):
        if not product:
            return ()
        if len(product) > 28:
            raw_ids = product[28] or ()
            normalized = []
            for value in raw_ids:
                product_id = self._normalize_product_id(value)
                if product_id is not None and product_id not in normalized:
                    normalized.append(product_id)
            if normalized:
                return tuple(normalized)
        normalized = self._normalize_product_id(product[0] if product else None)
        return (normalized,) if normalized is not None else ()

    def _get_group_catalog_key(self, product):
        if len(product) > 26 and product[26] not in (None, ""):
            return str(product[26]).strip().lower()
        return self._admin_catalog_key(product)

    def _get_group_selected_lot_id(self, product):
        if len(product) > 29:
            return self._normalize_product_id(product[29])
        return None

    def _get_group_selected_lot_position(self, product):
        if len(product) > 30:
            try:
                position = int(product[30])
            except Exception:
                return None
            return position if position > 0 else None
        return None

    def _dismiss_lot_menu(self):
        menu = getattr(self, "_lot_menu", None)
        if menu is None:
            return False
        try:
            menu.dismiss()
        except Exception:
            pass
        self._lot_menu = None
        return True

    def _prune_selected_lot_ids(self, rows):
        valid_by_key = {}
        for row in list(rows or []):
            if not row:
                continue
            catalog_key = self._admin_catalog_key(row)
            product_id = self._normalize_product_id(row[0] if len(row) > 0 else None)
            if product_id is None:
                continue
            valid_by_key.setdefault(catalog_key, set()).add(product_id)

        stale_keys = []
        for catalog_key, selected_id in dict(self._selected_lot_ids_by_catalog_key).items():
            if selected_id not in valid_by_key.get(catalog_key, set()):
                stale_keys.append(catalog_key)
        for catalog_key in stale_keys:
            self._selected_lot_ids_by_catalog_key.pop(catalog_key, None)

    def _apply_group_lot_selection(self, product, selected_lot_id=None):
        catalog_key = self._get_group_catalog_key(product)
        if not catalog_key:
            return False
        normalized_id = self._normalize_product_id(selected_lot_id)
        if normalized_id is None:
            self._selected_lot_ids_by_catalog_key.pop(catalog_key, None)
        else:
            self._selected_lot_ids_by_catalog_key[catalog_key] = normalized_id
        self._request_products_page(
            reset=False,
            search_text=self._current_search_text(),
            offset=self._products_page_offset,
            force=True,
        )
        return True

    def _format_lot_menu_text(self, lot_row, position=None, is_current=False):
        lot_id = self._normalize_product_id(lot_row[0] if lot_row else None) or 0
        expiry_raw = str(lot_row[13] if len(lot_row) > 13 and lot_row[13] else "").strip()
        expiry_text = self.format_date(expiry_raw) if expiry_raw else "Sem validade"
        is_weight = bool(lot_row[15]) if len(lot_row) > 15 else False
        stock_value = _safe_float(lot_row[2] if len(lot_row) > 2 else 0.0)
        stock_text = f"{stock_value:.2f} KG" if is_weight else f"{int(stock_value)} UN"
        prefix = "(Atual) " if is_current else ""
        lot_label = f"Lote {int(position)}" if position else f"ID {lot_id}"
        return f"{prefix}{lot_label} | ID {lot_id} | Val {expiry_text} | Stock {stock_text}"

    def _lot_row_sort_key(self, product):
        expiry_dt = self._parse_group_date(product[13] if len(product) > 13 else "")
        product_id = self._normalize_product_id(product[0] if product else None) or 0
        return (1 if expiry_dt is None else 0, expiry_dt or datetime.max, product_id)

    def _resolve_group_lot_rows(self, product):
        lot_rows = []
        seen_ids = set()
        for source_id in self._get_group_source_ids(product):
            product_id = self._normalize_product_id(source_id)
            if product_id is None or product_id in seen_ids:
                continue
            seen_ids.add(product_id)
            try:
                row = self.db.get_product(product_id)
            except Exception:
                row = None
            if row:
                lot_rows.append(row)
        lot_rows.sort(key=self._lot_row_sort_key)
        return lot_rows

    def _admin_catalog_key(self, product):
        barcode = str(product[12] if len(product) > 12 and product[12] is not None else "").strip().lower()
        if barcode:
            return f"bc:{barcode}"

        description = " ".join(str(product[1] if len(product) > 1 and product[1] is not None else "").split()).lower()
        category = " ".join(str(product[11] if len(product) > 11 and product[11] is not None else "").split()).lower()
        sale_price = round(_safe_float(product[4] if len(product) > 4 else 0.0), 4)
        is_weight = 1 if (len(product) > 15 and bool(product[15])) else 0
        units_per_package = (
            int(_safe_float(product[23], 0))
            if len(product) > 23 and product[23] not in (None, "")
            else 0
        )
        allow_pack_sale = 1 if (len(product) > 24 and bool(product[24])) else 0
        vat_rule = str(product[25] if len(product) > 25 and product[25] not in (None, "") else "STANDARD").strip().upper()
        return (
            f"desc:{description}|cat:{category}|w:{is_weight}|p:{sale_price:.4f}|"
            f"u:{units_per_package}|a:{allow_pack_sale}|v:{vat_rule}"
        )

    def _representative_group_row(self, rows):
        def priority(row):
            status = str(row[16] if len(row) > 16 and row[16] is not None else "").strip().upper()
            if "EXPIR" in status:
                status_rank = 0
            elif "PERTO" in status:
                status_rank = 1
            elif "ATIVO" in status:
                status_rank = 2
            else:
                status_rank = 3
            expiry_dt = self._parse_group_date(row[13] if len(row) > 13 else "")
            missing_expiry = 1 if expiry_dt is None else 0
            row_id = self._normalize_product_id(row[0] if row else None) or 0
            return (status_rank, missing_expiry, expiry_dt or datetime.max, -row_id)

        return min(list(rows or []), key=priority)

    # --------------------------------------------------------------------------
    # CORRECAO 2 — _aggregate_products_for_table
    # Nunca chamado na thread principal fora de contextos de background.
    # Mantido puro (sem side-effects) para poder ser chamado em threads.
    # --------------------------------------------------------------------------
    def _aggregate_products_for_table(self, rows):
        grouped = {}
        ordered_keys = []
        for row in list(rows or []):
            if not row:
                continue
            catalog_key = self._admin_catalog_key(row)
            bucket = grouped.get(catalog_key)
            if bucket is None:
                bucket = {"rows": []}
                grouped[catalog_key] = bucket
                ordered_keys.append(catalog_key)
            bucket["rows"].append(row)

        aggregated = []
        for catalog_key in ordered_keys:
            bucket_rows = list(grouped[catalog_key]["rows"])
            representative = self._representative_group_row(bucket_rows)
            ordered_bucket_rows = sorted(bucket_rows, key=self._lot_row_sort_key)
            source_ids = tuple(
                product_id
                for product_id in (
                    self._normalize_product_id(row[0] if len(row) > 0 else None)
                    for row in bucket_rows
                )
                if product_id is not None
            )
            lot_count = len(source_ids) or 1
            selected_lot_id = self._normalize_product_id(
                self._selected_lot_ids_by_catalog_key.get(catalog_key)
            )
            selected_row = next(
                (
                    row for row in bucket_rows
                    if self._normalize_product_id(row[0] if len(row) > 0 else None) == selected_lot_id
                ),
                None,
            )
            selected_lot_position = None
            if selected_lot_id is not None:
                for idx, row in enumerate(ordered_bucket_rows, start=1):
                    row_id = self._normalize_product_id(row[0] if len(row) > 0 else None)
                    if row_id == selected_lot_id:
                        selected_lot_position = idx
                        break
            if selected_lot_id is not None and selected_row is None:
                self._selected_lot_ids_by_catalog_key.pop(catalog_key, None)
                selected_lot_id = None
                selected_lot_position = None

            display_row = selected_row or representative
            if selected_row is not None:
                existing_stock = _safe_float(display_row[2])
                sold_stock = _safe_float(display_row[3])
                total_purchase_price = _safe_float(display_row[5])
                unit_purchase_price = _safe_float(display_row[6])
                sale_price = _safe_float(display_row[4])
                profit_per_unit = _safe_float(display_row[7])
                total_profit = _safe_float(display_row[8])
                profit_percentage = _safe_float(display_row[9])
                price_percentage = _safe_float(display_row[10])
                expiry_value = display_row[13] if len(display_row) > 13 else ""
                date_added = display_row[14] if len(display_row) > 14 else ""
                barcode_value = display_row[12] if len(display_row) > 12 else ""
                sku_value = display_row[22] if len(display_row) > 22 else ""
            else:
                existing_stock = sum(_safe_float(row[2]) for row in bucket_rows)
                sold_stock = sum(_safe_float(row[3]) for row in bucket_rows)
                total_purchase_price = sum(_safe_float(row[5]) for row in bucket_rows)
                total_profit = sum(_safe_float(row[8]) for row in bucket_rows)
                sold_cost_total = sum(_safe_float(row[6]) * _safe_float(row[3]) for row in bucket_rows)
                if existing_stock > 1e-9:
                    unit_purchase_price = total_purchase_price / existing_stock
                elif sold_stock > 1e-9:
                    unit_purchase_price = sold_cost_total / sold_stock
                else:
                    unit_purchase_price = _safe_float(representative[6])
                sale_price = _safe_float(representative[4])
                profit_per_unit = sale_price - unit_purchase_price
                profit_percentage = ((total_profit * 100.0) / sold_cost_total) if sold_cost_total > 1e-9 else 0.0
                price_percentage = ((sale_price - unit_purchase_price) / unit_purchase_price * 100.0) if unit_purchase_price > 1e-9 else 0.0

                expiry_candidates = [
                    row[13]
                    for row in bucket_rows
                    if len(row) > 13 and str(row[13] or "").strip()
                ]
                expiry_value = representative[13] if len(representative) > 13 else ""
                if expiry_candidates:
                    expiry_value = min(
                        expiry_candidates,
                        key=lambda value: self._parse_group_date(value) or datetime.max,
                    )

                date_added_candidates = [
                    row[14]
                    for row in bucket_rows
                    if len(row) > 14 and str(row[14] or "").strip()
                ]
                date_added = representative[14] if len(representative) > 14 else ""
                if date_added_candidates:
                    date_added = min(
                        date_added_candidates,
                        key=lambda value: self._parse_group_date(value) or datetime.max,
                    )

                barcode_value = next(
                    (
                        row[12]
                        for row in bucket_rows
                        if len(row) > 12 and str(row[12] or "").strip()
                    ),
                    representative[12] if len(representative) > 12 else "",
                )
                sku_value = next(
                    (
                        row[22]
                        for row in bucket_rows
                        if len(row) > 22 and str(row[22] or "").strip()
                    ),
                    representative[22] if len(representative) > 22 else "",
                )

            aggregated.append(
                (
                    display_row[0],
                    display_row[1],
                    existing_stock,
                    sold_stock,
                    sale_price,
                    total_purchase_price,
                    unit_purchase_price,
                    profit_per_unit,
                    total_profit,
                    profit_percentage,
                    price_percentage,
                    display_row[11],
                    barcode_value,
                    expiry_value,
                    date_added,
                    display_row[15],
                    display_row[16],
                    display_row[17],
                    display_row[18],
                    display_row[19],
                    display_row[20],
                    display_row[21],
                    sku_value,
                    display_row[23],
                    display_row[24],
                    display_row[25],
                    catalog_key,
                    lot_count,
                    source_ids,
                    selected_lot_id,
                    selected_lot_position,
                )
            )
        return aggregated

    def _rebuild_display_ids(self, rows=None):
        ordered_groups = []
        seen = set()
        for row in list(rows or []):
            if not row:
                continue
            source_ids = tuple(
                product_id for product_id in self._get_group_source_ids(row)
                if product_id is not None
            )
            if not source_ids:
                continue
            anchor_id = source_ids[0]
            if anchor_id in seen:
                continue
            seen.add(anchor_id)
            ordered_groups.append(source_ids)

        ordered_groups.sort(key=lambda ids: min(ids) if ids else 0)
        self._display_ids_by_product_id = {}
        for idx, product_ids in enumerate(ordered_groups, start=1):
            for product_id in product_ids:
                self._display_ids_by_product_id[product_id] = idx

    def _get_display_id(self, product_or_id):
        product_id = product_or_id
        if isinstance(product_or_id, (list, tuple)):
            product_id = product_or_id[0] if product_or_id else None
        normalized = self._normalize_product_id(product_id)
        if normalized is None:
            return ""
        return self._display_ids_by_product_id.get(normalized, normalized)

    @staticmethod
    def _normalize_search_text(text):
        normalized = unicodedata.normalize("NFKD", str(text or ""))
        return "".join(
            char for char in normalized
            if not unicodedata.combining(char)
        ).strip().lower()

    @staticmethod
    def _build_product_search_index_static(aggregated_rows, display_ids):
        display_ids = dict(display_ids or {})
        search_index = {}
        for product in list(aggregated_rows or []):
            if not product:
                continue
            pid = product[0] if product else None
            try:
                normalized_id = int(pid)
            except (TypeError, ValueError):
                normalized_id = None
            display_id = (
                display_ids.get(normalized_id, normalized_id)
                if normalized_id is not None
                else ""
            )
            source_ids = product[28] if len(product) > 28 and product[28] else (pid,)
            catalog_key = product[26] if len(product) > 26 else pid
            key_text = " ".join(
                str(value or "")
                for value in (
                    display_id,
                    pid,
                    product[1] if len(product) > 1 else "",
                    product[11] if len(product) > 11 else "",
                    product[12] if len(product) > 12 else "",
                    product[22] if len(product) > 22 else "",
                    " ".join(str(sid or "") for sid in source_ids),
                )
            )
            search_index[catalog_key] = AdminScreen._normalize_search_text(key_text)
        return search_index

    # --------------------------------------------------------------------------
    # CORRECAO 3 — filter_products + _apply_filter_result
    # Filtro usa índice em memória; load/refresh nao entram no caminho da digitação.
    # --------------------------------------------------------------------------
    @staticmethod
    def _matches_weight_filter_mode(product, filter_mode):
        sold_by_weight = bool(len(product) > 15 and product[15])
        if filter_mode == 1:
            return sold_by_weight
        if filter_mode == 2:
            return not sold_by_weight
        return True

    def filter_products(self, search_text, reset_page=True):
        self._pending_search = str(search_text or "")
        self._show_local_filter_preview(self._pending_search)
        return self._request_products_page(reset=reset_page, search_text=self._pending_search)

    def _apply_filter_result(self, filtered, token, reset_page=True):
        if token != self._filter_token:
            return
        self._current_filtered_products = filtered
        if not self._is_current_screen():
            self._products_table_dirty = True
            return
        self.update_product_table(filtered, reset_page=reset_page, already_aggregated=True)

    def clear_search(self):
        if self.search_input is not None:
            self.search_input.text = ""
            self.search_input.focus = True
        self._pending_search = ""
        if self._filter_ev:
            self._filter_ev.cancel()
            self._filter_ev = None
        self._request_products_page(reset=True, search_text="")

    def refresh_products_panel(self):
        """Repõe a gestão de produtos ao estado padrão e recarrega os dados."""
        if self._filter_ev:
            self._filter_ev.cancel()
            self._filter_ev = None
        self._filter_token += 1
        self._pending_search = ""
        self._products_page_offset = 0
        self.filter_mode = 0
        self._selected_category = None
        if self.category_menu:
            self.category_menu.dismiss()
        if self.category_spinner is not None:
            self.category_spinner.text = self._all_categories_label()
        if self.search_input is not None and self.search_input.text:
            # A regra KV agenda o filtro ao mudar o texto; cancelamo-lo logo
            # abaixo para que o refresh use apenas o estado padrão.
            self.search_input.text = ""
        if self._filter_ev:
            self._filter_ev.cancel()
            self._filter_ev = None
        self._request_products_page(reset=True, search_text="", force=True)
        self.show_snackbar("Tela atualizada e filtros repostos.")

    # ------------------------------------------------------------------
    # Data loading — paged and server-filtered, matching the Manager flow.
    # ------------------------------------------------------------------
    def _current_search_text(self):
        return str(self.search_input.text if self.search_input is not None else self._pending_search or "").strip()

    def _current_category(self):
        # The caption is localised for the user; the selected value remains a
        # database category only.  This avoids querying a literal category
        # such as "All Categories" after a language change.
        return self._selected_category

    def _current_weight_filter(self):
        mode = getattr(self, "filter_mode", 0)
        return True if mode == 1 else False if mode == 2 else None

    def _show_local_filter_preview(self, search_text):
        """Give immediate visual feedback without waiting for the API request."""
        source = list(self._aggregated_products_cache or [])
        if not source or not self._is_current_screen():
            return
        query = self._normalize_search_text(search_text)
        category = self._current_category()
        weight_filter = self._current_weight_filter()
        preview = []
        for product in source:
            if category and (len(product) <= 11 or product[11] != category):
                continue
            if weight_filter is not None and not self._matches_weight_filter_mode(product, 1 if weight_filter else 2):
                continue
            if query:
                catalog_key = product[26] if len(product) > 26 else product[0]
                haystack = self._product_search_index.get(catalog_key, "")
                if query not in haystack:
                    continue
            preview.append(product)
        self._current_filtered_products = preview
        self.update_product_table(preview, reset_page=False, already_aggregated=True)

    def _load_categories_async(self):
        if self._categories_loading:
            return
        self._categories_loading = True

        def worker():
            try:
                values = self.db.get_categories() or []
            except Exception:
                values = []
            categories = set()
            for value in values:
                category = value[0] if isinstance(value, (tuple, list)) and value else value
                if category:
                    categories.add(str(category))
            Clock.schedule_once(lambda _dt, data=categories: self._apply_categories(data), 0)

        Thread(target=worker, daemon=True).start()

    def _apply_categories(self, categories):
        self._catalog_categories.update(categories or ())
        self._categories_loading = False

    def _request_products_page(self, reset=True, search_text="", offset=None, force=False):
        query = str(search_text or "").strip()
        if offset is None:
            offset = 0 if reset else self._products_page_offset
        offset = max(0, int(offset or 0))

        if self._products_loading:
            self._queued_products_request = (reset, query, offset, force)
            return False

        token = self._products_load_token + 1
        self._products_load_token = token
        self._active_products_token = token
        self._products_loading = True
        self._queued_products_request = None
        self._load_categories_async()
        self._sync_product_pagination_controls(len(self._current_display or []), len(self._current_display or []))

        category = self._current_category()
        weight_filter = self._current_weight_filter()
        selected_lots = dict(self._selected_lot_ids_by_catalog_key)

        def worker():
            error = None
            payload = None
            try:
                payload = self.db.get_all_products_catalog_page(
                    search_text=query,
                    category=category,
                    sold_by_weight=weight_filter,
                    limit=self.PRODUCTS_PAGE_SIZE,
                    offset=offset,
                    selected_lot_ids_by_catalog_key=selected_lots,
                )
            except Exception as exc:
                error = str(exc)
            Clock.schedule_once(
                lambda _dt, data=payload, err=error, tok=token, off=offset, text=query:
                self._apply_products_page(data, err, tok, off, text),
                0,
            )

        Thread(target=worker, daemon=True).start()
        return True

    def _apply_products_page(self, payload, error, token, offset, search_text):
        if token != self._active_products_token:
            return
        self._products_loading = False
        if error:
            self.show_snackbar("Falha ao carregar produtos.")
            self._sync_product_pagination_controls(len(self._current_display or []), len(self._current_display or []))
            self._run_queued_products_request()
            return

        payload = payload or {}
        if isinstance(payload, dict):
            rows = list(payload.get("rows") or [])
            already_aggregated = bool(payload.get("aggregated"))
            total = payload.get("total")
            has_more = bool(payload.get("has_more"))
        else:
            rows = list(payload or [])
            already_aggregated = False
            total = None
            has_more = False

        if already_aggregated:
            aggregated = rows
        else:
            aggregated_all = AdminScreen._aggregate_products_for_table_static(
                rows,
                dict(self._selected_lot_ids_by_catalog_key),
            )
            # O backend moderno já limita no SQL. Fatiar novamente com o
            # offset global fazia a segunda página parecer vazia.
            if isinstance(payload, dict):
                aggregated = aggregated_all
            else:
                page_size = self.PRODUCTS_PAGE_SIZE
                aggregated = aggregated_all[offset:offset + page_size]
                total = len(aggregated_all)
                has_more = offset + len(aggregated) < total

        if not aggregated and offset > 0:
            self._request_products_page(reset=False, search_text=search_text, offset=max(0, offset - self.PRODUCTS_PAGE_SIZE))
            return

        self._products_loaded_once = True
        self._last_products_load_at = time.perf_counter()
        self._products_page_offset = offset
        self._products_has_more = has_more
        try:
            self._products_total_count = max(0, int(total)) if total is not None else None
        except (TypeError, ValueError):
            self._products_total_count = None
        self.products = list(aggregated)
        self._aggregated_products_cache = list(aggregated)
        self._display_ids_by_product_id = {
            source_id: offset + index + 1
            for index, product in enumerate(aggregated)
            for source_id in self._get_group_source_ids(product)
        }
        self._product_search_index = AdminScreen._build_product_search_index_static(
            aggregated,
            self._display_ids_by_product_id,
        )
        self._expiry_alerts_by_id = {
            product[0]: evaluate_expiry_alert(product[13] if len(product) > 13 else None)
            for product in aggregated if product
        }
        self._current_filtered_products = list(aggregated)
        self._products_table_dirty = True
        if self._is_current_screen():
            self.update_product_table(aggregated, reset_page=False, already_aggregated=True)
            self._show_expiry_dashboard_summary()

        self._run_queued_products_request()

    def _run_queued_products_request(self):
        pending = self._queued_products_request
        self._queued_products_request = None
        if not pending:
            return
        reset, queued_query, queued_offset, force = pending
        Clock.schedule_once(
            lambda _dt: self._request_products_page(reset, queued_query, queued_offset, force),
            0,
        )

    def load_products(self, force=False):
        if not force and self._aggregated_products_cache and not self._products_table_dirty:
            return False
        return self._request_products_page(
            reset=True,
            search_text=self._current_search_text(),
            force=force,
        )

    def _refresh_aggregated_products_async(self, reset_page=True):
        self._request_products_page(
            reset=reset_page,
            search_text=self._current_search_text(),
            offset=0 if reset_page else self._products_page_offset,
            force=True,
        )

    def _apply_refreshed_aggregated_products(self, aggregated, display_ids, search_index, token, reset_page):
        if token != self._products_load_token:
            return
        self._aggregated_products_cache = list(aggregated or [])
        self._display_ids_by_product_id = dict(display_ids or {})
        self._product_search_index = dict(search_index or {})
        self._products_table_dirty = True
        if not self._is_current_screen():
            return
        self.filter_products(
            self.search_input.text if self.search_input else self._pending_search,
            reset_page=reset_page,
        )

    @staticmethod
    def _aggregate_products_for_table_static(rows, selected_lot_ids_by_catalog_key=None):
        """
        Versao estatica de _aggregate_products_for_table para uso em threads.
        Recebe selecoes de lote por copia para nao tocar estado da UI.
        """
        selected_lot_ids_by_catalog_key = dict(selected_lot_ids_by_catalog_key or {})

        def _normalize_product_id(value):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        def _parse_group_date(value):
            text = str(value or "").strip()
            if not text:
                return None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    return datetime.strptime(text, fmt)
                except ValueError:
                    continue
            try:
                return datetime.fromisoformat(text)
            except Exception:
                return None

        def _admin_catalog_key(product):
            barcode = str(product[12] if len(product) > 12 and product[12] is not None else "").strip().lower()
            if barcode:
                return f"bc:{barcode}"
            description = " ".join(str(product[1] if len(product) > 1 and product[1] is not None else "").split()).lower()
            category = " ".join(str(product[11] if len(product) > 11 and product[11] is not None else "").split()).lower()
            sale_price = round(_safe_float(product[4] if len(product) > 4 else 0.0), 4)
            is_weight = 1 if (len(product) > 15 and bool(product[15])) else 0
            units_per_package = (
                int(_safe_float(product[23], 0))
                if len(product) > 23 and product[23] not in (None, "")
                else 0
            )
            allow_pack_sale = 1 if (len(product) > 24 and bool(product[24])) else 0
            vat_rule = str(product[25] if len(product) > 25 and product[25] not in (None, "") else "STANDARD").strip().upper()
            return (
                f"desc:{description}|cat:{category}|w:{is_weight}|p:{sale_price:.4f}|"
                f"u:{units_per_package}|a:{allow_pack_sale}|v:{vat_rule}"
            )

        def _lot_row_sort_key(product):
            expiry_dt = _parse_group_date(product[13] if len(product) > 13 else "")
            product_id = _normalize_product_id(product[0] if product else None) or 0
            return (1 if expiry_dt is None else 0, expiry_dt or datetime.max, product_id)

        def _representative_group_row(bucket_rows):
            def priority(row):
                status = str(row[16] if len(row) > 16 and row[16] is not None else "").strip().upper()
                if "EXPIR" in status:
                    status_rank = 0
                elif "PERTO" in status:
                    status_rank = 1
                elif "ATIVO" in status:
                    status_rank = 2
                else:
                    status_rank = 3
                expiry_dt = _parse_group_date(row[13] if len(row) > 13 else "")
                missing_expiry = 1 if expiry_dt is None else 0
                row_id = _normalize_product_id(row[0] if row else None) or 0
                return (status_rank, missing_expiry, expiry_dt or datetime.max, -row_id)
            return min(list(bucket_rows or []), key=priority)

        grouped = {}
        ordered_keys = []
        for row in list(rows or []):
            if not row:
                continue
            catalog_key = _admin_catalog_key(row)
            bucket = grouped.get(catalog_key)
            if bucket is None:
                bucket = {"rows": []}
                grouped[catalog_key] = bucket
                ordered_keys.append(catalog_key)
            bucket["rows"].append(row)

        aggregated = []
        for catalog_key in ordered_keys:
            bucket_rows = list(grouped[catalog_key]["rows"])
            representative = _representative_group_row(bucket_rows)
            ordered_bucket_rows = sorted(bucket_rows, key=_lot_row_sort_key)
            source_ids = tuple(
                pid for pid in (
                    _normalize_product_id(row[0] if len(row) > 0 else None)
                    for row in bucket_rows
                )
                if pid is not None
            )
            lot_count = len(source_ids) or 1

            selected_lot_id = _normalize_product_id(selected_lot_ids_by_catalog_key.get(catalog_key))
            selected_row = next(
                (
                    row for row in bucket_rows
                    if _normalize_product_id(row[0] if len(row) > 0 else None) == selected_lot_id
                ),
                None,
            )
            selected_lot_position = None
            if selected_lot_id is not None:
                for idx, row in enumerate(ordered_bucket_rows, start=1):
                    row_id = _normalize_product_id(row[0] if len(row) > 0 else None)
                    if row_id == selected_lot_id:
                        selected_lot_position = idx
                        break
            if selected_lot_id is not None and selected_row is None:
                selected_lot_id = None
                selected_lot_position = None

            display_row = selected_row or representative
            if selected_row is not None:
                existing_stock = _safe_float(display_row[2])
                sold_stock = _safe_float(display_row[3])
                total_purchase_price = _safe_float(display_row[5])
                unit_purchase_price = _safe_float(display_row[6])
                sale_price = _safe_float(display_row[4])
                profit_per_unit = _safe_float(display_row[7])
                total_profit = _safe_float(display_row[8])
                profit_percentage = _safe_float(display_row[9])
                price_percentage = _safe_float(display_row[10])
                expiry_value = display_row[13] if len(display_row) > 13 else ""
                date_added = display_row[14] if len(display_row) > 14 else ""
                barcode_value = display_row[12] if len(display_row) > 12 else ""
                sku_value = display_row[22] if len(display_row) > 22 else ""
            else:
                existing_stock = sum(_safe_float(row[2]) for row in bucket_rows)
                sold_stock = sum(_safe_float(row[3]) for row in bucket_rows)
                total_purchase_price = sum(_safe_float(row[5]) for row in bucket_rows)
                total_profit = sum(_safe_float(row[8]) for row in bucket_rows)
                sold_cost_total = sum(_safe_float(row[6]) * _safe_float(row[3]) for row in bucket_rows)
                if existing_stock > 1e-9:
                    unit_purchase_price = total_purchase_price / existing_stock
                elif sold_stock > 1e-9:
                    unit_purchase_price = sold_cost_total / sold_stock
                else:
                    unit_purchase_price = _safe_float(representative[6])
                sale_price = _safe_float(representative[4])
                profit_per_unit = sale_price - unit_purchase_price
                profit_percentage = ((total_profit * 100.0) / sold_cost_total) if sold_cost_total > 1e-9 else 0.0
                price_percentage = ((sale_price - unit_purchase_price) / unit_purchase_price * 100.0) if unit_purchase_price > 1e-9 else 0.0

                expiry_candidates = [
                    row[13] for row in bucket_rows
                    if len(row) > 13 and str(row[13] or "").strip()
                ]
                expiry_value = representative[13] if len(representative) > 13 else ""
                if expiry_candidates:
                    expiry_value = min(
                        expiry_candidates,
                        key=lambda v: _parse_group_date(v) or datetime.max,
                    )

                date_added_candidates = [
                    row[14] for row in bucket_rows
                    if len(row) > 14 and str(row[14] or "").strip()
                ]
                date_added = representative[14] if len(representative) > 14 else ""
                if date_added_candidates:
                    date_added = min(
                        date_added_candidates,
                        key=lambda v: _parse_group_date(v) or datetime.max,
                    )

                barcode_value = next(
                    (row[12] for row in bucket_rows if len(row) > 12 and str(row[12] or "").strip()),
                    representative[12] if len(representative) > 12 else "",
                )
                sku_value = next(
                    (row[22] for row in bucket_rows if len(row) > 22 and str(row[22] or "").strip()),
                    representative[22] if len(representative) > 22 else "",
                )

            aggregated.append((
                display_row[0], display_row[1],
                existing_stock, sold_stock, sale_price,
                total_purchase_price, unit_purchase_price,
                profit_per_unit, total_profit,
                profit_percentage, price_percentage,
                display_row[11], barcode_value,
                expiry_value, date_added,
                display_row[15], display_row[16], display_row[17],
                display_row[18], display_row[19], display_row[20],
                display_row[21], sku_value,
                display_row[23], display_row[24], display_row[25],
                catalog_key, lot_count, source_ids,
                selected_lot_id, selected_lot_position,
            ))
        return aggregated

    @staticmethod
    def _rebuild_display_ids_static(aggregated_rows):
        """Versao estatica de _rebuild_display_ids para uso em threads."""
        ordered_groups = []
        seen = set()

        def _get_source_ids(row):
            if not row:
                return ()
            if len(row) > 28 and row[28]:
                result = []
                for v in row[28]:
                    try:
                        result.append(int(v))
                    except (TypeError, ValueError):
                        pass
                return tuple(result) if result else ()
            try:
                pid = int(row[0])
                return (pid,)
            except (TypeError, ValueError):
                return ()

        for row in list(aggregated_rows or []):
            source_ids = _get_source_ids(row)
            if not source_ids:
                continue
            anchor_id = source_ids[0]
            if anchor_id in seen:
                continue
            seen.add(anchor_id)
            ordered_groups.append(source_ids)

        ordered_groups.sort(key=lambda ids: min(ids) if ids else 0)
        display_ids = {}
        for idx, product_ids in enumerate(ordered_groups, start=1):
            for product_id in product_ids:
                display_ids[product_id] = idx
        return display_ids

    def _apply_loaded_products(self, rows, aggregated, display_ids, search_index, expiry_alerts, token):
        if token != self._products_load_token:
            return
        self._products_loading = False
        self._products_loaded_once = True
        self._last_products_load_at = time.perf_counter()
        self.products = list(rows or [])
        self._prune_selected_lot_ids(self.products)

        # Resultados ja calculados na thread de fundo
        self._aggregated_products_cache = aggregated
        self._display_ids_by_product_id = display_ids
        self._product_search_index = dict(search_index or {})
        self._expiry_alerts_by_id = expiry_alerts
        self._products_table_dirty = True

        if self._pending_products_load:
            self._pending_products_load = False
            Clock.schedule_once(lambda dt: self.load_products(force=True), 0.05)
            return

        if self._is_current_screen():
            self.filter_products(self.search_input.text if self.search_input else self._pending_search)
            self._show_expiry_dashboard_summary()

    # ------------------------------------------------------------------
    # Date formatting
    # ------------------------------------------------------------------
    def format_datetime(self, datetime_str):
        try:
            if datetime_str and datetime_str != "N/A":
                dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
                return dt.strftime("%d/%m/%Y\n%H:%M")
        except Exception as e:
            print(f"Erro ao formatar data: {e}")
        return datetime_str

    def format_date(self, date_str):
        try:
            if date_str and date_str != "N/A":
                try:
                    dt = datetime.strptime(str(date_str), "%Y-%m-%d %H:%M:%S")
                    return dt.strftime("%d/%m/%Y")
                except ValueError:
                    dt = datetime.strptime(str(date_str), "%Y-%m-%d")
                    return dt.strftime("%d/%m/%Y")
        except Exception as e:
            print(f"Erro ao formatar data: {e}")
        return str(date_str)

    def _build_expiry_alerts(self, rows):
        alerts = {}
        for row in rows or []:
            if not row:
                continue
            product_id = row[0]
            expiry_date = row[13] if len(row) > 13 else None
            alerts[product_id] = evaluate_expiry_alert(expiry_date)
        return alerts

    def _get_expiry_alert(self, product):
        if not product:
            return evaluate_expiry_alert(None)
        product_id = product[0]
        alert = self._expiry_alerts_by_id.get(product_id)
        if alert is None:
            expiry_date = product[13] if len(product) > 13 else None
            alert = evaluate_expiry_alert(expiry_date)
            self._expiry_alerts_by_id[product_id] = alert
        return alert

    def _show_expiry_dashboard_summary(self):
        if not self._expiry_alerts_by_id:
            return
        now = time.perf_counter()
        if (now - self._last_expiry_summary_at) < self._expiry_summary_cooldown:
            return
        counts = get_expiry_level_counts(self._expiry_alerts_by_id.values())
        if counts["total"] <= 0:
            return
        self._last_expiry_summary_at = now
        self.show_snackbar(
            "Vencimento: "
            f"leve {counts['leve']} | medio {counts['medio']} | alto {counts['alto']} | "
            f"critico {counts['critico']} | vencido {counts['vencido']}"
        )

    # ------------------------------------------------------------------
    # Responsive sizing
    # ------------------------------------------------------------------
    def _row_height(self):
        base_height = max(dp(56), Window.height * 0.062)
        return min(base_height, dp(72))

    def _theme_tokens(self):
        app = App.get_running_app()
        return getattr(app, "theme_tokens", {}) if app else {}

    # ------------------------------------------------------------------
    # Table rendering
    # ------------------------------------------------------------------
    # As linhas sao atualizadas pelo RecycleView. Ao pesquisar, somente os
    # dados mudam; os widgets visiveis sao reaproveitados em vez de reconstruidos.
    def update_product_table(self, products_to_display=None, reset_page=True, already_aggregated=False):
        if not self._is_current_screen():
            self._products_table_dirty = True
            return

        if products_to_display is None:
            products_to_display = self._aggregated_products_cache or self.products
            already_aggregated = bool(self._aggregated_products_cache)

        if already_aggregated:
            self._current_display = (
                products_to_display
                if isinstance(products_to_display, list)
                else list(products_to_display or [])
            )
        else:
            self._aggregate_display_rows_async(products_to_display or [], reset_page=reset_page)
            return

        if reset_page:
            self._product_page_index = 0
        self._render_current_product_page()

    def _aggregate_display_rows_async(self, rows, reset_page=True):
        token = self._products_load_token
        source_rows = list(rows or [])

        def worker():
            try:
                aggregated = AdminScreen._aggregate_products_for_table_static(
                    source_rows,
                    dict(self._selected_lot_ids_by_catalog_key),
                )
            except Exception as exc:
                print(f"Erro ao preparar tabela de produtos: {exc}")
                aggregated = []
            Clock.schedule_once(
                lambda dt, data=aggregated, tok=token:
                self._apply_async_display_rows(data, tok, reset_page),
                0,
            )

        Thread(target=worker, daemon=True).start()

    def _apply_async_display_rows(self, aggregated, token, reset_page):
        if token != self._products_load_token:
            return
        if not self._is_current_screen():
            self._products_table_dirty = True
            return
        self.update_product_table(aggregated, reset_page=reset_page, already_aggregated=True)

    def _render_current_product_page(self):
        if not self._is_current_screen():
            self._products_table_dirty = True
            return

        self._cancel_product_table_render(keep_table_enabled=False)
        self._products_table_dirty = False

        page_rows = list(self._current_display or [])
        self._sync_product_pagination_controls(len(page_rows), len(page_rows))

        if not self.product_table:
            return

        row_h = self._row_height()
        tokens = self._theme_tokens()
        self._table_row_height = row_h
        dark_table = sum(tokens.get("card", [1, 1, 1, 1])[:3]) < 0.60
        self._table_palette = {
            "tokens": tokens,
            "row_even": tokens.get("surface_alt", [0.97, 0.98, 0.99, 1]),
            "row_odd": tokens.get("card", [1, 1, 1, 1]),
            "border_color": tokens.get("divider", [0, 0, 0, 0.25]),
            "text_primary": tokens.get("text_primary", [0.25, 0.30, 0.40, 1]),
            "text_secondary": tokens.get("text_secondary", [0.2, 0.25, 0.35, 1]),
            "text_muted": tokens.get("text_muted", [0.45, 0.50, 0.55, 1]),
            "info_color": [0.40, 0.74, 1.00, 1] if dark_table else tokens.get("info", [0.1, 0.45, 0.75, 1]),
            "success_color": [0.34, 0.90, 0.58, 1] if dark_table else tokens.get("success", [0.10, 0.55, 0.25, 1]),
            "warning_color": [1.00, 0.78, 0.35, 1] if dark_table else tokens.get("warning", [0.75, 0.45, 0.10, 1]),
            "danger_color": [1.00, 0.50, 0.52, 1] if dark_table else tokens.get("danger", [0.8, 0.2, 0.2, 1]),
        }

        page_offset = max(0, int(getattr(self, "_products_page_offset", 0) or 0))
        self.product_table.data = [
            {
                "admin_screen": self,
                "product_data": product,
                "row_index": page_offset + idx,
                "row_height": row_h,
                "palette": self._table_palette,
            }
            for idx, product in enumerate(page_rows)
        ]
        self.product_table.disabled = False

    def _render_table_batch(self, dt, token):
        # Kept as a harmless compatibility hook for callers from older builds.
        return False

    def _cancel_product_table_render(self, keep_table_enabled=True):
        if self._table_render_ev:
            try:
                self._table_render_ev.cancel()
            except Exception:
                Clock.unschedule(self._table_render_ev)
            self._table_render_ev = None
        self._pending_table_rows = deque()
        self._table_render_token += 1
        if keep_table_enabled and self.product_table:
            self.product_table.disabled = False

    @staticmethod
    def _blend_rgba(base, accent, factor):
        base = list(base or [1, 1, 1, 1])
        accent = list(accent or base)
        while len(base) < 4:
            base.append(1)
        while len(accent) < 4:
            accent.append(base[3])
        mix = max(0.0, min(1.0, float(factor or 0.0)))
        return [
            (base[index] * (1.0 - mix)) + (accent[index] * mix)
            for index in range(4)
        ]

    def _clear_product_row_hover_bindings(self):
        for handler in list(self._product_row_hover_handlers or []):
            try:
                Window.unbind(mouse_pos=handler)
            except Exception:
                pass
        self._product_row_hover_handlers = []

    def _bind_product_row_hover(self, row_cells, base_color, palette):
        cells = [cell for cell in list(row_cells or []) if cell is not None]
        if not cells:
            return
        tokens = palette.get("tokens", {}) if isinstance(palette, dict) else {}
        accent = tokens.get("primary", [0.15, 0.52, 0.76, 1])
        hover_color = self._blend_rgba(base_color, accent, 0.18)
        base = list(base_color or [1, 1, 1, 1])
        base_border = list(palette.get("border_color", [0, 0, 0, 0.18]))
        while len(base_border) < 4:
            base_border.append(1)
        hover_border = list(accent or [0.15, 0.52, 0.76, 1])
        while len(hover_border) < 4:
            hover_border.append(1)
        hover_border[3] = 0.62
        for cell in cells:
            if hasattr(cell, "set_hover_glow_color"):
                cell.set_hover_glow_color(accent)
        state = {"active_cell": None}

        def animate_cell(cell, hovered):
            if cell is None or cell.parent is None:
                return
            target = hover_color if hovered else base
            border_target = hover_border if hovered else base_border
            glow_alpha = 0.18 if hovered else 0
            Animation.cancel_all(cell, "md_bg_color", "hover_growth", "hover_glow_alpha")
            Animation(
                md_bg_color=target,
                hover_growth=0,
                hover_glow_alpha=glow_alpha,
                d=0.13,
                t="out_quad",
            ).start(cell)
            if hasattr(cell, "animate_inner_growth"):
                cell.animate_inner_growth(hovered)
            border_instruction = getattr(cell, "_border_color_instruction", None)
            if border_instruction is not None:
                border_instruction.rgba = border_target

        def set_active_cell(active_cell):
            if state["active_cell"] is active_cell:
                return
            previous = state["active_cell"]
            state["active_cell"] = active_cell
            animate_cell(previous, False)
            animate_cell(active_cell, True)

        def resolve_hover_cell(parent, pos):
            local_x, local_y = parent.to_widget(*pos)
            for cell in cells:
                if (
                    cell.x <= local_x <= cell.x + cell.width
                    and cell.y <= local_y <= cell.y + cell.height
                ):
                    return cell
            return None

        def handle_mouse_pos(_window, pos):
            parent = cells[0].parent
            if parent is None:
                try:
                    Window.unbind(mouse_pos=handle_mouse_pos)
                except Exception:
                    pass
                return
            try:
                hovered_cell = resolve_hover_cell(parent, pos)
            except Exception:
                hovered_cell = None
            set_active_cell(hovered_cell)

        Window.bind(mouse_pos=handle_mouse_pos)
        self._product_row_hover_handlers.append(handle_mouse_pos)

    def _sync_product_pagination_controls(self, total_rows, visible_rows):
        if not self.ids:
            return

        page_size = max(1, int(self.PRODUCTS_PAGE_SIZE))
        page_offset = max(0, int(getattr(self, "_products_page_offset", 0) or 0))
        current_page = (page_offset // page_size) + 1
        known_total = getattr(self, "_products_total_count", None)
        total_pages = (
            max(1, math.ceil(float(known_total) / page_size))
            if known_total is not None else None
        )

        label = self.ids.get("admin_page_label")
        if label is not None:
            app = App.get_running_app()
            language = getattr(app, "language", "pt") if app else "pt"
            templates = {
                "en": ("Page {page}/{pages} | {count} items", "Page {page}/{pages} | {start}-{end} of {total}"),
                "fr": ("Page {page}/{pages} | {count} éléments", "Page {page}/{pages} | {start}-{end} sur {total}"),
                "de": ("Seite {page}/{pages} | {count} Artikel", "Seite {page}/{pages} | {start}-{end} von {total}"),
                "es": ("Página {page}/{pages} | {count} artículos", "Página {page}/{pages} | {start}-{end} de {total}"),
                "zh": ("第 {page}/{pages} 页 | {count} 项", "第 {page}/{pages} 页 | {start}-{end}/{total}"),
                "pt": ("Página {page}/{pages} | {count} itens", "Página {page}/{pages} | {start}-{end} de {total}"),
            }
            empty_template, range_template = templates.get(str(language).lower(), templates["pt"])
            pages = total_pages or current_page
            if total_rows <= 0:
                label.text = empty_template.format(page=current_page, pages=pages, count=0)
            else:
                start = page_offset + 1
                end = start + max(0, int(visible_rows)) - 1
                if total_pages is not None:
                    label.text = range_template.format(page=current_page, pages=total_pages, start=start, end=end, total=known_total)
                else:
                    label.text = range_template.format(page=current_page, pages="?", start=start, end=end, total="?")

        prev_btn = self.ids.get("admin_prev_btn")
        if prev_btn is not None:
            prev_btn.disabled = self._products_loading or page_offset <= 0

        next_btn = self.ids.get("admin_next_btn")
        if next_btn is not None:
            next_btn.disabled = self._products_loading or not getattr(self, "_products_has_more", False) or total_rows <= 0

    def previous_product_page(self):
        page_offset = max(0, int(getattr(self, "_products_page_offset", 0) or 0))
        if self._products_loading or page_offset <= 0:
            return False
        return self._request_products_page(
            reset=False,
            search_text=self._current_search_text(),
            offset=max(0, page_offset - self.PRODUCTS_PAGE_SIZE),
        )

    def next_product_page(self):
        if self._products_loading or not getattr(self, "_products_has_more", False):
            return False
        return self._request_products_page(
            reset=False,
            search_text=self._current_search_text(),
            offset=max(0, int(getattr(self, "_products_page_offset", 0) or 0)) + self.PRODUCTS_PAGE_SIZE,
        )

    # --------------------------------------------------------------------------
    # CORRECAO 6 — _make_product_cell
    # Instruções de canvas criadas UMA única vez; callback só actualiza
    # coordenadas — zero alocações por evento pos/size.
    # --------------------------------------------------------------------------
    def _make_product_cell(self, col_idx, row_h, bg_color, border_color, align='center'):
        cell = ProductTableCell(
            size_hint_x=COL_HINTS[col_idx],
            size_hint_y=None,
            height=row_h,
            md_bg_color=bg_color,
            padding=[dp(6), 0] if align == 'center' else [dp(10), 0],
        )

        with cell.canvas.after:
            _border_color_instruction = Color(*border_color)
            _right_line  = Line(width=1)
            _bottom_line = Line(width=1)
        cell._border_color_instruction = _border_color_instruction
        cell._base_border_color = list(border_color)

        def _update_borders(instance, *_):
            x, y, w, h = instance.x, instance.y, instance.width, instance.height
            _right_line.points  = [x + w, y,     x + w, y + h]
            _bottom_line.points = [x,     y,     x + w, y    ]

        cell.bind(pos=_update_borders, size=_update_borders)
        _update_borders(cell)
        return cell

    def _append_product_row(self, product, idx, row_h, palette):
        row_bg_color = palette["row_even"] if idx % 2 == 0 else palette["row_odd"]
        border_color = palette["border_color"]
        text_primary = palette["text_primary"]
        text_secondary = palette["text_secondary"]
        text_muted = palette["text_muted"]
        info_color = palette["info_color"]
        success_color = palette["success_color"]
        warning_color = palette["warning_color"]
        danger_color = palette["danger_color"]
        action_tokens = palette["tokens"]
        expiry_alert = self._get_expiry_alert(product)
        display_id = self._get_display_id(product)
        lot_count = self._get_group_lot_count(product)
        selected_lot_id = self._get_group_selected_lot_id(product)
        selected_lot_position = self._get_group_selected_lot_position(product)

        is_sold_by_weight = product[15] if len(product) > 15 else 0
        unit_label = "KG" if is_sold_by_weight else ""
        row_cells = []

        def add_row_cell(widget):
            row_cells.append(widget)
            self.product_table.add_widget(widget)

        cell = self._make_product_cell(0, row_h, row_bg_color, border_color)
        if lot_count > 1:
            seq_btn = HoverRaisedButton(
                text=str(display_id),
                size_hint=(1, 1),
                md_bg_color=action_tokens.get("info", [0.1, 0.45, 0.75, 1]),
                theme_text_color="Custom",
                text_color=action_tokens.get("on_primary", [1, 1, 1, 1]),
                font_size=sp(13),
            )
            seq_btn.product_data = product
            seq_btn.requested_action = "select"
            seq_btn.hint_text = "Selecionar lote"
            seq_btn.bind(on_release=self.open_group_lot_selector)
            cell.add_widget(seq_btn)
        else:
            cell.add_widget(MDLabel(
                text=str(display_id),
                theme_text_color="Custom",
                text_color=text_primary,
                halign='center',
                bold=True,
                font_style="Body1"
            ))
        add_row_cell(cell)

        cell = self._make_product_cell(1, row_h, row_bg_color, border_color, align='left')
        cell.add_widget(MDLabel(
            text=(
                f"{product[1]} (Lote {selected_lot_position} de {lot_count})"
                if lot_count > 1 and selected_lot_position is not None
                else f"{product[1]} ({lot_count} lote{'s' if lot_count != 1 else ''})"
                if lot_count > 1 else product[1]
            ),
            theme_text_color="Custom",
            text_color=text_primary,
            halign='left',
            font_style="Body2",
            shorten=True,
            shorten_from="right"
        ))
        add_row_cell(cell)

        stock_value = product[2]
        stock_text = (
            f"{stock_value:.2f} {unit_label}"
            if is_sold_by_weight else f"{int(stock_value)} {unit_label}"
        )
        stock_color = danger_color if stock_value < 10 else text_secondary
        cell = self._make_product_cell(2, row_h, row_bg_color, border_color)
        cell.add_widget(MDLabel(
            text=stock_text,
            theme_text_color="Custom",
            text_color=stock_color,
            halign='center',
            font_style="Body2",
            bold=stock_value < 10
        ))
        add_row_cell(cell)

        sold_value = product[3]
        sold_text = (
            f"{sold_value:.2f} {unit_label}"
            if is_sold_by_weight else f"{int(sold_value)} {unit_label}"
        )
        cell = self._make_product_cell(3, row_h, row_bg_color, border_color)
        cell.add_widget(MDLabel(
            text=sold_text,
            theme_text_color="Custom",
            text_color=text_secondary,
            halign='center',
            font_style="Body2"
        ))
        add_row_cell(cell)

        cell = self._make_product_cell(4, row_h, row_bg_color, border_color)
        sale_type_text = "KG" if is_sold_by_weight else "UN"
        cell.add_widget(MDLabel(
            text=sale_type_text,
            theme_text_color="Custom",
            text_color=warning_color if is_sold_by_weight else info_color,
            halign='center',
            bold=True,
            font_style="Subtitle2"
        ))
        add_row_cell(cell)

        cell = self._make_product_cell(5, row_h, row_bg_color, border_color)
        cell.add_widget(MDLabel(
            text=f"{product[4]:.2f} MT",
            theme_text_color="Custom",
            text_color=success_color,
            halign='center',
            bold=True,
            font_style="Body1"
        ))
        add_row_cell(cell)

        cell = self._make_product_cell(6, row_h, row_bg_color, border_color)
        cell.add_widget(MDLabel(
            text=f"{product[8]:.2f} MT",
            theme_text_color="Custom",
            text_color=info_color,
            halign='center',
            bold=True,
            font_style="Body1"
        ))
        add_row_cell(cell)

        expiry_date = str(product[13]) if len(product) > 13 and product[13] else "N/A"
        expiry_color = (
            expiry_alert["color_rgba"]
            if expiry_alert.get("is_alert")
            else text_muted
        )
        expiry_label = expiry_alert.get("short_label", "--")
        expiry_text = (
            f"{self.format_date(expiry_date)} | {expiry_label}"
            if expiry_date != "N/A"
            else "Sem validade"
        )
        if lot_count > 1 and selected_lot_position is not None:
            expiry_text = f"{expiry_text} | Lote {selected_lot_position}"
        elif lot_count > 1:
            expiry_text = f"{expiry_text} | {lot_count} lotes"
        cell = self._make_product_cell(7, row_h, row_bg_color, border_color)
        cell.add_widget(MDLabel(
            text=expiry_text,
            theme_text_color="Custom",
            text_color=expiry_color,
            halign='center',
            font_style="Caption"
        ))
        add_row_cell(cell)

        cell = self._make_product_cell(8, row_h, row_bg_color, border_color)
        action_anchor = AnchorLayout(anchor_x="center", anchor_y="center")
        action_layout = MDBoxLayout(size_hint=(None, None), size=(dp(124), dp(36)), spacing=dp(8))
        action_layout.add_widget(self.create_detail_button(product, tokens=action_tokens))
        action_layout.add_widget(self.create_edit_button(product, tokens=action_tokens))
        action_layout.add_widget(self.create_delete_button(product, tokens=action_tokens))
        action_anchor.add_widget(action_layout)
        cell.add_widget(action_anchor)
        add_row_cell(cell)
        self._bind_product_row_hover(row_cells, row_bg_color, palette)

    # ------------------------------------------------------------------
    # Action buttons
    # ------------------------------------------------------------------
    def _open_product_details(self, product):
        if product:
            _get_detail_popup_class()(product).open()
            return True
        self.show_snackbar("Produto nao encontrado")
        return False

    def _open_product_editor(self, product):
        if not product:
            self.show_snackbar("Produto nao encontrado")
            return False
        _get_product_form_class()(self, product).open()
        return True

    def _apply_inline_product_edit(self, product, product_id, field, value, is_weight=False):
        """Aplica a alteração de um campo e refresca a tabela."""
        try:
            description = str(product[1] if len(product) > 1 else "")
            category = str(product[11] if len(product) > 11 else "") or "Geral"
            existing_stock = float(product[2] if len(product) > 2 else 0)
            sold_stock = float(product[3] if len(product) > 3 else 0)
            sale_price = float(product[4] if len(product) > 4 else 0)
            total_purchase = float(product[5] if len(product) > 5 else 0)
            unit_purchase = float(product[6] if len(product) > 6 else 0)
            barcode = product[12] if len(product) > 12 else None
            expiry = product[13] if len(product) > 13 else None
            package_quantity = product[21] if len(product) > 21 else None
            units_per_package = product[23] if len(product) > 23 else None
            allow_pack_sale = bool(product[24]) if len(product) > 24 else False
            vat_rule = product[25] if len(product) > 25 else None

            if field == "description":
                if not value:
                    self.show_snackbar("Nome obrigatório")
                    return False
                description = value
            elif field == "stock":
                try:
                    existing_stock = float(value.replace(",", "."))
                except ValueError:
                    self.show_snackbar("Stock inválido")
                    return False
                if not is_weight and not float(existing_stock).is_integer():
                    self.show_snackbar("Stock deve ser inteiro para unidades")
                    return False
                if existing_stock < 0:
                    self.show_snackbar("Stock não pode ser negativo")
                    return False
            elif field == "price":
                try:
                    sale_price = float(value.replace(",", "."))
                except ValueError:
                    self.show_snackbar("Preço inválido")
                    return False
                if sale_price < 0:
                    self.show_snackbar("Preço não pode ser negativo")
                    return False
            elif field == "expiry":
                if not value:
                    expiry = None
                else:
                    # Aceita DD/MM/AAAA e 00/MM/AAAA
                    import re as _re
                    import calendar as _cal
                    parts = _re.findall(r"\d+", value)
                    if len(parts) < 2:
                        self.show_snackbar("Use DD/MM/AAAA ou 00/MM/AAAA")
                        return False
                    try:
                        if len(parts) == 2:
                            d, m, y = 0, int(parts[0]), int(parts[1])
                        else:
                            d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                        if y < 100:
                            y += 2000
                        if not (1 <= m <= 12) or y < 1990 or y > 2100:
                            raise ValueError("mês/ano")
                        if d == 0:
                            d = _cal.monthrange(y, m)[1]
                        elif not (1 <= d <= _cal.monthrange(y, m)[1]):
                            raise ValueError("dia")
                        expiry = f"{y:04d}-{m:02d}-{d:02d}"
                    except Exception:
                        self.show_snackbar("Data inválida")
                        return False
            else:
                return False

            ok = self.db.update_product(
                product_id,
                description,
                category,
                existing_stock,
                sold_stock,
                sale_price,
                total_purchase,
                unit_purchase,
                barcode=barcode,
                expiry_date=expiry,
                is_sold_by_weight=is_weight,
                package_quantity=package_quantity,
                units_per_package=units_per_package,
                allow_pack_sale=allow_pack_sale,
                vat_rule_code=vat_rule,
            )
            if not ok:
                self.show_snackbar("Não foi possível guardar (verifique permissões/dono)")
                return False
            self.show_snackbar("Produto atualizado")
            self.load_products(force=True)
            return True
        except Exception as exc:
            print(f"[InlineEdit] {exc}")
            self.show_snackbar(f"Erro ao guardar: {exc}")
            return False

    def _prompt_delete_product(self, product_id):
        normalized_id = self._normalize_product_id(product_id)
        if normalized_id is None:
            self.show_snackbar("Produto nao encontrado")
            return False

        tokens = self._theme_tokens()
        danger = tokens.get("danger", [0.9, 0.3, 0.3, 1])
        muted = tokens.get("text_secondary", [0.55, 0.58, 0.63, 1])

        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(12),
            padding=[dp(4), dp(8), dp(4), 0],
            size_hint_y=None,
        )
        content.bind(minimum_height=content.setter("height"))

        description = MDLabel(
            text=(
                "Produtos com vendas ou movimentos serão arquivados e removidos "
                "do catálogo. Produtos sem histórico serão eliminados definitivamente."
            ),
            theme_text_color="Custom",
            text_color=muted,
            font_style="Body2",
            halign="left",
            valign="top",
            size_hint_y=None,
        )
        self._bind_wrapped_label_height(description, min_height=dp(40))
        content.add_widget(description)

        cancel_btn = MDFlatButton(
            text="NÃO",
            theme_text_color="Custom",
            text_color=muted,
            radius=[dp(10)],
        )
        confirm_btn = MDRaisedButton(
            text="SIM, ELIMINAR",
            md_bg_color=danger,
            radius=[dp(10)],
        )

        dialog = MDDialog(
            title="Confirmar Eliminação",
            type="custom",
            content_cls=content,
            size_hint=(None, None),
            size=(min(dp(420), Window.width - dp(48)), dp(170)),
            buttons=[cancel_btn, confirm_btn],
        )
        cancel_btn.bind(on_release=lambda _x: dialog.dismiss())
        confirm_btn.bind(on_release=lambda _x, pid=normalized_id: self.confirm_delete(pid))
        dialog.bind(on_dismiss=lambda *_: setattr(self, "dialog", None))

        self.dialog = dialog
        self.dialog.open()
        return True
    def _handle_group_lot_menu_choice(self, group_product, lot_row, requested_action="select"):
        self._dismiss_lot_menu()
        selected_lot_id = self._normalize_product_id(lot_row[0] if lot_row else None)
        self._apply_group_lot_selection(group_product, selected_lot_id)

        normalized_action = str(requested_action or "").strip().lower()
        if normalized_action == "edit" and lot_row:
            self._open_product_editor(lot_row)
        elif normalized_action == "delete" and lot_row:
            self._prompt_delete_product(selected_lot_id)
        elif normalized_action == "view" and lot_row:
            self._open_product_details(lot_row)

    def _open_group_lot_selector(self, product, caller=None, requested_action="select"):
        if not product:
            self.show_snackbar("Produto nao encontrado")
            return False

        lot_rows = self._resolve_group_lot_rows(product)
        if not lot_rows:
            self._dismiss_lot_menu()
            self.load_products(force=True)
            self.show_snackbar("Nenhum lote disponivel para este grupo. A lista foi atualizada.")
            return False

        current_selected_id = self._get_group_selected_lot_id(product)
        normalized_action = str(requested_action or "").strip().lower()
        menu_items = []

        if normalized_action == "select":
            menu_items.append(
                {
                    "viewclass": "OneLineListItem",
                    "text": "Resumo do grupo",
                    "height": dp(44),
                    "on_release": lambda current=product: self._handle_group_lot_menu_choice(
                        current,
                        None,
                        "select",
                    ),
                }
            )

        for idx, lot_row in enumerate(lot_rows, start=1):
            lot_id = self._normalize_product_id(lot_row[0] if lot_row else None)
            menu_items.append(
                {
                    "viewclass": "OneLineListItem",
                    "text": self._format_lot_menu_text(
                        lot_row,
                        position=idx,
                        is_current=(lot_id == current_selected_id),
                    ),
                    "height": dp(46),
                    "on_release": (
                        lambda current=product, selected=lot_row, action=normalized_action:
                        self._handle_group_lot_menu_choice(current, selected, action)
                    ),
                }
            )

        self._dismiss_lot_menu()
        self._lot_menu = MDDropdownMenu(
            caller=caller,
            items=menu_items,
            width_mult=6.5,
            max_height=dp(320),
            position="bottom",
            hor_growth="right",
            ver_growth="down",
        )
        self._lot_menu.open()
        return True

    def open_group_lot_selector(self, instance):
        product = getattr(instance, "product_data", None)
        requested_action = getattr(instance, "requested_action", "select")
        return self._open_group_lot_selector(product, caller=instance, requested_action=requested_action)

    def create_detail_button(self, product, tokens=None):
        tokens = tokens or self._theme_tokens()
        btn = TooltipIconButton(
            icon="information",
            theme_text_color="Custom",
            text_color=tokens.get("info", [0.1, 0.3, 0.9, 1]),
            md_bg_color=tokens.get("card_alt", [0.92, 0.95, 1, 1]),
            icon_size=sp(19), size_hint=(None, None), size=(dp(36), dp(36)),
            radius=[dp(18)], elevation=0,
            hint_text="Ver detalhes",
        )
        btn.product_data = product
        if self._get_group_lot_count(product) > 1 and self._get_group_selected_lot_id(product) is not None:
            btn.hint_text = "Ver lote selecionado"
        btn.bind(on_release=self.show_product_details)
        return btn

    def create_edit_button(self, product, tokens=None):
        tokens = tokens or self._theme_tokens()
        btn = TooltipIconButton(
            icon="pencil",
            theme_text_color="Custom",
            text_color=tokens.get("success", [0.1, 0.65, 0.2, 1]),
            md_bg_color=tokens.get("card_alt", [0.92, 1, 0.92, 1]),
            icon_size=sp(19), size_hint=(None, None), size=(dp(36), dp(36)),
            radius=[dp(18)], elevation=0,
            hint_text="Editar produto",
        )
        btn.product_data = product
        if self._get_group_lot_count(product) > 1 and self._get_group_selected_lot_id(product) is None:
            btn.hint_text = "Selecionar lote para editar"
            btn.requested_action = "edit"
        elif self._get_group_lot_count(product) > 1:
            btn.hint_text = "Editar lote selecionado"
        btn.bind(on_release=self.edit_product)
        return btn

    def create_delete_button(self, product, tokens=None):
        tokens = tokens or self._theme_tokens()
        btn = TooltipIconButton(
            icon="delete",
            theme_text_color="Custom",
            text_color=tokens.get("danger", [0.9, 0.2, 0.2, 1]),
            md_bg_color=tokens.get("card_alt", [1, 0.92, 0.92, 1]),
            icon_size=sp(19), size_hint=(None, None), size=(dp(36), dp(36)),
            radius=[dp(18)], elevation=0,
            hint_text="Eliminar produto",
        )
        btn.product_data = product
        if self._get_group_lot_count(product) > 1 and self._get_group_selected_lot_id(product) is None:
            btn.hint_text = "Selecionar lote para eliminar"
            btn.requested_action = "delete"
        elif self._get_group_lot_count(product) > 1:
            btn.hint_text = "Eliminar lote selecionado"
        btn.bind(on_release=self.delete_product)
        return btn

    # ------------------------------------------------------------------
    # Product actions
    # ------------------------------------------------------------------
    def show_product_details(self, instance):
        product = getattr(instance, "product_data", None)
        self._open_product_details(product)

    def add_product(self):
        _get_product_form_class()(self).open()

    def edit_product(self, instance):
        product = getattr(instance, "product_data", None)
        if self._get_group_lot_count(product) > 1 and self._get_group_selected_lot_id(product) is None:
            self._open_group_lot_selector(product, caller=instance, requested_action="edit")
            return
        self._open_product_editor(product)

    def delete_product(self, instance):
        product = getattr(instance, "product_data", None)
        if self._get_group_lot_count(product) > 1 and self._get_group_selected_lot_id(product) is None:
            self._open_group_lot_selector(product, caller=instance, requested_action="delete")
            return
        self._prompt_delete_product(product[0] if product else None)

    def open_archived_products(self, *args):
        self._run_async_action(
            "load_archived_products", self.db.get_archived_products,
            on_success=self._show_archived_products,
            busy_message="A consultar produtos arquivados...",
            error_message="Nao foi possivel consultar o arquivo.",
        )

    def _show_archived_products(self, products):
        tokens = self._theme_tokens()
        primary = tokens.get("primary", [0.12, 0.46, 0.78, 1])
        foreground = tokens.get("text_primary", [0.92, 0.94, 0.97, 1])
        muted = tokens.get("text_secondary", [0.62, 0.67, 0.73, 1])
        surface = tokens.get("surface", [0.12, 0.14, 0.17, 1])
        surface_alt = tokens.get("card_alt", [0.15, 0.18, 0.23, 1])
        danger = tokens.get("danger", [0.95, 0.36, 0.32, 1])
        search = MDTextField(hint_text="Pesquisar nome, codigo de barras ou ID", multiline=False,
                             mode="rectangle", icon_right="magnify", size_hint_y=None, height=dp(56))
        search.md_bg_color = surface_alt
        search.foreground_color = foreground
        search.hint_text_color = muted
        search.line_color_focus = primary
        rows = MDBoxLayout(orientation="vertical", spacing=dp(8), padding=[0, dp(2), dp(8), dp(2)], size_hint_y=None)
        rows.bind(minimum_height=rows.setter("height"))
        def archive_list_height():
            # Duas fichas são suficientes para leitura imediata; o restante
            # continua disponível por scroll, sem abrir um modal gigante.
            visible = min(max(len(products or []), 1), 2)
            return max(dp(156), min(dp(250), visible * dp(116) + dp(8)))

        list_height = archive_list_height()
        scroll = ScrollView(size_hint_y=None, height=list_height, do_scroll_x=False, bar_width=dp(4))
        scroll.add_widget(rows)
        content = MDBoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None, height=list_height + dp(164))
        summary = MDCard(orientation="vertical", size_hint_y=None, height=dp(46), padding=[dp(12), dp(5)],
                         radius=[dp(10)], elevation=0, md_bg_color=[*primary[:3], .12],
                         line_color=[*primary[:3], .30], line_width=1)
        summary_title = MDLabel(text="Arquivo de produtos", bold=True, font_style="Body2",
                                theme_text_color="Custom", text_color=foreground,
                                size_hint_y=None, height=dp(18), halign="left", valign="middle")
        summary_text = MDLabel(text="Restaure itens mantendo stock e histórico. A validade é verificada automaticamente.",
                               theme_text_color="Custom", text_color=muted, font_style="Caption",
                               halign="left", valign="middle")
        for label in (summary_title, summary_text):
            label.bind(size=lambda widget, *_: setattr(widget, "text_size", (widget.width, None)))
            summary.add_widget(label)
        content.add_widget(summary)
        search.height = dp(50)
        content.add_widget(search)
        content.add_widget(scroll)
        navigation = MDBoxLayout(size_hint_y=None, height=dp(36))
        previous = MDFlatButton(text="ANTERIOR", text_color=primary, radius=[dp(10)])
        counter = MDLabel(halign="center", font_style="Caption", theme_text_color="Custom", text_color=muted)
        following = MDFlatButton(text="SEGUINTE", text_color=primary, radius=[dp(10)])
        for widget in (previous, counter, following):
            navigation.add_widget(widget)
        content.add_widget(navigation)
        close = MDFlatButton(text="FECHAR", text_color=primary, radius=[dp(10)])
        dialog = MDDialog(title="Produtos arquivados", type="custom", content_cls=content,
                          size_hint=(None, None), width=min(dp(920), Window.width - dp(48)),
                          radius=[dp(18)] * 4, buttons=[close])
        def resize_archive_dialog(*_):
            dialog.width = min(dp(920), Window.width - dp(48))
            scroll.height = archive_list_height()
            content.height = scroll.height + dp(164)
            dialog.update_height()
            if dialog._is_open:
                render()
        Window.unbind(on_resize=dialog.update_width)
        Window.bind(on_resize=resize_archive_dialog)
        dialog.bind(on_dismiss=lambda *_: Window.unbind(on_resize=resize_archive_dialog))
        close.bind(on_release=lambda *_: dialog.dismiss())
        # O MDDialog original calculava a altura antes de abrir. Sem este
        # passo, o ModalView nativo inicia nos 260dp e corta o topo do arquivo.
        resize_archive_dialog()
        page = {"index": 0}

        def restore(item):
            cancel = MDFlatButton(text="CANCELAR")
            confirm = MDRaisedButton(text="RESTAURAR")
            confirmation = MDDialog(title="Restaurar produto?",
                text=f"{item['description']} (#{item['id']}) voltara ao catalogo com o stock guardado. A validade sera verificada.",
                buttons=[cancel, confirm], auto_dismiss=False)
            cancel.bind(on_release=lambda *_: confirmation.dismiss())
            def execute(*_):
                confirmation.dismiss()
                app = App.get_running_app()
                username = getattr(app, "current_user", None)
                def on_success(result):
                    if result["ok"]:
                        products.remove(item)
                        render()
                        self.load_products(force=True)
                    self.show_snackbar(result["message"])
                self._run_async_action(
                    f"restore:{item['archive_source']}:{item['id']}",
                    lambda: self.db.restore_archived_product(item["id"], item["archive_source"], username=username),
                    on_success=on_success, busy_message="A restaurar produto...",
                    error_message="Nao foi possivel restaurar o produto.",
                )
            confirm.bind(on_release=execute)
            confirmation.open()

        def render(*_):
            query = search.text.strip().casefold()
            filtered = [item for item in products if query in
                        f"{item['id']} {item['description']} {item.get('barcode') or ''}".casefold()]
            pages = max(1, (len(filtered) + 19) // 20)
            page["index"] = min(page["index"], pages - 1)
            rows.clear_widgets()
            compact_rows = dialog.width < dp(650)
            for item in filtered[page["index"] * 20:(page["index"] + 1) * 20]:
                row = MDCard(orientation="vertical" if compact_rows else "horizontal", size_hint_y=None,
                             height=dp(164) if compact_rows else dp(116), spacing=dp(10) if compact_rows else dp(14),
                             padding=[dp(14), dp(10)], radius=[dp(12)], elevation=0, md_bg_color=surface,
                             line_color=[*primary[:3], .16], line_width=1)
                details = MDBoxLayout(orientation="vertical", spacing=dp(2))
                def add_line(text, color, style="Body2", bold=False, box=details):
                    label = MDLabel(text=text, theme_text_color="Custom", text_color=color,
                                    font_style=style, bold=bold, size_hint_y=None, height=dp(18),
                                    shorten=True, shorten_from="right", halign="left", valign="middle")
                    label.bind(size=lambda widget, *_: setattr(widget, "text_size", (widget.width, None)))
                    box.add_widget(label)
                add_line(str(item['description']), foreground, "Subtitle1", True)
                unit = "kg" if item.get("is_sold_by_weight") else "un."
                quantity = f"{float(item['existing_stock']):g}"
                add_line(f"ID #{item['id']}   |   Stock: {quantity} {unit}", muted)
                expiry = item.get("expiry_date")
                try:
                    expired = bool(expiry and datetime.fromisoformat(str(expiry)).date() < datetime.now().date())
                except ValueError:
                    expired = False
                expiry_text = self.format_date(str(expiry)) if expiry else "Sem validade"
                add_line(f"Validade: {expiry_text}" + ("   •   Expirado" if expired else ""), danger if expired else muted)
                add_line(f"Codigo de barras: {item.get('barcode') or 'Nao informado'}", muted, "Caption")
                if expired:
                    add_line("Ao restaurar, permanece bloqueado para venda por validade.", danger, "Caption")
                row.add_widget(details)
                button = MDRaisedButton(text="RESTAURAR",
                                        size_hint=(1, None) if compact_rows else (None, None),
                                        size=(dp(142), dp(40) if compact_rows else dp(42)),
                                        radius=[dp(10)], elevation=1,
                                        pos_hint={} if compact_rows else {"center_y": 0.5},
                                        md_bg_color=primary, theme_text_color="Custom",
                                        text_color=tokens.get("on_primary", [1, 1, 1, 1]))
                button.bind(on_release=lambda _, selected=item: restore(selected))
                row.add_widget(button)
                rows.add_widget(row)
            if not filtered:
                rows.add_widget(MDLabel(text="Nenhum produto arquivado encontrado.\nExperimente pesquisar por outro nome ou codigo." if query else "O arquivo esta vazio.\nOs produtos arquivados aparecerao aqui.",
                                       halign="center", theme_text_color="Custom", text_color=muted,
                                       size_hint_y=None, height=dp(110)))
            previous.disabled = page["index"] == 0
            following.disabled = page["index"] >= pages - 1
            counter.text = f"Pagina {page['index'] + 1} de {pages}  •  {len(filtered)} produtos"

        def change_page(delta):
            page["index"] += delta
            render()
            scroll.scroll_y = 1
        def search_changed(*_):
            page["index"] = 0
            render()
        previous.bind(on_release=lambda *_: change_page(-1))
        following.bind(on_release=lambda *_: change_page(1))
        search.bind(text=search_changed)
        render()
        dialog.open()

    def confirm_delete(self, product_id):
        app = App.get_running_app()
        username = getattr(app, "current_user", None)
        role = getattr(app, "current_role", "admin") if app else "admin"
        if getattr(self, "dialog", None):
            self.dialog.dismiss()

        def task():
            ok = self.db.delete_product(product_id, username=username)
            if ok and username:
                try:
                    self.db.log_action(username, role, "DELETE_PRODUCT", f"Produto removido do catálogo ID {product_id}")
                except Exception:
                    pass
            return ok

        def on_success(ok):
            if ok:
                self.load_products(force=True)
                self.show_snackbar("Produto removido do catálogo com sucesso!")
                return
            self.show_snackbar("Erro ao eliminar produto!")

        self._run_async_action(
            f"delete:{product_id}",
            task,
            on_success=on_success,
            busy_message="A eliminar produto...",
            error_message="Erro ao eliminar produto!",
        )

    # ------------------------------------------------------------------
    # Snackbar — CORRECAO 7: objecto reutilizável, sem memory leaks
    # ------------------------------------------------------------------
    def show_snackbar(self, message):
        message = correct_portuguese_text(message)
        # Dismiss o anterior se ainda estiver visível
        if self._snackbar is not None:
            try:
                self._snackbar.dismiss()
            except Exception:
                pass

        snackbar = MDSnackbar(
            MDLabel(
                text=str(message),
                theme_text_color="Custom",
                text_color=[1, 1, 1, 1],
            ),
            pos=(dp(10), dp(10)),
            size_hint_x=0.5,
        )
        self._snackbar = snackbar
        snackbar.open()

    def _get_alert_key(self, insights):
        low_stock = sorted([item[0] for item in insights.get("low_stock", [])])
        expiry_levels = insights.get("expiry_levels") or {}
        exp_vencido = sorted([item[0] for item in expiry_levels.get("vencido", [])])
        exp_critico = sorted([item[0] for item in expiry_levels.get("critico", [])])
        exp_alto = sorted([item[0] for item in expiry_levels.get("alto", [])])
        exp_medio = sorted([item[0] for item in expiry_levels.get("medio", [])])
        exp_leve = sorted([item[0] for item in expiry_levels.get("leve", [])])
        if not (exp_vencido or exp_critico or exp_alto or exp_medio or exp_leve):
            exp_critico = sorted([item[0] for item in insights.get("expiring_7", [])])
            exp_alto = sorted([item[0] for item in insights.get("expiring_15", [])])

        parts = []
        if low_stock:
            parts.append("ls:" + ",".join(low_stock))
        if exp_vencido:
            parts.append("ev:" + ",".join(exp_vencido))
        if exp_critico:
            parts.append("ec:" + ",".join(exp_critico))
        if exp_alto:
            parts.append("ea:" + ",".join(exp_alto))
        if exp_medio:
            parts.append("em:" + ",".join(exp_medio))
        if exp_leve:
            parts.append("el:" + ",".join(exp_leve))
        fraud_alerts = [
            item for item in list(insights.get("fraud_alerts") or [])
            if isinstance(item, dict)
        ]
        if fraud_alerts:
            fraud_key_parts = []
            for item in fraud_alerts:
                fraud_key_parts.append(
                    ":".join(
                        str(item.get(field) or "").strip()
                        for field in (
                            "alert_type",
                            "severity",
                            "title",
                            "description",
                            "related_user",
                            "related_product_id",
                            "related_movement_id",
                        )
                    )
                )
            parts.append("fr:" + ",".join(sorted(fraud_key_parts)))
        return "|".join(parts)

    def mark_notifications_seen(self, insights=None):
        insights = insights or self._cached_admin_insights or {}
        key = self._get_alert_key(insights) if insights else ""
        app = App.get_running_app()
        if app:
            app._ai_notifications_seen_key = key
        self.update_notification_badge(0)

    def _refresh_alerts_async(self, show_popups=True):
        return False

    def _apply_alerts_refresh(self, insights, token, show_popups):
        if token != self._alerts_refresh_token:
            return
        self._cached_admin_insights = insights or {}
        self.update_ai_badge(insights=self._cached_admin_insights)
        if show_popups:
            self.show_auto_ai_popups(insights=self._cached_admin_insights)

    def _load_ai_insights_async(self, target):
        return False

    def _apply_ai_insights_result(self, kind, insights, token):
        if token != self._ai_popup_token:
            return
        self._render_ai_insights(kind, insights or {})

    def _render_ai_insights(self, kind, insights):
        if not hasattr(self, "ids") or "ai_banner_container" not in self.ids:
            return

        (build_auto_banner_data, build_banner_details_sections,
         build_positive_banner, render_auto_banners) = _get_ai_popup_helpers()
        banners = build_auto_banner_data(insights)
        low_stock = insights.get("low_stock") or []
        expiry_levels = insights.get("expiry_levels") or {}
        expiring_any = (
            (expiry_levels.get("vencido") or [])
            + (expiry_levels.get("critico") or [])
            + (expiry_levels.get("alto") or [])
            + (expiry_levels.get("medio") or [])
            + (expiry_levels.get("leve") or [])
        )
        if not expiring_any:
            expiring_any = (insights.get("expiring_7") or []) + (insights.get("expiring_15") or [])
        has_stock = bool(low_stock)
        has_expiry = bool(expiring_any)

        if kind == "stock":
            banners = [b for b in banners if b.get("kind") == "stock"]
            if not banners:
                banners = [build_positive_banner("stock")]
        elif kind == "expiry":
            banners = [b for b in banners if b.get("kind") == "expiry"]
            if not banners:
                banners = [build_positive_banner("expiry")]
        else:
            if has_stock and not has_expiry:
                banners.append(build_positive_banner("expiry"))
            elif has_expiry and not has_stock:
                banners.append(build_positive_banner("stock"))
            if not banners:
                return

        for banner in banners:
            banner["details_sections"] = build_banner_details_sections(
                insights,
                banner.get("kind"),
                max_lines=3,
                expiry_level=banner.get("expiry_level"),
            )
        target_container = self.ids.ai_banner_container
        ensure_center = getattr(self._get_intelligence(), "_ensure_banner_center", None)
        if callable(ensure_center):
            try:
                target_container = ensure_center()
            except Exception:
                target_container = self.ids.ai_banner_container
        render_auto_banners(
            target_container,
            banners,
            insights=insights,
            auto_dismiss_seconds=None,
            show_timer=False,
        )
        self.mark_notifications_seen(insights)

    def show_ai_insights(self, *args):
        caller = self.ids.ai_button if hasattr(self, "ids") and "ai_button" in self.ids else None
        self._get_intelligence().open_alerts(caller=caller)

    def open_ai_menu(self, caller):
        if caller is None and hasattr(self, "ids") and "ai_button" in self.ids:
            caller = self.ids.ai_button
        self._get_intelligence().open_alerts(caller=caller)

    def show_ai_recommendations(self, caller=None):
        if caller is None and hasattr(self, "ids") and "recommendations_button" in self.ids:
            caller = self.ids.recommendations_button
        self._get_intelligence().open_recommendations(caller=caller)

    def _open_ai_from_menu(self, key):
        if hasattr(self, "_ai_menu") and self._ai_menu:
            self._ai_menu.dismiss()
        caller = self.ids.ai_button if hasattr(self, "ids") and "ai_button" in self.ids else None
        self._get_intelligence().open_alerts(caller=caller)

    def show_ai_stock_popup(self, *args, insights=None, on_close=None):
        return None

    def show_ai_expiry_popup(self, *args, insights=None, on_close=None):
        return None

    def show_auto_ai_popups(self, *args, insights=None):
        return None

    def update_ai_badge(self, *args, insights=None):
        insights = insights or self._cached_admin_insights or {}
        if not insights:
            self.update_notification_badge(0)
            self.update_loss_alert_badges(0)
            return
        key = self._get_alert_key(insights)
        badge_counts = insights.get("badge_counts") or {}
        count = badge_counts.get("total", 0)
        fraud_count = badge_counts.get("fraud", len(insights.get("fraud_alerts") or []))

        if not key:
            count = 0

        app = App.get_running_app()
        if app and getattr(app, "_ai_notifications_seen_key", None) == key:
            count = 0

        self.update_notification_badge(count)
        self.update_loss_alert_badges(fraud_count)

    def _stop_ai_polling(self):
        if self._intelligence is not None:
            self._intelligence.stop()

    # ------------------------------------------------------------------
    # Sugestoes de compras
    # ------------------------------------------------------------------
    @staticmethod
    def _shopping_text_key(value):
        return " ".join(str(value or "").strip().lower().split())

    @staticmethod
    def _average_non_zero(values, default=0.0):
        clean_values = [_safe_float(value) for value in values if _safe_float(value) > 0]
        if not clean_values:
            return default
        return sum(clean_values) / len(clean_values)

    def _parse_shopping_date(self, value):
        parsed = self._parse_group_date(value)
        if parsed is None:
            return None
        return parsed.date()

    def _normalize_shopping_source_row(self, row, source="stock_control"):
        if not row:
            return None

        def get(index, default=None):
            return row[index] if len(row) > index else default

        is_restock_source = source == "restock"
        avg_index = 10 if is_restock_source else 9
        days_index = 11 if is_restock_source else 10
        last_update_index = None if is_restock_source else 11

        return {
            "product_id": self._normalize_product_id(get(0)),
            "name": str(get(1, "") or "").strip() or "Produto sem nome",
            "stock": _safe_float(get(2), 0.0),
            "sale_price": _safe_float(get(3), 0.0),
            "unit_cost": _safe_float(get(4), 0.0),
            "barcode": str(get(5, "") or "").strip(),
            "is_weight": bool(get(6, 0)),
            "expiry_date": get(7),
            "status": str(get(8, "") or "").strip(),
            "avg_daily": _safe_float(get(avg_index), 0.0),
            "days_left": None if get(days_index) is None else _safe_float(get(days_index), None),
            "last_update": get(last_update_index) if last_update_index is not None else None,
            # A consulta enriquecida acrescenta as saídas acumuladas no fim da
            # linha. Este valor é usado para o mesmo limite crítico do painel.
            "sold_stock": _safe_float(get(12), 0.0),
        }

    def _shopping_group_key(self, item):
        barcode = str(item.get("barcode") or "").strip().lower()
        if barcode:
            return f"bc:{barcode}"
        name = self._shopping_text_key(item.get("name"))
        sale_price = round(_safe_float(item.get("sale_price"), 0.0), 4)
        weight_flag = 1 if item.get("is_weight") else 0
        return f"name:{name}|w:{weight_flag}|p:{sale_price:.4f}"

    def _group_shopping_products(self, rows, source="stock_control"):
        buckets = {}
        ordered_keys = []

        for row in rows or []:
            item = self._normalize_shopping_source_row(row, source=source)
            if not item:
                continue
            key = self._shopping_group_key(item)
            bucket = buckets.get(key)
            if bucket is None:
                bucket = {
                    "product_ids": [],
                    "name": item["name"],
                    "barcode": item["barcode"],
                    "is_weight": item["is_weight"],
                    "stock": 0.0,
                    "avg_daily": 0.0,
                    "sold_stock": 0.0,
                    "lot_count": 0,
                    "cost_weight_total": 0.0,
                    "cost_weight_qty": 0.0,
                    "price_weight_total": 0.0,
                    "price_weight_qty": 0.0,
                    "cost_values": [],
                    "price_values": [],
                    "expiry_date": None,
                    "statuses": set(),
                    "last_update": None,
                }
                buckets[key] = bucket
                ordered_keys.append(key)

            product_id = item.get("product_id")
            if product_id is not None and product_id not in bucket["product_ids"]:
                bucket["product_ids"].append(product_id)

            stock_value = max(0.0, _safe_float(item.get("stock"), 0.0))
            unit_cost = _safe_float(item.get("unit_cost"), 0.0)
            sale_price = _safe_float(item.get("sale_price"), 0.0)
            bucket["stock"] += stock_value
            bucket["avg_daily"] += max(0.0, _safe_float(item.get("avg_daily"), 0.0))
            bucket["sold_stock"] += max(0.0, _safe_float(item.get("sold_stock"), 0.0))
            bucket["lot_count"] += 1

            if stock_value > 0:
                bucket["cost_weight_total"] += unit_cost * stock_value
                bucket["cost_weight_qty"] += stock_value
                bucket["price_weight_total"] += sale_price * stock_value
                bucket["price_weight_qty"] += stock_value
            if unit_cost > 0:
                bucket["cost_values"].append(unit_cost)
            if sale_price > 0:
                bucket["price_values"].append(sale_price)

            expiry = self._parse_shopping_date(item.get("expiry_date"))
            if expiry is not None and (
                bucket["expiry_date"] is None or expiry < bucket["expiry_date"]
            ):
                bucket["expiry_date"] = expiry

            status = str(item.get("status") or "").strip()
            if status:
                bucket["statuses"].add(status)

            last_update = item.get("last_update")
            if last_update and (
                not bucket["last_update"] or str(last_update) > str(bucket["last_update"])
            ):
                bucket["last_update"] = last_update

        grouped = []
        for key in ordered_keys:
            bucket = buckets[key]
            unit_cost = (
                bucket["cost_weight_total"] / bucket["cost_weight_qty"]
                if bucket["cost_weight_qty"] > 0
                else self._average_non_zero(bucket["cost_values"], 0.0)
            )
            sale_price = (
                bucket["price_weight_total"] / bucket["price_weight_qty"]
                if bucket["price_weight_qty"] > 0
                else self._average_non_zero(bucket["price_values"], 0.0)
            )
            avg_daily = _safe_float(bucket["avg_daily"], 0.0)
            stock_value = _safe_float(bucket["stock"], 0.0)
            days_left = (stock_value / avg_daily) if avg_daily > 0 else None

            grouped.append({
                "product_ids": tuple(bucket["product_ids"]),
                "name": bucket["name"],
                "barcode": bucket["barcode"],
                "is_weight": bucket["is_weight"],
                "stock": stock_value,
                "avg_daily": avg_daily,
                "sold_stock": _safe_float(bucket["sold_stock"], 0.0),
                "days_left": days_left,
                "unit_cost": unit_cost,
                "sale_price": sale_price,
                "expiry_date": bucket["expiry_date"],
                "lot_count": bucket["lot_count"],
                "statuses": tuple(sorted(bucket["statuses"])),
                "last_update": bucket["last_update"],
            })

        return grouped

    def _build_shopping_list_payload(self, rows, source="stock_control", *, use_ai=False):
        # Compras sao preventivas: avaliamos se o stock cobre as proximas tres
        # semanas e calculamos uma reposicao para cerca de um mes de procura.
        # Assim a lista reflete a rapidez de saida, sem esperar pelo esgotamento.
        target_days = 30
        warning_days = 21

        grouped_products = self._group_shopping_products(rows, source=source)
        candidates = build_demand_purchase_candidates(
            grouped_products,
            target_days=target_days,
            warning_days=warning_days,
        )
        api_context_by_barcode = load_product_api_context(grouped_products)
        for item in candidates:
            api_context = api_context_by_barcode.get(normalize_barcode(item.get("barcode")))
            if api_context:
                item["api_context"] = api_context

        analysis = build_ai_purchase_suggestions(candidates, use_ai=use_ai)
        items = list(analysis.get("items") or [])

        total_investment = sum(_safe_float(item.get("purchase_cost")) for item in items)
        total_revenue = sum(_safe_float(item.get("potential_revenue")) for item in items)
        total_profit = sum(_safe_float(item.get("potential_profit")) for item in items)
        unit_qty = sum(
            _safe_float(item.get("needed_qty"))
            for item in items
            if item.get("unit") == "UN"
        )
        kg_qty = sum(
            _safe_float(item.get("needed_qty"))
            for item in items
            if item.get("unit") == "KG"
        )

        summary = {
            "total_items": len(items),
            "out_of_stock_count": sum(
                1 for item in items if _safe_float(item.get("current_stock"), 0.0) <= 0
            ),
            "critical_count": sum(1 for item in items if item.get("priority") in {"Urgente", "Alta"}),
            "low_count": sum(1 for item in items if item.get("priority") == "Media"),
            "total_investment": total_investment,
            "total_potential_revenue": total_revenue,
            "total_potential_profit": total_profit,
            "unit_qty": unit_qty,
            "kg_qty": kg_qty,
            "velocity_days": 14,
            "target_days": target_days,
            "warning_days": warning_days,
            "source": source,
            "analysis_source": analysis.get("source") or "demand",
            "ai_used": bool(analysis.get("ai_used")),
            "api_product_count": int(analysis.get("api_product_count") or 0),
            "empty_reason": (
                "Não há produtos esgotados, abaixo do limite crítico ou com saída rápida "
                "que precisem de reposição agora."
                if not items else ""
            ),
        }
        return {"items": items, "summary": summary}

    def _load_shopping_list_payload(self, *, use_ai=False):
        source = "stock_control"
        rows = self.db.get_products_for_stock_control(
            include_velocity=True,
            velocity_days=14,
        ) or []
        if not rows:
            source = "restock"
            rows = self.db.get_products_for_restock(
                include_velocity=True,
                velocity_days=14,
            ) or []
        return self._build_shopping_list_payload(rows, source=source, use_ai=use_ai)

    def _format_shopping_qty(self, value, unit):
        amount = _safe_float(value, 0.0)
        if str(unit or "").upper() == "KG":
            return f"{amount:.2f} KG"
        return f"{int(round(amount))} UN"

    def _format_shopping_money(self, value):
        return self._format_money(value)

    def _make_shopping_preview_label(self, text, width_hint, halign="left", bold=False):
        label = MDLabel(
            text=str(text or "-"),
            size_hint_x=width_hint,
            halign=halign,
            valign="middle",
            bold=bold,
            font_size=dp(11.5),
            theme_text_color="Custom",
            text_color=self._theme_tokens().get("text_primary", [0.15, 0.18, 0.24, 1]),
            shorten=True,
            shorten_from="right",
        )
        return label

    def _build_shopping_preview_row(self, item=None, index=0, header=False):
        tokens = self._theme_tokens()
        row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(38 if not header else 34),
            padding=[dp(8), 0, dp(8), 0],
            spacing=dp(8),
            md_bg_color=(
                tokens.get("surface_alt", [0.95, 0.96, 0.98, 1])
                if header or index % 2 == 0
                else tokens.get("card", [1, 1, 1, 1])
            ),
        )
        if header:
            values = ("Produto", "Qtd.", "Preco", "Total")
            bold = True
        else:
            unit = (item or {}).get("unit") or "UN"
            values = (
                (item or {}).get("name") or "Produto",
                self._format_shopping_qty((item or {}).get("needed_qty"), unit),
                self._format_shopping_money((item or {}).get("unit_cost")),
                self._format_shopping_money((item or {}).get("purchase_cost")),
            )
            bold = False

        row.add_widget(self._make_shopping_preview_label(values[0], 0.48, "left", bold))
        row.add_widget(self._make_shopping_preview_label(values[1], 0.16, "center", bold))
        row.add_widget(self._make_shopping_preview_label(values[2], 0.18, "right", bold))
        row.add_widget(self._make_shopping_preview_label(values[3], 0.18, "right", bold))
        return row

    def _show_shopping_list_preview(self, payload):
        from kivy.uix.scrollview import ScrollView

        if self._shopping_list_dialog is not None:
            try:
                self._shopping_list_dialog.dismiss()
            except Exception:
                pass
            self._shopping_list_dialog = None

        items = list((payload or {}).get("items") or [])
        summary = (payload or {}).get("summary") or {}
        tokens = self._theme_tokens()
        primary = tokens.get("primary", [0.12, 0.46, 0.78, 1])
        foreground = tokens.get("text_primary", [0.15, 0.18, 0.24, 1])
        muted = tokens.get("text_secondary", [0.35, 0.39, 0.46, 1])
        card_alt = tokens.get("card_alt", [0.94, 0.96, 0.98, 1])
        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(12),
            padding=[dp(2), dp(2), dp(2), 0],
            size_hint_y=1,
        )

        source_label = "IA + procura" if summary.get("ai_used") else "Procura analisada"
        api_count = int(summary.get("api_product_count") or 0)
        api_label = f" | APIs: {api_count} produtos" if api_count else ""
        overview = MDBoxLayout(size_hint_y=None, height=dp(72), spacing=dp(8))

        def metric_card(title, value, accent):
            card = MDCard(orientation="vertical", padding=[dp(10), dp(8)], radius=[dp(10)], elevation=0,
                          md_bg_color=card_alt, line_color=[*accent[:3], .30], line_width=1)
            card.add_widget(MDLabel(text=title.upper(), font_style="Caption", theme_text_color="Custom",
                                    text_color=muted, size_hint_y=None, height=dp(18)))
            card.add_widget(MDLabel(text=value, bold=True, font_style="Body2", theme_text_color="Custom",
                                    text_color=accent, halign="left", valign="middle"))
            return card

        urgency = int(summary.get("critical_count") or 0)
        overview.add_widget(metric_card("Itens a repor", str(len(items)), primary))
        overview.add_widget(metric_card("Custo estimado", self._format_shopping_money(summary.get("total_investment")), primary))
        overview.add_widget(metric_card("Prioridade", f"{urgency} crítica(s)" if urgency else source_label, tokens.get("danger", primary) if urgency else primary))
        content.add_widget(overview)
        if not items:
            empty_label = MDLabel(
                text=(
                    summary.get("empty_reason")
                    or "Nao ha sugestoes de compras para a procura atual."
                ),
                size_hint_y=None,
                height=dp(78),
                halign="left",
                valign="middle",
                theme_text_color="Custom",
                text_color=self._theme_tokens().get("text_secondary", [0.35, 0.39, 0.46, 1]),
            )
            empty_label.bind(size=lambda instance, value: setattr(instance, "text_size", value))
            content.add_widget(empty_label)
            close_btn = MDFlatButton(text="FECHAR", text_color=primary, radius=[dp(10)])
            dialog = MDDialog(
                title="Sugestoes de Compras",
                type="custom",
                content_cls=content,
                size_hint=(None, None),
                size=(min(dp(680), Window.width * 0.9), min(dp(340), Window.height * 0.55)),
                buttons=[close_btn],
            )
            close_btn.bind(on_release=lambda _btn: dialog.dismiss())
            dialog.bind(
                on_dismiss=lambda *_args: (
                    setattr(self, "_shopping_list_dialog", None)
                    if self._shopping_list_dialog is dialog else None
                )
            )
            self._shopping_list_dialog = dialog
            dialog.open()
            return
        table_title = MDLabel(text="Itens sugeridos", bold=True, font_style="Body2", theme_text_color="Custom",
                              text_color=foreground, size_hint_y=None, height=dp(22))
        content.add_widget(table_title)

        visible_items = min(max(len(items), 1), 3)
        list_height = max(dp(150), min(dp(300), visible_items * dp(86) + max(0, visible_items - 1) * dp(8)))
        scroll = ScrollView(
            do_scroll_x=False,
            do_scroll_y=True,
            size_hint_y=None,
            height=list_height,
            bar_width=dp(6),
        )
        rows_box = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(8),
        )
        rows_box.bind(minimum_height=rows_box.setter("height"))
        for item in items:
            unit = (item or {}).get("unit") or "UN"
            item_card = MDCard(orientation="vertical", size_hint_y=None, height=dp(86),
                               padding=[dp(12), dp(8)], spacing=dp(4), radius=[dp(10)], elevation=0,
                               md_bg_color=card_alt, line_color=[*primary[:3], .16], line_width=1)
            item_card.add_widget(MDLabel(text=(item or {}).get("name") or "Produto", bold=True,
                                         font_style="Body2", theme_text_color="Custom", text_color=foreground,
                                         shorten=True, shorten_from="right", halign="left", valign="middle",
                                         size_hint_y=None, height=dp(20)))
            values = MDBoxLayout(size_hint_y=None, height=dp(34), spacing=dp(8))
            for title, value in (
                ("QUANTIDADE", self._format_shopping_qty((item or {}).get("needed_qty"), unit)),
                ("PREÇO UNIT.", self._format_shopping_money((item or {}).get("unit_cost"))),
                ("TOTAL", self._format_shopping_money((item or {}).get("purchase_cost"))),
            ):
                metric = MDBoxLayout(orientation="vertical")
                metric.add_widget(MDLabel(text=title, font_style="Caption", theme_text_color="Custom", text_color=muted))
                metric.add_widget(MDLabel(text=value, bold=True, font_style="Caption", theme_text_color="Custom",
                                          text_color=primary if title == "TOTAL" else foreground, halign="left"))
                values.add_widget(metric)
            item_card.add_widget(values)
            rows_box.add_widget(item_card)
        scroll.add_widget(rows_box)
        content.add_widget(scroll)

        dialog_height = min(dp(600), max(dp(430), list_height + dp(292)))
        dialog = MDDialog(
            title="Sugestoes de Compras",
            type="custom",
            content_cls=content,
            size_hint=(None, None),
            size=(min(dp(760), Window.width * 0.92), min(dialog_height, Window.height * 0.88)),
            buttons=[
                MDFlatButton(text="FECHAR", text_color=primary, radius=[dp(10)],
                             on_release=lambda _btn: dialog.dismiss()),
                MDRaisedButton(
                    text="GERAR PDF",
                    md_bg_color=primary,
                    radius=[dp(10)],
                    on_release=lambda _btn, data=payload: self.generate_shopping_list_pdf(
                        payload=data,
                        dialog=dialog,
                    ),
                ),
            ],
        )
        dialog.bind(
            on_dismiss=lambda *_args: (
                setattr(self, "_shopping_list_dialog", None)
                if self._shopping_list_dialog is dialog else None
            )
        )
        self._shopping_list_dialog = dialog
        dialog.open()

    def open_shopping_list_preview(self, *args):
        if self.shopping_list_busy or "shopping-list-preview" in self._async_actions:
            return

        self.shopping_list_busy = True

        def task():
            try:
                # A previsão local é imediata e já considera a procura, o
                # nível crítico e os produtos esgotados. A IA é atualizada
                # depois, sem segurar esta janela.
                payload = self._load_shopping_list_payload(use_ai=False)
                return {"status": "ok", "payload": payload}
            except Exception as exc:
                return {"status": "error", "message": str(exc)}

        def on_success(result):
            self.shopping_list_busy = False
            status = (result or {}).get("status")
            if status == "ok":
                payload = (result or {}).get("payload") or {}
                self._shopping_list_payload = payload
                self._show_shopping_list_preview(payload)
                self._warm_shopping_list_ai()
                return
            message = (result or {}).get("message") or "Erro ao preparar sugestoes de compras."
            self.show_snackbar(f"Erro ao preparar sugestoes de compras: {message}")

        started = self._run_async_action(
            "shopping-list-preview",
            task,
            on_success=on_success,
            busy_message=None,
            error_message="Erro ao preparar sugestoes de compras",
        )
        if not started:
            self.shopping_list_busy = False

    def _warm_shopping_list_ai(self):
        """Atualiza o cache de IA sem atrasar a abertura das sugestões."""
        if "shopping-list-ai-warmup" in self._async_actions:
            return

        def task():
            try:
                return self._load_shopping_list_payload(use_ai=True)
            except Exception:
                return None

        def on_success(payload):
            # A janela já aberta continua estável; a próxima abertura e o PDF
            # usam a análise já refinada e devolvida do cache.
            if payload and payload.get("summary", {}).get("ai_used"):
                self._shopping_list_payload = payload

        self._run_async_action(
            "shopping-list-ai-warmup",
            task,
            on_success=on_success,
            busy_message=None,
            error_message=None,
        )

    def generate_shopping_list_pdf(self, *args, payload=None, dialog=None):
        if self.shopping_list_busy or "shopping-list-pdf" in self._async_actions:
            return

        self.shopping_list_busy = True
        payload_snapshot = dict(payload or self._shopping_list_payload or {})

        def task():
            try:
                export_payload = payload_snapshot or self._load_shopping_list_payload()
                if not export_payload.get("items"):
                    return {"status": "empty"}

                filters = {
                    "velocity_days": export_payload["summary"].get("velocity_days", 14),
                    "target_days": export_payload["summary"].get("target_days", 14),
                    "warning_days": export_payload["summary"].get("warning_days", 7),
                    "source_label": "Sugestoes de compras",
                    "analysis_source": export_payload["summary"].get("analysis_source", "demand"),
                    "api_product_count": export_payload["summary"].get("api_product_count", 0),
                }
                pdf_path = self._ensure_shopping_list_report().generate(export_payload, filters)
                return {
                    "status": "ok",
                    "pdf_path": pdf_path,
                    "item_count": len(export_payload.get("items") or []),
                }
            except Exception as exc:
                return {"status": "error", "message": str(exc)}

        def on_success(result):
            self.shopping_list_busy = False
            status = (result or {}).get("status")
            if status == "ok":
                if dialog is not None:
                    try:
                        dialog.dismiss()
                    except Exception:
                        pass
                self._show_pdf_success((result or {}).get("pdf_path"))
                return
            if status == "empty":
                self.show_snackbar("Nenhuma sugestao de compra para a procura atual.")
                return
            message = (result or {}).get("message") or "Erro ao gerar sugestoes de compras."
            self.show_snackbar(f"Erro ao gerar sugestoes de compras: {message}")

        started = self._run_async_action(
            "shopping-list-pdf",
            task,
            on_success=on_success,
            busy_message="A gerar sugestoes de compras...",
            error_message="Erro ao gerar sugestoes de compras",
        )
        if not started:
            self.shopping_list_busy = False

    # ------------------------------------------------------------------
    # Reports & filter toggle
    # ------------------------------------------------------------------
    def generate_report(self):
        if not self.manager:
            return
        reports_screen = self._set_back_target("reports", "admin")
        if not reports_screen:
            return
        self.manager.current = "reports"
        if hasattr(reports_screen, "prepare_open_from_admin"):
            Clock.schedule_once(lambda dt: reports_screen.prepare_open_from_admin(), 0.04)

    def toggle_kg_products(self):
        if not hasattr(self, 'filter_mode'):
            self.filter_mode = 0

        self.filter_mode = (self.filter_mode + 1) % 3

        if self.filter_mode == 1:
            message = "Mostrando apenas produtos vendidos por KG"
        elif self.filter_mode == 2:
            message = "Mostrando apenas produtos vendidos por unidade"
        else:
            message = "Mostrando todos os produtos"

        if not self._aggregated_products_cache and not self.products:
            self.load_products()
            self.show_snackbar("A carregar produtos para aplicar filtro...")
            return

        self.filter_products(
            self.search_input.text if self.search_input else self._pending_search,
            reset_page=True,
        )
        self.show_snackbar(message)

    def open_losses_screen(self, *args):
        if not self.manager:
            return
        screen = self._set_back_target("losses", "admin")
        if not screen:
            return
        self.manager.current = "losses"
        if hasattr(screen, "prepare_open_from_admin"):
            Clock.schedule_once(lambda dt: screen.prepare_open_from_admin(), 0.02)
            return
        if hasattr(screen, "request_enter_refresh"):
            Clock.schedule_once(lambda dt: screen.request_enter_refresh(force=False, delay=0.02), 0.02)
            return
        Clock.schedule_once(lambda dt: screen.load_products(), 0.1)

    def open_restock_screen(self, *args):
        if not self.manager:
            return
        screen = self._set_back_target("restock", "admin")
        if not screen:
            return
        self.manager.current = "restock"
        if hasattr(screen, "prepare_open_from_admin"):
            Clock.schedule_once(lambda dt: screen.prepare_open_from_admin("IN"), 0.02)
            return
        if hasattr(screen, "request_enter_refresh"):
            Clock.schedule_once(lambda dt: screen.request_enter_refresh(force=False, delay=0.02), 0.02)
            return
        Clock.schedule_once(lambda dt: screen.load_products(), 0.1)

    def open_physical_inventory(self, *args):
        try:
            active = self.db.get_active_physical_inventory()
        except Exception as exc:
            self.show_snackbar(f"Erro ao consultar inventario: {exc}")
            return
        if active:
            self._show_physical_inventory_workspace(active)
            return

        name_input = MDTextField(
            hint_text="Nome do inventario",
            text=f"Inventario {datetime.now().strftime('%d/%m/%Y')}",
            multiline=False,
        )
        note_input = MDTextField(hint_text="Observacao (opcional)", multiline=False)
        content = MDBoxLayout(orientation="vertical", spacing=dp(10), size_hint_y=None, height=dp(120))
        content.add_widget(name_input)
        content.add_widget(note_input)
        cancel_btn = MDFlatButton(text="CANCELAR")
        history_btn = MDFlatButton(text="HISTORICO")
        start_btn = MDRaisedButton(text="INICIAR CONTAGEM")
        dialog = MDDialog(
            title="Novo inventario fisico",
            type="custom", content_cls=content, buttons=[cancel_btn, history_btn, start_btn],
        )
        cancel_btn.bind(on_release=lambda _b: dialog.dismiss())
        history_btn.bind(on_release=lambda _b: (dialog.dismiss(), self.show_physical_inventory_history()))

        def start(_button):
            app = App.get_running_app()
            actor = getattr(app, "current_user", None) or "admin"
            terminal = os.environ.get("COMPUTERNAME") or "ADMIN"
            result = self.db.start_physical_inventory(name_input.text, actor, terminal, note_input.text)
            if not result.get("ok"):
                self.show_snackbar(result.get("message") or "Falha ao iniciar inventario")
                return
            dialog.dismiss()
            self.show_snackbar(f"Inventario iniciado com {result.get('item_count', 0)} produtos")
            self._show_physical_inventory_workspace(result.get("inventory") or {})

        start_btn.bind(on_release=start)
        dialog.open()

    def show_physical_inventory_history(self):
        rows = self.db.list_physical_inventories(limit=100) or []
        tokens = self._theme_tokens()
        primary = tokens.get("primary", [0.12, 0.46, 0.78, 1])
        foreground = tokens.get("text_primary", [0.15, 0.18, 0.24, 1])
        muted = tokens.get("text_secondary", [0.35, 0.39, 0.46, 1])
        card_alt = tokens.get("card_alt", [0.94, 0.96, 0.98, 1])
        status_colors = {
            "COUNTING": tokens.get("warning", primary),
            "COMPLETED": tokens.get("success", primary),
            "CANCELLED": tokens.get("danger", primary),
        }
        container = MDBoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None)
        container.bind(minimum_height=container.setter("height"))
        if not rows:
            container.add_widget(MDLabel(text="Ainda não há inventários registados.", halign="center",
                                         theme_text_color="Custom", text_color=muted,
                                         size_hint_y=None, height=dp(72)))
        status_labels = {"COUNTING": "Em contagem", "COMPLETED": "Concluido", "CANCELLED": "Cancelado"}
        for item in rows:
            finished_at = item.get("completed_at") or item.get("cancelled_at") or "-"
            status = str(item.get("status") or "").upper()
            accent = status_colors.get(status, primary)
            card = MDCard(orientation="vertical", size_hint_y=None, height=dp(104), spacing=dp(5),
                          padding=[dp(12), dp(9)], radius=[dp(10)], elevation=0,
                          md_bg_color=card_alt, line_color=[*accent[:3], .28], line_width=1)
            header = MDBoxLayout(size_hint_y=None, height=dp(20), spacing=dp(8))
            header.add_widget(MDLabel(text=f"#{item.get('id')}  {item.get('name') or 'Inventário'}", bold=True,
                                      shorten=True, shorten_from="right", theme_text_color="Custom",
                                      text_color=foreground, halign="left"))
            header.add_widget(MDLabel(text=status_labels.get(status, status or "-"), bold=True,
                                      size_hint_x=None, width=dp(102), halign="right", theme_text_color="Custom",
                                      text_color=accent, font_style="Caption"))
            card.add_widget(header)
            period = MDLabel(text=f"Início: {item.get('started_at') or '-'}   •   Fim: {finished_at}",
                             size_hint_y=None, height=dp(18), shorten=True, shorten_from="right",
                             theme_text_color="Custom", text_color=muted, font_style="Caption")
            card.add_widget(period)
            metrics = MDBoxLayout(size_hint_y=None, height=dp(28), spacing=dp(8))
            for label, value, color in (
                ("CONTADOS", f"{item.get('counted_items', 0)}/{item.get('total_items', 0)}", primary),
                ("DIVERGÊNCIAS", str(item.get('divergent_items', 0)), tokens.get("danger", primary)),
            ):
                metric = MDBoxLayout(orientation="horizontal", spacing=dp(5))
                metric.add_widget(MDLabel(text=label, font_style="Caption", theme_text_color="Custom", text_color=muted))
                metric.add_widget(MDLabel(text=value, bold=True, font_style="Caption", theme_text_color="Custom", text_color=color))
                metrics.add_widget(metric)
            card.add_widget(metrics)
            container.add_widget(card)
        visible_rows = min(max(len(rows), 1), 3)
        list_height = max(dp(104), min(dp(328), visible_rows * dp(104) + max(0, visible_rows - 1) * dp(8)))
        scroll = ScrollView(size_hint_y=None, height=list_height, do_scroll_x=False, bar_width=dp(4))
        scroll.add_widget(container)
        content = MDBoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=1)
        content.add_widget(scroll)
        close_btn = MDFlatButton(text="FECHAR", text_color=primary, radius=[dp(10)])
        dialog_height = min(dp(520), max(dp(260), list_height + dp(150)))
        dialog = MDDialog(
            title="Histórico de inventários", type="custom", content_cls=content,
            size_hint=(None, None),
            size=(min(dp(760), Window.width - dp(48)), min(dialog_height, Window.height * .86)),
            buttons=[close_btn],
        )
        close_btn.bind(on_release=lambda _b: dialog.dismiss())
        dialog.open()

    def _show_physical_inventory_workspace(self, inventory):
        inventory_id = int(inventory.get("id"))
        tokens = self._theme_tokens()
        primary = tokens.get("primary", [0.12, 0.46, 0.78, 1])
        foreground = tokens.get("text_primary", [0.15, 0.18, 0.24, 1])
        muted = tokens.get("text_secondary", [0.35, 0.39, 0.46, 1])
        card_alt = tokens.get("card_alt", [0.94, 0.96, 0.98, 1])

        summary_card = MDBoxLayout(size_hint_y=None, height=dp(64), spacing=dp(8))
        summary_values = {}
        for key, title, accent in (
            ("counted", "CONTADOS", primary),
            ("pending", "PENDENTES", tokens.get("warning", primary)),
            ("divergent", "DIVERGÊNCIAS", tokens.get("danger", primary)),
        ):
            metric = MDCard(orientation="vertical", padding=[dp(10), dp(7)], radius=[dp(10)], elevation=0,
                            md_bg_color=card_alt, line_color=[*accent[:3], .28], line_width=1)
            metric.add_widget(MDLabel(text=title, font_style="Caption", theme_text_color="Custom",
                                      text_color=muted, size_hint_y=None, height=dp(17)))
            value = MDLabel(bold=True, font_style="Body2", theme_text_color="Custom", text_color=accent)
            metric.add_widget(value)
            summary_values[key] = value
            summary_card.add_widget(metric)

        search_input = MDTextField(hint_text="Pesquisar produto ou ID", multiline=False,
                                   icon_right="magnify", size_hint_y=None, height=dp(50))
        search_input.md_bg_color = card_alt
        search_input.foreground_color = foreground
        search_input.hint_text_color = muted
        search_input.line_color_focus = primary
        results = MDBoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None)
        results.bind(minimum_height=results.setter("height"))
        scroll = ScrollView(size_hint_y=None, height=dp(264), do_scroll_x=False, bar_width=dp(4))
        scroll.add_widget(results)
        content = MDBoxLayout(orientation="vertical", spacing=dp(8), padding=[dp(2), dp(34), dp(2), 0],
                              size_hint_y=None, height=dp(428))
        content.add_widget(summary_card)
        content.add_widget(search_input)
        content.add_widget(scroll)
        refresh_btn = MDFlatButton(text="PESQUISAR", text_color=primary, radius=[dp(10)])
        cancel_btn = MDFlatButton(text="CANCELAR INVENTÁRIO", text_color=tokens.get("danger", primary), radius=[dp(10)])
        finish_btn = MDRaisedButton(text="CONCLUIR", md_bg_color=primary, radius=[dp(10)])
        close_btn = MDFlatButton(text="FECHAR", text_color=primary, radius=[dp(10)])
        dialog = MDDialog(
            title=f"Inventario #{inventory_id} - {inventory.get('name') or ''}",
            type="custom", content_cls=content,
            size_hint=(None, None),
            size=(min(dp(900), Window.width - dp(48)), min(dp(570), Window.height - dp(48))),
            buttons=[close_btn, refresh_btn, cancel_btn, finish_btn],
        )
        close_btn.bind(on_release=lambda _b: dialog.dismiss())

        def refresh(*_args):
            summary = self.db.get_physical_inventory_summary(inventory_id) or {}
            summary_values["counted"].text = f"{summary.get('counted_items', 0)} / {summary.get('total_items', 0)}"
            summary_values["pending"].text = str(summary.get('pending_items', 0))
            summary_values["divergent"].text = str(summary.get('divergent_items', 0))
            rows = self.db.get_physical_inventory_items(
                inventory_id, query=search_input.text, limit=100,
            ) or []
            results.clear_widgets()
            if not rows:
                results.add_widget(MDLabel(text="Nenhum produto encontrado.", halign="center", size_hint_y=None, height=dp(48)))
                return
            for item in rows:
                row = MDCard(orientation="horizontal", size_hint_y=None, height=dp(76), spacing=dp(12),
                             padding=[dp(12), dp(8)], radius=[dp(10)], elevation=0, md_bg_color=card_alt,
                             line_color=[*primary[:3], .16], line_width=1)
                counted = item.get("counted_qty")
                count_text = "Pendente" if counted is None else f"Contado: {counted:g} {item.get('unit')} | Dif.: {float(item.get('difference_qty') or 0):+g}"
                row.add_widget(MDLabel(
                    text=f"{item.get('product_name')}\nSistema: {float(item.get('snapshot_qty') or 0):g} {item.get('unit')} | {count_text}",
                    theme_text_color="Custom", text_color=foreground, size_hint_x=1,
                    halign="left", valign="middle",
                ))
                count_btn = MDRaisedButton(text="CONTAR", size_hint=(None, None), size=(dp(98), dp(40)),
                                           radius=[dp(10)], md_bg_color=primary, pos_hint={"center_y": .5})
                count_btn.bind(on_release=lambda _b, selected=dict(item): open_count(selected))
                row.add_widget(count_btn)
                results.add_widget(row)

        def open_count(item):
            counted_input = MDTextField(
                hint_text=f"Quantidade encontrada ({item.get('unit')})",
                text="" if item.get("counted_qty") is None else str(item.get("counted_qty")),
                input_filter="float", multiline=False,
            )
            note_input = MDTextField(hint_text="Observacao da contagem", text=str(item.get("count_note") or ""), multiline=False)
            count_content = MDBoxLayout(orientation="vertical", spacing=dp(10), size_hint_y=None, height=dp(120))
            count_content.add_widget(counted_input)
            count_content.add_widget(note_input)
            back_btn = MDFlatButton(text="VOLTAR")
            save_btn = MDRaisedButton(text="GUARDAR")
            count_dialog = MDDialog(
                title=str(item.get("product_name") or "Produto"), type="custom",
                content_cls=count_content, buttons=[back_btn, save_btn],
            )
            back_btn.bind(on_release=lambda _b: count_dialog.dismiss())

            def save(_button):
                text = str(counted_input.text or "").strip()
                if not text:
                    self.show_snackbar("Informe a quantidade encontrada")
                    return
                app = App.get_running_app()
                actor = getattr(app, "current_user", None) or "admin"
                result = self.db.record_physical_inventory_count(
                    inventory_id, item.get("product_id"), text, actor, note_input.text,
                )
                if not result.get("ok"):
                    self.show_snackbar(result.get("message") or "Falha ao guardar contagem")
                    return
                count_dialog.dismiss()
                refresh()

            save_btn.bind(on_release=save)
            count_dialog.open()

        def finish(allow_partial=False):
            app = App.get_running_app()
            actor = getattr(app, "current_user", None) or "admin"
            result = self.db.complete_physical_inventory(inventory_id, actor, allow_partial=allow_partial)
            if result.get("ok"):
                dialog.dismiss()
                self.refresh_products_panel()
                self.show_snackbar(f"Inventario concluido: {result.get('adjustment_count', 0)} ajustes")
                return
            if not allow_partial and "faltam" in str(result.get("message") or "").lower():
                confirm = MDDialog(
                    title="Contagem incompleta",
                    text=f"{result.get('message')}. Concluir apenas os produtos contados?",
                    buttons=[MDFlatButton(text="NAO"), MDRaisedButton(text="CONCLUIR PARCIAL")],
                )
                confirm.buttons[0].bind(on_release=lambda _b: confirm.dismiss())
                confirm.buttons[1].bind(on_release=lambda _b: (confirm.dismiss(), finish(True)))
                confirm.open()
                return
            self.show_snackbar(result.get("message") or "Falha ao concluir inventario")

        def cancel_inventory(_button):
            app = App.get_running_app()
            actor = getattr(app, "current_user", None) or "admin"
            confirm = MDDialog(
                title="Cancelar inventario",
                text="As contagens serao descartadas e o stock nao sera alterado. Continuar?",
                buttons=[MDFlatButton(text="NAO"), MDRaisedButton(text="SIM, CANCELAR")],
            )
            confirm.buttons[0].bind(on_release=lambda _b: confirm.dismiss())

            def apply_cancel(_b):
                result = self.db.cancel_physical_inventory(inventory_id, actor, "Cancelado pelo administrador")
                confirm.dismiss()
                if result.get("ok"):
                    dialog.dismiss()
                    self.show_snackbar("Inventario cancelado sem alterar o stock")
                else:
                    self.show_snackbar(result.get("message") or "Falha ao cancelar")

            confirm.buttons[1].bind(on_release=apply_cancel)
            confirm.open()

        refresh_btn.bind(on_release=refresh)
        finish_btn.bind(on_release=lambda _b: finish(False))
        cancel_btn.bind(on_release=cancel_inventory)
        search_input.bind(on_text_validate=refresh)
        refresh()
        dialog.open()

    def show_loss_metrics(self, *args):
        def task():
            start_date, end_date = self._get_default_loss_metrics_period()
            metrics = self.db.calculate_loss_metrics(start_date, end_date)
            return {
                "metrics": metrics or {},
                "start_date": start_date,
                "end_date": end_date,
            }

        def on_success(payload):
            payload = payload or {}
            metrics = payload.get("metrics") or {}
            default_start, default_end = self._get_default_loss_metrics_period()
            start_date = payload.get("start_date") or default_start
            end_date = payload.get("end_date") or default_end
            if not metrics:
                self.show_snackbar("Erro ao calcular perdas")
                return

            if self._loss_metrics_dialog is not None:
                try:
                    self._loss_metrics_dialog.dismiss()
                except Exception:
                    pass
                self._loss_metrics_dialog = None

            content = self._build_loss_metrics_content(
                metrics,
                start_date,
                end_date,
                detailed=False,
            )
            dialog = None

            def open_details(_instance):
                self._open_loss_details_from_metrics(
                    dialog,
                    metrics,
                    start_date,
                    end_date,
                )

            def close_dialog(_instance):
                if dialog is not None:
                    dialog.dismiss()

            dialog = MDDialog(
                title="METRICAS DE PERDAS",
                type="custom",
                content_cls=content,
                size_hint=(None, None),
                size=(min(dp(820), Window.width * 0.9), min(dp(560), Window.height * 0.74)),
                buttons=[
                    MDRaisedButton(
                        text="PDF",
                        on_release=lambda _x, start=start_date, end=end_date, data=metrics: self._generate_loss_metrics_pdf(
                            start,
                            end,
                            metrics=data,
                        ),
                    ),
                    MDFlatButton(
                        text="DETALHES",
                        on_release=open_details,
                    ),
                    MDFlatButton(
                        text="FECHAR",
                        on_release=close_dialog,
                    ),
                ],
            )
            dialog.bind(on_dismiss=lambda *_: setattr(self, "_loss_metrics_dialog", None))
            self._loss_metrics_dialog = dialog
            dialog.open()

        self._run_async_action(
            "loss-metrics",
            task,
            on_success=on_success,
            busy_message="A carregar metricas de perdas...",
            error_message="Erro ao carregar metricas",
        )

    def show_detailed_loss_report(self, metrics=None, start_date=None, end_date=None, *args):
        try:
            if start_date is None or end_date is None:
                start_date, end_date = self._get_default_loss_metrics_period(end_date)
            if metrics is None:
                metrics = self.db.calculate_loss_metrics(start_date, end_date)
            if not metrics:
                return

            if self._loss_details_dialog is not None:
                try:
                    self._loss_details_dialog.dismiss()
                except Exception:
                    pass
                self._loss_details_dialog = None

            content = self._build_loss_metrics_content(
                metrics,
                start_date,
                end_date,
                detailed=True,
            )
            dialog = MDDialog(
                title="DETALHES DAS PERDAS",
                type='custom',
                content_cls=content,
                size_hint=(None, None),
                size=(min(dp(900), Window.width * 0.92), min(dp(660), Window.height * 0.84)),
                buttons=[
                    MDRaisedButton(
                        text="PDF",
                        on_release=lambda _x, start=start_date, end=end_date, data=metrics: self._generate_loss_metrics_pdf(
                            start,
                            end,
                            metrics=data,
                        ),
                    ),
                    MDFlatButton(
                        text="FECHAR",
                        on_release=lambda _x: dialog.dismiss()
                    ),
                ]
            )
            dialog.bind(on_dismiss=lambda *_: setattr(self, "_loss_details_dialog", None))
            self._loss_details_dialog = dialog
            dialog.open()

        except Exception as e:
            print(f"Erro ao mostrar relatorio: {e}")

    def show_fraud_alerts(self, *args):
        days_lookback = 30

        def task():
            return self.db.detect_fraud_patterns(days_lookback=days_lookback)

        def on_success(alerts):
            alerts = list(alerts or [])
            self.update_loss_alert_badges(len(alerts))
            banner = self._build_fraud_alerts_banner(alerts, days_lookback=days_lookback)
            if self._render_status_banners([banner], auto_dismiss_seconds=None):
                return

            if not alerts:
                self.show_snackbar("Nenhum alerta de fraude detectado")
                return

            high_alerts = [a for a in alerts if int(a.get('severity') or 0) == 3]
            medium_alerts = [a for a in alerts if int(a.get('severity') or 0) == 2]
            low_alerts = [a for a in alerts if int(a.get('severity') or 0) == 1]

            message = f"""ALERTAS DE SEGURANCA

    ALTA PRIORIDADE: {len(high_alerts)}
    MEDIA PRIORIDADE: {len(medium_alerts)}
    BAIXA PRIORIDADE: {len(low_alerts)}

    PRINCIPAIS ALERTAS:"""

            for alert in (high_alerts + medium_alerts)[:5]:
                severity_icon = {3: "[ALTO]", 2: "[MEDIO]", 1: "[BAIXO]"}.get(int(alert.get('severity') or 0), "[INFO]")
                message += f"\n\n{severity_icon} {alert.get('title')}\n{alert.get('description')}"

            dialog = MDDialog(
                title="ALERTAS DE FRAUDE",
                text=message,
                buttons=[
                    MDFlatButton(
                        text="VER TODOS",
                        on_release=lambda x: self.show_all_fraud_alerts(alerts)
                    ),
                    MDFlatButton(
                        text="FECHAR",
                        on_release=lambda x: dialog.dismiss()
                    )
                ]
            )
            dialog.open()

        self._run_async_action(
            "fraud-alerts",
            task,
            on_success=on_success,
            busy_message="A carregar alertas de fraude...",
            error_message="Erro ao carregar alertas",
        )

    def show_all_fraud_alerts(self, alerts):
        try:
            alerts = list(alerts or [])
            if self._render_status_banners(
                [self._build_fraud_alerts_banner(alerts, days_lookback=30)],
                auto_dismiss_seconds=None,
            ):
                return

            from kivy.uix.scrollview import ScrollView

            content = MDBoxLayout(
                orientation='vertical',
                padding=dp(20),
                spacing=dp(10),
                size_hint_y=None
            )
            content.bind(minimum_height=content.setter('height'))

            for alert in alerts:
                severity_label = self._severity_label(alert.get("severity"))

                alert_text = f"""{severity_label} - {alert.get('alert_type')}

    {alert.get('title')}
    {alert.get('description')}

    """
                if alert.get('related_user'):
                    alert_text += f"Utilizador: {alert.get('related_user')}\n"

                alert_text += "-" * 50 + "\n"

                alert_label = MDLabel(
                    text=alert_text,
                    size_hint_y=None,
                    halign='left',
                    valign='top',
                    text_size=(dp(1), None),
                )

                # Nunca use ``texture_size -> size`` neste contentor: a
                # largura do label volta a alterar o BoxLayout, que por sua
                # vez recalcula a textura no mesmo frame. Mantemos a largura
                # controlada pelo pai e adaptamos somente a altura do texto.
                def sync_alert_width(instance, width):
                    desired = (max(dp(1), width), None)
                    if instance.text_size != desired:
                        instance.text_size = desired

                def sync_alert_height(instance, texture_size):
                    desired = max(dp(24), texture_size[1])
                    if abs(instance.height - desired) >= 0.5:
                        instance.height = desired

                alert_label.bind(
                    width=sync_alert_width,
                    texture_size=sync_alert_height,
                )
                content.add_widget(alert_label)

            scroll = ScrollView(size_hint=(1, 1))
            scroll.add_widget(content)

            dialog = MDDialog(
                title="TODOS OS ALERTAS",
                type='custom',
                content_cls=scroll,
                size_hint=(0.9, 0.9),
                buttons=[
                    MDFlatButton(
                        text="FECHAR",
                        on_release=lambda x: dialog.dismiss()
                    )
                ]
            )
            dialog.open()

        except Exception as e:
            print(f"Erro: {e}")

    def show_pending_approvals(self, *args):
        def task():
            return self.db.get_pending_approvals()

        def on_success(pending):
            pending = list(pending or [])
            banner = self._build_pending_approvals_banner(pending)
            rendered = self._render_status_banners([banner], auto_dismiss_seconds=None)
            if not pending:
                if not rendered:
                    self.show_snackbar("Nenhuma aprovacao pendente")
                return

            self.show_approval_details(pending)
            return

        self._run_async_action(
            "pending-approvals",
            task,
            on_success=on_success,
            busy_message="A carregar aprovacoes pendentes...",
            error_message="Erro ao carregar aprovacoes",
        )

    def show_approval_details(self, pending_list):
        try:
            app = App.get_running_app()
            current_user = getattr(app, "current_user", None)
            tokens = getattr(app, "theme_tokens", {}) if app else {}
            dialog_ref = {"dialog": None}

            content = MDBoxLayout(
                orientation="vertical",
                padding=dp(8),
                spacing=dp(10),
                size_hint_y=None,
            )
            content.bind(minimum_height=content.setter("height"))

            for row in pending_list:
                values = list(row) + [""] * 14
                mov_id, _prod_id, description, mov_type, qty, unit, cost, _price, reason, note, evidence, created_at, user, role = values[:14]

                card = MDCard(
                    orientation="vertical",
                    padding=dp(12),
                    spacing=dp(8),
                    size_hint_y=None,
                    radius=[dp(8)],
                    elevation=0,
                    md_bg_color=tokens.get("card_alt", [0.96, 0.97, 0.99, 1]),
                )
                card.bind(minimum_height=card.setter("height"))

                header = MDBoxLayout(
                    size_hint_y=None,
                    height=dp(26),
                    spacing=dp(8),
                )
                header.add_widget(
                    MDIcon(
                        icon="clipboard-alert-outline",
                        theme_text_color="Custom",
                        text_color=tokens.get("warning", [0.84, 0.52, 0.12, 1]),
                        size_hint=(None, None),
                        size=(dp(18), dp(18)),
                    )
                )
                header.add_widget(
                    MDLabel(
                        text=f"#{mov_id} | {mov_type or 'Movimento pendente'}",
                        bold=True,
                        theme_text_color="Primary",
                        shorten=True,
                        shorten_from="right",
                    )
                )
                card.add_widget(header)

                note_line = f"\nObs: {note}" if note else ""
                info_text = (
                    f"Produto: {description or 'Produto'}\n"
                    f"Quantidade: {qty} {unit or 'un'} | Custo: {self._format_money(cost)}\n"
                    f"Registado por: {user or 'sistema'} ({role or 'sem perfil'})\n"
                    f"Data: {created_at or 'sem data'}\n"
                    f"Motivo: {reason or 'nao informado'}"
                    f"{note_line}\n"
                    f"{'Com evidencia fotografica' if evidence else 'Sem evidencia'}"
                )

                info_label = MDLabel(
                    text=info_text,
                    size_hint_y=None,
                    halign="left",
                    valign="top",
                    font_size=dp(12),
                    theme_text_color="Secondary",
                )
                self._bind_wrapped_label_height(info_label, min_height=dp(90))
                card.add_widget(info_label)

                buttons = MDBoxLayout(
                    size_hint_y=None,
                    height=dp(40),
                    spacing=dp(10),
                )

                approve_btn = MDRaisedButton(
                    text="APROVAR",
                    md_bg_color=tokens.get("success", [0.2, 0.7, 0.3, 1]),
                    on_release=lambda _x, mid=mov_id: (
                        dialog_ref["dialog"].dismiss() if dialog_ref.get("dialog") else None,
                        self.approve_loss(mid, current_user),
                    ),
                )

                reject_btn = MDRaisedButton(
                    text="REJEITAR",
                    md_bg_color=tokens.get("danger", [0.9, 0.3, 0.3, 1]),
                    on_release=lambda _x, mid=mov_id: (
                        dialog_ref["dialog"].dismiss() if dialog_ref.get("dialog") else None,
                        self.reject_loss(mid),
                    ),
                )

                buttons.add_widget(approve_btn)
                buttons.add_widget(reject_btn)
                card.add_widget(buttons)

                content.add_widget(card)

            scroll = self._build_bounded_scroll(
                content,
                max_height_ratio=0.58,
                max_height_dp=520,
                min_height_dp=260,
            )

            dialog = MDDialog(
                title="DETALHES DAS APROVACOES",
                type="custom",
                content_cls=scroll,
                size_hint=(None, None),
                size=(min(dp(860), Window.width * 0.9), min(dp(620), Window.height * 0.78)),
                buttons=[
                    MDRaisedButton(
                        text=f"APROVAR TODAS ({len(pending_list)})",
                        md_bg_color=tokens.get("success", [0.2, 0.7, 0.3, 1]),
                        on_release=lambda _x: self._confirm_approve_all_losses(
                            dialog_ref.get("dialog"),
                            current_user,
                            len(pending_list),
                        ),
                    ),
                    MDFlatButton(
                        text="FECHAR",
                        on_release=lambda _x: dialog.dismiss(),
                    )
                ],
            )
            dialog_ref["dialog"] = dialog
            dialog.open()

        except Exception as e:
            print(f"Erro: {e}")

    def _confirm_approve_all_losses(self, approvals_dialog, approved_by, pending_count):
        """Pede confirmação antes de aplicar todas as perdas pendentes."""
        actor = approved_by or getattr(App.get_running_app(), "current_user", None) or "admin"
        dialog_ref = {"dialog": None}

        def confirm(_instance):
            confirmation = dialog_ref.get("dialog")
            if confirmation:
                confirmation.dismiss()
            if approvals_dialog:
                approvals_dialog.dismiss()
            self.approve_all_losses(actor)

        dialog = MDDialog(
            title="Aprovar todas as perdas?",
            text=(
                f"Serão aprovadas {pending_count} perdas pendentes. "
                "O stock será atualizado para cada perda aprovada."
            ),
            buttons=[
                MDFlatButton(
                    text="CANCELAR",
                    on_release=lambda _x: dialog_ref["dialog"].dismiss(),
                ),
                MDRaisedButton(
                    text="APROVAR TODAS",
                    on_release=confirm,
                ),
            ],
        )
        dialog_ref["dialog"] = dialog
        dialog.open()

    def approve_all_losses(self, approved_by):
        """Aprova em lote as perdas que continuam pendentes no momento da ação."""
        actor = approved_by or getattr(App.get_running_app(), "current_user", None) or "admin"

        def task():
            return self.db.approve_all_pending_stock_movements(actor)

        def on_success(result):
            summary = result if isinstance(result, dict) else {}
            approved_count = int(summary.get("approved_count") or 0)
            failed_count = int(summary.get("failed_count") or 0)
            if approved_count:
                try:
                    self.db.log_action(
                        actor,
                        "admin",
                        "APPROVE_ALL_LOSSES",
                        f"Aprovadas {approved_count} perdas pendentes",
                    )
                except Exception:
                    pass
            if failed_count:
                self.show_snackbar(
                    f"{approved_count} perdas aprovadas; {failed_count} permanecem pendentes"
                )
            elif approved_count:
                self.show_snackbar(f"{approved_count} perdas aprovadas")
            else:
                self.show_snackbar("Nenhuma perda pendente para aprovar")
            self.show_pending_approvals()

        self._run_async_action(
            "approve-all-pending-losses",
            task,
            on_success=on_success,
            busy_message="A aprovar todas as perdas pendentes...",
            error_message="Erro ao aprovar todas as perdas",
        )

    def approve_loss(self, movement_id, approved_by):
        try:
            actor = approved_by or getattr(App.get_running_app(), "current_user", None) or "admin"
            success = self.db.approve_stock_movement(movement_id, actor)

            if success:
                self.show_snackbar(f"Perda #{movement_id} aprovada")
                self.db.log_action(actor, "admin", "APPROVE_LOSS", f"Aprovada perda ID {movement_id}")
                self.show_pending_approvals()
            else:
                self.show_snackbar("Erro ao aprovar perda")
        except Exception as e:
            print(f"Erro ao aprovar: {e}")
            self.show_snackbar("Erro ao aprovar")

    def reject_loss(self, movement_id):
        try:
            app = App.get_running_app()
            actor = getattr(app, "current_user", None) or "admin"
            rejecter = getattr(self.db, "reject_stock_movement", None)
            success = rejecter(movement_id, rejected_by=actor) if callable(rejecter) else False
            if success:
                self.show_snackbar(f"Perda #{movement_id} rejeitada")
                self.db.log_action(actor, "admin", "REJECT_LOSS", f"Rejeitada perda ID {movement_id}")
                self.show_pending_approvals()
                return
            self.show_snackbar("Erro ao rejeitar perda")
        except Exception as e:
            print(f"Erro ao rejeitar: {e}")
            self.show_snackbar("Erro ao rejeitar")

    # ------------------------------------------------------------------
    # Lifecycle events
    # --------------------------------------------------------------------------
    # CORRECAO 8 — on_enter
    # Entrada leve: nao faz refresh, filtro, render nem rotinas secundarias.
    # A tela fica pronta; dados so mudam por acao explicita do utilizador.
    # --------------------------------------------------------------------------
    def on_enter(self):
        self._bind_keyboard_shortcuts()
        self._bind_recycle_product_hover()
        self._cancel_enter_events()
        self._get_intelligence().start()
        self._update_responsive_layout()
        self._init_badge(0)
        if not self._aggregated_products_cache and not self._products_loading:
            self.load_products()
        elif self._products_table_dirty or not self._current_display:
            self.filter_products(
                self.search_input.text if self.search_input else self._pending_search
            )

    def on_leave(self):
        self._unbind_keyboard_shortcuts()
        self._unbind_recycle_product_hover()
        self._cancel_enter_events()
        if self._filter_ev:
            Clock.unschedule(self._filter_ev)
            self._filter_ev = None
        self._stop_ai_polling()
        self._clear_loading_overlay()
        self._dismiss_lot_menu()
        had_pending_render = bool(self._table_render_ev or self._pending_table_rows)
        if self._table_render_ev:
            Clock.unschedule(self._table_render_ev)
            self._table_render_ev = None
        self._pending_table_rows = deque()
        self._clear_product_row_hover_bindings()
        if had_pending_render:
            self._products_table_dirty = True
        if self.product_table:
            self.product_table.disabled = False
        self._alerts_refresh_token += 1
        self._ai_popup_token += 1
        for attr_name in (
            "_lot_selector_dialog",
            "_shopping_list_dialog",
            "_loss_metrics_dialog",
            "_loss_details_dialog",
            "_shortcut_help_dialog",
        ):
            dialog = getattr(self, attr_name, None)
            if dialog is not None:
                try:
                    dialog.dismiss()
                except Exception:
                    pass
                setattr(self, attr_name, None)
        self._shopping_list_payload = None

    def show_fraud_notification_popup(self, alert_count):
        try:
            count = int(alert_count or 0)
        except Exception:
            count = 0
        if self._render_status_banners(
            [
                {
                    "kind": "fraud",
                    "variant": "danger",
                    "icon": "shield-alert-outline",
                    "bg_color": (0.93, 0.34, 0.34, 1),
                    "title": "Alertas criticos de fraude",
                    "messages": [
                        f"Detectados {count} alerta(s) de alta prioridade.",
                        "Verifique estes alertas agora.",
                    ],
                    "all_messages": [],
                    "count": count,
                    "urgency": 0,
                    "details_sections": [
                        ("O que fazer", ["Verifique os movimentos suspeitos antes de novas validacoes."]),
                    ],
                }
            ],
            auto_dismiss_seconds=None,
        ):
            return

        dialog = MDDialog(
            title="ALERTAS CRITICOS",
            text=f"Foram encontrados {alert_count} alertas de seguranca de alta prioridade.\n\nVerifique-os antes de continuar.",
            buttons=[
                MDRaisedButton(
                    text="VER AGORA",
                    md_bg_color=[0.9, 0.3, 0.3, 1],
                    on_release=lambda x: (dialog.dismiss(), self.show_fraud_alerts())
                ),
                MDFlatButton(
                    text="MAIS TARDE",
                    on_release=lambda x: dialog.dismiss()
                )
            ]
        )
        dialog.open()


if __name__ == "__main__":
    from admin_app import AdminApp
    AdminApp().run()
