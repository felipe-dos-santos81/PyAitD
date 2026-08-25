# Enhanced Graphics Scene Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Insert a pure `FrameDescription` layer between game assets and presentation so actors render at an integer-scaled internal resolution with smooth shading and stencil-polygon masks, backgrounds can be filtered or overridden, and every simulation contract keeps the FITD integer projection.

**Architecture:** `scene.build_frame` produces an immutable `FrameDescription` (float geometry + normals + mask polygons + the logical `skel.skin` result) each frame. Two backends consume it: `render_gl.GLBackend` (ModernGL, `scale`×) and `render_soft.SoftwareBackend` (pygame.draw, 320×200, GL-free). `render.Renderer` owns the window, picks the backend with GL fallback, composites the 320×200 RGBA UI canvas over the scene and presents. UI presenters paint on a transparent canvas; picking/`draw_list` stay on the logical projection.

**Tech Stack:** Python 3.12, pygame-ce ≥ 2.5, moderngl ≥ 5.10, numpy ≥ 2.0, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-25-enhanced-graphics-scene-layer-design.md`

## Global Constraints

- Dependencies stay exactly `pygame-ce`, `moderngl`, `numpy` (+ `pytest` dev). No new packages.
- Every new module except `render_gl.py`, `render.py` and one PNG loader in `asset_resolver.py` must import neither `pygame` nor `moderngl`.
- `picking.py`, `playworld.py`, `navigate.py`, `tracks.py`, `life*.py`, `anim_action.py` are not modified.
- `draw_list` entries stay `(actor_index, picking.actor_bbox(skel.skin(...)))` — byte-identical to today.
- `scale` clamps to 1..8, default 4. `shading` ∈ {`flat`, `lambert`, `smooth`}, default `smooth`. `background_filter` ∈ {`nearest`, `bilinear`, `xbr`}, default `bilinear`.
- Override convention: `<override_dir>/backgrounds/floor<NN>/camera<NNN>.png`, `<override_dir>/palette.png`. Missing/unreadable → log once per path, fall back. Never crash mid-play.
- Settings schema v2 is additive: v1 files load with render defaults.
- Every SPDX header: `# SPDX-License-Identifier: GPL-2.0-only`.
- Tests needing game data use the `data_dir` fixture (skips without data). Tests needing GL use the `gl_ctx` fixture added in Task 7 (skips when no standalone context).
- Run the full gate before finishing any task: `.venv/bin/pytest -q`.

---

## File map

| File | Status | Responsibility |
|---|---|---|
| `PyAitD/render_options.py` | create | `RenderOptions` frozen dataclass, `validate_render_options(payload) -> (RenderOptions, str|None)` |
| `PyAitD/config.py` | modify | schema 2, `Settings.render`, per-field render fallback |
| `PyAitD/mask_geometry.py` | create | `MaskDraw`, `mask_polygons(camera_raw, camera_off) -> list[MaskDraw]` |
| `PyAitD/mask.py` | modify | `create_aitd1_mask` reuses the polygon walker from `mask_geometry` |
| `PyAitD/geometry.py` | create | `BodyGeometry`, `pose_geometry(body, group_states, actor_angles)`, normals, sphere/line/point expansion |
| `PyAitD/asset_resolver.py` | create | `ImageAsset`, `AssetResolver` with override lookup |
| `PyAitD/scene.py` | create | `CameraView`, `ActorDraw`, `FrameDescription`, `build_frame(game, floor, resolver) -> (FrameDescription, draw_list)` |
| `PyAitD/render_soft.py` | create | `SoftwareBackend.draw(frame) -> (200,320,3) uint8` |
| `PyAitD/render_gl.py` | create | `GLBackend(ctx, options)`, `.draw(frame)`, `.texture`, `.thumbnail()` |
| `PyAitD/render.py` | modify | `Renderer(options)`, backend selection + fallback, `compose_scene(frame) -> thumbnail`, `present(ui_canvas)` |
| `PyAitD/ui.py` | modify | RGBA canvas helpers, `transparent_canvas()`, thumbnail args, graphics rows in configuration |
| `PyAitD/__main__.py` | modify | `_scene_frame` via `build_frame`, CLI flags, resolver, canvas pipeline |
| `PyAitD/mouse_contract.py` | modify | graphics rows reachable via existing `MENU_ACTIVATE` (documented) |
| `tools/prove_graphics.py` | create | renders fixtures at scale 4 to `docs/graphics-proof/*.png` |
| `Makefile`, `CONTEXT.md`, `README.md`, `docs/enhanced-graphics-proof.md` | modify/create | target + docs |

---

### Task 1: RenderOptions and settings schema v2

**Files:**
- Create: `PyAitD/render_options.py`
- Modify: `PyAitD/config.py`
- Test: `tests/test_render_options.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `RenderOptions(scale: int = 4, shading: str = "smooth", background_filter: str = "bilinear", override_dir: str | None = None)` (frozen). `SHADING_MODES = ("flat", "lambert", "smooth")`, `BACKGROUND_FILTERS = ("nearest", "bilinear", "xbr")`. `validate_render_options(payload) -> tuple[RenderOptions, str | None]` (per-field fallback, joined error text or None). `RenderOptions.to_payload() -> dict`. `cycle_scale(o)`, `cycle_shading(o)`, `cycle_filter(o)` return new options (scale cycles 1,2,3,4,6,8). `Settings.render: RenderOptions`. `SCHEMA = 2`. `load_settings` still returns `(Settings, str | None)`.

- [ ] **Step 1: Write failing tests for render options**

```python
# tests/test_render_options.py
# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.render_options import (
    BACKGROUND_FILTERS, SHADING_MODES, RenderOptions, cycle_filter, cycle_scale,
    cycle_shading, validate_render_options,
)


def test_defaults():
    assert RenderOptions() == RenderOptions(4, "smooth", "bilinear", None)
    assert SHADING_MODES == ("flat", "lambert", "smooth")
    assert BACKGROUND_FILTERS == ("nearest", "bilinear", "xbr")


def test_valid_payload_round_trips():
    options = RenderOptions(2, "flat", "xbr", "/tmp/ov")
    assert validate_render_options(options.to_payload()) == (options, None)


def test_each_invalid_field_falls_back_alone():
    options, error = validate_render_options(
        {"scale": 99, "shading": "smooth", "background_filter": "bilinear", "override_dir": None})
    assert options == RenderOptions(8, "smooth", "bilinear", None)  # clamped, not rejected
    assert error is None
    options, error = validate_render_options(
        {"scale": "x", "shading": "neon", "background_filter": "bilinear", "override_dir": 3})
    assert options == RenderOptions(4, "smooth", "bilinear", None)
    assert "scale" in error and "shading" in error and "override_dir" in error


def test_non_dict_payload_is_all_defaults_with_error():
    assert validate_render_options(None) == (RenderOptions(), "render must be an object")


def test_cycles():
    o = RenderOptions()
    assert cycle_scale(o).scale == 6 and cycle_scale(RenderOptions(scale=8)).scale == 1
    assert cycle_shading(o).shading == "flat"
    assert cycle_filter(o).background_filter == "xbr"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_render_options.py -q`
Expected: ImportError `PyAitD.render_options`.

- [ ] **Step 3: Implement `render_options.py`**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Pygame-free rendering options: validation, clamping, and menu cycling."""
from dataclasses import dataclass, replace

SHADING_MODES = ("flat", "lambert", "smooth")
BACKGROUND_FILTERS = ("nearest", "bilinear", "xbr")
SCALE_STEPS = (1, 2, 3, 4, 6, 8)
MIN_SCALE, MAX_SCALE = 1, 8


@dataclass(frozen=True)
class RenderOptions:
    scale: int = 4
    shading: str = "smooth"
    background_filter: str = "bilinear"
    override_dir: str | None = None

    def to_payload(self):
        return {
            "scale": self.scale,
            "shading": self.shading,
            "background_filter": self.background_filter,
            "override_dir": self.override_dir,
        }


def validate_render_options(payload):
    defaults = RenderOptions()
    if not isinstance(payload, dict):
        return defaults, "render must be an object"
    errors = []
    scale = payload.get("scale")
    if type(scale) is int:
        scale = max(MIN_SCALE, min(MAX_SCALE, scale))
    else:
        errors.append("scale must be an integer")
        scale = defaults.scale
    shading = payload.get("shading")
    if shading not in SHADING_MODES:
        errors.append(f"shading must be one of {', '.join(SHADING_MODES)}")
        shading = defaults.shading
    background_filter = payload.get("background_filter")
    if background_filter not in BACKGROUND_FILTERS:
        errors.append(f"background_filter must be one of {', '.join(BACKGROUND_FILTERS)}")
        background_filter = defaults.background_filter
    override_dir = payload.get("override_dir")
    if override_dir is not None and (not isinstance(override_dir, str) or not override_dir):
        errors.append("override_dir must be null or a non-empty string")
        override_dir = None
    options = RenderOptions(scale, shading, background_filter, override_dir)
    return options, ("; ".join(errors) or None)


def _cycle(values, current):
    return values[(values.index(current) + 1) % len(values)]


def cycle_scale(options):
    current = options.scale if options.scale in SCALE_STEPS else SCALE_STEPS[0]
    return replace(options, scale=_cycle(SCALE_STEPS, current))


def cycle_shading(options):
    return replace(options, shading=_cycle(SHADING_MODES, options.shading))


def cycle_filter(options):
    return replace(options, background_filter=_cycle(BACKGROUND_FILTERS, options.background_filter))
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_render_options.py -q` — Expected: 5 passed.

- [ ] **Step 5: Write failing config tests**

Append to `tests/test_config.py`:

```python
from PyAitD.render_options import RenderOptions
from PyAitD.config import SCHEMA


def test_schema_is_2_and_settings_carry_render_defaults():
    assert SCHEMA == 2
    assert default_settings().render == RenderOptions()


def test_v1_payload_loads_with_render_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(valid_payload()))
    settings, error = load_settings(path)
    assert error is None
    assert settings.render == RenderOptions()
    assert settings.bindings == EXPECTED


def test_v2_render_field_falls_back_per_field_with_notice(tmp_path):
    payload = valid_payload()
    payload["schema"] = 2
    payload["render"] = {"scale": 2, "shading": "neon", "background_filter": "nearest",
                         "override_dir": None}
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(payload))
    settings, error = load_settings(path)
    assert settings.render == RenderOptions(2, "smooth", "nearest", None)
    assert settings.bindings == EXPECTED
    assert "shading" in error


def test_save_writes_schema_2_with_render(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings(EXPECTED, False, RenderOptions(3, "flat", "xbr", None))
    assert save_settings(settings, path) is None
    payload = json.loads(path.read_text())
    assert payload["schema"] == 2
    assert payload["render"] == {"scale": 3, "shading": "flat",
                                 "background_filter": "xbr", "override_dir": None}
    assert load_settings(path) == (settings, None)
```

- [ ] **Step 6: Run to verify failure**

Run: `.venv/bin/pytest tests/test_config.py -q` — Expected: the four new tests fail (`SCHEMA == 1`, no `render` attribute).

- [ ] **Step 7: Modify `config.py`**

Replace `SCHEMA = 1` with `SCHEMA = 2`; add `from PyAitD.render_options import RenderOptions, validate_render_options`. Change the dataclass and functions:

```python
@dataclass(frozen=True)
class Settings:
    bindings: dict[str, tuple[str, ...]]
    sticky_action: bool = False
    render: RenderOptions = RenderOptions()


def default_settings():
    return Settings(dict(_DEFAULT_BINDINGS), False, RenderOptions())


def validate_settings(payload):
    """Return (Settings, render_error). Raises ValueError on a structurally
    invalid payload; a bad render sub-object degrades per field instead."""
    if (not isinstance(payload, dict)
            or type(payload.get("schema")) is not int
            or payload.get("schema") not in (1, 2)):
        raise ValueError("settings schema must be 1 or 2")
    expected_fields = {"schema", "sticky_action", "bindings"}
    if payload["schema"] == 2:
        expected_fields.add("render")
    if set(payload) != expected_fields:
        raise ValueError("settings fields must be schema, sticky_action, bindings"
                         + (", and render" if payload["schema"] == 2 else ""))
    ... # existing sticky/bindings validation unchanged ...
    if payload["schema"] == 2:
        render, render_error = validate_render_options(payload["render"])
    else:
        render, render_error = RenderOptions(), None
    return Settings(converted, payload["sticky_action"], render), render_error
```

`replace_binding` returns `Settings(bindings, settings.sticky_action, settings.render)`.

`load_settings`:

```python
def load_settings(path):
    path = Path(path)
    try:
        if not path.exists():
            return default_settings(), None
        settings, render_error = validate_settings(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as exc:
        return default_settings(), f"Could not load settings from {path}: {exc}"
    if render_error is not None:
        return settings, f"Could not load render settings from {path}: {render_error}"
    return settings, None
```

`save_settings` payload gains `"render": settings.render.to_payload()`.

Every other `Settings(...)` construction in `ui.py` (`reduce_system_menu` sticky toggle: `Settings(dict(settings.bindings), not settings.sticky_action)`) must become `replace(settings, sticky_action=not settings.sticky_action)` using `dataclasses.replace` so `render` is preserved. Grep: `grep -n "Settings(" PyAitD/*.py tests/*.py` and fix every 2-positional constructor site; tests constructing `Settings(EXPECTED, False)` still work because `render` defaults.

- [ ] **Step 8: Run config and reducer tests**

Run: `.venv/bin/pytest tests/test_config.py tests/test_ui_reducers.py tests/test_shell_journeys.py -q` — Expected: all pass. Existing tests that assert `validate_settings(...)` returns a `Settings` directly must be updated to unpack `settings, _ = validate_settings(...)`.

- [ ] **Step 9: Full gate and commit**

Run: `.venv/bin/pytest -q`

```bash
git add PyAitD/render_options.py PyAitD/config.py PyAitD/ui.py tests/test_render_options.py tests/test_config.py tests/test_ui_reducers.py
git commit -m "feat: add render options and settings schema v2"
```

---

### Task 2: Mask polygons (`mask_geometry.py`)

