# SPDX-License-Identifier: GPL-2.0-only
from collections import deque

import pytest

from PyAitD.engine.effects import (
    AddMessage, BeginTake, ChooseCharacter, GameMode, LifeFrame, OpenSystemMenu,
    NavIntent, ShowFound,
)
from PyAitD.engine.game import init_game


def test_game_initializes_fitd_inventory_and_effect_state(data_dir):
    game = init_game(data_dir)
    assert game.mode is GameMode.PLAY
    assert game.active_modal is None
    assert game.life_stack == []
    assert game.immediate_effects == deque()
    assert game.inventory_count == [0, 0]
    assert game.inventory_table == [[-1] * 30, [-1] * 30]
    assert game.in_hand_table == [-1, -1]
    assert game.messages == [None] * 5


def test_game_rejects_two_active_modals(data_dir):
    game = init_game(data_dir)
    game.open_modal(ShowFound(12, False))
    assert game.mode is GameMode.FOUND
    with pytest.raises(RuntimeError, match=r"ShowFound.*ShowFound"):
        game.open_modal(ShowFound(13, False))


def test_immediate_effect_is_fifo(data_dir):
    game = init_game(data_dir)
    game.emit(AddMessage(100))
    game.emit(BeginTake(12))
    assert list(game.immediate_effects) == [AddMessage(100), BeginTake(12)]
    assert LifeFrame(3, 9).pc == 0


def test_nav_intent_defaults_to_a_non_held_approach():
    intent = NavIntent(10, 20, 0)
    assert intent.requires_hold is False
    assert intent.engaged is False
    assert intent.origin_floor is None
    assert intent.origin_room is None


@pytest.mark.parametrize(
    ("effect", "mode"),
    ((ChooseCharacter(), GameMode.CHARACTER_SELECT),
     (OpenSystemMenu(), GameMode.SYSTEM_MENU)),
)
def test_shell_effects_use_the_existing_modal_mode_mapping(data_dir, effect, mode):
    game = init_game(data_dir)
    game.open_modal(effect)
    assert game.mode is mode
