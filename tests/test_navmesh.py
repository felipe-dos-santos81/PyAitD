# SPDX-License-Identifier: GPL-2.0-only
import subprocess
import sys

from PyAitD.actors import cube_intersect
from PyAitD.floor import Floor
from PyAitD.game import init_game
from PyAitD.navmesh import COVER_SCALE, GRID_STEP, agent_extent, build_cover_grid, build_room_mesh, cover_polys
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
