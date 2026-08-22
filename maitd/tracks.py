# SPDX-License-Identifier: GPL-2.0-only
"""Track runner port (FITD track.cpp processTrack, AITD1 macro set)."""
import struct

from maitd.game import AF_TRIGGER
from maitd.realvalue import give_distance_2d, init_real_value, update_actor_rotation
from maitd.world import rotate_step

TL_INIT_COOR, TL_GOTO, TL_END, TL_REPEAT, TL_MARK = 0, 1, 2, 3, 4
TL_WALK, TL_RUN, TL_STOP, TL_BACK, TL_SET_ANGLE = 5, 6, 7, 8, 9
TL_COL_OFF, TL_COL_ON, TL_SET_DIST, TL_DEC_OFF, TL_DEC_ON = 10, 11, 12, 13, 14
TL_GOTO_3D, TL_MEMO_COOR, TL_GOTO_3DX, TL_GOTO_3DZ, TL_ANGLE, TL_CLOSE = 15, 16, 17, 18, 19, 20

DISTANCE_TO_POINT_TRESSHOLD = 400  # [sic] FITD spelling kept


def _read_s16(buf, off):
    return struct.unpack_from("<h", buf, off)[0]


def _cdiv(a, b):
    # C integer division: truncation toward zero
    return a // b if a >= 0 else -((-a) // b)


def _rotate(x, z, beta):
    # Rotate port via M2 rotate_step (x_out, z_out) == FITD (xOut, yOut)
    return rotate_step(beta, x, z)


def init_deplacement(actor, mode, number):
    actor.track_mode = mode
    if mode == 2:
        actor.track_number = number
        actor.mark = -1
    elif mode == 3:
        actor.track_number = number
        actor.position_in_track = 0
        actor.mark = -1


def compute_angle_modificator_to_position_sub1(ax, angle_comp_x, angle_comp_z):
    x_out, z_out = _rotate(0, 1000, ax)
    z_out *= angle_comp_z
    x_out *= angle_comp_x
    z_out -= x_out
    if z_out == 0:
        return 0
    return 1 if z_out > 0 else -1


def cap_objet(x1, z1, beta, x2, z2):
    angle_comp_x = x2 - x1
    angle_comp_z = z2 - z1
    result_min = compute_angle_modificator_to_position_sub1(beta - 4, angle_comp_x, angle_comp_z)
    result_max = compute_angle_modificator_to_position_sub1(beta + 4, angle_comp_x, angle_comp_z)
    if result_max == -1 and result_min == 1:
        return compute_angle_modificator_to_position_sub1(beta, angle_comp_x, angle_comp_z)
    return (result_max + result_min + 1) >> 1


def gere_manual_rot(actor, param, joyd, timer):
    if joyd & 4:
        if actor.direction != 1:
            actor.rotate.num_steps = 0
        actor.direction = 1
        if actor.rotate.num_steps == 0:
            old_beta = actor.beta
            if actor.speed == 0:
                init_real_value(old_beta, old_beta + 0x100, int(param / 2), actor.rotate, timer)
            else:
                init_real_value(old_beta, old_beta + 0x100, param, actor.rotate, timer)
        actor.beta = update_actor_rotation(actor.rotate, timer)
    if joyd & 8:
        if actor.direction != -1:
            actor.rotate.num_steps = 0
        actor.direction = -1
        if actor.rotate.num_steps == 0:
            old_beta = actor.beta
            if actor.speed == 0:
                init_real_value(old_beta, old_beta - 0x100, int(param / 2), actor.rotate, timer)
            else:
                init_real_value(old_beta, old_beta - 0x100, param, actor.rotate, timer)
        actor.beta = update_actor_rotation(actor.rotate, timer)
    if not (joyd & 0xC):
        actor.direction = 0
        actor.rotate.num_steps = 0


