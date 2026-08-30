# Plate Integration (Roadmap G) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the actors from looking pasted onto the room — read the plate's tone and grain off the background image, resolve the bodies into their own RGBA layer, and composite them back with the plate's black floor, white ceiling, dither amplitude and apparent softness.

**Architecture:** A new pure-numpy `render/plate.py` reads a `PlateProfile` (black, white, grain) off whatever background a camera resolves to, and models how much the background filter softened that plate at the current scale (`softness`). Under `integration="on"` the GL backend splits its one scratch target into two: background plus the gathered ground shadow resolve into `_plate_tex`, then the same target is cleared to transparent and the bodies resolve into `_actor_tex` with coverage in alpha. One full-target composite pass softens or pixelates the actor layer to the plate's grid, tone-matches its darks and brights toward the plate's floor and ceiling, adds grain at the plate's own amplitude, and writes `plate · (1 − a) + c · a` into `self.texture`.

**Tech Stack:** Python 3.12, numpy, ModernGL 5.12 (GL 3.3 core GLSL), pygame-ce, pytest.

**Spec:** `docs/superpowers/specs/2026-08-29-actor-realism-roadmap-design.md` (sections "G. Plate integration", "Options, UI and tooling", "Task ordering — G", "Testing — G", "Limitations").

## Global Constraints

