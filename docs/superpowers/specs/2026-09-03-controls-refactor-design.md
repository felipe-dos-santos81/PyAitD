# Controls Refactor: `app/controls/` and the Engine Input Boundary

Sub-project 2 of the content-packs programme
(`2026-09-03-content-packs-foundation-and-enemies-design.md`, "Build
order"). Independent of content; a prerequisite for pack-contributed
bindings (sub-project 5).

## Goal

Move every piece of input handling out of `PyAitD/app/shell.py` (1990
lines) and `PyAitD/app/ui.py` (1613) into a new `PyAitD/app/controls/`
package, behind a fixed action vocabulary, with the engine consuming a
small snapshot it owns instead of the app's `InputBuffer`. Behaviour is
identical: every existing input test keeps its assertions, and a recorded
event stream replays byte-identically before and after.

## Why

Input today is spread over three files and one object:

- `app/config.py`: eight `Control`s and their key names (settings v1).
- `app/ui.py`: `Command`, `InputBuffer` (about twenty fields, twelve of
  them pointer-follow state), `event_to_input`, `compile_bindings`, the
  modal reducers and hit tests, next to the presenters and painter.
- `app/shell.py`: about 900 lines from `resolve_play_click` to
  `route_hover`: click resolution, hold-follow, double-press run, resume,
  camera-cut settling, cursor and marker, and the mode/modal dispatch.
- `engine/script/playworld/input.py` reads seven `InputBuffer` fields.

Every mouse bug so far ("hold does not walk", "the run window swallowed
clicks", "an unreachable pixel refused") lived in the hold-follow
transitions, and each was reproduced only through a 700-line journey.
Packs will need a named action to bind a gesture or key to, and there is
no such thing today.

## Rejected

- **Pure move** of the existing code with no model change: least risk, but
  pack bindings would need a second pass through the same files, and the
  engine would keep reading an app object.
- **Full app split** (also breaking `ui.py`'s presenters into `app/ui/`):
  the presenter half has nothing to do with controls; it doubles the diff
  for no reliability gain now.

## 1. Package layout and layering

```
PyAitD/app/controls/
  __init__.py    re-exports the public names below
  actions.py     Action (the fixed vocabulary), DIRECTION_BITS
  bindings.py    compile_bindings(settings) -> {pygame key: Action}; canonical_key_name; the pre-settings default table
  keyboard.py    KeyboardState, feed_key_event(state, event, table), reset
  pointer.py     PointerState, press/move/release/reset, decide(...) -> PointerDecision; the three gesture constants
  modals.py      reduce_found/inventory/reading/system_menu, turn_page, capture_system_key, pick_system_key, hit_test_*
  router.py      route_command, route_mouse, route_hover, resolve_play_click, route_play_click, _steer, the result appliers
  cursor.py      play cursor kind, destination and intent markers, hit-feedback rects, pointer actor targets
  snapshot.py    ControlsState, build_play_input(controls, game) -> PlayInput, reset(controls, game), configure(controls, settings)
```

- `ui.py` keeps presenters, `*Presenter`/`*Result` dataclasses, layouts,
  `UIPainter`, `render_*`, `render_cursor`. It loses `Command`,
  `InputBuffer`, `compile_bindings`, `canonical_key_name`,
  `event_to_input`, `reset_input`, `configure_input`, the reducers and
  the hit tests.
- `shell.py` keeps `parse_args`, `main`, `run` (the pump and tick
  accumulator), `_capture_keydown` (remap capture), save/load policy, the
  restart and hero-boot branches, `render_active_mode` and presentation.
  It calls `controls` and never touches key codes or pointer state.
- `config.py` is unchanged except `Control = Action` for the eight
  key-bindable members; settings schema v1 does not change.

Layering, pinned in `tests/test_layering.py`:

| Package | May import | Never |
|---|---|---|
| `app/controls` | `pygame`, `PyAitD.engine`, `PyAitD.app.config`, `PyAitD.app.ui` (dataclasses only, via the presenter/result names) | `PyAitD.app.shell`, `PyAitD.render` |
| `app/ui` | as today | `PyAitD.app.controls` (one direction only) |
| `engine` | as today | anything under `PyAitD.app` (already forbidden); `InputBuffer` no longer exists |

## 2. The action vocabulary and bindings

```python
class Action(str, Enum):
    # key-bindable: settings v1 names, unchanged
    UP = "UP"; DOWN = "DOWN"; LEFT = "LEFT"; RIGHT = "RIGHT"
    ACTION = "ACTION"; INVENTORY_CONFIRM = "INVENTORY_CONFIRM"
    CANCEL = "CANCEL"; TOGGLE_INPUT_MODE = "TOGGLE_INPUT_MODE"
    # pointer-only: produced by pointer.decide, never in settings
    WALK = "WALK"; RUN = "RUN"; TARGET = "TARGET"; PUSH = "PUSH"
    USE = "USE"; MENU_CLICK = "MENU_CLICK"

KEY_BINDABLE = (UP, DOWN, LEFT, RIGHT, ACTION, INVENTORY_CONFIRM, CANCEL, TOGGLE_INPUT_MODE)
```

- The eight key-bindable members keep today's names and values, so
  `settings.bindings`, the key picker and saved settings files stay valid;
  `REMAPPABLE_CONTROLS` is `KEY_BINDABLE` minus `CANCEL`, as now.
- `Command` goes away. The keyboard queue carries `Action` values; the
  modal reducers switch on `Action.ACTION`, `Action.CANCEL`,
  `Action.INVENTORY_CONFIRM`, `Action.UP`... instead of `Command.*`. A
  rename, not a behaviour change.
- `bindings.py` is today's `compile_bindings`, `canonical_key_name` and
  `_DEFAULT_CONTROL_BY_KEY` moved verbatim.
- `keyboard.py`: `KeyboardState(held_joyd, action_held, action_pulse,
  sticky_action, sticky_armed, queue)` and `feed_key_event`, today's
  KEYDOWN/KEYUP half of `event_to_input` with unchanged logic (repeat
  suppression, sticky arm on ACTION and pulse on the next direction).
  Focus loss resets it.
- Pointer actions are emitted by `pointer.decide` and consumed by
  `router`; nothing in settings mentions them in this sub-project.

## 3. The engine boundary

`engine/script/playworld/input.py` gains

```python
@dataclass(frozen=True)
class PlayInput:
    joyd: int = 0
    action_held: bool = False
    action_pulse: bool = False
    pointer_held: bool = False
    focused: bool = True

IDLE = PlayInput()
```

- `play_tick(game, floor, play_input)` and `apply_play_input(game,
  play_input)` take a `PlayInput`. These five fields are exactly what the
  engine reads from `InputBuffer` today.
- The mouse attack latch moves into the engine, which is what ends it:
  `game.mouse_attack_target: int | None` and `game.mouse_attack_ticks:
  int` become transient `Game` fields (like `nav_intent`: never saved,
  reset by `restore_game`), set by `arm_mouse_attack(game, target_idx)`
  and cleared by `clear_mouse_attack(game)` in `playworld/input.py`. The
  strike-completion and `MOUSE_ATTACK_TICK_BUDGET` logic is unchanged and
  writes these fields. The shell's "a latch is alive" checks read
  `game.mouse_attack_target`.
- `action_pulse` is consumed today by the engine writing `False` into the
  buffer. `snapshot.build_play_input` clears `KeyboardState.action_pulse`
  itself when it builds the snapshot for a play tick, and only then, so a
  pulse raised while a modal is open still fires on the first play tick
  after it.
- Test churn on the engine side is mechanical: every
  `play_tick(game, floor, InputBuffer())` becomes `play_tick(game, floor,
  IDLE)`, and buffers with fields set become `PlayInput(...)`.

## 4. The pointer gesture machine (`pointer.py`)

```python
@dataclass
class PointerState:
    held: bool = False
    touch: bool = False
    pos: tuple[int, int] | None = None
    follow_last: tuple | None = None      # last resolution issued this hold
    follow_pos: tuple[int, int] | None = None   # pixel it was resolved at
    follow_camera: int | None = None      # camera slot it was resolved under
    settle_origin: tuple[int, int] | None = None  # after a cut: motion within CUT_DEAD_ZONE_PX is settling
    spent: bool = False                   # attack/inventory/push this hold: no follow resume
    run: bool = False
    last_press_tick: int | None = None
    resume_last: tuple | None = None
    resume_pos: tuple[int, int] | None = None
```

Pure transitions; no `pygame`, no `game`:

- Event half: `press(state, pos, tick, touch)`, `move(state, pos, touch)`,
  `release(state)`, `reset(state)`.
- Frame half: `decide(state, *, tick, camera, resolve) -> PointerDecision`,
  today's `follow_pointer` minus the engine calls. `resolve(pos)` is a
  callback returning today's `(kind, payload)` tuple with kind in
  `walk | steer | attack | push | inventory | blocked`. `decide` owns the
  double-press window (`DOUBLE_PRESS_TICKS = 25`), resume
  (`DOUBLE_PRESS_RESUME_PX = 6`), the camera-cut dead zone
  (`CUT_DEAD_ZONE_PX = 6`), re-resolve only when the pointer moved, and
  the spent latch. It returns one of `Nothing`, `Issue(kind, payload,
  run)`, `Cancel`, `Resume(payload, run)`.
- The three constants move here from `shell.py`; `DOUBLE_PRESS_TICKS`
  keeps its tick-not-milliseconds rationale in its comment.

The router applies decisions: `Issue("walk"|"steer")` issues the nav
intent exactly as `follow_pointer` does now; `Issue("attack")` calls
`arm_mouse_attack`; `Issue("push")` and `Issue("inventory")` do what
`route_play_click` does now; `Cancel` calls `cancel_nav_intent`;
`Resume` re-issues the stashed destination. `resolve_play_click` (the
pixel-to-world resolver, needing `game`, `floor` and the draw list) moves
to `router.py` unchanged and is what the shell passes as `resolve`.

## 5. Router, cursor, snapshot

- `router.py` is a move: `route_command`, `route_mouse`, `route_hover`,
  `resolve_play_click`, `route_play_click`, `_steer`,
  `_apply_system_result`, `_route_game_over_command`,
  `_apply_startup_result`, `_take_over_play_input`. Signatures keep
  `(game, session, ...)`; the `input_buffer` parameter becomes `controls:
  ControlsState`.
- `modals.py` takes the reducers and hit tests out of `ui.py`; they are
  input reducers, not presenters. `ui.py` keeps the `*Presenter` and
  `*Result` dataclasses and `SystemMenuPage`/`CharacterPhase`, which both
  sides import.
- `cursor.py`: `_play_cursor_state`, `_play_cursor_kind`, `_marker_for`,
  `_intent_marker`, `_hit_feedback_rects`, `_pointer_actor_targets`,
  `expand_actor_targets`: "what should the cursor look like" over `game`,
  the resolver and `PointerState`. Drawing stays in `ui.render_cursor`,
  called by `shell.render_active_mode` with the cursor module's answer.
- `snapshot.py`: `ControlsState(keyboard: KeyboardState, pointer:
  PointerState, focused: bool)` replaces `InputBuffer` at the shell level;
  `build_play_input(controls, game) -> PlayInput` is the one fold into the
  engine snapshot; `reset(controls, game)` resets both states and calls
  `clear_mouse_attack(game)`; `configure(controls, settings)` compiles
  bindings and sets sticky.
- The pump in `shell.run` becomes: pygame event → `_capture_keydown`
  (unchanged) → `keyboard.feed_key_event` or `pointer.press/move/release`
  → drain the action queue into `router.route_command` → per frame
  `pointer.decide` and apply → per tick `build_play_input` and
  `play_tick`.

## 6. Testing, migration, docs

- **Invariance net.** `test_mouse_only`, `test_runtime_modes`,
  `test_shell_journeys`, `test_ui_input`, `test_ui_mouse`,
  `test_ui_reducers`, `test_play_loop` keep every assertion; only imports
  and the `Command` → `Action`, `InputBuffer` → `ControlsState`/`PlayInput`
  renames change. Any other assertion edit is a finding for the
  controller to rule on.
- **Recorded-events golden.** Before any code moves, a task records on
  today's `main` a scripted event stream (presses, drags, releases,
  double presses, a camera cut, keys, focus loss, stamped in ticks)
  replayed through the real headless pump the way `test_play_loop`
  drives `shell.run`, and pins the per-tick `PlayInput` stream (fields
  only) plus the hero's position trace as JSON under `tests/golden/`.
  Every later task keeps it byte-identical.
- **Unit tests for the pure modules:** `tests/test_controls_pointer.py`
  (hold walks, release cancels, double press runs, resume within the
  window, cut dead zone, spent latch, touch), `test_controls_keyboard.py`
  (repeat, sticky arm and pulse, focus loss), `test_controls_bindings.py`,
  `test_controls_snapshot.py` (the pulse is consumed only for a play
  tick), `test_controls_modals.py` (the moved reducer tests). All carry
  the `shell` marker; only bindings needs pygame.
- **Layering:** the section 1 table in `tests/test_layering.py`.
- **Docs:** `CONTEXT.md`'s "M4a1 shell boundary" section is rewritten
  for the split and the `app/controls/` rows join the file map;
  `AGENTS.md`'s package layout gains `app/controls/`; README is unchanged
  (no user-visible change).

## Sequencing for the plan

1. Golden recording on unchanged code.
2. Engine `PlayInput` and the attack latch on `Game`; mechanical test churn.
3. `actions`, `bindings`, `keyboard`; `Command` removed.
4. `pointer` with its unit tests, called from the still-in-place
   `follow_pointer` as an adapter.
5. `modals` and `router`.
6. `cursor`, `snapshot`, the shell trim.
7. Layering pins, docs, golden re-pin (must be unchanged).

Each step leaves `make test` and the golden green.

## Done when

- `shell.py` contains no pygame key codes and no pointer state;
  `InputBuffer` and `Command` no longer exist anywhere.
- The golden and every suite pass; `make test` count only grows.
- Each earlier mouse bug has a unit test in `test_controls_pointer.py`.
- Settings files written before the refactor still load.
