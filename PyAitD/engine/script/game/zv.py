# SPDX-License-Identifier: GPL-2.0-only
"""ZV box geometry: fixed-point rotation helpers (pure)."""
from itertools import product

from PyAitD.engine.space.cos_table import COS_TABLE
from PyAitD.engine.space.world import cdiv as _cdiv


def _zv_default():
    return [-100, 100, -2000, 0, -100, 100]


def _zv_max(body_zv):
    # getZvMax: widest square footprint from body ZV (X/Z centered, Y kept)
    x1, x2, y1, y2, z1, z2 = body_zv
    x2 = -x1 + x2
    z2 = -z1 + z2
    if x2 < z2:
        x2 = z2
    x2 = _cdiv(x2, 2)
    return [-x2, x2, y1, y2, -x2, x2]


def _zv_cube(body_zv):
    # getZvCube: cube footprint from body ZV (X/Z centered, Y kept)
    x1, x2, y1, y2, z1, z2 = body_zv
    z2 = x2 = _cdiv(x2 + z2, 2)
    return [-z2, x2, y1, y2, -z2, z2]


def _point_rotate(x, y, z, cx, sx, cy, sy, cz, sz):
    # FITD pointRotate: fixed-point rotation Z then Y then X (>>16 arithmetic, <<1)
    temp_x, temp_y = x, y
    x = (((temp_x * sz - temp_y * cz) >> 16) << 1)
    y = (((temp_x * cz + temp_y * sz) >> 16) << 1)
    temp_x, temp_z = x, z
    x = (((temp_x * sy - temp_z * cy) >> 16) << 1)
    z = (((temp_x * cy + temp_z * sy) >> 16) << 1)
    temp_y, temp_z = y, z
    y = (((temp_y * sx - temp_z * cx) >> 16) << 1)
    z = (((temp_y * cx + temp_z * sx) >> 16) << 1)
    return x, y, z


def _zv_rot(body_zv, alpha, beta, gamma):
    # getZvRot: bounding box of the 8 rotated ZV corners (FITD getZvRot port)
    x1, x2, y1, y2, z1, z2 = body_zv
    if not (alpha or beta or gamma):
        return list(body_zv)
    a = alpha & 0x3FF
    b = beta & 0x3FF
    g = gamma & 0x3FF
    cx = COS_TABLE[a]
    sx = COS_TABLE[(a + 0x100) & 0x3FF]
    cy = COS_TABLE[b]
    sy = COS_TABLE[(b + 0x100) & 0x3FF]
    cz = COS_TABLE[g]
    sz = COS_TABLE[(g + 0x100) & 0x3FF]
    min_x = min_y = min_z = 32000
    max_x = max_y = max_z = -32000
    for px, py, pz in product((x1, x2), (y1, y2), (z1, z2)):
        rx, ry, rz = _point_rotate(px, py, pz, cx, sx, cy, sy, cz, sz)
        min_x = min(min_x, rx)
        max_x = max(max_x, rx)
        min_y = min(min_y, ry)
        max_y = max(max_y, ry)
        min_z = min(min_z, rz)
        max_z = max(max_z, rz)
    return [min_x, max_x, min_y, max_y, min_z, max_z]


def _hard_zv(game, room, hard_zv_idx):
    # type_zv == 4: ZV from room hard col entry (type == 9, parameter == hardZvIdx)
    for col in game.rooms_of_floor(game.current_floor)[room].hard_cols:
        if col.type == 9 and col.parameter == hard_zv_idx:
            return [col.x1, col.x2, col.y1, col.y2, col.z1, col.z2]
    return None
