# SPDX-License-Identifier: GPL-2.0-only
"""World object <-> actor slot lifecycle (InitObjet/DeleteObjet/PutAtObjet/GenereActiveList)."""
from PyAitD.engine.space.world import cdiv as _cdiv, room_delta
from PyAitD.engine.script.game.state import (
    AF_ANIMATED, AF_BOXIFY, AF_DRAWABLE, AF_SPECIAL, RealValue,
)
from PyAitD.engine.script.game.zv import (
    _hard_zv, _zv_cube, _zv_default, _zv_max, _zv_rot,
)


def add_actor(game, world_idx):
    # InitObjet port (object.cpp:3): copies tWorldObject -> tObject slot.
    # Returns the actor slot idx or -1.
    obj = game.world_objects[world_idx]
    slot = next((i for i, a in enumerate(game.actors) if a.index_in_world == -1), -1)
    if slot == -1:
        return -1
    actor = game.actors[slot]

    actor.body_num = obj.body
    actor.object_type = obj.flags & ~AF_SPECIAL
    actor.stage = obj.stage
    actor.room = obj.room
    actor.world_x = actor.room_x = obj.x
    actor.world_y = actor.room_y = obj.y
    actor.world_z = actor.room_z = obj.z

    x, y, z = obj.x, obj.y, obj.z
    if obj.type_zv == 4:
        zv = _hard_zv(game, obj.room, obj.found_name)
        if zv is not None:
            # hard zv: coords are the ZV midpoints (object.cpp:209)
            x = y = z = 0
            actor.world_x = actor.room_x = _cdiv(zv[0], 2) + _cdiv(zv[1], 2)
            actor.world_y = actor.room_y = _cdiv(zv[2], 2) + _cdiv(zv[3], 2)
            actor.world_z = actor.room_z = _cdiv(zv[4], 2) + _cdiv(zv[5], 2)
        else:
            zv = _zv_default()
    elif obj.body == -1:
        zv = _zv_default()
    else:
        body_zv = game.assets.body(obj.body).zv
        if obj.type_zv == 0:
            zv = _zv_max(body_zv)
        elif obj.type_zv == 1:
            zv = list(body_zv)
        elif obj.type_zv == 2:
            zv = _zv_cube(body_zv)
        elif obj.type_zv == 3:
            zv = _zv_rot(body_zv, obj.alpha, obj.beta, obj.gamma)
        else:
            zv = _zv_default()

    if obj.room != game.current_room:
        dx, dy, dz = room_delta(game, obj.room, game.current_room)
        actor.world_x -= dx
        actor.world_y += dy
        actor.world_z += dz

    actor.alpha = obj.alpha
    actor.beta = obj.beta
    actor.gamma = obj.gamma

    actor.dyn_flags = 1

    actor.anim = obj.anim
    actor.frame = obj.frame
    actor.anim_type = obj.anim_type
    actor.anim_info = obj.anim_info

    actor.end_frame = 1
    actor.flag_end_anim = 1
    actor.new_anim = -1
    actor.new_anim_type = 0
    actor.new_anim_info = -1

    actor.step_x = 0
    actor.step_y = 0
    actor.step_z = 0
    actor.anim_neg_x = 0
    actor.anim_neg_y = 0
    actor.anim_neg_z = 0
    actor.speed_change = RealValue()

    actor.col = [-1, -1, -1]
    actor.col_by = -1
    actor.hard_dec = -1
    actor.hard_col = -1

    actor.rotate = RealValue()
    actor.y_handler = RealValue()

    actor.falling = 0
    actor.direction = 0
    actor.speed = 0

    actor.track_mode = 0
    actor.track_number = -1

    actor.anim_action_type = 0
    actor.hit = -1
    actor.hit_by = -1

    if obj.body != -1:
        if obj.anim != -1:
            actor.num_of_frames = game.assets.anim(obj.anim).num_frames
            actor.flag_end_anim = 0
            actor.object_type |= AF_ANIMATED
        elif not (actor.object_type & AF_DRAWABLE):
            actor.object_type &= ~AF_ANIMATED  # do not animate an invisible object

    actor.zv = [zv[0] + x, zv[1] + x, zv[2] + y, zv[3] + y, zv[4] + z, zv[5] + z]

    return slot


