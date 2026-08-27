# SPDX-License-Identifier: GPL-2.0-only
import struct

from PyAitD.engine.game import FloorStart, init_game
from PyAitD.engine.life import process_life
import pytest

pytestmark = pytest.mark.engine


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


def test_angle_sets(data_dir, profile):
    game = init_game(data_dir, profile, hero=0)
    a = _run(game, 74, 0x10, 0x20, 0x30, 11)
    assert (a.alpha, a.beta, a.gamma) == (0x10, 0x20, 0x30)


def test_life_and_life_mode(data_dir, profile):
    game = init_game(data_dir, profile, hero=0)
    a = _run(game, 24, 1, 31, 5, 11)
    assert a.life_mode == 1
    assert a.life == 5


def test_move_init_track(data_dir, profile):
    game = init_game(data_dir, profile, hero=0)
    a = _run(game, 15, 3, 7, 11)
    assert a.track_mode == 3
    assert a.track_number == 7
    assert a.position_in_track == 0
    assert a.mark == -1


def test_c_var_write(data_dir, profile):
    game = init_game(data_dir, profile, hero=0)
    _run(game, 60, 0, -1, 99, 11)  # LM_C_VAR idx 0, evalVar literal 99
    assert game.cvars[0] == 99


def test_found_flag_masked(data_dir, profile):
    game = init_game(data_dir, profile, hero=0)
    actor = next(i for i, a in enumerate(game.actors) if a.index_in_world != -1)
    widx = game.actors[actor].index_in_world
    game.world_objects[widx].found_flag = 0xFFFF
    _run(game, 49, 0x23, 11, actor=actor)  # LM_FOUND_FLAG 0x23
    assert game.world_objects[widx].found_flag == (0xFFFF & 0xE000) | 0x23


def test_delete_object(data_dir, profile):
    game = init_game(data_dir, profile, hero=0)
    actor = next(i for i, a in enumerate(game.actors) if a.index_in_world != -1)
    widx = game.actors[actor].index_in_world
    _run(game, 32, widx, 11, actor=actor)
    assert game.world_objects[widx].obj_index == -1
    assert game.actors[actor].index_in_world == -1


def test_stub_consumes_args(data_dir, profile):
    game = init_game(data_dir, profile, hero=0)
    a = _run(game, 43, 123, 65, 456, 11)  # RND_FREQ + SHAKING stubs, args consumed
    assert a.life == 0  # unchanged; no crash = args consumed correctly


def test_type_mask(data_dir, profile):
    game = init_game(data_dir, profile, hero=0)
    a = _run(game, 40, 0x0010, 11)  # LM_TYPE AF_MOVABLE
    assert a.object_type & 0x0010


def test_camera_param_via_cvar(data_dir, profile):
    game = init_game(data_dir, profile, hero=0)
    game.num_camera = 0
    _run(game, 60, 0, 0x1C, 11)  # LM_C_VAR idx 0, evalVar property 0x1B
    assert game.cvars[0] == game.camera_param(0)


def test_hero_stage_opcode_records_destination(data_dir, profile):
    game = init_game(data_dir, profile)
    hero_idx = game.current_camera_target_actor
    actor = _run(game, 47, 5, 4, -7800, -4010, -1000, 11, actor=hero_idx)
    assert game.floor_start == FloorStart(5, 4, -7800, -4010, -1000, 0)
    assert game.flag_change_etage == 1
    assert game.new_num_etage == 5
    assert (actor.stage, actor.room) == (5, 4)


def test_hit_fire_throw_arm_only_when_init_anim_accepts(data_dir, profile, monkeypatch):
    game = init_game(data_dir, profile)
    actor_idx = game.current_camera_target_actor
    actor = game.actors[actor_idx]

    accepted = iter((0, 1, 1, 1))
    calls = []
    monkeypatch.setattr(
        "PyAitD.games.aitd1.life_ops.init_anim",
        lambda current, anim, kind, nxt: calls.append((anim, kind, nxt)) or next(accepted),
    )

    _run(game, 16, 100, 2, 3, 40, -1, 10, 101, 11, actor=actor_idx)
    assert actor.anim_action_type == 0
    _run(game, 16, 100, 2, 3, 40, -1, 10, 101, 11, actor=actor_idx)
    assert (actor.anim_action_type, actor.anim_action_anim, actor.anim_action_frame) == (1, 100, 2)
    assert (actor.hot_point_id, actor.anim_action_param, actor.hit_force) == (3, 40, 10)

    _run(game, 53, 200, 4, 5, 60, 12, 201, 11, actor=actor_idx)
    assert (actor.anim_action_type, actor.hot_point_id, actor.hit_force) == (4, 5, 12)

    thrown_idx = 13
    gamma = game.world_objects[thrown_idx].gamma
    _run(game, 76, 300, 6, 7, thrown_idx, 0, 14, 301, 11, actor=actor_idx)
    assert (actor.anim_action_type, actor.anim_action_param) == (6, thrown_idx)
    assert game.world_objects[thrown_idx].gamma == gamma - 0x100
    assert game.world_objects[thrown_idx].found_flag & 0x1000
    assert calls == [(100, 0, 101), (100, 0, 101), (200, 2, 201), (300, 2, 301)]


