# SPDX-License-Identifier: GPL-2.0-only
from maitd.game import NUM_MAX_OBJECT, Game, init_game, game_step_tick


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
