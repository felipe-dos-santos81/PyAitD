# SPDX-License-Identifier: GPL-2.0-only
"""PlayWorld is the simulation tick, importable without pygame or the Renderer."""
import subprocess
import sys

from maitd.floor import Floor
from maitd.game import init_game
from maitd.playworld import play_tick
from maitd.ui import InputBuffer

# Runs in a fresh interpreter: pytest (and this module, via InputBuffer) has
# pygame loaded in-process, so sys.modules is only meaningful out-of-process.
# A static import walk cannot substitute — it reports pygame reachable through
# interaction.apply_found_result's deferred `from maitd.ui import FoundResult`.
_PURITY_PROBE = """
import sys, maitd.playworld
# the layer rule, then the third-party names a direct import would pull in
leaked = {"maitd.ui", "maitd.render", "pygame", "moderngl", "OpenGL"} & sys.modules.keys()
sys.exit(", ".join(sorted(leaked)) or None)
"""


def test_playworld_does_not_import_the_presentation_layer():
    out = subprocess.run([sys.executable, "-c", _PURITY_PROBE], capture_output=True, text=True)
    assert out.returncode == 0, (
        f"maitd.playworld pulled in {out.stderr.strip()} — the tick must stay "
        f"importable without the presentation layer so it can run headless"
    )


def test_play_tick_advances_the_world_without_a_display(data_dir):
    # No Renderer, no display, and no SDL_VIDEODRIVER needed. Constructing the
    # InputBuffer still imports pygame: it is a pygame-free dataclass that lives
    # in ui.py, whose module scope evaluates pygame.K_* and pygame.Rect.
    game = init_game(data_dir, hero=0)
    floor = Floor(data_dir, game.current_floor)
    buf = InputBuffer()
    start = game.timer
    for _ in range(60):
        play_tick(game, floor, buf)
    assert game.timer > start
    assert game.flag_game_over == 0
