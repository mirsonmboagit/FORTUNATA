import time
import cv2
import numpy as np
from datetime import datetime
from pyzbar.pyzbar import decode

from kivy.uix.popup import Popup
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.image import Image
from kivy.graphics.texture import Texture
from kivy.graphics import Color, RoundedRectangle
from kivy.core.window import Window
from kivy.core.audio import SoundLoader
from kivy.clock import Clock
from kivy.animation import Animation
from kivy.metrics import dp, sp

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


class ProductForm(Popup):
    # Constantes de cores
    COLOR_PRIMARY = (0.2, 0.6, 0.86, 1)
    COLOR_SUCCESS = (0.27, 0.7, 0.42, 1)
    COLOR_ERROR = (0.85, 0.35, 0.35, 1)
    COLOR_WARNING = (0.85, 0.45, 0.3, 1)
    COLOR_GRAY = (0.65, 0.65, 0.65, 1)
    COLOR_LIGHT_GRAY = (0.88, 0.88, 0.88, 1)
    COLOR_TEXT = (0.25, 0.25, 0.25, 1)
    
    # Constantes de tamanhos
    FIELD_HEIGHT = dp(40)
    BUTTON_HEIGHT = dp(44)
    FONT_SIZE = sp(13)
    FONT_SIZE_SMALL = sp(12)
    
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
            on_success=self._on_api_success,
            on_failure=self._on_api_failure,
            on_status=self._on_api_status,
        )
        
        # Flag para evitar loops infinitos de cálculo
        self._calculating = False

        self._setup_popup()
        self._build_ui()

        if self.product:
            self._populate_fields()

        Window.bind(on_resize=self._on_window_resize)

    def _setup_popup(self):
        self.title = ""
        self.size_hint = (None, None)
        self.auto_dismiss = False
        self.background = ''
        self.separator_height = 0
        self.title_size = 0
        self._apply_popup_size()

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
            md_bg_color=(0.98, 0.98, 0.98, 1),
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
            md_bg_color=(1, 1, 1, 1),
            elevation=2
        )

        title_text = "Adicionar Produto" if not self.product else "Editar Produto"
        title_label = Label(
            text=title_text,
            color=(0.15, 0.15, 0.15, 1),
            font_size=sp(18),
            font_name="LogoFont",
            bold=True,
            halign='left',
            valign='middle',
            size_hint_x=0.9
        )
        title_label.bind(size=title_label.setter('text_size'))

        close_btn = MDIconButton(
            icon='close',
            theme_text_color='Custom',
            text_color=(0.25, 0.25, 0.25, 1),
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
            md_bg_color=(0.2, 0.2, 0.2, 1),
            elevation=3
        )

        self.camera_image = Image(allow_stretch=True, keep_ratio=True)
        camera_card.add_widget(self.camera_image)
        section.add_widget(camera_card)

        self.scanner_status = Label(
            text='Scanner Inativo',
            size_hint_y=None,
            height=dp(24),
            color=(0.45, 0.45, 0.45, 1),
            font_size=sp(12),
            bold=True,
            halign='center',
            valign='middle'
        )
        section.add_widget(self.scanner_status)

        # Botões
        btn_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))

        self.scan_btn = MDRaisedButton(
            text='INICIAR SCANNER',
            size_hint_x=0.68,
            md_bg_color=(0.2, 0.6, 0.86, 1),
            on_release=self._toggle_scanner,
            font_size=sp(12)
        )

        switch_btn = MDRaisedButton(
            text='TROCAR',
            size_hint_x=0.32,
            md_bg_color=(0.65, 0.65, 0.65, 1),
            on_release=self._switch_camera,
            font_size=sp(12)
        )

        btn_row.add_widget(self.scan_btn)
        btn_row.add_widget(switch_btn)
        section.add_widget(btn_row)

        section.add_widget(Label(
            text='Posicione o código de barras na câmera',
            size_hint_y=None,
            height=dp(32),
            color=(0.5, 0.5, 0.5, 1),
            font_size=sp(10),
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
            color=(0.15, 0.15, 0.15, 1),
            font_size=sp(14),
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
            bar_color=(0.2, 0.6, 0.86, 0.8)
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
            size_hint_x=0.82,
            font_size=fs,
            readonly=True,
            line_color_focus=self.COLOR_PRIMARY,
            line_color_normal=(0.6, 0.6, 0.6, 0.5)
        )
        
        # Menu dropdown para categorias
        categories = [c for c in self._get_admin_categories() if c != 'Todas']
        menu_items = [{"text": cat, "on_release": lambda x=cat: self._set_category_menu(x)} for cat in categories]
        
        self.category_menu = MDDropdownMenu(
            caller=self.category_field,
            items=menu_items,
            width_mult=3.5,
            max_height=dp(250),
            position="bottom"
        )
        
        self.category_field.bind(focus=lambda i, v: self.category_menu.open() if v else None)

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

        self.category_layout.add_widget(self.category_field)
        self.category_layout.add_widget(add_cat_btn)

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
        
        # Bindings para cálculo automático
        self.existing_stock.bind(text=self._on_stock_or_price_change)
        self.total_purchase_price.bind(text=self._on_total_price_change)
        self.unit_purchase_price.bind(text=self._on_unit_price_change)

    def _on_total_price_change(self, instance, value):
        """Calcula o preço unitário quando o preço total muda"""
        if self._calculating:
            return
            
        self._calculating = True
        try:
            total = value.strip()
            stock = self.existing_stock.text.strip()
            
            if total and stock:
                try:
                    total_val = float(total)
                    stock_val = float(stock)
                    
                    if stock_val > 0:
                        unit_price = total_val / stock_val
                        self.unit_purchase_price.text = f"{unit_price:.2f}"
                        # Sugerir preço de venda se estiver vazio
                        self._suggest_sale_price(unit_price)
                except ValueError:
                    pass
        finally:
            self._calculating = False
    
    def _on_unit_price_change(self, instance, value):
        """Calcula o preço total quando o preço unitário muda"""
        if self._calculating:
            return
            
        self._calculating = True
        try:
            unit = value.strip()
            stock = self.existing_stock.text.strip()
            
            if unit and stock:
                try:
                    unit_val = float(unit)
                    stock_val = float(stock)
                    
                    if stock_val > 0:
                        total_price = unit_val * stock_val
                        self.total_purchase_price.text = f"{total_price:.2f}"
                        # Sugerir preço de venda se estiver vazio
                        self._suggest_sale_price(unit_val)
                except ValueError:
                    pass
        finally:
            self._calculating = False
    
    def _on_stock_or_price_change(self, instance, value):
        """Recalcula quando o estoque muda"""
        if self._calculating:
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
        label_fs = sp(12)
        label_fn = "LogoFont"

        fields = [
            ("Código de Barras", self.barcode_input),
            ("Data de Validade", self.expiry_date_layout),
            ("Descrição *", self.description),
            ("Categoria *", self.category_layout),
            ("Estoque Existente *", self.existing_stock),
            ("Estoque Vendido", self.sold_stock),
            ("Vendido por Peso (KG)", self.weight_switch_layout),
            ("Preço de Venda *", self.sale_price),
            ("Preço Compra Total *", self.total_purchase_price),
            ("Preço Compra Unit. *", self.unit_purchase_price),
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
                font_name=label_fn,
                color=(0.25, 0.25, 0.25, 1)
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
            md_bg_color=self.COLOR_LIGHT_GRAY,
            font_size=self.FONT_SIZE,
            size_hint_x=0.3,
            on_release=self.dismiss
        )

        save_btn = MDRaisedButton(
            text="Confirmar Produto",
            font_name="LogoFont",
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

    def _on_api_failure(self):
        self._set_status("Scanner Ativo", (0.45, 0.45, 0.45, 1))
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
        if category:
            self._set_category(category)

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

    def _toggle_scanner(self, instance):
        if not self.scanning:
            self.scanning = True
            self.scan_btn.text = 'PARAR SCANNER'
            self.scan_btn.md_bg_color = self.COLOR_ERROR
            self._set_status("Scanner Ativo", self.COLOR_PRIMARY)
            Clock.schedule_interval(self._update_camera, 1.0 / 15.0)
        else:
            self._stop_scanner()

    def _stop_scanner(self):
        self.scanning = False
        self.scan_btn.text = 'INICIAR SCANNER'
        self.scan_btn.md_bg_color = self.COLOR_PRIMARY
        self._set_status("Scanner Inativo", (0.45, 0.45, 0.45, 1))
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
                    self.api_manager.search(barcode_value)

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
                self._set_status("Scanner Ativo", self.COLOR_PRIMARY)

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
        self.scan_btn.text = 'PARAR SCANNER'
        self.scan_btn.md_bg_color = self.COLOR_ERROR
        self._set_status("Scanner Ativo", self.COLOR_PRIMARY)
        Clock.schedule_interval(self._update_camera, 1.0 / 15.0)

    def _on_barcode_manual_entry(self, instance):
        barcode = instance.text.strip()
        if barcode and len(barcode) >= 8:
            self.api_manager.search(barcode)

    def _show_category_form(self, instance):
        # Content card
        content = MDCard(
            orientation='vertical',
            padding=[dp(24), dp(20)],
            spacing=dp(14),
            radius=[dp(12)],
            md_bg_color=(1, 1, 1, 1),
            size_hint_y=None,
            height=dp(180)
        )

        content.add_widget(Label(
            text='Adicionar Categoria',
            color=(0.15, 0.15, 0.15, 1),
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
        content.add_widget(category_input)

        btn_row = BoxLayout(size_hint_y=None, height=self.FIELD_HEIGHT, spacing=dp(10))

        cancel_btn = MDFlatButton(
            text='Cancelar',
            theme_text_color='Custom',
            text_color=self.COLOR_TEXT,
            md_bg_color=self.COLOR_LIGHT_GRAY,
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
            background='',
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
                    barcode, expiry, is_sold_by_weight
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
                    barcode, expiry, is_sold_by_weight
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
        self.is_sold_by_weight_switch.active = False
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