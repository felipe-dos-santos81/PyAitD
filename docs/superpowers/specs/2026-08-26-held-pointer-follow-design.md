# AITD1 Held Pointer Follow Design

Date: 2026-08-26

Status: Approved design — awaiting implementation plan

Reference: FITD `mainLoop.cpp` (input snapshot), `track.cpp` (manual rotation)

Builds on: M3d mouse-only input; M3e combat and invariants; mouse hold-to-push
actions; overall mouse accessibility hardening

Supersedes: the "drag-to-steer" and "dragging" non-goals in
`2026-08-24-mouse-hold-push-actions-design.md` and
`2026-08-24-overall-mouse-accessibility-design.md`, and the README sentence
"Moving the pointer while holding does not change the target" for every
route except hold-push.

## Goal

Make the left mouse button a held gesture for PLAY movement. While the button
is down the hero moves toward whatever the pointer currently resolves to —
walkable floor or an interactable object — and the destination follows the
pointer as it moves. Releasing the button stops the hero immediately. The OS
pointer is never locked, grabbed, or put into relative mode.

This is an input-layer change. The simulation keeps reading the same
`NavIntent`, the same follower, and the same arrival dispatch; only who
issues intents, how often, and when they are cancelled changes.

## Decisions taken during brainstorming

1. Release stops the hero immediately (not "keep walking to the last point").
2. Walking is hold-only. A plain click with no motion walks to that point for
   as long as the button stays down; there is no autonomous click-to-walk.
3. Interactable objects are hold-driven too: the hero approaches while held
   and uses the object once on arrival.
4. Tracking lives in the shell, once per frame (approach A). The engine API
   is unchanged apart from generalising the hold check.

## Scope

- One new shell routine, `follow_pointer`, run once per frame while the
  button is held in PLAY.
- One new `InputBuffer` field, `follow_last`, the per-hold retarget latch.
- Button release and focus loss cancel every navigation intent, not only
  push.
- `playworld._apply_mouse_input` cancels any intent whose buffer is not held
  and focused.
- Contract updates in `games/aitd1/mouse_contract.py` and their gate tests.
- Test rewrites for the shell routing, one journey, and a mechanical sweep of
  tests that tick a walk intent.
- README, AGENTS.md and CONTEXT.md updates, including the accessibility
  regression below.

## Non-goals

- Pointer lock, `pygame.mouse.set_relative_mode`, `pygame.event.set_grab`, or
  hiding the OS cursor outside the states that already hide it.
- Changing hold-push: its target stays latched at press and pointer motion is
  still ignored while it lives.
- Hold-to-attack, hold-to-open-inventory, or resuming a follow after a strike
  without a fresh press.
- Right-click, double-click, chords, timing thresholds, or a click-vs-hold
  discriminator (there is no click-to-walk left to discriminate from).
- Engine-owned tracking (approach B) or per-`MOUSEMOTION` retargeting
  (approach C).
- Any change to `NavIntent`, `navigate.decide`, `apply_click_intent`, the
  arrival dispatch, LIFE, collision, or animation.

## Gesture model

In PLAY with `InputMode.MOUSE` and no active modal, the left button is a
*held pointer follow*. Every frame while it is down the shell resolves
`input_buffer.pointer_pos` through the unchanged `resolve_play_click` and acts
on the kind:

| Resolution | Behaviour while held |
|---|---|
| `walk` | A* walk to the point (existing follower). On arrival the hero stands; the follow stays live. |
| `target` | walk to the approach cell; on arrival use the object once — a foundable opens the Take/Leave modal (which ends the hold), a scripted object gets today's Action pulse or push-into-target. Not re-fired until the pointer resolves to something else, or a new press. |
| `push` | unchanged latched hold-push. Only a press can start it; while it lives, `follow_pointer` does not run. |
| `attack` | one-shot on the press, exactly as today. The press does not start a follow; `follow_pointer` does not run while `mouse_attack_target` is latched. |
| `inventory` | one-shot on the press, opens the inventory (modal takeover). |
| `blocked`, or the pointer outside the logical frame | the hero stands; the hold stays live and moving back onto floor resumes. |

Button up or window focus loss stops the hero immediately. A press with no
motion walks to that point until release.

**Invariant:** under mouse control the hero never moves unless the left
button is down. Every navigation intent is hold-bound.

