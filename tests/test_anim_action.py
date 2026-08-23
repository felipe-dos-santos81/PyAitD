# SPDX-License-Identifier: GPL-2.0-only
"""Melee hot-point timing and hit publication (FITD animAction.cpp GereFrappe)."""
import pytest

from PyAitD.actors import anim_player_for
from PyAitD.anim_action import (
    DO_TIR, FRAPPE_OK, HIT_OBJECT, THROW_OBJECT, WAIT_ANIM_THROW, WAIT_FRAME_THROW,
    WAIT_FRAPPE_ANIM, WAIT_FRAPPE_FRAME, WAIT_TIR_ANIM, check_line_projection_with_actors,
    gere_frappe, refresh_hot_point,
)
from PyAitD.game import AF_ANIMATED, AF_BOXIFY, AF_MOVABLE, AF_SPECIAL, init_game, spawn_stage_actors
from PyAitD.skel import hot_point as skel_hot_point


def _live_actors(data_dir, count):
    game = init_game(data_dir)
    live = [i for i, actor in enumerate(game.actors) if actor.index_in_world >= 0]
    assert len(live) >= count
    selected = live[:count]
    room = game.actors[selected[0]].room
    for index in selected:
        game.actors[index].room = room
    return (game, *selected)


def test_melee_waits_for_animation_then_frame(data_dir):
    game, attacker_idx, _victim_idx = _live_actors(data_dir, 2)
    actor = game.actors[attacker_idx]
    actor.anim_action_type = WAIT_FRAPPE_ANIM
    actor.anim_action_anim = actor.anim
    actor.anim_action_frame = actor.frame + 1
    gere_frappe(game, attacker_idx)
    assert actor.anim_action_type == WAIT_FRAPPE_FRAME
    actor.frame += 1
    gere_frappe(game, attacker_idx)
    assert actor.anim_action_type == FRAPPE_OK


def test_frappe_ok_mismatch_still_hit_tests(monkeypatch, data_dir):
    game, attacker_idx, victim_idx = _live_actors(data_dir, 2)
    attacker = game.actors[attacker_idx]
    attacker.anim_action_type = FRAPPE_OK
    attacker.anim_action_anim = attacker.anim + 1
    attacker.anim_action_param = 50
    attacker.hit_force = 10
    monkeypatch.setattr("PyAitD.anim_action.check_object_col", lambda *args: (victim_idx,))
    gere_frappe(game, attacker_idx)
    assert attacker.anim_action_type == 0
    assert attacker.hit == victim_idx
    assert game.actors[victim_idx].hit_by == attacker_idx
    assert game.actors[victim_idx].hit_force == 10


def test_melee_stops_at_first_animated_victim(monkeypatch, data_dir):
    game, attacker_idx, first_idx, second_idx = _live_actors(data_dir, 3)
    game.actors[first_idx].object_type |= AF_ANIMATED
    monkeypatch.setattr(
        "PyAitD.anim_action.check_object_col", lambda *args: (first_idx, second_idx)
    )
    game.actors[attacker_idx].anim_action_type = FRAPPE_OK
    game.actors[attacker_idx].anim_action_param = 100
    gere_frappe(game, attacker_idx)
    assert game.actors[attacker_idx].hit == first_idx
    assert game.actors[second_idx].hit_by == -1


def test_gere_frappe_rejects_declared_but_unhandled_action(data_dir):
    # FITD declares action value 3 but animAction.cpp never handles it —
    # HANDLED_ACTIONS deliberately excludes it.
    game, actor_idx = _live_actors(data_dir, 1)
    game.actors[actor_idx].anim_action_type = 3
    with pytest.raises(ValueError, match=rf"actor {actor_idx}\D+3\b"):
        gere_frappe(game, actor_idx)


def test_gere_frappe_rejects_out_of_range_action(data_dir):
    game, actor_idx = _live_actors(data_dir, 1)
    game.actors[actor_idx].anim_action_type = 11
    with pytest.raises(ValueError, match=rf"actor {actor_idx}\D+11\b"):
        gere_frappe(game, actor_idx)


