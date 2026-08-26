# SPDX-License-Identifier: GPL-2.0-only
import struct

from PyAitD.engine.effects import AddMessage, BeginTake, ReadText, ShowFound, ShowPicture
from PyAitD.engine.game import init_game
from PyAitD.engine.life import process_life
from PyAitD.games.aitd1.profile import AITD1
import pytest

pytestmark = pytest.mark.engine


class Scripts:
    def __init__(self, script):
        self.script = script

    def life(self, index):
        return self.script


def run(game, *words):
    game.assets = Scripts(struct.pack(f"<{len(words)}h", *words))
    return process_life(game, 0, 0)


def test_message_effect_is_immediate_and_script_finishes(data_dir):
    game = init_game(data_dir, AITD1)
    assert run(game, 17, 100, 18, 101, 999, 12) is None
    assert list(game.immediate_effects) == [AddMessage(100), AddMessage(101)]


def test_found_read_and_picture_suspend_at_next_opcode(data_dir):
    game = init_game(data_dir, AITD1)
    game.timer = 300
    frame = run(game, 30, 44, 20, 1, 12)
    assert game.active_modal == ShowFound(44, False)
    assert frame.pc == 4

    game.close_modal()
    game.life_stack.clear()
    frame = run(game, 35, 2, 3, 77, 20, 1, 12)
    assert game.active_modal == ReadText(4, 2)
    assert frame.pc == 8

    game.close_modal()
    frame = run(game, 78, 10, 120, 6, 20, 1, 12)
    assert game.active_modal == ShowPicture(10, 120, 6)
    assert frame.pc == 8


def test_found_metadata_preserves_high_flag_bits(data_dir):
    game = init_game(data_dir, AITD1)
    world_idx = game.actors[0].index_in_world
    world = game.world_objects[world_idx]
    world.found_flag = 0xE000
    run(game, 48, 222, 49, 0x35, 50, 7, 55, 19, 67, 4, 12)
    assert (world.found_name, world.found_flag, world.found_life) == (222, 0xE035, 7)
    assert (world.found_body, world.position_in_track) == (19, 4)