**Pointer freedom:** the OS cursor is never locked or grabbed. Motion that
continues outside the window while the button is held (SDL's default mouse
auto-capture) converts to out-of-frame logical positions and resolves to
`blocked`. The software cursor keeps drawing only for PLAY + mouse + no
modal + not cutscene, as today.

## Shell data flow (`PyAitD/app/shell.py`)

### Press

`MOUSEBUTTONDOWN` button 1 in PLAY keeps going through `route_play_click`:

- `inventory`, `attack`, `push`, `blocked`: unchanged.
- `walk`, `target`: `apply_click_intent(...)` immediately (no frame of
  latency for the first step) and set
  `input_buffer.follow_last = (dest_x, dest_z, room, object_idx)`.

`route_play_click`'s existing early return while a `requires_hold` intent
lives is kept.

### Per frame

After the fixed-tick loop and the `_scene_frame` refresh (so `draw_list`
and `game.num_camera` describe the frame the pointer is over), and before
rendering:

```text
follow_pointer(game, floor, logical_pos, draw_list, input_buffer) -> None
```

Runs only when all of these hold:

- `game.mode is GameMode.PLAY`, `game.active_modal is None`,
  `game.input_mode is InputMode.MOUSE`, `not session.cutscene`;
- `input_buffer.pointer_held and input_buffer.focused`;
- `input_buffer.mouse_attack_target is None`;
- `game.nav_intent is None or not game.nav_intent.requires_hold`.

Body:

1. `kind, payload = resolve_play_click(game, floor, logical_pos, draw_list)`.
2. `walk` / `target`: if `payload != input_buffer.follow_last`, call
   `apply_click_intent` with the payload and set `follow_last = payload`.
   If equal, do nothing. This equality is the arrival/abandon latch: the
   engine clears the intent when the follower arrives or gives up, and the
   shell never re-issues an unchanged destination within one hold.
3. `blocked`: if `game.nav_intent is not None`, `cancel_nav_intent(game)`;
   set `follow_last = None`.
4. `inventory`, `attack`, `push`: do nothing. These need a fresh press.

`follow_last` is compared against the resolver's payload, never against the
live intent's destination, because `_push_into_target` legitimately re-aims
an arrived target intent at the object's own point.

### Cancellation

`_cancel_pointer_invalidation` cancels *any* intent on `MOUSEBUTTONUP`
button 1 or `WINDOWFOCUSLOST` (today only a `requires_hold` one). It also
clears `follow_last`; `reset_input` clears it too, so modal takeover, focus
loss and the input-mode toggle already reset the latch.

Where the tick loop reloads `floor` because `game.current_floor` changed,
also `cancel_nav_intent(game)` and clear `follow_last`; the next frame
re-resolves the pointer against the new floor.

### Cursor

No new cursor kind. `_play_cursor_kind` keeps showing the current
resolution; while held it therefore shows what the hero is heading for.

## Input buffer (`PyAitD/app/ui.py`)

```python
# Held pointer follow: the last (dest_x, dest_z, room, object_idx) the shell
# issued as an intent during this hold. follow_pointer re-issues only when the
# resolution differs, which is also the one-shot latch after an arrival.
follow_last: tuple | None = None
```

Cleared by `reset_input`. `event_to_input` is otherwise unchanged
(`pointer_held`, `pointer_pos`, `pointer_touch` already exist).

## Engine (`PyAitD/engine/playworld.py`)

In `_apply_mouse_input`, the focus/hold check that today guards only
`requires_hold` intents guards every intent:

```python
if not input_buffer.focused or not input_buffer.pointer_held:
    cancel_nav_intent(game)
    return
```

The push-only origin floor/room checks stay push-only. `cancel_nav_intent`
is unchanged: releasing a walking hero zeroes `local_joyd` on the next tick
and the hero's own LIFE stands it, the same stop a keyboard release gets;
push keeps its forced stand transition.

Nothing else in `engine/` changes. No engine module learns about pointer
motion.

## Contract (`PyAitD/games/aitd1/mouse_contract.py`)

- `CAPABILITY_ROUTES[WALK_TO_POINT]` becomes
  `MouseRoute("left_hold", "walkable floor", {PLAY})`.
- `CAPABILITY_ROUTES[INTERACT_WITH_OBJECT]` becomes
  `MouseRoute("left_hold", "interactable actor", {PLAY})`.
