# Controls Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every piece of input handling out of `PyAitD/app/shell.py` and `PyAitD/app/ui.py` into `PyAitD/app/controls/`, behind a fixed `Action` vocabulary, with the engine consuming a frozen `PlayInput` it owns; behaviour byte-identical, proven by a recorded event-stream golden.

**Architecture:** The engine's `play_tick` takes a five-field `PlayInput` and owns the mouse-attack latch on `Game`. The app's `ControlsState` holds a `KeyboardState` (keys → held bits, pulses, queued `Action`s) and a `PointerState` (hold-follow, double-press run, resume, cut settling) whose transitions are pure functions in `controls/pointer.py`; `controls/router.py` turns actions and pointer decisions into engine calls; `controls/cursor.py` says what the cursor shows; `controls/snapshot.py` folds the two states into one `PlayInput` per tick. `shell.py` keeps only the pump, tick accumulator, persistence policy, restart branches and presentation.

**Tech Stack:** Python 3.12, pygame-ce (events and key codes only inside `app/`), pytest. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-03-controls-refactor-design.md`

## Global Constraints

- `# SPDX-License-Identifier: GPL-2.0-only` is the first line of every new `.py` file (`tests/test_layering.py::test_every_python_file_starts_with_the_spdx_line`). Absolute imports only.
- Every test file declares exactly one subject marker (`engine`, `render`, `shell`, `tools`, `meta`) as module-level `pytestmark`, plus `journey` for real-loop and long real-data runs. New controls tests carry `shell`.
- Tests take game data from the `data_dir` fixture and the profile from the `profile` fixture; never import `AITD1` directly.
- Run pytest headless: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest ...`. `make test` is the gate after every task; the golden test (Task 1) must stay green after every task from Task 2 on.
- Layering (spec §1): `app/controls` may import `pygame`, `PyAitD.engine`, `PyAitD.app.config`, `PyAitD.app.ui`; never `PyAitD.app.shell` or `PyAitD.render`. `app/ui` never imports `PyAitD.app.controls`. `engine` imports nothing under `PyAitD.app` (already pinned); `InputBuffer` no longer exists anywhere after Task 4.
- Behaviour identical: existing input suites (`test_mouse_only`, `test_runtime_modes`, `test_shell_journeys`, `test_ui_input`, `test_ui_mouse`, `test_ui_reducers`, `test_play_loop`, `test_playworld`) keep every assertion; only imports, names and the `InputBuffer` field spellings listed per task change. Any other assertion edit is a finding to rule on.
- Settings schema v1 is unchanged: the eight key-bindable `Action` members keep the `Control` names and values `UP, DOWN, LEFT, RIGHT, ACTION, INVENTORY_CONFIRM, CANCEL, TOGGLE_INPUT_MODE`.
- Constants keep their values: `DOUBLE_PRESS_TICKS = 25`, `DOUBLE_PRESS_RESUME_PX = 6`, `CUT_DEAD_ZONE_PX = 6`, `MOUSE_ATTACK_TICK_BUDGET = 100`, `NATIVE_ACTION = 0x2000`, `TICK_MS = 20`.
- Never mass-reformat. No lint or typecheck is configured.
- Commit messages end with the session's attribution trailer:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Wr26qgHgbV5RqX5VHn6Tjf
  ```

---

## File map

| File | Responsibility after this plan |
|---|---|
| `PyAitD/engine/script/playworld/input.py` | `PlayInput`, `IDLE`, `arm_mouse_attack`, `clear_mouse_attack`; `apply_play_input(game, play_input)` |
| `PyAitD/engine/script/playworld/tick.py` | `play_tick(game, floor, play_input)` |
| `PyAitD/engine/script/game/state.py` | `Game.mouse_attack_target`, `Game.mouse_attack_ticks` (transient) |
| `PyAitD/app/controls/__init__.py` | re-exports |
| `PyAitD/app/controls/actions.py` | `Action`, `KEY_BINDABLE`, `DIRECTION_BITS` |
| `PyAitD/app/controls/bindings.py` | `compile_bindings`, `canonical_key_name`, `DEFAULT_ACTION_BY_KEY` |
| `PyAitD/app/controls/keyboard.py` | `KeyboardState`, `feed_key_event`, `reset_keyboard` |
| `PyAitD/app/controls/pointer.py` | `PointerState`, `press`, `move`, `release`, `reset_pointer`, `rebase`, `press_decision`, `hold_decision`, the decision types, the three constants |
| `PyAitD/app/controls/snapshot.py` | `ControlsState`, `build_play_input`, `reset`, `configure`, `feed_event` |
| `PyAitD/app/controls/modals.py` | the modal reducers, `capture_system_key`, `pick_system_key`, the `hit_test_*` functions |
| `PyAitD/app/controls/router.py` | `route_command`, `route_mouse`, `route_hover`, `resolve_play_click`, `route_play_click`, `apply_pointer`, `cancel_follow`, `rebase_follow`, `take_over_play_input`, the result appliers, `inventory_hud_available` |
| `PyAitD/app/controls/cursor.py` | `cursor_state`, `cursor_kind`, `marker_for`, `intent_marker`, `hit_actor_ids`, `hit_feedback_rects`, `pointer_actor_targets`, `expand_actor_targets` |
| `PyAitD/app/ui.py` | presenters, results, layouts, painter, `render_*`, `render_cursor`; nothing about input |
| `PyAitD/app/shell.py` | CLI, pump, accumulator, persistence policy, branches, presentation |
| `PyAitD/app/startup.py` | switches on `Action` instead of `Command` |
| `tests/test_controls_golden.py`, `tests/golden/controls_events.json` | the recorded-events golden |
| `tests/test_controls_{keyboard,bindings,pointer,snapshot,modals}.py` | unit tests for the pure modules |
| `tests/test_layering.py`, `CONTEXT.md`, `AGENTS.md` | pins and docs |

---

### Task 1: The recorded-events golden

Recorded on unchanged code and committed; every later task must keep it byte-identical. It replays a scripted pygame event stream through the real `shell.run` pump (the `tests/test_shell_journeys.py` harness, copied) against the real attic, and pins the per-tick engine-side input and the hero's motion.

**Files:**
- Create: `tests/test_controls_golden.py`, `tests/golden/controls_events.json`

**Interfaces:**
- Produces: the golden file and `PYAITD_RECORD_GOLDEN=1` re-recording. Nothing else consumes them.

- [ ] **Step 1: Write the test**

`tests/test_controls_golden.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""The controls refactor's invariance golden.

A scripted event stream (keys, presses, drags, a double press, focus loss,
the system menu) replays through the real shell.run pump against the real
attic, and the per-tick engine input plus the hero's motion are pinned.
Recorded on the code before the refactor; every task of the refactor must
keep it byte-identical. Re-record only with PYAITD_RECORD_GOLDEN=1 and a
reason in the commit message.
"""
import contextlib
import itertools
import json
import os
import pathlib
from types import SimpleNamespace

import numpy as np
import pygame
import pytest

from PyAitD.engine.script.game import init_game
from PyAitD.app.ui import ModalSession

pytestmark = [pytest.mark.shell, pytest.mark.journey]

GOLDEN = pathlib.Path(__file__).parent / "golden" / "controls_events.json"
_FRAME = np.zeros((200, 320, 3), dtype=np.uint8)


class _HeadlessRenderer:
    def __init__(self, *_args, **_kwargs):
        self.presented = 0
        self.fallback_notice = None

    def window_to_logical(self, pos):
        return pos

    def ui_scale(self):
        return 1.0

    def scene_thumbnail(self):
        return _FRAME

    def present(self, _frame):
        self.presented += 1

    def set_options(self, options):
        self.options = options

    def close(self):
        pass


@contextlib.contextmanager
def _pygame_runtime():
    from PyAitD.app import ui
    pygame.init()
    try:
        yield
    finally:
        pygame.quit()
        ui._font.cache_clear()


def _key_down(code):
    return pygame.event.Event(pygame.KEYDOWN, key=code, repeat=False)


def _key_up(code):
    return pygame.event.Event(pygame.KEYUP, key=code)


def _motion(pos, touch=False):
    return pygame.event.Event(pygame.MOUSEMOTION, pos=pos, touch=touch)


def _down(pos, touch=False):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos, touch=touch)


def _up(touch=False):
    return pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, touch=touch)


def _script():
    """One list of events per pumped frame; [] is a frame with no events.
    One frame is one 20 ms tick, so 25 frames is the double-press window."""
    frames = []

    def quiet(n):
        frames.extend([[] for _ in range(n)])

    quiet(5)
    # keyboard: toggle, walk forward, action, walk left, toggle back
    frames.append([_key_down(pygame.K_TAB)])
    quiet(3)
    frames.append([_key_down(pygame.K_UP)])
    quiet(40)
    frames.append([_key_down(pygame.K_SPACE)])
    frames.append([_key_up(pygame.K_SPACE)])
    quiet(10)
    frames.append([_key_up(pygame.K_UP), _key_down(pygame.K_LEFT)])
    quiet(20)
    frames.append([_key_up(pygame.K_LEFT)])
    frames.append([_key_down(pygame.K_TAB)])
    quiet(5)
    # mouse: hold-follow with a drag, release
    frames.append([_motion((160, 150))])
    frames.append([_down((160, 150))])
    quiet(40)
    frames.append([_motion((200, 150))])
    quiet(40)
    frames.append([_motion((60, 120))])
    quiet(30)
    frames.append([_up()])
    quiet(10)
    # double press: run, and resume the same destination
    frames.append([_down((200, 150))])
    frames.append([_up()])
    quiet(3)
    frames.append([_down((201, 150))])
    quiet(60)
    frames.append([_motion((240, 140))])
    quiet(30)
    frames.append([_up()])
    quiet(10)
    # a press far from any floor: steer, then focus loss ends the hold
    frames.append([_down((10, 10))])
    quiet(20)
    frames.append([pygame.event.Event(pygame.WINDOWFOCUSLOST)])
    quiet(5)
    frames.append([pygame.event.Event(pygame.WINDOWFOCUSGAINED)])
    quiet(5)
    # a touch-origin press, then the system menu opens and closes on Escape
    frames.append([_down((160, 150), touch=True)])
    quiet(20)
    frames.append([_up(touch=True)])
    frames.append([_key_down(pygame.K_ESCAPE)])
    quiet(5)
    frames.append([_key_down(pygame.K_ESCAPE)])
    quiet(20)
    frames.append([pygame.event.Event(pygame.QUIT)])
    return frames


def _intent_summary(game):
    intent = game.nav_intent
    if intent is None:
        return None
    return [intent.dest_x, intent.dest_z, intent.room, intent.target_object_idx,
            bool(intent.requires_hold), bool(intent.run), bool(intent.steering),
            bool(intent.engaged)]


def _record(data_dir, profile, monkeypatch, tmp_path):
    import PyAitD.app.shell as main

    game = init_game(data_dir, profile)
    game.num_camera = game.new_num_camera
    game.rng.seed(7)
    session = ModalSession(settings_path=tmp_path / "settings.json")
    frames = iter(_script())
    ticks = itertools.count(0, 20)
    rows = []
    real_play_tick = main.play_tick

    def spy(current, floor, snapshot):
        hero_idx = current.current_camera_target_actor
        result = real_play_tick(current, floor, snapshot)
        hero = current.actors[hero_idx]
        rows.append([
            current.timer, current.input_mode.name,
            current.local_joyd, current.local_click, current.action,
            hero.room, hero.room_x, hero.room_z, hero.beta,
            hero.anim, hero.track_mode, _intent_summary(current),
        ])
        return result

    renderer = _HeadlessRenderer()
    monkeypatch.setattr(main, "Renderer", lambda *_a, **_k: renderer)
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (_FRAME, []))
    monkeypatch.setattr(main, "play_tick", spy)
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(frames))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(ticks))
    monkeypatch.setattr(main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *args: None))
    monkeypatch.setattr(main.pygame.display, "set_caption", lambda *args: None)
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda *args: None)
    with _pygame_runtime():
        assert main.run(game, session=session) == 0
    assert renderer.presented > 0
    return {"ticks": rows}


def test_the_scripted_event_stream_replays_identically(data_dir, profile, monkeypatch, tmp_path):
    recorded = _record(data_dir, profile, monkeypatch, tmp_path)
    assert len(recorded["ticks"]) > 300, "the script did not reach the play loop"
    if os.environ.get("PYAITD_RECORD_GOLDEN") == "1":
        GOLDEN.write_text(json.dumps(recorded, indent=0) + "\n")
    expected = json.loads(GOLDEN.read_text())
    assert recorded == expected, (
        "the controls refactor changed what the engine saw or how the hero moved; "
        "diff tests/golden/controls_events.json against a re-record to find the tick"
    )
```

- [ ] **Step 2: Record**

Run: `PYAITD_RECORD_GOLDEN=1 SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_controls_golden.py -q`
Expected: PASS and `tests/golden/controls_events.json` created. Open it and confirm: `input_mode` is `KEYBOARD` for the keyboard section and `MOUSE` after; `local_joyd` is non-zero during the held UP; at least one tick has a non-null intent with `run` true (the double press) and one with `steering` true (the (10, 10) press). If any of those is missing, the script did not exercise that path — fix the script (a different pixel, more frames), not the assertions, and re-record.

- [ ] **Step 3: Verify stability**

