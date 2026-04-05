from datetime import datetime
import os
import sys
from threading import Thread
from time import perf_counter

from kivy.app import App
from kivy.animation import Animation
from kivy.clock import Clock
from kivy.factory import Factory
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import StringProperty
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.card import MDCard
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDIcon, MDLabel
from kivymd.uix.screen import MDScreen

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from AI.controller import ProactiveIntelligenceController
from database.provider import get_db
from ui.components.admin_home_dashboard import SalesTrendChart
from ui.components.tooltip_widgets import TooltipFloatingActionButton
from utils.ai_popups import build_positive_banner, render_auto_banners


Builder.load_file(os.path.join(CURRENT_DIR, "admin_home_screen.kv"))

def _set_label_text_color(label, color):
    label.theme_text_color = "Custom"
    label.text_color = color


def _format_mzn(value):
    try:
        return f"{float(value):,.2f} MZN".replace(",", " ")
    except Exception:
        return "0.00 MZN"


def _format_value(value):
    if value is None:
        return "--"
    try:
        if isinstance(value, float):
            return f"{value:,.2f}".replace(",", " ")
        return str(int(value))
    except Exception:
        return str(value)


def _format_compact_qty(value):
    try:
        amount = float(value or 0)
    except Exception:
        return "0"
    if abs(amount - round(amount)) < 0.01:
        return str(int(round(amount)))
    return f"{amount:.2f}".rstrip("0").rstrip(".")


