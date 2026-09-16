from datetime import datetime, timedelta
import os
import sys
from contextlib import nullcontext
from threading import Thread
from time import perf_counter

from kivy.app import App
from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.factory import Factory
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.modalview import ModalView
from kivy.properties import BooleanProperty, StringProperty
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.card import MDCard
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDIcon, MDLabel
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from database.provider import get_db
from ui.components.admin_home_dashboard import SalesTrendChart
from ui.components.hover_widgets import HoverCard, HoverRaisedButton
from ui.components.tooltip_widgets import TooltipFloatingActionButton, set_attention_shake
from utils.core.formatters import format_compact_number, format_display_value, format_money


Builder.load_file(os.path.join(CURRENT_DIR, "admin_home_screen.kv"))

def _set_label_text_color(label, color):
    label.theme_text_color = "Custom"
    label.text_color = color


def _format_mzn(value):
    return format_money(value, currency="MZN")


def _format_value(value):
    return format_display_value(value)


def _format_compact_qty(value):
    return format_compact_number(value, empty="0")


class AdminLogsDialog:
    """Consulta de logs enxuta para o painel administrativo."""

    DEFAULT_LIMIT = 60
    _ACTION_LABELS = {
        "ACCESS_ATTEMPT": "Tentativa de acesso",
        "ACCESS_DENIED": "Acesso negado",
        "ADD_PRODUCT": "Produto adicionado",
        "APPROVE_LOSS": "Perda aprovada",
        "APPROVE_ALL_LOSSES": "Todas as perdas aprovadas",
        "CANCEL_SALE": "Venda cancelada",
        "CANCEL_INVENTORY": "Inventário cancelado",
        "CLOSE_CASH": "Caixa fechado",
        "COMPLETE_INVENTORY": "Inventário concluído",
        "CREATE_USER": "Utilizador criado",
        "DELETE_PRODUCT": "Produto removido",
        "DELETE_USER": "Utilizador removido",
        "EXPORT_SALES": "Relatório de vendas exportado",
        "EXPORT_SALES_PDF": "Relatório de vendas em PDF exportado",
        "LOGIN": "Início de sessão",
        "LOGOUT": "Sessão terminada",
        "OPEN_CASH": "Caixa aberto",
        "PRINT_RECEIPT": "Recibo impresso",
        "REGISTER_LOSS": "Perda registada",
        "REJECT_LOSS": "Perda rejeitada",
        "REQUEST_LOSS_APPROVAL": "Pedido de aprovação de perda",
        "RESET_PASSWORD_EMAIL": "Palavra-passe redefinida por e-mail",
        "RESET_PASSWORD_QA": "Palavra-passe redefinida",
        "REFUND_SALE": "Venda estornada",
        "REMOVE_SALE_ITEM": "Item removido da venda",
        "SALE": "Venda registada",
        "SAVE_RECEIPT": "Recibo guardado",
        "START_INVENTORY": "Inventário iniciado",
        "UPDATE_PRODUCT": "Produto atualizado",
        "UPDATE_ADMIN": "Dados do administrador atualizados",
        "UPDATE_SECURITY_QUESTIONS": "Perguntas de recuperação atualizadas",
        "VERIFY_EMAIL": "E-mail confirmado",
    }
    _ROLE_LABELS = {"admin": "Admin", "manager": "Gerente"}
    _DETAIL_LABELS = {
        "ADJUSTMENT": "Ajuste",
        "DAMAGE": "Danificado",
        "EXPIRED": "Expirado",
        "IN": "Entrada",
        "OUT": "Saída",
        "RESTOCK": "Reposição",
        "THEFT": "Roubo",
    }

    def __init__(self):
        self.dialog = None
        self.date_field = None
        self.user_field = None
        self.refresh_button = None
        self.today_button = None
        self.clear_button = None
        self.status_label = None
        self.logs_list = None
        self.role_filter = ""
        self.role_buttons = {}
        self._request_token = 0
        self._render_token = 0
        self._render_event = None
        self._loading = False

    @staticmethod
    def _tokens():
        app = App.get_running_app()
        return getattr(app, "theme_tokens", {}) if app else {}

    @staticmethod
    def _format_timestamp(value):
        try:
            return datetime.strptime(str(value or ""), "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M")
        except (TypeError, ValueError):
            return str(value or "")

    def _set_status(self, text, tone="text_secondary"):
        if not self.status_label:
            return
        tokens = self._tokens()
        self.status_label.text = text
        self.status_label.theme_text_color = "Custom"
        self.status_label.text_color = tokens.get(tone, tokens.get("text_secondary", [0.35, 0.40, 0.50, 1]))

    def _set_loading(self, active):
        self._loading = bool(active)
        for widget in (self.date_field, self.user_field, self.refresh_button, self.today_button, self.clear_button, *self.role_buttons.values()):
            if widget is not None:
                widget.disabled = self._loading
        if self.refresh_button:
            self.refresh_button.text = "A CARREGAR..." if self._loading else "ATUALIZAR"

    def _parse_selected_date(self):
        raw_value = str(getattr(self.date_field, "text", "") or "").strip()
        if not raw_value:
            return "", None
        for date_format in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw_value, date_format).strftime("%Y-%m-%d"), None
            except ValueError:
                continue
        return None, "Informe a data como DD/MM/AAAA."

    @classmethod
    def _role_label(cls, role):
        normalized = str(role or "").strip().lower()
        return cls._ROLE_LABELS.get(normalized, normalized.capitalize() or "Sem perfil")

    @classmethod
    def _translate_details(cls, details):
        parts = [part.strip() for part in str(details or "").split("|")]
        translated = [cls._DETAIL_LABELS.get(part.upper(), part) for part in parts]
        return " | ".join(part for part in translated if part)

    def _set_role_filter(self, role):
        self.role_filter = str(role or "").strip().lower()
        tokens = self._tokens()
        for value, button in self.role_buttons.items():
            selected = value == self.role_filter
            button.theme_text_color = "Custom"
            button.text_color = tokens.get(
                "primary" if selected else "text_secondary",
                [0.10, 0.35, 0.65, 1] if selected else [0.35, 0.40, 0.50, 1],
            )
        if self.dialog is not None and not self._loading:
            self.load_logs()

    def _cancel_pending_work(self):
        self._request_token += 1
        self._render_token += 1
        event = self._render_event
        self._render_event = None
        if event is not None:
            try:
                event.cancel()
            except Exception:
                pass
        self._loading = False

    def _on_dismiss(self, *_args):
        self._cancel_pending_work()
        self.dialog = None

    def show(self):
        if self.dialog is not None:
            self.dialog.open()
            return

        tokens = self._tokens()
        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(8),
            padding=[dp(8), dp(6), dp(8), dp(6)],
            size_hint_y=None,
            height=dp(472),
        )

        filter_row = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(8),
            size_hint_y=None,
            height=dp(46),
        )
        self.date_field = MDTextField(
            hint_text="Data (DD/MM/AAAA)",
            mode="rectangle",
            size_hint_x=0.42,
        )
        self.date_field.bind(on_text_validate=lambda *_args: self.load_logs())
        self.user_field = MDTextField(
            hint_text="Utilizador",
            mode="rectangle",
            size_hint_x=0.28,
        )
        self.user_field.bind(on_text_validate=lambda *_args: self.load_logs())
        self.today_button = MDFlatButton(text="HOJE", on_release=lambda *_args: self.use_today())
        self.clear_button = MDFlatButton(text="LIMPAR", on_release=lambda *_args: self.clear_date())
        self.refresh_button = MDRaisedButton(
            text="ATUALIZAR",
            md_bg_color=tokens.get("primary", [0.10, 0.35, 0.65, 1]),
            theme_text_color="Custom",
            text_color=tokens.get("on_primary", [1, 1, 1, 1]),
            on_release=lambda *_args: self.load_logs(),
        )
        filter_row.add_widget(self.date_field)
        filter_row.add_widget(self.user_field)
        filter_row.add_widget(self.today_button)
        filter_row.add_widget(self.clear_button)
        filter_row.add_widget(self.refresh_button)
        content.add_widget(filter_row)

        role_row = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(6),
            size_hint_y=None,
            height=dp(30),
        )
        role_row.add_widget(MDLabel(
            text="Perfil:",
            font_style="Caption",
            size_hint_x=None,
            width=dp(46),
            theme_text_color="Custom",
            text_color=tokens.get("text_secondary", [0.35, 0.40, 0.50, 1]),
        ))
        for label, role in (("TODOS", ""), ("ADMIN", "admin"), ("GERENTE", "manager")):
            button = MDFlatButton(
                text=label,
                on_release=lambda _instance, value=role: self._set_role_filter(value),
            )
            self.role_buttons[role] = button
            role_row.add_widget(button)
        role_row.add_widget(MDLabel(text=""))
        content.add_widget(role_row)
        self._set_role_filter("")

        self.status_label = MDLabel(
            text="A preparar logs recentes...",
            font_style="Caption",
            size_hint_y=None,
            height=dp(20),
            theme_text_color="Custom",
            text_color=tokens.get("text_secondary", [0.35, 0.40, 0.50, 1]),
        )
        content.add_widget(self.status_label)

        self.logs_list = MDBoxLayout(
            orientation="vertical",
        )
        content.add_widget(self.logs_list)

        self.dialog = MDDialog(
            title="Logs recentes",
            type="custom",
            content_cls=content,
            size_hint=(0.78, 0.78),
            buttons=[MDFlatButton(text="FECHAR", on_release=lambda *_args: self.dialog.dismiss())],
        )
        self.dialog.bind(on_dismiss=self._on_dismiss)
        self.dialog.open()
        Clock.schedule_once(lambda _dt: self.load_logs(), 0)

    def use_today(self):
        if self.date_field is not None:
            self.date_field.text = datetime.now().strftime("%d/%m/%Y")
        self.load_logs()

    def clear_date(self):
        if self.date_field is not None:
            self.date_field.text = ""
        if self.user_field is not None:
            self.user_field.text = ""
        self._set_role_filter("")

    def _fetch_logs(self, date_filter, user_filter, role_filter):
        excluded_actions = ("LOGIN", "LOGOUT")
        with get_db() as db:
            try:
                return db.get_user_logs(
                    user_filter=user_filter,
                    role_filter=role_filter,
                    limit=self.DEFAULT_LIMIT,
                    date_filter=date_filter or None,
                    exclude_actions=excluded_actions,
                    details_limit=180,
                ) or []
            except TypeError:
                rows = db.get_user_logs(user_filter, "", role_filter, limit=self.DEFAULT_LIMIT) or []
                rows = [
                    row for row in rows
                    if str(row[3] or "").upper() not in excluded_actions
                    and (not date_filter or str(row[5] or "").startswith(date_filter))
                ]
                return rows

    def load_logs(self):
        if self.dialog is None or self._loading:
            return
        date_filter, validation_error = self._parse_selected_date()
        if validation_error:
            self._set_status(validation_error, "danger")
            return
        user_filter = str(getattr(self.user_field, "text", "") or "").strip()
        role_filter = self.role_filter

        self._request_token += 1
        request_token = self._request_token
        self._render_token += 1
        self.logs_list.clear_widgets()
        self.logs_list.add_widget(MDLabel(text="A carregar registos...", size_hint_y=None, height=dp(32), halign="center"))
        self._set_status("A consultar os logs sem bloquear o painel...", "info")
        self._set_loading(True)

        def worker():
            logs = None
            error = None
            try:
                logs = self._fetch_logs(date_filter, user_filter, role_filter)
            except Exception as exc:
                error = str(exc)
            Clock.schedule_once(
                lambda _dt, rows=logs, detail=error, token=request_token: self._apply_logs(
                    rows,
                    detail,
                    token,
                    date_filter,
                    user_filter,
                    role_filter,
                ),
                0,
            )

        Thread(target=worker, daemon=True).start()

    def _apply_logs(self, logs, error, request_token, date_filter, user_filter, role_filter):
        if request_token != self._request_token or self.dialog is None:
            return
        self.logs_list.clear_widgets()
        self._set_loading(False)
        if error:
            self._set_status(f"Não foi possível carregar os logs: {error}", "danger")
            return
        if not logs:
            details = []
            if date_filter:
                details.append("a data selecionada")
            if user_filter:
                details.append(f"o utilizador {user_filter}")
            if role_filter:
                details.append(f"o perfil {self._role_label(role_filter)}")
            detail = f" para {' e '.join(details)}" if details else ""
            self.logs_list.add_widget(MDLabel(text=f"Nenhum registo encontrado{detail}.", size_hint_y=None, height=dp(38), halign="center"))
            self._set_status("Sem resultados.", "text_secondary")
            return

        filters = []
        if date_filter:
            filters.append(datetime.strptime(date_filter, "%Y-%m-%d").strftime("%d/%m/%Y"))
        if user_filter:
            filters.append(user_filter)
        if role_filter:
            filters.append(self._role_label(role_filter))
        suffix = f" · filtros: {' | '.join(filters)}" if filters else " recentes"
        self._set_status(f"{len(logs)} registo(s){suffix}.", "success")
        self._render_logs_in_batches(list(logs), request_token)

    def _render_logs_in_batches(self, logs, request_token):
        if request_token != self._request_token or self.dialog is None:
            return
        tokens = self._tokens()
        view = RecycleView(do_scroll_x=False, bar_width=dp(4))
        layout = RecycleBoxLayout(
            default_size=(None, dp(62)), default_size_hint=(1, None),
            size_hint_y=None, orientation="vertical", spacing=dp(6),
            padding=[0, 0, dp(4), dp(4)],
        )
        layout.bind(minimum_height=layout.setter("height"))
        view.add_widget(layout)
        view.viewclass = RecycledLogCard
        view.data = [{"row": row, "tokens": tokens, "controller": self} for row in logs]
        self.logs_list.add_widget(view)

    def _build_log_card(self, row, tokens):
        _log_id, username, role, action, details, timestamp = row
        card = MDCard(
            orientation="vertical",
            size_hint_y=None,
            height=dp(62),
            padding=[dp(10), dp(7), dp(10), dp(7)],
            spacing=dp(2),
            radius=[dp(10)],
            elevation=0,
            md_bg_color=tokens.get("card_alt", [0.95, 0.96, 0.98, 1]),
        )
        action_text = self._ACTION_LABELS.get(
            str(action or "").upper(),
            str(action or "Ação do sistema").replace("_", " ").capitalize(),
        )
        header = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(20))
        header.add_widget(MDLabel(
            text=f"{username or 'Sistema'} ({self._role_label(role)}) · {action_text}",
            bold=True,
            font_style="Caption",
            theme_text_color="Custom",
            text_color=tokens.get("text_primary", [0.15, 0.20, 0.30, 1]),
            shorten=True,
            shorten_from="right",
        ))
        header.add_widget(MDLabel(
            text=self._format_timestamp(timestamp),
            font_style="Caption",
            halign="right",
            size_hint_x=0.40,
            theme_text_color="Custom",
            text_color=tokens.get("text_secondary", [0.35, 0.40, 0.50, 1]),
        ))
        card.add_widget(header)
        compact_details = " ".join(self._translate_details(details or role or "").split())[:180]
        card.add_widget(MDLabel(
            text=compact_details or "Sem detalhes adicionais.",
            font_style="Caption",
            theme_text_color="Custom",
            text_color=tokens.get("text_secondary", [0.35, 0.40, 0.50, 1]),
            shorten=True,
            shorten_from="right",
        ))
        return card


