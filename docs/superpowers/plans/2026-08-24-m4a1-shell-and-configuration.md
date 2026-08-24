# M4a1 Shell and Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Boot the windowed single-player port into an asset-faithful, fully mouse-reachable character selector; start either protagonist with the correct FITD archives and state; and replace Escape-to-quit with a paused system menu that persists remapping and sticky-action settings.

**Architecture:** Add `ChooseCharacter` and `OpenSystemMenu` to the existing typed modal/mode path, keeping the single pygame event pump and one present per frame in `__main__.py`. Keep JSON policy and persistence in a new pygame-free `config.py`; keep pygame key translation, reducers, hit geometry, and drawing in `ui.py`; keep the PLAY input snapshot in `playworld.py`. Normal boot uses the existing floor-zero `Game` as an unticked staging owner, and hero choice replaces game and floor atomically through the current restart-shaped seam while carrying only application-session settings and their recoverable error.

**Tech Stack:** Python 3.12, pygame-ce 2.5.8, ModernGL, NumPy, pytest. Reuse pygame-ce `event`, `key`, `Rect`, `Surface`, `surfarray`, `font`, cursor, and window APIs; add no dependency.

**Spec:** `docs/superpowers/specs/2026-08-24-m4a1-shell-design.md`

## Global Constraints

- `# SPDX-License-Identifier: GPL-2.0-only` is the first line of every Python file.
- Dependencies remain fixed: pygame-ce, ModernGL, NumPy, pytest. Do not add `pygame_gui`, `pygame-menu`, or another package.
- This plan implements M4a1 only. Do not add save/load, quick-save, audio, sequences, title/demo loops, or ending closure.
- FITD source is authoritative at `/Users/felipe.dos.santos/code/theirs/FITD/FitdLib/`. The supplied `/Users/felipe.dos.santos/code/theirs/FITD/graphify-out/graph.json` AST edges directly connect `ChoosePerso` to `AffBigCadre` at `AITD1.cpp:198`, `PlayWorld` to `processSystemMenu` at `mainLoop.cpp:61`, and `processSystemMenu` to `SaveTimerAnim`/`RestoreTimerAnim` at `systemMenu.cpp:59,107`; use those edges as routing evidence and the cited source bodies for behavior.
- Keep `playworld.py`, `life_ops.py`, `interaction.py`, and `effects.py` free of pygame/render/event imports. `config.py` must also remain pygame-free.
- `ui.py` may mutate presenter/input-buffer/application-settings state, but never game, world, actor, inventory, navigation, or LIFE state.
- `__main__.py` remains the only event pump, game/floor replacement authority, settings lifecycle owner, and presentation owner.
- Preserve one event pump and exactly one `Renderer.present` per visible frame. Character selection and system menu are modes in that loop, never nested loops.
- Every shell decision except typing a replacement key is reachable with one left click. Add no right-click, double-click, drag, hold, timed gesture, or key-and-mouse chord.
- Ambiguity resolved in favor of the original mouse-accessibility goal: CONFIG ends with a `Back to Menu` navigation row. It is not `Control.CANCEL` and is not remappable; it is the smallest local way for a one-button player to leave CONFIG without weakening fixed Escape recovery.
- The spec's instruction to pass settings into input handling is implemented by passing `ModalSession.settings` once through `configure_input` at boot/remap/replacement; the compiled table lives on `InputBuffer`, so `event_to_input(event, state)` stays stable and no key names are recompiled per event.
- The approved presenter has only `PORTRAITS|STORY`, not a story-page cursor. Render the first `layout_book` page for entry 20/21 and treat its activation as Start; multi-page intro sequencing remains M4b.
- Escape is permanently `Control.CANCEL`; configuration never offers a CANCEL row.
- Modal entry, modal exit, focus loss, remapping, input-mode changes, and game replacement clear held controls, queued commands, sticky latch, and sticky pulse.
- Settings belong to `ModalSession`, never `Game`, so hero/death replacement and future save serialization stay separate.
- Real-data tests use `data_dir` and skip through the existing fixture when data is absent. Goldens below were measured from the user's current AITD1 data; do not update them to make a failing implementation pass. If the authoritative data/source disproves one, correct it with a FITD file:line comment.
- Tests touching pygame/rendering run with `SDL_VIDEODRIVER=dummy`; focused shell proof also sets `SDL_AUDIODRIVER=dummy`.
- Never mass-reformat. The pytest suite is the only code-quality gate.
- Each task must first observe its focused new test fail, then implement the smallest production hunk, then run the focused test and `.venv/bin/pytest -q`. After non-trivial production changes also run `make prove`.

## Evidence-pinned constants

| Contract | Pinned value | Evidence |
|---|---|---|
| Portrait hit rectangles | left `(10,10,140,181)`, right `(170,10,140,181)` | `AITD1.cpp:192-205` |
| Portrait cadre calls | centers `(80,100)`, `(240,100)`, size `(160,200)` | `AITD1.cpp:196-205` |
| Choice-to-hero mapping | left `1` Emily, right `0` Carnby | `AITD1.cpp:266-287` |
| Story composition | Emily copies right half + text 21; Carnby left half + text 20 | `AITD1.cpp:266-290` |
| Hero archives | hero 0 `LISTBODY`/`LISTANIM`; hero 1 `LISTBOD2`/`LISTANI2` | `main.cpp:1173-1174`, `vars.cpp:247-255` |
| Menu pause/open | Escape calls system menu; timer saved/restored | `mainLoop.cpp:53-67`, `systemMenu.cpp:53-160` |
| Cadre entry 4 sprite shapes | `(20,20)` x4, `(8,20)` x2, `(20,8)` x2, `(8,44)` x1 in `(h,w)` order | measured from `ITD_RESS.PAK` entry 4 using `aitdBox.cpp:92-178` layout |
| Carnby body 12 / anim 4 | body SHA-256 `6bc39ca43fa8660bf1a09801168d350245873bb698523df3299b0b6727fdc1cd`; anim SHA-256 `9ab655b4e211ce3f8b973344d7386b56fc8538b0390dc501ce2234994f9e682c` | measured from `LISTBODY.PAK` / `LISTANIM.PAK` |
| Emily body 12 / anim 4 | body SHA-256 `bcdb6d5f4a3bb8449100af2768fa0fe518fcbc65da5b28cecf528d48438c1c0c`; anim SHA-256 `a4605893cac129ab9c8715cf5adcec83bb1a8004e02d50096a02f982b2899e56` | measured from `LISTBOD2.PAK` / `LISTANI2.PAK` |
| Shared initial hero state | `(floor, room, actor, world, body, anim, life, life_mode, x, y, z) = (0,0,1,1,12,4,549,0,3231,0,-1548)` | measured through current `init_game`; only archive pair/CVar differ |

## File map

| File | Responsibility in M4a1 |
|---|---|
| `PyAitD/config.py` | Pygame-free controls, settings defaults/schema validation, remap stealing, platform path, atomic load/save. |
| `PyAitD/effects.py` | Add `CHARACTER_SELECT`/`SYSTEM_MENU` modes and their typed effects. |
| `PyAitD/assets.py` | Select the hero body/animation archives before parsing and cache cadre sprites from `ITD_RESS` entry 4. |
| `PyAitD/game.py` | Pass `hero` into `Assets`; leave settings out of `Game`. |
| `PyAitD/ui.py` | Shell presenters/results/reducers, pygame key adapter, input drains/sticky state, cadre/character/menu/notice renderers and hit geometry. |
| `PyAitD/playworld.py` | Expose and consume the one-tick sticky Action pulse only in keyboard PLAY. |
| `PyAitD/__main__.py` | Load settings once, stage normal boot, route shell/menu/capture/notice input, save dirty settings, and replace game/floor while preserving the application session. |
| `PyAitD/mouse_contract.py` | Declare shell/menu/notice capabilities and the keyboard-only remap-capture decision. |
| `tests/test_config.py` | Pure schema/path/remap/load/save/atomic-failure tests. |
| `tests/test_assets.py` | Both hero archives plus cadre parser real-data and malformed-entry tests. |
| `tests/test_effects.py` | New effect-to-mode mapping. |
| `tests/test_ui_reducers.py` | Character/menu/config/capture transitions and wrap behavior. |
| `tests/test_ui_input.py` | Compiled bindings, canonical names, held state, focus drain, and sticky latch/pulse. |
| `tests/test_ui_render.py` | Cadre placement, story halves/text, menu frames, and settings notice purity. |
| `tests/test_ui_mouse.py` | Exclusive-edge portrait/menu/notice hit tests. |
| `tests/test_play_loop.py`, `tests/test_runtime_modes.py` | Sticky snapshot, modal drains, shell/menu routing, raw capture, settings save, and replacement lifetime. |
| `tests/test_main.py` | Normal boot versus explicit debug-start CLI contracts. |
| `tests/test_mouse_only.py` | Mouse registry exhaustiveness for the two new modes and persistent notice. |
| `tests/test_shell_journeys.py` | Real event-pump hero/menu/remap/restart/reload/error journeys. |
| `Makefile` | Make shell boot the default and add `prove-shell`. |
| `docs/m4a1-shell-proof.md` | Automated and windowed accessibility evidence. |
| `CONTEXT.md` | Mark M4a1 landed and document settings/shell ownership. |

---

### Task 1: Pygame-free settings model and atomic store

**Files:**
- Create: `PyAitD/config.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Produces `Control`, `REMAPPABLE_CONTROLS`, `Settings`, `default_settings()`, `validate_settings(payload)`, `replace_binding(settings, control, key_name)`, `settings_path(*, platform=None, home=None)`, `load_settings(path)`, and `save_settings(settings, path)`.
- Returns recoverable error strings from load/save; never imports pygame and never raises for corrupt/missing/unwritable user configuration.

- [ ] **Step 1: Write failing defaults, schema, remap, and path tests**

Create `tests/test_config.py` with the SPDX line and these contracts:

```python
import json
import subprocess
import sys

import pytest

from PyAitD.config import (
    Control, REMAPPABLE_CONTROLS, Settings, default_settings, load_settings,
    replace_binding, save_settings, settings_path, validate_settings,
)


EXPECTED = {
    "UP": ("up", "w"), "DOWN": ("down", "s"),
    "LEFT": ("left", "a"), "RIGHT": ("right", "d"),
    "ACTION": ("space",), "INVENTORY_CONFIRM": ("return", "i"),
    "CANCEL": ("escape",), "TOGGLE_INPUT_MODE": ("tab",),
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


def test_settings_paths_are_platform_specific(tmp_path):
    assert settings_path(platform="darwin", home=tmp_path) == (
        tmp_path / "Library" / "Application Support" / "PyAitD" / "settings.json"
    )
    assert settings_path(platform="linux", home=tmp_path) == (
        tmp_path / ".config" / "pyaitd" / "settings.json"
    )


def test_config_module_does_not_import_pygame():
    probe = "import sys, PyAitD.config; raise SystemExit('pygame' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", probe]).returncode == 0
