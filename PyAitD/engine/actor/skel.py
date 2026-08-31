# SPDX-License-Identifier: GPL-2.0-only
"""Skinning port of FITD renderer.cpp AnimNuage (AITD1 non-optimise path)."""
from dataclasses import dataclass

from PyAitD.engine.space.cos_table import COS_TABLE
from PyAitD.engine.space.world import transform_point, trunc_div as _trunc_div


@dataclass
class PrimEntry:
    type: int
    color: int
    points: list
    size: float = 0


@dataclass
class RenderResult:
    points: list
    primitives: list


def pose_vertices(body, group_states, actor_angles=None):
    # Unprojected pose step of FITD renderer.cpp AnimNuage, shared by skin()
    # (render path) and hot_point() (combat path); see getHotPoint main.cpp:2976.
    pts = [list(v) for v in body.vertices]
    num_points = len(pts)

    if actor_angles is not None:
        if body.group_order:
            # FITD AnimNuage: group 0 delta is the actor's own angles
            group_states = list(group_states)
            group_states[0] = (0, actor_angles)
        else:
            # FITD RotateNuage: non-animated bodies rotate as one model.
            _rotate_list(pts, 0, num_points, *actor_angles)

    for order_idx in body.group_order:
        group = body.groups[order_idx]
        gtype, (dx, dy, dz) = group_states[order_idx]
        if dx or dy or dz:
            if gtype == 0:
                _rotate_group(pts, group, body.groups, dx, dy, dz)
            elif gtype == 1:
                for i in range(group.num_vertices):
                    p = pts[group.start + i]
                    p[0] += dx
                    p[1] += dy
                    p[2] += dz
            elif gtype == 2:
                for i in range(group.num_vertices):
                    p = pts[group.start + i]
                    p[0] = _trunc_div(p[0] * (dx + 256), 256)
                    p[1] = _trunc_div(p[1] * (dy + 256), 256)
                    p[2] = _trunc_div(p[2] * (dz + 256), 256)

    for group in body.groups:
        base = pts[group.base_vertices]
        for i in range(group.num_vertices):
            p = pts[group.start + i]
            p[0] += base[0]
            p[1] += base[1]
            p[2] += base[2]

    return pts


def hot_point(body, group_states, actor_angles, hot_point_id):
    # getHotPoint main.cpp:2976: reads the skinned buffer, gated on flags & 2.
    if not body.flags & 2:
        return (0, 0, 0)
    if not 0 <= hot_point_id < len(body.groups):
        # Real AITD1 data asks for groups its own bodies do not have: the hero
        # wears body 12 (17 groups) while its animations address 19 and 20,
        # and the saber's LIFE 49 arms its hit on group 18. getHotPoint indexes
        # the group array unchecked, so the original reads past it, gets
        # whatever follows in memory, and swings on. There is no value to
        # match -- what it read was garbage -- so fall back to the actor's own
        # origin, which is the same answer this function already gives a body
        # that carries no hot point at all. Raising here instead killed the
        # game on every armed swing.
        return (0, 0, 0)
    points = pose_vertices(body, group_states, actor_angles)
    return tuple(points[body.groups[hot_point_id].base_vertices])


def skin(body, group_states, position, camera, actor_angles=None):
    pts = pose_vertices(body, group_states, actor_angles)

    px, py, pz = position
    projected = []
    for p in pts:
        x = p[0] + px - camera.x
        y = p[1] + py
        z = p[2] + pz - camera.z
        if y > 10000:
            projected.append((-10000.0, -10000.0, -10000.0))
            continue
        y -= camera.y
        x, y, z = transform_point(x, y, z, camera)
        sx, sy, depth = camera.project(x, y, z)
        projected.append((sx, sy, depth))

    primitives = []
    for prim in body.primitives:
        depth_min = 32000.0
        entries = []
        for idx in prim.points:
            e = projected[idx]
            entries.append(e)
            if e[2] < depth_min:
                depth_min = e[2]
        if depth_min > 100:
            size = 0.0
            if prim.type == 3:  # sphere: screen-space radius (FITD renderer.cpp)
                size = (prim.size * camera.focal2) / depth_min
            primitives.append(PrimEntry(prim.type, prim.color, entries, size))
    return RenderResult(projected, primitives)


def _rotate_group(pts, group, groups, dx, dy, dz):
    # InitGroupeRot + RotateGroupe (recursive over children) port
    _rotate_list(pts, group.start, group.num_vertices, dx, dy, dz)
    for other in groups:
        if other.org_group == group.num_group and other is not group:
            _rotate_group(pts, other, groups, dx, dy, dz)


def _rotate_list(pts, start, count, dx, dy, dz):
    rot_y = dy & 0x3FF
    rot_x = dx & 0x3FF
    rot_z = dz & 0x3FF
    for i in range(start, start + count):
        x, y, z = pts[i]
        if rot_y:
            s = COS_TABLE[(rot_y + 0x100) & 0x3FF]
            c = COS_TABLE[rot_y & 0x3FF]
            x, z = ((x * s - z * c) >> 16) << 1, ((x * c + z * s) >> 16) << 1
        if rot_x:
            s = COS_TABLE[(rot_x + 0x100) & 0x3FF]
            c = COS_TABLE[rot_x & 0x3FF]
            y, z = ((y * s - z * c) >> 16) << 1, ((y * c + z * s) >> 16) << 1
        if rot_z:
            s = COS_TABLE[(rot_z + 0x100) & 0x3FF]
            c = COS_TABLE[rot_z & 0x3FF]
            x, y = ((x * s - y * c) >> 16) << 1, ((x * c + y * s) >> 16) << 1
        pts[i] = [x, y, z]
