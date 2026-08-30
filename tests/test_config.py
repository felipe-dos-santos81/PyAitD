# SPDX-License-Identifier: GPL-2.0-only
import json

import pytest

from PyAitD.app.config import (
    SCHEMA, Control, REMAPPABLE_CONTROLS, Settings, default_settings, load_settings,
    replace_binding, save_settings, settings_path, validate_settings,
)
from PyAitD.render.render_options import RenderOptions

pytestmark = pytest.mark.shell


EXPECTED = {
    "UP": ("up", "w"), "DOWN": ("down", "s"),
    "LEFT": ("left", "a"), "RIGHT": ("right", "d"),
    "ACTION": ("space",), "INVENTORY_CONFIRM": ("return", "i"),
    "CANCEL": ("escape",), "TOGGLE_INPUT_MODE": ("tab",),
}


def valid_payload():
    return {
        "schema": 1,
        "sticky_action": False,
        "bindings": {name: list(keys) for name, keys in EXPECTED.items()},
    }


def test_defaults_and_stable_control_surface():
    settings = default_settings()
    assert [control.name for control in Control] == [
        "UP", "DOWN", "LEFT", "RIGHT", "ACTION",
        "INVENTORY_CONFIRM", "CANCEL", "TOGGLE_INPUT_MODE",
    ]
    assert settings == Settings(bindings=EXPECTED, sticky_action=False)
    assert Control.CANCEL not in REMAPPABLE_CONTROLS


def test_replace_binding_steals_and_replaces_the_complete_list():
    changed = replace_binding(default_settings(), Control.ACTION, "w")
    assert changed.bindings["ACTION"] == ("w",)
    assert changed.bindings["UP"] == ("up",)
    assert default_settings().bindings["ACTION"] == ("space",)


def test_replace_binding_rejects_cancel_and_empty_key():
    with pytest.raises(ValueError):
        replace_binding(default_settings(), Control.CANCEL, "x")
    with pytest.raises(ValueError):
        replace_binding(default_settings(), Control.ACTION, "")


def test_replace_binding_refuses_to_steal_cancels_escape():
    settings = default_settings()
    with pytest.raises(ValueError):
        replace_binding(settings, Control.ACTION, "escape")
    assert settings.bindings["CANCEL"] == ("escape",)


def test_settings_paths_are_platform_specific(tmp_path):
    assert settings_path(platform="darwin", home=tmp_path) == (
        tmp_path / "Library" / "Application Support" / "PyAitD" / "settings.json"
    )
    assert settings_path(platform="linux", home=tmp_path) == (
        tmp_path / ".config" / "pyaitd" / "settings.json"
    )


INVALID_PAYLOADS = {
    "not a mapping": [],
    "wrong schema": {**valid_payload(), "schema": 99},
    "missing top-level field": {
        "schema": 1,
        "bindings": valid_payload()["bindings"],
    },
    "extra top-level field": {**valid_payload(), "volume": 10},
    "missing control": {
        **valid_payload(),
        "bindings": {k: v for k, v in valid_payload()["bindings"].items()
                     if k != "UP"},
    },
    "extra control": {
        **valid_payload(),
        "bindings": {**valid_payload()["bindings"], "JUMP": ["j"]},
    },
    "non-list binding": {
        **valid_payload(),
        "bindings": {**valid_payload()["bindings"], "UP": "up"},
    },
    "non-string binding": {
        **valid_payload(),
        "bindings": {**valid_payload()["bindings"], "UP": ["up", 3]},
    },
    "empty string binding": {
        **valid_payload(),
        "bindings": {**valid_payload()["bindings"], "UP": ["up", ""]},
    },
    "duplicate key within control": {
        **valid_payload(),
        "bindings": {**valid_payload()["bindings"], "UP": ["up", "up"]},
    },
    "duplicate key across controls": {
        **valid_payload(),
        "bindings": {**valid_payload()["bindings"], "ACTION": ["w"]},
    },
    "non-boolean sticky_action": {**valid_payload(), "sticky_action": 1},
    "CANCEL rebound": {
        **valid_payload(),
        "bindings": {**valid_payload()["bindings"], "CANCEL": ["backspace"]},
    },
    "CANCEL with extra key": {
        **valid_payload(),
        "bindings": {**valid_payload()["bindings"],
                     "CANCEL": ["escape", "backspace"]},
    },
}


@pytest.mark.parametrize("payload", INVALID_PAYLOADS.values(),
                         ids=INVALID_PAYLOADS.keys())
def test_validate_settings_rejects_invalid_payloads(payload):
    with pytest.raises(ValueError):
        validate_settings(payload)


def test_empty_binding_list_is_valid_for_non_cancel_controls():
    payload = valid_payload()
    payload["bindings"]["ACTION"] = []
    settings, _ = validate_settings(payload)
    assert settings.bindings["ACTION"] == ()


def test_round_trip_uses_schema_two(tmp_path):
    path = tmp_path / "nested" / "settings.json"
    settings = Settings(EXPECTED, sticky_action=True)
    assert save_settings(settings, path) is None
    assert json.loads(path.read_text()) == {
        "schema": SCHEMA, "sticky_action": True,
        "bindings": {name: list(keys) for name, keys in EXPECTED.items()},
        "render": RenderOptions().to_payload(),
    }
    assert load_settings(path) == (settings, None)


@pytest.mark.parametrize("contents", ("{", '{"schema": 99}', "[]"))
def test_bad_files_fall_back_with_a_named_error(tmp_path, contents):
    path = tmp_path / "settings.json"
    path.write_text(contents)
    settings, error = load_settings(path)
    assert settings == default_settings()
    assert str(path) in error


def test_missing_file_is_a_clean_default(tmp_path):
    assert load_settings(tmp_path / "missing.json") == (default_settings(), None)


def test_replace_failure_is_reported_and_temp_is_removed(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr("PyAitD.app.config.os.replace", lambda *args: (_ for _ in ()).throw(OSError("read only")))
    error = save_settings(default_settings(), path)
    assert str(path) in error and "read only" in error
    assert list(tmp_path.glob(".settings.json.*.tmp")) == []


def test_schema_is_2_and_settings_carry_render_defaults():
    assert SCHEMA == 2
    assert default_settings().render == RenderOptions()


def test_v1_payload_loads_with_render_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(valid_payload()))
    settings, error = load_settings(path)
    assert error is None
    assert settings.render == RenderOptions()
    assert settings.bindings == EXPECTED


def test_v2_render_field_falls_back_per_field_with_notice(tmp_path):
    payload = valid_payload()
    payload["schema"] = 2
    payload["render"] = {"scale": 2, "shading": "neon", "background_filter": "nearest",
                         "override_dir": None}
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(payload))
    settings, error = load_settings(path)
    assert settings.render == RenderOptions(2, "smooth", "nearest", None)
    assert settings.bindings == EXPECTED
    assert "shading" in error


def test_save_writes_schema_2_with_render(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings(EXPECTED, False, RenderOptions(3, "flat", "xbr", None))
    assert save_settings(settings, path) is None
    payload = json.loads(path.read_text())
    assert payload["schema"] == SCHEMA
    assert payload["render"] == {"scale": 3, "shading": "flat",
                                 "background_filter": "xbr", "override_dir": None,
                                 "lighting": "scene", "msaa": 4, "realism": "enhanced",
                                 "smoothing": 2, "shadows": "soft", "integration": "on"}
    assert load_settings(path) == (settings, None)
