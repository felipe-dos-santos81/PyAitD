# Mouse-Only (Point-and-Click) Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the game fully playable with a mouse alone — click the floor to walk there, click an object to approach and interact with it — without removing the keyboard route.

**Architecture:** Three new pygame-free modules (`navmesh`, `picking`, `navigate`) plus a new `track_mode == 4` in the existing FITD track runner. The navmesh is a grid rasterized from the game's own camera cover zones using FITD's own containment predicate; picking inverts the floor plane with a homography fitted from the engine's real forward projection; the follower drives the hero through `_turn_toward` and mirrors tank joystick bits so LIFE scripts still see coherent input.

**Tech Stack:** Python 3.12, NumPy, pygame-ce, ModernGL, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-23-mouse-only-input-design.md`

## Global Constraints

- `# SPDX-License-Identifier: GPL-2.0-only` is the first line of every Python file.
- Dependencies are fixed: pygame-ce, ModernGL, NumPy, pytest. **Add nothing.**
- Layer rule: `playworld.py` / `life_ops.py` / `interaction.py` / `effects.py` / `navmesh.py` / `picking.py` / `navigate.py` never import pygame, ModernGL, `PyAitD.ui` or `PyAitD.render`.
- `ui.py` never mutates world/actor/inventory/LIFE/nav state.
- `__main__.py` owns the single event pump and one present per frame.
- No lint/formatter/typechecker is configured. The test suite is the only gate. **Never mass-reformat.**
- Any test touching rendering/pygame needs `SDL_VIDEODRIVER=dummy`.
- Golden values are pinned from real game data and never re-derived by guessing. Every golden in this plan was measured before the plan was written; the exact values are given inline.
- Tests requiring game data use the `data_dir` fixture and skip when it is absent.
- `ponytail:` comments mark deliberate simplifications with an upgrade path.
- Gate after every task: `.venv/bin/pytest -q`. After non-trivial changes also `make prove`.
- FITD behavioural authority: `/Users/felipe.dos.santos/code/theirs/FITD/FitdLib/`.

## Measured constants (do not re-derive)

| Constant | Value | Source |
|---|---|---|
| `GRID_STEP` | 100 room-scale units | ~5 cells across the hero's 532-unit width |
| `COVER_SCALE` | 10 | cover-zone unit -> room-scale |
| Hero agent half-extent | 266 | `max(x_half, z_half)` of hero ZV on floor 0 |
| Hero ZV Y band | `[-1777, 0]` | floor 0 hero after `init_game` |
| Floor 0 room 0 grid | shape `(151, 141)`, origin `(-7540, -4970)` | measured |
| Floor 0 room 0 cover union | 13976 cells | measured |
| Floor 0 room 0 walkable | 11120 cells | measured |
| Floor 0 room 0 components | 2, sizes `[10200, 920]` | measured |
| Floor 0 hero cell | `(108, 34)`, component 0 | measured |
| Type-4 room links overlapping hero Y | 0 of 95 | measured, all 8 floors |

---

### Task 1: navmesh module — cover-zone union

**Files:**
- Create: `PyAitD/navmesh.py`
- Test: `tests/test_navmesh.py`

**Interfaces:**
- Consumes: `PyAitD.floor.Floor`, `PyAitD.formats.parse_cover_zones`, `PyAitD.world.is_in_poly`
- Produces: `GRID_STEP`, `COVER_SCALE`, `cover_polys(floor, room_idx) -> list[list[tuple[int,int]]]` (cover units), `RoomMesh(x0, z0, step, walkable)` with `.shape`, `.center_of(i, j) -> (x, z)`, `.cell_of(x, z) -> (i, j) | None`, `.is_walkable(x, z) -> bool`, and `build_cover_grid(floor, room_idx, step=GRID_STEP) -> RoomMesh | None`. All coordinates on `RoomMesh` are **room-scale**.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_navmesh.py
# SPDX-License-Identifier: GPL-2.0-only
import subprocess
import sys

from PyAitD.floor import Floor
from PyAitD.navmesh import COVER_SCALE, build_cover_grid, cover_polys
from PyAitD.world import is_in_poly

_PURITY_PROBE = """
import sys, PyAitD.navmesh
leaked = {"PyAitD.ui", "PyAitD.render", "pygame", "moderngl", "OpenGL"} & sys.modules.keys()
sys.exit(", ".join(sorted(leaked)) or None)
"""


def test_navmesh_does_not_import_the_presentation_layer():
    out = subprocess.run([sys.executable, "-c", _PURITY_PROBE], capture_output=True, text=True)
    assert out.returncode == 0, (
        f"PyAitD.navmesh pulled in {out.stderr.strip()} — the mesh must stay "
        f"importable without the presentation layer so it can build headless"
    )


def test_cover_grid_shape_and_union_are_pinned(data_dir):
    mesh = build_cover_grid(Floor(data_dir, 0), 0)
    assert (mesh.x0, mesh.z0, mesh.step) == (-7540, -4970, 100)
    assert mesh.shape == (151, 141)
    assert int(mesh.walkable.sum()) == 13976


def test_cover_grid_matches_fitd_is_in_poly_cell_for_cell(data_dir):
    # The mesh must never disagree with the predicate the engine itself uses
    # for camera switching (playworld._camera_switch). A generic even-odd fill
    # disagrees on 64 of these cells; vectorising test_cross_product does not.
    floor = Floor(data_dir, 0)
    mesh = build_cover_grid(floor, 0)
    polys = cover_polys(floor, 0)
    mismatches = []
    for i in range(mesh.shape[0]):
        for j in range(mesh.shape[1]):
            x, z = mesh.center_of(i, j)
            cx, cz = x // COVER_SCALE, z // COVER_SCALE
            if bool(mesh.walkable[i, j]) != is_in_poly(cx, cx, cz, cz, polys):
                mismatches.append((i, j))
    assert mismatches == []


def test_room_without_cover_zones_has_no_mesh(data_dir):
    # floor 4 room 1 has camera_indices == [] — no camera views it
    assert build_cover_grid(Floor(data_dir, 4), 1) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_navmesh.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'PyAitD.navmesh'`

- [ ] **Step 3: Write the implementation**

```python
# PyAitD/navmesh.py
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_navmesh.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add PyAitD/navmesh.py tests/test_navmesh.py
git commit -m "feat(navmesh): rasterise the cover-zone union with FITD's own predicate"
```

---

### Task 2: navmesh — hard-col blocking

**Files:**
- Modify: `PyAitD/navmesh.py`
- Test: `tests/test_navmesh.py`

**Interfaces:**
- Consumes: `RoomMesh`, `build_cover_grid` from Task 1; `PyAitD.actors.cube_intersect` (for the equivalence test only)
- Produces: `agent_extent(actor) -> (half, y0, y1)`, `build_room_mesh(floor, room_idx, agent, step=GRID_STEP) -> RoomMesh | None` where `agent` is the `(half, y0, y1)` triple.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_navmesh.py
from PyAitD.actors import cube_intersect
from PyAitD.game import init_game
from PyAitD.navmesh import GRID_STEP, agent_extent, build_room_mesh


def _hero_agent(data_dir):
    game = init_game(data_dir)
    return game, game.actors[game.current_camera_target_actor]


def test_agent_extent_is_rotation_invariant(data_dir):
    _game, hero = _hero_agent(data_dir)
    assert agent_extent(hero) == (266, -1777, 0)


def test_room_mesh_walkable_count_is_pinned(data_dir):
    _game, hero = _hero_agent(data_dir)
    mesh = build_room_mesh(Floor(data_dir, 0), 0, agent_extent(hero))
    assert int(mesh.walkable.sum()) == 11120


def test_blocking_agrees_with_check_hard_col(data_dir):
    # The mesh's notion of "solid" must be the engine's: cube_intersect against
    # room.hard_cols, all three axes, no type filtering.
    game, hero = _hero_agent(data_dir)
    floor = Floor(data_dir, 0)
    half, y0, y1 = agent_extent(hero)
    mesh = build_room_mesh(floor, 0, (half, y0, y1))
    cover = build_cover_grid(floor, 0)
    hard_cols = floor.rooms[0].hard_cols
    for i in range(0, mesh.shape[0], 7):        # stride keeps the test quick
        for j in range(0, mesh.shape[1], 7):
            if not cover.walkable[i, j]:
                continue                        # outside the floor entirely
            x, z = mesh.center_of(i, j)
            zv = [x - half, x + half, y0, y1, z - half, z + half]
            blocked = any(
                cube_intersect(zv, (c.x1, c.x2, c.y1, c.y2, c.z1, c.z2))
                for c in hard_cols
            )
            assert bool(mesh.walkable[i, j]) is (not blocked), f"cell {(i, j)}"


def test_room_links_never_block(data_dir):
    # All 95 type-4 room links across all 8 floors sit outside the hero Y band,
    # so the engine's own 3D test keeps every doorway open with no special case.
    _game, hero = _hero_agent(data_dir)
    _half, y0, y1 = agent_extent(hero)
    total = blocking = 0
    for number in range(8):
        for room in Floor(data_dir, number).rooms:
            for col in room.hard_cols:
                if col.type != 4:
                    continue
                total += 1
                if y0 < col.y2 and col.y1 < y1:
                    blocking += 1
    assert (total, blocking) == (95, 0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_navmesh.py -q`
Expected: FAIL — `ImportError: cannot import name 'agent_extent'`

- [ ] **Step 3: Write the implementation**

Append to `PyAitD/navmesh.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_navmesh.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add PyAitD/navmesh.py tests/test_navmesh.py
git commit -m "feat(navmesh): subtract hard cols with the engine's own 3D rule"
```

---

### Task 3: navmesh — pathfinding and per-room cache

**Files:**
- Modify: `PyAitD/navmesh.py`
- Test: `tests/test_navmesh.py`

