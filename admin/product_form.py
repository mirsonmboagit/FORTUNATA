import time
import re
import unicodedata
from threading import Thread
from datetime import datetime

from kivy.uix.popup import Popup
from kivy.uix.boxlayout import BoxLayout
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

from kivymd.uix.button import MDRaisedButton, MDFlatButton, MDIconButton
from kivymd.uix.textfield import MDTextField
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.selectioncontrol import MDSwitch
from kivymd.uix.card import MDCard
from kivymd.uix.pickers import MDDatePicker

from api.api_manager import APIManager
from api.api_openfoodfacts import OpenFoodFactsAPI
from api.api_bazara import BazaraAPI
from api.api_ranxo import RanxoAPI
from api.api_upcitemdb import UPCitemdbAPI
from api.api_sixty60 import Sixty60API
from utils.vision import get_vision_dependencies


def _row(*widgets, spacing=dp(10), height=dp(44)):
    """Linha horizontal de campos com altura fixa e tamanho igual entre widgets."""
    row = BoxLayout(
        orientation="horizontal",
        size_hint=(1, None),
        height=height,
        spacing=spacing,
    )
    for w in widgets:
        if w.parent:
            w.parent.remove_widget(w)
        # Garantir que todos os widgets estiriquem igualmente na horizontal
        w.size_hint_x = 1
        row.add_widget(w)
    return row


