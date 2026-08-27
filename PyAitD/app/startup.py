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
    Command, UIPainter, _button, _font, _to_frame, draw_big_cadre, effective_rects, layout_book,
    screen_surface,
)

# AITD1.cpp:143 waits for `evalChrono(&chrono) >= 0x30`. This port's own
# chrono convention is 60 units/second, not FITD's 25fps frame-clock (see
# eval_var.py:101 and shell._auto_dismiss_picture's `delay_units * 1000 //
# 60`, the sibling conversion this mirrors) -- so 0x30 units is 800ms here,
# not the ~1920ms FITD's own frame-clock would give it.
TITLE_TIMEOUT_MS = 0x30 * 1000 // 60
TITLE_FADE_MS = 500            # FadeInPhys(8, 0) (AITD1.cpp:129)
MENU_TEXT_IDS = (11, 12, 13)   # "Begin a new game" / "Resume a saved game" / "Return to DOS"


class TitlePhase(Enum):
    TITLE = auto()
    CREDITS = auto()


@dataclass
class TitlePresenter:
    phase: TitlePhase = TitlePhase.TITLE
    page: int = 0


@dataclass(frozen=True)
class TitleResult:
    done: bool


def advance_title(presenter, elapsed_ms):
    # the title times out; the credits page never times out -- it waits for
    # input to turn each page, like FITD's Lire (turnPageFlag, AITD1.cpp:158-159)
    if presenter.phase is TitlePhase.TITLE and elapsed_ms >= TITLE_TIMEOUT_MS:
        presenter.phase = TitlePhase.CREDITS
    return None


def _credits_pages(assets, painter, size, credits_entry):
    # Lire(CVars[TEXTE_CREDITS] + 1, 48, 2, 260, 197, 1, 26, 0) (AITD1.cpp:159):
    # shared by reduce_title (page count only) and render_title (page content)
    # so the two can never disagree about how many pages there are.
    return layout_book(assets.book_tokens(credits_entry), painter, size, 212, 13)


def credits_page_count(assets, credits_entry):
    # scratch painter: credits_page_count has no painter in scope and
    # text_size measures at scale 1 regardless of which painter is passed,
    # so the page count this produces does not depend on it.
    painter = UIPainter()
    return len(_credits_pages(assets, painter, 15, credits_entry))


def reduce_title(presenter, command, *, page_count=1):
    if presenter.phase is TitlePhase.TITLE:
        presenter.phase = TitlePhase.CREDITS
        return None
    if presenter.page + 1 >= page_count:
        return TitleResult(True)
    presenter.page += 1
    return None


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


def _disabled_button(painter, rect, label, size=18):
    painter.rect(DISABLED_FILL, rect, border_radius=3)
    painter.rect((120, 110, 90), rect, width=2, border_radius=3)
    painter.text(label, size, DISABLED_TEXT, center=pygame.Rect(rect).center)


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
    # scratch painter: render_title isn't converted until Task 7, but
    # _credits_pages now needs a painter to measure logically.
    painter = UIPainter()
    pages = _credits_pages(assets, painter, 15, credits_entry)
    page = pages[min(presenter.page, len(pages) - 1)]
    y = 2
    for text, centered in page:
        glyph = font.render(text, True, (43, 31, 22))
        x = 48 + (212 - glyph.get_width()) // 2 if centered else 48
        surface.blit(glyph, (x, y))
        y += 15
    return _to_frame(surface)


def render_startup_menu(presenter, assets, *, continue_enabled):
    surface = pygame.Surface((320, 200))
    surface.fill((0, 0, 0))
    center, size = StartupLayout.CADRE
    draw_big_cadre(surface, assets.cadre_bank(), center, size)
    selection = presenter.hover if presenter.hover is not None else presenter.cursor
    # scratch painter: render_startup_menu isn't converted until Task 7, but
    # _button/_disabled_button now need a painter to draw. Borrowing the live
    # surface keeps the draw calls byte-identical to the direct pygame calls
    # they replace.
    painter = UIPainter()
    painter.surface = surface
    for index, (rect, text_id) in enumerate(zip(StartupLayout.ROWS, MENU_TEXT_IDS)):
        label = assets.system_text(text_id)
        if index == StartupRow.CONTINUE.value and not continue_enabled:
            _disabled_button(painter, rect, label, size=14)
        else:
            _button(painter, rect, label, selected=index == selection, size=14)
    return _to_frame(surface)
