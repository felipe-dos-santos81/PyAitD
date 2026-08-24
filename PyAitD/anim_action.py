# SPDX-License-Identifier: GPL-2.0-only
"""Per-actor animation action runner (FITD animAction.cpp GereFrappe et al.).

Consumes the previous tick's cached hot point (refreshed by
`refresh_hot_point`, called just before `gere_anim` in playworld's per-actor
pass) to build a strike cube and publish hits through `check_object_col`.
Never touches actor.life: health lives in script vars, hit/hit_by/hit_force
are the only fields this module writes.
"""
from PyAitD.actors import anim_player_for, check_hard_col, check_object_col, cube_intersect
from PyAitD.game import AF_ANIMATED, AF_BOXIFY, AF_SPECIAL, activate_world_object, put_at_objet
from PyAitD.interaction import point_in_zone, remove_from_inventory
from PyAitD.realvalue import init_real_value
from PyAitD.skel import hot_point
from PyAitD.world import adjust_zv_between_rooms, cdiv, rotate_step

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


def _hot_point_world(actor):
    # animAction.cpp:51-53 / 165-167 / 218-220: room position + cached hot
    # point + the in-progress step delta, shared by the melee strike cube
    # and both throw placements. Task 7's DO_TIR omits the step terms and
    # Task 8's in-flight position is different again, so this covers only
    # this exact triple — not a general "actor world position" helper.
    x = actor.room_x + actor.hot_point[0] + actor.step_x
    y = actor.room_y + actor.hot_point[1] + actor.step_y
    z = actor.room_z + actor.hot_point[2] + actor.step_z
    return x, y, z


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
    x, y, z = _hot_point_world(thrower)
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
    activate_world_object(game, object_idx)


def _launch_throw(game, thrower_idx):
    # animAction.cpp:214 case 7 (THROW): place the object's actor at the
    # release point and hand it off to in-flight state 9 (Task 8).
    thrower = game.actors[thrower_idx]
    thrower.anim_action_type = 0
    object_idx = thrower.anim_action_param
    world = game.world_objects[object_idx]
    if world.obj_index == -1:
        return
    x, y, z = _hot_point_world(thrower)
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


def throw_stopped_at(game, actor_idx, x, z):
    # main.cpp:4036-4132 throwStoppedAt: search backward (away from the
    # thrower, beta+0x200) in 100-unit steps for a hard-collision-free spot,
    # then hunt upward in 2000-unit bands for one Carnby can actually reach.
    actor = game.actors[actor_idx]
    raw = _raw_body_zv(game, actor.index_in_world)
    # main.cpp:4051: C integer division truncates toward zero, unlike
    # Python's floor `//` — they diverge for negative room_y that isn't
    # an exact multiple of 2000 (e.g. the pinned combat venue's own hero
    # Y, -4010). Use cdiv, not `//`, to preserve that truncation.
    x2, y2, z2 = x, cdiv(actor.room_y, 2000) * 2000, z
    step = 0
    room = game.rooms_of_floor(game.current_floor)[actor.room]
    while True:
        move_z, move_x = rotate_step(actor.beta + 0x200, 0, -step)
        x2, z2 = x + move_x, z + move_z
        cube = [raw[0]+x2, raw[1]+x2, raw[2]+y2, raw[3]+y2, raw[4]+z2, raw[5]+z2]
        if check_hard_col(cube, room.hard_cols):
            step += 100
            continue
        if y2 < -500:
            reachable = list(cube)
            reachable[2] += 100; reachable[3] += 100
            if not check_hard_col(reachable, room.hard_cols):
                y2 += 2000
                continue
        break
    actor.world_x = actor.room_x = x2
    actor.world_y = actor.room_y = y2
    actor.world_z = actor.room_z = z2
    actor.step_x = actor.step_z = 0
    actor.anim_action_type = actor.speed = actor.gamma = 0
    actor.zv = [raw[0]+x2, raw[1]+x2, raw[2]+y2, raw[3]+y2, raw[4]+z2, raw[5]+z2]
    world = game.world_objects[actor.index_in_world]
    world.found_flag |= 0x4000
    world.found_flag &= ~0x1000


