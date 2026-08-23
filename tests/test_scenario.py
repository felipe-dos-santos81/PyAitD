# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.game import init_game
from PyAitD.scenario import COMBAT_VENUE, enter_combat_venue


def test_combat_venue_uses_the_supported_floor_start(data_dir):
    game = init_game(data_dir)
    enter_combat_venue(game)
    enemy_idx = game.world_objects[222].obj_index
    enemy = game.actors[enemy_idx]

    assert game.floor_start == COMBAT_VENUE
    assert (game.current_floor, game.current_room) == (5, 4)
    assert (game.num_camera, game.new_num_camera, game.flag_init_view) == (-1, 0, 2)
    assert sum(actor.index_in_world >= 0 for actor in game.actors) == 48
    assert enemy.index_in_world == 222
    assert (enemy.track_mode, enemy.track_number, enemy.object_type) == (2, 1, 0x0141)
