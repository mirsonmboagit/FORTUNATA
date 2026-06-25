import os
import sys
import unicodedata
from pathlib import Path

from utils.paths import ROOT_DIR, report_search_dirs

sys.path.insert(
    0,
    str((ROOT_DIR / "pdfs").resolve())
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
from kivymd.uix.list import OneLineListItem
from kivymd.uix.card import MDSeparator
from kivymd.uix.pickers import MDDatePicker
from AI.controller import ProactiveIntelligenceController
import pandas as pd

from datetime import datetime, timedelta
from threading import Thread
from time import perf_counter
from kivy.metrics import dp, sp
from kivy.uix.scrollview import ScrollView
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.app import App
from kivy.animation import Animation
from kivy.lang import Builder
from kivy.properties import ObjectProperty, StringProperty

from database.provider import get_db
from ui.components.hover_widgets import HoverCard, HoverRaisedButton
from ui.components.loading_overlay import ScreenLoadingController
from utils.expiry_alerts import evaluate_expiry_alert
from utils.focus_navigation import FormKeyboardController
from utils.perf_utils import perf_start, perf_log


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
            title="Selecionar Periodo",
            type="custom",
            content_cls=content,
            size_hint=(None, None),
            size=(min(dp(500), Window.width * 0.85), min(dp(450), Window.height * 0.7)),
            buttons=[
                MDFlatButton(text="CANCELAR", on_release=lambda x: self.dismiss()),
                MDRaisedButton(
                    text="CONFIRMAR PERIODO",
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
            height=dp(56),
        )
        main_layout.add_widget(self.start_date_field)

        self.end_date_field = MDTextField(
            hint_text="Data Final (DD/MM/AAAA)",
            mode="rectangle",
            size_hint_y=None,
            height=dp(56),
        )
        main_layout.add_widget(self.end_date_field)

        main_layout.add_widget(MDLabel(
            text='Ou escolha um atalho:',
            font_style='Subtitle2',
            bold=True,
            halign='left',
            theme_text_color='Custom',
            text_color=_theme_color('text_primary', (0.3, 0.3, 0.3, 1)),
            size_hint_y=None,
            height=dp(25),
        ))

        shortcuts_layout = MDGridLayout(
            cols=2, spacing=dp(8), size_hint_y=None, height=dp(90), adaptive_height=True,
        )
        for label, func in [
            ("Hoje", self.set_today),
            ("7 Dias", lambda: self.set_days(7)),
            ("30 Dias", lambda: self.set_days(30)),
            ("Este Mes", self.set_this_month),
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
                min(dp(500), Window.width * 0.85),
                min(dp(450), Window.height * 0.7),
            )

    def on_pre_open(self, *args):
        if hasattr(self, "_field_navigation"):
            self._field_navigation.activate(focus_initial=True)
        return super().on_pre_open(*args)

    def on_dismiss(self, *args):
        if hasattr(self, "_field_navigation"):
            self._field_navigation.deactivate()
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
        d = MDDialog(
            title="Formato Invalido",
            text=message,
            buttons=[MDRaisedButton(
                text="ENTENDI",
                md_bg_color=_theme_color('danger', (0.85, 0.3, 0.3, 1)),
                on_release=lambda x: d.dismiss(),
            )],
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
    • ai_banner_container mantido no .kv para o historico inteligente.
    """

    FILTERS_CACHE_SECONDS = 60
    PRODUCTIVITY_CACHE_SECONDS = 15
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
        "sales_report_card": "Relatorio de Vendas",
        "stock_report_card": "Relatorio de Estoque",
        "profit_report_card": "Relatorio de Lucro",
        "complete_report_card": "Relatorio Completo",
        "cash_user_report_card": "Relatorio de Caixa por Utilizador",
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
        super().__init__(**kwargs)
        self._intelligence = ProactiveIntelligenceController(
            screen=self,
            db=self.db,
            history_title="Historico de monitorizacao dos relatorios",
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
        self._productivity_loading = False
        self._clear_loading_overlay()
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
                "Estamos a compilar os dados e a preparar o PDF do periodo selecionado.",
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
                "Os graficos estao a ser organizados para gerar o PDF final.",
            )
        else:
            self._set_loading_overlay("print_charts", False)
        button = self.ids.get("print_charts_button") if hasattr(self, "ids") else None
        if button is None:
            return
        button.disabled = self._printing_charts_busy
        button.text = "A preparar..." if self._printing_charts_busy else "Imprimir Graficos"

    @staticmethod
    def _report_config(report_kind):
        return {
            "sales": ("sales_report_card", "sales_report", "Relatorio de vendas"),
            "stock": ("stock_report_card", "stock_report", "Relatorio de estoque"),
            "profit": ("profit_report_card", "profit_report", "Relatorio de lucro"),
            "complete": ("complete_report_card", "complete_report", "Relatorio completo"),
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
        if not hasattr(self, "ids"):
            return
        width = self.width or Window.width or dp(1200)
        ids = self.ids

        header_card    = ids.get("header_card")
        header_content = ids.get("header_content")
        header_actions = ids.get("header_actions")
        search_row     = ids.get("search_row")
        filters_grid   = ids.get("filters_grid")
        seller_row     = ids.get("seller_filter_row")
        quick_range    = ids.get("quick_range_grid")
        reports_grid   = ids.get("reports_grid")
        filter_actions = ids.get("filter_actions")
        print_btn      = ids.get("print_charts_button")
        header_btns    = [ids.get(k) for k in ("hero_pdf_button", "hero_refresh_button", "hero_back_button")]
        search_clear   = ids.get("search_clear_button")
        filter_btns    = [ids.get("filter_reset_button"), ids.get("filter_refresh_button")]

        is_wide  = width >= dp(980)
        is_mid   = width >= dp(760)
        is_large = width >= dp(900)

        if header_content:
            header_content.orientation = "horizontal" if is_wide else "vertical"
        if header_actions:
            header_actions.orientation = "horizontal" if is_mid else "vertical"
            header_actions.size_hint_x = 0.36 if is_mid else 1
        if header_card:
            header_card.height = dp(74) if width >= dp(1100) else (dp(118) if is_mid else dp(166))

        for btn in header_btns:
            if btn is None:
                continue
            if is_mid:
                btn.size_hint_x = None
                btn.width = dp(122)
            else:
                btn.size_hint_x = 1

        if search_row:
            search_row.orientation = "horizontal" if is_mid else "vertical"
        if search_clear:
            if is_mid:
                search_clear.size_hint_x = None
                search_clear.width = dp(110)
            else:
                search_clear.size_hint_x = 1

        if filters_grid:
            filters_grid.cols = 2 if is_large else 1
            filters_grid.height = dp(64) if is_large else dp(136)
        if seller_row:
            seller_row.orientation = "horizontal" if is_mid else "vertical"
            seller_row.height = dp(48) if is_mid else dp(76)
        if quick_range:
            quick_range.cols = 4 if is_wide else 2
        if filter_actions:
            filter_actions.orientation = "horizontal" if is_mid else "vertical"
        for btn in filter_btns:
            if btn:
                btn.size_hint_x = 0.5 if is_mid else 1
        if print_btn:
            if is_mid:
                print_btn.size_hint_x = None
                print_btn.width = dp(190)
            else:
                print_btn.size_hint_x = 1
        if reports_grid:
            reports_grid.cols = 2 if is_large else 1

    # ------------------------------------------------------------------
    # Resumo de filtros
    # ------------------------------------------------------------------

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
        self._search_ev = Clock.schedule_once(lambda dt: self._apply_search_now(), 0.16)

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
        """Abre o calendário. Chamado APENAS por acção explícita do utilizador."""
        self._pending_report_callback = on_complete if callable(on_complete) else None
        if self.date_dialog:
            self.date_dialog.dismiss()
            self.date_dialog = None
        picker = MDDatePicker(**self._build_date_picker_kwargs())
        picker.title = "Selecionar Periodo"
        picker.bind(on_save=self._on_date_picker_save, on_cancel=self._on_date_picker_cancel)
        self._date_picker = picker
        picker.open()

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

        Se não há período, mostra um aviso amigável e NÃO abre o calendário
        automaticamente. O utilizador deverá clicar em "Selecionar Periodo".
        """
        if not self.start_date or not self.end_date:
            self.show_error_popup(
                "Por favor, selecione um periodo antes de gerar o relatorio.\n\n"
                "Use os atalhos rapidos (Hoje, 7 Dias, 30 Dias, Este Mes) ou\n"
                "clique em 'Selecionar Periodo' para escolher um intervalo."
            )
            return False
        return True

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
    # Menus dropdown
    # ------------------------------------------------------------------

    def open_product_menu(self, item):
        self._ensure_product_menu(item)
        if self.product_menu:
            self.product_menu.open()

    def select_product(self, product_name):
        if hasattr(self, 'product_spinner') and self.product_spinner:
            self.product_spinner.text = product_name
        if self.product_menu:
            self.product_menu.dismiss()
        self.update_product_selection(None, product_name)
        self._refresh_filter_summary()

    def open_category_menu(self, item):
        self._ensure_category_menu(item)
        if self.category_menu:
            self.category_menu.open()

    def select_category(self, category_name):
        if hasattr(self, 'category_spinner') and self.category_spinner:
            self.category_spinner.text = category_name
        if self.category_menu:
            self.category_menu.dismiss()
        self.update_category_selection(None, category_name)
        self._refresh_filter_summary()

    def open_seller_menu(self, item):
        self._ensure_seller_menu(item)
        if self.seller_menu:
            self.seller_menu.open()

    def select_seller(self, seller_name):
        if hasattr(self, 'seller_spinner') and self.seller_spinner:
            self.seller_spinner.text = seller_name
        if self.seller_menu:
            self.seller_menu.dismiss()
        self.update_seller_selection(None, seller_name)
        self._refresh_filter_summary()

    def _invalidate_product_menu(self):
        if self.product_menu:
            self.product_menu.dismiss()
            self.product_menu = None
        self._product_menu_signature = ()

    def _invalidate_category_menu(self):
        if self.category_menu:
            self.category_menu.dismiss()
            self.category_menu = None
        self._category_menu_signature = ()

    def _invalidate_seller_menu(self):
        if self.seller_menu:
            self.seller_menu.dismiss()
            self.seller_menu = None
        self._seller_menu_signature = ()

    def _ensure_product_menu(self, caller):
        source = self.filtered_products_list or self.products_list or ["Todos os Produtos"]
        sig = tuple(source)
        if self.product_menu is not None and self._product_menu_signature == sig:
            self.product_menu.caller = caller
            return
        self._invalidate_product_menu()
        self._product_menu_signature = sig
        self.product_menu = MDDropdownMenu(
            caller=caller,
            items=[{"text": p, "viewclass": "OneLineListItem",
                    "on_release": lambda x=p: self.select_product(x)} for p in source],
            width_mult=4,
            max_height=dp(300),
        )

    def _ensure_category_menu(self, caller):
        source = self.filtered_categories_list or self.categories_list or ["Todas as Categorias"]
        sig = tuple(source)
        if self.category_menu is not None and self._category_menu_signature == sig:
            self.category_menu.caller = caller
            return
        self._invalidate_category_menu()
        self._category_menu_signature = sig
        self.category_menu = MDDropdownMenu(
            caller=caller,
            items=[{"text": c, "viewclass": "OneLineListItem",
                    "on_release": lambda x=c: self.select_category(x)} for c in source],
            width_mult=4,
            max_height=dp(300),
        )

    def _ensure_seller_menu(self, caller):
        source = self.filtered_sellers_list or self.sellers_list or ["Todos os Vendedores"]
        sig = tuple(source)
        if self.seller_menu is not None and self._seller_menu_signature == sig:
            self.seller_menu.caller = caller
            return
        self._invalidate_seller_menu()
        self._seller_menu_signature = sig
        self.seller_menu = MDDropdownMenu(
            caller=caller,
            items=[{"text": s, "viewclass": "OneLineListItem",
                    "on_release": lambda x=s: self.select_seller(x)} for s in source],
            width_mult=4,
            max_height=dp(300),
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
                f"{len(matched_ids)} relatorio(s) em destaque, "
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

    def _ensure_report_generators(self):
        if self.sales_report is None:
            from pdfs.sales_report import SalesReport
            self.sales_report = SalesReport()
        if self.stock_report is None:
            from pdfs.stock_report import StockReport
            self.stock_report = StockReport()
        if self.profit_report is None:
            from pdfs.profit_report import ProfitReport
            self.profit_report = ProfitReport()
        if self.complete_report is None:
            from pdfs.complete_report import CompleteReport
            self.complete_report = CompleteReport()
        if self.productivity_charts_report is None:
            from pdfs.productivity_charts_report import ProductivityChartsReport
            self.productivity_charts_report = ProductivityChartsReport()
        if self.cash_user_report is None:
            from pdfs.cash_user_report import CashUserReport
            self.cash_user_report = CashUserReport()

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
            "Estamos a montar os graficos, caixas lideres e destaques do periodo.",
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
            insights.append("Operação estável no período, sem desvios fortes entre os caixas.")
        return insights[:4]

    # ------------------------------------------------------------------
    # Badge e animação do botão AI
    # ------------------------------------------------------------------

    def _init_badge(self, dt):
        if hasattr(self.ids, 'ai_badge'):
            self.ids.ai_badge.opacity = 0

    def add_notification(self):
        self.notification_count += 1
        self.update_notification_badge(self.notification_count)

    def clear_notifications(self):
        self.notification_count = 0
        self.update_notification_badge(0)

    def update_notification_badge(self, count):
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
        if not hasattr(self.ids, 'ai_badge'):
            return
        self.ids.ai_badge.size = (dp(0), dp(0))
        self.ids.ai_badge.opacity = 1
        Animation(size=(dp(24), dp(24)), duration=0.3, transition='out_back').start(self.ids.ai_badge)

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
                          selected_seller=None):
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
            expiry_vals = df['expiry_date'] if 'expiry_date' in df.columns else [None] * len(df)
            alerts = [evaluate_expiry_alert(v) for v in expiry_vals]
            df['expiry_alert_level']  = [a['level']       for a in alerts]
            df['expiry_alert_label']  = [a['label']       for a in alerts]
            df['expiry_alert_short']  = [a['short_label'] for a in alerts]
            df['expiry_days_left']    = [a['days_left']   for a in alerts]
            df['expiry_alert_color']  = [a['color_hex']   for a in alerts]
            df['expiry_has_alert']    = [bool(a['is_alert']) for a in alerts]
            if df['sold_stock'].sum() == 0:
                return None
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
        config = self._report_config(report_kind)
        if config is None or self._report_generation_busy:
            return
        button_id, generator_attr, report_label = config
        if not self.validate_filters():
            return

        start_date = self.start_date
        end_date   = self.end_date
        selected_product  = self.selected_product
        selected_category = self.selected_category
        selected_seller = self.selected_seller
        filters_dict = dict(self._get_filters_dict())
        self._ensure_report_generators()
        self._set_report_generation_busy(True, button_id=button_id, status_text="A gerar...")
        self.search_status_text  = f"{report_label} em preparação..."
        self.search_summary_text = "Os dados estão a ser processados em segundo plano."

        def worker():
            try:
                df = self.get_filtered_data(
                    start_date=start_date, end_date=end_date,
                    selected_product=selected_product, selected_category=selected_category,
                    selected_seller=selected_seller,
                )
                if df is None:
                    return {"status": "empty"}
                generator = getattr(self, generator_attr, None)
                if generator is None:
                    raise RuntimeError("Gerador de relatório indisponível")
                return {"status": "ok", "pdf_path": generator.generate(df, filters_dict)}
            except Exception as exc:
                return {"status": "error", "message": str(exc)}

        def apply_result(result):
            self._finish_report_generation()
            status = (result or {}).get("status")
            if status == "ok":
                self.show_success_popup(result.get("pdf_path"))
            elif status == "empty":
                self.show_error_popup('Nenhum dado encontrado para os filtros selecionados')
            else:
                msg = (result or {}).get("message") or "Erro ao gerar relatório."
                self.show_error_popup(f'Erro ao gerar relatorio:\n{msg}')
                print(f"Erro detalhado: {msg}")

        Thread(target=lambda: Clock.schedule_once(
            lambda dt, r=worker(): apply_result(r), 0), daemon=True).start()

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
        if not self.validate_filters():
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
        self.search_summary_text = "A consolidar abertura, fechamento e vendas por operador."

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
            if status == "ok":
                self.show_success_popup(result.get("pdf_path"))
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
        if not self.validate_filters():
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
                printed = self._ensure_pdf_viewer().print_pdf(pdf_path)
                self.show_chart_print_success_popup(pdf_path) if printed else self.show_success_popup(pdf_path)
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
            for root, dirs, files in os.walk(report_dir):
                for file in files:
                    if not file.lower().endswith('.pdf'):
                        continue
                    full_path = os.path.join(root, file)
                    if full_path in seen:
                        continue
                    seen.add(full_path)
                    pdf_files.append(full_path)
        pdf_files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return pdf_files

    def show_pdf_viewer(self):
        pdf_files = self._get_available_pdf_files()
        if not pdf_files:
            self.show_error_popup('Nenhum PDF encontrado na pasta de relatorios.')
            return
        self._create_pdf_list_dialog(pdf_files)

    def _create_pdf_list_dialog(self, pdf_files):
        if self.pdf_dialog:
            self.pdf_dialog.dismiss()

        content_height = min(dp(460), Window.height * 0.62)
        scroll_height  = max(dp(220), content_height - dp(78))

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
        header.add_widget(MDLabel(
            text=f"{len(pdf_files)} item(ns)", font_style='Caption', halign='right',
            theme_text_color='Custom', text_color=_theme_color('text_secondary', (0.5, 0.5, 0.5, 1)),
        ))
        body.add_widget(header)
        body.add_widget(MDSeparator(height=dp(1)))

        pdf_list = MDBoxLayout(orientation='vertical', spacing=dp(8),
                               size_hint_y=None, padding=[0, dp(8)])
        pdf_list.bind(minimum_height=pdf_list.setter('height'))
        for pdf_path in pdf_files:
            pdf_list.add_widget(self._create_pdf_list_item(pdf_path))

        scroll = ScrollView(size_hint=(1, None), height=scroll_height,
                            do_scroll_x=False, bar_width=dp(4))
        scroll.add_widget(pdf_list)
        body.add_widget(scroll)

        self.pdf_dialog = MDDialog(
            title=f"PDFs Disponiveis ({len(pdf_files)})",
            type="custom", content_cls=body,
            size_hint=(None, None),
            size=(min(dp(980), Window.width * 0.9), min(dp(620), Window.height * 0.76)),
            buttons=[MDFlatButton(text="FECHAR", on_release=lambda x: self.pdf_dialog.dismiss())],
        )
        self.pdf_dialog.open()

    def _create_pdf_list_item(self, pdf_path):
        file_size = os.path.getsize(pdf_path) / 1024
        mod_time  = datetime.fromtimestamp(os.path.getmtime(pdf_path))
        parts = pdf_path.split(os.sep)
        pdf_filename = parts[-1]
        if len(parts) >= 4:
            display_name = f"{parts[-3]} - {parts[-2]}"
            subtitle = pdf_filename
        else:
            display_name = pdf_filename
            subtitle = pdf_filename
        meta_text = f"{mod_time.strftime('%d/%m/%Y %H:%M')} | {file_size:.1f} KB"

        item = MDCard(
            orientation='horizontal', size_hint_y=None, height=dp(138),
            padding=[dp(12), dp(10)], spacing=dp(12), elevation=1,
            radius=[dp(10)], md_bg_color=_theme_color('card_alt', (0.98, 0.98, 0.98, 1)),
        )
        info_box = MDBoxLayout(orientation='vertical', spacing=dp(4))
        for text, style, bold, h, color_key in [
            (self._truncate_text(display_name, 56), 'Subtitle1', True,  dp(24), 'text_primary'),
            (self._truncate_text(subtitle, 76),     'Caption',   False, dp(18), 'text_secondary'),
            (meta_text,                             'Caption',   False, dp(18), 'text_secondary'),
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

        actions_box = MDBoxLayout(orientation='vertical', size_hint=(None, 1),
                                  width=dp(120), spacing=dp(8))
        for text, color_key, callback in [
            ("Visualizar", 'primary',  lambda _x, p=pdf_path: self._view_and_close_dialog(p)),
            ("Imprimir",   'success',  lambda _x, p=pdf_path: self._print_pdf_from_list(p)),
            ("Eliminar",   'danger',   lambda _x, p=pdf_path: self._confirm_delete_pdf(p)),
        ]:
            actions_box.add_widget(MDRaisedButton(
                text=text, size_hint=(None, None), size=(dp(110), dp(34)),
                pos_hint={"center_x": 0.5},
                md_bg_color=_theme_color(color_key, (0.5, 0.5, 0.5, 1)),
                on_release=callback,
            ))
        item.add_widget(actions_box)
        return item

    def _print_pdf_from_list(self, pdf_path):
        if self._ensure_pdf_viewer().print_pdf(pdf_path):
            self.show_pdf_print_success_popup(pdf_path)

    def _dismiss_delete_pdf_dialog(self):
        dlg = getattr(self, 'delete_pdf_dialog', None)
        if dlg:
            dlg.dismiss()
            self.delete_pdf_dialog = None

    def _confirm_delete_pdf(self, pdf_path):
        self._dismiss_delete_pdf_dialog()
        filename = os.path.basename(pdf_path)
        self.delete_pdf_dialog = MDDialog(
            title="Eliminar PDF",
            text=f"Quer eliminar este arquivo?\n{filename}",
            buttons=[
                MDFlatButton(text="CANCELAR", on_release=lambda _: self._dismiss_delete_pdf_dialog()),
                MDRaisedButton(
                    text="ELIMINAR",
                    md_bg_color=_theme_color('danger', (0.85, 0.3, 0.3, 1)),
                    on_release=lambda _, p=pdf_path: self._delete_pdf_and_refresh(p),
                ),
            ],
        )
        self.delete_pdf_dialog.open()

    def _delete_pdf_and_refresh(self, pdf_path):
        self._dismiss_delete_pdf_dialog()
        try:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
        except OSError as exc:
            self.show_error_popup(f"Nao foi possivel eliminar o PDF:\n{exc}")
            return
        remaining = self._get_available_pdf_files()
        if self.pdf_dialog:
            self.pdf_dialog.dismiss()
            self.pdf_dialog = None
        if remaining:
            self._create_pdf_list_dialog(remaining)
        else:
            self.show_error_popup('Nenhum PDF encontrado na pasta de relatorios.')

    def _view_and_close_dialog(self, pdf_path):
        if hasattr(self, 'pdf_dialog') and self.pdf_dialog:
            self.pdf_dialog.dismiss()
        self._ensure_pdf_viewer().view_pdf(pdf_path)

    # ------------------------------------------------------------------
    # Popups de erro / sucesso
    # ------------------------------------------------------------------

    def show_error_popup(self, message):
        if self.error_dialog:
            self.error_dialog.dismiss()
        self.error_dialog = MDDialog(
            title="Atencao", text=message,
            buttons=[MDRaisedButton(
                text="ENTENDI",
                md_bg_color=_theme_color('danger', (0.85, 0.3, 0.3, 1)),
                on_release=lambda x: self.error_dialog.dismiss(),
            )],
        )
        self.error_dialog.open()

    def show_success_popup(self, pdf_path):
        filename = os.path.basename(pdf_path)
        if self.success_dialog:
            self.success_dialog.dismiss()
        self.success_dialog = MDDialog(
            title="Sucesso", text=f"Relatorio gerado:\n{filename}",
            buttons=[
                MDFlatButton(text="FECHAR",       on_release=lambda x: self.success_dialog.dismiss()),
                MDFlatButton(text="IMPRIMIR PDF",  on_release=lambda x: self._print_pdf_after_generation(pdf_path)),
                MDRaisedButton(
                    text="VISUALIZAR PDF",
                    md_bg_color=_theme_color('primary', (0.15, 0.52, 0.76, 1)),
                    on_release=lambda x: self._view_pdf_and_close(pdf_path),
                ),
            ],
        )
        self.success_dialog.open()

    def _print_pdf_after_generation(self, pdf_path):
        if self.success_dialog:
            self.success_dialog.dismiss()
        if self._ensure_pdf_viewer().print_pdf(pdf_path):
            self.show_pdf_print_success_popup(pdf_path)

    def show_chart_print_success_popup(self, pdf_path):
        filename = os.path.basename(pdf_path)
        if self.success_dialog:
            self.success_dialog.dismiss()
        self.success_dialog = MDDialog(
            title="Graficos enviados", text=f"PDF preparado e enviado para impressao:\n{filename}",
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
        self.success_dialog = MDDialog(
            title="PDF enviado", text=f"Arquivo enviado para impressao:\n{filename}",
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
        self._intelligence.open_history(caller=caller)

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