class RecycledLogCard(RecycleDataViewBehavior, MDBoxLayout):
    """Reutiliza o cartao e os tres labels ao percorrer o historico."""

    def refresh_view_attrs(self, rv, index, data):
        # Os dados sao aplicados explicitamente: nao sao propriedades Kivy.
        row, tokens, controller = data["row"], data["tokens"], data["controller"]
        if not self.children:
            self.add_widget(controller._build_log_card(row, tokens))
        else:
            card = self.children[0]
            header = card.children[1]
            username, role, action, details, timestamp = row[1:]
            action_text = controller._ACTION_LABELS.get(
                str(action or "").upper(),
                str(action or "Ação do sistema").replace("_", " ").capitalize(),
            )
            header.children[1].text = f"{username or 'Sistema'} ({controller._role_label(role)}) · {action_text}"
            header.children[0].text = controller._format_timestamp(timestamp)
            card.children[0].text = " ".join(controller._translate_details(details or role or "").split())[:180] or "Sem detalhes adicionais."
            card.md_bg_color = tokens.get("card_alt", [0.95, 0.96, 0.98, 1])
            header.children[1].text_color = tokens.get("text_primary", [0.15, 0.20, 0.30, 1])
            for label in (header.children[0], card.children[0]):
                label.text_color = tokens.get("text_secondary", [0.35, 0.40, 0.50, 1])


