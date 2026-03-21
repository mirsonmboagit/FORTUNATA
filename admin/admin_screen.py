from kivy.uix.screenmanager import Screen
import os
import sys
from kivy.properties import ObjectProperty, ListProperty, BooleanProperty
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.app import App
from kivy.graphics import Color, Line
from kivy.animation import Animation
from collections import deque
from threading import Thread
import time
from datetime import datetime, timedelta
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton, MDRaisedButton, MDIconButton
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
from utils.ai_insights import build_admin_insights, build_admin_insights_ai
from utils.ai_popups import (
    build_auto_banner_data,
    build_banner_details_sections,
    build_positive_banner,
    render_auto_banners,
)
from utils.expiry_alerts import evaluate_expiry_alert, get_expiry_level_counts


def _get_detail_popup_class():
    try:
        from .detail_popup import DetailPopup
    except ImportError:
        from admin.detail_popup import DetailPopup
    return DetailPopup


def _get_product_form_class():
    try:
        from .product_form import ProductForm
    except ImportError:
        from admin.product_form import ProductForm
    return ProductForm


Builder.load_file(os.path.join(CURRENT_DIR, 'admin_screen.kv'))


# ---------------------------------------------------------------------------
# Column proportions - ajustadas para melhor distribuicao
# ---------------------------------------------------------------------------
COL_HINTS = [0.06, 0.20, 0.09, 0.09, 0.07, 0.11, 0.11, 0.13, 0.14]