- `# SPDX-License-Identifier: GPL-2.0-only` is the first line of every Python file.
- `make test` (headless: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`) must be green after every task. Baseline at the start of this plan: **1433 passed, 2 skipped, 1 xfailed, 26 warnings**. The 26 warnings are pre-existing; introduce none. No lint, formatter or typecheck exists in this repo; never mass-reformat.
- `classic + smoothing 0 + shadows hard + integration off` reproduces `tests/golden/scene_lit_classic.npy` byte for byte (`tests/test_render_gl.py::test_classic_realism_matches_the_pre_materials_golden`). `lighting="fixed"` renders byte-identically to today at every combination of the new option. **Integration must also hold a second identity: `integration="on"` with `NEUTRAL_PLATE` at `msaa = 0` reproduces the same golden**, by construction rather than by luck.
- `integration` applies under `lighting="scene"` only. Under `lighting="fixed"` the current single-target path runs untouched whatever `integration` says.
- `skel.skin()`, `draw_list`, picking, masks, the mouse contract, the software backend, the background filters themselves and the override directory layout are untouched.
- Layering (`tests/test_layering.py`): `render/` imports only `engine`; only `render_gl`, `render_soft`, `render`, `asset_resolver` may import pygame/moderngl. `plate.py` and `lighting.py` stay pure numpy; `glsl.py` stays strings only (`test_glsl_is_strings_only` allows a module docstring plus uppercase string assignments and nothing else).
- G adds exactly **six** GL resources. The leak-count assertion in `tests/test_render_gl.py::test_init_failure_releases_every_already_allocated_gl_object` goes from **38** to **44**, and every new resource is listed in that test's attribute tuple. A task that lands a different number has added something the plan did not ask for.
- Every uniform added to a shader must be seeded on **every program built from that shader**, through `_set_uniform` where the linker may drop it.
- Run tests with the venv interpreter: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest ...`.
- Never commit game data, keys, or generated `overrides*/` output.
- Commit messages end with the repo's trailer block when authored with Claude:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01S9WYQ21wFZzQZ2xjzF3KtX
  ```

## Deviations from the spec, decided here

The spec's G section was written before F and H shipped. Five corrections, each load-bearing:

1. **`softness` must fall back with `_draw_background`, not ahead of it.** The spec maps `xbr → 0.15 · cell`, but `render_gl._draw_background` only actually runs xBR when `(src_h, src_w) == (H, W)`; any other source size silently falls back to `GL_LINEAR`. A softness model that claimed 0.15 for a 640×400 override would be describing a filter that did not run. `softness` therefore returns the bilinear sigma for `xbr` at any non-classic source size, and `plate.CLASSIC_PLATE_SIZE = (320, 200)` is where that rule lives.

2. **`integration="on"` with `shadows="hard"` needs the hard casts moved ahead of the bodies.** The spec describes the plate layer as carrying "the gathered shadow", which only exists under `soft`. Under `hard`, `_composite_shadow` runs *inside* the per-actor loop with `blend_func=(DST_COLOR, ZERO)` — on a transparent actor layer that multiplies `(0,0,0,0)` by a factor and produces nothing, while darkening every body already drawn. So under `integrate`, task 3 runs every actor's hard cast and composite in its own loop over the plate layer, before the body loop starts. Same per-actor operations, same order, different target. This also happens to fix the ordering caveat documented in `_composite_shadow`'s docstring for the `on` path — say so, do not silently rely on it.

3. **Task 3's composite is premultiplied, with no unpremultiply at all.** The spec's step 2 unpremultiplies before tone matching. Introducing `(rgb / a) * a` in task 3, where the plumbing identity is the whole deliverable, would put a float round-trip between the actor's colour and the output for every fractional alpha. Task 3 writes exactly `plate * (1.0 - a.a) + a.rgb`. Task 5 introduces the division only inside the `a.a > 0.0` branch that needs it.

4. **`FrameDescription.plate` is read through a `getattr` shim.** Several tests in `tests/test_scene.py` pass stub resolvers that implement only the methods they use and have no `plate` at all. `scene._plate` returns `NEUTRAL_PLATE` for a resolver without the method, and keeps the `killed_sorcerer` TypeError fallback the existing `_light` shim uses.

5. **`GAIN` is `sqrt(12)`, derived rather than tuned.** `hash(...) - 0.5` is uniform on [−0.5, 0.5], whose RMS is `1/sqrt(12)`. Scaling by `grain * sqrt(12)` makes the composited actor's luma residual match the RMS `estimate_plate` measured off the plate — which is exactly what "grain at the plate's own amplitude" means. `TOE` and `SHOULDER` land at 1.0 (meet the plate's floor and ceiling exactly at luma 0 and luma 1; the quartic already confines the effect — at luma 0.5 only 6% of the offset applies). Task 6 may lower any of the three after the fixture pass, and records the change in the proof doc if it does.

---

## File structure

| File | Responsibility | Task |
|---|---|---|
| `PyAitD/render/plate.py` | **new.** `PlateProfile`, `NEUTRAL_PLATE`, `estimate_plate`, `softness`. Pure numpy. | 1 |
| `PyAitD/render/asset_resolver.py` | `AssetResolver.plate`, memoised per (floor, camera, killed_sorcerer) like `light` | 1 |
| `PyAitD/render/scene.py` | `FrameDescription.plate`, the `_plate` shim, `build_frame` wiring | 1 |
| `PyAitD/render/render_options.py` | `INTEGRATION_MODES`, the field, validation, payload, `cycle_integration` | 2, 6 |
| `PyAitD/app/ui.py` | `GRAPHICS_ROWS = 9`, `GRAPHICS_CYCLES`, the Integration label | 2 |
| `PyAitD/app/shell.py` | `--integration` CLI flag, `_MENU_RENDER_FIELDS` | 2 |
| `PyAitD/render/glsl.py` | `COMPOSITE_FSH` | 3, 4, 5 |
| `PyAitD/render/render_gl.py` | the plate/actor layers, the two resolves, `_composite`, the hard-cast pre-loop | 3, 4, 5 |
| `tools/prove_graphics.py` | `--integration` and the `-nocomposite` twin | 6 |
| `docs/plate-integration-proof.md` | **new.** the proof record | 6 |
| `tests/test_plate.py` | **new.** `estimate_plate` and `softness` | 1 |

New tests also land in `tests/test_asset_resolver.py`, `tests/test_scene.py`, `tests/test_render_options.py`, `tests/test_ui_reducers.py`, `tests/test_ui_render.py`, `tests/test_main.py`, `tests/test_config.py`, `tests/test_render_gl.py` and `tests/test_prove_graphics.py`.

---

### Task 1: The plate profile

**Files:**
- Create: `PyAitD/render/plate.py`
- Modify: `PyAitD/render/asset_resolver.py` (add `self._plates = {}` in `__init__`; add `plate()` beside `light()`)
- Modify: `PyAitD/render/scene.py` (import, `FrameDescription.plate`, `_plate`, `build_frame`)
- Test: `tests/test_plate.py` (create), `tests/test_asset_resolver.py`, `tests/test_scene.py`

**Interfaces:**
- Consumes: `PyAitD.render.lighting.LUMA` — the Rec. 709 weight vector, `np.array([0.2126, 0.7152, 0.0722])`.
- Produces:
  - `PlateProfile(black: tuple, white: tuple, grain: float)` — frozen dataclass, `black`/`white` are 3-tuples of 0..1 floats.
  - `NEUTRAL_PLATE = PlateProfile((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), 0.0)`
  - `estimate_plate(pixels) -> PlateProfile`
  - `softness(background_filter: str, src_size, target_size) -> (sigma_px: float, cell_px: float, pixelate: bool)` — `src_size` and `target_size` are `(width, height)`.
  - `CLASSIC_PLATE_SIZE = (320, 200)`
  - `AssetResolver.plate(floor, cam_idx, *, killed_sorcerer=False) -> PlateProfile`
  - `FrameDescription.plate: PlateProfile = NEUTRAL_PLATE` — the sixth-and-last field, after `light`.

- [ ] **Step 1: Write the failing tests for `plate.py`**

Create `tests/test_plate.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
import numpy as np
import pytest

from PyAitD.render.plate import (
    CLASSIC_PLATE_SIZE, NEUTRAL_PLATE, PlateProfile, estimate_plate, softness,
)

pytestmark = pytest.mark.render


def test_black_and_white_are_the_percentile_means_by_construction():
    # 100x100: the darkest and brightest 1% are 100 pixels each, and this
    # plate is built so those two sets are exactly the two painted bands.
    plate = np.full((100, 100, 3), 128, np.uint8)
    plate[0] = (10, 20, 30)      # 100 darkest pixels
    plate[99] = (200, 210, 220)  # 100 brightest
    profile = estimate_plate(plate)
    assert profile.black == pytest.approx((10 / 255, 20 / 255, 30 / 255))
    assert profile.white == pytest.approx((200 / 255, 210 / 255, 220 / 255))


def test_a_uniform_plate_has_zero_grain():
    assert estimate_plate(np.full((64, 64, 3), 77, np.uint8)).grain == 0.0


def test_a_checkerboard_carries_its_dither_amplitude():
    # A 1px checkerboard's 3x3 mean is 5/9 of white at a white pixel and
    # 4/9 at a black one, so every interior residual is 4/9 of white's luma.
    rows, cols = np.indices((64, 64))
    plate = np.zeros((64, 64, 3), np.uint8)
    plate[(rows + cols) % 2 == 0] = 255
    grain = estimate_plate(plate).grain
    assert 0.40 < grain < 0.46


def test_an_all_black_plate_is_total():
    profile = estimate_plate(np.zeros((32, 32, 3), np.uint8))
    assert profile.black == pytest.approx((0.0, 0.0, 0.0))
    assert profile.white == pytest.approx((0.0, 0.0, 0.0))
    assert profile.grain == 0.0


def test_an_all_white_plate_is_total():
    profile = estimate_plate(np.full((32, 32, 3), 255, np.uint8))
    assert profile.black == pytest.approx((1.0, 1.0, 1.0))
    assert profile.white == pytest.approx((1.0, 1.0, 1.0))
    assert profile.grain == 0.0


def test_the_neutral_plate_is_the_identity_profile():
    assert NEUTRAL_PLATE == PlateProfile((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), 0.0)


@pytest.mark.parametrize("filter_name,sigma,pixelate", [
    ("bilinear", 0.35 * 4, False),
    ("xbr", 0.15 * 4, False),
    ("nearest", 0.0, True),
])
def test_softness_at_cell_four(filter_name, sigma, pixelate):
    got = softness(filter_name, CLASSIC_PLATE_SIZE, (1280, 800))
    assert got[0] == pytest.approx(sigma)
    assert got[1] == pytest.approx(4.0)
    assert got[2] is pixelate


@pytest.mark.parametrize("filter_name", ["bilinear", "xbr", "nearest"])
@pytest.mark.parametrize("target,cell", [((320, 200), 1.0), ((160, 100), 0.5)])
def test_nothing_softens_or_pixelates_at_or_below_cell_one(filter_name, target, cell):
    # An override plate at or above the target resolution: nothing to match.
    assert softness(filter_name, CLASSIC_PLATE_SIZE, target) == (0.0, cell, False)


def test_xbr_falls_back_to_bilinear_softness_off_the_classic_size():
    # _draw_background only runs xBR at exactly 320x200; anywhere else it
    # falls back to GL_LINEAR, and the softness model falls back with it.
    assert softness("xbr", (640, 400), (1280, 800))[0] == pytest.approx(0.35 * 2)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_plate.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'PyAitD.render.plate'`.

- [ ] **Step 3: Write `PyAitD/render/plate.py`**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""What the room's own picture says about tone, dither and sharpness.

The actors are rendered clean: full contrast down to black and up to white,
a crisp edge at the internal resolution, no film grain. The plate they stand
on is none of those things -- it is a 320x200 image with a lifted black, a
capped white, an ordered dither, and, once the background filter has blown
it up to the target size, an edge that spans several pixels. Reading those
four quantities off the plate is what lets the composite put the actor
inside the room rather than on top of it.

Pure numpy: no pygame, no GL, no engine imports."""
from dataclasses import dataclass

import numpy as np

from PyAitD.render.lighting import LUMA

# The size at which render_gl._draw_background actually runs xBR. Any other
# source falls back to GL_LINEAR there, and `softness` falls back with it:
# a model that claimed the xBR sigma for a 640x400 override would be
# describing a filter that did not run.
CLASSIC_PLATE_SIZE = (320, 200)

# Sigma per plate cell, by filter. Bilinear spreads a source texel's
# influence across its whole cell; xBR reconstructs edges and leaves them
# far crisper; nearest leaves none at all and is handled by `pixelate`.
BILINEAR_SIGMA = 0.35
XBR_SIGMA = 0.15

# The share of pixels at each end of the luma order that defines the room's
# floor and ceiling. Deliberately tighter than lighting.BRIGHT_FRACTION /
# DARK_FRACTION: those two want the *lit* and *shadowed* parts of a room, a
# broad statement about where the light is. These two want the extremes the
# tone curve has to land on, which is a much smaller set of pixels.
TAIL_FRACTION = 0.01


@dataclass(frozen=True)
class PlateProfile:
    black: tuple    # 0..1 linear RGB: the room's floor
    white: tuple    # 0..1 linear RGB: the room's ceiling
    grain: float    # 0..1: RMS luma residual against the plate's own 3x3 mean


# What a frame built without a resolver carries, and what makes the whole
# composite an identity: a black of 0 adds nothing at the toe, a white of 1
# subtracts nothing at the shoulder, and a grain of 0 adds no noise. Every
# term vanishes by construction, not by rounding.
NEUTRAL_PLATE = PlateProfile((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), 0.0)


def estimate_plate(pixels):
    """A PlateProfile for a camera, read off its background image.

    Deterministic and total: an all-black plate yields a black white and
    zero grain, and a uniform plate yields zero grain."""
    image = np.asarray(pixels)
    rgb = image.reshape(-1, 3).astype(np.float64) / 255.0
    luma = rgb @ LUMA

    # argpartition, not argsort: only the two quantile boundaries matter.
    # Same selection lighting.estimate_light uses, and the same reason --
    # a full sort over a 1080p override costs ~200 ms against a 20 ms tick.
    count = luma.size
    tail = max(1, int(count * TAIL_FRACTION))
    order = np.argpartition(luma, (tail - 1, count - tail))
    black = tuple(rgb[order[:tail]].mean(axis=0))
    white = tuple(rgb[order[count - tail:]].mean(axis=0))
    return PlateProfile(black, white, _grain(image))


def _grain(image):
    """RMS of the plate's luma residual against its own 3x3 box mean: the
    amplitude of its dither, at the plate's own resolution.

    Edge-padded rather than cropped, so the residual is defined for every
    pixel and a 1x1 plate is still total (its own mean, residual zero)."""
    luma = (image.astype(np.float64) / 255.0) @ LUMA
    height, width = luma.shape
    padded = np.pad(luma, 1, mode="edge")
    mean = sum(padded[dy:dy + height, dx:dx + width]
               for dy in range(3) for dx in range(3)) / 9.0
    return float(np.clip(np.sqrt(np.mean((luma - mean) ** 2)), 0.0, 1.0))


def softness(background_filter, src_size, target_size):
    """(sigma_px, cell_px, pixelate) for a plate of `src_size` shown at
    `target_size` through `background_filter`. Both sizes are (width, height).

    `cell` is how many target pixels one plate pixel became. At or below 1 --
    an override plate at or above the target resolution -- there is nothing
    to match: the plate is as sharp as the actors are, so no softening and
    no pixelation. `nearest` leaves hard blocks, so the actor is fetched per
    cell rather than blurred."""
    src_w = float(src_size[0])
    target_w = float(target_size[0])
    cell = target_w / src_w if src_w > 0.0 else 1.0
    if cell <= 1.0:
        return 0.0, cell, False
    if background_filter == "nearest":
        return 0.0, cell, True
    if background_filter == "xbr" and tuple(src_size) == CLASSIC_PLATE_SIZE:
        return XBR_SIGMA * cell, cell, False
    return BILINEAR_SIGMA * cell, cell, False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_plate.py -q`
Expected: PASS (13 tests).

- [ ] **Step 5: Write the failing resolver test**

Append to `tests/test_asset_resolver.py`, directly after `test_light_follows_an_override_background`:

```python
def test_plate_is_estimated_once_per_camera():
    calls = []

    class CountingFloor:
        number = 3
        palette = np.zeros((256, 3), dtype=np.uint8)

        def camera_image(self, idx):
            calls.append(idx)
            plate = np.zeros((200, 320, 3), np.uint8)
            plate[:40] = 255
            return plate

    floor = CountingFloor()
    resolver = AssetResolver(SimpleNamespace(body=lambda n: n), None)
    first = resolver.plate(floor, 0)
    second = resolver.plate(floor, 0)
    assert first is second
    assert calls == [0]                     # one decode, one estimate
    assert first.white[0] > first.black[0]  # estimated, not the neutral default


def test_plate_follows_an_override_background(tmp_path):
    from PyAitD.render.asset_resolver import override_background_path
    path = override_background_path(tmp_path, 3, 0)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"")                   # content comes from the stub loader below
    bright = np.full((200, 320, 3), 200, np.uint8)
    resolver = AssetResolver(None, tmp_path, load_png=lambda p: bright)
    # _floor()'s own plate is flat black; the override's is flat 200.
    assert resolver.plate(_floor(), 0).white[0] == pytest.approx(200 / 255)
```

- [ ] **Step 6: Run it to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_asset_resolver.py -q -k plate`
Expected: FAIL with `AttributeError: 'AssetResolver' object has no attribute 'plate'`.

- [ ] **Step 7: Add `AssetResolver.plate`**

In `PyAitD/render/asset_resolver.py`, extend the import to
`from PyAitD.render.plate import estimate_plate`, add `self._plates = {}` beside `self._lights = {}` in `__init__`, and add this method directly after `light()`:

```python
    def plate(self, floor, cam_idx, *, killed_sorcerer=False):
        """The PlateProfile for a camera, estimated from whatever background
        that camera actually resolves to -- read through the same
        `background()` call `light()` uses, so an override plate is profiled
        from the override.

        Memoised per (floor number, camera, killed_sorcerer) exactly like
        `light`, and for exactly the same reason: a camera's tone and grain
        are properties of a static image."""
        key = (floor.number, cam_idx, killed_sorcerer)
        if key not in self._plates:
            self._plates[key] = estimate_plate(
                self.background(floor, cam_idx, killed_sorcerer=killed_sorcerer).pixels
            )
        return self._plates[key]
```

- [ ] **Step 8: Run it to verify it passes**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_asset_resolver.py -q`
Expected: PASS.

- [ ] **Step 9: Write the failing scene test**

Append to `tests/test_scene.py`:

```python
def test_frame_description_plate_defaults_to_neutral():
    from PyAitD.render.plate import NEUTRAL_PLATE
    from PyAitD.render.scene import FrameDescription
    import numpy as np
    from PyAitD.render.asset_resolver import ImageAsset
    frame = FrameDescription(
        None, ImageAsset(np.zeros((200, 320, 3), np.uint8), False),
        np.zeros((256, 3), np.uint8), (), (),
    )
    assert frame.plate is NEUTRAL_PLATE


def test_build_frame_carries_the_resolvers_plate(data_dir, profile):
    game = init_game(data_dir, profile)
    floor = game.load_floor(game.current_floor)
    resolver = AssetResolver(game.assets)
    frame, _ = build_frame(game, floor, resolver)
    cam_idx = floor.rooms[game.current_room].camera_indices[game.num_camera]
    assert frame.plate is resolver.plate(floor, cam_idx)


def test_build_frame_falls_back_to_the_neutral_plate_for_a_resolver_without_one(
        data_dir, profile):
    # Stub resolvers in this file implement only what they use. A missing
    # `plate` must not be an AttributeError mid-frame.
    from PyAitD.render.plate import NEUTRAL_PLATE
    game = init_game(data_dir, profile)
    floor = game.load_floor(game.current_floor)
    real = AssetResolver(game.assets)

    class NoPlate:
        def __getattr__(self, name):
            if name == "plate":
                raise AttributeError(name)
            return getattr(real, name)

    frame, _ = build_frame(game, floor, NoPlate())
    assert frame.plate is NEUTRAL_PLATE
```

Match the fixture names and imports the surrounding tests in `tests/test_scene.py` already use (`data_dir`, `profile`, `init_game`, `AssetResolver`, `build_frame`); if the file imports them differently, follow the file, not this snippet.

- [ ] **Step 10: Run it to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_scene.py -q -k plate`
Expected: FAIL — `FrameDescription` has no attribute `plate`.

- [ ] **Step 11: Wire the plate into `scene.py`**

Add to the imports:

```python
from PyAitD.render.plate import NEUTRAL_PLATE, PlateProfile
```

Add the field to `FrameDescription`, last, after `light`:

```python
    light: SceneLight = LEGACY_LIGHT
    plate: PlateProfile = NEUTRAL_PLATE
```

Add the shim beside `_light`:

```python
def _plate(resolver, floor, cam_idx, killed):
    """The camera's PlateProfile, or NEUTRAL_PLATE when the resolver has no
    `plate` at all: several stub resolvers in the test suite implement only
    the methods they use, and a neutral profile composites as an identity,
    so a frame built from one renders exactly as it does today. The
    TypeError branch is the same `killed_sorcerer` fallback `_light` uses."""
    getter = getattr(resolver, "plate", None)
    if getter is None:
        return NEUTRAL_PLATE
    try:
        return getter(floor, cam_idx, killed_sorcerer=killed)
    except TypeError as exc:
        if "killed_sorcerer" not in str(exc):
            raise
        return getter(floor, cam_idx)
```

And extend the `FrameDescription(...)` construction at the end of `build_frame` with one more positional argument after `_light(...)`:

```python
        _light(resolver, floor, cam_idx, killed),
        _plate(resolver, floor, cam_idx, killed),
    )
