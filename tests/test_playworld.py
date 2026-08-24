# SPDX-License-Identifier: GPL-2.0-only
"""PlayWorld is the simulation tick, importable without pygame or the Renderer."""
import subprocess
import sys

import pytest

from PyAitD.anim_action import WAIT_FRAPPE_ANIM
from PyAitD.floor import Floor
from PyAitD.game import init_game
from PyAitD.interaction import PLAYER_PUSH_ANIM
from PyAitD.playworld import _anim_pass, play_tick
from PyAitD.ui import InputBuffer

# Runs in a fresh interpreter: pytest (and this module, via InputBuffer) has
# pygame loaded in-process, so sys.modules is only meaningful out-of-process.
# A static import walk cannot substitute — it reports pygame reachable through
# interaction.apply_found_result's deferred `from PyAitD.ui import FoundResult`.
_PURITY_PROBE = """
import sys, PyAitD.playworld, PyAitD.anim_action
# the layer rule, then the third-party names a direct import would pull in
leaked = {"PyAitD.ui", "PyAitD.render", "pygame", "moderngl", "OpenGL"} & sys.modules.keys()
sys.exit(", ".join(sorted(leaked)) or None)
"""


def test_playworld_does_not_import_the_presentation_layer():
    out = subprocess.run([sys.executable, "-c", _PURITY_PROBE], capture_output=True, text=True)
    assert out.returncode == 0, (
        f"PyAitD.playworld pulled in {out.stderr.strip()} — the tick must stay "
        f"importable without the presentation layer so it can run headless"
    )


def test_play_tick_advances_the_world_without_a_display(data_dir):
    # No Renderer, no display, and no SDL_VIDEODRIVER needed. Constructing the
    # InputBuffer still imports pygame: it is a pygame-free dataclass that lives
    # in ui.py, whose module scope evaluates pygame.K_* and pygame.Rect.
    game = init_game(data_dir, hero=0)
    floor = Floor(data_dir, game.current_floor)
    buf = InputBuffer()
    start = game.timer
    for _ in range(60):
        play_tick(game, floor, buf)
    assert game.timer > start
    assert game.flag_game_over == 0


from PyAitD.effects import GameMode, InputMode, NavIntent
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
    # apply_play_input is called directly here (not through play_tick), so the
    # Floor that _apply_mouse_input's mesh build needs must be stashed by hand
    # — play_tick normally does this at the top of every tick.
    game.current_floor_data = Floor(data_dir, game.current_floor)
    hero = game.actors[game.current_camera_target_actor]
    game.nav_intent = NavIntent(
        dest_x=hero.room_x, dest_z=hero.room_z + 9000, room=hero.room,
        waypoints=[(hero.room_x, hero.room_z + 9000)],
    )
    apply_play_input(game, InputBuffer())
    assert game.nav_decision is not None
    assert game.local_joyd & 1, "scripts reading evalVar 0x13 must see movement"


@pytest.mark.parametrize("hero_id", (0, 1))
def test_engaged_wardrobe_retargets_and_never_asserts_action(data_dir, hero_id):
    game = init_game(data_dir, hero=hero_id)
    floor = Floor(data_dir, game.current_floor)
    hero = game.actors[game.current_camera_target_actor]
    target = game.actors[game.world_objects[4].obj_index]
    game.current_floor_data = floor
    game.nav_intent = NavIntent(
        target.room_x, target.room_z, target.room, 4,
        requires_hold=True, engaged=True,
        waypoints=[(target.room_x, target.room_z)], path_room=target.room,
    )
    buf = InputBuffer(pointer_held=True)
    apply_play_input(game, buf)
    assert game.action == game.local_click == 0
    old = (target.room_x, target.room_z)
    target.room_x += 20
    target.room_z += 30
    apply_play_input(game, buf)
    assert (game.nav_intent.dest_x, game.nav_intent.dest_z) == (old[0] + 20, old[1] + 30)
    assert hero.new_anim == PLAYER_PUSH_ANIM


