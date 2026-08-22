# SPDX-License-Identifier: GPL-2.0-only
"""AITD1 M3a play loop: PlayWorld port (mainLoop.cpp:41-281) — script-driven
actors, hero-following camera, M2 render pipeline."""
import argparse
import pathlib
import sys

import pygame

from maitd.anim import AnimPlayer
from maitd.floor import Floor
from maitd.formats import parse_cover_zones
from maitd.game import (
    AF_ANIMATED,
    change_salle,
    game_step_tick,
    init_game,
    joyd_from_keys,
    spawn_stage_actors,
)
from maitd.life import Trace, life_gate, process_life
from maitd.mask import create_aitd1_mask
from maitd.pak import PakError
from maitd.render import Renderer
from maitd.skel import skin
from maitd.world import CameraState, find_best_camera, is_in_poly

DEFAULT_DATA = (
    pathlib.Path(__file__).resolve().parent.parent
    / "Alone in the Dark 1.app"
    / "Contents"
    / "Resources"
    / "game"
    / "INDARK"
)

TICK_MS = 20  # 50 Hz logic tick


def parse_args(argv):
    p = argparse.ArgumentParser(prog="maitd", description="AITD1 play viewer (M3a: PlayWorld script loop)")
    p.add_argument("--data", type=pathlib.Path, default=DEFAULT_DATA, help="game data dir")
    p.add_argument("--floor", type=int, default=0, help="floor number (default 0)")
    p.add_argument("--trace", type=pathlib.Path, default=None, help="write per-opcode LIFE trace to FILE")
    return p.parse_args(argv)


def poll_input(game):
    # mainLoop.cpp:49-99 input snapshot; action from Click. ESC quits in run()
    # (M3a: no system menu / inventory).
    keys = pygame.key.get_pressed()
    game.local_joyd = joyd_from_keys(
        keys[pygame.K_UP], keys[pygame.K_DOWN], keys[pygame.K_LEFT], keys[pygame.K_RIGHT]
    )
    game.local_click = 1 if keys[pygame.K_SPACE] else 0
    if keys[pygame.K_RETURN]:
        game.local_key = 0x1C
    elif keys[pygame.K_ESCAPE]:
        game.local_key = 0x1B
    else:
        game.local_key = 0
    game.action = 0x2000 if game.local_click else 0


def _anim_player(game, i):
    a = game.actors[i]
    body = game.assets.body(a.body_num)
    anim = game.assets.anim(a.anim)
    player = game.anim_players.get(i)
    if player is None or player.body is not body or player.anim is not anim:
        player = AnimPlayer(body, anim, game.timer)
        game.anim_players[i] = player
    return player


def _anim_pass(game):
    # mainLoop.cpp:127-148: GereAnim per AF_ANIMATED actor (M2 AnimPlayer).
    # GereDec (AF_TRIGGER, M3b) and GereFrappe (anim_action_type, M3c) skipped.
    for i, a in enumerate(game.actors):
        if a.index_in_world < 0 or not (a.object_type & AF_ANIMATED) or a.anim == -1:
            continue
        _anim_player(game, i).advance(game.timer)


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
        cam_idx = room.camera_indices[game.num_camera]
        cam = floor.cameras[cam_idx]
        viewed = [vr.viewed_room_idx for vr in cam.viewed_rooms]
        if actor.room in viewed:
            vi = viewed.index(actor.room)
            off = floor.camera_data_offsets[cam_idx]
            if is_in_poly(x1, x2, z1, z2, parse_cover_zones(floor.camera_raw, off, vi)):
                return
    zones_by_camera = []
    for cam_idx in room.camera_indices:
        cam = floor.cameras[cam_idx]
        viewed = [vr.viewed_room_idx for vr in cam.viewed_rooms]
        if actor.room in viewed:
            vi = viewed.index(actor.room)
            off = floor.camera_data_offsets[cam_idx]
            zones_by_camera.append(parse_cover_zones(floor.camera_raw, off, vi))
        else:
            zones_by_camera.append([])
    new_camera = find_best_camera(x1, x2, z1, z2, actor.beta, room_cameras, zones_by_camera)
    if new_camera != -1 and game.num_camera != new_camera:
        game.new_num_camera = new_camera
        game.flag_init_view = 1


