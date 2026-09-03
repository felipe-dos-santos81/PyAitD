# SPDX-License-Identifier: GPL-2.0-only

from PyAitD.engine.data.floor import Floor
from PyAitD.engine.script.game import init_game
from PyAitD.engine.nav.navmesh import COVER_SCALE, cover_polys
from PyAitD.engine.nav.picking import pick_floor, pick_floor_any_room, pick_floor_in_room, project_floor_point
from PyAitD.engine.space.world import CameraState

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


from PyAitD.engine.nav.picking import ACTOR_PICK_PAD, actor_bbox, pick_actor


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


from types import SimpleNamespace

from PyAitD.engine.nav.picking import (
    OCCLUDE_BY_DEFAULT, floor_point_visible, ray_box_hit, room_volume,
    to_room_frame,
)


def _box(x1, x2, y1, y2, z1, z2):
    return SimpleNamespace(x1=x1, x2=x2, y1=y1, y2=y2, z1=z1, z2=z2, type=0, parameter=0)


def test_ray_box_hit_reports_the_entry_parameter():
    box = _box(400, 600, -1000, 0, -100, 100)
    t = ray_box_hit((0, -500, 0), (1000, -500, 0), box)
    assert t is not None and abs(t - 0.4) < 1e-9


def test_ray_box_hit_misses_a_box_beside_the_segment():
    box = _box(400, 600, -1000, 0, 300, 500)
    assert ray_box_hit((0, -500, 0), (1000, -500, 0), box) is None


def test_ray_box_hit_ignores_a_box_past_the_point():
    box = _box(1200, 1400, -1000, 0, -100, 100)
    assert ray_box_hit((0, -500, 0), (1000, -500, 0), box) is None


def test_ray_box_hit_ignores_a_box_the_origin_sits_in():
    box = _box(-100, 100, -1000, 0, -100, 100)
    assert ray_box_hit((0, -500, 0), (1000, -500, 0), box) is None


def test_ray_box_hit_treats_a_point_inside_the_box_as_occluded():
    box = _box(800, 1200, -1000, 0, -100, 100)
    t = ray_box_hit((0, -500, 0), (1000, -500, 0), box)
    assert t is not None and abs(t - 0.8) < 1e-9


def test_to_room_frame_uses_the_asymmetric_signs(data_dir, profile):
    # Floor 0 has a single room; floor 1 has enough rooms for a real
    # from-room/to-room pair (its rooms 0 and 1 are both used elsewhere in
    # this file, e.g. test_pick_floor_any_room_prefers_the_hero_s_own_room).
    floor = Floor(data_dir, 1, profile)
    src, dst = floor.rooms[0], floor.rooms[1]
    dx = 10 * (dst.world_x - src.world_x)
    dy = 10 * (dst.world_y - src.world_y)
    dz = 10 * (dst.world_z - src.world_z)
    assert to_room_frame(floor, 0, 1, 100, 200, 300) == (100 - dx, 200 + dy, 300 + dz)


def test_floor_point_visible_rejects_a_point_behind_a_hard_col(data_dir, profile):
    # The camera sits at (state.x, state.y, state.z) in room frame. A box
    # placed on the segment from there to a floor point must hide the point;
    # the same box moved off the segment must not.
    floor = Floor(data_dir, 0, profile)
    room = floor.rooms[0]
    cam = room.camera_indices[0]
    state = _state(floor, 0, 0)
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    point = (hero.room_x, hero.world_y, hero.room_z)
    mid = tuple((a + b) / 2 for a, b in zip((state.x, state.y, state.z), point))
    saved = list(room.hard_cols)
    try:
        room.hard_cols = saved + [_box(
            mid[0] - 50, mid[0] + 50, mid[1] - 50, mid[1] + 50, mid[2] - 50, mid[2] + 50,
        )]
        assert floor_point_visible(floor, cam, 0, *point) is False
        room.hard_cols = saved + [_box(
            mid[0] + 5000, mid[0] + 5100, mid[1] - 50, mid[1] + 50, mid[2] - 50, mid[2] + 50,
        )]
        assert floor_point_visible(floor, cam, 0, *point) is True
    finally:
        room.hard_cols = saved


def test_floor_point_visible_skips_boxes_outside_the_agent_band(data_dir, profile):
    floor = Floor(data_dir, 0, profile)
    room = floor.rooms[0]
    cam = room.camera_indices[0]
    state = _state(floor, 0, 0)
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    point = (hero.room_x, hero.world_y, hero.room_z)
    mid = tuple((a + b) / 2 for a, b in zip((state.x, state.y, state.z), point))
    saved = list(room.hard_cols)
    try:
        room.hard_cols = saved + [_box(
            mid[0] - 50, mid[0] + 50, mid[1] - 50, mid[1] + 50, mid[2] - 50, mid[2] + 50,
        )]
        # a band that cannot overlap the box: entirely above it
        band = (0, mid[1] - 10000, mid[1] - 9000)
        assert floor_point_visible(floor, cam, 0, *point, agent=band) is True
    finally:
        room.hard_cols = saved