def test_held_intent_cancels_when_release_is_observed(data_dir):
    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.current_floor_data = floor
    target = game.actors[game.world_objects[4].obj_index]
    game.nav_intent = NavIntent(
        target.room_x, target.room_z, target.room, 4,
        requires_hold=True, engaged=True, waypoints=[(target.room_x, target.room_z)],
        path_room=target.room,
    )
    apply_play_input(game, InputBuffer(pointer_held=False))
    assert game.nav_intent is None
    assert (game.local_joyd, game.local_click, game.action) == (0, 0, 0)


@pytest.mark.parametrize("engaged", (False, True), ids=("approach", "engaged"))
@pytest.mark.parametrize("invalidation", ("despawn", "room", "floor", "eligibility"))
def test_held_intent_cancels_when_the_live_target_is_invalid(
        data_dir, engaged, invalidation,
):
    from PyAitD.interaction import hold_action_approach

    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.current_floor_data = floor
    world = game.world_objects[4]
    target = game.actors[world.obj_index]
    if engaged:
        payload = (target.room_x, target.room_z, target.room, 4)
    else:
        payload = hold_action_approach(
            game, floor, game.current_camera_target_actor, world.obj_index,
        )
        assert payload is not None
    game.nav_intent = NavIntent(
        *payload, requires_hold=True, engaged=engaged,
        waypoints=[(payload[0], payload[1])], path_room=payload[2],
    )
    if invalidation == "despawn":
        world.obj_index = -1
    elif invalidation == "room":
        target.room += 1
    elif invalidation == "floor":
        game.current_floor += 1
    else:
        target.body_num = -1
    apply_play_input(game, InputBuffer(pointer_held=True))
    assert game.nav_intent is None
    assert (game.local_joyd, game.local_click, game.action) == (0, 0, 0)


@pytest.mark.parametrize("engaged", (False, True), ids=("approach", "engaged"))
def test_latched_world_target_cancels_if_slot_points_at_another_eligible_actor(
        data_dir, engaged,
):
    from PyAitD.interaction import hold_action_approach, is_hold_action_target

    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.current_floor_data = floor
    hero_idx = game.current_camera_target_actor
    world = game.world_objects[4]
    target = game.actors[world.obj_index]
    if engaged:
        payload = (target.room_x, target.room_z, target.room, 4)
    else:
        payload = hold_action_approach(game, floor, hero_idx, world.obj_index)
        assert payload is not None
    game.nav_intent = NavIntent(
        *payload, requires_hold=True, engaged=engaged,
        waypoints=[(payload[0], payload[1])], path_room=payload[2],
    )
    replacement_idx = game.world_objects[6].obj_index
    assert is_hold_action_target(game, replacement_idx) is True
    world.obj_index = replacement_idx
    apply_play_input(game, InputBuffer(pointer_held=True))
    assert game.nav_intent is None
    assert (game.local_joyd, game.local_click, game.action) == (0, 0, 0)


def test_approach_refreshes_its_adjacent_destination_when_the_target_moves(data_dir):
    from PyAitD.interaction import hold_action_approach

    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.current_floor_data = floor
    hero_idx = game.current_camera_target_actor
    actor_idx = game.world_objects[4].obj_index
    target = game.actors[actor_idx]
    payload = hold_action_approach(game, floor, hero_idx, actor_idx)
    assert payload is not None
    old_x, old_z, room, world_idx = payload
    game.nav_intent = NavIntent(old_x, old_z, room, world_idx, requires_hold=True)
    target.room_x += 100
    target.world_x += 100
    target.zv[0] += 100
    target.zv[1] += 100
    apply_play_input(game, InputBuffer(pointer_held=True))
    assert game.nav_intent is not None and game.nav_intent.engaged is False
    assert (game.nav_intent.dest_x, game.nav_intent.dest_z) == (old_x + 100, old_z)
    assert (game.nav_intent.dest_x, game.nav_intent.dest_z) != (
        target.room_x, target.room_z,
    )


