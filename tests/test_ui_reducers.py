# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.app.config import Control, REMAPPABLE_CONTROLS, default_settings
from PyAitD.engine.script.effects import FoundResult
from PyAitD.app.ui import (
    CharacterPhase, CharacterSelectPresenter, CharacterSelectResult, Command,
    FoundPresenter, InventoryPresenter, SystemMenuPage,
    SystemMenuPresenter, SystemMenuResult, capture_system_key, config_row_count,
    reduce_character_select, reduce_found, reduce_inventory, reduce_system_menu,
)
import pytest

pytestmark = pytest.mark.shell


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
    assert state.cursor == 5
    reduce_system_menu(state, Command.DOWN, default_settings())
    assert state.cursor == 0
    state.cursor = 4
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
    state = SystemMenuPresenter(cursor=5)
    assert reduce_system_menu(state, Command.ACCEPT, default_settings()) == SystemMenuResult(
        quit=True, save=True)
    state = SystemMenuPresenter(cursor=1)
    assert reduce_system_menu(state, Command.CANCEL, default_settings()) == SystemMenuResult(
        close=True, save=True)


def test_main_save_load_and_quick_save_rows():
    state = SystemMenuPresenter(cursor=1)
    assert reduce_system_menu(state, Command.ACCEPT, default_settings()) is None
    assert (state.page, state.cursor) == (SystemMenuPage.SAVE, 0)
    state = SystemMenuPresenter(cursor=2)
    assert reduce_system_menu(state, Command.ACCEPT, default_settings()) is None
    assert (state.page, state.cursor) == (SystemMenuPage.LOAD, 0)
    state = SystemMenuPresenter(cursor=3)
    assert reduce_system_menu(state, Command.ACCEPT, default_settings()) == SystemMenuResult(
        close=True, quick_save=True)


def test_save_page_manual_slot_and_back():
    state = SystemMenuPresenter(page=SystemMenuPage.SAVE)
    assert reduce_system_menu(state, Command.ACCEPT, default_settings()) == SystemMenuResult(
        save_slot="manual")
    assert state.page is SystemMenuPage.SAVE, "the menu stays open after a manual save"
    state.cursor = 1
    assert reduce_system_menu(state, Command.ACCEPT, default_settings()) is None
    assert (state.page, state.cursor) == (SystemMenuPage.MAIN, 0)
    state = SystemMenuPresenter(page=SystemMenuPage.SAVE)
    reduce_system_menu(state, Command.UP, default_settings())
    assert state.cursor == 1


def test_load_page_disabled_slots_are_inert_no_ops():
    for cursor in (0, 1):
        state = SystemMenuPresenter(page=SystemMenuPage.LOAD, cursor=cursor)
        assert reduce_system_menu(state, Command.ACCEPT, default_settings()) is None
        assert (state.page, state.cursor) == (SystemMenuPage.LOAD, cursor)


def test_load_page_enabled_slots_load_and_back():
    slots = frozenset({"manual", "quick"})
    state = SystemMenuPresenter(page=SystemMenuPage.LOAD, cursor=0)
    assert reduce_system_menu(
        state, Command.ACCEPT, default_settings(), slots) == SystemMenuResult(load_slot="manual")
    state = SystemMenuPresenter(page=SystemMenuPage.LOAD, cursor=1)
    assert reduce_system_menu(
        state, Command.ACCEPT, default_settings(), slots) == SystemMenuResult(load_slot="quick")
    state = SystemMenuPresenter(page=SystemMenuPage.LOAD, cursor=2)
    assert reduce_system_menu(state, Command.ACCEPT, default_settings(), slots) is None
    assert (state.page, state.cursor) == (SystemMenuPage.MAIN, 0)
    state = SystemMenuPresenter(page=SystemMenuPage.LOAD)
    reduce_system_menu(state, Command.UP, default_settings())
    assert state.cursor == 2


def test_save_and_load_cancel_returns_to_main():
    for page in (SystemMenuPage.SAVE, SystemMenuPage.LOAD):
        state = SystemMenuPresenter(page=page, cursor=1, hover=1)
        assert reduce_system_menu(state, Command.CANCEL, default_settings()) is None
        assert (state.page, state.cursor, state.hover) == (SystemMenuPage.MAIN, 0, None)


def test_configuration_cancel_and_back_row_return_to_main_saving():
    state = SystemMenuPresenter(page=SystemMenuPage.CONFIG, cursor=2)
    assert reduce_system_menu(state, Command.CANCEL, default_settings()) == SystemMenuResult(
        save=True)
    assert (state.page, state.cursor) == (SystemMenuPage.MAIN, 0)
    state = SystemMenuPresenter(page=SystemMenuPage.CONFIG)
    state.cursor = config_row_count() - 1
    assert reduce_system_menu(state, Command.ACCEPT, default_settings()) == SystemMenuResult(
        save=True)
    assert (state.page, state.cursor) == (SystemMenuPage.MAIN, 0)


