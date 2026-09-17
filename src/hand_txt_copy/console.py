"""Video-call-style console window: a *visible* app window for monitoring the tracker.

Unlike the transparent overlay (which floats invisibly over other apps for hands-free copy/paste),
this is a normal desktop window you can watch:

- a large **dashboard** (status pill, live gesture, FPS, and a gesture legend), plus
- a small **picture-in-picture webcam self-view** in the corner (like a video call), showing the
  live feed with the detected hand skeleton and fingertip cursor.

Click the small self-view (or press ``F``) to blow it up to **fullscreen** with the full HUD:
landmarks, fingertip cursor, pinch distance, the cursor active region, gesture, and status. Click
again or press ``Esc`` to return.

This window is for setup/monitoring/demo; it does not write to the clipboard. Run it with
``python -m hand_txt_copy --console``.
"""

from __future__ import annotations

import logging
import time

from PySide6 import QtCore, QtGui, QtWidgets

from . import winmouse
from .camera import Camera
from .capture import ScreenCapture
from .clipboard import Clipboard
from .config import Config
from .cursor import CursorMapper
from .gestures import Gesture, GestureDetector, pinch_distance
from .hand_tracker import HAND_CONNECTIONS, LANDMARK, HandTracker
from .ocr import OcrEngine
from .paste import Paster
from .selection import Rect, Selection, is_usable

log = logging.getLogger(__name__)

_STATUS_RED = ((220, 60, 60), "no camera")
_STATUS_GREEN = ((60, 200, 90), "tracking")
_STATUS_AMBER = ((240, 180, 40), "no hand")

_LEGEND = [
    ("Point (index finger)", "move cursor"),
    ("Two fingers (index+middle)", "click"),
    ("Pinch + drag", "select a region"),
    ("Release pinch", "copy image + text"),
    ("Open palm", "paste"),
    ("Fist", "cancel"),
]


class SharedState:
    """Per-frame data shared between the loop and both video views."""

    def __init__(self) -> None:
        self.qimage: QtGui.QImage | None = None
        self.landmarks = None
        self.gesture: Gesture = Gesture.NONE
        self.cursor_norm: tuple[float, float] | None = None
        self.pinch_dist: float | None = None
        self.camera_ok: bool = False
        self.hand_present: bool = False
        self.fps: float = 0.0
        self.mode: str = "MONITOR"
        self.move_cursor: bool = True
        self.screen_cursor: tuple[int, int] | None = None


def status_of(state: SharedState) -> tuple[tuple[int, int, int], str]:
    if not state.camera_ok:
        return _STATUS_RED
    return _STATUS_GREEN if state.hand_present else _STATUS_AMBER


