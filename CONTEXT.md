# CONTEXT — PyAitD

Python engine rewrite of **Alone in the Dark 1 (DOS, 1992)** — a faithful,
test-driven port of the [FITD](https://github.com/fn2006/FITD) C++
decompilation (GPLv2), targeting Apple Silicon with pygame-ce + ModernGL.

- Repo: `/Users/felipe.dos.santos/code/mine/m-aitd` (branch `main`)
- FITD reference: `/Users/felipe.dos.santos/code/theirs/FITD/FitdLib/` (authoritative for all game logic)
- Game data: `data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK`
- Python 3.12, `.venv/`; deps: pygame-ce, moderngl, numpy, pytest — no more.
  `tools/regenerate_backgrounds.py` reaches Gemini through the `agy` CLI
  (`subprocess`), so the one external service costs no Python dependency
- Version 0.5.0 (`pyproject.toml`); GPL-2.0-only

## Commands

```bash
make run                     # play (windowed) through character selection; floor=0 for the attic debug bypass, trace=/tmp/t.log writes per-opcode LIFE trace; overrides=DIR defaults to data/aitd1/overrides
make run-combat               # play the supported floor-5 combat venue (hero=0 Carnby, hero=1 Emily)
make run-mouse-combat         # deterministic object-38 mouse combat proof start (hero=0 Carnby, hero=1 Emily)
make test                     # whole pytest suite, headless — authoritative gate
make test-engine              # simulation, LIFE VM, formats, actors, anim, tracks, collision, navmesh, picking, opcodes
make test-render              # scene, geometry, both backends, asset resolution, override export/check
make test-shell                # event pump, settings, CLI, UI screens and modals
make test-tools                # the standalone scripts under tools/
make test-meta                 # the repo's own rules (package layering, test grouping)
make test-journey              # real run() event pump and long real-data simulations
make proof-mouse               # navmesh for every camera-visible room, every floor (needs game data)
make proof-combat              # venue, real enemy damage, player arms, game over (needs game data)
make proof-graphics            # attic + combat fixtures at every shading mode -> docs/graphics-proof/ (needs GL + game data)
make proof-intro               # opening cutscene: headless gate + one GL render per visited camera
make export-backgrounds      # originals + guides + manifest -> data/aitd1/overrides (out=, floors=, scale=, force=1)
make check-overrides         # validate an override dir as the game loads it (overrides=DIR, proof=1 side-by-sides)
make regenerate-backgrounds  # Gemini describe+render -> data/aitd1/overrides-ai (dry=1, floors=, style=, force=1); needs the `agy` CLI on PATH
make run overrides=DIR       # play with a different override directory (e.g. data/aitd1/overrides-ai); overrides= plays the originals
```

The nine legacy `prove-*` names remain as aliases of the targets above --
`prove` is `test-engine`; `prove-m3b` and `prove-shell` both run `-m "engine
or shell"`; `prove-mouse-only` and `prove-mouse-accessibility` are
`test-shell`; `prove-mouse`, `prove-combat`, `prove-graphics` and
`prove-intro` are the matching `proof-*` target. See `## Test grouping`
below for what pins each alias to the files it historically ran.

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
| M4a1 | Shell: character select, system menu, remappable controls, sticky Action, settings persistence, settings notice overlay | done — automated gates green (`make prove-shell`); the windowed pass is attested by the mouse accessibility hardening proof, which supersedes the pending rows in `docs/m4a1-shell-proof.md` |
| Mouse hold-to-push | Held approach/engage for scripted movable furniture | done — automated gates green; windowed pass attested via the hardening proof, superseding `docs/mouse-hold-push-proof.md` |
| Mouse accessibility hardening | Effective targets, optional pure hover, physical/touch parity, target precedence, atomic modal takeover, exhaustive contract gate | done — automated gates green and user-attested windowed standard-mouse/macOS-Accessibility-Keyboard passes for Emily and Carnby (`docs/mouse-accessibility-hardening-proof.md`) |
| Enhanced graphics scene layer | Higher-resolution actor rendering, per-vertex shading, GPU mask erasure, background upscale filters, asset override directory, GL fallback | automated gates green; windowed attestation pending (`docs/enhanced-graphics-proof.md`) |
| AI background regeneration | Export originals + structure guides + manifest, validate override dirs as the game loads them, optional Gemini describe+render regeneration | done — `make export-backgrounds` / `check-overrides` / `regenerate-backgrounds`; `docs/ai-background-regeneration.md` |
| Engine package reorganization | engine / render / games / app split + GameProfile | done — `tests/test_layering.py` |
| M4a2 / M4b / M4c | Save/load, audio + sequences, ending/completability | next (plans drafted under `docs/superpowers/plans/2026-08-24-m4*`) |

Design docs live in `docs/superpowers/specs/` and `docs/superpowers/plans/`
(one spec + one task-level TDD plan per milestone). `docs/life-vm-opcodes.md`
is the opcode research doc (note: its opcode numbers were later corrected
against `AITD1.cpp` — the plan + code are the source of truth).

## Architecture (PyAitD/)

| Module | Role |
|---|---|
| `engine/pak.py`, `engine/floor.py`, `engine/explode.py` | PAK/HQR archives, ETAGE floor data, EXPLODE decompression. `Floor(data_dir, number, profile)` takes the profile for the palette pak/entry; callers holding a `Game` use `game.load_floor(number)` instead (`rooms_of_floor` deliberately does not) |
| `engine/formats.py` | Pure parsers: bodies, anims, cameras, cover zones, WorldObject/VARS/DEFINES/PRIORITY records |
| `engine/assets.py` | Parse-once registries over the LRU: bodies, anims, LISTLIFE scripts, LISTTRAK tracks |
| `engine/game.py` | `Game` state: CVars (45, DEFINES big-endian), script vars (207), 292 world objects, 128 actor slots, `init_game`/`spawn_stage_actors` (FITD LoadWorld + GenereActiveList) |
| `engine/life.py` | VM core: fetch loop, 0x8000 actor-switch, control flow, `Trace`, `core_table()` (the game-neutral opcode slots); dispatch reads the filled table from `vm.game.profile.opcode_table` and the not-in-floor set from `vm.game.profile.reduced_dispatch` |
| `games/base.py` | `GameProfile`: PAK names, palette entry, hero archives, CVar names, DEFINES endianness, opcode table, reduced dispatch + its allowed opcode set, debug venues |
| `games/aitd1/profile.py` | The AITD1 instance; `games/__init__.load_profile("aitd1")` |
| `games/aitd1/life_ops.py`, `games/aitd1/life_reduced.py` | Full-dispatch opcode handlers + not-in-floor reduced set |
| `engine/eval_var.py` | evalVar tagged-s16 argument system (all AITD1 property codes) |
| `engine/tracks.py` | processTrack: manual (player) / follow / scripted modes, TL_* macros |
| `engine/realvalue.py` | RealValue interpolation (rotation/speed ramps), chronos, GiveDistance2D |
| `engine/actors.py` | Actor fields (tObject port), GereAnim movement/collision port, `sort_actor_indices` (FITD sortActorList) |
| `engine/anim.py` | AnimPlayer: SetAnimObjet/SetInterAnimObjet keyframe interpolation; `init_anim`/`ANIM_ONCE`/`ANIM_REPEAT`/`ANIM_UNINTERRUPTABLE` |
| `engine/world.py`, `engine/cos_table.py` | Fixed-point rotations, camera transform/projection (M2-verified goldens) |
| `engine/skel.py`, `engine/mask.py` | Skinning/projection (the FITD-faithful integer path, `skin()`), mask bitmap rasterization |
| `render/scene.py` | `build_frame(game, floor, resolver) -> (FrameDescription, draw_list)`: per-frame scene description shared by both backends; `CameraView`, a float twin of `skel.skin`'s projection, for the new renderers. `draw_list` stays built from the logical `skin()` bbox — picking, masks and the mouse contract are untouched |
| `render/geometry.py` | `pose_geometry(...) -> BodyGeometry`: float posed vertices, per-vertex normals, triangulated/line/point/sphere primitives, shared with `skel.pose_vertices` so pose can never disagree |
| `engine/mask_geometry.py` | Mask polygons in 320x200 screen space plus their trigger rects, parsed once from the existing mask data |
| `render/asset_resolver.py` | `AssetResolver(assets, override_dir=None)`: background/palette lookup, checking an optional override directory first and falling back to the original asset |
| `render/render_options.py` | `RenderOptions(scale, shading, background_filter, override_dir)`: validation, clamping, menu-cycle helpers; pygame/GL-free |
| `render/render_gl.py` | `GLBackend(ctx, options)`: ModernGL pipeline, per-actor depth, GPU mask-texture erasure, shading modes, background filtering |
| `render/render_soft.py` | `SoftwareBackend`: numpy/pygame compositor over the logical projection, used headless and as the GL-failure fallback |
| `render/render.py` | `Renderer(options)`: window/context ownership, backend selection and fallback, UI composite, present, `window_to_logical` |
| `engine/anim_action.py` | GereFrappe action runner: melee (1→10→2), hit-object, firearm volume sweep (4→5), throw setup/launch/flight (6→7→9). Publishes `hit`/`hit_by`/`hit_force` only — never actor `life` |
| `games/aitd1/scenario.py` | `COMBAT_VENUE`/`enter_combat_venue`: the one pinned floor-5 debug venue shared by play, tests and the proof tool |
| `engine/playworld.py` | PlayWorld tick (mainLoop.cpp:41-281 order): input snapshot → anim/dec pass → LIFE pass → floor/room/camera flags → messages. Free of pygame/GL: `play_tick` runs headless |
| `engine/navmesh.py` | Walkable grid from cover zones (FITD `is_in_poly` vectorised) + A* |
| `engine/picking.py` | Screen->world: floor homography fitted from the real projection, actor bbox hit-test |
| `engine/navigate.py` | Mouse follower: NavIntent -> one tick of steering + mirrored joyd |
| `games/aitd1/mouse_contract.py` | Pygame-free declaration of current player capabilities, per-mode one-button routes, and reviewed legacy command replacements (`KEYBOARD_ONLY_DECISIONS` is empty: remap capture has a clickable key picker) |
| `engine/text.py` | Pure parsers for system texts and book/letter token streams (readable items) |
| `render/background_export.py` | Pure export description: per-camera original background, depth-culled structure guide geometry, manifest records (layout shared with `asset_resolver.override_background_path`) |
| `render/override_check.py` | Pure validation of an override directory exactly as `AssetResolver` would load it; structural manifest checks |
| `app/config.py` | Pygame-free settings schema (v1), platform settings path, validated load, atomic save |
| `app/shell.py` | The process shell formerly in `__main__.py`; `__main__.py` is now a one-line re-export |
| `tools/` | CLI proofs and pipelines: `prove_mouse`, `prove_combat`, `prove_graphics`, `export_backgrounds`, `check_overrides`, `regenerate_backgrounds` (the only module that talks to an AI service; PNG encoding lives here, not in `PyAitD/`) |

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
- `FoundResult` moved from `ui.py` to `engine/effects.py`, and `init_anim`
  (with `ANIM_ONCE`/`ANIM_REPEAT`/`ANIM_UNINTERRUPTABLE`) moved from
  `life_ops.py` to `engine/anim.py`, so the engine imports no game or app
  module.

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

- `engine/effects.py`: typed immediate/modal effects and resumable LIFE frames.
- `engine/interaction.py`: found-LIFE, inventory/world transitions, contacts, and GereDec.
- `app/ui.py`: command buffering, modal reducers, mouse targets, and 320x200 presenters.
- `engine/playworld.py`: the PLAY-only fixed tick body, free of pygame/rendering.
- `app/shell.py`: one event pump, tick accumulator, mode routing, one present.
- Focused proof: `make prove-m3b`.
- Full regression: `.venv/bin/pytest -q && make prove`.
- Manual evidence: `docs/m3b-interaction-proof.md`.
- M3d mouse-input proof (navmesh coverage per floor): `make prove-mouse`; manual evidence `docs/m3d-mouse-input-proof.md`.

## M3c combat boundary

- `game.FloorStart` is the restart boundary `(stage, room, x, y, z, camera_slot)`;
  `enter_floor_start` is the one "immediately be on a floor" implementation and
  performs no Floor I/O — `app.shell.run` owns loading the Floor, before and after
  a restart.
- `scenario.COMBAT_VENUE` = `FloorStart(5, 4, -7800, -4010, -1000, 0)`, the only
  supported non-attic debug start (`--combat-venue`; a non-zero `--floor` exits 2).
- `LM_GAME_OVER` raises `flag_game_over`; `playworld` turns it into a
  `GameOver(120)` modal only after the complete LIFE pass — including a flag the
  real death script raises from a LIFE continuation resumed between ticks, which
  the next tick consumes before re-running that LIFE. `app.shell.restart_session`
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
- `app.shell.resolve_play_click` is the one HUD/attack/target/walk/blocked
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

- `app/config.py` owns the pygame-free settings schema (v1: bindings for eight
  controls, CANCEL fixed to Escape, sticky flag), the platform settings path,
  and the atomic store (temp file + fsync + `os.replace`).
- `app/ui.py` owns the compiled pygame bindings, transient input state
  (held/action/sticky/commands), the modal presenters and reducers, all shell
  drawing, and the hit geometry (`CharacterLayout`/`SystemMenuLayout`/
  `SettingsNoticeLayout`).
- `app/shell.py` owns the application session (`ModalSession` settings fields),
  the persistence policy (load once at boot, save at dirty boundaries), raw
  remap capture (consumes the captured KEYDOWN exclusively), the event pump,
  settings-notice first refusal, and the atomic game/floor/session/input
  replacement (`_hero_branch`/`_restart_branch` + one tuple assignment).
- `Game` owns no settings; settings never enter world state.
- `app/startup.py` owns the title/credits/menu presenters; `shell.open_startup_menu`
  is the one entry into the menu; `continue_available` is the M4a2 seam; no
  idle-timeout demo (FITD `MainMenu` 0x10000-unit timeout) — a later milestone
  adds it with the intro cutscene.
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

## AI background regeneration boundary

- `background_export.py` and `override_check.py` are pure like `scene.py`;
  `tools/export_backgrounds.py` and `tools/check_overrides.py` do the PNG I/O.
  The export layout is `asset_resolver.override_background_path`'s
  (`DIR/backgrounds/floor<NN>/camera<NNN>.png` + `DIR/palette.png`) — change
  both or neither. `manifest.json` merges across `--force` floor subsets and is
  written atomically.
- `screens/ressNN.png` overrides full-screen resources; `app/ui.screen_surface`
  scales them to 320x200 at composite time.
- `tools/regenerate_backgrounds.py` reads an export dir, asks Gemini for a
  description then an image per camera, fits the result to 1280x800, and
  writes `data/aitd1/overrides-ai` plus `prompts.json` (a resumable prompt
  cache saved after every camera). It reaches Gemini by invoking the `agy` CLI
  through `subprocess.run` and imports no SDK; the tests monkeypatch
  `subprocess.run`, and `tests/test_layering.py` pins the boundary.
- Output dirs `overrides/` and `overrides-ai/` are git-ignored; a missing
  override file — or a missing override directory entirely — falls back
  silently, a corrupt one warns and falls back. `make run` points at
  `data/aitd1/overrides` by default, so that fallback is the normal path on a
  fresh clone.
- Evidence: `docs/ai-background-regeneration.md`; spec/plan under
  `docs/superpowers/*/2026-08-25-{ai,gemini}-background-regeneration*`.

## Opening cutscene boundary

- `engine.game.start_game(game, stage, room)` is FITD's `startGame`
  (main.cpp:4134) minus `PlayWorld`: resets camera/world targets, loads
  `stage`, calls `change_salle(room)`, stages `new_num_camera=0` /
  `flag_init_view=2`, spawns the stage's actors, and clears `floor_start` —
  a staged start has no restart point until a script sets one. Only
  `_boot_hero`'s cutscene branch calls it. The attic hand-over relies on
  neither `start_game` nor `game_start`'s config alone: `init_game` reads
  `profile.game_start` for its own floor/room instead of hardcoding 0/0
  (`engine/game.py`), because running `start_game` on a booted attic leaves
  `current_camera_target_actor`/`current_world_target` at -1 and
  `floor_start` at `None` — an uncontrollable hero with no restart point.
  `tests/test_floor_start.py::test_start_game_on_the_attic_diverges_from_init_game_targeting`
  pins exactly this divergence.
- `Game.allow_system_menu` mirrors FITD's `allowSystemMenu` parameter to
  `PlayWorld`. While it's `False` (set right after `start_game` for the
  intro), `flag_game_over` going true surfaces as `effects.CutsceneFinished`
  (`GameMode.CUTSCENE_END`) instead of `GameOver` — the opening cannot be
  "lost", only finished or skipped.
