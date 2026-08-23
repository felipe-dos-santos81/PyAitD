# Alone in the Dark 1 — M3c: Combat + Multi-Floor Integrity Design

Date: 2026-08-23
Status: Approved (revised after architecture review)
Reference: FITD (`/Users/felipe.dos.santos/code/theirs/FITD`, GPLv2) —
`animAction.cpp`, `mainLoop.cpp`, `life.cpp`, `evalVar.cpp`, `main.cpp`
Builds on: M1 (data), M2 (actors), M3a (LIFE VM), M3b (interaction),
mouse-only input (`2026-08-23-mouse-only-input-design.md`)

## Goal

Make combat work: an enemy that reaches the player can hit them, the player
can hit back, and death ends the game. Plus the multi-floor work that combat
needs in order to be testable against real game data at all.

## The finding that motivates this

The reported symptom was "the enemy is not attacking the player". Investigation
found the enemy **does** pursue: on floor 5 room 4, world object 222 spawns with
`track_mode 2` (follow), `anim 199`, `speed 4`, and closes on a stationary hero
to 357 units before circling. Pursuit has worked all along.

What is missing is the swing. FITD's `GereFrappe` — the per-actor pass that turns
an attack animation into a published hit — is not ported. `LM_HIT` is a stub that
consumes its six arguments and sets `anim_action_type = 0`, discarding the attack
outright. Consequently `actor.hit` and `actor.hit_by` are written **only** to
`-1` anywhere in the codebase (initialised `game.py:369-370`, reset every tick
`playworld.py:131`), and are otherwise only read. No hit can land anywhere in the
game, on any floor, by anyone.

## Scope

This spec is **①+② of a three-way decomposition** of "completable", combined at
the user's explicit direction after the size risk was raised:

- **① Combat core** (this spec) — the `GereFrappe` runner, real `LM_HIT` /
  `LM_FIRE` / `LM_THROW`, hit publication, death and game over.
- **② Multi-floor integrity** (this spec) — only what combat needs to be
  testable: the `evalVar` out-of-floor fix and one reusable, named floor-5
  combat venue shared by manual and automated proof.
- **③ Ending** (NOT this spec) — `LM_END_SEQUENCE` and the win path.

Because ①+② together are roughly the size of the mouse-input branch — whose
whole-branch review found three Critical **seam** defects that fourteen per-task
reviews all passed — this spec keeps an explicit internal phase boundary
(Architecture, "Phase boundary") so the two halves can be reviewed as separate
surfaces rather than one undifferentiated diff.

## Non-goals

- A damage system. Damage is script-side; see "The runner publishes, scripts
  decide" below.
- Menus, audio, save/load (M4). `InitSpecialObjet` stays the visual stub it is.
- `LM_END_SEQUENCE` and completability.
- Proving a player can *walk* from the attic to floor 5. This spec guarantees the
  engine can correctly *be* on a floor, not that the game leads there.
- Fixing FITD's preserved quirks (see Invariants).

## Context discovered

Established by reading FITD and by throwaway probes against real game data.

### The runner and where it belongs

- `GereFrappe` (`animAction.cpp:15`, 457 lines) is called from
  `mainLoop.cpp:143`, **inside the same per-actor loop** as `GereAnim` and
  `GereDec`, gated on `animActionType`. `playworld._anim_pass` already performs
  the first two in that exact loop; M3c adds the runner plus the render-independent
  hot-point refresh described below.
- FITD handles nine action values: 1 `WAIT_FRAPPE_ANIM`, 10
  `WAIT_FRAPPE_FRAME`, 2 `FRAPPE_OK`, 4 `WAIT_TIR_ANIM`, 5 `DO_TIR`, 6
  `WAIT_ANIM_THROW`, 7 `THROW`, 8 `HIT_OBJ`, and 9 in-flight throw. Value 3
  is named `DONE_FRAPPE` but has no switch arm and is never produced.

The three opcode setup contracts are fixed before the runner:

| opcode | AITD1 operands | accepted-animation mutation |
|---|---|---|
| `LM_HIT` | raw anim, raw start frame, raw hot-point group, raw cube half-size, `evalVar` force, raw next anim | `init_anim(anim, 0, next)`; state 1, action anim/frame/param, hot-point id, force |
| `LM_FIRE` | six raw values: anim, fire frame, hot-point group, cube half-size, force, next anim | `init_anim(anim, 2, next)`; state 4, action anim/frame/param, hot-point id, force |
| `LM_THROW` | seven raw values: anim, throw frame, hot-point group, world object, rotated flag, force, next anim | `init_anim(anim, 2, next)`; state 6, action anim/frame/object, hot-point id, force; if rotated flag is zero subtract `0x100` from the thrown world's gamma; set its found flag `0x1000` |

If `init_anim` rejects an animation, the opcode still consumes every operand but
does not arm or partially mutate action state, matching FITD `hit`, `fire`, and
`throwObj`.

### The runner publishes, scripts decide

`FRAPPE_OK` computes a hit point (`roomX + hotPoint + stepX`, and the same on
y/z), builds a cube of `±animActionParam` around it, calls `CheckObjectCol`, and
for each touched actor sets the attacker's `HIT`, the victim's `HIT_BY`, and the
victim's `hitForce` — then stops at the first `AF_ANIMATED` victim. **It never
touches `life`.**

That is not an omission in FITD: `actor.life` in this port is the **LIFE script
index**, not health (`life_gate` gates on it; `LifeFrame(index, actor.life)`
runs it). Health lives in script vars. Scripts read the published hit through
`evalVar` and decide what it costs.

Those three `evalVar` codes are **already ported and already correct** —
`0x03` HIT, `0x04` HIT_BY (`eval_var.py:67-70`), `0x1A` hit_force
(`eval_var.py:133`). They return `-1`/`0` today only because nothing writes the
fields. The moment the runner writes them, existing enemy scripts begin working
with no further wiring. This is why combat is "publish hits faithfully", not
"build a damage system".

### Cost is lopsided across the arms

| arm | states | ~lines | needs | port has |
|---|---|---|---|---|
| melee | 1→10→2 | 55 | `hotPoint`, `CheckObjectCol` | `check_object_col` ✅; hot point new |
| shoot | 4→5 | ~145 | `checkLineProjectionWithActors`, `InitSpecialObjet` | integer step/room/cube helpers ✅; sweep new |
| throw setup | 6→7 | 90 | thrown body's ZV, hard collision, put/remove inventory | body registry, `check_hard_col`, `put_at_objet`, `remove_from_inventory` ✅ |
| hit-object | 8 | **0** | — the case is literally `break;` | already equivalent ✅ |
| in-flight | 9 | **187+** | actor/zone/hard collision, reverse, stopping placement | most primitives ✅; `throw_stopped_at` new |

- **Case 8 needs no work.** `LM_HIT_OBJECT` sets state 8 and the runner does
  nothing with it; the port's `op_hit_object` already matches.
- **`InitSpecialObjet` is not on the critical path.** It spawns muzzle flash and
  impact *visuals*. The combat contract is publishing HIT/HIT_BY/hitForce, which
  is unaffected. Shoot ships with it left stubbed; only
  `checkLineProjectionWithActors` is logically required.
- **Throw is atomic.** States 6, 7, and 9 together are the real `LM_THROW`
  behavior. State 9 may land last, but M3c is not complete until it lands; if it
  is split into a follow-up branch, that branch remains part of this milestone's
  completion gate.

### The hot point crosses the repo's hardest boundary

`getHotPoint` (`main.cpp:2976`) reads the **skinned vertex buffer** —
`pointBuffer[group.m_baseVertices]`, gated on `body.flags & 2` — and FITD calls
it at `main.cpp:3071`, inside `AllRedraw`, the *render* path. This port keeps
simulation (`playworld`, pygame-free, headless) separate from rendering.
`hot_point` is declared at `game.py:101` and **never written**.

Two details are part of the contract:

- FITD's `AffObjet` applies the actor's `(alpha, beta, gamma)` before
  `getHotPoint`; the point therefore includes the same group-0 actor rotation as
  `skel.skin`, not only animation group deltas.
- `AllRedraw` refreshes the cached point after the LIFE pass. The next tick's
  `GereFrappe` consumes that previous-pose value after `GereAnim`. In the
  headless port, refreshing an armed actor's point **immediately before** its
  next `GereAnim` reproduces the same pose without coupling simulation to a
  rendered frame.

