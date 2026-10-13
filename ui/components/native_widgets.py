"""Widgets de interface baseados exclusivamente em Kivy.



Esta camada concentra as propriedades visuais que eram usadas nos widgets

Material, mas sem depender de KivyMD. Ela existe para permitir uma migração

gradual dos ecrãs, mantendo cores, cantos e tipografia consistentes.

"""



from __future__ import annotations



from pathlib import Path

from datetime import date

import calendar



from kivy.event import EventDispatcher

from kivy.app import App

from kivy.factory import Factory

from kivy.clock import Clock

from kivy.core.image import Image as CoreImage

from kivy.core.window import Window

from kivy.graphics import Color, Line, RoundedRectangle

from kivy.metrics import dp, sp

from kivy.properties import (

    BooleanProperty,

    ListProperty,

    NumericProperty,

    ObjectProperty,

    StringProperty,

)

from kivy.uix.behaviors import ButtonBehavior

from kivy.uix.boxlayout import BoxLayout

from kivy.uix.button import Button

from kivy.uix.checkbox import CheckBox

from kivy.uix.dropdown import DropDown

from kivy.uix.gridlayout import GridLayout

from kivy.uix.label import Label

from kivy.uix.modalview import ModalView

from kivy.uix.progressbar import ProgressBar

from kivy.uix.screenmanager import Screen

from kivy.uix.scrollview import ScrollView

from kivy.uix.textinput import TextInput

from kivy.uix.widget import Widget





_ICON_FONT = str(

    Path(__file__).resolve().parents[2] / "assets" / "fonts" /

    "materialdesignicons-webfont.ttf"

)



# Catálogo mínimo local. Novos ícones são acrescentados apenas quando uma

# tela migrada os utiliza; não há consulta ao catálogo do KivyMD em runtime.

NATIVE_ICONS = {

    'logout': '\U000f0343', 'refresh': '\U000f0450', 'menu': '\U000f035c',

    'close': '\U000f0156', 'chevron-left': '\U000f0141', 'chevron-right': '\U000f0142', 'arrow-left': '\U000f004d',

    'package-variant-closed': '\U000f03d7', 'plus': '\U000f0415',

    'minus': '\U000f0374', 'delete': '\U000f01b4', 'pencil': '\U000f03eb',

    'calendar': '\U000f00ed', 'barcode-scan': '\U000f0072',

    'camera-switch': '\U000f0108', 'account': '\U000f0004', 'cart': '\U000f0110',

    'history': '\U000f02da', 'check': '\U000f012c', 'alert': '\U000f0026',

    'information': '\U000f02fc', 'cog': '\U000f0493', 'cash-register': '\U000f0cf4',

    'file-pdf-box': '\U000f0226', 'magnify': '\U000f0349', 'filter': '\U000f0232',

    'filter-variant': '\U000f0233', 'plus-circle': '\U000f0417',

    'archive-arrow-up-outline': '\U000f125a', 'cart-outline': '\U000f0111',

    'clipboard-list-outline': '\U000f10d5', 'view-dashboard-outline': '\U000f0a1e',

    'bell': '\U000f009a', 'eye-outline': '\U000f06d0',

    'package-variant-closed-plus': '\U000f19d5',

    'server-network': '\U000f048d',

    'account-key-outline': '\U000f0be4', 'account-plus': '\U000f000e',

    'email-check-outline': '\U000f0ab2', 'format-list-numbered': '\U000f027b',

    'information-outline': '\U000f02fd', 'lock-check-outline': '\U000f16a8',

    'menu-down': '\U000f035d', 'pause-circle-outline': '\U000f03e6',

    'shield-alert-outline': '\U000f0ecd', 'shield-lock-outline': '\U000f0ccc',

    'translate': '\U000f05ca',

    'lightbulb-on': '\U000f06e8',

    # Painel administrativo: mantidos na fonte local para que cards e ações

    # continuem legíveis sem o catálogo de ícones do KivyMD.

    'cash-multiple': '\U000f0116', 'text-box-search-outline': '\U000f0eaf',

    'package-variant': '\U000f03d6', 'package-variant-plus': '\U000f19d8',

    'alert-circle-outline': '\U000f05d6', 'chart-box-outline': '\U000f154e',

    'cog-outline': '\U000f08bb', 'calendar-remove-outline': '\U000f0c45',

    'alert-decagram-outline': '\U000f0ce5',

    'close-octagon-outline': '\U000f015d',

    'calendar-clock-outline': '\U000f16e1',

    'clipboard-alert-outline': '\U000f0cf7', 'cash-remove': '\U000f1262',

    'check-circle-outline': '\U000f05e1', 'star-circle-outline': '\U000f09a4',

    'trending-up': '\U000f0535', 'trending-down': '\U000f0533',

    'alert-circle': '\U000f0028', 'chart-line': '\U000f012a',

    'check-circle': '\U000f05e0',

    'numeric-1-circle': '\U000f0ca0', 'numeric-2-circle-outline': '\U000f0ca3',

    'close-circle': '\U000f0159', 'camera-wireless': '\U000f0db6',

    'format-list-bulleted': '\U000f0279',

    'chevron-left': '\U000f0141', 'fullscreen': '\U000f0293',

    'printer': '\U000f042a', 'chevron-down': '\U000f0140',

    'chevron-up': '\U000f013f',

}





class NativeTheme(EventDispatcher):

    """Tema leve, observável e independente de qualquer biblioteca externa."""



    theme_style = StringProperty("Light")

    primary_palette = StringProperty("Blue")

    primary_hue = StringProperty("800")

    accent_palette = StringProperty("BlueGray")

    accent_hue = StringProperty("600")

    material_style = StringProperty("M3")

    theme_style_switch_animation = BooleanProperty(False)

    theme_style_switch_animation_duration = NumericProperty(0)

    primary_color = ListProperty([0.08, 0.32, 0.62, 1])

    primary_light = ListProperty([0.20, 0.45, 0.72, 1])

    primary_dark = ListProperty([0.05, 0.22, 0.45, 1])

    accent_color = ListProperty([0.35, 0.42, 0.50, 1])

    text_color = ListProperty([0.12, 0.15, 0.20, 1])

    secondary_text_color = ListProperty([0.35, 0.40, 0.50, 1])

    disabled_hint_text_color = ListProperty([0.55, 0.60, 0.70, 1])

    disabled_primary_color = ListProperty([0.55, 0.60, 0.70, 1])

    divider_color = ListProperty([0, 0, 0, .12])

    error_color = ListProperty([0.78, 0.22, 0.24, 1])

    ripple_color = ListProperty([0.08, 0.32, 0.62, .18])

    bg_light = ListProperty([.98, .98, .99, 1])

    bg_normal = ListProperty([.96, .97, .98, 1])

    bg_dark = ListProperty([.15, .17, .21, 1])

    bg_darkest = ListProperty([.08, .10, .13, 1])

    opposite_bg_dark = ListProperty([.15, .17, .21, 1])

    horizontal_margins = NumericProperty(dp(24))

    standard_increment = NumericProperty(dp(56))

    device_orientation = StringProperty("portrait")

    colors = ObjectProperty({}, allownone=False)

    font_styles = ObjectProperty({

        "H4": ["Roboto", 34, False, 1.15], "H5": ["Roboto", 24, False, 1.2],

        "H6": ["Roboto", 20, False, 1.2], "Subtitle1": ["Roboto", 16, False, 1.5],

        "Subtitle2": ["Roboto", 14, False, 1.43], "Body1": ["Roboto", 16, False, 1.5],

        "Body2": ["Roboto", 14, False, 1.43], "Button": ["Roboto", 14, True, 1.0],

        "Caption": ["Roboto", 12, False, 1.33], "Overline": ["Roboto", 10, True, 1.6],

        # Asset local: mantém os ícones nas telas remanescentes sem depender

        # da fonte instalada dentro do pacote KivyMD.

        "Icon": [_ICON_FONT, 24, False, 1.0],

    }, allownone=False)





