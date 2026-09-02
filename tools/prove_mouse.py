# SPDX-License-Identifier: GPL-2.0-only
"""Build the navmesh for every camera-visible room on every floor.

Reports walkable counts. Near-empty cave rooms are a KNOWN boundary (type-3
climbable walls tile their cover area and nothing consumes hard_col == 255
yet), so they are reported, not failed on.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PyAitD.engine.script.game import init_game
from PyAitD.engine.nav.navmesh import agent_extent, build_room_mesh
from PyAitD.engine.nav.picking import pick_floor_any_room
from PyAitD.games.aitd1.profile import AITD1

DEFAULT_DATA = (
    pathlib.Path(__file__).resolve().parent.parent
    / "data" / "aitd1" / "Alone in the Dark 1.app" / "Contents" / "Resources" / "game" / "INDARK"
)


def count_occluded(floor, hero_room, floor_y, agent, stride=5):
    """Per camera slot of hero_room: how many sampled pixels the pre-occlusion
    pick accepted as floor and the occluded pick now refuses -- the wall and
    furniture pixels that used to fall through onto the floor behind them."""
    counts = {}
    pixels = [(x, y) for y in range(199, 40, -stride) for x in range(2, 320, stride)]
    for slot in range(len(floor.rooms[hero_room].camera_indices)):
        refused = 0
        for pixel in pixels:
            old = pick_floor_any_room(pixel, floor, hero_room, slot, floor_y, occlude=False)
            if old is None:
                continue
            new = pick_floor_any_room(pixel, floor, hero_room, slot, floor_y, agent=agent)
            if new is None:
                refused += 1
        counts[slot] = refused
    return counts


def main(argv):
    data = pathlib.Path(argv[0]) if argv else DEFAULT_DATA
    game = init_game(data, AITD1)
    agent = agent_extent(game.actors[game.current_camera_target_actor])
    built = skipped = empty = 0
    for number in range(8):
        floor = game.load_floor(number)
        for room_idx, room in enumerate(floor.rooms):
            mesh = build_room_mesh(floor, room_idx, agent)
            if mesh is None:
                skipped += 1
                print(f"floor {number} room {room_idx:2d}: no camera views it — skipped")
                continue
            built += 1
            count = int(mesh.walkable.sum())
            note = ""
            if count == 0:
                empty += 1
                note = "  <- EMPTY (known: climbable-wall floor)"
            print(f"floor {number} room {room_idx:2d}: {mesh.shape} "
                  f"walkable {count}{note}")
        if number == 0:
            hero = game.actors[game.current_camera_target_actor]
            for slot, refused in count_occluded(floor, hero.room, hero.world_y, agent).items():
                print(f"floor 0 camera slot {slot}: {refused} wall/furniture pixels no longer pick the floor behind them")
    print(f"\nbuilt {built} meshes, {skipped} rooms without cameras, {empty} empty")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
