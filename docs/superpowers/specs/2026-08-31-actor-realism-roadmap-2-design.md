# Actor Realism Roadmap 2 Design: Motion, Textures, Light Transport, Atmosphere

Date: 2026-08-31

Status: Approved design — awaiting implementation plans (one per sub-project)

Builds on: the first actor realism roadmap
(`2026-08-29-actor-realism-roadmap-design.md`), which shipped soft
shadows (F), materials v2 (H) and plate integration (G); smooth actor
geometry (`2026-08-28-smooth-actor-geometry-design.md`) for the
instanced PN tessellation and corner-attribute convention; the enhanced
graphics scene layer (`2026-08-25-enhanced-graphics-scene-layer-design.md`)
for `FrameDescription`, `BodyGeometry`, `CameraView` and `GLBackend`;
and the texture export boundary (`make export-textures` /
`check-textures`) whose external-tool contract sub-project J extends to
actor bodies.

Supersedes: nothing. It adds three fields to `RenderOptions`, one
optional argument to `build_frame`, one optional field to
`BodyGeometry`, two pure modules, one tools script, one system-menu
page, and amends the repository dependency policy.

## Goal

Nothing on screen is wrong; this roadmap makes it more real. Four
things still separate an actor from the room it stands in:

- it moves in 20 ms steps: the simulation ticks at 50 Hz and a 60–120 Hz
  display renders each pose one to three times;
- its surface is palette ramps plus procedural relief — no painted skin,
  cloth weave, wood grain or wear;
- its ambient light ignores what is next to it: nothing darkens a crease
  or the gap between two actors, and its shadow lands only on its own
  ZV floor plane, never on the furniture the room's `hard_cols` stand
  in for;
- the composite blends an actor eight metres away exactly like one at
  arm's length: no distance haze, no depth-graded softness or grain.

| Sub-project | Status |
|---|---|
| I. Motion interpolation (render-frame blending between ticks) | **this spec** |
| J. Actor surface textures (unwrap bake, external paint contract) | **this spec** |
| K. Light transport (SSAO, room shadow receivers) | **this spec** |
| L. Atmosphere (depth-graded composite: haze, softness, grain) | **this spec** |

One spec, four implementation plans, delivered in the order I, J, K, L.
This is a presentation change. No game state, no input handling and no
simulation code is touched. `skel.skin()`, `draw_list`, picking, masks
and the mouse contract are untouched. The software backend is untouched.

## Library strategy (researched 2026-08-31)

The owner's direction for this roadmap is to reuse existing libraries
instead of writing more custom code. Two verified surveys (PyPI
metadata, project docs, GitHub, the repo's own venv: pygame-ce 2.5.8,
moderngl 5.12.0, numpy 2.5.2, CPython 3.12) found:

- **Renderer side: no libraries exist.** There is no packaged
  post-processing, SSAO or shadow-mapping library for a foreign
  moderngl pipeline; moderngl-window is windowing glue with zero effect
  passes, zengl is a rival wrapper at the same abstraction level, and
  every pygame shader/lighting package (pygame-shaders, pygame-render,
  pygame-light2d, PygameShader, BloomEffect) is a 2D-surface tool below
  this engine's level — PygameShader is additionally GPL-3-only with no
  arm64 wheels. The ecosystem norm is per-project fullscreen-quad GLSL,
  which this renderer already ships as an idiom. The one real
  off-the-shelf renderer is pygfx (BSD-2, active, skinning + shadow
  maps + PBR) — but it renders through wgpu/Metal and cannot draw into
  the existing GL context: adopting it is a replatform that discards
  every bespoke pass, the opposite of the goal. panda3d is the same
  trade; raylib's Python binding is EPL-2.0, a GPL-2.0 hazard.
- **Tools side: libraries win.** `xatlas` (MIT, 0.0.11, arm64 cp312
  wheel) unwraps no-UV low-poly meshes in one call and packs atlases;
  `libigl` (MPL-2.0, 2.6.2, arm64 abi3 wheel) bakes embree-backed
  ambient occlusion in one call; `Pillow` (MIT-CMU) composes the guide
  images. All GPL-2.0-compatible, maintained, wheeled for this machine.
- **Runtime needs nothing new for textures**: pygame-ce decodes PNG,
  `moderngl.Texture.build_mipmaps()` builds the mip chain, and
  `Texture.anisotropy` exists.