class AdminScreen(Screen):
    PRODUCTS_CACHE_SECONDS = 4
    product_table = ObjectProperty(None)
    search_input = ObjectProperty(None)
    category_spinner = ObjectProperty(None)
    products = ListProperty([])
    quick_actions_open = BooleanProperty(False)

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
        self._alerts_refresh_token = 0
        self._ai_popup_token = 0
        self._fraud_check_token = 0
        self._fraud_check_until = 0.0
        self._cached_admin_insights = {}
        self._expiry_alerts_by_id = {}
        self._last_expiry_summary_at = 0.0
        self._expiry_summary_cooldown = 120.0
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
        Clock.schedule_once(lambda dt: self._update_responsive_layout(), 0)

    def toggle_quick_actions(self, *args):
        self.quick_actions_open = not self.quick_actions_open

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def _on_window_resize(self, instance, width, height):
        """Rebuild table rows so every cell re-measures at the new size."""
        self._update_responsive_layout(width)
        Clock.unschedule(self._deferred_rebuild)
        Clock.schedule_once(self._deferred_rebuild, 0.15)

    def _deferred_rebuild(self, dt):
        if hasattr(self, '_current_display'):
            self.update_product_table(self._current_display)
        else:
            self.update_product_table(self.products)

    def _update_responsive_layout(self, width=None):
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

            toolbar_card.height = toolbar_row.minimum_height + dp(16)
        else:
            toolbar_row.orientation = "horizontal"
            toolbar_row.spacing = dp(10)
            toolbar_card.padding = [dp(16), dp(10)]

            if search_input:
                search_input.size_hint_x = 0.33
            if category_spinner:
                category_spinner.size_hint_x = 0.20
            if filter_btn:
                filter_btn.size_hint_x = None
                filter_btn.width = dp(48)
            if add_btn:
                add_btn.size_hint_x = 0.14

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
            
            # Usar pos_hint para criar efeito de balanço (movimento lateral e vertical)
            original_pos = {"right": 0.965, "y": 0.04}
            
            # Sequência de balanço simulando oscilação
            swing = (
                # Balanço para direita-cima
                Animation(pos_hint={"right": 0.970, "y": 0.045}, duration=0.15, transition='out_sine') +
                # Balanço para esquerda-baixo
                Animation(pos_hint={"right": 0.960, "y": 0.035}, duration=0.3, transition='in_out_sine') +
                # Balanço direita-meio
                Animation(pos_hint={"right": 0.968, "y": 0.042}, duration=0.25, transition='in_out_sine') +
                # Balanço esquerda-meio
                Animation(pos_hint={"right": 0.962, "y": 0.038}, duration=0.25, transition='in_out_sine') +
                # Balanço direita-pequeno
                Animation(pos_hint={"right": 0.967, "y": 0.041}, duration=0.2, transition='in_out_sine') +
                # Balanço esquerda-pequeno
                Animation(pos_hint={"right": 0.963, "y": 0.039}, duration=0.2, transition='in_out_sine') +
                # Volta ao centro
                Animation(pos_hint=original_pos, duration=0.15, transition='out_sine')
            )
            swing.start(self.ids.ai_button)
            return True
        
        # Executar balanço a cada 2.5 segundos
        self.swing_event = Clock.schedule_interval(swing_cycle, 2.5)
        swing_cycle(0)  # Executar imediatamente
    
    def _stop_swing_animation(self):
        """Para a animação de abanar"""
        if hasattr(self, 'swing_event') and self.swing_event:
            self.swing_event.cancel()
            self.swing_event = None
        
        if hasattr(self.ids, 'ai_button'):
            Animation.cancel_all(self.ids.ai_button)
            
            # Retornar à posição original
            anim = Animation(
                pos_hint={"right": 0.965, "y": 0.04},
                duration=0.2,
                transition='out_sine'
            )
            anim.start(self.ids.ai_button)

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
            get_db().log_action(app.current_user, app.current_role or "admin", "LOGOUT", "Logout admin")
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

    # ------------------------------------------------------------------
    # Search / filter
    # ------------------------------------------------------------------
    def filter_products(self, search_text):
        category_text = self.category_spinner.text if self.category_spinner else "Todas as Categorias"
        category = category_text if category_text != "Todas as Categorias" else "Todas"
        search_value = (search_text or "").strip().lower()
        filtered = []

        for product in self.products:
            search_match = (
                search_value in str(product[0]).lower() or
                (len(product) > 1 and search_value in str(product[1]).lower()) or
                (len(product) > 11 and search_value in str(product[11]).lower()) or
                (len(product) > 12 and product[12] and search_value in str(product[12]).lower())
            )
            category_match = (
                category in ('Todas', 'Todas as Categorias') or
                (len(product) > 11 and category == product[11])
            )
            if search_match and category_match:
                filtered.append(product)

        self.update_product_table(filtered)

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
        self._last_products_load_at = time.perf_counter()
        self.products = list(rows or [])
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
    def update_product_table(self, products_to_display=None):
        """Atualizar a tabela de produtos com separadores visuais pretos."""
        if not self.product_table:
            return

        if self._table_render_ev:
            Clock.unschedule(self._table_render_ev)
            self._table_render_ev = None

        self._table_render_token += 1
        token = self._table_render_token

        if products_to_display is None:
            products_to_display = self.products
        display_rows = list(products_to_display or [])
        self._current_display = display_rows
        self.product_table.clear_widgets()

        if not display_rows:
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
        self._pending_table_rows = deque(enumerate(display_rows))
        self._table_render_ev = Clock.schedule_interval(
            lambda dt, tok=token: self._render_table_batch(dt, tok),
            0
        )
        return


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

        is_sold_by_weight = product[15] if len(product) > 15 else 0
        unit_label = "KG" if is_sold_by_weight else ""

        cell = self._make_product_cell(0, row_h, row_bg_color, border_color)
        cell.add_widget(MDLabel(
            text=str(product[0]),
            theme_text_color="Custom",
            text_color=text_primary,
            halign='center',
            bold=True,
            font_style="Body1"
        ))
        self.product_table.add_widget(cell)

        cell = self._make_product_cell(1, row_h, row_bg_color, border_color, align='left')
        cell.add_widget(MDLabel(
            text=product[1],
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
        action_layout.add_widget(self.create_detail_button(product[0], tokens=action_tokens))
        action_layout.add_widget(self.create_edit_button(product, tokens=action_tokens))
        action_layout.add_widget(self.create_delete_button(product[0], tokens=action_tokens))
        cell.add_widget(action_layout)
        self.product_table.add_widget(cell)

    # ------------------------------------------------------------------
    # Action buttons com Material Design
    # ------------------------------------------------------------------
    def create_detail_button(self, product_id, tokens=None):
        tokens = tokens or self._theme_tokens()
        btn = MDIconButton(
            icon="information",
            theme_text_color="Custom",
            text_color=tokens.get("info", [0.1, 0.3, 0.9, 1]),
            md_bg_color=tokens.get("card_alt", [0.92, 0.95, 1, 1]),
            icon_size=sp(20)
        )
        btn.product_id = product_id
        btn.bind(on_release=self.show_product_details)
        return btn

    def create_edit_button(self, product, tokens=None):
        tokens = tokens or self._theme_tokens()
        btn = MDIconButton(
            icon="pencil",
            theme_text_color="Custom",
            text_color=tokens.get("success", [0.1, 0.65, 0.2, 1]),
            md_bg_color=tokens.get("card_alt", [0.92, 1, 0.92, 1]),
            icon_size=sp(20)
        )
        btn.product_id = product
        btn.bind(on_release=self.edit_product)
        return btn

    def create_delete_button(self, product_id, tokens=None):
        tokens = tokens or self._theme_tokens()
        btn = MDIconButton(
            icon="delete",
            theme_text_color="Custom",
            text_color=tokens.get("danger", [0.9, 0.2, 0.2, 1]),
            md_bg_color=tokens.get("card_alt", [1, 0.92, 0.92, 1]),
            icon_size=sp(20)
        )
        btn.product_id = product_id
        btn.bind(on_release=self.delete_product)
        return btn

    # ------------------------------------------------------------------
    # Product actions
    # ------------------------------------------------------------------
    def show_product_details(self, instance):
        product = self.db.get_product(instance.product_id)
        if product:
            _get_detail_popup_class()(product).open()

    def add_product(self):
        _get_product_form_class()(self).open()

    def edit_product(self, instance):
        _get_product_form_class()(self, instance.product_id).open()

    def delete_product(self, instance):
        product_id = instance.product_id
        
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
                    on_release=lambda x: self.confirm_delete(product_id)
                ),
            ],
        )
        self.dialog.open()

    def confirm_delete(self, product_id):
        app = App.get_running_app()
        username = getattr(app, "current_user", None)
        ok = self.db.delete_product(product_id, username=username)
        self.dialog.dismiss()
        if ok:
            if username:
                self.db.log_action(username, app.current_role or "admin", "DELETE_PRODUCT", f"Produto eliminado ID {product_id}")
            self.load_products()
            self.show_snackbar("Produto eliminado com sucesso!")
        else:
            self.show_snackbar("Erro ao eliminar produto!")

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
        render_auto_banners(
            self.ids.ai_banner_container,
            banners,
            insights=insights,
            auto_dismiss_seconds=None,
            show_timer=False,
        )
        self.mark_notifications_seen(insights)

    def show_ai_insights(self, *args):
        self._intelligence.open_history()

    def open_ai_menu(self, caller):
        self._intelligence.open_history()

    def _open_ai_from_menu(self, key):
        if hasattr(self, "_ai_menu") and self._ai_menu:
            self._ai_menu.dismiss()
        self._intelligence.open_history()

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
        if not hasattr(self, 'filter_mode'):
            self.filter_mode = 0

        self.filter_mode = (self.filter_mode + 1) % 3

        if self.filter_mode == 1:
            kg_products = self.db.get_products_by_weight()
            if kg_products:
                self.update_product_table(kg_products)
                self.show_snackbar("Mostrando apenas produtos vendidos por KG")
            else:
                self.filter_mode = 2
                unit_products = [p for p in self.products if not (len(p) > 15 and p[15])]
                if unit_products:
                    self.update_product_table(unit_products)
                    self.show_snackbar("Mostrando apenas produtos vendidos por unidade")
                else:
                    self.filter_mode = 0
                    self.update_product_table(self.products)
                    self.show_snackbar("Mostrando todos os produtos")
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
        """Mostrar metricas de perdas do ultimo mes"""
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=30)
            metrics = self.db.calculate_loss_metrics(start_date, end_date)

            if not metrics:
                self.show_snackbar("Erro ao calcular perdas")
                return

            message = f"""PERDAS - ULTIMOS 30 DIAS

    RESUMO:
    - Eventos: {metrics['loss_count']} perdas
    - Custo Total: {metrics['total_cost']:.2f} MZN
    - Receita Perdida: {metrics['total_revenue_lost']:.2f} MZN
    - Lucro Perdido: {metrics['total_profit_lost']:.2f} MZN

    PERFORMANCE:
    - Total Vendas: {metrics['total_sales']:.2f} MZN
    - % Perdas vs Vendas: {metrics['loss_percentage']:.2f}%
    - Media por Perda: {metrics['avg_loss_value']:.2f} MZN

    POR TIPO:"""

            for loss_type, data in metrics['by_type'].items():
                message += f"\n- {loss_type}: {data['total_cost']:.2f} MZN ({data['count']}x)"

            dialog = MDDialog(
                title="METRICAS DE PERDAS",
                text=message,
                buttons=[
                    MDFlatButton(
                        text="VER DETALHES",
                        on_release=lambda x: self.show_detailed_loss_report()
                    ),
                    MDFlatButton(
                        text="FECHAR",
                        on_release=lambda x: dialog.dismiss()
                    )
                ]
            )
            dialog.open()

        except Exception as e:
            print(f"Erro ao mostrar metricas: {e}")
            self.show_snackbar("Erro ao carregar metricas")

    def show_detailed_loss_report(self, *args):
        """Mostrar relatorio detalhado de perdas"""
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=30)

            metrics = self.db.calculate_loss_metrics(start_date, end_date)
            if not metrics:
                return

            from kivymd.uix.boxlayout import MDBoxLayout
            from kivymd.uix.label import MDLabel
            from kivy.uix.scrollview import ScrollView
            from kivy.metrics import dp

            content = MDBoxLayout(
                orientation='vertical',
                padding=dp(20),
                spacing=dp(15),
                size_hint_y=None
            )
            content.bind(minimum_height=content.setter('height'))

            header = MDLabel(
                text=f"RELATORIO DE PERDAS\n{start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}",
                font_style="H6",
                halign='center',
                size_hint_y=None,
                height=dp(60)
            )
            content.add_widget(header)

            summary_text = f"""RESUMO GERAL:
    Eventos: {metrics['loss_count']}
    Custo Total: {metrics['total_cost']:.2f} MZN
    Receita Perdida: {metrics['total_revenue_lost']:.2f} MZN
    % vs Vendas: {metrics['loss_percentage']:.2f}%

    POR TIPO:"""

            for loss_type, data in metrics['by_type'].items():
                summary_text += f"\n{loss_type}: {data['total_cost']:.2f} MZN ({data['count']}x)"

            summary_text += "\n\nPOR UTILIZADOR:"
            for user_data in metrics['by_user'][:5]:
                username, role, count, cost, revenue, avg = user_data
                summary_text += f"\n{username}: {cost:.2f} MZN ({count}x)"

            summary_text += "\n\nTOP 5 PRODUTOS:"
            for prod_data in metrics['by_product'][:5]:
                product_id, description, count, cost = prod_data
                summary_text += f"\n{description}: {cost:.2f} MZN ({count}x)"

            summary_label = MDLabel(
                text=summary_text,
                size_hint_y=None,
                halign='left'
            )
            summary_label.bind(texture_size=summary_label.setter('size'))
            content.add_widget(summary_label)

            scroll = ScrollView(size_hint=(1, 1))
            scroll.add_widget(content)

            dialog = MDDialog(
                title="",
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
            print(f"Erro ao mostrar relatorio: {e}")

    def show_fraud_alerts(self, *args):
        """Mostrar alertas de fraude"""
        try:
            alerts = self.db.detect_fraud_patterns(days_lookback=30)

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

        except Exception as e:
            print(f"Erro ao mostrar alertas: {e}")

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
        try:
            pending = self.db.get_pending_approvals()

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

        except Exception as e:
            print(f"Erro: {e}")

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
        stale = (time.perf_counter() - self._last_products_load_at) >= self.PRODUCTS_CACHE_SECONDS
        if (not self.products) or stale:
            self.load_products()
        Clock.schedule_once(self._init_badge, 0.1)
        Clock.schedule_once(lambda dt: self._start_ai_polling(), 0.15)
        
        # NOVO: Verificar alertas de fraude
        Clock.schedule_once(self.check_fraud_alerts_on_enter, 0.3)

    def on_leave(self):
        self._stop_ai_polling()
        self._alerts_refresh_token += 1
        self._ai_popup_token += 1


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
            print(f"Alertas criticos detectados: {high_count}")

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


   