**Interfaces:**
- Consumes: `RoomMesh`, `build_room_mesh`, `agent_extent`
- Produces: `nearest_walkable(mesh, x, z, max_cells=6) -> (x, z) | None`, `find_path(mesh, start, goal) -> list[tuple[int,int]] | None` (room-scale waypoints, last is exactly `goal`), `MeshCache` with `.mesh_for(floor, room_idx, agent) -> RoomMesh | None` and `.clear()`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_navmesh.py
from PyAitD.navmesh import MeshCache, find_path, nearest_walkable


def test_path_between_two_walkable_points_is_walkable_throughout(data_dir):
    _game, hero = _hero_agent(data_dir)
    floor = Floor(data_dir, 0)
    mesh = build_room_mesh(floor, 0, agent_extent(hero))
    start = mesh.center_of(108, 34)              # the hero's own cell
    goal = mesh.center_of(145, 78)               # the type-10 sce zone, component 0
    path = find_path(mesh, start, goal)
    assert path is not None and len(path) >= 1
    assert path[-1] == goal
    for x, z in path:
        assert mesh.is_walkable(x, z), f"waypoint {(x, z)} is not walkable"


def test_path_is_string_pulled_not_a_cell_staircase(data_dir):
    _game, hero = _hero_agent(data_dir)
    mesh = build_room_mesh(Floor(data_dir, 0), 0, agent_extent(hero))
    path = find_path(mesh, mesh.center_of(108, 34), mesh.center_of(145, 78))
    # 37 cells of X travel alone; an unsmoothed path would return dozens of hops
    assert len(path) <= 8


def test_path_to_an_unreachable_cell_is_none(data_dir):
    _game, hero = _hero_agent(data_dir)
    mesh = build_room_mesh(Floor(data_dir, 0), 0, agent_extent(hero))
    blocked = next(
        mesh.center_of(i, j)
        for i in range(mesh.shape[0]) for j in range(mesh.shape[1])
        if not mesh.walkable[i, j]
    )
    assert find_path(mesh, mesh.center_of(108, 34), blocked) is None


def test_nearest_walkable_snaps_a_blocked_click(data_dir):
    _game, hero = _hero_agent(data_dir)
    mesh = build_room_mesh(Floor(data_dir, 0), 0, agent_extent(hero))
    blocked = next(
        mesh.center_of(i, j)
        for i in range(mesh.shape[0]) for j in range(mesh.shape[1])
        if not mesh.walkable[i, j] and 20 < i < 130 and 20 < j < 120
    )
    snapped = nearest_walkable(mesh, *blocked)
    assert snapped is not None and mesh.is_walkable(*snapped)


def test_mesh_cache_returns_the_same_object_for_the_same_room(data_dir):
    _game, hero = _hero_agent(data_dir)
    floor = Floor(data_dir, 0)
    cache = MeshCache()
    agent = agent_extent(hero)
    first = cache.mesh_for(floor, 0, agent)
    assert cache.mesh_for(floor, 0, agent) is first
    cache.clear()
    assert cache.mesh_for(floor, 0, agent) is not first
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_navmesh.py -q`
Expected: FAIL — `ImportError: cannot import name 'MeshCache'`

- [ ] **Step 3: Write the implementation**

Append to `PyAitD/navmesh.py` (add `import heapq` to the imports at the top):

```python
_NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


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
    steps = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
    if steps == 0:
        return True
    for k in range(steps + 1):
        i = round(a[0] + (b[0] - a[0]) * k / steps)
        j = round(a[1] + (b[1] - a[1]) * k / steps)
        if not mesh.walkable[i, j]:
            return False
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_navmesh.py -q`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add PyAitD/navmesh.py tests/test_navmesh.py
git commit -m "feat(navmesh): A* with string-pulled waypoints, snapping and a mesh cache"
```

---

### Task 4: picking — floor homography

**Files:**
- Create: `PyAitD/picking.py`
- Test: `tests/test_picking.py`

**Interfaces:**
- Consumes: `PyAitD.world.CameraState`, `PyAitD.world.transform_point`, `PyAitD.navmesh.cover_polys`, `COVER_SCALE`
- Produces: `project_floor_point(state, wx, wy, wz) -> (sx, sy) | None`, `floor_homography(state, poly_world, floor_y) -> np.ndarray | None` (3x3 world-plane -> screen), `pick_floor(logical_pos, floor, room_idx, cam_idx, floor_y) -> (x, z) | None` (room-scale).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_picking.py
# SPDX-License-Identifier: GPL-2.0-only
import subprocess
import sys

from PyAitD.floor import Floor
from PyAitD.game import init_game
from PyAitD.navmesh import COVER_SCALE, cover_polys
from PyAitD.picking import pick_floor, project_floor_point
from PyAitD.world import CameraState

_PURITY_PROBE = """
import sys, PyAitD.picking
leaked = {"PyAitD.ui", "PyAitD.render", "pygame", "moderngl", "OpenGL"} & sys.modules.keys()
sys.exit(", ".join(sorted(leaked)) or None)
"""


def test_picking_does_not_import_the_presentation_layer():
    out = subprocess.run([sys.executable, "-c", _PURITY_PROBE], capture_output=True, text=True)
    assert out.returncode == 0, (
        f"PyAitD.picking pulled in {out.stderr.strip()} — picking is pure math "
        f"and must not need a window; __main__ passes it logical coordinates"
    )


def _state(floor, room_idx, cam_idx):
    room = floor.rooms[room_idx]
    camera = floor.cameras[room.camera_indices[cam_idx]]
    return CameraState.from_camera(
        camera, room.world_x, room.world_y, room.world_z,
    ).angles()


def test_pick_floor_round_trips_projected_points(data_dir):
    # For every camera of the opening room, projecting a floor point and
    # picking it back must land within a cell of where it started.
    floor = Floor(data_dir, 0)
    game = init_game(data_dir)
    floor_y = game.actors[game.current_camera_target_actor].world_y
    checked = 0
    for cam_slot in range(len(floor.rooms[0].camera_indices)):
        state = _state(floor, 0, cam_slot)
        for poly in cover_polys(floor, 0):
            xs = [p[0] * COVER_SCALE for p in poly]
            zs = [p[1] * COVER_SCALE for p in poly]
            cx, cz = sum(xs) // len(xs), sum(zs) // len(zs)
            screen = project_floor_point(state, cx, floor_y, cz)
            if screen is None:
                continue
            picked = pick_floor(screen, floor, 0, cam_slot, floor_y)
            if picked is None:
                continue
            assert abs(picked[0] - cx) <= 100 and abs(picked[1] - cz) <= 100, (
                f"camera {cam_slot}: {picked} should round-trip to {(cx, cz)}"
            )
            checked += 1
    assert checked > 0, "no floor point round-tripped — the fit never ran"


def test_pick_floor_outside_every_cover_polygon_is_none(data_dir):
    floor = Floor(data_dir, 0)
    # top-left corner of the 320x200 logical surface is ceiling, never floor
    assert pick_floor((2, 2), floor, 0, 0, 0) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_picking.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'PyAitD.picking'`

- [ ] **Step 3: Write the implementation**

```python
# PyAitD/picking.py
# SPDX-License-Identifier: GPL-2.0-only
"""Screen -> world picking for mouse input. Pure math: no pygame, no Renderer.

The floor is a plane and CameraState.project is a real pinhole projection
(anisotropic focals, divide by z + focal1), so plane -> screen is a homography.
It is *fitted* from four points pushed through the engine's own forward path
rather than derived from alpha/beta/gamma and COS_TABLE, so it cannot drift
from the fixed-point pipeline it has to agree with.
"""
import numpy as np

from PyAitD.navmesh import COVER_SCALE, cover_polys
from PyAitD.world import CameraState, transform_point


def project_floor_point(state, wx, wy, wz):
    """World point -> logical 320x200 screen, via the real skin() path."""
    x = wx - state.x
    y = wy
    z = wz - state.z
    if y > 10000:
        return None
    y -= state.y
    x, y, z = transform_point(x, y, z, state)
    sx, sy, depth = state.project(x, y, z)
    if depth <= 50:
        return None
    return (sx, sy)


def _homography(src, dst):
    # 8-parameter fit from four correspondences, solved by SVD
    rows = []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    _u, _s, vt = np.linalg.svd(np.array(rows, dtype=float))
    matrix = vt[-1].reshape(3, 3)
    if abs(matrix[2, 2]) < 1e-12:
        return None
    return matrix / matrix[2, 2]


def _quad_of(poly_world, state, floor_y):
    # four extreme, validly-projecting vertices give a well-conditioned fit
    projected = [
        (world, project_floor_point(state, world[0], floor_y, world[1]))
        for world in poly_world
    ]
    usable = [(w, s) for w, s in projected if s is not None]
    if len(usable) < 4:
        return None
    xs = [w[0] for w, _s in usable]
    zs = [w[1] for w, _s in usable]
    corners = [
        (min(xs), min(zs)), (max(xs), min(zs)),
        (max(xs), max(zs)), (min(xs), max(zs)),
    ]
    chosen = []
    for target in corners:
        pick = min(
            usable,
            key=lambda ws: (ws[0][0] - target[0]) ** 2 + (ws[0][1] - target[1]) ** 2,
        )
        if pick in chosen:
            return None  # degenerate polygon: fewer than four distinct corners
        chosen.append(pick)
    return [w for w, _s in chosen], [s for _w, s in chosen]


def floor_homography(state, poly_world, floor_y):
    """3x3 mapping (world_x, world_z) on the floor plane -> logical screen."""
    quad = _quad_of(poly_world, state, floor_y)
    if quad is None:
        return None
    return _homography(quad[0], quad[1])


def _apply(matrix, x, y):
    vec = matrix @ np.array([x, y, 1.0])
    if abs(vec[2]) < 1e-12:
        return None
    return (vec[0] / vec[2], vec[1] / vec[2])


