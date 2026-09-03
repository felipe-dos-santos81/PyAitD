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
    position = _require(table, "position", file)
    if not isinstance(position, list) or len(position) != 3:
        raise PackError(file, "position", f"expected [x, y, z], got {position!r}")
    position = tuple(_s16(value, file, f"position[{i}]") for i, value in enumerate(position))
    beta = _s16(table.get("beta", 0), file, "beta")
    if not 0 <= beta <= 1023:
        raise PackError(file, "beta", f"{beta} is outside 0..1023")
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
