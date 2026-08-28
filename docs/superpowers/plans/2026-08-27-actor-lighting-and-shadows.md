# Actor Lighting and Shadows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Light each actor with a light estimated from the camera's own background image, and drop a projected silhouette shadow on the ground beneath them, so actors look like they are standing in the room rather than pasted over it.

**Architecture:** A new pure-numpy `render/lighting.py` estimates a `SceneLight` (direction, key colour, ambient colour, contrast) from a background image; `AssetResolver` memoises one per camera and `build_frame` puts it on `FrameDescription`; `GLBackend` uses it for a real diffuse term and for a per-actor shadow pass rasterised through a coverage texture. A new `lighting` render option gates all of it, and `lighting="fixed"` reproduces today's output byte for byte.

**Tech Stack:** Python 3.12, pygame-ce, ModernGL (GL 3.3 core), NumPy, pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-actor-lighting-and-shadows-design.md`

## Global Constraints

- Every Python file starts with `# SPDX-License-Identifier: GPL-2.0-only` as its first line.
- Dependencies are fixed: pygame-ce, ModernGL, NumPy, pytest. Add nothing.
- Package layering (enforced by `tests/test_layering.py`): `render/` and `games/` import only from `engine/`; `engine/` imports neither; `app/` may import everything. `render/lighting.py` therefore may not import from `app/` or `games/`.
- Game data is never committed. `data/aitd1/**` and `*.app/` are git-ignored.
- Never call `pygame.mouse.set_relative_mode`, `pygame.event.set_grab`, or `pygame.mouse.set_pos` anywhere under `PyAitD/`.
- Tests run headless: prefix every pytest command with `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`. The interpreter is `.venv/bin/python`.
- Every test file declares exactly one subject marker via a module-level `pytestmark` (`engine`, `render`, `shell`, `tools`, `meta`, plus the `journey` cross-marker). `tests/test_test_groups.py` enforces this.
- `lighting="fixed"` must reproduce today's rendered output byte for byte. This is the regression net for the whole plan; the existing GL tests are what prove it and must not be rewritten to accommodate new behaviour.
- No change to `skel.skin()`, `draw_list`, picking, masks, combat, or input.
- `SoftwareBackend` is not touched by this plan.

---

## File Structure

| File | Responsibility |
|---|---|
| `PyAitD/render/lighting.py` (create) | `SceneLight`, `LEGACY_LIGHT`, `estimate_light`, `shading_terms`, `project_to_plane`. Pure numpy: no pygame, no GL, no engine imports. |
| `tests/test_lighting.py` (create) | Unit tests for all of the above. No GL, no game data. |
| `PyAitD/render/render_options.py` | Adds the `lighting` and `msaa` fields, their legal-value tuples, validation and cycle helpers. |
| `PyAitD/app/ui.py` | Two more CONFIG menu rows, re-pitched to fit; the cycle and label wiring. |
| `PyAitD/app/shell.py` | `--lighting` and `--msaa` CLI flags; `_MENU_RENDER_FIELDS`. |
| `PyAitD/render/asset_resolver.py` | `AssetResolver.light(floor, cam_idx)`, memoised per camera. |
| `PyAitD/render/scene.py` | `FrameDescription.light`; `build_frame` fills it. |
| `PyAitD/render/render_gl.py` | The scene diffuse term, the shadow pass, MSAA. |
| `README.md`, `CONTEXT.md` | Document the two new options. |

---

### Task 1: The `lighting` and `msaa` render options

Both land switched off (`"fixed"` and `0`), so this task changes no rendered pixel. It exists so every later task has a gate to hide behind.

**Files:**
- Modify: `PyAitD/render/render_options.py`
- Modify: `PyAitD/app/ui.py:26-27` (`GRAPHICS_ROWS`), `PyAitD/app/ui.py:419-422` (the `cycles` tuple), `PyAitD/app/ui.py:1131-1138` (the label list), `PyAitD/app/ui.py:561-564` (`CONFIG_ROWS`), `PyAitD/app/ui.py:1140` (`button_size`)
- Modify: `PyAitD/app/shell.py:66-72` (CLI flags), `PyAitD/app/shell.py:96-100` (`apply_render_overrides`), `PyAitD/app/shell.py:579` (`_MENU_RENDER_FIELDS`)
- Test: `tests/test_render_options.py`, `tests/test_ui_reducers.py`, `tests/test_ui_mouse.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `LIGHTING_MODES = ("fixed", "scene")`, `MSAA_LEVELS = (0, 2, 4, 8)`, `RenderOptions(scale, shading, background_filter, override_dir, lighting, msaa)`, `cycle_lighting(options) -> RenderOptions`, `cycle_msaa(options) -> RenderOptions`.

**Note on field order:** the two new fields go **last**, after `override_dir`. Existing tests construct `RenderOptions(2, "flat", "xbr", "/tmp/ov")` positionally, and appending keeps them valid.

**Note on menu geometry:** the CONFIG page currently holds exactly 12 rows at a 16 px pitch starting at y=4, ending at y=196 — it is full. Two more rows do not fit at that pitch. `CONFIG_ROWS` is therefore re-pitched to 14 px starting at y=2, giving 14 rows ending at y=198. Rows stay ≥ 14 px tall, so `effective_rects`' 12×12 minimum-target contract (`docs/superpowers/specs/2026-08-24-overall-mouse-accessibility-design.md`) still holds with room to spare, but the raw row height drops from 16 to 14 and `tests/test_ui_mouse.py`'s CONFIG assertion has to move with it. That is a real, deliberate reduction in visible row height; do not paper over it by loosening the effective-target contract instead.

- [ ] **Step 1: Write the failing tests**

In `tests/test_render_options.py`, add:

```python
def test_lighting_and_msaa_default_off_and_cycle():
    from PyAitD.render.render_options import (
        LIGHTING_MODES, MSAA_LEVELS, cycle_lighting, cycle_msaa,
    )
    assert LIGHTING_MODES == ("fixed", "scene")
    assert MSAA_LEVELS == (0, 2, 4, 8)
    options = RenderOptions()
    assert options.lighting == "fixed" and options.msaa == 0
    assert cycle_lighting(options).lighting == "scene"
    assert cycle_lighting(cycle_lighting(options)).lighting == "fixed"
    assert cycle_msaa(options).msaa == 2
    assert cycle_msaa(RenderOptions(msaa=8)).msaa == 0


def test_invalid_lighting_and_msaa_fall_back_alone():
    payload = RenderOptions().to_payload()
    payload["lighting"] = "neon"
    options, error = validate_render_options(payload)
    assert options == RenderOptions() and "lighting" in error
    payload = RenderOptions().to_payload()
    payload["msaa"] = 3
    options, error = validate_render_options(payload)
    assert options == RenderOptions() and "msaa" in error
    # a bool is not an int here: True/False must not slip through as 1/0
    payload = RenderOptions().to_payload()
    payload["msaa"] = False
    options, error = validate_render_options(payload)
    assert options == RenderOptions() and "msaa" in error
```

In `tests/test_ui_reducers.py`, replace the body of the assertion at line 113:

```python
    assert GRAPHICS_ROWS == 5 and config_row_count() == 2 + len(REMAPPABLE_CONTROLS) + 5
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_options.py tests/test_ui_reducers.py -q`
Expected: FAIL with `ImportError: cannot import name 'LIGHTING_MODES'` and an assertion failure on `GRAPHICS_ROWS`.

- [ ] **Step 3: Add the options**

In `PyAitD/render/render_options.py`, add the value tuples beside the existing ones:

```python
LIGHTING_MODES = ("fixed", "scene")
MSAA_LEVELS = (0, 2, 4, 8)
```

Extend the dataclass (new fields last):

```python
@dataclass(frozen=True)
class RenderOptions:
    scale: int = 4
    shading: str = "smooth"
    background_filter: str = "bilinear"
    override_dir: str | None = None
    lighting: str = "fixed"
    msaa: int = 0

    def to_payload(self):
        return {
            "scale": self.scale,
            "shading": self.shading,
            "background_filter": self.background_filter,
            "override_dir": self.override_dir,
            "lighting": self.lighting,
            "msaa": self.msaa,
        }
