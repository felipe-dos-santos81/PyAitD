# SPDX-License-Identifier: GPL-2.0-only
"""LM_GAME_OVER's flag becomes a GameOver modal at the end of the LIFE pass
(mainLoop.cpp:185, 233): checked only after every live actor has run LIFE,
never mid-loop."""
from PyAitD.effects import GameMode, GameOver
from PyAitD.floor import Floor
from PyAitD.game import init_game
from PyAitD.playworld import play_tick
from PyAitD.ui import InputBuffer


def test_game_over_finishes_current_life_pass_then_opens_modal(data_dir, monkeypatch):
    import PyAitD.playworld as playworld

    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    live = [i for i, actor in enumerate(game.actors) if actor.index_in_world >= 0]
    assert len(live) > 1, "the test needs more than one live actor to prove the loop finished"
    seen = []

    def fake_run_life(current, frame):
        seen.append(frame.owner_idx)
        if frame.owner_idx == live[0]:
            current.flag_game_over = 1
        return True

    monkeypatch.setattr(playworld, "run_life", fake_run_life)
    monkeypatch.setattr(playworld, "life_gate", lambda actor: actor.index_in_world >= 0)
    assert play_tick(game, floor, InputBuffer()) is False
    assert seen == live
    assert game.flag_game_over == 0
    assert game.mode is GameMode.GAME_OVER
    assert game.active_modal == GameOver(120)
    timer = game.timer
    assert play_tick(game, floor, InputBuffer()) is False
    assert game.timer == timer
