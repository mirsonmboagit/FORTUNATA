from __future__ import annotations

import os
import sys
import time
import traceback
from datetime import datetime
from threading import Thread

from kivy.app import App
from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.audio import SoundLoader
from kivy.core.window import Window
from kivy.graphics import Color, Line, RoundedRectangle
from kivy.graphics.texture import Texture
from kivy.factory import Factory
from kivy.lang import Builder
from kivy.metrics import dp, sp
from kivy.properties import ListProperty, NumericProperty, StringProperty
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.modalview import ModalView
from kivy.uix.recycleview.views import RecycleDataViewBehavior

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.card import MDCard
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDIcon, MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.snackbar import MDSnackbar
from kivymd.uix.textfield import MDTextField
from kivymd.uix.tooltip import MDTooltip

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database.provider import get_db
from pdfs.pdf_viewer import PDFViewer
from pdfs.receipt_report import ReceiptReport
from ui.components.tooltip_widgets import (
    TooltipCleanupBehavior,
    TooltipIconButton,
)
from utils.receipt_policy import can_emit_receipt, resolve_receipt_data_for_emission
from utils.vat import compute_vat_breakdown
from utils.vision import get_vision_dependencies


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _format_money(value):
    return f"{_safe_float(value):,.2f} MT".replace(",", " ")


def _format_qty(value, is_weight=False):
    amount = _safe_float(value)
    if is_weight:
        return f"{amount:.2f} kg"
    return str(int(round(amount)))


def _calculate_promo(product):
    base_price = _safe_float(product[3] if len(product) > 3 else 0.0)
    status = str(product[7] if len(product) > 7 and product[7] is not None else "").strip().upper()
    promo_active = status == "PERTO_DO_PRAZO"
    return base_price, promo_active


def _unpack_sale_product(product):
    return {
        "id": product[0],
        "name": str(product[1] or "").strip(),
        "stock": _safe_float(product[2], 0.0),
        "unit_price": _safe_float(product[3], 0.0),
        "barcode": product[4] if len(product) > 4 else None,
        "is_weight": bool(product[5]) if len(product) > 5 else False,
        "expiry_date": product[6] if len(product) > 6 else None,
        "status": product[7] if len(product) > 7 else None,
        "units_per_package": int(_safe_float(product[8], 0)) if len(product) > 8 and product[8] not in (None, "") else None,
        "allow_pack_sale": bool(product[9]) if len(product) > 9 else False,
        "vat_rule_code": str(product[10] or "STANDARD").strip().upper() if len(product) > 10 else "STANDARD",
    }


class QuickProductCard(MDCard):
    def __init__(self, product_data=None, add_callback=None, **kwargs):
        super().__init__(**kwargs)
        self.product_data = product_data
        self.add_callback = add_callback
        self._allow_pack_sale = False
        self._is_weight = False
        if product_data is not None:
            self.set_product_payload(product_data, add_callback)

    def set_product_payload(self, product_data, add_callback=None):
        self.product_data = product_data
        if add_callback is not None:
            self.add_callback = add_callback
        if product_data is None or not self.ids:
            return

        info = _unpack_sale_product(product_data)
        unit_price, promo_active = _calculate_promo(product_data)
        is_weight = info["is_weight"]
        allow_pack_sale = bool(
            info["allow_pack_sale"]
            and info["units_per_package"]
            and info["units_per_package"] >= 2
            and not is_weight
        )
        self._allow_pack_sale = allow_pack_sale
        self._is_weight = is_weight

        self.ids.product_icon.icon = "scale-balance" if is_weight else "package-variant-closed"
        self.ids.product_icon.text_color = [0.98, 0.76, 0.28, 1] if is_weight else [0.58, 0.78, 0.98, 1]
        self.ids.product_name_label.text = info["name"]

        meta_parts = []
        if is_weight:
            meta_parts.append(f"Stock {_format_qty(info['stock'], True)}")
            meta_parts.append("Venda por kg")
        else:
            meta_parts.append(f"Stock {_format_qty(info['stock'])} un")
            meta_parts.append(f"Emb. {int(info['units_per_package'])} un" if allow_pack_sale else "Venda unitária")
        barcode = str(info["barcode"] or "").strip()
        if barcode:
            meta_parts.append(barcode)
        self.ids.product_meta_label.text = " | ".join(meta_parts)

        self.ids.product_price_label.text = _format_money(unit_price)
        if promo_active:
            self.ids.product_mode_label.text = "Promo ativa"
            self.ids.product_mode_label.text_color = [0.47, 0.90, 0.56, 1]
        elif is_weight:
            self.ids.product_mode_label.text = "Preço/kg"
            self.ids.product_mode_label.text_color = [0.98, 0.76, 0.28, 1]
        else:
            self.ids.product_mode_label.text = "Preço/un"
            self.ids.product_mode_label.text_color = [0.68, 0.73, 0.82, 1]

        self.ids.add_unit_btn.icon = "scale-balance" if is_weight else "plus"
        self.ids.add_unit_btn.hint_text = "Adicionar por kg" if is_weight else "Adicionar unidade"
        self.ids.add_pack_btn.hint_text = "Adicionar embalagem"
        self.ids.add_pack_btn.disabled = not allow_pack_sale
        self.ids.add_pack_btn.opacity = 1 if allow_pack_sale else 0.28

    def on_add_unit_click(self):
        if callable(self.add_callback):
            self.add_callback(self.product_data, sale_mode="unit", source="manual")

    def on_add_pack_click(self):
        if self._allow_pack_sale and callable(self.add_callback):
            self.add_callback(self.product_data, sale_mode="pack", source="manual")


class CompactActionButton(TooltipCleanupBehavior, MDTooltip, ButtonBehavior, MDBoxLayout):
    md_bg_color = ListProperty([0.26, 0.29, 0.36, 1])
    radius = ListProperty([dp(8)])
    border_color = ListProperty([1, 1, 1, 0])
    border_width = NumericProperty(dp(0.9))

    def __init__(self, icon="", icon_color=None, icon_font_size=None, **kwargs):
        kwargs.setdefault("tooltip_display_delay", 0.18)
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("padding", [0, 0, 0, 0])
        super().__init__(**kwargs)

        with self.canvas.before:
            self._bg_color_instruction = Color(rgba=self.md_bg_color)
            self._bg_rect = RoundedRectangle(pos=self.pos, size=self.size, radius=self._normalized_radius())
        with self.canvas.after:
            self._border_color_instruction = Color(rgba=self.border_color)
            self._border_line = Line(rounded_rectangle=(self.x, self.y, self.width, self.height, self._normalized_radius()[0]), width=self.border_width)
        self.bind(
            pos=self._sync_bg,
            size=self._sync_bg,
            md_bg_color=self._sync_bg,
            radius=self._sync_bg,
            border_color=self._sync_bg,
            border_width=self._sync_bg,
        )

        glyph = MDIcon(
            icon=icon,
            halign="center",
            valign="middle",
            font_size=icon_font_size or sp(14),
            theme_text_color="Custom",
            text_color=icon_color or [1, 1, 1, 1],
        )
        glyph.bind(size=lambda inst, value: setattr(inst, "text_size", value))
        self.add_widget(glyph)

    def _normalized_radius(self):
        if len(self.radius) == 1:
            return [self.radius[0]] * 4
        return list(self.radius)

    def _sync_bg(self, *_args):
        self._bg_color_instruction.rgba = self.md_bg_color
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size
        self._bg_rect.radius = self._normalized_radius()
        self._border_color_instruction.rgba = self.border_color
        self._border_line.rounded_rectangle = (self.x, self.y, self.width, self.height, self._normalized_radius()[0])
        self._border_line.width = self.border_width


class FloatingScannerPanel(MDCard):
    min_panel_width = NumericProperty(dp(220))
    min_panel_height = NumericProperty(dp(220))
    drag_bar_height = NumericProperty(dp(34))
    resize_handle_size = NumericProperty(dp(24))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._active_mode = None
        self._drag_offset = (0.0, 0.0)
        self._start_touch = (0.0, 0.0)
        self._start_size = (0.0, 0.0)

        with self.canvas.after:
            self._handle_color_instruction = Color(rgba=[0.56, 0.90, 0.54, 0.85])
            self._handle_line_one = Line(points=[], width=1.1)
            self._handle_line_two = Line(points=[], width=1.1)
            self._handle_line_three = Line(points=[], width=1.1)
        self.bind(pos=self._sync_handle, size=self._sync_handle, opacity=self._sync_handle)

    def _sync_handle(self, *_args):
        if self.opacity <= 0.01:
            self._handle_line_one.points = []
            self._handle_line_two.points = []
            self._handle_line_three.points = []
            return

        inset = dp(8)
        span = dp(9)
        step = dp(5)
        right = self.right - inset
        bottom = self.y + inset

        self._handle_line_one.points = [right - span, bottom, right, bottom + span]
        self._handle_line_two.points = [right - span - step, bottom, right, bottom + span + step]
        self._handle_line_three.points = [right - span - (step * 2), bottom, right, bottom + span + (step * 2)]

    def clamp_to_parent(self):
        parent = self.parent
        if parent is None:
            return

        max_width = max(dp(160), parent.width - dp(16))
        max_height = max(dp(170), parent.height - dp(16))
        min_width = min(self.min_panel_width, max_width)
        min_height = min(self.min_panel_height, max_height)
        self.width = min(max(self.width, min_width), max_width)
        self.height = min(max(self.height, min_height), max_height)

        self.x = min(max(self.x, dp(8)), max(dp(8), parent.width - self.width - dp(8)))
        self.y = min(max(self.y, dp(8)), max(dp(8), parent.height - self.height - dp(8)))

    def _touch_in_resize_zone(self, touch):
        return touch.x >= (self.right - self.resize_handle_size) and touch.y <= (self.y + self.resize_handle_size)

    def _touch_in_drag_zone(self, touch):
        return touch.y >= (self.top - self.drag_bar_height)

    def on_touch_down(self, touch):
        if self.disabled or self.opacity <= 0.01 or not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)

        if self._touch_in_resize_zone(touch):
            touch.grab(self)
            self._active_mode = "resize"
            self._start_touch = tuple(touch.pos)
            self._start_size = tuple(self.size)
            return True

        if self._touch_in_drag_zone(touch):
            touch.grab(self)
            self._active_mode = "move"
            self._drag_offset = (touch.x - self.x, touch.y - self.y)
            return True

        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if touch.grab_current is not self:
            return super().on_touch_move(touch)

        parent = self.parent
        if parent is None:
            return True

        if self._active_mode == "move":
            new_x = touch.x - self._drag_offset[0]
            new_y = touch.y - self._drag_offset[1]
            self.pos = (new_x, new_y)
            self.clamp_to_parent()
            return True

        if self._active_mode == "resize":
            delta_x = touch.x - self._start_touch[0]
            delta_y = touch.y - self._start_touch[1]
            max_width = max(dp(160), parent.width - self.x - dp(8))
            max_height = max(dp(170), parent.height - self.y - dp(8))
            min_width = min(self.min_panel_width, max_width)
            min_height = min(self.min_panel_height, max_height)
            self.width = min(max(min_width, self._start_size[0] + delta_x), max_width)
            self.height = min(max(min_height, self._start_size[1] + delta_y), max_height)
            self.clamp_to_parent()
            return True

        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            self._active_mode = None
            self.clamp_to_parent()
            return True
        return super().on_touch_up(touch)


