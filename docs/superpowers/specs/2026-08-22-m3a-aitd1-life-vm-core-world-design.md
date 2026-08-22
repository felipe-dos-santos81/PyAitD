# Alone in the Dark 1 — M3a: LIFE VM Core + World Design

Date: 2026-08-22
Status: Approved (design)
Reference: FITD (`/Users/felipe.dos.santos/code/theirs/FITD`, GPLv2) — `life.cpp`,
`AITD1.cpp`, `evalVar.cpp`, `track.cpp`, `mainLoop.cpp`, `main.cpp`
Builds on: M1 (data layer), M2 (actors, camera switching, masks)

## Goal

Boot the real game logic: a faithful port of FITD's LIFE script VM plus the
world model (objects, variables, tracks), driving the game from its original
scripts — intro scene runs, objects spawn, doors open, floor changes work.
The player is controlled through their own script (script-driven input).

## M3 decomposition (agreed with user)

- **M3a (this spec)** — VM core + world: interpreter, evalVar, CVars/VARS,
  OBJETS world objects, tracks, script-driven player input. Proof: game boots
  from data into the attic scene with correct objects and working scripts.
- **M3b** — interaction: inventory (TAKE/FOUND/IN_HAND), action button,
  text messages (MESSAGE + font rendering).
- **M3c** — combat (HIT/FIRE/THROW, animAction), game over, full playability
  pass → completable.

## Non-goals (M3a)

- Menus (M4; M3a bypasses the menu and auto-starts the game scene)
- Audio playback (M4; SAMPLE/MUSIC opcodes execute as no-op stubs that
  consume their arguments correctly)
- Text/message rendering (M3b), inventory semantics (M3b), combat (M3c)
- Save/load (M4)

## Context discovered (FITD reference)

- Scripts: `LISTLIFE.PAK`, 563 entries, s16 opcode streams. `processLife`
  (life.cpp:453) loops: fetch s16 opcode; if bit 0x8000 set, next s16 = world
  object index — switch the actor (its actor-table slot) or, when the object
  has no live actor, run the opcode against the world object table; runs
  until LM_RETURN/LM_END; LM_LIFE enters another script (FITD guards
  re-entry: a script already on the current call stack is skipped).
- Opcode mapping: `AITD1LifeMacroTable` (AITD1.cpp:30) maps game opcode
  values 0..76 to 77 macros (subset of the ~114-macro enum in life.h).
- Args use `evalVar` encodings (s16): plain literal vs variable reference
  vs CVar index vs stage/room references — ported from evalVar.cpp.
- World objects: `OBJETS.ITD` (15186 bytes) — fixed-size world-object
  records (body, anim, life, track, stage, room, flags, zv, world obj index);
  game vars: `VARS.ITD` (414 bytes) CVars init; `DEFINES.ITD` (90 bytes);
  `PRIORITY.ITD` (101 bytes) draw-priority table.
- Tracks: `LISTTRAK.PAK` — camera/actor motion paths (track.cpp: 764 lines:
  step/pos evaluation, track flags TL_*).
- Main loop (mainLoop.cpp PlayWorld) order per tick: process events →
  per actor: GereAnim → per actor: processLife → camera switch (GereSwitchCamera)
  → draw. Player input: JoyD bits polled each tick; the player's own script
  consumes them (animMove/speed/turn opcodes).
- M2 already provides: actors, anim player, movement/collision primitives
  (rotate_step, gere_collision, check_hard_col), camera switching, masks,
  assets LRU (reusable for LISTLIFE/LISTTRAK entries).

## Decisions (agreed with user)

- Three sub-milestones (a/b/c); this spec is M3a.
- Script-driven player input (FITD architecture): M2's direct-input movement
  becomes primitives invoked by the player script.
- Opcode trace logging included: `--trace FILE` writes per-tick lines
  (actor, opcode, args, vars touched) — essential for diagnosing stalls.
- Stub handlers (audio/inventory/combat/text) consume the same argument
  counts as their FITD implementations and log when tracing.

## Architecture

New/changed modules (extends the M2 pipeline):

