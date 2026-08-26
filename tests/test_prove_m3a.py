# SPDX-License-Identifier: GPL-2.0-only
import os
import pathlib

# Headless boot: no window in CI — SDL dummy drivers before pygame init.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from PyAitD.engine.assets import Assets
from PyAitD.engine.formats import parse_defines, parse_objets, parse_priority, parse_vars


def test_all_scripts_fetch(data_dir):
    assets = Assets(data_dir)
    assert assets.num_lifes == 563
    for i in range(assets.num_lifes):
        raw = assets.life(i)
        assert len(raw) % 2 == 0  # s16 stream
        assert len(raw) >= 2


def test_all_tracks_fetch(data_dir):
    assets = Assets(data_dir)
    assert assets.num_tracks == 45
    for i in range(assets.num_tracks):
        assert len(assets.track(i)) >= 2


def test_all_tables_parse(data_dir):
    d = pathlib.Path(data_dir)
    assert len(parse_objets((d / "OBJETS.ITD").read_bytes())) == 292
    assert len(parse_vars((d / "VARS.ITD").read_bytes())) == 207
    assert len(parse_defines((d / "DEFINES.ITD").read_bytes())) == 45
    assert len(parse_priority((d / "PRIORITY.ITD").read_bytes())) == 50


def test_headless_boot_ticks(data_dir):
    # Headless 60-tick PlayWorld boot with opcode trace, through the same
    # play_tick the game runs — playworld is pygame/GL-free, so CI needs no
    # window. Fails (not skips) if boot breaks or the intro produces no trace.
    from PyAitD.engine.floor import Floor
    from PyAitD.engine.game import init_game
    from PyAitD.engine.life import Trace
    from PyAitD.engine.playworld import play_tick
    from PyAitD.app.ui import InputBuffer

    trace_path = "/tmp/m3a_trace.log"
    game = init_game(data_dir, hero=0)
    game.trace = Trace(trace_path)
    floor = Floor(data_dir, game.current_floor)
    buf = InputBuffer()
    for tick in range(60):
        play_tick(game, floor, buf)
    game.trace.close()
    assert game.flag_game_over == 0
    assert pathlib.Path(trace_path).stat().st_size > 0
