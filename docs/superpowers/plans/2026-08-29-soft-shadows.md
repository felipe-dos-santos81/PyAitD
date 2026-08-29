# Soft Shadows (Roadmap F) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every actor's ground shadow a penumbra that hardens at contact, composite every shadow once before any body is drawn, and let bodies shadow themselves and each other through one light-view depth map — all behind a `shadows` knob whose `hard` value runs today's code byte for byte.

**Architecture:** `GLBackend._draw_frame` builds every actor's instance buffer up front (level 0 now a legal instance draw). Under `shadows="soft"` it renders one orthographic depth map from the light over all instances, casts each actor's silhouette (mask-erased, with a per-pixel penumbra radius) into one RG coverage texture, softens it with a two-pass radius-driven blur, multiplies it onto the plate once, then draws bodies whose fragment shader scales the key's share by a PCF visibility lookup. Two pure numpy functions in `lighting.py` — `light_view_matrix` and `soften` — are the reference the GL passes are tested against, as `refine.evaluate` is for the tessellator.

**Tech Stack:** Python 3.12, numpy, ModernGL 5.12 (GL 3.3 core GLSL; `sampler2DShadow`, `MAX` blend equation, depth textures — all verified on the Apple GL 4.1 driver), pygame-ce, pytest.

**Spec:** `docs/superpowers/specs/2026-08-29-actor-realism-roadmap-design.md` (sections "The pipeline", "F. Shadows v2", "Options, UI and tooling", "Task ordering — F", "Testing — Identity net, F", "Limitations").

## Global Constraints

