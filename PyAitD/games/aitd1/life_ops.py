# SPDX-License-Identifier: GPL-2.0-only
"""Full-dispatch opcode handlers (life.cpp switch bodies, AITD1)."""
import logging

from PyAitD.engine.actor.actors import cube_intersect
from PyAitD.engine.actor.anim import init_anim
from PyAitD.engine.script.effects import AddMessage, BeginTake, ReadText, ShowPicture
from PyAitD.engine.script.game import AF_ANIMATED, AF_MASK, FloorStart, _zv_cube, _zv_max, _zv_rot, relocate_actor
from PyAitD.engine.script.life import eval_var, read_s16
from PyAitD.engine.space.realvalue import init_real_value, update_actor_rotation
from PyAitD.engine.actor.tracks import gere_manual_rot, init_deplacement
from PyAitD.engine.space.world import room_delta

log = logging.getLogger(__name__)


def _add_room(a, zv):
    return [
        zv[0] + a.room_x, zv[1] + a.room_x,
        zv[2] + a.room_y, zv[3] + a.room_y,
        zv[4] + a.room_z, zv[5] + a.room_z,
    ]


def _body_zv(vm):
    return vm.game.assets.body(vm.actor.body_num).zv


def op_anim_once(vm):
    # life.cpp:938
    a = vm.actor
    anim = read_s16(vm)
    flags = read_s16(vm)
    if anim == -1:
        a.anim = -1
        a.new_anim = -2
    else:
        init_anim(a, anim, 0, flags)


def op_anim_all_once(vm):
    # life.cpp:966
    init_anim(vm.actor, read_s16(vm), 2, read_s16(vm))


def op_anim_repeat(vm):
    # life.cpp:957
    init_anim(vm.actor, read_s16(vm), 1, -1)


def op_body(vm):
    # life.cpp:736
    a = vm.actor
    game = vm.game
    v = eval_var(vm)
    game.world_objects[a.index_in_world].body = v
    if a.body_num != v:
        a.body_num = v
        if a.object_type & AF_ANIMATED:
            if a.anim != -1 and a.body_num != -1:
                # SetInterAnimObjet: mesh switch lands with the AnimPlayer (task 11)
                pass
        else:
            game.flag_init_view = 1


def op_hit(vm):
    # main.cpp:4375 hit(): arm melee only when InitAnim accepts the anim;
    # a rejection still consumes every operand but leaves prior state alone.
    from PyAitD.engine.actor.anim_action import arm_strike  # lazy like op_delete's: anim_action pulls in script.interaction
    anim = read_s16(vm)  # anim
    frame = read_s16(vm)  # startFrame
    group = read_s16(vm)  # groupNumber
    radius = read_s16(vm)  # hitBoxSize
    force = eval_var(vm)  # hitForce
    next_anim = read_s16(vm)  # nextAnim
    arm_strike(vm.actor, anim, frame, group, radius, force, next_anim)


def op_move(vm):
    # life.cpp:1166: InitDeplacement(trackMode, trackNumber)
    init_deplacement(vm.actor, read_s16(vm), read_s16(vm))


def op_anim_move(vm):
    # life.cpp:1203 + animMove (life.cpp:252)
    a = vm.actor
    stand = read_s16(vm)
    walk = read_s16(vm)
    run = read_s16(vm)
    stop = read_s16(vm)
    backward = read_s16(vm)
    turn_right = read_s16(vm)
    turn_left = read_s16(vm)
    if a.speed == 5:
        init_anim(a, run, 1, -1)
    if a.speed == 4:
        init_anim(a, walk, 1, -1)
    if a.speed == -1:  # backward
        if a.anim == walk:
            init_anim(a, stand, 0, backward)
        elif a.anim == run:
            init_anim(a, stop, 0, stand)
        else:
            init_anim(a, backward, 1, -1)
    if a.speed == 0:
        if a.anim == walk or a.anim == run:
            init_anim(a, stop, 0, stand)
        else:
            if a.direction == 0:
                init_anim(a, stand, 1, -1)
            if a.direction == 1:  # left
                init_anim(a, turn_left, 0, stand)
            if a.direction == -1:  # right
                init_anim(a, turn_right, 0, stand)


