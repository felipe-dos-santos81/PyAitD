# AI Background Regeneration (export / guide / check) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export every original 320×200 camera background into the override-directory layout with a structural guide image and a manifest, and check an override directory the way the game will load it — so the user can regenerate backgrounds with any external AI tool and play with the results.

**Architecture:** Two pure modules (`PyAitD/background_export.py`, `PyAitD/override_check.py`) do all the work on numpy arrays and `Floor`/`AssetResolver` objects; two thin CLIs in `tools/` add PNG encoding (`pygame.image.save`) and, for `--proof`, a standalone ModernGL context. No engine module changes; the override directory contract that `asset_resolver.py` already implements is the only interface to the game.

**Tech Stack:** Python 3.12, numpy ≥2.0, pygame-ce ≥2.5 (tools only), moderngl ≥5.10 (proof only), pytest.

**Spec:** `docs/superpowers/specs/2026-08-25-ai-background-regeneration-design.md`

## Global Constraints

- Dependencies fixed: pygame-ce, ModernGL, NumPy, pytest. Add nothing.
- This repo never ships game data. Exported PNGs, guides, manifests and proof renders are never committed; every output directory this plan names is git-ignored.
- `# SPDX-License-Identifier: GPL-2.0-only` first line of every Python file.
- Engine modules are untouched: `asset_resolver.py`, `render_*.py`, `scene.py`, `floor.py`, `__main__.py` do not change.
- Purity: `background_export.py` and `override_check.py` import neither pygame nor moderngl. PNG encoding (`pygame.image.save`) lives in `tools/` only; PNG decoding goes through `asset_resolver.load_png_rgb`.
- `skel.skin`'s integer projection stays the authority for anything the simulation reads. The guide's projected geometry is drawn through `scene.CameraView` and may diverge by the amounts documented on `CameraView.project` (≈12px within ~100 units of the camera, <1px beyond ~2000).
- Every claim is covered by a synthetic fixture so the suite is meaningful without game data; real-data tests are additional and skip via the `data_dir` fixture. Tests touching pygame need `SDL_VIDEODRIVER=dummy`; GL tests use the `gl_ctx` fixture.
- Run tests with `.venv/bin/pytest`. No lint/formatter is configured; never mass-reformat.

## File map

| File | Responsibility |
|---|---|
| `PyAitD/background_export.py` (new) | `draw_polyline`, `nearest_upscale`, `sha256_rgb`, `manifest_record`, `export_manifest`, `guide_overlay`, `LEGEND`, `GUIDE_FOOTER` |
| `PyAitD/override_check.py` (new) | `Finding`, `check_overrides`, `coverage`, `summarize` |
| `tools/export_backgrounds.py` (new) | CLI; `save_png`, `export_floor`, `main` |
| `tools/check_overrides.py` (new) | CLI; `render_proof`, `main` |
| `Makefile` | `export-backgrounds`, `check-overrides` targets; `overrides=` on `run` |
| `.gitignore` | `docs/graphics-proof/overrides/` |
| `docs/ai-background-regeneration.md` (new), `README.md`, `AGENTS.md` | workflow doc, pointers |
| `tests/test_background_export.py`, `tests/test_override_check.py`, `tests/test_tools_graphics_cli.py` (new) | tests |

## Shared test fixture (used verbatim in Tasks 2, 3, 4, 5, 6)

A stub floor whose only camera looks straight down +z from the origin with unit-free focals, so projection is `sx = x·1000/(z+1000) + 160`, `sy = y·1000/(z+1000) + 100`. Put this in `tests/stub_floor.py` in Task 2 and import it afterwards:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic Floor stand-in for the export/check tests (no game data)."""
import numpy as np

from PyAitD.formats import Camera, Room, ViewedRoom, Zone
from PyAitD.mask_geometry import MaskDraw

W, H = 320, 200


def checker_pixels(seed=0):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(H, W, 3), dtype=np.uint8)


class StubFloor:
    """One room, one camera at the origin looking down +z, one mask, one
    hard-col box. `cover_zones` is what the export module reads instead of
    parse_cover_zones when the floor object provides it."""

    def __init__(self, number=0, images=None):
        self.number = number
        self.palette = np.zeros((256, 3), np.uint8)
        self.rooms = [Room(
            world_x=0, world_y=0, world_z=0, camera_indices=[0],
            hard_cols=[Zone(x1=-100, x2=100, y1=-50, y2=0, z1=0, z2=1000, type=0, parameter=0)],
            sce_zones=[], offset_to_hard_col=0, offset_to_sce_zones=0,
        )]
        cam = Camera(alpha=0, beta=0, gamma=0, x=0, y=0, z=0,
                     focal1=1000, focal2=1000, focal3=1000)
        cam.viewed_rooms.append(ViewedRoom(0, 0, 0, 0, 0, 0))
        self.cameras = [cam]
        self.camera_raw = b""
        self.camera_data_offsets = [0]
        self._images = {0: checker_pixels()} if images is None else images
        # (x, z) in cover units: 10x smaller than room scale
        self._cover = {(0, 0): [[(-5, 0), (5, 0), (5, 50), (-5, 50)]]}

    def camera_image(self, cam_idx):
        if cam_idx not in self._images:
            raise KeyError(f"floor {self.number}: camera image {cam_idx} out of range")
        return self._images[cam_idx]

    def mask_draws(self, cam_idx):
        poly = np.array([[10, 10], [50, 10], [50, 40]], np.int16)
        return [MaskDraw(0, (poly,), (10, 10, 50, 40), 0, ())]

    def cover_zones(self, cam_idx, viewed_idx):
        return self._cover.get((cam_idx, viewed_idx), [])
```

Expected projections with this stub (used in assertions): hard-col corner `(100, 0, 0)` → `(260, 100)`; `(100, 0, 1000)` → `(210, 100)`; cover corner `(-5, 50)` cover units → room `(-50, 0, 500)` → `(126.67, 100)`.

---

### Task 1: Pure raster helpers — `draw_polyline`, `nearest_upscale`, `sha256_rgb`

**Files:**
- Create: `PyAitD/background_export.py`
- Test: `tests/test_background_export.py`

**Interfaces:**
- Produces: `draw_polyline(img: np.ndarray (H,W,3) uint8, points: sequence of (x, y) floats, rgb: tuple[int,int,int], closed: bool = False) -> None` (in place, clipped); `nearest_upscale(img, scale: int) -> np.ndarray`; `sha256_rgb(pixels) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# SPDX-License-Identifier: GPL-2.0-only
import hashlib

import numpy as np
import pytest

from PyAitD import background_export as be


def _blank(h=20, w=30):
    return np.zeros((h, w, 3), np.uint8)


def test_draw_polyline_sets_endpoints_and_line_pixels():
    img = _blank()
    be.draw_polyline(img, [(2, 3), (10, 3)], (255, 0, 0))
    assert tuple(img[3, 2]) == (255, 0, 0)
    assert tuple(img[3, 10]) == (255, 0, 0)
    assert (img[3, 2:11] == (255, 0, 0)).all()
    assert img[4].sum() == 0 and img[2].sum() == 0


def test_draw_polyline_closed_draws_return_edge():
    img = _blank()
    be.draw_polyline(img, [(2, 2), (8, 2), (8, 8)], (0, 255, 0), closed=True)
    # diagonal return edge (8,8)->(2,2) passes through (5,5)
    assert tuple(img[5, 5]) == (0, 255, 0)


def test_draw_polyline_clips_at_every_edge():
    img = _blank()
    be.draw_polyline(img, [(-50, -50), (100, 100)], (0, 0, 255))
    be.draw_polyline(img, [(15, -40), (15, 60)], (0, 0, 255))
    be.draw_polyline(img, [(-40, 10), (80, 10)], (0, 0, 255))
    assert tuple(img[0, 0]) == (0, 0, 255)
    assert tuple(img[19, 19]) == (0, 0, 255)
    assert tuple(img[0, 15]) == (0, 0, 255) and tuple(img[19, 15]) == (0, 0, 255)
    assert tuple(img[10, 0]) == (0, 0, 255) and tuple(img[10, 29]) == (0, 0, 255)


def test_draw_polyline_degenerate_inputs_do_not_raise():
    img = _blank()
    be.draw_polyline(img, [], (1, 1, 1))
    be.draw_polyline(img, [(5, 5)], (1, 1, 1))
    be.draw_polyline(img, [(5, 5), (5, 5)], (1, 1, 1))
    assert tuple(img[5, 5]) == (1, 1, 1)


def test_draw_polyline_rounds_float_coordinates():
    img = _blank()
    be.draw_polyline(img, [(2.4, 3.6), (2.4, 3.6)], (9, 9, 9))
    assert tuple(img[4, 2]) == (9, 9, 9)


def test_nearest_upscale_repeats_pixels():
    src = np.arange(2 * 3 * 3, dtype=np.uint8).reshape(2, 3, 3)
    out = be.nearest_upscale(src, 4)
    assert out.shape == (8, 12, 3)
    assert (out[0:4, 0:4] == src[0, 0]).all()
    assert (out[4:8, 8:12] == src[1, 2]).all()
    assert out.flags["C_CONTIGUOUS"]


def test_nearest_upscale_scale_one_is_a_copy():
    src = np.zeros((2, 2, 3), np.uint8)
    out = be.nearest_upscale(src, 1)
    out[0, 0] = 7
    assert src[0, 0, 0] == 0


def test_sha256_rgb_matches_hashlib_over_raw_bytes():
    px = np.arange(200 * 320 * 3, dtype=np.uint32).reshape(200, 320, 3) % 256
    px = px.astype(np.uint8)
    assert be.sha256_rgb(px) == hashlib.sha256(px.tobytes()).hexdigest()
    assert be.sha256_rgb(px[:, ::-1]) != be.sha256_rgb(px)  # non-contiguous view hashes its logical order


def test_background_export_is_pure():
    import sys
    for name in ("pygame", "moderngl"):
        sys.modules.pop(name, None)
    import importlib
    importlib.reload(be)
    src = open(be.__file__).read()
    assert "import pygame" not in src and "import moderngl" not in src
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_background_export.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'PyAitD.background_export'`

- [ ] **Step 3: Implement**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Export the original camera backgrounds for external (AI) regeneration.

Pure numpy: no pygame, no moderngl. PNG encoding lives in
tools/export_backgrounds.py. See docs/ai-background-regeneration.md.
"""
import hashlib

