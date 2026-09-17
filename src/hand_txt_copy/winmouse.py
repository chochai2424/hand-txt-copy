"""Move the real Windows mouse pointer, correctly on high-DPI and multi-monitor setups.

Uses ``SendInput`` (the recommended input-injection API) with absolute virtual-desktop
coordinates, which works in more contexts than ``SetCursorPos`` and respects a DPI-aware process.
Call :func:`set_dpi_aware` once before creating the GUI so screen metrics and cursor coordinates
are in real (physical) pixels; otherwise Windows silently rescales them on a scaled display.

All Windows-only imports are deferred into the functions so this module still imports on Linux
(e.g. CI), where every call is a safe no-op.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_ABSOLUTE = 0x8000
_MOUSEEVENTF_VIRTUALDESK = 0x4000

# Virtual-screen GetSystemMetrics indices.
_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79

_send_input = None  # cached (SendInput callable, INPUT factory)
_warned = False


def set_dpi_aware() -> None:
    """Make the process per-monitor DPI aware so pixel coordinates are physical, not scaled."""
    try:
        import ctypes

        try:
            # PER_MONITOR_AWARE_V2 (Win10+)
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            return
        except Exception:
            pass
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
            return
        except Exception:
            pass
        ctypes.windll.user32.SetProcessDPIAware()  # system-DPI aware (Vista+)
    except Exception as exc:  # non-Windows
        log.debug("could not set DPI awareness: %s", exc)


def screen_size() -> tuple[int, int] | None:
    """Primary-monitor size in physical pixels, or ``None`` if unavailable (non-Windows)."""
    try:
        import ctypes

        u = ctypes.windll.user32
        return int(u.GetSystemMetrics(0)), int(u.GetSystemMetrics(1))
    except Exception:
        return None


def _ensure_send_input():
    global _send_input
    if _send_input is not None:
        return _send_input
    import ctypes
    from ctypes import wintypes

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
        ]

    class _INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("mi", _MOUSEINPUT)]

        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    _send_input = (ctypes.windll.user32.SendInput, _INPUT, _MOUSEINPUT, ctypes)
    return _send_input


def move_to(x: int, y: int) -> None:
    """Move the pointer to the physical screen pixel ``(x, y)``. No-op (logged once) on failure."""
    global _warned
    try:
        send_input, INPUT, MOUSEINPUT, ctypes = _ensure_send_input()
        u = ctypes.windll.user32
        vx = u.GetSystemMetrics(_SM_XVIRTUALSCREEN)
        vy = u.GetSystemMetrics(_SM_YVIRTUALSCREEN)
        vw = u.GetSystemMetrics(_SM_CXVIRTUALSCREEN)
        vh = u.GetSystemMetrics(_SM_CYVIRTUALSCREEN)
        if vw <= 1 or vh <= 1:
            return
        nx = int((x - vx) * 65535 / (vw - 1))
        ny = int((y - vy) * 65535 / (vh - 1))
        inp = INPUT()
        inp.type = 0  # INPUT_MOUSE
        inp.mi = MOUSEINPUT(
            nx, ny, 0,
            _MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE | _MOUSEEVENTF_VIRTUALDESK,
            0, None,
        )
        send_input(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    except Exception as exc:
        if not _warned:
            _warned = True
            log.warning("could not move the OS mouse pointer: %s", exc)