- `# SPDX-License-Identifier: GPL-2.0-only` is the first line of every Python file.
- `make test` (headless: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`) must be green after every task. No lint, formatter or typecheck exists; never mass-reformat.
- `classic + smoothing 0 + shadows hard + integration off` reproduces `tests/golden/scene_lit_classic.npy` byte for byte (`tests/test_render_gl.py::test_classic_realism_matches_the_pre_materials_golden`). `lighting="fixed"` renders byte-identically to today at every setting.
- `skel.skin()`, `draw_list`, picking, masks, the mouse contract, the software backend and the background filter/override system are untouched.
- Layering (`tests/test_layering.py`): `render/` imports only `engine`; only `render_gl`, `render_soft`, `render`, `asset_resolver` may import pygame/moderngl. `lighting.py` and the new `glsl.py` are pygame/GL-free.
- Every option mirrors `lighting` exactly: tuple of legal values, validate-and-clamp, `to_payload`, `cycle_*`, a Graphics row, `shell._MENU_RENDER_FIELDS`, a session-only CLI flag, a settings-v2 key.
- The Graphics page's rows stay ≥ 13 px tall (the 12×12 hit-target contract).
- The new knob lands as `hard` and flips to `soft` only in Task 6.
- Run tests with the venv interpreter: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest ...`. Every `make test-*` target already sets those variables.
- Commit messages end with the trailer block the repo uses (`Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` and the session line) when authored with Claude; plain messages otherwise.

---

## File structure

| File | Responsibility | Task |
|---|---|---|
| `PyAitD/render/glsl.py` (new) | Every GLSL source as a plain string; no imports, no logic | 1, 4, 5 |
| `PyAitD/render/render_gl.py` | The pipeline: resources, passes, per-frame loop; imports the strings under its underscore names | 1, 3, 4, 5 |
| `PyAitD/render/render_options.py` | `SHADOW_MODES`, `RenderOptions.shadows`, validation, `cycle_shadows` | 2, 6 |
| `PyAitD/render/lighting.py` | `SHADOW_MAP_SIZE`, `light_view_matrix`, `soften` (pure numpy twins) | 3 |
| `PyAitD/app/ui.py` | Graphics row, cycle, label, 18 px pitch | 2 |
| `PyAitD/app/shell.py` | `--shadows`, `apply_render_overrides`, `_MENU_RENDER_FIELDS` | 2 |
| `tools/prove_graphics.py` | `--shadows`, the `-hardshadow` twin | 6 |
| `tests/test_layering.py` | `glsl.py` is strings only | 1 |
| `tests/test_render_options.py`, `tests/test_config.py`, `tests/test_main.py`, `tests/test_ui_reducers.py`, `tests/test_ui_render.py`, `tests/test_shell_journeys.py` | Option plumbing | 2, 6 |
| `tests/test_lighting.py` | Pure twins | 3 |
| `tests/test_render_gl.py` | Identity, penumbra, gathering, blur parity, shadow map, leak count | 3, 4, 5 |
| `tests/test_prove_graphics.py` | Proof tool axes | 6 |
| `docs/soft-shadows-proof.md` (new), `CONTEXT.md`, `AGENTS.md`, `README.md`, `Makefile` | Proof and docs | 6 |

Conventions the code below follows: `_draw_frame` sets every viewport and FBO it needs before each pass and `draw()`'s `finally` restores the caller's state; per-frame buffers are released in a `finally`; every GL resource is set to `None` before allocation so `release()` is safe after a partial `__init__`; `tests/test_render_gl.py` helpers `_view`, `_palette`, `_tri_geometry`, `_facing_tri`, `_standing_actor`, `_plain_background`, `_scene_light`, `_lit_frame`, `_planned_geometry`, `_hex_prism_body`, `_golden_frame` already exist and are reused.

---

### Task 1: Move the GLSL sources to `render/glsl.py`

**Files:**
- Create: `PyAitD/render/glsl.py`
- Modify: `PyAitD/render/render_gl.py` (the ten `_X = """..."""` blocks between `instance_layout` and `rotation_matrix`, lines ~76–325; the import block at the top)
- Test: `tests/test_layering.py`

**Interfaces:**
- Produces: `PyAitD.render.glsl.{BG_VSH, BG_FSH, ACTOR_VSH, ACTOR_FSH, TESS_VSH, SCREEN_VSH, STENCIL_VSH, STENCIL_FSH, SHADOW_GEOM_VSH, SHADOW_FSH}` — `str` constants, byte-identical to today's strings. `render_gl` keeps every internal reference and every test import (`from PyAitD.render.render_gl import _TESS_VSH`) by importing them `as _NAME`.

- [ ] **Step 1: Write the failing meta test**

Append to `tests/test_layering.py`:

```python
def test_glsl_is_strings_only():
    """render/glsl.py holds GLSL sources and nothing else -- no imports, no
    functions, no logic -- so it can never become a second graphics owner
    and a shader edit never hides a Python change."""
    tree = ast.parse((ROOT / "render" / "glsl.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Expr):        # the module docstring
            assert isinstance(node.value, ast.Constant) and isinstance(node.value.value, str), node.lineno
            continue
        assert isinstance(node, ast.Assign), f"line {node.lineno}: {type(node).__name__}"
        assert isinstance(node.value, ast.Constant) and isinstance(node.value.value, str), f"line {node.lineno}: not a string"
        assert all(isinstance(t, ast.Name) and t.id == t.id.upper() for t in node.targets), f"line {node.lineno}"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_layering.py::test_glsl_is_strings_only -q`
Expected: FAIL with `FileNotFoundError` (no `glsl.py`).

- [ ] **Step 3: Move the strings with a script, so nothing is retyped**

Run this from the repo root:

```python
import pathlib, re
gl = pathlib.Path("PyAitD/render/render_gl.py")
src = gl.read_text()
start = src.index('_BG_VSH = """')
end = src.index("def rotation_matrix(state):")
block = src[start:end].rstrip("\n") + "\n"
names = re.findall(r'^_([A-Z_]+) = """', block, re.M)
assert names == ["BG_VSH", "BG_FSH", "ACTOR_VSH", "ACTOR_FSH", "TESS_VSH", "SCREEN_VSH",
                 "STENCIL_VSH", "STENCIL_FSH", "SHADOW_GEOM_VSH", "SHADOW_FSH"], names
header = '''# SPDX-License-Identifier: GPL-2.0-only
"""Every GLSL source the GL backend compiles, as plain strings.

Strings only -- no imports, no functions, no state (tests/test_layering.py
pins that). render_gl.py imports them under its historical underscore
names, so every internal reference and every test import is unchanged."""
'''
public = re.sub(r'^_([A-Z_]+) = """', r'\1 = """', block, flags=re.M)
pathlib.Path("PyAitD/render/glsl.py").write_text(header + public)
anchor = "from PyAitD.render.geometry import icosphere\n"
imports = ("from PyAitD.render.glsl import (\n    "
           + ",\n    ".join(f"{n} as _{n}" for n in names) + ",\n)\n")
out = src[:start] + src[end:]
assert anchor in out
gl.write_text(out.replace(anchor, anchor + imports, 1))
print("moved", names)
```

Then open `PyAitD/render/render_gl.py` and confirm: the import block reads `from PyAitD.render.geometry import icosphere` followed by the `from PyAitD.render.glsl import (...)` block; `instance_layout` is followed by exactly two blank lines and `def rotation_matrix`; `grep -c '"""' PyAitD/render/glsl.py` prints `22` (ten strings, each opened and closed, plus the docstring's two).

- [ ] **Step 4: Run the meta test and the render suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_layering.py tests/test_render_gl.py -q`
Expected: all pass (the golden, the transform-feedback parity test and `test_pure_render_modules_import_no_graphics_library` all still green).

- [ ] **Step 5: Commit**

```bash
git add PyAitD/render/glsl.py PyAitD/render/render_gl.py tests/test_layering.py
git commit -m "refactor: move the GLSL sources to render/glsl.py, strings only"
```

---

### Task 2: The `shadows` option, defaulting to `hard`

**Files:**
- Modify: `PyAitD/render/render_options.py`
- Modify: `PyAitD/app/shell.py` (imports ~line 23, `parse_args` ~line 91, `apply_render_overrides` ~line 125, `_MENU_RENDER_FIELDS` ~line 606)
- Modify: `PyAitD/app/ui.py` (imports ~line 19, `GRAPHICS_ROWS` line 26, `GRAPHICS_CYCLES` ~line 398, `SystemMenuLayout.GRAPHICS_PAGE_ROWS` ~line 610, `graphics_labels` ~line 1184)
- Test: `tests/test_render_options.py`, `tests/test_config.py`, `tests/test_main.py`, `tests/test_ui_reducers.py`, `tests/test_ui_render.py`, `tests/test_shell_journeys.py`, `tests/test_render_gl.py` (the golden test)

**Interfaces:**
- Produces: `render_options.SHADOW_MODES = ("hard", "soft")`, `RenderOptions.shadows: str = "hard"` (ninth positional field, after `smoothing`), `cycle_shadows(options) -> RenderOptions`, `--shadows {hard,soft}`, settings key `"shadows"`, `ui.GRAPHICS_ROWS == 8` with the Shadows row at index 4 (after Lighting).

- [ ] **Step 1: Write the failing option tests**

Append to `tests/test_render_options.py`:

```python
def test_shadows_defaults_to_hard_and_cycles():
    from PyAitD.render.render_options import SHADOW_MODES, cycle_shadows
    assert SHADOW_MODES == ("hard", "soft")
    options = RenderOptions()
    assert options.shadows == "hard"
    assert cycle_shadows(options).shadows == "soft"
    assert cycle_shadows(RenderOptions(shadows="soft")).shadows == "hard"
    assert RenderOptions(shadows="soft").to_payload()["shadows"] == "soft"


def test_invalid_shadows_falls_back_alone():
    for bad in ("penumbra", 1, None, True):
        payload = RenderOptions().to_payload()
        payload["shadows"] = bad
        options, error = validate_render_options(payload)
        assert options == RenderOptions() and "shadows" in error, bad
```

In the same file, `test_each_invalid_field_falls_back_alone` builds two payload dicts by hand; add `"shadows": "hard"` to both (after `"smoothing": 0`), otherwise the missing key is itself reported as an error and `assert error is None` fails.

In `tests/test_config.py::test_save_writes_schema_2_with_render`, the expected `payload["render"]` dict gains `"shadows": "hard"` after `"smoothing": 2`.

Append to `tests/test_main.py`:

```python
def test_shadows_flag_overrides_only_its_own_field():
    from dataclasses import replace

    from PyAitD.app.shell import apply_render_overrides, parse_args
    from PyAitD.app.config import default_settings

    base = default_settings()
    only = apply_render_overrides(base, parse_args(["--shadows", "soft"]))
    assert only == replace(base, render=replace(base.render, shadows="soft"))
    with pytest.raises(SystemExit):
        parse_args(["--shadows", "blurry"])   # argparse choices reject it
```

In `tests/test_ui_reducers.py::test_graphics_rows_cycle_render_options`, replace the body from the `assert GRAPHICS_ROWS == 7` line down with:

```python
    assert GRAPHICS_ROWS == 8 and len(GRAPHICS_CYCLES) == GRAPHICS_ROWS
    assert graphics_row_count() == GRAPHICS_ROWS + 1
    settings = default_settings()
    state = SystemMenuPresenter(page=SystemMenuPage.GRAPHICS, cursor=0)
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(scale=6)
    state.cursor = 1
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(shading="flat")
    state.cursor = 2
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(background_filter="xbr")
    state.cursor = 3
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(lighting="fixed")
    state.cursor = 4
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(shadows="soft")
    state.cursor = 5
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(msaa=8)
    state.cursor = 6
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(realism="classic")
    state.cursor = 7
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(smoothing=3)
    assert state.page is SystemMenuPage.GRAPHICS  # a cycle never leaves the page
```

In `tests/test_ui_render.py::test_graphics_labels_match_the_cycles_one_per_row`, replace the last two asserts with:

```python
    assert labels[0] == "Scale: 4x" and labels[4] == "Shadows: Hard"
    assert labels[6] == "Realism: Enhanced" and labels[7] == "Smoothing: Medium"
```

In `tests/test_shell_journeys.py::test_menu_graphics_page_cycle_and_save_journey`, the Realism row moved down one: change `graphics_rows[5]` to `graphics_rows[6]` (keep the `# Realism` comment).

In `tests/test_render_gl.py::test_classic_realism_matches_the_pre_materials_golden`, name the new field so Task 6's default flip cannot move the golden:

```python
    # smoothing=0 and shadows="hard" name the legacy paths explicitly: the
    # golden predates tessellation and the gathered soft-shadow pass
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene", msaa=0,
                                              realism="classic", smoothing=0, shadows="hard"))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_options.py tests/test_config.py tests/test_main.py tests/test_ui_reducers.py tests/test_ui_render.py -q`
Expected: failures mentioning `SHADOW_MODES`, `shadows`, `GRAPHICS_ROWS == 8`, and the label indices.

- [ ] **Step 3: The option**

In `PyAitD/render/render_options.py`, after `SMOOTHING_LEVELS`:

```python
# hard: today's per-actor projected silhouette, thresholded, verbatim.
# soft: a penumbra that hardens at contact, every actor's shadow gathered
# into one pass before any body is drawn, and a light-view depth map that
# lets bodies shadow themselves and each other. Both under lighting="scene"
# only; "fixed" casts nothing either way.
SHADOW_MODES = ("hard", "soft")
```

Add the field after `smoothing` in `RenderOptions`:

```python
    shadows: str = "hard"
```

Add `"shadows": self.shadows,` to `to_payload` after `"smoothing"`. In `validate_render_options`, after the `smoothing` block and before the `options = RenderOptions(...)` line:

```python
    shadows = payload.get("shadows")
    if shadows not in SHADOW_MODES:
        errors.append(f"shadows must be one of {', '.join(SHADOW_MODES)}")
        shadows = defaults.shadows
```

and extend the constructor call: `RenderOptions(scale, shading, background_filter, override_dir, lighting, msaa, realism, smoothing, shadows)`. Append:

```python
def cycle_shadows(options):
    return replace(options, shadows=_cycle(SHADOW_MODES, options.shadows))
```

- [ ] **Step 4: The shell**

In `PyAitD/app/shell.py`: add `SHADOW_MODES` to the `from PyAitD.render.render_options import (...)` list. In `parse_args`, after the `--smoothing` argument:

```python
    p.add_argument(
        "--shadows", choices=SHADOW_MODES, default=None,
        help="hard: the flat projected silhouette; soft: a contact-hardening penumbra, "
             "one gathered pass, and bodies shadowing themselves and each other",
    )
```

In `apply_render_overrides`, after the `smoothing` lines:

```python
    if args.shadows is not None:
        payload["shadows"] = args.shadows
```

Change `_MENU_RENDER_FIELDS` to `("scale", "shading", "background_filter", "lighting", "msaa", "realism", "smoothing", "shadows")` and add `Shadows` to the comment above it listing the rows.

- [ ] **Step 5: The Graphics page**

In `PyAitD/app/ui.py`: add `cycle_shadows` to the `render_options` import list. `GRAPHICS_ROWS = 8`. `GRAPHICS_CYCLES` becomes:

```python
GRAPHICS_CYCLES = (
    cycle_scale, cycle_shading, cycle_filter, cycle_lighting, cycle_shadows,
    cycle_msaa, cycle_realism, cycle_smoothing,
)
```

In `graphics_labels`, insert after the `Lighting` line:

```python
        f"Shadows: {render.shadows.title()}",
```

Replace the `GRAPHICS_PAGE_ROWS` block in `SystemMenuLayout`:

```python
    # graphics_row_count() rows at an 18 px pitch, 18 px tall. The roadmap's
    # rows need the room: eight plus Back end at y=174, nine plus Back at
    # y=192, both inside the 200-row screen. Touching rows are fine --
    # effective_rects splits their 2 px hit padding at the midpoint, which
    # CONFIG's 13 px rows already rely on -- and 18 >= 13 keeps the 12x12
    # target contract.
    GRAPHICS_PAGE_ROWS = tuple(
        pygame.Rect(16, 12 + i * 18, 288, 18)
        for i in range(graphics_row_count())
    )
```

- [ ] **Step 6: Run the option, UI, shell and render suites**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_options.py tests/test_config.py tests/test_main.py tests/test_ui_reducers.py tests/test_ui_render.py tests/test_shell_journeys.py tests/test_render_gl.py -q`
Expected: all pass (`test_graphics_page_rows_fit_the_screen_and_do_not_overlap` covers the new pitch; the journey test needs game data and skips without it).

- [ ] **Step 7: Full suite, then commit**

Run: `make test`
Expected: green.

```bash
git add PyAitD/render/render_options.py PyAitD/app/shell.py PyAitD/app/ui.py tests/test_render_options.py tests/test_config.py tests/test_main.py tests/test_ui_reducers.py tests/test_ui_render.py tests/test_shell_journeys.py tests/test_render_gl.py
git commit -m "feat: a shadows render option, default hard, on the Graphics page and the CLI"
```

---

### Task 3: The pure twins, level-0 instances, and instance buffers built up front

**Files:**
- Modify: `PyAitD/render/lighting.py` (append after `project_to_plane`)
- Modify: `PyAitD/render/render_gl.py` (`__init__`'s subpatch loop ~line 553; `_draw_frame` ~line 630)
- Test: `tests/test_lighting.py`, `tests/test_render_gl.py`

**Interfaces:**
- Produces: `lighting.SHADOW_MAP_SIZE = 2048`; `lighting.light_view_matrix(travel, corners, pad=0.0) -> (matrix: (4,4) float32, extent: (3,) float64)` — column-vector clip matrix like `camera_matrix`, `matrix @ (x, y, z, 1)`; `lighting.soften(coverage, radius, r_max) -> (H, W) float32`; `GLBackend._subpatch_bufs[0]`; `_draw_frame`'s `instances` list (one `(buffer, count)` or `None` per actor, alive for the whole frame).

- [ ] **Step 1: Write the failing pure tests**

Add `light_view_matrix, soften` to the `from PyAitD.render.lighting import (...)` list in `tests/test_lighting.py`, then append:

```python
def test_light_view_matrix_frames_every_corner_strictly_inside_ndc():
    rng = np.random.default_rng(3)
    corners = rng.uniform(-2000.0, 2000.0, (24, 3))
    matrix, extent = light_view_matrix((0.3, 0.8, 0.5), corners)
    clip = np.c_[corners, np.ones(len(corners))] @ matrix.T.astype(np.float64)
    assert np.all(np.abs(clip[:, :3]) < 1.0) and np.allclose(clip[:, 3], 1.0)
    assert np.all(extent > 0.0)


def test_light_view_matrix_depth_grows_along_the_travel():
    travel = np.array([0.2, 0.9, 0.4]) / np.linalg.norm([0.2, 0.9, 0.4])   # inside the MIN_UP cone: unclamped
    near = np.array([100.0, 100.0, 100.0])
    far = near + travel * 500.0
    matrix, _ = light_view_matrix(travel, [near, far, near + (300.0, 0.0, 0.0)])
    depth = lambda p: float((matrix.astype(np.float64) @ np.r_[p, 1.0])[2])
    assert depth(far) > depth(near)      # so the depth test keeps what is nearest the light


def test_light_view_matrix_survives_a_single_point_and_a_vertical_light():
    for travel in ((0.0, 1.0, 0.0), (0.3, 0.8, 0.5)):
        matrix, extent = light_view_matrix(travel, [(5.0, 5.0, 5.0)])
        assert np.all(np.isfinite(matrix)) and np.all(extent >= 1.0)
        assert abs(np.linalg.det(matrix.astype(np.float64))) > 0.0


def test_light_view_matrix_pad_widens_every_axis():
    corners = [(0.0, 0.0, 0.0), (100.0, 100.0, 100.0)]
    _, tight = light_view_matrix((0.0, 1.0, 0.0), corners)
    _, padded = light_view_matrix((0.0, 1.0, 0.0), corners, pad=50.0)
    assert np.all(padded > tight + 99.0)      # 50 on each side, plus the margin's share of it


def test_soften_with_zero_radius_is_the_identity():
    cover = np.zeros((9, 9))
    cover[4, 4], cover[2, 6] = 1.0, 0.5
    out = soften(cover, np.zeros((9, 9)), r_max=4)
    assert np.array_equal(out, cover.astype(np.float32))


def test_soften_spreads_one_pixel_over_its_own_box_and_conserves_it():
    cover = np.zeros((21, 21))
    cover[10, 10] = 1.0
    radius = np.zeros((21, 21))
    radius[10, 10] = 3.0
    out = soften(cover, radius, r_max=6)
    assert np.allclose(out[7:14, 7:14], 1.0 / 49.0) and np.isclose(out.sum(), 1.0)
    assert out[6, :].max() == 0.0 and out[:, 14].max() == 0.0


def test_soften_keeps_a_contact_pixel_sharp_beside_a_soft_one():
    # the whole point of a per-pixel radius: a foot on the plane stays crisp
    # while the head's shadow spreads
    cover = np.zeros((21, 21))
    cover[10, 5], cover[10, 15] = 1.0, 1.0
    radius = np.zeros((21, 21))
    radius[10, 15] = 4.0
    out = soften(cover, radius, r_max=6)
    assert out[10, 5] == 1.0 and out[9, 5] == 0.0 and out[10, 4] == 0.0
    assert 0.0 < out[10, 15] < 1.0


def test_soften_never_exceeds_full_coverage():
    cover = np.ones((15, 15))
    radius = np.full((15, 15), 2.0)
    out = soften(cover, radius, r_max=6)
    assert np.allclose(out[2:-2, 2:-2], 1.0)          # a uniform field is unchanged inside
    radius[7, 7] = 5.0
    assert soften(cover, radius, r_max=6).max() <= 1.0
```

- [ ] **Step 2: Run them to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_lighting.py -q`
Expected: ImportError on `light_view_matrix`.

- [ ] **Step 3: Implement the twins**

Append to `PyAitD/render/lighting.py`:

```python
# The light-view depth map every actor is rendered into under
# shadows="soft": one square map per frame, fitted to the frame's actors.
SHADOW_MAP_SIZE = 2048


def light_view_matrix(travel, corners, pad=0.0):
    """(matrix, extent): an orthographic light-view matrix over `corners`.

    `travel` is the direction light travels, in world space; it is tipped
    onto the MIN_UP cone exactly as project_to_plane does, so the map and
    the ground shadow always agree about where the light goes. `corners`
    is (K, 3) world points -- every actor's bounding-box corners; `pad`
    widens the box by that many world units on every side before the
    one-texel margin, so a receiver the shader pushes along its normal
    still lands inside the map.

    The matrix is column-vector, like camera_matrix: `matrix @ (x, y, z,
    1)` is clip space, x and y across the map and z growing along
    `travel`, so the depth test keeps what is nearest the light. Every
    corner lands strictly inside [-1, 1] on all three axes. `extent` is
    the (3,) light-space size of the box mapped onto [-1, 1]; its z is
    what turns a bias in world units into map depth. A single point still
    gives a finite, invertible matrix: every axis is at least one unit
    wide."""
    forward = _clamp_downward(travel)
    corners = np.asarray(corners, dtype=np.float64).reshape(-1, 3)
    # World y grows downward, so "up" is -y. When the light travels almost
    # straight down the vertical is no use as a hint: fall back to world x.
    up_hint = np.array([0.0, -1.0, 0.0])
    if abs(float(np.dot(forward, up_hint))) > 0.99:
        up_hint = np.array([1.0, 0.0, 0.0])
    right = np.cross(up_hint, forward)
    right /= np.linalg.norm(right)
    up = np.cross(forward, right)
    basis = np.stack([right, up, forward])              # rows: the light-space axes
    local = corners @ basis.T
    lo, hi = local.min(axis=0) - pad, local.max(axis=0) + pad
    centre = (lo + hi) / 2.0
    half = np.maximum((hi - lo) / 2.0, 0.5)             # at least one unit wide
    half += 2.0 * half / SHADOW_MAP_SIZE                 # one texel of margin per side
    extent = 2.0 * half
    view = np.eye(4)
    view[:3, :3] = basis
    ortho = np.eye(4)
    ortho[0, 0], ortho[1, 1], ortho[2, 2] = 1.0 / half
    ortho[:3, 3] = -centre / half
    return (ortho @ view).astype(np.float32), extent


def _shift(array, d, axis):
    """`out[p] = array[p + d]` along `axis`, zero beyond the edge."""
    out = np.zeros_like(array)
    n = array.shape[axis]
    if abs(d) >= n:
        return out
    src = [slice(None)] * array.ndim
    dst = [slice(None)] * array.ndim
    if d >= 0:
        src[axis], dst[axis] = slice(d, n), slice(0, n - d)
    else:
        src[axis], dst[axis] = slice(0, n + d), slice(-d, n)
    out[tuple(dst)] = array[tuple(src)]
    return out


def soften(coverage, radius, r_max):
    """The numpy twin of render_gl's two-pass penumbra blur (SHADOW_BLUR_FSH),
    which the GL test pins the shader against.

    `coverage` and `radius` are (H, W): coverage 0..1 and a per-pixel
    penumbra radius in pixels, 0..r_max. Each covered pixel is spread over
    a box of *its own* radius -- (2r + 1) pixels per axis, weight
    1 / (2r + 1) each -- horizontally, then vertically, carrying the
    largest radius that reached a pixel into the second pass. Written as a
    gather (each output pixel asks which neighbours reach it), which is
    the form a fragment shader can take. A radius-0 pixel spreads nowhere:
    a foot on the plane stays sharp while the head's shadow goes soft.
    Coverage is clamped to 1.0 after each pass."""
    cover = np.asarray(coverage, dtype=np.float64)
    reach = np.floor(np.asarray(radius, dtype=np.float64) + 0.5)
    for axis in (1, 0):
        out = np.zeros_like(cover)
        carried = np.zeros_like(cover)
        for d in range(-r_max, r_max + 1):
            shifted_cover = _shift(cover, d, axis)
            shifted_reach = _shift(reach, d, axis)
            hits = (shifted_cover > 0.0) & (abs(d) <= shifted_reach)
            out += np.where(hits, shifted_cover / (2.0 * shifted_reach + 1.0), 0.0)
            carried = np.where(hits, np.maximum(carried, shifted_reach), carried)
        cover, reach = np.minimum(out, 1.0), carried
    return cover.astype(np.float32)
```

- [ ] **Step 4: Run the pure tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_lighting.py -q`
Expected: all pass.

- [ ] **Step 5: Write the failing GL tests for level 0 and the leak count**

In `tests/test_render_gl.py::test_init_failure_releases_every_already_allocated_gl_object`, change the subpatch assertions to:

```python
    assert sorted(backend._subpatch_bufs) == [0, 1, 2, 3]
    for level, buf in backend._subpatch_bufs.items():
        assert isinstance(buf.mglo, moderngl.InvalidObject), f"subpatch buffer {level} leaked"
        leak_checked += 1
    assert leak_checked == 31  # every GL resource __init__ allocates, none skipped
```

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py::test_init_failure_releases_every_already_allocated_gl_object -q`
Expected: FAIL (`[1, 2, 3] != [0, 1, 2, 3]`).

- [ ] **Step 6: Level 0 as an instance draw, and the buffers built up front**

In `PyAitD/render/render_gl.py` `__init__`, replace the subpatch loop and its comment:

```python
            # Every level, 0 included: subpatch(0) is the flat triangle with
            # exact corners, so the soft-shadow passes can draw every actor
            # through the instanced programs whatever `smoothing` says.
            for level in SMOOTHING_LEVELS:
                self._subpatch_bufs[level] = ctx.buffer(np.ascontiguousarray(subpatch(level), dtype="f4").tobytes())
```

Replace `_draw_frame` in full:

```python
    def _draw_frame(self, frame):
        self._target.use()
        self._ctx.viewport = (0, 0, *self.size)
        self._ctx.disable(moderngl.DEPTH_TEST)
        self._ctx.disable(moderngl.BLEND)
        self._target.color_mask = (True, True, True, True)
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)

        self._draw_background(frame.background)

        mvp = camera_matrix(frame.camera, self._options.scale)
        rot = rotation_matrix(frame.camera.state).astype("f4")
        scene_lit = self._options.lighting == "scene"
        soft = scene_lit and self._options.shadows == "soft"
        level = self._options.smoothing
        travel = None
        if scene_lit:
            # rotation_matrix maps world -> camera and is orthonormal, so
            # its transpose maps back. `direction` points toward the light;
            # light travels the other way. Computed only here so the
            # byte-for-byte `fixed` escape hatch never touches frame.light.
            travel = -(rot.astype(np.float64).T
                       @ np.asarray(frame.light.direction, np.float64))
            self._material_tex.use(location=3)
        self._set_frame_uniforms(self._actor_prog, frame, mvp, rot, scene_lit)
        if level:
            self._set_frame_uniforms(self._tess_prog, frame, mvp, rot, scene_lit)
        self._screen_prog["target_size"].value = self.size

        palette = frame.palette.astype("f4") / 255.0
        mask_by_id = {mask.id: mask for mask in frame.masks}

        # One instance buffer per actor for the whole frame, built before
        # the loop: the soft-shadow passes read every actor's before any
        # body is drawn, so they cannot be built per actor. Under hard
        # shadows at level 0 nothing is built, as before. Released in the
        # `finally` so a raise anywhere below cannot leak one.
        instances = [None] * len(frame.actors)
        try:
            if level or soft:
                for i, actor in enumerate(frame.actors):
                    data = self._instance_data(actor.geometry, np.asarray(actor.position, np.float64), palette)
                    if len(data):
                        instances[i] = (self._ctx.buffer(data.tobytes()), len(data))

            for actor, inst in zip(frame.actors, instances):
                masks = [mask_by_id[i] for i in actor.mask_ids if i in mask_by_id]
                self._rasterize_masks(masks)  # switches to the mask FBO and disables depth test

                if scene_lit:
                    if level:
                        cast = self._rasterize_shadow_tessellated(inst, travel, mvp, _plane_y(actor), level)
                    else:
                        cast = self._rasterize_shadow(actor, travel, mvp)
                    if cast:
                        self._composite_shadow(frame.light)

                self._target.use()
                self._ctx.viewport = (0, 0, *self.size)
                self._ctx.enable(moderngl.DEPTH_TEST)
                self._ctx.depth_func = "<="
                # A fresh depth buffer per actor: within one actor's own
                # primitives, depth decides what's in front; across actors,
                # later draws simply paint over earlier ones (painter's order).
                self._target.color_mask = (False, False, False, False)
                self._target.clear(depth=1.0)
                self._target.color_mask = (True, True, True, True)
                # Framebuffer.clear() leaves moderngl's colour-mask state
                # desynced from the GL binding point: re-`use()` the target so
                # the restored mask actually takes effect before the next
                # render.
                self._target.use()

                self._mask_tex.use(location=1)
                self._actor_prog["mask_tex"].value = 1
                self._screen_prog["mask_tex"].value = 1
                if level:
                    self._tess_prog["mask_tex"].value = 1

                if scene_lit:
                    self._actor_prog["plane_y"].value = _plane_y(actor)
                    if level:
                        self._tess_prog["plane_y"].value = _plane_y(actor)
                    self._upload_materials(actor.materials)
                if level:
                    self._draw_actor_tessellated(actor, frame, palette, inst, level)
                else:
                    self._draw_actor(actor, frame, palette)
                self._ctx.disable(moderngl.DEPTH_TEST)
        finally:
            for inst in instances:
                if inst is not None:
                    inst[0].release()

        if self._ms_fbo is not None:
            # Resolves the multisample buffer down into `.texture`, which is
            # what read_rgb, thumbnail and Renderer all read.
            self._ctx.copy_framebuffer(self._fbo, self._ms_fbo)
```

- [ ] **Step 7: Run the render suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py tests/test_render.py -q`
Expected: all pass — the golden, `test_smoothing_zero_draws_through_the_legacy_path` (level 0 under `hard` still never calls `_instance_data`), the tessellated shadow tests and the leak count at 31.

- [ ] **Step 8: Full suite, then commit**

Run: `make test`
Expected: green.

```bash
git add PyAitD/render/lighting.py PyAitD/render/render_gl.py tests/test_lighting.py tests/test_render_gl.py
git commit -m "feat: light-view matrix and penumbra twins; level-0 instances; per-frame instance buffers"
```

---

### Task 4: The gathered cast, the penumbra, the blur and the fractional composite

**Files:**
- Modify: `PyAitD/render/glsl.py` (`TESS_VSH`, `SHADOW_FSH`; new `SHADOW_CAST_FSH`, `SHADOW_BLUR_FSH`)
- Modify: `PyAitD/render/render_gl.py` (imports, constants, `__init__`, `release`, `draw`, `_draw_frame`, `_composite_shadow`; new `_r_max`, `_gather_shadows`, `_soften_shadows`)
- Test: `tests/test_render_gl.py`

**Interfaces:**
- Consumes: `lighting.soften`, `lighting._clamp_downward`, `GLBackend._subpatch_bufs[0]`, `_draw_frame`'s `instances`.
- Produces: `render_gl.R_MAX_PER_SCALE = 6`, `render_gl.SOURCE_ANGLE = 6.0`, `render_gl.TAN_SOURCE`, `GLBackend._r_max() -> int`, `GLBackend._gather_shadows(frame, instances, mask_by_id, travel, mvp, rot, level)`, `GLBackend._soften_shadows()`, `GLBackend._composite_shadow(light, soft=False)`; `_shadow_tex` is now two-channel (R coverage, G radius / R_MAX); `_shadow_blur_tex`, `_shadow_blur_fbo`, `_cast_prog`, `_cast_layout`, `_blur_prog`, `_blur_quad_vao`. `TESS_VSH` gains uniforms `right: vec3`, `tan_source: float`, `r_max: float`, `target_size: vec2` and the varying `v_penumbra: float`; `SHADOW_FSH` gains `soft: int`.

- [ ] **Step 1: Write the failing GL tests**

Append to `tests/test_render_gl.py`:

```python
# ---- soft shadows (roadmap F) ----

# A 200-grey plate under _scene_light (ambient 0.1, contrast 1.0) inside a
# shadow: mix(1, 0.1, shadow_opacity(1.0) = 0.7) * 200 -- measured 74.
FULL_SHADOW_ON_200 = 74


def _soft_frame_render(gl_ctx, shadows, actors, plate, direction, masks=(), level=0, shading="flat", realism="enhanced"):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading=shading, lighting="scene", msaa=0,
                                              realism=realism, smoothing=level, shadows=shadows))
    backend.draw(FrameDescription(_view(), ImageAsset(plate, False), _palette(), tuple(actors), tuple(masks),
                                  _scene_light(direction)))
    out = backend.read_rgb().astype(int)
    backend.release()
    return out


