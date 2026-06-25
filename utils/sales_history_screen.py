"""
SalesHistoryScreen — v3

Regras de comportamento
───────────────────────
• Ao entrar na tela, NUNCA carrega dados automaticamente.
  Mostra apenas os filtros. O utilizador escolhe o filtro e carrega.

• RecycleView substitui a criação manual de widgets por linha.
  Suporta 50 000+ linhas sem atraso perceptível: apenas as linhas
  visíveis são renderizadas (reciclagem de views, igual a RecyclerView
  no Android).

• Botão "ELIMINAR HISTÓRICO" na AppBar com confirmação em 2 passos.

• _show_loading_state nunca bloqueia a UI thread (sem clear_widgets()
  síncrono ao pressionar um botão).

• Cache de cores atualizado uma vez por lote, nunca por linha.

• Todos os filtros (hoje, semana, mês, ano, promo, data, texto)
  funcionam sobre o conjunto já carregado sem nova consulta ao DB
  enquanto o cache for válido.
"""

from collections import deque
from datetime import datetime, timedelta
from functools import lru_cache
from threading import Thread
from time import perf_counter

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import BooleanProperty, StringProperty, ListProperty
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.widget import Widget
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField

from database.provider import get_db


# ─────────────────────────────────────────────────────────────────────────────
#  KV
# ─────────────────────────────────────────────────────────────────────────────
Builder.load_string("""
#:import dp kivy.metrics.dp

<SaleRowView>:
    orientation: "horizontal"
    size_hint_y: None
    height: dp(54)
    padding: [dp(12), dp(4), dp(10), dp(4)]
    spacing: dp(6)
    md_bg_color: self.row_bg

    MDLabel:
        text: root.col_date
        size_hint_x: root.w_date
        halign: "left"
        font_size: dp(10)
        theme_text_color: "Custom"
        text_color: root.col_text_sec

    MDBoxLayout:
        orientation: "vertical"
        size_hint_x: root.w_prod
        padding: [0, 0, dp(4), 0]
        spacing: dp(1)

        MDLabel:
            text: root.col_product
            halign: "left"
            font_size: dp(12)
            bold: True
            shorten: True
            shorten_from: "right"
            theme_text_color: "Custom"
            text_color: root.col_text_pri

        MDLabel:
            text: root.col_meta
            halign: "left"
            font_size: dp(10)
            shorten: True
            shorten_from: "right"
            theme_text_color: "Custom"
            text_color: root.col_text_sec

    MDLabel:
        text: root.col_qty
        size_hint_x: root.w_qty
        halign: "center"
        font_size: dp(12)
        bold: True
        theme_text_color: "Custom"
        text_color: root.col_primary

    MDLabel:
        id: price_lbl
        text: root.col_price
        size_hint_x: root.w_price
        halign: "right"
        font_size: dp(11)
        theme_text_color: "Custom"
        text_color: root.col_text_sec
        opacity: root.show_price

    MDLabel:
        text: root.col_total
        size_hint_x: root.w_total
        halign: "right"
        font_size: dp(12)
        bold: True
        theme_text_color: "Custom"
        text_color: root.col_success

    MDRaisedButton:
        text: root.btn_label
        size_hint_x: root.w_action
        md_bg_color: root.btn_color
        theme_text_color: "Custom"
        text_color: [1,1,1,1]
        font_size: dp(9)
        elevation: 0
        disabled: root.btn_disabled
        on_release: root.on_action()


<SaleRecycleView>:
    viewclass: "SaleRowView"
    scroll_type: ["bars", "content"]
    bar_width: dp(6)
    bar_color: 0.09, 0.38, 0.73, 0.5
    bar_inactive_color: 0.85, 0.85, 0.88, 1

    RecycleBoxLayout:
        orientation: "vertical"
        default_size: None, dp(54)
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
                height: dp(154)
                padding: dp(10)
                spacing: dp(8)
                elevation: 1
                radius: [dp(8)]
                md_bg_color: app.theme_tokens['card']

                # Linha pesquisa
                MDBoxLayout:
                    size_hint_y: None
                    height: dp(44)
                    spacing: dp(6)

                    MDTextField:
                        id: search_input
                        hint_text: "Produto, vendedor ou ID…"
                        mode: "rectangle"
                        size_hint_x: 1
                        icon_right: "magnify"
                        line_color_focus: app.theme_tokens['primary']
                        on_text_validate: root.apply_search_filter()
                        on_text: root._on_search_text(self.text)

                    MDRaisedButton:
                        text: "BUSCAR"
                        size_hint_x: None
                        width: dp(88)
                        md_bg_color: app.theme_tokens['primary']
                        elevation: 0
                        on_release: root.apply_search_filter()

                    MDFlatButton:
                        text: "LIMPAR"
                        size_hint_x: None
                        width: dp(76)
                        theme_text_color: "Custom"
                        text_color: app.theme_tokens['danger']
                        on_release: root.clear_search_filter()

                # Linha datas
                MDBoxLayout:
                    size_hint_y: None
                    height: dp(44)
                    spacing: dp(6)

                    MDTextField:
                        id: start_date
                        hint_text: "Início  dd/mm/aaaa"
                        mode: "rectangle"
                        size_hint_x: 0.4
                        max_text_length: 10
                        icon_right: "calendar"
                        line_color_focus: app.theme_tokens['primary']
                        on_text_validate: root.apply_date_filter()

                    MDTextField:
                        id: end_date
                        hint_text: "Fim  dd/mm/aaaa"
                        mode: "rectangle"
                        size_hint_x: 0.4
                        max_text_length: 10
                        icon_right: "calendar"
                        line_color_focus: app.theme_tokens['primary']
                        on_text_validate: root.apply_date_filter()

                    MDRaisedButton:
                        text: "APLICAR"
                        size_hint_x: 0.2
                        md_bg_color: app.theme_tokens['primary']
                        elevation: 0
                        on_release: root.apply_date_filter()

                # Atalhos rápidos
                MDBoxLayout:
                    size_hint_y: None
                    height: dp(34)
                    spacing: dp(5)

                    MDRaisedButton:
                        text: "HOJE"
                        md_bg_color: app.theme_tokens['success']
                        elevation: 0
                        on_release: root.filter_today()

                    MDRaisedButton:
                        text: "SEMANA"
                        md_bg_color: app.theme_tokens['info']
                        elevation: 0
                        on_release: root.filter_this_week()

                    MDRaisedButton:
                        text: "MÊS"
                        md_bg_color: app.theme_tokens['info']
                        elevation: 0
                        on_release: root.filter_this_month()

                    MDRaisedButton:
                        text: "ANO"
                        md_bg_color: app.theme_tokens['info']
                        elevation: 0
                        on_release: root.filter_this_year()

                    MDRaisedButton:
                        text: "PROMO"
                        md_bg_color: app.theme_tokens['warning']
                        elevation: 0
                        on_release: root.filter_promotional_sales()

                    MDFlatButton:
                        text: "TODOS"
                        theme_text_color: "Custom"
                        text_color: app.theme_tokens['danger']
                        on_release: root.load_all_sales(prefer_local_cache=True)

            # ── Resumo ────────────────────────────────────────────────────────
            MDCard:
                orientation: "horizontal"
                size_hint_y: None
                height: dp(58)
                padding: [dp(14), dp(6)]
                spacing: dp(0)
                elevation: 1
                radius: [dp(8)]
                md_bg_color: app.theme_tokens['card']

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
                        font_style: "H5"
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
                        font_style: "H5"
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
                        text: "Removidos"
                        font_style: "Caption"
                        theme_text_color: "Secondary"
                        halign: "center"

                    MDLabel:
                        id: avg_sale_label
                        text: "—"
                        font_style: "H5"
                        bold: True
                        halign: "center"
                        theme_text_color: "Custom"
                        text_color: app.theme_tokens['info']

            # ── Tabela ────────────────────────────────────────────────────────
            MDCard:
                orientation: "vertical"
                padding: dp(0)
                spacing: dp(0)
                elevation: 1
                radius: [dp(8)]
                md_bg_color: app.theme_tokens['card']

                # Cabeçalho
                MDBoxLayout:
                    size_hint_y: None
                    height: dp(36)
                    padding: [dp(12), dp(0)]
                    spacing: dp(6)
                    md_bg_color: app.theme_tokens['card_alt']
                    radius: [dp(8), dp(8), 0, 0]

                    MDLabel:
                        text: "Data/Hora"
                        bold: True
                        size_hint_x: 0.20
                        halign: "left"
                        font_size: dp(11)
                        theme_text_color: "Secondary"

                    MDLabel:
                        text: "Produto"
                        bold: True
                        size_hint_x: 0.38
                        halign: "left"
                        font_size: dp(11)
                        theme_text_color: "Secondary"

                    MDLabel:
                        text: "Qtd"
                        bold: True
                        size_hint_x: 0.10
                        halign: "center"
                        font_size: dp(11)
                        theme_text_color: "Secondary"

                    MDLabel:
                        id: header_price_lbl
                        text: "Preço"
                        bold: True
                        size_hint_x: 0.14
                        halign: "right"
                        font_size: dp(11)
                        theme_text_color: "Secondary"

                    MDLabel:
                        text: "Total"
                        bold: True
                        size_hint_x: 0.10
                        halign: "right"
                        font_size: dp(11)
                        theme_text_color: "Secondary"

                    MDLabel:
                        text: "Ação"
                        bold: True
                        size_hint_x: 0.08
                        halign: "center"
                        font_size: dp(11)
                        theme_text_color: "Secondary"

                # RecycleView — renderiza apenas as linhas visíveis
                SaleRecycleView:
                    id: rv
                    data: []

                # Estado vazio / instrução inicial
                MDBoxLayout:
                    id: empty_state
                    orientation: "vertical"
                    padding: dp(40)
                    spacing: dp(12)
                    size_hint_y: None
                    height: dp(180)
                    opacity: 1

                    MDLabel:
                        id: empty_title
                        text: "Selecione um filtro para ver o histórico"
                        halign: "center"
                        theme_text_color: "Hint"
                        font_style: "H6"
                        bold: True

                    MDLabel:
                        id: empty_msg
                        text: "Use Hoje, Semana, Mês, Ano, Promo ou defina um intervalo de datas."
                        halign: "center"
                        theme_text_color: "Hint"
""")


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

    w_date   = 0.20
    w_prod   = 0.38
    w_qty    = 0.10
    w_price  = 0.14
    w_total  = 0.10
    w_action = 0.08

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
    ENTER_CACHE_SECONDS = 30   # cache válido por 30 s antes de precisar re-fetch
    compact_mode = BooleanProperty(False)

    # Cache de cores — atualizado uma vez em _display_rows, nunca por linha
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
        # Estado interno
        self._all_rows          = []   # todos os rows do DB (cache)
        self._filtered_rows     = []   # subset após filtros
        self._cache_valid       = False
        self._cache_at          = 0.0
        self._loading           = False
        self._load_token        = 0
        self._exporting         = False
        self._refund_in_prog    = False
        self._search_ev         = None
        self._pending_filter    = None  # filtro a aplicar ao entrar
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
        Mostra o estado inicial com instrução de selecionar filtro.
        Se havia um filtro pendente (ex: chamado de outra tela), aplica-o.
        """
        pending = self._pending_filter
        self._pending_filter = None
        self._refresh_color_cache()
        if pending:
            Clock.schedule_once(lambda dt, f=pending: self._apply_pending_filter(f), 0.05)
        else:
            # Sempre começa em branco — nunca auto-carrega
            self._show_initial_state()

    def _show_initial_state(self):
        """Estado inicial: sem dados, sem spinner, só instrução."""
        self._set_empty_state(
            "Selecione um filtro para ver o histórico",
            "Use Hoje, Semana, Mês, Ano, Promo ou defina um intervalo de datas.",
            visible=True,
        )
        self._apply_summary(None)
        if "rv" in self.ids:
            self.ids.rv.data = []

    def queue_enter_filter(self, filter_name):
        """Chamado externamente para pré-selecionar um filtro ao entrar."""
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
        """Compatibilidade: não auto-carrega, mas invalida cache se force."""
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
        if "header_price_lbl" in self.ids:
            self.ids.header_price_lbl.opacity = 0 if compact else 1
        if changed and self._filtered_rows:
            self._display_rows(self._filtered_rows)

    # ── Cache de cores ────────────────────────────────────────────────────────
    def _refresh_color_cache(self):
        app    = App.get_running_app()
        tokens = getattr(app, "theme_tokens", {})
        self._C = {
            "divider":    tokens.get("divider",        [0,    0,    0,    0.08]),
            "bg_even":    tokens.get("surface_alt",    [0.97, 0.98, 1,    1   ]),
            "bg_odd":     tokens.get("card",           [1,    1,    1,    1   ]),
            "text_pri":   tokens.get("text_primary",   [0.15, 0.20, 0.30, 1   ]),
            "text_sec":   tokens.get("text_secondary", [0.35, 0.40, 0.50, 1   ]),
            "primary":    tokens.get("primary",        [0.10, 0.35, 0.65, 1   ]),
            "success":    tokens.get("success",        [0.20, 0.65, 0.30, 1   ]),
            "warning":    tokens.get("warning",        [0.95, 0.62, 0.12, 1   ]),
            "on_primary": tokens.get("on_primary",     [1,    1,    1,    1   ]),
            "card_alt":   tokens.get("card_alt",       [0.65, 0.65, 0.65, 1   ]),
        }

    # ── Estado vazio ──────────────────────────────────────────────────────────
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
        for row in rows or []:
            gross    += float(row[4] or 0) if len(row) > 4 else 0.0
            ret_qty   = float(row[6] or 0) if len(row) > 6 else 0.0
            unit_p    = float(row[3] or 0) if len(row) > 3 else 0.0
            refunded += ret_qty * unit_p
        return {
            "total_sales":    len(rows or []),
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
            if v >= 1_000_000:
                return f"{v/1_000_000:.2f}M"
            if v >= 1_000:
                return f"{v/1_000:.1f}K"
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
        }

    # ── RecycleView: montar data list (O(n) puro, sem criar widgets) ──────────
    def _display_rows(self, rows):
        """
        Converte rows em lista de dicts para o RecycleView.
        O RecycleView renderiza apenas as linhas visíveis no viewport —
        10 000 linhas têm o mesmo custo de memória que 50 linhas visíveis.
        """
        if "rv" not in self.ids:
            return

        self._refresh_color_cache()
        C = self._C

        compact = self.compact_mode
        if compact:
            w_date, w_prod, w_qty, w_price, w_total, w_action = 0.22, 0.44, 0.11, 0.0, 0.15, 0.08
            show_price = 0
        else:
            w_date, w_prod, w_qty, w_price, w_total, w_action = 0.18, 0.40, 0.10, 0.14, 0.12, 0.08
            show_price = 1

        data = []
        warning_color = C["warning"]
        card_alt      = C["card_alt"]
        on_primary    = C["on_primary"]

        for i, row in enumerate(rows or []):
            sale         = self._row_to_dict(row)
            sale_id      = sale["sale_id"]
            returned_qty = sale["returned_qty"]
            available    = sale["available_qty"]
            price        = sale["price"]
            total        = sale["total"]
            is_promo     = sale["is_promotional"]
            created_by   = sale.get("created_by") or ""

            # Meta inline (sem widgets extras)
            meta_parts = []
            if sale_id:
                meta_parts.append(f"#{sale_id}")
            if created_by and created_by != "Sistema":
                meta_parts.append(created_by)
            if is_promo:
                meta_parts.append("PROMO")
            if returned_qty > 0:
                meta_parts.append(f"rem:{self._fmt_qty(returned_qty)}")

            total_liq  = max(0.0, total - returned_qty * price)
            can_remove = bool(sale_id and available > 0.0001)

            data.append({
                "sale_data":    sale,
                "action_callback": self.open_refund_dialog if can_remove else None,
                "row_bg":       C["bg_even"] if i % 2 == 0 else C["bg_odd"],
                "col_date":     self._fmt_date(sale["sale_date"]),
                "col_product":  str(sale["product"]),
                "col_meta":     "  ·  ".join(meta_parts),
                "col_qty":      self._fmt_qty(sale["qty"]),
                "col_price":    self._fmt_cur(price),
                "col_total":    self._fmt_cur(total_liq),
                "btn_label":    "REM" if can_remove else "OK",
                "btn_color":    warning_color if can_remove else card_alt,
                "btn_disabled": not can_remove,
                "show_price":   show_price,
                "col_text_pri": C["text_pri"],
                "col_text_sec": C["text_sec"],
                "col_primary":  C["primary"],
                "col_success":  C["success"],
                "w_date":  w_date,  "w_prod":  w_prod,
                "w_qty":   w_qty,   "w_price": w_price,
                "w_total": w_total, "w_action": w_action,
            })

        self.ids.rv.data = data   # atribuição única — RecycleView faz diff interno

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
        # Mostra "A carregar…" sem clear síncrono
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
            return  # resultado de uma query cancelada — ignora
        self._loading = False
        if error:
            self._set_empty_state("Erro ao carregar", error, visible=True)
            return
        if cache_all:
            self._all_rows    = list(rows)
            self._cache_valid = True
            self._cache_at    = perf_counter()
        # Aplica filtro de texto se houver
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
        return [r for r in rows if len(r) > 10 and bool(r[10])]

    def _apply_text_filter(self, rows):
        query = self._get_search_text()
        if not query:
            return list(rows or [])
        q = query.lower()
        out = []
        for row in rows or []:
            haystack = " ".join(str(v or "") for v in (
                row[0] if len(row) > 0 else "",
                row[1] if len(row) > 1 else "",
                row[8] if len(row) > 8 else "",
                row[5] if len(row) > 5 else "",
            )).lower()
            if q in haystack:
                out.append(row)
        return out

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

    def filter_today(self):
        today = datetime.now().strftime("%d/%m/%Y")
        self.current_filter = "today"
        self._set_date_inputs(today, today)
        cached = self._from_cache_filtered(today, today)
        if cached is not None:
            self._filtered_rows = cached
            self._display_rows(cached)
            return
        self._load_async(lambda d=today: self.db.get_sales_by_date(d))

    def filter_this_week(self):
        today = datetime.now()
        start = (today - timedelta(days=today.weekday())).strftime("%d/%m/%Y")
        end   = today.strftime("%d/%m/%Y")
        self.current_filter = "week"
        self._set_date_inputs(start, end)
        cached = self._from_cache_filtered(start, end)
        if cached is not None:
            self._filtered_rows = cached
            self._display_rows(cached)
            return
        self._load_async(lambda s=start, e=end: self.db.get_sales_by_date_range(s, e))

    def filter_this_month(self):
        today = datetime.now()
        start = today.replace(day=1).strftime("%d/%m/%Y")
        end   = today.strftime("%d/%m/%Y")
        self.current_filter = "month"
        self._set_date_inputs(start, end)
        cached = self._from_cache_filtered(start, end)
        if cached is not None:
            self._filtered_rows = cached
            self._display_rows(cached)
            return
        self._load_async(lambda s=start, e=end: self.db.get_sales_by_date_range(s, e))

    def filter_this_year(self):
        today = datetime.now()
        start = today.replace(month=1, day=1).strftime("%d/%m/%Y")
        end   = today.strftime("%d/%m/%Y")
        self.current_filter = "year"
        self._set_date_inputs(start, end)
        cached = self._from_cache_filtered(start, end)
        if cached is not None:
            self._filtered_rows = cached
            self._display_rows(cached)
            return
        self._load_async(lambda s=start, e=end: self.db.get_sales_by_date_range(s, e))

    def filter_promotional_sales(self):
        self.current_filter = "promo"
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
            # Nenhum dado carregado ainda — não faz nada silencioso
            return
        start, end = self._get_date_inputs()
        rows = self._filter_by_date(self._all_rows, start, end)
        if self.current_filter == "promo":
            rows = self._filter_promo(rows)
        rows = self._apply_text_filter(rows)
        self._filtered_rows = rows
        self._display_rows(rows)

    def _on_search_text(self, text):
        """Debounce: aplica filtro 250 ms após o último caractere digitado."""
        if self._search_ev:
            self._search_ev.cancel()
        if not self._cache_valid:
            return
        self._search_ev = Clock.schedule_once(lambda dt: self.apply_search_filter(), 0.25)

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
        self.current_filter = None
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
        """
        Pede confirmação em 2 passos antes de eliminar todo o histórico.
        """
        cancel_btn  = MDFlatButton(text="CANCELAR")
        confirm_btn = MDRaisedButton(
            text="SIM, ELIMINAR",
            md_bg_color=[0.85, 0.15, 0.15, 1],
        )
        dialog = MDDialog(
            title="Eliminar Histórico de Vendas",
            text=(
                "Esta ação é IRREVERSÍVEL.\n\n"
                "Todo o histórico de vendas será apagado permanentemente da base de dados.\n\n"
                "Tem a certeza que quer continuar?"
            ),
            buttons=[cancel_btn, confirm_btn],
        )
        cancel_btn.bind(on_release=lambda _: dialog.dismiss())
        confirm_btn.bind(on_release=lambda _: self._delete_history_step2(dialog))
        dialog.open()

    def _delete_history_step2(self, first_dialog):
        """Segunda confirmação — digitar a palavra ELIMINAR."""
        first_dialog.dismiss()

        confirm_input = MDTextField(
            hint_text='Digite ELIMINAR para confirmar',
            mode="rectangle",
            size_hint_y=None,
            height=dp(48),
        )
        content = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(70),
            padding=[dp(4), dp(8)],
        )
        content.add_widget(confirm_input)

        cancel_btn  = MDFlatButton(text="CANCELAR")
        confirm_btn = MDRaisedButton(
            text="ELIMINAR DEFINITIVAMENTE",
            md_bg_color=[0.85, 0.15, 0.15, 1],
        )
        dialog = MDDialog(
            title="Confirmação Final",
            text="Esta operação não pode ser desfeita.",
            type="custom",
            content_cls=content,
            buttons=[cancel_btn, confirm_btn],
        )
        cancel_btn.bind(on_release=lambda _: dialog.dismiss())
        confirm_btn.bind(
            on_release=lambda _: self._execute_delete_history(dialog, confirm_input)
        )
        dialog.open()

    def _execute_delete_history(self, dialog, confirm_input):
        typed = (confirm_input.text or "").strip().upper()
        if typed != "ELIMINAR":
            self._show_msg("Erro", "Escreva ELIMINAR (em maiúsculas) para confirmar.")
            return
        dialog.dismiss()

        def worker():
            error = None
            try:
                # Chama o método do DB (deve existir no seu provider)
                fn = getattr(self.db, "delete_all_sales_history", None)
                if callable(fn):
                    fn()
                else:
                    # Fallback: tenta SQL direto se o provider expõe conexão
                    conn = getattr(self.db, "conn", None) or getattr(self.db, "connection", None)
                    if conn:
                        conn.execute("DELETE FROM sales")
                        conn.commit()
                    else:
                        raise RuntimeError("Método delete_all_sales_history não encontrado no provider.")
                # Log da ação
                app = App.get_running_app()
                username = getattr(app, "current_user", None)
                role     = getattr(app, "current_role", None) or "manager"
                if username:
                    try:
                        self.db.log_action(username, role, "DELETE_ALL_SALES_HISTORY",
                                           "Histórico de vendas eliminado pelo utilizador.")
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

    # ── Diálogo de remoção de item ────────────────────────────────────────────
    def open_refund_dialog(self, sale_data):
        available = float(sale_data.get("available_qty", 0) or 0)
        if available <= 0:
            self._show_msg("Remover item", "Esta venda não tem saldo para remover.")
            return

        sale_id      = sale_data.get("sale_id")
        product      = sale_data.get("product") or "Produto"
        qty          = float(sale_data.get("qty", 0) or 0)
        returned_qty = float(sale_data.get("returned_qty", 0) or 0)
        price        = float(sale_data.get("price", 0) or 0)

        content = MDBoxLayout(
            orientation="vertical", spacing=dp(10),
            padding=[dp(8), dp(4)], size_hint_y=None,
        )
        content.bind(minimum_height=content.setter("height"))
        content.add_widget(MDLabel(
            text=(
                f"Venda #{sale_id} — {product}\n"
                f"Vendido: {self._fmt_qty(qty)}  |  Removido: {self._fmt_qty(returned_qty)}"
                f"  |  Disponível: {self._fmt_qty(available)}\n"
                f"Preço unitário: {self._fmt_cur(price)} MT"
            ),
            theme_text_color="Secondary",
            size_hint_y=None, height=dp(72),
        ))
        qty_input = MDTextField(
            hint_text="Quantidade para remover",
            input_filter="float", mode="rectangle",
            text=f"{available:.2f}", size_hint_y=None, height=dp(48),
        )
        reason_input = MDTextField(
            hint_text="Motivo", mode="rectangle",
            text="Item lançado por engano", size_hint_y=None, height=dp(48),
        )
        content.add_widget(qty_input)
        content.add_widget(reason_input)

        cancel_btn  = MDFlatButton(text="CANCELAR")
        confirm_btn = MDRaisedButton(text="CONFIRMAR")
        dialog = MDDialog(
            title="Remover Item da Venda", type="custom",
            content_cls=content, buttons=[cancel_btn, confirm_btn],
        )
        cancel_btn.bind(on_release=lambda _: dialog.dismiss())
        confirm_btn.bind(
            on_release=lambda _: self._submit_refund(
                dialog, sale_data, qty_input, reason_input, cancel_btn, confirm_btn,
            )
        )
        dialog.open()

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
        from kivymd.toast import toast
        if self._exporting:
            toast("Exportação já em curso.")
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
        toast("A gerar PDF…")

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
        }

    # ── Utilitário ────────────────────────────────────────────────────────────
    def _show_msg(self, title, message):
        dialog = MDDialog(
            title=title, text=message,
            buttons=[MDFlatButton(text="OK", on_release=lambda _: dialog.dismiss())],
        )
        dialog.open()
