# Actor Surface Textures (Roadmap 2, Sub-project J) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give actor bodies real painted surfaces — a tools-side UV bake that produces a per-corner UV sidecar and a painter's guide, and a runtime that takes albedo from `DIR/bodies/body<NNN>.png` when one exists and falls back silently when it does not.

**Architecture:** Bake with libraries, render with the existing pipeline. `tools/export_actor_uvs.py` unwraps each body's rest pose with xatlas, sharing `geometry._triangulate`'s triangulation exactly, and writes `(M,3,2)` per-corner UVs plus a triangulation hash to `DIR/bodies/body<NNN>.uv.json` — so the runtime never sees xatlas's vertex remap. At runtime `AssetResolver.body_texture` follows the same missing-silent / corrupt-warn rule the background override already uses, `BodyGeometry.uv` carries the corners, and `_ACTOR_FSH` substitutes the sampled albedo for `v_color` while the palette-index material table still drives every physical term.

**Tech Stack:** Python 3.12, numpy. Tools-only: `xatlas` (MIT) and `libigl` (MPL-2.0, for `igl.embree.ambient_occlusion`). No new runtime dependency — the runtime stays pygame-ce + moderngl + numpy.

**Spec:** `docs/superpowers/specs/2026-08-31-actor-realism-roadmap-2-design.md` (sub-project J, plus its "Dependency policy amendment" and "Task ordering" sections). Read the spec's J section before starting.

## Global Constraints

- **Runtime dependencies stay exactly pygame-ce + moderngl + numpy.** `xatlas` and `libigl` are tools-only, live in a `tools` extra, and `tests/test_layering.py` must fail if anything under `PyAitD/` imports them.
- **Licenses.** `xatlas` MIT, `libigl` MPL-2.0, `igl.embree` bundles Embree (Apache-2.0) — all GPL-2.0-compatible. **Never import `igl.copyleft.cgal` (GPL-3) or `igl.copyleft.tetgen` (AGPL-3).** A test pins that ban.
- **Absent textures change nothing.** A body with no `.png` renders exactly as it does today, byte for byte. `realism=classic` ignores body textures entirely.
- **The fallback rule is the background rule:** missing falls back silently (no log, no `failures` entry), corrupt logs a warning once and falls back. `AssetResolver._override` already implements it — go through it, do not reimplement.
- **Paint changes colour, not physics.** The texture replaces the albedo term only; specular, rim, bump, sss and emissive stay driven by the palette-index material table. Lines, points and spheres stay untextured.
- `tests/golden/scene_lit_classic.npy` must keep passing and **must never be regenerated**.
- `skel.skin()`, `draw_list`, picking, masks, the mouse contract and all simulation code stay untouched.
- Every source file starts with `# SPDX-License-Identifier: GPL-2.0-only`.
- Every test file carries exactly one subject marker (`tools` for `tests/test_export_actor_uvs.py`); `--strict-markers` is on. Edits to existing test files keep their marker.
- This repo never ships game data or generated textures: `data/aitd1/textures` is git-ignored and stays that way.
- Run the full gate before calling any task done: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q` (the repo's authoritative gate is `make test`).
- Commit after every task with a `feat:`/`test:`/`docs:` message as shown.

## Verified facts this plan is built on

These were checked against the real libraries and the real game data on the target machine (macOS arm64, CPython 3.12, Apple M3 Max). Do not re-derive them; do check them if something surprises you.

| Fact | Evidence |
|---|---|
| `xatlas`, `libigl` install as arm64 cp312 wheels | `pip install --only-binary=:all: xatlas libigl` → xatlas 0.0.11, libigl 2.6.2 |
| `xatlas.parametrize(v, f)` returns `(vmapping, indices, uvs)` | verified |
| **xatlas preserves face count and per-corner order**: `vmapping[indices] == faces` exactly | verified on real bodies 1, 12, 30 (131 / 214 / 268 triangles) |
| It splits vertices at chart seams (body 1: 67 → 198), which is *why* UVs must be per-corner | verified |
| `uv[indices]` is therefore the `(M,3,2)` per-corner payload, already in `[0, 1]` | verified, all three bodies |
| `xatlas.Atlas(...).generate(pack_options=PackOptions(resolution=512, padding=4))` yields `at.width`/`at.height` that **may exceed the requested resolution** (512 → 605 for body 12) | verified — read the size back, never assume it |
| `igl.embree` is **not** auto-imported: `hasattr(igl, "embree")` is `False` until `import igl.embree` | verified |
| `igl.embree.ambient_occlusion(V, F, P, N, num_samples)` takes float64 and returns `(P,)` occlusion | verified signature |
| `GL_MAX_VERTEX_ATTRIBS` is **16**, and the tessellated instance layout already uses **13** | verified on the target GPU |
| The non-tessellated path already expands to unindexed corners in `_triangle_data`, so per-corner UVs drop straight in | `PyAitD/render/render_gl.py:1221-1234` |
| The repo already writes PNGs atomically via pygame (`tools/export_textures.py:66 save_png`) | read |
| Bodies are archive-scoped, not floor-scoped: `Assets(data, profile, hero=h).num_bodies` is **272**, and real archives carry entries that are not bodies (probe and skip) | verified; `tools/bootstrap_materials.py:load_game` already uses this loop |
| `ctx.max_anisotropy` is 16.0, and `texture.build_mipmaps()` + `texture.anisotropy = 8.0` both work | verified on the target GPU |
| `Floor(data_dir, 0, profile).palette` is `(256, 3)` — the guide's colour source | verified |
| `tools/export_textures.py` exposes `parse_floors`, `load_floor`, `load_assets`, `_merge_manifest_records`, `save_png` | verified |

**Deviation from the spec, deliberate:** the spec's tools extra lists `Pillow`. This plan does not need it — `save_png` already encodes PNGs with an atomic-rename idiom, and adding a second image library to write one guide would be redundant. The extra is `xatlas` and `libigl` only. If a later sub-project needs Pillow it can add it then.

---

### Task 1: the `tools` extra and the runtime-import ban

**Files:**
- Modify: `pyproject.toml:13-14` (`[project.optional-dependencies]`)
- Modify: `tests/test_layering.py` (a new test)
- Modify: `AGENTS.md` (the dependency line)

**Interfaces:**
- Produces: a `tools` extra installable with `pip install -e ".[tools]"`; `TOOLS_ONLY_MODULES = ("xatlas", "igl")` in `tests/test_layering.py`, which Tasks 2-6 rely on to keep the runtime clean.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_layering.py` (its `pytestmark` is `meta`; keep it):

```python
# Tools-side only (spec: 2026-08-31-actor-realism-roadmap-2-design.md's
# dependency policy amendment). The runtime stays pygame-ce + moderngl +
# numpy; these live in the `tools` extra and may only be imported under
# tools/.
TOOLS_ONLY_MODULES = ("xatlas", "igl")


def test_runtime_never_imports_a_tools_only_dependency():
    repo = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for path in (repo / "PyAitD").rglob("*.py"):
        for name in _imported_names(path):
            root = name.split(".")[0]
            if root in TOOLS_ONLY_MODULES:
                offenders.append(f"{path.relative_to(repo)}: {name}")
    assert not offenders, (
        "PyAitD/ must not import a tools-extra dependency; the runtime is "
        f"frozen at pygame-ce + moderngl + numpy: {offenders}")


def test_no_module_imports_a_copyleft_igl_submodule():
    # igl.copyleft.cgal is GPL-3 and igl.copyleft.tetgen is AGPL-3; this
    # project is GPL-2.0-only, so neither may ever be imported. igl itself
    # (MPL-2.0) and igl.embree (Apache-2.0 Embree) are fine.
    repo = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for folder in ("PyAitD", "tools", "tests"):
        for path in (repo / folder).rglob("*.py"):
            for name in _imported_names(path):
                if name.startswith("igl.copyleft"):
                    offenders.append(f"{path.relative_to(repo)}: {name}")
    assert not offenders, (
        "igl.copyleft.* is GPL-3/AGPL-3 and incompatible with GPL-2.0-only: "
        f"{offenders}")
```

`_imported_names(path)` is the AST helper the file already uses for its other scans — reuse it under whatever name it actually carries in `tests/test_layering.py` rather than writing a second one. If the existing helper returns module names differently (e.g. already split to the root), adapt these two tests to it; the assertion content is the contract.

