# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.engine.script.playworld import IDLE, play_tick
from PyAitD.engine.script.effects import FoundResult, OpenInventory
from PyAitD.engine.data.floor import Floor
from PyAitD.engine.script.game import init_game
from PyAitD.engine.script.interaction import (
    apply_found_result, apply_inventory_result, inventory_actions,
    inventory_items, request_found,
)
from PyAitD.app.ui import InventoryResult
import pytest

pytestmark = [pytest.mark.engine, pytest.mark.journey]


def test_attic_lamp_find_take_use_and_drop_checkpoint(data_dir, profile):
    game = init_game(data_dir, profile)
    game.timer = 300
    lamp_idx = 13
    lamp = game.world_objects[lamp_idx]
    assert (lamp.stage, lamp.room, lamp.found_name, lamp.found_life) == (0, 0, 201, 9)
    assert (lamp.found_flag, lamp.found_body, lamp.position_in_track) == (1545, 10, 30)
    assert lamp.track_number == -1

    found = request_found(game, lamp_idx, parameter=0)
    assert found is not None
    game.open_modal(found)
    apply_found_result(game, FoundResult.TAKE)
    assert lamp_idx in inventory_items(game)
    assert lamp.found_flag & 0x8000
    assert (lamp.stage, lamp.room, lamp.obj_index) == (-1, -1, -1)

    game.open_modal(OpenInventory())
    actions = inventory_actions(game, lamp_idx)
    assert 23 in actions
    apply_inventory_result(game, InventoryResult(lamp_idx, 23))
    assert game.in_hand_table[0] == lamp_idx
    assert game.action == 1

    game.open_modal(OpenInventory())
    assert 33 in inventory_actions(game, lamp_idx)
    apply_inventory_result(game, InventoryResult(lamp_idx, 33))
    # FITD Drop/Put is two-stage. Lamp LIFE 9 case 0x400 (LISTLIFE 9, byte 108)
    # only re-points world object 1's actor (anim 10, LIFE 11) and stores the
    # subject in vars[9]; it does not touch the inventory. The removal happens
    # once that anim finishes (flag_end_anim gate, LISTLIFE 11, byte 10) via
    # LM_DROP (life.cpp:1510) -> drop(vars[9], 1) -> PutAtObjet (main.cpp:3948)
    # -> DeleteInventoryObjet (main.cpp:2356) + foundFlag |= 0x4000.
    assert game.vars[9] == lamp_idx
    floor = Floor(data_dir, 0, profile)
    for _ in range(200):
        if lamp_idx not in inventory_items(game):
            break
        # A False return is a legitimate mid-tick suspend (the attic boot
        # cutscene actor 2 takes object 2 on the first tick); keep ticking.
        play_tick(game, floor, IDLE)
    assert lamp_idx not in inventory_items(game)
    assert lamp.found_flag & 0x4000


def _tick_until(game, floor, predicate, *, limit):
    """Tick until predicate(game) holds. Returns the tick it held on, or -1."""
    for tick in range(limit):
        play_tick(game, floor, IDLE)
        if predicate(game):
            return tick
    return -1


def _window_creature(game):
    from PyAitD.games.aitd1.scenario import ATTIC_WINDOW_OBJECT

    slot = game.world_objects[ATTIC_WINDOW_OBJECT].obj_index
    return game.actors[slot] if slot != -1 else None


