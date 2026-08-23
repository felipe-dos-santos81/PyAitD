# Alone in the Dark 1 — M3c: Combat + Multi-Floor Integrity Design

Date: 2026-08-23
Status: Approved (design)
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
  testable: the `evalVar` out-of-floor fix, `--floor N` hero relocation, and a
  reusable combat-venue fixture.
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
  the first two in that exact loop, so the port point is one added call.
- Nine states: 1 `WAIT_FRAPPE_ANIM`, 2 `WAIT_FRAPPE_FRAME`, 3 `FRAPPE_OK`,
  4 `WAIT_TIR_ANIM`, 5 `DO_TIR`, 6 `WAIT_ANIM_THROW`, 7 `THROW`, 8 `HIT_OBJ`,
  9 in-flight throw.

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
| melee | 1→2→3 | 55 | `hotPoint`, `CheckObjectCol` | `check_object_col` ✅; hot point new |
| shoot | 4→5 | 60 | `checkLineProjectionWithActors`, `InitSpecialObjet` | neither ported |
| throw setup | 6→7 | 90 | `GiveZVObjet`, `AsmCheckListCol`, `PutAtObjet`, `DeleteInventoryObjet` | `_body_zv`, `check_hard_col`, `put_at_objet`, `remove_from_inventory` — all ✅ |
| hit-object | 8 | **0** | — the case is literally `break;` | already equivalent ✅ |
| in-flight | 9 | **187** | own collision + bounce | new, largest single piece |

- **Case 8 needs no work.** `LM_HIT_OBJECT` sets state 8 and the runner does
  nothing with it; the port's `op_hit_object` already matches.
- **`InitSpecialObjet` is not on the critical path.** It spawns muzzle flash and
  impact *visuals*. The combat contract is publishing HIT/HIT_BY/hitForce, which
  is unaffected. Shoot ships with it left stubbed; only
  `checkLineProjectionWithActors` is logically required.

### The hot point crosses the repo's hardest boundary

`getHotPoint` (`main.cpp:2976`) reads the **skinned vertex buffer** —
`pointBuffer[group.m_baseVertices]`, gated on `body.flags & 2` — and FITD calls
it at `main.cpp:3071`, inside `AllRedraw`, the *render* path. This port keeps
simulation (`playworld`, pygame-free, headless) separate from rendering.
`hot_point` is declared at `game.py:101` and **never written**.

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
- **The venue works.** Reproducing `op_stage`'s actor mutations plus what
  `play_tick` step 9 does in the same tick transitions cleanly to floor 5 room 4:
  48 actors spawn, obj222 appears as an actor with `track_mode 2` /
  `object_type 0x0141`, and it pursues the hero for 1200 ticks without error.
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
   throw setup → shoot → in-flight. Dependency and value order; the 187-line
   in-flight physics is last so it can slip without blocking enemies attacking.
4. **`InitSpecialObjet` stays stubbed.** Visual only.
5. **Death restarts the floor.** Menus are M4; restart is the only option that
   keeps the game playable end-to-end and lets a tester die repeatedly.
6. **`GameOver` is a modal effect, not a new mode mechanism.**

## Architecture

### Phase boundary

The two halves are deliberately separable and should be reviewed as such:

- **Phase A (②)** — `evalVar` fix, `--floor N` relocation, venue fixture,
  `prove-combat` skeleton. Touches `eval_var.py`, `__main__.py`, tests, Makefile.
- **Phase B (①)** — `anim_action.py`, `skel.hot_point`, real `LM_HIT`/`LM_FIRE`/
  `LM_THROW`, `GameOver`. Touches `anim_action.py` (new), `skel.py`,
  `life_ops.py`, `effects.py`, `playworld.py`, `__main__.py`.

Phase A lands first and completely, because Phase B's integration tests depend on
its fixture.

### New modules

**`PyAitD/anim_action.py`** — pygame-free, joins the layer-purity probe set.
`gere_frappe(game, actor_idx)` implements the nine-state dispatch. Consumes
`check_object_col` (melee), `check_hard_col` / `_body_zv` / `put_at_objet` /
`remove_from_inventory` (throw), and a new `checkLineProjectionWithActors` port
(shoot).

**`skel.hot_point(body, group_states, hot_point_id) -> (x, y, z)`** — the hot
point is computed **in simulation, not read back from the renderer**. `skel.py`
is already pure math (`cos_table` + `world`, no pygame), so the simulation can
skin. `getHotPoint` needs exactly one vertex — `groups[hot_point_id].base_vertices`
after the group transforms — so this computes that single vertex rather than
skinning the whole body.

The alternative, caching skinned points from the render pass and feeding them
back, is **rejected**: it would make combat depend on rendering and break
`play_tick`'s headless guarantee, which `tests/test_playworld.py` enforces with a
subprocess probe.

### The one added call

`playworld._anim_pass` gains a third call mirroring `mainLoop.cpp:143`:

```python
if flags & AF_TRIGGER:
    gere_dec(game, index)
if actor.anim_action_type:
    gere_frappe(game, index)
```

Same loop, same order as FITD. No new tick stage, so `play_tick`'s
`mainLoop.cpp:41-281` ordering docstring stays true.

### Game over

`game.mode` is derived purely from `active_modal` via `MODAL_MODE`
(`game.py`, `effects.py:66-71`). So `GAME_OVER` needs no new machinery: a
`GameOver` effect in `effects.py`, one `MODAL_MODE` entry, and the rest follows —
`play_tick` already suspends when `mode is not PLAY`, and `__main__` already
routes and renders by mode. `flag_game_over` stops being write-only by becoming
what opens that modal.

