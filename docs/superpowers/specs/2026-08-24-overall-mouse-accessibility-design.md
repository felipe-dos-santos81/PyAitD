# Overall Mouse Accessibility Design

Date: 2026-08-24

Status: In-chat design approved; written review pending

Builds on: M3d mouse input, M3e mouse reachability/combat, M4a1 shell and configuration, and mouse hold-to-push

## Goal

Make every current and future reachable game-progression and UI operation
usable through a single-button pointer, then prove both protagonists can
complete the game that way. Capturing the physical key for optional keyboard
remapping remains the sole keyboard-only configuration operation. Work is split
into ordered milestones so mouse accessibility stays inside the feature that
owns the behavior instead of becoming a parallel game system.

The first milestone hardens the implemented surface. Later mouse work lands
with M4a2 persistence, M4b media, and M4c playthrough closure.

## Verified baseline

The current checkout already provides:

- click-to-walk navigation and one shared hover/click resolver;
- clicked world interaction, inventory access, and combat targeting;
- mouse routes for found objects, inventory actions, reading, pictures, game
  over, character selection, the system menu, settings notices, and quit;
- held approach and pushing for eligible scripted scenery;
- a pygame-free capability registry in `mouse_contract.py`;
- one pygame event pump in `__main__.py` and headless simulation boundaries in
  `interaction.py` and `playworld.py`;
- focused automated gates for mouse-only gameplay and the shell.

The two windowed accessibility walkthroughs remain pending. The known input
regression is that clicking the inventory HUD during an active held push can
open the modal while retaining held navigation until mouse-up.

## Locked decisions

1. Use additive, contract-first changes through existing seams.
2. Add no dependency. Reuse pygame-ce mouse events, focus events, touch-origin
   metadata, cursor support, and rectangle collision operations.
3. Keep press-and-hold as the sole push gesture.
4. Add non-required hover previews to menus and modals.
5. Give small targets invisible, deterministic padding without changing art.
6. Treat pygame-ce mouse events with `touch=True` like physical mouse events.
   Do not add a separate `FINGERDOWN`/`FINGERUP` subsystem that could duplicate
   SDL's synthesized mouse events.
7. Require automated gates and actual windowed single-button evidence.
8. Keep save/load, media, and ending behavior in M4a2, M4b, and M4c. Mouse work
   exposes their existing commands and reducers; it does not reimplement them.
9. Produce a four-plan suite after this design is reviewed.

## Scope

### Current-surface hardening

- cancel held navigation atomically when any modal takes control;
- add forgiving hit geometry for small HUD and world targets;
- add optional hover preview for modal and shell controls;
- accept touch-origin pygame mouse events through the existing pointer path;
- extend capability, event-order, real-loop, and manual accessibility proof.

### Completion parity

- add mouse routes alongside M4a2 save/load UI and errors;
- add mouse routes alongside M4b sequences and any exposed audio controls;
- keep the capability registry exhaustive as M4 adds modes and commands;
- close with automated and windowed start-to-ending journeys for Emily and
  Carnby.

## Non-goals

- A generalized pointer framework or replacement event loop.
- pygame_gui or another UI dependency.
- Right-click, double-click, dragging, pointer lock, or mouse-plus-key chords.
- A second touch gesture system.
- Visual redesign or asset replacement.
- Implementing save/load, audio, sequence decoding, or ending logic in the
  mouse layer.
- Changing FITD simulation, LIFE, collision, combat, or world state directly
  from pointer code.

## Architecture and ownership

### `PyAitD/__main__.py`

Owns the single pygame event pump, window-to-logical conversion, mode-aware
pointer dispatch, atomic modal takeover, game/session replacement, and one
presentation per frame. It coordinates cancellation but does not implement
world behavior.

### `PyAitD/ui.py`

Owns pygame-ce event translation, visible layout rectangles, separate forgiving
hit rectangles, presenter-only hover state, hit tests, reducers, and drawing.
Hover may change presenter selection; it never changes `Game`, actor, inventory,
LIFE, or world state.

### `PyAitD/mouse_contract.py`

Remains pygame-free. It declares each player capability, its gesture, target,
and modes; maps commands to mouse capabilities or a reviewed legacy decision;
and makes every new M4 mode and command fail an exhaustiveness test until its
mouse route is decided.

