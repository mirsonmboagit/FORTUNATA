from kivy.uix.screenmanager import Screen
import os
import sys
import math
from kivy.properties import ObjectProperty, ListProperty, BooleanProperty
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.uix.modalview import ModalView
from kivy.app import App
from kivy.graphics import Color, Line
from kivy.animation import Animation
from collections import deque
from threading import Thread
import time
from datetime import datetime, timedelta
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.label import MDLabel
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.snackbar import MDSnackbar

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from AI.controller import ProactiveIntelligenceController

from database.provider import get_db
from ui.components.hover_widgets import HoverCard, HoverRaisedButton, HoverTooltipIconButton
from ui.components.loading_overlay import ScreenLoadingController
from utils.ai_insights import build_admin_insights, build_admin_insights_ai
from utils.ai_popups import (
    build_auto_banner_data,
    build_banner_details_sections,
    build_positive_banner,
    render_auto_banners,
)
from ui.components.tooltip_widgets import TooltipFloatingActionButton, TooltipIconButton
from utils.expiry_alerts import evaluate_expiry_alert, get_expiry_level_counts


def _get_detail_popup_class():
    # Importa o popup de detalhes mesmo quando o modulo muda de contexto.
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
    # Mostra uma mensagem simples se o formulario de produto falhar ao carregar.
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
    try:
        from .product_form import ProductForm
        return ProductForm
    except ImportError:
        try:
            from admin.product_form import ProductForm
            return ProductForm
        except Exception as exc:
            return _build_unavailable_product_form_class(exc)
    except Exception as exc:
        return _build_unavailable_product_form_class(exc)


Builder.load_file(os.path.join(CURRENT_DIR, 'admin_screen.kv'))


# ---------------------------------------------------------------------------
# Proporcoes das colunas da tabela.
# ---------------------------------------------------------------------------
COL_HINTS = [0.06, 0.20, 0.09, 0.09, 0.07, 0.11, 0.11, 0.13, 0.14]
LOSS_LABELS = {
    "DAMAGE": "Danificado",
    "EXPIRED": "Expirado",
    "THEFT": "Roubo",
    "ADJUSTMENT": "Ajuste",
}


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


