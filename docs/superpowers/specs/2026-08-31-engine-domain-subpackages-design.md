# Engine domain subpackages — design

Date: 2026-08-31. Status: approved design, pure reorganization + seam closing
(no behavior change).

## Goal

Restructure the flat `PyAitD/engine/` (29 modules, 6,631 lines) into five
domain subpackages — `data`, `space`, `actor`, `script`, `nav` — split the
three oversized modules (`game.py` 649, `interaction.py` 617, `playworld.py`
525) into same-named subpackages, and close the five known AITD1-only seam
clusters (AGENTS.md) by moving them into `GameProfile`. The layout and the
profile fields are shaped after FITD's own multi-game model so a future
`games/aitd2` or `games/aitd3` is additive: new profile instance, no engine
edits. Running a second game is **not** in scope.

This is the follow-up to `2026-08-26-engine-package-reorganization-design.md`,
which split flat `PyAitD/` into `engine/render/games/app` and explicitly
deferred the second game.

## FITD's multi-game model (the shape the seams take)

FITD supports AITD1/JACK/AITD2/AITD3/TIMEGATE with one engine and per-game
data, not per-game engines:

- Games are distinguished by an ordinal `gameTypeEnum { AITD1, JACK, AITD2,
  AITD3, TIMEGATE }` (`vars.h:5-12`); most branches are generation predicates
  (`g_gameId >= JACK`), not identity tests.
- Per-game knowledge lives in per-game files (`AITD1.cpp`, `AITD2.cpp`,
  `AITD3.cpp`): the LIFE macro table (`AITD1.cpp:30-119`, 80 entries;
  `AITD2.cpp:48-171`, ~119, shared by JACK/AITD3/TIMEGATE), ITD_RESS entry
  maps, known-CVar tables, boot flows.
- Record-layout deltas are generation-conditional trailing fields:
  viewed-room record 0x0C vs 0x10 (`floor.cpp:367-375`), `tObject` gains
  `hardMat` (`vars.h:179-181`), `tWorldObject` gains `mark`
  (parsed conditionally, `main.cpp:1117-1121`).
- Overlay masks are computed for AITD1 (`createAITD1Mask`) but loaded from
  `MASK%02d` PAKs for JACK+ (`main.cpp:2178-2190`).
- Screen size is 320x200 for all five games (`vars.h:272`); floor/camera
  archives are `ETAGE%02d`/`CAMERA%02d` through AITD3 (`floor.cpp:26-28`).

## Target layout

```
PyAitD/engine/
  __init__.py                     # unchanged (SPDX + docstring)
  data/    pak.py explode.py formats.py floor.py assets.py text.py
           mask.py mask_geometry.py
  space/   cos_table.py world.py realvalue.py
  actor/   actors.py anim.py anim_action.py tracks.py skel.py
  script/  game/ interaction/ life.py eval_var.py effects.py playworld/ save.py
  nav/     navmesh.py picking.py navigate.py
```

Placement follows the existing import graph (every cross-domain edge below
exists today):

- `data/` — "archive bytes -> parsed records". **Fully closed**: all import
  edges from these 8 modules stay inside `data/`. Two deliberate deviations
  from the pre-reorganization doc grouping: `text.py` is a pure
  bytes->records parser like `formats.py`, and `mask.py`/`mask_geometry.py`
  are rasterized at floor load from floor data — ownership is `data`;
  `render/` merely consumes them (4 and 6 importing files, rewrites only).
- `space/` — the shared math sink (fixed-point trig, camera transforms,
  interpolation/chronos). Imports `data` only (`world -> formats`).
- `actor/` — tObject state, keyframe playback, combat actions, movement
  modes, skinning/projection. Imports `space` + `data`.
- `script/` — Game state, LIFE VM, inventory/world interaction, effects,
  the 50 Hz tick, persistence. Imports everything.
- `nav/` — pointer navigation. Imports `data`/`space`/`actor` plus one edge
  into `script` (`navigate -> effects`).

Pre-existing cycles are kept honest, not hidden: `game <-> interaction`,
`game <-> anim/tracks`, `actors <-> interaction`, `life <-> eval_var` are
load-bearing lazy imports today. The moves neither fix nor worsen them; the
`game` split weakens them (`game/state.py` stops importing
`interaction`/`tracks`). No acyclicity is claimed beyond the two leaf pins
below.

## Splits (same-named subpackages, dotted paths preserved)

