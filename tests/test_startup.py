# SPDX-License-Identifier: GPL-2.0-only
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pytest

from PyAitD.app.startup import (
    MENU_TEXT_IDS, StartupLayout, StartupMenuPresenter, StartupMenuResult, StartupRow, TITLE_FADE_MS,
    TITLE_TIMEOUT_MS, TitlePhase, TitlePresenter, TitleResult, advance_title, credits_page_count,
    hit_test_startup, hit_test_title, reduce_startup_menu, reduce_title, render_startup_menu, render_title,
)
from PyAitD.app.ui import Command, UIPainter
from PyAitD.engine.game import init_game
from PyAitD.render.asset_resolver import AssetResolver

pytestmark = pytest.mark.shell


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


def test_title_fades_in_from_black(data_dir, profile):
    import pygame
    pygame.font.init()
    game = init_game(data_dir, profile)
    resolver = AssetResolver(game.assets, None)
    credits = game.cvars[profile.cvar_index("TEXTE_CREDITS")] + 1
    black_painter = UIPainter()
    render_title(black_painter, TitlePresenter(), game.assets, resolver, 0, credits)
    black = black_painter.to_frame()
    full_painter = UIPainter()
    render_title(full_painter, TitlePresenter(), game.assets, resolver, TITLE_FADE_MS, credits)
    full = full_painter.to_frame()
    assert black.shape == full.shape == (200, 320, 4)
    assert black[:, :, :3].max() == 0
    assert (full[:, :, :3] == game.assets.resource_screen(13)).all()
    page_painter = UIPainter()
    render_title(page_painter, TitlePresenter(TitlePhase.CREDITS), game.assets, resolver, 0, credits)
    page = page_painter.to_frame()
    assert page.shape == (200, 320, 4)
    assert not (page[:, :, :3] == game.assets.resource_screen(7)).all()  # text drawn


def test_menu_highlights_only_the_cursor_row(data_dir, profile):
    import pygame
    pygame.font.init()
    game = init_game(data_dir, profile)
    painter = UIPainter()
    render_startup_menu(painter, StartupMenuPresenter(cursor=2), game.assets, continue_enabled=False)
    frame = painter.to_frame()
    assert frame.shape == (200, 320, 4)
    rows = StartupLayout.ROWS
    # (x+2, y+2) sits on the rounded corner's 2px border stroke (border_radius=3),
    # not the fill -- verified against pygame-ce's actual rasterization. y+4 clears
    # the corner arc and still lands left of the centered label glyph.
    probe = lambda r: tuple(frame[r.y + 4, r.x + 2, :3])
    assert probe(rows[2]) == (214, 190, 142)          # selected fill (ui._button)
    assert probe(rows[0]) == (78, 59, 46)             # unselected fill
    assert probe(rows[1]) == (48, 40, 36)             # disabled fill


