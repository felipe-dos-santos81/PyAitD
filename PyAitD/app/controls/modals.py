# SPDX-License-Identifier: GPL-2.0-only
"""Modal input reducers and hit tests: what a key or a click does to a presenter. Drawing stays in app.ui."""
from dataclasses import replace

from PyAitD.app.config import REMAPPABLE_CONTROLS, replace_binding
from PyAitD.app.controls.actions import Action
from PyAitD.app.ui import (
    GRAPHICS_CYCLES, LOAD_ROW_LABELS, MAIN_ROW_LABELS, PICKABLE_KEYS, REALISM_CYCLES,
    SAVE_ROW_LABELS, CharacterLayout, CharacterPhase, CharacterSelectResult,
    InventoryResult, ModalLayout, ReadingResult, SettingsNoticeLayout,
    SystemMenuLayout, SystemMenuPage, SystemMenuResult, config_row_count,
    graphics_row_count, realism_row_count, visible_start,
)
from PyAitD.engine.script.effects import FoundResult


def reduce_found(state, command, *, forced_refuse):
    if forced_refuse:
        state.choice = FoundResult.LEAVE
    elif command is Action.LEFT:
        state.choice = FoundResult.LEAVE
    elif command is Action.RIGHT:
        state.choice = FoundResult.TAKE
    if command is Action.CANCEL:
        return FoundResult.LEAVE
    if command is Action.ACTION:
        return state.choice
    return None


def reduce_inventory(state, command, *, object_ids, action_ids):
    if command is Action.CANCEL:
        if state.choosing_action:
            state.choosing_action = False
            state.action_cursor = 0
            return None
        return InventoryResult(cancelled=True)
    if not object_ids:
        return InventoryResult(cancelled=True)
    if command in (Action.UP, Action.DOWN):
        cursor = state.action_cursor if state.choosing_action else state.object_cursor
        if command is Action.UP:
            cursor = max(0, cursor - 1)
        else:
            cursor = min(len(action_ids if state.choosing_action else object_ids) - 1, cursor + 1)
        if state.choosing_action:
            state.action_cursor = cursor
        else:
            state.object_cursor = cursor
    elif command is Action.ACTION and not state.choosing_action:
        state.choosing_action = True
        state.action_cursor = 0
    elif command is Action.ACTION and action_ids:
        return InventoryResult(object_ids[state.object_cursor], action_ids[state.action_cursor])
    return None


def turn_page(state, delta, page_count):
    state.page = min(page_count - 1, max(0, state.page + delta))


def reduce_reading(state, command, *, page_count):
    if command is Action.CANCEL:
        return ReadingResult(True)
    if command in (Action.LEFT, Action.UP):
        turn_page(state, -1, page_count)
    elif command in (Action.RIGHT, Action.DOWN, Action.ACTION):
        if state.page + 1 >= page_count:
            return ReadingResult(True)
        turn_page(state, 1, page_count)
    return None


def reduce_character_select(state, command):
    command = Action.ACTION if command is Action.INVENTORY_CONFIRM else command
    if command is Action.CANCEL:
        if state.phase is CharacterPhase.STORY:
            state.phase = CharacterPhase.PORTRAITS
            return None
        return CharacterSelectResult(quit=True)
    if state.phase is CharacterPhase.PORTRAITS:
        if command in (Action.LEFT, Action.UP):
            state.choice = 0
        elif command in (Action.RIGHT, Action.DOWN):
            state.choice = 1
        elif command is Action.ACTION:
            state.phase = CharacterPhase.STORY
        return None
    if command is Action.ACTION:
        return CharacterSelectResult(hero=1 if state.choice == 0 else 0)
    return None


def _leave_graphics(state):
    state.page = SystemMenuPage.CONFIG
    state.cursor = config_row_count() - 3   # back on the Graphics... row
    state.hover = None


def _leave_realism(state):
    state.page = SystemMenuPage.CONFIG
    state.cursor = config_row_count() - 2   # back on the Realism... row
    state.hover = None