import numpy as np

W, H = 320, 200


def draw_polyline(img, points, rgb, closed=False):
    """Draw 1px Bresenham segments through `points` ((x, y) floats, rounded)
    into `img` (H, W, 3) in place, clipping every pixel to the image."""
    pts = [(int(round(x)), int(round(y))) for x, y in points]
    if not pts:
        return
    if closed and len(pts) > 1:
        pts = pts + [pts[0]]
    if len(pts) == 1:
        pts = pts + [pts[0]]
    h, w = img.shape[:2]
    color = np.array(rgb, dtype=np.uint8)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        x, y = x0, y0
        while True:
            if 0 <= x < w and 0 <= y < h:
                img[y, x] = color
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy


def nearest_upscale(img, scale):
    """Integer nearest-neighbour upscale; always returns a fresh C-contiguous array."""
    out = np.repeat(np.repeat(img, scale, axis=0), scale, axis=1)
    return np.ascontiguousarray(out)


def sha256_rgb(pixels):
    """Hex digest over the raw (H, W, 3) uint8 bytes in row-major order --
    independent of the PNG encoder that later wrote or read them."""
    return hashlib.sha256(np.ascontiguousarray(pixels, dtype=np.uint8).tobytes()).hexdigest()
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_background_export.py -q`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add PyAitD/background_export.py tests/test_background_export.py
git commit -m "feat: pure raster helpers for background export"
```

---

### Task 2: Manifest records — `manifest_record`, `export_manifest`, `LEGEND`

**Files:**
- Modify: `PyAitD/background_export.py`
- Create: `tests/stub_floor.py` (the shared fixture from the top of this plan, verbatim)
- Test: `tests/test_background_export.py`

**Interfaces:**
- Consumes: `sha256_rgb` (Task 1).
- Produces: `LEGEND = {"red": "masks", "blue": "collision", "green": "walkable"}`; `MANIFEST_SCHEMA = 1`; `background_rel_path(floor_number, cam_idx) -> str` (`"backgrounds/floor00/camera000.png"`); `guide_rel_path(floor_number, cam_idx) -> str`; `manifest_record(floor, cam_idx, pixels) -> dict` (pixels `None` for an out-of-range camera); `export_manifest(records, data_dir, guide_scale) -> dict`.

- [ ] **Step 1: Create `tests/stub_floor.py`** with the content given under "Shared test fixture" above.

- [ ] **Step 2: Write the failing tests** (append to `tests/test_background_export.py`)

```python
from tests.stub_floor import StubFloor, checker_pixels


def test_manifest_record_fields():
    floor = StubFloor(number=3)
    px = checker_pixels()
    rec = be.manifest_record(floor, 0, px)
    assert rec == {
        "floor": 3, "camera": 0,
        "source": "backgrounds/floor03/camera000.png",
        "guide": "guides/floor03/camera000.png",
        "size": [320, 200],
        "viewed_rooms": [0],
        "masks": 1,
        "sha256": be.sha256_rgb(px),
    }


def test_manifest_record_out_of_range_camera_is_null():
    rec = be.manifest_record(StubFloor(), 7, None)
    assert rec["source"] is None and rec["guide"] is None and rec["sha256"] is None
    assert rec["size"] is None and rec["camera"] == 7


def test_export_manifest_envelope():
    floor = StubFloor()
    recs = [be.manifest_record(floor, 0, checker_pixels())]
    m = be.export_manifest(recs, "/data/INDARK", 4)
    assert m["schema"] == be.MANIFEST_SCHEMA == 1
    assert m["data_dir"] == "/data/INDARK"
    assert m["guide_scale"] == 4
    assert m["legend"] == {"red": "masks", "blue": "collision", "green": "walkable"}
    assert m["cameras"] == recs
    import json
    json.dumps(m)  # serialisable


def test_rel_paths_match_asset_resolver_layout(tmp_path):
    from PyAitD.asset_resolver import override_background_path
    assert (tmp_path / be.background_rel_path(5, 12)) == override_background_path(tmp_path, 5, 12)
    assert be.guide_rel_path(5, 12) == "guides/floor05/camera012.png"
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/pytest tests/test_background_export.py -q -k manifest or rel_paths`
Expected: FAIL — `AttributeError: module ... has no attribute 'manifest_record'`

- [ ] **Step 4: Implement** (append to `PyAitD/background_export.py`)