def op_message(vm):
    # life.cpp:2164: makeMessage(raw)
    vm.game.emit(AddMessage(read_s16(vm)))


def op_message_value(vm):
    # life.cpp:2174
    message_id = read_s16(vm)
    read_s16(vm)  # unused param in FITD
    vm.game.emit(AddMessage(message_id))


def op_found(vm):
    # life.cpp:1454: FoundObjet(id, 1)
    from PyAitD.engine.script.interaction import request_found
    effect = request_found(vm.game, read_s16(vm), parameter=1)
    if effect is not None:
        vm.suspend(effect)


def op_life(vm):
    # life.cpp:1329
    vm.actor.life = read_s16(vm)


def op_delete(vm):
    # life.cpp:1362
    from PyAitD.engine.script.game import delete_object
    game = vm.game
    idx = read_s16(vm)
    delete_object(game, idx)
    if game.world_objects[idx].found_body != -1:
        game.world_objects[idx].found_flag &= ~0x8000
        game.world_objects[idx].found_flag |= 0x4000


def op_take(vm):
    # life.cpp:1477: take(id)
    vm.suspend(BeginTake(read_s16(vm)))


def op_in_hand(vm):
    # life.cpp:1496
    vm.game.in_hand_table[vm.game.current_inventory] = read_s16(vm)


def op_read(vm):
    # life.cpp:1620: readBook(entry + 1, kind); AITD1 skips one extra word
    # (VOC files for the text)
    kind = read_s16(vm)
    entry = read_s16(vm)
    read_s16(vm)  # AITD1 extra digit
    vm.game.flag_init_view = 2
    vm.suspend(ReadText(text_index=entry + 1, kind=kind))


def op_anim_sample(vm):
    # life.cpp:1685 — M3b audio stub
    sample = eval_var(vm)
    anim = read_s16(vm)
    frame = read_s16(vm)
    log.debug("LM_ANIM_SAMPLE %d anim %d frame %d (M3b audio stub)", sample, anim, frame)


def op_special(vm):
    # life.cpp:1388: InitSpecialObjet — M3b visual-effect stub
    log.debug("LM_SPECIAL %d (M3b stub)", read_s16(vm))


def op_do_real_zv(vm):
    # life.cpp:810: doRealZv transforms the body vertex list (computeScreenBox);
    # M3a approximates with the rotated body ZV box, i.e. the getZvRot path.
    # ponytail: when computeScreenBox lands, this stops delegating.
    op_do_rot_zv(vm)


def op_sample(vm):
    # life.cpp:1730 — M3b audio stub
    log.debug("LM_SAMPLE %d (M3b audio stub)", eval_var(vm))


def op_type(vm):
    # life.cpp:901: objectType = (objectType & ~AF_MASK) + (arg & AF_MASK)
    a = vm.actor
    v = read_s16(vm) & AF_MASK
    a.object_type = (a.object_type & ~AF_MASK) + v


def op_game_over(vm):
    # life.cpp:2438: M3a — skip music fade + 120-tick spin
    vm.game.flag_game_over = 1
    vm.exit = True


def op_manual_rot(vm):
    # life.cpp:1218: AITD1 GereManualRot(240)
    gere_manual_rot(vm.actor, 240, vm.game.local_joyd, vm.game.timer)


def op_rnd_freq(vm):
    # life.cpp:1869: arg ignored
    log.debug("LM_RND_FREQ %d (stub)", read_s16(vm))


def op_music(vm):
    # life.cpp:1823 — M3b audio stub
    log.debug("LM_MUSIC %d (M3b audio stub)", read_s16(vm))


