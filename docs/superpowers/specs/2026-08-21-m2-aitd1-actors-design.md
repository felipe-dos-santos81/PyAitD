# Alone in the Dark 1 — M2: Actors Design

Date: 2026-08-22
Status: Approved (design)
Reference implementation: FITD (`/Users/felipe.dos.santos/code/theirs/FITD`, GPLv2)
Builds on: M1 (data layer + room rendering, merged to main)

## Goal

Render the player character in 3D over the 2D backgrounds: body/anim parsing,
GL skinning, walking with hard-collision, zone-driven camera switching, and
background mask occlusion. Playable via a debug viewer (no game logic — LIFE
VM arrives in M3).

## Non-goals

- LIFE script VM, inventory, combat, other actors (M3)
- Menus, save/load, audio, video (M4)
- Track-based movement (moving platforms/scripted paths) (M3)

## Context discovered (FITD reference)

- Bodies come from `LISTBODY.PAK` (parsed in FITD `hqr.cpp` `createBodyFromPtr`):
  flags, ZV bounds, scratch buffer, s16 vertices, anim groups (hierarchy via
  `orgGroup`, order via `m_groupOrder`), primitives (poly/line/point/sphere,
  vertex indices stored *6). Animations from `LISTANIM.PAK`
  (`createAnimationFromPtr`): frames of timestamp + root step + per-group
  type/delta (+rotateDelta in the optim variant).
- Camera math (`main.cpp` `SetAngleCamera`/`SetPosCamera`/`SetProjection`,
  `renderer.cpp` `transformPoint`): 1024-entry cos table (2pi/1024), fixed
  point 0x10000, rotation order Y→X→Z, `<<1` scaling after each multiply;
  projection `x' = X*fovX/(Z+perspective) + centerX`, same for Y. Camera
  position in room space = (roomWorld - cameraPos)*10 with Y flipped.
- Camera switching (`main.cpp` `GereSwitchCamera`/`findBestCamera`/`isInPoly`):
  actor ZV box (world/10) tested against cover-zone polygons (per camera's
  viewed room) with ray-cast cross products; outside current zone → pick
  camera whose zone contains the actor, minimizing angle between actor beta
  and camera beta+0x200. Camera background/palette loading exists from M1.
- Masks (`main.cpp` `createAITD1Mask`): mask-zone polygons from camera
  viewed-room data rasterized (poly fill) into a 320x200 bitmap; actor pixels
  behind the mask are occluded. AITD1 uses filled polygon masks, not the
  per-line JACK mask format.
- Anim playback (`anim.cpp` `SetAnimObjet`/`GereAnim`/`PatchInterAngle`):
  per-frame group states applied to body; interpolation between keyframes
  (angles and steps) driven by the 50Hz timer.
- Hero actor: FITD sets `bodyNum = 0` for the player (life.cpp). Anim indices
  are assigned by LIFE scripts in M3; M2 picks working LISTANIM indices
  empirically (debug keys cycle animations).
- Collision: hard col boxes (ZV structs, parsed in M1) resolve by pushing the
  actor box out; sce zones type 0 hold linked-room visibility.

## Decisions (agreed with user)

- Actor source: hardcoded debug spawn (player, body 0) at a fixed position in
  floor 0 room 0; debug keys cycle animations. LIFE VM spawns real actors in M3.
- Movement: original tank-style — up/down move forward/back along actor beta,
  left/right rotate. Matches the real anim set and script assumptions.
- Mask occlusion included in M2 (per M1 spec deferral note).
- Renderer: approach A — FITD-exact transform math in numpy, ModernGL
  rasterizes the projected mesh into a 320x200 offscreen actor layer, mask
  composite, upscale through the existing M1 quad path.

## Architecture

Extends the M1 pipeline. New/changed modules:

- `maitd/formats.py` (+ `parse_body`, `parse_anim`): pure parsers producing
  `Body`/`Animation` dataclasses; layout per FITD `hqr.cpp`.
- `maitd/assets.py`: body/anim asset registry — `LISTBODY.PAK`/`LISTANIM.PAK`
  loaded once via the M1 LRU; parse-once cache per index.
- `maitd/anim.py`: per-actor `AnimPlayer` — apply keyframe to group states
  (SetAnimObjet port), advance frames by timestamp at 50Hz, interpolate
  group angles/steps between keyframes (PatchInterAngle/PatchInterStep ports).
- `maitd/world.py`: camera state + math ports (`set_angle_camera`,
  `set_pos_camera`, `set_projection`, `transform_point`, cos table),
  cover-zone parsing (M1 left them as offsets), `is_in_poly`/`find_best_camera`
  ports, hard-col collision resolution.
- `maitd/actors.py`: `Actor` dataclass (position, body/anim indices, frame,
  group states, ZV box), `spawn_player()`, tank movement with collision.
- `maitd/mask.py`: `create_aitd1_mask` port — mask-zone polygons rasterized
  to a 320x200 numpy bitmap.
- `maitd/render.py` (extend): 320x200 actor FBO; projected vertices → VBO;
  GL draw in body primitive order (no depth test, painter's algorithm like
  the original); composite background + masked actor layer; upscale.
- `maitd/__main__.py` (extend): play loop — 50Hz fixed tick (input → move →
  camera switch → anim advance), render on demand; debug keys: arrows walk,
  A/Z cycle animations, R reset position.

Data flow: tick → input → move+resolve → GereSwitchCamera → anim advance →
frame: project (numpy) → GL actor pass → mask → composite → quad.

## Invariants

- All transform math stays fixed-point-identical to FITD (cos table,
  rotation order, `<<1`); golden tests pin known vectors.
- Parsers pure; `world.py`/`actors.py`/`anim.py` never touch disk.
- 50Hz logic tick; render rate independent.
- Renderer draws primitives in file order (original painter's algorithm).
- Errors: out-of-range body/anim index raises with PAK + index context.

## Error handling

- Corrupt body/anim data: ValueError with entry index and byte offset.
- Unknown primitive type: ValueError naming the type (FITD asserts).
- Collision/camera switching operate on validated parsed data; no silent
  failure paths.

## Testing

- Golden tests: parse LISTBODY entry 0 and LISTANIM entry 0..2 — exact
  counts (vertices, groups, primitives, frames) recorded from real data,
  plus invariant checks (indices/6 divisible, group offsets/0x10 divisible).
- Math tests: transform_point/project known vectors against FITD-derived
  expected values (cos table spot values, rotation order effects).
- Collision: box push-out cases (inside, overlapping, corner).
- Camera switching: synthetic zone polygons + actor positions → expected
  camera selection (including angle tie-break).
- Mask: known polygon set → exact 320x200 bitmap (small fixture).
- Proof harness `scripts/prove_m1.py` extended in place (same file, same
  Makefile target): additionally parse every body/anim entry in the game data.
- Visual smoke: floor 0 — actor visible, walks with collision, camera
  switches at zone edges, occluded behind furniture (human-verified).

## Assumptions

- Body 0 is the player model (FITD life.cpp sets it); anim indices chosen
  empirically in M2 (debug cycling), canonical mapping arrives with M3.
- Floor 0 room 0 has valid cover zones for camera switching.
- 50Hz tick matches FITD's game timer.

## Risks

- Group-rotation semantics in the renderer (rotation origin, hierarchy) are
  the trickiest port; mitigated by FITD renderer.cpp being the source of
  truth and by visual smoke tests.
- Anim interpolation edge cases (reversed angles, short keyframes); port
  PatchInterAngle exactly rather than reinventing.
- Mask polygon rasterization must match FITD's fillpoly convention; verify
  against known AITD1 mask polygons visually.
