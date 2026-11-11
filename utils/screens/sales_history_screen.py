"""
SalesHistoryScreen — v4

Regras de comportamento
───────────────────────
• Ao entrar na tela, NUNCA carrega dados automaticamente.
  Mostra apenas os filtros. O utilizador escolhe o filtro e carrega.

• RecycleView substitui a criação manual de widgets por linha.

• Botão "ELIMINAR HISTÓRICO" na AppBar com confirmação em 2 passos.

• _show_loading_state nunca bloqueia a UI thread.

• Cache de cores renovado uma vez por lote, nunca por linha.

• Todos os filtros funcionam sobre o conjunto já carregado sem nova
  consulta ao DB enquanto o cache for válido.

• v4: popup "Produtos da venda" redesenhado (ModalView próprio).
"""

from collections import deque
from datetime import datetime, timedelta
from functools import lru_cache
from threading import Thread
from time import perf_counter

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import BooleanProperty, StringProperty, ListProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from ui.components.native_widgets import (
    NativeBoxLayout as MDBoxLayout, NativeButton as MDRaisedButton,
    NativeDialog as MDDialog, NativeFlatButton as MDFlatButton,
    NativeLabel as MDLabel, NativeScreen as MDScreen,
    NativeTextField as MDTextField,
)

from database.provider import get_db
from utils.business.sales_transactions import (
    REFUND_WINDOW_MINUTES,
    group_sale_records,
    refund_window_status,
    transaction_key,
)


