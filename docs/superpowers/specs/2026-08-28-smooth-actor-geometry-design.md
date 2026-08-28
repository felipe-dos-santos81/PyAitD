# Smooth Actor Geometry Design

Date: 2026-08-28

Status: Approved design — awaiting implementation plan

Builds on: actor surface response and materials
(`2026-08-28-actor-surface-and-materials-design.md`), which gave
`BodyGeometry` its `rest` and `ao` fields and the actor shader its material
terms; actor lighting and shadows
(`2026-08-27-actor-lighting-and-shadows-design.md`) for the ground shadow
pass this design re-tessellates; and the enhanced graphics scene layer
(`2026-08-25-enhanced-graphics-scene-layer-design.md`) for
`FrameDescription`, `BodyGeometry` and `GLBackend`.

Supersedes: nothing. It adds a field to `RenderOptions`, two fields to
`BodyGeometry`, one pure module, one system-menu page, and a second way for
`GLBackend` to draw an actor's triangles and its shadow.

## Goal

Round the low-poly bodies. A limb in AITD1 is a six-sided prism and a head
is an 80-triangle icosphere; at render scale 4 every facet shows, and every
term the previous specs added — specular, occlusion, grain, the shadow's
silhouette — reads as a facet artefact on a surface that should be round.

This design curves the triangles on the GPU: each posed triangle becomes a
PN (point-normal) patch tessellated into 4, 16 or 64 sub-triangles, with
per-corner normals that respect creases so furniture keeps its edges. It
also fixes a defect it cannot work around: today's `smooth` shading gives
35% of the hero's mesh vertices a camera-facing placeholder normal, and a
curved patch built on a placeholder normal bulges instead of rounding.

It is a presentation change. No game state, no input handling and no
simulation code is touched. `skel.skin()`, `draw_list`, picking, masks and
the mouse contract are untouched.

"More graphics realism of actors and objects" decomposes, this round, into
four independent sub-projects; this spec is the first:

| Sub-project | Status |
|---|---|
| E. Smooth geometry (crease-aware normals, GPU tessellation) | **this spec** |
| F. Shadows v2 (soft penumbra, one gathered pass, self-shadowing) | later spec |
| G. Plate integration (exposure, grain, edge softness, haze) | later spec |
| H. Materials v2 (bump detail, anisotropy, skin wrap, plate reflections) | later spec |

## Current state

Measured on the shipped data (272 bodies; the attic and combat fixtures):

- A body's polygons index a shared vertex list, so mesh adjacency exists.
  Winding is consistent across every shared edge of every body surveyed
  (100% of two-face edges are traversed in opposite directions); only the
  global inward/outward sign of a body is unknown. That is what "FITD
  polygons have no consistent winding" actually amounts to.
- Meshes are open and sometimes non-manifold: edges shared by one face
  (limb rings, single-sided panels) and by three, four or six faces both
  occur.
- `geometry._vertex_normals` lets a face contribute to a vertex only when
  the whole face lies in that vertex's skeleton group. On the hero body 12,
  117 of 214 triangles span two groups, and 46 of the 131 triangle-referenced
  vertices touch *only* such faces, so they get the `(0, 0, -1)` fallback.
  Monster body 24: 44 of 100. Those fragments shade flat.
- Polygon-edge dihedral angles: the rocking horse and the chair are bimodal
  (flat panels plus edges above 75°); the piano's case is gently curved
  (45–60°); the hero's spread is even, with 27% of edges above 60°.
- Spheres are level-1 icospheres (80 triangles) expanded on the CPU.
- The shadow pass projects `geometry.vertices` onto the ground plane on the
  CPU (`lighting.project_to_plane`) and rasterises the flat triangles.
- The CONFIG page holds 15 rows at a 13 px pitch ending at y=197, and rows
  may not shrink below 13 px (the 12×12 hit-target contract). There is no
  room for a sixteenth row.
- Numpy PN tessellation of a body costs 0.2–1.4 ms per frame; a geometry
  shader on this machine (GL 4.1 Metal) allows 128 output components per
  vertex and 1024 output vertices, and ModernGL 5.12 supports instanced
  attributes (`/i`) and transform feedback (`VertexArray.transform`).

