# AI background regeneration: export, guide, check

Date: 2026-08-25. Status: approved design, awaiting implementation plan.

## Goal

Let the user regenerate the original 320×200 camera backgrounds with an
external AI tool of their choice and play with the results, using the
override directory that the enhanced graphics layer already loads
(`docs/superpowers/specs/2026-08-25-enhanced-graphics-scene-layer-design.md`).

The repo provides the two ends of that loop and nothing in between:

1. **Export** every background into the exact override layout, with a
   per-camera *guide* image and a manifest, so the user can regenerate in
   place with structural references.
2. **Check** an override directory the way the game will load it, report
   what is missing, invalid or geometrically off, and optionally render
   original-vs-override proofs.

The AI step itself is the user's: no model, no API key, no vendor is added.

## Decisions (from brainstorming)

- Scope: backgrounds only. Actors, UI, palette and pictures are out.
- The AI runs outside this repo. The tool exports; the user regenerates;
  `AssetResolver` imports unchanged.
- Export writes PNGs, guide overlays and a manifest (not PNGs alone).
- Export + Check, no normalising importer: the override contract is the
  interface, the checker catches mistakes instead of fixing them. A
  resize/rename importer is a possible later spec.

## Global constraints

- Dependencies fixed: pygame-ce, ModernGL, NumPy, pytest. Add nothing.
- This repo never ships game data. Exported PNGs, guides, manifests and
  proof renders are never committed; every output directory this spec
  names is git-ignored.
- `# SPDX-License-Identifier: GPL-2.0-only` first line of every Python file.
- Engine modules are untouched: `asset_resolver.py`, `render_*.py`,
  `scene.py`, `floor.py`, `__main__.py` do not change. The only interface
  between this work and the game is the override directory contract:
  `DIR/backgrounds/floor<NN>/camera<NNN>.png`, RGB, any size up to the
  resolver's dimension limit.
- Purity: `background_export.py` and `override_check.py` import neither
  pygame nor moderngl. PNG encoding (`pygame.image.save`) lives in
  `tools/` only; PNG decoding goes through `asset_resolver.load_png_rgb`.
- `skel.skin`'s integer projection stays the authority for anything the
  simulation reads. The guide's projected geometry is documentation for a
  human and an image model, drawn through `scene.CameraView`; it is
  allowed to diverge from the integer path by the amounts already
  documented on `CameraView.project` (≈12px within ~100 units of the
  camera, <1px beyond ~2000).

## Architecture

| Module | Role | pygame/GL |
|---|---|---|
| `PyAitD/background_export.py` | Pure export core. `manifest_record(floor, cam_idx, pixels) -> dict`, `guide_overlay(floor, cam_idx, scale) -> (200·scale, 320·scale, 3) uint8`, `export_manifest(records) -> dict`. Line rasterisation is a small numpy Bresenham (`draw_polyline(img, points, rgb)`), clipped to the image. | no |
| `PyAitD/override_check.py` | Pure checker. `Finding(floor, camera, path, kind, detail)` frozen; `check_overrides(override_dir, floors, manifest=None) -> list[Finding]`; `summarize(findings, manifest) -> str`. Loads through `AssetResolver` so acceptance is identical to the game's. | no |
| `tools/export_backgrounds.py` | CLI: `DATA --out DIR [--floors 0-7] [--guide-scale N]`. Writes `DIR/backgrounds/floorNN/cameraNNN.png`, `DIR/guides/floorNN/cameraNNN.png`, `DIR/manifest.json`. Encodes PNGs with `pygame.image.save` via a temp file + rename. | PNG save |
| `tools/check_overrides.py` | CLI: `DATA DIR [--floors 0-7] [--proof OUT]`. Prints findings and the coverage summary; exit 1 on any `invalid` or `aspect`. `--proof` renders original/override side-by-sides through `render_gl` at scale 4. | PNG save; GL for `--proof` only |
| `Makefile` | `export-backgrounds out=DIR`, `check-overrides overrides=DIR [proof=1]`. | — |
| `docs/ai-background-regeneration.md` | The workflow: export → regenerate (ControlNet / image-to-image with the guide as structure reference; keep 16:10; keep doors, stairs and floor edges where the guide draws them) → check → `make run overrides=DIR` / `--overrides DIR`. Lists the finding kinds and what to do about each. | — |
| `README.md` | One paragraph under Run pointing at the doc and the two targets. | — |

