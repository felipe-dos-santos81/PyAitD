# SPDX-License-Identifier: GPL-2.0-only
"""Versioned save snapshots (M4a2): source identity, snapshot, and full
validation before anything may touch a live game. Settings ride through as
an opaque JSON-ready dict -- app/config.validate_settings owns them, so this
module never imports the app layer."""
import hashlib
import pathlib
from dataclasses import fields as dataclass_fields

from PyAitD import __version__
from PyAitD.engine.formats import WorldObject, parse_defines, parse_objets, parse_vars
from PyAitD.engine.game import NUM_MAX_OBJECT, Actor

SCHEMA = 1

ROOT_KEYS = (
    "schema", "engine_version", "source", "hero", "game", "actors",
    "world_objects", "anim_players", "inventory", "messages", "rng_state",
    "settings",
)

GAME_KEYS = (
    "timer", "last_time_forward", "action", "vars", "cvars",
    "current_floor", "current_room", "current_stage",
    "num_camera", "new_num_camera",
    "current_camera_target_actor", "current_world_target",
    "flag_change_etage", "new_num_etage",
    "flag_change_salle", "new_num_salle",
    "flag_init_view", "flag_game_over", "flag_genere_aff_list",
    "hard_clip", "status_screen_allowed", "allow_system_menu",
    "current_music", "next_music", "light_off",
    "last_sample", "next_sample", "last_priority",
    "floor_start",
)

_WORLD_ARCHIVES = ("OBJETS.ITD", "VARS.ITD", "DEFINES.ITD")
_ACTOR_FIELDS = tuple(f.name for f in dataclass_fields(Actor))
_ACTOR_LIST_FIELDS = {"zv": 6, "col": 3, "hot_point": 3}
_ACTOR_REALVALUE_FIELDS = {"y_handler", "rotate", "speed_change"}
_ACTOR_INT_FIELDS = frozenset(_ACTOR_FIELDS) - set(_ACTOR_LIST_FIELDS) - _ACTOR_REALVALUE_FIELDS
_REALVALUE_KEYS = {"start_value", "end_value", "num_steps", "memo_ticks"}
_WORLD_FIELDS = tuple(f.name for f in dataclass_fields(WorldObject))
_FLOOR_START_KEYS = {"stage", "room", "x", "y", "z", "camera_slot"}
_INVENTORY_KEYS = {"table", "count", "in_hand", "current"}
_MESSAGE_KEYS = {"message_id", "age"}


class SaveError(Exception):
    """A save could not be written, read, or validated. The message carries
    the JSON path of the first offending value."""


def source_identity(data_dir, profile, hero):
    """The archive names plus one SHA-256 over their bytes, in order: the
    three world files, the life/track paks, then the hero's body/anim paks.
    A save is only loadable against the data it came from."""
    archives = source_identity_names(profile, hero)
    digest = hashlib.sha256()
    for name in archives:
        digest.update((pathlib.Path(data_dir) / name).read_bytes())
    return {"profile": profile.name, "archives": archives, "digest": digest.hexdigest()}


def snapshot_game(game, settings):
    profile = game.profile
    hero = game.hero
    return {
        "schema": SCHEMA,
        "engine_version": __version__,
        "source": source_identity(game._data_dir, profile, hero),
        "hero": hero,
        "game": _snapshot_state(game),
        "actors": [_snapshot_actor(a) for a in game.actors],
        "world_objects": [{name: getattr(w, name) for name in _WORLD_FIELDS}
                          for w in game.world_objects],
        # task 3 fills in the per-actor animation players
        "anim_players": {},
        "inventory": {
            "table": [list(row) for row in game.inventory_table],
            "count": list(game.inventory_count),
            "in_hand": list(game.in_hand_table),
            "current": game.current_inventory,
        },
        "messages": [
            None if m is None else {"message_id": m.message_id, "age": m.age}
            for m in game.messages
        ],
        "rng_state": _rng_to_json(game.rng.getstate()),
        "settings": settings,
    }