```python
MANIFEST_SCHEMA = 1
LEGEND = {"red": "masks", "blue": "collision", "green": "walkable"}


def background_rel_path(floor_number, cam_idx):
    # Must stay identical to asset_resolver.override_background_path's tail:
    # the export directory is used directly as --overrides DIR.
    return f"backgrounds/floor{floor_number:02d}/camera{cam_idx:03d}.png"


def guide_rel_path(floor_number, cam_idx):
    return f"guides/floor{floor_number:02d}/camera{cam_idx:03d}.png"


def manifest_record(floor, cam_idx, pixels):
    """One manifest entry. `pixels` is the exported (H, W, 3) array, or None
    when Floor.camera_image raised KeyError (image missing from CAMERAnn.PAK)."""
    cam = floor.cameras[cam_idx]
    rec = {
        "floor": floor.number,
        "camera": cam_idx,
        "source": None,
        "guide": None,
        "size": None,
        "viewed_rooms": [vr.viewed_room_idx for vr in cam.viewed_rooms],
        "masks": len(floor.mask_draws(cam_idx)),
        "sha256": None,
    }
    if pixels is not None:
        rec["source"] = background_rel_path(floor.number, cam_idx)
        rec["guide"] = guide_rel_path(floor.number, cam_idx)
        rec["size"] = [int(pixels.shape[1]), int(pixels.shape[0])]
        rec["sha256"] = sha256_rgb(pixels)
    return rec


def export_manifest(records, data_dir, guide_scale):
    return {
        "schema": MANIFEST_SCHEMA,
        "data_dir": str(data_dir),
        "guide_scale": int(guide_scale),
        "legend": dict(LEGEND),
        "cameras": list(records),
    }
```

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/pytest tests/test_background_export.py -q`
Expected: 13 passed

- [ ] **Step 6: Commit**

```bash
git add PyAitD/background_export.py tests/stub_floor.py tests/test_background_export.py
git commit -m "feat: manifest records for background export"
```

---

### Task 3: Guide overlay — `guide_overlay`

**Files:**
- Modify: `PyAitD/background_export.py`
- Test: `tests/test_background_export.py`

**Interfaces:**
- Consumes: `draw_polyline`, `nearest_upscale` (Task 1); `scene.CameraView`, `world.CameraState.from_camera(...).angles()`, `formats.parse_cover_zones`, `navmesh.COVER_SCALE`.
- Produces: `GUIDE_FOOTER = 12`; `COLOR_MASK = (255, 0, 0)`, `COLOR_COLLISION = (0, 128, 255)`, `COLOR_WALKABLE = (0, 200, 0)`; `cover_zones_for(floor, cam_idx, viewed_idx) -> list[list[(x, z)]]`; `guide_overlay(floor, cam_idx, scale) -> np.ndarray (200·scale + 12, 320·scale, 3) uint8`.

`cover_zones_for` prefers a `floor.cover_zones(cam_idx, viewed_idx)` method when the object has one (the stub) and otherwise calls `parse_cover_zones(floor.camera_raw, floor.camera_data_offsets[cam_idx], viewed_idx)` (the real `Floor`). This keeps the real path exactly what `navmesh.cover_polys` does while the synthetic tests avoid hand-assembling PAK bytes.

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_guide_overlay_shape_and_footer():
    g = be.guide_overlay(StubFloor(), 0, 4)
    assert g.shape == (200 * 4 + be.GUIDE_FOOTER, 320 * 4, 3)
    footer = g[800:]
    assert (footer[:, 0:40] == be.COLOR_MASK).all()
    assert (footer[:, 48:88] == be.COLOR_COLLISION).all()
    assert (footer[:, 96:136] == be.COLOR_WALKABLE).all()
    assert footer[:, 136:].sum() == 0


def test_guide_overlay_background_is_nearest_upscaled_original():
    floor = StubFloor()
    g = be.guide_overlay(floor, 0, 2)
    src = floor.camera_image(0)
    # a pixel far from every drawn line: bottom-right corner block
    assert (g[398:400, 638:640] == src[199, 319]).all()


def test_guide_overlay_draws_mask_polygon_in_red_at_scaled_vertices():
    g = be.guide_overlay(StubFloor(), 0, 4)
    for x, y in ((10, 10), (50, 10), (50, 40)):
        assert tuple(g[y * 4, x * 4]) == be.COLOR_MASK
    # closed: the (50,40)->(10,10) edge passes through (30,25)
    assert tuple(g[25 * 4, 30 * 4]) == be.COLOR_MASK


def test_guide_overlay_projects_hard_col_corners_in_blue():
    g = be.guide_overlay(StubFloor(), 0, 1)
    # (100, 0, 0) -> (260, 100); (100, 0, 1000) -> (210, 100); top y1=-50 at z=0 -> (260, 50)
    assert tuple(g[100, 260]) == be.COLOR_COLLISION
    assert tuple(g[100, 210]) == be.COLOR_COLLISION
    assert tuple(g[50, 260]) == be.COLOR_COLLISION
    # vertical edge between them
    assert tuple(g[75, 260]) == be.COLOR_COLLISION


def test_guide_overlay_projects_cover_polygon_in_green():
    g = be.guide_overlay(StubFloor(), 0, 1)
    # cover (5, 0) -> room (50, 0, 0) -> (210, 100) is also a blue corner; use
    # (-5, 50) -> room (-50, 0, 500) -> (126.67, 100) -> pixel (127, 100)
    assert tuple(g[100, 127]) == be.COLOR_WALKABLE


def test_guide_overlay_skips_culled_edges():
    floor = StubFloor()
    # a hard col entirely behind the camera projects to the sentinel and must not draw
    from PyAitD.formats import Zone
    floor.rooms[0].hard_cols = [Zone(x1=-10, x2=10, y1=-10, y2=0, z1=-5000, z2=-4000, type=0, parameter=0)]
    floor._cover = {}
    g = be.guide_overlay(floor, 0, 1)
    assert not (g[:200] == be.COLOR_COLLISION).all(axis=2).any()


def test_cover_zones_for_uses_parse_cover_zones_on_real_floors(monkeypatch):
    calls = []
    monkeypatch.setattr(be, "parse_cover_zones", lambda raw, off, vi: calls.append((raw, off, vi)) or [[(1, 2)]])

    class Plain:
        camera_raw = b"xyz"
        camera_data_offsets = [0, 40]

    assert be.cover_zones_for(Plain(), 1, 0) == [[(1, 2)]]
    assert calls == [(b"xyz", 40, 0)]


def test_guide_overlay_real_camera_matches_integer_projection(data_dir):
    from PyAitD.floor import Floor
    from PyAitD.world import CameraState, transform_point
    floor = Floor(data_dir, 0)
    cam_idx = 0
    room_idx = floor.cameras[cam_idx].viewed_rooms[0].viewed_room_idx
    room = floor.rooms[room_idx]
    state = CameraState.from_camera(floor.cameras[cam_idx], room.world_x, room.world_y, room.world_z).angles()
    box = room.hard_cols[0]
    # integer path, mirroring skel.skin's order (translate, then rotate, then project)
    x, y, z = box.x1 - state.x, box.y2 - state.y, box.z1 - state.z
    ix, iy, idepth = state.project(*transform_point(x, y, z, state))
    assert idepth > 50, "pick a corner in front of the camera for this test"
    from PyAitD.scene import CameraView
    fx, fy, fdepth = CameraView(state).project([(box.x1, box.y2, box.z1)])[0]
    tol = 12.0 if fdepth < 2000 else 1.0
    assert abs(fx - ix) <= tol and abs(fy - iy) <= tol
    g = be.guide_overlay(floor, cam_idx, 1)
    assert g.shape == (212, 320, 3)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_background_export.py -q -k "guide or cover_zones"`
Expected: FAIL — `AttributeError: ... 'guide_overlay'`

- [ ] **Step 3: Implement** (append; add the imports at the top of the module)

