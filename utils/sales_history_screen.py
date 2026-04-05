from collections import deque
from kivymd.uix.dialog import MDDialog
from datetime import datetime, timedelta
from functools import lru_cache
from threading import Thread
from time import perf_counter

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle  # ← MOVIDO PARA O TOPO (era importado dentro do loop)
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import BooleanProperty
from kivy.uix.widget import Widget
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton, MDFlatButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField

from database.provider import get_db


Builder.load_string("""
<SalesHistoryScreen>:
    name: "sales_history"
    md_bg_color: app.theme_tokens['surface']

    MDBoxLayout:
        orientation: "vertical"

        # Header com gradiente
        MDTopAppBar:
            title: "Histórico de Vendas"
            md_bg_color: app.theme_tokens['primary']
            specific_text_color: app.theme_tokens['on_primary']
            elevation: 4
            left_action_items: [["arrow-left", lambda x: root.go_back()]]
            right_action_items: [["file-download-outline", lambda x: root.export_sales()], ["refresh", lambda x: root.load_all_sales(force_refresh=True)]]

        # Main Content
        MDBoxLayout:
            orientation: "vertical"
            padding: dp(16)
            spacing: dp(16)

            # Filter Card com separadores
            MDCard:
                id: filters_card
                orientation: "vertical"
                size_hint_y: None
                height: dp(180)
                padding: dp(0)
                spacing: dp(0)
                elevation: 3
                radius: [dp(16)]
                md_bg_color: app.theme_tokens['card']

                # Header do Card
                MDBoxLayout:
                    size_hint_y: None
                    height: dp(50)
                    padding: [dp(20), dp(12)]
                    md_bg_color: app.theme_tokens['card_alt']
                    radius: [dp(16), dp(16), 0, 0]

                    MDIcon:
                        icon: "filter-variant"
                        size_hint_x: None
                        width: dp(28)
                        theme_text_color: "Custom"
                        text_color: app.theme_tokens['primary']

                    MDLabel:
                        text: "Filtros de Pesquisa"
                        font_style: "H6"
                        bold: True
                        theme_text_color: "Primary"

                # Divider customizado
                Widget:
                    size_hint_y: None
                    height: dp(1)
                    canvas.before:
                        Color:
                            rgba: app.theme_tokens['divider']
                        Rectangle:
                            pos: self.pos
                            size: self.size

                # Conteúdo dos filtros
                MDBoxLayout:
                    id: filters_content
                    orientation: "vertical"
                    padding: dp(20)
                    spacing: dp(14)

                    # Date Range Filters
                    MDBoxLayout:
                        id: date_filters_row
                        size_hint_y: None
                        height: dp(56)
                        spacing: dp(12)

                        MDTextField:
                            id: start_date
                            hint_text: "Data Início"
                            helper_text: "Formato: dd/mm/aaaa"
                            helper_text_mode: "on_focus"
                            mode: "rectangle"
                            size_hint_x: 0.38
                            icon_right: "calendar"
                            max_text_length: 10
                            line_color_focus: app.theme_tokens['primary']
                            on_text_validate: root.apply_date_filter()

                        MDTextField:
                            id: end_date
                            hint_text: "Data Fim"
                            helper_text: "Formato: dd/mm/aaaa"
                            helper_text_mode: "on_focus"
                            mode: "rectangle"
                            size_hint_x: 0.38
                            icon_right: "calendar"
                            max_text_length: 10
                            line_color_focus: app.theme_tokens['primary']
                            on_text_validate: root.apply_date_filter()

                        MDRaisedButton:
                            id: apply_filter_btn
                            text: "APLICAR"
                            size_hint_x: 0.24
                            md_bg_color: app.theme_tokens['primary']
                            elevation: 2
                            on_release: root.apply_date_filter()

                    # Quick Filter Buttons
                    MDGridLayout:
                        id: quick_filters_grid
                        cols: 6
                        adaptive_height: True
                        size_hint_y: None
                        spacing: dp(10)

                        MDRaisedButton:
                            text: "HOJE"
                            size_hint_x: 0.16
                            md_bg_color: app.theme_tokens['success']
                            elevation: 2
                            on_release: root.filter_today()

                        MDRaisedButton:
                            text: "SEMANA"
                            size_hint_x: 0.16
                            md_bg_color: app.theme_tokens['info']
                            elevation: 2
                            on_release: root.filter_this_week()

                        MDRaisedButton:
                            text: "MÊS"
                            size_hint_x: 0.16
                            md_bg_color: app.theme_tokens['info']
                            elevation: 2
                            on_release: root.filter_this_month()

                        MDRaisedButton:
                            text: "ANO"
                            size_hint_x: 0.16
                            md_bg_color: app.theme_tokens['info']
                            elevation: 2
                            on_release: root.filter_this_year()

                        MDRaisedButton:
                            text: "PROMO"
                            size_hint_x: 0.16
                            md_bg_color: app.theme_tokens['warning']
                            elevation: 2
                            on_release: root.filter_promotional_sales()

                        MDFlatButton:
                            text: "LIMPAR"
                            size_hint_x: 0.16
                            theme_text_color: "Custom"
                            text_color: app.theme_tokens['danger']
                            on_release: root.clear_filters()

            # Summary Card com separadores verticais
            MDCard:
                orientation: "horizontal"
                size_hint_y: None
                height: dp(100)
                padding: dp(0)
                spacing: dp(0)
                elevation: 3
                radius: [dp(16)]
                md_bg_color: app.theme_tokens['card']

                # Total Sales
                MDBoxLayout:
                    orientation: "vertical"
                    size_hint_x: 0.33
                    padding: dp(20)
                    spacing: dp(8)

                    MDBoxLayout:
                        size_hint_y: None
                        height: dp(24)
                        spacing: dp(8)

                        MDIcon:
                            icon: "cart-outline"
                            size_hint_x: None
                            width: dp(20)
                            theme_text_color: "Custom"
                            text_color: app.theme_tokens['primary']

                        MDLabel:
                            text: "Total de Vendas"
                            font_style: "Caption"
                            theme_text_color: "Secondary"

                    MDLabel:
                        id: total_sales_label
                        text: "0"
                        font_style: "H4"
                        theme_text_color: "Primary"
                        bold: True

                # Separador vertical
                Widget:
                    size_hint_x: None
                    width: dp(1)
                    canvas.before:
                        Color:
                            rgba: app.theme_tokens['divider']
                        Rectangle:
                            pos: self.pos
                            size: self.size

                # Total Revenue
                MDBoxLayout:
                    orientation: "vertical"
                    size_hint_x: 0.33
                    padding: dp(20)
                    spacing: dp(8)

                    MDBoxLayout:
                        size_hint_y: None
                        height: dp(24)
                        spacing: dp(8)

                        MDIcon:
                            icon: "cash-multiple"
                            size_hint_x: None
                            width: dp(20)
                            theme_text_color: "Custom"
                            text_color: app.theme_tokens['success']

                        MDLabel:
                            text: "Receita Total"
                            font_style: "Caption"
                            theme_text_color: "Secondary"

                    MDLabel:
                        id: total_revenue_label
                        text: "0.00 MT"
                        font_style: "H4"
                        theme_text_color: "Custom"
                        text_color: app.theme_tokens['success']
                        bold: True

                # Separador vertical
                Widget:
                    size_hint_x: None
                    width: dp(1)
                    canvas.before:
                        Color:
                            rgba: app.theme_tokens['divider']
                        Rectangle:
                            pos: self.pos
                            size: self.size

                # Average Sale
                MDBoxLayout:
                    orientation: "vertical"
                    size_hint_x: 0.34
                    padding: dp(20)
                    spacing: dp(8)

                    MDBoxLayout:
                        size_hint_y: None
                        height: dp(24)
                        spacing: dp(8)

                        MDIcon:
                            icon: "chart-line"
                            size_hint_x: None
                            width: dp(20)
                            theme_text_color: "Custom"
                            text_color: app.theme_tokens['info']

                        MDLabel:
                            text: "Estornos"
                            font_style: "Caption"
                            theme_text_color: "Secondary"

                    MDLabel:
                        id: avg_sale_label
                        text: "0.00 MT"
                        font_style: "H4"
                        theme_text_color: "Custom"
                        text_color: app.theme_tokens['info']
                        bold: True

            # Sales Table Card
            MDCard:
                orientation: "vertical"
                padding: dp(0)
                spacing: dp(0)
                elevation: 3
                radius: [dp(16)]
                md_bg_color: app.theme_tokens['card']

                # Table Header
                MDBoxLayout:
                    size_hint_y: None
                    height: dp(56)
                    padding: [dp(20), dp(0)]
                    spacing: dp(0)
                    md_bg_color: app.theme_tokens['primary']
                    radius: [dp(16), dp(16), 0, 0]

                    MDLabel:
                        id: header_date
                        text: "Data/Hora"
                        bold: True
                        theme_text_color: "Custom"
                        text_color: app.theme_tokens['on_primary']
                        size_hint_x: 0.22
                        halign: "left"
                        font_size: dp(13)

                    # Separador vertical
                    Widget:
                        id: header_sep_date_product
                        size_hint_x: None
                        width: dp(1)
                        canvas.before:
                            Color:
                                rgba: app.theme_tokens['divider']
                            Rectangle:
                                pos: self.pos
                                size: self.size

                    MDLabel:
                        id: header_product
                        text: "Produto"
                        bold: True
                        theme_text_color: "Custom"
                        text_color: app.theme_tokens['on_primary']
                        size_hint_x: 0.36
                        halign: "left"
                        padding: [dp(12), 0]
                        font_size: dp(13)

                    # Separador vertical
                    Widget:
                        id: header_sep_product_qty
                        size_hint_x: None
                        width: dp(1)
                        canvas.before:
                            Color:
                                rgba: app.theme_tokens['divider']
                            Rectangle:
                                pos: self.pos
                                size: self.size

                    MDLabel:
                        id: header_qty
                        text: "Qtd"
                        bold: True
                        theme_text_color: "Custom"
                        text_color: app.theme_tokens['on_primary']
                        size_hint_x: 0.12
                        halign: "center"
                        font_size: dp(13)

                    # Separador vertical
                    Widget:
                        id: header_sep_qty_price
                        size_hint_x: None
                        width: dp(1)
                        canvas.before:
                            Color:
                                rgba: app.theme_tokens['divider']
                            Rectangle:
                                pos: self.pos
                                size: self.size

                    MDLabel:
                        id: header_price
                        text: "Preço Un."
                        bold: True
                        theme_text_color: "Custom"
                        text_color: app.theme_tokens['on_primary']
                        size_hint_x: 0.15
                        halign: "right"
                        padding: [0, 0, dp(8), 0]
                        font_size: dp(13)

                    # Separador vertical
                    Widget:
                        id: header_sep_price_total
                        size_hint_x: None
                        width: dp(1)
                        canvas.before:
                            Color:
                                rgba: app.theme_tokens['divider']
                            Rectangle:
                                pos: self.pos
                                size: self.size

                    MDLabel:
                        id: header_total
                        text: "Total"
                        bold: True
                        theme_text_color: "Custom"
                        text_color: app.theme_tokens['on_primary']
                        size_hint_x: 0.15
                        halign: "right"
                        padding: [0, 0, dp(12), 0]
                        font_size: dp(13)

                    Widget:
                        id: header_sep_total_action
                        size_hint_x: None
                        width: dp(1)
                        canvas.before:
                            Color:
                                rgba: app.theme_tokens['divider']
                            Rectangle:
                                pos: self.pos
                                size: self.size

                    MDLabel:
                        id: header_action
                        text: "Ação"
                        bold: True
                        theme_text_color: "Custom"
                        text_color: app.theme_tokens['on_primary']
                        size_hint_x: 0.10
                        halign: "center"
                        font_size: dp(13)

                # Divider após header
                Widget:
                    size_hint_y: None
                    height: dp(2)
                    canvas.before:
                        Color:
                            rgba: app.theme_tokens['card_alt']
                        Rectangle:
                            pos: self.pos
                            size: self.size

                # Table Content
                ScrollView:
                    do_scroll_x: False
                    size_hint_y: 1
                    bar_width: dp(10)
                    bar_color: 0.09, 0.38, 0.73, 0.6
                    bar_inactive_color: 0.9, 0.9, 0.92, 1

                    MDBoxLayout:
                        id: sales_list
                        orientation: "vertical"
                        spacing: dp(0)
                        padding: dp(0)
                        size_hint_y: None
                        height: self.minimum_height

                # Empty State
                MDBoxLayout:
                    id: empty_state
                    orientation: "vertical"
                    padding: dp(40)
                    spacing: dp(20)
                    size_hint_y: None
                    height: 0
                    opacity: 0
                    disabled: True

                    MDIcon:
                        id: empty_state_icon
                        icon: "basket-off-outline"
                        font_size: dp(80)
                        halign: "center"
                        theme_text_color: "Custom"
                        text_color: app.theme_tokens['text_secondary']

                    MDLabel:
                        id: empty_state_title
                        text: "Nenhuma venda encontrada"
                        halign: "center"
                        theme_text_color: "Hint"
                        font_style: "H5"
                        bold: True

                    MDLabel:
                        id: empty_state_message
                        text: "Ajuste os filtros ou adicione novas vendas ao sistema"
                        halign: "center"
                        theme_text_color: "Hint"
                        font_style: "Body1"

                MDRaisedButton:
                    id: load_more_btn
                    text: "CARREGAR MAIS"
                    size_hint_y: None
                    height: dp(44)
                    md_bg_color: app.theme_tokens['primary']
                    on_release: root.load_more_rows()
                    opacity: 0
                    disabled: True

""")