def _partial_shadow_pixels(rendered, rows):
    """Pixels in `rows` that are darker than the plate but lighter than a full
    shadow: a hard shadow has none (binary coverage), a penumbra has many."""
    green = rendered[rows, :, 1]
    return int(((green > FULL_SHADOW_ON_200 + 2) & (green < 200 - 2)).sum())


def _sphere_at(x, y, z, radius=120.0, color=2):
    return BodyGeometry(np.array([[x, y, z]], np.float32), np.array([[0.0, 0.0, -1.0]], np.float32),
                        np.zeros((0, 3), np.int32), np.zeros(0, np.uint8),
                        np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), ((0, radius, color),),
                        np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))


def _facing_square(z, color, normal, span=400.0):
    v = np.array([[-span, -span, z], [span, -span, z], [-span, span, z], [span, span, z]], np.float32)
    n = np.tile(normal, (4, 1)).astype(np.float32)
    return BodyGeometry(v, n, np.array([[0, 1, 2], [1, 3, 2]], np.int32), np.array([color, color], np.uint8),
                        np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), (),
                        np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))


def test_soft_shadows_have_a_penumbra_and_hard_ones_do_not(gl_ctx):
    plate = np.full((200, 320, 3), 200, np.uint8)
    actor = _standing_actor(0, _planned_geometry(_hex_prism_body()), feet_y=150)
    light = (0.0, -0.5, 0.85)     # _shadow_frame's light: the shadow falls toward the camera, rows 137+
    below = slice(137, 200)
    hard = _soft_frame_render(gl_ctx, "hard", [actor], plate, light)
    soft = _soft_frame_render(gl_ctx, "soft", [actor], plate, light)
    assert _partial_shadow_pixels(hard, below) == 0            # thresholded coverage: all or nothing
    assert _partial_shadow_pixels(soft, below) > 100           # a real penumbra