Run the test twice more without the env var: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_controls_golden.py -q`
Expected: PASS both times (the run is deterministic: `rng.seed(7)`, fixed 20 ms frames).

- [ ] **Step 4: Full suite and commit**

Run: `make test`
Expected: everything green.

```bash
git add tests/test_controls_golden.py tests/golden/controls_events.json
git commit -m "test(controls): recorded-events golden for the controls refactor"
```

---

### Task 2: The engine boundary — `PlayInput` and the attack latch on `Game`

**Files:**
- Modify: `PyAitD/engine/script/playworld/input.py` (`apply_play_input`, `_apply_mouse_attack`, `_apply_mouse_input`, `_clear_mouse_attack`), `PyAitD/engine/script/playworld/tick.py:24,41` (`play_tick`), `PyAitD/engine/script/playworld/__init__.py`, `PyAitD/engine/script/game/state.py:173` (after `self.nav_intent = None`)
- Modify: `PyAitD/app/shell.py` (`route_play_click`, `follow_pointer`, `_cancel_pointer_invalidation`, `_take_over_play_input`, `route_command`'s TOGGLE branch, the `play_tick` call in `run`), `PyAitD/app/ui.py` (`InputBuffer` loses `mouse_attack_target`/`mouse_attack_ticks`; `reset_input` no longer touches them)
- Test: `tests/test_playworld.py`, `tests/test_play_loop.py`, `tests/test_ui_input.py`, `tests/test_runtime_modes.py`, `tests/test_mouse_only.py`, `tests/test_shell_journeys.py`, every file calling `play_tick(..., InputBuffer())`, `tools/prove_intro.py`

**Interfaces:**
- Produces: `PyAitD.engine.script.playworld.input.PlayInput(joyd=0, action_held=False, action_pulse=False, pointer_held=False, focused=True)` (frozen dataclass), `IDLE = PlayInput()`, `arm_mouse_attack(game, target_idx)`, `clear_mouse_attack(game)`; `play_tick(game, floor, play_input)`; `apply_play_input(game, play_input)`; `Game.mouse_attack_target: int | None`, `Game.mouse_attack_ticks: int`.
- Produces (temporary, removed in Task 4): `shell._play_input(input_buffer) -> PlayInput`, which also consumes `input_buffer.action_pulse`.

- [ ] **Step 1: Write the failing engine tests**

Append to `tests/test_playworld.py`:

```python
def test_play_input_is_frozen_and_idle_by_default():
    from PyAitD.engine.script.playworld import IDLE, PlayInput
    assert IDLE == PlayInput(joyd=0, action_held=False, action_pulse=False, pointer_held=False, focused=True)
    with pytest.raises(Exception):
        IDLE.joyd = 1


def test_the_engine_publishes_a_pulse_every_tick_it_is_handed_one(data_dir, profile):
    """Consumption moved to the app (controls.snapshot builds one snapshot per
    tick and clears the keyboard pulse then); the engine no longer writes
    back into its input."""
    from PyAitD.engine.script.effects import InputMode
    from PyAitD.engine.script.playworld import PlayInput, apply_play_input
    game = init_game(data_dir, profile)
    game.input_mode = InputMode.KEYBOARD
    pulse = PlayInput(action_pulse=True)
    apply_play_input(game, pulse)
    assert (game.local_click, game.action) == (1, 0x2000)
    apply_play_input(game, pulse)
    assert (game.local_click, game.action) == (1, 0x2000)
    apply_play_input(game, PlayInput())
    assert (game.local_click, game.action) == (0, 0)


def test_the_mouse_attack_latch_lives_on_the_game(data_dir, profile):
    from PyAitD.engine.script.playworld import arm_mouse_attack, clear_mouse_attack
    game = init_game(data_dir, profile)
    assert (game.mouse_attack_target, game.mouse_attack_ticks) == (None, 0)
    arm_mouse_attack(game, 7)
    assert (game.mouse_attack_target, game.mouse_attack_ticks) == (7, 0)
    game.mouse_attack_ticks = 12
    clear_mouse_attack(game)
    assert (game.mouse_attack_target, game.mouse_attack_ticks) == (None, 0)
```

Add `import pytest` at the top of `tests/test_playworld.py` if it is not already imported.

- [ ] **Step 2: Run them to see them fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_playworld.py -q -k "play_input or pulse_every_tick or latch_lives"`
Expected: 3 failures, `ImportError` on `IDLE`/`PlayInput`/`arm_mouse_attack`.

- [ ] **Step 3: Engine implementation**

`PyAitD/engine/script/playworld/input.py`: add after the imports

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class PlayInput:
    """What the engine reads from the player each tick, and nothing else.

    Built once per tick by app.controls.snapshot; the app keeps every piece
    of gesture state (hold-follow, double press, cut settling) on its side of
    this boundary. Frozen so the engine cannot write back into it: the
    sticky-action pulse is consumed by the app when it builds the snapshot.
    """
    joyd: int = 0
    action_held: bool = False
    action_pulse: bool = False
    pointer_held: bool = False
    focused: bool = True


IDLE = PlayInput()


def arm_mouse_attack(game, target_idx):
    """An accepted target click holds FITD's own action input for the next
    few ticks (mainLoop.cpp:87-101); the engine owns the countdown because
    the engine is what ends it (the hero back to idle, or the budget)."""
    game.mouse_attack_target = target_idx
    game.mouse_attack_ticks = 0


def clear_mouse_attack(game):
    game.mouse_attack_target = None
    game.mouse_attack_ticks = 0
```

Then:
- Delete `_clear_mouse_attack(input_buffer)`; every use becomes `clear_mouse_attack(game)`.
- `apply_play_input(game, play_input)`: rename the parameter; in the keyboard branch delete the line `input_buffer.action_pulse = False` and the mouse branch's `input_buffer.action_pulse = False`; `game.local_joyd = play_input.joyd if play_input.focused else 0`; `pressed = play_input.focused and (play_input.action_held or play_input.action_pulse)`.
- `_apply_mouse_attack(game, play_input)`: `target_idx = game.mouse_attack_target`; `ticks = game.mouse_attack_ticks`; `game.mouse_attack_ticks = ticks + 1`; the two `_clear_mouse_attack(input_buffer)` calls become `clear_mouse_attack(game)`.
- `_apply_mouse_input(game, play_input)`: `if not play_input.focused or not play_input.pointer_held:`.
- `tick.py`: `def play_tick(game, floor, play_input):` and `apply_play_input(game, play_input)`.
- `playworld/__init__.py`: export `IDLE, PlayInput, arm_mouse_attack, clear_mouse_attack` from `.input` and drop `_clear_mouse_attack` from the list.
- `state.py`, after `self.nav_intent = None` (line 173): `self.mouse_attack_target = None` and `self.mouse_attack_ticks = 0` with the comment `# the accepted target click's action hold (playworld.input.arm_mouse_attack); transient like nav_intent`.

- [ ] **Step 4: Run the engine tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_playworld.py -q -k "play_input or pulse_every_tick or latch_lives"`
Expected: PASS.

- [ ] **Step 5: The shell adapter and the latch call sites**

In `PyAitD/app/shell.py`:
- Import: `from PyAitD.engine.script.playworld import TICK_MS, PlayInput, arm_mouse_attack, clear_mouse_attack, play_tick`.
- Add after `configure_session_input`:

```python
def _play_input(input_buffer):
    """The engine's snapshot for one tick. Consumes the sticky pulse: the
    engine no longer writes back into its input (playworld.input.PlayInput),
    and a pulse raised while a modal is open must still fire on the first
    play tick after it, so it is cleared here and nowhere else."""
    snapshot = PlayInput(
        joyd=input_buffer.held_joyd,
        action_held=input_buffer.action_held,
        action_pulse=input_buffer.action_pulse,
        pointer_held=input_buffer.pointer_held,
        focused=input_buffer.focused,
    )
    input_buffer.action_pulse = False
    return snapshot
```
- In `run`: `play_tick(game, floor, _play_input(input_buffer))`.
- `route_play_click`, attack branch: replace the two `input_buffer.mouse_attack_*` writes with `arm_mouse_attack(game, payload)` (still inside `if attack_in_hand(game, payload)`; the `input_buffer is not None` guard on the arming is dropped, the one on `follow_spent` stays).
- `follow_pointer`: the guard `or input_buffer.mouse_attack_target is not None` becomes `or game.mouse_attack_target is not None`.
- `_take_over_play_input`: add `clear_mouse_attack(game)` right after `cancel_nav_intent(game)`.
- `_cancel_pointer_invalidation`: before `return _cancel_follow(game, input_buffer)` add `if event.type == pygame.WINDOWFOCUSLOST: clear_mouse_attack(game)`.
- `route_command` TOGGLE branch: add `clear_mouse_attack(game)` after `cancel_nav_intent(game)`.
- `_apply_system_result` and `_apply_startup_result` keep their `reset_input` calls unchanged (the latch was already cleared when the modal opened).

In `PyAitD/app/ui.py`: delete the `mouse_attack_target` and `mouse_attack_ticks` fields (and their comment) from `InputBuffer`, and the two lines clearing them in `reset_input`.

- [ ] **Step 6: Test churn (mechanical)**

- Every `play_tick(game, floor, InputBuffer())` in `tests/` and `tools/prove_intro.py` → `play_tick(game, floor, IDLE)` with `from PyAitD.engine.script.playworld import IDLE` (drop the `InputBuffer` import where it becomes unused). Find them: `grep -rln "play_tick(.*InputBuffer()" tests tools`.
- `tests/test_playworld.py`: every `apply_play_input(game, InputBuffer(...))` → `apply_play_input(game, PlayInput(...))` with `held_joyd=` → `joyd=`; tests that set `buf.mouse_attack_target`/`buf.mouse_attack_ticks` set `game.mouse_attack_target`/`game.mouse_attack_ticks` instead and assert on the game fields.
- `tests/test_play_loop.py::test_apply_play_input_mapping`: `PlayInput(joyd=9, action_held=True)`. Delete `test_sticky_action_pulse_is_visible_for_exactly_one_keyboard_tick` and replace it with:

```python
def test_the_shell_snapshot_consumes_the_sticky_pulse_exactly_once():
    import PyAitD.app.shell as main
    from PyAitD.app.ui import InputBuffer
    state = InputBuffer(action_pulse=True, held_joyd=3)
    first = main._play_input(state)
    assert (first.action_pulse, first.joyd, state.action_pulse) == (True, 3, False)
    assert main._play_input(state).action_pulse is False
```
- `tests/test_ui_input.py`: delete `test_reset_input_clears_native_mouse_combat` (its guarantee is now `test_the_mouse_attack_latch_lives_on_the_game` plus the `_take_over_play_input` journeys).
- `tests/test_runtime_modes.py`, `tests/test_mouse_only.py`, `tests/test_shell_journeys.py`, `tests/test_play_loop.py`: `grep -n mouse_attack` and change every `buffer.mouse_attack_target`/`..._ticks` read or write to `game.mouse_attack_target`/`game.mouse_attack_ticks` (the `game` in scope for that test). A test that constructs `InputBuffer(mouse_attack_target=...)` sets the game field after building the game instead. Assertions keep their expected values.
- Any test spy with the signature `(game, floor, buffer)` passed to `main.play_tick` keeps working (positional); one that asserts `not buffer.pointer_held` keeps working because `_play_input` copies the field.

- [ ] **Step 7: Full suite and the golden**

Run: `make test`
Expected: green, including `tests/test_controls_golden.py` unchanged.

- [ ] **Step 8: Commit**

```bash
git add PyAitD/engine/script/playworld PyAitD/engine/script/game/state.py PyAitD/app/shell.py PyAitD/app/ui.py tests tools/prove_intro.py
git commit -m "refactor(playworld): the engine reads a frozen PlayInput and owns the mouse attack latch"
```

---

### Task 3: `app/controls/` — `Action`, bindings, keyboard; `Command` removed

**Files:**
- Create: `PyAitD/app/controls/__init__.py`, `PyAitD/app/controls/actions.py`, `PyAitD/app/controls/bindings.py`, `PyAitD/app/controls/keyboard.py`
- Modify: `PyAitD/app/config.py:16-19` (`Control` becomes an alias), `PyAitD/app/ui.py` (delete `Command`, `_DIRECTION_CONTROL`, `_DEFAULT_CONTROL_BY_KEY`, `canonical_key_name`, `compile_bindings`; `InputBuffer.commands` carries `Action`s; `event_to_input`'s key half delegates to `feed_key_event`; the reducers switch on `Action`), `PyAitD/app/startup.py:90-112` (`Action`), `PyAitD/app/shell.py` (`Command` → `Action`)
- Test: create `tests/test_controls_bindings.py`, `tests/test_controls_keyboard.py`; modify `tests/test_ui_input.py`, `tests/test_ui_reducers.py`, `tests/test_startup.py`, `tests/test_runtime_modes.py`, `tests/test_mouse_only.py`, `tests/test_shell_journeys.py`, `tests/test_play_loop.py`, `tests/test_game_over.py`, `tests/test_main.py` (`Command` → `Action`)

**Interfaces:**
- Produces: `controls.actions.Action` (str Enum; members `UP, DOWN, LEFT, RIGHT, ACTION, INVENTORY_CONFIRM, CANCEL, TOGGLE_INPUT_MODE, WALK, RUN, TARGET, PUSH, USE, MENU_CLICK`), `KEY_BINDABLE`, `DIRECTION_BITS: dict[Action, int]`; `controls.bindings.compile_bindings(settings) -> dict[int, Action]`, `canonical_key_name(key) -> str`, `DEFAULT_ACTION_BY_KEY`; `controls.keyboard.KeyboardState(held_joyd=0, action_held=False, action_pulse=False, sticky_action=False, sticky_armed=False, queue=deque(), table=None)`, `feed_key_event(state, event) -> None`, `reset_keyboard(state)`.
- `config.Control is Action`; `REMAPPABLE_CONTROLS` unchanged in content.
- The old `Command` members map one-to-one: `Command.UP/DOWN/LEFT/RIGHT` → `Action.UP/DOWN/LEFT/RIGHT`, `Command.ACCEPT` → `Action.ACTION`, `Command.CANCEL` → `Action.CANCEL`, `Command.OPEN_INVENTORY` → `Action.INVENTORY_CONFIRM`, `Command.TOGGLE_INPUT_MODE` → `Action.TOGGLE_INPUT_MODE`.

- [ ] **Step 1: Write the failing tests**

`tests/test_controls_bindings.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
import pygame
import pytest

