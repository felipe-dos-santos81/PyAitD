# Actor Surface Response and Materials Design

Date: 2026-08-28

Status: Approved design — awaiting implementation plan

Builds on: actor lighting and shadows
(`2026-08-27-actor-lighting-and-shadows-design.md`), which introduced the
per-camera `SceneLight`, the oriented-normal `scene` shading path and the
ground shadow this design shades on top of; and the enhanced graphics scene
layer (`2026-08-25-enhanced-graphics-scene-layer-design.md`) for
`FrameDescription`, `BodyGeometry` and `GLBackend`.

Supersedes: nothing. It adds fields to `RenderOptions`, `BodyGeometry` and
`ActorDraw`, adds two pure modules and one tool, and changes how
`GLBackend` shades actors under `lighting="scene"`.

## Goal

Give actors and objects a surface. Today every body is a set of
flat-palette triangles that respond to the room's light in one way: a
Half-Lambert diffuse term. Skin, cloth, leather, wood and steel all reflect
identically, nothing has grain, and nothing darkens in a crease or where it
meets the floor.

This design covers the last two sub-projects of the decomposition the
lighting spec set out:

| Sub-project | Status |
|---|---|
| A. Silhouette quality (MSAA, normal handling) | shipped |
| B. Grounding: per-camera light and shadows | shipped |
| C. Surface response (occlusion, specular, rim, per-material response) | **this spec** |
| D. Material texture (procedural detail; bodies have no UVs) | **this spec** |

It is a presentation change. No game state, no input handling and no
simulation code is touched. `skel.skin()`, `draw_list`, picking, masks and
the mouse contract are untouched.

## Current state

- `BodyGeometry` carries posed float vertices, per-vertex normals averaged
  within a skeleton group, fan-triangulated polygons with a palette index
  each, and lines, points and spheres.
- `GLBackend._triangle_data` resolves each triangle's palette index to RGB
  before upload; the vertex format is `3f 3f 3f` (`in_pos`, `in_normal`,
  `in_color`). The palette index does not reach the shader.
- Under `lighting="scene"`, `_ACTOR_FSH` computes
  `v_color * (fill_tint + key_tint * wrapped²)` from an oriented normal and
  the room's estimated light. Under `lighting="fixed"` it keeps the legacy
  `0.55 + 0.45 * abs(dot(n, l))`.
- Lines and points are unshaded (`shading == 0`); spheres are icospheres
  drawn through the same triangle path.
- The game files carry no material information. A body is vertices,
  skeleton groups and coloured primitives; the palette is 256 RGB entries
  organised in ramps.
- Backgrounds and the palette may be user overrides under an override
  directory with a fixed layout (`backgrounds/`, `palette.png`,
  `screens/`).
- `tools/regenerate_backgrounds.py` reaches Gemini through the `agy` CLI
  (`agy_structured(model, instructions, schema)`), never a Python SDK.

## Decisions taken during brainstorming

1. C and D are one spec and one implementation plan: both change the same
   shader and the same vertex stream, and D's grain is worthless without
   C's per-material response to give it a reason to exist.
2. Material identity comes from a **palette-index table** committed to the
   repo, with a **per-body override** on top. The table classifies 256
   integers; it is not game data. Keying on index rather than colour means
   a palette override keeps its materials.
3. The table is **bootstrapped by a tool**, not hand-written from nothing:
   a deterministic survey of palette ramps and body usage proposes a class
   per ramp, an optional vision-model pass labels the uncertain ones, and a
   hand pass finishes. The tool's output is what gets committed.
4. The look is **selectable**: `realism="classic"` is byte-identical to
   today, `realism="enhanced"` is the tuned preset. Both are one set of
   global strengths multiplied into the same shader, so `classic` is
   identical by construction rather than by a separate code path.
5. Occlusion is **rest-pose vertex AO baked once per body at load time**
   plus an analytic contact term at the feet. Screen-space AO was
   considered and rejected: two more targets per actor, a per-actor loop
   rewrite, and on 100–300-triangle bodies it would mostly darken facet
   creases.