- [ ] **Step 2: Run the tests to verify they pass for the right reason**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_layering.py -q`
Expected: PASS — nothing imports them yet. These are *guards*, armed now so Task 2 cannot quietly violate them. To prove the guard actually bites, temporarily add `import xatlas` to `PyAitD/render/geometry.py`, re-run, watch `test_runtime_never_imports_a_tools_only_dependency` FAIL, then remove it. Record that in your report.

- [ ] **Step 3: Add the extra**

In `pyproject.toml`, replace the `[project.optional-dependencies]` block:

```toml
[project.optional-dependencies]
dev = ["pytest>=8"]
# Tools-side only, never imported from PyAitD/ (pinned by
# tests/test_layering.py::test_runtime_never_imports_a_tools_only_dependency).
# GPL-2.0-compatible, maintained, macOS arm64 / CPython 3.12 wheels:
# xatlas MIT, libigl MPL-2.0 (igl.embree bundles Apache-2.0 Embree).
tools = ["xatlas>=0.0.9", "libigl>=2.5"]
```

In `AGENTS.md`, replace the dependency bullet at the end of `## Conventions`:

```markdown
- Dependencies: the runtime (`PyAitD/`) is fixed at pygame-ce, ModernGL, NumPy
  (plus pytest for the suite) — add nothing. `tools/` may take PyPI
  dependencies vetted case-by-case (GPL-2.0-compatible, maintained, macOS
  arm64 / CPython 3.12 wheels) in the `tools` extra; today that is `xatlas`
  and `libigl`, and `tests/test_layering.py` fails if `PyAitD/` imports
  either. `igl.copyleft.cgal` (GPL-3) and `igl.copyleft.tetgen` (AGPL-3) are
  banned outright and pinned by the same file. The one external service,
  Gemini, is reached through the `agy` CLI, not a Python SDK, so it costs
  this project no dependency at all.
```

- [ ] **Step 4: Install the extra and confirm both guards still pass**

```bash
.venv/bin/pip install -e ".[dev,tools]"
.venv/bin/python -c "import xatlas, igl, igl.embree; print('tools extra OK')"
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_layering.py -q
```

Expected: the import line prints, and the layering tests pass.

- [ ] **Step 5: Full gate, then commit**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
git add pyproject.toml tests/test_layering.py AGENTS.md
git commit -m "feat: tools extra (xatlas, libigl) with the runtime-import ban"
```

---

### Task 2: `tools/export_actor_uvs.py` — the unwrap, the sidecar, the guide

**Files:**
- Create: `tools/export_actor_uvs.py`
- Create: `tests/test_export_actor_uvs.py` (marker: `tools`)
- Modify: `PyAitD/render/texture_export.py` (three path helpers + a hash)
- Modify: `tools/export_textures.py:231-241` (the stage flag), `Makefile:126-130`

**Interfaces:**
- Consumes: `geometry.pose_geometry(body, [(0, (0, 0, 0))] * len(body.groups))` — its `.vertices` is the assembled rest pose and `.tris` the triangulation the runtime uses.
- Produces:
  - `texture_export.body_uv_rel_path(num) -> "bodies/body<NNN>.uv.json"`
  - `texture_export.body_texture_rel_path(num) -> "bodies/body<NNN>.png"`
  - `texture_export.body_guide_rel_path(num) -> "bodies/body<NNN>-guide.png"`
  - `texture_export.sha256_tris(tris) -> str`
  - `export_actor_uvs.unwrap_body(body) -> UvBake` with fields `uvs (M,3,2) float32`, `width int`, `height int`, `tris_sha256 str`, `chart_count int`
  - `export_actor_uvs.sidecar_payload(bake) -> dict`
  - `export_actor_uvs.body_numbers(data_dir, profile, heroes=(0, 1)) -> list[int]`
  - `export_actor_uvs.export_bodies(data_dir, profile, out_dir, *, save=save_png) -> list[dict]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_export_actor_uvs.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""tools/export_actor_uvs.py: the actor UV bake.

Tools-side: xatlas and igl live in the `tools` extra, so every test here
skips cleanly when the extra is not installed."""
import json

import numpy as np
import pytest

pytestmark = pytest.mark.tools

xatlas = pytest.importorskip("xatlas")


def _stub_body():
    """Two triangles sharing an edge, one root group — enough for a real
    unwrap without game data."""
    from types import SimpleNamespace
    from PyAitD.engine.data.formats import Primitive
    group = SimpleNamespace(start=0, num_vertices=4, num_group=0, org_group=-1,
                            base_vertices=0)
    return SimpleNamespace(
        vertices=[(0, 0, 0), (100, 0, 0), (0, 100, 0), (100, 100, 0)],
        groups=[group], group_order=[0], flags=2,
        primitives=[Primitive(1, 0, 10, [0, 1, 3, 2])],
    )


def test_unwrap_produces_per_corner_uvs_aligned_with_the_triangulation():
    from PyAitD.render.geometry import pose_geometry
    from tools.export_actor_uvs import unwrap_body
    body = _stub_body()
    geo = pose_geometry(body, [(0, (0, 0, 0))] * len(body.groups))
    bake = unwrap_body(body)
    # one UV triple per source triangle, in the source triangle's order
    assert bake.uvs.shape == (len(geo.tris), 3, 2)
    assert bake.uvs.dtype == np.float32
    assert bake.uvs.min() >= 0.0 and bake.uvs.max() <= 1.0
    assert bake.width > 0 and bake.height > 0
    assert bake.chart_count >= 1


def test_unwrap_hash_tracks_the_triangulation_not_the_pose():
    from PyAitD.render.geometry import pose_geometry
    from PyAitD.render.texture_export import sha256_tris
    from tools.export_actor_uvs import unwrap_body
    body = _stub_body()
    geo = pose_geometry(body, [(0, (0, 0, 0))] * len(body.groups))
    assert unwrap_body(body).tris_sha256 == sha256_tris(geo.tris)


def test_sha256_tris_changes_when_the_triangulation_changes():
    from PyAitD.render.texture_export import sha256_tris
    a = np.array([[0, 1, 2], [1, 3, 2]], dtype=np.int32)
    b = np.array([[0, 1, 2], [1, 2, 3]], dtype=np.int32)
    assert sha256_tris(a) == sha256_tris(a.copy())
    assert sha256_tris(a) != sha256_tris(b)


def test_sidecar_payload_round_trips_through_json():
    from tools.export_actor_uvs import sidecar_payload, unwrap_body
    payload = sidecar_payload(unwrap_body(_stub_body()))
    reloaded = json.loads(json.dumps(payload))
    assert reloaded["schema"] == 1
    assert reloaded["size"] == [payload["size"][0], payload["size"][1]]
    assert len(reloaded["uvs"]) == len(payload["uvs"])
    assert len(reloaded["uvs"][0]) == 3 and len(reloaded["uvs"][0][0]) == 2
    assert isinstance(reloaded["tris_sha256"], str) and len(reloaded["tris_sha256"]) == 64


def test_body_paths_are_the_names_the_resolver_opens():
    from PyAitD.render.texture_export import (
        body_guide_rel_path, body_texture_rel_path, body_uv_rel_path,
    )
    assert body_uv_rel_path(7) == "bodies/body007.uv.json"
    assert body_texture_rel_path(7) == "bodies/body007.png"
    assert body_guide_rel_path(7) == "bodies/body007-guide.png"


@pytest.mark.parametrize("body_num", [1, 12, 30])
def test_unwrap_on_real_bodies_keeps_the_corner_order(data_dir, profile, body_num):
    """The whole per-corner design rests on xatlas preserving face order:
    vmapping[indices] == faces exactly. Pinned on real data."""
    from PyAitD.engine.data.assets import Assets
    from PyAitD.render.geometry import pose_geometry
    from tools.export_actor_uvs import unwrap_body
    body = Assets(data_dir, profile).body(body_num)
    geo = pose_geometry(body, [(0, (0, 0, 0))] * len(body.groups))
    bake = unwrap_body(body)
    assert bake.uvs.shape == (len(geo.tris), 3, 2)
    assert bake.uvs.min() >= 0.0 and bake.uvs.max() <= 1.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_export_actor_uvs.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.export_actor_uvs'` (and `ImportError` for the three path helpers).

- [ ] **Step 3: Add the path helpers and the hash**

In `PyAitD/render/texture_export.py`, beside the other `*_rel_path` helpers (near `screen_rel_path` at `:307`):

```python
def body_uv_rel_path(num):
    return f"bodies/body{num:03d}.uv.json"


def body_texture_rel_path(num):
    return f"bodies/body{num:03d}.png"


def body_guide_rel_path(num):
    return f"bodies/body{num:03d}-guide.png"


def sha256_tris(tris):
    """Content hash of a body's triangulation, so a UV sidecar baked against
    a different triangulation is detectable. Hashes the index array in a
    fixed dtype and byte order, plus its length, so the digest is stable
    across platforms and numpy versions."""
    import hashlib
    arr = np.ascontiguousarray(tris, dtype="<i4")
    h = hashlib.sha256()
    h.update(str(arr.shape).encode("ascii"))
    h.update(arr.tobytes())
    return h.hexdigest()
```

- [ ] **Step 4: Write the bake**

Create `tools/export_actor_uvs.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Unwrap actor bodies into a texture atlas for an external painter.

A stage of `make export-textures`, tools-side only: it imports xatlas and
libigl from the `tools` extra, which PyAitD/ may never import
(tests/test_layering.py pins that). It writes, per body:

- `bodies/body<NNN>.uv.json` -- the sidecar the runtime reads: atlas size
  and (M, 3, 2) per-corner UVs in the *runtime's own* triangulation order,
  plus a hash of that triangulation so a stale sidecar is detectable.
  xatlas splits vertices at chart seams (body 1: 67 -> 198), which is why
  the UVs are per corner and why the runtime never sees the vertex remap.
- `bodies/body<NNN>-guide.png` -- what a painter works from: charts filled
  with the body's own palette colours, an ambient-occlusion layer, and a
  wireframe overlay, at the atlas's own size.

The painter produces `bodies/body<NNN>.png` (albedo, same layout).
`make check-textures` validates the result."""
import argparse
import dataclasses
import json
import pathlib
import sys

