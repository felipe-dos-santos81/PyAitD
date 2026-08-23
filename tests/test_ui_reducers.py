# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.ui import (
    Command, FoundPresenter, FoundResult, InventoryPresenter,
    reduce_found, reduce_inventory,
)


def test_forced_found_choice_cannot_select_take():
    state = FoundPresenter(FoundResult.LEAVE)
    assert reduce_found(state, Command.LEFT, forced_refuse=True) is None
    assert state.choice is FoundResult.LEAVE
    assert reduce_found(state, Command.ACCEPT, forced_refuse=True) is FoundResult.LEAVE


def test_inventory_two_stage_selection_is_bounded():
    state = InventoryPresenter()
    reduce_inventory(state, Command.DOWN, object_ids=(4, 8), action_ids=(23, 25))
    assert state.object_cursor == 1
    assert reduce_inventory(state, Command.ACCEPT, object_ids=(4, 8), action_ids=(23, 25)) is None
    assert state.choosing_action is True
    reduce_inventory(state, Command.DOWN, object_ids=(4, 8), action_ids=(23, 25))
    result = reduce_inventory(state, Command.ACCEPT, object_ids=(4, 8), action_ids=(23, 25))
    assert (result.object_idx, result.action_text_id) == (8, 25)