## Export

### Layout

```
DIR/
  manifest.json
  backgrounds/floor00/camera000.png   # 320x200 RGB, original, overwrite in place
  guides/floor00/camera000.png        # 320·S x (200·S + 12) RGB, S = --guide-scale (default 4)
```

`DIR` is directly usable as `--overrides DIR` before any regeneration: the
checker then reports 0 regenerated, and the game renders the originals
through the override path (pixel-identical to not overriding, which is a
test).

### Manifest (`"schema": 1`)

```json
{
  "schema": 1,
  "data_dir": "<absolute path of DATA at export time>",
  "guide_scale": 4,
  "legend": {"red": "masks", "blue": "collision", "green": "walkable"},
  "cameras": [
    {
      "floor": 0, "camera": 0,
      "source": "backgrounds/floor00/camera000.png",
      "guide": "guides/floor00/camera000.png",
      "size": [320, 200],
      "viewed_rooms": [0, 1],
      "masks": 9,
      "sha256": "<hex of the 320x200x3 RGB bytes as exported>"
    }
  ]
}
```

A camera whose image is out of range in `CAMERAnn.PAK` (`Floor.camera_image`
raises `KeyError`) is recorded with `"source": null, "guide": null,
"sha256": null` and skipped. `sha256` is over the raw RGB bytes, not the
PNG file, so it does not depend on the encoder; the checker recomputes it
from decoded pixels.

### Guide overlay

Drawn over the original upscaled ×S by nearest neighbour, so structure
lines are 1px crisp and the AI sees the pixel art it is replacing:

| Layer | Source | Colour | Space |
|---|---|---|---|
| Foreground mask polygons | `floor.mask_draws(cam_idx)` → `MaskDraw.polygons` | red `(255, 0, 0)` | already 320×200 screen space; multiplied by S |
| Hard-collision boxes | `room.hard_cols` of every viewed room | blue `(0, 128, 255)` | room-scale → projected |
| Cover (walkable) polygons | `parse_cover_zones(floor.camera_raw, offset, viewed_idx)` | green `(0, 200, 0)` | cover units × `navmesh.COVER_SCALE` → room-scale → projected |
| Legend | 12px footer strip: three 40px colour swatches (red, blue, green, in that order, left-aligned) on black. No text — the repo has no pygame-free glyph table; the colour → meaning key lives in `docs/ai-background-regeneration.md` and the manifest carries `"legend": {"red": "masks", "blue": "collision", "green": "walkable"}` | — | image space |

Projection: `CameraState.from_camera(floor.cameras[cam_idx], room.world_x,
room.world_y, room.world_z).angles()` wrapped in `CameraView`, exactly as
`scene.build_frame` does, one `CameraState` per viewed room. Hard-col boxes
are drawn as their bottom rectangle (`y = y2`, the floor edge, four
corners) and top rectangle (`y = y1`), plus the four verticals; cover
polygons at `y = 0` of the room. Any edge with a culled endpoint
(`CameraView` sentinel) is skipped. Room-space to world: the room's
`world_x/y/z` is already folded into `CameraState.from_camera`, so box and
cover coordinates are passed as-is, matching how actor positions reach
`CameraView` in `build_frame`. The plan pins this with a data-gated test
comparing a projected hard-col corner against the integer path for one
real camera within the documented tolerance.

### Error handling

- A floor whose `ETAGEnn.PAK`/`CAMERAnn.PAK` is missing prints one warning
  and is skipped. Exit 0 if at least one floor exported, else exit 2.
- PNGs are written to `<path>.tmp` then renamed, so an interrupted run never
  leaves a truncated file the resolver would reject.
