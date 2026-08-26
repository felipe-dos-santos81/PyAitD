# CONTEXT — PyAitD

Python engine rewrite of **Alone in the Dark 1 (DOS, 1992)** — a faithful,
test-driven port of the [FITD](https://github.com/fn2006/FITD) C++
decompilation (GPLv2), targeting Apple Silicon with pygame-ce + ModernGL.

- Repo: `/Users/felipe.dos.santos/code/mine/m-aitd` (branch `main`)
- FITD reference: `/Users/felipe.dos.santos/code/theirs/FITD/FitdLib/` (authoritative for all game logic)
- Game data: `data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK`
- Python 3.12, `.venv/`; deps: pygame-ce, moderngl, numpy, pytest (no more)

## Commands

```bash
make run                     # play (windowed) through character selection; floor=0 for the attic debug bypass, trace=/tmp/t.log writes per-opcode LIFE trace
make run-combat              # play the supported floor-5 combat venue (hero=0 Carnby, hero=1 Emily)
make run-mouse-combat        # deterministic object-38 mouse combat proof start (hero=0 Carnby, hero=1 Emily)
make test                    # pytest suite — authoritative gate
make prove                   # M3a proof: parse-all 563 scripts/45 tracks/tables + headless 60-tick play_tick boot
make prove-combat            # M3c proof: venue, real enemy damage, player arms, game over (pytest gate)
make prove-mouse-only        # mouse contract + real-data attic/combat/restart/hold-push journeys
make prove-shell             # M4a1 proof: shell, configuration, mouse contract, real-loop journeys
```

## Where we are

| Milestone | Scope | Status |
|---|---|---|
| M1 | Data layer + room rendering: PAK, ETAGE floors, camera images, masks, ITD parsing | done |
| M2 | Actors: body/anim parsing, skinning (AnimNuage), tank movement + collision, zone-driven camera switching, mask compositing over backgrounds | done |
| M3a | LIFE script VM core + world: the game boots from its **real scripts** — intro scene, actors spawn, scripts drive everything; script-driven player input | done (merged) |
| M3b | Interaction: inventory (TAKE/FOUND/IN_HAND), action button, text MESSAGE rendering | done |
| M3c | Combat: HIT/FIRE/THROW animActions, floor-5 combat venue, multi-floor `FloorStart`, the real death script → GAME_OVER → restart | done (one open ruling: the restart boundary after the death cinematic, `docs/m3c-combat-proof.md`) |
| M3d | Mouse-only point-and-click input | done |
| M3e | Mouse reachability: HUD inventory, clicked native melee, exhaustive mouse contract | done (the clicked route was corrected from force-2 throw to native melee; `docs/mouse-accessibility-hardening-proof.md`) |
| M4a1 | Shell: character select, system menu, remappable controls, sticky Action, settings persistence, settings notice overlay | automated gates green (`make prove-shell`); windowed accessibility pass pending (`docs/m4a1-shell-proof.md`) |
| Mouse hold-to-push | Held approach/engage for scripted movable furniture | automated gates green; windowed accessibility pass pending (`docs/mouse-hold-push-proof.md`) |
| Mouse accessibility hardening | Effective targets, optional pure hover, physical/touch parity, target precedence, atomic modal takeover, exhaustive contract gate | done — automated gates green and user-attested windowed standard-mouse/macOS-Accessibility-Keyboard passes for Emily and Carnby (`docs/mouse-accessibility-hardening-proof.md`) |
| Enhanced graphics scene layer | Higher-resolution actor rendering, per-vertex shading, GPU mask erasure, background upscale filters, asset override directory, GL fallback | automated gates green; windowed attestation pending (`docs/enhanced-graphics-proof.md`) |
| M4 | Menus, audio, save/load, ending/completability | later |

Design docs live in `docs/superpowers/specs/` and `docs/superpowers/plans/`
(one spec + one task-level TDD plan per milestone). `docs/life-vm-opcodes.md`
is the opcode research doc (note: its opcode numbers were later corrected
against `AITD1.cpp` — the plan + code are the source of truth).

## Architecture (PyAitD/)

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
| `skel.py`, `mask.py` | Skinning/projection (the FITD-faithful integer path, `skin()`), mask bitmap rasterization |
| `scene.py` | `build_frame(game, floor, resolver) -> (FrameDescription, draw_list)`: per-frame scene description shared by both backends; `CameraView`, a float twin of `skel.skin`'s projection, for the new renderers. `draw_list` stays built from the logical `skin()` bbox — picking, masks and the mouse contract are untouched |
| `geometry.py` | `pose_geometry(...) -> BodyGeometry`: float posed vertices, per-vertex normals, triangulated/line/point/sphere primitives, shared with `skel.pose_vertices` so pose can never disagree |
| `mask_geometry.py` | Mask polygons in 320x200 screen space plus their trigger rects, parsed once from the existing mask data |
| `asset_resolver.py` | `AssetResolver(assets, override_dir=None)`: background/palette lookup, checking an optional override directory first and falling back to the original asset |
| `render_options.py` | `RenderOptions(scale, shading, background_filter, override_dir)`: validation, clamping, menu-cycle helpers; pygame/GL-free |
| `render_gl.py` | `GLBackend(ctx, options)`: ModernGL pipeline, per-actor depth, GPU mask-texture erasure, shading modes, background filtering |
| `render_soft.py` | `SoftwareBackend`: numpy/pygame compositor over the logical projection, used headless and as the GL-failure fallback |
| `render.py` | `Renderer(options)`: window/context ownership, backend selection and fallback, UI composite, present, `window_to_logical` |
| `anim_action.py` | GereFrappe action runner: melee (1→10→2), hit-object, firearm volume sweep (4→5), throw setup/launch/flight (6→7→9). Publishes `hit`/`hit_by`/`hit_force` only — never actor `life` |
| `scenario.py` | `COMBAT_VENUE`/`enter_combat_venue`: the one pinned floor-5 debug venue shared by play, tests and the proof tool |
| `playworld.py` | PlayWorld tick (mainLoop.cpp:41-281 order): input snapshot → anim/dec pass → LIFE pass → floor/room/camera flags → messages. Free of pygame/GL: `play_tick` runs headless |
| `navmesh.py` | Walkable grid from cover zones (FITD `is_in_poly` vectorised) + A* |
| `picking.py` | Screen->world: floor homography fitted from the real projection, actor bbox hit-test |
| `navigate.py` | Mouse follower: NavIntent -> one tick of steering + mirrored joyd |
| `mouse_contract.py` | Pygame-free declaration of current player capabilities, per-mode one-button routes, and reviewed legacy command replacements (`KEYBOARD_ONLY_DECISIONS` is empty: remap capture has a clickable key picker) |
| `config.py` | Pygame-free settings schema (v1), platform settings path, validated load, atomic save |
| `__main__.py` | Process shell: event pump, fixed-step accumulator, `_scene_frame` view assembly, modal routing, one present per frame |

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
- Masks are GPU-rasterised polygons per actor (a mask texture, not hardware
  stencil: ModernGL has no depth-stencil renderbuffer API).

Remaining stubs in `life_ops.py` consume exact FITD arg counts and log under trace
(audio, text) — scripts stay desync-free until real semantics land. The combat
opcodes are no longer stubs: `LM_HIT`, `LM_FIRE` and `LM_THROW` arm the real
action runner.

## M3b interaction boundary

- `effects.py`: typed immediate/modal effects and resumable LIFE frames.
- `interaction.py`: found-LIFE, inventory/world transitions, contacts, and GereDec.
- `ui.py`: command buffering, modal reducers, mouse targets, and 320x200 presenters.
- `playworld.py`: the PLAY-only fixed tick body, free of pygame/rendering.
- `__main__.py`: one event pump, tick accumulator, mode routing, one present.
- Focused proof: `make prove-m3b`.
- Full regression: `.venv/bin/pytest -q && make prove`.
- Manual evidence: `docs/m3b-interaction-proof.md`.
- M3d mouse-input proof (navmesh coverage per floor): `make prove-mouse`; manual evidence `docs/m3d-mouse-input-proof.md`.

## M3c combat boundary

- `game.FloorStart` is the restart boundary `(stage, room, x, y, z, camera_slot)`;
  `enter_floor_start` is the one "immediately be on a floor" implementation and
  performs no Floor I/O — `__main__.run` owns loading the Floor, before and after
  a restart.
- `scenario.COMBAT_VENUE` = `FloorStart(5, 4, -7800, -4010, -1000, 0)`, the only
  supported non-attic debug start (`--combat-venue`; a non-zero `--floor` exits 2).
- `LM_GAME_OVER` raises `flag_game_over`; `playworld` turns it into a
  `GameOver(120)` modal only after the complete LIFE pass — including a flag the
  real death script raises from a LIFE continuation resumed between ticks, which
  the next tick consumes before re-running that LIFE. `__main__.restart_session`
  rebuilds a fresh `Game` at the same `FloorStart`.
- A cross-floor `LM_STAGE` consumes its room change in the same tick (FITD
  mainLoop.cpp:189-199) and regenerates the active list through the existing
  `flag_genere_aff_list` gate: FITD's stale anim pass is an out-of-range
  `roomDataTable` read C++ tolerates and Python cannot.
- Focused proof: `make prove-combat`; evidence and the open gap:
  `docs/m3c-combat-proof.md`.
- Deferred (review rulings): `choose_inventory_action` sets in-hand + action
  directly where FITD sets in-hand only via LM_IN_HAND — revisit when M3c
  combat items land; `gere_dec` stops at the first containing zone where FITD
  re-scans the new room's zones in the same call (one-tick delay on chained
  crossings); modal result records live in `ui.py` though locked ownership
  puts them in `effects.py`; `op_special` still carries an M3b stub label.

