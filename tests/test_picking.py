# SPDX-License-Identifier: GPL-2.0-only

from PyAitD.engine.data.floor import Floor
from PyAitD.engine.game import init_game
from PyAitD.engine.navmesh import COVER_SCALE, cover_polys
from PyAitD.engine.picking import pick_floor, pick_floor_any_room, pick_floor_in_room, project_floor_point
from PyAitD.engine.world import CameraState

import pytest

pytestmark = pytest.mark.engine


def _state(floor, room_idx, cam_idx):
    room = floor.rooms[room_idx]
    camera = floor.cameras[room.camera_indices[cam_idx]]
    return CameraState.from_camera(
        camera, room.world_x, room.world_y, room.world_z,
    ).angles()


def test_pick_floor_round_trips_projected_points(data_dir, profile):
    # For every camera of the opening room, projecting a floor point and
    # picking it back must land within a cell of where it started. The floor
    # is per-camera, not just aggregate: a camera that puts any point on
    # screen must round-trip at least one of them, so a regression narrowed
    # to one camera angle (e.g. a _quad_of corner-selection bug) cannot hide
    # behind other cameras' successes.
    floor = Floor(data_dir, 0, profile)
    game = init_game(data_dir, profile)
    floor_y = game.actors[game.current_camera_target_actor].world_y
    checked = 0
    for cam_slot in range(len(floor.rooms[0].camera_indices)):
        state = _state(floor, 0, cam_slot)
        candidates = 0
        camera_checked = 0
        for poly in cover_polys(floor, 0):
            xs = [p[0] * COVER_SCALE for p in poly]
            zs = [p[1] * COVER_SCALE for p in poly]
            cx, cz = sum(xs) // len(xs), sum(zs) // len(zs)
            screen = project_floor_point(state, cx, floor_y, cz)
            if screen is None:
                continue
            candidates += 1
            picked = pick_floor(screen, floor, 0, cam_slot, floor_y)
            if picked is None:
                continue
            assert abs(picked[0] - cx) <= 100 and abs(picked[1] - cz) <= 100, (
                f"camera {cam_slot}: {picked} should round-trip to {(cx, cz)}"
            )
            camera_checked += 1
        # A camera that never projects a point onto screen has nothing to
        # prove here (that's project_floor_point's culling, not a picking
        # failure). But a camera that *did* put points on screen must
        # round-trip at least one of them, or the fit is broken for it.
        assert candidates == 0 or camera_checked > 0, (
            f"camera {cam_slot}: {candidates} point(s) projected onto screen "
            f"but none round-tripped — the fit is broken for this camera"
        )
        checked += camera_checked
    assert checked > 0, "no floor point round-tripped — the fit never ran"


def test_pick_floor_outside_every_cover_polygon_is_none(data_dir, profile):
    floor = Floor(data_dir, 0, profile)
    # top-left corner of the 320x200 logical surface is ceiling, never floor
    assert pick_floor((2, 2), floor, 0, 0, 0) is None


from PyAitD.engine.picking import ACTOR_PICK_PAD, actor_bbox, pick_actor


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


def test_expanded_actor_target_reaches_a_tiny_actor_s_minimum_size():
    from PyAitD.app.shell import expand_actor_targets

    # A four-pixel square must become a 12x12 logical target. The expectation
    # is hand-derived: two pixels of padding make it 8x8, then the minimum
    # grows it symmetrically by another two pixels on each side.
    original = [(7, (100, 50, 103, 53))]
    actor_idx, target = expand_actor_targets(original)[0]

    assert actor_idx == 7
    assert (target.left, target.top, target.width, target.height) == (96, 46, 12, 12)
    assert pick_actor((96, 50), original) is None
    assert pick_actor((96, 50), [(actor_idx, target)]) == 7


