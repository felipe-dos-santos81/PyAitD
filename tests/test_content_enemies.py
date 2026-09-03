# SPDX-License-Identifier: GPL-2.0-only
"""engine.content enemies: the pursuer/sentry state machine, unit-stepped
against a real attic boot, and the real-tick journeys of the example pack
(2026-09-03-content-packs-foundation-and-enemies-design.md, section 3)."""
import pytest

from PyAitD.engine.content import BEHAVIOUR_LIFE, load_pack
from PyAitD.engine.content.enemies import step_enemy
from PyAitD.engine.data.floor import Floor
from PyAitD.engine.script.game import init_game, relocate_actor, spawn_stage_actors
from PyAitD.engine.script.playworld import play_tick
from PyAitD.app.ui import InputBuffer

pytestmark = [pytest.mark.engine, pytest.mark.journey]

PROWLER, WATCHER = 292, 293


def _boot(data_dir, profile, example_pack_dir):
    pack = load_pack(example_pack_dir, data_dir, profile)
    game = init_game(data_dir, profile, pack=pack)
    floor = Floor(data_dir, 0, profile)
    play_tick(game, floor, InputBuffer())   # commits the spawn's pending anims
    return game, floor


def _actor(game, world_idx):
    slot = game.world_objects[world_idx].obj_index
    return None if slot == -1 else game.actors[slot]


def _slot(game, world_idx):
    return game.world_objects[world_idx].obj_index


def _tick_until(game, floor, predicate, *, limit):
    for tick in range(limit):
        play_tick(game, floor, InputBuffer())
        if predicate(game):
            return tick
    return -1


@pytest.fixture
def quiet_tick(monkeypatch):
    """play_tick's own behaviour branch is silenced so the explicit
    step_enemy calls below are the only thing driving the machine; the
    anim pass, collision and hit publication still run for real."""
    from PyAitD.engine.script.playworld import tick as tick_module
    monkeypatch.setattr(tick_module, "run_behaviour", lambda game, slot: None)


# ── the machine, one step at a time (quiet_tick: play_tick only animates) ────


def test_a_pursuer_leaves_idle_for_chase_on_its_first_step(data_dir, profile, example_pack_dir, quiet_tick):
    game, _ = _boot(data_dir, profile, example_pack_dir)
    record, state = game.content.record_for(PROWLER), game.content_state[PROWLER]
    actor = _actor(game, PROWLER)
    assert state["phase"] == "idle"
    step_enemy(game, _slot(game, PROWLER), record, state)
    assert state["phase"] == "chase"
    # LM_MOVE(2, hero) + LM_ANIM_REPEAT(walk), exactly what LISTLIFE 21 does
    assert (actor.track_mode, actor.track_number) == (2, game.current_world_target)
    assert (actor.new_anim, actor.new_anim_type) == (23, 1)


def test_a_pursuer_stays_idle_while_there_is_no_camera_target(data_dir, profile, example_pack_dir, quiet_tick):
    game, _ = _boot(data_dir, profile, example_pack_dir)
    record, state = game.content.record_for(PROWLER), game.content_state[PROWLER]
    slot = _slot(game, PROWLER)
    actor = _actor(game, PROWLER)
    hero_target = game.current_world_target

    game.current_world_target = -1
    step_enemy(game, slot, record, state)
    assert state["phase"] == "idle"
    assert actor.track_mode == 0

    game.current_world_target = hero_target
    step_enemy(game, slot, record, state)
    assert state["phase"] == "chase"
    assert actor.track_number == hero_target

    game.current_world_target = -1
    step_enemy(game, slot, record, state)
    assert state["phase"] == "idle"
    assert (actor.track_mode, actor.speed) == (0, 0)


def test_a_sentry_stays_put_until_the_hero_is_within_twice_its_range(data_dir, profile, example_pack_dir, quiet_tick):
    game, floor = _boot(data_dir, profile, example_pack_dir)
    record, state = game.content.record_for(WATCHER), game.content_state[WATCHER]
    watcher = _actor(game, WATCHER)
    hero_idx = game.current_camera_target_actor
    parked = (watcher.room_x, watcher.room_z, watcher.beta)
    for _ in range(10):
        step_enemy(game, _slot(game, WATCHER), record, state)
    assert state["phase"] == "idle"
    assert (watcher.room_x, watcher.room_z, watcher.beta) == parked
    assert watcher.new_anim == -1
    # hero 2200 units east: inside 2 * 1500, outside 1500 -> turns, no strike
    relocate_actor(game, hero_idx, 0, 0, 2500 + 2200, 0, 3500)
    step_enemy(game, _slot(game, WATCHER), record, state)
    assert state["phase"] == "idle"
    assert watcher.rotate.num_steps > 0 or watcher.beta != parked[2]
    assert (watcher.room_x, watcher.room_z) == parked[:2]
    # hero 1000 units east: inside range -> the strike is armed
    relocate_actor(game, hero_idx, 0, 0, 2500 + 1000, 0, 3500)
    step_enemy(game, _slot(game, WATCHER), record, state)
    assert state["phase"] == "attack"
    assert (watcher.anim_action_type, watcher.anim_action_anim, watcher.anim_action_frame) == (1, 25, 1)
    assert (watcher.hot_point_id, watcher.anim_action_param, watcher.hit_force) == (22, 400, 1)
    assert (watcher.new_anim, watcher.new_anim_info) == (25, 22)
    assert (watcher.track_mode, watcher.speed) == (0, 0)