## M3e mouse-reachability boundary

- `tracks.face_toward` is an instantaneous clicked-attack adapter; ordinary
  `_turn_toward` interpolation and its existing callers remain unchanged.
- `interaction.attack_in_hand` validates the target, stops navigation, and
  faces in the hero's room frame. It deliberately chooses no inventory action:
  ENGLISH.PAK text 32 is `Throw`, so delegating to `choose_inventory_action`
  launched the held object at the floor instead of swinging it.
- A target click instead arms a bounded input-local native combat latch.
  `route_play_click` stores the accepted target in the application-owned
  `InputBuffer`; `playworld._apply_mouse_attack` publishes FITD's ordinary
  `local_joyd = 1`, `local_click = 1` and `action = 0x2000` on each fixed tick
  until the melee animation completes, bounded at 100 ticks. The simulation
  never learns that a mouse exists, and every existing focus, modal,
  input-mode and restart `reset_input` seam already clears the latch, so no
  click can resume a swing after a takeover.
- Explicit inventory `Throw` is unchanged and remains reachable only by
  choosing that row; throw setup, flight and floor placement are untouched.
- `game.activate_world_object` is shared by normal active-list regeneration
  and throw release so a released projectile exists before later LIFE reads.
- `scenario.enter_mouse_combat_fixture` owns the deterministic object-38
  automated/manual proof start; the M3c `enter_combat_venue` remains unchanged.
