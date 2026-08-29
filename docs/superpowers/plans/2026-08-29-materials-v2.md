# Materials v2 (Roadmap H) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the material table's procedural detail from a colour multiply into real relief, give skin a warm terminator, make ramp 14 actually emit, normalise the specular lobe, and put a human's eyes on the 23 palette ramps any body uses — all under `realism=enhanced`, with `classic` byte-identical throughout.

**Architecture:** `Material` gains three fields (`bump`, `sss`, `emissive`), taking `PARAMETER_COUNT` from 8 to 12 and the material texture from 256×2 to 256×3; `RealismPreset` gains the matching three strengths, uploaded as a new `preset_c` and all-zero under `classic`. A new `view` uniform (the `rotate · translate` half of `camera_matrix`) and a `v_view` varying give `ACTOR_FSH` a camera-space position, whose screen-space derivatives drive Mikkelsen's unparametrized bump — a normal perturbation that needs no tangent frame. The perturbed normal feeds every existing term, so grain catches the key instead of tinting it.

**Tech Stack:** Python 3.12, numpy, ModernGL 5.12 (GL 3.3 core GLSL), pygame-ce, pytest.

**Spec:** `docs/superpowers/specs/2026-08-29-actor-realism-roadmap-design.md` (sections "H. Materials v2", "Task ordering — H", "Testing — H", "Limitations").

## Global Constraints

