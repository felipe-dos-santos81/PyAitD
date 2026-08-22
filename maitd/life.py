# SPDX-License-Identifier: GPL-2.0-only
"""LIFE script VM — faithful port of FITD life.cpp processLife (AITD1)."""
import struct


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


def _op_switch(vm):
    vm.switch_val = eval_var(vm)


def _op_case(vm):
    case = read_s16(vm)
    jump = read_s16(vm)
    if case != vm.switch_val:
        vm.pc += jump * 2


def _op_multi_case(vm):
    count = read_s16(vm)
    values = [read_s16(vm) for _ in range(count)]
    jump = read_s16(vm)
    if vm.switch_val not in values:
        vm.pc += jump * 2


# Dead in AITD1: LM_STOP_BETA(58), LM_DO_NORMAL_ZV(62), LM_SPEED(70) — assert in FITD.
# (LM_CAMERA is not part of the AITD1 88-entry table.)
def _op_dead(vm):
    raise ValueError(
        f"dead opcode {struct.unpack_from('<h', vm.script, vm.pc - 2)[0] & 0x7FFF} "
        f"in life of actor {vm.owner_idx} at byte {vm.pc - 2} (FITD asserts here)"
    )


def _op_not_implemented(index):
    def handler(vm):
        raise NotImplementedError(f"opcode {index} not implemented yet")
    return handler


# Reduced dispatch (world object not in floor, life.cpp:693-712): allowed set only.
# FITD set incl LM_BODY_RESET(4) and LM_START_CHRONO(29, no-op).
_REDUCED_ALLOWED = {1, 2, 3, 4, 13, 15, 25, 29, 32, 41, 48, 49, 50, 55, 56, 68, 75}


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


LIFETABLE = [_op_not_implemented(i) for i in range(88)]
LIFETABLE[4] = _make_if(lambda a, b: a == b)   # LM_IF_EGAL
LIFETABLE[5] = _make_if(lambda a, b: a != b)   # LM_IF_DIFFERENT
LIFETABLE[6] = _make_if(lambda a, b: a >= b)   # LM_IF_SUP_EGAL
LIFETABLE[7] = _make_if(lambda a, b: a > b)    # LM_IF_SUP
LIFETABLE[8] = _make_if(lambda a, b: a <= b)   # LM_IF_INF_EGAL
LIFETABLE[9] = _make_if(lambda a, b: a < b)    # LM_IF_INF
LIFETABLE[10] = _op_goto                       # LM_GOTO
LIFETABLE[11] = _op_end                        # LM_RETURN
LIFETABLE[12] = _op_end                        # LM_END
LIFETABLE[26] = _op_switch                     # LM_SWITCH
LIFETABLE[27] = _op_case                       # LM_CASE
LIFETABLE[30] = _op_multi_case                 # LM_MULTI_CASE
LIFETABLE[58] = _op_dead                       # LM_STOP_BETA
LIFETABLE[62] = _op_dead                       # LM_DO_NORMAL_ZV
LIFETABLE[70] = _op_dead                       # LM_SPEED
