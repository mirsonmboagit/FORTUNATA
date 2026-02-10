import time
import re
import unicodedata
from threading import Thread
import cv2
import numpy as np
from datetime import datetime
from pyzbar.pyzbar import decode

from kivy.uix.popup import Popup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.image import Image
from kivy.uix.anchorlayout import AnchorLayout
from kivy.graphics.texture import Texture
from kivy.graphics import Color, RoundedRectangle
from kivy.core.window import Window
from kivy.core.audio import SoundLoader
from kivy.clock import Clock
from kivy.animation import Animation
from kivy.metrics import dp, sp
from kivy.app import App

# KivyMD imports
from kivymd.uix.button import MDRaisedButton, MDFlatButton, MDIconButton
from kivymd.uix.textfield import MDTextField
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.selectioncontrol import MDSwitch
from kivymd.uix.card import MDCard
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.dialog import MDDialog
from kivymd.uix.pickers import MDDatePicker

from api.api_manager import APIManager
from api.api_openfoodfacts import OpenFoodFactsAPI
from api.api_bazara import BazaraAPI
from api.api_upcitemdb import UPCitemdbAPI
from api.api_sixty60 import Sixty60API


class ProductForm(Popup):
    # Constantes de cores
    COLOR_PRIMARY = (0.2, 0.6, 0.86, 1)
    COLOR_SUCCESS = (0.27, 0.7, 0.42, 1)
    COLOR_ERROR = (0.85, 0.35, 0.35, 1)
    COLOR_WARNING = (0.85, 0.45, 0.3, 1)
    COLOR_GRAY = (0.65, 0.65, 0.65, 1)
    COLOR_LIGHT_GRAY = (0.88, 0.88, 0.88, 1)
    COLOR_TEXT = (0.25, 0.25, 0.25, 1)
    COLOR_CARD = (0.88, 0.88, 0.88, 1)
    COLOR_CARD_ALT = (0.92, 0.92, 0.92, 1)
    
    # Constantes de tamanhos
    FIELD_HEIGHT = dp(40)
    BUTTON_HEIGHT = dp(44)
    FONT_SIZE = sp(15)
    FONT_SIZE_SMALL = sp(13)
    
    def __init__(self, admin_screen, product=None, **kwargs):
        super().__init__(**kwargs)

        self.admin_screen = admin_screen
        self.product = product

        self.scanning = False
        self.camera_capture = None
        self.current_camera = 0
        self.last_barcode = None
        self.last_barcode_time = 0

        self.beep_sound = self._load_beep_sound()

        self.api_manager = APIManager(
            database=admin_screen.db,
            on_success=self._on_api_success,
            on_failure=self._on_api_failure,
            on_status=self._on_api_status,
        )
        self._apply_theme_tokens()

        self._category_sources = [
            ("Bazara", BazaraAPI()),
            ("Open Food Facts", OpenFoodFactsAPI()),
            ("UPCitemdb", UPCitemdbAPI()),
            ("Sixty60", Sixty60API()),
        ]
        self._category_lookup_inflight = False
        self._category_lookup_barcode = None
        self._category_lookup_token = 0
        
        # Flag para evitar loops infinitos de cálculo
        self._calculating = False
        # Auto cálculo deve ocorrer apenas uma vez por sessão de formulário
        self._auto_calc_done = False

        self._setup_popup()
        self._build_ui()

        if self.product:
            self._populate_fields()

        Window.bind(on_resize=self._on_window_resize)

    def _setup_popup(self):
        self.title = ""
        self.size_hint = (None, None)
        self.auto_dismiss = False
        self.background = 'data/images/defaulttheme/transparent.png'
        self.background_color = (0, 0, 0, 0)
        self.separator_height = 0
        self.title_size = 0
        self._apply_popup_size()

    def _apply_theme_tokens(self):
        app = App.get_running_app()
        tokens = getattr(app, "theme_tokens", {}) if app else {}
        self.COLOR_PRIMARY = tokens.get("primary", self.COLOR_PRIMARY)
        self.COLOR_SUCCESS = tokens.get("success", self.COLOR_SUCCESS)
        self.COLOR_ERROR = tokens.get("danger", self.COLOR_ERROR)
        self.COLOR_WARNING = tokens.get("warning", self.COLOR_WARNING)
        self.COLOR_GRAY = tokens.get("text_secondary", self.COLOR_GRAY)
        self.COLOR_CARD = tokens.get("card", self.COLOR_CARD)
        self.COLOR_CARD_ALT = tokens.get("card_alt", self.COLOR_CARD_ALT)
        self.COLOR_LIGHT_GRAY = self.COLOR_CARD_ALT
        self.COLOR_TEXT = tokens.get("text_primary", self.COLOR_TEXT)

        theme_style = getattr(getattr(app, "theme_cls", None), "theme_style", "Light") if app else "Light"
        if theme_style == "Dark":
            # Garantir contraste legível mesmo quando tokens não estão definidos
            if self.COLOR_TEXT[0] < 0.6:
                self.COLOR_TEXT = (0.95, 0.95, 0.96, 1)
            if self.COLOR_GRAY[0] < 0.6:
                self.COLOR_GRAY = (0.78, 0.78, 0.82, 1)
            if self.COLOR_CARD[0] > 0.4:
                self.COLOR_CARD = (0.16, 0.17, 0.2, 1)
            if self.COLOR_CARD_ALT[0] > 0.45:
                self.COLOR_CARD_ALT = (0.2, 0.22, 0.25, 1)
            self.COLOR_LIGHT_GRAY = self.COLOR_CARD_ALT

    def _style_text_field(self, field):
        field.line_color_normal = (0, 0, 0, 0)
        field.line_color_focus = (
            self.COLOR_PRIMARY[0],
            self.COLOR_PRIMARY[1],
            self.COLOR_PRIMARY[2],
            0.7,
        )
        field.text_color = self.COLOR_TEXT
        field.text_color_normal = self.COLOR_TEXT
        field.text_color_focus = self.COLOR_TEXT
        field.hint_text_color = self.COLOR_GRAY
        if hasattr(field, "cursor_color"):
            field.cursor_color = self.COLOR_TEXT

    def _apply_popup_size(self):
        w, h = Window.size
        self.size = (min(dp(950), w * 0.85), min(dp(720), h * 0.88))

    def _build_ui(self):
        # Container principal com card
        main_card = MDCard(
            orientation='vertical',
            padding=0,
            spacing=0,
            radius=[dp(16)],
            md_bg_color=self.COLOR_CARD,
            elevation=0
        )

        # Header
        header = self._build_header()
        main_card.add_widget(header)

        # Content
        content = BoxLayout(orientation='horizontal', spacing=dp(20), padding=[dp(20), dp(16), dp(20), dp(20)])
        content.add_widget(self._build_camera_section())
        content.add_widget(self._build_form_section())
        main_card.add_widget(content)

        self.content = main_card

    def _build_header(self):
        header = MDCard(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(56),
            padding=[dp(20), dp(10)],
            radius=[dp(16), dp(16), 0, 0],
            md_bg_color=self.COLOR_CARD,
            elevation=2
        )

        title_text = "Adicionar Produto" if not self.product else "Editar Produto"
        title_label = Label(
            text=title_text,
            color=self.COLOR_TEXT,
            font_size=sp(20),
            bold=True,
            halign='left',
            valign='middle',
            size_hint_x=0.9
        )
        title_label.bind(size=title_label.setter('text_size'))

        close_btn = MDIconButton(
            icon='close',
            theme_text_color='Custom',
            text_color=self.COLOR_TEXT,
            on_release=self.dismiss,
            pos_hint={'center_y': 0.5}
        )

        header.add_widget(title_label)
        header.add_widget(close_btn)

        return header

    def _build_camera_section(self):
        section = BoxLayout(orientation='vertical', size_hint_x=0.36, spacing=dp(10))

        section.add_widget(self._create_section_title('Scanner de Código'))

        # Card para a câmera
        camera_card = MDCard(
            size_hint_y=0.62,
            radius=[dp(12)],
            md_bg_color=self.COLOR_PRIMARY,
            elevation=3
        )

        self.camera_image = Image(allow_stretch=True, keep_ratio=True)
        camera_card.add_widget(self.camera_image)
        section.add_widget(camera_card)

        self.scanner_status = Label(
            text='',
            size_hint_y=None,
            height=dp(24),
            color=self.COLOR_GRAY,
            font_size=sp(14),
            bold=True,
            halign='center',
            valign='middle'
        )
        section.add_widget(self.scanner_status)

        # Botões (centralizados)
        btn_row = BoxLayout(size_hint=(None, None), height=dp(40), width=dp(80), spacing=dp(10))

        self.scan_btn = MDIconButton(
            icon='barcode-scan',
            theme_text_color='Custom',
            text_color=(1, 1, 1, 1),
            md_bg_color=self.COLOR_PRIMARY,
            size_hint=(None, None),
            size=(dp(40), dp(40)),
            on_release=self._toggle_scanner,
        )

        switch_btn = MDIconButton(
            icon='camera-switch',
            theme_text_color='Custom',
            text_color=(1, 1, 1, 1),
            md_bg_color=self.COLOR_GRAY,
            size_hint=(None, None),
            size=(dp(40), dp(40)),
            on_release=self._switch_camera,
        )

        btn_row.add_widget(self.scan_btn)
        btn_row.add_widget(switch_btn)

        btn_wrapper = AnchorLayout(size_hint_y=None, height=dp(40))
        btn_wrapper.add_widget(btn_row)
        section.add_widget(btn_wrapper)

        section.add_widget(Label(
            text='Posicione o código de barras na câmera',
            size_hint_y=None,
            height=dp(32),
            color=self.COLOR_GRAY,
            font_size=sp(15),
            halign='center',
            valign='middle'
        ))

        return section

    def _create_section_title(self, text):
        """Cria um título de seção padronizado"""
        return Label(
            text=text,
            size_hint_y=None,
            height=dp(28),
            color=self.COLOR_TEXT,
            font_size=sp(28),
            bold=True,
            halign='center',
            valign='middle'
        )

    def _build_form_section(self):
        section = BoxLayout(orientation='vertical', size_hint_x=0.64, spacing=dp(8))

        section.add_widget(self._create_section_title('Informações do Produto'))

        self._create_form_fields()

        scroll = MDScrollView(
            size_hint_y=0.8,
            do_scroll_x=False,
            bar_width=dp(6),
            bar_color=(self.COLOR_PRIMARY[0], self.COLOR_PRIMARY[1], self.COLOR_PRIMARY[2], 0.8)
        )
        scroll.add_widget(self._build_fields_grid())
        section.add_widget(scroll)

        section.add_widget(self._build_action_buttons())
        return section

    def _create_form_fields(self):
        h = self.FIELD_HEIGHT
        fs = self.FONT_SIZE

        # Campos MDTextField
        self.barcode_input = MDTextField(
            hint_text="Código de barras",
            mode="rectangle",
            size_hint_y=None,
            height=h,
            font_size=fs,
            line_color_focus=self.COLOR_PRIMARY,
            line_color_normal=(0.6, 0.6, 0.6, 0.5)
        )
        self._style_text_field(self.barcode_input)
        self.barcode_input.bind(on_text_validate=self._on_barcode_manual_entry)

        # Campo de data com ícone de calendário
        self.expiry_date_layout = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=h,
            spacing=dp(4)
        )
        
        self.expiry_date = MDTextField(
            hint_text="DD/MM/AAAA",
            mode="rectangle",
            size_hint_x=0.82,
            font_size=fs,
            line_color_focus=self.COLOR_PRIMARY,
            line_color_normal=(0.6, 0.6, 0.6, 0.5)
        )
        self._style_text_field(self.expiry_date)
        
        calendar_btn = MDIconButton(
            icon='calendar',
            theme_text_color='Custom',
            text_color=self.COLOR_PRIMARY,
            size_hint=(None, None),
            size=(dp(36), dp(36)),
            pos_hint={'center_y': 0.5},
            on_release=self._show_date_picker
        )
        
        self.expiry_date_layout.add_widget(self.expiry_date)
        self.expiry_date_layout.add_widget(calendar_btn)

        self.description = MDTextField(
            hint_text="Nome do produto *",
            mode="rectangle",
            size_hint_y=None,
            height=h,
            font_size=fs,
            line_color_focus=self.COLOR_PRIMARY,
            line_color_normal=(0.6, 0.6, 0.6, 0.5)
        )
        self._style_text_field(self.description)
        # Converter para maiúsculas enquanto digita
        self.description.bind(text=self._on_description_text)

        # Category com dropdown
        self.category_layout = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=h,
            spacing=dp(4)
        )

        self.category_field = MDTextField(
            hint_text="Categoria *",
            mode="rectangle",
            size_hint_x=0.74,
            font_size=fs,
            readonly=False,
            line_color_focus=self.COLOR_PRIMARY,
            line_color_normal=(0.6, 0.6, 0.6, 0.5)
        )
        self._style_text_field(self.category_field)

        dropdown_btn = MDIconButton(
            icon='menu-down',
            theme_text_color='Custom',
            text_color=(1, 1, 1, 1),
            md_bg_color=self.COLOR_PRIMARY,
            size_hint=(None, None),
            size=(dp(36), dp(36)),
            pos_hint={'center_y': 0.5},
            on_release=self._open_category_menu
        )

        add_cat_btn = MDIconButton(
            icon='plus',
            theme_text_color='Custom',
            text_color=(1, 1, 1, 1),
            md_bg_color=self.COLOR_PRIMARY,
            size_hint=(None, None),
            size=(dp(36), dp(36)),
            pos_hint={'center_y': 0.5},
            on_release=self._show_category_form
        )

        # Menu dropdown para categorias
        categories = [c for c in self._get_admin_categories() if c != 'Todas']
        menu_items = [{"text": cat, "on_release": lambda x=cat: self._set_category_menu(x)} for cat in categories]

        self.category_menu = MDDropdownMenu(
            caller=dropdown_btn,
            items=menu_items,
            width_mult=3.5,
            max_height=dp(250),
            position="bottom"
        )

        self.category_layout.add_widget(self.category_field)
        self.category_layout.add_widget(dropdown_btn)
        self.category_layout.add_widget(add_cat_btn)

        self.package_quantity = MDTextField(
            hint_text="Ex: 500 ml, 1.5 L, 250 g",
            mode="rectangle",
            size_hint_y=None,
            height=h,
            font_size=fs,
            line_color_focus=self.COLOR_PRIMARY,
            line_color_normal=(0.6, 0.6, 0.6, 0.5)
        )
        self._style_text_field(self.package_quantity)

        # Stock fields
        self.existing_stock = MDTextField(
            hint_text="Estoque Existente *",
            mode="rectangle",
            size_hint_y=None,
            height=h,
            font_size=fs,
            input_filter='float',
            line_color_focus=self.COLOR_PRIMARY,
            line_color_normal=(0.6, 0.6, 0.6, 0.5)
        )
        self._style_text_field(self.existing_stock)

        self.sold_stock = MDTextField(
            hint_text="Estoque Vendido",
            mode="rectangle",
            size_hint_y=None,
            height=h,
            font_size=fs,
            text="0",
            readonly=True,
            line_color_focus=self.COLOR_PRIMARY,
            line_color_normal=(0.6, 0.6, 0.6, 0.5)
        )
        self._style_text_field(self.sold_stock)

        # Weight switch - layout horizontal compacto
        self.weight_switch_layout = BoxLayout(
            orientation='horizontal',
            size_hint_y=None, 
            height=h, 
            spacing=dp(4)
        )
        
        # Apenas o switch, sem label (o label está na coluna esquerda do grid)
        self.is_sold_by_weight_switch = MDSwitch(
            size_hint=(None, None),
            size=(dp(50), dp(30)),
            active=False,
            pos_hint={'center_y': 0.5},
            thumb_color_active=self.COLOR_PRIMARY,
            track_color_active=(self.COLOR_PRIMARY[0], self.COLOR_PRIMARY[1], self.COLOR_PRIMARY[2], 0.5),
            thumb_color_inactive=(0.8, 0.8, 0.8, 1),
            track_color_inactive=(0.6, 0.6, 0.6, 0.3)
        )
        
        self.weight_switch_layout.add_widget(self.is_sold_by_weight_switch)
        # Adicionar espaço em branco para alinhar à esquerda
        self.weight_switch_layout.add_widget(Label())

        # Price fields
        self.sale_price = MDTextField(
            hint_text="Preço de Venda *",
            mode="rectangle",
            size_hint_y=None,
            height=h,
            font_size=fs,
            input_filter='float',
            line_color_focus=self.COLOR_PRIMARY,
            line_color_normal=(0.6, 0.6, 0.6, 0.5)
        )
        self._style_text_field(self.sale_price)

        self.total_purchase_price = MDTextField(
            hint_text="Preço Compra Total *",
            mode="rectangle",
            size_hint_y=None,
            height=h,
            font_size=fs,
            input_filter='float',
            line_color_focus=self.COLOR_PRIMARY,
            line_color_normal=(0.6, 0.6, 0.6, 0.5)
        )
        self._style_text_field(self.total_purchase_price)

        self.unit_purchase_price = MDTextField(
            hint_text="Preço Compra Unit. *",
            mode="rectangle",
            size_hint_y=None,
            height=h,
            font_size=fs,
            input_filter='float',
            line_color_focus=self.COLOR_PRIMARY,
            line_color_normal=(0.6, 0.6, 0.6, 0.5)
        )
        self._style_text_field(self.unit_purchase_price)
        
        # Bindings para cálculo automático
        self.existing_stock.bind(text=self._on_stock_or_price_change)
        self.total_purchase_price.bind(text=self._on_total_price_change)
        self.unit_purchase_price.bind(text=self._on_unit_price_change)

    def _on_total_price_change(self, instance, value):
        """Calcula o preço unitário quando o preço total muda"""
        if self._calculating or self._auto_calc_done:
            return
            
        self._calculating = True
        try:
            total = value.strip()
            stock = self.existing_stock.text.strip()
            
            if total and stock and not self.unit_purchase_price.text.strip():
                try:
                    total_val = float(total)
                    stock_val = float(stock)
                    
                    if stock_val > 0:
                        unit_price = total_val / stock_val
                        self.unit_purchase_price.text = f"{unit_price:.2f}"
                        self._auto_calc_done = True
                        # Sugerir preço de venda se estiver vazio
                        self._suggest_sale_price(unit_price)
                except ValueError:
                    pass
        finally:
            self._calculating = False
    
    def _on_unit_price_change(self, instance, value):
        """Calcula o preço total quando o preço unitário muda"""
        if self._calculating or self._auto_calc_done:
            return
            
        self._calculating = True
        try:
            unit = value.strip()
            stock = self.existing_stock.text.strip()
            
            if unit and stock and not self.total_purchase_price.text.strip():
                try:
                    unit_val = float(unit)
                    stock_val = float(stock)
                    
                    if stock_val > 0:
                        total_price = unit_val * stock_val
                        self.total_purchase_price.text = f"{total_price:.2f}"
                        self._auto_calc_done = True
                        # Sugerir preço de venda se estiver vazio
                        self._suggest_sale_price(unit_val)
                except ValueError:
                    pass
        finally:
            self._calculating = False
    
    def _on_stock_or_price_change(self, instance, value):
        """Recalcula quando o estoque muda"""
        if self._calculating or self._auto_calc_done:
            return
            
        stock = value.strip()
        
        # Se tem preço total, recalcula o unitário
        if self.total_purchase_price.text.strip() and stock:
            self._on_total_price_change(self.total_purchase_price, self.total_purchase_price.text)
        # Se tem preço unitário, recalcula o total
        elif self.unit_purchase_price.text.strip() and stock:
            self._on_unit_price_change(self.unit_purchase_price, self.unit_purchase_price.text)
    
    def _suggest_sale_price(self, unit_cost):
        """Sugere um preço de venda com margem de lucro se o campo estiver vazio"""
        if not self.sale_price.text.strip():
            try:
                # Margem de lucro sugerida: 30%
                suggested_price = unit_cost * 1.30
                self.sale_price.text = f"{suggested_price:.2f}"
            except:
                pass

    def _show_date_picker(self, instance):
        """Mostra o seletor de data"""
        # Data inicial: se já tem data no campo, usar ela; senão, data atual
        initial_date = datetime.now()
        
        if self.expiry_date.text.strip():
            try:
                initial_date = datetime.strptime(self.expiry_date.text.strip(), "%d/%m/%Y")
            except ValueError:
                pass
        
        date_dialog = MDDatePicker(
            year=initial_date.year,
            month=initial_date.month,
            day=initial_date.day
        )
        date_dialog.bind(on_save=self._on_date_selected)
        date_dialog.open()
    
    def _on_date_selected(self, instance, value, date_range):
        """Callback quando uma data é selecionada no calendário"""
        # value é um objeto datetime.date
        self.expiry_date.text = value.strftime("%d/%m/%Y")

    def _on_description_text(self, instance, value):
        """Converte o texto da descrição para maiúsculas"""
        if value != value.upper():
            # Salvar posição do cursor
            cursor_pos = instance.cursor
            # Converter para maiúsculas
            instance.text = value.upper()
            # Restaurar posição do cursor
            instance.cursor = cursor_pos
    
    def _set_category_menu(self, category):
        """Define a categoria selecionada do menu"""
        self.category_field.text = category
        self.category_menu.dismiss()

    def _get_admin_categories(self):
        if hasattr(self.admin_screen, "get_categories"):
            return self.admin_screen.get_categories()
        if hasattr(self.admin_screen, "products"):
            categories = {p[11] for p in self.admin_screen.products if len(p) > 11 and p[11]}
            return sorted(categories)
        return []

    def _build_fields_grid(self):
        grid = GridLayout(
            cols=2,
            spacing=[dp(14), dp(10)],
            size_hint_y=None,
            padding=[0, 0, dp(4), dp(10)]
        )
        grid.bind(minimum_height=grid.setter('height'))

        label_h = dp(40)
        label_fs = sp(14)
        

        fields = [
            ("Código de Barras:", self.barcode_input),
            ("Data de Validade:", self.expiry_date_layout),
            ("Nome do Produto:", self.description),
            ("Categoria:", self.category_layout),
            ("Quantidade:", self.package_quantity),
            ("Estoque Existente:", self.existing_stock),
            ("Estoque Vendido:", self.sold_stock),
            ("Vendido por Peso (KG)", self.weight_switch_layout),
            ("Preço Compra Unit.:", self.unit_purchase_price),
            ("Preço de Venda:", self.sale_price),
            ("Preço Compra Total:", self.total_purchase_price),
        ]

        for text, widget in fields:
            label = Label(
                text=text,
                size_hint_y=None,
                height=label_h,
                halign='left',
                valign='middle',
                text_size=(dp(140), None),
                bold=True,
                font_size=label_fs,
                color=self.COLOR_TEXT
            )
            grid.add_widget(label)
            grid.add_widget(widget)

        return grid

    def _build_action_buttons(self):
        layout = BoxLayout(
            spacing=dp(10),
            size_hint_y=None,
            height=self.BUTTON_HEIGHT,
            padding=[0, dp(8), 0, 0]
        )

        # Adicionar espaço à esquerda para empurrar botões para direita
        layout.add_widget(Label(size_hint_x=0.4))

        cancel_btn = MDFlatButton(
            text="Cancelar",
            theme_text_color='Custom',
            text_color=self.COLOR_TEXT,
            md_bg_color=self.COLOR_CARD_ALT,
            font_size=self.FONT_SIZE,
            size_hint_x=0.3,
            on_release=self.dismiss
        )

        save_btn = MDRaisedButton(
            text="Cadastrar",
            md_bg_color=self.COLOR_SUCCESS,
            font_size=self.FONT_SIZE,
            size_hint_x=0.3,
            on_release=self._save_product
            
        )

        layout.add_widget(cancel_btn)
        layout.add_widget(save_btn)
        return layout

    def _on_api_success(self, source: str, data: dict):
        self._set_status(f"Encontrado: {source}", self.COLOR_PRIMARY)
        self._fill_fields(data)
        self._show_snackbar(f"Dados carregados de {source}", self.COLOR_SUCCESS)

    def _on_api_partial(self, source: str, data: dict):
        self._set_status(f"Encontrado: {source} (completando dados...)", self.COLOR_PRIMARY)
        if data:
            self._fill_fields(data)

    def _on_api_complete(self, data: dict):
        if not data or not data.get("source_chain"):
            self._on_api_failure()
            return
        self._fill_fields(data)
        self._set_status("Dados atualizados", self.COLOR_SUCCESS)
        self._show_snackbar("Dados atualizados", self.COLOR_SUCCESS)

    def _on_api_failure(self):
        self._set_status("Scanner    Ativo", self.COLOR_GRAY)
        barcode = self.barcode_input.text.strip()
        self._show_snackbar(f"Produto '{barcode}' não encontrado", self.COLOR_ERROR)

    def _on_api_status(self, message: str):
        self._set_status(message, self.COLOR_PRIMARY)

    def _fill_fields(self, data: dict):
        name = data.get("name", "")
        brand = data.get("brand", "")

        if name and not self.description.text.strip():
            if brand and brand.lower() not in name.lower():
                self.description.text = f"{brand} - {name}"
            else:
                self.description.text = name

        category = data.get("category")
        if category and not self.category_field.text.strip():
            self._set_category(category)
        elif not self.category_field.text.strip():
            inferred = self._infer_category_from_name(self.description.text or name)
            if inferred:
                self._set_category(inferred)
                self._register_generated_category(inferred)

        quantity = data.get("quantity", "")
        if not quantity:
            quantity = self._extract_quantity_from_text(data.get("name", ""))
        if not quantity and self.description.text.strip():
            quantity = self._extract_quantity_from_text(self.description.text)
        if quantity and not self.package_quantity.text.strip():
            self.package_quantity.text = str(quantity)

        price = data.get("price", "")
        if price and not self.sale_price.text.strip():
            self.sale_price.text = str(price)

        expiry = data.get("expiry_date", "")
        if expiry and not self.expiry_date.text.strip():
            self.expiry_date.text = expiry

        if data.get("sold_by_weight"):
            self.is_sold_by_weight_switch.active = True

    def _set_category(self, category_name: str):
        # Atualizar items do menu e campo
        categories = [c for c in self._get_admin_categories() if c != 'Todas']

        for cat in categories:
            if cat.lower() == category_name.lower():
                self.category_field.text = cat
                return
            if cat.lower() in category_name.lower() or category_name.lower() in cat.lower():
                self.category_field.text = cat
                return
        self.category_field.text = category_name

    @staticmethod
    def _normalize_text(text: str) -> str:
        if not text:
            return ""
        text = unicodedata.normalize("NFD", str(text))
        text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
        return text.lower()

    def _generate_category_candidates(self, name: str) -> list[str]:
        if not name:
            return []
        norm = self._normalize_text(name)
        if not norm:
            return []

        categories = [c for c in self._get_admin_categories() if c != "Todas"]
        candidates = []

        # Priorizar categorias existentes que aparecem no nome
        for cat in categories:
            cat_norm = self._normalize_text(cat)
            if cat_norm and cat_norm in norm and cat not in candidates:
                candidates.append(cat)

        keyword_map = {
            "Bebidas": ["agua", "água", "sumo", "suco", "refrigerante", "cerveja", "vinho", "whisky", "vodka", "energ", "bebida"],
            "Laticínios": ["leite", "iogurte", "queijo", "manteiga", "nata"],
            "Higiene": ["sabonete", "champô", "shampoo", "pasta", "dente", "desodorizante", "desodorante", "fralda"],
            "Limpeza": ["detergente", "lixivia", "lixívia", "cloro", "amaciante", "sabao", "sabão", "desinfetante", "desinfetante"],
            "Mercearia": ["arroz", "farinha", "acucar", "açúcar", "oleo", "óleo", "massa", "feijao", "feijão", "sal", "cafe", "café"],
            "Snacks": ["bolacha", "biscoito", "chips", "snack", "salgadinho"],
            "Congelados": ["congelado", "gelo", "ice"],
        }

        for cat, keywords in keyword_map.items():
            for kw in keywords:
                kw_norm = self._normalize_text(kw)
                if kw_norm and kw_norm in norm:
                    if cat not in candidates:
                        candidates.append(cat)
                    break

        return candidates

    def _infer_category_from_name(self, name: str) -> str | None:
        candidates = self._generate_category_candidates(name)
        return candidates[0] if candidates else None

    def _register_generated_category(self, category: str):
        if not category:
            return
        categories = [c for c in self._get_admin_categories() if c != "Todas"]
        if category not in categories and hasattr(self.admin_screen, "register_category"):
            self.admin_screen.register_category(category)

    @staticmethod
    def _extract_quantity_from_text(text: str) -> str | None:
        if not text:
            return None

        pattern = re.compile(r"(?i)\b(\d+(?:[.,]\d+)?\s*x\s*)?\d+(?:[.,]\d+)?\s*(ml|l|lt|lts|litro|litros|g|kg|grama|gramas|mg|cl|dl|un|unid|unidade|unidades)\b")
        match = pattern.search(text)
        if not match:
            return None

        return " ".join(match.group(0).split())

    def _open_category_menu(self, instance):
        categories = [c for c in self._get_admin_categories() if c != 'Todas']
        menu_items = [{"text": cat, "on_release": lambda x=cat: self._set_category_menu(x)} for cat in categories]
        self.category_menu.items = menu_items
        self.category_menu.width_mult = 3.5
        self.category_menu.max_height = dp(250)
        self.category_menu.open()

    def _toggle_scanner(self, instance):
        if not self.scanning:
            self.scanning = True
            self.scan_btn.icon = 'barcode-off'
            self.scan_btn.md_bg_color = self.COLOR_ERROR
            self._set_status("Scanner   Ativo", self.COLOR_PRIMARY)
            Clock.schedule_interval(self._update_camera, 1.0 / 15.0)
        else:
            self._stop_scanner()

    def _stop_scanner(self):
        self.scanning = False
        self.scan_btn.icon = 'barcode-scan'
        self.scan_btn.md_bg_color = self.COLOR_PRIMARY
        self._set_status("Scanner   Inativo", self.COLOR_GRAY)
        Clock.unschedule(self._update_camera)

        if self.camera_capture:
            self.camera_capture.release()
            self.camera_capture = None

        self.camera_image.texture = None

    def _update_camera(self, dt):
        if not self.scanning:
            return

        if self.camera_capture is None:
            if not self._init_camera():
                return

        ret, frame = self.camera_capture.read()
        if not ret:
            return

        frame = self._process_frame(frame)
        self._display_frame(frame)

    def _init_camera(self) -> bool:
        try:
            self.camera_capture = cv2.VideoCapture(self.current_camera)
            self.camera_capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.camera_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

            if not self.camera_capture.isOpened():
                self._set_status("Erro na Câmera", self.COLOR_ERROR)
                self._stop_scanner()
                return False

            self.last_barcode = None
            self.last_barcode_time = 0
            return True

        except Exception as e:
            print(f"[Scanner] Erro ao inicializar câmera: {e}")
            return False

    def _process_frame(self, frame) -> np.ndarray:
        current_time = time.time()
        frame = cv2.convertScaleAbs(frame, alpha=1.2, beta=10)
        codes = decode(frame)

        for code in codes:
            try:
                barcode_raw = code.data.decode('utf-8')
                barcode_value = ''.join(c for c in barcode_raw if c.isprintable()).strip()

                if barcode_value == self.last_barcode and (current_time - self.last_barcode_time) < 2:
                    continue

                self.last_barcode = barcode_value
                self.last_barcode_time = current_time

                self.barcode_input.text = barcode_value
                self._play_beep()
                self._set_status("Código Detectado", self.COLOR_SUCCESS)

                if not self.api_manager.is_loading:
                    self.api_manager.search_enriched(
                        barcode_value,
                        on_partial=self._on_api_partial,
                        on_complete=self._on_api_complete,
                    )

                if len(code.polygon) == 4:
                    pts = np.array([(p.x, p.y) for p in code.polygon], dtype=np.int32)
                    cv2.polylines(frame, [pts], True, (0, 255, 0), 3)

                x, y, w, h = code.rect
                cv2.putText(frame, barcode_value, (x, y - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

            except Exception as e:
                print(f"[Scanner] Erro ao processar código: {e}")

        if not codes and (current_time - self.last_barcode_time) > 2.5:
            if not self.api_manager.is_loading:
                self._set_status("Scanner   Ativo", self.COLOR_PRIMARY)

        return frame

    def _display_frame(self, frame: np.ndarray):
        buf = cv2.flip(frame, 0).tobytes()
        texture = Texture.create(size=(frame.shape[1], frame.shape[0]), colorfmt='bgr')
        texture.blit_buffer(buf, colorfmt='bgr', bufferfmt='ubyte')
        self.camera_image.texture = texture

    def _switch_camera(self, instance):
        was_scanning = self.scanning

        if self.scanning:
            self._stop_scanner()

        self.current_camera = (self.current_camera + 1) % 3
        self._show_snackbar(f'Trocado para Câmera {self.current_camera}', self.COLOR_PRIMARY)

        if was_scanning:
            Clock.schedule_once(lambda dt: self._restart_scanner(), 0.3)

    def _restart_scanner(self):
        self.scanning = True
        self.scan_btn.icon = 'barcode-off'
        self.scan_btn.md_bg_color = self.COLOR_ERROR
        self._set_status("Scanner   Ativo", self.COLOR_PRIMARY)
        Clock.schedule_interval(self._update_camera, 1.0 / 15.0)

    def _on_barcode_manual_entry(self, instance):
        barcode = instance.text.strip()
        if barcode and len(barcode) >= 8:
            self.api_manager.search_enriched(
                barcode,
                on_partial=self._on_api_partial,
                on_complete=self._on_api_complete,
            )

    def _search_category_if_missing(self, barcode: str):
        if not barcode or len(barcode) < 8:
            return

        needs_category = not self.category_field.text.strip()
        needs_quantity = not self.package_quantity.text.strip()
        if not (needs_category or needs_quantity):
            return

        self._category_lookup_token += 1
        token = self._category_lookup_token
        self._category_lookup_barcode = barcode
        self._category_lookup_inflight = True

        Thread(
            target=self._category_lookup_worker,
            args=(barcode, token, needs_category, needs_quantity),
            daemon=True
        ).start()

    def _category_lookup_worker(self, barcode: str, token: int, needs_category: bool, needs_quantity: bool):
        found_category = False
        found_quantity = False

        for source_name, api in self._category_sources:
            try:
                result = api.fetch(barcode)
            except Exception:
                result = None

            if not result:
                continue

            new_category = None
            new_quantity = None

            if needs_category and not found_category:
                category = result.get("category")
                if category:
                    found_category = True
                    new_category = category

            if needs_quantity and not found_quantity:
                quantity = result.get("quantity") or self._extract_quantity_from_text(result.get("name", ""))
                if quantity:
                    found_quantity = True
                    new_quantity = quantity

            if new_category or new_quantity:
                Clock.schedule_once(
                    lambda dt, c=new_category, q=new_quantity, t=token, b=barcode: self._apply_lookup_from_api(c, q, t, b),
                    0
                )

            if (not needs_category or found_category) and (not needs_quantity or found_quantity):
                break

        Clock.schedule_once(lambda dt, t=token, b=barcode: self._category_lookup_done(t, b), 0)

    def _apply_lookup_from_api(self, category: str | None, quantity: str | None, token: int, barcode: str):
        if token != self._category_lookup_token or barcode != self._category_lookup_barcode:
            return

        if category and not self.category_field.text.strip():
            self._set_category(category)

        if quantity and not self.package_quantity.text.strip():
            self.package_quantity.text = str(quantity)

    def _category_lookup_done(self, token: int, barcode: str):
        if token == self._category_lookup_token and barcode == self._category_lookup_barcode:
            self._category_lookup_inflight = False

    def _show_category_form(self, instance):
        # Content card
        content = MDCard(
            orientation='vertical',
            padding=[dp(24), dp(20)],
            spacing=dp(14),
            radius=[dp(12)],
            md_bg_color=self.COLOR_CARD,
            size_hint_y=None,
            height=dp(180)
        )

        content.add_widget(Label(
            text='Adicionar Categoria',
            color=self.COLOR_TEXT,
            font_size=sp(16),
            bold=True,
            halign='center',
            valign='middle',
            size_hint_y=None,
            height=dp(28)
        ))

        category_input = MDTextField(
            hint_text='Ex: Eletrônicos, Alimentos...',
            mode="rectangle",
            font_size=self.FONT_SIZE,
            size_hint_y=None,
            height=self.FIELD_HEIGHT,
            line_color_focus=self.COLOR_PRIMARY
        )
        self._style_text_field(category_input)
        content.add_widget(category_input)

        btn_row = BoxLayout(size_hint_y=None, height=self.FIELD_HEIGHT, spacing=dp(10))

        cancel_btn = MDFlatButton(
            text='Cancelar',
            theme_text_color='Custom',
            text_color=self.COLOR_TEXT,
            md_bg_color=self.COLOR_CARD_ALT,
            font_size=self.FONT_SIZE
        )

        add_btn = MDRaisedButton(
            text='Adicionar',
            md_bg_color=self.COLOR_SUCCESS,
            font_size=self.FONT_SIZE
        )

        popup = Popup(
            content=content,
            size_hint=(None, None),
            size=(dp(400), dp(250)),
            auto_dismiss=False,
            background='data/images/defaulttheme/transparent.png',
            background_color=(0, 0, 0, 0),
            separator_height=0,
            title='',
            title_size=0
        )

        def on_add(instance):
            new_cat = category_input.text.strip()
            if not new_cat:
                self._show_snackbar("Digite um nome para a categoria!", self.COLOR_ERROR)
                return

            # Atualizar menu dropdown
            categories = [c for c in self._get_admin_categories() if c != 'Todas']
            
            if new_cat in categories:
                self._show_snackbar("Esta categoria já existe!", self.COLOR_WARNING)
                return

            categories.append(new_cat)
            categories = sorted(categories)
            
            # Atualizar menu items
            menu_items = [{"text": cat, "on_release": lambda x=cat: self._set_category_menu(x)} for cat in categories]
            self.category_menu.items = menu_items
            self.category_menu.width_mult = 3.5
            self.category_menu.max_height = dp(250)
            self.category_field.text = new_cat

            if hasattr(self.admin_screen, "register_category"):
                self.admin_screen.register_category(new_cat)

            popup.dismiss()
            self._show_snackbar(f"Categoria '{new_cat}' adicionada!", self.COLOR_SUCCESS)

        cancel_btn.bind(on_release=popup.dismiss)
        add_btn.bind(on_release=on_add)
        btn_row.add_widget(cancel_btn)
        btn_row.add_widget(add_btn)
        content.add_widget(btn_row)

        popup.open()

    def _save_product(self, instance):
        if not self._validate_fields():
            return

        expiry = self._process_expiry_date()
        if expiry is False:
            return

        barcode_text = self.barcode_input.text.strip()
        barcode = ''.join(c for c in barcode_text if c.isprintable()).strip() if barcode_text else None

        self._save_to_database(barcode, expiry, self.is_sold_by_weight_switch.active)

    def _validate_fields(self) -> bool:
        validations = [
            (self.description.text.strip(), "A descrição é obrigatória!"),
            (self.category_field.text.strip() and self.category_field.text != "Categoria *", "Selecione uma categoria!"),
            (self.existing_stock.text.strip(), "O estoque existente é obrigatório!"),
            (self.sale_price.text.strip(), "O preço de venda é obrigatório!"),
            (self.total_purchase_price.text.strip(), "O preço de compra total é obrigatório!"),
            (self.unit_purchase_price.text.strip(), "O preço de compra unitário é obrigatório!"),
        ]
        for condition, message in validations:
            if not condition:
                self._show_snackbar(message, self.COLOR_ERROR)
                return False
        return True

    def _process_expiry_date(self):
        text = self.expiry_date.text.strip()
        if not text:
            return None

        try:
            dt = datetime.strptime(text, "%d/%m/%Y")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            self._show_snackbar("Data de validade inválida! Use DD/MM/AAAA", self.COLOR_ERROR)
            return False

    def _save_to_database(self, barcode, expiry, is_sold_by_weight):
        from database.database import Database
        db = Database()

        package_quantity = self.package_quantity.text.strip() or None

        try:
            if self.product:
                db.update_product(
                    self.product[0],
                    self.description.text.strip(),
                    self.category_field.text,
                    float(self.existing_stock.text),
                    float(self.sold_stock.text),
                    float(self.sale_price.text),
                    float(self.total_purchase_price.text),
                    float(self.unit_purchase_price.text),
                    barcode, expiry, is_sold_by_weight, package_quantity=package_quantity
                )
                self._show_snackbar("Produto atualizado com sucesso!", self.COLOR_SUCCESS)
                Clock.schedule_once(lambda dt: self.dismiss(), 1.5)
            else:
                db.add_product(
                    self.description.text.strip(),
                    self.category_field.text,
                    float(self.existing_stock.text),
                    float(self.sold_stock.text),
                    float(self.sale_price.text),
                    float(self.total_purchase_price.text),
                    float(self.unit_purchase_price.text),
                    barcode, expiry, is_sold_by_weight, package_quantity=package_quantity
                )
                self._show_snackbar("Produto adicionado com sucesso!", self.COLOR_SUCCESS)
                Clock.schedule_once(lambda dt: self._clear_fields(), 1.5)

            self.admin_screen.load_products()
        finally:
            db.close()

    def _clear_fields(self):
        self.barcode_input.text = ''
        self.expiry_date.text = ''
        self.description.text = ''
        self.existing_stock.text = ''
        self.sold_stock.text = ''
        self.sale_price.text = ''
        self.total_purchase_price.text = ''
        self.unit_purchase_price.text = ''
        self.category_field.text = ''
        self.package_quantity.text = ''
        self.is_sold_by_weight_switch.active = False
        self._category_lookup_inflight = False
        self._category_lookup_barcode = None
        self._category_lookup_token = 0
        self._auto_calc_done = False
        self.barcode_input.focus = True

    def _populate_fields(self):
        p = self.product
        self.description.text = p[1]
        self.category_field.text = p[11] if len(p) > 11 else ""
        self.existing_stock.text = str(p[2])
        self.sold_stock.text = str(p[3])
        self.sale_price.text = str(p[4])
        self.total_purchase_price.text = str(p[5])
        self.unit_purchase_price.text = str(p[6])
        # Evitar recalcular automaticamente em produtos existentes
        self._auto_calc_done = True

        if len(p) > 21 and p[-1]:
            self.package_quantity.text = str(p[-1])

        if len(p) > 12 and p[12]:
            self.barcode_input.text = str(p[12])

        if len(p) > 13 and p[13]:
            try:
                dt = datetime.strptime(str(p[13]), "%Y-%m-%d")
                self.expiry_date.text = dt.strftime("%d/%m/%Y")
            except ValueError:
                self.expiry_date.text = str(p[13])

        if len(p) > 15:
            self.is_sold_by_weight_switch.active = bool(p[15])

    @staticmethod
    def _load_beep_sound():
        try:
            sound = SoundLoader.load('sounds/beep.wav')
            if sound:
                sound.volume = 0.7
            return sound
        except Exception:
            return None

    def _play_beep(self):
        if not self.beep_sound:
            return
        try:
            if self.beep_sound.state == 'play':
                self.beep_sound.stop()
            self.beep_sound.play()
        except Exception:
            pass

    def _show_snackbar(self, message: str, color: tuple):
        """Mostra uma notificação toast elegante"""
        from kivy.uix.label import Label
        from kivy.animation import Animation
        from kivy.graphics import Color, RoundedRectangle
        
        # Criar toast
        toast = BoxLayout(
            size_hint=(None, None),
            size=(dp(300), dp(60)),
            padding=dp(16),
            opacity=0
        )
        
        # Background do toast
        with toast.canvas.before:
            Color(*color)
            toast_bg = RoundedRectangle(
                pos=toast.pos,
                size=toast.size,
                radius=[dp(8)]
            )
        toast.bind(
            pos=lambda i, v: setattr(toast_bg, 'pos', i.pos),
            size=lambda i, v: setattr(toast_bg, 'size', i.size)
        )
        
        # Label com a mensagem
        label = Label(
            text=message,
            color=(1, 1, 1, 1),
            font_size=sp(13),
            halign='center',
            valign='middle'
        )
        label.bind(size=label.setter('text_size'))
        toast.add_widget(label)
        
        # Adicionar ao popup principal
        if hasattr(self, 'content') and self.content:
            # Posicionar no centro inferior
            toast.pos = (
                self.content.center_x - toast.width / 2,
                self.content.y + dp(20)
            )
            self.content.add_widget(toast)
            
            # Animação de entrada
            anim_in = Animation(opacity=1, duration=0.3)
            anim_in.start(toast)
            
            # Animação de saída após 2 segundos
            def remove_toast(dt):
                anim_out = Animation(opacity=0, duration=0.3)
                anim_out.bind(on_complete=lambda *args: self.content.remove_widget(toast))
                anim_out.start(toast)
            
            Clock.schedule_once(remove_toast, 2)

    def _set_status(self, text: str, color: list):
        self.scanner_status.text = text
        self.scanner_status.color = color

    def _on_window_resize(self, instance, width, height):
        self._apply_popup_size()

    def on_dismiss(self):
        if self.scanning:
            self._stop_scanner()
        Window.unbind(on_resize=self._on_window_resize)