def validate_snapshot(payload, data_dir, profile):
    """Parse and validate the complete payload before a fresh Game may be
    built from it; raises SaveError with JSON-path context. Returns the
    payload unchanged."""
    if not isinstance(payload, dict):
        _fail("root", "expected an object")
    _require_keys(payload, set(ROOT_KEYS), "root")

    schema = _require_int(payload["schema"], "schema")
    if schema != SCHEMA:
        _fail("schema", f"expected schema {SCHEMA}, got {schema}")
    if type(payload["engine_version"]) is not str:
        _fail("engine_version", f"expected a string, got {type(payload['engine_version']).__name__}")

    hero = _require_int(payload["hero"], "hero")
    if not 0 <= hero < len(profile.heroes):
        _fail("hero", f"expected 0..{len(profile.heroes) - 1}, got {hero}")

    _validate_source(payload["source"], data_dir, profile, hero)
    _validate_state(payload["game"], data_dir, profile)
    _validate_actors(payload["actors"])
    _validate_world_objects(payload["world_objects"], data_dir)
    if type(payload["anim_players"]) is not dict:
        _fail("anim_players", f"expected an object, got {type(payload['anim_players']).__name__}")
    _validate_inventory(payload["inventory"])
    _validate_messages(payload["messages"])
    _validate_rng_state(payload["rng_state"])
    if not isinstance(payload["settings"], dict):
        _fail("settings", "expected an object")
    return payload


# ── snapshot helpers ────────────────────────────────────────────────────────


def _snapshot_state(game):
    floor_start = game.floor_start
    return {
        "timer": game.timer,
        "last_time_forward": game._last_time_forward,
        "action": game.action,
        "vars": list(game.vars),
        "cvars": list(game.cvars),
        "current_floor": game.current_floor,
        "current_room": game.current_room,
        "current_stage": game.current_stage,
        "num_camera": game.num_camera,
        "new_num_camera": game.new_num_camera,
        "current_camera_target_actor": game.current_camera_target_actor,
        "current_world_target": game.current_world_target,
        "flag_change_etage": game.flag_change_etage,
        "new_num_etage": game.new_num_etage,
        "flag_change_salle": game.flag_change_salle,
        "new_num_salle": game.new_num_salle,
        "flag_init_view": game.flag_init_view,
        "flag_game_over": game.flag_game_over,
        "flag_genere_aff_list": game.flag_genere_aff_list,
        "hard_clip": list(game.hard_clip),
        "status_screen_allowed": game.status_screen_allowed,
        "allow_system_menu": game.allow_system_menu,
        "current_music": game.current_music,
        "next_music": game.next_music,
        "light_off": game.light_off,
        "last_sample": game.last_sample,
        "next_sample": game.next_sample,
        "last_priority": game.last_priority,
        "floor_start": None if floor_start is None else {
            "stage": floor_start.stage, "room": floor_start.room,
            "x": floor_start.x, "y": floor_start.y, "z": floor_start.z,
            "camera_slot": floor_start.camera_slot,
        },
    }


def _snapshot_actor(actor):
    out = {}
    for name in _ACTOR_FIELDS:
        value = getattr(actor, name)
        if name in _ACTOR_REALVALUE_FIELDS:
            out[name] = {key: getattr(value, key) for key in _REALVALUE_KEYS}
        elif name in _ACTOR_LIST_FIELDS:
            out[name] = list(value)
        else:
            out[name] = value
    return out


def _rng_to_json(state):
    version, internal, gauss_next = state
    return [version, list(internal), gauss_next]


# ── validation helpers ──────────────────────────────────────────────────────


def _fail(path, message):
    raise SaveError(f"{path}: {message}")


def _require_keys(obj, expected, path):
    if not isinstance(obj, dict):
        _fail(path, f"expected an object, got {type(obj).__name__}")
    missing = expected - set(obj)
    if missing:
        _fail(path, f"missing keys: {', '.join(sorted(missing))}")
    extra = set(obj) - expected
    if extra:
        _fail(path, f"unexpected keys: {', '.join(sorted(extra))}")


def _require_int(value, path):
    if type(value) is not int:
        _fail(path, f"expected an integer, got {type(value).__name__}")
    return value


def _require_int_list(value, path, length=None):
    if not isinstance(value, list):
        _fail(path, f"expected a list, got {type(value).__name__}")
    if length is not None and len(value) != length:
        _fail(path, f"expected {length} entries, got {len(value)}")
    for i, item in enumerate(value):
        _require_int(item, f"{path}[{i}]")
    return value


def _read_archives(data_dir, archives):
    raws = {}
    data_dir = pathlib.Path(data_dir)
    for name in archives:
        path = data_dir / name
        if not path.is_file():
            raise SaveError(f"source: {name} not found in {data_dir}")
        raws[name] = path.read_bytes()
    return raws


def _validate_source(source, data_dir, profile, hero):
    _require_keys(source, {"profile", "archives", "digest"}, "source")
    expected = source_identity_names(profile, hero)
    archives = source["archives"]
    if source["profile"] != profile.name or archives != expected:
        _fail("source", "data identity mismatch: archives do not match this game")
    raws = _read_archives(data_dir, expected)
    digest = hashlib.sha256()
    for name in expected:
        digest.update(raws[name])
    if source["digest"] != digest.hexdigest():
        _fail("source", "data identity mismatch: digest does not match this game data")
    return raws