```

In `validate_render_options`, after the `override_dir` block and before constructing `options`:

```python
    lighting = payload.get("lighting")
    if lighting not in LIGHTING_MODES:
        errors.append(f"lighting must be one of {', '.join(LIGHTING_MODES)}")
        lighting = defaults.lighting
    msaa = payload.get("msaa")
    # `type(x) is int` rejects bools: `False in MSAA_LEVELS` is True, since
    # False == 0. Same guard the scale field above uses, same reason.
    if not (type(msaa) is int and msaa in MSAA_LEVELS):
        errors.append(f"msaa must be one of {', '.join(str(v) for v in MSAA_LEVELS)}")
        msaa = defaults.msaa
    options = RenderOptions(scale, shading, background_filter, override_dir, lighting, msaa)
```

Add the two cycles beside the existing ones:

```python
def cycle_lighting(options):
    return replace(options, lighting=_cycle(LIGHTING_MODES, options.lighting))


def cycle_msaa(options):
    current = options.msaa if options.msaa in MSAA_LEVELS else MSAA_LEVELS[0]
    return replace(options, msaa=_cycle(MSAA_LEVELS, current))
```

- [ ] **Step 4: Wire the menu**

In `PyAitD/app/ui.py`, change the import at line 19 to include the new cycles:

```python
from PyAitD.render.render_options import (
    RenderOptions, cycle_filter, cycle_lighting, cycle_msaa, cycle_scale, cycle_shading,
)
```

Change `GRAPHICS_ROWS = 3` to `GRAPHICS_ROWS = 5`.

Re-pitch `SystemMenuLayout.CONFIG_ROWS` so 14 rows fit inside 200 logical pixels:

```python
    # 14 rows at a 14 px pitch from y=2 ends at y=198. The previous 16 px
    # pitch fitted exactly 12 rows and had no room for the Lighting and AA
    # rows. Rows stay >= 14 px tall, so effective_rects' 12x12 minimum
    # target contract still holds.
    CONFIG_ROWS = tuple(
        pygame.Rect(16, 2 + i * 14, 288, 14)
        for i in range(config_row_count())
    )
```

In `reduce_system_menu`, extend the cycles tuple (order must match the label order below):

```python
        cycles = (cycle_scale, cycle_shading, cycle_filter, cycle_lighting, cycle_msaa)
```

In `render_system_menu`, add the two labels after the Filter label, and drop the CONFIG button size to 12 so the text clears the shorter row:

```python
        labels.append(f"Filter: {settings.render.background_filter.title()}")
        labels.append(f"Lighting: {settings.render.lighting.title()}")
        labels.append(f"AA: {settings.render.msaa}x" if settings.render.msaa else "AA: Off")
        labels.append("Back to Menu")
    selection = presenter.hover if presenter.hover is not None else presenter.cursor
    button_size = 12 if presenter.page is SystemMenuPage.CONFIG else 18
```

In `tests/test_ui_mouse.py`, update the CONFIG branch of `test_story_whole_frame_confirms_and_menu_rows_are_large`:

```python
        elif page is SystemMenuPage.CONFIG:
            # the 14-row CONFIG page packs at a 14 px pitch to fit Scale,
            # Shading, Filter, Lighting and AA above Back without
            # overflowing the screen; effective_rects still pads every row
            # past the 12x12 minimum target size
            assert all(rect.width >= 224 and rect.height >= 14 for rect in rows)
```

- [ ] **Step 5: Wire the CLI and the persisted-field set**

In `PyAitD/app/shell.py`, import the new value tuples alongside `SHADING_MODES` and `BACKGROUND_FILTERS`, then add the flags beside `--background-filter`:

```python
    p.add_argument(
        "--lighting", choices=LIGHTING_MODES, default=None,
        help="fixed rig, or a light estimated from each camera's background",
    )
    p.add_argument(
        "--msaa", type=int, choices=MSAA_LEVELS, default=None,
        help="multisample anti-aliasing samples (0 disables)",
    )
```

In `apply_render_overrides`, beside the existing overrides:

```python
    if args.lighting is not None:
        payload["lighting"] = args.lighting
    if args.msaa is not None:
        payload["msaa"] = args.msaa
```

Extend the menu-persisted field set — both rows are menu-cyclable, so both belong here:

```python
_MENU_RENDER_FIELDS = ("scale", "shading", "background_filter", "lighting", "msaa")
```

- [ ] **Step 6: Run the full suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/ -q`
Expected: PASS. No rendered output has changed — both new options default to off.

- [ ] **Step 7: Commit**

```bash
git add PyAitD/render/render_options.py PyAitD/app/ui.py PyAitD/app/shell.py tests/
git commit -m "feat: lighting and msaa render options, defaulting to off"
```

---

### Task 2: The light estimator