**The strategy: bake with libraries, render with the existing
pipeline.** Heavy geometry math runs once under `tools/`; the game
loads files.

### Dependency policy amendment

`CONTEXT.md`'s "deps: pygame-ce, moderngl, numpy, pytest — no more"
becomes:

- **Runtime** (`PyAitD/`) stays frozen at pygame-ce + moderngl + numpy.
- **Tools** (`tools/`) may take PyPI dependencies vetted case-by-case:
  GPL-2.0-compatible license, maintained, prebuilt wheels for macOS
  arm64 / CPython 3.12. They live in a `tools` extra in
  `pyproject.toml` (`[project.optional-dependencies]`), and
  `tests/test_layering.py` enforces that `PyAitD/` imports none of
  them.

This roadmap's extra is exactly what its plans import: `xatlas`,
`libigl`, `Pillow`. Vetted-but-deferred candidates, added only if a
plan turns out to need them: `trimesh` (MIT, mesh workbench), `scipy`
(BSD-3, `RotationSpline`/`Slerp`; sub-project I's slerp is ~30 lines of
in-repo numpy instead). Rejected on license: PyMeshLab (GPL-3),
`igl.copyleft.cgal` (GPL-3) and `igl.copyleft.tetgen` (AGPL-3 — never
import either submodule), PygameShader (GPL-3), raylib bindings
(EPL-2.0). `igl.embree` bundles Embree (Apache-2.0): acceptable
tools-side, where only its outputs ship.

## Decisions taken during brainstorming

1. **One roadmap spec, four plans, order I → J → K → L.** I is small
   and pays off immediately; J is the biggest visual jump; K's tuning
   wants textured surfaces under it; L grades the final look, so it
   comes last for the same reason G did.
2. **Bake with libraries, render with the existing pipeline** (above).
   Replatforming on pygfx was considered and rejected.
3. **Every knob's off value runs today's code verbatim**, lands off,
   and flips in its plan's last task — the F/H/G convention. All new
   behaviour lives under `lighting="scene"`; `fixed` stays the whole
   legacy renderer byte for byte.
4. **J's knob is the texture directory itself**, exactly as for
   backgrounds: no body files present means today's renderer verbatim;
   no `RenderOptions` field is added.
5. **Texture content comes from an external tool** through an export
   contract (guides + sidecars + manifest), mirroring the backgrounds
   pipeline; generation stays outside the repo.
6. **The UV sidecar stores per-corner UVs** aligned with the
   `corner_normals` convention, so the runtime never sees xatlas's
   vertex splitting.
7. **SSAO attenuates the fill/hemisphere share only** — key and
   specular are already gated by the shadow map, and F's rule that a
   shadowed limb falls to the room's fill, never to black, extends to
   occlusion.
8. **`hard_cols` become shadow receivers behind a fixture-review
   gate**: they are collision proxies, not painted geometry; vertical
   faces are excluded from the start and the plan chooses receiver
   classes by eye before the default moves.
9. **No depth of field.** The plates are uniformly sharp; L's mild
   depth-graded softness is the whole focus story.
10. **Motion interpolates, never extrapolates**: rendered pose runs up
    to one tick behind the simulation, and snaps rather than smears
    across cuts, teleports and anim restarts.
11. **The Graphics page splits**: display knobs stay on Graphics;
    lighting/realism knobs move to a new Realism page. Twelve knob
    rows plus Back no longer fit one page at legal row heights.
12. **YAGNI on the tools extra**: only xatlas, libigl, Pillow; trimesh
    and scipy documented as vetted candidates, not installed.

## I. Motion interpolation

### Current state

`playworld.TICK_MS = 20`. The shell's outer loop accumulates elapsed
milliseconds, runs the accumulated 50 Hz ticks without rendering, and
draws the resulting state once per outer frame. `AnimPlayer.advance`
already interpolates *within* a keyframe per tick (`patch_inter_angle`
with the ±0x200 shortest-arc wrap on the 0..0x400 circle); nothing
interpolates *between* ticks, so at 120 Hz each pose renders up to
three times.

### Design

Presentation-only, on the `CameraView` precedent: a float twin beside
the authoritative integer path, diverging by bounded amounts, never
consulted by picking, masks, combat or the mouse contract.

