from kivymd.uix.dialog import MDDialog
from datetime import datetime
from threading import Thread
from time import perf_counter

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import BooleanProperty
from kivy.uix.widget import Widget
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton, MDFlatButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.dialog import MDDialog
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
            right_action_items: [["file-download-outline", lambda x: root.export_sales()], ["refresh", lambda x: root.load_all_sales()]]

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
                        icon: "basket-off-outline"
                        font_size: dp(80)
                        halign: "center"
                        theme_text_color: "Custom"
                        text_color: app.theme_tokens['text_secondary']

                    MDLabel:
                        text: "Nenhuma venda encontrada"
                        halign: "center"
                        theme_text_color: "Hint"
                        font_style: "H5"
                        bold: True

                    MDLabel:
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
    compact_mode = BooleanProperty(False)

    def __init__(self, db=None, **kwargs):
        self._last_rows = []
        self._render_ev = None
        self._pending_rows = []
        self._render_index = 0
        self._display_rows = []
        self._page_size = 60
        self._current_page = 1
        self._last_loaded_at = 0.0
        self._rows_loading = False
        self._rows_token = 0
        self.back_target = "admin_home"
        super().__init__(**kwargs)
        self.db = db or get_db()
        self.current_filter = None

    def on_kv_post(self, base_widget):
        self._update_responsive_layout()

    def on_pre_enter(self, *args):
        self.request_enter_refresh()

    def request_enter_refresh(self, force=False, delay=0.05):
        stale = (perf_counter() - self._last_loaded_at) >= self.ENTER_CACHE_SECONDS
        if not force and self._last_rows and not stale:
            return
        Clock.schedule_once(lambda dt: self.load_all_sales(), delay)

    def _load_rows_async(self, fetcher):
        token = self._rows_token + 1
        self._rows_token = token
        self._rows_loading = True

        def worker():
            rows = []
            try:
                rows = fetcher() or []
            except Exception as exc:
                print(f"Erro ao carregar historico de vendas: {exc}")
            Clock.schedule_once(lambda dt, data=rows, tok=token: self._apply_loaded_rows(data, tok), 0)

        Thread(target=worker, daemon=True).start()

    def _apply_loaded_rows(self, rows, token):
        if token != self._rows_token:
            return
        self._rows_loading = False
        self._populate_list(rows)
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

    def _create_table_row(self, row, index):
        """Cria uma linha da tabela com separadores verticais"""
        sale = self._row_to_dict(row)
        sale_id = sale["sale_id"]
        product = sale["product"]
        qty = sale["qty"]
        price = sale["price"]
        total = sale["total"]
        sale_date = sale["sale_date"]
        returned_qty = sale["returned_qty"]
        available_qty = sale["available_qty"]
        is_promotional = sale["is_promotional"]

        app = App.get_running_app()
        tokens = getattr(app, "theme_tokens", {})
        bg_even = tokens.get("surface_alt", [0.98, 0.99, 1, 1])
        bg_odd = tokens.get("card", [1, 1, 1, 1])
        divider_color = tokens.get("divider", [0, 0, 0, 0.12])
        text_primary = tokens.get("text_primary", [0.15, 0.20, 0.30, 1])
        text_secondary = tokens.get("text_secondary", [0.35, 0.40, 0.50, 1])
        primary = tokens.get("primary", [0.10, 0.35, 0.65, 1])
        success = tokens.get("success", [0.20, 0.65, 0.30, 1])
        # Cores alternadas com melhor contraste
        bg = bg_even if index % 2 == 0 else bg_odd
        if self.compact_mode:
            date_w, product_w, qty_w, total_w, action_w = 0.24, 0.40, 0.12, 0.14, 0.10
        else:
            date_w, product_w, qty_w, price_w, total_w, action_w = 0.20, 0.33, 0.11, 0.13, 0.13, 0.10

        container = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(56),
            spacing=dp(0)
        )

        line = MDBoxLayout(
            size_hint_y=None,
            height=dp(56),
            padding=[dp(16), dp(10)],
            spacing=dp(0),
            md_bg_color=bg
        )

        # Data/Hora
        date_label = MDLabel(
            text=self._format_date(sale_date),
            size_hint_x=date_w,
            halign="left",
            font_size=dp(11),
            theme_text_color="Custom",
            text_color=text_secondary
        )
        line.add_widget(date_label)

        # Separador vertical
        sep1 = Widget(size_hint_x=None, width=dp(1))
        sep1.canvas.before.clear()
        from kivy.graphics import Color, Rectangle
        with sep1.canvas.before:
            Color(*divider_color)
            rect1 = Rectangle(pos=sep1.pos, size=sep1.size)
        sep1.bind(pos=lambda i, p: setattr(rect1, 'pos', p))
        sep1.bind(size=lambda i, s: setattr(rect1, 'size', s))
        line.add_widget(sep1)

        # Produto
        product_box = MDBoxLayout(
            orientation="vertical",
            size_hint_x=product_w,
            padding=[dp(12), 0, dp(8), 0],
            spacing=dp(2),
        )
        product_label = MDLabel(
            text=str(product),
            halign="left",
            font_size=dp(12),
            bold=True,
            shorten=True,
            shorten_from="right",
            theme_text_color="Custom",
            text_color=text_primary
        )
        product_box.add_widget(product_label)
        if is_promotional:
            promo_meta = MDLabel(
                text="PROMO",
                halign="left",
                font_size=dp(10),
                theme_text_color="Custom",
                text_color=tokens.get("warning", [0.95, 0.62, 0.12, 1]),
                bold=True,
                shorten=True,
                shorten_from="right",
            )
            product_box.add_widget(promo_meta)
        if returned_qty > 0:
            refunded_meta = MDLabel(
                text=f"Estornado: {self._format_qty(returned_qty)}",
                halign="left",
                font_size=dp(10),
                theme_text_color="Custom",
                text_color=text_secondary,
                shorten=True,
                shorten_from="right",
            )
            product_box.add_widget(refunded_meta)
        line.add_widget(product_box)

        # Separador vertical
        sep2 = Widget(size_hint_x=None, width=dp(1))
        with sep2.canvas.before:
            Color(*divider_color)
            rect2 = Rectangle(pos=sep2.pos, size=sep2.size)
        sep2.bind(pos=lambda i, p: setattr(rect2, 'pos', p))
        sep2.bind(size=lambda i, s: setattr(rect2, 'size', s))
        line.add_widget(sep2)

        # Quantidade com badge
        qty_box = MDBoxLayout(size_hint_x=qty_w, padding=dp(4))
        qty_card = MDCard(
            size_hint=(None, None),
            size=(dp(40), dp(26)),
            md_bg_color=[primary[0], primary[1], primary[2], 0.18],
            radius=[dp(14)],
            pos_hint={"center_x": 0.5, "center_y": 0.5}
        )
        qty_label = MDLabel(
            text=self._format_qty(qty),
            halign="center",
            valign="center",
            font_size=dp(12),
            bold=True,
            theme_text_color="Custom",
            text_color=primary
        )
        qty_card.add_widget(qty_label)
        qty_box.add_widget(qty_card)
        line.add_widget(qty_box)

        if not self.compact_mode:
            # Separador vertical
            sep3 = Widget(size_hint_x=None, width=dp(1))
            with sep3.canvas.before:
                Color(*divider_color)
                rect3 = Rectangle(pos=sep3.pos, size=sep3.size)
            sep3.bind(pos=lambda i, p: setattr(rect3, 'pos', p))
            sep3.bind(size=lambda i, s: setattr(rect3, 'size', s))
            line.add_widget(sep3)

            # Preço Unitário
            price_box = MDBoxLayout(size_hint_x=price_w, padding=[0, 0, dp(8), 0])
            price_label = MDLabel(
                text=f"{self._format_currency(price)}",
                halign="right",
                font_size=dp(11),
                theme_text_color="Custom",
                text_color=text_secondary
            )
            price_box.add_widget(price_label)
            line.add_widget(price_box)

            # Separador vertical
            sep4 = Widget(size_hint_x=None, width=dp(1))
            with sep4.canvas.before:
                Color(*divider_color)
                rect4 = Rectangle(pos=sep4.pos, size=sep4.size)
            sep4.bind(pos=lambda i, p: setattr(rect4, 'pos', p))
            sep4.bind(size=lambda i, s: setattr(rect4, 'size', s))
            line.add_widget(sep4)

        # Total com destaque (liquido de estornos)
        total_liquido = max(0.0, total - (returned_qty * price))
        total_box = MDBoxLayout(size_hint_x=total_w, padding=[0, 0, dp(8), 0])
        total_label = MDLabel(
            text=f"{self._format_currency(total_liquido)} MT",
            halign="right",
            font_size=dp(12),
            bold=True,
            theme_text_color="Custom",
            text_color=success
        )
        total_box.add_widget(total_label)
        line.add_widget(total_box)

        # Separador vertical (acao)
        sep_action = Widget(size_hint_x=None, width=dp(1))
        with sep_action.canvas.before:
            Color(*divider_color)
            rect_action = Rectangle(pos=sep_action.pos, size=sep_action.size)
        sep_action.bind(pos=lambda i, p: setattr(rect_action, "pos", p))
        sep_action.bind(size=lambda i, s: setattr(rect_action, "size", s))
        line.add_widget(sep_action)

        action_box = MDBoxLayout(
            size_hint_x=action_w,
            padding=[dp(4), dp(4), dp(4), dp(4)],
        )
        row_payload = dict(sale)
        if sale_id and available_qty > 0.0001:
            refund_btn = MDRaisedButton(
                text="ESTORNAR",
                md_bg_color=tokens.get("warning", [0.95, 0.62, 0.12, 1]),
                theme_text_color="Custom",
                text_color=tokens.get("on_primary", [1, 1, 1, 1]),
                font_size=dp(10),
                on_release=lambda _btn, data=row_payload: self.open_refund_dialog(data),
            )
        else:
            refund_btn = MDRaisedButton(
                text="OK",
                md_bg_color=tokens.get("card_alt", [0.65, 0.65, 0.65, 1]),
                theme_text_color="Custom",
                text_color=tokens.get("on_primary", [1, 1, 1, 1]),
                font_size=dp(10),
                disabled=True,
            )
        action_box.add_widget(refund_btn)
        line.add_widget(action_box)

        container.add_widget(line)

        # Divider horizontal entre linhas
        divider = Widget(size_hint_y=None, height=dp(1))
        with divider.canvas.before:
            Color(*divider_color)
            rect_div = Rectangle(pos=divider.pos, size=divider.size)
        divider.bind(pos=lambda i, p: setattr(rect_div, 'pos', p))
        divider.bind(size=lambda i, s: setattr(rect_div, 'size', s))
        container.add_widget(divider)

        return container

    def _populate_list(self, rows):
        """Popula a lista de vendas"""
        if "sales_list" not in self.ids:
            return

        rows = rows or []
        self._last_rows = list(rows)
        self.ids.sales_list.clear_widgets()

        # Mostrar/ocultar estado vazio
        if len(rows) == 0:
            self.ids.empty_state.opacity = 1
            self.ids.empty_state.height = dp(240)
            self.ids.empty_state.disabled = False
            self.ids.sales_list.opacity = 0
            if "load_more_btn" in self.ids:
                self.ids.load_more_btn.opacity = 0
                self.ids.load_more_btn.disabled = True
            if self._render_ev:
                Clock.unschedule(self._render_ev)
                self._render_ev = None
            self._pending_rows = []
            return
        else:
            self.ids.empty_state.opacity = 0
            self.ids.empty_state.height = 0
            self.ids.empty_state.disabled = True
            self.ids.sales_list.opacity = 1

        # Calcular estatísticas
        self._calculate_summary(rows)

        # Adicionar linhas com separadores (em lotes)
        self._display_rows = list(rows)
        self._current_page = 1
        self._render_page(reset=True)

    def _render_page(self, reset=False):
        if not self._display_rows:
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
        if "load_more_btn" in self.ids:
            self.ids.load_more_btn.opacity = 1 if has_more else 0
            self.ids.load_more_btn.disabled = not has_more

    def load_more_rows(self):
        if not self._display_rows:
            return
        end = self._current_page * self._page_size
        if end >= len(self._display_rows):
            return
        self._current_page += 1
        self._render_page(reset=False)

    def _start_batch_render(self, rows, reset=False):
        if self._render_ev:
            Clock.unschedule(self._render_ev)
            self._render_ev = None
        self._pending_rows = list(rows)
        if reset:
            self.ids.sales_list.clear_widgets()
            self._render_index = 0
        if not self._pending_rows:
            return
        self._render_ev = Clock.schedule_interval(self._render_next_batch, 0)

    def _render_next_batch(self, dt):
        batch_size = 30
        for _ in range(min(batch_size, len(self._pending_rows))):
            row = self._pending_rows.pop(0)
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

        sale_id = sale_data.get("sale_id")
        product = sale_data.get("product") or "Produto"
        qty = float(sale_data.get("qty", 0) or 0)
        returned_qty = float(sale_data.get("returned_qty", 0) or 0)
        price = float(sale_data.get("price", 0) or 0)

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

        app = App.get_running_app()
        username = getattr(app, "current_user", None)
        role = getattr(app, "current_role", None) or "manager"
        reason = (reason_input.text or "").strip()
        sale_id = sale_data.get("sale_id")

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
        self._reload_current_filter()
        self._show_message_dialog(
            "Sucesso",
            f"Estorno registado com sucesso ({qty:.2f}).",
        )

    def load_all_sales(self):
        """Carrega todas as vendas"""
        if "sales_list" not in self.ids:
            Clock.schedule_once(lambda dt: self.load_all_sales(), 0.1)
            return
        self.current_filter = None
        self.ids.start_date.text = ""
        self.ids.end_date.text = ""
        self._load_rows_async(lambda: self.db.get_all_sales())

    def filter_today(self):
        """Filtra vendas de hoje"""
        today = datetime.now().strftime("%d/%m/%Y")
        self.current_filter = "today"
        self.ids.start_date.text = today
        self.ids.end_date.text = today
        self._load_rows_async(lambda day=today: self.db.get_sales_by_date(day))

    def filter_this_week(self):
        """Filtra vendas desta semana"""
        from datetime import timedelta
        today = datetime.now()
        start_week = today - timedelta(days=today.weekday())
        
        start_date = start_week.strftime("%d/%m/%Y")
        end_date = today.strftime("%d/%m/%Y")
        
        self.current_filter = "week"
        self.ids.start_date.text = start_date
        self.ids.end_date.text = end_date
        self._load_rows_async(lambda start=start_date, end=end_date: self.db.get_sales_by_date_range(start, end))

    def filter_this_month(self):
        """Filtra vendas deste mês"""
        today = datetime.now()
        start_month = today.replace(day=1)
        
        start_date = start_month.strftime("%d/%m/%Y")
        end_date = today.strftime("%d/%m/%Y")
        
        self.current_filter = "month"
        self.ids.start_date.text = start_date
        self.ids.end_date.text = end_date
        self._load_rows_async(lambda start=start_date, end=end_date: self.db.get_sales_by_date_range(start, end))

    def filter_this_year(self):
        """Filtra vendas deste ano"""
        today = datetime.now()
        start_year = today.replace(month=1, day=1)
        
        start_date = start_year.strftime("%d/%m/%Y")
        end_date = today.strftime("%d/%m/%Y")
        
        self.current_filter = "year"
        self.ids.start_date.text = start_date
        self.ids.end_date.text = end_date
        self._load_rows_async(lambda start=start_date, end=end_date: self.db.get_sales_by_date_range(start, end))

    def _get_rows_from_date_inputs(self):
        start = self.ids.start_date.text.strip()
        end = self.ids.end_date.text.strip()
        if start and end:
            return self.db.get_sales_by_date_range(start, end)
        if start:
            return self.db.get_sales_by_date(start)
        if end:
            return self.db.get_sales_by_date(end)
        return self.db.get_all_sales()

    def _only_promotional_rows(self, rows):
        return [row for row in rows if self._row_to_dict(row).get("is_promotional")]

    def filter_promotional_sales(self):
        """Filtra vendas promocionais, respeitando datas quando preenchidas."""
        self.current_filter = "promo"
        self._load_rows_async(lambda: self._only_promotional_rows(self._get_rows_from_date_inputs()))

    def clear_filters(self):
        """Limpa todos os filtros"""
        self.load_all_sales()

    def apply_date_filter(self):
        """Aplica filtro de data personalizado"""
        start = self.ids.start_date.text.strip()
        end = self.ids.end_date.text.strip()

        if self.current_filter == "promo":
            self._load_rows_async(lambda: self._only_promotional_rows(self._get_rows_from_date_inputs()))
            return

        if start and end:
            self.current_filter = "custom"
            self._load_rows_async(lambda s=start, e=end: self.db.get_sales_by_date_range(s, e))
            return
        if start:
            self.current_filter = "custom"
            self._load_rows_async(lambda s=start: self.db.get_sales_by_date(s))
            return
        if end:
            self.current_filter = "custom"
            self._load_rows_async(lambda e=end: self.db.get_sales_by_date(e))
            return
        self.current_filter = None
        self.load_all_sales()

    def export_sales(self):
        """Exporta vendas para CSV"""
        # TODO: Implementar exportação
        from kivymd.toast import toast
        toast("Funcionalidade de exportação em desenvolvimento")