Each `__init__.py` re-exports every public name (absolute imports only —
the repo-wide relative-import ban applies), so all 46 external importers of
`game`, 18 of `interaction`, 15 of `playworld` keep working unchanged.
`save.py` (542) stays whole: one responsibility, and the rule is split by
responsibility, not size.

`engine/script/game/`:
- `state.py` — `RealValue`, `Actor`, `FloorStart`, `Game`, `AF_*` flags,
  `NUM_MAX_OBJECT`. Imports neither `interaction` nor `tracks`.
- `zv.py` — `_zv_default`, `_zv_max`, `_zv_cube`, `_point_rotate`, `_zv_rot`,
  `_hard_zv`. Re-exported: `games/aitd1/life_ops.py` imports three of them
  cross-module today.
- `objects.py` — `add_actor`, `_delete_objet`, `delete_object`,
  `put_at_objet`, `activate_world_object`, `spawn_stage_actors`.
- `boot.py` — `change_salle`, `relocate_actor`, `enter_floor_start`,
  `start_game`, `game_step_tick`, `init_game`.

`engine/script/interaction/`:
- `track_mode.py` — `player_track_mode`, `sync_player_track_mode`,
  `PLAYER_TRACK_MODES` (until S3).
- `life_cont.py` — `run_life`, `resume_life`, `execute_found_life`,
  temp-actor cleanup; the message/immediate-effect pump.
- `inventory.py` — read views, mutations, `apply_*_result` modal-result
  application, `INVENTORY_SIZE`, `MAX_VISIBLE_ACTIONS`.
- `combat.py` — target predicates, `combat_action_for`/`can_strike`,
  `attack_in_hand`, `hold_action_approach`, combat/push constants (until S3).
- `contacts.py` — `resolve_actor_contacts`, `point_in_zone`, `gere_dec`.
- `nav_intent.py` — click-intent record/drop, `dispatch_nav_arrival`.

`engine/script/playworld/`:
- `input.py` — `apply_play_input`, mouse-input/mouse-attack snapshot.
- `held_push.py` — held-push follower geometry (retarget, push point,
  detour, corridor helpers).
- `passes.py` — per-actor anim/LIFE passes, cover-zone camera switch,
  active-list regen, game-over handoff.
- `tick.py` — `play_tick` + `TICK_MS`/`NATIVE_ACTION`/
  `MOUSE_ATTACK_TICK_BUDGET`.

## GameProfile: 13 new fields

Each replaces a literal the engine reads today; each gets AITD1 values in
`games/aitd1/profile.py` and value-pins in `tests/test_game_profile.py`.
Engine read-sites follow the existing `palette_entry` pattern (profile
threaded via `Game`/`Assets`/`Floor`), with matching absence-pins
(`not hasattr(life, "NUM_OPCODES")`, the `not hasattr(floor,
"PALETTE_ENTRY")` precedent).

| Field | AITD1 value | Closes |
|---|---|---|
| `generation: int` | `0` | FITD `gameTypeEnum` ordinal; future `>= JACK`-style predicates take this shape |
| `floor_archive_name` / `camera_archive_name` | `ETAGE%02d` / `CAMERA%02d` | `floor.py:23-24` literals |
| `mask_factory` | `create_aitd1_mask` | overlay strategy (`floor.py:47`); pre-positions MASK-PAK loading |
| `cadre_bank: tuple[int, int]` | `(4, 9)` | `assets.py:82,86` ITD_RESS entry + sprite count |
| `core_slots: Mapping[str, int]` | 19 slots: IF comparators 4-9, GOTO 10, RETURN 11, END 12, VAR 19, INC 20, DEC 21, ADD 22, SUB 23, LIFE_MODE 24, SWITCH 25, CASE 26, START_CHRONO 28, MULTI_CASE 29 | `life.py` `core_table()` literals (`life.py:237-262`); mapping keys are the semantic op names `core_table()` already uses |
| `combat_action_text_ids: frozenset` | `{32}` | `interaction.py` `COMBAT_ACTIONS` |
| `player_stand_anim` / `player_push_anim` | `4` / `5` | `PLAYER_STAND_ANIM` / `PLAYER_PUSH_ANIM` |
| `player_track_modes: tuple` | `(1, 4)` | `PLAYER_TRACK_MODES` |
| `viewed_room_record_size` / `world_object_has_mark` / `actor_has_hard_mat` | `0x0C` / `False` / `False` | `formats.py` record layouts (FITD `floor.cpp:367-375`, `main.cpp:1117-1121`, `vars.h:179-181`); exact parse sites enumerated by the plan |

Three deliberate non-fields — seams closed by evidence instead:

