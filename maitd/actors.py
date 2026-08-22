# SPDX-License-Identifier: GPL-2.0-only
"""Actor state, hard-col collision helpers (FITD ports)."""
from dataclasses import dataclass

from maitd.anim import AnimPlayer
from maitd.game import AF_BOXIFY, AF_DRAWABLE, AF_ANIMATED
from maitd.realvalue import evaluate_real, init_real_value
from maitd.world import rotate_step

PLAYER_BODY = 12
PLAYER_ANIM = 2
SPAWN_POS = (-3642, 0, 1977)


@dataclass
class Actor:
    body_idx: int
    anim_idx: int
    x: int
    y: int
    z: int
    beta: int
    room_idx: int
    tick: int = 0


def spawn_player(assets, floor):
    return Actor(PLAYER_BODY, PLAYER_ANIM, SPAWN_POS[0], SPAWN_POS[1], SPAWN_POS[2], 0, 0)


def actor_zv(actor, body):
    bx = body.zv
    return (
        bx[0] + actor.x, bx[1] + actor.x,
        bx[2] + actor.y, bx[3] + actor.y,
        bx[4] + actor.z, bx[5] + actor.z,
    )


def cube_intersect(zv1, zv2):
    return not (
        zv1[0] >= zv2[1] or zv2[0] >= zv1[1]
        or zv1[2] >= zv2[3] or zv2[2] >= zv1[3]
        or zv1[4] >= zv2[5] or zv2[4] >= zv1[5]
    )


def check_hard_col(zv, hard_cols):
    out = []
    for col in hard_cols:
        f = (col.x1, col.x2, col.y1, col.y2, col.z1, col.z2)
        if (
            f[0] < zv[1] and zv[0] < f[1]
            and f[2] < zv[3] and zv[2] < f[3]
            and f[4] < zv[5] and zv[4] < f[5]
        ):
            out.append(col)
    return out


def _glisser(flag, step_x, step_z):
    if flag in (1, 2):
        step_z = 0
    elif flag in (4, 8):
        step_x = 0
    return step_x, step_z


def gere_collision(old_zv, animated_zv, fix_zv, step_x, step_z):
    # FITD GereCollision port: zeroes out the attempted step components that
    # would push the actor through fix_zv
    if old_zv[1] > fix_zv[0]:
        oldpos = 8 if fix_zv[1] <= old_zv[0] else 0
    else:
        oldpos = 4
    if old_zv[5] > fix_zv[4]:
        oldpos |= 2 if old_zv[4] >= fix_zv[5] else 0
    else:
        oldpos |= 1

    if oldpos in (5, 9, 6, 10):
        oldtype = 2
    elif oldpos == 0:
        return (0, 0)  # actor already inside: FITD zeroes the whole step
    else:
        oldtype = 1

    half_x = int((animated_zv[0] + animated_zv[1]) / 2)
    half_z = int((animated_zv[4] + animated_zv[5]) / 2)
    pos = 4 if fix_zv[0] > half_x else (0 if fix_zv[1] < half_x else 8)
    pos |= 1 if fix_zv[4] > half_z else (0 if fix_zv[5] < half_z else 2)

    if pos in (5, 9, 6, 10):
        type_ = 2
    elif pos == 0:
        type_ = 0
    else:
        type_ = 1

    if oldtype == 1:
        step_x, step_z = _glisser(oldpos, step_x, step_z)
    elif type_ == 1 and (pos & oldpos):
        step_x, step_z = _glisser(pos, step_x, step_z)
    else:
        if (pos == oldpos) or (pos + oldpos == 15):
            x_mod = abs(animated_zv[0] - old_zv[0])
            z_mod = abs(animated_zv[4] - old_zv[4])
            if x_mod > z_mod:
                step_z = 0
            else:
                step_x = 0
        elif type_ == 0 or (type_ == 1 and (pos & oldpos) == 0):
            step_x = 0
            step_z = 0
        else:
            step_x, step_z = _glisser(oldpos & pos, step_x, step_z)
    return (step_x, step_z)


def anim_player_for(game, actor_idx):
    # per-actor AnimPlayer keyed on the cached body/anim identities
    a = game.actors[actor_idx]
    body = game.assets.body(a.body_num)
    anim = game.assets.anim(a.anim)
    player = game.anim_players.get(actor_idx)
    if player is None or player.body is not body or player.anim is not anim:
        player = AnimPlayer(body, anim, game.timer)
        game.anim_players[actor_idx] = player
    return player