def test_a_hit_costs_hit_points_then_hurt_then_dying_then_deletion(data_dir, profile, example_pack_dir, quiet_tick):
    game, floor = _boot(data_dir, profile, example_pack_dir)
    record, state = game.content.record_for(PROWLER), game.content_state[PROWLER]
    slot = _slot(game, PROWLER)
    actor = game.actors[slot]
    hero_idx = game.current_camera_target_actor
    step_enemy(game, slot, record, state)      # idle -> chase
    play_tick(game, floor, InputBuffer())      # walk anim commits
    step_enemy(game, slot, record, state)

    actor.hit_by, actor.hit_force = hero_idx, 1
    step_enemy(game, slot, record, state)
    assert (state["hp"], state["phase"]) == (2, "hurt")
    assert (actor.new_anim, actor.new_anim_type, actor.new_anim_info) == (21, 0, 22)
    assert (actor.track_mode, actor.speed) == (0, 0)
    actor.hit_by = -1

    # a second hit while hurt still counts, the anim is not restarted
    play_tick(game, floor, InputBuffer())
    actor.hit_by, actor.hit_force = hero_idx, 1
    step_enemy(game, slot, record, state)
    assert (state["hp"], state["phase"]) == (1, "hurt")
    assert actor.new_anim == -1
    actor.hit_by = -1

    # the hurt anim ends -> a pursuer resumes the chase
    ended = _tick_until(game, floor, lambda g: game.actors[slot].flag_end_anim == 1, limit=200)
    assert ended != -1
    step_enemy(game, slot, record, state)
    assert state["phase"] == "chase"
    assert actor.new_anim == 23

    # the last hit: dying, uninterruptible death anim, no arming left behind
    actor.hit_by, actor.hit_force = hero_idx, 1
    step_enemy(game, slot, record, state)
    assert (state["hp"], state["phase"]) == (0, "dying")
    assert (actor.new_anim, actor.new_anim_type, actor.new_anim_info) == (24, 2, -1)
    actor.hit_by = -1
    play_tick(game, floor, InputBuffer())
    assert actor.anim == 24
    # a hit while dying changes nothing
    actor.hit_by, actor.hit_force = hero_idx, 5
    step_enemy(game, slot, record, state)
    assert (state["hp"], state["phase"]) == (0, "dying")
    actor.hit_by = -1
    ended = _tick_until(game, floor, lambda g: game.actors[slot].flag_end_anim == 1, limit=400)
    assert ended != -1
    step_enemy(game, slot, record, state)
    assert state["phase"] == "dead"
    world = game.world_objects[PROWLER]
    assert (world.obj_index, world.stage, world.room) == (-1, -1, -1)
    assert actor.index_in_world == -1
    step_enemy(game, slot, record, state)      # dead stays dead, no raise
    assert state["phase"] == "dead"


def test_an_attack_returns_a_pursuer_to_chase_and_a_sentry_to_idle(data_dir, profile, example_pack_dir, quiet_tick):
    game, floor = _boot(data_dir, profile, example_pack_dir)
    hero_idx = game.current_camera_target_actor

    def swing_and_finish(world_idx):
        record, state = game.content.record_for(world_idx), game.content_state[world_idx]
        slot = _slot(game, world_idx)
        actor = game.actors[slot]
        relocate_actor(game, hero_idx, 0, 0, actor.room_x + 600, 0, actor.room_z)
        if record.kind == "pursuer":
            step_enemy(game, slot, record, state)   # idle -> chase
        step_enemy(game, slot, record, state)       # in range -> attack (one step: a sentry arms from idle)
        assert state["phase"] == "attack"
        play_tick(game, floor, InputBuffer())
        assert actor.anim == 25
        ended = _tick_until(game, floor, lambda g: game.actors[slot].flag_end_anim == 1, limit=300)
        assert ended != -1
        relocate_actor(game, hero_idx, 0, 0, actor.room_x + 6000, 0, actor.room_z)   # out of range
        step_enemy(game, slot, record, state)
        return state["phase"]

    assert swing_and_finish(PROWLER) == "chase"
    assert swing_and_finish(WATCHER) == "idle"