```

Add parameterized validation cases for wrong schema, missing/extra top-level fields, missing/extra controls, a non-list binding, a non-string/empty string, a duplicate key anywhere in the mapping, non-boolean `sticky_action`, and any CANCEL value other than `['escape']`. Empty lists for non-CANCEL controls are valid because stealing a sole binding intentionally leaves that control unbound.

- [ ] **Step 2: Run the pure tests and verify the missing module failure**

Run:

```bash
.venv/bin/pytest tests/test_config.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'PyAitD.config'`.

- [ ] **Step 3: Implement the stable model, structural validator, and steal rule**

Create `PyAitD/config.py` around this exact public shape:

```python
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
    if control is Control.CANCEL or not key_name:
        raise ValueError("CANCEL is fixed and key names must be non-empty")
    bindings = {
        name: tuple(key for key in keys if key != key_name)
        for name, keys in settings.bindings.items()
    }
    bindings[control.name] = (key_name,)
    return Settings(bindings, settings.sticky_action)
```

- [ ] **Step 4: Add failing round-trip, fallback, and atomic-failure tests**

Add tests that assert:

```python
def test_round_trip_uses_schema_one(tmp_path):
    path = tmp_path / "nested" / "settings.json"
    settings = Settings(EXPECTED, sticky_action=True)
    assert save_settings(settings, path) is None
    assert json.loads(path.read_text()) == {
        "schema": 1, "sticky_action": True,
        "bindings": {name: list(keys) for name, keys in EXPECTED.items()},
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
    monkeypatch.setattr("PyAitD.config.os.replace", lambda *args: (_ for _ in ()).throw(OSError("read only")))
    error = save_settings(default_settings(), path)
    assert str(path) in error and "read only" in error
    assert list(tmp_path.glob(".settings.json.*.tmp")) == []
```

- [ ] **Step 5: Implement non-throwing load and same-directory atomic save**

Append:

```python
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
```

- [ ] **Step 6: Run focused and regression gates**

```bash
.venv/bin/pytest tests/test_config.py -q
.venv/bin/pytest -q
make prove
```

Expected: all pass; the purity subprocess proves importing `config.py` does not load pygame.

- [ ] **Step 7: Commit the settings core**

```bash
git add PyAitD/config.py tests/test_config.py
git commit -m "feat: add atomic shell settings store"
```

---

### Task 2: Typed shell effects and pure presenter reducers

**Files:**
- Modify: `PyAitD/effects.py`
- Modify: `PyAitD/ui.py`
- Modify: `tests/test_effects.py`
- Modify: `tests/test_ui_reducers.py`

**Interfaces:**
- Produces `ChooseCharacter`, `OpenSystemMenu`, `CharacterPhase`, `CharacterSelectPresenter`, `CharacterSelectResult`, `SystemMenuPage`, `SystemMenuPresenter`, `SystemMenuResult`, `reduce_character_select`, `reduce_system_menu`, and `capture_system_key`.
- Consumes Task 1 `Settings`, `Control`, `REMAPPABLE_CONTROLS`, and `replace_binding`.

- [ ] **Step 1: Write failing effect/mode mapping tests**

Extend `tests/test_effects.py`:

```python
from PyAitD.effects import ChooseCharacter, OpenSystemMenu


@pytest.mark.parametrize(
    ("effect", "mode"),
    ((ChooseCharacter(), GameMode.CHARACTER_SELECT),
     (OpenSystemMenu(), GameMode.SYSTEM_MENU)),
)
def test_shell_effects_use_the_existing_modal_mode_mapping(data_dir, effect, mode):
    game = init_game(data_dir)
    game.open_modal(effect)
    assert game.mode is mode
```

Run:

```bash
.venv/bin/pytest tests/test_effects.py -q
```

Expected: import/attribute failure for the missing effects/modes.

- [ ] **Step 2: Add modes, effects, union membership, and the single mapping owner**

In `effects.py` add `CHARACTER_SELECT` and `SYSTEM_MENU` to `GameMode`, frozen empty dataclasses `ChooseCharacter` and `OpenSystemMenu`, include both in `ModalEffect`, and add them to `MODAL_MODE`. Do not special-case `Game.mode`.

- [ ] **Step 3: Write failing reducer tests for every transition**

Extend `tests/test_ui_reducers.py` with tests that assert:

```python
def test_character_selection_maps_left_to_emily_and_right_to_carnby():
    state = CharacterSelectPresenter()
    assert state == CharacterSelectPresenter(choice=0, phase=CharacterPhase.PORTRAITS)
    assert reduce_character_select(state, Command.ACCEPT) is None
    assert state.phase is CharacterPhase.STORY
    assert reduce_character_select(state, Command.OPEN_INVENTORY) == CharacterSelectResult(hero=1)
    state = CharacterSelectPresenter(choice=1)
    reduce_character_select(state, Command.ACCEPT)
    assert reduce_character_select(state, Command.ACCEPT) == CharacterSelectResult(hero=0)


def test_character_cancel_backs_out_then_quits():
    state = CharacterSelectPresenter(phase=CharacterPhase.STORY)
    assert reduce_character_select(state, Command.CANCEL) is None
    assert state.phase is CharacterPhase.PORTRAITS
    assert reduce_character_select(state, Command.CANCEL) == CharacterSelectResult(quit=True)


def test_system_main_wraps_and_opens_configuration():
    state = SystemMenuPresenter()
    reduce_system_menu(state, Command.UP, default_settings())
    assert state.cursor == 2
    reduce_system_menu(state, Command.DOWN, default_settings())
    assert state.cursor == 0
    state.cursor = 1
    assert reduce_system_menu(state, Command.OPEN_INVENTORY, default_settings()) is None
    assert (state.page, state.cursor) == (SystemMenuPage.CONFIG, 0)


def test_configuration_toggles_capture_steals_and_escape_cancels():
    state = SystemMenuPresenter(page=SystemMenuPage.CONFIG)
    outcome = reduce_system_menu(state, Command.ACCEPT, default_settings())
    assert outcome.settings.sticky_action is True
    state.cursor = 1 + REMAPPABLE_CONTROLS.index(Control.ACTION)
    assert reduce_system_menu(state, Command.ACCEPT, outcome.settings) is None
    assert state.capture == "ACTION"
    changed = capture_system_key(state, outcome.settings, "w")
    assert changed.settings.bindings["ACTION"] == ("w",)
    assert changed.settings.bindings["UP"] == ("up",)
    state.capture = "ACTION"
    assert capture_system_key(state, changed.settings, "escape") is None
    assert state.capture is None
```

Also pin all main results: row 0 and main-page CANCEL return `SystemMenuResult(close=True, save=True)`; row 2 returns `SystemMenuResult(quit=True, save=True)`; CONFIG CANCEL and its final Back row return to MAIN with `save=True`; configuration cursor wraps across exactly `2 + len(REMAPPABLE_CONTROLS)` rows.

- [ ] **Step 4: Run reducers and verify missing interfaces**

```bash
.venv/bin/pytest tests/test_ui_reducers.py -q
```

Expected: collection fails on the new presenter/reducer imports.

- [ ] **Step 5: Implement the presenter/result types and reducers**

Add to `ui.py`:

```python
from PyAitD.config import (
    Control, REMAPPABLE_CONTROLS, Settings, default_settings, replace_binding,
)


class CharacterPhase(Enum):
    PORTRAITS = auto()
    STORY = auto()


@dataclass
class CharacterSelectPresenter:
    choice: int = 0
    phase: CharacterPhase = CharacterPhase.PORTRAITS


@dataclass(frozen=True)
class CharacterSelectResult:
    hero: int | None = None
    quit: bool = False


class SystemMenuPage(Enum):
    MAIN = auto()
    CONFIG = auto()


@dataclass
class SystemMenuPresenter:
    page: SystemMenuPage = SystemMenuPage.MAIN
    cursor: int = 0
    capture: str | None = None


@dataclass(frozen=True)
class SystemMenuResult:
    settings: Settings | None = None
    close: bool = False
    quit: bool = False
    save: bool = False


def reduce_character_select(state, command):
    command = Command.ACCEPT if command is Command.OPEN_INVENTORY else command
    if command is Command.CANCEL:
        if state.phase is CharacterPhase.STORY:
            state.phase = CharacterPhase.PORTRAITS
            return None
        return CharacterSelectResult(quit=True)
    if state.phase is CharacterPhase.PORTRAITS:
        if command in (Command.LEFT, Command.UP):
            state.choice = 0
        elif command in (Command.RIGHT, Command.DOWN):
            state.choice = 1
        elif command is Command.ACCEPT:
            state.phase = CharacterPhase.STORY
        return None
    if command is Command.ACCEPT:
        return CharacterSelectResult(hero=1 if state.choice == 0 else 0)
    return None


def reduce_system_menu(state, command, settings):
    if state.capture is not None:
        return None
    command = Command.ACCEPT if command is Command.OPEN_INVENTORY else command
    row_count = 3 if state.page is SystemMenuPage.MAIN else 2 + len(REMAPPABLE_CONTROLS)
    if command is Command.UP:
        state.cursor = (state.cursor - 1) % row_count
    elif command is Command.DOWN:
        state.cursor = (state.cursor + 1) % row_count
    elif command is Command.CANCEL:
        if state.page is SystemMenuPage.CONFIG:
            state.page = SystemMenuPage.MAIN
            state.cursor = 0
            return SystemMenuResult(save=True)
        return SystemMenuResult(close=True, save=True)
    elif command is Command.ACCEPT and state.page is SystemMenuPage.MAIN:
        if state.cursor == 0:
            return SystemMenuResult(close=True, save=True)
        if state.cursor == 1:
            state.page = SystemMenuPage.CONFIG
            state.cursor = 0
        else:
            return SystemMenuResult(quit=True, save=True)
    elif (command is Command.ACCEPT and state.page is SystemMenuPage.CONFIG
          and state.cursor == row_count - 1):
        state.page = SystemMenuPage.MAIN
        state.cursor = 0
        return SystemMenuResult(save=True)
    elif command is Command.ACCEPT and state.cursor == 0:
        return SystemMenuResult(
            settings=Settings(dict(settings.bindings), not settings.sticky_action),
        )
    elif command is Command.ACCEPT:
        state.capture = REMAPPABLE_CONTROLS[state.cursor - 1].name
    return None


def capture_system_key(state, settings, key_name):
    if state.capture is None:
        return None
    if key_name == "escape":
        state.capture = None
        return None
    control = Control[state.capture]
    state.capture = None
    return SystemMenuResult(settings=replace_binding(settings, control, key_name))
```

Extend `ModalSession` with `character`, `system_menu`, `settings`, `settings_path`, `settings_error`, `settings_dirty`, and `pending_hero`. `reset_for` must reset only the presenter owned by a newly observed effect; it must never overwrite those application-session settings fields.

Use these fields after the existing modal presenters:

```python
character: CharacterSelectPresenter = field(default_factory=CharacterSelectPresenter)
system_menu: SystemMenuPresenter = field(default_factory=SystemMenuPresenter)
settings: Settings = field(default_factory=default_settings)
settings_path: Path | None = None
settings_error: str | None = None
settings_dirty: bool = False
pending_hero: int | None = None
```

Import `Path` from `pathlib`. In `reset_for`, assign a fresh `CharacterSelectPresenter` only for a new `ChooseCharacter` instance and a fresh `SystemMenuPresenter` only for a new `OpenSystemMenu` instance, alongside the existing effect-specific resets.

- [ ] **Step 6: Run focused and regression gates**

```bash
.venv/bin/pytest tests/test_effects.py tests/test_ui_reducers.py tests/test_modal_results.py -q
.venv/bin/pytest -q
make prove
```

Expected: all pass; existing modal presenter identity/reset behavior remains green.

- [ ] **Step 7: Commit typed shell state**

```bash
git add PyAitD/effects.py PyAitD/ui.py tests/test_effects.py tests/test_ui_reducers.py tests/test_modal_results.py
git commit -m "feat: add shell modes and reducers"
```

---

### Task 3: Hero-specific body and animation archives

**Files:**
- Modify: `PyAitD/assets.py`
- Modify: `PyAitD/game.py`
- Modify: `tests/test_assets.py`
- Modify: `tests/test_game.py`

**Interfaces:**
- Changes `Assets(data_dir, hero: int = 0)` to publish `body_archive_name` and `anim_archive_name` and select the archive pair before any parse/cache lookup.
- Changes `Game.__init__(data_dir, hero=0)` to construct `Assets(data_dir, hero=hero)`; `init_game(data_dir, hero=0)` remains the public game initializer.

- [ ] **Step 1: Add failing archive and initial-state goldens**

Add to `tests/test_assets.py`:

```python
from hashlib import sha256
from PyAitD.floor import load_entry


@pytest.mark.parametrize(
    ("hero", "body_name", "anim_name", "body_hash", "anim_hash", "vertices", "groups"),
    (
        (0, "LISTBODY", "LISTANIM",
         "6bc39ca43fa8660bf1a09801168d350245873bb698523df3299b0b6727fdc1cd",
         "9ab655b4e211ce3f8b973344d7386b56fc8538b0390dc501ce2234994f9e682c",
         150, 20),
        (1, "LISTBOD2", "LISTANI2",
         "bcdb6d5f4a3bb8449100af2768fa0fe518fcbc65da5b28cecf528d48438c1c0c",
         "a4605893cac129ab9c8715cf5adcec83bb1a8004e02d50096a02f982b2899e56",
         164, 18),
    ),
)
def test_hero_archives_and_representative_content(
    data_dir, hero, body_name, anim_name, body_hash, anim_hash, vertices, groups,
):
    assets = Assets(data_dir, hero=hero)
    assert (assets.body_archive_name, assets.anim_archive_name) == (body_name, anim_name)
    assert (assets.num_bodies, assets.num_anims) == (272, 305)
    assert len(assets.body(12).vertices) == vertices
    assert assets.anim(4).num_groups == groups
    assert sha256(load_entry(assets._bodies_pak, 12)).hexdigest() == body_hash
    assert sha256(load_entry(assets._anims_pak, 4)).hexdigest() == anim_hash
```

Add a parameterized `tests/test_game.py` assertion for both heroes:

```python
@pytest.mark.parametrize("hero", (0, 1))
def test_both_heroes_share_fitd_initial_state_except_cvar_and_archives(data_dir, hero):
    game = init_game(data_dir, hero=hero)
    actor = game.actors[game.current_camera_target_actor]
    assert game.cvars[8] == hero
    assert (
        game.current_floor, game.current_room, game.current_camera_target_actor,
        actor.index_in_world, actor.body_num, actor.anim, actor.life, actor.life_mode,
        actor.room_x, actor.room_y, actor.room_z,
    ) == (0, 0, 1, 1, 12, 4, 549, 0, 3231, 0, -1548)
    assert game.inventory_count == [0, 0]
    assert game.in_hand_table == [-1, -1]
```

- [ ] **Step 2: Run and observe Emily use the wrong archive**

```bash
.venv/bin/pytest tests/test_assets.py::test_hero_archives_and_representative_content tests/test_game.py::test_both_heroes_share_fitd_initial_state_except_cvar_and_archives -q
```

Expected: `Assets` rejects `hero` or Emily reports `LISTBODY`/`LISTANIM` and Carnby content.

- [ ] **Step 3: Select archives at construction with no downstream rewrite**

In `assets.py`:

```python
BODY_ARCHIVES = ("LISTBODY", "LISTBOD2")
ANIM_ARCHIVES = ("LISTANIM", "LISTANI2")


class Assets:
    def __init__(self, data_dir, hero=0):
        if hero not in (0, 1):
            raise ValueError(f"hero must be 0 or 1, got {hero}")
        self.body_archive_name = BODY_ARCHIVES[hero]
        self.anim_archive_name = ANIM_ARCHIVES[hero]
        self._bodies_pak = str(find_pak(data_dir, self.body_archive_name))
        self._anims_pak = str(find_pak(data_dir, self.anim_archive_name))
```

Keep the current life, track, text, resource, palette, and cache initialization immediately after these changed lines. In `Game.__init__`, change only `self.assets = Assets(data_dir)` to `self.assets = Assets(data_dir, hero=hero)`. Do not branch actor spawning, inventory, vars, LIFE, or floor state by hero.

- [ ] **Step 4: Run focused and regression gates**

```bash
.venv/bin/pytest tests/test_assets.py tests/test_game.py -q
.venv/bin/pytest -q
make prove
```

Expected: both archive/content goldens pass; all existing default-hero calls retain Carnby behavior.

- [ ] **Step 5: Commit the narrow archive selection**

```bash
git add PyAitD/assets.py PyAitD/game.py tests/test_assets.py tests/test_game.py
git commit -m "feat: load protagonist-specific archives"
```

---

### Task 4: Bounds-checked cadre sprite bank

**Files:**
- Modify: `PyAitD/assets.py`
- Modify: `tests/test_assets.py`

**Interfaces:**
- Produces `Assets.cadre_bank() -> tuple[np.ndarray, ...]` containing nine cached RGB arrays in `(height, width, 3)` order.
- Uses the `ITD_RESS` entry 4 little-endian offset table, skips each four-byte sprite prefix, validates width/height/pixel bounds, and converts indices through `self._game_palette`.

- [ ] **Step 1: Add failing real-data shape and digest tests**

Add:

```python
@pytest.mark.parametrize(
    ("index", "shape", "digest"),
    (
        (0, (20, 20, 3), "cbb42c0d68cd9be12cb0b35885c27e93b5aa6df599a9864688d92c721fe5bc45"),
        (1, (20, 20, 3), "1dfb52dee2a7edff7a3245a685226a64de764ae2f5ef187a0a13163f23f1f59c"),
        (2, (20, 20, 3), "117532107f0fc661324cb25f3f6b65debbc134a3fd1577fd80a2c30c6e47aa77"),
        (3, (20, 20, 3), "1685163a31472bb8552df364e0a81e018f4b8ad32b48f9089a2b25a8c3b7fe50"),
        (4, (8, 20, 3), "130aafa9f4583e25a0718590f2978c171fcb03f4762f4bbf7afb87d1e6feb99c"),
        (5, (8, 20, 3), "756891ee5f09119cd5ed2e401a39acef10d9f9b98cbde882af20170d0a8409f0"),
        (6, (20, 8, 3), "a78732fcdebb80bbd1407ce1923e23b89edbaec030e2d48b1f6796eef16d86fb"),
        (7, (20, 8, 3), "cf23f9480178db0042889850345b65f4f585de67244b3b9758a2197ebe707b3c"),
        (8, (8, 44, 3), "aacf9f1337451f8eb9a613726718a2f2e5121617ef4fddfd1b904de8206109fa"),
    ),
)
def test_cadre_bank_real_data(data_dir, index, shape, digest):
    sprite = Assets(data_dir).cadre_bank()[index]
    assert sprite.shape == shape
    assert sha256(sprite.tobytes()).hexdigest() == digest
```

Add a synthetic malformed-entry test by monkeypatching `PyAitD.assets.load_entry` for resource entry 4 and asserting `ValueError` names `ITD_RESS.PAK`, `entry 4`, and the failing sprite index for a short offset table, out-of-range offset, truncated dimensions, and truncated pixel block.

- [ ] **Step 2: Run and verify the missing method failure**

```bash
.venv/bin/pytest tests/test_assets.py -q
```

Expected: `AttributeError: 'Assets' object has no attribute 'cadre_bank'`.

- [ ] **Step 3: Implement one cached, bounds-checked parser**

Add `import numpy as np`, initialize `self._cadre_sprites = None`, clear it in `clear`, and implement:

```python
def cadre_bank(self):
    if self._cadre_sprites is not None:
        return self._cadre_sprites
    raw = load_entry(self._resource_pak, 4)
    if len(raw) < 18:
        raise ValueError("ITD_RESS.PAK: entry 4 has a short cadre offset table")
    sprites = []
    for index in range(9):
        offset = int.from_bytes(raw[index * 2:index * 2 + 2], "little")
        dimensions = offset + 4
        if dimensions + 4 > len(raw):
            raise ValueError(f"ITD_RESS.PAK: entry 4 sprite {index} dimensions out of range")
        width = int.from_bytes(raw[dimensions:dimensions + 2], "little")
        height = int.from_bytes(raw[dimensions + 2:dimensions + 4], "little")
        end = dimensions + 4 + width * height
        if width == 0 or height == 0 or end > len(raw):
            raise ValueError(f"ITD_RESS.PAK: entry 4 sprite {index} pixels out of range")
        indexed = np.frombuffer(raw[dimensions + 4:end], dtype=np.uint8).reshape(height, width)
        sprites.append(np.ascontiguousarray(self._game_palette[indexed]))
    self._cadre_sprites = tuple(sprites)
    return self._cadre_sprites
```

- [ ] **Step 4: Run focused and regression gates**

```bash
.venv/bin/pytest tests/test_assets.py -q
.venv/bin/pytest -q
make prove
```

Expected: the nine measured shapes/digests and every malformed range test pass.

- [ ] **Step 5: Commit the cadre parser**

```bash
git add PyAitD/assets.py tests/test_assets.py
git commit -m "feat: parse FITD cadre sprite bank"
```

---

### Task 5: Asset-faithful shell rendering and honest hit geometry

**Files:**
- Modify: `PyAitD/ui.py`
- Modify: `tests/test_ui_render.py`
- Modify: `tests/test_ui_mouse.py`

**Interfaces:**
- Produces `CharacterLayout`, `SystemMenuLayout`, `draw_big_cadre`, `render_character_select`, `render_system_menu`, `hit_test_character`, and `hit_test_system_menu`.
- Consumes Task 4 `Assets.cadre_bank()`, existing `resource_screen`, `book_tokens`, `layout_book`, `_font`, `_to_surface`, `_to_frame`, and pygame `Rect`/`Surface`/`blit` APIs.

- [ ] **Step 1: Write failing exclusive-edge and minimum-target tests**

Extend `tests/test_ui_mouse.py`:

```python
from PyAitD.ui import (
    CharacterLayout, CharacterPhase, CharacterSelectPresenter,
    SystemMenuLayout, SystemMenuPage, SystemMenuPresenter,
    hit_test_character, hit_test_system_menu,
)


def test_character_portraits_match_fitd_and_have_exclusive_edges():
    assert CharacterLayout.PORTRAITS == (
        pygame.Rect(10, 10, 140, 181), pygame.Rect(170, 10, 140, 181),
    )
    for choice, rect in enumerate(CharacterLayout.PORTRAITS):
        assert hit_test_character(rect.topleft, CharacterSelectPresenter()) == choice
        assert hit_test_character((rect.right - 1, rect.bottom - 1), CharacterSelectPresenter()) == choice
        assert hit_test_character((rect.right, rect.bottom - 1), CharacterSelectPresenter()) is None


def test_story_whole_frame_confirms_and_menu_rows_are_large():
    story = CharacterSelectPresenter(phase=CharacterPhase.STORY)
    assert hit_test_character((0, 0), story) == 0
    assert hit_test_character((319, 199), story) == 0
    for page in SystemMenuPage:
        presenter = SystemMenuPresenter(page=page)
        rows = SystemMenuLayout.rows(page)
        assert all(rect.width >= 224 and rect.height >= 20 for rect in rows)
        for index, rect in enumerate(rows):
            assert hit_test_system_menu(rect.center, presenter) == index
```

Use `0` as the STORY hit sentinel only inside `hit_test_character`; the caller checks the phase and treats any non-`None` value as confirm. Portrait choice remains 0/1.

- [ ] **Step 2: Run hit tests and observe missing layouts**

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_mouse.py -q
```

Expected: collection fails on missing shell layout/hit interfaces.

- [ ] **Step 3: Implement pinned layouts and pure hit tests**

Add:

```python
class CharacterLayout:
    PORTRAITS = (
        pygame.Rect(10, 10, 140, 181),
        pygame.Rect(170, 10, 140, 181),
    )
    STORY = pygame.Rect(0, 0, 320, 200)


class SystemMenuLayout:
    MAIN_ROWS = tuple(pygame.Rect(48, 45 + i * 42, 224, 32) for i in range(3))
    CONFIG_ROWS = tuple(
        pygame.Rect(16, 8 + i * 20, 288, 20)
        for i in range(2 + len(REMAPPABLE_CONTROLS))
    )

    @classmethod
    def rows(cls, page):
        return cls.MAIN_ROWS if page is SystemMenuPage.MAIN else cls.CONFIG_ROWS


def hit_test_character(pos, presenter):
    if presenter.phase is CharacterPhase.STORY:
        return 0 if CharacterLayout.STORY.collidepoint(pos) else None
    for choice, rect in enumerate(CharacterLayout.PORTRAITS):
        if rect.collidepoint(pos):
            return choice
    return None


def hit_test_system_menu(pos, presenter):
    for index, rect in enumerate(SystemMenuLayout.rows(presenter.page)):
        if rect.collidepoint(pos):
            return index
    return None
```

- [ ] **Step 4: Write failing cadre, portrait, story, and system-frame tests**

Extend `tests/test_ui_render.py`:

Add `import pytest`, `from PyAitD.assets import Assets`, `from PyAitD.config import default_settings`, and the new shell presenter/layout/renderer imports before adding:

```python
def test_character_portraits_restore_art_inside_fitd_cadre(data_dir):
    assets = Assets(data_dir)
    base = assets.resource_screen(10)
    frame = render_character_select(CharacterSelectPresenter(choice=0), assets)
    left = CharacterLayout.PORTRAITS[0]
    assert np.array_equal(frame[left.top:left.bottom, left.left:left.right],
                          base[left.top:left.bottom, left.left:left.right])
    assert not np.array_equal(frame, base)


@pytest.mark.parametrize(
    ("choice", "hero", "copied"),
    ((0, 1, pygame.Rect(160, 0, 160, 200)),
     (1, 0, pygame.Rect(0, 0, 160, 200))),
)
def test_story_composes_the_opposite_intro_half_and_expected_text(
    data_dir, choice, hero, copied,
):
    assets = Assets(data_dir)
    presenter = CharacterSelectPresenter(choice=choice, phase=CharacterPhase.STORY)
    frame = render_character_select(presenter, assets)
    intro = assets.resource_screen(14)
    # Compare a margin outside the text column; the copied half remains exact.
    margin = pygame.Rect(copied.left, 0, 4, 200)
    assert np.array_equal(
        frame[margin.top:margin.bottom, margin.left:margin.right],
        intro[margin.top:margin.bottom, margin.left:margin.right],
    )
    assert int(frame.sum()) > 0
    assert (1 if choice == 0 else 0) == hero


@pytest.mark.parametrize("page", tuple(SystemMenuPage))
def test_system_menu_is_a_logical_rgb_frame(data_dir, page):
    frame = render_system_menu(
        SystemMenuPresenter(page=page), default_settings(), Assets(data_dir),
    )
    assert frame.shape == (200, 320, 3)
    assert frame.dtype == np.uint8
```

Also add a direct `draw_big_cadre` placement test with a 320x200 black `Surface`: assert the returned interior is `pygame.Rect(8, 8, 304, 184)` for `(160,100,320,200)`, that the outer frame is non-black, and that the interior stays black. This pins `aitdBox.cpp:107-176` without comparing platform font pixels.

- [ ] **Step 5: Run render tests and verify missing renderer failures**

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_render.py tests/test_ui_mouse.py -q
```

Expected: the new render imports fail.

- [ ] **Step 6: Port `AffBigCadre` with pygame surfaces and no new library**

Add a local RGB-array-to-surface helper and implement the same placement sequence as FITD:

```python
def draw_big_cadre(surface, sprites, center, size):
    x, y = center
    width, height = size
    left, top = x - width // 2, y - height // 2
    right, bottom = x + width // 2, y + height // 2
    sprite = tuple(_to_surface(image) for image in sprites)
    current_x, current_y = left, top
    surface.blit(sprite[0], (current_x, current_y))
    while True:
        current_x += 20
        if right - 20 <= current_x:
            break
        surface.blit(sprite[4], (current_x, current_y))
    surface.blit(sprite[1], (current_x, current_y))
    current_x = left
    while True:
        current_y += 20
        if bottom - 20 <= current_y:
            break
        surface.blit(sprite[6], (current_x, current_y))
    current_x, current_y = right - 8, top + 20
    while bottom - 20 > current_y:
        surface.blit(sprite[7], (current_x, current_y))
        current_y += 20
    current_x = left
    surface.blit(sprite[2], (current_x, current_y))
    while True:
        current_x += 20
        if right - 20 <= current_x:
            break
        surface.blit(sprite[5], (current_x, current_y + 12))
    surface.blit(sprite[3], (current_x, current_y))
    surface.blit(sprite[8], (x - 20, current_y + 12))
    interior = pygame.Rect(left + 8, top + 8, width - 16, height - 16)
    surface.fill((0, 0, 0), interior)
    return interior
```

Pygame clips the full-screen cadre at the surface edge, matching FITD's 320x200 clip. Do not introduce manual pixel loops.

- [ ] **Step 7: Render portraits/story and menu/config with existing helpers**

Implement:

```python
def render_character_select(presenter, assets):
    base = assets.resource_screen(10)
    surface = _to_surface(base.copy())
    center = ((80, 100), (240, 100))[presenter.choice]
    draw_big_cadre(surface, assets.cadre_bank(), center, (160, 200))
    portrait = CharacterLayout.PORTRAITS[presenter.choice]
    surface.blit(_to_surface(base[portrait.top:portrait.bottom,
                                  portrait.left:portrait.right]), portrait.topleft)
    if presenter.phase is CharacterPhase.PORTRAITS:
        return _to_frame(surface)
    intro = _to_surface(assets.resource_screen(14))
    if presenter.choice == 0:
        surface.blit(intro, (160, 0), pygame.Rect(160, 0, 160, 200))
        entry, text_x = 21, 165
    else:
        surface.blit(intro, (0, 0), pygame.Rect(0, 0, 160, 200))
        entry, text_x = 20, 5
    font = _font(15)
    page = layout_book(assets.book_tokens(entry), font, 150, 12)[0]
    y = 5
    for text, centered in page:
        glyph = font.render(text, True, (43, 31, 22))
        x = text_x + (150 - glyph.get_width()) // 2 if centered else text_x
        surface.blit(glyph, (x, y))
        y += 15
    return _to_frame(surface)
```

`render_system_menu` starts with a black 320x200 surface, calls `draw_big_cadre(surface, assets.cadre_bank(), (160,100), (320,200))`, and uses the existing `_button` helper over the exact hit rectangles. MAIN labels are `Return to Game`, `Configuration`, `Quit`. CONFIG labels are `Sticky Action: On|Off`, each remappable control with its joined key names, then `Back to Menu`; the captured row reads `CONTROL: press a key...`. Rendering reads settings and presenters only.

- [ ] **Step 8: Run focused and regression gates**

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_render.py tests/test_ui_mouse.py -q
.venv/bin/pytest -q
make prove
```

Expected: all render/hit tests pass; existing inventory/reading/HUD pixels remain green.

- [ ] **Step 9: Commit shell presentation**

```bash
git add PyAitD/ui.py tests/test_ui_render.py tests/test_ui_mouse.py
git commit -m "feat: render FITD shell screens"
```

---

### Task 6: Compiled control bindings and one-tick sticky action

**Files:**
- Modify: `PyAitD/ui.py`
- Modify: `PyAitD/playworld.py`
- Modify: `tests/test_ui_input.py`
- Modify: `tests/test_play_loop.py`

**Interfaces:**
- Produces `canonical_key_name(key)`, `compile_bindings(settings)`, `configure_input(state, settings)`, and `reset_input(state)`.
- Extends `InputBuffer` with `bindings`, `sticky_action`, `sticky_armed`, and `action_pulse`; leaves `event_to_input(event, state)` as the two-argument outer-loop interface.
- Changes `apply_play_input` to expose and consume `action_pulse` for one keyboard PLAY tick.

- [ ] **Step 1: Write failing key-adapter and remapped-input tests**

Extend `tests/test_ui_input.py`:

```python
import pytest

from PyAitD.config import (
    Control, Settings, default_settings, replace_binding,
)
from PyAitD.ui import (
    canonical_key_name, compile_bindings, configure_input, reset_input,
)


def test_pygame_key_names_round_trip_through_compat_adapter():
    assert canonical_key_name(pygame.K_RETURN) == "return"
    assert pygame.key.key_code(canonical_key_name(pygame.K_w)) == pygame.K_w


def test_unknown_persisted_key_name_is_rejected():
    settings = default_settings()
    bindings = dict(settings.bindings)
    bindings["ACTION"] = ("definitely-not-a-pygame-key",)
    with pytest.raises(ValueError, match="definitely-not-a-pygame-key"):
        compile_bindings(Settings(bindings, False))


def test_remapped_table_drives_commands_and_held_bits():
    settings = default_settings()
    settings = replace_binding(settings, Control.UP, "q")
    state = InputBuffer()
    configure_input(state, settings)
    event_to_input(key(pygame.KEYDOWN, pygame.K_q), state)
    assert (state.held_joyd, list(state.commands)) == (1, [Command.UP])
    event_to_input(key(pygame.KEYUP, pygame.K_q), state)
    assert state.held_joyd == 0
    event_to_input(key(pygame.KEYDOWN, pygame.K_w), state)
    assert state.held_joyd == 0
```

- [ ] **Step 2: Run and observe missing adapters**

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_input.py -q
```

Expected: import failures for the adapter/configuration functions.

- [ ] **Step 3: Compile names once and translate through `Control`**

Replace pygame-key constants as policy with control mappings:

```python
_DIRECTION_CONTROL = {
    Control.UP: (Command.UP, 1), Control.DOWN: (Command.DOWN, 2),
    Control.LEFT: (Command.LEFT, 4), Control.RIGHT: (Command.RIGHT, 8),
}

_DEFAULT_CONTROL_BY_KEY = {
    pygame.K_UP: Control.UP, pygame.K_w: Control.UP,
    pygame.K_DOWN: Control.DOWN, pygame.K_s: Control.DOWN,
    pygame.K_LEFT: Control.LEFT, pygame.K_a: Control.LEFT,
    pygame.K_RIGHT: Control.RIGHT, pygame.K_d: Control.RIGHT,
    pygame.K_SPACE: Control.ACTION,
    pygame.K_RETURN: Control.INVENTORY_CONFIRM,
    pygame.K_i: Control.INVENTORY_CONFIRM,
    pygame.K_ESCAPE: Control.CANCEL,
    pygame.K_TAB: Control.TOGGLE_INPUT_MODE,
}


def canonical_key_name(key):
    name = pygame.key.name(key, use_compat=True)
    if not name or name == "unknown key":
        raise ValueError(f"pygame key {key} has no stable name")
    return name


def compile_bindings(settings):
    compiled = {}
    for control in Control:
        for name in settings.bindings[control.name]:
            try:
                code = pygame.key.key_code(name)
            except ValueError as exc:
                raise ValueError(f"unknown pygame key name {name!r}") from exc
            compiled[code] = control
    return compiled


@dataclass
class InputBuffer:
    held_joyd: int = 0
    action_held: bool = False
    focused: bool = True
    commands: deque = field(default_factory=deque)
    bindings: dict | None = None
    sticky_action: bool = False
    sticky_armed: bool = False
    action_pulse: bool = False


def reset_input(state):
    state.held_joyd = 0
    state.action_held = False
    state.sticky_armed = False
    state.action_pulse = False
    state.commands.clear()


def configure_input(state, settings):
    state.bindings = compile_bindings(settings)
    state.sticky_action = settings.sticky_action
    reset_input(state)
```

Refactor `event_to_input` to look up `control = table.get(event.key)` for KEYDOWN/KEYUP. Direction controls set/clear the corresponding bit. ACTION preserves current held behavior when sticky is off; when sticky is on, a non-repeat KEYDOWN sets `sticky_armed=True` and does not set `action_held`. Every non-repeat ACTION still queues `Command.ACCEPT`, so menus remain activatable. INVENTORY_CONFIRM queues `OPEN_INVENTORY`, CANCEL queues `CANCEL`, and TOGGLE_INPUT_MODE queues `TOGGLE_INPUT_MODE`. A non-repeat direction KEYDOWN with an armed sticky latch sets `action_pulse=True` and clears the latch. Focus loss calls `reset_input` before setting `focused=False`.

Use `table = _DEFAULT_CONTROL_BY_KEY if state.bindings is None else state.bindings` before lookup. `None` preserves existing direct-test/default behavior without calling `pygame.key.key_code` before pygame initialization; an intentionally compiled empty table remains empty and does not silently restore defaults. `run` always installs the compiled settings table after `Renderer()` initializes pygame.

- [ ] **Step 4: Add failing sticky timing/reset tests**

Add:

```python
def test_sticky_action_arms_then_pulses_on_the_next_direction_only_once():
    settings = Settings(default_settings().bindings, sticky_action=True)
    state = InputBuffer()
    configure_input(state, settings)
    event_to_input(key(pygame.KEYDOWN, pygame.K_SPACE), state)
    assert (state.sticky_armed, state.action_held, state.action_pulse) == (True, False, False)
    event_to_input(key(pygame.KEYDOWN, pygame.K_UP), state)
    assert (state.sticky_armed, state.action_pulse) == (False, True)


def test_repeat_focus_loss_and_reconfiguration_cannot_leave_sticky_state():
    state = InputBuffer(sticky_armed=True, action_pulse=True, held_joyd=1, action_held=True)
    event_to_input(pygame.event.Event(pygame.WINDOWFOCUSLOST), state)
    assert (state.held_joyd, state.action_held, state.sticky_armed, state.action_pulse) == (0, False, False, False)
    configure_input(state, default_settings())
    assert not state.sticky_action
```

Extend `tests/test_play_loop.py`:

```python
def test_sticky_action_pulse_is_visible_for_exactly_one_keyboard_tick(data_dir):
    from PyAitD.effects import InputMode
    from PyAitD.playworld import apply_play_input
    game = init_game(data_dir)
    game.input_mode = InputMode.KEYBOARD
    state = InputBuffer(action_pulse=True)
    apply_play_input(game, state)
    assert (game.local_click, game.action, state.action_pulse) == (1, 0x2000, False)
    apply_play_input(game, state)
    assert (game.local_click, game.action, state.action_pulse) == (0, 0, False)


def test_mouse_mode_ignores_and_consumes_a_stale_sticky_pulse(data_dir):
    game = init_game(data_dir)
    state = InputBuffer(action_pulse=True)
    apply_play_input(game, state)
    assert state.action_pulse is False
```

- [ ] **Step 5: Run sticky tests and observe pulse not consumed**

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_input.py tests/test_play_loop.py::test_sticky_action_pulse_is_visible_for_exactly_one_keyboard_tick tests/test_play_loop.py::test_mouse_mode_ignores_and_consumes_a_stale_sticky_pulse -q
```

Expected: new `InputBuffer` fields or pulse assertions fail.

- [ ] **Step 6: Consume the pulse at the PLAY snapshot boundary**

In `apply_play_input`, preserve `sync_player_track_mode`, then use:

```python
if game.input_mode is InputMode.MOUSE:
    input_buffer.action_pulse = False
    _apply_mouse_input(game)
    return
game.nav_decision = None
game.local_joyd = input_buffer.held_joyd if input_buffer.focused else 0
pressed = input_buffer.focused and (input_buffer.action_held or input_buffer.action_pulse)
game.local_click = 1 if pressed else 0
game.local_key = 0
input_buffer.action_pulse = False
```

The existing following line that derives `game.action` from `local_click` remains unchanged. Do not consume `commands` here.

- [ ] **Step 7: Run focused and regression gates**

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_input.py tests/test_play_loop.py tests/test_runtime_modes.py -q
.venv/bin/pytest -q
make prove
```

Expected: defaults retain all existing input behavior; remapped held keys and sticky pulses pass.

- [ ] **Step 8: Commit the binding adapter and sticky snapshot**

```bash
git add PyAitD/ui.py PyAitD/playworld.py tests/test_ui_input.py tests/test_play_loop.py
git commit -m "feat: add remappable controls and sticky action"
```

---

### Task 7: Normal boot character flow and atomic hero replacement

**Files:**
- Modify: `PyAitD/__main__.py`
- Modify: `PyAitD/ui.py`
- Modify: `tests/test_main.py`
- Modify: `tests/test_runtime_modes.py`

**Interfaces:**
- Changes `parse_args([]).floor` to `None`; an explicitly present `--floor 0` remains distinguishable from normal boot.
- Produces `load_runtime_session(path) -> ModalSession`, `configure_session_input(session, input_buffer) -> None`, `replacement_session(session) -> ModalSession`, and `_hero_branch(game, renderer, session)`.
- Changes `run(game, trace_path=None, session=None)` to accept the application session while preserving direct test callers.

- [ ] **Step 1: Write failing CLI staging/bypass tests**

Replace the old default-floor assertion in `tests/test_main.py`, add `import pytest`, import `ChooseCharacter`, and add routing tests:

```python
def test_parse_args_distinguishes_normal_boot_from_explicit_floor_zero():
    assert parse_args([]).floor is None
    assert parse_args(["--floor", "0"]).floor == 0


def test_normal_main_opens_character_selection_before_run(monkeypatch, tmp_path):
    import PyAitD.__main__ as main
    game = SimpleNamespace(active_modal=None, open_modal=lambda effect: setattr(game, "active_modal", effect))
    seen = []
    monkeypatch.setattr(main, "init_game", lambda data: game)
    monkeypatch.setattr(main, "load_runtime_session", lambda path: SimpleNamespace())
    monkeypatch.setattr(main, "run", lambda g, trace, session=None: seen.append((g, session)) or 0)
    assert main.main(["--data", str(tmp_path)]) == 0
    assert isinstance(game.active_modal, ChooseCharacter)
    assert seen and seen[0][0] is game


@pytest.mark.parametrize("args", (["--floor", "0"], ["--combat-venue"], ["--mouse-combat-fixture"]))
def test_explicit_debug_starts_bypass_character_selection(monkeypatch, tmp_path, args):
    import PyAitD.__main__ as main
    game = SimpleNamespace(active_modal=None)
    seen = []
    monkeypatch.setattr(main, "init_game", lambda data: game)
    monkeypatch.setattr(main, "enter_combat_venue", lambda value: None)
    monkeypatch.setattr(main, "enter_mouse_combat_fixture", lambda value: None)
    monkeypatch.setattr(main, "load_runtime_session", lambda path: SimpleNamespace())
    monkeypatch.setattr(
        main, "run",
        lambda value, trace, session=None: seen.append((value, session)) or 0,
    )
    assert main.main([*args, "--data", str(tmp_path)]) == 0
    assert game.active_modal is None
    assert seen and seen[0][0] is game
```

- [ ] **Step 2: Run and observe the default-floor/boot failures**

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_main.py -q
```

Expected: default is still `0`, normal boot enters PLAY, and `run` has no session parameter.

- [ ] **Step 3: Load settings once and make shell boot explicit**

In `__main__.py` import config and UI adapters and add:

```python
def load_runtime_session(path):
    settings, error = load_settings(path)
    return ModalSession(settings=settings, settings_path=path, settings_error=error)


def configure_session_input(session, input_buffer):
    try:
        configure_input(input_buffer, session.settings)
    except ValueError as exc:
        session.settings = default_settings()
        session.settings_error = (
            f"Could not load settings from {session.settings_path}: {exc}"
        )
        configure_input(input_buffer, session.settings)


def replacement_session(session):
    return ModalSession(
        settings=session.settings,
        settings_path=session.settings_path,
        settings_error=session.settings_error,
        settings_dirty=session.settings_dirty,
    )
```

Change `--floor` default to `None`. In `main`, reject values other than `None`/`0`, create the staging game, apply fixture setup when requested, open `ChooseCharacter()` only when `args.floor is None` and neither fixture flag is set, load the runtime session once, and call `run(game, args.trace, session=session)`. Existing direct `run(game)` calls receive a default session.

Do not call `pygame.init()` or the pygame key adapter from `load_runtime_session`: it stays a JSON-only boot step even though `__main__.py` already imports pygame. In `run`, construct `Renderer()` first (the existing pygame initialization owner), then construct `InputBuffer` and call `configure_session_input`. Add a test with a structurally valid file containing an unknown pygame key: `load_runtime_session` succeeds without initializing pygame, then `configure_session_input` falls back to defaults and records a path-named notice after pygame is initialized.

- [ ] **Step 4: Write failing keyboard/mouse character routes and replacement tests**

Add to `tests/test_runtime_modes.py`:

Add imports for pygame, `Control`, `Settings`, `default_settings`, `load_settings`, `REMAPPABLE_CONTROLS`, `ChooseCharacter`, `OpenSystemMenu`, and the new shell UI interfaces used below.

```python
def test_character_routes_reach_story_back_and_pending_hero(data_dir):
    game = init_game(data_dir)
    game.open_modal(ChooseCharacter())
    session = ModalSession()
    assert route_command(game, session, Command.ACCEPT)
    assert session.character.phase is CharacterPhase.STORY
    assert route_command(game, session, Command.CANCEL)
    assert session.character.phase is CharacterPhase.PORTRAITS
    assert route_mouse(game, session, CharacterLayout.PORTRAITS[1].center)
    assert session.character.phase is CharacterPhase.STORY
    assert route_mouse(game, session, (160, 100))
    assert session.pending_hero == 0


def test_replacement_session_carries_only_application_settings(tmp_path):
    settings = Settings(default_settings().bindings, True)
    old = ModalSession(settings=settings, settings_path=tmp_path / "settings.json",
                       settings_error="named error", settings_dirty=True)
    old.character.choice = 1
    new = replacement_session(old)
    assert (new.settings, new.settings_path, new.settings_error, new.settings_dirty) == (
        settings, old.settings_path, "named error", True,
    )
    assert new.character == CharacterSelectPresenter()
    assert new.system_menu == SystemMenuPresenter()
```

Add a `_hero_branch` test that patches `init_game`, `Floor`, `_scene_frame`, and time; sets `session.pending_hero=1`; then asserts the returned game was initialized with hero 1, has the old trace, has a fresh configured `InputBuffer`, returns a carried session, and yields a floor belonging to the new game. Assert the old staging game is not ticked.

- [ ] **Step 5: Run and observe unroutable shell modal failure**

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_runtime_modes.py -q
```

Expected: `route_command`/`route_mouse` raises `unroutable modal ChooseCharacter` or the branch is missing.

- [ ] **Step 6: Route and render character selection through existing owners**

In `route_command`, before existing modal cases, reset the session for `ChooseCharacter`, call `reduce_character_select`, set `session.pending_hero` when a hero result arrives, and return `False` only for the portrait-phase quit result. In `route_mouse`, hit-test the character mode: a portrait click sets choice and phase to STORY; a story click sets `pending_hero` using left→1/right→0. In `render_active_mode`, return `render_character_select(session.character, game.assets)` for this effect.

Do not call `init_game` from `ui.py` or the reducers.

- [ ] **Step 7: Implement the atomic hero branch and preserve settings on death**

Add `_hero_branch` beside `_restart_branch`:

```python
def _hero_branch(game, renderer, session):
    if session.pending_hero is None:
        return None
    try:
        new_game = init_game(game._data_dir, hero=session.pending_hero)
        new_floor = Floor(new_game._data_dir, new_game.current_floor)
    except PakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return (None, None, None, None, 0, [], None, None, None, 2)
    new_game.trace = game.trace
    new_session = replacement_session(session)
    input_buffer = InputBuffer()
    configure_session_input(new_session, input_buffer)
    new_game.num_camera = new_game.new_num_camera
    new_game.flag_init_view = 0
    scene_frame, draw_list = _scene_frame(new_game, new_floor, renderer)
    return (
        new_game, new_floor, new_session, input_buffer, 0,
        draw_list, None, scene_frame, pygame.time.get_ticks(), 0,
    )
```

Change `_restart_branch(game, renderer)` to `_restart_branch(game, renderer, session)` and use `replacement_session(session)` plus `configure_session_input` rather than fresh default settings. In `run`, configure the initial `InputBuffer` from `session.settings` after `Renderer()` initializes pygame, check `_hero_branch` before `_restart_branch`, assign the complete tuple, and `continue` before any PLAY tick or stale present. Preserve the existing failure/cleanup behavior.

- [ ] **Step 8: Add a no-PLAY-present-before-choice loop test**

Use the existing monkeypatched run harness in `tests/test_play_loop.py`: start a real game with `ChooseCharacter`, emit an empty frame then QUIT, patch `play_tick` and `_scene_frame`, capture presented frames, and assert `play_tick` was never called and the only visible frame came from `render_character_select`, not the staged scene array.

- [ ] **Step 9: Run focused and regression gates**

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_main.py tests/test_runtime_modes.py tests/test_play_loop.py -q
.venv/bin/pytest -q
make prove
```

Expected: normal boot enters selector, every explicit debug start bypasses it, either hero replacement is atomic, and death restart retains settings/error.

- [ ] **Step 10: Commit boot and hero replacement**

```bash
git add PyAitD/__main__.py PyAitD/ui.py tests/test_main.py tests/test_runtime_modes.py tests/test_play_loop.py
git commit -m "feat: boot through character selection"
```

---

### Task 8: Paused system menu, raw capture, save policy, and transition drains

**Files:**
- Modify: `PyAitD/__main__.py`
- Modify: `tests/test_runtime_modes.py`
- Modify: `tests/test_play_loop.py`

**Interfaces:**
- Changes `route_command(game, session, command, input_buffer=None)` so Escape in PLAY opens `OpenSystemMenu` and input-mode changes can drain transient state.
- Produces `_save_session_settings(session) -> bool`, `_apply_system_result(game, session, input_buffer, result) -> bool`, and `_capture_keydown(event, game, session, input_buffer) -> tuple[bool, bool]` where the tuple is `(handled, running)`.
- Extends `route_mouse(game, session, logical_pos, input_buffer=None)` to activate honest menu rows.

- [ ] **Step 1: Write failing PLAY-to-menu pause and routing tests**

Add to `tests/test_runtime_modes.py`:

```python
def test_escape_in_play_opens_system_menu_instead_of_quitting(data_dir):
    game = init_game(data_dir)
    session = ModalSession()
    state = InputBuffer(held_joyd=9, action_held=True, sticky_armed=True,
                        action_pulse=True, commands=deque([Command.UP]))
    assert route_command(game, session, Command.CANCEL, state)
    assert isinstance(game.active_modal, OpenSystemMenu)
    assert game.mode is GameMode.SYSTEM_MENU


def test_system_menu_mouse_activates_configuration_and_return(data_dir):
    game = init_game(data_dir)
    game.open_modal(OpenSystemMenu())
    session = ModalSession()
    state = InputBuffer()
    assert route_mouse(
        game, session, SystemMenuLayout.MAIN_ROWS[1].center, state,
    )
    assert session.system_menu.page is SystemMenuPage.CONFIG
    assert route_mouse(
        game, session, SystemMenuLayout.CONFIG_ROWS[-1].center, state,
    )
    assert session.system_menu.page is SystemMenuPage.MAIN
    session.system_menu.page = SystemMenuPage.MAIN
    assert route_mouse(
        game, session, SystemMenuLayout.MAIN_ROWS[0].center, state,
    )
    assert game.mode is GameMode.PLAY
```

Add a run-loop test using the existing fake renderer/time/event harness: queue Escape, wait three frames, then window QUIT; patch `play_tick` to count calls and assert none occur while `game.mode is SYSTEM_MENU`. Preserve the existing fixed-step/one-present assertions.

- [ ] **Step 2: Run and observe Escape still quits/unroutable menu**

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_runtime_modes.py tests/test_play_loop.py -q
```

Expected: PLAY CANCEL still stops `run` or the new modal raises as unroutable.

- [ ] **Step 3: Open, route, click, and render the system menu**

In `route_command`, replace PLAY's CANCEL-to-app-quit behavior with:

```python
if game.mode is GameMode.PLAY and command is Command.CANCEL:
    game.open_modal(OpenSystemMenu())
    session.reset_for(game.active_modal)
    if input_buffer is not None:
        reset_input(input_buffer)
    return True
```

For `OpenSystemMenu`, call `reduce_system_menu` and apply any result through `_apply_system_result`. In `route_mouse`, hit-test the active page; if a row is hit, set `session.system_menu.cursor`, reduce with `Command.ACCEPT`, then apply the result. In `render_active_mode`, call `render_system_menu`.

Remove the special `if game.mode is PLAY and command is CANCEL: running=False` branch from `run`; all commands go through `route_command`.

- [ ] **Step 4: Write failing dirty-save success/failure tests**

Add pure runtime tests with `tmp_path`:

```python
def test_configuration_saves_once_when_leaving_and_applies_immediately(data_dir, tmp_path):
    game = init_game(data_dir)
    game.open_modal(OpenSystemMenu())
    session = ModalSession(settings_path=tmp_path / "settings.json")
    state = InputBuffer()
    session.system_menu.page = SystemMenuPage.CONFIG
    session.system_menu.cursor = 0
    assert route_command(game, session, Command.ACCEPT, state)
    assert session.settings.sticky_action is True
    assert state.sticky_action is True
    assert session.settings_dirty is True
    assert route_command(game, session, Command.CANCEL, state)
    assert session.system_menu.page is SystemMenuPage.MAIN
    assert session.settings_dirty is False
    loaded, error = load_settings(session.settings_path)
    assert error is None and loaded.sticky_action is True


def test_failed_quit_save_stays_in_menu_with_live_settings(data_dir, tmp_path, monkeypatch):
    game = init_game(data_dir)
    game.open_modal(OpenSystemMenu())
    session = ModalSession(settings_path=tmp_path / "settings.json", settings_dirty=True)
    session.settings = Settings(dict(session.settings.bindings), True)
    session.system_menu.cursor = 2
    monkeypatch.setattr("PyAitD.__main__.save_settings", lambda *args: "Could not save settings to target: read only")
    assert route_command(game, session, Command.ACCEPT, InputBuffer()) is True
    assert game.mode is GameMode.SYSTEM_MENU
    assert session.settings.sticky_action is True
    assert session.settings_dirty is True
    assert "read only" in session.settings_error
```

Also test clean Quit returns `False`, dirty successful Quit writes then returns `False`, and failed Return-to-PLAY still closes the menu but leaves the named error for the overlay. Successful saves do not clear an existing notice; every settings notice remains until explicit dismissal.

- [ ] **Step 5: Run and verify settings are not yet persisted**

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_runtime_modes.py -q
```

Expected: settings outcome is ignored or the save helpers are missing.

- [ ] **Step 6: Implement the one-save lifecycle and quit refusal**

Add:

```python
def _save_session_settings(session):
    if not session.settings_dirty:
        return True
    if session.settings_path is None:
        session.settings_dirty = False
        return True
    error = save_settings(session.settings, session.settings_path)
    if error is not None:
        session.settings_error = error
        return False
    session.settings_dirty = False
    return True


def _apply_system_result(game, session, input_buffer, result):
    if result is None:
        return True
    if result.settings is not None:
        session.settings = result.settings
        session.settings_dirty = True
        configure_input(input_buffer, session.settings)
    saved = _save_session_settings(session) if result.save else True
    if result.quit and not saved:
        return True
    if result.close:
        reset_input(input_buffer)
        game.close_modal()
    if result.quit:
        reset_input(input_buffer)
        return False
    return True
```

The CONFIG reducer already changes page before returning `save=True`, so a failed save while leaving CONFIG still reaches MAIN. A failed Return result closes to PLAY with a persistent notice. Only failed Quit stays in SYSTEM_MENU.

- [ ] **Step 7: Write failing raw-capture interception tests**

Add:

```python
def test_raw_capture_replaces_binding_without_activating_the_same_row(data_dir):
    game = init_game(data_dir)
    game.open_modal(OpenSystemMenu())
    session = ModalSession()
    session.system_menu.page = SystemMenuPage.CONFIG
    session.system_menu.cursor = 1 + REMAPPABLE_CONTROLS.index(Control.ACTION)
    session.system_menu.capture = "ACTION"
    state = InputBuffer()
    handled, running = _capture_keydown(
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_q, repeat=False),
        game, session, state,
    )
    assert (handled, running) == (True, True)
    assert session.settings.bindings["ACTION"] == ("q",)
    assert session.system_menu.capture is None
    assert list(state.commands) == []


def test_capture_escape_cancels_and_repeat_is_swallowed(data_dir):
    game = init_game(data_dir)
    game.open_modal(OpenSystemMenu())
    session = ModalSession()
    session.system_menu.capture = "ACTION"
    state = InputBuffer()
    repeat = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_q, repeat=True)
    assert _capture_keydown(repeat, game, session, state) == (True, True)
    assert session.system_menu.capture == "ACTION"
    escape = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, repeat=False)
    assert _capture_keydown(escape, game, session, state) == (True, True)
    assert session.system_menu.capture is None
    assert session.settings == default_settings()
```

- [ ] **Step 8: Run and observe capture helpers missing**

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_runtime_modes.py -q
```

Expected: `_capture_keydown` import fails.

- [ ] **Step 9: Intercept every capture KEYDOWN before `event_to_input`**

Implement:

```python
def _capture_keydown(event, game, session, input_buffer):
    from PyAitD.effects import OpenSystemMenu
    if (not isinstance(game.active_modal, OpenSystemMenu)
            or session.system_menu.capture is None
            or event.type != pygame.KEYDOWN):
        return False, True
    if bool(getattr(event, "repeat", False)):
        return True, True
    try:
        name = canonical_key_name(event.key)
        result = capture_system_key(session.system_menu, session.settings, name)
    except ValueError as exc:
        session.settings_error = f"Could not bind pygame key {event.key}: {exc}"
        return True, True
    return True, _apply_system_result(game, session, input_buffer, result)
```

At the top of each event iteration in `run`, call `_capture_keydown`; if handled, update `running` from its result and `continue`. Thus the captured event never reaches `event_to_input`, mouse routing, or menu reduction. KEYUP and window focus events retain the ordinary path.

- [ ] **Step 10: Drain every required transition at the owning branch**

Pass `input_buffer` from `run` into `route_command` and `route_mouse`. On `TOGGLE_INPUT_MODE`, call `reset_input` after cancelling navigation and syncing track mode. Character/system modal entry and exit already call it. Hero/death branches construct and configure a fresh buffer. Retain the current modal-entry `was_play` flush for modals opened by gameplay/LIFE, but replace its manual command clear with `reset_input(input_buffer)`. Add regression assertions that leaving the system menu cannot replay held movement, ACCEPT, sticky latch, or sticky pulse into the first PLAY tick.

- [ ] **Step 11: Run focused and regression gates**

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_runtime_modes.py tests/test_play_loop.py tests/test_ui_input.py -q
.venv/bin/pytest -q
make prove
```

Expected: menu ticks remain paused, changes apply immediately, each dirty boundary saves once, failed Quit remains visible, raw capture is exclusive, and all drains pass.

- [ ] **Step 12: Commit system-menu lifecycle**

```bash
git add PyAitD/__main__.py tests/test_runtime_modes.py tests/test_play_loop.py
git commit -m "feat: add persistent system configuration menu"
```

---

### Task 9: Persistent settings notice and exhaustive mouse contract

**Files:**
- Modify: `PyAitD/ui.py`
- Modify: `PyAitD/__main__.py`
- Modify: `PyAitD/mouse_contract.py`
- Modify: `tests/test_ui_render.py`
- Modify: `tests/test_ui_mouse.py`
- Modify: `tests/test_runtime_modes.py`
- Modify: `tests/test_mouse_only.py`

**Interfaces:**
- Produces `SettingsNoticeLayout.DISMISS`, `render_settings_notice(frame, message)`, `hit_test_settings_notice(pos)`, and `KEYBOARD_ONLY_DECISIONS["REMAP_CAPTURE"]`.
- Adds `SELECT_CHARACTER`, `CONFIRM_STORY_PAGE`, `MENU_ACTIVATE`, and `DISMISS_SETTINGS_ERROR` player capabilities.

- [ ] **Step 1: Write failing notice presentation/hit tests**

Add to `tests/test_ui_render.py` and `tests/test_ui_mouse.py`:

```python
def test_settings_notice_overlays_without_mutating_the_mode_frame():
    source = np.zeros((200, 320, 3), dtype=np.uint8)
    result = render_settings_notice(source, "Could not load settings from /x: corrupt")
    assert np.count_nonzero(source) == 0
    assert result.shape == source.shape
    assert not np.array_equal(result, source)


def test_settings_notice_has_one_large_exclusive_dismiss_target():
    rect = SettingsNoticeLayout.DISMISS
    assert rect.width >= 160 and rect.height >= 30
    assert hit_test_settings_notice(rect.topleft)
    assert hit_test_settings_notice((rect.right - 1, rect.bottom - 1))
    assert not hit_test_settings_notice((rect.right, rect.bottom - 1))
```

- [ ] **Step 2: Run and observe missing notice interfaces**

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_render.py tests/test_ui_mouse.py -q
```

Expected: imports fail.

- [ ] **Step 3: Add a large, mode-independent overlay**

Use existing surfaces/fonts/buttons:

```python
class SettingsNoticeLayout:
    DISMISS = pygame.Rect(72, 154, 176, 34)


def hit_test_settings_notice(pos):
    return SettingsNoticeLayout.DISMISS.collidepoint(pos)


def render_settings_notice(frame, message):
    if message is None:
        return frame
    surface = _to_surface(frame.copy())
    shade = pygame.Surface((320, 200), flags=pygame.SRCALPHA)
    shade.fill((0, 0, 0, 190))
    surface.blit(shade, (0, 0))
    title = _font(20).render("Settings error", True, (255, 220, 170))
    surface.blit(title, title.get_rect(center=(160, 38)))
    lines = layout_book((BookToken("text", message),), _font(15), 276, 5)[0]
    for index, (text, _centered) in enumerate(lines):
        glyph = _font(15).render(text, True, (255, 255, 255))
        surface.blit(glyph, glyph.get_rect(center=(160, 65 + index * 16)))
    _button(surface, SettingsNoticeLayout.DISMISS, "Dismiss", selected=True)
    return _to_frame(surface)
```

Import `BookToken` from `PyAitD.text`; do not create a second text wrapper.

- [ ] **Step 4: Write failing first-refusal tests**

Add runtime tests that start once in PLAY and once in CHARACTER_SELECT with `session.settings_error` set. Assert a left click inside Dismiss clears only the error and does not walk/select; `Command.ACCEPT` and `OPEN_INVENTORY` do the same; a direction command passes through while leaving the notice; clicking outside passes through; and `pygame.QUIT` still exits. Assert the active mode/effect is unchanged by dismissal.

- [ ] **Step 5: Run and observe notice input reaching gameplay**

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_runtime_modes.py -q
```

Expected: the click/activation is routed to the underlying mode or the error remains.

- [ ] **Step 6: Give the notice first refusal without a new mode**

In the mouse-button branch of `run`, before PLAY/modal routing:

```python
if session.settings_error is not None and hit_test_settings_notice(logical):
    session.settings_error = None
    continue
```

When popping a command, before `route_command`:

```python
if (session.settings_error is not None
        and command in (Command.ACCEPT, Command.OPEN_INVENTORY)):
    session.settings_error = None
else:
    running = route_command(game, session, command, input_buffer) and running
```

Other input proceeds normally. After `render_active_mode` and `render_play_hud`, call `render_settings_notice(composed, session.settings_error)`. Draw the notice after the HUD and before any software cursor so its target is visually topmost; shell/modal modes already use the OS cursor.

- [ ] **Step 7: Extend the mouse contract and its exhaustiveness tests**

Append these members to the existing `PlayerCapability` enum:

```python
SELECT_CHARACTER = auto()
CONFIRM_STORY_PAGE = auto()
MENU_ACTIVATE = auto()
DISMISS_SETTINGS_ERROR = auto()
```

Routes:

```python
PlayerCapability.SELECT_CHARACTER: MouseRoute(
    "left_click", "character portrait", frozenset({GameMode.CHARACTER_SELECT}),
),
PlayerCapability.CONFIRM_STORY_PAGE: MouseRoute(
    "left_click", "character story page", frozenset({GameMode.CHARACTER_SELECT}),
),
PlayerCapability.MENU_ACTIVATE: MouseRoute(
    "left_click", "system menu row", frozenset({GameMode.SYSTEM_MENU}),
),
PlayerCapability.DISMISS_SETTINGS_ERROR: MouseRoute(
    "left_click", "settings error Dismiss button", ALL_MODES,
),
```

Add these derived capabilities to `MODE_MOUSE_CAPABILITIES`; every mode gets Dismiss and Quit, CHARACTER_SELECT gets its two selection capabilities, and SYSTEM_MENU gets menu activation. Add:

```python
KEYBOARD_ONLY_DECISIONS = {
    "REMAP_CAPTURE": LegacyCommandDecision(
        None,
        "a keyboard remap must capture one physical key; menu entry, cancel, and all other configuration decisions remain mouse reachable",
    ),
}
```

Extend `tests/test_mouse_only.py` to assert the two new modes are covered by the existing derived-route equality, Dismiss is in every mode, and `KEYBOARD_ONLY_DECISIONS` is exactly `{"REMAP_CAPTURE"}` with the documented reason. Do not weaken the existing command exhaustiveness test.

- [ ] **Step 8: Run focused and regression gates**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest \
  tests/test_ui_render.py tests/test_ui_mouse.py \
  tests/test_runtime_modes.py tests/test_mouse_only.py -q
.venv/bin/pytest -q
make prove
```

Expected: corrupt-load/save errors remain visible across every mode until exactly the Dismiss activation, and all enum/mode route equalities pass.

- [ ] **Step 9: Commit notice and accessibility contract**

```bash
git add PyAitD/ui.py PyAitD/__main__.py PyAitD/mouse_contract.py tests/test_ui_render.py tests/test_ui_mouse.py tests/test_runtime_modes.py tests/test_mouse_only.py
git commit -m "feat: expose shell settings errors accessibly"
```

---

### Task 10: Real event-pump journeys, focused proof, and architecture handoff

**Files:**
- Create: `tests/test_shell_journeys.py`
- Modify: `tests/test_main.py`
- Modify: `Makefile`
- Create: `docs/m4a1-shell-proof.md`
- Modify: `CONTEXT.md`

**Interfaces:**
- Adds `make prove-shell` as the repeatable M4a1 gate.
- Changes `make run` to omit `--floor` unless the caller supplies `floor=...`.
- Records automated and windowed one-button/keyboard evidence without claiming unperformed manual proof.

- [ ] **Step 1: Build the real-loop shell harness**

Create `tests/test_shell_journeys.py` with the SPDX line, dummy-safe pygame imports, `_FRAME = np.zeros((200,320,3), dtype=np.uint8)`, `_HeadlessRenderer` matching `tests/test_mouse_only.py`, and:

```python
def _left_click(pos):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=tuple(pos))


