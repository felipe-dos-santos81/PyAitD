# SPDX-License-Identifier: GPL-2.0-only
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pytest

from PyAitD.app.startup import (
    StartupLayout, StartupMenuPresenter, StartupMenuResult, StartupRow, TITLE_TIMEOUT_MS,
    TitlePhase, TitlePresenter, TitleResult, advance_title, hit_test_startup, hit_test_title,
    reduce_startup_menu, reduce_title,
)
from PyAitD.app.ui import Command


def test_title_advances_by_timeout_then_only_by_input():
    p = TitlePresenter()
    assert advance_title(p, TITLE_TIMEOUT_MS - 1) is None and p.phase is TitlePhase.TITLE
    assert advance_title(p, TITLE_TIMEOUT_MS) is None and p.phase is TitlePhase.CREDITS
    assert advance_title(p, 10 ** 6) is None and p.phase is TitlePhase.CREDITS


def test_title_any_command_pages_then_finishes():
    p = TitlePresenter()
    assert reduce_title(p, Command.LEFT) is None and p.phase is TitlePhase.CREDITS
    assert reduce_title(p, Command.CANCEL) == TitleResult(True)


def test_menu_cursor_wraps_and_skips_the_disabled_row():
    p = StartupMenuPresenter()
    reduce_startup_menu(p, Command.DOWN, continue_enabled=False)
    assert p.cursor == StartupRow.QUIT.value
    reduce_startup_menu(p, Command.DOWN, continue_enabled=False)
    assert p.cursor == StartupRow.NEW_GAME.value
    reduce_startup_menu(p, Command.UP, continue_enabled=False)
    assert p.cursor == StartupRow.QUIT.value
    reduce_startup_menu(p, Command.UP, continue_enabled=True)
    assert p.cursor == StartupRow.CONTINUE.value


@pytest.mark.parametrize("command", (Command.ACCEPT, Command.OPEN_INVENTORY))
def test_menu_accept_selects_the_cursor_row(command):
    p = StartupMenuPresenter(cursor=StartupRow.QUIT.value)
    assert reduce_startup_menu(p, command, continue_enabled=False) == StartupMenuResult(quit=True)
    p.cursor = StartupRow.NEW_GAME.value
    assert reduce_startup_menu(p, command, continue_enabled=False) == StartupMenuResult(new_game=True)
    p.cursor = StartupRow.CONTINUE.value
    assert reduce_startup_menu(p, command, continue_enabled=False) is None
    assert reduce_startup_menu(p, command, continue_enabled=True) == StartupMenuResult(continue_game=True)


def test_menu_cancel_is_a_no_op():
    p = StartupMenuPresenter(cursor=2)
    assert reduce_startup_menu(p, Command.CANCEL, continue_enabled=False) is None and p.cursor == 2


def test_layout_matches_fitd_geometry():
    assert [tuple(r) for r in StartupLayout.ROWS] == [(10, 76, 300, 16), (10, 92, 300, 16), (10, 108, 300, 16)]
    assert StartupLayout.CADRE == ((160, 100), (320, 80))


def test_hit_tests():
    assert hit_test_startup((100, 80), continue_enabled=False) == 0
    assert hit_test_startup((100, 96), continue_enabled=False) is None
    assert hit_test_startup((100, 96), continue_enabled=True) == 1
    assert hit_test_startup((100, 112), continue_enabled=False) == 2
    assert hit_test_startup((100, 10), continue_enabled=False) is None
    assert hit_test_title((0, 0)) and hit_test_title((319, 199)) and not hit_test_title((320, 200))