def gere_anim(game, actor_idx):
    # anim.cpp:205 GereAnim port, M3a subset: anim advance, movement, hard
    # cols. ponytail: actor/actor collision (CheckObjectCol: AF_MOVABLE push,
    # AF_FOUNDABLE pickup, COL_BY) and AF_FALLABLE fall management need the
    # M3b inventory/object pass.
    a = game.actors[actor_idx]

    new_anim = a.new_anim
    if new_anim != -1:
        if new_anim == -2:
            # addActorToBgInscrust: actor becomes static background
            a.object_type |= AF_BOXIFY + AF_DRAWABLE
            a.object_type &= ~AF_ANIMATED
            a.new_anim = -1
            a.new_anim_type = 0
            a.new_anim_info = -1
            a.flag_end_anim = 1
            return
        if a.end_frame == 0:
            # ponytail: FITD skips this commit + ResetStartAnim when
            # newAnimType & ANIM_RESET (4) (anim.cpp:228-244) — no
            # ANIM_RESET users in AITD1 floor 0 data yet
            a.world_x += a.step_x
            a.room_x += a.step_x
            a.world_z += a.step_z
            a.room_z += a.step_z
            a.step_x = 0
            a.step_z = 0
            a.anim_neg_x = 0
            a.anim_neg_y = 0
            a.anim_neg_z = 0
        a.anim = new_anim
        a.anim_type = a.new_anim_type
        a.anim_info = a.new_anim_info
        a.new_anim = -1
        a.new_anim_type = 0
        a.new_anim_info = -1
        a.flag_end_anim = 0
        a.frame = 0
        a.num_of_frames = game.assets.anim(new_anim).num_frames

    old_step_x = a.step_x
    old_step_y = a.step_y
    old_step_z = a.step_z
    step_x = step_y = step_z = 0

    if a.anim == -1:
        a.end_frame = 0
        if a.speed == 0:
            # CheckObjectCol COL_BY writes: M3b skip (ponytail)
            # anim.cpp:291-300 zeroes local step vars only; pending field
            # steps stay (FITD leaves them too)
            old_step_y = 0
            old_step_z = 0
        else:
            anim_step_z = evaluate_real(a.speed_change, game.timer)
            # walkStep(0, animStepZ, beta): Rotate(beta, 0, animStepZ,
            # &animMoveZ, &animMoveX) — outputs crossed (main.cpp:3186),
            # so rotate_step (FITD xOut, yOut) unpacks z, x
            anim_move_z, anim_move_x = rotate_step(a.beta, 0, anim_step_z)
            step_x = anim_move_x - old_step_x
            step_z = anim_move_z - old_step_z
            step_y = 0
    else:
        if a.body_num == -1:
            return  # ponytail: body -1 cannot be skinned, FITD would fault
        player = anim_player_for(game, actor_idx)
        a.end_frame = player.advance(game.timer)
        anim_move_z, anim_move_x = rotate_step(a.beta, player.anim_step[0], player.anim_step[2])
        step_x = anim_move_x + a.anim_neg_x - old_step_x
        step_z = anim_move_z + a.anim_neg_z - old_step_z

    if a.y_handler.num_steps:
        if a.y_handler.num_steps != -1:
            step_y = evaluate_real(a.y_handler, game.timer) - old_step_y
        else:
            step_y = a.y_handler.end_value - old_step_y
            a.y_handler.num_steps = 0
            a.y_handler.end_value = 0
            a.y_handler.start_value = 0
    else:
        step_y = 0

    if step_x or step_y or step_z:
        zv = a.zv
        zv_local = [
            zv[0] + step_x, zv[1] + step_x,
            zv[2] + step_y, zv[3] + step_y,
            zv[4] + step_z, zv[5] + step_z,
        ]
        room = game.rooms_of_floor(game.current_floor)[a.room]
        if a.dyn_flags & 1:
            for col in check_hard_col(zv_local, room.hard_cols):
                if col.type == 9:
                    a.hard_col = col.parameter
                if col.type == 3:
                    a.hard_col = 255
                if step_x or step_z:
                    hard_col_step_x, hard_col_step_z = gere_collision(
                        zv, zv_local,
                        (col.x1, col.x2, col.y1, col.y2, col.z1, col.z2),
                        step_x, step_z,
                    )
                    a.anim_neg_x += hard_col_step_x - step_x
                    a.anim_neg_z += hard_col_step_z - step_z
                    zv_local[0] += hard_col_step_x - step_x
                    zv_local[1] += hard_col_step_x - step_x
                    zv_local[4] += hard_col_step_z - step_z
                    zv_local[5] += hard_col_step_z - step_z
                    step_x = hard_col_step_x
                    step_z = hard_col_step_z
        else:
            a.hard_col = 1 if check_hard_col(zv_local, room.hard_cols) else 0
        # ponytail: CheckObjectCol actor/actor collision skipped (M3b)
        a.step_x = step_x + old_step_x
        a.step_y = step_y + old_step_y
        a.step_z = step_z + old_step_z
        a.zv = zv_local

    if not a.y_handler.num_steps:
        a.world_y += a.step_y
        a.room_y += a.step_y
        a.step_y = 0
        # ponytail: AF_FALLABLE fall management (manageFall) skipped (M3b)
    else:
        if a.y_handler.num_steps != -1 and (a.object_type & 0x100):
            a.falling = 1

    if a.end_frame:
        player = game.anim_players[actor_idx] if a.anim != -1 else None
        a.frame = player.frame if player is not None else a.frame
        if player is not None and player.wrapped:
            a.flag_end_anim = 1
            if not (a.anim_type & 1) and a.new_anim == -1:
                # anim.cpp:654-660: one-shot anim wrapped with no pending anim:
                # clear ANIM_UNINTERRUPTABLE, restart same anim as ANIM_REPEAT
                a.anim_type &= ~2
                from maitd.life_ops import init_anim
                init_anim(a, a.anim_info, 1, -1)
        a.world_x += a.step_x
        a.room_x += a.step_x
        a.world_z += a.step_z
        a.room_z += a.step_z
        a.step_x = 0
        a.step_z = 0
        a.anim_neg_x = 0
        a.anim_neg_y = 0
        a.anim_neg_z = 0
    else:
        if a.anim == -1 and a.speed != 0 and a.speed_change.num_steps == 0:
            a.world_x += a.step_x
            a.room_x += a.step_x
            a.world_z += a.step_z
            a.room_z += a.step_z
            a.step_x = 0
            a.step_z = 0
            init_real_value(0, a.speed, 60, a.speed_change, game.timer)
        a.flag_end_anim = 0
