# Light Transport (Roadmap 2, Sub-project K) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the actor layer screen-space ambient occlusion that sees pose and neighbours, and let the room's collision boxes receive the hero's shadow — both behind knobs that land off.

**Architecture:** Two independent GL features sharing one plan. K1 adds a half-resolution G-buffer prepass (view normals + linear view depth in one RGBA16F attachment), an SSAO pass pinned against a pure-numpy twin in `render/ssao.py`, a bilateral blur, and a fill-share attenuation in `_ACTOR_FSH`. K2 adds a third `shadows` value, `room`, whose receiver pass rasterises the floor plane and the top faces of the current room's `hard_cols`, samples the existing light-view shadow map, and darkens the plate before any body is drawn. Every new pass follows the existing `STENCIL_VSH` + `_shadow_quad` fullscreen idiom or the instanced-triangle idiom already in `render_gl.py`.

**Tech Stack:** Python 3.12, numpy, moderngl, GLSL 330. No new dependency of any kind — the survey found nothing packaged worth reusing, and reference implementations are source material, not imports.

**Spec:** `docs/superpowers/specs/2026-08-31-actor-realism-roadmap-2-design.md` (sub-project K, plus its "Options, UI and tooling", "Task ordering", "Testing" and "Limitations" sections). Read the spec's K section before starting.

## Global Constraints

- **Runtime dependencies stay exactly pygame-ce + moderngl + numpy.** K adds none. `xatlas` and `libigl` remain tools-only and banned from `PyAitD/` by `tests/test_layering.py`.
- **Every knob's "off" value runs today's code verbatim.** `occlusion="off"` and `shadows` in `("hard", "soft")` must produce byte-identical output to the current renderer. Both knobs land off/unchanged and flip only in the tasks named below.
- **All new behaviour lives under `lighting="scene"`.** `lighting="fixed"` stays the whole legacy renderer, byte for byte, at every combination of the new options.
- **SSAO attenuates the fill share only.** Key and specular are already gated by the shadow map's `vis`, and F's rule — a shadowed limb falls to the room's fill, never to black — extends to occlusion. See "Deviation from the spec, deliberate" below for what this means for `hemi`.
- **`tests/golden/scene_lit_classic.npy` must keep passing and must never be regenerated.** If it fails, the change altered the identity path and the fix belongs in the code.
- `skel.skin()`, `draw_list`, picking, masks, the mouse contract and all simulation code stay untouched.
- **`PyAitD/render/glsl.py` is strings only** — pinned by `tests/test_layering.py::test_glsl_is_strings_only`. Every new shader is an `UPPER_CASE = """..."""` assignment there and nothing else.
- **`render/ssao.py` must stay pure.** `tests/test_layering.py`'s `GRAPHICS_OWNERS` (`tests/test_layering.py:41-46`) lists the only `render/` modules allowed to import pygame or moderngl; a new pure module fails the scan without being listed anywhere, which is the intent. Do not add `ssao` to that dict.
- **Every new GL resource is released in `release()` and counted by the leak test.** `tests/test_render_gl.py::test_init_failure_releases_every_already_allocated_gl_object` asserts an exact `leak_checked` total; a resource missing from its attribute tuple is a resource the test does not cover.
- Every source file starts with `# SPDX-License-Identifier: GPL-2.0-only`.
- Every test file carries exactly one subject marker (`render` for `tests/test_ssao.py`); `--strict-markers` is on. Edits to existing test files keep their marker.
- This repo never ships game data or generated textures: `data/aitd1/textures` is git-ignored and stays that way.
- Run the full gate before calling any task done: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q` (the repo's authoritative gate is `make test`).
- Commit after every task with a `feat:`/`test:`/`docs:` message as shown.

## Verified facts this plan is built on

Checked against the real code and a real GL context on the target machine (macOS arm64, CPython 3.12, Apple M3 Max, GL 4.1 Metal - 90.5). Do not re-derive them; do check them if something surprises you.

| Fact | Evidence |
|---|---|
| Per-actor depth clears really do leave no shared depth to sample | `render_gl.py:719-721`, inside the per-actor draw loop |
| `ctx.depth_texture(...)` defaults to `compare_func='<='` (a `sampler2DShadow`); assigning `compare_func = ''` turns comparison off and plain `sampler2D` reads work | probed |
| A half-float (`dtype='f2'`) colour attachment works, and a depth texture reads back as float32 | probed at 160x100 |
| `GL_MAX_COLOR_ATTACHMENTS` and `GL_MAX_DRAW_BUFFERS` are both **8** | probed |
| `ctx.max_samples` is **4** on this GPU, so `msaa=8` clamps — `self.samples = min(options.msaa, ctx.max_samples)` already handles it | `render_gl.py:456`, probed |
| The tessellated instance layout is at **exactly 16 of 16** vertex-attribute slots (15 instance names + `in_bary`) | `render_gl.py:138-149`, pinned by `tests/test_render_gl.py:2902-2927` |
| **Neither K pass may add a vertex attribute to the tessellated path.** Both are fullscreen passes or use their own small VAO, so neither does | consequence of the above |
| Texture units 0-6 are taken (0 background, 1 mask, 2 shadow/blur, 3 material, 4 shadow map, 5 body albedo *and* composite plate, 6 actor); **units 7+ are free** | `render_gl.py:898,728,1081,642,673,861,1236,1237` |
| The fullscreen idiom is `STENCIL_VSH` (imported into render_gl.py as `_STENCIL_VSH` -- every glsl constant is aliased with a leading underscore there, `render_gl.py:34`) + the shared `self._shadow_quad` buffer + a per-program VAO, deriving screen UV from `gl_FragCoord.xy / target_size` | `render_gl.py:374-383,486-487`; `glsl.py:405-409` |
| `soften` is the pure-numpy-twin precedent and `test_the_soft_blur_matches_the_numpy_twin` the pinning pattern: seed the backend's own texture, run one private pass method, read back, compare at `2.5/255` | `PyAitD/render/lighting.py:351-380`; `tests/test_render_gl.py:1820` |
| The leak test enumerates 40 named attributes plus 4 subpatch buffers and asserts `leak_checked == 44` | `tests/test_render_gl.py:839-882` |
| `RenderOptions` has 11 fields ending in `motion`; a new field must be appended last to keep positional construction working | `PyAitD/render/render_options.py:47-59`, and `validate_render_options`'s positional build at `:139` |
| `_MENU_RENDER_FIELDS` gates which fields a settings save persists and must gain the new key | `PyAitD/app/shell.py:676` |
| The Realism page has room for exactly the two rows K and L add: 8 rows ends at y=186, inside the 200-row screen | `PyAitD/app/ui.py:693-697`; `tests/test_ui_render.py:823-834` asserts it dynamically |
| `render/occlusion.py` already exists — it is the **baked rest-pose vertex AO** (`bake_vertex_ao`), a different feature. The new module is `render/ssao.py` and must not collide | `PyAitD/render/occlusion.py`, `tests/test_occlusion.py` |
| `Zone` is `x1,x2,y1,y2,z1,z2,type,parameter` (room-local ints); `Room` carries `world_x/y/z` and `hard_cols: list[Zone]` | `PyAitD/engine/data/formats.py:10-40` |
| `_box_corners(z)` already exists and returns the 8 corners in a fixed order, y2 face first | `PyAitD/render/texture_export.py:182-186` |
| Room-space coordinates go to `CameraView` as-is: the room's world offset is already folded into `CameraState.from_camera` | `PyAitD/render/texture_export.py:196-198`, and `scene.build_frame` |
| `FrameDescription`'s fields are `camera, background, palette, actors, masks, light, plate` — a new field must be appended last | `PyAitD/render/scene.py:107-121` |
| The shadow map is a 2048x2048 depth texture at unit 4, sampled as `sampler2DShadow`, and lines/points never cast (they never reach the instanced path) | `render_gl.py:401-406,673`; `glsl.py:78,222-236` |
| `vis` is the shadow visibility term; it already gates the key share, the SSS tint and the specular | `glsl.py:222-236,251,267,290` |

**Deviation from the spec, deliberate — what "fill/hemisphere share" resolves to in this shader.** The spec says SSAO attenuates "the fill/hemisphere share only". In `_ACTOR_FSH` those are not two separable terms:

- `fill_tint` is separable: it is the additive baseline inside `base` at `glsl.py:251`, and multiplying it alone attenuates exactly the ambient share.
- `hemi` (`glsl.py:279`) is **not** an ambient term. It is a whole-shading multiplier applied at `glsl.py:293` as `base * (grain * hemi * occl)`, so it scales the key share too. Attenuating `hemi` by SSAO would therefore attenuate the key — contradicting the spec's own decision 7, which exists precisely because the shadow map already owns the key.
- Likewise `occl` (`glsl.py:284`, the baked AO times the contact term) multiplies the whole of `base`. **Do not fold SSAO into `occl`**, however tempting the name: it would darken the key share along with the fill.

So this plan attenuates `fill_tint` and nothing else. That is the only insertion point in this shader that satisfies decision 7 literally. Task 4 records the same reasoning in a code comment, because the next reader will reach for `occl` first.

---

### Task 1: `render/ssao.py` — the kernel and the numpy twin

**Files:**
- Create: `PyAitD/render/ssao.py`
- Create: `tests/test_ssao.py` (marker: `render`)

**Interfaces:**
- Consumes: nothing. This task is pure numpy and stands alone.
- Produces:
  - `ssao.SSAO_KERNEL_SIZE = 16`
  - `ssao.SSAO_RADIUS = 14.0` (world/view units — the game's actors are roughly 200 units tall)
  - `ssao.SSAO_BIAS = 0.6`
  - `ssao.hemisphere_kernel(count=SSAO_KERNEL_SIZE, seed=7) -> np.ndarray` — `(count, 3)` float32, every sample in the `+z` hemisphere, lengths clustered toward the origin
  - `ssao.noise_rotations(size=4, seed=11) -> np.ndarray` — `(size, size, 2)` float32 unit vectors in the xy plane, the per-pixel rotation tile
  - `ssao.ssao_reference(depth, normals, kernel, rotations, proj_xy, radius=SSAO_RADIUS, bias=SSAO_BIAS) -> np.ndarray` — `(H, W)` float32 occlusion in `[0, 1]`, where **1.0 means unoccluded**

**Why 1.0 means unoccluded:** the shader multiplies `fill_tint` by this value, so the neutral value has to be the multiplicative identity. Naming it `occlusion` while 1.0 means "none" is confusing, so the docstring says so explicitly and the tests assert it in both directions.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ssao.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""render/ssao.py: the screen-space ambient occlusion twin.

Pure numpy -- the GL pass in render_gl.py is pinned against these same
functions by tests/test_render_gl.py, exactly as `soften` pins the
penumbra blur."""
import numpy as np
import pytest

from PyAitD.render.ssao import (
    SSAO_BIAS, SSAO_KERNEL_SIZE, SSAO_RADIUS,
    hemisphere_kernel, noise_rotations, ssao_reference,
)

pytestmark = pytest.mark.render


def _flat_plate(h=32, w=32, depth=500.0):
    """A wall square-on to the camera: constant depth, normals toward it.

    View space looks down -z, so a surface *facing* the camera has its
    normal pointing back along +z. Getting this sign wrong is not a
    cosmetic error: the hemisphere would push every sample away from the
    camera instead of toward it, and a flat plate would occlude itself
    (measured: min occlusion 0.125 with the sign flipped, 1.0 with it
    right)."""
    d = np.full((h, w), depth, dtype=np.float32)
    n = np.zeros((h, w, 3), dtype=np.float32)
    n[..., 2] = 1.0
    return d, n


def test_the_kernel_is_a_clustered_plus_z_hemisphere():
    k = hemisphere_kernel()
    assert k.shape == (SSAO_KERNEL_SIZE, 3)
    assert k.dtype == np.float32
    assert (k[:, 2] > 0.0).all()                 # every sample in the +z hemisphere
    lengths = np.linalg.norm(k, axis=1)
    assert (lengths <= 1.0 + 1e-6).all()
    # Clustered toward the origin: more than half the samples inside the
    # half-radius, which a uniform ball would not give (that is 12.5%).
    assert (lengths < 0.5).sum() > SSAO_KERNEL_SIZE // 2


def test_the_kernel_is_deterministic_for_a_seed():
    assert np.array_equal(hemisphere_kernel(seed=3), hemisphere_kernel(seed=3))
    assert not np.array_equal(hemisphere_kernel(seed=3), hemisphere_kernel(seed=4))


def test_the_rotation_tile_is_unit_vectors():
    r = noise_rotations()
    assert r.shape == (4, 4, 2)
    assert np.allclose(np.linalg.norm(r, axis=2), 1.0, atol=1e-6)


def test_a_flat_plate_occludes_nothing():
    d, n = _flat_plate()
    out = ssao_reference(d, n, hemisphere_kernel(), noise_rotations(), (2.0, 2.0))
    assert out.shape == (32, 32)
    # A plane cannot occlude itself: every sample lands in front of it.
    assert out.min() > 0.98


def test_occlusion_is_bounded_to_the_unit_range():
    rng = np.random.default_rng(5)
    d = rng.uniform(200.0, 900.0, (24, 24)).astype(np.float32)
    n = rng.normal(size=(24, 24, 3)).astype(np.float32)
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    out = ssao_reference(d, n, hemisphere_kernel(), noise_rotations(), (2.0, 2.0))
    assert out.min() >= 0.0 and out.max() <= 1.0


def test_a_nearby_step_occludes_the_pixels_beside_it():
    """A wall with a block of columns standing 10 units nearer the camera.

    Wall pixels next to that step have most of their hemisphere blocked by
    it and must come out darker; pixels far from it must not. Ten units
    against a 14-unit radius is deliberate -- the range check discards an
    occluder much further away than the radius, so a step of 200 units
    would (correctly) occlude nothing at all."""
    h = w = 48
    d = np.full((h, w), 500.0, dtype=np.float32)
    d[:, :8] = 490.0
    n = np.zeros((h, w, 3), dtype=np.float32)
    n[..., 2] = 1.0
    out = ssao_reference(d, n, hemisphere_kernel(), noise_rotations(), (2.0, 2.0))
    beside = out[:, 8:11].mean()
    far = out[:, 30:40].mean()
    # Measured on the reference implementation: 0.9219 and 1.0000.
    assert beside < 0.96, beside
    assert far > 0.99, far


def test_zero_radius_occludes_nothing():
    """The neutral identity the GL pass leans on: with the radius at zero
    every sample lands on the pixel itself, and nothing is occluded."""
    rng = np.random.default_rng(9)
    d = rng.uniform(200.0, 900.0, (16, 16)).astype(np.float32)
    n = np.zeros((16, 16, 3), dtype=np.float32)
    n[..., 2] = -1.0
    out = ssao_reference(d, n, hemisphere_kernel(), noise_rotations(), (2.0, 2.0), radius=0.0)
    assert np.allclose(out, 1.0)


def test_background_pixels_are_untouched():
    """Depth exactly 0.0 marks a pixel the prepass never wrote. It must
    come back fully unoccluded, not darkened by whatever the neighbouring
    geometry happens to be."""
    d, n = _flat_plate()
    d[:8, :] = 0.0
    out = ssao_reference(d, n, hemisphere_kernel(), noise_rotations(), (2.0, 2.0))
    assert np.allclose(out[:8, :], 1.0)


def test_the_defaults_are_the_documented_constants():
    assert SSAO_KERNEL_SIZE == 16
    assert SSAO_RADIUS == 14.0
    assert SSAO_BIAS == 0.6
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ssao.py -q`
Expected: FAIL at import — `ModuleNotFoundError: No module named 'PyAitD.render.ssao'`.