```

- [ ] **Step 12: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_plate.py tests/test_scene.py tests/test_asset_resolver.py tests/test_layering.py -q`
Expected: PASS.

- [ ] **Step 13: Run the full suite**

Run: `make test`
Expected: 1433 + the new tests passed, 2 skipped, 1 xfailed, 26 warnings.

- [ ] **Step 14: Commit**

```bash
git add PyAitD/render/plate.py PyAitD/render/asset_resolver.py PyAitD/render/scene.py tests/test_plate.py tests/test_asset_resolver.py tests/test_scene.py
git commit -m "feat: read the plate's tone, grain and softness off the background"
```

---

### Task 2: The `integration` option

**Files:**
- Modify: `PyAitD/render/render_options.py`
- Modify: `PyAitD/app/ui.py`
- Modify: `PyAitD/app/shell.py`
- Test: `tests/test_render_options.py`, `tests/test_ui_reducers.py`, `tests/test_ui_render.py`, `tests/test_main.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: nothing from task 1.
- Produces:
  - `INTEGRATION_MODES = ("off", "on")` in `render_options`
  - `RenderOptions.integration: str = "off"` — the **last** field, after `shadows`
  - `cycle_integration(options) -> RenderOptions`
  - `--integration {off,on}` on the CLI
  - `GRAPHICS_ROWS = 9` in `app/ui.py`

This task mirrors F's task 2 (`shadows`) exactly. Read the `shadows` wiring first — `git log --oneline -- PyAitD/render/render_options.py` finds the commit — and copy its shape rather than inventing a new one.

- [ ] **Step 1: Write the failing option tests**

Append to `tests/test_render_options.py`:

```python
def test_integration_defaults_to_off_and_cycles():
    from PyAitD.render.render_options import INTEGRATION_MODES, cycle_integration
    options = RenderOptions()
    assert INTEGRATION_MODES == ("off", "on")
    assert options.integration == "off"
    assert cycle_integration(options).integration == "on"
    assert cycle_integration(RenderOptions(integration="on")).integration == "off"


def test_an_unknown_integration_clamps_to_the_default_with_an_error():
    options, error = validate_render_options({**RenderOptions().to_payload(),
                                              "integration": "sometimes"})
    assert options.integration == RenderOptions().integration
    assert "integration must be one of off, on" in error


def test_integration_round_trips_through_the_payload():
    payload = RenderOptions(integration="on").to_payload()
    assert payload["integration"] == "on"
    assert validate_render_options(payload)[0].integration == "on"