- **`render/motion.py`** (pure, pygame/GL-free):
  - `snapshot(game) -> MotionSnapshot`: per-actor (index, body_num,
    room, position incl. steps, angles, group states as floats) plus
    the frame identity (floor id, `game.num_camera`). Called by the
    shell after each tick batch, before the ticks run again.
  - `blend_states(prev, cur, alpha)`: rotation states interpolated
    shortest-arc on the 0..1024 circle in float (the same wrap rule as
    `patch_inter_angle`, continuous); translate/scale states and
    positions lerped.
  - `pose_vertices_float(body, states, actor_angles)`: the float64
    numpy twin of `skel.pose_vertices` — same group order, same
    hierarchy, fractional angles through real `sin`/`cos` instead of
    `COS_TABLE` truncation. At alpha 1 with integer states it agrees
    with the integer pose within the documented truncation bound, the
    way `CameraView.project` agrees with `skel.skin`.
- **`build_frame(game, floor, resolver, blend=None)`**: `blend` is
  `(MotionSnapshot, alpha)` with `alpha = accumulator / TICK_MS` in
  [0, 1). With `blend`, `pose_geometry` receives blended float states
  and positions through the float pose twin; without it (or under
  `motion="tick"`), today's path runs verbatim. The logical `skin()`
  call and `draw_list` always use the current tick's integer states.
- **Snap rules**, per actor, evaluated in `build_frame`: the snapshot's
  frame identity differs (camera cut, floor change), the actor is
  absent from the snapshot (spawn), body_num or room differs, the anim
  restarted, or the position delta exceeds a teleport threshold (one
  constant the plan pins against the fastest legitimate per-tick
  movement) → that actor renders unblended this frame. A camera cut with a still world
  therefore changes nothing.
- **Knob**: `RenderOptions.motion: str ∈ MOTION_MODES = ("tick",
  "smooth")`, mirroring `lighting` exactly: validation, `to_payload`,
  `cycle_motion`, CLI flag `--motion`, a settings key an older file
  falls back on with the usual notice, and a Realism-page row. Lands
  as `tick`; flips to `smooth` in the plan's last task.

## J. Actor surface textures

### Current state

Bodies are flat palette-colored polygons with no UVs and no textures;
`realism=enhanced` gives them procedural relief keyed on rest-pose
position. The texture directory already overrides backgrounds and
screens with silent-missing / warn-corrupt fallback, validated by
`make check-textures` against `manifest.json` (schema 3).

### The bake: `tools/export_actor_uvs.py`

A stage of `make export-textures` (skippable like screens/materials),
using the tools extra:

- For each body any floor references: fan-triangulate the rest pose by
  the same rule as `geometry._triangulate`, `xatlas.parametrize` →
  charts, packed atlas, per-corner UVs.
- **Sidecar** `DIR/bodies/body<NNN>.uv.json`: atlas size and `(M, 3, 2)`
  per-corner UVs aligned with the triangulation order — the runtime
  never sees xatlas's vertex remap. A content hash of the body's
  triangulation rides along so a stale sidecar is detectable.
- **Guide** `DIR/bodies/body<NNN>-guide.png`: charts filled with the
  original palette colors, wireframe overlay, chart gutters, and an
  ambient-occlusion layer from `igl.embree.ambient_occlusion` — what an
  external painter (AI or human) needs to produce
  `DIR/bodies/body<NNN>.png` (albedo, same layout). Charts carry
  gutter padding against mip bleed.
- `manifest.json` schema bumps 3 → 4 with body records; the merge
  across `--force` subsets and atomic write are unchanged.
- `make check-textures` extends to bodies: PNG decodable, size matches
  the manifest, sidecar hash matches the body's current triangulation
  (a re-export invalidates stale paints loudly), UVs in [0, 1].

### Runtime

Zero new dependencies.

- `AssetResolver.body_texture(body_num) -> (uvs, ImageAsset) | None`:
  texture-dir check with the background rule — missing falls back
  silently, corrupt warns and falls back. Memoised per body.
- `BodyGeometry.uv: np.ndarray | None` — `(M, 3, 2)` float32
  per-corner, defaulting to `None` so every positional constructor
  keeps working; `build_frame` fills it through the resolver.
- GL: a per-corner UV attribute beside the corner normals; UVs
  interpolate barycentrically through PN tessellation exactly as
  normals do. The texture uploads once per body (memoised), with
  `build_mipmaps()` and anisotropy.
