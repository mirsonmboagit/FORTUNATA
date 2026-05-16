from __future__ import annotations

import time
from threading import Event, Lock, Thread
from typing import Callable

from manager.services.camera_service import CameraService
from utils.vision import (
    build_barcode_decode_frame,
    get_vision_dependencies,
    normalize_barcode_value,
)


class ScannerService:
    def __init__(
        self,
        camera_service: CameraService,
        *,
        decode_scale: float = 0.65,
        decode_interval_seconds: float = 0.18,
        detection_hold_seconds: float = 0.40,
        duplicate_cooldown_seconds: float = 2.0,
        on_detected: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self.camera_service = camera_service
        self.decode_scale = float(decode_scale)
        self.decode_interval_seconds = max(0.01, float(decode_interval_seconds))
        self.detection_hold_seconds = max(0.0, float(detection_hold_seconds))
        self.duplicate_cooldown_seconds = max(0.1, float(duplicate_cooldown_seconds))
        self.on_detected = on_detected
        self.on_error = on_error

        self._state_lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._run_token = 0
        self._last_barcode = ""
        self._last_barcode_at = 0.0

    def start(self) -> None:
        self.stop()
        with self._state_lock:
            self._run_token += 1
            token = self._run_token
            self._stop_event = Event()
            self._last_barcode = ""
            self._last_barcode_at = 0.0
        worker = Thread(target=self._worker_loop, args=(token,), daemon=True)
        self._thread = worker
        worker.start()

    def stop(self) -> None:
        with self._state_lock:
            self._run_token += 1
            self._stop_event.set()
            self._thread = None
            self._last_barcode = ""
            self._last_barcode_at = 0.0
        self.camera_service.clear_overlay()

    def _is_token_active(self, token: int) -> bool:
        with self._state_lock:
            return token == self._run_token and not self._stop_event.is_set()

    def _emit_detected(self, barcode_value: str) -> None:
        if callable(self.on_detected):
            self.on_detected(barcode_value)

    def _emit_error(self, message: str) -> None:
        if callable(self.on_error):
            self.on_error(message)

    def _worker_loop(self, token: int) -> None:
        try:
            cv2, _np, decode = get_vision_dependencies()
            last_frame_id = 0
            last_decode_at = 0.0

            while self._is_token_active(token):
                snapshot = self.camera_service.get_latest_frame_snapshot()
                now = time.perf_counter()
                if not snapshot:
                    time.sleep(0.01)
                    continue

                frame_id, frame = snapshot
                if frame_id == last_frame_id or (now - last_decode_at) < self.decode_interval_seconds:
                    time.sleep(0.01)
                    continue

                last_frame_id = frame_id
                last_decode_at = now
                scan_frame = build_barcode_decode_frame(
                    cv2,
                    frame,
                    alpha=1.12,
                    beta=8,
                    scale=self.decode_scale,
                )
                codes = decode(scan_frame)
                if not codes:
                    continue

                code = codes[0]
                points = getattr(code, "polygon", None) or []
                if len(points) >= 4:
                    if 0 < self.decode_scale < 1:
                        scaled_points = [
                            (point.x / self.decode_scale, point.y / self.decode_scale)
                            for point in points
                        ]
                    else:
                        scaled_points = [(point.x, point.y) for point in points]
                    self.camera_service.set_overlay_points(
                        scaled_points,
                        hold_seconds=self.detection_hold_seconds,
                    )

                barcode_value = normalize_barcode_value(getattr(code, "data", None))
                if not barcode_value:
                    continue
                if (
                    barcode_value == self._last_barcode
                    and (now - self._last_barcode_at) < self.duplicate_cooldown_seconds
                ):
                    continue

                self._last_barcode = barcode_value
                self._last_barcode_at = now
                self._emit_detected(barcode_value)
        except RuntimeError as exc:
            self._emit_error(str(exc))
        except Exception as exc:
            self._emit_error(str(exc))
        finally:
            self.camera_service.clear_overlay()