- The reduced `LM_STAGE` handler (`games/aitd1/life_reduced.py`) raises
  `flag_genere_aff_list` when an object is staged onto the *current* floor,
  so the existing per-tick spawn scan (`playworld._genere_active_list`)
  picks it up later in that same tick, at the tail of the LIFE loop — not
  the next one (`tests/test_intro.py` asserts at tick 1596, not 1597, for
  exactly this reason) — without this the intro's director (life 547 →
  object 288) never spawns and the cutscene stalls forever at tick 1596.
  `ponytail:` this raises the existing gated scan; it does **not** make the
  scan unconditional. FITD's `GenereActiveList` runs every frame regardless
  (`mainLoop.cpp:249`) — that unconditional scan is the faithful upgrade
  path, named here so nobody closes it ad hoc: it changes spawn timing
  everywhere, and every ticks golden in `tests/test_intro.py` (and the
  cameras `tools/prove_intro.py` visits) is pinned against the gated
  version.
- `ModalSession.cutscene` (`app/ui.py`) is the single flag that owns skip
  during the opening. The one *live* route is the event loop (`shell.run`):
  its cutscene swallow `continue`s on the first KEYDOWN, left-click
  `MOUSEBUTTONDOWN`, or `FINGERDOWN` seen while `session.cutscene`, before
  the event ever reaches command dispatch or mouse routing -- checked after
  the settings-notice Dismiss first-refusal (below), so a click on the
  notice during the opening clears the notice instead of skipping.
  `route_command`'s cutscene branch, `route_mouse`'s `CutsceneFinished`
  branch, and the command-drain's cutscene `pass` in `run()` are
  defence-in-depth, not additional live routes: with the pump swallow in
  place, no `Command` can exist while `session.cutscene` (nothing ever
  calls `event_to_input` to produce one) and no click can reach
  `route_mouse` while `CutsceneFinished` is the active modal (`session.
  cutscene` is still `True` then, so the swallow catches the click first).
  They exist for callers that invoke `route_command`/`route_mouse` directly
  -- tests today, any future caller bypassing the pump -- and are commented
  as such at each site. `PlayerCapability.SKIP_CUTSCENE` documents the
  live route for `GameMode.PLAY` and `GameMode.CUTSCENE_END` in the mouse
  contract; its `GameMode.PLAY` entry is the contract's one
  session-conditional capability (true only while `session.cutscene` --
  ordinary `PLAY` routes a left click to walk/interact instead), commented
  as such in `mouse_contract.py`. `--skip-intro` sets `session.skip_intro`,
  a development-only bypass (not FITD behaviour) that boots straight to the
  attic instead of staging the cutscene at all.
