# SPDX-License-Identifier: GPL-2.0-only
"""M3c end-to-end combat journeys against the real game data.

Nothing here writes `hit`, `hit_by`, `hit_force`, `life`, script variable 21,
`flag_game_over` or `active_modal`: the enemy's own LISTLIFE script arms a real
`LM_HIT`, the real action runner publishes it, and the real hero script consumes
it. `relocate_actor` is used only to take the enemy's nondeterministic circling
out of the death journey.
"""
import struct

import numpy as np
import pytest

from PyAitD.app.shell import _auto_dismiss_picture, restart_session, route_mouse
from PyAitD.engine.anim_action import (
    DO_TIR, FRAPPE_OK, THROW_OBJECT, WAIT_FRAPPE_ANIM, WAIT_FRAPPE_FRAME, gere_frappe,
)
from PyAitD.engine.effects import GameMode, GameOver
from PyAitD.engine.data.floor import Floor
from PyAitD.engine.game import AF_ANIMATED, init_game, relocate_actor
from PyAitD.engine.life import process_life
from PyAitD.engine.playworld import TICK_MS, play_tick
from PyAitD.games.aitd1.scenario import COMBAT_VENUE, enter_combat_venue
from PyAitD.app.ui import InputBuffer, ModalSession, UIPainter, render_game_over, transparent_canvas

pytestmark = [pytest.mark.engine, pytest.mark.journey]


def _venue(data_dir, profile):
    game = init_game(data_dir, profile)
    enter_combat_venue(game)
    return game, Floor(data_dir, 5, profile), game.world_objects[222].obj_index


def test_obj222_real_script_hits_and_hero_consumes_same_tick(data_dir, profile):
    game, floor, enemy_idx = _venue(data_dir, profile)
    hero_idx = game.current_camera_target_actor
    observed = False
    for _ in range(2400):
        play_tick(game, floor, InputBuffer())
        if game.actors[hero_idx].hit_by == enemy_idx:
            observed = True
            assert game.actors[enemy_idx].hit == hero_idx
            # Measured on real data: var 21 (health) is 20 both before and
            # after this tick — the decrement lands on a later tick, so the
            # "hero consumes in the same tick" claim is carried entirely by
            # this life assertion, not by var 21.
            assert game.actors[hero_idx].life == 553
            break
    assert observed, "obj222 never published its real scripted melee hit"


