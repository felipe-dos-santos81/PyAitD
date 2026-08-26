# SPDX-License-Identifier: GPL-2.0-only
"""Startup flow presenters, reducers, geometry and drawing: title screen and
credits page (AITD1.cpp:121 makeIntroScreens) and the main menu
(startupMenu.cpp:35 MainMenu). Same rules as app/ui.py: pygame allowed,
never mutates world/actor/inventory/LIFE state."""
from dataclasses import dataclass
from enum import Enum, auto

import numpy as np
import pygame

from PyAitD.app.ui import Command, _button, _font, _to_frame, draw_big_cadre, effective_rects, layout_book, screen_surface

TITLE_TIMEOUT_MS = 3000        # 0x30 chrono units of 1/16 s (AITD1.cpp:143)
TITLE_FADE_MS = 500            # FadeInPhys(8, 0) (AITD1.cpp:129)
MENU_TEXT_IDS = (11, 12, 13)   # "Begin a new game" / "Resume a saved game" / "Return to DOS"


class TitlePhase(Enum):
    TITLE = auto()
    CREDITS = auto()


@dataclass
class TitlePresenter:
    phase: TitlePhase = TitlePhase.TITLE


@dataclass(frozen=True)
class TitleResult:
    done: bool


def advance_title(presenter, elapsed_ms):
    # the title times out; the credits page waits for input like FITD's Lire
    if presenter.phase is TitlePhase.TITLE and elapsed_ms >= TITLE_TIMEOUT_MS:
        presenter.phase = TitlePhase.CREDITS
    return None


def reduce_title(presenter, command):
    if presenter.phase is TitlePhase.TITLE:
        presenter.phase = TitlePhase.CREDITS
        return None
    return TitleResult(True)


class StartupRow(Enum):
    NEW_GAME = 0
    CONTINUE = 1
    QUIT = 2


@dataclass
class StartupMenuPresenter:
    cursor: int = 0
    hover: int | None = None


@dataclass(frozen=True)
class StartupMenuResult:
    new_game: bool = False
    continue_game: bool = False
    quit: bool = False


def _enabled_rows(continue_enabled):
    return [row.value for row in StartupRow if continue_enabled or row is not StartupRow.CONTINUE]


def reduce_startup_menu(presenter, command, *, continue_enabled):
    rows = _enabled_rows(continue_enabled)
    command = Command.ACCEPT if command is Command.OPEN_INVENTORY else command
    if command in (Command.UP, Command.LEFT, Command.DOWN, Command.RIGHT):
        # step from the nearest enabled row so a cursor parked on the
        # disabled row (never reachable via navigation, only by direct
        # presenter mutation) still moves to a sane neighbour
        index = rows.index(presenter.cursor) if presenter.cursor in rows else 0
        step = -1 if command in (Command.UP, Command.LEFT) else 1
        presenter.cursor = rows[(index + step) % len(rows)]
        return None
    if command is Command.ACCEPT:
        if presenter.cursor not in rows:
            return None  # cursor is parked on the disabled row: no-op
        row = StartupRow(presenter.cursor)
        if row is StartupRow.NEW_GAME:
            return StartupMenuResult(new_game=True)
        if row is StartupRow.CONTINUE:
            return StartupMenuResult(continue_game=True)
        return StartupMenuResult(quit=True)
    return None


class StartupLayout:
    ROWS = tuple(pygame.Rect(10, 76 + 16 * i, 300, 16) for i in range(3))   # startupMenu.cpp:24 AffRect(10, y, 309, y+16)
    HIT_ROWS = effective_rects(ROWS)
    CADRE = ((160, 100), (320, 80))                                          # AffBigCadre(160, 100, 320, 80)
    FRAME = pygame.Rect(0, 0, 320, 200)


def hit_test_startup(pos, *, continue_enabled):
    for index, rect in enumerate(StartupLayout.HIT_ROWS):
        if rect.collidepoint(pos):
            return index if index in _enabled_rows(continue_enabled) else None
    return None


def hit_test_title(pos):
    return StartupLayout.FRAME.collidepoint(pos)
