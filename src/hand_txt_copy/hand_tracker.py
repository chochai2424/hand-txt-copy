"""MediaPipe hand tracking (Tasks API).

Turns a BGR camera frame into a ``(21, 3)`` numpy array of normalized landmarks (x, y in 0..1,
z relative depth), or ``None`` when no hand is detected. This is the only module that talks to
MediaPipe; everything downstream works on the numpy array.

Current MediaPipe (0.10.x/1.x on PyPI) ships only the **Tasks** API — the legacy
``mediapipe.solutions.hands`` module has been removed — so this uses
``mediapipe.tasks.python.vision.HandLandmarker``, which needs a ``hand_landmarker.task`` model
file (downloaded on first use, path configurable). The MediaPipe/Tasks import is deferred to
construction so the pure modules (gestures, cursor) and their tests do not require the native
dependency.
"""

from __future__ import annotations

import logging
import time
import urllib.request
from enum import IntEnum
from pathlib import Path

import numpy as np

from .config import HandTrackerConfig

log = logging.getLogger(__name__)

# Model published by Google; downloaded once to HandTrackerConfig.model_path if missing.
_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)


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


# The standard MediaPipe hand skeleton (21 bones). Hardcoded so drawing code (calibration,
# console) needs no MediaPipe import and CI stays light. Matches Tasks' HandLandmarksConnections.
HAND_CONNECTIONS: tuple[tuple[int, int], ...] = (
    (0, 1), (1, 2), (2, 3), (3, 4),           # thumb
    (0, 5), (5, 6), (6, 7), (7, 8),           # index
    (5, 9), (9, 10), (10, 11), (11, 12),      # middle
    (9, 13), (13, 14), (14, 15), (15, 16),    # ring
    (13, 17), (17, 18), (18, 19), (19, 20),   # pinky
    (0, 17),                                  # palm base
)


def ensure_model(model_path: str | Path, url: str = _MODEL_URL) -> Path:
    """Return the model path, downloading the ``.task`` file once if it is not present."""
    path = Path(model_path)
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    log.info("downloading hand landmarker model to %s", path)
    try:
        urllib.request.urlretrieve(url, path)  # noqa: S310 (fixed https Google URL)
    except Exception as exc:
        raise RuntimeError(
            f"could not download the hand model from {url} ({exc}). Download it manually and set "
            f"hand_tracker.model_path in the config to its location."
        ) from exc
    return path


class HandTracker:
    """Wrapper around the MediaPipe Tasks ``HandLandmarker`` in VIDEO mode."""

    def __init__(self, cfg: HandTrackerConfig) -> None:
        import mediapipe as mp
        from mediapipe.tasks.python import vision
        from mediapipe.tasks.python.core.base_options import BaseOptions

        self._mp = mp
        self._vision = vision
        model = ensure_model(cfg.model_path)
        options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=cfg.max_num_hands,
            min_hand_detection_confidence=cfg.min_detection_confidence,
            min_hand_presence_confidence=cfg.min_hand_presence_confidence,
            min_tracking_confidence=cfg.min_tracking_confidence,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)
        self._t0 = time.perf_counter()

    def process(self, frame_bgr: np.ndarray) -> np.ndarray | None:
        """Return landmarks for the most prominent hand, or ``None`` if no hand is found.

        ``frame_bgr`` is an OpenCV BGR image; MediaPipe expects RGB.
        """
        import cv2

        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=frame_rgb)
        timestamp_ms = int((time.perf_counter() - self._t0) * 1000)
        result = self._landmarker.detect_for_video(mp_image, timestamp_ms)
        if not result.hand_landmarks:
            return None
        hand = result.hand_landmarks[0]
        return np.array([[lm.x, lm.y, lm.z] for lm in hand], dtype=np.float32)

    def close(self) -> None:
        self._landmarker.close()

    def __enter__(self) -> HandTracker:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
