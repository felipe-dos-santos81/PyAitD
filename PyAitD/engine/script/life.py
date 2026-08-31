# SPDX-License-Identifier: GPL-2.0-only
"""LIFE script VM — faithful port of FITD life.cpp processLife (AITD1)."""
import struct

from PyAitD.engine.script.effects import AfterLife, LifeFrame
from PyAitD.engine.space.realvalue import start_chrono


class VM:
    __slots__ = (
        "script", "pc", "game", "owner_idx", "cur_idx", "switch_val",
        "exit", "suspended", "after", "subject_idx", "release_actor_idx", "table",
    )

    def __init__(self, script, game, owner_idx, *, pc=0, after=AfterLife.NONE,
                 subject_idx=-1, release_actor_idx=-1):
        self.script = script
        self.pc = pc
        self.game = game
        self.table = game.profile.opcode_table
        self.owner_idx = owner_idx
        self.cur_idx = owner_idx
        self.switch_val = 0
        self.exit = False
        self.suspended = False
        self.after = after
        self.subject_idx = subject_idx
        self.release_actor_idx = release_actor_idx

    def suspend(self, effect):
        self.game.emit(effect)
        self.suspended = True

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
    # Full encodings port (task 6, PyAitD.engine.script.eval_var); lazy import avoids a cycle.
    from PyAitD.engine.script.eval_var import eval_var as _full_eval_var
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


def process_life(game, actor_idx, life_num, *, pc=0, after=AfterLife.NONE,
                 subject_idx=-1, release_actor_idx=-1):
    vm = VM(
        game.assets.life(life_num), game, actor_idx, pc=pc, after=after,
        subject_idx=subject_idx, release_actor_idx=release_actor_idx,
    )
    while not vm.exit and not vm.suspended:
        op = read_s16(vm)
        if game.trace is not None:
            game.trace.log(game, actor_idx, life_num, op, vm.pc)
        if op & 0x8000:
            world_idx = read_s16(vm)
            if not 0 <= world_idx < len(game.world_objects):
                raise ValueError(
                    f"world object index {world_idx} out of range 0..{len(game.world_objects) - 1} "
                    f"(life {life_num} of actor {vm.owner_idx}, byte {vm.pc - 4})"
                )
            world = game.world_objects[world_idx]
            if world.obj_index != -1:
                vm.cur_idx = world.obj_index
                _dispatch(vm, op)
            else:
                # the allowed set is the game's (profile.reduced_allowed); the
                # guard is the engine's -- a second game inherits the raise
                if (op & 0x7FFF) not in game.profile.reduced_allowed:
                    raise ValueError(
                        f"opcode {op & 0x7FFF} not allowed on out-of-floor object "
                        f"{world_idx} (life of actor {vm.owner_idx}, byte {vm.pc - 4})"
                    )
                _dispatch_reduced(vm, op, world_idx)
            vm.cur_idx = vm.owner_idx
        else:
            _dispatch(vm, op)
    if vm.suspended:
        return LifeFrame(
            vm.owner_idx, life_num, vm.pc, vm.after, vm.subject_idx,
            vm.release_actor_idx,
        )
    return None


def _dispatch(vm, op):
    table = vm.table
    idx = op & 0x7FFF
    if idx >= len(table):
        raise ValueError(
            f"opcode {idx} out of range 0..{len(table) - 1} "
            f"(life of actor {vm.owner_idx}, byte {vm.pc - 2})"
        )
    table[idx](vm)


def _dispatch_reduced(vm, op, world_idx):
    # world-object-field ops on game.world_objects[world_idx]
    vm.game.profile.reduced_dispatch(vm, op & 0x7FFF, world_idx)


def life_gate(actor):
    return actor.life != -1 and actor.life_mode != -1


# AITD1LifeMacroTable (AITD1.cpp:30-119, life.h:7-93): 87 entries, index == enum value.
# The engine fills only the game-neutral slots; a GameProfile installs the rest.
NUM_OPCODES = 87


def core_table():
    table = [_op_not_implemented(i) for i in range(NUM_OPCODES)]
    table[4] = _make_if(lambda a, b: a == b)   # LM_IF_EGAL
    table[5] = _make_if(lambda a, b: a != b)   # LM_IF_DIFFERENT
    table[6] = _make_if(lambda a, b: a >= b)   # LM_IF_SUP_EGAL
    table[7] = _make_if(lambda a, b: a > b)    # LM_IF_SUP
    table[8] = _make_if(lambda a, b: a <= b)   # LM_IF_INF_EGAL
    table[9] = _make_if(lambda a, b: a < b)    # LM_IF_INF
    table[10] = _op_goto                       # LM_GOTO
    table[11] = _op_end                        # LM_RETURN
    table[12] = _op_end                        # LM_END
    table[19] = _op_var                        # LM_VAR
    table[20] = _op_inc                        # LM_INC
    table[21] = _op_dec                        # LM_DEC
    table[22] = _op_add                        # LM_ADD
    table[23] = _op_sub                        # LM_SUB
    table[24] = _op_life_mode                  # LM_LIFE_MODE
    table[25] = _op_switch                     # LM_SWITCH
    table[26] = _op_case                       # LM_CASE
    table[27] = _op_dead                       # LM_CAMERA
    table[28] = _op_start_chrono               # LM_START_CHRONO
    table[29] = _op_multi_case                 # LM_MULTI_CASE
    table[57] = _op_dead                       # LM_STOP_BETA
    table[61] = _op_dead                       # LM_DO_NORMAL_ZV
    table[69] = _op_dead                       # LM_SPEED
    return table