class AdminHomeScreen(MDScreen):
    HOME_CACHE_SECONDS = 20
    home_title = StringProperty("Painel do Administrador")
    home_subtitle = StringProperty("Resumo da loja")
    datetime_text = StringProperty("")
    status_text = StringProperty("A carregar dados...")
    chart_metric_text = StringProperty("Faturacao")
    chart_period_text = StringProperty("30 dias")
    quick_actions_open = BooleanProperty(False)

    def __init__(self, **kwargs):
        db = kwargs.pop("db", None)
        self.db = db or get_db()
        self.notification_count = 0
        self.recommendation_count = 0
        self._snapshot = None
        self._snapshot_error = None
        self._snapshot_loading = False
        self._snapshot_loaded_at = 0.0
        self._snapshot_period_days = None
        self._snapshot_token = 0
        self._clock_ev = None
        self._sales_chart = None
        self._chart_render_ev = None
        self._chart_render_signature = None
        self._chart_metric = "revenue"
        self._chart_period_days = 30
        self._chart_metric_menu = None
        self._chart_period_menu = None
        self._summary_render_signature = None
        self._alerts_render_signature = None
        self._insights_render_signature = None
        self._today_sales_dialog = None
        self._today_sales_loading = False
        self._logs_dialog = None
        self._home_action_dialog = None
        self._home_action_token = 0
        self._quick_restock_dialog = None
        self._quick_restock_product = None
        self._quick_restock_fields = {}
        self._quick_restock_submit_btn = None
        self._quick_restock_busy = False
        self._quick_action_last_key = None
        self._quick_action_last_at = 0.0
        self._settings_warmup_requested = False
        self._keyboard_shortcuts_bound = False
        self._last_shortcut_signature = None
        self._last_shortcut_at = 0.0
        self._intelligence = None
        self._layout_trigger = Clock.create_trigger(self._update_responsive_layout, 0)
        super().__init__(**kwargs)

    def _get_intelligence(self):
        if self._intelligence is None:
            from AI.controller import ProactiveIntelligenceController
            self._intelligence = ProactiveIntelligenceController(
                screen=self,
                db=self.db,
                history_title="Historico de avisos",
                banner_columns=1,
                auto_batch_size=2,
                auto_stagger_seconds=2.0,
                auto_present_enabled=True,
            )
        return self._intelligence

    def on_kv_post(self, base_widget):
        self._build_quick_actions()
        self._update_datetime_text()
        self._update_responsive_layout()
        self._init_badge(0)
        self._render_dashboard()

    def on_enter(self):
        self._bind_keyboard_shortcuts()
        self._start_clock()
        self._start_ai_polling()
        # O painel abre de imediato; a consulta já é feita numa thread e não
        # precisa de um atraso artificial nem de uma tela de bloqueio.
        self._ensure_snapshot_loaded(force=False)

    def on_leave(self):
        self._unbind_keyboard_shortcuts()
        self._dismiss_chart_menus()
        if self._clock_ev:
            self._clock_ev.cancel()
            self._clock_ev = None
        self._stop_ai_polling()
        self._snapshot_token += 1
        self._snapshot_loading = False
        if self._chart_render_ev is not None:
            self._chart_render_ev.cancel()
            self._chart_render_ev = None

    def on_size(self, *args):
        self._layout_trigger()

    def _chart_metric_options(self):
        return [
            ("revenue", "Faturacao"),
            ("sales_count", "Qtd. vendas"),
            ("stock_flow", "Fluxo stock"),
            ("top_products", "Produtos mais vendidos"),
        ]

    def _chart_period_options(self):
        return [
            (7, "7 dias"),
            (30, "30 dias"),
            (90, "90 dias"),
            (365, "1 ano"),
            (3650, "Geral"),
        ]

    def show_chart_metric_menu(self, caller):
        if self._chart_metric_menu:
            self._chart_metric_menu.dismiss()
        items = [
            {
                "text": label,
                "on_release": lambda key=key, text=label: self._set_chart_metric(key, text),
            }
            for key, label in self._chart_metric_options()
        ]
        self._chart_metric_menu = MDDropdownMenu(caller=caller, items=items, width_mult=3)
        self._chart_metric_menu.open()

    def show_chart_period_menu(self, caller):
        if self._chart_period_menu:
            self._chart_period_menu.dismiss()
        items = [
            {
                "text": label,
                "on_release": lambda days=days, text=label: self._set_chart_period(days, text),
            }
            for days, label in self._chart_period_options()
        ]
        self._chart_period_menu = MDDropdownMenu(caller=caller, items=items, width_mult=3)
        self._chart_period_menu.open()

    def _set_chart_metric(self, metric, label):
        if self._chart_metric_menu:
            self._chart_metric_menu.dismiss()
            self._chart_metric_menu = None
        self._chart_metric = metric
        self.chart_metric_text = label
        self._render_dashboard()

    def _set_chart_period(self, days, label):
        if self._chart_period_menu:
            self._chart_period_menu.dismiss()
            self._chart_period_menu = None
        self._chart_period_days = int(days or 30)
        self.chart_period_text = label
        if self._snapshot_loading:
            self._snapshot_token += 1
            self._snapshot_loading = False
        self._ensure_snapshot_loaded(force=True)

    def _dismiss_chart_menus(self):
        closed = False
        for attr_name in ("_chart_metric_menu", "_chart_period_menu"):
            menu = getattr(self, attr_name, None)
            if menu is None:
                continue
            try:
                menu.dismiss()
            except Exception:
                pass
            setattr(self, attr_name, None)
            closed = True
        return closed

    def _bind_keyboard_shortcuts(self):
        if self._keyboard_shortcuts_bound:
            return
        Window.bind(on_keyboard=self._handle_window_keyboard)
        Window.bind(on_key_down=self._handle_window_key_down)
        self._keyboard_shortcuts_bound = True

    def _unbind_keyboard_shortcuts(self):
        if not self._keyboard_shortcuts_bound:
            return
        Window.unbind(on_keyboard=self._handle_window_keyboard)
        Window.unbind(on_key_down=self._handle_window_key_down)
        self._keyboard_shortcuts_bound = False

    def _has_open_modal(self):
        return any(isinstance(child, ModalView) for child in Window.children)

    @staticmethod
    def _normalize_key_name(key, codepoint=""):
        if isinstance(key, (tuple, list)):
            numeric_key = key[0] if len(key) > 0 else None
            string_key = str(key[1] or "").strip().lower() if len(key) > 1 else ""
            if string_key:
                return string_key
            key = numeric_key

        if isinstance(key, str):
            key_name = key.strip().lower()
            if key_name:
                return key_name

        key_name = str(codepoint or "").strip().lower()
        if key_name:
            return key_name

        special_keys = {
            13: "enter",
            27: "escape",
            271: "enter",
        }
        if key in special_keys:
            return special_keys[key]

        try:
            if 32 <= int(key) <= 126:
                return chr(int(key)).lower()
        except Exception:
            pass
        return ""

    def _should_skip_duplicate_shortcut(self, signature):
        now = perf_counter()
        if signature == self._last_shortcut_signature and (now - self._last_shortcut_at) < 0.20:
            return True
        self._last_shortcut_signature = signature
        self._last_shortcut_at = now
        return False

    def _close_transient_panels(self):
        if self.quick_actions_open:
            self.quick_actions_open = False
            return True
        if self._dismiss_chart_menus():
            return True
        dialog = getattr(self, "_today_sales_dialog", None)
        if dialog is not None:
            self._dismiss_today_sales_dialog()
            return True
        return False

    def _dispatch_keyboard_shortcut(self, key, codepoint="", modifiers=None):
        if not self.manager or self.manager.current != self.name:
            return False

        key_name = self._normalize_key_name(key, codepoint)
        modifiers = {str(modifier or "").lower() for modifier in (modifiers or [])}
        signature = (key_name, tuple(sorted(modifiers)))
        if self._should_skip_duplicate_shortcut(signature):
            return False

        if key_name == "escape" and self._close_transient_panels():
            return True
        if self._has_open_modal():
            return False

        if "ctrl" in modifiers and key_name == "r":
            self.refresh_home()
            return True
        if "ctrl" in modifiers and key_name == "n":
            self.add_product()
            return True
        if "ctrl" in modifiers and key_name == "p":
            self.go_to_products()
            return True
        if "ctrl" in modifiers and key_name == "h":
            self.open_sales_history()
            return True
        if "ctrl" in modifiers and key_name == "t":
            self.open_today_sales()
            return True
        if "alt" in modifiers and key_name == "1":
            self.go_to_products()
            return True
        if "alt" in modifiers and key_name == "2":
            self.open_stock_module()
            return True
        if "alt" in modifiers and key_name == "3":
            self.open_losses_module()
            return True
        if "alt" in modifiers and key_name == "4":
            self.open_reports()
            return True
        if "alt" in modifiers and key_name == "u":
            self.open_users_module()
            return True
        if "alt" in modifiers and key_name == "p":
            self.show_all_pdfs()
            return True
        if "alt" in modifiers and key_name == "s":
            self.go_to_settings()
            return True
        return False

    def _handle_window_keyboard(self, _window, key, scancode=None, codepoint=None, modifiers=None):
        return self._dispatch_keyboard_shortcut(
            key,
            codepoint=codepoint or "",
            modifiers=modifiers or [],
        )

    def _handle_window_key_down(self, _window, key, scancode=None, codepoint=None, modifiers=None):
        return self._dispatch_keyboard_shortcut(
            key,
            codepoint=codepoint or "",
            modifiers=modifiers or [],
        )

    def _start_clock(self):
        self._update_datetime_text()
        if self._clock_ev:
            self._clock_ev.cancel()
        self._clock_ev = Clock.schedule_interval(lambda dt: self._update_datetime_text(), 30)

    def _init_badge(self, dt):
        if not hasattr(self, "ids"):
            return
        for badge_id in ("ai_badge", "recommendations_badge"):
            badge = self.ids.get(badge_id)
            if badge is not None:
                badge.opacity = 1
                badge.size = (dp(26), dp(26))

    def update_notification_badge(self, count):
        self.notification_count = max(0, int(count or 0))
        badge = self.ids.get("ai_badge") if hasattr(self, "ids") else None
        badge_label = self.ids.get("ai_badge_label") if hasattr(self, "ids") else None
        if badge is None or badge_label is None:
            return
        badge_label.text = str(self.notification_count)
        if self.notification_count > 0:
            self._show_badge()
            set_attention_shake(self.ids.get("ai_button"), True)
        else:
            badge.opacity = 1
            badge.size = (dp(26), dp(26))
            set_attention_shake(self.ids.get("ai_button"), False)

    def update_recommendation_badge(self, count):
        self.recommendation_count = max(0, int(count or 0))
        badge = self.ids.get("recommendations_badge") if hasattr(self, "ids") else None
        label = self.ids.get("recommendations_badge_label") if hasattr(self, "ids") else None
        if badge is None or label is None:
            return
        label.text = str(self.recommendation_count)
        Animation.cancel_all(badge)
        if self.recommendation_count > 0:
            badge.opacity = 1
            badge.size = (dp(0), dp(0))
            Animation(size=(dp(26), dp(26)), duration=0.25, transition="out_back").start(badge)
            set_attention_shake(self.ids.get("recommendations_button"), True)
            return
        badge.opacity = 1
        badge.size = (dp(26), dp(26))
        set_attention_shake(self.ids.get("recommendations_button"), False)

    def _show_badge(self):
        badge = self.ids.get("ai_badge") if hasattr(self, "ids") else None
        if badge is None:
            return
        Animation.cancel_all(badge)
        badge.opacity = 1
        badge.size = (dp(0), dp(0))
        Animation(
            size=(dp(26), dp(26)),
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
        self._get_intelligence().start()

    def _stop_ai_polling(self):
        if self._intelligence is not None:
            self._intelligence.stop()

    def _update_datetime_text(self):
        self.datetime_text = datetime.now().strftime("%d/%m/%Y | %H:%M")

    def _apply_hero_button_layout(self, fill_width):
        button_specs = (
            ("hero_add_button", dp(104)),
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

    def _update_responsive_layout(self, *_args):
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
            quick_cols = 2
            hero_orientation = "horizontal"
            hero_side_fill = False
            hero_height = dp(106)
            summary_height = dp(148)
            left_ratio, right_ratio = 0.67, 0.33
            card_ratios = (0.30, 0.46, 0.24)
            hero_buttons_fill = False
        elif width >= dp(1060):
            summary_cols = 2
            side_cols = 2
            quick_cols = 2
            hero_orientation = "horizontal"
            hero_side_fill = False
            hero_height = dp(120)
            summary_height = dp(242)
            left_ratio, right_ratio = 0.61, 0.39
            card_ratios = (0.30, 0.46, 0.24)
            hero_buttons_fill = False
        else:
            summary_cols = 2
            side_cols = 1
            quick_cols = 2
            hero_orientation = "vertical"
            hero_side_fill = True
            hero_height = dp(168)
            summary_height = dp(242)
            left_ratio, right_ratio = 0.57, 0.43
            card_ratios = (0.28, 0.48, 0.24)
            hero_buttons_fill = True

        if summary_grid:
            summary_grid.cols = summary_cols
        if alerts_grid:
            alerts_grid.cols = side_cols
        if quick_actions_grid:
            quick_actions_grid.cols = quick_cols
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

    def toggle_quick_actions(self, *args):
        self.quick_actions_open = not self.quick_actions_open

    def _ensure_chart_widgets(self):
        sales_host = self.ids.get("chart_canvas_host") if hasattr(self, "ids") else None
        if sales_host is None:
            sales_host = self.ids.get("sales_chart_host") if hasattr(self, "ids") else None
        if sales_host and self._sales_chart is None:
            self._sales_chart = SalesTrendChart()
            self._sales_chart.size_hint_y = 1
            sales_host.add_widget(self._sales_chart)

    def refresh_home(self, *args):
        self._ensure_snapshot_loaded(force=True)

    def _warmup_settings_screen(self):
        if self._settings_warmup_requested or not self.manager:
            return
        if "settings" in self.manager.screen_names:
            self._settings_warmup_requested = True
            return
        app = App.get_running_app()
        warmup = getattr(app, "warmup_screens", None)
        if not callable(warmup):
            return
        self._settings_warmup_requested = bool(warmup(("settings",), delay=0.04))

    def _ensure_snapshot_loaded(self, force=False):
        if self._snapshot_loading:
            return
        age = perf_counter() - self._snapshot_loaded_at
        same_period = self._snapshot_period_days == self._chart_period_days
        if not force and same_period and self._snapshot is not None and age < self.HOME_CACHE_SECONDS:
            self._render_dashboard()
            return
        self._load_snapshot_async()

    def _load_snapshot_async(self):
        token = self._snapshot_token + 1
        self._snapshot_token = token
        period_days = self._chart_period_days
        connection_factory = getattr(self.db, "background_connection", None)
        connection = connection_factory() if callable(connection_factory) else nullcontext(self.db)
        self._snapshot_loading = True
        self._snapshot_error = None
        self._render_dashboard()

        def worker():
            payload = None
            error = None
            try:
                with connection as db:
                    payload = db.get_admin_home_snapshot(lookback_days=period_days) or {}
            except Exception as exc:
                error = str(exc)
            if (payload is None or payload == {}) and error is None:
                last_error_fn = getattr(self.db, "last_error", None)
                if callable(last_error_fn):
                    error = last_error_fn()
            Clock.schedule_once(
                lambda dt, data=payload, err=error, tok=token: self._apply_snapshot(data, err, tok, period_days),
                0,
            )

        Thread(target=worker, daemon=True).start()

    def _apply_snapshot(self, payload, error=None, token=None, period_days=None):
        if token is not None and token != self._snapshot_token:
            return
        self._snapshot_loading = False
        if period_days is not None and period_days != self._chart_period_days:
            if self.manager and self.manager.current == self.name:
                self._ensure_snapshot_loaded(force=True)
            return
        self._snapshot_loaded_at = perf_counter()
        self._snapshot_period_days = period_days if period_days is not None else self._chart_period_days
        self._snapshot_error = str(error).strip() if error else None
        self._snapshot = payload or {}
        self._render_dashboard()

    def _render_dashboard(self):
        snapshot = self._snapshot or {}
        self._render_header(snapshot)
        self._render_summary_cards(snapshot.get("summary") or {})
        self._render_alert_cards(snapshot.get("alerts") or {})
        self._render_insights(snapshot)
        self._schedule_chart_render(snapshot)

    def _schedule_chart_render(self, snapshot):
        sales_series = snapshot.get("sales_series") or []
        stock_series = snapshot.get("stock_flow_series") or []
        top_products = snapshot.get("top_products") or []
        signature = (
            id(snapshot),
            self._chart_metric,
            self._chart_period_days,
            self._snapshot_error,
            bool(self._snapshot_loading),
            len(sales_series),
            len(stock_series),
            len(top_products),
        )
        if signature == self._chart_render_signature:
            return
        self._chart_render_signature = signature

        if self._chart_render_ev is not None:
            self._chart_render_ev.cancel()
        self._chart_render_ev = Clock.schedule_once(
            lambda dt, data=snapshot: self._render_chart(data),
            0,
        )

    def _render_chart(self, snapshot):
        self._chart_render_ev = None
        if snapshot and self._sales_chart is None:
            self._ensure_chart_widgets()
        if self._sales_chart:
            if self._snapshot_error:
                self._sales_chart.set_state_text("Falha ao carregar indicadores.")
            elif self._snapshot_loading and not snapshot:
                self._sales_chart.set_state_text("Indicadores a atualizar em segundo plano.")
            elif not snapshot:
                self._sales_chart.set_state_text("Indicadores visuais serao carregados em segundo plano.")
            else:
                self._sales_chart.set_dashboard(
                    metric=self._chart_metric,
                    period_label=self.chart_period_text,
                    sales_series=snapshot.get("sales_series") or [],
                    stock_series=snapshot.get("stock_flow_series") or [],
                    top_products=snapshot.get("top_products") or [],
                )

    def _render_header(self, snapshot):
        app = App.get_running_app()
        username = (getattr(app, "current_user", None) or "Administrador").strip() or "Administrador"
        first_name = username.split()[0]
        hour = datetime.now().hour
        greeting = "Bom dia" if hour < 12 else ("Boa tarde" if hour < 18 else "Boa noite")
        self.home_title = f"{greeting}, {first_name}"
        self.home_subtitle = self._build_header_subtitle(snapshot)

        if self._snapshot_error:
            self.status_text = "Resumo indisponivel no momento."
        elif self._snapshot_loading and not snapshot:
            self.status_text = "A atualizar dados..."
        else:
            summary = snapshot.get("summary") or {}
            alerts = snapshot.get("alerts") or {}
            total_alerts = sum(int(value or 0) for value in (alerts.get("counts") or {}).values())
            self.status_text = f"Hoje: {_format_mzn(summary.get('revenue_today'))} | Alertas ativos: {total_alerts}"
    def _build_header_subtitle(self, snapshot):
        if self._snapshot_error:
            return "Nao foi possivel atualizar os dados agora."
        if self._snapshot_loading and not snapshot:
            return "Vendas, stock e alertas."

        summary = snapshot.get("summary") or {}
        alerts = snapshot.get("alerts") or {}
        counts = alerts.get("counts") or {}
        comparison = snapshot.get("comparison") or {}
        context = snapshot.get("context") or {}

        expired = int(counts.get("expired") or 0)
        critical = int(counts.get("critical_stock") or 0)
        out_of_stock = int(counts.get("out_of_stock") or 0)
        expiring = int(counts.get("expiring_soon") or 0)
        direction = comparison.get("direction")
        delta_percent = comparison.get("delta_percent")
        peak_hour = context.get("peak_hour")
        top_product = context.get("top_product_today") or {}

        if expired > 0 or critical > 0 or out_of_stock > 0:
            parts = []
            if expired > 0:
                parts.append(f"{expired} itens vencidos")
            if critical > 0:
                parts.append(f"{critical} produtos com stock critico")
            if out_of_stock > 0:
                parts.append(f"{out_of_stock} produtos esgotados")
            return ", ".join(parts) + " requerem atencao."
        if expiring > 0:
            return f"Ha {expiring} produtos perto do vencimento."
        if direction == "above" and delta_percent is not None:
            return f"A receita de hoje esta {abs(delta_percent):.1f}% acima da media recente."
        if direction == "below" and delta_percent is not None:
            return f"A receita de hoje esta {abs(delta_percent):.1f}% abaixo da media recente."
        if top_product:
            suffix = f" Hora de maior movimento: {peak_hour}." if peak_hour else ""
            return f"Mais vendido hoje: {top_product.get('name')}.{suffix}"
        if float(summary.get("revenue_today") or 0.0) > 0:
            return "Vendas em curso."
        return "Sem vendas hoje."

    def _render_summary_cards(self, summary):
        grid = self.ids.get("summary_grid")
        if grid is None:
            return

        user_logs_today = int(summary.get("user_logs_today") or 0)
        sales_today = int(summary.get("sales_today_count") or 0)
        revenue_today = float(summary.get("revenue_today") or 0.0)
        alert_counts = self._get_home_alerts().get("counts") or {}
        fraud_alerts = int(alert_counts.get("fraud_alerts") or 0)
        theme_style = getattr(App.get_running_app(), "theme_style", "Light")

        specs = [
            ("Faturacao Hoje", _format_mzn(revenue_today), "Receita atual do dia", "cash-multiple", "primary", self.show_today_revenue),
            ("Vendas Hoje", _format_value(sales_today), "Resumo do dia", "cash-register", "success", self.open_today_sales),
            ("Acoes de utilizadores", _format_value(user_logs_today), "Registos de hoje", "text-box-search-outline", "info", self.open_user_logs),
            ("Alertas de fraude", _format_value(fraud_alerts), "Sinais a verificar", "shield-alert-outline", "danger" if fraud_alerts else "success", self.show_operational_alerts_banner),
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
            hover_accent_color=accent,
            hover_bg_mix=0.10,
            hover_line_mix=0.26,
            hover_elevation_delta=2.0,
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
            ("Reposicao", "Entrada de stock", "package-variant-plus", "warning", self.open_stock_module),
            ("Perdas", "Quebras e ajustes", "alert-circle-outline", "danger", self.open_losses_module),
            ("Relatorios", "Relatorios e PDF", "chart-box-outline", "info", self.open_reports),
            ("Definicoes", "Sistema", "cog-outline", "primary", self.go_to_settings),
            ("Utilizadores", "Acessos", "account-key-outline", "primary", self.open_users_module),
        ]

        for title, subtitle, icon_name, tone, callback in actions:
            grid.add_widget(self._build_quick_action_card(title, subtitle, icon_name, tone, callback))

    def _run_quick_action(self, callback):
        if not callable(callback):
            return
        key = id(callback)
        now = perf_counter()
        if key == self._quick_action_last_key and (now - self._quick_action_last_at) < 0.28:
            return
        self._quick_action_last_key = key
        self._quick_action_last_at = now
        callback()

    def _build_quick_action_card(self, title, subtitle, icon_name, tone, callback):
        tokens = getattr(App.get_running_app(), "theme_tokens", {}) or {}
        accent = tokens.get(tone, tokens.get("primary", [0.10, 0.35, 0.65, 1]))
        if tone == "text_secondary":
            accent = tokens.get("text_secondary", [0.45, 0.48, 0.52, 1])

        card = Factory.HomeButtonCard(
            orientation="vertical",
            size_hint_y=None,
            height=dp(56),
            padding=[dp(10), dp(8), dp(10), dp(8)],
            spacing=dp(1),
            radius=[dp(12)],
            elevation=1,
            md_bg_color=tokens.get("card", [1, 1, 1, 1]),
            hover_accent_color=accent,
            hover_bg_mix=0.10,
            hover_line_mix=0.26,
            hover_elevation_delta=2.0,
        )
        card.bind(on_press=lambda *_: self._run_quick_action(callback))

        header = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(22), spacing=dp(6))
        icon_chip = MDCard(
            size_hint=(None, None),
            size=(dp(22), dp(22)),
            radius=[dp(7)],
            elevation=0,
            md_bg_color=[accent[0], accent[1], accent[2], 0.14],
        )
        icon_label = MDIcon(icon=icon_name, halign="center", valign="middle")
        icon_label.bind(size=lambda inst, value: setattr(inst, "text_size", value))
        _set_label_text_color(icon_label, accent)
        icon_chip.add_widget(icon_label)

        title_label = MDLabel(text=title, font_style="Caption", bold=True)
        title_label.shorten = True
        title_label.shorten_from = "right"
        _set_label_text_color(title_label, tokens.get("text_primary", [0.2, 0.2, 0.2, 1]))
        header.add_widget(icon_chip)
        header.add_widget(title_label)

        subtitle_label = MDLabel(text=subtitle, font_style="Caption", size_hint_y=None, height=dp(16))
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
            cards.append(("Stock critico", int(counts.get("critical_stock") or 0), "warning", "alert-decagram-outline", f"{first.get('name', 'Reposicao')} esta com cobertura curta de stock.", self.show_stock_critical_banner))
        if int(counts.get("out_of_stock") or 0) > 0:
            first = out_of_stock_items[0] if out_of_stock_items else {}
            cards.append(("Produtos esgotados", int(counts.get("out_of_stock") or 0), "danger", "close-octagon-outline", f"{first.get('name', 'Ha produtos')} ja estao sem disponibilidade.", self.show_out_of_stock_banner))
        if int(counts.get("expiring_soon") or 0) > 0:
            first = expiring_items[0] if expiring_items else {}
            day_text = first.get("days_left")
            suffix = f" em {day_text} dias" if day_text is not None else ""
            cards.append(("Validades proximas", int(counts.get("expiring_soon") or 0), "warning", "calendar-clock-outline", f"{first.get('name', 'Itens com validade')} vencem{suffix}.", self.show_expiring_products_banner))
        if int(counts.get("pending_approvals") or 0) > 0:
            first = pending_items[0] if pending_items else {}
            cards.append(("Pendencias administrativas", int(counts.get("pending_approvals") or 0), "info", "clipboard-alert-outline", f"{first.get('product_name', 'Movimentos')} aguardam validacao.", self.show_pending_approvals_banner))
        if int(counts.get("fraud_alerts") or 0) > 0:
            first = fraud_items[0] if fraud_items else {}
            cards.append(("Alertas operacionais", int(counts.get("fraud_alerts") or 0), "danger", "shield-alert-outline", first.get("title") or "Foram encontrados padroes a rever.", self.show_operational_alerts_banner))
        if int(counts.get("negative_profit") or 0) > 0:
            first = negative_profit_items[0] if negative_profit_items else {}
            cards.append(("Margem negativa", int(counts.get("negative_profit") or 0), "warning", "cash-remove", f"{first.get('name', 'Alguns itens')} precisam de revisao de preco.", self.show_negative_profit_banner))

        if not cards:
            cards = [("Sem alertas", 0, "success", "check-circle-outline", "Sem alertas neste momento.", self.refresh_home)]

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
            hover_accent_color=accent,
            hover_bg_mix=0.10,
            hover_line_mix=0.26,
            hover_elevation_delta=2.0,
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
            meta_label.text = "Resumo do dia"

        insights = self._build_insight_specs(snapshot)[:2]
        theme_style = getattr(App.get_running_app(), "theme_style", "Light")
        signature = (theme_style, tuple((title, text, icon_name, tone) for title, text, icon_name, tone, _callback in insights))
        if signature == self._insights_render_signature:
            return
        self._insights_render_signature = signature
        grid.clear_widgets()

        for title, text, icon_name, tone, callback in insights:
            grid.add_widget(self._build_insight_card(title, text, icon_name, tone, callback))

    def _build_insight_specs(self, snapshot):
        summary = snapshot.get("summary") or {}
        comparison = snapshot.get("comparison") or {}
        context = snapshot.get("context") or {}
        items = []

        top_product = context.get("top_product_today") or {}
        if top_product:
            items.append((
                "Mais vendido hoje",
                f"{top_product.get('name')} vendeu {_format_mzn(top_product.get('revenue') or 0.0)} hoje.",
                "star-circle-outline",
                "primary",
                lambda name=top_product.get("name"): self.go_to_products(query=name),
            ))

        direction = comparison.get("direction")
        delta_percent = comparison.get("delta_percent")
        if direction == "above" and delta_percent is not None:
            items.append(("Vendas do dia", f"A receita esta {abs(delta_percent):.1f}% acima da media recente.", "trending-up", "success", None))
        elif direction == "below" and delta_percent is not None:
            items.append(("Vendas do dia", f"A receita esta {abs(delta_percent):.1f}% abaixo da media recente.", "trending-down", "warning", None))

        if not items:
            items.append(("Vendas do dia", f"Total vendido hoje: {_format_mzn(summary.get('revenue_today') or 0.0)}.", "cash-register", "success", None))
            critical_stock = int(summary.get("critical_stock") or 0)
            stock_text = f"{critical_stock} produto(s) com stock critico." if critical_stock else "Sem produtos com stock critico."
            items.append(("Stock", stock_text, "package-variant", "warning" if critical_stock else "success", self.show_stock_critical_banner if critical_stock else self.go_to_products))

        return items[:4]

    def _build_insight_card(self, title, text, icon_name, tone, callback=None):
        tokens = getattr(App.get_running_app(), "theme_tokens", {}) or {}
        accent = tokens.get(tone, tokens.get("primary", [0.10, 0.35, 0.65, 1]))

        card_kwargs = dict(
            orientation="vertical",
            size_hint_y=None,
            height=dp(68),
            padding=[dp(12), dp(10), dp(12), dp(10)],
            spacing=dp(2),
            radius=[dp(12)],
            elevation=1,
            md_bg_color=tokens.get("card_alt", [0.95, 0.96, 0.98, 1]),
        )
        if callback:
            card = Factory.HomeButtonCard(
                **card_kwargs,
                hover_accent_color=accent,
                hover_bg_mix=0.08,
                hover_line_mix=0.24,
                hover_elevation_delta=1.5,
            )
            card.bind(on_release=lambda *_: callback())
        else:
            card = MDCard(**card_kwargs)

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
        products = {}
        hours = {}
        transaction_keys = set()
        promotional_transaction_keys = set()
        recent_sales = []

        for row in rows:
            product_name = str(row[1] if len(row) > 1 and row[1] is not None else "Produto").strip() or "Produto"
            qty = float(row[2] or 0) if len(row) > 2 else 0.0
            unit_price = float(row[3] or 0) if len(row) > 3 else 0.0
            total = float(row[4] or 0) if len(row) > 4 else 0.0
            sale_raw = row[5] if len(row) > 5 else ""
            returned_qty = float(row[6] or 0) if len(row) > 6 else 0.0
            is_promotional = bool(row[10]) if len(row) > 10 else False
            transaction_code = str(row[12] if len(row) > 12 and row[12] is not None else "").strip()
            transaction_key = transaction_code or f"sale:{row[0] if row else ''}"
            sale_dt = self._parse_sale_datetime(sale_raw)
            refund_amount = returned_qty * unit_price
            net_total = max(0.0, total - refund_amount)
            net_qty = max(0.0, qty - returned_qty)

            gross_total += total
            refunded_total += refund_amount
            total_qty += net_qty
            transaction_keys.add(transaction_key)
            if is_promotional:
                promotional_transaction_keys.add(transaction_key)

            product_bucket = products.setdefault(product_name, {"count": 0, "net_total": 0.0})
            product_bucket["count"] += 1
            product_bucket["net_total"] += net_total

            if sale_dt is not None:
                hour_key = sale_dt.strftime("%H:00")
                hours.setdefault(hour_key, set()).add(transaction_key)
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
            peak_hour = max(hours.items(), key=lambda item: (len(item[1]), item[0]))[0]

        return {
            "total_sales": len(transaction_keys),
            "gross_total": gross_total,
            "refunded_total": refunded_total,
            "net_total": max(0.0, gross_total - refunded_total),
            "total_qty": total_qty,
            "promo_sales": len(promotional_transaction_keys),
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
                    "O resumo aparece apos a primeira venda.",
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
                f"Mais vendido: {top_product.get('name')} com {_format_mzn(top_product.get('net_total') or 0.0)}"
            )

        peak_hour = summary.get("peak_hour")
        if peak_hour:
            lines.append(f"Hora de maior movimento: {peak_hour}")

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
            Clock.schedule_once(lambda dt: screen.filter_today(), 0)
        elif screen and hasattr(screen, "request_enter_refresh"):
            Clock.schedule_once(lambda dt: screen.request_enter_refresh(force=False, delay=0), 0)

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

    @staticmethod
    def _translate_operational_text(value):
        """Evita que códigos técnicos da base de dados apareçam nos alertas."""
        translated = str(value or "")
        labels = {
            "ADJUSTMENT": "Ajuste",
            "DAMAGE": "Danificado",
            "EXPIRED": "Expirado",
            "THEFT": "roubo",
        }
        for code, label in labels.items():
            translated = translated.replace(code, label)
        return translated

    def _format_banner_quantity(self, stock, unit="un"):
        try:
            amount = float(stock or 0)
        except Exception:
            amount = 0.0
        unit_text = str(unit or "un").strip() or "un"
        if unit_text.lower() == "kg":
            number = f"{amount:.2f}".rstrip("0").rstrip(".").replace(".", ",")
            return f"{number} kg"
        if abs(amount - round(amount)) < 0.05:
            return f"{int(round(amount))} {unit_text}"
        return f"{amount:.1f}".replace(".", ",") + f" {unit_text}"

    def _alert_item_name(self, item, fallback="Produto"):
        item = item or {}
        return str(
            item.get("name")
            or item.get("product_name")
            or item.get("title")
            or fallback
        ).strip() or fallback

    def _alert_product_id(self, item):
        item = item or {}
        product_id = item.get("product_id")
        return product_id if product_id not in (None, "") else None

    def _alert_query(self, item):
        return self._alert_item_name(item, fallback="")

    def _stock_unit(self, item):
        return "kg" if bool((item or {}).get("is_weight")) else "un"

    def _action_button(self, text, callback):
        return {
            "text": text,
            "callback": callback,
            "dismiss_after": True,
        }

    def _build_stock_alert_banner(self, key, title, variant, icon, empty_kind="stock"):
        items = list(self._get_home_alerts().get(key) or [])
        if not items:
            from utils.ai.ai_popups import build_positive_banner
            banner = build_positive_banner(empty_kind)
            banner["details_sections"] = [("Estado atual", ["Nenhum produto nesta prioridade agora."])]
            return banner

        messages = []
        detail_lines = []
        for item in items:
            name = self._alert_item_name(item)
            qty = self._format_banner_quantity(item.get("stock"), self._stock_unit(item))
            days_left = item.get("days_left")
            if days_left is None:
                messages.append(f"{name}: stock atual {qty}. Reponha quando possível.")
                detail_lines.append(f"{name}: stock atual {qty}.")
            else:
                messages.append(f"{name}: restam {qty}. Cobertura estimada: {days_left} dia(s).")
                detail_lines.append(f"{name}: stock {qty}; cobertura estimada: {days_left} dia(s).")

        first = items[0] if items else {}
        return {
            "kind": "stock",
            "variant": variant,
            "icon": icon,
            "bg_color": (0.96, 0.62, 0.22, 1) if variant == "warning" else (0.93, 0.34, 0.34, 1),
            "title": title,
            "messages": messages[:5],
            "all_messages": messages,
            "count": len(items),
            "urgency": 0 if variant == "danger" else 3,
            "details_sections": [
                ("Produtos", detail_lines),
                ("Proxima acao", ["Abra a reposicao e registe a nova entrada de stock."]),
            ],
            "action_buttons": [
                self._action_button("Repor produto", lambda item=first: self.open_restock_modal(product_item=item)),
            ],
        }

    def _build_expired_products_banner(self):
        items = list(self._get_home_alerts().get("expired_items") or [])
        if not items:
            from utils.ai.ai_popups import build_positive_banner
            banner = build_positive_banner("expiry")
            banner["details_sections"] = [("Estado atual", ["Nenhum produto vencido na leitura atual da HOME."])]
            return banner

        messages = []
        detail_lines = []
        for item in items:
            name = self._alert_item_name(item)
            expiry_date = str(item.get("date") or "data nao informada")
            qty = self._format_banner_quantity(item.get("stock"), item.get("unit") or "un")
            messages.append(f"{name}: vencido em {expiry_date}.")
            detail_lines.append(f"{name}: stock {qty}; validade {expiry_date}.")

        first = items[0] if items else {}

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
                    "Registe a perda ou trate da devolucao assim que possível.",
                ]),
            ],
            "action_buttons": [
                self._action_button("Registar perda", lambda item=first: self.open_losses_module(product_item=item, loss_type_label="EXPIRADO", loss_type_code="EXPIRED")),
            ],
        }

    def _build_expiring_products_banner(self):
        items = list(self._get_home_alerts().get("expiring_items") or [])
        if not items:
            from utils.ai.ai_popups import build_positive_banner
            banner = build_positive_banner("expiry")
            banner["details_sections"] = [("Estado atual", ["Nenhum produto proximo do vencimento agora."])]
            return banner

        messages = []
        detail_lines = []
        for item in items:
            name = self._alert_item_name(item)
            days_left = item.get("days_left")
            expiry_date = str(item.get("date") or "data nao informada")
            qty = self._format_banner_quantity(item.get("stock"), item.get("unit") or "un")
            messages.append(f"{name}: vence em {days_left} dia(s) ({expiry_date}).")
            detail_lines.append(f"{name}: stock {qty}; vence em {expiry_date}.")

        first = items[0] if items else {}
        return {
            "kind": "expiry",
            "variant": "warning",
            "icon": "calendar-clock-outline",
            "bg_color": (0.96, 0.62, 0.22, 1),
            "title": "Validades proximas",
            "messages": messages[:5],
            "all_messages": messages,
            "count": len(items),
            "urgency": 7,
            "details_sections": [
                ("Produtos em atencao", detail_lines),
                ("Proxima acao", ["Abra o produto para rever preço, validade ou prioridade de venda."]),
            ],
            "action_buttons": [
                self._action_button("Registar perda", lambda item=first: self.open_losses_module(product_item=item)),
            ],
        }

    def _build_pending_approvals_home_banner(self):
        items = list(self._get_home_alerts().get("pending_items") or [])
        messages = []
        detail_lines = []
        for item in items:
            name = self._alert_item_name(item, "Movimento")
            qty = self._format_banner_quantity(item.get("qty"), item.get("unit") or "un")
            messages.append(f"{name}: {qty} aguardam validacao.")
            detail_lines.append(f"{name}: {qty}, criado por {item.get('created_by') or 'utilizador nao informado'}.")
        if not messages:
            messages = ["Nao existem pendencias administrativas neste momento."]

        first = items[0] if items else {}
        return {
            "kind": "approvals",
            "variant": "info",
            "icon": "clipboard-alert-outline",
            "bg_color": (0.35, 0.62, 0.93, 1),
            "title": "Pendencias administrativas",
            "messages": messages[:5],
            "all_messages": messages,
            "count": len(items),
            "urgency": 5,
            "details_sections": [
                ("Movimentos pendentes", detail_lines or messages),
                ("Proxima acao", ["Valide ou rejeite os movimentos pendentes antes de fechar o controlo de stock."]),
            ],
            "action_buttons": [
                self._action_button("Validar pendencias", self.open_pending_approvals),
            ],
        }

    def _build_operational_alerts_banner(self):
        items = list(self._get_home_alerts().get("fraud_items") or [])
        first = items[0] if items else {}
        messages = [
            f"{self._translate_operational_text(self._alert_item_name(item, 'Alerta'))}: "
            f"{self._translate_operational_text(item.get('description') or 'verificacao necessaria')}"
            for item in items
        ]
        if not messages:
            messages = ["Sem alertas operacionais criticos neste momento."]
        return {
            "kind": "operational",
            "variant": "danger" if items else "success",
            "icon": "shield-alert-outline",
            "bg_color": (0.93, 0.34, 0.34, 1) if items else (0.36, 0.72, 0.45, 1),
            "title": "Alertas operacionais",
            "messages": messages[:5],
            "all_messages": messages,
            "count": len(items),
            "urgency": 1 if items else 999,
            "details_sections": [
                ("Ocorrencias", messages),
                ("Proxima acao", ["Reveja perdas, movimentos e evidencias associadas."]),
            ],
            "action_buttons": [
                self._action_button("Rever perdas", self.open_losses_module),
            ],
        }

    def _build_operational_alert_banners(self):
        """Cria um banner por alerta para preservar a cor da prioridade."""
        items = sorted(
            list(self._get_home_alerts().get("fraud_items") or []),
            key=lambda item: int(item.get("severity") or 0),
            reverse=True,
        )
        if not items:
            return [{
                "kind": "operational_ok",
                "variant": "success",
                "icon": "shield-check-outline",
                "bg_color": (0.36, 0.72, 0.45, 1),
                "title": "Alertas operacionais em dia",
                "messages": ["Não existem alertas operacionais críticos neste momento."],
                "all_messages": [],
                "count": 0,
                "urgency": 999,
                "details_sections": [("Estado atual", ["Nenhum padrão de fraude exige revisão."])],
                "action_buttons": [],
            }]

        palettes = {
            3: ("danger", "shield-alert-outline", (0.93, 0.34, 0.34, 1), "ALTO", 0),
            2: ("warning", "alert-outline", (0.96, 0.62, 0.22, 1), "MÉDIO", 8),
            1: ("info", "information-outline", (0.35, 0.62, 0.93, 1), "BAIXO", 18),
        }
        banners = []
        for item in items[:8]:
            severity = int(item.get("severity") or 0)
            variant, icon, bg_color, label, urgency = palettes.get(
                severity,
                ("info", "information-outline", (0.35, 0.62, 0.93, 1), "INFORMATIVO", 25),
            )
            title = self._translate_operational_text(item.get("title") or "Alerta operacional").strip()
            description = self._translate_operational_text(
                item.get("description") or "Verificação necessária."
            ).strip()
            banners.append({
                "kind": f"operational_{severity or 'info'}",
                "variant": variant,
                "icon": icon,
                "bg_color": bg_color,
                "title": f"{label} · {title}",
                "messages": [description],
                "all_messages": [description],
                "count": 1,
                "urgency": urgency,
                "details_sections": [
                    ("Alerta identificado", [description]),
                    ("Orientação", ["Revise o movimento e a quantidade registada antes de tomar uma decisão."]),
                ],
                "action_buttons": [],
            })
        return banners

    def _build_negative_profit_banner(self):
        items = list(self._get_home_alerts().get("negative_profit_items") or [])
        messages = []
        detail_lines = []
        for item in items:
            name = self._alert_item_name(item)
            profit = _format_mzn(item.get("profit_per_unit") or 0)
            messages.append(f"{name} esta com margem negativa: {profit} por unidade.")
            detail_lines.append(f"{name}: margem por unidade {profit}.")
        if not messages:
            messages = ["Nenhum produto com margem negativa na leitura atual."]

        first = items[0] if items else {}
        return {
            "kind": "profit",
            "variant": "warning" if items else "success",
            "icon": "cash-remove",
            "bg_color": (0.96, 0.62, 0.22, 1) if items else (0.36, 0.72, 0.45, 1),
            "title": "Margem negativa",
            "messages": messages[:5],
            "all_messages": messages,
            "count": len(items),
            "urgency": 12,
            "details_sections": [
                ("Produtos", detail_lines or messages),
                ("Proxima acao", ["Revise preco de venda, custo de compra e regras de margem."]),
            ],
            "action_buttons": [
                self._action_button("Abrir relatorios", self.open_reports),
            ],
        }

    def _show_home_banners(self, banner_data_list):
        banners = [dict(item) for item in list(banner_data_list or []) if item]
        if not banners or not hasattr(self, "ids") or "ai_banner_container" not in self.ids:
            return

        # Home banners keep only their contextual actions. Product-navigation
        # shortcuts are intentionally removed from this compact presentation.
        for banner_data in banners:
            supplied_actions = [
                action
                for action in (banner_data.get("action_buttons") or [])
                if isinstance(action, dict) and str(action.get("text") or "").strip()
            ]
            banner_data["action_buttons"] = [
                action
                for action in supplied_actions
                if not str(action.get("text") or "").strip().casefold().startswith(
                    ("ver produto", "adicionar produto")
                )
            ][:2]

        target = self.ids.ai_banner_container
        ensure_center = getattr(self._get_intelligence(), "_ensure_banner_center", None)
        if callable(ensure_center):
            try:
                target = ensure_center()
            except Exception:
                target = self.ids.ai_banner_container

        show_history = getattr(target, "_show_history_banners", None)
        if callable(show_history):
            target.current_insights = {}
            show_history(banners)
            return

        from utils.ai.ai_popups import render_auto_banners
        render_auto_banners(
            target,
            banners,
            insights=None,
            auto_dismiss_seconds=None,
            show_timer=False,
        )

    def _show_single_home_banner(self, banner_data):
        self._show_home_banners([banner_data])

    def show_expired_products_banner(self, *args):
        self._show_single_home_banner(self._build_expired_products_banner())

    def show_stock_critical_banner(self, *args):
        self._show_single_home_banner(
            self._build_stock_alert_banner(
                "low_stock_items",
                "Stock critico",
                "warning",
                "alert-decagram-outline",
            )
        )

    def show_out_of_stock_banner(self, *args):
        self._show_single_home_banner(
            self._build_stock_alert_banner(
                "out_of_stock_items",
                "Produtos esgotados",
                "danger",
                "close-octagon-outline",
            )
        )

    def show_expiring_products_banner(self, *args):
        self._show_single_home_banner(self._build_expiring_products_banner())

    def show_pending_approvals_banner(self, *args):
        self._show_single_home_banner(self._build_pending_approvals_home_banner())

    def show_operational_alerts_banner(self, *args):
        self._show_home_banners(self._build_operational_alert_banners())

    def show_negative_profit_banner(self, *args):
        self._show_single_home_banner(self._build_negative_profit_banner())

    def _resolve_action_lookup(self, product_item=None, product_id=None, query=None):
        item = product_item or {}
        resolved_id = product_id if product_id not in (None, "") else self._alert_product_id(item)
        resolved_query = str(query or "").strip() or self._alert_query(item)
        return resolved_id, resolved_query

    def go_to_products(self, *args, open_form=False, product_item=None, product_id=None, query=None):
        screen = self._set_back_target("admin", "admin_home")
        if not screen or not self.manager:
            return
        self.manager.current = "admin"

        resolved_id, resolved_query = self._resolve_action_lookup(
            product_item=product_item,
            product_id=product_id,
            query=query,
        )

        def focus_product():
            search_text = str(resolved_id or resolved_query or "").strip()
            if not search_text:
                return
            if hasattr(screen, "_pending_search"):
                screen._pending_search = search_text
            search_input = getattr(screen, "search_input", None)
            if search_input is None and hasattr(screen, "ids"):
                search_input = screen.ids.get("search_input")
            if search_input is not None:
                search_input.text = search_text
            if getattr(screen, "products", None):
                if hasattr(screen, "filter_products"):
                    screen.filter_products(search_text, reset_page=True)
            elif hasattr(screen, "load_products"):
                screen.load_products()

        if resolved_id or resolved_query:
            Clock.schedule_once(lambda dt: focus_product(), 0)
        if open_form and hasattr(screen, "add_product"):
            Clock.schedule_once(lambda dt: screen.add_product(), 0)

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
            Clock.schedule_once(lambda dt: screen.prepare_open_from_admin(), 0)

    def show_all_pdfs(self, *args):
        if not self.manager:
            return
        screen = self._set_back_target("reports", "admin_home")
        if not screen or not hasattr(screen, "show_pdf_viewer"):
            return
        self.manager.current = "reports"
        if hasattr(screen, "prepare_open_from_admin"):
            Clock.schedule_once(lambda dt: screen.prepare_open_from_admin(), 0)
        Clock.schedule_once(lambda dt: screen.show_pdf_viewer(), 0)

    def open_sales_history(self, *args):
        if not self.manager:
            return
        screen = self._set_back_target("sales_history", "admin_home")
        if not screen:
            return
        self.manager.current = "sales_history"
        if screen and hasattr(screen, "request_enter_refresh"):
            Clock.schedule_once(lambda dt: screen.request_enter_refresh(force=False, delay=0), 0)

    def show_today_revenue(self, *args):
        self._dismiss_today_sales_dialog()
        summary = (self._snapshot or {}).get("summary") or {}
        today_label = datetime.now().strftime("%d/%m/%Y")
        revenue = _format_mzn(summary.get("revenue_today") or 0.0)
        dialog = MDDialog(
            title="Faturacao de Hoje",
            text=f"Data: {today_label}\nFaturacao: {revenue}",
            buttons=[
                MDFlatButton(text="FECHAR", on_release=lambda _x: dialog.dismiss()),
            ],
        )
        self._today_sales_dialog = dialog
        dialog.bind(on_dismiss=lambda *_: setattr(self, "_today_sales_dialog", None))
        dialog.open()

    def open_today_sales(self, *args):
        if self._today_sales_loading:
            return
        self._dismiss_today_sales_dialog()
        self._today_sales_loading = True
        today_label = datetime.now().strftime("%d/%m/%Y")

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

    def open_pending_approvals(self, *args):
        dialog, token = self._open_home_action_loader(
            "Aprovações pendentes",
            "A carregar movimentos que aguardam validação...",
        )

        def worker():
            pending = None
            error = None
            try:
                pending = list(self.db.get_pending_approvals() or [])
            except Exception as exc:
                error = str(exc)
            Clock.schedule_once(
                lambda _dt, rows=pending, detail=error: self._show_home_pending_approvals(rows, detail, dialog, token),
                0,
            )

        Thread(target=worker, daemon=True).start()

    def open_loss_metrics(self, *args):
        dialog, token = self._open_home_action_loader(
            "Métricas de perdas",
            "A calcular os indicadores dos últimos 30 dias...",
        )
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)

        def worker():
            metrics = None
            error = None
            try:
                metrics = self.db.calculate_loss_metrics(start_date, end_date) or {}
            except Exception as exc:
                error = str(exc)
            Clock.schedule_once(
                lambda _dt, data=metrics, detail=error: self._show_home_loss_metrics(
                    data,
                    detail,
                    start_date,
                    end_date,
                    dialog,
                    token,
                ),
                0,
            )

        Thread(target=worker, daemon=True).start()

    def open_operational_alerts(self, *args):
        self.show_operational_alerts_banner()

    def _open_home_action_loader(self, title, message):
        current = self._home_action_dialog
        if current is not None:
            self._home_action_dialog = None
            try:
                current.dismiss()
            except Exception:
                pass

        self._home_action_token += 1
        token = self._home_action_token
        dialog = MDDialog(
            title=title,
            text=message,
            buttons=[MDFlatButton(text="FECHAR", on_release=lambda *_args: dialog.dismiss())],
        )

        def clear_reference(*_args):
            if self._home_action_dialog is dialog:
                self._home_action_dialog = None

        dialog.bind(on_dismiss=clear_reference)
        self._home_action_dialog = dialog
        dialog.open()
        return dialog, token

    def _set_home_action_result(self, dialog, token, title, message):
        if token != self._home_action_token or self._home_action_dialog is not dialog:
            return
        dialog.title = title
        dialog.text = message

    def _show_home_loss_metrics(self, metrics, error, start_date, end_date, dialog, token):
        if token != self._home_action_token or self._home_action_dialog is not dialog:
            return
        if error:
            self._set_home_action_result(dialog, token, "Métricas de perdas", f"Não foi possível calcular as métricas: {error}")
            return

        metrics = metrics or {}
        loss_count = int(metrics.get("loss_count") or 0)
        total_cost = _format_mzn(metrics.get("total_cost") or 0)
        total_sales = _format_mzn(metrics.get("total_sales") or 0)
        average = _format_mzn(metrics.get("avg_loss_value") or 0)
        percentage = float(metrics.get("loss_percentage") or 0)
        lines = [
            f"Período: {start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}",
            f"Movimentos registados: {loss_count}",
            f"Custo das perdas: {total_cost}",
            f"Vendas no período: {total_sales}",
            f"Incidência das perdas: {percentage:.2f}%",
            f"Média por movimento: {average}",
        ]
        by_type = metrics.get("by_type") or {}
        if by_type:
            lines.append("\nPor tipo:")
            for loss_type, values in list(by_type.items())[:4]:
                lines.append(
                    f"• {str(loss_type or 'OUTRA').replace('_', ' ').title()}: "
                    f"{int(values.get('count') or 0)} movimento(s) · {_format_mzn(values.get('total_cost') or 0)}"
                )
        self._set_home_action_result(dialog, token, "Métricas de perdas", "\n".join(lines))

    def _show_home_pending_approvals(self, pending, error, loading_dialog, token):
        if token != self._home_action_token or self._home_action_dialog is not loading_dialog:
            return
        if error:
            self._set_home_action_result(
                loading_dialog,
                token,
                "Aprovações pendentes",
                f"Não foi possível carregar as aprovações: {error}",
            )
            return
        if not pending:
            self._set_home_action_result(
                loading_dialog,
                token,
                "Aprovações pendentes",
                "Não existem perdas pendentes de aprovação.",
            )
            return

        self._home_action_dialog = None
        try:
            loading_dialog.dismiss()
        except Exception:
            pass

        tokens = getattr(App.get_running_app(), "theme_tokens", {}) or {}
        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(8),
            size_hint_y=None,
            padding=[dp(4), dp(4), dp(4), dp(4)],
        )
        content.bind(minimum_height=content.setter("height"))
        for row in pending[:10]:
            values = list(row) + [""] * 14
            movement_id, _product_id, product, movement_type, qty, unit, cost, _price, reason, _note, _evidence, created_at, user, _role = values[:14]
            card = MDCard(
                orientation="vertical",
                size_hint_y=None,
                height=dp(118),
                spacing=dp(4),
                padding=[dp(10), dp(8), dp(10), dp(8)],
                radius=[dp(10)],
                elevation=0,
                md_bg_color=tokens.get("card_alt", [0.95, 0.96, 0.98, 1]),
            )
            card.add_widget(MDLabel(
                text=f"#{movement_id} · {product or 'Produto'}",
                bold=True,
                font_style="Caption",
                shorten=True,
                shorten_from="right",
                theme_text_color="Custom",
                text_color=tokens.get("text_primary", [0.15, 0.20, 0.30, 1]),
            ))
            card.add_widget(MDLabel(
                text=(
                    f"{movement_type or 'Perda'} · {self._format_banner_quantity(qty, unit or 'un')} · {_format_mzn(cost or 0)}\n"
                    f"Motivo: {reason or 'não informado'} · Por: {user or 'sistema'} · {created_at or 'sem data'}"
                ),
                font_style="Caption",
                theme_text_color="Custom",
                text_color=tokens.get("text_secondary", [0.35, 0.40, 0.50, 1]),
            ))
            actions = MDBoxLayout(size_hint_y=None, height=dp(30), spacing=dp(8))
            approve = MDRaisedButton(
                text="APROVAR",
                md_bg_color=tokens.get("success", [0.2, 0.7, 0.3, 1]),
                on_release=lambda _x, mid=movement_id: self._resolve_home_pending_approval(mid, True),
            )
            reject = MDFlatButton(
                text="REJEITAR",
                theme_text_color="Custom",
                text_color=tokens.get("danger", [0.9, 0.3, 0.3, 1]),
                on_release=lambda _x, mid=movement_id: self._resolve_home_pending_approval(mid, False),
            )
            actions.add_widget(approve)
            actions.add_widget(reject)
            card.add_widget(actions)
            content.add_widget(card)

        scroll = ScrollView(
            do_scroll_x=False,
            bar_width=dp(5),
            size_hint=(1, None),
            height=min(dp(540), Window.height * 0.62),
        )
        scroll.add_widget(content)
        dialog = MDDialog(
            title=f"Aprovações pendentes ({len(pending)})",
            type="custom",
            content_cls=scroll,
            size_hint=(None, None),
            size=(min(dp(760), Window.width * 0.88), min(dp(660), Window.height * 0.80)),
            buttons=[
                MDRaisedButton(
                    text=f"APROVAR TODAS ({len(pending)})",
                    md_bg_color=tokens.get("success", [0.2, 0.7, 0.3, 1]),
                    on_release=lambda *_args: self._confirm_home_approve_all(len(pending)),
                ),
                MDFlatButton(text="FECHAR", on_release=lambda *_args: dialog.dismiss()),
            ],
        )

        def clear_reference(*_args):
            if self._home_action_dialog is dialog:
                self._home_action_dialog = None

        dialog.bind(on_dismiss=clear_reference)
        self._home_action_dialog = dialog
        dialog.open()

    def _confirm_home_approve_all(self, pending_count):
        """Confirma a aprovação em lote no painel inicial do administrador."""
        dialog_ref = {"dialog": None}

        def confirm(_instance):
            confirmation = dialog_ref.get("dialog")
            if confirmation:
                confirmation.dismiss()
            self._approve_all_home_pending_losses()

        dialog = MDDialog(
            title="Aprovar todas as perdas?",
            text=(
                f"Serão aprovadas {pending_count} perdas pendentes. "
                "O stock será atualizado para cada perda aprovada."
            ),
            buttons=[
                MDFlatButton(
                    text="CANCELAR",
                    on_release=lambda _x: dialog_ref["dialog"].dismiss(),
                ),
                MDRaisedButton(text="APROVAR TODAS", on_release=confirm),
            ],
        )
        dialog_ref["dialog"] = dialog
        dialog.open()

    def _approve_all_home_pending_losses(self):
        current = self._home_action_dialog
        if current is not None:
            self._home_action_dialog = None
            try:
                current.dismiss()
            except Exception:
                pass

        dialog, token = self._open_home_action_loader(
            "Aprovar todas as perdas",
            "A processar as perdas pendentes...",
        )
        actor = getattr(App.get_running_app(), "current_user", None) or "admin"

        def worker():
            summary = None
            error = None
            try:
                summary = self.db.approve_all_pending_stock_movements(actor)
                approved_count = int((summary or {}).get("approved_count") or 0)
                if approved_count:
                    try:
                        self.db.log_action(
                            actor,
                            "admin",
                            "APPROVE_ALL_LOSSES",
                            f"Aprovadas {approved_count} perdas pendentes",
                        )
                    except Exception:
                        pass
            except Exception as exc:
                error = str(exc)
            Clock.schedule_once(
                lambda _dt, result=summary, detail=error: self._finish_home_approve_all_losses(
                    result,
                    detail,
                    dialog,
                    token,
                ),
                0,
            )

        Thread(target=worker, daemon=True).start()

    def _finish_home_approve_all_losses(self, summary, error, dialog, token):
        if token != self._home_action_token or self._home_action_dialog is not dialog:
            return
        if error:
            self._set_home_action_result(
                dialog,
                token,
                "Aprovação pendente",
                f"Não foi possível aprovar as perdas: {error}",
            )
            return

        result = summary if isinstance(summary, dict) else {}
        approved_count = int(result.get("approved_count") or 0)
        failed_count = int(result.get("failed_count") or 0)
        if approved_count:
            self._snapshot_loaded_at = 0.0
            self._ensure_snapshot_loaded(force=True)
        if failed_count:
            message = (
                f"{approved_count} perdas foram aprovadas. "
                f"{failed_count} permanecem pendentes porque já não podem ser aplicadas ao stock."
            )
            self._set_home_action_result(dialog, token, "Aprovação parcial", message)
            return
        if approved_count:
            self._set_home_action_result(
                dialog,
                token,
                "Aprovação concluída",
                f"{approved_count} perdas foram aprovadas e o stock foi atualizado.",
            )
            return
        self._set_home_action_result(
            dialog,
            token,
            "Aprovações pendentes",
            "Não existem perdas pendentes para aprovar.",
        )

    def _resolve_home_pending_approval(self, movement_id, approved):
        current = self._home_action_dialog
        if current is not None:
            self._home_action_dialog = None
            try:
                current.dismiss()
            except Exception:
                pass

        action_label = "Aprovar" if approved else "Rejeitar"
        dialog, token = self._open_home_action_loader(
            f"{action_label} perda",
            f"A processar a perda #{movement_id}...",
        )
        actor = getattr(App.get_running_app(), "current_user", None) or "admin"

        def worker():
            success = False
            error = None
            try:
                if approved:
                    success = bool(self.db.approve_stock_movement(movement_id, actor))
                    action_code = "APPROVE_LOSS"
                else:
                    success = bool(self.db.reject_stock_movement(movement_id, rejected_by=actor))
                    action_code = "REJECT_LOSS"
                if success:
                    try:
                        self.db.log_action(actor, "admin", action_code, f"Perda ID {movement_id}")
                    except Exception:
                        pass
            except Exception as exc:
                error = str(exc)
            Clock.schedule_once(
                lambda _dt, ok=success, detail=error: self._finish_home_pending_approval(
                    movement_id,
                    approved,
                    ok,
                    detail,
                    dialog,
                    token,
                ),
                0,
            )

        Thread(target=worker, daemon=True).start()

    def _finish_home_pending_approval(self, movement_id, approved, success, error, dialog, token):
        if token != self._home_action_token or self._home_action_dialog is not dialog:
            return
        action_label = "aprovada" if approved else "rejeitada"
        if success:
            self._snapshot_loaded_at = 0.0
            self._ensure_snapshot_loaded(force=True)
            self._set_home_action_result(dialog, token, "Aprovação concluída", f"A perda #{movement_id} foi {action_label}.")
            return
        message = error or "A operação não foi concluída."
        self._set_home_action_result(dialog, token, "Aprovação pendente", f"Não foi possível tratar a perda #{movement_id}: {message}")

    def open_stock_module(self, *args, product_item=None, product_id=None, query=None):
        if not self.manager:
            return
        screen = self._set_back_target("restock", "admin_home")
        if not screen:
            return
        self.manager.current = "restock"
        resolved_id, resolved_query = self._resolve_action_lookup(
            product_item=product_item,
            product_id=product_id,
            query=query,
        )
        if (resolved_id or resolved_query) and hasattr(screen, "open_restock_for_product"):
            Clock.schedule_once(
                lambda dt: screen.open_restock_for_product(product_id=resolved_id, query=resolved_query),
                0,
            )
            return
        if screen and hasattr(screen, "prepare_open_from_admin"):
            Clock.schedule_once(lambda dt: screen.prepare_open_from_admin("IN"), 0)

    def _quick_restock_payload(self, product_item=None, product_id=None, query=None):
        item = product_item or {}
        resolved_id, resolved_query = self._resolve_action_lookup(
            product_item=item,
            product_id=product_id,
            query=query,
        )
        name = self._alert_item_name(item, fallback=resolved_query or "Produto")
        stock_text = self._format_banner_quantity(item.get("stock"), self._stock_unit(item))
        return {
            "id": resolved_id,
            "name": name,
            "stock_text": stock_text,
            "is_weight": bool(item.get("is_weight")),
        }

    def _reset_quick_restock_refs(self, *args):
        self._quick_restock_dialog = None
        self._quick_restock_product = None
        self._quick_restock_fields = {}
        self._quick_restock_submit_btn = None
        self._quick_restock_busy = False

    def _dismiss_quick_restock_dialog(self, *args):
        dialog = self._quick_restock_dialog
        self._reset_quick_restock_refs()
        if dialog is not None:
            try:
                dialog.dismiss()
            except Exception:
                pass

    @staticmethod
    def _parse_restock_expiry(value):
        text = str(value or "").strip()
        if not text:
            return None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(text[:19], fmt).strftime("%Y-%m-%d")
            except Exception:
                continue
        raise ValueError("Data de validade invalida. Use DD/MM/AAAA.")

    def _show_quick_restock_error(self, message):
        error = MDDialog(
            title="Reposicao de Stock",
            text=str(message or "Falha ao registar reposicao."),
            buttons=[MDFlatButton(text="FECHAR", on_release=lambda _btn: error.dismiss())],
        )
        error.open()

    def _set_quick_restock_busy(self, busy):
        self._quick_restock_busy = bool(busy)
        button = self._quick_restock_submit_btn
        if button is not None:
            button.disabled = bool(busy)
            button.text = "A REGISTAR..." if busy else "REGISTAR ENTRADA"

    def _submit_quick_restock(self, *args):
        if self._quick_restock_busy:
            return
        product = self._quick_restock_product or {}
        product_id = product.get("id")
        if product_id in (None, ""):
            self._show_quick_restock_error("Produto sem ID valido para reposicao.")
            return

        fields = self._quick_restock_fields or {}
        qty_text = str(fields.get("qty").text if fields.get("qty") else "").strip()
        cost_text = str(fields.get("cost").text if fields.get("cost") else "").strip()
        try:
            qty = float(qty_text)
        except Exception:
            self._show_quick_restock_error("Quantidade invalida.")
            return
        try:
            unit_cost = float(cost_text)
        except Exception:
            self._show_quick_restock_error("Custo unitario invalido.")
            return
        if qty <= 0:
            self._show_quick_restock_error("Quantidade deve ser maior que zero.")
            return
        if not product.get("is_weight") and not float(qty).is_integer():
            self._show_quick_restock_error("Para produtos por unidade, a quantidade deve ser inteira.")
            return
        if unit_cost <= 0:
            self._show_quick_restock_error("Custo unitario deve ser maior que zero.")
            return
        try:
            expiry_iso = self._parse_restock_expiry(fields.get("expiry").text if fields.get("expiry") else "")
        except ValueError as exc:
            self._show_quick_restock_error(str(exc))
            return

        app = App.get_running_app()
        user = getattr(app, "current_user", None) if app else None
        role = getattr(app, "current_role", "admin") if app else "admin"
        note = str(fields.get("note").text if fields.get("note") else "").strip()
        supplier = str(fields.get("supplier").text if fields.get("supplier") else "").strip() or None
        invoice = str(fields.get("invoice").text if fields.get("invoice") else "").strip() or None

        self._set_quick_restock_busy(True)

        def worker():
            movement_id = None
            error = None
            try:
                movement_id = self.db.restock_product(
                    product_id,
                    qty,
                    unit_cost,
                    expiry_date=expiry_iso,
                    reason="Reposicao de stock",
                    note=note,
                    created_by=user,
                    created_role=role,
                    supplier_name=supplier,
                    invoice_number=invoice,
                )
            except Exception as exc:
                error = str(exc)
            Clock.schedule_once(
                lambda dt, mid=movement_id, err=error: self._finish_quick_restock(mid, err),
                0,
            )

        Thread(target=worker, daemon=True).start()

    def _finish_quick_restock(self, movement_id, error=None):
        self._set_quick_restock_busy(False)
        if error or not movement_id:
            self._show_quick_restock_error(error or "Falha ao registar entrada de stock.")
            return
        self._dismiss_quick_restock_dialog()
        self.status_text = "Reposicao registada. A atualizar indicadores..."
        self._ensure_snapshot_loaded(force=True)

    def open_restock_modal(self, *args, product_item=None, product_id=None, query=None):
        if not self.manager:
            return
        product = self._quick_restock_payload(
            product_item=product_item,
            product_id=product_id,
            query=query,
        )
        if product.get("id") in (None, ""):
            self._show_quick_restock_error("Produto sem ID valido para reposicao.")
            return

        self._dismiss_quick_restock_dialog()
        self._quick_restock_product = product

        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(8),
            size_hint_y=None,
            height=dp(292),
        )
        content.add_widget(
            MDLabel(
                text=f"Produto: {product.get('name') or '--'}",
                theme_text_color="Primary",
                size_hint_y=None,
                height=dp(24),
                shorten=True,
                shorten_from="right",
            )
        )
        content.add_widget(
            MDLabel(
                text=f"Stock atual: {product.get('stock_text') or '--'}",
                theme_text_color="Secondary",
                size_hint_y=None,
                height=dp(22),
            )
        )

        qty_field = MDTextField(hint_text="Quantidade *", mode="rectangle", input_filter="float")
        cost_field = MDTextField(hint_text="Custo unitario *", mode="rectangle", input_filter="float")
        expiry_field = MDTextField(hint_text="Validade do lote DD/MM/AAAA", mode="rectangle")
        note_field = MDTextField(hint_text="Observacao", mode="rectangle")
        supplier_field = MDTextField(hint_text="Fornecedor (opcional)", mode="rectangle")
        invoice_field = MDTextField(hint_text="N. Fatura (opcional)", mode="rectangle")

        first_row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(52), spacing=dp(8))
        first_row.add_widget(qty_field)
        first_row.add_widget(cost_field)
        content.add_widget(first_row)

        content.add_widget(expiry_field)

        supplier_row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(52), spacing=dp(8))
        supplier_row.add_widget(supplier_field)
        supplier_row.add_widget(invoice_field)
        content.add_widget(supplier_row)
        content.add_widget(note_field)

        self._quick_restock_fields = {
            "qty": qty_field,
            "cost": cost_field,
            "expiry": expiry_field,
            "note": note_field,
            "supplier": supplier_field,
            "invoice": invoice_field,
        }
        submit_btn = MDRaisedButton(text="REGISTAR ENTRADA", on_release=self._submit_quick_restock)
        self._quick_restock_submit_btn = submit_btn
        dialog = MDDialog(
            title="Reposicao de Stock",
            type="custom",
            content_cls=content,
            size_hint=(0.72, None),
            height=dp(430),
            buttons=[
                MDFlatButton(text="FECHAR", on_release=lambda _btn: self._dismiss_quick_restock_dialog()),
                submit_btn,
            ],
        )
        self._quick_restock_dialog = dialog
        dialog.bind(on_dismiss=self._reset_quick_restock_refs)
        dialog.open()
        Clock.schedule_once(
            lambda dt: setattr(qty_field, "focus", True),
            0,
        )

    def open_losses_module(self, *args, product_item=None, product_id=None, query=None, loss_type_label=None, loss_type_code=None):
        if not self.manager:
            return
        screen = self._set_back_target("losses", "admin_home")
        if not screen:
            return
        self.manager.current = "losses"
        resolved_id, resolved_query = self._resolve_action_lookup(
            product_item=product_item,
            product_id=product_id,
            query=query,
        )
        if (resolved_id or resolved_query) and hasattr(screen, "open_loss_for_product"):
            Clock.schedule_once(
                lambda dt: screen.open_loss_for_product(
                    product_id=resolved_id,
                    query=resolved_query,
                    loss_type_label=loss_type_label,
                    loss_type_code=loss_type_code,
                ),
                0,
            )
            return
        if screen and hasattr(screen, "prepare_open_from_admin"):
            Clock.schedule_once(lambda dt: screen.prepare_open_from_admin(), 0)

    def open_users_module(self, *args):
        if not self.manager:
            return
        screen = self._set_back_target("settings", "admin_home")
        if not screen:
            return
        self.manager.current = "settings"
        if screen and hasattr(screen, "add_user"):
            Clock.schedule_once(lambda dt: screen.add_user(), 0)

    def open_user_logs(self, *args):
        if self._logs_dialog is None:
            self._logs_dialog = AdminLogsDialog()
        self._logs_dialog.show()

    def change_screen_size(self, *args):
        from utils.screens.settings import ScreenSizeDialog

        ScreenSizeDialog(App.get_running_app()).show()

    def open_ai_menu(self, caller=None):
        if caller is None and hasattr(self, "ids") and "ai_button" in self.ids:
            caller = self.ids.ai_button
        self._get_intelligence().open_alerts(caller=caller)

    def show_ai_recommendations(self, caller=None):
        if caller is None and hasattr(self, "ids") and "recommendations_button" in self.ids:
            caller = self.ids.recommendations_button
        self._get_intelligence().open_recommendations(caller=caller)

    def go_to_settings(self, *args):
        if not self.manager:
            return
        screen = self._set_back_target("settings", "admin_home")
        if not screen:
            return
        self.manager.current = "settings"

    def logout(self, *args):
        app = App.get_running_app()
        setter = getattr(self.db, "set_active_user", None)
        if callable(setter):
            try:
                setter(None, None)
            except Exception:
                pass
        if app:
            username = getattr(app, "current_user", None)
            app.current_user = None
            app.current_role = None
            app._ai_banners_shown = False
            app._ai_notifications_seen_key = None
            app._ai_banners_last_key = None
        if self.manager:
            self.manager.current = "login"