def test_hit_object_state_is_an_explicit_no_op(data_dir):
    game, actor_idx = _live_actors(data_dir, 1)
    actor = game.actors[actor_idx]
    actor.anim_action_type = HIT_OBJECT
    actor.hit = -1
    actor.hit_by = -1
    actor.hit_force = 7
    gere_frappe(game, actor_idx)
    assert actor.anim_action_type == HIT_OBJECT
    assert actor.hit == -1
    assert actor.hit_by == -1
    assert actor.hit_force == 7


def test_frappe_ok_builds_the_expected_strike_cube(monkeypatch, data_dir):
    # Distinct, non-zero values on every axis so a dropped term, a swapped
    # axis, or a flipped sign in room_*/hot_point/step_* would move the
    # captured cube away from the hand-computed expectation below.
    game, attacker_idx, victim_idx = _live_actors(data_dir, 2)
    attacker = game.actors[attacker_idx]
    attacker.anim_action_type = FRAPPE_OK
    attacker.anim_action_anim = attacker.anim  # no mismatch: keep the fall-through out of this test
    attacker.room_x, attacker.room_y, attacker.room_z = 1000, 2000, 3000
    attacker.hot_point[:] = [10, 20, 30]
    attacker.step_x, attacker.step_y, attacker.step_z = 1, 2, 3
    attacker.anim_action_param = 50

    captured = {}

    def capturing_check_object_col(game_arg, actor_idx_arg, zv):
        captured["zv"] = zv
        return (victim_idx,)

    monkeypatch.setattr("PyAitD.anim_action.check_object_col", capturing_check_object_col)
    gere_frappe(game, attacker_idx)

    # x = 1000 + 10 + 1 = 1011, y = 2000 + 20 + 2 = 2022, z = 3000 + 30 + 3 = 3033,
    # cube = [x-50, x+50, y-50, y+50, z-50, z+50] — computed by hand, not by
    # re-reading the same attacker.room_*/hot_point/step_* expression under test.
    assert list(captured["zv"]) == [961, 1061, 1972, 2072, 2983, 3083]
    assert attacker.hit == victim_idx


def test_refresh_hot_point_uses_the_live_anim_pose(data_dir):
    game, idx = _live_actors(data_dir, 1)
    actor = game.actors[idx]
    actor.anim = 4  # a real body-12 walk anim with non-zero keyframe deltas
    actor.body_num = 12
    body = game.assets.body(actor.body_num)
    assert body.flags & 2, "fixture body must carry INFO_ANIM for hot_point() to do real posing"
    actor.alpha, actor.beta, actor.gamma = 0x40, 0x120, 0x2C0
    actor.hot_point_id = 5  # group 5, not the group-0 slot pose_vertices overrides with actor_angles

    player = anim_player_for(game, idx)
    player.advance(game.timer)  # populate real per-group keyframe deltas, mirroring gere_anim's usage
    live_states = list(player.group_states())
    assert any(delta != (0, 0, 0) for _gtype, delta in live_states), (
        "fixture animation must carry a non-zero delta or this test cannot "
        "distinguish the live pose from the zero-state fallback"
    )

    refresh_hot_point(game, idx)

    expected = skel_hot_point(
        body, live_states, (actor.alpha, actor.beta, actor.gamma), actor.hot_point_id,
    )
    assert tuple(actor.hot_point) == expected

    zero_states = [(0, (0, 0, 0))] * len(body.groups)
    zero_expected = skel_hot_point(
        body, zero_states, (actor.alpha, actor.beta, actor.gamma), actor.hot_point_id,
    )
    assert expected != zero_expected, (
        "the live and zero-state poses coincide here, so this fixture choice "
        "would not catch refresh_hot_point picking the wrong states branch"
    )


def test_refresh_hot_point_uses_zero_states_when_actor_has_no_anim(monkeypatch, data_dir):
    game, idx = _live_actors(data_dir, 1)
    actor = game.actors[idx]
    actor.anim = -1
    actor.body_num = 12  # confirmed INFO_ANIM (flags & 2) so hot_point() does real posing
    actor.alpha, actor.beta, actor.gamma = 0x40, 0x120, 0x2C0
    actor.hot_point_id = 5

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("refresh_hot_point must not touch game.assets.anim when actor.anim == -1")

    monkeypatch.setattr(game.assets, "anim", _must_not_be_called)

    refresh_hot_point(game, idx)

    body = game.assets.body(actor.body_num)
    zero_states = [(0, (0, 0, 0))] * len(body.groups)
    expected = skel_hot_point(
        body, zero_states, (actor.alpha, actor.beta, actor.gamma), actor.hot_point_id,
    )
    assert tuple(actor.hot_point) == expected