- `_ACTOR_FSH`: a textured fragment takes albedo from the texture in
  place of the ramp color; the palette-index material table still
  drives specular, rim, bump, sss and emissive — paint changes color,
  not physics. Lines, points and spheres stay untextured.
  `realism=classic` ignores body textures entirely.

## K. Light transport

Both features are custom GLSL in the existing fullscreen-pass idiom;
the survey confirmed nothing packaged exists to reuse. Reference
implementations (LearnOpenGL-class) are source material, not
dependencies.

### K1. SSAO on the actor layer

Per-actor depth clears make painter's order work but leave no shared
depth to sample, so:

- **Depth prepass**: all actors drawn once through the instanced
  tessellation path (camera mvp, no per-actor clears) into a
  half-resolution G-buffer — depth texture plus view-space-normal
  color attachment. Lines, points excluded as in the shadow map.
- **SSAO pass**: hemisphere kernel with per-pixel rotation noise over
  the G-buffer, then one bilateral-ish blur, into an occlusion
  texture.
- **Receiver term**: `_ACTOR_FSH` samples the occlusion texture by
  `gl_FragCoord` and attenuates the fill/hemisphere share only; key
  and specular are already gated by the shadow-map visibility. This
  complements the baked rest-pose vertex AO, which cannot see pose or
  neighbours: creases, armpits, the gap where a monster looms over the
  hero.
- **`render/ssao.py`** (pure): the kernel builder and
  `ssao_reference(depth, normals, kernel) -> occlusion`, the numpy
  twin the GL test pins the shader against, as `soften` pins the blur.
- **Knob**: `RenderOptions.occlusion: str ∈ OCCLUSION_MODES = ("off",
  "ssao")`, mirroring `lighting`; lands `off`, flips to `ssao` in the
  plan's last task.

### K2. Shadows received by the room

`Room.hard_cols` are world-space axis-aligned collision boxes. Under a
new `shadows` value — `SHADOW_MODES` becomes `("hard", "soft",
"room")`, room implying everything soft does:

- A receiver pass rasterises the current room's floor plane and the
  visible top and near-horizontal faces of its `hard_cols`, samples
  the existing light-view shadow map, and darkens the plate through
  the gathered composite (mask-erased as ever), drawn after the
  gathered ground shadow and before any body. The hero's shadow then
  drapes over the crates and tables the boxes stand in for.
- **The risk is named**: hard_cols approximate the painted geometry. A
  shadow on a box 30 units off its furniture looks worse than no
  shadow. Vertical faces are excluded from the start, and the plan
  carries an explicit fixture-review gate where receiver classes
  (floor only / + box tops) are chosen by eye. The `shadows` default
  moves to `room` only if that review passes; otherwise it stays
  `soft` and `room` remains a menu choice.

Resources (K total): the G-buffer textures and FBO, the SSAO and blur
programs and ping-pong target, the receiver-pass program and its
buffers — all released in `release()` and counted by the leak test.

## L. Atmosphere

On "perspective": projection is already true float perspective
(`CameraView`); what is missing is the composite knowing how deep each
actor pixel is.

- **Depth target**: the actor layer gains a second render target
  carrying linear camera depth (MRT), resolved alongside color; at
  `msaa = 0` the structure is identical. Pixels with zero coverage
  carry no depth and every term below is gated by coverage.
