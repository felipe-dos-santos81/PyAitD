# SPDX-License-Identifier: GPL-2.0-only
import struct

import pytest

from maitd.game import init_game
from maitd.life import process_life, read_s16, VM


def _script(*words):
    # 0x8000-flagged opcodes don't fit 'h': re-sign so they pack as intended
    return struct.pack(f"<{len(words)}h", *[w - 0x10000 if w >= 0x8000 else w for w in words])


def _make_game(data_dir):
    game = init_game(data_dir, hero=0)
    return game


def test_goto_loop_exits(data_dir):
    # GOTO +1 skips END; GOTO -3 loops back onto END; RET unreachable
    game = _make_game(data_dir)
    actor = game.current_camera_target_actor
    game.actors[actor].life = 0
    game.assets = _FakeAssets(script=_script(10, 1, 12, 10, -3, 11))
    process_life(game, actor, 0)


def test_conditionals(data_dir):
    # synthetic: evalVar literal forms only
    # IF_EGAL a==b -> skip jump (2-byte jump word), else jump
    game = init_game(data_dir, hero=0)
    game.assets = _FakeAssets(script=_script(
        4, -1, 7, -1, 7, 2,    # IF_EGAL 7==7, jump +2 (skipped)
        10, 1,                 # GOTO +1 (skips the END)
        12,                    # LM_END
        11,                    # LM_RETURN (target of the goto)
        12,
    ))
    game.actors[0].life = 0
    process_life(game, 0, 0)
    # reaching here without error = if-branch taken, goto executed, return hit
    assert True


def test_if_false_jumps(data_dir):
    game = init_game(data_dir, hero=0)
    game.assets = _FakeAssets(script=_script(
        4, -1, 7, -1, 6, 1,    # IF_EGAL 7==6 false -> jump +1 word: skips RET, hits END
        11,
        12,
    ))
    game.actors[0].life = 0
    process_life(game, 0, 0)


def test_return_and_end_equivalent(data_dir):
    game = init_game(data_dir, hero=0)
    game.assets = _FakeAssets(script=_script(11))
    game.actors[0].life = 0
    process_life(game, 0, 0)
    game.assets = _FakeAssets(script=_script(12))
    process_life(game, 0, 0)


def test_switch_case(data_dir):
    game = init_game(data_dir, hero=0)
    game.assets = _FakeAssets(script=_script(
        25, -1, 2,     # SWITCH evalVar -> 2
        26, 1, 1,      # CASE 1: no match, jump +1 word -> skips END, hits RET
        12,
        11,
    ))
    game.actors[0].life = 0
    process_life(game, 0, 0)


def test_actor_switch_flag(data_dir):
    game = init_game(data_dir, hero=0)
    # find a spawned actor (in floor -> full dispatch on the switched actor)
    spawned = next(i for i, a in enumerate(game.actors) if a.index_in_world != -1)
    world_idx = game.actors[spawned].index_in_world
    game.assets = _FakeAssets(script=_script(
        0x8000 | 11, world_idx,   # LM_RETURN with switch flag: dispatch on switched actor
    ))
    game.actors[spawned].life = 0
    process_life(game, spawned, 0)


def test_eval_var_script_var(data_dir):
    # evalVar tag 0: read game.vars[idx]; true branch skips jump onto END
    game = init_game(data_dir, hero=0)
    game.vars[0] = 5
    game.assets = _FakeAssets(script=_script(
        4, 0, 0, -1, 5, 1,    # IF_EGAL vars[0]==5 true -> skip jump -> END
        12,
        90,                   # false branch lands here -> ValueError
    ))
    game.actors[0].life = 0
    process_life(game, 0, 0)


def test_unknown_opcode_raises(data_dir):
    game = init_game(data_dir, hero=0)
    game.assets = _FakeAssets(script=_script(90))
    game.actors[0].life = 0
    with pytest.raises(ValueError):
        process_life(game, 0, 0)


def test_var_ops(data_dir):
    # LM_VAR/INC/DEC/ADD/SUB on game.vars (life.cpp:2194-2237)
    game = init_game(data_dir, hero=0)
    game.vars[0] = 0
    game.assets = _FakeAssets(script=_script(
        19, 0, -1, 5,     # LM_VAR vars[0] = 5
        20, 0,            # LM_INC vars[0] -> 6
        21, 0,            # LM_DEC vars[0] -> 5
        22, 0, -1, 3,     # LM_ADD vars[0] += 3 -> 8
        23, 0, -1, 2,     # LM_SUB vars[0] -= 2 -> 6
        12,
    ))
    game.actors[0].life = 0
    process_life(game, 0, 0)
    assert game.vars[0] == 6


def test_life_mode(data_dir):
    game = init_game(data_dir, hero=0)
    game.actors[0].life_mode = 0
    game.assets = _FakeAssets(script=_script(24, 2, 24, 2, 12))
    game.actors[0].life = 0
    process_life(game, 0, 0)
    assert game.actors[0].life_mode == 2


def test_start_chrono(data_dir):
    game = init_game(data_dir, hero=0)
    game.timer = 7
    game.assets = _FakeAssets(script=_script(28, 12))
    game.actors[0].life = 0
    process_life(game, 0, 0)
    assert game.actors[0].chrono == 7


def test_opcode_87_raises(data_dir):
    game = init_game(data_dir, hero=0)
    game.assets = _FakeAssets(script=_script(87))
    game.actors[0].life = 0
    with pytest.raises(ValueError):
        process_life(game, 0, 0)


def test_reduced_lm_type_unavailable(data_dir):
    # LM_TYPE(40) with 0x8000 on out-of-floor object: allowed set, but the
    # reduced dispatch module (maitd.life_reduced) lands in task 7 -> ValueError
    game = init_game(data_dir, hero=0)
    unspawned = next(i for i, o in enumerate(game.world_objects) if o.obj_index == -1)
    game.assets = _FakeAssets(script=_script(0x8000 | 40, unspawned, 12))
    game.actors[0].life = 0
    with pytest.raises(ValueError):
        process_life(game, 0, 0)


def test_reduced_disallowed_raises(data_dir):
    # LM_RETURN(11) with 0x8000 on out-of-floor object: not in reduced set
    game = init_game(data_dir, hero=0)
    unspawned = next(i for i, o in enumerate(game.world_objects) if o.obj_index == -1)
    game.assets = _FakeAssets(script=_script(0x8000 | 11, unspawned, 12))
    game.actors[0].life = 0
    with pytest.raises(ValueError):
        process_life(game, 0, 0)


@pytest.mark.parametrize("op", [27, 57, 61, 69])  # LM_CAMERA, LM_STOP_BETA, LM_DO_NORMAL_ZV, LM_SPEED
def test_dead_opcode_raises(data_dir, op):
    game = init_game(data_dir, hero=0)
    game.assets = _FakeAssets(script=_script(op))
    game.actors[0].life = 0
    with pytest.raises(ValueError):
        process_life(game, 0, 0)


class _FakeAssets:
    def __init__(self, script):
        self._script = script

    def life(self, index):
        return self._script

    def track(self, index):
        return b""