- `__main__.resolve_play_click` is the one HUD/attack/target/walk/blocked
  resolver used by both hover and click routing.
- `playworld._push_into_target` re-aims an arrived click at a non-foundable
  object that has a `found_life`, so the final step collides with the object
  and the scripted found fires from the collision (FITD anim.cpp:381: the
  attic lamp's found requires HARD_COL, unreachable via M3d's approach snap).
- It applies to every non-foundable `found_life` object, not just the lamp —
  an accepted out-of-plan addition from M3e review, not drift.
- Focused proof: `make prove-mouse-only`; manual evidence:
  `docs/m3e-mouse-only-proof.md`.
- This milestone does not claim complete-game mouse play; M4 owns that gate.

## M4a1 shell boundary

- `config.py` owns the pygame-free settings schema (v1: bindings for eight
  controls, CANCEL fixed to Escape, sticky flag), the platform settings path,
  and the atomic store (temp file + fsync + `os.replace`).
- `ui.py` owns the compiled pygame bindings, transient input state
  (held/action/sticky/commands), the modal presenters and reducers, all shell
  drawing, and the hit geometry (`CharacterLayout`/`SystemMenuLayout`/
  `SettingsNoticeLayout`).
- `__main__.py` owns the application session (`ModalSession` settings fields),
  the persistence policy (load once at boot, save at dirty boundaries), raw
  remap capture (consumes the captured KEYDOWN exclusively), the event pump,
  settings-notice first refusal, and the atomic game/floor/session/input
  replacement (`_hero_branch`/`_restart_branch` + one tuple assignment).
- `Game` owns no settings; settings never enter world state.
- Normal boot stages floor zero but never ticks or presents PLAY before
  character confirmation; explicit `--floor 0`, `--combat-venue`, and
  `--mouse-combat-fixture` bypass the selector.
- Focused proof: `make prove-shell`; evidence (automated run, windowed pass
  pending): `docs/m4a1-shell-proof.md`.
- The three-row MAIN menu (Return/Configuration/Quit) is the stable host into
  which M4a2 inserts Save/Load.

## Mouse hold-to-push boundary

- `NavIntent` latches a world-object index and distinguishes held approach from
  engaged contact; transient actor slots are resolved again every tick.
- Engagement projects AITD1 player animation 5 while ordinary follower output
  supplies forward contact. LIFE 1 enables the opening wardrobe's `AF_MOVABLE`;
  `resolve_actor_contacts` alone moves it.
- Mouse release, focus loss, modal entry, target/floor/room invalidation, and
  bounded stall share idempotent cancellation. Pushing never asserts Action.
- Focused proof: `make prove-mouse-only`; evidence:
  `docs/mouse-hold-push-proof.md`.

## Testing conventions

Golden values are pinned from real game data (do not re-derive): 292 world objects,
207 vars, 45 CVars, 563 scripts, 45 tracks, camera/body/anim pins per plan doc.
Tests skip when game data absent (`data_dir` fixture). New work follows the
brainstorm → spec → plan → subagent-driven TDD workflow recorded in `docs/superpowers/`.
