# SPDX-License-Identifier: GPL-2.0-only
"""Melee hot-point timing and hit publication (FITD animAction.cpp GereFrappe)."""
import pytest

from PyAitD.anim_action import (
    FRAPPE_OK, HIT_OBJECT, WAIT_FRAPPE_ANIM, WAIT_FRAPPE_FRAME, gere_frappe,
)
from PyAitD.game import AF_ANIMATED, init_game


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
