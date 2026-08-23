# SPDX-License-Identifier: GPL-2.0-only
"""Melee hot-point timing and hit publication (FITD animAction.cpp GereFrappe)."""
import pytest

from PyAitD.actors import anim_player_for
from PyAitD.anim_action import (
    FRAPPE_OK, HIT_OBJECT, WAIT_FRAPPE_ANIM, WAIT_FRAPPE_FRAME, gere_frappe, refresh_hot_point,
)
from PyAitD.game import AF_ANIMATED, init_game
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