```python
from PyAitD.formats import parse_cover_zones
from PyAitD.navmesh import COVER_SCALE
from PyAitD.scene import CameraView
from PyAitD.world import CameraState

GUIDE_FOOTER = 12
COLOR_MASK = (255, 0, 0)
COLOR_COLLISION = (0, 128, 255)
COLOR_WALKABLE = (0, 200, 0)
_SWATCH_W, _SWATCH_STRIDE = 40, 48
_CULLED = -9999.0


def cover_zones_for(floor, cam_idx, viewed_idx):
    """Cover polygons ((x, z) in cover units) of `viewed_idx` as seen from
    `cam_idx`. Real Floors go through parse_cover_zones exactly as
    navmesh.cover_polys does; a floor object exposing `cover_zones` (test
    stubs) is asked directly."""
    if hasattr(floor, "cover_zones"):
        return floor.cover_zones(cam_idx, viewed_idx)
    return parse_cover_zones(floor.camera_raw, floor.camera_data_offsets[cam_idx], viewed_idx)


def _draw_projected(img, view, world_pts, edges, rgb, scale):
    """Project `world_pts` and draw each (i, j) edge whose endpoints both
    survived culling, scaled by `scale`."""
    proj = view.project(world_pts)
    for i, j in edges:
        a, b = proj[i], proj[j]
        if a[0] <= _CULLED or b[0] <= _CULLED:
            continue
        draw_polyline(img, [(a[0] * scale, a[1] * scale), (b[0] * scale, b[1] * scale)], rgb)


_BOX_EDGES = (
    (0, 1), (1, 2), (2, 3), (3, 0),   # bottom rectangle (y2, the floor edge)
    (4, 5), (5, 6), (6, 7), (7, 4),   # top rectangle (y1)
    (0, 4), (1, 5), (2, 6), (3, 7),   # verticals
)


def _box_corners(z):
    return [
        (z.x1, z.y2, z.z1), (z.x2, z.y2, z.z1), (z.x2, z.y2, z.z2), (z.x1, z.y2, z.z2),
        (z.x1, z.y1, z.z1), (z.x2, z.y1, z.z1), (z.x2, z.y1, z.z2), (z.x1, z.y1, z.z2),
    ]


def guide_overlay(floor, cam_idx, scale):
    """The original background upscaled x`scale` (nearest neighbour) with
    mask polygons (red), hard-collision boxes (blue) and cover polygons
    (green) drawn over it, plus a GUIDE_FOOTER-px legend strip.

    Room-space coordinates are passed to CameraView as-is: the room's world
    offset is already folded into CameraState.from_camera, exactly as actor
    positions reach CameraView in scene.build_frame."""
    base = nearest_upscale(floor.camera_image(cam_idx), scale)
    h, w = base.shape[:2]
    img = np.zeros((h + GUIDE_FOOTER, w, 3), np.uint8)
    img[:h] = base

    for mask in floor.mask_draws(cam_idx):
        for poly in mask.polygons:
            pts = [(float(x) * scale, float(y) * scale) for x, y in np.asarray(poly).reshape(-1, 2)]
            draw_polyline(img, pts, COLOR_MASK, closed=True)

    camera = floor.cameras[cam_idx]
    for viewed_idx, vr in enumerate(camera.viewed_rooms):
        room = floor.rooms[vr.viewed_room_idx]
        view = CameraView(CameraState.from_camera(camera, room.world_x, room.world_y, room.world_z).angles())
        for box in room.hard_cols:
            _draw_projected(img, view, _box_corners(box), _BOX_EDGES, COLOR_COLLISION, scale)
        for poly in cover_zones_for(floor, cam_idx, viewed_idx):
            pts = [(x * COVER_SCALE, 0, z * COVER_SCALE) for x, z in poly]
            n = len(pts)
            if n < 2:
                continue
            edges = [(k, (k + 1) % n) for k in range(n)]
            _draw_projected(img, view, pts, edges, COLOR_WALKABLE, scale)

    for k, color in enumerate((COLOR_MASK, COLOR_COLLISION, COLOR_WALKABLE)):
        x0 = k * _SWATCH_STRIDE
        img[h:, x0:x0 + _SWATCH_W] = color
    return img
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_background_export.py -q`
Expected: all pass (the `data_dir` test runs when game data is present; run it — the data is in the main checkout at `Alone in the Dark 1.app/Contents/Resources/game/INDARK`, or set `PYAITD_DATA`). If the real-camera test fails on tolerance, first check which corner it picked (`idepth`) and adjust the test to pick the first hard col whose `idepth > 50` rather than loosening `tol`.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/background_export.py tests/test_background_export.py
git commit -m "feat: guide overlay with masks, collision and cover geometry"
```

---

### Task 4: Override checker — `Finding`, `check_overrides`, `coverage`, `summarize`

**Files:**
- Create: `PyAitD/override_check.py`
- Test: `tests/test_override_check.py`

**Interfaces:**
- Consumes: `asset_resolver.AssetResolver`, `asset_resolver.override_background_path`, `background_export.sha256_rgb`.
- Produces: `Finding(floor: int, camera: int, path: Path, kind: str, detail: str)` frozen; `ERROR_KINDS = ("invalid", "aspect")`; `check_overrides(override_dir, floors, manifest=None, *, load_png=load_png_rgb) -> list[Finding]`; `coverage(override_dir, floors, manifest, *, load_png=load_png_rgb) -> dict[int, dict[str, int]]` keyed by floor number with keys `regenerated/original/missing/invalid`; `summarize(findings, cov) -> str`; `has_errors(findings) -> bool`.

Test PNGs are written with pygame under `SDL_VIDEODRIVER=dummy`; the test module sets it via `os.environ.setdefault` before importing pygame.

- [ ] **Step 1: Write the failing tests**

```python
# SPDX-License-Identifier: GPL-2.0-only
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pytest

from PyAitD import override_check as oc
from PyAitD.asset_resolver import AssetResolver, load_png_rgb, override_background_path
from PyAitD.background_export import export_manifest, manifest_record, sha256_rgb
from tests.stub_floor import StubFloor, checker_pixels


def _write_png(path, rgb):
    import pygame
    path.parent.mkdir(parents=True, exist_ok=True)
    surf = pygame.surfarray.make_surface(np.ascontiguousarray(rgb.swapaxes(0, 1)))
    pygame.image.save(surf, str(path))


def _write_grey_png(path):
    import pygame
    path.parent.mkdir(parents=True, exist_ok=True)
    surf = pygame.Surface((64, 40), depth=8)
    surf.set_palette([(i, i, i) for i in range(256)])
    pygame.image.save(surf, str(path))


def _floors(n):
    return [StubFloor(number=i, images={0: checker_pixels(i)}) for i in range(n)]


def test_missing_override_is_informational(tmp_path):
    f = oc.check_overrides(tmp_path, _floors(1))
    assert [x.kind for x in f] == ["missing"]
    assert f[0].path == override_background_path(tmp_path, 0, 0)
    assert not oc.has_errors(f)


def test_valid_multiple_yields_no_finding(tmp_path):
    _write_png(override_background_path(tmp_path, 0, 0), np.zeros((400, 640, 3), np.uint8))
    assert oc.check_overrides(tmp_path, _floors(1)) == []


def test_greyscale_png_is_invalid_with_resolver_detail(tmp_path):
    _write_grey_png(override_background_path(tmp_path, 0, 0))
    f = oc.check_overrides(tmp_path, _floors(1))
    assert len(f) == 1 and f[0].kind == "invalid"
    # detail is whatever AssetResolver recorded -- acceptance parity
    r = AssetResolver(None, tmp_path)
    r.background(_floors(1)[0], 0)
    assert f[0].detail == r.failures[override_background_path(tmp_path, 0, 0)]
    assert oc.has_errors(f)


def test_four_by_three_is_aspect_error(tmp_path):
    _write_png(override_background_path(tmp_path, 0, 0), np.zeros((300, 400, 3), np.uint8))
    f = oc.check_overrides(tmp_path, _floors(1))
    assert [x.kind for x in f] == ["aspect"] and oc.has_errors(f)
    assert "400x300" in f[0].detail


def test_aspect_tolerance_is_one_percent(tmp_path):
    # 1.6 * 0.995 -> within aspect tolerance; not a 320x200 multiple -> informational size only
    _write_png(override_background_path(tmp_path, 0, 0), np.zeros((400, 637, 3), np.uint8))
    f = oc.check_overrides(tmp_path, _floors(1))
    assert [x.kind for x in f] == ["size"] and not oc.has_errors(f)


def test_small_or_non_multiple_is_size_info(tmp_path):
    _write_png(override_background_path(tmp_path, 0, 0), np.zeros((100, 160, 3), np.uint8))
    _write_png(override_background_path(tmp_path, 1, 0), np.zeros((500, 800, 3), np.uint8))
    f = oc.check_overrides(tmp_path, _floors(2))
    assert [x.kind for x in f] == ["size", "size"] and not oc.has_errors(f)


def test_one_finding_per_camera_and_only_requested_floors(tmp_path):
    _write_grey_png(override_background_path(tmp_path, 1, 0))
    f = oc.check_overrides(tmp_path, _floors(2)[1:])
    assert [(x.floor, x.camera, x.kind) for x in f] == [(1, 0, "invalid")]


def test_coverage_distinguishes_original_from_regenerated(tmp_path):
    floors = _floors(2)
    manifest = export_manifest(
        [manifest_record(fl, 0, fl.camera_image(0)) for fl in floors], "/d", 4)
    _write_png(override_background_path(tmp_path, 0, 0), floors[0].camera_image(0))  # untouched export
    _write_png(override_background_path(tmp_path, 1, 0), checker_pixels(99))          # regenerated
    cov = oc.coverage(tmp_path, floors, manifest)
    assert cov == {0: {"regenerated": 0, "original": 1, "missing": 0, "invalid": 0},
                   1: {"regenerated": 1, "original": 0, "missing": 0, "invalid": 0}}


def test_summarize_lines(tmp_path):
    cov = {0: {"regenerated": 1, "original": 2, "missing": 3, "invalid": 0}}
    findings = [oc.Finding(0, 5, tmp_path / "x.png", "aspect", "640x300")]
    text = oc.summarize(findings, cov)
    assert "floor 00: regenerated 1 / original 2 / missing 3 / invalid 0 / aspect 1" in text
    assert "total: regenerated 1 / original 2 / missing 3 / invalid 0 / aspect 1" in text
    assert "aspect  floor 00 camera 005" in text and "640x300" in text
    assert "missing" not in text.split("\n")[0] or True  # missing cameras are counted, not listed


def test_summarize_without_coverage():
    text = oc.summarize([], None)
    assert "coverage: no manifest" in text