**Files:**
- Create: `PyAitD/render/lighting.py`
- Test: `tests/test_lighting.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `SceneLight(direction: tuple, key: tuple, ambient: tuple, contrast: float)` — frozen dataclass.
  - `LEGACY_LIGHT: SceneLight`
  - `estimate_light(pixels) -> SceneLight` — `pixels` is `(H, W, 3)` uint8.
  - `shading_terms(light) -> (key: tuple, ambient: tuple)`
  - `project_to_plane(vertices, travel, plane_y) -> np.ndarray` — `vertices` `(N, 3)`, `travel` a 3-vector, returns `(N, 3)` float64.
  - `MIN_UP: float`, `FORWARD: float`

**Coordinate conventions — get these right, everything downstream depends on them:**

- Screen and camera-space **y grows downward**. `CameraState.project` computes `sy = y * focal3 / depth + SCREEN_CENTER_Y` with no sign flip, so a point higher on screen has a smaller y. World y shares that sense, since `camera_space` only subtracts the camera origin.
- Camera-space **+z is away from the camera**, into the scene (`depth = z + focal1`). `geometry._CAMERA_FACING` is `(0, 0, -1)`: a surface facing the viewer has a negative z normal.
- `SceneLight.direction` is the unit vector **from the surface toward the light**. Because y grows downward, a light above the scene has a **negative** y component; the estimator guarantees `direction[1] <= -MIN_UP`.
- The direction light **travels** is therefore `-direction`, whose y is positive — downward, which is what drops a shadow onto the floor.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_lighting.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
import numpy as np
import pytest

from PyAitD.render.lighting import (
    FORWARD, LEGACY_LIGHT, MIN_UP, SceneLight, estimate_light, project_to_plane,
    shading_terms,
)

pytestmark = pytest.mark.render


def _plate(fill=(0, 0, 0)):
    return np.full((200, 320, 3), fill, dtype=np.uint8)


def test_bright_region_top_left_puts_the_light_up_and_left():
    plate = _plate()
    plate[10:50, 10:60] = (255, 250, 230)
    light = estimate_light(plate)
    assert light.direction[0] < 0      # the light is to the left
    assert light.direction[1] < 0      # and above: screen y grows downward
    assert light.direction[2] < 0      # and in front of the scene
    assert np.isclose(np.linalg.norm(light.direction), 1.0)


def test_bright_region_bottom_right_puts_the_light_right_but_still_above():
    plate = _plate()
    plate[150:190, 260:310] = (255, 250, 230)
    light = estimate_light(plate)
    assert light.direction[0] > 0
    # a floor-lit room would cast an unusable upward shadow, so the
    # estimator clamps the light to always sit above the scene
    assert light.direction[1] <= -MIN_UP


def test_key_and_ambient_are_the_bright_and_dark_means():
    plate = _plate((20, 20, 40))
    plate[:20] = (200, 180, 160)
    light = estimate_light(plate)
    assert light.key[0] > light.ambient[0]
    assert light.ambient[2] > light.ambient[0]      # the dark region's blue cast survives
    assert 0.0 <= light.contrast <= 1.0
    assert light.contrast > 0.5                     # a bright band on a dark field


def test_uniform_plate_is_low_contrast_and_frontal():
    light = estimate_light(_plate((128, 128, 128)))
    assert light.contrast == pytest.approx(0.0, abs=1e-6)
    # with no contrast the centroid carries no information, so it is
    # discarded rather than read off argsort's arbitrary tie order
    assert light.direction[0] == pytest.approx(0.0)
    assert light.direction == pytest.approx(
        tuple(np.array([0.0, -MIN_UP, -FORWARD]) / np.linalg.norm([0.0, MIN_UP, FORWARD])))


@pytest.mark.parametrize("fill", [(0, 0, 0), (255, 255, 255)])
def test_degenerate_plates_still_produce_a_usable_light(fill):
    light = estimate_light(_plate(fill))
    assert np.isclose(np.linalg.norm(light.direction), 1.0)
    assert light.direction[1] <= -MIN_UP
    assert light.direction[2] < 0
    assert light.contrast == pytest.approx(0.0, abs=1e-6)


def test_shading_terms_are_unit_mean_tints_split_by_contrast():
    flat = SceneLight((0.0, -1.0, 0.0), (0.5, 0.5, 0.5), (0.2, 0.2, 0.2), 0.0)
    key, ambient = shading_terms(flat)
    assert np.mean(key) == pytest.approx(0.25)
    assert np.mean(ambient) == pytest.approx(0.75)
    assert np.mean(key) + np.mean(ambient) == pytest.approx(1.0)

    harsh = SceneLight((0.0, -1.0, 0.0), (0.5, 0.5, 0.5), (0.2, 0.2, 0.2), 1.0)
    key, ambient = shading_terms(harsh)
    assert np.mean(key) == pytest.approx(0.75)
    assert np.mean(ambient) == pytest.approx(0.25)


def test_shading_terms_keep_the_rooms_hue():
    warm = SceneLight((0.0, -1.0, 0.0), (0.6, 0.5, 0.4), (0.1, 0.1, 0.3), 0.5)
    key, ambient = shading_terms(warm)
    assert key[0] > key[2]          # a warm key stays warm
    assert ambient[2] > ambient[0]  # a cold fill stays cold


def test_shading_terms_survive_a_black_plate():
    black = SceneLight((0.0, -1.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 0.0)
    key, ambient = shading_terms(black)
    assert key == (0.0, 0.0, 0.0) and ambient == (0.0, 0.0, 0.0)


def test_project_to_plane_lands_every_vertex_on_the_plane():
    verts = np.array([[0.0, -100.0, 0.0], [50.0, -40.0, 20.0], [-30.0, 0.0, 10.0]])
    out = project_to_plane(verts, (0.0, 1.0, 0.0), 0.0)
    assert np.allclose(out[:, 1], 0.0)
    # a straight-down light drops each vertex straight down
    assert np.allclose(out[:, [0, 2]], verts[:, [0, 2]])


def test_project_to_plane_throws_the_shadow_along_the_light():
    verts = np.array([[0.0, -100.0, 0.0]])
    travel = np.array([1.0, 1.0, 0.0]) / np.sqrt(2.0)
    out = project_to_plane(verts, travel, 0.0)
    assert out[0] == pytest.approx([100.0, 0.0, 0.0])


def test_an_estimated_light_cannot_throw_the_shadow_to_the_horizon():
    # MIN_UP bounds the light's slope, so the horizontal throw is bounded by
    # construction: no per-vertex clamp is needed anywhere downstream.
    plate = _plate()
    plate[100:110, 300:320] = 255
    travel = -np.array(estimate_light(plate).direction)
    verts = np.array([[0.0, -100.0, 0.0]])
    out = project_to_plane(verts, travel, 0.0)
    assert np.linalg.norm(out[0, [0, 2]]) <= 100.0 * np.sqrt(1 - MIN_UP ** 2) / MIN_UP


def test_project_to_plane_with_a_flat_light_is_a_no_op():
    verts = np.array([[0.0, -100.0, 0.0]])
    assert np.allclose(project_to_plane(verts, (1.0, 0.0, 0.0), 0.0), verts)


def test_legacy_light_is_the_old_hard_coded_rig():
    assert np.isclose(np.linalg.norm(LEGACY_LIGHT.direction), 1.0)
    assert LEGACY_LIGHT.key == (0.45, 0.45, 0.45)
    assert LEGACY_LIGHT.ambient == (0.55, 0.55, 0.55)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_lighting.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'PyAitD.render.lighting'`.

- [ ] **Step 3: Write the module**

Create `PyAitD/render/lighting.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""A per-camera light estimated from that camera's background image, and the
ground-plane projection the shadow pass uses.

The AITD1 data files carry no light information at all -- a Camera has a
position, three angles and three focal lengths, and nothing else -- so the
only evidence about how a room is lit is the picture of the room. This
module reads that picture.

Conventions, which everything downstream depends on:

- Camera-space y grows *downward* (world.CameraState.project computes
  `sy = y * focal3 / depth + SCREEN_CENTER_Y` with no sign flip), and +z
  points away from the camera into the scene (`depth = z + focal1`).
- `SceneLight.direction` points *from the surface toward the light*, so a
  light above the scene has a negative y and a light in front of it has a
  negative z. The direction light *travels* is `-direction`.

Pure numpy: no pygame, no GL, no engine imports."""
from dataclasses import dataclass

import numpy as np

# Rec. 709 luma weights: perceived brightness, not a channel average.
LUMA = np.array([0.2126, 0.7152, 0.0722])

# The light is forced to sit at least this far above the scene. A light
# level with the floor projects a shadow to the horizon; this bound also
# caps the horizontal throw at sqrt(1 - MIN_UP^2) / MIN_UP times the drop
# (about 2.7x), which is why project_to_plane needs no clamp of its own.
MIN_UP = 0.35
# A fixed toward-the-viewer component, so the light can never degenerate
# into pure sidelight that rakes every surface at once.
FORWARD = 0.8
# What counts as "the lit part" and "the shadowed part" of a plate.
BRIGHT_FRACTION = 0.10
DARK_FRACTION = 0.25
# Below this, the bright centroid is noise (a uniform plate's brightest
# decile is whichever pixels argsort happened to put last), so it is
# discarded in favour of a frontal light.
CONTRAST_FLOOR = 0.02


@dataclass(frozen=True)
class SceneLight:
    direction: tuple    # unit, camera space, pointing from surface toward light
    key: tuple          # 0..1 linear RGB: what a lit surface in this room looks like
    ambient: tuple      # 0..1 linear RGB: what an unlit one looks like
    contrast: float     # 0..1: how directional this room's light is


def _unit(vec):
    vec = np.asarray(vec, dtype=np.float64)
    length = float(np.linalg.norm(vec))
    return tuple(vec / length) if length else (0.0, -1.0, 0.0)


# The rig GLBackend used before this module existed. Its y is negative, so by
# the convention above it was already an "above the scene" light -- but the
# old shader took abs() of the dot product, so the sign never actually
# mattered, which is exactly why the old lighting had no lit and dark side.
# Kept as FrameDescription.light's default so frames built without a resolver
# still carry a usable light.
LEGACY_LIGHT = SceneLight(_unit((-0.3, -0.5, -0.8)), (0.45,) * 3, (0.55,) * 3, 0.45)


def estimate_light(pixels):
    """A SceneLight for a camera, read off its background image."""
    image = np.asarray(pixels)
    height, width = image.shape[:2]
    rgb = image.reshape(-1, 3).astype(np.float64) / 255.0
    luma = rgb @ LUMA

    order = np.argsort(luma)
    count = len(order)
    bright = order[-max(1, int(count * BRIGHT_FRACTION)):]
    dark = order[:max(1, int(count * DARK_FRACTION))]

    key = tuple(rgb[bright].mean(axis=0))
    ambient = tuple(rgb[dark].mean(axis=0))

    bright_luma = float(luma[bright].mean())
    dark_luma = float(luma[dark].mean())
    contrast = (0.0 if bright_luma <= 0.0
                else float(np.clip((bright_luma - dark_luma) / bright_luma, 0.0, 1.0)))

    weights = luma[bright]
    total = float(weights.sum())
    if contrast < CONTRAST_FLOOR or total <= 0.0:
        offset_x = offset_y = 0.0
    else:
        rows, cols = np.divmod(bright, width)
        offset_x = float((cols * weights).sum() / total) / width * 2.0 - 1.0
        offset_y = float((rows * weights).sum() / total) / height * 2.0 - 1.0

    # min(), not max(): y grows downward, so "at least MIN_UP above" is
    # "no greater than -MIN_UP".
    direction = _unit((offset_x, min(offset_y, -MIN_UP), -FORWARD))
    return SceneLight(direction, key, ambient, contrast)


def shading_terms(light):
    """`(key, ambient)` multipliers for the shader: unit-mean tints carrying
    the room's hue, split by contrast into a directional share and a fill
    share that sum to roughly 1.

    Keeping the sum near 1 is what stops a lit surface from drifting far
    from its palette colour: a fully lit face lands near `ambient + key == 1`
    and an unlit one falls to the fill share alone, which is the same
    0.55-to-1.0 band the old fixed rig produced."""
    weight = 0.25 + 0.5 * float(np.clip(light.contrast, 0.0, 1.0))
    key = np.asarray(light.key, dtype=np.float64)
    ambient = np.asarray(light.ambient, dtype=np.float64)
    key_mean = float(key.mean())
    ambient_mean = float(ambient.mean())
    # A pitch-black plate has no hue to preserve and no light to give: it
    # stays black rather than being normalised into a division by zero.
    key = key / key_mean * weight if key_mean > 0.0 else key
    ambient = ambient / ambient_mean * (1.0 - weight) if ambient_mean > 0.0 else ambient
    return tuple(key), tuple(ambient)


def project_to_plane(vertices, travel, plane_y):
    """Slide each vertex along `travel` onto the horizontal plane `y == plane_y`.

    `travel` is the direction light *travels* (`-SceneLight.direction`), in
    the same space as `vertices`. A `travel` with no vertical component
    casts no shadow at all, and the vertices come back unmoved; an estimated
    light can never be in that state, because estimate_light clamps its
    vertical component to at least MIN_UP."""
    verts = np.asarray(vertices, dtype=np.float64).reshape(-1, 3)
    travel = np.asarray(travel, dtype=np.float64)
    if travel[1] == 0.0:
        return verts.copy()
    steps = (plane_y - verts[:, 1]) / travel[1]
    return verts + steps[:, None] * travel
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_lighting.py -q`
Expected: PASS, 13 tests.

