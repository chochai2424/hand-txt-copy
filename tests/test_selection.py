from __future__ import annotations

from hand_txt_copy.selection import Rect, Selection, is_usable


def test_selection_normalizes_direction():
    # Drag from bottom-right up to top-left; rect must still have positive size.
    sel = Selection((100, 100))
    sel.update((40, 30))
    rect = sel.rect()
    assert rect == Rect(left=40, top=30, width=60, height=70)


def test_rect_geometry():
    rect = Rect(10, 20, 30, 40)
    assert rect.right == 40
    assert rect.bottom == 60
    assert rect.area == 1200
    assert rect.as_mss() == {"left": 10, "top": 20, "width": 30, "height": 40}


def test_is_usable_rejects_tiny():
    assert not is_usable(Rect(0, 0, 2, 2))
    assert is_usable(Rect(0, 0, 50, 50))