**Files:**
- Create: `PyAitD/mask_geometry.py`
- Modify: `PyAitD/mask.py:84-128` (`create_aitd1_mask`)
- Modify: `PyAitD/floor.py` (add `mask_draws(camera_idx)`)
- Test: `tests/test_mask_geometry.py`

**Interfaces:**
- Produces: `MaskDraw(id: int, polygons: tuple[np.ndarray], bbox: tuple[int,int,int,int], viewed_room: int, test_rects: tuple)` frozen; each polygon is `(K,2) int16` in 320×200 screen space. `iter_mask_records(camera_raw, camera_off)` yields `(viewed_room, test_rects, polygons)` in file order. `mask_polygons(camera_raw, camera_off) -> list[MaskDraw]` (ids are list indices, the same order as `create_aitd1_mask`). `Floor.mask_draws(camera_idx) -> list[MaskDraw]` (cached).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_mask_geometry.py
# SPDX-License-Identifier: GPL-2.0-only
import numpy as np

from PyAitD.floor import Floor
from PyAitD.mask import create_aitd1_mask, fill_poly
from PyAitD.mask_geometry import MaskDraw, mask_polygons


def test_polygons_rasterize_to_the_bitmap_masks(data_dir):
    floor = Floor(data_dir, 0)
    for cam_idx in range(len(floor.cameras)):
        off = floor.camera_data_offsets[cam_idx]
        bitmaps = create_aitd1_mask(floor.camera_raw, off)
        draws = mask_polygons(floor.camera_raw, off)
        assert len(draws) == len(bitmaps)
        for draw, mask in zip(draws, bitmaps):
            assert isinstance(draw, MaskDraw)
            assert (draw.viewed_room, draw.test_rects) == (mask.viewed_room, mask.test_rects)
            assert draw.bbox == (mask.x1, mask.y1, mask.x2, mask.y2)
            bitmap = np.zeros((200, 320), dtype=np.uint8)
            for poly in draw.polygons:
                assert poly.dtype == np.int16 and poly.ndim == 2 and poly.shape[1] == 2
                fill_poly([tuple(p) for p in poly.tolist()], bitmap, 255)
            assert np.array_equal(bitmap, mask.bitmap)


def test_ids_are_positional_and_floor_caches(data_dir):
    floor = Floor(data_dir, 0)
    draws = floor.mask_draws(0)
    assert [d.id for d in draws] == list(range(len(draws)))
    assert floor.mask_draws(0) is draws
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_mask_geometry.py -q` — Expected: ImportError.

- [ ] **Step 3: Implement**

`PyAitD/mask_geometry.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Foreground mask polygons in 320x200 screen space (pre-rasterization view of
FITD main.cpp createAITD1Mask). Pygame/GL free."""
from dataclasses import dataclass
import struct

import numpy as np

from PyAitD.formats import _s16


@dataclass(frozen=True)
class MaskDraw:
    id: int
    polygons: tuple
    bbox: tuple
    viewed_room: int
    test_rects: tuple


def iter_mask_records(camera_raw, camera_off):
    num_viewed = struct.unpack_from("<H", camera_raw, camera_off + 0x12)[0]
    for viewed in range(num_viewed):
        vr_off = camera_off + 0x14 + viewed * 0x0C
        vr_room = struct.unpack_from("<h", camera_raw, vr_off)[0]
        mask_off = struct.unpack_from("<H", camera_raw, vr_off + 2)[0]
        base = camera_off + mask_off
        data2 = camera_raw[base:]
        num_mask = struct.unpack_from("<h", data2, 0)[0]
        data = 2
        for _ in range(num_mask):
            num_zones = struct.unpack_from("<H", data2, data)[0]
            test_rects = tuple(
                struct.unpack_from("<4h", data2, data + 4 + zone * 8)
                for zone in range(num_zones)
            )
            poly_off = struct.unpack_from("<H", data2, data + 2)[0]
            src = camera_raw[base + poly_off:]
            num_polys = struct.unpack_from("<H", src, 0)[0]
            off = 2
            polygons = []
            for _ in range(num_polys):
                num_points = struct.unpack_from("<H", src, off)[0]
                off += 2
                polygons.append([
                    (_s16(src, off + k * 4), _s16(src, off + k * 4 + 2))
                    for k in range(num_points)
                ])
                off += num_points * 4
            yield vr_room, test_rects, polygons
            data += 2 + ((num_zones * 4 + 1) * 2)


def mask_polygons(camera_raw, camera_off):
    draws = []
    for index, (room, test_rects, polygons) in enumerate(iter_mask_records(camera_raw, camera_off)):
        min_x, max_x, min_y, max_y = 319, 0, 199, 0
        for poly in polygons:
            for px, py in poly:
                min_x, max_x = min(min_x, px), max(max_x, px)
                min_y, max_y = min(min_y, py), max(max_y, py)
        draws.append(MaskDraw(
            index,
            tuple(np.array(poly, dtype=np.int16).reshape(-1, 2) for poly in polygons),
            (min_x, min_y, max_x, max_y), room, test_rects,
        ))
    return draws
```

`mask.py`: rewrite `create_aitd1_mask` on the shared walker (bit-identical bitmaps):

```python
from PyAitD.mask_geometry import iter_mask_records

def create_aitd1_mask(camera_raw, camera_off):
    masks = []
    for vr_room, test_rects, polygons in iter_mask_records(camera_raw, camera_off):
        min_x, max_x, min_y, max_y = 319, 0, 199, 0
        bitmap = np.zeros((SCREEN_H, SCREEN_W), dtype=np.uint8)
        for points in polygons:
            fill_poly(points, bitmap, 255)
            for px, py in points:
                min_x, max_x = min(min_x, px), max(max_x, px)
                min_y, max_y = min(min_y, py), max(max_y, py)
        masks.append(Mask(min_x, min_y, max_x, max_y, bitmap,
                          viewed_room=vr_room, test_rects=test_rects))
    return masks
```

(`struct` import in `mask.py` becomes unused — remove it; keep `_s16` import only if still used.)

`floor.py`: add `self._mask_draws = {}` in `__init__` and

```python
    def mask_draws(self, camera_idx):
        if camera_idx not in self._mask_draws:
            self._mask_draws[camera_idx] = mask_polygons(
                self.camera_raw, self.camera_data_offsets[camera_idx],
            )
        return self._mask_draws[camera_idx]
```

with `from PyAitD.mask_geometry import mask_polygons`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/test_mask_geometry.py tests/test_mask.py tests/test_floor.py -q` — Expected: pass.

- [ ] **Step 5: Full gate and commit**

```bash
.venv/bin/pytest -q
git add PyAitD/mask_geometry.py PyAitD/mask.py PyAitD/floor.py tests/test_mask_geometry.py
git commit -m "feat: expose mask polygons beside the rasterized masks"
```

---

### Task 3: Float body geometry with normals (`geometry.py`)

**Files:**
- Create: `PyAitD/geometry.py`
- Test: `tests/test_geometry.py`

**Interfaces:**
- Consumes: `skel.pose_vertices(body, group_states, actor_angles)`, `formats.Body/Primitive/Group`.
- Produces: 

```python
@dataclass(frozen=True)
class BodyGeometry:
    vertices: np.ndarray      # (N,3) float32, posed model space (FITD units)
    normals: np.ndarray       # (N,3) float32 unit
    tris: np.ndarray          # (M,3) int32 indices into vertices
    tri_colors: np.ndarray    # (M,) uint8
    lines: np.ndarray         # (L,2) int32
    line_colors: np.ndarray   # (L,) uint8
    spheres: tuple            # ((centre_idx:int, radius:float, color:int), ...)
    points: np.ndarray        # (P,) int32
    point_sizes: np.ndarray   # (P,) uint8: 1 (type 2/7) or 2 (others)
    point_colors: np.ndarray  # (P,) uint8
```
  `pose_geometry(body, group_states, actor_angles=None) -> BodyGeometry`; `vertex_groups(body) -> np.ndarray (N,) int32` (group index per vertex, -1 when body has no groups); `icosphere(level=1) -> (verts (V,3) float32 unit, tris (T,3) int32)` cached module-level; `POLY_TYPES = (1, 8, 9, 10)`, `POINT_TYPES = (2, 4, 5, 6, 7)` (mirror `formats._PRIM_POINT_LIKE` — read it and copy the exact tuple).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_geometry.py
# SPDX-License-Identifier: GPL-2.0-only
import numpy as np

from PyAitD.formats import Body, Group, Primitive
from PyAitD.geometry import BodyGeometry, icosphere, pose_geometry, vertex_groups
from PyAitD.skel import pose_vertices


def _cube_body():
    v = [(-100, -100, -100), (100, -100, -100), (100, 100, -100), (-100, 100, -100),
         (-100, -100, 100), (100, -100, 100), (100, 100, 100), (-100, 100, 100)]
    faces = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (0, 3, 7, 4), (1, 2, 6, 5)]
    prims = [Primitive(1, 0, 10 + i, list(f)) for i, f in enumerate(faces)]
    prims.append(Primitive(0, 0, 3, [0, 6]))
    prims.append(Primitive(3, 0, 4, [7], size=50))
    prims.append(Primitive(2, 0, 5, [1]))
    return Body(0, (0,) * 6, (), v, [], [], prims)


def test_quads_fan_into_triangles_and_colors_follow():
    geo = pose_geometry(_cube_body(), [], None)
    assert isinstance(geo, BodyGeometry)
    assert geo.tris.shape == (12, 3) and geo.tri_colors.tolist() == [c for c in range(10, 16) for _ in range(2)]
    assert geo.lines.tolist() == [[0, 6]] and geo.line_colors.tolist() == [3]
    assert geo.spheres == ((7, 50.0, 4),)
    assert geo.points.tolist() == [1] and geo.point_sizes.tolist() == [1] and geo.point_colors.tolist() == [5]


def test_vertices_match_pose_vertices_exactly():
    body = _cube_body()
    expected = np.array(pose_vertices(body, [], None), dtype=np.float32)
    assert np.array_equal(pose_geometry(body, [], None).vertices, expected)


def test_normals_are_unit_and_never_nan_on_degenerate_faces():
    body = _cube_body()
    body.primitives.append(Primitive(1, 0, 9, [0, 0, 0]))  # degenerate
    geo = pose_geometry(body, [], None)
    assert geo.normals.shape == (8, 3)
    assert not np.isnan(geo.normals).any()
    assert np.allclose(np.linalg.norm(geo.normals, axis=1), 1.0, atol=1e-5)


def test_normals_average_only_within_a_group():
    # two groups: vertices 0-3 (group 0) and 4-7 (group 1) share a face across
    # the boundary; a vertex normal must ignore faces of the other group.
    body = _cube_body()
    body.groups = [Group(0, 4, 0, -1, 0, 0, 0, 0), Group(4, 4, 4, 0, 1, 0, 0, 0)]
    body.group_order = [0, 1]
    assert vertex_groups(body).tolist() == [0, 0, 0, 0, 1, 1, 1, 1]
    geo = pose_geometry(body, [(0, (0, 0, 0)), (0, (0, 0, 0))], None)
    # vertex 0 belongs to group 0: faces (0,1,2,3) [-z] and the cross faces
    # contribute only their group-0 triangles; the resulting normal must have
    # no +z component from group-1-only faces
    assert geo.normals[0][2] < 0


def test_vertex_with_no_faces_faces_camera():
    body = Body(0, (0,) * 6, (), [(0, 0, 0)], [], [], [Primitive(2, 0, 1, [0])])
    geo = pose_geometry(body, [], None)
    assert geo.normals.tolist() == [[0.0, 0.0, -1.0]]


def test_icosphere_level_one():
    verts, tris = icosphere(1)
    assert verts.shape == (42, 3) and tris.shape == (80, 3)
    assert np.allclose(np.linalg.norm(verts, axis=1), 1.0, atol=1e-6)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_geometry.py -q` — Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Float mesh view of a posed FITD body for the enhanced renderer.

Shares skel.pose_vertices with the logical projection, so pose can never
disagree; only projection differs. Pygame/GL free."""
from dataclasses import dataclass
import functools

import numpy as np

from PyAitD.formats import _PRIM_POINT_LIKE
from PyAitD.skel import pose_vertices

POLY_TYPES = (1, 8, 9, 10)
POINT_TYPES = tuple(_PRIM_POINT_LIKE)
_CAMERA_FACING = np.array([0.0, 0.0, -1.0], dtype=np.float32)


@dataclass(frozen=True)
class BodyGeometry:
    vertices: np.ndarray
    normals: np.ndarray
    tris: np.ndarray
    tri_colors: np.ndarray
    lines: np.ndarray
    line_colors: np.ndarray
    spheres: tuple
    points: np.ndarray
    point_sizes: np.ndarray
    point_colors: np.ndarray


def vertex_groups(body):
    groups = np.full(len(body.vertices), -1, dtype=np.int32)
    for index, group in enumerate(body.groups):
        groups[group.start:group.start + group.num_vertices] = index
    return groups


def _triangulate(body):
    tris, tri_colors, lines, line_colors, spheres = [], [], [], [], []
    points, point_sizes, point_colors = [], [], []
    for prim in body.primitives:
        if prim.type in POLY_TYPES:
            for i in range(1, len(prim.points) - 1):
                tris.append((prim.points[0], prim.points[i], prim.points[i + 1]))
                tri_colors.append(prim.color)
        elif prim.type == 0:
            lines.append((prim.points[0], prim.points[1]))
            line_colors.append(prim.color)
        elif prim.type == 3:
            spheres.append((prim.points[0], float(prim.size), prim.color))
        elif prim.type in POINT_TYPES:
            points.append(prim.points[0])
            point_sizes.append(1 if prim.type in (2, 7) else 2)
            point_colors.append(prim.color)
    return (
        np.array(tris, dtype=np.int32).reshape(-1, 3),
        np.array(tri_colors, dtype=np.uint8),
        np.array(lines, dtype=np.int32).reshape(-1, 2),
        np.array(line_colors, dtype=np.uint8),
        tuple(spheres),
        np.array(points, dtype=np.int32),
        np.array(point_sizes, dtype=np.uint8),
        np.array(point_colors, dtype=np.uint8),
    )