def test_throw_setup_requests_normal_spawn_then_launches(data_dir, monkeypatch):
    game = init_game(data_dir)
    thrower_idx = game.current_camera_target_actor
    thrower = game.actors[thrower_idx]
    object_idx = 13
    world = game.world_objects[object_idx]
    world.body = 1
    thrower.anim_action_type = WAIT_ANIM_THROW
    thrower.anim_action_anim = thrower.anim
    thrower.anim_action_frame = thrower.frame
    thrower.anim_action_param = object_idx
    thrower.hot_point[:] = [0, 0, 0]

    monkeypatch.setattr("PyAitD.anim_action.check_hard_col", lambda *args: [])
    # init_game's own spawn pass already leaves flag_genere_aff_list == 1
    # (it just spawned the whole stage), so reset it here — otherwise the
    # assertion below would pass even if state 6 never touched the flag.
    game.flag_genere_aff_list = 0
    gere_frappe(game, thrower_idx)
    assert thrower.anim_action_type == WAIT_FRAME_THROW
    assert game.flag_genere_aff_list == 1
    assert (world.stage, world.room) == (thrower.stage, thrower.room)

    spawn_stage_actors(game)
    game.flag_genere_aff_list = 0
    gere_frappe(game, thrower_idx)
    thrown = game.actors[world.obj_index]
    assert thrower.anim_action_type == 0
    assert thrown.anim_action_type == THROW_OBJECT
    assert (thrown.speed, thrown.hit_force, thrown.hot_point_id) == (3000, thrower.hit_force, -1)
    assert thrown.speed_change.num_steps == 60
    assert world.alpha == thrower.index_in_world


def test_wait_anim_throw_stays_put_until_animation_matches(monkeypatch, data_dir):
    # FITD animAction.cpp:161: case 6 only builds the obstruction cube (and
    # therefore only calls check_hard_col) once ANIM == animActionANIM.
    game, thrower_idx = _live_actors(data_dir, 1)
    thrower = game.actors[thrower_idx]
    thrower.anim_action_type = WAIT_ANIM_THROW
    thrower.anim_action_anim = thrower.anim + 1  # deliberate mismatch

    calls = []
    monkeypatch.setattr("PyAitD.anim_action.check_hard_col", lambda *a: calls.append(a) or [])

    gere_frappe(game, thrower_idx)

    assert thrower.anim_action_type == WAIT_ANIM_THROW
    assert calls == []


def test_prepare_throw_builds_the_expected_obstruction_cube(monkeypatch, data_dir):
    # Distinct, non-zero values on every axis so a dropped term, a swapped
    # axis, or a flipped sign in room_*/hot_point/step_* would move the
    # captured cube away from the hand-computed expectation below.
    game, thrower_idx = _live_actors(data_dir, 1)
    thrower = game.actors[thrower_idx]
    object_idx = 13
    world = game.world_objects[object_idx]
    world.body = 1  # LISTBODY[1].zv == (-630, 630, -1441, 0, -360, 540), pinned game data
    thrower.anim_action_type = WAIT_ANIM_THROW
    thrower.anim_action_anim = thrower.anim
    thrower.anim_action_frame = thrower.frame + 1  # mismatch: return right after the cube check
    thrower.anim_action_param = object_idx
    thrower.room_x, thrower.room_y, thrower.room_z = 1000, 2000, 3000
    thrower.hot_point[:] = [10, 20, 30]
    thrower.step_x, thrower.step_y, thrower.step_z = 1, 2, 3

    room = game.rooms_of_floor(game.current_floor)[thrower.room]
    captured = {}

    def capturing_check_hard_col(zv, hard_cols):
        captured["zv"] = list(zv)
        captured["hard_cols"] = hard_cols
        return []

    monkeypatch.setattr("PyAitD.anim_action.check_hard_col", capturing_check_hard_col)

    gere_frappe(game, thrower_idx)

    # x = 1000 + 10 + 1 = 1011, y = 2000 + 20 + 2 = 2022, z = 3000 + 30 + 3 = 3033,
    # cube = raw body zv shifted by (x, y, y, z, z) — computed by hand, not by
    # re-reading the same room_*/hot_point/step_* expression under test.
    assert captured["zv"] == [381, 1641, 581, 2022, 2673, 3573]
    assert captured["hard_cols"] is room.hard_cols
    assert thrower.anim_action_type == WAIT_ANIM_THROW  # frame mismatch: stayed put


