"""Application orchestration: the copy/select/paste state machine and the per-frame tick.

``App`` owns all the components and the finite state machine. Each :meth:`tick` reads the latest
camera frame, extracts landmarks, resolves a debounced gesture, and drives the FSM:

    IDLE  --pinch-->  SELECTING  --release-->  (capture + OCR + clipboard)  -->  CAPTURED
    CAPTURED/IDLE  --open palm-->  paste into focused app
    any  --fist-->  IDLE (cancel)

The tick is deliberately loop-agnostic: ``__main__`` calls it from a Qt timer (with overlay) or a
plain loop (headless), so the state logic stays in one place.
"""

from __future__ import annotations

import logging
import time
from enum import Enum, auto

from .camera import Camera
from .capture import ScreenCapture
from .clipboard import Clipboard
from .config import Config
from .cursor import CursorMapper
from .gestures import Gesture, GestureDetector
from .hand_tracker import LANDMARK, HandTracker
from .ocr import OcrEngine
from .paste import Paster
from .selection import Selection, is_usable

log = logging.getLogger(__name__)


class State(Enum):
    IDLE = auto()
    SELECTING = auto()
    CAPTURED = auto()


class App:
    def __init__(self, cfg: Config, overlay=None) -> None:
        self.cfg = cfg
        self.overlay = overlay

        self.camera = Camera(cfg.camera)
        self.tracker = HandTracker(cfg.hand_tracker)
        self.detector = GestureDetector(cfg.gestures)
        self.screen = ScreenCapture(cfg.screen)
        self.ocr = OcrEngine(cfg.ocr)
        self.clipboard = Clipboard()
        self.paster = Paster(cfg.paste)
        self.mapper = CursorMapper(cfg.cursor, self.screen.monitor_size())

        self.state = State.IDLE
        self._selection: Selection | None = None
        self._cursor: tuple[int, int] = (0, 0)
        self._hand_present: bool = False
        self._last_ts = time.perf_counter()

    def start(self) -> None:
        self.camera.start()
        log.info("app started in state %s", self.state.name)

    def stop(self) -> None:
        self.camera.stop()
        self.tracker.close()
        self.screen.close()
        log.info("app stopped")

    def tick(self) -> None:
        """Process one frame and advance the state machine. Never raises for expected conditions."""
        frame = self.camera.read()
        if frame is None:
            if self.overlay is not None:
                self.overlay.set_status(camera_ok=False, hand_present=False)
            return

        now = time.perf_counter()
        dt = now - self._last_ts
        self._last_ts = now

        landmarks = self.tracker.process(frame)
        gesture = self.detector.update(landmarks)
        self._hand_present = landmarks is not None

        if landmarks is not None:
            tip = landmarks[LANDMARK.INDEX_TIP]
            self._cursor = self.mapper.map(float(tip[0]), float(tip[1]), dt)

        self._dispatch(gesture)
        self._render()

    # --- state machine --------------------------------------------------------
    def _dispatch(self, gesture: Gesture) -> None:
        if gesture == Gesture.FIST:
            self._cancel()
            return

        if self.state == State.IDLE:
            if gesture == Gesture.PINCH:
                self._begin_selection()
            elif gesture == Gesture.OPEN_PALM:
                self._do_paste()

        elif self.state == State.SELECTING:
            if gesture == Gesture.PINCH:
                if self._selection is not None:
                    self._selection.update(self._cursor)
            else:  # pinch released
                self._finish_selection()

        elif self.state == State.CAPTURED:
            if gesture == Gesture.OPEN_PALM:
                self._do_paste()
            elif gesture == Gesture.PINCH:
                self._begin_selection()

    def _begin_selection(self) -> None:
        self._selection = Selection(self._cursor)
        self.state = State.SELECTING
        log.debug("selection started at %s", self._cursor)

    def _finish_selection(self) -> None:
        if self._selection is None:
            self.state = State.IDLE
            return
        rect = self._selection.rect()
        self._selection = None
        if not is_usable(rect):
            log.debug("selection too small (%s); cancelling", rect)
            self.state = State.IDLE
            self._toast("Selection too small")
            return
        self._capture(rect)

    def _capture(self, rect) -> None:
        try:
            image = self.screen.grab(rect)
            text = self.ocr.read_text(image)
            self.clipboard.set(image=image, text=text or None)
            self.state = State.CAPTURED
            self._toast(f"Copied ({len(text)} chars)" if text else "Copied image")
        except Exception:
            log.exception("capture failed")
            self.state = State.IDLE
            self._toast("Copy failed")

    def _do_paste(self) -> None:
        try:
            self.paster.paste()
            self._toast("Pasted")
        except Exception:
            log.exception("paste failed")
            self._toast("Paste failed")

    def _cancel(self) -> None:
        if self.state != State.IDLE or self._selection is not None:
            log.debug("cancelled")
        self._selection = None
        self.state = State.IDLE

    # --- rendering ------------------------------------------------------------
    def _render(self) -> None:
        if self.overlay is None:
            return
        self.overlay.set_mode(self.state.name)
        self.overlay.set_cursor(self._cursor)
        rect = self._selection.rect() if self._selection is not None else None
        self.overlay.set_selection(rect)
        self.overlay.set_status(camera_ok=True, hand_present=self._hand_present)

    def _toast(self, text: str) -> None:
        log.info(text)
        if self.overlay is not None:
            self.overlay.show_toast(text)