The primary venue enemy is world object 222, body 234; real data reports body
flags `3`, so `flags & 2` is confirmed for the reported enemy rather than left
as an assumption.

### Shooting sweep, examined

FITD's `checkLineProjectionWithActors` (`main.cpp:3863-3946`) is an 84-line
integer stepped-volume sweep, not a screen-space line test:

1. Build a cube of `±param` at the hot point.
2. Advance X/Z by `walkStep(param * 2, 0, beta)` each iteration, preserving the
   port's crossed `walkStep` output convention.
3. Preserve FITD's counterintuitive `AsmCheckListCol` branch: terminate with no
   actor when the cube overlaps **no** hard-collision entry. While it overlaps at
   least one entry, inspect actors. This is verified source behavior, not a
   conventional raycast to "correct."
4. Inspect live actors in slot order, excluding the shooter and `AF_SPECIAL`,
   adjusting the cube between rooms before `cube_intersect`; also terminate when
   X/Z leaves `[-20000, 20000]`.
5. Return `(actor_idx, impact_x, impact_y, impact_z)`, where the impact position
   is FITD's last pre-step `tempX/tempZ`; return `actor_idx == -1` for no hit.

The tuple replaces FITD's `animMoveX/Y/Z` output globals. `DO_TIR` publishes the
hit from it and may update `actor.hot_point` exactly as FITD does.

### Throw dependencies, examined

State 6 needs the **thrown world object's** raw body ZV
(`game.assets.body(world.body).zv`). `life_ops._body_zv(vm)` is deliberately not
reused: it is VM-bound and returns the thrower's body, which is the wrong object.

States 7 and 9 reuse `check_object_col`, `check_hard_col`, `point_in_zone`, the
existing integer rotation/walk-step math, and `init_real_value`. A local
`throw_stopped_at(game, actor_idx, x, z)` ports FITD `main.cpp:4036-4132`: search
backward in 100-unit steps for a hard-collision-free placement, apply the
2,000-unit Y-band/reachability rule, zero speed/action/gamma/steps, rebuild the
ZV from the thrown body's raw ZV, and update found flags (`|= 0x4000`,
`&= ~0x1000`). FITD's background inscription is visual-only and remains omitted;
the stopped actor remains in the ordinary renderer.

FITD calls `GenereActiveList` unconditionally at `mainLoop.cpp:247-250`, so the
world-record mutations in throw state 6 are visible as an actor before state 7.
This port deliberately gates the same work behind `flag_genere_aff_list`.
Therefore state 6 must set that existing flag after activating the thrown world
object; adding a second spawn path or spawning directly inside the actor loop is
forbidden.

### Multi-floor state, measured

- **`evalVar` out-of-floor is off by one.** FITD switches that branch on the
  **raw** tag (`evalVar.cpp:193-205`: `case 0x1F` room, `case 0x26` stage) and
  decrements only afterwards. The port decrements first (`eval_var.py:186`) and
  then compares against those same constants, so it rejects exactly the two cases
  FITD supports. Correct comparisons are `0x1E` and `0x25`. **Confirmed by
  experiment: applying the fix boots floor 3, which previously crashed.**
- Floors 0, 1, 7 boot and run 600 ticks clean today. Floor 3 boots with the fix.
  Floors 4 and 5 boot once the hero is relocated onto them.
- `--floor N` sets `current_floor` but leaves the hero's world object at
  `stage 0`, so the hero never spawns and scripts querying it hit the out-of-floor
  path. This is a debug-harness gap, not a gameplay one.
- **The venue works.** Reproducing `op_stage`'s actor mutations plus the
  subsequent floor/room/spawn post-conditions transitions to the pinned start
  `(floor=5, room=4, x=-7800, y=-4010, z=-1000, camera_slot=0)`: 48 actors
  spawn, obj222 appears as an actor with `track_mode 2` / `object_type 0x0141`,
  and it pursues the hero for 1200 ticks without error.
- The game has exactly **five** chasers (`track_mode == 2`), all with
  `track_number 1` (following world object 1, the hero): objects 20, 79, 180 at
  `stage -1` (script-spawned), 222 at stage 5 room 4, 40 at stage 6 room 6.
  **None is on stage 0**, and none spawned on any bootable floor across 3000
  ticks — which is why combat has no natural test venue without ②.
