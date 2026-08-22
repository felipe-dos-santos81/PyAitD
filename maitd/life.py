# SPDX-License-Identifier: GPL-2.0-only
"""LIFE script VM — faithful port of FITD life.cpp processLife (AITD1)."""
import struct

from maitd.realvalue import start_chrono


class VM:
    __slots__ = ("script", "pc", "game", "owner_idx", "cur_idx", "switch_val", "exit")

    def __init__(self, script, game, owner_idx):
        self.script = script
        self.pc = 0
        self.game = game
        self.owner_idx = owner_idx
        self.cur_idx = owner_idx
        self.switch_val = 0
        self.exit = False

    @property
    def actor(self):
        return self.game.actors[self.cur_idx]

    @property
    def owner(self):
        return self.game.actors[self.owner_idx]


def read_s16(vm):
    value = struct.unpack_from("<h", vm.script, vm.pc)[0]
    vm.pc += 2
    return value


class Trace:
    """--trace FILE: best-effort per-opcode log. IO errors never propagate."""

    def __init__(self, path):
        self._file = None
        try:
            self._file = open(path, "w")
        except OSError:
            pass

    def log(self, game, actor_idx, life_num, op, pc):
        if self._file is None:
            return
        try:
            self._file.write(f"{game.timer} {actor_idx} {life_num} {op & 0x7FFF} {pc}\n")
        except OSError:
            pass

    def close(self):
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None


def eval_var(vm):
    # Full encodings port (task 6, maitd.eval_var); lazy import avoids a cycle.
    from maitd.eval_var import eval_var as _full_eval_var
    return _full_eval_var(vm)


def _op_end(vm):
    vm.exit = True


def _op_goto(vm):
    offset = read_s16(vm)
    vm.pc += offset * 2


def _make_if(op):  # condition functions over (a, b)
    def handler(vm):
        a = eval_var(vm)
        b = eval_var(vm)
        jump = read_s16(vm)
        if not op(a, b):
            vm.pc += jump * 2
    return handler


def _op_var(vm):
    # life.cpp:2194: vars[raw idx] = evalVar()
    idx = read_s16(vm)
    vm.game.vars[idx] = eval_var(vm)


def _op_inc(vm):
    vm.game.vars[read_s16(vm)] += 1


def _op_dec(vm):
    vm.game.vars[read_s16(vm)] -= 1


def _op_add(vm):
    idx = read_s16(vm)
    vm.game.vars[idx] += eval_var(vm)


def _op_sub(vm):
    idx = read_s16(vm)
    vm.game.vars[idx] -= eval_var(vm)


def _op_life_mode(vm):
    # life.cpp:1341: set only when different (AITD1 compares full value)
    mode = read_s16(vm)
    if mode != vm.actor.life_mode:
        vm.actor.life_mode = mode


def _op_switch(vm):
    vm.switch_val = eval_var(vm)


def _op_case(vm):
    case = read_s16(vm)
    jump = read_s16(vm)
    if case != vm.switch_val:
        vm.pc += jump * 2


def _op_start_chrono(vm):
    # life.cpp:1447: startChrono(&actor->CHRONO)
    start_chrono(vm.actor, "chrono", vm.game.timer)


def _op_multi_case(vm):
    count = read_s16(vm)
    values = [read_s16(vm) for _ in range(count)]
    jump = read_s16(vm)
    if vm.switch_val not in values:
        vm.pc += jump * 2


# Dead in AITD1: LM_CAMERA(27), LM_STOP_BETA(57), LM_DO_NORMAL_ZV(61), LM_SPEED(69)
# — table entries exist but FITD's dispatch switch has no case for them (assert).
def _op_dead(vm):
    raise ValueError(
        f"dead opcode {struct.unpack_from('<h', vm.script, vm.pc - 2)[0] & 0x7FFF} "
        f"in life of actor {vm.owner_idx} at byte {vm.pc - 2} (FITD asserts here)"
    )


def _op_not_implemented(index):
    def handler(vm):
        raise NotImplementedError(f"opcode {index} not implemented yet")
    return handler