- [ ] **Step 5: Run the layering and full suites**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/ -q`
Expected: PASS. `tests/test_layering.py` must stay green — `lighting.py` imports only numpy.

- [ ] **Step 6: Commit**

```bash
git add PyAitD/render/lighting.py tests/test_lighting.py
git commit -m "feat: estimate a scene light from a camera background image"
```

---

### Task 3: Carry the light through the resolver and the frame

**Files:**
- Modify: `PyAitD/render/asset_resolver.py:41-48` (`__init__`), and a new `light` method after `palette`
- Modify: `PyAitD/render/scene.py:98-112` (`FrameDescription`), `PyAitD/render/scene.py:167-173` (`build_frame`'s construction)
- Test: `tests/test_asset_resolver.py`, `tests/test_scene.py`

**Interfaces:**
- Consumes: `estimate_light(pixels) -> SceneLight`, `LEGACY_LIGHT` from `PyAitD.render.lighting`.
- Produces: `AssetResolver.light(floor, cam_idx) -> SceneLight`; `FrameDescription.light: SceneLight`, defaulting to `LEGACY_LIGHT`.

**Note on the default:** `light` is the **last** field of `FrameDescription` and carries a default. Three test files (`tests/test_render_gl.py:42`, `tests/test_render_soft.py:39`, `tests/test_render.py:238`) construct frames positionally with five arguments; the default is what keeps them working unedited.

- [ ] **Step 1: Write the failing tests**

In `tests/test_asset_resolver.py`, add:

```python
def test_light_is_estimated_once_per_camera():
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
    first = resolver.light(floor, 0)
    second = resolver.light(floor, 0)
    assert first is second
    assert calls == [0]                     # one decode, one estimate
    assert first.direction[1] < 0           # a bright ceiling band lights from above


def test_light_follows_an_override_background(tmp_path):
    from PyAitD.render.asset_resolver import override_background_path
    path = override_background_path(tmp_path, 3, 0)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"")                   # content comes from the stub loader below
    bright_left = np.zeros((200, 320, 3), np.uint8)
    bright_left[:, :40] = 255
    resolver = AssetResolver(None, tmp_path, load_png=lambda p: bright_left)
    light = resolver.light(_floor(), 0)
    assert light.direction[0] < 0           # estimated from the override, not the flat original
```

In `tests/test_scene.py`, add a non-gated test:

```python
def test_software_backend_ignores_the_scene_light():
    # The spec keeps the software fallback flat and unlit. Nothing in that
    # path may start reading frame.light by accident.
    from PyAitD.render.lighting import SceneLight
    from PyAitD.render.render_soft import SoftwareBackend
    view = CameraView(CameraState(0, 0, 0, 0, 0, 0, 1000, 320, 320).angles())
    plate = np.full((200, 320, 3), 90, np.uint8)
    plain = FrameDescription(view, ImageAsset(plate, False), np.zeros((256, 3), np.uint8), (), ())
    wild = FrameDescription(view, ImageAsset(plate, False), np.zeros((256, 3), np.uint8), (), (),
                            SceneLight((0.9, -0.4, -0.2), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0), 1.0))
    assert np.array_equal(SoftwareBackend().draw(plain), SoftwareBackend().draw(wild))


def test_frame_description_defaults_to_the_legacy_light():
    from PyAitD.render.lighting import LEGACY_LIGHT
    frame = FrameDescription(
        CameraView(CameraState(0, 0, 0, 0, 0, 0, 1000, 320, 320).angles()),
        None, None, (), (),
    )
    assert frame.light is LEGACY_LIGHT
```

Both need `import numpy as np` and `from PyAitD.render.asset_resolver import ImageAsset` at the top of `tests/test_scene.py`; add whichever is missing.

Then extend the existing gated `test_build_frame_matches_legacy_order_and_draw_list` with:

```python
    resolver = AssetResolver(game.assets)
    frame, draw_list = build_frame(game, floor, resolver)
    room = floor.rooms[game.current_room]
    assert frame.light is resolver.light(floor, room.camera_indices[game.num_camera])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_asset_resolver.py tests/test_scene.py -q`
Expected: FAIL with `AttributeError: 'AssetResolver' object has no attribute 'light'`.

- [ ] **Step 3: Add `AssetResolver.light`**

In `PyAitD/render/asset_resolver.py`, import the estimator at the top:

```python
from PyAitD.render.lighting import estimate_light
```

Add the cache in `__init__`, beside `self._cache`:

```python
        self._lights = {}
```

Add the method directly after `palette`:

```python
    def light(self, floor, cam_idx):
        """The SceneLight for a camera, estimated from whatever background
        that camera actually resolves to -- an override, including an
        AI-regenerated plate, is estimated from the override rather than
        from the original.

        Memoised per (floor, camera) exactly as backgrounds are: a camera's
        light is a property of a static image, so one estimate per camera
        per session is all this can ever need."""
        key = (floor.number, cam_idx)
        if key not in self._lights:
            self._lights[key] = estimate_light(self.background(floor, cam_idx).pixels)
        return self._lights[key]
```

- [ ] **Step 4: Put the light on the frame**

In `PyAitD/render/scene.py`, import the default:

```python
from PyAitD.render.lighting import LEGACY_LIGHT
```

Add the field last on `FrameDescription`:

```python
    masks: tuple[MaskDraw, ...]
    light: object = LEGACY_LIGHT