def test_active_push_suppresses_the_verified_pending_walk_request(data_dir):
    from PyAitD.life_ops import ANIM_REPEAT

    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.current_floor_data = floor
    hero = game.actors[game.current_camera_target_actor]
    target = game.actors[game.world_objects[4].obj_index]
    game.nav_intent = NavIntent(
        target.room_x, target.room_z, target.room, 4,
        requires_hold=True, engaged=True,
        waypoints=[(target.room_x, target.room_z)], path_room=target.room,
    )
    hero.anim = PLAYER_PUSH_ANIM
    hero.new_anim = 254
    hero.new_anim_type = ANIM_REPEAT
    hero.new_anim_info = -1
    apply_play_input(game, InputBuffer(pointer_held=True))
    assert (hero.new_anim, hero.new_anim_type, hero.new_anim_info) == (-1, 0, -1)


def test_active_push_preserves_an_unrelated_uninterruptible_animation_request(data_dir):
    from PyAitD.life_ops import ANIM_UNINTERRUPTABLE

    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.current_floor_data = floor
    hero = game.actors[game.current_camera_target_actor]
    target = game.actors[game.world_objects[4].obj_index]
    game.nav_intent = NavIntent(
        target.room_x, target.room_z, target.room, 4,
        requires_hold=True, engaged=True,
        waypoints=[(target.room_x, target.room_z)], path_room=target.room,
    )
    hero.anim = PLAYER_PUSH_ANIM
    hero.new_anim = 99
    hero.new_anim_type = ANIM_UNINTERRUPTABLE
    hero.new_anim_info = 77
    apply_play_input(game, InputBuffer(pointer_held=True))
    assert (hero.new_anim, hero.new_anim_type, hero.new_anim_info) == (
        99, ANIM_UNINTERRUPTABLE, 77,
    )


def test_stale_off_route_collision_witness_does_not_redirect_contact(data_dir):
    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.current_floor_data = floor
    hero_idx = game.current_camera_target_actor
    target_idx = game.world_objects[4].obj_index
    target = game.actors[target_idx]
    stale = game.actors[game.world_objects[6].obj_index]
    stale.col_by = hero_idx
    game.nav_intent = NavIntent(
        target.room_x, target.room_z, target.room, 4,
        requires_hold=True, engaged=True,
        waypoints=[(target.room_x, target.room_z)], path_room=target.room,
    )
    apply_play_input(game, InputBuffer(pointer_held=True))
    assert game.nav_decision is not None
    assert (game.nav_decision.target_x, game.nav_decision.target_z) == (
        target.room_x, target.room_z,
    )


@pytest.mark.parametrize("hero_id", (0, 1))
def test_real_wardrobe_moves_only_after_life_enables_it(data_dir, hero_id):
    from PyAitD.game import AF_MOVABLE
    from PyAitD.interaction import hold_action_approach

    game = init_game(data_dir, hero=hero_id)
    floor = Floor(data_dir, game.current_floor)
    # The real opening scripts perform an unrelated begin_take(object 2) on
    # their first pass, which sets Action 0x800 for that boot tick.  Complete
    # that bootstrap before measuring the held-push interval.
    play_tick(game, floor, InputBuffer())
    play_tick(game, floor, InputBuffer())
    assert game.action == game.local_click == 0
    hero_idx = game.current_camera_target_actor
    actor_idx = game.world_objects[4].obj_index
    payload = hold_action_approach(game, floor, hero_idx, actor_idx)
    assert payload is not None
    dest_x, dest_z, room, world_idx = payload
    game.nav_intent = NavIntent(
        dest_x, dest_z, room, world_idx, requires_hold=True,
    )
    wardrobe = game.actors[actor_idx]
    start = (wardrobe.room_x, wardrobe.room_z)
    buffer = InputBuffer(pointer_held=True)
    movable_seen = False
    action_seen = 0
    for _tick in range(2500):
        play_tick(game, floor, buffer)
        action_seen |= game.action | game.local_click
        movable_seen |= bool(wardrobe.object_type & AF_MOVABLE)
        if (wardrobe.room_x, wardrobe.room_z) != start:
            assert movable_seen is True
            break
    assert (wardrobe.room_x, wardrobe.room_z) != start
    assert action_seen == 0
    assert game.nav_intent is not None and game.nav_intent.engaged