def op_set_beta(vm):
    # life.cpp:1231
    a = vm.actor
    beta = read_s16(vm)
    speed = read_s16(vm)
    if a.beta != beta:
        if a.rotate.num_steps == 0 or a.rotate.end_value != beta:
            init_real_value(a.beta, beta, speed, a.rotate, vm.game.timer)
        a.beta = update_actor_rotation(a.rotate, vm.game.timer)


def op_do_rot_zv(vm):
    # life.cpp:856: getZvRot(body, zv, alpha, beta, gamma) + room offsets
    vm.actor.zv = _add_room(vm.actor, _zv_rot(_body_zv(vm), vm.actor.alpha, vm.actor.beta, vm.actor.gamma))


def op_stage(vm):
    # life.cpp:1293 + setStage (life.cpp:306)
    game = vm.game
    new_stage = read_s16(vm)
    new_room = read_s16(vm)
    x = read_s16(vm)
    y = read_s16(vm)
    z = read_s16(vm)

    relocate_actor(game, vm.cur_idx, new_stage, new_room, x, y, z)

    if game.current_camera_target_actor == vm.cur_idx:
        if new_stage != game.current_floor:
            game.floor_start = FloorStart(new_stage, new_room, x, y, z, 0)
            game.flag_change_etage = 1
            game.new_num_etage = new_stage
            game.new_num_salle = new_room
        elif game.current_room != new_room:
            game.flag_change_salle = 1
            game.new_num_salle = new_room
    elif game.current_room != new_room:
        actor = game.actors[vm.cur_idx]
        dx, dy, dz = room_delta(game, new_room, game.current_room)
        actor.world_x -= dx
        actor.world_y += dy
        actor.world_z += dz


def op_found_name(vm):
    # life.cpp:1580
    vm.game.world_objects[vm.actor.index_in_world].found_name = read_s16(vm)


def op_found_flag(vm):
    # life.cpp:1596
    obj = vm.game.world_objects[vm.actor.index_in_world]
    obj.found_flag = (obj.found_flag & 0xE000) | read_s16(vm)


def op_found_life(vm):
    # life.cpp:1612
    vm.game.world_objects[vm.actor.index_in_world].found_life = read_s16(vm)


def op_camera_target(vm):
    # life.cpp:1934, AITD1 branch
    game = vm.game
    target = read_s16(vm)
    if target != game.current_world_target:
        obj = game.world_objects[target]
        if obj.obj_index != -1:
            game.current_world_target = target
            game.current_camera_target_actor = obj.obj_index
            room = game.actors[obj.obj_index].room
            if room != game.current_room:
                game.flag_change_salle = 1
                game.new_num_salle = room
        else:  # different stage
            game.current_world_target = target
            if obj.stage != game.current_floor:
                game.flag_change_etage = 1
                game.new_num_etage = obj.stage
                game.new_num_salle = obj.room
            else:
                if game.current_room != obj.room:
                    game.flag_change_salle = 1
                    game.new_num_salle = obj.room


def op_drop(vm):
    # life.cpp:1510: drop(worldIdx, worldSource)
    from PyAitD.engine.script.interaction import drop_object
    object_idx = eval_var(vm)
    source_idx = read_s16(vm)
    drop_object(vm.game, object_idx, source_idx)


def op_fire(vm):
    # life.cpp:1064 fire(): arm ranged attack only when InitAnim accepts;
    # a rejection still consumes every operand but leaves prior state alone.
    anim, frame, group, radius, force, next_anim = (read_s16(vm) for _ in range(6))
    if init_anim(vm.actor, anim, 2, next_anim):
        vm.actor.anim_action_anim = anim
        vm.actor.anim_action_frame = frame
        vm.actor.anim_action_type = 4
        vm.actor.anim_action_param = radius
        vm.actor.hot_point_id = group
        vm.actor.hit_force = force


def op_test_col(vm):
    # life.cpp:1306
    if read_s16(vm):
        vm.actor.dyn_flags |= 1
    else:
        vm.actor.dyn_flags &= ~1