def reduce_system_menu(state, command, settings, available_slots=frozenset()):
    if state.capture is not None:
        return None
    command = Action.ACTION if command is Action.INVENTORY_CONFIRM else command
    if state.page is SystemMenuPage.MAIN:
        row_count = len(MAIN_ROW_LABELS)
    elif state.page is SystemMenuPage.SAVE:
        row_count = len(SAVE_ROW_LABELS)
    elif state.page is SystemMenuPage.LOAD:
        row_count = len(LOAD_ROW_LABELS)
    elif state.page is SystemMenuPage.GRAPHICS:
        row_count = graphics_row_count()
    elif state.page is SystemMenuPage.REALISM:
        row_count = realism_row_count()
    else:
        row_count = config_row_count()
    if command is Action.UP:
        state.cursor = (state.cursor - 1) % row_count
    elif command is Action.DOWN:
        state.cursor = (state.cursor + 1) % row_count
    elif command is Action.CANCEL:
        if state.page is SystemMenuPage.GRAPHICS:
            _leave_graphics(state)
            return SystemMenuResult(save=True)
        if state.page is SystemMenuPage.REALISM:
            _leave_realism(state)
            return SystemMenuResult(save=True)
        if state.page is SystemMenuPage.CONFIG:
            state.page = SystemMenuPage.MAIN
            state.cursor = 0
            return SystemMenuResult(save=True)
        if state.page in (SystemMenuPage.SAVE, SystemMenuPage.LOAD):
            state.page = SystemMenuPage.MAIN
            state.cursor = 0
            state.hover = None
            return None
        return SystemMenuResult(close=True, save=True)
    elif command is Action.ACTION and state.page is SystemMenuPage.MAIN:
        if state.cursor == 0:
            return SystemMenuResult(close=True, save=True)
        if state.cursor == 1:
            state.page = SystemMenuPage.SAVE
            state.cursor = 0
            state.hover = None
        elif state.cursor == 2:
            state.page = SystemMenuPage.LOAD
            state.cursor = 0
            state.hover = None
        elif state.cursor == 3:
            return SystemMenuResult(close=True, quick_save=True)
        elif state.cursor == 4:
            state.page = SystemMenuPage.CONFIG
            state.cursor = 0
        else:
            return SystemMenuResult(quit=True, save=True)
    elif command is Action.ACTION and state.page is SystemMenuPage.SAVE:
        if state.cursor == 0:
            return SystemMenuResult(save_slot="manual")
        state.page = SystemMenuPage.MAIN
        state.cursor = 0
        state.hover = None
    elif command is Action.ACTION and state.page is SystemMenuPage.LOAD:
        if state.cursor == 2:
            state.page = SystemMenuPage.MAIN
            state.cursor = 0
            state.hover = None
        elif state.cursor == 0 and "manual" in available_slots:
            return SystemMenuResult(load_slot="manual")
        elif state.cursor == 1 and "quick" in available_slots:
            return SystemMenuResult(load_slot="quick")
        # a row whose slot file does not exist is a forgiving no-op: it can
        # never fall through to Back
    elif command is Action.ACTION and state.page is SystemMenuPage.GRAPHICS:
        if state.cursor == row_count - 1:
            _leave_graphics(state)
            return SystemMenuResult(save=True)
        cycle = GRAPHICS_CYCLES[state.cursor]
        return SystemMenuResult(settings=replace(settings, render=cycle(settings.render)))
    elif command is Action.ACTION and state.page is SystemMenuPage.REALISM:
        if state.cursor == row_count - 1:
            _leave_realism(state)
            return SystemMenuResult(save=True)
        cycle = REALISM_CYCLES[state.cursor]
        return SystemMenuResult(settings=replace(settings, render=cycle(settings.render)))
    elif (command is Action.ACTION and state.page is SystemMenuPage.CONFIG
          and state.cursor == row_count - 1):
        state.page = SystemMenuPage.MAIN
        state.cursor = 0
        return SystemMenuResult(save=True)
    elif command is Action.ACTION and state.cursor == row_count - 3:
        # the Graphics... row
        state.page = SystemMenuPage.GRAPHICS
        state.cursor = 0
        state.hover = None
    elif command is Action.ACTION and state.cursor == row_count - 2:
        # the Realism... row
        state.page = SystemMenuPage.REALISM
        state.cursor = 0
        state.hover = None
    elif command is Action.ACTION and state.cursor == 0:
        return SystemMenuResult(
            settings=replace(settings, sticky_action=not settings.sticky_action),
        )
    elif command is Action.ACTION:
        state.capture = REMAPPABLE_CONTROLS[state.cursor - 1].name
        state.page = SystemMenuPage.KEY_PICK
        state.hover = None
    return None


def capture_system_key(state, settings, key_name):
    """Finish a remap with a physical or picked key; ``escape`` cancels.

    Leaves the key picker either way; the configuration row that was being
    bound stays selected.
    """
    if state.capture is None:
        return None
    control = state.capture
    state.capture = None
    state.page = SystemMenuPage.CONFIG
    state.hover = None
    if key_name == "escape":
        return None
    return SystemMenuResult(settings=replace_binding(settings, Action[control], key_name))


def pick_system_key(state, settings, index):
    """Mouse route for the key picker: cell ``index`` binds, the last cell cancels."""
    name = "escape" if index >= len(PICKABLE_KEYS) else PICKABLE_KEYS[index]
    return capture_system_key(state, settings, name)


def hit_test_found(pos):
    if ModalLayout.FOUND_HIT_ROWS[0].collidepoint(pos):
        return FoundResult.LEAVE
    if ModalLayout.FOUND_HIT_ROWS[1].collidepoint(pos):
        return FoundResult.TAKE
    return None


def hit_test_character(pos, presenter):
    if presenter.phase is CharacterPhase.STORY:
        return 0 if CharacterLayout.STORY.collidepoint(pos) else None
    for choice, rect in enumerate(CharacterLayout.PORTRAIT_HIT_ROWS):
        if rect.collidepoint(pos):
            return choice
    return None


def hit_test_system_menu(pos, presenter):
    for index, rect in enumerate(SystemMenuLayout.hit_rows(presenter.page)):
        if rect.collidepoint(pos):
            return index
    return None


def hit_test_settings_notice(pos):
    return SettingsNoticeLayout.DISMISS_HIT.collidepoint(pos)


def hit_test_inventory(pos, presenter, object_ids, action_ids, *, preview=False):
    rows = action_ids if presenter.choosing_action else object_ids
    cursor = presenter.action_cursor if presenter.choosing_action else presenter.object_cursor
    start = visible_start(cursor, len(rows))
    for visible, rect in enumerate(ModalLayout.INVENTORY_HIT_ROWS):
        index = start + visible
        if index < len(rows) and rect.collidepoint(pos):
            if preview:
                return index
            if presenter.choosing_action:
                presenter.action_cursor = index
                return InventoryResult(object_ids[presenter.object_cursor], action_ids[index])
            presenter.object_cursor = index
            presenter.choosing_action = True
            presenter.action_cursor = 0
            return None
    return None


def hit_test_reading(pos, page, page_count):
    if ModalLayout.READING_HIT_ROWS[1].collidepoint(pos):
        return ReadingResult(True)
    if page > 0 and ModalLayout.READING_HIT_ROWS[0].collidepoint(pos):
        return ReadingResult(False, -1)
    if page + 1 < page_count and ModalLayout.READING_HIT_ROWS[2].collidepoint(pos):
        return ReadingResult(False, 1)
    return None