class SalesHistoryScreen(MDScreen):
    ENTER_CACHE_SECONDS = 5
    RENDER_BATCH_SIZE = 20          # ← AUMENTADO de 8 para 20 (widgets mais leves agora suportam)
    RENDER_INTERVAL_SECONDS = 0.016 # ← AJUSTADO de 0.01 para ~60fps sem acumular frames
    compact_mode = BooleanProperty(False)

    # ─── Cache de cores para evitar lookup de tokens por linha ───────────────
    _divider_color_cache = [0, 0, 0, 0.12]
    _bg_even_cache = [0.98, 0.99, 1, 1]
    _bg_odd_cache = [1, 1, 1, 1]
    _text_primary_cache = [0.15, 0.20, 0.30, 1]
    _text_secondary_cache = [0.35, 0.40, 0.50, 1]
    _primary_cache = [0.10, 0.35, 0.65, 1]
    _success_cache = [0.20, 0.65, 0.30, 1]
    _warning_cache = [0.95, 0.62, 0.12, 1]
    _on_primary_cache = [1, 1, 1, 1]
    _card_alt_cache = [0.65, 0.65, 0.65, 1]

    def __init__(self, db=None, **kwargs):
        self._last_rows = []
        self._render_ev = None
        self._pending_rows = deque()
        self._render_index = 0
        self._display_rows = []
        self._page_size = 60
        self._current_page = 1
        self._last_loaded_at = 0.0
        self._rows_loading = False
        self._rows_token = 0
        self._all_sales_cache = []
        self._all_sales_summary = None
        self._all_sales_cache_valid = False
        self._all_sales_cache_at = 0.0
        self.sales_history_report = None
        self.pdf_viewer = None
        self._exporting_sales = False
        self._pending_enter_filter = None
        self.back_target = "admin_home"
        super().__init__(**kwargs)
        self.db = db or get_db()
        self.current_filter = None

    def on_kv_post(self, base_widget):
        self._update_responsive_layout()

    def on_pre_enter(self, *args):
        pending_filter = (self._pending_enter_filter or "").strip().lower()
        self._pending_enter_filter = None
        if pending_filter == "today":
            Clock.schedule_once(lambda dt: self.filter_today(), 0.05)
            return
        self.request_enter_refresh()

    def queue_enter_filter(self, filter_name):
        self._pending_enter_filter = str(filter_name or "").strip().lower() or None

    def request_enter_refresh(self, force=False, delay=0.05):
        stale = (perf_counter() - self._last_loaded_at) >= self.ENTER_CACHE_SECONDS
        if not force and self._last_rows and not stale:
            return
        Clock.schedule_once(lambda dt: self.load_all_sales(), delay)

    def _update_load_more_button(self, visible):
        if "load_more_btn" not in self.ids:
            return
        self.ids.load_more_btn.opacity = 1 if visible else 0
        self.ids.load_more_btn.disabled = not visible

    def _set_empty_state(self, title, message, icon="basket-off-outline"):
        if "empty_state_icon" in self.ids:
            self.ids.empty_state_icon.icon = icon
        if "empty_state_title" in self.ids:
            self.ids.empty_state_title.text = title
        if "empty_state_message" in self.ids:
            self.ids.empty_state_message.text = message

    def _show_empty_state(self, title, message, icon="basket-off-outline"):
        if "empty_state" not in self.ids:
            return
        self._set_empty_state(title, message, icon=icon)
        self.ids.empty_state.opacity = 1
        self.ids.empty_state.height = dp(240)
        self.ids.empty_state.disabled = False
        if "sales_list" in self.ids:
            self.ids.sales_list.opacity = 0

    def _hide_empty_state(self):
        if "empty_state" not in self.ids:
            return
        self.ids.empty_state.opacity = 0
        self.ids.empty_state.height = 0
        self.ids.empty_state.disabled = True
        if "sales_list" in self.ids:
            self.ids.sales_list.opacity = 1

    def _stop_rendering(self):
        if self._render_ev:
            try:
                self._render_ev.cancel()
            except Exception:
                Clock.unschedule(self._render_ev)
            self._render_ev = None
        self._pending_rows = deque()

    def _show_loading_state(self):
        if "sales_list" not in self.ids:
            return
        self._stop_rendering()
        self._display_rows = []
        self._current_page = 1
        self._render_index = 0
        # CORRIGIDO: clear_widgets() adiado para o próximo frame.
        # Antes era síncrono: removia 120+ widgets na UI thread antes do botão
        # soltar visualmente, causando o travamento percebido pelo usuário.
        self._update_load_more_button(False)
        self._show_empty_state("A carregar...", "Aguarde.", icon="progress-clock")
        Clock.schedule_once(lambda dt: self.ids.sales_list.clear_widgets() if "sales_list" in self.ids else None, 0)

    def _invalidate_all_sales_cache(self):
        self._all_sales_cache = []
        self._all_sales_summary = None
        self._all_sales_cache_valid = False
        self._all_sales_cache_at = 0.0

    def _get_cached_all_sales(self):
        if not self._all_sales_cache_valid:
            return None
        return self._all_sales_cache

    def _normalize_filter_dates(self, start_text="", end_text=""):
        start = (start_text or "").strip()
        end = (end_text or "").strip()
        if start and not end:
            end = start
        elif end and not start:
            start = end
        return start, end

    def _filter_rows_by_date_range_local(self, rows, start_text="", end_text=""):
        start_text, end_text = self._normalize_filter_dates(start_text, end_text)
        if not start_text and not end_text:
            return list(rows or [])

        start_dt = self._parse_sale_datetime(start_text)
        end_dt = self._parse_sale_datetime(end_text)
        if start_text and start_dt is None:
            return []
        if end_text and end_dt is None:
            return []

        start_date = start_dt.date() if start_dt else None
        end_date = end_dt.date() if end_dt else None
        filtered = []
        for row in rows or []:
            sale_raw = row[5] if len(row) > 5 else ""
            sale_dt = self._parse_sale_datetime(sale_raw)
            if sale_dt is None:
                continue
            sale_date = sale_dt.date()
            if start_date and sale_date < start_date:
                continue
            if end_date and sale_date > end_date:
                continue
            filtered.append(row)
        return filtered

    def _get_cached_filtered_rows(self, start_text="", end_text="", promo_only=False):
        rows = self._get_cached_all_sales()
        if rows is None:
            return None
        filtered = self._filter_rows_by_date_range_local(rows, start_text, end_text)
        if promo_only:
            filtered = self._only_promotional_rows(filtered)
        return filtered

    def _load_rows_from_cache(self, start_text="", end_text="", promo_only=False):
        if not self._all_sales_cache_valid:
            return False
        if not start_text and not end_text and not promo_only:
            # Sem filtro: entrega direto, sem thread nem loading state
            self._populate_list(
                list(self._all_sales_cache),
                summary=self._all_sales_summary,
            )
            return True
        # CORRIGIDO: filtro local (Python puro) não precisa de thread nem de
        # _show_loading_state(). Executa na UI thread mas é O(n) simples —
        # muito mais rápido do que o custo de clear_widgets() + thread overhead.
        rows = self._get_cached_filtered_rows(start_text, end_text, promo_only=promo_only)
        if rows is None:
            return False
        self._populate_list(rows)
        return True

    def _load_rows_async(self, fetcher, cache_all=False):
        token = self._rows_token + 1
        self._rows_token = token
        self._rows_loading = True
        self._show_loading_state()

        def worker():
            rows = []
            summary = None
            try:
                rows = list(fetcher() or [])
                summary = self._build_summary(rows)
            except Exception as exc:
                print(f"Erro ao carregar historico de vendas: {exc}")
                rows = []
                summary = self._build_summary(rows)
            Clock.schedule_once(
                lambda dt, data=rows, stats=summary, tok=token, cache_flag=cache_all: self._apply_loaded_rows(
                    data,
                    stats,
                    tok,
                    cache_all=cache_flag,
                ),
                0,
            )

        Thread(target=worker, daemon=True).start()

    def _apply_loaded_rows(self, rows, summary, token, cache_all=False):
        if token != self._rows_token:
            return
        self._rows_loading = False
        if cache_all:
            self._all_sales_cache = list(rows or [])
            self._all_sales_summary = dict(summary or {})
            self._all_sales_cache_valid = True
            self._all_sales_cache_at = perf_counter()
        self._populate_list(rows, summary=summary)
        self._last_loaded_at = perf_counter()

    def on_size(self, *args):
        Clock.schedule_once(lambda dt: self._update_responsive_layout(), 0)

    def go_back(self, *args):
        if self.manager:
            if getattr(self, "back_target", None) in self.manager.screen_names:
                self.manager.current = self.back_target
                return
            app = App.get_running_app()
            role = getattr(app, "current_role", "manager")
            target = "admin" if role == "admin" else "manager"
            if target in self.manager.screen_names:
                self.manager.current = target
            elif "login" in self.manager.screen_names:
                self.manager.current = "login"

    def _set_separator_visible(self, widget, visible):
        if not widget:
            return
        widget.opacity = 1 if visible else 0
        widget.disabled = not visible
        widget.width = dp(1) if visible else 0

    def _update_responsive_layout(self):
        if not self.ids or "header_date" not in self.ids:
            return
        width = self.width or dp(1200)
        compact = width < dp(980)
        if compact != self.compact_mode:
            self.compact_mode = compact
            if self._last_rows:
                self._populate_list(self._last_rows)
        self._apply_filters_layout(width)
        self._apply_header_layout()

    def _apply_filters_layout(self, width):
        if "date_filters_row" not in self.ids:
            return

        filters_card = self.ids.filters_card
        date_row = self.ids.date_filters_row
        quick_grid = self.ids.quick_filters_grid
        start_date = self.ids.start_date
        end_date = self.ids.end_date
        apply_btn = self.ids.apply_filter_btn

        if width < dp(1080):
            filters_card.height = dp(260)
            date_row.orientation = "vertical"
            date_row.height = dp(156)
            start_date.size_hint_x = 1
            end_date.size_hint_x = 1
            apply_btn.size_hint_x = 1
            quick_grid.cols = 3
        else:
            filters_card.height = dp(180)
            date_row.orientation = "horizontal"
            date_row.height = dp(56)
            start_date.size_hint_x = 0.38
            end_date.size_hint_x = 0.38
            apply_btn.size_hint_x = 0.24
            quick_grid.cols = 6 if width >= dp(1320) else 3

    def _apply_header_layout(self):
        if "header_date" not in self.ids:
            return
        if self.compact_mode:
            self.ids.header_date.size_hint_x = 0.24
            self.ids.header_product.size_hint_x = 0.40
            self.ids.header_qty.size_hint_x = 0.12
            self.ids.header_total.size_hint_x = 0.14
            self.ids.header_action.size_hint_x = 0.10

            self.ids.header_price.opacity = 0
            self.ids.header_price.disabled = True
            self.ids.header_price.size_hint_x = 0
            self._set_separator_visible(self.ids.header_sep_qty_price, False)
            self._set_separator_visible(self.ids.header_sep_price_total, False)
            self._set_separator_visible(self.ids.header_sep_total_action, True)
        else:
            self.ids.header_date.size_hint_x = 0.20
            self.ids.header_product.size_hint_x = 0.33
            self.ids.header_qty.size_hint_x = 0.11
            self.ids.header_price.size_hint_x = 0.13
            self.ids.header_total.size_hint_x = 0.13
            self.ids.header_action.size_hint_x = 0.10

            self.ids.header_price.opacity = 1
            self.ids.header_price.disabled = False
            self._set_separator_visible(self.ids.header_sep_qty_price, True)
            self._set_separator_visible(self.ids.header_sep_price_total, True)
            self._set_separator_visible(self.ids.header_sep_total_action, True)

    def _format_date(self, date_str):
        """Formata a data para exibição"""
        if not date_str:
            return ""
        try:
            dt = datetime.fromisoformat(date_str)
            return dt.strftime("%d/%m/%y\n%H:%M")
        except Exception:
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                return dt.strftime("%d/%m/%y\n%H:%M")
            except Exception:
                return str(date_str)[:16]

    def _format_qty(self, qty):
        """Formata a quantidade"""
        try:
            q = float(qty)
            if q.is_integer():
                return str(int(q))
            return f"{q:.1f}"
        except Exception:
            return str(qty)

    def _format_currency(self, value):
        """Formata valores monetários"""
        try:
            val = float(value)
            if val >= 1000000:
                return f"{val/1000000:.2f}M"
            elif val >= 1000:
                return f"{val/1000:.1f}K"
            return f"{val:,.2f}".replace(",", " ")
        except Exception:
            return "0.00"

    def _build_summary(self, rows):
        total_sales = len(rows or [])
        gross_revenue = 0.0
        refunded_total = 0.0
        for row in rows or []:
            gross_revenue += float(row[4] or 0) if len(row) > 4 else 0.0
            refunded_qty = float(row[6] or 0) if len(row) > 6 else 0.0
            unit_price = float(row[3] or 0) if len(row) > 3 else 0.0
            refunded_total += refunded_qty * unit_price
        return {
            "total_sales": total_sales,
            "net_revenue": gross_revenue - refunded_total,
            "refunded_total": refunded_total,
        }

    def _apply_summary(self, summary):
        if "total_sales_label" not in self.ids:
            return
        summary = summary or {}
        self.ids.total_sales_label.text = str(int(summary.get("total_sales") or 0))
        self.ids.total_revenue_label.text = (
            f"{self._format_currency(summary.get('net_revenue', 0.0))} MT"
        )
        self.ids.avg_sale_label.text = (
            f"{self._format_currency(summary.get('refunded_total', 0.0))} MT"
        )

    def _calculate_summary(self, rows):
        """Calcula estatísticas resumidas"""
        total_sales = len(rows)
        gross_revenue = 0.0
        refunded_total = 0.0
        for row in rows:
            sale = self._row_to_dict(row)
            gross_revenue += sale["total"]
            refunded_total += sale["returned_qty"] * sale["price"]
        net_revenue = gross_revenue - refunded_total

        self.ids.total_sales_label.text = str(total_sales)
        self.ids.total_revenue_label.text = f"{self._format_currency(net_revenue)} MT"
        self.ids.avg_sale_label.text = f"{self._format_currency(refunded_total)} MT"

    def _row_to_dict(self, row):
        sale_id = row[0] if len(row) > 0 else None
        product = (row[1] if len(row) > 1 else "") or "Produto"
        qty = float(row[2] or 0) if len(row) > 2 else 0.0
        price = float(row[3] or 0) if len(row) > 3 else 0.0
        total = float(row[4] or 0) if len(row) > 4 else 0.0
        sale_date = row[5] if len(row) > 5 else ""
        returned_qty = float(row[6] or 0) if len(row) > 6 else 0.0
        if len(row) > 7:
            available_qty = float(row[7] or 0)
        else:
            available_qty = max(0.0, qty - returned_qty)
        created_by = row[8] if len(row) > 8 else None
        created_role = row[9] if len(row) > 9 else None
        is_promotional = bool(row[10]) if len(row) > 10 else False
        return {
            "sale_id": sale_id,
            "product": product,
            "qty": qty,
            "price": price,
            "total": total,
            "sale_date": sale_date,
            "returned_qty": returned_qty,
            "available_qty": max(0.0, available_qty),
            "created_by": created_by,
            "created_role": created_role,
            "is_promotional": is_promotional,
        }

    # ─── NOVO: fábrica de separador vertical reutilizável ────────────────────
    def _make_vsep(self):
        """
        Cria um separador vertical de 1dp.
        Usa Color e Rectangle já importados no topo do módulo — sem re-import por linha.
        """
        sep = Widget(size_hint_x=None, width=dp(1))
        with sep.canvas.before:
            Color(*self._divider_color_cache)
            rect = Rectangle(pos=sep.pos, size=sep.size)
        sep.bind(
            pos=lambda w, p, r=rect: setattr(r, "pos", p),
            size=lambda w, s, r=rect: setattr(r, "size", s),
        )
        return sep

    # ─── NOVO: fábrica de separador horizontal reutilizável ─────────────────
    def _make_hsep(self):
        """Cria um separador horizontal de 1dp entre linhas da tabela."""
        div = Widget(size_hint_y=None, height=dp(1))
        with div.canvas.before:
            Color(*self._divider_color_cache)
            rect = Rectangle(pos=div.pos, size=div.size)
        div.bind(
            pos=lambda w, p, r=rect: setattr(r, "pos", p),
            size=lambda w, s, r=rect: setattr(r, "size", s),
        )
        return div

    def _create_table_row(self, row, index):
        """
        Cria uma linha da tabela com separadores verticais.

        Otimizações aplicadas vs versão anterior:
        - Color/Rectangle importados no topo do módulo (não por chamada)
        - _make_vsep() / _make_hsep() centralizam a criação de separadores
        - Cores lidas do cache de instância (não de theme_tokens por linha)
        - MDCard removido do badge de quantidade → MDLabel direto
        - MDBoxLayout de wrapper removido de qty, total e action → widgets diretos
        - product_box mantido como MDBoxLayout pois pode ter 1-3 filhos dinâmicos
        """
        sale = self._row_to_dict(row)
        sale_id      = sale["sale_id"]
        product      = sale["product"]
        qty          = sale["qty"]
        price        = sale["price"]
        total        = sale["total"]
        sale_date    = sale["sale_date"]
        returned_qty = sale["returned_qty"]
        available_qty = sale["available_qty"]
        is_promotional = sale["is_promotional"]

        # Cores lidas do cache (atualizado em _populate_list uma vez por lote)
        bg = self._bg_even_cache if index % 2 == 0 else self._bg_odd_cache
        divider_color   = self._divider_color_cache
        text_primary    = self._text_primary_cache
        text_secondary  = self._text_secondary_cache
        primary         = self._primary_cache
        success         = self._success_cache

        if self.compact_mode:
            date_w, product_w, qty_w, total_w, action_w = 0.24, 0.40, 0.12, 0.14, 0.10
        else:
            date_w, product_w, qty_w, price_w, total_w, action_w = 0.20, 0.33, 0.11, 0.13, 0.13, 0.10

        # Container externo (linha + divider horizontal)
        container = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(56),
            spacing=dp(0),
        )

        # Linha principal
        line = MDBoxLayout(
            size_hint_y=None,
            height=dp(56),
            padding=[dp(16), dp(10)],
            spacing=dp(0),
            md_bg_color=bg,
        )

        # ── Data/Hora ────────────────────────────────────────────────────────
        line.add_widget(MDLabel(
            text=self._format_date(sale_date),
            size_hint_x=date_w,
            halign="left",
            font_size=dp(11),
            theme_text_color="Custom",
            text_color=text_secondary,
        ))

        line.add_widget(self._make_vsep())

        # ── Produto (com sub-labels opcionais para promo e estorno) ──────────
        product_box = MDBoxLayout(
            orientation="vertical",
            size_hint_x=product_w,
            padding=[dp(12), 0, dp(8), 0],
            spacing=dp(2),
        )
        product_box.add_widget(MDLabel(
            text=str(product),
            halign="left",
            font_size=dp(12),
            bold=True,
            shorten=True,
            shorten_from="right",
            theme_text_color="Custom",
            text_color=text_primary,
        ))
        if is_promotional:
            product_box.add_widget(MDLabel(
                text="PROMO",
                halign="left",
                font_size=dp(10),
                theme_text_color="Custom",
                text_color=self._warning_cache,
                bold=True,
                shorten=True,
                shorten_from="right",
            ))
        if returned_qty > 0:
            product_box.add_widget(MDLabel(
                text=f"Estornado: {self._format_qty(returned_qty)}",
                halign="left",
                font_size=dp(10),
                theme_text_color="Custom",
                text_color=text_secondary,
                shorten=True,
                shorten_from="right",
            ))
        line.add_widget(product_box)

        line.add_widget(self._make_vsep())

        # ── Quantidade (MDLabel direto — sem MDCard nem MDBoxLayout wrapper) ─
        # ANTES: MDBoxLayout > MDCard > MDLabel  (3 widgets + canvas por badge)
        # AGORA: MDLabel direto com padding embutido (1 widget)
        line.add_widget(MDLabel(
            text=self._format_qty(qty),
            halign="center",
            valign="center",
            font_size=dp(12),
            bold=True,
            size_hint_x=qty_w,
            theme_text_color="Custom",
            text_color=primary,
        ))

        # ── Preço Unitário (apenas em modo normal) ───────────────────────────
        if not self.compact_mode:
            line.add_widget(self._make_vsep())
            line.add_widget(MDLabel(
                text=f"{self._format_currency(price)}",
                halign="right",
                font_size=dp(11),
                size_hint_x=price_w,
                padding=[0, 0, dp(8), 0],
                theme_text_color="Custom",
                text_color=text_secondary,
            ))
            line.add_widget(self._make_vsep())

        # ── Total líquido (sem MDBoxLayout wrapper) ──────────────────────────
        total_liquido = max(0.0, total - (returned_qty * price))
        line.add_widget(MDLabel(
            text=f"{self._format_currency(total_liquido)} MT",
            halign="right",
            font_size=dp(12),
            bold=True,
            size_hint_x=total_w,
            padding=[0, 0, dp(8), 0],
            theme_text_color="Custom",
            text_color=success,
        ))

        line.add_widget(self._make_vsep())

        # ── Ação (botão ESTORNAR ou OK desabilitado) ─────────────────────────
        # MDBoxLayout de wrapper removido — botão direto com size_hint_x
        row_payload = dict(sale)
        if sale_id and available_qty > 0.0001:
            action_btn = MDRaisedButton(
                text="ESTORNAR",
                size_hint_x=action_w,
                md_bg_color=self._warning_cache,
                theme_text_color="Custom",
                text_color=self._on_primary_cache,
                font_size=dp(10),
                on_release=lambda _btn, data=row_payload: self.open_refund_dialog(data),
            )
        else:
            action_btn = MDRaisedButton(
                text="OK",
                size_hint_x=action_w,
                md_bg_color=self._card_alt_cache,
                theme_text_color="Custom",
                text_color=self._on_primary_cache,
                font_size=dp(10),
                disabled=True,
            )
        line.add_widget(action_btn)

        container.add_widget(line)
        container.add_widget(self._make_hsep())

        return container

    def _populate_list(self, rows, summary=None):
        """Popula a lista de vendas"""
        if "sales_list" not in self.ids:
            return

        rows = list(rows or [])
        self._last_rows = rows
        self._stop_rendering()
        self.ids.sales_list.clear_widgets()

        # ── Atualiza cache de cores UMA vez por lote (não por linha) ─────────
        app = App.get_running_app()
        tokens = getattr(app, "theme_tokens", {})
        self._divider_color_cache  = tokens.get("divider",        [0,    0,    0,    0.12])
        self._bg_even_cache        = tokens.get("surface_alt",    [0.98, 0.99, 1,    1   ])
        self._bg_odd_cache         = tokens.get("card",           [1,    1,    1,    1   ])
        self._text_primary_cache   = tokens.get("text_primary",   [0.15, 0.20, 0.30, 1   ])
        self._text_secondary_cache = tokens.get("text_secondary", [0.35, 0.40, 0.50, 1   ])
        self._primary_cache        = tokens.get("primary",        [0.10, 0.35, 0.65, 1   ])
        self._success_cache        = tokens.get("success",        [0.20, 0.65, 0.30, 1   ])
        self._warning_cache        = tokens.get("warning",        [0.95, 0.62, 0.12, 1   ])
        self._on_primary_cache     = tokens.get("on_primary",     [1,    1,    1,    1   ])
        self._card_alt_cache       = tokens.get("card_alt",       [0.65, 0.65, 0.65, 1   ])

        # Mostrar/ocultar estado vazio
        if len(rows) == 0:
            self._display_rows = []
            self._apply_summary(None)
            self._update_load_more_button(False)
            self._show_empty_state(
                "Nenhuma venda encontrada",
                "Ajuste os filtros ou adicione novas vendas ao sistema",
            )
            return
        self._hide_empty_state()

        # Calcular estatísticas
        self._apply_summary(summary or self._build_summary(rows))

        # Adicionar linhas com separadores (em lotes)
        self._display_rows = rows
        self._current_page = 1
        self._render_page(reset=True)

    def _render_page(self, reset=False):
        if not self._display_rows:
            self._update_load_more_button(False)
            return
        if reset:
            start = 0
            self._current_page = 1
        else:
            start = (self._current_page - 1) * self._page_size
        end = self._current_page * self._page_size
        rows_to_render = self._display_rows[start:end]
        self._start_batch_render(rows_to_render, reset=reset)
        has_more = end < len(self._display_rows)
        self._update_load_more_button(has_more)

    def load_more_rows(self):
        if not self._display_rows or self._rows_loading or self._pending_rows:
            return
        end = self._current_page * self._page_size
        if end >= len(self._display_rows):
            return
        self._current_page += 1
        self._render_page(reset=False)

    def _start_batch_render(self, rows, reset=False):
        self._stop_rendering()
        self._pending_rows = deque(rows or [])
        if reset:
            self.ids.sales_list.clear_widgets()
            self._render_index = 0
        if not self._pending_rows:
            return
        self._render_ev = Clock.schedule_interval(
            self._render_next_batch,
            self.RENDER_INTERVAL_SECONDS,
        )

    def _render_next_batch(self, dt):
        batch_size = self.RENDER_BATCH_SIZE
        for _ in range(min(batch_size, len(self._pending_rows))):
            row = self._pending_rows.popleft()
            row_widget = self._create_table_row(row, self._render_index)
            self.ids.sales_list.add_widget(row_widget)
            self._render_index += 1
        if not self._pending_rows:
            self._render_ev = None
            return False
        return True

    def _show_message_dialog(self, title, message):
        dialog = MDDialog(
            title=title,
            text=message,
            buttons=[MDFlatButton(text="OK", on_release=lambda _x: dialog.dismiss())],
        )
        dialog.open()

    def _ensure_sales_history_report(self):
        if self.sales_history_report is None:
            from pdfs.sales_history_report import SalesHistoryReport
            self.sales_history_report = SalesHistoryReport()
        return self.sales_history_report

    def _ensure_pdf_viewer(self):
        if self.pdf_viewer is None:
            from pdfs.pdf_viewer import PDFViewer
            self.pdf_viewer = PDFViewer(
                error_callback=lambda msg: self._show_message_dialog("Erro", msg)
            )
        return self.pdf_viewer

    # CORRIGIDO: memoização por string de data.
    # Antes: chamado por linha de tabela, tentava 4 parsers com try/except cada vez.
    # Para 1000 linhas = 4000 tentativas de parse a cada filtro aplicado.
    # Agora: resultado cacheado por valor — cada string única é parseada só uma vez.
    @staticmethod
    @lru_cache(maxsize=2048)
    def _parse_sale_datetime(value):
        if not value:
            return None
        raw = str(value).strip()
        if not raw:
            return None
        for fmt, parser in (
            ("iso",            lambda s: datetime.fromisoformat(s)),
            ("%Y-%m-%d %H:%M:%S", lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M:%S")),
            ("%Y-%m-%d",       lambda s: datetime.strptime(s, "%Y-%m-%d")),
            ("%d/%m/%Y",       lambda s: datetime.strptime(s, "%d/%m/%Y")),
        ):
            try:
                return parser(raw)
            except Exception:
                continue
        return None

    def _get_export_period(self, sales):
        start_text = (self.ids.start_date.text or "").strip() if "start_date" in self.ids else ""
        end_text   = (self.ids.end_date.text   or "").strip() if "end_date"   in self.ids else ""
        start_dt = self._parse_sale_datetime(start_text)
        end_dt   = self._parse_sale_datetime(end_text)

        row_dates = []
        for sale in sales or []:
            parsed = self._parse_sale_datetime(sale.get("sale_date"))
            if parsed is not None:
                row_dates.append(parsed)

        if start_dt is None and row_dates:
            start_dt = min(row_dates)
        if end_dt is None and row_dates:
            end_dt = max(row_dates)
        if start_dt is None:
            start_dt = datetime.now()
        if end_dt is None:
            end_dt = start_dt
        if end_dt < start_dt:
            start_dt, end_dt = end_dt, start_dt
        return start_dt, end_dt

    def _get_filter_label(self):
        labels = {
            "today": "Hoje",
            "week":  "Esta semana",
            "month": "Este mes",
            "year":  "Este ano",
            "promo": "Promocoes",
            "custom":"Periodo personalizado",
        }
        return labels.get(self.current_filter, "Todos os registos")

    def _build_pdf_filters(self, sales):
        start_dt, end_dt = self._get_export_period(sales)
        return {
            "start_date":   start_dt,
            "end_date":     end_dt,
            "filter_label": self._get_filter_label(),
            "record_count": len(sales or []),
        }

    def _finish_sales_export(self, result):
        self._exporting_sales = False
        status = result.get("status")
        if status == "ok":
            self._show_pdf_success(result.get("path"))
            return
        self._show_message_dialog(
            "Erro",
            f"Falha ao gerar PDF de vendas: {result.get('error')}",
        )

    def _show_pdf_success(self, pdf_path):
        dialog = MDDialog(
            title="PDF Gerado",
            text=f"Arquivo criado em:\n{pdf_path}",
            buttons=[
                MDFlatButton(text="FECHAR",    on_release=lambda _x: dialog.dismiss()),
                MDFlatButton(
                    text="NAVEGADOR",
                    on_release=lambda _x: self._open_pdf_in_browser(dialog, pdf_path),
                ),
                MDRaisedButton(
                    text="INTERNO",
                    on_release=lambda _x: self._open_pdf_internal(dialog, pdf_path),
                ),
            ],
        )
        dialog.open()

    def _open_pdf_internal(self, dialog, pdf_path):
        dialog.dismiss()
        self._ensure_pdf_viewer()._view_internal(pdf_path)

    def _open_pdf_in_browser(self, dialog, pdf_path):
        dialog.dismiss()
        self._ensure_pdf_viewer()._open_in_browser(pdf_path)

    def _reload_current_filter(self):
        if self.current_filter == "today":
            self.filter_today()
            return
        if self.current_filter == "week":
            self.filter_this_week()
            return
        if self.current_filter == "month":
            self.filter_this_month()
            return
        if self.current_filter == "year":
            self.filter_this_year()
            return
        if self.current_filter == "promo":
            self.filter_promotional_sales()
            return
        if self.current_filter == "custom":
            self.apply_date_filter()
            return
        self.load_all_sales()

    def open_refund_dialog(self, sale_data):
        available_qty = float(sale_data.get("available_qty", 0) or 0)
        if available_qty <= 0:
            self._show_message_dialog("Estorno", "Esta venda nao possui saldo para estorno.")
            return

        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(10),
            padding=[dp(8), dp(4), dp(8), dp(4)],
            size_hint_y=None,
        )
        content.bind(minimum_height=content.setter("height"))

        sale_id      = sale_data.get("sale_id")
        product      = sale_data.get("product") or "Produto"
        qty          = float(sale_data.get("qty",          0) or 0)
        returned_qty = float(sale_data.get("returned_qty", 0) or 0)
        price        = float(sale_data.get("price",        0) or 0)

        info = MDLabel(
            text=(
                f"Venda #{sale_id}\n"
                f"Produto: {product}\n"
                f"Vendido: {self._format_qty(qty)} | Estornado: {self._format_qty(returned_qty)}\n"
                f"Disponivel: {self._format_qty(available_qty)} | Preco: {self._format_currency(price)} MT"
            ),
            theme_text_color="Secondary",
            size_hint_y=None,
            height=dp(88),
        )
        qty_input = MDTextField(
            hint_text="Quantidade para estornar",
            input_filter="float",
            mode="rectangle",
            text=f"{available_qty:.2f}",
            size_hint_y=None,
            height=dp(48),
        )
        reason_input = MDTextField(
            hint_text="Motivo (opcional)",
            mode="rectangle",
            size_hint_y=None,
            height=dp(48),
        )
        content.add_widget(info)
        content.add_widget(qty_input)
        content.add_widget(reason_input)

        dialog = MDDialog(
            title="Estornar Venda",
            type="custom",
            content_cls=content,
            buttons=[
                MDFlatButton(text="CANCELAR", on_release=lambda _x: dialog.dismiss()),
                MDRaisedButton(
                    text="CONFIRMAR",
                    on_release=lambda _x: self._submit_refund(
                        dialog, sale_data, qty_input, reason_input
                    ),
                ),
            ],
        )
        dialog.open()

    def _submit_refund(self, dialog, sale_data, qty_input, reason_input):
        try:
            qty = float((qty_input.text or "").strip())
        except Exception:
            self._show_message_dialog("Erro", "Quantidade invalida.")
            return

        available_qty = float(sale_data.get("available_qty", 0) or 0)
        if qty <= 0:
            self._show_message_dialog("Erro", "Quantidade deve ser maior que zero.")
            return
        if qty > (available_qty + 1e-9):
            self._show_message_dialog(
                "Erro",
                f"Quantidade acima do saldo disponivel ({available_qty:.2f}).",
            )
            return

        app      = App.get_running_app()
        username = getattr(app, "current_user", None)
        role     = getattr(app, "current_role", None) or "manager"
        reason   = (reason_input.text or "").strip()
        sale_id  = sale_data.get("sale_id")

        result = self.db.refund_sale_item(
            sale_id,
            qty,
            reason=reason,
            username=username,
            role=role,
        )
        if not (isinstance(result, dict) and result.get("ok")):
            message = (
                result.get("message")
                if isinstance(result, dict)
                else "Falha ao registar estorno."
            )
            self._show_message_dialog("Erro", message)
            return

        try:
            if username:
                total_refund = float(result.get("total_refund", 0) or 0)
                self.db.log_action(
                    username,
                    role,
                    "REFUND_SALE",
                    f"Venda #{sale_id} | Qtd {qty:.2f} | {total_refund:.2f} MT",
                )
        except Exception:
            pass

        dialog.dismiss()
        self._invalidate_all_sales_cache()
        self._reload_current_filter()
        self._show_message_dialog(
            "Sucesso",
            f"Estorno registado com sucesso ({qty:.2f}).",
        )

    def load_all_sales(self, force_refresh=False, prefer_local_cache=False):
        """Carrega todas as vendas"""
        if "sales_list" not in self.ids:
            Clock.schedule_once(
                lambda dt: self.load_all_sales(
                    force_refresh=force_refresh,
                    prefer_local_cache=prefer_local_cache,
                ),
                0.1,
            )
            return
        self.current_filter = None
        self.ids.start_date.text = ""
        self.ids.end_date.text   = ""
        if force_refresh:
            self._invalidate_all_sales_cache()
        if not force_refresh and prefer_local_cache and self._all_sales_cache_valid:
            self._populate_list(
                list(self._all_sales_cache),
                summary=self._all_sales_summary,
            )
            return
        self._load_rows_async(lambda: self.db.get_all_sales(), cache_all=True)

    def filter_today(self):
        """Filtra vendas de hoje"""
        today = datetime.now().strftime("%d/%m/%Y")
        self.current_filter = "today"
        self.ids.start_date.text = today
        self.ids.end_date.text   = today
        if self._load_rows_from_cache(today, today):
            return
        self._load_rows_async(lambda day=today: self.db.get_sales_by_date(day))

    def filter_this_week(self):
        """Filtra vendas desta semana"""
        today      = datetime.now()
        start_week = today - timedelta(days=today.weekday())

        start_date = start_week.strftime("%d/%m/%Y")
        end_date   = today.strftime("%d/%m/%Y")

        self.current_filter = "week"
        self.ids.start_date.text = start_date
        self.ids.end_date.text   = end_date
        if self._load_rows_from_cache(start_date, end_date):
            return
        self._load_rows_async(
            lambda start=start_date, end=end_date: self.db.get_sales_by_date_range(start, end)
        )

    def filter_this_month(self):
        """Filtra vendas deste mês"""
        today       = datetime.now()
        start_month = today.replace(day=1)

        start_date = start_month.strftime("%d/%m/%Y")
        end_date   = today.strftime("%d/%m/%Y")

        self.current_filter = "month"
        self.ids.start_date.text = start_date
        self.ids.end_date.text   = end_date
        if self._load_rows_from_cache(start_date, end_date):
            return
        self._load_rows_async(
            lambda start=start_date, end=end_date: self.db.get_sales_by_date_range(start, end)
        )

    def filter_this_year(self):
        """Filtra vendas deste ano"""
        today      = datetime.now()
        start_year = today.replace(month=1, day=1)

        start_date = start_year.strftime("%d/%m/%Y")
        end_date   = today.strftime("%d/%m/%Y")

        self.current_filter = "year"
        self.ids.start_date.text = start_date
        self.ids.end_date.text   = end_date
        if self._load_rows_from_cache(start_date, end_date):
            return
        self._load_rows_async(
            lambda start=start_date, end=end_date: self.db.get_sales_by_date_range(start, end)
        )

    def _get_rows_from_date_inputs(self):
        start = self.ids.start_date.text.strip()
        end   = self.ids.end_date.text.strip()
        if start and end:
            return self.db.get_sales_by_date_range(start, end)
        if start:
            return self.db.get_sales_by_date(start)
        if end:
            return self.db.get_sales_by_date(end)
        return self.db.get_all_sales()

    def _only_promotional_rows(self, rows):
        return [row for row in rows if len(row) > 10 and bool(row[10])]

    def filter_promotional_sales(self):
        """Filtra vendas promocionais, respeitando datas quando preenchidas."""
        self.current_filter = "promo"
        start, end = self._normalize_filter_dates(
            self.ids.start_date.text,
            self.ids.end_date.text,
        )
        if self._load_rows_from_cache(start, end, promo_only=True):
            return
        self._load_rows_async(
            lambda: self._only_promotional_rows(self._get_rows_from_date_inputs())
        )

    def clear_filters(self):
        """Limpa todos os filtros"""
        self.load_all_sales(prefer_local_cache=True)

    def apply_date_filter(self):
        """Aplica filtro de data personalizado"""
        start, end = self._normalize_filter_dates(
            self.ids.start_date.text,
            self.ids.end_date.text,
        )

        if self.current_filter == "promo":
            if self._load_rows_from_cache(start, end, promo_only=True):
                return
            if start and end:
                self._load_rows_async(
                    lambda s=start, e=end: self._only_promotional_rows(
                        self.db.get_sales_by_date_range(s, e)
                    )
                )
                return
            self._load_rows_async(lambda: self._only_promotional_rows(self.db.get_all_sales()))
            return

        if start and end:
            self.current_filter = "custom"
            if self._load_rows_from_cache(start, end):
                return
            self._load_rows_async(
                lambda s=start, e=end: self.db.get_sales_by_date_range(s, e)
            )
            return
        self.current_filter = None
        self.load_all_sales(prefer_local_cache=True)

    def export_sales(self):
        """Exporta vendas para PDF"""
        from kivymd.toast import toast

        if self._exporting_sales:
            toast("Ja existe uma exportacao em andamento.")
            return
        if self._rows_loading:
            self._show_message_dialog(
                "Aguarde",
                "As vendas ainda estao a carregar. Tente novamente em instantes.",
            )
            return

        rows = list(self._last_rows or [])
        if not rows:
            self._show_message_dialog(
                "Aviso",
                "Nao ha vendas para exportar com os filtros atuais.",
            )
            return

        sales   = [self._row_to_dict(row) for row in rows]
        filters = self._build_pdf_filters(sales)
        app      = App.get_running_app()
        username = getattr(app, "current_user", None)
        role     = getattr(app, "current_role", None) or "manager"
        self._exporting_sales = True
        toast("A gerar PDF do historico de vendas...")

        def worker(sales_snapshot, filter_payload, actor, actor_role):
            result = {"status": "ok", "path": None, "error": None}
            try:
                pdf_path = self._ensure_sales_history_report().generate(
                    sales_snapshot,
                    filter_payload,
                )
                result["path"] = str(pdf_path)
                if actor:
                    try:
                        self.db.log_action(
                            actor,
                            actor_role,
                            "EXPORT_SALES_PDF",
                            f"PDF: {pdf_path}",
                        )
                    except Exception:
                        pass
            except Exception as exc:
                result["status"] = "error"
                result["error"]  = str(exc)
            Clock.schedule_once(
                lambda dt, payload=result: self._finish_sales_export(payload),
                0,
            )

        Thread(
            target=worker,
            args=(sales, filters, username, role),
            daemon=True,
        ).start()
