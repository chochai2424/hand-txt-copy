from __future__ import annotations

from conftest import fist, make_landmarks, open_palm, pinch, pointing

from hand_txt_copy.config import GesturesConfig
from hand_txt_copy.gestures import Gesture, GestureDetector, classify, pinch_distance


def cfg(**kw) -> GesturesConfig:
    return GesturesConfig(**kw)


def test_pinch_distance_small_when_pinching():
    assert pinch_distance(pinch()) < 0.05


def test_classify_point():
    assert classify(pointing(), cfg()) == Gesture.POINT


def test_classify_click_two_fingers():
    # Index + middle extended, ring + pinky curled, thumb away (not a pinch) => CLICK.
    lm = make_landmarks(index=True, middle=True)
    assert classify(lm, cfg()) == Gesture.CLICK


def test_point_is_not_click():
    assert classify(pointing(), cfg()) == Gesture.POINT


def test_classify_open_palm():
    assert classify(open_palm(), cfg()) == Gesture.OPEN_PALM


def test_classify_fist():
    assert classify(fist(), cfg()) == Gesture.FIST


def test_classify_pinch_takes_priority():
    # A pinch pose keeps the index extended, but pinch must win over point.
    assert classify(pinch(), cfg()) == Gesture.PINCH


def test_classify_none_without_hand():
    assert classify(None, cfg()) == Gesture.NONE


def test_debounce_requires_consecutive_frames():
    det = GestureDetector(cfg(debounce_frames=3))
    # First two point frames should not yet be "stable".
    assert det.update(pointing()) != Gesture.POINT
    assert det.update(pointing()) != Gesture.POINT
    assert det.update(pointing()) == Gesture.POINT


def test_pinch_hysteresis_latches_until_open():
    c = cfg(pinch_on_distance=0.05, pinch_off_distance=0.08, debounce_frames=1)
    det = GestureDetector(c)
    # Engage pinch.
    assert det.update(pinch()) == Gesture.PINCH

    # A pose whose thumb-index distance is between on (0.05) and off (0.08) must stay PINCH.
    from conftest import make_landmarks

    mid = make_landmarks(index=True, thumb_tip=(0.4, 0.46))  # ~0.06 from index tip (0.4,0.4)
    assert 0.05 < pinch_distance(mid) < 0.08
    assert det.update(mid) == Gesture.PINCH

    # Opening past the off-distance releases the latch.
    assert det.update(pointing()) == Gesture.POINT
