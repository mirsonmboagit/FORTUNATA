import time
import re
import unicodedata
from datetime import datetime
import calendar
from threading import Lock, Thread

from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.image import Image
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.graphics.texture import Texture
from kivy.graphics import Color, RoundedRectangle
from kivy.core.window import Window
from kivy.uix.modalview import ModalView
from kivy.core.audio import SoundLoader
from kivy.clock import Clock
from kivy.animation import Animation
from kivy.metrics import dp, sp
from kivy.app import App

from ui.components.native_widgets import (
    NativeButton as MDRaisedButton,
    NativeIcon as MDIcon,
    NativeCard as MDCard,
    NativeDatePicker as MDDatePicker,
    NativeDialog as MDDialog,
    NativeDropdownMenu as MDDropdownMenu,
    NativeFlatButton as MDFlatButton,
    NativeSwitch as MDSwitch,
    NativeTextField as MDTextField,
)
from ui.components.tooltip_widgets import (
    TooltipFlatButton,
    TooltipIconButton,
    TooltipRaisedButton,
    TooltipTextField,
)
from utils.core.focus_navigation import FormKeyboardController
from utils.core.i18n import correct_portuguese_text

from utils.business.vat import (
    DEFAULT_VAT_RULE_CODE,
    VAT_RULE_CHOICES,
    describe_vat_choice,
    get_vat_choice_label,
)
from utils.hardware.vision import get_vision_dependencies


def _row(*widgets, spacing=dp(8), height=dp(60)):
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
        w.size_hint_x = 1
        row.add_widget(w)
    return row


def _describe_dependency_error(exc, prefix):
    missing_name = getattr(exc, "name", "")
    if missing_name:
        return f"{prefix}: dependencia em falta ({missing_name})"
    text = str(exc or "").strip()
    if not text:
        text = exc.__class__.__name__
    return f"{prefix}: {text}"


class _UnavailableAPIManager:
    def __init__(self, reason, on_status=None):
        self.is_loading = False
        self._reason = reason
        self._on_status = on_status
        self._notified = False

    def _notify(self):
        if self._notified or not callable(self._on_status):
            return
        self._notified = True
        Clock.schedule_once(lambda dt, msg=self._reason: self._on_status(msg), 0)

    def search(self, barcode, force_external=False):
        self._notify()

    def search_enriched(
        self,
        barcode,
        required_fields=None,
        on_partial=None,
        on_complete=None,
        force_external=False,
    ):
        self._notify()


def _build_api_manager(database, on_success, on_failure, on_status):
    try:
        from api.api_manager import APIManager

        return APIManager(
            database=database,
            on_success=on_success,
            on_failure=on_failure,
            on_status=on_status,
        )
    except Exception as exc:
        print(f"[ProductForm] APIManager indisponivel: {exc}")
        reason = _describe_dependency_error(exc, "Auto preenchimento indisponivel")
        return _UnavailableAPIManager(reason, on_status=on_status)


def _build_category_sources():
    source_defs = (
        ("Open Food Facts", "api.api_openfoodfacts", "OpenFoodFactsAPI"),
        ("Bazara", "api.api_bazara", "BazaraAPI"),
        ("Ranxo", "api.api_ranxo", "RanxoAPI"),
        ("UPCitemdb", "api.api_upcitemdb", "UPCitemdbAPI"),
    )
    sources = []
    for label, module_name, class_name in source_defs:
        try:
            module = __import__(module_name, fromlist=[class_name])
            source_class = getattr(module, class_name)
            sources.append((label, source_class()))
        except Exception as exc:
            print(f"[ProductForm] Fonte {label} indisponivel: {exc}")
    return sources


