# SPDX-License-Identifier: GPL-2.0-only
"""PlayWorld simulation tick (FITD mainLoop.cpp:41-281 order).

Imports no pygame, ModernGL or Renderer, so one 50 Hz logic step can be
advanced without a window. Callers still reach `ui.py` for an InputBuffer;
freeing that needs InputBuffer moved out of the presentation layer.
"""
from PyAitD.actors import gere_anim
from PyAitD.effects import GameMode, InputMode, LifeFrame
from PyAitD.formats import parse_cover_zones
from PyAitD.game import (
    AF_ANIMATED, AF_TRIGGER, change_salle, game_step_tick, spawn_stage_actors,
)
from PyAitD.interaction import (
    advance_messages, dispatch_nav_arrival, drain_immediate_effects, execute_found_life,
    gere_dec, run_life,
)
from PyAitD.life import life_gate
from PyAitD.navigate import decide
from PyAitD.navmesh import agent_extent
from PyAitD.world import find_best_camera, is_in_poly

TICK_MS = 20  # 50 Hz logic tick


def apply_play_input(game, input_buffer):
    if game.input_mode is InputMode.MOUSE:
        _apply_mouse_input(game)
        return
    game.nav_decision = None
    game.local_joyd = input_buffer.held_joyd if input_buffer.focused else 0
    game.local_click = 1 if input_buffer.focused and input_buffer.action_held else 0
    game.local_key = 0
    game.action = 0x2000 if game.local_click else 0


def _apply_mouse_input(game):
    # The follower decision is made here, in the input snapshot, so the tick
    # order stays exactly FITD's mainLoop order and the mouse is a peer of the
    # keyboard rather than a bolt-on.
    game.local_key = 0
    game.local_click = 0
    game.action = 0
    hero_idx = game.current_camera_target_actor
    if hero_idx == -1 or game.nav_intent is None:
        game.nav_decision = None
        game.local_joyd = 0
        return
    hero = game.actors[hero_idx]
    mesh = game.nav_meshes.mesh_for(game.current_floor_data, hero.room, agent_extent(hero))
    decision = decide(game, hero, mesh)
    game.nav_decision = decision
    game.local_joyd = decision.joyd if decision is not None else 0
    if decision is not None and decision.arrived:
        game.nav_arrived_target = game.nav_intent.target_object_idx
        game.nav_arrived_plain = game.nav_intent.target_object_idx == -1
        game.nav_intent = None
        game.nav_decision = None
        game.local_joyd = 0


def _anim_pass(game):
    for index, actor in enumerate(game.actors):
        if actor.index_in_world < 0:
            continue
        flags = actor.object_type
        if flags & AF_ANIMATED:
            gere_anim(game, index)
            if game.mode is not GameMode.PLAY:
                return False
        if flags & AF_TRIGGER:
            gere_dec(game, index)
    return game.mode is GameMode.PLAY


def _cover_zones(floor, cam_idx, room_idx):
    # cover zones of camera cam_idx for room_idx; [] when it does not view it
    viewed = [vr.viewed_room_idx for vr in floor.cameras[cam_idx].viewed_rooms]
    if room_idx not in viewed:
        return []
    off = floor.camera_data_offsets[cam_idx]
    return parse_cover_zones(floor.camera_raw, off, viewed.index(room_idx))


def _camera_switch(game, floor):
    # main.cpp:3654 GereSwitchCamera port: hero out of the current camera's
    # cover zones -> findBestCamera among the hero-room's cameras.
    if game.current_camera_target_actor == -1:
        return
    actor = game.actors[game.current_camera_target_actor]
    room = floor.rooms[actor.room]
    room_cameras = [floor.cameras[i] for i in room.camera_indices]
    zv = actor.zv
    x1, x2 = int(zv[0] / 10), int(zv[1] / 10)
    z1, z2 = int(zv[4] / 10), int(zv[5] / 10)
    if game.num_camera != -1:
        current = _cover_zones(floor, room.camera_indices[game.num_camera], actor.room)
        if current and is_in_poly(x1, x2, z1, z2, current):
            return
    zones_by_camera = [
        _cover_zones(floor, cam_idx, actor.room) for cam_idx in room.camera_indices
    ]
    new_camera = find_best_camera(x1, x2, z1, z2, actor.beta, room_cameras, zones_by_camera)
    if new_camera != -1 and game.num_camera != new_camera:
        game.new_num_camera = new_camera
        game.flag_init_view = 1


def play_tick(game, floor, input_buffer):
    # mainLoop.cpp:41-281 PlayWorld, one 50Hz iteration, PLAY mode only.
    # Rendering stays outside this fixed-step function so catch-up ticks
    # cannot block input behind repeated GPU work.
    if game.mode is not GameMode.PLAY:
        return False
    game.current_floor_data = floor   # the mesh cache needs the loaded Floor
    apply_play_input(game, input_buffer)
    if not dispatch_nav_arrival(game):
        return False
    game_step_tick(game)
    in_hand = game.in_hand_table[game.current_inventory]
    if in_hand != -1 and not execute_found_life(game, in_hand):
        return False
    if not drain_immediate_effects(game) or game.mode is not GameMode.PLAY:
        return False
    for actor in game.actors:
        if actor.index_in_world >= 0:
            actor.col_by = actor.hit_by = actor.hit = actor.hard_dec = actor.hard_col = -1
    if not _anim_pass(game):
        return False
    for index, actor in enumerate(game.actors):
        if actor.index_in_world < 0:
            continue
        if life_gate(actor):
            if not run_life(game, LifeFrame(index, actor.life)):
                drain_immediate_effects(game)
                return False
            if not drain_immediate_effects(game):
                return False
        if game.flag_change_etage:
            break
    if game.flag_change_etage:
        # LoadEtage M3a subset (floor.cpp:7): floor data swap happens in run();
        # FITD LoadEtage sets FlagChangeSalle so the view re-rooms next tick.
        game.current_floor = game.new_num_etage
        game.flag_change_etage = 0
        game.num_camera = -1
        game.flag_change_salle = 1
        return False
    if game.flag_change_salle:
        # mainLoop.cpp:194-199: ChangeSalle + InitView + continue (no draw)
        change_salle(game, game.new_num_salle)
        game.flag_change_salle = 0
        return False
    _camera_switch(game, floor)
    if game.flag_init_view:
        # InitView M3a subset: camera data is loaded on demand at draw
        game.num_camera = game.new_num_camera
        game.flag_init_view = 0
    if game.flag_genere_aff_list:
        spawn_stage_actors(game)
        game.flag_genere_aff_list = 0
    advance_messages(game)
    return True