- All 87 opcode slots have implementations. Remaining stubs: the 5 M3c ones,
  `LM_END_SEQUENCE`, and four cosmetic (`RND_FREQ`, `SHAKING`, `WATER`,
  `STOP_SAMPLE`).

## Decisions (agreed with user)

1. **Scope is ①+② combined**, with ③ deferred — chosen after the size risk was
   stated explicitly.
2. **Vertical slice first** (approach A): establish the real venue before
   building combat, so combat is verified against real game data rather than
   fixtures.
3. **Implementation order within the runner**: melee → hit-object (free) →
   throw setup → shoot → in-flight. Dependency and value order; in-flight is
   last but remains required for M3c completion.
4. **`InitSpecialObjet` stays stubbed.** Visual only.
5. **Death restarts the floor.** Menus are M4; restart is the only option that
   keeps the game playable end-to-end and lets a tester die repeatedly.
6. **`GameOver` is a modal effect, not a new mode mechanism.**
7. **The debug harness exposes one named combat venue, not generic floor
   relocation.** `--floor 0` remains valid; a non-zero `--floor` is rejected with
   a message directing the user to `--combat-venue`, because a floor number has
   no honest room/coordinate mapping.

## Architecture

### Phase boundary

The two halves are deliberately separable and should be reviewed as such:

- **Phase A (②)** — `evalVar` fix, shared actor-stage relocation, named venue,
  `--combat-venue`, and `prove-combat` skeleton. Touches `eval_var.py`,
  `game.py`, `life_ops.py`, `scenario.py` (new), `__main__.py`, tests, Makefile.
- **Phase B (①)** — `anim_action.py`, `skel.hot_point`, real `LM_HIT`/`LM_FIRE`/
  `LM_THROW`, `GameOver`. Touches `anim_action.py` (new), `skel.py`,
  `life_ops.py`, `effects.py`, `playworld.py`, `ui.py`, `__main__.py`.

Phase A lands first and completely, because Phase B's integration tests depend on
its shared venue scenario.

### New modules

**`PyAitD/scenario.py`** — pygame-free supported debug scenarios. It owns the
pinned combat-venue constants and `enter_combat_venue(game)`. The function calls
the same actor-stage relocation service as `LM_STAGE`, applies the normal
floor/room/spawn post-conditions, records the venue as the restart point, and is
the one implementation used by `--combat-venue`, integration tests, and
`make prove-combat`.

**`game.FloorStart`** — a frozen `(stage, room, x, y, z, camera_slot)` value.
`Game.floor_start` identifies the current restart boundary and
`Game.restart_requested` is the outer-loop request flag. These are session state,
not UI presenter state.

**`PyAitD/anim_action.py`** — pygame-free, joins the layer-purity probe set.
`refresh_hot_point(game, actor_idx)` and `gere_frappe(game, actor_idx)` implement
the cached-point boundary and FITD action dispatch. The module consumes existing
pure collision, room-adjustment, integer movement, inventory, and RealValue
helpers; it does not import private VM helpers from `life_ops.py`.

**`skel.pose_vertices(body, group_states, actor_angles=None)`** extracts the
existing unprojected pose step from `skin`. Both rendering and combat call this
one implementation, avoiding a second skeletal transform algorithm.

**`skel.hot_point(body, group_states, actor_angles, hot_point_id) -> (x, y, z)`**
returns `pose_vertices(...)[groups[hot_point_id].base_vertices]`, or zero when
`body.flags & 2` is unset. Full-body posing is small for these assets and is
preferred over an independent single-vertex ancestry walker: sharing the
already-golden path has the smaller correctness blast radius.

The alternative, caching skinned points from the render pass and feeding them
back, is **rejected**: it would make combat depend on rendering and break
`play_tick`'s headless guarantee, which `tests/test_playworld.py` enforces with a
subprocess probe.

### The per-actor call order

`playworld._anim_pass` gains a hot-point refresh and the runner call:

```python
if actor.anim_action_type and actor.hot_point_id != -1:
    refresh_hot_point(game, index)  # previous pose, before GereAnim
if flags & AF_ANIMATED:
    gere_anim(game, index)
if flags & AF_TRIGGER:
    gere_dec(game, index)
if actor.anim_action_type:
    gere_frappe(game, index)
```

