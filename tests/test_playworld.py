# SPDX-License-Identifier: GPL-2.0-only
"""PlayWorld is the simulation tick, reachable without a window.

The point of the module is that a 50 Hz logic step can be advanced headlessly,
so the import-purity check below is the load-bearing test: if someone reaches
for pygame or the Renderer from inside the tick, this fails.
"""
import subprocess
import sys

from maitd.floor import Floor
from maitd.game import init_game
from maitd.playworld import TICK_MS, play_tick
from maitd.ui import InputBuffer

# `python -c` in a fresh interpreter: pytest has already imported pygame by the
# time any in-process assertion could run, so sys.modules is only meaningful here.
_PURITY_PROBE = """
import sys
import maitd.playworld
leaked = sorted(m for m in ("pygame", "moderngl", "OpenGL") if m in sys.modules)
print("LEAKED:" + ",".join(leaked))  # marked: importing pygame prints its own banner
"""


def test_playworld_imports_without_pygame_or_gl():
    out = subprocess.run(
        [sys.executable, "-c", _PURITY_PROBE],
        capture_output=True, text=True, check=True,
    )
    marker = next(l for l in out.stdout.splitlines() if l.startswith("LEAKED:"))
    leaked = marker[len("LEAKED:"):]
    assert leaked == "", (
        f"maitd.playworld pulled in {leaked} — the tick must stay free of "
        f"pygame/GL so it can run headless"
    )


def test_tick_rate_is_50hz():
    assert TICK_MS == 20


def test_play_tick_advances_the_world_headless(data_dir):
    # No Renderer, no display, no SDL_VIDEODRIVER: just the simulation.
    game = init_game(data_dir, hero=0)
    floor = Floor(data_dir, game.current_floor)
    buf = InputBuffer()
    start = game.timer
    for _ in range(60):
        play_tick(game, floor, buf)
    assert game.timer > start
    assert game.flag_game_over == 0
