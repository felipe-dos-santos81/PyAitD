# SPDX-License-Identifier: GPL-2.0-only
import struct

import pytest

from PyAitD.engine.effects import NavDecision
from PyAitD.engine.formats import Zone
from PyAitD.engine.game import AF_TRIGGER, Actor, Game, init_game
from PyAitD.engine.tracks import (
    cap_objet, face_toward, get_room_link, init_deplacement, process_track,
)


def _actor():
    return Actor(index_in_world=0, room=0, room_x=0, room_y=0, room_z=0, life=0, life_mode=1)


def test_init_deplacement_track_mode(data_dir):
    game = init_game(data_dir, hero=0)
    a = _actor()
    init_deplacement(a, 3, 7)
    assert (a.track_mode, a.track_number, a.position_in_track, a.mark) == (3, 7, 0, -1)


def test_track_end_stops(data_dir):
    game = init_game(data_dir, hero=0)
    a = _actor()
    init_deplacement(a, 3, 0)
    a.speed = 4
    game.assets = _FakeAssets(track=struct.pack("<h", 2))  # TL_END
    process_track(game, a)
    assert a.speed == 0
    assert a.track_number == -1
    assert a.track_mode == 0


def test_track_walk_and_repeat(data_dir):
    game = init_game(data_dir, hero=0)
    a = _actor()
    init_deplacement(a, 3, 0)
    game.assets = _FakeAssets(track=struct.pack("<hh", 5, 3))  # TL_WALK, TL_REPEAT
    process_track(game, a)
    assert a.speed == 4
    assert a.position_in_track == 1
    process_track(game, a)
    assert a.position_in_track == 0


def test_track_init_coor_warps(data_dir):
    game = init_game(data_dir, hero=0)
    a = _actor()
    init_deplacement(a, 3, 0)
    game.assets = _FakeAssets(track=struct.pack("<hhhhh", 0, 0, 100, 50, 200))
    process_track(game, a)
    assert (a.room_x, a.room_y, a.room_z) == (100, 50, 200)
    assert a.position_in_track == 5
    assert a.speed == 0


def test_track_manual_forward(data_dir):
    game = init_game(data_dir, hero=0)
    a = _actor()
    init_deplacement(a, 1, 0)
    game.local_joyd = 1
    game.timer = 20  # past FITD's 10-tick cold-start window (lastTimeForward == 0)
    game.assets = _FakeAssets(track=b"")
    process_track(game, a)
    assert a.speed == 4
    game.local_joyd = 0
    process_track(game, a)
    assert a.speed == 3


def test_track_manual_backward(data_dir):
    game = init_game(data_dir, hero=0)
    a = _actor()
    init_deplacement(a, 1, 0)
    game.local_joyd = 2
    game.assets = _FakeAssets(track=b"")
    process_track(game, a)
    assert a.speed == -1


def test_track_run(data_dir):
    game = init_game(data_dir, hero=0)
    a = _actor()
    init_deplacement(a, 3, 0)
    game.assets = _FakeAssets(track=struct.pack("<h", 6))  # TL_RUN
    process_track(game, a)
    assert a.speed == 5
    assert a.position_in_track == 1


def test_track_goto_reached_advances(data_dir):
    game = init_game(data_dir, hero=0)
    a = _actor()
    init_deplacement(a, 3, 0)
    game.assets = _FakeAssets(track=struct.pack("<hhhh", 1, 0, 0, 0))  # TL_GOTO at current pos
    process_track(game, a)
    assert a.position_in_track == 4


def test_track_goto_3d_reached_advances(data_dir):
    game = init_game(data_dir, hero=0)
    a = _actor()
    init_deplacement(a, 3, 0)
    game.assets = _FakeAssets(track=struct.pack("<hhhhhh", 15, 0, 0, 0, 0, 0))
    process_track(game, a)
    assert a.position_in_track == 6


def test_track_set_angle_arrives(data_dir):
    game = init_game(data_dir, hero=0)
    a = _actor()
    init_deplacement(a, 3, 0)
    game.assets = _FakeAssets(track=struct.pack("<hh", 9, 0))  # TL_SET_ANGLE to 0
    process_track(game, a)
    assert a.beta == 0
    assert a.direction == 0
    assert a.position_in_track == 2


def test_track_flags_macros(data_dir):
    game = init_game(data_dir, hero=0)
    a = _actor()
    init_deplacement(a, 3, 0)
    game.assets = _FakeAssets(track=struct.pack("<hhhh", 10, 11, 13, 14))
    process_track(game, a)
    assert a.dyn_flags == 0
    process_track(game, a)
    assert a.dyn_flags == 1
    process_track(game, a)
    assert a.object_type & AF_TRIGGER == 0
    process_track(game, a)
    assert a.object_type & AF_TRIGGER == AF_TRIGGER
    assert a.position_in_track == 4


