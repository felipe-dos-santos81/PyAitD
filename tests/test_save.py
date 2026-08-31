# SPDX-License-Identifier: GPL-2.0-only
"""M4a2 task 2: the versioned save snapshot schema, the data-source identity,
and full validation before anything may touch a live game."""
import copy
import json
import tomllib
from dataclasses import fields

import pytest

from PyAitD import __version__
from PyAitD.engine.data.formats import WorldObject
from PyAitD.engine.script.game import NUM_MAX_OBJECT, Actor
from PyAitD.engine.script.game import init_game
from PyAitD.engine.script.save import SCHEMA, SaveError, source_identity, snapshot_game, validate_snapshot

pytestmark = pytest.mark.engine

ROOT_KEYS = {
    "schema", "engine_version", "source", "hero", "game", "actors",
    "world_objects", "anim_players", "inventory", "messages", "rng_state",
    "settings",
}

SETTINGS = {"schema": 2, "sticky_action": False, "bindings": {}, "render": {}}


def _game(data_dir, profile, hero=0):
    return init_game(data_dir, profile, hero=hero)


def _snapshot(data_dir, profile):
    return snapshot_game(_game(data_dir, profile), SETTINGS)


# ── shape ────────────────────────────────────────────────────────────────────


def test_engine_version_matches_pyproject():
    with open("pyproject.toml", "rb") as f:
        assert __version__ == tomllib.load(f)["project"]["version"]


def test_snapshot_root_keys_pinned(data_dir, profile):
    payload = _snapshot(data_dir, profile)
    assert set(payload) == ROOT_KEYS
    assert payload["schema"] == SCHEMA == 2
    assert payload["engine_version"] == __version__
    assert payload["hero"] == 0


def test_snapshot_counts_and_shapes(data_dir, profile):
    payload = _snapshot(data_dir, profile)
    assert len(payload["actors"]) == NUM_MAX_OBJECT == 128
    assert len(payload["world_objects"]) == 292
    assert len(payload["game"]["cvars"]) == 45
    assert len(payload["game"]["vars"]) == 207
    assert len(payload["inventory"]["table"]) == 2
    assert all(len(row) == 30 for row in payload["inventory"]["table"])
    assert len(payload["messages"]) == 5


def test_snapshot_floor_start_is_none_when_unstaged(data_dir, profile):
    game = _game(data_dir, profile)
    game.floor_start = None
    assert snapshot_game(game, SETTINGS)["game"]["floor_start"] is None


def test_actor_and_world_object_field_names_match_dataclasses(data_dir, profile):
    payload = _snapshot(data_dir, profile)
    actor_fields = {f.name for f in fields(Actor)}
    world_fields = {f.name for f in fields(WorldObject)}
    assert all(set(a) == actor_fields for a in payload["actors"])
    assert all(set(w) == world_fields for w in payload["world_objects"])
    # RealValue fields encode as their four integer fields
    for name in ("y_handler", "rotate", "speed_change"):
        assert set(payload["actors"][0][name]) == {
            "start_value", "end_value", "num_steps", "memo_ticks"
        }


def test_snapshot_excludes_transient_and_cache_fields(data_dir, profile):
    payload = _snapshot(data_dir, profile)
    assert set(payload["game"]) == {
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
    }
    assert payload["anim_players"] == {}
    assert payload["settings"] == SETTINGS
    # the RNG rides in rng_state alone, never inside the game dict
    assert "rng" not in payload["game"]


def test_snapshot_floor_start_encodes_the_restart_boundary(data_dir, profile):
    from PyAitD.engine.script.game import FloorStart
    game = _game(data_dir, profile)
    game.floor_start = FloorStart(5, 4, -7800, -4010, -1000, 0)
    assert snapshot_game(game, SETTINGS)["game"]["floor_start"] == {
        "stage": 5, "room": 4, "x": -7800, "y": -4010, "z": -1000,
        "camera_slot": 0,
    }


# ── source identity ─────────────────────────────────────────────────────────


def test_source_identity_names_and_digest_stable(data_dir, profile):
    source = source_identity(data_dir, profile, hero=0)
    assert source["profile"] == "aitd1"
    assert source["archives"] == [
        "OBJETS.ITD", "VARS.ITD", "DEFINES.ITD",
        "LISTLIFE.PAK", "LISTTRAK.PAK", "LISTBODY.PAK", "LISTANIM.PAK",
    ]
    assert source["digest"] == source_identity(data_dir, profile, hero=0)["digest"]
    emily = source_identity(data_dir, profile, hero=1)
    assert emily["archives"][-2:] == ["LISTBOD2.PAK", "LISTANI2.PAK"]
    assert emily["digest"] != source["digest"]


