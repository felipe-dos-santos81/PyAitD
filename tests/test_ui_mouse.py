# SPDX-License-Identifier: GPL-2.0-only
import pygame

from PyAitD.engine.effects import FoundResult
from PyAitD.app.ui import (
    CharacterLayout, CharacterPhase, CharacterSelectPresenter,
    InventoryPresenter, ModalLayout, PlayLayout, ReadingResult,
    SettingsNoticeLayout, SystemMenuLayout, SystemMenuPage,
    SystemMenuPresenter,
    effective_rects,
    hit_test_character, hit_test_found, hit_test_inventory, hit_test_reading,
    hit_test_settings_notice, hit_test_system_menu,
)
import pytest

pytestmark = pytest.mark.shell


def test_effective_rects_expand_clamp_and_partition_without_changing_art():
    visible = (pygame.Rect(0, 0, 4, 6), pygame.Rect(16, 0, 4, 6))
    hit = effective_rects(visible)
    assert visible == (pygame.Rect(0, 0, 4, 6), pygame.Rect(16, 0, 4, 6))
    assert all(rect.w >= 12 and rect.h >= 12 for rect in hit)
    assert hit[0].right <= hit[1].left
    assert hit[0].collidepoint(hit[0].right, hit[0].centery) is False


def test_effective_rects_use_explicit_bounds_and_exclusive_edges():
    visible = (pygame.Rect(1, 1, 4, 6),)
    hit = effective_rects(visible, bounds=pygame.Rect(0, 0, 20, 20))[0]
    assert hit == pygame.Rect(0, 0, 12, 12)
    assert not hit.collidepoint(hit.right, hit.centery)
    assert not hit.collidepoint(hit.centerx, hit.bottom)


def test_effective_rects_split_an_expansion_overlap_at_the_midpoint():
    visible = (pygame.Rect(10, 10, 20, 20), pygame.Rect(30, 10, 20, 20))
    hit = effective_rects(visible)
    assert hit[0].right == 30
    assert hit[1].left == 30
    assert not hit[0].colliderect(hit[1])


def test_effective_rects_partitions_geometric_neighbors_out_of_input_order():
    visible = (
        pygame.Rect(10, 10, 20, 20),
        pygame.Rect(10, 100, 4, 4),
        pygame.Rect(30, 10, 20, 20),
    )
    hit = effective_rects(visible)
    assert hit[0].right == hit[2].left == 30
    assert not hit[0].colliderect(hit[2])


def test_effective_rects_horizontal_partition_preserves_clamped_far_edge():
    bounds = pygame.Rect(0, 0, 20, 20)
    hit = effective_rects(
        (pygame.Rect(10, 5, 4, 4), pygame.Rect(16, 5, 4, 4)),
        bounds=bounds,
    )

    assert all(bounds.contains(rect) for rect in hit)
    assert hit[1].right == bounds.right


def test_effective_rects_vertical_partition_preserves_clamped_far_edge():
    bounds = pygame.Rect(0, 0, 20, 20)
    hit = effective_rects(
        (pygame.Rect(5, 10, 4, 4), pygame.Rect(5, 16, 4, 4)),
        bounds=bounds,
    )

    assert all(bounds.contains(rect) for rect in hit)
    assert hit[1].bottom == bounds.bottom


def test_layout_hit_rows_leave_visible_rectangles_unchanged():
    assert PlayLayout.INVENTORY == pygame.Rect(4, 4, 28, 20)
    assert PlayLayout.INVENTORY_HIT == pygame.Rect(2, 2, 32, 24)
    assert SystemMenuLayout.rows(SystemMenuPage.MAIN) == SystemMenuLayout.MAIN_ROWS
    assert SystemMenuLayout.hit_rows(SystemMenuPage.MAIN) != SystemMenuLayout.MAIN_ROWS
    assert ModalLayout.INVENTORY_ROWS == tuple(
        pygame.Rect(24, 30 + i * 24, 272, 22) for i in range(5)
    )
    assert SettingsNoticeLayout.DISMISS == pygame.Rect(72, 154, 176, 34)


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


def test_inventory_preview_hit_test_uses_the_activation_rows_without_mutation():
    presenter = InventoryPresenter(object_cursor=5)
    object_ids = (10, 11, 12, 13, 14, 15)

    assert hit_test_inventory(
        ModalLayout.INVENTORY_HIT_ROWS[0].center,
        presenter,
        object_ids,
        (23,),
        preview=True,
    ) == 1
    assert (presenter.object_cursor, presenter.action_cursor, presenter.choosing_action) == (5, 0, False)