def test_room_volume_is_the_bounding_box_of_the_rooms_hard_cols(data_dir, profile):
    floor = Floor(data_dir, 0, profile)
    boxes = floor.rooms[0].hard_cols
    assert room_volume(floor, 0) == (
        min(b.x1 for b in boxes), max(b.x2 for b in boxes),
        min(b.y1 for b in boxes), max(b.y2 for b in boxes),
        min(b.z1 for b in boxes), max(b.z2 for b in boxes),
    )
    saved = list(floor.rooms[0].hard_cols)
    try:
        floor.rooms[0].hard_cols = []
        assert room_volume(floor, 0) is None   # nothing to clip against
    finally:
        floor.rooms[0].hard_cols = saved


def test_floor_point_visible_ignores_a_box_the_camera_looks_over(data_dir, profile):
    # The camera of floor 2's room 1 sits at z ~ +10000 in room 1's frame,
    # past the room's own z extent: it films the room from OUTSIDE, over the
    # perimeter wall, like most of this game's cameras. Every segment from it
    # to a floor point therefore crosses whatever stands between it and the
    # room -- here a box of the neighbouring room 4, which the same camera
    # views. That box is not an occluder; the same box moved past the room's
    # own volume is.
    floor = Floor(data_dir, 2, profile)
    cam = floor.rooms[1].camera_indices[0]
    assert 4 in [vr.viewed_room_idx for vr in floor.cameras[cam].viewed_rooms]
    state = _state(floor, 1, 0)
    origin = (state.x, state.y, state.z)
    saved_1, saved_4 = list(floor.rooms[1].hard_cols), list(floor.rooms[4].hard_cols)
    try:
        # room 1 is one solid volume around the target; the target is its
        # centre, so the segment enters the volume well before reaching it
        volume = _box(-1500, 1500, -3000, 0, -3000, 3000)
        floor.rooms[1].hard_cols = [volume]
        point = (0, 0, 0)
        entry = ray_box_hit(origin, point, volume)
        assert entry is not None and entry > 0.2, "fixture: the camera is outside room 1"

        def at(fraction):
            # a small box centred on the segment at `fraction`, expressed in
            # room 4's frame -- the frame floor_point_visible tests it in
            spot = [o + fraction * (p - o) for o, p in zip(origin, point)]
            x, y, z = to_room_frame(floor, 1, 4, *spot)
            return _box(x - 100, x + 100, y - 100, y + 100, z - 100, z + 100)

        floor.rooms[4].hard_cols = [at(entry / 2)]
        assert floor_point_visible(floor, cam, 1, *point) is True, (
            "a box the camera looks over, before the room, hid the whole room"
        )
        floor.rooms[4].hard_cols = [at((entry + 1) / 2)]
        assert floor_point_visible(floor, cam, 1, *point) is False, (
            "a box inside the room stopped occluding"
        )
    finally:
        floor.rooms[1].hard_cols = saved_1
        floor.rooms[4].hard_cols = saved_4


from PyAitD.engine.nav.navmesh import agent_extent
from PyAitD.engine.nav.picking import viewed_floor_y


def _attic_pixels():
    return [(x, y) for y in range(199, 40, -5) for x in range(2, 320, 5)]


def test_viewed_floor_y_is_the_hero_height_in_the_hero_room(data_dir, profile):
    floor = Floor(data_dir, 0, profile)
    assert viewed_floor_y(floor, 0, 0, -1234) == -1234


def test_viewed_floor_y_follows_the_other_room_s_origin(data_dir, profile):
    # Floor 0 has a single room, so this uses floor 1 instead (rooms 0 and 1,
    # both used elsewhere in this file), following the same substitution as
    # test_to_room_frame_uses_the_asymmetric_signs above. Every room on every
    # floor of this game's real data shares world_y == 0 (checked across all
    # eight shipped floors), so rooms 0 and 1 would give dy == 0 and make the
    # assertion trivially true; room 1's world_y is temporarily patched to a
    # distinct value, mirroring this file's hard_cols save/restore idiom, so
    # the re-framing arithmetic actually has a nonzero dy to get right.
    floor = Floor(data_dir, 1, profile)
    saved = floor.rooms[1].world_y
    try:
        floor.rooms[1].world_y = saved + 7
        dy = 10 * (floor.rooms[1].world_y - floor.rooms[0].world_y)
        assert viewed_floor_y(floor, 0, 1, 500) == 500 + dy
    finally:
        floor.rooms[1].world_y = saved


