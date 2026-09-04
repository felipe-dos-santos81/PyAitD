# SPDX-License-Identifier: GPL-2.0-only
"""The floor-7 opening: FITD startGame(7, 1, 0) (AITD1.cpp:356). Real data;
golden ticks pinned from the 2026-08-26 headless spike."""
import pytest

from PyAitD.engine.data.floor import Floor
from PyAitD.engine.script.game import init_game, start_game
from PyAitD.engine.script.interaction import apply_reading_result
from PyAitD.engine.script.playworld import IDLE, play_tick
from PyAitD.app.ui import ReadingResult

pytestmark = [pytest.mark.engine, pytest.mark.journey]


def boot_intro(data_dir, profile, hero=0):
    game = init_game(data_dir, profile, hero=hero)
    start_game(game, *profile.intro_start)
    return game, Floor(data_dir, game.current_floor, profile)


def run_intro(data_dir, profile, game, floor, ticks, on_modal=None):
    """Tick the cutscene, swapping Floor on floor changes like shell.run and
    auto-dismissing pictures. Returns (last_tick, floor, events)."""
    events = []
    t = -1
    for t in range(ticks):
        play_tick(game, floor, IDLE)
        if floor.number != game.current_floor:
            floor = Floor(data_dir, game.current_floor, profile)
            events.append((t, "floor", game.current_floor, game.current_room))
        if game.mode.name != "PLAY":
            events.append((t, type(game.active_modal).__name__))
            if on_modal is not None and on_modal(game):
                break
            apply_reading_result(game, ReadingResult(True))
    return t, floor, events


def test_director_places_object_288_and_it_spawns(data_dir, profile):
    game, floor = boot_intro(data_dir, profile)
    # game.timer (game.py:604 game_step_tick) increments once per play_tick
    # call, so N calls leave game.timer == N. The director's reduced
    # LM_STAGE (life.cpp:620) places object 288 on floor 7 the tick
    # game.timer becomes 1596, and GenereActiveList spawns it later in that
    # same play_tick (mainLoop.cpp:249) -- 1596 calls, not 1597, land here.
    # One tick further, LIFE 537's own first opcode is LM_LIFE (life.cpp:1329,
    # life_ops.op_life) self-transitioning to life 538, so 1597 calls would
    # observe life 538 instead.
    run_intro(data_dir, profile, game, floor, 1596)
    w = game.world_objects[288]
    assert (w.stage, w.room) == (7, 0)
    assert w.obj_index != -1 and game.actors[w.obj_index].life == 537


LETTER_TICK = 1081
FLOOR_TICKS = ((3217, 3, 1), (4919, 2, 2), (5652, 1, 7))
END_TICK = 7293


def test_intro_runs_to_cutscene_finished_at_the_pinned_ticks(data_dir, profile):
    from PyAitD.engine.script.effects import CutsceneFinished
    game, floor = boot_intro(data_dir, profile)
    game.allow_system_menu = False
    last, floor, events = run_intro(
        data_dir, profile, game, floor, END_TICK + 50,
        on_modal=lambda g: isinstance(g.active_modal, CutsceneFinished),
    )
    assert (LETTER_TICK, "ShowPicture") in events
    assert [e for e in events if e[1] == "floor"] == [(t, "floor", f, r) for t, f, r in FLOOR_TICKS]
    assert last == END_TICK and isinstance(game.active_modal, CutsceneFinished)
    assert not any(e[1] == "GameOver" for e in events)


@pytest.mark.parametrize("hero", (0, 1))
def test_intro_boots_for_both_heroes(data_dir, profile, hero):
    game, floor = boot_intro(data_dir, profile, hero)
    game.allow_system_menu = False
    run_intro(data_dir, profile, game, floor, 200)
    assert game.current_floor == 7 and game.mode.name == "PLAY"