6. Detail is **procedural noise sampled in rest-pose model space**, so it
   sticks to the limb through animation. Image textures need UVs the
   bodies do not have and per-body authoring nothing would benefit from
   until it was done.

## Architecture

### Materials: `PyAitD/render/materials.py`

Pure Python and numpy: no pygame, no GL, no engine imports.

```
MATERIAL_CLASSES = ("matte", "skin", "cloth", "leather", "hair",
                    "wood", "stone", "metal", "glass", "emissive")

@dataclass(frozen=True)
class Material:
    roughness: float     # 0..1: specular exponent and spread
    specular: float      # 0..1: highlight strength
    metallic: float      # 0..1: highlight takes the surface colour, not the key's
    rim: float           # 0..1: fresnel rim strength
    detail: float        # 0..1: procedural grain amount
    detail_scale: float  # FITD units per noise cell
    detail_kind: int     # 0 none, 1 grain, 2 weave, 3 streak, 4 brushed

CLASS_PRESETS: dict[str, Material]   # one tuned Material per class

@dataclass(frozen=True)
class MaterialTable:
    classes: tuple[str, ...]          # 256 entries, index = palette index
    def parameters(self) -> np.ndarray      # (256, 8) float32: the 7 fields + padding
    def remapped(self, overrides: dict[int, str]) -> "MaterialTable"

def load_table(path) -> MaterialTable
def parse_table(data: dict) -> MaterialTable
def default_table() -> MaterialTable      # PyAitD/render/materials.json, cached

@dataclass(frozen=True)
class RealismPreset:
    spec: float; rim: float; ao: float; contact: float; detail: float; hemisphere: float

PRESETS = {"classic":  RealismPreset(0, 0, 0, 0, 0, 0),
           "enhanced": RealismPreset(spec=1.0, rim=0.6, ao=0.7, contact=1.0, detail=1.0, hemisphere=1.0)}
# enhanced's numbers are the starting point task 4 tunes against the proof fixtures
```

The table file shape, shared by the committed default and every per-body
override:

```json
{
  "ramps":   [{"lo": 16, "hi": 31, "class": "skin", "note": "bodies 0,1; head/hands"}],
  "indices": {"200": "metal"}
}
```

`parse_table` applies `ramps` in order, then `indices`; every index not
mentioned is `matte`. An unknown class, an index outside 0..255 or a ramp
with `lo > hi` raises `ValueError` naming the offending entry.
`remapped` applies a second parsed table's explicit assignments on top and
leaves everything else as it was.

Every `CLASS_PRESETS` entry has `detail_scale > 0` (the shader divides by
it). `matte` is defined as `Material(1, 0, 0, 0, 0, 1, 0)`: no specular, no
rim, no detail. A table of all `matte` under `enhanced` differs from
`classic` only by the hemisphere and occlusion terms.

### Where materials come from at runtime

`AssetResolver` gains

```
def material_table(self, body_num) -> MaterialTable
def geometry_ao(self, body_num) -> np.ndarray
```

both memoised per body number. `material_table` starts from
`default_table()` and, when an override directory is set, applies
`overrides/bodies/body{num:03d}.json` through `remapped`. The override
goes through the existing `_override` path: a missing file is silent, an
unreadable or invalid one logs once, is recorded in `failures`, and falls
back to the default. `override_body_material_path(override_dir, num)` sits
beside the other `override_*_path` helpers so `override_check.py` can
validate the same layout.

`geometry_ao` calls `bake_vertex_ao(self.body(num))` once and caches the
result.

`ActorDraw` gains `materials: MaterialTable`, filled by `build_frame` from
`resolver.material_table(actor.body_num)`. The field defaults to
`default_table()` so positional test constructors keep working.

### Geometry: `rest`, `ao` and `PyAitD/render/occlusion.py`

`BodyGeometry` gains

- `rest: (N,3) float32` — `body.vertices` unposed, in model space. Detail
  noise is sampled here, so grain is glued to the limb.
- `ao: (N,) float32` — per-vertex occlusion, 1 = fully open.

`pose_geometry(body, group_states, actor_angles=None, ao=None)` takes the
baked array as an optional argument and defaults to ones, so every present
caller and test is unchanged.

