# SPDX-License-Identifier: GPL-2.0-only
"""The floor-7 opening: FITD startGame(7, 1, 0) (AITD1.cpp:356). Real data;
golden ticks pinned from the 2026-08-26 headless spike."""
from PyAitD.engine.floor import Floor
from PyAitD.engine.game import init_game, start_game
from PyAitD.engine.interaction import apply_reading_result
from PyAitD.engine.playworld import play_tick
from PyAitD.app.ui import InputBuffer, ReadingResult
from PyAitD.games.aitd1.profile import AITD1


def boot_intro(data_dir, hero=0):
    game = init_game(data_dir, AITD1, hero=hero)
    start_game(game, *AITD1.intro_start)
    return game, Floor(data_dir, game.current_floor)


def run_intro(data_dir, game, floor, ticks, on_modal=None):
    """Tick the cutscene, swapping Floor on floor changes like shell.run and
    auto-dismissing pictures. Returns (last_tick, floor, events)."""
    buf = InputBuffer()
    events = []
    t = -1
    for t in range(ticks):
        play_tick(game, floor, buf)
        if floor.number != game.current_floor:
            floor = Floor(data_dir, game.current_floor)
            events.append((t, "floor", game.current_floor, game.current_room))
        if game.mode.name != "PLAY":
            events.append((t, type(game.active_modal).__name__))
            if on_modal is not None and on_modal(game):
                break
            apply_reading_result(game, ReadingResult(True))
    return t, floor, events


def test_director_places_object_288_and_it_spawns(data_dir):
    game, floor = boot_intro(data_dir)
    # game.timer (game.py:604 game_step_tick) increments once per play_tick
    # call, so N calls leave game.timer == N. The director's reduced
    # LM_STAGE (life.cpp:620) places object 288 on floor 7 the tick
    # game.timer becomes 1596, and GenereActiveList spawns it later in that
    # same play_tick (mainLoop.cpp:249) -- 1596 calls, not 1597, land here.
    # One tick further, LIFE 537's own first opcode is LM_LIFE (life.cpp:1329,
    # life_ops.op_life) self-transitioning to life 538, so 1597 calls would
    # observe life 538 instead.
    run_intro(data_dir, game, floor, 1596)
    w = game.world_objects[288]
    assert (w.stage, w.room) == (7, 0)
    assert w.obj_index != -1 and game.actors[w.obj_index].life == 537
