# SPDX-License-Identifier: GPL-2.0-only
import struct

import pytest

from maitd.eval_var import eval_var
from maitd.game import init_game
from maitd.life import VM


def _vm(game, *words):
    # pack as u16 bit patterns; read_s16 sign-extends (tags like 0x8020 don't fit '<h')
    script = struct.pack(f"<{len(words)}H", *(w & 0xFFFF for w in words))
    return VM(script, game, game.current_camera_target_actor)


def test_literal(data_dir):
    game = init_game(data_dir, hero=0)
    vm = _vm(game, -1, 1234)
    assert eval_var(vm) == 1234


def test_script_var(data_dir):
    game = init_game(data_dir, hero=0)
    game.vars[3] = 77
    vm = _vm(game, 0, 3)
    assert eval_var(vm) == 77


def test_actor_property(data_dir):
    game = init_game(data_dir, hero=0)
    owner = game.current_camera_target_actor
    game.actors[owner].beta = 0x2A0
    vm = _vm(game, 0x17 + 1)  # tag = code+1, beta
    assert eval_var(vm) == 0x2A0


def test_other_object_property(data_dir):
    game = init_game(data_dir, hero=0)
    spawned = next(i for i, a in enumerate(game.actors) if a.index_in_world != -1)
    widx = game.actors[spawned].index_in_world
    game.actors[spawned].life = 42
    vm = _vm(game, 0x8000 | (0x1F + 1), widx)  # life of other object
    assert eval_var(vm) == 42


def test_other_object_not_in_floor(data_dir):
    game = init_game(data_dir, hero=0)
    widx = next(i for i, w in enumerate(game.world_objects) if w.obj_index == -1)
    game.world_objects[widx].room = 3
    vm = _vm(game, 0x8000 | (0x1F + 1), widx)  # room allowed when not in floor
    assert eval_var(vm) == 3
    game.world_objects[widx].stage = 1
    vm = _vm(game, 0x8000 | (0x26 + 1), widx)  # stage allowed when not in floor
    assert eval_var(vm) == 1


def test_nested_eval_var_found_flag(data_dir):
    game = init_game(data_dir, hero=0)
    widx = next(i for i, w in enumerate(game.world_objects) if w.found_flag & 0x8000 == 0)
    game.world_objects[widx].found_flag |= 0x8000
    vm = _vm(game, 0x10 + 1, -1, widx)  # found test: +1 nested evalVar (literal widx)
    assert eval_var(vm) == 1


def test_cvar_index(data_dir):
    game = init_game(data_dir, hero=0)
    vm = _vm(game, 0x24 + 1, 2)  # CVars[2] = MAX_WEIGHT_LOADABLE = 700
    assert eval_var(vm) == 700


def test_rand_range(data_dir):
    game = init_game(data_dir, hero=0)
    vm = _vm(game, 0x1C + 1, 5)
    assert 0 <= eval_var(vm) < 5


def test_unknown_code_raises(data_dir):
    game = init_game(data_dir, hero=0)
    vm = _vm(game, 0x27 + 1)
    with pytest.raises(ValueError):
        eval_var(vm)