def _normalize_radius(radius):

    values = list(radius or [0])

    if len(values) == 1:

        return values * 4

    return values[:4]





class NativeAdaptiveMixin:

    adaptive_height = BooleanProperty(False)

    adaptive_width = BooleanProperty(False)

    adaptive_size = BooleanProperty(False)



    def _install_adaptive_size(self):

        self._adaptive_height_bound = False

        self._adaptive_width_bound = False

        self.bind(

            adaptive_height=self._apply_adaptive_size,

            adaptive_width=self._apply_adaptive_size,

            adaptive_size=self._apply_adaptive_size,

        )

        self._apply_adaptive_size()



    def _apply_adaptive_size(self, *_args):

        height = self.adaptive_height or self.adaptive_size

        width = self.adaptive_width or self.adaptive_size

        if height:

            self.size_hint_y = None

            if not self._adaptive_height_bound:

                self.bind(minimum_height=lambda instance, value: setattr(instance, "height", value))

                self._adaptive_height_bound = True

        if width:

            self.size_hint_x = None

            if not self._adaptive_width_bound:

                self.bind(minimum_width=lambda instance, value: setattr(instance, "width", value))

                self._adaptive_width_bound = True





class NativeBoxLayout(NativeAdaptiveMixin, BoxLayout):

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self._install_adaptive_size()





class NativeGridLayout(NativeAdaptiveMixin, GridLayout):

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self._install_adaptive_size()





class NativeListLayout(NativeBoxLayout):

    """Lista vertical adaptativa para o contrato ``MDList``.



    A lista Material original empilhava os itens. Mapear esse nome para um

    ``BoxLayout`` horizontal comprimia todos os produtos numa única linha.

    """



    def __init__(self, **kwargs):

        kwargs.setdefault("orientation", "vertical")

        kwargs.setdefault("adaptive_height", True)

        super().__init__(**kwargs)





class NativeScrollView(ScrollView):

    pass





class NativeScreen(Screen):

    """Screen com fundo opcional desenhado em canvas."""



    md_bg_color = ListProperty([0, 0, 0, 0])

    radius = ListProperty([0])

    line_color = ListProperty([0, 0, 0, 0])

    line_width = NumericProperty(0)



    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        with self.canvas.before:

            self._background_color = Color(rgba=self.md_bg_color)

            self._background = RoundedRectangle(pos=self.pos, size=self.size, radius=_normalize_radius(self.radius))

            self._border_color = Color(rgba=self.line_color)

            self._border = Line(rounded_rectangle=(self.x, self.y, self.width, self.height, 0), width=self.line_width)

        self.bind(pos=self._sync_canvas, size=self._sync_canvas, md_bg_color=self._sync_canvas,

                  radius=self._sync_canvas, line_color=self._sync_canvas, line_width=self._sync_canvas)



    def _sync_canvas(self, *_args):

        self._background_color.rgba = self.md_bg_color

        self._background.pos = self.pos

        self._background.size = self.size

        self._background.radius = _normalize_radius(self.radius)

        self._border_color.rgba = self.line_color

        self._border.width = max(0.001, self.line_width)

        self._border.rounded_rectangle = (self.x, self.y, self.width, self.height, _normalize_radius(self.radius)[0])





class NativeLabel(Label):

    """Label com as propriedades tipográficas usadas pelos ecrãs atuais."""



    font_style = StringProperty("")

    theme_text_color = StringProperty("Primary", allownone=True)

    text_color = ListProperty([0.12, 0.15, 0.20, 1])

    specific_text_color = ListProperty([0.12, 0.15, 0.20, 1])

    specific_secondary_text_color = ListProperty([0.35, 0.40, 0.50, 1])



    _FONT_STYLES = {

        "H4": 34, "H5": 24, "H6": 20, "Subtitle1": 16,

        "Subtitle2": 14, "Body1": 16, "Body2": 14,

        "Button": 14, "Caption": 12,

    }



    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self._native_auto_text_width = False

        self.bind(font_style=self._apply_font_style, text_color=self._apply_color,

                  theme_text_color=self._apply_color, size=self._sync_text_width,

                  shorten=self._sync_text_width, halign=self._sync_text_width)

        self._apply_font_style()

        self._apply_color()

        self._sync_text_width()



    def _sync_text_width(self, *_args):

        """Dá uma largura real a labels alinhadas/encurtadas em layouts Kivy."""

        needs_width = bool(self.shorten or self.halign != "left")

        if not needs_width:

            # O widget Ã© criado antes de as propriedades KV serem aplicadas.

            # Se o alinhamento final for Ã  esquerda, remova apenas a largura

            # automÃ¡tica criada durante essa fase inicial.

            if self._native_auto_text_width:

                self.text_size = (None, self.text_size[1])

                self._native_auto_text_width = False

            return

        current = self.text_size

        if self._native_auto_text_width or current[0] is None:

            self._native_auto_text_width = True

            self.text_size = (self.width, current[1])



    def _apply_font_style(self, *_args):

        size = self._FONT_STYLES.get(self.font_style)

        if size:

            self.font_size = sp(size)



    def _apply_color(self, *_args):

        theme = getattr(App.get_running_app(), "theme_cls", None)

        if self.theme_text_color == "Secondary" and theme:

            self.color = theme.secondary_text_color

        elif self.theme_text_color in {"Hint", "Disabled"} and theme:

            self.color = theme.disabled_hint_text_color

        elif self.theme_text_color == "Error" and theme:

            self.color = theme.error_color

        else:

            self.color = self.text_color





