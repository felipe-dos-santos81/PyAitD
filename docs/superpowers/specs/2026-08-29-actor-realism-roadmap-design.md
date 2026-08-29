# Actor Realism Roadmap Design: Shadows v2, Materials v2, Plate Integration

Date: 2026-08-29

Status: Approved design — awaiting implementation plans (one per sub-project)

Builds on: smooth actor geometry
(`2026-08-28-smooth-actor-geometry-design.md`), which gave every actor a
GPU-tessellated surface, crease-aware corner normals, the instanced
`_TESS_VSH` path and the Graphics sub-page; actor surface response and
materials (`2026-08-28-actor-surface-and-materials-design.md`) for the
material table, the realism presets and the material terms in
`_ACTOR_FSH`; actor lighting and shadows
(`2026-08-27-actor-lighting-and-shadows-design.md`) for the per-camera
`SceneLight`, the ground shadow pass and MSAA; and the enhanced graphics
scene layer (`2026-08-25-enhanced-graphics-scene-layer-design.md`) for
`FrameDescription`, `BodyGeometry` and `GLBackend`.

Supersedes: nothing. It adds two fields to `RenderOptions`, one field to
`FrameDescription`, three fields to `Material`, one pure module, one
strings-only module, three GL passes and one system-menu row pair.

## Goal

Finish the decomposition the smooth-geometry spec set out. Three things
still make an actor read as a model pasted over a picture of a room:

- its shadow is a hard-edged, uniformly dark cut-out — sharp at the head
  where a real shadow is softest — and no part of the body ever shadows
  another part, or another actor;
