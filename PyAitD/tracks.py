# SPDX-License-Identifier: GPL-2.0-only
"""Track runner port (FITD track.cpp processTrack, AITD1 macro set)."""
from PyAitD.formats import _s16 as _read_s16
from PyAitD.game import AF_TRIGGER
from PyAitD.realvalue import give_distance_2d, init_real_value, update_actor_rotation
from PyAitD.world import cdiv as _cdiv, room_delta, rotate_step

TL_INIT_COOR, TL_GOTO, TL_END, TL_REPEAT, TL_MARK = 0, 1, 2, 3, 4
TL_WALK, TL_RUN, TL_STOP, TL_BACK, TL_SET_ANGLE = 5, 6, 7, 8, 9
TL_COL_OFF, TL_COL_ON, TL_SET_DIST, TL_DEC_OFF, TL_DEC_ON = 10, 11, 12, 13, 14
TL_GOTO_3D, TL_MEMO_COOR, TL_GOTO_3DX, TL_GOTO_3DZ, TL_ANGLE, TL_CLOSE = 15, 16, 17, 18, 19, 20

DISTANCE_TO_POINT_TRESSHOLD = 400  # [sic] FITD spelling kept


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


def face_toward(actor, x, z, *, max_steps=256):
    """Instantly face a clicked point without changing track interpolation."""
    for _ in range(max_steps):
        direction = cap_objet(
            actor.room_x + actor.step_x,
            actor.room_z + actor.step_z,
            actor.beta,
            x,
            z,
        )
        if direction == 0:
            actor.direction = 0
            actor.rotate.num_steps = 0
            return
        actor.direction = direction
        actor.beta = (actor.beta - direction * 4) & 0x3FF
    raise RuntimeError(
        f"face_toward beta={actor.beta} target={(x, z)} "
        f"did not converge in {max_steps} steps"
    )


def gere_manual_rot(actor, param, joyd, timer):
    for bit, direction in ((4, 1), (8, -1)):
        if not joyd & bit:
            continue
        if actor.direction != direction:
            actor.rotate.num_steps = 0
        actor.direction = direction
        if actor.rotate.num_steps == 0:
            steps = int(param / 2) if actor.speed == 0 else param
            init_real_value(
                actor.beta, actor.beta + direction * 0x100, steps, actor.rotate, timer,
            )
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
    _turn_toward(game, actor, target_x, target_z)
    actor.speed = 4


def _goto_adjust(game, actor, room_number):
    # TL_GOTO / TL_GOTO_3D: room-diff world adjust (x -, y +, z +)
    return room_delta(game, room_number, actor.room)


def _stairs_walk(game, actor, x, y, z, prop):
    # TL_GOTO_3DX / TL_GOTO_3DZ shared body: prop = interpolated target Y on the active axis
    if actor.room_y + actor.step_y < y - 100 or actor.room_y + actor.step_y > y + 100:
        dif_y = prop - actor.world_y
        actor.world_y += dif_y
        actor.room_y += dif_y
        actor.zv[2] += dif_y
        actor.zv[3] += dif_y
        _turn_toward(game, actor, x, z)
    else:
        dif_y = y - actor.world_y
        actor.step_y = 0
        actor.world_y += dif_y
        actor.room_y += dif_y
        actor.zv[2] += dif_y
        actor.zv[3] += dif_y
        actor.position_in_track += 4


def _turn_toward(game, actor, x, z, *, step=256, time=60):
    # shared TL_* "rotate toward the target point" block (FITD track.cpp)
    angle_modif = cap_objet(
        actor.room_x + actor.step_x, actor.room_z + actor.step_z, actor.beta, x, z
    )
    if actor.rotate.num_steps == 0 or actor.direction != angle_modif:
        init_real_value(
            actor.beta, actor.beta - angle_modif * step, time, actor.rotate, game.timer,
        )
    actor.direction = angle_modif
    if angle_modif:
        actor.beta = update_actor_rotation(actor.rotate, game.timer)
    else:
        actor.rotate.num_steps = 0
    return angle_modif


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
        dx, dy, dz = room_delta(game, actor.room, game.current_room)
        actor.world_x -= dx
        actor.world_y += dy
        actor.world_z += dz
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
            _turn_toward(game, actor, x, z, step=64, time=15)
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
        if actor.y_handler.num_steps == 0:
            init_real_value(0, y - (actor.room_y + actor.step_y), time, actor.y_handler, game.timer)
        _turn_toward(game, actor, x, z)
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


def _process_track_mouse(game, actor):
    # Mouse follower mode. Not a FITD track mode: it generalises
    # _process_track_follow (steer toward a point, speed 4) to a waypoint list,
    # so the player turns *while* walking instead of pivoting in place the way
    # tank controls do. The decision itself is made in playworld.apply_play_input.
    decision = game.nav_decision
    if decision is None or not decision.advance:
        if 0 < actor.speed <= 4:
            actor.speed -= 1
        else:
            actor.speed = 0
        actor.direction = 0
        actor.rotate.num_steps = 0
        return
    _turn_toward(game, actor, decision.target_x, decision.target_z)
    actor.speed = 4


def process_track(game, actor):
    if actor.track_mode == 1:
        _process_track_manual(game, actor)
    elif actor.track_mode == 2:
        _process_track_follow(game, actor)
    elif actor.track_mode == 3:
        _process_track_scripted(game, actor)
    elif actor.track_mode == 4:
        _process_track_mouse(game, actor)
    actor.beta &= 0x3FF
