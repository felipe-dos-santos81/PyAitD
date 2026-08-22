# SPDX-License-Identifier: GPL-2.0-only
import struct

from maitd.effects import AfterLife, LifeFrame, ReadText
from maitd.game import init_game
from maitd.interaction import resume_life, run_life


class Scripts:
    def __init__(self, scripts):
        self.scripts = scripts

    def life(self, index):
        return self.scripts[index]


def words(*values):
    # 0x8000-flagged opcodes don't fit 'h': re-sign so they pack as intended
    return struct.pack(f"<{len(values)}h", *[v - 0x10000 if v >= 0x8000 else v for v in values])


def test_modal_suspends_after_all_read_operands_and_resumes_once(data_dir):
    game = init_game(data_dir)
    # LM_READ 35 consumes kind, entry, and the AITD1 extra word; LM_INC 20; LM_END 12.
    game.assets = Scripts({7: words(35, 1, 4, 99, 20, 6, 12)})
    game.vars[6] = 0
    assert run_life(game, LifeFrame(0, 7)) is False
    assert game.active_modal == ReadText(text_index=5, kind=1)
    assert game.life_stack[-1].pc == 8
    assert game.vars[6] == 0

    game.close_modal()
    assert resume_life(game) is True
    assert game.vars[6] == 1
    assert game.life_stack == []


def test_actor_switch_restores_owner_before_suspension(data_dir):
    game = init_game(data_dir)
    target_world = game.actors[0].index_in_world
    game.assets = Scripts({2: words(0x8000 | 35, target_world, 0, 0, 0, 12)})
    assert run_life(game, LifeFrame(1, 2)) is False
    assert game.life_stack[-1].owner_idx == 1
    assert game.life_stack[-1].pc == 10


def test_resume_keeps_parent_below_nested_frame(data_dir):
    game = init_game(data_dir)
    game.life_stack = [LifeFrame(2, 10, pc=14)]
    game.life_stack.append(LifeFrame(3, 11, pc=8, after=AfterLife.FINISH_TAKE, subject_idx=9))
    assert [frame.life_num for frame in game.life_stack] == [10, 11]
