# SPDX-License-Identifier: GPL-2.0-only
"""Versioned save snapshots (M4a2): source identity, snapshot, and full
validation before anything may touch a live game. Settings ride through as
an opaque JSON-ready dict -- app/config.validate_settings owns them, so this
module never imports the app layer."""
import hashlib
import json
import os
import pathlib
import sys
import tempfile
from dataclasses import fields as dataclass_fields

from PyAitD import __version__
from PyAitD.engine.actor.anim import AnimPlayer
from PyAitD.engine.content.schema import KINDS, PHASES
from PyAitD.engine.script.effects import TimedMessage
from PyAitD.engine.data.formats import WorldObject, parse_defines, parse_objets, parse_vars
from PyAitD.engine.script.game import NUM_MAX_OBJECT, Actor, FloorStart, init_game

SCHEMA = 4

ROOT_KEYS = (
    "schema", "engine_version", "source", "hero", "game", "actors",
    "world_objects", "anim_players", "inventory", "messages", "rng_state",
    "settings", "content_state", "content_flags",
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
_PLAYER_KEYS = {"frame", "start_tick", "prev_frame_index", "states", "anim_step", "wrapped"}
_RNG_STATE_LENGTH = 625  # CPython Mersenne Twister: 624 words + index
_SOURCE_KEYS = {"profile", "archives", "digest", "pack"}
_PACK_KEYS = {"name", "version", "digest"}
_ENEMY_STATE_KEYS = {"hp", "phase"}
_TRIGGER_STATE_KEYS = {"armed", "inside"}


class SaveError(Exception):
    """A save could not be written, read, or validated. The message carries
    the JSON path of the first offending value."""


def source_identity(data_dir, profile, hero, pack=None):
    """The archive names plus one SHA-256 over their bytes, in order: the
    three world files, the life/track paks, then the hero's body/anim paks;
    plus the attached content pack's identity (or None). A save is only
    loadable against the data, and the pack, it came from."""
    archives = source_identity_names(profile, hero)
    digest = hashlib.sha256()
    for name in archives:
        digest.update((pathlib.Path(data_dir) / name).read_bytes())
    return {
        "profile": profile.name, "archives": archives, "digest": digest.hexdigest(),
        "pack": None if pack is None else pack.identity(),
    }


def save_dir(*, platform=None, home=None):
    """The slot directory, beside the settings file app/config writes."""
    platform = sys.platform if platform is None else platform
    home = pathlib.Path.home() if home is None else pathlib.Path(home)
    if platform == "darwin":
        return home / "Library" / "Application Support" / "PyAitD" / "saves"
    return home / ".config" / "pyaitd" / "saves"


def slot_path(directory, kind):
    if kind not in ("manual", "quick"):
        raise ValueError(f"slot kind must be 'manual' or 'quick', got {kind!r}")
    return pathlib.Path(directory) / f"save-{kind}.json"


def write_slot(path, payload):
    """Atomically write the payload: a same-directory temp file, flush +
    fsync, then os.replace. Returns None, or a visible error string; a
    failure never touches an existing slot and leaves no temp file behind."""
    path = pathlib.Path(path)
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, raw_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
        )
        temporary = pathlib.Path(raw_name)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        return None
    except (OSError, ValueError, TypeError) as exc:
        return f"Could not save {path.name}: {exc}"
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def read_slot(path, data_dir, profile, pack=None):
    """Return (payload, None) on success, (None, None) when the slot does
    not exist, and (None, error) for a corrupt or incompatible one."""
    path = pathlib.Path(path)
    if not path.exists():
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"Could not load {path.name}: {exc}"
    try:
        return validate_snapshot(payload, data_dir, profile, pack=pack), None
    except SaveError as exc:
        return None, f"Could not load {path.name}: {exc}"


def snapshot_game(game, settings):
    profile = game.profile
    hero = game.hero
    return {
        "schema": SCHEMA,
        "engine_version": __version__,
        "source": source_identity(game._data_dir, profile, hero, game.pack),
        "hero": hero,
        "game": _snapshot_state(game),
        "actors": [_snapshot_actor(a) for a in game.actors],
        "world_objects": [{name: getattr(w, name) for name in _WORLD_FIELDS}
                          for w in game.world_objects],
        "anim_players": {str(idx): _snapshot_player(player)
                         for idx, player in game.anim_players.items()},
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
        "content_state": {str(idx): dict(state) for idx, state in sorted(game.content_state.items())},
        "content_flags": [] if game.content is None else sorted(game.content.flags),
        "settings": settings,
    }


def validate_snapshot(payload, data_dir, profile, pack=None):
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

    _validate_source(payload["source"], data_dir, profile, hero, pack)
    _validate_state(payload["game"], data_dir, profile)
    _validate_actors(payload["actors"])
    extra = 0 if pack is None else len(pack.enemies) + len(pack.objects)
    first = _validate_world_objects(payload["world_objects"], data_dir, profile.world_object_has_mark, extra)
    _validate_content_state(payload["content_state"], pack, first)
    _validate_content_flags(payload["content_flags"], pack)
    _validate_anim_players(payload["anim_players"])
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