def test_the_penumbra_hardens_toward_the_feet(gl_ctx):
    # The prism stands on its plane. Rows just below its feet (137-139) are
    # cast by its lowest points -- a drop of a few units, a radius under a
    # pixel -- and the rows nearest the camera (142+) by its top, 300 units
    # up, whose radius saturates at R_MAX. Partial pixels per row must grow
    # with the drop. The ratio is the claim; the counts are this geometry's.
    plate = np.full((200, 320, 3), 200, np.uint8)
    actor = _standing_actor(0, _planned_geometry(_hex_prism_body()), feet_y=150)
    soft = _soft_frame_render(gl_ctx, "soft", [actor], plate, (0.0, -0.5, 0.85))
    near_feet = _partial_shadow_pixels(soft, slice(137, 140)) / 3.0
    near_camera = _partial_shadow_pixels(soft, slice(142, 150)) / 8.0
    assert near_camera > 2.0 * near_feet


def _overlap_frame(with_caster):
    """The golden frame's light over a facing square, with a sphere placed
    so its ground shadow lands on the square's body (measured: 213 pixels
    at smoothing 2). At smoothing 0 the CPU path projects triangles only,
    so this scene is drawn tessellated."""
    from PyAitD.render.lighting import SceneLight
    light = SceneLight((0.3, -0.5, -0.8), (0.9, 0.8, 0.7), (0.2, 0.2, 0.3), 0.7)
    square = _standing_actor(0, _facing_square(600.0, 1, (0.0, -0.6, -0.8)), 400.0)
    caster = _standing_actor(1, _sphere_at(-200.0, -150.0, 500.0), 400.0)
    actors = (square, caster) if with_caster else (square,)
    return FrameDescription(_view(), ImageAsset(np.full((200, 320, 3), 40, np.uint8), False),
                            _palette(), actors, (), light)


def _render_overlap(gl_ctx, shadows, frame):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene", msaa=0,
                                              realism="classic", smoothing=2, shadows=shadows))
    backend.draw(frame)
    out = backend.read_rgb().astype(int)
    backend.release()
    return out


def test_a_gathered_shadow_never_darkens_an_earlier_actor(gl_ctx):
    # The per-actor composite is a full-target multiply with no depth: a
    # nearer actor's shadow, composited after a farther body was drawn,
    # paints over that body. Gathering every cast before any body is drawn
    # is what `soft` fixes; `hard` keeps the artefact verbatim.
    square_only = _overlap_frame(False)
    caster_only = FrameDescription(square_only.camera, square_only.background, square_only.palette,
                                   (_overlap_frame(True).actors[1],), (), square_only.light)
    solo_hard, paired_hard = _render_overlap(gl_ctx, "hard", square_only), _render_overlap(gl_ctx, "hard", _overlap_frame(True))
    solo_soft, paired_soft = _render_overlap(gl_ctx, "soft", square_only), _render_overlap(gl_ctx, "soft", _overlap_frame(True))
    sphere = _render_overlap(gl_ctx, "hard", caster_only)
    body = (solo_hard[..., 1] == 0) & (solo_hard[..., 0] > 0)          # the red square's own pixels...
    body &= ~((sphere[..., 0] == 0) & (sphere[..., 1] > 0))            # ...minus where the green sphere is drawn over it
    # ...and only below row 130: the sphere sits between the light and the
    # square, so from Task 5 on it *legitimately* shadows the square through
    # the depth map around screen (113, 83), rows 57-109. The composite
    # artefact this test is about lands at rows 149-158.
    body[:130] = False
    assert body.sum() > 5000
    wrong = np.any(paired_hard != solo_hard, axis=2) & body
    assert wrong.sum() > 100                                           # hard: the sphere's shadow lands on the square
    assert np.array_equal(paired_soft[body], solo_soft[body])          # soft: the body is untouched


def test_two_soft_casters_darken_a_pixel_once(gl_ctx):
    # Overlapping casts blend with MAX, so two shadows on one pixel are one.
    plate = np.full((200, 320, 3), 200, np.uint8)
    geometry = _tri_geometry(600.0, 1, span=100.0)
    one = [_standing_actor(0, geometry, feet_y=150)]
    two = one + [_standing_actor(1, geometry, feet_y=150)]
    assert np.array_equal(_soft_frame_render(gl_ctx, "soft", one, plate, (0.0, -1.0, -0.2)),
                          _soft_frame_render(gl_ctx, "soft", two, plate, (0.0, -1.0, -0.2)))


def test_a_mask_erases_a_soft_cast_beyond_its_penumbra(gl_ctx):
    # The mask discard moved from the composite into the cast, so the
    # coverage texture is already erased where the pillar stands -- and the
    # blur runs afterwards, so a penumbra can bleed up to R_MAX pixels past
    # the mask's edge (the spec's first limitation). Beyond that band the
    # masked half must be the untouched plate.
    plate = np.full((200, 320, 3), 200, np.uint8)
    geometry = _planned_geometry(_hex_prism_body())
    actor = ActorDraw(0, geometry, (0.0, 0.0, 0.0), 0, (0, 0, -50, 150, 0, 0), RenderResult([], []), (0,))
    poly = np.array([[160, 137], [320, 137], [320, 200], [160, 200]], np.int16)
    right_half = MaskDraw(0, (poly,), (160, 137, 320, 200), 0, ())
    rendered = _soft_frame_render(gl_ctx, "soft", [actor], plate, (0.0, -0.5, 0.85), masks=[right_half], level=2)
    plain = _plain_background(gl_ctx, plate)
    r_max = 6                                       # R_MAX_PER_SCALE at scale 1
    inside = (slice(137 + r_max, None), slice(160 + r_max, None))
    assert np.array_equal(rendered[inside], plain[inside])
    unmasked = int((rendered[137:, :160] < plain[137:, :160] - 5).any(axis=2).sum())
    assert unmasked > 300                           # still cast where the mask does not reach


def test_the_soft_blur_matches_the_numpy_twin(gl_ctx):
    from PyAitD.render.lighting import soften
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat", lighting="scene", msaa=0, shadows="soft"))
    rng = np.random.default_rng(11)
    cover = (rng.random((200, 320)) < 0.02).astype(np.float64)
    radius = np.where(cover > 0, rng.integers(0, 7, (200, 320)), 0).astype(np.float64)
    r_max = backend._r_max()
    assert r_max == 6
    rg = np.zeros((200, 320, 2), np.uint8)
    rg[..., 0] = (cover * 255).astype(np.uint8)
    rg[..., 1] = np.round(radius / r_max * 255).astype(np.uint8)
    backend._shadow_tex.write(np.ascontiguousarray(rg).tobytes())
    backend._soften_shadows()
    out = np.frombuffer(backend._shadow_tex.read(), np.uint8).reshape(200, 320, 2)[..., 0] / 255.0
    backend.release()
    expected = soften(cover, radius, r_max)
    # the intermediate pass is stored in 8 bits and so is the result: half a
    # step each, plus the twin's own rounding
    assert np.abs(out - expected).max() <= 2.5 / 255


def test_soft_with_nothing_to_shadow_is_byte_identical_to_hard(gl_ctx):
    # The spec's second identity: soft's plumbing -- the up-front instance
    # buffers, the gathered pass, the blur, the fractional composite (and,
    # from Task 5, the shadow-map lookup at visibility 1.0) -- changes no
    # pixel when there is nothing to shadow. A mask starting below the body
    # (rows 80-120) erases the ground shadow (rows 143-150) at the cast,
    # and nothing occludes the body.
    plate = np.full((200, 320, 3), 40, np.uint8)
    actor = ActorDraw(0, _tri_geometry(600.0, 1, span=100.0), (0.0, 0.0, 0.0), 0, (0, 0, 100, 300, 0, 0),
                      RenderResult([], []), (0,))
    poly = np.array([[0, 125], [320, 125], [320, 200], [0, 200]], np.int16)
    ground = MaskDraw(0, (poly,), (0, 125, 320, 200), 0, ())
    for level in (0, 2):
        hard = _soft_frame_render(gl_ctx, "hard", [actor], plate, (0.3, -0.5, -0.8), masks=[ground], level=level, shading="smooth")
        soft = _soft_frame_render(gl_ctx, "soft", [actor], plate, (0.3, -0.5, -0.8), masks=[ground], level=level, shading="smooth")
        assert np.any(hard != 40), level          # the body is really drawn
        assert np.array_equal(hard, soft), level


def test_fixed_lighting_ignores_the_shadows_option(gl_ctx):
    frame = _overlap_frame(True)
    outs = []
    for shadows in ("hard", "soft"):
        backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="fixed", msaa=0,
                                                  smoothing=0, shadows=shadows))
        backend.draw(frame)
        outs.append(backend.read_rgb().copy())
        backend.release()
    assert np.array_equal(*outs)