# Reduced dispatch (world object not in floor, life.cpp:522-716): allowed set only.
_REDUCED_ALLOWED = {1, 2, 3, 13, 15, 24, 28, 31, 40, 47, 48, 49, 54, 55, 67, 74}


def process_life(game, actor_idx, life_num):
    vm = VM(game.assets.life(life_num), game, actor_idx)
    while not vm.exit:
        op = read_s16(vm)
        if game.trace is not None:
            game.trace.log(game, actor_idx, life_num, op, vm.pc)
        if op & 0x8000:
            world_idx = read_s16(vm)
            world = game.world_objects[world_idx]
            if world.obj_index != -1:
                vm.cur_idx = world.obj_index
                _dispatch(vm, op)
            else:
                if (op & 0x7FFF) not in _REDUCED_ALLOWED:
                    raise ValueError(
                        f"opcode {op & 0x7FFF} not allowed on out-of-floor object "
                        f"{world_idx} (life of actor {vm.owner_idx}, byte {vm.pc - 4})"
                    )
                _dispatch_reduced(vm, op, world_idx)
            vm.cur_idx = vm.owner_idx
        else:
            _dispatch(vm, op)


def _dispatch(vm, op):
    idx = op & 0x7FFF
    if idx >= len(LIFETABLE):
        raise ValueError(
            f"opcode {idx} out of range 0..{len(LIFETABLE) - 1} "
            f"(life of actor {vm.owner_idx}, byte {vm.pc - 2})"
        )
    LIFETABLE[idx](vm)


def _dispatch_reduced(vm, op, world_idx):
    # world-object-field ops on game.world_objects[world_idx]; implemented in task 7.
    try:
        from maitd.life_reduced import reduced_dispatch
    except ImportError:
        raise ValueError(
            f"opcode {op & 0x7FFF} reduced dispatch unavailable (maitd.life_reduced, task 7)"
        ) from None
    reduced_dispatch(vm, op & 0x7FFF, world_idx)


def life_gate(actor):
    return actor.life != -1 and actor.life_mode != -1


# AITD1LifeMacroTable (AITD1.cpp:30-119, life.h:7-93): 87 entries, index == enum value.
LIFETABLE = [_op_not_implemented(i) for i in range(87)]
LIFETABLE[4] = _make_if(lambda a, b: a == b)   # LM_IF_EGAL
LIFETABLE[5] = _make_if(lambda a, b: a != b)   # LM_IF_DIFFERENT
LIFETABLE[6] = _make_if(lambda a, b: a >= b)   # LM_IF_SUP_EGAL
LIFETABLE[7] = _make_if(lambda a, b: a > b)    # LM_IF_SUP
LIFETABLE[8] = _make_if(lambda a, b: a <= b)   # LM_IF_INF_EGAL
LIFETABLE[9] = _make_if(lambda a, b: a < b)    # LM_IF_INF
LIFETABLE[10] = _op_goto                       # LM_GOTO
LIFETABLE[11] = _op_end                        # LM_RETURN
LIFETABLE[12] = _op_end                        # LM_END
LIFETABLE[19] = _op_var                        # LM_VAR
LIFETABLE[20] = _op_inc                        # LM_INC
LIFETABLE[21] = _op_dec                        # LM_DEC
LIFETABLE[22] = _op_add                        # LM_ADD
LIFETABLE[23] = _op_sub                        # LM_SUB
LIFETABLE[24] = _op_life_mode                  # LM_LIFE_MODE
LIFETABLE[25] = _op_switch                     # LM_SWITCH
LIFETABLE[26] = _op_case                       # LM_CASE
LIFETABLE[27] = _op_dead                       # LM_CAMERA
LIFETABLE[28] = _op_start_chrono               # LM_START_CHRONO
LIFETABLE[29] = _op_multi_case                 # LM_MULTI_CASE
LIFETABLE[57] = _op_dead                       # LM_STOP_BETA
LIFETABLE[61] = _op_dead                       # LM_DO_NORMAL_ZV
LIFETABLE[69] = _op_dead                       # LM_SPEED


