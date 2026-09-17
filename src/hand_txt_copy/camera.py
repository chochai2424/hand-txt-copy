"""Threaded webcam capture.

A background thread continuously grabs frames and keeps only the latest one, so the main loop
always processes a fresh frame instead of draining a backlog (which would add latency to the
gesture-to-cursor response).
"""

from __future__ import annotations

import logging
import threading

import numpy as np

from .config import CameraConfig

log = logging.getLogger(__name__)


class CameraError(RuntimeError):
    pass


class Camera:
    def __init__(self, cfg: CameraConfig) -> None:
        self._cfg = cfg
        self._cap = None
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        import cv2

        self._cap = cv2.VideoCapture(self._cfg.index, cv2.CAP_DSHOW)
        if not self._cap.isOpened():
            raise CameraError(f"could not open camera index {self._cfg.index}")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._cfg.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._cfg.height)
        self._cap.set(cv2.CAP_PROP_FPS, self._cfg.fps)

        self._running = True
        self._thread = threading.Thread(target=self._loop, name="camera", daemon=True)
        self._thread.start()
        log.info("camera %d started (%dx%d)", self._cfg.index, self._cfg.width, self._cfg.height)

    def _loop(self) -> None:
        import cv2

        while self._running:
            ok, frame = self._cap.read()
            if not ok:
                continue
            if self._cfg.mirror:
                frame = cv2.flip(frame, 1)
            with self._lock:
                self._frame = frame

    def read(self) -> np.ndarray | None:
        """Return the most recent frame (or ``None`` before the first frame arrives)."""
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self._cap is not None:
            self._cap.release()
        log.info("camera stopped")

    def __enter__(self) -> Camera:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