def _key(code):
    return pygame.event.Event(pygame.KEYDOWN, key=code, repeat=False)


def _run_shell(monkeypatch, game, session, next_events, *, observe_tick=None):
    import PyAitD.__main__ as main
    pygame.init()
    renderer = _HeadlessRenderer()
    ticks = itertools.count(0, 20)
    monkeypatch.setattr(main, "Renderer", lambda: renderer)
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (_FRAME, []))
    monkeypatch.setattr(main.pygame.event, "get", next_events)
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(ticks))
    monkeypatch.setattr(main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *args: None))
    monkeypatch.setattr(main.pygame.display, "set_caption", lambda *args: None)
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda *args: None)
    if observe_tick is not None:
        monkeypatch.setattr(main, "play_tick", observe_tick)
    try:
        assert main.run(game, session=session) == 0
        assert renderer.presented > 0
    finally:
        pygame.quit()
```

Unlike the M3e harness, do not patch `render_active_mode`: these journeys must exercise the real shell render dispatch.

- [ ] **Step 2: Add both one-click hero journeys through real `run`**

Parameterize `(portrait, expected_hero)` over left/Emily and right/Carnby. Start `init_game(data_dir)` plus `ChooseCharacter`, patch `PyAitD.__main__.init_game` with a wrapper that records hero replacements while delegating to the real initializer, and return event batches in this order: click the requested portrait, click the story frame, wait until the wrapper records the replacement, then QUIT. Assert exactly one replacement, its CVar/archive names match expected hero, its inventory is empty, and no PLAY tick was observed before replacement.

- [ ] **Step 3: Add the keyboard back/start journey**

Through the same real loop: use RIGHT, ACCEPT to enter Carnby's story, CANCEL to return, LEFT, OPEN_INVENTORY to enter Emily's story, OPEN_INVENTORY to start, then QUIT after replacement. Assert the final hero is Emily and each event advances only one state. This locks both activation controls and story→portrait Escape.

- [ ] **Step 4: Add the menu/remap/sticky/save/reload journey**

Start a real floor-zero game with `session.settings_path = tmp_path / "settings.json"`. Feed: Escape; click Configuration; click Sticky Action; click the UP control row; send `Q` as the raw captured key; click `Back to Menu`; click Return; Tab into keyboard mode; Space to arm; Q to move and pulse; wait for one observed PLAY tick; then QUIT. The tick wrapper delegates to the real `play_tick` and records `(local_joyd, local_click, action)`. Assert one tuple contains `(1,1,0x2000)`, the next tick has `local_click==0`, the file contains schema 1 with UP `['q']` and sticky true, and a second `load_runtime_session(path)` plus `configure_session_input` produces the same compiled behavior for a new boot.

- [ ] **Step 5: Add negative journeys for capture replay, transition replay, and errors**

Add three bounded state-machine tests:

1. During ACTION capture, send Return; assert it becomes the binding and does not activate/toggle another row in the same frame.
2. Hold movement/Action before opening and before closing the menu; assert the first resumed PLAY tick has zero movement/action and empty sticky state.
3. Boot from corrupt JSON, dismiss the notice once by its left-click target, then install a save failure and dismiss that notice by `Command.ACCEPT`; assert the character/menu mode remains unchanged at each dismissal.

Each `next_events` callback keeps a frame counter and asserts it stays below 200, following the M3e anti-hang pattern.

- [ ] **Step 6: Add death-restart settings and clean process-reload coverage**

Use the existing `_restart_branch` unit seam to assert a dirty/live remap, sticky flag, settings path, and visible error survive death replacement while input transient state does not. Then use two independent `load_runtime_session` calls around an actual successful `save_settings` to prove process-level reload, not just object reuse.

- [ ] **Step 7: Run journeys and fix only uncovered shell seams**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_shell_journeys.py -q
```

