# Alone in the Dark 1 — M3e Mouse Reachability and Combat Design

Date: 2026-08-23
Status: Approved — planning input
Reference: FITD (`/Users/felipe.dos.santos/code/theirs/FITD`, GPLv2) —
`inventory.cpp`, `mainLoop.cpp`, `main.cpp`, `track.cpp`, `animAction.cpp`;
port activation path: `game.py`, `playworld.py`, `anim_action.py`
Builds on: M3b (interaction and inventory), M3c (combat runner and venue),
M3d (point-and-click movement and interaction)

## Goal

Close the mouse-reachability gaps in the implemented M3 gameplay surface:
open and operate the inventory with one left button, aim the one real-data
player combat route at a clicked enemy, and add a regression gate covering
the mouse routes that exist today.

This is **M3e, a prerequisite to the conclusion**, not the conclusion itself.
The approved build-conclusion design still owns M4a shell/persistence, M4b
audio/sequences, and M4c start-to-ending closure. Each M4 slice must extend
the mouse contract and its journeys when it adds a player capability.

## Scope

- Add a persistent, visible inventory hotspot during mouse-controlled PLAY.
- Resolve HUD, combat-target, interactable, floor, and blocked pointer targets
  through one function used by both hover feedback and left-click routing.
- Let a click on the supported combat target stop the hero, face the target,
  and run the combat action exposed by the in-hand inventory object.
- Add an exhaustive declared-capability contract plus real-data mouse journeys
  behind `make prove-mouse-only`.
- Record windowed, single-button manual evidence for the new routes.

## Non-goals

- M4 menus, character selection, save/load, control configuration, audio,
  sequences, packaging, or the ending.
- Claiming a start-to-ending mouse playthrough before M4c records one for both
  protagonists.
- Inventing player melee or firearm routes. Real-data measurement found no
  inventory action that reaches them.
- Changing FITD combat collision, damage, LIFE, or animation-action semantics.
- Narrowing the generic `0x2000` action bit to the clicked actor.
- Adding right-click, double-click, drag, press-and-hold, or a key-and-mouse
  chord. One left button remains sufficient.
- Adding a UI dependency. The existing pygame-ce facilities are sufficient.

## Evidence and corrected findings

### Inventory is currently unreachable by mouse

`Command.OPEN_INVENTORY` is produced only by Return or `i` in
`ui.event_to_input`. The PLAY mouse branch calls `route_play_click`, while
`route_mouse` handles only an already-open modal. A mouse-only player can take
an object but cannot reopen the inventory to choose one of its actions.

Opening is allowed only when all of these are true:

- mode is PLAY and no modal is active;
- input mode is MOUSE for the HUD route;
- `status_screen_allowed` is true; and
- the current inventory is non-empty.

The old draft omitted the last condition even though `route_command` enforces
it. Drawing an enabled button without it would advertise a click that does
nothing and could expose `_inventory_view` to an empty object list.

### Attacking remains an inventory action

FITD sets the action bit from the selected inventory action
(`inventory.cpp:359-365`):

```c
action = 1 << (inventoryActionTable[selectedActions] - 23);
```

The port preserves that route in `interaction.choose_inventory_action`; it
sets the in-hand object and action bit, then runs that object's `found_life`.
The combat click must delegate to this function rather than arm
`anim_action_type` directly.

Measured against the original data at the combat venue:

| Inventory action id | Objects offering it | Combat state within 20 ticks |
|---|---:|---|
| 32 | 63 | `WAIT_ANIM_THROW` (6) |
| 33 | 70 | none |
| 23 | 30 | none |
| 25 | 19 | none |
| 24, 26, 27, 29, 30, 31 | 1–4 each | none |

Action 32 is therefore the only measured player combat action. The name
“throw” is inferred from behavior; code depends only on the id and observed
state.

Selecting action 32 in the inventory already begins the throw. Fresh real-data
probes found that action 23 leaves an object in hand and in inventory without
arming combat, while action 32 arms the hero's `WAIT_ANIM_THROW`. Object 13 is
not a valid proof projectile: its measured force is zero and its release cube
is blocked at the unmodified venue. Real object 38 exposes both actions, arms
force 2, and completes a hit when the deterministic fixture places the hero at
`(-7400, -4010, -1000)` and world object 222 at
`(-7400, -4010, -1250)`. The combat journey therefore uses object 38, selects
action 23 first, returns to PLAY, and then clicks the enemy; the enemy click
selects action 32 through the same inventory-action path. It must not describe
action 32 as an equip-only operation.