# ── the real tick, end to end ────────────────────────────────────────────────


def test_the_prowler_chases_the_hero_across_the_attic_and_arms_a_strike(data_dir, profile, example_pack_dir):
    game, floor = _boot(data_dir, profile, example_pack_dir)
    hero = game.actors[game.current_camera_target_actor]
    prowler = _actor(game, PROWLER)
    assert prowler is not None
    play_tick(game, floor, InputBuffer())
    assert game.content_state[PROWLER]["phase"] == "chase"
    assert (prowler.track_mode, prowler.track_number, prowler.new_anim) == (2, game.current_world_target, 23)
    play_tick(game, floor, InputBuffer())      # gere_anim commits the walk on the next anim pass
    assert prowler.anim == 23

    def gap(g):
        return abs(prowler.room_x - hero.room_x) + abs(prowler.room_z - hero.room_z)

    start_gap = gap(game)
    moved = _tick_until(game, floor, lambda g: abs(prowler.room_x + 5600) + abs(prowler.room_z - 1000) > 300, limit=200)
    assert moved != -1, "the prowler never left its spawn point"
    armed = _tick_until(game, floor, lambda g: g.content_state[PROWLER]["phase"] == "attack", limit=3000)
    assert armed != -1, f"the prowler never came within range: {start_gap} -> {gap(game)}"
    assert gap(game) < start_gap // 3
    assert (prowler.anim_action_type, prowler.anim_action_anim) == (1, 25)
    # the strike lands through gere_frappe like any scripted one
    landed = _tick_until(game, floor, lambda g: hero.hit_by == g.world_objects[PROWLER].obj_index, limit=1200)
    assert landed != -1, "the armed swing never reached the hero"


def test_a_pack_enemy_keeps_its_phase_and_hit_points_across_a_despawn_and_respawn(data_dir, profile, example_pack_dir):
    # spec section 3: hp and phase are keyed by world index (like the
    # original vars[]) and survive the despawn/respawn a room change
    # causes; a respawned enemy resumes the phase it was in. Provoked here
    # the way tests/test_game.py's phase1_delete_gates test does: drive
    # spawn_stage_actors's ROOM gate directly rather than faking a delete.
    game, floor = _boot(data_dir, profile, example_pack_dir)
    hero = game.actors[game.current_camera_target_actor]
    prowler = _actor(game, PROWLER)

    def gap(g):
        return abs(prowler.room_x - hero.room_x) + abs(prowler.room_z - hero.room_z)

    play_tick(game, floor, InputBuffer())
    assert game.content_state[PROWLER]["phase"] == "chase"
    start = (prowler.room_x, prowler.room_z)
    moved = _tick_until(
        game, floor,
        lambda g: abs(prowler.room_x - start[0]) + abs(prowler.room_z - start[1]) > 300,
        limit=200,
    )
    assert moved != -1, "the prowler never left its spawn point"
    before = dict(game.content_state[PROWLER])

    # despawn: life_mode "room" keeps an actor only while its room matches
    # the hero's; relocate the prowler's own actor to a room the hero is
    # not in and let spawn_stage_actors's ROOM gate delete it for real.
    slot = _slot(game, PROWLER)
    relocate_actor(game, slot, 0, game.current_room + 1, prowler.room_x, prowler.room_y, prowler.room_z)
    spawn_stage_actors(game)
    assert game.world_objects[PROWLER].obj_index == -1
    assert game.content_state[PROWLER] == before

    # respawn: move the world object (there is no actor to relocate any
    # more) back into the hero's room and let the same gate re-spawn it.
    game.world_objects[PROWLER].room = game.current_room
    spawn_stage_actors(game)
    assert game.world_objects[PROWLER].obj_index != -1
    assert game.content_state[PROWLER] == before
    assert game.content_state[PROWLER]["phase"] == "chase"

    prowler = _actor(game, PROWLER)
    assert prowler.track_mode == 2   # activate_world_object's init_deplacement re-armed the follow track

    start_gap = gap(game)
    closed = _tick_until(game, floor, lambda g: gap(game) < start_gap - 200, limit=300)
    assert closed != -1, "the respawned prowler never resumed closing on the hero"