```

Match the import style already used at the top of `tests/test_render_options.py` (`validate_render_options`, `RenderOptions`).

Update the two payload literals at `tests/test_render_options.py:42` and `:47` to carry `"integration": "off"`, and `tests/test_config.py:204`'s expected render payload likewise.

Append to `tests/test_main.py`, beside `test_shadows_flag_overrides_only_its_own_field`:

```python
def test_integration_flag_overrides_only_its_own_field():
    base = default_settings()
    assert apply_render_overrides(base, parse_args([])) == base
    only = apply_render_overrides(base, parse_args(["--integration", "on"]))
    assert only == replace(base, render=replace(base.render, integration="on"))
    with pytest.raises(SystemExit):
        parse_args(["--integration", "sometimes"])   # argparse choices reject it
```

Match the helper names `test_shadows_flag_overrides_only_its_own_field` uses in that file.

Update `tests/test_ui_reducers.py:120` from `GRAPHICS_ROWS == 8` to `GRAPHICS_ROWS == 9`, and append:

```python
def test_the_integration_row_cycles_from_the_graphics_page():
    from PyAitD.app.ui import GRAPHICS_CYCLES
    from PyAitD.render.render_options import cycle_integration
    assert GRAPHICS_CYCLES[8] is cycle_integration
```

Update `tests/test_ui_render.py:802-808` so the label assertions cover the ninth row:

```python
    assert len(labels) == GRAPHICS_ROWS == len(GRAPHICS_CYCLES)
    # every other row's label is total over its option; the Smoothing row
    ...
    assert labels[0] == "Scale: 4x" and labels[4] == "Shadows: Soft"
    assert labels[6] == "Realism: Enhanced" and labels[7] == "Smoothing: Medium"
    assert labels[8] == "Integration: Off"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_options.py tests/test_ui_reducers.py tests/test_ui_render.py tests/test_main.py tests/test_config.py -q`
Expected: FAIL — `ImportError: cannot import name 'INTEGRATION_MODES'`, plus the row-count and label assertions.

- [ ] **Step 3: Add the option**

In `PyAitD/render/render_options.py`, after `SHADOW_MODES`:

```python
# off: today's single-target path -- bodies drawn straight over the plate,
# at the internal resolution, with the plate's tone and dither ignored.
# on: bodies resolved into their own RGBA layer and composited back through
# the plate's softness, tone curve and grain. Under lighting="scene" only;
# "fixed" runs the single-target path either way.
INTEGRATION_MODES = ("off", "on")
```

Add the field last on the dataclass, the payload entry last in `to_payload`, this block last in `validate_render_options` (immediately before the `options = RenderOptions(...)` line):

```python
    integration = payload.get("integration")
    if integration not in INTEGRATION_MODES:
        errors.append(f"integration must be one of {', '.join(INTEGRATION_MODES)}")
        integration = defaults.integration
```

extend the constructor call with `, integration`, and add at the end of the file:

```python
def cycle_integration(options):
    return replace(options, integration=_cycle(INTEGRATION_MODES, options.integration))
```

In `PyAitD/app/ui.py`: add `cycle_integration` to the `render_options` import, set `GRAPHICS_ROWS = 9`, append `cycle_integration` to `GRAPHICS_CYCLES`, and append to `graphics_labels`:

```python
        f"Integration: {render.integration.title()}",
```

`SystemMenuLayout.GRAPHICS_PAGE_ROWS` is already derived from `graphics_row_count()`, so it grows on its own: ten rows at the 18 px pitch end at y=192, inside the 200 px page, and 18 >= 13 keeps `effective_rects`' 12x12 target contract. Change nothing there.

In `PyAitD/app/shell.py`: add `INTEGRATION_MODES` to the `render_options` import, add the argument beside `--shadows`:

```python
    p.add_argument(
        "--integration", choices=INTEGRATION_MODES, default=None,
        help="composite actors through the plate's tone, grain and softness")
```

add the override beside the `--shadows` one:

```python
    if args.integration is not None:
        payload["integration"] = args.integration
```

and append `"integration"` to `_MENU_RENDER_FIELDS`.

- [ ] **Step 4: Run them to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_options.py tests/test_ui_reducers.py tests/test_ui_render.py tests/test_ui_mouse.py tests/test_main.py tests/test_config.py tests/test_shell_journeys.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `make test`
Expected: green. `integration` defaults to `off`, so nothing renders differently yet.

- [ ] **Step 6: Commit**

```bash
git add PyAitD/render/render_options.py PyAitD/app/ui.py PyAitD/app/shell.py tests/
git commit -m "feat: add the integration option, defaulting off"
```

---

### Task 3: The actor layer and the identity composite

**Files:**
- Modify: `PyAitD/render/glsl.py` (add `COMPOSITE_FSH`)
- Modify: `PyAitD/render/render_gl.py` (`__init__`, `release`, `_draw_frame`, new `_cast_hard_shadow`, `_resolve`, `_composite`)
- Test: `tests/test_render_gl.py`

**Interfaces:**
- Consumes: `RenderOptions.integration` (task 2); `FrameDescription.plate` is present but unread until task 5.
- Produces:
  - `glsl.COMPOSITE_FSH`
  - `GLBackend._plate_tex`, `._plate_fbo`, `._actor_tex`, `._actor_fbo`, `._composite_prog`, `._composite_vao`
  - texture units **5** (`plate_tex`) and **6** (`actor_tex`); 0-4 are taken (bg, mask, shadow, material, shadow map).

**The identity this task exists to deliver:** at `msaa = 0` the actor layer's alpha is exactly 0 or exactly 1, so `plate * (1 - a) + rgb` is a multiply by exactly 1.0 or 0.0 — byte-exact against the direct draw. Under MSAA the two paths agree mathematically (the resolve is a linear average and so is "over"), but `_plate_tex` and `_actor_tex` quantise to 8 bits in between, so a ±1 difference on an antialiased edge is expected and is not a defect.

- [ ] **Step 1: Write the failing identity tests**

Append to `tests/test_render_gl.py`:

```python
def _integration_options(**kw):
    base = dict(scale=1, shading="smooth", lighting="scene", msaa=0)
    base.update(kw)
    return RenderOptions(**base)


def test_integration_on_with_a_neutral_plate_reproduces_the_golden(gl_ctx):
    # The plumbing identity: `on` changes where the pixels are assembled,
    # never what they are. NEUTRAL_PLATE makes every composite term vanish
    # by construction, and msaa=0 makes coverage exactly 0 or 1.
    backend = GLBackend(gl_ctx, RenderOptions(
        scale=1, shading="smooth", lighting="scene", msaa=0,
        realism="classic", smoothing=0, shadows="hard", integration="on"))
    backend.draw(_golden_frame())
    out = backend.read_rgb()
    backend.release()
    assert np.array_equal(out, np.load(GOLDEN))


@pytest.mark.parametrize("shadows", ["hard", "soft"])
def test_integration_on_matches_off_pixel_for_pixel_at_msaa_zero(gl_ctx, shadows):
    # Not just the golden scene: a real cast shadow under both shadow modes.
    frame = _lit_frame([_standing_actor(0, _tri_geometry(600.0, 1), 400.0)],
                       (0.3, -0.6, -0.7))
    off = GLBackend(gl_ctx, _integration_options(shadows=shadows, integration="off"))
    off.draw(frame)
    expected = off.read_rgb().copy()
    off.release()
    on = GLBackend(gl_ctx, _integration_options(shadows=shadows, integration="on"))
    on.draw(frame)
    got = on.read_rgb().copy()
    on.release()
    assert np.array_equal(got, expected)


def test_integration_leaves_fixed_lighting_untouched(gl_ctx):
    # `integration` applies under lighting="scene" only.
    actor = _actor(0, _facing_tri(600.0, 1, (0.0, 0.0, -1.0)))
    off = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="fixed",
                                          integration="off"))
    off.draw(_frame([actor]))
    expected = off.read_rgb().copy()
    off.release()
    on = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="fixed",
                                         integration="on"))
    on.draw(_frame([actor]))
    assert np.array_equal(on.read_rgb(), expected)
    on.release()


def test_integration_on_still_resolves_msaa_into_the_same_texture(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=2, shading="smooth", lighting="scene",
                                              msaa=4, integration="on"))
    backend.draw(_lit_frame([_standing_actor(0, _tri_geometry(600.0, 1), 400.0)],
                            (0.3, -0.6, -0.7)))
    assert backend.read_rgb().shape == (400, 640, 3)
    assert backend.thumbnail().shape == (200, 320, 3)
    backend.release()


def test_integration_on_still_darkens_the_ground_under_a_hard_shadow(gl_ctx):
    # The hard cast moved ahead of the bodies to reach the plate layer; it
    # must still land on the plate.
    plate = np.full((200, 320, 3), 200, np.uint8)
    baseline = _plain_background(gl_ctx, plate, shadows="hard")
    backend = GLBackend(gl_ctx, _integration_options(shadows="hard", integration="on"))
    backend.draw(FrameDescription(
        _view(), ImageAsset(plate, False), _palette(),
        (_standing_actor(0, _tri_geometry(600.0, 1), 400.0),), (),
        _scene_light((0.3, -0.6, -0.7))))
    out = backend.read_rgb().astype(int)
    backend.release()
    assert (out < baseline).any(), "the hard cast never reached the plate layer"