class VideoWidget(QtWidgets.QWidget):
    """Paints the webcam frame plus tracking overlays. Emits ``clicked`` on mouse press."""

    clicked = QtCore.Signal()

    def __init__(self, state: SharedState, connections, cfg: Config, *, detail: bool) -> None:
        super().__init__()
        self._state = state
        self._conn = connections
        self._cfg = cfg
        self._detail = detail
        self.setMinimumSize(160, 120)
        self.setCursor(QtCore.Qt.PointingHandCursor)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802 (Qt override)
        self.clicked.emit()

    def _image_rect(self, iw: int, ih: int) -> QtCore.QRectF:
        """Letterbox the frame into the widget, preserving aspect ratio."""
        w, h = self.width(), self.height()
        scale = min(w / iw, h / ih)
        dw, dh = iw * scale, ih * scale
        return QtCore.QRectF((w - dw) / 2, (h - dh) / 2, dw, dh)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802 (Qt override)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QtGui.QColor(17, 17, 17))
        st = self._state

        if st.qimage is None:
            p.setPen(QtGui.QColor(200, 200, 200))
            p.drawText(self.rect(), QtCore.Qt.AlignCenter, "waiting for camera…")
            self._draw_status_pill(p)
            return

        img = st.qimage
        rect = self._image_rect(img.width(), img.height())
        p.drawImage(rect, img)

        ox, oy, rw, rh = rect.x(), rect.y(), rect.width(), rect.height()

        def to_px(nx: float, ny: float) -> QtCore.QPointF:
            return QtCore.QPointF(ox + nx * rw, oy + ny * rh)

        if self._detail:
            self._draw_active_region(p, rect)

        if st.landmarks is not None:
            pts = [to_px(float(x), float(y)) for x, y, _ in st.landmarks]
            p.setPen(QtGui.QPen(QtGui.QColor(0, 180, 0), 2))
            for a, b in self._conn:
                p.drawLine(pts[a], pts[b])
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(0, 255, 0))
            for pt in pts:
                p.drawEllipse(pt, 3, 3)
            # pinch pair
            p.setBrush(QtCore.Qt.NoBrush)
            p.setPen(QtGui.QPen(QtGui.QColor(0, 200, 255), 2))
            p.drawEllipse(pts[LANDMARK.THUMB_TIP], 7, 7)
            p.drawEllipse(pts[LANDMARK.INDEX_TIP], 7, 7)
            p.drawLine(pts[LANDMARK.THUMB_TIP], pts[LANDMARK.INDEX_TIP])

        if st.cursor_norm is not None:
            cp = to_px(*st.cursor_norm)
            p.setPen(QtGui.QPen(QtGui.QColor(*self._cfg.overlay.cursor_color), 3))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawEllipse(cp, 10, 10)

        self._draw_hud(p)
        self._draw_status_pill(p)

    def _draw_active_region(self, p: QtGui.QPainter, rect: QtCore.QRectF) -> None:
        mx, my = self._cfg.cursor.margin_x, self._cfg.cursor.margin_y
        ar = QtCore.QRectF(
            rect.x() + mx * rect.width(),
            rect.y() + my * rect.height(),
            rect.width() * (1 - 2 * mx),
            rect.height() * (1 - 2 * my),
        )
        p.setPen(QtGui.QPen(QtGui.QColor(255, 200, 0), 1, QtCore.Qt.DashLine))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRect(ar)

    def _draw_hud(self, p: QtGui.QPainter) -> None:
        st = self._state
        font = p.font()
        font.setPointSize(12 if self._detail else 9)
        p.setFont(font)
        p.setPen(QtGui.QColor(255, 255, 255))
        cursor_txt = "mouse: ON (M)" if st.move_cursor else "mouse: OFF (M)"
        lines = [f"gesture: {st.gesture.value}", cursor_txt, f"{st.fps:4.1f} fps"]
        if self._detail and st.pinch_dist is not None:
            lines.insert(1, f"pinch dist: {st.pinch_dist:.3f}")
        y = self.height() - 12 - 16 * (len(lines) - 1)
        for text in lines:
            p.drawText(12, y, text)
            y += 16
        if not self._detail:
            p.setPen(QtGui.QColor(180, 180, 180))
            p.drawText(12, 18, "click to expand")

    def _draw_status_pill(self, p: QtGui.QPainter) -> None:
        rgb, label = status_of(self._state)
        r = 7
        cx, cy = self.width() - 16, 16
        halo = QtGui.QColor(*rgb)
        phase = 0.5 + 0.5 * abs((time.monotonic() % 2.0) - 1.0)
        halo.setAlpha(int(70 * phase))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QtCore.QPointF(cx, cy), r + 5, r + 5)
        p.setBrush(QtGui.QColor(*rgb))
        p.setPen(QtGui.QPen(QtGui.QColor(20, 20, 20), 1))
        p.drawEllipse(QtCore.QPointF(cx, cy), r, r)
        font = p.font()
        font.setPointSize(9)
        p.setFont(font)
        p.setPen(QtGui.QColor(*rgb))
        metrics = QtGui.QFontMetrics(font)
        p.drawText(cx - r - 8 - metrics.horizontalAdvance(label), cy + 4, label)


