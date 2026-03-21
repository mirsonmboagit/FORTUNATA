"""Ponte entre o monitor proativo e as telas Kivy."""

from __future__ import annotations

from typing import Any, Callable

from kivy.app import App

from .alert_manager import AlertManager
from .monitor import IntelligenceMonitor
from ui.components.intelligent_banner import IntelligentBannerCenter


class SharedIntelligenceHub:
    """Servico compartilhado por todas as telas para evitar trabalho duplicado."""

    def __init__(self, db: Any, interval_seconds: float = 30.0) -> None:
        self.alert_manager = AlertManager()
        self.monitor = IntelligenceMonitor(
            db=db,
            alert_manager=self.alert_manager,
            interval_seconds=interval_seconds,
        )
        self.listeners: set[Callable[[dict[str, Any]], None]] = set()
        self.enabled = True
        self._last_payload = self.alert_manager.snapshot()

    def subscribe(self, listener: Callable[[dict[str, Any]], None]) -> None:
        self.listeners.add(listener)
        listener(dict(self._last_payload))
        if self.enabled:
            self.monitor.start(self._handle_payload)

    def unsubscribe(self, listener: Callable[[dict[str, Any]], None]) -> None:
        self.listeners.discard(listener)
        if not self.listeners:
            self.monitor.stop()

    def request_refresh(self) -> None:
        if self.enabled:
            self.monitor.request_refresh()

    def mark_all_seen(self) -> None:
        self.alert_manager.mark_all_seen()
        self._last_payload = self.alert_manager.snapshot()
        self._broadcast(self._last_payload)

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)
        if not self.enabled:
            self.monitor.stop()
            self.alert_manager.mark_all_seen()
            self.alert_manager.clear_active()
            self._last_payload = self.alert_manager.snapshot()
            self._broadcast(self._last_payload)
            return
        if self.listeners:
            self.monitor.start(self._handle_payload)

    def _handle_payload(self, payload: dict[str, Any]) -> None:
        self._last_payload = payload
        self._broadcast(payload)

    def _broadcast(self, payload: dict[str, Any]) -> None:
        for listener in list(self.listeners):
            listener(dict(payload))


def get_shared_intelligence_hub(db: Any, interval_seconds: float = 30.0) -> SharedIntelligenceHub:
    app = App.get_running_app()
    if app is None:
        raise RuntimeError("Nenhuma instancia de App ativa para monitorizacao inteligente.")
    hub = getattr(app, "_shared_intelligence_hub", None)
    if hub is None:
        hub = SharedIntelligenceHub(db=db, interval_seconds=interval_seconds)
        setattr(app, "_shared_intelligence_hub", hub)
    return hub


class ProactiveIntelligenceController:
    """Controlador por tela que reutiliza um hub compartilhado."""

    def __init__(
        self,
        screen: Any,
        db: Any,
        history_title: str,
        interval_seconds: float = 30.0,
        banner_columns: int = 1,
        auto_batch_size: int | None = None,
        auto_stagger_seconds: float = 0.2,
        auto_present_enabled: bool = False,
    ) -> None:
        self.screen = screen
        self.history_title = history_title
        self.banner_columns = max(1, int(banner_columns or 1))
        self.auto_batch_size = max(1, int(auto_batch_size)) if auto_batch_size else None
        self.auto_stagger_seconds = max(0.0, float(auto_stagger_seconds or 0.0))
        self.auto_present_enabled = bool(auto_present_enabled)
        self.hub = get_shared_intelligence_hub(db=db, interval_seconds=interval_seconds)
        self._listener = self._apply_payload
        self._banner_center: IntelligentBannerCenter | None = None
        self._last_payload: dict[str, Any] = {}
        self._auto_presented_once = False

    def start(self) -> None:
        if not self._is_enabled():
            self.clear()
            self._update_badge(0)
            return
        self._ensure_banner_center()
        self.hub.subscribe(self._listener)
        self.hub.request_refresh()

    def stop(self) -> None:
        self.hub.unsubscribe(self._listener)
        self.clear()

    def refresh(self) -> None:
        if self._is_enabled():
            self.hub.request_refresh()

    def open_history(self) -> None:
        center = self._ensure_banner_center()
        center.open_history(
            self.hub.alert_manager.snapshot().get("history", []),
            insights=self._last_payload.get("banner_insights", {}),
        )
        self.hub.mark_all_seen()

    def set_enabled(self, enabled: bool) -> None:
        self.hub.set_enabled(enabled)
        if not enabled:
            self._auto_presented_once = False
            self.clear(reset_memory=True)
            self._update_badge(0)
        else:
            self.start()

    def clear(self, reset_memory: bool = False) -> None:
        if self._banner_center:
            self._banner_center.clear_visible(reset_memory=reset_memory)

    def _is_enabled(self) -> bool:
        app = App.get_running_app()
        return bool(getattr(app, "smart_monitor_enabled", True)) if app else True

    def _apply_payload(self, payload: dict[str, Any]) -> None:
        self._last_payload = dict(payload)
        display_alerts = payload.get("display_alerts", []) or []
        banner_insights = payload.get("banner_insights", {}) or {}
        center = self._ensure_banner_center()
        center.set_history(payload.get("history", []))
        has_auto_content = self.auto_present_enabled and bool(display_alerts or banner_insights)
        should_auto_show = False
        if has_auto_content:
            if not self._auto_presented_once:
                should_auto_show = True
            elif display_alerts:
                should_auto_show = True
        if should_auto_show:
            center.show_alerts(
                display_alerts,
                insights=banner_insights,
            )
            self._auto_presented_once = True
        self._update_badge(int(payload.get("unread_count", 0) or 0))

    def _update_badge(self, count: int) -> None:
        if hasattr(self.screen, "update_notification_badge"):
            self.screen.update_notification_badge(count)

    def _ensure_banner_center(self) -> IntelligentBannerCenter:
        if self._banner_center:
            return self._banner_center
        container = self.screen.ids.get("ai_banner_container")
        if container is None:
            raise ValueError("Container ai_banner_container nao encontrado na tela.")
        self._banner_center = IntelligentBannerCenter(
            history_title=self.history_title,
            columns=self.banner_columns,
            auto_batch_size=self.auto_batch_size,
            auto_stagger_seconds=self.auto_stagger_seconds,
        )
        container.add_widget(self._banner_center)
        return self._banner_center
