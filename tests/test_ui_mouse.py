# SPDX-License-Identifier: GPL-2.0-only
import pygame

from PyAitD.ui import (
    CharacterLayout, CharacterPhase, CharacterSelectPresenter,
    FoundResult, InventoryPresenter, ModalLayout, PlayLayout, ReadingResult,
    SettingsNoticeLayout, SystemMenuLayout, SystemMenuPage,
    SystemMenuPresenter,
    hit_test_character, hit_test_found, hit_test_inventory, hit_test_reading,
    hit_test_settings_notice, hit_test_system_menu,
)


def test_inventory_hud_target_has_pinned_exclusive_edges():
    rect = PlayLayout.INVENTORY
    assert rect == pygame.Rect(4, 4, 28, 20)
    assert rect.collidepoint(rect.left, rect.top)
    assert rect.collidepoint(rect.right - 1, rect.bottom - 1)
    assert not rect.collidepoint(rect.right, rect.bottom - 1)
    assert not rect.collidepoint(rect.right - 1, rect.bottom)


def test_found_buttons_are_large_and_single_clickable():
    assert ModalLayout.FOUND_LEAVE.width >= 96
    assert ModalLayout.FOUND_LEAVE.height >= 28
    assert ModalLayout.FOUND_TAKE.width >= 96
    assert hit_test_found(ModalLayout.FOUND_LEAVE.center) is FoundResult.LEAVE
    assert hit_test_found(ModalLayout.FOUND_TAKE.center) is FoundResult.TAKE


def test_inventory_mouse_rows_follow_five_row_scroll_window():
    presenter = InventoryPresenter(object_cursor=5)
    object_ids = (10, 11, 12, 13, 14, 15)
    assert hit_test_inventory(
        ModalLayout.INVENTORY_ROWS[0].center,
        presenter,
        object_ids,
        (23,),
    ) is None
    assert presenter.object_cursor == 1
    assert presenter.choosing_action is True


def test_reading_hit_tests_respect_page_bounds():
    assert hit_test_reading(ModalLayout.READING_CLOSE.center, 0, 1) == ReadingResult(True)
    assert hit_test_reading(ModalLayout.READING_PREV.center, 0, 2) is None
    assert hit_test_reading(ModalLayout.READING_PREV.center, 1, 2) == ReadingResult(False, -1)
    assert hit_test_reading(ModalLayout.READING_NEXT.center, 1, 2) is None
    assert hit_test_reading(ModalLayout.READING_NEXT.center, 0, 2) == ReadingResult(False, 1)


def test_settings_notice_has_one_large_exclusive_dismiss_target():
    rect = SettingsNoticeLayout.DISMISS
    assert rect.width >= 160 and rect.height >= 30
    assert hit_test_settings_notice(rect.topleft)
    assert hit_test_settings_notice((rect.right - 1, rect.bottom - 1))
    assert not hit_test_settings_notice((rect.right, rect.bottom - 1))


def test_character_portraits_match_fitd_and_have_exclusive_edges():
    assert CharacterLayout.PORTRAITS == (
        pygame.Rect(10, 10, 140, 181), pygame.Rect(170, 10, 140, 181),
    )
    for choice, rect in enumerate(CharacterLayout.PORTRAITS):
        assert hit_test_character(rect.topleft, CharacterSelectPresenter()) == choice
        assert hit_test_character((rect.right - 1, rect.bottom - 1), CharacterSelectPresenter()) == choice
        assert hit_test_character((rect.right, rect.bottom - 1), CharacterSelectPresenter()) is None


def test_story_whole_frame_confirms_and_menu_rows_are_large():
    story = CharacterSelectPresenter(phase=CharacterPhase.STORY)
    assert hit_test_character((0, 0), story) == 0
    assert hit_test_character((319, 199), story) == 0
    for page in SystemMenuPage:
        presenter = SystemMenuPresenter(page=page)
        rows = SystemMenuLayout.rows(page)
        assert all(rect.width >= 224 and rect.height >= 20 for rect in rows)
        for index, rect in enumerate(rows):
            assert hit_test_system_menu(rect.center, presenter) == index