def test_actor_bbox_padding_enlarges_the_target():
    result = _FakeResult([(100.0, 50.0, 900.0), (120.0, 80.0, 900.0)])
    x0, y0, x1, y1 = actor_bbox(result)
    assert (x0, y0, x1, y1) == (100 - ACTOR_PICK_PAD, 50 - ACTOR_PICK_PAD,
                                120 + ACTOR_PICK_PAD, 80 + ACTOR_PICK_PAD)


def test_actor_bbox_excludes_non_sentinel_negative_extremes():
    # near-clip projection (depth just above 50) can divide out to a huge
    # negative value that is not the exact (-10000,...) sentinel; it must
    # still be treated as unusable, or the box balloons toward -infinity
    result = _FakeResult([(100.0, 60.0, 900.0), (-9500.0, 40.0, 3000.0)])
    assert actor_bbox(result, pad=0) == (100, 60, 100, 60)


def test_actor_bbox_excludes_positive_extremes_and_stays_on_surface():
    # the same near-clip division can overflow positive, with no sentinel at
    # all to filter on; previously this ballooned the box past the screen
    result = _FakeResult([(100.0, 60.0, 900.0), (50000.0, 70.0, 3000.0)])
    box = actor_bbox(result, pad=0)
    assert box == (100, 60, 100, 60)
    x0, y0, x1, y1 = box
    assert 0 <= x0 <= 320 and 0 <= x1 <= 320
    assert 0 <= y0 <= 200 and 0 <= y1 <= 200


def test_actor_bbox_clamps_rather_than_drops_a_straddling_actor():
    # a legitimately off-screen vertex (an actor straddling the edge of the
    # 320x200 logical surface) is not a near-clip artifact and must not be
    # filtered out -- the box is clamped to the surface, not dropped
    result = _FakeResult([(-100.0, 90.0, 900.0), (350.0, 110.0, 900.0)])
    assert actor_bbox(result, pad=0) == (0, 90, 320, 110)


def test_pick_floor_in_room_uses_that_room_s_own_origin(data_dir, profile):
    # room 0 of floor 0 is the only room, so the global-camera form must agree
    # exactly with the slot form it generalises
    floor = Floor(data_dir, 0, profile)
    game = init_game(data_dir, profile)
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


def test_pick_floor_any_room_reports_which_room_it_hit(data_dir, profile):
    floor = Floor(data_dir, 0, profile)
    game = init_game(data_dir, profile)
    floor_y = game.actors[game.current_camera_target_actor].world_y
    state = _state(floor, 0, 0)
    poly = cover_polys(floor, 0)[0]
    xs = [p[0] * COVER_SCALE for p in poly]
    zs = [p[1] * COVER_SCALE for p in poly]
    screen = project_floor_point(state, sum(xs) // len(xs), floor_y, sum(zs) // len(zs))
    hit = pick_floor_any_room(screen, floor, 0, 0, floor_y)
    assert hit is not None and hit[2] == 0


def test_pick_floor_any_room_prefers_the_hero_s_own_room(data_dir, profile):
    # A real preference: one screen point that resolves to a valid floor point
    # in BOTH rooms camera 0 views, so the hero's room is what breaks the tie
    # rather than the only candidate. Camera 0 lists its viewed rooms as
    # [6, 0], so without the preference room 6 would win in both directions.
    floor = Floor(data_dir, 1, profile)
    screen = (178, 181)
    floor_y = 0
    for room_idx in (0, 6):
        assert pick_floor_in_room(screen, floor, room_idx, 0, floor_y) is not None, (
            f"fixture: room {room_idx} must claim this pixel for the tie to exist"
        )
    hero_in_0 = pick_floor_any_room(
        screen, floor, 0, floor.rooms[0].camera_indices.index(0), floor_y,
    )
    hero_in_6 = pick_floor_any_room(
        screen, floor, 6, floor.rooms[6].camera_indices.index(0), floor_y,
    )
    assert hero_in_0[2] == 0, "the hero's own room must win the overlap"
    assert hero_in_6[2] == 6, "the same pixel resolves to room 6 for a hero there"
    assert hero_in_0[:2] != hero_in_6[:2], (
        "each room recovers the point in its own coordinate space"
    )
