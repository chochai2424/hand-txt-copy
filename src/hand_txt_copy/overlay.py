"""Transparent, always-on-top overlay for visual feedback.

Draws the gesture cursor, the live selection rectangle, the current mode, and transient toasts on
top of every other window. Critically, the window is configured to **never take keyboard focus and
never receive mouse input**, so the operator's paste keystroke reaches the application underneath.

Only this module imports PySide6. The app treats the overlay through the small public surface:
``set_cursor``, ``set_selection``, ``set_mode``, ``show_toast``, ``set_status``.

It also shows a running indicator: an on-screen status dot (glanceable for the operator, who has no
keyboard/mouse) and a system-tray icon whose color mirrors it and whose menu lets an admin quit.
"""

from __future__ import annotations

import logging
import time

from PySide6 import QtCore, QtGui, QtWidgets

from .config import OverlayConfig
from .selection import Rect

log = logging.getLogger(__name__)

# Status -> (color RGB, short label). Keyed by (camera_ok, hand_present).
_STATUS_RED = ((220, 60, 60), "no camera")
_STATUS_GREEN = ((60, 200, 90), "tracking")
_STATUS_AMBER = ((240, 180, 40), "ready")


class Overlay(QtWidgets.QWidget):
    def __init__(self, cfg: OverlayConfig) -> None:
        super().__init__()
        self._cfg = cfg
        self._cursor: tuple[int, int] | None = None
        self._selection: Rect | None = None
        self._mode: str = "IDLE"
        self._toast: str = ""
        self._camera_ok: bool = False
        self._hand_present: bool = False
        self._tray: QtWidgets.QSystemTrayIcon | None = None
        self._tray_menu: QtWidgets.QMenu | None = None
        self._last_status: tuple[tuple[int, int, int], str] | None = None

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

        screen = QtWidgets.QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

        self._toast_timer = QtCore.QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._clear_toast)

        self._setup_tray()

    def _setup_tray(self) -> None:
        """Create a system-tray icon so admins can see it running and quit it (needs a mouse)."""
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            log.debug("system tray unavailable; HUD indicator only")
            return
        self._tray = QtWidgets.QSystemTrayIcon(self)
        self._tray_menu = QtWidgets.QMenu()
        quit_action = self._tray_menu.addAction("Quit hand-txt-copy")
        quit_action.triggered.connect(lambda: QtWidgets.QApplication.quit())
        self._tray.setContextMenu(self._tray_menu)
        self._tray.setIcon(self._make_icon(_STATUS_AMBER[0]))
        self._tray.setToolTip("hand-txt-copy: starting…")
        self._tray.show()

    @staticmethod
    def _make_icon(rgb: tuple[int, int, int]) -> QtGui.QIcon:
        pix = QtGui.QPixmap(32, 32)
        pix.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pix)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setBrush(QtGui.QColor(*rgb))
        painter.setPen(QtGui.QPen(QtGui.QColor(30, 30, 30), 2))
        painter.drawEllipse(4, 4, 24, 24)
        painter.end()
        return QtGui.QIcon(pix)

    def showEvent(self, event: QtGui.QShowEvent) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._apply_noactivate()

    def _apply_noactivate(self) -> None:
        """Belt-and-suspenders: set WS_EX_NOACTIVATE so the window never steals focus on Windows."""
        try:
            import win32con
            import win32gui

            hwnd = int(self.winId())
            ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            win32gui.SetWindowLong(
                hwnd,
                win32con.GWL_EXSTYLE,
                ex | win32con.WS_EX_NOACTIVATE | win32con.WS_EX_TRANSPARENT,
            )
        except Exception as exc:  # non-Windows or pywin32 missing
            log.debug("could not apply WS_EX_NOACTIVATE: %s", exc)

    # --- public state setters -------------------------------------------------
    def set_cursor(self, point: tuple[int, int] | None) -> None:
        self._cursor = point
        self.update()

    def set_selection(self, rect: Rect | None) -> None:
        self._selection = rect
        self.update()

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.update()

    def set_status(self, camera_ok: bool, hand_present: bool) -> None:
        """Update the running indicator (HUD dot + tray icon)."""
        self._camera_ok = camera_ok
        self._hand_present = hand_present
        status = self._status()
        if status != self._last_status:
            self._last_status = status
            if self._tray is not None:
                self._tray.setIcon(self._make_icon(status[0]))
                self._tray.setToolTip(f"hand-txt-copy: {status[1]}")
        self.update()

    def _status(self) -> tuple[tuple[int, int, int], str]:
        if not self._camera_ok:
            return _STATUS_RED
        return _STATUS_GREEN if self._hand_present else _STATUS_AMBER

    def notify(self, title: str, message: str) -> None:
        """Show a transient tray balloon (no-op if the tray is unavailable)."""
        if self._tray is not None:
            self._tray.showMessage(title, message, self._tray.icon(), 3000)

    def show_toast(self, text: str) -> None:
        self._toast = text
        self.update()
        self._toast_timer.start(self._cfg.toast_ms)

    def _clear_toast(self) -> None:
        self._toast = ""
        self.update()

    # --- painting -------------------------------------------------------------
    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802 (Qt override)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        if self._selection is not None:
            self._draw_selection(painter, self._selection)
        if self._cursor is not None:
            self._draw_cursor(painter, self._cursor)
        self._draw_hud(painter)
        self._draw_status(painter)

    def _draw_cursor(self, painter: QtGui.QPainter, point: tuple[int, int]) -> None:
        r = self._cfg.cursor_radius
        color = QtGui.QColor(*self._cfg.cursor_color)
        pen = QtGui.QPen(color, 3)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(QtCore.QPoint(*point), r, r)
        painter.drawPoint(QtCore.QPoint(*point))

    def _draw_selection(self, painter: QtGui.QPainter, rect: Rect) -> None:
        color = QtGui.QColor(*self._cfg.selection_color)
        pen = QtGui.QPen(color, 2, QtCore.Qt.DashLine)
        painter.setPen(pen)
        fill = QtGui.QColor(color)
        fill.setAlpha(40)
        painter.setBrush(fill)
        painter.drawRect(rect.left, rect.top, rect.width, rect.height)

    def _draw_hud(self, painter: QtGui.QPainter) -> None:
        painter.setPen(QtGui.QColor(255, 255, 255))
        font = painter.font()
        font.setPointSize(14)
        painter.setFont(font)
        painter.drawText(20, 30, f"hand-txt-copy — {self._mode}")
        if self._toast:
            font.setPointSize(20)
            painter.setFont(font)
            painter.setPen(QtGui.QColor(*self._cfg.cursor_color))
            painter.drawText(20, 64, self._toast)

    def _draw_status(self, painter: QtGui.QPainter) -> None:
        """A glanceable running dot in the top-right corner, pulsing to show the app is alive."""
        rgb, label = self._status()
        cx, cy, r = self.width() - 28, 28, 9

        # Pulsing halo (0.5 Hz) so a steady operator can still tell it is live.
        phase = 0.5 + 0.5 * abs((time.monotonic() % 2.0) - 1.0)
        halo = QtGui.QColor(*rgb)
        halo.setAlpha(int(60 * phase))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(QtCore.QPoint(cx, cy), r + 6, r + 6)

        painter.setBrush(QtGui.QColor(*rgb))
        painter.setPen(QtGui.QPen(QtGui.QColor(30, 30, 30), 1))
        painter.drawEllipse(QtCore.QPoint(cx, cy), r, r)

        font = painter.font()
        font.setPointSize(10)
        painter.setFont(font)
        painter.setPen(QtGui.QColor(*rgb))
        metrics = QtGui.QFontMetrics(font)
        text_w = metrics.horizontalAdvance(label)
        painter.drawText(cx - r - 8 - text_w, cy + 4, label)
