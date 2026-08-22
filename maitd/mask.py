# SPDX-License-Identifier: GPL-2.0-only
"""Mask rasterization port of FITD polys.cpp fillpoly + main.cpp createAITD1Mask."""
import struct
from dataclasses import dataclass

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


def _s16(buf, off):
    v = struct.unpack_from("<H", buf, off)[0]
    return v - 0x10000 if v & 0x8000 else v


def create_aitd1_mask(camera_raw, camera_off):
    masks = []
    num_viewed = struct.unpack_from("<H", camera_raw, camera_off + 0x12)[0]
    for viewed in range(num_viewed):
        vr_off = camera_off + 0x14 + viewed * 0x0C
        vr_room = struct.unpack_from("<h", camera_raw, vr_off)[0]
        mask_off = struct.unpack_from("<H", camera_raw, vr_off + 2)[0]
        base = camera_off + mask_off
        data2 = camera_raw[base:]
        num_mask = struct.unpack_from("<h", data2, 0)[0]
        data = 2  # skip numMask
        for _ in range(num_mask):
            num_zones = struct.unpack_from("<H", data2, data)[0]
            test_rects = tuple(
                struct.unpack_from("<4h", data2, data + 4 + zone * 8)
                for zone in range(num_zones)
            )
            # FITD: src = data2 + u16(data+2) — the offset value is relative to data2
            poly_off = struct.unpack_from("<H", data2, data + 2)[0]
            src = camera_raw[base + poly_off :]
            num_polys = struct.unpack_from("<H", src, 0)[0]
            off = 2
            min_x, max_x, min_y, max_y = 319, 0, 199, 0
            bitmap = np.zeros((SCREEN_H, SCREEN_W), dtype=np.uint8)
            for _ in range(num_polys):
                num_points = struct.unpack_from("<H", src, off)[0]
                off += 2
                points = [
                    (_s16(src, off + k * 4), _s16(src, off + k * 4 + 2))
                    for k in range(num_points)
                ]
                off += num_points * 4
                fill_poly(points, bitmap, 255)
                for px, py in points:
                    min_x, max_x = min(min_x, px), max(max_x, px)
                    min_y, max_y = min(min_y, py), max(max_y, py)
            masks.append(Mask(
                min_x, min_y, max_x, max_y, bitmap,
                viewed_room=vr_room, test_rects=test_rects,
            ))
            # advance to the next mask header after its actor trigger rectangles
            data += 2 + ((num_zones * 4 + 1) * 2)
    return masks
