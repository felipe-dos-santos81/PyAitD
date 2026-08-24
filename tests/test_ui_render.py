# SPDX-License-Identifier: GPL-2.0-only
import numpy as np
import pygame
import pytest

from PyAitD.assets import Assets
from PyAitD.config import default_settings
from PyAitD.effects import ReadText, ShowFound, ShowPicture, TimedMessage
from PyAitD.game import init_game
from PyAitD.text import BookToken
from PyAitD.ui import (
    CharacterLayout, CharacterPhase, CharacterSelectPresenter,
    FoundPresenter, ReadingPresenter, SystemMenuPage, SystemMenuPresenter,
    draw_big_cadre, layout_book,
    overlay_messages, render_character_select, render_cursor, render_found,
    render_game_over, render_picture, render_play_hud, render_reading,
    render_settings_notice, render_system_menu,
)


def test_modal_renderers_return_logical_rgb_frames(data_dir):
    pygame.font.init()
    game = init_game(data_dir)
    frames = [
        render_found(
            ShowFound(13, False), FoundPresenter(), game.assets,
            game.assets.system_text(game.world_objects[13].found_name),
        ),
        render_reading(ReadText(1, 0), ReadingPresenter(), game.assets),
        render_picture(ShowPicture(10, 60, 4), game.assets),
    ]
    assert all(frame.shape == (200, 320, 3) for frame in frames)
    assert all(frame.dtype == np.uint8 for frame in frames)


def test_book_layout_preserves_tab_prefix_and_center_flag():
    pygame.font.init()
    pages = layout_book(
        (BookToken("tab"), BookToken("center"), BookToken("text", "Entry")),
        pygame.font.Font(None, 16),
        190,
        8,
    )
    assert pages[0][0] == ("    Entry", True)


def test_message_overlay_does_not_mutate_source_frame(data_dir):
    pygame.font.init()
    game = init_game(data_dir)
    source = np.zeros((200, 320, 3), dtype=np.uint8)
    result = overlay_messages(source, [TimedMessage(100), None, None, None, None], game.assets)
    assert np.count_nonzero(source) == 0
    assert np.count_nonzero(result) > 0


def test_cursor_marks_the_frame_without_mutating_the_input():
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    out = render_cursor(frame, (160, 100), "walk")
    assert out is not frame, "presentation must not mutate the scene frame"
    assert int(out.sum()) > 0, "the cursor drew nothing"
    assert int(frame.sum()) == 0


def test_play_hud_draws_only_when_available_without_mutating_input():
    source = np.zeros((200, 320, 3), dtype=np.uint8)
    unavailable = render_play_hud(source, inventory_available=False)
    available = render_play_hud(source, inventory_available=True)
    assert unavailable is source
    assert np.array_equal(unavailable, source)
    assert not np.array_equal(available, source)
    assert int(source.sum()) == 0


def test_all_pointer_kinds_have_distinct_pixel_output():
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    rendered = {
        kind: render_cursor(frame, (160, 100), kind)
        for kind in ("inventory", "attack", "target", "walk", "blocked")
    }
    assert len({image.tobytes() for image in rendered.values()}) == 5


def test_push_cursor_is_a_sixth_distinct_pointer():
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    kinds = ("inventory", "attack", "target", "push", "walk", "blocked")
    rendered = {kind: render_cursor(frame, (160, 100), kind) for kind in kinds}

    assert len({image.tobytes() for image in rendered.values()}) == len(kinds)


def test_cursor_outside_the_surface_is_a_no_op():
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    assert np.array_equal(render_cursor(frame, None, "walk"), frame)


def test_game_over_locked_frame_is_identical_and_ready_frame_is_overlayed():
    pygame.font.init()
    source = np.arange(320 * 200 * 3, dtype=np.uint8).reshape((200, 320, 3))
    locked = render_game_over(source, ready=False)
    ready = render_game_over(source, ready=True)
    assert locked is source
    assert np.array_equal(locked, source)
    assert not np.array_equal(ready, source)
    assert np.array_equal(source, locked)


def test_big_cadre_pins_fitd_interior_and_ring(data_dir):
    surface = pygame.Surface((320, 200))
    surface.fill((0, 0, 0))
    interior = draw_big_cadre(surface, Assets(data_dir).cadre_bank(), (160, 100), (320, 200))
    assert interior == pygame.Rect(8, 8, 304, 184)
    frame = pygame.surfarray.array3d(surface).swapaxes(0, 1)
    assert np.count_nonzero(frame) > 0, "the cadre ring drew nothing"
    inside = frame[interior.top:interior.bottom, interior.left:interior.right]
    assert np.count_nonzero(inside) == 0, "the cadre interior must stay black"


def test_character_portraits_restore_art_inside_fitd_cadre(data_dir):
    assets = Assets(data_dir)
    base = assets.resource_screen(10)
    frame = render_character_select(CharacterSelectPresenter(choice=0), assets)
    left = CharacterLayout.PORTRAITS[0]
    assert np.array_equal(frame[left.top:left.bottom, left.left:left.right],
                          base[left.top:left.bottom, left.left:left.right])
    assert not np.array_equal(frame, base)


@pytest.mark.parametrize(
    ("choice", "hero", "copied"),
    ((0, 1, pygame.Rect(160, 0, 160, 200)),
     (1, 0, pygame.Rect(0, 0, 160, 200))),
)
def test_story_composes_the_opposite_intro_half_and_expected_text(
    data_dir, choice, hero, copied,
):
    assets = Assets(data_dir)
    presenter = CharacterSelectPresenter(choice=choice, phase=CharacterPhase.STORY)
    frame = render_character_select(presenter, assets)
    intro = assets.resource_screen(14)
    # Compare a margin outside the text column; the copied half remains exact.
    margin = pygame.Rect(copied.left, 0, 4, 200)
    assert np.array_equal(
        frame[margin.top:margin.bottom, margin.left:margin.right],
        intro[margin.top:margin.bottom, margin.left:margin.right],
    )
    assert int(frame.sum()) > 0
    assert (1 if choice == 0 else 0) == hero


def test_settings_notice_overlays_without_mutating_the_mode_frame():
    source = np.zeros((200, 320, 3), dtype=np.uint8)
    result = render_settings_notice(source, "Could not load settings from /x: corrupt")
    assert np.count_nonzero(source) == 0
    assert result.shape == source.shape
    assert not np.array_equal(result, source)


@pytest.mark.parametrize("page", tuple(SystemMenuPage))
def test_system_menu_is_a_logical_rgb_frame(data_dir, page):
    frame = render_system_menu(
        SystemMenuPresenter(page=page), default_settings(), Assets(data_dir),
    )
    assert frame.shape == (200, 320, 3)
    assert frame.dtype == np.uint8