- [ ] **Step 3: Write the module**

Create `PyAitD/render/ssao.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Screen-space ambient occlusion: the kernel, the rotation tile, and the
numpy twin render_gl's SSAO_FSH is pinned against.

Pure numpy: no pygame, no GL, no engine imports -- the same rule
render/lighting.py follows, and tests/test_layering.py enforces it by
scanning every render/ module that is not a declared graphics owner.

This is *not* render/occlusion.py. That module bakes per-vertex AO into a
body's rest pose once, and cannot see pose or neighbours; this one runs
per frame over the depth the actors actually occupy, which is where
creases, armpits and the gap under a looming monster come from. The two
are additive by design.

Conventions, shared verbatim with SSAO_FSH:

- View space looks down -z, and `depth` is **positive linear distance**
  from the camera, not a projective depth buffer value. The prepass
  writes it into the G-buffer's alpha channel precisely so neither side
  has to invert a projection matrix -- that inversion is where a twin and
  a shader most easily disagree.
- A pixel the prepass never covered carries depth exactly 0.0 and is
  returned unoccluded.
- The result is a *multiplier*: 1.0 means no occlusion, 0.0 means fully
  occluded. The shader multiplies the fill share by it, so the neutral
  value has to be the multiplicative identity.
"""
import numpy as np

SSAO_KERNEL_SIZE = 16
# In view-space units. AITD1's actors stand about 200 units tall, so this
# is roughly a hand's width -- large enough to find the gap between two
# actors, small enough not to darken a whole limb against the torso.
SSAO_RADIUS = 14.0
# Depth slack before a nearer sample counts as an occluder, in the same
# units. Below this, a plane's own sampling noise reads as self-occlusion.
SSAO_BIAS = 0.6


def hemisphere_kernel(count=SSAO_KERNEL_SIZE, seed=7):
    """`(count, 3)` sample offsets in the +z hemisphere, clustered toward
    the origin so near-surface detail gets most of the taps.

    The quadratic ramp is the standard LearnOpenGL-class weighting: it is
    the shape of the kernel that matters, not its provenance."""
    rng = np.random.default_rng(seed)
    v = rng.normal(size=(count, 3)).astype(np.float32)
    v[:, 2] = np.abs(v[:, 2])                     # fold into the +z hemisphere
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    t = (np.arange(count, dtype=np.float32) + 0.5) / count
    v *= (0.1 + 0.9 * t * t)[:, None]             # cluster near the origin
    return np.ascontiguousarray(v, dtype=np.float32)


def noise_rotations(size=4, seed=11):
    """`(size, size, 2)` unit vectors, tiled over the screen to rotate the
    kernel per pixel. Trading banding for high-frequency noise, which the
    blur in Task 4 then removes."""
    rng = np.random.default_rng(seed)
    a = rng.uniform(0.0, 2.0 * np.pi, (size, size)).astype(np.float32)
    return np.ascontiguousarray(np.stack([np.cos(a), np.sin(a)], axis=2), dtype=np.float32)


def _view_position(depth, proj_xy):
    """Back-project every pixel to its view-space position.

    `proj_xy` is the projection's (fx, fy): the same pair the shader gets,
    so both sides run the identical pinhole relation
    `ndc = (x/-z) * f` and neither inverts a matrix."""
    h, w = depth.shape
    ndc_x = (np.arange(w, dtype=np.float32) + 0.5) / w * 2.0 - 1.0
    ndc_y = (np.arange(h, dtype=np.float32) + 0.5) / h * 2.0 - 1.0
    gx, gy = np.meshgrid(ndc_x, ndc_y)
    z = -depth
    return np.stack([gx * depth / proj_xy[0], gy * depth / proj_xy[1], z], axis=2)


def _project(p, proj_xy, shape):
    """View-space points to integer pixel coordinates, clamped in range.

    Returns `(ix, iy, ok)` where `ok` is False for anything behind or on
    the camera plane, which has no screen position at all."""
    h, w = shape
    z = p[..., 2]
    ok = z < -1e-6
    safe = np.where(ok, -z, 1.0)
    ndc_x = p[..., 0] * proj_xy[0] / safe
    ndc_y = p[..., 1] * proj_xy[1] / safe
    ix = np.clip(((ndc_x + 1.0) * 0.5 * w).astype(np.int32), 0, w - 1)
    iy = np.clip(((ndc_y + 1.0) * 0.5 * h).astype(np.int32), 0, h - 1)
    return ix, iy, ok


def ssao_reference(depth, normals, kernel, rotations, proj_xy,
                   radius=SSAO_RADIUS, bias=SSAO_BIAS):
    """`(H, W)` occlusion multiplier in [0, 1]; 1.0 is unoccluded.

    `depth` is positive linear view distance, 0.0 where nothing was drawn.
    `normals` are unit view-space normals. `kernel` and `rotations` come
    from the two builders above. Every step below has a line-for-line
    counterpart in SSAO_FSH."""
    depth = np.asarray(depth, dtype=np.float32)
    normals = np.asarray(normals, dtype=np.float32)
    h, w = depth.shape
    covered = depth > 0.0
    pos = _view_position(depth, proj_xy)

    # Per-pixel kernel basis: Gram-Schmidt against the tiled rotation, so
    # neighbouring pixels sample different directions.
    tile = rotations.shape[0]
    ry, rx = np.meshgrid(np.arange(h) % tile, np.arange(w) % tile, indexing="ij")
    rot = rotations[ry, rx]
    rand = np.stack([rot[..., 0], rot[..., 1], np.zeros((h, w), dtype=np.float32)], axis=2)
    n = normals
    tangent = rand - n * np.sum(rand * n, axis=2, keepdims=True)
    tlen = np.linalg.norm(tangent, axis=2, keepdims=True)
    # A normal parallel to the rotation leaves a zero tangent; any
    # perpendicular direction will do there.
    fallback = np.zeros_like(tangent)
    fallback[..., 1] = 1.0
    tangent = np.where(tlen > 1e-6, tangent / np.maximum(tlen, 1e-6), fallback)
    bitangent = np.cross(n, tangent)

    occluded = np.zeros((h, w), dtype=np.float32)
    for k in kernel:
        offset = (tangent * k[0] + bitangent * k[1] + n * k[2]) * radius
        sample = pos + offset
        ix, iy, ok = _project(sample, proj_xy, (h, w))
        sample_depth = depth[iy, ix]
        sample_dist = -sample[..., 2]
        # An occluder is geometry nearer the camera than the sample point.
        hit = ok & (sample_depth > 0.0) & (sample_depth < sample_dist - bias)
        # Range check: a wall far behind the pixel is not its occluder.
        delta = np.abs(depth - sample_depth)
        weight = np.clip(radius / np.maximum(delta, 1e-6), 0.0, 1.0)
        occluded += np.where(hit, weight, 0.0).astype(np.float32)

    out = 1.0 - occluded / float(len(kernel))
    return np.where(covered, np.clip(out, 0.0, 1.0), 1.0).astype(np.float32)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ssao.py -q`