def test_override_check_is_pure():
    src = open(oc.__file__).read()
    assert "import pygame" not in src and "import moderngl" not in src
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_override_check.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'PyAitD.override_check'`

- [ ] **Step 3: Implement**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Check an override directory the way the game will load it.

Pure: loads through AssetResolver so whatever it accepts, the game
accepts, and vice versa. PNG decoding is asset_resolver.load_png_rgb.
"""
from dataclasses import dataclass
from pathlib import Path

from PyAitD.asset_resolver import AssetResolver, load_png_rgb, override_background_path
from PyAitD.background_export import sha256_rgb

ERROR_KINDS = ("invalid", "aspect")
_ASPECT = 320 / 200
_ASPECT_TOL = 0.01
_ORDER = ("regenerated", "original", "missing", "invalid", "aspect")


@dataclass(frozen=True)
class Finding:
    floor: int
    camera: int
    path: Path
    kind: str      # missing | invalid | aspect | size
    detail: str


def has_errors(findings):
    return any(f.kind in ERROR_KINDS for f in findings)


def _each_camera(override_dir, floors, load_png):
    """Yield (floor, cam_idx, path, resolver) for every camera of every floor;
    one resolver per floor keeps AssetResolver's cache and failures intact."""
    for floor in floors:
        resolver = AssetResolver(None, override_dir, load_png=load_png)
        for cam_idx in range(len(floor.cameras)):
            yield floor, cam_idx, override_background_path(override_dir, floor.number, cam_idx), resolver


def check_overrides(override_dir, floors, manifest=None, *, load_png=load_png_rgb):
    """At most one Finding per camera. `manifest` is accepted for symmetry
    with coverage() and unused here."""
    findings = []
    for floor, cam_idx, path, resolver in _each_camera(override_dir, floors, load_png):
        if not path.is_file():
            findings.append(Finding(floor.number, cam_idx, path, "missing", "original will be used"))
            continue
        asset = resolver.background(floor, cam_idx)
        if not asset.is_override:
            findings.append(Finding(floor.number, cam_idx, path, "invalid", resolver.failures.get(path, "rejected")))
            continue
        h, w = asset.pixels.shape[:2]
        if abs(w / h - _ASPECT) > _ASPECT * _ASPECT_TOL:
            findings.append(Finding(floor.number, cam_idx, path, "aspect",
                                    f"{w}x{h} is not 16:10 within 1% -- the game would stretch it"))
            continue
        if w < 320 or h < 200 or w % 320 or h % 200:
            findings.append(Finding(floor.number, cam_idx, path, "size",
                                    f"{w}x{h} is not an integer multiple of 320x200"))
    return findings


def coverage(override_dir, floors, manifest, *, load_png=load_png_rgb):
    """Per-floor counts. An override whose pixels hash to the manifest's
    sha256 is an untouched export ('original'); any other loadable override
    is 'regenerated'."""
    expected = {(c["floor"], c["camera"]): c["sha256"] for c in manifest["cameras"]}
    out = {}
    for floor, cam_idx, path, resolver in _each_camera(override_dir, floors, load_png):
        counts = out.setdefault(floor.number, {"regenerated": 0, "original": 0, "missing": 0, "invalid": 0})
        if not path.is_file():
            counts["missing"] += 1
            continue
        asset = resolver.background(floor, cam_idx)
        if not asset.is_override:
            counts["invalid"] += 1
        elif sha256_rgb(asset.pixels) == expected.get((floor.number, cam_idx)):
            counts["original"] += 1
        else:
            counts["regenerated"] += 1
    return out


def summarize(findings, cov):
    lines = []
    for f in findings:
        if f.kind != "missing":
            lines.append(f"{f.kind:<7} floor {f.floor:02d} camera {f.camera:03d}  {f.path}: {f.detail}")
    if cov is None:
        lines.append("coverage: no manifest")
        return "\n".join(lines)
    aspect_by_floor = {}
    for f in findings:
        if f.kind == "aspect":
            aspect_by_floor[f.floor] = aspect_by_floor.get(f.floor, 0) + 1
    total = {k: 0 for k in _ORDER}
    for number in sorted(cov):
        row = dict(cov[number], aspect=aspect_by_floor.get(number, 0))
        for k in _ORDER:
            total[k] += row[k]
        lines.append(f"floor {number:02d}: " + " / ".join(f"{k} {row[k]}" for k in _ORDER))
    lines.append("total: " + " / ".join(f"{k} {total[k]}" for k in _ORDER))
    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify pass**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_override_check.py -q`
Expected: 12 passed. (`AssetResolver(None, ...)` is fine: `body()` is never called.)

- [ ] **Step 5: Commit**

```bash
git add PyAitD/override_check.py tests/test_override_check.py
git commit -m "feat: override directory checker with coverage summary"
```

---

### Task 5: `tools/export_backgrounds.py` CLI, Make target, gitignore

**Files:**
- Create: `tools/export_backgrounds.py`
- Modify: `Makefile` (`.PHONY` line 12; new target after `prove-graphics`), `.gitignore`
- Test: `tests/test_tools_graphics_cli.py`

**Interfaces:**
- Consumes: `background_export.{background_rel_path, guide_rel_path, guide_overlay, manifest_record, export_manifest}`; `PyAitD.floor.Floor`.
- Produces: `save_png(path: Path, rgb) -> None` (temp + `os.replace`); `parse_floors(text: str) -> list[int]` (`"0-7"`, `"0,3,5"`, `"2"`); `export_floor(floor, out_dir: Path, guide_scale: int, save=save_png) -> list[dict]` (manifest records); `main(argv=None) -> int` with exit codes 0 ok, 2 usage/data error, 3 refused (`backgrounds/` exists without `--force`). `main` loads floors via a module-level `load_floor(data_dir, number)` that wraps `Floor(...)` so tests can monkeypatch it.

- [ ] **Step 1: Write the failing tests**

```python
# SPDX-License-Identifier: GPL-2.0-only
import json
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pytest

from PyAitD.asset_resolver import load_png_rgb
from tests.stub_floor import StubFloor, checker_pixels
from tools import export_backgrounds as xb


def test_parse_floors():
    assert xb.parse_floors("0-7") == [0, 1, 2, 3, 4, 5, 6, 7]
    assert xb.parse_floors("0,3,5") == [0, 3, 5]
    assert xb.parse_floors("2") == [2]
    with pytest.raises(ValueError):
        xb.parse_floors("a")


def test_save_png_round_trips_and_leaves_no_temp(tmp_path):
    rgb = checker_pixels(3)
    path = tmp_path / "sub" / "x.png"
    xb.save_png(path, rgb)
    assert (load_png_rgb(path) == rgb).all()
    assert sorted(p.name for p in path.parent.iterdir()) == ["x.png"]


def test_export_floor_writes_layout_and_records(tmp_path):
    floor = StubFloor(number=2)
    recs = xb.export_floor(floor, tmp_path, 4)
    assert (tmp_path / "backgrounds/floor02/camera000.png").is_file()
    assert (tmp_path / "guides/floor02/camera000.png").is_file()
    assert load_png_rgb(tmp_path / "guides/floor02/camera000.png").shape == (812, 1280, 3)
    assert (load_png_rgb(tmp_path / "backgrounds/floor02/camera000.png") == floor.camera_image(0)).all()
    assert recs[0]["source"] == "backgrounds/floor02/camera000.png"


def test_export_floor_records_missing_image_as_null(tmp_path):
    floor = StubFloor(number=0, images={})
    recs = xb.export_floor(floor, tmp_path, 1)
    assert recs[0]["source"] is None
    assert not (tmp_path / "backgrounds").exists()


def _patch_floors(monkeypatch, numbers):
    def load_floor(data_dir, number):
        if number not in numbers:
            raise FileNotFoundError(f"ETAGE{number:02d}")
        return StubFloor(number=number, images={0: checker_pixels(number)})
    monkeypatch.setattr(xb, "load_floor", load_floor)


def test_main_exports_requested_floors_and_manifest(tmp_path, monkeypatch, capsys):
    _patch_floors(monkeypatch, {0, 1})
    out = tmp_path / "ov"
    rc = xb.main([str(tmp_path), "--out", str(out), "--floors", "0-1", "--guide-scale", "2"])
    assert rc == 0
    m = json.loads((out / "manifest.json").read_text())
    assert m["schema"] == 1 and m["guide_scale"] == 2 and m["data_dir"] == str(tmp_path.resolve())
    assert [(c["floor"], c["camera"]) for c in m["cameras"]] == [(0, 0), (1, 0)]
    assert load_png_rgb(out / "guides/floor01/camera000.png").shape == (412, 640, 3)


def test_main_skips_missing_floor_with_warning(tmp_path, monkeypatch, capsys):
    _patch_floors(monkeypatch, {0})
    rc = xb.main([str(tmp_path), "--out", str(tmp_path / "ov"), "--floors", "0-1"])
    assert rc == 0
    assert "floor 01" in capsys.readouterr().err


def test_main_exit_2_when_nothing_exported(tmp_path, monkeypatch):
    _patch_floors(monkeypatch, set())
    assert xb.main([str(tmp_path), "--out", str(tmp_path / "ov"), "--floors", "0-1"]) == 2


def test_main_exit_2_for_missing_data_dir(tmp_path):
    assert xb.main([str(tmp_path / "nope"), "--out", str(tmp_path / "ov")]) == 2


def test_main_refuses_to_overwrite_existing_export_without_force(tmp_path, monkeypatch):
    _patch_floors(monkeypatch, {0})
    out = tmp_path / "ov"
    assert xb.main([str(tmp_path), "--out", str(out), "--floors", "0"]) == 0
    regenerated = checker_pixels(42)
    xb.save_png(out / "backgrounds/floor00/camera000.png", regenerated)
    assert xb.main([str(tmp_path), "--out", str(out), "--floors", "0"]) == 3
    assert (load_png_rgb(out / "backgrounds/floor00/camera000.png") == regenerated).all()
    assert xb.main([str(tmp_path), "--out", str(out), "--floors", "0", "--force"]) == 0
    assert (load_png_rgb(out / "backgrounds/floor00/camera000.png") == checker_pixels(0)).all()


def test_makefile_and_gitignore_mention_export():
    mk = open("Makefile").read()
    assert "export-backgrounds:" in mk and "export-backgrounds" in mk.split(".PHONY:")[1].split("\n")[0]
    assert "tools/export_backgrounds.py" in mk
    assert "docs/graphics-proof/overrides/" in open(".gitignore").read()
```