def _draw(game, floor, renderer):
    # mainLoop.cpp:270 AllRedraw: M2 render pipeline, every live actor skinned
    # through the current camera (num_camera is room-relative, FITD InitView).
    room = floor.rooms[game.current_room]
    cam_idx = room.camera_indices[game.num_camera]
    cam = floor.cameras[cam_idx]
    state = CameraState.from_camera(cam, room.world_x, room.world_y, room.world_z).angles()
    results = []
    for i, a in enumerate(game.actors):
        if a.index_in_world < 0 or a.body_num == -1:
            continue
        body = game.assets.body(a.body_num)
        if a.anim == -1:
            states = [(0, (0, 0, 0))] * len(body.groups)  # static mesh: no anim
        else:
            states = _anim_player(game, i).group_states()
        results.append(skin(
            body, states,
            (a.world_x + a.step_x, a.world_y + a.step_y, a.world_z + a.step_z),
            state, actor_angles=(a.alpha, a.beta, a.gamma),
        ))
    masks = create_aitd1_mask(floor.camera_raw, floor.camera_data_offsets[cam_idx])
    renderer.present_scene(floor.camera_image(cam_idx), results, masks, floor.palette)
    live = sum(1 for a in game.actors if a.index_in_world >= 0)
    pygame.display.set_caption(
        f"maitd — floor {floor.number} room {game.current_room} camera {cam_idx} "
        f"actors {live}"
    )


def play_tick(game, floor, renderer):
    # mainLoop.cpp:41-281 PlayWorld, one 50Hz iteration. Movement integration
    # and collision (GereAnim steps) land with the anim runner, M3a runs the
    # LIFE scripts only.
    game_step_tick(game)
    poll_input(game)

    # per-actor collision snapshot clear (mainLoop.cpp:114-125)
    for a in game.actors:
        if a.index_in_world >= 0:
            a.col_by = a.hit_by = a.hit = a.hard_dec = a.hard_col = -1

    _anim_pass(game)

    # life pass (mainLoop.cpp:151-183), break on floor change
    for i, a in enumerate(game.actors):
        if a.index_in_world < 0:
            continue
        if life_gate(a):
            process_life(game, i, a.life)
        if game.flag_change_etage:
            break

    if game.flag_change_etage:
        # LoadEtage M3a subset (floor.cpp:7): floor data swap happens in run();
        # FITD LoadEtage sets FlagChangeSalle so the view re-rooms next tick.
        game.current_floor = game.new_num_etage
        game.flag_change_etage = 0
        game.num_camera = -1
        game.flag_change_salle = 1
        return

    if game.flag_change_salle:
        # mainLoop.cpp:194-199: ChangeSalle + InitView + continue (no draw)
        change_salle(game, game.new_num_salle)
        game.flag_change_salle = 0
        return

    _camera_switch(game, floor)
    if game.flag_init_view:
        # InitView M3a subset: camera data is loaded on demand at draw
        game.num_camera = game.new_num_camera
        game.flag_init_view = 0
    if game.flag_genere_aff_list:
        spawn_stage_actors(game)
        game.flag_genere_aff_list = 0
    _draw(game, floor, renderer)


def run(game, trace_path=None):
    # M3a play loop: 50Hz PlayWorld ticks, M2 clock discipline
    try:
        floor = Floor(game._data_dir, game.current_floor)
    except PakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    game.trace = Trace(trace_path) if trace_path else None
    renderer = Renderer()
    clock = pygame.time.Clock()
    running = True
    last = pygame.time.get_ticks()
    acc = 0
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False  # M3a: no system menu, ESC quits
        now = pygame.time.get_ticks()
        acc += now - last
        last = now
        while acc >= TICK_MS:
            play_tick(game, floor, renderer)
            acc -= TICK_MS
            if floor.number != game.current_floor:
                floor = Floor(game._data_dir, game.current_floor)
        clock.tick(60)
    if game.trace is not None:
        game.trace.close()
    renderer.close()
    return 0


def main(argv=None):
    args = parse_args(argv)
    try:
        game = init_game(args.data)
    except PakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.floor != game.current_floor:
        game.current_floor = args.floor
        spawn_stage_actors(game)
        game.num_camera = -1
        game.flag_init_view = 2
    return run(game, args.trace)


if __name__ == "__main__":
    raise SystemExit(main())