def test_prepare_throw_waits_for_frame_before_arming(monkeypatch, data_dir):
    game, thrower_idx = _live_actors(data_dir, 1)
    thrower = game.actors[thrower_idx]
    object_idx = 13
    world = game.world_objects[object_idx]
    original_room, original_stage = world.room, world.stage
    original_x, original_y, original_z = world.x, world.y, world.z
    thrower.anim_action_type = WAIT_ANIM_THROW
    thrower.anim_action_anim = thrower.anim
    thrower.anim_action_frame = thrower.frame + 1  # not yet reached
    thrower.anim_action_param = object_idx
    game.flag_genere_aff_list = 0

    monkeypatch.setattr("PyAitD.anim_action.check_hard_col", lambda *a: [])

    gere_frappe(game, thrower_idx)

    assert thrower.anim_action_type == WAIT_ANIM_THROW
    assert game.flag_genere_aff_list == 0
    assert (world.room, world.stage) == (original_room, original_stage)
    assert (world.x, world.y, world.z) == (original_x, original_y, original_z)


def test_prepare_throw_obstructed_reverts_placement(monkeypatch, data_dir):
    game, thrower_idx = _live_actors(data_dir, 1)
    thrower = game.actors[thrower_idx]
    object_idx = 13
    world = game.world_objects[object_idx]
    thrower.anim_action_type = WAIT_ANIM_THROW
    thrower.anim_action_anim = thrower.anim
    thrower.anim_action_frame = thrower.frame  # frame already matches
    thrower.anim_action_param = object_idx
    thrower.index_in_world = 4  # distinct from thrower_idx and from object_idx
    original_room, original_stage = world.room, world.stage
    original_x, original_y, original_z = world.x, world.y, world.z
    game.flag_genere_aff_list = 0

    monkeypatch.setattr("PyAitD.anim_action.check_hard_col", lambda *a: ["blocked"])

    calls = []
    monkeypatch.setattr(
        "PyAitD.anim_action.put_at_objet",
        lambda game_arg, obj_idx, put_at_idx: calls.append((game_arg, obj_idx, put_at_idx)),
    )

    gere_frappe(game, thrower_idx)

    assert thrower.anim_action_type == 0
    assert calls == [(game, object_idx, 4)]
    assert (world.room, world.stage) == (original_room, original_stage)
    assert (world.x, world.y, world.z) == (original_x, original_y, original_z)
    assert game.flag_genere_aff_list == 0


def test_launch_throw_places_actor_with_expected_zv_and_flight_state(data_dir):
    # Distinct, non-zero values on every axis so a dropped term, a swapped
    # axis, or a wrong source object (e.g. the thrower's own body instead of
    # the thrown object's) would move the result away from the hand-computed
    # expectation below.
    game, thrower_idx = _live_actors(data_dir, 1)
    thrower = game.actors[thrower_idx]
    object_idx = 13
    world = game.world_objects[object_idx]
    world.body = 1  # LISTBODY[1].zv == (-630, 630, -1441, 0, -360, 540), pinned game data
    assert world.obj_index != -1, "fixture must already carry a live actor for object 13"
    thrown = game.actors[world.obj_index]

    thrower.anim_action_type = WAIT_FRAME_THROW
    thrower.anim_action_param = object_idx
    thrower.room_x, thrower.room_y, thrower.room_z = 1000, 2000, 3000
    thrower.hot_point[:] = [10, 20, 30]
    thrower.step_x, thrower.step_y, thrower.step_z = 1, 2, 3
    thrower.index_in_world = 4  # distinct from thrower_idx: proves world.alpha takes this field
    thrower.hit_force = 77
    game.timer = 123

    thrown.object_type = AF_BOXIFY | AF_MOVABLE
    thrown.dyn_flags = 5
    thrown.hot_point_id = 9
    thrown.speed_change.num_steps = 42

    gere_frappe(game, thrower_idx)

    # x = 1000 + 10 + 1 = 1011, y = 2000 + 20 + 2 = 2022, z = 3000 + 30 + 3 = 3033 —
    # computed by hand, not re-derived from the same expression under test.
    assert (thrown.room_x, thrown.room_y, thrown.room_z) == (1011, 2022, 3033)
    assert (thrown.world_x, thrown.world_y, thrown.world_z) == (1011, 2022, 3033)
    assert list(thrown.zv) == [381, 1641, 581, 2022, 2673, 3573]
    assert (world.x, world.y, world.z) == (1011, 2022, 3033)
    assert world.alpha == 4
    assert thrown.object_type & AF_ANIMATED
    assert not (thrown.object_type & AF_BOXIFY)
    assert thrown.object_type & AF_MOVABLE  # untouched bit survives the |=/&= pair
    assert thrown.dyn_flags == 0
    assert thrower.anim_action_type == 0
    assert thrown.anim_action_type == THROW_OBJECT
    assert thrown.anim_action_param == 100
    assert thrown.hit_force == 77
    assert thrown.hot_point_id == -1
    assert thrown.speed == 3000
    assert (thrown.speed_change.start_value, thrown.speed_change.end_value) == (0, 3000)
    assert thrown.speed_change.num_steps == 60
    assert thrown.speed_change.memo_ticks == 123


