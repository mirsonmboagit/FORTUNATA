import os
import sys
import unicodedata
from pathlib import Path
from collections import deque

from utils.config.paths import ROOT_DIR, report_search_dirs

sys.path.insert(
    0,
    str((ROOT_DIR / "pdfs").resolve())
)

from ui.components.native_widgets import (
    NativeBoxLayout as MDBoxLayout,
    NativeButton as MDRaisedButton,
    NativeCard as MDCard,
    NativeDatePicker as MDDatePicker,
    NativeDialog as MDDialog,
    NativeDropdownMenu as MDDropdownMenu,
    NativeFlatButton as MDFlatButton,
    NativeGridLayout as MDGridLayout,
    NativeIcon as MDIcon,
    NativeLabel as MDLabel,
    NativeListItem as OneLineListItem,
    NativeScreen as MDScreen,
    NativeSeparator as MDSeparator,
    NativeTextField as MDTextField,
)
from AI.controller import ProactiveIntelligenceController

from datetime import datetime, timedelta
from threading import Thread
from time import perf_counter
from kivy.metrics import dp, sp
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.app import App
from kivy.animation import Animation
from kivy.lang import Builder
from kivy.properties import ObjectProperty, StringProperty

from database.provider import get_db
from ui.components.hover_widgets import HoverCard, HoverRaisedButton
from ui.components.loading_overlay import ScreenLoadingController
from ui.components.tooltip_widgets import set_attention_shake
from utils.business.expiry_alerts import evaluate_expiry_alert
from utils.core.focus_navigation import FormKeyboardController
from utils.core.perf_utils import perf_start, perf_log


def _theme_color(name, fallback):
    app = App.get_running_app()
    tokens = getattr(app, "theme_tokens", {}) if app else {}
    return tokens.get(name, fallback)


Builder.load_file(str(Path(__file__).with_name("reports_screen.kv")))


# ---------------------------------------------------------------------------
# DateRangeDialog  (sem alterações de comportamento)
# ---------------------------------------------------------------------------

class DateRangeDialog(MDDialog):
    """Dialog para seleção manual de intervalo de datas."""

    def __init__(self, callback, database, **kwargs):
        self.callback = callback
        self.database = database
        content = self._create_content()
        super().__init__(
            title="Selecionar período",
            type="custom",
            content_cls=content,
            size_hint=(None, None),
            size=(min(dp(560), Window.width * 0.92), min(dp(520), Window.height * 0.82)),
            buttons=[
                MDFlatButton(text="CANCELAR", on_release=lambda x: self.dismiss()),
                MDRaisedButton(
                    text="CONFIRMAR PERÍODO",
                    md_bg_color=_theme_color('success', (0.2, 0.65, 0.33, 1)),
                    on_release=lambda x: self.confirm(),
                ),
            ],
            **kwargs,
        )
        Window.bind(on_resize=self.reposition)
        self._field_navigation = FormKeyboardController(
            host=self,
            fields=[self.start_date_field, self.end_date_field],
            initial_field=self.start_date_field,
            on_escape=self.dismiss,
            on_submit=self.confirm,
            shortcuts={"ctrl+s": self.confirm},
        )

    def _create_content(self):
        main_layout = MDBoxLayout(
            orientation='vertical',
            spacing=dp(15),
            size_hint_y=None,
            padding=[dp(10), dp(10)],
        )
        main_layout.bind(minimum_height=main_layout.setter('height'))

        main_layout.add_widget(MDLabel(
            text='Defina o intervalo de datas para o relatorio',
            font_style='Caption',
            halign='left',
            theme_text_color='Custom',
            text_color=_theme_color('text_secondary', (0.5, 0.5, 0.5, 1)),
            size_hint_y=None,
            height=dp(20),
        ))

        self.start_date_field = MDTextField(
            hint_text="Data Inicial (DD/MM/AAAA)",
            mode="rectangle",
            size_hint_y=None,
            height=dp(52),
        )
        main_layout.add_widget(self.start_date_field)

        self.end_date_field = MDTextField(
            hint_text="Data Final (DD/MM/AAAA)",
            mode="rectangle",
            size_hint_y=None,
            height=dp(52),
        )
        main_layout.add_widget(self.end_date_field)

        main_layout.add_widget(MDLabel(
            text='Ou escolha um atalho rápido:',
            font_style='Subtitle2',
            bold=True,
            halign='left',
            theme_text_color='Custom',
            text_color=_theme_color('text_primary', (0.3, 0.3, 0.3, 1)),
            size_hint_y=None,
            height=dp(25),
        ))

        shortcuts_layout = MDGridLayout(
            cols=3, spacing=dp(8), size_hint_y=None, height=dp(90), adaptive_height=True,
        )
        for label, func in [
            ("Hoje", self.set_today),
            ("7 Dias", lambda: self.set_days(7)),
            ("30 Dias", lambda: self.set_days(30)),
            ("Este Mes", self.set_this_month),
            ("Este Ano", self.set_this_year),
        ]:
            shortcuts_layout.add_widget(MDRaisedButton(
                text=label,
                md_bg_color=_theme_color('card_alt', (0.98, 0.98, 0.98, 1)),
                text_color=_theme_color('warning', (0.8, 0.5, 0.15, 1)),
                elevation=0,
                size_hint_y=None,
                height=dp(40),
                on_release=lambda x, f=func: f(),
            ))
        main_layout.add_widget(shortcuts_layout)
        return main_layout

    def reposition(self, instance, width, height):
        if self.parent:
            self.size = (
                min(dp(560), max(dp(300), Window.width * 0.92)),
                min(dp(520), max(dp(300), Window.height * 0.82)),
            )

    def on_pre_open(self, *args):
        if hasattr(self, "_field_navigation"):
            self._field_navigation.activate(focus_initial=True)
        return super().on_pre_open(*args)

    def on_dismiss(self, *args):
        if hasattr(self, "_field_navigation"):
            self._field_navigation.deactivate()
        try:
            Window.unbind(on_resize=self.reposition)
        except Exception:
            pass
        return super().on_dismiss(*args)

    def set_today(self):
        today = datetime.now().strftime("%d/%m/%Y")
        self.start_date_field.text = today
        self.end_date_field.text = today

    def set_days(self, days):
        end = datetime.now()
        start = end - timedelta(days=days)
        self.start_date_field.text = start.strftime("%d/%m/%Y")
        self.end_date_field.text = end.strftime("%d/%m/%Y")

    def set_this_month(self):
        today = datetime.now()
        start = datetime(today.year, today.month, 1)
        self.start_date_field.text = start.strftime("%d/%m/%Y")
        self.end_date_field.text = today.strftime("%d/%m/%Y")

    def set_this_year(self):
        today = datetime.now()
        self.start_date_field.text = datetime(today.year, 1, 1).strftime("%d/%m/%Y")
        self.end_date_field.text = today.strftime("%d/%m/%Y")

    def confirm(self):
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
        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(10),
            padding=[dp(6), dp(4)],
            size_hint_y=None,
            height=dp(100),
        )
        lbl = MDLabel(
            text=str(message or ""),
            theme_text_color="Custom",
            text_color=_theme_color('text_secondary', (0.7, 0.72, 0.76, 1)),
            font_style="Body2",
            halign="left",
            size_hint_y=None,
            text_size=(dp(360), None),
        )
        lbl.bind(
            texture_size=lambda inst, val: setattr(inst, "height", max(dp(40), val[1] + dp(4))),
            width=lambda inst, val: setattr(inst, "text_size", (max(dp(200), val - dp(8)), None)),
        )
        content.add_widget(lbl)
        content.bind(minimum_height=content.setter("height"))
        d = MDDialog(
            title="Verifique as datas",
            type="custom",
            content_cls=content,
            buttons=[MDRaisedButton(
                text="ENTENDI",
                md_bg_color=_theme_color('danger', (0.85, 0.3, 0.3, 1)),
                text_color=_theme_color('on_primary', (1, 1, 1, 1)),
                on_release=lambda x: d.dismiss(),
            )],
            size_hint=(None, None),
            size=(min(dp(440), max(dp(300), Window.width * 0.88)), dp(220)),
        )
        d.open()


# ---------------------------------------------------------------------------
# ReportsScreen
# ---------------------------------------------------------------------------