Expected: PASS, 9 tests.

If `test_a_nearby_step_occludes_the_pixels_beside_it` fails, do **not** loosen its thresholds to make it pass — check the normal's sign first (`+z` faces the camera; the reference measures 0.9219 beside the step and 1.0000 far from it). A step that does not darken means the kernel is sampling away from the camera into free space, which is the one thing this twin exists to catch.

- [ ] **Step 5: Full gate, then commit**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
git add PyAitD/render/ssao.py tests/test_ssao.py
git commit -m "feat: the SSAO kernel and its pure-numpy twin"
```

---

### Task 2: the `occlusion` option, end to end, defaulting off

**Files:**
- Modify: `PyAitD/render/render_options.py` (mode tuple, field, payload, validation, cycle)
- Modify: `PyAitD/app/ui.py:28` (`REALISM_ROWS`), `:422` (`REALISM_CYCLES`), `realism_labels`
- Modify: `PyAitD/app/shell.py` (the CLI flag, `_MENU_RENDER_FIELDS`)
- Test: `tests/test_render_options.py`, `tests/test_ui_reducers.py`, `tests/test_ui_render.py`, `tests/test_main.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: nothing from Task 1 — this task is pure plumbing and can be reviewed on its own.
- Produces:
  - `render_options.OCCLUSION_MODES = ("off", "ssao")`
  - `RenderOptions.occlusion: str = "off"` — **appended last**, after `motion`
  - `render_options.cycle_occlusion(options) -> RenderOptions`
  - `--occlusion {off,ssao}` on the CLI
  - `REALISM_CYCLES[5] is cycle_occlusion`, `REALISM_ROWS == 6`

**Why the field lands `off` while `motion` landed `tick`:** both are the inert value of their tuple. `OCCLUSION_MODES`'s inert value is spelled `"off"` because there is no prior behaviour to name — unlike `shadows`, whose inert value is the real technique `"hard"`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_render_options.py` (marker `render`):

```python
def test_occlusion_defaults_off_and_cycles():
    from PyAitD.render.render_options import OCCLUSION_MODES, cycle_occlusion
    options = RenderOptions()
    assert options.occlusion == "off"
    assert OCCLUSION_MODES == ("off", "ssao")
    assert cycle_occlusion(options).occlusion == "ssao"
    assert cycle_occlusion(cycle_occlusion(options)).occlusion == "off"


def test_occlusion_is_last_so_positional_construction_still_works():
    # Every earlier field keeps its slot: this is what stops a new knob
    # from silently shifting an existing caller's arguments.
    options = RenderOptions(4, "smooth", "bilinear", None, "scene", 4, "enhanced", 2)
    assert options.occlusion == "off"


def test_an_unknown_occlusion_value_falls_back_alone():
    payload = RenderOptions().to_payload()
    payload["occlusion"] = "raytraced"
    options, errors = validate_render_options(payload)
    assert options.occlusion == "off"
    assert options.motion == "smooth"          # its neighbour is undisturbed
    assert any("occlusion" in e for e in errors)


def test_occlusion_round_trips_through_the_payload():
    options = replace(RenderOptions(), occlusion="ssao")
    assert options.to_payload()["occlusion"] == "ssao"
    restored, errors = validate_render_options(options.to_payload())
    assert restored.occlusion == "ssao" and not errors
```

In `tests/test_ui_reducers.py` (marker `shell`), extend the existing pins:

```python
def test_the_realism_page_gained_the_occlusion_row():
    from PyAitD.app.ui import REALISM_CYCLES, REALISM_ROWS
    from PyAitD.render.render_options import cycle_occlusion
    assert REALISM_ROWS == 6
    assert len(REALISM_CYCLES) == REALISM_ROWS
    assert REALISM_CYCLES[5] is cycle_occlusion
```

In `tests/test_main.py` (marker `shell`):

```python
def test_the_occlusion_flag_overrides_only_its_own_field(tmp_path):
    settings = Settings()
    args = parse_args(["--occlusion", "ssao"])
    updated, _ = apply_render_overrides(settings, args)
    assert updated.render.occlusion == "ssao"
    assert updated.render.motion == settings.render.motion
    assert updated.render.shadows == settings.render.shadows
```

Match the surrounding style of each file rather than these snippets' imports — every one of these files already imports what it needs at the top, and the existing tests beside yours show the exact fixture and helper names in use. `tests/test_main.py`'s override tests are at `:315-360`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_render_options.py tests/test_ui_reducers.py tests/test_main.py -q`
Expected: FAIL — `ImportError` on `OCCLUSION_MODES`/`cycle_occlusion`, and `AttributeError: 'RenderOptions' object has no attribute 'occlusion'`.

- [ ] **Step 3: Add the option**

In `PyAitD/render/render_options.py`, beside `MOTION_MODES` (`:44`):

```python
# Screen-space ambient occlusion on the actor layer. "off" runs today's
# renderer verbatim; "ssao" adds the G-buffer prepass and the two SSAO
# passes. Additive to the baked rest-pose AO in render/occlusion.py, which
# cannot see pose or neighbours.
OCCLUSION_MODES = ("off", "ssao")
```

Append the field to the dataclass, after `motion`:

```python
    occlusion: str = "off"
```

Add it to `to_payload()`'s dict (last key, matching field order), and to `validate_render_options` beside the `motion` block:

```python
    occlusion = payload.get("occlusion", defaults.occlusion)
    if occlusion not in OCCLUSION_MODES:
        errors.append(f"occlusion must be one of {OCCLUSION_MODES}, got {occlusion!r}")
        occlusion = defaults.occlusion
```

and as the last positional argument of the final `RenderOptions(...)` construction at `:139`.

Add the cycle beside `cycle_motion` (`:187`):

```python
def cycle_occlusion(options):
    return replace(options, occlusion=_cycle(OCCLUSION_MODES, options.occlusion))
```

In `PyAitD/app/ui.py`: bump `REALISM_ROWS` to `6` (`:28`), append `cycle_occlusion` to `REALISM_CYCLES` (`:422`), import it, and add the row's label to `realism_labels` (`:1289-1311`) in the same slot, following the existing rows' phrasing:

```python
        f"Occlusion: {'SSAO' if render.occlusion == 'ssao' else 'Off'}",
```

In `PyAitD/app/shell.py`: add the flag beside `--motion` (`:130`):

```python
    p.add_argument("--occlusion", choices=OCCLUSION_MODES,
                   help="screen-space ambient occlusion on actors (session only)")
```

extend `apply_render_overrides` with the matching `if args.occlusion is not None: payload["occlusion"] = args.occlusion`, and add `"occlusion"` to `_MENU_RENDER_FIELDS` (`:676`) — without it the menu's change never persists.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_render_options.py tests/test_ui_reducers.py tests/test_ui_render.py tests/test_main.py tests/test_config.py -q`
Expected: PASS.