def _camera_state(floor, room_idx, cam_slot):
    room = floor.rooms[room_idx]
    camera = floor.cameras[room.camera_indices[cam_slot]]
    return CameraState.from_camera(
        camera, room.world_x, room.world_y, room.world_z,
    ).angles()


def pick_floor(logical_pos, floor, room_idx, cam_slot, floor_y):
    """Logical 320x200 click -> room-scale (x, z) on the floor, or None.

    Only the current camera's polygons are on screen. When a click falls inside
    more than one, the recovered point is tested against the polygon it came
    from, and self-consistency picks the right one at no extra cost.
    """
    state = _camera_state(floor, room_idx, cam_slot)
    for poly in cover_polys(floor, room_idx):
        world = [(x * COVER_SCALE, z * COVER_SCALE) for x, z in poly]
        matrix = floor_homography(state, world, floor_y)
        if matrix is None:
            continue
        try:
            inverse = np.linalg.inv(matrix)
        except np.linalg.LinAlgError:
            continue
        recovered = _apply(inverse, float(logical_pos[0]), float(logical_pos[1]))
        if recovered is None:
            continue
        wx, wz = int(round(recovered[0])), int(round(recovered[1]))
        forward = _apply(matrix, wx, wz)
        if forward is None:
            continue
        if abs(forward[0] - logical_pos[0]) > 2 or abs(forward[1] - logical_pos[1]) > 2:
            continue  # the fit does not explain this pixel
        if _point_in_world_poly(wx, wz, world):
            return (wx, wz)
    return None


def _point_in_world_poly(x, z, world_poly):
    # even-odd test in room-scale, used only to attribute a click to the polygon
    # whose homography produced it; the mesh, not this, decides walkability
    inside = False
    count = len(world_poly)
    for k in range(count):
        x1, z1 = world_poly[k]
        x2, z2 = world_poly[(k + 1) % count]
        if (z1 > z) != (z2 > z) and z1 != z2:
            crossing = (x2 - x1) * (z - z1) / (z2 - z1) + x1
            if x < crossing:
                inside = not inside
    return inside
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_picking.py -q`
Expected: 3 passed

A camera whose polygons cannot be fitted returns `None` from `pick_floor`, so
clicks there fall through to a no-op rather than producing a wrong destination;
`make prove-mouse` (Task 14) is where that surfaces as a report.

If the round-trip assertion fails for a specific camera, the fit is not
explaining that camera's projection: print the residual between `forward` and
`logical_pos` for its quad before changing tolerances, and record the finding.
Do **not** widen the tolerance to make it pass.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/picking.py tests/test_picking.py
git commit -m "feat(picking): recover floor points via a homography fitted from the real projection"
```

---

### Task 5: picking — actor hit-testing and the renderer draw list

**Files:**
- Modify: `PyAitD/picking.py`, `PyAitD/__main__.py:43-81` (`_scene_frame`)
- Test: `tests/test_picking.py`

**Interfaces:**
- Consumes: `RenderResult` entries produced by `PyAitD.skel.skin`
- Produces: `actor_bbox(result, pad=ACTOR_PICK_PAD) -> (x0, y0, x1, y1) | None`, `pick_actor(logical_pos, draw_list) -> int | None` where `draw_list` is `[(actor_idx, bbox)]` in painter order. `_scene_frame` now returns `(frame, draw_list)`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_picking.py
from PyAitD.picking import ACTOR_PICK_PAD, actor_bbox, pick_actor


class _FakeResult:
    def __init__(self, points):
        self.points = points


def test_actor_bbox_ignores_culled_vertices():
    # skel.skin writes (-10000, -10000, -10000) for culled points
    result = _FakeResult([(100.0, 50.0, 900.0), (-10000.0, -10000.0, -10000.0),
                          (120.0, 80.0, 900.0)])
    assert actor_bbox(result, pad=0) == (100, 50, 120, 80)


def test_actor_bbox_is_none_when_everything_is_culled():
    assert actor_bbox(_FakeResult([(-10000.0, -10000.0, -10000.0)])) is None


def test_pick_actor_returns_the_topmost_hit():
    # painter order is farthest first, so a later entry is nearer the camera
    draw_list = [(3, (100, 40, 160, 120)), (7, (110, 50, 140, 100))]
    assert pick_actor((120, 60), draw_list) == 7
    assert pick_actor((105, 45), draw_list) == 3
    assert pick_actor((10, 10), draw_list) is None


def test_actor_bbox_padding_enlarges_the_target():
    result = _FakeResult([(100.0, 50.0, 900.0), (120.0, 80.0, 900.0)])
    x0, y0, x1, y1 = actor_bbox(result)
    assert (x0, y0, x1, y1) == (100 - ACTOR_PICK_PAD, 50 - ACTOR_PICK_PAD,
                                120 + ACTOR_PICK_PAD, 80 + ACTOR_PICK_PAD)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_picking.py -q`
Expected: FAIL — `ImportError: cannot import name 'ACTOR_PICK_PAD'`

- [ ] **Step 3: Write the implementation**

Append to `PyAitD/picking.py`:

```python
ACTOR_PICK_PAD = 3  # logical pixels of slack; the accessibility contract
                    # forbids requiring precise pointing
_CULLED = -9000     # skel.skin writes -10000 for culled vertices


def actor_bbox(result, pad=ACTOR_PICK_PAD):
    """Screen-space bounding box of a skinned actor, or None if fully culled."""
    xs = [p[0] for p in result.points if p[0] > _CULLED and p[1] > _CULLED]
    ys = [p[1] for p in result.points if p[0] > _CULLED and p[1] > _CULLED]
    if not xs:
        return None
    return (int(min(xs)) - pad, int(min(ys)) - pad,
            int(max(xs)) + pad, int(max(ys)) + pad)


def pick_actor(logical_pos, draw_list):
    """Topmost interactable actor under the click. draw_list is painter order."""
    x, y = logical_pos
    for actor_idx, box in reversed(draw_list):
        if box is None:
            continue
        if box[0] <= x <= box[2] and box[1] <= y <= box[3]:
            return actor_idx
    return None
```

In `PyAitD/__main__.py`, change `_scene_frame` to also build and return the
draw list. Inside the existing `for index in draw_order:` loop, after
`results.append(skin(...))`, add:

```python
        draw_list.append((index, actor_bbox(results[-1])))
```

Initialise `draw_list = []` next to `results = []`, add
`from PyAitD.picking import actor_bbox` to the imports, and change the final
`return renderer.compose_scene(...)` to:

```python
    return renderer.compose_scene(
        floor.camera_image(cam_idx), results, floor.masks(cam_idx), floor.palette,
        actor_rooms, actor_zvs,
    ), draw_list
```

Update the two call sites in `run()` (`scene_frame = _scene_frame(...)`) to
unpack: `scene_frame, draw_list = _scene_frame(game, floor, renderer)`.
Initialise `draw_list = []` before the loop so the first frame has one.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_picking.py tests/test_play_loop.py -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add PyAitD/picking.py PyAitD/__main__.py tests/test_picking.py
git commit -m "feat(picking): hit-test actors from the renderer's own draw order"
```

---

### Task 6: nav intent and input mode state

**Files:**
- Modify: `PyAitD/effects.py`, `PyAitD/game.py:107-160` (`Game.__init__`)
- Test: `tests/test_runtime_modes.py`

**Interfaces:**
- Produces: `effects.InputMode` (`MOUSE`, `KEYBOARD`), `effects.NavIntent(dest_x, dest_z, room, target_object_idx=-1, waypoints=None)`, `effects.NavDecision(joyd, target_x, target_z, advance, arrived)`. New `Game` fields: `input_mode` (default `InputMode.MOUSE`), `nav_intent` (default `None`), `nav_decision` (default `None`), `nav_meshes` (a `MeshCache`), `nav_arrived_target` (default `-1`).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_runtime_modes.py
from PyAitD.effects import InputMode, NavDecision, NavIntent
from PyAitD.game import init_game


def test_game_starts_in_mouse_mode_with_no_intent(data_dir):
    game = init_game(data_dir)
    assert game.input_mode is InputMode.MOUSE
    assert game.nav_intent is None
    assert game.nav_decision is None
    assert game.nav_arrived_target == -1


def test_nav_intent_defaults_to_a_bare_destination():
    intent = NavIntent(dest_x=100, dest_z=200, room=0)
    assert intent.target_object_idx == -1
    assert intent.waypoints is None


def test_nav_decision_carries_the_mirrored_joystick_bits():
    decision = NavDecision(joyd=5, target_x=1, target_z=2, advance=True, arrived=False)
    assert decision.joyd == 5 and decision.advance is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_runtime_modes.py -q`
Expected: FAIL — `ImportError: cannot import name 'InputMode'`

- [ ] **Step 3: Write the implementation**

Append to `PyAitD/effects.py` (it already imports `dataclass` and `Enum`/`auto`;
add whichever are missing):

```python
class InputMode(Enum):
    """Mouse is the default route; the keyboard route is retained, not replaced."""
    MOUSE = auto()
    KEYBOARD = auto()


@dataclass
class NavIntent:
    """Where the player clicked, and what they meant by it."""
    dest_x: int
    dest_z: int
    room: int
    target_object_idx: int = -1
    waypoints: list = None


@dataclass
class NavDecision:
    """One tick of follower output: mirrored joyd plus the steering target."""
    joyd: int
    target_x: int
    target_z: int
    advance: bool
    arrived: bool
```

In `PyAitD/game.py`, inside `Game.__init__`, after the `# M3b effect / mode /
inventory state` block add:

```python
        # mouse navigation state (see docs/superpowers/specs/2026-08-23-...)
        self.input_mode = InputMode.MOUSE
        self.nav_intent = None
        self.nav_decision = None
        self.nav_arrived_target = -1
        self.nav_meshes = MeshCache()
