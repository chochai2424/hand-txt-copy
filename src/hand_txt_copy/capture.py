"""Screen region capture via ``mss``.

Grabs a rectangle of the screen and returns it as a PIL image (RGB), ready for OCR and for
conversion to a clipboard DIB.
"""

from __future__ import annotations

import logging

from PIL import Image

from .config import ScreenConfig
from .selection import Rect

log = logging.getLogger(__name__)


class ScreenCapture:
    """Wraps an ``mss`` instance. Not thread-safe; use from the main loop only."""

    def __init__(self, cfg: ScreenConfig) -> None:
        import mss

        self._cfg = cfg
        self._sct = mss.mss()

    def monitor_size(self) -> tuple[int, int]:
        """Return (width, height) of the configured monitor, for cursor mapping."""
        mon = self._sct.monitors[self._cfg.monitor]
        return mon["width"], mon["height"]

    def monitor_origin(self) -> tuple[int, int]:
        """Top-left (left, top) of the configured monitor in virtual-desktop coordinates."""
        mon = self._sct.monitors[self._cfg.monitor]
        return mon["left"], mon["top"]

    def grab(self, rect: Rect) -> Image.Image:
        """Screenshot ``rect`` (given in monitor-local pixels) and return an RGB PIL image."""
        origin_x, origin_y = self.monitor_origin()
        region = {
            "left": rect.left + origin_x,
            "top": rect.top + origin_y,
            "width": rect.width,
            "height": rect.height,
        }
        raw = self._sct.grab(region)
        img = Image.frombytes("RGB", raw.size, raw.rgb)
        log.debug("captured region %s", region)
        return img

    def close(self) -> None:
        self._sct.close()