class NativeIcon(NativeLabel):

    """Base de ícone. O mapeamento para a fonte local é migrado por família."""



    icon = StringProperty("")

    icon_size = NumericProperty(sp(20))



    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self.font_name = _ICON_FONT

        self.bind(icon=self._sync_icon, icon_size=self._sync_icon)

        self._sync_icon()



    def _sync_icon(self, *_args):

        self.font_size = self.icon_size

        self.text = NATIVE_ICONS.get(self.icon, self.icon)





class NativeSpinner(Widget):

    """Indicador circular compacto, equivalente ao spinner usado no overlay."""



    active = BooleanProperty(False)

    color = ListProperty([0.08, 0.32, 0.62, 1])

    angle = NumericProperty(0)



    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        # O spinner anterior ficava com o azul padrão, mesmo em temas onde a

        # ação principal usa outra tonalidade.  Mantém o tom de destaque do

        # tema, como o MDSpinner fazia.

        app = App.get_running_app()

        tokens = getattr(app, "theme_tokens", {}) if app else {}

        if "color" not in kwargs:

            self.color = list(tokens.get("focus", tokens.get("primary", self.color)))

        with self.canvas:

            self._color = Color(rgba=self.color)

            self._arc = Line(circle=(self.center_x, self.center_y, dp(18), 30, 300), width=dp(3))

        self.bind(pos=self._sync_spinner, size=self._sync_spinner, color=self._sync_spinner,

                  angle=self._sync_spinner, active=self._sync_spinner)

        self.bind(active=self._sync_spinner_event)

        self._event = None

        self._sync_spinner()



    def _sync_spinner_event(self, *_args):

        should_animate = self.active and self.parent is not None

        if should_animate and self._event is None:

            self._event = Clock.schedule_interval(self._tick, 1 / 30)

        elif not should_animate and self._event is not None:

            self._event.cancel()

            self._event = None



    def _tick(self, dt):

        if self.active:

            self.angle = (self.angle + dt * 330) % 360



    def _sync_spinner(self, *_args):

        self._color.rgba = self.color

        radius = max(1, min(self.width, self.height) / 2 - dp(3))

        self._arc.circle = (self.center_x, self.center_y, radius, self.angle + 30, self.angle + 300)

        self._arc.width = dp(3) if self.active else 0.001



    def on_parent(self, _widget, parent):

        self._sync_spinner_event()





class _CanvasSurface:

    md_bg_color = ListProperty([1, 1, 1, 1])

    radius = ListProperty([0])

    line_color = ListProperty([0, 0, 0, 0])

    line_width = NumericProperty(0)

    elevation = NumericProperty(0)

    ripple_behavior = BooleanProperty(False)



    def _install_surface(self):

        with self.canvas.before:

            self._shadow_color = Color(0, 0, 0, 0)

            self._shadow = RoundedRectangle(pos=self.pos, size=self.size, radius=_normalize_radius(self.radius))

            self._surface_color = Color(rgba=self.md_bg_color)

            self._surface = RoundedRectangle(pos=self.pos, size=self.size, radius=_normalize_radius(self.radius))

            self._line_color = Color(rgba=self.line_color)

            self._line = Line(rounded_rectangle=(self.x, self.y, self.width, self.height, 0), width=self.line_width)

        self.bind(pos=self._sync_surface, size=self._sync_surface, md_bg_color=self._sync_surface,

                  radius=self._sync_surface, line_color=self._sync_surface, line_width=self._sync_surface,

                  elevation=self._sync_surface)

        self._sync_surface()



    def _sync_surface(self, *_args):

        radius = _normalize_radius(self.radius)

        offset = min(dp(6), max(0, self.elevation) * dp(.7))

        self._shadow_color.rgba = [0, 0, 0, min(.22, self.elevation * .035)]

        self._shadow.pos = (self.x, self.y - offset)

        self._shadow.size = self.size

        self._shadow.radius = radius

        self._surface_color.rgba = self.md_bg_color

        self._surface.pos = self.pos

        self._surface.size = self.size

        self._surface.radius = radius

        self._line_color.rgba = self.line_color

        # Kivy exige largura estritamente positiva; cor transparente mantém

        # o resultado visual quando a borda está desativada.

        self._line.width = max(0.001, self.line_width)

        self._line.rounded_rectangle = (self.x, self.y, self.width, self.height, radius[0])





class NativeCard(_CanvasSurface, NativeBoxLayout):

    def __init__(self, **kwargs):

        if "md_bg_color" not in kwargs:

            app = App.get_running_app()

            tokens = getattr(app, "theme_tokens", {}) if app else {}

            kwargs["md_bg_color"] = list(tokens.get("card", [1, 1, 1, 1]))

        super().__init__(**kwargs)

        self._install_surface()





class NativeActionCard(ButtonBehavior, NativeCard):

    """Card clicável com ButtonBehavior antes do layout no MRO."""



    pass





class NativeButton(_CanvasSurface, Button):

    md_bg_color = ListProperty([0.08, 0.32, 0.62, 1])

    text_color = ListProperty([1, 1, 1, 1])

    theme_text_color = StringProperty("Custom")

    font_style = StringProperty("Button")



    def __init__(self, **kwargs):

        kwargs.setdefault("background_normal", "")

        kwargs.setdefault("background_down", "")

        kwargs.setdefault("background_color", [0, 0, 0, 0])

        super().__init__(**kwargs)

        self.color = self.text_color

        self._install_surface()

        self.bind(state=self._sync_button, text_color=self._sync_button)



    def _sync_button(self, *_args):

        self.color = self.text_color

        self.opacity = 0.88 if self.disabled else 1





class NativeFlatButton(NativeButton):

    md_bg_color = ListProperty([0, 0, 0, 0])

    text_color = ListProperty([0.08, 0.32, 0.62, 1])

    elevation = NumericProperty(0)





class NativeIconButton(NativeButton):

    icon = StringProperty("")

    icon_size = NumericProperty(sp(24))

    tooltip_text = StringProperty("")

    text = StringProperty("")



    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self.font_name = _ICON_FONT

        self._icon_asset_texture = None

        with self.canvas.after:

            self._icon_asset_color = Color(1, 1, 1, 0)

            self._icon_asset = RoundedRectangle(pos=self.pos, size=(0, 0), radius=[0])

        self.bind(icon=self._sync_icon, icon_size=self._sync_icon)

        self.bind(pos=self._sync_icon_asset, size=self._sync_icon_asset)

        self._sync_icon()



    def _sync_icon(self, *_args):

        icon_value = str(self.icon or "")

        asset_path = Path(icon_value)

        if icon_value and asset_path.is_file():

            try:

                self._icon_asset_texture = CoreImage(str(asset_path)).texture

                self.text = ""

                self._icon_asset_color.a = 1

                self._sync_icon_asset()

                return

            except Exception:

                self._icon_asset_texture = None

        self._icon_asset_texture = None

        self._icon_asset_color.a = 0

        self.font_size = self.icon_size

        if icon_value:

            self.text = NATIVE_ICONS.get(icon_value, icon_value)



    def _sync_icon_asset(self, *_args):

        texture = self._icon_asset_texture

        if texture is None:

            self._icon_asset.size = (0, 0)

            return

        side = min(float(self.icon_size), float(self.width), float(self.height)) * 0.82

        self._icon_asset.texture = texture

        self._icon_asset.size = (side, side)

        self._icon_asset.pos = (self.center_x - side / 2, self.center_y - side / 2)