```

Add to `game.py`'s imports: `from PyAitD.effects import InputMode` and
`from PyAitD.navmesh import MeshCache`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_runtime_modes.py -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add PyAitD/effects.py PyAitD/game.py tests/test_runtime_modes.py
git commit -m "feat: carry nav intent, follower decision and input mode on Game"
```

---

### Task 7: navigate — the follower decision and joyd mirror

**Files:**
- Create: `PyAitD/navigate.py`
- Test: `tests/test_navigate.py`

**Interfaces:**
- Consumes: `effects.NavIntent`, `effects.NavDecision`, `tracks.cap_objet`, `realvalue.give_distance_2d`, `navmesh.find_path`
- Produces: `ARRIVE_DISTANCE`, `WAYPOINT_DISTANCE`, `decide(game, actor, mesh) -> NavDecision | None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_navigate.py
# SPDX-License-Identifier: GPL-2.0-only
import subprocess
import sys

from PyAitD.effects import NavIntent
from PyAitD.game import Actor
from PyAitD.navigate import ARRIVE_DISTANCE, decide

_PURITY_PROBE = """
import sys, PyAitD.navigate
leaked = {"PyAitD.ui", "PyAitD.render", "pygame", "moderngl", "OpenGL"} & sys.modules.keys()
sys.exit(", ".join(sorted(leaked)) or None)
"""


def test_navigate_does_not_import_the_presentation_layer():
    out = subprocess.run([sys.executable, "-c", _PURITY_PROBE], capture_output=True, text=True)
    assert out.returncode == 0, f"PyAitD.navigate pulled in {out.stderr.strip()}"


class _Game:
    def __init__(self, intent):
        self.nav_intent = intent
        self.timer = 0


def _actor(x, z, beta=0, room=0):
    actor = Actor()
    actor.room_x, actor.room_z, actor.room = x, z, room
    actor.world_x, actor.world_z = x, z
    actor.beta = beta
    return actor


def test_no_intent_means_no_decision():
    assert decide(_Game(None), _actor(0, 0), None) is None


def test_far_from_the_destination_the_follower_advances():
    game = _Game(NavIntent(dest_x=5000, dest_z=0, room=0, waypoints=[(5000, 0)]))
    decision = decide(game, _actor(0, 0), None)
    assert decision.advance is True
    assert decision.arrived is False
    assert decision.joyd & 1, "forward bit must be mirrored while advancing"
    assert (decision.target_x, decision.target_z) == (5000, 0)


def test_reaching_the_final_waypoint_reports_arrival():
    game = _Game(NavIntent(dest_x=10, dest_z=10, room=0, waypoints=[(10, 10)]))
    decision = decide(game, _actor(0, 0), None)
    assert decision.arrived is True
    assert decision.advance is False
    assert decision.joyd == 0, "an arrived follower presses nothing"


def test_intermediate_waypoints_are_consumed_in_order():
    intent = NavIntent(dest_x=9000, dest_z=0, room=0, waypoints=[(10, 0), (9000, 0)])
    game = _Game(intent)
    decision = decide(game, _actor(0, 0), None)
    # first waypoint is already within reach, so it pops and we steer to the next
    assert (decision.target_x, decision.target_z) == (9000, 0)
    assert intent.waypoints == [(9000, 0)]
    assert decision.arrived is False


def test_turn_bits_mirror_the_engine_turn_direction():
    # cap_objet returns +1 to turn left (joyd bit 4) and -1 to turn right (bit 8),
    # matching gere_manual_rot's bit->direction mapping
    left = decide(_Game(NavIntent(0, 9000, 0, waypoints=[(0, 9000)])), _actor(0, 0, beta=0), None)
    right = decide(_Game(NavIntent(0, -9000, 0, waypoints=[(0, -9000)])), _actor(0, 0, beta=0), None)
    assert (left.joyd & 0xC) in (4, 8)
    assert (right.joyd & 0xC) in (4, 8)
    assert (left.joyd & 0xC) != (right.joyd & 0xC), "opposite targets must turn opposite ways"


def test_arrival_threshold_is_the_engine_track_threshold():
    assert ARRIVE_DISTANCE == 400
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_navigate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'PyAitD.navigate'`

- [ ] **Step 3: Write the implementation**

```python
# PyAitD/navigate.py
# SPDX-License-Identifier: GPL-2.0-only
"""Mouse follower: turns a NavIntent into one tick of steering.

Runs inside playworld.apply_play_input, so the decision is made once per tick
and consumed twice — once as mirrored joystick bits (LIFE scripts read the
joystick through evalVar 0x13 and must not see a dead stick while the player
is walking), and once by tracks._process_track_mouse, which applies it through
the same _turn_toward the engine's follow mode uses.
"""
from PyAitD.effects import NavDecision
from PyAitD.navmesh import find_path
from PyAitD.realvalue import give_distance_2d
from PyAitD.tracks import cap_objet

ARRIVE_DISTANCE = 400    # tracks.DISTANCE_TO_POINT_TRESSHOLD [sic], same units
WAYPOINT_DISTANCE = 400  # how close counts as reaching an intermediate hop


def _repath(game, actor, mesh):
    intent = game.nav_intent
    start = (actor.room_x + actor.step_x, actor.room_z + actor.step_z)
    goal = (intent.dest_x, intent.dest_z)
    if mesh is not None:
        path = find_path(mesh, start, goal)
        if path:
            intent.waypoints = list(path)
            return
    # degraded mode: no mesh, hero off-mesh, or no route — steer straight at the
    # click and let the engine's own collision slide do what A* would not
    intent.waypoints = [goal]


def decide(game, actor, mesh):
    """One tick of follower output, or None when there is nothing to follow."""
    intent = game.nav_intent
    if intent is None:
        return None
    if intent.waypoints is None:
        _repath(game, actor, mesh)
    here_x = actor.room_x + actor.step_x
    here_z = actor.room_z + actor.step_z
    while len(intent.waypoints) > 1:
        target = intent.waypoints[0]
        if give_distance_2d(here_x, here_z, target[0], target[1]) >= WAYPOINT_DISTANCE:
            break
        intent.waypoints.pop(0)
    target_x, target_z = intent.waypoints[0]
    distance = give_distance_2d(here_x, here_z, target_x, target_z)
    if len(intent.waypoints) == 1 and distance < ARRIVE_DISTANCE:
        return NavDecision(0, target_x, target_z, advance=False, arrived=True)
    joyd = 1  # forward
    modificator = cap_objet(here_x, here_z, actor.beta, target_x, target_z)
    if modificator > 0:
        joyd |= 4   # gere_manual_rot: bit 4 -> direction +1
    elif modificator < 0:
        joyd |= 8   # bit 8 -> direction -1
    return NavDecision(joyd, target_x, target_z, advance=True, arrived=False)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_navigate.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add PyAitD/navigate.py tests/test_navigate.py
git commit -m "feat(navigate): follower decision with a mirrored joystick snapshot"
```

---

### Task 8: tracks — track_mode 4

**Files:**
- Modify: `PyAitD/tracks.py:344-351` (`process_track`)
- Test: `tests/test_tracks.py`

**Interfaces:**
- Consumes: `game.nav_decision` (a `NavDecision` or `None`)
- Produces: `_process_track_mouse(game, actor)`; `process_track` dispatches `track_mode == 4` to it.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_tracks.py
from PyAitD.effects import NavDecision
from PyAitD.tracks import process_track


class _NavGame:
    def __init__(self, decision):
        self.nav_decision = decision
        self.timer = 0


def test_mouse_mode_walks_toward_the_decision_target():
    actor = Actor()
    actor.track_mode = 4
    actor.room_x = actor.room_z = 0
    actor.beta = 0
    game = _NavGame(NavDecision(joyd=1, target_x=0, target_z=9000,
                                advance=True, arrived=False))
    process_track(game, actor)
    assert actor.speed == 4, "an advancing follower walks"


def test_mouse_mode_decelerates_when_there_is_no_decision():
    actor = Actor()
    actor.track_mode = 4
    actor.speed = 4
    process_track(_NavGame(None), actor)
    assert actor.speed == 3, "speed ramps down exactly as manual mode does"


def test_mouse_mode_stops_dead_on_arrival():
    actor = Actor()
    actor.track_mode = 4
    actor.speed = 1
    game = _NavGame(NavDecision(joyd=0, target_x=0, target_z=0,
                                advance=False, arrived=True))
    process_track(game, actor)
    assert actor.speed == 0
    assert actor.direction == 0
    assert actor.rotate.num_steps == 0


def test_manual_mode_is_untouched_by_the_new_branch():
    # mode 1 must remain byte-for-byte the tank behaviour it has always been
    actor = Actor()
    actor.track_mode = 1
    actor.speed = 0
    game = _NavGame(None)
    game.local_joyd = 1
    game.timer = 100
    game._last_time_forward = 0
    process_track(game, actor)
    assert actor.speed == 4
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_tracks.py -q`
Expected: FAIL — `AttributeError: 'Actor' object has no attribute ...` or the
mode-4 tests fail because `process_track` ignores mode 4 and leaves `speed` at 0.

- [ ] **Step 3: Write the implementation**

Add to `PyAitD/tracks.py`, above `process_track`:

```python
def _process_track_mouse(game, actor):
    # Mouse follower mode. Not a FITD track mode: it generalises
    # _process_track_follow (steer toward a point, speed 4) to a waypoint list,
    # so the player turns *while* walking instead of pivoting in place the way
    # tank controls do. The decision itself is made in playworld.apply_play_input.
    decision = getattr(game, "nav_decision", None)
    if decision is None or not decision.advance:
        if 0 < actor.speed <= 4:
            actor.speed -= 1
        else:
            actor.speed = 0
        actor.direction = 0
        actor.rotate.num_steps = 0
        return
    _turn_toward(game, actor, decision.target_x, decision.target_z)
    actor.speed = 4
