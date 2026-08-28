# Actor Lighting and Shadows Design

Date: 2026-08-27

Status: Approved design — awaiting implementation plan

Builds on: the enhanced graphics scene layer
(`2026-08-25-enhanced-graphics-scene-layer-design.md`), which introduced
`FrameDescription`, `GLBackend` and the three shading modes this design
extends.

Supersedes: nothing. It adds fields to `RenderOptions` and
`FrameDescription` and changes how `GLBackend` shades actors; no committed
decision fixes either.

## Goal

Make actors and objects look like they are standing in the room rather than
pasted over a picture of it. Two things do most of that work: a light whose
direction and colour come from the room the actor is actually in, and a
shadow on the ground beneath them.

This is a presentation change. No game state, no input handling and no
simulation code is touched. `skel.skin()`, `draw_list`, picking, masks and
the mouse contract are untouched.

## Scope

"Graphics realism of actors and objects" decomposes into four independent
sub-projects. This spec is the second of them and folds in the first:

| Sub-project | Status |
|---|---|
| A. Silhouette quality (MSAA, normal handling) | folded into this spec |
| B. Grounding: per-camera light and shadows | **this spec** |
| C. Surface response (ambient occlusion, specular, rim, materials) | later spec |
| D. Material texture (needs a UV or projection scheme; bodies have none) | later spec |

C and D each need their own spec. C's specular is meaningless until a light
points somewhere defensible, and D over an unlit, ungrounded model buys
almost nothing — which is why B comes first.

## Current state

- Actors are palette-coloured triangles plus expanded spheres, lines and
  points, drawn per actor into an internal target at `320·scale × 200·scale`
  with a fresh depth buffer per actor and a per-actor mask texture sampled
  with `discard`.
- Lighting is one hard-coded camera-space constant,
  `LIGHT_DIR = (-0.3, -0.5, -0.8)`, and one formula,
  `shade = 0.55 + 0.45 * abs(dot(N, L))`. The three `SHADING_MODES` differ
  only in where `N` comes from: `flat` (none), `lambert` (screen-space
  derivatives) and `smooth` (interpolated vertex normals).
- The `abs()` is there because FITD polygons have no consistent winding, so
  a body's normals point both inward and outward. Its cost is that a surface
  facing away from the light is exactly as bright as one facing into it: the
  model has no lit side and no dark side.
- Nothing casts a shadow. There is nothing for a shadow to land on either —
  the scene contains a background image, actor bodies and mask polygons, and
  no floor geometry whatsoever.
- The game files carry no light information. `Camera` has position, three
  angles and three focal lengths; `Room` has a world offset and collision
  columns. There is no lamp, no light colour, no time of day.
- Backgrounds may be user overrides, including AI-regenerated ones, resolved
  through `AssetResolver.background`.
- The internal target is single-sampled, so actor silhouettes are hard-edged
  against a background that may be smoothly filtered.

## Decisions taken during brainstorming

1. The whole four-part problem is decomposed; this spec covers grounding
   (light plus shadow) with silhouette quality folded in.
2. Each camera's light is **estimated from its background image**. Authored
   per-camera light files were considered and rejected for now: the repo
   ships no game data, so every one of several hundred cameras would need
   hand-authoring before anything looked different. Estimation covers every
   camera on every floor at once and re-derives itself automatically for a
   regenerated background.
3. The shadow is a **projected silhouette** of the actor's own geometry on a
   ground plane, not a blob. It therefore has the actor's real shape and
   follows the animation.
4. The ground plane is the actor's own `zv` lower bound. It travels with the
   actor, so the shadow is always directly beneath and does not detach in
   mid-air; see Limitations.
5. `lighting="fixed"` reproduces today's output byte for byte, and is the
   regression net for the change.

## Architecture

### The light estimator

A new module `PyAitD/render/lighting.py`. Pure numpy: no pygame, no GL, no
engine imports beyond what `render/` may already use.

```
@dataclass(frozen=True)
class SceneLight:
    direction: tuple[float, float, float]   # unit, camera space
    key: tuple[float, float, float]         # 0..1 linear RGB
    ambient: tuple[float, float, float]     # 0..1 linear RGB
    contrast: float                         # 0..1

def estimate_light(pixels) -> SceneLight
```

From an `(H, W, 3)` uint8 background alone:

- **ambient** — the mean colour of the darkest quartile of pixels by
  luminance. That is what unlit surfaces in this room actually reflect, so it
  is the right colour for an actor's shadow side and for the shadow itself.
- **key** — the mean colour of the brightest decile: what a lit surface in
  this room looks like.
