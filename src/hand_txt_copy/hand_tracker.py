"""MediaPipe Hands wrapper.

Turns a BGR camera frame into a ``(21, 3)`` numpy array of normalized landmarks (x, y in 0..1,
z relative depth), or ``None`` when no hand is detected. This is the only module that talks to
MediaPipe; everything downstream works on the numpy array.
"""

from __future__ import annotations

from enum import IntEnum

import numpy as np

from .config import HandTrackerConfig


class LANDMARK(IntEnum):
    """MediaPipe hand landmark indices (subset used by the app)."""

    WRIST = 0
    THUMB_CMC = 1
    THUMB_MCP = 2
    THUMB_IP = 3
    THUMB_TIP = 4
    INDEX_MCP = 5
    INDEX_PIP = 6
    INDEX_DIP = 7
    INDEX_TIP = 8
    MIDDLE_MCP = 9
    MIDDLE_PIP = 10
    MIDDLE_DIP = 11
    MIDDLE_TIP = 12
    RING_MCP = 13
    RING_PIP = 14
    RING_DIP = 15
    RING_TIP = 16
    PINKY_MCP = 17
    PINKY_PIP = 18
    PINKY_DIP = 19
    PINKY_TIP = 20


class HandTracker:
    """Thin wrapper around ``mediapipe.solutions.hands.Hands``.

    Import of mediapipe is deferred to construction so the pure modules (gestures, cursor) and
    their tests do not require the native dependency.
    """

    def __init__(self, cfg: HandTrackerConfig) -> None:
        import mediapipe as mp  # deferred import

        self._mp_hands = mp.solutions.hands
        self._hands = self._mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=cfg.max_num_hands,
            model_complexity=cfg.model_complexity,
            min_detection_confidence=cfg.min_detection_confidence,
            min_tracking_confidence=cfg.min_tracking_confidence,
        )

    def process(self, frame_bgr: np.ndarray) -> np.ndarray | None:
        """Return landmarks for the most prominent hand, or ``None`` if no hand is found.

        ``frame_bgr`` is an OpenCV BGR image; MediaPipe expects RGB, so we convert here.
        """
        import cv2

        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        frame_rgb.flags.writeable = False
        result = self._hands.process(frame_rgb)
        if not result.multi_hand_landmarks:
            return None
        hand = result.multi_hand_landmarks[0]
        return np.array([[lm.x, lm.y, lm.z] for lm in hand.landmark], dtype=np.float32)

    def close(self) -> None:
        self._hands.close()

    def __enter__(self) -> HandTracker:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