def test_occlusion_only_removes_picks_and_removes_some(data_dir, profile):
    # Under every attic camera the occluded pick is a subset of the old one:
    # a pixel that still picks lands on the same point, and at least one
    # camera has a pixel that falls through a wall onto the floor behind it
    # under occlude=False and does not under occlude=True. occlude=True is
    # explicit: the filter does not ship on (OCCLUDE_BY_DEFAULT), and this is
    # the property the whole-game census gate in tests/test_prove_mouse.py
    # leans on to census one pick per pixel.
    floor = Floor(data_dir, 0, profile)
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    agent = agent_extent(hero)
    refused_anywhere = 0
    for cam_slot in range(len(floor.rooms[hero.room].camera_indices)):
        for pixel in _attic_pixels():
            old = pick_floor_any_room(
                pixel, floor, hero.room, cam_slot, hero.world_y, occlude=False,
            )
            new = pick_floor_any_room(
                pixel, floor, hero.room, cam_slot, hero.world_y,
                agent=agent, occlude=True,
            )
            if new is not None:
                assert new == old, f"camera {cam_slot} pixel {pixel} moved"
            elif old is not None:
                refused_anywhere += 1
    assert refused_anywhere > 0, "no attic pixel was ever occluded"


def test_occlude_false_is_the_pre_occlusion_baseline(data_dir, profile):
    # occlude=False must ignore hard cols entirely: adding a box in front of
    # every point changes nothing for it, while the default pick refuses.
    floor = Floor(data_dir, 0, profile)
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    slot = game.new_num_camera
    pixel = next(
        p for p in _attic_pixels()
        if (hit := pick_floor_any_room(p, floor, hero.room, slot, hero.world_y)) is not None
        and hit[2] == hero.room
    )
    baseline = pick_floor_any_room(pixel, floor, hero.room, slot, hero.world_y, occlude=False)
    assert baseline is not None
    # a box half-way along the camera ray to the picked point (the box must
    # not contain the camera: an origin inside a box is never an occlusion)
    x, z, room_idx = baseline
    state = _state(floor, room_idx, slot)
    mid = ((state.x + x) / 2, (state.y + hero.world_y) / 2, (state.z + z) / 2)
    room = floor.rooms[room_idx]
    saved = list(room.hard_cols)
    try:
        room.hard_cols = saved + [_box(
            mid[0] - 50, mid[0] + 50, mid[1] - 50, mid[1] + 50, mid[2] - 50, mid[2] + 50,
        )]
        assert pick_floor_any_room(
            pixel, floor, hero.room, slot, hero.world_y, occlude=False,
        ) == baseline
        assert pick_floor_any_room(
            pixel, floor, hero.room, slot, hero.world_y, occlude=True,
        ) is None
        # and what SHIPS is the baseline: see OCCLUDE_BY_DEFAULT
        assert pick_floor_any_room(
            pixel, floor, hero.room, slot, hero.world_y,
        ) == baseline
    finally:
        room.hard_cols = saved


from PyAitD.engine.nav.picking import (
    SNAP_BUDGET_PX, project_room_point, snap_accept, visible_accept,
)


def test_project_room_point_matches_project_floor_point_in_the_hero_room(data_dir, profile):
    floor = Floor(data_dir, 0, profile)
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    slot = game.new_num_camera
    state = _state(floor, hero.room, slot)
    expected = project_floor_point(state, hero.room_x, hero.world_y, hero.room_z)
    got = project_room_point(floor, hero.room, slot, hero.room, hero.room_x, hero.world_y, hero.room_z)
    assert got is not None and expected is not None
    assert abs(got[0] - expected[0]) < 1e-9 and abs(got[1] - expected[1]) < 1e-9


def test_project_room_point_is_none_off_the_frame(data_dir, profile):
    floor = Floor(data_dir, 0, profile)
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    slot = game.new_num_camera
    # far enough along +x that no attic camera keeps it in 320x200
    assert project_room_point(
        floor, hero.room, slot, hero.room, hero.room_x + 200000, hero.world_y, hero.room_z,
    ) is None