def test_a_sphere_casts_a_soft_shadow_even_on_the_flat_mesh(gl_ctx):
    # Under hard, level 0 projects geometry.tris on the CPU and a sphere has
    # none; soft always casts from the instance stream, spheres included.
    plate = np.full((200, 320, 3), 200, np.uint8)
    actor = _standing_actor(0, _sphere_at(0.0, 0.0, 600.0, radius=150.0, color=1), feet_y=150)
    plain = _plain_background(gl_ctx, plate)
    hard = _soft_frame_render(gl_ctx, "hard", [actor], plate, (0.0, -0.5, 0.85))
    soft = _soft_frame_render(gl_ctx, "soft", [actor], plate, (0.0, -0.5, 0.85))
    assert int((hard[137:] < plain[137:] - 5).any(axis=2).sum()) == 0
    assert int((soft[137:] < plain[137:] - 5).any(axis=2).sum()) > 50
```

In `test_init_failure_releases_every_already_allocated_gl_object`, add to the attribute tuple (after `"_tess_prog", "_tess_shadow_prog",`):

```python
        "_shadow_blur_tex", "_shadow_blur_fbo", "_cast_prog", "_blur_prog", "_blur_quad_vao",
```

and change the count to `assert leak_checked == 36`.

- [ ] **Step 2: Run them to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q -k "soft or penumbra or gathered or blur or leak or fixed_lighting_ignores"`
Expected: failures — `_r_max` missing, `_shadow_blur_tex` never allocated, penumbra counts 0 under soft, the ordering assertion.

- [ ] **Step 3: The shaders**

In `PyAitD/render/glsl.py`, `TESS_VSH`: extend the uniform block and outputs, and the `project` branch. The uniform line

```glsl
uniform int project; uniform vec3 travel; uniform float plane_y;
```

becomes

```glsl
uniform int project; uniform vec3 travel; uniform float plane_y;
// Cast mode only: the camera's world x axis, tan of the light source's
// angular radius, the penumbra radius the blur can honour, and the target
// size in pixels -- a caster's height above its plane becomes a penumbra
// width in world units and then a radius in pixels, written to v_penumbra
// as a fraction of r_max. Under project == 0 v_penumbra is 0 and unread.
uniform vec3 right; uniform float tan_source; uniform float r_max; uniform vec2 target_size;
```

add `out float v_penumbra;` after the `out vec3 v_world;` line, and replace the single line

```glsl
    if (project == 1) pos += (plane_y - pos.y) / travel.y * travel;
```

with

```glsl
    v_penumbra = 0.0;
    if (project == 1) {
        float drop = plane_y - pos.y;                   // height above the plane: world y grows downward
        pos += (plane_y - pos.y) / travel.y * travel;
        // penumbra width = drop * tan(source angle), projected to pixels
        // along the camera's x axis at the shadow point's own depth
        vec4 a = mvp * vec4(pos, 1.0);
        vec4 b = mvp * vec4(pos + right * drop * tan_source, 1.0);
        vec2 px = (b.xy / max(b.w, 1.0) - a.xy / max(a.w, 1.0)) * 0.5 * target_size;
        v_penumbra = clamp(length(px) / r_max, 0.0, 1.0);
    }
```

Replace `SHADOW_FSH` in full:

```python
SHADOW_FSH = """
#version 330
uniform sampler2D shadow_tex; uniform sampler2D mask_tex;
uniform vec2 target_size; uniform vec3 shadow_color; uniform float opacity;
uniform int soft;
out vec4 f_color;
void main() {
    vec2 uv = gl_FragCoord.xy / target_size;
    float cover = texture(shadow_tex, uv).r;
    if (soft == 0) {
        // The per-actor path, verbatim: this actor's foreground masks hide
        // its shadow exactly as they hide the actor, and coverage is
        // binary, so overlapping limbs darken a pixel once.
        if (texture(mask_tex, uv).r > 0.5) discard;
        if (cover < 0.5) discard;
        cover = 1.0;
    } else if (cover <= 0.0) {
        // The gathered path: every cast was erased by its own actor's
        // masks and softened before this runs; coverage is fractional.
        discard;
    }
    // A per-channel factor <= 1.0 (shadow_color is 0..1), multiplied
    // (not alpha-blended) into the destination below: this can only ever
    // scale the background down toward the room's ambient hue, never
    // brighten it, unlike a src-alpha blend which pulls the destination
    // toward ambient from either side.
    f_color = vec4(mix(vec3(1.0), shadow_color, opacity * cover), 1.0);
}
"""
```

Append the two new programs' fragment shaders:

```python
SHADOW_CAST_FSH = """
#version 330
// The gathered ground-shadow cast: coverage in R, the penumbra radius
// (a fraction of r_max) in G. This actor's own foreground masks erase
// its cast here, once, so the gathered coverage needs no mask at
// composite time. Overlapping casts blend with MAX on both channels.
uniform sampler2D mask_tex; uniform vec2 target_size;
in float v_penumbra;
out vec4 f_color;
void main() {
    if (texture(mask_tex, gl_FragCoord.xy / target_size).r > 0.5) discard;
    f_color = vec4(1.0, v_penumbra, 0.0, 0.0);
}
"""
SHADOW_BLUR_FSH = """
#version 330
// One axis of the penumbra blur: each covered source pixel is spread over
// a box of its own radius, written as a gather -- this output pixel asks
// every neighbour within r_max whether that neighbour's radius reaches it,
// and takes cover / (2 r + 1) from each that does, carrying the largest
// radius that reached it into G for the second axis. lighting.soften is
// the numpy twin the parity test pins this against.
uniform sampler2D src; uniform ivec2 axis; uniform int r_max;
out vec4 f_color;
void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    ivec2 size = textureSize(src, 0);
    float cover = 0.0;
    float reach = 0.0;
    for (int d = -r_max; d <= r_max; d++) {
        ivec2 q = p + axis * d;
        if (q.x < 0 || q.y < 0 || q.x >= size.x || q.y >= size.y) continue;
        vec2 s = texelFetch(src, q, 0).rg;
        float r = floor(s.g * float(r_max) + 0.5);
        if (s.r > 0.0 && float(abs(d)) <= r) {
            cover += s.r / (2.0 * r + 1.0);
            reach = max(reach, r);
        }
    }
    f_color = vec4(min(cover, 1.0), reach / float(r_max), 0.0, 0.0);
}
"""
```

- [ ] **Step 4: The backend — imports, constants, resources**

In `PyAitD/render/render_gl.py`: add `SHADOW_CAST_FSH as _SHADOW_CAST_FSH` and `SHADOW_BLUR_FSH as _SHADOW_BLUR_FSH` to the `glsl` import list. After `CONTACT_HEIGHT`, add:

```python
# The ground shadow's penumbra. A light source of angular radius
# SOURCE_ANGLE throws a penumbra `drop * tan(SOURCE_ANGLE)` wide at a point
# whose caster is `drop` units above the plane -- 6 degrees is an indoor
# lamp a few metres off; the sun would be a quarter of one. R_MAX_PER_SCALE
# is the widest radius the blur honours, in pixels per unit of render
# scale, and what the cast shader normalises its radius by.
SOURCE_ANGLE = 6.0
TAN_SOURCE = math.tan(math.radians(SOURCE_ANGLE))
R_MAX_PER_SCALE = 6
```

In `__init__`'s pre-allocation `None` list, add after `self._shadow_fbo = None`:

```python
        self._shadow_blur_tex = None
        self._shadow_blur_fbo = None
        self._cast_prog = None
        self._cast_layout = None
        self._blur_prog = None
        self._blur_quad_vao = None
```

Change the shadow texture allocation to two channels and add the blur pair beside it:

```python
            # Two channels: R is coverage, G the penumbra radius the gathered
            # cast writes (a fraction of R_MAX); the hard path writes 1.0 to
            # both and reads only R. The blur ping-pongs between this and
            # _shadow_blur_tex, horizontal then vertical, ending back here.
            self._shadow_tex = ctx.texture(self.size, 2)
            self._shadow_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            self._shadow_tex.repeat_x = False
            self._shadow_tex.repeat_y = False
            self._shadow_fbo = ctx.framebuffer(color_attachments=[self._shadow_tex])
            self._shadow_blur_tex = ctx.texture(self.size, 2)
            self._shadow_blur_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            self._shadow_blur_tex.repeat_x = False
            self._shadow_blur_tex.repeat_y = False
            self._shadow_blur_fbo = ctx.framebuffer(color_attachments=[self._shadow_blur_tex])
```

After the `self._shadow_quad_vao = ...` allocation, add:

```python
            self._blur_prog = ctx.program(vertex_shader=_STENCIL_VSH, fragment_shader=_SHADOW_BLUR_FSH)
            self._blur_quad_vao = ctx.vertex_array(
                self._blur_prog, [(self._shadow_quad, "2f", "in_pos")])
```

After the `_tess_shadow_layout` line, add:

```python
            # The gathered cast: _TESS_VSH in project mode, writing coverage
            # and penumbra radius. Seeded like _tess_shadow_prog so an unset
            # travel can never divide by zero.
            self._cast_prog = ctx.program(vertex_shader=_TESS_VSH, fragment_shader=_SHADOW_CAST_FSH)
            self._cast_prog["travel"].value = (0.0, 1.0, 0.0)
            self._cast_layout = instance_layout(self._cast_prog)
```

In `release()`, add `self._blur_quad_vao, self._blur_prog, self._cast_prog,` after `self._shadow_quad,` and `self._shadow_blur_fbo, self._shadow_blur_tex,` after `self._shadow_fbo, self._shadow_tex,`.

In `draw()`'s `finally`, after the `blend_func` reset line:

```python
            self._ctx.blend_equation = moderngl.FUNC_ADD  # the gathered cast blends with MAX
```

- [ ] **Step 5: The backend — the passes**

Add these methods after `_rasterize_shadow_tessellated`:

```python
    def _r_max(self):
        """The widest penumbra radius the blur honours, in target pixels."""
        return R_MAX_PER_SCALE * self._options.scale

    def _gather_shadows(self, frame, instances, mask_by_id, travel, mvp, rot, level):
        """Every actor's ground shadow into one coverage texture -- each cast
        erased by that actor's own masks -- softened by the per-pixel
        penumbra radius and multiplied onto the plate once, before any body
        is drawn. A nearer actor's shadow can no longer paint over a farther
        body, and overlapping casts take the MAX, so they darken once."""
        self._shadow_fbo.use()
        self._ctx.viewport = (0, 0, *self.size)
        self._ctx.disable(moderngl.DEPTH_TEST)
        self._shadow_fbo.clear(0.0, 0.0, 0.0, 0.0)
        prog = self._cast_prog
        prog["mvp"].write(mvp.T.astype("f4").tobytes())
        prog["project"].value = 1
        prog["travel"].value = tuple(float(v) for v in _clamp_downward(travel))
        # rot maps world -> camera, so its first row is the world vector
        # that lands on camera +x: the axis the penumbra width is measured along
        prog["right"].value = tuple(float(v) for v in rot[0])
        prog["tan_source"].value = TAN_SOURCE
        prog["r_max"].value = float(self._r_max())
        prog["target_size"].value = self.size
        prog["mask_tex"].value = 1
        cast = False
        for actor, inst in zip(frame.actors, instances):
            if inst is None:
                continue
            self._rasterize_masks([mask_by_id[i] for i in actor.mask_ids if i in mask_by_id])
            self._shadow_fbo.use()
            self._ctx.viewport = (0, 0, *self.size)
            self._mask_tex.use(location=1)
            prog["plane_y"].value = _plane_y(actor)
            self._ctx.enable(moderngl.BLEND)
            self._ctx.blend_func = moderngl.ONE, moderngl.ONE
            self._ctx.blend_equation = moderngl.MAX
            self._render_instanced(prog, self._cast_layout, inst[0], inst[1], level)
            self._ctx.blend_equation = moderngl.FUNC_ADD
            self._ctx.disable(moderngl.BLEND)
            cast = True
        if cast:
            self._soften_shadows()
            self._composite_shadow(frame.light, soft=True)

    def _soften_shadows(self):
        """Two passes of the radius-driven blur over the coverage texture:
        horizontal into _shadow_blur_tex, vertical back into _shadow_tex."""
        self._blur_prog["src"].value = 2
        self._blur_prog["r_max"].value = self._r_max()
        passes = (((1, 0), self._shadow_tex, self._shadow_blur_fbo),
                  ((0, 1), self._shadow_blur_tex, self._shadow_fbo))
        for axis, src, dst in passes:
            dst.use()
            self._ctx.viewport = (0, 0, *self.size)
            self._ctx.disable(moderngl.DEPTH_TEST)
            src.use(location=2)
            self._blur_prog["axis"].value = axis
            self._blur_quad_vao.render(moderngl.TRIANGLES)
```

