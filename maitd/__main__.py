# SPDX-License-Identifier: GPL-2.0-only
"""AITD1 M2 play viewer: walk the player actor around floor rooms."""
import argparse
import pathlib
import sys

import pygame

from maitd.actors import actor_zv, player_step, spawn_player
from maitd.anim import AnimPlayer
from maitd.assets import Assets
from maitd.floor import Floor
from maitd.formats import parse_cover_zones
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
    p = argparse.ArgumentParser(prog="maitd", description="AITD1 room viewer (M2: actor walk)")
    p.add_argument("--data", type=pathlib.Path, default=DEFAULT_DATA, help="game data dir")
    p.add_argument("--floor", type=int, default=0, help="floor number (default 0)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        floor = Floor(args.data, args.floor)
        assets = Assets(args.data)
    except PakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not any(r.camera_indices for r in floor.rooms):
        print("error: no room with cameras on this floor", file=sys.stderr)
        return 2

    renderer = Renderer()
    clock = pygame.time.Clock()

    actor = spawn_player(assets, floor)
    room_idx = actor.room_idx
    cam_slot = 0
    body = assets.body(actor.body_idx)
    player = AnimPlayer(body, assets.anim(actor.anim_idx), actor.tick)

    def room_zone_lists():
        # per room camera slot: cover zones for the actor's room, [] if the
        # camera does not view that room
        room = floor.rooms[room_idx]
        out = []
        for cam_idx in room.camera_indices:
            cam = floor.cameras[cam_idx]
            viewed = [vr.viewed_room_idx for vr in cam.viewed_rooms]
            if room_idx in viewed:
                vi = viewed.index(room_idx)
                off = floor.camera_data_offsets[cam_idx]
                out.append(parse_cover_zones(floor.camera_raw, off, vi))
            else:
                out.append([])
        return out

    def draw():
        room = floor.rooms[room_idx]
        cam_idx = room.camera_indices[cam_slot % len(room.camera_indices)]
        cam = floor.cameras[cam_idx]
        state = CameraState.from_camera(
            cam, room.world_x, room.world_y, room.world_z
        ).angles()
        result = skin(body, player.group_states(), (actor.x, actor.y, actor.z), state,
                      actor_angles=(0, actor.beta, 0))
        masks = create_aitd1_mask(floor.camera_raw, floor.camera_data_offsets[cam_idx])
        renderer.present_scene(floor.camera_image(cam_idx), [result], masks, floor.palette)
        pygame.display.set_caption(
            f"maitd — floor {floor.number} room {room_idx} camera {cam_idx} "
            f"body {actor.body_idx} anim {actor.anim_idx}"
        )

    def logic_tick():
        nonlocal cam_slot
        joyd = 0
        keys = pygame.key.get_pressed()
        if keys[pygame.K_UP]:
            joyd |= 1
        if keys[pygame.K_DOWN]:
            joyd |= 2
        if keys[pygame.K_LEFT]:
            joyd |= 4
        if keys[pygame.K_RIGHT]:
            joyd |= 8
        player_step(actor, body, joyd, floor.rooms[room_idx].hard_cols)

        # camera switching: still inside current camera's zone?
        room = floor.rooms[room_idx]
        cam_idx = room.camera_indices[cam_slot % len(room.camera_indices)]
        zv = actor_zv(actor, body)
        x1, x2, z1, z2 = int(zv[0] / 10), int(zv[1] / 10), int(zv[4] / 10), int(zv[5] / 10)
        cam = floor.cameras[cam_idx]
        viewed = [vr.viewed_room_idx for vr in cam.viewed_rooms]
        current_zones = []
        if room_idx in viewed:
            vi = viewed.index(room_idx)
            off = floor.camera_data_offsets[cam_idx]
            current_zones = parse_cover_zones(floor.camera_raw, off, vi)
        if not is_in_poly(x1, x2, z1, z2, current_zones):
            room_cameras = [floor.cameras[i] for i in room.camera_indices]
            new_slot = find_best_camera(x1, x2, z1, z2, actor.beta, room_cameras, room_zone_lists())
            if new_slot != -1:
                cam_slot = new_slot

        player.advance(actor.tick)

    draw()
    running = True
    last = pygame.time.get_ticks()
    acc = 0
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
        now = pygame.time.get_ticks()
        acc += now - last
        last = now
        while acc >= TICK_MS:
            logic_tick()
            acc -= TICK_MS
        draw()
        clock.tick(60)
    renderer.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
