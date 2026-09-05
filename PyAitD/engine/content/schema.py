# SPDX-License-Identifier: GPL-2.0-only
"""Content pack records: the fixed vocabulary, parsed and range-checked.

Pure -- no archive access. `parse_enemy` turns one enemy TOML table into an
EnemyRecord or raises PackError naming the file, the key and the value.
Archive-dependent checks (body/anim counts, floor rooms) live in pack.py."""
from dataclasses import dataclass

BEHAVIOUR_LIFE = -2
"""WorldObject.life / Actor.life of a behaviour-driven actor. Every original
OBJETS.ITD record has life >= -1 (tests/test_world_data.py pins it) and
script.life.life_gate admits only life >= 0 to the VM, so -2 collides with
nothing and the VM never fetches it."""

KINDS = ("pursuer", "sentry")
ZV_TYPES = {"max": 0, "body": 1, "cube": 2, "rotated": 3}   # WorldObject.type_zv
LIFE_MODES = {"stage": 0, "room": 1}                         # WorldObject.life_mode
PHASES = ("idle", "chase", "attack", "hurt", "dying", "dead")
S16_MIN, S16_MAX = -32768, 32767
ENEMY_KEYS = frozenset({
    "id", "kind", "body", "stage", "room", "position", "beta", "zv",
    "life_mode", "falls", "hit_points", "anims", "attack",
})
ANIM_KEYS = ("stand", "walk", "attack", "hurt", "death")
ATTACK_KEYS = ("frame", "group", "radius", "force", "range")

OBJECT_KINDS = ("pickup", "scenery", "trigger")
EFFECT_OPS = ("message", "set_flag", "clear_flag", "remove_item", "delete_object")
CONDITION_KEYS = ("flag", "not_flag", "has_item", "not_item")
MAX_ACTIONS = 5          # interaction.inventory.MAX_VISIBLE_ACTIONS: the inventory shows no more
_COMMON_OBJECT_KEYS = ("id", "kind", "stage", "room")
OBJECT_KEYS = {
    "pickup": frozenset(_COMMON_OBJECT_KEYS + ("name", "body", "position", "beta", "zv", "weight", "on_take", "actions")),
    "scenery": frozenset(_COMMON_OBJECT_KEYS + ("body", "position", "beta", "zv", "pushable")),
    "trigger": frozenset(_COMMON_OBJECT_KEYS + ("box", "on_enter")),
}
RULE_KEYS = ("when", "then")
ACTION_KEYS = ("label", "when", "then")


class PackError(Exception):
    """A pack could not be read or validated: `file` is the path inside the
    pack, `key` the dotted TOML key (or `root`), `message` says what was
    wrong with the value."""

    def __init__(self, file, key, message):
        super().__init__(f"{file}: {key}: {message}")
        self.file = file
        self.key = key
        self.message = message


@dataclass(frozen=True)
class Anims:
    stand: int
    walk: int | None
    attack: int
    hurt: int
    death: int

    def present(self):
        """(key, anim) for every anim the record names, in ANIM_KEYS order."""
        return tuple((key, getattr(self, key)) for key in ANIM_KEYS if getattr(self, key) is not None)


@dataclass(frozen=True)
class Attack:
    frame: int
    group: int
    radius: int
    force: int
    range: int


@dataclass(frozen=True)
class EnemyRecord:
    id: str
    kind: str
    body: int
    stage: int
    room: int
    position: tuple
    beta: int
    type_zv: int
    life_mode: int
    falls: bool
    hit_points: int
    anims: Anims
    attack: Attack
    file: str


@dataclass(frozen=True)
class Condition:
    """A rule's `when`: every named part must hold (conjunction)."""
    flag: str | None = None
    not_flag: str | None = None
    has_item: str | None = None
    not_item: str | None = None


ALWAYS = Condition()


@dataclass(frozen=True)
class Effect:
    op: str      # one of EFFECT_OPS
    arg: str     # the message string, the flag name or the pack id


@dataclass(frozen=True)
class Rule:
    when: Condition
    then: tuple  # of Effect, never empty


@dataclass(frozen=True)
class Action:
    label: str   # the inventory verb the pack shows
    rule: Rule


@dataclass(frozen=True)
class PickupRecord:
    id: str
    kind: str
    stage: int
    room: int
    name: str
    body: int
    position: tuple
    beta: int
    type_zv: int
    weight: int
    on_take: tuple   # of Rule
    actions: tuple   # of Action
    file: str

    def rules(self):
        """(dotted key, Rule) for every rule the record holds, in text order."""
        return tuple(
            [(f"on_take[{i}]", rule) for i, rule in enumerate(self.on_take)]
            + [(f"actions[{i}]", action.rule) for i, action in enumerate(self.actions)]
        )


@dataclass(frozen=True)
class SceneryRecord:
    id: str
    kind: str
    stage: int
    room: int
    body: int
    position: tuple
    beta: int
    type_zv: int
    pushable: bool
    file: str

    def rules(self):
        return ()