class NativeIconTextButton(ButtonBehavior, NativeCard):

    """Botão de texto com ícone, usado onde o layout Material o combinava."""



    text = StringProperty("")

    icon = StringProperty("")

    text_color = ListProperty([0.08, 0.32, 0.62, 1])

    theme_text_color = StringProperty("Custom")

    font_size = NumericProperty(sp(14))



    def __init__(self, **kwargs):

        kwargs.setdefault("orientation", "horizontal")

        kwargs.setdefault("spacing", dp(6))

        kwargs.setdefault("padding", [dp(12), dp(6)])

        kwargs.setdefault("radius", [dp(8)])

        kwargs.setdefault("md_bg_color", [0, 0, 0, 0])

        kwargs.setdefault("line_color", [0.08, 0.32, 0.62, 1])

        kwargs.setdefault("line_width", 1)

        super().__init__(**kwargs)

        self._icon = NativeIcon(size_hint_x=None, width=dp(20), halign="center", valign="middle")

        self._label = NativeLabel(halign="center", valign="middle")

        self.add_widget(self._icon)

        self.add_widget(self._label)

        self.bind(text=self._sync_icon_text, icon=self._sync_icon_text,

                  text_color=self._sync_icon_text, font_size=self._sync_icon_text)

        self._sync_icon_text()



    def _sync_icon_text(self, *_args):

        self._icon.icon = self.icon

        self._icon.text_color = self.text_color

        self._label.text = self.text

        self._label.text_color = self.text_color

        self._label.font_size = self.font_size





class NativeDropdownItem(NativeButton):

    """Campo de seleção outlined, próximo ao ``MDDropDownItem`` original."""



    def __init__(self, **kwargs):

        app = App.get_running_app()

        tokens = getattr(app, "theme_tokens", {}) if app else {}

        kwargs.setdefault("size_hint_y", None)

        kwargs.setdefault("height", dp(48))

        kwargs.setdefault("padding", [dp(14), 0])

        kwargs.setdefault("radius", [dp(10)])

        kwargs.setdefault("elevation", 0)

        kwargs.setdefault("md_bg_color", tokens.get("surface", tokens.get("card", [1, 1, 1, 1])))

        kwargs.setdefault("line_color", tokens.get("outline", [0.35, 0.40, 0.50, 1]))

        kwargs.setdefault("line_width", 1)

        kwargs.setdefault("text_color", tokens.get("text_primary", [0.12, 0.15, 0.20, 1]))

        super().__init__(**kwargs)

        self._selected_text = str(self.text or "")

        self.bind(size=self._sync_dropdown_text)

        self._sync_dropdown_text()



    def set_item(self, text):

        self._selected_text = str(text or "")

        self._sync_dropdown_text()



    def _sync_dropdown_text(self, *_args):

        # A seta discreta devolve a indicação de controlo selecionável que o

        # KivyMD mostrava, sem transformar o campo num botão azul sólido.

        self.text = f"{self._selected_text}   ▾".rstrip()

        self.halign = "left"

        self.valign = "middle"

        self.text_size = (max(0, self.width - dp(26)), self.height)





class NativeListItem(ButtonBehavior, NativeCard):

    text = StringProperty("")

    secondary_text = StringProperty("")

    text_color = ListProperty([.12, .15, .20, 1])



    def __init__(self, **kwargs):

        kwargs.setdefault("orientation", "vertical")

        kwargs.setdefault("padding", [dp(16), dp(7)])

        kwargs.setdefault("md_bg_color", [0, 0, 0, 0])

        kwargs.setdefault("size_hint_y", None)

        kwargs.setdefault("height", dp(56))

        super().__init__(**kwargs)

        self._primary = NativeLabel(halign="left", valign="middle", shorten=True, text_size=(None, None))

        self._secondary = NativeLabel(halign="left", valign="middle", shorten=True, text_size=(None, None), font_style="Caption")

        self.add_widget(self._primary)

        self.add_widget(self._secondary)

        self.bind(text=self._sync_text, secondary_text=self._sync_text, text_color=self._sync_text)

        self._sync_text()



    def _sync_text(self, *_args):

        self._primary.text = self.text

        self._primary.text_color = self.text_color

        self._secondary.text = self.secondary_text

        self._secondary.text_color = self.text_color

        self._secondary.opacity = 1 if self.secondary_text else 0





class NativeProgressBar(ProgressBar):

    color = ListProperty([0.08, .32, .62, 1])





class NativeCheckbox(CheckBox):

    pass





class NativeSwitch(ButtonBehavior, Widget):

    """Interruptor booleano com o contrato ``active`` do formulário."""



    active = BooleanProperty(False)

    disabled = BooleanProperty(False)

    active_color = ListProperty([0.08, 0.32, 0.62, 1])

    inactive_color = ListProperty([.45, .48, .55, 1])



    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        with self.canvas:

            self._track_color = Color()

            self._track = RoundedRectangle(radius=[dp(12)] * 4)

            self._thumb_color = Color(1, 1, 1, 1)

            self._thumb = RoundedRectangle(radius=[dp(10)] * 4)

        self.bind(pos=self._sync_switch, size=self._sync_switch, active=self._sync_switch,

                  disabled=self._sync_switch, active_color=self._sync_switch,

                  inactive_color=self._sync_switch)

        self._sync_switch()



    def _sync_switch(self, *_args):

        width, height = self.size

        track_height = min(dp(20), height)

        y = self.y + (height - track_height) / 2

        self._track.pos = (self.x, y)

        self._track.size = (width, track_height)

        color = self.active_color if self.active else self.inactive_color

        self._track_color.rgba = [*color[:3], .45 if not self.disabled else .22]

        thumb_size = min(dp(20), track_height)

        x = self.right - thumb_size if self.active else self.x

        self._thumb.pos = (x, y)

        self._thumb.size = (thumb_size, thumb_size)

        self._thumb_color.rgba = [1, 1, 1, .55 if self.disabled else 1]



    def on_release(self):

        if not self.disabled:

            self.active = not self.active