`tests/test_ui_render.py::test_graphics_and_realism_page_rows_fit_the_screen_and_do_not_overlap` and `::test_graphics_and_realism_labels_match_the_cycles_one_per_row` should pass without edits — the first computes its bound dynamically, the second counts labels against cycles. If either fails, the label list and the cycles tuple have drifted out of alignment; fix the alignment, not the test.

- [ ] **Step 5: Full gate, then commit**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
git add PyAitD/render/render_options.py PyAitD/app/ui.py PyAitD/app/shell.py \
        tests/test_render_options.py tests/test_ui_reducers.py tests/test_main.py
git commit -m "feat: the occlusion option and its Realism row, defaulting off"
```

---

### Task 3: the half-resolution G-buffer prepass

**Files:**
- Modify: `PyAitD/render/glsl.py` (a new `GBUFFER_FSH`; `TESS_VSH` gains one varying)
- Modify: `PyAitD/render/render_gl.py` (the G-buffer resources, `_render_gbuffer`, `release()`)
- Test: `tests/test_render_gl.py`

**Interfaces:**
- Consumes: `RenderOptions.occlusion` (Task 2).
- Produces:
  - `GLBackend._gbuf_tex` — half-resolution RGBA16F, `rgb` = unit view-space normal, `a` = positive linear view depth (0.0 where nothing was drawn)
  - `GLBackend._gbuf_depth`, `GLBackend._gbuf_fbo`
  - `GLBackend._gbuf_prog` (`_TESS_VSH` + `_GBUFFER_FSH`), `GLBackend._gbuf_size` — the `(w, h)` tuple
  - `GLBackend._render_gbuffer(frame, instances, level)` — draws every actor once, no per-actor depth clears
  - `GLBackend._proj_xy()` -> `(fx, fy)`, the projection pair `ssao_reference` takes

**The point of this task:** `render_gl.py:719-721` clears depth per actor so painter's order works, which leaves no shared depth anywhere in the frame for SSAO to sample. This pass draws the same actors once into its own buffer with depth testing on and no clears between them, which is the only place a coherent depth of the whole actor layer exists.

- [ ] **Step 1: Write the failing tests**

In `tests/test_render_gl.py` (marker `render`):

```python
def test_the_gbuffer_is_half_resolution_and_starts_empty(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat",
                                              lighting="scene", msaa=0, occlusion="ssao"))
    try:
        assert backend._gbuf_size == (backend.size[0] // 2, backend.size[1] // 2)
        assert backend._gbuf_tex.size == backend._gbuf_size
        gbuf = np.frombuffer(backend._gbuf_tex.read(), np.float16).reshape(
            backend._gbuf_size[1], backend._gbuf_size[0], 4)
        # Alpha is linear depth and nothing has been drawn yet.
        assert (gbuf[..., 3] == 0.0).all()
    finally:
        backend.release()


def test_the_gbuffer_carries_depth_and_normals_where_an_actor_stands(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth",
                                              lighting="scene", msaa=0, occlusion="ssao"))
    try:
        backend.draw(_golden_frame())
        gbuf = np.frombuffer(backend._gbuf_tex.read(), np.float16).reshape(
            backend._gbuf_size[1], backend._gbuf_size[0], 4)
        depth = gbuf[..., 3].astype(np.float32)
        covered = depth > 0.0
        assert covered.any(), "the prepass drew nothing"
        assert not covered.all(), "the prepass covered the whole frame"
        assert depth[covered].min() > 0.0
        n = gbuf[..., :3].astype(np.float32)[covered]
        assert np.allclose(np.linalg.norm(n, axis=1), 1.0, atol=2e-2)
    finally:
        backend.release()


def test_the_prepass_does_not_run_with_occlusion_off(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth",
                                              lighting="scene", msaa=0, occlusion="off"))
    try:
        backend.draw(_golden_frame())
        gbuf = np.frombuffer(backend._gbuf_tex.read(), np.float16).reshape(
            backend._gbuf_size[1], backend._gbuf_size[0], 4)
        assert (gbuf[..., 3] == 0.0).all(), "the prepass ran with occlusion off"
    finally:
        backend.release()


def test_proj_xy_projects_a_known_point_where_the_main_pass_does(gl_ctx):
    """The twin and the shader share this pair, so it has to be the same
    projection the actors are drawn with -- not a second derivation."""
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat",
                                              lighting="scene", msaa=0, occlusion="ssao"))
    try:
        frame = _golden_frame()
        fx, fy = backend._proj_xy(frame)
        assert fx > 0.0 and fy > 0.0
        # A point on the camera axis projects to the centre of the screen
        # under any pinhole, whatever fx and fy are.
        p = np.array([0.0, 0.0, -500.0], dtype=np.float32)
        ndc_x = p[0] * fx / -p[2]
        ndc_y = p[1] * fy / -p[2]
        assert abs(ndc_x) < 1e-6 and abs(ndc_y) < 1e-6
        # Off-axis, doubling the distance halves the screen offset.
        q = np.array([50.0, 0.0, -500.0], dtype=np.float32)
        r = np.array([50.0, 0.0, -1000.0], dtype=np.float32)
        assert abs((q[0] * fx / -q[2]) / 2.0 - (r[0] * fx / -r[2])) < 1e-6
    finally:
        backend.release()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_render_gl.py -q -k "gbuffer or proj_xy"`
Expected: FAIL — `AttributeError: 'GLBackend' object has no attribute '_gbuf_size'`.

- [ ] **Step 3: Add the shader**

In `PyAitD/render/glsl.py`, after `STENCIL_FSH`:

```python
GBUFFER_FSH = """
#version 330
// The SSAO prepass's only output: view-space normal in rgb, positive
// linear view depth in alpha.
//
// Linear depth rather than the depth buffer's projective value, because
// ssao_reference has to reproduce this exactly and a projection inverse
// is the easiest place for a twin and a shader to disagree by a hair.
// The depth attachment is still there -- it is what makes the pass
// depth-test correctly against itself -- but nothing reads it.
//
// Alpha 0.0 marks a pixel no actor covered. ssao_reference and SSAO_FSH
// both treat that as "unoccluded" rather than as depth zero.
in vec3 v_normal;
in vec3 v_view;
out vec4 f_gbuf;
void main() {
    f_gbuf = vec4(normalize(v_normal), -v_view.z);
}
"""
```

`v_view` is already emitted by both `ACTOR_VSH` and `TESS_VSH` (`glsl.py:330-335`), so no varying has to be added and the tessellated path's attribute budget — already at 16 of 16 — is untouched. Confirm that before writing any code: `grep -n "v_view" PyAitD/render/glsl.py`. If `v_view` turns out to be camera-space *position*, `-v_view.z` is the positive distance this shader wants; if it is a direction, use the view matrix to build the position instead and say so in your report.

- [ ] **Step 4: Build the G-buffer resources**

In `GLBackend.__init__`, beside the other render targets and following the file's own "declare `None` first" convention (`render_gl.py:289-339`):

```python
        # Half resolution: SSAO is a low-frequency term and the blur in
        # _blur_ssao bounds the haloing that costs. The spec names this
        # trade explicitly as a limitation.
        self._gbuf_size = (max(1, self.size[0] // 2), max(1, self.size[1] // 2))
        self._gbuf_tex = ctx.texture(self._gbuf_size, 4, dtype="f2")
        self._gbuf_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self._gbuf_tex.repeat_x = self._gbuf_tex.repeat_y = False
        self._gbuf_depth = ctx.depth_renderbuffer(self._gbuf_size)
        self._gbuf_fbo = ctx.framebuffer(color_attachments=[self._gbuf_tex],
                                         depth_attachment=self._gbuf_depth)
        self._gbuf_prog = ctx.program(vertex_shader=_TESS_VSH, fragment_shader=_GBUFFER_FSH)
```

and the pass itself, placed beside `_render_shadow_map` (`render_gl.py:1085`):

```python
    def _render_gbuffer(self, frame, instances, level):
        """Every actor once, into a half-resolution normal+depth buffer.

        The per-actor depth clears the main loop needs for painter's order
        (render_gl.py's draw loop) leave no shared depth to sample, so this
        is the only place a coherent depth of the whole actor layer exists.
        Lines and points are excluded for the same reason they never cast:
        they never reach the instanced path at all."""
        self._gbuf_fbo.use()
        self._ctx.viewport = (0, 0, *self._gbuf_size)
        # Alpha 0 is "no actor here" -- the value both SSAO sides read as
        # unoccluded, so an empty G-buffer contributes nothing.
        self._gbuf_fbo.clear(0.0, 0.0, 0.0, 0.0)
        self._ctx.enable(moderngl.DEPTH_TEST)
        for actor, instance in instances:
            if instance is None:
                continue
            self._set_actor_uniforms(self._gbuf_prog, frame, actor)
            self._render_instanced(self._gbuf_prog, instance, level)
        self._ctx.disable(moderngl.DEPTH_TEST)
```

`_set_actor_uniforms` and `_render_instanced` are placeholders for whatever the file's existing per-actor uniform and instanced-draw helpers are called — read `_draw_actor_tessellated` (`render_gl.py:844-867`) and reuse its exact calls rather than inventing new ones. The prepass must set the same `mvp`, `rot` and `view` uniforms the main pass sets, or its depth will not correspond to the frame.

Call it from `_draw_frame` after the instance buffers are built (`render_gl.py:652-658`) and before the shadow map, guarded:

```python
        ssao_on = scene_lit and self._options.occlusion == "ssao"
        if ssao_on:
            self._render_gbuffer(frame, instances, level)
```

then restore the viewport the main pass expects — the existing passes each set `self._ctx.viewport` before drawing, so follow that pattern rather than saving and restoring.

Add `_proj_xy(frame)`, returning the same `(fx, fy)` the frame's projection uses. Derive it from the projection matrix `_draw_frame` already builds at `:629-644` (`fx = proj[0][0]`, `fy = proj[1][1]` for a standard perspective) rather than recomputing it from the camera — a second derivation is a second thing to drift.

- [ ] **Step 5: Release and count the new resources**

Add `_gbuf_tex`, `_gbuf_depth`, `_gbuf_fbo`, `_gbuf_prog` to `release()`'s tuple (`render_gl.py:538-560`) and to the leak test's attribute tuple (`tests/test_render_gl.py:858-871`), bumping `leak_checked` from 44 by exactly the number you added. Run the leak test and let it tell you the number rather than guessing:

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_render_gl.py -q -k leak
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_render_gl.py -q`
Expected: PASS, including `test_classic_realism_matches_the_pre_materials_golden` — the prepass writes to its own FBO and touches no pixel of the frame.

- [ ] **Step 7: Full gate, then commit**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
git add PyAitD/render/glsl.py PyAitD/render/render_gl.py tests/test_render_gl.py
git commit -m "feat: the half-resolution SSAO depth and normal prepass"
```

---

### Task 4: the SSAO and blur passes, the fill-share attenuation, and the default flip

**Files:**
- Modify: `PyAitD/render/glsl.py` (`SSAO_FSH`, `SSAO_BLUR_FSH`, `ACTOR_FSH`)
- Modify: `PyAitD/render/render_gl.py` (the SSAO resources, `_render_ssao`, `_blur_ssao`, the uniform wiring, `release()`)
- Modify: `PyAitD/render/render_options.py` (the default flip)
- Test: `tests/test_render_gl.py`, `tests/test_render_options.py`

**Interfaces:**
- Consumes: `ssao.hemisphere_kernel`, `ssao.noise_rotations`, `ssao.ssao_reference`, `SSAO_RADIUS`, `SSAO_BIAS` (Task 1); `_gbuf_tex`, `_gbuf_size`, `_proj_xy` (Task 3).
- Produces:
  - `GLBackend._ssao_tex`, `_ssao_fbo`, `_ssao_blur_tex`, `_ssao_blur_fbo` — half-resolution R8 ping-pong
  - `GLBackend._ssao_noise_tex` — the 4x4 RG16F rotation tile
  - `GLBackend._ssao_prog`, `_ssao_vao`, `_ssao_blur_prog`, `_ssao_blur_vao`
  - `GLBackend._render_ssao(frame)`, `GLBackend._blur_ssao()`
  - `_ACTOR_FSH` uniforms `ssao_tex` (unit 7) and `occlusion_on` (int)
  - `RenderOptions.occlusion` default becomes `"ssao"`

- [ ] **Step 1: Write the failing tests**

In `tests/test_render_gl.py`:

```python
def test_the_ssao_pass_matches_the_numpy_twin(gl_ctx):
    """The `soften` pattern: seed the backend's own G-buffer, run the one
    pass, read it back, compare against the twin at byte tolerance."""
    from PyAitD.render.ssao import (SSAO_BIAS, SSAO_RADIUS, hemisphere_kernel,
                                    noise_rotations, ssao_reference)
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat",
                                              lighting="scene", msaa=0, occlusion="ssao"))
    try:
        w, h = backend._gbuf_size
        rng = np.random.default_rng(23)
        depth = rng.uniform(300.0, 700.0, (h, w)).astype(np.float32)
        depth[: h // 4, :] = 0.0                     # a band the prepass never covered
        n = rng.normal(size=(h, w, 3)).astype(np.float32)
        n /= np.linalg.norm(n, axis=2, keepdims=True)
        gbuf = np.concatenate([n, depth[..., None]], axis=2).astype(np.float16)
        backend._gbuf_tex.write(np.ascontiguousarray(gbuf).tobytes())
        proj_xy = (2.0, 2.0)
        backend._render_ssao_with(proj_xy)           # the seam the test drives
        out = np.frombuffer(backend._ssao_tex.read(), np.uint8).reshape(h, w) / 255.0
        expected = ssao_reference(gbuf[..., 3].astype(np.float32),
                                  gbuf[..., :3].astype(np.float32),
                                  hemisphere_kernel(), noise_rotations(), proj_xy,
                                  SSAO_RADIUS, SSAO_BIAS)
        assert np.abs(out - expected).max() <= 4.0 / 255
    finally:
        backend.release()


def test_an_empty_gbuffer_leaves_the_ssao_texture_fully_open(gl_ctx):
    """The neutral identity: nothing drawn means nothing occluded, so the
    attenuation the actor shader applies is exactly 1.0."""
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat",
                                              lighting="scene", msaa=0, occlusion="ssao"))
    try:
        w, h = backend._gbuf_size
        backend._gbuf_tex.write(np.zeros((h, w, 4), np.float16).tobytes())
        backend._render_ssao_with((2.0, 2.0))
        out = np.frombuffer(backend._ssao_tex.read(), np.uint8).reshape(h, w)
        assert (out == 255).all()
    finally:
        backend.release()