@dataclass(frozen=True)
class TriggerRecord:
    id: str
    kind: str
    stage: int
    room: int
    box: tuple       # (x_min, x_max, y_min, y_max, z_min, z_max), room coordinates
    on_enter: tuple  # of Rule, never empty
    file: str

    def rules(self):
        return tuple((f"on_enter[{i}]", rule) for i, rule in enumerate(self.on_enter))


def _require(table, key, file, prefix=""):
    if key not in table:
        raise PackError(file, f"{prefix}{key}", "missing")
    return table[key]


def _s16(value, file, key):
    if type(value) is not int:
        raise PackError(file, key, f"expected an integer, got {value!r}")
    if not S16_MIN <= value <= S16_MAX:
        raise PackError(file, key, f"{value} is outside {S16_MIN}..{S16_MAX}")
    return value


def _non_negative(value, file, key):
    value = _s16(value, file, key)
    if value < 0:
        raise PackError(file, key, f"{value} is negative")
    return value


def _choice(value, choices, file, key):
    if value not in choices:
        raise PackError(file, key, f"{value!r} is not one of {', '.join(choices)}")
    return value


def _reject_unknown(table, allowed, file, prefix=""):
    unknown = sorted(set(table) - set(allowed))
    if unknown:
        raise PackError(file, f"{prefix}{unknown[0]}", "unknown key")


def _string(value, file, key):
    if type(value) is not str or not value:
        raise PackError(file, key, f"expected a non-empty string, got {value!r}")
    return value


def _parse_position(value, file):
    if not isinstance(value, list) or len(value) != 3:
        raise PackError(file, "position", f"expected [x, y, z], got {value!r}")
    return tuple(_s16(v, file, f"position[{i}]") for i, v in enumerate(value))


def _parse_beta(value, file):
    beta = _s16(value, file, "beta")
    if not 0 <= beta <= 1023:
        raise PackError(file, "beta", f"{beta} is outside 0..1023")
    return beta


def _parse_condition(table, file, key):
    if not isinstance(table, dict):
        raise PackError(file, key, f"expected a table, got {table!r}")
    _reject_unknown(table, CONDITION_KEYS, file, key + ".")
    return Condition(**{
        name: _string(table[name], file, f"{key}.{name}") for name in CONDITION_KEYS if name in table
    })


def _parse_effect(table, file, key):
    if not isinstance(table, dict) or len(table) != 1:
        raise PackError(file, key, f"expected a table with exactly one key, got {table!r}")
    (op, arg), = table.items()
    if op not in EFFECT_OPS:
        raise PackError(file, f"{key}.{op}", f"unknown effect; expected one of {', '.join(EFFECT_OPS)}")
    return Effect(op, _string(arg, file, f"{key}.{op}"))


def _parse_rule(table, file, key, allowed):
    if not isinstance(table, dict):
        raise PackError(file, key, f"expected a table, got {table!r}")
    _reject_unknown(table, allowed, file, key + ".")
    when = _parse_condition(table["when"], file, f"{key}.when") if "when" in table else ALWAYS
    then = _require(table, "then", file, key + ".")
    if not isinstance(then, list) or not then:
        raise PackError(file, f"{key}.then", f"expected a non-empty array of effects, got {then!r}")
    return Rule(when, tuple(_parse_effect(e, file, f"{key}.then[{i}]") for i, e in enumerate(then)))


def _parse_rules(value, file, key):
    if not isinstance(value, list):
        raise PackError(file, key, f"expected an array of tables, got {value!r}")
    return tuple(_parse_rule(t, file, f"{key}[{i}]", RULE_KEYS) for i, t in enumerate(value))


def _parse_actions(value, file):
    if not isinstance(value, list):
        raise PackError(file, "actions", f"expected an array of tables, got {value!r}")
    if len(value) > MAX_ACTIONS:
        raise PackError(file, "actions", f"{len(value)} actions is more than the inventory shows ({MAX_ACTIONS})")
    actions = []
    seen = {}
    for i, table in enumerate(value):
        key = f"actions[{i}]"
        rule = _parse_rule(table, file, key, ACTION_KEYS)
        label = _string(_require(table, "label", file, key + "."), file, f"{key}.label")
        if label in seen:
            raise PackError(file, f"{key}.label", f"{label!r} is already used by actions[{seen[label]}]")
        seen[label] = i
        actions.append(Action(label, rule))
    return tuple(actions)


def _parse_box(table, file):
    if not isinstance(table, dict) or sorted(table) != ["x", "y", "z"]:
        raise PackError(file, "box", f"expected a table with the keys x, y, z, got {table!r}")
    bounds = []
    for axis in ("x", "y", "z"):
        pair = table[axis]
        if not isinstance(pair, list) or len(pair) != 2:
            raise PackError(file, f"box.{axis}", f"expected [min, max], got {pair!r}")
        low, high = (_s16(v, file, f"box.{axis}[{i}]") for i, v in enumerate(pair))
        if low > high:
            raise PackError(file, f"box.{axis}", f"min {low} is above max {high}")
        bounds += [low, high]
    return tuple(bounds)


