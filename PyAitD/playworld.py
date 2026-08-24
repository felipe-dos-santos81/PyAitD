# SPDX-License-Identifier: GPL-2.0-only
"""PlayWorld simulation tick (FITD mainLoop.cpp:41-281 order).

Imports no pygame, ModernGL or Renderer, so one 50 Hz logic step can be
advanced without a window. Callers still reach `ui.py` for an InputBuffer;
freeing that needs InputBuffer moved out of the presentation layer.
"""
from PyAitD.actors import gere_anim
from PyAitD.anim_action import gere_frappe, refresh_hot_point
from PyAitD.effects import GameMode, GameOver, InputMode, LifeFrame
from PyAitD.formats import parse_cover_zones
from PyAitD.game import (
    AF_ANIMATED, AF_TRIGGER, change_salle, game_step_tick, spawn_stage_actors,
)
from PyAitD.interaction import (
    advance_messages, dispatch_nav_arrival, drain_immediate_effects, execute_found_life,
    gere_dec, run_life, sync_player_track_mode,
)
from PyAitD.life import life_gate
from PyAitD.navigate import decide
from PyAitD.navmesh import agent_extent
from PyAitD.world import find_best_camera, is_in_poly

TICK_MS = 20  # 50 Hz logic tick


def apply_play_input(game, input_buffer):
    # The hero's manual-control track mode belongs to the input mode, and a
    # script can hand it back to tank mode at any time (LM_INIT_DEPLACEMENT),
    # so it is re-asserted here rather than only at init and on the Tab toggle.
    sync_player_track_mode(game)
    if game.input_mode is InputMode.MOUSE:
        _apply_mouse_input(game)
        return
    game.nav_decision = None
    game.local_joyd = input_buffer.held_joyd if input_buffer.focused else 0
    game.local_click = 1 if input_buffer.focused and input_buffer.action_held else 0
    game.local_key = 0
    game.action = 0x2000 if game.local_click else 0


def _push_into_target(game):
    """Re-aim an arrived target click at the object itself for the final push.

    FITD fires scripted founds from the collision itself: anim.cpp:381 sets
    HARD_COL from a type-9 hard col's parameter, and watchers such as the
    attic lamp's life 7 call FOUND when the hero grinds into the furniture.
    The snapped approach cell stops one agent-radius short of every hard col,
    so a click that ended there could never reach those scripts. Steer into
    the object instead and let the engine's own collision clamp the hero
    against it — the mouse equivalent of holding the walk key. Foundable
    objects keep the contact-free dispatch at the approach cell, and a second
    arrival at the object's own point dispatches normally, so the push always
    terminates in a dispatch, a modal, or the stall give-up.
    """
    from PyAitD.game import AF_FOUNDABLE
    intent = game.nav_intent
    if intent.target_object_idx == -1:
        return False
    target = game.world_objects[intent.target_object_idx]
    if target.obj_index == -1 or target.found_life == -1:
        return False
    actor = game.actors[target.obj_index]
    if actor.object_type & AF_FOUNDABLE:
        return False
    if (intent.dest_x, intent.dest_z) == (actor.room_x, actor.room_z):
        return False
    intent.dest_x, intent.dest_z = actor.room_x, actor.room_z
    intent.room = actor.room
    intent.waypoints = None
    return True


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
    if decision is not None and (decision.arrived or decision.abandoned):
        if decision.arrived and not decision.abandoned and _push_into_target(game):
            game.nav_decision = None
            game.local_joyd = 0
            return
        if decision.arrived:
            game.nav_arrived_target = game.nav_intent.target_object_idx
        game.nav_intent = None
        game.nav_decision = None
        game.local_joyd = 0


def _run_actor_action(game, index, actor, flags):
    # animAction.cpp's GereFrappe consumes the *previous* pose's hot point
    # inside AllRedraw; this port refreshes it here, immediately before
    # gere_anim advances that pose, to reproduce the same value headlessly.
    if actor.anim_action_type and actor.hot_point_id != -1:
        refresh_hot_point(game, index)
    if flags & AF_ANIMATED:
        gere_anim(game, index)
        if game.mode is not GameMode.PLAY:
            return False
    if flags & AF_TRIGGER:
        gere_dec(game, index)
    if actor.anim_action_type:
        gere_frappe(game, index)
    return game.mode is GameMode.PLAY


def _anim_pass(game):
    for index, actor in enumerate(game.actors):
        if actor.index_in_world < 0:
            continue
        if not _run_actor_action(game, index, actor, actor.object_type):
            return False
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


def _genere_active_list(game):
    # mainLoop.cpp:249 GenereActiveList. FITD calls it unconditionally; this
    # port keeps its flag_genere_aff_list request gate, so this stays the one
    # place the active list is regenerated.
    if not game.flag_genere_aff_list:
        return
    spawn_stage_actors(game)
    game.flag_genere_aff_list = 0


def _handoff_game_over(game):
    # mainLoop.cpp:185,233: FlagGameOver is checked only after the complete
    # LIFE actor loop, never mid-loop, and precedes floor/room/camera/spawn
    # handling. No LIFE continuation is retained: restart is a fresh session.
    if not game.flag_game_over:
        return True
    game.flag_game_over = 0
    game.open_modal(GameOver())
    return False


def play_tick(game, floor, input_buffer):
    # mainLoop.cpp:41-281 PlayWorld, one 50Hz iteration, PLAY mode only.
    # Rendering stays outside this fixed-step function so catch-up ticks
    # cannot block input behind repeated GPU work.
    if game.mode is not GameMode.PLAY:
        return False
    if game.flag_game_over and not _handoff_game_over(game):
        # A LIFE frame suspended on a modal is resumed by interaction.resume_life
        # when that modal closes, outside this function: the real death sequence
        # (LISTLIFE 554) is LM_PICTURE immediately followed by LM_GAME_OVER, so
        # the flag is raised long after the raising tick's LIFE loop finished.
        # FITD never sees a pending flag -- its LM_PICTURE blocks inside
        # processLife, so LM_GAME_OVER lands in the same pass mainLoop.cpp:185
        # checks. Consume it before this tick re-runs that LIFE, which would
        # suspend on the picture again and strand the flag forever.
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
    if not _handoff_game_over(game):
        return False
    if game.flag_change_etage:
        # LoadEtage M3a subset (floor.cpp:7): floor data swap happens in run().
        # LoadEtage raises FlagChangeSalle (floor.cpp:40) and mainLoop consumes
        # it in the same iteration (mainLoop.cpp:189-199), so the room change
        # lands here rather than a tick later.
        game.current_floor = game.new_num_etage
        game.flag_change_etage = 0
        change_salle(game, game.new_num_salle)
        game.flag_change_salle = 0
        # FITD then `continue`s past GenereActiveList, so its next iteration
        # runs the anim pass over the previous floor's actors and only
        # regenerates at the end of it (mainLoop.cpp:249) -- C++ tolerates the
        # out-of-range roomDataTable read that produces, Python raises
        # IndexError. Raise the port's existing spawn request instead, so the
        # one spawn gate regenerates the list here, before any pass indexes the
        # new floor's rooms.
        game.flag_genere_aff_list = 1
        _genere_active_list(game)
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
    _genere_active_list(game)
    advance_messages(game)
    return True