Change `_composite_shadow`'s signature to `def _composite_shadow(self, light, soft=False):`, add to its docstring a final paragraph:

```
        Under `soft` the coverage is the gathered, mask-erased, softened
        texture and is consumed fractionally; the ordering caveat below
        no longer applies, since this runs once before any body is drawn.
```

and set the uniform beside the others: `self._shadow_prog["soft"].value = 1 if soft else 0`.

In `_draw_frame`, insert the gathered pass right after the instance buffers are built (inside the `try`, before the `for actor, inst in zip(...)` loop):

```python
            if soft:
                self._gather_shadows(frame, instances, mask_by_id, travel, mvp, rot, level)
```

and change the per-actor shadow condition from `if scene_lit:` to `if scene_lit and not soft:`.

- [ ] **Step 6: Run the render suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q`
Expected: all pass. If `test_the_penumbra_hardens_toward_the_feet` fails on its ratio, print `_partial_shadow_pixels` per row for rows 135–160 and check the shadow really spans rows 137–150 under this light before touching the constants; the ratio, not the counts, is the claim.

- [ ] **Step 7: Full suite, then commit**

Run: `make test`
Expected: green.

```bash
git add PyAitD/render/glsl.py PyAitD/render/render_gl.py tests/test_render_gl.py
git commit -m "feat: gathered ground shadows with a contact-hardening penumbra under shadows=soft"
```

---

### Task 5: The light-view shadow map and the receiver term

**Files:**
- Modify: `PyAitD/render/glsl.py` (`ACTOR_VSH`, `TESS_VSH`, `SCREEN_VSH`, `ACTOR_FSH`)
- Modify: `PyAitD/render/render_gl.py` (imports, constants, `__init__`, `release`, `_set_frame_uniforms`, `_draw_frame`; new `_set_uniform`, `_world_box`, `_render_shadow_map`)
- Test: `tests/test_render_gl.py`

**Interfaces:**
- Consumes: `lighting.light_view_matrix`, `lighting.SHADOW_MAP_SIZE`, `_draw_frame`'s `instances`.
- Produces: `render_gl.NORMAL_OFFSET = 6.0`, `render_gl.SHADOW_BIAS_UNITS = 4.0`, `render_gl._world_box(actor) -> list[8 (x, y, z)]`, `render_gl._set_uniform(prog, name, value)`, `GLBackend._render_shadow_map(frame, instances, travel, level) -> (light_vp_T: (4,4) f4, depth_bias: float) | None`, `GLBackend._set_frame_uniforms(prog, frame, mvp, rot, scene_lit, shadow=None)`, `_shadow_map`, `_shadow_map_fbo`. Shader uniforms `light_vp: mat4`, `normal_offset: float`, `self_shadow: int`, `depth_bias: float`, `shadow_map: sampler2DShadow` (unit 4); varying `v_shadow: vec4`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_render_gl.py`:

```python
def test_world_box_encloses_vertices_and_spheres():
    from PyAitD.render.render_gl import _world_box
    actor = ActorDraw(0, _sphere_at(10.0, 20.0, 30.0, radius=5.0), (100.0, 0.0, 0.0), 0, (0,) * 6,
                      RenderResult([], []), ())
    corners = np.array(_world_box(actor))
    assert corners.shape == (8, 3)
    assert corners.min(axis=0).tolist() == [105.0, 15.0, 25.0]
    assert corners.max(axis=0).tolist() == [115.0, 25.0, 35.0]


def test_an_occluder_shadows_the_key_share_of_a_receiver_only_under_soft(gl_ctx):
    # A small triangle held between the light and a big facing one, off to
    # the side so its shadow (measured: screen x 129-145, y 91-115) lands
    # on the receiver away from its own footprint (x 175-194, y 36-66).
    receiver = _standing_actor(0, _facing_tri(600.0, 1, (0.0, 0.0, -1.0)), 400.0)
    occluder_geometry = BodyGeometry(
        np.array([[60.0, -260.0, 300.0], [140.0, -260.0, 300.0], [60.0, -140.0, 300.0]], np.float32),
        np.tile([0.0, 0.0, -1.0], (3, 1)).astype(np.float32),
        np.array([[0, 1, 2]], np.int32), np.array([1], np.uint8),
        np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), (),
        np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))
    occluder = _standing_actor(1, occluder_geometry, 400.0)
    direction = (0.5, -0.5, -0.7)

    def window(shadows, actors):
        backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene", msaa=0,
                                                  realism="classic", smoothing=0, shadows=shadows))
        backend.draw(_lit_frame(actors, direction))
        out = backend.read_rgb().astype(int)[98:106, 132:142]     # inside the occluder's shadow on the receiver
        backend.release()
        return out

    lit_red = int(window("soft", [receiver])[..., 0].mean())
    dark_red = int(window("soft", [receiver, occluder])[..., 0].mean())
    assert dark_red < lit_red - 40                    # the key's share is gone...
    assert dark_red > 30                              # ...and the fill's is not: never black
    assert np.array_equal(window("hard", [receiver, occluder]), window("hard", [receiver]))   # hard never self-shadows


def test_hard_shadows_never_touch_the_shadow_map(gl_ctx, monkeypatch):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene", msaa=0,
                                              smoothing=2, shadows="hard"))

    def boom(*_a, **_k):
        raise AssertionError("shadow map rendered under shadows=hard")

    monkeypatch.setattr(backend, "_render_shadow_map", boom)
    backend.draw(_overlap_frame(True))
    backend.release()
```

In `test_init_failure_releases_every_already_allocated_gl_object`, add `"_shadow_map", "_shadow_map_fbo",` to the attribute tuple and change the count to `assert leak_checked == 38`.

- [ ] **Step 2: Run them to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q -k "world_box or occluder or shadow_map or leak"`
Expected: ImportError on `_world_box`; the occluder test's `dark_red < lit_red - 40` fails; the leak count fails.

- [ ] **Step 3: The shaders**

In `PyAitD/render/glsl.py`:

`ACTOR_VSH` becomes:

```python
ACTOR_VSH = """
#version 330
uniform mat4 mvp; uniform mat3 rot;
// The receiver's place in the light-view depth map: its world position
// pushed along its world normal, so a surface never shadows itself at
// its own depth. Unread under shadows=hard (light_vp stays zero).
uniform mat4 light_vp; uniform float normal_offset;
in vec3 in_pos; in vec3 in_normal; in vec3 in_color; in vec3 in_rest; in float in_ao; in float in_index;
out vec3 v_color; out vec3 v_normal; out vec3 v_rest; out float v_ao; flat out float v_index; out float v_world_y;
out vec4 v_shadow;
void main() {
    gl_Position = mvp * vec4(in_pos, 1.0);
    v_color = in_color; v_normal = rot * in_normal;
    v_rest = in_rest; v_ao = in_ao; v_index = in_index;
    v_world_y = in_pos.y;   // in_pos is already world space: the actor position was added on the CPU
    v_shadow = light_vp * vec4(in_pos + in_normal * normal_offset, 1.0);
}
"""
```

`TESS_VSH`: add `uniform mat4 light_vp; uniform float normal_offset;` after the `uniform mat4 mvp; uniform mat3 rot;` line, `out vec4 v_shadow;` after `out float v_penumbra;`, and insert, immediately before the `v_penumbra = 0.0;` line (so it sees the unprojected position):

```glsl
    v_shadow = light_vp * vec4(pos + n * normal_offset, 1.0);
```

`SCREEN_VSH`: add `out vec4 v_shadow;` to its outputs and `v_shadow = vec4(0.0);` in `main` (lines and points never reach the term).

`ACTOR_FSH`: add after the `uniform float plane_y; uniform float contact_height;` line:

```glsl
// The light-view depth map (shadows=soft): hardware-compared, bilinear.
// self_shadow gates the lookup; depth_bias is in map depth units, from
// SHADOW_BIAS_UNITS over the map's extent along the light.
uniform sampler2DShadow shadow_map; uniform int self_shadow; uniform float depth_bias;
```

add `in vec4 v_shadow;` to the inputs, and replace the two lines

```glsl
    float wrapped = clamp(dot(n, l) * 0.5 + 0.5, 0.0, 1.0);
    vec3 base = v_color * (fill_tint + key_tint * wrapped * wrapped);
```

with

```glsl
    float vis = 1.0;
    if (self_shadow == 1) {
        // How much of the key reaches this fragment: a slope-scaled bias in
        // map depth on top of the vertex shader's normal offset, four
        // hardware-compared taps averaged into a soft edge. Under
        // shadows=hard the branch is skipped and vis stays exactly 1.0, so
        // `* vis` below is the identity and `base` is the classic
        // expression bit for bit.
        vec4 s = v_shadow;
        s.z -= depth_bias * (1.0 + 2.0 * (1.0 - abs(dot(n, l)))) * s.w;
        vis = 0.25 * (textureProj(shadow_map, s)
                    + textureProjOffset(shadow_map, s, ivec2(1, 0))
                    + textureProjOffset(shadow_map, s, ivec2(0, 1))
                    + textureProjOffset(shadow_map, s, ivec2(1, 1)));
    }
    float wrapped = clamp(dot(n, l) * 0.5 + 0.5, 0.0, 1.0);
    // The key's share is what a shadow removes; the fill's share stays, so
    // a shadowed limb falls to the room's fill colour and never to black.
    vec3 base = v_color * (fill_tint + key_tint * wrapped * wrapped * vis);
```

and change the `spec` line to end `* m0.y * preset_a.x * vis;`.

- [ ] **Step 4: The backend**

In `PyAitD/render/render_gl.py`: add `light_view_matrix, SHADOW_MAP_SIZE` to the `lighting` import. After `R_MAX_PER_SCALE`, add:

```python
# The shadow-map receiver: a vertex is pushed NORMAL_OFFSET world units
# along its normal before it is looked up, and the comparison is biased
# by SHADOW_BIAS_UNITS (scaled by slope) so a surface never shadows itself
# at its own depth. Bodies are 100-400 units across; both are well under a
# limb's thickness.
NORMAL_OFFSET = 6.0
SHADOW_BIAS_UNITS = 4.0
# Clip [-1, 1] -> texture [0, 1] on every axis, folded into light_vp so the
# fragment shader's textureProj reads the map directly.
_SHADOW_BIAS = np.array([[0.5, 0.0, 0.0, 0.5],
                         [0.0, 0.5, 0.0, 0.5],
                         [0.0, 0.0, 0.5, 0.5],
                         [0.0, 0.0, 0.0, 1.0]])


def _set_uniform(prog, name, value):
    """Set `name` if the linker kept it. A program whose fragment stage never
    reads a varying loses the uniforms that only fed it -- the cast program
    drops light_vp, the shadow-map program drops right/tan_source/r_max --
    and ModernGL raises KeyError for a name the program lacks."""
    try:
        uniform = prog[name]
    except KeyError:
        return
    if isinstance(value, np.ndarray):
        uniform.write(value.tobytes())
    else:
        uniform.value = value


