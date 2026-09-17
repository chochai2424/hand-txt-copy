from __future__ import annotations

from hand_txt_copy.config import CursorConfig
from hand_txt_copy.cursor import CursorMapper, OneEuroFilter, _remap_axis


def test_remap_axis_trims_margin():
    # With a 0.2 margin, the active range is [0.2, 0.8] -> [0, 1].
    assert _remap_axis(0.2, 0.2) == 0.0
    assert _remap_axis(0.8, 0.2) == 1.0
    assert abs(_remap_axis(0.5, 0.2) - 0.5) < 1e-6


def test_remap_axis_clamps():
    assert _remap_axis(0.0, 0.2) == 0.0
    assert _remap_axis(1.0, 0.2) == 1.0


def test_cursor_maps_center_to_screen_center():
    cfg = CursorConfig(margin_x=0.1, margin_y=0.1, one_euro_min_cutoff=1000.0, one_euro_beta=1.0)
    mapper = CursorMapper(cfg, (1920, 1080))
    # High cutoff => almost no smoothing lag, so a centered fingertip lands near screen center.
    x, y = mapper.map(0.5, 0.5, dt=1.0)
    assert abs(x - 960) <= 2
    assert abs(y - 540) <= 2


def test_cursor_stays_in_bounds():
    cfg = CursorConfig()
    mapper = CursorMapper(cfg, (800, 600))
    x, y = mapper.map(2.0, -1.0, dt=1.0)  # out-of-range input
    assert 0 <= x < 800
    assert 0 <= y < 600


def test_one_euro_smooths_toward_signal():
    f = OneEuroFilter(min_cutoff=1.0, beta=0.0)
    out = [f(10.0, dt=1.0) for _ in range(20)]
    # First sample initializes to the input; then it converges back toward the constant signal.
    assert abs(out[-1] - 10.0) < 1e-3