class AdminScreen(Screen):
    # Tela principal do administrador.
    PRODUCTS_CACHE_SECONDS = 4
    LOSS_METRICS_LOOKBACK_DAYS = 365
    PRODUCTS_PAGE_SIZE = 18
    product_table = ObjectProperty(None)
    search_input = ObjectProperty(None)
    category_spinner = ObjectProperty(None)
    products = ListProperty([])
    quick_actions_open = BooleanProperty(False)
    shopping_list_busy = BooleanProperty(False)

    def __init__(self, **kwargs):
        db = kwargs.pop("db", None)
        super(AdminScreen, self).__init__(**kwargs)
        self.db = db or get_db()
        self.category_menu = None
        self._manual_categories = set()
        self._filter_ev = None
        self._pending_search = ""
        self._compact_layout = None
        
        # Variáveis para controle de notificações e animação
        self.swing_event = None
        self.notification_count = 0
        self._ai_poll_ev = None
        self._products_load_token = 0
        self._products_loading = False
        self._pending_products_load = False
        self._last_products_load_at = 0.0
        self._table_render_ev = None
        self._table_render_token = 0
        self._pending_table_rows = deque()
        self._table_row_height = dp(48)
        self._table_palette = {}
        self._current_display = []
        self._current_filtered_products = []
        self._product_page_index = 0
        self._display_ids_by_product_id = {}
        self._selected_lot_ids_by_catalog_key = {}
        self._alerts_refresh_token = 0
        self._ai_popup_token = 0
        self._fraud_check_token = 0
        self._fraud_check_until = 0.0
        self._last_fraud_log_count = 0
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
        self._loading_controller = getattr(self, "_loading_controller", None)
        self._intelligence = ProactiveIntelligenceController(
            screen=self,
            db=self.db,
            history_title="Historico de monitorizacao",
            banner_columns=1,
            auto_batch_size=2,
            auto_stagger_seconds=2.0,
            auto_present_enabled=False,
        )
        
        Window.bind(on_resize=self._on_window_resize)

    def on_kv_post(self, base_widget):
        # Finaliza controles que dependem dos ids carregados no KV.
        self._ensure_loading_overlay()
        Clock.schedule_once(lambda dt: self._update_responsive_layout(), 0)

    def _ensure_loading_overlay(self):
        if getattr(self, "_loading_controller", None) is None:
            self._loading_controller = ScreenLoadingController(self)
        self._loading_controller.attach()
        return self._loading_controller

    def _set_loading_overlay(self, key, active, message="", detail=""):
        controller = self._ensure_loading_overlay()
        if active:
            controller.show(key, message, detail)
            return
        controller.hide(key)

    def _clear_loading_overlay(self):
        if getattr(self, "_loading_controller", None) is not None:
            self._loading_controller.clear()

    def toggle_quick_actions(self, *args):
        self.quick_actions_open = not self.quick_actions_open

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
        if self.quick_actions_open:
            self.quick_actions_open = False
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
                "Alt+2: reposicao\n"
                "Alt+3: perdas\n"
                "Alt+4: relatorios\n"
                "Alt+S: definicoes\n"
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
        if "alt" in modifiers and key_name == "2":
            self.open_restock_screen()
            return True
        if "alt" in modifiers and key_name == "3":
            self.open_losses_screen()
            return True
        if "alt" in modifiers and key_name == "4":
            self.generate_report()
            return True
        if "alt" in modifiers and key_name == "s":
            self.go_to_definitions()
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
        # Executa tarefas demoradas fora da thread da interface.
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
            "Aguarde enquanto os dados sao preparados nesta tela.",
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
        """Rebuild table rows so every cell re-measures at the new size."""
        self._update_responsive_layout(width)
        Clock.unschedule(self._deferred_rebuild)
        Clock.schedule_once(self._deferred_rebuild, 0.15)

    def _deferred_rebuild(self, dt):
        self._render_current_product_page()

    def _update_responsive_layout(self, width=None):
        # Ajusta botoes e tabela conforme a largura da janela.
        if not self.ids:
            return
        width = width or Window.width
        compact = width < dp(900)
        if compact == self._compact_layout:
            return
        self._compact_layout = compact

        toolbar_card = self.ids.get("toolbar_card")
        toolbar_row = self.ids.get("toolbar_row")
        search_input = self.ids.get("search_input")
        category_spinner = self.ids.get("category_spinner")
        filter_btn = self.ids.get("filter_btn")
        add_btn = self.ids.get("add_btn")
        shopping_list_btn = self.ids.get("shopping_list_btn")

        if not toolbar_card or not toolbar_row:
            return

        if compact:
            toolbar_row.orientation = "vertical"
            toolbar_row.spacing = dp(8)
            toolbar_card.padding = [dp(12), dp(10)]

            if search_input:
                search_input.size_hint_x = 1
            if category_spinner:
                category_spinner.size_hint_x = 1
            if filter_btn:
                filter_btn.size_hint_x = 1
            if add_btn:
                add_btn.size_hint_x = 1
            if shopping_list_btn:
                shopping_list_btn.size_hint_x = 1

            toolbar_card.height = toolbar_row.minimum_height + dp(16)
        else:
            toolbar_row.orientation = "horizontal"
            toolbar_row.spacing = dp(10)
            toolbar_card.padding = [dp(16), dp(10)]

            if search_input:
                search_input.size_hint_x = 0.29
            if category_spinner:
                category_spinner.size_hint_x = 0.18
            if filter_btn:
                filter_btn.size_hint_x = None
                filter_btn.width = dp(48)
            if add_btn:
                add_btn.size_hint_x = 0.13
            if shopping_list_btn:
                shopping_list_btn.size_hint_x = 0.18

            toolbar_card.height = max(dp(70), self.height * 0.08)

    # ------------------------------------------------------------------
    # Sistema de Notificações e Animação de Abanar
    # ------------------------------------------------------------------
    def _init_badge(self, dt):
        """Inicializa o badge de notificações"""
        if hasattr(self.ids, 'ai_badge'):
            self.ids.ai_badge.opacity = 0

    def add_notification(self):
        """Adiciona uma nova notificação"""
        self.notification_count += 1
        self.update_notification_badge(self.notification_count)

    def clear_notifications(self):
        """Limpa todas as notificações"""
        self.notification_count = 0
        self.update_notification_badge(0)

    def update_notification_badge(self, count):
        """
        Atualiza o badge e controla a animação de abanar
        
        Args:
            count (int): Número de notificações
        """
        self.notification_count = count
        
        if not hasattr(self.ids, 'ai_badge') or not hasattr(self.ids, 'ai_badge_label'):
            return
        
        # Atualizar texto
        self.ids.ai_badge_label.text = str(count)
        
        if count > 0:
            self._show_badge()
            self._start_swing_animation()
        else:
            self._hide_badge()
            self._stop_swing_animation()

    def _show_badge(self):
        """Mostra o badge com animação pop"""
        if not hasattr(self.ids, 'ai_badge'):
            return
        
        # Pop in animation
        self.ids.ai_badge.size = (dp(0), dp(0))
        self.ids.ai_badge.opacity = 1
        
        anim = Animation(
            size=(dp(24), dp(24)),
            duration=0.3,
            transition='out_back'
        )
        anim.start(self.ids.ai_badge)

    def _hide_badge(self):
        """Esconde o badge com animação"""
        if not hasattr(self.ids, 'ai_badge'):
            return
        
        anim = Animation(
            opacity=0,
            size=(dp(0), dp(0)),
            duration=0.2
        )
        anim.start(self.ids.ai_badge)

    def _start_swing_animation(self):
        """Inicia animação de abanar/balançar a lâmpada"""
        if not hasattr(self.ids, 'ai_button'):
            return
        
        self._stop_swing_animation()
        
        def swing_cycle(dt):
            if self.notification_count <= 0:
                return False
            button = self.ids.ai_button
            base_pos = tuple(button.pos)
            self._ai_button_rest_pos = base_pos

            swing = (
                Animation(pos=(base_pos[0] + dp(4), base_pos[1] + dp(4)), duration=0.15, transition='out_sine') +
                Animation(pos=(base_pos[0] - dp(4), base_pos[1] - dp(3)), duration=0.3, transition='in_out_sine') +
                Animation(pos=(base_pos[0] + dp(3), base_pos[1] + dp(2)), duration=0.25, transition='in_out_sine') +
                Animation(pos=(base_pos[0] - dp(3), base_pos[1] - dp(2)), duration=0.25, transition='in_out_sine') +
                Animation(pos=(base_pos[0] + dp(2), base_pos[1] + dp(1)), duration=0.2, transition='in_out_sine') +
                Animation(pos=(base_pos[0] - dp(2), base_pos[1] - dp(1)), duration=0.2, transition='in_out_sine') +
                Animation(pos=base_pos, duration=0.15, transition='out_sine')
            )
            swing.start(button)
            return True
        
        self.swing_event = Clock.schedule_interval(swing_cycle, 2.5)
        swing_cycle(0)
    
    def _stop_swing_animation(self):
        """Para a animação de abanar"""
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
        try:
            return f"{float(value or 0):,.2f} MZN".replace(",", " ")
        except Exception:
            return "0.00 MZN"

    def _loss_type_label(self, code):
        return LOSS_LABELS.get(str(code or "").upper(), str(code or "Sem tipo"))

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
        from kivymd.uix.card import MDCard
        from kivymd.uix.label import MDIcon

        app = App.get_running_app()
        tokens = getattr(app, "theme_tokens", {}) if app else {}
        tone_color = tokens.get(
            tone,
            tokens.get("info", [0.15, 0.45, 0.75, 1]),
        )

        card = MDCard(
            orientation="vertical",
            size_hint_y=None,
            height=dp(120),
            padding=dp(14),
            spacing=dp(8),
            radius=[dp(18)],
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
            )
        )
        return card

    def _build_loss_section_card(self, title, lines, icon_name="text-box-outline", tone="info"):
        from kivymd.uix.card import MDCard
        from kivymd.uix.label import MDIcon

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
            radius=[dp(18)],
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

        section_lines = list(lines or []) or ["Sem dados suficientes para apresentar nesta secao."]
        for line in section_lines:
            item = MDLabel(
                text=str(line),
                size_hint_y=None,
                font_size=dp(11.5),
                theme_text_color="Secondary",
            )
            item.bind(
                texture_size=lambda inst, value: setattr(
                    inst,
                    "height",
                    max(dp(18), value[1]),
                )
            )
            card.add_widget(item)

        return card

    def _build_loss_metrics_content(self, metrics, start_date, end_date, detailed=False):
        from kivy.uix.scrollview import ScrollView
        from kivymd.uix.gridlayout import MDGridLayout

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
        content.add_widget(
            self._build_loss_section_card(
                "Resumo Executivo",
                header_lines,
                icon_name="chart-areaspline",
                tone="info",
            )
        )

        metrics_grid = MDGridLayout(
            cols=1 if Window.width < dp(1180) else 2,
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
                        "A secao por utilizador ajuda a identificar concentracao de perdas por operador.",
                        "A secao por produto ajuda a decidir reposicao, promocao ou revisao de manuseio.",
                    ],
                    icon_name="lightbulb-on-outline",
                    tone="success",
                )
            )

        scroll = ScrollView(
            do_scroll_x=False,
            bar_width=dp(6),
            size_hint=(1, 1),
        )
        scroll.add_widget(content)
        return scroll

    def _show_pdf_success(self, pdf_path):
        dialog = MDDialog(
            title="PDF Gerado",
            text=f"Arquivo criado em:\n{pdf_path}",
            buttons=[
                MDFlatButton(text="FECHAR", on_release=lambda _x: dialog.dismiss()),
                MDRaisedButton(
                    text="ABRIR PDF",
                    on_release=lambda _x: self._open_pdf(dialog, pdf_path),
                ),
            ],
        )
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
        categories = set(self._manual_categories)
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
        """Show dropdown menu for category selection"""
        menu_items = [
            {
                "text": "Todas as Categorias",
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
        """Set the selected category and filter products"""
        self.category_spinner.text = category if category != "Todas" else "Todas as Categorias"
        if self.category_menu:
            self.category_menu.dismiss()
        self.filter_products(self.search_input.text if self.search_input else "")

    def queue_filter(self, search_text):
        self._pending_search = search_text or ""
        if self._filter_ev:
            Clock.unschedule(self._filter_ev)
        self._filter_ev = Clock.schedule_once(self._apply_queued_filter, 0.2)

    def _apply_queued_filter(self, dt):
        self._filter_ev = None
        self.filter_products(self._pending_search)

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
        source_rows = list(self._current_filtered_products or self.products or [])
        self.update_product_table(source_rows, reset_page=False)
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
        # Escolhe o lote que representa o grupo na tabela.
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

    def _aggregate_products_for_table(self, rows):
        # Junta lotes iguais para a lista ficar mais facil de ler.
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

    # ------------------------------------------------------------------
    # Search / filter
    # ------------------------------------------------------------------
    def filter_products(self, search_text):
        category_text = self.category_spinner.text if self.category_spinner else "Todas as Categorias"
        category = category_text if category_text != "Todas as Categorias" else "Todas"
        search_value = (search_text or "").strip().lower()
        filtered = []

        for product in self.products:
            display_id = self._get_display_id(product)
            source_ids = self._get_group_source_ids(product)
            search_match = (
                search_value in str(display_id).lower() or
                search_value in str(product[0]).lower() or
                (len(product) > 1 and search_value in str(product[1]).lower()) or
                (len(product) > 11 and search_value in str(product[11]).lower()) or
                (len(product) > 12 and product[12] and search_value in str(product[12]).lower()) or
                any(search_value in str(product_id).lower() for product_id in source_ids)
            )
            category_match = (
                category in ('Todas', 'Todas as Categorias') or
                (len(product) > 11 and category == product[11])
            )
            if search_match and category_match:
                filtered.append(product)

        self._current_filtered_products = list(filtered)
        self.update_product_table(filtered)

    def clear_search(self):
        if self.search_input is not None:
            self.search_input.text = ""
            self.search_input.focus = False
        self._pending_search = ""
        self.filter_products("")

    def refresh_products_panel(self):
        self.load_products()
        self.show_snackbar("A atualizar lista de produtos...")

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------
    def load_products(self):
        if self._products_loading:
            self._pending_products_load = True
            return

        token = self._products_load_token + 1
        self._products_load_token = token
        self._products_loading = True
        self._set_loading_overlay(
            "products",
            True,
            "A carregar catalogo do admin...",
            "Estamos a atualizar a lista de produtos, stock e alertas principais.",
        )

        def worker():
            try:
                rows = self.db.get_all_products() or []
            except Exception as e:
                print(f"Erro ao carregar produtos: {e}")
                rows = []
            Clock.schedule_once(lambda dt, data=rows, tok=token: self._apply_loaded_products(data, tok), 0)

        Thread(target=worker, daemon=True).start()

    def _apply_loaded_products(self, rows, token):
        if token != self._products_load_token:
            return
        self._products_loading = False
        self._set_loading_overlay("products", False)
        self._last_products_load_at = time.perf_counter()
        self.products = list(rows or [])
        self._prune_selected_lot_ids(self.products)
        self._rebuild_display_ids(self._aggregate_products_for_table(self.products))
        self._expiry_alerts_by_id = self._build_expiry_alerts(self.products)
        self.filter_products(self.search_input.text if self.search_input else self._pending_search)
        self._show_expiry_dashboard_summary()
        if self._pending_products_load:
            self._pending_products_load = False
            Clock.schedule_once(lambda dt: self.load_products(), 0.05)

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
        """Compute a single row height that scales with the window."""
        base_height = max(dp(46), Window.height * 0.054)
        return min(base_height, dp(62))

    def _theme_tokens(self):
        app = App.get_running_app()
        return getattr(app, "theme_tokens", {}) if app else {}

    # ------------------------------------------------------------------
    # Table rendering com linhas separadoras PRETAS
    # ------------------------------------------------------------------
    def update_product_table(self, products_to_display=None, reset_page=True):
        # Monta a tabela em lotes para manter a tela responsiva.
        """Atualizar a tabela de produtos com separadores visuais pretos."""
        if products_to_display is None:
            products_to_display = self.products
        self._current_display = self._aggregate_products_for_table(products_to_display or [])
        self._rebuild_display_ids(self._current_display)
        if reset_page:
            self._product_page_index = 0
        self._render_current_product_page()

    def _render_current_product_page(self):
        if self._table_render_ev:
            Clock.unschedule(self._table_render_ev)
            self._table_render_ev = None

        self._table_render_token += 1
        token = self._table_render_token

        display_rows = list(self._current_display or [])
        total_rows = len(display_rows)
        page_size = max(1, int(self.PRODUCTS_PAGE_SIZE))
        total_pages = max(1, (total_rows + page_size - 1) // page_size) if total_rows else 1
        self._product_page_index = min(max(0, self._product_page_index), total_pages - 1)
        start_index = self._product_page_index * page_size
        page_rows = display_rows[start_index:start_index + page_size]

        self._sync_product_pagination_controls(total_rows, len(page_rows))

        if not self.product_table:
            return

        self.product_table.clear_widgets()

        if not page_rows:
            self._pending_table_rows = deque()
            return

        row_h = self._row_height()
        tokens = self._theme_tokens()
        self._table_row_height = row_h
        self._table_palette = {
            "tokens": tokens,
            "row_even": tokens.get("surface_alt", [0.97, 0.98, 0.99, 1]),
            "row_odd": tokens.get("card", [1, 1, 1, 1]),
            "border_color": tokens.get("divider", [0, 0, 0, 0.25]),
            "text_primary": tokens.get("text_primary", [0.25, 0.30, 0.40, 1]),
            "text_secondary": tokens.get("text_secondary", [0.2, 0.25, 0.35, 1]),
            "text_muted": tokens.get("text_muted", [0.45, 0.50, 0.55, 1]),
            "info_color": tokens.get("info", [0.1, 0.45, 0.75, 1]),
            "success_color": tokens.get("success", [0.10, 0.55, 0.25, 1]),
            "warning_color": tokens.get("warning", [0.75, 0.45, 0.10, 1]),
            "danger_color": tokens.get("danger", [0.8, 0.2, 0.2, 1]),
        }
        self._pending_table_rows = deque(
            (start_index + idx, product) for idx, product in enumerate(page_rows)
        )
        self._table_render_ev = Clock.schedule_interval(
            lambda dt, tok=token: self._render_table_batch(dt, tok),
            0
        )
        return

    def _sync_product_pagination_controls(self, total_rows, visible_rows):
        if not self.ids:
            return

        page_size = max(1, int(self.PRODUCTS_PAGE_SIZE))
        total_pages = max(1, (total_rows + page_size - 1) // page_size) if total_rows else 1
        current_page = min(self._product_page_index, total_pages - 1) + 1

        label = self.ids.get("admin_page_label")
        if label is not None:
            if total_rows <= 0:
                label.text = "Pagina 1/1 | 0 itens"
            else:
                start = (self._product_page_index * page_size) + 1
                end = start + max(0, int(visible_rows)) - 1
                label.text = f"Pagina {current_page}/{total_pages} | {start}-{end} de {total_rows}"

        prev_btn = self.ids.get("admin_prev_btn")
        if prev_btn is not None:
            prev_btn.disabled = self._products_loading or self._product_page_index <= 0

        next_btn = self.ids.get("admin_next_btn")
        if next_btn is not None:
            next_btn.disabled = self._products_loading or current_page >= total_pages or total_rows <= 0

    def previous_product_page(self):
        if self._products_loading or self._product_page_index <= 0:
            return False
        self._product_page_index -= 1
        self._render_current_product_page()
        return True

    def next_product_page(self):
        total_rows = len(self._current_display or [])
        page_size = max(1, int(self.PRODUCTS_PAGE_SIZE))
        total_pages = max(1, (total_rows + page_size - 1) // page_size) if total_rows else 1
        if self._products_loading or self._product_page_index >= (total_pages - 1):
            return False
        self._product_page_index += 1
        self._render_current_product_page()
        return True


    def _render_table_batch(self, dt, token):
        if token != self._table_render_token:
            return False
        if not self._pending_table_rows:
            self._table_render_ev = None
            return False

        batch_size = 8
        for _ in range(min(batch_size, len(self._pending_table_rows))):
            idx, product = self._pending_table_rows.popleft()
            self._append_product_row(product, idx, self._table_row_height, self._table_palette)

        if not self._pending_table_rows:
            self._table_render_ev = None
            return False
        return True

    def _make_product_cell(self, col_idx, row_h, bg_color, border_color, align='center'):
        cell = MDBoxLayout(
            size_hint_x=COL_HINTS[col_idx],
            size_hint_y=None,
            height=row_h,
            md_bg_color=bg_color,
            padding=[dp(6), 0] if align == 'center' else [dp(10), 0]
        )

        def draw_borders(instance, *_):
            instance.canvas.after.clear()
            with instance.canvas.after:
                Color(*border_color)
                Line(
                    points=[
                        instance.x + instance.width,
                        instance.y,
                        instance.x + instance.width,
                        instance.y + instance.height,
                    ],
                    width=1
                )
                Line(
                    points=[instance.x, instance.y, instance.x + instance.width, instance.y],
                    width=1
                )

        cell.bind(pos=draw_borders, size=draw_borders)
        draw_borders(cell)
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
        self.product_table.add_widget(cell)

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
        self.product_table.add_widget(cell)

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
        self.product_table.add_widget(cell)

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
        self.product_table.add_widget(cell)

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
        self.product_table.add_widget(cell)

        cell = self._make_product_cell(5, row_h, row_bg_color, border_color)
        cell.add_widget(MDLabel(
            text=f"{product[4]:.2f} MT",
            theme_text_color="Custom",
            text_color=success_color,
            halign='center',
            bold=True,
            font_style="Body1"
        ))
        self.product_table.add_widget(cell)

        cell = self._make_product_cell(6, row_h, row_bg_color, border_color)
        cell.add_widget(MDLabel(
            text=f"{product[8]:.2f} MT",
            theme_text_color="Custom",
            text_color=info_color,
            halign='center',
            bold=True,
            font_style="Body1"
        ))
        self.product_table.add_widget(cell)

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
        self.product_table.add_widget(cell)

        cell = self._make_product_cell(8, row_h, row_bg_color, border_color)
        action_layout = MDBoxLayout(spacing=dp(4), padding=[dp(4), 0])
        action_layout.add_widget(self.create_detail_button(product, tokens=action_tokens))
        action_layout.add_widget(self.create_edit_button(product, tokens=action_tokens))
        action_layout.add_widget(self.create_delete_button(product, tokens=action_tokens))
        cell.add_widget(action_layout)
        self.product_table.add_widget(cell)

    # ------------------------------------------------------------------
    # Action buttons com Material Design
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
        Clock.schedule_once(lambda dt, current=product: _get_product_form_class()(self, current).open(), 0)
        return True

    def _prompt_delete_product(self, product_id):
        normalized_id = self._normalize_product_id(product_id)
        if normalized_id is None:
            self.show_snackbar("Produto nao encontrado")
            return False

        self.dialog = MDDialog(
            title="Confirmar Eliminação",
            text="Tem certeza que deseja eliminar este produto?",
            buttons=[
                MDFlatButton(
                    text="NAO",
                    theme_text_color="Custom",
                    text_color=[0.3, 0.3, 0.3, 1],
                    on_release=lambda x: self.dialog.dismiss()
                ),
                MDRaisedButton(
                    text="SIM",
                    md_bg_color=[0.9, 0.3, 0.3, 1],
                    on_release=lambda x, pid=normalized_id: self.confirm_delete(pid)
                ),
            ],
        )
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
            self.load_products()
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
            icon_size=sp(20),
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
            icon_size=sp(20),
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
            icon_size=sp(20),
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
        Clock.schedule_once(lambda dt: _get_product_form_class()(self).open(), 0)

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
                    self.db.log_action(username, role, "DELETE_PRODUCT", f"Produto eliminado ID {product_id}")
                except Exception:
                    pass
            return ok

        def on_success(ok):
            if ok:
                self.load_products()
                self.show_snackbar("Produto eliminado com sucesso!")
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
    # Snackbar for notifications
    # ------------------------------------------------------------------
    def show_snackbar(self, message):
        MDSnackbar(
            MDLabel(
                text=message,
                theme_text_color="Custom",
                text_color=[1, 1, 1, 1],
            ),
            pos=(dp(10), dp(10)),
            size_hint_x=0.5,
        ).open()

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
        return "|".join(parts)

    def mark_notifications_seen(self, insights=None):
        insights = insights or self._cached_admin_insights or {}
        key = self._get_alert_key(insights) if insights else ""
        app = App.get_running_app()
        if app:
            app._ai_notifications_seen_key = key
        self.update_notification_badge(0)

    def _refresh_alerts_async(self, show_popups=True):
        token = self._alerts_refresh_token + 1
        self._alerts_refresh_token = token

        def worker():
            try:
                insights = build_admin_insights(self.db) or {}
            except Exception as exc:
                print(f"Erro ao atualizar alertas AI: {exc}")
                insights = {}
            Clock.schedule_once(
                lambda dt, data=insights, tok=token, pop=show_popups: self._apply_alerts_refresh(data, tok, pop),
                0
            )

        Thread(target=worker, daemon=True).start()

    def _apply_alerts_refresh(self, insights, token, show_popups):
        if token != self._alerts_refresh_token:
            return
        self._cached_admin_insights = insights or {}
        self.update_ai_badge(insights=self._cached_admin_insights)
        if show_popups:
            self.show_auto_ai_popups(insights=self._cached_admin_insights)

    def _load_ai_insights_async(self, target):
        token = self._ai_popup_token + 1
        self._ai_popup_token = token
        self.show_snackbar("A preparar insights...")

        def worker():
            try:
                insights = build_admin_insights_ai(self.db) or {}
            except Exception as exc:
                print(f"Erro ao carregar insights AI: {exc}")
                insights = build_admin_insights(self.db) or {}
            Clock.schedule_once(
                lambda dt, kind=target, data=insights, tok=token: self._apply_ai_insights_result(kind, data, tok),
                0
            )

        Thread(target=worker, daemon=True).start()

    def _apply_ai_insights_result(self, kind, insights, token):
        if token != self._ai_popup_token:
            return
        self._render_ai_insights(kind, insights or {})

    def _render_ai_insights(self, kind, insights):
        if not hasattr(self, "ids") or "ai_banner_container" not in self.ids:
            return

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
        ensure_center = getattr(self._intelligence, "_ensure_banner_center", None)
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
        self._intelligence.open_history(caller=caller)

    def open_ai_menu(self, caller):
        if caller is None and hasattr(self, "ids") and "ai_button" in self.ids:
            caller = self.ids.ai_button
        self._intelligence.open_history(caller=caller)

    def _open_ai_from_menu(self, key):
        if hasattr(self, "_ai_menu") and self._ai_menu:
            self._ai_menu.dismiss()
        caller = self.ids.ai_button if hasattr(self, "ids") and "ai_button" in self.ids else None
        self._intelligence.open_history(caller=caller)

    def show_ai_stock_popup(self, *args, insights=None, on_close=None):
        self._intelligence.refresh()

    def show_ai_expiry_popup(self, *args, insights=None, on_close=None):
        self._intelligence.refresh()

    def show_auto_ai_popups(self, *args, insights=None):
        self._intelligence.refresh()

    def update_ai_badge(self, *args, insights=None):
        """Atualiza o badge do botão de insights com animação de abanar"""
        insights = insights or self._cached_admin_insights or {}
        if not insights:
            self.update_notification_badge(0)
            return
        key = self._get_alert_key(insights)
        badge_counts = insights.get("badge_counts") or {}
        count = badge_counts.get("total", 0)

        if not key:
            count = 0

        app = App.get_running_app()
        if app and getattr(app, "_ai_notifications_seen_key", None) == key:
            count = 0

        self.update_notification_badge(count)

    def _poll_ai_alerts(self, dt):
        self._intelligence.refresh()

    def _start_ai_polling(self):
        self._intelligence.start()

    def _stop_ai_polling(self):
        self._intelligence.stop()

    # ------------------------------------------------------------------
    # Lista de compras
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
                "days_left": days_left,
                "unit_cost": unit_cost,
                "sale_price": sale_price,
                "expiry_date": bucket["expiry_date"],
                "lot_count": bucket["lot_count"],
                "statuses": tuple(sorted(bucket["statuses"])),
                "last_update": bucket["last_update"],
            })

        return grouped

    def _build_shopping_item(self, product, velocity_days, target_days, warning_days, min_stock):
        stock_value = max(0.0, _safe_float(product.get("stock"), 0.0))
        avg_daily = max(0.0, _safe_float(product.get("avg_daily"), 0.0))
        unit_cost = _safe_float(product.get("unit_cost"), 0.0)
        sale_price = _safe_float(product.get("sale_price"), 0.0)
        is_weight = bool(product.get("is_weight"))
        unit = "KG" if is_weight else "UN"
        today = datetime.now().date()
        expiry_date = product.get("expiry_date")
        days_to_expiry = None
        usable_stock = stock_value
        notes = []

        if expiry_date is not None:
            days_to_expiry = (expiry_date - today).days
            if days_to_expiry < 0:
                usable_stock = 0.0
                notes.append("stock vencido")
            elif days_to_expiry <= target_days:
                notes.append(f"validade em {days_to_expiry} dias")
                if avg_daily > 0:
                    usable_stock = min(stock_value, avg_daily * max(days_to_expiry, 0))
                elif days_to_expiry <= warning_days:
                    usable_stock = 0.0

        days_left = (usable_stock / avg_daily) if avg_daily > 0 else None
        include = False
        reason = "Reposicao preventiva"

        if stock_value <= 0:
            include = True
            reason = "Esgotado"
        elif usable_stock <= 0:
            include = True
            reason = "Stock sem cobertura util"
        elif usable_stock <= min_stock:
            include = True
            reason = "Stock baixo"
        elif days_left is not None and days_left <= warning_days:
            include = True
            reason = "Cobertura curta"

        if not include:
            return None

        if avg_daily > 0:
            target_stock = max(min_stock, avg_daily * target_days)
        else:
            target_stock = min_stock * 2 if usable_stock <= min_stock else min_stock

        needed_qty = max(0.0, target_stock - usable_stock)
        if needed_qty <= 0:
            needed_qty = min_stock

        if is_weight:
            needed_qty = round(needed_qty, 2)
        else:
            needed_qty = float(max(1, int(math.ceil(needed_qty - 1e-9))))

        if needed_qty <= 0:
            return None

        if stock_value <= 0:
            priority = "Esgotado"
            priority_rank = 0
        elif days_left is not None and days_left <= 3:
            priority = "Critico"
            priority_rank = 1
        elif usable_stock <= (min_stock / 2.0):
            priority = "Critico"
            priority_rank = 1
        else:
            priority = "Baixo"
            priority_rank = 2

        if not notes:
            notes.append(reason.lower())

        purchase_cost = needed_qty * unit_cost
        potential_revenue = needed_qty * sale_price
        potential_profit = needed_qty * (sale_price - unit_cost)

        return {
            "product_ids": product.get("product_ids") or (),
            "name": product.get("name") or "Produto sem nome",
            "barcode": product.get("barcode") or "",
            "unit": unit,
            "current_stock": stock_value,
            "usable_stock": usable_stock,
            "avg_daily": avg_daily,
            "days_left": days_left,
            "needed_qty": needed_qty,
            "target_stock": target_stock,
            "unit_cost": unit_cost,
            "sale_price": sale_price,
            "purchase_cost": purchase_cost,
            "potential_revenue": potential_revenue,
            "potential_profit": potential_profit,
            "priority": priority,
            "priority_rank": priority_rank,
            "reason": reason,
            "notes": "; ".join(notes),
            "expiry_date": expiry_date.isoformat() if expiry_date else "",
            "days_to_expiry": days_to_expiry,
            "lot_count": int(product.get("lot_count") or 1),
            "velocity_days": velocity_days,
        }

    def _build_shopping_list_payload(self, rows, source="stock_control"):
        velocity_days = 14
        target_days = 14
        warning_days = 7
        min_stock = 5.0

        grouped_products = self._group_shopping_products(rows, source=source)
        items = []
        for product in grouped_products:
            item = self._build_shopping_item(
                product,
                velocity_days=velocity_days,
                target_days=target_days,
                warning_days=warning_days,
                min_stock=min_stock,
            )
            if item:
                items.append(item)

        items.sort(key=lambda item: (
            item.get("priority_rank", 9),
            item.get("days_left") is None,
            item.get("days_left") if item.get("days_left") is not None else 999999,
            str(item.get("name") or "").lower(),
        ))

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
            "out_of_stock_count": sum(1 for item in items if item.get("priority") == "Esgotado"),
            "critical_count": sum(1 for item in items if item.get("priority") == "Critico"),
            "low_count": sum(1 for item in items if item.get("priority") == "Baixo"),
            "total_investment": total_investment,
            "total_potential_revenue": total_revenue,
            "total_potential_profit": total_profit,
            "unit_qty": unit_qty,
            "kg_qty": kg_qty,
            "velocity_days": velocity_days,
            "target_days": target_days,
            "warning_days": warning_days,
            "min_stock": min_stock,
            "source": source,
        }
        return {"items": items, "summary": summary}

    def _load_shopping_list_payload(self):
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
        return self._build_shopping_list_payload(rows, source=source)

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
        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(10),
            padding=[dp(4), dp(2), dp(4), 0],
            size_hint_y=None,
        )
        content.bind(minimum_height=content.setter("height"))

        total_text = (
            f"{len(items)} produtos | Total estimado: "
            f"{self._format_shopping_money(summary.get('total_investment'))}"
        )
        content.add_widget(
            MDLabel(
                text=total_text,
                size_hint_y=None,
                height=dp(24),
                halign="left",
                bold=True,
                theme_text_color="Custom",
                text_color=self._theme_tokens().get("text_primary", [0.15, 0.18, 0.24, 1]),
            )
        )
        content.add_widget(self._build_shopping_preview_row(header=True))

        scroll = ScrollView(
            do_scroll_x=False,
            do_scroll_y=True,
            size_hint_y=None,
            height=min(dp(360), max(dp(150), Window.height * 0.42)),
            bar_width=dp(6),
        )
        rows_box = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=0,
        )
        rows_box.bind(minimum_height=rows_box.setter("height"))
        for idx, item in enumerate(items):
            rows_box.add_widget(self._build_shopping_preview_row(item=item, index=idx))
        scroll.add_widget(rows_box)
        content.add_widget(scroll)

        dialog = MDDialog(
            title="Lista de Compras",
            type="custom",
            content_cls=content,
            size_hint=(None, None),
            size=(min(dp(760), Window.width * 0.92), min(dp(560), Window.height * 0.88)),
            buttons=[
                MDFlatButton(text="FECHAR", on_release=lambda _btn: dialog.dismiss()),
                MDRaisedButton(
                    text="GERAR PDF",
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
                payload = self._load_shopping_list_payload()
                if not payload.get("items"):
                    return {"status": "empty"}
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
                return
            if status == "empty":
                self.show_snackbar("Nenhum produto precisa de reposicao neste momento.")
                return
            message = (result or {}).get("message") or "Erro ao preparar lista de compras."
            self.show_snackbar(f"Erro ao preparar lista de compras: {message}")

        started = self._run_async_action(
            "shopping-list-preview",
            task,
            on_success=on_success,
            busy_message="A preparar lista de compras...",
            error_message="Erro ao preparar lista de compras",
        )
        if not started:
            self.shopping_list_busy = False

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
                    "min_stock": export_payload["summary"].get("min_stock", 5),
                    "source_label": "Tela de produtos",
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
                self.show_snackbar("Nenhum produto precisa de reposicao neste momento.")
                return
            message = (result or {}).get("message") or "Erro ao gerar lista de compras."
            self.show_snackbar(f"Erro ao gerar lista de compras: {message}")

        started = self._run_async_action(
            "shopping-list-pdf",
            task,
            on_success=on_success,
            busy_message="A gerar lista de compras...",
            error_message="Erro ao gerar lista de compras",
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
            Clock.schedule_once(lambda dt: reports_screen.prepare_open_from_admin(), 0.02)
        Clock.schedule_once(lambda dt: reports_screen.select_date_range(), 0.12)

    def toggle_kg_products(self):
        if "kg-filter" in self._async_actions:
            return
        if not hasattr(self, 'filter_mode'):
            self.filter_mode = 0

        self.filter_mode = (self.filter_mode + 1) % 3

        if self.filter_mode == 1:
            def task():
                return self.db.get_products_by_weight() or []

            def on_success(kg_products):
                if kg_products:
                    self.update_product_table(kg_products)
                    self.show_snackbar("Mostrando apenas produtos vendidos por KG")
                    return
                self.filter_mode = 2
                unit_products = [p for p in self.products if not (len(p) > 15 and p[15])]
                if unit_products:
                    self.update_product_table(unit_products)
                    self.show_snackbar("Mostrando apenas produtos vendidos por unidade")
                    return
                self.filter_mode = 0
                self.update_product_table(self.products)
                self.show_snackbar("Mostrando todos os produtos")

            self._run_async_action(
                "kg-filter",
                task,
                on_success=on_success,
                busy_message="A carregar produtos por KG...",
                error_message="Erro ao carregar filtro por KG",
            )
        elif self.filter_mode == 2:
            unit_products = [p for p in self.products if not (len(p) > 15 and p[15])]
            if unit_products:
                self.update_product_table(unit_products)
                self.show_snackbar("Mostrando apenas produtos vendidos por unidade")
            else:
                self.filter_mode = 0
                self.update_product_table(self.products)
                self.show_snackbar("Mostrando todos os produtos")
        else:
            self.update_product_table(self.products)
            self.show_snackbar("Mostrando todos os produtos")


    def open_losses_screen(self, *args):
        """Abrir tela de perdas"""
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
        """Abrir tela de reposição de stock"""
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

    def show_loss_metrics(self, *args):
        """Mostrar metricas de perdas no periodo padrao do historico."""
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
                size_hint=(0.92, 0.9),
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
        """Mostrar relatorio detalhado de perdas"""
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
                size_hint=(0.93, 0.92),
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
        """Mostrar alertas de fraude"""
        def task():
            return self.db.detect_fraud_patterns(days_lookback=30)

        def on_success(alerts):
            if not alerts:
                self.show_snackbar("Nenhum alerta de fraude detectado")
                return

            high_alerts = [a for a in alerts if a['severity'] == 3]
            medium_alerts = [a for a in alerts if a['severity'] == 2]
            low_alerts = [a for a in alerts if a['severity'] == 1]

            message = f"""ALERTAS DE SEGURANCA

    ALTA PRIORIDADE: {len(high_alerts)}
    MEDIA PRIORIDADE: {len(medium_alerts)}
    BAIXA PRIORIDADE: {len(low_alerts)}

    PRINCIPAIS ALERTAS:"""

            for alert in (high_alerts + medium_alerts)[:5]:
                severity_icon = {3: "[ALTO]", 2: "[MEDIO]", 1: "[BAIXO]"}[alert['severity']]
                message += f"\n\n{severity_icon} {alert['title']}\n{alert['description']}"

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
        """Mostrar todos os alertas em detalhe"""
        try:
            from kivymd.uix.boxlayout import MDBoxLayout
            from kivymd.uix.label import MDLabel
            from kivy.uix.scrollview import ScrollView
            from kivy.metrics import dp

            content = MDBoxLayout(
                orientation='vertical',
                padding=dp(20),
                spacing=dp(10),
                size_hint_y=None
            )
            content.bind(minimum_height=content.setter('height'))

            for alert in alerts:
                severity_label = {3: "ALTO", 2: "MEDIO", 1: "BAIXO"}[alert['severity']]

                alert_text = f"""{severity_label} - {alert['alert_type']}

    {alert['title']}
    {alert['description']}

    """
                if alert['related_user']:
                    alert_text += f"Utilizador: {alert['related_user']}\n"

                alert_text += "-" * 50 + "\n"

                alert_label = MDLabel(
                    text=alert_text,
                    size_hint_y=None,
                    halign='left'
                )
                alert_label.bind(texture_size=alert_label.setter('size'))
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
        """Mostrar aprovacoes pendentes"""
        def task():
            return self.db.get_pending_approvals()

        def on_success(pending):
            if not pending:
                self.show_snackbar("Nenhuma aprovacao pendente")
                return

            message = f"APROVACOES PENDENTES: {len(pending)}\n\n"

            for row in pending[:5]:
                mov_id, prod_id, description, mov_type, qty, unit, cost, price, reason, note, evidence, created_at, user, role = row

                message += f"""ID #{mov_id} - {mov_type}
    Produto: {description}
    Quantidade: {qty} {unit}
    Custo: {cost:.2f} MZN
    Por: {user}
    Motivo: {reason[:50]}...
    {'Com evidencia' if evidence else 'Sem evidencia'}

    """

            if len(pending) > 5:
                message += f"\n... e mais {len(pending) - 5} aprovacoes"

            dialog = MDDialog(
                title="APROVACOES PENDENTES",
                text=message,
                buttons=[
                    MDFlatButton(
                        text="VER DETALHES",
                        on_release=lambda x: self.show_approval_details(pending)
                    ),
                    MDFlatButton(
                        text="FECHAR",
                        on_release=lambda x: dialog.dismiss()
                    )
                ]
            )
            dialog.open()

        self._run_async_action(
            "pending-approvals",
            task,
            on_success=on_success,
            busy_message="A carregar aprovacoes pendentes...",
            error_message="Erro ao carregar aprovacoes",
        )

    def show_approval_details(self, pending_list):
        """Mostrar detalhes das aprovacoes com opcao de aprovar/rejeitar"""
        try:
            from kivymd.uix.boxlayout import MDBoxLayout
            from kivymd.uix.label import MDLabel
            from kivymd.uix.button import MDRaisedButton
            from kivy.uix.scrollview import ScrollView
            from kivy.metrics import dp
            from kivy.app import App

            app = App.get_running_app()
            current_user = getattr(app, "current_user", None)

            content = MDBoxLayout(
                orientation='vertical',
                padding=dp(20),
                spacing=dp(15),
                size_hint_y=None
            )
            content.bind(minimum_height=content.setter('height'))

            for row in pending_list:
                mov_id, prod_id, description, mov_type, qty, unit, cost, price, reason, note, evidence, created_at, user, role = row

                card = MDBoxLayout(
                    orientation='vertical',
                    padding=dp(10),
                    spacing=dp(5),
                    size_hint_y=None,
                    height=dp(200),
                    md_bg_color=[0.95, 0.95, 0.95, 1]
                )

                info_text = f"""ID: {mov_id} | Tipo: {mov_type}
    Produto: {description}
    Quantidade: {qty} {unit} | Custo: {cost:.2f} MZN
    Registado por: {user} ({role})
    Data: {created_at}
    Motivo: {reason}
    {f'Obs: {note}' if note else ''}
    {'Com evidencia fotografica' if evidence else 'Sem evidencia'}"""

                info_label = MDLabel(
                    text=info_text,
                    size_hint_y=None,
                    halign='left',
                    font_size=dp(12)
                )
                info_label.bind(texture_size=info_label.setter('size'))
                card.add_widget(info_label)

                buttons = MDBoxLayout(
                    size_hint_y=None,
                    height=dp(40),
                    spacing=dp(10)
                )

                approve_btn = MDRaisedButton(
                    text="APROVAR",
                    md_bg_color=[0.2, 0.7, 0.3, 1],
                    on_release=lambda x, mid=mov_id: self.approve_loss(mid, current_user)
                )

                reject_btn = MDRaisedButton(
                    text="REJEITAR",
                    md_bg_color=[0.9, 0.3, 0.3, 1],
                    on_release=lambda x, mid=mov_id: self.reject_loss(mid)
                )

                buttons.add_widget(approve_btn)
                buttons.add_widget(reject_btn)
                card.add_widget(buttons)

                content.add_widget(card)

            scroll = ScrollView(size_hint=(1, 1))
            scroll.add_widget(content)

            dialog = MDDialog(
                title="DETALHES DAS APROVACOES",
                type='custom',
                content_cls=scroll,
                size_hint=(0.95, 0.9),
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

    def approve_loss(self, movement_id, approved_by):
        """Aprovar perda"""
        try:
            success = self.db.approve_stock_movement(movement_id, approved_by)

            if success:
                self.show_snackbar(f"Perda #{movement_id} aprovada")
                self.db.log_action(approved_by, "admin", "APPROVE_LOSS", f"Aprovada perda ID {movement_id}")
                self.show_pending_approvals()
            else:
                self.show_snackbar("Erro ao aprovar perda")
        except Exception as e:
            print(f"Erro ao aprovar: {e}")
            self.show_snackbar("Erro ao aprovar")

    def reject_loss(self, movement_id):
        """Rejeitar perda (marcar como rejeitada)"""
        try:
            # Implementar lógica de rejeição
            # Por enquanto, apenas mostrar mensagem
            self.show_snackbar(f"Perda #{movement_id} marcada para rejeição")
            # TODO: Adicionar status REJECTED ao banco
        except Exception as e:
            print(f"Erro ao rejeitar: {e}")


    # ==================== 3. MODIFICAR O METODO on_enter ====================

    # Modificar o método on_enter existente para adicionar verificação de alertas:

    def on_enter(self):
        """Ao entrar na tela - VERSAO MODIFICADA"""
        self._bind_keyboard_shortcuts()
        stale = (time.perf_counter() - self._last_products_load_at) >= self.PRODUCTS_CACHE_SECONDS
        if (not self.products) or stale:
            self.load_products()
        Clock.schedule_once(self._init_badge, 0.1)
        Clock.schedule_once(lambda dt: self._start_ai_polling(), 0.15)
        
        # NOVO: Verificar alertas de fraude
        Clock.schedule_once(self.check_fraud_alerts_on_enter, 0.3)

    def on_leave(self):
        self._unbind_keyboard_shortcuts()
        self._stop_ai_polling()
        self._clear_loading_overlay()
        self._dismiss_lot_menu()
        self._alerts_refresh_token += 1
        self._ai_popup_token += 1
        for attr_name in ("_lot_selector_dialog", "_shopping_list_dialog", "_loss_metrics_dialog", "_loss_details_dialog", "_shortcut_help_dialog"):
            dialog = getattr(self, attr_name, None)
            if dialog is not None:
                try:
                    dialog.dismiss()
                except Exception:
                    pass
                setattr(self, attr_name, None)
        self._shopping_list_payload = None


    def check_fraud_alerts_on_enter(self, dt):
        """Verificar alertas de fraude ao entrar"""
        now = time.time()
        if now < self._fraud_check_until:
            return

        self._fraud_check_until = now + 120
        token = self._fraud_check_token + 1
        self._fraud_check_token = token

        def worker():
            try:
                alerts = self.db.detect_fraud_patterns(days_lookback=7) or []
                high_count = sum(1 for alert in alerts if alert.get("severity") == 3)
            except Exception as exc:
                print(f"Erro ao verificar alertas: {exc}")
                high_count = 0
            Clock.schedule_once(
                lambda _dt, count=high_count, tok=token: self._apply_fraud_check_result(count, tok),
                0
            )

        Thread(target=worker, daemon=True).start()

    def _apply_fraud_check_result(self, high_count, token):
        if token != self._fraud_check_token:
            return
        if high_count > 0:
            if high_count != self._last_fraud_log_count:
                app = App.get_running_app()
                actor = getattr(app, "current_user", None) or "sistema"
                role = getattr(app, "current_role", None) or "admin"
                try:
                    self.db.log_action(
                        actor,
                        role,
                        "FRAUD_ALERT",
                        f"{high_count} alerta(s) critico(s) de fraude detetado(s) automaticamente",
                    )
                except Exception:
                    pass
            self._last_fraud_log_count = high_count
            print(f"Alertas criticos detectados: {high_count}")
            return
        self._last_fraud_log_count = 0

    def show_fraud_notification_popup(self, alert_count):
        """Popup de notificacao de alertas criticos"""
        from kivymd.uix.dialog import MDDialog
        from kivymd.uix.button import MDFlatButton, MDRaisedButton

        dialog = MDDialog(
            title="ALERTAS CRITICOS",
            text=f"Detectados {alert_count} alertas de seguranca de alta prioridade!\n\nRecomenda-se revisao imediata.",
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


   