def test_two_actors_side_by_side_darken_the_gap_between_them(gl_ctx):
    """The whole point of screen-space AO over the baked kind: the baked
    pass cannot see a neighbour, this one can."""
    backend = GLBackend(gl_ctx, RenderOptions(scale=2, shading="smooth", lighting="scene",
                                              msaa=0, occlusion="ssao", realism="enhanced"))
    try:
        one = _golden_frame()
        two = _two_actor_frame()          # the same actor plus a second beside it
        backend.draw(one)
        alone = backend.read_rgb().astype(np.int32)
        backend.draw(two)
        together = backend.read_rgb().astype(np.int32)
    finally:
        backend.release()
    gap = _gap_column_slice(alone, together)   # the pixels between the two bodies
    assert together[gap].mean() < alone[gap].mean() - 1.0


def test_ssao_attenuates_the_fill_share_and_leaves_key_and_specular_alone(gl_ctx):
    """Decision 7, made testable: with the key light switched off entirely
    the frame is pure fill, so SSAO must move it; with the fill switched
    off the frame is pure key and specular, so SSAO must not."""
    fill_only = _frame_with_light(key=(0.0, 0.0, 0.0), fill=(0.5, 0.5, 0.5))
    key_only = _frame_with_light(key=(0.8, 0.8, 0.8), fill=(0.0, 0.0, 0.0))
    for frame, should_move in ((fill_only, True), (key_only, False)):
        off = _render_with(gl_ctx, frame, occlusion="off")
        on = _render_with(gl_ctx, frame, occlusion="ssao")
        moved = int(np.abs(off.astype(np.int32) - on.astype(np.int32)).sum()) > 0
        assert moved is should_move, ("fill" if should_move else "key", moved)


def test_occlusion_off_renders_byte_identically(gl_ctx):
    off = _render_with(gl_ctx, _golden_frame(), occlusion="off")
    # The same options a pre-K build would have run.
    assert np.array_equal(off, _render_baseline(gl_ctx, _golden_frame()))
```

`_two_actor_frame`, `_gap_column_slice`, `_frame_with_light`, `_render_with` and `_render_baseline` are helpers you write beside the existing `_golden_frame`/`_painted_frame` fixtures in that file — follow their construction style exactly, and keep `_render_baseline` free of any new option so it means what its name says.

`_render_ssao_with(proj_xy)` is a deliberate seam: `_render_ssao(frame)` derives `proj_xy` from the frame and calls it, and the test drives the inner one with a known projection. Do not have the test reach into the frame to fake a projection — that is the seam existing for a reason.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_render_gl.py -q -k ssao`
Expected: FAIL — `AttributeError: 'GLBackend' object has no attribute '_render_ssao_with'`.

- [ ] **Step 3: Add the SSAO shaders**

In `PyAitD/render/glsl.py`:

```python
SSAO_FSH = """
#version 330
// Screen-space ambient occlusion over the half-resolution G-buffer.
//
// Every line here has a counterpart in PyAitD/render/ssao.py's
// ssao_reference, which tests/test_render_gl.py pins this against at
// 4/255 -- the same arrangement `soften` and SHADOW_BLUR_FSH have. When
// you change one, change both, or the test will tell you.
//
// Depth is positive linear view distance in the G-buffer's alpha, and 0.0
// means no actor covered that pixel. Output is a *multiplier*: 1.0 is
// unoccluded, which is what makes an empty G-buffer contribute nothing.
uniform sampler2D gbuf_tex;
uniform sampler2D noise_tex;
uniform vec2 target_size;      // the half-resolution G-buffer's size
uniform vec2 proj_xy;          // the projection's (fx, fy), shared with the twin
uniform float radius;
uniform float bias;
uniform int kernel_count;
uniform vec3 kernel[64];
out vec4 f_color;

vec3 view_position(vec2 uv, float depth) {
    vec2 ndc = uv * 2.0 - 1.0;
    return vec3(ndc.x * depth / proj_xy.x, ndc.y * depth / proj_xy.y, -depth);
}

void main() {
    vec2 uv = gl_FragCoord.xy / target_size;
    vec4 g = texture(gbuf_tex, uv);
    float depth = g.a;
    if (depth <= 0.0) { f_color = vec4(1.0); return; }
    vec3 n = normalize(g.rgb);
    vec3 p = view_position(uv, depth);

    vec2 r = texture(noise_tex, gl_FragCoord.xy / 4.0).rg;
    vec3 rand = vec3(r, 0.0);
    vec3 tangent = rand - n * dot(rand, n);
    float tlen = length(tangent);
    tangent = tlen > 1e-6 ? tangent / tlen : vec3(0.0, 1.0, 0.0);
    vec3 bitangent = cross(n, tangent);

    float occluded = 0.0;
    for (int i = 0; i < kernel_count; i++) {
        vec3 k = kernel[i];
        vec3 sample_pos = p + (tangent * k.x + bitangent * k.y + n * k.z) * radius;
        if (sample_pos.z >= -1e-6) continue;         // behind the camera: no screen position
        vec2 s_ndc = vec2(sample_pos.x * proj_xy.x, sample_pos.y * proj_xy.y) / (-sample_pos.z);
        vec2 s_uv = clamp(s_ndc * 0.5 + 0.5, vec2(0.0), vec2(1.0));
        float s_depth = texture(gbuf_tex, s_uv).a;
        float sample_dist = -sample_pos.z;
        if (s_depth > 0.0 && s_depth < sample_dist - bias) {
            occluded += clamp(radius / max(abs(depth - s_depth), 1e-6), 0.0, 1.0);
        }
    }
    f_color = vec4(clamp(1.0 - occluded / float(kernel_count), 0.0, 1.0));
}
"""

SSAO_BLUR_FSH = """
#version 330
// One bilateral-ish pass over the occlusion texture: a 4x4 box the width
// of the noise tile, which is exactly what removes the tile's pattern,
// rejecting taps whose depth is far from the centre's so the blur does
// not drag occlusion across a silhouette.
uniform sampler2D ssao_tex;
uniform sampler2D gbuf_tex;
uniform vec2 target_size;
uniform float depth_threshold;
out vec4 f_color;
void main() {
    vec2 texel = 1.0 / target_size;
    vec2 uv = gl_FragCoord.xy / target_size;
    float centre_depth = texture(gbuf_tex, uv).a;
    if (centre_depth <= 0.0) { f_color = vec4(1.0); return; }
    float sum = 0.0;
    float total = 0.0;
    for (int y = -2; y < 2; y++) {
        for (int x = -2; x < 2; x++) {
            vec2 q = uv + vec2(float(x), float(y)) * texel;
            float d = texture(gbuf_tex, q).a;
            // A tap on the far side of a silhouette is a different
            // surface; averaging it in is what makes a thin limb halo.
            if (d > 0.0 && abs(d - centre_depth) < depth_threshold) {
                sum += texture(ssao_tex, q).r;
                total += 1.0;
            }
        }
    }
    f_color = vec4(total > 0.0 ? sum / total : 1.0);
}
"""
```

