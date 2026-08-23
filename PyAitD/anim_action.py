# SPDX-License-Identifier: GPL-2.0-only
"""Per-actor animation action runner (FITD animAction.cpp GereFrappe et al.).

Consumes the previous tick's cached hot point (refreshed by
`refresh_hot_point`, called just before `gere_anim` in playworld's per-actor
pass) to build a strike cube and publish hits through `check_object_col`.
Never touches actor.life: health lives in script vars, hit/hit_by/hit_force
are the only fields this module writes.
"""
from PyAitD.actors import anim_player_for, check_hard_col, check_object_col
from PyAitD.game import AF_ANIMATED, AF_BOXIFY, AF_SPECIAL, put_at_objet
from PyAitD.interaction import remove_from_inventory
from PyAitD.realvalue import init_real_value
from PyAitD.skel import hot_point

WAIT_FRAPPE_ANIM = 1
FRAPPE_OK = 2
WAIT_TIR_ANIM = 4
DO_TIR = 5
WAIT_ANIM_THROW = 6
WAIT_FRAME_THROW = 7
HIT_OBJECT = 8
THROW_OBJECT = 9
WAIT_FRAPPE_FRAME = 10
HANDLED_ACTIONS = {1, 2, 4, 5, 6, 7, 8, 9, 10}


def refresh_hot_point(game, actor_idx):
    actor = game.actors[actor_idx]
    body = game.assets.body(actor.body_num)
    states = (
        [(0, (0, 0, 0))] * len(body.groups)
        if actor.anim == -1 else anim_player_for(game, actor_idx).group_states()
    )
    actor.hot_point[:] = hot_point(
        body, states, (actor.alpha, actor.beta, actor.gamma),
        actor.hot_point_id,
    )


def _publish_hit(game, attacker_idx, victim_idx):
    attacker = game.actors[attacker_idx]
    victim = game.actors[victim_idx]
    attacker.hit = victim_idx
    victim.hit_by = attacker_idx
    victim.hit_force = attacker.hit_force


def _raw_body_zv(game, object_idx):
    # GiveZVObjet(HQR_Get(HQ_Bodys, objPtr->body), ...) (animAction.cpp:159):
    # the thrown *world object's* body, never the thrower's (life_ops's
    # VM-bound _body_zv would silently return the wrong actor's body here).
    world = game.world_objects[object_idx]
    if world.body == -1:
        raise ValueError(f"thrown object {object_idx} has no body")
    return list(game.assets.body(world.body).zv)


def _place_thrown_actor(game, actor_idx, x, y, z, raw):
    actor = game.actors[actor_idx]
    actor.room_x = actor.world_x = x
    actor.room_y = actor.world_y = y
    actor.room_z = actor.world_z = z
    actor.zv = [raw[0] + x, raw[1] + x, raw[2] + y, raw[3] + y, raw[4] + z, raw[5] + z]


def _prepare_throw(game, thrower_idx):
    # animAction.cpp:161 case WAIT_ANIM_THROW: build the obstruction cube
    # around the object's landing spot; on collision, drop it back at the
    # thrower instead of arming the throw.
    thrower = game.actors[thrower_idx]
    object_idx = thrower.anim_action_param
    world = game.world_objects[object_idx]
    raw = _raw_body_zv(game, object_idx)
    x = thrower.room_x + thrower.hot_point[0] + thrower.step_x
    y = thrower.room_y + thrower.hot_point[1] + thrower.step_y
    z = thrower.room_z + thrower.hot_point[2] + thrower.step_z
    cube = [raw[0] + x, raw[1] + x, raw[2] + y, raw[3] + y, raw[4] + z, raw[5] + z]
    room = game.rooms_of_floor(game.current_floor)[thrower.room]
    if check_hard_col(cube, room.hard_cols):
        thrower.anim_action_type = 0
        put_at_objet(game, object_idx, thrower.index_in_world)
        return
    if thrower.frame != thrower.anim_action_frame:
        return
    thrower.anim_action_type = WAIT_FRAME_THROW
    remove_from_inventory(game, object_idx)
    world.x, world.y, world.z = x, y, z
    world.room, world.stage = thrower.room, thrower.stage
    world.alpha, world.beta = thrower.alpha, thrower.beta + 0x200
    world.found_flag &= ~0x4000
    world.flags |= 0x85
    world.flags &= ~AF_SPECIAL
    # FITD leaves FlagGenereActiveList commented out here (main.cpp path
    # spawns unconditionally at mainLoop.cpp:247-250); this port gates the
    # spawn behind the flag instead, so state 6 must raise it explicitly.
    game.flag_genere_aff_list = 1


