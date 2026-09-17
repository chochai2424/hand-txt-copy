"""Send a paste action to the currently focused application.

Two modes (from ``PasteConfig``):
- ``clipboard``: send the configured keystroke (default Ctrl+V) so the focused app pastes whatever
  is on the clipboard (image or text, its choice).
- ``type``: type the given text directly, for fields that reject image/clipboard paste.

The overlay window must not hold keyboard focus for this to reach the intended app.
"""

from __future__ import annotations

import logging

from .config import PasteConfig

log = logging.getLogger(__name__)


class Paster:
    def __init__(self, cfg: PasteConfig) -> None:
        self._cfg = cfg

    def paste(self, text: str | None = None) -> None:
        """Perform the paste according to the configured mode."""
        import pyautogui

        if self._cfg.mode == "type" and text:
            pyautogui.typewrite(text)
            log.info("typed %d chars into focused app", len(text))
            return

        keys = self._cfg.keystroke.split("+")
        pyautogui.hotkey(*keys)
        log.info("sent %s to focused app", self._cfg.keystroke)
