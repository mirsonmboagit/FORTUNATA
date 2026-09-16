"""Fila sequencial e limitada para leituras de codigo de barras no POS."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from typing import Any, Callable

from kivy.clock import Clock


@dataclass(frozen=True)
class BarcodeScanResult:
    barcode: str
    source: str
    rows: list[tuple]
    error: str | None = None


class BarcodeScanPipeline:
    """Executa consultas de scanner numa unica conexao SQLite de leitura.

    Scans USB sao todos mantidos na ordem de chegada. A deduplicacao fica no
    produtor de camera, onde uma imagem continua a mostrar o mesmo codigo por
    varios frames; nunca e aplicada aos scans USB, pois duas leituras iguais
    consecutivas podem ser uma venda legitima de duas unidades.
    """

    def __init__(
        self,
        db: Any,
        on_results: Callable[[list[BarcodeScanResult]], None],
        *,
        max_pending: int = 2048,
        max_results_per_frame: int = 32,
    ) -> None:
        self.db = db
        self.on_results = on_results
        self.max_results_per_frame = max(1, int(max_results_per_frame))
        self._pending: Queue[tuple[int, str, str] | None] = Queue(maxsize=max(1, int(max_pending)))
        self._results: Queue[tuple[int, BarcodeScanResult]] = Queue(maxsize=max(1, int(max_pending)))
        self._state_lock = Lock()
        self._stop_event = Event()
        self._worker: Thread | None = None
        self._generation = 0
        self._delivery_trigger = Clock.create_trigger(self._deliver, 0)

    @staticmethod
    def normalize(value: Any) -> str:
        return "".join(char for char in str(value or "") if char.isprintable()).strip()

    def submit(self, barcode: Any, source: str = "physical") -> bool:
        code = self.normalize(barcode)
        if not code:
            return False
        with self._state_lock:
            if self._worker is None or not self._worker.is_alive():
                self._start_locked()
            generation = self._generation
        try:
            self._pending.put_nowait((generation, code, str(source or "physical")))
            return True
        except Full:
            return False

    def stop(self) -> None:
        with self._state_lock:
            self._generation += 1
            self._stop_event.set()
            self._worker = None
        self._drain_queue(self._pending)
        self._drain_queue(self._results)

    def _start_locked(self) -> None:
        self._generation += 1
        self._stop_event = Event()
        worker = Thread(target=self._worker_loop, args=(self._generation,), daemon=True)
        self._worker = worker
        worker.start()

    @staticmethod
    def _drain_queue(queue: Queue) -> None:
        while True:
            try:
                queue.get_nowait()
            except Empty:
                return

    def _is_current(self, generation: int) -> bool:
        with self._state_lock:
            return generation == self._generation and not self._stop_event.is_set()

    def _worker_loop(self, generation: int) -> None:
        factory = getattr(self.db, "background_connection", None)
        context = factory() if callable(factory) else _NullContext(self.db)
        try:
            with context as db:
                while self._is_current(generation):
                    try:
                        item = self._pending.get(timeout=0.10)
                    except Empty:
                        continue
                    if item is None:
                        continue
                    item_generation, barcode, source = item
                    if item_generation != generation:
                        continue
                    try:
                        rows = db.get_sale_lots_by_barcode_fast(barcode) or []
                        result = BarcodeScanResult(barcode, source, rows)
                    except Exception as exc:
                        result = BarcodeScanResult(barcode, source, [], str(exc))
                    if not self._is_current(generation):
                        continue
                    # A entrega pode ficar temporariamente atrasada pela UI.
                    # Esperar com timeout preserva a ordem e permite encerrar
                    # sem deixar a thread bloqueada para sempre.
                    while self._is_current(generation):
                        try:
                            self._results.put((generation, result), timeout=0.10)
                            break
                        except Full:
                            self._delivery_trigger()
                    else:
                        continue
                    self._delivery_trigger()
        finally:
            self._delivery_trigger()

    def _deliver(self, *_args) -> None:
        with self._state_lock:
            generation = self._generation
        batch: list[BarcodeScanResult] = []
        while len(batch) < self.max_results_per_frame:
            try:
                item_generation, result = self._results.get_nowait()
            except Empty:
                break
            if item_generation == generation:
                batch.append(result)
        if batch and self._is_current(generation):
            self.on_results(batch)
        if not self._results.empty() and self._is_current(generation):
            self._delivery_trigger()


class _NullContext:
    def __init__(self, value: Any) -> None:
        self.value = value

    def __enter__(self) -> Any:
        return self.value

    def __exit__(self, *_args) -> None:
        return None