def test_title_and_menu_renders_do_not_bleed_across_calls(data_dir, profile):
    # screen_surface's Surface is shared/cached per (resolver, entry): a renderer
    # that draws on it without .copy() first would bleed its fade/text into every
    # later frame for that entry. Calling twice and comparing catches that.
    import pygame
    pygame.font.init()
    game = init_game(data_dir, profile)
    resolver = AssetResolver(game.assets, None)
    credits = game.cvars[profile.cvar_index("TEXTE_CREDITS")] + 1

    fade1_painter = UIPainter()
    render_title(fade1_painter, TitlePresenter(), game.assets, resolver, TITLE_FADE_MS // 2, credits)
    fade2_painter = UIPainter()
    render_title(fade2_painter, TitlePresenter(), game.assets, resolver, TITLE_FADE_MS // 2, credits)
    assert (fade1_painter.to_frame() == fade2_painter.to_frame()).all()

    page1_painter = UIPainter()
    render_title(page1_painter, TitlePresenter(TitlePhase.CREDITS), game.assets, resolver, 0, credits)
    page2_painter = UIPainter()
    render_title(page2_painter, TitlePresenter(TitlePhase.CREDITS), game.assets, resolver, 0, credits)
    assert (page1_painter.to_frame() == page2_painter.to_frame()).all()


def test_credits_reaches_every_page_before_handing_off_to_the_menu(data_dir, profile):
    # AITD1.cpp:158-159 sets turnPageFlag before Lire, so the player pages
    # through the whole entry -- not just page 0 (Important 2). On real data
    # this entry lays out to 8 pages; the handoff must land on the last one.
    game = init_game(data_dir, profile)
    credits = game.cvars[profile.cvar_index("TEXTE_CREDITS")] + 1
    page_count = credits_page_count(game.assets, credits)
    assert page_count == 8

    presenter = TitlePresenter(TitlePhase.CREDITS)
    seen_pages = [presenter.page]
    for _ in range(page_count - 1):
        result = reduce_title(presenter, Command.ACCEPT, page_count=page_count)
        assert result is None, "must not hand off before the last page"
        seen_pages.append(presenter.page)
    assert seen_pages == list(range(page_count)), "every page must be reachable"

    assert reduce_title(presenter, Command.ACCEPT, page_count=page_count) == TitleResult(True)
    assert presenter.page == page_count - 1, "the handoff must happen on the last page, not the first"


def test_credits_render_shows_each_pages_own_content(data_dir, profile):
    # Regression for the truncation bug: page 0's only text is the
    # publisher credit; the director credit only appears on page 1.
    import pygame
    pygame.font.init()
    game = init_game(data_dir, profile)
    resolver = AssetResolver(game.assets, None)
    credits = game.cvars[profile.cvar_index("TEXTE_CREDITS")] + 1

    page0_painter = UIPainter()
    render_title(page0_painter, TitlePresenter(TitlePhase.CREDITS, page=0), game.assets, resolver, 0, credits)
    page1_painter = UIPainter()
    render_title(page1_painter, TitlePresenter(TitlePhase.CREDITS, page=1), game.assets, resolver, 0, credits)
    assert not (page0_painter.to_frame() == page1_painter.to_frame()).all(), (
        "page 1 must render different content from page 0"
    )


def test_menu_text_ids_resolve_to_the_games_own_strings(data_dir, profile):
    # Important/Minor 6: MENU_TEXT_IDS must point at the game's own ENGLISH.PAK
    # strings, not paraphrases -- an id slip would still pass the render test
    # (which only probes fill colours), so pin the actual resolved text.
    game = init_game(data_dir, profile)
    assert [game.assets.system_text(text_id) for text_id in MENU_TEXT_IDS] == [
        "Begin a new game", "Resume a saved game", "Return to DOS",
    ]


@pytest.mark.parametrize("scale", (1, 4))
def test_credits_centred_line_lands_on_the_credits_columns_centre(
    data_dir, profile, monkeypatch, scale,
):
    """render_title measured a centred credits line with the scale-1
    text_size and placed it by topleft; pygame's font metrics are not linear
    in size, so at scale 4 the widest real credit ("Realized & Directed by")
    landed 3.5 logical pixels (14 window pixels) left of the column's
    centre. Isolates the glyph by diffing against the same page with the
    line blank, so the AITD1_LIVRE background cancels out."""
    import numpy as np
    import pygame

    import PyAitD.app.startup as startup

    pygame.font.init()
    game = init_game(data_dir, profile)
    resolver = AssetResolver(game.assets, None)
    credits = game.cvars[profile.cvar_index("TEXTE_CREDITS")] + 1

    def render(line):
        monkeypatch.setattr(startup, "_credits_pages", lambda *_a: (((line, True),),))
        painter = UIPainter(scale)
        render_title(painter, TitlePresenter(TitlePhase.CREDITS), game.assets, resolver, 0, credits)
        return painter.to_frame()

    ink = np.argwhere(np.any(render("") != render("Realized & Directed by"), axis=2))
    assert ink.size, "the centred line drew nothing"
    centre = (int(ink[:, 1].min()) + int(ink[:, 1].max()) + 1) / 2
    # AITD1.cpp:159's Lire box is x=48 wide 212, so its centre is logical 154
    assert abs(centre / scale - 154) <= 1.0, (
        f"the centred credit spans a box centred on logical x={centre / scale:.2f}, not 154"
    )