import numpy as np

from PyAitD.engine.data.assets import Assets
from PyAitD.games import load_profile
from PyAitD.render.geometry import pose_geometry
from PyAitD.render.texture_export import (
    body_guide_rel_path, body_texture_rel_path, body_uv_rel_path, sha256_tris,
)

SIDECAR_SCHEMA = 1
# Requested atlas resolution. xatlas treats this as a hint and grows the
# atlas when the charts do not fit (512 produced 605 for body 12), so the
# real size is always read back from the atlas, never assumed.
ATLAS_RESOLUTION = 512
# Gutter in texels between charts, so a mip level cannot bleed one chart's
# paint into its neighbour.
ATLAS_PADDING = 4
AO_SAMPLES = 64


@dataclasses.dataclass(frozen=True)
class UvBake:
    uvs: np.ndarray      # (M, 3, 2) float32, per corner, runtime triangle order
    width: int
    height: int
    tris_sha256: str
    chart_count: int


def rest_geometry(body):
    """The assembled rest pose and its triangulation -- the exact arrays the
    runtime builds, so the UVs land in the runtime's own corner order."""
    return pose_geometry(body, [(0, (0, 0, 0))] * len(body.groups))


def unwrap_body(body):
    """xatlas unwrap of `body`'s rest pose, as per-corner UVs.

    xatlas returns (vmapping, indices, uvs) where the vertices have been
    split at chart seams; `vmapping[indices] == tris` exactly (verified on
    real bodies 1, 12 and 30), so `uvs[indices]` is the per-corner payload
    in the original triangle order."""
    import xatlas
    geo = rest_geometry(body)
    vertices = np.ascontiguousarray(geo.vertices, dtype=np.float32)
    tris = np.ascontiguousarray(geo.tris, dtype=np.uint32)
    atlas = xatlas.Atlas()
    atlas.add_mesh(vertices, tris)
    options = xatlas.PackOptions()
    options.resolution = ATLAS_RESOLUTION
    options.padding = ATLAS_PADDING
    atlas.generate(pack_options=options)
    vmapping, indices, uvs = atlas[0]
    if not np.array_equal(vmapping[indices], tris):
        # The per-corner sidecar is only meaningful if xatlas kept the
        # triangle order. It does; this guards against a future xatlas
        # changing that silently rather than letting it corrupt every paint.
        raise RuntimeError(
            "xatlas did not preserve triangle order; the per-corner UV "
            "sidecar cannot be built against this unwrap")
    corner_uvs = np.ascontiguousarray(uvs[indices], dtype=np.float32)
    return UvBake(
        uvs=corner_uvs,
        width=int(atlas.width),
        height=int(atlas.height),
        tris_sha256=sha256_tris(geo.tris),
        chart_count=int(atlas.chart_count),
    )


def sidecar_payload(bake):
    return {
        "schema": SIDECAR_SCHEMA,
        "size": [bake.width, bake.height],
        "chart_count": bake.chart_count,
        "tris_sha256": bake.tris_sha256,
        "uvs": bake.uvs.round(6).tolist(),
    }


HEROES = (0, 1)


def body_numbers(data_dir, profile, heroes=HEROES):
    """Every body number the hero archives actually expose, sorted.

    Bodies live in per-hero archives (`Assets(..., hero=h).num_bodies`),
    and real archives carry entries that are not bodies at all, so each is
    probed and the failures skipped -- the same loop
    `tools/bootstrap_materials.py:load_game` already uses.

    Note the same number can name a *different* body in each hero's
    archive, while the texture directory keys paints by number alone
    (`bodies/body<NNN>.png`). That ambiguity is inherited, not introduced:
    the existing per-body material override
    (`asset_resolver.texture_body_material_path`) keys the same way. The
    proof document records it as a known limitation."""
    seen = set()
    for hero in heroes:
        assets = Assets(data_dir, profile, hero=hero)
        for num in range(assets.num_bodies):
            try:
                assets.body(num)
            except (ValueError, KeyError, IndexError):
                continue   # an entry that is not a body
            seen.add(num)
    return sorted(seen)


def ambient_occlusion(body):
    """(N,) float32 per-vertex openness of the rest pose, 1 = open.

    `igl.embree` is a submodule that is not imported by `import igl`, so it
    is imported explicitly here."""
    import igl.embree
    geo = rest_geometry(body)
    v = np.ascontiguousarray(geo.vertices, dtype=np.float64)
    f = np.ascontiguousarray(geo.tris, dtype=np.int64)
    n = np.ascontiguousarray(geo.normals, dtype=np.float64)
    occlusion = igl.embree.ambient_occlusion(v, f, v, n, AO_SAMPLES)
    return (1.0 - np.asarray(occlusion, dtype=np.float32)).clip(0.0, 1.0)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_export_actor_uvs.py -q`
Expected: PASS (the real-body cases skip without game data; run with data present if available).

- [ ] **Step 6: Add the guide renderer and the writer**

Append to `tools/export_actor_uvs.py`:

```python
def _barycentric_fill(size, corner_uvs, corner_values, ao_values):
    """Rasterise each triangle's chart into an (H, W, 3) uint8 image.

    Flat-fills each triangle with its own palette colour scaled by the mean
    openness of its corners -- enough for a painter to read shape and
    cavity without pulling in a rasteriser dependency."""
    width, height = size
    img = np.zeros((height, width, 3), dtype=np.uint8)
    xs = np.clip((corner_uvs[:, :, 0] * (width - 1)).round().astype(np.int32), 0, width - 1)
    ys = np.clip(((1.0 - corner_uvs[:, :, 1]) * (height - 1)).round().astype(np.int32), 0, height - 1)
    for tri in range(len(corner_uvs)):
        x0, x1 = int(xs[tri].min()), int(xs[tri].max())
        y0, y1 = int(ys[tri].min()), int(ys[tri].max())
        shade = float(ao_values[tri])
        img[y0:y1 + 1, x0:x1 + 1] = np.clip(
            corner_values[tri].astype(np.float32) * shade, 0, 255).astype(np.uint8)
    return img


def guide_image(body, bake, palette, ao):
    """The painter's guide: every triangle's chart filled with that
    triangle's own palette colour, darkened by its corners' mean
    occlusion."""
    geo = rest_geometry(body)
    tri_rgb = np.asarray(palette, dtype=np.uint8)[np.asarray(geo.tri_colors, dtype=np.int32)]
    tri_ao = np.asarray(ao, dtype=np.float32)[np.asarray(geo.tris, dtype=np.int32)].mean(axis=1)
    return _barycentric_fill((bake.width, bake.height), bake.uvs, tri_rgb, tri_ao)