### A thrown object needs one narrow activation repair

At the release frame, `_prepare_throw` moves the carried world object into the
current stage and room. The port defers `spawn_stage_actors` until the end of
the tick, but a later LIFE in the same tick can evaluate an actor-only property
of that object while `obj_index == -1`; the real object-38 journey raises before
launch. Calling the whole active-list regeneration in the middle of the actor
pass would have a wide ordering impact.

M3e instead extracts the existing single-object initialization body from
`spawn_stage_actors` as `activate_world_object(game, object_idx)`. The normal
active-list loop delegates to it, and `_prepare_throw` calls it immediately
after publishing the released object's stage/room/flags. No collision, damage,
LIFE, or animation-action rule changes.

### The supported target proxy is venue-scoped

At `COMBAT_VENUE`, exactly one live non-hero actor is `AF_ANIMATED`: actor 12,
world object 222. It is also the only actor in follow track mode 2. For M3e,
“combat target” means a live, `AF_ANIMATED`, non-hero actor. This is a runtime
proxy, not a claim that the engine can classify hostility on every floor.

M4c must validate or refine the proxy against both recorded complete journeys.
Until then, acceptance is deliberately limited to world object 222 at the
supported venue.

### A one-shot `_turn_toward` call does not face the hero

`tracks._turn_toward` starts a 60-tick `RealValue` and evaluates it at the
same `game.timer`. A direct probe from beta 0 toward `(1000, 0)` left beta at
0 and only scheduled an end value of 256. Calling it once before arming an
attack therefore does not implement “face, then attack.” Renaming or changing
it would affect follow, mouse movement, scripted tracks, and stairs.

The combat path instead adds a narrow public `face_toward` helper while
leaving `_turn_toward` and all five existing callers unchanged. It repeatedly
uses FITD's existing `cap_objet` direction predicate with four-angle-unit
steps: while the predicate is non-zero, set `actor.direction` to its result and
set `actor.beta = (actor.beta - actor.direction * 4) & 0x3FF`. On alignment,
set direction to zero and clear any pending `actor.rotate` interpolation so a
later track update cannot restore the old facing. The loop is bounded at 256
iterations. A probe over 10 target directions and all 1,024 starting betas
converged in at most 128 iterations. This is an instantaneous point-and-click
facing adaptation; it does not alter FITD's ordinary interpolated movement.

## Decisions

1. **Focused M3e slice.** Do not fold M4 into this spec or its plan.
2. **One top-level pointer resolver.** HUD and world clicks cannot disagree
   with hover feedback.
3. **Attack from the current position.** Cancel navigation, stop movement,
   face, then delegate to the inventory action. Never walk toward the enemy.
4. **One existing combat route.** Ship `COMBAT_ACTIONS = frozenset({32})`;
   extend it only after a real route is measured.
5. **Visible inventory hotspot.** Keep M3d's single-left-click rule; do not use
   an invisible edge band or right-click.
6. **Contract plus journeys.** Static exhaustiveness catches new declared
   commands/modes; real journeys catch routes that exist only on paper.
7. **Documented fixture boundaries.** Do not pretend the current engine can
   travel naturally from the attic to the floor-5 debug venue.
8. **Separate manual combat start.** Keep `make run-combat` unchanged for M3c;
   add `make run-mouse-combat` for the deterministic object-38 mouse proof.

## Pointer architecture

```text
MOUSEBUTTONDOWN(left)
        |
        v
window_to_logical
        |
        v
resolve_play_click  <---------------- hover uses the same result
        |
        +-- inventory --> route_command(OPEN_INVENTORY)
        +-- attack -----> attack_in_hand(target actor)
        +-- target -----> existing NavIntent to an interactable
        +-- walk -------> existing NavIntent to a floor point
        `-- blocked ----> no-op
