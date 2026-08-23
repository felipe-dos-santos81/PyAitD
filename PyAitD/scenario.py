# SPDX-License-Identifier: GPL-2.0-only
"""The one supported debug/test venue: floor 5, room 4, in front of world
object 222 (an enemy). Pinned so manual play, integration tests, and the
headless proof tool share a single "immediately be in combat" entry point
instead of each hand-rolling their own floor transition."""
from PyAitD.game import FloorStart, enter_floor_start

COMBAT_VENUE = FloorStart(5, 4, -7800, -4010, -1000, 0)


def enter_combat_venue(game):
    enter_floor_start(game, COMBAT_VENUE)
    game.floor_start = COMBAT_VENUE