def _vertex_normals(vertices, tris, groups):
    normals = np.zeros_like(vertices)
    if len(tris):
        a, b, c = vertices[tris[:, 0]], vertices[tris[:, 1]], vertices[tris[:, 2]]
        face = np.cross(b - a, c - a)
        length = np.linalg.norm(face, axis=1)
        valid = length > 1e-6
        face[valid] /= length[valid][:, None]
        face[~valid] = 0.0
        # a face contributes to a vertex only when the whole face lies in that
        # vertex's skeleton group: no smearing across joints
        same_group = (groups[tris[:, 0]] == groups[tris[:, 1]]) & (groups[tris[:, 1]] == groups[tris[:, 2]])
        for corner in range(3):
            idx = tris[:, corner]
            np.add.at(normals, idx[same_group], face[same_group])
    length = np.linalg.norm(normals, axis=1)
    valid = length > 1e-6
    normals[valid] /= length[valid][:, None]
    normals[~valid] = _CAMERA_FACING
    return normals.astype(np.float32)


def pose_geometry(body, group_states, actor_angles=None):
    vertices = np.array(pose_vertices(body, group_states, actor_angles), dtype=np.float32).reshape(-1, 3)
    tris, tri_colors, lines, line_colors, spheres, points, point_sizes, point_colors = _triangulate(body)
    normals = _vertex_normals(vertices, tris, vertex_groups(body))
    return BodyGeometry(vertices, normals, tris, tri_colors, lines, line_colors,
                        spheres, points, point_sizes, point_colors)


@functools.lru_cache(maxsize=4)
def icosphere(level=1):
    t = (1.0 + 5 ** 0.5) / 2.0
    verts = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t),
             (0, -1, -t), (0, 1, -t), (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    tris = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4),
            (11, 10, 2), (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8),
            (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    verts = [np.array(v, dtype=np.float64) / np.linalg.norm(v) for v in verts]
    for _ in range(level):
        cache, new_tris = {}, []
        def mid(i, j):
            key = (min(i, j), max(i, j))
            if key not in cache:
                m = verts[i] + verts[j]
                verts.append(m / np.linalg.norm(m))
                cache[key] = len(verts) - 1
            return cache[key]
        for a, b, c in tris:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            new_tris += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        tris = new_tris
    return np.array(verts, dtype=np.float32), np.array(tris, dtype=np.int32)
```

Note: the "same group" test in the plan's Step 1 (`geo.normals[0][2] < 0`) — with all six cube faces in the tests, faces `(0,1,5,4)` etc. span both groups and are excluded, leaving only face `(0,1,2,3)` (−z) for vertex 0. Verify the triangle winding gives −z for that face; if it gives +z, flip the assertion to `> 0` and add a comment that winding is data-defined (FITD does no back-face culling, so sign is irrelevant to lighting — Task 7 uses `abs(dot)`).

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/test_geometry.py tests/test_skel.py -q` — Expected: pass.

- [ ] **Step 5: Real-data smoke test (append)**

```python
def test_every_body_in_the_data_poses_without_nan(data_dir):
    from PyAitD.assets import Assets
    assets = Assets(data_dir)
    for num in range(assets.body_count()):  # if no such method: iterate 0.. until KeyError, at most 200
        body = assets.body(num)
        states = [(0, (0, 0, 0))] * len(body.groups)
        geo = pose_geometry(body, states, (0, 0, 0))
        assert not np.isnan(geo.normals).any()
        assert geo.tris.max(initial=-1) < len(geo.vertices)
```

Read `PyAitD/assets.py` first; if there is no count accessor, add `body_count()` returning the LISTBODY PAK entry count (it wraps a `Pak(...).count` — check how `body()` locates its PAK).

- [ ] **Step 6: Full gate and commit**

```bash
.venv/bin/pytest -q
git add PyAitD/geometry.py PyAitD/assets.py tests/test_geometry.py
git commit -m "feat: add float body geometry with group-local normals"
```

---

### Task 4: AssetResolver with override lookup

**Files:**
- Create: `PyAitD/asset_resolver.py`
- Test: `tests/test_asset_resolver.py`

**Interfaces:**
- Consumes: `Floor.camera_image(idx)`, `Floor.palette`, `Assets.body(num)`.
- Produces: `ImageAsset(pixels: np.ndarray (H,W,3) uint8, is_override: bool)`; `AssetResolver(assets, override_dir=None, *, load_png=load_png_rgb)` with `background(floor, cam_idx) -> ImageAsset`, `palette(floor) -> np.ndarray (256,3) uint8`, `body(num) -> Body`, `failures: dict[Path, str]` (paths that failed once; logged once via `logging.getLogger("PyAitD.assets")`). `load_png_rgb(path) -> np.ndarray (H,W,3) uint8` is the only pygame-touching function (uses `pygame.image.load` + `pygame.surfarray.array3d`; no display needed). `override_background_path(override_dir, floor_number, cam_idx) -> Path` (`backgrounds/floor{NN:02d}/camera{NNN:03d}.png`), `override_palette_path(override_dir) -> Path`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_asset_resolver.py
# SPDX-License-Identifier: GPL-2.0-only
import logging
from types import SimpleNamespace

import numpy as np
import pytest

from PyAitD.asset_resolver import (
    AssetResolver, ImageAsset, override_background_path, override_palette_path,
)


def _floor(number=3):
    original = np.full((200, 320, 3), 7, dtype=np.uint8)
    return SimpleNamespace(number=number, palette=np.zeros((256, 3), dtype=np.uint8),
                           camera_image=lambda idx: original)


def test_paths_follow_the_convention(tmp_path):
    assert override_background_path(tmp_path, 3, 12) == tmp_path / "backgrounds" / "floor03" / "camera012.png"
    assert override_palette_path(tmp_path) == tmp_path / "palette.png"


def test_no_override_dir_returns_original():
    resolver = AssetResolver(SimpleNamespace(body=lambda n: n), None)
    asset = resolver.background(_floor(), 0)
    assert isinstance(asset, ImageAsset) and not asset.is_override and asset.pixels.shape == (200, 320, 3)
    assert resolver.body(5) == 5


def test_override_png_is_used_at_any_size(tmp_path):
    path = override_background_path(tmp_path, 3, 0)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"png")
    big = np.zeros((800, 1280, 3), dtype=np.uint8)
    resolver = AssetResolver(None, tmp_path, load_png=lambda p: big)
    asset = resolver.background(_floor(), 0)
    assert asset.is_override and asset.pixels is big


def test_unreadable_override_logs_once_and_falls_back(tmp_path, caplog):
    path = override_background_path(tmp_path, 3, 0)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"bad")
    def boom(p):
        raise ValueError("corrupt")
    resolver = AssetResolver(None, tmp_path, load_png=boom)
    with caplog.at_level(logging.WARNING, logger="PyAitD.assets"):
        first = resolver.background(_floor(), 0)
        second = resolver.background(_floor(), 0)
    assert not first.is_override and not second.is_override
    assert sum("corrupt" in r.message for r in caplog.records) == 1
    assert path in resolver.failures


def test_palette_override_must_be_256_wide(tmp_path):
    override_palette_path(tmp_path).write_bytes(b"png")
    resolver = AssetResolver(None, tmp_path, load_png=lambda p: np.ones((1, 256, 3), dtype=np.uint8))
    assert resolver.palette(_floor()).shape == (256, 3) and resolver.palette(_floor())[0].tolist() == [1, 1, 1]
    resolver = AssetResolver(None, tmp_path, load_png=lambda p: np.ones((1, 16, 3), dtype=np.uint8))
    assert resolver.palette(_floor()).tolist() == np.zeros((256, 3), dtype=np.uint8).tolist()
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_asset_resolver.py -q` → ImportError.

- [ ] **Step 3: Implement**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Visual asset lookup with an optional user override directory.

Only load_png_rgb touches pygame; everything else is pure so headless tests
inject a loader."""
from dataclasses import dataclass
import logging
from pathlib import Path

import numpy as np

log = logging.getLogger("PyAitD.assets")


@dataclass(frozen=True)
class ImageAsset:
    pixels: np.ndarray
    is_override: bool


def override_background_path(override_dir, floor_number, cam_idx):
    return Path(override_dir) / "backgrounds" / f"floor{floor_number:02d}" / f"camera{cam_idx:03d}.png"


def override_palette_path(override_dir):
    return Path(override_dir) / "palette.png"


def load_png_rgb(path):
    import pygame
    surface = pygame.image.load(str(path))
    return np.ascontiguousarray(pygame.surfarray.array3d(surface).swapaxes(0, 1)).astype(np.uint8)


class AssetResolver:
    def __init__(self, assets, override_dir=None, *, load_png=load_png_rgb):
        self._assets = assets
        self._override_dir = Path(override_dir) if override_dir else None
        self._load_png = load_png
        self._cache = {}
        self.failures = {}

    def body(self, num):
        return self._assets.body(num)

    def _override(self, path, validate):
        if self._override_dir is None or path in self.failures:
            return None
        if path in self._cache:
            return self._cache[path]
        if not path.is_file():
            return None
        try:
            pixels = self._load_png(path)
            validate(pixels)
        except Exception as exc:  # any loader/validation failure degrades, never crashes
            self.failures[path] = str(exc)
            log.warning("override %s ignored: %s", path, exc)
            return None
        self._cache[path] = pixels
        return pixels

    def background(self, floor, cam_idx):
        if self._override_dir is not None:
            pixels = self._override(
                override_background_path(self._override_dir, floor.number, cam_idx),
                lambda p: _require_rgb(p),
            )
            if pixels is not None:
                return ImageAsset(pixels, True)
        return ImageAsset(floor.camera_image(cam_idx), False)

    def palette(self, floor):
        if self._override_dir is not None:
            pixels = self._override(override_palette_path(self._override_dir), _require_palette)
            if pixels is not None:
                return np.ascontiguousarray(pixels[0, :256, :3]).astype(np.uint8)
        return floor.palette


def _require_rgb(pixels):
    if pixels.ndim != 3 or pixels.shape[2] != 3 or pixels.shape[0] < 1 or pixels.shape[1] < 1:
        raise ValueError(f"expected an RGB image, got shape {pixels.shape}")


def _require_palette(pixels):
    _require_rgb(pixels)
    if pixels.shape[1] != 256:
        raise ValueError(f"palette must be 256 pixels wide, got {pixels.shape[1]}")
```

- [ ] **Step 4: Run tests** — `.venv/bin/pytest tests/test_asset_resolver.py -q` → 5 passed.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/asset_resolver.py tests/test_asset_resolver.py
git commit -m "feat: add asset resolver with override directory lookup"
```

---

### Task 5: `scene.py` — CameraView, FrameDescription, build_frame

**Files:**
- Create: `PyAitD/scene.py`
- Test: `tests/test_scene.py`

**Interfaces:**
- Consumes: `world.CameraState`, `skel.skin`, `geometry.pose_geometry`, `mask_geometry.MaskDraw`, `actors.sort_actor_indices`, `actors.anim_player_for`, `picking.actor_bbox`, `AssetResolver`.
- Produces:

```python
@dataclass(frozen=True)
class CameraView:
    state: CameraState            # the FITD integer camera (angles() applied)
    def project(self, world_xyz: np.ndarray) -> np.ndarray  # (N,3) float -> (N,3) [sx, sy, depth] logical px; depth<=50 -> (-10000,-10000,-10000)
    def camera_space(self, world_xyz: np.ndarray) -> np.ndarray  # (N,3) after FITD rotation, before projection

@dataclass(frozen=True)
class ActorDraw:
    index: int; geometry: BodyGeometry; position: tuple[float,float,float]; room: int
    zv: tuple; logical: RenderResult; mask_ids: tuple[int, ...]

@dataclass(frozen=True)
class FrameDescription:
    camera: CameraView; background: ImageAsset; palette: np.ndarray
    actors: tuple[ActorDraw, ...]; masks: tuple[MaskDraw, ...]

def mask_applies_to_actor(mask: MaskDraw, actor_room: int, zv) -> bool   # moved from render._mask_applies_to_actor, same logic
def build_frame(game, floor, resolver) -> tuple[FrameDescription, list]
```

`CameraView.project` replicates `skel.skin`'s per-vertex path in float: `x = wx - cam.x; y = wy; z = wz - cam.z; if y > 10000: sentinel; y -= cam.y; rotate (Y, X, Z order) using COS_TABLE values as `s = COS_TABLE[(a + 0x100) & 0x3FF] / 32768`, `c = COS_TABLE[a & 0x3FF] / 32768` and the exact FITD formulas `x' = x*s - z*c; z' = x*c + z*s` (no truncation), then `depth = z + focal1; sx = x*focal2/depth + 160; sy = y*focal3/depth + 100`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_scene.py
# SPDX-License-Identifier: GPL-2.0-only
import numpy as np

from PyAitD.asset_resolver import AssetResolver
from PyAitD.floor import Floor
from PyAitD.game import init_game
from PyAitD.scene import CameraView, FrameDescription, build_frame, mask_applies_to_actor
from PyAitD.mask_geometry import MaskDraw
from PyAitD.skel import skin
from PyAitD.world import CameraState


def _boot(data_dir):
    game = init_game(data_dir)
    game.num_camera = game.new_num_camera
    floor = Floor(data_dir, game.current_floor)
    return game, floor


def _legacy_scene(game, floor):
    """The pre-layer _scene_frame body: what draw_list and actor order were."""
    from PyAitD.actors import anim_player_for, sort_actor_indices
    from PyAitD.picking import actor_bbox
    room = floor.rooms[game.current_room]
    cam = floor.cameras[room.camera_indices[game.num_camera]]
    state = CameraState.from_camera(cam, room.world_x, room.world_y, room.world_z).angles()
    out = []
    for index in sort_actor_indices(game, state.x, state.y, state.z):
        actor = game.actors[index]
        body = game.assets.body(actor.body_num)
        states = ([(0, (0, 0, 0))] * len(body.groups) if actor.anim == -1
                  else anim_player_for(game, index).group_states())
        result = skin(body, states,
                      (actor.world_x + actor.step_x, actor.world_y + actor.step_y, actor.world_z + actor.step_z),
                      state, actor_angles=(actor.alpha, actor.beta, actor.gamma))
        out.append((index, actor_bbox(result), result))
    return out