def _snapshot_player(player):
    prev = player.prev_frame
    return {
        "frame": player.frame,
        "start_tick": player.start_tick,
        # body/anim identities are the restored actor's; only the keyframe
        # index rides in the save
        "prev_frame_index": None if prev is None else player.anim.frames.index(prev),
        "states": [[gtype, list(delta)] for gtype, delta in player.group_states()],
        "anim_step": list(player.anim_step),
        "wrapped": player.wrapped,
    }


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


def _validate_source(source, data_dir, profile, hero, pack=None):
    _require_keys(source, _SOURCE_KEYS, "source")
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
    saved = source["pack"]
    if saved is not None:
        _require_keys(saved, _PACK_KEYS, "source.pack")
        for key in sorted(_PACK_KEYS):
            if type(saved[key]) is not str:
                _fail(f"source.pack.{key}", f"expected a string, got {type(saved[key]).__name__}")
    attached = None if pack is None else pack.identity()
    if saved is None and attached is not None:
        _fail("source.pack", f"save was made without a content pack; {attached['name']} is attached")
    if saved is not None and attached is None:
        _fail("source.pack", f"save was made with content pack {saved['name']}; none is attached")
    if saved != attached:
        _fail("source.pack",
              f"content pack mismatch: save has {saved['name']} {saved['version']} ({saved['digest'][:8]}), "
              f"attached is {attached['name']} {attached['version']} ({attached['digest'][:8]})")
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


def _validate_world_objects(world_objects, data_dir, has_mark, extra=0):
    original = len(parse_objets((pathlib.Path(data_dir) / "OBJETS.ITD").read_bytes(), has_mark=has_mark))
    expected = original + extra
    if not isinstance(world_objects, list) or len(world_objects) != expected:
        count = len(world_objects) if isinstance(world_objects, list) else type(world_objects).__name__
        _fail("world_objects", f"expected {expected} world objects, got {count}")
    for i, world in enumerate(world_objects):
        path = f"world_objects[{i}]"
        _require_keys(world, set(_WORLD_FIELDS), path)
        for name in _WORLD_FIELDS:
            _require_int(world[name], f"{path}.{name}")
    return original


def _validate_content_state(state, pack, first_index):
    if not isinstance(state, dict):
        _fail("content_state", "expected an object")
    if pack is None:
        if state:
            _fail("content_state", "expected no content state without a pack")
        return
    records = pack.enemies + pack.objects
    last = first_index + len(records) - 1
    for key, entry in state.items():
        path = f"content_state.{key}"
        if not (type(key) is str and key.isascii() and key.isdigit() and first_index <= int(key) <= last):
            _fail(path, f"expected a world index in {first_index}..{last}")
        record = records[int(key) - first_index]
        if record.kind in KINDS:
            _require_keys(entry, _ENEMY_STATE_KEYS, path)
            _require_int(entry["hp"], f"{path}.hp")
            if entry["phase"] not in PHASES:
                _fail(f"{path}.phase", f"expected one of {', '.join(PHASES)}, got {entry['phase']!r}")
        elif record.kind == "trigger":
            _require_keys(entry, _TRIGGER_STATE_KEYS, path)
            for name in sorted(_TRIGGER_STATE_KEYS):
                if type(entry[name]) is not bool:
                    _fail(f"{path}.{name}", f"expected a boolean, got {type(entry[name]).__name__}")
        else:
            _require_keys(entry, set(), path)
    expected = {str(i) for i in range(first_index, last + 1)}
    if set(state) != expected:
        _fail("content_state", f"expected entries for {first_index}..{last}")


def _validate_content_flags(flags, pack):
    if not isinstance(flags, list):
        _fail("content_flags", f"expected a list, got {type(flags).__name__}")
    if pack is None and flags:
        _fail("content_flags", "expected no content flags without a pack")
    for i, flag in enumerate(flags):
        if type(flag) is not str or not flag:
            _fail(f"content_flags[{i}]", f"expected a non-empty string, got {flag!r}")
    if len(set(flags)) != len(flags):
        _fail("content_flags", "duplicate flag names")


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
    _require_int_list(state[1], "rng_state[1]", _RNG_STATE_LENGTH)
    gauss = state[2]
    if gauss is not None and type(gauss) is not float:
        _fail("rng_state[2]", f"expected a float or null, got {type(gauss).__name__}")


def _validate_anim_players(players):
    if type(players) is not dict:
        _fail("anim_players", f"expected an object, got {type(players).__name__}")
    for key, entry in players.items():
        if not (isinstance(key, str) and key.isascii() and key.isdigit() and int(key) < NUM_MAX_OBJECT):
            _fail("anim_players", f"bad actor key {key!r}")
        path = f"anim_players[{key}]"
        _require_keys(entry, _PLAYER_KEYS, path)
        _require_int(entry["frame"], f"{path}.frame")
        _require_int(entry["start_tick"], f"{path}.start_tick")
        prev = entry["prev_frame_index"]
        if prev is not None:
            _require_int(prev, f"{path}.prev_frame_index")
        states = entry["states"]
        if not isinstance(states, list):
            _fail(f"{path}.states", f"expected a list, got {type(states).__name__}")
        for i, state in enumerate(states):
            if not isinstance(state, list) or len(state) != 2:
                _fail(f"{path}.states[{i}]", "expected [group type, [x, y, z]]")
            _require_int(state[0], f"{path}.states[{i}][0]")
            _require_int_list(state[1], f"{path}.states[{i}][1]", 3)
        _require_int_list(entry["anim_step"], f"{path}.anim_step", 3)
        if type(entry["wrapped"]) is not bool:
            _fail(f"{path}.wrapped", f"expected a boolean, got {type(entry['wrapped']).__name__}")