def test_configuration_cursor_wraps_across_all_rows():
    state = SystemMenuPresenter(page=SystemMenuPage.CONFIG)
    reduce_system_menu(state, Command.UP, default_settings())
    assert state.cursor == config_row_count() - 1
    reduce_system_menu(state, Command.DOWN, default_settings())
    assert state.cursor == 0


def test_configuration_graphics_row_opens_the_graphics_page():
    from PyAitD.app.ui import config_row_count
    assert config_row_count() == 4 + len(REMAPPABLE_CONTROLS)
    state = SystemMenuPresenter(page=SystemMenuPage.CONFIG, cursor=config_row_count() - 3, hover=3)
    assert reduce_system_menu(state, Command.ACCEPT, default_settings()) is None
    assert (state.page, state.cursor, state.hover) == (SystemMenuPage.GRAPHICS, 0, None)


def test_graphics_and_realism_rows_cycle_render_options():
    from PyAitD.app.ui import (
        GRAPHICS_CYCLES, GRAPHICS_ROWS, REALISM_CYCLES, REALISM_ROWS,
        graphics_row_count, realism_row_count,
    )
    assert GRAPHICS_ROWS == 5 and len(GRAPHICS_CYCLES) == GRAPHICS_ROWS
    assert REALISM_ROWS == 5 and len(REALISM_CYCLES) == REALISM_ROWS
    assert graphics_row_count() == GRAPHICS_ROWS + 1
    assert realism_row_count() == REALISM_ROWS + 1
    from PyAitD.render.render_options import RenderOptions
    settings = default_settings()
    state = SystemMenuPresenter(page=SystemMenuPage.GRAPHICS, cursor=0)
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(scale=6)
    state.cursor = 1
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(shading="flat")
    state.cursor = 2
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(background_filter="xbr")
    state.cursor = 3
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(msaa=8)
    state.cursor = 4
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(smoothing=3)
    assert state.page is SystemMenuPage.GRAPHICS  # a cycle never leaves the page

    state = SystemMenuPresenter(page=SystemMenuPage.REALISM, cursor=0)
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(lighting="fixed")
    state.cursor = 1
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(shadows="hard")
    state.cursor = 2
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(realism="classic")
    state.cursor = 3
    # Minor 12: REALISM_CYCLES[3] (cycle_integration) was otherwise pinned
    # only by identity (test_smoothing_integration_and_motion_cycle_slots_
    # are_pinned) and by label rendering, never by an actual
    # reduce_system_menu(ACCEPT) asserting the resulting settings.render
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(integration=3)
    assert state.page is SystemMenuPage.REALISM  # a cycle never leaves the page


def test_smoothing_integration_and_motion_cycle_slots_are_pinned():
    from PyAitD.app.ui import GRAPHICS_CYCLES, REALISM_CYCLES
    from PyAitD.render.render_options import cycle_integration, cycle_motion, cycle_smoothing
    assert GRAPHICS_CYCLES[4] is cycle_smoothing
    assert REALISM_CYCLES[3] is cycle_integration
    assert REALISM_CYCLES[4] is cycle_motion


def test_graphics_back_and_cancel_return_to_the_graphics_row_saving():
    from PyAitD.app.ui import config_row_count, graphics_row_count
    state = SystemMenuPresenter(page=SystemMenuPage.GRAPHICS, cursor=graphics_row_count() - 1, hover=2)
    assert reduce_system_menu(state, Command.ACCEPT, default_settings()) == SystemMenuResult(save=True)
    assert (state.page, state.cursor, state.hover) == (SystemMenuPage.CONFIG, config_row_count() - 3, None)
    state = SystemMenuPresenter(page=SystemMenuPage.GRAPHICS, cursor=3)
    assert reduce_system_menu(state, Command.CANCEL, default_settings()) == SystemMenuResult(save=True)
    assert (state.page, state.cursor) == (SystemMenuPage.CONFIG, config_row_count() - 3)


def test_config_navigates_to_both_pages_and_back():
    state = SystemMenuPresenter(page=SystemMenuPage.CONFIG,
                                cursor=config_row_count() - 3)
    settings = default_settings()
    assert reduce_system_menu(state, Command.ACCEPT, settings) is None
    assert state.page is SystemMenuPage.GRAPHICS and state.cursor == 0
    result = reduce_system_menu(state, Command.CANCEL, settings)
    assert result.save and state.page is SystemMenuPage.CONFIG
    assert state.cursor == config_row_count() - 3   # back on Graphics...
    state.cursor = config_row_count() - 2
    assert reduce_system_menu(state, Command.ACCEPT, settings) is None
    assert state.page is SystemMenuPage.REALISM and state.cursor == 0
    result = reduce_system_menu(state, Command.CANCEL, settings)
    assert result.save and state.page is SystemMenuPage.CONFIG
    assert state.cursor == config_row_count() - 2   # back on Realism...