class NativeDatePicker(ModalView):

    """Calendário local compatível com o evento ``on_save`` do MDDatePicker."""



    def __init__(self, year=None, month=None, day=None, **kwargs):

        kwargs.setdefault("size_hint", (.82, None))

        kwargs.setdefault("height", dp(410))

        kwargs.setdefault("background_color", [0, 0, 0, .45])

        super().__init__(**kwargs)

        app = App.get_running_app()

        tokens = getattr(app, "theme_tokens", {}) if app else {}

        self._calendar_primary = list(tokens.get("primary", [0.08, 0.38, 0.72, 1]))

        self._calendar_on_primary = list(tokens.get("on_primary", [1, 1, 1, 1]))

        self._calendar_text = list(tokens.get("text_primary", [.88, .91, .96, 1]))

        self._calendar_muted = list(tokens.get("text_secondary", [.62, .68, .78, 1]))

        self._calendar_surface = list(tokens.get("card_alt", [.10, .14, .20, 1]))

        today = date.today()

        self._selected = date(year or today.year, month or today.month, day or today.day)

        self._display_year = self._selected.year

        self._display_month = self._selected.month



        content = NativeCard(orientation="vertical", padding=[dp(20), dp(16)], spacing=dp(10), radius=[dp(16)])

        content.add_widget(NativeLabel(text="Selecionar data", font_style="H6", bold=True,

                                       theme_text_color="Custom", text_color=self._calendar_text,

                                       size_hint_y=None, height=dp(30)))



        month_bar = NativeBoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))

        previous = NativeIconButton(icon="chevron-left", size_hint=(None, None), size=(dp(36), dp(36)),

                                    radius=[dp(18)], theme_text_color="Custom", text_color=self._calendar_primary,

                                    md_bg_color=[*self._calendar_primary[:3], .12])

        self._month_label = NativeLabel(halign="center", valign="middle", bold=True,

                                        theme_text_color="Custom", text_color=self._calendar_text)

        next_ = NativeIconButton(icon="chevron-right", size_hint=(None, None), size=(dp(36), dp(36)),

                                 radius=[dp(18)], theme_text_color="Custom", text_color=self._calendar_primary,

                                 md_bg_color=[*self._calendar_primary[:3], .12])

        previous.bind(on_release=lambda *_args: self._change_month(-1))

        next_.bind(on_release=lambda *_args: self._change_month(1))

        month_bar.add_widget(previous)

        month_bar.add_widget(self._month_label)

        month_bar.add_widget(next_)

        content.add_widget(month_bar)



        self._calendar_grid = NativeGridLayout(cols=7, spacing=dp(3), size_hint_y=None,

                                                height=dp(226), row_default_height=dp(28),

                                                row_force_default=True)

        content.add_widget(self._calendar_grid)



        actions = NativeBoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))

        cancel = NativeFlatButton(text="CANCELAR", text_color=self._calendar_primary, radius=[dp(10)])

        today_button = NativeFlatButton(text="HOJE", text_color=self._calendar_primary, radius=[dp(10)])

        save = NativeButton(text="SELECIONAR", text_color=self._calendar_on_primary,

                            md_bg_color=self._calendar_primary, radius=[dp(10)])

        cancel.bind(on_release=lambda *_args: self.dismiss())

        today_button.bind(on_release=self._select_today)

        save.bind(on_release=self._save)

        actions.add_widget(cancel)

        actions.add_widget(today_button)

        actions.add_widget(save)

        content.add_widget(actions)

        self.add_widget(content)

        self.register_event_type("on_save")

        self._render_calendar()



    def _change_month(self, delta):

        month = self._display_month + delta

        if month == 0:

            self._display_year -= 1

            month = 12

        elif month == 13:

            self._display_year += 1

            month = 1

        self._display_month = month

        self._render_calendar()



    def _render_calendar(self):

        self._calendar_grid.clear_widgets()

        self._month_label.text = "%s %d" % (calendar.month_name[self._display_month].capitalize(), self._display_year)

        for weekday in ("SEG", "TER", "QUA", "QUI", "SEX", "SÁB", "DOM"):

            self._calendar_grid.add_widget(NativeLabel(text=weekday, halign="center", valign="middle",

                                                        font_size=sp(10), theme_text_color="Custom",

                                                        text_color=self._calendar_muted))



        first_weekday, days_in_month = calendar.monthrange(self._display_year, self._display_month)

        for _ in range(first_weekday):

            self._calendar_grid.add_widget(Widget())

        for day in range(1, days_in_month + 1):

            value = date(self._display_year, self._display_month, day)

            selected = value == self._selected

            button = NativeButton(text=str(day), size_hint_y=None, height=dp(28), font_size=sp(11),

                                  radius=[dp(14)], elevation=0,

                                  md_bg_color=self._calendar_primary if selected else [0, 0, 0, 0],

                                  theme_text_color="Custom",

                                  text_color=self._calendar_on_primary if selected else self._calendar_text)

            button.bind(on_release=lambda _button, selected_date=value: self._select_date(selected_date))

            self._calendar_grid.add_widget(button)



    def _select_date(self, selected):

        self._selected = selected

        self._render_calendar()



    def _select_today(self, *_args):

        self._selected = date.today()

        self._display_year = self._selected.year

        self._display_month = self._selected.month

        self._render_calendar()



    def _save(self, *_args):

        self.dispatch("on_save", self._selected, [])

        self.dismiss()



    def on_save(self, _value, _date_range):

        pass





class NativeTooltip:

    """Contrato de tooltip sem dependência externa.



    A renderização do balão é deliberadamente adiada para a fase de polimento;

    manter estes métodos torna seguros os ciclos de limpeza e arrasto já

    usados pelos widgets da aplicação.

    """



    tooltip_text = StringProperty("")

    tooltip_display_delay = NumericProperty(.18)



    def display_tooltip(self, *_args):

        return None



    def animation_tooltip_show(self, *_args):

        return None



    def animation_tooltip_dismiss(self, *_args):

        return None





class NativeFloatingActionButton(NativeIconButton):

    def __init__(self, **kwargs):

        kwargs.setdefault("size_hint", (None, None))

        kwargs.setdefault("size", (dp(56), dp(56)))

        kwargs.setdefault("radius", [dp(28)])

        kwargs.setdefault("elevation", 4)

        super().__init__(**kwargs)