# ─────────────────────────────────────────────────────────────────────────────
#  KV
# ─────────────────────────────────────────────────────────────────────────────
Builder.load_string("""
#:import dp kivy.metrics.dp

<SaleRowView>:
    orientation: "horizontal"
    size_hint_y: None
    height: dp(56)
    padding: [dp(12), dp(5), dp(10), dp(5)]
    spacing: dp(6)
    md_bg_color: self.row_bg
    canvas.after:
        Color:
            rgba: 1, 1, 1, 0.06
        Rectangle:
            pos: self.x + dp(12), self.y
            size: self.width - dp(24), dp(1)

    MDLabel:
        text: root.col_date
        size_hint_x: root.w_date
        halign: "left"
        valign: "middle"
        font_size: dp(11)
        theme_text_color: "Custom"
        text_color: root.col_text_sec
        text_size: self.size

    MDBoxLayout:
        orientation: "vertical"
        size_hint_x: root.w_prod
        padding: [0, 0, dp(4), 0]
        spacing: dp(2)

        MDLabel:
            text: root.col_product
            halign: "left"
            font_size: dp(13)
            bold: True
            shorten: True
            shorten_from: "right"
            theme_text_color: "Custom"
            text_color: root.col_text_pri
            size_hint_y: None
            height: dp(20)

        MDLabel:
            text: root.col_meta
            halign: "left"
            font_size: dp(10)
            shorten: True
            shorten_from: "right"
            theme_text_color: "Custom"
            text_color: root.col_text_sec
            size_hint_y: None
            height: dp(16)

    MDLabel:
        text: root.col_qty
        size_hint_x: root.w_qty
        halign: "center"
        valign: "middle"
        font_size: dp(13)
        bold: True
        theme_text_color: "Custom"
        text_color: root.col_primary
        text_size: self.size

    MDLabel:
        id: price_lbl
        text: root.col_price
        size_hint_x: root.w_price
        halign: "center"
        valign: "middle"
        font_size: dp(12)
        theme_text_color: "Custom"
        text_color: root.col_text_sec
        opacity: root.show_price
        text_size: self.size

    MDLabel:
        text: root.col_total
        size_hint_x: root.w_total
        halign: "right"
        valign: "middle"
        font_size: dp(13)
        bold: True
        theme_text_color: "Custom"
        text_color: root.col_success
        text_size: self.size

    AnchorLayout:
        size_hint_x: root.w_action
        anchor_x: "center"
        anchor_y: "center"

        MDRaisedButton:
            text: root.btn_label
            size_hint: None, None
            size: dp(58), dp(28)
            md_bg_color: root.btn_color
            theme_text_color: "Custom"
            text_color: [1, 1, 1, 1]
            font_size: dp(11)
            elevation: 0
            radius: [dp(8)]
            disabled: root.btn_disabled
            on_release: root.on_action()


<SaleRecycleView>:
    viewclass: "SaleRowView"
    scroll_type: ["bars", "content"]
    bar_width: dp(6)
    bar_color: 0.20, 0.55, 0.90, 0.55
    bar_inactive_color: 0.30, 0.34, 0.40, 0.4

    RecycleBoxLayout:
        orientation: "vertical"
        default_size: None, dp(58)
        default_size_hint: 1, None
        size_hint_y: None
        height: self.minimum_height


<SalesHistoryScreen>:
    name: "sales_history"
    md_bg_color: app.theme_tokens['surface']

    MDBoxLayout:
        orientation: "vertical"

        # ── AppBar ────────────────────────────────────────────────────────────
        MDTopAppBar:
            title: "Histórico de Vendas"
            md_bg_color: app.theme_tokens['primary']
            specific_text_color: app.theme_tokens['on_primary']
            elevation: 4
            left_action_items:
                [["arrow-left", lambda x: root.go_back()]]
            right_action_items:
                [ \
                  ["delete-sweep-outline", lambda x: root.confirm_delete_history()], \
                  ["file-download-outline", lambda x: root.export_sales()], \
                  ["refresh", lambda x: root._hard_refresh()] \
                ]

        MDBoxLayout:
            orientation: "vertical"
            padding: dp(10)
            spacing: dp(8)

            # ── Painel de filtros ─────────────────────────────────────────────
            MDCard:
                id: filters_card
                orientation: "vertical"
                size_hint_y: None
                height: dp(186)
                padding: [dp(10), dp(8)]
                spacing: dp(6)
                elevation: 0
                radius: [dp(12)]
                md_bg_color: app.theme_tokens['card']
                canvas.before:
                    Color:
                        rgba: app.theme_tokens.get('divider', [0.25, 0.28, 0.34, 0.55])
                    Line:
                        width: 1
                        rounded_rectangle: self.x, self.y, self.width, self.height, dp(12)

                # Linha pesquisa
                MDBoxLayout:
                    size_hint_y: None
                    height: dp(40)
                    spacing: dp(6)

                    MDTextField:
                        id: search_input
                        hint_text: "Produto, vendedor ou ID…"
                        mode: "rectangle"
                        size_hint_x: 1
                        font_size: dp(13)
                        icon_right: "magnify"
                        line_color_focus: app.theme_tokens['primary']
                        on_text_validate: root.apply_search_filter()
                        on_text: root._on_search_text(self.text)

                    MDRaisedButton:
                        text: "BUSCAR"
                        size_hint: None, None
                        size: dp(80), dp(34)
                        font_size: dp(12)
                        md_bg_color: app.theme_tokens['primary']
                        elevation: 0
                        radius: [dp(8)]
                        pos_hint: {"center_y": 0.5}
                        on_release: root.apply_search_filter()

                    MDFlatButton:
                        text: "LIMPAR"
                        size_hint: None, None
                        size: dp(70), dp(34)
                        font_size: dp(12)
                        theme_text_color: "Custom"
                        text_color: app.theme_tokens['danger']
                        pos_hint: {"center_y": 0.5}
                        on_release: root.clear_search_filter()

                # Linha datas
                MDBoxLayout:
                    size_hint_y: None
                    height: dp(40)
                    spacing: dp(6)

                    MDTextField:
                        id: start_date
                        hint_text: "Início  dd/mm/aaaa"
                        mode: "rectangle"
                        size_hint_x: 1
                        font_size: dp(13)
                        icon_right: "calendar"
                        line_color_focus: app.theme_tokens['primary']
                        on_text_validate: root.apply_date_filter()

                    MDTextField:
                        id: end_date
                        hint_text: "Fim  dd/mm/aaaa"
                        mode: "rectangle"
                        size_hint_x: 1
                        font_size: dp(13)
                        icon_right: "calendar"
                        line_color_focus: app.theme_tokens['primary']
                        on_text_validate: root.apply_date_filter()

                    MDRaisedButton:
                        text: "APLICAR"
                        size_hint: None, None
                        size: dp(100), dp(34)
                        font_size: dp(12)
                        md_bg_color: app.theme_tokens['primary']
                        elevation: 0
                        radius: [dp(8)]
                        pos_hint: {"center_y": 0.5}
                        on_release: root.apply_date_filter()

                # Atalhos rápidos
                MDBoxLayout:
                    size_hint_y: None
                    height: dp(34)
                    spacing: dp(5)

                    MDRaisedButton:
                        id: btn_today
                        text: "HOJE"
                        font_size: dp(11)
                        md_bg_color: app.theme_tokens['success']
                        elevation: 0
                        radius: [dp(8)]
                        on_release: root.filter_today()

                    MDRaisedButton:
                        id: btn_week
                        text: "SEMANA"
                        font_size: dp(11)
                        md_bg_color: app.theme_tokens['info']
                        elevation: 0
                        radius: [dp(8)]
                        on_release: root.filter_this_week()

                    MDRaisedButton:
                        id: btn_month
                        text: "MÊS"
                        font_size: dp(11)
                        md_bg_color: app.theme_tokens['info']
                        elevation: 0
                        radius: [dp(8)]
                        on_release: root.filter_this_month()

                    MDRaisedButton:
                        id: btn_year
                        text: "ANO"
                        font_size: dp(11)
                        md_bg_color: app.theme_tokens['info']
                        elevation: 0
                        radius: [dp(8)]
                        on_release: root.filter_this_year()

                    MDRaisedButton:
                        id: btn_promo
                        text: "PROMO"
                        font_size: dp(11)
                        md_bg_color: app.theme_tokens['warning']
                        elevation: 0
                        radius: [dp(8)]
                        on_release: root.filter_promotional_sales()

                    MDFlatButton:
                        id: btn_all
                        text: "TODOS"
                        font_size: dp(11)
                        theme_text_color: "Custom"
                        text_color: app.theme_tokens['danger']
                        on_release: root.load_all_sales(prefer_local_cache=True)

                # Acção destrutiva
                MDBoxLayout:
                    size_hint_y: None
                    height: dp(34)
                    spacing: dp(8)
                    padding: [0, dp(2), 0, 0]

                    Widget:
                        size_hint_x: 1

                    MDRaisedButton:
                        id: btn_delete_history
                        text: "ELIMINAR HISTÓRICO"
                        size_hint: None, None
                        size: dp(170), dp(32)
                        font_size: dp(11)
                        md_bg_color: app.theme_tokens['danger']
                        elevation: 0
                        radius: [dp(8)]
                        on_release: root.confirm_delete_history()

            # ── Resumo ────────────────────────────────────────────────────────
            MDCard:
                orientation: "horizontal"
                size_hint_y: None
                height: dp(52)
                padding: [dp(12), dp(4)]
                spacing: dp(0)
                elevation: 0
                radius: [dp(12)]
                md_bg_color: app.theme_tokens['card']
                canvas.before:
                    Color:
                        rgba: app.theme_tokens.get('divider', [0.25, 0.28, 0.34, 0.55])
                    Line:
                        width: 1
                        rounded_rectangle: self.x, self.y, self.width, self.height, dp(12)

                MDBoxLayout:
                    orientation: "vertical"
                    size_hint_x: 0.33

                    MDLabel:
                        text: "Vendas"
                        font_style: "Caption"
                        theme_text_color: "Secondary"
                        halign: "center"

                    MDLabel:
                        id: total_sales_label
                        text: "—"
                        font_size: dp(18)
                        bold: True
                        halign: "center"
                        theme_text_color: "Primary"

                MDLabel:
                    text: "|"
                    size_hint_x: None
                    width: dp(14)
                    halign: "center"
                    theme_text_color: "Hint"

                MDBoxLayout:
                    orientation: "vertical"
                    size_hint_x: 0.34

                    MDLabel:
                        text: "Receita Líquida"
                        font_style: "Caption"
                        theme_text_color: "Secondary"
                        halign: "center"

                    MDLabel:
                        id: total_revenue_label
                        text: "—"
                        font_size: dp(18)
                        bold: True
                        halign: "center"
                        theme_text_color: "Custom"
                        text_color: app.theme_tokens['success']

                MDLabel:
                    text: "|"
                    size_hint_x: None
                    width: dp(14)
                    halign: "center"
                    theme_text_color: "Hint"

                MDBoxLayout:
                    orientation: "vertical"
                    size_hint_x: 0.33

                    MDLabel:
                        text: "Estornado"
                        font_style: "Caption"
                        theme_text_color: "Secondary"
                        halign: "center"

                    MDLabel:
                        id: avg_sale_label
                        text: "—"
                        font_size: dp(18)
                        bold: True
                        halign: "center"
                        theme_text_color: "Custom"
                        text_color: app.theme_tokens['info']

            # ── Tabela ────────────────────────────────────────────────────────
            MDCard:
                orientation: "vertical"
                padding: dp(0)
                spacing: dp(0)
                elevation: 0
                radius: [dp(12)]
                md_bg_color: app.theme_tokens['card']
                canvas.before:
                    Color:
                        rgba: app.theme_tokens.get('divider', [0.25, 0.28, 0.34, 0.55])
                    Line:
                        width: 1
                        rounded_rectangle: self.x, self.y, self.width, self.height, dp(12)

                # Cabeçalho
                MDBoxLayout:
                    size_hint_y: None
                    height: dp(36)
                    padding: [dp(12), dp(0), dp(10), dp(0)]
                    spacing: dp(6)
                    md_bg_color: app.theme_tokens['card_alt']
                    radius: [dp(12), dp(12), 0, 0]

                    MDLabel:
                        id: h_date
                        text: "Data/Hora"
                        bold: True
                        size_hint_x: 0.15
                        halign: "left"
                        valign: "middle"
                        font_size: dp(11)
                        theme_text_color: "Secondary"
                        text_size: self.size

                    MDLabel:
                        id: h_prod
                        text: "Produto"
                        bold: True
                        size_hint_x: 0.40
                        halign: "left"
                        valign: "middle"
                        font_size: dp(11)
                        theme_text_color: "Secondary"
                        text_size: self.size

                    MDLabel:
                        id: h_qty
                        text: "Qtd"
                        bold: True
                        size_hint_x: 0.10
                        halign: "center"
                        valign: "middle"
                        font_size: dp(11)
                        theme_text_color: "Secondary"
                        text_size: self.size

                    MDLabel:
                        id: h_price
                        text: "Itens"
                        bold: True
                        size_hint_x: 0.10
                        halign: "center"
                        valign: "middle"
                        font_size: dp(11)
                        theme_text_color: "Secondary"
                        text_size: self.size

                    MDLabel:
                        id: h_total
                        text: "Total"
                        bold: True
                        size_hint_x: 0.13
                        halign: "right"
                        valign: "middle"
                        font_size: dp(11)
                        theme_text_color: "Secondary"
                        text_size: self.size

                    MDLabel:
                        id: h_ver
                        text: ""
                        size_hint_x: 0.12
                        font_size: dp(11)

                # RecycleView — renderiza apenas as linhas visíveis
                SaleRecycleView:
                    id: rv
                    data: []

                # Estado vazio / instrução inicial
                MDBoxLayout:
                    id: empty_state
                    orientation: "vertical"
                    padding: [dp(24), dp(28)]
                    spacing: dp(8)
                    size_hint_y: None
                    height: dp(140)
                    opacity: 1

                    MDLabel:
                        id: empty_title
                        text: "Selecione um filtro para ver o histórico"
                        halign: "center"
                        font_size: dp(15)
                        bold: True
                        theme_text_color: "Custom"
                        text_color: app.theme_tokens.get('text_primary', [0.9, 0.9, 0.92, 1])
                        size_hint_y: None
                        height: dp(28)

                    MDLabel:
                        id: empty_msg
                        text: "Use Hoje, Semana, Mês, Ano, Promo ou defina um intervalo de datas."
                        halign: "center"
                        font_size: dp(12)
                        theme_text_color: "Custom"
                        text_color: app.theme_tokens.get('text_secondary', [0.6, 0.65, 0.7, 1])
                        size_hint_y: None
                        height: dp(40)

""")


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers de UI do popup "Produtos da venda"
# ─────────────────────────────────────────────────────────────────────────────
def _popup_label(text, size=12, color=(1, 1, 1, 1), bold=False,
                 halign="left", **kwargs):
    lbl = Label(
        text=text,
        font_size=dp(size),
        color=list(color),
        bold=bold,
        halign=halign,
        valign="middle",
        markup=True,
        **kwargs,
    )
    lbl.bind(size=lambda w, s: setattr(w, "text_size", s))
    return lbl


def _popup_paint(widget, color, radius=12):
    """Pinta um fundo arredondado atrás do widget."""
    with widget.canvas.before:
        Color(*color)
        rect = RoundedRectangle(pos=widget.pos, size=widget.size, radius=[dp(radius)])
    widget.bind(
        pos=lambda w, v: setattr(rect, "pos", v),
        size=lambda w, v: setattr(rect, "size", v),
    )
    return rect


def _popup_button(text, color, width=112, height=38, enabled=True, font_size=11):
    btn = Button(
        text=text,
        size_hint=(None, None),
        size=(dp(width), dp(height)),
        font_size=dp(font_size),
        bold=True,
        background_normal="",
        background_down="",
        background_disabled_normal="",
        background_color=[0, 0, 0, 0],
        color=[1, 1, 1, 1],
        disabled_color=[1, 1, 1, 0.55],
        disabled=not enabled,
    )
    _popup_paint(btn, color, radius=8)
    return btn


def _popup_input(text="", hint="", height=44, **kwargs):
    ti = TextInput(
        text=text,
        hint_text=hint,
        multiline=False,
        size_hint_y=None,
        height=dp(height),
        font_size=dp(14),
        background_normal="",
        background_active="",
        background_color=[0, 0, 0, 0],
        foreground_color=[0.95, 0.96, 0.98, 1],
        hint_text_color=[0.55, 0.60, 0.68, 1],
        cursor_color=[0.95, 0.62, 0.12, 1],
        padding=[dp(12), (dp(height) - dp(14) * 1.25) / 2, dp(12), 0],
        **kwargs,
    )
    _popup_paint(ti, (0.18, 0.21, 0.27, 1), radius=10)
    return ti




