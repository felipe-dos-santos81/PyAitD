# SPDX-License-Identifier: GPL-2.0-only
import struct

from PyAitD.floor import Floor
from PyAitD.game import FloorStart, enter_floor_start, init_game, relocate_actor
from PyAitD.life import process_life
from PyAitD.playworld import play_tick
from PyAitD.scenario import enter_combat_venue
from PyAitD.ui import InputBuffer


def test_relocate_actor_rebases_zv_and_zeroes_steps(data_dir):
    game = init_game(data_dir)
    idx = game.current_camera_target_actor
    actor = game.actors[idx]
    actor.step_x, actor.step_y, actor.step_z = 11, 12, 13
    old_zv = list(actor.zv)
    old_actual = (actor.room_x + 11, actor.room_y + 12, actor.room_z + 13)

    relocate_actor(game, idx, 5, 4, -7800, -4010, -1000)

    delta = (-7800 - old_actual[0], -4010 - old_actual[1], -1000 - old_actual[2])
    assert actor.zv == [
        old_zv[0] + delta[0], old_zv[1] + delta[0],
        old_zv[2] + delta[1], old_zv[3] + delta[1],
        old_zv[4] + delta[2], old_zv[5] + delta[2],
    ]
    assert (actor.stage, actor.room) == (5, 4)
    assert (actor.room_x, actor.room_y, actor.room_z) == (-7800, -4010, -1000)
    assert (actor.step_x, actor.step_y, actor.step_z) == (0, 0, 0)


def test_enter_floor_start_applies_transition_postconditions(data_dir, monkeypatch):
    import PyAitD.game as game_module
    game = init_game(data_dir)
    calls = []
    real_spawn = game_module.spawn_stage_actors
    monkeypatch.setattr(
        game_module, "spawn_stage_actors",
        lambda current: (calls.append(current.current_floor), real_spawn(current))[1],
    )
    start = FloorStart(5, 4, -7800, -4010, -1000, 0)

    enter_floor_start(game, start)

    assert calls == [5]
    assert (game.current_floor, game.new_num_etage) == (5, 5)
    assert (game.current_room, game.new_num_salle) == (4, 4)
    assert game.new_num_camera == 0
    assert (game.num_camera, game.flag_init_view) == (-1, 2)
    assert (game.flag_change_etage, game.flag_genere_aff_list) == (0, 0)


def test_init_game_records_the_real_hero_start(data_dir):
    game = init_game(data_dir)
    hero = game.actors[game.current_camera_target_actor]
    assert game.floor_start == FloorStart(
        hero.stage, hero.room, hero.room_x, hero.room_y, hero.room_z, 0,
    )
    assert game.restart_requested is False


def test_natural_lm_stage_records_a_reenterable_floor_start(data_dir, monkeypatch):
    # The real transition this fixture replays: the hero's own death sequence
    # (LISTLIFE 555) runs LM_STAGE(6, 6, -5000, -4000, 11500) after LIFE 39.
    # FITD gives a floor change no camera continuity -- LoadEtage sets
    # NumCamera = -1 (floor.cpp:39), so ChangeSalle's oldCameraIdx is -1, no
    # slot matches, and its `int newNumCamera = 0` (room.cpp:112) is what
    # reaches NewNumCamera (room.cpp:193). Slot 0 is therefore the observed
    # entry camera, not an assumption.
    game = init_game(data_dir)
    enter_combat_venue(game)
    floor = Floor(data_dir, 5)
    game.current_floor_data = floor
    game.num_camera = game.new_num_camera
    game.flag_init_view = 0
    for _ in range(3):
        play_tick(game, floor, InputBuffer())
    assert game.num_camera not in (-1, 0), (
        "precondition: the venue's camera switch must have left slot 0, so the "
        "entry slot below cannot be leftover state"
    )

    hero_idx = game.current_camera_target_actor
    hero = game.actors[hero_idx]
    monkeypatch.setattr(
        game.assets, "life",
        lambda index: struct.pack("<7h", 47, 6, 6, -5000, -4000, 11500, 11),
    )
    process_life(game, hero_idx, hero.life)

    assert (hero.stage, hero.room) == (6, 6)
    assert (hero.room_x, hero.room_y, hero.room_z) == (-5000, -4000, 11500)
    assert game.flag_change_etage == 1
    assert (game.new_num_etage, game.new_num_salle) == (6, 6)
    assert game.floor_start == FloorStart(6, 6, -5000, -4000, 11500, 0)

    # finish the handoff the outer loop performs: swap the Floor, enter the
    # recorded boundary, then InitView.
    floor = Floor(data_dir, 6)
    game.current_floor_data = floor
    assert len(floor.rooms[6].camera_indices) > game.floor_start.camera_slot
    enter_floor_start(game, game.floor_start)
    game.num_camera = game.new_num_camera
    game.flag_init_view = 0

    assert game.floor_start.camera_slot == game.num_camera
    assert game.current_floor == 6 and game.current_room == 6
    assert game.actors[game.current_camera_target_actor] is hero
    assert game.world_objects[40].obj_index != -1  # floor 6's own actors spawned