def source_identity_names(profile, hero):
    body_pak, anim_pak = profile.hero_archives(hero)
    return list(_WORLD_ARCHIVES) + [
        f"{profile.lifes_pak}.PAK", f"{profile.tracks_pak}.PAK",
        f"{body_pak}.PAK", f"{anim_pak}.PAK",
    ]


def _validate_state(state, data_dir, profile):
    _require_keys(state, set(GAME_KEYS), "game")
    raws = _read_archives(data_dir, list(_WORLD_ARCHIVES))
    _require_int_list(state["vars"], "game.vars", len(parse_vars(raws["VARS.ITD"])))
    _require_int_list(
        state["cvars"], "game.cvars",
        len(parse_defines(raws["DEFINES.ITD"], big_endian=profile.defines_big_endian)),
    )
    _require_int_list(state["hard_clip"], "game.hard_clip", 6)
    if type(state["allow_system_menu"]) is not bool:
        _fail("game.allow_system_menu",
              f"expected a boolean, got {type(state['allow_system_menu']).__name__}")
    floor_start = state["floor_start"]
    if floor_start is not None:
        _require_keys(floor_start, _FLOOR_START_KEYS, "game.floor_start")
        for key in _FLOOR_START_KEYS:
            _require_int(floor_start[key], f"game.floor_start.{key}")
    for key in GAME_KEYS:
        if key in ("vars", "cvars", "hard_clip", "allow_system_menu", "floor_start"):
            continue
        _require_int(state[key], f"game.{key}")


def _validate_actors(actors):
    if not isinstance(actors, list) or len(actors) != NUM_MAX_OBJECT:
        count = len(actors) if isinstance(actors, list) else type(actors).__name__
        _fail("actors", f"expected {NUM_MAX_OBJECT} actors, got {count}")
    for i, actor in enumerate(actors):
        path = f"actors[{i}]"
        _require_keys(actor, set(_ACTOR_FIELDS), path)
        for name in _ACTOR_INT_FIELDS:
            _require_int(actor[name], f"{path}.{name}")
        for name, length in _ACTOR_LIST_FIELDS.items():
            _require_int_list(actor[name], f"{path}.{name}", length)
        for name in _ACTOR_REALVALUE_FIELDS:
            value = actor[name]
            _require_keys(value, _REALVALUE_KEYS, f"{path}.{name}")
            for key in _REALVALUE_KEYS:
                _require_int(value[key], f"{path}.{name}.{key}")


def _validate_world_objects(world_objects, data_dir):
    expected = len(parse_objets((pathlib.Path(data_dir) / "OBJETS.ITD").read_bytes()))
    if not isinstance(world_objects, list) or len(world_objects) != expected:
        count = len(world_objects) if isinstance(world_objects, list) else type(world_objects).__name__
        _fail("world_objects", f"expected {expected} world objects, got {count}")
    for i, world in enumerate(world_objects):
        path = f"world_objects[{i}]"
        _require_keys(world, set(_WORLD_FIELDS), path)
        for name in _WORLD_FIELDS:
            _require_int(world[name], f"{path}.{name}")


def _validate_inventory(inventory):
    _require_keys(inventory, _INVENTORY_KEYS, "inventory")
    table = inventory["table"]
    if not isinstance(table, list) or len(table) != 2:
        _fail("inventory.table", "expected 2 rows")
    for i, row in enumerate(table):
        _require_int_list(row, f"inventory.table[{i}]", 30)
    _require_int_list(inventory["count"], "inventory.count", 2)
    _require_int_list(inventory["in_hand"], "inventory.in_hand", 2)
    _require_int(inventory["current"], "inventory.current")


def _validate_messages(messages):
    if not isinstance(messages, list) or len(messages) != 5:
        count = len(messages) if isinstance(messages, list) else type(messages).__name__
        _fail("messages", f"expected 5 slots, got {count}")
    for i, message in enumerate(messages):
        if message is None:
            continue
        path = f"messages[{i}]"
        _require_keys(message, _MESSAGE_KEYS, path)
        _require_int(message["message_id"], f"{path}.message_id")
        _require_int(message["age"], f"{path}.age")


def _validate_rng_state(state):
    if not isinstance(state, list) or len(state) != 3:
        _fail("rng_state", "expected [version, internal state, gauss_next]")
    _require_int(state[0], "rng_state[0]")
    _require_int_list(state[1], "rng_state[1]")
    gauss = state[2]
    if gauss is not None and type(gauss) is not float:
        _fail("rng_state[2]", f"expected a float or null, got {type(gauss).__name__}")
