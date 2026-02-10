import sys
import os
import sys

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), 'pdfs')
)

from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.gridlayout import MDGridLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.button import MDRaisedButton, MDFlatButton
from kivymd.uix.textfield import MDTextField
from kivymd.uix.dialog import MDDialog
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.card import MDCard
from kivymd.uix.list import OneLineListItem, TwoLineListItem
from kivymd.uix.card import MDSeparator
from utils.ai_insights import build_admin_insights, build_admin_insights_ai
from utils.ai_popups import (
    build_auto_banner_data,
    build_banner_details_sections,
    render_auto_banners,
)

from datetime import datetime, timedelta
import sqlite3
from kivy.metrics import dp, sp
import pandas as pd
from kivy.uix.scrollview import ScrollView
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.app import App
from kivy.animation import Animation
from kivy.lang import Builder
from kivy.properties import ObjectProperty

from database.database import Database
from pdfs.sales_report import SalesReport
from pdfs.stock_report import StockReport
from pdfs.profit_report import ProfitReport

def _theme_color(name, fallback):
    app = App.get_running_app()
    tokens = getattr(app, "theme_tokens", {}) if app else {}
    return tokens.get(name, fallback)
from pdfs.complete_report import CompleteReport
from pdfs.pdf_viewer import PDFViewer


Builder.load_file('utils/reports_screen.kv')


