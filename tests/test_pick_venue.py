# SPDX-License-Identifier: GPL-2.0-only
"""Click-to-walk at the floor-5 combat venue (room 4, camera slot 5).

The venue's visible floor sits in L-shaped cover polygons whose world-bbox
extreme corners snap to the same vertex, so _quad_of's corner heuristic
rejected them and pick_floor_any_room resolved almost every on-screen floor
pixel — including the hero's own feet — to None ("blocked").
"""
import PyAitD.app.shell as main
from PyAitD.engine.data.floor import Floor
from PyAitD.engine.script.game import init_game, relocate_actor
from PyAitD.engine.nav.picking import _camera_state_global, pick_floor_any_room, project_floor_point
from PyAitD.engine.script.playworld import play_tick
from PyAitD.games.aitd1.scenario import enter_mouse_combat_fixture
from PyAitD.app.ui import InputBuffer
import pytest

pytestmark = pytest.mark.engine


def _settled_venue(data_dir, profile):
    game = init_game(data_dir, profile)
    enter_mouse_combat_fixture(game)
    hero_idx = game.current_camera_target_actor
    # This floor-picking regression owns camera slot 5 independently of the
    # manual mouse-combat fixture's now-visible camera-0 lane.
    relocate_actor(game, hero_idx, 5, 4, -7400, -4010, -1000)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    play_tick(game, floor, InputBuffer())  # one tick: the camera settles
    return game, floor


def test_click_on_the_heros_feet_picks_a_floor_point(data_dir, profile):
    game, floor = _settled_venue(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    assert hero.room == 4 and game.num_camera == 5
    state = _camera_state_global(
        floor, hero.room, floor.rooms[hero.room].camera_indices[game.num_camera],
    )
    feet = project_floor_point(state, hero.room_x, hero.world_y, hero.room_z)
    assert feet is not None, "fixture: the hero's feet must be on screen"
    click = (int(round(feet[0])), int(round(feet[1])))
    picked = pick_floor_any_room(click, floor, hero.room, game.num_camera, hero.world_y)
    assert picked is not None, "clicking the hero's feet must find floor"
    dest_x, dest_z, dest_room = picked
    assert dest_room == hero.room
    assert abs(dest_x - hero.room_x) <= 150 and abs(dest_z - hero.room_z) <= 150


def test_click_on_the_heros_feet_resolves_to_a_walk(data_dir, profile):
    game, floor = _settled_venue(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    state = _camera_state_global(
        floor, hero.room, floor.rooms[hero.room].camera_indices[game.num_camera],
    )
    feet = project_floor_point(state, hero.room_x, hero.world_y, hero.room_z)
    click = (int(round(feet[0])), int(round(feet[1])))
    kind, payload = main.resolve_play_click(game, floor, click, [])
    assert kind == "walk"
    assert payload[2] == hero.room
