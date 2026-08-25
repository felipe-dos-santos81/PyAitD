# SPDX-License-Identifier: GPL-2.0-only
"""Foreground mask polygons in 320x200 screen space (pre-rasterization view of
FITD main.cpp createAITD1Mask). Pygame/GL free."""
from dataclasses import dataclass
import struct

import numpy as np

from PyAitD.formats import _s16


@dataclass(frozen=True)
class MaskDraw:
    id: int
    polygons: tuple
    bbox: tuple
    viewed_room: int
    test_rects: tuple


def iter_mask_records(camera_raw, camera_off):
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
            # FITD: src = data2 + u16(data+2) -- the offset value is relative to data2
            poly_off = struct.unpack_from("<H", data2, data + 2)[0]
            src = camera_raw[base + poly_off :]
            num_polys = struct.unpack_from("<H", src, 0)[0]
            off = 2
            polygons = []
            for _ in range(num_polys):
                num_points = struct.unpack_from("<H", src, off)[0]
                off += 2
                polygons.append([
                    (_s16(src, off + k * 4), _s16(src, off + k * 4 + 2))
                    for k in range(num_points)
                ])
                off += num_points * 4
            yield vr_room, test_rects, polygons
            # advance to the next mask header after its actor trigger rectangles
            data += 2 + ((num_zones * 4 + 1) * 2)


def _polygons_bbox(polygons):
    min_x, max_x, min_y, max_y = 319, 0, 199, 0
    for poly in polygons:
        for px, py in poly:
            min_x, max_x = min(min_x, px), max(max_x, px)
            min_y, max_y = min(min_y, py), max(max_y, py)
    return min_x, min_y, max_x, max_y


def mask_polygons(camera_raw, camera_off):
    draws = []
    for index, (viewed_room, test_rects, polygons) in enumerate(
        iter_mask_records(camera_raw, camera_off)
    ):
        draws.append(MaskDraw(
            index,
            tuple(np.array(poly, dtype=np.int16).reshape(-1, 2) for poly in polygons),
            _polygons_bbox(polygons),
            viewed_room,
            test_rects,
        ))
    return draws
