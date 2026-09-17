"""Windows clipboard writer.

Places both an image (``CF_DIB``) and text (``CF_UNICODETEXT``) on the clipboard in a single
open/empty/set sequence, so the paste target can choose whichever format it accepts. The Win32
calls are isolated behind a small ``_backend`` indirection so the format-building logic (BMP header
stripping) can be unit-tested without the native ``win32clipboard`` dependency.
"""

from __future__ import annotations

import io
import logging

from PIL import Image

log = logging.getLogger(__name__)

# BMP files start with a 14-byte BITMAPFILEHEADER; a DIB on the clipboard omits it.
_BMP_FILE_HEADER_SIZE = 14


def image_to_dib(image: Image.Image) -> bytes:
    """Convert a PIL image to a device-independent bitmap (DIB) byte string for ``CF_DIB``."""
    with io.BytesIO() as output:
        image.convert("RGB").save(output, "BMP")
        data = output.getvalue()
    return data[_BMP_FILE_HEADER_SIZE:]


class _Win32Backend:
    """Real backend calling into ``win32clipboard`` / ``win32con``."""

    def set_formats(self, dib: bytes | None, text: str | None) -> None:
        import win32clipboard as clip
        import win32con

        clip.OpenClipboard()
        try:
            clip.EmptyClipboard()
            if text:
                clip.SetClipboardData(win32con.CF_UNICODETEXT, text)
            if dib is not None:
                clip.SetClipboardData(win32con.CF_DIB, dib)
        finally:
            clip.CloseClipboard()


class Clipboard:
    """Writes text and/or image to the Windows clipboard together."""

    def __init__(self, backend: _Win32Backend | None = None) -> None:
        self._backend = backend or _Win32Backend()

    def set(self, image: Image.Image | None = None, text: str | None = None) -> None:
        """Place ``image`` and/or ``text`` on the clipboard. At least one should be provided."""
        if image is None and not text:
            log.warning("clipboard.set called with nothing to copy")
            return
        dib = image_to_dib(image) if image is not None else None
        self._backend.set_formats(dib, text or None)
        log.info(
            "copied to clipboard (image=%s, text=%s chars)",
            image is not None,
            len(text) if text else 0,
        )