def test_launch_throw_missing_actor_resets_thrower_only(data_dir):
    game, thrower_idx = _live_actors(data_dir, 1)
    thrower = game.actors[thrower_idx]
    object_idx = 13
    world = game.world_objects[object_idx]
    world.obj_index = -1  # not spawned yet
    world.body = 1
    original_x, original_y, original_z = world.x, world.y, world.z
    thrower.anim_action_type = WAIT_FRAME_THROW
    thrower.anim_action_param = object_idx

    gere_frappe(game, thrower_idx)

    assert thrower.anim_action_type == 0
    assert (world.x, world.y, world.z) == (original_x, original_y, original_z)


def test_prepare_throw_raises_when_thrown_object_has_no_body(data_dir):
    # Spec: "A thrown object whose world record has no body raises with the
    # object index; silently using the thrower's body is forbidden." Reached
    # through gere_frappe (the real dispatch path), not by calling the
    # private _raw_body_zv/_prepare_throw helpers directly.
    game, thrower_idx = _live_actors(data_dir, 1)
    thrower = game.actors[thrower_idx]
    object_idx = 13
    world = game.world_objects[object_idx]
    world.body = -1  # no body: _raw_body_zv must refuse to guess one
    thrower.anim_action_type = WAIT_ANIM_THROW
    thrower.anim_action_anim = thrower.anim  # animation already matches
    thrower.anim_action_param = object_idx

    with pytest.raises(ValueError, match=rf"\b{object_idx}\b"):
        gere_frappe(game, thrower_idx)


def test_launch_throw_raises_when_thrown_object_has_no_body(data_dir):
    game, thrower_idx = _live_actors(data_dir, 1)
    thrower = game.actors[thrower_idx]
    object_idx = 13
    world = game.world_objects[object_idx]
    assert world.obj_index != -1, "fixture must already carry a live actor for object 13"
    world.body = -1  # no body: _raw_body_zv must refuse to guess one
    thrower.anim_action_type = WAIT_FRAME_THROW
    thrower.anim_action_param = object_idx

    with pytest.raises(ValueError, match=rf"\b{object_idx}\b"):
        gere_frappe(game, thrower_idx)


# --- Task 7: firearm volume sweep (checkLineProjectionWithActors) ---


def test_fire_sweep_preserves_no_hard_collision_termination(monkeypatch, data_dir):
    # animAction.cpp:3900-3904 AsmCheckListCol branch: the sweep stops with
    # NO hit the instant the swept cube overlaps zero hard-collision
    # entries. This is FITD's verified (if counterintuitive) behaviour, not
    # a raycast-until-blocked convention to "correct".
    game, shooter_idx, victim_idx = _live_actors(data_dir, 2)
    monkeypatch.setattr("PyAitD.anim_action.check_hard_col", lambda *args: [])
    result = check_line_projection_with_actors(game, shooter_idx, 0, 0, 0, 0, 0, 50)
    assert result[0] == -1
    assert result[1:] == (0, 0, 0)
    assert game.actors[victim_idx].hit_by == -1


