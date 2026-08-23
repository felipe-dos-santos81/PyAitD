# SPDX-License-Identifier: GPL-2.0-only
import struct

from PyAitD.game import FloorStart, init_game
from PyAitD.life import process_life


class _FakeAssets:
    def __init__(self, script):
        self._script = script

    def life(self, index):
        return self._script

    def track(self, index):
        return b"\x02\x00"  # TL_END


def _run(game, *words, actor=None):
    if actor is None:
        actor = next(i for i, a in enumerate(game.actors) if a.index_in_world != -1)
    game.assets = _FakeAssets(struct.pack(f"<{len(words)}h", *words))
    game.actors[actor].life = 0
    process_life(game, actor, 0)
    return game.actors[actor]


def test_angle_sets(data_dir):
    game = init_game(data_dir, hero=0)
    a = _run(game, 74, 0x10, 0x20, 0x30, 11)
    assert (a.alpha, a.beta, a.gamma) == (0x10, 0x20, 0x30)


def test_life_and_life_mode(data_dir):
    game = init_game(data_dir, hero=0)
    a = _run(game, 24, 1, 31, 5, 11)
    assert a.life_mode == 1
    assert a.life == 5


def test_move_init_track(data_dir):
    game = init_game(data_dir, hero=0)
    a = _run(game, 15, 3, 7, 11)
    assert a.track_mode == 3
    assert a.track_number == 7
    assert a.position_in_track == 0
    assert a.mark == -1


def test_c_var_write(data_dir):
    game = init_game(data_dir, hero=0)
    _run(game, 60, 0, -1, 99, 11)  # LM_C_VAR idx 0, evalVar literal 99
    assert game.cvars[0] == 99


def test_found_flag_masked(data_dir):
    game = init_game(data_dir, hero=0)
    actor = next(i for i, a in enumerate(game.actors) if a.index_in_world != -1)
    widx = game.actors[actor].index_in_world
    game.world_objects[widx].found_flag = 0xFFFF
    _run(game, 49, 0x23, 11, actor=actor)  # LM_FOUND_FLAG 0x23
    assert game.world_objects[widx].found_flag == (0xFFFF & 0xE000) | 0x23


def test_delete_object(data_dir):
    game = init_game(data_dir, hero=0)
    actor = next(i for i, a in enumerate(game.actors) if a.index_in_world != -1)
    widx = game.actors[actor].index_in_world
    _run(game, 32, widx, 11, actor=actor)
    assert game.world_objects[widx].obj_index == -1
    assert game.actors[actor].index_in_world == -1


def test_stub_consumes_args(data_dir):
    game = init_game(data_dir, hero=0)
    a = _run(game, 43, 123, 65, 456, 11)  # RND_FREQ + SHAKING stubs, args consumed
    assert a.life == 0  # unchanged; no crash = args consumed correctly


def test_type_mask(data_dir):
    game = init_game(data_dir, hero=0)
    a = _run(game, 40, 0x0010, 11)  # LM_TYPE AF_MOVABLE
    assert a.object_type & 0x0010


def test_camera_param_via_cvar(data_dir):
    game = init_game(data_dir, hero=0)
    game.num_camera = 0
    _run(game, 60, 0, 0x1C, 11)  # LM_C_VAR idx 0, evalVar property 0x1B
    assert game.cvars[0] == game.camera_param(0)


def test_hero_stage_opcode_records_destination(data_dir):
    game = init_game(data_dir)
    hero_idx = game.current_camera_target_actor
    actor = _run(game, 47, 5, 4, -7800, -4010, -1000, 11, actor=hero_idx)
    assert game.floor_start == FloorStart(5, 4, -7800, -4010, -1000, 0)
    assert game.flag_change_etage == 1
    assert game.new_num_etage == 5
    assert (actor.stage, actor.room) == (5, 4)