- `_boot_hero` (`app/shell.py`) is the one hero-boot path shared by
  `_hero_branch` (character confirmation → the opening, `cutscene=True`,
  `start_game(*profile.intro_start)`) and `_cutscene_end_branch`
  (`CutsceneFinished` or `skip_cutscene` → the attic, `cutscene=False`,
  no `start_game` call — FITD's own hand-over is `startGame(0, 0, 1)`,
  `AITD1.cpp:361`, but the port reaches the same floor/room through
  `init_game`'s `game_start` staging instead, per the note above) — same
  `init_game` + conditional `start_game` staging, same atomic
  replacement-tuple contract as the rest of `shell.py`'s hero/restart swaps.
- Focused proof: `make prove-intro` (headless golden-tick gate +
  `tools/prove_intro.py`, one GL render per camera the opening visits);
  tests: `tests/test_intro.py` (golden ticks, both heroes) and the real-loop
  journeys in `tests/test_shell_journeys.py`; evidence: `docs/intro-proof.md`.

## Testing conventions

Golden values are pinned from real game data (do not re-derive): 292 world objects,
207 vars, 45 CVars, 563 scripts, 45 tracks, camera/body/anim pins per plan doc.
Tests skip when game data absent (`data_dir` fixture). New work follows the
brainstorm → spec → plan → subagent-driven TDD workflow recorded in `docs/superpowers/`.

## Test grouping

`tests/` is partitioned by one module-level subject marker per file — `engine`,
`render`, `shell`, `tools`, `meta` — with an optional cross-cutting `journey`.
The Makefile's `test-*` targets are `pytest -m <marker>`; the vocabulary lives
in `pyproject.toml` and `--strict-markers` rejects anything else.

`tests/test_test_groups.py` owns three properties: the subjects cover every
test file and never overlap, the vocabulary matches `pyproject.toml`, and
every legacy `prove-*` alias still exists in the Makefile — and, for the five
of the nine that gated pytest files before markers replaced their recipe
(`prove`, `prove-m3b`, `prove-shell`, `prove-mouse-only`,
`prove-mouse-accessibility`), still selects each file it ran before. That
last one is why the proof documents can keep citing `make prove-shell` and
friends without being rewritten; the other four aliases (`prove-mouse`,
`prove-combat`, `prove-graphics`, `prove-intro`) are straight renames of the
`proof-*` artifact targets, which need real game data (and GL, for
graphics/intro) rather than a pinned file list. Its `LEGACY_GATE_FILES` table
is historical data captured at `4024b10` — fix a marker when it fails, never
the table.

Markers are parsed with `ast`, never by importing the modules, so the
enforcement costs one file read per test file and cannot trigger a module-level
fixture.