from PyAitD.app.config import Control, Settings, default_settings, replace_binding
from PyAitD.app.controls.actions import Action, KEY_BINDABLE
from PyAitD.app.controls.bindings import (
    DEFAULT_ACTION_BY_KEY, canonical_key_name, compile_bindings,
)

pytestmark = pytest.mark.shell


def test_control_is_the_key_bindable_half_of_action():
    assert Control is Action
    assert tuple(action.name for action in KEY_BINDABLE) == (
        "UP", "DOWN", "LEFT", "RIGHT", "ACTION", "INVENTORY_CONFIRM", "CANCEL", "TOGGLE_INPUT_MODE",
    )
    assert set(default_settings().bindings) == {action.name for action in KEY_BINDABLE}


def test_pygame_key_names_round_trip_through_compat_adapter():
    assert canonical_key_name(pygame.K_RETURN) == "return"
    assert pygame.key.key_code(canonical_key_name(pygame.K_w)) == pygame.K_w


def test_unknown_persisted_key_name_is_rejected():
    settings = default_settings()
    bindings = dict(settings.bindings)
    bindings["ACTION"] = ("definitely-not-a-pygame-key",)
    with pytest.raises(ValueError, match="definitely-not-a-pygame-key"):
        compile_bindings(Settings(bindings, False))


def test_the_default_table_matches_the_default_settings():
    compiled = compile_bindings(default_settings())
    assert compiled == DEFAULT_ACTION_BY_KEY


def test_a_remap_moves_the_key_and_nothing_else():
    compiled = compile_bindings(replace_binding(default_settings(), Control.UP, "q"))
    assert compiled[pygame.K_q] is Action.UP
    assert pygame.K_w not in compiled
    assert compiled[pygame.K_SPACE] is Action.ACTION
```

`tests/test_controls_keyboard.py` (the keyboard half of today's `tests/test_ui_input.py`, on the new state):

```python
# SPDX-License-Identifier: GPL-2.0-only
import pygame
import pytest

from PyAitD.app.config import Settings, default_settings, replace_binding
from PyAitD.app.controls.actions import Action
from PyAitD.app.controls.bindings import compile_bindings
from PyAitD.app.controls.keyboard import KeyboardState, feed_key_event, reset_keyboard

pytestmark = pytest.mark.shell


def key(kind, value, *, repeat=False):
    return pygame.event.Event(kind, key=value, repeat=repeat)


def test_held_movement_survives_queue_consumption_and_action_is_edge_free():
    state = KeyboardState()
    feed_key_event(state, key(pygame.KEYDOWN, pygame.K_UP))
    feed_key_event(state, key(pygame.KEYDOWN, pygame.K_SPACE))
    assert (state.held_joyd, state.action_held) == (1, True)
    assert list(state.queue) == [Action.UP, Action.ACTION]
    state.queue.popleft()
    assert (state.held_joyd, state.action_held) == (1, True)


def test_keyup_and_reset_release_without_a_new_action():
    state = KeyboardState(held_joyd=1, action_held=True)
    feed_key_event(state, key(pygame.KEYUP, pygame.K_UP))
    assert state.held_joyd == 0
    state.queue.append(Action.ACTION)
    reset_keyboard(state)
    assert (state.held_joyd, state.action_held, list(state.queue)) == (0, False, [])


def test_inventory_shortcuts_are_single_edges():
    state = KeyboardState()
    feed_key_event(state, key(pygame.KEYDOWN, pygame.K_RETURN))
    feed_key_event(state, key(pygame.KEYDOWN, pygame.K_RETURN, repeat=True))
    feed_key_event(state, key(pygame.KEYDOWN, pygame.K_i))
    assert list(state.queue) == [Action.INVENTORY_CONFIRM, Action.INVENTORY_CONFIRM]


def test_tab_requests_an_input_mode_toggle():
    state = KeyboardState()
    feed_key_event(state, key(pygame.KEYDOWN, pygame.K_TAB))
    assert Action.TOGGLE_INPUT_MODE in state.queue


def test_remapped_table_drives_actions_and_held_bits():
    state = KeyboardState(table=compile_bindings(replace_binding(default_settings(), Action.UP, "q")))
    feed_key_event(state, key(pygame.KEYDOWN, pygame.K_q))
    assert (state.held_joyd, list(state.queue)) == (1, [Action.UP])
    feed_key_event(state, key(pygame.KEYUP, pygame.K_q))
    assert state.held_joyd == 0
    feed_key_event(state, key(pygame.KEYDOWN, pygame.K_w))
    assert state.held_joyd == 0


def test_sticky_action_arms_then_pulses_on_the_next_direction_only_once():
    state = KeyboardState(sticky_action=True)
    feed_key_event(state, key(pygame.KEYDOWN, pygame.K_SPACE))
    assert (state.sticky_armed, state.action_held, state.action_pulse) == (True, False, False)
    assert list(state.queue) == [Action.ACTION]
    feed_key_event(state, key(pygame.KEYDOWN, pygame.K_UP))
    assert (state.sticky_armed, state.action_pulse) == (False, True)
    feed_key_event(state, key(pygame.KEYDOWN, pygame.K_UP, repeat=True))
    assert (state.sticky_armed, state.action_pulse) == (False, True)


def test_reset_cannot_leave_sticky_state_but_keeps_the_table_and_the_setting():
    table = compile_bindings(default_settings())
    state = KeyboardState(sticky_action=True, sticky_armed=True, action_pulse=True, held_joyd=1, action_held=True, table=table)
    reset_keyboard(state)
    assert (state.held_joyd, state.action_held, state.sticky_armed, state.action_pulse) == (0, False, False, False)
    assert state.table is table and state.sticky_action is True
```

- [ ] **Step 2: Run them to see them fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_controls_bindings.py tests/test_controls_keyboard.py -q`
Expected: collection errors, `No module named 'PyAitD.app.controls'`.

- [ ] **Step 3: The package**

`PyAitD/app/controls/actions.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""The fixed vocabulary every key, gesture and (later) pack binds to.

The eight key-bindable members keep the names and values settings schema v1
stores under "bindings", so a settings file written before this package
existed still loads. The pointer-only members are produced by
controls.pointer and consumed by controls.router; nothing in settings names
them yet.
"""
from enum import Enum


class Action(str, Enum):
    UP = "UP"; DOWN = "DOWN"; LEFT = "LEFT"; RIGHT = "RIGHT"
    ACTION = "ACTION"; INVENTORY_CONFIRM = "INVENTORY_CONFIRM"
    CANCEL = "CANCEL"; TOGGLE_INPUT_MODE = "TOGGLE_INPUT_MODE"
    WALK = "WALK"; RUN = "RUN"; TARGET = "TARGET"; PUSH = "PUSH"
    USE = "USE"; MENU_CLICK = "MENU_CLICK"


KEY_BINDABLE = (
    Action.UP, Action.DOWN, Action.LEFT, Action.RIGHT, Action.ACTION,
    Action.INVENTORY_CONFIRM, Action.CANCEL, Action.TOGGLE_INPUT_MODE,
)

# FITD's joystick direction bits (mainLoop.cpp): up 1, down 2, left 4, right 8
DIRECTION_BITS = {Action.UP: 1, Action.DOWN: 2, Action.LEFT: 4, Action.RIGHT: 8}
```

`PyAitD/app/config.py`: replace the `class Control(str, Enum)` block (lines 16-19) with

```python
from PyAitD.app.controls.actions import Action, KEY_BINDABLE

Control = Action   # the key-bindable half of the vocabulary; settings v1 stores its names
```

and make `REMAPPABLE_CONTROLS = tuple(control for control in KEY_BINDABLE if control is not Control.CANCEL)`. Check every `for control in Control` in `config.py` (`validate_settings`, `default_settings`, `settings_payload`) and change it to iterate `KEY_BINDABLE`, so the pointer-only members never reach the settings file. Drop the now-unused `Enum` import if nothing else uses it.

`PyAitD/app/controls/bindings.py` (moved from `ui.py`, names changed):

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Settings key names to pygame key codes, and back."""
import pygame

from PyAitD.app.controls.actions import Action, KEY_BINDABLE

# The table the pump uses before settings are loaded, and the one
# default_settings compiles to. Never touches pygame.key before init.
DEFAULT_ACTION_BY_KEY = {
    pygame.K_UP: Action.UP, pygame.K_w: Action.UP,
    pygame.K_DOWN: Action.DOWN, pygame.K_s: Action.DOWN,
    pygame.K_LEFT: Action.LEFT, pygame.K_a: Action.LEFT,
    pygame.K_RIGHT: Action.RIGHT, pygame.K_d: Action.RIGHT,
    pygame.K_SPACE: Action.ACTION,
    pygame.K_RETURN: Action.INVENTORY_CONFIRM,
    pygame.K_i: Action.INVENTORY_CONFIRM,
    pygame.K_ESCAPE: Action.CANCEL,
    pygame.K_TAB: Action.TOGGLE_INPUT_MODE,
}


def canonical_key_name(key):
    name = pygame.key.name(key, use_compat=True)
    if not name or name == "unknown key":
        raise ValueError(f"pygame key {key} has no stable name")
    return name


def compile_bindings(settings):
    compiled = {}
    for action in KEY_BINDABLE:
        for name in settings.bindings[action.name]:
            try:
                code = pygame.key.key_code(name)
            except ValueError as exc:
                raise ValueError(f"unknown pygame key name {name!r}") from exc
            compiled[code] = action
    return compiled
```

`PyAitD/app/controls/keyboard.py` (the KEYDOWN/KEYUP half of today's `event_to_input`, logic unchanged):

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Keys to held direction bits, the action button, the sticky-action pulse
and the queue of one-shot actions the router drains."""
from collections import deque
from dataclasses import dataclass, field

import pygame

from PyAitD.app.controls.actions import Action, DIRECTION_BITS
from PyAitD.app.controls.bindings import DEFAULT_ACTION_BY_KEY


@dataclass
class KeyboardState:
    held_joyd: int = 0
    action_held: bool = False
    action_pulse: bool = False
    sticky_action: bool = False
    sticky_armed: bool = False
    queue: deque = field(default_factory=deque)
    # None keeps the pre-settings defaults; a compiled table is used as-is,
    # even when intentionally empty.
    table: dict | None = None


def reset_keyboard(state):
    state.held_joyd = 0
    state.action_held = False
    state.action_pulse = False
    state.sticky_armed = False
    state.queue.clear()


def feed_key_event(state, event):
    table = DEFAULT_ACTION_BY_KEY if state.table is None else state.table
    if event.type == pygame.KEYDOWN:
        repeated = bool(getattr(event, "repeat", False))
        action = table.get(event.key)
        if action in DIRECTION_BITS:
            state.held_joyd |= DIRECTION_BITS[action]
            if not repeated:
                state.queue.append(action)
                if state.sticky_armed:
                    state.action_pulse = True
                    state.sticky_armed = False
        elif action is Action.ACTION:
            if state.sticky_action:
                if not repeated:
                    state.sticky_armed = True
                    state.queue.append(Action.ACTION)
            else:
                state.action_held = True
                if not repeated:
                    state.queue.append(Action.ACTION)
        elif not repeated and action in (
                Action.INVENTORY_CONFIRM, Action.CANCEL, Action.TOGGLE_INPUT_MODE):
            state.queue.append(action)
    elif event.type == pygame.KEYUP:
        action = table.get(event.key)
        if action in DIRECTION_BITS:
            state.held_joyd &= ~DIRECTION_BITS[action]
        elif action is Action.ACTION:
            state.action_held = False
```

`PyAitD/app/controls/__init__.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Input: the action vocabulary, key bindings, keyboard and pointer state,
the per-tick engine snapshot, and the routing of actions into the game.
Layering: may import pygame, PyAitD.engine, app.config and app.ui; never
app.shell or PyAitD.render (tests/test_layering.py).