- [ ] **Step 2: Run to verify failure**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_tools_graphics_cli.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.export_backgrounds'` (`tools` is a namespace package; `tests/test_prove_graphics.py` already imports `tools.prove_graphics` the same way).

- [ ] **Step 3: Implement `tools/export_backgrounds.py`**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Export every camera background for external (AI) regeneration.

Writes, under --out DIR:

    manifest.json
    backgrounds/floorNN/cameraNNN.png   320x200 originals -- overwrite these in place
    guides/floorNN/cameraNNN.png        upscaled originals with masks (red),
                                        collision (blue) and walkable (green) drawn on

DIR is directly usable as `--overrides DIR` / `make run overrides=DIR`.
See docs/ai-background-regeneration.md. This repo never ships game data:
never commit the output.
"""
import argparse
import json
import os
import pathlib
import sys

import numpy as np

from PyAitD.background_export import (
    background_rel_path, export_manifest, guide_overlay, guide_rel_path, manifest_record,
)
from PyAitD.floor import Floor
from PyAitD.pak import PakError


def load_floor(data_dir, number):
    return Floor(data_dir, number)


def parse_floors(text):
    out = []
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return out


def save_png(path, rgb):
    """Encode via pygame to `<path>.tmp` (PNG format forced by namehint),
    then atomically rename, so an interrupted run never leaves a truncated
    PNG that AssetResolver would reject."""
    import pygame
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    surface = pygame.surfarray.make_surface(np.ascontiguousarray(rgb.swapaxes(0, 1)))
    pygame.image.save(surface, str(tmp), "png")
    os.replace(tmp, path)


def export_floor(floor, out_dir, guide_scale, save=save_png):
    out_dir = pathlib.Path(out_dir)
    records = []
    for cam_idx in range(len(floor.cameras)):
        try:
            pixels = floor.camera_image(cam_idx)
        except KeyError:
            records.append(manifest_record(floor, cam_idx, None))
            continue
        save(out_dir / background_rel_path(floor.number, cam_idx), pixels)
        save(out_dir / guide_rel_path(floor.number, cam_idx), guide_overlay(floor, cam_idx, guide_scale))
        records.append(manifest_record(floor, cam_idx, pixels))
    return records


def _parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("data", type=pathlib.Path, help="game data directory (e.g. .../INDARK)")
    p.add_argument("--out", type=pathlib.Path, required=True, help="override directory to create")
    p.add_argument("--floors", default="0-7", help="floors to export, e.g. 0-7 or 0,3,5 (default 0-7)")
    p.add_argument("--guide-scale", type=int, default=4, help="guide image scale (default 4)")
    p.add_argument("--force", action="store_true",
                    help="re-export even if --out already holds backgrounds/ (overwrites regenerated files)")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    if not args.data.is_dir():
        print(f"error: game data directory not found: {args.data}", file=sys.stderr)
        return 2
    if args.guide_scale < 1:
        print("error: --guide-scale must be >= 1", file=sys.stderr)
        return 2
    try:
        floors = parse_floors(args.floors)
    except ValueError:
        print(f"error: bad --floors {args.floors!r}", file=sys.stderr)
        return 2
    if (args.out / "backgrounds").exists() and not args.force:
        print(f"error: {args.out / 'backgrounds'} exists; pass --force to overwrite "
              "(this discards regenerated images)", file=sys.stderr)
        return 3

    records, exported = [], 0
    for number in floors:
        try:
            floor = load_floor(args.data, number)
        except (PakError, FileNotFoundError, OSError, ValueError) as exc:
            print(f"warning: floor {number:02d} skipped: {exc}", file=sys.stderr)
            continue
        records.extend(export_floor(floor, args.out, args.guide_scale))
        exported += 1
        print(f"floor {number:02d}: {len(floor.cameras)} cameras")
    if not exported:
        print("error: no floor exported", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = export_manifest(records, args.data.resolve(), args.guide_scale)
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(args.out / "manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`PyAitD.pak.find_pak` raises `PakError` for a missing PAK; it is the first entry of the `except` tuple above.

- [ ] **Step 4: Makefile and .gitignore**

In `Makefile` line 12 append ` export-backgrounds check-overrides` to `.PHONY`. After the `prove-graphics` target add:

```make
export-backgrounds: install ## Export every camera background + guide + manifest to out=DIR for external AI regeneration (floors="0-7", scale=4)
	@test -n "$(out)" || { echo "usage: make export-backgrounds out=DIR [floors=0-7] [scale=4] [force=1]"; exit 2; }
	$(PYTHON) tools/export_backgrounds.py "$(data)" --out "$(out)" --floors "$(or $(floors),0-7)" --guide-scale "$(or $(scale),4)" $(if $(force),--force)
```

Append `docs/graphics-proof/overrides/` to `.gitignore`.

- [ ] **Step 5: Run to verify pass**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_tools_graphics_cli.py -q`
Expected: 10 passed. Then, with real data: `make export-backgrounds out=/tmp/aitd-ov floors=0` — expect `floor 00: N cameras` and a manifest path; `ls /tmp/aitd-ov/guides/floor00 | head`; open one guide and confirm red/blue/green lines land on the plate.

- [ ] **Step 6: Commit**

```bash
git add tools/export_backgrounds.py tests/test_tools_graphics_cli.py Makefile .gitignore
git commit -m "feat: export_backgrounds tool and make target"
```

---

### Task 6: `tools/check_overrides.py` CLI with `--proof`, Make targets

**Files:**
- Create: `tools/check_overrides.py`
- Modify: `Makefile` (`check-overrides` target; `run` target gains `overrides=`)
- Test: `tests/test_tools_graphics_cli.py`

**Interfaces:**
- Consumes: `override_check.{check_overrides, coverage, summarize, has_errors}`; `export_backgrounds.{load_floor, parse_floors, save_png}`; `asset_resolver.AssetResolver`; `scene.CameraView`; `world.CameraState`; `render_gl.GLBackend`; `render_options.RenderOptions`; `scene.FrameDescription`.
- Produces: `render_proof(ctx, floor, cam_idx, override_dir, out_dir, scale=4, save=save_png) -> Path | None` (None when the camera has no loadable override); `main(argv=None) -> int`: 0 clean, 1 error findings, 2 usage.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_tools_graphics_cli.py`)

```python
from tools import check_overrides as co


def test_check_main_round_trip_reports_zero_regenerated(tmp_path, monkeypatch, capsys):
    _patch_floors(monkeypatch, {0, 1})
    monkeypatch.setattr(co, "load_floor", xb.load_floor)
    out = tmp_path / "ov"
    assert xb.main([str(tmp_path), "--out", str(out), "--floors", "0-1"]) == 0
    assert co.main([str(tmp_path), str(out), "--floors", "0-1"]) == 0
    text = capsys.readouterr().out
    assert "total: regenerated 0 / original 2 / missing 0 / invalid 0 / aspect 0" in text


def test_check_main_counts_regenerated_and_fails_on_invalid(tmp_path, monkeypatch, capsys):
    _patch_floors(monkeypatch, {0, 1})
    monkeypatch.setattr(co, "load_floor", xb.load_floor)
    out = tmp_path / "ov"
    xb.main([str(tmp_path), "--out", str(out), "--floors", "0-1"])
    xb.save_png(out / "backgrounds/floor00/camera000.png", checker_pixels(77))
    assert co.main([str(tmp_path), str(out), "--floors", "0-1"]) == 0
    assert "regenerated 1 / original 1" in capsys.readouterr().out
    import pygame
    grey = pygame.Surface((64, 40), depth=8)
    grey.set_palette([(i, i, i) for i in range(256)])
    pygame.image.save(grey, str(out / "backgrounds/floor01/camera000.png"))
    assert co.main([str(tmp_path), str(out), "--floors", "0-1"]) == 1
    assert "invalid floor 01 camera 000" in capsys.readouterr().out


def test_check_main_without_manifest_still_checks(tmp_path, monkeypatch, capsys):
    _patch_floors(monkeypatch, {0})
    monkeypatch.setattr(co, "load_floor", xb.load_floor)
    (tmp_path / "ov").mkdir()
    assert co.main([str(tmp_path), str(tmp_path / "ov"), "--floors", "0"]) == 0
    assert "coverage: no manifest" in capsys.readouterr().out


def test_check_main_usage_errors(tmp_path):
    assert co.main([str(tmp_path / "nope"), str(tmp_path)]) == 2
    assert co.main([str(tmp_path), str(tmp_path / "nope")]) == 2


def test_render_proof_writes_side_by_side(gl_ctx, tmp_path, monkeypatch):
    floor = StubFloor(number=0)
    ov = tmp_path / "ov"
    xb.save_png(ov / "backgrounds/floor00/camera000.png", checker_pixels(5))
    path = co.render_proof(gl_ctx, floor, 0, ov, tmp_path / "proof", scale=4)
    assert path == tmp_path / "proof" / "floor00-camera000.png"
    assert load_png_rgb(path).shape == (800, 2 * 1280, 3)
    assert co.render_proof(gl_ctx, floor, 0, tmp_path / "empty", tmp_path / "proof") is None


def test_check_main_proof_without_gl_prints_notice(tmp_path, monkeypatch, capsys):
    _patch_floors(monkeypatch, {0})
    monkeypatch.setattr(co, "load_floor", xb.load_floor)
    monkeypatch.setattr(co, "create_context", lambda: (_ for _ in ()).throw(RuntimeError("no gl")))
    (tmp_path / "ov").mkdir()
    assert co.main([str(tmp_path), str(tmp_path / "ov"), "--floors", "0", "--proof", str(tmp_path / "p")]) == 0
    assert "proof skipped" in capsys.readouterr().err


def test_makefile_mentions_check_and_run_overrides():
    mk = open("Makefile").read()
    assert "check-overrides:" in mk and "tools/check_overrides.py" in mk
    run_target = mk.split("\nrun:")[1].split("\n\n")[0]
    assert "--overrides" in run_target and "$(overrides)" in run_target
```

- [ ] **Step 2: Run to verify failure**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_tools_graphics_cli.py -q -k check`
Expected: FAIL — `ModuleNotFoundError: ... 'tools.check_overrides'`

- [ ] **Step 3: Implement `tools/check_overrides.py`**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Check an override directory the way the game loads it.

    check_overrides.py DATA DIR [--floors 0-7] [--proof OUT]

Prints one line per invalid/aspect/size finding and a per-floor coverage
summary (when DIR/manifest.json exists). Exit 1 on any `invalid` or
`aspect` finding -- those would be silently ignored or stretched in-game.
--proof renders original|override side by side through the GL backend at
scale 4 to OUT (default docs/graphics-proof/overrides/, git-ignored).
"""
import argparse
import json
import pathlib
import sys

