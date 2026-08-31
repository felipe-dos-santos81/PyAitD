# SPDX-License-Identifier: GPL-2.0-only
"""M4a2 task 1: the gameplay RNG lives on the Game, so a save can snapshot it
and a restored game draws the identical stream (engine/eval_var.py 0x1C)."""
import random
import struct

import pytest

from PyAitD.engine.script.eval_var import eval_var
from PyAitD.engine.script.game import init_game
from PyAitD.engine.script.life import VM

pytestmark = pytest.mark.engine


def _vm(game, *words):
    script = struct.pack(f"<{len(words)}H", *(w & 0xFFFF for w in words))
    return VM(script, game, game.current_camera_target_actor)


def _draw(game, n, count):
    return [eval_var(_vm(game, 0x1C + 1, n)) for _ in range(count)]


def test_eval_var_random_reads_the_game_rng_not_the_module_global(data_dir, profile):
    game = init_game(data_dir, profile, hero=0)
    game.rng.seed(20260830)
    shadow = random.Random(20260830)
    expected = [shadow.randrange(7) for _ in range(10)]
    got = []
    for i in range(10):
        random.seed(i)  # perturb the module-global stream between draws
        got.append(eval_var(_vm(game, 0x1C + 1, 7)))
    assert got == expected


def test_two_games_seeded_alike_draw_alike(data_dir, profile):
    a = init_game(data_dir, profile, hero=0)
    b = init_game(data_dir, profile, hero=1)
    a.rng.seed(99)
    b.rng.seed(99)
    assert _draw(a, 1000, 16) == _draw(b, 1000, 16)


def test_rng_state_is_restorable(data_dir, profile):
    game = init_game(data_dir, profile, hero=0)
    game.rng.seed(7)
    state = game.rng.getstate()
    first = _draw(game, 500, 8)
    game.rng.setstate(state)
    assert _draw(game, 500, 8) == first