- **Distance haze**: the composite shifts actor color toward the
  scene's ambient/plate tone by `1 − exp(−HAZE_DENSITY · max(0, depth −
  HAZE_START))`. In a small room the effect is near zero by
  construction; in the caves and long halls it finally separates far
  actors from near ones. (The first roadmap dropped haze because a
  plate-wide haze read off a picture was guesswork; a depth-driven
  term on actors only is measurable and bounded.)
- **Depth-graded integration**: G's softness sigma and grain gain
  scale mildly upward with depth — far actors go slightly softer and
  grainier, matching how distant content in the pre-rendered plates
  carries less detail than near content.
- **No depth of field** (decision 9).
- **Knob**: `RenderOptions.atmosphere: str ∈ ATMOSPHERE_MODES =
  ("off", "on")`, mirroring `lighting`; applies only under
  `integration > 0` and `lighting="scene"`. Lands `off`, flips on in
  the plan's last task.
- Tunables (`HAZE_DENSITY`, `HAZE_START`, the two depth-grade slopes)
  are settled by eye against the fixtures and recorded in the proof
  document, like G's `TOE`/`SHOULDER`/`GAIN`.

## Options, UI and tooling

### The page split

Twelve knob rows plus Back no longer fit one page at the 13 px hit
floor, so Configuration gains a second sub-page:

- **Graphics** (display): `Scale`, `Shading`, `Filter`, `AA`,
  `Smoothing`, Back — 6 rows.
- **Realism** (new): `Lighting`, `Shadows: Hard / Soft / Room`,
  `Realism`, `Integration`, `Motion: Tick / Smooth`, `Occlusion: Off /
  SSAO`, `Atmosphere: Off / On`, Back — 8 rows.

Both pages return to the 22 px pitch from y=12; every row clears the
13 px hit-target floor. `SystemMenuPage` gains `REALISM`; `cycles`,
`hit_rows`, keyboard and mouse routes follow the existing pattern; the
page split lands in I's option task (the first to need a new row), and
J/K/L add rows to the Realism page. New settings keys follow the usual
older-file-falls-back-with-notice convention. Each new option persists
only from the menu and has a session-only CLI flag.

### Proof tooling

`tools/prove_graphics.py` gains `--motion`, `--occlusion`,
`--atmosphere` (defaults from `RenderOptions`) and per-fixture twins
beside the existing ones: `-tickmotion` (the same frame blended at
alpha 0.5 versus unblended), `-nossao`, `-noroomshadow`, `-nohaze` —
every sub-project gets its before/after pair.

Four proof documents, one per plan: `docs/motion-interpolation-proof.md`,
`docs/actor-textures-proof.md`, `docs/light-transport-proof.md`,
`docs/atmosphere-proof.md` — each with the automated gates as actually
run, one measured frame-time line, and the pending manual attestation
table.

**Budget:** with I, J, K and L all on, the attic fixture at scale 4,
msaa 4, smoothing 2 renders in at most 1.5× the time with all four
off. Each plan measures its own contribution; the gate is on the plan,
not a unit test.

## Task ordering

Four plans. Every intermediate state is shippable: each knob lands off
and flips in its plan's last task.

**I — motion interpolation**

1. `render/motion.py`: `snapshot`, `blend_states`,
   `pose_vertices_float`, with the wrap and parity tests.
2. The `motion` option and the Graphics → Realism page split
   (validation, payload, cycle, CLI, settings key, both pages' rows,
   journey coverage). Default `tick`.
3. Shell snapshot after each tick batch; `build_frame(blend=...)`;
   snap rules. `tick` output unchanged.
4. Default `smooth`; `prove_graphics --motion` and the `-tickmotion`
   twin; `docs/motion-interpolation-proof.md`; `CONTEXT.md`,
   `AGENTS.md`, `README.md`.

**J — actor textures**

1. The `tools` extra in `pyproject.toml` (xatlas, libigl, Pillow);
   `test_layering` learns the runtime-import ban.
2. `tools/export_actor_uvs.py`: triangulation-shared unwrap, per-corner
   sidecar with content hash, AO-layered guide with gutters; the
   export-textures stage flag.
3. Manifest schema 4; `check_textures` body checks.
4. `AssetResolver.body_texture`; `BodyGeometry.uv`; `build_frame`
   wiring; fallback tests.
5. GL: corner UV attribute, memoised texture upload with mipmaps and
   anisotropy, albedo substitution in `_ACTOR_FSH`, tessellation
   interpolation; `classic` identity.
6. `docs/actor-textures-proof.md` (synthetic painted fixture); docs.

**K — light transport**

1. `render/ssao.py` twin and kernel; the `occlusion` option and
   Realism row. Default `off`.
2. The half-resolution depth + view-normal prepass.
3. The SSAO and blur passes pinned against the twin; the fill-share
   attenuation in `_ACTOR_FSH`; default `ssao`.
4. `shadows` gains `room`; the receiver pass over floor + hard_col
   tops; the fixture-review gate decides the default.
5. `docs/light-transport-proof.md`; docs.

**L — atmosphere**

1. The `atmosphere` option and Realism row. Default `off`.
2. The linear-depth MRT through both resolve paths; the composite's
   depth input; the neutral identity.
3. Haze; depth-graded sigma and grain; tunables against the fixtures.
4. Default `on`; `prove_graphics --atmosphere` and the twins;
   `docs/atmosphere-proof.md`; docs.

## Testing

Pure modules first; GL through the `gl_ctx` fixture and the `render`
mark; everything headless.

**Identity net, throughout.** `classic + smoothing 0 + shadows hard +
integration 0 + motion tick + occlusion off + atmosphere off` (and no
body textures present) reproduces `tests/golden/scene_lit_classic.npy`;
the classic-identity test names every new field explicitly once the
defaults flip. `lighting="fixed"` renders byte-identically to today at
every combination of the new options. Each GL feature adds a neutral
identity: `smooth` at alpha 0 with a matching snapshot, a body with no
texture file, `ssao` with an empty G-buffer contribution clamped off,
`room` with no hard_col in view, `atmosphere` with its tunables zeroed
so every term vanishes.

**I.** `blend_states`: alpha 0 is `prev`, alpha 1 is `cur`; the
0/1023 boundary interpolates through the short arc, never the long
way; translate states lerp exactly. `pose_vertices_float` agrees with
the integer pose within a pinned bound across the fixture bodies. Snap
rules: camera cut, spawn, teleport and anim restart each render
unblended. The golden holds under `tick`.

**J.** Sidecar UVs are `(M, 3, 2)` in [0, 1] and the content hash
detects a re-triangulated body; `check_textures` rejects a wrong-size
paint and a stale sidecar with the file's JSON path; the resolver
falls back silently on missing and warns on corrupt; a textured
fixture renders with texture albedo while its material terms still
follow the palette-index table; `classic` ignores the texture; the
tessellated and flat paths sample the same UVs.

**K.** `ssao_reference`: a flat plate occludes nothing; a right-angle
crease occludes its corner; occlusion is in [0, 1]. The GL pass
matches the twin within 1/255; a second actor beside the first darkens
the gap; the fill share attenuates while key and spec follow the
shadow map alone. `room`: a caster over a hard_col top darkens it
through the shadow map; a mask erases the receiver pass; `soft` output
is untouched by the receiver code. Leak counts rise by the listed
resources.

**L.** With `atmosphere="on"` and neutral tunables the golden holds at
`msaa = 0`; a far actor's color moves toward the ambient tone while a
near one is untouched; softness and grain measurably increase with
depth; zero-coverage pixels are untouched; both resolve paths carry
depth; leak counts.

**UI, options, shell.** All three new options validate, clamp unknown
values to defaults, cycle, survive the settings round-trip and the CLI
override, and persist only from the menu; both pages show their rows
unclipped with every row cycling by keyboard and mouse; the journey
test reaches the Realism page and both new K/L rows; `shadows`
round-trips its third value against a v-older settings file.

## Limitations

- **Interpolation, not extrapolation**: `smooth` renders up to one
  tick (20 ms) behind the simulation. Nothing the mouse contract
  measures changes — picking still reads the tick pose.
- **SSAO is half-resolution**: thin limbs can halo; the bilateral blur
  bounds it, the proof shows it.
- **hard_cols are proxies**: the fixture-review gate exists because a
  misplaced receiver looks worse than none; vertical faces are out
  from the start.
- **Haze and depth grades are tuned by eye** against the fixtures,
  like G's constants.
- **Chart seams**: mip bleed across chart boundaries is bounded by the
  bake's gutters, not eliminated.
- **The paint step is external**: J ships the contract and a synthetic
  fixture; real painted textures arrive through the texture directory
  like background overrides, and their quality is the painter's.
- **Cost**: I adds a float pose per actor per frame; K adds a prepass,
  two SSAO passes and a receiver pass; L adds one resolve and composite
  arithmetic. `tick`, no-files, `off`, `soft` and `off` are the escape
  hatches, all on the menu or in the texture directory.
- **Software backend** stays flat, unlit, untextured, tick-stepped and
  uncomposited.

## Out of scope

- Smooth skinning weights. The researched path is a tools-side
  `igl.bbw`/`igl.harmonic` bake (seeded from the existing one-bone
  binding, solved on the triangle surface — never `igl.copyleft.*`)
  plus a small matrix-palette LBS vertex shader. It is the natural
  next sub-project after this roadmap and is deliberately not in it.
- Replatforming the renderer (pygfx/panda3d/raylib) — rejected above.
- scipy or trimesh at runtime; any new runtime dependency at all.
- Bloom, HDR tonemapping, TAA, plate reflections, image-based
  lighting, authored per-camera light or depth data.
- Any change to `skel.skin()`, `draw_list`, picking, masks, combat,
  input, simulation timing, or the animation data itself.
- Anything in the software backend.