## Decisions taken during brainstorming

1. **Aggressive rounding, every body.** The crease threshold is 80°: an
   edge sharper than that stays hard, everything softer rounds. Limbs,
   heads, the horse's belly and the piano's case round; slabs, boxes and
   chair legs stay crisp. A per-body override in the existing
   `bodies/body<NNN>.json` moves the threshold (`0` opts a body out).
2. **Tessellation runs on the GPU**, chosen over per-frame numpy
   refinement for zero per-frame CPU cost. The mechanism is **instanced
   vertex-shader evaluation, not a geometry shader**: each source triangle
   is one instance carrying its three corners, the per-vertex stream is a
   fixed sub-patch of barycentrics, and the vertex shader evaluates the PN
   patch. It keeps the GPU path's property, has no output-vertex cap (GL's guaranteed 1024 total geometry output
   components hold 64 sixteen-component vertices: level 2, not 3), avoids the geometry stage
   Apple's GL emulates slowly on a tile-based GPU, and is testable exactly
   through transform feedback.
3. **Topology is precomputed once per body from the rest pose** and cached
   on `AssetResolver` like the AO bake. Creases do not pop when a joint
   bends across the threshold; per frame the CPU does what it does today
   plus one normal pass.
4. **Crease and non-manifold edges keep straight PN edge control points**,
   so a smooth patch never opens a crack against a hard neighbour; boundary
   edges curve.
5. **The shadow pass tessellates too**: the same vertex shader in a
   "project onto the plane" mode writes coverage, so the shadow is as round
   as the actor.
6. **The knob is `smoothing ∈ (0, 1, 2, 3)`**, `0` byte-identical to today,
   and it lives on a **new Graphics sub-page** of the system menu that also
   takes over CONFIG's six existing graphics rows — the page CONFIG has no
   room for, and the home the three queued specs will need.

## Architecture

### Refinement: `PyAitD/render/refine.py`

Numpy only: no pygame, no GL; its one project import is `render.geometry`.

```
CREASE_DEG = 80.0

@dataclass(frozen=True)
class Refinement:                 # per body, pose-independent
    orientation: np.ndarray       # (M,) float32 ±1: makes face normals agree across shared edges
    pairs: np.ndarray             # (K,2) int32 (corner, face): the faces that feed each corner's normal
    straight: np.ndarray          # (M,3) float32: 1.0 where edge k (v_k -> v_k+1) keeps a straight control polygon
    crease_deg: float

def plan_refinement(body, crease_deg=CREASE_DEG) -> Refinement
def corner_normals(vertices, tris, refinement) -> np.ndarray     # (M,3,3) float32, per frame
def subpatch(level) -> np.ndarray                                 # (3*4**level, 3) float32 barycentrics
def evaluate(corners, normals, straight, bary) -> (positions, normals)
    # corners, normals (M,3,3); straight (M,3); bary (S,3) -> two (M,S,3): the numpy twin of the GLSL
def parse_crease(data) -> float | None
```

`plan_refinement` works on `pose_geometry(body, rest_states)`'s `tris` —
the same fan triangulation the backend draws — and its rest-pose vertices:

- *Orientation.* Faces are visited breadth-first through edges shared by
  exactly two faces; a face whose traversal of the shared edge runs in the same
  direction as its already-oriented neighbour's (the neighbour's own sign
  applied) gets the opposite sign, so the two disagree on the edge as a
  consistently wound mesh must.
  Propagation never crosses an edge with three or more faces. Each
  connected component then takes the global sign that makes the
  area-weighted sum of `dot(normal_f, centroid_f - centroid_component)`
  non-negative. On the shipped data every body is already consistent, so
  this is a safety net for the per-corner averaging below, not a repair the
  data needs; the shader keeps its per-fragment flip toward the viewer for
  single-sided surfaces regardless.
- *Creases.* An edge shared by exactly two faces is a crease when the angle
  between the two oriented face normals exceeds `crease_deg`. An edge
  shared by three or more faces is a crease. An edge belonging to a
  zero-area face is a crease. A boundary edge (one face) is not a crease.
  `straight[f, k]` is 1.0 for a crease edge and 0.0 otherwise, so boundary
  edges curve.