```

Extend the dispatch in `process_track`:

```python
    elif actor.track_mode == 4:
        _process_track_mouse(game, actor)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_tracks.py -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add PyAitD/tracks.py tests/test_tracks.py
git commit -m "feat(tracks): add mouse follower mode 4 alongside the tank mode"
```

---

### Task 9: playworld — wire the follower into the input snapshot

**Files:**
- Modify: `PyAitD/playworld.py:23-28` (`apply_play_input`)
- Test: `tests/test_playworld.py`

**Interfaces:**
- Consumes: `navigate.decide`, `game.nav_meshes`, `navmesh.agent_extent`, `effects.InputMode`
- Produces: `apply_play_input` now branches on `game.input_mode`; sets `game.nav_decision`; sets `game.nav_arrived_target` when the follower arrives.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_playworld.py
from PyAitD.effects import InputMode, NavIntent
from PyAitD.navmesh import agent_extent
from PyAitD.playworld import apply_play_input


def test_keyboard_mode_still_reads_the_input_buffer(data_dir):
    game = init_game(data_dir, hero=0)
    game.input_mode = InputMode.KEYBOARD
    buf = InputBuffer()
    buf.held_joyd = 5
    buf.action_held = True
    apply_play_input(game, buf)
    assert game.local_joyd == 5
    assert game.action == 0x2000
    assert game.nav_decision is None


def test_mouse_mode_ignores_the_keyboard_buffer(data_dir):
    game = init_game(data_dir, hero=0)
    buf = InputBuffer()
    buf.held_joyd = 5
    apply_play_input(game, buf)
    assert game.local_joyd == 0, "mouse mode must not read held keys"


def test_mouse_mode_mirrors_the_follower_joystick(data_dir):
    game = init_game(data_dir, hero=0)
    hero = game.actors[game.current_camera_target_actor]
    game.nav_intent = NavIntent(
        dest_x=hero.room_x, dest_z=hero.room_z + 9000, room=hero.room,
        waypoints=[(hero.room_x, hero.room_z + 9000)],
    )
    apply_play_input(game, InputBuffer())
    assert game.nav_decision is not None
    assert game.local_joyd & 1, "scripts reading evalVar 0x13 must see movement"


def test_hero_walks_toward_a_destination_over_real_ticks(data_dir):
    game = init_game(data_dir, hero=0)
    floor = Floor(data_dir, game.current_floor)
    hero = game.actors[game.current_camera_target_actor]
    hero.track_mode = 4
    mesh = game.nav_meshes.mesh_for(floor, hero.room, agent_extent(hero))
    goal = mesh.center_of(145, 78)          # the type-10 sce zone, component 0
    start = (hero.room_x, hero.room_z)
    game.nav_intent = NavIntent(goal[0], goal[1], hero.room)
    buf = InputBuffer()
    for _ in range(400):
        if not play_tick(game, floor, buf):
            break
        if game.nav_intent is None:
            break
    moved = abs(hero.room_x - start[0]) + abs(hero.room_z - start[1])
    assert moved > 500, f"the hero barely moved ({moved} units)"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_playworld.py -q`
Expected: FAIL — `ImportError: cannot import name 'apply_play_input'` is
available, but mouse-mode assertions fail because `apply_play_input` still
reads the buffer unconditionally.

- [ ] **Step 3: Write the implementation**

Replace `apply_play_input` in `PyAitD/playworld.py`:

```python
def apply_play_input(game, input_buffer):
    if game.input_mode is InputMode.MOUSE:
        _apply_mouse_input(game)
        return
    game.nav_decision = None
    game.local_joyd = input_buffer.held_joyd if input_buffer.focused else 0
    game.local_click = 1 if input_buffer.focused and input_buffer.action_held else 0
    game.local_key = 0
    game.action = 0x2000 if game.local_click else 0


def _apply_mouse_input(game):
    # The follower decision is made here, in the input snapshot, so the tick
    # order stays exactly FITD's mainLoop order and the mouse is a peer of the
    # keyboard rather than a bolt-on.
    game.local_key = 0
    game.local_click = 0
    game.action = 0
    hero_idx = game.current_camera_target_actor
    if hero_idx == -1 or game.nav_intent is None:
        game.nav_decision = None
        game.local_joyd = 0
        return
    hero = game.actors[hero_idx]
    mesh = game.nav_meshes.mesh_for(game.current_floor_data, hero.room, agent_extent(hero))
    decision = decide(game, hero, mesh)
    game.nav_decision = decision
    game.local_joyd = decision.joyd if decision is not None else 0
    if decision is not None and decision.arrived:
        game.nav_arrived_target = game.nav_intent.target_object_idx
        game.nav_intent = None
        game.nav_decision = None
        game.local_joyd = 0
```

`_apply_mouse_input` needs the `Floor` to build meshes, but `play_tick` receives
it as a parameter. Store it on the game at the top of `play_tick` so the input
snapshot can reach it without changing the signature:

```python
def play_tick(game, floor, input_buffer):
    if game.mode is not GameMode.PLAY:
        return False
    game.current_floor_data = floor   # the mesh cache needs the loaded Floor
    apply_play_input(game, input_buffer)
```

Add `self.current_floor_data = None` to `Game.__init__` next to the other nav
fields, and add these imports to `playworld.py`:

```python
from PyAitD.effects import GameMode, InputMode, LifeFrame
from PyAitD.navigate import decide
from PyAitD.navmesh import agent_extent
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_playworld.py -q`
Expected: all passed (including the existing purity test — `navigate`, `navmesh`
and `effects` are all pygame-free)

- [ ] **Step 5: Commit**

```bash
git add PyAitD/playworld.py PyAitD/game.py tests/test_playworld.py
git commit -m "feat(playworld): drive the follower from the input snapshot"
```

---

### Task 10: interaction — widen the player-controlled gate

**Files:**
- Modify: `PyAitD/interaction.py:220`
- Test: `tests/test_interaction.py`

**Interfaces:** no new symbols; behaviour change only.

This task exists on its own because it is the one change that fails **silently**:
with the hero in mode 4, `AF_FOUNDABLE` contact stops raising `ShowFound` and
pickups just quietly stop working, with no error anywhere.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_interaction.py
from PyAitD.effects import ShowFound
from PyAitD.game import AF_FOUNDABLE
from PyAitD.interaction import resolve_actor_contacts


def _foundable_pair(game):
    hero_idx = game.current_camera_target_actor
    hero = game.actors[hero_idx]
    other_idx = next(
        i for i, a in enumerate(game.actors)
        if a.index_in_world >= 0 and i != hero_idx
    )
    other = game.actors[other_idx]
    other.object_type |= AF_FOUNDABLE
    other.room = hero.room
    other.zv = list(hero.zv)          # overlapping, so contact is guaranteed
    return hero_idx, hero, other_idx


def test_mouse_mode_hero_still_triggers_found_on_contact(data_dir):
    # the gate was `track_mode == 1`; mode 4 is equally player-controlled
    game = init_game(data_dir)
    hero_idx, hero, _other = _foundable_pair(game)
    hero.track_mode = 4
    resolve_actor_contacts(game, hero_idx, list(hero.zv), list(hero.zv), 0, 0)
    assert isinstance(game.active_modal, ShowFound)


def test_tank_mode_hero_still_triggers_found_on_contact(data_dir):
    game = init_game(data_dir)
    hero_idx, hero, _other = _foundable_pair(game)
    hero.track_mode = 1
    resolve_actor_contacts(game, hero_idx, list(hero.zv), list(hero.zv), 0, 0)
    assert isinstance(game.active_modal, ShowFound)


def test_scripted_actor_does_not_trigger_found(data_dir):
    game = init_game(data_dir)
    hero_idx, hero, _other = _foundable_pair(game)
    hero.track_mode = 3          # scripted track: not player-controlled
    resolve_actor_contacts(game, hero_idx, list(hero.zv), list(hero.zv), 0, 0)
    assert game.active_modal is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_interaction.py -q`
Expected: FAIL on `test_mouse_mode_hero_still_triggers_found_on_contact` —
`assert None is instance of ShowFound`

- [ ] **Step 3: Write the implementation**

In `PyAitD/interaction.py`, change the gate at line 220:

```python
            if actor.track_mode in PLAYER_TRACK_MODES and game.active_modal is None:
```

and define near the top of the module, under the existing constants:

```python
# FITD gates found-contact on trackMode == 1, meaning "manually controlled".
# Mode 4 (mouse follower) is equally player-controlled, so it belongs here too.
PLAYER_TRACK_MODES = (1, 4)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_interaction.py -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add PyAitD/interaction.py tests/test_interaction.py
git commit -m "fix(interaction): treat the mouse follower as player-controlled

