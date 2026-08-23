# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.ui import (
    FoundResult, InventoryPresenter, ModalLayout, ReadingResult,
    hit_test_found, hit_test_inventory, hit_test_reading,
)


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