### `PyAitD/interaction.py` and `PyAitD/playworld.py`

Retain headless navigation, action, and held-intent cancellation. They accept
input state and semantic intents only. They never import pygame or inspect raw
events.

### Owning M4 modules

M4a2 owns save snapshots, slot UI, validation, and restoration. M4b owns audio,
sequence parsing, playback, and skip semantics. M4c owns reachable behavior and
ending closure. Their UI actions reuse the established command/effect/reducer
boundary, which the pointer router may activate.

## Pointer interaction contract

### Coordinates and hit geometry

Every event position is converted once with `Renderer.window_to_logical()`.
Letterbox and out-of-window positions remain `None` and cannot activate an
action.

Visible rectangles remain unchanged. Effective targets are computed on the
320x200 logical surface with these rules:

- add two logical pixels of padding on each side when space permits;
- ensure a minimum effective size of 12x12 logical pixels, equivalent to 48x48
  window pixels at the default 4x scale;
- clamp effective targets to the logical frame;
- divide the gap between adjacent UI targets at their midpoint so their
  effective rectangles never overlap;
- when expanded world-actor targets overlap, preserve the existing frontmost
  draw-order winner;
- preserve top-level action priority regardless of padding.

The action priority remains:

1. settings notice;
2. PLAY inventory HUD;
3. armed combat target;
4. interactable actor;
5. held-push actor;
6. walkable floor;
7. blocked/no action.

The same effective geometry is used for hover and activation, so feedback
cannot advertise an action that clicking will not perform.

### Hover

`MOUSEMOTION` stores the logical pointer position and may update a modal or
shell presenter's preview selection. It never activates a reducer, emits a
command, starts navigation, or mutates game state. Leaving a target or the
logical frame clears the preview. Keyboard selection remains authoritative
until subsequent mouse motion selects another valid target.

Hover is optional feedback. Every operation remains usable without moving the
pointer over a target before pressing it.

### Primary-button down

`MOUSEBUTTONDOWN` for button 1 sets `InputBuffer.pointer_held`, resolves one
target in the active mode, and routes at most one semantic action. Settings
notice dismissal keeps first refusal. PLAY uses `resolve_play_click`; modal and
shell modes use their existing hit tests and reducers.

Touch-origin mouse events use this identical route. The `touch` attribute is
accepted as provenance, not as a different gesture.

### Primary-button up and focus loss

`MOUSEBUTTONUP` for button 1 and `WINDOWFOCUSLOST` clear pointer-held state and
cancel a held navigation intent before the same pump can run another PLAY tick.
Cancellation is idempotent and does not cancel an ordinary one-shot
click-to-walk intent.

### Atomic modal takeover

Every transition from PLAY to a modal performs one shared takeover operation
before modal input, modal rendering, or another simulation tick:

1. clear held/action/sticky/queued transient input;
2. cancel any ordinary or held navigation intent through the existing
   interaction service;
3. clear cached click/navigation decisions and local movement/action signals;
4. install or retain the modal and reset its presenter once;
5. continue in the modal with no stale PLAY event available for replay.

This transition rule covers pointer-opened inventory, keyboard-opened system
menu, collision/found effects, reading/pictures, game over, load replacement,
and sequence boundaries. Repeating takeover or cancellation is safe.

## Ordered milestones

### 1. Mouse accessibility hardening

Owns only the implemented surface. It repairs atomic modal takeover, introduces
effective hit geometry and hover preview, accepts touch-origin mouse events,
extends the mouse contract, and completes both protagonists' current windowed
single-button walkthroughs.

Press-and-hold pushing is an explicit, user-approved exception to the older
conclusion roadmap statement that no operation requires holding. The exception
applies only to pushing; no other operation may add a hold requirement.

Focused gate: `make prove-mouse-only` plus the relevant shell tests. Full gate:
`.venv/bin/pytest -q && make prove`. The existing `make prove-shell` gate must
also remain green.

### 2. M4a2 persistence mouse parity

M4a2 implements persistence. Its mouse slice adds single-click access to Save,
Load, slot selection, confirmation, cancellation, quick-save UI if exposed,
and persistent error dismissal. Loading validates into a temporary snapshot;
invalid loads leave the live game unchanged. Successful load replacement
cancels transient pointer state before the new session becomes active.