The `kernel[64]` array is sized to the GL 3.3 guaranteed uniform-vector floor with room to spare; `kernel_count` is what actually runs, so `SSAO_KERNEL_SIZE` can change without touching the shader.

- [ ] **Step 4: Wire the passes**

In `GLBackend.__init__`, following the fullscreen idiom (`render_gl.py:374-383`) and reusing the existing `self._shadow_quad` buffer rather than allocating another:

```python
        self._ssao_tex = ctx.texture(self._gbuf_size, 1)
        self._ssao_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self._ssao_tex.repeat_x = self._ssao_tex.repeat_y = False
        self._ssao_fbo = ctx.framebuffer(color_attachments=[self._ssao_tex])
        self._ssao_blur_tex = ctx.texture(self._gbuf_size, 1)
        self._ssao_blur_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self._ssao_blur_tex.repeat_x = self._ssao_blur_tex.repeat_y = False
        self._ssao_blur_fbo = ctx.framebuffer(color_attachments=[self._ssao_blur_tex])
        rot = noise_rotations()
        self._ssao_noise_tex = ctx.texture((rot.shape[1], rot.shape[0]), 2, dtype="f2")
        self._ssao_noise_tex.write(np.ascontiguousarray(rot.astype(np.float16)).tobytes())
        self._ssao_noise_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self._ssao_noise_tex.repeat_x = self._ssao_noise_tex.repeat_y = True
        self._ssao_prog = ctx.program(vertex_shader=_STENCIL_VSH, fragment_shader=SSAO_FSH)
        self._ssao_vao = ctx.vertex_array(self._ssao_prog, [(self._shadow_quad, "2f", "in_pos")])
        self._ssao_blur_prog = ctx.program(vertex_shader=_STENCIL_VSH, fragment_shader=SSAO_BLUR_FSH)
        self._ssao_blur_vao = ctx.vertex_array(self._ssao_blur_prog,
                                               [(self._shadow_quad, "2f", "in_pos")])
        kernel = hemisphere_kernel()
        _set_uniform(self._ssao_prog, "kernel", tuple(map(tuple, kernel)))
        _set_uniform(self._ssao_prog, "kernel_count", len(kernel))
        _set_uniform(self._ssao_prog, "radius", SSAO_RADIUS)
        _set_uniform(self._ssao_prog, "bias", SSAO_BIAS)
```

The noise tile repeats — that is the one texture in this backend that should, and it is why `gl_FragCoord.xy / 4.0` tiles correctly.

The passes, beside `_soften_shadows` (`render_gl.py:1064`):

```python
    def _render_ssao(self, frame):
        self._render_ssao_with(self._proj_xy(frame))

    def _render_ssao_with(self, proj_xy):
        self._ssao_fbo.use()
        self._ctx.viewport = (0, 0, *self._gbuf_size)
        self._ctx.disable(moderngl.DEPTH_TEST)
        self._gbuf_tex.use(location=7)
        self._ssao_noise_tex.use(location=8)
        _set_uniform(self._ssao_prog, "gbuf_tex", 7)
        _set_uniform(self._ssao_prog, "noise_tex", 8)
        _set_uniform(self._ssao_prog, "target_size", tuple(float(v) for v in self._gbuf_size))
        _set_uniform(self._ssao_prog, "proj_xy", (float(proj_xy[0]), float(proj_xy[1])))
        self._ssao_vao.render(moderngl.TRIANGLES)

    def _blur_ssao(self):
        """One pass, into the ping-pong target, then swap so _ssao_tex is
        always the texture the actor shader samples."""
        self._ssao_blur_fbo.use()
        self._ctx.viewport = (0, 0, *self._gbuf_size)
        self._ssao_tex.use(location=7)
        self._gbuf_tex.use(location=8)
        _set_uniform(self._ssao_blur_prog, "ssao_tex", 7)
        _set_uniform(self._ssao_blur_prog, "gbuf_tex", 8)
        _set_uniform(self._ssao_blur_prog, "target_size", tuple(float(v) for v in self._gbuf_size))
        _set_uniform(self._ssao_blur_prog, "depth_threshold", SSAO_RADIUS)
        self._ssao_blur_vao.render(moderngl.TRIANGLES)
        self._ssao_tex, self._ssao_blur_tex = self._ssao_blur_tex, self._ssao_tex
        self._ssao_fbo, self._ssao_blur_fbo = self._ssao_blur_fbo, self._ssao_fbo
```

**The swap is a trap for `release()`**: after an odd number of frames the attribute names point at each other's objects. That is harmless for releasing (both are released either way) but it means the leak test's `isinstance(..., InvalidObject)` check still holds. Say so in a comment so nobody "fixes" it.

Call both from `_draw_frame` right after `_render_gbuffer`, then bind the result for the actor programs:

```python
        if ssao_on:
            self._render_gbuffer(frame, instances, level)
            self._render_ssao(frame)
            self._blur_ssao()
        self._ssao_tex.use(location=7)
        for prog in (self._actor_prog, self._tess_prog, self._screen_prog):
            _set_uniform(prog, "ssao_tex", 7)
            _set_uniform(prog, "occlusion_on", 1 if ssao_on else 0)
```

Bind and set the uniform **unconditionally**, exactly as the shadow map is bound at `render_gl.py:673` whatever `shadows` says: a sampler left unbound reads undefined data if the branch is ever mispredicted by a driver, and the `occlusion_on` gate is what makes the value irrelevant rather than the binding.

- [ ] **Step 5: Attenuate the fill share**

In `ACTOR_FSH`, add the uniforms beside `has_body_texture` (`glsl.py:81-82`):

```glsl
uniform sampler2D ssao_tex; uniform int occlusion_on;
```

and change exactly one line — `glsl.py:251`:

```glsl
    // Screen-space occlusion attenuates the *fill* share and nothing else.
    // The key share is already gated by `vis` (the shadow map), and F's
    // rule holds: a shadowed limb falls to the room's fill, never to
    // black -- so the fill is the one share an occlusion term may touch.
    //
    // Not folded into `occl` below, however much the name invites it:
    // `occl` multiplies the whole of `base`, key share included, as does
    // `hemi`. Either would darken the key light a second time, which the
    // shadow map already owns.
    //
    // ssao is exactly 1.0 when occlusion_on is 0, and multiplying by
    // exactly 1.0 is exact in IEEE 754 -- that, not a mix(), is what
    // makes the off path byte-identical.
    float ssao = 1.0;
    if (occlusion_on != 0) {
        ssao = texture(ssao_tex, gl_FragCoord.xy / target_size).r;
    }
    vec3 base = albedo * (fill_tint * ssao + key_tint * wrapped * wrapped * vis);
```

- [ ] **Step 6: Release, count, and flip the default**

Add `_ssao_tex`, `_ssao_fbo`, `_ssao_blur_tex`, `_ssao_blur_fbo`, `_ssao_noise_tex`, `_ssao_prog`, `_ssao_vao`, `_ssao_blur_prog`, `_ssao_blur_vao` to `release()` and to the leak test's tuple, bumping `leak_checked` again. Release the VAOs before `_shadow_quad`, following the ordering comment at `render_gl.py:545-549`.

Then flip the default in `render_options.py`:

```python
    occlusion: str = "ssao"
```

and update `tests/test_render_options.py::test_occlusion_defaults_off_and_cycles` to expect `"ssao"` — rename it accordingly. Add `occlusion="off"` to the identity net at `tests/test_render_gl.py:972-980` (`test_classic_realism_matches_the_pre_materials_golden`), which already carries the comment "names every roadmap-2 field the identity holds at".

- [ ] **Step 7: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_render_gl.py tests/test_render_options.py tests/test_ssao.py -q`
Expected: PASS.

If the twin comparison misses by more than `4/255`, the likely causes in order: `f2` quantisation of the seeded depth (the test writes half-floats and the twin reads float32 — round the twin's input through `np.float16` first, do not widen the tolerance); a different `proj_xy` on the two sides; the tangent fallback branch disagreeing. Do not raise the tolerance to make it pass — the twin exists to catch exactly the drift a loose tolerance would hide.

- [ ] **Step 8: Full gate, then commit**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
git add PyAitD/render/glsl.py PyAitD/render/render_gl.py PyAitD/render/render_options.py \
        tests/test_render_gl.py tests/test_render_options.py
git commit -m "feat: the SSAO and blur passes, the fill-share attenuation, default ssao"
```

