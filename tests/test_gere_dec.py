# SPDX-License-Identifier: GPL-2.0-only
from types import SimpleNamespace

from PyAitD.engine.data.formats import Zone
from PyAitD.engine.script.interaction import gere_dec
import pytest

pytestmark = pytest.mark.engine


def room(wx, wy, wz, zones=()):
    return SimpleNamespace(world_x=wx, world_y=wy, world_z=wz, sce_zones=list(zones))


def test_room_zone_rebases_room_coordinates_and_requests_camera_change(monkeypatch, data_dir, profile):
    from PyAitD.engine.script.game import init_game
    game = init_game(data_dir, profile)
    actor_idx = game.current_camera_target_actor
    actor = game.actors[actor_idx]
    actor.room = 0
    actor.room_x = actor.room_y = actor.room_z = 0
    actor.step_x = actor.step_y = actor.step_z = 0
    actor.zv = [-1, 1, -1, 1, -1, 1]
    zones = [Zone(-2, 2, -2, 2, -2, 2, 0, 1)]
    monkeypatch.setattr(game, "rooms_of_floor", lambda floor: [room(0, 0, 0, zones), room(2, 1, -3)])
    gere_dec(game, actor_idx)
    assert actor.room == 1
    assert (actor.room_x, actor.room_y, actor.room_z) == (-20, 10, -30)
    assert actor.zv == [-21, -19, 9, 11, -31, -29]
    assert (game.flag_change_salle, game.new_num_salle) == (1, 1)


def test_scenario_and_floor_life_zones_write_fitd_fields(monkeypatch, data_dir, profile):
    from PyAitD.engine.script.game import init_game
    game = init_game(data_dir, profile)
    actor = game.actors[0]
    actor.room = 0
    actor.room_x = actor.room_y = actor.room_z = 0
    actor.step_x = actor.step_y = actor.step_z = 0
    actor.zv = [-1, 1, -1, 1, -1, 1]
    world = game.world_objects[actor.index_in_world]
    world.floor_life = 55
    monkeypatch.setattr(game, "rooms_of_floor", lambda floor: [room(0, 0, 0, [Zone(-2, 2, -2, 2, -2, 2, 9, 44)])])
    gere_dec(game, 0)
    assert actor.hard_dec == 44
    monkeypatch.setattr(game, "rooms_of_floor", lambda floor: [room(0, 0, 0, [Zone(-2, 2, -2, 2, -2, 2, 10, 66)])])
    gere_dec(game, 0)
    assert (actor.life, actor.hard_dec) == (55, 66)
