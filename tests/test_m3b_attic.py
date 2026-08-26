# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.engine.playworld import play_tick
from PyAitD.engine.effects import OpenInventory
from PyAitD.engine.floor import Floor
from PyAitD.engine.game import init_game
from PyAitD.engine.interaction import (
    apply_found_result, apply_inventory_result, inventory_actions,
    inventory_items, request_found,
)
from PyAitD.ui import FoundResult, InputBuffer, InventoryResult


def test_attic_lamp_find_take_use_and_drop_checkpoint(data_dir):
    game = init_game(data_dir)
    game.timer = 300
    lamp_idx = 13
    lamp = game.world_objects[lamp_idx]
    assert (lamp.stage, lamp.room, lamp.found_name, lamp.found_life) == (0, 0, 201, 9)
    assert (lamp.found_flag, lamp.found_body, lamp.position_in_track) == (1545, 10, 30)
    assert lamp.track_number == -1

    found = request_found(game, lamp_idx, parameter=0)
    assert found is not None
    game.open_modal(found)
    apply_found_result(game, FoundResult.TAKE)
    assert lamp_idx in inventory_items(game)
    assert lamp.found_flag & 0x8000
    assert (lamp.stage, lamp.room, lamp.obj_index) == (-1, -1, -1)

    game.open_modal(OpenInventory())
    actions = inventory_actions(game, lamp_idx)
    assert 23 in actions
    apply_inventory_result(game, InventoryResult(lamp_idx, 23))
    assert game.in_hand_table[0] == lamp_idx
    assert game.action == 1

    game.open_modal(OpenInventory())
    assert 33 in inventory_actions(game, lamp_idx)
    apply_inventory_result(game, InventoryResult(lamp_idx, 33))
    # FITD Drop/Put is two-stage. Lamp LIFE 9 case 0x400 (LISTLIFE 9, byte 108)
    # only re-points world object 1's actor (anim 10, LIFE 11) and stores the
    # subject in vars[9]; it does not touch the inventory. The removal happens
    # once that anim finishes (flag_end_anim gate, LISTLIFE 11, byte 10) via
    # LM_DROP (life.cpp:1510) -> drop(vars[9], 1) -> PutAtObjet (main.cpp:3948)
    # -> DeleteInventoryObjet (main.cpp:2356) + foundFlag |= 0x4000.
    assert game.vars[9] == lamp_idx
    floor = Floor(data_dir, 0)
    for _ in range(200):
        if lamp_idx not in inventory_items(game):
            break
        # A False return is a legitimate mid-tick suspend (the attic boot
        # cutscene actor 2 takes object 2 on the first tick); keep ticking.
        play_tick(game, floor, InputBuffer())
    assert lamp_idx not in inventory_items(game)
    assert lamp.found_flag & 0x4000
