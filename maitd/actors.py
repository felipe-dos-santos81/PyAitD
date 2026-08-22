# SPDX-License-Identifier: GPL-2.0-only
"""Actor state, hard-col collision helpers (FITD ports)."""
from dataclasses import dataclass

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