def test_build_frame_matches_legacy_order_and_draw_list(data_dir):
    game, floor = _boot(data_dir)
    frame, draw_list = build_frame(game, floor, AssetResolver(game.assets))
    legacy = _legacy_scene(game, floor)
    assert isinstance(frame, FrameDescription)
    assert draw_list == [(i, bbox) for i, bbox, _ in legacy]
    assert [a.index for a in frame.actors] == [i for i, _, _ in legacy]
    for actor, (_, _, result) in zip(frame.actors, legacy):
        assert actor.logical.points == result.points


def test_mask_ids_follow_the_trigger_rule(data_dir):
    game, floor = _boot(data_dir)
    frame, _ = build_frame(game, floor, AssetResolver(game.assets))
    for actor in frame.actors:
        expected = tuple(m.id for m in frame.masks if mask_applies_to_actor(m, actor.room, actor.zv))
        assert actor.mask_ids == expected


def test_mask_rule_is_the_render_rule():
    mask = MaskDraw(0, (), (0, 0, 0, 0), viewed_room=0, test_rects=((1, 3, 2, 4),))
    assert mask_applies_to_actor(mask, 0, (10, 20, 0, 0, 30, 40))
    assert not mask_applies_to_actor(mask, 1, (10, 20, 0, 0, 30, 40))
    assert not mask_applies_to_actor(mask, 0, (1000, 1100, 0, 0, 1000, 1100))
    assert not mask_applies_to_actor(mask, 0, None)


def test_float_projection_parity_with_skin(data_dir):
    game, floor = _boot(data_dir)
    frame, _ = build_frame(game, floor, AssetResolver(game.assets))
    for actor in frame.actors:
        world = actor.geometry.vertices + np.array(actor.position, dtype=np.float32)
        projected = frame.camera.project(world.astype(np.float64))
        logical = np.array(actor.logical.points, dtype=np.float64)
        culled = logical[:, 0] == -10000.0
        assert np.array_equal(projected[culled], logical[culled])
        assert np.abs(projected[~culled][:, :2] - logical[~culled][:, :2]).max() <= 0.5


def test_every_floor_camera_and_body_stays_within_half_a_pixel(data_dir):
    # exhaustive parity: every body at the origin of every camera on floor 0
    from PyAitD.geometry import pose_geometry
    from PyAitD.assets import Assets
    assets = Assets(data_dir)
    floor = Floor(data_dir, 0)
    for room in floor.rooms:
        for cam_idx in room.camera_indices:
            state = CameraState.from_camera(floor.cameras[cam_idx], room.world_x, room.world_y, room.world_z).angles()
            view = CameraView(state)
            for num in range(min(assets.body_count(), 40)):
                body = assets.body(num)
                states = [(0, (0, 0, 0))] * len(body.groups)
                logical = np.array(skin(body, states, (0, 0, 0), state, actor_angles=(0, 0, 0)).points)
                projected = view.project(pose_geometry(body, states, (0, 0, 0)).vertices.astype(np.float64))
                culled = logical[:, 0] == -10000.0
                assert np.abs(projected[~culled][:, :2] - logical[~culled][:, :2]).max(initial=0) <= 0.5
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_scene.py -q` → ImportError.

- [ ] **Step 3: Implement `scene.py`**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Per-frame scene description: the layer between game assets and any renderer.

Pure and pygame/GL free. The logical FITD projection (skel.skin) is kept for
picking, masks and every simulation contract; float geometry is added beside it."""
from dataclasses import dataclass

import numpy as np

from PyAitD.actors import anim_player_for, sort_actor_indices
from PyAitD.cos_table import COS_TABLE
from PyAitD.geometry import pose_geometry
from PyAitD.picking import actor_bbox
from PyAitD.skel import skin
from PyAitD.world import SCREEN_CENTER_X, SCREEN_CENTER_Y, CameraState

_SENTINEL = np.array([-10000.0, -10000.0, -10000.0])


def _sin_cos(angle):
    a = angle & 0x3FF
    return COS_TABLE[(a + 0x100) & 0x3FF] / 32768.0, COS_TABLE[a] / 32768.0


@dataclass(frozen=True)
class CameraView:
    state: CameraState

    def camera_space(self, world):
        cam = self.state
        pts = np.array(world, dtype=np.float64).reshape(-1, 3).copy()
        pts[:, 0] -= cam.x
        pts[:, 2] -= cam.z
        far = pts[:, 1] > 10000
        pts[:, 1] -= cam.y
        x, y, z = pts[:, 0], pts[:, 1], pts[:, 2]
        if cam._use_y:
            s, c = _sin_cos(cam._use_y)
            x, z = x * s - z * c, x * c + z * s
        if cam._use_x:
            s, c = _sin_cos(cam._use_x)
            y, z = y * s - z * c, y * c + z * s
        if cam._use_z:
            s, c = _sin_cos(cam._use_z)
            x, y = x * s - y * c, x * c + y * s
        out = np.stack([x, y, z], axis=1)
        return out, far

    def project(self, world):
        cam = self.state
        pts, far = self.camera_space(world)
        depth = pts[:, 2] + cam.focal1
        culled = far | (depth <= 50)
        safe = np.where(culled, 1.0, depth)
        sx = pts[:, 0] * cam.focal2 / safe + SCREEN_CENTER_X
        sy = pts[:, 1] * cam.focal3 / safe + SCREEN_CENTER_Y
        out = np.stack([sx, sy, depth], axis=1)
        out[culled] = _SENTINEL
        return out


@dataclass(frozen=True)
class ActorDraw:
    index: int
    geometry: object
    position: tuple
    room: int
    zv: tuple
    logical: object
    mask_ids: tuple


@dataclass(frozen=True)
class FrameDescription:
    camera: CameraView
    background: object
    palette: np.ndarray
    actors: tuple
    masks: tuple


def mask_applies_to_actor(mask, actor_room, zv):
    if zv is None or mask.viewed_room != actor_room:
        return False
    x1, x2 = int(zv[0] / 10), int(zv[1] / 10)
    z1, z2 = int(zv[4] / 10), int(zv[5] / 10)
    return any(
        x1 >= zone_x1 and z1 >= zone_z1 and x2 <= zone_x2 and z2 <= zone_z2
        for zone_x1, zone_z1, zone_x2, zone_z2 in mask.test_rects
    )


def build_frame(game, floor, resolver):
    room = floor.rooms[game.current_room]
    cam_idx = room.camera_indices[game.num_camera]
    state = CameraState.from_camera(
        floor.cameras[cam_idx], room.world_x, room.world_y, room.world_z,
    ).angles()
    masks = tuple(floor.mask_draws(cam_idx))
    actors, draw_list = [], []
    for index in sort_actor_indices(game, state.x, state.y, state.z):
        actor = game.actors[index]
        body = resolver.body(actor.body_num)
        if actor.anim == -1:
            states = [(0, (0, 0, 0))] * len(body.groups)
        else:
            states = anim_player_for(game, index).group_states()
        position = (
            actor.world_x + actor.step_x,
            actor.world_y + actor.step_y,
            actor.world_z + actor.step_z,
        )
        angles = (actor.alpha, actor.beta, actor.gamma)
        logical = skin(body, states, position, state, actor_angles=angles)
        draw_list.append((index, actor_bbox(logical)))
        actors.append(ActorDraw(
            index, pose_geometry(body, states, angles), position, actor.room,
            actor.zv, logical,
            tuple(m.id for m in masks if mask_applies_to_actor(m, actor.room, actor.zv)),
        ))
    frame = FrameDescription(
        CameraView(state), resolver.background(floor, cam_idx), resolver.palette(floor),
        tuple(actors), masks,
    )
    return frame, draw_list
```

Note `skin` checks `y > 10000` *before* subtracting `camera.y`; `camera_space` mirrors that (`far` computed before the subtraction). The exact `<< 1` after `>> 16` in the integer path equals `/32768`, which is why the float path divides the table by 32768.

- [ ] **Step 4: Run tests** — `.venv/bin/pytest tests/test_scene.py -q` → 5 passed. If parity exceeds 0.5 px, the integer path's `trunc_div(..., 65536) << 1` truncation accumulates per axis; loosen only to 1.0 px with a comment citing the measured maximum — never beyond.

- [ ] **Step 5: Full gate and commit**

```bash
.venv/bin/pytest -q
git add PyAitD/scene.py tests/test_scene.py
git commit -m "feat: add the per-frame scene description layer"
```

---

### Task 6: SoftwareBackend (GL-free 320×200)

**Files:**
- Create: `PyAitD/render_soft.py`
- Test: `tests/test_render_soft.py`

**Interfaces:**
- Consumes: `FrameDescription`, `ActorDraw.logical` (`RenderResult` with `PrimEntry(type, color, points[(sx,sy,depth)...], size)`), `MaskDraw.polygons`, `mask.fill_poly`.
- Produces: `SoftwareBackend()` with `draw(frame) -> np.ndarray (200,320,3) uint8` and `thumbnail() -> np.ndarray` (the last drawn frame). Uses `pygame.draw` on `pygame.Surface` (no display needed); no moderngl.

Behavioural contract (same as the three existing `tests/test_render.py` actor-layer tests, now expressed on the software backend): painter order across rooms; within one actor primitives are ordered far-to-near by `depth_min` (the software approximation of the per-actor depth buffer); a mask erases only actors whose `mask_ids` contain it.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_render_soft.py
# SPDX-License-Identifier: GPL-2.0-only
import numpy as np

from PyAitD.asset_resolver import ImageAsset
from PyAitD.geometry import BodyGeometry
from PyAitD.mask_geometry import MaskDraw
from PyAitD.render_soft import SoftwareBackend
from PyAitD.scene import ActorDraw, CameraView, FrameDescription
from PyAitD.skel import PrimEntry, RenderResult
from PyAitD.world import CameraState


def _palette():
    palette = np.zeros((256, 3), dtype=np.uint8)
    palette[1], palette[2], palette[3] = (255, 0, 0), (0, 255, 0), (0, 0, 255)
    return palette


def _empty_geometry():
    e = np.zeros((0, 3), dtype=np.float32)
    return BodyGeometry(e, e, np.zeros((0, 3), np.int32), np.zeros(0, np.uint8), np.zeros((0, 2), np.int32),
                        np.zeros(0, np.uint8), (), np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))


def _actor(index, prims, room=0, mask_ids=()):
    return ActorDraw(index, _empty_geometry(), (0.0, 0.0, 0.0), room, (0,) * 6,
                     RenderResult([], prims), mask_ids)


def _frame(actors, masks=()):
    state = CameraState(0, 0, 0, 0, 0, 0, 100, 100, 100).angles()
    return FrameDescription(CameraView(state), ImageAsset(np.zeros((200, 320, 3), np.uint8), False),
                            _palette(), tuple(actors), tuple(masks))


def test_painter_order_is_the_given_order_across_rooms():
    frame = _frame([_actor(0, [PrimEntry(2, 1, [(20, 10, 1)])], room=0),
                    _actor(1, [PrimEntry(2, 2, [(20, 10, 1)])], room=1),
                    _actor(2, [PrimEntry(2, 3, [(20, 10, 1)])], room=0)])
    out = SoftwareBackend().draw(frame)
    assert out.shape == (200, 320, 3) and tuple(out[10, 20]) == (0, 0, 255)


def test_near_polygon_wins_inside_one_actor_even_if_submitted_last():
    near = PrimEntry(1, 1, [(10, 10, 100), (30, 10, 100), (10, 30, 100)])
    far = PrimEntry(1, 2, [(10, 10, 1000), (30, 10, 1000), (10, 30, 1000)])
    out = SoftwareBackend().draw(_frame([_actor(0, [far, near]), ]))
    assert tuple(out[15, 15]) == (255, 0, 0)
    out = SoftwareBackend().draw(_frame([_actor(0, [near, far]), ]))
    assert tuple(out[15, 15]) == (255, 0, 0)


def test_mask_erases_only_the_actor_it_applies_to():
    mask = MaskDraw(0, (np.array([[20, 10], [21, 10], [21, 11], [20, 11]], np.int16),), (20, 10, 21, 11), 0, ())
    frame = _frame([_actor(0, [PrimEntry(2, 1, [(20, 10, 1)])]),
                    _actor(1, [PrimEntry(2, 2, [(20, 10, 1)])], mask_ids=(0,))], [mask])
    out = SoftwareBackend().draw(frame)
    assert tuple(out[10, 20]) == (255, 0, 0)


def test_background_is_copied_not_aliased():
    background = np.full((200, 320, 3), 9, np.uint8)
    frame = _frame([])
    frame = FrameDescription(frame.camera, ImageAsset(background, False), frame.palette, (), ())
    out = SoftwareBackend().draw(frame)
    assert out is not background and np.array_equal(out, background)