---

### Task 5: `shadows` gains `room` — the receiver pass over the floor and hard_col tops

**Files:**
- Modify: `PyAitD/render/render_options.py` (`SHADOW_MODES`)
- Modify: `PyAitD/render/scene.py` (`FrameDescription.receivers`, the builder)
- Modify: `PyAitD/render/glsl.py` (`RECEIVER_VSH`, `RECEIVER_FSH`)
- Modify: `PyAitD/render/render_gl.py` (`_draw_receivers`, its resources, `release()`)
- Test: `tests/test_scene.py`, `tests/test_render_gl.py`, `tests/test_render_options.py`

**Interfaces:**
- Consumes: the existing `_shadow_map` and its `light_vp` matrix.
- Produces:
  - `render_options.SHADOW_MODES = ("hard", "soft", "room")`
  - `scene.ReceiverQuad` — a frozen dataclass of `corners: np.ndarray` `(4, 3)` float32, world space
  - `FrameDescription.receivers: tuple[ReceiverQuad, ...] = ()` — **appended last**
  - `scene.room_receivers(room, plane_y) -> tuple[ReceiverQuad, ...]`
  - `GLBackend._draw_receivers(frame)`

**The gate this task carries.** `hard_cols` are collision proxies, not the painted furniture. A shadow on a box 30 units off its table looks worse than no shadow at all. So: vertical faces are excluded from the start, and **the default does not move in this task**. `shadows` stays `"soft"`; `"room"` is a menu choice. Task 6's proof document carries the fixture-review row, and a human decides whether the default moves — not this plan, and not the implementer.

- [ ] **Step 1: Write the failing tests**

In `tests/test_scene.py` (marker `render`):

```python
def test_room_receivers_are_the_floor_plus_every_hard_col_top():
    room = _room_with_boxes([
        Zone(x1=0, x2=100, y1=-50, y2=0, z1=0, z2=100, type=0, parameter=0),
        Zone(x1=200, x2=260, y1=-80, y2=0, z1=0, z2=60, type=0, parameter=0),
    ])
    receivers = room_receivers(room, plane_y=0.0)
    # One floor quad plus one top face per box -- and nothing else: the
    # vertical faces are excluded by design, not by accident.
    assert len(receivers) == 3
    tops = [r for r in receivers[1:]]
    for r in tops:
        assert r.corners.shape == (4, 3)
        ys = r.corners[:, 1]
        assert np.allclose(ys, ys[0]), "a top face is horizontal by definition"
    # World y grows downward, so a box top is *above* the floor plane.
    assert tops[0].corners[0][1] < 0.0


def test_a_room_with_no_boxes_still_has_its_floor():
    receivers = room_receivers(_room_with_boxes([]), plane_y=0.0)
    assert len(receivers) == 1


def test_build_frame_carries_receivers_only_under_shadows_room():
    frame = build_frame(_game(), _floor(), _resolver(), shadows="room")
    assert frame.receivers
    assert build_frame(_game(), _floor(), _resolver(), shadows="soft").receivers == ()
```

In `tests/test_render_gl.py`:

```python
def test_a_caster_over_a_box_top_darkens_it_through_the_shadow_map(gl_ctx):
    frame = _frame_with_box_under_the_hero()
    lit = _render_with(gl_ctx, frame, shadows="soft")
    received = _render_with(gl_ctx, frame, shadows="room")
    top = _box_top_pixels(frame)
    assert received[top].mean() < lit[top].mean() - 2.0


def test_the_room_receiver_pass_leaves_soft_output_untouched(gl_ctx):
    """The whole receiver feature is gated behind the third mode: `soft`
    must be byte-identical to what it was before this task."""
    frame = _frame_with_box_under_the_hero()
    assert np.array_equal(_render_with(gl_ctx, frame, shadows="soft"),
                          _render_baseline_soft(gl_ctx, frame))


def test_a_mask_erases_the_receiver_pass(gl_ctx):
    """Receivers are drawn through the same gathered composite the ground
    shadow uses, so the room's masks erase them exactly as they erase it."""
    frame = _frame_with_box_under_the_hero_and_a_mask_over_it()
    received = _render_with(gl_ctx, frame, shadows="room")
    top = _box_top_pixels(frame)
    assert np.array_equal(received[top], _render_with(gl_ctx, frame, shadows="soft")[top])


def test_room_with_no_hard_col_in_view_matches_soft(gl_ctx):
    """The neutral identity for this mode."""
    frame = _frame_with_no_boxes()
    assert np.array_equal(_render_with(gl_ctx, frame, shadows="room"),
                          _render_with(gl_ctx, frame, shadows="soft"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_scene.py tests/test_render_gl.py -q -k "receiver or room"`
Expected: FAIL — `ImportError: cannot import name 'room_receivers'`.

- [ ] **Step 3: Build the receiver geometry, scene-side**

In `PyAitD/render/scene.py`:

```python
@dataclass(frozen=True)
class ReceiverQuad:
    """One horizontal surface the room's shadows may land on, in the same
    room-space coordinates every other geometry in a FrameDescription uses
    -- the room's world offset is already folded into the camera, exactly
    as in layout_geometry and build_frame.

    Horizontal only. hard_cols approximate the painted furniture rather
    than matching it, and a shadow on a vertical face 30 units off the
    wall it stands for reads as a bug; a top face that is a little too
    high still reads as the top of that crate."""
    corners: np.ndarray          # (4, 3) float32, counter-clockwise


def room_receivers(room, plane_y):
    """The room's floor plane plus the top face of every hard_col.

    Vertical faces are excluded by design -- see ReceiverQuad. World y
    grows downward, so a box's top face is at its y1 (the smaller value),
    not its y2."""
    quads = [ReceiverQuad(_floor_quad(room, plane_y))]
    for box in room.hard_cols:
        top = np.array([
            [box.x1, box.y1, box.z1], [box.x2, box.y1, box.z1],
            [box.x2, box.y1, box.z2], [box.x1, box.y1, box.z2],
        ], dtype=np.float32)
        quads.append(ReceiverQuad(top))
    return tuple(quads)
```

Write `_floor_quad(room, plane_y)` to span the room's own extent at `plane_y` — derive the extent from the room's `hard_cols` bounding box plus a margin, or from whatever the existing ground-shadow pass already uses for its plane, and reuse that rather than inventing a second notion of "the floor". Read `_gather_shadows` (`render_gl.py:1023-1062`) and `_composite_shadow` (`:1115-1161`) first: if the ground shadow already has a plane quad, this is the same quad and must not disagree with it.

Verify the y convention before you commit to it: `glsl.py:280-281` says "World y grows downward: the feet are at plane_y and everything above them has a smaller y." If `_box_corners` (`texture_export.py:182-186`) puts `y2` first and calls that the top, one of the two is wrong about which end is up — settle it against a real room's boxes and record what you found in your report.

Add the field to `FrameDescription`, last:

```python
    receivers: tuple[ReceiverQuad, ...] = ()
```

and populate it in `build_frame` only when the caller asks for `shadows="room"`, so no other mode pays to build it.

- [ ] **Step 4: Add the receiver pass**

In `glsl.py`, a minimal pair — the receivers are world-space quads, so they need their own vertex shader rather than the fullscreen `STENCIL_VSH`:

```python
RECEIVER_VSH = """
#version 330
uniform mat4 mvp; uniform mat4 light_vp; uniform float normal_offset;
in vec3 in_pos;
out vec4 v_shadow;
void main() {
    // Horizontal faces only, so the receiver normal is always straight
    // up and the push along it is a push in y -- the same normal_offset
    // the actor receivers use, for the same acne.
    v_shadow = light_vp * vec4(in_pos + vec3(0.0, -normal_offset, 0.0), 1.0);
    gl_Position = mvp * vec4(in_pos, 1.0);
}
"""

RECEIVER_FSH = """
#version 330
// How much of the light the shadow map says this surface loses. Written
// into the same gathered coverage texture the ground shadow uses, so the
// composite and the room's masks treat both the same way.
uniform sampler2DShadow shadow_map;
uniform float depth_bias;
in vec4 v_shadow;
out vec4 f_color;
void main() {
    vec3 c = v_shadow.xyz / v_shadow.w;
    float vis = textureProj(shadow_map, vec4(c.xy, c.z - depth_bias, 1.0));
    f_color = vec4(1.0 - vis, 0.0, 0.0, 1.0);
}
"""
```

In `render_gl.py`, add `_receiver_prog`, a dynamic `_receiver_buf` (six vertices per quad, written per frame) and `_receiver_vao`, then:

```python
    def _draw_receivers(self, frame):
        """The room's floor and box tops, darkened by the shadow map,
        drawn into the gathered shadow texture after the ground shadow and
        before any body -- so the hero's shadow drapes over the crates the
        hard_cols stand in for, and the masks erase it like everything
        else on that layer."""
        if not frame.receivers:
            return
        verts = np.concatenate([_quad_triangles(r.corners) for r in frame.receivers])
        self._receiver_buf.orphan(verts.nbytes)
        self._receiver_buf.write(verts.tobytes())
        self._receiver_vao.render(moderngl.TRIANGLES, vertices=len(verts))
```

Call it from `_draw_frame` immediately after `_gather_shadows` (`render_gl.py:680`) and before the hard-shadow pre-loop, under `self._options.shadows == "room"`. `_quad_triangles` turns a `(4,3)` quad into `(6,3)`; write it beside the other small geometry helpers in that file.

- [ ] **Step 5: Extend the mode tuple, release, count**

In `render_options.py`:

```python
# "room" implies everything "soft" does and adds the receiver pass over
# the room's floor and hard_col tops. The default stays "soft": hard_cols
# are collision proxies, and whether a shadow on them reads as furniture
# or as a bug is a question for a human at a window, not for a test.
SHADOW_MODES = ("hard", "soft", "room")
```

