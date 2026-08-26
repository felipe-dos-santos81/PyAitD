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
import heapq
from dataclasses import dataclass

import numpy as np

from PyAitD.engine.formats import parse_cover_zones

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


_NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))

TARGET_SNAP_CELLS = 12   # rings searched when snapping a clicked *object* to a
                         # standing spot. An object's own cell is essentially
                         # never walkable — the hard col representing it plus
                         # the 266-unit agent inflation — and nearest_walkable's
                         # 6 is too small: censused over all 22 interactable
                         # world objects on all 8 floors, the worst needs 8
                         # rings and floor 0's only interactable needs 7.


def _clamp_cell(value, limit):
    return max(0, min(int(value), limit - 1))


def approach_cell(mesh, x, z, from_x, from_z, max_cells=TARGET_SNAP_CELLS):
    """Where to stand to reach (x, z), coming from (from_x, from_z).

    Rings outward from the target and takes the first ring's cell closest to the
    approaching actor, so the hero stops on its own side of the object instead
    of walking around it. Unlike nearest_walkable this accepts a target outside
    the grid (an object can sit past the cover-zone bounds) by clamping the
    search origin. None when no walkable cell is within max_cells.
    """
    if mesh.is_walkable(x, z):
        return (x, z)
    nx, nz = mesh.shape
    origin_i = _clamp_cell(round((x - mesh.x0) / mesh.step), nx)
    origin_j = _clamp_cell(round((z - mesh.z0) / mesh.step), nz)
    from_i = (from_x - mesh.x0) / mesh.step
    from_j = (from_z - mesh.z0) / mesh.step
    # radius 0 is the clamped origin itself, which matters only when the target
    # was outside the grid: an in-grid walkable target already returned above
    for radius in range(0, max_cells + 1):
        best = None
        for di in range(-radius, radius + 1):
            for dj in range(-radius, radius + 1):
                if max(abs(di), abs(dj)) != radius:
                    continue
                i, j = origin_i + di, origin_j + dj
                if not (0 <= i < nx and 0 <= j < nz) or not mesh.walkable[i, j]:
                    continue
                score = (i - from_i) ** 2 + (j - from_j) ** 2
                if best is None or score < best[0]:
                    best = (score, (i, j))
        if best is not None:
            return mesh.center_of(*best[1])
    return None


def nearest_walkable(mesh, x, z, max_cells=6):
    """Closest walkable cell centre to (x, z), searching outward in rings."""
    if mesh.is_walkable(x, z):
        return (x, z)
    origin = mesh.cell_of(x, z)
    if origin is None:
        return None
    nx, nz = mesh.shape
    for radius in range(1, max_cells + 1):
        best = None
        for di in range(-radius, radius + 1):
            for dj in range(-radius, radius + 1):
                if max(abs(di), abs(dj)) != radius:
                    continue
                i, j = origin[0] + di, origin[1] + dj
                if not (0 <= i < nx and 0 <= j < nz) or not mesh.walkable[i, j]:
                    continue
                dist = di * di + dj * dj
                if best is None or dist < best[0]:
                    best = (dist, (i, j))
        if best is not None:
            return mesh.center_of(*best[1])
    return None


def _line_clear(mesh, a, b):
    walkable = mesh.walkable
    steps = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
    if steps == 0:
        return True
    if not walkable[a[0], a[1]]:
        return False
    prev_i, prev_j = a
    for k in range(1, steps + 1):
        i = round(a[0] + (b[0] - a[0]) * k / steps)
        j = round(a[1] + (b[1] - a[1]) * k / steps)
        if not walkable[i, j]:
            return False
        di, dj = i - prev_i, j - prev_j
        if di and dj and not (walkable[i, prev_j] and walkable[prev_i, j]):
            return False  # never cut a blocked corner — mirrors find_path's neighbour guard
        prev_i, prev_j = i, j
    return True


def _string_pull(mesh, cells, goal):
    # keep only the farthest cell still in line of sight, so the follower gets
    # a handful of waypoints instead of one per grid cell
    pulled = []
    index = 0
    while index < len(cells) - 1:
        far = len(cells) - 1
        while far > index + 1 and not _line_clear(mesh, cells[index], cells[far]):
            far -= 1
        pulled.append(cells[far])
        index = far
    points = [mesh.center_of(*cell) for cell in pulled]
    if not points:
        return [goal]
    points[-1] = goal
    return points


def find_path(mesh, start, goal):
    """A* over walkable cells, string-pulled. Room-scale in, room-scale out."""
    start_cell = mesh.cell_of(*start)
    goal_cell = mesh.cell_of(*goal)
    if start_cell is None or goal_cell is None:
        return None
    if not mesh.walkable[start_cell] or not mesh.walkable[goal_cell]:
        return None
    if start_cell == goal_cell:
        return [goal]
    walkable = mesh.walkable
    nx, nz = walkable.shape
    came_from = {start_cell: None}
    best_cost = {start_cell: 0}
    frontier = [(0, start_cell)]
    while frontier:
        _priority, cell = heapq.heappop(frontier)
        if cell == goal_cell:
            break
        for di, dj in _NEIGHBOURS:
            i, j = cell[0] + di, cell[1] + dj
            if not (0 <= i < nx and 0 <= j < nz) or not walkable[i, j]:
                continue
            if di and dj and not (walkable[cell[0] + di, cell[1]]
                                  and walkable[cell[0], cell[1] + dj]):
                continue  # never cut a blocked corner
            cost = best_cost[cell] + (14 if di and dj else 10)
            if cost < best_cost.get((i, j), 1 << 30):
                best_cost[(i, j)] = cost
                came_from[(i, j)] = cell
                estimate = max(abs(i - goal_cell[0]), abs(j - goal_cell[1])) * 10
                heapq.heappush(frontier, (cost + estimate, (i, j)))
    if goal_cell not in came_from:
        return None
    cells = []
    cursor = goal_cell
    while cursor is not None:
        cells.append(cursor)
        cursor = came_from[cursor]
    cells.reverse()
    return _string_pull(mesh, cells, goal)


class MeshCache:
    """Per-(floor, room) mesh cache. Meshes are static for a given agent."""

    def __init__(self):
        self._meshes = {}

    def mesh_for(self, floor, room_idx, agent):
        key = (floor.number, room_idx, agent)
        if key not in self._meshes:
            self._meshes[key] = build_room_mesh(floor, room_idx, agent)
        return self._meshes[key]

    def clear(self):
        self._meshes.clear()