def test_fire_sweep_returns_first_live_non_special_slot(monkeypatch, data_dir):
    # Controller ruling: the brief co-locates only three actors, but the
    # sweep iterates every live actor in slot order, so on real floor-0
    # data an unrelated live actor at a lower slot (possibly in another
    # room, reachable via adjust_zv_between_rooms) could intersect the
    # swept cube first and make the assertion below flaky. Deactivate every
    # other live actor rather than weaken the asserted contract, which
    # stays: first live, non-AF_SPECIAL, non-shooter actor in slot order.
    game, shooter_idx, first_idx, second_idx = _live_actors(data_dir, 3)
    for idx, other in enumerate(game.actors):
        if idx not in (shooter_idx, first_idx, second_idx):
            other.index_in_world = -1
    monkeypatch.setattr("PyAitD.anim_action.check_hard_col", lambda *args: [object()])
    game.actors[first_idx].object_type |= AF_SPECIAL
    game.actors[second_idx].zv = [-100, 100, -100, 100, -100, 100]
    hit, x, y, z = check_line_projection_with_actors(
        game, shooter_idx, 0, 0, -100, 0, game.actors[shooter_idx].room, 50,
    )
    assert hit == second_idx
    assert (x, y, z) == (0, 0, -100)


@pytest.mark.parametrize(
    "beta, start_x, expected_impact_x",
    [
        # beta == 0: walkStep gives move_x == +param*2 (rotate_step's
        # crossed no-rotation identity). param == 1 carries X from 19999 to
        # exactly 20001 in a single step, past the 20000 upper bound.
        (0, 19999, 19999),
        # beta == 0x200 (half turn): move_x == -param*2, so param == 1
        # carries X from -19999 to exactly -20001, past the lower bound —
        # exercising both signs of the strict '>'/'<' comparison.
        (0x200, -19999, -19999),
    ],
)
def test_fire_sweep_terminates_outside_xz_bounds(beta, start_x, expected_impact_x, data_dir):
    # animAction.cpp:3892-3897: X/Z leaving [-20000, 20000] ends the sweep
    # with no hit. The returned impact position is the *pre-step* tempX
    # (animMoveX at loop exit), one step short of the out-of-bounds value
    # that triggered termination — pinned by hand below so an off-by-one
    # iteration bug is not invisible to the assertion.
    game, shooter_idx = _live_actors(data_dir, 1)
    room = game.actors[shooter_idx].room
    result = check_line_projection_with_actors(game, shooter_idx, start_x, 0, 0, beta, room, 1)
    assert result == (-1, expected_impact_x, 0, 0)


def test_fire_sweep_adjusts_zv_across_rooms_before_intersecting(monkeypatch, data_dir):
    # animAction.cpp:3910-3922: when the candidate actor is in a different
    # room, the swept cube is copied and AdjustZV'd into that actor's room
    # *before* CubeIntersect runs — the raw same-room cube is never
    # compared directly for a cross-room actor. Forcing
    # adjust_zv_between_rooms to return a cube that only overlaps the
    # victim (the untouched local cube, still near x=0, does not) proves
    # its return value is what gets tested, not silently discarded.
    game, shooter_idx, victim_idx = _live_actors(data_dir, 2)
    for idx, other in enumerate(game.actors):
        if idx not in (shooter_idx, victim_idx):
            other.index_in_world = -1
    shooter = game.actors[shooter_idx]
    victim = game.actors[victim_idx]
    # Floor 0 (the fixture default) carries only one room, so force a floor
    # with >= 2 rooms to exercise the cross-room branch at all.
    multi_room_floor = next(
        f for f in range(8) if len(game.rooms_of_floor(f)) >= 2
    )
    game.current_floor = multi_room_floor
    shooter.room = 0
    victim.room = 1
    victim.zv = [900, 1100, -100, 100, -100, 100]

    monkeypatch.setattr("PyAitD.anim_action.check_hard_col", lambda *args: [object()])

    captured = {}

    def fake_adjust(game_arg, zv, from_room, to_room):
        captured["game"] = game_arg
        captured["from_room"] = from_room
        captured["to_room"] = to_room
        captured["zv"] = list(zv)
        return [900, 1100, -100, 100, -100, 100]

    monkeypatch.setattr("PyAitD.anim_action.adjust_zv_between_rooms", fake_adjust)

    hit, x, y, z = check_line_projection_with_actors(
        game, shooter_idx, 0, 0, -100, 0, shooter.room, 50,
    )

    assert hit == victim_idx
    assert captured["game"] is game
    assert captured["from_room"] == shooter.room
    assert captured["to_room"] == victim.room
    assert len(captured["zv"]) == 6


