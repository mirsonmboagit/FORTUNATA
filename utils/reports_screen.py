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
from kivymd.uix.list import OneLineListItem, TwoLineListItem
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
        self._field_navigation = FormKeyboardController(
            host=self,
            fields=[self.start_date_field, self.end_date_field],
            initial_field=self.start_date_field,
            on_escape=self.dismiss,
            on_submit=self.confirm,
            shortcuts={"ctrl+s": self.confirm},
        )
    
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

    def on_pre_open(self, *args):
        if hasattr(self, "_field_navigation"):
            self._field_navigation.activate(focus_initial=True)
        return super().on_pre_open(*args)

    def on_dismiss(self, *args):
        if hasattr(self, "_field_navigation"):
            self._field_navigation.deactivate()
        return super().on_dismiss(*args)
    
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
    FILTERS_CACHE_SECONDS = 60
    PRODUCTIVITY_CACHE_SECONDS = 15
    REPORT_CARD_SEARCH = (
        (
            "sales_report_card",
            "relatorio vendas venda faturamento receita desempenho saida ticket",
        ),
        (
            "stock_report_card",
            "relatorio estoque stock inventario niveis quantidades reposicao ruptura",
        ),
        (
            "profit_report_card",
            "relatorio lucro margem rentabilidade ganhos resultados financeiro",
        ),
        (
            "complete_report_card",
            "relatorio completo geral panorama executivo resumo analise total",
        ),
    )
    REPORT_BUTTON_LABELS = {
        "sales_report_card": "Relatorio de Vendas",
        "stock_report_card": "Relatorio de Estoque",
        "profit_report_card": "Relatorio de Lucro",
        "complete_report_card": "Relatorio Completo",
    }
    date_label = ObjectProperty(None)
    product_spinner = ObjectProperty(None)
    category_spinner = ObjectProperty(None)
    search_status_text = StringProperty(
        "Pesquise por tipo de relatorio, produto ou categoria para encontrar o que precisa mais rapido."
    )
    search_summary_text = StringProperty("4 relatorios prontos para gerar em PDF.")
    period_summary_text = StringProperty("Escolha um periodo")
    product_summary_text = StringProperty("Todos os Produtos")
    category_summary_text = StringProperty("Todas as Categorias")
    
    def __init__(self, **kwargs):
        db = kwargs.pop("db", None)
        self.db = db or get_db()
        self.back_target = "admin_home"
        self.notification_count = 0
        self.start_date = None
        self.end_date = None
        self.selected_product = None
        self.selected_category = None
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
        super(ReportsScreen, self).__init__(**kwargs)
        self._intelligence = ProactiveIntelligenceController(
            screen=self,
            db=self.db,
            history_title="Historico de monitorizacao dos relatorios",
            auto_present_enabled=False,
        )
        
        # Menus dropdown do KivyMD
        self.product_menu = None
        self.category_menu = None
        self._product_menu_signature = ()
        self._category_menu_signature = ()
        self.products_list = ['Todos os Produtos']
        self.categories_list = ['Todas as Categorias']
        self.filtered_products_list = list(self.products_list)
        self.filtered_categories_list = list(self.categories_list)
        self._report_card_ids = [card_id for card_id, _terms in self.REPORT_CARD_SEARCH]
        self._report_cards_by_id = {}
        
        # Dialogs
        self.date_dialog = None
        self.error_dialog = None
        self.success_dialog = None
        self.pdf_dialog = None
        self.delete_pdf_dialog = None
        
        # Inicializar geradores de relatório
        self.sales_report = None
        self.stock_report = None
        self.profit_report = None
        self.complete_report = None
        self.productivity_charts_report = None
        self.pdf_viewer = None

    def on_kv_post(self, base_widget):
        self._ensure_loading_overlay()
        self._ensure_productivity_dashboard()
        Clock.schedule_once(lambda dt: self._render_productivity_dashboard(), 0)
        self.bind(size=lambda *_args: self._schedule_responsive_layout())
        Clock.schedule_once(lambda dt: self._cache_report_cards(), 0)
        Clock.schedule_once(lambda dt: self._ensure_report_generators(), 0.05)
        Clock.schedule_once(lambda dt: self._refresh_filter_summary(), 0)
        Clock.schedule_once(lambda dt: self._apply_search_now(), 0)
        Clock.schedule_once(lambda dt: self._schedule_responsive_layout(), 0)
    
    def on_enter(self):
        """Chamado quando a tela é exibida."""
        self._ensure_filters_loaded()
        self._refresh_date_label()
        self._ensure_productivity_loaded(force=False)
        self._refresh_filter_summary()
        self._apply_search_now()
        Clock.schedule_once(self._init_badge, 0.1)
        Clock.schedule_once(lambda dt: self._start_ai_polling(), 0.15)

    def on_leave(self):
        self._stop_ai_polling()
        self._productivity_load_token += 1
        self._productivity_loading = False
        self._clear_loading_overlay()

        if self._filters_load_ev:
            self._filters_load_ev.cancel()
            self._filters_load_ev = None
        if self._responsive_ev:
            self._responsive_ev.cancel()
            self._responsive_ev = None
        if self._search_ev:
            self._search_ev.cancel()
            self._search_ev = None

    def _ensure_loading_overlay(self):
        if self._loading_controller is None:
            self._loading_controller = ScreenLoadingController(self)
        self._loading_controller.attach()
        return self._loading_controller

    def _set_loading_overlay(self, key, active, message="", detail=""):
        controller = self._ensure_loading_overlay()
        if active:
            controller.show(key, message, detail)
            return
        controller.hide(key)

    def _clear_loading_overlay(self):
        if self._loading_controller is not None:
            self._loading_controller.clear()

    @staticmethod
    def _normalize_search_text(text):
        normalized = unicodedata.normalize("NFKD", str(text or ""))
        return "".join(char for char in normalized if not unicodedata.combining(char)).strip().lower()

    @staticmethod
    def _truncate_text(text, limit=34):
        value = str(text or "").strip()
        if len(value) <= limit:
            return value or "-"
        return value[: max(limit - 3, 1)].rstrip() + "..."

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
                "report_generation",
                True,
                f"A gerar {report_label.lower()}...",
                "Estamos a compilar os dados e a preparar o PDF do periodo selecionado.",
            )
        else:
            self._set_loading_overlay("report_generation", False)
        for card_id, default_text in self.REPORT_BUTTON_LABELS.items():
            button = self._report_cards_by_id.get(card_id)
            if button is None and hasattr(self, "ids"):
                button = self.ids.get(card_id)
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
                "print_charts",
                True,
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
        mapping = {
            "sales": ("sales_report_card", "sales_report", "Relatorio de vendas"),
            "stock": ("stock_report_card", "stock_report", "Relatorio de estoque"),
            "profit": ("profit_report_card", "profit_report", "Relatorio de lucro"),
            "complete": ("complete_report_card", "complete_report", "Relatorio completo"),
        }
        return mapping.get(report_kind)

    def _schedule_responsive_layout(self, *args):
        if self._responsive_ev:
            self._responsive_ev.cancel()
        self._responsive_ev = Clock.schedule_once(lambda dt: self._update_responsive_layout(), 0)

    def _update_responsive_layout(self):
        self._responsive_ev = None
        if not hasattr(self, "ids"):
            return

        width = self.width or Window.width or dp(1200)
        header_card = self.ids.get("header_card")
        header_content = self.ids.get("header_content")
        header_actions = self.ids.get("header_actions")
        search_row = self.ids.get("search_row")
        filters_grid = self.ids.get("filters_grid")
        quick_range_grid = self.ids.get("quick_range_grid")
        reports_grid = self.ids.get("reports_grid")
        filter_actions = self.ids.get("filter_actions")
        print_charts_button = self.ids.get("print_charts_button")
        header_buttons = [
            self.ids.get("hero_pdf_button"),
            self.ids.get("hero_refresh_button"),
            self.ids.get("hero_back_button"),
        ]
        search_clear_button = self.ids.get("search_clear_button")
        filter_buttons = [
            self.ids.get("filter_reset_button"),
            self.ids.get("filter_refresh_button"),
        ]

        if header_content:
            header_content.orientation = "horizontal" if width >= dp(980) else "vertical"
        if header_actions:
            header_actions.orientation = "horizontal" if width >= dp(760) else "vertical"
            header_actions.spacing = dp(10)
            if width >= dp(760):
                header_actions.size_hint_x = 0.36
            else:
                header_actions.size_hint_x = 1
        if header_card:
            if width >= dp(1100):
                header_card.height = dp(74)
            elif width >= dp(760):
                header_card.height = dp(118)
            else:
                header_card.height = dp(166)

        if width >= dp(760):
            for button in header_buttons:
                if button is None:
                    continue
                button.size_hint_x = None
                button.width = dp(122)
        else:
            for button in header_buttons:
                if button is None:
                    continue
                button.size_hint_x = 1

        if search_row:
            search_row.orientation = "horizontal" if width >= dp(760) else "vertical"
        if search_clear_button:
            if width >= dp(760):
                search_clear_button.size_hint_x = None
                search_clear_button.width = dp(126)
            else:
                search_clear_button.size_hint_x = 1

        if filters_grid:
            filters_grid.cols = 2 if width >= dp(900) else 1
        if quick_range_grid:
            quick_range_grid.cols = 4 if width >= dp(980) else 2
        if filter_actions:
            filter_actions.orientation = "horizontal" if width >= dp(760) else "vertical"
        if width >= dp(760):
            for button in filter_buttons:
                if button is None:
                    continue
                button.size_hint_x = 0.5
            if print_charts_button is not None:
                print_charts_button.size_hint_x = None
                print_charts_button.width = dp(190)
        else:
            for button in filter_buttons:
                if button is None:
                    continue
                button.size_hint_x = 1
            if print_charts_button is not None:
                print_charts_button.size_hint_x = 1
        if reports_grid:
            reports_grid.cols = 2 if width >= dp(900) else 1

    def _refresh_filter_summary(self):
        if self.start_date and self.end_date:
            self.period_summary_text = f"{self.start_date.strftime('%d/%m/%Y')} a {self.end_date.strftime('%d/%m/%Y')}"
        else:
            self.period_summary_text = "Escolha um periodo"

        product_text = "Todos os Produtos"
        category_text = "Todas as Categorias"

        if hasattr(self, "product_spinner") and self.product_spinner:
            product_text = self.product_spinner.text
        elif hasattr(self, "ids") and "product_spinner" in self.ids:
            product_text = self.ids.product_spinner.text

        if hasattr(self, "category_spinner") and self.category_spinner:
            category_text = self.category_spinner.text
        elif hasattr(self, "ids") and "category_spinner" in self.ids:
            category_text = self.ids.category_spinner.text

        self.product_summary_text = self._truncate_text(product_text, limit=36)
        self.category_summary_text = self._truncate_text(category_text, limit=36)

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
        self._productivity_error = None
        self._productivity_loading = False
        self._productivity_payload = None
        self._productivity_last_loaded_at = 0.0

        if hasattr(self, "product_spinner") and self.product_spinner:
            self.product_spinner.text = "Todos os Produtos"
        if hasattr(self, "category_spinner") and self.category_spinner:
            self.category_spinner.text = "Todas as Categorias"

        self.clear_search()
        self._refresh_date_label()
        self._refresh_filter_summary()
        self._render_productivity_dashboard()

    def refresh_screen_data(self):
        self._ensure_filters_loaded(force=True)
        self._ensure_productivity_loaded(force=True)
        self._apply_search_now()

    def apply_today_range(self):
        today = datetime.now()
        start = today.replace(hour=0, minute=0, second=0, microsecond=0)
        end = today.replace(hour=23, minute=59, second=59, microsecond=0)
        self.set_date_range(start, end)

    def apply_last_days_range(self, days):
        today = datetime.now()
        end = today.replace(hour=23, minute=59, second=59, microsecond=0)
        start = (today - timedelta(days=max(int(days) - 1, 0))).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        self.set_date_range(start, end)

    def apply_current_month_range(self):
        today = datetime.now()
        start = datetime(today.year, today.month, 1)
        end = today.replace(hour=23, minute=59, second=59, microsecond=0)
        self.set_date_range(start, end)

    def _clear_pending_report_callback(self):
        self._pending_report_callback = None

    def _on_date_picker_cancel(self, *args):
        self._date_picker = None
        self._clear_pending_report_callback()

    def _on_date_picker_save(self, instance, value, date_range):
        self._date_picker = None

        selected_range = [day for day in (date_range or []) if day is not None]
        if selected_range:
            start_date = min(selected_range)
            end_date = max(selected_range)
        elif value is not None:
            start_date = value
            end_date = value
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
        base_date = datetime.now().date()
        kwargs = {
            "mode": "range",
            "year": base_date.year,
            "month": base_date.month,
            "day": base_date.day,
        }

        if self.start_date and self.end_date:
            start_date = self.start_date.date()
            end_date = self.end_date.date()
            kwargs.update(
                year=start_date.year,
                month=start_date.month,
                day=start_date.day,
            )
            if start_date < end_date:
                kwargs["min_date"] = start_date
                kwargs["max_date"] = end_date

        return kwargs

    def _filter_options(self, items, default_item, query):
        source = list(items or [default_item])
        if not query:
            return source

        default_items = [item for item in source if item == default_item]
        filtered_items = [
            item
            for item in source
            if item != default_item and query in self._normalize_search_text(item)
        ]
        return default_items + filtered_items

    def _get_matching_report_ids(self, query):
        if not query:
            return list(self._report_card_ids)
        matches = []
        for card_id, search_terms in self.REPORT_CARD_SEARCH:
            if query in self._normalize_search_text(search_terms):
                matches.append(card_id)
        return matches

    def _render_report_cards(self, card_ids):
        grid = self.ids.get("reports_grid") if hasattr(self, "ids") else None
        if grid is None:
            return 0

        if not self._report_cards_by_id:
            return 0

        grid.clear_widgets()
        for card_id in self._report_card_ids:
            if card_id not in card_ids:
                continue
            card = self._report_cards_by_id.get(card_id)
            if card is not None:
                grid.add_widget(card)

        empty_state = self.ids.get("reports_empty_state")
        if empty_state is not None:
            empty_state.size_hint_y = None
            empty_state.height = dp(112) if not card_ids else 0
            empty_state.opacity = 1 if not card_ids else 0
            empty_state.disabled = bool(card_ids)
        return len(card_ids)

    def _update_search_feedback(
        self,
        query,
        visible_report_ids,
        matched_report_ids,
        product_matches,
        category_matches,
    ):
        total_products = max(len(product_matches) - 1, 0)
        total_categories = max(len(category_matches) - 1, 0)
        raw_query = (self._pending_search or "").strip()

        if not query:
            self.search_status_text = (
                "Pesquise por vendas, estoque, lucro, completo, produto ou categoria."
            )
            self.search_summary_text = "4 relatorios prontos para gerar em PDF."
            return

        if not visible_report_ids and total_products == 0 and total_categories == 0:
            self.search_status_text = f"Nenhum resultado encontrado para \"{raw_query}\"."
            self.search_summary_text = "Ajuste a pesquisa para voltar a mostrar relatorios e filtros."
            return

        if matched_report_ids:
            self.search_status_text = (
                f"{len(matched_report_ids)} relatorio(s) em destaque, "
                f"{total_products} produto(s) e {total_categories} categoria(s) relacionados."
            )
            self.search_summary_text = (
                f"{len(matched_report_ids)} relatorio(s) filtrados por \"{raw_query}\"."
            )
            return

        self.search_status_text = (
            f"Pesquisa aplicada aos filtros: {total_products} produto(s) e "
            f"{total_categories} categoria(s) encontrados."
        )
        self.search_summary_text = "Todos os relatorios continuam disponiveis para a pesquisa atual."

    def _apply_search_now(self, *args):
        self._search_ev = None
        if hasattr(self, "ids") and "report_search_input" in self.ids:
            self._pending_search = self.ids.report_search_input.text

        query = self._normalize_search_text(self._pending_search)
        self.filtered_products_list = self._filter_options(
            self.products_list,
            "Todos os Produtos",
            query,
        )
        self.filtered_categories_list = self._filter_options(
            self.categories_list,
            "Todas as Categorias",
            query,
        )
        self._invalidate_product_menu()
        self._invalidate_category_menu()

        matched_report_ids = self._get_matching_report_ids(query)
        product_match_count = max(len(self.filtered_products_list) - 1, 0)
        category_match_count = max(len(self.filtered_categories_list) - 1, 0)

        if not query:
            visible_report_ids = list(self._report_card_ids)
        elif matched_report_ids:
            visible_report_ids = matched_report_ids
        elif product_match_count > 0 or category_match_count > 0:
            visible_report_ids = list(self._report_card_ids)
        else:
            visible_report_ids = []

        self._render_report_cards(visible_report_ids)
        self._update_search_feedback(
            query,
            visible_report_ids,
            matched_report_ids,
            self.filtered_products_list,
            self.filtered_categories_list,
        )

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

    def _ensure_pdf_viewer(self):
        if self.pdf_viewer is None:
            from pdfs.pdf_viewer import PDFViewer
            self.pdf_viewer = PDFViewer(error_callback=self.show_error_popup)
        return self.pdf_viewer

    def prepare_open_from_admin(self):
        self._ensure_filters_loaded()
        self._ensure_productivity_loaded(force=False)

    def _ensure_filters_loaded(self, force=False):
        if self._filters_loading:
            return
        age = perf_counter() - self._filters_last_loaded_at
        if not force and self._filters_loaded and age < self.FILTERS_CACHE_SECONDS:
            return
        if self._filters_load_ev:
            self._filters_load_ev.cancel()
        self._filters_load_ev = Clock.schedule_once(lambda dt: self.load_filters(), 0.08)

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
            "productivity",
            True,
            "A carregar produtividade...",
            "Estamos a montar os graficos, caixas lideres e destaques do periodo.",
        )
        self._render_productivity_dashboard()

        start_dt = self.start_date.strftime("%Y-%m-%d %H:%M:%S")
        end_dt = self.end_date.strftime("%Y-%m-%d %H:%M:%S")

        def worker():
            payload = None
            error = None
            try:
                payload = self.db.get_productivity_report_data(start_dt, end_dt) or {}
            except Exception as exc:
                error = str(exc)
            if (payload is None or payload == {}) and error is None:
                last_error_fn = getattr(self.db, "last_error", None)
                if callable(last_error_fn):
                    error = last_error_fn()
            Clock.schedule_once(
                lambda dt, data=payload, err=error, tok=token: self._apply_productivity_payload(
                    data,
                    error=err,
                    token=tok,
                ),
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
                f"{int(leader.get('sales_count') or 0)} vendas e {float(leader.get('revenue') or 0):.2f} MZN."
            )

        best_day = summary.get("best_day") or {}
        if best_day:
            insights.append(
                f"O pico ocorreu em {datetime.fromisoformat(str(best_day.get('date'))).strftime('%d/%m')} "
                f"com {int(best_day.get('sales_count') or 0)} vendas e {float(best_day.get('revenue') or 0):.2f} MZN."
            )

        if len(daily_series) >= 5 and len(insights) < 4:
            avg_sales = sum(int(item.get("sales_count") or 0) for item in daily_series) / max(len(daily_series), 1)
            worst_day = min(
                daily_series,
                key=lambda item: (
                    int(item.get("sales_count") or 0),
                    float(item.get("revenue") or 0.0),
                    str(item.get("date") or ""),
                ),
            )
            if avg_sales > 0 and int(worst_day.get("sales_count") or 0) < (avg_sales * 0.65):
                insights.append(
                    f"Houve quebra relevante em {datetime.fromisoformat(str(worst_day.get('date'))).strftime('%d/%m')}, "
                    f"abaixo do ritmo médio do período."
                )

        avg_discount = float(summary.get("avg_discount_percent") or 0.0)
        if len(insights) < 4:
            for item in terminal_series:
                sales_count = int(item.get("sales_count") or 0)
                discount_percent = float(item.get("discount_percent") or 0.0)
                if sales_count < 5:
                    continue
                if (avg_discount > 0 and discount_percent > (avg_discount * 1.25)) or (
                    avg_discount <= 0 and discount_percent >= 5.0
                ):
                    insights.append(
                        f"Caixa {item.get('terminal_id')} aplicou desconto médio acima do padrão do período."
                    )
                    break

        avg_margin = summary.get("avg_margin_percent")
        if len(insights) < 4 and avg_margin is not None:
            comparable = [item for item in terminal_series if item.get("margin_percent") is not None]
            if len(comparable) >= 2:
                weakest = min(
                    comparable,
                    key=lambda item: (
                        float(item.get("margin_percent") or 0.0),
                        -int(item.get("sales_count") or 0),
                    ),
                )
                if float(weakest.get("margin_percent") or 0.0) <= (float(avg_margin) - 5.0):
                    insights.append(
                        f"Caixa {weakest.get('terminal_id')} fechou com margem abaixo da média do período."
                    )

        if len(insights) <= 2:
            insights.append("Operação estável no período, sem desvios fortes entre os caixas.")

        return insights[:4]

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
        self._filters_load_ev = None
        if self._filters_loading:
            return
        started_at = perf_start()
        token = self._filters_load_token + 1
        self._filters_load_token = token
        self._filters_loading = True
        self._set_loading_overlay(
            "filters",
            True,
            "A carregar filtros dos relatorios...",
            "Estamos a atualizar produtos, categorias e opcoes disponiveis.",
        )

        def worker():
            products = []
            categories = []
            error = None
            try:
                products = self.db.get_products_for_filter() or []
                categories = self.db.get_categories() or []
            except Exception as exc:
                error = exc

            Clock.schedule_once(
                lambda dt, prods=products, cats=categories, err=error, tok=token, started=started_at: self._apply_loaded_filters(
                    prods,
                    cats,
                    err,
                    tok,
                    started,
                ),
                0,
            )

        Thread(target=worker, daemon=True).start()

    def _apply_loaded_filters(self, products, categories, error, token, started_at):
        if token != self._filters_load_token:
            return
        try:
            if error:
                print(f"Erro ao carregar filtros: {error}")
                return

            new_products = ['Todos os Produtos'] + [f"{prod[0]} - {prod[1]}" for prod in (products or [])]
            new_categories = ['Todas as Categorias'] + list(categories or [])
            if new_products != self.products_list:
                self.products_list = new_products
                self.filtered_products_list = list(new_products)
                self._invalidate_product_menu()
            if new_categories != self.categories_list:
                self.categories_list = new_categories
                self.filtered_categories_list = list(new_categories)
                self._invalidate_category_menu()
            self._filters_loaded = True
            self._filters_last_loaded_at = perf_counter()
            self._refresh_filter_summary()
            self._apply_search_now()
            perf_log(
                "reports.load_filters",
                started_at,
                f"products={len(self.products_list)} categories={len(self.categories_list)}",
            )
        finally:
            self._filters_loading = False
            self._set_loading_overlay("filters", False)
    
    # ----------------------------------------------------------------
    # Dropdown Menus para Produto e Categoria
    # ----------------------------------------------------------------
    def open_product_menu(self, item):
        """Abrir menu dropdown de produtos."""
        self._ensure_product_menu(item)
        if self.product_menu is None:
            return
        self.product_menu.open()
    
    def select_product(self, product_name):
        """Selecionar produto do menu."""
        if hasattr(self, 'product_spinner') and self.product_spinner:
            self.product_spinner.text = product_name
        self.product_menu.dismiss()
        self.update_product_selection(None, product_name)
        self._refresh_filter_summary()
    
    def open_category_menu(self, item):
        """Abrir menu dropdown de categorias."""
        self._ensure_category_menu(item)
        if self.category_menu is None:
            return
        self.category_menu.open()

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

    def _ensure_product_menu(self, caller):
        source_items = self.filtered_products_list or self.products_list or ["Todos os Produtos"]
        signature = tuple(source_items)
        if self.product_menu is not None and self._product_menu_signature == signature:
            self.product_menu.caller = caller
            return
        self._invalidate_product_menu()
        self._product_menu_signature = signature
        menu_items = [
            {
                "text": product,
                "viewclass": "OneLineListItem",
                "on_release": lambda x=product: self.select_product(x),
            }
            for product in source_items
        ]
        self.product_menu = MDDropdownMenu(
            caller=caller,
            items=menu_items,
            width_mult=4,
            max_height=dp(300),
        )

    def _ensure_category_menu(self, caller):
        source_items = self.filtered_categories_list or self.categories_list or ["Todas as Categorias"]
        signature = tuple(source_items)
        if self.category_menu is not None and self._category_menu_signature == signature:
            self.category_menu.caller = caller
            return
        self._invalidate_category_menu()
        self._category_menu_signature = signature
        menu_items = [
            {
                "text": category,
                "viewclass": "OneLineListItem",
                "on_release": lambda x=category: self.select_category(x),
            }
            for category in source_items
        ]
        self.category_menu = MDDropdownMenu(
            caller=caller,
            items=menu_items,
            width_mult=4,
            max_height=dp(300),
        )
    
    def select_category(self, category_name):
        """Selecionar categoria do menu."""
        if hasattr(self, 'category_spinner') and self.category_spinner:
            self.category_spinner.text = category_name
        self.category_menu.dismiss()
        self.update_category_selection(None, category_name)
        self._refresh_filter_summary()
    
    # ----------------------------------------------------------------
    # Seleção de Datas com Dialog Customizado
    # ----------------------------------------------------------------
    def _legacy_select_date_range(self):
        """Abre dialog customizado de seleção de período."""
        self.date_dialog = DateRangeDialog(database=self.db, callback=self.set_date_range)
        self.date_dialog.open()
    
    def select_date_range(self, on_complete=None):
        """Abre calendario para selecionar o periodo do relatorio."""
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
        """Define o período selecionado."""
        self.start_date = start
        self.end_date = end
        self._refresh_date_label()
        self._refresh_filter_summary()
        self._ensure_productivity_loaded(force=True)

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
        self._refresh_filter_summary()
    
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
    def _legacy_validate_filters(self):
        """Valida se os filtros necessários foram selecionados."""
        if not self.start_date or not self.end_date:
            self.show_error_popup('Selecione um periodo para gerar o relatorio')
            return False
        return True
    
    def validate_filters(self, on_missing_period=None):
        """Valida se os filtros necessarios foram selecionados."""
        if not self.start_date or not self.end_date:
            if callable(on_missing_period):
                self.select_date_range(on_complete=on_missing_period)
            else:
                self.select_date_range()
            return False
        return True

    def get_filtered_data(self, start_date=None, end_date=None, selected_product=None, selected_category=None):
        """Obtém dados filtrados do banco de dados."""
        start_date = start_date or self.start_date
        end_date = end_date or self.end_date
        if not start_date or not end_date:
            return None

        product_id = self.selected_product if selected_product is None else selected_product
        category = self.selected_category if selected_category is None else selected_category
        start_dt = start_date.strftime("%Y-%m-%d %H:%M:%S")
        end_dt = end_date.strftime("%Y-%m-%d %H:%M:%S")
        try:
            rows = self.db.get_report_data(
                start_dt,
                end_dt,
                product_id=product_id,
                category=category,
            )
            if not rows:
                return None

            df = pd.DataFrame(rows)
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
            expiry_values = df['expiry_date'] if 'expiry_date' in df.columns else [None] * len(df)
            expiry_alerts = [evaluate_expiry_alert(value) for value in expiry_values]
            df['expiry_alert_level'] = [item['level'] for item in expiry_alerts]
            df['expiry_alert_label'] = [item['label'] for item in expiry_alerts]
            df['expiry_alert_short'] = [item['short_label'] for item in expiry_alerts]
            df['expiry_days_left'] = [item['days_left'] for item in expiry_alerts]
            df['expiry_alert_color'] = [item['color_hex'] for item in expiry_alerts]
            df['expiry_has_alert'] = [bool(item['is_alert']) for item in expiry_alerts]

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

    def _finish_report_generation(self):
        self._set_report_generation_busy(False)
        self._apply_search_now()
        self._refresh_filter_summary()

    def _generate_report_async(self, report_kind):
        config = self._report_config(report_kind)
        if config is None or self._report_generation_busy:
            return

        button_id, generator_attr, report_label = config
        callback_name = f"generate_{report_kind}_report"
        callback = getattr(self, callback_name, None)
        if not self.validate_filters(on_missing_period=callback):
            return

        start_date = self.start_date
        end_date = self.end_date
        selected_product = self.selected_product
        selected_category = self.selected_category
        filters_dict = dict(self._get_filters_dict())
        self._ensure_report_generators()

        self._set_report_generation_busy(True, button_id=button_id, status_text="A gerar...")
        self.search_status_text = f"{report_label} em preparação..."
        self.search_summary_text = "Os dados estão a ser processados em segundo plano."

        def worker():
            try:
                df = self.get_filtered_data(
                    start_date=start_date,
                    end_date=end_date,
                    selected_product=selected_product,
                    selected_category=selected_category,
                )
                if df is None:
                    return {"status": "empty"}
                generator = getattr(self, generator_attr, None)
                if generator is None:
                    raise RuntimeError("Gerador de relatório indisponível")
                pdf_path = generator.generate(df, filters_dict)
                return {"status": "ok", "pdf_path": pdf_path}
            except Exception as exc:
                return {"status": "error", "message": str(exc)}

        def apply_result(result):
            self._finish_report_generation()
            status = (result or {}).get("status")
            if status == "ok":
                self.show_success_popup(result.get("pdf_path"))
                return
            if status == "empty":
                self.show_error_popup('Nenhum dado encontrado para os filtros selecionados')
                return
            message = (result or {}).get("message") or "Erro ao gerar relatório."
            self.show_error_popup(f'Erro ao gerar relatorio:\n{message}')
            print(f"Erro detalhado: {message}")

        def finish_worker():
            result = worker()
            Clock.schedule_once(lambda dt, payload=result: apply_result(payload), 0)

        Thread(target=finish_worker, daemon=True).start()
    
    # ----------------------------------------------------------------
    # Geração de Relatórios
    # ----------------------------------------------------------------
    def generate_sales_report(self):
        """Gera relatório de vendas."""
        self._generate_report_async("sales")
    
    def generate_stock_report(self):
        """Gera relatório de estoque."""
        self._generate_report_async("stock")
    
    def generate_profit_report(self):
        """Gera relatório de lucro."""
        self._generate_report_async("profit")
    
    def generate_complete_report(self):
        """Gera relatório completo."""
        self._generate_report_async("complete")

    def print_productivity_charts(self):
        """Gera e imprime um PDF contendo apenas os graficos de produtividade."""
        if self._printing_charts_busy:
            return

        if not self.validate_filters(on_missing_period=self.print_productivity_charts):
            return

        start_date = self.start_date
        end_date = self.end_date
        filters_dict = {
            "start_date": start_date,
            "end_date": end_date,
            "product": "Nao se aplica",
            "category": "Nao se aplica",
        }
        self._ensure_report_generators()

        self._set_print_charts_busy(True)
        self.search_status_text = "Graficos em preparacao para impressao..."
        self.search_summary_text = "Apenas os graficos principais serao enviados para PDF."

        def worker():
            try:
                start_dt = start_date.strftime("%Y-%m-%d %H:%M:%S")
                end_dt = end_date.strftime("%Y-%m-%d %H:%M:%S")
                payload = self.db.get_productivity_report_data(start_dt, end_dt) or {}
                summary = payload.get("summary") or {}
                total_sales = int(summary.get("total_sales") or 0)
                if total_sales <= 0:
                    return {"status": "empty"}

                generator = self.productivity_charts_report
                if generator is None:
                    raise RuntimeError("Gerador de graficos indisponivel")

                pdf_path = generator.generate(payload, filters_dict)
                return {"status": "ok", "pdf_path": pdf_path}
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
                if printed:
                    self.show_chart_print_success_popup(pdf_path)
                else:
                    self.show_success_popup(pdf_path)
                return
            if status == "empty":
                self.show_error_popup("Nao ha graficos com vendas no periodo selecionado.")
                return

            message = (result or {}).get("message") or "Erro ao preparar os graficos."
            self.show_error_popup(f"Erro ao imprimir graficos:\n{message}")

        def finish_worker():
            result = worker()
            Clock.schedule_once(lambda dt, payload=result: apply_result(payload), 0)

        Thread(target=finish_worker, daemon=True).start()
    
    # ----------------------------------------------------------------
    # Visualizador de PDFs
    # ----------------------------------------------------------------
    def _get_available_pdf_files(self):
        """Retorna os PDFs gerados, ordenados do mais recente para o mais antigo."""
        pdf_files = []
        seen = set()
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

        pdf_files.sort(key=lambda path: os.path.getmtime(path), reverse=True)
        return pdf_files

    def show_pdf_viewer(self):
        """Mostra lista de PDFs disponíveis."""
        pdf_files = self._get_available_pdf_files()

        if not pdf_files:
            self.show_error_popup('Nenhum PDF encontrado na pasta de relatorios.')
            return

        self._create_pdf_list_dialog(pdf_files)
    
    def _create_pdf_list_dialog(self, pdf_files):
        """Cria dialog com lista de PDFs usando KivyMD."""
        if self.pdf_dialog:
            self.pdf_dialog.dismiss()

        content_height = min(dp(460), Window.height * 0.62)
        scroll_height = max(dp(220), content_height - dp(78))

        body = MDBoxLayout(
            orientation='vertical',
            spacing=dp(12),
            size_hint_y=None,
            height=content_height,
            padding=[dp(16), dp(12), dp(16), dp(10)]
        )

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
        body.add_widget(header)
        body.add_widget(MDSeparator(height=dp(1)))

        pdf_list = MDBoxLayout(
            orientation='vertical',
            spacing=dp(8),
            size_hint_y=None,
            padding=[0, dp(8)]
        )
        pdf_list.bind(minimum_height=pdf_list.setter('height'))
        
        for pdf_path in pdf_files:
            pdf_list.add_widget(self._create_pdf_list_item(pdf_path))

        scroll = ScrollView(
            size_hint=(1, None),
            height=scroll_height,
            do_scroll_x=False,
            do_scroll_y=True,
            bar_width=dp(4),
        )
        scroll.add_widget(pdf_list)
        body.add_widget(scroll)
        
        # Dialog
        self.pdf_dialog = MDDialog(
            title=f"PDFs Disponiveis ({len(pdf_files)})",
            type="custom",
            content_cls=body,
            size_hint=(None, None),
            size=(min(dp(980), Window.width * 0.9), min(dp(620), Window.height * 0.76)),
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
        
        title_label = MDLabel(
            text=display_name,
            font_style='Subtitle1',
            bold=True,
            halign='left',
            valign='middle',
            theme_text_color='Custom',
            text_color=_theme_color('text_primary', (0.2, 0.2, 0.2, 1)),
            size_hint_y=None,
            height=dp(25),
            shorten=True,
            shorten_from='right',
            max_lines=1,
        )
        title_label.bind(size=lambda inst, _: setattr(inst, "text_size", (inst.width, None)))
        info_box.add_widget(title_label)
        
        subtitle_label = MDLabel(
            text=subtitle,
            font_style='Caption',
            halign='left',
            valign='middle',
            theme_text_color='Custom',
            text_color=_theme_color('text_secondary', (0.5, 0.5, 0.5, 1)),
            size_hint_y=None,
            height=dp(18),
            shorten=True,
            shorten_from='right',
            max_lines=1,
        )
        subtitle_label.bind(size=lambda inst, _: setattr(inst, "text_size", (inst.width, None)))
        info_box.add_widget(subtitle_label)
        
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

    def _create_pdf_list_item(self, pdf_path):
        """Cria uma linha de PDF com acoes de visualizar e eliminar."""
        file_size = os.path.getsize(pdf_path) / 1024
        mod_time = datetime.fromtimestamp(os.path.getmtime(pdf_path))

        parts = pdf_path.split(os.sep)
        pdf_filename = parts[-1]

        if len(parts) >= 4:
            report_type = parts[-3]
            report_date = parts[-2]
            display_name = f"{report_type} - {report_date}"
            subtitle = pdf_filename
        else:
            display_name = pdf_filename
            subtitle = pdf_filename

        meta_text = f"{mod_time.strftime('%d/%m/%Y %H:%M')} | {file_size:.1f} KB"

        item = MDCard(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(138),
            padding=[dp(12), dp(10)],
            spacing=dp(12),
            elevation=1,
            radius=[dp(10)],
            md_bg_color=_theme_color('card_alt', (0.98, 0.98, 0.98, 1)),
        )

        info_box = MDBoxLayout(
            orientation='vertical',
            spacing=dp(4),
        )

        title_label = MDLabel(
            text=self._truncate_text(display_name, 56),
            font_style='Subtitle1',
            bold=True,
            halign='left',
            valign='middle',
            theme_text_color='Custom',
            text_color=_theme_color('text_primary', (0.2, 0.2, 0.2, 1)),
            size_hint_y=None,
            height=dp(24),
            shorten=True,
            shorten_from='right',
            max_lines=1,
        )
        title_label.bind(size=lambda inst, _: setattr(inst, "text_size", (inst.width, None)))
        info_box.add_widget(title_label)

        subtitle_label = MDLabel(
            text=self._truncate_text(subtitle, 76),
            font_style='Caption',
            halign='left',
            valign='middle',
            theme_text_color='Custom',
            text_color=_theme_color('text_secondary', (0.45, 0.45, 0.45, 1)),
            size_hint_y=None,
            height=dp(18),
            shorten=True,
            shorten_from='right',
            max_lines=1,
        )
        subtitle_label.bind(size=lambda inst, _: setattr(inst, "text_size", (inst.width, None)))
        info_box.add_widget(subtitle_label)

        meta_label = MDLabel(
            text=meta_text,
            font_style='Caption',
            halign='left',
            valign='middle',
            theme_text_color='Custom',
            text_color=_theme_color('text_secondary', (0.5, 0.5, 0.5, 1)),
            size_hint_y=None,
            height=dp(18),
        )
        meta_label.bind(size=lambda inst, _: setattr(inst, "text_size", (inst.width, None)))
        info_box.add_widget(meta_label)

        item.add_widget(info_box)

        actions_box = MDBoxLayout(
            orientation='vertical',
            size_hint=(None, 1),
            width=dp(120),
            spacing=dp(8),
        )

        actions_box.add_widget(MDRaisedButton(
            text="Visualizar",
            size_hint=(None, None),
            size=(dp(110), dp(34)),
            pos_hint={"center_x": 0.5},
            md_bg_color=_theme_color('primary', (0.15, 0.52, 0.76, 1)),
            on_release=lambda _x, path=pdf_path: self._view_and_close_dialog(path),
        ))

        actions_box.add_widget(MDRaisedButton(
            text="Imprimir",
            size_hint=(None, None),
            size=(dp(110), dp(34)),
            pos_hint={"center_x": 0.5},
            md_bg_color=_theme_color('success', (0.2, 0.65, 0.33, 1)),
            on_release=lambda _x, path=pdf_path: self._print_pdf_from_list(path),
        ))

        actions_box.add_widget(MDRaisedButton(
            text="Eliminar",
            size_hint=(None, None),
            size=(dp(110), dp(34)),
            pos_hint={"center_x": 0.5},
            md_bg_color=_theme_color('danger', (0.85, 0.3, 0.3, 1)),
            on_release=lambda _x, path=pdf_path: self._confirm_delete_pdf(path),
        ))

        item.add_widget(actions_box)
        return item

    def _print_pdf_from_list(self, pdf_path):
        """Imprime o PDF selecionado diretamente da lista."""
        printed = self._ensure_pdf_viewer().print_pdf(pdf_path)
        if printed:
            self.show_pdf_print_success_popup(pdf_path)

    def _dismiss_delete_pdf_dialog(self):
        dialog = getattr(self, 'delete_pdf_dialog', None)
        if dialog:
            dialog.dismiss()
            self.delete_pdf_dialog = None

    def _confirm_delete_pdf(self, pdf_path):
        """Pede confirmacao antes de eliminar o PDF."""
        self._dismiss_delete_pdf_dialog()
        filename = os.path.basename(pdf_path)

        self.delete_pdf_dialog = MDDialog(
            title="Eliminar PDF",
            text=f"Quer eliminar este arquivo?\n{filename}",
            buttons=[
                MDFlatButton(
                    text="CANCELAR",
                    on_release=lambda _x: self._dismiss_delete_pdf_dialog()
                ),
                MDRaisedButton(
                    text="ELIMINAR",
                    md_bg_color=_theme_color('danger', (0.85, 0.3, 0.3, 1)),
                    on_release=lambda _x, path=pdf_path: self._delete_pdf_and_refresh(path)
                ),
            ],
        )
        self.delete_pdf_dialog.open()

    def _delete_pdf_and_refresh(self, pdf_path):
        """Elimina o arquivo selecionado e recarrega a lista."""
        self._dismiss_delete_pdf_dialog()

        try:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
        except OSError as exc:
            self.show_error_popup(f"Nao foi possivel eliminar o PDF:\n{exc}")
            return

        remaining_files = self._get_available_pdf_files()

        if self.pdf_dialog:
            self.pdf_dialog.dismiss()
            self.pdf_dialog = None

        if remaining_files:
            self._create_pdf_list_dialog(remaining_files)
        else:
            self.show_error_popup('Nenhum PDF encontrado na pasta de relatorios.')
    
    def _view_and_close_dialog(self, pdf_path):
        """Visualiza PDF e fecha dialog."""
        if hasattr(self, 'pdf_dialog'):
            self.pdf_dialog.dismiss()
        self._ensure_pdf_viewer().view_pdf(pdf_path)
    
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
                MDFlatButton(
                    text="IMPRIMIR PDF",
                    on_release=lambda x: self._print_pdf_after_generation(pdf_path)
                ),
                MDRaisedButton(
                    text="VISUALIZAR PDF",
                    md_bg_color=_theme_color('primary', (0.15, 0.52, 0.76, 1)),
                    on_release=lambda x: self._view_pdf_and_close(pdf_path)
                ),
            ],
        )
        self.success_dialog.open()

    def _print_pdf_after_generation(self, pdf_path):
        """Imprime o PDF a partir do popup de sucesso."""
        if self.success_dialog:
            self.success_dialog.dismiss()
        printed = self._ensure_pdf_viewer().print_pdf(pdf_path)
        if printed:
            self.show_pdf_print_success_popup(pdf_path)

    def show_chart_print_success_popup(self, pdf_path):
        """Mostra confirmacao apos enviar o PDF de graficos para impressao."""
        filename = os.path.basename(pdf_path)

        if self.success_dialog:
            self.success_dialog.dismiss()

        self.success_dialog = MDDialog(
            title="Graficos enviados",
            text=f"PDF preparado e enviado para impressao:\n{filename}",
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

    def show_pdf_print_success_popup(self, pdf_path):
        """Mostra confirmacao apos enviar um PDF para impressao."""
        filename = os.path.basename(pdf_path)

        if self.success_dialog:
            self.success_dialog.dismiss()

        self.success_dialog = MDDialog(
            title="PDF enviado",
            text=f"Arquivo enviado para impressao:\n{filename}",
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
        self._ensure_pdf_viewer().view_pdf(pdf_path)

    def show_ai_insights(self, *args):
        self.open_ai_menu()

    def open_ai_menu(self, caller=None):
        if caller is None and hasattr(self, "ids") and "ai_button" in self.ids:
            caller = self.ids.ai_button
        self._intelligence.open_history(caller=caller)

    def _open_ai_from_menu(self, key):
        caller = self.ids.ai_button if hasattr(self, "ids") and "ai_button" in self.ids else None
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
    
    # ----------------------------------------------------------------
    # Navegação
    # ----------------------------------------------------------------
    def go_back(self):
        """Volta para a tela anterior."""
        target = self.back_target if getattr(self, "back_target", None) in getattr(self.manager, "screen_names", []) else "admin"
        self.manager.current = target