Expected before final wiring: at least one journey fails at boot replacement, raw capture, drain, save, or reload. Implement only the smallest missing shell seam; do not broaden the gameplay loop.

- [ ] **Step 8: Make shell boot the default and add the focused gate**

Change the Makefile variable and command:

```make
floor ?=

run: install ## Run the game through character selection (use floor=0 for the attic debug bypass)
	$(PYTHON) -m PyAitD $(if $(floor),--floor "$(floor)") --data $(data) $(if $(trace),--trace $(trace))

prove-shell: install ## M4a1 proof: shell, configuration, mouse contract, and real-loop journeys
	SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy $(PYTHON) -m pytest \
		tests/test_config.py tests/test_assets.py tests/test_effects.py \
		tests/test_ui_input.py tests/test_ui_reducers.py tests/test_ui_mouse.py \
		tests/test_ui_render.py tests/test_runtime_modes.py tests/test_main.py \
		tests/test_mouse_only.py tests/test_shell_journeys.py -q
```

Add `prove-shell` to `.PHONY` and update the top target comment. Add `import subprocess` to `tests/test_main.py` and this dry-run assertion, which never opens a window:

```python
def test_make_run_uses_shell_by_default_and_floor_zero_only_when_explicit():
    plain = subprocess.run(
        ["make", "-n", "run"], capture_output=True, text=True, check=True,
    ).stdout
    explicit = subprocess.run(
        ["make", "-n", "run", "floor=0"],
        capture_output=True, text=True, check=True,
    ).stdout
    plain_run = next(line for line in plain.splitlines() if " -m PyAitD " in line)
    explicit_run = next(line for line in explicit.splitlines() if " -m PyAitD " in line)
    assert "--floor" not in plain_run
    assert '--floor "0"' in explicit_run
```

