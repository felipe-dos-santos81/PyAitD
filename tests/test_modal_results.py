# SPDX-License-Identifier: GPL-2.0-only
from maitd.effects import GameMode, LifeFrame, OpenInventory, ReadText, ShowFound
from maitd.game import init_game
from maitd.interaction import apply_found_result, apply_inventory_result, apply_reading_result
from maitd.ui import FoundResult, InventoryResult, ReadingResult


def test_leave_debounces_and_resumes_parent(data_dir, monkeypatch):
    game = init_game(data_dir)
    game.life_stack.append(LifeFrame(0, 1, pc=6))
    game.open_modal(ShowFound(13, False))
    resumed = []
    monkeypatch.setattr("maitd.interaction.resume_life", lambda g: resumed.append(True) or True)
    assert apply_found_result(game, FoundResult.LEAVE) is True
    assert game.world_objects[13].track_number == game.timer
    assert game.mode is GameMode.PLAY
    assert resumed == [True]


def test_take_closes_found_before_nested_found_life(data_dir, monkeypatch):
    game = init_game(data_dir)
    game.open_modal(ShowFound(13, False))
    seen = []
    monkeypatch.setattr("maitd.interaction.begin_take", lambda g, i: seen.append((i, g.active_modal)) or False)
    assert apply_found_result(game, FoundResult.TAKE) is False
    assert seen == [(13, None)]


def test_inventory_cancel_and_read_dismiss_restore_play(data_dir, monkeypatch):
    game = init_game(data_dir)
    monkeypatch.setattr("maitd.interaction.resume_life", lambda g: True)
    game.open_modal(OpenInventory())
    assert apply_inventory_result(game, InventoryResult(cancelled=True)) is True
    game.open_modal(ReadText(1, 0))
    assert apply_reading_result(game, ReadingResult(True)) is True
    assert game.flag_init_view == 1
    assert game.mode is GameMode.PLAY