Only `actions` is re-exported here. app.config imports
PyAitD.app.controls.actions, and importing a submodule runs this package
__init__ first, so anything re-exported here that reaches app.config would
be a cycle. Import the other modules by name
(`from PyAitD.app.controls.keyboard import ...`)."""
from PyAitD.app.controls.actions import Action, DIRECTION_BITS, KEY_BINDABLE
```

Import direction, checked: `config` → `controls.actions` (imports nothing); `controls.bindings` → `controls.actions` only (it takes `settings` untyped); `controls.keyboard` → `actions`, `bindings`. Nothing under `controls` imports `config` at module level in this task. Verify with `SDL_VIDEODRIVER=dummy .venv/bin/python -c "import PyAitD.app.config, PyAitD.app.controls.keyboard"`.

- [ ] **Step 4: `ui.py`, `startup.py`, `shell.py` switch to `Action`**

`PyAitD/app/ui.py`:
- Delete `class Command`, `_DIRECTION_CONTROL`, `_DEFAULT_CONTROL_BY_KEY`, `canonical_key_name`, `compile_bindings`. Add `from PyAitD.app.controls.actions import Action` and `from PyAitD.app.controls.bindings import compile_bindings` and `from PyAitD.app.controls.keyboard import KeyboardState, feed_key_event, reset_keyboard`.
- `InputBuffer`: replace the fields `held_joyd`, `action_held`, `action_pulse`, `commands`, `bindings`, `sticky_action`, `sticky_armed` with one field `keyboard: KeyboardState = field(default_factory=KeyboardState)`. **Do not** rename the pointer fields yet (Task 4 does). Add read-through properties so the shell and the tests keep compiling in this task:

```python
    @property
    def held_joyd(self): return self.keyboard.held_joyd
    @held_joyd.setter
    def held_joyd(self, value): self.keyboard.held_joyd = value
    @property
    def action_held(self): return self.keyboard.action_held
    @action_held.setter
    def action_held(self, value): self.keyboard.action_held = value
    @property
    def action_pulse(self): return self.keyboard.action_pulse
    @action_pulse.setter
    def action_pulse(self, value): self.keyboard.action_pulse = value
    @property
    def sticky_armed(self): return self.keyboard.sticky_armed
    @sticky_armed.setter
    def sticky_armed(self, value): self.keyboard.sticky_armed = value
    @property
    def sticky_action(self): return self.keyboard.sticky_action
    @property
    def commands(self): return self.keyboard.queue
    @property
    def bindings(self): return self.keyboard.table
```
  A dataclass field cannot share a name with a property, which is why the underlying fields move into `keyboard`. Tests that construct `InputBuffer(held_joyd=9, action_held=True, sticky_armed=True, ...)` must change to `InputBuffer(keyboard=KeyboardState(held_joyd=9, action_held=True, sticky_armed=True))` — those are in `tests/test_runtime_modes.py` (lines ~920-1160), `tests/test_play_loop.py`, `tests/test_ui_input.py`; `grep -n "InputBuffer(" tests | grep -v "InputBuffer()"` lists them all. `commands=deque([...])` becomes `keyboard=KeyboardState(queue=deque([...]))`.
- `reset_input(state)`: the keyboard lines become `reset_keyboard(state.keyboard)`; the pointer lines stay.
- `configure_input(state, settings)`: `state.keyboard.table = compile_bindings(settings)`; `state.keyboard.sticky_action = settings.sticky_action`; `reset_input(state)`.
- `event_to_input(event, state, logical_pos=None)`: the `KEYDOWN`/`KEYUP` half becomes `feed_key_event(state.keyboard, event)`; the QUIT, focus and mouse branches are unchanged.
- The reducers (`reduce_found`, `reduce_inventory`, `reduce_reading`, `reduce_character_select`, `reduce_system_menu`): `Command.X` → `Action.X` per the mapping in Interfaces (`ACCEPT` → `ACTION`, `OPEN_INVENTORY` → `INVENTORY_CONFIRM`).

`PyAitD/app/startup.py`: import `Action` from `PyAitD.app.controls.actions` instead of `Command` from `ui`; same mapping in `reduce_title` and `reduce_startup_menu`.

`PyAitD/app/shell.py`: import `Action` from `PyAitD.app.controls.actions`; every `Command.X` → `Action.X` per the mapping (`route_command`, `route_mouse`, `route_play_click`, `run`'s notice-dismiss check, `_route_game_over_command`); `input_buffer.bindings.get(event.key)` in the mirror block stays (the property). `canonical_key_name` in `_capture_keydown` now comes from `PyAitD.app.controls.bindings`.

- [ ] **Step 5: Test renames**

- `tests/test_ui_input.py`: keep only the pointer and reset tests (`test_primary_pointer_events_preserve_provenance_only_while_held`, `test_reset_input_clears_the_follow_latch`, `test_reset_input_clears_the_cut_settle_state`, `test_keyup_and_focus_loss_release_controls_without_new_command`, `test_repeat_focus_loss_and_reconfiguration_cannot_leave_sticky_state`); the keyboard ones now live in `tests/test_controls_keyboard.py` and the binding ones in `tests/test_controls_bindings.py` (delete them here). In the kept tests, `Command.X` → `Action.X`, `state.commands` stays (property), `InputBuffer(held_joyd=1, action_held=True)` → `InputBuffer(keyboard=KeyboardState(held_joyd=1, action_held=True))`.
- `tests/test_ui_reducers.py`, `tests/test_startup.py`, `tests/test_runtime_modes.py`, `tests/test_mouse_only.py`, `tests/test_shell_journeys.py`, `tests/test_play_loop.py`, `tests/test_game_over.py`, `tests/test_main.py`: `from PyAitD.app.ui import Command` → `from PyAitD.app.controls.actions import Action`; `Command.ACCEPT` → `Action.ACTION`, `Command.OPEN_INVENTORY` → `Action.INVENTORY_CONFIRM`, every other `Command.X` → `Action.X`. `sed` is fine: `sed -i '' -e 's/Command\.ACCEPT/Action.ACTION/g; s/Command\.OPEN_INVENTORY/Action.INVENTORY_CONFIRM/g; s/Command\./Action./g'` on those files, then fix the import lines by hand.
- `tests/test_ui_input.py::test_pygame_key_names_round_trip_through_compat_adapter` and `test_unknown_persisted_key_name_is_rejected` are deleted here (moved to bindings tests above).

- [ ] **Step 6: Run the new tests, then everything**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_controls_bindings.py tests/test_controls_keyboard.py tests/test_ui_input.py tests/test_ui_reducers.py tests/test_startup.py tests/test_layering.py -q`
Expected: PASS. Then `make test`: green, golden unchanged. `grep -rn "Command\b" PyAitD tests tools --include='*.py'` must find nothing but `LegacyCommandDecision`/`LEGACY_COMMAND_REPLACEMENTS` in `mouse_contract.py` and its test.

- [ ] **Step 7: Commit**

```bash
git add PyAitD/app/controls PyAitD/app/config.py PyAitD/app/ui.py PyAitD/app/startup.py PyAitD/app/shell.py tests
git commit -m "refactor(controls): Action vocabulary, bindings and keyboard state in app/controls; Command removed"
```

---

### Task 4: `ControlsState` replaces `InputBuffer`; `PointerState` and the snapshot

**Files:**
- Create: `PyAitD/app/controls/pointer.py` (state and event half only; the decisions come in Task 5), `PyAitD/app/controls/snapshot.py`, `tests/test_controls_snapshot.py`
- Modify: `PyAitD/app/ui.py` (delete `InputBuffer`, `reset_input`, `configure_input`, `event_to_input`, `DOUBLE_PRESS_TICKS`), `PyAitD/app/shell.py` (every `input_buffer` becomes `controls`; `_play_input` deleted), `PyAitD/engine/script/playworld/tick.py` (nothing), `tools/prove_intro.py` (nothing further)
- Test: `tests/test_ui_input.py` → renamed `tests/test_controls_pointer_state.py`; `tests/test_runtime_modes.py`, `tests/test_play_loop.py`, `tests/test_mouse_only.py`, `tests/test_shell_journeys.py`, `tests/test_game_over.py`, `tests/test_main.py`, `tests/test_ui_mouse.py` (field renames)

**Interfaces:**
- Produces: `controls.pointer.PointerState(held=False, touch=False, pos=None, follow_last=None, follow_pos=None, follow_camera=None, settle_origin=None, spent=False, run=False, last_press_tick=None, resume_last=None, resume_pos=None)`; `press(state, pos, touch)`, `move(state, pos, touch)`, `release(state)`, `reset_pointer(state)`; constants `DOUBLE_PRESS_TICKS = 25`, `DOUBLE_PRESS_RESUME_PX = 6`, `CUT_DEAD_ZONE_PX = 6`.
- Produces: `controls.snapshot.ControlsState(keyboard=KeyboardState(), pointer=PointerState(), focused=True)`; `feed_event(controls, event, logical_pos=None) -> bool` (False on QUIT, today's `event_to_input`); `build_play_input(controls) -> PlayInput` (consumes the pulse; spec §5 wrote `build_play_input(controls, game)`, but `game` has no role since the attack latch lives on `Game` and is read by the engine, so the parameter is dropped); `reset(controls, game)` (both states plus `clear_mouse_attack(game)`; `game=None` allowed for callers with no game); `configure(controls, settings)`.
- Field spelling map, old `InputBuffer` → new: `pointer_held` → `pointer.held`, `pointer_touch` → `pointer.touch`, `pointer_pos` → `pointer.pos`, `follow_last/follow_pos/follow_camera` → `pointer.follow_last/follow_pos/follow_camera`, `follow_settle_origin` → `pointer.settle_origin`, `follow_spent` → `pointer.spent`, `pointer_run` → `pointer.run`, `last_press_tick/resume_last/resume_pos` → `pointer.last_press_tick/resume_last/resume_pos`, `held_joyd/action_held/action_pulse/sticky_action/sticky_armed` → `keyboard.*`, `commands` → `keyboard.queue`, `bindings` → `keyboard.table`, `focused` → `focused`.

- [ ] **Step 1: Write the failing tests**

`tests/test_controls_snapshot.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
from collections import deque

import pygame
import pytest

from PyAitD.app.config import Settings, default_settings, replace_binding
from PyAitD.app.controls.actions import Action
from PyAitD.app.controls.keyboard import KeyboardState
from PyAitD.app.controls.pointer import PointerState
from PyAitD.app.controls.snapshot import (
    ControlsState, build_play_input, configure, feed_event, reset,
)
from PyAitD.engine.script.playworld import IDLE, PlayInput

pytestmark = pytest.mark.shell


def test_an_untouched_controls_state_snapshots_to_idle():
    assert build_play_input(ControlsState()) == IDLE


def test_the_snapshot_copies_the_five_engine_fields_and_consumes_the_pulse():
    controls = ControlsState(
        keyboard=KeyboardState(held_joyd=3, action_held=True, action_pulse=True),
        pointer=PointerState(held=True, pos=(1, 2)), focused=False,
    )
    first = build_play_input(controls)
    assert first == PlayInput(joyd=3, action_held=True, action_pulse=True, pointer_held=True, focused=False)
    assert controls.keyboard.action_pulse is False
    assert build_play_input(controls).action_pulse is False


def test_quit_and_focus_flow_through_feed_event():
    controls = ControlsState(keyboard=KeyboardState(held_joyd=1, queue=deque([Action.ACTION])),
                             pointer=PointerState(held=True, pos=(5, 5)))
    assert feed_event(controls, pygame.event.Event(pygame.WINDOWFOCUSLOST)) is True
    assert (controls.focused, controls.keyboard.held_joyd, list(controls.keyboard.queue)) == (False, 0, [])
    assert (controls.pointer.held, controls.pointer.pos) == (False, None)
    assert feed_event(controls, pygame.event.Event(pygame.WINDOWFOCUSGAINED)) is True
    assert controls.focused is True
    assert feed_event(controls, pygame.event.Event(pygame.QUIT)) is False


@pytest.mark.parametrize("touch", (False, True), ids=("physical", "touch-origin"))
def test_primary_pointer_events_preserve_provenance_only_while_held(touch):
    controls = ControlsState()
    feed_event(controls, pygame.event.Event(pygame.MOUSEMOTION, touch=touch), (12, 34))
    assert (controls.pointer.held, controls.pointer.touch, controls.pointer.pos) == (False, touch, (12, 34))
    feed_event(controls, pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, touch=touch), (56, 78))
    assert (controls.pointer.held, controls.pointer.touch, controls.pointer.pos) == (True, touch, (56, 78))
    feed_event(controls, pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, touch=touch))
    assert (controls.pointer.held, controls.pointer.touch, controls.pointer.pos) == (False, False, None)


def test_keys_reach_the_keyboard_state_through_feed_event():
    controls = ControlsState()
    feed_event(controls, pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP, repeat=False))
    assert (controls.keyboard.held_joyd, list(controls.keyboard.queue)) == (1, [Action.UP])


def test_configure_compiles_the_table_sets_sticky_and_resets():
    controls = ControlsState(keyboard=KeyboardState(held_joyd=1), pointer=PointerState(held=True, spent=True))
    configure(controls, Settings(replace_binding(default_settings(), Action.UP, "q").bindings, sticky_action=True))
    assert controls.keyboard.table[pygame.K_q] is Action.UP
    assert controls.keyboard.sticky_action is True
    assert (controls.keyboard.held_joyd, controls.pointer.held, controls.pointer.spent) == (0, False, False)


def test_reset_clears_both_states_and_the_game_latch(data_dir, profile):
    from PyAitD.engine.script.game import init_game
    from PyAitD.engine.script.playworld import arm_mouse_attack
    game = init_game(data_dir, profile)
    arm_mouse_attack(game, 7)
    controls = ControlsState(
        keyboard=KeyboardState(held_joyd=9, action_held=True, sticky_armed=True, action_pulse=True),
        pointer=PointerState(held=True, pos=(1, 1), follow_last=(1, 2, 0, -1), follow_pos=(10, 20),
                             follow_camera=2, settle_origin=(10, 10), spent=True, run=True,
                             last_press_tick=7, resume_last=(1, 2, 0, -1), resume_pos=(10, 20)),
    )
    reset(controls, game)
    assert controls.keyboard == KeyboardState()
    assert controls.pointer == PointerState()
    assert (game.mouse_attack_target, game.mouse_attack_ticks) == (None, 0)
    reset(ControlsState(), None)   # callers without a game
```

The `test_reset_clears_...` case pins that a reset ends the hold, the run, and the press clock the next double press would be measured against (`last_press_tick` → None), exactly as `reset_input` does today.

- [ ] **Step 2: Run them to see them fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_controls_snapshot.py -q`
Expected: collection error, no module `PyAitD.app.controls.pointer`.

- [ ] **Step 3: `pointer.py` (state and events) and `snapshot.py`**

`PyAitD/app/controls/pointer.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""The pointer's gesture state and its transitions, pure over PointerState.

Nothing here reads pygame or the game: the pump feeds press/move/release,
and (Task 5) the router asks press_decision/hold_decision what the gesture
means, handing in a resolver for "what is under this pixel".
"""
from dataclasses import dataclass