class ReportsScreen(MDScreen):
    """
    Tela principal de geração de relatórios.

    Mudanças vs versão anterior
    ───────────────────────────
    • Sem calendário automático — validate_filters() apenas mostra aviso ao
      utilizador; o calendário só abre se ele clicar em "Selecionar Periodo".
    • Filtros carregados com delay de 0.5 s após on_enter, sem bloquear a UI.
    • Geradores de PDF carregados sob demanda, não no on_kv_post.
    • Produtividade nunca carregada automaticamente na abertura.
    • Layout responsivo continua funcional mas mais leve (altura fixa no .kv).
    • ai_banner_container mantido no .kv para o historico de avisos.
    """

    FILTERS_CACHE_SECONDS = 60
    PRODUCTIVITY_CACHE_SECONDS = 15
    PDF_SCAN_CACHE_SECONDS = 8
    PDF_INITIAL_RENDER_LIMIT = 12
    PDF_RENDER_PAGE_SIZE = 12
    PDF_RENDER_BATCH_SIZE = 3
    PDF_TYPE_LABELS = {
        "etiquetas_codigos_barras": "Etiquetas de Codigos de Barras",
        "graficos_produtividade": "Graficos de Produtividade",
        "historico_vendas": "Historico de Vendas",
        "lista_de_compras": "Sugestões de Compras",
        "movimentos_stock": "Movimentos de Stock",
        "relatorio_caixa_usuarios": "Relatório de Caixa por Utilizador",
        "relatorio_completo": "Relatorio Completo",
        "relatorio_estoque": "Relatorio de Estoque",
        "relatorio_logs": "Relatorio de Logs",
        "relatorio_lucro": "Relatorio de Lucro",
        "relatorio_perdas": "Relatorio de Perdas",
        "relatorio_vendas": "Relatorio de Vendas",
    }
    REPORT_CARD_SEARCH = (
        ("sales_report_card",
         "relatorio vendas venda faturamento receita desempenho saida ticket"),
        ("stock_report_card",
         "relatorio estoque stock inventario niveis quantidades reposicao ruptura"),
        ("profit_report_card",
         "relatorio lucro margem rentabilidade ganhos resultados financeiro"),
        ("complete_report_card",
         "relatorio completo geral panorama executivo resumo analise total"),
        ("cash_user_report_card",
         "relatorio caixa usuarios utilizadores abertura fechamento fecho operador terminal"),
    )
    REPORT_BUTTON_LABELS = {
        "sales_report_card": "Vendas",
        "stock_report_card": "Estoque",
        "profit_report_card": "Lucro",
        "complete_report_card": "Completo",
        "cash_user_report_card": "Caixa por utilizador",
    }

    date_label = ObjectProperty(None)
    product_spinner = ObjectProperty(None)
    category_spinner = ObjectProperty(None)
    seller_spinner = ObjectProperty(None)
    search_status_text = StringProperty(
        "Pesquise por tipo de relatorio, produto ou categoria."
    )
    search_summary_text = StringProperty("5 relatorios prontos para gerar em PDF.")
    period_summary_text = StringProperty("Escolha um periodo")
    product_summary_text = StringProperty("Todos os Produtos")
    category_summary_text = StringProperty("Todas as Categorias")
    seller_summary_text = StringProperty("Todos os Vendedores")

    def __init__(self, **kwargs):
        db = kwargs.pop("db", None)
        self.db = db or get_db()
        self.back_target = "admin_home"
        self.notification_count = 0
        self.recommendation_count = 0
        self.start_date = None
        self.end_date = None
        self.selected_product = None
        self.selected_category = None
        self.selected_seller = None
        self._ai_poll_ev = None
        self._filters_loading = False
        self._filters_loaded = False
        self._filters_last_loaded_at = 0.0
        self._filters_load_ev = None
        self._filters_load_token = 0
        self._productivity_dashboard = None
        self._productivity_payload = None
        self._productivity_error = None
        self._productivity_loading = False
        self._productivity_last_loaded_at = 0.0
        self._productivity_load_token = 0
        self._responsive_ev = None
        self._search_ev = None
        self._pending_search = ""
        self._date_picker = None
        self._pending_report_callback = None
        self._report_generation_busy = False
        self._active_report_button_id = None
        self._printing_charts_busy = False
        self._loading_controller = None
        # Geradores de relatório: carregados sob demanda
        self.sales_report = None
        self.stock_report = None
        self.profit_report = None
        self.complete_report = None
        self.productivity_charts_report = None
        self.cash_user_report = None
        self.pdf_viewer = None
        # Menus dropdown
        self.product_menu = None
        self.category_menu = None
        self.seller_menu = None
        self._product_menu_signature = ()
        self._category_menu_signature = ()
        self._seller_menu_signature = ()
        self.products_list = ['Todos os Produtos']
        self.categories_list = ['Todas as Categorias']
        self.sellers_list = ['Todos os Vendedores']
        self.filtered_products_list = list(self.products_list)
        self.filtered_categories_list = list(self.categories_list)
        self.filtered_sellers_list = list(self.sellers_list)
        self._report_card_ids = [card_id for card_id, _ in self.REPORT_CARD_SEARCH]
        self._report_cards_by_id = {}
        # Dialogs
        self.date_dialog = None
        self.error_dialog = None
        self.success_dialog = None
        self.pdf_dialog = None
        self.delete_pdf_dialog = None
        self._pdf_list_token = 0
        self._pdf_loading = False
        self._pdf_all_files = []
        self._pdf_filtered_files = []
        self._pdf_file_meta = {}
        self._pdf_scan_cache = []
        self._pdf_scan_cache_at = 0.0
        self._pdf_visible_limit = self.PDF_INITIAL_RENDER_LIMIT
        self._pdf_type_filter = None
        self._pdf_render_ev = None
        self._pdf_pending_items = deque()
        self._pdf_list_container = None
        self._pdf_count_label = None
        self._pdf_status_label = None
        self._pdf_selector_button = None
        self._pdf_selector_menu = None
        self._pdf_delete_filtered_button = None
        self._pdf_load_more_button = None
        self._pdf_dialog_body = None
        self._pdf_dialog_scroll = None
        super().__init__(**kwargs)
        self._intelligence = ProactiveIntelligenceController(
            screen=self,
            db=self.db,
            history_title="Historico de avisos dos relatorios",
            auto_present_enabled=False,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_kv_post(self, base_widget):
        """Inicialização mínima — apenas o que é visível imediatamente."""
        self._ensure_loading_overlay()
        self._ensure_productivity_dashboard()
        self.bind(size=lambda *_: self._schedule_responsive_layout())
        Clock.schedule_once(lambda dt: self._cache_report_cards(), 0)
        Clock.schedule_once(lambda dt: self._refresh_filter_summary(), 0)
        Clock.schedule_once(lambda dt: self._apply_search_now(), 0)
        # Layout responsivo com pequeno delay para não competir com o render
        Clock.schedule_once(lambda dt: self._schedule_responsive_layout(), 0.05)

    def on_enter(self):
        """Chamado quando a tela é exibida."""
        self._refresh_date_label()
        self._refresh_filter_summary()
        self._apply_search_now()
        # Renderiza o dashboard (vazio se não há período — sem carregar dados)
        Clock.schedule_once(lambda dt: self._render_productivity_dashboard(), 0)
        # Filtros com delay para não travar a transição de entrada
        Clock.schedule_once(lambda dt: self._ensure_filters_loaded(), 0.5)
        Clock.schedule_once(self._init_badge, 0.1)
        Clock.schedule_once(lambda dt: self._start_ai_polling(), 0.2)

    def on_leave(self):
        self._stop_ai_polling()
        self._productivity_load_token += 1
        self._filters_load_token += 1
        self._pdf_list_token += 1
        self._productivity_loading = False
        self._clear_loading_overlay()
        for menu in (self.product_menu, self.category_menu, self.seller_menu, self._pdf_selector_menu):
            try:
                if menu:
                    menu.dismiss()
            except Exception:
                pass
        for dialog in (self.date_dialog, self.error_dialog, self.success_dialog, self.delete_pdf_dialog, self.pdf_dialog):
            try:
                if dialog:
                    dialog.dismiss()
            except Exception:
                pass
        for ev in ("_filters_load_ev", "_responsive_ev", "_search_ev"):
            evt = getattr(self, ev, None)
            if evt:
                evt.cancel()
            setattr(self, ev, None)

    # ------------------------------------------------------------------
    # Loading overlay
    # ------------------------------------------------------------------

    def _ensure_loading_overlay(self):
        if self._loading_controller is None:
            self._loading_controller = ScreenLoadingController(self)
        self._loading_controller.attach()
        return self._loading_controller

    def _set_loading_overlay(self, key, active, message="", detail=""):
        ctrl = self._ensure_loading_overlay()
        if active:
            ctrl.show(key, message, detail)
        else:
            ctrl.hide(key)

    def _clear_loading_overlay(self):
        if self._loading_controller is not None:
            self._loading_controller.clear()

    # ------------------------------------------------------------------
    # Helpers estáticos
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_search_text(text):
        normalized = unicodedata.normalize("NFKD", str(text or ""))
        return "".join(c for c in normalized if not unicodedata.combining(c)).strip().lower()

    @staticmethod
    def _truncate_text(text, limit=34):
        value = str(text or "").strip()
        if len(value) <= limit:
            return value or "-"
        return value[: max(limit - 3, 1)].rstrip() + "..."

    # ------------------------------------------------------------------
    # Report cards
    # ------------------------------------------------------------------

    def _cache_report_cards(self):
        if not hasattr(self, "ids"):
            return
        self._report_cards_by_id = {
            card_id: self.ids.get(card_id)
            for card_id in self._report_card_ids
            if self.ids.get(card_id) is not None
        }
        self._render_report_cards(self._report_card_ids)

    def _set_report_generation_busy(self, busy, button_id=None, status_text=None):
        self._report_generation_busy = bool(busy)
        self._active_report_button_id = button_id if self._report_generation_busy else None
        if self._report_generation_busy:
            report_label = self.REPORT_BUTTON_LABELS.get(button_id, "Relatorio")
            self._set_loading_overlay(
                "report_generation", True,
                f"A gerar {report_label.lower()}...",
                "A preparar o PDF do periodo selecionado.",
            )
        else:
            self._set_loading_overlay("report_generation", False)
        for card_id, default_text in self.REPORT_BUTTON_LABELS.items():
            button = self._report_cards_by_id.get(card_id) or (
                self.ids.get(card_id) if hasattr(self, "ids") else None
            )
            if button is None:
                continue
            button.disabled = self._report_generation_busy
            if self._report_generation_busy and card_id == button_id:
                button.text = status_text or "A gerar..."
            else:
                button.text = default_text

    def _set_print_charts_busy(self, busy):
        self._printing_charts_busy = bool(busy)
        if self._printing_charts_busy:
            self._set_loading_overlay(
                "print_charts", True,
                "A preparar os graficos para impressao...",
                "A preparar o PDF.",
            )
        else:
            self._set_loading_overlay("print_charts", False)
        button = self.ids.get("print_charts_button") if hasattr(self, "ids") else None
        if button is None:
            return
        button.disabled = self._printing_charts_busy
        button.text = "A preparar..." if self._printing_charts_busy else "Imprimir gráficos"

    @staticmethod
    def _report_config(report_kind):
        return {
            "sales": ("sales_report_card", "sales_report", "Relatório de vendas"),
            "stock": ("stock_report_card", "stock_report", "Relatório de estoque"),
            "profit": ("profit_report_card", "profit_report", "Relatório de lucro"),
            "complete": ("complete_report_card", "complete_report", "Relatório completo"),
        }.get(report_kind)

    # ------------------------------------------------------------------
    # Layout responsivo
    # ------------------------------------------------------------------

    def _schedule_responsive_layout(self, *args):
        if self._responsive_ev:
            self._responsive_ev.cancel()
        self._responsive_ev = Clock.schedule_once(lambda dt: self._update_responsive_layout(), 0)

    def _update_responsive_layout(self):
        self._responsive_ev = None
        if not hasattr(self, "ids") or not self.ids:
            return
        width = float(self.width or Window.width or 1200)
        narrow = width < dp(720)
        medium = width < dp(980)

        ids = self.ids
        reports_grid = ids.get("reports_grid")
        quick_range = ids.get("quick_range_grid")
        filters_grid = ids.get("filters_grid")
        period_row = ids.get("period_row")
        search_row = ids.get("search_row")
        filter_actions = ids.get("filter_actions")
        content = ids.get("reports_content")
        print_btn = ids.get("print_charts_button")
        search_clear = ids.get("search_clear_button")

        if reports_grid is not None:
            if narrow:
                reports_grid.cols = 1
            elif medium:
                reports_grid.cols = 2
            else:
                reports_grid.cols = 3
            try:
                reports_grid.height = reports_grid.minimum_height
            except Exception:
                pass

        if quick_range is not None:
            if narrow:
                quick_range.cols = 2
                quick_range.height = dp(88)
            elif medium:
                quick_range.cols = 3
                quick_range.height = dp(88)
            else:
                quick_range.cols = 5
                quick_range.height = dp(40)

        if filters_grid is not None:
            filters_grid.cols = 1 if narrow else 2
            filters_grid.height = dp(140) if narrow else dp(64)

        if period_row is not None:
            period_row.orientation = "vertical" if narrow else "horizontal"
            period_row.height = dp(96) if narrow else dp(48)

        if search_row is not None:
            search_row.orientation = "vertical" if narrow else "horizontal"
            search_row.height = dp(100) if narrow else dp(48)
        if search_clear is not None:
            search_clear.size_hint_x = 1 if narrow else None
            if not narrow:
                search_clear.width = dp(100)

        if filter_actions is not None:
            filter_actions.orientation = "vertical" if narrow else "horizontal"
            filter_actions.height = dp(92) if narrow else dp(42)

        if content is not None:
            pad = dp(12) if narrow else dp(16)
            content.padding = [pad, dp(12), pad, dp(96)]

        if print_btn is not None:
            print_btn.size_hint_x = 1 if narrow else None
            if not narrow:
                print_btn.width = dp(180)


    def _refresh_filter_summary(self):
        if self.start_date and self.end_date:
            self.period_summary_text = (
                f"{self.start_date.strftime('%d/%m/%Y')} a {self.end_date.strftime('%d/%m/%Y')}"
            )
        else:
            self.period_summary_text = "Escolha um periodo"

        product_text = "Todos os Produtos"
        category_text = "Todas as Categorias"
        seller_text = "Todos os Vendedores"
        if hasattr(self, "product_spinner") and self.product_spinner:
            product_text = self.product_spinner.text
        elif hasattr(self, "ids") and "product_spinner" in self.ids:
            product_text = self.ids.product_spinner.text
        if hasattr(self, "category_spinner") and self.category_spinner:
            category_text = self.category_spinner.text
        elif hasattr(self, "ids") and "category_spinner" in self.ids:
            category_text = self.ids.category_spinner.text
        if hasattr(self, "seller_spinner") and self.seller_spinner:
            seller_text = self.seller_spinner.text
        elif hasattr(self, "ids") and "seller_spinner" in self.ids:
            seller_text = self.ids.seller_spinner.text

        self.product_summary_text = self._truncate_text(product_text, limit=36)
        self.category_summary_text = self._truncate_text(category_text, limit=36)
        self.seller_summary_text = self._truncate_text(seller_text, limit=36)

    # ------------------------------------------------------------------
    # Pesquisa
    # ------------------------------------------------------------------

    def on_search(self, text):
        self._pending_search = text or ""
        if self._search_ev:
            self._search_ev.cancel()
        self._search_ev = Clock.schedule_once(lambda dt: self._apply_search_now(), 0.28)

    def on_search_enter(self):
        if self._search_ev:
            self._search_ev.cancel()
            self._search_ev = None
        self._apply_search_now()

    def clear_search(self):
        if hasattr(self, "ids") and "report_search_input" in self.ids:
            self.ids.report_search_input.text = ""
        self._pending_search = ""
        if self._search_ev:
            self._search_ev.cancel()
            self._search_ev = None
        self._apply_search_now()

    def reset_filters(self):
        self.start_date = None
        self.end_date = None
        self.selected_product = None
        self.selected_category = None
        self.selected_seller = None
        self._productivity_error = None
        self._productivity_loading = False
        self._productivity_payload = None
        self._productivity_last_loaded_at = 0.0
        if hasattr(self, "product_spinner") and self.product_spinner:
            self.product_spinner.text = "Todos os Produtos"
        if hasattr(self, "category_spinner") and self.category_spinner:
            self.category_spinner.text = "Todas as Categorias"
        if hasattr(self, "seller_spinner") and self.seller_spinner:
            self.seller_spinner.text = "Todos os Vendedores"
        self.clear_search()
        self._refresh_date_label()
        self._refresh_filter_summary()
        self._render_productivity_dashboard()

    def refresh_screen_data(self):
        self._ensure_filters_loaded(force=True)
        self._ensure_productivity_loaded(force=True)
        self._apply_search_now()

    # ------------------------------------------------------------------
    # Atalhos de período
    # ------------------------------------------------------------------

    def apply_today_range(self):
        today = datetime.now()
        self.set_date_range(
            today.replace(hour=0, minute=0, second=0, microsecond=0),
            today.replace(hour=23, minute=59, second=59, microsecond=0),
        )

    def apply_last_days_range(self, days):
        today = datetime.now()
        end = today.replace(hour=23, minute=59, second=59, microsecond=0)
        start = (today - timedelta(days=max(int(days) - 1, 0))).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        self.set_date_range(start, end)

    def apply_current_month_range(self):
        today = datetime.now()
        self.set_date_range(
            datetime(today.year, today.month, 1),
            today.replace(hour=23, minute=59, second=59, microsecond=0),
        )

    def apply_current_year_range(self):
        today = datetime.now()
        self.set_date_range(
            datetime(today.year, 1, 1),
            today.replace(hour=23, minute=59, second=59, microsecond=0),
        )

    # ------------------------------------------------------------------
    # Seleção de datas — SEM calendário automático
    # ------------------------------------------------------------------

    def _clear_pending_report_callback(self):
        self._pending_report_callback = None

    def _on_date_picker_cancel(self, *args):
        self._date_picker = None
        self._clear_pending_report_callback()

    def _on_date_picker_save(self, instance, value, date_range):
        self._date_picker = None
        selected_range = [d for d in (date_range or []) if d is not None]
        if selected_range:
            start_date, end_date = min(selected_range), max(selected_range)
        elif value is not None:
            start_date = end_date = value
        else:
            self._clear_pending_report_callback()
            return
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time()).replace(microsecond=0)
        self.set_date_range(start_dt, end_dt)
        callback = self._pending_report_callback
        self._clear_pending_report_callback()
        if callable(callback):
            Clock.schedule_once(lambda dt: callback(), 0)

    def _build_date_picker_kwargs(self):
        base = datetime.now().date()
        kwargs = {"mode": "range", "year": base.year, "month": base.month, "day": base.day}
        if self.start_date and self.end_date:
            s = self.start_date.date()
            kwargs.update(year=s.year, month=s.month, day=s.day)
            if s < self.end_date.date():
                kwargs["min_date"] = s
                kwargs["max_date"] = self.end_date.date()
        return kwargs

    def select_date_range(self, on_complete=None):
        """Abre o seletor de intervalo compatível com os widgets nativos da aplicação.

        A implementação anterior tentava passar ``mode="range"`` para
        ``NativeDatePicker``. Esse widget é um ``ModalView`` sem uma
        propriedade Kivy ``mode`` e, por isso, o Kivy interrompia a aplicação
        durante o clique em "Selecionar Período".

        O ``DateRangeDialog`` já existente foi feito especificamente para
        intervalo de datas, possui validação DD/MM/AAAA, atalhos e é
        responsivo. Usá-lo aqui evita depender da API de outra versão do
        DatePicker e mantém a seleção de intervalo completa.
        """
        self._pending_report_callback = on_complete if callable(on_complete) else None

        if self.date_dialog is not None:
            try:
                self.date_dialog.dismiss()
            except Exception:
                pass
            self.date_dialog = None

        def apply_range(start, end):
            self.set_date_range(start, end)
            callback = self._pending_report_callback
            self._clear_pending_report_callback()
            self.date_dialog = None
            if callable(callback):
                Clock.schedule_once(lambda _dt: callback(), 0)

        dialog = DateRangeDialog(
            callback=apply_range,
            database=self.db,
        )

        # Reaproveita o período atualmente selecionado, quando existir.
        if self.start_date is not None:
            dialog.start_date_field.text = self.start_date.strftime("%d/%m/%Y")
        if self.end_date is not None:
            dialog.end_date_field.text = self.end_date.strftime("%d/%m/%Y")

        self.date_dialog = dialog
        dialog.open()

    def set_date_range(self, start, end):
        self.start_date = start
        self.end_date = end
        self._refresh_date_label()
        self._refresh_filter_summary()
        self._ensure_productivity_loaded(force=True)

    def _refresh_date_label(self, *args):
        label = None
        if hasattr(self, 'date_label') and self.date_label:
            label = self.date_label
        elif hasattr(self, 'ids') and 'date_label' in self.ids:
            label = self.ids.date_label
        if not label:
            Clock.schedule_once(self._refresh_date_label, 0)
            return
        if self.start_date and self.end_date:
            label.text = f"{self.start_date.strftime('%d/%m/%Y')} ate {self.end_date.strftime('%d/%m/%Y')}"
            label.text_color = _theme_color('text_primary', (0.2, 0.2, 0.2, 1))
        else:
            label.text = "Nenhum periodo selecionado"
            label.text_color = _theme_color('text_secondary', (0.5, 0.5, 0.5, 1))
        self._refresh_filter_summary()

    # ------------------------------------------------------------------
    # Validação — NUNCA abre o calendário automaticamente
    # ------------------------------------------------------------------

    def validate_filters(self, on_missing_period=None):
        """
        Retorna True se há período selecionado.

        Se não há período, abre um diálogo interativo onde o utilizador pode
        escolher o intervalo (atalhos rápidos ou período personalizado) em
        vez de apenas ler um aviso de texto.
        """
        if not self.start_date or not self.end_date:
            self._show_period_required_dialog(on_selected=on_missing_period)
            return False
        return True

    def _show_period_required_dialog(self, on_selected=None):
        """Diálogo interativo: escolher período antes de gerar o relatório."""
        if self.error_dialog:
            try:
                self.error_dialog.dismiss()
            except Exception:
                pass
            self.error_dialog = None

        tokens_fg = _theme_color('text_primary', (0.92, 0.94, 0.97, 1))
        tokens_muted = _theme_color('text_secondary', (0.55, 0.58, 0.63, 1))
        icon_color = _theme_color('warning', (0.9, 0.7, 0.15, 1))
        card_alt = _theme_color('card_alt', (0.16, 0.18, 0.22, 1))
        warning = _theme_color('warning', (0.9, 0.55, 0.12, 1))
        primary = _theme_color('primary', (0.15, 0.52, 0.76, 1))
        success = _theme_color('success', (0.2, 0.65, 0.33, 1))
        info = _theme_color('info', (0.28, 0.47, 0.84, 1))
        on_primary = _theme_color('on_primary', (1, 1, 1, 1))
        divider = _theme_color('divider', (1, 1, 1, 0.12))

        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(12),
            padding=[dp(6), dp(4), dp(6), dp(2)],
            size_hint_y=None,
        )
        content.bind(minimum_height=content.setter("height"))

        # Cabeçalho
        header = MDBoxLayout(size_hint_y=None, height=dp(28), spacing=dp(8))
        header.add_widget(MDIcon(
            icon="calendar-range",
            theme_text_color="Custom",
            text_color=icon_color,
            size_hint=(None, None),
            size=(dp(24), dp(24)),
        ))
        header.add_widget(MDLabel(
            text="Selecione um período",
            bold=True,
            font_style="Body1",
            theme_text_color="Custom",
            text_color=tokens_fg,
            valign="middle",
        ))
        content.add_widget(header)

        body = MDLabel(
            text=(
                "É necessário definir o intervalo de datas antes de gerar "
                "o relatório. Escolha um atalho ou abra o seletor completo."
            ),
            theme_text_color="Custom",
            text_color=tokens_muted,
            font_style="Body2",
            halign="left",
            valign="top",
            size_hint_y=None,
            text_size=(dp(400), None),
        )
        body.bind(
            texture_size=lambda inst, val: setattr(inst, "height", max(dp(40), val[1] + dp(4))),
            width=lambda inst, val: setattr(inst, "text_size", (max(dp(200), val - dp(8)), None)),
        )
        content.add_widget(body)

        # Separador visual
        sep = Widget(size_hint_y=None, height=dp(1))
        with sep.canvas:
            from kivy.graphics import Color, Rectangle
            Color(rgba=divider)
            sep._rect = Rectangle(pos=sep.pos, size=sep.size)
        sep.bind(
            pos=lambda inst, *_: setattr(inst._rect, "pos", inst.pos),
            size=lambda inst, *_: setattr(inst._rect, "size", inst.size),
        )
        content.add_widget(sep)

        content.add_widget(MDLabel(
            text="Atalhos rápidos",
            bold=True,
            font_style="Caption",
            theme_text_color="Custom",
            text_color=tokens_muted,
            size_hint_y=None,
            height=dp(20),
        ))

        shortcuts = MDGridLayout(
            cols=3,
            spacing=dp(8),
            size_hint_y=None,
            height=dp(92),
        )

        def _pick(action):
            def _handler(_btn):
                action()
                dlg = getattr(self, "error_dialog", None)
                if dlg:
                    dlg.dismiss()
                    self.error_dialog = None
                if callable(on_selected):
                    Clock.schedule_once(lambda _dt: on_selected(), 0.05)
            return _handler

        shortcut_defs = [
            ("Hoje", warning, self.apply_today_range),
            ("7 dias", primary, lambda: self.apply_last_days_range(7)),
            ("30 dias", success, lambda: self.apply_last_days_range(30)),
            ("Este mês", info, self.apply_current_month_range),
            ("Este ano", primary, self.apply_current_year_range),
        ]
        for label, color, action in shortcut_defs:
            btn = MDRaisedButton(
                text=label,
                size_hint_y=None,
                height=dp(40),
                elevation=0,
                md_bg_color=card_alt,
                text_color=color,
                on_release=_pick(action),
            )
            shortcuts.add_widget(btn)
        content.add_widget(shortcuts)

        # Botão período personalizado
        custom_btn = MDRaisedButton(
            text="Período personalizado…",
            size_hint_y=None,
            height=dp(42),
            elevation=0,
            md_bg_color=primary,
            text_color=on_primary,
            on_release=lambda _x: self._open_custom_period_from_dialog(on_selected),
        )
        content.add_widget(custom_btn)

        self.error_dialog = MDDialog(
            title="",
            type="custom",
            content_cls=content,
            size_hint=(None, None),
            size=(min(dp(480), max(dp(320), Window.width * 0.90)), dp(360)),
            buttons=[
                MDFlatButton(
                    text="CANCELAR",
                    text_color=tokens_muted,
                    on_release=lambda _x: self.error_dialog.dismiss() if self.error_dialog else None,
                ),
            ],
        )

        def _fit(*_a):
            try:
                h = max(dp(320), float(content.height) + dp(90))
                self.error_dialog.height = min(h, max(dp(280), Window.height * 0.75))
                self.error_dialog.width = min(dp(500), max(dp(320), Window.width * 0.90))
                content.width = self.error_dialog.width - dp(40)
            except Exception:
                pass

        Clock.schedule_once(_fit, 0)
        Clock.schedule_once(_fit, 0.05)
        self.error_dialog.open()

    def _open_custom_period_from_dialog(self, on_selected=None):
        """Fecha o aviso e abre o seletor completo de datas."""
        if self.error_dialog:
            try:
                self.error_dialog.dismiss()
            except Exception:
                pass
            self.error_dialog = None
        self.select_date_range(on_complete=on_selected)

    # ------------------------------------------------------------------
    # Filtros de produto / categoria
    # ------------------------------------------------------------------

    def _filter_options(self, items, default_item, query):
        source = list(items or [default_item])
        if not query:
            return source
        defaults = [i for i in source if i == default_item]
        filtered = [i for i in source if i != default_item
                    and query in self._normalize_search_text(i)]
        return defaults + filtered

    def update_product_selection(self, instance, text):
        if text == "Todos os Produtos":
            self.selected_product = None
        else:
            try:
                self.selected_product = int(text.split(" - ")[0])
            except (ValueError, IndexError):
                self.selected_product = None

    def update_category_selection(self, instance, text):
        self.selected_category = None if text == "Todas as Categorias" else text

    def update_seller_selection(self, instance, text):
        self.selected_seller = None if text == "Todos os Vendedores" else text

    # ------------------------------------------------------------------
    # Carregamento de filtros (lazy, em background)
    # ------------------------------------------------------------------

    def _ensure_filters_loaded(self, force=False):
        if self._filters_loading:
            return
        age = perf_counter() - self._filters_last_loaded_at
        if not force and self._filters_loaded and age < self.FILTERS_CACHE_SECONDS:
            return
        if self._filters_load_ev:
            self._filters_load_ev.cancel()
        self._filters_load_ev = Clock.schedule_once(lambda dt: self._load_filters_bg(), 0)

    def _load_filters_bg(self):
        """Carrega filtros em background sem mostrar overlay de loading."""
        self._filters_load_ev = None
        if self._filters_loading:
            return
        token = self._filters_load_token + 1
        self._filters_load_token = token
        self._filters_loading = True
        started_at = perf_start()

        def worker():
            products, categories, sellers, error = [], [], [], None
            try:
                products = self.db.get_products_for_filter() or []
                categories = self.db.get_categories() or []
                getter = getattr(self.db, "get_sales_users_for_filter", None)
                if callable(getter):
                    sellers = getter() or []
            except Exception as exc:
                error = exc
            Clock.schedule_once(
                lambda dt, p=products, c=categories, u=sellers, e=error, tok=token, s=started_at:
                    self._apply_loaded_filters(p, c, u, e, tok, s),
                0,
            )

        Thread(target=worker, daemon=True).start()

    # Mantém compatibilidade com prepare_open_from_admin
    def load_filters(self):
        self._load_filters_bg()

    def _apply_loaded_filters(self, products, categories, sellers, error, token, started_at):
        if token != self._filters_load_token:
            return
        try:
            if error:
                print(f"Erro ao carregar filtros: {error}")
                return
            new_products = ['Todos os Produtos'] + [
                f"{p[0]} - {p[1]}" for p in (products or [])
            ]
            new_categories = ['Todas as Categorias'] + list(categories or [])
            new_sellers = ['Todos os Vendedores'] + [
                str(s[0] if isinstance(s, (list, tuple)) else s).strip()
                for s in (sellers or [])
                if str(s[0] if isinstance(s, (list, tuple)) else s).strip()
            ]
            if new_products != self.products_list:
                self.products_list = new_products
                self.filtered_products_list = list(new_products)
                self._invalidate_product_menu()
            if new_categories != self.categories_list:
                self.categories_list = new_categories
                self.filtered_categories_list = list(new_categories)
                self._invalidate_category_menu()
            if new_sellers != self.sellers_list:
                self.sellers_list = new_sellers
                self.filtered_sellers_list = list(new_sellers)
                self._invalidate_seller_menu()
            self._filters_loaded = True
            self._filters_last_loaded_at = perf_counter()
            self._refresh_filter_summary()
            self._apply_search_now()
            perf_log(
                "reports.load_filters", started_at,
                f"products={len(self.products_list)} categories={len(self.categories_list)} sellers={len(self.sellers_list)}",
            )
        finally:
            self._filters_loading = False

    # ------------------------------------------------------------------
    # Menus dropdown (limitados para evitar menus enormes e bloqueio da UI)
    # ------------------------------------------------------------------

    MAX_DROPDOWN_ITEMS = 80
    _DROPDOWN_OVERFLOW_HINT = "… use a pesquisa acima para filtrar"

    def _menu_source(self, full_list, default_item):
        """Limita itens apresentados sem remover a opção padrão do topo."""
        source = list(full_list or [default_item])
        # Remove duplicados preservando a ordem; evita menus com linhas repetidas.
        source = list(dict.fromkeys(str(item) for item in source if str(item).strip()))
        if default_item not in source:
            source.insert(0, default_item)
        if len(source) <= self.MAX_DROPDOWN_ITEMS:
            return source
        rest = [item for item in source if item != default_item]
        return [default_item] + rest[:self.MAX_DROPDOWN_ITEMS - 2] + [self._DROPDOWN_OVERFLOW_HINT]

    def _focus_report_search(self):
        search = self.ids.get("report_search_input") if hasattr(self, "ids") else None
        if search is not None:
            Clock.schedule_once(lambda _dt: setattr(search, "focus", True), 0.05)

    def open_product_menu(self, item):
        self._ensure_product_menu(item)
        if self.product_menu:
            self.product_menu.open()

    def select_product(self, product_name):
        if product_name == self._DROPDOWN_OVERFLOW_HINT:
            self._dismiss_menu("product_menu")
            self._focus_report_search()
            return
        spinner = getattr(self, "product_spinner", None) or (self.ids.get("product_spinner") if hasattr(self, "ids") else None)
        if spinner is not None:
            spinner.text = product_name
        self._dismiss_menu("product_menu")
        self.update_product_selection(None, product_name)
        self._refresh_filter_summary()

    def open_category_menu(self, item):
        self._ensure_category_menu(item)
        if self.category_menu:
            self.category_menu.open()

    def select_category(self, category_name):
        if category_name == self._DROPDOWN_OVERFLOW_HINT:
            self._dismiss_menu("category_menu")
            self._focus_report_search()
            return
        spinner = getattr(self, "category_spinner", None) or (self.ids.get("category_spinner") if hasattr(self, "ids") else None)
        if spinner is not None:
            spinner.text = category_name
        self._dismiss_menu("category_menu")
        self.update_category_selection(None, category_name)
        self._refresh_filter_summary()

    def open_seller_menu(self, item):
        self._ensure_seller_menu(item)
        if self.seller_menu:
            self.seller_menu.open()

    def select_seller(self, seller_name):
        if seller_name == self._DROPDOWN_OVERFLOW_HINT:
            self._dismiss_menu("seller_menu")
            self._focus_report_search()
            return
        spinner = getattr(self, "seller_spinner", None) or (self.ids.get("seller_spinner") if hasattr(self, "ids") else None)
        if spinner is not None:
            spinner.text = seller_name
        self._dismiss_menu("seller_menu")
        self.update_seller_selection(None, seller_name)
        self._refresh_filter_summary()

    def _dismiss_menu(self, attr_name):
        menu = getattr(self, attr_name, None)
        if menu is not None:
            try:
                menu.dismiss()
            except Exception as exc:
                # O menu pode já ter sido fechado pela seleção/camada nativa.
                print(f"Aviso ao fechar menu {attr_name}: {exc}")
        setattr(self, attr_name, None)
        signature_name = "_" + attr_name.replace("_menu", "_menu_signature")
        if hasattr(self, signature_name):
            setattr(self, signature_name, ())

    def _invalidate_product_menu(self):
        self._dismiss_menu("product_menu")

    def _invalidate_category_menu(self):
        self._dismiss_menu("category_menu")

    def _invalidate_seller_menu(self):
        self._dismiss_menu("seller_menu")

    def _ensure_product_menu(self, caller):
        source = self._menu_source(
            self.filtered_products_list or self.products_list,
            "Todos os Produtos",
        )
        sig = tuple(source)
        if self.product_menu is not None and self._product_menu_signature == sig:
            self.product_menu.caller = caller
            return
        self._invalidate_product_menu()
        self._product_menu_signature = sig
        self.product_menu = MDDropdownMenu(
            caller=caller,
            items=[{
                "text": product,
                "viewclass": "OneLineListItem",
                "height": dp(42),
                "size_hint_y": None,
                "on_release": (lambda value=product: self.select_product(value)),
            } for product in source],
            # 8 unidades (~448dp): evita que os nomes dos produtos quebrem
            # em várias linhas e mantém o menu próximo da largura do campo.
            width_mult=8,
            max_height=min(dp(320), max(dp(180), Window.height * 0.40)),
        )

    def _ensure_category_menu(self, caller):
        source = self._menu_source(
            self.filtered_categories_list or self.categories_list,
            "Todas as Categorias",
        )
        sig = tuple(source)
        if self.category_menu is not None and self._category_menu_signature == sig:
            self.category_menu.caller = caller
            return
        self._invalidate_category_menu()
        self._category_menu_signature = sig
        self.category_menu = MDDropdownMenu(
            caller=caller,
            items=[{
                "text": category,
                "viewclass": "OneLineListItem",
                "height": dp(42),
                "size_hint_y": None,
                "on_release": (lambda value=category: self.select_category(value)),
            } for category in source],
            width_mult=8,
            max_height=min(dp(320), max(dp(180), Window.height * 0.40)),
        )

    def _ensure_seller_menu(self, caller):
        source = self._menu_source(
            self.filtered_sellers_list or self.sellers_list,
            "Todos os Vendedores",
        )
        sig = tuple(source)
        if self.seller_menu is not None and self._seller_menu_signature == sig:
            self.seller_menu.caller = caller
            return
        self._invalidate_seller_menu()
        self._seller_menu_signature = sig
        self.seller_menu = MDDropdownMenu(
            caller=caller,
            items=[{
                "text": seller,
                "viewclass": "OneLineListItem",
                "height": dp(42),
                "size_hint_y": None,
                "on_release": (lambda value=seller: self.select_seller(value)),
            } for seller in source],
            width_mult=8,
            max_height=min(dp(320), max(dp(180), Window.height * 0.40)),
        )

    # ------------------------------------------------------------------
    # Pesquisa — render de cards
    # ------------------------------------------------------------------

    def _get_matching_report_ids(self, query):
        if not query:
            return list(self._report_card_ids)
        return [
            card_id for card_id, terms in self.REPORT_CARD_SEARCH
            if query in self._normalize_search_text(terms)
        ]

    def _render_report_cards(self, card_ids):
        grid = self.ids.get("reports_grid") if hasattr(self, "ids") else None
        if grid is None or not self._report_cards_by_id:
            return 0
        grid.clear_widgets()
        for card_id in self._report_card_ids:
            if card_id not in card_ids:
                continue
            card = self._report_cards_by_id.get(card_id)
            if card:
                grid.add_widget(card)
        empty = self.ids.get("reports_empty_state")
        if empty:
            empty.size_hint_y = None
            empty.height = dp(112) if not card_ids else 0
            empty.opacity = 1 if not card_ids else 0
            empty.disabled = bool(card_ids)
        return len(card_ids)

    def _update_search_feedback(self, query, visible_ids, matched_ids,
                                product_matches, category_matches, seller_matches):
        total_products = max(len(product_matches) - 1, 0)
        total_categories = max(len(category_matches) - 1, 0)
        total_sellers = max(len(seller_matches) - 1, 0)
        raw_query = (self._pending_search or "").strip()
        if not query:
            self.search_status_text = "Pesquise por vendas, estoque, lucro, produto, categoria ou vendedor."
            self.search_summary_text = "5 relatorios prontos para gerar em PDF."
            return
        if not visible_ids and total_products == 0 and total_categories == 0 and total_sellers == 0:
            self.search_status_text = f"Nenhum resultado encontrado para \"{raw_query}\"."
            self.search_summary_text = "Ajuste a pesquisa para voltar a mostrar relatorios."
            return
        if matched_ids:
            self.search_status_text = (
                f"{len(matched_ids)} relatorio(s) encontrados, "
                f"{total_products} produto(s), {total_categories} categoria(s) e "
                f"{total_sellers} vendedor(es) relacionados."
            )
            self.search_summary_text = f"{len(matched_ids)} relatorio(s) filtrados por \"{raw_query}\"."
            return
        self.search_status_text = (
            f"Pesquisa aplicada: {total_products} produto(s), "
            f"{total_categories} categoria(s) e {total_sellers} vendedor(es) encontrados."
        )
        self.search_summary_text = "Todos os relatorios continuam disponiveis."

    def _apply_search_now(self, *args):
        self._search_ev = None
        if hasattr(self, "ids") and "report_search_input" in self.ids:
            self._pending_search = self.ids.report_search_input.text
        query = self._normalize_search_text(self._pending_search)
        self.filtered_products_list = self._filter_options(self.products_list, "Todos os Produtos", query)
        self.filtered_categories_list = self._filter_options(self.categories_list, "Todas as Categorias", query)
        self.filtered_sellers_list = self._filter_options(self.sellers_list, "Todos os Vendedores", query)
        self._invalidate_product_menu()
        self._invalidate_category_menu()
        self._invalidate_seller_menu()
        matched = self._get_matching_report_ids(query)
        prod_count = max(len(self.filtered_products_list) - 1, 0)
        cat_count  = max(len(self.filtered_categories_list) - 1, 0)
        seller_count = max(len(self.filtered_sellers_list) - 1, 0)
        if not query:
            visible = list(self._report_card_ids)
        elif matched:
            visible = matched
        elif prod_count > 0 or cat_count > 0 or seller_count > 0:
            visible = list(self._report_card_ids)
        else:
            visible = []
        self._render_report_cards(visible)
        self._update_search_feedback(
            query, visible, matched,
            self.filtered_products_list, self.filtered_categories_list, self.filtered_sellers_list,
        )

    # ------------------------------------------------------------------
    # Geradores de relatório (lazy import)
    # ------------------------------------------------------------------

    def _ensure_report_generator(self, attr_name):
        """Importa apenas o gerador necessário (mais rápido na 1.ª geração)."""
        existing = getattr(self, attr_name, None)
        if existing is not None:
            return existing
        mapping = {
            "sales_report": ("pdfs.sales_report", "SalesReport"),
            "stock_report": ("pdfs.stock_report", "StockReport"),
            "profit_report": ("pdfs.profit_report", "ProfitReport"),
            "complete_report": ("pdfs.complete_report", "CompleteReport"),
            "productivity_charts_report": ("pdfs.productivity_charts_report", "ProductivityChartsReport"),
            "cash_user_report": ("pdfs.cash_user_report", "CashUserReport"),
        }
        if attr_name not in mapping:
            raise KeyError(f"Gerador desconhecido: {attr_name}")
        mod_name, cls_name = mapping[attr_name]
        import importlib
        mod = importlib.import_module(mod_name)
        instance = getattr(mod, cls_name)()
        setattr(self, attr_name, instance)
        return instance

    def _ensure_report_generators(self):
        """Compatibilidade: carrega todos (preferir _ensure_report_generator)."""
        for attr in (
            "sales_report",
            "stock_report",
            "profit_report",
            "complete_report",
            "productivity_charts_report",
            "cash_user_report",
        ):
            try:
                self._ensure_report_generator(attr)
            except Exception as exc:
                print(f"[Reports] Falha a carregar {attr}: {exc}")

    def _ensure_pdf_viewer(self):
        if self.pdf_viewer is None:
            from pdfs.pdf_viewer import PDFViewer
            self.pdf_viewer = PDFViewer(error_callback=self.show_error_popup)
        return self.pdf_viewer

    def prepare_open_from_admin(self):
        self._ensure_filters_loaded()

    # ------------------------------------------------------------------
    # Dashboard de produtividade
    # ------------------------------------------------------------------

    def _ensure_productivity_dashboard(self):
        host = self.ids.get("productivity_dashboard_host") if hasattr(self, "ids") else None
        if host is None:
            return None
        if self._productivity_dashboard and self._productivity_dashboard.parent is host:
            return self._productivity_dashboard
        from ui.components.productivity_dashboard import ProductivityDashboard
        host.clear_widgets()
        self._productivity_dashboard = ProductivityDashboard()
        host.add_widget(self._productivity_dashboard)
        return self._productivity_dashboard

    def _ensure_productivity_loaded(self, force=False):
        dashboard = self._ensure_productivity_dashboard()
        if dashboard is None:
            return
        if not self.start_date or not self.end_date:
            self._render_productivity_dashboard()
            return
        if self._productivity_loading:
            return
        age = perf_counter() - self._productivity_last_loaded_at
        if not force and self._productivity_payload is not None and age < self.PRODUCTIVITY_CACHE_SECONDS:
            self._render_productivity_dashboard()
            return
        self._load_productivity_async()

    def _load_productivity_async(self):
        if not self.start_date or not self.end_date or self._productivity_loading:
            return
        token = self._productivity_load_token + 1
        self._productivity_load_token = token
        self._productivity_loading = True
        self._productivity_error = None
        self._set_loading_overlay(
            "productivity", True,
            "A carregar produtividade...",
            "A preparar os graficos e o resumo do periodo.",
        )
        self._render_productivity_dashboard()
        start_dt = self.start_date.strftime("%Y-%m-%d %H:%M:%S")
        end_dt   = self.end_date.strftime("%Y-%m-%d %H:%M:%S")

        def worker():
            payload, error = None, None
            try:
                payload = self.db.get_productivity_report_data(start_dt, end_dt) or {}
            except Exception as exc:
                error = str(exc)
            if (payload is None or payload == {}) and error is None:
                fn = getattr(self.db, "last_error", None)
                if callable(fn):
                    error = fn()
            Clock.schedule_once(
                lambda dt, d=payload, e=error, tok=token:
                    self._apply_productivity_payload(d, error=e, token=tok),
                0,
            )

        Thread(target=worker, daemon=True).start()

    def _apply_productivity_payload(self, payload, error=None, token=None):
        if token is not None and token != self._productivity_load_token:
            return
        self._productivity_loading = False
        self._set_loading_overlay("productivity", False)
        self._productivity_last_loaded_at = perf_counter()
        self._productivity_error = str(error).strip() if error else None
        self._productivity_payload = payload or {}
        self._render_productivity_dashboard()

    def _render_productivity_dashboard(self):
        dashboard = self._ensure_productivity_dashboard()
        if dashboard is None:
            return
        if not self.start_date or not self.end_date:
            dashboard.show_empty("Selecione um período para visualizar os gráficos de produtividade")
            return
        if self._productivity_loading:
            dashboard.show_loading("A carregar gráficos de produtividade...")
            return
        if self._productivity_error:
            dashboard.show_error("Falha ao carregar produtividade no momento.")
            return
        payload = self._productivity_payload or {}
        summary = payload.get("summary") or {}
        if int(summary.get("total_sales") or 0) <= 0:
            dashboard.show_no_data("Sem vendas no período selecionado", summary=summary)
            return
        dashboard.set_payload(payload, self._build_productivity_insights(payload))

    def _build_productivity_insights(self, payload):
        payload = payload or {}
        summary = payload.get("summary") or {}
        daily_series = list(payload.get("daily_series") or [])
        terminal_series = list(payload.get("terminal_series") or [])
        insights = []

        if terminal_series:
            leader = terminal_series[0]
            insights.append(
                f"Caixa {leader.get('terminal_id')} liderou o período com "
                f"{int(leader.get('sales_count') or 0)} vendas e "
                f"{float(leader.get('revenue') or 0):.2f} MZN."
            )
        best_day = summary.get("best_day") or {}
        if best_day:
            insights.append(
                f"O pico ocorreu em "
                f"{datetime.fromisoformat(str(best_day.get('date'))).strftime('%d/%m')} "
                f"com {int(best_day.get('sales_count') or 0)} vendas e "
                f"{float(best_day.get('revenue') or 0):.2f} MZN."
            )
        if len(daily_series) >= 5 and len(insights) < 4:
            avg = sum(int(i.get("sales_count") or 0) for i in daily_series) / max(len(daily_series), 1)
            worst = min(daily_series, key=lambda i: (
                int(i.get("sales_count") or 0), float(i.get("revenue") or 0), str(i.get("date") or ""),
            ))
            if avg > 0 and int(worst.get("sales_count") or 0) < avg * 0.65:
                insights.append(
                    f"Houve quebra relevante em "
                    f"{datetime.fromisoformat(str(worst.get('date'))).strftime('%d/%m')}, "
                    "abaixo do ritmo médio do período."
                )
        avg_discount = float(summary.get("avg_discount_percent") or 0.0)
        if len(insights) < 4:
            for item in terminal_series:
                sc = int(item.get("sales_count") or 0)
                dp_ = float(item.get("discount_percent") or 0.0)
                if sc < 5:
                    continue
                if (avg_discount > 0 and dp_ > avg_discount * 1.25) or (avg_discount <= 0 and dp_ >= 5.0):
                    insights.append(
                        f"Caixa {item.get('terminal_id')} aplicou desconto médio acima do padrão."
                    )
                    break
        avg_margin = summary.get("avg_margin_percent")
        if len(insights) < 4 and avg_margin is not None:
            comparable = [i for i in terminal_series if i.get("margin_percent") is not None]
            if len(comparable) >= 2:
                weakest = min(comparable, key=lambda i: (
                    float(i.get("margin_percent") or 0.0), -int(i.get("sales_count") or 0),
                ))
                if float(weakest.get("margin_percent") or 0.0) <= float(avg_margin) - 5.0:
                    insights.append(
                        f"Caixa {weakest.get('terminal_id')} fechou com margem abaixo da média."
                    )
        if len(insights) <= 2:
            insights.append("Sem variacoes relevantes entre os caixas neste periodo.")
        return insights[:4]

    # ------------------------------------------------------------------
    # Badge e animação do botão AI
    # ------------------------------------------------------------------

    def _init_badge(self, dt):
        for badge_id in ('ai_badge', 'recommendations_badge'):
            badge = self.ids.get(badge_id)
            if badge is not None:
                badge.opacity = 0
                badge.size = (dp(0), dp(0))

    def add_notification(self):
        self.notification_count += 1
        self.update_notification_badge(self.notification_count)

    def clear_notifications(self):
        self.notification_count = 0
        self.update_notification_badge(0)

    def update_notification_badge(self, count):
        self.notification_count = max(0, int(count or 0))
        if not hasattr(self.ids, 'ai_badge') or not hasattr(self.ids, 'ai_badge_label'):
            return
        self.ids.ai_badge_label.text = str(self.notification_count)
        if self.notification_count > 0:
            self._show_badge()
            set_attention_shake(self.ids.get('ai_button'), True)
        else:
            Animation.cancel_all(self.ids.ai_badge)
            self.ids.ai_badge.opacity = 0
            self.ids.ai_badge.size = (dp(0), dp(0))
            set_attention_shake(self.ids.get('ai_button'), False)

    def update_recommendation_badge(self, count):
        self.recommendation_count = max(0, int(count or 0))
        badge = self.ids.get('recommendations_badge') if hasattr(self, 'ids') else None
        label = self.ids.get('recommendations_badge_label') if hasattr(self, 'ids') else None
        if badge is None or label is None:
            return
        label.text = str(self.recommendation_count)
        Animation.cancel_all(badge)
        if self.recommendation_count > 0:
            badge.opacity = 1
            badge.size = (dp(0), dp(0))
            Animation(size=(dp(26), dp(26)), duration=0.25, transition='out_back').start(badge)
            set_attention_shake(self.ids.get('recommendations_button'), True)
            return
        Animation.cancel_all(badge)
        badge.opacity = 0
        badge.size = (dp(0), dp(0))
        set_attention_shake(self.ids.get('recommendations_button'), False)

    def _show_badge(self):
        if not hasattr(self.ids, 'ai_badge'):
            return
        self.ids.ai_badge.size = (dp(0), dp(0))
        self.ids.ai_badge.opacity = 1
        Animation(size=(dp(26), dp(26)), duration=0.3, transition='out_back').start(self.ids.ai_badge)

    def _hide_badge(self):
        if not hasattr(self.ids, 'ai_badge'):
            return
        Animation(opacity=0, size=(dp(0), dp(0)), duration=0.2).start(self.ids.ai_badge)

    def _start_swing_animation(self):
        if not hasattr(self.ids, 'ai_button'):
            return
        self._stop_swing_animation()
        orig = {"right": 0.965, "y": 0.04}

        def swing_cycle(dt):
            if self.notification_count <= 0:
                return False
            swing = (
                Animation(pos_hint={"right": 0.970, "y": 0.045}, duration=0.15, transition='out_sine') +
                Animation(pos_hint={"right": 0.960, "y": 0.035}, duration=0.30, transition='in_out_sine') +
                Animation(pos_hint={"right": 0.968, "y": 0.042}, duration=0.25, transition='in_out_sine') +
                Animation(pos_hint={"right": 0.962, "y": 0.038}, duration=0.25, transition='in_out_sine') +
                Animation(pos_hint={"right": 0.967, "y": 0.041}, duration=0.20, transition='in_out_sine') +
                Animation(pos_hint={"right": 0.963, "y": 0.039}, duration=0.20, transition='in_out_sine') +
                Animation(pos_hint=orig, duration=0.15, transition='out_sine')
            )
            swing.start(self.ids.ai_button)
            return True

        self.swing_event = Clock.schedule_interval(swing_cycle, 2.5)
        swing_cycle(0)

    def _stop_swing_animation(self):
        if hasattr(self, 'swing_event') and self.swing_event:
            self.swing_event.cancel()
            self.swing_event = None
        if hasattr(self.ids, 'ai_button'):
            Animation.cancel_all(self.ids.ai_button)
            Animation(pos_hint={"right": 0.965, "y": 0.04}, duration=0.2, transition='out_sine').start(
                self.ids.ai_button
            )

    # ------------------------------------------------------------------
    # Obtenção de dados filtrados
    # ------------------------------------------------------------------

    def get_filtered_data(self, start_date=None, end_date=None,
                          selected_product=None, selected_category=None,
                          selected_seller=None, skip_expiry=False):
        start_date = start_date or self.start_date
        end_date   = end_date   or self.end_date
        if not start_date or not end_date:
            return None
        product_id = self.selected_product if selected_product is None else selected_product
        category   = self.selected_category if selected_category is None else selected_category
        seller     = self.selected_seller if selected_seller is None else selected_seller
        start_dt = start_date.strftime("%Y-%m-%d %H:%M:%S")
        end_dt   = end_date.strftime("%Y-%m-%d %H:%M:%S")
        try:
            rows = self.db.get_report_data(
                start_dt,
                end_dt,
                product_id=product_id,
                category=category,
                seller=seller,
            )
            if not rows:
                return None
            # Importar pandas apenas quando ha dados para o relatorio.
            import pandas as pd

            df = pd.DataFrame(rows)
            if df.empty:
                return None
            df['sold_stock'] = df['sold_in_period']
            df['entrada'] = df['existing_stock'] + df['sold_stock']
            df['saida'] = df['sold_stock']
            df['remanescente'] = df['existing_stock']
            df['lucro_unitario'] = df['sale_price'] - df['unit_purchase_price']
            df['lucro_total'] = df['lucro_unitario'] * df['sold_stock']
            df['percentual_lucro'] = (
                (df['lucro_unitario'] / df['unit_purchase_price']) * 100
            ).fillna(0)
            df['valor_total_vendas'] = df['total_sales']
            if (not skip_expiry) and 'expiry_date' in df.columns:
                from utils.business.expiry_alerts import evaluate_expiry_alert
                alerts = [evaluate_expiry_alert(v) for v in df['expiry_date']]
                df['expiry_alert_level'] = [a.get('level') for a in alerts]
                df['expiry_alert_label'] = [a.get('label') for a in alerts]
                df['expiry_alert_short'] = [a.get('short_label') for a in alerts]
                df['expiry_days_left'] = [a.get('days_left') for a in alerts]
                df['expiry_alert_color'] = [a.get('color') for a in alerts]

            return df
        except Exception as e:
            print(f"Erro ao obter dados filtrados: {e}")
            return None

    def _get_filters_dict(self):
        product_text  = "Todos os Produtos"
        category_text = "Todas as Categorias"
        seller_text = "Todos os Vendedores"
        if hasattr(self, 'product_spinner') and self.product_spinner:
            product_text = self.product_spinner.text
        if hasattr(self, 'category_spinner') and self.category_spinner:
            category_text = self.category_spinner.text
        if hasattr(self, 'seller_spinner') and self.seller_spinner:
            seller_text = self.seller_spinner.text
        return {
            'start_date': self.start_date,
            'end_date': self.end_date,
            'product': product_text,
            'category': category_text,
            'seller': seller_text,
        }

    def _finish_report_generation(self):
        self._set_report_generation_busy(False)
        self._apply_search_now()
        self._refresh_filter_summary()

    # ------------------------------------------------------------------
    # Geração de relatórios (assíncrona)
    # ------------------------------------------------------------------

    def _generate_report_async(self, report_kind):
        """Carrega dados e abre pré-visualização interna (PDF só sob pedido)."""
        config = self._report_config(report_kind)
        if config is None or self._report_generation_busy:
            return
        button_id, generator_attr, report_label = config
        if not self.validate_filters(on_missing_period=lambda: self._generate_report_async(report_kind)):
            return

        start_date = self.start_date
        end_date = self.end_date
        selected_product = self.selected_product
        selected_category = self.selected_category
        selected_seller = self.selected_seller
        filters_dict = dict(self._get_filters_dict())
        self._set_report_generation_busy(True, button_id=button_id, status_text="A carregar...")
        self.search_status_text = f"{report_label}: a carregar dados..."
        self.search_summary_text = "A preparar a visualização interna."

        def worker():
            try:
                df = self.get_filtered_data(
                    start_date=start_date,
                    end_date=end_date,
                    selected_product=selected_product,
                    selected_category=selected_category,
                    selected_seller=selected_seller,
                    skip_expiry=True,
                )
                if df is None:
                    return {"status": "empty"}
                return {
                    "status": "ok",
                    "df": df,
                    "filters": filters_dict,
                    "kind": report_kind,
                    "generator_attr": generator_attr,
                    "label": report_label,
                }
            except Exception as exc:
                return {"status": "error", "message": str(exc)}

        def apply_result(result):
            self._finish_report_generation()
            status = (result or {}).get("status")
            if status == "empty":
                self.show_error_popup("Nenhum dado encontrado para os filtros selecionados")
                return
            if status != "ok":
                msg = (result or {}).get("message") or "Erro ao carregar dados."
                self.show_error_popup(f"Erro:\n{msg}")
                return
            self._open_report_preview(
                kind=result["kind"],
                df=result["df"],
                filters=result["filters"],
                generator_attr=result["generator_attr"],
                label=result["label"],
            )

        def run():
            result = worker()
            Clock.schedule_once(lambda dt: apply_result(result), 0)

        Thread(target=run, daemon=True).start()

    def _open_report_preview(self, kind, df, filters, generator_attr, label):
        """Abre pré-visualização; se o módulo faltar, exporta PDF direto."""
        def do_export(dataframe=None):
            self._export_preview_to_pdf(
                generator_attr=generator_attr,
                df=dataframe if dataframe is not None else df,
                filters=filters,
                label=label,
            )

        ReportDataPreview = None
        columns_for_report = None
        kpis_from_dataframe = None
        for mod_path in (
            "ui.components.report_preview",
            "pdfs.report_preview",
            "report_preview",
        ):
            try:
                import importlib
                mod = importlib.import_module(mod_path)
                ReportDataPreview = getattr(mod, "ReportDataPreview", None)
                columns_for_report = getattr(mod, "columns_for_report", None)
                kpis_from_dataframe = getattr(mod, "kpis_from_dataframe", None)
                if ReportDataPreview is not None:
                    break
            except Exception:
                continue

        if ReportDataPreview is None or columns_for_report is None:
            # Fallback: gera PDF sem pré-visualização (ecrã continua funcional)
            print("[Reports] report_preview indisponível — a exportar PDF direto.")
            do_export(df)
            return

        try:
            dlg = ReportDataPreview(
                title=f"{label} — visualização",
                dataframe=df,
                columns=columns_for_report(kind),
                kpis=kpis_from_dataframe(df) if callable(kpis_from_dataframe) else [],
                on_export_pdf=do_export,
            )
            dlg.open()
        except Exception as exc:
            print(f"[Reports] Falha na pré-visualização: {exc}")
            do_export(df)

    def _export_preview_to_pdf(self, generator_attr, df, filters, label):
        if self._report_generation_busy:
            return
        self._set_report_generation_busy(True, status_text="A exportar PDF...")
        self.search_status_text = f"A gerar PDF: {label}..."

        def worker():
            try:
                generator = self._ensure_report_generator(generator_attr)
                path = generator.generate(df, filters)
                return {"status": "ok", "pdf_path": path}
            except Exception as exc:
                return {"status": "error", "message": str(exc)}

        def apply(result):
            self._finish_report_generation()
            if (result or {}).get("status") == "ok" and result.get("pdf_path"):
                self.show_success_popup(result["pdf_path"])
            else:
                self.show_error_popup(
                    (result or {}).get("message") or "Falha ao exportar PDF."
                )

        def run():
            result = worker()
            Clock.schedule_once(lambda dt: apply(result), 0)

        Thread(target=run, daemon=True).start()


    def generate_sales_report(self):
        self._generate_report_async("sales")

    def generate_stock_report(self):
        self._generate_report_async("stock")

    def generate_profit_report(self):
        self._generate_report_async("profit")

    def generate_complete_report(self):
        self._generate_report_async("complete")

    def generate_cash_user_report(self):
        if self._report_generation_busy:
            return
        if not self.validate_filters(on_missing_period=self.generate_cash_user_report):
            return
        start_date = self.start_date
        end_date   = self.end_date
        selected_seller = self.selected_seller
        filters_dict = {
            "start_date": start_date, "end_date": end_date,
            "product": "Nao se aplica", "category": "Nao se aplica",
            "seller": self.seller_spinner.text if getattr(self, "seller_spinner", None) else "Todos os Vendedores",
        }
        self._ensure_report_generators()
        self._set_report_generation_busy(True, button_id="cash_user_report_card", status_text="A gerar...")
        self.search_status_text  = "Relatorio de caixa por utilizador em preparacao..."
        self.search_summary_text = "A consolidar abertura, fechamento e vendas por atendente."

        def worker():
            try:
                start_dt = start_date.strftime("%Y-%m-%d %H:%M:%S")
                end_dt   = end_date.strftime("%Y-%m-%d %H:%M:%S")
                payload  = self.db.get_cash_user_report_data(start_dt, end_dt, seller=selected_seller) or {}
                summary  = payload.get("summary") or {}
                if int(summary.get("total_sales") or 0) <= 0:
                    return {"status": "empty"}
                if self.cash_user_report is None:
                    raise RuntimeError("Gerador de relatorio de caixa indisponivel")
                return {"status": "ok", "pdf_path": self.cash_user_report.generate(payload, filters_dict)}
            except Exception as exc:
                return {"status": "error", "message": str(exc)}

        def apply_result(result):
            self._finish_report_generation()
            status = (result or {}).get("status")
            if status == "ok" and result.get("pdf_path"):
                self.show_success_popup(result.get("pdf_path"))
            elif status == "ok":
                self.show_error_popup("O relatório de caixa foi gerado, mas o caminho do PDF não foi devolvido.")
            elif status == "empty":
                self.show_error_popup("Nao ha movimentos de caixa no periodo selecionado.")
            else:
                msg = (result or {}).get("message") or "Erro ao gerar relatorio de caixa."
                self.show_error_popup(f"Erro ao gerar relatorio de caixa:\n{msg}")

        Thread(target=lambda: Clock.schedule_once(
            lambda dt, r=worker(): apply_result(r), 0), daemon=True).start()

    def print_productivity_charts(self):
        if self._printing_charts_busy:
            return
        if not self.validate_filters(on_missing_period=self.print_productivity_charts):
            return
        start_date = self.start_date
        end_date   = self.end_date
        filters_dict = {
            "start_date": start_date, "end_date": end_date,
            "product": "Nao se aplica", "category": "Nao se aplica",
        }
        self._ensure_report_generators()
        self._set_print_charts_busy(True)
        self.search_status_text  = "Graficos em preparacao para impressao..."
        self.search_summary_text = "Apenas os graficos principais serao enviados para PDF."

        def worker():
            try:
                start_dt = start_date.strftime("%Y-%m-%d %H:%M:%S")
                end_dt   = end_date.strftime("%Y-%m-%d %H:%M:%S")
                payload  = self.db.get_productivity_report_data(start_dt, end_dt) or {}
                summary  = payload.get("summary") or {}
                if int(summary.get("total_sales") or 0) <= 0:
                    return {"status": "empty"}
                if self.productivity_charts_report is None:
                    raise RuntimeError("Gerador de graficos indisponivel")
                return {"status": "ok", "pdf_path": self.productivity_charts_report.generate(payload, filters_dict)}
            except Exception as exc:
                return {"status": "error", "message": str(exc)}

        def apply_result(result):
            self._set_print_charts_busy(False)
            self._apply_search_now()
            self._refresh_filter_summary()
            status = (result or {}).get("status")
            if status == "ok":
                pdf_path = result.get("pdf_path")
                viewer = self._ensure_pdf_viewer()
                if viewer.print_pdf(pdf_path):
                    self.show_chart_print_success_popup(pdf_path)
                else:
                    self.show_pdf_print_ready_popup(
                        pdf_path,
                        getattr(viewer, "last_print_message", ""),
                    )
            elif status == "empty":
                self.show_error_popup("Nao ha graficos com vendas no periodo selecionado.")
            else:
                msg = (result or {}).get("message") or "Erro ao preparar os graficos."
                self.show_error_popup(f"Erro ao imprimir graficos:\n{msg}")

        Thread(target=lambda: Clock.schedule_once(
            lambda dt, r=worker(): apply_result(r), 0), daemon=True).start()

    # ------------------------------------------------------------------
    # Visualizador de PDFs
    # ------------------------------------------------------------------

    def _get_available_pdf_files(self):
        pdf_files, seen = [], set()
        for report_dir in report_search_dirs():
            if not os.path.isdir(report_dir):
                continue
            for root, dirs, files in os.walk(report_dir):
                for file in files:
                    if not file.lower().endswith('.pdf'):
                        continue
                    full_path = os.path.abspath(os.path.join(root, file))
                    key = os.path.normcase(full_path)
                    if key in seen:
                        continue
                    seen.add(key)
                    pdf_files.append(self._build_pdf_meta(full_path))
        pdf_files.sort(key=lambda item: item.get("mtime", 0), reverse=True)
        return pdf_files

    def _get_recent_pdf_scan_cache(self):
        if self._pdf_scan_cache_at <= 0:
            return None
        if perf_counter() - self._pdf_scan_cache_at > self.PDF_SCAN_CACHE_SECONDS:
            return None
        return [dict(item) for item in self._pdf_scan_cache]

    def _get_pdf_type(self, pdf_path):
        resolved_path = Path(pdf_path).resolve()
        raw_type = ""
        for report_dir in report_search_dirs():
            try:
                relative_path = resolved_path.relative_to(Path(report_dir).resolve())
            except (OSError, ValueError):
                continue
            if len(relative_path.parts) > 1:
                raw_type = relative_path.parts[0]
            break

        if not raw_type:
            raw_type = "outros"
        type_key = self._normalize_search_text(raw_type).replace(" ", "_")
        type_label = self.PDF_TYPE_LABELS.get(
            type_key,
            raw_type.replace("_", " ").strip().title() or "Outros",
        )
        return type_key, type_label

    def _build_pdf_meta(self, pdf_path):
        full_path = os.path.abspath(os.fspath(pdf_path))
        filename = os.path.basename(full_path)
        folder = os.path.basename(os.path.dirname(full_path))
        parent = os.path.basename(os.path.dirname(os.path.dirname(full_path)))
        type_key, type_label = self._get_pdf_type(full_path)

        try:
            stat = os.stat(full_path)
            mtime = stat.st_mtime
            size_kb = stat.st_size / 1024
        except OSError:
            mtime = 0
            size_kb = 0

        mod_time_text = (
            datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")
            if mtime else ""
        )
        if parent and folder:
            display_name = f"{parent} - {folder}"
            subtitle = filename
        else:
            display_name = filename
            subtitle = filename

        meta_text = (
            f"{mod_time_text} | {size_kb:.1f} KB"
            if mod_time_text else f"{size_kb:.1f} KB"
        )
        filter_key = self._normalize_search_text(
            f"{filename} {folder} {parent} {mod_time_text} {full_path}"
        )
        return {
            "path": full_path,
            "mtime": mtime,
            "size_kb": size_kb,
            "display_name": display_name,
            "subtitle": subtitle,
            "meta_text": meta_text,
            "filter_key": filter_key,
            "type_key": type_key,
            "type_label": type_label,
        }

    @staticmethod
    def _safe_pdf_mtime(pdf_path):
        try:
            return os.path.getmtime(pdf_path)
        except OSError:
            return 0

    @staticmethod
    def _safe_pdf_size_kb(pdf_path):
        try:
            return os.path.getsize(pdf_path) / 1024
        except OSError:
            return 0

    def show_pdf_viewer(self):
        self._pdf_list_token += 1
        token = self._pdf_list_token
        self._pdf_loading = True
        self._pdf_type_filter = None
        self._pdf_all_files = []
        self._pdf_filtered_files = []
        self._pdf_file_meta = {}
        self._pdf_visible_limit = self.PDF_INITIAL_RENDER_LIMIT
        self._create_pdf_list_dialog()

        cached_files = self._get_recent_pdf_scan_cache()
        if cached_files is not None:
            Clock.schedule_once(
                lambda dt, files=cached_files, tok=token:
                self._finish_pdf_scan(files, None, tok),
                0.05,
            )
            return

        def worker():
            try:
                pdf_files = self._get_available_pdf_files()
                error = None
            except Exception as exc:
                pdf_files = []
                error = exc
            Clock.schedule_once(
                lambda dt, files=pdf_files, err=error, tok=token:
                self._finish_pdf_scan(files, err, tok),
                0,
            )

        Clock.schedule_once(lambda dt: Thread(target=worker, daemon=True).start(), 0.05)

    def _update_pdf_dialog_layout(self, *args):
        if not self._pdf_dialog_body or not self._pdf_dialog_scroll:
            return
        content_height = min(dp(520), max(dp(320), Window.height * 0.64))
        scroll_height = max(dp(180), content_height - dp(154))
        self._pdf_dialog_body.height = content_height
        self._pdf_dialog_scroll.height = scroll_height

    def _bind_pdf_dialog_layout(self):
        try:
            Window.unbind(on_resize=self._update_pdf_dialog_layout)
        except Exception:
            pass
        Window.bind(on_resize=self._update_pdf_dialog_layout)
        self._update_pdf_dialog_layout()

    def _create_pdf_list_dialog(self):
        if self.pdf_dialog:
            self.pdf_dialog.dismiss()

        if self._pdf_selector_menu:
            self._pdf_selector_menu.dismiss()
            self._pdf_selector_menu = None
        if self._pdf_render_ev:
            self._pdf_render_ev.cancel()
            self._pdf_render_ev = None
        self._pdf_pending_items = deque()
        self._pdf_load_more_button = None

        content_height = min(dp(500), Window.height * 0.66)
        scroll_height  = max(dp(220), content_height - dp(142))

        body = MDBoxLayout(
            orientation='vertical', spacing=dp(12),
            size_hint_y=None, height=content_height,
            padding=[dp(16), dp(12), dp(16), dp(10)],
        )
        header = MDBoxLayout(orientation='horizontal', size_hint_y=None, height=dp(28))
        header.add_widget(MDLabel(
            text="Arquivos encontrados", font_style='Subtitle1', bold=True,
            theme_text_color='Custom', text_color=_theme_color('text_primary', (0.2, 0.2, 0.2, 1)),
        ))
        self._pdf_count_label = MDLabel(
            text="A carregar...", font_style='Caption', halign='right',
            theme_text_color='Custom', text_color=_theme_color('text_secondary', (0.5, 0.5, 0.5, 1)),
        )
        header.add_widget(self._pdf_count_label)
        body.add_widget(header)

        selector_row = MDBoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(48),
        )
        self._pdf_selector_button = MDRaisedButton(
            text="A CARREGAR PDFS...",
            size_hint=(1, None),
            height=dp(44),
            disabled=True,
            font_size=sp(14),
            elevation=0,
            md_bg_color=_theme_color('card_alt', (0.98, 0.98, 0.98, 1)),
            text_color=_theme_color('text_primary', (0.2, 0.2, 0.2, 1)),
            on_release=lambda caller: self._open_pdf_selector(caller),
        )
        selector_row.add_widget(self._pdf_selector_button)
        body.add_widget(selector_row)
        body.add_widget(MDSeparator(height=dp(1)))

        self._pdf_status_label = MDLabel(
            text="A carregar PDFs...",
            font_style='Caption',
            halign='center',
            valign='middle',
            size_hint_y=None,
            height=dp(34),
            theme_text_color='Custom',
            text_color=_theme_color('text_secondary', (0.5, 0.5, 0.5, 1)),
        )
        body.add_widget(self._pdf_status_label)

        self._pdf_list_container = MDBoxLayout(
            orientation='vertical',
            spacing=dp(8),
            size_hint_y=None,
            padding=[0, dp(8)],
        )
        self._pdf_list_container.bind(minimum_height=self._pdf_list_container.setter('height'))

        scroll = ScrollView(size_hint=(1, None), height=scroll_height,
                            do_scroll_x=False, bar_width=dp(4))
        scroll.add_widget(self._pdf_list_container)
        body.add_widget(scroll)
        self._pdf_dialog_body = body
        self._pdf_dialog_scroll = scroll

        close_btn = MDFlatButton(text="FECHAR", on_release=lambda x: self._dismiss_pdf_dialog())
        self._pdf_delete_filtered_button = MDRaisedButton(
            text="APAGAR TODOS",
            md_bg_color=_theme_color('danger', (0.85, 0.3, 0.3, 1)),
            disabled=True,
            on_release=lambda x: self._confirm_delete_filtered_pdfs(),
        )

        self.pdf_dialog = MDDialog(
            title="PDFs disponíveis",
            type="custom", content_cls=body,
            size_hint=(None, None),
            size=(min(dp(980), Window.width * 0.92), min(dp(680), Window.height * 0.82)),
            buttons=[close_btn, self._pdf_delete_filtered_button],
        )
        self._style_dialog(self.pdf_dialog, max_width=980, max_height=680, width_ratio=0.92, height_ratio=0.82)
        self._bind_pdf_dialog_layout()
        self.pdf_dialog.open()

    def _dismiss_pdf_dialog(self):
        if self._pdf_selector_menu:
            self._pdf_selector_menu.dismiss()
            self._pdf_selector_menu = None
        if self._pdf_render_ev:
            self._pdf_render_ev.cancel()
            self._pdf_render_ev = None
        self._pdf_pending_items = deque()
        self._pdf_load_more_button = None
        try:
            Window.unbind(on_resize=self._update_pdf_dialog_layout)
        except Exception:
            pass
        self._pdf_dialog_body = None
        self._pdf_dialog_scroll = None
        if self.pdf_dialog:
            self.pdf_dialog.dismiss()
            self.pdf_dialog = None

    def _finish_pdf_scan(self, pdf_files, error, token):
        if token != self._pdf_list_token:
            return
        self._pdf_loading = False
        if error is not None:
            if self._pdf_status_label:
                self._pdf_status_label.text = "Erro ao carregar PDFs."
            self.show_error_popup(f"Nao foi possivel listar os PDFs:\n{error}")
            return
        pdf_items = []
        for item in list(pdf_files or []):
            meta = item if isinstance(item, dict) else self._build_pdf_meta(item)
            path = meta.get("path")
            if not path:
                continue
            pdf_items.append(meta)

        self._pdf_scan_cache = [dict(item) for item in pdf_items]
        self._pdf_scan_cache_at = perf_counter()
        self._pdf_file_meta = {item["path"]: item for item in pdf_items}
        self._pdf_all_files = [item["path"] for item in pdf_items]
        self._pdf_visible_limit = self.PDF_INITIAL_RENDER_LIMIT
        self._rebuild_pdf_selector()
        self._apply_pdf_type_filter()

    def _get_pdf_meta(self, pdf_path):
        meta = self._pdf_file_meta.get(pdf_path)
        if meta is None or not meta.get("type_key"):
            meta = self._build_pdf_meta(pdf_path)
            self._pdf_file_meta[pdf_path] = meta
        return meta

    def _get_pdf_type_filters(self):
        filters = {}
        for pdf_path in self._pdf_all_files:
            meta = self._get_pdf_meta(pdf_path)
            type_key = meta.get("type_key")
            if type_key:
                filters[type_key] = meta.get("type_label") or "Outros"
        return filters

    def _rebuild_pdf_selector(self):
        if self._pdf_selector_menu:
            self._pdf_selector_menu.dismiss()
            self._pdf_selector_menu = None
        if not self._pdf_selector_button:
            return

        has_files = bool(self._pdf_all_files)
        self._pdf_selector_button.disabled = not has_files
        if not has_files:
            self._pdf_type_filter = None
            self._pdf_selector_button.text = "NENHUM PDF DISPONÍVEL"
            return

        type_filters = self._get_pdf_type_filters()
        if self._pdf_type_filter not in type_filters:
            self._pdf_type_filter = None
        self._set_pdf_selector_text(type_filters)

        items = [{
            "text": "Todos os Tipos",
            "viewclass": "OneLineListItem",
            "on_release": lambda: self._select_pdf_filter(None),
        }]
        items.extend({
            "text": label,
            "viewclass": "OneLineListItem",
            "on_release": lambda selected=type_key: self._select_pdf_filter(selected),
        } for type_key, label in sorted(
            type_filters.items(),
            key=lambda item: self._normalize_search_text(item[1]),
        ))
        self._pdf_selector_menu = MDDropdownMenu(
            caller=self._pdf_selector_button,
            items=items,
            width_mult=5,
            max_height=min(dp(420), max(dp(200), Window.height * 0.50)),
        )

    def _set_pdf_selector_text(self, type_filters=None):
        if not self._pdf_selector_button:
            return
        type_filters = type_filters or self._get_pdf_type_filters()
        if self._pdf_type_filter in type_filters:
            label = type_filters[self._pdf_type_filter]
            self._pdf_selector_button.text = f"{self._truncate_text(label, 68)}  ▾"
        else:
            self._pdf_selector_button.text = "TODOS OS TIPOS  ▾"

    def _open_pdf_selector(self, caller):
        if not self._pdf_all_files:
            return
        if self._pdf_selector_menu is None:
            self._rebuild_pdf_selector()
        if self._pdf_selector_menu:
            self._pdf_selector_menu.caller = caller
            self._pdf_selector_menu.open()

    def _select_pdf_filter(self, type_key):
        if self._pdf_selector_menu:
            self._pdf_selector_menu.dismiss()
        type_filters = self._get_pdf_type_filters()
        self._pdf_type_filter = type_key if type_key in type_filters else None
        self._set_pdf_selector_text(type_filters)
        self._apply_pdf_type_filter()

    def _apply_pdf_type_filter(self):
        self._pdf_visible_limit = self.PDF_INITIAL_RENDER_LIMIT
        type_filters = self._get_pdf_type_filters()
        if self._pdf_type_filter in type_filters:
            filtered = [
                pdf_path for pdf_path in self._pdf_all_files
                if self._get_pdf_meta(pdf_path).get("type_key") == self._pdf_type_filter
            ]
        else:
            self._pdf_type_filter = None
            filtered = list(self._pdf_all_files)
        self._pdf_filtered_files = filtered
        self._render_pdf_file_list(filtered)

    def _render_pdf_file_list(self, pdf_files):
        if self._pdf_render_ev:
            self._pdf_render_ev.cancel()
            self._pdf_render_ev = None
        self._pdf_load_more_button = None
        matches = list(pdf_files or [])
        total_matches = len(matches)
        render_limit = max(0, int(self._pdf_visible_limit or self.PDF_INITIAL_RENDER_LIMIT))
        render_files = matches[:render_limit]
        self._pdf_pending_items = deque(render_files)
        if self._pdf_list_container:
            self._pdf_list_container.clear_widgets()

        total = len(self._pdf_all_files)
        shown = len(render_files)
        type_filters = self._get_pdf_type_filters()
        has_filter = self._pdf_type_filter in type_filters
        if self._pdf_count_label:
            if self._pdf_loading:
                self._pdf_count_label.text = "A carregar..."
            elif has_filter:
                self._pdf_count_label.text = f"{total_matches} de {total} item(ns)"
            else:
                self._pdf_count_label.text = f"{total} item(ns)"

        if self._pdf_delete_filtered_button:
            self._pdf_delete_filtered_button.disabled = total_matches <= 0
            self._pdf_delete_filtered_button.text = (
                "APAGAR FILTRADOS" if has_filter else "APAGAR TODOS"
            )

        if self._pdf_status_label:
            if self._pdf_loading:
                self._pdf_status_label.text = "A carregar PDFs..."
            elif total <= 0:
                self._pdf_status_label.text = "Nenhum PDF encontrado na pasta de relatorios."
            elif total_matches <= 0:
                self._pdf_status_label.text = "Nenhum PDF corresponde ao filtro selecionado."
            elif shown < total_matches:
                self._pdf_status_label.text = f"Mostrando {shown} de {total_matches} PDFs. Carregue mais se precisar."
            elif has_filter:
                self._pdf_status_label.text = (
                    f"Mostrando PDFs de {type_filters[self._pdf_type_filter]}."
                )
            else:
                self._pdf_status_label.text = "Mostrando todos os PDFs."

        if not self._pdf_pending_items:
            return

        self._render_pdf_batch(0)
        if self._pdf_pending_items:
            self._pdf_render_ev = Clock.schedule_interval(self._render_pdf_batch, 0.016)

    def _render_pdf_batch(self, dt):
        if not self._pdf_list_container:
            self._pdf_render_ev = None
            return False
        batch_count = 0
        while self._pdf_pending_items and batch_count < self.PDF_RENDER_BATCH_SIZE:
            pdf_path = self._pdf_pending_items.popleft()
            self._pdf_list_container.add_widget(self._create_pdf_list_item(pdf_path))
            batch_count += 1
        if not self._pdf_pending_items:
            self._pdf_render_ev = None
            self._add_pdf_load_more_control()
            return False
        return True

    def _add_pdf_load_more_control(self):
        if not self._pdf_list_container:
            return
        total_matches = len(self._pdf_filtered_files or [])
        shown = min(total_matches, int(self._pdf_visible_limit or 0))
        remaining = total_matches - shown
        if remaining <= 0:
            return

        row = MDBoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(50),
            spacing=dp(8),
            padding=[0, dp(6)],
        )
        row.add_widget(Widget())
        next_count = min(self.PDF_RENDER_PAGE_SIZE, remaining)
        row.add_widget(MDRaisedButton(
            text=f"CARREGAR MAIS {next_count}",
            size_hint=(None, None),
            size=(dp(190), dp(38)),
            md_bg_color=_theme_color('info', (0.28, 0.47, 0.84, 1)),
            on_release=lambda _x: self._load_more_pdfs(),
        ))
        row.add_widget(Widget())
        self._pdf_load_more_button = row
        self._pdf_list_container.add_widget(row)

    def _load_more_pdfs(self):
        if self._pdf_render_ev:
            self._pdf_render_ev.cancel()
            self._pdf_render_ev = None
        self._pdf_visible_limit += self.PDF_RENDER_PAGE_SIZE
        self._render_pdf_file_list(self._pdf_filtered_files)

    def _create_pdf_list_item(self, pdf_path):
        meta = self._pdf_file_meta.get(pdf_path)
        if meta is None:
            meta = self._build_pdf_meta(pdf_path)
            self._pdf_file_meta[pdf_path] = meta
        display_name = meta.get("display_name") or os.path.basename(pdf_path)
        subtitle = meta.get("subtitle") or os.path.basename(pdf_path)
        meta_text = meta.get("meta_text") or ""

        item = MDCard(
            orientation='vertical', size_hint_y=None, height=dp(108),
            padding=[dp(12), dp(8)], spacing=dp(6), elevation=0,
            radius=[dp(8)], md_bg_color=_theme_color('card_alt', (0.98, 0.98, 0.98, 1)),
        )
        info_box = MDBoxLayout(
            orientation='vertical',
            spacing=dp(2),
            size_hint_y=None,
            height=dp(60),
        )
        for text, style, bold, h, color_key in [
            (self._truncate_text(display_name, 56), 'Subtitle2', True,  dp(22), 'text_primary'),
            (self._truncate_text(subtitle, 76),     'Caption',   False, dp(17), 'text_secondary'),
            (meta_text,                             'Caption',   False, dp(17), 'text_secondary'),
        ]:
            lbl = MDLabel(
                text=text, font_style=style, bold=bold, halign='left', valign='middle',
                theme_text_color='Custom',
                text_color=_theme_color(color_key, (0.2, 0.2, 0.2, 1)),
                size_hint_y=None, height=h, shorten=True, shorten_from='right', max_lines=1,
            )
            lbl.bind(size=lambda inst, _: setattr(inst, "text_size", (inst.width, None)))
            info_box.add_widget(lbl)
        item.add_widget(info_box)

        actions_box = MDBoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(30),
            spacing=dp(6),
        )
        actions_box.add_widget(Widget())
        for text, color_key, width, callback in [
            ("VER",       'primary',  dp(54), lambda _x, p=pdf_path: self._view_and_close_dialog(p)),
            ("IMPRIMIR",  'success',  dp(82), lambda _x, p=pdf_path: self._print_pdf_from_list(p)),
            ("ELIMINAR",  'danger',   dp(82), lambda _x, p=pdf_path: self._confirm_delete_pdf(p)),
        ]:
            actions_box.add_widget(MDRaisedButton(
                text=text, size_hint=(None, None), size=(width, dp(30)),
                font_size=sp(11),
                md_bg_color=_theme_color(color_key, (0.5, 0.5, 0.5, 1)),
                on_release=callback,
            ))
        item.add_widget(actions_box)
        return item

    def _print_pdf_from_list(self, pdf_path):
        viewer = self._ensure_pdf_viewer()
        if viewer.print_pdf(pdf_path):
            self.show_pdf_print_success_popup(pdf_path)
        else:
            self.show_pdf_print_ready_popup(
                pdf_path,
                getattr(viewer, "last_print_message", ""),
            )

    def _dismiss_delete_pdf_dialog(self):
        dlg = getattr(self, 'delete_pdf_dialog', None)
        if dlg:
            dlg.dismiss()
            self.delete_pdf_dialog = None

    def _build_confirm_content(self, message, detail="", icon_name="delete-outline"):
        """Conteúdo legível para diálogos de confirmação (largura estável)."""
        tokens_fg = _theme_color('text_primary', (0.92, 0.94, 0.97, 1))
        tokens_muted = _theme_color('text_secondary', (0.55, 0.58, 0.63, 1))
        danger = _theme_color('danger', (0.85, 0.3, 0.3, 1))
        card_alt = _theme_color('card_alt', (0.16, 0.18, 0.22, 1))

        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(12),
            padding=[dp(4), dp(4), dp(4), dp(2)],
            size_hint_y=None,
        )
        content.bind(minimum_height=content.setter("height"))

        header = MDBoxLayout(size_hint_y=None, height=dp(28), spacing=dp(8))
        header.add_widget(MDIcon(
            icon=icon_name,
            theme_text_color="Custom",
            text_color=danger,
            size_hint=(None, None),
            size=(dp(24), dp(24)),
        ))
        header.add_widget(MDLabel(
            text="Confirmar eliminação",
            bold=True,
            font_style="Body1",
            theme_text_color="Custom",
            text_color=tokens_fg,
            valign="middle",
        ))
        content.add_widget(header)

        body = MDLabel(
            text=str(message or ""),
            theme_text_color="Custom",
            text_color=tokens_muted,
            font_style="Body2",
            halign="left",
            valign="top",
            size_hint_y=None,
            text_size=(dp(380), None),
        )
        body.bind(
            texture_size=lambda inst, val: setattr(inst, "height", max(dp(36), val[1] + dp(4))),
            width=lambda inst, val: setattr(inst, "text_size", (max(dp(240), val - dp(8)), None)),
        )
        content.add_widget(body)

        if detail:
            detail_card = MDCard(
                orientation="vertical",
                size_hint_y=None,
                height=dp(44),
                padding=[dp(12), dp(8)],
                radius=[dp(10)],
                elevation=0,
                md_bg_color=card_alt,
            )
            detail_lbl = MDLabel(
                text=str(detail),
                theme_text_color="Custom",
                text_color=tokens_fg,
                font_style="Caption",
                bold=True,
                halign="left",
                valign="middle",
                shorten=True,
                shorten_from="middle",
            )
            detail_lbl.bind(size=lambda inst, *_: setattr(inst, "text_size", (inst.width, None)))
            detail_card.add_widget(detail_lbl)
            content.add_widget(detail_card)

        return content

    def _open_confirm_dialog(self, content, buttons, width=dp(440), height=dp(240)):
        """Abre diálogo de confirmação com tamanho estável e legível."""
        self._dismiss_delete_pdf_dialog()
        dlg_width = min(float(width), max(dp(320), Window.width * 0.88))
        dlg_height = min(float(height), max(dp(200), Window.height * 0.55))
        self.delete_pdf_dialog = MDDialog(
            title="",
            type="custom",
            content_cls=content,
            size_hint=(None, None),
            size=(dlg_width, dlg_height),
            buttons=buttons,
        )

        def _fit(*_a):
            try:
                content.width = self.delete_pdf_dialog.width - dp(40)
                needed = max(dp(200), float(content.height) + dp(100))
                self.delete_pdf_dialog.height = min(needed, max(dp(220), Window.height * 0.6))
                self.delete_pdf_dialog.width = min(dp(480), max(dp(320), Window.width * 0.88))
            except Exception:
                pass

        Clock.schedule_once(_fit, 0)
        Clock.schedule_once(_fit, 0.05)
        self.delete_pdf_dialog.open()
        return self.delete_pdf_dialog

    def _confirm_delete_pdf(self, pdf_path):
        filename = os.path.basename(pdf_path)
        content = self._build_confirm_content(
            "Quer eliminar este arquivo? Esta ação não pode ser desfeita.",
            detail=filename,
            icon_name="delete-outline",
        )
        self._open_confirm_dialog(
            content,
            buttons=[
                MDFlatButton(
                    text="CANCELAR",
                    text_color=_theme_color('text_secondary', (0.55, 0.58, 0.63, 1)),
                    on_release=lambda _: self._dismiss_delete_pdf_dialog(),
                ),
                MDRaisedButton(
                    text="ELIMINAR",
                    md_bg_color=_theme_color('danger', (0.85, 0.3, 0.3, 1)),
                    text_color=_theme_color('on_primary', (1, 1, 1, 1)),
                    on_release=lambda _, p=pdf_path: self._delete_pdf_and_refresh(p),
                ),
            ],
            width=dp(440),
            height=dp(260),
        )

    def _confirm_delete_filtered_pdfs(self):
        files = [path for path in self._pdf_filtered_files if os.path.exists(path)]
        if not files:
            self.show_error_popup("Nenhum PDF selecionado.")
            return
        total = len(files)
        type_filters = self._get_pdf_type_filters()
        if self._pdf_type_filter in type_filters:
            message = (
                f"Quer apagar {total} PDF(s) filtrado(s) por "
                f"«{type_filters[self._pdf_type_filter]}»?"
            )
            detail = f"{total} ficheiro(s) serão eliminados"
        else:
            message = f"Quer apagar todos os {total} PDFs encontrados?"
            detail = f"{total} ficheiro(s) serão eliminados"

        content = self._build_confirm_content(
            message + " Esta ação não pode ser desfeita.",
            detail=detail,
            icon_name="delete-sweep-outline",
        )
        self._open_confirm_dialog(
            content,
            buttons=[
                MDFlatButton(
                    text="CANCELAR",
                    text_color=_theme_color('text_secondary', (0.55, 0.58, 0.63, 1)),
                    on_release=lambda _: self._dismiss_delete_pdf_dialog(),
                ),
                MDRaisedButton(
                    text="APAGAR",
                    md_bg_color=_theme_color('danger', (0.85, 0.3, 0.3, 1)),
                    text_color=_theme_color('on_primary', (1, 1, 1, 1)),
                    on_release=lambda _, selected=list(files): self._delete_pdfs_and_refresh(selected),
                ),
            ],
            width=dp(460),
            height=dp(270),
        )

    def _delete_pdf_and_refresh(self, pdf_path):
        self._delete_pdfs_and_refresh([pdf_path])

    def _delete_pdfs_and_refresh(self, pdf_paths):
        self._dismiss_delete_pdf_dialog()
        selected = {
            os.path.normcase(os.path.abspath(path))
            for path in list(pdf_paths or [])
        }
        allowed = {
            os.path.normcase(os.path.abspath(path))
            for path in list(self._pdf_all_files or [])
        }
        deleted = 0
        failures = []
        refreshed_all = []
        try:
            for pdf_path in list(self._pdf_all_files or []):
                normalized = os.path.normcase(os.path.abspath(pdf_path))
                if normalized not in selected:
                    if os.path.exists(pdf_path):
                        refreshed_all.append(pdf_path)
                    continue
                if normalized not in allowed:
                    failures.append(os.path.basename(pdf_path))
                    continue
                try:
                    if os.path.exists(pdf_path):
                        os.remove(pdf_path)
                        deleted += 1
                except OSError:
                    failures.append(os.path.basename(pdf_path))
                    refreshed_all.append(pdf_path)
        finally:
            self._pdf_all_files = refreshed_all
            self._pdf_file_meta = {
                path: self._pdf_file_meta.get(path) or self._build_pdf_meta(path)
                for path in refreshed_all
            }
            self._pdf_scan_cache = [
                dict(self._pdf_file_meta[path])
                for path in refreshed_all
                if path in self._pdf_file_meta
            ]
            self._pdf_scan_cache_at = perf_counter()
            self._pdf_visible_limit = self.PDF_INITIAL_RENDER_LIMIT
            self._rebuild_pdf_selector()
            self._apply_pdf_type_filter()

        if failures:
            self.show_error_popup(
                f"{deleted} PDF(s) apagado(s). Falha ao apagar: {', '.join(failures[:5])}"
            )
        elif deleted:
            if self._pdf_status_label:
                self._pdf_status_label.text = f"{deleted} PDF(s) apagado(s)."
        else:
            self.show_error_popup("Nenhum PDF foi apagado.")

    def _view_and_close_dialog(self, pdf_path):
        self._dismiss_pdf_dialog()
        self._ensure_pdf_viewer().view_pdf(pdf_path)

    # ------------------------------------------------------------------
    # Sistema visual de dialogs
    # ------------------------------------------------------------------

    @staticmethod
    def _dialog_size(max_width=620, max_height=520, width_ratio=0.90, height_ratio=0.82):
        """Calcula dimensões seguras para dialogs em janelas de vários tamanhos."""
        width = min(dp(max_width), max(dp(300), Window.width * width_ratio))
        height = min(dp(max_height), max(dp(220), Window.height * height_ratio))
        return width, height

    def _style_dialog(self, dialog, max_width=620, max_height=520, width_ratio=0.90, height_ratio=0.82):
        """Padroniza dialogs e acompanha o redimensionamento da janela."""
        if dialog is None:
            return None

        dialog.size_hint = (None, None)

        def resize(*_args):
            try:
                if dialog.parent is not None:
                    dialog.size = self._dialog_size(
                        max_width=max_width,
                        max_height=max_height,
                        width_ratio=width_ratio,
                        height_ratio=height_ratio,
                    )
            except Exception:
                pass

        resize()

        def cleanup(*_args):
            try:
                Window.unbind(on_resize=resize)
            except Exception:
                pass

        dialog.bind(on_dismiss=cleanup)
        Window.bind(on_resize=resize)
        return dialog

    @staticmethod
    def _dialog_button(text, callback, *, primary=False, color_key='primary'):
        button_cls = MDRaisedButton if primary else MDFlatButton
        kwargs = {
            'text': text,
            'on_release': callback,
        }
        if primary:
            kwargs.update({
                'md_bg_color': _theme_color(color_key, (0.15, 0.52, 0.76, 1)),
                'text_color': _theme_color('on_primary', (1, 1, 1, 1)),
            })
        else:
            kwargs.update({
                'text_color': _theme_color(color_key, (0.15, 0.52, 0.76, 1)),
            })
        return button_cls(**kwargs)

    # ------------------------------------------------------------------
    # Popups de erro / sucesso
    # ------------------------------------------------------------------

    def _build_message_content(self, message, icon_name="alert-circle-outline", icon_color_key="warning"):
        """Conteudo de dialogo com texto legivel (sem quebrar por coluna)."""
        tokens_fg = _theme_color('text_primary', (0.92, 0.94, 0.97, 1))
        tokens_muted = _theme_color('text_secondary', (0.55, 0.58, 0.63, 1))
        icon_color = _theme_color(icon_color_key, (0.9, 0.7, 0.15, 1))

        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(12),
            padding=[dp(4), dp(4), dp(4), dp(2)],
            size_hint_y=None,
        )
        content.bind(minimum_height=content.setter("height"))

        header = MDBoxLayout(size_hint_y=None, height=dp(28), spacing=dp(8))
        header.add_widget(MDIcon(
            icon=icon_name,
            theme_text_color="Custom",
            text_color=icon_color,
            size_hint=(None, None),
            size=(dp(24), dp(24)),
        ))
        header.add_widget(MDLabel(
            text="Aviso",
            bold=True,
            font_style="Body1",
            theme_text_color="Custom",
            text_color=tokens_fg,
            valign="middle",
        ))
        content.add_widget(header)

        body = MDLabel(
            text=str(message or ""),
            theme_text_color="Custom",
            text_color=tokens_muted,
            font_style="Body2",
            halign="left",
            valign="top",
            size_hint_y=None,
            text_size=(dp(400), None),
        )
        body.bind(
            texture_size=lambda inst, val: setattr(inst, "height", max(dp(48), val[1] + dp(4))),
            width=lambda inst, val: setattr(inst, "text_size", (max(dp(200), val - dp(8)), None)),
        )
        content.add_widget(body)
        return content

    def show_error_popup(self, message):
        if self.error_dialog:
            self.error_dialog.dismiss()
        content = self._build_message_content(message)
        self.error_dialog = MDDialog(
            title="",
            type="custom",
            content_cls=content,
            size_hint=(None, None),
            size=(min(dp(460), max(dp(320), Window.width * 0.88)), dp(240)),
            buttons=[MDRaisedButton(
                text="ENTENDI",
                md_bg_color=_theme_color('danger', (0.85, 0.3, 0.3, 1)),
                text_color=_theme_color('on_primary', (1, 1, 1, 1)),
                on_release=lambda x: self.error_dialog.dismiss(),
            )],
        )
        # Ajusta altura ao conteudo apos abrir
        def _fit(*_a):
            try:
                h = max(dp(200), float(content.height) + dp(100))
                self.error_dialog.height = min(h, max(dp(220), Window.height * 0.7))
                self.error_dialog.width = min(dp(480), max(dp(320), Window.width * 0.88))
                content.width = self.error_dialog.width - dp(40)
            except Exception:
                pass
        Clock.schedule_once(_fit, 0)
        Clock.schedule_once(_fit, 0.05)
        self.error_dialog.open()

    def show_success_popup(self, pdf_path):
        filename = os.path.basename(pdf_path)
        if self.success_dialog:
            self.success_dialog.dismiss()
        content = self._build_message_content(
            f"Relatorio gerado com sucesso.\n\n{filename}",
            icon_name="check-circle-outline",
            icon_color_key="success",
        )
        self.success_dialog = MDDialog(
            title="",
            type="custom",
            content_cls=content,
            size_hint=(None, None),
            size=(min(dp(480), max(dp(320), Window.width * 0.88)), dp(260)),
            buttons=[
                MDFlatButton(text="FECHAR", on_release=lambda x: self.success_dialog.dismiss()),
                MDFlatButton(text="IMPRIMIR PDF", on_release=lambda x: self._print_pdf_after_generation(pdf_path)),
                MDRaisedButton(
                    text="VISUALIZAR PDF",
                    md_bg_color=_theme_color('primary', (0.15, 0.52, 0.76, 1)),
                    on_release=lambda x: self._view_pdf_and_close(pdf_path),
                ),
            ],
        )
        def _fit(*_a):
            try:
                self.success_dialog.width = min(dp(500), max(dp(320), Window.width * 0.88))
                self.success_dialog.height = min(dp(300), max(dp(220), float(content.height) + dp(120)))
                content.width = self.success_dialog.width - dp(40)
            except Exception:
                pass
        Clock.schedule_once(_fit, 0)
        self.success_dialog.open()

    def _print_pdf_after_generation(self, pdf_path):
        if self.success_dialog:
            self.success_dialog.dismiss()
        viewer = self._ensure_pdf_viewer()
        if viewer.print_pdf(pdf_path):
            self.show_pdf_print_success_popup(pdf_path)
        else:
            self.show_pdf_print_ready_popup(
                pdf_path,
                getattr(viewer, "last_print_message", ""),
            )


    def show_pdf_print_ready_popup(self, pdf_path, message=""):
        filename = os.path.basename(pdf_path)
        if self.success_dialog:
            self.success_dialog.dismiss()
        guidance = str(message or "").strip() or (
            "Abra o PDF para concluir a impressao pelo leitor disponivel."
        )
        content = self._build_message_content(
            f"O PDF foi preparado:\n{filename}\n\n{guidance}",
            icon_name="printer-outline",
            icon_color_key="info",
        )
        self.success_dialog = MDDialog(
            title="",
            type="custom",
            content_cls=content,
            size_hint=(None, None),
            size=(min(dp(480), max(dp(320), Window.width * 0.88)), dp(280)),
            buttons=[
                MDFlatButton(text="FECHAR", on_release=lambda x: self.success_dialog.dismiss()),
                MDRaisedButton(
                    text="VISUALIZAR PDF",
                    md_bg_color=_theme_color('primary', (0.15, 0.52, 0.76, 1)),
                    on_release=lambda x: self._view_pdf_and_close(pdf_path),
                ),
            ],
        )
        self.success_dialog.open()

    def show_chart_print_success_popup(self, pdf_path):
        filename = os.path.basename(pdf_path)
        if self.success_dialog:
            self.success_dialog.dismiss()
        content = self._build_message_content(
            f"PDF preparado e enviado para impressao:\n{filename}",
            icon_name="check-circle-outline",
            icon_color_key="success",
        )
        self.success_dialog = MDDialog(
            title="",
            type="custom",
            content_cls=content,
            size_hint=(None, None),
            size=(min(dp(480), max(dp(320), Window.width * 0.88)), dp(240)),
            buttons=[
                MDFlatButton(text="FECHAR", on_release=lambda x: self.success_dialog.dismiss()),
                MDRaisedButton(
                    text="VISUALIZAR PDF",
                    md_bg_color=_theme_color('primary', (0.15, 0.52, 0.76, 1)),
                    on_release=lambda x: self._view_pdf_and_close(pdf_path),
                ),
            ],
        )
        self.success_dialog.open()

    def show_pdf_print_success_popup(self, pdf_path):
        filename = os.path.basename(pdf_path)
        if self.success_dialog:
            self.success_dialog.dismiss()
        content = self._build_message_content(
            f"Arquivo enviado para impressao:\n{filename}",
            icon_name="printer-check",
            icon_color_key="success",
        )
        self.success_dialog = MDDialog(
            title="",
            type="custom",
            content_cls=content,
            size_hint=(None, None),
            size=(min(dp(480), max(dp(320), Window.width * 0.88)), dp(240)),
            buttons=[
                MDFlatButton(text="FECHAR", on_release=lambda x: self.success_dialog.dismiss()),
                MDRaisedButton(
                    text="VISUALIZAR PDF",
                    md_bg_color=_theme_color('primary', (0.15, 0.52, 0.76, 1)),
                    on_release=lambda x: self._view_pdf_and_close(pdf_path),
                ),
            ],
        )
        self.success_dialog.open()


    def _view_pdf_and_close(self, pdf_path):
        if self.success_dialog:
            self.success_dialog.dismiss()
        self._ensure_pdf_viewer().view_pdf(pdf_path)

    # ------------------------------------------------------------------
    # AI
    # ------------------------------------------------------------------

    def show_ai_insights(self, *args):
        self.open_ai_menu()

    def open_ai_menu(self, caller=None):
        if caller is None and hasattr(self, "ids") and "ai_button" in self.ids:
            caller = self.ids.ai_button
        self._intelligence.open_alerts(caller=caller)

    def show_ai_recommendations(self, caller=None):
        if caller is None and hasattr(self, "ids") and "recommendations_button" in self.ids:
            caller = self.ids.recommendations_button
        self._intelligence.open_recommendations(caller=caller)

    def show_ai_stock_popup(self, *args, insights=None, on_close=None):
        self._intelligence.refresh()

    def show_ai_expiry_popup(self, *args, insights=None, on_close=None):
        self._intelligence.refresh()

    def show_auto_ai_popups(self, *args):
        self._intelligence.refresh()

    def update_ai_badge(self, *args):
        self.update_notification_badge(0)

    def _poll_ai_alerts(self, dt):
        self._intelligence.refresh()

    def _start_ai_polling(self):
        self._intelligence.start()

    def _stop_ai_polling(self):
        self._intelligence.stop()

    # ------------------------------------------------------------------
    # Navegação
    # ------------------------------------------------------------------

    def go_back(self):
        target = self.back_target if getattr(self, "back_target", None) in getattr(
            self.manager, "screen_names", []
        ) else "admin"
        self.manager.current = target