class DateRangeDialog(MDDialog):
    """
    Dialog para seleção de intervalo de datas usando KivyMD.
    Permite seleção manual ou via atalhos predefinidos.
    """
    
    def __init__(self, callback, database, **kwargs):
        super().__init__(**kwargs)
        self.callback = callback
        self.database = database
        
        # Criar conteúdo
        content = self._create_content()
        
        super(DateRangeDialog, self).__init__(
            title="Selecionar Periodo",
            type="custom",
            content_cls=content,
            size_hint=(None, None),
            size=(min(dp(500), Window.width * 0.85), min(dp(450), Window.height * 0.7)),
            buttons=[
                MDFlatButton(
                    text="CANCELAR",
                    on_release=lambda x: self.dismiss()
                ),
                MDRaisedButton(
                    text="CONFIRMAR PERIODO",
                    md_bg_color=_theme_color('success', (0.2, 0.65, 0.33, 1)),
                    on_release=lambda x: self.confirm()
                ),
            ],
            **kwargs
        )
        
        Window.bind(on_resize=self.reposition)
    
    def _create_content(self):
        """Cria o conteúdo do dialog."""
        main_layout = MDBoxLayout(
            orientation='vertical',
            spacing=dp(15),
            size_hint_y=None,
            padding=[dp(10), dp(10)]
        )
        main_layout.bind(minimum_height=main_layout.setter('height'))
        
        # Descrição
        main_layout.add_widget(MDLabel(
            text='Defina o intervalo de datas para o relatorio',
            font_style='Caption',
            halign='left',
            theme_text_color='Custom',
            text_color=_theme_color('text_secondary', (0.5, 0.5, 0.5, 1)),
            size_hint_y=None,
            height=dp(20)
        ))
        
        # Campos de data
        self.start_date_field = MDTextField(
            hint_text="Data Inicial (DD/MM/AAAA)",
            mode="rectangle",
            size_hint_y=None,
            height=dp(56)
        )
        main_layout.add_widget(self.start_date_field)
        
        self.end_date_field = MDTextField(
            hint_text="Data Final (DD/MM/AAAA)",
            mode="rectangle",
            size_hint_y=None,
            height=dp(56)
        )
        main_layout.add_widget(self.end_date_field)
        
        # Label de atalhos
        main_layout.add_widget(MDLabel(
            text='Ou escolha um atalho:',
            font_style='Subtitle2',
            bold=True,
            halign='left',
            theme_text_color='Custom',
            text_color=_theme_color('text_primary', (0.3, 0.3, 0.3, 1)),
            size_hint_y=None,
            height=dp(25)
        ))
        
        # Atalhos de período
        shortcuts_layout = MDGridLayout(
            cols=2,
            spacing=dp(8),
            size_hint_y=None,
            height=dp(90),
            adaptive_height=True
        )
        
        shortcuts = [
            ("Hoje", self.set_today),
            ("7 Dias", lambda: self.set_days(7)),
            ("30 Dias", lambda: self.set_days(30)),
            ("Este Mes", self.set_this_month)
        ]
        
        for label, func in shortcuts:
            btn = MDRaisedButton(
                text=label,
                md_bg_color=_theme_color('card_alt', (0.98, 0.98, 0.98, 1)),
                text_color=_theme_color('warning', (0.8, 0.5, 0.15, 1)),
                elevation=0,
                size_hint_y=None,
                height=dp(40),
                on_release=lambda x, f=func: f()
            )
            shortcuts_layout.add_widget(btn)
        
        main_layout.add_widget(shortcuts_layout)
        
        return main_layout
    
    def reposition(self, instance, width, height):
        """Reposiciona dialog ao redimensionar janela."""
        if self.parent:
            self.size = (
                min(dp(500), Window.width * 0.85),
                min(dp(450), Window.height * 0.7)
            )
    
    def set_today(self):
        """Define período como hoje."""
        today = datetime.now().strftime("%d/%m/%Y")
        self.start_date_field.text = today
        self.end_date_field.text = today
    
    def set_days(self, days):
        """Define período de N dias atrás até hoje."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        self.start_date_field.text = start_date.strftime("%d/%m/%Y")
        self.end_date_field.text = end_date.strftime("%d/%m/%Y")
    
    def set_this_month(self):
        """Define período como o mês atual."""
        today = datetime.now()
        start_date = datetime(today.year, today.month, 1)
        self.start_date_field.text = start_date.strftime("%d/%m/%Y")
        self.end_date_field.text = today.strftime("%d/%m/%Y")
    
    def confirm(self):
        """Confirma seleção de datas."""
        try:
            start_text = self.start_date_field.text.strip()
            end_text = self.end_date_field.text.strip()
            
            if not start_text or not end_text:
                self._show_error("Por favor, preencha ambas as datas")
                return
            
            start = datetime.strptime(start_text, "%d/%m/%Y")
            end = datetime.strptime(end_text, "%d/%m/%Y")
            
            if start > end:
                self._show_error("A data inicial nao pode ser maior que a data final")
                return
            
            end = end.replace(hour=23, minute=59, second=59)
            
            self.callback(start, end)
            self.dismiss()
        except ValueError:
            self._show_error("Formato invalido. Use DD/MM/AAAA\nExemplo: 01/02/2026")
    
    def _show_error(self, message):
        """Mostra dialog de erro."""
        error_dialog = MDDialog(
            title="Formato Invalido",
            text=message,
            buttons=[
                MDRaisedButton(
                    text="ENTENDI",
                    md_bg_color=_theme_color('danger', (0.85, 0.3, 0.3, 1)),
                    on_release=lambda x: error_dialog.dismiss()
                ),
            ],
        )
        error_dialog.open()


class ReportsScreen(MDScreen):
    """
    Tela principal de geração de relatórios usando KivyMD.
    Gerencia filtros, geração de PDFs e visualização.
    """
    
    # ObjectProperties para widgets do .kv
    date_label = ObjectProperty(None)
    product_spinner = ObjectProperty(None)
    category_spinner = ObjectProperty(None)
    
    def __init__(self, **kwargs):
        super(ReportsScreen, self).__init__(**kwargs)
        self.db = Database()
        self.notification_count = 0
        self.start_date = None
        self.end_date = None
        self.selected_product = None
        self.selected_category = None
        self.db_path = 'database/inventory.db'
        self._ai_poll_ev = None
        
        # Menus dropdown do KivyMD
        self.product_menu = None
        self.category_menu = None
        self.products_list = ['Todos os Produtos']
        self.categories_list = ['Todas as Categorias']
        
        # Dialogs
        self.date_dialog = None
        self.error_dialog = None
        self.success_dialog = None
        
        # Inicializar geradores de relatório
        self.sales_report = SalesReport()
        self.stock_report = StockReport()
        self.profit_report = ProfitReport()
        self.complete_report = CompleteReport()
        self.pdf_viewer = PDFViewer(error_callback=self.show_error_popup)
    
    def on_enter(self):
        """Chamado quando a tela é exibida."""
        self.load_filters()
        self._refresh_date_label()
        Clock.schedule_once(self._init_badge, 0.1)
        Clock.schedule_once(self.update_ai_badge, 0.15)
        Clock.schedule_once(self.show_auto_ai_popups, 0.2)
        self._start_ai_polling()

    def on_leave(self):
        self._stop_ai_polling()

    # ------------------------------------------------------------------
    # Sistema de Notificacoes e Animacao de Abanar
    # ------------------------------------------------------------------
    def _init_badge(self, dt):
        """Inicializa o badge de notificacoes"""
        if hasattr(self.ids, 'ai_badge'):
            self.ids.ai_badge.opacity = 0

    def add_notification(self):
        """Adiciona uma nova notificacao"""
        self.notification_count += 1
        self.update_notification_badge(self.notification_count)

    def clear_notifications(self):
        """Limpa todas as notificacoes"""
        self.notification_count = 0
        self.update_notification_badge(0)

    def update_notification_badge(self, count):
        """Atualiza o badge e controla a animacao vibrante"""
        self.notification_count = count

        if not hasattr(self.ids, 'ai_badge') or not hasattr(self.ids, 'ai_badge_label'):
            return

        self.ids.ai_badge_label.text = str(count)

        if count > 0:
            self._show_badge()
            self._start_swing_animation()
        else:
            self._hide_badge()
            self._stop_swing_animation()

    def _show_badge(self):
        """Mostra o badge com animacao pop"""
        if not hasattr(self.ids, 'ai_badge'):
            return

        self.ids.ai_badge.size = (dp(0), dp(0))
        self.ids.ai_badge.opacity = 1

        anim = Animation(
            size=(dp(24), dp(24)),
            duration=0.3,
            transition='out_back'
        )
        anim.start(self.ids.ai_badge)

    def _hide_badge(self):
        """Esconde o badge com animacao"""
        if not hasattr(self.ids, 'ai_badge'):
            return

        anim = Animation(
            opacity=0,
            size=(dp(0), dp(0)),
            duration=0.2
        )
        anim.start(self.ids.ai_badge)

    def _start_swing_animation(self):
        """Inicia animacao vibrante do botao"""
        if not hasattr(self.ids, 'ai_button'):
            return

        self._stop_swing_animation()

        def swing_cycle(dt):
            if self.notification_count <= 0:
                return False

            original_pos = {"right": 0.965, "y": 0.04}

            swing = (
                Animation(pos_hint={"right": 0.970, "y": 0.045}, duration=0.15, transition='out_sine') +
                Animation(pos_hint={"right": 0.960, "y": 0.035}, duration=0.3, transition='in_out_sine') +
                Animation(pos_hint={"right": 0.968, "y": 0.042}, duration=0.25, transition='in_out_sine') +
                Animation(pos_hint={"right": 0.962, "y": 0.038}, duration=0.25, transition='in_out_sine') +
                Animation(pos_hint={"right": 0.967, "y": 0.041}, duration=0.2, transition='in_out_sine') +
                Animation(pos_hint={"right": 0.963, "y": 0.039}, duration=0.2, transition='in_out_sine') +
                Animation(pos_hint=original_pos, duration=0.15, transition='out_sine')
            )
            swing.start(self.ids.ai_button)
            return True

        self.swing_event = Clock.schedule_interval(swing_cycle, 2.5)
        swing_cycle(0)

    def _stop_swing_animation(self):
        """Para a animacao vibrante"""
        if hasattr(self, 'swing_event') and self.swing_event:
            self.swing_event.cancel()
            self.swing_event = None

        if hasattr(self.ids, 'ai_button'):
            Animation.cancel_all(self.ids.ai_button)
            anim = Animation(
                pos_hint={"right": 0.965, "y": 0.04},
                duration=0.2,
                transition='out_sine'
            )
            anim.start(self.ids.ai_button)
    
    def load_filters(self):
        """Carrega opções de filtros do banco de dados."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Carregar produtos
            cursor.execute("SELECT id, description FROM products ORDER BY description")
            products = cursor.fetchall()
            self.products_list = ['Todos os Produtos'] + [f"{prod[0]} - {prod[1]}" for prod in products]
            
            # Carregar categorias
            cursor.execute(
                "SELECT DISTINCT category FROM products " 
                "WHERE category IS NOT NULL ORDER BY category"
            )
            categories = cursor.fetchall()
            self.categories_list = ['Todas as Categorias'] + [cat[0] for cat in categories]
            
            conn.close()
        except Exception as e:
            print(f"Erro ao carregar filtros: {e}")
    
    # ----------------------------------------------------------------
    # Dropdown Menus para Produto e Categoria
    # ----------------------------------------------------------------
    def open_product_menu(self, item):
        """Abrir menu dropdown de produtos."""
        menu_items = [
            {
                "text": product,
                "viewclass": "OneLineListItem",
                "on_release": lambda x=product: self.select_product(x),
            } for product in self.products_list
        ]
        
        self.product_menu = MDDropdownMenu(
            caller=item,
            items=menu_items,
            width_mult=4,
            max_height=dp(300),
        )
        self.product_menu.open()
    
    def select_product(self, product_name):
        """Selecionar produto do menu."""
        if hasattr(self, 'product_spinner') and self.product_spinner:
            self.product_spinner.text = product_name
        self.product_menu.dismiss()
        self.update_product_selection(None, product_name)
    
    def open_category_menu(self, item):
        """Abrir menu dropdown de categorias."""
        menu_items = [
            {
                "text": category,
                "viewclass": "OneLineListItem",
                "on_release": lambda x=category: self.select_category(x),
            } for category in self.categories_list
        ]
        
        self.category_menu = MDDropdownMenu(
            caller=item,
            items=menu_items,
            width_mult=4,
            max_height=dp(300),
        )
        self.category_menu.open()
    
    def select_category(self, category_name):
        """Selecionar categoria do menu."""
        if hasattr(self, 'category_spinner') and self.category_spinner:
            self.category_spinner.text = category_name
        self.category_menu.dismiss()
        self.update_category_selection(None, category_name)
    
    # ----------------------------------------------------------------
    # Seleção de Datas com Dialog Customizado
    # ----------------------------------------------------------------
    def select_date_range(self):
        """Abre dialog customizado de seleção de período."""
        self.date_dialog = DateRangeDialog(database=self.db, callback=self.set_date_range)
        self.date_dialog.open()
    
    def set_date_range(self, start, end):
        """Define o período selecionado."""
        self.start_date = start
        self.end_date = end
        self._refresh_date_label()

    def _refresh_date_label(self, *args):
        """Atualiza o texto do período selecionado na UI."""
        label = None
        if hasattr(self, 'date_label') and self.date_label:
            label = self.date_label
        elif hasattr(self, 'ids') and 'date_label' in self.ids:
            label = self.ids.date_label

        if not label:
            Clock.schedule_once(self._refresh_date_label, 0)
            return

        if self.start_date and self.end_date:
            start_str = self.start_date.strftime("%d/%m/%Y")
            end_str = self.end_date.strftime("%d/%m/%Y")
            label.text = f"{start_str} ate {end_str}"
            label.theme_text_color = "Custom"
            label.text_color = _theme_color('text_primary', (0.2, 0.2, 0.2, 1))
        else:
            label.text = "Nenhum periodo selecionado"
            label.theme_text_color = "Custom"
            label.text_color = _theme_color('text_secondary', (0.5, 0.5, 0.5, 1))
    
    # ----------------------------------------------------------------
    # Atualização de Seleções
    # ----------------------------------------------------------------
    def update_product_selection(self, instance, text):
        """Atualiza seleção de produto."""
        if text == "Todos os Produtos":
            self.selected_product = None
        else:
            try:
                self.selected_product = int(text.split(" - ")[0])
            except (ValueError, IndexError):
                self.selected_product = None
    
    def update_category_selection(self, instance, text):
        """Atualiza seleção de categoria."""
        if text == "Todas as Categorias":
            self.selected_category = None
        else:
            self.selected_category = text
    
    # ----------------------------------------------------------------
    # Validação e Obtenção de Dados
    # ----------------------------------------------------------------
    def validate_filters(self):
        """Valida se os filtros necessários foram selecionados."""
        if not self.start_date or not self.end_date:
            self.show_error_popup('Selecione um periodo para gerar o relatorio')
            return False
        return True
    
    def get_filtered_data(self):
        """Obtém dados filtrados do banco de dados."""
        query = """
        SELECT 
            p.id,
            p.description,
            p.existing_stock,
            p.sale_price,
            p.total_purchase_price,
            p.unit_purchase_price,
            p.category,
            COALESCE(SUM(s.quantity), 0) as sold_in_period,
            COALESCE(SUM(s.total_price), 0) as total_sales
        FROM products p
        LEFT JOIN sales s
            ON s.product_id = p.id
           AND s.sale_date BETWEEN ? AND ?
        WHERE 1=1
        """
        params = [
            self.start_date.strftime("%Y-%m-%d %H:%M:%S"),
            self.end_date.strftime("%Y-%m-%d %H:%M:%S"),
        ]
        
        # Filtro de produto
        if self.selected_product:
            query += " AND p.id = ?"
            params.append(self.selected_product)
        
        # Filtro de categoria
        if self.selected_category:
            query += " AND p.category = ?"
            params.append(self.selected_category)

        query += """
        GROUP BY 
            p.id, p.description, p.existing_stock, p.sale_price,
            p.total_purchase_price, p.unit_purchase_price, p.category
        """
        
        try:
            conn = sqlite3.connect(self.db_path)
            df = pd.read_sql_query(query, conn, params=params)
            conn.close()
            
            if df.empty:
                return None

            df['sold_stock'] = df['sold_in_period']

            # Calcular métricas usando vendas do período
            df['entrada'] = df['existing_stock'] + df['sold_stock']
            df['saida'] = df['sold_stock']
            df['remanescente'] = df['existing_stock']
            df['lucro_unitario'] = df['sale_price'] - df['unit_purchase_price']
            df['lucro_total'] = df['lucro_unitario'] * df['sold_stock']
            df['percentual_lucro'] = (
                (df['lucro_unitario'] / df['unit_purchase_price']) * 100
            ).fillna(0)
            df['valor_total_vendas'] = df['total_sales']

            # Se não há vendas no período, retorna vazio
            if df['sold_stock'].sum() == 0:
                return None
            
            return df
        except Exception as e:
            print(f"Erro ao obter dados filtrados: {e}")
            return None
    
    def _get_filters_dict(self):
        """Retorna dicionário com os filtros atuais."""
        product_text = "Todos os Produtos"
        category_text = "Todas as Categorias"
        
        if hasattr(self, 'product_spinner') and self.product_spinner:
            product_text = self.product_spinner.text
        if hasattr(self, 'category_spinner') and self.category_spinner:
            category_text = self.category_spinner.text
        
        return {
            'start_date': self.start_date,
            'end_date': self.end_date,
            'product': product_text,
            'category': category_text
        }
    
    # ----------------------------------------------------------------
    # Geração de Relatórios
    # ----------------------------------------------------------------
    def generate_sales_report(self):
        """Gera relatório de vendas."""
        if not self.validate_filters():
            return
        
        df = self.get_filtered_data()
        if df is None:
            self.show_error_popup('Nenhum dado encontrado para os filtros selecionados')
            return
        
        try:
            pdf_path = self.sales_report.generate(df, self._get_filters_dict())
            self.show_success_popup(pdf_path)
        except Exception as e:
            self.show_error_popup(f'Erro ao gerar relatorio:\n{str(e)}')
            print(f"Erro detalhado: {e}")
    
    def generate_stock_report(self):
        """Gera relatório de estoque."""
        if not self.validate_filters():
            return
        
        df = self.get_filtered_data()
        if df is None:
            self.show_error_popup('Nenhum dado encontrado para os filtros selecionados')
            return
        
        try:
            pdf_path = self.stock_report.generate(df, self._get_filters_dict())
            self.show_success_popup(pdf_path)
        except Exception as e:
            self.show_error_popup(f'Erro ao gerar relatorio:\n{str(e)}')
            print(f"Erro detalhado: {e}")
    
    def generate_profit_report(self):
        """Gera relatório de lucro."""
        if not self.validate_filters():
            return
        
        df = self.get_filtered_data()
        if df is None:
            self.show_error_popup('Nenhum dado encontrado para os filtros selecionados')
            return
        
        try:
            pdf_path = self.profit_report.generate(df, self._get_filters_dict())
            self.show_success_popup(pdf_path)
        except Exception as e:
            self.show_error_popup(f'Erro ao gerar relatorio:\n{str(e)}')
            print(f"Erro detalhado: {e}")
    
    def generate_complete_report(self):
        """Gera relatório completo."""
        if not self.validate_filters():
            return
        
        df = self.get_filtered_data()
        if df is None:
            self.show_error_popup('Nenhum dado encontrado para os filtros selecionados')
            return
        
        try:
            pdf_path = self.complete_report.generate(df, self._get_filters_dict())
            self.show_success_popup(pdf_path)
        except Exception as e:
            self.show_error_popup(f'Erro ao gerar relatorio:\n{str(e)}')
            print(f"Erro detalhado: {e}")
    
    # ----------------------------------------------------------------
    # Visualizador de PDFs
    # ----------------------------------------------------------------
    def show_pdf_viewer(self):
        """Mostra lista de PDFs disponíveis."""
        report_dir = "Relatórios"
        
        if not os.path.exists(report_dir):
            self.show_error_popup(
                'Nenhum relatorio foi gerado ainda.\nGere um relatorio primeiro.'
            )
            return
        
        # Busca recursiva por PDFs
        pdf_files = []
        for root, dirs, files in os.walk(report_dir):
            for file in files:
                if file.lower().endswith('.pdf'):
                    pdf_files.append(os.path.join(root, file))
        
        if not pdf_files:
            self.show_error_popup('Nenhum PDF encontrado na pasta de relatorios.')
            return
        
        # Ordena por data (mais recente primeiro)
        pdf_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

        # Abre o popup do PDFViewer com o arquivo mais recente
        latest_pdf = pdf_files[0]
        self.pdf_viewer.view_pdf(latest_pdf)
    
    def _create_pdf_list_dialog(self, pdf_files):
        """Cria dialog com lista de PDFs usando KivyMD."""
        content = MDBoxLayout(
            orientation='vertical',
            spacing=dp(12),
            size_hint_y=None,
            padding=[dp(16), dp(12), dp(16), dp(10)]
        )
        content.bind(minimum_height=content.setter('height'))

        header = MDBoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(28),
        )
        header.add_widget(MDLabel(
            text="Arquivos encontrados",
            font_style='Subtitle1',
            bold=True,
            theme_text_color='Custom',
            text_color=_theme_color('text_primary', (0.2, 0.2, 0.2, 1)),
        ))
        header.add_widget(MDLabel(
            text=f"{len(pdf_files)} item(ns)",
            font_style='Caption',
            halign='right',
            theme_text_color='Custom',
            text_color=_theme_color('text_secondary', (0.5, 0.5, 0.5, 1)),
        ))
        content.add_widget(header)
        content.add_widget(MDSeparator(height=dp(1)))
        
        # Scroll com lista de PDFs
        scroll = ScrollView(size_hint=(1, 1))
        pdf_list = MDBoxLayout(
            orientation='vertical',
            spacing=dp(8),
            size_hint_y=None,
            padding=[0, dp(8)]
        )
        pdf_list.bind(minimum_height=pdf_list.setter('height'))
        
        for pdf_path in pdf_files:
            pdf_list.add_widget(self._create_pdf_card_md(pdf_path))
        
        scroll.add_widget(pdf_list)
        content.add_widget(scroll)
        
        # Dialog
        self.pdf_dialog = MDDialog(
            title=f"PDFs Disponiveis ({len(pdf_files)})",
            type="custom",
            content_cls=content,
            size_hint=(0.85, 0.82),
            buttons=[
                MDFlatButton(
                    text="FECHAR",
                    on_release=lambda x: self.pdf_dialog.dismiss()
                ),
            ],
        )
        self.pdf_dialog.open()
    
    def _create_pdf_card_md(self, pdf_path):
        """Cria card de PDF usando KivyMD."""
        file_size = os.path.getsize(pdf_path) / 1024
        mod_time = datetime.fromtimestamp(os.path.getmtime(pdf_path))
        
        # Extrai informação
        parts = pdf_path.split(os.sep)
        pdf_filename = parts[-1]
        
        if len(parts) >= 4:
            report_type = parts[-3]
            report_date = parts[-2]
            display_name = f"{report_type} - {report_date}"
            subtitle = pdf_filename
        else:
            display_name = pdf_filename
            subtitle = f"{mod_time.strftime('%d/%m/%Y %H:%M')} | {file_size:.1f} KB"
        
        # Card
        card = MDCard(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(72),
            padding=[dp(12), dp(10)],
            spacing=dp(12),
            elevation=2,
            md_bg_color=_theme_color('card_alt', (0.98, 0.98, 0.98, 1)),
            radius=[dp(8)]
        )

        icon_box = MDBoxLayout(
            size_hint=(None, None),
            size=(dp(46), dp(46)),
            md_bg_color=_theme_color('card_alt', (0.15, 0.52, 0.76, 0.15)),
            radius=[dp(8)],
            pos_hint={"center_y": 0.5}
        )
        icon_label = MDLabel(
            text="PDF",
            font_style='Subtitle2',
            bold=True,
            halign='center',
            valign='middle',
            theme_text_color='Custom',
            text_color=_theme_color('primary', (0.15, 0.52, 0.76, 1)),
        )
        icon_label.bind(size=lambda inst, _: setattr(inst, "text_size", inst.size))
        icon_box.add_widget(icon_label)
        card.add_widget(icon_box)
        
        # Informações
        info_box = MDBoxLayout(
            orientation='vertical',
            spacing=dp(4),
            size_hint_x=0.65
        )
        
        info_box.add_widget(MDLabel(
            text=display_name,
            font_style='Subtitle1',
            bold=True,
            theme_text_color='Custom',
            text_color=_theme_color('text_primary', (0.2, 0.2, 0.2, 1)),
            size_hint_y=None,
            height=dp(25)
        ))
        
        info_box.add_widget(MDLabel(
            text=subtitle,
            font_style='Caption',
            theme_text_color='Custom',
            text_color=_theme_color('text_secondary', (0.5, 0.5, 0.5, 1)),
            size_hint_y=None,
            height=dp(18),
            shorten=True,
            shorten_from='right'
        ))
        
        card.add_widget(info_box)
        
        # Botão Visualizar
        view_btn = MDRaisedButton(
            text="Visualizar",
            size_hint=(None, None),
            size=(dp(110), dp(34)),
            md_bg_color=_theme_color('primary', (0.15, 0.52, 0.76, 1)),
            pos_hint={"center_y": 0.5},
            on_release=lambda x, path=pdf_path: self._view_and_close_dialog(path)
        )
        
        card.add_widget(view_btn)
        
        return card
    
    def _view_and_close_dialog(self, pdf_path):
        """Visualiza PDF e fecha dialog."""
        if hasattr(self, 'pdf_dialog'):
            self.pdf_dialog.dismiss()
        self.pdf_viewer.view_pdf(pdf_path)
    
    # ----------------------------------------------------------------
    # Dialogs de Erro e Sucesso usando KivyMD
    # ----------------------------------------------------------------
    def show_error_popup(self, message):
        """Mostra dialog de erro usando KivyMD."""
        if self.error_dialog:
            self.error_dialog.dismiss()
        
        self.error_dialog = MDDialog(
            title="Atencao",
            text=message,
            buttons=[
                MDRaisedButton(
                    text="ENTENDI",
                    md_bg_color=_theme_color('danger', (0.85, 0.3, 0.3, 1)),
                    on_release=lambda x: self.error_dialog.dismiss()
                ),
            ],
        )
        self.error_dialog.open()
    
    def show_success_popup(self, pdf_path):
        """Mostra dialog de sucesso usando KivyMD."""
        filename = os.path.basename(pdf_path)
        
        if self.success_dialog:
            self.success_dialog.dismiss()
        
        self.success_dialog = MDDialog(
            title="Sucesso",
            text=f"Relatorio gerado:\n{filename}",
            buttons=[
                MDFlatButton(
                    text="FECHAR",
                    on_release=lambda x: self.success_dialog.dismiss()
                ),
                MDRaisedButton(
                    text="VISUALIZAR PDF",
                    md_bg_color=_theme_color('primary', (0.15, 0.52, 0.76, 1)),
                    on_release=lambda x: self._view_pdf_and_close(pdf_path)
                ),
            ],
        )
        self.success_dialog.open()
    
    def _view_pdf_and_close(self, pdf_path):
        """Visualiza PDF e fecha dialog de sucesso."""
        if self.success_dialog:
            self.success_dialog.dismiss()
        self.pdf_viewer.view_pdf(pdf_path)

    def _get_alert_key(self, insights):
        low_stock = sorted([item[0] for item in insights.get("low_stock", [])])
        exp7 = sorted([item[0] for item in insights.get("expiring_7", [])])
        exp15 = sorted([item[0] for item in insights.get("expiring_15", [])])

        parts = []
        if low_stock:
            parts.append("ls:" + ",".join(low_stock))
        if exp7:
            parts.append("e7:" + ",".join(exp7))
        if exp15:
            parts.append("e15:" + ",".join(exp15))
        return "|".join(parts)

    def mark_notifications_seen(self, insights=None):
        insights = insights or build_admin_insights()
        key = self._get_alert_key(insights)
        app = App.get_running_app()
        if app:
            app._ai_notifications_seen_key = key
        self.update_notification_badge(0)

    def show_ai_insights(self, *args):
        """Abrir notificacoes em formato de banner"""
        if not hasattr(self, "ids") or "ai_banner_container" not in self.ids:
            return
        insights = build_admin_insights_ai()
        banners = build_auto_banner_data(insights)
        if not banners:
            return
        for banner in banners:
            banner["details_sections"] = build_banner_details_sections(
                insights, banner.get("kind"), max_lines=3
            )
        render_auto_banners(
            self.ids.ai_banner_container,
            banners,
            auto_dismiss_seconds=None,
            show_timer=False,
        )
        self.mark_notifications_seen(insights)

    def open_ai_menu(self, caller):
        app = App.get_running_app()
        insights = build_admin_insights()
        key = self._get_alert_key(insights)
        badge_counts = insights.get("badge_counts") or {}
        stock_count = badge_counts.get("stock", 0)
        expiry_count = badge_counts.get("expiry_7", 0) + badge_counts.get("expiry_15", 0)
        total_count = badge_counts.get("total", 0)

        if app and getattr(app, "_ai_notifications_seen_key", None) == key:
            stock_count = 0
            expiry_count = 0
            total_count = 0

        def _label(base, count):
            return f"{base} ({count})" if count > 0 else base

        items = [
            {"text": _label("Insights completos", total_count), "on_release": lambda x="full": self._open_ai_from_menu(x)},
            {"text": _label("Reposicao de stock", stock_count), "on_release": lambda x="stock": self._open_ai_from_menu(x)},
            {"text": _label("Avisos de vencimento", expiry_count), "on_release": lambda x="expiry": self._open_ai_from_menu(x)},
        ]
        if hasattr(self, "_ai_menu") and self._ai_menu:
            self._ai_menu.dismiss()
        self._ai_menu = MDDropdownMenu(caller=caller, items=items, width_mult=4)
        self._ai_menu.open()
        self.mark_notifications_seen()

    def _open_ai_from_menu(self, key):
        if hasattr(self, "_ai_menu") and self._ai_menu:
            self._ai_menu.dismiss()
        if key == "stock":
            self.show_ai_stock_popup()
        elif key == "expiry":
            self.show_ai_expiry_popup()
        else:
            self.show_ai_insights()

    def show_ai_stock_popup(self, *args, insights=None, on_close=None):
        if not hasattr(self, "ids") or "ai_banner_container" not in self.ids:
            return
        insights = insights or build_admin_insights_ai()
        banners = [b for b in build_auto_banner_data(insights) if b.get("kind") == "stock"]
        if not banners:
            return
        for banner in banners:
            banner["details_sections"] = build_banner_details_sections(
                insights, banner.get("kind"), max_lines=3
            )
        render_auto_banners(
            self.ids.ai_banner_container,
            banners,
            auto_dismiss_seconds=None,
            show_timer=False,
        )
        self.mark_notifications_seen(insights)

    def show_ai_expiry_popup(self, *args, insights=None, on_close=None):
        if not hasattr(self, "ids") or "ai_banner_container" not in self.ids:
            return
        insights = insights or build_admin_insights_ai()
        banners = [b for b in build_auto_banner_data(insights) if b.get("kind") == "expiry"]
        if not banners:
            return
        for banner in banners:
            banner["details_sections"] = build_banner_details_sections(
                insights, banner.get("kind"), max_lines=3
            )
        render_auto_banners(
            self.ids.ai_banner_container,
            banners,
            auto_dismiss_seconds=None,
            show_timer=False,
        )
        self.mark_notifications_seen(insights)

    def show_auto_ai_popups(self, *args):
        """Mostra banners automaticos (stock e vencimentos)."""
        if not hasattr(self, "ids") or "ai_banner_container" not in self.ids:
            return

        app = App.get_running_app()
        insights = build_admin_insights_ai(self.db)
        banners = build_auto_banner_data(insights)
        key = self._get_alert_key(insights)

        if not banners:
            if app:
                app._ai_banners_last_key = key
            return

        if app:
            last_key = getattr(app, "_ai_banners_last_key", None)
            if last_key == key:
                return
            app._ai_banners_last_key = key

        container = self.ids.ai_banner_container
        render_auto_banners(container, banners, auto_dismiss_seconds=10)

    def update_ai_badge(self, *args):
        """Atualiza o badge do botao de insights com animacao vibrante."""
        insights = build_admin_insights()
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
        self.update_ai_badge()
        self.show_auto_ai_popups()

    def _start_ai_polling(self):
        if self._ai_poll_ev:
            self._ai_poll_ev.cancel()
        self._ai_poll_ev = Clock.schedule_interval(self._poll_ai_alerts, 30)

    def _stop_ai_polling(self):
        if self._ai_poll_ev:
            self._ai_poll_ev.cancel()
            self._ai_poll_ev = None
    
    # ----------------------------------------------------------------
    # Navegação
    # ----------------------------------------------------------------
    def go_back(self):
        """Volta para a tela anterior."""
        self.manager.current = 'admin'
