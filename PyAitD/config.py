# SPDX-License-Identifier: GPL-2.0-only
from dataclasses import dataclass
from enum import Enum
import json
import os
from pathlib import Path
import sys
import tempfile


SCHEMA = 1


class Control(str, Enum):
    UP = "UP"; DOWN = "DOWN"; LEFT = "LEFT"; RIGHT = "RIGHT"
    ACTION = "ACTION"; INVENTORY_CONFIRM = "INVENTORY_CONFIRM"
    CANCEL = "CANCEL"; TOGGLE_INPUT_MODE = "TOGGLE_INPUT_MODE"


REMAPPABLE_CONTROLS = tuple(control for control in Control if control is not Control.CANCEL)
_DEFAULT_BINDINGS = {
    "UP": ("up", "w"), "DOWN": ("down", "s"),
    "LEFT": ("left", "a"), "RIGHT": ("right", "d"),
    "ACTION": ("space",), "INVENTORY_CONFIRM": ("return", "i"),
    "CANCEL": ("escape",), "TOGGLE_INPUT_MODE": ("tab",),
}


@dataclass(frozen=True)
class Settings:
    bindings: dict[str, tuple[str, ...]]
    sticky_action: bool = False


def default_settings():
    return Settings(dict(_DEFAULT_BINDINGS), False)


def validate_settings(payload):
    if (not isinstance(payload, dict)
            or type(payload.get("schema")) is not int
            or payload.get("schema") != SCHEMA):
        raise ValueError("settings schema must be 1")
    if set(payload) != {"schema", "sticky_action", "bindings"}:
        raise ValueError("settings fields must be schema, sticky_action, and bindings")
    if type(payload.get("sticky_action")) is not bool:
        raise ValueError("sticky_action must be boolean")
    bindings = payload.get("bindings")
    expected = {control.name for control in Control}
    if not isinstance(bindings, dict) or set(bindings) != expected:
        raise ValueError("bindings must contain every control exactly once")
    converted = {}
    seen = set()
    for control in Control:
        names = bindings[control.name]
        if not isinstance(names, list):
            raise ValueError(f"{control.name} bindings must be a list")
        if any(not isinstance(name, str) or not name for name in names):
            raise ValueError(f"{control.name} bindings must be non-empty strings")
        if any(name in seen for name in names) or len(set(names)) != len(names):
            raise ValueError("key names must be unique across controls")
        seen.update(names)
        converted[control.name] = tuple(names)
    if converted[Control.CANCEL.name] != ("escape",):
        raise ValueError("CANCEL must remain bound only to escape")
    return Settings(converted, payload["sticky_action"])


def replace_binding(settings, control, key_name):
    if (control is Control.CANCEL or not key_name
            or key_name in settings.bindings[Control.CANCEL.name]):
        raise ValueError("CANCEL is fixed and key names must be non-empty")
    bindings = {
        name: tuple(key for key in keys if key != key_name)
        for name, keys in settings.bindings.items()
    }
    bindings[control.name] = (key_name,)
    return Settings(bindings, settings.sticky_action)


def settings_path(*, platform=None, home=None):
    platform = sys.platform if platform is None else platform
    home = Path.home() if home is None else Path(home)
    if platform == "darwin":
        return home / "Library" / "Application Support" / "PyAitD" / "settings.json"
    return home / ".config" / "pyaitd" / "settings.json"


def load_settings(path):
    path = Path(path)
    try:
        if not path.exists():
            return default_settings(), None
        return validate_settings(json.loads(path.read_text(encoding="utf-8"))), None
    except (OSError, ValueError, TypeError) as exc:
        return default_settings(), f"Could not load settings from {path}: {exc}"


def save_settings(settings, path):
    path = Path(path)
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, raw_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
        )
        temporary = Path(raw_name)
        payload = {
            "schema": SCHEMA,
            "sticky_action": settings.sticky_action,
            "bindings": {name: list(keys) for name, keys in settings.bindings.items()},
        }
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        return None
    except OSError as exc:
        return f"Could not save settings to {path}: {exc}"
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
