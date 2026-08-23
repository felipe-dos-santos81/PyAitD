# SPDX-License-Identifier: GPL-2.0-only
"""Headless proof for the shared floor-5 combat venue (M3c Phase A).

Enters the pinned venue, runs it for 1200 PLAY ticks, and checks that
world object 222 — the venue's enemy — closes distance on the hero. Combat
itself is Phase B; this only proves the venue and its pursuit are alive.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PyAitD.effects import GameMode
from PyAitD.floor import Floor
from PyAitD.game import init_game
from PyAitD.playworld import play_tick
from PyAitD.realvalue import give_distance_2d
from PyAitD.scenario import enter_combat_venue
from PyAitD.ui import InputBuffer


def main(argv):
    data = pathlib.Path(argv[0])
    game = init_game(data)
    enter_combat_venue(game)
    floor = Floor(data, game.current_floor)
    hero = game.actors[game.current_camera_target_actor]
    enemy = game.actors[game.world_objects[222].obj_index]
    start = give_distance_2d(hero.room_x, hero.room_z, enemy.room_x, enemy.room_z)
    closest = start
    for _ in range(1200):
        play_tick(game, floor, InputBuffer())
        if game.mode is not GameMode.PLAY:
            raise AssertionError(f"venue opened unexpected mode {game.mode}")
        closest = min(
            closest,
            give_distance_2d(hero.room_x, hero.room_z, enemy.room_x, enemy.room_z),
        )
    if closest >= start:
        raise AssertionError(f"obj222 did not pursue: start={start}, closest={closest}")
    print(f"venue pursuit: start={start}, closest={closest}")
    print("combat arms: pending Phase B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
