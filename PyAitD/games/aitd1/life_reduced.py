# SPDX-License-Identifier: GPL-2.0-only
"""Not-in-floor world-object dispatch (life.cpp:522-716, AITD1)."""
from PyAitD.engine.actor.anim import ANIM_ONCE, ANIM_REPEAT
from PyAitD.engine.life import eval_var, read_s16

TYPE_MASK = 0x1D1

ANIM_ALL_ONCE = ANIM_ONCE | 2


def reduced_dispatch(vm, opcode, world_idx):
    w = vm.game.world_objects[world_idx]
    if opcode == 3:  # LM_BODY — the one evalVar user in the reduced set
        w.body = eval_var(vm)
    elif opcode == 1:  # LM_ANIM_ONCE
        w.anim = read_s16(vm)
        w.anim_info = read_s16(vm)
        w.anim_type = ANIM_ONCE
    elif opcode == 13:  # LM_ANIM_REPEAT
        w.anim = read_s16(vm)
        w.anim_info = -1
        w.anim_type = ANIM_REPEAT
    elif opcode == 2:  # LM_ANIM_ALL_ONCE
        w.anim = read_s16(vm)
        w.anim_info = read_s16(vm)
        w.anim_type = ANIM_ALL_ONCE
    elif opcode == 40:  # LM_TYPE
        w.flags = (w.flags & ~TYPE_MASK) + (read_s16(vm) & TYPE_MASK)
    elif opcode == 15:  # LM_MOVE
        w.track_mode = read_s16(vm)
        w.track_number = read_s16(vm)
        w.position_in_track = 0
    elif opcode == 74:  # LM_ANGLE
        w.alpha = read_s16(vm)
        w.beta = read_s16(vm)
        w.gamma = read_s16(vm)
    elif opcode == 47:  # LM_STAGE
        w.stage = read_s16(vm)
        w.room = read_s16(vm)
        w.x = read_s16(vm)
        w.y = read_s16(vm)
        w.z = read_s16(vm)
        # FITD's GenereActiveList runs every frame (mainLoop.cpp:249; spawn
        # scan main.cpp:1990), so an object moved onto the current floor is
        # picked up by that same tick's spawn scan, not the next one. This
        # port gates that scan on flag_genere_aff_list
        # (playworld._genere_active_list): raise it here or the intro's
        # director (life 547 -> object 288) never spawns its next act.
        # ponytail: an unconditional per-frame scan is the faithful upgrade;
        # it changes spawn timing everywhere and the goldens pinned on it.
        if w.stage == vm.game.current_floor:
            vm.game.flag_genere_aff_list = 1
    elif opcode == 54:  # LM_TEST_COL
        if read_s16(vm):
            w.flags |= 0x20
        else:
            w.flags &= 0xFFDF
    elif opcode == 31:  # LM_LIFE
        w.life = read_s16(vm)
    elif opcode == 24:  # LM_LIFE_MODE
        mode = read_s16(vm)
        if mode != w.life_mode:
            w.life_mode = mode
    elif opcode == 48:  # LM_FOUND_NAME
        w.found_name = read_s16(vm)
    elif opcode == 55:  # LM_FOUND_BODY
        w.found_body = read_s16(vm)
    elif opcode == 49:  # LM_FOUND_FLAG
        w.found_flag = (w.found_flag & 0xE000) | read_s16(vm)
    elif opcode == 67:  # LM_FOUND_WEIGHT
        w.position_in_track = read_s16(vm)
    elif opcode == 28:  # LM_START_CHRONO — no-op in the not-in-floor path
        pass
    else:
        raise ValueError(f"opcode {opcode} has no reduced handler")