def export_bodies(data_dir, profile, out_dir, *, save=None):
    """Bake every body the hero archives expose. Returns one manifest record
    per body, in body-number order."""
    from PyAitD.engine.data.floor import Floor
    from tools.export_textures import save_png
    save = save_png if save is None else save
    # Hero 0's archive is the one the guide's palette colours come from; a
    # number present only in hero 1's archive falls back to that archive.
    by_hero = {h: Assets(data_dir, profile, hero=h) for h in HEROES}
    palette = Floor(data_dir, 0, profile).palette
    out_dir = pathlib.Path(out_dir)
    records = []
    for num in body_numbers(data_dir, profile):
        body = None
        for hero in HEROES:
            try:
                body = by_hero[hero].body(num)
                break
            except (ValueError, KeyError, IndexError):
                continue
        if body is None:
            continue
        bake = unwrap_body(body)
        uv_path = out_dir / body_uv_rel_path(num)
        uv_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = uv_path.with_suffix(uv_path.suffix + ".tmp")
        tmp.write_text(json.dumps(sidecar_payload(bake)), encoding="utf-8")
        tmp.replace(uv_path)
        ao = ambient_occlusion(body)
        save(out_dir / body_guide_rel_path(num), guide_image(body, bake, palette, ao))
        records.append({
            "body": num,
            "uv": body_uv_rel_path(num),
            "guide": body_guide_rel_path(num),
            "texture": body_texture_rel_path(num),
            "size": [bake.width, bake.height],
            "charts": bake.chart_count,
            "tris_sha256": bake.tris_sha256,
        })
    return records


