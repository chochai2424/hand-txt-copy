"""Shared test helpers: synthetic MediaPipe-style landmark builders.

Landmarks are a (21, 3) array in normalized space; image y grows downward, so an *extended*
finger has tip.y < pip.y. We only need to set the joints that gestures.py inspects.
"""

from __future__ import annotations

import numpy as np

from hand_txt_copy.hand_tracker import LANDMARK

_FINGERS = {
    "index": (LANDMARK.INDEX_TIP, LANDMARK.INDEX_PIP),
    "middle": (LANDMARK.MIDDLE_TIP, LANDMARK.MIDDLE_PIP),
    "ring": (LANDMARK.RING_TIP, LANDMARK.RING_PIP),
    "pinky": (LANDMARK.PINKY_TIP, LANDMARK.PINKY_PIP),
}


def make_landmarks(
    *,
    index: bool = False,
    middle: bool = False,
    ring: bool = False,
    pinky: bool = False,
    thumb_tip: tuple[float, float] = (0.2, 0.6),
) -> np.ndarray:
    """Build landmarks with the given fingers extended and an explicit thumb-tip position."""
    lm = np.full((21, 3), 0.5, dtype=np.float32)
    extended = {"index": index, "middle": middle, "ring": ring, "pinky": pinky}
    for i, name in enumerate(_FINGERS):
        tip, pip = _FINGERS[name]
        x = 0.4 + i * 0.05
        lm[pip] = (x, 0.5, 0.0)
        lm[tip] = (x, 0.4 if extended[name] else 0.6, 0.0)
    lm[LANDMARK.THUMB_TIP] = (thumb_tip[0], thumb_tip[1], 0.0)
    return lm


def pointing() -> np.ndarray:
    return make_landmarks(index=True)


def open_palm() -> np.ndarray:
    return make_landmarks(index=True, middle=True, ring=True, pinky=True)


def fist() -> np.ndarray:
    return make_landmarks()


def pinch() -> np.ndarray:
    # Thumb tip placed on top of the index tip (index tip is at x=0.4, y=0.4 when extended).
    return make_landmarks(index=True, thumb_tip=(0.41, 0.41))