```

and fill it in `build_frame`:

```python
    frame = FrameDescription(
        CameraView(state),
        resolver.background(floor, cam_idx),
        resolver.palette(floor),
        tuple(actors),
        masks,
        resolver.light(floor, cam_idx),
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/ -q`
Expected: PASS. Nothing reads `frame.light` yet, so no rendered pixel changes.

- [ ] **Step 6: Commit**

```bash
git add PyAitD/render/asset_resolver.py PyAitD/render/scene.py tests/
git commit -m "feat: carry a per-camera scene light through the resolver and frame"
```

---

### Task 4: The scene diffuse term

**Files:**
- Modify: `PyAitD/render/render_gl.py:74-88` (`_ACTOR_FSH`), `PyAitD/render/render_gl.py:210-213` (`_screen_prog` setup), `PyAitD/render/render_gl.py:305-325` (`_draw_frame`'s uniform block)
- Test: `tests/test_render_gl.py`

**Interfaces:**
- Consumes: `SceneLight`, `shading_terms(light) -> (key, ambient)`.
- Produces: nothing new for later tasks; the shadow pass reads `frame.light` itself.

- [ ] **Step 1: Write the failing tests**

In `tests/test_render_gl.py`, add:

```python
def _lit_frame(actors, direction):
    from PyAitD.render.lighting import SceneLight
    light = SceneLight(direction, (1.0, 1.0, 1.0), (0.2, 0.2, 0.2), 1.0)
    return FrameDescription(_view(), ImageAsset(np.zeros((200, 320, 3), np.uint8), False),
                            _palette(), tuple(actors), (), light)


def _facing_tri(z, color, normal):
    span = 400.0
    v = np.array([[-span, -span, z], [span, -span, z], [-span, span, z]], np.float32)
    n = np.tile(normal, (3, 1)).astype(np.float32)
    return BodyGeometry(v, n, np.array([[0, 1, 2]], np.int32), np.array([color], np.uint8),
                        np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), (),
                        np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))


def test_fixed_lighting_is_unchanged_by_the_scene_light(gl_ctx):
    # The regression net: with lighting="fixed" the frame's light is ignored
    # entirely, so a wild SceneLight cannot move a single pixel.
    options = RenderOptions(scale=1, shading="smooth", lighting="fixed")
    backend = GLBackend(gl_ctx, options)
    actor = _actor(0, _facing_tri(600.0, 1, (0.0, 0.0, -1.0)))
    backend.draw(_frame([actor]))
    plain = backend.read_rgb().copy()
    backend.draw(_lit_frame([actor], (0.9, -0.3, -0.3)))
    assert np.array_equal(backend.read_rgb(), plain)
    backend.release()


def test_scene_lighting_gives_a_face_a_lit_and_a_dark_side(gl_ctx):
    # What abs(dot(N, L)) could never do: two faces with opposite normals
    # under one light must not come out the same brightness.
    options = RenderOptions(scale=1, shading="smooth", lighting="scene")
    backend = GLBackend(gl_ctx, options)
    toward = _lit_frame([_actor(0, _facing_tri(600.0, 1, (0.0, -1.0, 0.0)))], (0.0, -1.0, 0.0))
    away = _lit_frame([_actor(0, _facing_tri(600.0, 1, (0.0, 1.0, 0.0)))], (0.0, -1.0, 0.0))
    backend.draw(toward)
    lit = backend.read_rgb().astype(int).max()
    backend.draw(away)
    dark = backend.read_rgb().astype(int).max()
    assert lit > dark + 20
    backend.release()


def test_scene_lighting_never_goes_below_the_rooms_ambient(gl_ctx):
    # The dark side falls to the room's fill light, not to black: an actor
    # in shadow is still visible against the plate.
    options = RenderOptions(scale=1, shading="smooth", lighting="scene")
    backend = GLBackend(gl_ctx, options)
    away = _lit_frame([_actor(0, _facing_tri(600.0, 1, (0.0, 1.0, 0.0)))], (0.0, -1.0, 0.0))
    backend.draw(away)
    assert backend.read_rgb().astype(int).max() > 0
    backend.release()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q -k "scene_lighting or fixed_lighting"`
Expected: FAIL — `test_scene_lighting_gives_a_face_a_lit_and_a_dark_side` fails because `abs()` makes both sides equal. (`test_fixed_lighting_is_unchanged_by_the_scene_light` may already pass; it is the pin that must keep passing, not a driver of the change.)

- [ ] **Step 3: Rewrite the actor fragment shader**

Replace `_ACTOR_FSH` in `PyAitD/render/render_gl.py`:

```python
_ACTOR_FSH = """
#version 330
uniform int shading; uniform int lighting;
uniform vec3 light; uniform vec3 key; uniform vec3 ambient;
uniform sampler2D mask_tex; uniform vec2 target_size;
in vec3 v_color; in vec3 v_normal; out vec4 f_color;
void main() {
    if (texture(mask_tex, gl_FragCoord.xy / target_size).r > 0.5) discard;
    if (shading == 0) {
        // unshaded: flat palette colour, and the only path lines and points take
        f_color = vec4(v_color, 1.0);
        return;
    }
    vec3 n = (shading == 1)
        ? normalize(cross(dFdx(gl_FragCoord.xyz), dFdy(gl_FragCoord.xyz)))
        : normalize(v_normal);
    vec3 l = normalize(light);
    if (lighting == 0) {
        // the pre-scene-light rig, kept byte-identical: abs() because FITD
        // polygons have no consistent winding
        f_color = vec4(v_color * (0.55 + 0.45 * abs(dot(n, l))), 1.0);
        return;
    }
    // Orient rather than fold: -z is toward the camera, so a normal with a
    // positive z faces away from the viewer and is pointing into the body.
    if (n.z > 0.0) n = -n;
    // Half-Lambert: the lit side reaches ambient + key, the shadow side
    // falls to ambient rather than to black.
    float wrapped = clamp(dot(n, l) * 0.5 + 0.5, 0.0, 1.0);
    f_color = vec4(v_color * (ambient + key * wrapped * wrapped), 1.0);
}
"""
```

Note the `shading == 0` early return now short-circuits both lighting paths. That is what keeps `_screen_prog` (lines and points, which set `shading = 0`) unshaded under either mode; also set its `lighting` uniform explicitly so it never reads an uninitialised value:

```python
            self._screen_prog["shading"].value = 0  # lines/points are never shaded
            self._screen_prog["lighting"].value = 0
```

- [ ] **Step 4: Set the uniforms per frame**

Import the helper at the top of `render_gl.py`:

```python
from PyAitD.render.lighting import shading_terms
```

In `_draw_frame`, replace the single `light` assignment with:

```python
        self._actor_prog["shading"].value = _SHADING_INDEX[self._options.shading]
        if self._options.lighting == "scene":
            key, ambient = shading_terms(frame.light)
            self._actor_prog["lighting"].value = 1
            self._actor_prog["light"].value = tuple(float(v) for v in frame.light.direction)
            self._actor_prog["key"].value = tuple(float(v) for v in key)
            self._actor_prog["ambient"].value = tuple(float(v) for v in ambient)
        else:
            self._actor_prog["lighting"].value = 0
            self._actor_prog["light"].value = LIGHT_DIR
            self._actor_prog["key"].value = (0.0, 0.0, 0.0)
            self._actor_prog["ambient"].value = (0.0, 0.0, 0.0)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q`
Expected: PASS, including every pre-existing pixel assertion — those all run under the default `lighting="fixed"`.

- [ ] **Step 6: Run the full suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add PyAitD/render/render_gl.py tests/test_render_gl.py
git commit -m "feat: a real diffuse term for the estimated scene light"
```

---

### Task 5: The shadow pass

**Files:**
- Modify: `PyAitD/render/render_gl.py` — shader sources near line 100, `__init__`'s allocation block (lines 176-256), `release` (lines 257-274), `_draw_frame` (lines 305-350), and two new methods beside `_rasterize_masks`
- Test: `tests/test_render_gl.py`