- **direction** — the luminance-weighted centroid of that brightest decile,
  measured against the image centre, gives a screen-space bias `(dx, dy)`
  normalised to roughly ±1 across the frame. The light is
  `normalize(dx, dy_down, -k)` where `k` is a fixed forward component so the
  light can never degenerate into pure sidelight, and `dy_down` is `dy`
  clamped to keep a minimum downward component. Rooms are lit from above, and
  a light with no vertical term projects no shadow at all.
- **contrast** — the ratio of the bright decile's mean luminance to the dark
  quartile's, mapped into 0..1. A dark, high-contrast crypt gets a strong key
  and a hard, opaque shadow; a flatly lit corridor gets a weak key and a
  faint one. One number drives both the key/ambient ratio and the shadow's
  opacity, so rooms differ from one another for the same reason photographs
  of them would.

Screen-space y grows downward in this projection (`sy = y·focal3/depth +
SCREEN_CENTER_Y`), so a bright region high in the frame yields a negative
`dy`, and the clamp is expressed in that convention.

`estimate_light` is deterministic, total, and defined for degenerate inputs:
an all-black or all-white plate yields zero contrast, equal `key` and
`ambient`, and a direction that still satisfies the unit-length, downward and
forward guarantees.

### Where the light comes from at runtime

`AssetResolver` gains

```
def light(self, floor, cam_idx) -> SceneLight
```

memoised per `(floor.number, cam_idx)` exactly as `background` caches its
decode. It estimates from whatever `background(floor, cam_idx)` returns, so
an override — including an AI-regenerated plate — is estimated from the
override, not from the original. Backgrounds are already cached, so this
costs one estimate per camera per session.

`FrameDescription` gains `light: SceneLight`, filled by `build_frame`. The
field carries a default equal to the legacy fixed light, so existing test
helpers that construct frames positionally keep working unedited.

### Shading

Two changes inside `_ACTOR_FSH`, both active only under `lighting="scene"`:

- **Orient rather than fold.** In camera space the viewer looks along +z;
  any normal whose z component faces away from the viewer is negated. This
  gives a consistent outward orientation for the closed bodies the game
  actually contains, and removes the reason `abs()` existed.
- **A real term.** `shade = ambient + key · max(0, dot(N, L))`, with a wrap
  factor so the unlit side lands on the room's ambient colour rather than
  black. `key` and `ambient` arrive as uniforms from `frame.light`; the
  key/ambient balance is driven by `contrast`.

Under `lighting="fixed"` the shader keeps `0.55 + 0.45 · abs(dot(N, L))`
against `LIGHT_DIR`, unchanged.

The `shading` option keeps its present meaning — where `N` comes from — and
is orthogonal to `lighting`.

### The shadow pass

Inside `GLBackend`'s existing per-actor loop, which today reads: rasterise
this actor's masks, clear depth, draw actor. The shadow pass goes between
the mask rasterisation and the actor.

1. The camera-space light rotates into world space through
   `rotation_matrix(frame.camera.state).T` — the matrix is orthonormal, so
   the transpose is the inverse.
2. The ground plane is `plane_y`, the actor's `zv` lower bound in the
   vertical axis (`zv` is `[x1, x2, y1, y2, z1, z2]`).
3. `project_to_plane(vertices, light_world, plane_y)` — a pure function
   beside `estimate_light` — slides each posed world vertex along the light
   onto that plane: `t = (plane_y - v.y) / L.y`, `p = v + t·L`. `L.y` is
   guaranteed non-degenerate by the estimator's downward clamp, and `t` is
   clamped so a near-horizontal light cannot throw the shadow to the horizon.
4. The flattened triangles rasterise into a new single-channel
   `_shadow_tex` / `_shadow_fbo` pair, allocated and released exactly like
   `_mask_tex` / `_mask_fbo`.
5. One full-target quad then multiplies `ambient`-tinted darkness through
   that coverage texture over the background, with opacity from `contrast`.

Going through a coverage texture rather than blending the triangles directly
is what keeps overlapping limbs from double-darkening into a black blob:
coverage is binary, so the composite darkens each pixel exactly once.

The pass samples the same `_mask_tex` and discards, so a shadow never spills
over a foreground pillar. The actor is drawn after its own shadow and simply
paints over it.

### MSAA

The internal target becomes a multisampled colour and depth renderbuffer
pair, resolved into the existing `self.texture` at the end of `_draw_frame`.
`read_rgb`, `thumbnail`, `render.py`'s compositor and everything else
downstream keep reading `self.texture` and are unchanged. The sample count is
clamped at construction to `ctx.max_samples`; `msaa=0` keeps today's
single-sampled path.

### Options