`occlusion.py` is numpy only:

```
def bake_vertex_ao(body, rays=32) -> np.ndarray   # (N,) float32 in 0..1
```

For each rest-pose vertex it casts a fixed, deterministic set of `rays`
directions distributed over the hemisphere around the vertex normal
(computed as `geometry._vertex_normals` does, without the group
restriction) and intersects them with every triangle of the body
(Möller–Trumbore, vectorised as an `(N·rays, M)` broadcast). Each ray
starts a small epsilon along its direction so a vertex never hits the
triangles it belongs to. Hits count regardless of triangle facing, because
FITD polygons have no consistent winding. AO is the unoccluded fraction.

A body with no triangles returns all ones. Bodies are 100–400 vertices and
100–300 triangles, so the bake is a few milliseconds and runs once per body
per session.

### Shading

The vertex format grows from `3f 3f 3f` to `3f 3f 3f 3f 1f 1f`:
`in_pos in_normal in_color in_rest in_ao in_index`. `_triangle_data`
keeps resolving RGB (`in_color`) and also passes the palette index through
as a float. Spheres carry `rest` as the icosphere surface and `ao = 1`.

New uniforms on `_actor_prog`:

- `material_tex`: a 256×2 RGBA32F texture holding `MaterialTable.parameters()`
  (row 0: roughness, specular, metallic, rim; row 1: detail, detail_scale,
  detail_kind, unused). Uploaded per actor from `actor.materials`; the
  backend caches the last table object and skips the upload when it is the
  same instance.
- `preset_a = vec3(spec, rim, ao)` and `preset_b = vec3(contact, detail,
  hemisphere)` from `PRESETS[options.realism]`.
- `plane_y`: the actor's `zv` lower bound, already computed for the shadow
  pass; `contact_height`: a constant in FITD units over which the contact
  term fades, initially 150 (roughly shin height on the hero bodies), tuned
  in task 4.

The fragment shader, on the `lighting == 1` path only (the `fixed` branch is
untouched):

```
vec4 m0 = texelFetch(material_tex, ivec2(index, 0), 0);   // roughness specular metallic rim
vec4 m1 = texelFetch(material_tex, ivec2(index, 1), 0);   // detail scale kind -
vec3 view = vec3(0, 0, -1);                              // camera space, toward the viewer
vec3 h    = normalize(l + view);

float diffuse_w = wrapped * wrapped;                       // as today
vec3  diffuse   = fill_tint + key_tint * diffuse_w;
float hemi      = mix(1.0 - 0.3 * preset_b.z, 1.0 + 0.3 * preset_b.z, n.y * 0.5 + 0.5);
float contact   = 1.0 - preset_b.x * (1.0 - clamp((v_world_y - plane_y) / contact_height, 0.0, 1.0)) * 0.5;
float occl      = mix(1.0, v_ao, preset_a.z) * contact;
float gloss     = exp2(1.0 + 10.0 * (1.0 - m0.x));
vec3  spec_col  = mix(vec3(1.0), v_color, m0.z);
vec3  spec      = key_tint * spec_col * pow(max(dot(n, h), 0.0), gloss) * m0.y * preset_a.x;
vec3  rim       = key_tint * pow(1.0 - max(dot(n, view), 0.0), 3.0) * m0.w * preset_a.y;
float grain     = 1.0 + preset_b.y * m1.x * detail_noise(v_rest / m1.y, int(m1.z));
f_color = vec4(v_color * grain * diffuse * hemi * occl + spec + rim, 1.0);
```

`detail_noise` is a hashed 3D value noise in GLSL returning −1..1; `kind`
selects isotropic grain (1), a two-axis weave — the product of two sines
modulated by the noise (2), a one-axis streak — noise stretched along the
limb's long axis (3), or a brushed anisotropic stretch across it (4).
`v_world_y` and `v_rest` are new varyings; `v_world_y` is the posed
vertex's world-space height, passed from the vertex shader alongside the
existing transform.

