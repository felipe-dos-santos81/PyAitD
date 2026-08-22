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
make test                    # pytest suite (179 passed, 1 skipped)
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
- **Masks**: a viewed room's masks occlude actors in *other* viewed rooms only.
- **FITD quirks preserved**: GiveDistance2D is Manhattan with s16-cast saturation;
  `_last_time_forward = 0` cold-start run quirk; LM_READ skips an extra s16;
  LM_WAIT_GAME_OVER second wait has the non-negated Click bug; `walkStep` outputs
  crossed (xOut→animMoveZ).
- Known simplifications (ponytail comments in code): per-actor mask erase order,
  do_real_zv box zv instead of per-vertex bounds, ANIM_RESET skip, CheckObjectCol
  push/pickup (M3b), fall management.

## Current open thread (rendering QA with user)

M3a boots and plays; user-confirmed: player visible, head occlusion fixed by the
depth-sort correction. Open complaint: *"horse on right is near the camera"*.
Forensics so far:

- The horse candidate is **wobj 21, body 24** at OBJETS position **(0, 0, 10000)**,
  room 0 — projected by camera 0 to frame ~(186, 50), small (≈15×14 px) = far.
  Headless 3000-tick runs: position stable; scripts don't move it without input.
- Screenshot comparison (low-res averaged) matches the boot-state render closely;
  no evidence of misprojection yet. **Awaiting user to circle the object they mean.**
- Cameras 3/4 project boot-position actors off-screen — expected (player not in
  their view there); zone-gated switching verified for cameras 0-2.

M3b/M3c stubs in `life_ops.py` consume exact FITD arg counts and log under trace
(audio, inventory, combat, text) — scripts stay desync-free until real semantics land.

## Testing conventions

Golden values are pinned from real game data (do not re-derive): 292 world objects,
207 vars, 45 CVars, 563 scripts, 45 tracks, camera/body/anim pins per plan doc.
Tests skip when game data absent (`data_dir` fixture). New work follows the
brainstorm → spec → plan → subagent-driven TDD workflow recorded in `docs/superpowers/`.