def test_realism_page_cycles_motion_and_backs_out():
    from PyAitD.app.ui import realism_row_count
    settings = default_settings()
    state = SystemMenuPresenter(page=SystemMenuPage.REALISM, cursor=4)
    result = reduce_system_menu(state, Command.ACCEPT, settings)
    assert result.settings.render.motion == "tick"
    state.cursor = realism_row_count() - 1
    result = reduce_system_menu(state, Command.ACCEPT, settings)
    assert result.save and state.page is SystemMenuPage.CONFIG


def test_graphics_cursor_wraps_across_all_rows():
    from PyAitD.app.ui import graphics_row_count
    state = SystemMenuPresenter(page=SystemMenuPage.GRAPHICS)
    reduce_system_menu(state, Command.UP, default_settings())
    assert state.cursor == graphics_row_count() - 1
    reduce_system_menu(state, Command.DOWN, default_settings())
    assert state.cursor == 0


def test_choosing_a_control_row_opens_the_key_picker():
    state = SystemMenuPresenter(page=SystemMenuPage.CONFIG)
    state.cursor = 1 + REMAPPABLE_CONTROLS.index(Control.ACTION)
    assert reduce_system_menu(state, Command.ACCEPT, default_settings()) is None
    assert state.capture == "ACTION"
    assert state.page is SystemMenuPage.KEY_PICK


def test_clicking_a_picker_cell_binds_and_returns_to_configuration():
    from PyAitD.app.ui import PICKABLE_KEYS, pick_system_key
    state = SystemMenuPresenter(page=SystemMenuPage.KEY_PICK, capture="ACTION", cursor=5)
    result = pick_system_key(state, default_settings(), PICKABLE_KEYS.index("q"))
    assert result.settings.bindings["ACTION"] == ("q",)
    assert state.capture is None
    assert state.page is SystemMenuPage.CONFIG
    assert state.cursor == 5, "the configuration row that was being bound stays selected"


def test_picker_cancel_cell_keeps_settings_and_returns_to_configuration():
    from PyAitD.app.ui import PICKABLE_KEYS, pick_system_key
    state = SystemMenuPresenter(page=SystemMenuPage.KEY_PICK, capture="ACTION", cursor=5)
    assert pick_system_key(state, default_settings(), len(PICKABLE_KEYS)) is None
    assert state.capture is None
    assert state.page is SystemMenuPage.CONFIG
    assert state.cursor == 5


def test_physical_capture_also_leaves_the_key_picker():
    state = SystemMenuPresenter(page=SystemMenuPage.KEY_PICK, capture="ACTION", cursor=5)
    assert capture_system_key(state, default_settings(), "escape") is None
    assert state.page is SystemMenuPage.CONFIG
    state.capture = "ACTION"
    state.page = SystemMenuPage.KEY_PICK
    assert capture_system_key(state, default_settings(), "w").settings.bindings["ACTION"] == ("w",)
    assert state.page is SystemMenuPage.CONFIG


def test_picker_ignores_keyboard_menu_commands_while_capturing():
    state = SystemMenuPresenter(page=SystemMenuPage.KEY_PICK, capture="ACTION", cursor=5)
    assert reduce_system_menu(state, Command.DOWN, default_settings()) is None
    assert (state.page, state.cursor, state.capture) == (SystemMenuPage.KEY_PICK, 5, "ACTION")


def test_pickable_keys_round_trip_through_pygame_and_fit_the_frame():
    import pygame
    from PyAitD.app import ui
    from PyAitD.app.ui import PICKABLE_KEYS, SystemMenuLayout, canonical_key_name
    pygame.init()
    try:
        assert len(set(PICKABLE_KEYS)) == len(PICKABLE_KEYS)
        for name in PICKABLE_KEYS:
            assert canonical_key_name(pygame.key.key_code(name)) == name
        assert "escape" not in PICKABLE_KEYS
        rows = SystemMenuLayout.rows(SystemMenuPage.KEY_PICK)
        assert len(rows) == len(PICKABLE_KEYS) + 1, "one cell per key plus Cancel"
        frame = pygame.Rect(0, 0, 320, 200)
        assert all(frame.contains(rect) for rect in rows)
        hit_rows = SystemMenuLayout.hit_rows(SystemMenuPage.KEY_PICK)
        for index, rect in enumerate(hit_rows):
            assert rect.width >= 12 and rect.height >= 12
            assert all(
                not rect.colliderect(other) for other in hit_rows[index + 1:]
            ), "effective picker cells never overlap"
    finally:
        # pygame.quit() invalidates ui's module-level font cache -- see the
        # same hazard/fix in tests/test_shell_journeys.py's _pygame_runtime.
        pygame.quit()
        ui._font.cache_clear()