class ProductForm(Screen):
    COLOR_PRIMARY    = (0.2,  0.6,  0.86, 1)
    COLOR_SUCCESS    = (0.27, 0.7,  0.42, 1)
    COLOR_ERROR      = (0.85, 0.35, 0.35, 1)
    COLOR_WARNING    = (0.85, 0.45, 0.3,  1)
    COLOR_GRAY       = (0.65, 0.65, 0.65, 1)
    COLOR_TEXT       = (0.25, 0.25, 0.25, 1)
    COLOR_CARD       = (0.88, 0.88, 0.88, 1)
    COLOR_CARD_ALT   = (0.92, 0.92, 0.92, 1)

    # MDTextField necessita de espaco vertical proprio para o texto de ajuda
    # e a linha de contorno. A linha do formulario e deliberadamente maior
    # que o input, criando uma separacao visual sem aumentar o campo.
    FIELD_H      = dp(48)
    ROW_H        = dp(60)
    BUTTON_H     = dp(40)
    FONT_SIZE    = sp(13)
    FONT_SIZE_SM = sp(12)

    def __init__(self, admin_screen, product=None, **kwargs):
        kwargs.setdefault("name", "product_form")
        super().__init__(**kwargs)

        self.admin_screen = admin_screen
        self.product      = product

        self.scanning          = False
        self.camera_capture    = None
        self.current_camera    = 0
        self.last_barcode      = None
        self.last_barcode_time = 0
        # -- ALTERAÇÃO 1: removido _scanner_auto_start_ev (auto-start eliminado) --
        self.beep_sound        = None
        self._beep_sound_loaded = False
        self._vision_modules   = None

        self.api_manager = None
        self._api_manager_lock = Lock()
        self._lazy_dependencies_started = False
        self._apply_theme_tokens()

        self._category_sources = None
        self._category_sources_lock = Lock()
        self._category_lookup_inflight = False
        self._category_lookup_barcode  = None
        self._category_lookup_token    = 0
        self._selected_vat_rule_code  = DEFAULT_VAT_RULE_CODE
        self._vat_menu                = None
        self._barcode_context         = None
        self._barcode_request_id      = 0
        self._queued_barcode_request  = None
        self._barcode_lookup_status   = None

        self._calculating                = False
        self._discount_base_price        = None
        self._applying_price_action      = False
        self._auto_unit_purchase_price   = False
        self._auto_total_purchase_price  = False
        self._auto_sale_price            = False
        self._cost_source_field          = None
        self._business_rules             = self._load_business_rules()
        self._business_rules_dialog      = None
        self._custom_field_widgets       = {}
        self._custom_field_definitions   = self._load_custom_field_definitions()
        self._custom_field_rows          = []

        self._price_discount_buttons = []
        self._price_revert_btn       = None
        self._cancel_btn             = None
        self._save_btn               = None
        self._content_layout         = None
        self._content_scroll         = None
        self._camera_section         = None
        self._form_section           = None
        self._form_rows              = []
        self._camera_card            = None
        self._compact_layout         = None
        self._shortcut_help_dialog   = None
        self._field_navigation       = None

        self._setup_page()
        self._build_ui()
        self._setup_keyboard_navigation()

        if self.product:
            self._populate_fields()

        Window.bind(on_resize=self._on_window_resize)

    # -- Pagina -------------------------------------------------------------
    def _setup_page(self):
        """O formulario ocupa uma tela completa, sem limite de popup."""
        self.size_hint = (1, 1)
        self._apply_page_layout()

    def _apply_page_layout(self):
        self._update_responsive_layout()

    # -- Theme --------------------------------------------------------------
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
        # Campo vazio não é erro. O visual outlined neutro aproxima-se do
        # MDTextField e deixa o vermelho reservado à validação efetiva.
        app = App.get_running_app()
        tokens = getattr(app, "theme_tokens", {}) if app else {}
        field.md_bg_color = tokens.get("surface_alt", self.COLOR_CARD_ALT)
        field.radius = [dp(10)]
        field.padding = [dp(12), dp(10), dp(12), dp(8)]
        field.line_color_normal = tokens.get("outline", (0.45, 0.48, 0.55, 1))
        field.line_color_focus = self.COLOR_PRIMARY
        field.hint_text_color = self.COLOR_GRAY
        field.foreground_color = self.COLOR_TEXT
        if hasattr(field, "cursor_color"):
            field.cursor_color = self.COLOR_PRIMARY
        self._update_field_color(field, field.text)
        field.bind(text=self._update_field_color)

    def _update_field_color(self, field, text):
        filled = bool((text or "").strip())
        app = App.get_running_app()
        tokens = getattr(app, "theme_tokens", {}) if app else {}
        neutral = tokens.get("outline", (0.45, 0.48, 0.55, 1))
        # Uma presença discreta de sucesso apenas nos campos preenchidos;
        # mantém o foco no azul principal e elimina o aspecto de formulário
        # permanentemente em erro.
        field.hint_text_color = self.COLOR_GRAY
        field.line_color_normal = (*self.COLOR_SUCCESS[:3], 0.72) if filled else neutral
        field.line_color_focus = self.COLOR_PRIMARY
        field.foreground_color = self.COLOR_TEXT
        field.text_color = self.COLOR_TEXT
        field.text_color_normal = self.COLOR_TEXT
        field.text_color_focus = self.COLOR_TEXT

    # -- Build UI -----------------------------------------------------------
    def _build_ui(self):
        main_card = MDCard(
            orientation = "vertical",
            padding     = dp(10),
            spacing     = 0,
            radius      = [dp(16)],
            md_bg_color = self.COLOR_CARD,
            elevation   = 0,
        )
        main_card.add_widget(self._build_header())

        self._content_layout = BoxLayout(
            orientation = "horizontal",
            size_hint_y = 1,
            spacing     = dp(10),
            padding     = [dp(10), dp(10), dp(10), dp(10)],
        )
        self._camera_section = self._build_camera_section()
        self._form_section = self._build_form_section()
        self._content_layout.add_widget(self._camera_section)
        self._content_layout.add_widget(self._form_section)
        self._content_scroll.bind(size=lambda *_: self._update_responsive_layout())
        self.bind(size=lambda *_: self._update_responsive_layout())
        main_card.add_widget(self._content_layout)
        self._page_content = main_card
        self.add_widget(main_card)
        self._update_responsive_layout()

    # -- Header -------------------------------------------------------------
    def _build_header(self):
        header = MDCard(
            orientation = "horizontal",
            size_hint_y = None,
            height      = dp(58),
            padding     = [dp(16), dp(8), dp(10), dp(8)],
            radius      = [dp(14)],
            md_bg_color = self.COLOR_PRIMARY,
            elevation   = 2,
        )
        title_label = Label(
            text        = "Adicionar Produto" if not self.product else "Editar Produto",
            color       = (1, 1, 1, 1),
            font_size   = sp(16),
            bold        = True,
            halign      = "left",
            valign      = "middle",
            size_hint_x = 0.9,
        )
        title_label.bind(size=title_label.setter("text_size"))
        rules_btn = TooltipRaisedButton(
            text="Regras",
            theme_text_color="Custom",
            text_color=(1, 1, 1, 1),
            md_bg_color=[1, 1, 1, 0.18],
            radius=[dp(12)],
            size_hint=(None, None),
            size=(dp(110), dp(36)),
            elevation=0,
            tooltip_text="Definir regras comerciais e margem de lucro",
            on_release=lambda *_: self._open_business_rules_dialog(),
            pos_hint={"center_y": 0.5},
        )
        close_btn = TooltipIconButton(
            icon             = "arrow-left",
            theme_text_color = "Custom",
            text_color       = (1, 1, 1, 1),
            md_bg_color      = [1, 1, 1, 0.14],
            radius           = [dp(18)],
            size_hint        = (None, None), size=(dp(36), dp(36)),
            hint_text        = "Voltar ao catalogo (Esc)",
            on_release       = self.dismiss,
            pos_hint         = {"center_y": 0.5},
        )
        header.add_widget(title_label)
        header.add_widget(rules_btn)
        header.add_widget(close_btn)
        return header

    # -- Camera -------------------------------------------------------------
    def _build_section_title(self, text):
        """Cabecalho reutilizavel para manter as secoes do formulario alinhadas."""
        row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(40),
            spacing=dp(8),
            padding=[dp(2), 0],
        )
        accent = BoxLayout(
            size_hint=(None, None),
            size=(dp(4), dp(18)),
            pos_hint={"center_y": 0.5},
        )
        with accent.canvas.before:
            from kivy.graphics import Color, RoundedRectangle
            Color(*self.COLOR_PRIMARY)
            accent._accent_rect = RoundedRectangle(
                pos=accent.pos, size=accent.size, radius=[dp(2)],
            )
        accent.bind(
            pos=lambda i, *_: setattr(i._accent_rect, "pos", i.pos),
            size=lambda i, *_: setattr(i._accent_rect, "size", i.size),
        )
        label = Label(
            text=text,
            color=self.COLOR_TEXT,
            font_size=sp(16),
            bold=True,
            halign="left",
            valign="middle",
        )
        label.bind(size=label.setter("text_size"))
        row.add_widget(accent)
        row.add_widget(label)
        return row

    def _build_camera_section(self):
        """Painel fixo do scanner — preview, estado e botoes sempre no mesmo sitio."""
        outer = BoxLayout(
            orientation="vertical",
            spacing=dp(8),
            padding=[dp(10), dp(10), dp(10), dp(10)],
            size_hint=(None, 1),
            width=dp(300),
        )
        self._scanner_panel = outer

        # Titulo do painel
        title = Label(
            text="Scanner",
            font_size=sp(14),
            bold=True,
            color=self.COLOR_TEXT,
            size_hint_y=None,
            height=dp(22),
            halign="left",
            valign="middle",
        )
        title.bind(size=title.setter("text_size"))
        outer.add_widget(title)

        # Cartao do preview (proporcao estavel)
        camera_card = MDCard(
            orientation="vertical",
            size_hint=(1, None),
            height=dp(240),
            radius=[dp(14)],
            elevation=0,
            md_bg_color=(0.10, 0.12, 0.16, 1),
            padding=[dp(4), dp(4), dp(4), dp(4)],
        )
        self._camera_card = camera_card

        preview_root = FloatLayout(size_hint=(1, 1))

        self.camera_image = Image(
            size_hint=(1, 1),
            allow_stretch=True,
            keep_ratio=True,
            pos_hint={"x": 0, "y": 0},
        )
        preview_root.add_widget(self.camera_image)

        # Placeholder escuro (so visivel com scanner parado)
        self._camera_placeholder = BoxLayout(
            orientation="vertical",
            spacing=dp(6),
            size_hint=(1, 1),
            pos_hint={"x": 0, "y": 0},
        )
        with self._camera_placeholder.canvas.before:
            self._ph_bg_color = Color(0.10, 0.12, 0.16, 1)
            self._ph_bg_rect = RoundedRectangle(radius=[dp(10)])

        def _sync_ph(*_a):
            self._ph_bg_rect.pos = self._camera_placeholder.pos
            self._ph_bg_rect.size = self._camera_placeholder.size

        self._camera_placeholder.bind(pos=_sync_ph, size=_sync_ph)

        ph_icon = Label(
            text="[  ]",
            font_size=sp(28),
            color=(0.45, 0.52, 0.62, 1),
            size_hint_y=None,
            height=dp(36),
            halign="center",
        )
        try:
            ph_icon = MDIcon(
                icon="camera-off-outline",
                theme_text_color="Custom",
                text_color=(0.45, 0.52, 0.62, 1),
                size_hint=(None, None),
                size=(dp(36), dp(36)),
                pos_hint={"center_x": 0.5},
            )
        except Exception:
            pass

        ph_text = Label(
            text="Camara desligada\nToque no botao para iniciar",
            font_size=sp(12),
            color=(0.55, 0.62, 0.72, 1),
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=dp(40),
        )
        ph_text.bind(size=ph_text.setter("text_size"))

        self._camera_placeholder.add_widget(BoxLayout(size_hint_y=0.35))
        self._camera_placeholder.add_widget(ph_icon)
        self._camera_placeholder.add_widget(ph_text)
        self._camera_placeholder.add_widget(BoxLayout(size_hint_y=0.35))
        preview_root.add_widget(self._camera_placeholder)

        camera_card.add_widget(preview_root)
        outer.add_widget(camera_card)

        # Estado
        self.scanner_status = Label(
            text="Scanner parado",
            size_hint_y=None,
            height=dp(22),
            color=self.COLOR_GRAY,
            font_size=sp(12),
            bold=True,
            halign="center",
            valign="middle",
        )
        outer.add_widget(self.scanner_status)

        # Botoes centrados
        btn_row = BoxLayout(
            size_hint=(None, None),
            height=dp(44),
            width=dp(104),
            spacing=dp(12),
        )
        self.scan_btn = TooltipIconButton(
            icon="barcode-scan",
            theme_text_color="Custom",
            text_color=(1, 1, 1, 1),
            md_bg_color=self.COLOR_PRIMARY,
            size_hint=(None, None),
            size=(dp(44), dp(44)),
            radius=[dp(22)],
            elevation=2,
            hint_text="Iniciar ou parar scanner (Alt+B)",
            on_release=self._toggle_scanner,
        )
        switch_btn = TooltipIconButton(
            icon="camera-switch",
            theme_text_color="Custom",
            text_color=(1, 1, 1, 1),
            md_bg_color=(0.35, 0.38, 0.45, 1),
            size_hint=(None, None),
            size=(dp(44), dp(44)),
            radius=[dp(22)],
            elevation=1,
            hint_text="Trocar camera (Alt+M)",
            on_release=self._switch_camera,
        )
        btn_row.add_widget(self.scan_btn)
        btn_row.add_widget(switch_btn)
        wrapper = AnchorLayout(size_hint_y=None, height=dp(52))
        wrapper.add_widget(btn_row)
        outer.add_widget(wrapper)

        hint = Label(
            text="Posicione o codigo de barras na area da camara",
            size_hint_y=None,
            height=dp(28),
            color=self.COLOR_GRAY,
            font_size=sp(11),
            halign="center",
            valign="middle",
        )
        hint.bind(size=hint.setter("text_size"))
        outer.add_widget(hint)

        # Espaco flexivel no fundo — mantem o bloco alinhado ao topo
        outer.add_widget(BoxLayout(size_hint_y=1))
        return outer

    def _build_form_section(self):
        self._create_form_fields()

        sec = MDCard(
            orientation="vertical",
            size_hint_x=1,
            padding=dp(10),
            spacing=dp(8),
            radius=[dp(12)],
            md_bg_color=self.COLOR_CARD_ALT,
            line_color=(*self.COLOR_PRIMARY[:3], 0.16),
            line_width=1,
            elevation=1,
        )
        sec.add_widget(self._build_section_title("Informações do produto"))

        self._form_rows = [
            _row(self.barcode_input, self.sku_input),
            _row(self.description, self.category_layout),
            _row(self.vat_rule_layout, self.vat_mode_layout),
            _row(self.package_quantity, self.expiry_date_layout),
            _row(self.units_per_package_input, self.pack_sale_layout),
            _row(self.existing_stock, self.sold_stock),
            _row(self.unit_purchase_price, self.total_purchase_price),
            _row(self.sale_price, self.weight_switch_layout),
            _row(self.produce_mode_btn, self.sack_weight_input),
        ]
        # Somente esta area rola. Cabecalho, scanner e botoes de acao ficam
        # fixos, evitando que a roda do rato desloque a pagina inteira.
        self._content_scroll = ScrollView(
            do_scroll_x=False,
            do_scroll_y=True,
            bar_width=dp(6),
            scroll_type=["bars", "content"],
        )
        self._form_content = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(8),
            padding=[0, 0, dp(4), 0],
        )
        for form_row in self._form_rows:
            self._form_content.add_widget(form_row)
        self._form_content.add_widget(self._price_actions_layout)
        self._custom_fields_section = self._build_custom_fields_section()
        self._form_content.add_widget(self._custom_fields_section)
        self._content_scroll.add_widget(self._form_content)
        sec.add_widget(self._content_scroll)
        sec.add_widget(self._build_action_buttons())

        return sec

    # -- Campos -------------------------------------------------------------
    def _create_form_fields(self):
        h  = self.FIELD_H
        fs = self.FONT_SIZE

        def _tooltip(hint, shortcut=None):
            hint = str(hint or "").strip()
            shortcut = str(shortcut or "").strip()
            return f"{hint} ({shortcut})" if shortcut else hint

        def _f(hint, readonly=False, inp_filter=None, size_hint_x=1, shortcut=None):
            f = TooltipTextField(
                hint_text         = hint,
                tooltip_text      = _tooltip(hint, shortcut),
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

        self.barcode_input = _f("Cod. Barras (opcional)", shortcut="Ctrl+B")
        self.barcode_input.bind(on_text_validate=self._on_barcode_manual_entry)

        self.sku_input = _f("SKU (auto)", readonly=True)

        self.package_quantity = _f("Unidade de medida ex: 500ml")
        self.units_per_package_input = _f("Unidades por embalagem", inp_filter="int")

        self.description = _f("Nome do produto *", shortcut="Ctrl+N")
        self.description.bind(text=self._on_description_text)

        self.category_layout = BoxLayout(
            orientation="horizontal", size_hint=(1, None), height=h, spacing=dp(4),
        )
        self.category_field = _f("Categoria *", shortcut="Alt+C")
        dropdown_btn = TooltipIconButton(
            icon="menu-down", theme_text_color="Custom", text_color=(1,1,1,1),
            md_bg_color=self.COLOR_PRIMARY, size_hint=(None, None), size=(dp(36), dp(36)),
            radius=[dp(18)], elevation=1,
            hint_text="Selecionar categoria (Alt+C)",
            pos_hint={"center_y": 0.5}, on_release=self._open_category_menu,
        )
        add_cat_btn = TooltipIconButton(
            icon="plus", theme_text_color="Custom", text_color=(1,1,1,1),
            md_bg_color=self.COLOR_PRIMARY, size_hint=(None, None), size=(dp(36), dp(36)),
            radius=[dp(18)], elevation=1,
            hint_text="Adicionar categoria",
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

        self.vat_rule_layout = BoxLayout(
            orientation="horizontal", size_hint=(1, None), height=h, spacing=dp(4),
        )
        self.vat_rule_field = _f("Criterio de IVA", readonly=True, shortcut="Alt+I")
        self.vat_rule_field.text = get_vat_choice_label(self._selected_vat_rule_code)
        vat_dropdown_btn = TooltipIconButton(
            icon="menu-down", theme_text_color="Custom", text_color=(1, 1, 1, 1),
            md_bg_color=self.COLOR_PRIMARY,
            size_hint=(None, None), size=(dp(36), dp(36)),
            radius=[dp(18)], elevation=1,
            hint_text="Selecionar criterio de IVA (Alt+I)",
            pos_hint={"center_y": 0.5}, on_release=self._open_vat_menu,
        )
        self._vat_menu = MDDropdownMenu(
            caller=vat_dropdown_btn,
            items=[
                {
                    "text": choice["label"],
                    "on_release": (lambda code=choice["code"]: self._set_vat_rule(code)),
                }
                for choice in VAT_RULE_CHOICES
            ],
            width_mult=4.2,
            max_height=dp(250),
            position="bottom",
        )
        self.vat_rule_layout.add_widget(self.vat_rule_field)
        self.vat_rule_layout.add_widget(vat_dropdown_btn)

        self.vat_mode_layout = BoxLayout(
            orientation="horizontal", size_hint=(1, None), height=h, spacing=dp(4),
        )
        self.vat_mode_field = _f("Preco fiscal", readonly=True)
        self.vat_mode_field.text = describe_vat_choice(self._selected_vat_rule_code)
        self.vat_mode_layout.add_widget(self.vat_mode_field)

        self.existing_stock = _f("Estoque atual *", inp_filter="float", shortcut="Ctrl+E")
        self.existing_stock.bind(text=self._on_stock_or_price_change)

        self.sold_stock = _f("Vendido", readonly=False)
        self.sold_stock.text = "0"

        self.expiry_date_layout = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=h, spacing=dp(4),
        )
        self.expiry_date = _f("Validade DD/MM/AAAA", shortcut="Alt+V")
        cal_btn = TooltipIconButton(
            icon="calendar", theme_text_color="Custom", text_color=self.COLOR_PRIMARY,
            size_hint=(None, None), size=(dp(36), dp(36)),
            radius=[dp(18)], elevation=1,
            hint_text="Escolher validade (Alt+V)",
            pos_hint={"center_y": 0.5}, on_release=self._show_date_picker,
        )
        self.expiry_date_layout.add_widget(self.expiry_date)
        self.expiry_date_layout.add_widget(cal_btn)

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
        self.weight_state_btn = TooltipRaisedButton(
            text="○ INATIVO",
            tooltip_text="Alternar modo KG (Alt+K)",
            md_bg_color=(0.45, 0.45, 0.48, 1),
            text_color=(1, 1, 1, 1),
            font_size=sp(11),
            size_hint=(None, None),
            size=(dp(118), dp(34)),
            radius=[dp(17)], elevation=1,
            on_release=self._toggle_weight_button,
        )
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
        self.pack_sale_state_btn = TooltipRaisedButton(
            text="○ INATIVO",
            tooltip_text="Alternar venda por embalagem (Alt+E)",
            md_bg_color=(0.45, 0.45, 0.48, 1),
            text_color=(1, 1, 1, 1),
            font_size=sp(11),
            size_hint=(None, None),
            size=(dp(118), dp(34)),
            radius=[dp(17)], elevation=1,
            on_release=self._toggle_pack_sale_button,
        )
        self.allow_pack_sale_switch = self.pack_sale_state_btn
        self.allow_pack_sale_switch.active = False
        self.pack_sale_layout.add_widget(pack_lbl)
        self.pack_sale_layout.add_widget(BoxLayout(size_hint_x=1))
        self.pack_sale_layout.add_widget(self.pack_sale_state_btn)
        self._set_pack_sale_state(False)

        self.unit_purchase_price = _f("Preco unit. compra *", inp_filter="float", shortcut="Ctrl+U")
        self.unit_purchase_price.bind(text=self._on_unit_price_change)

        self.total_purchase_price = _f("Preco total compra *", inp_filter="float", shortcut="Ctrl+T")
        self.total_purchase_price.bind(text=self._on_total_price_change)

        self.sale_price = _f("Preco de venda *", inp_filter="float", shortcut="Ctrl+P")
        self.sale_price.bind(text=self._on_sale_price_text_change)

        self.produce_mode_btn = TooltipRaisedButton(
            text="📦  Stock exato",
            tooltip_text="Alternar para sacos com venda avulsa, sem peso obrigatorio",
            md_bg_color=self.COLOR_CARD_ALT,
            theme_text_color="Custom",
            text_color=self.COLOR_TEXT,
            font_size=self.FONT_SIZE_SM,
            size_hint=(1, None),
            height=self.FIELD_H,
            radius=[dp(10)],
            elevation=0,
            line_color=(*self.COLOR_GRAY[:3], 0.35),
            line_width=1,
            on_release=lambda *_: self._set_produce_mode(not self._produce_mode),
        )
        self._produce_mode = False
        self.sack_weight_input = _f("Peso do saco em kg (opcional)", inp_filter="float")
        self.sack_weight_input.disabled = True
        self._price_actions_layout = self._build_price_actions()

    # -- Price actions ------------------------------------------------------
    def _build_price_actions(self):
        layout = BoxLayout(
            orientation="horizontal", size_hint=(1, None), height=dp(40), spacing=dp(8),
        )
        lbl = Label(
            text="Desconto rápido:", color=self.COLOR_GRAY, font_size=self.FONT_SIZE_SM,
            size_hint=(None, 1), width=dp(118), halign="left", valign="middle",
        )
        lbl.bind(size=lambda i, *_: setattr(i, "text_size", (i.width, None)))
        layout.add_widget(lbl)

        self._price_discount_buttons = []
        for pct in (5, 10, 15, 20):
            btn = MDFlatButton(
                text=f"−{pct}%", theme_text_color="Custom",
                text_color=self.COLOR_PRIMARY, md_bg_color=self.COLOR_CARD_ALT,
                size_hint=(None, None), size=(dp(58), dp(34)), font_size=self.FONT_SIZE_SM,
                radius=[dp(17)], line_color=(*self.COLOR_PRIMARY[:3], 0.45), line_width=1,
            )
            btn.bind(on_release=lambda _b, p=pct: self._apply_quick_discount(p))
            layout.add_widget(btn)
            self._price_discount_buttons.append(btn)

        try:
            self._price_revert_btn = MDFlatButton(
                text="Reverter", icon="undo",
                theme_text_color="Custom",
                text_color=self.COLOR_TEXT, md_bg_color=self.COLOR_CARD_ALT,
                size_hint=(None, None), size=(dp(110), dp(34)), font_size=self.FONT_SIZE_SM,
                radius=[dp(17)], line_color=(*self.COLOR_GRAY[:3], 0.40), line_width=1,
            )
        except TypeError:
            self._price_revert_btn = MDFlatButton(
                text="↺  Reverter",
                theme_text_color="Custom",
                text_color=self.COLOR_TEXT, md_bg_color=self.COLOR_CARD_ALT,
                size_hint=(None, None), size=(dp(110), dp(34)), font_size=self.FONT_SIZE_SM,
                radius=[dp(17)], line_color=(*self.COLOR_GRAY[:3], 0.40), line_width=1,
            )
        self._price_revert_btn.bind(on_release=self._restore_sale_price)
        layout.add_widget(self._price_revert_btn)
        layout.add_widget(BoxLayout(size_hint_x=1))
        self._update_price_actions_state()
        return layout

    # -- Action buttons -----------------------------------------------------
    def _build_action_buttons(self):
        layout = BoxLayout(
            orientation="horizontal",
            size_hint=(1, None),
            height=dp(48),
            spacing=dp(12),
            padding=[0, dp(4), 0, 0],
        )
        layout.add_widget(BoxLayout(size_hint_x=1))

        save_label = "Salvar" if self.product else "Cadastrar"
        save_icon = "content-save" if self.product else "plus-circle"

        # Botões com ícone + texto (Tooltip* aceita icon quando disponível)
        try:
            self._cancel_btn = TooltipFlatButton(
                text="Cancelar",
                icon="close-circle-outline",
                theme_text_color="Custom",
                tooltip_text="Cancelar e fechar (Esc)",
                text_color=self.COLOR_TEXT,
                md_bg_color=self.COLOR_CARD_ALT,
                font_size=self.FONT_SIZE,
                size_hint=(None, None),
                size=(dp(140), dp(44)),
                radius=[dp(12)],
                line_color=(*self.COLOR_GRAY[:3], 0.50),
                line_width=1,
                on_release=self.dismiss,
            )
        except TypeError:
            self._cancel_btn = TooltipFlatButton(
                text="✕  Cancelar",
                theme_text_color="Custom",
                tooltip_text="Cancelar e fechar (Esc)",
                text_color=self.COLOR_TEXT,
                md_bg_color=self.COLOR_CARD_ALT,
                font_size=self.FONT_SIZE,
                size_hint=(None, None),
                size=(dp(140), dp(44)),
                radius=[dp(12)],
                line_color=(*self.COLOR_GRAY[:3], 0.50),
                line_width=1,
                on_release=self.dismiss,
            )

        try:
            self._save_btn = TooltipRaisedButton(
                text=save_label,
                icon=save_icon,
                tooltip_text="Salvar produto (Ctrl+S ou Ctrl+Enter)",
                md_bg_color=self.COLOR_SUCCESS,
                theme_text_color="Custom",
                text_color=(1, 1, 1, 1),
                font_size=self.FONT_SIZE,
                size_hint=(None, None),
                size=(dp(150), dp(44)),
                radius=[dp(12)],
                elevation=2,
                on_release=self._save_product,
            )
        except TypeError:
            prefix = "💾  " if self.product else "＋  "
            self._save_btn = TooltipRaisedButton(
                text=prefix + save_label,
                tooltip_text="Salvar produto (Ctrl+S ou Ctrl+Enter)",
                md_bg_color=self.COLOR_SUCCESS,
                theme_text_color="Custom",
                text_color=(1, 1, 1, 1),
                font_size=self.FONT_SIZE,
                size_hint=(None, None),
                size=(dp(150), dp(44)),
                radius=[dp(12)],
                elevation=2,
                on_release=self._save_product,
            )

        layout.add_widget(self._cancel_btn)
        layout.add_widget(self._save_btn)
        return layout

    def _setup_keyboard_navigation(self):
        self._field_navigation = FormKeyboardController(
            host=self,
            fields=[
                self.barcode_input,
                self.description,
                self.category_field,
                self.package_quantity,
                self.expiry_date,
                self.units_per_package_input,
                self.existing_stock,
                self.sold_stock,
                self.unit_purchase_price,
                self.total_purchase_price,
                self.sale_price,
            ],
            initial_field=lambda: self.description if self.product else self.barcode_input,
            on_escape=self.dismiss,
            on_submit=lambda: self._save_product(None),
            shortcuts={
                "ctrl+s": lambda: self._save_product(None),
                "ctrl+h": self._show_keyboard_shortcuts,
                "ctrl+b": lambda: self._focus_form_field(self.barcode_input, select_all=True),
                "ctrl+n": lambda: self._focus_form_field(self.description, select_all=True),
                "ctrl+e": lambda: self._focus_form_field(self.existing_stock, select_all=True),
                "ctrl+u": lambda: self._focus_form_field(self.unit_purchase_price, select_all=True),
                "ctrl+t": lambda: self._focus_form_field(self.total_purchase_price, select_all=True),
                "ctrl+p": lambda: self._focus_form_field(self.sale_price, select_all=True),
                "alt+c": lambda: self._open_category_menu(None),
                "alt+i": lambda: self._open_vat_menu(None),
                "alt+v": lambda: self._show_date_picker(None),
                "alt+k": lambda: self._toggle_weight_button(None),
                "alt+e": lambda: self._toggle_pack_sale_button(None),
                "alt+b": lambda: self._toggle_scanner(None),
                "alt+m": lambda: self._switch_camera(None),
            },
        )

    @staticmethod
    def _focus_form_field(field, select_all=False):
        if field is None or getattr(field, "disabled", False) or getattr(field, "readonly", False):
            return
        try:
            field.focus = True
        except Exception:
            return
        if select_all and hasattr(field, "select_all"):
            Clock.schedule_once(lambda _dt, widget=field: widget.select_all(), 0)

    def _show_keyboard_shortcuts(self):
        dialog = self._shortcut_help_dialog
        if dialog is None:
            help_text = (
                "Ctrl+B: focar codigo de barras\n"
                "Ctrl+N: focar nome\n"
                "Ctrl+E: focar estoque\n"
                "Ctrl+U: focar preco unitario de compra\n"
                "Ctrl+T: focar preco total de compra\n"
                "Ctrl+P: focar preco de venda\n"
                "Ctrl+S ou Ctrl+Enter: salvar\n"
                "Ctrl+H: ver atalhos\n"
                "Alt+C: abrir categorias\n"
                "Alt+I: abrir criterio de IVA\n"
                "Alt+V: abrir validade\n"
                "Alt+K: alternar modo KG\n"
                "Alt+E: alternar venda por embalagem\n"
                "Alt+B: iniciar/parar scanner\n"
                "Alt+M: trocar camera\n"
                "Tab / Shift+Tab: navegar entre campos\n"
                "Esc: fechar formulario"
            )
            dialog = MDDialog(
                title="Atalhos do Formulario",
                text=help_text,
                buttons=[MDFlatButton(text="Fechar")],
            )
            if dialog.buttons:
                dialog.buttons[0].bind(on_release=lambda *_: dialog.dismiss())
            dialog.bind(on_dismiss=lambda *_: setattr(self, "_shortcut_help_dialog", None))
            self._shortcut_help_dialog = dialog
        dialog.open()

    # -- Window resize ------------------------------------------------------
    def _update_responsive_layout(self):
        """Layout limpo e previsivel.

        wide/medium: camera | formulario (horizontal)
        compact:     camera em cima (altura fixa) + formulario em baixo
        """
        if not self._content_layout:
            return

        viewport_width = float(self.width or Window.width or 1000)
        viewport_height = float(self.height or Window.height or 700)

        if viewport_width >= dp(1000):
            mode = "wide"
        elif viewport_width >= dp(780):
            mode = "medium"
        else:
            mode = "compact"

        self._layout_mode = mode
        self._compact_layout = mode == "compact"
        narrow = mode == "compact"

        # --- linhas do formulario ---
        for form_row in getattr(self, "_form_rows", []) or []:
            form_row.orientation = "vertical" if narrow else "horizontal"
            form_row.height = dp(104) if narrow else self.ROW_H
            form_row.spacing = dp(6) if narrow else dp(8)

        for custom_row in getattr(self, "_custom_field_rows", []) or []:
            custom_row.orientation = "vertical" if narrow else "horizontal"
            custom_row.height = dp(104) if narrow else self.ROW_H
            custom_row.spacing = dp(6) if narrow else dp(8)

        custom_defs = getattr(self, "_custom_field_definitions", []) or []
        custom_row_count = (len(custom_defs) + 1) // 2
        custom_row_height = dp(104) if narrow else self.ROW_H
        custom_fields_height = (
            custom_row_count * custom_row_height + max(0, custom_row_count - 1) * dp(7)
        )
        if hasattr(self, "_custom_fields_container"):
            self._custom_fields_container.height = custom_fields_height
        if getattr(self, "_custom_fields_section", None) is not None:
            self._custom_fields_section.height = dp(64) + custom_fields_height

        form_height = (dp(1116) if narrow else dp(720)) + custom_fields_height
        if getattr(self, "_form_content", None) is not None:
            self._form_content.height = form_height

        # --- secoes principais ---
        cam = self._camera_section
        form = self._form_section

        if mode in ("wide", "medium"):
            self._content_layout.orientation = "horizontal"
            self._content_layout.spacing = dp(12)
            self._content_layout.padding = [dp(10), dp(10), dp(10), dp(10)]

            cam_w = dp(300) if mode == "wide" else dp(260)
            if cam is not None:
                cam.size_hint = (None, 1)
                cam.width = cam_w
                cam.height = 0
                cam.pos_hint = {}
            if form is not None:
                form.size_hint = (1, 1)
                form.height = 0

            if self._camera_card is not None:
                # Preview quadratico dentro do painel
                self._camera_card.height = max(dp(200), min(cam_w - dp(28), dp(280)))
        else:
            # compact: camera no topo com altura fixa, form preenche o resto
            self._content_layout.orientation = "vertical"
            self._content_layout.spacing = dp(8)
            self._content_layout.padding = [dp(8), dp(8), dp(8), dp(8)]

            cam_h = min(dp(280), max(dp(220), viewport_height * 0.32))
            if cam is not None:
                cam.size_hint = (1, None)
                cam.width = 0
                cam.height = cam_h
                cam.pos_hint = {}
            if form is not None:
                form.size_hint = (1, 1)
                form.height = 0

            if self._camera_card is not None:
                self._camera_card.height = max(dp(160), cam_h - dp(110))

    def _on_window_resize(self, instance, width, height):
        self._apply_page_layout()

    def _warm_lazy_dependencies(self, *_args):
        if self._lazy_dependencies_started:
            return
        self._lazy_dependencies_started = True
        Thread(target=self._warm_lazy_dependencies_worker, daemon=True).start()

    def _warm_lazy_dependencies_worker(self):
        self._get_api_manager()
        self._get_category_sources()

    def _get_api_manager(self):
        if self.api_manager is not None:
            return self.api_manager
        with self._api_manager_lock:
            if self.api_manager is None:
                self.api_manager = _build_api_manager(
                    database=self.admin_screen.db,
                    on_success=self._on_api_success,
                    on_failure=self._on_api_failure,
                    on_status=self._on_api_status,
                )
        return self.api_manager

    def _get_category_sources(self):
        if self._category_sources is not None:
            return self._category_sources
        with self._category_sources_lock:
            if self._category_sources is None:
                self._category_sources = _build_category_sources()
        return self._category_sources

    def _api_manager_is_loading(self):
        manager = self.api_manager
        return bool(manager is not None and getattr(manager, "is_loading", False))

    def _get_beep_sound(self):
        if not self._beep_sound_loaded:
            self._beep_sound_loaded = True
            self.beep_sound = self._load_beep_sound()
        return self.beep_sound

    # -- API callbacks ------------------------------------------------------
    @staticmethod
    def _sanitize_barcode(value):
        if value is None:
            return ""
        return "".join(c for c in str(value) if c.isprintable()).strip()

    def _barcode_request_is_current(self, request_id, barcode):
        return request_id == self._barcode_request_id and barcode == self._barcode_context

    def _prepare_form_for_barcode(self, barcode):
        if barcode == self._barcode_context:
            return
        self._barcode_context = barcode
        if self.product is None:
            self._clear_fields(preserve_barcode=True, barcode_value=barcode)
            self._barcode_lookup_status = "pending"
        else:
            self.barcode_input.text = barcode

    def _run_barcode_search(self, barcode, request_id):
        self._queued_barcode_request = None
        self._set_status("Buscando...", self.COLOR_PRIMARY)
        self._get_api_manager().search_enriched(
            barcode,
            required_fields=["name", "brand", "category", "quantity", "price"],
            on_partial=lambda source, data, rid=request_id, code=barcode: self._on_api_partial(source, data, rid, code),
            on_complete=lambda data, rid=request_id, code=barcode: self._on_api_complete(data, rid, code),
        )

    def _queue_or_start_barcode_search(self, raw_barcode):
        barcode = self._sanitize_barcode(raw_barcode)
        if len(barcode) < 8:
            return
        self._barcode_request_id += 1
        request_id = self._barcode_request_id
        self._prepare_form_for_barcode(barcode)
        api_manager = self._get_api_manager()
        if api_manager.is_loading:
            self._queued_barcode_request = (request_id, barcode)
            self._set_status("A trocar de codigo...", self.COLOR_WARNING)
            return
        self._run_barcode_search(barcode, request_id)

    def _start_pending_barcode_search(self, *_args):
        if not self._queued_barcode_request:
            return
        api_manager = self._get_api_manager()
        if api_manager.is_loading:
            Clock.schedule_once(self._start_pending_barcode_search, 0.05)
            return
        request_id, barcode = self._queued_barcode_request
        if not self._barcode_request_is_current(request_id, barcode):
            self._queued_barcode_request = None
            return
        self._queued_barcode_request = None
        self._run_barcode_search(barcode, request_id)

    def _on_api_success(self, source, data, request_id=None, barcode=None):
        if request_id is not None and not self._barcode_request_is_current(request_id, barcode):
            return
        if not self._has_usable_product_payload(data):
            self._on_api_failure(request_id=request_id, barcode=barcode)
            return
        self._set_status(f"OK: {source}", self.COLOR_PRIMARY)
        self._fill_fields(data)
        self._show_snackbar(f"Dados de {source}", self.COLOR_SUCCESS)

    def _on_api_partial(self, source, data, request_id=None, barcode=None):
        if request_id is not None and not self._barcode_request_is_current(request_id, barcode):
            return
        if not self._has_usable_product_payload(data):
            return
        self._set_status(f"{source}...", self.COLOR_PRIMARY)
        self._fill_fields(data)

    def _on_api_complete(self, data, request_id=None, barcode=None):
        try:
            if request_id is not None and not self._barcode_request_is_current(request_id, barcode):
                return
            if not self._has_usable_product_payload(data):
                self._on_api_failure(request_id=request_id, barcode=barcode)
                return
            self._fill_fields(data)
            self._barcode_lookup_status = "found"
            self._set_status("OK", self.COLOR_SUCCESS)
            self._show_snackbar("Produto encontrado", self.COLOR_SUCCESS)
        finally:
            if request_id is not None:
                Clock.schedule_once(self._start_pending_barcode_search, 0)

    def _on_api_failure(self, request_id=None, barcode=None):
        if request_id is not None and not self._barcode_request_is_current(request_id, barcode):
            return
        target_barcode = self._sanitize_barcode(barcode or self.barcode_input.text)
        if self.product is None:
            self._clear_fields(preserve_barcode=True, barcode_value=target_barcode)
        self._barcode_lookup_status = "not_found"
        self._set_status("Produto nao encontrado", self.COLOR_ERROR)
        self._show_snackbar("Produto nao encontrado", self.COLOR_ERROR)

    @staticmethod
    def _has_usable_product_payload(data):
        if not isinstance(data, dict):
            return False
        name = str(data.get("name") or "").strip().casefold()
        invalid_names = {
            "",
            "novo produto",
            "new product",
            "produto",
            "produto nao encontrado",
            "produto não encontrado",
            "nenhum produto encontrado",
            "nenhum produto encontrado.",
            "not found",
        }
        if name in invalid_names:
            return False
        return bool(name or str(data.get("brand") or "").strip())

    def _on_api_status(self, message):
        if self._queued_barcode_request:
            self._set_status("A trocar de codigo...", self.COLOR_WARNING)
            return
        self._set_status(message, self.COLOR_PRIMARY)

    # -- Fill fields --------------------------------------------------------
    def _fill_fields(self, data):
        if not isinstance(data, dict):
            return

        name = str(data.get("name") or "").strip()
        brand = str(data.get("brand") or "").strip()
        if name.lower() in {"novo produto", "new product", "produto"}:
            name = ""
        if name and not self.description.text.strip():
            full_name = name
            if brand and self._normalize_text(brand) not in self._normalize_text(name):
                full_name = f"{brand} - {name}"
            self.description.text = full_name

        category = data.get("category")
        if category and not self.category_field.text.strip():
            self._set_category(category)
        elif not self.category_field.text.strip():
            inferred = self._infer_category_from_name(self.description.text or name or brand)
            if inferred:
                self._set_category(inferred)
                self._register_generated_category(inferred)

        quantity = (
            data.get("quantity") or
            data.get("size") or
            self._extract_quantity_from_text(name) or
            (self._extract_quantity_from_text(self.description.text) if self.description.text.strip() else None)
        )
        if quantity and not self.package_quantity.text.strip():
            self.package_quantity.text = str(quantity)

        if data.get("price") and not self.sale_price.text.strip():
            self.sale_price.text = str(data["price"])
        if data.get("expiry_date") and not self.expiry_date.text.strip():
            self.expiry_date.text = data["expiry_date"]
        if data.get("sold_by_weight"):
            self._set_weight_state(True)

    # -- Category helpers ---------------------------------------------------
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

    def _set_vat_rule(self, code):
        self._selected_vat_rule_code = str(code or DEFAULT_VAT_RULE_CODE).strip().upper() or DEFAULT_VAT_RULE_CODE
        if hasattr(self, "vat_rule_field"):
            self.vat_rule_field.text = get_vat_choice_label(self._selected_vat_rule_code)
        if hasattr(self, "vat_mode_field"):
            self.vat_mode_field.text = describe_vat_choice(self._selected_vat_rule_code)
        if self._vat_menu:
            self._vat_menu.dismiss()

    def _open_vat_menu(self, _instance):
        if not self._vat_menu:
            return
        self._vat_menu.items = [
            {
                "text": f"{choice['label']} - {choice['hint']}",
                "on_release": (lambda code=choice["code"]: self._set_vat_rule(code)),
            }
            for choice in VAT_RULE_CHOICES
        ]
        self._vat_menu.open()

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
            "Laticinios": ["leite", "iogurte", "queijo", "manteiga", "nata"],
            "Higiene":    ["sabonete", "shampoo", "pasta", "dente", "desodorante", "fralda"],
            "Limpeza":    ["detergente", "lixivia", "cloro", "amaciante", "sabao", "desinfetante"],
            "Alimentos":  ["arroz", "farinha", "acucar", "oleo", "massa", "feijao", "sal", "cafe"],
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

    # -- Category form popup ------------------------------------------------
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
            hint_text="Ex.: Bebidas, Alimentos...", mode="rectangle",
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

    # -- Auto price calc ----------------------------------------------------
    @staticmethod
    def _parse_numeric_input(raw):
        text = (raw or "").strip().replace(",", ".")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def _set_field_value(self, field, value):
        text = "" if value is None else f"{value:.2f}"
        if field.text == text:
            return
        self._calculating = True
        try:
            field.text = text
        finally:
            self._calculating = False

    def _set_unit_purchase_price_value(self, value, auto=False):
        self._auto_unit_purchase_price = auto
        self._set_field_value(self.unit_purchase_price, value)

    def _set_total_purchase_price_value(self, value, auto=False):
        self._auto_total_purchase_price = auto
        self._set_field_value(self.total_purchase_price, value)

    def _sync_costs_from_total(self, total_changed=False):
        total = self._parse_numeric_input(self.total_purchase_price.text)
        stock = self._parse_numeric_input(self.existing_stock.text)
        if total_changed:
            self._auto_total_purchase_price = False
            self._cost_source_field = "total" if total is not None else None
        if total is None or stock is None or stock <= 0:
            return
        unit_cost = total / stock
        self._set_unit_purchase_price_value(unit_cost, auto=True)
        self._suggest_sale_price(unit_cost)

    def _sync_costs_from_unit(self, unit_changed=False):
        unit_cost = self._parse_numeric_input(self.unit_purchase_price.text)
        stock = self._parse_numeric_input(self.existing_stock.text)
        if unit_changed:
            self._auto_unit_purchase_price = False
            self._cost_source_field = "unit" if unit_cost is not None else None
        if unit_cost is None or stock is None:
            return
        self._set_total_purchase_price_value(unit_cost * stock, auto=True)
        self._suggest_sale_price(unit_cost)

    def _on_total_price_change(self, instance, value):
        if self._calculating or self.product:
            return
        self._sync_costs_from_total(total_changed=True)

    def _on_unit_price_change(self, instance, value):
        if self._calculating or self.product:
            return
        self._sync_costs_from_unit(unit_changed=True)

    def _on_stock_or_price_change(self, instance, value):
        if self._calculating or self.product:
            return
        total_value = self._parse_numeric_input(self.total_purchase_price.text)
        unit_value = self._parse_numeric_input(self.unit_purchase_price.text)
        if self._cost_source_field == "total" and total_value is not None:
            self._sync_costs_from_total()
            return
        if self._cost_source_field == "unit" and unit_value is not None:
            self._sync_costs_from_unit()
            return
        if unit_value is not None and not self._auto_unit_purchase_price:
            self._sync_costs_from_unit()
            return
        if total_value is not None and not self._auto_total_purchase_price:
            self._sync_costs_from_total()

    def _suggest_sale_price(self, unit_cost):
        if getattr(self, "_produce_mode", False):
            return
        current_sale_price = self._parse_price_value(self.sale_price.text)
        if current_sale_price is not None and not self._auto_sale_price:
            return
        try:
            margin = float(self._business_rules.get("default_profit_margin_percent", 30.0))
            self._set_sale_price_value(unit_cost * (1 + margin / 100), auto=True)
        except Exception:
            pass

    # -- Campos personalizados --------------------------------------------
    def _load_custom_field_definitions(self):
        from database.provider import get_db
        db = get_db()
        try:
            fields = db.list_product_custom_fields()
            return fields if isinstance(fields, list) else []
        except Exception:
            return []
        finally:
            db.close()

    def _build_custom_fields_section(self):
        section = MDCard(
            orientation="vertical", size_hint_y=None, padding=dp(12), spacing=dp(8),
            radius=[dp(10)], md_bg_color=self.COLOR_CARD_ALT, elevation=0,
        )
        title_row = BoxLayout(size_hint_y=None, height=dp(32), spacing=dp(8))
        title = Label(
            text="Informações adicionais", color=self.COLOR_TEXT, bold=True,
            font_size=sp(14), halign="left", valign="middle", size_hint_x=1,
        )
        title.bind(size=lambda widget, *_: setattr(widget, "text_size", (widget.width, None)))
        title_row.add_widget(title)
        manage = TooltipRaisedButton(
            text="Campos",
            theme_text_color="Custom",
            text_color=(1, 1, 1, 1),
            md_bg_color=self.COLOR_PRIMARY,
            radius=[dp(10)],
            elevation=1,
            size_hint=(None, None),
            size=(dp(118), dp(34)),
            tooltip_text="Gerir campos adicionais do formulario",
            on_release=lambda *_: self._open_custom_fields_manager(),
        )
        title_row.add_widget(manage)
        section.add_widget(title_row)
        self._custom_fields_container = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(7))
        section.add_widget(self._custom_fields_container)
        self._refresh_custom_fields_widgets()
        section.height = dp(64) + self._custom_fields_container.height
        return section

    def _refresh_custom_fields_widgets(self, values=None):
        if not hasattr(self, "_custom_fields_container"):
            return
        values = values or {}
        self._custom_fields_container.clear_widgets()
        self._custom_field_widgets = {}
        self._custom_field_rows = []
        fields = []
        for definition in self._custom_field_definitions:
            field_id = str(definition["id"])
            label = definition["label"] + (" *" if definition.get("required") else "")
            field = TooltipTextField(
                hint_text=label, tooltip_text=label, mode="rectangle", size_hint_y=None,
                height=self.FIELD_H, input_filter="float" if definition.get("type") == "NUMBER" else None,
            )
            self._style_field(field)
            field.text = str(values.get(field_id, values.get(definition["id"], "")) or "")
            fields.append(field)
            self._custom_field_widgets[field_id] = field

        # Repete exatamente a organizacao dos campos nativos: duas colunas
        # em ecras largos e uma coluna por vez quando a janela fica estreita.
        for index in range(0, len(fields), 2):
            pair = fields[index:index + 2]
            if len(pair) == 1:
                pair.append(BoxLayout())
            row = _row(*pair)
            self._custom_fields_container.add_widget(row)
            self._custom_field_rows.append(row)
        row_count = len(self._custom_field_rows)
        self._custom_fields_container.height = (
            sum(row.height for row in self._custom_field_rows)
            + max(0, row_count - 1) * dp(7)
        )
        # Durante a construcao inicial a secao ainda esta a ser devolvida por
        # _build_custom_fields_section, logo o atributo ainda nao existe.
        section = getattr(self, "_custom_fields_section", None)
        if section is not None:
            section.height = dp(64) + self._custom_fields_container.height
        self._update_responsive_layout()

    def _custom_field_values(self):
        return {field_id: widget.text.strip() for field_id, widget in self._custom_field_widgets.items()}

    @staticmethod
    def _make_switch(active=False):
        """Cria o interruptor com o estado inicial aplicado após a construção.

        Definir o estado depois do construtor mantém a construção previsível.
        """
        switch = MDSwitch(size_hint=(None, None), size=(dp(48), dp(36)))
        switch.active = bool(active)
        return switch

    def _open_custom_fields_manager(self):
        """Um unico cartao modal: lista existente + formulario de novo campo."""
        tokens_alt = self.COLOR_CARD_ALT

        card = MDCard(
            orientation="vertical",
            size_hint=(None, None),
            size=(dp(520), dp(460)),
            padding=[dp(18), dp(16), dp(18), dp(14)],
            spacing=dp(10),
            radius=[dp(16)],
            elevation=6,
            md_bg_color=self.COLOR_CARD,
            pos_hint={"center_x": 0.5, "center_y": 0.5},
        )

        # Cabecalho
        header = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
        title = Label(
            text="Campos personalizados",
            color=self.COLOR_TEXT,
            font_size=sp(17),
            bold=True,
            halign="left",
            valign="middle",
        )
        title.bind(size=title.setter("text_size"))
        header.add_widget(title)

        def _close(*_a):
            if getattr(self, "_custom_fields_modal", None) is not None:
                self._custom_fields_modal.dismiss()
                self._custom_fields_modal = None

        try:
            close_x = TooltipIconButton(
                icon="close",
                theme_text_color="Custom",
                text_color=self.COLOR_TEXT,
                size_hint=(None, None),
                size=(dp(34), dp(34)),
                on_release=_close,
            )
        except Exception:
            close_x = MDFlatButton(text="X", size_hint=(None, None), size=(dp(34), dp(34)), on_release=_close)
        header.add_widget(close_x)
        card.add_widget(header)

        # --- Campos existentes ---
        list_title = Label(
            text="Campos existentes",
            color=self.COLOR_GRAY,
            font_size=sp(12),
            bold=True,
            size_hint_y=None,
            height=dp(18),
            halign="left",
        )
        list_title.bind(size=list_title.setter("text_size"))
        card.add_widget(list_title)

        rows_box = BoxLayout(orientation="vertical", spacing=dp(6), size_hint_y=None)
        rows_box.bind(minimum_height=rows_box.setter("height"))
        scroll = ScrollView(
            size_hint=(1, None),
            height=dp(150),
            do_scroll_x=False,
            bar_width=dp(4),
        )
        scroll.add_widget(rows_box)
        card.add_widget(scroll)

        empty_label = Label(
            text="Nenhum campo personalizado ainda.",
            color=self.COLOR_GRAY,
            font_size=sp(12),
            size_hint_y=None,
            height=dp(40),
            halign="center",
            valign="middle",
        )
        empty_label.bind(size=empty_label.setter("text_size"))

        def _action_btn(text, icon, color, callback, width=dp(96)):
            try:
                return TooltipFlatButton(
                    text=text,
                    icon=icon,
                    theme_text_color="Custom",
                    text_color=color,
                    md_bg_color=(0, 0, 0, 0),
                    size_hint=(None, None),
                    size=(width, dp(32)),
                    radius=[dp(8)],
                    font_size=sp(11),
                    on_release=callback,
                )
            except TypeError:
                return MDFlatButton(
                    text=text,
                    theme_text_color="Custom",
                    text_color=color,
                    size_hint=(None, None),
                    size=(width, dp(32)),
                    on_release=callback,
                )

        def render_rows():
            rows_box.clear_widgets()
            definitions = self._load_all_custom_field_definitions()
            if not definitions:
                rows_box.add_widget(empty_label)
                return
            for definition in definitions:
                active = bool(definition.get("active"))
                kind = "numero" if definition.get("type") == "NUMBER" else "texto"
                status = "ativo" if active else "inativo"

                row = MDCard(
                    orientation="horizontal",
                    size_hint_y=None,
                    height=dp(42),
                    padding=[dp(10), dp(4), dp(6), dp(4)],
                    spacing=dp(6),
                    radius=[dp(10)],
                    elevation=0,
                    md_bg_color=tokens_alt,
                )
                try:
                    row.add_widget(MDIcon(
                        icon="numeric" if kind == "numero" else "form-textbox",
                        theme_text_color="Custom",
                        text_color=self.COLOR_SUCCESS if active else self.COLOR_GRAY,
                        size_hint=(None, None),
                        size=(dp(20), dp(20)),
                        pos_hint={"center_y": 0.5},
                    ))
                except Exception:
                    pass

                info = BoxLayout(orientation="vertical", spacing=0, size_hint_x=1)
                name_lbl = Label(
                    text=str(definition.get("label") or ""),
                    color=self.COLOR_TEXT,
                    font_size=sp(13),
                    bold=True,
                    halign="left",
                    size_hint_y=None,
                    height=dp(16),
                    shorten=True,
                    shorten_from="right",
                )
                name_lbl.bind(size=name_lbl.setter("text_size"))
                meta = Label(
                    text=f"{kind} · {status}"
                    + (" · obrigatorio" if definition.get("required") else ""),
                    color=self.COLOR_GRAY,
                    font_size=sp(10),
                    halign="left",
                    size_hint_y=None,
                    height=dp(14),
                )
                meta.bind(size=meta.setter("text_size"))
                info.add_widget(name_lbl)
                info.add_widget(meta)
                row.add_widget(info)

                row.add_widget(_action_btn(
                    "Editar", "pencil-outline", self.COLOR_PRIMARY,
                    lambda _b, item=definition: self._edit_custom_field(item, render_rows),
                    width=dp(88),
                ))
                if active:
                    row.add_widget(_action_btn(
                        "Desativar", "eye-off-outline",
                        self.COLOR_ERROR if hasattr(self, "COLOR_ERROR") else (0.85, 0.3, 0.3, 1),
                        lambda _b, item=definition: self._toggle_custom_field(item, render_rows),
                        width=dp(104),
                    ))
                else:
                    row.add_widget(_action_btn(
                        "Ativar", "eye-outline", self.COLOR_SUCCESS,
                        lambda _b, item=definition: self._toggle_custom_field(item, render_rows),
                        width=dp(92),
                    ))
                rows_box.add_widget(row)

        # --- Novo campo (dentro do mesmo card) ---
        new_title = Label(
            text="Novo campo",
            color=self.COLOR_GRAY,
            font_size=sp(12),
            bold=True,
            size_hint_y=None,
            height=dp(18),
            halign="left",
        )
        new_title.bind(size=new_title.setter("text_size"))
        card.add_widget(new_title)

        add_label = TooltipTextField(
            hint_text="Nome do campo (ex.: Marca, Fornecedor)",
            mode="rectangle",
            size_hint_y=None,
            height=self.FIELD_H,
        )
        card.add_widget(add_label)

        kind = self._make_switch(False)
        required = self._make_switch(False)

        def _sw(label_text, icon_name, sw):
            box = BoxLayout(size_hint_x=1, spacing=dp(6))
            try:
                box.add_widget(MDIcon(
                    icon=icon_name,
                    theme_text_color="Custom",
                    text_color=self.COLOR_GRAY,
                    size_hint=(None, None),
                    size=(dp(18), dp(18)),
                    pos_hint={"center_y": 0.5},
                ))
            except Exception:
                pass
            lbl = Label(
                text=label_text,
                color=self.COLOR_TEXT,
                font_size=sp(12),
                halign="left",
                valign="middle",
            )
            lbl.bind(size=lbl.setter("text_size"))
            box.add_widget(lbl)
            box.add_widget(sw)
            return box

        switches = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(36),
            spacing=dp(12),
        )
        switches.add_widget(_sw("Campo numerico", "numeric", kind))
        switches.add_widget(_sw("Obrigatorio", "asterisk", required))
        card.add_widget(switches)

        try:
            add_button = TooltipRaisedButton(
                text="Adicionar campo",
                icon="plus-circle-outline",
                md_bg_color=self.COLOR_SUCCESS,
                theme_text_color="Custom",
                text_color=(1, 1, 1, 1),
                size_hint=(1, None),
                height=dp(42),
                radius=[dp(12)],
                elevation=1,
            )
        except TypeError:
            add_button = MDRaisedButton(
                text="+  Adicionar campo",
                md_bg_color=self.COLOR_SUCCESS,
                theme_text_color="Custom",
                text_color=(1, 1, 1, 1),
                size_hint=(1, None),
                height=dp(42),
                radius=[dp(12)],
            )

        def add_field(*_args):
            name = (add_label.text or "").strip()
            if not name:
                self._show_snackbar(
                    "Indique o nome do campo.",
                    self.COLOR_WARNING if hasattr(self, "COLOR_WARNING") else self.COLOR_GRAY,
                )
                return
            try:
                from database.provider import get_db
                db = get_db()
                try:
                    db.create_product_custom_field(
                        name,
                        "NUMBER" if kind.active else "TEXT",
                        required.active,
                    )
                finally:
                    db.close()
                add_label.text = ""
                kind.active = False
                required.active = False
                self._custom_field_definitions = self._load_custom_field_definitions()
                self._refresh_custom_fields_widgets(self._custom_field_values())
                render_rows()
                self._show_snackbar("Campo adicionado.", self.COLOR_SUCCESS)
            except Exception as exc:
                self._show_snackbar(
                    f"Nao foi possivel criar o campo: {exc}",
                    self.COLOR_ERROR,
                )

        add_button.bind(on_release=add_field)
        card.add_widget(add_button)

        # ModalView garante que o card e o unico contentor visivel
        modal = ModalView(
            size_hint=(1, 1),
            background_color=(0, 0, 0, 0.55),
            auto_dismiss=True,
        )
        modal.add_widget(card)
        modal.bind(on_dismiss=lambda *_: setattr(self, "_custom_fields_modal", None))
        self._custom_fields_modal = modal
        render_rows()
        modal.open()

    def _load_all_custom_field_definitions(self):
        from database.provider import get_db
        db = get_db()
        try:
            fields = db.list_product_custom_fields(active_only=False)
            return fields if isinstance(fields, list) else []
        finally:
            db.close()

    def _toggle_custom_field(self, definition, on_done):
        try:
            from database.provider import get_db
            db = get_db()
            try:
                db.update_product_custom_field(
                    definition["id"], definition["label"], definition["type"],
                    definition.get("required", False), not definition.get("active", False),
                )
            finally:
                db.close()
            self._custom_field_definitions = self._load_custom_field_definitions()
            self._refresh_custom_fields_widgets(self._custom_field_values())
            on_done()
        except Exception as exc:
            self._show_snackbar(f"Nao foi possivel atualizar o campo: {exc}", self.COLOR_ERROR)

    def _edit_custom_field(self, definition, on_done):
        """Dialog compacto para editar um campo personalizado."""
        card = MDCard(
            orientation="vertical",
            size_hint=(None, None),
            size=(dp(360), dp(220)),
            padding=[dp(16), dp(14), dp(16), dp(12)],
            spacing=dp(10),
            radius=[dp(14)],
            elevation=6,
            md_bg_color=self.COLOR_CARD,
            pos_hint={"center_x": 0.5, "center_y": 0.5},
        )

        header = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(6))
        header.add_widget(Label(
            text="Editar campo",
            color=self.COLOR_TEXT,
            font_size=sp(15),
            bold=True,
            halign="left",
            valign="middle",
        ))
        card.add_widget(header)

        label = TooltipTextField(
            text=definition.get("label") or "",
            hint_text="Nome do campo",
            mode="rectangle",
            size_hint_y=None,
            height=self.FIELD_H,
        )
        card.add_widget(label)

        numeric = self._make_switch(definition.get("type") == "NUMBER")
        required = self._make_switch(bool(definition.get("required")))

        def _sw(text, icon_name, sw):
            row = BoxLayout(size_hint_x=1, spacing=dp(6))
            try:
                row.add_widget(MDIcon(
                    icon=icon_name,
                    theme_text_color="Custom",
                    text_color=self.COLOR_GRAY,
                    size_hint=(None, None),
                    size=(dp(18), dp(18)),
                    pos_hint={"center_y": 0.5},
                ))
            except Exception:
                pass
            lbl = Label(
                text=text,
                color=self.COLOR_TEXT,
                font_size=sp(12),
                halign="left",
                valign="middle",
            )
            lbl.bind(size=lbl.setter("text_size"))
            row.add_widget(lbl)
            row.add_widget(sw)
            return row

        switches = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(34),
            spacing=dp(10),
        )
        switches.add_widget(_sw("Numerico", "numeric", numeric))
        switches.add_widget(_sw("Obrigatorio", "asterisk", required))
        card.add_widget(switches)

        actions = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(40),
            spacing=dp(10),
        )
        actions.add_widget(BoxLayout(size_hint_x=1))  # spacer

        try:
            cancel_btn = TooltipFlatButton(
                text="Cancelar",
                icon="close",
                theme_text_color="Custom",
                text_color=self.COLOR_TEXT,
                size_hint=(None, None),
                size=(dp(110), dp(36)),
            )
        except TypeError:
            cancel_btn = MDFlatButton(
                text="Cancelar",
                size_hint=(None, None),
                size=(dp(110), dp(36)),
            )

        try:
            save_btn = TooltipRaisedButton(
                text="Guardar",
                icon="content-save-outline",
                md_bg_color=self.COLOR_SUCCESS,
                theme_text_color="Custom",
                text_color=(1, 1, 1, 1),
                size_hint=(None, None),
                size=(dp(120), dp(36)),
                radius=[dp(10)],
                elevation=1,
            )
        except TypeError:
            save_btn = MDRaisedButton(
                text="Guardar",
                md_bg_color=self.COLOR_SUCCESS,
                theme_text_color="Custom",
                text_color=(1, 1, 1, 1),
                size_hint=(None, None),
                size=(dp(120), dp(36)),
                radius=[dp(10)],
            )

        actions.add_widget(cancel_btn)
        actions.add_widget(save_btn)
        card.add_widget(actions)

        modal = ModalView(
            size_hint=(1, 1),
            background_color=(0, 0, 0, 0.45),
            auto_dismiss=False,
        )
        modal.add_widget(card)

        def _dismiss(*_a):
            modal.dismiss()

        def save(*_args):
            name = (label.text or "").strip()
            if not name:
                self._show_snackbar("Indique o nome do campo.", self.COLOR_GRAY)
                return
            try:
                from database.provider import get_db
                db = get_db()
                try:
                    db.update_product_custom_field(
                        definition["id"],
                        name,
                        "NUMBER" if numeric.active else "TEXT",
                        required.active,
                        definition.get("active", True),
                    )
                finally:
                    db.close()
                self._custom_field_definitions = self._load_custom_field_definitions()
                self._refresh_custom_fields_widgets(self._custom_field_values())
                modal.dismiss()
                on_done()
            except Exception as exc:
                self._show_snackbar(
                    f"Nao foi possivel editar o campo: {exc}",
                    self.COLOR_ERROR,
                )

        cancel_btn.bind(on_release=_dismiss)
        save_btn.bind(on_release=save)
        modal.open()

    def _load_business_rules(self):
        from database.provider import get_db
        db = get_db()
        try:
            rules = db.get_product_business_rules()
            return rules if isinstance(rules, dict) else {}
        except Exception:
            # O formulario continua utilizavel se uma versao antiga do
            # servidor ainda nao tiver este recurso.
            return {}
        finally:
            db.close()

    def _open_business_rules_dialog(self):
        if self._business_rules_dialog is not None:
            self._business_rules_dialog.open()
            return
        rules = self._business_rules or {}
        content = BoxLayout(orientation="vertical", spacing=dp(10), size_hint_y=None, height=dp(300))
        intro = MDCard(
            orientation="vertical", size_hint_y=None, height=dp(54), padding=[dp(12), dp(7)],
            radius=[dp(10)], elevation=0, md_bg_color=(*self.COLOR_PRIMARY[:3], .12),
            line_color=(*self.COLOR_PRIMARY[:3], .32), line_width=1,
        )
        intro_title = Label(text="Proteção automática de preço", color=self.COLOR_TEXT, bold=True,
                            font_size=sp(13), halign="left", valign="middle", size_hint_y=None, height=dp(18))
        intro_text = Label(
            text="Estas regras são aplicadas no formulário e confirmadas ao guardar o produto.",
            color=self.COLOR_GRAY, font_size=sp(11), halign="left", valign="middle",
        )
        for label in (intro_title, intro_text):
            label.bind(size=lambda widget, *_: setattr(widget, "text_size", (widget.width, None)))
            intro.add_widget(label)
        content.add_widget(intro)

        default_margin = TooltipTextField(
            hint_text="Ex.: 30", input_filter="float", mode="rectangle",
            text=str(rules.get("default_profit_margin_percent", 30)), size_hint_y=None, height=self.FIELD_H,
        )
        minimum_margin = TooltipTextField(
            hint_text="Ex.: 0", input_filter="float", mode="rectangle",
            text=str(rules.get("minimum_profit_margin_percent", 0)), size_hint_y=None, height=self.FIELD_H,
        )
        self._style_field(default_margin)
        self._style_field(minimum_margin)
        margins = BoxLayout(size_hint_y=None, height=dp(76), spacing=dp(10))
        for title, field, hint in (
            ("Margem sugerida", default_margin, "Percentagem usada no cálculo automático."),
            ("Margem mínima", minimum_margin, "Limite mínimo permitido para venda."),
        ):
            block = BoxLayout(orientation="vertical", spacing=dp(3))
            title_label = Label(text=title, color=self.COLOR_TEXT, bold=True, font_size=sp(12),
                                halign="left", valign="middle", size_hint_y=None, height=dp(18))
            title_label.bind(size=lambda widget, *_: setattr(widget, "text_size", (widget.width, None)))
            field.hint_text = hint
            block.add_widget(title_label)
            block.add_widget(field)
            margins.add_widget(block)
        content.add_widget(margins)

        enforce = self._make_switch(bool(rules.get("enforce_minimum_margin", False)))
        negative = self._make_switch(bool(rules.get("allow_negative_margin", False)))
        for title, description, switch in (
            ("Bloquear abaixo da margem mínima", "Impede preços abaixo do limite definido.", enforce),
            ("Permitir prejuízo", "Autoriza vender por valor inferior ao custo.", negative),
        ):
            row = MDCard(orientation="horizontal", size_hint_y=None, height=dp(52), spacing=dp(10),
                         padding=[dp(12), dp(6)], radius=[dp(10)], elevation=0,
                         md_bg_color=self.COLOR_CARD_ALT)
            copy = BoxLayout(orientation="vertical", spacing=0)
            title_label = Label(text=title, color=self.COLOR_TEXT, bold=True, font_size=sp(12),
                                halign="left", valign="middle")
            description_label = Label(text=description, color=self.COLOR_GRAY, font_size=sp(10),
                                      halign="left", valign="middle")
            for label in (title_label, description_label):
                label.bind(size=lambda widget, *_: setattr(widget, "text_size", (widget.width, None)))
                copy.add_widget(label)
            switch.size_hint_x = None
            switch.width = dp(48)
            row.add_widget(copy)
            row.add_widget(switch)
            content.add_widget(row)

        dialog = MDDialog(
            title="Regras comerciais do produto", type="custom", content_cls=content,
            auto_dismiss=False, size_hint=(.78, None), height=dp(470),
            buttons=[
                MDFlatButton(text="CANCELAR", text_color=self.COLOR_PRIMARY, radius=[dp(10)]),
                MDRaisedButton(text="GUARDAR REGRAS", md_bg_color=self.COLOR_SUCCESS, radius=[dp(10)]),
            ],
        )

        def close_dialog(*_args):
            dialog.dismiss()

        def save_rules(*_args):
            try:
                payload = {
                    "default_profit_margin_percent": float(default_margin.text.replace(",", ".")),
                    "minimum_profit_margin_percent": float(minimum_margin.text.replace(",", ".")),
                    "enforce_minimum_margin": bool(enforce.active),
                    "allow_negative_margin": bool(negative.active),
                }
                from database.provider import get_db
                db = get_db()
                try:
                    self._business_rules = db.update_product_business_rules(payload)
                finally:
                    db.close()
                dialog.dismiss()
                self._show_snackbar("Regras comerciais guardadas.", self.COLOR_SUCCESS)
            except (TypeError, ValueError) as exc:
                self._show_snackbar(f"Regra invalida: {exc}", self.COLOR_ERROR)
            except Exception as exc:
                self._show_snackbar(f"Nao foi possivel guardar as regras: {exc}", self.COLOR_ERROR)

        dialog.buttons[0].bind(on_release=close_dialog)
        dialog.buttons[1].bind(on_release=save_rules)
        dialog.bind(on_dismiss=lambda *_: setattr(self, "_business_rules_dialog", None))
        self._business_rules_dialog = dialog
        dialog.open()

    # -- Price actions ------------------------------------------------------
    @staticmethod
    def _parse_price_value(raw):
        text = (raw or "").strip().replace(",", ".")
        try: return float(text) if text else None
        except ValueError: return None

    def _set_sale_price_value(self, value, auto=False):
        text = f"{value:.2f}"
        self._applying_price_action = True
        try:
            self._auto_sale_price = auto
            if self.sale_price.text != text:
                self.sale_price.text = text
        finally:
            self._applying_price_action = False

    def _on_sale_price_text_change(self, instance, value):
        if not self._applying_price_action:
            self._auto_sale_price = False
            if self._discount_base_price is not None:
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
        self._show_snackbar(f"-{pct}%: {self._discount_base_price:.2f} ? {discounted:.2f}", self.COLOR_PRIMARY)

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

    # -- Date picker (simples e rápido) -------------------------------------
    def _show_date_picker(self, instance):
        """Popup de validade: cartao unico, campos DD/MM/AAAA, pre-visualizacao e atalhos."""
        from datetime import timedelta

        current = datetime.now()
        _partial_day = False
        if self.expiry_date.text.strip():
            try:
                raw = self.expiry_date.text.strip()
                parts = re.findall(r"\d+", raw)
                if len(parts) >= 3:
                    d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                    if y < 100:
                        y += 2000
                    if d == 0 and 1 <= m <= 12:
                        _partial_day = True
                        d = 1  # só para preencher o campo; partial mantém 00
                    current = datetime(y, m, d)
                else:
                    current = datetime.strptime(raw, "%d/%m/%Y")
            except ValueError:
                pass

        card_w = min(dp(420), Window.width * 0.92)
        card_h = dp(384)

        card = MDCard(
            orientation="vertical",
            size_hint=(1, 1),
            padding=[dp(20), dp(16), dp(20), dp(16)],
            spacing=dp(10),
            radius=[dp(20)],
            elevation=6,
            md_bg_color=self.COLOR_CARD,
        )

        modal = ModalView(
            size_hint=(None, None),
            size=(card_w, card_h),
            background="",
            background_color=(0, 0, 0, 0),
            overlay_color=(0, 0, 0, 0.55),
            auto_dismiss=True,
        )

        def _close(*_a):
            modal.dismiss()

        def _digits(text):
            return "".join(ch for ch in (text or "") if ch.isdigit())

        # ---------------- Cabecalho ----------------
        header = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(10))
        try:
            header.add_widget(MDIcon(
                icon="calendar-month-outline",
                theme_text_color="Custom",
                text_color=self.COLOR_PRIMARY,
                size_hint=(None, None),
                size=(dp(26), dp(26)),
                pos_hint={"center_y": 0.5},
            ))
        except Exception:
            pass
        title = Label(
            text="Validade do produto",
            color=self.COLOR_TEXT,
            font_size=sp(17),
            bold=True,
            halign="left",
            valign="middle",
        )
        title.bind(size=title.setter("text_size"))
        header.add_widget(title)
        header.add_widget(TooltipIconButton(
            icon="close",
            theme_text_color="Custom",
            text_color=self.COLOR_GRAY,
            md_bg_color=self.COLOR_CARD_ALT,
            size_hint=(None, None),
            size=(dp(34), dp(34)),
            radius=[dp(17)],
            hint_text="Fechar",
            pos_hint={"center_y": 0.5},
            on_release=_close,
        ))
        card.add_widget(header)

        # ---------------- Pre-visualizacao ----------------
        preview_box = MDCard(
            size_hint_y=None,
            height=dp(34),
            radius=[dp(12)],
            elevation=0,
            md_bg_color=(*self.COLOR_PRIMARY[:3], 0.12),
        )
        preview = Label(
            text="",
            color=self.COLOR_PRIMARY,
            font_size=sp(13),
            bold=True,
            halign="center",
            valign="middle",
        )
        preview.bind(size=preview.setter("text_size"))
        preview_box.add_widget(preview)
        card.add_widget(preview_box)

        # ---------------- Campos DIA / MES / ANO ----------------
        def _make_col(label_text, value, placeholder, flex):
            col = BoxLayout(orientation="vertical", spacing=dp(3), size_hint_x=flex)
            lbl = Label(
                text=label_text,
                color=self.COLOR_GRAY,
                font_size=sp(11),
                bold=True,
                size_hint_y=None,
                height=dp(15),
                halign="center",
                valign="middle",
            )
            lbl.bind(size=lbl.setter("text_size"))
            field = MDTextField(
                text=value,
                hint_text=placeholder,
                input_filter="int",
                mode="rectangle",
                size_hint_y=None,
                height=dp(48),
                font_size=sp(18),
                multiline=False,
                halign="center",
            )
            self._style_field(field)
            col.add_widget(lbl)
            col.add_widget(field)
            return col, field

        def _slash():
            wrap = BoxLayout(size_hint_x=None, width=dp(14), padding=[0, dp(18), 0, 0])
            s = Label(
                text="/",
                color=(*self.COLOR_GRAY[:3], 0.55),
                font_size=sp(18),
                bold=True,
                halign="center",
                valign="middle",
            )
            s.bind(size=s.setter("text_size"))
            wrap.add_widget(s)
            return wrap

        fields_row = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(68), spacing=dp(6),
        )
        day_col, day_f = _make_col(
            "DIA",
            ("00" if _partial_day else f"{current.day:02d}"), "DD", 0.28)
        month_col, month_f = _make_col("MÊS", f"{current.month:02d}", "MM", 0.28)
        year_col, year_f = _make_col("ANO", str(current.year), "AAAA", 0.44)
        for widget in (day_col, _slash(), month_col, _slash(), year_col):
            fields_row.add_widget(widget)
        card.add_widget(fields_row)

        # ---------------- Logica dos campos ----------------
        def _read_date():
            """
            Devolve (datetime, partial).
            partial=True quando o dia é 0/00 (só mês e ano na embalagem).
            Nesse caso usa o último dia do mês para o cálculo de validade.
            """
            try:
                d = int(_digits(day_f.text) or "0")
                m = int(_digits(month_f.text) or "0")
                y = int(_digits(year_f.text) or "0")
                if y < 100:
                    y += 2000
                if not (1 <= m <= 12) or y < 1990 or y > 2100:
                    return None, False
                partial = d == 0
                if partial:
                    d = calendar.monthrange(y, m)[1]
                elif not (1 <= d <= calendar.monthrange(y, m)[1]):
                    return None, False
                return datetime(y, m, d), partial
            except Exception:
                return None, False

        def _refresh_preview(*_a):
            value, partial = _read_date()
            if value is None:
                preview.text = "Data incompleta ou inválida"
                preview.color = self.COLOR_GRAY
                status.text = ""
                return
            delta = (value.date() - datetime.now().date()).days
            plural = "dia" if abs(delta) == 1 else "dias"
            if delta > 0:
                rel, color = f"daqui a {delta} {plural}", self.COLOR_SUCCESS
            elif delta == 0:
                rel, color = "expira hoje", self.COLOR_WARNING
            else:
                rel, color = f"expirado há {-delta} {plural}", self.COLOR_ERROR
            if partial:
                preview.text = (
                    f"00/{value.month:02d}/{value.year}  ·  só mês/ano  ·  "
                    f"válido até {value.strftime('%d/%m/%Y')}  ·  {rel}"
                )
                status.text = "Dia 00 aceite: validade só com mês e ano."
                status.color = self.COLOR_SUCCESS
            else:
                preview.text = f"{value.strftime('%d/%m/%Y')}  ·  {rel}"
                status.text = ""
            preview.color = color

        def _on_day_text(_inst, value):
            digits = _digits(value)
            if len(digits) > 2:
                day_f.text = digits[:2]
                return
            if len(digits) == 2:
                Clock.schedule_once(lambda *_: setattr(month_f, "focus", True), 0)
            _refresh_preview()

        def _on_month_text(_inst, value):
            digits = _digits(value)
            if len(digits) > 2:
                month_f.text = digits[:2]
                return
            if len(digits) == 2:
                Clock.schedule_once(lambda *_: setattr(year_f, "focus", True), 0)
            _refresh_preview()

        def _on_year_text(_inst, value):
            digits = _digits(value)
            if len(digits) > 4:
                year_f.text = digits[:4]
                return
            _refresh_preview()

        day_f.bind(text=_on_day_text)
        month_f.bind(text=_on_month_text)
        year_f.bind(text=_on_year_text)
        day_f.bind(on_text_validate=lambda *_: setattr(month_f, "focus", True))
        month_f.bind(on_text_validate=lambda *_: setattr(year_f, "focus", True))

        def _select_all(field, focused):
            if focused:
                Clock.schedule_once(lambda _dt: field.select_all(), 0.02)

        for f in (day_f, month_f, year_f):
            f.bind(focus=_select_all)

        def _set_date(dt_value):
            day_f.text = f"{dt_value.day:02d}"
            month_f.text = f"{dt_value.month:02d}"
            year_f.text = str(dt_value.year)

        def _apply_offset(days=0, months=0, years=0):
            base = datetime.now()
            if years or months:
                y = base.year + years
                m = base.month + months
                while m > 12:
                    m -= 12
                    y += 1
                while m < 1:
                    m += 12
                    y -= 1
                last = 31 if m == 12 else (datetime(y, m + 1, 1) - timedelta(days=1)).day
                _set_date(datetime(y, m, min(base.day, last)) + timedelta(days=days))
            else:
                _set_date(base + timedelta(days=days))

        # ---------------- Atalhos rapidos ----------------
        quick_label = Label(
            text="ATALHOS RÁPIDOS",
            color=self.COLOR_GRAY,
            font_size=sp(11),
            bold=True,
            size_hint_y=None,
            height=dp(16),
            halign="left",
            valign="middle",
        )
        quick_label.bind(size=quick_label.setter("text_size"))
        card.add_widget(quick_label)

        def _chip(label, action):
            chip = MDCard(
                orientation="horizontal",
                size_hint=(1, None),
                height=dp(34),
                radius=[dp(17)],
                elevation=0,
                md_bg_color=(*self.COLOR_PRIMARY[:3], 0.12),
                ripple_behavior=True,
            )
            lbl = Label(
                text=label,
                color=self.COLOR_PRIMARY,
                font_size=sp(12),
                bold=True,
                halign="center",
                valign="middle",
            )
            lbl.bind(size=lbl.setter("text_size"))
            chip.add_widget(lbl)

            def _down(inst, touch):
                if inst.collide_point(*touch.pos) and not touch.is_mouse_scrolling:
                    touch.grab(inst)
                    return True
                return False

            def _up(inst, touch, fn=action):
                if touch.grab_current is inst:
                    touch.ungrab(inst)
                    if inst.collide_point(*touch.pos):
                        fn()
                    return True
                return False

            chip.bind(on_touch_down=_down, on_touch_up=_up)
            return chip

        for row_items in (
            (("Hoje", lambda: _apply_offset(0)),
             ("+30 dias", lambda: _apply_offset(30)),
             ("+90 dias", lambda: _apply_offset(90))),
            (("+6 meses", lambda: _apply_offset(months=6)),
             ("+1 ano", lambda: _apply_offset(years=1)),
             ("+2 anos", lambda: _apply_offset(years=2))),
        ):
            chips_row = BoxLayout(
                orientation="horizontal", size_hint_y=None, height=dp(34), spacing=dp(8),
            )
            for label, action in row_items:
                chips_row.add_widget(_chip(label, action))
            card.add_widget(chips_row)

        # ---------------- Estado + acoes ----------------
        status = Label(
            text="",
            color=self.COLOR_ERROR,
            font_size=sp(11),
            size_hint_y=None,
            height=dp(14),
            halign="center",
            valign="middle",
        )
        status.bind(size=status.setter("text_size"))
        card.add_widget(status)

        actions = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(44), spacing=dp(10),
        )
        cancel_btn = MDFlatButton(
            text="Cancelar",
            theme_text_color="Custom",
            text_color=self.COLOR_TEXT,
            md_bg_color=self.COLOR_CARD_ALT,
            font_size=sp(13),
            size_hint=(0.38, 1),
            radius=[dp(12)],
        )
        apply_btn = MDRaisedButton(
            text="Aplicar data",
            md_bg_color=self.COLOR_PRIMARY,
            theme_text_color="Custom",
            text_color=(1, 1, 1, 1),
            font_size=sp(13),
            size_hint=(0.62, 1),
            radius=[dp(12)],
        )
        actions.add_widget(cancel_btn)
        actions.add_widget(apply_btn)
        card.add_widget(actions)

        def _confirm(*_a):
            value, partial = _read_date()
            if value is None:
                status.text = "Data inválida. Verifique mês e ano (dia 00 permitido)."
                status.color = self.COLOR_ERROR
                return
            if partial:
                # Guarda 00/MM/AAAA — o save converte para o último dia do mês
                self.expiry_date.text = f"00/{value.month:02d}/{value.year}"
            else:
                self.expiry_date.text = value.strftime("%d/%m/%Y")
            _close()

        cancel_btn.bind(on_release=_close)
        apply_btn.bind(on_release=_confirm)
        year_f.bind(on_text_validate=_confirm)

        modal.add_widget(card)
        _refresh_preview()
        modal.open()
        Clock.schedule_once(lambda *_: setattr(day_f, "focus", True), 0.10)

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
        self.weight_state_btn.text = "● ATIVO" if active else "○ INATIVO"
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
        if hasattr(self, "existing_stock"):
            self.existing_stock.input_filter = "float" if active else "int"
        if hasattr(self, "sold_stock"):
            self.sold_stock.input_filter = "float" if active else "int"
        if hasattr(self, "units_per_package_input"):
            self.units_per_package_input.disabled = bool(active)
        if active:
            if hasattr(self, "units_per_package_input"):
                self.units_per_package_input.text = ""
            self._set_pack_sale_state(False)

    def _on_pack_sale_toggle(self, instance, active):
        if not hasattr(self, "pack_sale_state_btn"):
            return
        self.pack_sale_state_btn.text = "● ATIVO" if active else "○ INATIVO"
        self.pack_sale_state_btn.md_bg_color = (
            (*self.COLOR_SUCCESS[:3], 0.95) if active else (0.45, 0.45, 0.48, 1)
        )
        if hasattr(self, "pack_sale_layout"):
            self.pack_sale_layout.md_bg_color = (
                (self.COLOR_PRIMARY[0], self.COLOR_PRIMARY[1], self.COLOR_PRIMARY[2], 0.18)
                if active else self.COLOR_CARD_ALT
            )

    # -- Scanner ------------------------------------------------------------

    def _preload_vision_modules(self, _dt):
        """Carrega cv2/pyzbar em background logo apos o popup abrir.
        Quando o utilizador clicar no botao de scan os modulos ja estao
        em cache e o arranque e imediato."""
        try:
            self._load_vision_modules()
        except Exception:
            pass  # o erro sera reportado quando o utilizador clicar em scan

    def _start_scanner(self):
        if self.scanning:
            return True
        if not self._ensure_scanner_dependencies():
            return False
        self.scanning = True
        self.scan_btn.icon        = "barcode-off"
        self.scan_btn.md_bg_color = self.COLOR_ERROR
        if getattr(self, "_camera_placeholder", None) is not None:
            self._camera_placeholder.opacity = 0
            self._camera_placeholder.disabled = True
        self._set_status("Scanner Ativo", self.COLOR_PRIMARY)
        Clock.unschedule(self._update_camera)
        Clock.schedule_interval(self._update_camera, 1.0 / 15.0)
        return True

    def _on_scanner_launch_touch(self, instance, touch):
        if instance.disabled or instance.opacity < 0.5:
            return False
        if not instance.collide_point(*touch.pos):
            return False
        if touch.is_mouse_scrolling:
            return False
        self.open_scanner_modal()
        return True

    def open_scanner_modal(self, *_args):
        """Abre o scanner em modal quando o painel esta colapsado."""
        if getattr(self, "_scanner_modal", None) is not None:
            try:
                self._scanner_modal.dismiss()
            except Exception:
                pass
            self._scanner_modal = None

        content = BoxLayout(
            orientation="vertical",
            spacing=dp(10),
            padding=[dp(14), dp(12), dp(14), dp(12)],
            md_bg_color=self.COLOR_CARD,
        )
        header = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        header.add_widget(Label(
            text="Scanner de codigo de barras",
            font_size=sp(16), bold=True, color=self.COLOR_TEXT,
            halign="left", valign="middle",
        ))
        close_btn = TooltipIconButton(
            icon="close", theme_text_color="Custom", text_color=self.COLOR_TEXT,
            size_hint=(None, None), size=(dp(36), dp(36)),
            on_release=lambda *_: self._close_scanner_modal(),
        )
        header.add_widget(close_btn)
        content.add_widget(header)

        # Reutilizar o painel expandido se existir
        expanded = getattr(self, "_scanner_expanded", None)
        host = BoxLayout(orientation="vertical", size_hint=(1, 1))
        if expanded is not None:
            parent = expanded.parent
            if parent is not None:
                parent.remove_widget(expanded)
            expanded.opacity = 1
            expanded.disabled = False
            expanded.size_hint = (1, 1)
            host.add_widget(expanded)
        content.add_widget(host)

        modal = ModalView(
            size_hint=(0.92, 0.88),
            auto_dismiss=True,
            background_color=[0, 0, 0, 0.55],
        )
        modal.add_widget(content)

        def _on_dismiss(*_a):
            if expanded is not None:
                if expanded.parent is not None:
                    expanded.parent.remove_widget(expanded)
                panel = getattr(self, "_scanner_panel", None) or self._camera_section
                if panel is not None and not getattr(self, "_scanner_collapsed", False):
                    panel.add_widget(expanded)
                elif panel is not None:
                    # Mantem no painel mas oculto ate expandir de novo
                    expanded.opacity = 0
                    expanded.disabled = True
                    if expanded.parent is None:
                        panel.add_widget(expanded)
            self._scanner_modal = None
            # Se estava a digitalizar, continua; senao deixa parado
            self._update_responsive_layout()

        modal.bind(on_dismiss=_on_dismiss)
        self._scanner_modal = modal
        modal.open()

    def _close_scanner_modal(self):
        if getattr(self, "_scanner_modal", None) is not None:
            try:
                self._scanner_modal.dismiss()
            except Exception:
                pass
            self._scanner_modal = None

    def _toggle_scanner(self, instance):
        if not self.scanning:
            self._start_scanner()
        else:
            self._stop_scanner()

    def _stop_scanner(self):
        self.scanning = False
        self.scan_btn.icon        = "barcode-scan"
        self.scan_btn.md_bg_color = self.COLOR_PRIMARY
        self._set_status("Scanner parado", self.COLOR_GRAY)
        Clock.unschedule(self._update_camera)
        if self.camera_capture:
            self.camera_capture.release()
            self.camera_capture = None
        self.camera_image.texture = None
        if getattr(self, "_camera_placeholder", None) is not None:
            self._camera_placeholder.opacity = 1
            self._camera_placeholder.disabled = False

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
                self._queue_or_start_barcode_search(val)
                if len(code.polygon) == 4:
                    pts = np.array([(p.x, p.y) for p in code.polygon], dtype=np.int32)
                    cv2.polylines(frame, [pts], True, (0, 255, 0), 3)
                x, y, w, h = code.rect
                cv2.putText(frame, val, (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)
            except Exception as e:
                print(f"[Scanner] {e}")
        if not codes and (now - self.last_barcode_time) > 2.5 and not self._api_manager_is_loading():
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
        self._start_scanner()

    def _on_barcode_manual_entry(self, instance):
        self._queue_or_start_barcode_search(instance.text)

    # -- Category lookup thread ---------------------------------------------
    def _search_category_if_missing(self, barcode):
        from threading import Thread
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
        for _, api in self._get_category_sources():
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

    # -- Save ---------------------------------------------------------------
    def _save_product(self, instance):
        raw = self.barcode_input.text.strip()
        barcode = "".join(c for c in raw if c.isprintable()).strip() if raw else None
        # Cadastro manual SEMPRE permitido.
        # Se a API externa não encontrou o código, o utilizador preenche os
        # campos e grava na mesma — produtos locais / sem catálogo online.
        if (
            self.product is None
            and barcode
            and self._barcode_lookup_status == "pending"
        ):
            # Ainda a procurar: não bloqueia o save, só informa.
            self._set_status("A gravar mesmo com pesquisa em curso…", self.COLOR_WARNING)
        if not self._validate_fields():
            return
        expiry = self._process_expiry_date()
        if expiry is False:
            return
        # Limpa estado de lookup para não interferir em cadastros seguintes
        self._barcode_lookup_status = None
        self._save_to_database(barcode, expiry, self.is_sold_by_weight_switch.active)

    def _set_produce_mode(self, enabled):
        self._produce_mode = bool(enabled)
        self.produce_mode_btn.text = "🛒  Venda avulsa - sacos" if enabled else "📦  Stock exato"
        self.sack_weight_input.disabled = not enabled
        if enabled:
            self._set_weight_state(False)
            self._set_pack_sale_state(False)
        self.weight_state_btn.disabled = enabled
        self.pack_sale_state_btn.disabled = enabled
        self.units_per_package_input.disabled = enabled
        self.existing_stock.hint_text = "Sacos disponiveis *" if enabled else "Estoque atual *"
        self.sold_stock.hint_text = "Sacos vendidos inteiros" if enabled else "Vendido"
        self.unit_purchase_price.hint_text = "Custo por saco *" if enabled else "Preco unit. compra *"
        self.sale_price.hint_text = "Preco por unidade *" if enabled else "Preco de venda *"

    def _validate_fields(self):
        if self._produce_mode and self.sack_weight_input.text.strip():
            import math
            weight = self._parse_numeric_input(self.sack_weight_input.text)
            if weight is None or not math.isfinite(weight) or weight <= 0:
                self._show_snackbar("Informe um peso positivo ou deixe vazio.", self.COLOR_ERROR)
                return False
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
        if not self.is_sold_by_weight_switch.active:
            for field, label in (
                (self.existing_stock, "Estoque atual"),
                (self.sold_stock, "Vendido"),
            ):
                try:
                    quantity = float(field.text.strip() or "0")
                except (TypeError, ValueError):
                    self._show_snackbar(f"{label} deve ser um numero inteiro.", self.COLOR_ERROR)
                    return False
                if not quantity.is_integer():
                    self._show_snackbar(
                        f"{label} deve ser inteiro para produtos por unidade.",
                        self.COLOR_ERROR,
                    )
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
        """
        Aceita:
          - DD/MM/AAAA completo
          - 00/MM/AAAA (só mês e ano — comum em embalagens)
        Dia 00 → grava o último dia do mês (validade até ao fim desse mês).
        """
        text = (self.expiry_date.text or "").strip()
        if not text:
            return None

        digits = re.findall(r"\d+", text)
        if len(digits) < 2:
            self._show_snackbar("Data inválida! Use DD/MM/AAAA ou 00/MM/AAAA", self.COLOR_ERROR)
            return False

        try:
            if len(digits) == 2:
                # MM/AAAA
                day, month, year = 0, int(digits[0]), int(digits[1])
            else:
                day, month, year = int(digits[0]), int(digits[1]), int(digits[2])
            if year < 100:
                year += 2000
            if not (1 <= month <= 12) or year < 1990 or year > 2100:
                raise ValueError("mês/ano")
            if day == 0:
                day = calendar.monthrange(year, month)[1]
            elif not (1 <= day <= calendar.monthrange(year, month)[1]):
                raise ValueError("dia")
            return f"{year:04d}-{month:02d}-{day:02d}"
        except Exception:
            self._show_snackbar(
                "Data inválida! Use DD/MM/AAAA (dia 00 = só mês/ano)",
                self.COLOR_ERROR,
            )
            return False

    def _save_to_database(self, barcode, expiry, is_sold_by_weight):
        # Usar a mesma sessão/dono do ecrã admin — senão o produto fica com
        # owner_username=SYSTEM e desaparece da pesquisa e da venda.
        db = getattr(self.admin_screen, "db", None)
        if db is None:
            from database.provider import get_db
            db = get_db()
            admin_db = getattr(self.admin_screen, "db", None)
            if admin_db is not None and hasattr(db, "set_active_user"):
                try:
                    db.set_active_user(
                        getattr(admin_db, "current_user", None),
                        getattr(admin_db, "current_role", None),
                    )
                    if getattr(admin_db, "current_data_owner", None):
                        db.current_data_owner = admin_db.current_data_owner
                except Exception as exc:
                    print(f"[ProductForm] Não foi possível sincronizar dono: {exc}")
        package_quantity = self.package_quantity.text.strip() or None
        allow_pack_sale = bool(getattr(self.allow_pack_sale_switch, "active", False))
        vat_rule_code = self._selected_vat_rule_code or DEFAULT_VAT_RULE_CODE
        produce_options = {
            "stock_mode": "SACKS" if self._produce_mode else "EXACT",
            "sack_weight_kg": self.sack_weight_input.text.strip() or None,
        }
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
            kwargs = {"package_quantity": package_quantity, "vat_rule_code": vat_rule_code,
                      "produce_options": produce_options, "custom_fields": self._custom_field_values()}
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
            kwargs = {"package_quantity": package_quantity, "vat_rule_code": vat_rule_code,
                      "produce_options": produce_options, "custom_fields": self._custom_field_values()}
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
                if _do_update(include_pack_fields=True) is False:
                    raise RuntimeError("Nao foi possivel guardar o produto")
                err = _last_error()
                if _needs_legacy_retry(err):
                    _do_update(include_pack_fields=False)
                    err = _last_error()
                    if not err:
                        self._show_snackbar(
                            "A versao do servidor e antiga; os dados da embalagem nao foram guardados. Reinicie o servidor.",
                            self.COLOR_WARNING,
                        )
                if err:
                    raise RuntimeError(err)
                self._show_snackbar("Produto guardado!", self.COLOR_SUCCESS)
                Clock.schedule_once(lambda dt: self.dismiss(), 1.5)
            else:
                product_id = _do_add(include_pack_fields=True)
                err = _last_error()
                if _needs_legacy_retry(err):
                    product_id = _do_add(include_pack_fields=False)
                    err = _last_error()
                    if not err:
                        self._show_snackbar(
                            "A versao do servidor e antiga; os dados da embalagem nao foram guardados. Reinicie o servidor.",
                            self.COLOR_WARNING,
                        )
                if err or not product_id:
                    raise RuntimeError(err or "Falha ao cadastrar produto.")
                self._show_snackbar("Produto cadastrado!", self.COLOR_SUCCESS)
                Clock.schedule_once(lambda dt: self._clear_fields(), 1.5)
            self.admin_screen.load_products(force=True)
        except Exception as e:
            self._show_snackbar(f"Erro ao salvar produto: {e}", self.COLOR_ERROR)
        finally:
            # Não fechar a conexão partilhada do admin_screen
            if db is not getattr(self.admin_screen, "db", None):
                try:
                    db.close()
                except Exception:
                    pass

    def _clear_fields(self, preserve_barcode=False, barcode_value=None):
        fields = [self.sku_input, self.expiry_date, self.description,
                  self.existing_stock, self.sale_price, self.total_purchase_price,
                  self.unit_purchase_price, self.category_field, self.package_quantity,
                  self.units_per_package_input, self.sack_weight_input]
        if not preserve_barcode:
            fields.insert(0, self.barcode_input)
        self._calculating = True
        try:
            for f in fields:
                f.text = ""
            if preserve_barcode:
                self.barcode_input.text = self._sanitize_barcode(barcode_value or self.barcode_input.text)
                self._barcode_context = self.barcode_input.text or None
            else:
                self.barcode_input.text = ""
                self._barcode_context = None
                self._queued_barcode_request = None
                self._barcode_lookup_status = None
            self.sold_stock.text = "0"
        finally:
            self._calculating = False
        self._set_produce_mode(False)
        self._set_weight_state(False)
        self._set_pack_sale_state(False)
        self._category_lookup_inflight = False
        self._category_lookup_barcode  = None
        self._category_lookup_token    = 0
        self._discount_base_price      = None
        self._applying_price_action    = False
        self._auto_unit_purchase_price = False
        self._auto_total_purchase_price = False
        self._auto_sale_price          = False
        self._cost_source_field        = None
        self._update_price_actions_state()
        self._set_vat_rule(DEFAULT_VAT_RULE_CODE)

    def _populate_fields(self):
        p = self.product
        from database.provider import get_db
        db = get_db()
        try:
            settings = db.get_produce_settings(p[0]) or {}
            custom_values = db.get_product_custom_field_values(p[0]) or {}
        finally:
            db.close()
        self._set_produce_mode(settings.get("stock_mode") == "SACKS")
        self.sack_weight_input.text = str(settings.get("sack_weight_kg") or "")
        self._calculating = True
        try:
            self.description.text          = p[1]
            self.category_field.text       = p[11] if len(p) > 11 else ""
            self.existing_stock.text       = str(p[2])
            self.sold_stock.text           = str(p[3])
            self.sale_price.text           = str(p[4])
            self.total_purchase_price.text = str(p[5])
            self.unit_purchase_price.text  = str(p[6])
            if len(p) > 21 and p[21]:
                self.package_quantity.text = str(p[21])
            if len(p) > 22 and p[22]:
                self.sku_input.text = str(p[22])
            if len(p) > 23 and p[23] not in (None, ""):
                self.units_per_package_input.text = str(int(float(p[23])))
            if len(p) > 12 and p[12]:
                self.barcode_input.text = str(p[12])
            if len(p) > 13 and p[13]:
                try:
                    self.expiry_date.text = datetime.strptime(str(p[13]), "%Y-%m-%d").strftime("%d/%m/%Y")
                except ValueError:
                    self.expiry_date.text = str(p[13])
        finally:
            self._calculating = False
        self._barcode_context = self._sanitize_barcode(self.barcode_input.text) or None
        self._discount_base_price      = None
        self._auto_unit_purchase_price = False
        self._auto_total_purchase_price = False
        self._auto_sale_price          = False
        self._cost_source_field        = "unit" if self._parse_numeric_input(self.unit_purchase_price.text) is not None else None
        is_weight = bool(p[15]) if len(p) > 15 else False
        self._set_weight_state(is_weight)
        self._set_pack_sale_state(bool(p[24]) if (len(p) > 24 and not is_weight) else False)
        self._set_vat_rule(str(p[25]) if len(p) > 25 and p[25] else DEFAULT_VAT_RULE_CODE)
        self._refresh_custom_fields_widgets(custom_values)
        self._update_price_actions_state()

    # -- Beep ---------------------------------------------------------------
    @staticmethod
    def _load_beep_sound():
        try:
            s = SoundLoader.load("assets/sounds/beep.wav")
            if s: s.volume = 0.7
            return s
        except Exception: return None

    def _play_beep(self):
        beep_sound = self._get_beep_sound()
        if not beep_sound: return
        try:
            if beep_sound.state == "play": beep_sound.stop()
            beep_sound.play()
        except Exception: pass

    # -- Snackbar / status --------------------------------------------------
    def _show_snackbar(self, message, color):
        message = correct_portuguese_text(message)
        toast = BoxLayout(size_hint=(None, None), size=(dp(320), dp(52)), padding=dp(14), opacity=0)
        with toast.canvas.before:
            Color(*color)
            bg = RoundedRectangle(pos=toast.pos, size=toast.size, radius=[dp(8)])
        toast.bind(pos=lambda i,v: setattr(bg,"pos",i.pos), size=lambda i,v: setattr(bg,"size",i.size))
        lbl = Label(text=message, color=(1,1,1,1), font_size=sp(13), halign="center", valign="middle")
        lbl.bind(size=lbl.setter("text_size"))
        toast.add_widget(lbl)
        if getattr(self, "_page_content", None) is not None:
            content = self._page_content
            toast.pos = (content.center_x - toast.width/2, content.y + dp(16))
            content.add_widget(toast)
            Animation(opacity=1, duration=0.25).start(toast)
            def _rm(dt):
                a = Animation(opacity=0, duration=0.25)
                a.bind(on_complete=lambda *_: content.remove_widget(toast))
                a.start(toast)
            Clock.schedule_once(_rm, 2.2)

    def _set_status(self, text, color):
        text = correct_portuguese_text(text)
        self.scanner_status.text  = text
        self.scanner_status.color = color

    # -- Lifecycle ----------------------------------------------------------
    def open(self):
        """Compatibilidade com os chamadores antigos, abrindo uma pagina."""
        manager = getattr(self.admin_screen, "manager", None)
        if manager is None:
            return self
        if self.name in manager.screen_names:
            existing = manager.get_screen(self.name)
            if existing is not self:
                manager.remove_widget(existing)
        if self.manager is None:
            manager.add_widget(self)
        manager.current = self.name
        self.on_open()
        return self

    def dismiss(self, *_args):
        """Fecha a pagina e regressa ao catalogo de produtos."""
        manager = self.manager or getattr(self.admin_screen, "manager", None)
        self.on_dismiss()
        if manager is None:
            return
        target = getattr(self.admin_screen, "name", "admin")
        if target in manager.screen_names:
            manager.current = target
        Clock.schedule_once(
            lambda _dt: manager.remove_widget(self) if self.parent is manager else None,
            0.15,
        )

    def on_open(self):
        # -- ALTERAÇÃO 3: auto-start removido — scanner só arranca quando
        #    o utilizador clicar no botao. --
        if self._field_navigation:
            self._field_navigation.activate(focus_initial=False)
        Clock.schedule_once(self._warm_lazy_dependencies, 0)

    def on_dismiss(self):
        if self._field_navigation:
            self._field_navigation.deactivate()
        if self.category_menu:
            try:
                self.category_menu.dismiss()
            except Exception:
                pass
        if self._vat_menu:
            try:
                self._vat_menu.dismiss()
            except Exception:
                pass
        if self._shortcut_help_dialog:
            try:
                self._shortcut_help_dialog.dismiss()
            except Exception:
                pass
            self._shortcut_help_dialog = None
        if self.scanning:
            self._stop_scanner()
        Window.unbind(on_resize=self._on_window_resize)