# How long after a press a second one still reads as a double press, in game
# ticks (50Hz, so 25 is half a second). Deliberately NOT the keyboard's
# tracks.DOUBLE_TAP_TICKS, though the two gestures mean the same thing: a
# double tap on a held movement key is a fast repeat, while a double click is
# one motion of one finger that every desktop times at around half a second
# -- macOS defaults to 500ms. Sharing the keyboard's 10 ticks put the window
# under 180ms, which is quicker than most people can click twice, so the
# gesture almost never fired.
#
# The unit is still game ticks rather than wall-clock milliseconds, because
# the tick clock stops while a modal has the game paused: a press before the
# inventory and one after it are never a double press, however long the
# player spent in there.
DOUBLE_PRESS_TICKS = 25
# how far the pointer may drift between the two halves of a double press and
# still resume the first half's destination
DOUBLE_PRESS_RESUME_PX = 6
# after a camera cut the pointer must move this far on either axis before a
# held follow re-resolves against the new camera
CUT_DEAD_ZONE_PX = 6


@dataclass
class PointerState:
    held: bool = False
    touch: bool = False
    pos: tuple | None = None
    # Held pointer follow: the last (dest_x, dest_z, room, object_idx) issued
    # as an intent during this hold; re-issued only when the resolution
    # differs, which is also the one-shot latch after an arrival.
    follow_last: tuple | None = None
    # The logical pixel follow_last was resolved at: re-resolve only when the
    # pointer has moved off it. None means "resolve on the next frame
    # regardless" -- what a floor change leaves behind.
    follow_pos: tuple | None = None
    # The camera slot follow_pos was resolved under; a mismatch means a cut.
    follow_camera: int | None = None
    # Where the pointer was when a cut was noticed: motion within
    # CUT_DEAD_ZONE_PX of it is settling, not a gesture.
    settle_origin: tuple | None = None
    # True once this hold's press resolved to attack/inventory/push: no
    # follow resumes on this hold, even after the underlying latch dies.
    spent: bool = False
    # A press within DOUBLE_PRESS_TICKS of the previous one runs.
    run: bool = False
    last_press_tick: int | None = None
    # What the hold that just ended was heading for and the pixel that said
    # so, so the second press of a double press resumes it.
    resume_last: tuple | None = None
    resume_pos: tuple | None = None


def reset_pointer(state):
    state.held = False
    state.touch = False
    state.pos = None
    state.follow_last = None
    state.follow_pos = None
    state.follow_camera = None
    state.settle_origin = None
    state.spent = False
    state.run = False
    state.last_press_tick = None
    state.resume_last = None
    state.resume_pos = None


def press(state, pos, touch=False):
    state.held = True
    state.touch = touch
    state.pos = pos


def move(state, pos, touch=False):
    state.touch = touch
    state.pos = pos


def release(state):
    state.held = False
    state.touch = False
    state.pos = None
```

`PyAitD/app/controls/snapshot.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""The one holder of the app's input state, the pump's event feed, and the
fold into the engine's per-tick PlayInput."""
from dataclasses import dataclass, field

import pygame

from PyAitD.app.controls.bindings import compile_bindings
from PyAitD.app.controls.keyboard import KeyboardState, feed_key_event, reset_keyboard
from PyAitD.app.controls.pointer import PointerState, move, press, release, reset_pointer
from PyAitD.engine.script.playworld import PlayInput, clear_mouse_attack


@dataclass
class ControlsState:
    keyboard: KeyboardState = field(default_factory=KeyboardState)
    pointer: PointerState = field(default_factory=PointerState)
    focused: bool = True


def reset(controls, game):
    """Focus loss, modal takeover, input-mode toggle, restart and hero
    replacement all funnel through here, so an old click can never resume a
    walk or a swing later. `game` may be None for callers that own none."""
    reset_keyboard(controls.keyboard)
    reset_pointer(controls.pointer)
    if game is not None:
        clear_mouse_attack(game)


def configure(controls, settings):
    controls.keyboard.table = compile_bindings(settings)
    controls.keyboard.sticky_action = settings.sticky_action
    reset(controls, None)


def feed_event(controls, event, logical_pos=None):
    """One pygame event into the state. False means QUIT."""
    if event.type == pygame.QUIT:
        return False
    if event.type == pygame.WINDOWFOCUSLOST:
        reset(controls, None)
        controls.focused = False
        return True
    if event.type == pygame.WINDOWFOCUSGAINED:
        controls.focused = True
        return True
    if event.type == pygame.MOUSEMOTION:
        move(controls.pointer, logical_pos, bool(getattr(event, "touch", False)))
        return True
    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
        press(controls.pointer, logical_pos, bool(getattr(event, "touch", False)))
        return True
    if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
        release(controls.pointer)
        return True
    feed_key_event(controls.keyboard, event)
    return True


def build_play_input(controls):
    """The engine's snapshot for one tick. Consumes the sticky pulse: the
    engine no longer writes back into its input, and a pulse raised while a
    modal is open must still fire on the first play tick after it, so it is
    cleared here and nowhere else."""
    keyboard = controls.keyboard
    snapshot = PlayInput(
        joyd=keyboard.held_joyd,
        action_held=keyboard.action_held,
        action_pulse=keyboard.action_pulse,
        pointer_held=controls.pointer.held,
        focused=controls.focused,
    )
    keyboard.action_pulse = False
    return snapshot
```

Note `feed_event` on focus loss calls `reset(controls, None)`: the game latch is cleared by the shell's `_cancel_pointer_invalidation` (Task 2) on the same event, as today.

- [ ] **Step 4: Replace `InputBuffer` in the shell**

In `PyAitD/app/shell.py`:
- Imports: drop `InputBuffer`, `configure_input`, `reset_input`, `event_to_input` from the `ui` import; add `from PyAitD.app.controls.snapshot import ControlsState, build_play_input, configure, feed_event, reset` and `from PyAitD.app.controls.pointer import CUT_DEAD_ZONE_PX, DOUBLE_PRESS_RESUME_PX, DOUBLE_PRESS_TICKS` (delete the three module constants from `shell.py`; `ui.DOUBLE_PRESS_TICKS` is deleted too).
- Rename every `input_buffer` parameter/local to `controls` (`sed -i '' 's/input_buffer/controls/g' PyAitD/app/shell.py` is safe: the name appears nowhere else in that file), then apply the field spelling map from Interfaces to every `controls.<old field>` (`grep -n "controls\.\(pointer_\|follow_\|held_joyd\|action_\|sticky\|commands\|bindings\|last_press\|resume_\)" PyAitD/app/shell.py` lists them; there are about forty).
- `configure_session_input(session, controls)`: `configure(controls, session.settings)` in both places.
- `_play_input` (Task 2) is deleted; `run` calls `play_tick(game, floor, build_play_input(controls))`.
- `run`: `controls = ControlsState()`; `running = feed_event(event, ...)` → `running = feed_event(controls, event, logical_pos) and running`; `input_buffer.bindings.get(event.key)` → `controls.keyboard.table.get(event.key)`; `if input_buffer.commands:` / `popleft()` → `controls.keyboard.queue`; `hover = controls.pointer.pos`.
- Every `reset_input(controls)` → `reset(controls, game)` where a game is in scope (`_take_over_play_input`, `route_command`'s TOGGLE branch, `_apply_startup_result`, `_apply_system_result`). In `_apply_system_result` tests pass `object()` as the game, so that one is `reset(controls, None)` (the latch was cleared when the menu opened). The explicit `clear_mouse_attack(game)` calls Task 2 added next to `reset_input` become redundant where `reset(controls, game)` now runs; remove the duplicates, keep the one in `_cancel_pointer_invalidation`.
- `_load_branch`, `_boot_hero`, `_restart_branch`: `controls = ControlsState()` + `configure_session_input(...)`.
- `_render_play_cursor`: `held=controls.pointer.held`, `settling=controls.pointer.settle_origin is not None`.

In `PyAitD/app/ui.py`: delete `InputBuffer`, `reset_input`, `configure_input`, `event_to_input`, `DOUBLE_PRESS_TICKS`, the `deque` import if unused, and the `KeyboardState`/`feed_key_event`/`reset_keyboard`/`compile_bindings` imports added in Task 3 if nothing else in `ui.py` uses them.

- [ ] **Step 5: Test renames**

- `git mv tests/test_ui_input.py tests/test_controls_pointer_state.py`; rewrite its remaining tests against `ControlsState`/`PointerState` (the pointer provenance test is now in `test_controls_snapshot.py`, so delete it here; keep `test_reset_input_clears_the_follow_latch` and `test_reset_input_clears_the_cut_settle_state` as `reset_pointer` tests on `PointerState`, and `test_keyup_and_focus_loss_release_controls_without_new_command` as a `feed_event` test).
- In every test file: `from PyAitD.app.ui import InputBuffer` → `from PyAitD.app.controls.snapshot import ControlsState`; `InputBuffer()` → `ControlsState()`; `InputBuffer(keyboard=KeyboardState(...))` → `ControlsState(keyboard=KeyboardState(...))`; `InputBuffer(pointer_held=True, pointer_pos=(150, 100), ...)` → `ControlsState(pointer=PointerState(held=True, pos=(150, 100)), ...)`; attribute reads/writes per the spelling map (`buffer.pointer_held` → `buffer.pointer.held`, `buffer.commands` → `buffer.keyboard.queue`, `buffer.follow_spent` → `buffer.pointer.spent`, and so on). `monkeypatch.setattr(main, "InputBuffer", lambda: input_buffer)` → `monkeypatch.setattr(main, "ControlsState", lambda: controls)`. `reset_input(state)` → `reset(state, None)`; `configure_input(state, settings)` → `configure(state, settings)`; `event_to_input(event, state, pos)` → `feed_event(state, event, pos)`.
- `tests/test_runtime_modes.py` asserts `isinstance(new_buffer, InputBuffer) and new_buffer.bindings is not None` → `isinstance(new_controls, ControlsState) and new_controls.keyboard.table is not None`.
- No expected value changes anywhere. If a test cannot be expressed by renaming alone, stop and report it.

- [ ] **Step 6: Run everything**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_controls_snapshot.py tests/test_controls_pointer_state.py tests/test_runtime_modes.py tests/test_play_loop.py -q`, then `make test`.
Expected: green; golden unchanged. `grep -rn "InputBuffer\|reset_input\|configure_input\|event_to_input" PyAitD tests tools --include='*.py'` finds nothing.

- [ ] **Step 7: Commit**

```bash
git add PyAitD/app tests tools
git commit -m "refactor(controls): ControlsState with KeyboardState and PointerState replaces InputBuffer; the snapshot builds PlayInput"
```

---

### Task 5: The pointer gesture machine — pure decisions with unit tests

The press half of `route_play_click` (with `_stamp_press` and `_resume_destination`), the hold half of `follow_pointer`, and `_cancel_follow`/`_drop_destination`/`_rebase_follow`'s state work become pure functions over `PointerState`. The shell functions keep their names and signatures in this task and become thin adapters (they move to the router in Task 6). No test outside the new unit file changes.

**Files:**
- Modify: `PyAitD/app/controls/pointer.py`, `PyAitD/app/shell.py` (`route_play_click`, `_resume_destination`, `_stamp_press`, `follow_pointer`, `_drop_destination`, `_cancel_follow`, `_rebase_follow`)
- Test: create `tests/test_controls_pointer.py`

**Interfaces:**
- Produces, in `controls.pointer`: decision types `Nothing`, `Issue(kind: str, payload: tuple, run: bool)`, `Cancel`, `OpenInventory`, `Attack(target: int)` (frozen dataclasses; singletons `NOTHING`, `CANCEL`, `OPEN_INVENTORY`); `press_decision(state, *, tick, pos, camera, resolve, latched_push) -> decision`; `hold_decision(state, *, pos, camera, resolve, latched_push, intent_alive) -> decision`; `end_hold(state, *, steering)`; `drop_destination(state)`; `rebase(state)`.
- `resolve(pos)` returns today's `(kind, payload)` with kind in `inventory | attack | target | push | walk | steer | blocked`.
- The spec's `Resume(payload, run)` is folded into `Issue`: a resumed press is an `Issue` carrying the stashed payload. Nothing downstream needed to tell them apart.

- [ ] **Step 1: Write the failing tests**

