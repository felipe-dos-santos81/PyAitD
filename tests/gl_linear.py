# SPDX-License-Identifier: GPL-2.0-only
"""A numpy reference for GL_LINEAR magnification.

Shared by `test_plate` (which pins `plate.grain_retention`'s derivation
against it) and `test_render_gl` (which holds the composite's dither
against it): both need to say what the background filter actually does to
a source field, written out independently so the assertions are evidence
about the derivation rather than restatements of it."""
import numpy as np


def gl_linear_upscale(src, cell):
    """One channel magnified by an integer `cell` the way GL_LINEAR does:
    target pixel `j` samples the source at `(j + 0.5) / cell - 0.5`, with
    the two straddling texels weighted by the fractional part and the
    border clamped."""
    height, width = src.shape

    def taps(count):
        x = (np.arange(count * cell) + 0.5) / cell - 0.5
        lo = np.floor(x).astype(int)
        return np.clip(lo, 0, count - 1), np.clip(lo + 1, 0, count - 1), x - lo

    x0, x1, fx = taps(width)
    y0, y1, fy = taps(height)
    rows = src[:, x0] * (1.0 - fx) + src[:, x1] * fx
    return rows[y0, :] * (1.0 - fy)[:, None] + rows[y1, :] * fy[:, None]