```

Also update `test_init_failure_releases_every_already_allocated_gl_object`: add
`"_plate_tex", "_plate_fbo", "_actor_tex", "_actor_fbo", "_composite_prog", "_composite_vao"`
to the attribute tuple and change `assert leak_checked == 38` to `== 44`.

- [ ] **Step 2: Run them to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q -k "integration or init_failure"`
Expected: FAIL — the `on` renders differ from `off` (nothing implements the branch yet), and the leak test fails on the missing attributes.

- [ ] **Step 3: Add `COMPOSITE_FSH` to `glsl.py`**

At the end of `PyAitD/render/glsl.py`:

```python
COMPOSITE_FSH = """
#version 330
// The one full-target pass that puts the actor layer back onto the plate.
//
// The actor layer is premultiplied: its shader writes alpha 1, so a
// multisample resolve of covered and uncovered samples yields colour
// already scaled by coverage, which is exactly what "over" wants. At
// msaa = 0 alpha is 0 or 1 and this is `plate` or `rgb` with no arithmetic
// in between -- byte-exact against drawing the body straight onto the
// plate, which is the identity `integration=on` has to hold.
uniform sampler2D plate_tex; uniform sampler2D actor_tex;
out vec4 f_color;
void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    vec4 a = texelFetch(actor_tex, p, 0);
    vec3 plate = texelFetch(plate_tex, p, 0).rgb;
    f_color = vec4(plate * (1.0 - a.a) + a.rgb, 1.0);
}
"""
```

- [ ] **Step 4: Allocate the resources**

In `render_gl.py`, extend the `glsl` import with `COMPOSITE_FSH as _COMPOSITE_FSH`.

Add to the `None`-initialisation block in `__init__`, beside `self._target = None`:

```python
        self._plate_tex = None
        self._plate_fbo = None
        self._actor_tex = None
        self._actor_fbo = None
        self._composite_prog = None
        self._composite_vao = None
```

Allocate them inside the `try`, immediately after the `self._target = self._ms_fbo or self._fbo` line (they need `self._depth` and `self._shadow_quad`, both already built by then):

```python
            # The two halves integration="on" splits the frame into. Both
            # are the target's own size and format, so a resolve into either
            # is the same copy_framebuffer the single-target path already
            # does. _actor_fbo shares `_depth` with `_fbo` rather than
            # allocating a second one: the two are never both the render
            # target, and the composite that writes through `_fbo` runs with
            # the depth test disabled.
            self._plate_tex = ctx.texture(self.size, 4)
            self._plate_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            self._plate_tex.repeat_x = False
            self._plate_tex.repeat_y = False
            self._plate_fbo = ctx.framebuffer(color_attachments=[self._plate_tex])
            self._actor_tex = ctx.texture(self.size, 4)
            self._actor_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            self._actor_tex.repeat_x = False
            self._actor_tex.repeat_y = False
            self._actor_fbo = ctx.framebuffer(
                color_attachments=[self._actor_tex], depth_attachment=self._depth)
            self._composite_prog = ctx.program(
                vertex_shader=_STENCIL_VSH, fragment_shader=_COMPOSITE_FSH)
            _set_uniform(self._composite_prog, "plate_tex", 5)
            _set_uniform(self._composite_prog, "actor_tex", 6)
            self._composite_vao = ctx.vertex_array(
                self._composite_prog, [(self._shadow_quad, "2f", "in_pos")])
```

In `release()`, add `self._composite_vao,` to the VAO group that precedes `self._shadow_quad` (it is built on that buffer, so it must be freed first), and add `self._composite_prog, self._plate_fbo, self._plate_tex, self._actor_fbo, self._actor_tex,` immediately before the `self._mask_fbo, self._mask_tex,` line. Extend `release()`'s leading comment so it names the new aliases:

```python
        # `self._target` is intentionally absent: it aliases `self._ms_fbo`,
        # `self._fbo`, `self._plate_fbo` or `self._actor_fbo` depending on
        # the integration mode and the frame phase, and each of those is
        # released below under its own name.
```

- [ ] **Step 5: Restructure `_draw_frame`**

Three edits inside `_draw_frame`, plus three new small methods.

First, right after `soft = ...` and `level = ...`:

```python
        # Under lighting="scene" only: `fixed` runs the single-target path
        # byte for byte whatever `integration` says.
        integrate = scene_lit and self._options.integration == "on"
        self._target = (self._ms_fbo or self._plate_fbo) if integrate \
            else (self._ms_fbo or self._fbo)
```

Note the ordering: `self._target` is assigned **before** the existing
`self._target.use()` at the top of the method, so move that assignment (and
the `integrate`/`soft`/`scene_lit` lines it depends on) above the current
first line of `_draw_frame`. `mvp`, `view_m` and `rot` do not move.

Second, replace the `if soft: self._gather_shadows(...)` line with:

```python
            if soft:
                self._gather_shadows(frame, instances, mask_by_id, travel, mvp, rot, level)
            elif integrate and scene_lit:
                # The hard casts have to reach the *plate* layer, so under
                # `on` they all run here, before any body, instead of
                # interleaved in the loop below. _composite_shadow blends
                # (DST_COLOR, ZERO): on a transparent actor layer it would
                # scale (0,0,0,0) by a factor -- producing nothing -- while
                # darkening every body already drawn. Running them here also
                # retires, for this path only, the ordering caveat in
                # _composite_shadow's docstring.
                for actor, inst in zip(frame.actors, instances):
                    self._cast_hard_shadow(actor, inst, mask_by_id, frame, travel, mvp, level)

            if integrate:
                self._resolve_into(self._plate_fbo)
                self._target = self._ms_fbo or self._actor_fbo
                self._target.use()
                self._ctx.viewport = (0, 0, *self.size)
                self._ctx.disable(moderngl.DEPTH_TEST)
                self._ctx.disable(moderngl.BLEND)
                self._target.color_mask = (True, True, True, True)
                # Transparent, not opaque black: the actor shader writes
                # alpha 1, so what survives the resolve is coverage.
                self._ctx.clear(0.0, 0.0, 0.0, 0.0)
```

Third, in the per-actor loop, guard the existing hard-shadow block so it does
not run twice:

```python
                if scene_lit and not soft and not integrate:
```

and replace its body with a call to the same helper, so there is one copy of
the rule:

```python
                if scene_lit and not soft and not integrate:
                    self._cast_hard_shadow(actor, inst, mask_by_id, frame, travel, mvp, level)
```

Note that the loop's own `self._rasterize_masks(masks)` call stays where it
is: the actor shader reads `_mask_tex` for its own discard, independently of
any shadow.

Finally, replace the tail of `_draw_frame`:

```python
        if integrate:
            self._resolve_into(self._actor_fbo)
            self._composite()
        elif self._ms_fbo is not None:
            # Resolves the multisample buffer down into `.texture`, which is
            # what read_rgb, thumbnail and Renderer all read.
            self._ctx.copy_framebuffer(self._fbo, self._ms_fbo)
```

The three new methods, placed after `_composite_shadow`:

```python
    def _cast_hard_shadow(self, actor, inst, mask_by_id, frame, travel, mvp, level):
        """One actor's `shadows=hard` projected silhouette, erased by its own
        masks and multiplied onto whatever `self._target` currently is.

        Extracted so the per-actor loop and the integration pre-loop share
        one copy of the rule; the only difference between the two callers is
        which layer `self._target` names when they run."""
        self._rasterize_masks([mask_by_id[i] for i in actor.mask_ids if i in mask_by_id])
        if level:
            cast = self._rasterize_shadow_tessellated(inst, travel, mvp, _plane_y(actor), level)
        else:
            cast = self._rasterize_shadow(actor, travel, mvp)
        if cast:
            self._composite_shadow(frame.light)

    def _resolve_into(self, fbo):
        """Resolve the multisample buffer into `fbo`'s single-sampled
        texture. A no-op when msaa is off: `fbo` was the render target
        itself, and its texture already holds the result."""
        if self._ms_fbo is not None:
            self._ctx.copy_framebuffer(fbo, self._ms_fbo)

    def _composite(self):
        """The actor layer back onto the plate layer, into `.texture`."""
        self._fbo.use()
        self._ctx.viewport = (0, 0, *self.size)
        self._ctx.disable(moderngl.DEPTH_TEST)
        self._ctx.disable(moderngl.BLEND)
        self._fbo.color_mask = (True, True, True, True)
        self._fbo.use()
        self._plate_tex.use(location=5)
        self._actor_tex.use(location=6)
        self._composite_prog["plate_tex"].value = 5
        self._composite_prog["actor_tex"].value = 6
        self._composite_vao.render(moderngl.TRIANGLES)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q`
