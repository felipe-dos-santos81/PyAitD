# CONTEXT — maitd

Python engine rewrite of **Alone in the Dark 1 (DOS, 1992)** — a faithful,
test-driven port of the [FITD](https://github.com/fn2006/FITD) C++
decompilation (GPLv2), targeting Apple Silicon with pygame-ce + ModernGL.

- Repo: `/Users/felipe.dos.santos/code/mine/m-aitd` (branch `main`)
- FITD reference: `/Users/felipe.dos.santos/code/theirs/FITD/FitdLib/` (authoritative for all game logic)
- Game data: `Alone in the Dark 1.app/Contents/Resources/game/INDARK`
- Python 3.12, `.venv/`; deps: pygame-ce, moderngl, numpy, pytest (no more)

## Commands

```bash
make run                     # play (windowed); make run trace=/tmp/t.log writes per-opcode LIFE trace
make test                    # pytest suite (187 passed, 1 skipped)
make prove                   # M3a proof: parse-all 563 scripts/45 tracks/tables + headless 60-tick boot
make floor=N run             # start on another floor
```

## Where we are

| Milestone | Scope | Status |
|---|---|---|
| M1 | Data layer + room rendering: PAK, ETAGE floors, camera images, masks, ITD parsing | done |
| M2 | Actors: body/anim parsing, skinning (AnimNuage), tank movement + collision, zone-driven camera switching, mask compositing over backgrounds | done |
| M3a | LIFE script VM core + world: the game boots from its **real scripts** — intro scene, actors spawn, scripts drive everything; script-driven player input | done (merged) |
| M3b | Interaction: inventory (TAKE/FOUND/IN_HAND), action button, text MESSAGE rendering | **next** |
| M3c | Combat: HIT/FIRE/THROW animActions, game over → completable | later |
| M4 | Menus, audio, save/load | later |

Design docs live in `docs/superpowers/specs/` and `docs/superpowers/plans/`
(one spec + one task-level TDD plan per milestone). `docs/life-vm-opcodes.md`
is the opcode research doc (note: its opcode numbers were later corrected
against `AITD1.cpp` — the plan + code are the source of truth).

## Architecture (maitd/)

| Module | Role |
|---|---|
| `pak.py`, `floor.py`, `explode.py` | PAK/HQR archives, ETAGE floor data, EXPLODE decompression |
| `formats.py` | Pure parsers: bodies, anims, cameras, cover zones, WorldObject/VARS/DEFINES/PRIORITY records |
| `assets.py` | Parse-once registries over the LRU: bodies, anims, LISTLIFE scripts, LISTTRAK tracks |
| `game.py` | `Game` state: CVars (45, DEFINES big-endian), script vars (207), 292 world objects, 128 actor slots, `init_game`/`spawn_stage_actors` (FITD LoadWorld + GenereActiveList) |
| `life.py` | VM core: fetch loop, 87-slot `LIFETABLE`, 0x8000 actor-switch, control flow, `Trace` |
| `life_ops.py`, `life_reduced.py` | Full-dispatch opcode handlers + not-in-floor reduced set |
| `eval_var.py` | evalVar tagged-s16 argument system (all AITD1 property codes) |
| `tracks.py` | processTrack: manual (player) / follow / scripted modes, TL_* macros |
| `realvalue.py` | RealValue interpolation (rotation/speed ramps), chronos, GiveDistance2D |
| `actors.py` | Actor fields (tObject port), GereAnim movement/collision port, `sort_actor_indices` (FITD sortActorList) |
| `anim.py` | AnimPlayer: SetAnimObjet/SetInterAnimObjet keyframe interpolation |
| `world.py`, `cos_table.py` | Fixed-point rotations, camera transform/projection (M2-verified goldens) |
| `skel.py`, `mask.py`, `render.py` | Skinning/projection, mask rasterization, ModernGL pipeline (actor FBO → composite → window quad) |
| `__main__.py` | PlayWorld loop (mainLoop.cpp:41-281 order): input snapshot → anim pass → life pass → camera switch → draw |

## Fidelity notes (hard-won)

- **Opcode table**: 87 slots (0..86), index == enum value; dead = {27 LM_CAMERA,
  57 LM_STOP_BETA, 61 LM_DO_NORMAL_ZV, 69 LM_SPEED} → raise. Var ops LM_VAR/INC/
  DEC/ADD/SUB = 19-23 write `game.vars`. No call stack; LM_LIFE assigns, next tick runs.
- **Scale mix is FITD-faithful**: actor coords are room-scale; camera translate is
  `(cam - room.world) * 10`. Projection matches FITD AnimNuage.
- **Renderer row orientation**: GL FBO rows are bottom-up; backgrounds are top-down.
  `present_scene` flips the actor layer on read (`layer[::-1]`) and mask-erase coords.
- **Painter's algorithm**: actors depth-sorted farthest-first (FITD comparator
  returns -1 when distance1 > distance2 — do not "fix" the direction).