```

### Resolver contract

`resolve_play_click(game, floor, logical_pos, draw_list)` retains its tuple
shape but makes the payload explicit by kind:

| Kind | Payload |
|---|---|
| `inventory` | `None` |
| `attack` | target actor index |
| `target` | existing `(x, z, room, world_object_idx)` navigation tuple |
| `walk` | existing `(x, z, room, -1)` navigation tuple |
| `blocked` | `None` |

Resolution order is:

1. reject invalid state, non-mouse input, missing camera, or missing hero;
2. inventory HUD, when the shared availability predicate is true;
3. the topmost actor whose draw-list entry is either a combat target or an
   existing interactable;
4. a walkable floor point;
5. blocked.

The actor candidates are unioned before the existing `pick_actor` call, so
the current painter order still determines the topmost actor. Once selected:

- a combat target with an available combat action resolves to `attack`;
- a combat target without one resolves to `blocked`, preventing the same click
  from becoming an accidental floor walk;
- an interactable resolves through the unchanged M3d target path.

This preserves non-combat target/floor behavior. It intentionally adds combat
targets ahead of the floor, which means the old statement “click priority is
unchanged” is no longer made.

`route_play_click` gains the `ModalSession` it needs for the inventory branch,
then switches on the resolved kind. It calls the existing `route_command` for
inventory rather than creating a second modal-opening implementation.

### Cursor honesty

`render_cursor` gains distinct `inventory` and `attack` presentations using
the existing `pygame.draw` primitives. The five kinds must produce distinct
pixel output. Hovering the HUD reports `inventory`; hovering an armed combat
target reports `attack`; unavailable combat reports `blocked`.

The software cursor is drawn after the HUD. Manual evidence must confirm that
the operating-system pointer does not obscure it. If both are visible, use
`pygame.mouse.set_visible(False)` for the running window rather than adding a
cursor library.

## Inventory HUD

`ui.PlayLayout.INVENTORY = pygame.Rect(4, 4, 28, 20)` is the sole inventory
hotspot. `ui.render_play_hud(frame, *, inventory_available)` draws it with the
existing `_button`, font, Surface, and blit helpers and never reads or mutates
game state.

`__main__.inventory_hud_available(game)` is the shared policy used by drawing,
resolution, and click routing. It is true only for mouse-controlled PLAY with
no modal, a valid camera and hero, status-screen permission, and at least one
inventory item. The camera/hero guards keep a transition frame from drawing a
HUD target that the resolver must reject.

The logical rectangle is scaled by the existing 320x200 presentation path.
Hit-testing uses `Rect.collidepoint`; its right and bottom edges are exclusive,
so boundary tests use `rect.right - 1`/`rect.bottom - 1` for inside and
`rect.right`/`rect.bottom` for outside. No new dependency is introduced.

## Combat route

### Discovering the action

`interaction.COMBAT_ACTIONS = frozenset({32})` is the measured extension
point. `combat_action_for(game, object_idx) -> int | None` preserves the order
returned by `inventory_actions` and returns the first member also present in
`COMBAT_ACTIONS`. It returns `None` when:

- the object is not in the current inventory;
- it exposes no measured combat action; or
- the hero already has a non-zero `anim_action_type`.

These checks prevent a stale in-hand id or click-spam during an active attack
from duplicating a throw.

### Facing and arming

`interaction.attack_in_hand(game, target_actor_idx)`:

1. revalidates the hero, target, in-hand membership, idle combat state, and
   selected combat action;
2. calls `cancel_nav_intent`, clears the current navigation decision, and sets
   the hero's speed to zero;
3. expresses a cross-room target in the hero's room frame using the same FITD
   follow conversion as `track.cpp:265-273`:
   `target_x += dx`, `target_z -= dz`, where
   `(dx, _, dz) = room_delta(game, hero.room, target.room)`;
4. calls the new `tracks.face_toward` helper;
5. delegates to `choose_inventory_action(game, in_hand, action_id)`.

It returns the existing boolean continuation result from
`choose_inventory_action`. It never writes `anim_action_type`, hit fields,
health, or LIFE directly.

The expected state sequence is precise: the hero first reaches
`WAIT_ANIM_THROW`; after the release frame, the spawned thrown actor reaches
`THROW_OBJECT`; that thrown actor, not the hero, publishes the hit.

## Mouse-only contract

`PyAitD/mouse_contract.py` is a new pygame-free module that declares:

- `PlayerCapability`, the canonical current user-facing operations;
- `CAPABILITY_ROUTES`, one single-left-click or window-chrome route per member;
- `MODE_MOUSE_CAPABILITIES`, the capabilities available in every `GameMode`;
- the named replacement for each legacy keyboard-only movement command.

The initial capabilities cover:

- walk to a floor point and approach/interact with an object;
- take or leave a found object;
- open inventory, select an object, and select an action;
- page and close reading, and dismiss a picture;
- attack the supported target;
- restart after game over; and
- quit through the window close control.

Tank-direction commands are implementation controls replaced by
`WALK_TO_POINT`; they are not separate mouse gestures. `TOGGLE_INPUT_MODE`
leaves the mouse scheme and is documented as such rather than being used as a
general `KEYBOARD_ONLY` escape hatch.

`tests/test_mouse_only.py` compares the declared tables with the concrete
`Command` and `GameMode` enums:

- every `PlayerCapability` has exactly one route;
- every `GameMode` has declared mouse capabilities;
- every `Command` has either a mouse capability or a named legacy replacement;
- a new enum member without a contract entry fails the test.

This gate enforces declared input surfaces; it cannot discover a completely
undeclared semantic feature. The journeys below are the independent guard
against that limitation.

## Journey and fixture boundaries

The old draft described one impossible continuous journey: the floor-5 debug
venue has no acquired floor-0 throwable, while natural attic-to-venue travel
depends on unfinished M4c paths. M3e uses three real-data journeys instead.

1. **Attic interaction and inventory.** Start from `init_game`, click the real
   lamp, run ticks until the real found modal, click Take, open inventory from
   the HUD, select the lamp, and select a real non-combat action. No `Command`
   is injected by the test.
2. **Combat venue.** Start through
   `scenario.enter_mouse_combat_fixture`, which first enters `COMBAT_VENUE`,
   then places real object 38 in the inventory using the same state
   postconditions as a completed take, relocates the hero to
   `(-7400, -4010, -1000)`, and relocates world object 222 to
   `(-7400, -4010, -1250)`. It freezes only the target's LIFE/track movement so
   the proof measures the player's force-2 throw rather than an enemy hit that
   overwrites `hit_force` before release. The helper is the shared setup for
   the automated journey and `make run-mouse-combat`; `make run-combat` keeps
   its existing real-enemy behavior. Mouse clicks open the HUD, select action
   23 to put object 38 in hand, return to PLAY, and click world object 222.
   From that point, only the real found LIFE, opcode, action runner, activation,
   and collision paths may arm and publish the throw.
3. **Death and restart.** Use the existing real enemy/death journey. After the
   game-over delay, a synthetic left click requests restart through the real
   event-pump branch. No restart command is injected directly.

Fixture mutation is allowed only before each journey's audited sequence and
is listed in the test name or docstring. Once auditing begins, player actions
enter as `pygame.event.Event` mouse events. The run-loop test patches rendering
and time as existing runtime tests do; it does not bypass the event pump by
calling `route_command` itself. Pygame-ce explicitly supports constructing and
posting emulated system events, so no event-test library is needed.

## Invariants

- `interaction.py`, `mouse_contract.py`, `playworld.py`, `anim_action.py`,
  `life_ops.py`, and `effects.py` import no pygame, ModernGL, rendering, or
  event-pump modules. The existing deferred `FoundResult` import from `ui.py`
  in `interaction.py` is not widened into a UI behavior dependency.
- `ui.py` only presents state and reduces/hit-tests UI input. It never mutates
  world, actor, inventory, navigation, or LIFE state.
- `__main__.py` retains the sole event pump, game/floor replacement authority,
  and one present per outer frame.
- One top-level resolver drives PLAY hover and PLAY clicks, including the HUD.
- Existing `_turn_toward` behavior and its callers are unchanged.
- Combat is armed only through `choose_inventory_action`.
- An attack click cancels navigation and does not move toward the target.
- Every interaction requires at most one left click per decision; no precision
  gesture, chord, drag, double-click, or hold is introduced.
- Real-data goldens are measured, isolated per probe, and never guessed.

## Error handling

- An unavailable inventory HUD is not drawn, does not resolve as `inventory`,
  and cannot open a modal.
- Clicking a combat target with no valid idle in-hand combat route resolves as
  `blocked` and is a no-op.
- `attack_in_hand` revalidates everything the hover checked because state may
  change between motion and click. A failed revalidation returns without
  mutation.
- `choose_inventory_action` retains its `ValueError` contract for invalid
  direct callers; the click path prevents that error by construction.
- `face_toward` raises with actor beta and target coordinates if its 256-step
  convergence bound is ever exhausted; silently aiming in the wrong direction
  is forbidden.
- A modal always owns its click before PLAY routing. The HUD is neither drawn
  nor hit-tested while a modal is active.
- Letterbox/out-of-frame coordinates remain `None` and do nothing.

## Automated verification

### Pure and focused tests

- HUD availability covers mode, modal, input mode, status permission, empty
  inventory, and non-empty inventory.
- HUD render output differs from the input frame without mutating it.
- `Rect.collidepoint` boundary cases pin the exclusive right/bottom edges.
- Resolver cases cover every payload row and the topmost union of combat and
  interactable actor candidates.
- HUD resolution proves the click does not also create a navigation intent.
  The outside-boundary case spies on world routing rather than assuming that
  the top-left background is walkable.
- Cursor output is distinct for `inventory`, `attack`, `target`, `walk`, and
  `blocked`; hover and click consume the same resolver result.
- `combat_action_for` rejects missing, removed, non-combat, and currently busy
  items and deterministically chooses from ordered inventory actions.
- `face_toward` covers all 1,024 starting betas for representative directions,
  the convergence bound, and cross-room coordinate conversion.
- `attack_in_hand` cancels an existing intent, stops speed, faces first, and
  delegates the exact object/action arguments without writing combat state.

### Real-data tests

- The venue proxy accepts only actor 12/world object 222 among the live venue
  actors and rejects the hero.
- A fresh isolated probe per object/action derives the combat-action set and
  asserts it equals `{32}` within the stated 20-tick observation window.
- The attic, combat, and death/restart journeys follow the fixture rules above.
- Combat asserts hero `WAIT_ANIM_THROW`, then thrown-actor `THROW_OBJECT`, then
  victim `hit_by == thrown_actor_idx` and the measured published force `2`.
- Existing M3d tests remain unchanged except for mechanical `ModalSession`
  arguments required by the expanded PLAY router.

### Proof target and regression gate

`make prove-mouse-only` runs `tests/test_mouse_only.py` with SDL's dummy video
and audio drivers. It is distinct from `make prove-mouse`, which remains the
navmesh census. After non-trivial implementation changes, the full gate stays:

```bash
.venv/bin/pytest -q && make prove
```

Every implementation task observes its new test failing before the production
hunk is added. The proof target must be seen failing at the first missing mouse
route before it is made green.

## Manual windowed evidence

Extend the existing M3d/M3b proof rather than claiming automation proves motor
accessibility. Using `make run` and `make run-mouse-combat`, record:

- single-button completion of found, HUD inventory, object/action selection,
  reading, combat click, game-over restart, and window close;
- successful clicks near every corner of the 28x20 logical HUD target;
- no world action from a HUD click and no action from letterbox coordinates;
- one visible, honest cursor over HUD, attack, target, walk, and blocked areas;
- no cursor or clickable HUD advertised in keyboard mode;
- the hero stops, visibly faces world object 222, and throws toward it without
  first walking; and
- the window remains responsive while every modal is left open for ten seconds.

M4a, M4b, and M4c extend this evidence with their screens and both complete
protagonist journeys. M3e alone does not satisfy the final release gate.

## Assumptions and risks

- Action 32's behavior is measured, while its display-name meaning is inferred.
- `AF_ANIMATED` is a clean target proxy only at the supported venue. M4c must
  replace or validate it before claiming all-floor mouse combat.
- Melee and firearm remain unreachable through real player data. This slice
  does not relabel synthetic opcode-runner tests as player routes.
- A declared registry can be updated dishonestly or bypassed by failing to
  declare a semantic feature. Enum exhaustiveness plus independent journeys
  reduce that risk; review remains necessary.
- The HUD occupies 28x20 pixels of the 320x200 logical frame. Placement is a
  constant and can move if manual evidence finds an obstruction, without
  changing the routing design.
- Direct facing is a modernization at the input boundary. Ordinary FITD track
  interpolation and combat physics remain unchanged.

## Planning boundary

This document defines the M3e behavior and verification contracts only. After
review approval, write one task-level TDD implementation plan for M3e. Do not
fold M4a, M4b, or M4c implementation into that plan.
