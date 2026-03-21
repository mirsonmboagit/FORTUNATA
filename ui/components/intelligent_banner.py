"""Adaptador dos alertas proativos para o renderer original de banners."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import time
from typing import Any

from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.floatlayout import FloatLayout
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.menu import MDDropdownMenu

from utils.ai_popups import build_auto_banner_data, clear_banner_container, render_auto_banners


_PRIORITY = {"critico": 0, "atencao": 1, "info": 2}


def _priority_of(alert_type: str) -> int:
    return _PRIORITY.get(str(alert_type or "").lower(), 99)


def _format_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M")
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return text


def _severity_style(alert_type: str) -> tuple[str, tuple[float, float, float, float]]:
    alert_type = str(alert_type or "info").lower()
    if alert_type == "critico":
        return "alert-circle", (0.98, 0.84, 0.86, 0.98)
    if alert_type == "atencao":
        return "alert", (0.99, 0.93, 0.78, 0.98)
    return "information-outline", (0.84, 0.91, 0.99, 0.98)


def _title_for(category: str, alert_type: str) -> str:
    category = str(category or "monitorizacao").lower()
    alert_type = str(alert_type or "info").lower()
    prefix = {
        "critico": "IA Critica",
        "atencao": "IA em Atencao",
        "info": "IA Monitor",
    }.get(alert_type, "IA Monitor")
    base = {
        "vendas": "Vendas",
        "stock": "Stock",
        "produtividade": "Produtividade",
    }.get(category, "Operacao")
    return f"{prefix} - {base}"


def _group_alerts(alerts: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for alert in alerts:
        if not isinstance(alert, dict):
            continue
        key = str(alert.get("categoria") or "monitorizacao").lower()
        grouped[key].append(alert)

    groups = list(grouped.values())
    groups.sort(
        key=lambda items: (
            min(_priority_of(item.get("tipo")) for item in items),
            str(items[0].get("categoria") or ""),
        )
    )
    return groups


def _build_details_sections(items: list[dict[str, Any]]) -> list[tuple[str, list[str]]]:
    details_lines = []
    timeline_lines = []

    for item in items:
        mensagem = str(item.get("mensagem") or "").strip()
        detalhes = str(item.get("detalhes") or "").strip()
        timestamp = _format_timestamp(item.get("timestamp"))
        if detalhes:
            details_lines.append(f"{mensagem}: {detalhes}")
        elif mensagem:
            details_lines.append(mensagem)
        if mensagem and timestamp:
            timeline_lines.append(f"{timestamp} - {mensagem}")

    sections = []
    if details_lines:
        sections.append(("Analise Inteligente", details_lines[:12]))
    if timeline_lines:
        sections.append(("Registos", timeline_lines[:12]))
    return sections


def _alerts_to_banner_data(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    banner_data = []
    for items in _group_alerts(alerts):
        if not items:
            continue
        items = sorted(items, key=lambda item: _priority_of(item.get("tipo")))
        top = items[0]
        icon, bg_color = _severity_style(str(top.get("tipo")))
        banner_data.append(
            {
                "kind": str(top.get("categoria") or "monitorizacao").lower(),
                "variant": "danger" if str(top.get("tipo") or "").lower() == "critico" else "warning" if str(top.get("tipo") or "").lower() == "atencao" else "info",
                "icon": icon,
                "bg_color": bg_color,
                "title": _title_for(top.get("categoria"), top.get("tipo")),
                "messages": [str(item.get("mensagem") or "") for item in items[:5]],
                "all_messages": [str(item.get("mensagem") or "") for item in items],
                "count": len(items),
                "details_sections": _build_details_sections(items),
                "urgency": _priority_of(top.get("tipo")),
            }
        )
    return banner_data


def _insights_have_issues(insights: dict[str, Any] | None) -> bool:
    insights = insights or {}
    expiry_levels = insights.get("expiry_levels") or {}
    return bool(
        insights.get("low_stock")
        or expiry_levels.get("vencido")
        or expiry_levels.get("critico")
        or expiry_levels.get("alto")
        or expiry_levels.get("medio")
        or expiry_levels.get("leve")
        or insights.get("expiring_7")
        or insights.get("expiring_15")
    )


def _insights_to_banner_data(
    insights: dict[str, Any] | None,
    include_positive: bool,
) -> list[dict[str, Any]]:
    payload = insights or {}
    if not payload:
        return []
    if not include_positive and not _insights_have_issues(payload):
        return []
    return build_auto_banner_data(payload)


def _banner_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    urgency = item.get("urgency")
    if urgency is None:
        urgency = 999
    return (
        urgency,
        str(item.get("kind") or ""),
        str(item.get("title") or ""),
    )


def _banner_signature(items: list[dict[str, Any]]) -> tuple[Any, ...]:
    return tuple(
        (
            str(item.get("kind") or ""),
            str(item.get("title") or ""),
            tuple(str(message or "") for message in item.get("messages", [])[:5]),
            int(item.get("count") or 0),
        )
        for item in items
    )


class IntelligentBannerCenter(FloatLayout):
    """Usa o renderer original de banners para os novos alertas proativos."""

    def __init__(
        self,
        history_title: str = "Historico de alertas",
        columns: int = 1,
        auto_batch_size: int | None = None,
        auto_stagger_seconds: float = 0.2,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.history_title = history_title
        self.columns = max(1, int(columns or 1))
        self.auto_batch_size = max(1, int(auto_batch_size)) if auto_batch_size else None
        self.auto_stagger_seconds = max(0.0, float(auto_stagger_seconds or 0.0))
        self.history_items: list[dict[str, Any]] = []
        self.current_insights: dict[str, Any] = {}
        self._last_signature: tuple[Any, ...] = ()
        self._last_positive_signature: tuple[Any, ...] = ()
        self._last_positive_at = 0.0
        self._history_picker_dialog: MDDialog | None = None
        self._history_picker_menu: MDDropdownMenu | None = None
        self._history_picker_button: MDRaisedButton | None = None
        self._history_picker_selected = ""
        self._history_picker_options: dict[str, list[dict[str, Any]]] = {}
        self._manual_view_active = False

    def set_history(self, history_items: list[dict[str, Any]]) -> None:
        self.history_items = list(history_items)

    def _has_visible_banners(self) -> bool:
        return any(widget and widget.parent for widget in list(getattr(self, "_ai_banner_widgets", []) or []))

    def _render_inline_banners(
        self,
        banner_data: list[dict[str, Any]],
        *,
        auto_dismiss_seconds: float | None,
        show_timer: bool,
    ) -> None:
        if not banner_data:
            self.clear_visible()
            return
        render_auto_banners(
            self,
            banner_data,
            insights=self.current_insights or None,
            auto_dismiss_seconds=auto_dismiss_seconds,
            show_timer=show_timer,
            stagger_seconds=self.auto_stagger_seconds,
            columns=self.columns,
            batch_size=self.auto_batch_size,
        )

    def show_alerts(
        self,
        alerts: list[dict[str, Any]],
        insights: dict[str, Any] | None = None,
        auto_dismiss_seconds: float = 7.0,
    ) -> None:
        if insights is not None:
            self.current_insights = dict(insights)

        banner_data = _insights_to_banner_data(
            self.current_insights,
            include_positive=not bool(alerts),
        )
        banner_data.extend(_alerts_to_banner_data(alerts))
        banner_data.sort(key=_banner_sort_key)
        if not banner_data:
            return

        signature = _banner_signature(banner_data)
        if self._manual_view_active and self._has_visible_banners():
            self._last_signature = signature
            if insights is not None:
                self.current_insights = dict(insights)
            return
        if signature == self._last_signature:
            return

        only_positive = (
            len(banner_data) == 1
            and str(banner_data[0].get("kind") or "").lower() == "positive"
        )
        now = time.time()
        if only_positive and signature == self._last_positive_signature and (now - self._last_positive_at) < 180:
            return

        self._last_signature = signature
        if only_positive:
            self._last_positive_signature = signature
            self._last_positive_at = now

        self._render_inline_banners(
            banner_data,
            auto_dismiss_seconds=auto_dismiss_seconds,
            show_timer=True,
        )

    def clear_visible(self, reset_memory: bool = False) -> None:
        clear_banner_container(self)
        self._manual_view_active = False
        if reset_memory:
            self._last_signature = ()
            self._last_positive_signature = ()
            self._last_positive_at = 0.0

    def _build_history_banner_data(
        self,
        history_items: list[dict[str, Any]] | None = None,
        insights: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if history_items is not None:
            self.history_items = list(history_items)
        if insights is not None:
            self.current_insights = dict(insights)
        banner_data = _insights_to_banner_data(self.current_insights, include_positive=True)
        banner_data.extend(_alerts_to_banner_data(self.history_items[:12]))
        banner_data.sort(key=_banner_sort_key)
        return banner_data

    def _dismiss_history_picker(self, *_args: Any) -> None:
        menu = self._history_picker_menu
        self._history_picker_menu = None
        if menu is not None:
            try:
                menu.dismiss()
            except Exception:
                pass

        dialog = self._history_picker_dialog
        self._history_picker_dialog = None
        self._history_picker_button = None
        self._history_picker_selected = ""
        self._history_picker_options = {}
        if dialog is not None:
            try:
                dialog.dismiss()
            except Exception:
                pass

    def _reset_history_picker_refs(self, *_args: Any) -> None:
        self._history_picker_dialog = None
        self._history_picker_menu = None
        self._history_picker_button = None
        self._history_picker_selected = ""
        self._history_picker_options = {}

    def _dismiss_history_picker_menu(self, *_args: Any) -> None:
        menu = self._history_picker_menu
        self._history_picker_menu = None
        if menu is not None:
            try:
                menu.dismiss()
            except Exception:
                pass

    def _select_history_picker_option(self, label: str) -> None:
        self._history_picker_selected = str(label or "").strip()
        button = self._history_picker_button
        if button is not None:
            button.text = self._history_picker_selected or "Selecionar banner"
        self._dismiss_history_picker_menu()

    def _show_selected_history_banner(self, *_args: Any) -> None:
        selected = self._history_picker_selected
        banner_data = list(self._history_picker_options.get(selected) or [])
        self._dismiss_history_picker()
        if not banner_data:
            self.clear_visible()
            return
        render_auto_banners(
            self,
            banner_data,
            insights=self.current_insights or None,
            auto_dismiss_seconds=None,
            show_timer=False,
            stagger_seconds=0.08,
            columns=self.columns,
        )

    def _open_history_picker(self, banner_data: list[dict[str, Any]]) -> None:
        self._dismiss_history_picker()

        dialog_width = min(max(dp(320), Window.width * 0.40), dp(420))
        has_choices = bool(banner_data)
        options_map: dict[str, list[dict[str, Any]]] = {}
        option_labels: list[str] = []

        for index, item in enumerate(banner_data, start=1):
            title = str(item.get("title") or "Banner inteligente").strip()
            count = int(item.get("count") or len(item.get("messages") or []))
            label = f"{index}. {title}"
            if count > 0:
                label += f" ({count})"
            options_map[label] = [item]
            option_labels.append(label)

        if len(banner_data) > 1:
            option_labels.append("Todos os banners")
            options_map["Todos os banners"] = list(banner_data)

        if not option_labels:
            option_labels = ["Nenhum banner disponivel"]
            options_map["Nenhum banner disponivel"] = []

        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(10),
            padding=[dp(8), dp(6), dp(8), dp(2)],
            size_hint_y=None,
            height=dp(118),
        )

        helper_label = MDLabel(
            text=(
                "Escolha qual banner deseja visualizar."
                if has_choices
                else "Nao ha banners registados no momento."
            ),
            font_style="Caption",
            size_hint_y=None,
            height=dp(38),
        )
        helper_label.text_size = (dialog_width - dp(96), None)

        picker_button = MDRaisedButton(
            text=option_labels[0],
            size_hint_y=None,
            height=dp(44),
        )
        picker_button.disabled = not has_choices

        content.add_widget(helper_label)
        content.add_widget(picker_button)

        menu_items = [
            {
                "viewclass": "OneLineListItem",
                "text": label,
                "height": dp(42),
                "on_release": lambda selected=label: self._select_history_picker_option(selected),
            }
            for label in option_labels
        ]
        menu = MDDropdownMenu(
            caller=picker_button,
            items=menu_items,
            width_mult=4,
            max_height=dp(280),
            position="bottom",
        )
        picker_button.bind(on_release=lambda *_: menu.open())

        dialog = MDDialog(
            title="Selecionar banner",
            type="custom",
            content_cls=content,
            size_hint=(None, None),
            size=(dialog_width, dp(250)),
            auto_dismiss=True,
            buttons=[
                MDFlatButton(
                    text="CANCELAR",
                    on_release=self._dismiss_history_picker,
                ),
                MDRaisedButton(
                    text="VER",
                    on_release=self._show_selected_history_banner,
                    disabled=not has_choices,
                ),
            ],
        )
        dialog.bind(on_dismiss=self._reset_history_picker_refs)

        self._history_picker_dialog = dialog
        self._history_picker_menu = menu
        self._history_picker_button = picker_button
        self._history_picker_selected = option_labels[0] if has_choices else ""
        self._history_picker_options = options_map
        dialog.open()

    def open_history(
        self,
        history_items: list[dict[str, Any]] | None = None,
        insights: dict[str, Any] | None = None,
    ) -> None:
        banner_data = self._build_history_banner_data(history_items=history_items, insights=insights)
        self._dismiss_history_picker()
        self._manual_view_active = True
        self._render_inline_banners(
            banner_data,
            auto_dismiss_seconds=None,
            show_timer=False,
        )
