# SPDX-License-Identifier: GPL-2.0-only
"""Debug viewer: browse every room/camera background of a floor."""
import argparse
import pathlib
import sys

import pygame

from maitd.floor import Floor
from maitd.pak import PakError
from maitd.render import Renderer

DEFAULT_DATA = (
    pathlib.Path(__file__).resolve().parent.parent
    / "Alone in the Dark 1.app"
    / "Contents"
    / "Resources"
    / "game"
    / "INDARK"
)


def parse_args(argv):
    p = argparse.ArgumentParser(prog="maitd", description="AITD1 room viewer (M1 debug)")
    p.add_argument("--data", type=pathlib.Path, default=DEFAULT_DATA, help="game data dir")
    p.add_argument("--floor", type=int, default=0, help="floor number (default 0)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        floor = Floor(args.data, args.floor)
    except PakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    renderer = Renderer()
    clock = pygame.time.Clock()
    room_idx = 0
    cam_slot = 0

    def show():
        nonlocal room_idx
        room = floor.rooms[room_idx]
        # some floors contain rooms with no cameras (legit original data) —
        # skip them so the debug viewer never divides by zero
        while not room.camera_indices:
            room_idx = (room_idx + 1) % len(floor.rooms)
            room = floor.rooms[room_idx]
        cam_idx = room.camera_indices[cam_slot % len(room.camera_indices)]
        renderer.present(floor.camera_image(cam_idx))
        pygame.display.set_caption(
            f"maitd — floor {floor.number} room {room_idx} camera {cam_idx}"
        )

    show()
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_RIGHT:
                    cam_slot += 1
                    show()
                elif event.key == pygame.K_LEFT:
                    cam_slot -= 1
                    show()
                elif event.key == pygame.K_UP:
                    room_idx = (room_idx + 1) % len(floor.rooms)
                    cam_slot = 0
                    show()
                elif event.key == pygame.K_DOWN:
                    room_idx = (room_idx - 1) % len(floor.rooms)
                    cam_slot = 0
                    show()
        clock.tick(60)
    renderer.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