- `MOUSE_INTERACTION_DECISIONS["held_pointer_follow"] =
  MouseInteractionDecision("retarget_per_frame", "while the left button is
  held in PLAY the walk or approach destination follows the pointer; motion
  with the button down is a gesture, not hover")`.
- `hover_preview` keeps `presenter_only`: it now describes the *unheld*
  pointer only.
- `LEGACY_COMMAND_REPLACEMENTS` for UP/DOWN/LEFT/RIGHT keep
  `WALK_TO_POINT` as the replacement; the reason string changes to
  "held pointer follow replaces the legacy tank-direction command".
- The word "drag" stays forbidden in gesture names; the gesture is
  `left_hold`.

## Edge cases

| Case | Behaviour |
|---|---|
| Pointer leaves the logical frame while held | resolves `blocked` → hero stands, hold stays live |
| Camera cut with the pointer still | next frame re-resolves the same pixel against the new camera and retargets |
| Floor change mid-hold | intent cancelled and `follow_last` cleared at the floor reload; next frame re-resolves on the new floor |
| Modal takeover (found, reading, picture, game over, inventory, system menu) | `_take_over_play_input` resets the buffer and cancels the intent; the physical button still being down does not resume — a new press is required |
| Stall give-up or abandoned intent | engine clears the intent; `follow_last` is unchanged so the same point is not retried until the pointer moves |
| Attack press | one-shot as today; no follow while the attack latch lives |
| Touch | identical path via SDL-synthesised mouse events; `touch` remains provenance |
| Keyboard mode, Tab mid-hold | unchanged; the toggle resets input |
| Opening cutscene | the skip press is swallowed before `event_to_input`, so `pointer_held` never sets and no follow starts from it |

## Accessibility regression (accepted)

PLAY movement now requires press-and-hold. The dwell-click and macOS
Accessibility Keyboard attestations in
`docs/mouse-accessibility-hardening-proof.md` no longer cover walking or
approaching objects. `CONTEXT.md`'s accessibility row is marked
"re-attestation pending: held pointer follow"; every other attested surface
(HUD, modals, shell, push, attack) is untouched.

## Testing

Shell (`tests/test_play_loop.py`, headless, real data):

- a floor press issues a walk intent and records `follow_last`;
- `follow_pointer` retargets when the resolution changes and does nothing
  when it is equal;
- `follow_pointer` on `blocked` cancels the intent and clears `follow_last`;
- button-up and focus loss cancel a plain walk intent (rewrites
  `test_mouseup_cancels_only_a_hold_required_intent`);
- arrival latch: a pointer held over a used object produces exactly one
  dispatch across many frames;
- `follow_pointer` does not run while a push or attack latch lives, and an
  attack or inventory press starts no follow;
- a floor change clears the intent and `follow_last`;
- no `set_relative_mode` / `set_grab` call anywhere in `PyAitD/` (grep gate
  in `tests/test_layering.py`, alongside the presentation-free probes).

Engine (`tests/test_playworld.py`): an unheld or unfocused buffer cancels a
walk intent on the next tick.

Contract (`tests/test_mouse_only.py`): hold capabilities are exactly
`{WALK_TO_POINT, INTERACT_WITH_OBJECT, HOLD_PUSH_OBJECT}`; decisions are
exactly `{hover_preview, touch_origin, held_pointer_follow}`; the attic
take/HUD journey drives the hero by a held pointer for both heroes; the
wardrobe hold-push journey is unchanged.

Sweep: tests that tick a walk intent pass a held buffer. A conftest helper
`held_pointer(pos=None) -> InputBuffer` (pointer_held=True, focused=True,
pointer_pos=pos) replaces `InputBuffer()` at those sites.

Gate: `make prove-mouse-only` (already `test-shell`). A windowed pass for
Emily and Carnby is the manual step and is recorded by the user.

## Documentation

- README: the mouse paragraph describes hold-to-walk, hold-to-approach, and
  the unchanged push, attack and menu routes.
- AGENTS.md: the held-actions bullet states the invariant and the
  per-frame shell ownership.
- CONTEXT.md: the M3e boundary section gains the `follow_pointer` seam; the
  accessibility milestone row is marked re-attestation pending.

## Assumptions

- SDL's default mouse auto-capture delivers `MOUSEMOTION` while the button
  is held outside the window. If a platform does not, the pointer simply
  stops updating and the hero keeps heading for the last resolution until
  release — acceptable, and the windowed pass checks it.
