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

    def log_behaviour(self, game, actor_idx, phase):
        # the content-pack twin of `log`: one line per behaviour step
        if self._file is None:
            return
        try:
            self._file.write(f"{game.timer} {actor_idx} BEHAVIOUR {phase}\n")
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
    # life >= 0 names a LISTLIFE script; -1 is none, and engine.content's
    # BEHAVIOUR_LIFE (-2) marks an actor a pack behaviour drives instead.
    return actor.life >= 0 and actor.life_mode != -1


# The semantic VM-control handlers, keyed by name. FITD shares these
# enumLifeMacro semantics across games while each game's macro table maps
# them onto its own bytecode slots (AITD1.cpp:30-119, AITD2.cpp:48-171) —
# the numbering is the profile's core_slots, not this module's.
_CORE = {
    "IF_EGAL": _make_if(lambda a, b: a == b),
    "IF_DIFFERENT": _make_if(lambda a, b: a != b),
    "IF_SUP_EGAL": _make_if(lambda a, b: a >= b),
    "IF_SUP": _make_if(lambda a, b: a > b),
    "IF_INF_EGAL": _make_if(lambda a, b: a <= b),
    "IF_INF": _make_if(lambda a, b: a < b),
    "GOTO": _op_goto,
    "RETURN": _op_end,
    "END": _op_end,
    "VAR": _op_var,
    "INC": _op_inc,
    "DEC": _op_dec,
    "ADD": _op_add,
    "SUB": _op_sub,
    "LIFE_MODE": _op_life_mode,
    "SWITCH": _op_switch,
    "CASE": _op_case,
    "START_CHRONO": _op_start_chrono,
    "MULTI_CASE": _op_multi_case,
}


def core_table(size, core_slots, dead_slots):
    # size and dead_slots are the game's macro-table facts. Slots left
    # _op_not_implemented are for the game profile to fill or reject.
    table = [_op_not_implemented(i) for i in range(size)]
    for name, slot in core_slots.items():
        table[slot] = _CORE[name]
    for slot in dead_slots:
        table[slot] = _op_dead
    return table
