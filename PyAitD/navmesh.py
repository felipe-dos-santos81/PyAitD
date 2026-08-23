# SPDX-License-Identifier: GPL-2.0-only
"""Walkable mesh over the camera cover zones (mouse navigation).

Cover zones are the game's authored floor polygons, in room-scale/10 units
(playworld._camera_switch feeds zv/10 into world.is_in_poly). The union of
every camera viewing a room is that room's floor.

Containment vectorises FITD's own two-ray predicate (world.test_cross_product)
rather than a generic even-odd fill: the generic fill disagrees with
world.is_in_poly on boundary cells in both directions, and the mesh must not
drift from the predicate the engine uses for camera switching.
"""
from dataclasses import dataclass

import numpy as np

from PyAitD.formats import parse_cover_zones

GRID_STEP = 100   # room-scale units per cell (~5 across the hero's 532)
COVER_SCALE = 10  # cover-zone unit -> room-scale
_RAY = 10000      # world.is_in_poly ray length, in cover units


def cover_polys(floor, room_idx):
    """Cover polygons of every camera viewing room_idx, in cover units."""
    out = []
    for cam_idx in range(len(floor.cameras)):
        viewed = [vr.viewed_room_idx for vr in floor.cameras[cam_idx].viewed_rooms]
        if room_idx not in viewed:
            continue
        offset = floor.camera_data_offsets[cam_idx]
        out.extend(parse_cover_zones(floor.camera_raw, offset, viewed.index(room_idx)))
    return out


@dataclass
class RoomMesh:
    """Grid of walkable cells over one room. All coordinates are room-scale."""
    x0: int
    z0: int
    step: int
    walkable: np.ndarray

    @property
    def shape(self):
        return self.walkable.shape

    def center_of(self, i, j):
        return (self.x0 + i * self.step, self.z0 + j * self.step)

    def cell_of(self, x, z):
        i = int(round((x - self.x0) / self.step))
        j = int(round((z - self.z0) / self.step))
        if 0 <= i < self.walkable.shape[0] and 0 <= j < self.walkable.shape[1]:
            return (i, j)
        return None

    def is_walkable(self, x, z):
        cell = self.cell_of(x, z)
        return cell is not None and bool(self.walkable[cell])


def _cross_grid(x_grid, z_grid, ray_dx, x3, z3, x4, z4):
    # world.test_cross_product vectorised. Segment A runs from each grid point
    # to (point + ray_dx, same z), so x_ab == -ray_dx and z_ab == 0.
    x_ab = np.int64(-ray_dx)
    x_cd = np.int64(x3 - x4)
    z_cd = np.int64(z3 - z4)
    x_ac = x_grid - np.int64(x3)
    z_ac = z_grid - np.int64(z3)
    dot = x_ab * z_cd - x_cd * z_ac
    dda = x_ac * z_cd - x_cd * z_ac
    dmu = -x_ab * z_ac  # + x_ac * z_ab, and z_ab is zero
    negative = dot < 0
    dot = np.where(negative, -dot, dot)
    dda = np.where(negative, -dda, dda)
    dmu = np.where(negative, -dmu, dmu)
    return (dot != 0) & (dda >= 0) & (dmu >= 0) & (dot >= dda) & (dot >= dmu)


def _fill_union(polys, x_grid, z_grid):
    # world.is_in_poly: a point is inside when both the -X and +X rays hit an
    # edge of the same polygon (its flag == 3 test).
    inside = np.zeros(x_grid.shape, dtype=bool)
    for poly in polys:
        left = np.zeros(x_grid.shape, dtype=bool)
        right = np.zeros(x_grid.shape, dtype=bool)
        for k in range(len(poly)):
            (x3, z3), (x4, z4) = poly[k], poly[(k + 1) % len(poly)]
            left |= _cross_grid(x_grid, z_grid, -_RAY, x3, z3, x4, z4)
            right |= _cross_grid(x_grid, z_grid, _RAY, x3, z3, x4, z4)
        inside |= left & right
    return inside


def build_cover_grid(floor, room_idx, step=GRID_STEP):
    """Rasterise the cover-zone union for one room. None when no camera views it."""
    polys = cover_polys(floor, room_idx)
    if not polys:
        return None
    points = [p for poly in polys for p in poly]
    cx0, cx1 = min(p[0] for p in points), max(p[0] for p in points)
    cz0, cz1 = min(p[1] for p in points), max(p[1] for p in points)
    x0, z0 = cx0 * COVER_SCALE, cz0 * COVER_SCALE
    nx = int((cx1 - cx0) * COVER_SCALE // step) + 1
    nz = int((cz1 - cz0) * COVER_SCALE // step) + 1
    xs = (x0 + np.arange(nx, dtype=np.int64) * step) // COVER_SCALE
    zs = (z0 + np.arange(nz, dtype=np.int64) * step) // COVER_SCALE
    x_grid, z_grid = np.meshgrid(xs, zs, indexing="ij")
    return RoomMesh(x0, z0, step, _fill_union(polys, x_grid, z_grid))


def agent_extent(actor):
    """Rotation-invariant footprint of an actor: (half_extent, y0, y1).

    The ZV is beta-dependent (life_ops.op_do_real_zv rebuilds it via _zv_rot),
    so the mesh uses the larger horizontal half-extent and stays valid for
    every facing — one mesh per room instead of one per angle.
    """
    zv = actor.zv
    half = max((zv[1] - zv[0]) // 2, (zv[5] - zv[4]) // 2)
    return (int(half), int(zv[2]), int(zv[3]))


def _subtract_hard_cols(grid, x0, z0, step, hard_cols, agent):
    # cube_intersect with the agent box centred on each cell. Hero ZV and hard
    # col are both AABBs, so expanding the box by the half-extent is exact, not
    # conservative. No type filtering: type 4 room links fall out on the Y test.
    half, y0, y1 = agent
    nx, nz = grid.shape
    xs = x0 + np.arange(nx, dtype=np.int64) * step
    zs = z0 + np.arange(nz, dtype=np.int64) * step
    x_grid, z_grid = np.meshgrid(xs, zs, indexing="ij")
    walkable = grid.copy()
    for col in hard_cols:
        if not (y0 < col.y2 and col.y1 < y1):
            continue  # outside the agent's Y band — cube_intersect would miss
        hit = (
            ((x_grid - half) < col.x2) & (col.x1 < (x_grid + half))
            & ((z_grid - half) < col.z2) & (col.z1 < (z_grid + half))
        )
        walkable &= ~hit
    return walkable


def build_room_mesh(floor, room_idx, agent, step=GRID_STEP):
    """Walkable mesh for one room: cover-zone union minus the room's hard cols."""
    mesh = build_cover_grid(floor, room_idx, step)
    if mesh is None:
        return None
    mesh.walkable = _subtract_hard_cols(
        mesh.walkable, mesh.x0, mesh.z0, mesh.step,
        floor.rooms[room_idx].hard_cols, agent,
    )
    return mesh