The refresh substitutes for the preceding FITD `AllRedraw`; the remaining order
is exactly `GereAnim → GereDec → GereFrappe`. No render dependency or new
tick stage is introduced, so `play_tick` remains headless.

### Game over

`game.mode` remains derived from `active_modal` via `MODAL_MODE`. Add
`GameMode.GAME_OVER` and a frozen `GameOver(delay_units=120)` modal effect.
`play_tick` processes the remainder of the LIFE actor loop, as FITD does, then
converts `flag_game_over` into that modal **before** floor/room/camera/spawn
handling, clears the flag, and returns `False`. No LIFE continuation is retained
because restart creates a fresh session.

The flag handoff matches FITD, where `FlagGameOver` is only a loop-exit flag
(`mainLoop.cpp:185, 233`) and presentation lives outside `PlayWorld`.

FITD's `LM_GAME_OVER` fades music and spins 120 chrono units **inside the
opcode**, then sets the flag (`life.cpp:2438-2450`). The fade stays skipped
(audio is M4); the delay is real pacing. This port deliberately moves only that
wall-clock wait to the modal: the rest of the current LIFE actor loop completes
immediately, but no later simulation tick runs during the wait. This differs in
when discarded post-death state is computed, not in actor-loop order or what is
rendered: `run()` keeps presenting the last successfully composed PLAY
`scene_frame`, without recomputing it, until the wait expires. Remaining actors
could observe different chrono values than in FITD, but all of that state is
discarded by the mandatory fresh restart. This responsive scheduling adaptation
avoids blocking the sole event pump for two seconds.

`ModalSession` owns one generic `elapsed_ms` counter, reused by `ShowPicture`
and `GameOver`; entering a different effect resets it. GAME_OVER ignores
keyboard and mouse dismissal until `elapsed_ms >= 120 * 1000 // 60`. During the
lock `ui.render_game_over(scene_frame, ready=False)` returns that frozen frame
unchanged. At expiry it darkens the frame and presents `Game Over` / `Click to
restart`. ACCEPT, CANCEL, OPEN_INVENTORY-as-ACCEPT, or **any left click** then
sets `game.restart_requested = True`. The whole logical frame is the mouse
target, so restart has no precision requirement and no hit rectangle is needed.

`__main__.py` must add explicit GAME_OVER branches to command routing, mouse
routing, and `render_active_mode`; otherwise its current exhaustive dispatch
raises. `ui.render_game_over(scene_frame, ready)` returns the frozen scene while
locked, then darkens it and shows a large `Game Over` / `Click to restart`
presentation when ready. UI only presents and returns intent; it never mutates
world state.

The outer `run()` loop owns restart. When `restart_requested` is observed it
calls `restart_session(old_game) -> new_game`, replaces its local `game`
reference, then loads `Floor(new_game._data_dir, new_game.current_floor)` and
only then resets `ModalSession`, input buffer, accumulator, draw-list, hover, and
frozen `scene_frame`. No tick or render occurs between those operations. The
loop continues with the existing renderer, clock, and single event pump; it does
not close or reopen the trace. `restart_session` and `enter_floor_start` perform
no `Floor` I/O. A restart load failure follows the existing initial-load error
path and exits cleanly with status 2.

`__main__.restart_session` has one construction sequence:

1. Save the selected hero, input mode, live trace sink, data directory, and
   immutable `floor_start` from `old_game`.
2. Call `init_game` to create fresh vars, actors, world objects, inventory, LIFE
   stacks, modal/effect state, and navigation state.
3. Restore the hero selection/input mode and assign the existing trace sink.
4. Call `enter_floor_start(new_game, floor_start)`, the same generic transition
   helper used by the named venue: relocate the newly created hero, select the
   recorded floor/room/camera, and regenerate that stage's actors exactly once.
5. Reassign the immutable `floor_start` and return the new game.

The named venue calls `enter_floor_start(game, COMBAT_VENUE)` and records its
pinned tuple. Initial floor 0 records the hero's initial tuple. A natural hero
`LM_STAGE` records its stage/room/coordinates with `camera_slot=0`: `LM_STAGE`
has no camera operand, and slot 0 is the deterministic entry camera before the
ordinary camera-switch pass. This is an explicit assumption to verify with a
natural floor transition; a later observed non-zero entry camera changes only
the recorded slot, not the restart design.