def _launch_throw(game, thrower_idx):
    # animAction.cpp:214 case 7 (THROW): place the object's actor at the
    # release point and hand it off to in-flight state 9 (Task 8).
    thrower = game.actors[thrower_idx]
    thrower.anim_action_type = 0
    object_idx = thrower.anim_action_param
    world = game.world_objects[object_idx]
    if world.obj_index == -1:
        return
    x = thrower.room_x + thrower.hot_point[0] + thrower.step_x
    y = thrower.room_y + thrower.hot_point[1] + thrower.step_y
    z = thrower.room_z + thrower.hot_point[2] + thrower.step_z
    thrown = game.actors[world.obj_index]
    _place_thrown_actor(game, world.obj_index, x, y, z, _raw_body_zv(game, object_idx))
    thrown.object_type |= AF_ANIMATED
    thrown.object_type &= ~AF_BOXIFY
    world.x, world.y, world.z = x, y, z
    world.alpha = thrower.index_in_world
    thrown.dyn_flags = 0
    thrown.anim_action_type = THROW_OBJECT
    thrown.anim_action_param = 100
    thrown.hit_force = thrower.hit_force
    thrown.hot_point_id = -1
    thrown.speed = 3000
    init_real_value(0, thrown.speed, 60, thrown.speed_change, game.timer)


def gere_frappe(game, actor_idx):
    actor = game.actors[actor_idx]
    action = actor.anim_action_type
    if action not in HANDLED_ACTIONS:
        raise ValueError(f"actor {actor_idx} has unsupported anim action {action}")
    if action == WAIT_FRAPPE_ANIM:
        if actor.anim == actor.anim_action_anim:
            actor.anim_action_type = WAIT_FRAPPE_FRAME
        # Same-tick fall-through into WAIT_FRAPPE_FRAME below: FITD
        # animAction.cpp:24 marks this an explicit [[fallthrough]], not a
        # missing break.
        action = actor.anim_action_type
    if action == WAIT_FRAPPE_FRAME:
        if actor.anim != actor.anim_action_anim:
            actor.anim_action_type = 0
            return
        if actor.frame == actor.anim_action_frame:
            actor.anim_action_type = FRAPPE_OK
        return
    if action == FRAPPE_OK:
        if actor.anim != actor.anim_action_anim:
            actor.anim_action_type = 0
        # No early return here: FITD animAction.cpp:48-51 hit-tests on this
        # tick even when the anim mismatch just zeroed anim_action_type.
        x = actor.room_x + actor.hot_point[0] + actor.step_x
        y = actor.room_y + actor.hot_point[1] + actor.step_y
        z = actor.room_z + actor.hot_point[2] + actor.step_z
        radius = actor.anim_action_param
        cube = [x-radius, x+radius, y-radius, y+radius, z-radius, z+radius]
        for victim_idx in check_object_col(game, actor_idx, cube):
            _publish_hit(game, actor_idx, victim_idx)
            if game.actors[victim_idx].object_type & AF_ANIMATED:
                actor.anim_action_type = 0
                return
        return
    if action == HIT_OBJECT:
        return
    if action == WAIT_ANIM_THROW:
        if actor.anim == actor.anim_action_anim:
            _prepare_throw(game, actor_idx)
        return
    if action == WAIT_FRAME_THROW:
        _launch_throw(game, actor_idx)
        return
