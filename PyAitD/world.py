# SPDX-License-Identifier: GPL-2.0-only
"""Camera math ports from FITD main.cpp/renderer.cpp (fixed point, exact)."""
from dataclasses import dataclass

from PyAitD.cos_table import COS_TABLE
from PyAitD.formats import Camera

SCREEN_CENTER_X = 160
SCREEN_CENTER_Y = 100


@dataclass
class CameraState:
    alpha: int
    beta: int
    gamma: int
    x: int
    y: int
    z: int
    focal1: int
    focal2: int
    focal3: int

    @classmethod
    def from_camera(cls, camera, world_x, world_y, world_z):
        return cls(
            camera.alpha,
            camera.beta,
            camera.gamma,
            (camera.x - world_x) * 10,
            (world_y - camera.y) * 10,
            (world_z - camera.z) * 10,
            camera.focal1,
            camera.focal2,
            camera.focal3,
        )

    def angles(self):
        self._use_x = self.alpha & 0x3FF
        self._use_y = self.beta & 0x3FF
        self._use_z = self.gamma & 0x3FF
        return self

    def project(self, x, y, z):
        # projection only: caller owns camera-space transform and y handling
        depth = z + self.focal1
        if depth <= 50:
            return (-10000.0, -10000.0, -10000.0)
        sx = (x * self.focal2) / depth + SCREEN_CENTER_X
        sy = (y * self.focal3) / depth + SCREEN_CENTER_Y
        return (sx, sy, depth)


def cdiv(a, b):
    # C integer division: truncation toward zero
    return a // b if a >= 0 else -((-a) // b)


def trunc_div(v, n):
    return int(v / n)  # C integer division: truncation toward zero


def room_delta(game, from_room, to_room):
    # FITD AdjustZV (main.cpp:3222): roomDataTable world-coord delta * 10.
    # Every caller applies it with FITD's asymmetric signs: x -, y +, z +.
    rooms = game.rooms_of_floor(game.current_floor)
    src, dst = rooms[from_room], rooms[to_room]
    return (
        10 * (dst.world_x - src.world_x),
        10 * (dst.world_y - src.world_y),
        10 * (dst.world_z - src.world_z),
    )


def shifted_zv(zv, dx, dy, dz):
    # room_delta's sign convention applied to a 6-element ZV box
    return [zv[0] - dx, zv[1] - dx, zv[2] + dy, zv[3] + dy, zv[4] + dz, zv[5] + dz]


def adjust_zv_between_rooms(game, zv, from_room, to_room):
    return shifted_zv(zv, *room_delta(game, from_room, to_room))


def transform_point(x, y, z, angles):
    ax, bx, cx = x, y, z
    if angles._use_y:
        s = COS_TABLE[(angles._use_y + 0x100) & 0x3FF]
        c = COS_TABLE[angles._use_y & 0x3FF]
        x = (trunc_div(ax * s - cx * c, 65536)) << 1
        z = (trunc_div(ax * c + cx * s, 65536)) << 1
    else:
        x, z = ax, cx
    if angles._use_x:
        s = COS_TABLE[(angles._use_x + 0x100) & 0x3FF]
        c = COS_TABLE[angles._use_x & 0x3FF]
        temp_y = bx
        temp_z = z
        y = (trunc_div(temp_y * s - temp_z * c, 65536)) << 1
        z = (trunc_div(temp_y * c + temp_z * s, 65536)) << 1
    else:
        y = bx
    if angles._use_z:
        s = COS_TABLE[(angles._use_z + 0x100) & 0x3FF]
        c = COS_TABLE[angles._use_z & 0x3FF]
        temp_x = x
        temp_y = y
        x = (trunc_div(temp_x * s - temp_y * c, 65536)) << 1
        y = (trunc_div(temp_x * c + temp_y * s, 65536)) << 1
    return (x, y, z)


def _s32(v):
    # C s32 wrap (two's complement truncation)
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v >= 0x80000000 else v


def _s32_mask_high(v):
    # C: (s32)v & 0xFFFF0000, sign-preserving
    v &= 0xFFFFFFFF
    v &= 0xFFFF0000
    return v - 0x100000000 if v >= 0x80000000 else v


def rotate_step(angle, x, z):
    # FITD Rotate() port: xOut/zOut are y/z in FITD terms; here (x, z) vector
    if angle:
        sinv = COS_TABLE[angle & 0x3FF]
        cosv = COS_TABLE[(angle + 0x100) & 0x3FF]
        v1 = _s32_mask_high((cosv * x) << 1)
        v2 = _s32_mask_high((sinv * x) << 1)
        v1 = _s32(v1 - _s32_mask_high((sinv * z) << 1))
        v2 = _s32(v2 + _s32_mask_high((cosv * z) << 1))
        z_out = v1 >> 16
        x_out = v2 >> 16
    else:
        x_out = z
        z_out = x
    return (x_out, z_out)

def test_cross_product(x1, z1, x2, z2, x3, z3, x4, z4):
    x_ab = x1 - x2
    z_ab = z1 - z2
    x_cd = x3 - x4
    z_cd = z3 - z4
    x_ac = x1 - x3
    z_ac = z1 - z3
    dot = (x_ab * z_cd) - (x_cd * z_ac)
    if dot == 0:
        return False
    dda = x_ac * z_cd - x_cd * z_ac
    dmu = -x_ab * z_ac + x_ac * z_ab
    if dot < 0:
        dot = -dot
        dda = -dda
        dmu = -dmu
    return dda >= 0 and dmu >= 0 and dot >= dda and dot >= dmu


def is_in_poly(x1, x2, z1, z2, zones):
    x_mid = int((x1 + x2) / 2)
    z_mid = int((z1 + z2) / 2)
    for poly in zones:
        flag = 0
        for j in range(len(poly)):
            zx1, zz1 = poly[j]
            zx2, zz2 = poly[(j + 1) % len(poly)]
            if test_cross_product(x_mid, z_mid, x_mid - 10000, z_mid, zx1, zz1, zx2, zz2):
                flag |= 1
            if test_cross_product(x_mid, z_mid, x_mid + 10000, z_mid, zx1, zz1, zx2, zz2):
                flag |= 2
        if flag == 3:
            return True
    return False


def find_best_camera(actor_x1, actor_x2, actor_z1, actor_z2, actor_beta, room_cameras, zones_by_camera):
    found_angle = 32000
    found_camera = -1
    for i, cam in enumerate(room_cameras):
        if is_in_poly(actor_x1, actor_x2, actor_z1, actor_z2, zones_by_camera[i]):
            new_angle = actor_beta + ((cam.beta + 0x200) & 0x3FF)
            if new_angle < 0:
                new_angle = -new_angle
            if new_angle < found_angle:
                found_angle = new_angle
                found_camera = i
    return found_camera
