"""Execucao periodica segura do motor de inteligencia fora da thread principal."""

from __future__ import annotations

from threading import Lock, Thread
from typing import Any, Callable

from kivy.clock import Clock

from .alert_manager import AlertManager
from .data_collector import IntelligenceDataCollector
from .engine import executar_analise


PayloadCallback = Callable[[dict[str, Any]], None]
DEFAULT_INTELLIGENCE_INTERVAL_SECONDS = 15 * 60.0


class IntelligenceMonitor:
    """Executa coleta e analise em worker thread e devolve payloads via Clock."""

    def __init__(
        self,
        db: Any | None,
        alert_manager: AlertManager | None = None,
        interval_seconds: float = DEFAULT_INTELLIGENCE_INTERVAL_SECONDS,
    ) -> None:
        self.collector = IntelligenceDataCollector(db=db, default_ttl=max(10.0, interval_seconds * 0.6))
        self.alert_manager = alert_manager or AlertManager()
        self.interval_seconds = max(10.0, float(interval_seconds))
        self._event = None
        self._busy_lock = Lock()
        self._callback: PayloadCallback | None = None

    def start(self, callback: PayloadCallback) -> None:
        self._callback = callback
        if self._event:
            self._event.cancel()
        self._event = Clock.schedule_interval(self._tick, self.interval_seconds)
        self.request_refresh()

    def stop(self) -> None:
        if self._event:
            self._event.cancel()
            self._event = None

    def request_refresh(self) -> None:
        if not self._callback:
            return
        if not self._busy_lock.acquire(blocking=False):
            return
        Thread(target=self._run_cycle, daemon=True).start()

    def _tick(self, _dt: float) -> None:
        self.request_refresh()

    def _run_cycle(self) -> None:
        callback = self._callback
        try:
            snapshot = self.collector.collect_snapshot()
            alerts = executar_analise(snapshot)
            payload = self.alert_manager.process(alerts)
            payload["snapshot"] = snapshot
            payload["banner_insights"] = snapshot.get("banner_insights", {})
        except Exception as exc:
            payload = self.alert_manager.snapshot()
            payload["error"] = str(exc)
        finally:
            self._busy_lock.release()

        if callback:
            Clock.schedule_once(lambda _dt, data=payload: callback(data), 0)