- *Smoothing groups.* At a vertex `v`, its incident faces are connected
  through the non-crease edges incident to `v`; each connected set is a
  smoothing group. Corner `(f, k)` of vertex `v` is fed by every face in
  `f`'s group at `v`. `pairs` lists `(3*f + k, g)` for each such face `g`.
  A corner always lists its own face.

`corner_normals` computes each face's oriented, area-weighted normal from
the posed vertices — `orientation * cross(b - a, c - a)`, unnormalised so
large faces weigh more, as `_vertex_normals` does — accumulates them through
`pairs` with `np.add.at`, and normalises. A corner whose sum is zero
(degenerate geometry) gets `geometry._CAMERA_FACING`, as today's fallback
does; on the shipped bodies no used corner falls back, and a test pins that
for body 12.

`subpatch(level)` is the barycentric triangle list of a triangle split into
`n = 2**level` segments per edge — `4**level` sub-triangles, each row a
`(u, v, w)` with `u + v + w = 1`, corners present exactly. Deterministic
order, `lru_cache`d, arrays read-only like `geometry.icosphere`. Level 0 is
the triangle itself, defined so `evaluate` can express the identity; the
backend never asks for it because level 0 means "off".

`evaluate` is the reference for the GLSL below, in the same terms: PN edge
control points, straight collapse, centre point, cubic Bernstein position,
quadratic normal. Tests compare the shader against it through transform
feedback.

`parse_crease(data)` returns `data["crease"]` as a float when the key is
present, `None` when absent, and raises `ValueError` naming the key when
the value is not a number (bools rejected) or lies outside 0..180.

### Geometry

`BodyGeometry` gains

- `corner_normals: (M,3,3) float32` — one normal per triangle corner.
  Defaults in `__post_init__` to `normals[tris]`, the per-vertex normals
  replicated per corner, so every positional constructor keeps working and
  a frame built without a plan still tessellates on the legacy normals.
- `straight: (M,3) float32` — defaults to zeros.

`pose_geometry(body, group_states, actor_angles=None, ao=None,
refinement=None)`: when handed a `Refinement`, fills `corner_normals` from
`refine.corner_normals` and `straight` from the plan. `normals` is still
computed exactly as today — the `smoothing=0` path, lines and points read
it — and `test_normals_average_only_within_a_group` keeps pinning that
legacy rule for that path.

### Where the plan comes from at runtime

`AssetResolver` gains

```
def refinement(self, body_num) -> Refinement
```

memoised per body number. The crease threshold comes from the body's
override file when one exists: `bodies/body<NNN>.json` gains an optional
`"crease": <number 0..180>` beside its `ramps`/`indices`. One validator,
`asset_resolver._validate_body_override(data)` — `materials.parse_assignments`
followed by `refine.parse_crease` — runs once through the existing
`_override` cache, and both `material_table` and `refinement` read fields
off the cached dict. One file, one verdict: an invalid `crease` rejects the
file's material remap too, logs once, and lands in `failures`; a missing
file is silent. `override_check.check_body_materials` becomes
`check_bodies` and validates through the same function, so `make
check-overrides` reports a bad `crease` with its path.

`build_frame` passes `refinement=resolver.refinement(actor.body_num)` to
`pose_geometry`. `ActorDraw` and `FrameDescription` gain no field: the plan
rides on the geometry, and the frame stays option-agnostic — `RenderOptions`
still never reaches `scene.py`.

### The GL pipeline

**Instance layout.** For each actor, `GLBackend._instance_data(geometry,
position, palette)` builds one `(M', 45)` float32 row per triangle — the
body's triangles followed by the expanded sphere triangles — from the same
numbers `_triangle_data` gathers today, reshaped one triangle per row:

```
corner k ∈ {0,1,2}:  in_p{k}: vec4(pos.xyz, ao)        in_n{k}: vec4(normal.xyz, straight[k])
                     in_c{k}: vec4(rgb, palette index)   in_r{k}: vec3(rest)
per-vertex stream:   in_bary: vec3, from subpatch(level)
```

