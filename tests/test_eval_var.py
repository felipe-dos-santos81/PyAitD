# SPDX-License-Identifier: GPL-2.0-only
import struct

import pytest

from PyAitD.engine.eval_var import eval_var
from PyAitD.engine.game import init_game
from PyAitD.engine.life import VM
from PyAitD.games.aitd1.profile import AITD1

pytestmark = pytest.mark.engine


def _vm(game, *words):
    # pack as u16 bit patterns; read_s16 sign-extends (tags like 0x8020 don't fit '<h')
    script = struct.pack(f"<{len(words)}H", *(w & 0xFFFF for w in words))
    return VM(script, game, game.current_camera_target_actor)


def test_literal(data_dir):
    game = init_game(data_dir, AITD1, hero=0)
    vm = _vm(game, -1, 1234)
    assert eval_var(vm) == 1234


def test_script_var(data_dir):
    game = init_game(data_dir, AITD1, hero=0)
    game.vars[3] = 77
    vm = _vm(game, 0, 3)
    assert eval_var(vm) == 77


def test_actor_property(data_dir):
    game = init_game(data_dir, AITD1, hero=0)
    owner = game.current_camera_target_actor
    game.actors[owner].beta = 0x2A0
    vm = _vm(game, 0x17 + 1)  # tag = code+1, beta
    assert eval_var(vm) == 0x2A0


def test_other_object_property(data_dir):
    game = init_game(data_dir, AITD1, hero=0)
    spawned = next(i for i, a in enumerate(game.actors) if a.index_in_world != -1)
    widx = game.actors[spawned].index_in_world
    game.actors[spawned].life = 42
    vm = _vm(game, 0x8000 | (0x1F + 1), widx)  # life of other object
    assert eval_var(vm) == 42


def test_world_idx_out_of_range_raises(data_dir):
    game = init_game(data_dir, AITD1, hero=0)
    vm = _vm(game, 0x8000 | (0x1F + 1), 9999)
    with pytest.raises(ValueError):
        eval_var(vm)


def test_other_object_not_in_floor_supports_only_fitd_raw_tags(data_dir):
    game = init_game(data_dir, AITD1, hero=0)
    widx = next(i for i, w in enumerate(game.world_objects) if w.obj_index == -1)
    world = game.world_objects[widx]
    world.room = 3
    world.stage = 5

    assert eval_var(_vm(game, 0x801F, widx)) == 3
    assert eval_var(_vm(game, 0x8026, widx)) == 5

    with pytest.raises(ValueError, match=r"raw tag 0x0020.*FITD asserts"):
        eval_var(_vm(game, 0x8020, widx))


def test_nested_eval_var_found_flag(data_dir):
    game = init_game(data_dir, AITD1, hero=0)
    widx = next(i for i, w in enumerate(game.world_objects) if w.found_flag & 0x8000 == 0)
    game.world_objects[widx].found_flag |= 0x8000
    vm = _vm(game, 0x10 + 1, -1, widx)  # found test: +1 nested evalVar (literal widx)
    assert eval_var(vm) == 1


def test_cvar_index(data_dir):
    game = init_game(data_dir, AITD1, hero=0)
    vm = _vm(game, 0x24 + 1, 2)  # CVars[2] = MAX_WEIGHT_LOADABLE = 700
    assert eval_var(vm) == 700


def test_rand_range(data_dir):
    game = init_game(data_dir, AITD1, hero=0)
    vm = _vm(game, 0x1C + 1, 5)
    assert 0 <= eval_var(vm) < 5


def test_unknown_code_raises(data_dir):
    game = init_game(data_dir, AITD1, hero=0)
    vm = _vm(game, 0x27 + 1)
    with pytest.raises(ValueError):
        eval_var(vm)


def _spawned(data_dir):
    game = init_game(data_dir, AITD1, hero=0)
    spawned = next(i for i, a in enumerate(game.actors) if a.index_in_world != -1)
    return game, spawned


def test_col_world_idx(data_dir):
    game, spawned = _spawned(data_dir)
    owner = game.current_camera_target_actor
    game.actors[owner].col[0] = spawned
    vm = _vm(game, 0x00 + 1)
    assert eval_var(vm) == game.actors[spawned].index_in_world
    game.actors[owner].col[0] = -1
    vm = _vm(game, 0x00 + 1)
    assert eval_var(vm) == -1


def test_hit_world_idx(data_dir):
    game, spawned = _spawned(data_dir)
    owner = game.current_camera_target_actor
    game.actors[owner].hit = spawned
    vm = _vm(game, 0x03 + 1)
    assert eval_var(vm) == game.actors[spawned].index_in_world
    game.actors[owner].hit = -1
    vm = _vm(game, 0x03 + 1)
    assert eval_var(vm) == -1


def test_hit_by_world_idx(data_dir):
    # FITD evalVar.cpp case 0x4: HIT_BY -1 → -1, else ListObjets[HIT_BY].indexInWorld
    game, spawned = _spawned(data_dir)
    owner = game.current_camera_target_actor
    game.actors[owner].hit_by = spawned
    vm = _vm(game, 0x04 + 1)
    assert eval_var(vm) == game.actors[spawned].index_in_world
    game.actors[owner].hit_by = -1
    vm = _vm(game, 0x04 + 1)
    assert eval_var(vm) == -1