This is the precise meaning of **restart the current floor**. Returning to a
title screen remains M4.

### Multi-floor (Phase A)

- `eval_var.py` out-of-floor branch compares `0x1E` (room) and `0x25` (stage).
  Codes FITD itself asserts on keep raising, and the message says so, so the
  error does not read like a port gap.
- Extract `relocate_actor(game, actor_idx, stage, room, x, y, z)` from
  `op_stage`: it updates stage/room, rebases the ZV, commits room/world
  coordinates, and zeroes steps. `op_stage` remains responsible for decoding
  operands and setting floor/room transition flags. When the actor is the camera
  target and the stage changes, it also records the destination as
  `game.floor_start`.
- Add `game.enter_floor_start(game, floor_start)` beside `relocate_actor`. It is
  the single immediate-transition service for restart and supported scenarios:
  call `relocate_actor`; set `current_floor`/`new_num_etage`; clear the
  floor-change flag; call `change_salle`; set `new_num_salle`, `new_num_camera`,
  and `flag_init_view=2`; run `spawn_stage_actors` once; clear its request flag;
  and leave `num_camera=-1` for `run()`'s initialization gate.
- Add `--combat-venue` and `make run-combat`; both call
  `scenario.enter_combat_venue`. Existing `--floor 0` remains the default;
  `main()` rejects non-zero `--floor` with a concise error because a floor number
  alone cannot determine a valid room and `(x, y, z)`.
- The shared venue places the hero at
  `(floor=5, room=4, x=-7800, y=-4010, z=-1000, camera_slot=0)`, in front of
  obj222. Tests, `make prove-combat`, and manual play import this same function;
  no test-only fixture duplicates its mutations.
- `enter_combat_venue` delegates to `enter_floor_start` with the pinned tuple;
  it adds no transition mutations of its own. The resulting post-conditions
  (`current_floor/new_num_etage=5`, room 4, `new_num_camera=0`,
  `flag_init_view=2`, one spawn pass, `num_camera=-1`) are pinned in one Phase A
  test before combat code is added.

### Pygame reuse decision

Current pygame-ce documentation provides `Rect.colliderect`, `Rect.clipline`,
sprite/mask collision, and float vector helpers. They are 2D or render-oriented;
FITD combat uses integer 3D room-space cubes, cross-room adjustment, fixed-point
rotation, and preserved `walkStep` quirks. Importing pygame would also violate
the headless `anim_action.py` boundary. Therefore combat reuses the port's
existing pure helpers rather than introducing a pygame collision representation.
GAME_OVER reuses the existing pygame `Surface`, font, and alpha-composition UI
path. It deliberately needs no `Rect` hit target because any left click accepts.

## Invariants

- `anim_action.py` imports no pygame, ModernGL, `PyAitD.ui`, or `PyAitD.render`.
- `play_tick` stays headless and its FITD `mainLoop` ordering unchanged.
- Rendering and combat derive poses through the same `skel.pose_vertices` code;
  neither maintains a second skeletal transform implementation.
- The runner never writes `life`; damage stays script-side.
- `LM_THROW` is complete only when setup, launch, in-flight collision, reverse,
  and stopping placement all work.
- Only `run()` replaces a `Game` during restart; UI and LIFE handlers request it
  through typed/modal state.
- FITD-ported quirks are preserved, never "fixed" — including the two below.
- Golden values are pinned from real game data, never re-derived by guessing.

## Error handling

- `evalVar` on an out-of-floor object with a code FITD does not support keeps
  raising, with a message naming the raw tag and stating FITD asserts here too.
- `gere_frappe` on an actor whose body cannot supply a hot point
  (`body.flags & 2` unset) yields `(0, 0, 0)`, exactly as `getHotPoint` does —
  not an error.
- An out-of-range `hot_point_id` on a body with `flags & 2` raises with body and
  group details; FITD asserts the same bound in `main.cpp:2984`.
