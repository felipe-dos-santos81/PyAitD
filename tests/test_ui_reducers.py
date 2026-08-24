# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.config import Control, REMAPPABLE_CONTROLS, default_settings
from PyAitD.ui import (
    CharacterPhase, CharacterSelectPresenter, CharacterSelectResult, Command,
    FoundPresenter, FoundResult, InventoryPresenter, SystemMenuPage,
    SystemMenuPresenter, SystemMenuResult, capture_system_key,
    reduce_character_select, reduce_found, reduce_inventory, reduce_system_menu,
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


def test_character_selection_maps_left_to_emily_and_right_to_carnby():
    state = CharacterSelectPresenter()
    assert state == CharacterSelectPresenter(choice=0, phase=CharacterPhase.PORTRAITS)
    assert reduce_character_select(state, Command.ACCEPT) is None
    assert state.phase is CharacterPhase.STORY
    assert reduce_character_select(state, Command.OPEN_INVENTORY) == CharacterSelectResult(hero=1)
    state = CharacterSelectPresenter(choice=1)
    reduce_character_select(state, Command.ACCEPT)
    assert reduce_character_select(state, Command.ACCEPT) == CharacterSelectResult(hero=0)


def test_character_cancel_backs_out_then_quits():
    state = CharacterSelectPresenter(phase=CharacterPhase.STORY)
    assert reduce_character_select(state, Command.CANCEL) is None
    assert state.phase is CharacterPhase.PORTRAITS
    assert reduce_character_select(state, Command.CANCEL) == CharacterSelectResult(quit=True)


def test_system_main_wraps_and_opens_configuration():
    state = SystemMenuPresenter()
    reduce_system_menu(state, Command.UP, default_settings())
    assert state.cursor == 2
    reduce_system_menu(state, Command.DOWN, default_settings())
    assert state.cursor == 0
    state.cursor = 1
    assert reduce_system_menu(state, Command.OPEN_INVENTORY, default_settings()) is None
    assert (state.page, state.cursor) == (SystemMenuPage.CONFIG, 0)


def test_configuration_toggles_capture_steals_and_escape_cancels():
    state = SystemMenuPresenter(page=SystemMenuPage.CONFIG)
    outcome = reduce_system_menu(state, Command.ACCEPT, default_settings())
    assert outcome.settings.sticky_action is True
    state.cursor = 1 + REMAPPABLE_CONTROLS.index(Control.ACTION)
    assert reduce_system_menu(state, Command.ACCEPT, outcome.settings) is None
    assert state.capture == "ACTION"
    changed = capture_system_key(state, outcome.settings, "w")
    assert changed.settings.bindings["ACTION"] == ("w",)
    assert changed.settings.bindings["UP"] == ("up",)
    state.capture = "ACTION"
    assert capture_system_key(state, changed.settings, "escape") is None
    assert state.capture is None


def test_system_main_accept_rows_and_cancel():
    state = SystemMenuPresenter(cursor=0)
    assert reduce_system_menu(state, Command.ACCEPT, default_settings()) == SystemMenuResult(
        close=True, save=True)
    state = SystemMenuPresenter(cursor=2)
    assert reduce_system_menu(state, Command.ACCEPT, default_settings()) == SystemMenuResult(
        quit=True, save=True)
    state = SystemMenuPresenter(cursor=1)
    assert reduce_system_menu(state, Command.CANCEL, default_settings()) == SystemMenuResult(
        close=True, save=True)


def test_configuration_cancel_and_back_row_return_to_main_saving():
    state = SystemMenuPresenter(page=SystemMenuPage.CONFIG, cursor=2)
    assert reduce_system_menu(state, Command.CANCEL, default_settings()) == SystemMenuResult(
        save=True)
    assert (state.page, state.cursor) == (SystemMenuPage.MAIN, 0)
    state = SystemMenuPresenter(page=SystemMenuPage.CONFIG)
    state.cursor = 2 + len(REMAPPABLE_CONTROLS) - 1
    assert reduce_system_menu(state, Command.ACCEPT, default_settings()) == SystemMenuResult(
        save=True)
    assert (state.page, state.cursor) == (SystemMenuPage.MAIN, 0)


def test_configuration_cursor_wraps_across_all_rows():
    state = SystemMenuPresenter(page=SystemMenuPage.CONFIG)
    reduce_system_menu(state, Command.UP, default_settings())
    assert state.cursor == 2 + len(REMAPPABLE_CONTROLS) - 1
    reduce_system_menu(state, Command.DOWN, default_settings())
    assert state.cursor == 0