`tests/test_controls_pointer.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""The hold-follow, double-press and cut-settling rules, each as a unit test
over PointerState with a fake resolver -- the shape the mouse bugs so far
("hold does not walk", "the run window swallowed clicks", "an unreachable
pixel refused") should have been reproduced in."""
import pytest

from PyAitD.app.controls.pointer import (
    CANCEL, CUT_DEAD_ZONE_PX, DOUBLE_PRESS_RESUME_PX, DOUBLE_PRESS_TICKS, NOTHING,
    OPEN_INVENTORY, Attack, Issue, PointerState, drop_destination, end_hold,
    hold_decision, press, press_decision, rebase, release,
)

pytestmark = pytest.mark.shell

WALK_A = (1000, 2000, 0, -1)
WALK_B = (1500, 2500, 0, -1)
TARGET = (300, 400, 0, 13)
PUSH = (300, 400, 0, 4)
STEER = (9000, 9000, 0, -1)


def resolver(table):
    """pixel -> (kind, payload); anything unlisted is blocked."""
    return lambda pos: table.get(pos, ("blocked", None))


def _held(pos, **fields):
    state = PointerState(**fields)
    press(state, pos)
    return state


def test_a_walk_press_issues_and_opens_the_follow():
    state = _held((10, 10))
    decision = press_decision(state, tick=100, pos=(10, 10), camera=2,
                              resolve=resolver({(10, 10): ("walk", WALK_A)}), latched_push=False)
    assert decision == Issue("walk", WALK_A, False)
    assert (state.follow_last, state.follow_pos, state.follow_camera) == (WALK_A, (10, 10), 2)
    assert (state.spent, state.run, state.last_press_tick, state.settle_origin) == (False, False, 100, None)


def test_a_blocked_press_does_nothing_but_still_stamps_the_press_clock():
    state = _held((10, 10))
    assert press_decision(state, tick=100, pos=(10, 10), camera=2, resolve=resolver({}), latched_push=False) is NOTHING
    assert (state.last_press_tick, state.follow_last) == (100, None)


def test_inventory_and_attack_presses_spend_the_hold():
    state = _held((10, 10))
    assert press_decision(state, tick=1, pos=(10, 10), camera=0,
                          resolve=resolver({(10, 10): ("inventory", None)}), latched_push=False) is OPEN_INVENTORY
    assert state.spent is True
    state = _held((10, 10))
    assert press_decision(state, tick=1, pos=(10, 10), camera=0,
                          resolve=resolver({(10, 10): ("attack", 7)}), latched_push=False) == Attack(7)
    assert (state.spent, state.follow_last) == (True, None)


def test_a_push_press_latches_without_a_follow_and_spends_the_hold():
    state = _held((10, 10))
    assert press_decision(state, tick=1, pos=(10, 10), camera=0,
                          resolve=resolver({(10, 10): ("push", PUSH)}), latched_push=False) == Issue("push", PUSH, False)
    assert (state.follow_last, state.follow_pos, state.follow_camera, state.spent) == (None, None, None, True)


def test_a_press_while_a_push_is_latched_is_ignored():
    state = _held((10, 10))
    assert press_decision(state, tick=1, pos=(10, 10), camera=0,
                          resolve=resolver({(10, 10): ("walk", WALK_A)}), latched_push=True) is NOTHING


def test_the_second_press_within_the_window_runs_and_resumes_the_first_destination():
    state = _held((10, 10))
    press_decision(state, tick=100, pos=(10, 10), camera=0, resolve=resolver({(10, 10): ("walk", WALK_A)}), latched_push=False)
    release(state)
    end_hold(state, steering=False)
    assert (state.resume_last, state.resume_pos, state.follow_last) == (WALK_A, (10, 10), None)
    drift = (10 + DOUBLE_PRESS_RESUME_PX, 10)
    press(state, drift)
    # the drifted pixel would resolve elsewhere; the resume wins
    decision = press_decision(state, tick=100 + DOUBLE_PRESS_TICKS - 1, pos=drift, camera=0,
                              resolve=resolver({drift: ("walk", WALK_B)}), latched_push=False)
    assert decision == Issue("walk", WALK_A, True)
    assert state.run is True


def test_a_press_outside_the_window_or_too_far_picks_afresh():
    state = _held((10, 10))
    press_decision(state, tick=100, pos=(10, 10), camera=0, resolve=resolver({(10, 10): ("walk", WALK_A)}), latched_push=False)
    release(state)
    end_hold(state, steering=False)
    far = (10 + DOUBLE_PRESS_RESUME_PX + 1, 10)
    press(state, far)
    assert press_decision(state, tick=101, pos=far, camera=0,
                          resolve=resolver({far: ("walk", WALK_B)}), latched_push=False) == Issue("walk", WALK_B, True)
    release(state)
    end_hold(state, steering=False)
    press(state, (10, 10))
    assert press_decision(state, tick=101 + DOUBLE_PRESS_TICKS, pos=(10, 10), camera=0,
                          resolve=resolver({(10, 10): ("walk", WALK_A)}), latched_push=False) == Issue("walk", WALK_A, False)


def test_a_steer_is_never_stashed_for_resume():
    state = _held((10, 10))
    press_decision(state, tick=1, pos=(10, 10), camera=0, resolve=resolver({(10, 10): ("steer", STEER)}), latched_push=False)
    release(state)
    end_hold(state, steering=True)
    assert (state.resume_last, state.resume_pos) == (None, (10, 10))


def test_a_still_pointer_means_what_it_meant_last_frame():
    state = _held((10, 10))
    press_decision(state, tick=1, pos=(10, 10), camera=0, resolve=resolver({(10, 10): ("walk", WALK_A)}), latched_push=False)
    calls = []
    def spy(pos):
        calls.append(pos)
        return ("walk", WALK_B)
    assert hold_decision(state, pos=(10, 10), camera=0, resolve=spy, latched_push=False, intent_alive=True) is NOTHING
    assert calls == []


def test_a_moved_pointer_re_issues_only_when_the_resolution_differs():
    state = _held((10, 10))
    press_decision(state, tick=1, pos=(10, 10), camera=0, resolve=resolver({(10, 10): ("walk", WALK_A)}), latched_push=False)
    same = resolver({(11, 10): ("walk", WALK_A), (40, 40): ("target", TARGET)})
    assert hold_decision(state, pos=(11, 10), camera=0, resolve=same, latched_push=False, intent_alive=True) is NOTHING
    assert state.follow_pos == (11, 10)
    assert hold_decision(state, pos=(40, 40), camera=0, resolve=same, latched_push=False, intent_alive=True) == Issue("target", TARGET, False)
    assert state.follow_last == TARGET


def test_a_blocked_hold_cancels_a_live_intent_once_and_retries_only_after_motion():
    state = _held((10, 10))
    press_decision(state, tick=1, pos=(10, 10), camera=0, resolve=resolver({(10, 10): ("walk", WALK_A)}), latched_push=False)
    assert hold_decision(state, pos=(50, 50), camera=0, resolve=resolver({}), latched_push=False, intent_alive=True) is CANCEL
    assert state.follow_last is None
    assert hold_decision(state, pos=(50, 50), camera=0, resolve=resolver({}), latched_push=False, intent_alive=False) is NOTHING
    assert hold_decision(state, pos=(51, 50), camera=0, resolve=resolver({}), latched_push=False, intent_alive=False) is NOTHING


def test_a_camera_cut_opens_a_dead_zone_the_hand_must_leave():
    state = _held((10, 10))
    press_decision(state, tick=1, pos=(10, 10), camera=0, resolve=resolver({(10, 10): ("walk", WALK_A)}), latched_push=False)
    inside = (10 + CUT_DEAD_ZONE_PX, 10 - CUT_DEAD_ZONE_PX)
    table = resolver({inside: ("walk", WALK_B), (30, 30): ("walk", WALK_B)})
    assert hold_decision(state, pos=inside, camera=3, resolve=table, latched_push=False, intent_alive=True) is NOTHING
    assert (state.settle_origin, state.follow_camera, state.follow_last) == ((10, 10), 0, WALK_A)
    assert hold_decision(state, pos=(30, 30), camera=3, resolve=table, latched_push=False, intent_alive=True) == Issue("walk", WALK_B, False)
    assert (state.settle_origin, state.follow_camera) == (None, 3)


def test_the_hold_keeps_running_while_the_run_belongs_to_it():
    state = PointerState(last_press_tick=90)
    press(state, (10, 10))
    press_decision(state, tick=100, pos=(10, 10), camera=0, resolve=resolver({(10, 10): ("walk", WALK_A)}), latched_push=False)
    assert hold_decision(state, pos=(20, 20), camera=0, resolve=resolver({(20, 20): ("walk", WALK_B)}),
                         latched_push=False, intent_alive=True) == Issue("walk", WALK_B, True)


def test_a_spent_or_released_hold_and_a_latched_push_never_follow():
    spent = _held((10, 10), spent=True)
    assert hold_decision(spent, pos=(20, 20), camera=0, resolve=resolver({(20, 20): ("walk", WALK_A)}), latched_push=False, intent_alive=False) is NOTHING
    released = PointerState(pos=(20, 20))
    assert hold_decision(released, pos=(20, 20), camera=0, resolve=resolver({(20, 20): ("walk", WALK_A)}), latched_push=False, intent_alive=False) is NOTHING
    latched = _held((10, 10))
    assert hold_decision(latched, pos=(20, 20), camera=0, resolve=resolver({(20, 20): ("walk", WALK_A)}), latched_push=True, intent_alive=True) is NOTHING


def test_ending_the_hold_clears_spent_and_run_but_keeps_the_press_clock():
    state = _held((10, 10), spent=True, run=True, last_press_tick=42, follow_last=WALK_A, follow_pos=(10, 10), follow_camera=1, settle_origin=(9, 9))
    end_hold(state, steering=False)
    assert (state.spent, state.run, state.last_press_tick) == (False, False, 42)
    assert (state.follow_last, state.follow_pos, state.follow_camera, state.settle_origin) == (None, None, None, None)
    assert (state.resume_last, state.resume_pos) == (WALK_A, (10, 10))


def test_rebase_drops_the_destination_and_the_stash_but_keeps_the_hold():
    state = _held((10, 10), follow_last=WALK_A, follow_pos=(10, 10), follow_camera=1, resume_last=WALK_B, resume_pos=(3, 3), run=True)
    rebase(state)
    assert (state.held, state.run) == (True, True)
    assert (state.follow_last, state.follow_pos, state.resume_last, state.resume_pos) == (None, None, None, None)
    drop_destination(state)   # idempotent
    assert state.follow_camera is None
```

- [ ] **Step 2: Run them to see them fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_controls_pointer.py -q`
Expected: `ImportError` on `press_decision`.

- [ ] **Step 3: The decisions**

Append to `PyAitD/app/controls/pointer.py`:

```python
@dataclass(frozen=True)
class Nothing:
    pass


@dataclass(frozen=True)
class Cancel:
    pass


@dataclass(frozen=True)
class OpenInventory:
    pass


@dataclass(frozen=True)
class Attack:
    target: int


@dataclass(frozen=True)
class Issue:
    kind: str          # walk | steer | target | push
    payload: tuple     # (dest_x, dest_z, room, object_idx)
    run: bool


NOTHING = Nothing()
CANCEL = Cancel()
OPEN_INVENTORY = OpenInventory()


def _resume_destination(state, pos):
    """The destination this press should reuse, or None to pick afresh.

    The second press of a double press is the same finger on the same spot
    saying "faster", so it resumes what the first press committed to instead
    of resolving again -- a pixel of drift between the two halves of one
    gesture must not choose a different cell. Only a double press (run)
    within DOUBLE_PRESS_RESUME_PX of the first press's pixel resumes.
    """
    if not state.run:
        return None
    last, at = state.resume_last, state.resume_pos
    if last is None or at is None:
        return None
    if (abs(pos[0] - at[0]) > DOUBLE_PRESS_RESUME_PX
            or abs(pos[1] - at[1]) > DOUBLE_PRESS_RESUME_PX):
        return None
    return last


def press_decision(state, *, tick, pos, camera, resolve, latched_push):
    """What a PLAY press means. Every press is stamped against the previous
    one (timed on game ticks, so the window stops while a modal has the game
    paused); then the pixel is resolved and the hold opened or spent."""
    previous = state.last_press_tick
    state.run = previous is not None and tick - previous < DOUBLE_PRESS_TICKS
    state.last_press_tick = tick
    kind, payload = resolve(pos)
    if kind == "inventory":
        # a press resolving to anything but walk/target spends the hold: no
        # resuming a follow after it without a fresh press
        state.spent = True
        return OPEN_INVENTORY
    if kind == "attack":
        # spends the hold whether or not the target is accepted
        state.spent = True
        return Attack(payload)
    if latched_push or kind == "blocked":
        return NOTHING
    if kind != "push":
        resumed = _resume_destination(state, pos)
        if resumed is not None:
            payload = resumed
    is_push = kind == "push"
    # a walk or target press opens a held follow; a push is latched and never
    # re-resolved, so it leaves no latch behind and spends the hold
    state.follow_last = None if is_push else payload
    state.follow_pos = None if is_push else pos
    state.follow_camera = None if is_push else camera
    state.settle_origin = None
    state.spent = is_push
    return Issue(kind, payload, state.run)


def hold_decision(state, *, pos, camera, resolve, latched_push, intent_alive):
    """What a held pointer means this frame: re-aim at whatever it resolves
    to, once per frame in which it moved, surviving camera cuts.

    A pixel means a different world point under every camera, so a still
    pointer is never re-resolved at a cut, and after one the hand must leave
    a CUT_DEAD_ZONE_PX zone around where it was before resolution proceeds
    against the new camera. The resolution is compared against follow_last,
    never the live intent: an unchanged resolution is never re-issued within
    one hold, which is both the arrival one-shot latch and the "a dead click
    is not retried until the pointer moves" rule.
    """
    if not state.held or state.spent or latched_push:
        return NOTHING
    if pos == state.follow_pos:
        return NOTHING
    if state.follow_camera is not None and state.follow_camera != camera:
        if state.settle_origin is None:
            state.settle_origin = state.follow_pos if state.follow_pos is not None else pos
        ox, oy = state.settle_origin
        if abs(pos[0] - ox) <= CUT_DEAD_ZONE_PX and abs(pos[1] - oy) <= CUT_DEAD_ZONE_PX:
            return NOTHING
    # every path that advances follow_camera closes the dead zone with it
    state.settle_origin = None
    state.follow_pos = pos
    state.follow_camera = camera
    kind, payload = resolve(pos)
    if kind in ("walk", "target", "steer"):
        if payload == state.follow_last:
            return NOTHING
        state.follow_last = payload
        # the run belongs to the hold, not to the destination
        return Issue(kind, payload, state.run)
    if kind == "blocked":
        state.follow_last = None
        return CANCEL if intent_alive else NOTHING
    return NOTHING   # inventory, attack and push need a fresh press


