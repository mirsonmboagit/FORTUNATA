"""Execucao periodica segura do motor de inteligencia fora da thread principal."""

from __future__ import annotations

from threading import Lock, Thread
from typing import Any, Callable

from kivy.clock import Clock

from .alert_manager import AlertManager
from .data_collector import IntelligenceDataCollector
from .engine import executar_analise
from utils.ai.ai_insights import build_proactive_ai_recommendations


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
        self._ai_busy_lock = Lock()
        self._cycle_lock = Lock()
        self._cycle_id = 0
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
        self._invalidate_pending_cycles()

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
        cycle_id = self._begin_cycle()
        payload: dict[str, Any] | None = None
        snapshot: dict[str, Any] | None = None
        try:
            snapshot = self.collector.collect_snapshot()
            alerts = executar_analise(snapshot)
            payload = self.alert_manager.process(alerts)
            payload["snapshot"] = snapshot
            banner_insights = dict(snapshot.get("banner_insights", {}) or {})
            # A leitura local nunca espera pela resposta da IA externa.
            banner_insights["recommendations_source"] = "local"
            payload["banner_insights"] = banner_insights
        except Exception as exc:
            payload = self.alert_manager.snapshot()
            payload["error"] = str(exc)
        finally:
            self._busy_lock.release()

        if callback and payload is not None:
            self._dispatch_payload(callback, payload)

        if callback and snapshot is not None and payload is not None:
            self._request_ai_enrichment(cycle_id, callback, payload, snapshot)

    def _request_ai_enrichment(
        self,
        cycle_id: int,
        callback: PayloadCallback,
        payload: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> None:
        """Carrega a parte externa sem bloquear alertas, contadores ou a UI."""
        if not self._ai_busy_lock.acquire(blocking=False):
            return
        Thread(
            target=self._run_ai_enrichment,
            args=(cycle_id, callback, dict(payload), snapshot),
            daemon=True,
        ).start()

    def _run_ai_enrichment(
        self,
        cycle_id: int,
        callback: PayloadCallback,
        payload: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> None:
        try:
            ai_recommendations = build_proactive_ai_recommendations(snapshot)
            if not ai_recommendations or not self._is_current_cycle(cycle_id):
                return

            banner_insights = dict(payload.get("banner_insights", {}) or {})
            banner_insights["recommendations_ai"] = ai_recommendations
            banner_insights["recommendations_source"] = "ai"
            enriched_payload = dict(payload)
            enriched_payload["banner_insights"] = banner_insights
            self._dispatch_payload(callback, enriched_payload)
        finally:
            self._ai_busy_lock.release()

    @staticmethod
    def _dispatch_payload(callback: PayloadCallback, payload: dict[str, Any]) -> None:
        Clock.schedule_once(lambda _dt, data=payload: callback(data), 0)

    def _begin_cycle(self) -> int:
        with self._cycle_lock:
            self._cycle_id += 1
            return self._cycle_id

    def _invalidate_pending_cycles(self) -> None:
        with self._cycle_lock:
            self._cycle_id += 1

    def _is_current_cycle(self, cycle_id: int) -> bool:
        with self._cycle_lock:
            return self._cycle_id == cycle_id