**Interfaces:**
- Consumes: `project_to_plane(vertices, travel, plane_y)`, `rotation_matrix(state)` (already in this module), `frame.light`.
- Produces: nothing for later tasks.

**Geometry notes:**
- `rotation_matrix(frame.camera.state)` maps world space into camera space, and is orthonormal, so its transpose maps camera space back into world space. The light's world-space travel direction is `rotation_matrix(state).T @ direction`, negated.
- `actor.zv` is `[x1, x2, y1, y2, z1, z2]`. World y grows downward, so the ground under an actor is `max(zv[2], zv[3])`.
- Only `geometry.tris` is projected. Spheres, lines and points are not part of a body's silhouette in any useful sense and are skipped.
- Actors are composited in painter order with no shared depth buffer, so a later actor's shadow falls over an earlier actor's pixels as readily as over the background. That is the same ordering rule the actors themselves already follow, and it is why the shadow composite belongs inside the per-actor loop rather than being batched before them.

- [ ] **Step 1: Write the failing tests**

In `tests/test_render_gl.py`, add:

```python
def _standing_actor(index, geometry, feet_y):
    zv = (0, 0, feet_y - 200, feet_y, 0, 0)
    return ActorDraw(index, geometry, (0.0, 0.0, 0.0), 0, zv, RenderResult([], []), ())


def _lit_scene_backend(gl_ctx):
    return GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene"))


def test_a_shadow_darkens_the_ground_below_the_actor_only(gl_ctx):
    backend = _lit_scene_backend(gl_ctx)
    plate = np.full((200, 320, 3), 200, np.uint8)
    geometry = _tri_geometry(600.0, 1, span=100.0)
    actor = _standing_actor(0, geometry, feet_y=150)
    light = _scene_light((0.0, -1.0, -0.2))
    frame = FrameDescription(_view(), ImageAsset(plate, False), _palette(), (actor,), (), light)
    backend.draw(frame)
    rendered = backend.read_rgb().astype(int)
    plain = _plain_background(gl_ctx, plate)
    # somewhere below the actor's feet the plate got darker...
    assert (rendered[120:, :] < plain[120:, :] - 5).any()
    # ...and nothing above the top of the frame did
    assert (rendered[:5, :] >= plain[:5, :] - 1).all()
    backend.release()


def test_overlapping_shadow_triangles_darken_a_pixel_once(gl_ctx):
    # Coverage is binary: two limbs crossing must not stack into a black
    # blob. This is the whole reason the pass goes through a texture.
    backend = _lit_scene_backend(gl_ctx)
    plate = np.full((200, 320, 3), 200, np.uint8)
    single = _standing_actor(0, _tri_geometry(600.0, 1, span=100.0), feet_y=150)
    doubled = _standing_actor(0, _doubled_tri_geometry(600.0, 1, span=100.0), feet_y=150)
    light = _scene_light((0.0, -1.0, -0.2))
    backend.draw(FrameDescription(_view(), ImageAsset(plate, False), _palette(), (single,), (), light))
    once = backend.read_rgb().astype(int)
    backend.draw(FrameDescription(_view(), ImageAsset(plate, False), _palette(), (doubled,), (), light))
    twice = backend.read_rgb().astype(int)
    assert np.array_equal(once, twice)
    backend.release()


def test_a_foreground_mask_erases_the_shadow_under_it(gl_ctx):
    backend = _lit_scene_backend(gl_ctx)
    plate = np.full((200, 320, 3), 200, np.uint8)
    actor = _standing_actor(0, _tri_geometry(600.0, 1, span=100.0), feet_y=150)
    masked = ActorDraw(actor.index, actor.geometry, actor.position, actor.room, actor.zv,
                       actor.logical, (0,))
    full = MaskDraw(0, (np.array([[0, 0], [320, 0], [320, 200], [0, 200]], np.int16),),
                    (0, 0, 320, 200), 0, ())
    light = _scene_light((0.0, -1.0, -0.2))
    frame = FrameDescription(_view(), ImageAsset(plate, False), _palette(), (masked,), (full,), light)
    backend.draw(frame)
    assert np.array_equal(backend.read_rgb(), _plain_background(gl_ctx, plate))
    backend.release()


def test_fixed_lighting_casts_no_shadow(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="fixed"))
    plate = np.full((200, 320, 3), 200, np.uint8)
    actor = _standing_actor(0, _tri_geometry(600.0, 1, span=100.0), feet_y=150)
    light = _scene_light((0.0, -1.0, -0.2))
    with_light = FrameDescription(_view(), ImageAsset(plate, False), _palette(), (actor,), (), light)
    backend.draw(with_light)
    lit = backend.read_rgb().copy()
    backend.draw(_frame([actor], background=plate))
    assert np.array_equal(backend.read_rgb(), lit)
    backend.release()
```

Add these helpers near the other builders at the top of the file:

```python
def _scene_light(direction):
    from PyAitD.render.lighting import SceneLight
    return SceneLight(direction, (1.0, 1.0, 1.0), (0.1, 0.1, 0.1), 1.0)


def _doubled_tri_geometry(z, color, span):
    """One triangle drawn twice: identical coverage, two overlapping draws."""
    base = _tri_geometry(z, color, span)
    return BodyGeometry(
        base.vertices, base.normals,
        np.array([[0, 1, 2], [0, 1, 2]], np.int32), np.array([color, color], np.uint8),
        base.lines, base.line_colors, base.spheres,
        base.points, base.point_sizes, base.point_colors)


def _plain_background(gl_ctx, plate):
    """The same plate with no actors at all: the baseline a shadow darkens."""
    empty = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene"))
    empty.draw(FrameDescription(_view(), ImageAsset(plate, False), _palette(), (), ()))
    out = empty.read_rgb().astype(int)
    empty.release()
    return out
```

In `test_a_construction_failure_releases_everything_allocated_so_far`, extend
the `for attr in (...)` tuple with the six new resources and raise the count.
The loop body is unchanged; only the tuple and the final assertion move:

```python
    for attr in (
        "texture", "_depth", "_fbo", "_mask_tex", "_mask_fbo",
        "_shadow_tex", "_shadow_fbo", "_shadow_prog", "_shadow_geom_prog",
        "_shadow_quad", "_shadow_quad_vao",
        "_bg_prog", "_actor_prog", "_screen_prog", "_stencil_prog",
        "_quad", "_quad_vao", "_thumb_tex", "_thumb_fbo",
        "_thumb_quad", "_thumb_quad_vao",
    ):
        resource = getattr(backend, attr)
        assert resource is not None, f"{attr} was never allocated before the failure"
        assert isinstance(resource.mglo, moderngl.InvalidObject), f"{attr} leaked (not released)"
        leak_checked += 1
    assert leak_checked == 21  # every GL resource __init__ allocates, none skipped
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q -k shadow`
Expected: FAIL — no shadow is drawn, so the plate is unchanged beneath the actor.

- [ ] **Step 3: Add the shadow programs**

In `PyAitD/render/render_gl.py`, add beside `_STENCIL_VSH`:

```python
_SHADOW_GEOM_VSH = """
#version 330
uniform mat4 mvp;
in vec3 in_pos;
void main() { gl_Position = mvp * vec4(in_pos, 1.0); }
"""
_SHADOW_FSH = """
#version 330
uniform sampler2D shadow_tex; uniform sampler2D mask_tex;
uniform vec2 target_size; uniform vec3 shadow_color; uniform float opacity;
out vec4 f_color;
void main() {
    vec2 uv = gl_FragCoord.xy / target_size;
    // A foreground mask hides the shadow exactly as it hides the actor.
    if (texture(mask_tex, uv).r > 0.5) discard;
    // Coverage is binary, so overlapping limbs darken a pixel once.
    if (texture(shadow_tex, uv).r < 0.5) discard;
    f_color = vec4(shadow_color, opacity);
}
"""
```

- [ ] **Step 4: Allocate and release the shadow resources**

In `__init__`, add to the up-front `None` block:

```python
        self._shadow_tex = None
        self._shadow_fbo = None
        self._shadow_prog = None
        self._shadow_geom_prog = None
        self._shadow_quad = None
        self._shadow_quad_vao = None
```

and inside the `try`, after the mask FBO:

```python
            self._shadow_tex = ctx.texture(self.size, 1)
            self._shadow_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            self._shadow_tex.repeat_x = False
            self._shadow_tex.repeat_y = False
            self._shadow_fbo = ctx.framebuffer(color_attachments=[self._shadow_tex])
            self._shadow_geom_prog = ctx.program(
                vertex_shader=_SHADOW_GEOM_VSH, fragment_shader=_STENCIL_FSH)
            self._shadow_prog = ctx.program(
                vertex_shader=_STENCIL_VSH, fragment_shader=_SHADOW_FSH)
            # A full-target triangle pair in NDC. `_quad` cannot be reused:
            # it carries interleaved UVs the shadow composite has no
            # attribute for.
            shadow_quad = np.array([
                -1, -1,  1, -1,  1, 1,
                -1, -1,  1,  1, -1, 1,
            ], dtype="f4")
            self._shadow_quad = ctx.buffer(shadow_quad.tobytes())
            self._shadow_quad_vao = ctx.vertex_array(
                self._shadow_prog, [(self._shadow_quad, "2f", "in_pos")])
```

In `release`, add them to the tuple, before the mask entries:

```python
            self._shadow_quad_vao, self._shadow_quad,
            self._shadow_prog, self._shadow_geom_prog,
            self._shadow_fbo, self._shadow_tex,
```

- [ ] **Step 5: Draw the shadow**

Add these two methods immediately after `_rasterize_masks`:

```python
    def _rasterize_shadow(self, actor, travel, mvp):
        """This actor's triangles, flattened onto the ground plane beneath it,
        into the single-channel coverage texture.

        The plane is the actor's own zv lower bound -- world y grows
        downward, so the feet are the larger of the two y bounds. It travels
        with the actor, which is why a shadow never detaches in mid-air; see
        the spec's Limitations."""
        self._shadow_fbo.use()
        self._ctx.viewport = (0, 0, *self.size)
        self._ctx.disable(moderngl.DEPTH_TEST)
        self._shadow_fbo.clear(0.0, 0.0, 0.0, 0.0)
        geometry = actor.geometry
        if not len(geometry.tris):
            return
        plane_y = float(max(actor.zv[2], actor.zv[3]))
        world = geometry.vertices.astype(np.float64) + np.asarray(actor.position, np.float64)
        flat = project_to_plane(world, travel, plane_y)
        verts = flat[geometry.tris.reshape(-1)].astype("f4")
        self._shadow_geom_prog["mvp"].write(mvp.T.astype("f4").tobytes())
        buf = self._ctx.buffer(np.ascontiguousarray(verts).tobytes())
        vao = self._ctx.vertex_array(self._shadow_geom_prog, [(buf, "3f", "in_pos")])
        vao.render(moderngl.TRIANGLES)
        vao.release()
        buf.release()

    def _composite_shadow(self, light):
        """Blend the coverage texture over the background as the room's own
        ambient colour: a shadowed floor still shows the fill light, so the
        result can never go darker than the room's own shadows do."""
        self._target.use()
        self._ctx.viewport = (0, 0, *self.size)
        self._ctx.disable(moderngl.DEPTH_TEST)
        self._shadow_tex.use(location=2)
        self._mask_tex.use(location=1)
        self._shadow_prog["shadow_tex"].value = 2
        self._shadow_prog["mask_tex"].value = 1
        self._shadow_prog["target_size"].value = self.size
        self._shadow_prog["shadow_color"].value = tuple(float(c) for c in light.ambient)
        self._shadow_prog["opacity"].value = float(0.25 + 0.45 * light.contrast)
        self._ctx.enable(moderngl.BLEND)
        self._shadow_quad_vao.render(moderngl.TRIANGLES)
        self._ctx.disable(moderngl.BLEND)
```

`self._target` is introduced in Task 6; until then, add `self._target = self._fbo` at the end of `__init__`'s `try` block so both tasks read the same name.

In `_draw_frame`, compute the world-space travel direction once per frame, right after `rot`:

```python
        scene_lit = self._options.lighting == "scene"
        # rotation_matrix maps world -> camera and is orthonormal, so its
        # transpose maps back. `direction` points toward the light; light
        # travels the other way.
        travel = -(rot.astype(np.float64).T @ np.asarray(frame.light.direction, np.float64))
```

and inside the per-actor loop, between the mask rasterisation and the depth clear:

```python
            self._rasterize_masks(masks)  # switches to the mask FBO and disables depth test

            if scene_lit:
                self._rasterize_shadow(actor, travel, mvp)
                self._composite_shadow(frame.light)

            self._target.use()
```

Import the projection at the top of the module:

```python
from PyAitD.render.lighting import project_to_plane, shading_terms
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q`
Expected: PASS, leak test included.