class NativeTopAppBar(NativeCard):

    """Barra superior leve com título e ações compatíveis com o contrato KV."""



    title = StringProperty("")

    specific_text_color = ListProperty([1, 1, 1, 1])

    left_action_items = ListProperty([])

    right_action_items = ListProperty([])



    def __init__(self, **kwargs):

        kwargs.setdefault("orientation", "horizontal")

        kwargs.setdefault("size_hint_y", None)

        kwargs.setdefault("height", dp(64))

        kwargs.setdefault("padding", [dp(12), dp(6), dp(8), dp(6)])

        super().__init__(**kwargs)

        self._left = NativeBoxLayout(size_hint_x=None, width=0, spacing=dp(2))

        self._title = NativeLabel(halign="left", valign="middle", text_size=(None, None), bold=True)

        self._right = NativeBoxLayout(size_hint_x=None, width=0, spacing=dp(2))

        self.add_widget(self._left)

        self.add_widget(self._title)

        self.add_widget(self._right)

        self.bind(title=self._sync_bar, specific_text_color=self._sync_bar,

                  left_action_items=self._sync_bar, right_action_items=self._sync_bar)

        self._sync_bar()



    def _make_actions(self, container, items):

        container.clear_widgets()

        for item in items or []:

            icon, callback = item[0], item[1] if len(item) > 1 else None

            button = NativeIconButton(icon=icon, size_hint=(None, None), size=(dp(42), dp(42)),

                                      md_bg_color=[0, 0, 0, 0], text_color=self.specific_text_color)

            if callable(callback):

                button.bind(on_release=callback)

            container.add_widget(button)

        container.width = len(container.children) * dp(44)



    def _sync_bar(self, *_args):

        self._title.text = self.title

        self._title.text_color = self.specific_text_color

        self._title.color = self.specific_text_color

        self._make_actions(self._left, self.left_action_items)

        self._make_actions(self._right, self.right_action_items)





class NativeTextField(TextInput):

    hint_text = StringProperty("")

    icon_left = StringProperty("")

    icon_right = StringProperty("")

    mode = StringProperty("rectangle")

    helper_text = StringProperty("")

    helper_text_mode = StringProperty("none")

    error = BooleanProperty(False)

    line_color_normal = ListProperty([0.45, 0.48, 0.55, 1])

    line_color_focus = ListProperty([0.08, 0.32, 0.62, 1])

    radius = ListProperty([dp(10)])

    md_bg_color = ListProperty([1, 1, 1, 1])

    # ``DropDown`` usa ``None`` para representar ausência de limite. Zero

    # faria o reposicionamento interno reduzir o menu a altura zero.

    max_height = ObjectProperty(None, allownone=True)



    def __init__(self, **kwargs):

        kwargs.setdefault("multiline", False)

        kwargs.setdefault("background_normal", "")

        kwargs.setdefault("background_active", "")

        kwargs.setdefault("background_color", [0, 0, 0, 0])

        super().__init__(**kwargs)

        app = App.get_running_app()

        tokens = getattr(app, "theme_tokens", {}) if app else {}

        self.md_bg_color = list(tokens.get("surface_alt", tokens.get("card", [1, 1, 1, 1])))

        self.hint_text_color = list(tokens.get("text_muted", [0.45, 0.48, 0.55, 1]))

        self.foreground_color = list(tokens.get("text_primary", [0.12, 0.15, 0.20, 1]))

        self.cursor_color = list(tokens.get("focus", tokens.get("primary", [0.08, 0.32, 0.62, 1])))

        self.line_color_normal = list(tokens.get("outline", self.line_color_normal))

        self.line_color_focus = list(tokens.get("focus", self.line_color_focus))

        # O TextInput puro deixa um retângulo branco. Esta superfície devolve

        # o campo outlined e o feedback de foco que o MDTextField oferecia.

        with self.canvas.before:

            self._field_bg_color = Color(rgba=self.md_bg_color)

            self._field_bg = RoundedRectangle(pos=self.pos, size=self.size, radius=_normalize_radius(self.radius))

            self._field_line_color = Color(rgba=self.line_color_normal)

            self._field_line = Line(width=1, rounded_rectangle=(self.x, self.y, self.width, self.height, dp(10)))

        self._hint_label = NativeLabel(

            text=self.hint_text,

            font_style="Caption",

            theme_text_color="Custom",

            text_color=self.hint_text_color,

            size_hint=(None, None),

            halign="left",

            valign="middle",

        )

        self._left_icon = NativeIcon(size_hint=(None, None), size=(dp(22), dp(22)),

                                     halign="center", valign="middle", opacity=0)

        self._right_icon = NativeIcon(size_hint=(None, None), size=(dp(22), dp(22)),

                                      halign="center", valign="middle", opacity=0)

        self.add_widget(self._hint_label)

        self.add_widget(self._left_icon)

        self.add_widget(self._right_icon)

        self.bind(

            pos=self._sync_field_surface, size=self._sync_field_surface, focus=self._sync_field_surface,

            disabled=self._sync_field_surface, error=self._sync_field_surface, radius=self._sync_field_surface,

            md_bg_color=self._sync_field_surface, line_color_normal=self._sync_field_surface,

            line_color_focus=self._sync_field_surface, hint_text=self._sync_field_hint,

            hint_text_color=self._sync_field_hint, text=self._sync_field_hint,

            padding=self._sync_field_hint, icon_left=self._sync_field_adornments,

            icon_right=self._sync_field_adornments,

        )

        self._sync_field_surface()

        self._sync_field_hint()

        self._sync_field_adornments()



    def _sync_field_adornments(self, *_args):

        """Exibe os ícones laterais aceites pelo antigo MDTextField."""

        color = self.line_color_focus if self.focus else self.hint_text_color

        left = getattr(self, "_left_icon", None)

        right = getattr(self, "_right_icon", None)

        if left is not None:

            left.icon = self.icon_left

            left.text_color = color

            left.opacity = 1 if self.icon_left else 0

            left.pos = (self.x + dp(10), self.center_y - dp(11))

        if right is not None:

            right.icon = self.icon_right

            right.text_color = color

            right.opacity = 1 if self.icon_right else 0

            right.pos = (self.right - dp(32), self.center_y - dp(11))



    def _sync_field_surface(self, *_args):

        app = App.get_running_app()

        tokens = getattr(app, "theme_tokens", {}) if app else {}

        base = list(self.md_bg_color or tokens.get("card", [1, 1, 1, 1]))

        if self.disabled:

            base = [*base[:3], 0.46]

        border = self.line_color_focus if self.focus else self.line_color_normal

        if self.error:

            border = tokens.get("danger", [0.82, 0.24, 0.28, 1])

        self._field_bg_color.rgba = base

        self._field_bg.pos = self.pos

        self._field_bg.size = self.size

        self._field_bg.radius = _normalize_radius(self.radius)

        self._field_line_color.rgba = border

        self._field_line.width = dp(1.6) if self.focus else dp(1)

        self._field_line.rounded_rectangle = (

            self.x + dp(.5), self.y + dp(.5), max(0, self.width - dp(1)),

            max(0, self.height - dp(1)), _normalize_radius(self.radius)[0],

        )

        self._sync_field_adornments()



    def _sync_field_hint(self, *_args):

        """Equivalente leve ao hint interno do MDTextField para Kivy puro."""

        label = getattr(self, "_hint_label", None)

        if label is None:

            return

        left = float(self.padding[0] if self.padding else dp(10)) + (dp(28) if self.icon_left else 0)

        right = float(self.padding[2] if len(self.padding or []) > 2 else dp(10)) + (dp(28) if self.icon_right else 0)

        label.text = self.hint_text

        label.text_color = self.hint_text_color

        label.width = max(dp(12), self.width - left - right)

        label.height = dp(20)

        label.pos = (self.x + left, self.center_y - label.height / 2)

        label.opacity = 0 if self.text else (0.52 if self.disabled else 1)

        self._sync_field_adornments()





