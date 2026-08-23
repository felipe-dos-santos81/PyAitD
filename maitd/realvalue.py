# SPDX-License-Identifier: GPL-2.0-only
"""RealValue interpolation + chrono ports (FITD main.cpp:2277-2321, evalChrono)."""


def init_real_value(start_value, end_value, time, real_value, timer):
    real_value.start_value = start_value
    real_value.end_value = end_value
    real_value.num_steps = time
    real_value.memo_ticks = timer
    return real_value


def evaluate_real(real_value, timer):
    # FITD evaluateReal (anim.cpp): linear interpolation, no angle masking.
    # ponytail: num_steps == -1 diverges (C compares vs (unsigned)-1 and
    # interpolates with /-1; Python early-outs to end_value) — GereAnim
    # guards != -1, unreachable in M3a.
    if not real_value.num_steps:
        return real_value.end_value
    if timer - real_value.memo_ticks > real_value.num_steps:
        real_value.num_steps = 0
        return real_value.end_value
    value_diff = real_value.end_value - real_value.start_value
    current_time = timer - real_value.memo_ticks
    return real_value.start_value + int((value_diff * current_time) / real_value.num_steps)


def update_actor_rotation(rotate_ptr, timer):
    if not rotate_ptr.num_steps:
        return rotate_ptr.end_value
    time_dif = timer - rotate_ptr.memo_ticks
    if time_dif > rotate_ptr.num_steps:
        rotate_ptr.num_steps = 0
        return rotate_ptr.end_value
    end = rotate_ptr.end_value & 0x3FF
    start = rotate_ptr.start_value & 0x3FF
    angle = end - start
    if angle > 0x200:  # take the short way round
        angle -= 0x400
    elif angle < -0x200:
        angle += 0x400
    return start + int((angle * time_dif) / rotate_ptr.num_steps)


def start_chrono(actor, field, timer):
    setattr(actor, field, timer)


def eval_chrono(chrono_value, timer):
    return timer - chrono_value


def _s16(v):
    # C (s16) cast: truncate to 16 bits, sign-extend
    v %= 0x10000
    return v - 0x10000 if v > 0x7FFF else v


def give_distance_2d(x1, z1, x2, z2):
    # C: if (s16)x1 < 0, x1 = -(s16)x1 — magnitude of the truncated s16 value
    x1 -= x2
    if _s16(x1) < 0:
        x1 = -_s16(x1)
    z1 -= z2
    if _s16(z1) < 0:
        z1 = -_s16(z1)
    if x1 + z1 > 0xFFFF:
        return 0x7D00
    return x1 + z1