Under `realism="classic"` every preset strength is 0, so `hemi = occl =
grain = 1`, `spec = rim = 0`, and the expression collapses to
`v_color * diffuse`: today's output. That identity is what the regression
test pins.

Lines and points stay on the unshaded `shading == 0` path.
`SoftwareBackend` stays flat, unlit and unshadowed, as the lighting spec
decided.

### Options

`RenderOptions` gains `realism: str ∈ ("classic", "enhanced")`, mirroring
`lighting` exactly: a `REALISM_MODES` tuple, clamping in
`validate_render_options`, an entry in `to_payload`, `cycle_realism`, a
CONFIG menu row in `app/ui.reduce_system_menu`'s `cycles` tuple and label
list, an entry in `shell._MENU_RENDER_FIELDS`, and a `--realism` CLI flag.
It defaults to `"classic"` when it lands and flips to `"enhanced"` in the
final task.

### The bootstrap tool: `tools/bootstrap_materials.py`

Three stages, each writing a reviewable JSON so the run can stop and be
edited between them. Only stage 2 touches a model.

**`survey`** — deterministic, no network. Reads the game palette and every
body (`assets.num_bodies`, `assets.body(i)`).

- *Ramps*: splits the 256 entries into runs where luminance is monotone and
  hue drifts less than a threshold; entries that fit no run are singletons.
- *Usage*: per ramp, which bodies use it, how many triangles, and which
  skeleton group indices. Group 0 is the root; a group's role (head, hand)
  is inferred from the body's group count and the group's vertex extent,
  and is reported as a hint, never trusted on its own.
- *Heuristic proposal*: hue/saturation/luminance rules (low-saturation
  peach → `skin`; long near-grey ramp → `metal`; saturated brown → `wood`
  or `leather` by luminance; very short bright ramp → `emissive`) combined
  with usage (a ramp only on bodies with many groups → `skin`/`cloth`
  candidates; only on one-group bodies → object materials). Each ramp gets
  `class` and `confidence` in 0..1.
- Writes `survey.json` (ramps, usage, proposal) and, under `sheets/`, one
  flat-colour contact sheet per body rendered through `SoftwareBackend` in
  rest pose against a black plate, plus a copy per ramp with that ramp's
  triangles tinted magenta.

**`label`** — optional, `--vision`. For each ramp with
`confidence < 0.8`, calls `agy_structured` — imported from
`tools/regenerate_backgrounds.py`, so the `agy` CLI remains the only route
to a model and no dependency is added — with the sheet, the highlighted
copy, and the schema `{"class": enum(MATERIAL_CLASSES), "reason": str}`.
Merges the answer into `survey.json` as `vision_class` beside the
heuristic's `class`. Never overwrites a hand-set `label`. When `agy` is not
on `PATH` it prints one line saying so and exits 2 without touching the
file.

**`emit`** — resolves each ramp's class as hand `label` > `vision_class` >
heuristic `class`, and writes `PyAitD/render/materials.json` in the
`load_table` shape, with a `note` per ramp recording the evidence
(`"bodies 0,1,34; groups 5,6; vision: skin"`). `--check` re-emits from the
current `survey.json` into memory and exits 1 if the committed file differs.

Constraints inherited from the repo: `# SPDX-License-Identifier:
GPL-2.0-only` first line; no Pillow; the tool changes no engine module;
`agy` is reached only through the one imported function; unit tests
inject a fake `agy_structured`; the single live test is skipped unless
`PYAITD_LIVE_AI=1`. `survey.json` and `sheets/` land in a git-ignored
`--out` directory (default `data/aitd1/materials-survey/`); only
`materials.json` is committed. A `make bootstrap-materials` target wraps
the three stages with `vision=1` selecting stage 2.

## Task ordering

Every intermediate state is shippable; the `classic` default guards each
step until the last.

1. `materials.py` — `Material`, `CLASS_PRESETS`, `MaterialTable`,
   `parse_table`/`load_table`, `RealismPreset`, `PRESETS`; the `realism`
   option wired through options, menu, shell and CLI, default `classic`.
2. `tools/bootstrap_materials.py` `survey` and `emit`; run it against the
   local data; hand-review; commit `PyAitD/render/materials.json`.