- `maitd/game.py` — `Game` class: CVars (from VARS.ITD), world objects
  (OBJETS.ITD), actor table (ListObjets-equivalent), inventory/in-hand
  placeholder fields, chronos, current stage/room, floor orchestration
  (LoadEtage-equivalent), input snapshot (JoyD/action per tick),
  `init_game(data_dir)` (menu bypassed).
- `maitd/life.py` — VM: `process_life(game, actor_idx, life_num)`;
  `eval_var(game, s16) -> int` port; `OPCODE_HANDLERS` dict keyed by AITD1
  macro enum (77 handlers); stub handlers consume args per FITD arg counts;
  `Trace` helper (opcode lines to file when enabled).
- `maitd/tracks.py` — LISTTRAK parse (via assets LRU) + track runner:
  position/step evaluation for DO_MOVE/MOVE per FITD track.cpp (track flags
  TL_*: loop, wait, camera track).
- `maitd/formats.py` (+ parse_objets, parse_vars, parse_defines,
  parse_priority) — pure parsers, golden-tested.
- `maitd/actors.py` — M2 movement exposed as primitives the VM calls
  (walk_step, set speed via RealValue evaluation port from anim.cpp
  evaluateReal).
- `maitd/__main__.py` — play loop in FITD order (anim tick → life tick →
  camera switch → draw), `--trace FILE`, script-driven input; M2 debug
  direct-input removed.

Data flow per 50Hz tick: poll input snapshot → per actor: anim tick
(AnimPlayer.advance) → per actor: process_life (scripts drive moves,
spawns, camera, stage) → GereSwitchCamera → draw (M2 pipeline).

## Invariants

- VM never touches rendering or disk; effects via Game/actor/world APIs.
- Script fetch/parse cached through the assets LRU (LISTLIFE entries).
- 77-handler dispatch table is the single source of opcode semantics;
  stub handlers are marked with their owning sub-milestone.
- All script arithmetic matches FITD exactly (s16 semantics, truncating
  division, evalVar encodings).

## Error handling

- Unknown opcode value (not in AITD1LifeMacroTable): hard error with life
  number, actor, and byte offset (FITD asserts — we raise with context).
- Script fetch miss (bad life index): ValueError with index and PAK name.
- Trace writes are best-effort (IO errors warn, never crash the game).

## Testing

- Golden parsers: OBJETS.ITD record count + first-record fields; VARS.ITD
  var count; DEFINES/PRIORITY sizes; LISTLIFE = 563 scripts (parse all,
  byte-consistent).
- VM unit tests (synthetic bytecode): goto, 6 conditionals, INC/DEC/ADD/SUB,
  C_VAR read/write, actor switch, LM_LIFE call + re-entry guard, SWITCH/CASE.
- evalVar unit tests: each encoding class round-trips to expected values.
- Tracks: synthetic track + known LISTTRAK entry positions.
- Integration proof (manual + trace): `make run` boots to the attic scene;
  trace log shows the intro script flow; objects/doors appear; stage
  changes work. Automated: prove harness parses all 563 scripts + tables.
- Existing 72 tests stay green.

## Assumptions

- ITD_RESS font/text rendering arrives in M3b (MESSAGE is a stub in M3a).
- The player object is identified by CVar `WORLD_NUM_PERSO` (FITD main.cpp:1192
  `currentWorldTarget = CVars[getCVarsIdx(WORLD_NUM_PERSO)]`), initialized from
  VARS.ITD; the AITD1 CVar name list is ported from AITD1.cpp. The player's
  script reads the input snapshot.
- Audio/inventory/combat stubs suffice for the intro to run to completion
  (verified via trace log; if the intro stalls on a stubbed opcode's
  semantics, that opcode moves up in priority).

## Risks

- Script stall loops (goto cycles with empty bodies) — mitigated by trace
  logging and FITD-parity (FITD has the same loops; stall = port bug).
- evalVar encoding edge cases — mitigated by golden tests + FITD evalVar.cpp
  as source of truth.
- Track semantics (loop/wait flags) — tracked against FITD track.cpp line
  by line during implementation.