def _check_throw_step(
    game, actor_idx, actor, world, room, cube, x2, y2, z2,
    actual_x, actual_y, actual_z, old_x, old_y, old_z, raw_zv,
):
    # animAction.cpp:335-425, one swept cube of case 9. Returns True once
    # the in-flight object has been resolved for this tick (hit, reflected,
    # or stopped); False to keep sweeping.
    collisions = check_object_col(game, actor_idx, cube)
    effective = len(collisions)
    if collisions:
        # animAction.cpp:339-341: hotPoint is cleared as soon as ANY object
        # collision is found this tick, before the per-actor loop below —
        # not only on the trailing hard-collision branch further down.
        actor.hot_point[:] = [0, 0, 0]
    for touched_idx in collisions:
        touched_world = game.actors[touched_idx].index_in_world
        if touched_world == world.alpha:
            # animAction.cpp:349-356: the original thrower doesn't count as
            # a hit and returns immediately (skipping the `if(collision2)`
            # check below) even if an earlier COL[] entry this same tick
            # already published a hit on someone else.
            effective -= 1
            world.x, world.y, world.z = actual_x, actual_y, actual_z
            return True
        if touched_world == game.cvars[11]:
            world.alpha = game.cvars[11]
            actor.beta += 0x200
            _place_thrown_actor(game, actor_idx, old_x, old_y, old_z, raw_zv)
            # animAction.cpp:378-379: FITD zeroes stepX/stepZ here but
            # leaves stepY untouched — preserve that asymmetry exactly.
            actor.step_x = actor.step_z = 0
            # animAction.cpp:389,399-401: xtemp/ztemp are reassigned to
            # x3/z3 (old_x/old_z) right before commit, but ytemp is never
            # reassigned in this branch — so the committed world position
            # mixes the reverted x/z with the tick's actual (stepped) y.
            world.x, world.y, world.z = old_x, actual_y, old_z
            return True
        _publish_hit(game, actor_idx, touched_idx)
    if effective:
        throw_stopped_at(game, actor_idx, old_x, old_z)
        return True
    zone = next(
        (item for item in room.sce_zones if point_in_zone(x2, y2, z2, item)),
        None,
    )
    if zone is not None and zone.type in (0, 10):
        throw_stopped_at(game, actor_idx, old_x, old_z)
        return True
    if check_hard_col(cube, room.hard_cols):
        actor.hot_point[:] = [0, 0, 0]
        throw_stopped_at(game, actor_idx, old_x, old_z)
        return True
    return False


def _throw_in_flight(game, actor_idx):
    # animAction.cpp:271-441 case 9 (during throw): sweep the thrown
    # object's world position 100 units at a time, away from its last
    # committed spot along beta, checking actor/zone/hard collisions at
    # each cube. Stops sweeping once the swept X/Z lands back inside the
    # actor's own ZV (expanded by 100 on each side) — at that point the
    # object's normal per-tick movement has caught up with the sweep, so
    # the tick commits the actor's actual (stepped) position.
    actor = game.actors[actor_idx]
    world = game.world_objects[actor.index_in_world]
    room = game.rooms_of_floor(game.current_floor)[actor.room]

    actual_x = actor.room_x + actor.step_x
    actual_y = actor.room_y + actor.step_y
    actual_z = actor.room_z + actor.step_z
    raw_zv = [
        actor.zv[0] - actual_x, actor.zv[1] - actual_x,
        actor.zv[2] - actual_y, actor.zv[3] - actual_y,
        actor.zv[4] - actual_z, actor.zv[5] - actual_z,
    ]
    old_x, old_y, old_z = world.x, world.y, world.z

    step = 0
    while True:
        move_z, move_x = rotate_step(actor.beta, 0, -step)
        step += 100
        x2, z2 = old_x + move_x, old_z + move_z
        y2 = old_y
        cube = [x2-200, x2+200, y2-200, y2+200, z2-200, z2+200]
        if _check_throw_step(
            game, actor_idx, actor, world, room, cube, x2, y2, z2,
            actual_x, actual_y, actual_z, old_x, old_y, old_z, raw_zv,
        ):
            return
        if not (
            actor.zv[0] - 100 > x2 or actor.zv[1] + 100 < x2
            or actor.zv[4] - 100 > z2 or actor.zv[5] + 100 < z2
        ):
            break
    world.x, world.y, world.z = actual_x, actual_y, actual_z


