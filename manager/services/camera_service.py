from __future__ import annotations

import time
from threading import Event, Lock, Thread
from typing import Callable

from utils.vision import get_vision_dependencies, open_optimized_camera_capture


PreviewPayload = tuple[int, int, int, bytes]
FrameSnapshot = tuple[int, object]


class CameraService:
    def __init__(
        self,
        *,
        width: int = 480,
        height: int = 360,
        preview_fps: int = 20,
        on_started: Callable[[int], None] | None = None,
        on_error: Callable[[str, str | None], None] | None = None,
    ) -> None:
        self.width = int(width)
        self.height = int(height)
        self.preview_fps = max(1, int(preview_fps))
        self.on_started = on_started
        self.on_error = on_error

        self._state_lock = Lock()
        self._data_lock = Lock()
        self._overlay_lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._capture = None
        self._run_token = 0
        self._camera_index = 0
        self._latest_frame = None
        self._latest_frame_id = 0
        self._latest_preview: PreviewPayload | None = None
        self._overlay_points: tuple[tuple[int, int], ...] | None = None
        self._overlay_expires_at = 0.0

    def start(self, camera_index: int = 0) -> None:
        self.stop()
        with self._state_lock:
            self._run_token += 1
            token = self._run_token
            self._camera_index = max(0, int(camera_index or 0))
            self._stop_event = Event()
        worker = Thread(target=self._worker_loop, args=(token,), daemon=True)
        self._thread = worker
        worker.start()

    def stop(self) -> None:
        capture = None
        with self._state_lock:
            self._run_token += 1
            self._stop_event.set()
            capture = self._capture
            self._capture = None
            self._thread = None

        if capture is not None:
            try:
                capture.release()
            except Exception:
                pass

        self.clear_overlay()
        with self._data_lock:
            self._latest_frame = None
            self._latest_frame_id = 0
            self._latest_preview = None

    def get_latest_frame_snapshot(self) -> FrameSnapshot | None:
        with self._data_lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame_id, self._latest_frame.copy()

    def consume_latest_preview_payload(self) -> PreviewPayload | None:
        with self._data_lock:
            payload = self._latest_preview
            self._latest_preview = None
        return payload

    def set_overlay_points(self, points, hold_seconds: float = 0.4) -> None:
        normalized = []
        for point in points or []:
            try:
                normalized.append((int(point[0]), int(point[1])))
            except Exception:
                continue
        if not normalized:
            self.clear_overlay()
            return
        with self._overlay_lock:
            self._overlay_points = tuple(normalized)
            self._overlay_expires_at = time.perf_counter() + max(0.0, float(hold_seconds))

    def clear_overlay(self) -> None:
        with self._overlay_lock:
            self._overlay_points = None
            self._overlay_expires_at = 0.0

    def _is_token_active(self, token: int) -> bool:
        with self._state_lock:
            return token == self._run_token and not self._stop_event.is_set()

    def _read_camera_index(self, token: int) -> int | None:
        with self._state_lock:
            if token != self._run_token:
                return None
            return self._camera_index

    def _emit_started(self, token: int, camera_index: int) -> None:
        if self._is_token_active(token) and callable(self.on_started):
            self.on_started(camera_index)

    def _emit_error(self, token: int, reason: str, message: str | None = None) -> None:
        if self._is_token_active(token) and callable(self.on_error):
            self.on_error(reason, message)

    def _get_active_overlay_points(self, now: float):
        with self._overlay_lock:
            if not self._overlay_points:
                return None
            if now > self._overlay_expires_at:
                self._overlay_points = None
                self._overlay_expires_at = 0.0
                return None
            return self._overlay_points

    def _worker_loop(self, token: int) -> None:
        capture = None
        try:
            cv2, np, _decode = get_vision_dependencies()
            if not self._is_token_active(token):
                return

            camera_index = self._read_camera_index(token)
            if camera_index is None:
                return

            capture = open_optimized_camera_capture(
                cv2,
                camera_index,
                width=self.width,
                height=self.height,
                preview_fps=self.preview_fps,
            )
            if not capture or not capture.isOpened():
                self._emit_error(token, "camera_missing")
                return

            with self._state_lock:
                if token != self._run_token:
                    try:
                        capture.release()
                    except Exception:
                        pass
                    return
                self._capture = capture

            self._emit_started(token, camera_index)
            target_interval = 1.0 / float(self.preview_fps)

            while self._is_token_active(token):
                frame_started_at = time.perf_counter()
                ok, frame = capture.read()
                if not ok or frame is None:
                    time.sleep(0.01)
                    continue

                overlay_points = self._get_active_overlay_points(time.perf_counter())
                preview_frame = frame
                if overlay_points:
                    preview_frame = frame.copy()
                    cv2.polylines(
                        preview_frame,
                        [np.array(overlay_points, dtype=np.int32)],
                        True,
                        (40, 220, 80),
                        3,
                    )

                flipped = cv2.flip(preview_frame, 0)
                with self._data_lock:
                    self._latest_frame_id += 1
                    frame_id = self._latest_frame_id
                    self._latest_frame = frame
                    self._latest_preview = (
                        frame_id,
                        int(flipped.shape[1]),
                        int(flipped.shape[0]),
                        flipped.tobytes(),
                    )

                elapsed = time.perf_counter() - frame_started_at
                if elapsed < target_interval:
                    time.sleep(target_interval - elapsed)
        except RuntimeError as exc:
            self._emit_error(token, "dependencies", str(exc))
        except Exception as exc:
            self._emit_error(token, "generic", str(exc))
        finally:
            if capture is not None:
                try:
                    capture.release()
                except Exception:
                    pass
            with self._state_lock:
                if self._capture is capture:
                    self._capture = None