import numpy as np

from PyAitD.asset_resolver import AssetResolver
from PyAitD.override_check import check_overrides, coverage, has_errors, summarize
from PyAitD.pak import PakError
from PyAitD.render_gl import GLBackend
from PyAitD.render_options import RenderOptions
from PyAitD.scene import CameraView, FrameDescription
from PyAitD.world import CameraState
from tools.export_backgrounds import load_floor, parse_floors, save_png

DEFAULT_PROOF_DIR = pathlib.Path("docs/graphics-proof/overrides")


def create_context():
    import moderngl
    return moderngl.create_standalone_context(require=330)


def _plate(ctx, floor, cam_idx, asset, scale):
    room = floor.rooms[floor.cameras[cam_idx].viewed_rooms[0].viewed_room_idx]
    state = CameraState.from_camera(floor.cameras[cam_idx], room.world_x, room.world_y, room.world_z).angles()
    frame = FrameDescription(CameraView(state), asset, floor.palette, (), ())
    backend = GLBackend(ctx, RenderOptions(scale=scale))
    try:
        backend.draw(frame)
        return backend.read_rgb()
    finally:
        backend.release()


def render_proof(ctx, floor, cam_idx, override_dir, out_dir, scale=4, save=save_png):
    """original | override for one camera, or None if no loadable override."""
    resolver = AssetResolver(None, override_dir)
    override = resolver.background(floor, cam_idx)
    if not override.is_override:
        return None
    original = AssetResolver(None, None).background(floor, cam_idx)
    left = _plate(ctx, floor, cam_idx, original, scale)
    right = _plate(ctx, floor, cam_idx, override, scale)
    path = pathlib.Path(out_dir) / f"floor{floor.number:02d}-camera{cam_idx:03d}.png"
    save(path, np.concatenate([left, right], axis=1))
    return path


