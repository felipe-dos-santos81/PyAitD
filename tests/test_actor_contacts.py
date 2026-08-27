# SPDX-License-Identifier: GPL-2.0-only
from types import SimpleNamespace

from PyAitD.engine.actors import check_object_col
from PyAitD.engine.game import AF_FOUNDABLE, AF_MOVABLE, init_game
from PyAitD.engine.interaction import resolve_actor_contacts
import pytest

pytestmark = pytest.mark.engine


def live_actor(game, index, room, zv, flags=0, world_idx=0):
    actor = game.actors[index]
    actor.index_in_world = world_idx
    actor.room = room
    actor.zv = list(zv)
    actor.object_type = flags
    # spawn_stage_actors leaves real positions; isolate the contact scenario
    actor.world_x = actor.world_y = actor.world_z = 0
    actor.room_x = actor.room_y = actor.room_z = 0
    return actor


def test_check_object_col_adjusts_candidate_to_other_room(data_dir, profile, monkeypatch):
    game = init_game(data_dir, profile)
    for actor in game.actors:
        actor.index_in_world = -1
    live_actor(game, 0, 0, (0, 10, 0, 10, 0, 10), world_idx=1)
    live_actor(game, 1, 1, (-20, -10, 0, 10, 0, 10), world_idx=2)
    rooms = [SimpleNamespace(world_x=0, world_y=0, world_z=0), SimpleNamespace(world_x=2, world_y=0, world_z=0)]
    monkeypatch.setattr(game, "rooms_of_floor", lambda floor: rooms)
    assert check_object_col(game, 0, [0, 10, 0, 10, 0, 10]) == (1,)
    assert game.actors[0].col == [1, -1, -1]


def test_foundable_contact_opens_modal_without_blocking_step(data_dir, profile, monkeypatch):
    game = init_game(data_dir, profile)
    game.timer = 300
    for actor in game.actors:
        actor.index_in_world = -1
    mover = live_actor(game, 0, 0, (0, 10, 0, 10, 0, 10), world_idx=1)
    mover.track_mode = 1
    item = live_actor(game, 1, 0, (8, 18, 0, 10, 0, 10), AF_FOUNDABLE, world_idx=2)
    game.world_objects[2].position_in_track = 0
    monkeypatch.setattr(game, "rooms_of_floor", lambda floor: [SimpleNamespace(world_x=0, world_y=0, world_z=0, hard_cols=[])])
    zv, sx, sz = resolve_actor_contacts(game, 0, mover.zv, [8, 18, 0, 10, 0, 10], 8, 0)
    assert (sx, sz, zv) == (8, 0, [8, 18, 0, 10, 0, 10])
    assert item.col_by == 0
    assert game.active_modal.object_idx == 2


def test_movable_contact_pushes_when_destination_is_clear(data_dir, profile, monkeypatch):
    game = init_game(data_dir, profile)
    for actor in game.actors:
        actor.index_in_world = -1
    mover = live_actor(game, 0, 0, (0, 10, 0, 10, 0, 10), world_idx=1)
    pushed = live_actor(game, 1, 0, (8, 18, 0, 10, 0, 10), AF_MOVABLE, world_idx=2)
    monkeypatch.setattr(game, "rooms_of_floor", lambda floor: [SimpleNamespace(world_x=0, world_y=0, world_z=0, hard_cols=[])])
    resolve_actor_contacts(game, 0, mover.zv, [8, 18, 0, 10, 0, 10], 8, 0)
    assert pushed.zv == [16, 26, 0, 10, 0, 10]
    assert pushed.world_x == 8
    assert pushed.room_x == 8
