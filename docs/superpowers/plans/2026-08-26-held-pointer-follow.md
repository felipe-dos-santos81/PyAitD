# Held Pointer Follow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the left mouse button a held gesture for PLAY movement: while it is down the hero moves toward whatever the pointer resolves to and the destination follows the pointer; release stops the hero immediately; the OS cursor is never locked.

**Architecture:** Tracking lives in the shell (`PyAitD/app/shell.py`): a new `follow_pointer` runs once per frame while the button is held, re-resolves the pointer through the unchanged `resolve_play_click`, and re-issues a `NavIntent` only when the resolution differs from `InputBuffer.follow_last`. The engine (`PyAitD/engine/playworld.py`) enforces the invariant that every intent is hold-bound by cancelling any intent whose buffer is not held and focused. The AITD1 mouse contract declares walk and interact as `left_hold` routes and a `held_pointer_follow` decision.

**Tech Stack:** Python 3, pygame-ce (events only), pytest with `engine`/`shell`/`meta` markers, `make` targets prefixed by `HEADLESS = SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`.

**Spec:** `docs/superpowers/specs/2026-08-26-held-pointer-follow-design.md`

## Global Constraints

- Invariant: under mouse control the hero never moves unless the left button is down. Every navigation intent is hold-bound.
- Never call `pygame.mouse.set_relative_mode`, `pygame.event.set_grab`, or `pygame.mouse.set_pos` anywhere under `PyAitD/`.
- `NavIntent`, `navigate.decide`, `apply_click_intent`, the arrival dispatch, LIFE, collision and animation are not changed. No engine module learns about pointer motion.
- Hold-push is unchanged: target latched at press, pointer motion ignored while it lives; `follow_pointer` never runs while a `requires_hold` intent lives.
- `attack` and `inventory` presses stay one-shot and never start a follow.
- `follow_last` is compared against the resolver's payload, never against the live intent's destination.
- Package layering (`tests/test_layering.py`) stays green: `engine/` imports no pygame/moderngl/render/games/app.
- `ponytail:` comments mark deliberate simplifications; FITD `file:line` citations are never re-guessed.
- Game data under `data/aitd1/**` is never committed. Every test that needs it takes the `data_dir` and `profile` fixtures.
- Run the full suite with `make test` (equivalently `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests/ -q`). Baseline before this plan: 1012 passed, 1 skipped, 1 xfailed.

---

## File structure

| File | Responsibility in this plan |
|---|---|
| `PyAitD/engine/playworld.py` | `_apply_mouse_input`: cancel any intent whose buffer is not held and focused (Task 1) |
| `tests/conftest.py` | `held_pointer(pos=None)` helper for tests that tick a walk (Task 1) |
| `PyAitD/app/ui.py` | `InputBuffer.follow_last` field, cleared by `reset_input` (Task 2) |
| `PyAitD/app/shell.py` | `route_play_click` records `follow_last`; `_cancel_follow` / `_cancel_pointer_invalidation` cancel any intent (Task 2); `follow_pointer` and its per-frame call plus the floor-change cancel in `run` (Task 3) |
| `PyAitD/games/aitd1/mouse_contract.py` | `left_hold` routes for walk/interact, `held_pointer_follow` decision (Task 4) |
| `tests/test_playworld.py` | engine hold-enforcement test; sweep (Task 1) |
| `tests/test_play_loop.py` | shell unit tests for the latch, cancellation and `follow_pointer` (Tasks 1-3) |
| `tests/test_ui_input.py` | `reset_input` clears `follow_last` (Task 2) |
| `tests/test_mouse_only.py` | contract gates (Task 4); held attic journey (Task 5) |
| `tests/test_layering.py` | pointer-freedom grep gate (Task 4) |
| `README.md`, `AGENTS.md`, `CONTEXT.md` | user and agent documentation (Task 5) |

Task order keeps the suite green after every commit: the engine invariant lands first with its test sweep, the shell then records/cancels, then follows, then the contract and docs catch up.

---

### Task 1: Every intent is hold-bound at the tick

**Files:**
- Modify: `PyAitD/engine/playworld.py:307-330` (`_apply_mouse_input`)
- Modify: `tests/conftest.py` (add `held_pointer`)
- Test: `tests/test_playworld.py`
- Modify: `tests/test_playworld.py:66`, `tests/test_playworld.py:480`, `tests/test_playworld.py:676-683`, `tests/test_play_loop.py:1224`

**Interfaces:**
- Consumes: `PyAitD.app.ui.InputBuffer` (`pointer_held`, `focused`, `pointer_pos`), `PyAitD.engine.interaction.cancel_nav_intent(game)`.
- Produces: `tests.conftest.held_pointer(pos=None) -> InputBuffer` — used by every later task's tests that tick a walk.

- [ ] **Step 1: Add the test helper to `tests/conftest.py`**

Append after the `profile` fixture (a plain function, not a fixture, so tests can call it inline):

```python
def held_pointer(pos=None):
    """An InputBuffer with the left button down. Since held pointer follow
    every navigation intent is hold-bound: a test that ticks a walk must hold
    the button, or the next tick cancels the intent (playworld._apply_mouse_input).
    """
    from PyAitD.app.ui import InputBuffer
    return InputBuffer(pointer_held=True, focused=True, pointer_pos=pos)
```

- [ ] **Step 2: Write the failing engine test**

Append to `tests/test_playworld.py` (module already imports `Floor`, `init_game`, `InputBuffer`, `NavIntent`, `apply_play_input` at lines 7-32):