Twelve packed per-instance attributes (`/i`) plus one per-vertex attribute:
13 of the 16 slots GL 3.3 guarantees. `pos` is world space (the actor
position is added on the CPU, as now). Spheres enter with the icosphere's
unit vectors as corner normals and `straight = 0`, so PN rounds a level-1
icosphere into a visually perfect sphere; `rest` and `ao` are set as today.

**The tessellating vertex shader** `_TESS_VSH` — GLSL 330 core only: plain
attributes with a VAO divisor, no `gl_InstanceID`, no extension — emits
exactly `_ACTOR_VSH`'s varyings, so `_ACTOR_FSH` is reused unchanged,
including its per-fragment flip toward the viewer and every material term:

- Edge control points `b_ij = (2 p_i + p_j) / 3 - (1 - straight_ij) *
  dot(p_j - p_i, n_i) * n_i / 3`: PN's projection onto the corner's tangent
  plane, collapsing to the straight line on a crease. Centre `b111 = E +
  (E - V) / 2` with `E` the mean of the six edge points and `V` the mean of
  the corners. Position is the cubic Bernstein sum at `in_bary`.
- Normals: PN's quadratic scheme — the mid-edge normal `n_ij` is
  `n_i + n_j` reflected across the edge's chord on a smooth edge and
  `n_i + n_j` on a straight one — normalised after interpolation, then
  `v_normal = rot * n`.
- `v_color` and `v_index` from corner 0 (a triangle has one palette index),
  `v_rest` and `v_ao` barycentric, `v_world_y = pos.y` so the contact term
  sees the tessellated height.
- `uniform int project; uniform vec3 travel; uniform float plane_y;` — when
  `project == 1` the shader adds `(plane_y - pos.y) / travel.y * travel` to
  the evaluated position before `mvp`: the GLSL twin of
  `lighting.project_to_plane`. The `MIN_UP` clamp stays on the CPU and
  arrives in `travel`.

Corners are exact (`u = 1` gives `p_0`). A shared edge's curve depends only
on the two shared corners' positions, their corner normals and the edge's
`straight` flag. Two faces sharing a non-crease edge are in the same
smoothing group at both of its vertices, so they see the same corner
normals; `straight` is an edge property; a crease is straight from both
sides. Patches are therefore **watertight** by construction, and a test
pins it on `evaluate`.

**Programs and resources.** `_tess_prog = (_TESS_VSH, _ACTOR_FSH)` and
`_tess_shadow_prog = (_TESS_VSH, _STENCIL_FSH)`, compiled at construction
like every other program: a compile failure fails the backend, which
`_select_backend` already turns into the software fallback. Three
`subpatch` buffers (levels 1–3) are allocated at construction. The
resource-leak test's count rises by five. Per-draw buffers and vertex
arrays stay transient, released after each draw as now.

**Per-frame loop** under `options.smoothing > 0`, per actor: rasterise
masks → build the instance buffer → shadow pass renders it through
`_tess_shadow_prog` with `project = 1`, `travel`, `plane_y` and `mvp`
(replacing the CPU projection and `_shadow_geom_prog`; skipped, like today,
when the actor has no triangles) → composite the shadow as today → clear
depth → render the same buffer through `_tess_prog` with `project = 0`
(the actor uniforms — shading, lighting, tints, material texture, presets,
`plane_y`, `contact_height`, `target_size`, `mask_tex` — are uploaded by
one helper applied to both `_actor_prog` and `_tess_prog`) → lines and
points through `_screen_prog` unchanged → release the buffer. Each draw
issues `instances = M'` over `3 * 4**level` vertices. The per-actor depth
buffer is unchanged, so the rounded surface self-occludes correctly.

**Under `options.smoothing == 0`** the branch at the top of `_draw_frame`
selects today's functions verbatim: `_render_triangles`, the CPU
`project_to_plane`, `_shadow_geom_prog`. The tessellating programs are
compiled but never bound. That is the byte-identity the golden pins.

