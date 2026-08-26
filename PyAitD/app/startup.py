# SPDX-License-Identifier: GPL-2.0-only
"""Startup flow presenters, reducers, geometry and drawing: title screen and
credits page (AITD1.cpp:121 makeIntroScreens) and the main menu
(startupMenu.cpp:35 MainMenu). Same rules as app/ui.py: pygame allowed,
never mutates world/actor/inventory/LIFE state."""
from dataclasses import dataclass
from enum import Enum, auto

import numpy as np
import pygame

from PyAitD.app.ui import (
    Command, _button, _font, _to_frame, draw_big_cadre, effective_rects, layout_book, screen_surface,
)

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


DISABLED_FILL = (48, 40, 36)
DISABLED_TEXT = (140, 128, 110)


def _disabled_button(surface, rect, label, size=18):
    pygame.draw.rect(surface, DISABLED_FILL, rect, border_radius=3)
    pygame.draw.rect(surface, (120, 110, 90), rect, width=2, border_radius=3)
    glyph = _font(size).render(label, True, DISABLED_TEXT)
    surface.blit(glyph, glyph.get_rect(center=rect.center))


def render_title(presenter, assets, resolver, elapsed_ms, credits_entry):
    if presenter.phase is TitlePhase.TITLE:
        # screen_surface's Surface is shared/cached: copy before drawing on it.
        surface = screen_surface(resolver, 13).copy()                # AITD1_TITRE
        alpha = min(255, 255 * max(0, elapsed_ms) // TITLE_FADE_MS)
        if alpha < 255:
            shade = pygame.Surface((320, 200), flags=pygame.SRCALPHA)
            shade.fill((0, 0, 0, 255 - alpha))
            surface.blit(shade, (0, 0))
        return _to_frame(surface)
    # screen_surface's Surface is shared/cached: copy before drawing on it.
    surface = screen_surface(resolver, 7).copy()                     # AITD1_LIVRE
    font = _font(15)
    page = layout_book(assets.book_tokens(credits_entry), font, 212, 13)[0]   # Lire(..., 48,2,260,197)
    y = 2
    for text, centered in page:
        glyph = font.render(text, True, (43, 31, 22))
        x = 48 + (212 - glyph.get_width()) // 2 if centered else 48
        surface.blit(glyph, (x, y))
        y += 15
    return _to_frame(surface)


def render_startup_menu(presenter, assets, resolver, *, continue_enabled):
    surface = pygame.Surface((320, 200))
    surface.fill((0, 0, 0))
    center, size = StartupLayout.CADRE
    draw_big_cadre(surface, assets.cadre_bank(), center, size)
    selection = presenter.hover if presenter.hover is not None else presenter.cursor
    for index, (rect, text_id) in enumerate(zip(StartupLayout.ROWS, MENU_TEXT_IDS)):
        label = assets.system_text(text_id)
        if index == StartupRow.CONTINUE.value and not continue_enabled:
            _disabled_button(surface, rect, label, size=14)
        else:
            _button(surface, rect, label, selected=index == selection, size=14)
    return _to_frame(surface)