- An `anim_action_type` outside FITD's handled set
  `{1, 2, 4, 5, 6, 7, 8, 9, 10}` raises with the actor and value. This includes
  the declared-but-unhandled value 3. It is a deliberate defensive divergence:
  FITD only prints for unhandled values in `FITD_DEBUGGER` builds and otherwise
  has no default arm (`animAction.cpp:449-455`); it does **not** assert.
- A thrown object whose world record has no body raises with the object index;
  silently using the thrower's body is forbidden.

## Testing

- **Layer purity**: `anim_action.py` joins the subprocess probe set. A static
  import walk cannot substitute — deferred imports make pygame look reachable.
- **Pose/hot-point golden**: against real body 234 and at least one player combat
  body, assert `hot_point` equals the named base vertex returned by the shared
  pose path for non-zero animation group deltas and non-zero actor alpha/beta/
  gamma. Pin the no-flag zero and bad-group error cases.
- **Hot-point timing**: arm an action in the LIFE pass, assert no same-tick
  strike, then assert the next `_anim_pass` refreshes from the pre-`GereAnim`
  pose and calls `gere_frappe` after `gere_dec`.
- **The preserved fall-through is pinned by a test.** `FRAPPE_OK` sets
  `animActionType = 0` when the anim no longer matches and then falls through and
  hit-tests anyway (no `return`, `animAction.cpp:48-51`). That reads like a bug;
  a test is the only thing that stops the next reader "fixing" it.
- **Opcode setup**: `LM_HIT`, `LM_FIRE`, and `LM_THROW` consume the exact AITD1
  raw/evalVar operands, call `init_anim` with FITD's type, and arm fields only
  when `init_anim` accepts the animation. Throw also pins gamma/found-flag
  mutations.
- **Melee**: pin states 1→10→2, the fall-through, collision slot order,
  cross-room adjustment, publication to both actors, hit force, and the stop at
  the first `AF_ANIMATED` victim.
- **Fire**: pin FITD's no-hard-collision branch and ±20000 termination, first
  live non-special actor by slot order, cross-room cubes, the returned pre-step
  impact point, and HIT/HIT_BY/hitForce publication.
- **Throw**: pin obstructed setup placement, launch flags/ZV/RealValue, ignoring
  the original thrower, `REVERSE_OBJECT` reflection, actor hit publication,
  the gated active-list request between states 6 and 7, room/zone/hard stops,
  100-unit backward placement search, Y-band reachability, and final actor/world/
  found state. State 8 remains an explicit no-op.
- **Real-data enemy journey**: enter the shared venue → obj222 pursues → its
  real script arms `LM_HIT` → the frame runner publishes
  `hero.hit_by == enemy` → the hero LIFE script consumes it in that same tick.
- **Real-data survival journey**: repeat controlled real enemy hits and pin the
  script-owned health variable/checkpoint until the real script reaches
  `LM_GAME_OVER`; assert the 120-unit input lock, GAME_OVER presentation, and
  restart into a fresh copy of the identical venue. This closes the current
  damage assumption before M3c can pass.
- **Game-over scheduling**: assert the triggering tick finishes the remaining
  LIFE actors before entering GAME_OVER; later play ticks do not run; the last
  PLAY `scene_frame` is presented unchanged throughout the lock; and only the
  ready frame gains the overlay and accepts whole-frame input.
- **Restart reconstruction**: spy on `init_game`, `enter_floor_start`, floor
  loading, and stage generation to pin their order and one-call counts. Assert a
  new `Game` with fresh mutable state, identical `FloorStart`, hero/input mode,
  and the same live trace object; verify both initial floor 0 and the floor-5
  venue.
- **Natural transition restart point**: execute a real hero `LM_STAGE` fixture,
  complete the ordinary floor/room/camera handoff, and assert the recorded
  `FloorStart` camera slot is the actual entry slot. The current expected value
  is 0; update the assumption and golden if the observed FITD-backed transition
  selects another slot.
- **Player arms**: deterministic scenarios prove player melee, firearm, and
  thrown-object hits publish the correct world indices and force. These may set
  up real inventory/actors directly, but may not bypass the real opcode and
  runner states under test.
- **`make prove-combat`**, alongside `prove` / `prove-m3b` / `prove-mouse`:
  headless, runs the **same venue scenario the integration tests use** (one
  implementation, two callers). In Phase A it reports pursuit and marks combat
  arms pending without failing. The final target is a gate, not a report: enemy
  hit publication, script damage/death, game-over/restart, player melee, fire,
  throw launch, in-flight collision, and stopping placement must each pass or
  the command exits non-zero.