This matches FITD, where `FlagGameOver` is only a loop-exit flag
(`mainLoop.cpp:185, 233`) and presentation lives outside `PlayWorld`.

FITD's `LM_GAME_OVER` fades music and spins 120 chrono units before setting the
flag (`life.cpp:2438-2450`). The fade stays skipped (audio is M4); the delay is
real pacing and reuses `ShowPicture`'s existing `delay_units` /
`_auto_dismiss_picture` pattern rather than inventing a timer.

**Dismissing the `GameOver` modal restarts the current floor** — re-running
`init_game` plus the floor's spawn, not returning to a title screen that does not
exist yet. Menus are M4. This is a deliberate placeholder to revisit then, and it
is the only outcome that lets a tester die repeatedly while checking combat.

### Multi-floor (Phase A)

- `eval_var.py` out-of-floor branch compares `0x1E` (room) and `0x25` (stage).
  Codes FITD itself asserts on keep raising, and the message says so, so the
  error does not read like a port gap.
- `--floor N` applies `op_stage`'s relocation to the hero so `make run floor=5`
  is usable by hand — necessary because no automated test can judge combat feel.
- The venue fixture reproduces `op_stage`'s mutations plus `play_tick` step 9's
  floor swap, placing the hero in front of obj222 on floor 5 room 4. It is a
  single shared implementation used by both the Phase B integration tests and
  `make prove-combat`; it must not be duplicated between them.

## Invariants

- `anim_action.py` imports no pygame, ModernGL, `PyAitD.ui`, or `PyAitD.render`.
- `play_tick` stays headless and its FITD `mainLoop` ordering unchanged.
- The runner never writes `life`; damage stays script-side.
- FITD-ported quirks are preserved, never "fixed" — including the two below.
- Golden values are pinned from real game data, never re-derived by guessing.

## Error handling

- `evalVar` on an out-of-floor object with a code FITD does not support keeps
  raising, with a message naming the raw tag and stating FITD asserts here too.
- `gere_frappe` on an actor whose body cannot supply a hot point
  (`body.flags & 2` unset) yields `(0, 0, 0)`, exactly as `getHotPoint` does —
  not an error.
- An `anim_action_type` outside 1..9 raises with the actor and value, matching
  FITD's `printf` + `assert(0)` default arm (`animAction.cpp:452`).

## Testing

- **Layer purity**: `anim_action.py` joins the subprocess probe set. A static
  import walk cannot substitute — deferred imports make pygame look reachable.
- **Golden**: `hot_point` against a real body with `flags & 2` — assert it equals
  the skinned base vertex of the named group. Measured before the plan is
  written.
- **The preserved fall-through is pinned by a test.** `FRAPPE_OK` sets
  `animActionType = 0` when the anim no longer matches and then falls through and
  hit-tests anyway (no `return`, `animAction.cpp:48-51`). That reads like a bug;
  a test is the only thing that stops the next reader "fixing" it.
- **Tick-order pinning**: assert `gere_frappe` runs *after* `gere_dec` within the
  same per-actor iteration, not merely that it runs. The mouse branch's Criticals
  were all seam defects of exactly this kind.
- **Real-data integration** on Phase A's fixture: transition → enemy pursues →
  attack fires → `hero.hit_by == enemy`. This is the test that would have caught
  "nothing ever attacks", and it exists only because ② proved the venue.
- **`make prove-combat`**, alongside `prove` / `prove-m3b` / `prove-mouse`:
  headless, runs the **same venue fixture the integration tests use** (one
  implementation, two callers), and reports whether the enemy closed and whether a
  hit was published. It lands in Phase A, before any arm exists, so it reports
  rather than fails on arms not yet implemented — the way `prove-mouse` reports
  empty meshes. Once all arms land it should report hits on every one; a silent
  "no hit published" is then a regression, not a pending item.
- **Every new test must be verified to fail with its fix reverted**, and the
  report must say so. During the mouse fix wave an implementer did this unprompted
  and it is the only reason we know that test was not decorative. This codebase
  has already produced two tests that passed while testing nothing.

**Not coverable by tests**: whether combat *feels* right — pacing, whether an
enemy that reaches you is threatening — needs `make run floor=5` and a human,
which is why the harness fix is in scope.

## Assumptions

- A script-driven transition arising naturally in play behaves identically to the
  reproduced one. The fixture reproduces `op_stage`'s post-conditions faithfully,
  but no natural playthrough was observed.
- Enemy scripts already contain working damage logic behind `evalVar` `0x04`, so
  publishing hits is sufficient to produce damage. Consistent with the runner
  never touching `life`, but unverified until a hit actually lands.
- `body.flags & 2` gates hot-point availability on the bodies combat actually
  uses. Unverified across all combat bodies.

## Risks

- **In-flight throw (state 9) is 187 lines** of collision-and-bounce physics,
  larger than melee and shoot combined, and delivers the least. It is sequenced
  last so it can slip without blocking the reported problem. If it proves a
  swamp, it should be split out rather than allowed to stall the spec.
- **Floors 2 and 6 are of unknown status.** An earlier probe appeared to show them
  crashing; that was an artifact of the probe placing an invalid room index before
  the floor swap, and the claim was retracted. They are simply untested.
- **Combined scope.** ①+② is roughly the size of the mouse-input branch, whose
  whole-branch review found three Criticals invisible to per-task review. The
  phase boundary above is the mitigation; if the branch grows past it, the halves
  should be split into separate branches rather than reviewed as one diff.
- **`checkLineProjectionWithActors` is unported and unexamined.** Its size and
  dependencies are unknown; shoot's cost estimate is therefore softer than
  melee's or throw's.