def op_found_body(vm):
    # life.cpp:1588
    vm.game.world_objects[vm.actor.index_in_world].found_body = read_s16(vm)


def op_set_alpha(vm):
    # life.cpp:1249
    a = vm.actor
    alpha = read_s16(vm)
    speed = read_s16(vm)
    if a.alpha != alpha:
        if a.rotate.num_steps == 0 or a.rotate.end_value != alpha:
            init_real_value(a.alpha, alpha, speed, a.rotate, vm.game.timer)
        a.alpha = update_actor_rotation(a.rotate, vm.game.timer)


def op_do_max_zv(vm):
    # life.cpp:873: getZvMax(body, zv) + room offsets
    vm.actor.zv = _add_room(vm.actor, _zv_max(_body_zv(vm)))


def op_put(vm):
    # life.cpp:1521: put(x, y, z, room, stage, alpha, beta, gamma, idx)
    from PyAitD.engine.script.interaction import put_object
    object_idx = read_s16(vm)
    x, y, z = read_s16(vm), read_s16(vm), read_s16(vm)
    room, stage = read_s16(vm), read_s16(vm)
    alpha, beta, gamma = read_s16(vm), read_s16(vm), read_s16(vm)
    put_object(vm.game, object_idx, x, y, z, room, stage, alpha, beta, gamma)


def op_c_var(vm):
    # life.cpp:2238 — idx read first (C order), then evalVar
    idx = read_s16(vm)
    vm.game.cvars[idx] = eval_var(vm)


def op_do_carre_zv(vm):
    # life.cpp:887: getZvCube(body, zv) + room offsets
    vm.actor.zv = _add_room(vm.actor, _zv_cube(_body_zv(vm)))


def op_sample_then(vm):
    # life.cpp:1781 — M3b audio stub
    a = eval_var(vm)
    b = eval_var(vm)
    log.debug("LM_SAMPLE_THEN %d %d (M3b audio stub)", a, b)


def op_light(vm):
    # life.cpp:1877: lightOff = 2 - (v << 1); skipped if KILLED_SORCERER
    v = 2 - (read_s16(vm) << 1)
    if not vm.game.cvars[vm.game.profile.cvar_index("KILLED_SORCERER")]:
        vm.game.light_off = v


def op_shaking(vm):
    # life.cpp:1894: arg ignored
    log.debug("LM_SHAKING %d (stub)", read_s16(vm))


def op_inventory(vm):
    # life.cpp:2127
    vm.game.status_screen_allowed = read_s16(vm)


def op_found_weight(vm):
    # life.cpp:1604: world obj positionInTrack = weight
    vm.game.world_objects[vm.actor.index_in_world].position_in_track = read_s16(vm)


def op_up_coor_y(vm):
    # life.cpp:1322: InitRealValue(0, -2000, -1, &YHandler)
    init_real_value(0, -2000, -1, vm.actor.y_handler, vm.game.timer)


def op_put_at(vm):
    # life.cpp:1565: PutAtObjet(obj1, obj2)
    from PyAitD.engine.script.interaction import drop_object
    drop_object(vm.game, read_s16(vm), read_s16(vm))


def op_def_zv(vm):
    # life.cpp:816: zv = room + step + 6 raw args
    a = vm.actor
    a.zv = [
        a.room_x + read_s16(vm) + a.step_x, a.room_x + read_s16(vm) + a.step_x,
        a.room_y + read_s16(vm) + a.step_y, a.room_y + read_s16(vm) + a.step_y,
        a.room_z + read_s16(vm) + a.step_z, a.room_z + read_s16(vm) + a.step_z,
    ]


def op_hit_object(vm):
    # life.cpp:1117
    a = vm.actor
    a.anim_action_type = 8
    a.anim_action_param = read_s16(vm)
    a.hit_force = read_s16(vm)
    a.hot_point_id = -1