def drop_destination(state):
    state.follow_last = None
    state.follow_pos = None
    state.follow_camera = None
    state.settle_origin = None


def end_hold(state, *, steering):
    """Button-up or focus loss: the destination plus everything that belonged
    to the press that opened it. The run goes; last_press_tick survives, it
    is what the next press is measured against. A bearing is never stashed
    for resume: it was taken from where the hero stood at the press."""
    state.spent = False
    state.run = False
    state.resume_last = None if steering else state.follow_last
    state.resume_pos = state.follow_pos
    drop_destination(state)


def rebase(state):
    """A floor change: the destination and the stash index a floor that was
    just unloaded, but the button never came up, so the hold survives."""
    state.resume_last = None
    state.resume_pos = None
    drop_destination(state)
```

- [ ] **Step 4: Run the unit tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_controls_pointer.py -q`
Expected: PASS.

- [ ] **Step 5: The shell functions become adapters**

In `PyAitD/app/shell.py` (import the new names from `PyAitD.app.controls.pointer`):

```python
def route_play_click(game, session, floor, logical_pos, draw_list, controls=None):
    """Route one resolved PLAY click; HUD and world share the resolver."""
    from PyAitD.engine.script.interaction import apply_click_intent, attack_in_hand
    if controls is None:
        # callers that own no controls: resolve and act once, nothing to latch
        kind, payload = resolve_play_click(game, floor, logical_pos, draw_list)
        if kind == "inventory":
            route_command(game, session, Action.INVENTORY_CONFIRM, None)
        elif kind == "attack":
            attack_in_hand(game, payload)
        elif kind not in ("blocked",) and not (game.nav_intent is not None and game.nav_intent.requires_hold):
            dest_x, dest_z, room, object_idx = payload
            apply_click_intent(game, dest_x, dest_z, room, target_object_idx=object_idx,
                               requires_hold=(kind == "push"), run=False, steering=(kind == "steer"))
        return
    intent = game.nav_intent
    decision = press_decision(
        controls.pointer, tick=game.timer, pos=logical_pos, camera=game.num_camera,
        resolve=lambda pos: resolve_play_click(game, floor, pos, draw_list),
        latched_push=intent is not None and intent.requires_hold,
    )
    if decision is OPEN_INVENTORY:
        route_command(game, session, Action.INVENTORY_CONFIRM, controls)
    elif isinstance(decision, Attack):
        # attack_in_hand only validates, stops and faces. The strike itself is
        # published by the fixed-tick input snapshot from the game-owned latch.
        if attack_in_hand(game, decision.target):
            arm_mouse_attack(game, decision.target)
    elif isinstance(decision, Issue):
        dest_x, dest_z, room, object_idx = decision.payload
        apply_click_intent(
            game, dest_x, dest_z, room, target_object_idx=object_idx,
            requires_hold=(decision.kind == "push"), run=decision.run,
            steering=(decision.kind == "steer"),
        )
```

Check the old `route_play_click` for the `controls is None` path before writing the branch above: today `_stamp_press`/`_resume_destination`/the latch writes are all guarded by `input_buffer is not None`, and `run=input_buffer is not None and input_buffer.pointer_run`; the branch reproduces exactly that. If no test or caller passes `None` (grep `route_play_click(` in `tests/` and `PyAitD/`), drop the parameter default and the branch instead.

```python
def follow_pointer(game, session, floor, logical_pos, draw_list, controls):
    from PyAitD.engine.script.interaction import apply_click_intent, cancel_nav_intent
    if (game.active_modal is not None or game.mode is not GameMode.PLAY
            or game.input_mode is not InputMode.MOUSE or session.cutscene
            or game.num_camera == -1 or not controls.focused
            or game.mouse_attack_target is not None):
        return
    intent = game.nav_intent
    decision = hold_decision(
        controls.pointer, pos=logical_pos, camera=game.num_camera,
        resolve=lambda pos: resolve_play_click(game, floor, pos, draw_list),
        latched_push=intent is not None and intent.requires_hold,
        intent_alive=intent is not None,
    )
    if isinstance(decision, Issue):
        dest_x, dest_z, room, object_idx = decision.payload
        apply_click_intent(
            game, dest_x, dest_z, room, target_object_idx=object_idx,
            run=decision.run, steering=(decision.kind == "steer"),
        )
    elif decision is CANCEL:
        cancel_nav_intent(game)


def _drop_destination(game, controls):
    from PyAitD.engine.script.interaction import cancel_nav_intent
    if controls is not None:
        drop_destination(controls.pointer)
    if game.nav_intent is None:
        return False
    cancel_nav_intent(game)
    return True


def _cancel_follow(game, controls):
    if controls is not None:
        steered = game.nav_intent is not None and game.nav_intent.steering
        end_hold(controls.pointer, steering=steered)
    return _drop_destination(game, controls)


def _rebase_follow(game, controls):
    if controls is not None:
        rebase(controls.pointer)
    return _drop_destination(game, controls)
```

Delete `_stamp_press` and `_resume_destination` from `shell.py`. Keep every docstring's substance by moving it onto the pointer functions (done in Step 3); the adapters carry one-line docstrings.