def _world_box(actor):
    """The eight corners of the box around everything this actor draws --
    posed vertices and sphere extents, in world space. Not the collision
    `zv`: FITD's box stops short of outstretched limbs, and a fragment
    outside the shadow map's box would compare against its edge texel."""
    geometry = actor.geometry
    position = np.asarray(actor.position, np.float64)
    points = [geometry.vertices.astype(np.float64) + position]
    for centre_idx, radius, _color in geometry.spheres:
        centre = geometry.vertices[centre_idx].astype(np.float64) + position
        points.append(centre[None, :] - radius)
        points.append(centre[None, :] + radius)
    pts = np.concatenate(points, axis=0)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    return [(float(x), float(y), float(z)) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
```

In `__init__`'s `None` list add `self._shadow_map = None` and `self._shadow_map_fbo = None`. After the `_material_tex` allocation, add:

```python
            # The light-view depth map every actor is rendered into under
            # shadows=soft. compare_func turns sampling into a depth test the
            # hardware bilinearly filters (2x2 PCF); LINEAR is what makes
            # that filtering happen. Depth-only: no colour attachment.
            self._shadow_map = ctx.depth_texture((SHADOW_MAP_SIZE, SHADOW_MAP_SIZE))
            self._shadow_map.compare_func = "<="
            self._shadow_map.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self._shadow_map.repeat_x = False
            self._shadow_map.repeat_y = False
            self._shadow_map_fbo = ctx.framebuffer(depth_attachment=self._shadow_map)
            for prog in (self._actor_prog, self._screen_prog):
                _set_uniform(prog, "shadow_map", 4)
                _set_uniform(prog, "self_shadow", 0)
```

and after `self._tess_prog = ctx.program(...)`:

```python
            _set_uniform(self._tess_prog, "shadow_map", 4)
```

In `release()`, add `self._shadow_map_fbo, self._shadow_map,` after `self._material_tex,`.

Replace `_set_frame_uniforms` in full:

```python
    def _set_frame_uniforms(self, prog, frame, mvp, rot, scene_lit, shadow=None):
        """Everything an actor program needs once per frame. Shared by
        _actor_prog and _tess_prog so the two can never disagree about the
        light; the values are exactly what _draw_frame set inline before.
        `shadow` is _render_shadow_map's (light_vp, depth_bias) under
        shadows=soft, else None -- which leaves self_shadow at 0 and the
        classic expression untouched."""
        prog["mvp"].write(mvp.T.tobytes())
        prog["rot"].write(rot.T.tobytes())
        prog["shading"].value = _SHADING_INDEX[self._options.shading]
        if scene_lit:
            key_tint, fill_tint = shading_terms(frame.light)
            prog["lighting"].value = 1
            prog["light"].value = tuple(float(v) for v in frame.light.direction)
            prog["key_tint"].value = tuple(float(v) for v in key_tint)
            prog["fill_tint"].value = tuple(float(v) for v in fill_tint)
            preset = PRESETS[self._options.realism]
            prog["preset_a"].value = (preset.spec, preset.rim, preset.ao)
            prog["preset_b"].value = (preset.contact, preset.detail, preset.hemisphere)
            prog["contact_height"].value = CONTACT_HEIGHT
            prog["material_tex"].value = 3
        else:
            prog["lighting"].value = 0
            prog["light"].value = LIGHT_DIR
            prog["key_tint"].value = (0.0, 0.0, 0.0)
            prog["fill_tint"].value = (0.0, 0.0, 0.0)
            prog["preset_a"].value = (0.0, 0.0, 0.0)
            prog["preset_b"].value = (0.0, 0.0, 0.0)
        if shadow is not None:
            light_vp, depth_bias = shadow
            _set_uniform(prog, "self_shadow", 1)
            _set_uniform(prog, "light_vp", light_vp)
            _set_uniform(prog, "depth_bias", depth_bias)
            _set_uniform(prog, "normal_offset", NORMAL_OFFSET)
        else:
            _set_uniform(prog, "self_shadow", 0)
        prog["target_size"].value = self.size
```

Add after `_soften_shadows`:

```python
    def _render_shadow_map(self, frame, instances, travel, level):
        """One orthographic depth map from the light over every actor's
        instances, spheres included, lines and points excluded as in every
        shadow pass. Returns the (light_vp, depth_bias) the receivers need
        -- light_vp already carrying the clip-to-texture bias, transposed
        for GLSL -- or None when no actor has anything to cast, in which
        case the receivers keep self_shadow = 0. No face culling: FITD
        winding is not consistent, so both faces write depth."""
        corners = []
        for actor, inst in zip(frame.actors, instances):
            if inst is not None:
                corners.extend(_world_box(actor))
        if not corners:
            return None
        matrix, extent = light_view_matrix(travel, corners, pad=NORMAL_OFFSET)
        self._shadow_map_fbo.use()
        self._ctx.viewport = (0, 0, SHADOW_MAP_SIZE, SHADOW_MAP_SIZE)
        self._ctx.enable(moderngl.DEPTH_TEST)
        self._ctx.depth_func = "<="
        self._shadow_map_fbo.clear(depth=1.0)
        prog = self._tess_shadow_prog
        prog["mvp"].write(matrix.T.astype("f4").tobytes())
        prog["project"].value = 0
        for inst in instances:
            if inst is not None:
                self._render_instanced(prog, self._tess_shadow_layout, inst[0], inst[1], level)
        self._ctx.disable(moderngl.DEPTH_TEST)
        biased = (_SHADOW_BIAS @ matrix.astype(np.float64)).astype("f4")
        return np.ascontiguousarray(biased.T), float(SHADOW_BIAS_UNITS / extent[2])
```

In `_draw_frame`: bind the map every frame — add `self._shadow_map.use(location=4)` right after the `if scene_lit:` block that binds the material texture (outside that block, unconditionally). Move the two `_set_frame_uniforms` calls and the `_screen_prog["target_size"]` line from before the `palette = ...` line to inside the `try`, after the instance buffers are built and before the gathered pass, as:

```python
            shadow = None
            if soft:
                shadow = self._render_shadow_map(frame, instances, travel, level)
            self._set_frame_uniforms(self._actor_prog, frame, mvp, rot, scene_lit, shadow)
            if level:
                self._set_frame_uniforms(self._tess_prog, frame, mvp, rot, scene_lit, shadow)
            self._screen_prog["target_size"].value = self.size

            if soft:
                self._gather_shadows(frame, instances, mask_by_id, travel, mvp, rot, level)
```

The final shape of `_draw_frame`'s `try` body is: build instances → shadow map → frame uniforms → gathered pass → the per-actor loop.

- [ ] **Step 5: Run the render suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q`
Expected: all pass — including `test_soft_with_nothing_to_shadow_is_byte_identical_to_hard` (visibility is exactly 1.0 for an unoccluded fragment: every compared tap passes, and `* 1.0` is exact), the golden, and the transform-feedback parity test (the new uniforms are unset there and only feed varyings it does not capture).

If the identity test fails only at level 2, the tessellated surface is shadowing itself: raise `SHADOW_BIAS_UNITS` to 6.0 before anything else and re-run; record the value that holds in the commit message.

- [ ] **Step 6: Full suite, then commit**

Run: `make test`
Expected: green.

```bash
git add PyAitD/render/glsl.py PyAitD/render/render_gl.py tests/test_render_gl.py
git commit -m "feat: a light-view shadow map so bodies shadow themselves and each other under shadows=soft"
```

---

### Task 6: Default `soft`, the proof tool's twin, the proof document and the docs

**Files:**
- Modify: `PyAitD/render/render_options.py` (the default)
- Modify: `tools/prove_graphics.py`
- Modify: `Makefile` (the `proof-graphics` help line)
- Modify: `README.md` (the CLI-flags paragraph ~line 84, the tests list ~line 130), `AGENTS.md` (line 19, the `render/` conventions bullet ~line 145), `CONTEXT.md` (line 30, the `render/lighting.py`, `render_options.py`, `render_gl.py` rows ~lines 96–98, a new `render/glsl.py` row, the "Where we are" table)
- Create: `docs/soft-shadows-proof.md`
- Test: `tests/test_render_options.py`, `tests/test_config.py`, `tests/test_ui_reducers.py`, `tests/test_ui_render.py`, `tests/test_prove_graphics.py`

**Interfaces:**
- Produces: `RenderOptions.shadows == "soft"` by default; `prove_graphics.render_fixture(data_dir, name, scale, shading, ctx, realism="enhanced", smoothing=None, shadows=None)`; `prove_graphics.output_paths(out_dir, smoothing=None, shadows=None) -> [(name, mode, realism, level, shadows, path)]` with the `-flatmesh` and `-hardshadow` twins; `--shadows`.

- [ ] **Step 1: Flip the default and update the tests that name it**

`PyAitD/render/render_options.py`: `shadows: str = "soft"`.

Test edits: `tests/test_render_options.py::test_shadows_defaults_to_hard_and_cycles` → rename to `test_shadows_defaults_to_soft_and_cycles`, body:

```python
    assert SHADOW_MODES == ("hard", "soft")
    options = RenderOptions()
    assert options.shadows == "soft"
    assert cycle_shadows(options).shadows == "hard"
    assert cycle_shadows(RenderOptions(shadows="hard")).shadows == "soft"
    assert RenderOptions(shadows="hard").to_payload()["shadows"] == "hard"
```

`tests/test_config.py::test_save_writes_schema_2_with_render`: `"shadows": "soft"`. `tests/test_render_options.py::test_each_invalid_field_falls_back_alone`: both hand-built payload dicts change to `"shadows": "soft"` (they must match the default, or the expected positional `RenderOptions(8, ...)` no longer equals the validated one). `tests/test_ui_reducers.py::test_graphics_rows_cycle_render_options`: cursor 4 → `RenderOptions(shadows="hard")`. `tests/test_ui_render.py::test_graphics_labels_match_the_cycles_one_per_row`: `labels[4] == "Shadows: Soft"`.

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_options.py tests/test_config.py tests/test_ui_reducers.py tests/test_ui_render.py tests/test_render_gl.py -q`
Expected: all pass (the golden names `shadows="hard"` since Task 2).

- [ ] **Step 2: Write the failing proof-tool tests**

In `tests/test_prove_graphics.py`, replace `test_output_paths_cover_every_combination_plus_a_flat_mesh_pair`, `test_parse_args_smoothing_defaults_to_the_render_default` and `test_render_fixture_is_importable_with_the_documented_signature` with:

```python
def test_output_paths_cover_every_combination_plus_the_twins():
    from PyAitD.render.render_options import RenderOptions
    paths = output_paths("docs/graphics-proof")
    assert len(paths) == len(FIXTURES) * len(SHADING_MODES) * len(REALISM_MODES) + 2 * len(FIXTURES)
    default = RenderOptions()
    names = {(name, mode, realism, level, shadows) for name, mode, realism, level, shadows, _ in paths}
    expected = {(n, m, r, default.smoothing, default.shadows)
                for n in FIXTURES for m in SHADING_MODES for r in REALISM_MODES}
    expected |= {(n, "smooth", "enhanced", 0, default.shadows) for n in FIXTURES}
    expected |= {(n, "smooth", "enhanced", default.smoothing, "hard") for n in FIXTURES}
    assert names == expected
    for name, mode, realism, level, shadows, path in paths:
        suffix = "-flatmesh" if level == 0 else "-hardshadow" if shadows == "hard" else ""
        assert path == pathlib.Path("docs/graphics-proof") / f"{name}-{mode}-{realism}{suffix}.png"


def test_parse_args_smoothing_and_shadows_default_to_the_render_defaults():
    from PyAitD.render.render_options import RenderOptions
    assert _parse_args(["d"]).smoothing == RenderOptions().smoothing
    assert _parse_args(["d", "--smoothing", "0"]).smoothing == 0
    assert _parse_args(["d"]).shadows == RenderOptions().shadows
    assert _parse_args(["d", "--shadows", "hard"]).shadows == "hard"


def test_render_fixture_is_importable_with_the_documented_signature():
    # Purely a signature check -- guards against a stray reorder of
    # positional args in a later edit, without needing GL or game data.
    import inspect
    params = list(inspect.signature(render_fixture).parameters)
    assert params == ["data_dir", "name", "scale", "shading", "ctx", "realism", "smoothing", "shadows"]
```

and extend `test_render_fixture_produces_scaled_frames` with two lines at the end:

```python
    hard = render_fixture(data_dir, "attic", scale=2, shading="smooth", ctx=gl_ctx, shadows="hard")
    assert not np.array_equal(rgb, hard)   # the default softens the shadows, and it shows
```

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_prove_graphics.py -q`
Expected: failures on the tuple width, the signature and `--shadows`.

- [ ] **Step 3: The proof tool**

In `tools/prove_graphics.py`: import `SHADOW_MODES` beside `SMOOTHING_LEVELS`. Update the module docstring's second paragraph to say "plus one flat-mesh (smoothing 0) and one hard-shadow (`shadows=hard`) PNG per fixture beside the smooth-enhanced render" and add "`docs/soft-shadows-proof.md` for the one the two `-hardshadow` files feed" to its last sentence.

`render_fixture`:

```python
def render_fixture(data_dir, name, scale, shading, ctx, realism="enhanced", smoothing=None, shadows=None):
    game, floor = _boot(data_dir, name)
    frame, _ = build_frame(game, floor, AssetResolver(game.assets))
    options = RenderOptions(scale=scale, shading=shading, realism=realism)
    if smoothing is not None:
        options = replace(options, smoothing=smoothing)
    if shadows is not None:
        options = replace(options, shadows=shadows)
    backend = GLBackend(ctx, options)
    try:
        backend.draw(frame)
        return backend.read_rgb()
    finally:
        backend.release()
```

`output_paths`:

```python
def output_paths(out_dir, smoothing=None, shadows=None):
    """(name, mode, realism, smoothing, shadows, path) for every fixture x
    shading-mode x realism combination at `smoothing` and `shadows` (the
    RenderOptions defaults when None), then one flat-mesh (smoothing 0)
    file and one hard-shadow (shadows "hard") file per fixture beside the
    smooth-enhanced render, in the order rendered and printed by `main`."""
    out_dir = pathlib.Path(out_dir)
    defaults = RenderOptions()
    level = defaults.smoothing if smoothing is None else smoothing
    mode_shadows = defaults.shadows if shadows is None else shadows
    paths = [
        (name, mode, realism, level, mode_shadows, out_dir / f"{name}-{mode}-{realism}.png")
        for name in FIXTURES
        for mode in SHADING_MODES
        for realism in REALISM_MODES
    ]
    paths += [(name, "smooth", "enhanced", 0, mode_shadows, out_dir / f"{name}-smooth-enhanced-flatmesh.png")
              for name in FIXTURES]
    paths += [(name, "smooth", "enhanced", level, "hard", out_dir / f"{name}-smooth-enhanced-hardshadow.png")
              for name in FIXTURES]
    return paths
```

`_parse_args` gains, after `--smoothing`:

```python
    p.add_argument("--shadows", choices=SHADOW_MODES, default=RenderOptions().shadows,
                   help="shadow mode for the main renders (the -hardshadow pair is always hard)")
```

and `main`'s loop becomes:

```python
        for name, mode, realism, level, shadows, path in output_paths(args.out, args.smoothing, args.shadows):
            rgb = render_fixture(args.data, name, args.scale, mode, ctx, realism, level, shadows)
```

`Makefile` line 85's help text: "... plus a flat-mesh pair and a hard-shadow pair, to docs/graphics-proof/".

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_prove_graphics.py -q`
Expected: all pass (the data-dependent one skips without game data).

- [ ] **Step 4: Render the proof and measure the frame time**

Run: `make proof-graphics` (needs game data and GL). Expected: sixteen PNG paths printed, the two `-hardshadow` files among them. Open `docs/graphics-proof/attic-smooth-enhanced.png` beside `attic-smooth-enhanced-hardshadow.png`: the lantern's, the horse's and Carnby's shadows have soft outer edges and sharp contact at the feet; the arms shade the coat.

Measure the budget with this scratch script (do not commit it; substitute your data path):

```python
import time, moderngl
from tools.prove_graphics import _boot
from PyAitD.render.asset_resolver import AssetResolver
from PyAitD.render.scene import build_frame
from PyAitD.render.render_gl import GLBackend
from PyAitD.render.render_options import RenderOptions
DATA = "data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK"
ctx = moderngl.create_standalone_context(require=330)
game, floor = _boot(DATA, "attic")
frame, _ = build_frame(game, floor, AssetResolver(game.assets))
for shadows in ("hard", "soft"):
    backend = GLBackend(ctx, RenderOptions(scale=4, shading="smooth", lighting="scene", msaa=4,
                                           realism="enhanced", smoothing=2, shadows=shadows))
    for _ in range(3):
        backend.draw(frame); ctx.finish()
    start = time.perf_counter()
    for _ in range(20):
        backend.draw(frame); ctx.finish()
    print(shadows, round((time.perf_counter() - start) / 20 * 1000, 2), "ms")
    backend.release()
ctx.release()
```

Run it as `SDL_VIDEODRIVER=dummy .venv/bin/python scratch_timing.py` from the repo root. Record both numbers; `soft` must be ≤ 1.5× `hard`. If it is not, halve the blur's cost first by running `_soften_shadows` at `R_MAX_PER_SCALE = 4` and re-measure, and say so in the proof.

- [ ] **Step 5: The proof document**

Create `docs/soft-shadows-proof.md` in the shape of `docs/smooth-geometry-proof.md`, with real output pasted in:

```markdown
# Soft shadows proof

Date: <today>
Spec: `docs/superpowers/specs/2026-08-29-actor-realism-roadmap-design.md` (sub-project F)

**This document's "Manual attestation" table is a checklist for a human with
real game data and a real window; every row starts `pending` and no claim
about the rendered PNGs should be inferred from this file until a human
fills them in.** Everything under "Automated gates" was actually run, in this
environment, on this branch, and the output shown is the real output of that
run.

## What changed

Under `shadows=soft` (the new default; `hard` is the previous per-actor
projected silhouette, byte for byte) every actor's ground shadow is cast
into one coverage texture with a per-pixel penumbra radius -- the caster's
height above its plane times tan 6 degrees, projected to pixels -- and
softened by a two-pass blur that spreads each pixel over its own radius, so
a foot on the floor stays sharp and a head's shadow goes soft. Every cast is
erased by its own actor's masks and the whole texture is composited once
before any body is drawn, so a nearer actor's shadow no longer paints over a
farther body. One 2048-square depth map rendered from the light over every
actor lets a body shadow itself and other actors: the shader scales the
key's share of the light by a four-tap compared lookup, leaving the fill
share, so shadowed skin falls to the room's fill colour and never to black.
The GLSL sources moved to `PyAitD/render/glsl.py`. `smoothing=0` with
`shadows=hard` and `realism=classic` reproduces the pre-change output byte
for byte (`tests/golden/scene_lit_classic.npy`).

## Automated gates

<paste the exact command and output of>
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_lighting.py tests/test_render_gl.py tests/test_render_options.py tests/test_layering.py tests/test_ui_reducers.py tests/test_ui_render.py tests/test_prove_graphics.py -q

<paste the exact command and output of>
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest -q

`tests/test_render_gl.py::test_classic_realism_matches_the_pre_materials_golden`
(now naming `shadows="hard"`), `test_soft_with_nothing_to_shadow_is_byte_identical_to_hard`
(the plumbing identity) and `test_the_soft_blur_matches_the_numpy_twin`
(the shader against `lighting.soften`) are the binding ones.

## `make proof-graphics`

Sixteen PNGs under `docs/graphics-proof/` (git-ignored): the twelve
`<attic|combat>-<flat|lambert|smooth>-<classic|enhanced>.png` at the
defaults, `<fixture>-smooth-enhanced-flatmesh.png` at smoothing 0, and
`<fixture>-smooth-enhanced-hardshadow.png` at `shadows=hard`.

<one paragraph comparing attic-smooth-enhanced.png with its -hardshadow twin
pixel by pixel: how many pixels differ, where the bounding box lies, and
what a crop of Carnby's feet and of the lantern's shadow shows>

## Frame time

Attic fixture, scale 4, msaa 4, smoothing 2, enhanced, 20 frames after 3
warm-ups, `ctx.finish()` after each: `hard` <n> ms, `soft` <n> ms
(<ratio>x; the budget is 1.5x).

## Known limitations

- A penumbra can bleed up to `6 * scale` pixels across a foreground mask's
  edge: the blur runs after the mask erase.
- One depth map for every actor in the frame: its texel is the frame's
  actor extent over 2048, coarse in the widest caves; single-sided panels
  can show acne bounded by the bias.
- Walls, masks and the plate receive nothing but the projected ground
  silhouette; the receiving plane still travels with the actor.
- Lines and points cast nothing.

## Manual attestation

| Check | Status |
|---|---|
| `attic-smooth-enhanced-hardshadow.png` is identical to the pre-change `attic-smooth-enhanced.png` | pending |
| Under `soft`, Carnby's shadow is sharp at his feet and soft at his head; the lantern's and horse's shadows likewise | pending |
| Carnby's arm shadows his coat, and a monster standing between the lamp and Carnby shadows him | pending |
| No dark speckling (acne) on the wardrobe's flat panels or the barrels | pending |
| Graphics page: `Shadows: Soft / Hard` sits between Lighting and AA; 8 rows plus Back, nothing clipped; every row cycles by mouse and keyboard | pending |
| Toggling Shadows to Hard in the menu changes the look live; Hard looks as before | pending |
| `--shadows soft` at scale 8 in the floor-5 combat venue keeps a playable frame rate | pending |
```

- [ ] **Step 6: The docs**

`README.md`, in the CLI-flags paragraph, after the `--smoothing {0,1,2,3}` clause and before `and --overrides DIR`, insert:

```
`--shadows {hard,soft}` (`hard` is the flat projected silhouette; `soft`
gives every shadow a penumbra that hardens where the actor meets the ground,
composites every actor's shadow once before any body is drawn, and lets
limbs and actors shadow each other through a light-view depth map),
```

and change line 130's proof description to "render attic + combat fixtures at every shading mode, plus flat-mesh and hard-shadow pairs, to docs/graphics-proof/".

`AGENTS.md` line 19: "... plus a flat-mesh pair and a hard-shadow pair (needs GL + game data)". In the `render/` conventions bullet (~line 145), after the `refine` sentence, add: "`glsl` is strings only — every GLSL source the backend compiles, no imports (`test_layering` pins it). `lighting.soften` and `lighting.light_view_matrix` are the numpy twins of the penumbra blur and the shadow-map projection, pinned like `refine.evaluate` — change a formula in both or neither."

`CONTEXT.md`: line 30 as the README's; the `render/lighting.py` row gains "`light_view_matrix`, `soften`: the orthographic light view every actor's shadow map is rendered from, and the numpy twin of the penumbra blur"; the `render/render_options.py` row's field list gains `shadows`; the `render/render_gl.py` row gains "gathered contact-hardening soft shadows and a light-view shadow map behind `shadows`"; add a row `| render/glsl.py | Every GLSL source as a plain string; no imports, no logic |` after the `render_gl.py` row; the "Where we are" table gains a row after "Smooth actor geometry":

```
| Soft shadows (roadmap F) | Contact-hardening penumbra, one gathered shadow pass, light-view shadow map for self/inter-actor shadowing, `shadows` knob | automated gates green; windowed attestation pending (`docs/soft-shadows-proof.md`) |
```

- [ ] **Step 7: Full suite, then commit**

Run: `make test`
Expected: green.

```bash
git add PyAitD/render/render_options.py tools/prove_graphics.py Makefile README.md AGENTS.md CONTEXT.md docs/soft-shadows-proof.md tests/test_render_options.py tests/test_config.py tests/test_ui_reducers.py tests/test_ui_render.py tests/test_prove_graphics.py
git commit -m "feat: soft shadows on by default, with the proof and docs"
```
