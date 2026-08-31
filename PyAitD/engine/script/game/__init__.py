# SPDX-License-Identifier: GPL-2.0-only
"""Game state, world-object lifecycle and boot (subpackage split of the
former engine.game module; every name re-exported for importers)."""
from PyAitD.engine.script.game.state import (
    AF_ANIMATED, AF_BOXIFY, AF_DRAWABLE, AF_FALLABLE, AF_FOUNDABLE, AF_MASK,
    AF_MOVABLE, AF_SPECIAL, AF_TRIGGER, NUM_MAX_OBJECT, Actor, FloorStart,
    Game, RealValue,
)
from PyAitD.engine.script.game.zv import (
    _hard_zv, _point_rotate, _zv_cube, _zv_default, _zv_max, _zv_rot,
)
from PyAitD.engine.script.game.objects import (
    _delete_objet, activate_world_object, add_actor, delete_object,
    put_at_objet, spawn_stage_actors,
)
from PyAitD.engine.script.game.boot import (
    change_salle, enter_floor_start, game_step_tick, init_game,
    relocate_actor, start_game,
)