```

- [ ] **Step 2: Run to verify failure** — ImportError.

- [ ] **Step 3: Implement**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""GL-free 320x200 backend over the logical FITD projection.

Used headless (tests, proofs) and as the fallback when no GL 3.3 context
exists. Within one actor, primitives are painted far-to-near by their minimum
depth: the software stand-in for the per-actor depth buffer."""
import math

import numpy as np
import pygame

from PyAitD.mask import fill_poly

W, H = 320, 200


class SoftwareBackend:
    def __init__(self):
        self._last = np.zeros((H, W, 3), dtype=np.uint8)

    def thumbnail(self):
        return self._last

    def draw(self, frame):
        background = frame.background.pixels
        if background.shape[:2] != (H, W):
            background = _nearest_resize(background, W, H)
        composite = np.array(background, dtype=np.uint8, copy=True)
        palette = frame.palette
        mask_bitmaps = {}
        for actor in frame.actors:
            layer = pygame.Surface((W, H), flags=pygame.SRCALPHA)
            for prim in sorted(actor.logical.primitives, key=_depth_min, reverse=True):
                _draw_prim(layer, prim, tuple(int(c) for c in palette[prim.color]))
            rgb = pygame.surfarray.array3d(layer).swapaxes(0, 1)
            alpha = pygame.surfarray.array_alpha(layer).swapaxes(0, 1)
            visible = alpha != 0
            for mask_id in actor.mask_ids:
                if mask_id not in mask_bitmaps:
                    mask_bitmaps[mask_id] = _rasterize(frame.masks[mask_id])
                visible &= mask_bitmaps[mask_id] == 0
            composite[visible] = rgb[visible]
        self._last = composite
        return composite


def _depth_min(prim):
    return min(p[2] for p in prim.points) if prim.points else 0.0


def _draw_prim(surface, prim, color):
    pts = [(int(p[0]), int(p[1])) for p in prim.points]
    if prim.type == 1 and len(pts) >= 3:
        pygame.draw.polygon(surface, color, pts)
    elif prim.type == 0 and len(pts) == 2:
        pygame.draw.line(surface, color, pts[0], pts[1])
    elif prim.type == 3 and pts:
        pygame.draw.circle(surface, color, pts[0], max(1, int(prim.size)))
    else:
        size = 1 if prim.type in (2, 7) else 2
        for x, y in pts:
            pygame.draw.rect(surface, color, pygame.Rect(x, y, size, size))


def _rasterize(mask):
    bitmap = np.zeros((H, W), dtype=np.uint8)
    for poly in mask.polygons:
        fill_poly([tuple(p) for p in poly.tolist()], bitmap, 255)
    return bitmap


def _nearest_resize(image, width, height):
    ys = (np.arange(height) * image.shape[0] // height)
    xs = (np.arange(width) * image.shape[1] // width)
    return image[ys][:, xs]
```

Note: `pygame.draw` needs `pygame.init()`? No — `pygame.Surface` and `pygame.draw` work without a display; do not call `pygame.init()` here.

- [ ] **Step 4: Run tests** — `.venv/bin/pytest tests/test_render_soft.py -q` → 4 passed. If the sphere/point rect semantics differ from the `_ActorLayer` `_point_quad` (a 1-px point at (20,10) covers pixel (20,10)), adjust `_draw_prim` so `out[10, 20]` is painted; that is the contract.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/render_soft.py tests/test_render_soft.py
git commit -m "feat: add the GL-free software backend over the scene layer"
```

---

### Task 7: GLBackend — target, background filters, camera matrix, flat actors

**Files:**
- Create: `PyAitD/render_gl.py`
- Modify: `tests/conftest.py` (add `gl_ctx` fixture)
- Test: `tests/test_render_gl.py`

**Interfaces:**
- Consumes: `FrameDescription`, `RenderOptions`, `geometry.icosphere`.
- Produces: `GLBackend(ctx, options)` with `.size -> (w, h)` = `(320*scale, 200*scale)`, `.draw(frame)` (renders into `.texture`, a `moderngl.Texture` RGBA of `.size`), `.read_rgb() -> (h, w, 3) uint8 top-down`, `.thumbnail() -> (200,320,3) uint8` (box-downsample of `read_rgb` by `scale`), `.release()`. Module constant `LIGHT_DIR = (-0.3, -0.5, -0.8)` normalised in camera space (the shader normalises). `camera_matrix(view: CameraView, scale) -> np.ndarray (4,4) float32` builds the view-projection: rotation from the same `_sin_cos` formulas as `scene.CameraView`, then a perspective that maps `depth = z + focal1` and `sx = x*focal2/depth + 160` into NDC of the internal target, with `gl_Position.z` from depth scaled so near = 50, far = 40960 (linear in `w`). Depth < 50 is clipped by the near plane, matching the sentinel cull.

- [ ] **Step 1: Add the fixture**

Append to `tests/conftest.py`:

```python
@pytest.fixture
def gl_ctx():
    moderngl = pytest.importorskip("moderngl")
    try:
        ctx = moderngl.create_standalone_context(require=330)
    except Exception as exc:  # no GL on this host/CI
        pytest.skip(f"no standalone GL 3.3 context: {exc}")
    yield ctx
    ctx.release()
```

- [ ] **Step 2: Write failing tests**

```python
# tests/test_render_gl.py
# SPDX-License-Identifier: GPL-2.0-only
import numpy as np

from PyAitD.asset_resolver import ImageAsset
from PyAitD.geometry import BodyGeometry
from PyAitD.mask_geometry import MaskDraw
from PyAitD.render_gl import GLBackend, camera_matrix
from PyAitD.render_options import RenderOptions
from PyAitD.scene import ActorDraw, CameraView, FrameDescription
from PyAitD.skel import RenderResult
from PyAitD.world import CameraState


def _palette():
    palette = np.zeros((256, 3), dtype=np.uint8)
    palette[1], palette[2], palette[3] = (255, 0, 0), (0, 255, 0), (0, 0, 255)
    return palette


def _view():
    return CameraView(CameraState(0, 0, 0, 0, 0, 0, 1000, 320, 320).angles())


def _tri_geometry(z, color, span=400.0):
    v = np.array([[-span, -span, z], [span, -span, z], [-span, span, z]], np.float32)
    n = np.tile([0.0, 0.0, -1.0], (3, 1)).astype(np.float32)
    return BodyGeometry(v, n, np.array([[0, 1, 2]], np.int32), np.array([color], np.uint8),
                        np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), (),
                        np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))


def _actor(index, geometry, room=0, mask_ids=()):
    return ActorDraw(index, geometry, (0.0, 0.0, 0.0), room, (0,) * 6, RenderResult([], []), mask_ids)


def _frame(actors, masks=(), background=None):
    background = np.zeros((200, 320, 3), np.uint8) if background is None else background
    return FrameDescription(_view(), ImageAsset(background, False), _palette(), tuple(actors), tuple(masks))


def test_target_size_follows_scale(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=2, shading="flat"))
    assert backend.size == (640, 400)
    backend.release()


def test_background_fills_target_and_thumbnail_round_trips(gl_ctx):
    background = np.zeros((200, 320, 3), np.uint8)
    background[:, :160] = (200, 0, 0)
    backend = GLBackend(gl_ctx, RenderOptions(scale=2, shading="flat", background_filter="nearest"))
    backend.draw(_frame([], background=background))
    rgb = backend.read_rgb()
    assert rgb.shape == (400, 640, 3)
    assert tuple(rgb[10, 10]) == (200, 0, 0) and tuple(rgb[10, 630]) == (0, 0, 0)
    assert tuple(backend.thumbnail()[5, 5]) == (200, 0, 0)
    backend.release()


def test_camera_matrix_projects_like_the_logical_camera():
    view = _view()
    m = camera_matrix(view, scale=1)
    world = np.array([[100.0, -50.0, 500.0, 1.0]])
    clip = world @ m.T
    ndc = clip[0, :3] / clip[0, 3]
    sx, sy = (ndc[0] + 1) * 160, (1 - ndc[1]) * 100
    logical = view.project(world[:, :3])[0]
    assert abs(sx - logical[0]) < 0.01 and abs(sy - logical[1]) < 0.01