def test_hero_walks_to_a_clicked_destination_and_arrives(data_dir):
    from PyAitD.navigate import ARRIVE_DISTANCE
    from PyAitD.realvalue import give_distance_2d

    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    hero = game.actors[game.current_camera_target_actor]
    # Deliberately NOT set here. Object data spawns the hero in track mode 1
    # (tank), and mouse is the default input mode: if init_game does not put the
    # hero into the follower's mode 4, process_track hands the follower's
    # mirrored joyd to _process_track_manual, which reads it as *keyboard*
    # input. The hero then walks a long way in the wrong direction — which is
    # why this test asserts where it ended up, not merely that it moved.
    assert hero.track_mode == 4, "init_game left the hero in tank mode"
    mesh = game.nav_meshes.mesh_for(floor, hero.room, agent_extent(hero))
    goal = mesh.center_of(100, 45)   # walkable, and clear of room 0's two sce_zones
    assert mesh.is_walkable(*goal), "the fixture goal must be on the mesh"
    assert not any(
        zone.x1 <= goal[0] <= zone.x2 and zone.z1 <= goal[1] <= zone.z2
        for zone in floor.rooms[hero.room].sce_zones
    ), "the goal must not be a trigger/transition zone"
    start = (hero.room_x, hero.room_z)
    game.nav_intent = NavIntent(goal[0], goal[1], hero.room)
    buf = InputBuffer()
    joyd_seen = 0
    for tick in range(600):
        # play_tick returns False whenever a LIFE script suspends mid-tick
        # (e.g. a background actor's own message op) — that is a normal
        # "the tick did not finish, call me again" signal, not game-over;
        # test_play_tick_advances_the_world_without_a_display already relies
        # on this by ignoring the return value outright. Treating a bare
        # False as a hard stop aborted this loop after tick 0, before the
        # hero had moved at all — game.mode is the real stop signal.
        play_tick(game, floor, buf)
        if game.mode is not GameMode.PLAY:
            break
        joyd_seen |= game.local_joyd
        # hero.track_mode is owned by the hero's LIFE script (LM_DO_MOVE ->
        # process_track dispatches on it); apply_play_input re-asserts the
        # follower mode every tick, so this must hold all the way through.
        assert hero.track_mode == 4, "the hero fell out of mouse-follow mode"
        if game.nav_intent is None:
            break
    assert game.nav_intent is None, "the hero never reached the destination"
    assert joyd_seen & 1, "scripts reading evalVar 0x13 must have seen movement"
    here = (hero.room_x + hero.step_x, hero.room_z + hero.step_z)
    assert give_distance_2d(*here, *goal) < ARRIVE_DISTANCE, (
        f"stopped at {here}, not at the goal {goal} "
        f"(started at {start})"
    )
    assert hero.room == 0, "the walk must not have left the room"
    assert game.action == 0, "a bare floor walk does not press the action button"


def test_anim_pass_refreshes_before_anim_and_strikes_after_dec(monkeypatch, data_dir):
    # idx is the hero (current_camera_target_actor), not actor 0: actor 0 is
    # live but carries neither AF_ANIMATED nor AF_TRIGGER nor a set
    # anim_action_type in the real floor-0 data, so it contributes zero
    # entries to `calls` and the hero supplies the whole calls[:4] slice —
    # the contract pinned here is refresh-before-anim, strike-after-dec, in
    # that order, for the armed actor.
    game = init_game(data_dir)
    idx = game.current_camera_target_actor
    game.actors[idx].anim_action_type = WAIT_FRAPPE_ANIM
    game.actors[idx].hot_point_id = 0
    calls = []
    monkeypatch.setattr("PyAitD.playworld.refresh_hot_point", lambda *args: calls.append("hot"))
    monkeypatch.setattr("PyAitD.playworld.gere_anim", lambda *args: calls.append("anim"))
    monkeypatch.setattr("PyAitD.playworld.gere_dec", lambda *args: calls.append("dec"))
    monkeypatch.setattr("PyAitD.playworld.gere_frappe", lambda *args: calls.append("hit"))
    _anim_pass(game)
    assert calls[:4] == ["hot", "anim", "dec", "hit"]