```python
@pytest.mark.parametrize(
    "buf", [InputBuffer(pointer_held=False), InputBuffer(pointer_held=True, focused=False)],
    ids=["released", "unfocused"],
)
def test_an_unheld_or_unfocused_buffer_cancels_a_walk_intent_on_the_next_tick(
        data_dir, profile, buf):
    # Held pointer follow: every intent is hold-bound, plain walks included,
    # and the tick -- where FITD reads input -- enforces it, not only the
    # frame (spec: Engine section).
    game = init_game(data_dir, profile, hero=0)
    game.current_floor_data = Floor(data_dir, game.current_floor, profile)
    hero = game.actors[game.current_camera_target_actor]
    game.nav_intent = NavIntent(
        dest_x=hero.room_x, dest_z=hero.room_z + 9000, room=hero.room,
        waypoints=[(hero.room_x, hero.room_z + 9000)],
    )
    apply_play_input(game, buf)
    assert game.nav_intent is None
    assert (game.nav_decision, game.local_joyd) == (None, 0)
```

- [ ] **Step 3: Run it to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests/test_playworld.py -k "cancels_a_walk_intent_on_the_next_tick" -v`
Expected: both cases FAIL — `game.nav_intent` is still the `NavIntent` (today only `requires_hold` intents are cancelled).

- [ ] **Step 4: Generalise the hold check in `_apply_mouse_input`**

In `PyAitD/engine/playworld.py`, replace

```python
    from PyAitD.engine.interaction import cancel_nav_intent
    if intent.requires_hold and (not input_buffer.focused or not input_buffer.pointer_held):
        cancel_nav_intent(game)
        return
```

with

```python
    from PyAitD.engine.interaction import cancel_nav_intent
    if not input_buffer.focused or not input_buffer.pointer_held:
        # Held pointer follow: every intent is hold-bound, plain walks
        # included. Enforced here, at the tick where FITD reads input, so a
        # release stops the hero on the very next tick, between frames too.
        cancel_nav_intent(game)
        return
```

The push-only `origin_floor` / `origin_room` checks that follow stay push-only.

- [ ] **Step 5: Run the new test to verify it passes**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests/test_playworld.py -k "cancels_a_walk_intent_on_the_next_tick" -v`
Expected: 2 PASS.

- [ ] **Step 6: Sweep the tests that tick a walk with an unheld buffer**

Exactly these four sites (each ticks or applies input with a plain walk intent live):

1. `tests/test_playworld.py:66` in `test_mouse_mode_mirrors_the_follower_joystick`: `apply_play_input(game, InputBuffer())` → `apply_play_input(game, InputBuffer(pointer_held=True))`.
2. `tests/test_playworld.py:480` in `test_hero_walks_to_a_clicked_destination_and_arrives`: `buf = InputBuffer()` → `buf = held_pointer()`; add `from tests.conftest import held_pointer` to the module imports.
3. `tests/test_playworld.py:676-683` in `test_held_push_on_the_rocking_horse_never_wedges_the_hero`: the test releases (`buf.pointer_held = False`) to end the push and then walks the hero with a plain `apply_click_intent`. Insert `buf.pointer_held = True` on the line immediately before `apply_click_intent(game, dest[0], dest[1], hero.room)`.
4. `tests/test_play_loop.py:1224` in `test_clicking_floor_zero_s_interactable_walks_there_and_dispatches`: `buf = InputBuffer()` → `buf = held_pointer()`; add `from tests.conftest import held_pointer` next to the module's other test imports (line 769 area).

- [ ] **Step 7: Run the full suite**

Run: `make test`
Expected: 1014 passed (baseline 1012 + 2), 1 skipped, 1 xfailed. If any other test now fails with a walk intent vanishing after one tick, it ticks a walk with an unheld buffer: replace its `InputBuffer()` with `held_pointer()` and list the site in the commit message.

- [ ] **Step 8: Commit**

```bash
git add PyAitD/engine/playworld.py tests/conftest.py tests/test_playworld.py tests/test_play_loop.py
git commit -m "feat: every navigation intent is hold-bound at the tick"
```

---

### Task 2: The follow latch and release cancellation