def _install_handlers():
    # Task 8 wiring (opcode numbers per AITD1LifeMacroTable, AITD1.cpp:30-119)
    from maitd import life_ops as ops
    from maitd.tracks import process_track
    LIFETABLE[0] = lambda vm: process_track(vm.game, vm.actor)  # LM_DO_MOVE
    LIFETABLE[1] = ops.op_anim_once
    LIFETABLE[2] = ops.op_anim_all_once
    LIFETABLE[3] = ops.op_body
    LIFETABLE[13] = ops.op_anim_repeat
    LIFETABLE[14] = ops.op_anim_move
    LIFETABLE[15] = ops.op_move
    LIFETABLE[16] = ops.op_hit
    LIFETABLE[17] = ops.op_message
    LIFETABLE[18] = ops.op_message_value
    LIFETABLE[30] = ops.op_found
    LIFETABLE[31] = ops.op_life
    LIFETABLE[32] = ops.op_delete
    LIFETABLE[33] = ops.op_take
    LIFETABLE[34] = ops.op_in_hand
    LIFETABLE[35] = ops.op_read
    LIFETABLE[36] = ops.op_anim_sample
    LIFETABLE[37] = ops.op_special
    LIFETABLE[38] = ops.op_do_real_zv
    LIFETABLE[39] = ops.op_sample
    LIFETABLE[40] = ops.op_type
    LIFETABLE[41] = ops.op_game_over
    LIFETABLE[42] = ops.op_manual_rot
    LIFETABLE[43] = ops.op_rnd_freq
    LIFETABLE[44] = ops.op_music
    LIFETABLE[45] = ops.op_set_beta
    LIFETABLE[46] = ops.op_do_rot_zv
    LIFETABLE[47] = ops.op_stage
    LIFETABLE[48] = ops.op_found_name
    LIFETABLE[49] = ops.op_found_flag
    LIFETABLE[50] = ops.op_found_life
    LIFETABLE[51] = ops.op_camera_target
    LIFETABLE[52] = ops.op_drop
    LIFETABLE[53] = ops.op_fire
    LIFETABLE[54] = ops.op_test_col
    LIFETABLE[55] = ops.op_found_body
    LIFETABLE[56] = ops.op_set_alpha
    LIFETABLE[58] = ops.op_do_max_zv
    LIFETABLE[59] = ops.op_put
    LIFETABLE[60] = ops.op_c_var
    LIFETABLE[62] = ops.op_do_carre_zv
    LIFETABLE[63] = ops.op_sample_then
    LIFETABLE[64] = ops.op_light
    LIFETABLE[65] = ops.op_shaking
    LIFETABLE[66] = ops.op_inventory
    LIFETABLE[67] = ops.op_found_weight
    LIFETABLE[68] = ops.op_up_coor_y
    LIFETABLE[70] = ops.op_put_at
    LIFETABLE[71] = ops.op_def_zv
    LIFETABLE[72] = ops.op_hit_object
    LIFETABLE[73] = ops.op_get_hard_clip
    LIFETABLE[74] = ops.op_angle
    LIFETABLE[75] = ops.op_rep_sample
    LIFETABLE[76] = ops.op_throw
    LIFETABLE[77] = ops.op_water
    LIFETABLE[78] = ops.op_picture
    LIFETABLE[79] = ops.op_stop_sample
    LIFETABLE[80] = ops.op_next_music
    LIFETABLE[81] = ops.op_fade_music
    LIFETABLE[82] = ops.op_stop_hit_object
    LIFETABLE[83] = ops.op_copy_angle
    LIFETABLE[84] = ops.op_end_sequence
    LIFETABLE[85] = ops.op_sample_then_repeat
    LIFETABLE[86] = ops.op_wait_game_over


_install_handlers()

for _i, _h in enumerate(LIFETABLE):
    if _h.__qualname__.startswith("_op_not_implemented"):
        raise RuntimeError(f"life LIFETABLE slot {_i} left unimplemented")