Everything that reads `shadows == "soft"` to decide whether to run the soft path must now read `shadows in ("soft", "room")`. Grep for it — `render_gl.py` and `scene.py` both branch on it — and fix every site. Missing one is how `room` silently renders as `hard`.

Add `_receiver_prog`, `_receiver_buf`, `_receiver_vao` to `release()` and the leak test, bumping `leak_checked`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_scene.py tests/test_render_gl.py tests/test_render_options.py tests/test_config.py -q`
Expected: PASS. `tests/test_config.py` matters here: `shadows` now round-trips a third value, and an older settings file carrying `"soft"` must still load.

- [ ] **Step 7: Full gate, then commit**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
git add PyAitD/render/render_options.py PyAitD/render/scene.py PyAitD/render/glsl.py \
        PyAitD/render/render_gl.py tests/test_scene.py tests/test_render_gl.py \
        tests/test_render_options.py
git commit -m "feat: shadows=room, the floor and hard_col-top receiver pass"
```

---

### Task 6: the proof document and the docs

**Files:**
- Modify: `tools/prove_graphics.py`, `tests/test_prove_graphics.py`
- Create: `docs/light-transport-proof.md`
- Modify: `CONTEXT.md`, `AGENTS.md`, `README.md`, `Makefile`

**Interfaces:**
- Consumes: everything above.
- Produces: `--occlusion` on `prove_graphics`, the `-nossao` and `-noroomshadow` twins, and the proof document.

- [ ] **Step 1: Add the twins to the proof tool**

`render_fixture`'s signature is pinned exactly by `tests/test_prove_graphics.py:132-138`. Append `occlusion=None` after `painted`, and extend that test's expected parameter list to match — the pin exists so a silent reordering cannot happen, so update it deliberately rather than deleting it.

In `output_paths`, add two twin rows beside the existing six (`tools/prove_graphics.py:183-200`), following their exact shape:

```python
        rows.append((*base, "nossao", _path(out_dir, name, mode, realism, "nossao")))
        rows.append((*base, "noroomshadow", _path(out_dir, name, mode, realism, "noroomshadow")))
```

with `nossao` forcing `occlusion="off"` against a default of `ssao`, and `noroomshadow` forcing `shadows="soft"` against `shadows="room"`. Match the surrounding rows' tuple arity exactly — they carry `(name, mode, realism, level, shadows, integration, blend, label, path)` and a mismatched arity fails at unpack, not at assert.

Then update `tests/test_prove_graphics.py::test_output_paths_cover_every_combination_plus_the_twins`: the `6 * len(FIXTURES)` term becomes `8 * len(FIXTURES)`, and the `expected` set gains one block per new label. That test compares sets with `==`, so a new row with a duplicate label collapses silently into an existing one and the count assertion is what catches it — do not weaken the count to `>=`.

Add `--occlusion` to `_parse_args` with `default=RenderOptions().occlusion`, matching the existing flags' pattern, and add a difference smoke test in the style of `test_the_default_composites_and_nocomposite_does_not`:

```python
def test_the_nossao_twin_differs_from_the_default(tmp_path, gl_ctx, data_dir):
    default = render_fixture(data_dir, "attic", 1, "smooth", gl_ctx)
    nossao = render_fixture(data_dir, "attic", 1, "smooth", gl_ctx, occlusion="off")
    assert not np.array_equal(default, nossao)
```

- [ ] **Step 2: Write the proof document**

Create `docs/light-transport-proof.md`, following `docs/motion-interpolation-proof.md` and `docs/actor-textures-proof.md` exactly — those two are the house style and this one is read beside them.

**Every number and every block of output in it must come from a command you actually ran, pasted as it came back.** If a gate cannot run in this environment, write that it could not, and why. Do not reconstruct output that "would have" printed; a proof document's only value is that its claims can be trusted.

Sections, in this order:

1. **What changed** — the two features in a paragraph each, naming the knob that turns each off.
2. **Automated gates** — the full gate, `tests/test_ssao.py`, and the SSAO-twin and receiver tests by name, with their real output.
3. **The twin** — the measured maximum difference between `_render_ssao_with` and `ssao_reference` over the seeded G-buffer, as the test reports it, and the tolerance it is held to.
4. **Attenuation** — evidence that the fill share moves and the key share does not: the two numbers `test_ssao_attenuates_the_fill_share_and_leaves_key_and_specular_alone` produces.
5. **Pixel evidence** — the `-nossao` and `-noroomshadow` twin pairs, with the differing-pixel counts on both fixtures, produced by `make proof-graphics`.
6. **Frame time** — one measured line, mean of at least 16 runs of the attic fixture at scale 4, msaa 4, smoothing 2, with `occlusion` off versus on, and the ratio. The spec's budget is 1.5x with **all four** sub-projects on; report K's own contribution against the branch's base, and say plainly that the budget is a roadmap-level gate, not this plan's.
7. **The fixture-review gate** — a table of the receiver classes (floor only / floor + box tops) with a `pending` row for the human decision on whether `shadows` should default to `room`. **This stays `pending`.** Task 5 did not move the default and this task does not either.
8. **Manual attestation** — the usual `pending` table: SSAO reads as contact shading rather than a dark outline; thin limbs do not halo; the receiver shadow lands on furniture rather than beside it; a moving actor's occlusion does not crawl or flicker.
9. **Known limitations** — half-resolution SSAO and its haloing; `hard_cols` as proxies; the excluded vertical faces; the `occl`/`hemi` reasoning from this plan's deviation note, so the next reader does not "simplify" the fill-share attenuation into `occl`.

- [ ] **Step 3: Update the three docs and the Makefile**

- `README.md`: the CLI flag count goes from "eleven CLI flags" to "twelve" (`README.md:98`), with `--occlusion` described beside `--motion`; the Realism page description gains its row; `shadows` gains its third value wherever the README lists it. There is no test on that count — grep for the number and fix the prose.
- `AGENTS.md`: a convention block for the new passes, in the voice of the existing ones — the G-buffer's linear-depth-in-alpha contract and why it is not the depth buffer; the ssao/`occl`/`hemi` rule; that `render/ssao.py` is pure and `render/occlusion.py` is the different, baked feature; that `shadows="room"` implies `soft`.
- `CONTEXT.md`: the milestone row and the `render/` file table gain `ssao.py`.
- `Makefile`: `proof-graphics`'s help text gains the two new twins and the `occlusion=` variable, and the recipe forwards `$(if $(occlusion),--occlusion "$(occlusion)")` — the `motion=` line at `Makefile:85-86` is the pattern.

- [ ] **Step 4: Full gate, then commit**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
git add tools/prove_graphics.py tests/test_prove_graphics.py docs/light-transport-proof.md \
        CONTEXT.md AGENTS.md README.md Makefile
git commit -m "docs: light-transport proof, SSAO and room-shadow twins, docs"
```

---

## Plan self-review (record kept)

**Spec coverage.** K1's five bullets: depth prepass (Task 3), SSAO pass with rotation noise and a blur (Task 4), the receiver term attenuating the fill share (Task 4), `render/ssao.py` with the kernel builder and `ssao_reference` (Task 1), the `occlusion` knob landing off and flipping last (Tasks 2 and 4). K2's three bullets: `SHADOW_MODES` gaining `room` (Task 5), the receiver pass over floor and box tops drawn after the gathered ground shadow and before any body (Task 5), the named risk and the fixture-review gate (Task 5's preamble and Task 6's section 7). The resources paragraph: every task that adds a GL object adds it to `release()` and the leak test in the same step. The spec's K testing bullets all appear as named tests. Proof tooling and the four-document convention: Task 6.

**Two things I checked and changed while writing.** First, the spec's "attenuates the fill/hemisphere share" does not survive contact with the shader: `hemi` and `occl` both multiply the key share, so attenuating either would double-count what the shadow map already owns. The plan attenuates `fill_tint` alone and says why, in the plan and in a code comment. Second, I had the prepass writing depth to the depth attachment and reconstructing view position from it; that puts a projection inverse in both the twin and the shader, which is the least reliable place for them to agree. The G-buffer now carries linear view depth in alpha and both sides share a `proj_xy` pair.

**Type consistency.** `occlusion` is the field name everywhere (`RenderOptions.occlusion`, `--occlusion`, `cycle_occlusion`, `OCCLUSION_MODES`, the payload key, `_MENU_RENDER_FIELDS`). The twin is `ssao_reference` in both the module and every test that names it. `_gbuf_tex`/`_gbuf_size`/`_gbuf_fbo`/`_gbuf_depth`/`_gbuf_prog` are the G-buffer names throughout; `_ssao_tex`/`_ssao_fbo`/`_ssao_blur_tex`/`_ssao_blur_fbo`/`_ssao_noise_tex`/`_ssao_prog`/`_ssao_vao`/`_ssao_blur_prog`/`_ssao_blur_vao` the SSAO ones; `_receiver_prog`/`_receiver_buf`/`_receiver_vao` K2's. `ReceiverQuad.corners` is `(4,3)` in the scene module and in every test.

## Known limitations this plan ships with

- **SSAO is half resolution.** Thin limbs can halo; the bilateral blur bounds it and the proof shows it. This is the spec's own named trade, not a defect to fix here.
- **`hard_cols` are proxies.** Vertical faces are excluded from the start and the default does not move without a human's eye on the fixtures. If the review fails, `room` stays a menu choice — which is a complete, shippable outcome, not a failure of the plan.
- **The kernel and radius are tuned by construction, not by measurement.** `SSAO_RADIUS = 14.0` is reasoned from the actors' scale, and the fixture review is where it earns or loses that value.
- **The prepass costs a full extra pass over every actor.** It runs only under `occlusion="ssao"` and `lighting="scene"`; `off` is the escape hatch and is on the menu.