**Cost.** GPU: level 2 turns the largest body (570 triangles) into 9k and a
45-actor combat frame into roughly 40k triangles; level 3 is four times
that. Both are negligible for the target hardware. CPU per frame: today's
work plus `corner_normals` — one `np.add.at` over about `3 M` pairs.

### Options

`RenderOptions` gains `smoothing: int ∈ SMOOTHING_LEVELS = (0, 1, 2, 3)`
(level → `2**level` segments per edge → 4, 16 or 64 sub-triangles),
mirroring `msaa` exactly: bool-rejecting validation that clamps an unknown
value to the default, an entry in `to_payload`, `cycle_smoothing`, a
`--smoothing {0,1,2,3}` session-only CLI flag applied through
`apply_render_overrides`, and a settings-v2 key — an older settings file
lacking it falls back to the default through the usual validation notice,
as `realism` did. It defaults to `0` when it lands and to `2` in the final
task.

### The Graphics sub-page

A new `SystemMenuPage.GRAPHICS`.

- CONFIG keeps Sticky Action, the remappable controls, then one
  `Graphics...` row and `Back to Menu`: `config_row_count() = 3 +
  len(REMAPPABLE_CONTROLS)`. Its 13 px pitch is left as it is; the page is
  simply shorter.
- GRAPHICS holds `GRAPHICS_ROWS = 7` — `Scale`, `Shading`, `Filter`,
  `Lighting`, `AA`, `Realism`, `Smoothing: Off / Low / Medium / High`
  (levels 0–3) — plus `Back`. Layout starts at `pygame.Rect(48, 12 + i *
  22, 224, 18)` for eight rows with 12 px text, hit rows through
  `effective_rects` like every page; the plan may retune the pitch, never
  below 13 px.
- `reduce_system_menu`: ACCEPT on `Graphics...` opens the page at cursor 0
  and clears `hover`, as entering the key picker does. On GRAPHICS, UP and
  DOWN wrap over the eight rows; ACCEPT on rows 0–6 applies `cycles[i]` —
  today's tuple plus `cycle_smoothing`; ACCEPT on `Back` or CANCEL returns
  to CONFIG with the cursor on `Graphics...` (`config_row_count() - 2`)
  and `SystemMenuResult(save=True)`, mirroring CONFIG → MAIN. `KEY_PICK`
  and `capture_system_key` are unchanged.
- Mouse hover and hit-testing dispatch on `SystemMenuLayout.hit_rows(page)`
  and follow.
- `shell._MENU_RENDER_FIELDS` gains `smoothing`, so a menu change persists
  and a CLI override does not.

### Proof tooling

`tools/prove_graphics.py` gains `--smoothing` (default:
`RenderOptions().smoothing`), renders every existing fixture × shading ×
realism file at that level, and writes two extra files at level 0 —
`attic-smooth-enhanced-flatmesh.png` and `combat-smooth-enhanced-flatmesh.png`
— so the proof shows before and after. `docs/smooth-geometry-proof.md`
carries the automated gates and the manual attestation table.

## Task ordering

Every intermediate state is shippable; the `0` default guards each step
until the last.

1. The Graphics sub-page holding CONFIG's six existing graphics rows; no
   option change.
2. `smoothing`: options, payload, `cycle_smoothing`, CLI flag, the seventh
   row, `_MENU_RENDER_FIELDS`; default `0`.
3. `refine.py`: `plan_refinement`, `corner_normals`, `subpatch`,
   `evaluate`, `parse_crease`; `BodyGeometry.corner_normals` and
   `.straight`; `pose_geometry(refinement=)`.
4. `AssetResolver.refinement`, `_validate_body_override`,
   `override_check.check_bodies`, `build_frame` wiring.
5. GL: instance layout, `_TESS_VSH`, the actor draw through `_tess_prog`,
   the transform-feedback parity test and the `smoothing=0` identity test.
6. GL: the tessellated shadow pass.
7. Flip the default to `2`; `prove_graphics` axis; the proof document;
   `CONTEXT.md`, `AGENTS.md`, `README.md`.

## Testing

`refine.py` is pure, so most of the substance is testable headless.