- **Every new test must be verified to fail with its fix reverted**, and the
  report must say so. During the mouse fix wave an implementer did this unprompted
  and it is the only reason we know that test was not decorative. This codebase
  has already produced two tests that passed while testing nothing.

**Not coverable by tests**: whether combat *feels* right — pacing, whether an
enemy that reaches you is threatening — needs `make run-combat` and a human,
which is why the harness fix is in scope.

## Assumptions

- A script-driven transition arising naturally in play behaves identically to the
  reproduced one. The venue scenario uses the same relocation service and
  transition post-conditions, but no natural playthrough was observed.
- A natural `LM_STAGE` entry uses camera slot 0 because the opcode carries no
  camera operand. The natural-transition acceptance test must replace this
  assumption with observed data if FITD selects another entry slot.
  **Resolved (task 11), slot 0 confirmed**: `LoadEtage` sets `NumCamera = -1`
  (`floor.cpp:39`), so a floor change gives `ChangeSalle` no camera continuity
  and its `int newNumCamera = 0` (`room.cpp:112`) is what reaches `NewNumCamera`
  (`room.cpp:193`). Observed on the hero's own death transition,
  `LM_STAGE(6, 6, -5000, -4000, 11500)` from LISTLIFE 555
  (`tests/test_floor_start.py::test_natural_lm_stage_records_a_reenterable_floor_start`).
  Note the port's *settled* camera differs: `change_salle` does not port that
  `NewNumCamera` assignment, so after a natural transition the ordinary
  camera-switch pass picks the slot (9 for that floor 6 / room 6 entry). Only
  `enter_floor_start` selects the recorded slot.
- Real-data probing with injected pre-LIFE hit publication confirms the hero
  script consumes `HIT_BY`/`hitForce` and changes its script-owned health state;
  reaching the complete death/game-over path remains an explicit acceptance
  test, not an assumption.
  **Correction (task 11) — which number came from where.** The pinned damage
  step `var 21: 20 -> 10` came from that *injected* probe, which published
  `hitForce 10`; it is not what the venue's own enemy does. Measured from the
  real venue with no injection: obj222's real `LM_HIT` carries **force 1**, the
  hero script subtracts the published force, so the real step is `20 -> 19` and
  the real fight is 20 landed hits from 20 to 0 (with hero LIFE `549 -> 553 ->
  549` per hit and transient var 24 `0 -> 1`). Both numbers describe the same
  subtraction; only the injected one reaches 10 in a single hit. Real-data
  anchor: `tests/test_combat_journey.py`, venue `FloorStart(5, 4, -7800, -4010,
  -1000, 0)`; death LIFE 39 at play tick 1983, `GameOver(120)` at play tick
  3958.
- Body 234 (obj222) has flags `3`, confirming hot-point availability for the
  reported enemy. Player firearm/throw bodies remain covered by the arm-specific
  real-data tests rather than assumed globally.

## Risks

- **In-flight throw is the largest arm.** It is sequenced last and may be
  developed/reviewed on its own branch, but the milestone remains incomplete
  until states 6/7/9 and stopping placement pass together.
- **Floors 2 and 6 are of unknown status.** An earlier probe appeared to show them
  crashing; that was an artifact of the probe placing an invalid room index before
  the floor swap, and the claim was retracted. They are simply untested.
  **Update (task 11)**: floor 6 is now exercised end to end by the real death
  sequence (`LM_STAGE(6, 6, ...)` from LISTLIFE 555 through `LM_GAME_OVER`).
  Floor 2 remains untested.
- **Combined scope.** ①+② is roughly the size of the mouse-input branch, whose
  whole-branch review found three Criticals invisible to per-task review. The
  phase boundary above is the mitigation; if the branch grows past it, the halves
  should be split into separate branches rather than reviewed as one diff.
- **Natural death timing is not yet measured.** Injected hits confirm script-side
  health mutation, but the real enemy-hit → death animation/script →
  `LM_GAME_OVER` duration is intentionally left to the real-data survival
  acceptance test; the plan must not replace it with a synthetic flag write.
