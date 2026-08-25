# SPDX-License-Identifier: GPL-2.0-only
"""Mask rasterization port of FITD polys.cpp fillpoly + main.cpp createAITD1Mask."""
from dataclasses import dataclass

from PyAitD.mask_geometry import _polygons_bbox, iter_mask_records

import numpy as np

SCREEN_W, SCREEN_H = 320, 200


@dataclass
class Mask:
    x1: int
    y1: int
    x2: int
    y2: int
    bitmap: np.ndarray  # (200, 320) uint8, 255 = occluded
    viewed_room: int = -1
    test_rects: tuple = ()  # actor-space (x1, z1, x2, z2) activation boxes


def _putdot(dots, h, x, y):
    if 0 <= y < h:
        dots[y].append(x)


def fill_poly(points, target, value):
    # faithful FITD fillpoly port: scanline edge-dot accumulation with the
    # dir state machine for horizontal edges and the closing-edge extra dot.
    # Note: C casts float->int with truncation; int(curx + 0.5) matches.
    h, w = target.shape
    dots = [[] for _ in range(h)]
    n = len(points)
    if n == 0:
        return
    if n == 1:
        x, y = points[0]
        _putdot(dots, h, x, y)
        # single dot fills one pixel
        if 0 <= y < h:
            target[y, max(0, min(w - 1, x))] = value
        return
    dir_flag = -2
    x2, y2 = points[-1]
    for i in range(n):
        x1, y1 = x2, y2
        x2, y2 = points[i]
        if y1 == y2:
            if not dir_flag:
                continue
            _putdot(dots, h, x1, y1)
            dir_flag = 0
            continue
        step = (x2 - x1) / (y2 - y1)
        curx = x1
        if y1 < y2:
            for j in range(y1, y2):
                _putdot(dots, h, int(curx + 0.5), j)
                curx += step
            if dir_flag == -1:
                _putdot(dots, h, x1, y1)
            dir_flag = 1
        else:
            for j in range(y1, y2, -1):
                _putdot(dots, h, int(curx + 0.5), j)
                curx -= step
            if dir_flag == 1:
                _putdot(dots, h, x1, y1)
            dir_flag = -1
    # FITD closing-edge extra dot
    x1, y1 = x2, y2
    x2, y2 = points[0]
    if (y1 < y2 and dir_flag == -1) or (y1 > y2 and dir_flag == 1) or (y1 == y2 and dir_flag == 0):
        _putdot(dots, h, x1, y1)
    for y in range(h):
        row = sorted(dots[y])
        for j in range(0, len(row) - 1, 2):
            x_a = max(0, min(w - 1, row[j]))
            x_b = max(0, min(w - 1, row[j + 1]))
            if x_a <= x_b:
                target[y, x_a : x_b + 1] = value


def create_aitd1_mask(camera_raw, camera_off):
    masks = []
    for vr_room, test_rects, polygons in iter_mask_records(camera_raw, camera_off):
        bitmap = np.zeros((SCREEN_H, SCREEN_W), dtype=np.uint8)
        for points in polygons:
            fill_poly(points, bitmap, 255)
        min_x, min_y, max_x, max_y = _polygons_bbox(polygons)
        masks.append(Mask(
            min_x, min_y, max_x, max_y, bitmap,
            viewed_room=vr_room, test_rects=test_rects,
        ))
    return masks