- `NUM_OPCODES` is deleted, not moved: `len(profile.opcode_table)` is
  already 87 and test-pinned. Dead slots `{27, 57, 61, 69}` already ride
  inside `opcode_table` as `_op_dead` entries, so no `dead_opcodes` field.
- Screen size is not per-game (FITD `vars.h:272`, all five games 320x200):
  `assets.py` gains named `SCREEN_PIXELS = 64000` with the citation.
- No changes to `reduced_dispatch`/`reduced_allowed`/`opcode_table` — those
  seams are already profile-driven.

## Package rules

Added to `tests/test_layering.py` (subpackages already covered by `rglob`):

- `PyAitD.engine.data.*` imports nothing outside stdlib/NumPy and
  `PyAitD.engine.data` itself (beyond the existing engine-wide bans).
- `PyAitD.engine.space.*` additionally may import `PyAitD.engine.data` only.
- No new rules for `actor`/`script`/`nav` — the pre-existing cycles above
  would make stricter pins dishonest.

`tests/purity.py`'s `PRESENTATION_FREE` rows move to the new dotted paths
(`engine.nav.navigate`, `engine.nav.navmesh`, `engine.nav.picking`,
`engine.script.playworld`, `engine.actor.anim_action`). All imports stay
absolute; the S1 rewrite is mechanical: `PyAitD.engine.X` ->
`PyAitD.engine.<domain>.X` across ~285 module-import edges in `PyAitD/`,
`tests/`, `tools/` (per-module importing-file counts tallied during
exploration; unique files fewer).

## Invariants

- `make test` (headless, the gate) passes after every stage; S1 and S3 also
  run `make test-journey` (real data present).
- Golden values, do-not-fix quirks, `ponytail:` comments, and FITD
  `file:line` citations move verbatim. A golden diff in S3 means the wiring
  is wrong — fix the wiring, never re-derive goldens.
- Legacy `prove-*` gate pins are unaffected: test file stems do not move and
  `tests/test_test_groups.py` reads markers by AST, not imports.
- `# SPDX-License-Identifier: GPL-2.0-only` stays the first line of every
  Python file, including every new `__init__.py`.
- No renames of functions, classes, or test files beyond what the moves
  require; no compatibility shims (the old flat `PyAitD.engine.X` paths
  disappear).
- Dependency set unchanged: pygame-ce, ModernGL, NumPy, pytest. The
  relaxed-for-this-session rule was exercised as design exploration;
  nothing is adopted. A `pygame_gui`-based asset browser in `tools/` for
  future AITD2/3 bring-up is the one candidate with merit — separable,
  not part of this milestone.
- `engine/` stays pygame/GL-free; the purity gate is architectural
  (headless simulation is the test strategy), not dependency policy.

## Sequencing

Each stage is its own commit series, ends green, and is independently
revertable; risk increases only as the mechanical work settles.

1. **S1 — domain moves (content-free).** `git mv` into the five domains;
   mechanical import rewrite; new domain `__init__.py` files (SPDX);
   purity-table dotted paths; the two new layering pins. Verification:
   diffs contain only renames, import-line edits, new `__init__.py` files,
   and the layering/purity updates; then `make test` +
   `make test-journey`.
2. **S2 — oversized splits (behavior-free).** `game`, `interaction`,
   `playworld` become the subpackages above; `__init__.py` re-exports keep
   every importer unchanged. Verification: `make test`.
3. **S3 — seam closing (golden-pinned).** The 13 profile fields land with
   AITD1 values; read-sites rewired in `floor.py`, `assets.py`, `life.py`,
   `formats.py`, and the `interaction` subpackage; `games/base.py`
   seam-status docstring rewritten; value-pins + absence-pins in
   `tests/test_game_profile.py`. Verification: `make test` +
   `make test-journey`; goldens must pass byte-identical.
4. **S4 — docs.** `CONTEXT.md` architecture map rewritten for the domain
   layout; `AGENTS.md` package table, "Where new code goes", and the
   known-seams list rewritten (the list flips from "hard-coded" to "closed;
   pattern: `palette_entry`"); docs citing old `engine/<module>.py` paths
   get translation addenda where historical (the M4a2 addendum precedent)
   — files enumerated by the plan via grep over `docs/`.

## Out of scope

Running AITD2/AITD3 (their opcode-table values, per-camera palette model,
MASK-PAK overlay loading, hybrid bodies, per-game inventory/read-book
screens, boot flows) — the seams this milestone closes are what makes that
work additive later. Also out: audio (M4b), sequences, any new dependency,
any behavior change, any rename beyond the moves.
