# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.game import init_game
from PyAitD.interaction import inventory_items
from PyAitD.scenario import (
    COMBAT_VENUE, enter_combat_venue, enter_mouse_combat_fixture,
)


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


def test_mouse_combat_fixture_is_deterministic_and_does_not_change_m3c_start(data_dir):
    game = init_game(data_dir)
    enter_mouse_combat_fixture(game)
    hero = game.actors[game.current_camera_target_actor]
    enemy = game.actors[game.world_objects[222].obj_index]
    assert game.floor_start == COMBAT_VENUE
    assert inventory_items(game) == (38,)
    assert (hero.room_x, hero.room_y, hero.room_z) == (-7400, -4010, -1000)
    assert (enemy.room_x, enemy.room_y, enemy.room_z) == (-7400, -4010, -1250)
    assert (enemy.life, enemy.life_mode, enemy.track_mode, enemy.speed) == (-1, -1, 0, 0)

    control = init_game(data_dir)
    enter_combat_venue(control)
    control_enemy = control.actors[control.world_objects[222].obj_index]
    assert inventory_items(control) == ()
    assert (control_enemy.track_mode, control_enemy.track_number) == (2, 1)
