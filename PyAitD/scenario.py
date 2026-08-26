# SPDX-License-Identifier: GPL-2.0-only
"""The one supported debug/test venue: floor 5, room 4, in front of world
object 222 (an enemy). Pinned so manual play, integration tests, and the
headless proof tool share a single "immediately be in combat" entry point
instead of each hand-rolling their own floor transition."""
from PyAitD.engine.game import FloorStart, enter_floor_start, relocate_actor

COMBAT_VENUE = FloorStart(5, 4, -7800, -4010, -1000, 0)

MOUSE_COMBAT_OBJECT = 38
MOUSE_COMBAT_HERO = (5500, -4010, 5250)
MOUSE_COMBAT_TARGET = (5500, -4010, 5000)


def enter_combat_venue(game):
    enter_floor_start(game, COMBAT_VENUE)
    game.floor_start = COMBAT_VENUE


def enter_mouse_combat_fixture(game):
    """Deterministic object-38 lane for automated and manual mouse proof."""
    from PyAitD.engine.interaction import _finish_take

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
