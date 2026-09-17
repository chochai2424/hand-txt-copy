"""OCR of a captured region via Tesseract (pytesseract wrapper).

``pytesseract`` is only a wrapper around the Tesseract executable, which must be installed
separately on the station. If it is missing, OCR degrades gracefully to an empty string and logs
a warning rather than crashing the copy flow (the image is still placed on the clipboard).
"""

from __future__ import annotations

import logging

from PIL import Image

from .config import OcrConfig

log = logging.getLogger(__name__)


class OcrEngine:
    def __init__(self, cfg: OcrConfig) -> None:
        self._cfg = cfg
        if cfg.enabled and cfg.tesseract_cmd:
            import pytesseract

            pytesseract.pytesseract.tesseract_cmd = cfg.tesseract_cmd

    def read_text(self, image: Image.Image) -> str:
        """Return recognized text (stripped), or '' if OCR is disabled or unavailable."""
        if not self._cfg.enabled:
            return ""
        try:
            import pytesseract

            text = pytesseract.image_to_string(image, lang=self._cfg.language)
            return text.strip()
        except Exception as exc:  # tesseract missing / language pack absent / decode error
            log.warning("OCR failed (%s); copying image only", exc)
            return ""
