"""Selection-rectangle geometry (PURE — no I/O).

A :class:`Selection` is anchored at one screen point when a pinch begins and its far corner
follows the cursor until the pinch releases. It always yields a normalized rectangle (left, top,
width, height) with non-negative size, regardless of drag direction.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def area(self) -> int:
        return self.width * self.height

    def as_mss(self) -> dict[str, int]:
        """Return the dict shape ``mss`` expects for a region grab."""
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}


class Selection:
    """Tracks a drag from an anchor point to a moving point."""

    def __init__(self, anchor: tuple[int, int]) -> None:
        self._ax, self._ay = anchor
        self._bx, self._by = anchor

    def update(self, point: tuple[int, int]) -> None:
        self._bx, self._by = point

    def rect(self) -> Rect:
        left = min(self._ax, self._bx)
        top = min(self._ay, self._by)
        width = abs(self._bx - self._ax)
        height = abs(self._by - self._ay)
        return Rect(left, top, width, height)


MIN_SELECTION_PX = 5


def is_usable(rect: Rect, min_px: int = MIN_SELECTION_PX) -> bool:
    """True when the rectangle is large enough to be a deliberate selection, not a stray tap."""
    return rect.width >= min_px and rect.height >= min_px