class NativeDialog(ModalView):

    """Diálogo modal Kivy com título, corpo e ações sem widgets externos."""



    title = StringProperty("")

    text = StringProperty("")

    type = StringProperty("alert")

    content_cls = ObjectProperty(None, allownone=True)

    buttons = ListProperty([])

    md_bg_color = ListProperty([1, 1, 1, 1])

    radius = ListProperty([dp(16)])



    def __init__(self, **kwargs):

        kwargs.setdefault("background_color", [0, 0, 0, .45])

        kwargs.setdefault("size_hint", (.88, None))

        # ``size=(largura, altura)`` era comum no MDDialog. Não injete uma

        # altura padrão depois desse argumento, pois isso reduz o modal a

        # 260dp e faz o conteúdo transbordar para fora do cartão.

        if "height" not in kwargs and "size" not in kwargs:

            kwargs["height"] = dp(260)

        if "md_bg_color" not in kwargs:

            app = App.get_running_app()

            tokens = getattr(app, "theme_tokens", {}) if app else {}

            kwargs["md_bg_color"] = list(tokens.get("card", [1, 1, 1, 1]))

        super().__init__(**kwargs)

        self._card = NativeCard(orientation="vertical", padding=[dp(20), dp(16)],

                                spacing=dp(12), radius=self.radius, md_bg_color=self.md_bg_color)

        self._heading = NativeLabel(font_style="H6", bold=True, size_hint_y=None, height=dp(30))

        self._body = NativeLabel(theme_text_color="Secondary", text_size=(None, None),

                                 size_hint_y=None, height=0)

        self._content = NativeBoxLayout(orientation="vertical", size_hint_y=1)

        self._actions = NativeBoxLayout(orientation="horizontal", size_hint_y=None,

                                        height=dp(44), spacing=dp(8))

        self._card.add_widget(self._heading)

        self._card.add_widget(self._body)

        self._card.add_widget(self._content)

        self._card.add_widget(self._actions)

        self.add_widget(self._card)

        self.bind(title=self._sync_dialog, text=self._sync_dialog, content_cls=self._sync_dialog,

                  buttons=self._sync_dialog, md_bg_color=self._sync_dialog, radius=self._sync_dialog)

        self._sync_dialog()



    def _sync_dialog(self, *_args):

        app = App.get_running_app()

        tokens = getattr(app, "theme_tokens", {}) if app else {}

        self._heading.text = self.title

        # NativeLabel parte de uma cor escura. Em diálogos dark isso deixava

        # títulos praticamente invisíveis, ao contrário do MDDialog original.

        self._heading.theme_text_color = "Custom"

        self._heading.text_color = list(tokens.get("text_primary", [0.12, 0.15, 0.20, 1]))

        self._body.text = self.text

        self._body.theme_text_color = "Custom"

        self._body.text_color = list(tokens.get("text_secondary", [0.35, 0.40, 0.50, 1]))

        self._body.text_size = (self.width - dp(40), None)

        self._body.texture_update()

        self._body.height = self._body.texture_size[1] if self.text else 0

        self._card.md_bg_color = self.md_bg_color

        self._card.radius = self.radius

        self._content.clear_widgets()

        if self.content_cls is not None:

            self._content.add_widget(self.content_cls)

        self._actions.clear_widgets()

        for button in self.buttons or []:

            self._actions.add_widget(button)

        self._actions.opacity = 1 if self.buttons else 0

        self._actions.height = dp(44) if self.buttons else 0



    def update_height(self, *_args):

        """Compatibilidade com o ajuste dinâmico de altura do MDDialog."""

        content = self.content_cls

        content_height = float(getattr(content, "height", 0) or 0)

        body_height = float(getattr(self._body, "height", 0) or 0)

        actions_height = dp(44) if self.buttons else 0

        required = dp(32 + 30 + 36) + content_height + body_height + actions_height

        self.height = min(max(dp(180), required), max(dp(180), Window.height - dp(40)))



    def update_width(self, *_args):

        """Mantém a API do MDDialog para handlers de redimensionamento antigos."""

        self._sync_dialog()