Expected: PASS, including the four new identity tests and the 44-resource leak count.

- [ ] **Step 7: Prove the composite is load-bearing**

Temporarily change `COMPOSITE_FSH`'s last line to `f_color = vec4(a.rgb, 1.0);` (drop the plate term) and rerun
`SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q -k integration`.
Expected: the identity tests FAIL. Revert the change and confirm they pass again. Paste both outcomes into the task report — a composite pass that no test can distinguish from a black screen is the failure mode this step exists to rule out.

- [ ] **Step 8: Run the full suite**

Run: `make test`
Expected: green.

- [ ] **Step 9: Commit**

```bash
git add PyAitD/render/glsl.py PyAitD/render/render_gl.py tests/test_render_gl.py
git commit -m "feat: resolve actors into their own layer and composite them back"
```

---

### Task 4: Soften and pixelate

**Files:**
- Modify: `PyAitD/render/glsl.py` (`COMPOSITE_FSH`)
- Modify: `PyAitD/render/render_gl.py` (`_composite` takes `frame`; `MAX_BLUR_RADIUS`)
- Test: `tests/test_render_gl.py`

**Interfaces:**
- Consumes: `plate.softness(background_filter, src_size, target_size)` from task 1; `COMPOSITE_FSH` and `_composite()` from task 3.
- Produces: `render_gl.MAX_BLUR_RADIUS = 4`; `COMPOSITE_FSH` uniforms `radius` (int), `inv_sigma2` (float), `cell` (float), `pixelate` (int).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_render_gl.py`:

```python
def _edge_transition_width(rgb, row):
    """How many pixels of the row are strictly between the two extremes:
    the width of the actor's edge ramp."""
    line = rgb[row].astype(int).sum(axis=1)
    lo, hi = line.min(), line.max()
    return int(((line > lo + 4) & (line < hi - 4)).sum())


def _edge_frame(plate):
    return FrameDescription(
        _view(), ImageAsset(plate, False), _palette(),
        (_standing_actor(0, _tri_geometry(600.0, 1), 400.0),), (),
        _scene_light((0.0, -1.0, 0.0)))


def test_bilinear_softening_widens_an_actor_edge(gl_ctx):
    # At scale 4 over a 320-wide plate each plate pixel became a 4x4 cell,
    # so bilinear left the plate soft over ~1.4 px; the actor is softened
    # to match, and its edge ramp gets wider than the hard `off` one.
    plate = np.zeros((200, 320, 3), np.uint8)
    frame = _edge_frame(plate)
    widths = {}
    for integration in ("off", "on"):
        backend = GLBackend(gl_ctx, RenderOptions(
            scale=4, shading="smooth", lighting="scene", msaa=0,
            background_filter="bilinear", integration=integration))
        backend.draw(frame)
        widths[integration] = _edge_transition_width(backend.read_rgb(), 400)
        backend.release()
    assert widths["on"] > widths["off"]


def test_nearest_pixelates_the_actor_to_the_plate_grid(gl_ctx):
    # A constant plate, so the only thing that could vary inside a 4x4 cell
    # is the actor -- and under `nearest` it must not.
    plate = np.full((200, 320, 3), 90, np.uint8)
    backend = GLBackend(gl_ctx, RenderOptions(
        scale=4, shading="smooth", lighting="scene", msaa=0,
        background_filter="nearest", integration="on"))
    backend.draw(_edge_frame(plate))
    out = backend.read_rgb()
    backend.release()
    cells = out.reshape(200, 4, 320, 4, 3)
    assert (cells.max(axis=(1, 3)) == cells.min(axis=(1, 3))).all()


def test_nothing_is_softened_when_the_plate_is_already_target_resolution(gl_ctx):
    # cell == 1: an override plate at the target size. Still the identity.
    frame = _edge_frame(np.zeros((200, 320, 3), np.uint8))
    off = GLBackend(gl_ctx, _integration_options(background_filter="bilinear",
                                                 integration="off"))
    off.draw(frame)
    expected = off.read_rgb().copy()
    off.release()
    on = GLBackend(gl_ctx, _integration_options(background_filter="bilinear",
                                                integration="on"))
    on.draw(frame)
    assert np.array_equal(on.read_rgb(), expected)
    on.release()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q -k "softening or pixelates or already_target"`
Expected: the first two FAIL (no softening or pixelation yet); the third already passes and must keep passing.

- [ ] **Step 3: Extend `COMPOSITE_FSH`**

Replace the shader body with:

```python
COMPOSITE_FSH = """
#version 330
// The one full-target pass that puts the actor layer back onto the plate.
//
// The actor layer is premultiplied: its shader writes alpha 1, so a
// multisample resolve of covered and uncovered samples yields colour
// already scaled by coverage, which is exactly what "over" wants. At
// msaa = 0 alpha is 0 or 1 and this is `plate` or `rgb` with no arithmetic
// in between -- byte-exact against drawing the body straight onto the
// plate, which is the identity `integration=on` has to hold.
//
// Sampling is done on the premultiplied values throughout: blurring colour
// and coverage together is what keeps a soft edge from bleeding the
// interior's colour outward into fully transparent pixels.
uniform sampler2D plate_tex; uniform sampler2D actor_tex;
uniform int radius;        // Gaussian half-width in target pixels; 0 = one tap
uniform float inv_sigma2;  // 1 / (2 sigma^2); unread when radius is 0
uniform float cell;        // one plate pixel, in target pixels
uniform int pixelate;      // 1 under `nearest`: fetch per plate cell
out vec4 f_color;

vec4 sample_actor(ivec2 p, ivec2 size) {
    if (pixelate != 0) {
        // The centre of the plate cell this pixel falls in, so a blocky
        // plate gets blocky actors on the same grid.
        vec2 c = (floor(vec2(p) / cell) + 0.5) * cell;
        return texelFetch(actor_tex, clamp(ivec2(c), ivec2(0), size - 1), 0);
    }
    if (radius <= 0) return texelFetch(actor_tex, p, 0);
    vec4 sum = vec4(0.0);
    float total = 0.0;
    // `radius` is a uniform, so this is uniform control flow and the tap
    // count is the same for every pixel of the frame. Edge-clamped rather
    // than skipped, and normalised by the weight actually accumulated, so
    // the border neither darkens nor loses coverage.
    for (int dy = -radius; dy <= radius; dy++) {
        for (int dx = -radius; dx <= radius; dx++) {
            ivec2 q = clamp(p + ivec2(dx, dy), ivec2(0), size - 1);
            float w = exp(-float(dx * dx + dy * dy) * inv_sigma2);
            sum += texelFetch(actor_tex, q, 0) * w;
            total += w;
        }
    }
    return sum / total;
}

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    vec4 a = sample_actor(p, textureSize(actor_tex, 0));
    vec3 plate = texelFetch(plate_tex, p, 0).rgb;
    f_color = vec4(plate * (1.0 - a.a) + a.rgb, 1.0);
}
"""
```

- [ ] **Step 4: Drive it from `_composite`**

In `render_gl.py`, add the import `from PyAitD.render.plate import softness` and the constant beside `R_MAX_PER_SCALE`:

```python
# The composite's tap budget: a 9x9 window at the widest. sigma tops out at
# 0.35 * 8 = 2.8 at scale 8 over a classic plate, where +-4 covers 1.4
# sigma; the weights are renormalised by what was actually gathered, so the
# truncation costs sharpness at the tail, never brightness.
MAX_BLUR_RADIUS = 4
```

Change `_composite(self)` to `_composite(self, frame)`, call it as `self._composite(frame)`, and seed the four uniforms at the top of its body:

```python
        src_h, src_w = frame.background.pixels.shape[:2]
        sigma, cell, pixelate = softness(
            self._options.background_filter, (src_w, src_h), self.size)
        radius = 0 if sigma <= 0.0 else min(MAX_BLUR_RADIUS, int(math.ceil(2.0 * sigma)))
        self._composite_prog["radius"].value = radius
        self._composite_prog["inv_sigma2"].value = (
            0.0 if sigma <= 0.0 else 1.0 / (2.0 * sigma * sigma))
        self._composite_prog["cell"].value = float(cell)
        self._composite_prog["pixelate"].value = 1 if pixelate else 0
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q`
Expected: PASS, the task 3 identity tests included — at scale 1 over a 320-wide plate `cell` is 1, so `softness` returns `(0.0, 1.0, False)` and `sample_actor` takes the single `texelFetch` branch.

- [ ] **Step 6: Run the full suite**

Run: `make test`
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add PyAitD/render/glsl.py PyAitD/render/render_gl.py tests/test_render_gl.py
git commit -m "feat: soften or pixelate the actor layer to the plate's grid"
```

---

### Task 5: Tone and grain