def parse_object(table, file):
    """One object TOML table -> PickupRecord | SceneryRecord | TriggerRecord,
    or PackError(file, key, message). The key set is exact per kind."""
    if not isinstance(table, dict):
        raise PackError(file, "root", "expected a table")
    kind = _choice(_require(table, "kind", file), OBJECT_KINDS, file, "kind")
    _reject_unknown(table, OBJECT_KEYS[kind], file)
    ident = _string(_require(table, "id", file), file, "id")
    stage = _non_negative(_require(table, "stage", file), file, "stage")
    room = _non_negative(_require(table, "room", file), file, "room")
    if kind == "trigger":
        box = _parse_box(_require(table, "box", file), file)
        on_enter = _parse_rules(_require(table, "on_enter", file), file, "on_enter")
        if not on_enter:
            raise PackError(file, "on_enter", "expected at least one rule")
        return TriggerRecord(id=ident, kind=kind, stage=stage, room=room, box=box, on_enter=on_enter, file=file)
    body = _non_negative(_require(table, "body", file), file, "body")
    position = _parse_position(_require(table, "position", file), file)
    beta = _parse_beta(table.get("beta", 0), file)
    type_zv = ZV_TYPES[_choice(table.get("zv", "max"), tuple(ZV_TYPES), file, "zv")]
    if kind == "scenery":
        pushable = table.get("pushable", False)
        if type(pushable) is not bool:
            raise PackError(file, "pushable", f"expected true or false, got {pushable!r}")
        return SceneryRecord(id=ident, kind=kind, stage=stage, room=room, body=body, position=position,
                             beta=beta, type_zv=type_zv, pushable=pushable, file=file)
    return PickupRecord(
        id=ident, kind=kind, stage=stage, room=room,
        name=_string(_require(table, "name", file), file, "name"),
        body=body, position=position, beta=beta, type_zv=type_zv,
        weight=_non_negative(table.get("weight", 0), file, "weight"),
        on_take=_parse_rules(table.get("on_take", []), file, "on_take"),
        actions=_parse_actions(table.get("actions", []), file),
        file=file,
    )


def _parse_anims(table, kind, file):
    if not isinstance(table, dict):
        raise PackError(file, "anims", f"expected a table, got {table!r}")
    _reject_unknown(table, ANIM_KEYS, file, "anims.")
    values = {}
    for key in ANIM_KEYS:
        if key == "walk":
            if kind == "sentry":
                if "walk" in table:
                    raise PackError(file, "anims.walk", "a sentry never walks")
                values["walk"] = None
                continue
        values[key] = _non_negative(_require(table, key, file, "anims."), file, f"anims.{key}")
    return Anims(**values)


def _parse_attack(table, file):
    if not isinstance(table, dict):
        raise PackError(file, "attack", f"expected a table, got {table!r}")
    _reject_unknown(table, ATTACK_KEYS, file, "attack.")
    return Attack(**{
        key: _non_negative(_require(table, key, file, "attack."), file, f"attack.{key}")
        for key in ATTACK_KEYS
    })


def parse_enemy(table, file):
    """One enemy TOML table -> EnemyRecord, or PackError(file, key, message)."""
    if not isinstance(table, dict):
        raise PackError(file, "root", "expected a table")
    _reject_unknown(table, ENEMY_KEYS, file)
    ident = _require(table, "id", file)
    if type(ident) is not str or not ident:
        raise PackError(file, "id", f"expected a non-empty string, got {ident!r}")
    kind = _choice(_require(table, "kind", file), KINDS, file, "kind")
    body = _non_negative(_require(table, "body", file), file, "body")
    stage = _non_negative(_require(table, "stage", file), file, "stage")
    room = _non_negative(_require(table, "room", file), file, "room")
    position = _parse_position(_require(table, "position", file), file)
    beta = _parse_beta(table.get("beta", 0), file)
    type_zv = ZV_TYPES[_choice(table.get("zv", "max"), tuple(ZV_TYPES), file, "zv")]
    life_mode = LIFE_MODES[_choice(table.get("life_mode", "room"), tuple(LIFE_MODES), file, "life_mode")]
    falls = table.get("falls", False)
    if type(falls) is not bool:
        raise PackError(file, "falls", f"expected true or false, got {falls!r}")
    hit_points = _s16(_require(table, "hit_points", file), file, "hit_points")
    if hit_points < 1:
        raise PackError(file, "hit_points", f"{hit_points} is below 1")
    anims = _parse_anims(_require(table, "anims", file), kind, file)
    attack = _parse_attack(_require(table, "attack", file), file)
    return EnemyRecord(
        id=ident, kind=kind, body=body, stage=stage, room=room, position=position,
        beta=beta, type_zv=type_zv, life_mode=life_mode, falls=falls,
        hit_points=hit_points, anims=anims, attack=attack, file=file,
    )
