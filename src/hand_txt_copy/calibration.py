"""Live calibration UI for tuning gesture and cursor parameters at the station.

Runs a preview window (OpenCV highgui — no extra dependency) showing the camera feed with the
detected hand skeleton, the live thumb-index pinch distance, the currently classified gesture, and
the cursor **active region** implied by the margin settings. Trackbars adjust the parameters in
real time; the operator watches the effect and saves a per-station config file.

This is an I/O tool that *reuses* the pure logic (`gestures`, cursor margins) — it does not
reimplement any thresholds.

Keys:
    s   save the current settings to the output config path
    a   auto-set pinch thresholds from the hand held in front of the camera *now*
    q / Esc   quit without saving
"""

from __future__ import annotations

import logging
import time
from collections import deque

import numpy as np

from .camera import Camera
from .config import Config, save_config
from .cursor import CursorMapper, _remap_axis
from .gestures import Gesture, classify, pinch_distance
from .hand_tracker import LANDMARK, HandTracker

log = logging.getLogger(__name__)

_WINDOW = "hand-txt-copy calibration"

# Trackbar spec: (label, config path, scale, max_slider). Stored value = slider / scale.
_TRACKBARS = [
    ("pinch on x1000", ("gestures", "pinch_on_distance"), 1000, 200),
    ("pinch off x1000", ("gestures", "pinch_off_distance"), 1000, 300),
    ("margin x x100", ("cursor", "margin_x"), 100, 49),
    ("margin y x100", ("cursor", "margin_y"), 100, 49),
    ("min_cutoff x100", ("cursor", "one_euro_min_cutoff"), 100, 1000),
    ("beta x100000", ("cursor", "one_euro_beta"), 100000, 2000),
    ("debounce", ("gestures", "debounce_frames"), 1, 10),
]

_GESTURE_COLOR = {
    Gesture.PINCH: (0, 200, 255),
    Gesture.POINT: (0, 255, 0),
    Gesture.OPEN_PALM: (255, 200, 0),
    Gesture.FIST: (0, 0, 255),
    Gesture.NONE: (160, 160, 160),
}


def _get(cfg: Config, path: tuple[str, str]) -> float:
    return getattr(getattr(cfg, path[0]), path[1])


def _set(cfg: Config, path: tuple[str, str], value: float) -> None:
    setattr(getattr(cfg, path[0]), path[1], value)


def _draw_landmarks(frame: np.ndarray, landmarks: np.ndarray, connections) -> None:
    import cv2

    h, w = frame.shape[:2]
    pts = [(int(x * w), int(y * h)) for x, y, _ in landmarks]
    for a, b in connections:
        cv2.line(frame, pts[a], pts[b], (0, 180, 0), 2)
    for p in pts:
        cv2.circle(frame, p, 4, (0, 255, 0), -1)
    # Highlight the thumb tip and index tip (the pinch pair).
    cv2.circle(frame, pts[LANDMARK.THUMB_TIP], 8, (0, 200, 255), 2)
    cv2.circle(frame, pts[LANDMARK.INDEX_TIP], 8, (0, 200, 255), 2)
    cv2.line(frame, pts[LANDMARK.THUMB_TIP], pts[LANDMARK.INDEX_TIP], (0, 200, 255), 1)


def _draw_active_region(frame: np.ndarray, margin_x: float, margin_y: float) -> None:
    import cv2

    h, w = frame.shape[:2]
    x0, y0 = int(margin_x * w), int(margin_y * h)
    x1, y1 = int((1 - margin_x) * w), int((1 - margin_y) * h)
    cv2.rectangle(frame, (x0, y0), (x1, y1), (255, 200, 0), 1)
    cv2.putText(
        frame, "active region", (x0 + 4, y0 + 18),
        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 1, cv2.LINE_AA
    )


def _screen_size(cfg: Config) -> tuple[int, int]:
    """Real monitor size (so the One-Euro feel matches the app), with a safe fallback."""
    try:
        from .capture import ScreenCapture

        sc = ScreenCapture(cfg.screen)
        size = sc.monitor_size()
        sc.close()
        return size
    except Exception as exc:  # mss unavailable / headless
        log.debug("using fallback screen size for preview: %s", exc)
        return (1920, 1080)


def _draw_cursor_preview(
    frame: np.ndarray,
    raw_screen: tuple[float, float],
    smooth_screen: tuple[int, int],
    trail: deque[tuple[int, int]],
    screen_size: tuple[int, int],
) -> None:
    """Draw the raw target vs. the smoothed cursor (mapped from screen space into the preview).

    Red hollow ring = where the cursor would be with no smoothing (the true fingertip target).
    Blue dot + trail = the One-Euro-smoothed cursor. The gap is *lag*; a trembling dot under a
    steady hand is *jitter*.
    """
    import cv2

    h, w = frame.shape[:2]
    sw, sh = screen_size

    def to_frame(p: tuple[float, float]) -> tuple[int, int]:
        return (int(p[0] / sw * w), int(p[1] / sh * h))

    rp = to_frame(raw_screen)
    sp = to_frame((float(smooth_screen[0]), float(smooth_screen[1])))

    trail.append(sp)
    for i in range(1, len(trail)):
        cv2.line(frame, trail[i - 1], trail[i], (255, 120, 0), 1, cv2.LINE_AA)

    cv2.circle(frame, rp, 11, (0, 0, 255), 1, cv2.LINE_AA)      # raw target
    cv2.line(frame, rp, sp, (0, 0, 255), 1, cv2.LINE_AA)         # lag gap
    cv2.circle(frame, sp, 7, (255, 120, 0), -1, cv2.LINE_AA)     # smoothed cursor


