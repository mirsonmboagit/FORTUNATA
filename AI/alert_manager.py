"""Gerenciamento de alertas proativos e historico em memoria."""

from __future__ import annotations

from collections import deque
from datetime import datetime
from threading import Lock
from typing import Any


class AlertManager:
    """Controla deduplicacao, prioridade, historico e frequencia de banners."""

    PRIORITY = {"critico": 0, "atencao": 1, "info": 2}

    def __init__(
        self,
        cooldown_seconds: int = 300,
        simultaneous_limit: int = 3,
        history_limit: int = 200,
    ) -> None:
        self.cooldown_seconds = max(30, int(cooldown_seconds))
        self.simultaneous_limit = max(1, int(simultaneous_limit))
        self.history_limit = max(50, int(history_limit))
        self._history: deque[dict[str, Any]] = deque(maxlen=self.history_limit)
        self._last_emitted: dict[str, datetime] = {}
        self._active_alerts: list[dict[str, Any]] = []
        self._unread_count = 0
        self._lock = Lock()

    def process(self, alerts: list[dict[str, Any]]) -> dict[str, Any]:
        """Processa uma nova leva de alertas e devolve payload pronto para UI."""
        now = datetime.now()
        normalized = self._deduplicate(alerts)
        prioritized = sorted(
            normalized,
            key=lambda item: (
                self.PRIORITY.get(item.get("tipo"), 99),
                item.get("categoria", ""),
                item.get("mensagem", ""),
            ),
        )
        active = prioritized[: self.simultaneous_limit]

        display_alerts: list[dict[str, Any]] = []
        with self._lock:
            self._active_alerts = active
            for alert in active:
                fingerprint = self._fingerprint(alert)
                last_sent = self._last_emitted.get(fingerprint)
                if last_sent and (now - last_sent).total_seconds() < self.cooldown_seconds:
                    continue
                self._last_emitted[fingerprint] = now
                display_alerts.append(alert)
                self._history.appendleft(dict(alert))
                self._unread_count += 1

            unread = self._unread_count
            history = list(self._history)
            active_snapshot = list(self._active_alerts)

        return {
            "display_alerts": display_alerts,
            "active_alerts": active_snapshot,
            "history": history,
            "unread_count": unread,
        }

    def snapshot(self) -> dict[str, Any]:
        """Retorna estado atual sem emitir novos banners."""
        with self._lock:
            return {
                "display_alerts": [],
                "active_alerts": list(self._active_alerts),
                "history": list(self._history),
                "unread_count": self._unread_count,
            }

    def mark_all_seen(self) -> None:
        """Zera o contador de itens nao vistos."""
        with self._lock:
            self._unread_count = 0

    def clear_active(self) -> None:
        """Limpa alertas ativos sem apagar o historico."""
        with self._lock:
            self._active_alerts = []

    def _deduplicate(self, alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique: dict[str, dict[str, Any]] = {}
        for alert in alerts:
            if not isinstance(alert, dict) or not alert.get("mensagem"):
                continue
            fingerprint = self._fingerprint(alert)
            previous = unique.get(fingerprint)
            if previous is None:
                unique[fingerprint] = dict(alert)
                continue
            prev_priority = self.PRIORITY.get(previous.get("tipo"), 99)
            next_priority = self.PRIORITY.get(alert.get("tipo"), 99)
            if next_priority < prev_priority:
                unique[fingerprint] = dict(alert)
        return list(unique.values())

    def _fingerprint(self, alert: dict[str, Any]) -> str:
        mensagem = str(alert.get("mensagem") or "").strip().lower()
        categoria = str(alert.get("categoria") or "").strip().lower()
        tipo = str(alert.get("tipo") or "").strip().lower()
        return f"{tipo}|{categoria}|{mensagem}"