class AdminHomeScreen(MDScreen):
    HOME_CACHE_SECONDS = 20
    home_title = StringProperty("Painel do Administrador")
    home_subtitle = StringProperty("Visao geral operacional do negocio")
    datetime_text = StringProperty("")
    status_text = StringProperty("A carregar resumo operacional...")

    def __init__(self, **kwargs):
        db = kwargs.pop("db", None)
        self.db = db or get_db()
        self.notification_count = 0
        self._snapshot = None
        self._snapshot_error = None
        self._snapshot_loading = False
        self._snapshot_loaded_at = 0.0
        self._snapshot_token = 0
        self._clock_ev = None
        self._sales_chart = None
        self._summary_render_signature = None
        self._alerts_render_signature = None
        self._insights_render_signature = None
        self._today_sales_dialog = None
        self._today_sales_loading = False
        self._intelligence = ProactiveIntelligenceController(
            screen=self,
            db=self.db,
            history_title="Historico de monitorizacao",
            banner_columns=1,
            auto_batch_size=2,
            auto_stagger_seconds=2.0,
            auto_present_enabled=True,
        )
        super().__init__(**kwargs)

    def on_kv_post(self, base_widget):
        self._ensure_chart_widgets()
        self._build_quick_actions()
        self._update_datetime_text()
        self._update_responsive_layout()
        Clock.schedule_once(self._init_badge, 0.05)
        self._render_dashboard()

    def on_enter(self):
        self._start_clock()
        self._ensure_snapshot_loaded(force=False)
        app = App.get_running_app()
        warmup = getattr(app, "warmup_screens", None)
        if callable(warmup):
            # O primeiro clique ficava lento porque a tela alvo era criada
            # inteira apenas no momento do on_release.
            Clock.schedule_once(
                lambda dt: warmup(
                    ("admin", "reports", "sales_history", "restock", "losses", "settings"),
                    delay=0.12,
                ),
                0.22,
            )
        Clock.schedule_once(lambda dt: self._start_ai_polling(), 0.1)

    def on_leave(self):
        if self._clock_ev:
            self._clock_ev.cancel()
            self._clock_ev = None
        self._stop_ai_polling()
        self._snapshot_token += 1
        self._snapshot_loading = False

    def on_size(self, *args):
        Clock.schedule_once(lambda dt: self._update_responsive_layout(), 0)

    def _start_clock(self):
        self._update_datetime_text()
        if self._clock_ev:
            self._clock_ev.cancel()
        self._clock_ev = Clock.schedule_interval(lambda dt: self._update_datetime_text(), 30)

    def _init_badge(self, dt):
        badge = self.ids.get("ai_badge") if hasattr(self, "ids") else None
        if badge is not None:
            badge.opacity = 0
            badge.size = (dp(0), dp(0))

    def update_notification_badge(self, count):
        self.notification_count = int(count or 0)
        badge = self.ids.get("ai_badge") if hasattr(self, "ids") else None
        badge_label = self.ids.get("ai_badge_label") if hasattr(self, "ids") else None
        if badge is None or badge_label is None:
            return
        badge_label.text = str(self.notification_count)
        if self.notification_count > 0:
            self._show_badge()
        else:
            self._hide_badge()

    def _show_badge(self):
        badge = self.ids.get("ai_badge") if hasattr(self, "ids") else None
        if badge is None:
            return
        Animation.cancel_all(badge)
        badge.opacity = 1
        badge.size = (dp(0), dp(0))
        Animation(
            size=(dp(24), dp(24)),
            duration=0.25,
            transition="out_back",
        ).start(badge)

    def _hide_badge(self):
        badge = self.ids.get("ai_badge") if hasattr(self, "ids") else None
        if badge is None:
            return
        Animation.cancel_all(badge)
        Animation(
            opacity=0,
            size=(dp(0), dp(0)),
            duration=0.18,
            transition="out_quad",
        ).start(badge)

    def _start_ai_polling(self):
        self._intelligence.start()

    def _stop_ai_polling(self):
        self._intelligence.stop()

    def _update_datetime_text(self):
        self.datetime_text = datetime.now().strftime("%d/%m/%Y | %H:%M")

    def _apply_hero_button_layout(self, fill_width):
        button_specs = (
            ("hero_add_button", dp(96)),
            ("hero_reports_button", dp(96)),
            ("hero_pdfs_button", dp(84)),
        )
        for button_id, default_width in button_specs:
            button = self.ids.get(button_id)
            if button is None:
                continue
            if fill_width:
                button.size_hint_x = 1
                button.width = 0
            else:
                button.size_hint_x = None
                button.width = default_width

    def _update_responsive_layout(self):
        if not self.ids:
            return
        width = self.width or dp(1200)

        hero_card = self.ids.get("hero_card")
        summary_grid = self.ids.get("summary_grid")
        summary_card = self.ids.get("summary_card")
        alerts_grid = self.ids.get("alerts_grid")
        alerts_card = self.ids.get("alerts_card")
        quick_actions_grid = self.ids.get("quick_actions_grid")
        quick_actions_card = self.ids.get("quick_actions_card")
        insights_grid = self.ids.get("insights_grid")
        insights_card = self.ids.get("insights_card")
        hero_content = self.ids.get("hero_content")
        hero_actions = self.ids.get("hero_actions")
        hero_side = self.ids.get("hero_side")
        left_col = self.ids.get("left_col")
        right_col = self.ids.get("right_col")

        if width >= dp(1280):
            summary_cols = 4
            side_cols = 2
            hero_orientation = "horizontal"
            hero_side_fill = False
            hero_height = dp(106)
            summary_height = dp(148)
            left_ratio, right_ratio = 0.67, 0.33
            card_ratios = (0.34, 0.40, 0.26)
            hero_buttons_fill = False
        elif width >= dp(1060):
            summary_cols = 2
            side_cols = 2
            hero_orientation = "horizontal"
            hero_side_fill = False
            hero_height = dp(120)
            summary_height = dp(242)
            left_ratio, right_ratio = 0.61, 0.39
            card_ratios = (0.34, 0.40, 0.26)
            hero_buttons_fill = False
        else:
            summary_cols = 2
            side_cols = 1
            hero_orientation = "vertical"
            hero_side_fill = True
            hero_height = dp(168)
            summary_height = dp(242)
            left_ratio, right_ratio = 0.57, 0.43
            card_ratios = (0.34, 0.34, 0.32)
            hero_buttons_fill = True

        if summary_grid:
            summary_grid.cols = summary_cols
        if alerts_grid:
            alerts_grid.cols = side_cols
        if quick_actions_grid:
            quick_actions_grid.cols = side_cols
        if insights_grid:
            insights_grid.cols = side_cols

        if hero_card is not None:
            hero_card.height = hero_height
        if summary_card is not None:
            summary_card.height = summary_height
        if alerts_card is not None:
            alerts_card.size_hint_y = card_ratios[0]
        if quick_actions_card is not None:
            quick_actions_card.size_hint_y = card_ratios[1]
        if insights_card is not None:
            insights_card.size_hint_y = card_ratios[2]

        if hero_content:
            hero_content.orientation = hero_orientation
            hero_content.spacing = dp(14)
        if hero_side:
            if hero_side_fill:
                hero_side.size_hint_x = 1
                hero_side.width = 0
            else:
                hero_side.size_hint_x = None
                hero_side.width = dp(300)
        if hero_actions:
            hero_actions.orientation = "horizontal"
            hero_actions.spacing = dp(8)
            hero_actions.height = dp(36)
        self._apply_hero_button_layout(hero_buttons_fill)

        if left_col and right_col:
            left_col.size_hint_x = left_ratio
            right_col.size_hint_x = right_ratio

    def _ensure_chart_widgets(self):
        sales_host = self.ids.get("sales_chart_host") if hasattr(self, "ids") else None
        if sales_host and self._sales_chart is None:
            self._sales_chart = SalesTrendChart()
            self._sales_chart.size_hint_y = 1
            sales_host.add_widget(self._sales_chart)

    def refresh_home(self, *args):
        self._ensure_snapshot_loaded(force=True)

    def _ensure_snapshot_loaded(self, force=False):
        if self._snapshot_loading:
            return
        age = perf_counter() - self._snapshot_loaded_at
        if not force and self._snapshot is not None and age < self.HOME_CACHE_SECONDS:
            self._render_dashboard()
            return
        self._load_snapshot_async()

    def _load_snapshot_async(self):
        token = self._snapshot_token + 1
        self._snapshot_token = token
        self._snapshot_loading = True
        self._snapshot_error = None
        self.status_text = "A carregar resumo operacional..."
        self._render_dashboard()

        def worker():
            payload = None
            error = None
            try:
                payload = self.db.get_admin_home_snapshot(lookback_days=7) or {}
            except Exception as exc:
                error = str(exc)
            if (payload is None or payload == {}) and error is None:
                last_error_fn = getattr(self.db, "last_error", None)
                if callable(last_error_fn):
                    error = last_error_fn()
            Clock.schedule_once(
                lambda dt, data=payload, err=error, tok=token: self._apply_snapshot(data, err, tok),
                0,
            )

        Thread(target=worker, daemon=True).start()

    def _apply_snapshot(self, payload, error=None, token=None):
        if token is not None and token != self._snapshot_token:
            return
        self._snapshot_loading = False
        self._snapshot_loaded_at = perf_counter()
        self._snapshot_error = str(error).strip() if error else None
        self._snapshot = payload or {}
        self._render_dashboard()

    def _render_dashboard(self):
        snapshot = self._snapshot or {}
        self._render_header(snapshot)
        self._render_summary_cards(snapshot.get("summary") or {})
        self._render_alert_cards(snapshot.get("alerts") or {})
        self._render_insights(snapshot)

        if self._sales_chart:
            if self._snapshot_error:
                self._sales_chart.set_state_text("Falha ao carregar indicadores.")
            elif self._snapshot_loading and not snapshot:
                self._sales_chart.set_state_text("A carregar tendencia de vendas...")
            elif not snapshot:
                self._sales_chart.set_state_text("Indicadores visuais serao carregados apos o resumo inicial.")
            else:
                self._sales_chart.set_series(snapshot.get("sales_series") or [])

    def _render_header(self, snapshot):
        app = App.get_running_app()
        username = (getattr(app, "current_user", None) or "Administrador").strip() or "Administrador"
        first_name = username.split()[0]
        hour = datetime.now().hour
        greeting = "Bom dia" if hour < 12 else ("Boa tarde" if hour < 18 else "Boa noite")
        self.home_title = f"{greeting}, {first_name}"
        self.home_subtitle = self._build_header_subtitle(snapshot)

        if self._snapshot_error:
            self.status_text = "Resumo indisponivel no momento. Os atalhos continuam ativos."
        elif self._snapshot_loading and not snapshot:
            self.status_text = "A carregar sinais do negocio..."
        else:
            summary = snapshot.get("summary") or {}
            alerts = snapshot.get("alerts") or {}
            total_alerts = sum(int(value or 0) for value in (alerts.get("counts") or {}).values())
            self.status_text = f"Hoje: {_format_mzn(summary.get('revenue_today'))} | Alertas ativos: {total_alerts}"

    def _build_header_subtitle(self, snapshot):
        if self._snapshot_error:
            return "Nao foi possivel atualizar a visao geral agora."
        if self._snapshot_loading and not snapshot:
            return "A preparar visao geral, alertas e indicadores operacionais."

        summary = snapshot.get("summary") or {}
        alerts = snapshot.get("alerts") or {}
        counts = alerts.get("counts") or {}
        comparison = snapshot.get("comparison") or {}
        context = snapshot.get("context") or {}

        expired = int(counts.get("expired") or 0)
        critical = int(counts.get("critical_stock") or 0)
        expiring = int(counts.get("expiring_soon") or 0)
        direction = comparison.get("direction")
        delta_percent = comparison.get("delta_percent")
        peak_hour = context.get("peak_hour")
        top_product = context.get("top_product_today") or {}

        if expired > 0 or critical > 0:
            parts = []
            if expired > 0:
                parts.append(f"{expired} itens vencidos")
            if critical > 0:
                parts.append(f"{critical} produtos com stock critico")
            return ", ".join(parts) + " pedem acao imediata."
        if expiring > 0:
            return f"Ha {expiring} produtos proximos do vencimento a acompanhar."
        if direction == "above" and delta_percent is not None:
            return f"A receita de hoje esta {abs(delta_percent):.1f}% acima da media recente."
        if direction == "below" and delta_percent is not None:
            return f"A receita de hoje esta {abs(delta_percent):.1f}% abaixo da media recente."
        if top_product:
            suffix = f" Pico do dia: {peak_hour}." if peak_hour else ""
            return f"{top_product.get('name')} lidera o dia ate agora.{suffix}"
        if float(summary.get("revenue_today") or 0.0) > 0:
            return "Operacao estavel, com vendas em curso e sem desvios fortes."
        return "Ainda sem vendas hoje. Use a HOME para priorizar o arranque do dia."

    def _render_summary_cards(self, summary):
        grid = self.ids.get("summary_grid")
        if grid is None:
            return

        critical_stock = int(summary.get("critical_stock") or 0)
        theme_style = getattr(App.get_running_app(), "theme_style", "Light")

        specs = [
            ("Faturacao Hoje", _format_mzn(summary.get("revenue_today") or 0.0), "Receita atual do dia", "cash-multiple", "primary", self.open_reports),
            ("Vendas Hoje", _format_value(summary.get("sales_today_count") or 0), "Resumo do dia", "cash-register", "success", self.open_today_sales),
            ("Stock Critico", _format_value(critical_stock), "Reposicao prioritaria", "alert-outline", "danger" if critical_stock > 0 else "success", self.open_stock_module),
            ("Produtos", _format_value(summary.get("total_products") or 0), "Catalogo ativo", "package-variant-closed", "info", self.go_to_products),
        ]

        signature = (theme_style, tuple((title, value, subtitle, icon_name, tone) for title, value, subtitle, icon_name, tone, _callback in specs))
        if signature == self._summary_render_signature:
            return
        self._summary_render_signature = signature
        grid.clear_widgets()

        for title, value, subtitle, icon_name, tone, callback in specs:
            grid.add_widget(self._build_metric_card(title, value, subtitle, icon_name, tone, callback))

    def _build_metric_card(self, title, value, subtitle, icon_name, tone, callback=None):
        tokens = getattr(App.get_running_app(), "theme_tokens", {}) or {}
        accent = tokens.get(tone, tokens.get("primary", [0.10, 0.35, 0.65, 1]))
        if tone == "text_secondary":
            accent = tokens.get("text_secondary", [0.45, 0.48, 0.52, 1])

        card = Factory.HomeButtonCard(
            orientation="vertical",
            size_hint_y=None,
            height=dp(92),
            padding=[dp(12), dp(10), dp(12), dp(10)],
            spacing=dp(4),
            radius=[dp(12)],
            elevation=1,
            md_bg_color=tokens.get("card", [1, 1, 1, 1]),
        )
        if callback:
            card.bind(on_release=lambda *_: callback())

        top_row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(26), spacing=dp(8))
        icon_chip = MDCard(
            size_hint=(None, None),
            size=(dp(28), dp(28)),
            radius=[dp(10)],
            elevation=0,
            md_bg_color=[accent[0], accent[1], accent[2], 0.14],
        )
        icon_label = MDIcon(icon=icon_name, halign="center", valign="middle")
        icon_label.bind(size=lambda inst, value: setattr(inst, "text_size", value))
        _set_label_text_color(icon_label, accent)
        icon_chip.add_widget(icon_label)

        title_label = MDLabel(text=title, font_style="Caption", bold=True)
        _set_label_text_color(title_label, tokens.get("text_secondary", [0.42, 0.46, 0.50, 1]))
        top_row.add_widget(icon_chip)
        top_row.add_widget(title_label)

        value_label = MDLabel(text=value, bold=True, font_size=dp(18), size_hint_y=None, height=dp(24))
        _set_label_text_color(value_label, accent)

        subtitle_label = MDLabel(text=subtitle, font_style="Caption", size_hint_y=None, height=dp(16))
        _set_label_text_color(subtitle_label, tokens.get("text_secondary", [0.42, 0.46, 0.50, 1]))

        card.add_widget(top_row)
        card.add_widget(value_label)
        card.add_widget(subtitle_label)
        return card

    def _build_quick_actions(self):
        grid = self.ids.get("quick_actions_grid")
        if grid is None or len(grid.children) > 0:
            return

        actions = [
            ("Produtos", "Catalogo", "package-variant", "primary", self.go_to_products),
            ("Stock", "Movimentos", "warehouse", "warning", self.open_stock_module),
            ("Relatorios", "Analise", "chart-box-outline", "info", self.open_reports),
            ("Utilizadores", "Acessos", "account-key-outline", "primary", self.open_users_module),
        ]

        for title, subtitle, icon_name, tone, callback in actions:
            grid.add_widget(self._build_quick_action_card(title, subtitle, icon_name, tone, callback))

    def _build_quick_action_card(self, title, subtitle, icon_name, tone, callback):
        tokens = getattr(App.get_running_app(), "theme_tokens", {}) or {}
        accent = tokens.get(tone, tokens.get("primary", [0.10, 0.35, 0.65, 1]))
        if tone == "text_secondary":
            accent = tokens.get("text_secondary", [0.45, 0.48, 0.52, 1])

        card = Factory.HomeButtonCard(
            orientation="vertical",
            size_hint_y=None,
            height=dp(68),
            padding=[dp(12), dp(10), dp(12), dp(10)],
            spacing=dp(2),
            radius=[dp(12)],
            elevation=1,
            md_bg_color=tokens.get("card", [1, 1, 1, 1]),
        )
        card.bind(on_release=lambda *_: callback())

        header = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(24), spacing=dp(6))
        icon_chip = MDCard(
            size_hint=(None, None),
            size=(dp(24), dp(24)),
            radius=[dp(8)],
            elevation=0,
            md_bg_color=[accent[0], accent[1], accent[2], 0.14],
        )
        icon_label = MDIcon(icon=icon_name, halign="center", valign="middle")
        icon_label.bind(size=lambda inst, value: setattr(inst, "text_size", value))
        _set_label_text_color(icon_label, accent)
        icon_chip.add_widget(icon_label)

        title_label = MDLabel(text=title, font_style="Caption", bold=True)
        _set_label_text_color(title_label, tokens.get("text_primary", [0.2, 0.2, 0.2, 1]))
        header.add_widget(icon_chip)
        header.add_widget(title_label)

        subtitle_label = MDLabel(text=subtitle, font_style="Caption")
        subtitle_label.shorten = True
        subtitle_label.shorten_from = "right"
        _set_label_text_color(subtitle_label, tokens.get("text_secondary", [0.42, 0.46, 0.50, 1]))

        card.add_widget(header)
        card.add_widget(subtitle_label)
        return card

    def _render_alert_cards(self, alerts):
        grid = self.ids.get("alerts_grid")
        meta_label = self.ids.get("alerts_meta_label")
        if grid is None:
            return

        counts = alerts.get("counts") or {}
        cards = []
        theme_style = getattr(App.get_running_app(), "theme_style", "Light")

        expired_items = alerts.get("expired_items") or []
        expiring_items = alerts.get("expiring_items") or []
        low_stock_items = alerts.get("low_stock_items") or []
        out_of_stock_items = alerts.get("out_of_stock_items") or []
        pending_items = alerts.get("pending_items") or []
        fraud_items = alerts.get("fraud_items") or []
        negative_profit_items = alerts.get("negative_profit_items") or []

        if int(counts.get("expired") or 0) > 0:
            first = expired_items[0] if expired_items else {}
            cards.append(("Produtos vencidos", int(counts.get("expired") or 0), "danger", "calendar-remove-outline", f"{first.get('name', 'Itens expirados')} exigem retirada imediata.", self.show_expired_products_banner))
        if int(counts.get("critical_stock") or 0) > 0:
            first = low_stock_items[0] if low_stock_items else {}
            cards.append(("Stock critico", int(counts.get("critical_stock") or 0), "warning", "alert-decagram-outline", f"{first.get('name', 'Reposicao')} esta com cobertura curta de stock.", self.open_stock_module))
        if int(counts.get("out_of_stock") or 0) > 0:
            first = out_of_stock_items[0] if out_of_stock_items else {}
            cards.append(("Produtos esgotados", int(counts.get("out_of_stock") or 0), "danger", "close-octagon-outline", f"{first.get('name', 'Ha produtos')} ja estao sem disponibilidade.", self.go_to_products))
        if int(counts.get("expiring_soon") or 0) > 0:
            first = expiring_items[0] if expiring_items else {}
            day_text = first.get("days_left")
            suffix = f" em {day_text} dias" if day_text is not None else ""
            cards.append(("Validades proximas", int(counts.get("expiring_soon") or 0), "warning", "calendar-clock-outline", f"{first.get('name', 'Itens com validade')} vencem{suffix}.", self.go_to_products))
        if int(counts.get("pending_approvals") or 0) > 0:
            first = pending_items[0] if pending_items else {}
            cards.append(("Pendencias administrativas", int(counts.get("pending_approvals") or 0), "info", "clipboard-alert-outline", f"{first.get('product_name', 'Movimentos')} aguardam validacao.", self.open_stock_module))
        if int(counts.get("fraud_alerts") or 0) > 0:
            first = fraud_items[0] if fraud_items else {}
            cards.append(("Alertas operacionais", int(counts.get("fraud_alerts") or 0), "danger", "shield-alert-outline", first.get("title") or "Foram encontrados padroes a rever.", self.open_losses_module))
        if int(counts.get("negative_profit") or 0) > 0:
            first = negative_profit_items[0] if negative_profit_items else {}
            cards.append(("Margem negativa", int(counts.get("negative_profit") or 0), "warning", "cash-remove", f"{first.get('name', 'Alguns itens')} precisam de revisao de preco.", self.open_reports))

        if not cards:
            cards = [("Operacao estavel", 0, "success", "check-circle-outline", "Sem alertas criticos no momento. Monitorizacao sob controlo.", self.refresh_home)]

        if meta_label:
            meta_label.text = f"{len(cards[:2])} prioridades"

        signature = (theme_style, tuple((title, count, tone, icon_name, description) for title, count, tone, icon_name, description, _callback in cards[:2]))
        if signature == self._alerts_render_signature:
            return
        self._alerts_render_signature = signature
        grid.clear_widgets()

        for title, count, tone, icon_name, description, callback in cards[:2]:
            grid.add_widget(self._build_alert_card(title, count, tone, icon_name, description, callback))

    def _build_alert_card(self, title, count, tone, icon_name, description, callback):
        tokens = getattr(App.get_running_app(), "theme_tokens", {}) or {}
        accent = tokens.get(tone, tokens.get("primary", [0.10, 0.35, 0.65, 1]))

        card = Factory.HomeButtonCard(
            orientation="vertical",
            size_hint_y=None,
            height=dp(72),
            padding=[dp(12), dp(10), dp(12), dp(10)],
            spacing=dp(2),
            radius=[dp(12)],
            elevation=1,
            md_bg_color=tokens.get("card", [1, 1, 1, 1]),
        )
        card.bind(on_release=lambda *_: callback())

        header = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(22), spacing=dp(6))
        icon_chip = MDCard(size_hint=(None, None), size=(dp(22), dp(22)), radius=[dp(8)], elevation=0, md_bg_color=[accent[0], accent[1], accent[2], 0.14])
        icon_label = MDIcon(icon=icon_name, halign="center", valign="middle")
        icon_label.bind(size=lambda inst, value: setattr(inst, "text_size", value))
        _set_label_text_color(icon_label, accent)
        icon_chip.add_widget(icon_label)

        title_label = MDLabel(text=title, font_style="Caption", bold=True)
        _set_label_text_color(title_label, tokens.get("text_primary", [0.2, 0.2, 0.2, 1]))
        count_label = MDLabel(text=str(count), font_style="Caption", bold=True, halign="right", size_hint_x=None, width=dp(30))
        _set_label_text_color(count_label, accent)

        header.add_widget(icon_chip)
        header.add_widget(title_label)
        header.add_widget(count_label)

        description_label = MDLabel(text=description, font_style="Caption")
        description_label.shorten = True
        description_label.shorten_from = "right"
        _set_label_text_color(description_label, tokens.get("text_secondary", [0.42, 0.46, 0.50, 1]))

        card.add_widget(header)
        card.add_widget(description_label)
        return card

    def _render_insights(self, snapshot):
        grid = self.ids.get("insights_grid")
        meta_label = self.ids.get("insights_meta_label")
        if grid is None:
            return
        if meta_label:
            meta_label.text = "Sinais do dia"

        insights = self._build_insight_specs(snapshot)[:2]
        theme_style = getattr(App.get_running_app(), "theme_style", "Light")
        signature = (theme_style, tuple(insights))
        if signature == self._insights_render_signature:
            return
        self._insights_render_signature = signature
        grid.clear_widgets()

        for title, text, icon_name, tone in insights:
            grid.add_widget(self._build_insight_card(title, text, icon_name, tone))

    def _build_insight_specs(self, snapshot):
        summary = snapshot.get("summary") or {}
        alerts = snapshot.get("alerts") or {}
        comparison = snapshot.get("comparison") or {}
        context = snapshot.get("context") or {}
        counts = alerts.get("counts") or {}
        items = []

        top_product = context.get("top_product_today") or {}
        if top_product:
            items.append(("Produto em destaque", f"{top_product.get('name')} lidera hoje com {_format_mzn(top_product.get('revenue') or 0.0)}.", "star-circle-outline", "primary"))

        direction = comparison.get("direction")
        delta_percent = comparison.get("delta_percent")
        if direction == "above" and delta_percent is not None:
            items.append(("Ritmo de venda", f"A receita do dia esta {abs(delta_percent):.1f}% acima da media recente.", "trending-up", "success"))
        elif direction == "below" and delta_percent is not None:
            items.append(("Ritmo de venda", f"A receita do dia esta {abs(delta_percent):.1f}% abaixo da media recente.", "trending-down", "warning"))

        if int(counts.get("critical_stock") or 0) > 0:
            first = (alerts.get("low_stock_items") or [{}])[0]
            items.append(("Reposicao prioritaria", f"{counts.get('critical_stock')} itens criticos. Priorize {first.get('name', 'os produtos mais sensiveis')}.", "package-variant-plus", "warning"))

        expiry_total = int(counts.get("expired") or 0) + int(counts.get("expiring_soon") or 0)
        if expiry_total > 0:
            items.append(("Validade", f"{expiry_total} produtos exigem monitorizacao de validade neste momento.", "calendar-alert-outline", "danger" if int(counts.get("expired") or 0) > 0 else "warning"))

        if int(counts.get("pending_approvals") or 0) > 0:
            items.append(("Pendencias", f"{counts.get('pending_approvals')} movimento(s) aguardam validacao administrativa.", "clipboard-text-clock-outline", "info"))

        if int(counts.get("fraud_alerts") or 0) > 0:
            items.append(("Monitorizacao", f"{counts.get('fraud_alerts')} alerta(s) operacionais merecem revisao.", "shield-search-outline", "danger"))

        if not items:
            items.append(("Leitura do sistema", f"Operacao equilibrada. Receita atual do dia: {_format_mzn(summary.get('revenue_today') or 0.0)}.", "check-decagram-outline", "success"))
            items.append(("Painel preparado", "Clientes e expansoes comerciais podem ser integrados aqui no proximo ciclo.", "rocket-launch-outline", "info"))

        return items[:4]

    def _build_insight_card(self, title, text, icon_name, tone):
        tokens = getattr(App.get_running_app(), "theme_tokens", {}) or {}
        accent = tokens.get(tone, tokens.get("primary", [0.10, 0.35, 0.65, 1]))

        card = MDCard(
            orientation="vertical",
            size_hint_y=None,
            height=dp(68),
            padding=[dp(12), dp(10), dp(12), dp(10)],
            spacing=dp(2),
            radius=[dp(12)],
            elevation=1,
            md_bg_color=tokens.get("card_alt", [0.95, 0.96, 0.98, 1]),
        )

        header = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(22), spacing=dp(6))
        icon_chip = MDCard(size_hint=(None, None), size=(dp(22), dp(22)), radius=[dp(8)], elevation=0, md_bg_color=[accent[0], accent[1], accent[2], 0.14])
        icon_label = MDIcon(icon=icon_name, halign="center", valign="middle")
        icon_label.bind(size=lambda inst, value: setattr(inst, "text_size", value))
        _set_label_text_color(icon_label, accent)
        icon_chip.add_widget(icon_label)

        title_label = MDLabel(text=title, font_style="Caption", bold=True)
        _set_label_text_color(title_label, tokens.get("text_primary", [0.2, 0.2, 0.2, 1]))
        header.add_widget(icon_chip)
        header.add_widget(title_label)

        text_label = MDLabel(text=text, font_style="Caption")
        text_label.shorten = True
        text_label.shorten_from = "right"
        _set_label_text_color(text_label, tokens.get("text_secondary", [0.42, 0.46, 0.50, 1]))

        card.add_widget(header)
        card.add_widget(text_label)
        return card

    def _dismiss_today_sales_dialog(self):
        dialog = getattr(self, "_today_sales_dialog", None)
        if dialog is None:
            return
        self._today_sales_dialog = None
        try:
            dialog.dismiss()
        except Exception:
            pass

    def _parse_sale_datetime(self, raw_value):
        text = str(raw_value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text)
        except Exception:
            pass
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y %H:%M",
            "%Y-%m-%d",
            "%d/%m/%Y",
        ):
            try:
                return datetime.strptime(text, fmt)
            except Exception:
                continue
        return None

    def _build_today_sales_summary(self, rows):
        rows = list(rows or [])
        gross_total = 0.0
        refunded_total = 0.0
        total_qty = 0.0
        promo_sales = 0
        products = {}
        hours = {}
        recent_sales = []

        for row in rows:
            product_name = str(row[1] if len(row) > 1 and row[1] is not None else "Produto").strip() or "Produto"
            qty = float(row[2] or 0) if len(row) > 2 else 0.0
            unit_price = float(row[3] or 0) if len(row) > 3 else 0.0
            total = float(row[4] or 0) if len(row) > 4 else 0.0
            sale_raw = row[5] if len(row) > 5 else ""
            returned_qty = float(row[6] or 0) if len(row) > 6 else 0.0
            is_promotional = bool(row[10]) if len(row) > 10 else False
            sale_dt = self._parse_sale_datetime(sale_raw)
            refund_amount = returned_qty * unit_price
            net_total = max(0.0, total - refund_amount)
            net_qty = max(0.0, qty - returned_qty)

            gross_total += total
            refunded_total += refund_amount
            total_qty += net_qty
            if is_promotional:
                promo_sales += 1

            product_bucket = products.setdefault(product_name, {"count": 0, "net_total": 0.0})
            product_bucket["count"] += 1
            product_bucket["net_total"] += net_total

            if sale_dt is not None:
                hour_key = sale_dt.strftime("%H:00")
                hours[hour_key] = hours.get(hour_key, 0) + 1
                time_text = sale_dt.strftime("%H:%M")
            else:
                time_text = "--:--"

            recent_sales.append(
                {
                    "time": time_text,
                    "product": product_name,
                    "qty": net_qty,
                    "net_total": net_total,
                }
            )

        top_product = None
        if products:
            name, payload = max(
                products.items(),
                key=lambda item: (float(item[1].get("net_total") or 0.0), int(item[1].get("count") or 0)),
            )
            top_product = {
                "name": name,
                "count": int(payload.get("count") or 0),
                "net_total": float(payload.get("net_total") or 0.0),
            }

        peak_hour = None
        if hours:
            peak_hour = max(hours.items(), key=lambda item: (int(item[1]), item[0]))[0]

        return {
            "total_sales": len(rows),
            "gross_total": gross_total,
            "refunded_total": refunded_total,
            "net_total": max(0.0, gross_total - refunded_total),
            "total_qty": total_qty,
            "promo_sales": promo_sales,
            "top_product": top_product,
            "peak_hour": peak_hour,
            "recent_sales": recent_sales[:6],
            "remaining_sales": max(0, len(recent_sales) - 6),
        }

    def _build_today_sales_dialog_text(self, day_label, summary):
        total_sales = int(summary.get("total_sales") or 0)
        if total_sales <= 0:
            return "\n".join(
                [
                    f"Data: {day_label}",
                    "",
                    "Ainda nao ha vendas registadas hoje.",
                    "Quando a primeira venda entrar, este resumo aparece aqui.",
                ]
            )

        lines = [
            f"Data: {day_label}",
            f"Total de vendas: {total_sales}",
            f"Receita liquida: {_format_mzn(summary.get('net_total') or 0.0)}",
            f"Itens vendidos: {_format_compact_qty(summary.get('total_qty') or 0.0)}",
        ]

        refunded_total = float(summary.get("refunded_total") or 0.0)
        if refunded_total > 0:
            lines.append(f"Estornos no dia: {_format_mzn(refunded_total)}")

        promo_sales = int(summary.get("promo_sales") or 0)
        if promo_sales > 0:
            lines.append(f"Vendas promocionais: {promo_sales}")

        top_product = summary.get("top_product") or {}
        if top_product:
            lines.append(
                f"Destaque: {top_product.get('name')} com {_format_mzn(top_product.get('net_total') or 0.0)}"
            )

        peak_hour = summary.get("peak_hour")
        if peak_hour:
            lines.append(f"Pico operacional: {peak_hour}")

        lines.append("")
        lines.append("Ultimas vendas:")

        for sale in summary.get("recent_sales") or []:
            lines.append(
                f"{sale.get('time')} | {sale.get('product')} | Qtd {_format_compact_qty(sale.get('qty') or 0.0)} | {_format_mzn(sale.get('net_total') or 0.0)}"
            )

        remaining_sales = int(summary.get("remaining_sales") or 0)
        if remaining_sales > 0:
            lines.append(f"+ {remaining_sales} venda(s) adicional(is) no historico de hoje.")

        return "\n".join(lines)

    def _open_today_sales_history(self, dialog=None):
        if dialog is not None:
            try:
                dialog.dismiss()
            except Exception:
                pass
        if not self.manager:
            return
        screen = self._set_back_target("sales_history", "admin_home")
        if not screen:
            return
        if hasattr(screen, "queue_enter_filter"):
            screen.queue_enter_filter("today")
        self.manager.current = "sales_history"
        if screen and not hasattr(screen, "queue_enter_filter") and hasattr(screen, "filter_today"):
            Clock.schedule_once(lambda dt: screen.filter_today(), 0.06)
        elif screen and hasattr(screen, "request_enter_refresh"):
            Clock.schedule_once(lambda dt: screen.request_enter_refresh(force=False, delay=0.04), 0.04)

    def _finish_today_sales_loading(self, day_label, rows, error=None):
        self._today_sales_loading = False
        self._dismiss_today_sales_dialog()

        if error:
            dialog = MDDialog(
                title="Vendas de Hoje",
                text=f"Falha ao carregar o resumo do dia.\n{error}",
                buttons=[
                    MDFlatButton(text="FECHAR", on_release=lambda _x: dialog.dismiss()),
                ],
            )
            self._today_sales_dialog = dialog
            dialog.bind(on_dismiss=lambda *_: setattr(self, "_today_sales_dialog", None))
            dialog.open()
            return

        summary = self._build_today_sales_summary(rows)
        dialog = MDDialog(
            title="Resumo das Vendas de Hoje",
            text=self._build_today_sales_dialog_text(day_label, summary),
            buttons=[
                MDFlatButton(text="FECHAR", on_release=lambda _x: dialog.dismiss()),
                MDRaisedButton(
                    text="VER HISTORICO",
                    on_release=lambda _x: self._open_today_sales_history(dialog),
                ),
            ],
        )
        self._today_sales_dialog = dialog
        dialog.bind(on_dismiss=lambda *_: setattr(self, "_today_sales_dialog", None))
        dialog.open()

    def _set_back_target(self, screen_name, target):
        if not self.manager:
            return None
        app = App.get_running_app()
        ensure_screen = getattr(app, "ensure_screen", None)
        if screen_name not in self.manager.screen_names and callable(ensure_screen):
            ensure_screen(screen_name)
        if screen_name not in self.manager.screen_names:
            return None
        screen = self.manager.get_screen(screen_name)
        setattr(screen, "back_target", target)
        return screen

    def _get_home_alerts(self):
        return (self._snapshot or {}).get("alerts") or {}

    def _format_banner_quantity(self, stock, unit="un"):
        try:
            amount = float(stock or 0)
        except Exception:
            amount = 0.0
        unit_text = str(unit or "un").strip() or "un"
        if unit_text.lower() == "kg":
            return f"{amount:.2f} kg"
        if abs(amount - round(amount)) < 0.05:
            return f"{int(round(amount))} {unit_text}"
        return f"{amount:.1f} {unit_text}"

    def _build_expired_products_banner(self):
        items = list(self._get_home_alerts().get("expired_items") or [])
        if not items:
            banner = build_positive_banner("expiry")
            banner["details_sections"] = [("Estado atual", ["Nenhum produto vencido na leitura atual da HOME."])]
            return banner

        messages = []
        detail_lines = []
        for item in items:
            name = str(item.get("name") or "Produto")
            expiry_date = str(item.get("date") or "data nao informada")
            qty = self._format_banner_quantity(item.get("stock"), item.get("unit") or "un")
            messages.append(f"{name} venceu em {expiry_date}.")
            detail_lines.append(f"{name}: {qty} ainda em stock, validade {expiry_date}.")

        return {
            "kind": "expiry",
            "expiry_level": "vencido",
            "variant": "danger",
            "icon": "alert-octagon",
            "bg_color": (0.93, 0.34, 0.34, 1),
            "title": "Produtos vencidos",
            "messages": messages[:5],
            "all_messages": messages,
            "count": len(items),
            "urgency": 0,
            "details_sections": [
                ("Produtos vencidos", detail_lines),
                ("Acao imediata", [
                    "Retire os itens vencidos da area de venda.",
                    "Registe a perda ou trate a devolucao assim que possivel.",
                ]),
            ],
        }

    def _show_single_home_banner(self, banner_data):
        if not banner_data or not hasattr(self, "ids") or "ai_banner_container" not in self.ids:
            return

        target = self.ids.ai_banner_container
        ensure_center = getattr(self._intelligence, "_ensure_banner_center", None)
        if callable(ensure_center):
            try:
                target = ensure_center()
            except Exception:
                target = self.ids.ai_banner_container

        show_history = getattr(target, "_show_history_banners", None)
        if callable(show_history):
            target.current_insights = {}
            show_history([banner_data])
            return

        render_auto_banners(
            target,
            [banner_data],
            insights=None,
            auto_dismiss_seconds=None,
            show_timer=False,
        )

    def show_expired_products_banner(self, *args):
        self._show_single_home_banner(self._build_expired_products_banner())

    def go_to_products(self, *args, open_form=False):
        screen = self._set_back_target("admin", "admin_home")
        if not screen or not self.manager:
            return
        self.manager.current = "admin"
        if open_form and hasattr(screen, "add_product"):
            Clock.schedule_once(lambda dt: screen.add_product(), 0.12)

    def add_product(self, *args):
        screen = self._set_back_target("admin", "admin_home")
        if not screen or not hasattr(screen, "add_product"):
            return
        Clock.schedule_once(lambda dt: screen.add_product(), 0)

    def open_reports(self, *args):
        if not self.manager:
            return
        screen = self._set_back_target("reports", "admin_home")
        if not screen:
            return
        self.manager.current = "reports"
        if screen and hasattr(screen, "prepare_open_from_admin"):
            Clock.schedule_once(lambda dt: screen.prepare_open_from_admin(), 0.04)

    def show_all_pdfs(self, *args):
        screen = self._set_back_target("reports", "admin_home")
        if not screen or not hasattr(screen, "show_pdf_viewer"):
            return
        if hasattr(screen, "prepare_open_from_admin"):
            Clock.schedule_once(lambda dt: screen.prepare_open_from_admin(), 0)
        Clock.schedule_once(lambda dt: screen.show_pdf_viewer(), 0.05)

    def open_sales_history(self, *args):
        if not self.manager:
            return
        screen = self._set_back_target("sales_history", "admin_home")
        if not screen:
            return
        self.manager.current = "sales_history"
        if screen and hasattr(screen, "request_enter_refresh"):
            Clock.schedule_once(lambda dt: screen.request_enter_refresh(force=False, delay=0.04), 0.04)

    def open_today_sales(self, *args):
        if self._today_sales_loading:
            return
        self._dismiss_today_sales_dialog()
        self._today_sales_loading = True
        today_label = datetime.now().strftime("%d/%m/%Y")

        loading_dialog = MDDialog(
            title="Vendas de Hoje",
            text=f"A carregar resumo de {today_label}...",
            buttons=[
                MDFlatButton(text="FECHAR", on_release=lambda _x: loading_dialog.dismiss()),
            ],
        )
        self._today_sales_dialog = loading_dialog
        loading_dialog.bind(on_dismiss=lambda *_: setattr(self, "_today_sales_dialog", None))
        loading_dialog.open()

        def worker():
            rows = []
            error = None
            try:
                rows = list(self.db.get_sales_by_date(today_label) or [])
            except Exception as exc:
                error = str(exc)
            Clock.schedule_once(
                lambda dt, day=today_label, data=rows, err=error: self._finish_today_sales_loading(day, data, err),
                0,
            )

        Thread(target=worker, daemon=True).start()

    def open_stock_module(self, *args):
        if not self.manager:
            return
        screen = self._set_back_target("restock", "admin_home")
        if not screen:
            return
        self.manager.current = "restock"
        if screen and hasattr(screen, "prepare_open_from_admin"):
            Clock.schedule_once(lambda dt: screen.prepare_open_from_admin("IN"), 0.04)

    def open_losses_module(self, *args):
        if not self.manager:
            return
        screen = self._set_back_target("losses", "admin_home")
        if not screen:
            return
        self.manager.current = "losses"
        if screen and hasattr(screen, "prepare_open_from_admin"):
            Clock.schedule_once(lambda dt: screen.prepare_open_from_admin(), 0.04)

    def open_users_module(self, *args):
        if not self.manager:
            return
        screen = self._set_back_target("settings", "admin_home")
        if not screen:
            return
        self.manager.current = "settings"
        if screen and hasattr(screen, "add_user"):
            Clock.schedule_once(lambda dt: screen.add_user(), 0.08)

    def open_ai_menu(self, caller=None):
        if caller is None and hasattr(self, "ids") and "ai_button" in self.ids:
            caller = self.ids.ai_button
        self._intelligence.open_history(caller=caller)

    def go_to_settings(self, *args):
        if not self.manager:
            return
        screen = self._set_back_target("settings", "admin_home")
        if not screen:
            return
        self.manager.current = "settings"

    def logout(self, *args):
        app = App.get_running_app()
        if app:
            username = getattr(app, "current_user", None)
            app.current_user = None
            app.current_role = None
            app._ai_banners_shown = False
            app._ai_notifications_seen_key = None
            app._ai_banners_last_key = None
        if self.manager:
            self.manager.current = "login"