def test_hits_in_the_real_loop_take_the_prowler_through_hurt_dying_and_out(data_dir, profile, example_pack_dir, monkeypatch):
    # play_tick resets hit_by before the anim pass; inject the hero's hit
    # right after that pass, where gere_frappe would publish it, so the
    # behaviour sees it at the LIFE loop's position (the same trick
    # tests/test_game_over.py uses on playworld.tick).
    from PyAitD.engine.script.playworld import tick as tick_module
    game, floor = _boot(data_dir, profile, example_pack_dir)
    hero_idx = game.current_camera_target_actor
    pending = {"hits": 0}
    real_anim_pass = tick_module._anim_pass

    def anim_pass_then_hit(g):
        result = real_anim_pass(g)
        if pending["hits"]:
            prowler = _actor(g, PROWLER)
            prowler.hit_by, prowler.hit_force = hero_idx, 1
            pending["hits"] -= 1
        return result

    monkeypatch.setattr(tick_module, "_anim_pass", anim_pass_then_hit)
    _tick_until(game, floor, lambda g: g.content_state[PROWLER]["phase"] == "chase", limit=10)
    _tick_until(game, floor, lambda g: False, limit=60)

    pending["hits"] = 1
    hurt = _tick_until(game, floor, lambda g: g.content_state[PROWLER]["phase"] == "hurt", limit=5)
    assert hurt != -1
    assert game.content_state[PROWLER]["hp"] == 2
    back = _tick_until(game, floor, lambda g: g.content_state[PROWLER]["phase"] == "chase", limit=300)
    assert back != -1, "the hurt anim never handed back to the chase"

    pending["hits"] = 2
    dying = _tick_until(game, floor, lambda g: g.content_state[PROWLER]["phase"] == "dying", limit=10)
    assert dying != -1
    assert game.content_state[PROWLER]["hp"] == 0
    slot = _slot(game, PROWLER)
    dead = _tick_until(game, floor, lambda g: g.content_state[PROWLER]["phase"] == "dead", limit=400)
    assert dead != -1, "the death anim never ended"
    assert game.world_objects[PROWLER].obj_index == -1
    assert game.world_objects[PROWLER].stage == -1
    assert game.actors[slot].index_in_world == -1

    # leaving and re-entering the room regenerates the active list; a dead
    # record has stage -1 and is skipped like a taken object
    game.flag_genere_aff_list = 1
    play_tick(game, floor, InputBuffer())
    assert game.world_objects[PROWLER].obj_index == -1
    assert game.content_state[PROWLER] == {"hp": 0, "phase": "dead"}


def test_the_watcher_never_moves_and_turns_to_face_a_hero_who_comes_close(data_dir, profile, example_pack_dir):
    game, floor = _boot(data_dir, profile, example_pack_dir)
    hero_idx = game.current_camera_target_actor
    watcher = _actor(game, WATCHER)
    parked = (watcher.room_x, watcher.room_y, watcher.room_z, watcher.beta)
    _tick_until(game, floor, lambda g: False, limit=300)
    assert (watcher.room_x, watcher.room_y, watcher.room_z, watcher.beta) == parked
    assert game.content_state[WATCHER]["phase"] == "idle"
    relocate_actor(game, hero_idx, 0, 0, 2500 - 2500, 0, 3500)    # 2500 west: turns, no strike
    turned = _tick_until(game, floor, lambda g: watcher.beta != parked[3], limit=120)
    assert turned != -1, "the watcher never turned toward the hero"
    assert (watcher.room_x, watcher.room_z) == (parked[0], parked[2])
    assert game.content_state[WATCHER]["phase"] == "idle"
    relocate_actor(game, hero_idx, 0, 0, 2500 - 1000, 0, 3500)    # 1000 west: in range
    armed = _tick_until(game, floor, lambda g: g.content_state[WATCHER]["phase"] == "attack", limit=10)
    assert armed != -1
    assert (watcher.room_x, watcher.room_z) == (parked[0], parked[2])


def test_the_trace_records_each_behaviour_step(data_dir, profile, example_pack_dir, tmp_path):
    from PyAitD.engine.script.life import Trace
    game, floor = _boot(data_dir, profile, example_pack_dir)
    game.trace = Trace(tmp_path / "t.log")
    play_tick(game, floor, InputBuffer())
    play_tick(game, floor, InputBuffer())
    game.trace.close()
    lines = (tmp_path / "t.log").read_text().splitlines()
    prowler, watcher = _slot(game, PROWLER), _slot(game, WATCHER)
    behaviour = [line for line in lines if " BEHAVIOUR " in line]
    assert f"{game.timer - 1} {prowler} BEHAVIOUR chase" in behaviour
    assert f"{game.timer - 1} {watcher} BEHAVIOUR idle" in behaviour
    assert f"{game.timer} {prowler} BEHAVIOUR chase" in behaviour
