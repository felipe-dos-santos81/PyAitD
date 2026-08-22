# SPDX-License-Identifier: GPL-2.0-only
"""RealValue interpolation + chrono ports (FITD main.cpp:2277-2321, evalChrono)."""
import math


def init_real_value(start_value, end_value, time, real_value, timer):
    real_value.start_value = start_value
    real_value.end_value = end_value
    real_value.num_steps = time
    real_value.memo_ticks = timer
    return real_value


def update_actor_rotation(rotate_ptr, timer):
    if not rotate_ptr.num_steps:
        return rotate_ptr.end_value
    time_dif = timer - rotate_ptr.memo_ticks
    if time_dif > rotate_ptr.num_steps:
        rotate_ptr.num_steps = 0
        return rotate_ptr.end_value
    angle_dif = (rotate_ptr.end_value & 0x3FF) - (rotate_ptr.start_value & 0x3FF)
    if angle_dif <= 0x200:
        if angle_dif >= -0x200:
            angle = (rotate_ptr.end_value & 0x3FF) - (rotate_ptr.start_value & 0x3FF)
            return (rotate_ptr.start_value & 0x3FF) + int((angle * time_dif) / rotate_ptr.num_steps)
        else:
            angle = ((rotate_ptr.end_value & 0x3FF) + 0x400) - (rotate_ptr.start_value & 0x3FF)
            return (rotate_ptr.start_value & 0x3FF) + int((angle * time_dif) / rotate_ptr.num_steps)
    else:
        angle = (rotate_ptr.end_value & 0x3FF) - ((rotate_ptr.start_value & 0x3FF) + 0x400)
        return int((angle * time_dif) / rotate_ptr.num_steps) + (rotate_ptr.start_value & 0x3FF)


def start_chrono(chrono_slot, timer):
    chrono_slot[0] = timer


def eval_chrono(chrono_value, timer):
    return timer - chrono_value


def give_distance_2d(x1, z1, x2, z2):
    return int(math.sqrt((x1 - x2) * (x1 - x2) + (z1 - z2) * (z1 - z2)))
