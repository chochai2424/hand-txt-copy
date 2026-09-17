from __future__ import annotations

from PIL import Image

from hand_txt_copy.clipboard import Clipboard, image_to_dib


class FakeBackend:
    def __init__(self):
        self.calls = []

    def set_formats(self, dib, text):
        self.calls.append((dib, text))


def test_image_to_dib_strips_bmp_file_header():
    img = Image.new("RGB", (4, 4), (255, 0, 0))
    dib = image_to_dib(img)
    # A DIB starts with the BITMAPINFOHEADER whose first 4 bytes are its size (40) little-endian.
    assert dib[:4] == (40).to_bytes(4, "little")


def test_set_both_formats():
    backend = FakeBackend()
    Clipboard(backend).set(image=Image.new("RGB", (2, 2)), text="ABC")
    assert len(backend.calls) == 1
    dib, text = backend.calls[0]
    assert dib is not None
    assert text == "ABC"


def test_set_text_only():
    backend = FakeBackend()
    Clipboard(backend).set(text="hello")
    dib, text = backend.calls[0]
    assert dib is None
    assert text == "hello"


def test_set_nothing_is_noop():
    backend = FakeBackend()
    Clipboard(backend).set()
    assert backend.calls == []