class DashboardPage(QtWidgets.QWidget):
    """The large view: status + gesture legend, with the PiP self-view floating in the corner."""

    def __init__(self, pip: VideoWidget, state: SharedState) -> None:
        super().__init__()
        self._pip = pip
        self._pip.setParent(self)
        self._state = state
        self.setStyleSheet("background:#1b1f24; color:#e8e8e8;")

        self._title = QtWidgets.QLabel("hand-txt-copy")
        self._title.setStyleSheet("font-size:26px; font-weight:600;")
        self._subtitle = QtWidgets.QLabel("gesture-driven copy / paste — monitor console")
        self._subtitle.setStyleSheet("color:#9aa4af;")
        self._status = QtWidgets.QLabel("starting…")
        self._status.setStyleSheet("font-size:18px; font-weight:600;")

        legend = QtWidgets.QGridLayout()
        legend.setHorizontalSpacing(18)
        legend.setVerticalSpacing(6)
        for i, (gesture, effect) in enumerate(_LEGEND):
            g = QtWidgets.QLabel(gesture)
            g.setStyleSheet("font-weight:600;")
            e = QtWidgets.QLabel(f"→  {effect}")
            e.setStyleSheet("color:#9aa4af;")
            legend.addWidget(g, i, 0)
            legend.addWidget(e, i, 1)
        legend.setColumnStretch(2, 1)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.addWidget(self._title)
        layout.addWidget(self._subtitle)
        layout.addSpacing(18)
        layout.addWidget(self._status)
        layout.addSpacing(18)
        layout.addLayout(legend)
        layout.addStretch(1)
        hint = QtWidgets.QLabel(
            "Click the webcam preview (bottom-right) or press F for fullscreen.   "
            "The mouse pointer follows your finger — press M to toggle."
        )
        hint.setStyleSheet("color:#6f7783;")
        layout.addWidget(hint)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: N802 (Qt override)
        margin = 20
        w = max(240, min(380, self.width() // 3))
        h = int(w * 3 / 4)
        self._pip.setGeometry(self.width() - w - margin, self.height() - h - margin, w, h)
        self._pip.raise_()

    def refresh(self) -> None:
        rgb, label = status_of(self._state)
        self._status.setText(f"● {label}   |   {self._state.gesture.value}   |   {self._state.fps:4.1f} fps")
        self._status.setStyleSheet(f"font-size:18px; font-weight:600; color:rgb{rgb};")


class ScreenOverlay(QtWidgets.QWidget):
    """Full-screen, always-on-top, click-through overlay drawn over ALL windows.

    Renders the mini status/action badge in the top-left corner and the live selection rectangle
    while the operator is drawing one. It never takes keyboard focus (so paste reaches the app
    underneath) and never receives mouse input (so it does not block clicks).
    """

    def __init__(self) -> None:
        super().__init__()
        self._badge_rgb = (240, 180, 40)
        self._badge_text = "starting…"
        self._selection: QtCore.QRect | None = None

        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool
            | QtCore.Qt.WindowTransparentForInput
            | QtCore.Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        self.setGeometry(QtWidgets.QApplication.primaryScreen().geometry())

    def showEvent(self, event: QtGui.QShowEvent) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        try:
            import win32con
            import win32gui

            hwnd = int(self.winId())
            ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            win32gui.SetWindowLong(
                hwnd, win32con.GWL_EXSTYLE,
                ex | win32con.WS_EX_NOACTIVATE | win32con.WS_EX_TRANSPARENT,
            )
        except Exception as exc:
            log.debug("could not apply WS_EX_NOACTIVATE to overlay: %s", exc)

    def set_badge(self, rgb: tuple[int, int, int], text: str) -> None:
        self._badge_rgb, self._badge_text = rgb, text
        self.update()

    def set_selection(self, rect: QtCore.QRect | None) -> None:
        self._selection = rect
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802 (Qt override)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)

        if self._selection is not None:
            color = QtGui.QColor(0, 200, 255)
            p.setPen(QtGui.QPen(color, 2, QtCore.Qt.DashLine))
            fill = QtGui.QColor(color)
            fill.setAlpha(40)
            p.setBrush(fill)
            p.drawRect(self._selection)

        # Mini badge, top-left.
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(20, 24, 30, 210))
        badge = QtCore.QRectF(16, 16, 210, 40)
        p.drawRoundedRect(badge, 10, 10)
        p.setBrush(QtGui.QColor(*self._badge_rgb))
        p.drawEllipse(QtCore.QPointF(38, 36), 8, 8)
        p.setPen(QtGui.QColor(235, 238, 242))
        font = p.font()
        font.setPointSize(11)
        font.setBold(True)
        p.setFont(font)
        p.drawText(QtCore.QRectF(58, 16, 160, 40), QtCore.Qt.AlignVCenter, self._badge_text)