def _parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("data", type=pathlib.Path, help="game data directory (e.g. .../INDARK)")
    p.add_argument("--out", type=pathlib.Path, required=True, help="texture directory to write into")
    p.add_argument("--game", default="aitd1", help="game id (default aitd1)")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    if not args.data.is_dir():
        print(f"error: game data directory not found: {args.data}", file=sys.stderr)
        return 2
    records = export_bodies(args.data, load_profile(args.game), args.out)
    for rec in records:
        print(f"{rec['uv']}  {rec['size'][0]}x{rec['size'][1]}  {rec['charts']} charts")
    print(f"{len(records)} bodies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`tools/export_textures.py` already exposes `parse_floors`, `load_floor`, `load_assets` and `_merge_manifest_records` (all verified present) — this bake needs none of them except `save_png`, because bodies are archive-scoped rather than floor-scoped.

- [ ] **Step 7: Wire the stage into `make export-textures`**

In `tools/export_textures.py`'s `_parse_args` (beside `--screens` at `:235`):

```python
    p.add_argument("--uvs", action=argparse.BooleanOptionalAction, default=True,
                   help="bake actor UV sidecars and painter guides (needs the tools extra)")
```

and in `main`, after the screens stage, guarded exactly like it:

```python
    if args.uvs:
        from tools.export_actor_uvs import export_bodies
        body_records = export_bodies(args.data, profile, args.out)
    else:
        body_records = []
```

carrying `body_records` into the manifest call Task 3 changes. In the `Makefile`'s `export-textures` recipe, add the skip flag beside `--no-screens`:

```make
	$(PYTHON) tools/export_textures.py "$(data)" --out "$(out)" --floors "$(or $(floors),0-7)" --guide-scale "$(or $(scale),4)" $(if $(force),--force) $(if $(filter 0,$(screens)),--no-screens) $(if $(filter 0,$(uvs)),--no-uvs)
```

and mention `uvs=0 skips the actor UV bake` in that target's `##` help text and in `AGENTS.md:24`'s `make export-textures` line.

- [ ] **Step 8: Full gate, then commit**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
git add tools/export_actor_uvs.py tests/test_export_actor_uvs.py \
        PyAitD/render/texture_export.py tools/export_textures.py Makefile AGENTS.md
git commit -m "feat: actor UV bake (xatlas unwrap, per-corner sidecar, painter guide)"
```

---

### Task 3: manifest schema 4 and the body checks

**Files:**
- Modify: `PyAitD/render/texture_export.py:64-65` (`MANIFEST_SCHEMA`, `SUPPORTED_SCHEMAS`), `:128-138` (`export_manifest`)
- Modify: `PyAitD/render/texture_check.py:217` (`check_bodies`) and its `summarize`
- Modify: `tools/check_textures.py`
- Test: `tests/test_texture_export.py`, `tests/test_texture_check.py`

**Interfaces:**
- Consumes: the `body` records `export_bodies` returns (Task 2).
- Produces: `export_manifest(records, data_dir, guide_scale, screens=(), alt_cameras=(), bodies=())` with `"schema": 4` and a `"bodies"` list; `texture_check.check_body_textures(texture_dir, data_dir, profile) -> list[Finding]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_texture_export.py` (keep its existing marker):

```python
def test_manifest_schema_is_4_and_carries_bodies():
    from PyAitD.render.texture_export import (
        MANIFEST_SCHEMA, SUPPORTED_SCHEMAS, export_manifest,
    )
    assert MANIFEST_SCHEMA == 4
    assert SUPPORTED_SCHEMAS == (1, 2, 3, 4)
    body = {"body": 12, "uv": "bodies/body012.uv.json",
            "guide": "bodies/body012-guide.png",
            "texture": "bodies/body012.png", "size": [605, 605],
            "charts": 52, "tris_sha256": "0" * 64}
    manifest = export_manifest([], "d", 4, bodies=[body])
    assert manifest["schema"] == 4
    assert manifest["bodies"] == [body]


def test_manifest_bodies_default_to_empty_so_a_uvless_export_still_writes_schema_4():
    from PyAitD.render.texture_export import export_manifest
    assert export_manifest([], "d", 4)["bodies"] == []
```

Append to `tests/test_texture_check.py` (keep its existing marker):

```python
def test_body_texture_findings_cover_size_hash_and_uv_range(tmp_path, data_dir, profile):
    """A painted body is only usable if the PNG matches the manifest's atlas
    size, the sidecar was baked against the body's current triangulation,
    and every UV is inside [0, 1]."""
    import json
    import numpy as np
    from PyAitD.engine.data.assets import Assets
    from PyAitD.render.geometry import pose_geometry
    from PyAitD.render.texture_check import check_body_textures
    from PyAitD.render.texture_export import (
        body_texture_rel_path, body_uv_rel_path, sha256_tris,
    )
    from tools.export_textures import save_png

    num = 12
    body = Assets(data_dir, profile).body(num)
    geo = pose_geometry(body, [(0, (0, 0, 0))] * len(body.groups))
    good_uvs = np.full((len(geo.tris), 3, 2), 0.5, dtype=np.float32)
    bodies = tmp_path / "bodies"
    bodies.mkdir(parents=True)

    def write(uvs, digest, size):
        (tmp_path / body_uv_rel_path(num)).write_text(json.dumps({
            "schema": 1, "size": list(size), "chart_count": 1,
            "tris_sha256": digest, "uvs": np.asarray(uvs).tolist(),
        }), encoding="utf-8")
        save_png(tmp_path / body_texture_rel_path(num),
                 np.zeros((size[1], size[0], 3), dtype=np.uint8))

    # clean
    write(good_uvs, sha256_tris(geo.tris), (64, 64))
    assert check_body_textures(tmp_path, data_dir, profile) == []
    # stale sidecar: baked against a different triangulation
    write(good_uvs, "f" * 64, (64, 64))
    assert any("triangulation" in f.detail for f in
               check_body_textures(tmp_path, data_dir, profile))
    # a UV outside [0, 1]
    bad = good_uvs.copy()
    bad[0, 0, 0] = 1.5
    write(bad, sha256_tris(geo.tris), (64, 64))
    assert any("0, 1" in f.detail or "range" in f.detail for f in
               check_body_textures(tmp_path, data_dir, profile))


def test_a_body_with_no_texture_is_not_a_finding(tmp_path, data_dir, profile):
    """Missing is the steady state, not a failure -- the same rule the
    background override follows."""
    from PyAitD.render.texture_check import check_body_textures
    (tmp_path / "bodies").mkdir(parents=True)
    assert check_body_textures(tmp_path, data_dir, profile) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_texture_export.py tests/test_texture_check.py -q`
Expected: FAIL — `assert 3 == 4` on the schema, and `ImportError: cannot import name 'check_body_textures'`.

- [ ] **Step 3: Bump the schema**

In `PyAitD/render/texture_export.py`:

```python
MANIFEST_SCHEMA = 4
SUPPORTED_SCHEMAS = (1, 2, 3, 4)   # 1: cameras; 2: + screens; 3: + alt_cameras; 4: + bodies
```

and change `export_manifest`:

```python
def export_manifest(records, data_dir, guide_scale, screens=(), alt_cameras=(), bodies=()):
    return {
        "schema": MANIFEST_SCHEMA,
        "data_dir": str(data_dir),
        "guide_scale": int(guide_scale),
        "legend": dict(LEGEND),
        "cameras": list(records),
        "alt_cameras": list(alt_cameras),
        "screens": list(screens),
        "bodies": list(bodies),
    }
```

Pass `bodies=body_records` at `tools/export_textures.py`'s `export_manifest` call site. The `--force` subset merge is unchanged: bodies merge by `body` number the same way cameras merge by `(floor, camera)` — follow whatever merge helper that file already uses, and if it merges by key, add `bodies` to it keyed on `"body"`.

- [ ] **Step 4: Add the body-texture check**

In `PyAitD/render/texture_check.py`, beside `check_bodies`:

```python
def check_body_textures(texture_dir, data_dir, profile):
    """One Finding per painted body the game could not use.

    A body with no PNG is not a finding -- missing is the steady state, the
    same rule the background override follows. A body that HAS a paint is
    checked hard: the sidecar must exist and parse, its hash must match the
    body's current triangulation (a re-export invalidates stale paints
    loudly), every UV must be inside [0, 1], and the PNG must decode at the
    sidecar's atlas size. `floor` is -3 and `camera` is the body number."""
    from PyAitD.engine.data.assets import Assets
    from PyAitD.render.geometry import pose_geometry
    from PyAitD.render.texture_export import (
        body_texture_rel_path, body_uv_rel_path, sha256_tris,
    )
    texture_dir = Path(texture_dir)
    findings = []
    assets = Assets(data_dir, profile)
    for png in sorted((texture_dir / "bodies").glob("body*.png")):
        stem = png.stem
        if stem.endswith("-guide"):
            continue                      # the painter's input, not a paint
        if not stem[4:].isdigit():
            findings.append(Finding(-3, -1, png, "invalid",
                                    "the game never loads this name; it opens body<NNN>.png"))
            continue
        num = int(stem[4:])
        if png != texture_dir / body_texture_rel_path(num):
            findings.append(Finding(-3, num, png, "invalid",
                                    f"the game never loads this name; it opens "
                                    f"{Path(body_texture_rel_path(num)).name}"))
            continue
        uv_path = texture_dir / body_uv_rel_path(num)
        if not uv_path.is_file():
            findings.append(Finding(-3, num, png, "invalid",
                                    f"painted but unmapped: {uv_path.name} is missing"))
            continue
        try:
            payload = json.loads(uv_path.read_text(encoding="utf-8"))
            uvs = np.asarray(payload["uvs"], dtype=np.float32)
            width, height = int(payload["size"][0]), int(payload["size"][1])
            digest = str(payload["tris_sha256"])
        except Exception as exc:
            findings.append(Finding(-3, num, uv_path, "invalid", f"unreadable sidecar: {exc}"))
            continue
        body = assets.body(num)
        tris = pose_geometry(body, [(0, (0, 0, 0))] * len(body.groups)).tris
        if digest != sha256_tris(tris):
            findings.append(Finding(-3, num, uv_path, "invalid",
                                    "sidecar was baked against a different triangulation; "
                                    "re-export and repaint"))
            continue
        if uvs.shape != (len(tris), 3, 2):
            findings.append(Finding(-3, num, uv_path, "invalid",
                                    f"expected {(len(tris), 3, 2)} per-corner UVs, got {uvs.shape}"))
            continue
        if float(uvs.min()) < 0.0 or float(uvs.max()) > 1.0:
            findings.append(Finding(-3, num, uv_path, "invalid",
                                    f"UVs outside [0, 1]: [{uvs.min():.4f}, {uvs.max():.4f}]"))
            continue
        try:
            pixels = load_png_rgb(png)
        except Exception as exc:
            findings.append(Finding(-3, num, png, "invalid", f"unreadable: {exc}"))
            continue
        if (pixels.shape[1], pixels.shape[0]) != (width, height):
            findings.append(Finding(-3, num, png, "invalid",
                                    f"is {pixels.shape[1]}x{pixels.shape[0]}, "
                                    f"sidecar says {width}x{height}"))
    return findings
```

Add `import json` and `import numpy as np` to that module's imports if they are not already there, and call `check_body_textures` from `tools/check_textures.py` beside `check_bodies`, folding its findings into the same `summarize` output with a `bodies` count line.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_texture_export.py tests/test_texture_check.py -q`
Expected: PASS.

- [ ] **Step 6: Full gate, then commit**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
git add PyAitD/render/texture_export.py PyAitD/render/texture_check.py \
        tools/check_textures.py tools/export_textures.py \
        tests/test_texture_export.py tests/test_texture_check.py
git commit -m "feat: manifest schema 4 with body records and the body-texture check"
```

---

### Task 4: `AssetResolver.body_texture`, `BodyGeometry.uv`, and the `build_frame` wiring

**Files:**
- Modify: `PyAitD/render/asset_resolver.py` (a path helper, a validator, `body_texture`)
- Modify: `PyAitD/render/geometry.py:24-60` (`BodyGeometry.uv`, `pose_geometry(uv=...)`)
- Modify: `PyAitD/render/scene.py` (`build_frame` passes the UVs through)
- Test: `tests/test_asset_resolver.py`, `tests/test_geometry.py`, `tests/test_scene.py`

**Interfaces:**
- Consumes: `texture_export.body_uv_rel_path`, `body_texture_rel_path`, `sha256_tris` (Task 2).
- Produces:
  - `asset_resolver.texture_body_uv_path(texture_dir, num) -> Path`, `texture_body_texture_path(texture_dir, num) -> Path`
  - `AssetResolver.body_texture(num) -> (uvs: np.ndarray (M,3,2) float32, ImageAsset) | None`, memoised per body
  - `BodyGeometry.uv: np.ndarray | None` — `(M,3,2)` float32 per corner, defaulting to `None`
  - `pose_geometry(body, group_states, actor_angles=None, ao=None, refinement=None, pose_fn=None, uv=None)` — `uv` **last**, so no positional caller breaks
- Task 5 reads `ActorDraw.geometry.uv` and the `ImageAsset` for the GL upload.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_geometry.py`:

```python
def test_body_geometry_uv_defaults_to_none_and_positional_construction_still_works():
    from PyAitD.render.geometry import pose_geometry
    body = _cube_body()
    geo = pose_geometry(body, [], None)
    assert geo.uv is None


def test_pose_geometry_carries_the_uv_through():
    import numpy as np
    from PyAitD.render.geometry import pose_geometry
    body = _cube_body()
    tris = pose_geometry(body, [], None).tris
    uv = np.full((len(tris), 3, 2), 0.25, dtype=np.float32)
    geo = pose_geometry(body, [], None, uv=uv)
    assert geo.uv is uv
```

Append to `tests/test_asset_resolver.py` (keep its existing marker):

```python
def test_body_texture_is_none_without_a_texture_dir_and_when_the_paint_is_missing(tmp_path):
    from PyAitD.render.asset_resolver import AssetResolver
    assert AssetResolver(None).body_texture(12) is None
    assert AssetResolver(None, tmp_path).body_texture(12) is None
    # a plain absence never lands in failures: missing is the steady state
    assert AssetResolver(None, tmp_path).failures == {}


def test_body_texture_returns_uvs_and_pixels_and_memoises(tmp_path):
    import json
    import numpy as np
    from PyAitD.render.asset_resolver import AssetResolver
    from PyAitD.render.texture_export import body_texture_rel_path, body_uv_rel_path
    from tools.export_textures import save_png
    (tmp_path / "bodies").mkdir(parents=True)
    uvs = np.full((2, 3, 2), 0.5, dtype=np.float32)
    (tmp_path / body_uv_rel_path(12)).write_text(json.dumps({
        "schema": 1, "size": [8, 8], "chart_count": 1,
        "tris_sha256": "0" * 64, "uvs": uvs.tolist(),
    }), encoding="utf-8")
    save_png(tmp_path / body_texture_rel_path(12), np.zeros((8, 8, 3), np.uint8))
    resolver = AssetResolver(None, tmp_path)
    first = resolver.body_texture(12)
    assert first is not None
    got_uvs, asset = first
    assert got_uvs.shape == (2, 3, 2) and got_uvs.dtype == np.float32
    assert asset.pixels.shape == (8, 8, 3)
    assert resolver.body_texture(12) is first      # memoised per body


def test_a_corrupt_body_texture_warns_once_and_falls_back(tmp_path, caplog):
    import json
    import numpy as np
    from PyAitD.render.asset_resolver import AssetResolver
    from PyAitD.render.texture_export import body_texture_rel_path, body_uv_rel_path
    (tmp_path / "bodies").mkdir(parents=True)
    (tmp_path / body_uv_rel_path(12)).write_text(json.dumps({
        "schema": 1, "size": [8, 8], "chart_count": 1,
        "tris_sha256": "0" * 64,
        "uvs": np.full((2, 3, 2), 0.5, dtype=np.float32).tolist(),
    }), encoding="utf-8")
    (tmp_path / body_texture_rel_path(12)).write_bytes(b"not a png")
    resolver = AssetResolver(None, tmp_path)
    assert resolver.body_texture(12) is None
    assert any(rec.levelname == "WARNING" for rec in caplog.records)
    assert resolver.failures                       # corrupt is recorded, missing is not
```

Append to `tests/test_scene.py`:

```python
def test_build_frame_carries_the_body_uv_when_the_resolver_has_one():
    import numpy as np
    game, floor, resolver = _stub_scene()          # the file's own helper
    tris = resolver.body(0).__class__ and None     # placeholder removed below
```

Replace that stub with a real test written against `tests/test_scene.py`'s own
`_StubResolver`: give the stub a `body_texture(num)` returning a fixed
`(uvs, ImageAsset)` for one body number and `None` for the rest, build a frame,
and assert `frame.actors[i].geometry.uv` is the stub's array for the textured
body and `None` for the others. Also add a resolver **without** a
`body_texture` attribute at all and assert `build_frame` still works — several
stub resolvers in the suite implement only the methods they use, and the
`_plate` helper at `PyAitD/render/scene.py:164` is the established pattern for
that `getattr` fallback.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_geometry.py tests/test_asset_resolver.py tests/test_scene.py -q`
Expected: FAIL — `AttributeError: 'BodyGeometry' object has no attribute 'uv'` and `AttributeError: 'AssetResolver' object has no attribute 'body_texture'`.

- [ ] **Step 3: Add the field and the resolver method**

In `PyAitD/render/geometry.py`, add the field **after** `refinement` (last, so positional construction is unaffected):

```python
    uv: np.ndarray = None               # (M,3,2) float32 per-corner atlas UVs, or None when the body is unpainted
```

and give `pose_geometry` a trailing `uv=None` parameter it passes straight into the `BodyGeometry(...)` construction. Do not default it from anything in `__post_init__`: `None` means "unpainted", which is a real state the renderer branches on.

In `PyAitD/render/asset_resolver.py`, beside `texture_body_material_path`:

```python
def texture_body_uv_path(texture_dir, num):
    return Path(texture_dir) / "bodies" / f"body{num:03d}.uv.json"


def texture_body_texture_path(texture_dir, num):
    return Path(texture_dir) / "bodies" / f"body{num:03d}.png"


def _require_body_uvs(data):
    """One verdict per bodies/body<NNN>.uv.json. Shape and range only -- the
    triangulation hash is `make check-textures`' job, not the game's: a
    stale sidecar still renders, just wrongly, and the game never refuses to
    start over a texture."""
    uvs = np.asarray(data["uvs"], dtype=np.float32)
    if uvs.ndim != 3 or uvs.shape[1:] != (3, 2):
        raise ValueError(f"uvs must be (M, 3, 2), got {uvs.shape}")
    if float(uvs.min()) < 0.0 or float(uvs.max()) > 1.0:
        raise ValueError("uvs must lie in [0, 1]")
    return uvs
```

and the method, memoised like `geometry_ao`:

```python
    def body_texture(self, num):
        """`(uvs, ImageAsset)` for body `num`, or None when it is unpainted.

        Both halves must be present: a paint with no sidecar has no way to
        land on the mesh, and a sidecar with no paint has nothing to show.
        Missing falls back silently -- an unpainted body is the steady
        state, not a failure -- while a corrupt sidecar or PNG warns once
        through `_override` and falls back. Memoised per body, including
        the None, so an unpainted body costs one filesystem check per
        session rather than one per frame."""
        if num not in self._body_textures:
            self._body_textures[num] = self._load_body_texture(num)
        return self._body_textures[num]

    def _load_body_texture(self, num):
        if self._texture_dir is None:
            return None
        data = self._override(texture_body_uv_path(self._texture_dir, num),
                              _require_body_uvs, load=load_json)
        if data is None:
            return None
        uvs = np.ascontiguousarray(np.asarray(data["uvs"], dtype=np.float32))
        pixels = self._override(texture_body_texture_path(self._texture_dir, num),
                                _require_rgb)
        if pixels is None:
            return None
        return uvs, ImageAsset(pixels.astype(np.uint8, copy=False), True)
```

with `self._body_textures = {}` beside the other caches in `__init__`.

Note the `_override` contract: it caches the *validated* loaded object, so
`_require_body_uvs` returning the array does not change what `_override`
stores — it stores the raw JSON dict. Re-deriving `uvs` from `data["uvs"]`
above is deliberate and cheap; do not "optimise" it by having the validator
mutate `data`.

- [ ] **Step 4: Wire it through `build_frame`**

In `PyAitD/render/scene.py`, add the same `getattr` fallback shape `_plate` uses:

```python
def _body_texture(resolver, body_num):
    """The resolver's `(uvs, ImageAsset)` for a body, or None -- including
    for a stub resolver that implements no `body_texture` at all, the same
    tolerance `_plate` extends to resolvers without a `plate`."""
    getter = getattr(resolver, "body_texture", None)
    return None if getter is None else getter(body_num)
```

and in the actor loop, before the `ActorDraw` construction:

```python
        texture = _body_texture(resolver, actor.body_num)
```

passing `uv=None if texture is None else texture[0]` into `pose_geometry`, and
carrying the `ImageAsset` onto the `ActorDraw` as a new trailing field:

```python
    texture: ImageAsset = None      # the body's albedo atlas, or None when unpainted
```

added **last** on `ActorDraw` so every positional construction in the suite keeps working.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_geometry.py tests/test_asset_resolver.py tests/test_scene.py -q`
Expected: PASS.

- [ ] **Step 6: Full gate, then commit**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
git add PyAitD/render/asset_resolver.py PyAitD/render/geometry.py PyAitD/render/scene.py \
        tests/test_asset_resolver.py tests/test_geometry.py tests/test_scene.py
git commit -m "feat: resolve per-body UVs and albedo atlases onto the frame"
```

---

### Task 5: the GL path — corner UV attribute, texture upload, albedo substitution

**Files:**
- Modify: `PyAitD/render/glsl.py` (`ACTOR_VSH`, `TESS_VSH`, `SCREEN_VSH`, `ACTOR_FSH`)
- Modify: `PyAitD/render/render_gl.py:138-148` (instance layout), `:1221-1252` (`_triangle_data`), `_draw_actor`, `_draw_actor_tessellated`, a texture cache
- Test: `tests/test_render_gl.py`

**Interfaces:**
- Consumes: `BodyGeometry.uv` and `ActorDraw.texture` (Task 4).
- Produces: `INSTANCE_FLOATS = 51`; `_INSTANCE_NAMES` gains `in_uv0/1/2`; `GLBackend._body_texture(actor)` memoised per `id(pixels)`.

**The attribute budget — read this before you start.** The tessellated
instance layout currently packs 12 attributes plus the per-vertex
barycentric = **13**, and `GL_MAX_VERTEX_ATTRIBS` on the target GPU is
**16** (both verified). Adding `in_uv0/1/2` takes it to **16 of 16** — the
tessellated actor path is then full, with no room for another per-corner
attribute. That is acceptable because the remaining roadmap-2 sub-projects
add no vertex attributes (K's SSAO is a screen-space prepass, L's
atmosphere is an MRT output), but it must be pinned so a future addition
fails loudly rather than mysteriously.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_render_gl.py` (keep its marker and its `gl_ctx` fixture usage):

```python
def test_instance_layout_uses_no_more_than_the_guaranteed_attribute_slots(gl_ctx):
    """The tessellated actor path packs 12 per-corner attributes plus the
    per-vertex barycentric, and adding the UVs takes it to 16 -- exactly
    GL 3.3's guaranteed minimum. This pin is the tripwire: the next
    per-corner attribute does not fit, and must find room by packing into
    an existing one instead."""
    from PyAitD.render.render_gl import INSTANCE_FLOATS, _INSTANCE_NAMES
    assert INSTANCE_FLOATS == 51
    assert len(_INSTANCE_NAMES) == 15          # 5 per corner x 3 corners
    assert len(_INSTANCE_NAMES) + 1 <= gl_ctx.info["GL_MAX_VERTEX_ATTRIBS"]
    assert gl_ctx.info["GL_MAX_VERTEX_ATTRIBS"] >= 16


def test_an_unpainted_body_renders_byte_identically_with_the_texture_path_compiled(gl_ctx):
    """The whole feature is opt-in per body: a frame whose actors carry no
    uv must produce exactly the pixels it produced before textures existed."""
    import numpy as np
    from PyAitD.render.render_gl import GLBackend
    from PyAitD.render.render_options import RenderOptions
    options = RenderOptions(scale=1, shading="smooth", lighting="scene", msaa=0,
                            realism="enhanced", smoothing=0, shadows="hard",
                            integration=0, motion="tick")
    backend = GLBackend(gl_ctx, options)
    try:
        backend.draw(_golden_frame())          # the file's own unpainted fixture
        first = backend.read_rgb()
        backend.draw(_golden_frame())
        assert np.array_equal(first, backend.read_rgb())
    finally:
        backend.release()


def test_a_painted_body_changes_pixels_and_classic_ignores_it(gl_ctx):
    """A flat red atlas over every corner must move pixels under
    realism=enhanced and move none under realism=classic."""
    import numpy as np
    from dataclasses import replace
    from PyAitD.render.render_gl import GLBackend
    from PyAitD.render.render_options import RenderOptions

    plain = _golden_frame()
    painted = _painted_frame()                 # same frame, uv + red texture (helper below)

    def render(frame, realism):
        options = RenderOptions(scale=1, shading="smooth", lighting="scene", msaa=0,
                                realism=realism, smoothing=0, shadows="hard",
                                integration=0, motion="tick")
        backend = GLBackend(gl_ctx, options)
        try:
            backend.draw(frame)
            return backend.read_rgb()
        finally:
            backend.release()

    assert not np.array_equal(render(plain, "enhanced"), render(painted, "enhanced"))
    assert np.array_equal(render(plain, "classic"), render(painted, "classic"))
```

Write `_painted_frame()` beside `_golden_frame()` in the same file: take
`_golden_frame()`'s actors, give each `ActorDraw` a `geometry` whose `uv` is
`np.full((len(tris), 3, 2), 0.5, np.float32)` (via `dataclasses.replace` on
the geometry) and a `texture` of `ImageAsset(np.tile([[[255, 0, 0]]], (8, 8, 1)).astype(np.uint8), True)`,
then `dataclasses.replace` the frame with those actors.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_render_gl.py -q`
Expected: FAIL — `assert 45 == 51` on the layout pin, and the painted frame renders identically to the plain one because nothing samples a texture yet.

- [ ] **Step 3: Widen the instance layout**

In `PyAitD/render/render_gl.py`, replace the layout block at `:138-148`:

```python
# One instance per source triangle for the tessellating programs: per
# corner k, (pos.xyz, ao), (normal.xyz, straight of edge k -> k+1),
# (rgb, palette index), rest.xyz, uv.xy -- 17 floats, 51 per triangle,
# fifteen packed attributes plus the per-vertex barycentric: 16 of the 16
# slots GL 3.3 guarantees, which is all of them. A further per-corner
# attribute does not fit and must pack into an existing one instead
# (tests/test_render_gl.py pins this).
INSTANCE_FLOATS = 51
_INSTANCE_ATTRIBUTES = ("4f", "4f", "4f", "3f", "2f") * 3
_INSTANCE_NAMES = ("in_p0", "in_n0", "in_c0", "in_r0", "in_uv0",
                   "in_p1", "in_n1", "in_c1", "in_r1", "in_uv1",
                   "in_p2", "in_n2", "in_c2", "in_r2", "in_uv2")
```

`instance_layout` needs no change: it already turns an attribute the program
does not read into padding of the same width, so the shadow program (which
never samples albedo) keeps the same stride.

Wherever the instance buffer is packed, append each corner's UV after its
`rest`, using `geometry.uv` when present and `np.zeros((M, 3, 2), "f4")`
when it is `None` — the shader gates on a uniform, not on the UV value, so
an unpainted body's zeros are never sampled.

- [ ] **Step 4: Add the UV to the non-tessellated path**

In `_triangle_data` (`:1221`), add the per-corner UV to the triangle branch:

```python
            uv = (np.zeros((len(idx), 2), "f4") if geometry.uv is None
                  else geometry.uv.reshape(-1, 2)[:len(idx)].astype("f4"))
```

appended to that branch's `np.concatenate([...], axis=1)`, and give the sphere
branch `uv = np.full((len(pos), 2), -1.0, "f4")` — spheres share this buffer
and stay untextured, and a negative UV is the sentinel the shader reads for
that. Widen the empty return from `np.zeros((0, 14), dtype="f4")` to
`(0, 16)` and add `"2f"` / `"in_uv"` to the vertex-array format and names
wherever `_render_triangles` binds this buffer.

- [ ] **Step 5: Cache the texture upload**

Add to `GLBackend`, following `_draw_background`'s `id(pixels)` cache idiom
(`:843-860`) including its keep-alive reference:

```python
    def _body_texture(self, asset):
        """The GL texture for a body's albedo atlas, memoised on the source
        array's identity the way the background is. Mipmapped and
        anisotropically filtered: an actor's atlas is minified hard at
        distance, and without mips the chart gutters alias into each
        other."""
        if asset is None:
            return None
        pixels = asset.pixels
        key = (id(pixels), pixels.shape)
        cached = self._body_tex_cache.get(key)
        if cached is None:
            data = np.ascontiguousarray(pixels, dtype=np.uint8).tobytes()
            tex = self._ctx.texture((pixels.shape[1], pixels.shape[0]), 3, data)
            tex.build_mipmaps()
            tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
            tex.anisotropy = min(8.0, self._ctx.max_anisotropy)
            tex.repeat_x = tex.repeat_y = False
            # keep the source array alive for as long as its id() is the key
            self._body_tex_cache[key] = (tex, pixels)
            cached = self._body_tex_cache[key]
        return cached[0]
```

with `self._body_tex_cache = {}` in `__init__` and a release loop in
`release()` beside the other texture teardowns.

In `_draw_actor` and `_draw_actor_tessellated`, before the triangle draw:

```python
        texture = self._body_texture(actor.texture)
        textured = texture is not None and self._options.realism != "classic"
        if textured:
            texture.use(5)                    # unit 5: 0-4 are taken
        _set_uniform(prog, "body_albedo", 5)
        _set_uniform(prog, "has_body_texture", 1 if textured else 0)
```

binding `prog` to whichever program that draw uses. Unit 5 must not collide
with the shadow map (4) or any other bound sampler — check the `use(...)`
calls in this file and pick the next free unit if 5 is taken.

- [ ] **Step 6: Substitute the albedo in the shaders**

In `PyAitD/render/glsl.py`:

- `ACTOR_VSH` and `SCREEN_VSH`: add `in vec2 in_uv;` and `out vec2 v_uv;`,
  with `v_uv = in_uv;` in `main`.
- `TESS_VSH`: add `in vec2 in_uv0; in vec2 in_uv1; in vec2 in_uv2;` and
  `out vec2 v_uv;`, interpolating barycentrically exactly as the colour does
  at `:370` — `v_uv = in_uv0 * u + in_uv1 * v + in_uv2 * w;`. This is what
  makes UVs follow PN tessellation the same way normals do.
- `ACTOR_FSH`: add `in vec2 v_uv; uniform sampler2D body_albedo; uniform int has_body_texture;`
  and, immediately before the first use of `v_color` in the lit path (the
  `vec3 base = v_color * ...` line at `:238`), introduce the substitution:

```glsl
    // Paint changes colour, not physics: the sampled albedo replaces the
    // ramp colour, while the palette-index material table keeps driving
    // specular, rim, bump, sss and emissive. A negative uv marks a sphere,
    // which shares the triangle buffer and stays untextured.
    vec3 albedo = v_color;
    if (has_body_texture != 0 && v_uv.x >= 0.0) {
        albedo = texture(body_albedo, v_uv).rgb;
    }
```

then replace `v_color` with `albedo` **only** in the albedo positions: the
`base` expression at `:238`, the specular tint mix at `:276`, and the
emissive mix at `:285`. Leave the flat and lambert early-outs at `:122` and
`:132` reading `v_color` — those are the `realism=classic` and non-smooth
paths, which the spec says ignore body textures entirely.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_render_gl.py -q`
Expected: PASS, including the classic golden.

- [ ] **Step 8: Full gate, then commit**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
git add PyAitD/render/glsl.py PyAitD/render/render_gl.py tests/test_render_gl.py
git commit -m "feat: sample body albedo atlases through the tessellated and flat actor paths"
```

---

### Task 6: the proof document and the docs

**Files:**
- Modify: `tools/prove_graphics.py`, `tests/test_prove_graphics.py`
- Create: `docs/actor-textures-proof.md`
- Modify: `CONTEXT.md`, `AGENTS.md`, `README.md`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Add a painted twin to the proof tool**

The proof needs a painted body without shipping one, so synthesise it: in
`tools/prove_graphics.py`, add a `painted=False` parameter to
`render_fixture` that, when true, gives every actor's geometry a
`uv` of `np.full((len(tris), 3, 2), ...)` derived from each triangle's index
(so the atlas is sampled non-uniformly rather than flat) and a generated
checker `ImageAsset`, via `dataclasses.replace` on the `ActorDraw`s — the
same shape the `-tickmotion` twin already uses for its synthetic snapshot.
Add a `-painted` pair after the `-tickmotion` pair, with the row carrying a
`"painted"` label so it cannot collide with another row's tuple (the
`-tickmotion` row's `label` field from the motion sub-project is the
precedent). Extend `tests/test_prove_graphics.py`'s `output_paths` pin for
the new pair and the new label, following the existing arms.

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_prove_graphics.py -q` — PASS.

- [ ] **Step 2: Write the proof document**

Create `docs/actor-textures-proof.md`, following `docs/soft-shadows-proof.md`'s
shape and `docs/motion-interpolation-proof.md`'s honesty rules:

```markdown
# Actor surface textures proof

Date: <run date>
Spec: `docs/superpowers/specs/2026-08-31-actor-realism-roadmap-2-design.md` (sub-project J)
Plan: `docs/superpowers/plans/2026-08-31-actor-textures.md`

**This document's "Manual attestation" table is a checklist for a human
with real game data and a real window; every row starts `pending`.**
Everything under "Automated gates" and "The bake" was actually run, in
this environment, on this branch, and the output shown is the real
output of that run.

## What changed

Bodies can carry a painted albedo atlas. `make export-textures` bakes a
per-corner UV sidecar and a painter's guide per body; an external painter
produces `bodies/body<NNN>.png`; the runtime samples it in place of the
ramp colour while the palette-index material table still drives every
physical term. A body with no paint renders exactly as before, and
`realism=classic` ignores paints entirely.

## Automated gates

<paste the real output of the focused suites and the full gate>

## The bake

<paste the real output of `make export-textures uvs=1`, the per-body
atlas sizes and chart counts, and `make check-textures` on the result>

## Attribute budget

The tessellated actor path now packs 16 of the 16 vertex attributes GL 3.3
guarantees (12 per-corner + 3 UV + the barycentric), measured at
`GL_MAX_VERTEX_ATTRIBS = <observed>` on <GPU>. Record the number, because
the next per-corner attribute does not fit.

## Frame time

<attic fixture, scale 4, msaa 4, smoothing 2: unpainted vs painted,
measured the way the soft-shadows and motion proofs measured theirs, with
the command shown. The roadmap's budget gate is 1.5x across all four
sub-projects; record J's share here.>

## Manual attestation

| Check | Result |
|---|---|
| Paint one body, run the game: the paint appears on that actor and no other | pending |
| Delete the paint, keep the sidecar: the actor falls back silently, no notice | pending |
| Corrupt the paint: one warning, the actor falls back, the game keeps running | pending |
| Re-export UVs after a triangulation change: `make check-textures` reports the stale paint | pending |
| `realism=classic`: the paint is ignored | pending |
| A painted body at distance: chart gutters do not bleed (mips + anisotropy) | pending |

## Known limitations

- **Body numbers are archive-scoped.** Bodies live in per-hero archives and
  the same number can name a different body for Carnby and Emily, while a
  paint is keyed by number alone (`bodies/body<NNN>.png`). A paint made for
  one hero's body 12 will be applied to the other hero's body 12 as well.
  This is inherited from the existing per-body material override, which keys
  the same way; fixing it would mean a hero-qualified path for both, and is
  out of scope here. Record which hero's archive each paint was authored
  against.
- **The bake covers every body the archives expose (272 per hero), not just
  the ones a floor can show.** That is deliberate — the archive is the unit
  the game loads from — but it means a full bake writes a guide per body.
```

Fill the gate and bake blocks by actually running the commands and pasting
real output. If a figure cannot be measured in this environment, say so
plainly and say why — never leave a bare placeholder and never invent a number.

- [ ] **Step 3: Update the three docs**

- `CONTEXT.md`: add a milestone row after the motion-interpolation row —
  `| Actor surface textures (roadmap 2 J) | xatlas UV bake, per-corner sidecar + painter guide, manifest schema 4, albedo atlas sampled in the actor shader | automated gates green; windowed attestation pending (docs/actor-textures-proof.md) |` —
  and a render-module row for the changed `asset_resolver` responsibility.
  Update the `render/geometry.py` row to mention `uv`.
- `AGENTS.md`: in the `## Conventions` block for `render/`, record that a
  body's paint changes albedo only while the material table keeps driving
  the physical terms, that lines/points/spheres stay untextured (spheres via
  the negative-UV sentinel they share the triangle buffer with), that
  `realism=classic` ignores paints, and that the tessellated instance layout
  is now at 16 of 16 attributes. Update the `make export-textures` line at
  `:24` for the UV stage and `uvs=0`.
- `README.md`: in the `make export-textures` paragraph, say that the export
  also writes a per-body UV sidecar and painter guide, and that
  `DIR/bodies/body<NNN>.png` is the painted albedo the game will use when
  present. Mention it in the texture-directory contents list beside
  `DIR/bodies/body<NNN>.json`.

- [ ] **Step 4: Full gate, then commit**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
git add -A
git commit -m "docs: actor-textures proof, painted proof twin, docs"
```

---

## Plan self-review (record kept)

- **Spec coverage.** J's design points all land: the tools extra and the
  import ban (Task 1); the shared-triangulation unwrap, per-corner sidecar
  with content hash, and the AO-layered guide with gutters (Task 2); manifest
  schema 3 → 4 and the `check-textures` body checks (Task 3);
  `AssetResolver.body_texture`, `BodyGeometry.uv` and the `build_frame`
  wiring with the silent/warn fallback (Task 4); the corner UV attribute,
  memoised mipmapped upload, albedo substitution and tessellation
  interpolation with the `classic` identity (Task 5); the proof document and
  docs (Task 6).
- **Deliberate deviations, both recorded above:** Pillow is dropped from the
  tools extra (the repo already has an atomic PNG writer, so it would earn
  nothing), and the spec's "AO layer" is rendered as a per-triangle shade of
  the guide fill rather than a separate image layer — the guide is one PNG a
  painter opens, and a second layer would need a format the repo does not
  write.
- **Placeholders.** None. Four steps deliberately defer to the target file's
  own local shape rather than inventing names: `_imported_names` in Task 1,
  `parse_floors` and the manifest merge helper in Tasks 2-3, `_stub_scene`
  and `_painted_frame` in Tasks 4-5. Each says exactly what the contract is
  and that the assertion content is what matters.
- **Type consistency.** `(M,3,2) float32` per-corner UVs are the same object
  end to end: produced by `unwrap_body().uvs`, serialised by
  `sidecar_payload`, validated by `_require_body_uvs`, returned by
  `body_texture()[0]`, carried as `BodyGeometry.uv`, and packed as
  `in_uv0/1/2`. `body_texture` returns `(uvs, ImageAsset) | None` in Tasks 4
  and 5 alike. `sha256_tris` is the one hash function, used by the bake, the
  checker and their tests. `ActorDraw.texture` and `BodyGeometry.uv` are both
  added last on their dataclasses so positional construction across the suite
  keeps working.
- **Risk carried forward.** Task 5 lands the tessellated path on 16 of 16
  vertex attributes. That is verified to fit on the target GPU and pinned by
  a test, but it means sub-projects K and L must not add a per-corner
  attribute — neither plans to.