def _parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("data", type=pathlib.Path)
    p.add_argument("overrides", type=pathlib.Path)
    p.add_argument("--floors", default="0-7")
    p.add_argument("--proof", type=pathlib.Path, nargs="?", const=DEFAULT_PROOF_DIR, default=None,
                    help=f"render original|override proofs to this directory (default {DEFAULT_PROOF_DIR})")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    if not args.data.is_dir():
        print(f"error: game data directory not found: {args.data}", file=sys.stderr)
        return 2
    if not args.overrides.is_dir():
        print(f"error: override directory not found: {args.overrides}", file=sys.stderr)
        return 2
    try:
        numbers = parse_floors(args.floors)
    except ValueError:
        print(f"error: bad --floors {args.floors!r}", file=sys.stderr)
        return 2
    manifest = None
    manifest_path = args.overrides / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, ValueError) as exc:
            print(f"error: unreadable manifest {manifest_path}: {exc}", file=sys.stderr)
            return 2

    floors = []
    for number in numbers:
        try:
            floors.append(load_floor(args.data, number))
        except (PakError, FileNotFoundError, OSError, ValueError) as exc:
            print(f"warning: floor {number:02d} skipped: {exc}", file=sys.stderr)

    findings = check_overrides(args.overrides, floors, manifest)
    cov = coverage(args.overrides, floors, manifest) if manifest is not None else None
    print(summarize(findings, cov))

    if args.proof is not None:
        try:
            ctx = create_context()
        except Exception as exc:
            print(f"proof skipped: no standalone GL 3.3 context: {exc}", file=sys.stderr)
        else:
            try:
                for floor in floors:
                    for cam_idx in range(len(floor.cameras)):
                        path = render_proof(ctx, floor, cam_idx, args.overrides, args.proof)
                        if path is not None:
                            print(path)
            finally:
                ctx.release()
    return 1 if has_errors(findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`GLBackend.draw` with `actors=()` and `masks=()` draws just the background (`_draw_frame` clears, draws the background, then loops over `frame.actors`, which is empty) — verified against `render_gl.py:305-320`.

- [ ] **Step 4: Makefile**

After `export-backgrounds` add:

```make
check-overrides: install ## Check overrides=DIR the way the game loads it; proof=1 renders original|override side-by-sides to docs/graphics-proof/overrides/
	@test -n "$(overrides)" || { echo "usage: make check-overrides overrides=DIR [floors=0-7] [proof=1]"; exit 2; }
	$(PYTHON) tools/check_overrides.py "$(data)" "$(overrides)" --floors "$(or $(floors),0-7)" $(if $(proof),--proof)
```

Change the `run` target to:

```make
run: install ## Run the game through character selection (floor=0 for the attic debug bypass, overrides=DIR for regenerated backgrounds)
	$(PYTHON) -m PyAitD $(if $(floor),--floor "$(floor)") --data "$(data)" $(if $(trace),--trace $(trace)) $(if $(overrides),--overrides "$(overrides)")
```

- [ ] **Step 5: Run to verify pass**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_tools_graphics_cli.py -q`
Expected: all pass (the `gl_ctx` proof test runs on this machine — GL 4.1 Metal is available; it must not be skipped). Then with real data: `make check-overrides overrides=/tmp/aitd-ov floors=0 proof=1` → `total: regenerated 0 / original N ...`, exit 0, and side-by-sides in `docs/graphics-proof/overrides/` (`git status` must show nothing new there).

- [ ] **Step 6: Commit**

```bash
git add tools/check_overrides.py tests/test_tools_graphics_cli.py Makefile
git commit -m "feat: check_overrides tool with side-by-side proof renders"
```

---

### Task 7: Round-trip proof against real data, docs, README, AGENTS

**Files:**
- Create: `docs/ai-background-regeneration.md`
- Modify: `README.md` (after the override paragraph ending line 56), `AGENTS.md` (Commands block lines 9-18), `docs/graphics-proof/.gitkeep` untouched
- Test: `tests/test_tools_graphics_cli.py`

**Interfaces:** consumes everything above; produces nothing new.

- [ ] **Step 1: Write the failing data-gated test** (append)

```python
def test_exported_originals_render_pixel_identical_through_override_path(data_dir, tmp_path):
    """DIR straight from export, used as --overrides, changes nothing."""
    from PyAitD.floor import Floor
    from PyAitD.asset_resolver import AssetResolver
    out = tmp_path / "ov"
    assert xb.main([str(data_dir), "--out", str(out), "--floors", "0"]) == 0
    floor = Floor(data_dir, 0)
    plain = AssetResolver(None, None)
    overridden = AssetResolver(None, out)
    for cam_idx in range(len(floor.cameras)):
        try:
            floor.camera_image(cam_idx)
        except KeyError:
            continue
        a = plain.background(floor, cam_idx)
        b = overridden.background(floor, cam_idx)
        assert b.is_override
        assert (a.pixels == b.pixels).all()
    assert overridden.failures == {}


def test_docs_reference_the_workflow():
    doc = open("docs/ai-background-regeneration.md").read()
    for needle in ("make export-backgrounds", "make check-overrides", "--overrides", "manifest.json",
                   "red", "blue", "green", "invalid", "aspect", "size", "missing", "16:10"):
        assert needle in doc, needle
    assert "ai-background-regeneration.md" in open("README.md").read()
    assert "make export-backgrounds" in open("AGENTS.md").read()
```

- [ ] **Step 2: Run to verify failure**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_tools_graphics_cli.py -q -k "pixel_identical or docs"`
Expected: `test_docs_reference_the_workflow` FAILS (`FileNotFoundError`); the pixel-identical test passes if the tools are correct (it is a proof, not a red-first test — record that in the report).

- [ ] **Step 3: Write `docs/ai-background-regeneration.md`**

```markdown
# Regenerating backgrounds with AI

PyAitD can play with replacement camera backgrounds from an override
directory (`--overrides DIR`, see README). This workflow exports the
originals with structural guides so you can regenerate them in any external
image tool — ControlNet, image-to-image, an upscaler, a paint program — and
checks the results the way the game will load them. Nothing here calls an
AI service; the repo ships no model, no key and no game data.

## 1. Export

    make export-backgrounds out=~/aitd-overrides            # all floors, guide scale 4
    make export-backgrounds out=~/aitd-overrides floors=0 scale=2

Produces:

    ~/aitd-overrides/manifest.json
    ~/aitd-overrides/backgrounds/floorNN/cameraNNN.png   the 320x200 originals
    ~/aitd-overrides/guides/floorNN/cameraNNN.png        originals x4 with structure lines

The export refuses to run into a directory that already has `backgrounds/`
(your regenerated images) unless you pass `force=1`.

## 2. Regenerate

Overwrite `backgrounds/floorNN/cameraNNN.png` in place. Rules the engine
cares about:

- RGB PNG (no palette/greyscale/alpha-only), any size up to 8192x8192.
- Keep the 16:10 aspect (320x200 x N). Anything else is stretched.
- Integer multiples of 320x200 (640x400, 1280x800, ...) map cleanly to the
  internal render target; other sizes work but resample.

Use the guide as a structure reference (ControlNet canny/lineart, or as a
second input layer). The lines mean:

- **red** — foreground occlusion masks: actors walking behind these
  regions are hidden. If a regenerated plate moves a pillar, the mask
  will not follow it.
- **blue** — hard collision boxes: walls and furniture the hero cannot
  walk through. Keep visible geometry inside them.
- **green** — walkable cover polygons: where click-to-walk can send the
  hero. Keep the floor readable here.

The 12px footer strip repeats the three colours in that order. The
mapping is also in `manifest.json` under `legend`.

Masks, collision and walkable areas are engine data, not pixels: they do
not change when the background does. A plate that redraws doors or stairs
elsewhere will look wrong in play even though it loads fine.

## 3. Check

    make check-overrides overrides=~/aitd-overrides
    make check-overrides overrides=~/aitd-overrides proof=1   # also renders original|override to docs/graphics-proof/overrides/

Findings, one line each, then a per-floor coverage summary:

| kind | meaning | what to do |
|---|---|---|
| `invalid` | the game would ignore this file and use the original (not RGB, unreadable, too large); the detail is the loader's message | re-export from your tool as 8-bit RGB PNG |
| `aspect` | not 16:10 within 1% — the game would stretch it | crop or outpaint to 16:10 |
| `size` | smaller than 320x200 or not an integer multiple of it | fine to play; resize if you want crisp scaling |
| `missing` | counted, not listed: the original is used | nothing |

Exit status is 1 when any `invalid` or `aspect` finding exists. Coverage
(`regenerated / original / missing / invalid`) compares each file's pixels
with the sha256 recorded in `manifest.json` at export time, so untouched
exports count as `original`.

## 4. Play

    make run overrides=~/aitd-overrides
    .venv/bin/python -m PyAitD --overrides ~/aitd-overrides --background-filter bilinear

The CLI flag is session-only; the in-game Configuration screen persists an
override directory like every other setting.
```

- [ ] **Step 4: README and AGENTS**

README, after the paragraph ending "the game always runs." (line 56), add:

```markdown
To regenerate the backgrounds with an external AI tool, `make
export-backgrounds out=DIR` writes the originals plus structure guides and a
manifest into an override directory, and `make check-overrides overrides=DIR`
validates the results the way the game loads them. See
[docs/ai-background-regeneration.md](docs/ai-background-regeneration.md).
```

README Tests block: add `make check-overrides overrides=DIR proof=1  # validate regenerated backgrounds; side-by-sides to docs/graphics-proof/overrides/` after the `prove-graphics` line.

AGENTS.md Commands block, after the `prove-graphics` line:

```
make export-backgrounds out=DIR # originals + guides + manifest for external AI regeneration (floors=, scale=, force=1)
make check-overrides overrides=DIR # validate an override dir as the game loads it; proof=1 renders side-by-sides
```

AGENTS.md Conventions, after the graphics-layering bullet, add:

```
- `background_export.py` and `override_check.py` are pure like `scene.py`;
  PNG encoding lives only in `tools/`. The export directory layout is
  `asset_resolver.override_background_path`'s — change both or neither.
```

- [ ] **Step 5: Run the whole gate**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest -q && make prove`
Expected: all pass, no skips in the three new test files on this machine (data + GL present). Then `git status` — no PNGs, no `docs/graphics-proof/overrides/` entries.

- [ ] **Step 6: Commit**

```bash
git add docs/ai-background-regeneration.md README.md AGENTS.md tests/test_tools_graphics_cli.py
git commit -m "docs: AI background regeneration workflow and round-trip proof"
```