class ConsoleWindow(QtWidgets.QMainWindow):
    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg
        self.setWindowTitle("hand-txt-copy — console")
        self.resize(1000, 680)

        self.state = SharedState()
        self._conn = HAND_CONNECTIONS

        self.pip = VideoWidget(self.state, self._conn, cfg, detail=False)
        self.full = VideoWidget(self.state, self._conn, cfg, detail=True)
        self.dash = DashboardPage(self.pip, self.state)

        self.stack = QtWidgets.QStackedWidget()
        self.stack.addWidget(self.dash)
        self.stack.addWidget(self.full)
        self.setCentralWidget(self.stack)

        self.pip.clicked.connect(self.enter_full)
        self.full.clicked.connect(self.exit_full)

        self.camera = Camera(cfg.camera)
        self.tracker = HandTracker(cfg.hand_tracker)
        self.detector = GestureDetector(cfg.gestures)
        self._last = time.perf_counter()

        # Map the fingertip to a real screen pixel (physical, DPI-correct) to drive the OS pointer.
        phys = winmouse.screen_size()
        if phys is None:
            geo = QtWidgets.QApplication.primaryScreen().geometry()
            phys = (geo.width(), geo.height())
        self._screen_size = phys
        self.mapper = CursorMapper(cfg.cursor, self._screen_size)
        self.state.move_cursor = cfg.console.move_cursor
        self._dpr = QtWidgets.QApplication.primaryScreen().devicePixelRatio() or 1.0

        # Copy/paste effect modules and finite-state machine (mirrors app.App).
        self.screen_capture = ScreenCapture(cfg.screen)
        self.ocr = OcrEngine(cfg.ocr)
        self.clipboard = Clipboard()
        self.paster = Paster(cfg.paste)
        self._fsm = "IDLE"  # IDLE | SELECTING | CAPTURING
        self._selection: Selection | None = None
        self._last_gesture = Gesture.NONE
        self._toast_text = "Ready"
        self._toast_rgb = _STATUS_AMBER[0]
        self._toast_until = 0.0

        # Always-on-top badge + selection rectangle, visible over every other window.
        self.overlay = ScreenOverlay()
        self.overlay.show()

        self.camera.start()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(max(1, int(1000 / cfg.camera.fps)))

    def enter_full(self) -> None:
        self.state.mode = "DETAIL"
        self.stack.setCurrentWidget(self.full)
        self.showFullScreen()

    def exit_full(self) -> None:
        self.state.mode = "MONITOR"
        self.stack.setCurrentWidget(self.dash)
        self.showNormal()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:  # noqa: N802 (Qt override)
        if event.key() == QtCore.Qt.Key_Escape:
            self.exit_full()
        elif event.key() == QtCore.Qt.Key_F:
            self.exit_full() if self.stack.currentWidget() is self.full else self.enter_full()
        elif event.key() == QtCore.Qt.Key_M:
            self.state.move_cursor = not self.state.move_cursor
            log.info("OS cursor control: %s", "ON" if self.state.move_cursor else "OFF")
        else:
            super().keyPressEvent(event)

    def _tick(self) -> None:
        import cv2

        now = time.perf_counter()
        dt = now - self._last
        self._last = now
        if dt > 0:
            self.state.fps = 0.9 * self.state.fps + 0.1 * (1.0 / dt)

        frame = self.camera.read()
        if frame is None:
            self.state.camera_ok = False
            self._refresh()
            return

        landmarks = self.tracker.process(frame)
        self.state.gesture = self.detector.update(landmarks)
        self.state.landmarks = landmarks
        self.state.hand_present = landmarks is not None
        self.state.camera_ok = True
        if landmarks is not None:
            tip = landmarks[LANDMARK.INDEX_TIP]
            self.state.cursor_norm = (float(tip[0]), float(tip[1]))
            self.state.pinch_dist = pinch_distance(landmarks)
            sx, sy = self.mapper.map(float(tip[0]), float(tip[1]), dt)
            self.state.screen_cursor = (sx, sy)
            if self.state.move_cursor:
                self._move_os_cursor(sx, sy)
        else:
            self.state.cursor_norm = None
            self.state.pinch_dist = None

        self._dispatch(self.state.gesture)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        self.state.qimage = QtGui.QImage(
            rgb.data, w, h, 3 * w, QtGui.QImage.Format_RGB888
        ).copy()
        self._refresh()

    # --- click / copy / paste / cancel state machine -------------------------
    def _dispatch(self, gesture: Gesture) -> None:
        # One-shot actions fire only on the transition INTO the gesture, not every frame it is held.
        changed = gesture != self._last_gesture
        self._last_gesture = gesture

        if self._fsm == "CAPTURING":
            return  # capture in progress (screenshot pending); ignore input briefly

        if gesture == Gesture.FIST:
            if changed and (self._fsm != "IDLE" or self._selection is not None):
                self._toast("Cancelled", (240, 180, 40))
            self._selection = None
            self._fsm = "IDLE"
            return

        if self._fsm == "IDLE":
            if gesture == Gesture.PINCH:
                self._selection = Selection(self.state.screen_cursor)
                self._fsm = "SELECTING"
            elif gesture == Gesture.CLICK and changed:
                self._do_click()
            elif gesture == Gesture.OPEN_PALM and changed:
                self._do_paste()
        elif self._fsm == "SELECTING":
            if gesture == Gesture.PINCH and self._selection is not None:
                self._selection.update(self.state.screen_cursor)
            else:  # pinch released
                self._finish_selection()

    def _finish_selection(self) -> None:
        sel, self._selection = self._selection, None
        if sel is None:
            self._fsm = "IDLE"
            return
        rect = sel.rect()
        if not is_usable(rect):
            self._fsm = "IDLE"
            self._toast("Selection too small", (240, 180, 40))
            return
        # Hide our overlay so the screenshot does not include the selection rectangle/badge,
        # then grab on the next event-loop turn once it has repainted away.
        self._fsm = "CAPTURING"
        self.overlay.hide()
        QtCore.QTimer.singleShot(60, lambda: self._capture(rect))

    def _capture(self, rect: Rect) -> None:
        try:
            image = self.screen_capture.grab(rect)
            text = self.ocr.read_text(image)
            self.clipboard.set(image=image, text=text or None)
            self._toast(f"Copied ({len(text)} chars)" if text else "Copied image", (60, 200, 90))
        except Exception:
            log.exception("capture failed")
            self._toast("Copy failed", (220, 60, 60))
        finally:
            self.overlay.show()
            self._fsm = "IDLE"

    def _do_click(self) -> None:
        winmouse.click()
        self._toast("Click", (0, 200, 255))

    def _do_paste(self) -> None:
        try:
            self.paster.paste()
            self._toast("Pasted", (60, 200, 90))
        except Exception:
            log.exception("paste failed")
            self._toast("Paste failed", (220, 60, 60))

    def _toast(self, text: str, rgb: tuple[int, int, int]) -> None:
        self._toast_text, self._toast_rgb = text, rgb
        self._toast_until = time.monotonic() + (self.cfg.overlay.toast_ms / 1000.0)
        log.info("action: %s", text)

    @staticmethod
    def _move_os_cursor(x: int, y: int) -> None:
        """Move the real Windows mouse pointer to a physical screen pixel."""
        winmouse.move_to(x, y)

    def _refresh(self) -> None:
        self.dash.refresh()
        (self.full if self.stack.currentWidget() is self.full else self.pip).update()
        self._refresh_overlay()

    def _refresh_overlay(self) -> None:
        # Badge: show the active toast, else the live tracking/selecting status.
        if time.monotonic() < self._toast_until:
            self.overlay.set_badge(self._toast_rgb, self._toast_text)
        elif self._fsm == "SELECTING":
            self.overlay.set_badge((0, 200, 255), "Selecting…")
        else:
            rgb, label = status_of(self.state)
            self.overlay.set_badge(rgb, label.capitalize())

        # Selection rectangle, converted from physical pixels to the overlay's logical pixels.
        if self._fsm == "SELECTING" and self._selection is not None:
            r = self._selection.rect()
            d = self._dpr
            self.overlay.set_selection(
                QtCore.QRect(int(r.left / d), int(r.top / d), int(r.width / d), int(r.height / d))
            )
        else:
            self.overlay.set_selection(None)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802 (Qt override)
        self.timer.stop()
        self.camera.stop()
        self.tracker.close()
        self.screen_capture.close()
        self.overlay.close()
        super().closeEvent(event)


def run_console(cfg: Config) -> int:
    """Launch the console window and run the Qt event loop."""
    import sys

    # Must precede QApplication so Qt, screen metrics, and cursor coords all use physical pixels.
    winmouse.set_dpi_aware()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    window = ConsoleWindow(cfg)
    window.show()
    log.info("console window started")
    return app.exec()