def get_room_link(game, room1, room2):
    # FITD getRoomLink: hard-col zones (offset at room data +0), type 4 = room link
    zones = game.rooms_of_floor(game.current_floor)[room1].hard_cols
    best = zones[0]
    for zone in zones:
        if zone.type == 4:
            best = zone
            if zone.parameter == room2:
                return zone
    return best


def _process_track_manual(game, actor):
    joyd = game.local_joyd
    gere_manual_rot(actor, 60, joyd, game.timer)
    if joyd & 1:
        if game.timer - game._last_time_forward < 10 and actor.speed != 4:
            actor.speed = 5
        else:
            if actor.speed == 0 or actor.speed == -1:
                actor.speed = 4
        game._last_time_forward = game.timer
    else:
        if 0 < actor.speed <= 4:
            actor.speed -= 1
        else:
            actor.speed = 0
    if joyd & 2:
        if actor.speed == 0 or actor.speed >= 4:
            actor.speed = -1
        if actor.speed == 5:
            actor.speed = 0


def _process_track_follow(game, actor):
    followed_idx = game.world_objects[actor.track_number].obj_index
    if followed_idx == -1:
        actor.direction = 0
        actor.speed = 0
        return
    followed = game.actors[followed_idx]
    target_room = followed.room
    target_x = followed.room_x
    target_y = followed.room_y
    target_z = followed.room_z
    if actor.room != target_room:
        # AITD1: aim for the center of the trigger zone leading to the target room
        link = get_room_link(game, actor.room, target_room)
        target_x = link.x1 + _cdiv(link.x2 - link.x1, 2)
        target_y = link.y1 + _cdiv(link.y2 - link.y1, 2)
        target_z = link.z1 + _cdiv(link.z2 - link.z1, 2)
    angle_modif = cap_objet(
        actor.room_x + actor.step_x, actor.room_z + actor.step_z, actor.beta, target_x, target_z
    )
    if actor.rotate.num_steps == 0 or actor.direction != angle_modif:
        init_real_value(actor.beta, actor.beta - angle_modif * 256, 60, actor.rotate, game.timer)
    actor.direction = angle_modif
    if actor.direction == 0:
        actor.rotate.num_steps = 0
    else:
        actor.beta = update_actor_rotation(actor.rotate, game.timer)
    actor.speed = 4


def _goto_adjust(game, actor, room_number):
    # TL_GOTO / TL_GOTO_3D: room-diff world adjust (x -, y +, z +)
    rooms = game.rooms_of_floor(game.current_floor)
    return (
        (rooms[actor.room].world_x - rooms[room_number].world_x) * 10,
        (rooms[actor.room].world_y - rooms[room_number].world_y) * 10,
        (rooms[actor.room].world_z - rooms[room_number].world_z) * 10,
    )


def _stairs_walk(game, actor, x, y, z, prop):
    # TL_GOTO_3DX / TL_GOTO_3DZ shared body: prop = interpolated target Y on the active axis
    if actor.room_y + actor.step_y < y - 100 or actor.room_y + actor.step_y > y + 100:
        dif_y = prop - actor.world_y
        actor.world_y += dif_y
        actor.room_y += dif_y
        actor.zv[2] += dif_y
        actor.zv[3] += dif_y
        angle_modif = cap_objet(
            actor.room_x + actor.step_x, actor.room_z + actor.step_z, actor.beta, x, z
        )
        if not actor.rotate.num_steps or actor.direction != angle_modif:
            init_real_value(actor.beta, actor.beta - (angle_modif << 8), 60, actor.rotate, game.timer)
        actor.direction = angle_modif
        if angle_modif:
            actor.beta = update_actor_rotation(actor.rotate, game.timer)
        else:
            actor.rotate.num_steps = 0
    else:
        dif_y = y - actor.world_y
        actor.step_y = 0
        actor.world_y += dif_y
        actor.room_y += dif_y
        actor.zv[2] += dif_y
        actor.zv[3] += dif_y
        actor.position_in_track += 4


def _make_proportional(x1, x2, y1, y2):
    return x1 + _cdiv((x2 - x1) * y2, y1)


