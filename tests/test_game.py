# SPDX-License-Identifier: GPL-2.0-only
import pytest

from PyAitD.engine.game import NUM_MAX_OBJECT, Game, init_game, game_step_tick, spawn_stage_actors
from PyAitD.games.aitd1.profile import AITD1


def test_init_golden(data_dir):
    game = init_game(data_dir, AITD1, hero=0)
    assert len(game.world_objects) == 292
    assert len(game.actors) == NUM_MAX_OBJECT
    assert len(game.cvars) == 45
    assert len(game.vars) == 207
    assert game.cvars[7] == 1 and game.cvars[8] == 0
    assert game.current_world_target == 1


def test_stage_actors_spawned(data_dir):
    game = init_game(data_dir, AITD1, hero=0)
    spawned = [a for a in game.actors if a.index_in_world != -1]
    assert len(spawned) > 0
    for a in spawned:
        assert game.world_objects[a.index_in_world].obj_index == game.actors.index(a)
    # player world object is the camera target
    assert game.current_camera_target_actor != -1


def test_tick(data_dir):
    game = init_game(data_dir, AITD1, hero=0)
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
    game = init_game(data_dir, AITD1, hero=0)
    world_idx = _stage_free_world_idx(game)
    _plant_actor(game, world_idx, life=life, life_mode=life_mode, stage=stage, room=room)
    spawn_stage_actors(game)
    assert (game.actors[0].index_in_world != -1) == kept


def test_phase2_life_mode_minus1_not_spawned(data_dir):
    game = init_game(data_dir, AITD1, hero=0)
    world_idx = _stage_free_world_idx(game)
    obj = game.world_objects[world_idx]
    obj.obj_index = -1
    obj.stage = game.current_floor
    obj.life = 5
    obj.life_mode = -1
    spawn_stage_actors(game)
    assert obj.obj_index == -1


def test_spawn_does_not_touch_found_flag(data_dir):
    game = init_game(data_dir, AITD1, hero=0)
    for a in game.actors:
        if a.index_in_world != -1:
            assert game.world_objects[a.index_in_world].found_flag & 0x4000 == 0


def test_activate_world_object_initializes_one_released_item(data_dir):
    from PyAitD.engine.game import activate_world_object
    from PyAitD.engine.interaction import _finish_take

    game = init_game(data_dir, AITD1)
    _finish_take(game, 38)
    world = game.world_objects[38]
    world.stage = game.current_floor
    world.room = game.current_room
    assert world.obj_index == -1

    actor_idx = activate_world_object(game, 38)

    assert actor_idx != -1
    assert world.obj_index == actor_idx
    assert game.actors[actor_idx].index_in_world == 38
    assert activate_world_object(game, 38) == actor_idx


@pytest.mark.parametrize("hero", (0, 1))
def test_both_heroes_share_fitd_initial_state_except_cvar_and_archives(data_dir, hero):
    game = init_game(data_dir, AITD1, hero=hero)
    actor = game.actors[game.current_camera_target_actor]
    assert game.cvars[8] == hero
    assert (
        game.current_floor, game.current_room, game.current_camera_target_actor,
        actor.index_in_world, actor.body_num, actor.anim, actor.life, actor.life_mode,
        actor.room_x, actor.room_y, actor.room_z,
    ) == (0, 0, 1, 1, 12, 4, 549, 0, 3231, 0, -1548)
    assert game.inventory_count == [0, 0]
    assert game.in_hand_table == [-1, -1]


def test_game_carries_its_profile_and_sets_choose_perso_by_name(data_dir):
    from PyAitD.engine.game import Game
    from PyAitD.games.aitd1.profile import AITD1
    game = Game(data_dir, AITD1, hero=1)
    assert game.profile is AITD1
    assert game.cvars[AITD1.cvar_index("CHOOSE_PERSO")] == 1