- [ ] **Step 6: Everything, and the golden**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_controls_pointer.py tests/test_mouse_only.py tests/test_play_loop.py tests/test_runtime_modes.py tests/test_controls_golden.py -q`, then `make test`.
Expected: green, golden unchanged. This is the step most likely to surface a real divergence: if the golden differs, diff the JSON to find the first tick and compare the adapter against the pre-Task-5 function in `git show HEAD:PyAitD/app/shell.py` before touching the decisions.

- [ ] **Step 7: Commit**

```bash
git add PyAitD/app/controls/pointer.py PyAitD/app/shell.py tests/test_controls_pointer.py
git commit -m "refactor(controls): the pointer gesture machine as pure decisions over PointerState"
```

---

### Task 6: `modals.py` and `router.py` — the reducers, hit tests and routing leave `ui.py` and `shell.py`

A move. Function bodies do not change except for import paths and the `controls` parameter name already in place.

**Files:**
- Create: `PyAitD/app/controls/modals.py`, `PyAitD/app/controls/router.py`
- Modify: `PyAitD/app/ui.py`, `PyAitD/app/shell.py`, `PyAitD/app/controls/__init__.py` (docstring only), `tools/*.py` if any import the moved names
- Test: `tests/test_ui_reducers.py` → `git mv` to `tests/test_controls_modals.py`; `tests/test_ui_mouse.py`, `tests/test_runtime_modes.py`, `tests/test_mouse_only.py`, `tests/test_play_loop.py`, `tests/test_shell_journeys.py`, `tests/test_game_over.py`, `tests/test_main.py`, `tests/test_startup.py` (import paths)

**Interfaces:**
- Produces `controls.modals`: `reduce_found`, `reduce_inventory`, `reduce_reading`, `turn_page`, `reduce_character_select`, `reduce_system_menu`, `capture_system_key`, `pick_system_key`, `hit_test_found`, `hit_test_character`, `hit_test_system_menu`, `hit_test_settings_notice`, `hit_test_inventory`, `hit_test_reading`, `visible_start`, and the constants they use that are not layouts (`MAIN_ROW_LABELS`, `SAVE_ROW_LABELS`, `LOAD_ROW_LABELS`, `PICKABLE_KEYS`, `PICKABLE_KEY_LABELS`, `GRAPHICS_CYCLES`, `REALISM_CYCLES`, `GRAPHICS_ROWS`, `REALISM_ROWS`, `_leave_graphics`, `_leave_realism`). Ruling on what moves: `ui.py` must not import `controls`, so the labels, `PICKABLE_*`, `GRAPHICS_CYCLES`, `REALISM_CYCLES`, `GRAPHICS_ROWS`, `REALISM_ROWS`, `config_row_count`, `graphics_row_count`, `realism_row_count` and `visible_start` stay in `ui.py` (they are drawn) and `modals.py` imports them from `ui`. Only the reducers, `capture_system_key`, `pick_system_key`, `_leave_graphics`, `_leave_realism` and the `hit_test_*` functions move.
- Produces `controls.router`: unchanged signatures for `inventory_hud_available(game)`, `resolve_play_click(game, floor, logical_pos, draw_list)`, `route_play_click(game, session, floor, logical_pos, draw_list, controls)`, `follow_pointer(game, session, floor, logical_pos, draw_list, controls)`, `route_command(game, session, action, controls=None, renderer=None)`, `route_mouse(game, session, logical_pos, controls=None, renderer=None)`, `route_hover(game, session, logical_pos)`, `cancel_pointer_invalidation(game, event, controls)`, `cancel_follow(game, controls)`, `rebase_follow(game, controls)`, `drop_destination(game, controls)`, `take_over_play_input(game, session, controls)`, `apply_system_result(game, session, controls, result, renderer=None)`, `apply_startup_result(game, session, controls, result)`, `route_game_over_command(game, session, action)`, `game_over_ready(session, effect)`, `inventory_view(game, session)`, `is_interactable(game, actor_idx)`, `pointer_actor_targets(game, draw_list, hero_idx)`, `expand_actor_targets(targets, *, pad=2, minimum=12)`, `steer(game, floor, logical_pos, hero)`, plus the menu policy they call: `available_slots(session)`, `save_session_settings(session)`, `persisted_render(session)`, `write_save(game, session, kind)`, `manual_save(game, session, kind)`, `request_quick_save(session)`, `request_load(game, session, kind)`, `open_startup_menu(game, session)`, `credits_entry(game)`, `continue_available(session)`. Leading underscores are dropped on the way (they are the package's public seam now); `shell.py` imports what it still needs (`inventory_hud_available`, `resolve_play_click`, `route_play_click`, `follow_pointer`, `route_command`, `route_mouse`, `route_hover`, `cancel_pointer_invalidation`, `rebase_follow`, `take_over_play_input`, `apply_system_result`, `write_save`, `open_startup_menu`, `continue_available`, `credits_entry`) from `PyAitD.app.controls.router`.
- `shell.py` keeps `_capture_keydown` (calls `router.apply_system_result` and `bindings.canonical_key_name`), `_commit_quick_save` (calls `router.write_save`), `_load_branch`, `_boot_hero`, the branches, `render_active_mode`, `_render_play_cursor`, `run`, `main`.

- [ ] **Step 1: Move the modal reducers and hit tests**

Create `PyAitD/app/controls/modals.py` with the SPDX line, a docstring ("Modal input reducers and hit tests: what a key or a click does to a presenter. Drawing stays in app.ui."), and these imports:

```python
from dataclasses import replace

from PyAitD.app.config import REMAPPABLE_CONTROLS, replace_binding
from PyAitD.app.controls.actions import Action
from PyAitD.app.ui import (
    GRAPHICS_CYCLES, LOAD_ROW_LABELS, MAIN_ROW_LABELS, PICKABLE_KEYS, REALISM_CYCLES,
    SAVE_ROW_LABELS, CharacterLayout, CharacterPhase, CharacterSelectResult,
    InventoryResult, ModalLayout, ReadingResult, SettingsNoticeLayout,
    SystemMenuLayout, SystemMenuPage, SystemMenuResult, config_row_count,
    graphics_row_count, realism_row_count, visible_start,
)
from PyAitD.engine.script.effects import FoundResult
```

Cut from `ui.py` and paste unchanged: `reduce_found`, `reduce_inventory`, `turn_page`, `reduce_reading`, `reduce_character_select`, `_leave_graphics`, `_leave_realism`, `reduce_system_menu`, `capture_system_key`, `pick_system_key`, `hit_test_found`, `hit_test_character`, `hit_test_system_menu`, `hit_test_settings_notice`, `hit_test_inventory`, `hit_test_reading`. `capture_system_key` used `Control[control]`; write `Action[control]`. Remove from `ui.py` the imports those functions alone used (`replace_binding`, `REMAPPABLE_CONTROLS`, `Action`, `replace` if unused). `ui.py` must import nothing from `PyAitD.app.controls` afterwards (`grep -n controls PyAitD/app/ui.py`).

- [ ] **Step 2: Move the router**

Create `PyAitD/app/controls/router.py` with the SPDX line and a docstring ("Mode and modal dispatch: actions from the keyboard queue, clicks and hovers, and the held pointer, into engine calls and presenter reducers. The shell's pump calls in; nothing here draws."). Move the functions listed in Interfaces from `shell.py`, dropping leading underscores, keeping bodies. Module-level imports it needs (everything the moved functions imported at module level in `shell.py`, minus render): `pygame`; `Action`; the pointer decision names; `PlayLayout` and the presenter/result/page names from `ui`; `modals` names; `config` (`default_settings`, `settings_payload`, `save_settings`, `validate_settings`? only if `save_session_settings`/`request_load` use them — check each moved function's names with `grep`); `PyAitD.engine.script.effects` (`GameMode`, `InputMode`, `ChooseCharacter`, `OpenStartupMenu`, `ShowTitle`); `PyAitD.engine.nav.navmesh` (`agent_extent`, `approach_cell`, `nearest_walkable`, `snap_accept`, `visible_accept`), `PyAitD.engine.nav.picking` (`pick_actor`, `pick_floor_any_room`, `steer_point`, `viewed_floor_y`), `PyAitD.engine.script.playworld` (`arm_mouse_attack`, `clear_mouse_attack`), `PyAitD.engine.script.save` (`SaveError`, `read_slot`, `snapshot_game`, `write_slot`, whichever `write_save`/`request_load` use), `PyAitD.app.controls.snapshot.reset`, `PyAitD.app.startup` names (lazily, as today). `_MENU_RENDER_FIELDS` moves with `apply_system_result`; `shell.py` re-imports it (tests read `main._MENU_RENDER_FIELDS`) as `from PyAitD.app.controls.router import MENU_RENDER_FIELDS as _MENU_RENDER_FIELDS`.

Then in `shell.py` import the names it still uses from `router` (list in Interfaces) and delete the moved definitions. `run` and the branches call `route_command`, `route_mouse`, `route_hover`, `follow_pointer`, `route_play_click`, `cancel_pointer_invalidation`, `rebase_follow`, `take_over_play_input` by their new names. `_capture_keydown` calls `apply_system_result`. `_commit_quick_save` calls `write_save`. `main` calls `open_startup_menu`/`continue_available` where it did. `run`'s notice-dismiss check imports `hit_test_settings_notice` from `PyAitD.app.controls.modals`.

Check the layering direction by importing: `SDL_VIDEODRIVER=dummy .venv/bin/python -c "import PyAitD.app.controls.router, PyAitD.app.controls.modals, PyAitD.app.ui, PyAitD.app.shell"` must succeed, and `grep -n "PyAitD.app.shell\|PyAitD.render" PyAitD/app/controls/*.py` must find nothing.

- [ ] **Step 3: Test import renames**

- `git mv tests/test_ui_reducers.py tests/test_controls_modals.py`; its `from PyAitD.app.ui import (...)` splits into presenters/results/pages from `ui` and reducers/`capture_system_key` from `PyAitD.app.controls.modals`.
- `tests/test_ui_mouse.py`: `hit_test_*` come from `PyAitD.app.controls.modals`; layouts and presenters stay from `ui`.
- Every `main.follow_pointer` → `router.follow_pointer` with `from PyAitD.app.controls import router` (or `import PyAitD.app.controls.router as router`) at the test's import site; likewise `main._cancel_pointer_invalidation` → `router.cancel_pointer_invalidation`, `main._rebase_follow` → `router.rebase_follow`, `main._cancel_follow` → `router.cancel_follow`, `main.resolve_play_click` → `router.resolve_play_click`, `main._take_over_play_input` → `router.take_over_play_input`; `from PyAitD.app.shell import route_command, route_mouse, route_hover, resolve_play_click, _apply_system_result, ...` → the same names (underscore dropped) from `PyAitD.app.controls.router`. A test that monkeypatches one of the moved names on `main` (`monkeypatch.setattr(main, "route_command", ...)`) must patch it on `router` instead, since `run` now resolves it through the `router` module import... it does not: `shell.py` imports the names into its namespace with `from ... import`, so `monkeypatch.setattr(main, "route_command", fake)` keeps working for `run`. Patch on `main` for `run`-level tests, on `router` for tests calling router functions directly.
- `grep -rn "main\._\(cancel\|rebase\|take_over\|apply_system\|apply_startup\|route_game\|game_over_ready\|inventory_view\|is_interactable\|steer\|drop_destination\|available_slots\|save_session\|persisted_render\|write_save\|manual_save\|request_\)" tests tools` must find nothing afterwards.
- `tools/prove_mouse.py`, `tools/prove_combat.py`, `tools/compare_original.py`: `grep -n "from PyAitD.app.shell import\|shell\." tools/*.py`; repoint any moved name.

- [ ] **Step 4: Everything, and the golden**

Run: `make test`
Expected: green; golden unchanged. `wc -l PyAitD/app/shell.py` should be roughly 1,100.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/app tests tools
git commit -m "refactor(controls): modal reducers and hit tests in controls/modals; routing in controls/router"
```

---

### Task 7: `cursor.py`, the shell trim, layering pins, docs, golden re-pin

**Files:**
- Create: `PyAitD/app/controls/cursor.py`
- Modify: `PyAitD/app/shell.py` (`_render_play_cursor` calls `cursor`; the eight cursor helpers deleted), `PyAitD/app/controls/__init__.py` (docstring lists the modules), `tests/test_layering.py`, `CONTEXT.md` (file map rows + "M4a1 shell boundary" rewrite), `AGENTS.md` (package layout), `README.md` (nothing)
- Test: `tests/test_layering.py`, the tests calling `main._intent_marker`/`main._play_cursor_state`/`main._play_cursor_kind`/`main._marker_for`/`main._render_play_cursor` (`tests/test_mouse_only.py`, `tests/test_play_loop.py`)

**Interfaces:**
- Produces `controls.cursor`: `hit_actor_ids(game)`, `hit_feedback_rects(game, draw_list, actor_ids)`, `cursor_state(game, floor, hover, draw_list, pointer)`, `cursor_kind(...)`, `marker_for(game, floor, payload)`, `intent_marker(game, floor)`; bodies moved from `shell.py` unchanged except `input_buffer.pointer_held` → `pointer.held`. `cursor` imports `router` for `resolve_play_click`; `router` never imports `cursor`.
- `shell._render_play_cursor(game, floor, hover, draw_list, controls, painter)` stays in the shell (it draws) and calls `cursor_state`/`intent_marker`/`marker_for`.

- [ ] **Step 1: Write the failing layering tests**

Append to `tests/test_layering.py` (the `FORBIDDEN` dict gains one row; the rest are new tests):

```python
    "app/controls": ("PyAitD.app.shell", "PyAitD.render"),
```

```python
def test_ui_never_imports_controls_so_the_dependency_runs_one_way():
    # controls reduces and routes; ui draws. controls may import ui's
    # presenters, results and layouts, so ui importing controls back would
    # be a cycle waiting to happen.
    bad = [name for name in _imports(ROOT / "app" / "ui.py") if name.startswith("PyAitD.app.controls")]
    assert not bad, bad


def test_the_shell_holds_no_key_codes_and_no_pointer_state():
    # the spec's "done when": every key code lives in controls.bindings and
    # every gesture field in controls.pointer; the shell only pumps.
    source = (ROOT / "app" / "shell.py").read_text()
    assert "pygame.K_" not in source
    for field in ("follow_last", "follow_pos", "settle_origin", "resume_last", "last_press_tick", ".spent"):
        assert field not in source, field


def test_nothing_outside_controls_reads_a_pygame_key_code_at_runtime():
    # startup and ui draw key *names*; only controls.bindings maps codes
    offenders = [
        str(path.relative_to(ROOT))
        for path in _modules("app")
        if "controls" not in path.parts and "pygame.K_" in path.read_text()
    ]
    assert offenders == [], offenders
```

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_layering.py -q`
Expected: `test_the_shell_holds_no_key_codes_and_no_pointer_state` fails (the mirror block in `run` and `_render_play_cursor` still read pointer fields); the `app/controls` row passes; check whether `test_nothing_outside_controls_reads_a_pygame_key_code_at_runtime` fails on `startup.py` or `ui.py` — if it does, those uses are `pygame.K_ESCAPE`-style constants in a key picker; keep the test and route them through `bindings.canonical_key_name` names (strings), which is what the picker stores anyway. If that turns out to need behaviour changes, delete this third test and note it in the report rather than changing behaviour.

- [ ] **Step 2: `cursor.py` and the shell trim**

Create `PyAitD/app/controls/cursor.py` (SPDX line; docstring "What the PLAY cursor should show: the resolver's kind for the hovered pixel, the live destination and the press preview, projected on screen. Drawing is app.ui.render_cursor.") and move `_hit_actor_ids`, `_hit_feedback_rects`, `_play_cursor_state`, `_play_cursor_kind`, `_marker_for`, `_intent_marker` from `shell.py`, dropping the underscores, with `pointer` as the last parameter of `cursor_state`/`cursor_kind` (`pointer.held`). Imports: `pygame` (for `Rect`), `GameMode` from effects, `resolve_play_click` from `router`, and the picking names inside `marker_for` as today.

In `shell.py`: import `cursor_state, hit_actor_ids, hit_feedback_rects, intent_marker, marker_for` from `PyAitD.app.controls.cursor`; `_render_play_cursor` becomes

```python
def _render_play_cursor(game, floor, hover, draw_list, controls, painter):
    kind, payload = cursor_state(game, floor, hover, draw_list, controls.pointer)
    destination = intent_marker(game, floor)
    preview = None
    if not controls.pointer.held and destination is None and kind in ("walk", "target"):
        preview = marker_for(game, floor, payload)
    render_cursor(
        painter, hover, kind, held=controls.pointer.held,
        settling=controls.pointer.settle_origin is not None,
        destination=destination, preview=preview,
    )
```

That still names `settle_origin` in the shell. Add `def settling(state): return state.settle_origin is not None` to `pointer.py` and call it; then the layering test's field list holds. The mirror block in `run` reads `controls.keyboard.table.get(event.key)`: fine (no `pygame.K_`).

Test renames: `main._intent_marker` → `cursor.intent_marker`, `main._play_cursor_state` → `cursor.cursor_state(..., controls.pointer)`, `main._play_cursor_kind` → `cursor.cursor_kind(..., controls.pointer)`, `main._marker_for` → `cursor.marker_for`; `main._render_play_cursor` keeps its name (still in the shell) but takes `controls`.

- [ ] **Step 3: Docs**

`CONTEXT.md`:
- In the `## Architecture (PyAitD/)` file map, add rows for `app/controls/__init__.py` ("the input package: vocabulary, bindings, keyboard/pointer state, snapshot, modal reducers, routing, cursor"), `app/controls/actions.py`, `bindings.py`, `keyboard.py`, `pointer.py`, `snapshot.py`, `modals.py`, `router.py`, `cursor.py`, one line each from this plan's file map; update the `app/ui.py` and `app/shell.py` rows to say what they no longer own.
- Replace the body of `## M4a1 shell boundary` with:

```
- `app/config.py` owns the pygame-free settings schema (v1: bindings for the
  eight key-bindable `Action`s, CANCEL fixed to Escape, sticky flag), the
  platform settings path, and the atomic store. `config.Control` is
  `controls.actions.Action`.
- `app/controls/` owns everything between a pygame event and the engine:
  `actions` (the fixed vocabulary keys, gestures and packs bind to),
  `bindings` (key names to codes), `keyboard` (held bits, sticky pulse, the
  action queue), `pointer` (hold-follow, double-press run, resume and
  camera-cut settling as pure transitions over `PointerState`), `snapshot`
  (`ControlsState` and the one fold into the engine's frozen `PlayInput`),
  `modals` (presenter reducers and hit tests), `router` (mode and modal
  dispatch into engine calls; the menu result appliers and save/load
  requests), `cursor` (what the PLAY cursor shows). It may import
  `engine`, `config` and `ui`; never `shell` or `render`.
- `engine/script/playworld/input.py` owns `PlayInput` (joyd, action_held,
  action_pulse, pointer_held, focused) and the mouse attack latch on `Game`
  (`arm_mouse_attack`/`clear_mouse_attack`); the engine never sees
  `ControlsState`.
- `app/ui.py` owns the modal presenters and results, the layouts, all shell
  drawing (`UIPainter`, `render_*`, `render_cursor`). It never imports
  `controls`.
- `app/shell.py` owns the application session (`ModalSession` settings
  fields), the persistence policy boundaries (quick-save commit, the load
  replacement), raw remap capture, the event pump and tick accumulator, the
  atomic game/floor/session/controls replacement, and presentation. It holds
  no key codes and no pointer state (`tests/test_layering.py`).
- `Game` owns no settings; settings never enter world state.
- `tests/test_controls_golden.py` replays a recorded event stream through
  the real pump and pins the per-tick engine input and hero motion; a
  behaviour change in controls shows up there first.
```
  Keep the paragraph about `UIPainter`/`screen_surface` from the old section; drop the sentences now false.
- `AGENTS.md`: in `## Package layout`, the `PyAitD/app/` row becomes "Window, the single event pump, settings schema/persistence, CLI, UI screens; `app/controls/` is the input package (vocabulary, bindings, gesture state, routing)"; the "Input, menus, settings, CLI flags → `app/`" bullet becomes "Input → `app/controls/` (actions, bindings, pointer/keyboard state, routing); menus and settings → `app/ui.py`/`app/config.py`; CLI flags → `app/shell.py`". Add one convention bullet: "A mouse or keyboard behaviour change gets a unit test in `tests/test_controls_pointer.py` or `tests/test_controls_keyboard.py` first, and must keep `tests/test_controls_golden.py` byte-identical unless the change is the point, in which case re-record with `PYAITD_RECORD_GOLDEN=1` and say why in the commit."

- [ ] **Step 4: Everything, and the golden one last time**

Run: `make test`
Expected: green; `tests/test_controls_golden.py` unchanged (do **not** re-record). `grep -rn "pygame.K_" PyAitD/app/shell.py` empty; `wc -l PyAitD/app/shell.py PyAitD/app/ui.py` both well under their starting sizes (the shell around 1,000 lines, ui around 1,200).

- [ ] **Step 5: Commit**

```bash
git add PyAitD/app tests CONTEXT.md AGENTS.md
git commit -m "refactor(controls): cursor state in controls/cursor; the shell keeps only the pump; layering pins and docs"
```

---

## Final verification

- `make test` green; `make test-meta` green (layering, SPDX, test grouping).
- `git diff --stat main..HEAD -- tests/golden/controls_events.json` is empty after Task 1's commit.
- `grep -rn "InputBuffer\|Command\b\|event_to_input\|reset_input\|configure_input" PyAitD tests tools --include='*.py'` finds only `mouse_contract.py`'s `LegacyCommandDecision` names.
- `SDL_VIDEODRIVER=dummy .venv/bin/python -c "import PyAitD.app.controls, PyAitD.app.controls.router, PyAitD.app.ui, PyAitD.app.shell, PyAitD.engine.script.playworld"` succeeds cold.
- Manual: `make run floor=0`: hold-to-walk, double-press run, click an object, Tab to keyboard mode and walk, Escape to the menu, remap a key in Configuration, quit; then `make run` again and confirm the remap persisted (settings v1 unchanged).