def _process_track_scripted(game, actor):
    track = game.assets.track(actor.track_number)
    off = actor.position_in_track * 2
    macro = _read_s16(track, off)
    off += 2

    if macro == TL_INIT_COOR:  # warp
        room_number = _read_s16(track, off)
        off += 2
        if actor.room != room_number:
            slot = next((i for i, a in enumerate(game.actors) if a is actor), -1)
            if game.current_camera_target_actor == slot:
                game.flag_change_salle = 1
                game.new_num_salle = room_number
            actor.room = room_number
        zv = actor.zv
        zv[0] -= actor.room_x + actor.step_x
        zv[1] -= actor.room_x + actor.step_x
        zv[2] -= actor.room_y + actor.step_y
        zv[3] -= actor.room_y + actor.step_y
        zv[4] -= actor.room_z + actor.step_z
        zv[5] -= actor.room_z + actor.step_z
        actor.world_x = actor.room_x = _read_s16(track, off)
        off += 2
        actor.world_y = actor.room_y = _read_s16(track, off)
        off += 2
        actor.world_z = actor.room_z = _read_s16(track, off)
        off += 2
        rooms = game.rooms_of_floor(game.current_floor)
        cur, act = rooms[game.current_room], rooms[actor.room]
        actor.world_x -= (cur.world_x - act.world_x) * 10
        actor.world_y += (cur.world_y - act.world_y) * 10
        actor.world_z += (cur.world_z - act.world_z) * 10
        zv[0] += actor.room_x + actor.step_x
        zv[1] += actor.room_x + actor.step_x
        zv[2] += actor.room_y + actor.step_y
        zv[3] += actor.room_y + actor.step_y
        zv[4] += actor.room_z + actor.step_z
        zv[5] += actor.room_z + actor.step_z
        actor.speed = 0
        actor.direction = 0
        actor.rotate.num_steps = 0
        actor.position_in_track += 5
    elif macro == TL_GOTO:
        room_number = _read_s16(track, off)
        off += 2
        x = _read_s16(track, off)
        off += 2
        z = _read_s16(track, off)
        off += 2
        if room_number != actor.room:
            dx, _, dz = _goto_adjust(game, actor, room_number)
            x -= dx
            z += dz
        distance = give_distance_2d(
            actor.room_x + actor.step_x, actor.room_z + actor.step_z, x, z
        )
        if distance >= DISTANCE_TO_POINT_TRESSHOLD:
            angle_modif = cap_objet(
                actor.room_x + actor.step_x, actor.room_z + actor.step_z, actor.beta, x, z
            )
            if actor.rotate.num_steps == 0 or actor.direction != angle_modif:
                init_real_value(actor.beta, actor.beta - angle_modif * 64, 15, actor.rotate, game.timer)
            actor.direction = angle_modif
            if not angle_modif:
                actor.rotate.num_steps = 0
            else:
                actor.beta = update_actor_rotation(actor.rotate, game.timer)
        else:
            actor.position_in_track += 4
    elif macro == TL_GOTO_3D:
        room_number = _read_s16(track, off)
        off += 2
        x = _read_s16(track, off)
        off += 2
        y = _read_s16(track, off)
        off += 2
        z = _read_s16(track, off)
        off += 2
        time = _read_s16(track, off)
        off += 2
        if room_number != actor.room:
            dx, dy, dz = _goto_adjust(game, actor, room_number)
            x -= dx
            y += dy
            z += dz
        if y == actor.room_y:
            distance = give_distance_2d(
                actor.room_x + actor.step_x, actor.room_z + actor.step_z, x, z
            )
            if distance < DISTANCE_TO_POINT_TRESSHOLD:
                actor.position_in_track += 6
                return
        direction = cap_objet(
            actor.room_x + actor.step_x, actor.room_z + actor.step_z, actor.beta, x, z
        )
        if actor.y_handler.num_steps == 0:
            init_real_value(0, y - (actor.room_y + actor.step_y), time, actor.y_handler, game.timer)
        if actor.rotate.num_steps == 0 or actor.direction != direction:
            init_real_value(actor.beta, actor.beta - direction * 256, 60, actor.rotate, game.timer)
        actor.direction = direction
        if not direction:
            actor.rotate.num_steps = 0
        else:
            actor.beta = update_actor_rotation(actor.rotate, game.timer)
    elif macro == TL_END:
        actor.speed = 0
        actor.track_number = -1
        init_deplacement(actor, 0, 0)
    elif macro == TL_REPEAT:
        actor.position_in_track = 0
    elif macro == TL_MARK:
        actor.mark = _read_s16(track, off)
        off += 2
        actor.position_in_track += 2
    elif macro == TL_WALK:
        actor.speed = 4
        actor.position_in_track += 1
    elif macro == TL_RUN:
        actor.speed = 5
        actor.position_in_track += 1
    elif macro == TL_STOP:
        actor.speed = 0
        actor.position_in_track += 1
    elif macro == TL_SET_ANGLE:
        beta_dif = _read_s16(track, off)
        off += 2
        if (actor.beta - beta_dif) & 0x3FF > 0x200:
            actor.direction = 1  # left
        else:
            actor.direction = -1  # right
        if not actor.rotate.num_steps:
            init_real_value(actor.beta, beta_dif, 120, actor.rotate, game.timer)
        actor.beta = update_actor_rotation(actor.rotate, game.timer)
        if actor.beta == beta_dif:
            actor.direction = 0
            actor.position_in_track += 2
    elif macro == TL_COL_OFF:
        actor.dyn_flags &= ~1
        actor.position_in_track += 1
    elif macro == TL_COL_ON:
        actor.dyn_flags |= 1
        actor.position_in_track += 1
    elif macro == TL_DEC_OFF:
        actor.object_type &= ~AF_TRIGGER
        actor.position_in_track += 1
    elif macro == TL_DEC_ON:
        actor.object_type |= AF_TRIGGER
        actor.position_in_track += 1
    elif macro == TL_MEMO_COOR:
        obj = game.world_objects[actor.index_in_world]
        obj.x = actor.room_x + actor.step_x
        obj.y = actor.room_y + actor.step_y
        obj.z = actor.room_z + actor.step_z
        actor.position_in_track += 1
    elif macro == TL_GOTO_3DX:
        x = _read_s16(track, off)
        off += 2
        y = _read_s16(track, off)
        off += 2
        z = _read_s16(track, off)
        off += 2
        obj = game.world_objects[actor.index_in_world]
        prop = _make_proportional(
            obj.y, y, x - obj.x, (actor.room_x + actor.step_x) - obj.x
        )
        _stairs_walk(game, actor, x, y, z, prop)
    elif macro == TL_GOTO_3DZ:
        x = _read_s16(track, off)
        off += 2
        y = _read_s16(track, off)
        off += 2
        z = _read_s16(track, off)
        off += 2
        obj = game.world_objects[actor.index_in_world]
        prop = _make_proportional(
            obj.y, y, z - obj.z, (actor.room_z + actor.step_z) - obj.z
        )
        _stairs_walk(game, actor, x, y, z, prop)
    elif macro == TL_ANGLE:
        actor.alpha = _read_s16(track, off)
        off += 2
        actor.beta = _read_s16(track, off)
        off += 2
        actor.gamma = _read_s16(track, off)
        off += 2
        actor.direction = 0
        actor.position_in_track += 4
    else:
        # TL_BACK (8), TL_SET_DIST (12), TL_CLOSE (20): no case in FITD switch
        raise ValueError(f"unknown track macro {macro:#x}")


def process_track(game, actor):
    if actor.track_mode == 1:
        _process_track_manual(game, actor)
    elif actor.track_mode == 2:
        _process_track_follow(game, actor)
    elif actor.track_mode == 3:
        _process_track_scripted(game, actor)
    actor.beta &= 0x3FF
