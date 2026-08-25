# SPDX-License-Identifier: GPL-2.0-only
"""Export the original camera backgrounds for external (AI) regeneration.

Pure numpy: no pygame, no moderngl. PNG encoding lives in
tools/export_backgrounds.py. See docs/ai-background-regeneration.md.
"""
import hashlib

import numpy as np

W, H = 320, 200


def draw_polyline(img, points, rgb, closed=False):
    """Draw 1px Bresenham segments through `points` ((x, y) floats, rounded)
    into `img` (H, W, 3) in place, clipping every pixel to the image."""
    pts = [(int(round(x)), int(round(y))) for x, y in points]
    if not pts:
        return
    if closed and len(pts) > 1:
        pts = pts + [pts[0]]
    if len(pts) == 1:
        pts = pts + [pts[0]]
    h, w = img.shape[:2]
    color = np.array(rgb, dtype=np.uint8)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        x, y = x0, y0
        while True:
            if 0 <= x < w and 0 <= y < h:
                img[y, x] = color
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy


def nearest_upscale(img, scale):
    """Integer nearest-neighbour upscale; always returns a fresh C-contiguous array."""
    out = np.repeat(np.repeat(img, scale, axis=0), scale, axis=1)
    return np.ascontiguousarray(out)


def sha256_rgb(pixels):
    """Hex digest over the raw (H, W, 3) uint8 bytes in row-major order --
    independent of the PNG encoder that later wrote or read them."""
    return hashlib.sha256(np.ascontiguousarray(pixels, dtype=np.uint8).tobytes()).hexdigest()
