# SPDX-License-Identifier: GPL-2.0-only
import subprocess
import sys

from PyAitD.engine.actors import cube_intersect
from PyAitD.engine.floor import Floor
from PyAitD.engine.game import init_game
from PyAitD.engine.navmesh import COVER_SCALE, GRID_STEP, agent_extent, build_cover_grid, build_room_mesh, cover_polys
from PyAitD.engine.world import is_in_poly

_PURITY_PROBE = """
import sys, PyAitD.engine.navmesh
leaked = {"PyAitD.app.ui", "PyAitD.render.render", "pygame", "moderngl", "OpenGL"} & sys.modules.keys()
sys.exit(", ".join(sorted(leaked)) or None)
"""


def test_navmesh_does_not_import_the_presentation_layer():
    out = subprocess.run([sys.executable, "-c", _PURITY_PROBE], capture_output=True, text=True)
    assert out.returncode == 0, (
        f"PyAitD.engine.navmesh pulled in {out.stderr.strip()} — the mesh must stay "
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


import numpy as np

from PyAitD.engine.navmesh import (
    TARGET_SNAP_CELLS, MeshCache, RoomMesh, approach_cell, find_path, nearest_walkable,
)


def _segment_is_walkable(mesh, p, q):
    """Sample the straight segment between two room-scale points at grid
    resolution and refuse a diagonal step that cuts a blocked corner —
    independent of _line_clear's own implementation, so this genuinely
    exercises "walkable throughout" rather than restating the production
    code under test.
    """
    a, b = mesh.cell_of(*p), mesh.cell_of(*q)
    if a is None or b is None:
        return False
    steps = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
    if not mesh.walkable[a]:
        return False
    prev = a
    for k in range(1, steps + 1):
        i = round(a[0] + (b[0] - a[0]) * k / steps)
        j = round(a[1] + (b[1] - a[1]) * k / steps)
        if not mesh.walkable[i, j]:
            return False
        di, dj = i - prev[0], j - prev[1]
        if di and dj and not (mesh.walkable[i, prev[1]] and mesh.walkable[prev[0], j]):
            return False  # a follower tracing this edge would clip the corner
        prev = (i, j)
    return True


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
    waypoints = [start, *path]
    for p, q in zip(waypoints, waypoints[1:]):
        assert _segment_is_walkable(mesh, p, q), f"edge {p} -> {q} is not walkable throughout"


def test_string_pull_never_cuts_a_blocked_diagonal_corner():
    # Synthetic chokepoint: cells (1, 1) and (2, 2) are walkable, but the two
    # cells that flank that diagonal — (2, 1) and (1, 2) — are blocked. A
    # straight line between (1, 1) and (2, 2) only ever samples those two
    # walkable endpoints (steps == 1), so a _line_clear that checks nothing
    # but sampled cell centres would wrongly call it clear and let the
    # string-pull cut the corner. find_path's own A* neighbour guard already
    # refuses that diagonal move, so a route around exists (orthogonal-only,
    # through row 0 and column 3); the pulled path must respect the same
    # guard and keep the detour instead of collapsing back through the corner.
    walkable = np.ones((5, 5), dtype=bool)
    walkable[2, 1] = False
    walkable[1, 2] = False
    mesh = RoomMesh(x0=0, z0=0, step=100, walkable=walkable)
    start = mesh.center_of(1, 1)
    goal = mesh.center_of(2, 2)
    path = find_path(mesh, start, goal)
    assert path is not None
    assert len(path) >= 2, "string-pull collapsed straight through the blocked corner"
    waypoints = [start, *path]
    for p, q in zip(waypoints, waypoints[1:]):
        assert _segment_is_walkable(mesh, p, q), f"edge {p} -> {q} cuts the blocked corner"


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


def test_snapping_a_clicked_object_needs_more_rings_than_a_clicked_floor(data_dir):
    # Floor 0's only clickable interactable is world object 13 (actor 10). Its
    # own cell is not walkable: a type-9 hard col covers it, and the agent's
    # 266-unit inflation widens that further. nearest_walkable's default 6
    # rings (600 units) cannot reach past it, which is why target snapping has
    # its own, wider constant. Censused over all 22 interactable world objects
    # on all 8 floors, the worst needs 8 rings; this one needs 7.
    game, hero = _hero_agent(data_dir)
    mesh = build_room_mesh(Floor(data_dir, 0), 0, agent_extent(hero))
    target = game.actors[10]
    assert game.world_objects[target.index_in_world].found_life != -1, "fixture moved"
    assert not mesh.is_walkable(target.room_x, target.room_z)
    assert nearest_walkable(mesh, target.room_x, target.room_z) is None
    spot = approach_cell(mesh, target.room_x, target.room_z, hero.room_x, hero.room_z)
    assert spot == (4060, -3870)
    assert mesh.is_walkable(*spot)
    assert TARGET_SNAP_CELLS >= 8, "the census maximum, plus room to spare"


def test_approach_cell_stands_on_the_side_the_actor_comes_from():
    # a corridor of walkable cells with one blocked cell in the middle: the
    # standing spot must be the neighbour nearer whoever is approaching
    walkable = np.ones((5, 5), dtype=bool)
    walkable[2, 2] = False
    mesh = RoomMesh(0, 0, 100, walkable)
    blocked = mesh.center_of(2, 2)
    assert approach_cell(mesh, *blocked, *mesh.center_of(0, 2)) == mesh.center_of(1, 2)
    assert approach_cell(mesh, *blocked, *mesh.center_of(4, 2)) == mesh.center_of(3, 2)


def test_approach_cell_accepts_a_target_outside_the_grid():
    # objects can sit past the cover-zone bounds; the search origin clamps in
    mesh = RoomMesh(0, 0, 100, np.ones((3, 3), dtype=bool))
    assert approach_cell(mesh, -5000, -5000, 200, 200) == mesh.center_of(0, 0)


def test_approach_cell_gives_up_when_nothing_walkable_is_in_range():
    mesh = RoomMesh(0, 0, 100, np.zeros((30, 30), dtype=bool))
    assert approach_cell(mesh, 1500, 1500, 0, 0) is None