def _delete_objet(game, index):
    # DeleteObjet port (main.cpp:1663)
    actor = game.actors[index]
    if actor.index_in_world == -2:  # flow
        actor.index_in_world = -1
        if actor.anim == 4:
            game.cvars[game.profile.cvar_index("FOG_FLAG")] = 0
        return
    if actor.index_in_world >= 0:
        obj = game.world_objects[actor.index_in_world]
        obj.obj_index = -1
        actor.index_in_world = -1
        obj.body = actor.body_num
        obj.anim = actor.anim
        obj.frame = actor.frame
        obj.anim_type = actor.anim_type
        obj.anim_info = actor.anim_info
        obj.flags = actor.object_type & ~AF_BOXIFY
        obj.flags |= AF_SPECIAL * actor.dyn_flags
        obj.life = actor.life
        obj.life_mode = actor.life_mode
        obj.track_mode = actor.track_mode
        if obj.track_mode:
            obj.track_number = actor.track_number
            obj.position_in_track = actor.position_in_track
        obj.x = actor.room_x + actor.step_x
        obj.y = actor.room_y + actor.step_y
        obj.z = actor.room_z + actor.step_z
        obj.alpha = actor.alpha
        obj.beta = actor.beta
        obj.gamma = actor.gamma
        obj.stage = actor.stage
        obj.room = actor.room
        game.flag_genere_aff_list = 1


def delete_object(game, obj_idx):
    # deleteObject port (main.cpp:2372): AITD1 delete opcode
    obj = game.world_objects[obj_idx]
    actor_idx = obj.obj_index
    if actor_idx != -1:
        actor = game.actors[actor_idx]
        actor.room = -1
        actor.stage = -1
        actor.index_in_world = -1
    obj.obj_index = -1
    obj.room = -1
    obj.stage = -1
    from PyAitD.engine.script.interaction import remove_from_inventory
    remove_from_inventory(game, obj_idx)


def put_at_objet(game, obj_idx, obj_idx_to_put_at):
    # PutAtObjet port (main.cpp:3948)
    obj = game.world_objects[obj_idx]
    put_at = game.world_objects[obj_idx_to_put_at]
    if put_at.obj_index != -1:
        src = game.actors[put_at.obj_index]
        x, y, z = src.room_x, src.room_y, src.room_z
        room, stage = src.room, src.stage
        alpha, beta, gamma = src.alpha, src.beta, src.gamma
    else:
        x, y, z = put_at.x, put_at.y, put_at.z
        room, stage = put_at.room, put_at.stage
        alpha, beta, gamma = put_at.alpha, put_at.beta, put_at.gamma
    if obj.obj_index == -1:
        obj.x, obj.y, obj.z = x, y, z
        obj.room, obj.stage = room, stage
        obj.alpha, obj.beta, obj.gamma = alpha, beta, gamma
        obj.found_flag |= 0x4000
        obj.flags |= 0x80
    else:
        actor = game.actors[obj.obj_index]
        actor.room_x, actor.room_y, actor.room_z = x, y, z
        actor.room, actor.stage = room, stage
        actor.alpha, actor.beta, actor.gamma = alpha, beta, gamma
        game.world_objects[actor.index_in_world].found_flag |= 0x4000
        game.world_objects[actor.index_in_world].flags |= 0x80
    from PyAitD.engine.script.interaction import remove_from_inventory
    remove_from_inventory(game, obj_idx)


def activate_world_object(game, world_idx):
    """Initialize one staged world object, or return its existing actor."""
    from PyAitD.engine.actor.tracks import init_deplacement

    obj = game.world_objects[world_idx]
    if obj.obj_index != -1:
        return obj.obj_index
    obj.obj_index = add_actor(game, world_idx)
    if obj.obj_index == -1:
        return -1

    actor = game.actors[obj.obj_index]
    if game.current_world_target == world_idx:
        game.current_camera_target_actor = obj.obj_index
    actor.dyn_flags = (obj.flags & 0x20) // 0x20
    actor.life = obj.life
    actor.life_mode = obj.life_mode
    actor.index_in_world = world_idx
    init_deplacement(actor, obj.track_mode, obj.track_number)
    actor.position_in_track = obj.position_in_track
    game.flag_genere_aff_list = 1
    return obj.obj_index


def spawn_stage_actors(game):
    # GenereActiveList port (main.cpp:1990-2130)
    for i, actor in enumerate(game.actors):
        if actor.index_in_world == -1:
            continue
        if actor.stage == game.current_floor:
            if actor.life != -1:
                if actor.life_mode == 0:
                    continue  # STAGE: keep
                if actor.life_mode == 1 and actor.room == game.current_room:
                    continue  # ROOM: keep
                # ponytail: life_mode 2 keeps (FITD: isInViewList with the
                # selected camera) — needs camera state, M4+
                if actor.life_mode == 2:
                    continue
                # default (incl life_mode == -1): delete
            else:
                # ponytail: life == -1 keeps (FITD: isInViewList), M4+
                continue
        _delete_objet(game, i)

    for i, obj in enumerate(game.world_objects):
        if obj.obj_index != -1:
            if game.current_world_target == i:
                game.current_camera_target_actor = obj.obj_index
            continue
        if obj.stage != game.current_floor:
            continue
        if obj.life != -1:
            if obj.life_mode == -1:
                continue
            if obj.life_mode == 1 and obj.room != game.current_room:
                continue
            # ponytail: life_mode 2 passes unconditionally (FITD: isInViewList), M4+
        # ponytail: life == -1 passes unconditionally (FITD: isInViewList), M4+

        activate_world_object(game, i)