Contact pickup was gated on track_mode == 1, so switching the hero to the
mouse follower would have stopped AF_FOUNDABLE contact firing with no error."
```

---

### Task 11: interaction — click intent and arrival dispatch

**Files:**
- Modify: `PyAitD/interaction.py`, `PyAitD/playworld.py` (`play_tick`)
- Test: `tests/test_interaction.py`

**Interfaces:**
- Produces: `apply_click_intent(game, dest_x, dest_z, room, target_object_idx=-1) -> None`, `cancel_nav_intent(game) -> None`, `dispatch_nav_arrival(game) -> bool` (False when it opened a modal, matching the other `play_tick` helpers).

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_interaction.py
from PyAitD.effects import NavIntent
from PyAitD.interaction import (
    apply_click_intent, cancel_nav_intent, dispatch_nav_arrival,
)


def test_apply_click_intent_replaces_any_previous_intent(data_dir):
    game = init_game(data_dir)
    apply_click_intent(game, 100, 200, 0)
    apply_click_intent(game, 300, 400, 0)
    assert (game.nav_intent.dest_x, game.nav_intent.dest_z) == (300, 400)
    assert game.nav_intent.waypoints is None, "a new click re-paths from scratch"


def test_cancel_clears_intent_and_decision(data_dir):
    game = init_game(data_dir)
    apply_click_intent(game, 100, 200, 0)
    game.nav_decision = object()
    cancel_nav_intent(game)
    assert game.nav_intent is None and game.nav_decision is None


def test_arrival_at_a_foundable_target_opens_that_object_s_prompt(data_dir):
    # the accessibility win: the prompt is for the object that was CLICKED,
    # not for whatever ZV the hero happened to overlap on the way
    game = init_game(data_dir)
    target = next(
        i for i, w in enumerate(game.world_objects)
        if w.obj_index != -1 and game.actors[w.obj_index].object_type & AF_FOUNDABLE
    )
    game.nav_arrived_target = target
    completed = dispatch_nav_arrival(game)
    assert completed is False, "opening a modal suspends the tick"
    assert isinstance(game.active_modal, ShowFound)
    assert game.active_modal.object_idx == target
    assert game.nav_arrived_target == -1, "arrival is consumed exactly once"


def test_arrival_without_a_target_sets_the_action_bit(data_dir):
    game = init_game(data_dir)
    game.nav_arrived_target = -1
    game.nav_intent = None
    game.nav_arrived_plain = True
    assert dispatch_nav_arrival(game) is True
    assert game.action == 0x2000, "a bare floor arrival presses Action once"


def test_arrival_on_a_despawned_target_is_dropped(data_dir):
    game = init_game(data_dir)
    target = next(i for i, w in enumerate(game.world_objects) if w.obj_index == -1)
    game.nav_arrived_target = target
    assert dispatch_nav_arrival(game) is True
    assert game.active_modal is None
    assert game.nav_arrived_target == -1


def test_no_dispatch_while_a_modal_is_open(data_dir):
    game = init_game(data_dir)
    game.open_modal(ShowFound(object_idx=0, forced_refuse=False))
    game.nav_arrived_target = 5
    assert dispatch_nav_arrival(game) is True
    assert game.active_modal.object_idx == 0, "the open modal is untouched"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_interaction.py -q`
Expected: FAIL — `ImportError: cannot import name 'apply_click_intent'`

- [ ] **Step 3: Write the implementation**

Append to `PyAitD/interaction.py`:

```python
def apply_click_intent(game, dest_x, dest_z, room, target_object_idx=-1):
    """Record where the player clicked. A new click replaces any previous one."""
    from PyAitD.effects import NavIntent
    game.nav_intent = NavIntent(dest_x, dest_z, room, target_object_idx)
    game.nav_decision = None


def cancel_nav_intent(game):
    """Drop the current intent. Used on modal entry and on a stop click."""
    game.nav_intent = None
    game.nav_decision = None
    game.nav_arrived_plain = False


def dispatch_nav_arrival(game):
    """Act on a follower arrival. False when a modal was opened (tick suspends)."""
    target = game.nav_arrived_target
    plain = getattr(game, "nav_arrived_plain", False)
    game.nav_arrived_target = -1
    game.nav_arrived_plain = False
    if game.active_modal is not None:
        return True
    if target == -1:
        if plain:
            # a bare floor arrival still presses Action once, exactly as the
            # keyboard action button does; scripts read it via evalVar 0x11
            game.action = 0x2000
        return True
    world = game.world_objects[target]
    if world.obj_index == -1:
        return True  # taken or despawned while we walked
    actor = game.actors[world.obj_index]
    if actor.object_type & AF_FOUNDABLE:
        effect = request_found(game, target, parameter=0)
        if effect is not None:
            game.open_modal(effect)
            return False
        return True
    game.action = 0x2000
    return True
```

`interaction.py` imports game constants *inside* functions by convention (see
`resolve_actor_contacts`). Follow it: put `from PyAitD.game import AF_FOUNDABLE`
at the top of `dispatch_nav_arrival`'s body, not at module scope.

In `PyAitD/playworld.py`, call the dispatch immediately after the input
snapshot, before `game_step_tick`:

```python
    apply_play_input(game, input_buffer)
    if not dispatch_nav_arrival(game):
        return False
    game_step_tick(game)
```

and extend the `interaction` import list with `dispatch_nav_arrival`.

Set `nav_arrived_plain` in `playworld._apply_mouse_input` where arrival is
detected — replace the arrival block with:

```python
    if decision is not None and decision.arrived:
        game.nav_arrived_target = game.nav_intent.target_object_idx
        game.nav_arrived_plain = game.nav_intent.target_object_idx == -1
        game.nav_intent = None
        game.nav_decision = None
        game.local_joyd = 0
```

and add `self.nav_arrived_plain = False` to `Game.__init__`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_interaction.py tests/test_playworld.py -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add PyAitD/interaction.py PyAitD/playworld.py PyAitD/game.py tests/test_interaction.py
git commit -m "feat(interaction): dispatch click targets on follower arrival"
```

---

### Task 12: __main__ — route clicks during PLAY

**Files:**
- Modify: `PyAitD/__main__.py:137-180` (`route_mouse`), `:222-294` (`run`), `PyAitD/ui.py:32-63` (`event_to_input`)
- Test: `tests/test_play_loop.py`, `tests/test_ui_input.py`

**Interfaces:**
- Produces: `route_play_click(game, floor, logical_pos, draw_list) -> None` in `__main__.py`; `Command.TOGGLE_INPUT_MODE` in `ui.py`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_play_loop.py
from PyAitD.__main__ import route_play_click
from PyAitD.effects import InputMode


def test_a_floor_click_becomes_a_walk_intent(data_dir):
    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.num_camera = game.new_num_camera
    hero = game.actors[game.current_camera_target_actor]
    screen = project_floor_point(
        _state_for(floor, hero.room, game.num_camera),
        hero.room_x + 1500, hero.world_y, hero.room_z,
    )
    route_play_click(game, floor, (int(screen[0]), int(screen[1])), [])
    assert game.nav_intent is not None
    assert game.nav_intent.target_object_idx == -1


def test_a_click_on_an_actor_becomes_a_target_intent(data_dir):
    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.num_camera = game.new_num_camera
    other_idx = next(
        i for i, a in enumerate(game.actors)
        if a.index_in_world >= 0 and i != game.current_camera_target_actor
    )
    draw_list = [(other_idx, (100, 60, 200, 160))]
    route_play_click(game, floor, (150, 100), draw_list)
    assert game.nav_intent is not None
    assert game.nav_intent.target_object_idx == game.actors[other_idx].index_in_world


def test_a_click_on_nothing_leaves_the_intent_alone(data_dir):
    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.num_camera = game.new_num_camera
    route_play_click(game, floor, (2, 2), [])
    assert game.nav_intent is None
```

```python
# append to tests/test_ui_input.py
def test_tab_requests_an_input_mode_toggle():
    state = InputBuffer()
    event_to_input(_key_down(pygame.K_TAB), state)
    assert Command.TOGGLE_INPUT_MODE in state.commands
```

Use the existing `_key_down` helper in that file; if it does not exist, build the
event with `pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB, repeat=False)`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_play_loop.py tests/test_ui_input.py -q`
Expected: FAIL — `ImportError: cannot import name 'route_play_click'`

- [ ] **Step 3: Write the implementation**

In `PyAitD/ui.py`, add `TOGGLE_INPUT_MODE = auto()` to `Command`, and in
`event_to_input`'s `KEYDOWN` branch add:

```python
        elif not repeated and event.key == pygame.K_TAB:
            state.commands.append(Command.TOGGLE_INPUT_MODE)
```

In `PyAitD/__main__.py`, add:

```python
def _state_for(floor, room_idx, cam_slot):
    from PyAitD.world import CameraState
    room = floor.rooms[room_idx]
    camera = floor.cameras[room.camera_indices[cam_slot]]
    return CameraState.from_camera(
        camera, room.world_x, room.world_y, room.world_z,
    ).angles()


def route_play_click(game, floor, logical_pos, draw_list):
    """A left click during PLAY: pick an object, else a floor point, else nothing."""
    from PyAitD.interaction import apply_click_intent
    from PyAitD.navmesh import agent_extent, nearest_walkable
    from PyAitD.picking import pick_actor, pick_floor
    if logical_pos is None or game.active_modal is not None:
        return
    hero_idx = game.current_camera_target_actor
    if hero_idx == -1 or game.num_camera == -1:
        return
    hero = game.actors[hero_idx]

    actor_idx = pick_actor(logical_pos, [
        (idx, box) for idx, box in draw_list
        if idx != hero_idx and _is_interactable(game, idx)
    ])
    if actor_idx is not None:
        target = game.actors[actor_idx]
        apply_click_intent(
            game, target.room_x, target.room_z, target.room,
            target_object_idx=target.index_in_world,
        )
        return

    picked = pick_floor(logical_pos, floor, hero.room, game.num_camera, hero.world_y)
    if picked is None:
        return
    mesh = game.nav_meshes.mesh_for(floor, hero.room, agent_extent(hero))
    if mesh is not None:
        snapped = nearest_walkable(mesh, picked[0], picked[1])
        if snapped is not None:
            picked = snapped
    apply_click_intent(game, picked[0], picked[1], hero.room)


def _is_interactable(game, actor_idx):
    from PyAitD.game import AF_FOUNDABLE
    actor = game.actors[actor_idx]
    if actor.index_in_world < 0:
        return False
    if actor.object_type & AF_FOUNDABLE:
        return True
    return game.world_objects[actor.index_in_world].found_life != -1
```

In `run()`, extend the mouse branch of the event loop:

```python
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                logical = renderer.window_to_logical(event.pos)
                if game.active_modal is None and game.mode is GameMode.PLAY:
                    route_play_click(game, floor, logical, draw_list)
                else:
                    running = route_mouse(game, session, logical) and running