def test_the_attic_window_creature_drops_in_and_comes_for_the_hero(data_dir, profile):
    """The attic's own encounter, end to end, against the real scripts.

    The repo pinned only the floor-5 venue (scenario.COMBAT_VENUE), so the
    game's first monster had no coverage at all. This walks the whole chain --
    LIFE 16's gate, track 0's drop from the window, and LIFE 18's pursuit --
    because each stage fails in a different place, and a bug report of "it
    breaks in and then just stands there" cannot say which one.
    """
    from PyAitD.games.aitd1.scenario import arm_attic_window_creature

    game = init_game(data_dir, profile)
    floor = Floor(data_dir, 0, profile)
    play_tick(game, floor, IDLE)
    hero = game.actors[game.current_camera_target_actor]

    creature = _window_creature(game)
    assert creature is not None, "the window creature is placed from the start"
    assert (creature.room, creature.life) == (0, 16)

    arm_attic_window_creature(game)

    # LIFE 16 hands over to the entry track once its chrono passes 20.
    entered = _tick_until(
        game, floor, lambda g: _window_creature(g).track_mode == 3, limit=2500,
    )
    assert entered != -1, "LIFE 16 never armed the entry track"
    assert (creature.track_number, creature.body_num) == (0, 23)
    # INIT_COOR puts it up at the window before anything else moves.
    assert creature.room_y == 3000

    # Track 0's GOTO_3D is the drop to the floor: 240 ticks of y_handler.
    landed = _tick_until(
        game, floor,
        lambda g: _window_creature(g).room_y == 0
        and _window_creature(g).position_in_track > 6,
        limit=600,
    )
    assert landed != -1, "the creature never came down from the window"

    # Track 0 ends by handing the actor to LIFE 18, which follows the hero.
    chasing = _tick_until(
        game, floor,
        lambda g: _window_creature(g).track_mode == 2, limit=400,
    )
    assert chasing != -1, "the entry track never handed over to the chase"
    assert creature.life == 18
    # track mode 2 follows a *world* object; 1 is the hero.
    assert creature.track_number == 1

    def gap(g):
        c = _window_creature(g)
        return abs(c.room_x - hero.room_x) + abs(c.room_z - hero.room_z)

    start_gap = gap(game)
    closed = _tick_until(game, floor, lambda g: gap(g) < start_gap // 4, limit=2500)
    assert closed != -1, (
        f"the creature did not close on the hero: {start_gap} -> {gap(game)}"
    )


def test_the_attic_stair_creature_can_still_walk_once_it_stops_in_the_doorway(
        data_dir, profile):
    """The attic's second creature must not be frozen by the door it came through.

    World object 21 walks in on track 1 with collision off, stops ~400 units
    short of the track's own target (TL_GOTO's DISTANCE_TO_POINT_TRESSHOLD),
    and then TL_COL_ON turns collision back on -- with its 1062-unit bounding
    cube still straddling the doorway hard-col at z 5000..5300. From that tick
    on, gere_collision's "already inside" case zeroes every step, so it
    animates forever without moving.
    """
    from PyAitD.games.aitd1.scenario import ATTIC_STAIR_OBJECT

    game = init_game(data_dir, profile)
    floor = Floor(data_dir, 0, profile)

    def creature(g):
        slot = g.world_objects[ATTIC_STAIR_OBJECT].obj_index
        return g.actors[slot] if slot != -1 else None

    chasing = _tick_until(
        game, floor, lambda g: creature(g).track_mode == 2, limit=4200,
    )
    assert chasing != -1, "the second creature never reached its chase life"

    hero = game.actors[game.current_camera_target_actor]

    def gap(g):
        c = creature(g)
        return abs(c.room_x - hero.room_x) + abs(c.room_z - hero.room_z)

    # let the pending step from the entry track commit before measuring
    _tick_until(game, floor, lambda g: False, limit=60)
    parked = (creature(game).room_x, creature(game).room_z)
    start_gap = gap(game)
    _tick_until(game, floor, lambda g: False, limit=300)
    moved = abs(creature(game).room_x - parked[0]) + abs(creature(game).room_z - parked[1])
    assert moved > 0, (
        f"the creature is frozen at {parked} six seconds into its chase"
    )
    # and it must actually cross the room, not merely twitch free
    closed = _tick_until(game, floor, lambda g: gap(g) < start_gap // 4, limit=2000)
    assert closed != -1, f"the creature never reached the hero: {start_gap} -> {gap(game)}"