- `refine.py`: a two-triangle strip with one face flipped gets
  `orientation = (+1, -1)` and agreeing corner normals; propagation stops at
  a three-face edge; a unit cube plans all-straight at 80° and all-smooth at
  100°; a hexagonal prism (60° sides, 90° caps) at 80° has smooth side edges
  and straight cap rims; a side corner's normal is the area-weighted mean of
  its two side faces and excludes the cap; a T-junction edge is straight; a
  boundary edge is not; a zero-area face's edges are straight and its
  corners never NaN; `subpatch(level)` has `4**level` triangles, barycentrics
  ≥ 0 summing to 1, and the three corners present exactly; `evaluate`: a
  flat triangle with face normals stays in its plane, tilted normals bulge
  along the mean normal, corners are exact, a straight edge's samples are
  collinear, two adjacent patches agree on every sample of their shared
  edge; `parse_crease` accepts an absent key, an int and a float, rejects a
  bool, a string and 181 naming the key. Data-gated: every body plans
  without error, and body 12 has zero fallback corner normals.
- Geometry: `corner_normals` defaults to `normals[tris]`, `straight` to
  zeros; a plan fills both; `normals` is unchanged by a plan.
- Resolver: `refinement` plans once per body (counting stub); a `crease`
  override is honoured; a bad file logs once, lands in `failures`, uses the
  default plan and drops the material remap with it; a missing file is
  silent. `override_check`: a `bodies/body000.json` with `"crease": "soft"`
  is reported with its path.
- Options, settings, CLI: `smoothing` validates, clamps an unknown value to
  the default, rejects a bool, cycles, survives the settings round-trip, and
  is applied by `--smoothing`; only a menu change of it is persisted.
- UI: `Graphics...` opens the page; each of the seven rows cycles its
  field; Back and CANCEL return to CONFIG on `Graphics...` and save; row
  counts and labels; per-page mouse hit rows; the key picker is unaffected;
  one `journey` test reaches the page through the real event pump.
- GL, through the `gl_ctx` fixture and the `render` mark:
  - Transform feedback: `_TESS_VSH`'s positions and normals match
    `refine.evaluate` on random patches (positions within 1e-4 of the
    patch extent, normals within 1e-3), in both `project` modes, the
    projected one against `project_to_plane`.
  - `smoothing=0` reproduces `tests/golden/scene_lit_classic.npy`; the
    existing test names `smoothing=0` explicitly once the default flips.
  - A level-2 hexagonal prism's silhouette is wider at mid-edge than at
    level 0.
  - A cube renders pixel-identically at levels 0 and 2 under
    `shading="flat"`.
  - A sphere's tessellated shadow covers more pixels than its faceted one
    and none under a mask.
  - The resource-leak count rises by five.

## Limitations

- **PN patches are C0 across edges.** Positions and normals are continuous,
  curvature is not; the coarsest bodies may show faint shading bands at
  patch borders.
- **Open rings curve outward.** A limb's boundary ring bows out, so the gap
  or overlap the original mesh already shows at a bent joint can grow by a
  few units.
- **One global threshold.** 80° is a guess that fits the surveyed bodies;
  a chamfered 60–75° furniture edge rounds (override it per body) and a
  genuinely round 85° facet stays hard.
- **Silhouettes grow past the logical bbox.** Picking uses `skel.skin`'s
  bounding box and masks are unchanged, so a bulge can cross a mask edge
  the flat mesh did not — sub-pixel at game scale.
- **`lambert` shows sub-facets**, since it derives normals from the
  tessellated surface.
- **Software backend** stays flat and faceted; `smoothing` is GL-only like
  lighting and materials.
- **Per-frame instance buffers** are rebuilt per actor, the same cadence as
  today's per-draw buffers.

## Out of scope

- Subdivision surfaces, G1 continuity, or authored per-body meshes.
- Sub-projects F (shadows v2), G (plate integration) and H (materials v2).
- Any change to `skel.skin()`, `draw_list`, picking, masks, combat or input.
- Any change to the background filter, the background override system, or
  the UI layer beyond the Graphics sub-page.
- Tessellation, lighting or materials in the software backend.
