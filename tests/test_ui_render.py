# SPDX-License-Identifier: GPL-2.0-only
import numpy as np
import pygame

from PyAitD.effects import ReadText, ShowFound, ShowPicture, TimedMessage
from PyAitD.game import init_game
from PyAitD.text import BookToken
from PyAitD.ui import (
    FoundPresenter, ReadingPresenter, layout_book,
    overlay_messages, render_found, render_picture, render_reading,
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
