# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.engine.effects import FoundResult, GameMode, LifeFrame, OpenInventory, ReadText, ShowFound
from PyAitD.engine.game import init_game
from PyAitD.engine.interaction import apply_found_result, apply_inventory_result, apply_reading_result
from PyAitD.app.ui import InventoryResult, ModalSession, ReadingResult
from PyAitD.games.aitd1.profile import AITD1


def test_leave_debounces_and_resumes_parent(data_dir, monkeypatch):
    game = init_game(data_dir, AITD1)
    game.life_stack.append(LifeFrame(0, 1, pc=6))
    game.open_modal(ShowFound(13, False))
    resumed = []
    monkeypatch.setattr("PyAitD.engine.interaction.resume_life", lambda g: resumed.append(True) or True)
    assert apply_found_result(game, FoundResult.LEAVE) is True
    assert game.world_objects[13].track_number == game.timer
    assert game.mode is GameMode.PLAY
    assert resumed == [True]


def test_take_closes_found_before_nested_found_life(data_dir, monkeypatch):
    game = init_game(data_dir, AITD1)
    game.open_modal(ShowFound(13, False))
    seen = []
    monkeypatch.setattr("PyAitD.engine.interaction.begin_take", lambda g, i: seen.append((i, g.active_modal)) or False)
    assert apply_found_result(game, FoundResult.TAKE) is False
    assert seen == [(13, None)]


def test_inventory_cancel_and_read_dismiss_restore_play(data_dir, monkeypatch):
    game = init_game(data_dir, AITD1)
    monkeypatch.setattr("PyAitD.engine.interaction.resume_life", lambda g: True)
    game.open_modal(OpenInventory())
    assert apply_inventory_result(game, InventoryResult(cancelled=True)) is True
    game.open_modal(ReadText(1, 0))
    assert apply_reading_result(game, ReadingResult(True)) is True
    assert game.flag_init_view == 1
    assert game.mode is GameMode.PLAY


def test_session_keeps_presenters_for_same_effect():
    session = ModalSession()
    effect = OpenInventory()
    session.reset_for(effect)
    session.inventory.object_cursor = 3
    session.reset_for(effect)
    assert session.inventory.object_cursor == 3


def test_session_resets_for_equal_valued_new_effect():
    session = ModalSession()
    session.reset_for(OpenInventory())
    session.inventory.object_cursor = 3
    session.reset_for(OpenInventory())
    assert session.inventory.object_cursor == 0
    session.reset_for(ShowFound(2, True))
    assert session.found.choice is FoundResult.LEAVE
    session.reset_for(ShowFound(3, False))
    assert session.found.choice is FoundResult.TAKE