def test_source_identity_sensitive_to_one_byte(tmp_path):
    names = ["OBJETS.ITD", "VARS.ITD", "DEFINES.ITD",
             "LISTLIFE.PAK", "LISTTRAK.PAK", "LISTBODY.PAK", "LISTANIM.PAK"]
    for name in names:
        (tmp_path / name).write_bytes(b"\x00" * 64)

    class _Profile:
        name = "aitd1"
        lifes_pak = "LISTLIFE"
        tracks_pak = "LISTTRAK"

        def hero_archives(self, hero):
            return ("LISTBODY", "LISTANIM")

    before = source_identity(tmp_path, _Profile(), hero=0)["digest"]
    blob = bytearray((tmp_path / "VARS.ITD").read_bytes())
    blob[7] ^= 0x01
    (tmp_path / "VARS.ITD").write_bytes(bytes(blob))
    assert source_identity(tmp_path, _Profile(), hero=0)["digest"] != before


# ── validation ───────────────────────────────────────────────────────────────


def test_validate_round_trip_json(data_dir, profile):
    payload = _snapshot(data_dir, profile)
    assert validate_snapshot(json.loads(json.dumps(payload)), data_dir, profile)


def test_validate_rejects_unknown_schema(data_dir, profile):
    payload = _snapshot(data_dir, profile)
    payload["schema"] = 3
    with pytest.raises(SaveError, match=r"schema"):
        validate_snapshot(payload, data_dir, profile)


def test_validate_rejects_missing_and_extra_root_keys(data_dir, profile):
    payload = _snapshot(data_dir, profile)
    del payload["rng_state"]
    with pytest.raises(SaveError, match=r"rng_state"):
        validate_snapshot(payload, data_dir, profile)
    payload = _snapshot(data_dir, profile)
    payload["extra"] = 1
    with pytest.raises(SaveError, match=r"extra"):
        validate_snapshot(payload, data_dir, profile)


def test_validate_rejects_bool_as_int(data_dir, profile):
    payload = _snapshot(data_dir, profile)
    payload["game"]["timer"] = True
    with pytest.raises(SaveError, match=r"game\.timer"):
        validate_snapshot(payload, data_dir, profile)


def test_validate_reports_json_paths(data_dir, profile):
    payload = _snapshot(data_dir, profile)
    payload["actors"][3]["zv"][2] = "deep"
    with pytest.raises(SaveError, match=r"actors\[3\]\.zv\[2\]"):
        validate_snapshot(payload, data_dir, profile)
    payload = _snapshot(data_dir, profile)
    payload["world_objects"][9]["beta"] = None
    with pytest.raises(SaveError, match=r"world_objects\[9\]\.beta"):
        validate_snapshot(payload, data_dir, profile)


def test_validate_rejects_count_and_shape_mismatches(data_dir, profile):
    payload = _snapshot(data_dir, profile)
    payload["actors"] = payload["actors"][:127]
    with pytest.raises(SaveError, match=r"128"):
        validate_snapshot(payload, data_dir, profile)
    payload = _snapshot(data_dir, profile)
    payload["game"]["vars"] = payload["game"]["vars"][:-1]
    with pytest.raises(SaveError, match=r"vars"):
        validate_snapshot(payload, data_dir, profile)
    payload = _snapshot(data_dir, profile)
    payload["inventory"]["table"][1] = payload["inventory"]["table"][1][:29]
    with pytest.raises(SaveError, match=r"inventory"):
        validate_snapshot(payload, data_dir, profile)
    payload = _snapshot(data_dir, profile)
    payload["messages"] = payload["messages"][:4]
    with pytest.raises(SaveError, match=r"messages"):
        validate_snapshot(payload, data_dir, profile)


def test_validate_rejects_actor_field_mismatch(data_dir, profile):
    payload = _snapshot(data_dir, profile)
    del payload["actors"][0]["beta"]
    with pytest.raises(SaveError, match=r"actors\[0\].*beta"):
        validate_snapshot(payload, data_dir, profile)
    payload = _snapshot(data_dir, profile)
    payload["actors"][0]["surprise"] = 1
    with pytest.raises(SaveError, match=r"actors\[0\].*surprise"):
        validate_snapshot(payload, data_dir, profile)


