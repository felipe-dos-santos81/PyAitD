# SPDX-License-Identifier: GPL-2.0-only
import pytest

from maitd.game import NUM_MAX_OBJECT, Game, init_game, game_step_tick, spawn_stage_actors


def test_init_golden(data_dir):
    game = init_game(data_dir, hero=0)
    assert len(game.world_objects) == 292
    assert len(game.actors) == NUM_MAX_OBJECT
    assert len(game.cvars) == 45
    assert len(game.vars) == 207
    assert game.cvars[7] == 1 and game.cvars[8] == 0
    assert game.current_world_target == 1


def test_stage_actors_spawned(data_dir):
    game = init_game(data_dir, hero=0)
    spawned = [a for a in game.actors if a.index_in_world != -1]
    assert len(spawned) > 0
    for a in spawned:
        assert game.world_objects[a.index_in_world].obj_index == game.actors.index(a)
    # player world object is the camera target
    assert game.current_camera_target_actor != -1


def test_tick(data_dir):
    game = init_game(data_dir, hero=0)
    game.timer = 0
    game_step_tick(game)
    assert game.timer == 1


def _stage_free_world_idx(game):
    return next(i for i, o in enumerate(game.world_objects) if o.stage != game.current_floor)


def _plant_actor(game, world_idx, *, life, life_mode, stage, room=0):
    actor = game.actors[0]
    actor.index_in_world = world_idx
    actor.life = life
    actor.life_mode = life_mode
    actor.stage = stage
    actor.room = room
    game.world_objects[world_idx].obj_index = 0
    return actor


@pytest.mark.parametrize(
    "life,life_mode,stage,room,kept",
    [
        (5, 0, 0, 0, True),    # STAGE: keep (main.cpp:2010)
        (5, -1, 0, 0, False),  # default: delete (incl life_mode -1)
        (5, 1, 0, 0, True),    # ROOM match: keep
        (5, 1, 0, 1, False),   # ROOM mismatch: delete
        (5, 0, 1, 0, False),   # stage != current floor: delete
        (-1, -1, 0, 0, True),  # life == -1: M3a keep (FITD isInViewList)
        (5, 2, 0, 0, True),    # CAMERA: M3a keep (FITD isInViewList)
    ],
)
def test_phase1_delete_gates(data_dir, life, life_mode, stage, room, kept):
    game = init_game(data_dir, hero=0)
    world_idx = _stage_free_world_idx(game)
    _plant_actor(game, world_idx, life=life, life_mode=life_mode, stage=stage, room=room)
    spawn_stage_actors(game)
    assert (game.actors[0].index_in_world != -1) == kept


def test_phase2_life_mode_minus1_not_spawned(data_dir):
    game = init_game(data_dir, hero=0)
    world_idx = _stage_free_world_idx(game)
    obj = game.world_objects[world_idx]
    obj.obj_index = -1
    obj.stage = game.current_floor
    obj.life = 5
    obj.life_mode = -1
    spawn_stage_actors(game)
    assert obj.obj_index == -1


def test_spawn_does_not_touch_found_flag(data_dir):
    game = init_game(data_dir, hero=0)
    for a in game.actors:
        if a.index_in_world != -1:
            assert game.world_objects[a.index_in_world].found_flag & 0x4000 == 0