def test_track_memo_coor_and_angle(data_dir):
    game = init_game(data_dir, hero=0)
    a = _actor()
    init_deplacement(a, 3, 0)
    game.assets = _FakeAssets(track=struct.pack("<hhhhhhh", 16, 19, 1, 2, 3, 0, 0))
    process_track(game, a)
    obj = game.world_objects[0]
    assert (obj.x, obj.y, obj.z) == (a.room_x, a.room_y, a.room_z)
    assert a.position_in_track == 1
    process_track(game, a)
    assert (a.alpha, a.beta, a.gamma) == (1, 2, 3)
    assert a.direction == 0
    assert a.position_in_track == 5


def test_track_unknown_macros_raise(data_dir):
    game = init_game(data_dir, hero=0)
    for macro in (8, 12, 20):  # TL_BACK, TL_SET_DIST, TL_CLOSE: no case in FITD
        a = _actor()
        init_deplacement(a, 3, 0)
        game.assets = _FakeAssets(track=struct.pack("<h", macro))
        with pytest.raises(ValueError):
            process_track(game, a)


def test_track_follow_stops_when_target_not_in_floor(data_dir):
    game = init_game(data_dir, hero=0)
    a = _actor()
    init_deplacement(a, 2, 0)
    game.world_objects[0].obj_index = -1
    process_track(game, a)
    assert a.speed == 0
    assert a.direction == 0


def test_track_follow_walks_to_target(data_dir):
    game = init_game(data_dir, hero=0)
    a = _actor()
    init_deplacement(a, 2, 0)
    game.world_objects[0].obj_index = 5
    game.actors[5] = Actor(room=0, room_x=0, room_y=0, room_z=500)
    process_track(game, a)
    assert a.speed == 4
    assert a.direction == cap_objet(0, 0, a.beta, 0, 500)


class _FakeRoom:
    def __init__(self, hard_cols):
        self.hard_cols = hard_cols


class _FakeFloorGame:
    current_floor = 0

    def __init__(self, room):
        self._room = room

    def rooms_of_floor(self, floor_number):
        return [self._room]


def test_get_room_link_matches_target_room():
    other = Zone(0, 0, 0, 0, 0, 0, parameter=1, type=4)
    match = Zone(10, 20, 30, 40, 50, 60, parameter=2, type=4)
    game = _FakeFloorGame(_FakeRoom([other, match]))
    assert get_room_link(game, 0, 2) is match
    assert get_room_link(game, 0, 3) is match  # best (last) type-4 zone fallback


class _FakeAssets:
    def __init__(self, track=b""):
        self._track = track

    def life(self, index):
        return b""

    def track(self, index):
        return self._track


class _NavGame:
    def __init__(self, decision):
        self.nav_decision = decision
        self.timer = 0


def test_mouse_mode_walks_toward_the_decision_target():
    actor = Actor()
    actor.track_mode = 4
    actor.room_x = actor.room_z = 0
    actor.beta = 0
    game = _NavGame(NavDecision(joyd=1, target_x=0, target_z=9000,
                                advance=True, arrived=False))
    process_track(game, actor)
    assert actor.speed == 4, "an advancing follower walks"


def test_mouse_mode_decelerates_when_there_is_no_decision():
    actor = Actor()
    actor.track_mode = 4
    actor.speed = 4
    process_track(_NavGame(None), actor)
    assert actor.speed == 3, "speed ramps down exactly as manual mode does"


def test_mouse_mode_stops_dead_on_arrival():
    actor = Actor()
    actor.track_mode = 4
    actor.speed = 1
    game = _NavGame(NavDecision(joyd=0, target_x=0, target_z=0,
                                advance=False, arrived=True))
    process_track(game, actor)
    assert actor.speed == 0
    assert actor.direction == 0
    assert actor.rotate.num_steps == 0


def test_manual_mode_is_untouched_by_the_new_branch():
    # mode 1 must remain byte-for-byte the tank behaviour it has always been
    actor = Actor()
    actor.track_mode = 1
    actor.speed = 0
    game = _NavGame(None)
    game.local_joyd = 1
    game.timer = 100
    game._last_time_forward = 0
    process_track(game, actor)
    assert actor.speed == 4


@pytest.mark.parametrize(
    "target",
    ((0, 1000), (1000, 0), (0, -1000), (-1000, 0),
     (700, 700), (700, -700), (-700, 700), (-700, -700),
     (123, 987), (-821, 349)),
)
def test_face_toward_converges_from_every_beta(target):
    for beta in range(1024):
        actor = _actor()
        actor.beta = beta
        actor.rotate.num_steps = 60
        face_toward(actor, *target)
        assert cap_objet(
            actor.room_x + actor.step_x,
            actor.room_z + actor.step_z,
            actor.beta,
            *target,
        ) == 0
        assert actor.direction == 0
        assert actor.rotate.num_steps == 0


def test_face_toward_raises_at_its_bound(monkeypatch):
    actor = _actor()
    monkeypatch.setattr("PyAitD.engine.tracks.cap_objet", lambda *args: 1)
    with pytest.raises(
        RuntimeError,
        match=r"beta=0 target=\(100, 200\) did not converge in 256 steps",
    ):
        face_toward(actor, 100, 200)