def test_validate_rejects_bad_identity_and_hero(data_dir, profile):
    payload = _snapshot(data_dir, profile)
    payload["source"]["digest"] = "0" * 64
    with pytest.raises(SaveError, match=r"identity"):
        validate_snapshot(payload, data_dir, profile)
    payload = _snapshot(data_dir, profile)
    payload["hero"] = 2
    with pytest.raises(SaveError, match=r"hero"):
        validate_snapshot(payload, data_dir, profile)
    payload = _snapshot(data_dir, profile)
    payload["source"]["archives"][0] = "OTHER.ITD"
    with pytest.raises(SaveError, match=r"identity"):
        validate_snapshot(payload, data_dir, profile)


def test_validate_rejects_corrupt_rng_state(data_dir, profile):
    payload = _snapshot(data_dir, profile)
    payload["rng_state"][1][0] = "not-an-int"
    with pytest.raises(SaveError, match=r"rng_state"):
        validate_snapshot(payload, data_dir, profile)
    payload = _snapshot(data_dir, profile)
    payload["rng_state"] = payload["rng_state"][:2]
    with pytest.raises(SaveError, match=r"rng_state"):
        validate_snapshot(payload, data_dir, profile)


# ── task 3: animation state and fresh-game restoration ──────────────────────

from PyAitD.engine.actor.actors import anim_player_for
from PyAitD.engine.script.effects import TimedMessage
from PyAitD.engine.data.floor import Floor
from PyAitD.engine.script.game import FloorStart
from PyAitD.engine.nav.navmesh import MeshCache
from PyAitD.engine.script.playworld import play_tick
from PyAitD.engine.script.save import restore_game


PLAYER_KEYS = {"frame", "start_tick", "prev_frame_index", "states", "anim_step", "wrapped"}


def _animated_slot(game, slot=127):
    actor = game.actors[slot]
    actor.body_num = 4
    actor.anim = 0
    player = anim_player_for(game, slot)
    player.advance(game.timer + 1)
    return slot, player


def test_snapshot_encodes_anim_players(data_dir, profile):
    game = _game(data_dir, profile)
    slot, player = _animated_slot(game)
    payload = snapshot_game(game, SETTINGS)
    entry = payload["anim_players"][str(slot)]
    assert set(entry) == PLAYER_KEYS
    assert entry["frame"] == player.frame
    assert entry["start_tick"] == player.start_tick
    expected_prev = None if player.prev_frame is None else player.anim.frames.index(player.prev_frame)
    assert entry["prev_frame_index"] == expected_prev
    assert entry["anim_step"] == list(player.anim_step)
    assert entry["wrapped"] == player.wrapped


def test_restore_round_trip_state(data_dir, profile):
    game = _game(data_dir, profile)
    # representatives of every persisted field family
    game.timer = 1234
    game.action = 0x2000
    game.vars[5] = 4242
    game.cvars[10] = 701
    hero = game.actors[0]
    hero.beta = 123
    hero.world_x += 5
    hero.speed_change.end_value = 9
    hero.zv[1] = 42
    game.world_objects[3].beta = 512
    game.inventory_table[0][0] = 2
    game.inventory_count[0] = 1
    game.in_hand_table[0] = 2
    game.messages[0] = TimedMessage(5, age=3)
    game.floor_start = FloorStart(5, 4, -7800, -4010, -1000, 0)
    game.rng.seed(77)
    game.rng.randrange(100)
    _animated_slot(game)

    payload = json.loads(json.dumps(snapshot_game(game, SETTINGS)))
    restored, settings = restore_game(data_dir, profile, payload)
    assert settings == SETTINGS
    assert snapshot_game(restored, SETTINGS) == payload


def test_restored_game_ticks_and_draws_like_the_original(data_dir, profile):
    game = _game(data_dir, profile)
    game.rng.seed(77)
    _animated_slot(game)
    payload = json.loads(json.dumps(snapshot_game(game, SETTINGS)))
    restored, _ = restore_game(data_dir, profile, payload)

    play_tick(game, Floor(data_dir, game.current_floor, profile), _input_buffer())
    play_tick(restored, Floor(data_dir, restored.current_floor, profile), _input_buffer())
    assert snapshot_game(game, SETTINGS) == snapshot_game(restored, SETTINGS)
    assert game.rng.randrange(1000) == restored.rng.randrange(1000)


