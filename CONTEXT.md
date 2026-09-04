# CONTEXT — PyAitD

Python engine rewrite of **Alone in the Dark 1 (DOS, 1992)** — a faithful,
test-driven port of the [FITD](https://github.com/fn2006/FITD) C++
decompilation (GPLv2), targeting Apple Silicon with pygame-ce + ModernGL.

- Repo: `/Users/felipe.dos.santos/code/mine/m-aitd` (branch `main`)
- FITD reference: `/Users/felipe.dos.santos/code/theirs/FITD/FitdLib/` (authoritative for all game logic)
- Game data: `data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK`
- Python 3.12, `.venv/`; deps: pygame-ce, moderngl, numpy, pytest — no more.
  `tools/bootstrap_materials.py` reaches Gemini through the `agy` CLI
  (`subprocess`), so the one external service costs no Python dependency
- Version 0.8.0 (`pyproject.toml`); GPL-2.0-only

## Commands

```bash
make run                     # play (windowed) through character selection; floor=0 for the attic debug bypass, trace=/tmp/t.log writes per-opcode LIFE trace; textures=DIR defaults to data/aitd1/textures
make run-combat               # play the supported floor-5 combat venue (hero=0 Carnby, hero=1 Emily)
make run-mouse-combat         # deterministic object-38 mouse combat proof start (hero=0 Carnby, hero=1 Emily)
make test                     # whole pytest suite, headless — authoritative gate
make test-engine              # simulation, LIFE VM, formats, actors, anim, tracks, collision, navmesh, picking, opcodes
make test-render              # scene, geometry, both backends, asset resolution, texture export/check
make test-shell                # event pump, settings, CLI, UI screens and modals
make test-tools                # the standalone scripts under tools/
make test-meta                 # the repo's own rules (package layering, test grouping)
make test-journey              # real run() event pump and long real-data simulations
make proof-mouse               # navmesh for every camera-visible room, every floor (needs game data)
make proof-combat              # venue, real enemy damage, player arms, game over (needs game data)
make proof-graphics            # attic + combat fixtures at every shading mode, plus flat-mesh, hard-shadow, un-composited, over-composited, tickmotion, painted, nossao, roomshadow and nohaze pairs, -> docs/graphics-proof/ (needs GL + game data; motion=, occlusion=, atmosphere= set the main renders' modes)
make proof-intro               # opening cutscene: headless gate + one GL render per visited camera
make prove-persistence         # M4a2 gate: save schema, slots, restoration, menu pages, loop policy, journeys, mouse contract (headless)
make export-textures         # originals + 5 KILLED_SORCERER alts + palette + guides + per-body UV sidecars/painter guides + manifest schema 4 -> data/aitd1/textures, then palette ramps + body usage -> <out>/materials-survey + PyAitD/render/materials.json (out=, floors=, scale=, force=1, screens=0 skips screens, uvs=0 skips the actor UV bake, materials=0 skips materials, vision=1 asks Gemini through agy)
make check-textures          # validate a texture dir as the game loads it (textures=DIR, proof=1 side-by-sides: bases, alts -alt.png, screens)
make run textures=DIR        # play with a different texture directory; textures= plays the originals
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
| M3d | Mouse-only input: held pointer follow since 2026-08-26 (was point-and-click) | done |
| M3e | Mouse reachability: HUD inventory, clicked native melee, exhaustive mouse contract | done (the clicked route was corrected from force-2 throw to native melee; `docs/mouse-accessibility-hardening-proof.md`) |
| M4a1 | Shell: character select, system menu, remappable controls, sticky Action, settings persistence, settings notice overlay | done — automated gates green (`make prove-shell`); the windowed pass is attested by the mouse accessibility hardening proof, which supersedes the pending rows in `docs/m4a1-shell-proof.md` |
| Mouse hold-to-push | Held approach/engage for scripted movable furniture | done — automated gates green; windowed pass attested via the hardening proof, superseding `docs/mouse-hold-push-proof.md` |
| Mouse accessibility hardening | Effective targets, optional pure hover, physical/touch parity, target precedence, atomic modal takeover, exhaustive contract gate | done — automated gates green and user-attested windowed standard-mouse/macOS-Accessibility-Keyboard passes for Emily and Carnby (`docs/mouse-accessibility-hardening-proof.md`) — re-attestation pending: held pointer follow made PLAY movement press-and-hold, so the dwell-click / Accessibility Keyboard attestation no longer covers walking or approaching objects (`docs/superpowers/specs/2026-08-26-held-pointer-follow-design.md`) |
| Mouse fidelity | Walking possible from every pixel (an unreachable one steers along its bearing), viewed rooms picked at their own depth, an eight-pixel snap budget, a six-pixel dead zone after a camera cut, and a destination marker, hover preview and press ring on the cursor; the occlusion filter is built and tested but ships OFF (`picking.OCCLUDE_BY_DEFAULT`) — with it on, 87 of the game's 274 camera slots had no clickable floor at all, 14 even after clipping the ray at the room's own volume, so a whole-game census gates it | automated gates green; windowed attestation pending (`docs/mouse-fidelity-proof.md`) |
| Enhanced graphics scene layer | Higher-resolution actor rendering, per-vertex shading, GPU mask erasure, background upscale filters, asset texture directory, GL fallback | automated gates green; windowed attestation pending (`docs/enhanced-graphics-proof.md`) |
| Smooth actor geometry | GPU PN tessellation behind `smoothing`, crease-aware corner normals, tessellated shadow, Graphics sub-page | automated gates green; windowed attestation pending (`docs/smooth-geometry-proof.md`) |
| Soft shadows (roadmap F) | Contact-hardening penumbra, one gathered shadow pass, light-view shadow map for self/inter-actor shadowing, `shadows` knob | automated gates green; windowed attestation pending (`docs/soft-shadows-proof.md`) |
| Plate integration (roadmap G) | Actors resolved into their own layer and composited back through the plate's softness, tone curve and grain, graded by an `integration` level 0-3 that defaults to 2 (the full match) | automated gates green; windowed attestation pending (`docs/plate-integration-proof.md`) |
| Materials v2 (roadmap H) | Derivative bump so `detail` is relief and not dirt, a warm skin terminator, real emissive, a normalised specular lobe, the 23 used palette ramps hand-reviewed, and the class table retuned against the fixtures | automated gates green; windowed attestation pending (`docs/materials-v2-proof.md`) |
| Motion interpolation (roadmap 2 I) | Inter-tick pose/position blending behind a Motion knob, float pose twin, Graphics/Realism menu split | automated gates green; windowed attestation pending (`docs/motion-interpolation-proof.md`) |
| Actor surface textures (roadmap 2 J) | xatlas UV bake, per-corner sidecar + painter guide, manifest schema 4, albedo atlas sampled in the actor shader | automated gates green; windowed attestation pending (docs/actor-textures-proof.md) |
| Light transport (roadmap 2 K) | Half-resolution G-buffer prepass + SSAO pass (`occlusion` knob) attenuating the fill share, and a third `shadows="room"` mode with a floor + hard_col-top receiver pass | automated gates green; fixture-review gate on `shadows`'s default and windowed attestation both pending (docs/light-transport-proof.md) |
| Atmosphere (roadmap 2 L) | A linear eye-depth MRT resolved beside the actor layer, distance haze toward the room's ambient tone, and depth-graded softness and grain, behind an `atmosphere` knob that defaults on | automated gates green; windowed attestation pending (`docs/atmosphere-proof.md`) |
| **Actor realism roadmap 2 (I + J + K + L)** | All four sub-projects landed. The spec's closing frame-time budget -- attic at scale 4, msaa 4, smoothing 2, all four on versus all four off -- measured 1.02-1.05x across four runs against a 1.5x ceiling | **complete** -- automated gates green across all four; every windowed attestation still pending |
| Texture export + check | Export originals + structure guides + manifest for an external texture tool, validate texture dirs as the game loads them; the same target surveys palette ramps and emits the material table | done — `make export-textures` / `check-textures` (regeneration itself moved to an external tool) |
| Engine package reorganization | engine / render / games / app split + GameProfile | done — `tests/test_layering.py` |
| Engine domain subpackages | data/space/actor/script/nav + 12 GameProfile seam fields | done — docs/superpowers/specs/2026-08-31-engine-domain-subpackages-design.md |
| M4a2 | Save/load: validated atomic JSON slots, persistence menu pages, deferred quick save, atomic load replacement | automated gates green (`make prove-persistence`); windowed attestation pending (`docs/m4a2-persistence-proof.md`) |
| M4b / M4c | Audio + sequences, ending/completability | next (plans drafted under `docs/superpowers/plans/2026-08-24-m4*`) |

Design docs live in `docs/superpowers/specs/` and `docs/superpowers/plans/`
(one spec + one task-level TDD plan per milestone). `docs/life-vm-opcodes.md`
is the opcode research doc (note: its opcode numbers were later corrected
against `AITD1.cpp` — the plan + code are the source of truth).

## Architecture (PyAitD/)

The engine is organised into five domain subpackages:

| Domain | Modules |
|---|---|
| `engine/data/` | `pak.py` PAK/HQR archives; `explode.py` EXPLODE decompression; `formats.py` pure parsers (bodies, anims, cameras, cover zones, world-object/VARS/DEFINES records — record stride/mark from profile); `floor.py` ETAGE floors (rooms, cameras, masks — archive naming and mask strategy from profile); `assets.py` parse-once registries (bodies, anims, LISTLIFE, LISTTRAK, cadre bank from profile, `SCREEN_PIXELS`); `text.py` system/book text parsers; `mask.py` + `mask_geometry.py` mask rasterization and screen-space polygons |
| `engine/space/` | `cos_table.py` + `world.py` fixed-point rotations, camera transform/projection; `realvalue.py` rotation/speed interpolation, chronos, distances |
| `engine/actor/` | `actors.py` actor fields + GereAnim movement/collision; `anim.py` AnimPlayer; `anim_action.py` combat action runner; `tracks.py` track processor; `skel.py` skinning/projection (integer path, authoritative) |
| `engine/script/` | `game/` (`state.py` Game/Actor/FloorStart, `zv.py` ZV geometry, `objects.py` object-slot lifecycle, `boot.py` boot/transitions); `life.py` VM core (dispatch reads `profile.opcode_table`, core table built from `profile.core_slots`); `eval_var.py` evalVar; `interaction/` (`inventory.py`, `life_cont.py`, `combat.py`, `contacts.py`, `nav_intent.py`, `track_mode.py`); `effects.py` typed effects; `playworld/` (`tick.py`, `input.py`, `held_push.py`, `passes.py`); `save.py` versioned snapshots |
| `engine/content/` | `schema.py` pack records + `BEHAVIOUR_LIFE`; `pack.py` reader, digest, archive checks; `world.py` records -> appended `WorldObject`s, `attach`; `enemies.py` pursuer/sentry state machine; `runner.py` the tick's behaviour branch |
| `engine/nav/` | `navmesh.py` walkable grid + A*; `picking.py` screen->world, hard-col occlusion (off by default), snap budget, steer bearings, marker projection; `navigate.py` pointer follower |

The games, render, app and tools packages:

| Module | Role |
|---|---|
| `games/base.py` | `GameProfile`: PAK names, palette entry, hero archives, CVar names, DEFINES endianness, opcode table, reduced dispatch + its allowed opcode set, debug venues |
| `games/aitd1/profile.py` | The AITD1 instance; `games/__init__.load_profile("aitd1")` |
| `games/aitd1/life_ops.py`, `games/aitd1/life_reduced.py` | Full-dispatch opcode handlers + not-in-floor reduced set |
| `render/scene.py` | `build_frame(game, floor, resolver) -> (FrameDescription, draw_list)`: per-frame scene description shared by both backends; `CameraView`, a float twin of `skel.skin`'s projection, for the new renderers. `draw_list` stays built from the logical `skin()` bbox — picking, masks and the mouse contract are untouched |
| `render/materials.py` | `Material` (12 shader parameters: roughness, specular, metallic, rim, detail, detail_scale, detail_kind, bump, sss, emissive + 2 pad), `CLASS_PRESETS`, `MaterialTable`, `parse_table`/`load_table`/`default_table`, `RealismPreset`/`PRESETS`: palette-index material classes, the hand-reviewed `materials.json`, and the two realism presets that scale every term (`classic` all-zero, so it renders byte-identically to the pre-materials engine); pygame/GL-free |
| `render/occlusion.py` | `bake_vertex_ao(body) -> (N,) float32`: rest-pose hemisphere-ray vertex occlusion, baked once per body; pygame/GL-free |
| `render/ssao.py` | `hemisphere_kernel`, `noise_rotations`, `ssao_reference(depth, normal, kernel, rotations, proj_xy, radius=SSAO_RADIUS, bias=SSAO_BIAS)`: the pure-numpy screen-space ambient occlusion twin the GL SSAO pass is pinned against, over a half-resolution G-buffer (view normals + linear view depth); pygame/GL-free, and distinct from `render/occlusion.py`'s baked rest-pose AO, which sees neither pose nor neighbours |
| `render/refine.py` | `plan_refinement(body) -> Refinement`, `corner_normals`, `subpatch(level)`, `evaluate`: rest-pose orientation, creases and smoothing groups for the GPU tessellation, and the numpy twin of the shader; pygame/GL-free |
| `render/motion.py` | snapshot/blend_states/blend_actor + pose_vertices_float: inter-tick blending for build_frame, the float twin of skel.pose_vertices; pygame/GL-free |
| `render/geometry.py` | `pose_geometry(..., ao=None, pose_fn=None) -> BodyGeometry`: float posed vertices, per-vertex normals, rest-pose vertices, baked AO, triangulated/line/point/sphere primitives, crease-aware per-corner normals and straight-edge flags when handed a refinement, plus the body's optional per-corner atlas `uv` carried through untouched; poses with `skel.pose_vertices` by default (same integer path as the logical projection), or with the `pose_fn` override (`render/motion.py`'s presentation-only float twin for inter-tick blending) |
| `render/asset_resolver.py` | `AssetResolver(assets, texture_dir=None)`: background/palette/light lookup, per-body material table (with `bodies/body<NNN>.json` override) and AO bake, checking an optional texture directory first and falling back to the original asset, tessellation plan (with the same file's `crease`), and `body_texture(num) -> (uv, ImageAsset) | None` -- the memoised per-corner UV sidecar + painted albedo atlas lookup, missing paint falling back silently and a corrupt one warning once |
| `render/lighting.py` | `estimate_light(pixels) -> SceneLight`, `shading_terms`, `project_to_plane`: a per-camera light read off the background image, and the ground-plane projection the shadow pass uses; pygame/GL-free. `light_view_matrix`, `soften`: the orthographic light view every actor's shadow map is rendered from, and the numpy twin of the penumbra blur |
| `render/render_options.py` | `RenderOptions(scale, shading, background_filter, texture_dir, lighting, msaa, realism, smoothing, shadows, integration)`: validation, clamping, menu-cycle helpers, and the `INTEGRATION_STRENGTHS` the composite multiplies by; pygame/GL-free |
| `render/render_gl.py` | `GLBackend(ctx, options)`: ModernGL pipeline, per-actor depth, GPU mask-texture erasure, shading modes, estimated scene lighting, projected ground shadows, per-material surface response, multisampling, background filtering, instanced PN tessellation of actors and their shadows, gathered contact-hardening soft shadows and a light-view shadow map behind `shadows` |
| `render/glsl.py` | Every GLSL source as a plain string; no imports, no logic |
| `render/render_soft.py` | `SoftwareBackend`: numpy/pygame compositor over the logical projection, used headless and as the GL-failure fallback |
| `render/render.py` | `Renderer(options)`: window/context ownership, backend selection and fallback, UI composite, present, `window_to_logical` |
| `games/aitd1/scenario.py` | `COMBAT_VENUE`/`enter_combat_venue`: the one pinned floor-5 debug venue shared by play, tests and the proof tool |
| `games/aitd1/mouse_contract.py` | Pygame-free declaration of current player capabilities, per-mode one-button routes, and reviewed legacy command replacements (`KEYBOARD_ONLY_DECISIONS` is empty: remap capture has a clickable key picker) |
| `render/texture_export.py` | Pure export description: per-camera original background, depth-culled structure guide geometry, manifest records (layout shared with `asset_resolver.texture_background_path`) |
| `render/texture_check.py` | Pure validation of a texture directory exactly as `AssetResolver` would load it; structural manifest checks |
| `app/config.py` | Pygame-free settings schema (v1), platform settings path, validated load, atomic save |
| `app/controls/__init__.py` | The input package: vocabulary, bindings, keyboard/pointer state, snapshot, modal reducers, routing, cursor |
| `app/controls/actions.py` | `Action`, `KEY_BINDABLE`, `DIRECTION_BITS` |
| `app/controls/bindings.py` | `compile_bindings`, `canonical_key_name`, `DEFAULT_ACTION_BY_KEY` |
| `app/controls/keyboard.py` | `KeyboardState`, `feed_key_event`, `reset_keyboard` |
| `app/controls/pointer.py` | `PointerState`, `press`, `move`, `release`, `reset_pointer`, `rebase`, `press_decision`, `hold_decision`, the decision types, the three constants |
| `app/controls/snapshot.py` | `ControlsState`, `build_play_input`, `reset`, `configure`, `feed_event` |
| `app/controls/modals.py` | the modal reducers, `capture_system_key`, `pick_system_key`, the `hit_test_*` functions |
| `app/controls/router.py` | `route_command`, `route_mouse`, `route_hover`, `resolve_play_click`, `route_play_click`, `apply_pointer`, `cancel_follow`, `rebase_follow`, `take_over_play_input`, the result appliers, `inventory_hud_available`, `pointer_actor_targets`, `expand_actor_targets` |
| `app/controls/cursor.py` | `cursor_state`, `cursor_kind`, `marker_for`, `intent_marker`, `hit_actor_ids`, `hit_feedback_rects` |
| `app/ui.py` | presenters, results, layouts, painter, `render_*`, `render_cursor`; nothing about input |
| `app/shell.py` | CLI, pump, accumulator, persistence policy, branches, presentation; the process shell formerly in `__main__.py`, which is now a one-line re-export |
| `tools/` | CLI proofs and pipelines: `prove_mouse`, `prove_combat`, `prove_graphics`, `export_textures`, `check_textures`, `bootstrap_materials` (survey/label/emit/check of the material table; its label stage is the only module that talks to an AI service, reaching Gemini through its own `agy_structured`; PNG encoding lives here, not in `PyAitD/`) |

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
- `FoundResult` moved from `ui.py` to `engine/script/effects.py`, and `init_anim`
  (with `ANIM_ONCE`/`ANIM_REPEAT`/`ANIM_UNINTERRUPTABLE`) moved from
  `life_ops.py` to `engine/actor/anim.py`, so the engine imports no game or app
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

- `engine/script/effects.py`: typed immediate/modal effects and resumable LIFE frames.
- `engine/script/interaction/`: found-LIFE, inventory/world transitions, contacts, and GereDec.
- `app/ui.py`: command buffering, modal reducers, mouse targets, and 320x200 presenters.
- `engine/script/playworld/`: the PLAY-only fixed tick body, free of pygame/rendering.
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
  puts them in `engine/script/effects.py`; `op_special` still carries an M3b stub label.

## Attic creatures and the already-inside collision rule

- The attic's two enemies are pinned in `games/aitd1/scenario.py`:
  `ATTIC_WINDOW_OBJECT` (world 9, body 23, LIFE 16 -> 17 -> 18, track 0 --
  drops in at the window from y=3000) and `ATTIC_STAIR_OBJECT` (world 21,
  body 24, LIFE 19 -> 20 -> 21, track 1 -- walks in through the north
  doorway). Before this the repo pinned only the floor-5 venue, so the game's
  first two monsters had no coverage at all. The window creature waits on
  `vars[19] == 1` plus a 20-second chrono; `arm_attic_window_creature` opens
  that first gate and lets the rest run on the real scripts. The stair
  creature arms itself around tick 3600.
- `actors.gere_collision`'s "actor already inside the blocker" case
  (`oldpos == 0`) does **not** zero the whole step the way FITD does
  (main.cpp:3394-3401). FITD's version is a permanent trap, and AITD1's own
  data walks actors into it: an entry track carries a creature in under
  `TL_COL_OFF`, then `TL_COL_ON` re-arms collision wherever `TL_GOTO`'s
  400-unit "close enough" threshold left it. For world 21 that is 382 units
  short of its own target, with its 1062-unit `getZvMax` cube straddling the
  doorway hard-col at z 5000..5300 -- so it animated in the doorway forever
  and never came for the player. `_escape_step` instead keeps each step
  component that does not deepen the overlap. An actor *outside* a box never
  reaches that branch, so walls are exactly as solid as before; only an
  already-penetrating actor is affected.
- Gated by `tests/test_m3b_attic.py`:
  `test_the_attic_window_creature_drops_in_and_comes_for_the_hero` walks the
  window creature's whole chain, and
  `test_the_attic_stair_creature_can_still_walk_once_it_stops_in_the_doorway`
  fails on the old rule with "the creature is frozen at (50, 4882)".

## M3e mouse-reachability boundary

- `tracks.face_toward` is an instantaneous clicked-attack adapter; ordinary
  `_turn_toward` interpolation and its existing callers remain unchanged.
- `interaction.attack_in_hand` validates the target, stops navigation, and
  faces in the hero's room frame. It deliberately chooses no inventory action:
  ENGLISH.PAK text 32 is `Throw`, so delegating to `choose_inventory_action`
  launched the held object at the floor instead of swinging it.
- A target click instead arms a bounded input-local native combat latch.
  `route_play_click` latches the accepted target on `Game` via
  `arm_mouse_attack`; `playworld._apply_mouse_attack` publishes FITD's
  ordinary `local_joyd = 1`, `local_click = 1` and `action = 0x2000` on each
  fixed tick until the melee animation completes, bounded at 100 ticks. The
  simulation never learns that a mouse exists, and every existing focus,
  modal, input-mode and restart seam already clears the latch via
  `clear_mouse_attack` (reached through `controls.snapshot.reset(controls,
  game)`), so no click can resume a swing after a takeover.
- Explicit inventory `Throw` is unchanged and remains reachable only by
  choosing that row; throw setup, flight and floor placement are untouched.
- `game.activate_world_object` is shared by normal active-list regeneration
  and throw release so a released projectile exists before later LIFE reads.
- `scenario.enter_mouse_combat_fixture` owns the deterministic object-38
  automated/manual proof start; the M3c `enter_combat_venue` remains unchanged.
- `app.controls.router.resolve_play_click` is the one HUD/attack/target/walk/steer/blocked
  resolver used by hover, the press, and the per-frame held follow. Its attack
  branch gates on `interaction.can_strike` -- something in hand, hero idle --
  not on the held object's Fight action: equipping leaves the wielded variant
  in hand (the attic lamp's Fight leaves object 2, whose flags carry no
  Fight), and the swing comes from that object's own LIFE, which `play_tick`
  runs every tick.
- `app.controls.router.follow_pointer` runs after the ticks and the scene refresh
  while the left button is held in PLAY, and resolves only on the frames the
  pointer moved off `PointerState.follow_pos` -- a camera cut with a still
  hand therefore changes nothing, where re-resolving would retarget the hero
  onto the new camera's reading of that pixel or stop it outright. It
  re-issues an intent only when the resolution differs from
  `PointerState.follow_last`, which is also the arrival one-shot latch.
  Button-up, focus loss and modal takeover clear both and end the hold; a
  floor change goes through `router.rebase_follow`, which clears both but keeps the
  hold live so the hero walks on off the stairs. Push and attack latches
  suspend it.
- `controls.pointer.press_decision` marks a PLAY press that landed within
  `controls.pointer.DOUBLE_PRESS_TICKS` of the previous one, and that hold runs instead of
  walking: `NavIntent.run` -> `navigate.decide` -> `NavDecision.run` ->
  `tracks._process_track_mouse` speed 5, which the hero's own ANIM_MOVE
  already answers with the run animation. Timed on `game.timer`, so the
  window stops counting while a modal has the game paused. The window is the
  mouse's own, not the keyboard's `tracks.DOUBLE_TAP_TICKS`: a double click
  is one motion of one finger that desktops time at around half a second,
  where a double tap on a held key is a fast repeat. A held push never runs.
  Run adds no `PlayerCapability`: it is a speed, and every destination stays
  reachable at a walk (`mouse_contract` decision `held_double_press_run`). No engine module learns about pointer motion.
- The second press of a double press resumes the first press's destination
  (`shell._resume_destination`, within `DOUBLE_PRESS_RESUME_PX`) rather than
  picking again: one motion of one finger means one place, and a pixel of
  drift under the snap budget could otherwise find nothing at all.
- Walking is possible from every pixel of the world. A pixel that names no
  reachable place -- over a wall, a ceiling, the sky, or a cell nothing
  walkable snaps to -- resolves `steer` rather than `blocked`: the destination
  is `picking.steer_point`, a bearing dressed as a point 12000 units along the
  line from the hero through the pointer, and the engine's own collision
  decides where he stops. `picking._floor_plane_inverse` maps the pixel back
  onto the hero room's floor plane, which is unbounded by any cover polygon; a
  pixel above the horizon recovers *behind* the camera, so the sample walks
  back down the screen ray toward the hero's feet until it lands in front of
  one -- free of accuracy loss, since a projective map takes lines to lines
  and every pixel of that segment recovers a point on the one world ray.
  `NavIntent.steering` makes `navigate._repath` steer straight at it: no path
  (it is on no mesh) and no room-link hop (which would aim the hero back
  through the door he came out of), re-framing the bearing by `room_delta`
  when he crosses a threshold. `STEER_DISTANCE` sits between two bounds: far
  enough not to be reached inside one hold, and inside s16, since
  `give_distance_2d` truncates each axis and a destination past 32767 reads as
  an arrival on the first tick. A steer draws no destination diamond and is
  never stashed for a double press to resume -- both would be about a place,
  and a bearing is not one. An actor with nothing to offer -- no `found_life`,
  not foundable, not a hold-action target -- no longer intercepts the click
  either: a draw-list entry is a screen *rectangle* around the skinned model,
  so refusing there refused the floor around the object too (215 of the
  opening room's sampled pixels, from two pieces of inert scenery), and the
  pixel now falls through to the floor as though the actor were not there.
  What still refuses is a click aimed at a combat actor with an empty hand or
  a hero mid-swing: there the click meant the enemy, not the ground past it.
  `test_no_pixel_of_the_opening_room_refuses_a_click` is the gate, swept
  against the real draw list.
- A press advances the hero on the very next tick, and nothing delays it. A
  double press therefore walks for a few ticks before it runs, which is
  intrinsic: run is decided at press time and a press cannot see the second
  one coming. Holding the hero still until a second press could arrive was
  tried (`RUN_COMMIT_TICKS`, 20a09ac) and reverted -- such a wait has to
  outlast the gap *between* two presses (100-200ms), which is longer than an
  ordinary click is held down (60-120ms), so under hold-bound navigation the
  release cancelled the intent before it ever advanced and a plain click moved
  the hero nowhere at all. Do not reintroduce a press-time wait;
  `tests/test_play_loop.py::test_a_click_of_ordinary_length_walks_before_the_button_comes_up`
  is the guard.
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

- `app/config.py` owns the pygame-free settings schema (v1: bindings for the
  eight key-bindable `Action`s, CANCEL fixed to Escape, sticky flag), the
  platform settings path, and the atomic store. `config.Control` is
  `controls.actions.Action`.
- `app/controls/` owns everything between a pygame event and the engine:
  `actions` (the fixed vocabulary keys, gestures and packs bind to),
  `bindings` (key names to codes), `keyboard` (held bits, sticky pulse, the
  action queue), `pointer` (hold-follow, double-press run, resume and
  camera-cut settling as pure transitions over `PointerState`), `snapshot`
  (`ControlsState` and the one fold into the engine's frozen `PlayInput`),
  `modals` (presenter reducers and hit tests), `router` (mode and modal
  dispatch into engine calls; the menu result appliers and save/load
  requests), `cursor` (what the PLAY cursor shows). It may import
  `engine`, `config` and `ui`; never `shell` or `render`.
- `engine/script/playworld/input.py` owns `PlayInput` (joyd, action_held,
  action_pulse, pointer_held, focused) and the mouse attack latch on `Game`
  (`arm_mouse_attack`/`clear_mouse_attack`); the engine never sees
  `ControlsState`.
- `app/ui.py` owns the modal presenters and results, the layouts, all shell
  drawing (`UIPainter`, `render_*`, `render_cursor`). It never imports
  `controls`.
- `app.ui.UIPainter` is the UI canvas: a surface at `(320*s, 200*s)` plus the
  scale, and the only object that knows `s`. `shell.render_active_mode`
  builds one per frame from `Renderer.ui_scale()` and every presenter and
  overlay paints on it; the loop hands the painter itself to `present()`,
  whose GL path uploads `to_bytes()` (0.7 ms at 1280x800) rather than the
  `to_frame()` numpy round trip (18.6 ms, against a 16.7 ms budget) that
  only the software compositor still needs.
  `screen_surface(resolver, entry, size)` fetches ITD_RESS screens at the
  canvas size, so an override keeps the resolution it came with.
- `app/shell.py` owns the application session (`ModalSession` settings
  fields), the persistence policy boundaries (quick-save commit, the load
  replacement), raw remap capture, the event pump and tick accumulator, the
  atomic game/floor/session/controls replacement, and presentation. It holds
  no key codes and no pointer state (`tests/test_layering.py`).
- `Game` owns no settings; settings never enter world state.
- `tests/test_controls_golden.py` replays a recorded event stream through
  the real pump and pins the per-tick engine input and hero motion; a
  behaviour change in controls shows up there first.

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

## Texture export boundary

- `texture_export.py` and `texture_check.py` are pure like `scene.py`;
  `tools/export_textures.py` and `tools/check_textures.py` do the PNG I/O.
  The export layout is `asset_resolver.texture_background_path`'s and
  `texture_alt_background_path`'s
  (`DIR/backgrounds/floor<NN>/camera<NNN>.png` +
  `DIR/alt_backgrounds/floor<NN>/camera<NNN>.png` (5 KILLED_SORCERER road alts,
  shared `guides/`) + `DIR/palette.png` + `DIR/screens/ressNN.png`) — change
  all or neither. `manifest.json` (schema 4, carrying a `"bodies"` list
  alongside `cameras`/`alt_cameras`/`screens`) merges across `--force` floor
  subsets and is written atomically.
- `screens/ressNN.png` replaces full-screen resources; `app/ui.screen_surface`
  scales them to 320x200 at composite time.
- Regeneration itself lives outside this repo: `make export-textures` writes
  the contract (originals, guides, layout sidecars, manifest) and
  `make check-textures` validates the result exactly the way the game loads
  it. The guide geometry comes from `layout_segments`, so the guide pixels
  and any external gate agree by construction.
- Output dirs `textures/` (and legacy `overrides*/`) are git-ignored; a
  missing texture file — or a missing texture directory entirely — falls back
  silently, a corrupt one warns and falls back. `make run` points at
  `data/aitd1/textures` by default, so that fallback is the normal path on a
  fresh clone.
- Spec/plan for the original in-repo pipeline:
  `docs/superpowers/*/2026-08-25-{ai,gemini}-background-regeneration*`.

## Opening cutscene boundary

- `engine.script.game.start_game(game, stage, room)` is FITD's `startGame`
  (main.cpp:4134) minus `PlayWorld`: resets camera/world targets, loads
  `stage`, calls `change_salle(room)`, stages `new_num_camera=0` /
  `flag_init_view=2`, spawns the stage's actors, and clears `floor_start` —
  a staged start has no restart point until a script sets one. Only
  `_boot_hero`'s cutscene branch calls it. The attic hand-over relies on
  neither `start_game` nor `game_start`'s config alone: `init_game` reads
  `profile.game_start` for its own floor/room instead of hardcoding 0/0
  (`engine/script/game/boot.py`), because running `start_game` on a booted attic leaves
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
  place, no `Action` can exist while `session.cutscene` (nothing ever
  calls `feed_event` to produce one) and no click can reach
  `route_mouse` while `CutsceneFinished` is the active modal (`session.
  cutscene` is still `True` then, so the swallow catches the click first).
  They exist for callers that invoke `route_command`/`route_mouse` directly
  -- tests today, any future caller bypassing the pump -- and are commented
  as such at each site. `PlayerCapability.SKIP_CUTSCENE` documents the
  live route for `GameMode.PLAY` and `GameMode.CUTSCENE_END` in the mouse
  contract; its `GameMode.PLAY` entry is the contract's one
  session-conditional capability (true only while `session.cutscene` --
  ordinary `PLAY` routes the held button to a walk/interact follow instead),
  commented as such in `mouse_contract.py`. `--skip-intro` sets
  `session.skip_intro`, a development-only bypass (not FITD behaviour) that
  boots straight to the attic instead of staging the cutscene at all.
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

## M4a2 persistence boundary

- The snapshot schema is `engine/script/save.py:SCHEMA` (3): root keys `schema`,
  `engine_version`, `source`, `hero`, `game`, `actors`, `world_objects`,
  `anim_players`, `inventory`, `messages`, `rng_state`, `settings`,
  `content_state`. Validation is total before anything live is touched: exact
  key sets, exact counts (actors pinned to `NUM_MAX_OBJECT`; world/var/CVar
  counts re-derived from the three world files), strict `type is int` (bools
  rejected), and the JSON path of the first offending value in every
  `SaveError`.
- The save carries the game's own data identity: one SHA-256 over
  `OBJETS.ITD`, `VARS.ITD`, `DEFINES.ITD`, `LISTLIFE.PAK`, `LISTTRAK.PAK`
  and the selected hero's body/anim paks, in that order, plus `source.pack`
  (the content pack's identity, or none). A save only loads against the data
  it was written from, and only against the same content pack (or its
  absence) it was written with.
- Settings ride through the snapshot as an opaque JSON-ready dict:
  `engine/script/save.py` never imports the app layer, and
  `app/config.validate_settings` alone validates the block at the shell
  boundary (`settings_payload` in `app/config.py` is the one builder shared
  with `save_settings`).
- `Game.rng` owns every gameplay draw (evalVar 0x1C reads it, never the
  module-global `random`); the snapshot stores `getstate()` as JSON lists,
  so a restored game continues the identical stream.
- Slots are `save-manual.json` / `save-quick.json` under `save_dir()`
  (beside the settings file; `--save-dir` overrides). `write_slot` is the
  settings atomic idiom: same-directory temp file, flush + fsync,
  `os.replace`, best-effort cleanup — a failure never touches a prior slot.
- Policy lives in `app/shell.py`: manual save only at a stable system-menu
  boundary (a pending LIFE continuation or platform effect refuses with the
  dismissible runtime notice); Quick Save closes the menu and commits at the
  first stable end-of-PLAY-tick boundary, never mid-tick; a Load click reads
  and validates the slot, stages `session.pending_load`, and `_load_branch`
  rebuilds game/floor/session/input as one replace tuple (the `_hero_branch`
  shape), landing in PLAY with clean pointer/action/navigation state. Every
  failure path leaves the live game, settings, input, floor and modal
  untouched. Unavailable load rows are dimmed inert no-ops, never falling
  through to Back.
- The menu surfaces are `SystemMenuPage.SAVE`/`LOAD` inside the existing
  system menu (`app/ui.py`): MAIN rows Return/Save/Load/Quick
  Save/Configuration/Quit; SAVE rows Manual Slot/Back; LOAD rows Manual
  Slot/Quick Save/Back. `reduce_system_menu`, `render_system_menu` and the
  mouse routes take `available_slots`; the mouse contract names each
  persistence decision a single forgiving `left_click` in `SYSTEM_MENU`.
- Focused gate: `make prove-persistence`; evidence:
  `docs/m4a2-persistence-proof.md` (windowed one-button attestation
  pending).

## Content packs boundary

- A pack (`packs/example`) is TOML: `pack.toml` + `enemies/*.toml`. Records
  compile to `WorldObject`s appended after the 292 OBJETS ones with
  `life = BEHAVIOUR_LIFE (-2)`; `life_gate` admits only `life >= 0`, and the
  tick's LIFE loop runs `content.run_behaviour` for `-2` actors at the same
  slot position. Behaviours call only what opcodes call (`init_deplacement`
  + `process_track`, `init_anim`, `anim_action.arm_strike`, `delete_object`).
- `game.pack`, `game.content` (records by world index) and
  `game.content_state[world_idx] = {"hp", "phase"}` are the whole runtime
  surface; saves (schema 3) carry `source.pack` and `content_state` and
  refuse a mismatch either way. `--content DIR` is CLI-only; a bad pack exits
  2 before any window. `engine/content` imports `script.game`'s leaf modules
  only (`boot.init_game` imports `attach` lazily); `test_layering.py` pins it.
- Real numbers the example pack rests on: body 24's anims stand 22 / walk 23
  / attack 25 / hurt 21 / death 24, `LM_HIT(25, 1, 22, 400, 1, 22)`, a strike
  from ~2000 Manhattan units, follow no closer than ~800.

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