def test_snap_accept_bounds_candidates_in_screen_pixels(data_dir, profile):
    floor = Floor(data_dir, 0, profile)
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    slot = game.new_num_camera
    here = project_room_point(floor, hero.room, slot, hero.room, hero.room_x, hero.world_y, hero.room_z)
    pointer = (int(here[0]), int(here[1]))
    accept = snap_accept(floor, hero.room, slot, hero.room, hero.world_y, pointer)
    assert accept(hero.room_x, hero.room_z) is True
    # walk +x until the projection leaves the budget; that candidate is refused
    step = 100
    while True:
        x = hero.room_x + step
        screen = project_room_point(floor, hero.room, slot, hero.room, x, hero.world_y, hero.room_z)
        if screen is None or max(abs(screen[0] - pointer[0]), abs(screen[1] - pointer[1])) > SNAP_BUDGET_PX:
            break
        step += 100
    assert accept(x, hero.room_z) is False
    assert SNAP_BUDGET_PX == 8


def test_visible_accept_is_floor_point_visible_under_the_hero_camera(data_dir, profile):
    floor = Floor(data_dir, 0, profile)
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    slot = game.new_num_camera
    cam = floor.rooms[hero.room].camera_indices[slot]
    accept = visible_accept(
        floor, hero.room, slot, hero.room, hero.world_y, occlude=True,
    )
    assert accept(hero.room_x, hero.room_z) == floor_point_visible(
        floor, cam, hero.room, hero.room_x, hero.world_y, hero.room_z,
    )


def test_visible_accept_accepts_everything_outside_the_cameras_viewed_rooms(data_dir, profile):
    # Floor 1, room 0, camera slot 0 (global camera 0) views rooms [6, 0] --
    # room 7 is never rendered by it. A camera's ray to a point in a room it
    # never renders crosses hard cols by construction, not because anything
    # actually occludes the view, so the filter must stand down there rather
    # than refuse every candidate and turn a real interaction into blocked.
    floor = Floor(data_dir, 1, profile)
    cam = floor.rooms[0].camera_indices[0]
    assert [vr.viewed_room_idx for vr in floor.cameras[cam].viewed_rooms] == [6, 0]

    # a room the camera does view still filters, same as floor_point_visible
    viewed = visible_accept(floor, 0, 0, 0, 0, occlude=True)
    assert viewed(400, -200) == floor_point_visible(floor, cam, 0, 400, 0, -200)

    # a room the camera never views accepts unconditionally
    unviewed = visible_accept(floor, 0, 0, 7, 0, occlude=True)
    assert unviewed(300, 500) is True
    assert unviewed(-999999, 999999) is True, "unconditional, not merely unoccluded here"


def test_the_shipped_pick_and_its_cell_filter_agree_about_occlusion(data_dir, profile):
    """The two must move together. A floor pick that ignores occlusion beside
    an approach-cell filter that does not would make objects unreachable in
    exactly the rooms whose floor is freely clickable -- which is what
    `blocked` looked like when the filter was refusing every cell of 87 camera
    slots. Both read OCCLUDE_BY_DEFAULT, so this pins the pair, not the value.
    """
    floor = Floor(data_dir, 0, profile)
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    slot = game.new_num_camera
    cam = floor.rooms[hero.room].camera_indices[slot]
    point = (hero.room_x, hero.world_y, hero.room_z)
    state = _state(floor, hero.room, slot)
    mid = tuple((a + b) / 2 for a, b in zip((state.x, state.y, state.z), point))
    room = floor.rooms[hero.room]
    saved = list(room.hard_cols)
    try:
        room.hard_cols = saved + [_box(
            mid[0] - 50, mid[0] + 50, mid[1] - 50, mid[1] + 50, mid[2] - 50, mid[2] + 50,
        )]
        assert floor_point_visible(floor, cam, hero.room, *point) is False, (
            "fixture: the box must hide the hero's own cell"
        )
        # the hidden cell is refused exactly when the pick occludes too
        accept = visible_accept(floor, hero.room, slot, hero.room, hero.world_y)
        assert accept(hero.room_x, hero.room_z) is not OCCLUDE_BY_DEFAULT
    finally:
        room.hard_cols = saved


def test_the_shipped_floor_pick_is_the_unoccluded_one(data_dir, profile):
    # The fallback the whole-game census forced: OCCLUDE_BY_DEFAULT off, so
    # calling pick_floor_any_room the way the shell does IS occlude=False.
    # tests/test_prove_mouse.py's gate is what says this may not change until
    # no camera slot goes dark.
    assert OCCLUDE_BY_DEFAULT is False
    floor = Floor(data_dir, 0, profile)
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    slot = game.new_num_camera
    agent = agent_extent(hero)
    for pixel in _attic_pixels()[::7]:
        assert (
            pick_floor_any_room(pixel, floor, hero.room, slot, hero.world_y, agent=agent)
            == pick_floor_any_room(
                pixel, floor, hero.room, slot, hero.world_y, occlude=False)
        )
