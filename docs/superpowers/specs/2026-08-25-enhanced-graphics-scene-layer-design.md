# Enhanced graphics: a scene-description layer between assets and presentation

Date: 2026-08-25. Status: approved design, awaiting implementation plan.

## Goal

Insert a pure, GL-free layer between game asset data (bodies, animations,
camera images, masks, palette) and graphics presentation so that:

1. Actors render at a higher internal resolution with smooth shading, crisp
   polygonal foreground masks, and proper 3D spheres/lines.
2. Backgrounds can be filtered and, optionally, replaced by user-supplied
   overrides (this repo still ships no game data).
3. Every simulation-facing contract (picking, mouse targets, mask trigger
   tests, combat hot points, `draw_list`) keeps using the FITD-faithful
   integer projection unchanged.
4. Headless tests and `make prove-*` keep working without a GL context.

## Decisions (from brainstorming)

- Full enhancement path: resolution, shading, filtering, override hook.
- Two outputs from one pose: `skel.skin()` remains the logical 320×200
  projection; a float geometry path is added beside it, sharing
  `skel.pose_vertices()` so pose can never disagree.
- Internal render target is an integer multiple of 320×200 (`scale`, default
  4, clamped 1..8). UI presenters keep painting 320×200 and are composited
  on top with nearest-neighbour scaling.
- Masks become polygons rasterised into the GL stencil buffer per actor; the
  bitmap `mask.py` path is kept only for the logical contract and software
  backend.
- `AssetResolver` checks an optional override directory first, then the
  original data. Original backgrounds get a configurable upscale filter.
- Shading modes: `flat`, `lambert`, `smooth` (default `smooth`, per-vertex
  normals averaged within a skeleton group).
- Structure: immutable per-frame `FrameDescription` consumed by
  interchangeable backends (`GLBackend`, `SoftwareBackend`).

## Architecture

| Module | Role | Touches pygame/GL |
|---|---|---|
| `scene.py` | `build_frame(game, floor, resolver, options) -> (FrameDescription, draw_list)`. Replaces the asset-touching body of `__main__._scene_frame`. Evaluates painter order and mask applicability. | no |
| `geometry.py` | `pose_geometry(body, group_states, actor_angles) -> BodyGeometry`: float vertices, per-vertex normals, triangulated primitives, expanded spheres/lines/points. Uses `skel.pose_vertices`. | no |
| `mask_geometry.py` | Mask polygons in 320×200 screen space plus trigger rects, taken from the existing mask parser before `fill_poly`. | no |
| `asset_resolver.py` | `AssetResolver(data_dir, override_dir=None)`: `background(floor, cam)`, `body(num)`, `palette()`. Override lookup by convention path, fallback to `assets.py` / `floor.py`. One isolated PNG-loading function touches pygame's image module. | PNG load only |
| `render_options.py` | `RenderOptions(scale, shading, background_filter, override_dir)`; validation and clamping. | no |
| `render_gl.py` | `GLBackend(ctx, options).draw(frame) -> internal texture`. Owns all ModernGL: shaders, stencil masking, background filtering. | yes |
| `render_soft.py` | `SoftwareBackend.draw(frame) -> (200,320,3) uint8`: today's numpy compositor over the logical projection. Used headless. | no |
| `render.py` | `Renderer(options)`: window, context, backend selection, UI composite, present, `window_to_logical` (unchanged). | yes |

`__main__._scene_frame` becomes: `frame, draw_list = build_frame(...)`;
`renderer.compose_scene(frame)`. `picking.py`, `playworld.py`, `navigate.py`
and the mouse contract are untouched; `draw_list` stays built from the logical
`skin()` bbox.

## Data model

All frozen dataclasses; bulk data as numpy arrays.

```
FrameDescription
  camera:      CameraView        # FITD camera fields + derived float view-projection
  background:  BackgroundRef     # ImageAsset (H,W,3) uint8, any size; filter hint
  palette:     np.ndarray (256,3) uint8
  actors:      tuple[ActorDraw]  # painter order from sort_actor_indices
  masks:       tuple[MaskDraw]   # masks of this camera

ActorDraw
  index:       int
  geometry:    BodyGeometry
  position:    (x, y, z) float world
  room:        int
  zv:          tuple
  logical:     RenderResult      # skel.skin() output, the FITD projection
  mask_ids:    tuple[int]        # masks whose trigger rects this actor satisfies

BodyGeometry
  vertices:    (N,3) float32 posed, model space
  normals:     (N,3) float32 unit
  tris:        (M,3) int32; tri_colors (M,) uint8 palette index
  lines:       (L,2) int32; line_colors (L,) uint8
  spheres:     tuple[(centre_idx, radius, color)]
  points:      (P,) int32 indices; point_sizes (P,) uint8; point_colors (P,) uint8

MaskDraw
  id: int; polygons: tuple[(K,2) int16]; bbox: (x1,y1,x2,y2)
  viewed_room: int; test_rects: tuple[(x1,z1,x2,z2)]
```