def check_line_projection_with_actors(game, actor_idx, x, y, z, beta, room, param):
    # animAction.cpp:3863-3946 checkLineProjectionWithActors: an 84-line
    # integer stepped-volume sweep, not a screen-space raycast. The cube
    # walks by walkStep(param*2, 0, beta) increments each iteration (ported
    # here as rotate_step, unpacked crossed to preserve walkStep's output
    # convention). Per FITD's counterintuitive AsmCheckListCol branch, the
    # sweep terminates with NO hit the instant the cube stops overlapping
    # any hard-collision entry — this is verified source behaviour, not a
    # bug to "fix" into a conventional raycast.
    local = [x-param, x+param, y-param, y+param, z-param, z+param]
    move_z, move_x = rotate_step(beta, param * 2, 0)
    impact_x, impact_z = x, z
    while True:
        local[0] += move_x; local[1] += move_x
        local[4] += move_z; local[5] += move_z
        impact_x, impact_z = x, z
        x += move_x; z += move_z
        if x > 20000 or x < -20000 or z > 20000 or z < -20000:
            return (-1, impact_x, y, impact_z)
        hard_cols = game.rooms_of_floor(game.current_floor)[room].hard_cols
        if not check_hard_col(local, hard_cols):
            return (-1, impact_x, y, impact_z)
        for other_idx, other in enumerate(game.actors):
            if other.index_in_world == -1 or other_idx == actor_idx:
                continue
            if other.object_type & AF_SPECIAL:
                continue
            candidate = local if other.room == room else adjust_zv_between_rooms(
                game, local, room, other.room,
            )
            if cube_intersect(candidate, other.zv):
                return (other_idx, impact_x, y, impact_z)


def _gere_fire(game, actor_idx, actor, action):
    # animAction.cpp:92-150 case WAIT_TIR_ANIM / DO_TIR. InitSpecialObjet's
    # muzzle-flash and impact visuals are out of scope for this port: combat
    # publishes hit/hit_by/hit_force only, never actor.life.
    if action == WAIT_TIR_ANIM:
        if actor.anim == actor.anim_action_anim and actor.frame == actor.anim_action_frame:
            actor.anim_action_type = DO_TIR
        return
    if action == DO_TIR:
        victim_idx, impact_x, impact_y, impact_z = check_line_projection_with_actors(
            game, actor_idx,
            actor.room_x + actor.hot_point[0],
            actor.room_y + actor.hot_point[1],
            actor.room_z + actor.hot_point[2],
            actor.beta - 0x100, actor.room, actor.anim_action_param,
        )
        if victim_idx != -1:
            actor.hot_point[:] = [
                impact_x - actor.room_x,
                impact_y - actor.room_y,
                impact_z - actor.room_z,
            ]
            _publish_hit(game, actor_idx, victim_idx)
        actor.anim_action_type = 0


def gere_frappe(game, actor_idx):
    actor = game.actors[actor_idx]
    action = actor.anim_action_type
    if action not in HANDLED_ACTIONS:
        raise ValueError(f"actor {actor_idx} has unsupported anim action {action}")
    if action in (WAIT_FRAPPE_ANIM, WAIT_FRAPPE_FRAME):
        # FITD animAction.cpp:19-24: case WAIT_FRAPPE_ANIM carries an
        # explicit [[fallthrough]] into case WAIT_FRAPPE_FRAME
        # (animAction.cpp:25-34) *unconditionally* — not only when the anim
        # already matched. WAIT_FRAPPE_FRAME's first statement then cancels
        # the melee (anim_action_type = 0) whenever the anim doesn't match,
        # so a state-1 actor whose anim never committed is disarmed on the
        # very next gere_frappe call, not left armed forever.
        if action == WAIT_FRAPPE_ANIM and actor.anim == actor.anim_action_anim:
            actor.anim_action_type = WAIT_FRAPPE_FRAME
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
        x, y, z = _hot_point_world(actor)
        radius = actor.anim_action_param
        cube = [x-radius, x+radius, y-radius, y+radius, z-radius, z+radius]
        for victim_idx in check_object_col(game, actor_idx, cube):
            _publish_hit(game, actor_idx, victim_idx)
            if game.actors[victim_idx].object_type & AF_ANIMATED:
                actor.anim_action_type = 0
                return
        return
    if action == WAIT_TIR_ANIM:
        _gere_fire(game, actor_idx, actor, action)
        return
    if action == DO_TIR:
        _gere_fire(game, actor_idx, actor, action)
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
    if action == THROW_OBJECT:
        _throw_in_flight(game, actor_idx)
        return