**Files:**
- Modify: `PyAitD/app/ui.py:37-56` (`InputBuffer`), `PyAitD/app/ui.py:96-106` (`reset_input`)
- Modify: `PyAitD/app/shell.py:338-378` (`route_play_click`, `_cancel_pointer_invalidation`), `PyAitD/app/shell.py:1105` (the loop's `_cancel_pointer_invalidation` call)
- Test: `tests/test_ui_input.py`, `tests/test_play_loop.py`

**Interfaces:**
- Consumes: `resolve_play_click(game, floor, logical_pos, draw_list) -> (kind, payload)` where a `walk`/`target`/`push` payload is `(dest_x, dest_z, room, object_idx)`.
- Produces: `InputBuffer.follow_last: tuple | None`; `_cancel_follow(game, input_buffer) -> bool`; `_cancel_pointer_invalidation(game, event, input_buffer=None) -> bool`. Task 3's `follow_pointer` reads and writes `follow_last` and Task 3's floor-change site calls `_cancel_follow`.

- [ ] **Step 1: Write the failing `reset_input` test**

Append to `tests/test_ui_input.py`:

```python
def test_reset_input_clears_the_follow_latch():
    # the held pointer follow's latch lives in the buffer so every existing
    # focus, modal and input-mode reset seam clears it for free
    state = InputBuffer(follow_last=(1, 2, 0, -1))
    reset_input(state)
    assert state.follow_last is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests/test_ui_input.py -k follow_latch -v`
Expected: FAIL with `TypeError: InputBuffer.__init__() got an unexpected keyword argument 'follow_last'`.

- [ ] **Step 3: Add the field and clear it**

In `PyAitD/app/ui.py`, after `mouse_attack_ticks: int = 0` inside `InputBuffer`:

```python
    # Held pointer follow: the last (dest_x, dest_z, room, object_idx) the
    # shell issued as an intent during this hold. shell.follow_pointer
    # re-issues only when the resolution differs, which is also the one-shot
    # latch after an arrival. Lives here so every reset_input seam clears it.
    follow_last: tuple | None = None
```

In `reset_input`, after `state.mouse_attack_ticks = 0`:

```python
    state.follow_last = None
```

- [ ] **Step 4: Run it to verify it passes**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests/test_ui_input.py -k follow_latch -v`
Expected: PASS.

- [ ] **Step 5: Write the failing shell tests**

Append to `tests/test_play_loop.py` (after the module-level `_floor_screen_point` helper defined at line 1239; the module already imports `Floor`, `init_game`, `route_play_click`, `InputBuffer`, `ModalSession`):

```python
def test_a_walk_press_records_the_follow_latch(data_dir, profile):
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    screen = _floor_screen_point(game, floor, 1500, 0)
    buf = InputBuffer(pointer_held=True)
    route_play_click(
        game, ModalSession(), floor, (int(screen[0]), int(screen[1])), [], buf,
    )
    intent = game.nav_intent
    assert intent is not None and intent.target_object_idx == -1
    assert buf.follow_last == (intent.dest_x, intent.dest_z, intent.room, -1)


def test_a_push_press_leaves_no_follow_latch(data_dir, profile):
    # a push is latched and never re-resolved, so a stale latch from an
    # earlier walk must not survive into the hold
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    actor_idx = game.world_objects[4].obj_index
    buf = InputBuffer(pointer_held=True, follow_last=(1, 2, 0, -1))
    route_play_click(
        game, ModalSession(), floor, (150, 100),
        [(actor_idx, (100, 60, 200, 160))], buf,
    )
    assert game.nav_intent.requires_hold is True
    assert buf.follow_last is None


def test_pointer_invalidation_cancels_a_plain_walk_intent(data_dir, profile):
    # today only a hold-required push is cancelled on release; every intent
    # is hold-bound now
    import PyAitD.app.shell as main
    from PyAitD.engine.interaction import apply_click_intent

    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    for event in (
        main.pygame.event.Event(main.pygame.MOUSEBUTTONUP, button=1),
        main.pygame.event.Event(main.pygame.WINDOWFOCUSLOST),
    ):
        buf = InputBuffer(pointer_held=True, follow_last=(100, 200, hero.room, -1))
        apply_click_intent(game, 100, 200, hero.room)
        assert main._cancel_pointer_invalidation(game, event, buf) is True
        assert game.nav_intent is None
        assert buf.follow_last is None
    up = main.pygame.event.Event(main.pygame.MOUSEBUTTONUP, button=1)
    assert main._cancel_pointer_invalidation(game, up, InputBuffer()) is False
    assert main._cancel_pointer_invalidation(game, up) is False, "the buffer stays optional"
```

- [ ] **Step 6: Run them to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests/test_play_loop.py -k "follow_latch or cancels_a_plain_walk_intent" -v`
Expected: `records_the_follow_latch` FAILS (`follow_last` is None), `push_press` FAILS (the stale `(1, 2, 0, -1)` latch survives), `cancels_a_plain_walk_intent` FAILS with `TypeError` (unexpected third argument).

- [ ] **Step 7: Record the latch on press and cancel any intent on release**

In `PyAitD/app/shell.py`, `route_play_click`: replace the tail

```python
    dest_x, dest_z, room, object_idx = payload
    apply_click_intent(
        game, dest_x, dest_z, room, target_object_idx=object_idx,
        requires_hold=(kind == "push"),
    )
```

with

```python
    dest_x, dest_z, room, object_idx = payload
    apply_click_intent(
        game, dest_x, dest_z, room, target_object_idx=object_idx,
        requires_hold=(kind == "push"),
    )
    if input_buffer is not None:
        # a walk or target press opens a held pointer follow (follow_pointer
        # compares later resolutions against this); a push is latched and
        # never re-resolved, so it leaves no latch behind
        input_buffer.follow_last = payload if kind != "push" else None
```

Replace `_cancel_pointer_invalidation` entirely:

```python
def _cancel_pointer_invalidation(game, event, input_buffer=None):
    """Button-up and focus loss end the hold, and every intent is hold-bound."""
    invalidated = (
        event.type == pygame.MOUSEBUTTONUP and event.button == 1
    ) or event.type == pygame.WINDOWFOCUSLOST
    if not invalidated:
        return False
    return _cancel_follow(game, input_buffer)


def _cancel_follow(game, input_buffer):
    """Drop any navigation intent and the follow latch. True when an intent
    was live. The buffer is optional only for callers that own no buffer."""
    from PyAitD.engine.interaction import cancel_nav_intent
    if input_buffer is not None:
        input_buffer.follow_last = None
    if game.nav_intent is None:
        return False
    cancel_nav_intent(game)
    return True
```

In `run`, change the loop call `_cancel_pointer_invalidation(game, event)` to `_cancel_pointer_invalidation(game, event, input_buffer)`.

- [ ] **Step 8: Run the tests and the file**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests/test_play_loop.py -q`
Expected: all pass. `test_mouseup_cancels_only_a_hold_required_intent` (line 850) still passes and stays: it pins the engine helper `cancel_held_nav_intent`, which is unchanged; the shell's broader cancellation is the new test above. `test_pointer_invalidation_routes_mouseup_and_focus_loss` (line 862) still passes: the two-argument call keeps working.

- [ ] **Step 9: Run the full suite**

Run: `make test`
Expected: 1018 passed, 1 skipped, 1 xfailed.

- [ ] **Step 10: Commit**

```bash
git add PyAitD/app/ui.py PyAitD/app/shell.py tests/test_ui_input.py tests/test_play_loop.py
git commit -m "feat: follow latch on press, release cancels any navigation intent"
```

---

### Task 3: `follow_pointer` and its per-frame call

**Files:**
- Modify: `PyAitD/app/shell.py` (new `follow_pointer` after `route_play_click`; `run` at lines 1189-1193)
- Test: `tests/test_play_loop.py`

**Interfaces:**
- Consumes: `resolve_play_click`, `apply_click_intent(game, dest_x, dest_z, room, target_object_idx=-1, *, requires_hold=False)`, `cancel_nav_intent(game)`, `InputBuffer.follow_last` / `pointer_held` / `focused` / `mouse_attack_target`, `_cancel_follow(game, input_buffer)` from Task 2, `ModalSession.cutscene`.
- Produces: `follow_pointer(game, session, floor, logical_pos, draw_list, input_buffer) -> None`, exported at module level so tests and the journey can monkeypatch `resolve_play_click` around it.

- [ ] **Step 1: Write the failing unit tests**

Append to `tests/test_play_loop.py`:

```python
def _resolving(monkeypatch, results):
    """Queue (kind, payload) pairs for shell.resolve_play_click; returns the
    queue so a test can assert how many resolutions were consumed."""
    import PyAitD.app.shell as main
    queue = list(results)
    monkeypatch.setattr(main, "resolve_play_click", lambda *args: queue.pop(0))
    return queue


def _follow_fixture(data_dir, profile):
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    hero = game.actors[game.current_camera_target_actor]
    near = (hero.room_x + 1000, hero.room_z, hero.room, -1)
    far = (hero.room_x + 2000, hero.room_z, hero.room, -1)
    return game, floor, InputBuffer(pointer_held=True), near, far


def test_follow_reissues_only_when_the_resolution_changes(data_dir, profile, monkeypatch):
    import PyAitD.app.shell as main
    game, floor, buf, near, far = _follow_fixture(data_dir, profile)
    _resolving(monkeypatch, [("walk", near), ("walk", near), ("walk", far)])

    main.follow_pointer(game, ModalSession(), floor, (10, 10), [], buf)
    first = game.nav_intent
    assert (first.dest_x, first.dest_z, first.room) == near[:3]
    assert buf.follow_last == near
    first.waypoints = ["sentinel"]
    main.follow_pointer(game, ModalSession(), floor, (10, 10), [], buf)
    assert game.nav_intent is first and first.waypoints == ["sentinel"], (
        "an unchanged resolution is never re-issued: re-pathing every frame "
        "would reset the follower's stall bookkeeping and its waypoints"
    )
    main.follow_pointer(game, ModalSession(), floor, (10, 10), [], buf)
    assert game.nav_intent is not first
    assert (game.nav_intent.dest_x, game.nav_intent.dest_z) == far[:2]
    assert buf.follow_last == far


def test_follow_blocked_stops_the_hero_and_clears_the_latch(data_dir, profile, monkeypatch):
    import PyAitD.app.shell as main
    game, floor, buf, near, _far = _follow_fixture(data_dir, profile)
    _resolving(monkeypatch, [("walk", near), ("blocked", None), ("walk", near)])

    main.follow_pointer(game, ModalSession(), floor, (10, 10), [], buf)
    main.follow_pointer(game, ModalSession(), floor, (10, 10), [], buf)
    assert game.nav_intent is None and buf.follow_last is None
    assert (game.local_joyd, game.nav_decision) == (0, None)
    # back over the floor: the same point is issued again, the hold is live
    main.follow_pointer(game, ModalSession(), floor, (10, 10), [], buf)
    assert game.nav_intent is not None and buf.follow_last == near


def test_follow_does_not_reissue_an_arrived_or_abandoned_destination(
        data_dir, profile, monkeypatch):
    # the engine clears the intent on arrival or give-up; without the latch
    # the shell would re-issue it every frame -- re-dispatching a used object
    # and grinding at a dead click
    import PyAitD.app.shell as main
    game, floor, buf, _near, _far = _follow_fixture(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    target = (hero.room_x + 1000, hero.room_z, hero.room, 13)
    _resolving(monkeypatch, [("target", target), ("target", target)])

    main.follow_pointer(game, ModalSession(), floor, (10, 10), [], buf)
    assert game.nav_intent.target_object_idx == 13
    game.nav_intent = None   # what playworld does when the follower arrives
    main.follow_pointer(game, ModalSession(), floor, (10, 10), [], buf)
    assert game.nav_intent is None and buf.follow_last == target


@pytest.mark.parametrize("kind", ["inventory", "attack", "push"])
def test_follow_ignores_press_only_kinds(data_dir, profile, monkeypatch, kind):
    import PyAitD.app.shell as main
    game, floor, buf, near, _far = _follow_fixture(data_dir, profile)
    _resolving(monkeypatch, [(kind, near)])
    main.follow_pointer(game, ModalSession(), floor, (10, 10), [], buf)
    assert game.nav_intent is None and buf.follow_last is None


def test_follow_is_skipped_while_a_push_or_attack_latch_lives(data_dir, profile, monkeypatch):
    import PyAitD.app.shell as main
    from PyAitD.engine.interaction import apply_click_intent
    game, floor, buf, near, _far = _follow_fixture(data_dir, profile)
    queue = _resolving(monkeypatch, [("walk", near)])

    apply_click_intent(game, 10, 20, 0, 4, requires_hold=True)
    main.follow_pointer(game, ModalSession(), floor, (10, 10), [], buf)
    assert game.nav_intent.requires_hold is True and len(queue) == 1

    game.nav_intent = None
    buf.mouse_attack_target = 3
    main.follow_pointer(game, ModalSession(), floor, (10, 10), [], buf)
    assert game.nav_intent is None and len(queue) == 1


@pytest.mark.parametrize(
    "why", ["released", "unfocused", "modal", "keyboard", "cutscene", "transition"],
)
def test_follow_requires_a_held_pointer_in_live_play(data_dir, profile, monkeypatch, why):
    import PyAitD.app.shell as main
    from PyAitD.engine.effects import InputMode
    game, floor, buf, near, _far = _follow_fixture(data_dir, profile)
    session = ModalSession()
    queue = _resolving(monkeypatch, [("walk", near)])
    if why == "released":
        buf.pointer_held = False
    elif why == "unfocused":
        buf.focused = False
    elif why == "modal":
        game.active_modal = SimpleNamespace()
    elif why == "keyboard":
        game.input_mode = InputMode.KEYBOARD
    elif why == "cutscene":
        session.cutscene = True
    elif why == "transition":
        game.num_camera = -1
    main.follow_pointer(game, session, floor, (10, 10), [], buf)
    assert game.nav_intent is None and buf.follow_last is None
    assert len(queue) == 1, "nothing was resolved"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests/test_play_loop.py -k "follow_" -v`
Expected: every new test FAILS with `AttributeError: module 'PyAitD.app.shell' has no attribute 'follow_pointer'`.

- [ ] **Step 3: Implement `follow_pointer`**

In `PyAitD/app/shell.py`, immediately after `route_play_click`:

```python
def follow_pointer(game, session, floor, logical_pos, draw_list, input_buffer):
    """Held pointer follow: once per frame, re-aim the hero at whatever the
    held pointer resolves to (docs/superpowers/specs/2026-08-26-held-pointer-follow-design.md).

    The resolution is compared against input_buffer.follow_last, never the
    live intent: the engine clears an intent when the follower arrives or
    gives up, and _push_into_target re-aims a target intent at the object
    itself, so an unchanged resolution must never be re-issued within one
    hold. That one rule is both the arrival one-shot latch and the "a dead
    click is not retried until the pointer moves" rule. A transition frame
    (num_camera == -1) is skipped rather than resolved: the resolver reports
    blocked there, which would stop the hero for a tick at every room change.
    """
    from PyAitD.engine.interaction import apply_click_intent, cancel_nav_intent

    if (game.mode is not GameMode.PLAY or game.active_modal is not None
            or game.input_mode is not InputMode.MOUSE or session.cutscene
            or game.num_camera == -1
            or not input_buffer.pointer_held or not input_buffer.focused
            or input_buffer.mouse_attack_target is not None):
        return
    intent = game.nav_intent
    if intent is not None and intent.requires_hold:
        return  # a latched push ignores pointer motion until release
    kind, payload = resolve_play_click(game, floor, logical_pos, draw_list)
    if kind in ("walk", "target"):
        if payload == input_buffer.follow_last:
            return
        dest_x, dest_z, room, object_idx = payload
        apply_click_intent(game, dest_x, dest_z, room, target_object_idx=object_idx)
        input_buffer.follow_last = payload
    elif kind == "blocked":
        if intent is not None:
            cancel_nav_intent(game)
        input_buffer.follow_last = None
    # inventory, attack and push need a fresh press: nothing to follow
```

- [ ] **Step 4: Run the unit tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests/test_play_loop.py -k "follow_" -v`
Expected: all PASS.

- [ ] **Step 5: Wire the per-frame call and the floor-change cancel into `run`**

In `run`'s PLAY branch, replace

```python
                if floor.number != game.current_floor:
                    floor = game.load_floor(game.current_floor)
            if game.num_camera != -1:
                scene_frame, draw_list = _scene_frame(game, floor, renderer, resolver)
```

with

```python
                if floor.number != game.current_floor:
                    floor = game.load_floor(game.current_floor)
                    # the intent's room indexes the old floor; the next
                    # frame re-resolves the held pointer against the new one
                    _cancel_follow(game, input_buffer)
            if game.num_camera != -1:
                scene_frame, draw_list = _scene_frame(game, floor, renderer, resolver)
            # after the ticks and the scene refresh, so the held pointer
            # resolves against the frame it is actually over -- a camera cut
            # with a still pointer retargets here, without a motion event
            follow_pointer(
                game, session, floor, input_buffer.pointer_pos, draw_list, input_buffer,
            )
```

- [ ] **Step 6: Run the full suite**

Run: `make test`
Expected: 1031 passed, 1 skipped, 1 xfailed. The existing `test_mouse_journey_attic_take_hud_inventory_action` stays green: its `_left_click` never releases, so after the Take the follow re-resolves the held Take-button position in PLAY and either walks or stands — its assertions do not depend on where the hero is. Task 5 turns it into a true hold journey.

- [ ] **Step 7: Commit**

```bash
git add PyAitD/app/shell.py tests/test_play_loop.py
git commit -m "feat: held pointer follow re-resolves the pointer once per frame"
```

---

### Task 4: Contract, gate tests, and the pointer-freedom gate

**Files:**
- Modify: `PyAitD/games/aitd1/mouse_contract.py:55-56` (routes), `:196-201` (legacy reason), `:209-219` (decisions)
- Test: `tests/test_mouse_only.py:34-70`, `tests/test_layering.py`

**Interfaces:**
- Produces: `CAPABILITY_ROUTES[WALK_TO_POINT].gesture == "left_hold"`, `CAPABILITY_ROUTES[INTERACT_WITH_OBJECT].gesture == "left_hold"`, `MOUSE_INTERACTION_DECISIONS["held_pointer_follow"].decision == "retarget_per_frame"`.

- [ ] **Step 1: Rewrite the contract gates and add the new ones**

In `tests/test_mouse_only.py` replace `test_contract_declares_only_the_reviewed_primary_button_gestures` and `test_contract_declares_hover_and_touch_provenance_decisions` with:

```python
def test_contract_declares_only_the_reviewed_primary_button_gestures():
    hold_capabilities = {
        capability
        for capability, route in CAPABILITY_ROUTES.items()
        if route.gesture == "left_hold"
    }
    # walk and interact became held pointer follow routes
    # (2026-08-26-held-pointer-follow-design.md); push was already held
    assert hold_capabilities == {
        PlayerCapability.WALK_TO_POINT,
        PlayerCapability.INTERACT_WITH_OBJECT,
        PlayerCapability.HOLD_PUSH_OBJECT,
    }
    assert all(
        forbidden not in route.gesture
        for forbidden in ("double_click", "drag", "chord")
        for route in CAPABILITY_ROUTES.values()
    )


def test_contract_declares_hover_touch_and_held_follow_decisions():
    assert set(MOUSE_INTERACTION_DECISIONS) == {
        "hover_preview", "touch_origin", "held_pointer_follow",
    }
    assert MOUSE_INTERACTION_DECISIONS["hover_preview"].decision == "presenter_only"
    assert MOUSE_INTERACTION_DECISIONS["touch_origin"].decision == "same_primary_button_route"
    assert MOUSE_INTERACTION_DECISIONS["held_pointer_follow"].decision == "retarget_per_frame"
    assert all(decision.reason for decision in MOUSE_INTERACTION_DECISIONS.values())


def test_walk_and_interact_are_held_pointer_follow_routes():
    assert CAPABILITY_ROUTES[PlayerCapability.WALK_TO_POINT] == MouseRoute(
        "left_hold", "walkable floor", frozenset({GameMode.PLAY}),
    )
    assert CAPABILITY_ROUTES[PlayerCapability.INTERACT_WITH_OBJECT] == MouseRoute(
        "left_hold", "interactable actor", frozenset({GameMode.PLAY}),
    )
    # the press-only PLAY routes stay single clicks
    assert CAPABILITY_ROUTES[PlayerCapability.ATTACK_TARGET].gesture == "left_click"
    assert CAPABILITY_ROUTES[PlayerCapability.OPEN_INVENTORY].gesture == "left_click"
    for name in ("UP", "DOWN", "LEFT", "RIGHT"):
        decision = LEGACY_COMMAND_REPLACEMENTS[name]
        assert decision.replacement is PlayerCapability.WALK_TO_POINT
        assert "held pointer follow" in decision.reason
```

- [ ] **Step 2: Add the pointer-freedom gate**

Append to `tests/test_layering.py` (module has `ROOT = .../PyAitD` and is marked `meta`):

```python
def test_no_module_locks_grabs_or_warps_the_pointer():
    # Held pointer follow tracks a free OS cursor: the spec forbids relative
    # mode and grab (2026-08-26-held-pointer-follow-design.md, Non-goals);
    # warping the pointer would be the same control by another name.
    forbidden = ("set_relative_mode", "set_grab", "mouse.set_pos")
    hits = sorted(
        (str(path.relative_to(ROOT.parent)), name)
        for path in ROOT.rglob("*.py")
        for name in forbidden
        if name in path.read_text()
    )
    assert hits == []
```

- [ ] **Step 3: Run the gates to verify the contract ones fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests/test_mouse_only.py -k "contract or held_pointer_follow_routes" tests/test_layering.py -k "pointer" -v`
Expected: the three contract tests FAIL (walk/interact are still `left_click`, no `held_pointer_follow` decision); the layering gate PASSES (nothing under `PyAitD/` uses those calls today — this gate is a ratchet).

- [ ] **Step 4: Update the contract**

In `PyAitD/games/aitd1/mouse_contract.py`:

```python
    PlayerCapability.WALK_TO_POINT: MouseRoute("left_hold", "walkable floor", frozenset({GameMode.PLAY})),
    PlayerCapability.INTERACT_WITH_OBJECT: MouseRoute("left_hold", "interactable actor", frozenset({GameMode.PLAY})),
```

Legacy replacements:

```python
LEGACY_COMMAND_REPLACEMENTS = {
    name: LegacyCommandDecision(
        PlayerCapability.WALK_TO_POINT,
        "held pointer follow replaces the legacy tank-direction command",
    )
    for name in ("UP", "DOWN", "LEFT", "RIGHT")
}
```

Decisions:

```python
MOUSE_INTERACTION_DECISIONS = {
    "hover_preview": MouseInteractionDecision(
        "presenter_only",
        "hover previews the current effective target of the unheld pointer "
        "without activating or mutating game state",
    ),
    "touch_origin": MouseInteractionDecision(
        "same_primary_button_route",
        "touch-origin pointer events are provenance and use the same primary-button route",
    ),
    "held_pointer_follow": MouseInteractionDecision(
        "retarget_per_frame",
        "while the left button is held in PLAY the walk or approach destination "
        "follows the pointer; motion with the button down is a gesture, not hover",
    ),
}
```

Update the module docstring's first line to `"""Declared one-button mouse surface for the implemented game modes: single presses, held pointer follow, and latched hold-push."""`.

- [ ] **Step 5: Run the gates to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests/test_mouse_only.py tests/test_layering.py -q`
Expected: all pass (the journeys in `test_mouse_only.py` need game data; with it present they run).

- [ ] **Step 6: Run the full suite**

Run: `make test`
Expected: 1033 passed, 1 skipped, 1 xfailed.

- [ ] **Step 7: Commit**

```bash
git add PyAitD/games/aitd1/mouse_contract.py tests/test_mouse_only.py tests/test_layering.py
git commit -m "feat: contract declares walk and interact as held pointer follow routes"
```

---

### Task 5: Held attic journey and documentation

**Files:**
- Modify: `tests/test_mouse_only.py:403-441` (replace `test_mouse_journey_attic_take_hud_inventory_action`)
- Modify: `README.md:46-51`, `AGENTS.md:170-174`, `CONTEXT.md:54`, `CONTEXT.md:58`, `CONTEXT.md:227-228`

**Interfaces:**
- Consumes: `follow_pointer` wiring from Task 3 (the journey passes only if the per-frame follow retargets from a floor walk to the lamp without a second press), `resolve_play_click`, the `_run_scripted_mouse` / `_left_down` / `_left_up` helpers already in the file.

- [ ] **Step 1: Replace the attic journey with a held one**

In `tests/test_mouse_only.py`, replace the whole `test_mouse_journey_attic_take_hud_inventory_action` with:

```python
def test_mouse_journey_attic_take_by_held_pointer_follow(data_dir, profile, monkeypatch):
    # Press on bare floor, then drag the held pointer onto the lamp: the
    # per-frame follow must retarget from the floor walk to the lamp's
    # approach and use it once, with no second press. Modal clicks release
    # in the same pump so no stray follow starts when PLAY resumes.
    from PyAitD.app.shell import resolve_play_click

    lamp_idx = 13
    lamp_box = (100, 60, 200, 160)
    probe = init_game(data_dir, profile)
    probe.num_camera = probe.new_num_camera
    probe_floor = Floor(data_dir, probe.current_floor, profile)
    actor_idx = probe.world_objects[lamp_idx].obj_index
    draw_list = [(actor_idx, lamp_box)]
    # the first screen point, scanning the bottom of the frame upward, that
    # the real resolver reports as walkable floor with the lamp box in place
    floor_pos = next(
        pos
        for pos in ((x, y) for y in range(199, 100, -10) for x in range(10, 320, 20))
        if resolve_play_click(probe, probe_floor, pos, draw_list)[0] == "walk"
    )
    assert not (lamp_box[0] <= floor_pos[0] < lamp_box[2]
                and lamp_box[1] <= floor_pos[1] < lamp_box[3])

    game = init_game(data_dir, profile)
    game.timer = 300
    hero = game.actors[game.current_camera_target_actor]
    state = {
        "step": "press", "frames": 0, "hero_start": _effective_position(hero),
        "floor_walk_seen": False, "lamp_intent_seen": False,
    }

    def click(pos):
        return [_left_down(pos), _left_up(pos)]

    def next_events():
        state["frames"] += 1
        assert state["frames"] < 2500, "held attic journey exceeded its budget"
        intent = game.nav_intent
        if state["step"] == "press":
            state["step"] = "drag"
            return [_left_down(floor_pos)]
        if state["step"] == "drag":
            if intent is not None and intent.target_object_idx == -1:
                state["floor_walk_seen"] = True
                state["step"] = "lamp"
                return [pygame.event.Event(
                    pygame.MOUSEMOTION, pos=(150, 100),
                    rel=(150 - floor_pos[0], 100 - floor_pos[1]), buttons=(1, 0, 0),
                )]
            return []
        if state["step"] == "lamp":
            if intent is not None and intent.target_object_idx == lamp_idx:
                state["lamp_intent_seen"] = True
            if game.mode is GameMode.FOUND:
                state["step"] = "found"
                return [_left_up((150, 100))]
            return []
        if state["step"] == "found" and game.mode is GameMode.FOUND:
            state["step"] = "hud"
            return click(ModalLayout.FOUND_TAKE.center)
        if (state["step"] == "hud" and game.mode is GameMode.PLAY
                and lamp_idx in inventory_items(game)):
            assert game.nav_intent is None, "no follow may start from a modal click"
            state["step"] = "object"
            return click(PlayLayout.INVENTORY.center)
        if state["step"] == "object" and game.mode is GameMode.INVENTORY:
            state["step"] = "action"
            # The lamp is row 1, not row 0: the boot scripts grant object 2
            # first, and FITD take() inserts a second item at index 1
            # (main.cpp:3294-3307).
            return click(ModalLayout.INVENTORY_ROWS[1].center)
        if state["step"] == "action" and game.mode is GameMode.INVENTORY:
            state["step"] = "quit"
            return click(ModalLayout.INVENTORY_ROWS[0].center)
        if (state["step"] == "quit" and game.mode is GameMode.PLAY
                and game.in_hand_table[0] == lamp_idx):
            return [pygame.event.Event(pygame.QUIT)]
        return []

    _run_scripted_mouse(monkeypatch, game, draw_list, next_events)
    assert state["floor_walk_seen"] is True
    assert state["lamp_intent_seen"] is True, "the follow never retargeted onto the lamp"
    assert _effective_position(hero) != state["hero_start"]
    assert lamp_idx in inventory_items(game)
    assert game.in_hand_table[0] == lamp_idx
    assert game.nav_intent is None
```

- [ ] **Step 2: Run the journey**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest tests/test_mouse_only.py -k "held_pointer_follow" -v`
Expected: PASS. If `lamp_intent_seen` fails, the follow is not running per frame (check the Task 3 wiring in `run`); if the `floor_pos` scan raises `StopIteration`, no probed point resolves to floor with the lamp box in place — widen the scan's `y` range to `range(199, 60, -5)` and report it in the task report.

- [ ] **Step 3: Update README**

Replace `README.md` lines 46-51 (the paragraph starting "Pick Emily or Carnby") with:

```markdown
Pick Emily or Carnby by mouse or keyboard, then play. Mouse (default): press
and hold the left button — the hero walks toward the pointer and keeps
following it while you hold; hold over an object to approach and use it;
release to stop immediately. Pushable scenery shows an amber opposed-arrow
cursor: press and hold to approach and push (the push target stays latched
while you hold), release to stop. Armed enemies and the inventory button
answer a single press. The OS cursor is never locked or grabbed. Tab switches
to the keyboard scheme (arrows/WASD walk, Space acts) and back. Menus accept
both throughout.
```

- [ ] **Step 4: Update AGENTS.md**

Replace the bullet at `AGENTS.md` lines 170-174 (starting "- Held mouse actions latch one world object") with:

```markdown
- Mouse movement is a held pointer follow: every navigation intent is
  hold-bound (`playworld._apply_mouse_input` cancels an intent whose buffer is
  not held and focused), `app.shell.follow_pointer` re-resolves the held
  pointer once per frame and re-issues an intent only when the resolution
  differs from `InputBuffer.follow_last`, and hold-push keeps its latched
  target. Held actions never publish global Action; existing LIFE and
  collision code alone move pushable scenery. Never lock, grab or warp the OS
  cursor (`tests/test_layering.py` gates it). Keep the both-protagonist
  journeys in `tests/test_mouse_only.py` and run `make prove-mouse-only` after
  changing pointer, navigation, animation, modal, or collision behavior.
```

- [ ] **Step 5: Update CONTEXT.md**

Line 54: `| M3d | Mouse-only point-and-click input | done |` → `| M3d | Mouse-only input: held pointer follow since 2026-08-26 (was point-and-click) | done |`.

Line 58 (the "Mouse accessibility hardening" row): append to the status cell, before the closing `|`: ` — re-attestation pending: held pointer follow made PLAY movement press-and-hold, so the dwell-click / Accessibility Keyboard attestation no longer covers walking or approaching objects (`docs/superpowers/specs/2026-08-26-held-pointer-follow-design.md`)`.

Lines 227-228: replace

```markdown
- `app.shell.resolve_play_click` is the one HUD/attack/target/walk/blocked
  resolver used by both hover and click routing.
```

with

```markdown
- `app.shell.resolve_play_click` is the one HUD/attack/target/walk/blocked
  resolver used by hover, the press, and the per-frame held follow.
- `app.shell.follow_pointer` runs once per frame after the ticks and the
  scene refresh while the left button is held in PLAY; it re-issues an
  intent only when the resolution differs from `InputBuffer.follow_last`,
  which is also the arrival one-shot latch. Button-up, focus loss, modal
  takeover and a floor change clear both. Push and attack latches suspend
  it. No engine module learns about pointer motion.
```

- [ ] **Step 6: Run the full suite and the focused gate**

Run: `make test && make prove-mouse-only`
Expected: 1033 passed, 1 skipped, 1 xfailed; `prove-mouse-only` green.

- [ ] **Step 7: Commit**

```bash
git add tests/test_mouse_only.py README.md AGENTS.md CONTEXT.md
git commit -m "test+docs: held pointer follow attic journey and documentation"
```

---

## Verification checklist (whole branch)

- `make test`: 1033 passed, 1 skipped, 1 xfailed (baseline 1012 + 21: Task 1 +2, Task 2 +4, Task 3 +13, Task 4 +2, Task 5 ±0).
- `grep -rn "set_relative_mode\|set_grab\|set_pos" PyAitD/` prints nothing.
- `grep -n "requires_hold and (not input_buffer" PyAitD/engine/playworld.py` prints nothing (the hold check is general).
- `grep -n "follow_pointer(" PyAitD/app/shell.py` shows the definition and exactly one call inside `run`.
- `grep -n "_cancel_follow(game, input_buffer)" PyAitD/app/shell.py` shows exactly two calls: `_cancel_pointer_invalidation` and the floor-reload branch of `run`. The floor-change rule has no automated test (a real floor transition inside `run` is not cheap to script); this grep and the final review stand in for it.
- `git diff main -- PyAitD/engine/effects.py PyAitD/engine/navigate.py PyAitD/engine/interaction.py` is empty.
- Manual (user): windowed pass for Emily and Carnby — hold to walk, drag onto the lamp, release stops; push still latches; OS cursor free to leave the window.