def test_wait_tir_anim_arms_do_tir_only_when_anim_and_frame_match(data_dir):
    # animAction.cpp:92-100 case WAIT_TIR_ANIM: two separate early returns
    # in C++ (ANIM mismatch, then frame mismatch) collapse into a single
    # AND-guarded transition in the port; exercise both mismatches.
    game, actor_idx = _live_actors(data_dir, 1)
    actor = game.actors[actor_idx]
    actor.anim_action_type = WAIT_TIR_ANIM
    actor.anim_action_anim = actor.anim + 1  # anim mismatch
    actor.anim_action_frame = actor.frame
    gere_frappe(game, actor_idx)
    assert actor.anim_action_type == WAIT_TIR_ANIM

    actor.anim_action_anim = actor.anim  # anim matches now, frame doesn't
    actor.anim_action_frame = actor.frame + 1
    gere_frappe(game, actor_idx)
    assert actor.anim_action_type == WAIT_TIR_ANIM

    actor.anim_action_frame = actor.frame  # both match
    gere_frappe(game, actor_idx)
    assert actor.anim_action_type == DO_TIR


def test_do_tir_hit_updates_hotpoint_and_publishes_hit(monkeypatch, data_dir):
    # animAction.cpp:104-149 case DO_TIR: the fire hot point deliberately
    # omits the step_x/y/z terms _hot_point_world adds for melee/throw, and
    # uses beta - 0x100 (not beta) for the sweep angle. Distinct non-zero
    # step_* values make sure an accidental step inclusion would move the
    # captured call away from this hand-computed expectation.
    game, actor_idx, victim_idx = _live_actors(data_dir, 2)
    actor = game.actors[actor_idx]
    actor.anim_action_type = DO_TIR
    actor.room_x, actor.room_y, actor.room_z = 1000, 2000, 3000
    actor.hot_point[:] = [10, 20, 30]
    actor.step_x, actor.step_y, actor.step_z = 1, 2, 3
    actor.beta = 0x300
    actor.anim_action_param = 50
    actor.hit_force = 9
    expected_room = actor.room

    captured = {}

    def fake_sweep(game_arg, actor_idx_arg, x, y, z, beta, room, param):
        captured["args"] = (actor_idx_arg, x, y, z, beta, room, param)
        return (victim_idx, 1111, 2222, 3333)

    monkeypatch.setattr("PyAitD.anim_action.check_line_projection_with_actors", fake_sweep)

    gere_frappe(game, actor_idx)

    # x = 1000 + 10 = 1010, y = 2000 + 20 = 2020, z = 3000 + 30 = 3030 (no
    # step_* terms); beta = 0x300 - 0x100 = 0x200 — computed by hand.
    assert captured["args"] == (actor_idx, 1010, 2020, 3030, 0x200, expected_room, 50)
    assert list(actor.hot_point) == [1111 - 1000, 2222 - 2000, 3333 - 3000]
    assert actor.hit == victim_idx
    assert game.actors[victim_idx].hit_by == actor_idx
    assert game.actors[victim_idx].hit_force == 9
    assert actor.anim_action_type == 0


def test_do_tir_miss_resets_without_publishing_hit(monkeypatch, data_dir):
    game, actor_idx = _live_actors(data_dir, 1)
    actor = game.actors[actor_idx]
    actor.anim_action_type = DO_TIR
    actor.hot_point[:] = [10, 20, 30]
    actor.hit = -1

    monkeypatch.setattr(
        "PyAitD.anim_action.check_line_projection_with_actors",
        lambda *args: (-1, 999, 999, 999),
    )

    gere_frappe(game, actor_idx)

    assert list(actor.hot_point) == [10, 20, 30]
    assert actor.hit == -1
    assert actor.anim_action_type == 0