3. `occlusion.py` `bake_vertex_ao`; `BodyGeometry.rest` and `.ao`;
   `AssetResolver.geometry_ao` and `material_table`; `ActorDraw.materials`
   and `build_frame` wiring.
4. Shader, vertex format and material texture; tune the `enhanced` preset
   and `CLASS_PRESETS` against the graphics-proof fixtures.
5. Per-body override JSON, `override_body_material_path`, and
   `override_check.py` validation of `bodies/`.
6. Bootstrap `label` stage (`--vision`).
7. Flip `realism`'s default to `enhanced`; `docs/graphics-realism-proof.md`
   with `classic`/`enhanced` pairs from `tools/prove_graphics.py`, which
   gains a realism axis beside its shading axis.

## Testing

`materials.py` and `occlusion.py` are pure, so most of the substance is
testable headless.

- `materials.py`: a table round-trips through JSON; an unknown class is
  rejected with the index named; `remapped` changes only the listed
  indices; `parameters()` is `(256, 8)` float32 with every row inside the
  documented ranges; `PRESETS["classic"]` is all zeros; unmentioned
  indices are `matte`.
- `occlusion.py`: a lone triangle's vertices are fully open; a vertex
  inside a closed box is fully occluded; a vertex on a floor beside a wall
  is about half; two calls agree exactly; a triangle-less body returns all
  ones; a triangle's own vertices are not occluded by it.
- `geometry.py`: `rest` equals `body.vertices` whatever the pose; `ao`
  length matches `vertices`; the default `ao` is all ones.
- Resolver: `material_table` estimates once per body (counting stub);
  follows a per-body override; an invalid override logs once, lands in
  `failures`, and falls back to the default; a missing one is silent.
- `override_check.py`: an invalid `bodies/body000.json` is reported with
  its path.
- Bootstrap: ramp splitting on a synthetic palette with two ramps and a
  singleton; the heuristic on hand-built ramps with known usage; `emit`
  precedence label > vision > heuristic; a fake `agy_structured` records
  the schema and the sheet paths it was handed and only sees ramps under
  the confidence threshold; `--check` fails on a drifted table and passes
  on the committed one when data is present.
- Options: `realism` validates, clamps an unknown value to the default,
  cycles, and survives the settings round-trip like `lighting` does.
- GL, through the `gl_ctx` fixture and the `render` mark:
  - `realism="classic"` under `lighting="scene"` is pixel-identical to a
    golden buffer captured from the pre-change backend.
  - Under `enhanced`, a `metal` triangle facing the half-vector is
    brighter at its centre than a `matte` triangle of the same colour.
  - A `rim` material brightens pixels at the silhouette edge and not at the
    centre.
  - Two fragments that differ only in `rest` differ when `detail > 0` and
    match when it is 0.
  - A vertex with `ao = 0` is darker than one with `ao = 1`.
  - `test_init_failure_releases_every_already_allocated_gl_object`'s
    `leak_checked` count rises by the material texture.

## Limitations

- **AO is rest-pose.** Limbs pressed together in an animation do not
  darken each other; only creases present in the rest pose do.
- **Material identity is inferred.** A palette index shared between skin
  on one body and wood on another is wrong on one of them until a
  per-body override says otherwise. The survey's usage report shows where
  that happens.
- **Detail is shape-free.** No seams, buttons, or wood grain following a
  plank. That is the price of having no UVs.
- **Low-poly bodies stay low-poly.** Specular on a dozen-facet limb shows
  the facets; `CLASS_PRESETS` are tuned with that in mind and `enhanced`
  can be turned off from the CONFIG menu.
- **Software backend** stays flat.
- **Cost.** One extra draw attribute set per actor and a 256-texel lookup
  per fragment. `classic` is the escape hatch.

## Out of scope

- Image textures, UV authoring, or any per-body art.
- Screen-space AO, shadows between actors, shadows on walls.
- Any change to `skel.skin()`, `draw_list`, picking, masks, combat or
  input.
- Any change to the background filter, the background override system, or
  the UI layer.
- Lighting, occlusion or materials in the software backend.