# ─────────────────────────────────────────────────────────────────────────────
#  RecycleView e view-item reutilizável
# ─────────────────────────────────────────────────────────────────────────────
class SaleRecycleView(RecycleView):
    pass


class SaleRowView(RecycleDataViewBehavior, MDBoxLayout):
    """
    View reciclável de uma linha da tabela.
    Todos os valores são KivyProperties — o RecycleView apenas atualiza
    as propriedades ao rolar, sem criar/destruir widgets.
    """
    index       = 0
    row_bg      = ListProperty([1, 1, 1, 1])
    col_date    = StringProperty("")
    col_product = StringProperty("")
    col_meta    = StringProperty("")
    col_qty     = StringProperty("")
    col_price   = StringProperty("")
    col_total   = StringProperty("")
    btn_label   = StringProperty("OK")
    btn_color   = ListProperty([0.65, 0.65, 0.65, 1])
    btn_disabled= BooleanProperty(True)
    show_price  = 1   # float: opacity do label Preço

    col_text_pri = ListProperty([0.15, 0.20, 0.30, 1])
    col_text_sec = ListProperty([0.35, 0.40, 0.50, 1])
    col_primary  = ListProperty([0.10, 0.35, 0.65, 1])
    col_success  = ListProperty([0.20, 0.65, 0.30, 1])

    w_date   = 0.15
    w_prod   = 0.40
    w_qty    = 0.10
    w_price  = 0.10
    w_total  = 0.13
    w_action = 0.12

    _sale_data   = None
    _on_action_cb = None

    def refresh_view_attrs(self, rv, index, data):
        self.index = index
        self._sale_data    = data.get("sale_data")
        self._on_action_cb = data.get("action_callback")
        self.row_bg        = data.get("row_bg",      [1, 1, 1, 1])
        self.col_date      = data.get("col_date",    "")
        self.col_product   = data.get("col_product", "")
        self.col_meta      = data.get("col_meta",    "")
        self.col_qty       = data.get("col_qty",     "")
        self.col_price     = data.get("col_price",   "")
        self.col_total     = data.get("col_total",   "")
        self.btn_label     = data.get("btn_label",   "OK")
        self.btn_color     = data.get("btn_color",   [0.65, 0.65, 0.65, 1])
        self.btn_disabled  = data.get("btn_disabled", True)
        self.show_price    = data.get("show_price",  1)
        self.col_text_pri  = data.get("col_text_pri", [0.15, 0.20, 0.30, 1])
        self.col_text_sec  = data.get("col_text_sec", [0.35, 0.40, 0.50, 1])
        self.col_primary   = data.get("col_primary",  [0.10, 0.35, 0.65, 1])
        self.col_success   = data.get("col_success",  [0.20, 0.65, 0.30, 1])
        self.w_date        = data.get("w_date",   0.20)
        self.w_prod        = data.get("w_prod",   0.38)
        self.w_qty         = data.get("w_qty",    0.10)
        self.w_price       = data.get("w_price",  0.14)
        self.w_total       = data.get("w_total",  0.10)
        self.w_action      = data.get("w_action", 0.08)
        return super().refresh_view_attrs(rv, index, data)

    def on_action(self):
        if callable(self._on_action_cb) and self._sale_data:
            self._on_action_cb(self._sale_data)