- its surface grain is a colour multiply, so detail reads as dirt and
  streaks rather than as lit relief, and the material table it keys on is
  an unreviewed model answer (the hero's face is labelled `hair`);
- it is MSAA-crisp and clean-coloured over a bilinear-blurred, dithered
  320×200 plate, with blacks darker and whites brighter than anything in
  the room.

| Sub-project | Status |
|---|---|
| E. Smooth geometry (crease-aware normals, GPU tessellation) | shipped |
| F. Shadows v2 (contact-hardening penumbra, one gathered pass, self-shadowing) | **this spec** |
| G. Plate integration (edge softness, tone, grain matched to the plate) | **this spec** |
| H. Materials v2 (bump-lit detail, sss, emissive, reviewed table) | **this spec** |

This is one spec and three implementation plans, delivered in the order
F, H, G. It is a presentation change. No game state, no input handling and
no simulation code is touched. `skel.skin()`, `draw_list`, picking, masks
and the mouse contract are untouched.

## Current state

Measured on the shipped data and the `docs/graphics-proof` fixtures at the
current defaults (`smooth`, `scene`, `enhanced`, smoothing 2, msaa 4):

- The ground shadow is `_rasterize_shadow_tessellated` → `_composite_shadow`
  per actor, inside the per-actor loop: a binary coverage texture,
  thresholded at 0.5, multiplied onto the target before that actor is
  drawn. The composite is a full-target quad with no depth, so a nearer
  actor's shadow darkens any farther actor already drawn.
  `tests/golden/scene_lit_classic.npy` is a two-actor scene whose sphere
  shadow lands on its triangle: the golden bakes that ordering in.
- Nothing shadows a surface. The key term `key_tint · wrapped²` is applied
  to every fragment the light faces, whatever lies between it and the
  light.
- `_ACTOR_FSH`'s `grain` multiplies `base` by `1 + detail · noise(v_rest /
  scale)`. Palette ramp 15–31 is a peach ramp used by about seventy bodies,
  the hero included; the survey's heuristic called it `skin` (0.7) and the
  vision pass overrode it to `hair` on the strength of one moustache, so
  the hero's face carries streak noise at scale 8. No ramp in the shipped
  table is `glass`; ramp 14 is labelled `emissive` and the shader has no
  emissive term.
- Actors and the plate share one target. The plate is bilinear-upscaled
  (or xbr, or nearest) from 320×200 and carries the original dither; the
  actor layer is rendered at `320·scale × 200·scale` with 4× MSAA. Nothing
  relates the two: the actor's darkest pixel can be black in a room whose
  darkest pixel is (30, 20, 20).
- `_draw_frame` builds each actor's instance buffer inside the loop and
  releases it after the actor's draw. `refine.subpatch(0)` exists (the
  flat triangle, corners exact) and the backend never requests it.
- `render_gl.py` is 1151 lines, about 250 of them GLSL.
- The Graphics page holds seven rows plus Back at a 22 px pitch from y=12
  (`pygame.Rect(16, 12 + i * 22, 288, 20)`), ending at y=186. Rows may not
  shrink below 13 px (the 12×12 hit-target contract).
- The estimator (`lighting.estimate_light`) already reads per-camera
  colour off the plate: `key`, `ambient`, `contrast`, direction. The
  resolver memoises it per (floor, camera, variant).

## Decisions taken during brainstorming

1. **One roadmap spec, three plans, order F → H → G.** Pipeline order:
   light, then surface, then compositing. G's tuning depends on what the
   final surface and shadow look like, so it comes last; H's retune
   depends on the shadow term being final, so F comes first.
2. **Layered, incremental** over a restructure-first foundation: each
   sub-project hangs on the existing per-actor loop and adds exactly one
   knob whose off value runs today's code verbatim, the way `smoothing=0`,
   `realism=classic` and `lighting=fixed` do. `_draw_frame` is reorganised
   twice (F, then G); that is the price of shipping something visible at
   every step.
3. **Two knobs, not one.** `shadows ∈ ("hard", "soft")` and
   `integration ∈ ("off", "on")`. H has no knob: it redefines what
   `realism=enhanced` means and `classic` stays all-zero.
4. **The gathered shadow pass is gated behind `soft`**, although it is a
   bug fix, because the golden encodes the bug. `hard` is today's
   per-actor composite, ordering artefact included.
5. **All three sub-projects live under `lighting="scene"`.** `fixed` is
   the whole legacy renderer, byte for byte, at every other setting.
6. **Self-shadowing through one light-view depth map per frame** over
   every actor, rather than one map per actor: the same pass gives
   inter-actor shadows, and the actors already share one light.
7. **The ground penumbra comes from the projected silhouette plus a
   height-driven blur**, not from the shadow map: the receiving plane is
   each actor's own `zv` floor, not shared geometry, and the projected
   pass already exists and is tested.
8. **Detail is bump-lit through screen-space derivatives** (Mikkelsen's
   unparametrized bump), which needs no tangents or UVs — the bodies have
   neither. Anisotropic specular and plate reflections are dropped: the
   first needs a tangent field, the second treats a picture as an
   environment and slides at every camera cut.
9. **The material table gets a human pass** over the 23 ramps any body
   uses, with the face and the glass as known corrections going in.
10. **Plate softness is computed, not measured** — it is a function of
    the filter and the size ratio the backend already knows — while
    black, white and grain are measured off the plate like the light is.
    Under `nearest` the actor layer is pixelated to the plate's grid.
11. **Depth haze is dropped.** Rooms are small, the plate carries its own
    depth cues, and a per-room haze read off a picture is guesswork.
12. **The GLSL strings move to `render/glsl.py`** in F's first task, so
    `render_gl.py` stays about the pipeline.

## The pipeline

`GLBackend._draw_frame` at the end of the roadmap, every knob on, under
`lighting="scene"`:

1. Background → the plate (unchanged).
2. Instance buffers for every actor in the frame, built up front and kept
   for the frame. Level 0 is a legal instance draw: `subpatch(0)` is the
   flat triangle with exact corners, so the PN evaluation reproduces the
   flat mesh and every shadow pass has one geometry path whatever
   `smoothing` says.
3. **F.** One light-view depth map over all instances. Then the gathered
   ground shadow: per actor in painter's order, rasterise its masks and
   cast its silhouette (mask discard in the cast) into one two-channel
   coverage texture; blur by the per-pixel penumbra radius; multiply onto
   the plate once, before any body is drawn.
4. Actors as today — painter's order, per-actor depth clear, per-actor
   masks — with the fragment shader gaining a shadow-map visibility term
   (F) and bump, sss and emissive terms (H).
5. **G.** The actors went into their own RGBA layer rather than the
   plate; one composite pass blends that layer over the plate with
   plate-matched softness or pixelation, a tonal toe and shoulder, and
   static grain.
6. MSAA resolve → `.texture`. `render.py`, `read_rgb` and `thumbnail`
   are unchanged.

Under `shadows="hard"` steps 3's passes and 4's visibility term are
skipped and the per-actor composite runs verbatim; under
`integration="off"` step 5 collapses to today's single target. Under
`smoothing=0` the actor draw of step 4 still uses the legacy
`_triangle_data` path when `shadows="hard"`, which is what keeps the
golden byte-identical.

`draw()`'s restore postcondition grows by `blend_equation` (reset to
`FUNC_ADD`): the cast pass blends with `MAX`.

## F. Shadows v2

### Penumbra that hardens at contact

The cast program is `_TESS_VSH` in `project` mode with a new fragment
shader, `_SHADOW_CAST_FSH`, that writes two channels into an RG coverage
texture (`_shadow_tex` changes from one channel to two; same object
count):

- R: coverage, 1.0.
- G: the penumbra radius in target pixels, normalised by `R_MAX`.

`_TESS_VSH` computes the radius and passes it as a varying: the caster's
height above its plane is `drop = plane_y − pos.y` (world units, before
projection); a light source of angular radius `SOURCE_ANGLE` throws a
penumbra `w = drop · tan(SOURCE_ANGLE)` wide at the receiver; the shader
projects both the projected point and the point offset by `w` along the
camera's world x axis (a new `uniform vec3 right`, `rotation_matrix(state).T`'s
first column) through `mvp` and takes the screen distance. `SOURCE_ANGLE`
is one tunable, initially 6° — an indoor lamp a few metres away; the sun
would be 0.25°. `R_MAX = 6 · scale` pixels.

Where two casters overlap the blend equation is `MAX` on both channels, so
overlapping shadows darken a pixel once and take the softer radius.

The blur is two passes of one program (`_SHADOW_BLUR_FSH`, horizontal then
vertical through a ping-pong RG texture): each output pixel gathers over
`d ∈ [−R_MAX, R_MAX]` along the axis and takes, from every sample `j`
whose own radius reaches it (`|d| ≤ r_j`), `coverage_j / (2·r_j + 1)`,
carrying `max(r_j)` forward so the second pass knows the reach. That is
each coverage pixel scattered over a box of *its own* radius, written as a
gather: a foot on the plane (`drop = 0`) stays one pixel sharp, the head's
shadow spreads. `lighting.soften(coverage, radius, r_max) -> coverage` is
the numpy twin of the two passes; the GL test pins the shader against it
as `refine.evaluate` pins the tessellator.

`_SHADOW_FSH` under `soft` multiplies fractional coverage —
`mix(1, shadow_color, opacity · coverage)` — instead of discarding below
0.5; under `hard` the threshold stays.

### One gathered pass

Under `soft`, the shadow work leaves the per-actor loop:

```
for actor in frame.actors (painter's order):
    rasterise actor's masks        # into _mask_tex, as today
    cast actor's silhouette        # _SHADOW_CAST_FSH discards under _mask_tex
blur                               # two passes
composite once onto the plate      # _SHADOW_FSH, no mask sampling: already erased
for actor in frame.actors:
    rasterise actor's masks        # again; polygons are cheap
    clear depth, draw body
```

The mask discard moves from the composite into the cast, so the coverage
texture is already erased where a foreground pillar stands. A nearer
actor's shadow can no longer paint over a farther body, and the
`_composite_shadow` docstring's "true fix" paragraph is retired with the
per-actor composite under `soft`.

### Self- and inter-actor shadowing

One orthographic depth map per frame from the light, over every actor.

- `lighting.light_view_matrix(travel, boxes) -> (4,4) float32`: pure
  numpy. `travel` is the world-space, MIN_UP-clamped light travel the
  ground shadow already computes; the basis is `forward = travel`, `up`
  the world vertical made perpendicular to it (or world x when the two
  are parallel), `right = cross`. `boxes` is every actor's `zv` as its
  eight world corners, `position` added; the orthographic bounds are
  their extent in light space plus a one-texel margin (extent / 2048) on
  every side. A single actor still yields a valid, non-degenerate matrix.
- The map: `ctx.depth_texture((2048, 2048))` with `compare_func = "<="`
  and linear filtering (hardware 2×2 PCF), in its own FBO with no colour
  attachment. Rendered with the existing `_tess_shadow_prog` — `project =
  0`, `mvp = light_vp` — over all instances at the current smoothing level,
  spheres included, lines and points excluded as today. No culling: FITD
  winding is not consistent, so both faces write.
- Receiver: both `_ACTOR_VSH` and `_TESS_VSH` emit
  `v_shadow = light_vp · vec4(pos + n_world · NORMAL_OFFSET, 1)` (the
  world normal is what the vertex shader has before `rot`). `_ACTOR_FSH`
  under `soft` reads `vis = textureProj(shadow_map, v_shadow)` averaged
  over four `textureProjOffset` taps, with a slope-scaled bias in the
  comparison, and applies it to the key's share only:

  ```
  vec3 base = v_color * (fill_tint + key_tint * wrapped * wrapped * vis);
  spec *= vis;
  ```

  Fill and rim are untouched, so a shadowed limb falls to the room's fill
  colour, never to black. Under `hard` a `uniform int self_shadow` is 0
  and the branch skips the fetch entirely, so `base` is today's exact
  expression.
- `_SCREEN_VSH` (lines and points) emits `v_shadow = vec4(0)` and those
  fragments never reach the term (`shading == 0` returns first).

Every actor is in the map, so a monster's arm shadows the hero's chest
with the same term. Texel size is the frame's actor extent over 2048: a
few world units per texel in the attic, tens in the widest caves.

### Options

`RenderOptions.shadows: str ∈ SHADOW_MODES = ("hard", "soft")`, mirroring
`lighting` exactly: clamping in `validate_render_options`, `to_payload`,
`cycle_shadows`, a Graphics row, `shell._MENU_RENDER_FIELDS`, a
`--shadows {hard,soft}` session-only flag, a settings-v2 key an older file
falls back on with the usual notice. Lands as `hard`; flips to `soft` in
F's last task. Under `lighting="fixed"` there are no shadows at all, as
today.

### Resources

New at construction, released in `release()`, counted by the leak test:
the level-0 subpatch buffer; the blur ping-pong RG texture and its FBO;
the cast program (`_TESS_VSH` + `_SHADOW_CAST_FSH`); the blur program
(`_STENCIL_VSH` + `_SHADOW_BLUR_FSH`) and its full-target VAO over the
existing `_shadow_quad`; the shadow-map depth texture and its FBO. No new
program for the map. The plan pins the exact count.

## H. Materials v2

### Relief instead of dirt

`detail_noise(v_rest / scale, kind)` becomes a height field `h`, and the
normal is perturbed by its screen-space gradient — Mikkelsen's
unparametrized bump, which needs no tangent frame:

```
vec3 sx = dFdx(v_view), sy = dFdy(v_view);      // camera-space position derivatives
vec3 r1 = cross(sy, n), r2 = cross(n, sx);
float det = dot(sx, r1);
vec2 dh = vec2(dFdx(h), dFdy(h));
vec3 grad = sign(det) * (dh.x * r1 + dh.y * r2);
vec3 fw = fwidth(v_rest / scale);
float fade = 1.0 - smoothstep(0.25, 0.5, max(fw.x, max(fw.y, fw.z)));
n = normalize(abs(det) * n - preset_c.x * m2.x * fade * grad);
```

`v_view` is a new varying from a new `uniform mat4 view` — the `rotate ·
translate` half of `camera_matrix` — emitted by both vertex shaders
(`_SCREEN_VSH` emits zero). `fade` takes `bump` to zero as a noise cell
approaches half a pixel, so a hero walking away does not shimmer; at that
distance the relief is below the pixel anyway. The perturbed normal feeds
`wrapped`, `hemi`, `spec` and `rim`, so grain catches the key and shades
itself. The colour multiply survives as albedo variation at a fraction of
its strength: wood keeps a tonal streak, skin gets none.

`lambert` shading derives `n` from `gl_FragCoord` derivatives and is
perturbed the same way.

### Fields and terms

`Material` gains `bump`, `sss` and `emissive`, each 0..1; `PARAMETER_COUNT`
becomes 12 and the material texture 256×3 (row 2: `bump, sss, emissive,
0`). `RealismPreset` gains `bump`, `sss`, `emissive`, uploaded as
`preset_c`; `classic` is all zeros, so every new term collapses to
exactly 1.0 or 0.0 by the same construction as before.

- **Skin.** Today's Half-Lambert is already a fully wrapped diffuse, so
  skin gets no extra wrap; it gets a warm terminator:
  `base *= mix(vec3(1.0), SSS_TINT, preset_c.y * m2.y * 4.0 * wrapped *
  (1.0 - wrapped))`, peaking at the light/shade boundary and vanishing on
  the fully lit and fully unlit sides. `SSS_TINT` is one constant,
  initially (1.0, 0.82, 0.74).
- **Emissive.** `f_color.rgb = mix(shaded, v_color, preset_c.z * m2.z)`,
  so ramp 14 renders its palette colour whatever the light does.
- **Specular normalisation.** Blinn-Phong gains `(gloss + 8) / (8π)`, so
  a low-roughness metal gets the tight, bright highlight it is missing
  instead of a faint one. Written as a multiplier on the existing `spec`
  term, which `preset_a.x` already zeroes under `classic`.

### The human pass over the table

The shipped `materials.json` is an unreviewed model answer. One task,
which needs your eyes: for each of the 23 ramps any body uses, look at
the survey's existing `sheets/ramp<lo>-<hi>.png` (the ramp's triangles
tinted magenta on the bodies that use it) and set `label` in
`data/aitd1/materials-survey/survey.json` where the vision answer is
wrong. Known going in: ramp 15–31 → `skin`; the attic window panes and
the lantern chimney → `glass`; ramp 14 confirmed `emissive`. Then `make
bootstrap-materials` re-emits — hand labels carry forward through the
survey stage — and `tools/bootstrap_materials.py --check` pins the
committed table. A ramp that is skin on one body and wood on another
stays wrong on one of them until a per-body override under
`bodies/body<NNN>.json` says otherwise; the survey's usage report shows
where that happens.

### Retune

`CLASS_PRESETS` and `PRESETS["enhanced"]` are retuned against the
graphics-proof fixtures once bump exists. Criteria: skin reads smooth with
a soft highlight and a warm terminator; cloth's weave is relief, not
stripes; wood is streaked; metal is brushed with a real highlight; glass
is rimmed and glossy; nothing shimmers when the hero walks away at scale
4. Tuning is done by eye and recorded in the proof document.

### Dropped

Anisotropic specular (hair, brushed metal) needs a tangent field; the
bodies carry none and a gravity-projected substitute is wrong on every
surface that is not hair. Plate reflections for metal and glass treat a
picture as an environment and slide at every camera cut. Neither is worth
its cost at this scale.

## G. Plate integration

### The plate profile: `PyAitD/render/plate.py`

Pure numpy: no pygame, no GL, no engine imports.

```
@dataclass(frozen=True)
class PlateProfile:
    black: tuple     # 0..1 linear RGB: the room's floor
    white: tuple     # 0..1 linear RGB: the room's ceiling
    grain: float     # 0..1: RMS luma residual of the plate against its own 3x3 mean

NEUTRAL_PLATE = PlateProfile((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), 0.0)

def estimate_plate(pixels) -> PlateProfile
def softness(background_filter, src_size, target_size) -> (sigma_px: float, cell_px: float, pixelate: bool)
```

`estimate_plate`: `black` and `white` are the mean colours of the darkest
and brightest 1% of pixels by luma (the same argpartition selection
`estimate_light` uses; one plate, two quantities each). `grain` is the RMS
of the luma residual against a 3×3 box mean at the plate's own resolution
— the amplitude of its dither — clipped to 0..1. Deterministic, total: an
all-black plate yields black white and zero grain; a uniform plate yields
zero grain.

`softness`: `cell = target_w / src_w`. `bilinear` → `sigma = 0.35 · cell`;
`xbr` → `0.15 · cell`; `nearest` → `sigma = 0` and `pixelate = True`.
When `cell ≤ 1` — an override plate at or above target resolution —
`sigma = 0` and `pixelate = False`: there is nothing to match. The two
constants are tunables the plan settles against the fixtures.

`AssetResolver.plate(floor, cam_idx, *, killed_sorcerer=False)` memoises
`estimate_plate` on whatever `background()` resolves to, keyed like
`light`. `FrameDescription.plate: PlateProfile = NEUTRAL_PLATE`, filled by
`build_frame`; the default keeps positional test constructors working and
makes a frame without a resolver composite as an identity.

### The actor layer

Under `integration="on"`:

1. Background and the gathered shadow render into the scratch target
   (`_target`: the multisample FBO when `msaa > 0`, else `_plate_fbo`
   directly) and are resolved into `_plate_tex`.
2. The scratch target is cleared to (0, 0, 0, 0); actors draw exactly as
   before — painter's order, per-actor depth clear, per-actor masks — and
   are resolved into `_actor_tex`.
3. The composite writes `self.texture` through `_fbo`.

The actor shader writes alpha 1, so the multisample resolve of covered
and uncovered samples yields premultiplied colour with coverage alpha —
what "over" wants — and at `msaa = 0` alpha is 0 or 1, so
`plate · (1 − a) + rgb` is byte-exact against today's direct draw. Under
`off` the current single-target path runs untouched.

### The composite

`_COMPOSITE_FSH`, one full-target pass, per pixel:

1. **Soften or pixelate.** The actor layer is sampled through a Gaussian
   of `sigma_px` on premultiplied RGBA (a single pass, at most 9×9 taps
   at scale 8), or, when pixelating, fetched once at the centre of the
   plate cell the pixel falls in, so a blocky plate gets blocky actors.
2. **Tone.** Unpremultiply, then a toe and a shoulder toward the plate:
   `c += black · (1 − luma)⁴ · TOE` lifts the actor's darks to the room's
   floor; `c −= (1 − white) · luma⁴ · SHOULDER` pulls its brights to the
   room's ceiling. Both vanish for `NEUTRAL_PLATE`.
3. **Grain.** `c += grain · (hash(floor(gl_FragCoord.xy / cell)) − 0.5) ·
   GAIN`, hashed on the screen cell alone so it sits still like the
   plate's dither rather than flickering. Zero where `a = 0`.
4. `out = plate · (1 − a) + c · a`.

The three constants (`TOE`, `SHOULDER`, `GAIN`) are tunables settled
against the fixtures.

### Options

`RenderOptions.integration: str ∈ INTEGRATION_MODES = ("off", "on")`,
mirroring `lighting` exactly, as `shadows` does. Lands as `off`; flips to
`on` in G's last task. Applies under `lighting="scene"` only.

### Resources

`_plate_tex` and `_plate_fbo`, `_actor_tex` and `_actor_fbo` (the latter
with the existing `_depth` renderbuffer attached, for the `msaa = 0`
case), the composite program and its full-target VAO. The plan pins the
leak count.

## Options, UI and tooling

### The Graphics page

Nine rows plus Back: `Scale`, `Shading`, `Filter`, `Lighting`, `Shadows:
Hard / Soft`, `AA`, `Realism`, `Smoothing`, `Integration: Off / On`. The
pitch drops from 22 to 18 px with rows 18 px tall
(`pygame.Rect(16, 12 + i * 18, 288, 18)`), ending at y=192; rows stay
above the 13 px floor so `effective_rects`' 12×12 target contract holds.
`GRAPHICS_ROWS` becomes 9, `cycles` gains `cycle_shadows` and
`cycle_integration` in row order, hit rows follow through
`SystemMenuLayout.hit_rows`, and the existing journey test that reaches
the page covers the two new rows.

### Proof tooling

`tools/prove_graphics.py` gains `--shadows` and `--integration` (defaults
from `RenderOptions`), renders the twelve fixture × shading × realism
files at those values, and writes two more twins per fixture beside
`-flatmesh`: `<fixture>-smooth-enhanced-hardshadow.png` (`shadows=hard`)
and `<fixture>-smooth-enhanced-nocomposite.png` (`integration=off`), so
every sub-project has its before/after pair.

Three proof documents, one per plan — `docs/soft-shadows-proof.md`,
`docs/materials-v2-proof.md`, `docs/plate-integration-proof.md` — each
with the automated gates as actually run, one measured frame-time line
(attic fixture, scale 4, msaa 4, smoothing 2: the feature on versus off),
and the pending manual attestation table.

**Budget:** with F, H and G all on, the attic frame at those settings
renders in at most 1.5× the time it takes with all three off. Each plan
measures it; the proof records it. It is a gate on the plan, not a unit
test.

## Task ordering

Three plans. Every intermediate state is shippable: each knob lands off
and flips in its plan's last task; H's terms land at zero strength.

**F — soft shadows**

1. Move every GLSL string to `render/glsl.py` (strings only; no imports).
   No behaviour change; `test_layering` learns the module.
2. `shadows` option: `SHADOW_MODES`, validation, payload, `cycle_shadows`,
   CLI flag, settings key, `_MENU_RENDER_FIELDS`, the Graphics row at the
   18 px pitch. Default `hard`.
3. `lighting.light_view_matrix`, `lighting.soften`, the level-0 subpatch
   buffer, instance buffers for every actor built up front and released
   at frame end. `hard` output unchanged.
4. Under `soft`: the cast program with penumbra radius, `MAX` blending,
   the two-pass blur pinned against `soften`, the gathered pass, the
   fractional composite, `draw()`'s `blend_equation` restore.
5. The shadow map and the receiver term in `_ACTOR_FSH`.
6. Default `soft`; `prove_graphics --shadows` and the `-hardshadow` twin;
   `docs/soft-shadows-proof.md`; `CONTEXT.md`, `AGENTS.md`, `README.md`.

**H — materials v2**

1. `Material.bump/sss/emissive`, `PARAMETER_COUNT = 12`, the 256×3
   texture, `preset_c`, the `view` uniform and `v_view` varying — all at
   zero strength; the golden holds.
2. Bump with the distance fade.
3. The sss terminator, the emissive mix, the specular normalisation.
4. The human review of the 23 used ramps, re-emit, `--check`.
5. Retune `CLASS_PRESETS` and `enhanced`; `docs/materials-v2-proof.md`;
   docs.

**G — plate integration**

1. `plate.py`: `PlateProfile`, `estimate_plate`, `softness`;
   `AssetResolver.plate`; `FrameDescription.plate`; `build_frame` wiring.
2. `integration` option, mirroring task F2; the Graphics row. Default
   `off`.
3. The actor layer and a composite that is `plate · (1 − a) + rgb` with
   the neutral profile — the plumbing identity, pinned against the golden
   at `msaa = 0`.
4. Soften and pixelate.
5. Tone and grain.
6. Default `on`; `prove_graphics --integration` and the `-nocomposite`
   twin; `docs/plate-integration-proof.md`; docs.

## Testing

Pure modules first; GL through the `gl_ctx` fixture and the `render`
mark; everything headless.

**Identity net, throughout.** `classic + smoothing 0 + shadows hard +
integration off` reproduces `tests/golden/scene_lit_classic.npy`
(`test_classic_realism_matches_the_pre_materials_golden` names the two
new fields explicitly once the defaults flip). `lighting="fixed"` renders
byte-identically to today at every combination of the new options. F and
G each add a second identity: the feature *on* with neutral inputs
reproduces the same golden at `msaa = 0` — `soft` with no occluder in
the map and casters that do not overlap a body, `on` with
`NEUTRAL_PLATE` and `cell ≤ 1`. H has no golden for `enhanced` to hold
(the retune moves it by design), so its plumbing identity is transitional:
H's task 1 captures the attic fixture under `enhanced` before its change,
asserts it unchanged after, and task 2 retires that check when bump lands.

**F**

- `light_view_matrix`: every box corner lands inside NDC; a point further
  along `travel` maps to greater depth; a single box and a box with zero
  extent on one axis still give a finite, invertible matrix; `travel`
  parallel to the world vertical picks the fallback `up`.
- `soften`: radius 0 is the identity; one pixel of radius `r` spreads to a
  `(2r + 1)²` box whose sum is the original coverage; two casters combine
  by `MAX`, never additively; the carried radius is the max of the
  contributors.
- GL: `hard` reproduces the golden; under `soft` a caster lying on its
  plane produces a one-pixel edge and a caster held 1000 units above it a
  wider one; the golden's own sphere-over-triangle scene *no longer*
  darkens the triangle under `soft`; two overlapping casters darken a
  pixel once; a foreground mask erases a cast; an occluding triangle held
  between the light and a facing triangle darkens the second's key share
  and leaves its fill share alone, and removing the occluder restores the
  neutral identity; `fixed` is untouched; the blur output matches
  `soften` within 1/255; the leak count rises by the listed resources.

**H**

- `materials.py`: the three fields validate 0..1; `parameters()` is
  (256, 12) float32 within range; `PRESETS["classic"]` is all zeros
  including `preset_c`; a table round-trips.
- GL: the golden holds; two facing triangles that differ only in `rest`
  shade differently per pixel *and* agree in mean luminance within 1%
  (relief, not tint — the existing grain test asserted only difference);
  the same triangle placed at ten times the distance shows per-pixel
  variance below a threshold (the fade); a back-lit triangle with
  `emissive = 1` renders its exact palette colour; a `skin` triangle at the
  terminator has a higher red/green ratio than a `matte` one of the same
  colour; a roughness-0.2 highlight peaks brighter than a roughness-0.8
  one; `lambert` shading with bump differs from `lambert` without.
- Bootstrap: `--check` passes on the committed table; the survey stage
  carries a hand `label` forward across a re-survey (already pinned).

**G**

- `plate.py`: `black` and `white` equal the percentile means by
  construction on a synthetic plate; a uniform plate has zero grain and a
  checkerboard its amplitude; all-black and all-white plates are total;
  `softness` for each filter at cell 4, cell 1 and cell 0.5 (`nearest`
  pixelates at 4, nothing pixelates at ≤ 1).
- Resolver: `plate` estimates once per camera (counting stub) and follows
  an override plate; `FrameDescription.plate` defaults to
  `NEUTRAL_PLATE`.
- GL: `off` reproduces the golden; `on` with `NEUTRAL_PLATE` at `msaa = 0`
  reproduces it too; a black actor pixel over a plate whose `black` is
  (30, 20, 20)/255 lands on that colour; a white actor pixel over a plate
  whose `white` is 0.8 grey is pulled below 255; under `bilinear` at scale
  4 an actor edge's transition spans more pixels than under `off`; under
  `nearest` at scale 4 the composited actor is constant within every 4×4
  cell; grain is identical across two draws of the same frame and zero
  outside the actor; MSAA still resolves into `.texture` at the same size
  and `thumbnail()` round-trips; the leak count rises by the listed
  resources.

**UI, options, shell.** Both new options validate, clamp an unknown value
to the default, cycle, survive the settings round-trip and the CLI
override, and persist only from the menu; the Graphics page shows nine
rows plus Back with nothing clipped, each row cycles by keyboard and
mouse, and the journey test reaches both new rows.

## Limitations

- **Penumbra bleed.** The blur runs after the mask erase, so a soft edge
  can spread up to `R_MAX` pixels across a foreground mask's edge.
- **One shadow map for the frame.** Its texel size is set by the widest
  spread of actors in view: fine in a room, coarse in the big caves.
  Single-sided panels can show acne bounded by the bias.
- **Receivers are actors only.** Walls, masks and the plate receive
  nothing but the projected ground silhouette; the receiving plane still
  travels with the actor.
- **Derivative bump is per 2×2 quad**: faintly blocky at scale 1,
  invisible at 4. Distant actors lose their relief by design.
- **The review is a human step** that gates H's retune.
- **Detail is still shape-free**: no seams, no planks, no buttons.
- **Tone matching is global** to the plate, not local to the pixels
  around the actor; grain is luma-only.
- **`nearest` pixelates the actor, not its ground shadow**, which stays
  at target resolution on the plate layer.
- **Softening touches the actor's interior**, not just its edge, by
  `sigma ≤ 0.35 · cell`.
- **Cost.** F adds one depth pass over every instance and two blur passes
  over the coverage texture; G adds two resolves and one full-target
  composite. `hard` and `off` are the escape hatches, both on the Graphics
  page.
- **Software backend** stays flat, unlit, unshadowed and uncomposited.

## Out of scope

- Shadows onto walls, masks or the plate beyond the projected silhouette;
  a true floor plane from `hard_cols`.
- Depth haze; anisotropic specular; plate reflections; image textures;
  authored per-camera light, plate or material data.
- Any change to `skel.skin()`, `draw_list`, picking, masks, combat or
  input.
- Any change to the background filters themselves, the override
  directory layout, or the UI layer beyond the two Graphics rows.
- Anything in the software backend.
