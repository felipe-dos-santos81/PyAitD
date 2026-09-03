# SPDX-License-Identifier: GPL-2.0-only
"""The supported debug/test venues: floor 5, room 4, in front of world object
222 (an enemy), and the attic's own window creature. Pinned so manual play,
integration tests, and the headless proof tool share single entry points
instead of each hand-rolling their own floor transition or script state."""
from PyAitD.engine.script.game import FloorStart, enter_floor_start, relocate_actor

COMBAT_VENUE = FloorStart(5, 4, -7800, -4010, -1000, 0)

ATTIC_WINDOW_OBJECT = 9
"""The attic creature that comes in through the window (body 23).

Its LIFE 16 waits on two gates -- vars[19] == 1 and a chrono past 20 -- then
runs LM_MOVE(3, 0) + LM_BODY(23) + LM_ANIM_REPEAT(19) and hands over to LIFE
17. Track 0 drops it from y=3000 (the window) to the floor, walks it clear of
the wall, and LIFE 18 puts it in track mode 2 following world object 1, the
hero. The attic is one room, so the whole encounter plays out on floor 0.
"""

ATTIC_STAIR_OBJECT = 21
"""The attic's other creature (body 24), the one that walks in through the
doorway in the north wall.

Its LIFE 19 -> 20 -> 21 chain is the mirror of the window creature's: track 1
walks it in from z=10000 with collision off, TL_COL_ON turns collision back
on, and LIFE 21 puts it in track mode 2 following the hero. It needs no
fixture -- it arms itself about 3600 ticks into the attic.
"""

ATTIC_WINDOW_ARMED_VAR = 19
"""The flag the attic's *other* creature raises (LISTLIFE 20 byte 58, LISTLIFE
21 byte 164) to arm the window entry. Setting it is the whole fixture: the
20-second chrono then runs on its own."""


def arm_attic_window_creature(game):
    """Open LIFE 16's first gate so the window entry runs on its own clock.

    Deliberately does not touch the actor: the point of the fixture is to
    exercise the real script chain, not to pose the creature.
    """
    game.vars[ATTIC_WINDOW_ARMED_VAR] = 1

MOUSE_COMBAT_OBJECT = 38
MOUSE_COMBAT_HERO = (5500, -4010, 5250)
MOUSE_COMBAT_TARGET = (5500, -4010, 5000)


def enter_combat_venue(game):
    enter_floor_start(game, COMBAT_VENUE)
    game.floor_start = COMBAT_VENUE


def enter_mouse_combat_fixture(game):
    """Deterministic object-38 lane for automated and manual mouse proof."""
    from PyAitD.engine.script.interaction import _finish_take

    enter_combat_venue(game)
    _finish_take(game, MOUSE_COMBAT_OBJECT)
    hero_idx = game.current_camera_target_actor
    enemy_idx = game.world_objects[222].obj_index
    relocate_actor(game, hero_idx, 5, 4, *MOUSE_COMBAT_HERO)
    relocate_actor(game, enemy_idx, 5, 4, *MOUSE_COMBAT_TARGET)
    enemy = game.actors[enemy_idx]
    enemy.life = -1
    enemy.life_mode = -1
    enemy.track_mode = 0
    enemy.speed = 0