def test_col_by_world_idx(data_dir):
    game, spawned = _spawned(data_dir)
    owner = game.current_camera_target_actor
    game.actors[owner].col_by = spawned
    vm = _vm(game, 0x0F + 1)
    assert eval_var(vm) == game.actors[spawned].index_in_world
    game.actors[owner].col_by = -1
    vm = _vm(game, 0x0F + 1)
    assert eval_var(vm) == -1


def test_col_or_col_by_world_idx(data_dir):
    game, spawned = _spawned(data_dir)
    owner = game.current_camera_target_actor
    game.actors[owner].col[0] = spawned
    vm = _vm(game, 0x15 + 1)
    assert eval_var(vm) == game.actors[spawned].index_in_world
    game.actors[owner].col[0] = -1
    game.actors[owner].col_by = spawned
    vm = _vm(game, 0x15 + 1)
    assert eval_var(vm) == game.actors[spawned].index_in_world
    game.actors[owner].col_by = -1
    vm = _vm(game, 0x15 + 1)
    assert eval_var(vm) == -1


def test_dist_3d_manhattan(data_dir):
    game, spawned = _spawned(data_dir)
    widx = game.actors[spawned].index_in_world
    a = game.actors[game.current_camera_target_actor]
    b = game.actors[spawned]
    expected = (
        abs(a.world_x - b.world_x)
        + abs(a.world_y - b.world_y)
        + abs(a.world_z - b.world_z)
    )
    vm = _vm(game, 0x0E + 1, widx)
    assert eval_var(vm) == expected


def test_dist_not_in_floor(data_dir):
    game = init_game(data_dir, AITD1, hero=0)
    widx = next(i for i, w in enumerate(game.world_objects) if w.obj_index == -1)
    vm = _vm(game, 0x0E + 1, widx)
    assert eval_var(vm) == 32000


def _posrel_game(data_dir):
    game, spawned = _spawned(data_dir)
    owner = game.current_camera_target_actor
    a, b = game.actors[owner], game.actors[spawned]
    a.room = b.room  # same room: no AdjustZV
    a.beta = 0
    b.zv = [0, 10, -100, 100, 0, 10]  # centerX=5, centerZ=5
    return game, a, b


@pytest.mark.parametrize(
    "zv,expected",
    [
        ([0, 4, -100, 100, 0, 10], 4),    # Z overlap, right of center → counter 4
        ([6, 20, -100, 100, 0, 10], 8),   # Z overlap, left of center → counter 6
        ([0, 20, -100, 100, 0, 4], 1),    # Z above, X overlap → counter 5
        ([0, 20, -100, 100, 0, 10], 0),   # straddles center → 0
        ([20, 30, -100, 100, 0, 10], 8),  # Z overlap, right of center → counter 6
        ([0, 20, -100, 100, 6, 20], 2),   # Z below: falls through → table[counter]
    ],
)
def test_posrel_directions(data_dir, zv, expected):
    game, a, b = _posrel_game(data_dir)
    a.zv = list(zv)
    widx = b.index_in_world
    vm = _vm(game, 0x12 + 1, widx)
    assert eval_var(vm) == expected


@pytest.mark.parametrize(
    "beta,zv,expected",
    [
        (0x100, [0, 4, -100, 100, 0, 10], 2),   # counter 2 + 1
        (0x200, [6, 20, -100, 100, 0, 10], 4),  # counter 1 + 3
        (0x300, [0, 20, -100, 100, 0, 4], 8),   # counter 0 + 2
    ],
)
def test_posrel_beta_quadrants(data_dir, beta, zv, expected):
    game, a, b = _posrel_game(data_dir)
    a.beta = beta
    a.zv = list(zv)
    widx = b.index_in_world
    vm = _vm(game, 0x12 + 1, widx)
    assert eval_var(vm) == expected


def test_posrel_not_in_floor(data_dir):
    game = init_game(data_dir, AITD1, hero=0)
    widx = next(i for i, w in enumerate(game.world_objects) if w.obj_index == -1)
    vm = _vm(game, 0x12 + 1, widx)
    assert eval_var(vm) == 0


def test_adjust_zv_room_shift(data_dir):
    from PyAitD.engine.eval_var import _adjust_zv

    game = init_game(data_dir, AITD1, hero=0)
    rooms = game.rooms_of_floor(game.current_floor)
    if len(rooms) < 2:
        pytest.skip("floor has a single room")
    src, dst = 0, 1
    zv = [1, 2, 3, 4, 5, 6]
    _adjust_zv(game, zv, src, dst)
    xdif = 10 * (rooms[dst].world_x - rooms[src].world_x)
    ydif = 10 * (rooms[dst].world_y - rooms[src].world_y)
    zdif = 10 * (rooms[dst].world_z - rooms[src].world_z)
    assert zv == [1 - xdif, 2 - xdif, 3 + ydif, 4 + ydif, 5 + zdif, 6 + zdif]