def _draw_hud(frame: np.ndarray, lines: list[tuple[str, tuple[int, int, int]]]) -> None:
    import cv2

    y = 24
    for text, color in lines:
        cv2.putText(frame, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(frame, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1, cv2.LINE_AA)
        y += 26


def run_calibration(cfg: Config, out_path: str) -> int:
    """Run the interactive calibration loop; return a process exit code."""
    import cv2

    cv2.namedWindow(_WINDOW, cv2.WINDOW_NORMAL)
    for label, path, scale, maximum in _TRACKBARS:
        init = int(round(_get(cfg, path) * scale))
        cv2.createTrackbar(label, _WINDOW, min(init, maximum), maximum, lambda _v: None)

    camera = Camera(cfg.camera)
    tracker = HandTracker(cfg.hand_tracker)
    import mediapipe as mp

    connections = mp.solutions.hands.HAND_CONNECTIONS

    screen_size = _screen_size(cfg)
    mapper = CursorMapper(cfg.cursor, screen_size)
    mapper_key = (cfg.cursor.one_euro_min_cutoff, cfg.cursor.one_euro_beta)
    trail: deque[tuple[int, int]] = deque(maxlen=32)

    camera.start()
    log.info("calibration started; keys: [s]ave  [a]uto-pinch  [q]uit")
    status = "adjust sliders, then press 's' to save"
    last = time.perf_counter()
    fps = 0.0
    try:
        while True:
            # Pull current slider values into the config object.
            for label, path, scale, _maximum in _TRACKBARS:
                raw = cv2.getTrackbarPos(label, _WINDOW)
                value = raw / scale if scale != 1 else raw
                if path[1] == "debounce_frames":
                    value = max(1, int(raw))
                _set(cfg, path, value)

            frame = camera.read()
            if frame is None:
                if cv2.waitKey(10) & 0xFF in (ord("q"), 27):
                    break
                continue

            now = time.perf_counter()
            dt = now - last
            last = now
            if dt > 0:
                fps = 0.9 * fps + 0.1 * (1.0 / dt)

            # Rebuild the filter only when the One-Euro parameters change (margins are read live),
            # otherwise the smoothing state would reset every frame and hide the real behaviour.
            key = (cfg.cursor.one_euro_min_cutoff, cfg.cursor.one_euro_beta)
            if key != mapper_key:
                mapper = CursorMapper(cfg.cursor, screen_size)
                mapper_key = key
                trail.clear()

            landmarks = tracker.process(frame)
            _draw_active_region(frame, cfg.cursor.margin_x, cfg.cursor.margin_y)

            dist_txt = "pinch dist: --"
            gesture = Gesture.NONE
            if landmarks is not None:
                _draw_landmarks(frame, landmarks, connections)
                dist = pinch_distance(landmarks)
                gesture = classify(landmarks, cfg.gestures)
                dist_txt = f"pinch dist: {dist:.3f}  (on<{cfg.gestures.pinch_on_distance:.3f})"

                nx, ny = float(landmarks[LANDMARK.INDEX_TIP, 0]), float(landmarks[LANDMARK.INDEX_TIP, 1])
                raw_screen = (
                    _remap_axis(nx, cfg.cursor.margin_x) * screen_size[0],
                    _remap_axis(ny, cfg.cursor.margin_y) * screen_size[1],
                )
                smooth_screen = mapper.map(nx, ny, dt)
                _draw_cursor_preview(frame, raw_screen, smooth_screen, trail, screen_size)
            else:
                trail.clear()

            _draw_hud(
                frame,
                [
                    (f"gesture: {gesture.value}", _GESTURE_COLOR[gesture]),
                    (dist_txt, (255, 255, 255)),
                    (
                        f"margins: x={cfg.cursor.margin_x:.2f} y={cfg.cursor.margin_y:.2f}  "
                        f"min_cutoff={cfg.cursor.one_euro_min_cutoff:.2f} "
                        f"beta={cfg.cursor.one_euro_beta:.5f}",
                        (255, 255, 255),
                    ),
                    ("cursor preview: red ring=raw target  blue dot=smoothed (gap=lag)", (255, 160, 60)),
                    (f"{status}   |   {fps:4.1f} fps", (0, 255, 255)),
                ],
            )

            cv2.imshow(_WINDOW, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("a") and landmarks is not None:
                status = _auto_pinch(cfg, pinch_distance(landmarks))
                _sync_trackbars(cfg)
            if key == ord("s"):
                status = _save(cfg, out_path)
    finally:
        camera.stop()
        tracker.close()
        cv2.destroyAllWindows()
    return 0


def _auto_pinch(cfg: Config, dist: float) -> str:
    """Set pinch thresholds from a currently-held pinch: engage tight, release wider (hysteresis)."""
    on = round(max(0.02, dist * 1.6), 3)
    off = round(max(on + 0.02, dist * 2.6), 3)
    cfg.gestures.pinch_on_distance = on
    cfg.gestures.pinch_off_distance = off
    log.info("auto pinch: on=%.3f off=%.3f (from held distance %.3f)", on, off, dist)
    return f"auto pinch set: on={on:.3f} off={off:.3f}"


def _sync_trackbars(cfg: Config) -> None:
    import cv2

    for label, path, scale, maximum in _TRACKBARS:
        value = int(round(_get(cfg, path) * scale))
        cv2.setTrackbarPos(label, _WINDOW, min(value, maximum))


def _save(cfg: Config, out_path: str) -> str:
    try:
        save_config(cfg, out_path)
        log.info("saved calibrated config to %s", out_path)
        return f"saved -> {out_path}"
    except Exception as exc:  # invalid combination (e.g. on >= off)
        log.warning("save failed: %s", exc)
        return f"save failed: {exc}"