**Files:**
- Modify: `PyAitD/render/glsl.py` (`COMPOSITE_FSH`)
- Modify: `PyAitD/render/render_gl.py` (`_composite` seeds the profile)
- Test: `tests/test_render_gl.py`

**Interfaces:**
- Consumes: `FrameDescription.plate` (task 1); `COMPOSITE_FSH` and `_composite(frame)` (tasks 3-4).
- Produces: `COMPOSITE_FSH` uniforms `plate_black` (vec3), `plate_white` (vec3), `plate_grain` (float).

**The identity, again by construction:** with `NEUTRAL_PLATE`, `plate_black` is `(0,0,0)` so the toe adds exactly zero, `1.0 - plate_white` is `(0,0,0)` so the shoulder subtracts exactly zero, and `plate_grain` is 0.0 so the noise term is exactly zero. `c` is then `a.rgb / a.a` and `c * a.a` returns `a.rgb` exactly when `a.a` is 1.0. Nothing here is a near-miss that happens to round back.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_render_gl.py`:

```python
def _profiled_frame(plate_pixels, profile, colour=1):
    from PyAitD.render.scene import FrameDescription as FD
    return FD(_view(), ImageAsset(plate_pixels, False), _palette(),
              (_standing_actor(0, _tri_geometry(600.0, colour), 400.0),), (),
              _scene_light((0.0, -1.0, 0.0)), profile)


def _composited_centre(gl_ctx, profile, palette=None, colour=1, plate_value=0):
    """The composited pixel at the centre of one flat, fully-lit triangle,
    under `profile`. Everything except the profile is held fixed, so two
    calls differ only by what the tone curve did."""
    from PyAitD.render.scene import FrameDescription as FD
    palette = _palette() if palette is None else palette
    plate = np.full((200, 320, 3), plate_value, np.uint8)
    frame = FD(_view(), ImageAsset(plate, False), palette,
               (_standing_actor(0, _tri_geometry(600.0, colour), 400.0),), (),
               _scene_light((0.0, 0.0, -1.0)), profile)
    backend = GLBackend(gl_ctx, RenderOptions(
        scale=1, shading="smooth", lighting="scene", msaa=0,
        realism="classic", integration="on"))
    backend.draw(frame)
    got = _centre(backend.read_rgb())
    backend.release()
    return got


def test_the_toe_lifts_a_black_actor_to_the_rooms_floor(gl_ctx):
    # palette index 0 is black, and realism="classic" zeroes the specular
    # and rim terms, so the actor's own colour really is (0, 0, 0): the
    # whole of the difference below is the toe.
    from PyAitD.render.plate import NEUTRAL_PLATE, PlateProfile
    black = (30 / 255, 20 / 255, 20 / 255)
    flat = _composited_centre(gl_ctx, NEUTRAL_PLATE, colour=0)
    lifted = _composited_centre(gl_ctx, PlateProfile(black, (1.0, 1.0, 1.0), 0.0), colour=0)
    assert list(flat) == [0, 0, 0]
    assert list(lifted) == pytest.approx([30, 20, 20], abs=1)


def test_the_shoulder_pulls_a_white_actor_to_the_rooms_ceiling(gl_ctx):
    # A white palette entry on a triangle facing the light head-on: the
    # neutral render saturates, and the 0.8 ceiling has to pull it down.
    from PyAitD.render.plate import NEUTRAL_PLATE, PlateProfile
    palette = np.zeros((256, 3), np.uint8)
    palette[1] = (255, 255, 255)
    flat = _composited_centre(gl_ctx, NEUTRAL_PLATE, palette=palette)
    pulled = _composited_centre(
        gl_ctx, PlateProfile((0.0, 0.0, 0.0), (0.8, 0.8, 0.8), 0.0), palette=palette)
    assert flat.max() == 255
    assert pulled.max() < 255
    assert pulled.max() == pytest.approx(204, abs=2)   # 255 * 0.8


def test_grain_is_still_and_confined_to_the_actor(gl_ctx):
    from PyAitD.render.plate import PlateProfile
    profile = PlateProfile((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), 0.08)
    plate = np.full((200, 320, 3), 120, np.uint8)
    backend = GLBackend(gl_ctx, _integration_options(integration="on"))
    frame = _profiled_frame(plate, profile)
    backend.draw(frame)
    first = backend.read_rgb().copy()
    backend.draw(frame)
    second = backend.read_rgb().copy()
    backend.release()
    assert np.array_equal(first, second)          # hashed on the screen cell: it sits still
    assert np.array_equal(first[10, 10], [120, 120, 120])   # outside the actor: untouched


def test_grain_lands_at_the_plates_own_amplitude(gl_ctx):
    # GAIN is sqrt(12) precisely so the composited residual's RMS equals
    # `grain`. Measured as the difference between two otherwise identical
    # renders, which isolates the noise from the actor's own shading.
    from PyAitD.render.plate import PlateProfile
    plate = np.full((200, 320, 3), 120, np.uint8)
    outs = []
    for grain in (0.0, 0.08):
        backend = GLBackend(gl_ctx, _integration_options(integration="on"))
        backend.draw(_profiled_frame(plate, PlateProfile((0.0,) * 3, (1.0,) * 3, grain)))
        outs.append(backend.read_rgb().astype(float))
        backend.release()
    # A patch well inside the triangle (see _centre's note on its extent).
    patch = (outs[1] - outs[0])[60:100, 110:150, 0]
    assert patch.std() == pytest.approx(0.08 * 255, rel=0.25)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q -k "toe or shoulder or grain"`
Expected: FAIL — no tone or grain terms exist, so the black actor stays black, the white one stays 255, and both grain renders are identical.

- [ ] **Step 3: Extend `COMPOSITE_FSH`**

Add the three uniforms, the constants, the hash and the tone block. The declarations go with the others; the constants and hash go above `sample_actor`:

```glsl
uniform vec3 plate_black;   // the room's floor, 0..1 linear RGB
uniform vec3 plate_white;   // the room's ceiling
uniform float plate_grain;  // RMS luma residual of the plate's own dither

// Meet the plate exactly at the extremes: at luma 0 the toe adds the whole
// of `plate_black`, at luma 1 the shoulder subtracts the whole of
// `1 - plate_white`. The quartic confines both to the ends -- at luma 0.5
// only 1/16 of the offset applies -- so this lifts the actor's darks into
// the room without flattening its midtones.
const float TOE = 1.0;
const float SHOULDER = 1.0;
// hash - 0.5 is uniform on [-0.5, 0.5], whose RMS is 1/sqrt(12). Scaling
// by sqrt(12) makes the composited residual's RMS equal `plate_grain` --
// which is the RMS estimate_plate measured off the plate. Not a taste
// constant: it is what "the plate's own amplitude" resolves to.
const float GAIN = 3.4641016;
const vec3 REC709 = vec3(0.2126, 0.7152, 0.0722);

// Hoskins' hash11 on a vec2 seed: no sin(), which GPUs implement to wildly
// different precision at large arguments. Seeded on the screen cell alone,
// so the noise sits still like the plate's dither instead of crawling.
float hash21(vec2 v) {
    vec3 p = fract(vec3(v.xyx) * 0.1031);
    p += dot(p, p.yzx + 33.33);
    return fract((p.x + p.y) * p.z);
}
```

and replace `main`:

```glsl
void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    vec4 a = sample_actor(p, textureSize(actor_tex, 0));
    vec3 plate = texelFetch(plate_tex, p, 0).rgb;
    vec3 c = vec3(0.0);
    if (a.a > 0.0) {
        c = a.rgb / a.a;                        // unpremultiply to tone-match
        float luma = dot(c, REC709);
        float toe = (1.0 - luma) * (1.0 - luma);
        toe *= toe;                             // (1 - luma)^4
        float shoulder = luma * luma;
        shoulder *= shoulder;                   // luma^4
        c += plate_black * (toe * TOE);
        c -= (vec3(1.0) - plate_white) * (shoulder * SHOULDER);
        c += plate_grain * (hash21(floor(gl_FragCoord.xy / cell)) - 0.5) * GAIN;
        c = clamp(c, 0.0, 1.0);
    }
    f_color = vec4(plate * (1.0 - a.a) + c * a.a, 1.0);
}
```

- [ ] **Step 4: Seed the profile in `_composite`**

Append to `_composite(self, frame)`, beside the softness uniforms:

```python
        self._composite_prog["plate_black"].value = tuple(float(v) for v in frame.plate.black)
        self._composite_prog["plate_white"].value = tuple(float(v) for v in frame.plate.white)
        self._composite_prog["plate_grain"].value = float(frame.plate.grain)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q`
Expected: PASS, the task 3 and task 4 identity tests included — the golden frame carries `NEUTRAL_PLATE`, so every term above is exactly zero.

- [ ] **Step 6: Run the full suite**

Run: `make test`
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add PyAitD/render/glsl.py PyAitD/render/render_gl.py tests/test_render_gl.py
git commit -m "feat: tone-match and grain the actor layer to the plate"
```