def _fight_to_death(data_dir, profile, budget):
    """Run the real venue fight, keeping the enemy on the hero, until the real
    hero script has selected its death LIFE. Returns (game, floor, saw_death)."""
    game, floor, enemy_idx = _venue(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    saw_death_life = False
    for _ in range(budget):
        if game.vars[21] > 0:
            relocate_actor(
                game, enemy_idx, 5, 4,
                hero.room_x, hero.room_y, hero.room_z + 300,
            )
        play_tick(game, floor, InputBuffer())
        saw_death_life |= hero.life == 39
        if saw_death_life and game.vars[21] == 0:
            break
    return game, floor, saw_death_life


def test_real_enemy_damage_empties_health_and_selects_the_death_life(data_dir, profile):
    # Real data: hero script var 21 starts at 20 and obj222's LM_HIT carries
    # force 1, so the real fight needs 20 landed hits; the hero's LIFE then
    # runs 549 -> 553 per hit and selects death LIFE 39 at var 21 == 0.
    game, _floor, saw_death_life = _fight_to_death(data_dir, profile, 12000)
    assert game.vars[21] == 0
    assert game.vars[24] == 1
    assert saw_death_life


def _journey_to_game_over(data_dir, profile, budget=12000):
    """The whole real death path: 20 published hits, LIFE 39, LIFE 555's
    LM_STAGE onto floor 6, LIFE 554's LM_PICTURE, then LM_GAME_OVER."""
    game, floor, saw_death_life = _fight_to_death(data_dir, profile, budget)
    loop_session = ModalSession()
    for _ in range(budget):
        if game.mode is GameMode.GAME_OVER:
            break
        if game.active_modal is not None:
            # a non-PLAY frame of __main__.run: no tick, the modal clock runs,
            # and the death sequence's LM_PICTURE auto-dismisses on its delay
            loop_session.reset_for(game.active_modal)
            loop_session.elapsed_ms += TICK_MS
            _auto_dismiss_picture(game, loop_session)
            continue
        play_tick(game, floor, InputBuffer())
        if floor.number != game.current_floor:
            # the outer loop owns Floor I/O (__main__.run does exactly this)
            floor = Floor(data_dir, game.current_floor, profile)
    return game, saw_death_life


def test_real_enemy_damage_reaches_game_over_and_fresh_restart(data_dir, profile):
    game, saw_death_life = _journey_to_game_over(data_dir, profile)

    assert game.vars[21] == 0
    assert saw_death_life
    assert game.active_modal == GameOver(120)

    session = ModalSession()
    session.reset_for(game.active_modal)
    frozen = np.zeros((200, 320, 3), dtype=np.uint8)
    painter = UIPainter()
    render_game_over(painter, frozen, ready=False)
    assert np.array_equal(painter.to_frame(), transparent_canvas())
    session.elapsed_ms = 1999
    route_mouse(game, session, (0, 0))
    assert game.restart_requested is False
    session.elapsed_ms = 2000
    route_mouse(game, session, (319, 199))
    assert game.restart_requested is True

    restarted = restart_session(game)
    assert restarted.vars[21] == 20
    assert restarted.active_modal is None


@pytest.mark.xfail(
    strict=True,
    reason="the death cinematic's own LM_STAGE onto floor 6 (LISTLIFE 555) "
           "overwrites the restart boundary through op_stage, so restart "
           "rebuilds the session in the death stage instead of the venue the "
           "player was fighting in. See docs/m3c-combat-proof.md.",
)
def test_restart_after_death_returns_to_the_venue_that_was_played(data_dir, profile):
    game, _saw_death_life = _journey_to_game_over(data_dir, profile)
    # precondition, so a broken journey fails this test instead of turning the
    # expected failure below into an XPASS for the wrong reason
    assert game.active_modal == GameOver(120)
    assert restart_session(game).floor_start == COMBAT_VENUE


class _OneLife:
    """One synthetic LIFE script; every other asset comes from the real registry."""

    def __init__(self, base, words):
        self.base = base
        self.script = struct.pack(f"<{len(words)}h", *words)

    def life(self, index):
        return self.script if index == 999 else self.base.life(index)

    def __getattr__(self, name):
        return getattr(self.base, name)


def _execute_words(game, actor_idx, words):
    assets = game.assets
    game.assets = _OneLife(assets, words)
    try:
        process_life(game, actor_idx, 999)
    finally:
        game.assets = assets


def test_player_melee_executes_opcode_and_runner(data_dir, profile, monkeypatch):
    game, _floor, victim_idx = _venue(data_dir, profile)
    hero_idx = game.current_camera_target_actor
    hero = game.actors[hero_idx]
    assert (hero.body_num, hero.anim, hero.frame) == (12, 4, 0)  # real venue pose
    hero.object_type &= ~AF_ANIMATED  # makes same real anim 4 acceptable to InitAnim
    # FITD main.cpp:4375-4386 hit(anim, frame, group, radius, force, next).
    # The strike frame is 1, not 0: the hero already stands on frame 0 of the
    # same real anim, and arming there would collapse 1 -> 10 -> 2 into the
    # single fall-through call FITD documents (animAction.cpp:24), leaving both
    # wait states untested.
    _execute_words(game, hero_idx, [16, 4, 1, 0, 2000, -1, 10, 4, 11])
    monkeypatch.setattr("PyAitD.engine.anim_action.check_object_col", lambda *args: (victim_idx,))
    assert hero.anim_action_type == WAIT_FRAPPE_ANIM
    gere_frappe(game, hero_idx); assert hero.anim_action_type == WAIT_FRAPPE_FRAME
    hero.frame = 1  # the strike frame gere_anim would reach (anim 4 has 4 frames)
    gere_frappe(game, hero_idx); assert hero.anim_action_type == FRAPPE_OK
    gere_frappe(game, hero_idx)
    assert hero.hit == victim_idx
    assert game.actors[victim_idx].hit_force == 10


def test_player_fire_executes_opcode_and_runner(data_dir, profile, monkeypatch):
    game, _floor, victim_idx = _venue(data_dir, profile)
    hero_idx = game.current_camera_target_actor
    hero = game.actors[hero_idx]
    hero.object_type &= ~AF_ANIMATED
    # FITD life.cpp:66-78 fire(anim, frame, group, radius, force, next)
    _execute_words(game, hero_idx, [53, 4, 0, 0, 50, 12, 4, 11])
    monkeypatch.setattr(
        "PyAitD.engine.anim_action.check_line_projection_with_actors",
        lambda *args: (victim_idx, hero.room_x + 20, hero.room_y, hero.room_z + 30),
    )
    gere_frappe(game, hero_idx); assert hero.anim_action_type == DO_TIR
    gere_frappe(game, hero_idx)
    assert hero.hit == victim_idx
    assert game.actors[victim_idx].hit_force == 12
    assert hero.hot_point == [20, 0, 30]


def test_player_throw_executes_setup_launch_and_flight(data_dir, profile, monkeypatch):
    game, _floor, victim_idx = _venue(data_dir, profile)
    hero_idx = game.current_camera_target_actor
    hero = game.actors[hero_idx]
    object_idx = 13  # real floor-0 inventory candidate, body 9
    assert game.world_objects[object_idx].body == 9
    hero.object_type &= ~AF_ANIMATED
    game.inventory_table[0][0] = object_idx
    game.inventory_count[0] = 1
    # FITD life.cpp:18-36 throwObj(anim, frame, group, object, rotated, force, next)
    _execute_words(game, hero_idx, [76, 4, 0, 0, object_idx, 1, 14, 4, 11])
    monkeypatch.setattr("PyAitD.engine.anim_action.check_hard_col", lambda *args: [])
    gere_frappe(game, hero_idx)
    thrown_idx = game.world_objects[object_idx].obj_index
    assert thrown_idx != -1, "throw release must activate its own world object"
    assert game.actors[thrown_idx].index_in_world == object_idx
    gere_frappe(game, hero_idx)
    assert game.actors[thrown_idx].anim_action_type == THROW_OBJECT
    monkeypatch.setattr("PyAitD.engine.anim_action.check_object_col", lambda *args: (victim_idx,))
    monkeypatch.setattr("PyAitD.engine.anim_action.throw_stopped_at", lambda *args: None)
    gere_frappe(game, thrown_idx)
    assert game.actors[thrown_idx].hit == victim_idx
    assert game.actors[victim_idx].hit_force == 14


def test_armed_melee_survives_a_hot_point_group_the_body_does_not_have(
        data_dir, profile):
    """The whole tick, not just the runner: a real swing must not crash.

    The hero's body is 12 (17 groups) in the object data for both heroes,
    while its own animations address 19 and 20, and the saber's LIFE 49 arms
    its hit on group 18. getHotPoint (main.cpp:2976) indexes the group array
    with no bounds check, so the original reads past it and carries on; a port
    that raises there kills the game on every armed swing. Driven through
    play_tick, which is the only path that reaches refresh_hot_point.
    """
    from PyAitD.engine.effects import InputMode
    from PyAitD.engine.interaction import _finish_take, sync_player_track_mode

    game, floor, enemy_idx = _venue(data_dir, profile)
    game.current_floor_data = floor
    game.input_mode = InputMode.KEYBOARD
    sync_player_track_mode(game)
    _finish_take(game, 38)
    game.in_hand_table[game.current_inventory] = 38
    hero = game.actors[game.current_camera_target_actor]
    buf = InputBuffer(action_held=True, held_joyd=1, focused=True)

    landed = False
    for _ in range(400):
        # same reason _fight_to_death relocates: the enemy's own circling is
        # nondeterministic, and this test is about the swing, not the chase
        relocate_actor(
            game, enemy_idx, game.current_floor, hero.room,
            hero.room_x, hero.room_y, hero.room_z + 500,
        )
        play_tick(game, floor, buf)      # must not raise
        if hero.hit == enemy_idx:
            landed = True
            break

    assert landed, "the armed swing never reached the enemy"
    assert hero.hot_point_id >= len(game.assets.body(hero.body_num).groups), (
        "the out-of-range group this pins is gone; the guard needs a new case"
    )