```

In `route_command`, handle the toggle before the PLAY branch:

```python
    if command is Command.TOGGLE_INPUT_MODE:
        from PyAitD.interaction import cancel_nav_intent
        game.input_mode = (
            InputMode.KEYBOARD if game.input_mode is InputMode.MOUSE else InputMode.MOUSE
        )
        cancel_nav_intent(game)
        hero_idx = game.current_camera_target_actor
        if hero_idx != -1:
            game.actors[hero_idx].track_mode = (
                4 if game.input_mode is InputMode.MOUSE else 1
            )
        return True
```

Add `InputMode` to the `effects` import in `__main__.py`.

Finally, in the `was_play and game.mode is not GameMode.PLAY` block that already
flushes queued commands on modal entry, also cancel the intent:

```python
            input_buffer.commands.clear()
            from PyAitD.interaction import cancel_nav_intent
            cancel_nav_intent(game)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add PyAitD/__main__.py PyAitD/ui.py tests/test_play_loop.py tests/test_ui_input.py
git commit -m "feat: route play-mode clicks into walk and target intents"
```

---

### Task 13: cross-room clicks (one hop)

**Files:**
- Modify: `PyAitD/picking.py`, `PyAitD/navigate.py`, `PyAitD/__main__.py` (`route_play_click`)
- Test: `tests/test_picking.py`, `tests/test_navigate.py`

**Why this exists:** a camera's `viewed_rooms` can include neighbouring rooms, so
a click can legitimately land on floor that belongs to a different room than the
one the hero stands in. Each room has its own coordinate origin, so the picked
point is meaningless until it is attributed to the right room.

**Interfaces:**
- Produces: `picking.pick_floor_in_room(logical_pos, floor, room_idx, global_cam_idx, floor_y) -> (x, z) | None`; `picking.pick_floor_any_room(logical_pos, floor, hero_room, cam_slot, floor_y) -> (x, z, room) | None`. `pick_floor` from Task 4 becomes a thin wrapper and keeps its signature and behaviour.
- `NavIntent` gains a `path_room` attribute set by `navigate._repath`, so the follower knows which room its waypoints were computed for.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_picking.py
from PyAitD.picking import pick_floor_any_room, pick_floor_in_room


def test_pick_floor_in_room_uses_that_room_s_own_origin(data_dir):
    # room 0 of floor 0 is the only room, so the global-camera form must agree
    # exactly with the slot form it generalises
    floor = Floor(data_dir, 0)
    game = init_game(data_dir)
    floor_y = game.actors[game.current_camera_target_actor].world_y
    global_cam = floor.rooms[0].camera_indices[0]
    state = _state(floor, 0, 0)
    poly = cover_polys(floor, 0)[0]
    xs = [p[0] * COVER_SCALE for p in poly]
    zs = [p[1] * COVER_SCALE for p in poly]
    centre = (sum(xs) // len(xs), sum(zs) // len(zs))
    screen = project_floor_point(state, centre[0], floor_y, centre[1])
    assert pick_floor_in_room(screen, floor, 0, global_cam, floor_y) == \
        pick_floor(screen, floor, 0, 0, floor_y)


def test_pick_floor_any_room_reports_which_room_it_hit(data_dir):
    floor = Floor(data_dir, 0)
    game = init_game(data_dir)
    floor_y = game.actors[game.current_camera_target_actor].world_y
    state = _state(floor, 0, 0)
    poly = cover_polys(floor, 0)[0]
    xs = [p[0] * COVER_SCALE for p in poly]
    zs = [p[1] * COVER_SCALE for p in poly]
    screen = project_floor_point(state, sum(xs) // len(xs), floor_y, sum(zs) // len(zs))
    hit = pick_floor_any_room(screen, floor, 0, 0, floor_y)
    assert hit is not None and hit[2] == 0


def test_pick_floor_any_room_prefers_the_hero_s_own_room(data_dir):
    # a multi-room floor: whichever room the hero is in must win a tie, because
    # walking within the current room never needs a transition
    floor = Floor(data_dir, 1)
    game = init_game(data_dir)
    floor_y = 0
    for slot in range(len(floor.rooms[0].camera_indices)):
        state = _state(floor, 0, slot)
        polys = cover_polys(floor, 0)
        if not polys:
            continue
        xs = [p[0] * COVER_SCALE for p in polys[0]]
        zs = [p[1] * COVER_SCALE for p in polys[0]]
        screen = project_floor_point(state, sum(xs) // len(xs), floor_y, sum(zs) // len(zs))
        if screen is None:
            continue
        hit = pick_floor_any_room(screen, floor, 0, slot, floor_y)
        if hit is not None:
            assert hit[2] == 0
            return
    raise AssertionError("no camera of floor 1 room 0 produced a pick")
```

```python
# append to tests/test_navigate.py
def test_a_destination_in_another_room_steers_to_the_room_link():
    # the follower must not path straight at coordinates that belong to a
    # different room's origin; it aims for the link zone first
    class _LinkGame(_Game):
        def __init__(self, intent):
            super().__init__(intent)
            self.link_asked = None

    intent = NavIntent(dest_x=500, dest_z=500, room=3, waypoints=None)
    game = _LinkGame(intent)
    actor = _actor(0, 0, room=0)

    import PyAitD.navigate as navigate_module

    class _Zone:
        x1, x2, y1, y2, z1, z2, type, parameter = 100, 300, 0, 0, 700, 900, 4, 3

    original = navigate_module.get_room_link
    navigate_module.get_room_link = lambda g, a, b: (
        setattr(g, "link_asked", (a, b)) or _Zone()
    )
    try:
        decision = navigate_module.decide(game, actor, None)
    finally:
        navigate_module.get_room_link = original

    assert game.link_asked == (0, 3)
    assert (decision.target_x, decision.target_z) == (200, 800)  # zone centre
    assert intent.path_room == 0, "waypoints belong to the room we started in"


def test_entering_the_target_room_repaths_to_the_real_destination():
    intent = NavIntent(dest_x=500, dest_z=500, room=3, waypoints=[(9, 9)])
    intent.path_room = 0
    game = _Game(intent)
    actor = _actor(0, 0, room=3)          # gere_dec moved us into room 3
    decision = decide(game, actor, None)
    assert intent.path_room == 3
    assert (decision.target_x, decision.target_z) == (500, 500)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_picking.py tests/test_navigate.py -q`
Expected: FAIL — `ImportError: cannot import name 'pick_floor_in_room'`

- [ ] **Step 3: Write the implementation**

In `PyAitD/picking.py`, replace `_camera_state` and `pick_floor` with a
room-explicit pair, keeping `pick_floor`'s existing signature intact:

```python
def _camera_state_global(floor, room_idx, global_cam_idx):
    # the camera is addressed globally, but the transform is built from the
    # ORIGIN OF THE ROOM BEING PICKED — each room has its own coordinate space
    room = floor.rooms[room_idx]
    camera = floor.cameras[global_cam_idx]
    return CameraState.from_camera(
        camera, room.world_x, room.world_y, room.world_z,
    ).angles()


def pick_floor_in_room(logical_pos, floor, room_idx, global_cam_idx, floor_y):
    """Logical click -> room-scale (x, z) in room_idx's own coordinate space."""
    state = _camera_state_global(floor, room_idx, global_cam_idx)
    for poly in cover_polys(floor, room_idx):
        world = [(x * COVER_SCALE, z * COVER_SCALE) for x, z in poly]
        matrix = floor_homography(state, world, floor_y)
        if matrix is None:
            continue
        try:
            inverse = np.linalg.inv(matrix)
        except np.linalg.LinAlgError:
            continue
        recovered = _apply(inverse, float(logical_pos[0]), float(logical_pos[1]))
        if recovered is None:
            continue
        wx, wz = int(round(recovered[0])), int(round(recovered[1]))
        forward = _apply(matrix, wx, wz)
        if forward is None:
            continue
        if abs(forward[0] - logical_pos[0]) > 2 or abs(forward[1] - logical_pos[1]) > 2:
            continue
        if _point_in_world_poly(wx, wz, world):
            return (wx, wz)
    return None


def pick_floor(logical_pos, floor, room_idx, cam_slot, floor_y):
    """Room-slot form. Kept for callers that already know the room."""
    global_cam_idx = floor.rooms[room_idx].camera_indices[cam_slot]
    return pick_floor_in_room(logical_pos, floor, room_idx, global_cam_idx, floor_y)


def pick_floor_any_room(logical_pos, floor, hero_room, cam_slot, floor_y):
    """Pick across every room this camera views. Returns (x, z, room) or None.

    The hero's own room is tried first: walking inside the current room never
    needs a transition, so it wins any overlap.
    """
    global_cam_idx = floor.rooms[hero_room].camera_indices[cam_slot]
    viewed = [vr.viewed_room_idx for vr in floor.cameras[global_cam_idx].viewed_rooms]
    ordered = [hero_room] + [r for r in viewed if r != hero_room]
    for room_idx in ordered:
        if room_idx >= len(floor.rooms):
            continue
        hit = pick_floor_in_room(logical_pos, floor, room_idx, global_cam_idx, floor_y)
        if hit is not None:
            return (hit[0], hit[1], room_idx)
    return None
```

In `PyAitD/navigate.py`, add `from PyAitD.tracks import cap_objet, get_room_link`
to the imports and replace `_repath`:

```python
def _repath(game, actor, mesh):
    intent = game.nav_intent
    intent.path_room = actor.room
    start = (actor.room_x + actor.step_x, actor.room_z + actor.step_z)
    if intent.room != actor.room:
        # One hop: aim for the centre of the zone linking us to the target room,
        # exactly as _process_track_follow does for a followed actor in another
        # room. gere_dec performs the actual transition when we cross it; the
        # room change then re-paths us to the real destination below.
        link = get_room_link(game, actor.room, intent.room)
        intent.waypoints = [(
            link.x1 + (link.x2 - link.x1) // 2,
            link.z1 + (link.z2 - link.z1) // 2,
        )]
        return
    goal = (intent.dest_x, intent.dest_z)
    if mesh is not None:
        path = find_path(mesh, start, goal)
        if path:
            intent.waypoints = list(path)
            return
    # degraded mode: no mesh, hero off-mesh, or no route — steer straight at the
    # click and let the engine's own collision slide do what A* would not
    intent.waypoints = [goal]
```

and, at the top of `decide`, re-path whenever the room changed underneath us:

```python
    if intent.waypoints is None or getattr(intent, "path_room", None) != actor.room:
        _repath(game, actor, mesh)
```

In `PyAitD/effects.py`, add `path_room: int = -1` to `NavIntent`.

In `__main__.route_play_click`, use the any-room form:

```python
    picked = pick_floor_any_room(
        logical_pos, floor, hero.room, game.num_camera, hero.world_y,
    )
    if picked is None:
        return
    dest_x, dest_z, dest_room = picked
    if dest_room == hero.room:
        mesh = game.nav_meshes.mesh_for(floor, hero.room, agent_extent(hero))
        if mesh is not None:
            snapped = nearest_walkable(mesh, dest_x, dest_z)
            if snapped is not None:
                dest_x, dest_z = snapped
    apply_click_intent(game, dest_x, dest_z, dest_room)
```

changing its import to `from PyAitD.picking import pick_actor, pick_floor_any_room`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add PyAitD/picking.py PyAitD/navigate.py PyAitD/effects.py PyAitD/__main__.py \
        tests/test_picking.py tests/test_navigate.py
git commit -m "feat: resolve clicks that land in a neighbouring room"
```

---

### Task 14: hover cursor, the mouse proof harness, and docs

**Files:**
- Modify: `PyAitD/ui.py`, `PyAitD/__main__.py`, `Makefile`, `CONTEXT.md`, `README.md`
- Create: `docs/m3d-mouse-input-proof.md`
- Test: `tests/test_ui_render.py`

**Interfaces:**
- Produces: `ui.render_cursor(frame, logical_pos, kind) -> frame` where `kind` is `"walk"`, `"target"` or `"blocked"`; `make prove-mouse`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_ui_render.py
import numpy as np

from PyAitD.ui import render_cursor


def test_cursor_marks_the_frame_without_mutating_the_input():
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    out = render_cursor(frame, (160, 100), "walk")
    assert out is not frame, "presentation must not mutate the scene frame"
    assert int(out.sum()) > 0, "the cursor drew nothing"
    assert int(frame.sum()) == 0


def test_cursor_kinds_differ():
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    walk = render_cursor(frame, (160, 100), "walk")
    blocked = render_cursor(frame, (160, 100), "blocked")
    assert not np.array_equal(walk, blocked)


def test_cursor_outside_the_surface_is_a_no_op():
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    assert np.array_equal(render_cursor(frame, None, "walk"), frame)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_render.py -q`
Expected: FAIL — `ImportError: cannot import name 'render_cursor'`

- [ ] **Step 3: Write the implementation**

Add to `PyAitD/ui.py`:

```python
_CURSOR_COLORS = {
    "walk": (200, 230, 170),
    "target": (255, 220, 130),
    "blocked": (190, 90, 80),
}


def render_cursor(frame, logical_pos, kind):
    """Draw the pick cursor. Pure presentation: never touches world state."""
    if logical_pos is None:
        return frame
    surface = _to_surface(frame.copy())
    color = _CURSOR_COLORS.get(kind, _CURSOR_COLORS["walk"])
    x, y = int(logical_pos[0]), int(logical_pos[1])
    if kind == "target":
        pygame.draw.rect(surface, color, pygame.Rect(x - 5, y - 5, 11, 11), width=1)
    elif kind == "blocked":
        pygame.draw.line(surface, color, (x - 4, y - 4), (x + 4, y + 4))
        pygame.draw.line(surface, color, (x - 4, y + 4), (x + 4, y - 4))
    else:
        pygame.draw.circle(surface, color, (x, y), 4, width=1)
    return _to_frame(surface)
```

In `__main__.py`'s `run()`, track the last motion position and classify it once
per frame, then draw it on top of the composed frame:

```python
            if event.type == pygame.MOUSEMOTION:
                hover = renderer.window_to_logical(event.pos)
```

Initialise `hover = None` before the loop, and change the present call to:

```python
        composed = render_active_mode(game, session, scene_frame)
        if game.mode is GameMode.PLAY and game.active_modal is None:
            composed = render_cursor(composed, hover, _hover_kind(game, floor, hover, draw_list))
        renderer.present(composed)
```

with:

```python
def _hover_kind(game, floor, logical_pos, draw_list):
    from PyAitD.navmesh import agent_extent
    from PyAitD.picking import pick_actor, pick_floor
    if logical_pos is None or game.num_camera == -1:
        return "blocked"
    hero_idx = game.current_camera_target_actor
    if hero_idx == -1:
        return "blocked"
    hero = game.actors[hero_idx]
    if pick_actor(logical_pos, [
        (idx, box) for idx, box in draw_list
        if idx != hero_idx and _is_interactable(game, idx)
    ]) is not None:
        return "target"
    picked = pick_floor(logical_pos, floor, hero.room, game.num_camera, hero.world_y)
    if picked is None:
        return "blocked"
    mesh = game.nav_meshes.mesh_for(floor, hero.room, agent_extent(hero))
    if mesh is None or mesh.is_walkable(*picked):
        return "walk"
    from PyAitD.navmesh import nearest_walkable
    return "walk" if nearest_walkable(mesh, *picked) else "blocked"
```

Add `render_cursor` to the `ui` import in `__main__.py`.

- [ ] **Step 4: Add the proof harness**

Create `tools/prove_mouse.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Build the navmesh for every camera-visible room on every floor.

Reports walkable counts. Near-empty cave rooms are a KNOWN boundary (type-3
climbable walls tile their cover area and nothing consumes hard_col == 255
yet), so they are reported, not failed on.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PyAitD.floor import Floor
from PyAitD.game import init_game
from PyAitD.navmesh import agent_extent, build_room_mesh

DEFAULT_DATA = (
    pathlib.Path(__file__).resolve().parent.parent
    / "Alone in the Dark 1.app" / "Contents" / "Resources" / "game" / "INDARK"
)


def main(argv):
    data = pathlib.Path(argv[0]) if argv else DEFAULT_DATA
    game = init_game(data)
    agent = agent_extent(game.actors[game.current_camera_target_actor])
    built = skipped = empty = 0
    for number in range(8):
        floor = Floor(data, number)
        for room_idx, room in enumerate(floor.rooms):
            mesh = build_room_mesh(floor, room_idx, agent)
            if mesh is None:
                skipped += 1
                print(f"floor {number} room {room_idx:2d}: no camera views it — skipped")
                continue
            built += 1
            count = int(mesh.walkable.sum())
            note = ""
            if count == 0:
                empty += 1
                note = "  <- EMPTY (known: climbable-wall floor)"
            print(f"floor {number} room {room_idx:2d}: {mesh.shape} "
                  f"walkable {count}{note}")
    print(f"\nbuilt {built} meshes, {skipped} rooms without cameras, {empty} empty")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

Add to the `Makefile`, next to `prove-m3b`:

```make
prove-mouse:
	$(PY) tools/prove_mouse.py $(if $(data),"$(data)",)
```

Run: `make prove-mouse`
Expected: every camera-visible room builds; the four camera-less rooms are
skipped; cave rooms may report EMPTY without failing.

- [ ] **Step 5: Update the docs**

In `CONTEXT.md`, add to the architecture table:

```
| `navmesh.py` | Walkable grid from cover zones (FITD `is_in_poly` vectorised) + A* |
| `picking.py` | Screen->world: floor homography fitted from the real projection, actor bbox hit-test |
| `navigate.py` | Mouse follower: NavIntent -> one tick of steering + mirrored joyd |
```

Add a milestone row: `| M3d | Mouse-only point-and-click input | done |`, and a
line under "M3b interaction boundary" noting `make prove-mouse`.

In `README.md`, update the controls paragraph:

```
Mouse (default): left-click the floor to walk there, left-click an object to
approach and use it. Tab switches to the keyboard scheme (arrows/WASD walk,
Space acts) and back. Menus accept both throughout.
```

Create `docs/m3d-mouse-input-proof.md` recording manual evidence: walk across
the attic by clicking, click the foundable object and confirm the Take/Leave
prompt names *that* object, Tab back to keyboard and confirm tank movement is
unchanged, and note the observed feel of turn-while-walking versus the old
pivot-then-walk.

- [ ] **Step 6: Run the full gate**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest -q && make prove && make prove-mouse`
Expected: all green

- [ ] **Step 7: Commit**

```bash
git add PyAitD/ui.py PyAitD/__main__.py tools/prove_mouse.py Makefile \
        CONTEXT.md README.md docs/m3d-mouse-input-proof.md tests/test_ui_render.py
git commit -m "feat(ui): hover cursor, mouse proof harness and docs"
```

---

## Risks carried from the spec

- **Cave floors (5, 6) will report near-empty meshes.** Expected, not a defect:
  type-3 climbable walls tile their cover area and nothing consumes
  `hard_col == 255` yet. Degraded direct steering keeps the mouse usable.
- **The picking round-trip is only proven on floor 0's five cameras**, since no
  other floor boots in this port today. If Task 4's round-trip fails on another
  floor later, investigate the residual — do not widen the tolerance.
- **Multi-component rooms** may leave a reachable-looking destination
  unreachable by A*. Handled by degraded mode case 3, but worth watching in play.
