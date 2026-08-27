# Background Layout Fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `make regenerate-backgrounds` only writes plates that keep the original scene — same framing, every object at the same place, same kind, same count — and rejects the rest.

**Architecture:** The export gains a per-camera layout sidecar (the guide's geometry as JSON). The regeneration tool describes each plate as a structured inventory, dictates an explicit `generate_image` call with the original and guide attached, then verifies every attempt with a deterministic numpy gate (`tools/plate_check.py`) followed by a vision-model judge, retrying with corrections up to `--attempts` times and writing nothing when all attempts fail. Every model call still goes through the `agy` CLI via `subprocess.run`.

**Tech Stack:** Python 3.12, numpy, pygame-ce (decode/scale/PNG only), pytest; the `agy` CLI on PATH at run time (never in tests).

**Spec:** `docs/superpowers/specs/2026-08-27-background-layout-fidelity-design.md`

## Global Constraints

- `# SPDX-License-Identifier: GPL-2.0-only` first line of every Python file.
- Dependencies fixed: pygame-ce, ModernGL, NumPy, pytest. No scipy, no Pillow, no SDK. `tools/plate_check.py` is numpy only (it may import `PyAitD.render.background_export`, which is pure numpy).
- `tools/regenerate_backgrounds.py` stays the only module that talks to an AI service, only via `subprocess.run` on the `agy` CLI. Its tests monkeypatch `subprocess.run`; no test touches the network except the live test gated on `PYAITD_LIVE_AI=1`.
- Engine untouched: `asset_resolver.py`, `render_*.py`, `scene.py`, `floor.py`, `__main__.py`, `override_check.py`, `mask_geometry.py` do not change. `PyAitD/render/background_export.py` changes only as described below and its guide pixels stay byte-identical (the existing `test_guide_overlay_*` / `test_screen_guide_*` tests pin that).
- Manifest schema stays 2; new keys are additive.
- Output directories are git-ignored; nothing under `data/` is committed.
- Nothing in `IN` is ever written. `prompts.json`, `report.json`, layout sidecars and every PNG are written via `.tmp` + `os.replace`.
- Run tests headless: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest …` (the Makefile's `make test` does this).
- Never call `agy` from a test. `FakeSubprocess` in `tests/test_regenerate_backgrounds.py` stands in for it.

## Execution notes

- Game-data tests skip when `data/aitd1/…` is absent. In a worktree, symlink `data/aitd1/Alone in the Dark 1.app`, `data/aitd1/overrides` and `data/aitd1/overrides-b` from the main checkout into the worktree's `data/aitd1/`, and append `data/aitd1/overrides`, `data/aitd1/overrides-b` to `.git/info/exclude` so the symlinks never show as untracked. Task 4 needs all three.
- Baseline on `main` before Task 1: `make test` → 1036 passed, 1 skipped, 1 xfailed.
- Commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## File structure

| File | Responsibility |
|---|---|
| `PyAitD/render/background_export.py` (modify) | `layout_geometry`, `screen_layout`, `layout_segments`, `layout_rel_path`, `screen_layout_rel_path`; guides drawn from the layout; records carry `"layout"`. |
| `tools/export_backgrounds.py` (modify) | `save_layout`; `export_floor` / `export_screens` write sidecars. |
| `tools/plate_check.py` (create) | `layout_regions`, `polygon_mask`, `guide_lines`, `gate`, `THRESHOLDS`, `GateResult`, `Region`. Pure numpy. |
| `tools/regenerate_backgrounds.py` (modify) | `GAME_CONTEXT`, `INVENTORY_SCHEMA`, `JUDGE_SCHEMA`, `agy_structured`, `describe` → inventory, `generation_prompt`, `make_reference`, `attachments`, `image_name`, `generate` contract, `judge`, `judge_accepts`, `judge_corrections`, attempt loop, `report.json`, CLI. |
| `tests/test_background_export.py`, `tests/test_export_screens.py`, `tests/test_plate_check.py` (create), `tests/test_regenerate_backgrounds.py` | Tests per task. |
| `Makefile`, `docs/ai-background-regeneration.md`, `README.md`, `AGENTS.md`, `CONTEXT.md` | Task 8 (Makefile) and Task 9 (docs). |

---

### Task 1: Layout geometry in `background_export`

**Files:**
- Modify: `PyAitD/render/background_export.py` (guide section, lines ~120–232 and ~234–290)
- Modify: `docs/superpowers/specs/2026-08-27-background-layout-fidelity-design.md` (three wording fixes, step 7)
- Test: `tests/test_background_export.py`

**Interfaces:**
- Produces: `layout_geometry(floor, cam_idx) -> dict` with keys `schema, size, masks, collision, walkable`; vertex lists hold `[x, y]` float pairs or `None` for a depth-culled vertex (collision corners and walkable vertices alike). `screen_layout(entry) -> dict` with `schema, size, blit`. `layout_segments(layout) -> list[tuple[tuple[float, float], tuple[float, float]]]` — every 320×200 segment a guide draws, `None`-touching edges skipped. `layout_rel_path(floor_number, cam_idx) -> "guides/floorNN/cameraNNN.json"`, `screen_layout_rel_path(entry) -> "guides/screens/ressNN.json"`. `guide_overlay(floor, cam_idx, scale, layout=None)`. `manifest_record(...)["layout"]`, `screen_record(...)["layout"]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background_export.py`:

```python
def test_layout_geometry_lists_masks_collision_and_walkable():
    layout = be.layout_geometry(StubFloor(), 0)
    assert layout["schema"] == 1 and layout["size"] == [320, 200]
    assert layout["masks"] == [[[10.0, 10.0], [50.0, 10.0], [50.0, 40.0]]]
    assert len(layout["collision"]) == 1 and len(layout["collision"][0]) == 8
    # _box_corners order: 1 = (x2, y2, z1) = (100, 0, 0) -> (260, 100); 5 = (100, -50, 0) -> (260, 50)
    assert layout["collision"][0][1] == pytest.approx([260.0, 100.0], abs=0.6)
    assert layout["collision"][0][5] == pytest.approx([260.0, 50.0], abs=0.6)
    assert len(layout["walkable"]) == 1 and len(layout["walkable"][0]) == 4
    # cover (5, 0) -> room (50, 0, 0) -> (210, 100); (-5, 50) -> (126.67, 100)
    assert layout["walkable"][0][1] == pytest.approx([210.0, 100.0], abs=0.6)
    assert layout["walkable"][0][3] == pytest.approx([126.67, 100.0], abs=0.6)
    import json
    json.dumps(layout)


def test_layout_geometry_nulls_culled_vertices():
    floor = StubFloor()
    from PyAitD.engine.formats import Zone
    floor.rooms[0].hard_cols = [Zone(x1=-10, x2=10, y1=-10, y2=0, z1=-5000, z2=-4000, type=0, parameter=0)]
    floor._cover = {}
    layout = be.layout_geometry(floor, 0)
    assert layout["collision"] == [[None] * 8] and layout["walkable"] == []


def test_layout_segments_skip_null_endpoints_and_close_polygons():
    layout = {"masks": [[[0, 0], [10, 0], [10, 10]]],
              "collision": [[[0, 0], None, [5, 5], [7, 7], None, None, None, None]],
              "walkable": [[[1, 1], [2, 2], None]],
              "blit": [[0, 0, 4, 3]]}
    segs = be.layout_segments(layout)
    assert ((0, 0), (10, 0)) in segs and ((10, 10), (0, 0)) in segs      # mask: closed
    assert ((5, 5), (7, 7)) in segs and ((7, 7), (0, 0)) in segs         # box edges (2,3) and (3,0)
    assert ((1, 1), (2, 2)) in segs                                      # walkable edge (0,1)
    assert ((0, 0), (3, 0)) in segs and ((0, 2), (0, 0)) in segs         # blit rect, inclusive corners
    assert len(segs) == 3 + 2 + 1 + 4
    assert not any(a is None or b is None for a, b in segs)


def test_guide_overlay_accepts_a_precomputed_layout():
    floor = StubFloor()
    layout = be.layout_geometry(floor, 0)
    assert (be.guide_overlay(floor, 0, 2, layout=layout) == be.guide_overlay(floor, 0, 2)).all()


def test_screen_layout_lists_blit_rects():
    assert be.screen_layout(10) == {"schema": 1, "size": [320, 200],
                                    "blit": [list(r) for r in be.SCREEN_GUIDES[10]]}


def test_records_carry_layout_paths():
    assert be.layout_rel_path(3, 0) == "guides/floor03/camera000.json"
    assert be.screen_layout_rel_path(10) == "guides/screens/ress10.json"
    assert be.manifest_record(StubFloor(number=3), 0, checker_pixels())["layout"] == "guides/floor03/camera000.json"
    assert be.manifest_record(StubFloor(), 7, None)["layout"] is None
    assert be.screen_record(10, np.zeros((200, 320, 3), np.uint8))["layout"] == "guides/screens/ress10.json"
```

And in the existing `test_manifest_record_fields`, add `"layout": "guides/floor03/camera000.png".replace(".png", ".json"),` — i.e. the expected dict gains `"layout": "guides/floor03/camera000.json"` after `"guide"`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_background_export.py -q`
Expected: the six new tests and `test_manifest_record_fields` FAIL (`AttributeError: module ... has no attribute 'layout_geometry'` etc.).

- [ ] **Step 3: Implement the layout functions and draw the guides from them**

In `PyAitD/render/background_export.py`, add after `guide_rel_path`:

```python
def layout_rel_path(floor_number, cam_idx):
    return f"guides/floor{floor_number:02d}/camera{cam_idx:03d}.json"
```

In `manifest_record`, add `"layout": None,` to the initial dict (after `"guide"`) and, inside the `if pixels is not None:` block, `rec["layout"] = layout_rel_path(floor.number, cam_idx)`.

Replace `_draw_projected`, `guide_overlay` and their neighbours so the section reads:

```python
def _projected_or_none(view, world_pts):
    """Project `world_pts`; a depth-culled vertex becomes None, the rest
    [x, y] floats in 320x200 logical pixels (unrounded, so drawing from the
    layout is pixel-identical to drawing from the projection)."""
    proj = view.project(world_pts)
    return [None if p[2] <= _CULLED else [float(p[0]), float(p[1])] for p in proj]


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


LAYOUT_SCHEMA = 1


def layout_geometry(floor, cam_idx):
    """The structures the guide draws, as a JSON-able dict in 320x200 pixel
    space: mask polygons (closed), each hard-collision box's 8 projected
    corners in _box_corners order, and the projected cover polygons
    (closed). A depth-culled vertex is None. Room-space coordinates are
    passed to CameraView as-is: the room's world offset is already folded
    into CameraState.from_camera, exactly as in scene.build_frame."""
    masks = []
    for mask in floor.mask_draws(cam_idx):
        for poly in mask.polygons:
            pts = np.asarray(poly, dtype=float).reshape(-1, 2)
            masks.append([[float(x), float(y)] for x, y in pts])
    collision, walkable = [], []
    camera = floor.cameras[cam_idx]
    for viewed_idx, vr in enumerate(camera.viewed_rooms):
        room = floor.rooms[vr.viewed_room_idx]
        view = CameraView(CameraState.from_camera(camera, room.world_x, room.world_y, room.world_z).angles())
        for box in room.hard_cols:
            collision.append(_projected_or_none(view, _box_corners(box)))
        for poly in cover_zones_for(floor, cam_idx, viewed_idx):
            pts = [(x * COVER_SCALE, 0, z * COVER_SCALE) for x, z in poly]
            if len(pts) < 2:
                continue
            walkable.append(_projected_or_none(view, pts))
    return {"schema": LAYOUT_SCHEMA, "size": [W, H],
            "masks": masks, "collision": collision, "walkable": walkable}


def _ring_edges(n):
    return [(k, (k + 1) % n) for k in range(n)]


def _edges_of(pts, edges):
    out = []
    for i, j in edges:
        a, b = pts[i], pts[j]
        if a is None or b is None:
            continue
        out.append(((a[0], a[1]), (b[0], b[1])))
    return out


def layout_segments(layout):
    """Every segment a guide draws for `layout`, in 320x200 pixel space:
    masks and walkable polygons closed, collision boxes along _BOX_EDGES,
    blit rects around their inclusive corners. Edges touching a None
    vertex are skipped. Shared by guide_overlay/screen_guide (scaled) and
    tools/plate_check.guide_lines (unscaled)."""
    segs = []
    for poly in layout.get("masks", ()):
        segs.extend(_edges_of(poly, _ring_edges(len(poly))))
    for corners in layout.get("collision", ()):
        segs.extend(_edges_of(corners, _BOX_EDGES))
    for poly in layout.get("walkable", ()):
        segs.extend(_edges_of(poly, _ring_edges(len(poly))))
    for x, y, rw, rh in layout.get("blit", ()):
        rect = [(x, y), (x + rw - 1, y), (x + rw - 1, y + rh - 1), (x, y + rh - 1)]
        segs.extend(_edges_of(rect, _ring_edges(4)))
    return segs


def _draw_segments(img, segs, rgb, scale):
    for a, b in segs:
        draw_polyline(img, [(a[0] * scale, a[1] * scale), (b[0] * scale, b[1] * scale)], rgb)


def guide_overlay(floor, cam_idx, scale, layout=None):
    """The original background upscaled x`scale` (nearest neighbour) with
    mask polygons (red), hard-collision boxes (blue) and cover polygons
    (green) drawn over it, plus a GUIDE_FOOTER-px legend strip. `layout`
    is layout_geometry(floor, cam_idx), computed here when not given."""
    if layout is None:
        layout = layout_geometry(floor, cam_idx)
    base = nearest_upscale(floor.camera_image(cam_idx), scale)
    h, w = base.shape[:2]
    img = np.zeros((h + GUIDE_FOOTER, w, 3), np.uint8)
    img[:h] = base
    _draw_segments(img, layout_segments({"masks": layout["masks"]}), COLOR_MASK, scale)
    _draw_segments(img, layout_segments({"collision": layout["collision"]}), COLOR_COLLISION, scale)
    _draw_segments(img, layout_segments({"walkable": layout["walkable"]}), COLOR_WALKABLE, scale)
    _draw_legend_footer(img, h)
    return img
```

Drawing order must stay masks → collision → walkable (later colours overwrite earlier ones where lines cross), as before.

In the screens section, add after `screen_guide_rel_path`:

```python
def screen_layout_rel_path(entry):
    return f"guides/screens/ress{entry:02d}.json"


def screen_layout(entry):
    """The blit rects the engine draws over `entry`, as a JSON-able layout."""
    return {"schema": LAYOUT_SCHEMA, "size": [W, H], "blit": [list(r) for r in SCREEN_GUIDES[entry]]}
```

Add `"layout": screen_layout_rel_path(entry),` to `screen_record` (after `"guide"`), and rewrite `screen_guide`'s loop as:

```python
    _draw_segments(img, layout_segments(screen_layout(entry)), COLOR_BLIT, scale)
```

replacing the `for x, y, rw, rh in SCREEN_GUIDES[entry]: … draw_polyline(…, closed=True)` block. Update the module docstring's guide lines to mention the `.json` sidecars. Delete `_draw_projected` (no caller remains).

- [ ] **Step 4: Run the render and tools tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_background_export.py tests/test_export_screens.py tests/test_override_check.py tests/test_regenerate_backgrounds.py -q`
Expected: all PASS — in particular every pre-existing `test_guide_overlay_*` and `test_screen_guide_*` test, which pin pixel identity.

- [ ] **Step 5: Run the meta/layering suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_layering.py -q`
Expected: PASS (no new imports outside the allowed set).

- [ ] **Step 6: Update the spec wording that this task settled**

In `docs/superpowers/specs/2026-08-27-background-layout-fidelity-design.md`:
- "returns (floats, one decimal, may fall outside the frame — consumers clip)" → "returns (floats, unrounded so the guide stays pixel-identical; may fall outside the frame — consumers clip)".
- In the `walkable` bullet: "one closed polygon per cover polygon, projected." → "one closed polygon per cover polygon, projected; `null` for a depth-culled vertex, like collision corners."
- Add to the Layout sidecar section, after the `guide_overlay` paragraph: "`layout_segments(layout)` returns every segment a guide draws (masks and walkable closed, collision along the box edges, blit rects) and is the single source for both the guide drawing and `plate_check.guide_lines`."
- In the gate section's `GateResult` sentence, add `leaked: bool` — "`GateResult(passed: bool, scores: dict, failures: list[str], leaked: bool)`; `leaked` is True when either leak threshold was exceeded (the attachment rule keys off it)."

- [ ] **Step 7: Commit**

```bash
git add PyAitD/render/background_export.py tests/test_background_export.py docs/superpowers/specs/2026-08-27-background-layout-fidelity-design.md
git commit -m "feat: layout geometry behind the background guides

guide_overlay/screen_guide draw from layout_geometry/screen_layout via
layout_segments; manifest records name the layout sidecar."
```

---

### Task 2: Export writes the layout sidecars

**Files:**
- Modify: `tools/export_backgrounds.py` (`export_floor`, `export_screens`, imports, docstring)
- Test: `tests/test_export_screens.py`

**Interfaces:**
- Consumes: Task 1's `layout_geometry`, `screen_layout`, `layout_rel_path`, `screen_layout_rel_path`, `guide_overlay(..., layout=)`.
- Produces: `save_layout(path, layout)` (atomic JSON write); `export_floor(floor, out_dir, guide_scale, save=save_png, save_layout=save_layout)`; `export_screens(assets, out_dir, guide_scale, save=save_png, save_layout=save_layout)`. Sidecar files at `OUT/guides/floorNN/cameraNNN.json` and `OUT/guides/screens/ressNN.json`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_export_screens.py`:

```python
def test_export_floor_writes_layout_sidecars(tmp_path):
    from tests.stub_floor import StubFloor
    saved = {}
    records = xb.export_floor(StubFloor(), tmp_path, 2, save=lambda p, rgb: saved.__setitem__(p, rgb.shape))
    path = tmp_path / "guides" / "floor00" / "camera000.json"
    layout = json.loads(path.read_text())
    assert layout["schema"] == 1 and len(layout["masks"]) == 1 and len(layout["collision"]) == 1
    assert records[0]["layout"] == "guides/floor00/camera000.json"
    assert not path.with_name(path.name + ".tmp").exists()
    assert saved[tmp_path / "guides" / "floor00" / "camera000.png"] == (400 + be.GUIDE_FOOTER, 640, 3)


def test_export_floor_skips_the_sidecar_of_a_missing_image(tmp_path):
    from tests.stub_floor import StubFloor
    records = xb.export_floor(StubFloor(images={}), tmp_path, 2, save=lambda p, rgb: None)
    assert records[0]["layout"] is None
    assert not (tmp_path / "guides").exists()


def test_export_screens_writes_layout_sidecars(tmp_path):
    records = xb.export_screens(_assets(), tmp_path, 2, save=lambda p, rgb: None)
    layout = json.loads((tmp_path / "guides" / "screens" / "ress10.json").read_text())
    assert layout == be.screen_layout(10)
    assert records[0]["layout"] == "guides/screens/ress06.json"


def test_save_layout_is_atomic(tmp_path):
    path = tmp_path / "a" / "b.json"
    xb.save_layout(path, {"schema": 1})
    assert json.loads(path.read_text()) == {"schema": 1}
    assert sorted(p.name for p in path.parent.iterdir()) == ["b.json"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_export_screens.py -q`
Expected: the four new tests FAIL (`FileNotFoundError` for the `.json`, `AttributeError: save_layout`).

- [ ] **Step 3: Implement**

In `tools/export_backgrounds.py`, extend the import from `PyAitD.render.background_export` with `layout_geometry, layout_rel_path, screen_layout, screen_layout_rel_path`. Add after `save_png`:

```python
def save_layout(path, layout):
    """Write a layout sidecar via `.tmp` + os.replace, like save_manifest."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(layout))
    os.replace(tmp, path)
```

Rewrite `export_floor` and `export_screens`:

```python
def export_floor(floor, out_dir, guide_scale, save=save_png, save_layout=save_layout):
    out_dir = pathlib.Path(out_dir)
    records = []
    for cam_idx in range(len(floor.cameras)):
        try:
            pixels = floor.camera_image(cam_idx)
        except KeyError:
            records.append(manifest_record(floor, cam_idx, None))
            continue
        layout = layout_geometry(floor, cam_idx)
        save(out_dir / background_rel_path(floor.number, cam_idx), pixels)
        save(out_dir / guide_rel_path(floor.number, cam_idx), guide_overlay(floor, cam_idx, guide_scale, layout=layout))
        save_layout(out_dir / layout_rel_path(floor.number, cam_idx), layout)
        records.append(manifest_record(floor, cam_idx, pixels))
    return records


def export_screens(assets, out_dir, guide_scale, save=save_png, save_layout=save_layout):
    # Per-entry, like export_floor's per-camera loop: one damaged ITD_RESS
    # entry must not discard the records for entries already written to
    # disk earlier in the loop (a whole-loop try/except did exactly that).
    out_dir = pathlib.Path(out_dir)
    records = []
    for entry in SCREEN_ENTRIES:
        try:
            pixels = assets.resource_screen(entry)
            save(out_dir / screen_rel_path(entry), pixels)
            save(out_dir / screen_guide_rel_path(entry), screen_guide(pixels, entry, guide_scale))
            save_layout(out_dir / screen_layout_rel_path(entry), screen_layout(entry))
            records.append(screen_record(entry, pixels))
        except (PakError, FileNotFoundError, OSError, ValueError) as exc:
            print(f"warning: screen {entry} ({SCREEN_NAMES[entry]}) skipped: {exc}", file=sys.stderr)
    return records
```

Add two lines to the module docstring's layout listing:

```
    guides/floorNN/cameraNNN.json       the same structures as JSON (320x200 px)
    guides/screens/ressNN.json          the blit rects as JSON
```

- [ ] **Step 4: Run the tools tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_export_screens.py tests/test_regenerate_backgrounds.py tests/test_override_check.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/export_backgrounds.py tests/test_export_screens.py
git commit -m "feat: export writes layout sidecars beside every guide"
```

---

### Task 3: The local gate (`tools/plate_check.py`)

**Files:**
- Create: `tools/plate_check.py`
- Test: `tests/test_plate_check.py`

**Interfaces:**
- Consumes: `PyAitD.render.background_export.draw_polyline`, `layout_segments`, `nearest_upscale` (Task 1).
- Produces:
  - `Region(kind: str, polygon: tuple[tuple[float, float], ...], bbox_pct: tuple[int, int, int, int])`
  - `layout_regions(layout: dict | None) -> list[Region]`
  - `polygon_mask(polygon, shape=(200, 320)) -> np.ndarray[bool]`
  - `guide_lines(layout) -> np.ndarray[bool]` (200×320)
  - `GateResult(passed: bool, scores: dict, failures: list[str], leaked: bool)`
  - `gate(candidate, original, layout, scale=1.0) -> GateResult`; `candidate` `(800, 1280, 3)` uint8, `original` `(200, 320, 3)` uint8; raises `ValueError` on other shapes.
  - `THRESHOLDS = {"ncc": 0.50, "edge_recall": 0.60, "region_recall": 0.50, "leak": 0.02, "leak_frame": 0.005, "plain": 0.02}`
  - `fmt_bbox((x0, y0, x1, y1)) -> "x 45–52 y 12–25"` (en dash).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_plate_check.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
import numpy as np
import pytest

from PyAitD.render.background_export import nearest_upscale
from tools import plate_check as pc

pytestmark = pytest.mark.tools

LAYOUT = {"schema": 1, "size": [320, 200],
          "masks": [[[100, 60], [160, 60], [160, 140], [100, 140]]],
          "collision": [[[220, 20], [270, 20], [270, 50], [220, 50], None, None, None, None]],
          "walkable": [[[0, 150], [320, 150], [320, 200], [0, 200]]]}


def scene(shift=0):
    """A gradient floor with a bright 'crate' and a dark 'window'; `shift`
    moves both objects right by that many pixels."""
    img = np.zeros((200, 320, 3), np.uint8)
    img[:] = np.linspace(40, 120, 320).astype(np.uint8)[None, :, None]
    img[60:140, 100 + shift:160 + shift] = (200, 180, 160)
    img[20:50, 220 + shift:270 + shift] = (30, 30, 30)
    return img


def test_identical_scene_passes_every_score():
    r = pc.gate(nearest_upscale(scene(), 4), scene(), LAYOUT)
    assert r.passed and r.failures == [] and not r.leaked
    assert r.scores["ncc"] > 0.99 and r.scores["edge_recall"] == 1.0
    assert r.scores["leak"] == 0.0 and r.scores["leak_frame"] == 0.0
    kinds = [reg["kind"] for reg in r.scores["regions"]]
    assert kinds == ["mask", "collision"]                      # walkable is prompt-only
    assert all(reg["recall"] == 1.0 for reg in r.scores["regions"])


def test_shifted_scene_fails_regions_with_bbox_wording():
    r = pc.gate(nearest_upscale(scene(8), 4), scene(), LAYOUT)
    assert not r.passed
    mask_region = r.scores["regions"][0]
    assert mask_region["bbox_pct"] == [31, 30, 50, 70] and mask_region["recall"] < 0.5
    assert any(f.startswith("structure missing inside x 31–50 y 30–70") for f in r.failures)


def test_guide_coloured_lines_fail_leak():
    cand = nearest_upscale(scene(), 4)
    lines = nearest_upscale(pc.guide_lines(LAYOUT)[..., None].astype(np.uint8), 4)[..., 0] > 0
    cand[lines] = (255, 0, 0)
    r = pc.gate(cand, scene(), LAYOUT)
    assert not r.passed and r.leaked and r.scores["leak"] > 0.25   # dilated line pixels dilute it to ~1/3
    assert any("guide colour" in f and "do not draw" in f for f in r.failures)
    clean = pc.gate(nearest_upscale(scene(), 4), scene(), LAYOUT)
    assert not clean.leaked


def test_blit_noise_fails_plain():
    layout = {"schema": 1, "size": [320, 200], "blit": [[20, 20, 100, 60]]}
    cand = nearest_upscale(scene(), 4)
    rng = np.random.default_rng(0)
    cand[80:320, 80:480] = rng.integers(0, 256, size=(240, 400, 3), dtype=np.uint8)
    r = pc.gate(cand, scene(), layout)
    assert any(f.startswith("text or clutter inside plain region x 6–38 y 10–40") for f in r.failures)
    assert pc.gate(nearest_upscale(scene(), 4), scene(), layout).passed


def test_no_layout_reports_only_global_scores():
    r = pc.gate(nearest_upscale(scene(), 4), scene(), None)
    assert set(r.scores) == {"ncc", "edge_recall"} and r.passed and not r.leaked


def test_polygon_mask_fills_concave_polygon():
    L = [(2, 2), (10, 2), (10, 5), (5, 5), (5, 10), (2, 10)]
    m = pc.polygon_mask(L, shape=(12, 12))
    assert m[3, 3] and m[3, 9] and m[8, 3]
    assert not m[8, 8] and not m[0, 0] and not m[11, 11]


def test_flat_regions_report_null_recall_without_failing():
    layout = {"schema": 1, "size": [320, 200], "masks": [[[10, 150], [60, 150], [60, 190], [10, 190]]],
              "collision": [], "walkable": []}
    r = pc.gate(nearest_upscale(scene(), 4), scene(), layout)
    assert r.scores["regions"][0]["recall"] is None and r.passed


def test_scale_zero_passes_anything():
    r = pc.gate(nearest_upscale(scene(40), 4), scene(), LAYOUT, scale=0)
    assert r.passed and r.failures == [] and r.scores["edge_recall"] < 0.6


def test_layout_regions_bboxes_hull_and_filters():
    regions = pc.layout_regions(LAYOUT)
    assert [(r.kind, r.bbox_pct) for r in regions] == [
        ("mask", (31, 30, 50, 70)), ("collision", (69, 10, 84, 25)), ("walkable", (0, 75, 100, 100))]
    assert len(regions[1].polygon) == 4                        # hull of the four live corners
    tiny = {"masks": [[[0, 0], [2, 0], [2, 2]]], "collision": [[None] * 8], "walkable": []}
    assert pc.layout_regions(tiny) == [] and pc.layout_regions(None) == []
    blit = pc.layout_regions({"blit": [[20, 20, 100, 60]]})
    assert blit[0].kind == "blit" and blit[0].bbox_pct == (6, 10, 38, 40)
    assert pc.fmt_bbox((45, 12, 52, 25)) == "x 45–52 y 12–25"


def test_gate_rejects_wrong_shapes():
    with pytest.raises(ValueError):
        pc.gate(np.zeros((400, 640, 3), np.uint8), scene(), LAYOUT)
    with pytest.raises(ValueError):
        pc.gate(nearest_upscale(scene(), 4), np.zeros((100, 160, 3), np.uint8), LAYOUT)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_plate_check.py -q`
Expected: `ModuleNotFoundError: No module named 'tools.plate_check'`.

- [ ] **Step 3: Implement `tools/plate_check.py`**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Offline gate for regenerated plates: does a candidate keep the original's
structure? Pure numpy; no I/O, no network. Scores are compared at 320x200:
the candidate (1280x800) is box-downsampled 4x, both go to luminance, Sobel
edges are thresholded at EDGE_FRACTION of each image's own 95th percentile
magnitude (floored at EDGE_MIN), and the original's edges are checked for a candidate edge within
2 px -- globally and inside every mask / collision region. Guide colours
along the layout's lines are counted as a leak. See
docs/superpowers/specs/2026-08-27-background-layout-fidelity-design.md."""
import dataclasses

import numpy as np

from PyAitD.render.background_export import draw_polyline, layout_segments

W, H = 320, 200
THRESHOLDS = {"ncc": 0.50, "edge_recall": 0.60, "region_recall": 0.50,
              "leak": 0.02, "leak_frame": 0.005, "plain": 0.02}
MIN_REGION_EDGES = 20        # fewer original edge pixels: the region says nothing
MIN_REGION_AREA = 0.005      # of the frame; smaller regions are dropped
EDGE_FRACTION = 0.25         # of the 95th-percentile Sobel magnitude ...
EDGE_MIN = 40.0              # ... with this floor (Sobel of a ~10-level luminance step): a flat or
                             # gently graded image must not turn its every pixel into an "edge"
EDGE_TOLERANCE = 2           # px: dilation of the candidate's edges
BLUR_SIGMA, BLUR_RADIUS = 3.0, 9
SCORED_KINDS = ("mask", "collision")   # walkable is prompt-only; blit is checked for plainness


@dataclasses.dataclass(frozen=True)
class Region:
    kind: str          # mask | collision | walkable | blit
    polygon: tuple     # ((x, y), ...) in 320x200 px
    bbox_pct: tuple    # (x0, y0, x1, y1), whole percent of frame


@dataclasses.dataclass
class GateResult:
    passed: bool
    scores: dict
    failures: list
    leaked: bool = False


def fmt_bbox(bbox):
    x0, y0, x1, y1 = bbox
    return f"x {x0}–{x1} y {y0}–{y1}"


def _hull(points):
    """Andrew's monotone chain; the convex hull as a counter-clockwise list."""
    pts = sorted(set((float(x), float(y)) for x, y in points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _region(kind, polygon):
    pts = tuple((float(x), float(y)) for x, y in polygon)
    if len(pts) < 3:
        return None
    xs = [min(max(x, 0.0), float(W)) for x, _ in pts]
    ys = [min(max(y, 0.0), float(H)) for _, y in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if (x1 - x0) * (y1 - y0) < MIN_REGION_AREA * W * H:
        return None
    bbox = (int(round(x0 * 100 / W)), int(round(y0 * 100 / H)),
            int(round(x1 * 100 / W)), int(round(y1 * 100 / H)))
    return Region(kind, pts, bbox)


def layout_regions(layout):
    """Prompt/gate regions of a layout sidecar: masks and walkable polygons
    as they are (None vertices dropped), each collision box as the convex
    hull of its live corners, blit rects as rectangles. Regions under
    MIN_REGION_AREA of the frame are dropped."""
    if not layout:
        return []
    out = []
    for poly in layout.get("masks", ()):
        out.append(_region("mask", [p for p in poly if p is not None]))
    for corners in layout.get("collision", ()):
        out.append(_region("collision", _hull([c for c in corners if c is not None])))
    for poly in layout.get("walkable", ()):
        out.append(_region("walkable", [p for p in poly if p is not None]))
    for x, y, rw, rh in layout.get("blit", ()):
        out.append(_region("blit", [(x, y), (x + rw, y), (x + rw, y + rh), (x, y + rh)]))
    return [r for r in out if r is not None]


def polygon_mask(polygon, shape=(H, W)):
    """Even-odd scanline fill; a pixel is inside when its centre is."""
    h, w = shape
    mask = np.zeros((h, w), bool)
    pts = [(float(x), float(y)) for x, y in polygon]
    n = len(pts)
    if n < 3:
        return mask
    for row in range(h):
        y = row + 0.5
        xs = []
        for k in range(n):
            (x0, y0), (x1, y1) = pts[k], pts[(k + 1) % n]
            if (y0 <= y) != (y1 <= y):
                xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
        xs.sort()
        for a, b in zip(xs[0::2], xs[1::2]):
            lo, hi = max(int(np.ceil(a - 0.5)), 0), min(int(np.floor(b - 0.5)) + 1, w)
            if hi > lo:
                mask[row, lo:hi] = True
    return mask


def guide_lines(layout):
    """Boolean 320x200 map of every line a guide would draw for `layout`."""
    img = np.zeros((H, W, 3), np.uint8)
    for a, b in layout_segments(layout):
        draw_polyline(img, [a, b], (255, 255, 255))
    return img[..., 0] > 0


def luminance(rgb):
    rgb = np.asarray(rgb, dtype=np.float32)
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def downsample4(candidate):
    c = np.asarray(candidate, dtype=np.float32)
    h, w = c.shape[:2]
    return c.reshape(h // 4, 4, w // 4, 4, 3).mean(axis=(1, 3))


def sobel_magnitude(lum):
    p = np.pad(lum, 1, mode="edge")
    gx = (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])
    gy = (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])
    return np.hypot(gx, gy)


def edge_map(lum):
    mag = sobel_magnitude(lum)
    return mag >= max(EDGE_MIN, EDGE_FRACTION * float(np.percentile(mag, 95)))


def dilate(mask, r):
    if r <= 0:
        return mask.copy()
    h, w = mask.shape
    p = np.pad(mask, r)
    out = np.zeros_like(mask)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out |= p[r + dy:r + dy + h, r + dx:r + dx + w]
    return out


def gaussian_blur(img, sigma=BLUR_SIGMA, radius=BLUR_RADIUS):
    k = np.exp(-0.5 * (np.arange(-radius, radius + 1, dtype=np.float32) / sigma) ** 2)
    k /= k.sum()
    h, w = img.shape
    p = np.pad(img, ((radius, radius), (radius, radius)), mode="edge")
    rows = sum(k[i] * p[:, i:i + w] for i in range(2 * radius + 1))
    return sum(k[i] * rows[i:i + h, :] for i in range(2 * radius + 1))


def ncc(a, b):
    a = a - a.mean()
    b = b - b.mean()
    d = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / d) if d > 0 else 0.0


def _recall(orig_edges, cand_dilated, where=None):
    sel = orig_edges if where is None else (orig_edges & where)
    n = int(sel.sum())
    if n == 0:
        return None, 0
    return float((sel & cand_dilated).sum() / n), n


def guide_band(rgb):
    """Pixels whose colour sits in a guide band: red, blue (COLOR_COLLISION
    is (0, 128, 255)) or green."""
    r, g, b = rgb[..., 0].astype(int), rgb[..., 1].astype(int), rgb[..., 2].astype(int)
    red = (r > 180) & (g < 80) & (b < 80)
    blue = (b > 200) & (g >= 80) & (g <= 180) & (r < 80)
    green = (g > 150) & (r < 80) & (b < 80)
    return red | blue | green


def gate(candidate, original, layout, scale=1.0):
    """Score `candidate` against `original`; see the module docstring.
    `scale` multiplies every threshold; 0 passes everything but still
    reports scores. Failures are worded as corrections for the next
    attempt."""
    candidate = np.asarray(candidate)
    original = np.asarray(original)
    if candidate.shape != (4 * H, 4 * W, 3):
        raise ValueError(f"candidate must be {4 * W}x{4 * H} RGB, got {candidate.shape}")
    if original.shape != (H, W, 3):
        raise ValueError(f"original must be {W}x{H} RGB, got {original.shape}")
    t = {k: v * scale for k, v in THRESHOLDS.items()}
    small = downsample4(candidate)
    lum_c, lum_o = luminance(small), luminance(original)
    edges_o, edges_c = edge_map(lum_o), edge_map(lum_c)
    edges_c2 = dilate(edges_c, EDGE_TOLERANCE)
    scores, failures, leaked = {}, [], False

    scores["ncc"] = ncc(gaussian_blur(lum_c), gaussian_blur(lum_o))
    if scores["ncc"] < t["ncc"]:
        failures.append(f"framing differs (ncc {scores['ncc']:.2f})")
    recall, _ = _recall(edges_o, edges_c2)
    scores["edge_recall"] = 1.0 if recall is None else recall
    if scores["edge_recall"] < t["edge_recall"]:
        failures.append(f"structure differs (edge recall {scores['edge_recall']:.2f})")

    if layout:
        regions = []
        for region in layout_regions(layout):
            where = polygon_mask(region.polygon)
            entry = {"kind": region.kind, "bbox_pct": list(region.bbox_pct)}
            if region.kind in SCORED_KINDS:
                r, n = _recall(edges_o, edges_c2, where)
                entry["recall"] = None if n < MIN_REGION_EDGES else r
                if entry["recall"] is not None and entry["recall"] < t["region_recall"]:
                    failures.append(f"structure missing inside {fmt_bbox(region.bbox_pct)} "
                                    f"(edge recall {entry['recall']:.2f})")
            elif region.kind == "blit":
                entry["plain"] = float((edges_c & where).sum() / max(int(where.sum()), 1))
                if entry["plain"] > t["plain"]:
                    failures.append(f"text or clutter inside plain region {fmt_bbox(region.bbox_pct)} "
                                    f"(edge density {entry['plain']:.3f})")
            else:
                continue
            regions.append(entry)
        scores["regions"] = regions

        band_full = guide_band(candidate)
        band = band_full.reshape(H, 4, W, 4).any(axis=(1, 3))
        lines = dilate(guide_lines(layout), 1)
        n_lines = int(lines.sum())
        scores["leak"] = float((band & lines).sum() / n_lines) if n_lines else 0.0
        scores["leak_frame"] = float(band_full.mean())
        if scores["leak"] > t["leak"]:
            leaked = True
            failures.append(f"guide colour on {scores['leak'] * 100:.0f} % of guide-line pixels: "
                            "do not draw the red, blue or green lines")
        if scores["leak_frame"] > t["leak_frame"]:
            leaked = True
            failures.append(f"guide colours on {scores['leak_frame'] * 100:.1f} % of the frame: "
                            "do not draw the red, blue or green lines")

    if scale == 0:
        failures, leaked = [], False
    return GateResult(not failures, scores, failures, leaked)
```

- [ ] **Step 4: Run the tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_plate_check.py -q`
Expected: PASS. If `test_shifted_scene_fails_regions_with_bbox_wording` passes the gate, the mask region's recall is not < 0.5 for an 8 px shift — check that `_recall` restricts to `where` and that `EDGE_TOLERANCE` is 2, not larger; do not loosen the test.

- [ ] **Step 5: Run the layering suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_layering.py -q`
Expected: PASS (plate_check imports nothing from pygame, moderngl or google).

- [ ] **Step 6: Record the edge floor in the spec**

In `docs/superpowers/specs/2026-08-27-background-layout-fidelity-design.md`, gate section step 2: "each thresholded at 0.25 × its own 95th percentile → binary edge maps" → "each thresholded at max(40, 0.25 × its own 95th percentile) — the floor keeps a flat or gently graded image from turning every pixel into an edge → binary edge maps".

- [ ] **Step 7: Commit**

```bash
git add tools/plate_check.py tests/test_plate_check.py docs/superpowers/specs/2026-08-27-background-layout-fidelity-design.md
git commit -m "feat: offline plate gate — ncc, edge recall per region, guide-colour leak"
```

---

### Task 4: Calibrate the gate on real data

**Files:**
- Modify: `tools/plate_check.py` (`THRESHOLDS`, `guide_band` only if the table demands it)
- Test: `tests/test_plate_check.py` (one data-dependent test)
- Scratch (never committed): `.superpowers/calibrate_gate.py`

**Interfaces:**
- Consumes: Task 1 `layout_geometry`, Task 3 `gate`; the `data_dir` / `profile` fixtures in `tests/conftest.py`; `tools.export_backgrounds.load_floor`; `PyAitD.render.asset_resolver.load_png_rgb`.
- Produces: committed threshold values; `test_every_original_passes_the_gate_against_itself`.

- [ ] **Step 1: Write the data-dependent test**

Append to `tests/test_plate_check.py`:

```python
def test_every_original_passes_the_gate_against_itself(data_dir, profile):
    """Calibration guard: the pixel-art originals must never trip the gate
    or the guide-colour bands (green cloths, blue windows) by themselves."""
    from PyAitD.engine.floor import Floor
    from PyAitD.render.background_export import layout_geometry
    failed = []
    for number in range(8):
        floor = Floor(data_dir, number, profile)
        for cam_idx in range(len(floor.cameras)):
            try:
                original = floor.camera_image(cam_idx)
            except KeyError:
                continue
            r = pc.gate(nearest_upscale(original, 4), original, layout_geometry(floor, cam_idx))
            if not r.passed or r.scores["leak_frame"] >= 0.005:
                failed.append((number, cam_idx, r.failures, r.scores["leak_frame"]))
    assert failed == []
```

- [ ] **Step 2: Run it**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_plate_check.py::test_every_original_passes_the_gate_against_itself -q`
Expected: PASS, or a list of (floor, camera, failures, leak_frame) tuples. A failure here is a calibration input, not a bug: continue to Step 3 either way.

- [ ] **Step 3: Write and run the calibration script**

Create `.superpowers/calibrate_gate.py` (git-ignored scratch):

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Score the gate over real data: originals vs themselves, vs 8 px shifts,
vs the drifted overrides-b plates. Prints one table; never committed."""
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from PyAitD.render.asset_resolver import load_png_rgb
from PyAitD.render.background_export import layout_geometry, nearest_upscale
from tools.export_backgrounds import load_floor
from tools import plate_check as pc

DATA = pathlib.Path("data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK")
DRIFTED = pathlib.Path("data/aitd1/overrides-b/backgrounds")

rows = {"self": [], "shift8": [], "drifted": []}
for number in range(8):
    floor = load_floor(DATA, number)
    for cam_idx in range(len(floor.cameras)):
        try:
            original = floor.camera_image(cam_idx)
        except KeyError:
            continue
        layout = layout_geometry(floor, cam_idx)
        rows["self"].append(pc.gate(nearest_upscale(original, 4), original, layout))
        rows["shift8"].append(pc.gate(nearest_upscale(np.roll(original, 8, axis=1), 4), original, layout))
        plate = DRIFTED / f"floor{number:02d}" / f"camera{cam_idx:03d}.png"
        if plate.is_file():
            rows["drifted"].append(pc.gate(load_png_rgb(plate), original, layout))

for name, results in rows.items():
    n = len(results)
    passed = sum(r.passed for r in results)
    ncc = np.array([r.scores["ncc"] for r in results])
    rec = np.array([r.scores["edge_recall"] for r in results])
    leak = np.array([r.scores["leak_frame"] for r in results])
    region_fail = sum(any(f.startswith("structure missing") for f in r.failures) for r in results)
    print(f"{name:8} n={n:3} pass={passed:3} ncc[min p5 p50]={ncc.min():.2f} {np.percentile(ncc, 5):.2f} {np.median(ncc):.2f} "
          f"recall[min p5 p50]={rec.min():.2f} {np.percentile(rec, 5):.2f} {np.median(rec):.2f} "
          f"leak_frame[max]={leak.max():.4f} region_fail={region_fail}")
```

Run: `SDL_VIDEODRIVER=dummy .venv/bin/python .superpowers/calibrate_gate.py`
Expected: three rows. Targets: `self` pass = n and `leak_frame[max]` < 0.005; `shift8` pass ≤ 10 % of n; `drifted` pass well under half of n.

- [ ] **Step 4: Adjust the constants only as the table demands**

Rules (apply in order, then rerun the script and the test from Step 2):
1. If any `self` plate fails `ncc` or `edge_recall`, lower that threshold to `0.05` below the `self` minimum (rounded down to 0.05). If `self` fails a region, lower `region_recall` the same way.
2. If `self` `leak_frame[max]` ≥ 0.005, tighten the offending band in `guide_band` (raise the dominant-channel floor by 20 and lower the other-channel ceilings by 20, once) and rerun; repeat once more at most. Record the final bands in the commit message.
3. If `shift8` passes more than 10 % of plates, raise `region_recall` by 0.05 (never above 0.70) and rerun; if that breaks rule 1, keep rule 1 and note the trade-off.
4. Leave everything else at the spec defaults.

Write the final table into the commit message body verbatim.

- [ ] **Step 5: Run the gate tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_plate_check.py -q`
Expected: PASS, including the data-dependent test.

- [ ] **Step 6: Commit**

```bash
git add tools/plate_check.py tests/test_plate_check.py
git commit -m "test: calibrate the plate gate on the 144 originals and the drifted overrides-b run

<paste the calibration table here>"
```

Do not `git add .superpowers/`.

---

### Task 5: Structured describe, inventory cache, new generation prompt

**Files:**
- Modify: `tools/regenerate_backgrounds.py` (`Camera`, `discover`, prompt constants, `describe_prompt`, `generation_prompt`, `describe`, `regenerate`'s cache and prompt code)
- Test: `tests/test_regenerate_backgrounds.py`

**Interfaces:**
- Consumes: Task 3 `plate_check.layout_regions`, `plate_check.fmt_bbox`, `Region`.
- Produces:
  - `Camera(floor, camera, source, guide, key, layout=None)`; `discover` sets `layout` to `IN/guides/<key>.json` when it exists.
  - `GAME_CONTEXT: str` (verbatim from the spec), `INVENTORY_SCHEMA: dict`.
  - `agy_structured(model, instructions, schema) -> dict` — runs `agy … --output-format json --json-schema <json>`, returns `structured_output`; `RuntimeError("agy returned no structured output")` otherwise.
  - `describe(model, cam) -> dict` (the inventory: `prompt`, `camera`, `objects[]`); raises `RuntimeError("empty description from text model")` / `RuntimeError("empty inventory from text model")`.
  - `generation_prompt(inventory, style, regions=(), corrections=(), rejected_attempt=0, guide_attached=False, screen=False) -> str`.
  - `prompts.json` entries: `{"inventory": {...}, "model": str, "sha256": str}`; entries without `"inventory"` are stale.
  - `load_json(path) -> dict`, `save_json(path, data)` (atomic); `load_prompts`/`save_prompts` stay as aliases.

- [ ] **Step 1: Replace `FakeSubprocess` and rewrite the describe/prompt tests**

In `tests/test_regenerate_backgrounds.py`, replace the `FakeSubprocess` class with this version (the generate branch keeps the old contract for now; Task 6 changes it):

```python
INVENTORY = {"prompt": "a dusty attic under sloped rafters", "camera": "eye level, wide, from the stairs",
             "objects": [{"name": "window", "kind": "small square window", "count": 1, "bbox": [45, 12, 52, 25]},
                         {"name": "barrels", "kind": "wooden barrels", "count": 3, "bbox": [55, 22, 66, 34]}]}


def envelope(obj):
    return json.dumps({"status": "SUCCESS", "structured_output": obj})


class FakeSubprocess:
    """Stands in for the agy CLI. `describe` is the structured output for
    describe calls (None -> an envelope without structured_output); `judge`
    is a list of verdicts handed out in order (Task 7); `image_png` is what
    a generate call copies to the requested path."""

    def __init__(self, image_png=None, fail_image_calls=(), no_image=False, describe=INVENTORY, judge=()):
        self.image_png = image_png
        self.fail = set(fail_image_calls)
        self.no_image = no_image
        self.describe = describe
        self.judge = list(judge)
        self.calls = []
        self.image_calls = 0

    def run(self, cmd, capture_output=True, text=True, check=True):
        self.calls.append(cmd)
        prompt = cmd[2]
        if "--json-schema" in cmd:
            if "For every inventory object" in prompt:
                verdict = self.judge.pop(0)
                return _t.SimpleNamespace(stdout=envelope(verdict), returncode=0)
            if self.describe is None:
                return _t.SimpleNamespace(stdout=json.dumps({"status": "SUCCESS"}), returncode=0)
            return _t.SimpleNamespace(stdout=envelope(self.describe), returncode=0)
        self.image_calls += 1
        if self.image_calls in self.fail:
            raise subprocess.CalledProcessError(1, cmd, output="quota")
        if not self.no_image and self.image_png:
            m = re.search(r"this path: (.*?)\. (?:Then output|Output)", prompt)
            if m:
                with open(m.group(1), "wb") as f:
                    f.write(self.image_png)
        return _t.SimpleNamespace(stdout="SUCCESS\n", returncode=0)
```

Replace `test_prompts_mention_guide_only_when_present`, `test_describe_sends_source_guide_and_prompt`, `test_describe_without_guide_sends_no_guide_prompt` and `test_describe_raises_on_empty_text` with:

```python
def test_discover_finds_layout_sidecars(tmp_path):
    in_dir = make_in_dir(tmp_path)
    (in_dir / "guides" / "floor00").mkdir(parents=True, exist_ok=True)
    (in_dir / "guides" / "floor00" / "camera000.json").write_text(json.dumps({"schema": 1}))
    cams = rb.discover(in_dir, None)
    assert cams[0].layout == in_dir / "guides" / "floor00" / "camera000.json"
    assert cams[1].layout is None


def test_describe_prompt_opens_with_game_context_and_asks_for_objects():
    text = rb.describe_prompt(True)
    assert text.startswith(rb.GAME_CONTEXT)
    assert "Alone in the Dark 1" in rb.GAME_CONTEXT and "Lovecraftian" in rb.GAME_CONTEXT
    assert "second image" in text and "bounding box" in text
    assert "the game" not in text.replace(rb.GAME_CONTEXT, "")
    assert "second image" not in rb.describe_prompt(False)


def test_describe_returns_the_inventory_and_sends_schema(tmp_path, monkeypatch):
    cam = rb.discover(make_in_dir(tmp_path), None)[0]
    fake = FakeSubprocess()
    monkeypatch.setattr(subprocess, "run", fake.run)
    assert rb.describe("gemini-3.1-pro", cam) == INVENTORY
    cmd = fake.calls[0]
    assert cmd[0] == "agy" and "gemini-3.1-pro" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == rb.INVENTORY_SCHEMA
    assert str(cam.source.absolute()) in cmd[2] and str(cam.guide.absolute()) in cmd[2]


def test_describe_without_guide_sends_no_guide_prompt(tmp_path, monkeypatch):
    cam = rb.discover(make_in_dir(tmp_path), None)[1]
    fake = FakeSubprocess()
    monkeypatch.setattr(subprocess, "run", fake.run)
    rb.describe("gemini-3.1-pro", cam)
    assert "guide image" not in fake.calls[0][2] and "second image" not in fake.calls[0][2]


@pytest.mark.parametrize("bad, message", [
    (None, "no structured output"),
    ({"prompt": "  ", "camera": "c", "objects": [{"name": "x", "kind": "x", "count": 1, "bbox": [0, 0, 1, 1]}]},
     "empty description from text model"),
    ({"prompt": "p", "camera": "c", "objects": []}, "empty inventory from text model"),
])
def test_describe_rejects_bad_inventories(tmp_path, bad, message, monkeypatch):
    cam = rb.discover(make_in_dir(tmp_path), None)[0]
    fake = FakeSubprocess(describe=bad)
    monkeypatch.setattr(subprocess, "run", fake.run)
    with pytest.raises(RuntimeError, match=message):
        rb.describe("gemini-3.1-pro", cam)


def test_generation_prompt_order_and_contents():
    from tools.plate_check import Region
    regions = [Region("mask", ((0, 0),), (10, 20, 30, 40)), Region("collision", ((0, 0),), (50, 60, 70, 80)),
               Region("walkable", ((0, 0),), (0, 75, 100, 100))]
    text = rb.generation_prompt(INVENTORY, "film grain.", regions, ["window drawn at x 60–68"],
                                rejected_attempt=1, guide_attached=True)
    assert text.startswith(rb.GAME_CONTEXT)
    i = {s: text.index(s) for s in (
        "Re-render the first image as a photorealistic photograph",
        "second image marks the layout",
        "Layout (percent of frame, x left→right, y top→bottom): 1 small square window x 45–52 y 12–25; 3 wooden barrels x 55–66 y 22–34.",
        "Foreground occluders at x 10–30 y 20–40; solid walls and furniture at x 50–70 y 60–80; walkable floor at x 0–100 y 75–100.",
        "Attempt 1 was rejected: window drawn at x 60–68.",
        "eye level, wide, from the stairs", "a dusty attic under sloped rafters")}
    order = sorted(i, key=i.get)
    assert order == list(i)
    assert text.endswith(" film grain.")
    plain = rb.generation_prompt(INVENTORY, "s.", guide_attached=False)
    assert "second image" not in plain and "Attempt" not in plain and "occluders" not in plain


def test_screen_generation_prompt_uses_illustration_wording():
    from tools.plate_check import Region
    text = rb.generation_prompt(INVENTORY, "", [Region("blit", ((0, 0),), (3, 5, 47, 95))],
                                guide_attached=True, screen=True)
    assert "painted illustration of exactly this composition" in text
    assert "Regions that must stay plain: x 3–47 y 5–95." in text
    assert "drawn there by the game" in text and "walkable" not in text
```

Update the regenerate-level tests that inspect prompts for the inventory cache:
- `test_regenerate_writes_fitted_pngs_and_prompt_cache`: the expected cache entry becomes `{"inventory": INVENTORY, "model": "gemini-3.1-pro", "sha256": ...}`; the last assertion becomes `assert rb.generation_prompt(INVENTORY, "s.", guide_attached=True) in gen_prompt`.
- `test_regenerate_resumes_and_force_redoes`: edit `prompts["floor00/camera001"]["inventory"]["prompt"] = "EDITED"` and assert the reread `["inventory"]["prompt"]` values instead of `["prompt"]`.
- `test_regenerate_counts_empty_description_as_failed`: construct `FakeSubprocess(png, describe={"prompt": "", "camera": "c", "objects": []})` and keep its assertions.
- Add:

```python
def test_regenerate_redescribes_a_schema_1_prompt_entry(tmp_path, monkeypatch):
    fake = FakeSubprocess(png_bytes(np.zeros((1024, 1536, 3), np.uint8)))
    monkeypatch.setattr(subprocess, "run", fake.run)
    out = tmp_path / "out"
    cams = rb.discover(make_in_dir(tmp_path), {1})
    sha = hashlib.sha256(cams[0].source.read_bytes()).hexdigest()
    rb.save_prompts(out / rb.PROMPTS_FILE, {"floor01/camera000": {"prompt": "old prose", "model": "m", "sha256": sha}})
    assert rb.regenerate(cams, out, text_model="t", style="s.", force=False, dry_run=False,
                         log=lambda *_: None) == (1, 0)
    assert "--json-schema" in fake.calls[0]                       # re-described despite a matching sha
    assert rb.load_prompts(out / rb.PROMPTS_FILE)["floor01/camera000"]["inventory"] == INVENTORY
```

Every `rb.regenerate(...)` / `_run(...)` call in the file drops `image_model=...` (the keyword is removed in this task); `test_main_runs_with_injected_subprocess_and_reports_failures` drops `"--image-model", "image-x"` from its argv and the `fake.calls[1]` model assertion stays.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_regenerate_backgrounds.py -q`
Expected: the new/changed tests FAIL (`TypeError` on `layout`, missing `GAME_CONTEXT`, `regenerate() got an unexpected keyword`), dry-run and discover tests still pass.

- [ ] **Step 3: Implement**

In `tools/regenerate_backgrounds.py`:

Imports: add `from tools.plate_check import fmt_bbox, layout_regions` next to the `export_backgrounds` import. Remove `DEFAULT_IMAGE_MODEL`.

`Camera` gains a trailing `layout: pathlib.Path | None = None`. In `discover`, for cameras and screens alike, after computing `guide`:

```python
        layout = in_dir / "guides" / f"{key}.json"
        cams.append(Camera(floor, cam, path, guide if guide.is_file() else None, key,
                           layout if layout.is_file() else None))
```

(screens: `Camera(-1, entry, path, guide if guide.is_file() else None, key, layout if layout.is_file() else None)`).

Prompt constants — replace `describe_prompt` and `generation_prompt`:

```python
GAME_CONTEXT = ("This image depicts a scene from the Alone in the Dark 1 game. Atmosphere notes: The "
                "entire Alone in the Dark 1 game evokes a gothic horror/Lovecraftian mood. The darkness, "
                "somber portraits, and period-appropriate text work together to set the tone before the "
                "player even enters the mansion. The design is effective at establishing dread and mystery.")

INVENTORY_SCHEMA = {
    "type": "object", "required": ["prompt", "camera", "objects"],
    "properties": {
        "prompt": {"type": "string"},
        "camera": {"type": "string"},
        "objects": {"type": "array", "items": {
            "type": "object", "required": ["name", "kind", "count", "bbox"],
            "properties": {"name": {"type": "string"}, "kind": {"type": "string"},
                           "count": {"type": "integer", "minimum": 1},
                           "bbox": {"type": "array", "minItems": 4, "maxItems": 4,
                                    "items": {"type": "integer", "minimum": 0, "maximum": 100}}}}}}}

_CAMERA_RERENDER = ("Re-render the first image as a photorealistic photograph of exactly this scene: same "
                    "camera position, framing and perspective; every wall, door, window, stair and piece "
                    "of furniture stays where it is, same kind and same count — add nothing, remove "
                    "nothing. Change only materials, lighting detail and realism.")
_SCREEN_RERENDER = ("Re-render the first image as a painted illustration of exactly this composition, "
                    "keeping the framing and every element's placement; change only the medium and finish.")
_REGION_LABELS = (("mask", "foreground occluders at "), ("collision", "solid walls and furniture at "),
                  ("walkable", "walkable floor at "))


def describe_prompt(guide_present, screen=False):
    text = (GAME_CONTEXT + " Describe this 320x200 background as a single-paragraph prompt for a "
            "photorealistic image generator. Name the room type, the camera angle and height, every "
            "piece of furniture and architecture with its position in frame, the light sources and "
            "their direction, materials and colours, and the mood. Do not mention pixel art or "
            "resolution. Then list every distinct object with its kind, count and bounding box in "
            "percent of frame (x0, y0, x1, y1; x left to right, y top to bottom).")
    if not guide_present:
        return text
    return text + " " + (_SCREEN_DESCRIBE if screen else _GUIDE_DESCRIBE)


def _bbox_list(bbox):
    x0, y0, x1, y1 = bbox
    return fmt_bbox((x0, y0, x1, y1))


def generation_prompt(inventory, style, regions=(), corrections=(), rejected_attempt=0,
                      guide_attached=False, screen=False):
    """The Prompt argument of the generate_image call, in the spec's order:
    game context, re-render instruction, guide sentence, layout from the
    inventory and the sidecar regions, corrections from the last rejected
    attempt, the inventory's camera and prose, then `style` verbatim."""
    parts = [GAME_CONTEXT, _SCREEN_RERENDER if screen else _CAMERA_RERENDER]
    if guide_attached:
        parts.append(_SCREEN_GENERATE if screen else _GUIDE_GENERATE)
    objects = "; ".join(f"{o['count']} {o['kind']} {_bbox_list(o['bbox'])}" for o in inventory["objects"])
    parts.append("Layout (percent of frame, x left→right, y top→bottom): " + objects + ".")
    by_kind = {}
    for region in regions:
        by_kind.setdefault(region.kind, []).append(fmt_bbox(region.bbox_pct))
    if screen:
        if by_kind.get("blit"):
            parts.append("Regions that must stay plain: " + "; ".join(by_kind["blit"]) + ".")
    else:
        clauses = [label + ", ".join(by_kind[kind]) for kind, label in _REGION_LABELS if by_kind.get(kind)]
        if clauses:
            sentence = "; ".join(clauses)
            parts.append(sentence[0].upper() + sentence[1:] + ".")
    if corrections:
        parts.append(f"Attempt {rejected_attempt} was rejected: " + "; ".join(corrections) + ".")
    parts.append(inventory["camera"].strip())
    parts.append(inventory["prompt"].strip())
    return " ".join(p for p in parts if p) + " " + style
```

Structured calls and `describe`:

```python
def agy_structured(model, instructions, schema):
    """One agy call with an enforced JSON schema; returns structured_output."""
    cmd = ["agy", "-p", instructions, "--dangerously-skip-permissions", "--effort", "low",
           "--model", model, "--output-format", "json", "--json-schema", json.dumps(schema)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        payload = None
    out = payload.get("structured_output") if isinstance(payload, dict) else None
    if not isinstance(out, dict):
        raise RuntimeError("agy returned no structured output")
    return out


def describe(model, cam):
    """One text-model call via agy: original (+ guide) -> inventory dict."""
    instructions = f"Look at the image at {cam.source.absolute()}. "
    if cam.guide:
        instructions += f"Also look at the guide image at {cam.guide.absolute()}. "
    instructions += describe_prompt(cam.guide is not None, screen=cam.floor == -1)
    inventory = agy_structured(model, instructions, INVENTORY_SCHEMA)
    if not str(inventory.get("prompt", "")).strip():
        raise RuntimeError("empty description from text model")
    if not inventory.get("objects"):
        raise RuntimeError("empty inventory from text model")
    return inventory
```

JSON helpers — rename `load_prompts`/`save_prompts` bodies to `load_json`/`save_json` and keep `load_prompts = load_json`, `save_prompts = save_json`.

`regenerate` — drop the `image_model` parameter; replace the describe/prompt block:

```python
            source_sha = hashlib.sha256(cam.source.read_bytes()).hexdigest()
            entry = prompts.get(cam.key)
            stale = entry is None or "inventory" not in entry or entry.get("sha256") != source_sha
            if stale or force:
                inventory = describe(text_model, cam)
                prompts[cam.key] = {"inventory": inventory, "model": text_model, "sha256": source_sha}
                save_prompts(prompts_path, prompts)
            inventory = prompts[cam.key]["inventory"]
            layout = json.loads(cam.layout.read_text()) if cam.layout else None
            prompt = generation_prompt(inventory, style, layout_regions(layout),
                                       guide_attached=cam.guide is not None, screen=cam.floor == -1)
            image = generate(text_model, cam, prompt)
```

and `cached = "yes" if cam.key in prompts and "inventory" in prompts[cam.key] else "no"`. In `_parse_args` remove `--image-model`; in `main` drop `image_model=`.

- [ ] **Step 4: Run the tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_regenerate_backgrounds.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/regenerate_backgrounds.py tests/test_regenerate_backgrounds.py
git commit -m "feat: describe returns a structured inventory; prompts carry game context, layout and corrections"
```

---

### Task 6: The `generate_image` call contract

**Files:**
- Modify: `tools/regenerate_backgrounds.py` (`generate`, new helpers, `regenerate`'s generate block)
- Test: `tests/test_regenerate_backgrounds.py`

**Interfaces:**
- Consumes: `PyAitD.render.background_export.nearest_upscale`, `PyAitD.render.asset_resolver.load_png_rgb`, `tools.export_backgrounds.save_png`.
- Produces:
  - `make_reference(cam) -> pathlib.Path` — temp PNG of the original upscaled 4× (caller unlinks).
  - `temp_png() -> pathlib.Path` — an empty temp file with `.png` suffix (caller unlinks).
  - `attachments(cam, ref, leaked) -> list[pathlib.Path]` — `[ref, cam.guide]`, or `[ref]` when `leaked` or no guide.
  - `image_name(cam) -> "plate_fNN_cNNN" | "screen_ressNN"`.
  - `generate(model, cam, prompt, attached, out_path) -> bytes`; `RuntimeError("no image generated or copied by agent")` when `out_path` is missing or empty.

- [ ] **Step 1: Update the fake and write the failing tests**

In `FakeSubprocess.run`, the generate branch's regex becomes `r"this path: (.*?)\. Output ONLY the word SUCCESS"`. Replace `test_generate_requests_image_and_returns_bytes` and `test_generate_without_image_part_raises` with:

```python
def test_generate_dictates_the_tool_call(tmp_path, monkeypatch):
    cam = rb.discover(make_in_dir(tmp_path), None)[0]
    png = png_bytes(np.zeros((1024, 1536, 3), np.uint8))
    fake = FakeSubprocess(png)
    monkeypatch.setattr(subprocess, "run", fake.run)
    ref, out = tmp_path / "ref.png", tmp_path / "out.png"
    ref.write_bytes(b"x")
    assert rb.generate("gemini-3.1-pro", cam, "the prompt", [ref, cam.guide], out) == png
    cmd = fake.calls[0]
    assert cmd[0] == "agy" and "gemini-3.1-pro" in cmd and "--json-schema" not in cmd
    text = cmd[2]
    assert f'ImagePaths = ["{ref.absolute()}", "{cam.guide.absolute()}"]' in text
    assert 'AspectRatio = "3:2"' in text and 'ImageName = "plate_f00_c000"' in text
    assert f"copy the generated image file to exactly this path: {out}. Output ONLY the word SUCCESS" in text
    assert "---PROMPT---\nthe prompt\n---END---" in text
    assert "Look at the image" not in text


def test_generate_raises_when_nothing_was_copied(tmp_path, monkeypatch):
    cam = rb.discover(make_in_dir(tmp_path), None)[0]
    fake = FakeSubprocess(no_image=True)
    monkeypatch.setattr(subprocess, "run", fake.run)
    out = rb.temp_png()
    try:
        with pytest.raises(RuntimeError, match="no image generated or copied by agent"):
            rb.generate("gemini-3.1-pro", cam, "p", [tmp_path / "ref.png"], out)
    finally:
        out.unlink(missing_ok=True)


def test_reference_and_attachment_rules(tmp_path):
    cams = rb.discover(make_in_dir(tmp_path), None)
    ref = rb.make_reference(cams[0])
    try:
        assert load_png_rgb(ref).shape == (800, 1280, 3)
        assert rb.attachments(cams[0], ref, leaked=False) == [ref, cams[0].guide]
        assert rb.attachments(cams[0], ref, leaked=True) == [ref]
        assert rb.attachments(cams[1], ref, leaked=False) == [ref]         # no guide
    finally:
        ref.unlink()
    assert rb.image_name(cams[0]) == "plate_f00_c000"
    assert rb.image_name(rb.Camera(-1, 10, cams[0].source, None, "screens/ress10")) == "screen_ress10"


def test_regenerate_attaches_reference_and_guide_and_cleans_up(tmp_path, monkeypatch):
    fake = FakeSubprocess(png_bytes(np.zeros((1024, 1536, 3), np.uint8)))
    monkeypatch.setattr(subprocess, "run", fake.run)
    before = set(pathlib.Path(tempfile.gettempdir()).glob("*.png"))
    assert _run(tmp_path, fake) == (3, 0)
    gen = [c[2] for c in fake.calls if "--json-schema" not in c]
    assert gen[0].count(".png") >= 2 and str((tmp_path / "in/guides/floor00/camera000.png").absolute()) in gen[0]
    assert str((tmp_path / "in/guides/floor00/camera000.png").absolute()) not in gen[1]   # camera001 has no guide
    assert set(pathlib.Path(tempfile.gettempdir()).glob("*.png")) == before
```

Add `import tempfile` to the test module's imports.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_regenerate_backgrounds.py -q`
Expected: the four new tests FAIL (`TypeError: generate() takes 3 positional arguments`, `AttributeError: temp_png`), plus every regenerate-level test whose fake no longer matches the old copy phrasing.

- [ ] **Step 3: Implement**

Replace `generate` with:

```python
def temp_png():
    """An empty temp file with a .png suffix; the caller unlinks it."""
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    return pathlib.Path(path)


def make_reference(cam):
    """The original upscaled 4x (nearest) as a temp PNG: the first reference
    image of every generate call, at the guide's scale. Caller unlinks."""
    from PyAitD.render.asset_resolver import load_png_rgb
    from PyAitD.render.background_export import nearest_upscale
    path = temp_png()
    save_png(path, nearest_upscale(load_png_rgb(cam.source), 4))
    return path


def attachments(cam, ref, leaked):
    """Reference images for a generate call: [ref, guide] until an attempt
    leaks guide colours into the plate, then [ref] only."""
    if leaked or cam.guide is None:
        return [ref]
    return [ref, cam.guide]


def image_name(cam):
    return f"screen_ress{cam.camera:02d}" if cam.floor == -1 else f"plate_f{cam.floor:02d}_c{cam.camera:03d}"


def generate(model, cam, prompt, attached, out_path):
    """One image-model call via agy: dictate the generate_image tool call
    (references, aspect, name, prompt) and read the copied result."""
    paths = ", ".join(f'"{pathlib.Path(p).absolute()}"' for p in attached)
    instructions = (
        f"Call the generate_image tool exactly once with these arguments: ImagePaths = [{paths}]; "
        f'AspectRatio = "{GENERATE_ASPECT}"; ImageName = "{image_name(cam)}"; Prompt = the text between '
        f"the markers below. Then copy the generated image file to exactly this path: {out_path}. "
        f"Output ONLY the word SUCCESS.\n---PROMPT---\n{prompt}\n---END---")
    cmd = ["agy", "-p", instructions, "--dangerously-skip-permissions", "--effort", "low", "--model", model]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    out_path = pathlib.Path(out_path)
    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise RuntimeError("no image generated or copied by agent")
    return out_path.read_bytes()
```

Add `from tools.export_backgrounds import parse_floors, save_png` (already imported) and use it in `make_reference`. In `regenerate`, replace `image = generate(text_model, cam, prompt)` with:

```python
            ref = make_reference(cam)
            try:
                attached = attachments(cam, ref, leaked=False)
                prompt = generation_prompt(inventory, style, layout_regions(layout),
                                           guide_attached=len(attached) > 1, screen=cam.floor == -1)
                out = temp_png()
                try:
                    image = generate(text_model, cam, prompt, attached, out)
                finally:
                    out.unlink(missing_ok=True)
            finally:
                ref.unlink(missing_ok=True)
```

(the earlier `prompt = generation_prompt(...)` line from Task 5 moves inside this block). `tempfile` is already imported.

- [ ] **Step 4: Run the tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_regenerate_backgrounds.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/regenerate_backgrounds.py tests/test_regenerate_backgrounds.py
git commit -m "feat: generate dictates the generate_image call with the upscaled original and guide attached"
```

---

### Task 7: The judge

**Files:**
- Modify: `tools/regenerate_backgrounds.py` (`JUDGE_SCHEMA`, `judge`, `judge_accepts`, `judge_corrections`)
- Test: `tests/test_regenerate_backgrounds.py`

**Interfaces:**
- Consumes: Task 5 `agy_structured`, `GAME_CONTEXT`.
- Produces:
  - `JUDGE_SCHEMA: dict` (verbatim from the spec).
  - `judge(model, cam, inventory, ref_path, candidate_path) -> dict` (the verdict).
  - `judge_accepts(verdict, inventory) -> bool`.
  - `judge_corrections(verdict, inventory) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_regenerate_backgrounds.py`:

```python
GOOD_VERDICT = {"camera_same": True, "guide_lines_visible": False,
                "objects": [{"name": "window", "present": True, "same_kind": True, "same_count": True,
                             "same_position": True, "note": ""},
                            {"name": "barrels", "present": True, "same_kind": True, "same_count": True,
                             "same_position": True, "note": ""}],
                "extra_objects": [], "corrections": []}


def _verdict(**changes):
    v = json.loads(json.dumps(GOOD_VERDICT))
    v.update(changes)
    return v


def test_judge_sends_both_images_the_inventory_and_the_schema(tmp_path, monkeypatch):
    cam = rb.discover(make_in_dir(tmp_path), None)[0]
    fake = FakeSubprocess(judge=[GOOD_VERDICT])
    monkeypatch.setattr(subprocess, "run", fake.run)
    ref, cand = tmp_path / "ref.png", tmp_path / "cand.png"
    assert rb.judge("gemini-3.1-pro", cam, INVENTORY, ref, cand) == GOOD_VERDICT
    cmd = fake.calls[0]
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == rb.JUDGE_SCHEMA
    text = cmd[2]
    assert str(ref.absolute()) in text and str(cand.absolute()) in text
    assert rb.GAME_CONTEXT in text and json.dumps(INVENTORY["objects"]) in text
    assert "For every inventory object" in text and "within about 5 %" in text


def test_judge_accepts_only_a_fully_matching_verdict():
    assert rb.judge_accepts(GOOD_VERDICT, INVENTORY)
    assert not rb.judge_accepts(_verdict(camera_same=False), INVENTORY)
    assert not rb.judge_accepts(_verdict(guide_lines_visible=True), INVENTORY)
    assert not rb.judge_accepts(_verdict(extra_objects=["table"]), INVENTORY)
    bad = _verdict()
    bad["objects"][1]["same_count"] = False
    assert not rb.judge_accepts(bad, INVENTORY)
    unreported = _verdict(objects=GOOD_VERDICT["objects"][:1])
    assert not rb.judge_accepts(unreported, INVENTORY)


def test_judge_corrections_name_every_problem():
    v = _verdict(camera_same=False, guide_lines_visible=True, extra_objects=["table"],
                 corrections=["move the window left"])
    v["objects"][1].update(same_count=False, note="four barrels instead of three")
    v["objects"] = v["objects"][:2]
    out = rb.judge_corrections(v, INVENTORY)
    assert out[0] == "move the window left"
    assert "barrels: four barrels instead of three" in out
    assert "extra object: table" in out
    assert "red, blue or green guide lines are visible: do not draw them" in out
    assert "camera position, framing or perspective differs" in out
    assert rb.judge_corrections(GOOD_VERDICT, INVENTORY) == []
    missing = _verdict(objects=GOOD_VERDICT["objects"][:1])
    assert "barrels: not assessed by the judge" in rb.judge_corrections(missing, INVENTORY)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_regenerate_backgrounds.py -k judge -q`
Expected: FAIL with `AttributeError: ... has no attribute 'judge'`.

- [ ] **Step 3: Implement**

Add to `tools/regenerate_backgrounds.py` after `describe`:

```python
JUDGE_SCHEMA = {
    "type": "object",
    "required": ["camera_same", "guide_lines_visible", "objects", "extra_objects", "corrections"],
    "properties": {
        "camera_same": {"type": "boolean"},
        "guide_lines_visible": {"type": "boolean"},
        "objects": {"type": "array", "items": {
            "type": "object",
            "required": ["name", "present", "same_kind", "same_count", "same_position", "note"],
            "properties": {"name": {"type": "string"}, "present": {"type": "boolean"},
                           "same_kind": {"type": "boolean"}, "same_count": {"type": "boolean"},
                           "same_position": {"type": "boolean"}, "note": {"type": "string"}}}},
        "extra_objects": {"type": "array", "items": {"type": "string"}},
        "corrections": {"type": "array", "items": {"type": "string"}}}}

_OBJECT_FLAGS = ("present", "same_kind", "same_count", "same_position")


def judge(model, cam, inventory, ref_path, candidate_path):
    """One text-model call via agy: original + candidate + inventory -> verdict."""
    instructions = (
        f"Look at the image at {pathlib.Path(ref_path).absolute()} (the original) and the image at "
        f"{pathlib.Path(candidate_path).absolute()} (the candidate). {GAME_CONTEXT} The original's "
        f"inventory is: {json.dumps(inventory['objects'])} For every inventory object report whether it "
        "is present in the candidate, of the same kind, the same count, and at the same position (within "
        "about 5 % of the frame). List objects in the candidate that are not in the inventory. Say whether "
        "the camera position, framing and perspective are the same, and whether any red, blue or green "
        "outline lines are visible. Give one short correction sentence per problem.")
    return agy_structured(model, instructions, JUDGE_SCHEMA)


def _reported(verdict):
    return {o.get("name"): o for o in verdict.get("objects", [])}


def judge_accepts(verdict, inventory):
    if not verdict.get("camera_same") or verdict.get("guide_lines_visible") or verdict.get("extra_objects"):
        return False
    reported = _reported(verdict)
    for obj in inventory["objects"]:
        r = reported.get(obj["name"])
        if r is None or not all(r.get(flag) for flag in _OBJECT_FLAGS):
            return False
    return True


def judge_corrections(verdict, inventory):
    """Corrections for the next attempt: the judge's own sentences, then one
    line per failing or unreported object, extra object and flag."""
    out = list(verdict.get("corrections", []))
    reported = _reported(verdict)
    for obj in inventory["objects"]:
        r = reported.get(obj["name"])
        if r is None:
            out.append(f"{obj['name']}: not assessed by the judge")
        elif not all(r.get(flag) for flag in _OBJECT_FLAGS):
            out.append(f"{obj['name']}: {r.get('note') or 'differs from the original'}")
    for extra in verdict.get("extra_objects", []):
        out.append(f"extra object: {extra}")
    if verdict.get("guide_lines_visible"):
        out.append("red, blue or green guide lines are visible: do not draw them")
    if not verdict.get("camera_same"):
        out.append("camera position, framing or perspective differs")
    return out
```

- [ ] **Step 4: Run the tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_regenerate_backgrounds.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/regenerate_backgrounds.py tests/test_regenerate_backgrounds.py
git commit -m "feat: vision judge with a structured verdict, acceptance rule and corrections"
```

---

### Task 8: Attempt loop, report, abort limits, CLI and Makefile

**Files:**
- Modify: `tools/regenerate_backgrounds.py` (`regenerate`, new `_process_camera`, `CameraOutcome`, constants, `_parse_args`, `main`)
- Modify: `Makefile:121-122`
- Test: `tests/test_regenerate_backgrounds.py`

**Interfaces:**
- Consumes: Tasks 3, 5, 6, 7: `gate`, `THRESHOLDS`, `describe`, `generation_prompt`, `make_reference`, `temp_png`, `attachments`, `generate`, `judge`, `judge_accepts`, `judge_corrections`, `layout_regions`; `fit_to_target`, `save_png`.
- Produces:
  - `regenerate(cams, out_dir, *, text_model, style, attempts=3, gate_scale=1.0, force, dry_run, log=print) -> (done, failed)`.
  - `REPORT_FILE = "report.json"`, `MAX_CONSECUTIVE_REJECTS = 5`, `REJECT_ABORT` message.
  - `CameraOutcome(status: "ok" | "rejected" | "error", attempts: list, message: str)`.
  - CLI `--attempts N` (≥ 1, default 3), `--gate-scale F` (≥ 0, default 1.0); `--image-model` gone.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_regenerate_backgrounds.py`:

```python
def _gate_script(monkeypatch, outcomes):
    """Make rb.gate return scripted results: each entry is (passed, leaked, failures)."""
    from tools.plate_check import GateResult
    queue = list(outcomes)
    calls = []

    def fake_gate(candidate, original, layout, scale=1.0):
        calls.append((candidate.shape, original.shape, layout is not None, scale))
        passed, leaked, failures = queue.pop(0)
        scores = {"ncc": 0.71, "edge_recall": 0.83, "leak": 0.5 if leaked else 0.0, "leak_frame": 0.0, "regions": []}
        return GateResult(passed, scores, list(failures), leaked)

    monkeypatch.setattr(rb, "gate", fake_gate)
    return calls


def _one(tmp_path, floors={0}):
    return rb.discover(make_in_dir(tmp_path), floors)[:1]


def _regen(cams, out, **kw):
    opts = dict(text_model="t", style="s.", force=False, dry_run=False, log=lambda *_: None)
    opts.update(kw)
    return rb.regenerate(cams, out, **opts)


def test_accept_on_second_attempt_writes_png_and_report(tmp_path, monkeypatch):
    png = png_bytes(np.full((1024, 1536, 3), 7, np.uint8))
    fake = FakeSubprocess(png, judge=[_verdict(extra_objects=["table"], corrections=["remove the table"]), GOOD_VERDICT])
    monkeypatch.setattr(subprocess, "run", fake.run)
    gates = _gate_script(monkeypatch, [(True, False, []), (True, False, [])])
    logs = []
    out = tmp_path / "out"
    assert _regen(_one(tmp_path), out, log=logs.append) == (1, 0)
    assert load_png_rgb(out / "backgrounds/floor00/camera000.png").shape == (800, 1280, 3)
    assert logs[-1] == "floor00/camera000: ok (attempt 2/3, ncc 0.71, recall 0.83)"
    gen = [c[2] for c in fake.calls if "--json-schema" not in c]
    assert len(gen) == 2 and "Attempt 1 was rejected: remove the table; extra object: table." in gen[1]
    assert "Attempt" not in gen[0]
    assert gates[0] == ((800, 1280, 3), (200, 320, 3), False, 1.0)
    report = rb.load_json(out / rb.REPORT_FILE)["floor00/camera000"]
    assert report["accepted"] is True and len(report["attempts"]) == 2
    assert report["attempts"][0]["attached"] == ["ref", "guide"]
    assert report["attempts"][0]["gate"]["passed"] is True and report["attempts"][0]["judge"]["extra_objects"] == ["table"]
    assert report["attempts"][1]["judge"] == GOOD_VERDICT


def test_gate_failure_skips_the_judge_and_drops_the_guide_after_a_leak(tmp_path, monkeypatch):
    png = png_bytes(np.zeros((1024, 1536, 3), np.uint8))
    fake = FakeSubprocess(png, judge=[GOOD_VERDICT])
    monkeypatch.setattr(subprocess, "run", fake.run)
    _gate_script(monkeypatch, [(False, True, ["guide colour on 40 % of guide-line pixels: do not draw the red, blue or green lines"]),
                               (True, False, [])])
    out = tmp_path / "out"
    assert _regen(_one(tmp_path), out) == (1, 0)
    judge_calls = [c for c in fake.calls if "For every inventory object" in c[2]]
    assert len(judge_calls) == 1
    gen = [c[2] for c in fake.calls if "--json-schema" not in c]
    guide = str((tmp_path / "in/guides/floor00/camera000.png").absolute())
    assert guide in gen[0] and guide not in gen[1]
    assert "Attempt 1 was rejected: guide colour on 40 %" in gen[1]
    report = rb.load_json(out / rb.REPORT_FILE)["floor00/camera000"]
    assert report["attempts"][0]["judge"] is None and report["attempts"][1]["attached"] == ["ref"]


def test_reject_after_all_attempts_writes_nothing(tmp_path, monkeypatch):
    png = png_bytes(np.zeros((1024, 1536, 3), np.uint8))
    fake = FakeSubprocess(png, judge=[_verdict(camera_same=False)] * 2)
    monkeypatch.setattr(subprocess, "run", fake.run)
    _gate_script(monkeypatch, [(True, False, []), (True, False, [])])
    logs = []
    out = tmp_path / "out"
    assert _regen(_one(tmp_path), out, attempts=2, log=logs.append) == (0, 1)
    assert not (out / "backgrounds").exists()
    assert logs[-1] == ("floor00/camera000: failed: layout mismatch after 2 attempts "
                        "(last: camera position, framing or perspective differs)")
    report = rb.load_json(out / rb.REPORT_FILE)["floor00/camera000"]
    assert report["accepted"] is False and len(report["attempts"]) == 2


def test_error_mid_attempt_ends_the_camera_without_retry(tmp_path, monkeypatch):
    fake = FakeSubprocess(png_bytes(np.zeros((1024, 1536, 3), np.uint8)), fail_image_calls={1})
    monkeypatch.setattr(subprocess, "run", fake.run)
    _gate_script(monkeypatch, [])
    logs = []
    out = tmp_path / "out"
    assert _regen(_one(tmp_path), out, log=logs.append) == (0, 1)
    assert fake.image_calls == 1 and logs[-1].startswith("floor00/camera000: failed: ")
    report = rb.load_json(out / rb.REPORT_FILE)["floor00/camera000"]
    assert report["accepted"] is False and "error" in report["attempts"][-1]


def test_five_consecutive_rejections_abort_with_a_hint(tmp_path, monkeypatch):
    in_dir = tmp_path / "in"
    for i in range(6):
        xb.save_png(in_dir / "backgrounds" / f"floor00/camera{i:03d}.png", checker_pixels(i))
    cams = rb.discover(in_dir, None)
    fake = FakeSubprocess(png_bytes(np.zeros((1024, 1536, 3), np.uint8)), judge=[_verdict(camera_same=False)] * 6)
    monkeypatch.setattr(subprocess, "run", fake.run)
    _gate_script(monkeypatch, [(True, False, [])] * 6)
    logs = []
    assert _regen(cams, tmp_path / "out", attempts=1, log=logs.append) == (0, 5)
    assert logs[-1] == rb.REJECT_ABORT
    assert fake.image_calls == 5


def test_rejections_and_errors_keep_separate_streaks(tmp_path, monkeypatch):
    in_dir = tmp_path / "in"
    for i in range(4):
        xb.save_png(in_dir / "backgrounds" / f"floor00/camera{i:03d}.png", checker_pixels(i))
    cams = rb.discover(in_dir, None)
    # cameras 0,1: error; camera 2: rejected (resets the error streak); camera 3: error -> no abort
    fake = FakeSubprocess(png_bytes(np.zeros((1024, 1536, 3), np.uint8)), fail_image_calls={1, 2, 4},
                          judge=[_verdict(camera_same=False)])
    monkeypatch.setattr(subprocess, "run", fake.run)
    _gate_script(monkeypatch, [(True, False, [])])
    logs = []
    assert _regen(cams, tmp_path / "out", attempts=1, log=logs.append) == (0, 4)
    assert not any(line.startswith("aborting") for line in logs)


def test_report_entry_is_replaced_on_rerun_and_dry_run_names_layout(tmp_path, monkeypatch):
    png = png_bytes(np.zeros((1024, 1536, 3), np.uint8))
    fake = FakeSubprocess(png, judge=[_verdict(camera_same=False), GOOD_VERDICT])
    monkeypatch.setattr(subprocess, "run", fake.run)
    _gate_script(monkeypatch, [(True, False, []), (True, False, [])])
    out = tmp_path / "out"
    cams = _one(tmp_path)
    assert _regen(cams, out, attempts=1) == (0, 1)
    assert _regen(cams, out, attempts=1) == (1, 0)
    report = rb.load_json(out / rb.REPORT_FILE)["floor00/camera000"]
    assert report["accepted"] is True and len(report["attempts"]) == 1
    logs = []
    assert _regen(cams, out, dry_run=True, force=True, log=logs.append) == (0, 0)
    assert logs == ["floor00/camera000: would regenerate (guide yes, layout no, prompt cached yes)"]


def test_missing_sidecar_logs_framing_gate_only_once(tmp_path, monkeypatch):
    fake = FakeSubprocess(png_bytes(np.zeros((1024, 1536, 3), np.uint8)), judge=[GOOD_VERDICT])
    monkeypatch.setattr(subprocess, "run", fake.run)
    _gate_script(monkeypatch, [(True, False, [])])
    logs = []
    assert _regen(_one(tmp_path), tmp_path / "out", log=logs.append) == (1, 0)
    assert logs.count("floor00/camera000: no layout: framing gate only") == 1


def test_screens_go_through_the_loop_with_screen_naming(tmp_path, monkeypatch):
    in_dir = tmp_path / "in"
    xb.save_png(in_dir / "screens" / "ress10.png", checker_pixels(1))
    (in_dir / "guides" / "screens").mkdir(parents=True)
    (in_dir / "guides" / "screens" / "ress10.json").write_text(json.dumps({"schema": 1, "size": [320, 200], "blit": [[10, 10, 140, 181]]}))
    cams = rb.discover(in_dir, None)
    fake = FakeSubprocess(png_bytes(np.full((1024, 1536, 3), 9, np.uint8)), judge=[GOOD_VERDICT])
    monkeypatch.setattr(subprocess, "run", fake.run)
    gates = _gate_script(monkeypatch, [(True, False, [])])
    out = tmp_path / "out"
    assert _regen(cams, out) == (1, 0)
    assert (out / "screens" / "ress10.png").is_file()
    gen = [c[2] for c in fake.calls if "--json-schema" not in c][0]
    assert 'ImageName = "screen_ress10"' in gen and "painted illustration" in gen
    assert "Regions that must stay plain: x 3–47 y 5–96." in gen
    assert gates[0][2] is True


def test_cli_knobs(tmp_path, monkeypatch):
    args = rb._parse_args([str(tmp_path), "--out", str(tmp_path / "o"), "--attempts", "2", "--gate-scale", "0.5"])
    assert args.attempts == 2 and args.gate_scale == 0.5
    assert rb._parse_args([str(tmp_path), "--out", "o"]).attempts == 3
    with pytest.raises(SystemExit):
        rb._parse_args([str(tmp_path), "--out", "o", "--image-model", "x"])
    with pytest.raises(SystemExit):
        rb._parse_args([str(tmp_path), "--out", "o", "--attempts", "0"])
```

Also update the older regenerate-level tests to the loop: every `FakeSubprocess(...)` used by a test that expects an accepted plate gets `judge=[GOOD_VERDICT] * <accepted cameras>`, and each such test calls `_gate_script(monkeypatch, [(True, False, [])] * <cameras>)` before running (the fake image is a flat colour and would not pass the real gate). Affected: `test_regenerate_writes_fitted_pngs_and_prompt_cache` (its `len(fake.calls)` becomes 9: describe, generate, judge per camera), `test_regenerate_resumes_and_force_redoes` (call counts 9 / 2 / 9 — the edited-prompt run makes one generate and one judge call, so `len(fake.calls) == 2 and "EDITED" in fake.calls[0][2]`; it needs one judge verdict + one gate result), `test_regenerate_continues_after_a_failed_camera`, `test_regenerate_redescribes_when_source_hash_changes` (`len(fake.calls) == 3`), `test_regenerate_round_trips_through_check_overrides`, `test_copy_manifest_never_overwrites_existing_out_manifest`, `test_main_runs_with_injected_subprocess_and_reports_failures` (three accepted plates across its two `main` runs: three verdicts, three gate entries), `test_regenerate_screens_land_under_screens_and_copy_manifest`, `test_regenerate_attaches_reference_and_guide_and_cleans_up`, `test_regenerate_redescribes_a_schema_1_prompt_entry`. Tests that expect failures before any gate (`test_regenerate_counts_empty_description_as_failed`, `test_regenerate_counts_non_png_image_as_failed`, `test_regenerate_aborts_after_consecutive_failures`) need no gate script.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_regenerate_backgrounds.py -q`
Expected: the new tests FAIL (`TypeError: regenerate() got an unexpected keyword argument 'attempts'`, `AttributeError: REPORT_FILE`).

- [ ] **Step 3: Implement the loop**

In `tools/regenerate_backgrounds.py` add near the top constants:

```python
REPORT_FILE = "report.json"
MAX_CONSECUTIVE_REJECTS = 5    # a model that cannot keep the layout: stop burning attempts
REJECT_ABORT = ("aborting after 5 consecutive layout mismatches: edit the inventory in prompts.json, "
                "lower --gate-scale, or raise --attempts")
```

Add `from tools.plate_check import fmt_bbox, gate, layout_regions` (extend the existing import) and `from PyAitD.render.asset_resolver import load_png_rgb` at module level is **not** allowed (pygame at import time is fine for a tool, but keep the pattern: import it inside the functions that need it). Add:

```python
@dataclasses.dataclass
class CameraOutcome:
    status: str        # ok | rejected | error
    attempts: list     # report entries, one per attempt (or {"error": msg})
    message: str


def _process_camera(cam, target, prompts, prompts_path, *, text_model, style, attempts, gate_scale,
                    force, log):
    """Describe (cached), then up to `attempts` generate -> gate -> judge
    rounds; writes `target` on acceptance. Never raises: errors become an
    "error" outcome with the message."""
    from PyAitD.render.asset_resolver import load_png_rgb
    record = []
    try:
        source_sha = hashlib.sha256(cam.source.read_bytes()).hexdigest()
        entry = prompts.get(cam.key)
        stale = entry is None or "inventory" not in entry or entry.get("sha256") != source_sha
        if stale or force:
            inventory = describe(text_model, cam)
            prompts[cam.key] = {"inventory": inventory, "model": text_model, "sha256": source_sha}
            save_prompts(prompts_path, prompts)
        inventory = prompts[cam.key]["inventory"]
        original = load_png_rgb(cam.source)
        layout = json.loads(cam.layout.read_text()) if cam.layout else None
        if layout is None:
            log(f"{cam.key}: no layout: framing gate only")
        regions = layout_regions(layout)
        screen = cam.floor == -1
        ref = make_reference(cam)
        try:
            leaked, corrections = False, []
            for n in range(1, attempts + 1):
                attached = attachments(cam, ref, leaked)
                prompt = generation_prompt(inventory, style, regions, corrections, rejected_attempt=n - 1,
                                           guide_attached=len(attached) > 1, screen=screen)
                attempt = {"attached": ["ref"] + (["guide"] if len(attached) > 1 else []),
                           "gate": None, "judge": None}
                record.append(attempt)
                out = temp_png()
                try:
                    png = generate(text_model, cam, prompt, attached, out)
                finally:
                    out.unlink(missing_ok=True)
                fitted = fit_to_target(png)
                result = gate(fitted, original, layout, gate_scale)
                attempt["gate"] = {"passed": result.passed, "scores": result.scores, "failures": result.failures}
                if not result.passed:
                    leaked = leaked or result.leaked
                    corrections = list(result.failures)
                    continue
                cand = temp_png()
                try:
                    save_png(cand, fitted)
                    verdict = judge(text_model, cam, inventory, ref, cand)
                finally:
                    cand.unlink(missing_ok=True)
                attempt["judge"] = verdict
                if judge_accepts(verdict, inventory):
                    save_png(target, fitted)
                    return CameraOutcome("ok", record, f"attempt {n}/{attempts}, ncc {result.scores['ncc']:.2f}, "
                                                       f"recall {result.scores['edge_recall']:.2f}")
                corrections = judge_corrections(verdict, inventory)
            return CameraOutcome("rejected", record,
                                 f"layout mismatch after {attempts} attempts (last: {'; '.join(corrections)})")
        finally:
            ref.unlink(missing_ok=True)
    except Exception as exc:   # per-camera: agy errors, bad JSON, undecodable image
        record.append({"error": str(exc)})
        return CameraOutcome("error", record, str(exc))
```

Replace `regenerate`:

```python
def regenerate(cams, out_dir, *, text_model, style, attempts=3, gate_scale=1.0, force, dry_run, log=print):
    """Describe + generate + verify every camera into out_dir. Returns
    (done, failed); failed counts rejected and errored cameras. Existing
    outputs are skipped unless force; cached inventories are reused unless
    force or stale; prompts.json and report.json are saved after every
    camera. Errors abort after MAX_CONSECUTIVE_FAILURES in a row,
    rejections after MAX_CONSECUTIVE_REJECTS in a row."""
    out_dir = pathlib.Path(out_dir)
    prompts_path, report_path = out_dir / PROMPTS_FILE, out_dir / REPORT_FILE
    prompts, report = load_prompts(prompts_path), load_json(report_path)
    done = failed = errors = rejects = 0
    for cam in cams:
        target = out_dir / (f"backgrounds/{cam.key}.png" if cam.floor >= 0 else f"{cam.key}.png")
        if target.is_file() and not force:
            log(f"{cam.key}: exists, skipped")
            continue
        guide = "yes" if cam.guide is not None else "no"
        layout = "yes" if cam.layout is not None else "no"
        cached = "yes" if cam.key in prompts and "inventory" in prompts[cam.key] else "no"
        if dry_run:
            log(f"{cam.key}: would regenerate (guide {guide}, layout {layout}, prompt cached {cached})")
            continue
        outcome = _process_camera(cam, target, prompts, prompts_path, text_model=text_model, style=style,
                                  attempts=attempts, gate_scale=gate_scale, force=force, log=log)
        report[cam.key] = {"accepted": outcome.status == "ok", "attempts": outcome.attempts}
        save_json(report_path, report)
        if outcome.status == "ok":
            done += 1
            errors = rejects = 0
            log(f"{cam.key}: ok ({outcome.message})")
            continue
        failed += 1
        log(f"{cam.key}: failed: {outcome.message}")
        if outcome.status == "rejected":
            rejects, errors = rejects + 1, 0
            if rejects >= MAX_CONSECUTIVE_REJECTS:
                log(REJECT_ABORT)
                break
        else:
            errors, rejects = errors + 1, 0
            if errors >= MAX_CONSECUTIVE_FAILURES:
                log(f"aborting after {errors} consecutive failures")
                break
    if not dry_run:
        _copy_manifest(cams, out_dir)
    return done, failed
```

`_parse_args`:

```python
def _positive_int(text):
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


def _non_negative_float(text):
    value = float(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return value
```

and the options `p.add_argument("--attempts", type=_positive_int, default=3, help="generate/verify rounds per camera before rejecting it (default 3)")`, `p.add_argument("--gate-scale", type=_non_negative_float, default=1.0, help="multiply every gate threshold (1.0 default, 0 disables the gate)")`. `main` passes `attempts=args.attempts, gate_scale=args.gate_scale`. Update the module docstring: describe → inventory, generate contract, gate + judge, `report.json`.

Makefile lines 121–122:

```make
regenerate-backgrounds: install ## Regenerate data/aitd1/overrides backgrounds with Gemini into data/aitd1/overrides-ai (in=, out_ai=, floors=0-7, style=, force=1, dry=1, text_model=, attempts=3, gate_scale=1.0, screens=0 to skip screens); rejects plates whose layout drifts; needs the `agy` CLI on PATH
	$(PYTHON) tools/regenerate_backgrounds.py "$(or $(in),data/aitd1/overrides)" --out "$(or $(out_ai),data/aitd1/overrides-ai)" --floors "$(or $(floors),0-7)" $(if $(style),--style "$(style)") $(if $(force),--force) $(if $(dry),--dry-run) $(if $(text_model),--text-model "$(text_model)") $(if $(attempts),--attempts "$(attempts)") $(if $(gate_scale),--gate-scale "$(gate_scale)") $(if $(filter 0,$(screens)),--no-screens)
```

- [ ] **Step 4: Run the tool tests, then the whole suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_regenerate_backgrounds.py -q`
Expected: PASS.

Run: `make test`
Expected: everything green; `make regenerate-backgrounds dry=1` lists cameras with `layout no` (the export dir predates the sidecars) and makes no calls.

- [ ] **Step 5: Commit**

```bash
git add tools/regenerate_backgrounds.py tests/test_regenerate_backgrounds.py Makefile
git commit -m "feat: regenerate verifies every attempt with the gate and the judge, retries with corrections, rejects drift"
```

---

### Task 9: Documentation and the live test

**Files:**
- Modify: `docs/ai-background-regeneration.md` (§1 listing, §2b, Screens paragraph), `README.md:85-91`, `AGENTS.md:24` and `:158-163`, `CONTEXT.md:11-13`, `:34`, `:294-300`
- Test: `tests/test_regenerate_backgrounds.py` (live test)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Add the live test**

Append to `tests/test_regenerate_backgrounds.py`:

```python
import shutil


@pytest.mark.journey
@pytest.mark.skipif(os.environ.get("PYAITD_LIVE_AI") != "1" or shutil.which("agy") is None,
                    reason="set PYAITD_LIVE_AI=1 with the agy CLI on PATH to call Gemini")
def test_live_one_camera_through_the_loop(tmp_path):
    from tests.stub_floor import StubFloor
    in_dir = tmp_path / "in"
    xb.export_floor(StubFloor(), in_dir, 4)
    cams = rb.discover(in_dir, None)
    logs = []
    done, failed = rb.regenerate(cams, tmp_path / "out", text_model=rb.DEFAULT_TEXT_MODEL, style=rb.DEFAULT_STYLE,
                                 attempts=2, force=False, dry_run=False, log=logs.append)
    report = rb.load_json(tmp_path / "out" / rb.REPORT_FILE)["floor00/camera000"]
    assert report["attempts"] and (done, failed) in ((1, 0), (0, 1))
    if done:
        assert load_png_rgb(tmp_path / "out/backgrounds/floor00/camera000.png").shape == (800, 1280, 3)
```

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_regenerate_backgrounds.py -q`
Expected: the live test is reported as skipped; the rest PASS.

- [ ] **Step 2: Rewrite `docs/ai-background-regeneration.md`**

§1 "Produces" listing gains two lines after the guide lines:

```
    ~/aitd-overrides/guides/floorNN/cameraNNN.json       the same structures as JSON (320x200 px)
    ~/aitd-overrides/guides/screens/ressNN.json          the blit rects as JSON
```

Replace §2b with:

```markdown
## 2b. Regenerate with Gemini (optional, in-repo)

    command -v agy                                # once: the agy CLI must be on PATH
    make regenerate-backgrounds dry=1             # list what would run, no calls
    make regenerate-backgrounds                   # data/aitd1/overrides -> data/aitd1/overrides-ai
    make regenerate-backgrounds floors=0 style="Sunlit, warm, clean." force=1 attempts=5

Every plate must keep the original scene: same camera framing, every
wall, door, window, stair and piece of furniture at the same place, same
kind, same count. Materials, lighting and style may change. A plate that
drifts is not written; the game shows the original for that camera.

For each `backgrounds/floorNN/cameraNNN.png` (with its guide and layout
sidecar when present) the tool:

1. asks the text model (`gemini-3.1-pro` via `agy`) for an **inventory** —
   a scene prompt plus every object with kind, count and bounding box in
   percent of frame — and caches it in `data/aitd1/overrides-ai/prompts.json`;
2. dictates one `generate_image` call: the original (upscaled 4x) and the
   guide as reference images, aspect 3:2, and a prompt that opens with the
   game's atmosphere notes, asks for a re-render of exactly this scene,
   lists the layout in percent of frame, and repeats the corrections from
   the previous rejected attempt;
3. fits the result to 1280x800 and runs the **gate**
   (`tools/plate_check.py`, offline): blurred-luminance correlation
   (`ncc` >= 0.50), the share of the original's edges found within 2 px in
   the plate (`edge_recall` >= 0.60, and >= 0.50 inside every mask and
   collision region), and guide-colour leaks along the guide's lines
   (<= 2 % of line pixels, <= 0.5 % of the frame). A gate failure skips
   the judge; a leak drops the guide from the next attempt's references;
4. asks the text model to **judge** the plate against the original and
   the inventory: camera the same, no guide lines, every object present
   with the same kind, count and position, nothing extra;
5. retries up to `attempts=` (3) times with the gate's and judge's
   corrections, then rejects the camera.

Every prompt opens with a fixed game-context block naming Alone in the
Dark 1 and its gothic horror / Lovecraftian mood; `style=` is appended
verbatim at the end.

- `report.json` in the output directory records every attempt's gate
  scores and judge verdict per camera.
- Cameras that already exist in the output are skipped; rerun after an
  interruption or a rejection and it retries only the missing ones.
  `force=1` redoes existing plates and their inventories.
- Edit a camera's `objects` or `prompt` in `prompts.json` (keep the
  `sha256`), delete its PNG and rerun to steer it with your wording.
- A camera that fails with an error (quota, no image returned) is logged
  and skipped; three consecutive errors abort the run. A camera rejected
  on every attempt is logged as `failed: layout mismatch`; five
  consecutive rejections abort with a hint (`edit the inventory in
  prompts.json, lower --gate-scale, or raise --attempts`). Exit status 1
  means at least one camera failed either way.
- `gate_scale=` multiplies every gate threshold (`0` disables the gate
  for experiments); `text_model=` overrides the model for the description
  and the judge (the image model is whatever `generate_image` uses; there
  is no choice); `in=` and `out_ai=` the directories.
- Export directories made before the layout sidecars existed still work:
  such cameras get the framing scores and the judge only, and the log says
  `no layout: framing gate only`. Re-export (`make export-backgrounds
  force=1`) to add the sidecars.

Then `make check-overrides overrides=data/aitd1/overrides-ai proof=1` and
`make run overrides=data/aitd1/overrides-ai`.
```

In the Screens section, after "`proof=1` writes `screen-ressNN.png` side-by-sides.", add: "Regenerated screens go through the same gate and judge; the gate additionally requires the blit regions to stay plain (edge density <= 2 %)."

- [ ] **Step 3: One-liners in README, AGENTS, CONTEXT**

`README.md` lines 85–91: replace the parenthetical "(optional; needs the `agy` CLI on `PATH`, which it invokes once per camera for the description and once for the image)" with "(optional; needs the `agy` CLI on `PATH`; per camera it asks for a structured inventory, dictates the image call, and verifies every attempt with an offline gate plus a vision judge, rejecting plates that move or change objects)".

`AGENTS.md` line 24: `make regenerate-backgrounds # Gemini describe+render+verify data/aitd1/overrides -> data/aitd1/overrides-ai (dry=1, floors=, style=, force=1, attempts=3, gate_scale=1.0); rejects drifted plates; needs the \`agy\` CLI on PATH`. In the bullet at lines 158–163 append: "`tools/plate_check.py` is the offline gate (numpy only, no I/O); it never calls anything."

`CONTEXT.md` line 34: same wording as the AGENTS line. Lines 294–300: after "fits the result to 1280x800," insert "gates it offline (`tools/plate_check.py`: correlation, per-region edge recall, guide-colour leak), has the text model judge it against the inventory, retries with corrections, rejects drift,". Lines 11–13 unchanged.

- [ ] **Step 4: Run the full suite and the dry run**

Run: `make test`
Expected: green (live test skipped).

Run: `make regenerate-backgrounds dry=1 floors=0 | head -5`
Expected: `floor00/cameraNNN: would regenerate (guide yes, layout no, prompt cached ...)` lines and no `agy` call.

- [ ] **Step 5: Commit**

```bash
git add docs/ai-background-regeneration.md README.md AGENTS.md CONTEXT.md tests/test_regenerate_backgrounds.py
git commit -m "docs: layout-fidelity regeneration — inventory, gate, judge, report; live loop test"
```

---

## Self-review

**Spec coverage.** Layout sidecar → Tasks 1–2. `layout_regions` / gate scores / thresholds / calibration → Tasks 3–4. `GAME_CONTEXT`, `INVENTORY_SCHEMA`, describe, `prompts.json` schema 2 with re-describe, `generation_prompt` order → Task 5. Generate contract, `ref.png`, attachment rule, `image_name` → Task 6. `JUDGE_SCHEMA`, `judge`, acceptance, corrections → Task 7. Attempt loop, two failure classes and abort limits, `report.json`, dry-run line, CLI knobs, `--image-model` removal, Makefile → Task 8. Docs, live test → Task 9. Error-handling table: every row is exercised by a Task 5–8 test except "interrupted run", which is the pre-existing atomic-write behaviour (`save_json`, `save_png`).

**Placeholders.** None; every code step carries its code.

**Type consistency.** `gate(candidate, original, layout, scale=1.0)` (Task 3) is what Task 8's `_process_camera` and `_gate_script` call. `GateResult` fields `(passed, scores, failures, leaked)` match the fake in Task 8. `generation_prompt(inventory, style, regions=(), corrections=(), rejected_attempt=0, guide_attached=False, screen=False)` is called with those keywords in Tasks 5, 6 and 8. `generate(model, cam, prompt, attached, out_path)` (Task 6) matches Task 8. `judge(model, cam, inventory, ref_path, candidate_path)`, `judge_accepts(verdict, inventory)`, `judge_corrections(verdict, inventory)` (Task 7) match Task 8. `Camera(..., layout=None)` trailing default keeps the positional constructions in older tests valid. `load_json` / `save_json` (Task 5) are used by Task 8 for the report.