def restore_game(data_dir, profile, payload, pack=None):
    """Validate the complete payload, then rebuild a fresh Game from it.
    Nothing live is mutated: any failure raises SaveError before the new
    game is returned. The settings block comes back untouched for
    app/config.validate_settings to own."""
    payload = validate_snapshot(payload, data_dir, profile, pack=pack)
    game = init_game(data_dir, profile, hero=payload["hero"], pack=pack)

    state = payload["game"]
    game.timer = state["timer"]
    game._last_time_forward = state["last_time_forward"]
    game.action = state["action"]
    game.vars = list(state["vars"])
    game.cvars = list(state["cvars"])
    game.current_floor = state["current_floor"]
    game.current_room = state["current_room"]
    game.current_stage = state["current_stage"]
    game.num_camera = state["num_camera"]
    game.new_num_camera = state["new_num_camera"]
    game.current_camera_target_actor = state["current_camera_target_actor"]
    game.current_world_target = state["current_world_target"]
    game.flag_change_etage = state["flag_change_etage"]
    game.new_num_etage = state["new_num_etage"]
    game.flag_change_salle = state["flag_change_salle"]
    game.new_num_salle = state["new_num_salle"]
    game.hard_clip = list(state["hard_clip"])
    game.status_screen_allowed = state["status_screen_allowed"]
    game.allow_system_menu = state["allow_system_menu"]
    game.current_music = state["current_music"]
    game.next_music = state["next_music"]
    game.light_off = state["light_off"]
    game.last_sample = state["last_sample"]
    game.next_sample = state["next_sample"]
    game.last_priority = state["last_priority"]
    floor_start = state["floor_start"]
    game.floor_start = None if floor_start is None else FloorStart(
        floor_start["stage"], floor_start["room"], floor_start["x"],
        floor_start["y"], floor_start["z"], floor_start["camera_slot"],
    )
    # the flags snapshot carries, overridden by fresh-boot semantics:
    # a loaded game re-inits its view and regenerates its active list
    game.flag_init_view = 2
    game.flag_genere_aff_list = 1

    for idx, entry in enumerate(payload["actors"]):
        actor = game.actors[idx]
        for name in _ACTOR_INT_FIELDS:
            setattr(actor, name, entry[name])
        for name in _ACTOR_LIST_FIELDS:
            setattr(actor, name, list(entry[name]))
        for name in _ACTOR_REALVALUE_FIELDS:
            realvalue = getattr(actor, name)
            for key in _REALVALUE_KEYS:
                setattr(realvalue, key, entry[name][key])

    for world, entry in zip(game.world_objects, payload["world_objects"]):
        for name in _WORLD_FIELDS:
            setattr(world, name, entry[name])
    game.content_state = {int(key): dict(entry) for key, entry in payload["content_state"].items()}
    if game.content is not None:
        game.content.flags = set(payload["content_flags"])

    for key, entry in payload["anim_players"].items():
        idx = int(key)
        actor = game.actors[idx]
        path = f"anim_players[{key}]"
        if actor.anim == -1:
            _fail(path, "actor has no animation")
        try:
            body = game.assets.body(actor.body_num)
            anim = game.assets.anim(actor.anim)
        except Exception as exc:
            _fail(path, f"actor's body/anim cannot be resolved: {exc}")
        prev = entry["prev_frame_index"]
        if prev is not None and not 0 <= prev < anim.num_frames:
            _fail(f"{path}.prev_frame_index",
                  f"expected 0..{anim.num_frames - 1}, got {prev}")
        player = AnimPlayer(body, anim, entry["start_tick"])
        player.frame = entry["frame"]
        player.prev_frame = None if prev is None else anim.frames[prev]
        player._states = [(gtype, tuple(delta)) for gtype, delta in entry["states"]]
        player.anim_step = tuple(entry["anim_step"])
        player.wrapped = entry["wrapped"]
        game.anim_players[idx] = player

    inventory = payload["inventory"]
    game.inventory_table = [list(row) for row in inventory["table"]]
    game.inventory_count = list(inventory["count"])
    game.in_hand_table = list(inventory["in_hand"])
    game.current_inventory = inventory["current"]

    game.messages = [
        None if m is None else TimedMessage(m["message_id"], m["age"])
        for m in payload["messages"]
    ]

    version, internal, gauss = payload["rng_state"]
    game.rng.setstate((version, tuple(internal), gauss))
    return game, payload["settings"]
