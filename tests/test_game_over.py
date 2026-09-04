# SPDX-License-Identifier: GPL-2.0-only
"""LM_GAME_OVER's flag becomes a GameOver modal at the end of the LIFE pass
(mainLoop.cpp:185, 233): checked only after every live actor has run LIFE,
never mid-loop."""
import pytest

from PyAitD.app.controls.router import route_command, route_mouse
from PyAitD.engine.script.effects import GameMode, GameOver
from PyAitD.engine.script.game import init_game
from PyAitD.engine.script.playworld import IDLE, play_tick
from PyAitD.app.controls.actions import Action
from PyAitD.app.ui import ModalSession

pytestmark = pytest.mark.engine


def test_game_over_finishes_current_life_pass_then_opens_modal(data_dir, profile, monkeypatch):
    import PyAitD.engine.script.playworld as playworld

    game = init_game(data_dir, profile)
    floor = game.load_floor(game.current_floor)
    live = [i for i, actor in enumerate(game.actors) if actor.index_in_world >= 0]
    assert len(live) > 1, "the test needs more than one live actor to prove the loop finished"
    seen = []

    def fake_run_life(current, frame):
        seen.append(frame.owner_idx)
        if frame.owner_idx == live[0]:
            current.flag_game_over = 1
        return True

    monkeypatch.setattr(playworld.tick, "run_life", fake_run_life)
    monkeypatch.setattr(playworld.tick, "life_gate", lambda actor: actor.index_in_world >= 0)
    assert play_tick(game, floor, IDLE) is False
    assert seen == live
    assert game.flag_game_over == 0
    assert game.mode is GameMode.GAME_OVER
    assert game.active_modal == GameOver(120)
    timer = game.timer
    assert play_tick(game, floor, IDLE) is False
    assert game.timer == timer


def _game_over_session(data_dir, profile):
    game = init_game(data_dir, profile)
    game.open_modal(GameOver())
    session = ModalSession()
    session.reset_for(game.active_modal)
    return game, session


@pytest.mark.parametrize("command", [Action.ACTION, Action.CANCEL, Action.INVENTORY_CONFIRM])
def test_game_over_command_locked_at_1999ms_rejects_restart(data_dir, profile, command):
    game, session = _game_over_session(data_dir, profile)
    session.elapsed_ms = 1999
    assert route_command(game, session, command) is True
    assert game.restart_requested is False


@pytest.mark.parametrize("command", [Action.ACTION, Action.CANCEL, Action.INVENTORY_CONFIRM])
def test_game_over_command_ready_at_2000ms_requests_restart(data_dir, profile, command):
    # OPEN_INVENTORY is translated to ACCEPT by route_command before dispatch,
    # so this parametrization also covers the OPEN_INVENTORY-as-ACCEPT case.
    game, session = _game_over_session(data_dir, profile)
    session.elapsed_ms = 2000
    assert route_command(game, session, command) is True
    assert game.restart_requested is True


def test_game_over_accepts_any_left_click_only_after_delay(data_dir, profile):
    game = init_game(data_dir, profile)
    game.open_modal(GameOver())
    session = ModalSession()
    session.reset_for(game.active_modal)
    assert route_mouse(game, session, (0, 0))
    assert game.restart_requested is False
    session.elapsed_ms = 120 * 1000 // 60
    assert route_mouse(game, session, (319, 199))
    assert game.restart_requested is True


@pytest.mark.parametrize("corner", [(0, 0), (319, 199)])
def test_game_over_click_accepts_at_either_extreme_corner_once_ready(data_dir, profile, corner):
    game, session = _game_over_session(data_dir, profile)
    session.elapsed_ms = 2000
    assert route_mouse(game, session, corner) is True
    assert game.restart_requested is True


@pytest.mark.parametrize("corner", [(0, 0), (319, 199)])
def test_game_over_click_locked_at_either_extreme_corner_rejects_restart(data_dir, profile, corner):
    game, session = _game_over_session(data_dir, profile)
    session.elapsed_ms = 1999
    assert route_mouse(game, session, corner) is True
    assert game.restart_requested is False


def test_game_over_during_a_cutscene_is_cutscene_finished(data_dir, profile, monkeypatch):
    from PyAitD.engine.script.effects import CutsceneFinished
    import PyAitD.engine.script.playworld as playworld

    game = init_game(data_dir, profile)
    game.allow_system_menu = False      # PlayWorld(allowSystemMenu=0): mainLoop.cpp:185 break, not death
    floor = game.load_floor(game.current_floor)
    monkeypatch.setattr(playworld.tick, "run_life", lambda current, frame: setattr(current, "flag_game_over", 1) or True)
    monkeypatch.setattr(playworld.tick, "life_gate", lambda actor: actor.index_in_world >= 0)
    assert play_tick(game, floor, IDLE) is False
    assert game.active_modal == CutsceneFinished() and game.mode is GameMode.CUTSCENE_END
    assert game.flag_game_over == 0
