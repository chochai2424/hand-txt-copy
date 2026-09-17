"""Gesture recognition from hand landmarks (PURE — no I/O).

Given a ``(21, 3)`` numpy landmark array (MediaPipe normalized space), classify the current hand
pose into a :class:`Gesture`, and expose a :class:`GestureDetector` that adds temporal debouncing
and pinch hysteresis so downstream state transitions do not flicker frame-to-frame.

Everything here is deterministic and testable from saved landmark fixtures.
"""

from __future__ import annotations

from enum import Enum

import numpy as np

from .config import GesturesConfig
from .hand_tracker import LANDMARK

# Fingertip / PIP joint pairs used to decide whether a finger is extended.
_FINGER_TIP_PIP = {
    "index": (LANDMARK.INDEX_TIP, LANDMARK.INDEX_PIP),
    "middle": (LANDMARK.MIDDLE_TIP, LANDMARK.MIDDLE_PIP),
    "ring": (LANDMARK.RING_TIP, LANDMARK.RING_PIP),
    "pinky": (LANDMARK.PINKY_TIP, LANDMARK.PINKY_PIP),
}


class Gesture(Enum):
    NONE = "none"          # no hand / unrecognized
    POINT = "point"        # index extended, other fingers curled
    CLICK = "click"        # index + middle extended (two-finger), ring + pinky curled
    PINCH = "pinch"        # thumb tip and index tip close together
    OPEN_PALM = "palm"     # all four fingers extended
    FIST = "fist"          # all fingers curled


def pinch_distance(landmarks: np.ndarray) -> float:
    """Euclidean distance (normalized units) between the thumb tip and index fingertip."""
    thumb = landmarks[LANDMARK.THUMB_TIP, :2]
    index = landmarks[LANDMARK.INDEX_TIP, :2]
    return float(np.linalg.norm(thumb - index))


def _finger_extended(landmarks: np.ndarray, tip: int, pip: int) -> bool:
    """A finger is 'extended' when its tip is above (smaller y than) its PIP joint.

    Image y grows downward, so an upright extended finger has tip.y < pip.y.
    """
    return bool(landmarks[tip, 1] < landmarks[pip, 1])


def extended_fingers(landmarks: np.ndarray) -> dict[str, bool]:
    """Return which of index/middle/ring/pinky are extended (thumb handled separately)."""
    return {
        name: _finger_extended(landmarks, tip, pip)
        for name, (tip, pip) in _FINGER_TIP_PIP.items()
    }


def classify(landmarks: np.ndarray | None, cfg: GesturesConfig) -> Gesture:
    """Classify a single frame's landmarks into a :class:`Gesture` (no temporal state).

    Pinch is checked first because a pinch pose can otherwise read as a point.
    """
    if landmarks is None:
        return Gesture.NONE

    if pinch_distance(landmarks) < cfg.pinch_on_distance:
        return Gesture.PINCH

    ext = extended_fingers(landmarks)
    count = sum(ext.values())

    if ext["index"] and not ext["middle"] and not ext["ring"] and not ext["pinky"]:
        return Gesture.POINT
    if ext["index"] and ext["middle"] and not ext["ring"] and not ext["pinky"]:
        return Gesture.CLICK
    if count >= 4:
        return Gesture.OPEN_PALM
    if count == 0:
        return Gesture.FIST
    return Gesture.NONE


class GestureDetector:
    """Stateful wrapper adding debounce (N consecutive frames) and pinch hysteresis.

    - A raw gesture must repeat for ``debounce_frames`` frames before it becomes the stable output.
    - Once pinching, releasing requires the thumb-index distance to open past
      ``pinch_off_distance`` (wider than the engage threshold), preventing flicker at the boundary.
    """

    def __init__(self, cfg: GesturesConfig) -> None:
        self._cfg = cfg
        self._pinching = False
        self._candidate: Gesture = Gesture.NONE
        self._candidate_count = 0
        self._stable: Gesture = Gesture.NONE

    @property
    def stable(self) -> Gesture:
        return self._stable

    def update(self, landmarks: np.ndarray | None) -> Gesture:
        """Feed one frame's landmarks; return the current stable gesture."""
        raw = self._apply_pinch_hysteresis(landmarks)

        if raw == self._candidate:
            self._candidate_count += 1
        else:
            self._candidate = raw
            self._candidate_count = 1

        if self._candidate_count >= self._cfg.debounce_frames:
            self._stable = self._candidate
        return self._stable

    def _apply_pinch_hysteresis(self, landmarks: np.ndarray | None) -> Gesture:
        """Resolve the raw gesture, keeping PINCH latched until the hand opens past the off-distance."""
        if landmarks is None:
            self._pinching = False
            return Gesture.NONE

        dist = pinch_distance(landmarks)
        if self._pinching:
            if dist > self._cfg.pinch_off_distance:
                self._pinching = False
            else:
                return Gesture.PINCH
        else:
            if dist < self._cfg.pinch_on_distance:
                self._pinching = True
                return Gesture.PINCH

        return classify(landmarks, self._cfg)
