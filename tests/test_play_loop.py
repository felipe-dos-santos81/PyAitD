# SPDX-License-Identifier: GPL-2.0-only
from maitd.game import init_game
from maitd.life import life_gate


def test_life_gate(data_dir):
    game = init_game(data_dir, hero=0)
    a = game.actors[0]
    a.life, a.life_mode = -1, -1
    assert not life_gate(a)
    a.life, a.life_mode = 3, 0
    assert life_gate(a)
    a.life, a.life_mode = 3, -1
    assert not life_gate(a)
    a.life, a.life_mode = -1, 0
    assert not life_gate(a)


def test_poll_input_mapping(data_dir):
    # pygame not importable headless in all environments: test the pure mapping helper
    from maitd.game import joyd_from_keys
    assert joyd_from_keys(up=True) == 1
    assert joyd_from_keys(down=True) == 2
    assert joyd_from_keys(left=True) == 4
    assert joyd_from_keys(right=True) == 8
    assert joyd_from_keys(up=True, left=True) == 5
    assert joyd_from_keys() == 0