def test_reading_hit_tests_respect_page_bounds():
    assert hit_test_reading(ModalLayout.READING_CLOSE.center, 0, 1) == ReadingResult(True)
    assert hit_test_reading(ModalLayout.READING_PREV.center, 0, 2) is None
    assert hit_test_reading(ModalLayout.READING_PREV.center, 1, 2) == ReadingResult(False, -1)
    assert hit_test_reading(ModalLayout.READING_NEXT.center, 1, 2) is None
    assert hit_test_reading(ModalLayout.READING_NEXT.center, 0, 2) == ReadingResult(False, 1)


def test_reading_disabled_effective_targets_remain_non_targets():
    previous, _, next_page = ModalLayout.READING_HIT_ROWS
    assert hit_test_reading(previous.center, 0, 1) is None
    assert hit_test_reading(next_page.center, 0, 1) is None


def test_settings_notice_has_one_large_exclusive_dismiss_target():
    rect = SettingsNoticeLayout.DISMISS
    hit = SettingsNoticeLayout.DISMISS_HIT
    assert rect.width >= 160 and rect.height >= 30
    assert hit_test_settings_notice(rect.topleft)
    assert hit_test_settings_notice((rect.right - 1, rect.bottom - 1))
    assert hit_test_settings_notice((rect.right, rect.bottom - 1))
    assert not hit_test_settings_notice((hit.right, hit.bottom - 1))


def test_character_portraits_match_fitd_and_have_exclusive_edges():
    assert CharacterLayout.PORTRAITS == (
        pygame.Rect(10, 10, 140, 181), pygame.Rect(170, 10, 140, 181),
    )
    for choice, rect in enumerate(CharacterLayout.PORTRAITS):
        hit = CharacterLayout.PORTRAIT_HIT_ROWS[choice]
        assert hit_test_character(rect.topleft, CharacterSelectPresenter()) == choice
        assert hit_test_character((rect.right - 1, rect.bottom - 1), CharacterSelectPresenter()) == choice
        assert hit_test_character((rect.right, rect.bottom - 1), CharacterSelectPresenter()) == choice
        assert hit_test_character((hit.right, hit.bottom - 1), CharacterSelectPresenter()) is None


def test_save_and_load_hit_rows_are_exclusive_and_inside_the_frame():
    for page in (SystemMenuPage.SAVE, SystemMenuPage.LOAD):
        rows = SystemMenuLayout.rows(page)
        assert all(rect.bottom <= 200 for rect in rows)
        hit = SystemMenuLayout.hit_rows(page)
        for a in range(len(hit)):
            for b in range(a + 1, len(hit)):
                assert not hit[a].colliderect(hit[b])


def test_story_whole_frame_confirms_and_menu_rows_are_large():
    story = CharacterSelectPresenter(phase=CharacterPhase.STORY)
    assert hit_test_character((0, 0), story) == 0
    assert hit_test_character((319, 199), story) == 0
    for page in SystemMenuPage:
        presenter = SystemMenuPresenter(page=page)
        rows = SystemMenuLayout.rows(page)
        if page is SystemMenuPage.KEY_PICK:
            # the key picker is a grid: its cells satisfy the effective-size
            # contract (>= 12x12 logical) rather than the one-column row size
            hits = SystemMenuLayout.hit_rows(page)
            assert all(rect.width >= 12 and rect.height >= 12 for rect in hits)
        elif page is SystemMenuPage.CONFIG:
            # CONFIG keeps its 13 px pitch from when it held the graphics
            # rows; effective_rects still pads every row past the 12x12
            # minimum target size
            assert all(rect.width >= 224 and rect.height >= 13 for rect in rows)
        elif page is SystemMenuPage.GRAPHICS:
            # GRAPHICS moved to an 18 px pitch to fit the Shadows row; still
            # comfortably above the 12x12 minimum target size
            assert all(rect.width >= 224 and rect.height >= 18 for rect in rows)
        else:
            assert all(rect.width >= 224 and rect.height >= 20 for rect in rows)
        for index, rect in enumerate(rows):
            assert hit_test_system_menu(rect.center, presenter) == index