- [ ] **Step 7: Run the full suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add PyAitD/render/render_gl.py tests/test_render_gl.py
git commit -m "feat: project each actor's silhouette as a ground shadow"
```

---

### Task 6: Multisampling

**Files:**
- Modify: `PyAitD/render/render_gl.py` — `__init__`, `release`, `_draw_frame`
- Test: `tests/test_render_gl.py`

**Interfaces:**
- Consumes: `RenderOptions.msaa`.
- Produces: `GLBackend._target` — the framebuffer every draw call renders into, which is the multisample FBO when `msaa` is on and `_fbo` when it is off. `self.texture` remains the single-sampled result every reader already uses.

- [ ] **Step 1: Write the failing tests**

In `tests/test_render_gl.py`, add:

```python
def test_msaa_resolves_into_the_same_texture(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat", msaa=4))
    assert backend.size == (320, 200)
    plate = np.full((200, 320, 3), 40, np.uint8)
    backend.draw(_frame([_actor(0, _tri_geometry(600.0, 1))], background=plate))
    rendered = backend.read_rgb()
    assert rendered.shape == (200, 320, 3)
    assert rendered.max() > 0                      # something actually landed
    assert backend.thumbnail().shape == (200, 320, 3)
    backend.release()


def test_msaa_softens_a_diagonal_edge(gl_ctx):
    # The whole point: with multisampling the silhouette gains intermediate
    # values along its diagonal that a single-sampled render cannot produce.
    plate = np.zeros((200, 320, 3), np.uint8)
    frame = _frame([_actor(0, _tri_geometry(600.0, 1))], background=plate)

    def edge_values(msaa):
        backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat", msaa=msaa))
        backend.draw(frame)
        red = backend.read_rgb()[:, :, 0].astype(int)
        backend.release()
        return red

    aliased, smoothed = edge_values(0), edge_values(4)
    partial = ((smoothed > 0) & (smoothed < 255)).sum()
    assert partial > ((aliased > 0) & (aliased < 255)).sum()


def test_msaa_is_clamped_to_what_the_context_supports(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat", msaa=8))
    assert backend.samples <= gl_ctx.max_samples
    backend.release()


def test_msaa_zero_keeps_the_single_sampled_path(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat", msaa=0))
    assert backend.samples == 0
    assert backend._target is backend._fbo
    assert backend._ms_fbo is None
    backend.release()
```

In `test_a_construction_failure_releases_everything_allocated_so_far`, pin
multisampling on in the options it constructs, so the three new resources are
actually allocated before the induced failure:

```python
        backend.__init__(gl_ctx, RenderOptions(scale=8, shading="flat", msaa=4))
```

then extend the tuple and the count again (the loop body is unchanged):

```python
    for attr in (
        "texture", "_depth", "_fbo", "_mask_tex", "_mask_fbo",
        "_shadow_tex", "_shadow_fbo", "_shadow_prog", "_shadow_geom_prog",
        "_shadow_quad", "_shadow_quad_vao",
        "_ms_color", "_ms_depth", "_ms_fbo",
        "_bg_prog", "_actor_prog", "_screen_prog", "_stencil_prog",
        "_quad", "_quad_vao", "_thumb_tex", "_thumb_fbo",
        "_thumb_quad", "_thumb_quad_vao",
    ):
        resource = getattr(backend, attr)
        assert resource is not None, f"{attr} was never allocated before the failure"
        assert isinstance(resource.mglo, moderngl.InvalidObject), f"{attr} leaked (not released)"
        leak_checked += 1
    assert leak_checked == 24  # every GL resource __init__ allocates, none skipped
```

The `icosphere` monkeypatch that induces the failure fires after the
multisample block, so all three are allocated by then. If `_sphere`'s
allocation is ever moved above them, this test is what catches it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q -k msaa`
Expected: FAIL with `AttributeError: 'GLBackend' object has no attribute 'samples'`.

- [ ] **Step 3: Allocate the multisample target**

In `__init__`, add to the up-front `None` block:

```python
        self._ms_color = None
        self._ms_depth = None
        self._ms_fbo = None
        self._target = None
```

and inside the `try`, after the shadow resources and before `self._sphere = icosphere(1)`:

```python
            # A driver that supports fewer samples than asked gets what it
            # has rather than an exception: msaa is a quality knob, not a
            # requirement, and _select_backend would otherwise drop the
            # whole GL path to software over it.
            self.samples = min(options.msaa, ctx.max_samples) if options.msaa else 0
            if self.samples:
                self._ms_color = ctx.renderbuffer(self.size, 4, samples=self.samples)
                self._ms_depth = ctx.depth_renderbuffer(self.size, samples=self.samples)
                self._ms_fbo = ctx.framebuffer(
                    color_attachments=[self._ms_color], depth_attachment=self._ms_depth)
            self._target = self._ms_fbo or self._fbo
```

Set `self.samples = 0` in the up-front block too, so a construction failure before that line leaves the attribute defined.

Replace the `self._target = self._fbo` line added in Task 5 with this block.

In `release`, add before the `_fbo` entries:

```python
            self._ms_fbo, self._ms_color, self._ms_depth,
```

- [ ] **Step 4: Render into the target and resolve**

In `_draw_frame`, every drawing reference to `self._fbo` becomes `self._target`: the opening `use()`, the two `color_mask` assignments, the `clear(depth=1.0)`, and the `use()` calls inside the per-actor loop. `_composite_shadow` already uses `self._target`.

At the very end of `_draw_frame`, resolve:

```python
        if self._ms_fbo is not None:
            # Resolves the multisample buffer down into `.texture`, which is
            # what read_rgb, thumbnail and Renderer all read.
            self._ctx.copy_framebuffer(self._fbo, self._ms_fbo)
```

`draw`'s `finally` block already restores the caller's viewport and framebuffer, so nothing else changes.

- [ ] **Step 5: Default `msaa` to 4**

In `PyAitD/render/render_options.py`, change the dataclass default:

```python
    msaa: int = 4
```

Update `tests/test_render_options.py`'s `test_defaults` and the new option test to expect 4:

```python
def test_defaults():
    assert RenderOptions() == RenderOptions(4, "smooth", "bilinear", None, "fixed", 4)
```

and in `test_lighting_and_msaa_default_off_and_cycle`, change the two `msaa` expectations:

```python
    assert options.lighting == "fixed" and options.msaa == 4
    assert cycle_msaa(options).msaa == 8
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/ -q`
Expected: PASS. If any pre-existing GL pixel assertion fails, it is because it now runs multisampled — pin `msaa=0` in that test's `RenderOptions` rather than relaxing the assertion, since those tests are the `lighting="fixed"` regression net.

- [ ] **Step 7: Commit**

```bash
git add PyAitD/render/render_gl.py PyAitD/render/render_options.py tests/
git commit -m "feat: multisample the internal render target"
```

---

### Task 7: Turn scene lighting on by default, and document it

**Files:**
- Modify: `PyAitD/render/render_options.py`
- Modify: `README.md:69-78`, `CONTEXT.md:92-93`
- Test: `tests/test_render_options.py`

**Interfaces:**
- Consumes: everything above.
- Produces: the shipped default.

- [ ] **Step 1: Write the failing test**

In `tests/test_render_options.py`, update `test_defaults`:

```python
def test_defaults():
    assert RenderOptions() == RenderOptions(4, "smooth", "bilinear", None, "scene", 4)
    assert SHADING_MODES == ("flat", "lambert", "smooth")
    assert BACKGROUND_FILTERS == ("nearest", "bilinear", "xbr")
```

and in `test_lighting_and_msaa_default_off_and_cycle`, which is no longer about "off" — rename it and update:

```python
def test_lighting_and_msaa_defaults_and_cycles():
    from PyAitD.render.render_options import (
        LIGHTING_MODES, MSAA_LEVELS, cycle_lighting, cycle_msaa,
    )
    assert LIGHTING_MODES == ("fixed", "scene")
    assert MSAA_LEVELS == (0, 2, 4, 8)
    options = RenderOptions()
    assert options.lighting == "scene" and options.msaa == 4
    assert cycle_lighting(options).lighting == "fixed"
    assert cycle_msaa(options).msaa == 8
    assert cycle_msaa(RenderOptions(msaa=8)).msaa == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_options.py -q`
Expected: FAIL — the default is still `"fixed"`.

- [ ] **Step 3: Flip the default**

In `PyAitD/render/render_options.py`:

```python
    lighting: str = "scene"
```

- [ ] **Step 4: Run the full suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/ -q`
Expected: PASS. Any GL test that asserts specific pixels and did not pin `lighting` explicitly now renders scene-lit; pin `lighting="fixed"` in those tests rather than updating the expected pixels — they exist to prove the fixed path is unchanged.

- [ ] **Step 5: Update the docs**

In `README.md`, the paragraph beginning "The in-game Configuration screen's Graphics rows, and four CLI flags" becomes six flags; add after the `--background-filter` clause:

```
`--lighting {fixed,scene}` (`fixed` is the old hard-coded rig; `scene`
estimates each camera's light direction and colour from its own background
image and casts a ground shadow under every actor), `--msaa {0,2,4,8}`
(multisampling on the internal render target),
```

In `CONTEXT.md`, update the two render rows:

```
| `render/lighting.py` | `estimate_light(pixels) -> SceneLight`, `shading_terms`, `project_to_plane`: a per-camera light read off the background image, and the ground-plane projection the shadow pass uses; pygame/GL-free |
| `render/render_options.py` | `RenderOptions(scale, shading, background_filter, override_dir, lighting, msaa)`: validation, clamping, menu-cycle helpers; pygame/GL-free |
| `render/render_gl.py` | `GLBackend(ctx, options)`: ModernGL pipeline, per-actor depth, GPU mask-texture erasure, shading modes, estimated scene lighting, projected ground shadows, multisampling, background filtering |
```

- [ ] **Step 6: Commit**

```bash
git add PyAitD/render/render_options.py README.md CONTEXT.md tests/test_render_options.py
git commit -m "feat: scene lighting on by default"
```

---

## Manual verification

No test can judge whether this looks right. After Task 7, with game data present:

```bash
make run
```

Check, in order:

1. **The Configuration screen fits.** Open the system menu, go to Configuration: 14 rows, Lighting and AA present between Filter and Back, nothing clipped off the bottom, every row clickable at its label.
2. **Lighting: Scene vs Fixed.** Toggle the row and watch an actor. Under Scene the model should have a distinct lit and shadowed side; under Fixed it goes back to uniformly bright.
3. **Shadows.** Walk the hero across a lit room. There should be a shape-following shadow under them that turns with the animation, and it should vanish where a foreground pillar covers it.
4. **The estimate is sane per room.** Move between several cameras, including a dark one and a bright one. The shadow should be strong and hard in high-contrast rooms and faint in flat ones, and the light should not obviously contradict the background plate.
5. **AA.** Cycle AA between Off and 4x and look at an actor's silhouette against the background.

Record anything that reads wrong per room — that is the evidence for whether the authored-sidecar follow-up in the spec's Limitations is worth building.