- [ ] **Step 9: Run all automated acceptance gates**

```bash
.venv/bin/pytest -q
make prove
make prove-shell
```

Expected: all pass under dummy SDL; no test hangs; existing M1-M3e proof behavior stays green.

- [ ] **Step 10: Record real windowed accessibility evidence**

Create `docs/m4a1-shell-proof.md` in the M3e proof format. Run with the user's real data and record actual date/platform/commands/results for:

- plain `make run` visibly enters selection before any PLAY frame;
- Emily and Carnby each select/start once by mouse and once by keyboard;
- story starts by single click and Esc returns to portraits;
- PLAY Escape opens the paused menu; Return, Configuration, and Quit work by mouse and keyboard;
- sticky Action works with one-finger sequential Space then direction;
- remapped key works immediately and after a full process restart;
- corrupt-load and forced/unwritable-save messages name the settings path and dismiss by mouse/keyboard without changing mode;
- no held movement, activation, or sticky pulse replays after menu entry/exit;
- exactly one visible cursor appears in every shell/menu/PLAY mode and window close remains reachable.

Record only observations actually performed. A failed manual item is an implementation failure to fix and rerun, not a waived checkbox.

- [ ] **Step 11: Update the living architecture map**

In `CONTEXT.md`, mark M4a1 complete in the milestone table and add a concise shell boundary section documenting:

- `config.py` owns pygame-free settings schema/path/atomic store;
- `ui.py` owns compiled pygame bindings, transient input state, presenters, drawing, and hit geometry;
- `__main__.py` owns the session, persistence policy, raw capture, event pump, notice priority, and atomic game/floor replacement;
- `Game` owns no settings;
- normal boot stages floor zero but never ticks/presents PLAY before character confirmation;
- `make prove-shell` and `docs/m4a1-shell-proof.md` are the automated/manual release evidence.

- [ ] **Step 12: Commit proof and handoff**

```bash
git add tests/test_shell_journeys.py tests/test_main.py Makefile docs/m4a1-shell-proof.md CONTEXT.md
git commit -m "test: prove accessible M4a1 shell"
```

---

## Final acceptance checklist

- [ ] Normal launch opens CHARACTER_SELECT; explicit `--floor 0`, `--combat-venue`, and `--mouse-combat-fixture` bypass it.
- [ ] Left portrait starts Emily (`hero=1`, `LISTBOD2`/`LISTANI2`); right starts Carnby (`hero=0`, `LISTBODY`/`LISTANIM`).
- [ ] Portrait art/cadre and story half/text placement pass real-data goldens; missing/short cadre/resource data fails with archive/entry/index context.
- [ ] Character selection and story start are each single-left-click reachable; Escape backs/cleanly quits as specified.
- [ ] Escape in PLAY opens SYSTEM_MENU, simulation pauses, and Return/Configuration/Quit work with keyboard and one left button.
- [ ] Seven remappable controls and fixed Escape CANCEL match the schema; capture steals a key and never replays the captured event.
- [ ] Settings load once, save atomically at dirty boundaries, survive hero/death replacement and process reload, and never enter `Game`.
- [ ] Sticky Action is sequential, keyboard-only, one tick, default-off, and cleared at every required transition.
- [ ] Corrupt/unknown/unwritable settings fall back or remain live as required, name the destination/error, and persist visibly until Dismiss.
- [ ] Notice dismissal has first refusal only for its own click/activation routes and never changes the active mode.
- [ ] Mouse capability and mode registries are exhaustive for CHARACTER_SELECT, SYSTEM_MENU, notice dismissal, and window close; remap capture is explicitly documented keyboard-only.
- [ ] The OS/software cursor rule still yields exactly one visible cursor; PLAY click resolver and M3e behavior are unchanged.
- [ ] `.venv/bin/pytest -q`, `make prove`, and `make prove-shell` pass.
- [ ] `docs/m4a1-shell-proof.md` contains actual successful windowed single-button/keyboard evidence.

## Implementation stop boundary

Stop after M4a1 acceptance. Do not add M4a2 save/load rows or persistence format, M4b audio/sequences/title flow, or M4c ending closure. Leave the three-row MAIN menu as the stable host into which M4a2 will insert Save/Load.