def test_flat_triangle_lands_where_the_logical_projection_says(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat"))
    geometry = _tri_geometry(z=1000.0, color=1)
    backend.draw(_frame([_actor(0, geometry)]))
    rgb = backend.read_rgb()
    centre = _view().project(geometry.vertices.mean(axis=0, keepdims=True).astype(np.float64))[0]
    assert tuple(rgb[int(centre[1]), int(centre[0])]) == (255, 0, 0)
    backend.release()


def test_depth_test_keeps_the_near_face_within_one_actor(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat"))
    near, far = _tri_geometry(500.0, 1), _tri_geometry(3000.0, 2, span=1200.0)
    merged = BodyGeometry(
        np.vstack([far.vertices, near.vertices]), np.vstack([far.normals, near.normals]),
        np.array([[0, 1, 2], [3, 4, 5]], np.int32), np.array([2, 1], np.uint8),
        near.lines, near.line_colors, (), near.points, near.point_sizes, near.point_colors)
    backend.draw(_frame([_actor(0, merged)]))
    rgb = backend.read_rgb()
    assert tuple(rgb[110, 150]) == (255, 0, 0)  # inside both; near wins
    backend.release()


def test_painter_order_across_actors_ignores_depth(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat"))
    near, far = _tri_geometry(500.0, 1), _tri_geometry(3000.0, 2, span=1200.0)
    backend.draw(_frame([_actor(0, near), _actor(1, far)]))  # far drawn last: covers near
    assert tuple(backend.read_rgb()[110, 150]) == (0, 255, 0)
    backend.release()


def test_stencil_mask_erases_only_the_flagged_actor(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat"))
    poly = np.array([[0, 0], [319, 0], [319, 199], [0, 199]], np.int16)
    mask = MaskDraw(0, (poly,), (0, 0, 319, 199), 0, ())
    a, b = _tri_geometry(1000.0, 1), _tri_geometry(900.0, 2)
    backend.draw(_frame([_actor(0, a), _actor(1, b, mask_ids=(0,))], [mask]))
    assert tuple(backend.read_rgb()[110, 150]) == (255, 0, 0)
    backend.release()


def test_stencil_mask_matches_bitmap_erase_at_scale_one(gl_ctx, data_dir):
    from PyAitD.floor import Floor
    from PyAitD.mask import create_aitd1_mask
    floor = Floor(data_dir, 0)
    draws = floor.mask_draws(0)
    bitmaps = create_aitd1_mask(floor.camera_raw, floor.camera_data_offsets[0])
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat"))
    full = _tri_geometry(400.0, 1, span=100000.0)  # covers the whole screen
    for draw, mask in zip(draws, bitmaps):
        backend.draw(_frame([_actor(0, full, mask_ids=(draw.id,))], draws))
        erased = backend.read_rgb()[:, :, 0] == 0
        expected = mask.bitmap == 255
        # edges may differ by a pixel between GL rasterisation and fillpoly
        disagree = erased != expected
        assert disagree.sum() <= 2 * sum(len(p) for p in draw.polygons) * 4 + 16
    backend.release()


def test_shading_modes_differ(gl_ctx):
    tilted = _tri_geometry(1000.0, 1)
    tilted = BodyGeometry(tilted.vertices, np.tile([0.6, 0.0, -0.8], (3, 1)).astype(np.float32),
                          tilted.tris, tilted.tri_colors, tilted.lines, tilted.line_colors, (),
                          tilted.points, tilted.point_sizes, tilted.point_colors)
    outputs = {}
    for mode in ("flat", "lambert", "smooth"):
        backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading=mode))
        backend.draw(_frame([_actor(0, tilted)]))
        outputs[mode] = backend.read_rgb()[110, 150].copy()
        backend.release()
    assert tuple(outputs["flat"]) == (255, 0, 0)
    assert 0 < outputs["lambert"][0] < 255 and 0 < outputs["smooth"][0] < 255
    assert outputs["smooth"][0] >= int(255 * 0.55) - 1


def test_sphere_and_line_and_point_render(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat"))
    v = np.array([[0.0, 0.0, 1000.0], [300.0, 0.0, 1000.0]], np.float32)
    n = np.tile([0.0, 0.0, -1.0], (2, 1)).astype(np.float32)
    geometry = BodyGeometry(v, n, np.zeros((0, 3), np.int32), np.zeros(0, np.uint8),
                            np.array([[0, 1]], np.int32), np.array([2], np.uint8),
                            ((0, 60.0, 3),), np.array([1], np.int32), np.array([2], np.uint8), np.array([1], np.uint8))
    backend.draw(_frame([_actor(0, geometry)]))
    rgb = backend.read_rgb()
    centre = _view().project(v.astype(np.float64))
    assert tuple(rgb[int(centre[0][1]), int(centre[0][0])]) == (0, 0, 255)      # sphere at v0
    assert tuple(rgb[int(centre[1][1]), int(centre[1][0])]) == (255, 0, 0)      # point at v1 (drawn after line)
    mid = (centre[0] + centre[1]) / 2
    assert tuple(rgb[int(mid[1]), int(mid[0])]) == (0, 255, 0)                  # line midpoint
    backend.release()
```

- [ ] **Step 3: Run to verify failure** — `.venv/bin/pytest tests/test_render_gl.py -q` → ImportError (or all skipped if no GL: then run the non-GL `test_camera_matrix_projects_like_the_logical_camera` at least).

- [ ] **Step 4: Implement `render_gl.py`**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""ModernGL backend: renders a FrameDescription at an integer multiple of
320x200 with per-actor depth, stencil-polygon masks and optional shading."""
import math

import moderngl
import numpy as np

from PyAitD.cos_table import COS_TABLE
from PyAitD.geometry import icosphere
from PyAitD.render_options import BACKGROUND_FILTERS
from PyAitD.world import SCREEN_CENTER_X, SCREEN_CENTER_Y

LIGHT_DIR = (-0.3, -0.5, -0.8)
NEAR, FAR = 50.0, 40960.0

_BG_VSH = """
#version 330
in vec2 in_pos; in vec2 in_uv; out vec2 v_uv;
void main() { gl_Position = vec4(in_pos, 0.0, 1.0); v_uv = in_uv; }
"""
_BG_FSH = """
#version 330
uniform sampler2D tex; uniform int mode; uniform vec2 src_size;
in vec2 v_uv; out vec4 f_color;
vec4 xbr(vec2 uv) {
    // 2-tap edge-aware blend: sample the 4 neighbours, keep the pixel
    // unless two diagonal neighbours agree, then blend toward them.
    vec2 px = 1.0 / src_size;
    vec4 c = texture(tex, uv);
    vec4 n = texture(tex, uv + vec2(0.0, -px.y)); vec4 s = texture(tex, uv + vec2(0.0, px.y));
    vec4 w = texture(tex, uv + vec2(-px.x, 0.0)); vec4 e = texture(tex, uv + vec2(px.x, 0.0));
    vec2 f = fract(uv * src_size) - 0.5;
    vec4 h = f.x < 0.0 ? w : e; vec4 v = f.y < 0.0 ? n : s;
    if (distance(h.rgb, v.rgb) < 0.05 && distance(h.rgb, c.rgb) > 0.1 && abs(f.x) + abs(f.y) > 0.5)
        return h;
    return c;
}
void main() {
    if (mode == 2) f_color = xbr(v_uv); else f_color = texture(tex, v_uv);
}
"""
_ACTOR_VSH = """
#version 330
uniform mat4 mvp; uniform mat3 rot;
in vec3 in_pos; in vec3 in_normal; in vec3 in_color;
out vec3 v_color; out vec3 v_normal;
void main() { gl_Position = mvp * vec4(in_pos, 1.0); v_color = in_color; v_normal = rot * in_normal; }
"""
_ACTOR_FSH = """
#version 330
uniform int shading; uniform vec3 light;
in vec3 v_color; in vec3 v_normal; out vec4 f_color;
void main() {
    float shade = 1.0;
    if (shading == 1) {
        vec3 n = normalize(cross(dFdx(gl_FragCoord.xyz), dFdy(gl_FragCoord.xyz)));
        shade = 0.55 + 0.45 * abs(dot(n, normalize(light)));
    } else if (shading == 2) {
        shade = 0.55 + 0.45 * abs(dot(normalize(v_normal), normalize(light)));
    }
    f_color = vec4(v_color * shade, 1.0);
}
"""
_STENCIL_VSH = """
#version 330
in vec2 in_pos;
void main() { gl_Position = vec4(in_pos, 0.0, 1.0); }
"""
_STENCIL_FSH = """
#version 330
out vec4 f_color;
void main() { f_color = vec4(0.0); }
"""
_SHADING_INDEX = {"flat": 0, "lambert": 1, "smooth": 2}


def _sin_cos(angle):
    a = angle & 0x3FF
    return COS_TABLE[(a + 0x100) & 0x3FF] / 32768.0, COS_TABLE[a] / 32768.0


def rotation_matrix(state):
    """3x3 matching scene.CameraView.camera_space (Y, then X, then Z)."""
    m = np.eye(3)
    if state._use_y:
        s, c = _sin_cos(state._use_y)
        m = np.array([[s, 0, -c], [0, 1, 0], [c, 0, s]]) @ m
    if state._use_x:
        s, c = _sin_cos(state._use_x)
        m = np.array([[1, 0, 0], [0, s, -c], [0, c, s]]) @ m
    if state._use_z:
        s, c = _sin_cos(state._use_z)
        m = np.array([[s, -c, 0], [c, s, 0], [0, 0, 1]]) @ m
    return m


def camera_matrix(view, scale):
    state = view.state
    rot = rotation_matrix(state)
    translate = np.eye(4)
    translate[:3, 3] = (-state.x, -state.y, -state.z)
    rotate = np.eye(4)
    rotate[:3, :3] = rot
    # clip = [x*f2 + 160*d, y*f3 + 100*d, zdepth, d] with d = z + focal1, so
    # ndc.x = (x*f2/d + 160)/160 - 1 ; ndc.y = 1 - (y*f3/d + 100)/100
    proj = np.array([
        [state.focal2 / SCREEN_CENTER_X, 0, 1.0, state.focal1],
        [0, -state.focal3 / SCREEN_CENTER_Y, -1.0, -state.focal1],
        [0, 0, (FAR + NEAR) / (FAR - NEAR), -2 * FAR * NEAR / (FAR - NEAR) + state.focal1 * (FAR + NEAR) / (FAR - NEAR)],
        [0, 0, 1.0, state.focal1],
    ])
    # row 0: x*f2 + (z + f1)*160 -> divide by w=(z+f1): x*f2/d + 160 ; scaled by 1/160 then -1 via the +1.0*z? No:
    # keep it explicit instead of clever:
    proj = np.array([
        [state.focal2 / SCREEN_CENTER_X, 0, 0, 0],
        [0, -state.focal3 / SCREEN_CENTER_Y, 0, 0],
        [0, 0, (FAR + NEAR) / (FAR - NEAR), -2 * FAR * NEAR / (FAR - NEAR)],
        [0, 0, 1.0, 0],
    ])
    shift = np.eye(4)
    shift[2, 3] = state.focal1  # d = z + focal1 becomes the clip w
    # ndc.x = x*f2/(160*d): logical sx = x*f2/d + 160 -> ndc = sx/160 - 1  (checked by test)
    m = proj @ shift @ rotate @ translate
    return m.astype(np.float32)
```

The doubled `proj` above is a plan-writing artifact: implement only the second, explicit version (`proj @ shift @ rotate @ translate`), and delete the first. The parity test `test_camera_matrix_projects_like_the_logical_camera` is the arbiter; `-focal3/100` gives `ndc.y = -(sy-100)/100`, i.e. `sy = (1 - ndc.y)*100` as the test computes. The depth row uses `z' = z + focal1` as the eye depth so the near plane sits at `d = 50` (the sentinel cull) and `FAR = 40960` (the old `/40960` normalisation).

Then the backend class:

```python
class GLBackend:
    def __init__(self, ctx, options):
        self._ctx = ctx
        self._options = options
        self.size = (320 * options.scale, 200 * options.scale)
        self.texture = ctx.texture(self.size, 4)
        self._depth = ctx.depth_renderbuffer(self.size)  # combined depth+stencil below
        self._fbo = ctx.framebuffer(color_attachments=[self.texture], depth_attachment=self._depth)
        self._bg_prog = ctx.program(vertex_shader=_BG_VSH, fragment_shader=_BG_FSH)
        self._actor_prog = ctx.program(vertex_shader=_ACTOR_VSH, fragment_shader=_ACTOR_FSH)
        self._stencil_prog = ctx.program(vertex_shader=_STENCIL_VSH, fragment_shader=_STENCIL_FSH)
        quad = np.array([-1, -1, 0, 1, 1, -1, 1, 1, 1, 1, 1, 0, -1, -1, 0, 1, 1, 1, 1, 0, -1, 1, 0, 0], dtype="f4")
        self._quad = ctx.buffer(quad.tobytes())
        self._quad_vao = ctx.vertex_array(self._bg_prog, [(self._quad, "2f 2f", "in_pos", "in_uv")])
        self._bg_tex = None
        self._bg_key = None
        self._sphere = icosphere(1)

    def release(self):
        for r in (self._quad_vao, self._quad, self._stencil_prog, self._actor_prog, self._bg_prog,
                  self._fbo, self._depth, self.texture, self._bg_tex):
            if r is not None:
                r.release()
```

`moderngl` needs a depth+stencil attachment for stencil tests: use `ctx.depth_renderbuffer(size)` is depth-only — replace with `ctx.renderbuffer(size, components=..., dtype=...)`? ModernGL exposes `Context.depth_renderbuffer(size, samples=0)` producing `GL_DEPTH_COMPONENT24` — no stencil. Use `ctx.depth_texture`? Also no stencil. The supported way: `ctx.framebuffer(color_attachments=[tex], depth_attachment=ctx.depth_renderbuffer(size))` plus stencil is unavailable in ModernGL 5.x without the raw GL path. **Decision for the implementer:** check `moderngl.__version__`; ModernGL ≥ 5.8 supports `ctx.depth_stencil_renderbuffer`? It does not. Therefore implement masks with a *mask texture* instead of hardware stencil, preserving the spec's "polygons rasterised at internal resolution" property:

- Per actor, rasterise its applicable mask polygons into an R8 texture of `self.size` on the GPU: bind a second FBO `self._mask_fbo` (colour = `self._mask_tex` R8), clear to 0, draw each polygon as a triangle fan with `_stencil_prog` writing 1.0 (change `_STENCIL_FSH` to output `vec4(1.0)`), NDC from 320×200 coordinates (`x/160 - 1`, `1 - y/100`).
- The actor fragment shader samples `mask_tex` at `gl_FragCoord.xy / size` and `discard`s when > 0.5.

This is equivalent to the stencil approach (same polygons, same resolution, per-actor) and stays within ModernGL's documented API. Update the spec wording in Task 12's doc pass ("stencil buffer" → "GPU mask texture").

`draw(frame)`:

```python
    def draw(self, frame):
        self._fbo.use()
        self._ctx.viewport = (0, 0, *self.size)
        self._ctx.disable(moderngl.DEPTH_TEST)
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        self._draw_background(frame.background)
        mvp = camera_matrix(frame.camera, self._options.scale)
        rot = rotation_matrix(frame.camera.state).astype("f4")
        self._actor_prog["mvp"].write(mvp.T.tobytes())        # column-major for GLSL
        self._actor_prog["rot"].write(rot.T.tobytes())
        self._actor_prog["shading"].value = _SHADING_INDEX[self._options.shading]
        self._actor_prog["light"].value = LIGHT_DIR
        self._actor_prog["target_size"].value = self.size      # add `uniform vec2 target_size;` + `uniform sampler2D mask_tex;` to _ACTOR_FSH
        palette = frame.palette.astype("f4") / 255.0
        for actor in frame.actors:
            self._rasterize_masks([frame.masks[i] for i in actor.mask_ids])
            self._fbo.use()
            self._ctx.enable(moderngl.DEPTH_TEST)
            self._ctx.depth_func = "<="
            self._fbo.clear(depth=1.0)   # ModernGL: clear(depth=...) keeps colour when only depth given — verify; otherwise use ctx.clear with color mask off
            self._mask_tex.use(location=1)
            self._actor_prog["mask_tex"].value = 1
            self._draw_actor(actor, palette)
        self._ctx.disable(moderngl.DEPTH_TEST)
```

`_fbo.clear(depth=1.0)` in ModernGL clears colour too; to clear depth only use `self._ctx.clear(depth=1.0, viewport=...)`? Both clear colour. Correct approach: `self._fbo.color_mask = (False, False, False, False); self._fbo.clear(depth=1.0); self._fbo.color_mask = (True, True, True, True)`. Use that.

`_draw_actor` builds one interleaved `f4` buffer `[x, y, z, nx, ny, nz, r, g, b]` per vertex list and renders:

1. triangles: expand `geometry.tris` to per-corner vertices (positions offset by `actor.position`, normals from `geometry.normals`, colour from `palette[tri_colors]`), `render(moderngl.TRIANGLES)`;
2. lines: for each `(a, b)`, build a screen-space quad of width `scale` px: project both endpoints with `frame.camera.project` (logical px), compute the perpendicular in logical space, offset by `±0.5 * scale / scale = ±0.5` logical px (so width = `scale` internal px), then *un-project* is not needed — instead draw lines in a second tiny program with `in vec2` NDC positions and a per-vertex depth: simplest is `_ctx.line_width = float(scale)` and `render(moderngl.LINES)` with the same actor program (normals = camera facing). ModernGL core profiles clamp wide lines to 1 on macOS; so implement the quad route: for each line take the two projected endpoints `p0, p1` (logical), direction `d`, normal `n = (-d.y, d.x)/|d| * 0.5`, emit two triangles with NDC positions from `(p ± n)` and `gl_Position.z` from the projected depth mapped as in `camera_matrix` (`(FAR+NEAR)/(FAR-NEAR) - 2*FAR*NEAR/((FAR-NEAR)*depth)`), via a third program `_SCREEN_VSH` (`in vec3 in_ndc; in vec3 in_color;`) sharing `_ACTOR_FSH` with `shading` forced to 0 for lines/points. Skip a line if either endpoint is the sentinel.
3. points: same screen-space program, quad of `point_sizes * scale` internal px anchored at the projected vertex (top-left like `_point_quad`).
4. spheres: icosphere vertices `* radius + vertices[centre_idx] + position`, normals = unit icosphere vertices, colour `palette[color]`, rendered with the actor program (so they shade like real spheres).

`_draw_background(asset)`: upload `asset.pixels` as an RGB texture when `(id(asset.pixels), shape)` changed since last frame; set `filter` to `NEAREST` for `nearest`, `LINEAR` otherwise; `mode = 2` only for `xbr` and only when the source is 320×200; `src_size` uniform = `(w, h)`. Render `_quad_vao` with the UV y flipped so image row 0 is the top (same trick as today's `Renderer` verts).

`read_rgb()`: `np.frombuffer(self.texture.read(), np.uint8).reshape(h, w, 4)[::-1, :, :3].copy()`.

`thumbnail()`: `read_rgb().reshape(200, s, 320, s, 3).mean(axis=(1, 3)).astype(np.uint8)`.

- [ ] **Step 5: Run tests** — `.venv/bin/pytest tests/test_render_gl.py -q` → all pass (or skipped without GL; then at least the pure `camera_matrix` test must pass).

- [ ] **Step 6: Commit**

```bash
git add PyAitD/render_gl.py tests/test_render_gl.py tests/conftest.py
git commit -m "feat: add the ModernGL backend for the scene layer"
```

---

### Task 8: Renderer refactor — backend selection, fallback, scene + UI composite

**Files:**
- Modify: `PyAitD/render.py` (rewrite; delete `_ActorLayer`, `_mask_applies_to_actor`, `_compose_existing_scene`)
- Modify: `tests/test_render.py` (drop the three `_ActorLayer` tests — their contracts now live in `test_render_soft.py` and `test_render_gl.py`; keep `fit_quad`/`window_to_logical`)
- Test: `tests/test_render.py`

**Interfaces:**
- Produces: `Renderer(options: RenderOptions | None = None, width=1280, height=800, title="PyAitD")`. Attributes: `options`, `backend` (`GLBackend` or `SoftwareBackend`), `fallback_notice: str | None` (`"Enhanced rendering unavailable"` when GL failed). Methods: `compose_scene(frame: FrameDescription) -> np.ndarray (200,320,3)` (draws the scene into the backend, returns the thumbnail — the `scene_frame` the loop and presenters use), `present(ui_canvas: np.ndarray)` where `ui_canvas` is `(200,320,3)` (opaque) or `(200,320,4)` (alpha-composited), `set_options(options)` (rebuilds the backend; used by the menu), `window_to_logical(pos)` unchanged, `close()`.
- `composite_ui(scene_rgb, ui_canvas) -> (200,320,3) uint8` module-level pure helper (numpy alpha blend; RGB canvas = replace) used by the software path and tests.

- [ ] **Step 1: Write failing tests (replace the actor-layer tests)**

```python
def test_composite_ui_blends_alpha_and_replaces_rgb():
    from PyAitD.render import composite_ui
    scene = np.full((200, 320, 3), 100, np.uint8)
    canvas = np.zeros((200, 320, 4), np.uint8)
    canvas[10, 10] = (255, 255, 255, 255)
    canvas[20, 20] = (0, 0, 0, 128)
    out = composite_ui(scene, canvas)
    assert tuple(out[10, 10]) == (255, 255, 255)
    assert tuple(out[5, 5]) == (100, 100, 100)
    assert 40 <= out[20, 20][0] <= 60
    opaque = np.full((200, 320, 3), 7, np.uint8)
    assert np.array_equal(composite_ui(scene, opaque), opaque)


def test_renderer_falls_back_to_software_when_gl_fails(monkeypatch):
    import PyAitD.render as render
    from PyAitD.render_options import RenderOptions
    from PyAitD.render_soft import SoftwareBackend
    renderer = object.__new__(render.Renderer)
    renderer._ctx = object()
    def boom(*_a, **_k):
        raise RuntimeError("no stencil")
    monkeypatch.setattr(render, "GLBackend", boom)
    renderer._select_backend(RenderOptions(scale=4))
    assert isinstance(renderer.backend, SoftwareBackend)
    assert renderer.fallback_notice == "Enhanced rendering unavailable"
    assert renderer.options.scale == 1


def test_compose_scene_returns_backend_thumbnail(monkeypatch):
    import PyAitD.render as render
    renderer = object.__new__(render.Renderer)
    expected = np.zeros((200, 320, 3), np.uint8)
    class Backend:
        def draw(self, frame): self.drawn = frame
        def thumbnail(self): return expected
    renderer.backend = Backend()
    assert renderer.compose_scene("frame") is expected
    assert renderer.backend.drawn == "frame"
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_render.py -q` → failures on the three new tests.

- [ ] **Step 3: Rewrite `render.py`**

Keep the existing `_VSH/_FSH`, `IMG_W/IMG_H`, `fit_quad`, and the window quad. New shape:

```python
class Renderer:
    def __init__(self, options=None, width=1280, height=800, title="PyAitD"):
        ...existing pygame/GL context setup...
        self._ui_tex = self._ctx.texture((IMG_W, IMG_H), 4)
        self._ui_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self._scene_tex = self._ctx.texture((IMG_W, IMG_H), 3)   # software path upload
        self._scene_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        ...quad vao as today...
        self.fallback_notice = None
        self._select_backend(options or RenderOptions())

    def _select_backend(self, options):
        try:
            self.backend = GLBackend(self._ctx, options)
            self.options = options
        except Exception as exc:
            logging.getLogger("PyAitD.render").warning("GL backend unavailable: %s", exc)
            self.backend = SoftwareBackend()
            self.options = replace(options, scale=1)
            self.fallback_notice = "Enhanced rendering unavailable"

    def set_options(self, options):
        if options == self.options:
            return
        if isinstance(self.backend, GLBackend):
            self.backend.release()
        self._select_backend(options)

    def compose_scene(self, frame):
        self.backend.draw(frame)
        return self.backend.thumbnail()

    def present(self, ui_canvas):
        self._ctx.screen.use()
        self._ctx.viewport = (0, 0, *pygame.display.get_window_size())
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        if isinstance(self.backend, GLBackend):
            self.backend.texture.use(location=0)
            self._vao.render()                                 # scene at internal resolution, linear
            self._ui_tex.write(_rgba(ui_canvas).tobytes())
            self._ctx.enable(moderngl.BLEND)
            self._ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
            self._ui_tex.use(location=0)
            self._vao.render()                                 # UI at 320x200, nearest, alpha
            self._ctx.disable(moderngl.BLEND)
        else:
            composed = composite_ui(self.backend.thumbnail(), ui_canvas)
            self._scene_tex.write(np.ascontiguousarray(composed).tobytes())
            self._scene_tex.use(location=0)
            self._vao.render()
        pygame.display.flip()
```

Because the GL backend texture is bottom-up and the UI texture is top-down, keep two VAOs with opposite UV flips (`_vao_scene`, `_vao_ui`) rather than one; the software-path upload uses `_vao_ui`'s orientation (top-down, as today).

```python
def _rgba(canvas):
    canvas = np.ascontiguousarray(canvas)
    if canvas.shape[2] == 4:
        return canvas
    out = np.empty((canvas.shape[0], canvas.shape[1], 4), np.uint8)
    out[:, :, :3] = canvas
    out[:, :, 3] = 255
    return out


def composite_ui(scene_rgb, ui_canvas):
    if ui_canvas.shape[2] == 3:
        return np.ascontiguousarray(ui_canvas)
    alpha = ui_canvas[:, :, 3:4].astype(np.float32) / 255.0
    out = scene_rgb.astype(np.float32) * (1 - alpha) + ui_canvas[:, :, :3].astype(np.float32) * alpha
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)
```

`close()` releases the backend (if GL), the UI/scene textures, then the existing resources.

- [ ] **Step 4: Run tests** — `.venv/bin/pytest tests/test_render.py -q` → pass. `tests/test_play_loop.py` and friends still pass because they stub `Renderer` (checked in Task 9).

- [ ] **Step 5: Commit**

```bash
git add PyAitD/render.py tests/test_render.py
git commit -m "refactor: renderer composites scene backend and UI canvas"
```

---

### Task 9: UI canvas (RGBA) and the loop wiring

**Files:**
- Modify: `PyAitD/ui.py` (`_to_surface`, `_to_frame`, new `transparent_canvas()`, `render_inventory`, `render_game_over`, `overlay_messages` unchanged)
- Modify: `PyAitD/__main__.py` (`_scene_frame`, `render_active_mode`, `run`, imports)
- Modify: tests that stub `Renderer` / `render_game_over`
- Test: `tests/test_ui_render.py`, `tests/test_play_loop.py`, `tests/test_combat_journey.py`, `tests/test_mouse_only.py`

**Interfaces:**
- `ui.transparent_canvas() -> np.ndarray (200,320,4) uint8 zeros`.
- `ui._to_surface(frame)` accepts 3- or 4-channel; `ui._to_frame(surface)` returns 4-channel when the surface has `SRCALPHA`, else 3.
- `ui.render_inventory(presenter, assets, scene_frame, object_names, action_names)` unchanged signature (`scene_frame` is the thumbnail; output opaque RGB).
- `ui.render_game_over(canvas, scene_frame, ready)`: `not ready` returns `canvas` unchanged (identity); `ready` returns opaque RGB dimmed scene + text.
- `__main__.render_active_mode(game, session, scene_frame)` returns an RGBA canvas when no modal (messages over `transparent_canvas()`), opaque RGB otherwise.
- `__main__._scene_frame(game, floor, renderer, resolver)` → `(scene_frame_rgb, draw_list)` via `build_frame` + `renderer.compose_scene`.
- `__main__.run(game, trace_path=None, session=None, resolver=None)`; `Renderer(session.settings.render)`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ui_render.py`:

```python
def test_transparent_canvas_and_rgba_round_trip():
    from PyAitD.ui import _to_frame, _to_surface, transparent_canvas
    canvas = transparent_canvas()
    assert canvas.shape == (200, 320, 4) and canvas.max() == 0
    surface = _to_surface(canvas)
    assert surface.get_flags() & pygame.SRCALPHA
    back = _to_frame(surface)
    assert back.shape == (200, 320, 4) and back.max() == 0
    rgb = np.full((200, 320, 3), 5, np.uint8)
    assert _to_frame(_to_surface(rgb)).shape == (200, 320, 3)


def test_play_hud_and_cursor_keep_the_canvas_transparent_elsewhere():
    from PyAitD.ui import render_cursor, render_play_hud, transparent_canvas
    out = render_play_hud(transparent_canvas(), inventory_available=True)
    out = render_cursor(out, (160, 100), "walk")
    assert out.shape == (200, 320, 4)
    assert out[0, 0, 3] == 0                      # untouched corner stays clear
    assert out[:, :, 3].max() == 255              # something was drawn


def test_game_over_not_ready_is_identity_on_the_canvas():
    from PyAitD.ui import render_game_over, transparent_canvas
    canvas = transparent_canvas()
    scene = np.zeros((200, 320, 3), np.uint8)
    assert render_game_over(canvas, scene, False) is canvas
    ready = render_game_over(canvas, scene, True)
    assert ready.shape == (200, 320, 3)
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_ui_render.py -q` → ImportError on `transparent_canvas`.

- [ ] **Step 3: Implement in `ui.py`**

```python
def transparent_canvas():
    return np.zeros((200, 320, 4), dtype=np.uint8)


def _to_surface(frame):
    frame = np.ascontiguousarray(frame)
    if frame.shape[2] == 3:
        return pygame.surfarray.make_surface(frame.swapaxes(0, 1))
    surface = pygame.Surface((frame.shape[1], frame.shape[0]), flags=pygame.SRCALPHA)
    pygame.surfarray.pixels3d(surface)[:] = frame[:, :, :3].swapaxes(0, 1)
    pygame.surfarray.pixels_alpha(surface)[:] = frame[:, :, 3].swapaxes(0, 1)
    return surface


def _to_frame(surface):
    rgb = pygame.surfarray.array3d(surface).swapaxes(0, 1)
    if surface.get_flags() & pygame.SRCALPHA:
        alpha = pygame.surfarray.array_alpha(surface).swapaxes(0, 1)
        return np.ascontiguousarray(np.dstack([rgb, alpha]))
    return np.ascontiguousarray(rgb)
```

`render_game_over(canvas, scene_frame, ready)`: `if not ready: return canvas`; otherwise the existing body over `scene_frame.copy()`.

Every presenter that does `frame.copy()` → `_to_surface(...)` works unchanged with 4 channels. `overlay_messages` unchanged.

- [ ] **Step 4: Wire `__main__.py`**

Imports: drop `anim_player_for, sort_actor_indices, actor_bbox, skin, CameraState` if now unused (keep those tests reference via `main.<name>` — grep `tests/` for `main.skin` etc.; `_real_draw_list_entry` in test_play_loop imports its own). Add `from PyAitD.asset_resolver import AssetResolver`, `from PyAitD.scene import build_frame`, `from PyAitD.ui import transparent_canvas`.

```python
def _scene_frame(game, floor, renderer, resolver=None):
    # mainLoop.cpp:270 AllRedraw through the scene layer: build_frame keeps the
    # logical draw_list; the renderer draws the enhanced frame and returns the
    # 320x200 thumbnail that presenters and the software path use.
    resolver = resolver or AssetResolver(game.assets)
    frame, draw_list = build_frame(game, floor, resolver)
    return renderer.compose_scene(frame), draw_list
```

`render_active_mode`: no modal → `overlay_messages(transparent_canvas(), game.messages, game.assets)`; `GameOver` → `render_game_over(transparent_canvas(), scene_frame, _game_over_ready(session, effect))`.

`run(game, trace_path=None, session=None, resolver=None)`: `renderer = Renderer(session.settings.render)` after `session` is resolved (move `if session is None: session = ModalSession()` above it); `if renderer.fallback_notice and session.settings_error is None: session.settings_error = renderer.fallback_notice`; `resolver = resolver or AssetResolver(game.assets, session.settings.render.override_dir)`; every `_scene_frame(game, floor, renderer)` call (three sites: initial, `_hero_branch`, `_restart_branch`, the per-frame one) passes `resolver` (`_hero_branch`/`_restart_branch` get a `resolver` parameter; after a hero/restart branch the `Game` changes, so rebuild `AssetResolver(new_game.assets, override_dir)` there). The frame end: `renderer.present(composed)` stays — `composed` is now the canvas.

Update test stubs: in `tests/test_play_loop.py`, `tests/test_mouse_only.py`, `tests/test_runtime_modes.py`, `tests/test_shell_journeys.py`, change `monkeypatch.setattr(main, "Renderer", lambda: ...)` to `lambda *_a, **_k: ...` (run `grep -n '"Renderer", lambda:' tests/*.py`). `tests/test_combat_journey.py:113` becomes `assert render_game_over(canvas, frozen, ready=False) is canvas` with `canvas = transparent_canvas()`. Tests that monkeypatch `main._scene_frame` with a 3-arg lambda: change to `lambda *args: (...)` (most already use `*args`).

- [ ] **Step 5: Run the affected suites**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_ui_render.py tests/test_play_loop.py tests/test_combat_journey.py tests/test_mouse_only.py tests/test_runtime_modes.py tests/test_shell_journeys.py tests/test_main.py -q` → pass.

- [ ] **Step 6: Windowed smoke run**

Run: `make run floor=0` for ten seconds; expect the attic at 4× with smooth-shaded actors, the INV HUD button and cursor drawn crisp at 320×200 scale. Note anything odd in the commit message body.

- [ ] **Step 7: Full gate and commit**

```bash
.venv/bin/pytest -q
git add PyAitD/ui.py PyAitD/__main__.py tests/
git commit -m "feat: route the play loop through the scene layer and a UI canvas"
```

---

### Task 10: CLI flags and override directory

**Files:**
- Modify: `PyAitD/__main__.py:43-62` (`parse_args`), `main()`
- Test: `tests/test_main.py`

**Interfaces:**
- `parse_args` gains `--render-scale INT`, `--shading {flat,lambert,smooth}`, `--background-filter {nearest,bilinear,xbr}`, `--overrides DIR` (all default `None` = keep settings). `apply_render_overrides(settings, args) -> Settings` (pure; `dataclasses.replace` on `settings.render`, scale clamped via `validate_render_options`).

- [ ] **Step 1: Write failing tests** (append to `tests/test_main.py`)

```python
def test_render_cli_flags_override_settings_for_the_session():
    from PyAitD.__main__ import apply_render_overrides, parse_args
    from PyAitD.config import default_settings
    args = parse_args(["--render-scale", "2", "--shading", "flat", "--overrides", "/tmp/ov"])
    settings = apply_render_overrides(default_settings(), args)
    assert (settings.render.scale, settings.render.shading, settings.render.background_filter,
            settings.render.override_dir) == (2, "flat", "bilinear", "/tmp/ov")
    assert apply_render_overrides(default_settings(), parse_args([])) == default_settings()
    assert apply_render_overrides(default_settings(), parse_args(["--render-scale", "50"])).render.scale == 8
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_main.py -q -k render_cli` → fails.

- [ ] **Step 3: Implement**

In `parse_args`:

```python
    p.add_argument("--render-scale", type=int, default=None, help="internal resolution multiple of 320x200 (1-8)")
    p.add_argument("--shading", choices=SHADING_MODES, default=None, help="actor shading mode")
    p.add_argument("--background-filter", choices=BACKGROUND_FILTERS, default=None, help="background upscale filter")
    p.add_argument("--overrides", type=pathlib.Path, default=None, help="asset override directory")
```

```python
def apply_render_overrides(settings, args):
    payload = settings.render.to_payload()
    if args.render_scale is not None:
        payload["scale"] = args.render_scale
    if args.shading is not None:
        payload["shading"] = args.shading
    if args.background_filter is not None:
        payload["background_filter"] = args.background_filter
    if args.overrides is not None:
        payload["override_dir"] = str(args.overrides)
    render, _error = validate_render_options(payload)
    return replace(settings, render=render)
```

In `main()`: after `session = load_runtime_session(settings_path())`, `session.settings = apply_render_overrides(session.settings, args)` (session-only: `settings_dirty` untouched so CLI flags are never persisted).

- [ ] **Step 4: Run and commit**

```bash
.venv/bin/pytest tests/test_main.py -q && .venv/bin/pytest -q
git add PyAitD/__main__.py tests/test_main.py
git commit -m "feat: add render CLI flags for one session"
```

---

### Task 11: Graphics rows in the configuration menu

**Files:**
- Modify: `PyAitD/ui.py` (`SystemMenuLayout.CONFIG_ROWS`, `reduce_system_menu`, `render_system_menu`, `_button` size for 16-px rows)
- Modify: `PyAitD/__main__.py` (`_apply_system_result` applies `renderer.set_options` — pass `renderer` through)
- Modify: `PyAitD/mouse_contract.py` (row description text)
- Test: `tests/test_ui_reducers.py`, `tests/test_ui_mouse.py`, `tests/test_ui_render.py`

**Interfaces:**
- CONFIG page rows: `[Sticky Action] + REMAPPABLE_CONTROLS + [Scale, Shading, Filter] + [Back]`; `GRAPHICS_ROWS = 3`; `ui.config_row_count() = 2 + len(REMAPPABLE_CONTROLS) + GRAPHICS_ROWS`. Row rects: `pygame.Rect(16, 4 + i * 16, 288, 16)`, buttons drawn with `size=13`.
- Accepting a graphics row returns `SystemMenuResult(settings=replace(settings, render=cycle_*(settings.render)))`.
- `__main__._apply_system_result(game, session, input_buffer, result, renderer=None)`: when `result.settings` changes `render`, call `renderer.set_options(session.settings.render)` if `renderer` is not None.

- [ ] **Step 1: Write failing tests**

`tests/test_ui_reducers.py` (append; update the two existing tests that hard-code `2 + len(REMAPPABLE_CONTROLS)` to use `config_row_count()`):

```python
def test_graphics_rows_cycle_render_options():
    from dataclasses import replace
    from PyAitD.ui import GRAPHICS_ROWS, config_row_count
    from PyAitD.render_options import RenderOptions
    assert GRAPHICS_ROWS == 3 and config_row_count() == 2 + len(REMAPPABLE_CONTROLS) + 3
    first = 1 + len(REMAPPABLE_CONTROLS)
    settings = default_settings()
    state = SystemMenuPresenter(page=SystemMenuPage.CONFIG, cursor=first)
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(scale=6)
    state.cursor = first + 1
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(shading="flat")
    state.cursor = first + 2
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(background_filter="xbr")
    assert state.page is SystemMenuPage.CONFIG  # never opens the key picker
```

`tests/test_ui_render.py` (append):

```python
def test_configuration_lists_graphics_rows_inside_the_screen():
    from PyAitD.ui import SystemMenuLayout, config_row_count
    rows = SystemMenuLayout.rows(SystemMenuPage.CONFIG)
    assert len(rows) == config_row_count()
    assert all(r.bottom <= 200 for r in rows)
    hit = SystemMenuLayout.hit_rows(SystemMenuPage.CONFIG)
    for a in range(len(hit)):
        for b in range(a + 1, len(hit)):
            assert not hit[a].colliderect(hit[b])
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_ui_reducers.py tests/test_ui_render.py -q` → ImportError on `GRAPHICS_ROWS`.

- [ ] **Step 3: Implement**

`ui.py`:

```python
GRAPHICS_ROWS = 3


def config_row_count():
    return 2 + len(REMAPPABLE_CONTROLS) + GRAPHICS_ROWS
```

`SystemMenuLayout.CONFIG_ROWS = tuple(pygame.Rect(16, 4 + i * 16, 288, 16) for i in range(config_row_count()))`.

`reduce_system_menu`: `row_count = 3 if MAIN else config_row_count()`; before the `elif command is Command.ACCEPT:` (key picker) branch add:

```python
    elif command is Command.ACCEPT and state.cursor > len(REMAPPABLE_CONTROLS):
        cycles = (cycle_scale, cycle_shading, cycle_filter)
        cycle = cycles[state.cursor - 1 - len(REMAPPABLE_CONTROLS)]
        return SystemMenuResult(settings=replace(settings, render=cycle(settings.render)))
```

`render_system_menu` CONFIG labels: after the controls append
`f"Scale: {settings.render.scale}x"`, `f"Shading: {settings.render.shading.title()}"`, `f"Filter: {settings.render.background_filter.title()}"`, then `"Back to Menu"`; draw CONFIG rows with `_button(surface, rect, label, selected=..., size=13)`.

`__main__._apply_system_result(..., renderer=None)`: after `session.settings = result.settings`, `if renderer is not None: renderer.set_options(session.settings.render)`. Pass `renderer` from `run`'s call sites (`route_command`/`route_mouse` receive it via an added keyword `renderer=None`; grep their `_apply_system_result(` calls).

`mouse_contract.py`: `MENU_ACTIVATE` description becomes `"system menu row (including graphics rows)"` — the existing contract tests compare declared routes against `mouse_contract`; update any exact-string assertion.

- [ ] **Step 4: Run** — `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_reducers.py tests/test_ui_render.py tests/test_ui_mouse.py tests/test_shell_journeys.py tests/test_mouse_only.py -q` → pass.

- [ ] **Step 5: Full gate and commit**

```bash
.venv/bin/pytest -q
git add PyAitD/ui.py PyAitD/__main__.py PyAitD/mouse_contract.py tests/
git commit -m "feat: add graphics rows to the configuration menu"
```

---

### Task 12: `make prove-graphics`, proof doc, project docs

**Files:**
- Create: `tools/prove_graphics.py`, `docs/enhanced-graphics-proof.md`, `docs/graphics-proof/.gitkeep`
- Modify: `Makefile`, `CONTEXT.md`, `README.md`, the spec (stencil → mask texture wording)
- Test: `tests/test_prove_graphics.py`

**Interfaces:**
- `tools/prove_graphics.py <data_dir> [--out docs/graphics-proof] [--scale 4]`: boots the attic (`init_game` + `num_camera = new_num_camera`) and the combat venue (`scenario.enter_combat_venue`), builds a frame for each with `build_frame`, renders with `GLBackend` on a standalone context at each shading mode, writes `attic-<mode>.png` and `combat-<mode>.png` via `pygame.image.save` from `read_rgb()`, and prints one line per file. Exits 3 with a message when no standalone GL context exists. `render_fixture(data_dir, name, scale, shading) -> np.ndarray` is importable for the test.

- [ ] **Step 1: Write failing test**

```python
# tests/test_prove_graphics.py
# SPDX-License-Identifier: GPL-2.0-only
import numpy as np


def test_render_fixture_produces_scaled_frames(data_dir, gl_ctx):
    from tools.prove_graphics import render_fixture
    rgb = render_fixture(data_dir, "attic", scale=2, shading="smooth", ctx=gl_ctx)
    assert rgb.shape == (400, 640, 3)
    assert rgb.std() > 10  # not a blank frame
```

Add `tools/__init__.py` if imports fail (check `tests/test_prove_m3a.py` for how the existing tools are imported and mirror it).

- [ ] **Step 2: Run to verify failure** — ImportError.

- [ ] **Step 3: Implement the tool**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Render fixed fixtures through the enhanced pipeline for the manual proof."""
import argparse
import pathlib
import sys

import numpy as np

from PyAitD.asset_resolver import AssetResolver
from PyAitD.floor import Floor
from PyAitD.game import init_game
from PyAitD.render_gl import GLBackend
from PyAitD.render_options import SHADING_MODES, RenderOptions
from PyAitD.scenario import enter_combat_venue
from PyAitD.scene import build_frame

FIXTURES = ("attic", "combat")


def _boot(data_dir, name):
    game = init_game(data_dir)
    if name == "combat":
        enter_combat_venue(game)
    game.num_camera = game.new_num_camera
    return game, Floor(data_dir, game.current_floor)


def render_fixture(data_dir, name, scale, shading, ctx):
    game, floor = _boot(data_dir, name)
    frame, _ = build_frame(game, floor, AssetResolver(game.assets))
    backend = GLBackend(ctx, RenderOptions(scale=scale, shading=shading))
    try:
        backend.draw(frame)
        return backend.read_rgb()
    finally:
        backend.release()


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("data", type=pathlib.Path)
    p.add_argument("--out", type=pathlib.Path, default=pathlib.Path("docs/graphics-proof"))
    p.add_argument("--scale", type=int, default=4)
    args = p.parse_args(argv)
    import moderngl, pygame
    try:
        ctx = moderngl.create_standalone_context(require=330)
    except Exception as exc:
        print(f"error: no standalone GL 3.3 context: {exc}", file=sys.stderr)
        return 3
    args.out.mkdir(parents=True, exist_ok=True)
    for name in FIXTURES:
        for mode in SHADING_MODES:
            rgb = render_fixture(args.data, name, args.scale, mode, ctx)
            path = args.out / f"{name}-{mode}.png"
            pygame.image.save(pygame.surfarray.make_surface(np.ascontiguousarray(rgb.swapaxes(0, 1))), str(path))
            print(path)
    ctx.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Makefile (add to `.PHONY` and the proof section):

```make
prove-graphics: install ## Enhanced graphics proof: render attic + combat fixtures at scale 4 per shading mode to docs/graphics-proof/
	$(PYTHON) tools/prove_graphics.py "$(data)"
```

`docs/enhanced-graphics-proof.md`: title, what the layer is (three sentences), the automated gates (`tests/test_scene.py`, `test_geometry.py`, `test_mask_geometry.py`, `test_render_soft.py`, `test_render_gl.py`, `test_render.py`, `test_config.py`, `test_render_options.py`), the command `make prove-graphics`, and a "Manual attestation" table with rows `attic 4x smooth`, `combat 4x smooth`, `configuration graphics rows (mouse)`, `--overrides with a 1280x800 PNG`, `GL fallback (force by --render-scale 1 and monkeypatching is not manual: note "not attested")` — each with a Status column initially `pending`.

`CONTEXT.md`: add a row to the milestone table ("Enhanced graphics scene layer — automated gates green; windowed attestation pending (`docs/enhanced-graphics-proof.md`)"), add the new modules to the Architecture table (`scene.py`, `geometry.py`, `mask_geometry.py`, `asset_resolver.py`, `render_options.py`, `render_gl.py`, `render_soft.py`; update `render.py`'s row), and add a "Rendering QA" bullet: "Masks are GPU-rasterised polygons per actor (a mask texture, not hardware stencil: ModernGL has no depth-stencil renderbuffer API)".

`README.md`: under Run, one paragraph on `--render-scale/--shading/--background-filter/--overrides` and the override directory convention; under Tests add `make prove-graphics`.

Spec: replace "GL stencil buffer" / "stencil" wording with "per-actor GPU mask texture" and add a one-line note explaining why.

- [ ] **Step 4: Run** — `.venv/bin/pytest tests/test_prove_graphics.py -q && make prove-graphics` → PNGs written (or exit 3 without GL — record that in the proof doc).

- [ ] **Step 5: Look at the PNGs** — open `docs/graphics-proof/attic-smooth.png`; confirm the rocking horse sits behind the right beam (mask) and the wardrobe doors face the camera (depth). If not, this is a Task 7 bug — fix there before continuing.

- [ ] **Step 6: Full gate and commit**

```bash
.venv/bin/pytest -q
git add tools/prove_graphics.py tests/test_prove_graphics.py docs/enhanced-graphics-proof.md docs/graphics-proof/.gitkeep Makefile CONTEXT.md README.md docs/superpowers/specs/2026-08-25-enhanced-graphics-scene-layer-design.md
git commit -m "docs: add the enhanced graphics proof target and records"
```

---

## Self-review

- **Spec coverage:** architecture modules → Tasks 2–8; data model → 3, 5; pipeline steps 1–5 → 7, 8, 9; config/overrides/fallback/menu → 1, 4, 8, 10, 11; tests/proofs → each task + 12. Spec deviation recorded: stencil → per-actor mask texture (Task 7, doc pass in Task 12); software backend uses far-to-near primitive order rather than a depth buffer, passing the behavioural goldens rather than being byte-identical to the old GL compositor (Task 6) — update the spec's "byte-identical" line in Task 12's doc pass as well.
- **Placeholders:** none; the duplicated `proj` block in Task 7 is explicitly resolved in favour of the second version.
- **Type consistency:** `RenderOptions` fields, `FrameDescription/ActorDraw/MaskDraw/BodyGeometry` field names, `Renderer.compose_scene(frame) -> thumbnail`, `present(ui_canvas)`, `render_game_over(canvas, scene_frame, ready)`, `config_row_count()`, `GRAPHICS_ROWS` are used identically across tasks.