def test_hit_rejected_by_init_anim_consumes_operands_and_leaves_state_alone(data_dir, profile, monkeypatch):
    game = init_game(data_dir, profile)
    actor_idx = game.current_camera_target_actor
    actor = game.actors[actor_idx]
    actor.anim_action_type = 99
    actor.anim_action_anim = 55
    actor.anim_action_frame = 66
    actor.anim_action_param = 77
    actor.hot_point_id = 88
    actor.hit_force = 44
    monkeypatch.setattr("PyAitD.games.aitd1.life_ops.init_anim", lambda *args: 0)

    # LM_END (11) placed immediately after the operands: if op_hit consumed
    # the wrong number of words, the VM would either misread a trailing
    # operand as the next opcode (raising, since it is not a valid index) or
    # read past the end of the packed script buffer (struct.error) — either
    # way process_life inside _run would blow up instead of returning quietly.
    result = _run(game, 16, 100, 2, 3, 40, -1, 10, 101, 11, actor=actor_idx)

    assert (result.anim_action_type, result.anim_action_anim, result.anim_action_frame) == (99, 55, 66)
    assert (result.anim_action_param, result.hot_point_id, result.hit_force) == (77, 88, 44)


def test_fire_rejected_by_init_anim_consumes_operands_and_leaves_state_alone(data_dir, profile, monkeypatch):
    game = init_game(data_dir, profile)
    actor_idx = game.current_camera_target_actor
    actor = game.actors[actor_idx]
    actor.anim_action_type = 99
    actor.anim_action_anim = 55
    actor.anim_action_frame = 66
    actor.anim_action_param = 77
    actor.hot_point_id = 88
    actor.hit_force = 44
    monkeypatch.setattr("PyAitD.games.aitd1.life_ops.init_anim", lambda *args: 0)

    result = _run(game, 53, 200, 4, 5, 60, 12, 201, 11, actor=actor_idx)

    assert (result.anim_action_type, result.anim_action_anim, result.anim_action_frame) == (99, 55, 66)
    assert (result.anim_action_param, result.hot_point_id, result.hit_force) == (77, 88, 44)


def test_throw_rejected_by_init_anim_consumes_operands_and_leaves_state_alone(data_dir, profile, monkeypatch):
    game = init_game(data_dir, profile)
    actor_idx = game.current_camera_target_actor
    actor = game.actors[actor_idx]
    actor.anim_action_type = 99
    actor.anim_action_anim = 55
    actor.anim_action_frame = 66
    actor.anim_action_param = 77
    actor.hot_point_id = 88
    actor.hit_force = 44
    monkeypatch.setattr("PyAitD.games.aitd1.life_ops.init_anim", lambda *args: 0)

    thrown_idx = 13
    world = game.world_objects[thrown_idx]
    gamma = world.gamma
    found_flag = world.found_flag

    result = _run(game, 76, 300, 6, 7, thrown_idx, 0, 14, 301, 11, actor=actor_idx)

    assert (result.anim_action_type, result.anim_action_anim, result.anim_action_frame) == (99, 55, 66)
    assert (result.anim_action_param, result.hot_point_id, result.hit_force) == (77, 88, 44)
    assert world.gamma == gamma
    assert world.found_flag == found_flag


def test_reduced_stage_onto_the_current_floor_requests_a_spawn(data_dir, profile):
    # FITD regenerates the active list every frame (mainLoop.cpp:249,
    # GenereActiveList main.cpp:1990), so a world object moved onto the
    # current floor by the reduced LM_STAGE (life.cpp:620) spawns next frame.
    # This port gates the scan on flag_genere_aff_list: the reduced op must
    # raise it.
    from types import SimpleNamespace
    from PyAitD.games.aitd1.life_reduced import reduced_dispatch
    game = init_game(data_dir, profile, hero=0)
    game.flag_genere_aff_list = 0
    vm = SimpleNamespace(game=game, script=struct.pack("<5h", 0, 2, 10, 20, 30), pc=0)
    reduced_dispatch(vm, 47, 288)
    w = game.world_objects[288]
    assert (w.stage, w.room, w.x, w.y, w.z) == (0, 2, 10, 20, 30)
    assert game.flag_genere_aff_list == 1
    game.flag_genere_aff_list = 0
    vm = SimpleNamespace(game=game, script=struct.pack("<5h", 5, 0, 0, 0, 0), pc=0)
    reduced_dispatch(vm, 47, 288)
    assert game.flag_genere_aff_list == 0    # another floor: no request
