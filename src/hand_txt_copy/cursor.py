"""Camera-space to screen-space cursor mapping with One-Euro smoothing (PURE — no I/O).

The index fingertip's normalized position (0..1 in the camera frame) is mapped to a screen pixel,
after (a) trimming a configurable margin so the operator need not reach the frame edges and
(b) smoothing with a One-Euro filter, which gives low latency on fast moves and low jitter when
the hand is still.

Reference: Casiez, Roussel, Vogel, "1€ Filter" (CHI 2012).
"""

from __future__ import annotations

import math

from .config import CursorConfig


def _alpha(cutoff: float, dt: float) -> float:
    tau = 1.0 / (2.0 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


class _LowPass:
    def __init__(self) -> None:
        self._value: float | None = None

    def __call__(self, x: float, alpha: float) -> float:
        if self._value is None:
            self._value = x
        else:
            self._value = alpha * x + (1.0 - alpha) * self._value
        return self._value

    @property
    def last(self) -> float | None:
        return self._value


class OneEuroFilter:
    """One-Euro filter for a single scalar signal."""

    def __init__(self, min_cutoff: float, beta: float, d_cutoff: float = 1.0) -> None:
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._x = _LowPass()
        self._dx = _LowPass()
        self._last_x: float | None = None

    def __call__(self, x: float, dt: float) -> float:
        if dt <= 0:
            dt = 1e-3
        if self._last_x is None:
            dx = 0.0
        else:
            dx = (x - self._last_x) / dt
        self._last_x = x

        edx = self._dx(dx, _alpha(self.d_cutoff, dt))
        cutoff = self.min_cutoff + self.beta * abs(edx)
        return self._x(x, _alpha(cutoff, dt))


def _remap_axis(value: float, margin: float) -> float:
    """Map ``value`` in [margin, 1 - margin] to [0, 1], clamped."""
    span = 1.0 - 2.0 * margin
    if span <= 0:
        return min(max(value, 0.0), 1.0)
    scaled = (value - margin) / span
    return min(max(scaled, 0.0), 1.0)


class CursorMapper:
    """Map a normalized fingertip position to a screen pixel, with smoothing.

    ``screen_size`` is (width, height) in pixels. Landmarks are already mirrored upstream (the
    camera frame is flipped), so no additional x-inversion happens here.
    """

    def __init__(self, cfg: CursorConfig, screen_size: tuple[int, int]) -> None:
        self._cfg = cfg
        self._w, self._h = screen_size
        self._fx = OneEuroFilter(cfg.one_euro_min_cutoff, cfg.one_euro_beta, cfg.one_euro_d_cutoff)
        self._fy = OneEuroFilter(cfg.one_euro_min_cutoff, cfg.one_euro_beta, cfg.one_euro_d_cutoff)

    def map(self, norm_x: float, norm_y: float, dt: float) -> tuple[int, int]:
        """Return smoothed integer screen coordinates for a normalized fingertip position."""
        rx = _remap_axis(norm_x, self._cfg.margin_x)
        ry = _remap_axis(norm_y, self._cfg.margin_y)
        sx = self._fx(rx * self._w, dt)
        sy = self._fy(ry * self._h, dt)
        px = int(round(min(max(sx, 0), self._w - 1)))
        py = int(round(min(max(sy, 0), self._h - 1)))
        return px, py