The M4a2 focused proof must cover save, mutate, load, invalid load, overwrite
confirmation if the owning design includes it, error dismissal, and a clean
process restart using only declared pointer routes for UI decisions.

### 3. M4b media mouse parity

M4b implements audio and sequences. Its mouse slice adds single-click sequence
advance or skip according to the owning FITD-backed design and exposes any real
audio controls through large single-click targets. Playback cannot block the
event pump. Silent-audio fallback remains fully playable. Media errors remain
visible and dismissible.

The M4b focused proof must cover sequence input during playback, skip/advance
at legal and illegal boundaries, focus loss, silent fallback, and error
dismissal without hidden waits or replayed actions.

### 4. M4c completion mouse gate

M4c adds mouse declarations and routes for every newly reachable operation and
then proves the combined product. Automated journeys are bounded by explicit
step/frame budgets and name the last successful checkpoint on failure.

Release requires recorded windowed journeys for Emily and Carnby from character
selection through ending, using one primary button only. They may not use a
debug start, keyboard command, manual state edit, skipped mandatory interaction,
or an undeclared mouse route. Press-and-hold pushing remains allowed. Optional
remap capture need not be visited because it is a keyboard-configuration action,
not a prerequisite to complete either game path.

## Error handling

- Outside-frame, stale, disabled, or ambiguous pointer targets are no-ops and
  never fall through to an unintended lower-priority action.
- Target expansion cannot change the selected world actor when the pointer is
  already inside its original visible bounds.
- Focus loss, modal takeover, load, hero replacement, restart, floor change,
  and sequence takeover cannot leave held navigation or local action asserted.
- Invalid saves and unavailable/malformed media follow their owning M4 recovery
  contracts and never partially mutate valid running state.
- Recoverable errors remain visible until their explicit large target is
  activated. Dismissal changes no underlying mode or game state.
- An unknown mode, effect, capability, or command/mouse mapping fails a test or
  raises with type and mode context; it is never silently treated as clickable.

## Verification

### Pure and headless tests

- layout tests pin visible and effective rectangles, minimum size, frame clamp,
  midpoint partitioning, and exclusive boundaries;
- picking tests pin original-bound precedence and expanded frontmost tie-breaks;
- capability tests require complete mode, command, gesture, and target tables;
- input tests cover physical and `touch=True` mouse down/up, focus loss, and
  repeated idempotent cancellation;
- headless interaction/playworld tests prove no pygame import crosses into the
  simulation boundary.

### Dummy-SDL real-loop tests

- modal entry during held approach and engaged push cancels before the next
  observed PLAY tick;
- inventory HUD, system menu, found, reading, picture, game-over, settings
  notice, character selection, and future M4 modes route one activation each;
- hover previews every enabled target, clears outside it, and never mutates
  game state;
- physical and touch-origin event scripts reach the same semantic results;
- focus loss and session replacement cannot replay an action;
- every scripted journey has a bounded event/frame budget.

Rendering tests set `SDL_VIDEODRIVER=dummy`; media tests also use the dummy audio
driver or the silent adapter as appropriate.

### Windowed evidence

Milestone 1 records current-surface walkthroughs for both protagonists with a
single-button mouse. M4c records both complete paths. Evidence names the build,
data identity, platform, route checkpoints, failures encountered, and successful
rerun. A failed item is fixed and rerun; it is not waived.

### Regression gates

Each milestone runs its focused proof, then:

```bash
.venv/bin/pytest -q
make prove
```

Mouse, shell, gameplay, combat, rendering, and headless boundaries that predate
the milestone must remain green.

## Plan suite

After written-spec approval, the implementation planning phase produces these
ordered task-level plans:

1. `docs/superpowers/plans/2026-08-24-mouse-accessibility-hardening.md`
2. `docs/superpowers/plans/2026-08-24-m4a2-persistence-mouse-parity.md`
3. `docs/superpowers/plans/2026-08-24-m4b-media-mouse-parity.md`
4. `docs/superpowers/plans/2026-08-24-m4c-completion-mouse-gate.md`

Each plan must verify its owning feature's live code and FITD anchors before
fixing interfaces or test goldens. A plan may depend on earlier plan contracts,
but implementation stops at each milestone's acceptance boundary.