def _input_buffer():
    from PyAitD.app.ui import InputBuffer
    return InputBuffer()


def test_restore_resets_transient_state_and_forces_boot_flags(data_dir, profile):
    payload = _snapshot(data_dir, profile)
    payload["game"]["flag_init_view"] = 0
    payload["game"]["flag_genere_aff_list"] = 0
    restored, _ = restore_game(data_dir, profile, payload)
    assert restored.flag_init_view == 2
    assert restored.flag_genere_aff_list == 1
    assert restored.active_modal is None
    assert restored.life_stack == []
    assert not restored.immediate_effects
    assert restored.nav_intent is None
    assert restored.nav_decision is None
    assert restored.nav_arrived_target == -1
    assert not restored.restart_requested
    assert isinstance(restored.nav_meshes, MeshCache)


def test_restore_rejects_players_inconsistent_with_their_actor(data_dir, profile):
    payload = _snapshot(data_dir, profile)
    payload["anim_players"]["127"] = {
        "frame": 0, "start_tick": 0, "prev_frame_index": None,
        "states": [[0, [0, 0, 0]]], "anim_step": [0, 0, 0], "wrapped": False,
    }
    with pytest.raises(SaveError, match=r"anim_players\[127\]"):
        restore_game(data_dir, profile, payload)


def test_validate_rejects_bad_anim_player_entries(data_dir, profile):
    payload = _snapshot(data_dir, profile)
    payload["anim_players"]["nope"] = {}
    with pytest.raises(SaveError, match=r"anim_players"):
        validate_snapshot(payload, data_dir, profile)
    payload = _snapshot(data_dir, profile)
    payload["anim_players"]["3"] = {
        "frame": "x", "start_tick": 0, "prev_frame_index": None,
        "states": [], "anim_step": [0, 0, 0], "wrapped": False,
    }
    with pytest.raises(SaveError, match=r"anim_players\[3\]\.frame"):
        validate_snapshot(payload, data_dir, profile)
    payload = _snapshot(data_dir, profile)
    payload["anim_players"]["3"] = {
        "frame": 0, "start_tick": 0, "prev_frame_index": None,
        "states": [], "anim_step": [0, 0], "wrapped": False,
    }
    with pytest.raises(SaveError, match=r"anim_players\[3\]\.anim_step"):
        validate_snapshot(payload, data_dir, profile)


# ── task 4: atomic manual and quick slot storage ────────────────────────────

import PyAitD.engine.script.save as save_module
from PyAitD.app.config import settings_path
from PyAitD.engine.script.save import read_slot, save_dir, slot_path, write_slot


def test_save_dir_sits_beside_the_settings_path(tmp_path):
    for platform in ("darwin", "linux"):
        assert save_dir(platform=platform, home=tmp_path).parent == \
            settings_path(platform=platform, home=tmp_path).parent
    assert save_dir(platform="darwin", home=tmp_path) == \
        tmp_path / "Library" / "Application Support" / "PyAitD" / "saves"
    assert save_dir(platform="linux", home=tmp_path) == \
        tmp_path / ".config" / "pyaitd" / "saves"


def test_slot_path_names_and_kinds(tmp_path):
    assert slot_path(tmp_path, "manual") == tmp_path / "save-manual.json"
    assert slot_path(tmp_path, "quick") == tmp_path / "save-quick.json"
    with pytest.raises(ValueError):
        slot_path(tmp_path, "auto")


def test_write_and_read_slot_round_trip(data_dir, profile, tmp_path):
    payload = _snapshot(data_dir, profile)
    slot = slot_path(tmp_path, "manual")
    assert write_slot(slot, payload) is None
    raw = slot.read_text(encoding="utf-8")
    assert raw == json.dumps(payload, sort_keys=True, separators=(",", ":"))
    loaded, error = read_slot(slot, data_dir, profile)
    assert error is None
    assert loaded == payload


def test_read_missing_slot_is_not_an_error(tmp_path, data_dir, profile):
    assert read_slot(slot_path(tmp_path, "manual"), data_dir, profile) == (None, None)


def test_read_malformed_slot_reports_an_error(tmp_path, data_dir, profile):
    slot = slot_path(tmp_path, "manual")
    slot.write_text("{truncated", encoding="utf-8")
    loaded, error = read_slot(slot, data_dir, profile)
    assert loaded is None
    assert "save-manual.json" in error