class NativeDropdownMenu(DropDown):

    """Menu ancorado com a API de itens utilizada nas telas atuais.



    A lista é materializada somente quando ``items`` muda. Cada seleção fecha

    o menu antes de despachar o callback, como fazia o menu Material.

    """



    items = ListProperty([])

    caller = ObjectProperty(None, allownone=True)

    width_mult = NumericProperty(4)

    # ``DropDown`` interpreta zero como uma altura válida. Para os menus que

    # não definem limite, o valor correto é ``None``; caso contrário o menu é

    # posicionado com altura zero e parece não abrir.

    max_height = NumericProperty(None, allownone=True)

    position = StringProperty("auto")

    hor_growth = StringProperty("auto")

    ver_growth = StringProperty("auto")

    item_height = NumericProperty(dp(44))

    md_bg_color = ListProperty([1, 1, 1, 1])

    radius = ListProperty([dp(8)])

    elevation = NumericProperty(4)



    def __init__(self, **kwargs):

        has_max_height = "max_height" in kwargs

        has_background_color = "md_bg_color" in kwargs

        super().__init__(**kwargs)

        if not has_max_height:

            self.max_height = None

        self._uses_theme_background = not has_background_color

        self.auto_width = False

        self._item_widgets = []

        # DropDown puro só posiciona o seu container: não desenha a

        # superfície Material que os menus tinham antes. O canvas abaixo

        # restaura esse fundo sem adicionar um widget intermediário.

        with self.canvas.before:

            self._surface_color = Color(*self.md_bg_color)

            self._surface = RoundedRectangle(

                pos=self.pos, size=self.size, radius=_normalize_radius(self.radius)

            )

            self._surface_border_color = Color(0, 0, 0, 0)

            self._surface_border = Line(width=1)

        self.bind(

            pos=self._sync_surface,

            size=self._sync_surface,

            md_bg_color=self._sync_surface,

            radius=self._sync_surface,

        )

        self.bind(items=self._rebuild_items, max_height=self._rebuild_items,

                  item_height=self._rebuild_items)

        self._rebuild_items()



    def _sync_surface(self, *_args):

        app = App.get_running_app()

        tokens = getattr(app, "theme_tokens", {}) if app else {}

        self._surface_color.rgba = self.md_bg_color

        self._surface.pos = self.pos

        self._surface.size = self.size

        self._surface.radius = _normalize_radius(self.radius)

        self._surface_border_color.rgba = tokens.get("outline", [0.35, 0.40, 0.50, 1])

        self._surface_border.rounded_rectangle = (

            self.x, self.y, self.width, self.height, _normalize_radius(self.radius)[0]

        )



    def _sync_theme_background(self):

        if not self._uses_theme_background:

            return

        app = App.get_running_app()

        tokens = getattr(app, "theme_tokens", {}) if app else {}

        # ``card`` é a mesma superfície usada pelos cards e dialogs nativos,

        # portanto o dropdown acompanha os temas claro e escuro já existentes.

        self.md_bg_color = list(tokens.get("card", [1, 1, 1, 1]))



    def _rebuild_items(self, *_args):

        self.clear_widgets()

        self._item_widgets = []

        app = App.get_running_app()

        tokens = getattr(app, "theme_tokens", {}) if app else {}

        total_height = 0

        for item in self.items or []:

            if not isinstance(item, dict):

                item = {"text": str(item)}

            text = str(item.get("text", ""))

            callback = item.get("on_release")

            height = float(item.get("height") or self.item_height)

            is_selected = bool(item.get("selected", False))

            button = NativeFlatButton(

                text=text,

                size_hint_y=None,

                height=height,

                halign="left",

                valign="middle",

                padding=[dp(16), 0],

                text_size=(None, None),

                radius=[dp(8)],

                md_bg_color=(

                    [*tokens.get("primary", [0.08, 0.32, 0.62, 1])[:3], 0.14]

                    if is_selected else [0, 0, 0, 0]

                ),

                text_color=tokens.get(

                    "primary" if is_selected else "text_primary",

                    [0.08, 0.32, 0.62, 1] if is_selected else [0.12, 0.15, 0.20, 1],

                ),

            )

            button.bind(

                size=lambda instance, _value: setattr(

                    instance, "text_size", (max(0, instance.width - dp(32)), instance.height)

                )

            )

            if callable(callback):

                button.bind(on_release=lambda _button, action=callback: self._select_item(action))

            self.add_widget(button)

            self._item_widgets.append(button)

            total_height += height

        self.container.do_layout()

        self.height = min(float(self.max_height), total_height) if self.max_height else total_height



    def _select_item(self, callback):

        self.dismiss()

        callback()



    def open(self, caller=None):

        if caller is not None:

            self.caller = caller

        if self.caller is None:

            return

        self._sync_theme_background()

        self.width = dp(56) * self.width_mult

        self._rebuild_items()

        if self.parent is not None:

            self.dismiss()

        super().open(self.caller)





class NativeSnackbar(NativeCard):

    """Notificação temporária posicionada diretamente sobre a janela Kivy."""



    duration = NumericProperty(3)



    def __init__(self, *children, **kwargs):

        kwargs.setdefault("orientation", "horizontal")

        kwargs.setdefault("size_hint_y", None)

        kwargs.setdefault("height", dp(52))

        kwargs.setdefault("padding", [dp(16), dp(8)])

        kwargs.setdefault("radius", [dp(10)])

        kwargs.setdefault("md_bg_color", [.12, .15, .20, .96])

        super().__init__(**kwargs)

        for child in children:

            self.add_widget(child)

        self._dismiss_event = None



    def open(self):

        if self.parent is None:

            Window.add_widget(self)

        if self.duration > 0:

            self._dismiss_event = Clock.schedule_once(lambda _dt: self.dismiss(), self.duration)

        return self



    def dismiss(self, *_args):

        if self._dismiss_event:

            self._dismiss_event.cancel()

            self._dismiss_event = None

        if self.parent is not None:

            self.parent.remove_widget(self)





class NativeSeparator(Widget):

    color = ListProperty([0, 0, 0, .12])



    def __init__(self, **kwargs):

        kwargs.setdefault("size_hint_y", None)

        kwargs.setdefault("height", dp(1))

        super().__init__(**kwargs)

        with self.canvas:

            self._color = Color(rgba=self.color)

            self._line = RoundedRectangle(pos=self.pos, size=self.size)

        self.bind(pos=self._sync, size=self._sync, color=self._sync)



    def _sync(self, *_args):

        self._color.rgba = self.color

        self._line.pos = self.pos

        self._line.size = self.size





# As regras KV são carregadas por nome através do Factory. O registo explícito

# evita dependência de imports implícitos ou de classes KivyMD.

for _native_widget in (

    NativeBoxLayout, NativeGridLayout, NativeListLayout, NativeScrollView, NativeScreen,

    NativeLabel, NativeIcon, NativeSpinner, NativeCard, NativeActionCard, NativeButton, NativeFlatButton,

    NativeListItem, NativeProgressBar, NativeCheckbox,

    NativeIconButton, NativeIconTextButton, NativeDropdownItem, NativeSwitch, NativeDatePicker,

    NativeFloatingActionButton, NativeTooltip,

    NativeTopAppBar, NativeTextField, NativeDialog,

    NativeDropdownMenu, NativeSnackbar, NativeSeparator,

):

    if _native_widget.__name__ not in Factory.classes:

        Factory.register(_native_widget.__name__, cls=_native_widget)



# Compatibilidade de regras KV durante a conversão por tela. Estes nomes são

# resolvidos para widgets Kivy locais; não importam KivyMD nem o usam em

# runtime. Os fontes são migrados gradualmente para os nomes `Native*`.

for _legacy_name, _native_widget in {

    "MDScreen": NativeScreen,

    "MDBoxLayout": NativeBoxLayout,

    "MDGridLayout": NativeGridLayout,

    "MDScrollView": NativeScrollView,

    "MDLabel": NativeLabel,

    "MDIcon": NativeIcon,

    "MDCard": NativeCard,

    "MDTextField": NativeTextField,

    "MDFlatButton": NativeFlatButton,

    "MDRaisedButton": NativeButton,

    "MDIconButton": NativeIconButton,

    "MDFloatingActionButton": NativeFloatingActionButton,

    "MDSpinner": NativeSpinner,

    "MDDropDownItem": NativeDropdownItem,

    "OneLineListItem": NativeListItem,

    "TwoLineListItem": NativeListItem,

    "MDList": NativeListLayout,

    "MDProgressBar": NativeProgressBar,

    "MDCheckbox": NativeCheckbox,

    "MDSwitch": NativeSwitch,

    "MDDatePicker": NativeDatePicker,

    "MDRectangleFlatIconButton": NativeIconTextButton,

    "MDFillRoundFlatIconButton": NativeIconTextButton,

    "MDTopAppBar": NativeTopAppBar,

    "MDDialog": NativeDialog,

    "MDDropdownMenu": NativeDropdownMenu,

    "MDSnackbar": NativeSnackbar,

    "MDSeparator": NativeSeparator,

}.items():

    if _legacy_name not in Factory.classes:

        Factory.register(_legacy_name, cls=_native_widget)