- `# SPDX-License-Identifier: GPL-2.0-only` is the first line of every Python file.
- `make test` (headless: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`) must be green after every task. Baseline at the start of this plan: **1417 passed, 2 skipped, 1 xfailed, 26 warnings**. 26 is pre-existing; introduce none. No lint, formatter or typecheck exists; never mass-reformat.
- `classic + smoothing 0 + shadows hard` reproduces `tests/golden/scene_lit_classic.npy` byte for byte (`tests/test_render_gl.py::test_classic_realism_matches_the_pre_materials_golden`). `lighting="fixed"` renders byte-identically to today at every setting. **Every new shading term must collapse to exactly 1.0 or 0.0 under `classic` by construction, not by luck** — that is the existing file's discipline and the reason `classic` survives each addition.
- `skel.skin()`, `draw_list`, picking, masks, the mouse contract, the software backend and the background filter/override system are untouched.
- Layering (`tests/test_layering.py`): `render/` imports only `engine`; only `render_gl`, `render_soft`, `render`, `asset_resolver` may import pygame/moderngl. `materials.py` and `lighting.py` stay pure numpy; `glsl.py` stays strings only (`test_glsl_is_strings_only` allows a module docstring plus uppercase string assignments and nothing else).
- H adds **no new GL resources**: the material texture changes shape, not count. The leak-count assertion in `tests/test_render_gl.py` stays at **38**. A task that changes it has added something the plan did not ask for.
- Every uniform added to a shader must be seeded on **every program built from that shader**, through `_set_uniform` where the linker may drop it (the F review shipped a `0.0/0.0` on a program that never wrote a new uniform; do not repeat it).
- Run tests with the venv interpreter: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest ...`.
- Commit messages end with the repo's trailer block when authored with Claude:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01S9WYQ21wFZzQZ2xjzF3KtX
  ```

## Deviations from the spec, decided here

The spec's H section was written before F shipped. Three corrections, each load-bearing:

1. **The bump line as written is not `classic`-safe.** The spec gives
   `n = normalize(abs(det) * n - preset_c.x * m2.x * fade * grad);`.
   Under `classic` the subtrahend is zero but the line still evaluates
   `normalize(abs(det) * n)`, which is `n` mathematically and *not*
   guaranteed bit-identical. The golden would be at the driver's
   discretion. Task 2 therefore guards the perturbation with
   `if (preset_c.x > 0.0)`.
2. **That guard must branch on a uniform, not on the material.** `dFdx`,
   `dFdy` and `fwidth` are undefined inside non-uniform control flow, and
   `m2.x` comes from a texture fetch. All derivatives are computed at top
   level; only the assignment to `n` sits inside the branch. `preset_c.x`
   is a uniform, so the branch is uniform control flow and legal.
3. **`--check` is a stage, not a flag.** `tools/bootstrap_materials.py`
   already takes `stage` from `("survey", "label", "emit", "check")`. The
   command is `bootstrap_materials.py <data> check`, and it exists — task 4
   uses it rather than building it.

---

## File structure

| File | Responsibility | Task |
|---|---|---|
| `PyAitD/render/materials.py` | `Material.bump/sss/emissive`, `PARAMETER_COUNT = 12`, `RealismPreset` + three fields, `CLASS_PRESETS`/`PRESETS` retune | 1, 5 |
| `PyAitD/render/glsl.py` | `view` uniform and `v_view` varying in the three vertex shaders; the bump, sss, emissive and specular-normalisation terms in `ACTOR_FSH` | 1, 2, 3 |
| `PyAitD/render/render_gl.py` | the 256×3 texture, the `(3, 256, 4)` upload, `preset_c`, the `view` matrix and its seeding | 1 |
| `data/aitd1/materials-survey/survey.json` | the 23 hand `label`s | 4 |
| `PyAitD/render/materials.json` | re-emitted from the reviewed survey | 4 |
| `tests/test_materials.py` | field validation, `(256, 12)`, `classic` all-zero | 1, 5 |
| `tests/test_render_gl.py` | the transitional enhanced identity, relief-not-tint, the fade, emissive, sss, specular peak, lambert bump | 1, 2, 3 |
| `tests/test_bootstrap_materials.py` | `check` on the committed table | 4 |
| `docs/materials-v2-proof.md` (new), `CONTEXT.md`, `AGENTS.md`, `README.md` | proof and docs | 5 |

Conventions this plan follows: `ACTOR_FSH` is shared by `_actor_prog`, `_screen_prog` and `_tess_prog`, so a uniform added to it must be seeded on all three; `_screen_prog` never sees `_set_frame_uniforms`, so its constants are seeded at construction; the test helpers `_view`, `_palette`, `_scene_light`, `_lit_frame`, `_standing_actor`, `_facing_square`, `_plain_background`, `_golden_frame`, `_soft_frame_render` already exist and are reused.

---

### Task 1: The three fields, the 256×3 texture, `preset_c`, and the `view` plumbing — all at zero strength

**Files:**
- Modify: `PyAitD/render/materials.py` (`PARAMETER_COUNT` line 22, `Material` ~line 28, `parameters()` ~line 48, `MaterialTable.parameters()` ~line 93, `RealismPreset` ~line 155, `PRESETS` ~line 163)
- Modify: `PyAitD/render/glsl.py` (`ACTOR_VSH`, `TESS_VSH`, `SCREEN_VSH`, `ACTOR_FSH`'s uniform block)
- Modify: `PyAitD/render/render_gl.py` (`_material_tex` allocation ~line 336, `_upload_materials` ~line 1001, `_set_frame_uniforms` ~line 657, the `view` matrix)
- Test: `tests/test_materials.py`, `tests/test_render_gl.py`

**Interfaces:**
- Produces: `materials.PARAMETER_COUNT == 12`; `Material(roughness, specular, metallic, rim, detail, detail_scale, detail_kind, bump, sss, emissive)` with the three new fields defaulting to `0.0` and validated to `0.0 <= x <= 1.0`; `MaterialTable.parameters() -> (256, 12) float32`; `RealismPreset(spec, rim, ao, contact, detail, hemisphere, bump, sss, emissive)` with `PRESETS["classic"]` all zeros; shader uniform `preset_c: vec3` = `(bump, sss, emissive)`, `view: mat4`, varying `v_view: vec3`; `render_gl.view_matrix(view) -> (4,4) float32`.

- [ ] **Step 1: Write the failing pure tests**

Append to `tests/test_materials.py`:

```python
def test_the_three_new_fields_default_to_zero_and_validate():
    from PyAitD.render.materials import Material
    m = Material(1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0)
    assert (m.bump, m.sss, m.emissive) == (0.0, 0.0, 0.0)
    for field in ("bump", "sss", "emissive"):
        with pytest.raises(ValueError, match=field):
            Material(1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0, **{field: 1.5})
        with pytest.raises(ValueError, match=field):
            Material(1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0, **{field: -0.1})


def test_parameters_are_twelve_wide_and_in_range():
    from PyAitD.render.materials import PARAMETER_COUNT, default_table
    assert PARAMETER_COUNT == 12
    params = default_table().parameters()
    assert params.shape == (256, 12)
    assert params.dtype == np.float32
    # every field is 0..1 except detail_scale (FITD units) and detail_kind
    scaleless = np.delete(params, [5, 6], axis=1)
    assert scaleless.min() >= 0.0 and scaleless.max() <= 1.0
    assert (params[:, 5] > 0.0).all()


def test_classic_zeroes_every_preset_field_including_the_new_ones():
    from PyAitD.render.materials import PRESETS
    classic = PRESETS["classic"]
    assert (classic.spec, classic.rim, classic.ao) == (0.0, 0.0, 0.0)
    assert (classic.contact, classic.detail, classic.hemisphere) == (0.0, 0.0, 0.0)
    assert (classic.bump, classic.sss, classic.emissive) == (0.0, 0.0, 0.0)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_materials.py -q -k "new_fields or twelve_wide or classic_zeroes"`
Expected: FAIL — `TypeError: Material.__init__() got an unexpected keyword argument 'bump'` and `assert 8 == 12`.

- [ ] **Step 3: Widen `Material`**

In `PyAitD/render/materials.py`, change line 22 and the dataclass:

```python
PARAMETER_COUNT = 12  # 10 Material fields + two padding floats: three RGBA texels per index
```

Add three fields to `Material` after `detail_kind`, and extend `__post_init__` and `parameters()`:

```python
    detail_kind: int     # DETAIL_NONE .. DETAIL_BRUSHED
    bump: float = 0.0    # 0..1: how much the detail height field perturbs the normal
    sss: float = 0.0     # 0..1: warm terminator, the cheap stand-in for subsurface
    emissive: float = 0.0  # 0..1: the surface renders its palette colour whatever the light does

    def __post_init__(self):
        # (existing detail_scale check unchanged)
        if not self.detail_scale > 0:
            raise ValueError(f"detail_scale must be > 0, got {self.detail_scale!r}")
        # The shader multiplies each of these by a preset strength and by a
        # noise or wrap term; outside 0..1 they stop being a fraction of
        # anything and the classic-identity argument (strength 0 collapses
        # the term) no longer bounds what a bad table can do.
        for name in ("bump", "sss", "emissive"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be within 0..1, got {value!r}")

    def parameters(self):
        return np.array([self.roughness, self.specular, self.metallic, self.rim,
                         self.detail, self.detail_scale, float(self.detail_kind), 0.0,
                         self.bump, self.sss, self.emissive, 0.0], dtype=np.float32)
```

- [ ] **Step 4: Widen `RealismPreset`**

```python
@dataclass(frozen=True)
class RealismPreset:
    spec: float
    rim: float
    ao: float
    contact: float
    detail: float
    hemisphere: float
    bump: float = 0.0
    sss: float = 0.0
    emissive: float = 0.0


PRESETS = {
    "classic": RealismPreset(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    # bump/sss/emissive stay 0.0 here until Task 5's retune: Tasks 2 and 3
    # land the terms, and a term at zero strength cannot move a pixel.
    "enhanced": RealismPreset(spec=1.0, rim=0.6, ao=0.7, contact=1.0, detail=1.0, hemisphere=1.0),
}
```

- [ ] **Step 5: Run the pure tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_materials.py -q`
Expected: PASS.

- [ ] **Step 6: Capture the transitional enhanced identity**

`classic` has the golden; `enhanced` has nothing, and Task 5's retune moves it by design. So this task pins `enhanced` against *itself* across this task only. Append to `tests/test_render_gl.py`:

```python
# Transitional, and deliberately so: Task 1 of the materials-v2 plan adds
# fields, a texture row and three uniforms, all at zero strength, so the
# enhanced render must not move. Task 2 lands bump and retires this test --
# it is scaffolding for one task's blast radius, not a golden.
def test_enhanced_is_unmoved_by_the_material_plumbing(gl_ctx):
    plate = np.full((200, 320, 3), 200, np.uint8)
    actor = _standing_actor(0, _planned_geometry(_hex_prism_body()), feet_y=150)
    rendered = _soft_frame_render(gl_ctx, "soft", [actor], plate, (0.0, -0.5, 0.85),
                                  shading="smooth", realism="enhanced", level=2)
    expected = np.load(pathlib.Path(__file__).parent / "golden" / "enhanced_plumbing.npy")
    assert np.array_equal(rendered, expected)
```

Generate the fixture **before** touching the shaders — from the pre-change tree:

```bash
git stash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python - <<'PY'
import sys, numpy as np, moderngl, pathlib
sys.path.insert(0, ".")
from tests.test_render_gl import (_hex_prism_body, _planned_geometry,
                                  _standing_actor, _soft_frame_render)
ctx = moderngl.create_standalone_context(require=330)
plate = np.full((200, 320, 3), 200, np.uint8)
actor = _standing_actor(0, _planned_geometry(_hex_prism_body()), feet_y=150)
out = _soft_frame_render(ctx, "soft", [actor], plate, (0.0, -0.5, 0.85),
                         shading="smooth", realism="enhanced", level=2)
np.save("tests/golden/enhanced_plumbing.npy", out.astype(np.uint8))
ctx.release()
PY
git stash pop
```

Confirm `pathlib` is imported at the top of `tests/test_render_gl.py`; add it if not.

- [ ] **Step 7: Widen the texture and the upload**

In `PyAitD/render/render_gl.py`, the allocation:

```python
            self._material_tex = ctx.texture((PALETTE_SIZE, 3), 4, dtype="f4")
```

and `_upload_materials`'s reshape (docstring's `(256, 8)` becomes `(256, 12)`):

```python
        params = table.parameters()                      # (256, 12)
        rows = np.stack([params[:, :4], params[:, 4:8], params[:, 8:]], axis=0)   # (3, 256, 4)
        self._material_tex.write(np.ascontiguousarray(rows, dtype="f4").tobytes())
```

- [ ] **Step 8: Add the `view` matrix**

In `PyAitD/render/render_gl.py`, beside `camera_matrix` (~line 175):

```python
def view_matrix(view):
    """(4,4) float32 world -> camera space: `camera_matrix`'s `rotate @
    translate` half, without the projection.

    The fragment shader needs a camera-space *position* to take screen-space
    derivatives of (Mikkelsen's bump needs dP/dx and dP/dy, not a direction),
    and `rot` is rotation only -- it cannot carry the camera's translation.
    Kept next to `camera_matrix` because the two must agree: a change to the
    camera's rotation or translation convention has to land in both."""
    state = view.state
    translate = np.eye(4)
    translate[:3, 3] = (-state.x, -state.y, -state.z)
    rotate = np.eye(4)
    rotate[:3, :3] = rotation_matrix(state)
    return (rotate @ translate).astype(np.float32)
```

- [ ] **Step 9: Emit `v_view` from the three vertex shaders**

In `PyAitD/render/glsl.py`, `ACTOR_VSH` gains the uniform, the varying and one line:

```glsl
uniform mat4 light_vp; uniform float normal_offset;
// Camera-space position, for the fragment shader's screen-space
// derivatives. A direction would not do: bump needs dP/dx and dP/dy.
uniform mat4 view;
```
```glsl
out vec4 v_shadow; out vec3 v_view;
```
```glsl
    v_shadow = light_vp * vec4(in_pos + in_normal * normal_offset, 1.0);
    v_view = (view * vec4(in_pos, 1.0)).xyz;
```

`TESS_VSH` gains the same `uniform mat4 view;` and `out vec3 v_view;`, and one line beside its existing `v_world = pos;`:

```glsl
    v_world = pos;
    v_view = (view * vec4(pos, 1.0)).xyz;
```

`SCREEN_VSH` emits the degenerate value, as it already does for `v_shadow`:

```glsl
out vec4 v_shadow; out vec3 v_view;
```
```glsl
    v_shadow = vec4(0.0);   // lines and points never reach the term
    v_view = vec3(0.0);     // nor the derivative bump
}
```

- [ ] **Step 10: Declare the new fragment uniforms**

In `ACTOR_FSH`, extend the material comment and add `preset_c` and the varying. Do **not** read them yet:

```glsl
// Materials (scene lighting only). material_tex is 256x3 RGBA32F: row 0 is
// (roughness, specular, metallic, rim), row 1 (detail, detail_scale,
// detail_kind, 0), row 2 (bump, sss, emissive, 0) for the palette index in
// v_index. preset_a/preset_b/preset_c are the RealismPreset strengths
// (spec, rim, ao), (contact, detail, hemisphere) and (bump, sss, emissive);
// under realism=classic all nine are 0 and every term below is exactly 1.0
// or 0.0, leaving `base` untouched.
uniform sampler2D material_tex;
uniform vec3 preset_a; uniform vec3 preset_b; uniform vec3 preset_c;
```
```glsl
in vec4 v_shadow; in vec3 v_view;
```

- [ ] **Step 11: Seed and write the new uniforms**

In `_set_frame_uniforms`, beside the existing preset writes:

```python
            prog["preset_a"].value = (preset.spec, preset.rim, preset.ao)
            prog["preset_b"].value = (preset.contact, preset.detail, preset.hemisphere)
            _set_uniform(prog, "preset_c", (preset.bump, preset.sss, preset.emissive))
```

and in the `classic`/unlit branch:

```python
            prog["preset_a"].value = (0.0, 0.0, 0.0)
            prog["preset_b"].value = (0.0, 0.0, 0.0)
            _set_uniform(prog, "preset_c", (0.0, 0.0, 0.0))
```

Write `view` once per frame beside `mvp` in `_draw_frame`, for every program built from `ACTOR_VSH` or `TESS_VSH`, through `_set_uniform` — `_tess_shadow_prog` and `_cast_prog` are built from `TESS_VSH` with fragment stages that read no varying, so a linker may drop `view` there:

```python
        view_m = view_matrix(frame.camera)
        for prog in (self._actor_prog, self._tess_prog, self._tess_shadow_prog, self._cast_prog):
            _set_uniform(prog, "view", np.ascontiguousarray(view_m.T))
```

`_set_uniform` already writes an ndarray with `.write(value.tobytes())`; `.T` matches the column-vector convention `mvp` uses.

- [ ] **Step 12: Run the identity net**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py tests/test_materials.py tests/test_layering.py -q`
Expected: PASS, including `test_classic_realism_matches_the_pre_materials_golden` and the new `test_enhanced_is_unmoved_by_the_material_plumbing`.

If the golden moves here, stop and report: nothing in this task may read a new uniform, so a moved golden means a shader edit changed an existing expression rather than adding to it.

- [ ] **Step 13: Run the full suite and commit**

Run: `make test`
Expected: 1420 passed (1417 + 3 new pure tests + 1 GL test − nothing removed; confirm the exact number and use what you observe), 2 skipped, 1 xfailed, 26 warnings.

```bash
git add PyAitD/render/materials.py PyAitD/render/glsl.py PyAitD/render/render_gl.py \
        tests/test_materials.py tests/test_render_gl.py tests/golden/enhanced_plumbing.npy
git commit -m "feat: material bump/sss/emissive fields and the view plumbing, all at zero strength"
```

---

### Task 2: Bump — relief instead of dirt

**Files:**
- Modify: `PyAitD/render/glsl.py` (`ACTOR_FSH`'s `main`, between the normal orientation and `wrapped`)
- Modify: `PyAitD/render/materials.py` (`PRESETS["enhanced"]` gains `bump=1.0`)
- Test: `tests/test_render_gl.py`

**Interfaces:**
- Consumes: `preset_c.x`, `m2.x`, `v_view`, `v_rest`, `m1.x`/`m1.y`/`m1.z` from Task 1.
- Produces: a perturbed `n` feeding `wrapped`, `hemi`, `spec` and `rim`; `PRESETS["enhanced"].bump == 1.0`. Retires `test_enhanced_is_unmoved_by_the_material_plumbing` and `tests/golden/enhanced_plumbing.npy`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_render_gl.py`. `_facing_square` already gives a flat, camera-facing quad; two of them differing only in `rest` is the relief-not-tint case:

```python
def _material_square(gl_ctx, table, z=600.0, realism="enhanced", shading="smooth"):
    """A camera-facing square lit by the scene light, with `table` as its
    material table. Returns the rendered frame."""
    plate = np.full((200, 320, 3), 200, np.uint8)
    geometry = _facing_square(z, 1, (0.0, 0.0, -1.0), span=300.0)
    actor = ActorDraw(0, geometry, (0.0, 0.0, 0.0), 0, (0, 0, 0, 200, 0, 0),
                      RenderResult([], []), (), materials=table)
    return _soft_frame_render(gl_ctx, "hard", [actor], plate, (0.0, -0.5, 0.85),
                              shading=shading, realism=realism)


def _one_class_table(name):
    from PyAitD.render.materials import MaterialTable
    return MaterialTable((name,) * 256)


def test_bump_is_relief_not_tint(gl_ctx):
    # The old grain multiplied the colour, so it changed a surface's mean
    # brightness. Relief moves light around instead: pixel to pixel it must
    # differ, but the patch's mean luminance must stay put.
    from PyAitD.render.materials import CLASS_PRESETS, Material, MaterialTable
    body = (slice(70, 130), slice(120, 200))
    flat = _material_square(gl_ctx, _one_class_table("matte"))
    stony = _material_square(gl_ctx, _one_class_table("stone"))
    flat_patch = flat[body].astype(float)
    stony_patch = stony[body].astype(float)
    assert stony_patch.std() > flat_patch.std() + 1.0          # relief varies
    assert abs(stony_patch.mean() - flat_patch.mean()) < 0.01 * flat_patch.mean()


def test_bump_fades_out_with_distance(gl_ctx):
    # fwidth of the noise coordinate crosses half a cell as the surface
    # recedes, and `fade` takes the perturbation to zero before the relief
    # can alias into shimmer.
    near = _material_square(gl_ctx, _one_class_table("stone"), z=600.0)
    far = _material_square(gl_ctx, _one_class_table("stone"), z=6000.0)
    near_body = near[70:130, 120:200].astype(float)
    far_body = far[95:105, 155:165].astype(float)
    assert near_body.std() > 1.0
    assert far_body.std() < 0.5


def test_lambert_shading_gets_the_bump_too(gl_ctx):
    # lambert derives n from gl_FragCoord derivatives; the perturbation is
    # applied after that choice, so it must reach both paths.
    plain = _material_square(gl_ctx, _one_class_table("matte"), shading="lambert")
    stony = _material_square(gl_ctx, _one_class_table("stone"), shading="lambert")
    assert not np.array_equal(plain, stony)
```

`ActorDraw.materials` is the last field, `MaterialTable`, defaulting to `default_table()` — so `materials=table` is the whole of what a test needs to give a square its own material.

- [ ] **Step 2: Run them to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q -k "bump or lambert_shading_gets"`
Expected: FAIL — `stony_patch.std()` is not above `flat_patch.std()` (no relief exists yet; `stone`'s detail is still only a colour multiply, which moves the mean rather than the variance).

- [ ] **Step 3: Add the bump block**

In `ACTOR_FSH`, immediately after the `if (n.z > 0.0) n = -n;` orientation and **before** `float vis = 1.0;`:

```glsl
    // Mikkelsen's unparametrized bump: perturb the normal by the screen-space
    // gradient of a height field, using derivatives of the camera-space
    // position instead of a tangent frame. FITD bodies carry no UVs and no
    // tangents, so this is the only bump that is available at all.
    //
    // Every derivative is taken here, at top level. dFdx/dFdy/fwidth are
    // undefined inside non-uniform control flow, and both `h` and `m2.x`
    // come from texture-dependent values -- so the *branch* below tests
    // preset_c.x, a uniform, and only the assignment to `n` sits inside it.
    // That branch is also what keeps realism=classic byte-exact: the
    // spec's unguarded form still evaluates normalize(abs(det) * n), which
    // is n mathematically but not bit-for-bit.
    vec4 m2 = texelFetch(material_tex, ivec2(index, 2), 0);
    float h = m1.x * detail_noise(v_rest / m1.y, int(m1.z + 0.5));
    vec3 sx = dFdx(v_view), sy = dFdy(v_view);
    vec3 r1 = cross(sy, n), r2 = cross(n, sx);
    float det = dot(sx, r1);
    vec2 dh = vec2(dFdx(h), dFdy(h));
    vec3 grad = sign(det) * (dh.x * r1 + dh.y * r2);
    // One noise cell shrinking toward half a pixel is relief the frame
    // cannot resolve; fading it out there is what stops a hero shimmering
    // as he walks away.
    vec3 fw = fwidth(v_rest / m1.y);
    float fade = 1.0 - smoothstep(0.25, 0.5, max(fw.x, max(fw.y, fw.z)));
    if (preset_c.x > 0.0) {
        n = normalize(abs(det) * n - preset_c.x * m2.x * fade * grad);
    }
```

`index`, `m1` and `m2` are fetched above this block in the shipped file; move the `int index = ...` / `m0` / `m1` fetches up to just before it if they currently sit lower, keeping their expressions identical.

- [ ] **Step 4: Turn `bump` on for `enhanced`**

In `PyAitD/render/materials.py`:

```python
    "enhanced": RealismPreset(spec=1.0, rim=0.6, ao=0.7, contact=1.0, detail=1.0,
                              hemisphere=1.0, bump=1.0),
```

Give every textured class a `bump` in `CLASS_PRESETS` — a first pass, retuned in Task 5:

```python
    "skin":     Material(0.7, 0.15, 0.0, 0.25, 0.15, 40.0, DETAIL_GRAIN, bump=0.3),
    "cloth":    Material(0.9, 0.05, 0.0, 0.35, 0.08, 12.0, DETAIL_WEAVE, bump=0.8),
    "leather":  Material(0.5, 0.35, 0.0, 0.3, 0.2, 30.0, DETAIL_GRAIN, bump=0.7),
    "hair":     Material(0.6, 0.3, 0.0, 0.4, 0.3, 8.0, DETAIL_STREAK, bump=0.8),
    "wood":     Material(0.6, 0.2, 0.0, 0.1, 0.35, 60.0, DETAIL_STREAK, bump=0.6),
    "stone":    Material(0.85, 0.05, 0.0, 0.05, 0.3, 50.0, DETAIL_GRAIN, bump=0.9),
    "metal":    Material(0.25, 0.8, 0.8, 0.2, 0.15, 25.0, DETAIL_BRUSHED, bump=0.5),
```

- [ ] **Step 5: Retire the transitional check**

Delete `test_enhanced_is_unmoved_by_the_material_plumbing` and `tests/golden/enhanced_plumbing.npy` — bump moves `enhanced` by design, which is exactly what that test existed to bound.

```bash
git rm tests/golden/enhanced_plumbing.npy
```

- [ ] **Step 6: Run the tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py tests/test_materials.py -q`
Expected: PASS, the golden included — `classic` never enters the branch.

If `test_bump_is_relief_not_tint`'s mean-luminance bound fails, report the measured means rather than widening the bound: a mean that moves means the colour multiply is still doing the work, which is the thing this task replaces.

- [ ] **Step 7: Full suite and commit**

Run: `make test`

```bash
git add PyAitD/render/glsl.py PyAitD/render/materials.py tests/test_render_gl.py
git commit -m "feat: derivative bump, so material detail is relief that catches the key"
```

---

### Task 3: The sss terminator, the emissive mix, and the specular normalisation

**Files:**
- Modify: `PyAitD/render/glsl.py` (`ACTOR_FSH`: `SSS_TINT`, the `base` tint, the `spec` term, the final `f_color`)
- Modify: `PyAitD/render/materials.py` (`PRESETS["enhanced"]` gains `sss` and `emissive`; `CLASS_PRESETS` gives `skin` an `sss` and `emissive` an `emissive`)
- Test: `tests/test_render_gl.py`

**Interfaces:**
- Consumes: `preset_c.y`, `preset_c.z`, `m2.y`, `m2.z`, `wrapped`, `gloss` from Tasks 1-2.
- Produces: `SSS_TINT` = `vec3(1.0, 0.82, 0.74)`; a normalised Blinn-Phong lobe; `f_color.rgb` mixed toward `v_color` by `preset_c.z * m2.z`.

- [ ] **Step 1: Write the failing tests**

```python
def test_skin_warms_at_the_terminator(gl_ctx):
    # The sss tint peaks where wrapped is 0.5 -- the light/shade boundary --
    # and vanishes on both the fully lit and fully unlit sides, so skin is
    # redder than matte *there* and the same everywhere else.
    skin = _material_square(gl_ctx, _one_class_table("skin"))
    matte = _material_square(gl_ctx, _one_class_table("matte"))
    def redness(img, rows, cols):
        patch = img[rows, cols].astype(float)
        return patch[..., 0].mean() / max(patch[..., 1].mean(), 1e-6)
    # a sphere would give a clean terminator; on a flat square the whole
    # face shares one `wrapped`, so tilt the light to put the boundary in
    # frame and sample the band where the two renders differ most.
    diff = np.abs(skin.astype(int) - matte.astype(int)).sum(axis=2)
    band_rows = np.argsort(diff.sum(axis=1))[-10:]
    assert redness(skin, band_rows, slice(None)) > redness(matte, band_rows, slice(None))


def test_an_emissive_surface_renders_its_palette_colour(gl_ctx):
    # Ramp 14 is a flame: it must not go dark when the key turns away.
    away = (0.0, -0.5, -0.85)           # light pointing away from the face
    lit = _material_square(gl_ctx, _one_class_table("emissive"))
    unlit = _soft_frame_render(
        gl_ctx, "hard", [_emissive_actor()], np.full((200, 320, 3), 200, np.uint8),
        away, shading="smooth", realism="enhanced")
    body = (slice(85, 115), slice(140, 180))
    assert np.abs(lit[body].astype(int) - unlit[body].astype(int)).max() <= 1


def test_a_tight_highlight_peaks_brighter_than_a_broad_one(gl_ctx):
    # Blinn-Phong without its (gloss + 8) / 8pi normalisation spreads a
    # low-roughness lobe so thin it reads dimmer than a broad one, which is
    # backwards: the same energy in a smaller cone must be brighter.
    from PyAitD.render.materials import Material, MaterialTable, DETAIL_NONE
    def peak(roughness):
        table = MaterialTable(("matte",) * 256)
        with _class_preset("matte", Material(roughness, 0.8, 0.0, 0.0, 0.0, 1.0, DETAIL_NONE)):
            return _material_square(gl_ctx, table).max()
    assert peak(0.2) > peak(0.8)
```

`_emissive_actor` and `_class_preset` are helpers this task adds: the first is `_material_square`'s actor with the emissive table, the second a context manager that swaps one `CLASS_PRESETS` entry and restores it — and, per `_upload_materials`'s docstring, hands out a **fresh** `MaterialTable` each time so the identity cache cannot serve stale parameters. Write both beside the tests.

- [ ] **Step 2: Run them to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q -k "terminator or emissive or highlight_peaks"`
Expected: FAIL — skin and matte are equally red, the emissive square goes dark when the light turns away, and the tight highlight is dimmer than the broad one.

- [ ] **Step 3: Add the three terms**

In `ACTOR_FSH`, beside the other file-scope constants:

```glsl
// Warm blood under thin skin: the tint the terminator picks up. One
// constant, not a material field -- the hue is a property of people, not
// of this palette index.
const vec3 SSS_TINT = vec3(1.0, 0.82, 0.74);
```

After `base` is computed:

```glsl
    // Peaks at the light/shade boundary (wrapped 0.5, where 4x(1-x) is 1)
    // and vanishes on both the fully lit and the fully unlit side. Under
    // classic preset_c.y is 0, mix(a, b, 0) is exactly a, and base is
    // untouched.
    base *= mix(vec3(1.0), SSS_TINT, preset_c.y * m2.y * 4.0 * wrapped * (1.0 - wrapped));
```

The `spec` line gains the normalisation factor:

```glsl
    // Blinn-Phong's lobe integrates to less as it tightens, so without
    // (gloss + 8) / 8pi a polished metal reads *dimmer* than a rough one.
    // preset_a.x already zeroes the whole term under classic.
    vec3 spec = key_tint * mix(vec3(1.0), v_color, m0.z) * pow(max(dot(n, h), 0.0), gloss)
              * ((gloss + 8.0) / (8.0 * 3.14159265)) * m0.y * preset_a.x * vis;
```

And the final line mixes toward the raw palette colour:

```glsl
    vec3 shaded = base * (grain * hemi * occl) + spec + rim;
    // mix(x, y, 0) is x*(1-0) + y*0 -- exactly x -- so classic is untouched
    // by construction, the same argument the hemisphere term relies on.
    f_color = vec4(mix(shaded, v_color, preset_c.z * m2.z), 1.0);
```

- [ ] **Step 4: Turn the terms on for `enhanced`**

```python
    "enhanced": RealismPreset(spec=1.0, rim=0.6, ao=0.7, contact=1.0, detail=1.0,
                              hemisphere=1.0, bump=1.0, sss=1.0, emissive=1.0),
```

and in `CLASS_PRESETS`:

```python
    "skin":     Material(0.7, 0.15, 0.0, 0.25, 0.15, 40.0, DETAIL_GRAIN, bump=0.3, sss=1.0),
    # No longer a label only: emissive renders its palette colour whatever
    # the light does, which is what ramp 14's flames need.
    "emissive": Material(1.0, 0.0, 0.0, 0.0, 0.0, 1.0, DETAIL_NONE, emissive=1.0),
```

Delete the `# A label only: no emissive term exists in the shader` comment above `emissive` — it is now false.

- [ ] **Step 5: Run the tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py tests/test_materials.py -q`
Expected: PASS, golden included.

- [ ] **Step 6: Full suite and commit**

Run: `make test`

```bash
git add PyAitD/render/glsl.py PyAitD/render/materials.py tests/test_render_gl.py
git commit -m "feat: a warm skin terminator, real emissive, and a normalised specular lobe"
```

---

### Task 4: The human review of the 23 used ramps

**This task needs the user's eyes and cannot be completed by an agent alone.** An implementer runs the mechanics and prepares the evidence; the labelling decisions are the user's. Stop and hand over at Step 2.

**Files:**
- Modify: `data/aitd1/materials-survey/survey.json` (the `class` field of the 23 ramps with `usage.triangles > 0`)
- Modify: `PyAitD/render/materials.json` (re-emitted)
- Test: `tests/test_bootstrap_materials.py`

**Interfaces:**
- Consumes: the shipped survey and its `sheets/ramp<lo>-<hi>.png` highlights.
- Produces: a reviewed `materials.json` that `bootstrap_materials.py <data> check` passes.

- [ ] **Step 1: Assemble the review sheet**

The survey holds 55 ramps; only 23 are used by any body, and **all 23 sit below the 0.8 confidence threshold**, so every one is a genuine question rather than a confident answer. The shipped table uses only 6 of the 10 classes — no `glass`, `wood`, `hair` or `emissive` appears anywhere, which is why the spec names three corrections up front.

Run this to produce the list the user reviews:

```bash
.venv/bin/python - <<'PY'
import json, pathlib
survey = json.loads(pathlib.Path("data/aitd1/materials-survey/survey.json").read_text())
used = [r for r in survey["ramps"] if r["usage"].get("triangles", 0) > 0]
used.sort(key=lambda r: -r["usage"]["triangles"])
print(f"{len(used)} ramps in use\n")
for r in used:
    print(f"ramp {r['lo']:3d}-{r['hi']:3d}  class={r['class']:<9} conf={r['confidence']:.2f} "
          f"tris={r['usage']['triangles']:5d}  {r['highlight']}")
    print(f"    bodies: {', '.join(r['usage']['bodies'][:8])}"
          f"{' ...' if len(r['usage']['bodies']) > 8 else ''}")
    print(f"    why: {r['reason']}")
PY
```

- [ ] **Step 2: Hand over to the user**

Present the list with the three known corrections called out, and ask them to open `data/aitd1/materials-survey/sheets/ramp<lo>-<hi>.png` (the ramp's triangles tinted magenta on the bodies that use it) for each ramp and give a class from `MATERIAL_CLASSES` — `matte, skin, cloth, leather, hair, wood, stone, metal, glass, emissive`. Known going in, from the spec:

- ramp 15–31 → `skin`
- the attic window panes and the lantern chimney → `glass`
- ramp 14 → `emissive` (confirmed)

Flag the structural limit while they review: a ramp that is skin on one body and wood on another stays wrong on one of them until a per-body override under `DIR/bodies/body<NNN>.json` says otherwise. The `bodies` list printed above is where to look for that; note any ramp whose bodies disagree rather than forcing one answer.

- [ ] **Step 3: Write the labels back**

For each ramp the user reclassified, set `class` on that entry in `data/aitd1/materials-survey/survey.json`. Hand labels carry forward through a re-survey, which `tests/test_bootstrap_materials.py` already pins.

- [ ] **Step 4: Re-emit and check**

```bash
make bootstrap-materials
.venv/bin/python tools/bootstrap_materials.py "data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK" check
```
Expected: `check` passes against the newly emitted `PyAitD/render/materials.json`.

Note that `make bootstrap-materials` runs the `survey` and `emit` stages and needs real game data; it does **not** run `label` unless `vision=1`, so it will not overwrite the user's hand labels with a model's.

- [ ] **Step 5: Pin the committed table**

Add to `tests/test_bootstrap_materials.py`:

```python
def test_the_committed_table_matches_the_reviewed_survey(tmp_path):
    """`check` is the gate that stops materials.json drifting from the
    survey it was emitted from -- a hand label that never made it into the
    table would otherwise be invisible."""
    from PyAitD.render.materials import default_table, MATERIAL_CLASSES
    classes = set(default_table().classes)
    assert classes <= set(MATERIAL_CLASSES)
    # The review put eyes on every ramp any body uses; glass and emissive
    # were absent from the model's answer and are the two the spec names.
    assert {"skin", "glass", "emissive"} <= classes
```

If the user's review does not in fact produce `glass` or `emissive`, drop them from that assertion and say so — the test records what the review decided, not what the plan predicted.

- [ ] **Step 6: Run and commit**

Run: `make test`

```bash
git add data/aitd1/materials-survey/survey.json PyAitD/render/materials.json tests/test_bootstrap_materials.py
git commit -m "fix: hand-review the 23 palette ramps any body actually uses"
```

Note `data/aitd1/materials-survey/` is git-ignored via the `materials-survey/` rule — `git add` the survey explicitly with `-f` if git refuses, or, if the user prefers it stay out of the repo, commit only `PyAitD/render/materials.json` and record the labels in the proof document. Ask rather than force it.

---

### Task 5: Retune, the proof document, and the docs

**Files:**
- Modify: `PyAitD/render/materials.py` (`CLASS_PRESETS`, `PRESETS["enhanced"]`)
- Create: `docs/materials-v2-proof.md`
- Modify: `README.md` (the `--realism` clause ~line 79), `AGENTS.md` (the `render/` conventions bullet), `CONTEXT.md` (the `render/materials.py` row and the "Where we are" table)
- Test: `tests/test_materials.py`

**Interfaces:**
- Consumes: everything from Tasks 1-4.
- Produces: the tuned tables and `docs/materials-v2-proof.md`.

- [ ] **Step 1: Render the fixtures**

```bash
make proof-graphics
```
Sixteen PNGs under `docs/graphics-proof/` (git-ignored). The `-enhanced` renders are what this task tunes against; their `-classic` twins must be unchanged from before this plan.

- [ ] **Step 2: Tune by eye, against the spec's criteria**

Adjust `CLASS_PRESETS`' `bump`, `detail`, `detail_scale`, `sss`, `specular` and `roughness`, and `PRESETS["enhanced"]`'s strengths, until:

- skin reads smooth with a soft highlight and a warm terminator;
- cloth's weave is relief, not stripes;
- wood is streaked;
- metal is brushed with a real highlight;
- glass is rimmed and glossy;
- nothing shimmers when the hero walks away at scale 4.

Re-render after each change. Record the final numbers and what each was traded against in the proof document — the tuning is by eye and the record is the only thing that makes it reviewable.

- [ ] **Step 3: Pin the tuned invariants**

```python
def test_every_class_keeps_its_parameters_in_range_after_the_retune():
    from PyAitD.render.materials import CLASS_PRESETS
    for name, material in CLASS_PRESETS.items():
        for field in ("roughness", "specular", "metallic", "rim", "detail", "bump", "sss", "emissive"):
            value = getattr(material, field)
            assert 0.0 <= value <= 1.0, f"{name}.{field} = {value}"
        assert material.detail_scale > 0.0, name


def test_only_emissive_emits():
    from PyAitD.render.materials import CLASS_PRESETS
    emitting = {n for n, m in CLASS_PRESETS.items() if m.emissive > 0.0}
    assert emitting == {"emissive"}
```

- [ ] **Step 4: Write the proof document**

Create `docs/materials-v2-proof.md` on the pattern of `docs/soft-shadows-proof.md`, with these sections and nothing invented:

- **What changed** — bump, sss, emissive, the specular normalisation, the reviewed table, in a paragraph.
- **Automated gates** — the real pasted output of the focused run and of `make test`.
- **The ramp review** — the 23 ramps, their before and after classes, and who decided. Name any ramp whose bodies disagreed and what was chosen.
- **`make proof-graphics`** — what the `-enhanced` renders show against their `-classic` twins, per material class.
- **Retune** — the final numbers and what each was traded against.
- **Known limitations** — carried from the spec: derivative bump is per 2×2 quad, faintly blocky at scale 1 and invisible at 4; distant actors lose relief by design; the review is a human step; detail is still shape-free (no seams, planks or buttons); anisotropy and plate reflections were dropped as not worth their cost at this scale.
- **Manual attestation** — a table of `pending` rows for what only a human at a window can confirm, with the same preamble `docs/soft-shadows-proof.md` uses.

- [ ] **Step 5: Update the docs**

- `README.md`: the `--realism` clause currently says `enhanced` gives every surface "specular, rim, occlusion and grain". Grain is now relief; add bump, the warm skin terminator and emissive.
- `AGENTS.md`: the `render/` conventions bullet gains a sentence on `materials.py` owning the 12 parameters and the three presets, and on `preset_c` being the classic/enhanced switch for the new terms.
- `CONTEXT.md`: the `render/materials.py` row and the "Where we are" table.

- [ ] **Step 6: Full suite and commit**

Run: `make test`

```bash
git add PyAitD/render/materials.py tests/test_materials.py docs/materials-v2-proof.md \
        README.md AGENTS.md CONTEXT.md
git commit -m "feat: retune the material classes for relief, and the materials-v2 proof"
```

---

## Self-review

**Spec coverage.** "Relief instead of dirt" → Task 2 (with the two `classic`-safety corrections recorded above). "Fields and terms" → Task 1 (fields, `PARAMETER_COUNT`, 256×3, `preset_c`) and Task 3 (skin, emissive, specular normalisation). "The human pass over the table" → Task 4. "Retune" → Task 5. "Dropped" needs no task. "Testing — H" maps as: the three-field validation and `(256, 12)` and all-zero `classic` → Task 1 Step 1; relief-not-tint and the distance fade and lambert bump → Task 2 Step 1; emissive, sss redness and the specular peak → Task 3 Step 1; `check` on the committed table → Task 4 Step 5.

**Placeholder scan.** Two steps deliberately defer to observation rather than assert a number: Task 1 Step 13's test count ("confirm the exact number and use what you observe") and Task 5's tuning, which is by eye by the spec's own design. Both name exactly what to do and what to record. The two names the first draft asked an implementer to look up have since been resolved into the plan: `ActorDraw.materials` (last field, `MaterialTable`, defaulting to `default_table()`) and `TESS_VSH`'s `v_world = pos;`.

**Type consistency.** `Material`'s three new fields are keyword-with-default throughout, so every existing positional construction in `CLASS_PRESETS` and in tests keeps working. `RealismPreset` likewise. `parameters()` is 12 wide in `Material`, `MaterialTable.parameters()` and the `(3, 256, 4)` reshape. `preset_c` is `(bump, sss, emissive)` in the dataclass, the uploader and the shader. `view_matrix(view)` is named the same in its definition and its one call site.

**Known risk to watch.** `tests/test_render_gl.py:1172` builds a transform-feedback program from `TESS_VSH` with `varyings=["v_world", "v_normal"]`. Adding `v_view` does not change that capture list, but it does add a `view` uniform to that program; if the linker keeps it and the test never writes it, the value is zero — harmless there, since `v_view` is not captured. Task 1 Step 11 seeds `view` through `_set_uniform` on the backend's programs; the test program needs nothing.