# ─────────────────────────────────────────────────────────────────────────────
#  Screen principal
# ─────────────────────────────────────────────────────────────────────────────
class SalesHistoryScreen(MDScreen):
    # ── Config ────────────────────────────────────────────────────────────────
    ENTER_CACHE_SECONDS = 30
    compact_mode = BooleanProperty(False)

    # Cache de cores — renovado uma vez em _display_rows, nunca por linha
    _C = {
        "divider":    [0, 0, 0, 0.08],
        "bg_even":    [0.97, 0.98, 1,    1],
        "bg_odd":     [1,    1,    1,    1],
        "text_pri":   [0.15, 0.20, 0.30, 1],
        "text_sec":   [0.35, 0.40, 0.50, 1],
        "primary":    [0.10, 0.35, 0.65, 1],
        "success":    [0.20, 0.65, 0.30, 1],
        "warning":    [0.95, 0.62, 0.12, 1],
        "on_primary": [1,    1,    1,    1],
        "card_alt":   [0.65, 0.65, 0.65, 1],
    }

    def __init__(self, db=None, **kwargs):
        self._all_rows          = []
        self._filtered_rows     = []
        self._cache_valid       = False
        self._cache_at          = 0.0
        self._loading           = False
        self._load_token        = 0
        self._exporting         = False
        self._refund_in_prog    = False
        self._search_ev         = None
        self._pending_filter    = None
        self.back_target        = "admin_home"
        self.current_filter     = None
        self.sales_history_report = None
        self.pdf_viewer           = None
        super().__init__(**kwargs)
        self.db = db or get_db()

    # ── Ciclo de vida ─────────────────────────────────────────────────────────
    def on_pre_enter(self, *args):
        """
        REGRA PRINCIPAL: ao entrar, NUNCA mostrar dados automaticamente.
        Se havia um filtro pendente (ex: chamado de outra tela), aplica-o.
        """
        pending = self._pending_filter
        self._pending_filter = None
        self._refresh_color_cache()
        if pending:
            Clock.schedule_once(lambda dt, f=pending: self._apply_pending_filter(f), 0.05)
        else:
            self._show_initial_state()


    def _show_initial_state(self):
        self.current_filter = None
        self._highlight_filter()
        self._set_empty_state(
            "Selecione um filtro para ver o histórico",
            "Use Hoje, Semana, Mês, Ano, Promo ou defina um intervalo de datas.",
            visible=True,
        )
        self._apply_summary(None)
        if "rv" in self.ids:
            self.ids.rv.data = []

    def queue_enter_filter(self, filter_name):
        self._pending_filter = str(filter_name or "").strip().lower() or None

    def _apply_pending_filter(self, filter_name):
        dispatch = {
            "today": self.filter_today,
            "week":  self.filter_this_week,
            "month": self.filter_this_month,
            "year":  self.filter_this_year,
            "promo": self.filter_promotional_sales,
        }
        fn = dispatch.get(filter_name)
        if fn:
            fn()

    def request_enter_refresh(self, force=False, delay=0.05):
        if force:
            self._invalidate_cache()

    def go_back(self, *args):
        if not self.manager:
            return
        target = getattr(self, "back_target", None)
        if target and target in self.manager.screen_names:
            self.manager.current = target
            return
        app = App.get_running_app()
        role = getattr(app, "current_role", "manager")
        fb = "admin" if role == "admin" else "manager"
        if fb in self.manager.screen_names:
            self.manager.current = fb
        elif "login" in self.manager.screen_names:
            self.manager.current = "login"

    def on_size(self, *args):
        Clock.schedule_once(lambda dt: self._update_layout(), 0)

    def _update_layout(self):
        width = self.width or dp(1200)
        compact = width < dp(900)
        changed = compact != self.compact_mode
        self.compact_mode = compact
        if compact:
            w = (0.16, 0.46, 0.10, 0.0, 0.14, 0.14)
        else:
            w = (0.15, 0.40, 0.10, 0.10, 0.13, 0.12)
        for wid, sx in zip(("h_date", "h_prod", "h_qty", "h_price", "h_total", "h_ver"), w):
            if wid in self.ids:
                self.ids[wid].size_hint_x = sx
        if "h_price" in self.ids:
            self.ids.h_price.opacity = 0 if compact else 1
        # compat legado
        if "header_price_lbl" in self.ids:
            self.ids.header_price_lbl.opacity = 0 if compact else 1
        if changed and self._filtered_rows:
            self._display_rows(self._filtered_rows)

    # ── Cache de cores ────────────────────────────────────────────────────────
    def _refresh_color_cache(self):
        app    = App.get_running_app()
        tokens = getattr(app, "theme_tokens", {}) or {}
        card = tokens.get("card", [0.14, 0.16, 0.20, 1])
        card_alt = tokens.get("card_alt", [0.17, 0.19, 0.24, 1])
        self._C = {
            "divider":    tokens.get("divider",        [0.25, 0.28, 0.34, 0.6]),
            "bg_even":    card_alt,
            "bg_odd":     card,
            "text_pri":   tokens.get("text_primary",   [0.95, 0.96, 0.98, 1]),
            "text_sec":   tokens.get("manager_ink", tokens.get("text_secondary", [0.62, 0.67, 0.74, 1])),
            "primary":    tokens.get("primary",        [0.15, 0.48, 0.82, 1]),
            "success":    tokens.get("success",        [0.20, 0.68, 0.42, 1]),
            "warning":    tokens.get("warning",        [0.95, 0.62, 0.12, 1]),
            "danger":     tokens.get("danger",         [0.85, 0.28, 0.30, 1]),
            "on_primary": tokens.get("on_primary",     [1, 1, 1, 1]),
            "card_alt":   card_alt,
            "info":       tokens.get("info",           [0.20, 0.55, 0.80, 1]),
        }


    def _set_empty_state(self, title, msg, visible=True):
        if "empty_state" not in self.ids:
            return
        es = self.ids.empty_state
        es.opacity  = 1 if visible else 0
        es.height   = dp(180) if visible else 0
        es.disabled = not visible
        if "empty_title" in self.ids:
            self.ids.empty_title.text = title
        if "empty_msg" in self.ids:
            self.ids.empty_msg.text = msg
        if "rv" in self.ids:
            self.ids.rv.opacity = 0 if visible else 1

    # ── Resumo ────────────────────────────────────────────────────────────────
    def _build_summary(self, rows):
        gross = refunded = 0.0
        transaction_keys = set()
        for row in rows or []:
            gross    += float(row[4] or 0) if len(row) > 4 else 0.0
            ret_qty   = float(row[6] or 0) if len(row) > 6 else 0.0
            unit_p    = float(row[3] or 0) if len(row) > 3 else 0.0
            refunded += ret_qty * unit_p
            transaction_code = str(row[12] if len(row) > 12 and row[12] is not None else "").strip()
            sale_id = row[0] if len(row) > 0 else id(row)
            transaction_keys.add(transaction_code or f"sale:{sale_id}")
        return {
            "total_sales":    len(transaction_keys),
            "net_revenue":    gross - refunded,
            "refunded_total": refunded,
        }

    def _apply_summary(self, summary):
        if "total_sales_label" not in self.ids:
            return
        if not summary:
            self.ids.total_sales_label.text  = "—"
            self.ids.total_revenue_label.text = "—"
            self.ids.avg_sale_label.text      = "—"
            return
        self.ids.total_sales_label.text  = str(int(summary.get("total_sales") or 0))
        self.ids.total_revenue_label.text = f"{self._fmt_cur(summary.get('net_revenue', 0))} MT"
        self.ids.avg_sale_label.text      = f"{self._fmt_cur(summary.get('refunded_total', 0))} MT"

    # ── Formatação ────────────────────────────────────────────────────────────
    @staticmethod
    def _fmt_date(date_str):
        if not date_str:
            return ""
        try:
            return datetime.fromisoformat(str(date_str)).strftime("%d/%m/%y\n%H:%M")
        except Exception:
            try:
                return datetime.strptime(str(date_str), "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%y\n%H:%M")
            except Exception:
                return str(date_str)[:16]

    @staticmethod
    def _fmt_qty(qty):
        try:
            q = float(qty)
            return str(int(q)) if q.is_integer() else f"{q:.1f}"
        except Exception:
            return str(qty)

    @staticmethod
    def _fmt_cur(value):
        try:
            v = float(value)
            return f"{v:,.2f}".replace(",", " ")
        except Exception:
            return "0.00"

    # ── Conversão row → dict ──────────────────────────────────────────────────
    def _row_to_dict(self, row):
        qty          = float(row[2] or 0) if len(row) > 2 else 0.0
        returned_qty = float(row[6] or 0) if len(row) > 6 else 0.0
        available    = float(row[7] or 0) if len(row) > 7 else max(0.0, qty - returned_qty)
        return {
            "sale_id":       row[0] if len(row) > 0 else None,
            "product":       (row[1] if len(row) > 1 else "") or "Produto",
            "qty":           qty,
            "price":         float(row[3] or 0) if len(row) > 3 else 0.0,
            "total":         float(row[4] or 0) if len(row) > 4 else 0.0,
            "sale_date":     row[5] if len(row) > 5 else "",
            "returned_qty":  returned_qty,
            "available_qty": max(0.0, available),
            "created_by":    row[8] if len(row) > 8 else None,
            "created_role":  row[9] if len(row) > 9 else None,
            "is_promotional": bool(row[10]) if len(row) > 10 else False,
            "transaction_code": str(row[12] if len(row) > 12 and row[12] is not None else "").strip(),
        }

    @staticmethod
    def _row_transaction_key(row, index=0):
        sale_id = row[0] if len(row) > 0 else index
        code = row[12] if len(row) > 12 else ""
        return transaction_key(code, sale_id if sale_id is not None else index)

    @staticmethod
    def _refund_window_text(seconds_left, refundable):
        if not refundable:
            return "Estorno indisponível"
        minutes, seconds = divmod(max(0, int(seconds_left or 0)), 60)
        return f"Estorno: {minutes:02d}:{seconds:02d}"

    # ── RecycleView: montar data list ─────────────────────────────────────────
    def _display_rows(self, rows):
        if "rv" not in self.ids:
            return

        self._refresh_color_cache()
        C = self._C

        compact = self.compact_mode
        if compact:
            w_date, w_prod, w_qty, w_price, w_total, w_action = 0.16, 0.46, 0.10, 0.0, 0.14, 0.14
            show_price = 0
        else:
            w_date, w_prod, w_qty, w_price, w_total, w_action = 0.15, 0.40, 0.10, 0.10, 0.13, 0.12
            show_price = 1

        data = []
        transactions = group_sale_records(
            [self._row_to_dict(row) for row in (rows or [])],
        )

        for i, transaction in enumerate(transactions):
            items = transaction["items"]
            product_names = []
            for item in items:
                name = str(item.get("product") or "Produto").strip()
                if name not in product_names:
                    product_names.append(name)

            def _short(n, limit=28):
                n = str(n or "").strip()
                if len(n) <= limit:
                    return n
                return n[: limit - 1].rstrip() + "…"

            if len(product_names) == 1:
                displayed = _short(product_names[0], 32)
            elif len(product_names) == 2:
                displayed = f"{_short(product_names[0], 18)} · {_short(product_names[1], 14)}"
            else:
                displayed = f"{_short(product_names[0], 22)} · +{len(product_names) - 1}"

            code = transaction.get("transaction_code") or ""
            sale_ref = code if code and len(str(code)) <= 16 else f"#{items[0].get('sale_id')}"
            meta_parts = [f"{transaction['item_count']} item(s)", str(sale_ref)]
            seller = str(transaction.get("created_by") or "").strip()
            if seller and seller.lower() != "sistema":
                meta_parts.append(seller)
            if transaction.get("is_promotional"):
                meta_parts.append("PROMO")
            if float(transaction.get("refunded_total") or 0) > 0:
                meta_parts.append(f"est. {self._fmt_cur(transaction['refunded_total'])}")
            if transaction.get("can_refund"):
                minutes, seconds = divmod(max(0, int(transaction.get("refund_seconds_left") or 0)), 60)
                meta_parts.append(f"{minutes:02d}:{seconds:02d}")
            else:
                meta_parts.append("expirado")

            data.append({
                "sale_data": transaction,
                "action_callback": self.open_transaction_dialog,
                "row_bg": C["bg_even"] if i % 2 == 0 else C["bg_odd"],
                "col_date": self._fmt_date(transaction.get("sale_date")),
                "col_product": displayed or "Produtos",
                "col_meta": "  ·  ".join(meta_parts),
                "col_qty": self._fmt_qty(transaction.get("quantity")),
                "col_price": str(transaction.get("item_count") or 0),
                "col_total": self._fmt_cur(transaction.get("net_total")),
                "btn_label": "VER",
                "btn_color": C["primary"],
                "btn_disabled": False,
                "show_price": show_price,
                "col_text_pri": C["text_pri"],
                "col_text_sec": C["text_sec"],
                "col_primary": C["primary"],
                "col_success": C["success"],
                "w_date": w_date, "w_prod": w_prod,
                "w_qty": w_qty, "w_price": w_price,
                "w_total": w_total, "w_action": w_action,
            })

        self.ids.rv.data = data

        if data:
            self._set_empty_state("", "", visible=False)
            self._apply_summary(self._build_summary(rows))
        else:
            self._set_empty_state(
                "Nenhuma venda encontrada",
                "Ajuste os filtros ou adicione novas vendas.",
                visible=True,
            )
            self._apply_summary(None)

    # ── Cache e fetch async ───────────────────────────────────────────────────
    def _invalidate_cache(self):
        self._all_rows   = []
        self._cache_valid = False
        self._cache_at    = 0.0

    def _load_async(self, fetcher, cache_all=False):
        """Busca rows em thread de background. Nunca bloqueia a UI."""
        token = self._load_token + 1
        self._load_token = token
        self._loading    = True
        self._set_empty_state("A carregar…", "Aguarde um momento.", visible=True)
        if "rv" in self.ids:
            self.ids.rv.data = []

        def worker():
            rows  = []
            error = None
            try:
                rows = list(fetcher() or [])
            except Exception as exc:
                error = str(exc)
            Clock.schedule_once(
                lambda dt, r=rows, e=error, t=token, ca=cache_all:
                    self._on_rows_loaded(r, e, t, ca),
                0,
            )

        Thread(target=worker, daemon=True).start()

    def _on_rows_loaded(self, rows, error, token, cache_all):
        if token != self._load_token:
            return
        self._loading = False
        if error:
            self._set_empty_state("Erro ao carregar", error, visible=True)
            return
        if cache_all:
            self._all_rows    = list(rows)
            self._cache_valid = True
            self._cache_at    = perf_counter()
        visible = self._apply_text_filter(rows)
        self._filtered_rows = visible
        self._display_rows(visible)

    # ── Filtros locais (sem round-trip ao DB) ─────────────────────────────────
    @staticmethod
    @lru_cache(maxsize=4096)
    def _parse_dt(value):
        if not value:
            return None
        raw = str(value).strip()
        for parser in (
            lambda s: datetime.fromisoformat(s),
            lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M:%S"),
            lambda s: datetime.strptime(s, "%Y-%m-%d"),
            lambda s: datetime.strptime(s, "%d/%m/%Y"),
        ):
            try:
                return parser(raw)
            except Exception:
                pass
        return None

    def _filter_by_date(self, rows, start_text="", end_text=""):
        s, e = (start_text or "").strip(), (end_text or "").strip()
        if s and not e:
            e = s
        elif e and not s:
            s = e
        if not s and not e:
            return list(rows or [])
        s_dt = self._parse_dt(s)
        e_dt = self._parse_dt(e)
        if s and not s_dt:
            return []
        if e and not e_dt:
            return []
        s_d = s_dt.date() if s_dt else None
        e_d = e_dt.date() if e_dt else None
        out = []
        for row in rows or []:
            dt = self._parse_dt(row[5] if len(row) > 5 else "")
            if dt is None:
                continue
            d = dt.date()
            if s_d and d < s_d:
                continue
            if e_d and d > e_d:
                continue
            out.append(row)
        return out

    def _filter_promo(self, rows):
        promo_keys = {
            self._row_transaction_key(row, index)
            for index, row in enumerate(rows or [])
            if len(row) > 10 and bool(row[10])
        }
        return [
            row for index, row in enumerate(rows or [])
            if self._row_transaction_key(row, index) in promo_keys
        ]

    def _apply_text_filter(self, rows):
        query = self._get_search_text()
        if not query:
            return list(rows or [])
        q = query.lower()
        matching_keys = set()
        for index, row in enumerate(rows or []):
            haystack = " ".join(str(v or "") for v in (
                row[0] if len(row) > 0 else "",
                row[1] if len(row) > 1 else "",
                row[8] if len(row) > 8 else "",
                row[5] if len(row) > 5 else "",
                row[12] if len(row) > 12 else "",
            )).lower()
            if q in haystack:
                matching_keys.add(self._row_transaction_key(row, index))
        return [
            row for index, row in enumerate(rows or [])
            if self._row_transaction_key(row, index) in matching_keys
        ]

    def _get_search_text(self):
        if "search_input" not in self.ids:
            return ""
        return (self.ids.search_input.text or "").strip()

    def _get_date_inputs(self):
        start = (self.ids.start_date.text if "start_date" in self.ids else "").strip()
        end   = (self.ids.end_date.text   if "end_date"   in self.ids else "").strip()
        return start, end

    def _from_cache_filtered(self, start="", end="", promo_only=False):
        """Aplica filtros sobre o cache local sem ir ao DB. Retorna None se sem cache."""
        if not self._cache_valid:
            return None
        rows = self._filter_by_date(self._all_rows, start, end)
        if promo_only:
            rows = self._filter_promo(rows)
        return self._apply_text_filter(rows)

    # ── Filtros públicos ──────────────────────────────────────────────────────
    def _set_date_inputs(self, start, end):
        if "start_date" in self.ids:
            self.ids.start_date.text = start
        if "end_date" in self.ids:
            self.ids.end_date.text = end


    def _highlight_filter(self):
        """Destaca o atalho de filtro activo."""
        mapping = {
            "today": "btn_today",
            "week": "btn_week",
            "month": "btn_month",
            "year": "btn_year",
            "promo": "btn_promo",
            "all": "btn_all",
        }
        for key, wid in mapping.items():
            btn = self.ids.get(wid) if self.ids else None
            if btn is None:
                continue
            active = self.current_filter == key or (
                key == "all" and self.current_filter in (None, "all", "custom")
            )
            btn.opacity = 1.0 if active else 0.55

    def filter_today(self):
        self.current_filter = "today"
        today = datetime.now().strftime("%d/%m/%Y")
        self._highlight_filter()
        self._set_date_inputs(today, today)
        cached = self._from_cache_filtered(today, today)
        if cached is not None:
            self._filtered_rows = cached
            self._display_rows(cached)
            return
        self._load_async(lambda d=today: self.db.get_sales_by_date(d))

    def filter_this_week(self):
        self.current_filter = "week"
        today = datetime.now()
        start = (today - timedelta(days=today.weekday())).strftime("%d/%m/%Y")
        end   = today.strftime("%d/%m/%Y")
        self._highlight_filter()
        self._set_date_inputs(start, end)
        cached = self._from_cache_filtered(start, end)
        if cached is not None:
            self._filtered_rows = cached
            self._display_rows(cached)
            return
        self._load_async(lambda s=start, e=end: self.db.get_sales_by_date_range(s, e))

    def filter_this_month(self):
        self.current_filter = "month"
        today = datetime.now()
        start = today.replace(day=1).strftime("%d/%m/%Y")
        end   = today.strftime("%d/%m/%Y")
        self._highlight_filter()
        self._set_date_inputs(start, end)
        cached = self._from_cache_filtered(start, end)
        if cached is not None:
            self._filtered_rows = cached
            self._display_rows(cached)
            return
        self._load_async(lambda s=start, e=end: self.db.get_sales_by_date_range(s, e))

    def filter_this_year(self):
        self.current_filter = "year"
        today = datetime.now()
        start = today.replace(month=1, day=1).strftime("%d/%m/%Y")
        end   = today.strftime("%d/%m/%Y")
        self._highlight_filter()
        self._set_date_inputs(start, end)
        cached = self._from_cache_filtered(start, end)
        if cached is not None:
            self._filtered_rows = cached
            self._display_rows(cached)
            return
        self._load_async(lambda s=start, e=end: self.db.get_sales_by_date_range(s, e))

    def filter_promotional_sales(self):
        self.current_filter = "promo"
        self.current_filter = "promo"
        self._highlight_filter()
        start, end = self._get_date_inputs()
        cached = self._from_cache_filtered(start, end, promo_only=True)
        if cached is not None:
            self._filtered_rows = cached
            self._display_rows(cached)
            return
        self._load_async(
            lambda s=start, e=end: self._filter_promo(
                self.db.get_sales_by_date_range(s, e) if s and e
                else self.db.get_all_sales()
            )
        )

    def apply_search_filter(self):
        if not self._cache_valid:
            return
        start, end = self._get_date_inputs()
        rows = self._filter_by_date(self._all_rows, start, end)
        if self.current_filter == "promo":
            rows = self._filter_promo(rows)
        rows = self._apply_text_filter(rows)
        self._filtered_rows = rows
        self._display_rows(rows)

    def _on_search_text(self, text):
        """Debounce: aplica filtro após uma pausa curta na digitação."""
        if self._search_ev:
            self._search_ev.cancel()
        if not self._cache_valid:
            return
        self._search_ev = Clock.schedule_once(lambda dt: self.apply_search_filter(), 0.35)

    def clear_search_filter(self):
        if "search_input" in self.ids:
            self.ids.search_input.text = ""
        self.apply_search_filter()

    def apply_date_filter(self):
        start, end = self._get_date_inputs()
        promo = self.current_filter == "promo"
        cached = self._from_cache_filtered(start, end, promo_only=promo)
        if cached is not None:
            self._filtered_rows = cached
            self._display_rows(cached)
            return
        if start and end:
            self.current_filter = self.current_filter or "custom"
            fetcher = lambda s=start, e=end: self.db.get_sales_by_date_range(s, e)
            if promo:
                fetcher = lambda s=start, e=end: self._filter_promo(self.db.get_sales_by_date_range(s, e))
        else:
            fetcher = lambda: self.db.get_all_sales()
        self._load_async(fetcher, cache_all=not promo)

    def load_all_sales(self, force_refresh=False, prefer_local_cache=False):
        self.current_filter = "all"
        self._highlight_filter()
        self._set_date_inputs("", "")
        if force_refresh:
            self._invalidate_cache()
        if prefer_local_cache and self._cache_valid:
            rows = self._apply_text_filter(self._all_rows)
            self._filtered_rows = rows
            self._display_rows(rows)
            return
        self._load_async(lambda: self.db.get_all_sales(), cache_all=True)

    def _hard_refresh(self):
        self._invalidate_cache()
        if self.current_filter:
            self._reload_current_filter()
        else:
            self._show_initial_state()

    def _reload_current_filter(self):
        dispatch = {
            "today": self.filter_today,
            "week":  self.filter_this_week,
            "month": self.filter_this_month,
            "year":  self.filter_this_year,
            "promo": self.filter_promotional_sales,
            "custom": self.apply_date_filter,
        }
        fn = dispatch.get(self.current_filter)
        if fn:
            fn()
        else:
            self._show_initial_state()

    # ── Eliminar histórico ────────────────────────────────────────────────────
    def confirm_delete_history(self):
        """Passo 1: aviso claro, botoes equilibrados."""
        BG = (0.12, 0.14, 0.18, 1)
        CARD = (0.16, 0.19, 0.24, 1)
        TXT = (0.95, 0.96, 0.98, 1)
        MUTED = (0.62, 0.67, 0.75, 1)
        DANGER = (0.85, 0.22, 0.24, 1)
        GRAY = (0.28, 0.32, 0.38, 1)

        popup = ModalView(
            size_hint=(None, None),
            size=(min(Window.width * 0.88, dp(420)), dp(260)),
            background="",
            background_color=[0, 0, 0, 0],
            overlay_color=[0, 0, 0, 0.55],
            auto_dismiss=True,
        )
        root = BoxLayout(
            orientation="vertical",
            padding=[dp(18), dp(16)],
            spacing=dp(12),
        )
        _popup_paint(root, BG, radius=14)

        root.add_widget(_popup_label(
            "Eliminar histórico", size=17, color=TXT, bold=True,
            size_hint_y=None, height=dp(26),
        ))

        warn = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(96),
            padding=[dp(12), dp(10)],
            spacing=dp(4),
        )
        _popup_paint(warn, CARD, radius=10)
        warn.add_widget(_popup_label(
            "Esta ação é IRREVERSÍVEL", size=13, color=DANGER, bold=True,
            size_hint_y=None, height=dp(20),
        ))
        warn.add_widget(_popup_label(
            "Todo o histórico de vendas será apagado permanentemente da base de dados.",
            size=12, color=MUTED,
            size_hint_y=None, height=dp(40),
        ))
        warn.add_widget(_popup_label(
            "Tem a certeza que quer continuar?",
            size=12, color=TXT, bold=True,
            size_hint_y=None, height=dp(20),
        ))
        root.add_widget(warn)

        actions = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(10))
        cancel_btn = _popup_button("CANCELAR", GRAY, width=150, height=40, font_size=12)
        next_btn = _popup_button("CONTINUAR", DANGER, width=150, height=40, font_size=12)
        actions.add_widget(cancel_btn)
        actions.add_widget(Widget())
        actions.add_widget(next_btn)
        root.add_widget(actions)

        cancel_btn.bind(on_release=lambda *_: popup.dismiss())
        next_btn.bind(on_release=lambda *_: self._delete_history_step2(popup))
        popup.add_widget(root)
        popup.open()

    def _delete_history_step2(self, first_dialog):
        """Passo 2: confirmar digitando ELIMINAR."""
        try:
            first_dialog.dismiss()
        except Exception:
            pass

        BG = (0.12, 0.14, 0.18, 1)
        CARD = (0.16, 0.19, 0.24, 1)
        TXT = (0.95, 0.96, 0.98, 1)
        MUTED = (0.62, 0.67, 0.75, 1)
        DANGER = (0.85, 0.22, 0.24, 1)
        GRAY = (0.28, 0.32, 0.38, 1)

        popup = ModalView(
            size_hint=(None, None),
            size=(min(Window.width * 0.88, dp(420)), dp(280)),
            background="",
            background_color=[0, 0, 0, 0],
            overlay_color=[0, 0, 0, 0.55],
            auto_dismiss=True,
        )
        root = BoxLayout(
            orientation="vertical",
            padding=[dp(18), dp(16)],
            spacing=dp(10),
        )
        _popup_paint(root, BG, radius=14)

        root.add_widget(_popup_label(
            "Confirmação final", size=17, color=TXT, bold=True,
            size_hint_y=None, height=dp(26),
        ))
        root.add_widget(_popup_label(
            "Escreva ELIMINAR em maiúsculas para confirmar.",
            size=12, color=MUTED,
            size_hint_y=None, height=dp(22),
        ))

        confirm_input = MDTextField(
            hint_text="ELIMINAR",
            mode="rectangle",
            size_hint_y=None,
            height=dp(44),
            font_size=dp(14),
        )
        root.add_widget(confirm_input)

        tip = BoxLayout(
            size_hint_y=None, height=dp(36),
            padding=[dp(10), dp(6)],
        )
        _popup_paint(tip, CARD, radius=8)
        tip.add_widget(_popup_label(
            "Esta operação não pode ser desfeita.",
            size=11, color=DANGER, bold=True,
            size_hint_y=None, height=dp(24),
        ))
        root.add_widget(tip)

        actions = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(10))
        cancel_btn = _popup_button("CANCELAR", GRAY, width=150, height=40, font_size=12)
        confirm_btn = _popup_button("ELIMINAR", DANGER, width=150, height=40, font_size=12)
        actions.add_widget(cancel_btn)
        actions.add_widget(Widget())
        actions.add_widget(confirm_btn)
        root.add_widget(actions)

        class _Proxy:
            def dismiss(self_inner):
                popup.dismiss()

        proxy = _Proxy()
        cancel_btn.bind(on_release=lambda *_: popup.dismiss())
        confirm_btn.bind(
            on_release=lambda *_: self._execute_delete_history(proxy, confirm_input)
        )
        popup.add_widget(root)
        popup.open()
        Clock.schedule_once(lambda _dt: setattr(confirm_input, "focus", True), 0.08)

    def _execute_delete_history(self, dialog, confirm_input):
        typed = (confirm_input.text or "").strip().upper()
        if typed != "ELIMINAR":
            self._show_msg("Erro", "Escreva ELIMINAR (em maiúsculas) para confirmar.")
            return
        dialog.dismiss()

        def worker():
            error = None
            try:
                fn = getattr(self.db, "delete_all_sales_history", None)
                if not callable(fn):
                    raise RuntimeError(
                        "Método delete_all_sales_history não encontrado na base de dados. "
                        "Actualize o ficheiro database.py."
                    )
                ok = fn()
                if ok is False:
                    raise RuntimeError("A base de dados recusou a eliminação do histórico.")
                app = App.get_running_app()
                username = getattr(app, "current_user", None)
                role = getattr(app, "current_role", None) or "manager"
                if username:
                    try:
                        self.db.log_action(
                            username,
                            role,
                            "DELETE_ALL_SALES_HISTORY",
                            "Histórico de vendas eliminado pelo utilizador.",
                        )
                    except Exception:
                        pass
            except Exception as exc:
                error = str(exc)
            Clock.schedule_once(lambda dt, e=error: self._on_delete_done(e), 0)

        Thread(target=worker, daemon=True).start()

    def _on_delete_done(self, error):
        if error:
            self._show_msg("Erro", f"Não foi possível eliminar o histórico:\n{error}")
            return
        self._invalidate_cache()
        self._filtered_rows = []
        if "rv" in self.ids:
            self.ids.rv.data = []
        self._apply_summary(None)
        self._set_date_inputs("", "")
        if "search_input" in self.ids:
            self.ids.search_input.text = ""
        self.current_filter = None
        self._show_initial_state()
        self._show_msg("Concluído", "Histórico de vendas eliminado com sucesso.")

    # ── Popup "Produtos da venda" (redesenhado) ───────────────────────────────
    def open_transaction_dialog(self, transaction):
        items = list((transaction or {}).get("items") or [])
        if not items:
            self._show_msg("Venda", "Não foi possível obter os produtos desta venda.")
            return

        # Paleta
        C = self._C
        BG_CARD = (0.09, 0.11, 0.15, 1)
        BG_ROW  = (0.13, 0.16, 0.21, 1)
        TXT_PRI = (0.95, 0.96, 0.98, 1)
        TXT_SEC = (0.62, 0.67, 0.75, 1)
        WARN    = (0.95, 0.62, 0.12, 1)
        DANGER  = (0.90, 0.35, 0.35, 1)
        OFF     = (0.30, 0.33, 0.38, 1)

        # Dados da venda
        seconds_left = int((transaction or {}).get("refund_seconds_left") or 0)
        can_refund   = bool((transaction or {}).get("can_refund"))
        seller       = str((transaction or {}).get("created_by") or "").strip() or "Sistema"
        code         = (transaction or {}).get("transaction_code") or f"#{items[0].get('sale_id')}"
        net_total    = self._fmt_cur((transaction or {}).get("net_total"))
        refund_txt   = self._refund_window_text(seconds_left, can_refund)
        refund_color = WARN if can_refund else DANGER

        # Dimensões
        row_h    = dp(72)
        row_gap  = dp(8)
        header_h = dp(70)
        footer_h = dp(52)
        title_h  = dp(36)
        pad      = dp(18)
        spacing  = dp(10)

        list_h   = len(items) * row_h + max(0, len(items) - 1) * row_gap
        wanted_h = title_h + header_h + list_h + footer_h + pad * 2 + spacing * 3
        popup_h  = min(wanted_h, Window.height * 0.88)
        popup_w  = min(Window.width * 0.92, dp(720))

        popup = ModalView(
            size_hint=(None, None),
            size=(popup_w, popup_h),
            background="",
            background_color=[0, 0, 0, 0],
            overlay_color=[0, 0, 0, 0.60],
            auto_dismiss=True,
        )

        root = BoxLayout(
            orientation="vertical",
            padding=[pad, pad, pad, dp(12)],
            spacing=spacing,
        )
        _popup_paint(root, BG_CARD, radius=16)

        # Título
        title_row = BoxLayout(size_hint_y=None, height=title_h)
        title_row.add_widget(_popup_label("Produtos da venda", size=17, color=TXT_PRI, bold=True))
        title_row.add_widget(_popup_label(
            f"[b]{len(items)}[/b] item(ns)", size=12, color=TXT_SEC, halign="right",
            size_hint_x=None, width=dp(100),
        ))
        root.add_widget(title_row)

        # Resumo
        header = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=header_h,
            padding=[dp(14), dp(8)],
            spacing=dp(12),
        )
        _popup_paint(header, BG_ROW, radius=12)

        def info_block(title, value, color=TXT_PRI, size_hint_x=1):
            box = BoxLayout(orientation="vertical", spacing=dp(2), size_hint_x=size_hint_x)
            box.add_widget(_popup_label(title, size=9, color=TXT_SEC, bold=True))
            box.add_widget(_popup_label(
                value, size=13, color=color, bold=True,
                shorten=True, shorten_from="right",
            ))
            return box

        header.add_widget(info_block("ATENDENTE", seller))
        header.add_widget(info_block("TOTAL", f"{net_total} MT", C["success"]))
        header.add_widget(info_block("VENDA", str(code)))
        header.add_widget(info_block(
            f"ESTORNO (MÁX. {REFUND_WINDOW_MINUTES} MIN)", refund_txt, refund_color,
            size_hint_x=1.3,
        ))
        root.add_widget(header)

        # Lista de produtos
        scroll = ScrollView(
            do_scroll_x=False,
            bar_width=dp(4),
            scroll_type=["bars", "content"],
        )
        product_list = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=row_gap,
            padding=[0, 0, dp(6), 0],
        )
        product_list.bind(minimum_height=product_list.setter("height"))
        scroll.add_widget(product_list)
        root.add_widget(scroll)

        for item in items:
            available    = float(item.get("available_qty") or 0.0)
            returned_qty = float(item.get("returned_qty") or 0.0)
            allowed, _left = refund_window_status(item.get("sale_date"))
            refundable = bool(allowed and available > 0.0001)

            row = BoxLayout(
                orientation="horizontal",
                size_hint_y=None,
                height=row_h,
                padding=[dp(14), dp(8)],
                spacing=dp(10),
            )
            _popup_paint(row, BG_ROW, radius=12)

            info = BoxLayout(orientation="vertical", spacing=dp(2))
            info.add_widget(_popup_label(
                str(item.get("product") or "Produto"),
                size=13, color=TXT_PRI, bold=True,
                shorten=True, shorten_from="right",
            ))
            info.add_widget(_popup_label(
                f"{self._fmt_qty(item.get('qty'))} × {self._fmt_cur(item.get('price'))} MT"
                f"   =   {self._fmt_cur(item.get('total'))} MT",
                size=11, color=TXT_SEC,
            ))
            if returned_qty > 0:
                info.add_widget(_popup_label(
                    f"Estornado: {self._fmt_qty(returned_qty)}",
                    size=10, color=WARN,
                ))
            row.add_widget(info)

            if refundable:
                btn_text, btn_color = "ESTORNAR", WARN
            elif available <= 0.0001:
                btn_text, btn_color = "ESTORNADO", OFF
            else:
                btn_text, btn_color = "EXPIRADO", OFF

            btn = _popup_button(btn_text, btn_color, enabled=refundable)
            if refundable:
                btn.bind(
                    on_release=lambda _b, sale=dict(item):
                        self._open_transaction_item_refund(popup, sale)
                )

            holder = BoxLayout(orientation="vertical", size_hint_x=None, width=dp(112))
            holder.add_widget(Widget())
            holder.add_widget(btn)
            holder.add_widget(Widget())
            row.add_widget(holder)

            product_list.add_widget(row)

        # Rodapé
        footer = BoxLayout(size_hint_y=None, height=footer_h, padding=[0, dp(8), 0, 0])
        footer.add_widget(Widget())
        close_btn = _popup_button("FECHAR", C["primary"], width=140, height=40, font_size=12)
        close_btn.bind(on_release=lambda *_: popup.dismiss())
        footer.add_widget(close_btn)
        root.add_widget(footer)

        popup.add_widget(root)
        popup.open()

    def _open_transaction_item_refund(self, transaction_dialog, sale_data):
        transaction_dialog.dismiss()
        self.open_refund_dialog(sale_data)

    # ── Diálogo de remoção de item ────────────────────────────────────────────
    def open_refund_dialog(self, sale_data):
        refund_allowed, _ = refund_window_status((sale_data or {}).get("sale_date"))
        if not refund_allowed:
            self._show_msg(
                "Estorno expirado",
                f"O estorno só é permitido nos primeiros {REFUND_WINDOW_MINUTES} minutos após a venda.",
            )
            return
        available = float(sale_data.get("available_qty", 0) or 0)
        if available <= 0:
            self._show_msg("Remover item", "Esta venda não tem saldo para remover.")
            return

        sale_id      = sale_data.get("sale_id")
        product      = sale_data.get("product") or "Produto"
        qty          = float(sale_data.get("qty", 0) or 0)
        returned_qty = float(sale_data.get("returned_qty", 0) or 0)
        price        = float(sale_data.get("price", 0) or 0)

        # Paleta (igual ao popup "Produtos da venda")
        BG_CARD = (0.09, 0.11, 0.15, 1)
        BG_ROW  = (0.13, 0.16, 0.21, 1)
        TXT_PRI = (0.95, 0.96, 0.98, 1)
        TXT_SEC = (0.62, 0.67, 0.75, 1)
        WARN    = (0.95, 0.62, 0.12, 1)
        DANGER  = (0.90, 0.35, 0.35, 1)
        OFF     = (0.30, 0.33, 0.38, 1)

        popup = ModalView(
            size_hint=(None, None),
            size=(min(Window.width * 0.92, dp(560)), min(dp(520), Window.height * 0.94)),
            background="",
            background_color=[0, 0, 0, 0],
            overlay_color=[0, 0, 0, 0.60],
            auto_dismiss=False,
        )
        root = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(10))
        _popup_paint(root, BG_CARD, radius=16)

        # ── Título ──
        root.add_widget(_popup_label(
            "Remover item da venda", size=17, color=TXT_PRI, bold=True,
            size_hint_y=None, height=dp(30),
        ))

        # ── Cartão do produto ──
        prod_card = BoxLayout(
            orientation="vertical", size_hint_y=None, height=dp(64),
            padding=[dp(14), dp(8)], spacing=dp(2),
        )
        _popup_paint(prod_card, BG_ROW, radius=12)
        prod_card.add_widget(_popup_label(
            product, size=14, color=TXT_PRI, bold=True,
            shorten=True, shorten_from="right",
        ))
        prod_card.add_widget(_popup_label(
            f"Venda #{sale_id}   ·   {self._fmt_cur(price)} MT / un.",
            size=11, color=TXT_SEC,
        ))
        root.add_widget(prod_card)

        # ── Chips: vendido / removido / disponível ──
        chips = BoxLayout(size_hint_y=None, height=dp(54), spacing=dp(8))

        def chip(title, value, color=TXT_PRI):
            box = BoxLayout(orientation="vertical", padding=[dp(12), dp(6)], spacing=dp(1))
            _popup_paint(box, BG_ROW, radius=10)
            box.add_widget(_popup_label(title, size=9, color=TXT_SEC, bold=True))
            box.add_widget(_popup_label(value, size=14, color=color, bold=True))
            return box

        chips.add_widget(chip("VENDIDO", self._fmt_qty(qty)))
        chips.add_widget(chip(
            "REMOVIDO",
            self._fmt_qty(returned_qty),
            WARN if returned_qty > 0 else TXT_PRI,
        ))
        chips.add_widget(chip("DISPONÍVEL", self._fmt_qty(available), self._C["success"]))
        root.add_widget(chips)

        # ── Quantidade com stepper ──
        root.add_widget(_popup_label(
            "QUANTIDADE A REMOVER", size=10, color=TXT_SEC, bold=True,
            size_hint_y=None, height=dp(18),
        ))
        qty_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        qty_input = _popup_input(text=self._fmt_qty(available), input_filter="float")
        qty_input.size_hint_y = 1
        minus_btn = _popup_button("−", OFF, width=44, height=44, font_size=20)
        plus_btn  = _popup_button("+", OFF, width=44, height=44, font_size=20)
        all_btn   = _popup_button("TUDO", WARN, width=70, height=44, font_size=11)
        for w in (minus_btn, qty_input, plus_btn, all_btn):
            qty_row.add_widget(w)
        root.add_widget(qty_row)

        preview = _popup_label(
            "", size=12, color=TXT_SEC, size_hint_y=None, height=dp(22),
        )
        root.add_widget(preview)

        def _read_qty():
            try:
                return float((qty_input.text or "").replace(",", "."))
            except Exception:
                return 0.0

        def _update_preview(*_):
            q = _read_qty()
            if q <= 0 or q > available + 1e-9:
                preview.color = list(DANGER)
                preview.text = f"Quantidade inválida (máx. {self._fmt_qty(available)})"
            else:
                preview.color = list(TXT_SEC)
                preview.text = f"Valor a estornar:  [b]{self._fmt_cur(q * price)} MT[/b]"

        def _step(delta):
            q = min(available, max(0.0, _read_qty() + delta))
            qty_input.text = self._fmt_qty(q)

        qty_input.bind(text=_update_preview)
        minus_btn.bind(on_release=lambda *_: _step(-1))
        plus_btn.bind(on_release=lambda *_: _step(+1))
        all_btn.bind(on_release=lambda *_: setattr(qty_input, "text", self._fmt_qty(available)))
        _update_preview()

        # ── Motivo + atalhos ──
        root.add_widget(_popup_label(
            "MOTIVO", size=10, color=TXT_SEC, bold=True,
            size_hint_y=None, height=dp(18),
        ))
        reason_input = _popup_input(text="Item lançado por engano", hint="Motivo")
        root.add_widget(reason_input)

        quick = BoxLayout(size_hint_y=None, height=dp(32), spacing=dp(6))
        for txt in ("Lançado por engano", "Cliente desistiu", "Produto danificado"):
            b = _popup_button(txt, OFF, width=10, height=32, font_size=10)
            b.size_hint = (1, None)
            b.bind(on_release=lambda _b, t=txt: setattr(reason_input, "text", t))
            quick.add_widget(b)
        root.add_widget(quick)

        root.add_widget(Widget())  # empurra o rodapé para baixo

        # ── Rodapé: botões com tamanho fixo ──
        footer = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(10))
        footer.add_widget(Widget())
        cancel_btn  = _popup_button("CANCELAR", OFF, width=130, height=44, font_size=12)
        confirm_btn = _popup_button("CONFIRMAR", WARN, width=170, height=44, font_size=12)
        footer.add_widget(cancel_btn)
        footer.add_widget(confirm_btn)
        root.add_widget(footer)

        cancel_btn.bind(on_release=lambda *_: popup.dismiss())
        confirm_btn.bind(
            on_release=lambda *_: self._submit_refund(
                popup, sale_data, qty_input, reason_input, cancel_btn, confirm_btn,
            )
        )

        popup.add_widget(root)
        popup.open()


    def _set_refund_state(self, widgets, busy):
        for w in widgets:
            if w:
                w.disabled = busy
        confirm = widgets[-1]
        if confirm:
            confirm.text = "A PROCESSAR…" if busy else "CONFIRMAR"

    def _submit_refund(self, dialog, sale_data, qty_input, reason_input, cancel_btn, confirm_btn):
        if self._refund_in_prog:
            return
        refund_allowed, _seconds_left = refund_window_status((sale_data or {}).get("sale_date"))
        if not refund_allowed:
            self._show_msg(
                "Estorno expirado",
                f"O prazo de {REFUND_WINDOW_MINUTES} minutos para estorno desta venda expirou.",
            )
            return
        try:
            qty = float((qty_input.text or "").strip())
        except Exception:
            self._show_msg("Erro", "Quantidade inválida.")
            return
        available = float(sale_data.get("available_qty", 0) or 0)
        if qty <= 0:
            self._show_msg("Erro", "Quantidade deve ser maior que zero.")
            return
        if qty > available + 1e-9:
            self._show_msg("Erro", f"Acima do disponível ({available:.2f}).")
            return

        app      = App.get_running_app()
        username = getattr(app, "current_user", None)
        role     = getattr(app, "current_role", None) or "manager"
        reason   = (reason_input.text or "").strip() or "Item lançado por engano"
        sale_id  = sale_data.get("sale_id")
        self._refund_in_prog = True
        widgets = [qty_input, reason_input, cancel_btn, confirm_btn]
        self._set_refund_state(widgets, True)

        def worker():
            try:
                result = self.db.refund_sale_item(
                    sale_id, qty, reason=reason, username=username, role=role,
                )
                ok  = isinstance(result, dict) and bool(result.get("ok"))
                msg = result.get("message") if not ok and isinstance(result, dict) else None
                if ok and username:
                    try:
                        total_r = float((result or {}).get("total_refund", 0) or 0)
                        self.db.log_action(
                            username, role, "REMOVE_SALE_ITEM",
                            f"Venda #{sale_id} | Qtd {qty:.2f} | {total_r:.2f} MT",
                        )
                    except Exception:
                        pass
                payload = {"ok": ok, "message": msg}
            except Exception as exc:
                payload = {"ok": False, "message": str(exc)}
            Clock.schedule_once(
                lambda dt, p=payload: self._on_refund_done(dialog, p, qty, widgets), 0,
            )

        Thread(target=worker, daemon=True).start()

    def _on_refund_done(self, dialog, result, qty, widgets):
        self._refund_in_prog = False
        self._set_refund_state(widgets, False)
        if not (result or {}).get("ok"):
            self._show_msg("Erro", (result or {}).get("message") or "Falha ao remover item.")
            return
        dialog.dismiss()
        self._invalidate_cache()
        self._reload_current_filter()
        self._show_msg("Sucesso", f"Item removido com sucesso ({qty:.2f}).")

    # ── Export PDF ────────────────────────────────────────────────────────────
    def export_sales(self):
        if self._exporting:
            self._show_msg("Aviso", "Exportação já em curso.")
            return
        if self._loading:
            self._show_msg("Aguarde", "Dados ainda a carregar.")
            return
        rows = self._filtered_rows or []
        if not rows:
            self._show_msg("Aviso", "Não há vendas para exportar com os filtros atuais.")
            return
        sales   = [self._row_to_dict(r) for r in rows]
        filters = self._build_pdf_filters(sales)
        app      = App.get_running_app()
        username = getattr(app, "current_user", None)
        role     = getattr(app, "current_role", None) or "manager"
        self._exporting = True
        self._show_msg("Exportação", "A gerar PDF…")

        def worker():
            res = {"status": "ok", "path": None, "error": None}
            try:
                if self.sales_history_report is None:
                    from pdfs.sales_history_report import SalesHistoryReport
                    self.sales_history_report = SalesHistoryReport()
                res["path"] = str(self.sales_history_report.generate(sales, filters))
                if username:
                    try:
                        self.db.log_action(username, role, "EXPORT_SALES_PDF", f"PDF: {res['path']}")
                    except Exception:
                        pass
            except Exception as exc:
                res["status"] = "error"
                res["error"]  = str(exc)
            Clock.schedule_once(lambda dt, r=res: self._on_export_done(r), 0)

        Thread(target=worker, args=(), daemon=True).start()

    def _on_export_done(self, result):
        self._exporting = False
        if result.get("status") != "ok":
            self._show_msg("Erro", f"Falha ao gerar PDF: {result.get('error')}")
            return
        pdf_path = result.get("path")
        dialog = MDDialog(
            title="PDF Gerado",
            text=f"Ficheiro criado em:\n{pdf_path}",
            buttons=[
                MDFlatButton(text="FECHAR", on_release=lambda _: dialog.dismiss()),
                MDFlatButton(
                    text="NAVEGADOR",
                    on_release=lambda _: self._open_browser(dialog, pdf_path),
                ),
                MDRaisedButton(
                    text="INTERNO",
                    on_release=lambda _: self._open_internal(dialog, pdf_path),
                ),
            ],
        )
        dialog.open()

    def _open_internal(self, dialog, path):
        dialog.dismiss()
        if self.pdf_viewer is None:
            from pdfs.pdf_viewer import PDFViewer
            self.pdf_viewer = PDFViewer(error_callback=lambda m: self._show_msg("Erro", m))
        self.pdf_viewer._view_internal(path)

    def _open_browser(self, dialog, path):
        dialog.dismiss()
        if self.pdf_viewer is None:
            from pdfs.pdf_viewer import PDFViewer
            self.pdf_viewer = PDFViewer(error_callback=lambda m: self._show_msg("Erro", m))
        self.pdf_viewer._open_in_browser(path)

    def _build_pdf_filters(self, sales):
        start_text, end_text = self._get_date_inputs()
        s_dt = self._parse_dt(start_text)
        e_dt = self._parse_dt(end_text)
        dates = [self._parse_dt(s.get("sale_date")) for s in sales if self._parse_dt(s.get("sale_date"))]
        if not s_dt and dates:
            s_dt = min(dates)
        if not e_dt and dates:
            e_dt = max(dates)
        s_dt = s_dt or datetime.now()
        e_dt = e_dt or s_dt
        if e_dt < s_dt:
            s_dt, e_dt = e_dt, s_dt
        labels = {
            "today": "Hoje", "week": "Esta semana", "month": "Este mês",
            "year": "Este ano", "promo": "Promoções", "custom": "Período personalizado",
        }
        return {
            "start_date":   s_dt,
            "end_date":     e_dt,
            "filter_label": labels.get(self.current_filter, "Todos os registos"),
            "record_count": len(sales),
            "transaction_count": len({
                str(sale.get("transaction_code") or "").strip()
                or f"sale:{sale.get('sale_id') if sale.get('sale_id') is not None else index}"
                for index, sale in enumerate(sales)
            }),
        }

    # ── Utilitário ────────────────────────────────────────────────────────────
    def _show_msg(self, title, message):
        dialog = MDDialog(
            title=title, text=message,
            buttons=[MDFlatButton(text="OK", on_release=lambda _: dialog.dismiss())],
        )
        dialog.open()