def test_read_incompatible_slot_reports_an_error(tmp_path, data_dir, profile):
    payload = _snapshot(data_dir, profile)
    payload["source"]["digest"] = "0" * 64
    slot = slot_path(tmp_path, "quick")
    assert write_slot(slot, payload) is None
    loaded, error = read_slot(slot, data_dir, profile)
    assert loaded is None
    assert "identity" in error


def test_write_to_an_impossible_path_reports_an_error(data_dir, profile, tmp_path):
    payload = _snapshot(data_dir, profile)
    impossible = tmp_path / "not-a-dir.json" / "save-manual.json"
    impossible.parent.write_text("a file, not a directory", encoding="utf-8")
    error = write_slot(impossible, payload)
    assert error and "save-manual.json" in error


def _written_slot(data_dir, profile, tmp_path):
    payload = _snapshot(data_dir, profile)
    slot = slot_path(tmp_path, "manual")
    assert write_slot(slot, payload) is None
    return payload, slot, slot.read_bytes()


def _assert_failure_left_nothing_behind(tmp_path, slot, before):
    assert slot.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == [slot.name]


def test_dump_failure_keeps_the_prior_slot(data_dir, profile, tmp_path, monkeypatch):
    _, slot, before = _written_slot(data_dir, profile, tmp_path)

    def boom(*args, **kwargs):
        raise OSError("simulated dump failure")

    monkeypatch.setattr(save_module.json, "dump", boom)
    error = write_slot(slot, _snapshot(data_dir, profile))
    assert error and "save-manual.json" in error
    _assert_failure_left_nothing_behind(tmp_path, slot, before)


def test_fsync_failure_keeps_the_prior_slot(data_dir, profile, tmp_path, monkeypatch):
    _, slot, before = _written_slot(data_dir, profile, tmp_path)

    def boom(fd):
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(save_module.os, "fsync", boom)
    error = write_slot(slot, _snapshot(data_dir, profile))
    assert error and "save-manual.json" in error
    _assert_failure_left_nothing_behind(tmp_path, slot, before)


def test_replace_failure_keeps_the_prior_slot(data_dir, profile, tmp_path, monkeypatch):
    _, slot, before = _written_slot(data_dir, profile, tmp_path)

    def boom(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(save_module.os, "replace", boom)
    error = write_slot(slot, _snapshot(data_dir, profile))
    assert error and "save-manual.json" in error
    _assert_failure_left_nothing_behind(tmp_path, slot, before)


# ── task 7: clean-process restoration proof ─────────────────────────────────


def test_clean_process_restores_the_identical_world(data_dir, profile, tmp_path):
    """The whole point of the atomic replacement: a fresh interpreter that
    only has the slot file and the game data rebuilds the identical world --
    the writer's mutated state, its RNG stream, and the settings block."""
    import subprocess
    import sys

    game = _game(data_dir, profile)
    game.timer = 1234
    game.action = 0x2000
    game.vars[5] = 4242
    game.cvars[10] = 701
    game.actors[0].beta = 123
    game.world_objects[3].beta = 512
    game.inventory_table[0][0] = 2
    game.inventory_count[0] = 1
    game.messages[0] = TimedMessage(5, age=3)
    game.floor_start = FloorStart(5, 4, -7800, -4010, -1000, 0)
    game.rng.seed(77)
    game.rng.randrange(100)
    payload = snapshot_game(game, SETTINGS)
    slot = slot_path(tmp_path, "manual")
    assert write_slot(slot, payload) is None

    script = f"""
import json, pathlib
from PyAitD.engine.script.save import read_slot, restore_game, snapshot_game
from PyAitD.games import load_profile
profile = load_profile("aitd1")
payload, error = read_slot(pathlib.Path({str(slot)!r}), pathlib.Path({str(data_dir)!r}), profile)
assert error is None, error
restored, settings = restore_game(pathlib.Path({str(data_dir)!r}), profile, payload)
print(json.dumps({{"world": snapshot_game(restored, settings), "draw": restored.rng.randrange(1000)}}))
"""
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    checkpoint = json.loads(out.stdout)
    assert checkpoint["world"] == payload
    # the restored RNG draws exactly what the writer's stream draws next
    assert checkpoint["draw"] == game.rng.randrange(1000)
