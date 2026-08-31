# SPDX-License-Identifier: GPL-2.0-only
"""Per-actor anim/LIFE passes, cover-zone camera switch, active-list regen, game-over handoff."""
from PyAitD.engine.actor.actors import gere_anim
from PyAitD.engine.actor.anim_action import gere_frappe, refresh_hot_point
from PyAitD.engine.script.effects import CutsceneFinished, GameMode, GameOver
from PyAitD.engine.script.game import AF_ANIMATED, AF_TRIGGER, spawn_stage_actors
from PyAitD.engine.script.interaction import gere_dec
from PyAitD.engine.space.world import find_best_camera, is_in_poly


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
    return floor.cover_zones(cam_idx, viewed.index(room_idx))


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
    if not game.allow_system_menu:
        game.open_modal(CutsceneFinished())
        return False
    game.open_modal(GameOver())
    return False
