from datetime import datetime

from kivy.clock import Clock
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.uix.widget import Widget
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton, MDFlatButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField

from database.database import Database


Builder.load_string("""
<SalesHistoryScreen>:
    name: "sales_history"
    md_bg_color: 0.95, 0.96, 0.98, 1

    MDBoxLayout:
        orientation: "vertical"

        # Header com gradiente
        MDTopAppBar:
            title: "Histórico de Vendas"
            md_bg_color: 0.09, 0.38, 0.73, 1
            specific_text_color: 1, 1, 1, 1
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
                orientation: "vertical"
                size_hint_y: None
                height: dp(180)
                padding: dp(0)
                spacing: dp(0)
                elevation: 3
                radius: [dp(16)]
                md_bg_color: 1, 1, 1, 1

                # Header do Card
                MDBoxLayout:
                    size_hint_y: None
                    height: dp(50)
                    padding: [dp(20), dp(12)]
                    md_bg_color: 0.97, 0.98, 1, 1
                    radius: [dp(16), dp(16), 0, 0]

                    MDIcon:
                        icon: "filter-variant"
                        size_hint_x: None
                        width: dp(28)
                        theme_text_color: "Custom"
                        text_color: 0.09, 0.38, 0.73, 1

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
                            rgba: 0.9, 0.9, 0.92, 1
                        Rectangle:
                            pos: self.pos
                            size: self.size

                # Conteúdo dos filtros
                MDBoxLayout:
                    orientation: "vertical"
                    padding: dp(20)
                    spacing: dp(14)

                    # Date Range Filters
                    MDBoxLayout:
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
                            line_color_focus: 0.09, 0.38, 0.73, 1

                        MDTextField:
                            id: end_date
                            hint_text: "Data Fim"
                            helper_text: "Formato: dd/mm/aaaa"
                            helper_text_mode: "on_focus"
                            mode: "rectangle"
                            size_hint_x: 0.38
                            icon_right: "calendar"
                            max_text_length: 10
                            line_color_focus: 0.09, 0.38, 0.73, 1

                        MDRaisedButton:
                            text: "APLICAR"
                            size_hint_x: 0.24
                            md_bg_color: 0.09, 0.38, 0.73, 1
                            elevation: 2
                            on_release: root.apply_date_filter()

                    # Quick Filter Buttons
                    MDBoxLayout:
                        size_hint_y: None
                        height: dp(42)
                        spacing: dp(10)

                        MDRaisedButton:
                            text: "HOJE"
                            size_hint_x: 0.2
                            md_bg_color: 0.15, 0.68, 0.38, 1
                            elevation: 2
                            on_release: root.filter_today()

                        MDRaisedButton:
                            text: "SEMANA"
                            size_hint_x: 0.2
                            md_bg_color: 0.2, 0.59, 0.86, 1
                            elevation: 2
                            on_release: root.filter_this_week()

                        MDRaisedButton:
                            text: "MÊS"
                            size_hint_x: 0.2
                            md_bg_color: 0.4, 0.47, 0.84, 1
                            elevation: 2
                            on_release: root.filter_this_month()

                        MDRaisedButton:
                            text: "ANO"
                            size_hint_x: 0.2
                            md_bg_color: 0.61, 0.35, 0.71, 1
                            elevation: 2
                            on_release: root.filter_this_year()

                        MDFlatButton:
                            text: "LIMPAR"
                            size_hint_x: 0.2
                            theme_text_color: "Custom"
                            text_color: 0.8, 0.3, 0.3, 1
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
                md_bg_color: 1, 1, 1, 1

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
                            text_color: 0.09, 0.38, 0.73, 1

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
                            rgba: 0.9, 0.9, 0.92, 1
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
                            text_color: 0.15, 0.68, 0.38, 1

                        MDLabel:
                            text: "Receita Total"
                            font_style: "Caption"
                            theme_text_color: "Secondary"

                    MDLabel:
                        id: total_revenue_label
                        text: "0.00 MT"
                        font_style: "H4"
                        theme_text_color: "Custom"
                        text_color: 0.15, 0.68, 0.38, 1
                        bold: True

                # Separador vertical
                Widget:
                    size_hint_x: None
                    width: dp(1)
                    canvas.before:
                        Color:
                            rgba: 0.9, 0.9, 0.92, 1
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
                            text_color: 0.4, 0.47, 0.84, 1

                        MDLabel:
                            text: "Venda Média"
                            font_style: "Caption"
                            theme_text_color: "Secondary"

                    MDLabel:
                        id: avg_sale_label
                        text: "0.00 MT"
                        font_style: "H4"
                        theme_text_color: "Custom"
                        text_color: 0.4, 0.47, 0.84, 1
                        bold: True

            # Sales Table Card
            MDCard:
                orientation: "vertical"
                padding: dp(0)
                spacing: dp(0)
                elevation: 3
                radius: [dp(16)]
                md_bg_color: 1, 1, 1, 1

                # Table Header
                MDBoxLayout:
                    size_hint_y: None
                    height: dp(56)
                    padding: [dp(20), dp(0)]
                    spacing: dp(0)
                    md_bg_color: 0.09, 0.38, 0.73, 1
                    radius: [dp(16), dp(16), 0, 0]

                    MDLabel:
                        text: "Data/Hora"
                        bold: True
                        theme_text_color: "Custom"
                        text_color: 1, 1, 1, 1
                        size_hint_x: 0.22
                        halign: "left"
                        font_size: dp(13)

                    # Separador vertical
                    Widget:
                        size_hint_x: None
                        width: dp(1)
                        canvas.before:
                            Color:
                                rgba: 1, 1, 1, 0.2
                            Rectangle:
                                pos: self.pos
                                size: self.size

                    MDLabel:
                        text: "Produto"
                        bold: True
                        theme_text_color: "Custom"
                        text_color: 1, 1, 1, 1
                        size_hint_x: 0.36
                        halign: "left"
                        padding: [dp(12), 0]
                        font_size: dp(13)

                    # Separador vertical
                    Widget:
                        size_hint_x: None
                        width: dp(1)
                        canvas.before:
                            Color:
                                rgba: 1, 1, 1, 0.2
                            Rectangle:
                                pos: self.pos
                                size: self.size

                    MDLabel:
                        text: "Qtd"
                        bold: True
                        theme_text_color: "Custom"
                        text_color: 1, 1, 1, 1
                        size_hint_x: 0.12
                        halign: "center"
                        font_size: dp(13)

                    # Separador vertical
                    Widget:
                        size_hint_x: None
                        width: dp(1)
                        canvas.before:
                            Color:
                                rgba: 1, 1, 1, 0.2
                            Rectangle:
                                pos: self.pos
                                size: self.size

                    MDLabel:
                        text: "Preço Un."
                        bold: True
                        theme_text_color: "Custom"
                        text_color: 1, 1, 1, 1
                        size_hint_x: 0.15
                        halign: "right"
                        padding: [0, 0, dp(8), 0]
                        font_size: dp(13)

                    # Separador vertical
                    Widget:
                        size_hint_x: None
                        width: dp(1)
                        canvas.before:
                            Color:
                                rgba: 1, 1, 1, 0.2
                            Rectangle:
                                pos: self.pos
                                size: self.size

                    MDLabel:
                        text: "Total"
                        bold: True
                        theme_text_color: "Custom"
                        text_color: 1, 1, 1, 1
                        size_hint_x: 0.15
                        halign: "right"
                        padding: [0, 0, dp(12), 0]
                        font_size: dp(13)

                # Divider após header
                Widget:
                    size_hint_y: None
                    height: dp(2)
                    canvas.before:
                        Color:
                            rgba: 0.85, 0.87, 0.90, 1
                        Rectangle:
                            pos: self.pos
                            size: self.size

                # Table Content
                ScrollView:
                    do_scroll_x: False
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
                    height: dp(300)
                    opacity: 0

                    MDIcon:
                        icon: "basket-off-outline"
                        font_size: dp(80)
                        halign: "center"
                        theme_text_color: "Custom"
                        text_color: 0.85, 0.85, 0.87, 1

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
""")


