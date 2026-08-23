# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.game import FloorStart, enter_floor_start, init_game, relocate_actor


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