class ProductForm(Popup):
    COLOR_PRIMARY    = (0.2,  0.6,  0.86, 1)
    COLOR_SUCCESS    = (0.27, 0.7,  0.42, 1)
    COLOR_ERROR      = (0.85, 0.35, 0.35, 1)
    COLOR_WARNING    = (0.85, 0.45, 0.3,  1)
    COLOR_GRAY       = (0.65, 0.65, 0.65, 1)
    COLOR_TEXT       = (0.25, 0.25, 0.25, 1)
    COLOR_CARD       = (0.88, 0.88, 0.88, 1)
    COLOR_CARD_ALT   = (0.92, 0.92, 0.92, 1)

    FIELD_H      = dp(44)
    BUTTON_H     = dp(42)
    FONT_SIZE    = sp(14)
    FONT_SIZE_SM = sp(13)

    def __init__(self, admin_screen, product=None, **kwargs):
        super().__init__(**kwargs)

        self.admin_screen = admin_screen
        self.product      = product

        self.scanning          = False
        self.camera_capture    = None
        self.current_camera    = 0
        self.last_barcode      = None
        self.last_barcode_time = 0
        self.beep_sound        = self._load_beep_sound()
        self._vision_modules   = None

        self.api_manager = APIManager(
            database   = admin_screen.db,
            on_success = self._on_api_success,
            on_failure = self._on_api_failure,
            on_status  = self._on_api_status,
        )
        self._apply_theme_tokens()

        self._category_sources = [
            ("Bazara",          BazaraAPI()),
            ("Ranxo",           RanxoAPI()),
            ("Open Food Facts", OpenFoodFactsAPI()),
            ("UPCitemdb",       UPCitemdbAPI()),
            ("Sixty60",         Sixty60API()),
        ]
        self._category_lookup_inflight = False
        self._category_lookup_barcode  = None
        self._category_lookup_token    = 0

        self._calculating           = False
        self._auto_calc_done        = False
        self._discount_base_price   = None
        self._applying_price_action = False

        self._price_discount_buttons = []
        self._price_revert_btn       = None
        self._cancel_btn             = None
        self._save_btn               = None
        self._content_layout         = None
        self._camera_section         = None
        self._form_section           = None
        self._camera_card            = None
        self._compact_layout         = None

        self._setup_popup()
        self._build_ui()

        if self.product:
            self._populate_fields()

        Window.bind(on_resize=self._on_window_resize)

    # â”€â”€ Popup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _setup_popup(self):
        self.title            = ""
        self.size_hint        = (None, None)
        self.auto_dismiss     = False
        self.background       = "data/images/defaulttheme/transparent.png"
        self.background_color = (0, 0, 0, 0)
        self.separator_height = 0
        self.title_size       = 0
        self._apply_popup_size()

    def _apply_popup_size(self):
        w, h = Window.size
        if w < dp(980):
            self.size = (w * 0.98, h * 0.965)
        else:
            self.size = (min(dp(1060), w * 0.9), min(dp(780), h * 0.94))
        self._update_responsive_layout()

    # â”€â”€ Theme â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _apply_theme_tokens(self):
        app    = App.get_running_app()
        tokens = getattr(app, "theme_tokens", {}) if app else {}
        self.COLOR_PRIMARY  = tokens.get("primary",        self.COLOR_PRIMARY)
        self.COLOR_SUCCESS  = tokens.get("success",        self.COLOR_SUCCESS)
        self.COLOR_ERROR    = tokens.get("danger",         self.COLOR_ERROR)
        self.COLOR_WARNING  = tokens.get("warning",        self.COLOR_WARNING)
        self.COLOR_GRAY     = tokens.get("text_secondary", self.COLOR_GRAY)
        self.COLOR_CARD     = tokens.get("card",           self.COLOR_CARD)
        self.COLOR_CARD_ALT = tokens.get("card_alt",       self.COLOR_CARD_ALT)
        self.COLOR_TEXT     = tokens.get("text_primary",   self.COLOR_TEXT)

        theme_style = getattr(getattr(app, "theme_cls", None), "theme_style", "Light") if app else "Light"
        if theme_style == "Dark":
            if self.COLOR_TEXT[0]     < 0.6:  self.COLOR_TEXT     = (0.95, 0.95, 0.96, 1)
            if self.COLOR_GRAY[0]     < 0.6:  self.COLOR_GRAY     = (0.78, 0.78, 0.82, 1)
            if self.COLOR_CARD[0]     > 0.4:  self.COLOR_CARD     = (0.16, 0.17, 0.20, 1)
            if self.COLOR_CARD_ALT[0] > 0.45: self.COLOR_CARD_ALT = (0.20, 0.22, 0.25, 1)

    def _style_field(self, field):
        """Estilo com validacao visual: vermelho vazio, verde preenchido."""
        field.line_color_normal = (*self.COLOR_ERROR[:3], 0.95)
        field.line_color_focus  = (*self.COLOR_ERROR[:3], 1)
        field.hint_text_color   = self.COLOR_ERROR
        if hasattr(field, "cursor_color"):
            field.cursor_color = self.COLOR_TEXT

        # Aplica cor inicial
        self._update_field_color(field, field.text)

        # Atualiza cor sempre que o texto mudar
        field.bind(text=self._update_field_color)

    def _update_field_color(self, field, text):
        """Vermelho = vazio, Verde = preenchido."""
        filled = bool((text or "").strip())
        color = self.COLOR_SUCCESS if filled else self.COLOR_ERROR

        field.hint_text_color   = color
        field.line_color_normal = (*color[:3], 0.95)
        field.line_color_focus  = (*color[:3], 1)
        field.text_color        = self.COLOR_TEXT if filled else color
        field.text_color_normal = field.text_color
        field.text_color_focus  = self.COLOR_TEXT if filled else color

    # â”€â”€ Build UI â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _build_ui(self):
        main_card = MDCard(
            orientation = "vertical",
            padding     = 0,
            spacing     = 0,
            radius      = [dp(16)],
            md_bg_color = self.COLOR_CARD,
            elevation   = 0,
        )
        main_card.add_widget(self._build_header())

        self._content_layout = BoxLayout(
            orientation = "horizontal",
            spacing     = dp(14),
            padding     = [dp(16), dp(16), dp(16), dp(16)],
        )
        self._camera_section = self._build_camera_section()
        self._form_section = self._build_form_section()
        self._content_layout.add_widget(self._camera_section)
        self._content_layout.add_widget(self._form_section)
        main_card.add_widget(self._content_layout)
        self.content = main_card
        self._update_responsive_layout()

    # â”€â”€ Header â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _build_header(self):
        header = MDCard(
            orientation = "horizontal",
            size_hint_y = None,
            height      = dp(50),
            padding     = [dp(18), dp(6)],
            radius      = [dp(16), dp(16), 0, 0],
            md_bg_color = self.COLOR_CARD,
            elevation   = 2,
        )
        title_label = Label(
            text        = "Adicionar Produto" if not self.product else "Editar Produto",
            color       = self.COLOR_TEXT,
            font_size   = sp(18),
            bold        = True,
            halign      = "left",
            valign      = "middle",
            size_hint_x = 0.9,
        )
        title_label.bind(size=title_label.setter("text_size"))
        close_btn = MDIconButton(
            icon             = "close",
            theme_text_color = "Custom",
            text_color       = self.COLOR_TEXT,
            on_release       = self.dismiss,
            pos_hint         = {"center_y": 0.5},
        )
        header.add_widget(title_label)
        header.add_widget(close_btn)
        return header

    # â”€â”€ Camera â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _build_camera_section(self):
        # Bloco de camera com preview quadrado e limite de crescimento.
        outer = MDCard(
            orientation = "vertical",
            size_hint   = (None, 1),
            width       = dp(332),
            padding     = dp(12),
            spacing     = dp(8),
            radius      = [dp(12)],
            md_bg_color = self.COLOR_CARD_ALT,
            elevation   = 1,
        )

        title = Label(
            text="Scanner de Codigo", size_hint_y=None, height=dp(22),
            color=self.COLOR_TEXT, font_size=sp(15), bold=True,
            halign="left", valign="middle",
        )
        title.bind(size=title.setter("text_size"))
        outer.add_widget(title)

        camera_card = MDCard(
            size_hint=(1, None),
            height=dp(300),
            radius=[dp(10)],
            md_bg_color=self.COLOR_PRIMARY,
            elevation=3,
        )
        self._camera_card = camera_card
        camera_card.bind(width=lambda inst, val: setattr(inst, "height", max(dp(220), min(val, dp(360)))))
        self.camera_image = Image(fit_mode="contain")
        camera_card.add_widget(self.camera_image)
        outer.add_widget(camera_card)

        self.scanner_status = Label(
            text="", size_hint_y=None, height=dp(20),
            color=self.COLOR_GRAY, font_size=sp(12), bold=True,
            halign="center", valign="middle",
        )
        outer.add_widget(self.scanner_status)

        btn_row = BoxLayout(size_hint=(None, None), height=dp(40), width=dp(92), spacing=dp(12))
        self.scan_btn = MDIconButton(
            icon="barcode-scan", theme_text_color="Custom", text_color=(1,1,1,1),
            md_bg_color=self.COLOR_PRIMARY, size_hint=(None, None), size=(dp(40), dp(40)),
            on_release=self._toggle_scanner,
        )
        switch_btn = MDIconButton(
            icon="camera-switch", theme_text_color="Custom", text_color=(1,1,1,1),
            md_bg_color=self.COLOR_GRAY, size_hint=(None, None), size=(dp(40), dp(40)),
            on_release=self._switch_camera,
        )
        btn_row.add_widget(self.scan_btn)
        btn_row.add_widget(switch_btn)
        wrapper = AnchorLayout(size_hint_y=None, height=dp(40))
        wrapper.add_widget(btn_row)
        outer.add_widget(wrapper)

        hint = Label(
            text="Posicione o codigo de barras",
            size_hint_y=None, height=dp(28),
            color=self.COLOR_GRAY, font_size=sp(12), halign="center", valign="middle",
        )
        outer.add_widget(hint)
        return outer

    # â”€â”€ Form â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _build_form_section(self):
        """
        Sem scroll. Layout denso em filas horizontais de 2-4 campos.
        Sem labels externos â€” toda a info estÃ¡ nos hint_text dos inputs.
        """
        self._create_form_fields()

        sec = BoxLayout(orientation="vertical", size_hint_x=1, spacing=dp(14))

        title = Label(
            text="Informacoes do Produto", size_hint_y=None, height=dp(22),
            color=self.COLOR_TEXT, font_size=sp(15), bold=True,
            halign="left", valign="middle",
        )
        title.bind(size=title.setter("text_size"))
        sec.add_widget(title)

        # â”€â”€ Fila 1: Barcode | SKU â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        sec.add_widget(_row(
            self.barcode_input,
            self.sku_input,
        ))

        # â”€â”€ Fila 2: Nome | Categoria â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        sec.add_widget(_row(
            self.description,
            self.category_layout,
        ))

        # â”€â”€ Fila 3: Unidade de medida | Validade â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        sec.add_widget(_row(
            self.package_quantity,
            self.expiry_date_layout,
        ))

        # â”€â”€ Fila 4: Unidades por embalagem | Venda por embalagem â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        sec.add_widget(_row(
            self.units_per_package_input,
            self.pack_sale_layout,
        ))

        # â”€â”€ Fila 5: Estoque Atual | Estoque Vendido â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        sec.add_widget(_row(
            self.existing_stock,
            self.sold_stock,
        ))

        # â”€â”€ Fila 6: Preco Unitario | Preco Total â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        sec.add_widget(_row(
            self.unit_purchase_price,
            self.total_purchase_price,
        ))

        # â”€â”€ Fila 7: Preco de Venda | Peso â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        sec.add_widget(_row(
            self.sale_price,
            self.weight_switch_layout,
        ))

        # â”€â”€ Fila 5: Ajuste rapido de preco â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        sec.add_widget(self._price_actions_layout)

        # spacer
        sec.add_widget(BoxLayout(size_hint_y=1))

        # â”€â”€ Botoes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        sec.add_widget(self._build_action_buttons())

        return sec

    # â”€â”€ Campos â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _create_form_fields(self):
        h  = self.FIELD_H
        fs = self.FONT_SIZE

        def _f(hint, readonly=False, inp_filter=None, size_hint_x=1):
            f = MDTextField(
                hint_text         = hint,
                mode              = "rectangle",
                size_hint         = (size_hint_x, None),
                height            = h,
                font_size         = fs,
                readonly          = readonly,
                line_color_focus  = self.COLOR_PRIMARY,
                line_color_normal = (0.6, 0.6, 0.6, 0.4),
            )
            if inp_filter:
                f.input_filter = inp_filter
            self._style_field(f)
            return f

        # â”€â”€ Fila 1 â”€â”€
        self.barcode_input = _f("Cod. Barras (opcional)")
        self.barcode_input.bind(on_text_validate=self._on_barcode_manual_entry)

        self.sku_input = _f("SKU (auto)", readonly=True)

        self.package_quantity = _f("Unidade de medida ex: 500ml")
        self.units_per_package_input = _f("Unidades por embalagem", inp_filter="int")

        # â”€â”€ Fila 2 â”€â”€
        self.description = _f("Nome do produto *")
        self.description.bind(text=self._on_description_text)

        # Categoria: campo + botao dropdown + botao adicionar
        self.category_layout = BoxLayout(
            orientation="horizontal", size_hint=(1, None), height=h, spacing=dp(4),
        )
        self.category_field = _f("Categoria *")
        dropdown_btn = MDIconButton(
            icon="menu-down", theme_text_color="Custom", text_color=(1,1,1,1),
            md_bg_color=self.COLOR_PRIMARY, size_hint=(None, None), size=(dp(36), dp(36)),
            pos_hint={"center_y": 0.5}, on_release=self._open_category_menu,
        )
        add_cat_btn = MDIconButton(
            icon="plus", theme_text_color="Custom", text_color=(1,1,1,1),
            md_bg_color=self.COLOR_PRIMARY, size_hint=(None, None), size=(dp(36), dp(36)),
            pos_hint={"center_y": 0.5}, on_release=self._show_category_form,
        )
        categories = [c for c in self._get_admin_categories() if c != "Todas"]
        self.category_menu = MDDropdownMenu(
            caller=dropdown_btn,
            items=[{"text": c, "on_release": lambda x=c: self._set_category_menu(x)} for c in categories],
            width_mult=3.5, max_height=dp(250), position="bottom",
        )
        self.category_layout.add_widget(self.category_field)
        self.category_layout.add_widget(dropdown_btn)
        self.category_layout.add_widget(add_cat_btn)

        # â”€â”€ Fila 3 â”€â”€
        self.existing_stock = _f("Estoque atual *", inp_filter="float")
        self.existing_stock.bind(text=self._on_stock_or_price_change)

        self.sold_stock = _f("Vendido", readonly=False)
        self.sold_stock.text = "0"

        # Validade com Ã­cone calendÃ¡rio
        self.expiry_date_layout = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=h, spacing=dp(4),
        )
        self.expiry_date = _f("Validade DD/MM/AAAA")
        cal_btn = MDIconButton(
            icon="calendar", theme_text_color="Custom", text_color=self.COLOR_PRIMARY,
            size_hint=(None, None), size=(dp(36), dp(36)),
            pos_hint={"center_y": 0.5}, on_release=self._show_date_picker,
        )
        self.expiry_date_layout.add_widget(self.expiry_date)
        self.expiry_date_layout.add_widget(cal_btn)

        # Peso â€” card estruturado + toggle alinhado
        self.weight_switch_layout = MDCard(
            orientation="horizontal",
            size_hint=(1, None),
            height=h,
            spacing=dp(10),
            padding=[dp(10), 0, dp(10), 0],
            radius=[dp(10)],
            md_bg_color=self.COLOR_CARD_ALT,
            elevation=0,
        )
        peso_lbl = Label(
            text="Peso KG",
            color=self.COLOR_GRAY,
            font_size=self.FONT_SIZE_SM,
            size_hint=(None, 1),
            width=dp(62),
            halign="left",
            valign="middle",
        )
        peso_lbl.bind(size=lambda i, *_: setattr(i, "text_size", (i.width, None)))
        self.weight_state_btn = MDRaisedButton(
            text="INATIVO",
            md_bg_color=(0.45, 0.45, 0.48, 1),
            text_color=(1, 1, 1, 1),
            font_size=sp(11),
            size_hint=(None, None),
            size=(dp(102), dp(32)),
            on_release=self._toggle_weight_button,
        )
        # Mantem interface esperada pelo restante do formulario (.active)
        self.is_sold_by_weight_switch = self.weight_state_btn
        self.is_sold_by_weight_switch.active = False
        self.weight_switch_layout.add_widget(peso_lbl)
        self.weight_switch_layout.add_widget(BoxLayout(size_hint_x=1))
        self.weight_switch_layout.add_widget(self.weight_state_btn)
        self._set_weight_state(False)

        self.pack_sale_layout = MDCard(
            orientation="horizontal",
            size_hint=(1, None),
            height=h,
            spacing=dp(10),
            padding=[dp(10), 0, dp(10), 0],
            radius=[dp(10)],
            md_bg_color=self.COLOR_CARD_ALT,
            elevation=0,
        )
        pack_lbl = Label(
            text="Embalagem",
            color=self.COLOR_GRAY,
            font_size=self.FONT_SIZE_SM,
            size_hint=(None, 1),
            width=dp(92),
            halign="left",
            valign="middle",
        )
        pack_lbl.bind(size=lambda i, *_: setattr(i, "text_size", (i.width, None)))
        self.pack_sale_state_btn = MDRaisedButton(
            text="INATIVO",
            md_bg_color=(0.45, 0.45, 0.48, 1),
            text_color=(1, 1, 1, 1),
            font_size=sp(11),
            size_hint=(None, None),
            size=(dp(102), dp(32)),
            on_release=self._toggle_pack_sale_button,
        )
        self.allow_pack_sale_switch = self.pack_sale_state_btn
        self.allow_pack_sale_switch.active = False
        self.pack_sale_layout.add_widget(pack_lbl)
        self.pack_sale_layout.add_widget(BoxLayout(size_hint_x=1))
        self.pack_sale_layout.add_widget(self.pack_sale_state_btn)
        self._set_pack_sale_state(False)

        # â”€â”€ Fila 4 â”€â”€
        self.unit_purchase_price = _f("Preco unit. compra *", inp_filter="float")
        self.unit_purchase_price.bind(text=self._on_unit_price_change)

        self.total_purchase_price = _f("Preco total compra *", inp_filter="float")
        self.total_purchase_price.bind(text=self._on_total_price_change)

        self.sale_price = _f("Preco de venda *", inp_filter="float")
        self.sale_price.bind(text=self._on_sale_price_text_change)

        # â”€â”€ Fila 5 â€” ajuste â”€â”€
        self._price_actions_layout = self._build_price_actions()

    # â”€â”€ Price actions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _build_price_actions(self):
        layout = BoxLayout(
            orientation="horizontal", size_hint=(1, None), height=dp(36), spacing=dp(8),
        )
        lbl = Label(
            text="Desconto rapido:", color=self.COLOR_GRAY, font_size=self.FONT_SIZE_SM,
            size_hint=(None, 1), width=dp(112), halign="left", valign="middle",
        )
        lbl.bind(size=lambda i, *_: setattr(i, "text_size", (i.width, None)))
        layout.add_widget(lbl)

        self._price_discount_buttons = []
        for pct in (5, 10, 15, 20):
            btn = MDFlatButton(
                text=f"-{pct}%", theme_text_color="Custom",
                text_color=self.COLOR_PRIMARY, md_bg_color=self.COLOR_CARD_ALT,
                size_hint=(None, 1), width=dp(56), font_size=self.FONT_SIZE_SM,
            )
            btn.bind(on_release=lambda _b, p=pct: self._apply_quick_discount(p))
            layout.add_widget(btn)
            self._price_discount_buttons.append(btn)

        self._price_revert_btn = MDFlatButton(
            text="Reverter", theme_text_color="Custom",
            text_color=self.COLOR_TEXT, md_bg_color=self.COLOR_CARD_ALT,
            size_hint=(None, 1), width=dp(80), font_size=self.FONT_SIZE_SM,
        )
        self._price_revert_btn.bind(on_release=self._restore_sale_price)
        layout.add_widget(self._price_revert_btn)
        layout.add_widget(BoxLayout(size_hint_x=1))
        self._update_price_actions_state()
        return layout

    # â”€â”€ Action buttons â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _build_action_buttons(self):
        layout = BoxLayout(
            orientation="horizontal", size_hint=(1, None), height=self.BUTTON_H, spacing=dp(10),
        )
        layout.add_widget(BoxLayout(size_hint_x=1))
        self._cancel_btn = MDFlatButton(
            text="Cancelar", theme_text_color="Custom",
            text_color=self.COLOR_TEXT, md_bg_color=self.COLOR_CARD_ALT,
            font_size=self.FONT_SIZE, size_hint=(None, 1), width=dp(120), on_release=self.dismiss,
        )
        self._save_btn = MDRaisedButton(
            text="Salvar" if self.product else "Cadastrar",
            md_bg_color=self.COLOR_SUCCESS, font_size=self.FONT_SIZE,
            size_hint=(None, 1), width=dp(130), on_release=self._save_product,
        )
        layout.add_widget(self._cancel_btn)
        layout.add_widget(self._save_btn)
        return layout

    # â”€â”€ Window resize â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _update_responsive_layout(self):
        if not self._content_layout:
            return

        compact = self.size[0] < dp(980) or Window.width < dp(1120)
        self._compact_layout = compact

        if compact:
            self._content_layout.orientation = "vertical"
            self._content_layout.spacing = dp(10)
            self._content_layout.padding = [dp(12), dp(12), dp(12), dp(12)]
            if self._camera_section:
                cam_w = max(dp(280), min(self.size[0] - dp(52), dp(420)))
                self._camera_section.size_hint = (None, None)
                self._camera_section.width = cam_w
                self._camera_section.height = cam_w + dp(165)
                self._camera_section.pos_hint = {"center_x": 0.5}
            if self._form_section:
                self._form_section.size_hint = (1, 1)
        else:
            self._content_layout.orientation = "horizontal"
            self._content_layout.spacing = dp(14)
            self._content_layout.padding = [dp(16), dp(16), dp(16), dp(16)]
            if self._camera_section:
                cam_w = max(dp(304), min(self.size[0] * 0.34, dp(360)))
                self._camera_section.size_hint = (None, 1)
                self._camera_section.width = cam_w
                self._camera_section.height = 0
                self._camera_section.pos_hint = {}
            if self._form_section:
                self._form_section.size_hint = (1, 1)

        if self._camera_card and self._camera_section:
            preview_size = self._camera_section.width - dp(24)
            self._camera_card.height = max(dp(220), min(preview_size, dp(360)))

    def _on_window_resize(self, instance, width, height):
        self._apply_popup_size()

    # â”€â”€ API callbacks â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _on_api_success(self, source, data):
        self._set_status(f"OK: {source}", self.COLOR_PRIMARY)
        self._fill_fields(data)
        self._show_snackbar(f"Dados de {source}", self.COLOR_SUCCESS)

    def _on_api_partial(self, source, data):
        self._set_status(f"{source}...", self.COLOR_PRIMARY)
        if data: self._fill_fields(data)

    def _on_api_complete(self, data):
        if not data or not data.get("source_chain"):
            self._on_api_failure(); return
        self._fill_fields(data)
        self._set_status("OK", self.COLOR_SUCCESS)
        self._show_snackbar("Dados atualizados", self.COLOR_SUCCESS)

    def _on_api_failure(self):
        self._set_status("Nao encontrado", self.COLOR_ERROR)
        self._show_snackbar(f"'{self.barcode_input.text.strip()}' nao encontrado", self.COLOR_ERROR)

    def _on_api_status(self, message):
        self._set_status(message, self.COLOR_PRIMARY)

    # â”€â”€ Fill fields â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _fill_fields(self, data):
        name  = data.get("name",  "")
        brand = data.get("brand", "")
        if name and not self.description.text.strip():
            self.description.text = f"{brand} - {name}" if brand and brand.lower() not in name.lower() else name

        category = data.get("category")
        if category and not self.category_field.text.strip():
            self._set_category(category)
        elif not self.category_field.text.strip():
            inferred = self._infer_category_from_name(self.description.text or name)
            if inferred:
                self._set_category(inferred)
                self._register_generated_category(inferred)

        quantity = (data.get("quantity") or
                    self._extract_quantity_from_text(data.get("name", "")) or
                    (self._extract_quantity_from_text(self.description.text) if self.description.text.strip() else None))
        if quantity and not self.package_quantity.text.strip():
            self.package_quantity.text = str(quantity)

        if data.get("price") and not self.sale_price.text.strip():
            self.sale_price.text = str(data["price"])
        if data.get("expiry_date") and not self.expiry_date.text.strip():
            self.expiry_date.text = data["expiry_date"]
        if data.get("sold_by_weight"):
            self._set_weight_state(True)

    # â”€â”€ Category helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _get_admin_categories(self):
        if hasattr(self.admin_screen, "get_categories"):
            return self.admin_screen.get_categories()
        if hasattr(self.admin_screen, "products"):
            cats = {p[11] for p in self.admin_screen.products if len(p) > 11 and p[11]}
            return sorted(cats)
        return []

    def _set_category(self, category_name):
        for cat in [c for c in self._get_admin_categories() if c != "Todas"]:
            if cat.lower() == category_name.lower() or cat.lower() in category_name.lower() or category_name.lower() in cat.lower():
                self.category_field.text = cat
                return
        self.category_field.text = category_name

    def _set_category_menu(self, category):
        self.category_field.text = category
        self.category_menu.dismiss()

    def _open_category_menu(self, instance):
        categories = [c for c in self._get_admin_categories() if c != "Todas"]
        self.category_menu.items = [
            {"text": c, "on_release": lambda x=c: self._set_category_menu(x)} for c in categories
        ]
        self.category_menu.open()

    @staticmethod
    def _normalize_text(text):
        if not text: return ""
        text = unicodedata.normalize("NFD", str(text))
        return "".join(ch for ch in text if unicodedata.category(ch) != "Mn").lower()

    def _infer_category_from_name(self, name):
        if not name: return None
        norm = self._normalize_text(name)
        for cat in [c for c in self._get_admin_categories() if c != "Todas"]:
            if self._normalize_text(cat) in norm: return cat
        keyword_map = {
            "Bebidas":    ["agua", "sumo", "suco", "refrigerante", "cerveja", "vinho", "bebida"],
            "LaticÃ­nios": ["leite", "iogurte", "queijo", "manteiga", "nata"],
            "Higiene":    ["sabonete", "shampoo", "pasta", "dente", "desodorante", "fralda"],
            "Limpeza":    ["detergente", "lixivia", "cloro", "amaciante", "sabao", "desinfetante"],
            "Mercearia":  ["arroz", "farinha", "acucar", "oleo", "massa", "feijao", "sal", "cafe"],
            "Snacks":     ["bolacha", "biscoito", "chips", "snack", "salgadinho"],
            "Congelados": ["congelado", "gelo"],
        }
        for cat, kws in keyword_map.items():
            if any(self._normalize_text(k) in norm for k in kws): return cat
        return None

    def _register_generated_category(self, category):
        if not category: return
        cats = [c for c in self._get_admin_categories() if c != "Todas"]
        if category not in cats and hasattr(self.admin_screen, "register_category"):
            self.admin_screen.register_category(category)

    @staticmethod
    def _extract_quantity_from_text(text):
        if not text: return None
        m = re.search(
            r"(?i)\b(\d+(?:[.,]\d+)?\s*x\s*)?\d+(?:[.,]\d+)?\s*"
            r"(ml|l|lt|lts|litro|litros|g|kg|grama|gramas|mg|cl|dl|un|unid|unidade|unidades)\b",
            text,
        )
        return " ".join(m.group(0).split()) if m else None

    # â”€â”€ Category form popup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _show_category_form(self, instance):
        content = MDCard(
            orientation="vertical", padding=[dp(24), dp(20)], spacing=dp(14),
            radius=[dp(12)], md_bg_color=self.COLOR_CARD, size_hint_y=None, height=dp(180),
        )
        content.add_widget(Label(
            text="Nova Categoria", color=self.COLOR_TEXT, font_size=sp(16), bold=True,
            halign="center", valign="middle", size_hint_y=None, height=dp(28),
        ))
        cat_input = MDTextField(
            hint_text="Ex.: Bebidas, Mercearia...", mode="rectangle",
            font_size=self.FONT_SIZE, size_hint_y=None, height=self.FIELD_H,
            line_color_focus=self.COLOR_PRIMARY,
        )
        self._style_field(cat_input)
        content.add_widget(cat_input)
        btn_row = BoxLayout(size_hint_y=None, height=self.FIELD_H, spacing=dp(10))
        cancel_btn = MDFlatButton(text="Cancelar", theme_text_color="Custom",
                                  text_color=self.COLOR_TEXT, md_bg_color=self.COLOR_CARD_ALT,
                                  font_size=self.FONT_SIZE)
        add_btn = MDRaisedButton(text="Adicionar", md_bg_color=self.COLOR_SUCCESS, font_size=self.FONT_SIZE)
        popup = Popup(content=content, size_hint=(None, None), size=(dp(380), dp(240)),
                      auto_dismiss=False, background="data/images/defaulttheme/transparent.png",
                      background_color=(0,0,0,0), separator_height=0, title="", title_size=0)

        def on_add(_):
            new_cat = cat_input.text.strip()
            if not new_cat: self._show_snackbar("Digite o nome!", self.COLOR_ERROR); return
            cats = [c for c in self._get_admin_categories() if c != "Todas"]
            if new_cat in cats: self._show_snackbar("Ja existe!", self.COLOR_WARNING); return
            self.category_menu.items = [
                {"text": c, "on_release": lambda x=c: self._set_category_menu(x)}
                for c in sorted(cats + [new_cat])
            ]
            self.category_field.text = new_cat
            if hasattr(self.admin_screen, "register_category"):
                self.admin_screen.register_category(new_cat)
            popup.dismiss()
            self._show_snackbar(f"'{new_cat}' adicionada!", self.COLOR_SUCCESS)

        cancel_btn.bind(on_release=popup.dismiss)
        add_btn.bind(on_release=on_add)
        btn_row.add_widget(cancel_btn)
        btn_row.add_widget(add_btn)
        content.add_widget(btn_row)
        popup.open()

    # â”€â”€ Auto price calc â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _on_total_price_change(self, instance, value):
        if self._calculating or self._auto_calc_done: return
        self._calculating = True
        try:
            total = value.strip(); stock = self.existing_stock.text.strip()
            if total and stock and not self.unit_purchase_price.text.strip():
                try:
                    unit = float(total) / float(stock)
                    self.unit_purchase_price.text = f"{unit:.2f}"
                    self._auto_calc_done = True
                    self._suggest_sale_price(unit)
                except (ValueError, ZeroDivisionError): pass
        finally: self._calculating = False

    def _on_unit_price_change(self, instance, value):
        if self._calculating or self._auto_calc_done: return
        self._calculating = True
        try:
            unit = value.strip(); stock = self.existing_stock.text.strip()
            if unit and stock and not self.total_purchase_price.text.strip():
                try:
                    u = float(unit)
                    self.total_purchase_price.text = f"{u * float(stock):.2f}"
                    self._auto_calc_done = True
                    self._suggest_sale_price(u)
                except (ValueError, ZeroDivisionError): pass
        finally: self._calculating = False

    def _on_stock_or_price_change(self, instance, value):
        if self._calculating or self._auto_calc_done: return
        if self.total_purchase_price.text.strip() and value.strip():
            self._on_total_price_change(self.total_purchase_price, self.total_purchase_price.text)
        elif self.unit_purchase_price.text.strip() and value.strip():
            self._on_unit_price_change(self.unit_purchase_price, self.unit_purchase_price.text)

    def _suggest_sale_price(self, unit_cost):
        if not self.sale_price.text.strip():
            try: self.sale_price.text = f"{unit_cost * 1.30:.2f}"
            except Exception: pass

    # â”€â”€ Price actions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    @staticmethod
    def _parse_price_value(raw):
        text = (raw or "").strip().replace(",", ".")
        try: return float(text) if text else None
        except ValueError: return None

    def _set_sale_price_value(self, value):
        self._applying_price_action = True
        try: self.sale_price.text = f"{value:.2f}"
        finally: self._applying_price_action = False

    def _on_sale_price_text_change(self, instance, value):
        if not self._applying_price_action and self._discount_base_price is not None:
            self._discount_base_price = None
        self._update_price_actions_state()

    def _apply_quick_discount(self, pct):
        current = self._parse_price_value(self.sale_price.text)
        if not current or current <= 0:
            self._show_snackbar("Informe um preco de venda valido.", self.COLOR_WARNING); return
        if self._discount_base_price is None:
            self._discount_base_price = current
        discounted = self._discount_base_price * (1 - pct / 100)
        self._set_sale_price_value(discounted)
        self._update_price_actions_state()
        self._show_snackbar(f"-{pct}%: {self._discount_base_price:.2f} â†’ {discounted:.2f}", self.COLOR_PRIMARY)

    def _restore_sale_price(self, instance):
        if self._discount_base_price is None:
            self._show_snackbar("Nao ha preco para reverter.", self.COLOR_WARNING); return
        original = self._discount_base_price
        self._set_sale_price_value(original)
        self._discount_base_price = None
        self._update_price_actions_state()
        self._show_snackbar(f"Preco restaurado: {original:.2f}", self.COLOR_SUCCESS)

    def _update_price_actions_state(self):
        current = self._parse_price_value(self.sale_price.text)
        can = current is not None and current > 0
        for btn in self._price_discount_buttons: btn.disabled = not can
        if self._price_revert_btn: self._price_revert_btn.disabled = self._discount_base_price is None

    # â”€â”€ Date picker â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _show_date_picker(self, instance):
        d = datetime.now()
        if self.expiry_date.text.strip():
            try: d = datetime.strptime(self.expiry_date.text.strip(), "%d/%m/%Y")
            except ValueError: pass
        dp_ = MDDatePicker(year=d.year, month=d.month, day=d.day)
        dp_.bind(on_save=lambda inst, v, r: setattr(self.expiry_date, "text", v.strftime("%d/%m/%Y")))
        dp_.open()

    # â”€â”€ Misc callbacks â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _on_description_text(self, instance, value):
        if value != value.upper():
            cur = instance.cursor
            instance.text = value.upper()
            instance.cursor = cur

    def _set_weight_state(self, active):
        active = bool(active)
        if hasattr(self, "is_sold_by_weight_switch"):
            self.is_sold_by_weight_switch.active = active
        self._on_weight_switch_toggle(self.is_sold_by_weight_switch, active)

    def _set_pack_sale_state(self, active):
        active = bool(active)
        if hasattr(self, "allow_pack_sale_switch"):
            self.allow_pack_sale_switch.active = active
        self._on_pack_sale_toggle(self.allow_pack_sale_switch, active)

    def _toggle_weight_button(self, instance):
        current = bool(getattr(self.is_sold_by_weight_switch, "active", False))
        self._set_weight_state(not current)

    def _toggle_pack_sale_button(self, instance):
        if getattr(self, "pack_sale_state_btn", None) and self.pack_sale_state_btn.disabled:
            return
        current = bool(getattr(self.allow_pack_sale_switch, "active", False))
        self._set_pack_sale_state(not current)

    def _on_weight_switch_toggle(self, instance, active):
        if not hasattr(self, "weight_state_btn"):
            return
        self.weight_state_btn.text = "ATIVO" if active else "INATIVO"
        self.weight_state_btn.md_bg_color = (
            (*self.COLOR_SUCCESS[:3], 0.95) if active else (0.45, 0.45, 0.48, 1)
        )
        if hasattr(self, "weight_switch_layout"):
            self.weight_switch_layout.md_bg_color = (
                (self.COLOR_PRIMARY[0], self.COLOR_PRIMARY[1], self.COLOR_PRIMARY[2], 0.18)
                if active else self.COLOR_CARD_ALT
            )
        if hasattr(self, "pack_sale_state_btn"):
            self.pack_sale_state_btn.disabled = bool(active)
        if hasattr(self, "units_per_package_input"):
            self.units_per_package_input.disabled = bool(active)
        if active:
            if hasattr(self, "units_per_package_input"):
                self.units_per_package_input.text = ""
            self._set_pack_sale_state(False)

    def _on_pack_sale_toggle(self, instance, active):
        if not hasattr(self, "pack_sale_state_btn"):
            return
        self.pack_sale_state_btn.text = "ATIVO" if active else "INATIVO"
        self.pack_sale_state_btn.md_bg_color = (
            (*self.COLOR_SUCCESS[:3], 0.95) if active else (0.45, 0.45, 0.48, 1)
        )
        if hasattr(self, "pack_sale_layout"):
            self.pack_sale_layout.md_bg_color = (
                (self.COLOR_PRIMARY[0], self.COLOR_PRIMARY[1], self.COLOR_PRIMARY[2], 0.18)
                if active else self.COLOR_CARD_ALT
            )

    # â”€â”€ Scanner â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _toggle_scanner(self, instance):
        if not self.scanning:
            if not self._ensure_scanner_dependencies():
                return
            self.scanning = True
            self.scan_btn.icon        = "barcode-off"
            self.scan_btn.md_bg_color = self.COLOR_ERROR
            self._set_status("Scanner Ativo", self.COLOR_PRIMARY)
            Clock.schedule_interval(self._update_camera, 1.0 / 15.0)
        else:
            self._stop_scanner()

    def _stop_scanner(self):
        self.scanning = False
        self.scan_btn.icon        = "barcode-scan"
        self.scan_btn.md_bg_color = self.COLOR_PRIMARY
        self._set_status("Inativo", self.COLOR_GRAY)
        Clock.unschedule(self._update_camera)
        if self.camera_capture:
            self.camera_capture.release()
            self.camera_capture = None
        self.camera_image.texture = None

    def _update_camera(self, dt):
        if not self.scanning: return
        if self.camera_capture is None:
            if not self._init_camera(): return
        ret, frame = self.camera_capture.read()
        if not ret: return
        self._display_frame(self._process_frame(frame))

    def _ensure_scanner_dependencies(self):
        try:
            self._load_vision_modules()
            return True
        except RuntimeError as exc:
            self.scanning = False
            self.scan_btn.icon = "barcode-scan"
            self.scan_btn.md_bg_color = self.COLOR_PRIMARY
            self._set_status("Scanner indisponivel", self.COLOR_ERROR)
            self._show_snackbar(str(exc), self.COLOR_ERROR)
            return False

    def _load_vision_modules(self):
        if self._vision_modules is None:
            self._vision_modules = get_vision_dependencies()
        return self._vision_modules

    def _init_camera(self):
        try:
            cv2, _np, _decode = self._load_vision_modules()
            self.camera_capture = cv2.VideoCapture(self.current_camera)
            self.camera_capture.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
            self.camera_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            if not self.camera_capture.isOpened():
                self._set_status("Erro na Camera", self.COLOR_ERROR)
                self._stop_scanner(); return False
            self.last_barcode = None; self.last_barcode_time = 0
            return True
        except Exception as e:
            print(f"[Scanner] {e}"); return False

    def _process_frame(self, frame):
        cv2, np, decode = self._load_vision_modules()
        now   = time.time()
        frame = cv2.convertScaleAbs(frame, alpha=1.2, beta=10)
        codes = decode(frame)
        for code in codes:
            try:
                val = "".join(c for c in code.data.decode("utf-8") if c.isprintable()).strip()
                if val == self.last_barcode and (now - self.last_barcode_time) < 2: continue
                self.last_barcode = val; self.last_barcode_time = now
                self.barcode_input.text = val
                self._play_beep()
                self._set_status("Detectado!", self.COLOR_SUCCESS)
                if not self.api_manager.is_loading:
                    self.api_manager.search_enriched(val, on_partial=self._on_api_partial, on_complete=self._on_api_complete)
                if len(code.polygon) == 4:
                    pts = np.array([(p.x, p.y) for p in code.polygon], dtype=np.int32)
                    cv2.polylines(frame, [pts], True, (0, 255, 0), 3)
                x, y, w, h = code.rect
                cv2.putText(frame, val, (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)
            except Exception as e:
                print(f"[Scanner] {e}")
        if not codes and (now - self.last_barcode_time) > 2.5 and not self.api_manager.is_loading:
            self._set_status("Scanner Ativo", self.COLOR_PRIMARY)
        return frame

    def _display_frame(self, frame):
        cv2, _np, _decode = self._load_vision_modules()
        buf = cv2.flip(frame, 0).tobytes()
        tex = Texture.create(size=(frame.shape[1], frame.shape[0]), colorfmt="bgr")
        tex.blit_buffer(buf, colorfmt="bgr", bufferfmt="ubyte")
        self.camera_image.texture = tex

    def _switch_camera(self, instance):
        was = self.scanning
        if self.scanning: self._stop_scanner()
        self.current_camera = (self.current_camera + 1) % 3
        self._show_snackbar(f"Camera {self.current_camera}", self.COLOR_PRIMARY)
        if was: Clock.schedule_once(lambda dt: self._restart_scanner(), 0.3)

    def _restart_scanner(self):
        self.scanning = True
        self.scan_btn.icon        = "barcode-off"
        self.scan_btn.md_bg_color = self.COLOR_ERROR
        self._set_status("Scanner Ativo", self.COLOR_PRIMARY)
        Clock.schedule_interval(self._update_camera, 1.0 / 15.0)

    def _on_barcode_manual_entry(self, instance):
        barcode = instance.text.strip()
        if barcode and len(barcode) >= 8:
            self.api_manager.search_enriched(barcode, on_partial=self._on_api_partial, on_complete=self._on_api_complete)

    # â”€â”€ Category lookup thread â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _search_category_if_missing(self, barcode):
        if not barcode or len(barcode) < 8: return
        needs_cat = not self.category_field.text.strip()
        needs_qty = not self.package_quantity.text.strip()
        if not (needs_cat or needs_qty): return
        self._category_lookup_token += 1
        token = self._category_lookup_token
        self._category_lookup_barcode  = barcode
        self._category_lookup_inflight = True
        Thread(target=self._category_lookup_worker, args=(barcode, token, needs_cat, needs_qty), daemon=True).start()

    def _category_lookup_worker(self, barcode, token, needs_cat, needs_qty):
        found_cat = False; found_qty = False
        for _, api in self._category_sources:
            try: result = api.fetch(barcode)
            except Exception: result = None
            if not result: continue
            new_cat = new_qty = None
            if needs_cat and not found_cat:
                cat = result.get("category")
                if cat: found_cat = True; new_cat = cat
            if needs_qty and not found_qty:
                qty = result.get("quantity") or self._extract_quantity_from_text(result.get("name",""))
                if qty: found_qty = True; new_qty = qty
            if new_cat or new_qty:
                Clock.schedule_once(lambda dt, c=new_cat, q=new_qty, t=token, b=barcode: self._apply_lookup_from_api(c,q,t,b), 0)
            if (not needs_cat or found_cat) and (not needs_qty or found_qty): break
        Clock.schedule_once(lambda dt, t=token, b=barcode: self._category_lookup_done(t,b), 0)

    def _apply_lookup_from_api(self, category, quantity, token, barcode):
        if token != self._category_lookup_token or barcode != self._category_lookup_barcode: return
        if category and not self.category_field.text.strip(): self._set_category(category)
        if quantity  and not self.package_quantity.text.strip(): self.package_quantity.text = str(quantity)

    def _category_lookup_done(self, token, barcode):
        if token == self._category_lookup_token and barcode == self._category_lookup_barcode:
            self._category_lookup_inflight = False

    # â”€â”€ Save / Validate â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _save_product(self, instance):
        if not self._validate_fields(): return
        expiry = self._process_expiry_date()
        if expiry is False: return
        raw = self.barcode_input.text.strip()
        barcode = "".join(c for c in raw if c.isprintable()).strip() if raw else None
        self._save_to_database(barcode, expiry, self.is_sold_by_weight_switch.active)

    def _validate_fields(self):
        checks = [
            (self.description.text.strip(),                                              "Descricao obrigatoria!"),
            (self.category_field.text.strip() and self.category_field.text != "Categoria *", "Selecione uma categoria!"),
            (self.existing_stock.text.strip(),                                           "Estoque atual obrigatorio!"),
            (self.sale_price.text.strip(),                                               "Preco de venda obrigatorio!"),
            (self.total_purchase_price.text.strip(),                                     "Preco total obrigatorio!"),
            (self.unit_purchase_price.text.strip(),                                      "Preco unitario obrigatorio!"),
        ]
        for cond, msg in checks:
            if not cond: self._show_snackbar(msg, self.COLOR_ERROR); return False
        if self.is_sold_by_weight_switch.active and getattr(self.allow_pack_sale_switch, "active", False):
            self._show_snackbar("Produto por KG nao pode vender embalagem fechada.", self.COLOR_ERROR)
            return False
        if getattr(self.allow_pack_sale_switch, "active", False):
            raw_units = self.units_per_package_input.text.strip()
            try:
                units = int(raw_units)
            except (TypeError, ValueError):
                units = 0
            if units < 2:
                self._show_snackbar("Unidades por embalagem deve ser >= 2.", self.COLOR_ERROR)
                return False
        return True

    def _process_expiry_date(self):
        text = self.expiry_date.text.strip()
        if not text: return None
        try: return datetime.strptime(text, "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            self._show_snackbar("Data invalida! Use DD/MM/AAAA", self.COLOR_ERROR)
            return False

    def _save_to_database(self, barcode, expiry, is_sold_by_weight):
        from database.provider import get_db
        db = get_db()
        package_quantity = self.package_quantity.text.strip() or None
        allow_pack_sale = bool(getattr(self.allow_pack_sale_switch, "active", False))
        units_raw = self.units_per_package_input.text.strip()
        units_per_package = int(units_raw) if units_raw.isdigit() else None
        if not allow_pack_sale:
            units_per_package = None

        def _last_error():
            fn = getattr(db, "last_error", None)
            if callable(fn):
                try:
                    return fn()
                except Exception:
                    return None
            return None

        def _needs_legacy_retry(err):
            if not err:
                return False
            text = str(err).lower()
            return (
                "unexpected keyword argument" in text
                and ("units_per_package" in text or "allow_pack_sale" in text)
            )

        def _do_update(include_pack_fields=True):
            kwargs = {"package_quantity": package_quantity}
            if include_pack_fields:
                kwargs["units_per_package"] = units_per_package
                kwargs["allow_pack_sale"] = allow_pack_sale
            return db.update_product(
                self.product[0], self.description.text.strip(), self.category_field.text,
                float(self.existing_stock.text), sold, float(self.sale_price.text),
                float(self.total_purchase_price.text), float(self.unit_purchase_price.text),
                barcode, expiry, is_sold_by_weight, **kwargs,
            )

        def _do_add(include_pack_fields=True):
            kwargs = {"package_quantity": package_quantity}
            if include_pack_fields:
                kwargs["units_per_package"] = units_per_package
                kwargs["allow_pack_sale"] = allow_pack_sale
            return db.add_product(
                self.description.text.strip(), self.category_field.text,
                float(self.existing_stock.text), sold, float(self.sale_price.text),
                float(self.total_purchase_price.text), float(self.unit_purchase_price.text),
                barcode, expiry, is_sold_by_weight, **kwargs,
            )

        try:
            sold = float(self.sold_stock.text.strip() or "0")
            if self.product:
                _do_update(include_pack_fields=True)
                err = _last_error()
                if _needs_legacy_retry(err):
                    _do_update(include_pack_fields=False)
                    err = _last_error()
                    if not err:
                        self._show_snackbar(
                            "Servidor desatualizado: dados de embalagem nao foram salvos. Reinicie o server.",
                            self.COLOR_WARNING,
                        )
                if err:
                    raise RuntimeError(err)
                self._show_snackbar("Produto atualizado!", self.COLOR_SUCCESS)
                Clock.schedule_once(lambda dt: self.dismiss(), 1.5)
            else:
                product_id = _do_add(include_pack_fields=True)
                err = _last_error()
                if _needs_legacy_retry(err):
                    product_id = _do_add(include_pack_fields=False)
                    err = _last_error()
                    if not err:
                        self._show_snackbar(
                            "Servidor desatualizado: dados de embalagem nao foram salvos. Reinicie o server.",
                            self.COLOR_WARNING,
                        )
                if err or not product_id:
                    raise RuntimeError(err or "Falha ao cadastrar produto.")
                self._show_snackbar("Produto cadastrado!", self.COLOR_SUCCESS)
                Clock.schedule_once(lambda dt: self._clear_fields(), 1.5)
            self.admin_screen.load_products()
        except Exception as e:
            self._show_snackbar(f"Erro ao salvar produto: {e}", self.COLOR_ERROR)
        finally: db.close()

    def _clear_fields(self):
        for f in (self.barcode_input, self.sku_input, self.expiry_date, self.description,
                  self.existing_stock, self.sale_price, self.total_purchase_price,
                  self.unit_purchase_price, self.category_field, self.package_quantity,
                  self.units_per_package_input):
            f.text = ""
        self.sold_stock.text = "0"
        self._set_weight_state(False)
        self._set_pack_sale_state(False)
        self._category_lookup_inflight = False
        self._category_lookup_barcode  = None
        self._category_lookup_token    = 0
        self._auto_calc_done           = False
        self._discount_base_price      = None
        self._applying_price_action    = False
        self._update_price_actions_state()
        self.barcode_input.focus = True

    def _populate_fields(self):
        p = self.product
        self.description.text          = p[1]
        self.category_field.text       = p[11] if len(p) > 11 else ""
        self.existing_stock.text       = str(p[2])
        self.sold_stock.text           = str(p[3])
        self.sale_price.text           = str(p[4])
        self.total_purchase_price.text = str(p[5])
        self.unit_purchase_price.text  = str(p[6])
        self._discount_base_price      = None
        self._auto_calc_done           = True
        if len(p) > 21 and p[21]: self.package_quantity.text = str(p[21])
        if len(p) > 22 and p[22]: self.sku_input.text        = str(p[22])
        if len(p) > 23 and p[23] not in (None, ""):
            self.units_per_package_input.text = str(int(float(p[23])))
        if len(p) > 12 and p[12]: self.barcode_input.text    = str(p[12])
        if len(p) > 13 and p[13]:
            try: self.expiry_date.text = datetime.strptime(str(p[13]), "%Y-%m-%d").strftime("%d/%m/%Y")
            except ValueError: self.expiry_date.text = str(p[13])
        is_weight = bool(p[15]) if len(p) > 15 else False
        self._set_weight_state(is_weight)
        self._set_pack_sale_state(bool(p[24]) if (len(p) > 24 and not is_weight) else False)
        self._update_price_actions_state()

    # â”€â”€ Beep â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    @staticmethod
    def _load_beep_sound():
        try:
            s = SoundLoader.load("assets/sounds/beep.wav")
            if s: s.volume = 0.7
            return s
        except Exception: return None

    def _play_beep(self):
        if not self.beep_sound: return
        try:
            if self.beep_sound.state == "play": self.beep_sound.stop()
            self.beep_sound.play()
        except Exception: pass

    # â”€â”€ Snackbar / status â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _show_snackbar(self, message, color):
        toast = BoxLayout(size_hint=(None, None), size=(dp(320), dp(52)), padding=dp(14), opacity=0)
        with toast.canvas.before:
            Color(*color)
            bg = RoundedRectangle(pos=toast.pos, size=toast.size, radius=[dp(8)])
        toast.bind(pos=lambda i,v: setattr(bg,"pos",i.pos), size=lambda i,v: setattr(bg,"size",i.size))
        lbl = Label(text=message, color=(1,1,1,1), font_size=sp(13), halign="center", valign="middle")
        lbl.bind(size=lbl.setter("text_size"))
        toast.add_widget(lbl)
        if hasattr(self, "content") and self.content:
            toast.pos = (self.content.center_x - toast.width/2, self.content.y + dp(16))
            self.content.add_widget(toast)
            Animation(opacity=1, duration=0.25).start(toast)
            def _rm(dt):
                a = Animation(opacity=0, duration=0.25)
                a.bind(on_complete=lambda *_: self.content.remove_widget(toast))
                a.start(toast)
            Clock.schedule_once(_rm, 2.2)

    def _set_status(self, text, color):
        self.scanner_status.text  = text
        self.scanner_status.color = color

    def on_dismiss(self):
        if self.scanning: self._stop_scanner()
        Window.unbind(on_resize=self._on_window_resize)

