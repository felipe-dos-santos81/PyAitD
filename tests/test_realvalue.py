# SPDX-License-Identifier: GPL-2.0-only
from maitd.realvalue import (
    eval_chrono, give_distance_2d, init_real_value, start_chrono, update_actor_rotation,
)
from maitd.game import RealValue


def test_update_rotation_identity():
    rv = init_real_value(0x100, 0x100, 60, RealValue(), timer=0)
    assert update_actor_rotation(rv, timer=0) == 0x100


def test_update_rotation_linear():
    rv = init_real_value(0, 0x200, 4, RealValue(), timer=10)
    assert update_actor_rotation(rv, timer=12) == 0x100


def test_update_rotation_overshoot():
    rv = init_real_value(0, 0x200, 4, RealValue(), timer=10)
    assert update_actor_rotation(rv, timer=99) == 0x200
    assert rv.num_steps == 0


def test_update_rotation_wrap():
    # angleDif = 0x0C0 - 0x300 = -0x240 < -0x200 -> +0x400 branch
    # (C condition angleDif>=-0x200 is inclusive; -0x200 itself takes the normal branch)
    rv = init_real_value(0x300, 0x0C0, 2, RealValue(), timer=0)
    assert update_actor_rotation(rv, timer=1) == 0x3E0


def test_chrono():
    slot = [0]
    start_chrono(slot, timer=10)
    assert eval_chrono(slot[0], timer=30) == 20


def test_distance():
    assert give_distance_2d(0, 0, 3, 4) == 5
    assert give_distance_2d(0, 0, 0, 0) == 0