---

### Task 6: Flip the default, prove it, document it

**Files:**
- Modify: `PyAitD/render/render_options.py` (`integration: str = "on"`)
- Modify: `tools/prove_graphics.py`
- Modify: `tests/test_render_gl.py`, `tests/test_prove_graphics.py`, `tests/test_render_options.py`, `tests/test_ui_render.py`, `tests/test_config.py`
- Create: `docs/plate-integration-proof.md`
- Modify: `README.md`, `AGENTS.md`, `CONTEXT.md`, `Makefile`

**Interfaces:**
- Consumes: everything from tasks 1-5.
- Produces: `prove_graphics.render_fixture(..., integration=None)`, `output_paths(out_dir, smoothing=None, shadows=None, integration=None)` yielding 7-tuples `(name, mode, realism, smoothing, shadows, integration, path)`, and a `<fixture>-smooth-enhanced-nocomposite.png` twin per fixture.

- [ ] **Step 1: Flip the default and repin the tests that named it**

In `render_options.py`, `integration: str = "on"`.

In `tests/test_render_gl.py::test_classic_realism_matches_the_pre_materials_golden`, add `integration="off"` to the `RenderOptions(...)` call and extend the comment:

```python
    # smoothing=0, shadows="hard" and integration="off" name the legacy
    # paths explicitly: the golden predates tessellation, the gathered
    # soft-shadow pass and the plate composite.
```

In `tests/test_render_options.py`, flip `test_integration_defaults_to_off_and_cycles` to
`test_integration_defaults_to_on_and_cycles`, asserting `options.integration == "on"`
and `cycle_integration(options).integration == "off"`; update the two payload literals.
Update `tests/test_config.py:204` and `tests/test_ui_render.py`'s
`labels[8] == "Integration: On"`.

- [ ] **Step 2: Run the full suite and read every failure**

Run: `make test`
Expected: some tests fail. Every failure must be triaged and reported, not blanket-repinned. The two legitimate categories:
  1. A test that named the old default and must now name it explicitly (repin).
  2. A test asserting an exact pixel at `msaa > 0`, now off by 1 because the plate and actor layers quantise to 8 bits between the resolve and the composite (widen to a tolerance, and say so in the report).
Anything outside those two is a defect in tasks 3-5. Do not repin it — fix it, or escalate with the diff.

- [ ] **Step 3: Add the proof twin to `prove_graphics.py`**

Add `INTEGRATION_MODES` to the `render_options` import. Extend `render_fixture`:

```python
def render_fixture(data_dir, name, scale, shading, ctx, realism="enhanced",
                   smoothing=None, shadows=None, integration=None):
    ...
    if integration is not None:
        options = replace(options, integration=integration)
```

Extend `output_paths` to a 7-tuple and add the twin:

```python
def output_paths(out_dir, smoothing=None, shadows=None, integration=None):
    """(name, mode, realism, smoothing, shadows, integration, path) for every
    fixture x shading-mode x realism combination at `smoothing`, `shadows`
    and `integration` (the RenderOptions defaults when None), then one
    flat-mesh (smoothing 0), one hard-shadow (shadows "hard") and one
    un-composited (integration "off") file per fixture beside the
    smooth-enhanced render, in the order rendered and printed by `main`."""
    ...
    mode_integration = defaults.integration if integration is None else integration
    ...
    paths += [(name, "smooth", "enhanced", level, mode_shadows, "off",
               out_dir / f"{name}-smooth-enhanced-nocomposite.png")
              for name in FIXTURES]
```

Add the argument and thread it through `main`'s loop:

```python
    p.add_argument("--integration", choices=INTEGRATION_MODES,
                   default=RenderOptions().integration,
                   help="plate integration for the main renders (the -nocomposite pair is always off)")
```

Update the module docstring to name the third twin and `docs/plate-integration-proof.md`.

Update `tests/test_prove_graphics.py` for the 7-tuple, the new suffix, and the new
flag — the existing `test_parse_args_smoothing_and_shadows_default_to_the_render_defaults`
and the `params == [...]` signature assertion at line 90 both need extending. Add:

```python
def test_the_default_composites_and_nocomposite_does_not(gl_ctx, data_dir):
    rgb = render_fixture(data_dir, "attic", scale=2, shading="smooth", ctx=gl_ctx)
    plain = render_fixture(data_dir, "attic", scale=2, shading="smooth", ctx=gl_ctx,
                           integration="off")
    assert not np.array_equal(rgb, plain)   # the default composites, and it shows
```

matching the fixture names `test_prove_graphics.py` already uses.

- [ ] **Step 4: Run the tool tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_prove_graphics.py -q`
Expected: PASS (tests needing real game data skip without it; say which in the report).

- [ ] **Step 5: Write `docs/plate-integration-proof.md`**

Follow `docs/soft-shadows-proof.md`'s structure exactly: `# Plate integration proof`, date, spec pointer, the standing warning that every "Manual attestation" row starts `pending` and no claim about the rendered PNGs may be inferred until a human fills them in, then `## What changed`, `## Automated gates` (paste the *real* output of the two pytest runs), `## make proof-graphics`, `## Frame time`, `## Deviations from the plan`, `## Known limitations`, `## Manual attestation`.

Known limitations to carry over verbatim from the spec, each as its own row:
- Tone matching is global to the plate, not local to the pixels around the actor; grain is luma-only.
- `nearest` pixelates the actor, not its ground shadow, which stays at target resolution on the plate layer.
- Softening touches the actor's interior, not just its edge, by `sigma <= 0.35 * cell`.
- Cost: two resolves and one full-target composite per frame; `off` is the escape hatch, on the Graphics page.
- The software backend stays uncomposited.

Plus two this plan added:
- Under `integration="on"`, `shadows="hard"` casts run before the bodies rather than interleaved, so a nearer actor's hard silhouette can no longer paint over a farther body — a behaviour difference from `off`, in the same direction `soft` already went.
- The plate and actor layers quantise to 8 bits between the resolve and the composite, so at `msaa > 0` an antialiased edge can differ from `off` by 1/255.

Measure frame time the way `docs/soft-shadows-proof.md` does, at scale 4 and scale 8, `on` against `off`, and report both. If `on` at scale 8 comes in over the budget that document sets, say so and record it as a limitation — do not silently retune `MAX_BLUR_RADIUS` to hide it.

- [ ] **Step 6: Update the docs**

- `README.md:69`: "nine CLI flags" → "ten CLI flags". Add an `--integration {off,on}` clause beside the `--shadows` one at line 97, in the same voice.
- `AGENTS.md`: extend the `render/` conventions bullet (around line 145) so `plate.py` is named as pure numpy beside `refine`, and note that `render_gl` splits into a plate layer and an actor layer under `integration="on"`.
- `CONTEXT.md`: add the sub-project G line beside F's and H's.
- `Makefile:85`: extend `proof-graphics`' help text to mention the un-composited pair.
- `pyproject.toml`: **leave it alone.** No new dependency, and this repo bumps the version at milestone doc-syncs, not per feature.
- `.gitignore`: no change — `docs/graphics-proof/` already keeps only its `.gitkeep`.

- [ ] **Step 7: Run the full suite**

Run: `make test`
Expected: green, with the count reported in the proof doc.

- [ ] **Step 8: Commit**

```bash
git add PyAitD/render/render_options.py tools/prove_graphics.py tests/ docs/plate-integration-proof.md README.md AGENTS.md CONTEXT.md Makefile
git commit -m "feat: composite actors through the plate by default"
```

---

## Self-review

**Spec coverage.** `plate.py` / `PlateProfile` / `estimate_plate` / `softness` → task 1; `AssetResolver.plate` and `FrameDescription.plate` → task 1; the actor layer's three phases → task 3; the composite's four steps → tasks 3 (step 4), 4 (step 1), 5 (steps 2 and 3); `RenderOptions.integration` and the Graphics row → task 2; the resource list and the pinned leak count → task 3; every "Testing — G" bullet is claimed by a named test above; the default flip, the proof tooling and the docs → task 6. No spec requirement is unclaimed.

**Placeholders.** None: every code step carries the code, every test step the assertions, every command its expected output.

**Type consistency.** `softness` returns `(sigma_px, cell_px, pixelate)` in task 1 and is destructured in that order in task 4. `PlateProfile.black/.white` are 3-tuples in task 1 and are seeded as `vec3` in task 5. `_composite` takes no argument in task 3 and gains `frame` in task 4, which task 5 also uses — the task 4 step says to change both the definition and its one call site. `output_paths`' tuple widens from 6 to 7 elements in task 6, and both the tool's own loop and `tests/test_prove_graphics.py` are named there.