def op_get_hard_clip(vm):
    # life.cpp:931 + getHardClip (life.cpp:206)
    a = vm.actor
    game = vm.game
    for col in game.rooms_of_floor(game.current_floor)[a.room].hard_cols:
        zv_col = [col.x1, col.x2, col.y1, col.y2, col.z1, col.z2]
        if cube_intersect(a.zv, zv_col):
            game.hard_clip = zv_col
            return
    game.hard_clip = [32000, -32000, 32000, -32000, 32000, -32000]


def op_angle(vm):
    # life.cpp:1267
    a = vm.actor
    a.alpha = read_s16(vm)
    a.beta = read_s16(vm)
    a.gamma = read_s16(vm)


def op_rep_sample(vm):
    # life.cpp:1754: AITD1 — evalVar + 1 raw skipped, nothing played
    sample = eval_var(vm)
    read_s16(vm)
    log.debug("LM_REP_SAMPLE %d (M3b audio stub)", sample)


def op_throw(vm):
    # life.cpp:1143 throwObj(): arm the throw only when InitAnim accepts;
    # a rejection still consumes every operand but leaves prior state alone.
    anim, frame, group, object_idx, rotated, force, next_anim = (
        read_s16(vm) for _ in range(7)
    )
    if init_anim(vm.actor, anim, 2, next_anim):
        vm.actor.anim_action_anim = anim
        vm.actor.anim_action_frame = frame
        vm.actor.anim_action_type = 6
        vm.actor.anim_action_param = object_idx
        vm.actor.hot_point_id = group
        vm.actor.hit_force = force
        if rotated == 0:
            vm.game.world_objects[object_idx].gamma -= 0x100
        vm.game.world_objects[object_idx].found_flag |= 0x1000


def op_water(vm):
    # life.cpp:1915: arg ignored
    log.debug("LM_WATER %d (stub)", read_s16(vm))


def op_picture(vm):
    # life.cpp:2006
    picture = read_s16(vm)
    delay = read_s16(vm)
    sample = read_s16(vm)
    vm.suspend(ShowPicture(picture, delay, sample))


def op_stop_sample(vm):
    # life.cpp:1769: nothing
    log.debug("LM_STOP_SAMPLE (stub)")


def op_next_music(vm):
    # life.cpp:1832
    game = vm.game
    idx = read_s16(vm)
    if game.current_music == -1:
        log.debug("LM_NEXT_MUSIC play %d (M3b audio stub)", idx)
    else:
        game.next_music = idx


def op_fade_music(vm):
    # life.cpp:1849
    game = vm.game
    idx = read_s16(vm)
    if game.current_music != -1:
        game.current_music = -2  # waiting next music
        game.next_music = idx
    else:
        log.debug("LM_FADE_MUSIC play %d (M3b audio stub)", idx)


def op_stop_hit_object(vm):
    # life.cpp:1130
    a = vm.actor
    if a.anim_action_type == 8:
        a.anim_action_type = 0
        a.anim_action_param = 0
        a.hit_force = 0
        a.hot_point_id = -1


def op_copy_angle(vm):
    # life.cpp:1276
    a = vm.actor
    obj = vm.game.world_objects[read_s16(vm)]
    if obj.obj_index == -1:
        src = obj
    else:
        src = vm.game.actors[obj.obj_index]
    a.alpha = src.alpha
    a.beta = src.beta
    a.gamma = src.gamma


def op_end_sequence(vm):
    # life.cpp:2186: printf only
    log.debug("LM_END_SEQUENCE (stub)")


def op_sample_then_repeat(vm):
    # life.cpp:1813 — M3b audio stub
    a = eval_var(vm)
    b = eval_var(vm)
    log.debug("LM_SAMPLE_THEN_REPEAT %d %d (M3b audio stub)", a, b)


def op_wait_game_over(vm):
    # life.cpp:2452: both waits are event-polling loops (process_events); no
    # event pump in the M3a VM, so the waits degenerate. FITD bug preserved in
    # reference: second wait tests Click NOT negated.
    vm.game.flag_game_over = 1
    vm.exit = True