class SalesHistoryScreen(MDScreen):
    def __init__(self, db=None, **kwargs):
        super().__init__(**kwargs)
        self.db = db or Database()
        self.current_filter = None
        Clock.schedule_once(lambda dt: self.load_all_sales(), 0.1)

    def go_back(self, *args):
        if self.manager:
            self.manager.current = "manager"

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
        total_revenue = sum(float(row[4]) for row in rows) if rows else 0
        avg_sale = total_revenue / total_sales if total_sales > 0 else 0

        self.ids.total_sales_label.text = str(total_sales)
        self.ids.total_revenue_label.text = f"{self._format_currency(total_revenue)} MT"
        self.ids.avg_sale_label.text = f"{self._format_currency(avg_sale)} MT"

    def _create_table_row(self, sale_id, product, qty, price, total, sale_date, index):
        """Cria uma linha da tabela com separadores verticais"""
        # Cores alternadas com melhor contraste
        bg = [0.98, 0.99, 1, 1] if index % 2 == 0 else [1, 1, 1, 1]

        container = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(60),
            spacing=dp(0)
        )

        line = MDBoxLayout(
            size_hint_y=None,
            height=dp(60),
            padding=[dp(20), dp(12)],
            spacing=dp(0),
            md_bg_color=bg
        )

        # Data/Hora
        date_label = MDLabel(
            text=self._format_date(sale_date),
            size_hint_x=0.22,
            halign="left",
            font_size=dp(11),
            theme_text_color="Secondary"
        )
        line.add_widget(date_label)

        # Separador vertical
        sep1 = Widget(size_hint_x=None, width=dp(1))
        sep1.canvas.before.clear()
        from kivy.graphics import Color, Rectangle
        with sep1.canvas.before:
            Color(0.92, 0.93, 0.95, 1)
            rect1 = Rectangle(pos=sep1.pos, size=sep1.size)
        sep1.bind(pos=lambda i, p: setattr(rect1, 'pos', p))
        sep1.bind(size=lambda i, s: setattr(rect1, 'size', s))
        line.add_widget(sep1)

        # Produto
        product_box = MDBoxLayout(size_hint_x=0.36, padding=[dp(12), 0, dp(8), 0])
        product_label = MDLabel(
            text=str(product),
            halign="left",
            font_size=dp(12),
            bold=True,
            shorten=True,
            shorten_from="right"
        )
        product_box.add_widget(product_label)
        line.add_widget(product_box)

        # Separador vertical
        sep2 = Widget(size_hint_x=None, width=dp(1))
        with sep2.canvas.before:
            Color(0.92, 0.93, 0.95, 1)
            rect2 = Rectangle(pos=sep2.pos, size=sep2.size)
        sep2.bind(pos=lambda i, p: setattr(rect2, 'pos', p))
        sep2.bind(size=lambda i, s: setattr(rect2, 'size', s))
        line.add_widget(sep2)

        # Quantidade com badge
        qty_box = MDBoxLayout(size_hint_x=0.12, padding=dp(4))
        qty_card = MDCard(
            size_hint=(None, None),
            size=(dp(40), dp(28)),
            md_bg_color=[0.09, 0.38, 0.73, 0.15],
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
            text_color=[0.09, 0.38, 0.73, 1]
        )
        qty_card.add_widget(qty_label)
        qty_box.add_widget(qty_card)
        line.add_widget(qty_box)

        # Separador vertical
        sep3 = Widget(size_hint_x=None, width=dp(1))
        with sep3.canvas.before:
            Color(0.92, 0.93, 0.95, 1)
            rect3 = Rectangle(pos=sep3.pos, size=sep3.size)
        sep3.bind(pos=lambda i, p: setattr(rect3, 'pos', p))
        sep3.bind(size=lambda i, s: setattr(rect3, 'size', s))
        line.add_widget(sep3)

        # Preço Unitário
        price_box = MDBoxLayout(size_hint_x=0.15, padding=[0, 0, dp(8), 0])
        price_label = MDLabel(
            text=f"{self._format_currency(price)}",
            halign="right",
            font_size=dp(11),
            theme_text_color="Secondary"
        )
        price_box.add_widget(price_label)
        line.add_widget(price_box)

        # Separador vertical
        sep4 = Widget(size_hint_x=None, width=dp(1))
        with sep4.canvas.before:
            Color(0.92, 0.93, 0.95, 1)
            rect4 = Rectangle(pos=sep4.pos, size=sep4.size)
        sep4.bind(pos=lambda i, p: setattr(rect4, 'pos', p))
        sep4.bind(size=lambda i, s: setattr(rect4, 'size', s))
        line.add_widget(sep4)

        # Total com destaque
        total_box = MDBoxLayout(size_hint_x=0.15, padding=[0, 0, dp(12), 0])
        total_label = MDLabel(
            text=f"{self._format_currency(total)} MT",
            halign="right",
            font_size=dp(12),
            bold=True,
            theme_text_color="Custom",
            text_color=[0.15, 0.68, 0.38, 1]
        )
        total_box.add_widget(total_label)
        line.add_widget(total_box)

        container.add_widget(line)

        # Divider horizontal entre linhas
        divider = Widget(size_hint_y=None, height=dp(1))
        with divider.canvas.before:
            Color(0.95, 0.95, 0.96, 1)
            rect_div = Rectangle(pos=divider.pos, size=divider.size)
        divider.bind(pos=lambda i, p: setattr(rect_div, 'pos', p))
        divider.bind(size=lambda i, s: setattr(rect_div, 'size', s))
        container.add_widget(divider)

        return container

    def _populate_list(self, rows):
        """Popula a lista de vendas"""
        if "sales_list" not in self.ids:
            return

        self.ids.sales_list.clear_widgets()

        # Mostrar/ocultar estado vazio
        if len(rows) == 0:
            self.ids.empty_state.opacity = 1
            self.ids.sales_list.opacity = 0
        else:
            self.ids.empty_state.opacity = 0
            self.ids.sales_list.opacity = 1

        # Calcular estatísticas
        self._calculate_summary(rows)

        # Adicionar linhas com separadores
        for i, row in enumerate(rows):
            sale_id, product, qty, price, total, sale_date = row
            row_widget = self._create_table_row(sale_id, product, qty, price, total, sale_date, i)
            self.ids.sales_list.add_widget(row_widget)

    def load_all_sales(self):
        """Carrega todas as vendas"""
        self.current_filter = None
        self.ids.start_date.text = ""
        self.ids.end_date.text = ""
        rows = self.db.get_all_sales()
        self._populate_list(rows)

    def filter_today(self):
        """Filtra vendas de hoje"""
        today = datetime.now().strftime("%d/%m/%Y")
        self.current_filter = "today"
        self.ids.start_date.text = today
        self.ids.end_date.text = today
        rows = self.db.get_sales_by_date(today)
        self._populate_list(rows)

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
        rows = self.db.get_sales_by_date_range(start_date, end_date)
        self._populate_list(rows)

    def filter_this_month(self):
        """Filtra vendas deste mês"""
        today = datetime.now()
        start_month = today.replace(day=1)
        
        start_date = start_month.strftime("%d/%m/%Y")
        end_date = today.strftime("%d/%m/%Y")
        
        self.current_filter = "month"
        self.ids.start_date.text = start_date
        self.ids.end_date.text = end_date
        rows = self.db.get_sales_by_date_range(start_date, end_date)
        self._populate_list(rows)

    def filter_this_year(self):
        """Filtra vendas deste ano"""
        today = datetime.now()
        start_year = today.replace(month=1, day=1)
        
        start_date = start_year.strftime("%d/%m/%Y")
        end_date = today.strftime("%d/%m/%Y")
        
        self.current_filter = "year"
        self.ids.start_date.text = start_date
        self.ids.end_date.text = end_date
        rows = self.db.get_sales_by_date_range(start_date, end_date)
        self._populate_list(rows)

    def clear_filters(self):
        """Limpa todos os filtros"""
        self.load_all_sales()

    def apply_date_filter(self):
        """Aplica filtro de data personalizado"""
        start = self.ids.start_date.text.strip()
        end = self.ids.end_date.text.strip()

        if start and end:
            rows = self.db.get_sales_by_date_range(start, end)
            self._populate_list(rows)
            return
        if start:
            rows = self.db.get_sales_by_date(start)
            self._populate_list(rows)
            return
        if end:
            rows = self.db.get_sales_by_date(end)
            self._populate_list(rows)
            return
        self.load_all_sales()

    def export_sales(self):
        """Exporta vendas para CSV"""
        # TODO: Implementar exportação
        from kivymd.toast import toast
        toast("Funcionalidade de exportação em desenvolvimento")