`RenderOptions` gains two fields, each mirroring `shading` exactly — a
tuple of legal values, clamping in `validate_render_options`, an entry in
`to_payload`, a `cycle_*` function, a CONFIG menu row in
`ui.reduce_system_menu`'s `cycles` tuple and label list, an entry in
`shell._MENU_RENDER_FIELDS`, and a CLI flag:

- `lighting: str` ∈ `("fixed", "scene")`
- `msaa: int` ∈ `(0, 2, 4, 8)`

Both default to off — `"fixed"` and `0` — when the option lands, so adding
them changes nothing. `msaa`'s default becomes `4` in the task that
implements it, and `lighting`'s becomes `"scene"` in the final task.

### Software backend

`SoftwareBackend` ignores `frame.light` and stays flat, unlit and
unshadowed. That path already announces itself as degraded, and it renders
the logical 320×200 projection rather than the float geometry the shadow
projection needs. This matches the calls the enhanced-graphics and
native-resolution-UI specs both made about it.

## Task ordering

The byte-for-byte requirement dictates the order, and every intermediate
state is shippable:

1. `lighting` and `msaa` options, defaulting to `fixed` and `0` — no
   behaviour change.
2. `lighting.py`: `SceneLight`, `estimate_light`, `project_to_plane`.
3. `AssetResolver.light`, `FrameDescription.light`, `build_frame` wiring.
4. The `scene` shading term in the actor shader.
5. The shadow pass.
6. MSAA, defaulting to 4.
7. Flip `lighting`'s default to `scene`.

## Testing

The estimator and the projection are pure numpy, so the substantive half is
testable headless with no GL context:

- `estimate_light` on synthetic plates: a bright blob at the top-left of a
  dark field yields a direction biased up and left; a uniform grey field
  yields low contrast and a near-frontal direction; `key` and `ambient`
  equal the decile and quartile means by construction.
- `estimate_light` on all-black and all-white inputs still returns a
  unit-length direction with the guaranteed downward and forward components,
  and zero contrast.
- `project_to_plane`: a vertex above the plane lands exactly on it; a
  straight-down light projects straight down; a near-horizontal light is
  clamped rather than escaping to the horizon.
- `AssetResolver.light` estimates once per camera (a counting stub loader
  proves the memoisation) and follows an override background rather than the
  original.
- GL, through the existing `gl_ctx` fixture and the `render` mark:
  - `lighting="fixed"` renders pixel-identically to the current backend.
  - Under `scene`, a face oriented toward the light is brighter than one
    oriented away — the `abs()` regression that `fixed` cannot catch.
  - A shadow darkens background pixels beneath an actor and leaves pixels
    above it untouched.
  - Two overlapping shadow triangles darken a pixel exactly as much as one
    does.
  - A shadow is erased where a foreground mask covers it.
  - MSAA resolves into `self.texture` at the same size, and `thumbnail()`
    still round-trips.
  - `test_render_gl.py`'s resource-leak test asserts a fixed count of
    released GL objects (`leak_checked == 15` today); that count rises by
    the shadow texture, the shadow framebuffer and the multisample
    renderbuffers.

## Limitations

- **The shadow does not detach.** The receiving plane is the actor's own
  `zv` lower bound, which travels with the actor, so a jumping or falling
  actor keeps its shadow at its feet and there is no height falloff. Rooms
  carry `hard_cols` with y ranges that could yield a true floor height, but
  choosing the right column under an arbitrary footprint is its own piece of
  work. For a game whose actors walk almost everywhere they go this is right
  nearly all the time; a true floor plane is a follow-up if falls look wrong.
- **The estimate is plausible, not correct.** A room whose brightest region
  is a window behind the actor will light them from behind. The forced
  downward and forward components bound how wrong it can look, and low
  contrast pulls uncertain rooms toward flat ambient, but some rooms will
  read better on `fixed`. The authored-sidecar path set aside in decision 2
  is the remedy if that turns out to be common.
- **Thin geometry may shimmer.** Flipping normals toward the viewer assumes
  a closed body seen from outside. A single-sided polygon seen at a grazing
  angle can flip per fragment.
- **Cost.** One extra rasterisation and one extra full-target composite per
  actor, plus MSAA at the internal scale. `msaa=0` and `lighting="fixed"`
  are both escape hatches, and both are reachable from the CONFIG menu.

## Out of scope

- Sub-projects C (surface response) and D (material texture).
- Authored per-camera light files.
- Shadows cast onto walls, onto foreground masks, or onto other actors.
- Lighting or shadows in the software backend.
- Any change to `skel.skin()`, `draw_list`, picking, masks, combat or input.
- Any change to the background filter, the override system, or the UI layer.
