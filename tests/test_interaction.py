# SPDX-License-Identifier: GPL-2.0-only
from maitd.effects import ShowFound
from maitd.game import init_game
from maitd.interaction import (
    _finish_take, choose_inventory_action, inventory_actions, inventory_items,
    inventory_weight, put_object, remove_from_inventory, request_found,
)


def test_take_keeps_first_item_at_zero_and_inserts_later_items_at_one(data_dir):
    game = init_game(data_dir)
    for object_idx in (10, 11, 12):
        _finish_take(game, object_idx)
    assert inventory_items(game) == (10, 12, 11)
    assert game.inventory_count[0] == 3
    assert game.world_objects[12].found_flag & 0x8000
    assert not game.world_objects[12].found_flag & 0x4000
    assert (game.world_objects[12].room, game.world_objects[12].stage) == (-1, -1)


def test_remove_and_put_match_found_flags(data_dir):
    game = init_game(data_dir)
    _finish_take(game, 10)
    assert remove_from_inventory(game, 10) is True
    assert not game.world_objects[10].found_flag & 0x8000
    _finish_take(game, 10)
    put_object(game, 10, 1, 2, 3, 4, 5, 6, 7, 8)
    world = game.world_objects[10]
    assert (world.x, world.y, world.z, world.room, world.stage) == (1, 2, 3, 4, 5)
    assert (world.alpha, world.beta, world.gamma) == (6, 7, 8)
    assert world.found_flag & 0x4000
    assert not world.found_flag & 0x8000


def test_weight_and_first_five_found_flag_actions(data_dir):
    game = init_game(data_dir)
    game.world_objects[10].position_in_track = 7
    _finish_take(game, 10)
    game.world_objects[10].found_flag = 0x8000 | sum(1 << bit for bit in (0, 2, 4, 6, 8, 10))
    assert inventory_weight(game) == 7
    assert inventory_actions(game, 10) == (23, 25, 27, 29, 31)


def test_found_request_applies_flags_debounce_weight_and_capacity(data_dir):
    game = init_game(data_dir)
    game.timer = 300
    world = game.world_objects[10]
    world.position_in_track = game.cvars[2] + 1
    assert request_found(game, 10, 1) == ShowFound(10, True)
    world.found_flag = 0x8000
    assert request_found(game, 10, 1) is None
    assert request_found(game, 10, 0) == ShowFound(10, True)
    world.found_flag = 0
    world.track_number = game.timer - 20
    assert request_found(game, 10, 0) is None


def test_inventory_choice_sets_action_and_in_hand_before_found_life(data_dir, monkeypatch):
    game = init_game(data_dir)
    _finish_take(game, 10)
    game.world_objects[10].found_flag |= 1 << 2
    called = []
    monkeypatch.setattr("maitd.interaction.execute_found_life", lambda g, i, **kw: called.append(i) or True)
    assert choose_inventory_action(game, 10, 25) is True
    assert game.in_hand_table[0] == 10
    assert game.action == 1 << 2
    assert called == [10]
