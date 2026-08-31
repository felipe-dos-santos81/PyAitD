# SPDX-License-Identifier: GPL-2.0-only
"""Object-collision resolution and zone walks (GereDec)."""
from PyAitD.engine.script.interaction.inventory import request_found
from PyAitD.engine.space.world import adjust_zv_between_rooms, room_delta, shifted_zv


def resolve_actor_contacts(game, actor_idx, old_zv, attempted_zv, step_x, step_z):
    from PyAitD.engine.actor.actors import check_hard_col, check_object_col, gere_collision
    from PyAitD.engine.script.game import AF_ANIMATED, AF_BOXIFY, AF_FOUNDABLE, AF_MOVABLE

    actor = game.actors[actor_idx]
    room = game.rooms_of_floor(game.current_floor)[actor.room]
    for touched_idx in check_object_col(game, actor_idx, attempted_zv):
        touched = game.actors[touched_idx]
        touched.col_by = actor_idx
        if touched.object_type & AF_FOUNDABLE:
            if actor.track_mode in game.profile.player_track_modes and game.active_modal is None:
                effect = request_found(game, touched.index_in_world, parameter=0)
                if effect is not None:
                    game.open_modal(effect)
            continue

        touched_zv = touched.zv
        if touched.room != actor.room:
            touched_zv = adjust_zv_between_rooms(game, touched_zv, touched.room, actor.room)
        if touched.object_type & AF_MOVABLE:
            pushed_zv = [
                touched_zv[0] + step_x, touched_zv[1] + step_x,
                touched_zv[2], touched_zv[3],
                touched_zv[4] + step_z, touched_zv[5] + step_z,
            ]
            blocked = bool(check_hard_col(pushed_zv, room.hard_cols))
            if not blocked:
                original_room = touched.room
                touched.room = actor.room
                blocked = bool(check_object_col(game, touched_idx, pushed_zv))
                touched.room = original_room
            if not blocked:
                touched.object_type |= AF_ANIMATED
                touched.object_type &= ~AF_BOXIFY
                touched.world_x += step_x
                touched.world_z += step_z
                touched.room_x += step_x
                touched.room_z += step_z
                touched.zv = pushed_zv
                continue
        if actor.dyn_flags & 1 and (step_x or step_z):
            step_x, step_z = gere_collision(old_zv, attempted_zv, touched_zv, step_x, step_z)
            attempted_zv = [
                old_zv[0] + step_x, old_zv[1] + step_x,
                attempted_zv[2], attempted_zv[3],
                old_zv[4] + step_z, old_zv[5] + step_z,
            ]
    return attempted_zv, step_x, step_z


def point_in_zone(x, y, z, zone):
    return zone.x1 <= x <= zone.x2 and zone.y1 <= y <= zone.y2 and zone.z1 <= z <= zone.z2


def gere_dec(game, actor_idx):
    actor = game.actors[actor_idx]
    rooms = game.rooms_of_floor(game.current_floor)
    room = rooms[actor.room]
    x = actor.room_x + actor.step_x
    y = actor.room_y + actor.step_y
    z = actor.room_z + actor.step_z
    for zone in room.sce_zones:
        if not point_in_zone(x, y, z, zone):
            continue
        if zone.type == 0:
            old_room = actor.room
            actor.room = zone.parameter
            dx, dy, dz = room_delta(game, old_room, actor.room)
            actor.room_x -= dx
            actor.room_y += dy
            actor.room_z += dz
            actor.zv = shifted_zv(actor.zv, dx, dy, dz)
            if actor_idx == game.current_camera_target_actor:
                game.flag_change_salle = 1
                game.new_num_salle = actor.room
            else:
                game.flag_genere_aff_list = 1
        elif zone.type == 9:
            actor.hard_dec = zone.parameter
        elif zone.type == 10:
            world = game.world_objects[actor.index_in_world]
            if world.floor_life == -1:
                return
            actor.life = world.floor_life
            actor.hard_dec = zone.parameter
        return