Rules:

- Mask applicability (`render._mask_applies_to_actor`) moves to `scene.py`.
  Backends never evaluate game rules.
- Normals are computed per frame from the posed vertices with numpy: face
  normals per triangle; vertex normal = normalised sum over adjacent faces
  belonging to the same skeleton group. Degenerate faces contribute zero; a
  vertex with no valid faces gets the camera-facing normal (0,0,-1).
- Sphere primitives expand to a level-1 icosphere scaled by `size` around the
  centre vertex; lines are emitted as index pairs and widened in the backend
  (width = `scale` px); points become `scale`- or `2·scale`-px quads.
- `geometry.vertices` derive from the same integer-posed vertices as `logical`;
  only projection differs.

## Rendering pipeline (`GLBackend.draw`)

Internal target `(320·scale) × (200·scale)`: RGBA colour, depth, stencil.

1. Background: upload the `ImageAsset` texture; draw a full-target quad with
   the configured filter: `nearest`, `bilinear`, or `xbr` (fragment shader on
   the original 320×200). Overrides always use bilinear.
2. Camera: one float view-projection matrix from FITD camera fields
   (translate `(cam − room.world)·10`, three-axis rotation, `focal1/focal2`
   perspective). Parity test: every posed vertex projected through the float
   path lands within 0.5 logical px of `skin()`.
3. Actors, in painter order, each: clear depth and stencil; write stencil=1 for
   every `MaskDraw` in `mask_ids` (polygon fans, colour writes off); draw
   triangles with depth test `<=` and stencil test `== 0`, shader per shading
   mode (`flat`: palette colour; `lambert`: face normal · fixed camera-space
   light; `smooth`: interpolated vertex normal · light; ambient 0.55, diffuse
   0.45, palette colour); then lines, points and spheres under the same
   stencil. No CPU readback between actors.
4. UI composite: `render_active_mode` and the HUD/notice/cursor presenters
   paint onto a transparent 320×200 RGBA canvas instead of the scene frame.
   Presenters that dim or reuse the scene (`render_game_over`,
   `render_inventory`) receive a `scene_thumbnail` (the software-backend
   320×200 frame or a downsampled GL readback, chosen by the Renderer) for
   that effect. The canvas is uploaded as an RGBA texture and drawn over the
   internal target with nearest filtering.
5. Present: `fit_quad` letterboxes the internal target into the window with
   linear filtering.

Per-actor GPU buffers are rebuilt every frame (dynamic VBOs); no caching.

`SoftwareBackend.draw` reproduces today's compositor: background copy,
per-actor logical primitive rasterisation, bitmap mask erase, painter
composite, returning the 320×200 frame. It is byte-identical to the current
`Renderer.compose_scene` on the M2 goldens.

## Configuration, overrides, error handling

- `config.py` schema v2 (additive): `render: {scale: 4, shading: "smooth",
  background_filter: "bilinear", override_dir: null}`. v1 files load with
  defaults. Invalid fields fall back individually and raise the existing
  settings notice overlay. CLI overrides for one session: `--render-scale`,
  `--shading`, `--overrides DIR`.
- Override convention: `<override_dir>/backgrounds/floor<NN>/camera<NNN>.png`
  (any size) and `<override_dir>/palette.png` (256×1). Missing or unreadable
  files: log once per path, fall back to the original. Never a crash mid-play.
- GL failure (no 3.3 core context, stencil unavailable): `Renderer` falls back
  to `SoftwareBackend` at scale 1 and shows the settings notice "Enhanced
  rendering unavailable". The game always runs.
- The system menu Configuration screen gains a "Graphics" row cycling scale,
  shading and filter; mouse-reachable like the other rows (extends the mouse
  contract declaration); applies on the next frame and persists.

## Testing and proofs

- Golden `FrameDescription` tests on the attic fixture: actor order,
  `mask_ids`, and logical bboxes identical to the pre-change `_scene_frame`.
- Projection parity: float path vs `skin()` ≤ 0.5 px for every vertex of every
  body in the data (skips without data).
- Normals: group-local averaging, unit length, no NaN on degenerate faces.
- `SoftwareBackend` byte-identical to the current compositor on
  `tests/test_render.py` goldens.
- GL tests (skipped when no context): stencil mask matches the bitmap erase
  at scale 1 within polygon-edge tolerance; shading modes differ; override
  PNG is picked up; fallback path engages when the backend raises.
- Config: v1 → v2 defaults; invalid render fields raise the notice.
- `make prove-*` targets keep the software backend.
- `make prove-graphics`: renders fixed camera/actor fixtures at scale 4 to
  PNGs under `docs/graphics-proof/` for a manual attestation doc
  (`docs/enhanced-graphics-proof.md`).

## Out of scope

- Shipping or generating upscaled assets (AI upscaling tool: separate milestone).
- Rendering at arbitrary window resolution / aspect.
- Retained scene graphs or GPU buffer caching.
- Changes to picking, navigation, combat, or LIFE.