- **Masks**: FITD selects masks per actor: the mask's viewed room must match the
  actor room, and the actor ZV / 10 must fit one of that mask's trigger rectangles.
- **FITD quirks preserved**: GiveDistance2D is Manhattan with s16-cast saturation;
  `_last_time_forward = 0` cold-start run quirk; LM_READ skips an extra s16;
  LM_WAIT_GAME_OVER second wait has the non-negated Click bug; `walkStep` outputs
  crossed (xOut→animMoveZ).
- Known simplifications (ponytail comments in code): do_real_zv box zv instead
  of per-vertex bounds, ANIM_RESET skip, CheckObjectCol push/pickup (M3b), fall
  management.

## Current rendering QA findings

- FITD `AnimNuage` always writes actor angles to skeleton **group 0**. The old
  port incorrectly used `group_order[0]` (player body 12: group 5; rocking-horse
  body 4: group 1), making visible facing disagree with movement. Static bodies
  now also take the whole-model rotation used by FITD `RotateNuage`.
- The prominent rocking horse at the right is **wobj 6, body 4** at OBJETS
  position **(5740, 0, 569)**, beta 768. The previously investigated wobj 21 /
  body 24 is a different, small distant object at (0, 0, 10000).
- Camera 0 mask 4 contains the right support beam. Its second trigger rectangle
  contains the horse ZV, so FITD redraws that background mask after the horse;
  retaining and applying those rectangles places the horse behind the beam.
- FITD renders each body's primitives with a depth buffer (`WRITE_Z` plus
  `DEPTH_TEST_LEQUAL`). Without per-actor depth testing, body 2's later back
  polygons covered its nearer door polygons, making the left wardrobe look
  side-on. The actor FBO now carries and clears a depth attachment per actor.
- Fixed-step simulation and rendering are decoupled in the pygame loop. GPU
  rendering can exceed the 20 ms logic interval, so accumulated 50 Hz ticks
  run without rendering and the resulting state is drawn once per outer frame;
  this prevents repeated readbacks from making held controls stall.
- Opening-room camera switching matches FITD's cover-zone algorithm. A full
  play-tick trace turns right, walks forward, and switches local camera 0 -> 3
  at player position (505, -1706); the wrong rendered facing had made navigation
  toward that trigger appear inconsistent.

M3b/M3c stubs in `life_ops.py` consume exact FITD arg counts and log under trace
(audio, inventory, combat, text) — scripts stay desync-free until real semantics land.

## M3b interaction boundary

- `effects.py`: typed immediate/modal effects and resumable LIFE frames.
- `interaction.py`: found-LIFE, inventory/world transitions, contacts, and GereDec.
- `ui.py`: command buffering, modal reducers, mouse targets, and 320x200 presenters.
- `__main__.py`: one event pump, PLAY-only fixed ticks, mode routing, one present.
- Focused proof: `make prove-m3b`.
- Full regression: `.venv/bin/pytest -q && make prove`.
- Manual evidence: `docs/m3b-interaction-proof.md`.

## Testing conventions

Golden values are pinned from real game data (do not re-derive): 292 world objects,
207 vars, 45 CVars, 563 scripts, 45 tracks, camera/body/anim pins per plan doc.
Tests skip when game data absent (`data_dir` fixture). New work follows the
brainstorm → spec → plan → subagent-driven TDD workflow recorded in `docs/superpowers/`.
