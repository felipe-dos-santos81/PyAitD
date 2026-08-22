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


def eval_var(vm):
    # FITD evalVar vars.cpp:157-174 subset: tag -1 = constant, tag 0 = script var.
    # Actor-field tags (>0) land in task 6 (maitd.eval_var) and take over here.
    tag = read_s16(vm)
    if tag == -1:
        return read_s16(vm)
    if tag == 0:
        return vm.game.vars[read_s16(vm)]
    raise NotImplementedError(f"evalVar tag {tag} not implemented yet (task 6)")


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


def _op_message(vm):
    # life.cpp:2164: makeMessage(evalVar()) — message UI lands in M4.
    eval_var(vm)


def _op_message_value(vm):
    # life.cpp:2174: two raw words; message UI lands in M4.
    read_s16(vm)
    read_s16(vm)


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
LIFETABLE[17] = _op_message                    # LM_MESSAGE
LIFETABLE[18] = _op_message_value              # LM_MESSAGE_VALUE
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