- `--out` that already contains `backgrounds/` is refused unless
  `--force`: the user's regenerated images must not be overwritten by a
  careless re-export. `--force` re-exports everything.

## Check

`check_overrides(override_dir, floors, manifest)` walks every `(floor,
camera)` of the given floors and yields at most one `Finding` per camera:

| kind | condition | severity |
|---|---|---|
| `missing` | no file at the override path — the original will be used | informational |
| `invalid` | `AssetResolver.background()` fell back and recorded the path in `resolver.failures` (not RGB, too large, unreadable); `detail` is the resolver's message | error |
| `aspect` | width/height differs from 1.6 by more than 1% — the game would stretch it | error |
| `size` | smaller than 320×200, or not an integer multiple of it | informational |

Coverage: with a manifest, a loaded override whose recomputed sha256
equals the manifest entry counts as "original"; otherwise "regenerated".
`summarize` prints `regenerated R / original O / missing M / invalid I /
aspect A` per floor and in total. Without a manifest, coverage is not
reported. `check_overrides` never raises on a bad override; only a missing
`DATA` or unreadable manifest is a usage error (exit 2).

`--proof OUT` (default `docs/graphics-proof/overrides/`, git-ignored):
for every camera that has a loadable override, boot the floor's camera on
a standalone ModernGL context (as `tools/prove_graphics.py` does), render
the background twice — original and override — through `GLBackend` at
scale 4 with the configured filter, and write them side by side as
`OUT/floorNN-cameraNNN.png`. No actors are drawn: the proof is about the
plate. If no GL context is available, print a notice and skip proofs; the
exit code still follows the findings.

## Testing

Every claim is covered by a synthetic fixture so the suite is meaningful
without game data; real-data tests are additional and skip without data
(the previous plan's 464 never-executed tests are the reason for this
rule).

- `tests/test_background_export.py`
  - `manifest_record` fields, `viewed_rooms`, `masks`, `sha256` of known
    pixels, `source: null` for an out-of-range camera — on a stub floor.
  - `draw_polyline`: endpoints set, clipping at every edge, degenerate
    (single point, zero-length) inputs do not raise.
  - `guide_overlay`: red pixels at the scaled mask polygon vertices; output
    shape `(200·S + 12, 320·S, 3)`; a stub camera whose projected hard-col
    corner is known lands within 1px.
  - Data-gated: floor 0 camera 0's projected hard-col corner vs the
    integer path, within the `CameraView` tolerance; every camera of every
    floor exports without raising.
- `tests/test_override_check.py`
  - Temp override dir with a valid 640×400, a greyscale PNG, a 4:3 PNG, a
    160×100 PNG and one missing → exactly `[]`, `invalid`, `aspect`,
    `size`, `missing`, with paths.
  - Same PNG through `AssetResolver` and `check_overrides` agree
    (acceptance parity).
  - Coverage: manifest sha256 match → original; changed pixels →
    regenerated; no manifest → no coverage line.
- `tests/test_tools_graphics_cli.py`
  - `export_backgrounds.main` on a stub data dir: layout, manifest, guide
    sizes, `--floors` filter, refusal without `--force`, exit codes.
  - Round trip: export → `check_overrides.main` reports 0 error findings
    and `regenerated 0`; overwrite one PNG with different pixels →
    `regenerated 1`; exit 1 when one override is greyscale.
  - Data-gated, `SDL_VIDEODRIVER=dummy`: exporting floor 0 then running the
    game's `AssetResolver` with that directory yields a background
    pixel-identical to the un-overridden one.
  - `gl_ctx`-gated: `--proof` writes one side-by-side per overridden
    camera with width `2 · 320 · 4`.

## Non-goals

- Resizing, renaming, cropping or otherwise repairing AI output.
- Regenerating masks, collision, cover zones or palette to match a
  regenerated plate.
- Calling any AI service from this repo (superseded for one tool by
  `2026-08-25-gemini-background-regeneration-design.md`).
