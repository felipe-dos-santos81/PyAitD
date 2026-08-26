# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.engine.anim import patch_inter_angle, patch_inter_step


def test_patch_angle_equal():
    assert patch_inter_angle(100, 100, 5, 10) == 100


def test_patch_angle_small_diff():
    assert patch_inter_angle(100, 200, 5, 10) == 150


def test_patch_angle_wrap_positive():
    # diff > 0x200: previous += 0x400, then next - previous (truncating mid)
    assert patch_inter_angle(0, 0x300, 5, 10) == 0x380


def test_patch_angle_wrap_negative():
    assert patch_inter_angle(0x300, 0, 5, 10) == 0x380


def test_patch_step():
    assert patch_inter_step(10, 30, 5, 10) == 20
    assert patch_inter_step(30, 10, 5, 10) == 20


def test_init_anim_lives_in_the_engine():
    # engine modules (actors, interaction, playworld) call init_anim; it must
    # not live in the game-specific opcode module or the engine would import games
    from PyAitD.engine.anim import ANIM_REPEAT, ANIM_UNINTERRUPTABLE, init_anim
    from PyAitD.engine.game import AF_ANIMATED, Actor
    actor = Actor()
    assert init_anim(actor, 3, ANIM_REPEAT, -1) == 1
    assert actor.object_type & AF_ANIMATED and actor.new_anim == 3
    actor.new_anim_type = ANIM_UNINTERRUPTABLE
    assert init_anim(actor, 4, ANIM_REPEAT, -1) == 0