class NoticeBannerCard(MDCard):
    pass


class RecycleQuickProductCard(RecycleDataViewBehavior, QuickProductCard):
    def refresh_view_attrs(self, rv, index, data):
        payload = data.get("product_data")
        callback = data.get("add_callback")
        attrs = dict(data)
        attrs.pop("product_data", None)
        attrs.pop("add_callback", None)
        result = super().refresh_view_attrs(rv, index, attrs)
        self.set_product_payload(payload, callback)
        return result


Factory.register("FloatingScannerPanel", cls=FloatingScannerPanel)
Factory.register("NoticeBannerCard", cls=NoticeBannerCard)
Builder.load_file(os.path.join(CURRENT_DIR, "sales_screen.kv"))


class SalesScreen(MDScreen):
    PRODUCTS_PAGE_SIZE = 80
    PRODUCTS_CACHE_SECONDS = 8
    STOCK_SYNC_INTERVAL_SECONDS = 15
    NOTICE_KEYS = ("one", "two", "three")

    operator_name = StringProperty("Operador")
    header_datetime_text = StringProperty("")
    hold_button_text = StringProperty("Suspender Venda")

    def __init__(self, **kwargs):
        db = kwargs.pop("db", None)
        super().__init__(**kwargs)
        self.db = db or get_db()
        self.back_target = "manager"
        self.cart_items = []
        self.total_amount = 0.0
        self.discount_amount = 0.0
        self.final_amount = 0.0
        self.payment_method = "cash"
        self.products_dict = {}
        self._loaded_products = []
        self._products_offset = 0
        self._products_has_more = False
        self._products_loading = False
        self._products_token = 0
        self._last_products_refresh_at = 0.0
        self._search_ev = None
        self._pending_search = ""
        self._qty_update_events = {}
        self._stock_poll_ev = None
        self._clock_ev = None
        self._snapshot_loading = False
        self._barcode_lookup_active = False
        self._sale_submitting = False
        self._suspended_sale = None
        self._last_completed_receipt_data = None
        self._notice_details = {}
        self._notice_overlay_key = None
        self._notice_overlay_visible = False
        self._notice_dialog = None
        self._keyboard_shortcuts_bound = False
        self._last_shortcut_signature = None
        self._last_shortcut_at = 0.0
        self._vision_modules = None
        self._scanner_panel_initialized = False
        self.scanning = False
        self.current_camera = 0
        self.camera_capture = None
        self.last_barcode = None
        self.last_barcode_time = 0.0
        self.scanner_sound_success = None
        self.scanner_sound_error = None
        self.pdf_viewer = None
        self.receipt_report = ReceiptReport()
        Clock.schedule_once(self._post_init, 0.05)

    def _post_init(self, *_args):
        self._bind_scanner_panel_ids()
        self._set_notice_detail("one", "Stock sob controlo", "Sem alertas críticos no momento.", ["Use este espaço para acompanhar reposição e desvios de stock."])
        self._set_notice_detail("two", "Movimento inicial", "Ainda não há produto destaque hoje.", ["Assim que houver vendas suficientes, este banner mostra o produto líder do dia."])
        self._set_notice_detail("three", "Pico operacional", "O sistema ainda está a acumular dados do dia.", ["Quando houver volume suficiente, este banner mostra a hora de maior movimento."])
        self._refresh_header_meta()
        self._set_connection_text()
        self.load_scanner_sounds()
        self.set_payment_method("cash")
        self.set_search_feedback(
            "Pronto para vender | Ctrl+F pesquisa | Enter adiciona | Ctrl+B scanner",
            "success",
            "check-circle",
        )
        self.load_products()
        self._load_operational_snapshot()
        self._update_action_states()
        self._update_responsive_layout()
        self._refresh_notice_widgets()

    def on_enter(self):
        # Os atalhos ficam ativos apenas enquanto o manager estiver em foco.
        self._bind_keyboard_shortcuts()
        self._refresh_header_meta()
        self._start_clock()
        stale = (time.perf_counter() - self._last_products_refresh_at) >= self.PRODUCTS_CACHE_SECONDS
        if not self._loaded_products or stale:
            self.manual_refresh_stock(silent=True)
        self._load_operational_snapshot()
        self._start_stock_polling()
        app = App.get_running_app()
        warmup = getattr(app, "warmup_screens", None) if app else None
        if callable(warmup):
            Clock.schedule_once(
                lambda _dt: warmup(("sales_history", "losses", "losses_history"), delay=0.1),
                0.18,
            )

    def on_leave(self):
        self._unbind_keyboard_shortcuts()
        self._stop_clock()
        self._stop_stock_polling()
        if self._search_ev:
            self._search_ev.cancel()
            self._search_ev = None
        self.close_notice_overlay()
        self.stop_scanner()

    def on_size(self, *_args):
        Clock.schedule_once(lambda _dt: self._update_responsive_layout(), 0)

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
        # Evita que os atalhos concorram com dialogs modais da operacao.
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

        # Mantemos apenas teclas especiais estaveis; o manager nao depende mais de F1..F6.
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

    def _close_transient_panels(self):
        if self._notice_overlay_visible:
            self.close_notice_overlay()
            return True
        if self.scanning:
            self.stop_scanner()
            return True
        return False

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

        # Preferimos combinacoes com Ctrl porque as teclas F variam entre teclados e modos Fn.
        if "ctrl" in modifiers and key_name == "f":
            return self._focus_text_field("search_input", select_all=True)
        if "ctrl" in modifiers and key_name == "b":
            self.toggle_scanner()
            return True
        if "ctrl" in modifiers and key_name == "h":
            self.open_sales_history()
            return True
        if "ctrl" in modifiers and key_name == "r":
            self.refresh_products_panel()
            return True
        if "ctrl" in modifiers and key_name == "d":
            self.open_losses_screen()
            return True
        if "ctrl" in modifiers and key_name == "enter":
            self.finalize_sale()
            return True
        if "ctrl" in modifiers and key_name == "p":
            self.emit_receipt()
            return True
        if "ctrl" in modifiers and key_name == "s":
            self.toggle_suspend_sale()
            return True
        if "ctrl" in modifiers and key_name == "l":
            self.clear_search()
            return True
        if "alt" in modifiers and key_name == "1":
            self.set_payment_method("cash")
            return True
        if "alt" in modifiers and key_name == "2":
            self.set_payment_method("card")
            return True
        if "alt" in modifiers and key_name == "3":
            self.set_payment_method("mobile")
            return True
        if "alt" in modifiers and key_name == "d":
            return self._focus_text_field("discount_input", select_all=True)
        if "alt" in modifiers and key_name == "v":
            return self._focus_text_field("paid_input", select_all=True)
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

    def _refresh_header_meta(self):
        app = App.get_running_app()
        username = getattr(app, "current_user", None) if app else None
        self.operator_name = str(username or "Operador")
        self.header_datetime_text = datetime.now().strftime("%d/%m/%Y %H:%M")
        if self.ids:
            operator_label = self.ids.get("operator_label")
            if operator_label is not None:
                operator_label.text = self.operator_name
            datetime_label = self.ids.get("datetime_label")
            if datetime_label is not None:
                datetime_label.text = self.header_datetime_text

    def _set_connection_text(self):
        text = "Online"
        connection_label_fn = getattr(self.db, "get_connection_label", None)
        if callable(connection_label_fn):
            try:
                text = connection_label_fn() or text
            except Exception:
                text = "Online"
        else:
            module_name = str(getattr(self.db.__class__, "__module__", "") or "")
            if module_name.startswith("database.database"):
                text = "Local"
        if self.ids:
            label = self.ids.get("connection_label")
            if label is not None:
                label.text = text

    def _start_clock(self):
        self._refresh_header_meta()
        if self._clock_ev:
            self._clock_ev.cancel()
        self._clock_ev = Clock.schedule_interval(lambda _dt: self._refresh_header_meta(), 30)

    def _stop_clock(self):
        if self._clock_ev:
            self._clock_ev.cancel()
            self._clock_ev = None

    def _update_responsive_layout(self):
        if not self.ids:
            return
        width = self.width or dp(1360)
        body_shell = self.ids.get("body_shell")
        workspace_card = self.ids.get("workspace_card")
        cart_card = self.ids.get("cart_card")
        summary_card = self.ids.get("summary_card")
        sidebar = self.ids.get("sidebar")
        bottom_actions_grid = self.ids.get("bottom_actions_grid")
        product_results_card = self.ids.get("product_results_card")

        if not body_shell or not workspace_card or not bottom_actions_grid or not product_results_card:
            return

        if sidebar is None and cart_card is not None and summary_card is not None:
            if width >= dp(1320):
                body_shell.orientation = "horizontal"
                workspace_card.size_hint_x = 0.36
                cart_card.size_hint_x = 0.39
                summary_card.size_hint_x = 0.25
                bottom_actions_grid.cols = 4
                product_results_card.height = dp(230)
            elif width >= dp(1120):
                body_shell.orientation = "horizontal"
                workspace_card.size_hint_x = 0.35
                cart_card.size_hint_x = 0.40
                summary_card.size_hint_x = 0.25
                bottom_actions_grid.cols = 3
                product_results_card.height = dp(210)
            else:
                body_shell.orientation = "vertical"
                workspace_card.size_hint_x = 1
                cart_card.size_hint_x = 1
                summary_card.size_hint_x = 1
                bottom_actions_grid.cols = 2 if width >= dp(820) else 1
                product_results_card.height = dp(190)
            panel = self.ids.get("scanner_preview_card")
            if panel is not None and (self._scanner_panel_initialized or panel.opacity > 0.01):
                self._ensure_scanner_panel_geometry()
            return

        if width >= dp(1260):
            body_shell.orientation = "horizontal"
            workspace_card.size_hint_x = 0.70
            if sidebar is not None:
                sidebar.size_hint_x = 0.30
                sidebar.size_hint_y = 1
                sidebar.height = 0
            bottom_actions_grid.cols = 4
            product_results_card.height = dp(230)
        elif width >= dp(980):
            body_shell.orientation = "vertical"
            workspace_card.size_hint_x = 1
            if sidebar is not None:
                sidebar.size_hint_x = 1
                sidebar.size_hint_y = None
                sidebar.height = dp(520)
            bottom_actions_grid.cols = 2
            product_results_card.height = dp(210)
        else:
            body_shell.orientation = "vertical"
            workspace_card.size_hint_x = 1
            if sidebar is not None:
                sidebar.size_hint_x = 1
                sidebar.size_hint_y = None
                sidebar.height = dp(560)
            bottom_actions_grid.cols = 1
            product_results_card.height = dp(190)

        panel = self.ids.get("scanner_preview_card")
        if panel is not None and (self._scanner_panel_initialized or panel.opacity > 0.01):
            self._ensure_scanner_panel_geometry()
        if self._notice_overlay_visible and self._notice_overlay_key:
            Clock.schedule_once(lambda _dt, key=self._notice_overlay_key: self._position_notice_overlay(key), 0)
        Clock.schedule_once(lambda _dt: self._refresh_notice_widgets(), 0)

    def _ensure_scanner_panel_geometry(self, reset=False):
        if not self.ids:
            return
        panel = self.ids.get("scanner_preview_card")
        if panel is None:
            return

        if reset or not self._scanner_panel_initialized:
            max_width = max(dp(180), self.width - dp(36))
            max_height = max(dp(190), self.height - dp(96))
            available_width = min(max_width, max(panel.min_panel_width, dp(280)))
            available_height = min(max_height, max(panel.min_panel_height, dp(300)))
            panel.size = (available_width, available_height)

            workspace_card = self.ids.get("workspace_card")
            if workspace_card is not None and workspace_card.width > dp(120):
                default_x = workspace_card.x + max(dp(12), workspace_card.width - panel.width - dp(12))
                default_y = workspace_card.y + dp(18)
            else:
                default_x = self.width - panel.width - dp(18)
                default_y = dp(108)
            panel.pos = (default_x, default_y)
            self._scanner_panel_initialized = True

        if hasattr(panel, "clamp_to_parent"):
            panel.clamp_to_parent()

    def _ensure_pdf_viewer(self):
        if self.pdf_viewer is None:
            self.pdf_viewer = PDFViewer(error_callback=self.show_message)
        return self.pdf_viewer

    def set_search_feedback(self, text, tone="info", icon="information"):
        palette = {
            "success": ([0.15, 0.33, 0.22, 1], [0.69, 0.96, 0.67, 1], [0.92, 0.99, 0.92, 1]),
            "warning": ([0.33, 0.24, 0.12, 1], [0.98, 0.76, 0.28, 1], [0.99, 0.95, 0.86, 1]),
            "danger": ([0.35, 0.18, 0.18, 1], [0.99, 0.55, 0.55, 1], [1, 0.92, 0.92, 1]),
            "info": ([0.16, 0.24, 0.36, 1], [0.50, 0.78, 1, 1], [0.91, 0.96, 1, 1]),
        }
        bg, icon_color, text_color = palette.get(tone, palette["info"])
        if self.ids:
            card = self.ids.get("search_feedback_card")
            icon_widget = self.ids.get("search_feedback_icon")
            label = self.ids.get("search_feedback_label")
            if card is not None:
                card.md_bg_color = bg
            if icon_widget is not None:
                icon_widget.icon = icon
                icon_widget.text_color = icon_color
            if label is not None:
                label.text = str(text)
                label.text_color = text_color

    def _set_scanner_preview_visible(self, visible):
        if not self.ids:
            return
        self._bind_scanner_panel_ids()
        card = self.ids.get("scanner_preview_card")
        if card is None:
            return
        if visible:
            card.opacity = 1
            card.disabled = False
            self._ensure_scanner_panel_geometry()
        else:
            card.opacity = 0
            card.disabled = True

    def _get_scanner_panel(self):
        if not self.ids:
            return None
        return self.ids.get("scanner_preview_card")

    def _get_scanner_widget(self, widget_id):
        panel = self._get_scanner_panel()
        if panel is None or not hasattr(panel, "ids"):
            return None
        return panel.ids.get(widget_id)

    def _bind_scanner_panel_ids(self):
        if not self.ids:
            return
        panel = self._get_scanner_panel()
        if panel is None or not hasattr(panel, "ids"):
            return
        for widget_id in ("scanner_status_label", "camera_image"):
            widget = panel.ids.get(widget_id)
            if widget is not None:
                self.ids[widget_id] = widget

    def load_scanner_sounds(self):
        try:
            self.scanner_sound_success = SoundLoader.load("assets/sounds/beep.wav")
            self.scanner_sound_error = SoundLoader.load("assets/sounds/beeperror.mp3")
        except Exception:
            self.scanner_sound_success = None
            self.scanner_sound_error = None

    def play_scanner_sound(self, success=True):
        try:
            if success and self.scanner_sound_success:
                self.scanner_sound_success.play()
            if (not success) and self.scanner_sound_error:
                self.scanner_sound_error.play()
        except Exception:
            pass

    def load_products(self):
        return self._request_products_page(reset=True, search_text=self._current_search_text(), silent=True)

    def _current_search_text(self):
        if not self.ids:
            return (self._pending_search or "").strip()
        widget = self.ids.get("search_input")
        if widget is None:
            return (self._pending_search or "").strip()
        return str(widget.text or "").strip()

    def _request_products_page(self, reset=True, search_text="", silent=True):
        if self._products_loading:
            return False

        token = self._products_token + 1
        self._products_token = token
        self._products_loading = True
        offset = 0 if reset else self._products_offset
        query_text = str(search_text or "").strip()
        self._update_action_states()

        def worker():
            rows = []
            error = None
            try:
                rows = self.db.get_products_for_sale_page(
                    search_text=query_text,
                    limit=self.PRODUCTS_PAGE_SIZE,
                    offset=offset,
                ) or []
            except Exception as exc:
                error = str(exc)
            Clock.schedule_once(
                lambda _dt, payload=rows, tok=token, rst=reset, off=offset, sl=silent, err=error:
                self._apply_products_page(payload, tok, rst, off, sl, err),
                0,
            )

        Thread(target=worker, daemon=True).start()
        return True

    def _apply_products_page(self, rows, token, reset, offset, silent, error):
        if token != self._products_token:
            return

        self._products_loading = False
        if error:
            self.show_message("Falha ao carregar produtos.")
            self._update_action_states()
            return

        if reset:
            self._loaded_products = list(rows)
        else:
            self._loaded_products.extend(rows)
        self.products_dict = {row[0]: row for row in self._loaded_products}
        self._products_offset = offset + len(rows)
        self._products_has_more = len(rows) >= self.PRODUCTS_PAGE_SIZE
        self._last_products_refresh_at = time.perf_counter()
        self.display_products(self._filter_sale_products(self._loaded_products, self._pending_search))
        self._sync_cart_with_live_stock()
        if not silent and reset:
            self.set_search_feedback("Stock atualizado com sucesso", "success", "refresh")
        self._update_action_states()

    def _filter_sale_products(self, products, text):
        query = str(text or "").strip().lower()
        if not query:
            return list(products or [])
        return [
            product for product in (products or [])
            if (
                query in str(product[0]).lower()
                or query in str(product[1]).lower()
                or (len(product) > 4 and product[4] and query in str(product[4]).lower())
            )
        ]

    def display_products(self, products):
        if not self.ids:
            return
        rv = self.ids.product_matches_rv
        results_label = self.ids.product_results_label
        results = list(products or [])
        results_label.text = f"{len(results)} produtos"
        rv.data = [{"product_data": product, "add_callback": self.add_to_cart} for product in results]

    def on_search(self, text):
        self._pending_search = str(text or "")
        self.display_products(self._filter_sale_products(self._loaded_products, self._pending_search))
        if self._search_ev:
            self._search_ev.cancel()
        self._search_ev = Clock.schedule_once(self._dispatch_search, 0.24)
        self._update_action_states()

    def clear_search(self):
        if not self.ids:
            return
        search_input = self.ids.get("search_input")
        if search_input is not None:
            search_input.text = ""
            search_input.focus = True
        self._pending_search = ""
        self.display_products(self._loaded_products)
        self.set_search_feedback("Pesquisa limpa", "info", "magnify")
        self._update_action_states()

    def _looks_like_barcode_query(self, text):
        raw = str(text or "").strip()
        if not raw or " " in raw:
            return False
        return raw.isdigit() or len(raw) >= 6

    def _find_preferred_search_product(self, text):
        query = str(text or "").strip().lower()
        if not query:
            return None, []

        filtered = self._filter_sale_products(self._loaded_products, text)
        if not filtered:
            return None, []

        exact_matches = []
        for product in filtered:
            product_id = str(product[0] if len(product) > 0 else "").strip().lower()
            name = str(product[1] if len(product) > 1 else "").strip().lower()
            barcode = str(product[4] if len(product) > 4 and product[4] is not None else "").strip().lower()
            if query in (product_id, name, barcode):
                exact_matches.append(product)

        if exact_matches:
            return exact_matches[0], filtered
        if len(filtered) == 1:
            return filtered[0], filtered
        return None, filtered

    def _add_search_match_to_cart(self, text):
        product, matches = self._find_preferred_search_product(text)
        if product is None:
            return False

        self.add_to_cart(product, source="search")
        product_name = str(product[1] if len(product) > 1 else "Produto")
        self.set_search_feedback(
            f"{product_name} adicionado ao carrinho",
            "success",
            "check-circle",
        )
        if self.ids:
            search_input = self.ids.get("search_input")
            if search_input is not None:
                search_input.text = ""
                search_input.focus = True
        self._pending_search = ""
        self.display_products(self._loaded_products)
        self._update_action_states()
        return True

    def _dispatch_search(self, _dt):
        self._search_ev = None
        self._request_products_page(reset=True, search_text=self._pending_search, silent=True)

    def on_search_enter(self):
        if self._search_ev:
            self._search_ev.cancel()
            self._search_ev = None
        text = self._current_search_text()
        if not text:
            return
        if self._add_search_match_to_cart(text):
            return
        if self._looks_like_barcode_query(text):
            self._lookup_barcode_async(text, source="search")
            return
        self.set_search_feedback(
            "Use Enter para produto unico/exato ou refine a pesquisa.",
            "info",
            "keyboard-return",
        )

    def on_products_scroll(self, scroll_y):
        if scroll_y > 0.04:
            return
        if self._products_has_more and not self._products_loading:
            self._request_products_page(reset=False, search_text=self._pending_search, silent=True)

    def manual_refresh_stock(self, silent=False):
        if self._products_loading:
            return False
        return self._request_products_page(reset=True, search_text=self._current_search_text(), silent=silent)

    def refresh_products_panel(self):
        self.manual_refresh_stock(silent=False)
        self._load_operational_snapshot()

    def _start_stock_polling(self):
        if self._stock_poll_ev:
            self._stock_poll_ev.cancel()
        self._stock_poll_ev = Clock.schedule_interval(
            lambda _dt: self.manual_refresh_stock(silent=True),
            self.STOCK_SYNC_INTERVAL_SECONDS,
        )

    def _stop_stock_polling(self):
        if self._stock_poll_ev:
            self._stock_poll_ev.cancel()
            self._stock_poll_ev = None

    def _sync_cart_with_live_stock(self):
        changed = False
        for item in self.cart_items:
            live_product = self.products_dict.get(item.get("id"))
            if live_product is None:
                continue
            live_stock = _unpack_sale_product(live_product)["stock"]
            if abs(_safe_float(item.get("max_stock")) - live_stock) > 1e-9:
                item["max_stock"] = live_stock
                changed = True
        if changed:
            self.update_cart_display()

    def _resolve_product_from_barcode(self, barcode_value):
        lookup_fn = getattr(self.db, "find_product_by_barcode_fast", None)
        if callable(lookup_fn):
            product = lookup_fn(barcode_value)
        else:
            product = self.db.get_product_by_barcode(barcode_value)
        if not product:
            return None
        product_id = product[0]
        live_product = self.products_dict.get(product_id)
        if live_product is not None:
            return live_product
        rows = self.db.get_products_for_sale_ids([product_id]) or []
        return rows[0] if rows else product

    def _lookup_barcode_async(self, barcode_value, source="search"):
        code = str(barcode_value or "").strip()
        if not code or self._barcode_lookup_active:
            return False
        self._barcode_lookup_active = True
        self.set_search_feedback(f"À procura do código {code}...", "info", "barcode-scan")

        def worker():
            product = None
            error = None
            try:
                product = self._resolve_product_from_barcode(code)
            except Exception as exc:
                error = str(exc)
            Clock.schedule_once(
                lambda _dt, data=product, err=error, raw=code, src=source: self._apply_barcode_lookup(data, err, raw, src),
                0,
            )

        Thread(target=worker, daemon=True).start()
        return True

    def _apply_barcode_lookup(self, product, error, barcode_value, source):
        self._barcode_lookup_active = False
        if error:
            self.play_scanner_sound(False)
            self.set_search_feedback("Erro ao pesquisar o código de barras", "danger", "close-circle")
            return
        if not product:
            self.play_scanner_sound(False)
            self.set_search_feedback(f"Código {barcode_value} não encontrado", "warning", "alert-circle")
            return

        self.add_to_cart(product, source="barcode")
        self.play_scanner_sound(True)
        self.set_search_feedback(f"{product[1]} adicionado ao carrinho", "success", "check-circle")
        if source == "search" and self.ids:
            search_input = self.ids.get("search_input")
            if search_input is not None:
                search_input.text = ""
        self._update_action_states()

    def add_to_cart(self, product, sale_mode=None, source="manual"):
        try:
            if product is None:
                self.show_message("Produto indisponível.")
                return
            info = _unpack_sale_product(product)
            base_price, promo_active = _calculate_promo(product)
            is_weight = info["is_weight"]
            allow_pack_sale = bool(
                info["allow_pack_sale"]
                and info["units_per_package"]
                and info["units_per_package"] >= 2
                and not is_weight
            )

            if is_weight:
                self.show_weight_dialog(product)
                return

            sale_mode = sale_mode or "unit"
            if sale_mode == "pack" and not allow_pack_sale:
                sale_mode = "unit"

            if sale_mode == "pack":
                pack_units = int(info["units_per_package"])
                pack_price = base_price * pack_units
                for item in self.cart_items:
                    if item["id"] == info["id"] and item.get("sale_mode") == "pack":
                        next_units = _safe_float(item.get("qty_units")) + pack_units
                        if next_units > info["stock"]:
                            self.show_message("Estoque insuficiente.")
                            return
                        item["qty"] += 1
                        item["qty_units"] = next_units
                        item["total"] = item["qty"] * item["price"]
                        self.update_cart_display()
                        return

                self.cart_items.append(
                    {
                        "id": info["id"],
                        "name": info["name"],
                        "qty": 1,
                        "qty_units": pack_units,
                        "pack_units": pack_units,
                        "price": pack_price,
                        "unit_price": base_price,
                        "total": pack_price,
                        "max_stock": info["stock"],
                        "is_weight": False,
                        "weight_kg": 0,
                        "sale_mode": "pack",
                        "promo_active": promo_active,
                        "vat_rule_code": info["vat_rule_code"],
                    }
                )
                self.update_cart_display()
                return

            for item in self.cart_items:
                if item["id"] == info["id"] and item.get("sale_mode", "unit") == "unit":
                    next_qty = _safe_float(item.get("qty")) + 1
                    if next_qty > info["stock"]:
                        self.show_message("Estoque insuficiente.")
                        return
                    item["qty"] = next_qty
                    item["qty_units"] = next_qty
                    item["total"] = item["qty"] * item["price"]
                    self.update_cart_display()
                    return

            self.cart_items.append(
                {
                    "id": info["id"],
                    "name": info["name"],
                    "qty": 1,
                    "qty_units": 1,
                    "pack_units": None,
                    "price": base_price,
                    "unit_price": base_price,
                    "total": base_price,
                    "max_stock": info["stock"],
                    "is_weight": False,
                    "weight_kg": 0,
                    "sale_mode": "unit",
                    "promo_active": promo_active,
                    "vat_rule_code": info["vat_rule_code"],
                }
            )
            self.update_cart_display()
        except Exception:
            traceback.print_exc()
            self.show_message("Falha ao adicionar produto.")

    def show_weight_dialog(self, product):
        info = _unpack_sale_product(product)
        base_price, promo_active = _calculate_promo(product)

        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(12),
            padding=[dp(18), dp(18), dp(18), dp(12)],
            size_hint_y=None,
            height=dp(360),
        )
        title = MDLabel(
            text=info["name"],
            bold=True,
            font_style="H6",
            theme_text_color="Custom",
            text_color=[0.12, 0.18, 0.28, 1],
            size_hint_y=None,
            height=dp(28),
        )
        price_label = MDLabel(
            text=f"Preço por kg: {_format_money(base_price)} | Stock: {_format_qty(info['stock'], True)}",
            theme_text_color="Secondary",
            size_hint_y=None,
            height=dp(22),
        )
        weight_input = MDTextField(
            hint_text="Peso em kg",
            multiline=False,
            input_filter="float",
            mode="rectangle",
            size_hint_y=None,
            height=dp(52),
        )
        total_input = MDTextField(
            hint_text="Ou valor total em MT",
            multiline=False,
            input_filter="float",
            mode="rectangle",
            size_hint_y=None,
            height=dp(52),
        )
        preview = MDLabel(
            text="",
            size_hint_y=None,
            height=dp(28),
            theme_text_color="Custom",
            text_color=[0.12, 0.50, 0.20, 1],
        )
        content.add_widget(title)
        content.add_widget(price_label)
        content.add_widget(weight_input)
        content.add_widget(total_input)
        content.add_widget(preview)

        sync_guard = {"active": False}

        def update_from_weight(_instance, value):
            if sync_guard["active"]:
                return
            sync_guard["active"] = True
            try:
                text = str(value or "").strip()
                if not text:
                    total_input.text = ""
                    preview.text = ""
                    return
                weight = _safe_float(text)
                total_price = weight * base_price
                total_input.text = f"{total_price:.2f}"
                preview.text = f"Total calculado: {_format_money(total_price)}"
            finally:
                sync_guard["active"] = False

        def update_from_total(_instance, value):
            if sync_guard["active"]:
                return
            sync_guard["active"] = True
            try:
                text = str(value or "").strip()
                if not text:
                    weight_input.text = ""
                    preview.text = ""
                    return
                total_price = _safe_float(text)
                if base_price <= 0:
                    return
                weight = total_price / base_price
                weight_input.text = f"{weight:.3f}"
                preview.text = f"Peso calculado: {_format_qty(weight, True)}"
            finally:
                sync_guard["active"] = False

        weight_input.bind(text=update_from_weight)
        total_input.bind(text=update_from_total)

        dialog = MDDialog(
            title="Venda por peso",
            type="custom",
            content_cls=content,
            buttons=[
                MDFlatButton(text="Cancelar", on_release=lambda _btn: dialog.dismiss()),
                MDRaisedButton(text="Adicionar", md_bg_color=[0.19, 0.70, 0.32, 1]),
            ],
        )

        def confirm_add(_btn):
            weight = _safe_float(weight_input.text)
            if weight <= 0:
                self.show_message("Informe o peso.")
                return
            if weight > info["stock"]:
                self.show_message("Peso acima do stock disponível.")
                return

            total_price = round(weight * base_price, 2)
            for item in self.cart_items:
                if item["id"] == info["id"] and item.get("sale_mode") == "weight":
                    next_weight = _safe_float(item.get("weight_kg")) + weight
                    if next_weight > info["stock"]:
                        self.show_message("Peso acima do stock disponível.")
                        return
                    item["weight_kg"] = next_weight
                    item["qty"] = next_weight
                    item["qty_units"] = next_weight
                    item["total"] = round(next_weight * item["unit_price"], 2)
                    dialog.dismiss()
                    self.update_cart_display()
                    return

            self.cart_items.append(
                {
                    "id": info["id"],
                    "name": info["name"],
                    "qty": weight,
                    "qty_units": weight,
                    "pack_units": None,
                    "price": base_price,
                    "unit_price": base_price,
                    "total": total_price,
                    "max_stock": info["stock"],
                    "is_weight": True,
                    "weight_kg": weight,
                    "sale_mode": "weight",
                    "promo_active": promo_active,
                    "vat_rule_code": info["vat_rule_code"],
                }
            )
            dialog.dismiss()
            self.update_cart_display()

        dialog.buttons[1].bind(on_release=confirm_add)
        dialog.open()

    def update_cart_display(self):
        if not self.ids:
            return
        cart_list = self.ids.cart_list
        cart_list.clear_widgets()
        self.total_amount = 0.0
        self.ids.cart_empty_label.opacity = 1 if not self.cart_items else 0
        self.ids.cart_count_label.text = f"{len(self.cart_items)} itens"

        for index, item in enumerate(self.cart_items):
            row = MDCard(
                orientation="horizontal",
                size_hint_y=None,
                height=dp(66),
                padding=[dp(10), dp(6), dp(8), dp(6)],
                spacing=dp(6),
                radius=[dp(14)],
                elevation=0,
                md_bg_color=[0.13, 0.15, 0.20, 1] if index % 2 == 0 else [0.16, 0.18, 0.23, 1],
            )

            info_box = MDBoxLayout(
                orientation="vertical",
                spacing=dp(2),
                size_hint_x=0.42,
            )
            sale_mode = item.get("sale_mode", "unit")
            mode_label = {
                "unit": "Venda unitária",
                "pack": f"Embalagem x {int(item.get('pack_units') or 1)}",
                "weight": "Venda por peso",
            }.get(sale_mode, "Venda")
            info_box.add_widget(
                MDLabel(
                    text=item["name"],
                    bold=True,
                    theme_text_color="Custom",
                    text_color=[0.97, 0.98, 1, 1],
                    font_size=dp(11),
                    shorten=True,
                    shorten_from="right",
                    size_hint_y=None,
                    height=dp(18),
                )
            )
            info_box.add_widget(
                MDLabel(
                    text=mode_label,
                    font_size=dp(9),
                    theme_text_color="Custom",
                    text_color=[0.69, 0.73, 0.81, 1],
                    shorten=True,
                    shorten_from="right",
                    size_hint_y=None,
                    height=dp(16),
                )
            )

            qty_box = MDBoxLayout(
                size_hint_x=0.22,
                spacing=0,
                padding=[0, dp(4), 0, dp(4)],
            )
            if item.get("is_weight"):
                qty_box.add_widget(
                    MDLabel(
                        text=_format_qty(item.get("weight_kg"), True),
                        halign="center",
                        bold=True,
                        theme_text_color="Custom",
                        text_color=[0.98, 0.76, 0.28, 1],
                    )
                )
            else:
                qty_box.add_widget(
                    MDLabel(
                        text=_format_qty(item.get("qty")),
                        halign="center",
                        bold=True,
                        theme_text_color="Custom",
                        text_color=[0.90, 0.94, 1, 1],
                        font_size=dp(11),
                    )
                )

            price_label = MDLabel(
                text=_format_money(item.get("price")),
                halign="right",
                size_hint_x=0.16,
                theme_text_color="Custom",
                text_color=[0.83, 0.88, 0.95, 1],
                font_size=dp(10),
            )
            total_label = MDLabel(
                text=_format_money(item.get("total")),
                halign="right",
                size_hint_x=0.14,
                bold=True,
                theme_text_color="Custom",
                text_color=[0.56, 0.90, 0.54, 1],
                font_size=dp(11),
            )
            remove_btn = CompactActionButton(
                icon="close-thick",
                size_hint=(None, None),
                size=(dp(22), dp(22)),
                radius=[dp(11)],
                icon_font_size=sp(11),
                icon_color=[1, 0.88, 0.90, 1],
                md_bg_color=[0.35, 0.14, 0.18, 1],
                border_color=[0.94, 0.42, 0.47, 0.65],
                border_width=dp(0.9),
                hint_text="Remover item",
            )
            remove_btn.bind(on_release=lambda _btn, idx=index: self.remove_from_cart(idx))
            remove_box = AnchorLayout(
                size_hint_x=0.06,
                anchor_x="center",
                anchor_y="center",
            )
            remove_box.add_widget(remove_btn)

            row.add_widget(info_box)
            row.add_widget(qty_box)
            row.add_widget(price_label)
            row.add_widget(total_label)
            row.add_widget(remove_box)
            cart_list.add_widget(row)
            self.total_amount += _safe_float(item.get("total"))

        self.recalculate_totals()
        self._update_action_states()

    def recalculate_totals(self):
        self.discount_amount = min(max(self._read_discount_value(), 0.0), self.total_amount)
        self.final_amount = max(self.total_amount - self.discount_amount, 0.0)
        if not self.ids:
            return
        self.ids.subtotal_value_label.text = _format_money(self.total_amount)
        self.ids.discount_value_label.text = _format_money(self.discount_amount)
        self.ids.total_value_label.text = _format_money(self.final_amount)
        self.calculate_change()

    def _read_discount_value(self):
        if not self.ids:
            return 0.0
        widget = self.ids.get("discount_input")
        return _safe_float(widget.text if widget is not None else 0.0)

    def on_discount_text(self, _text):
        self.recalculate_totals()

    def calculate_change(self):
        if not self.ids:
            return
        paid_text = str(self.ids.paid_input.text or "").strip()
        paid_amount = self.final_amount if not paid_text else _safe_float(paid_text)
        change = round(paid_amount - self.final_amount, 2)
        if change >= 0:
            self.ids.change_value_label.text = _format_money(change)
            self.ids.change_value_label.text_color = [0.47, 0.90, 0.56, 1]
        else:
            self.ids.change_value_label.text = f"Falta {_format_money(abs(change))}"
            self.ids.change_value_label.text_color = [0.99, 0.55, 0.55, 1]

    def fill_paid_with_exact_total(self):
        if not self.ids or self.final_amount <= 0:
            return
        paid_input = self.ids.get("paid_input")
        if paid_input is None:
            return
        paid_input.text = f"{self.final_amount:.2f}"
        paid_input.focus = True
        Clock.schedule_once(lambda _dt: paid_input.select_all(), 0)
        self.calculate_change()

    def on_total_final_card_touch(self, widget, touch):
        if self._sale_submitting or self.final_amount <= 0:
            return False
        if not widget.collide_point(*touch.pos):
            return False
        if touch.is_mouse_scrolling:
            return False
        self.fill_paid_with_exact_total()
        return True

    def set_payment_method(self, method):
        self.payment_method = method
        if not self.ids:
            return
        palette = {
            "selected": [0.16, 0.72, 0.46, 1],
            "default": [0.24, 0.27, 0.34, 1],
        }
        mapping = {
            "cash": self.ids.pay_cash_btn,
            "card": self.ids.pay_card_btn,
            "mobile": self.ids.pay_mobile_btn,
        }
        for key, button in mapping.items():
            button.md_bg_color = palette["selected"] if key == method else palette["default"]
        if method != "cash" and self.final_amount > 0 and not str(self.ids.paid_input.text or "").strip():
            self.ids.paid_input.text = f"{self.final_amount:.2f}"
        self.calculate_change()

    def increase_qty(self, index):
        if index >= len(self.cart_items):
            return
        item = self.cart_items[index]
        if item.get("is_weight"):
            return
        if item.get("sale_mode") == "pack":
            pack_units = int(item.get("pack_units") or 1)
            next_units = _safe_float(item.get("qty_units")) + pack_units
            if next_units > _safe_float(item.get("max_stock")):
                self.show_message("Estoque insuficiente.")
                return
            item["qty"] += 1
            item["qty_units"] = next_units
            item["total"] = item["qty"] * item["price"]
        else:
            next_qty = _safe_float(item.get("qty")) + 1
            if next_qty > _safe_float(item.get("max_stock")):
                self.show_message("Estoque insuficiente.")
                return
            item["qty"] = next_qty
            item["qty_units"] = next_qty
            item["total"] = item["qty"] * item["price"]
        self.update_cart_display()

    def decrease_qty(self, index):
        if index >= len(self.cart_items):
            return
        item = self.cart_items[index]
        if item.get("is_weight"):
            return
        if _safe_float(item.get("qty")) <= 1:
            self.remove_from_cart(index)
            return
        item["qty"] -= 1
        item["qty_units"] = item["qty"] * int(item.get("pack_units") or 1) if item.get("sale_mode") == "pack" else item["qty"]
        item["total"] = item["qty"] * item["price"]
        self.update_cart_display()

    def schedule_qty_update(self, index, value):
        pending = self._qty_update_events.pop(index, None)
        if pending:
            pending.cancel()
        self._qty_update_events[index] = Clock.schedule_once(
            lambda _dt, idx=index, raw=value: self._apply_scheduled_qty_update(idx, raw),
            0.15,
        )

    def _apply_scheduled_qty_update(self, index, value):
        self._qty_update_events.pop(index, None)
        self.update_qty(index, value)

    def update_qty(self, index, value):
        if index >= len(self.cart_items):
            return
        item = self.cart_items[index]
        if item.get("is_weight"):
            return
        qty = int(_safe_float(value, 0))
        if qty <= 0:
            self.remove_from_cart(index)
            return
        qty_units = qty * int(item.get("pack_units") or 1) if item.get("sale_mode") == "pack" else qty
        if qty_units > _safe_float(item.get("max_stock")):
            self.show_message("Quantidade acima do stock disponível.")
            self.update_cart_display()
            return
        item["qty"] = qty
        item["qty_units"] = qty_units
        item["total"] = qty * item["price"]
        self.update_cart_display()

    def remove_from_cart(self, index):
        if 0 <= index < len(self.cart_items):
            self.cart_items.pop(index)
            self.update_cart_display()

    def clear_cart(self):
        self.cart_items.clear()
        self.update_cart_display()

    def cancel_sale(self):
        if not self.cart_items:
            self.show_message("O carrinho já está vazio.")
            return
        self.clear_cart()
        if self.ids:
            self.ids.paid_input.text = ""
            self.ids.discount_input.text = ""
        self._last_completed_receipt_data = None
        self.recalculate_totals()
        self.set_search_feedback("Venda cancelada", "warning", "cancel")
        self.show_message("Venda cancelada.")

    def toggle_suspend_sale(self):
        if self.cart_items:
            self._suspended_sale = {
                "cart_items": [dict(item) for item in self.cart_items],
                "paid_text": str(self.ids.paid_input.text or "") if self.ids else "",
                "discount_text": str(self.ids.discount_input.text or "") if self.ids else "",
                "payment_method": self.payment_method,
            }
            self.clear_cart()
            if self.ids:
                self.ids.paid_input.text = ""
                self.ids.discount_input.text = ""
            self.set_search_feedback("Venda suspensa. Pode retomá-la depois.", "info", "pause-circle")
            self.show_message("Venda suspensa.")
        elif self._suspended_sale:
            self.cart_items = [dict(item) for item in self._suspended_sale.get("cart_items") or []]
            if self.ids:
                self.ids.paid_input.text = self._suspended_sale.get("paid_text", "")
                self.ids.discount_input.text = self._suspended_sale.get("discount_text", "")
            self.set_payment_method(self._suspended_sale.get("payment_method") or "cash")
            self._suspended_sale = None
            self.update_cart_display()
            self.set_search_feedback("Venda retomada com sucesso", "success", "play-circle")
            self.show_message("Venda retomada.")
        else:
            self.show_message("Não existe venda suspensa.")
        self._update_action_states()

    def _allocate_discount(self, cart_snapshot, discount_amount):
        items = [dict(item) for item in (cart_snapshot or [])]
        subtotal = sum(_safe_float(item.get("total")) for item in items)
        discount_to_apply = min(max(_safe_float(discount_amount), 0.0), subtotal)
        remaining_discount = round(discount_to_apply, 2)
        allocations = []
        for index, item in enumerate(items):
            line_total = round(_safe_float(item.get("total")), 2)
            if subtotal <= 0:
                line_discount = 0.0
            elif index == len(items) - 1:
                line_discount = remaining_discount
            else:
                line_discount = round(discount_to_apply * (line_total / subtotal), 2)
                remaining_discount = round(remaining_discount - line_discount, 2)
            effective_line_total = max(0.0, round(line_total - line_discount, 2))
            qty_units = max(_safe_float(item.get("qty_units")), 0.000001)
            effective_unit_price = round(effective_line_total / qty_units, 6)
            allocations.append(
                {
                    **item,
                    "line_discount": line_discount,
                    "effective_line_total": effective_line_total,
                    "effective_unit_price": effective_unit_price,
                }
            )
        return allocations

    def _build_receipt_data(self, cart_snapshot, discount_amount, paid_amount, change_amount):
        app = App.get_running_app()
        operator = getattr(app, "current_user", None) if app else None
        allocations = self._allocate_discount(cart_snapshot, discount_amount)
        items = []
        subtotal_net = 0.0
        vat_total = 0.0
        vat_tags = []

        for item in allocations:
            qty_units = _safe_float(item.get("qty_units"))
            vat_rule_code = item.get("vat_rule_code") or "STANDARD"
            breakdown = compute_vat_breakdown(
                item.get("effective_unit_price"),
                quantity=qty_units,
                rule_code=vat_rule_code,
                reference_date=datetime.now(),
            )
            subtotal_net += _safe_float(breakdown.get("net_total"))
            vat_total += _safe_float(breakdown.get("vat_amount"))
            vat_tags.append(str(breakdown.get("short_label") or "").strip())
            sale_mode = item.get("sale_mode")
            if sale_mode == "weight":
                qty_text = _format_qty(item.get("weight_kg"), True)
                sale_mode_label = "Peso"
            elif sale_mode == "pack":
                qty_text = f"{int(_safe_float(item.get('qty')))} emb"
                sale_mode_label = f"Emb. x {int(item.get('pack_units') or 1)}"
            else:
                qty_text = f"{int(_safe_float(item.get('qty')))} un"
                sale_mode_label = "Unidade"
            items.append(
                {
                    "name": item.get("name"),
                    "qty_text": qty_text,
                    "unit_price": item.get("effective_unit_price"),
                    "line_total": item.get("effective_line_total"),
                    "sale_mode_label": sale_mode_label,
                    "vat_tag": breakdown.get("short_label"),
                }
            )

        total = round(sum(_safe_float(item.get("effective_line_total")) for item in allocations), 2)
        note_parts = [f"Pagamento: {self._payment_method_label()}."]
        if discount_amount > 0:
            note_parts.append(f"Desconto aplicado: {_format_money(discount_amount)}.")
        unique_vats = [tag for tag in dict.fromkeys(vat_tags) if tag]
        if unique_vats:
            note_parts.append("IVA considerado no preço final: " + ", ".join(unique_vats) + ".")

        return {
            "store_name": "MERCEARIA",
            "receipt_code": datetime.now().strftime("%Y%m%d%H%M%S"),
            "issued_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "operator": operator or "Operador",
            "items_count": len(items),
            "items": items,
            "subtotal": round(subtotal_net, 2),
            "vat_total": round(vat_total, 2),
            "total": total,
            "paid_amount": round(_safe_float(paid_amount), 2),
            "change_amount": round(_safe_float(change_amount), 2),
            "vat_note": " ".join(note_parts),
        }

    def _payment_method_label(self):
        return {"cash": "Dinheiro", "card": "Cartão", "mobile": "M-Pesa"}.get(self.payment_method, "Dinheiro")

    def finalize_sale(self):
        if self._sale_submitting:
            return
        if not self.cart_items:
            self.show_message("O carrinho está vazio.")
            return

        paid_text = str(self.ids.paid_input.text or "").strip() if self.ids else ""
        paid_amount = self.final_amount if not paid_text else _safe_float(paid_text)
        if paid_amount + 1e-9 < self.final_amount:
            self.show_message("Pagamento insuficiente.")
            return

        discount_amount = self.discount_amount
        change_amount = max(0.0, round(paid_amount - self.final_amount, 2))
        cart_snapshot = [dict(item) for item in self.cart_items]
        receipt_data = self._build_receipt_data(cart_snapshot, discount_amount, paid_amount, change_amount)

        app = App.get_running_app()
        username = getattr(app, "current_user", None) if app else None
        role = getattr(app, "current_role", None) or "manager"
        terminal_id = os.environ.get("COMPUTERNAME") or "POS"
        self._set_sale_busy(True)

        def worker():
            try:
                ids = [item.get("id") for item in cart_snapshot if item.get("id") is not None]
                live_rows = self.db.get_products_for_sale_ids(ids) or []
                live_map = {row[0]: row for row in live_rows}
                conflicts = []
                for item in cart_snapshot:
                    live_product = live_map.get(item["id"]) or self.products_dict.get(item["id"])
                    live_stock = _unpack_sale_product(live_product)["stock"] if live_product else 0.0
                    if _safe_float(item.get("qty_units")) > live_stock + 1e-9:
                        conflicts.append((item["name"], _safe_float(item.get("qty_units")), live_stock))
                if conflicts:
                    actor = username or terminal_id or "desconhecido"
                    try:
                        summary = " | ".join(
                            f"{name}: {requested:.2f}>{available:.2f}"
                            for name, requested, available in conflicts[:3]
                        )
                        if len(conflicts) > 3:
                            summary += f" | +{len(conflicts) - 3} item(ns)"
                        self.db.log_action(
                            actor,
                            role,
                            "RUPTURE_ATTEMPT",
                            f"Tentativa de venda com stock insuficiente | {summary}",
                        )
                    except Exception:
                        pass
                    return {"status": "conflict", "conflicts": conflicts, "live_map": live_map}

                for item in self._allocate_discount(cart_snapshot, discount_amount):
                    result = self.db.add_sale(
                        item["id"],
                        item["qty_units"],
                        item["effective_unit_price"],
                        username,
                        role,
                        terminal_id=terminal_id,
                        is_promotional=bool(item.get("promo_active")),
                        vat_rule_code=item.get("vat_rule_code"),
                    )
                    if not result:
                        raise RuntimeError(f"Falha ao gravar {item['name']}")

                if username:
                    try:
                        details = (
                            f"Itens: {len(cart_snapshot)} | Total: {self.final_amount:.2f} MT | "
                            f"Pagamento: {self._payment_method_label()}"
                        )
                        self.db.log_action(username, role, "SALE", details)
                    except Exception:
                        pass
                return {"status": "ok", "receipt_data": receipt_data}
            except Exception as exc:
                return {"status": "error", "error": str(exc)}

        def apply_result(_dt, result):
            self._set_sale_busy(False)
            status = str((result or {}).get("status") or "")
            if status == "conflict":
                conflicts = result.get("conflicts") or []
                for item in self.cart_items:
                    live_product = (result.get("live_map") or {}).get(item["id"]) or self.products_dict.get(item["id"])
                    if live_product is not None:
                        item["max_stock"] = _unpack_sale_product(live_product)["stock"]
                self.update_cart_display()
                if conflicts:
                    name, requested, available = conflicts[0]
                    self.show_message(f"Stock alterado: {name} ({requested:.2f} > {available:.2f}).")
                return
            if status == "ok":
                self._last_completed_receipt_data = result.get("receipt_data")
                self.cart_items.clear()
                if self.ids:
                    self.ids.paid_input.text = ""
                    self.ids.discount_input.text = ""
                self._suspended_sale = None
                self.update_cart_display()
                self.manual_refresh_stock(silent=True)
                self._load_operational_snapshot()
                self.set_search_feedback("Venda finalizada com sucesso", "success", "cash-check")
                self.show_message("Venda finalizada com sucesso.")
                return
            self.show_message((result or {}).get("error") or "Erro ao finalizar venda.")

        def commit_worker():
            result = worker()
            Clock.schedule_once(lambda _dt, payload=result: apply_result(0, payload), 0)

        Thread(target=commit_worker, daemon=True).start()

    def emit_receipt(self):
        if self._sale_submitting:
            return
        receipt_data = resolve_receipt_data_for_emission(self._last_completed_receipt_data)
        if not receipt_data:
            self.show_message("Não há dados de venda para emitir recibo.")
            return

        def worker():
            path = None
            error = None
            try:
                path = self.receipt_report.generate(receipt_data)
                app = App.get_running_app()
                username = getattr(app, "current_user", None) if app else None
                role = getattr(app, "current_role", None) or "manager"
                if username:
                    try:
                        self.db.log_action(username, role, "SAVE_RECEIPT", f"Recibo salvo: {path}")
                    except Exception:
                        pass
            except Exception as exc:
                error = str(exc)
            Clock.schedule_once(lambda _dt, pdf_path=path, err=error: apply_result(pdf_path, err), 0)

        def apply_result(path, error):
            if error:
                self.show_message("Falha ao emitir recibo.")
                return
            if not path:
                self.show_message("Nao foi possivel localizar o PDF gerado.")
                return
            self._ensure_pdf_viewer().view_pdf(path)
            self.show_message(f"Recibo gerado em {os.path.basename(path)}.")
            self.set_search_feedback("Recibo pronto para visualizacao", "success", "file-document-check")

        Thread(target=worker, daemon=True).start()

    def _set_sale_busy(self, busy):
        self._sale_submitting = bool(busy)
        self._update_action_states()

    def _update_action_states(self):
        has_cart = bool(self.cart_items)
        has_receipt = can_emit_receipt(self._last_completed_receipt_data)
        if self.ids:
            self.ids.finalize_btn.disabled = (not has_cart) or self._sale_submitting
            self.ids.receipt_btn.disabled = (not has_receipt) or self._sale_submitting
            self.ids.cancel_btn.disabled = (not has_cart) or self._sale_submitting
            self.ids.clear_search_btn.disabled = not bool(self._current_search_text())
            self.ids.scan_toggle_btn.disabled = self._sale_submitting
            self.ids.pay_cash_btn.disabled = self._sale_submitting
            self.ids.pay_card_btn.disabled = self._sale_submitting
            self.ids.pay_mobile_btn.disabled = self._sale_submitting
            self.ids.paid_input.disabled = self._sale_submitting
            self.ids.discount_input.disabled = self._sale_submitting
        self.hold_button_text = "Retomar Venda" if (not has_cart and self._suspended_sale) else "Suspender Venda"

    def open_sales_history(self):
        if not self.manager:
            return
        app = App.get_running_app()
        ensure_screen = getattr(app, "ensure_screen", None) if app else None
        if "sales_history" not in self.manager.screen_names and callable(ensure_screen):
            ensure_screen("sales_history")
        if "sales_history" not in self.manager.screen_names:
            return
        screen = self.manager.get_screen("sales_history")
        if hasattr(screen, "back_target"):
            screen.back_target = self.name or "manager"
        if hasattr(screen, "request_enter_refresh"):
            Clock.schedule_once(lambda _dt: screen.request_enter_refresh(force=False, delay=0.02), 0.02)
        self.stop_scanner()
        self.manager.current = "sales_history"

    def open_losses_screen(self):
        if not self.manager:
            return
        app = App.get_running_app()
        ensure_screen = getattr(app, "ensure_screen", None) if app else None
        if "losses" not in self.manager.screen_names and callable(ensure_screen):
            ensure_screen("losses")
        if "losses" not in self.manager.screen_names:
            return
        screen = self.manager.get_screen("losses")
        if hasattr(screen, "back_target"):
            screen.back_target = self.name or "manager"
        if hasattr(screen, "prepare_open_from_admin"):
            Clock.schedule_once(lambda _dt: screen.prepare_open_from_admin(), 0.02)
        elif hasattr(screen, "request_enter_refresh"):
            Clock.schedule_once(lambda _dt: screen.request_enter_refresh(force=False, delay=0.02), 0.02)
        self.stop_scanner()
        self.manager.current = "losses"

    def _load_vision_modules(self):
        if self._vision_modules is None:
            self._vision_modules = get_vision_dependencies()
        return self._vision_modules

    def toggle_scanner(self):
        if self.scanning:
            self.stop_scanner()
            return
        try:
            self._load_vision_modules()
        except RuntimeError as exc:
            self.show_message(str(exc))
            self.set_search_feedback("Scanner indisponível neste ambiente", "danger", "camera-off")
            return
        self.scanning = True
        self._set_scanner_preview_visible(True)
        if self.ids:
            self.ids.scan_toggle_btn.icon = "barcode-off"
            self.ids.scan_toggle_btn.md_bg_color = [0.84, 0.24, 0.26, 1]
            self.ids.scanner_status_label.text = "A iniciar a câmara..."
        Clock.schedule_once(self.init_camera, 0.1)

    def stop_scanner(self):
        if not self.scanning and self.camera_capture is None:
            self._set_scanner_preview_visible(False)
            return
        self.scanning = False
        Clock.unschedule(self.update_camera)
        self.release_camera()
        self._set_scanner_preview_visible(False)
        if self.ids:
            self.ids.scan_toggle_btn.icon = "barcode-scan"
            self.ids.scan_toggle_btn.md_bg_color = [0.16, 0.72, 0.46, 1]

    def release_camera(self):
        if self.camera_capture is not None:
            try:
                self.camera_capture.release()
            except Exception:
                pass
            self.camera_capture = None
        if self.ids:
            image = self.ids.get("camera_image")
            if image is not None:
                image.texture = None

    def init_camera(self, _dt):
        try:
            cv2, _np, _decode = self._load_vision_modules()
            self.release_camera()
            self.camera_capture = cv2.VideoCapture(self.current_camera)
            if not self.camera_capture or not self.camera_capture.isOpened():
                self.stop_scanner()
                self.set_search_feedback("Câmara não encontrada", "warning", "camera-off")
                return
            self.camera_capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.camera_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.last_barcode = None
            self.last_barcode_time = 0.0
            if self.ids:
                self.ids.scanner_status_label.text = f"Câmara {self.current_camera} ativa"
            Clock.schedule_interval(self.update_camera, 1 / 18)
        except Exception:
            traceback.print_exc()
            self.stop_scanner()
            self.set_search_feedback("Erro ao iniciar o scanner", "danger", "alert-circle")

    def update_camera(self, _dt):
        if not self.scanning or self.camera_capture is None:
            return
        try:
            cv2, np, decode = self._load_vision_modules()
            ok, frame = self.camera_capture.read()
            if not ok or frame is None:
                return

            frame = cv2.convertScaleAbs(frame, alpha=1.2, beta=10)
            codes = decode(frame)
            current_time = time.time()
            if codes:
                code = codes[0]
                barcode_value = "".join(c for c in code.data.decode("utf-8", errors="ignore") if c.isprintable()).strip()
                if barcode_value and (
                    barcode_value != self.last_barcode or (current_time - self.last_barcode_time) > 2
                ):
                    self.last_barcode = barcode_value
                    self.last_barcode_time = current_time
                    if self.ids:
                        self.ids.scanner_status_label.text = f"Lido: {barcode_value}"
                    self._lookup_barcode_async(barcode_value, source="scanner")

                pts = code.polygon
                if len(pts) >= 4:
                    points = [(p.x, p.y) for p in pts]
                    cv2.polylines(frame, [np.array(points, dtype=np.int32)], True, (40, 220, 80), 3)

            buf = cv2.flip(frame, 0).tobytes()
            texture = Texture.create(size=(frame.shape[1], frame.shape[0]), colorfmt="bgr")
            texture.blit_buffer(buf, colorfmt="bgr", bufferfmt="ubyte")
            if self.ids:
                image = self.ids.get("camera_image")
                if image is not None:
                    image.texture = texture
        except Exception:
            traceback.print_exc()

    def switch_camera(self):
        was_active = self.scanning
        self.stop_scanner()
        self.current_camera = (self.current_camera + 1) % 4
        if was_active:
            self.toggle_scanner()

    def _set_notice_detail(self, notice_key, title, summary, extra_lines=None):
        lines = [str(summary or "").strip()]
        for line in (extra_lines or []):
            text = str(line or "").strip()
            if text:
                lines.append(text)
        self._notice_details[notice_key] = {
            "title": str(title or "Aviso"),
            "text": "\n\n".join(part for part in lines if part),
        }

    def _refresh_notice_widgets(self, *_args):
        if not self.ids:
            return
        for notice_key in self.NOTICE_KEYS:
            detail = self._notice_details.get(notice_key) or {}
            body = self.ids.get(f"notice_{notice_key}_detail_body")
            shell = self.ids.get(f"notice_{notice_key}_details_shell")
            toggle_icon = self.ids.get(f"notice_{notice_key}_toggle_icon")
            if body is None or shell is None:
                continue

            body.text = str(detail.get("text") or "").strip()
            shell.height = 0
            shell.opacity = 0
            if toggle_icon is not None:
                toggle_icon.icon = "chevron-up" if self._notice_overlay_visible and self._notice_overlay_key == notice_key else "chevron-right"

    def _position_notice_overlay(self, notice_key):
        if not self.ids:
            return
        overlay = self.ids.get("notice_overlay_card")
        card = self.ids.get(f"notice_{notice_key}_card")
        body_label = self.ids.get("notice_overlay_body")
        if overlay is None or card is None or body_label is None:
            return

        body_label.texture_update()
        max_width = max(dp(280), self.width - dp(28))
        overlay.width = min(max(card.width + dp(36), dp(300)), max_width)
        overlay.height = min(max(dp(124), body_label.texture_size[1] + dp(78)), max(dp(140), self.height - dp(120)))

        window_x, window_y = card.to_window(card.x, card.y, relative=False)
        local_x, local_y = self.to_widget(window_x, window_y, relative=False)
        target_x = max(dp(12), min(local_x + (card.width - overlay.width) / 2.0, self.width - overlay.width - dp(12)))
        below_y = local_y - overlay.height - dp(8)
        above_y = local_y + card.height + dp(8)
        if below_y >= dp(12):
            target_y = below_y
        else:
            target_y = min(max(dp(12), above_y), self.height - overlay.height - dp(12))
        overlay.pos = (target_x, target_y)

    def close_notice_overlay(self, *_args):
        if not self.ids:
            return
        overlay = self.ids.get("notice_overlay_card")
        if overlay is None:
            return
        self._notice_overlay_visible = False
        self._notice_overlay_key = None
        Animation.cancel_all(overlay)
        Animation(opacity=0, d=0.14, t="out_quad").start(overlay)
        overlay.disabled = True
        Clock.schedule_once(self._refresh_notice_widgets, 0)

    def open_notice_detail(self, notice_key):
        normalized_key = str(notice_key or "").strip()
        detail = self._notice_details.get(normalized_key) or {}
        if not str(detail.get("text") or "").strip():
            self.show_message("Sem detalhes adicionais neste aviso.")
            return
        if not self.ids:
            return

        overlay = self.ids.get("notice_overlay_card")
        title_label = self.ids.get("notice_overlay_title")
        body_label = self.ids.get("notice_overlay_body")
        if overlay is None or title_label is None or body_label is None:
            return

        if self._notice_overlay_visible and self._notice_overlay_key == normalized_key:
            self.close_notice_overlay()
            return

        title_label.text = str(detail.get("title") or "Aviso")
        body_label.text = str(detail.get("text") or "").strip()
        overlay.disabled = False
        self._notice_overlay_key = normalized_key
        self._notice_overlay_visible = True
        self._position_notice_overlay(normalized_key)
        Animation.cancel_all(overlay)
        overlay.opacity = 0
        Animation(opacity=1, d=0.16, t="out_quad").start(overlay)
        Clock.schedule_once(self._refresh_notice_widgets, 0)

    def _load_operational_snapshot(self):
        if self._snapshot_loading:
            return
        self._snapshot_loading = True

        def worker():
            snapshot = {}
            try:
                snapshot = self.db.get_admin_home_snapshot(lookback_days=7) or {}
            except Exception:
                snapshot = {}
            Clock.schedule_once(lambda _dt, data=snapshot: self._apply_operational_snapshot(data), 0)

        Thread(target=worker, daemon=True).start()

    def _apply_operational_snapshot(self, snapshot):
        self._snapshot_loading = False
        if not self.ids:
            return
        summary = snapshot.get("summary") or {}
        context = snapshot.get("context") or {}
        alerts = snapshot.get("alerts") or {}

        self.ids.sales_today_metric.text = str(int(summary.get("sales_today_count") or 0))
        self.ids.revenue_today_metric.text = _format_money(summary.get("revenue_today") or 0.0)
        top_product = context.get("top_product_today") or {}
        self.ids.top_product_metric.text = top_product.get("name") or "Sem dados"

        low_stock_items = alerts.get("low_stock_items") or []
        if low_stock_items:
            first = low_stock_items[0]
            self.ids.notice_one_icon.icon = "alert-outline"
            self.ids.notice_one_icon.text_color = [0.98, 0.76, 0.28, 1]
            self.ids.notice_one_title.text = "Stock baixo"
            self.ids.notice_one_body.text = f"{first.get('name', 'Produto')} com {_format_qty(first.get('stock'), bool(first.get('is_weight')))} disponível."
            low_stock_lines = [
                f"- {item.get('name', 'Produto')}: {_format_qty(item.get('stock'), bool(item.get('is_weight')))} disponível."
                for item in low_stock_items[:5]
            ]
            remaining_low_stock = len(low_stock_items) - len(low_stock_lines)
            if remaining_low_stock > 0:
                low_stock_lines.append(f"- Mais {remaining_low_stock} produto(s) com alerta de stock.")
            self._set_notice_detail(
                "one",
                "Stock baixo",
                "Lista dos produtos que merecem reposição mais rápida.",
                low_stock_lines,
            )
        else:
            self.ids.notice_one_icon.icon = "shield-check-outline"
            self.ids.notice_one_icon.text_color = [0.56, 0.90, 0.54, 1]
            self.ids.notice_one_title.text = "Stock sob controlo"
            self.ids.notice_one_body.text = "Sem alertas críticos no momento."
            self._set_notice_detail(
                "one",
                "Stock sob controlo",
                "Nao existem produtos em stock baixo neste momento.",
                [
                    "A reposicao atual parece equilibrada para a operacao.",
                ],
            )

        if top_product:
            self.ids.notice_two_icon.icon = "chart-line"
            self.ids.notice_two_icon.text_color = [0.42, 0.76, 1, 1]
            self.ids.notice_two_title.text = "Produto do dia"
            self.ids.notice_two_body.text = f"{top_product.get('name')} lidera com {_format_money(top_product.get('revenue'))}."
            top_product_lines = [
                f"- Produto: {top_product.get('name') or 'Sem nome'}",
                f"- Receita acumulada: {_format_money(top_product.get('revenue') or 0.0)}",
            ]
            quantity_sold = top_product.get("quantity")
            if quantity_sold not in (None, ""):
                top_product_lines.append(f"- Quantidade vendida: {_safe_float(quantity_sold):.2f}")
            self._set_notice_detail(
                "two",
                "Produto do dia",
                "Resumo do artigo com melhor desempenho no periodo atual.",
                top_product_lines,
            )
        else:
            self.ids.notice_two_icon.icon = "cash-remove"
            self.ids.notice_two_icon.text_color = [0.69, 0.73, 0.81, 1]
            self.ids.notice_two_title.text = "Movimento inicial"
            self.ids.notice_two_body.text = "Ainda não há produto destaque hoje."
            self._set_notice_detail(
                "two",
                "Movimento inicial",
                "Ainda nao ha dados suficientes para destacar um produto do dia.",
                [
                    f"- Vendas de hoje registadas: {int(summary.get('sales_today_count') or 0)}",
                    f"- Receita acumulada: {_format_money(summary.get('revenue_today') or 0.0)}",
                ],
            )

        peak_hour = context.get("peak_hour")
        if peak_hour:
            self.ids.notice_three_icon.icon = "clock-outline"
            self.ids.notice_three_icon.text_color = [0.56, 0.90, 0.54, 1]
            self.ids.notice_three_title.text = "Pico operacional"
            self.ids.notice_three_body.text = f"Maior movimento em {peak_hour}."
            self._set_notice_detail(
                "three",
                "Pico operacional",
                f"O maior fluxo atual de vendas concentrou-se em {peak_hour}.",
                [
                    f"- Vendas de hoje: {int(summary.get('sales_today_count') or 0)}",
                    f"- Receita acumulada: {_format_money(summary.get('revenue_today') or 0.0)}",
                ],
            )
        else:
            self.ids.notice_three_icon.icon = "calendar-clock"
            self.ids.notice_three_icon.text_color = [0.69, 0.73, 0.81, 1]
            self.ids.notice_three_title.text = "Pico operacional"
            self.ids.notice_three_body.text = "O sistema ainda está a acumular dados do dia."
            self._set_notice_detail(
                "three",
                "Pico operacional",
                "Ainda nao ha volume suficiente para identificar a hora de maior movimento.",
                [
                    "Volte a verificar este aviso depois de mais vendas registadas.",
                ],
            )
        Clock.schedule_once(self._refresh_notice_widgets, 0)

    def show_message(self, message):
        MDSnackbar(
            MDLabel(
                text=str(message),
                theme_text_color="Custom",
                text_color=[1, 1, 1, 1],
            ),
            pos=(dp(12), dp(12)),
            size_hint_x=0.55,
        ).open()

    def return_to_login(self):
        self.stop_scanner()
        app = App.get_running_app()
        if app:
            app.current_user = None
            app.current_role = None
        if not self.manager:
            return
        for screen_name in ("login_manager", "login"):
            if screen_name in self.manager.screen_names:
                screen = self.manager.get_screen(screen_name)
                if hasattr(screen, "reset_fields"):
                    try:
                        screen.reset_fields()
                    except Exception:
                        pass
                self.manager.current = screen_name
                return
