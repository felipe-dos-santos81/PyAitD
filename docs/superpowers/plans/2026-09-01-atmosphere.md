# Atmosphere (Roadmap 2, Sub-project L) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the composite know how deep each actor pixel is, and use that depth for distance haze and a mild depth grade on softness and grain — so far actors finally separate from near ones in the caves and long halls.

**Architecture:** The actor layer gains a second render target carrying linear camera depth (MRT), resolved alongside colour through both the MSAA and the non-MSAA path. `COMPOSITE_FSH` reads it, shifts actor colour toward the room's ambient tone by `1 − exp(−HAZE_DENSITY · max(0, depth − HAZE_START))`, and scales the integration blur's sigma and the grain gain mildly upward with depth. Every term is gated by coverage and vanishes when its tunable is zero, so the whole feature is an identity by construction before the knob flips.

**Tech Stack:** Python 3.12, numpy, moderngl, GLSL 330. No new dependency.

**Spec:** `docs/superpowers/specs/2026-08-31-actor-realism-roadmap-2-design.md` (sub-project L, plus its "Options, UI and tooling", "Task ordering", "Testing" and "Limitations" sections). Read the spec's L section before starting.

**Predecessor:** this plan assumes sub-project K (`docs/superpowers/plans/2026-09-01-light-transport.md`) has landed, because K adds the Realism page's sixth row and L adds the seventh. If K has not landed, L's Task 1 is still correct — it appends its row after whatever is there — but the row indices in its tests must be adjusted, and the `REALISM_ROWS` value it asserts will be one lower.

## Global Constraints

- **Runtime dependencies stay exactly pygame-ce + moderngl + numpy.** L adds none.
- **`atmosphere="off"` runs today's code verbatim**, byte for byte. The knob lands off and flips in Task 4.
- **All new behaviour lives under `lighting="scene"`.** `lighting="fixed"` stays the whole legacy renderer, byte for byte, at every combination of the new options.
- **Atmosphere applies only under `integration > 0`.** The composite pass is where every term lives; at `integration = 0` there is no composite to modify, and the knob must be inert rather than partially applied.
- **`tests/golden/scene_lit_classic.npy` must keep passing and must never be regenerated.**
- **The neutral identity is stronger than the knob.** With `atmosphere="on"` and the tunables zeroed, the golden must still hold at `msaa = 0`. Build every term as `x + k * f(depth)` or `x * (1 + k * f(depth))` so `k = 0` collapses it exactly, the way `NEUTRAL_PLATE` makes the whole composite an identity by construction rather than by rounding (`PyAitD/render/plate.py:46-50`).
- `skel.skin()`, `draw_list`, picking, masks, the mouse contract and all simulation code stay untouched.
- **`PyAitD/render/glsl.py` is strings only** — pinned by `tests/test_layering.py::test_glsl_is_strings_only`.
- **Every new GL resource is released in `release()` and counted by the leak test** (`tests/test_render_gl.py::test_init_failure_releases_every_already_allocated_gl_object`, which asserts an exact `leak_checked` total).
- Every source file starts with `# SPDX-License-Identifier: GPL-2.0-only`.
- Every test file carries exactly one subject marker; `--strict-markers` is on. Edits to existing test files keep their marker.
- Run the full gate before calling any task done: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q`.
- Commit after every task with a `feat:`/`test:`/`docs:` message as shown.

## Verified facts this plan is built on

Checked against the real code and a real GL context on the target machine (macOS arm64, CPython 3.12, Apple M3 Max, GL 4.1 Metal - 90.5). Do not re-derive them; do check them if something surprises you.

| Fact | Evidence |
|---|---|
| **A two-output fragment shader renders correctly against a one-attachment FBO** — attachment 0 is unaffected and the extra output is discarded | probed; this is what lets `ACTOR_FSH` emit depth unconditionally without breaking `_screen_prog`'s single-attachment targets |
| **`ctx.copy_framebuffer(dst, ms_fbo)` resolves *both* colour attachments** when source and destination each carry two | probed with an RGBA8 + RGBA32F pair |
| Single-attachment FBO "views" over the same renderbuffers also resolve per attachment, if a per-attachment resolve is ever needed | probed |
| `GL_MAX_COLOR_ATTACHMENTS` and `GL_MAX_DRAW_BUFFERS` are both **8** | probed |
| `ctx.max_samples` is **4**, so `msaa=8` clamps; `self.samples = min(options.msaa, ctx.max_samples)` already handles it | `render_gl.py:456`, probed |
| The actor layer is **premultiplied**: its shader writes alpha 1, and the multisample resolve of covered and uncovered samples yields colour already scaled by coverage | `glsl.py:510-517` (COMPOSITE_FSH's own header comment) |
| At `msaa = 0` alpha is 0 or 1 and the composite is `plate` or `rgb` with no arithmetic between — the identity every composing level holds against level 0 | same |
| Every glsl constant is imported into render_gl.py with a leading-underscore alias (`STENCIL_VSH as _STENCIL_VSH`) | `render_gl.py:34` |
| The composite's blur is `sample_actor(p, size)`, weights `exp(-(dx²+dy²) * inv_sigma2)`, normalised by the weight actually accumulated | `glsl.py:609-631` |
| **`radius` is a uniform and the comment says so explicitly**: "uniform control flow and the tap count is the same for every pixel of the frame" | `glsl.py:620-622` |
| `sigma`, `radius` and `inv_sigma2` are computed CPU-side, with `radius = min(MAX_BLUR_RADIUS, ceil(2*sigma))` | `render_gl.py:1195-1199` |
| The grain term is `c += plate_grain * strength * dither(gl_FragCoord.xy) * GAIN` | `glsl.py:646` |
| `SceneLight.ambient` is "0..1 linear RGB: what an unlit surface looks like" — the room's ambient tone | `PyAitD/render/lighting.py:50-54` |
| `PlateProfile` is `black`/`white`/`grain`; `NEUTRAL_PLATE` makes the composite an identity by construction | `PyAitD/render/plate.py:40-50` |
| `_actor_tex`/`_actor_fbo` share `self._depth` rather than allocating a second depth renderbuffer | `render_gl.py:467-481` |
| `_actor_tex` is bound at unit 6 and `_plate_tex` at unit 5 in `_composite`; **units 7+ are free** (K takes 7 and 8 if it has landed) | `render_gl.py:1236-1237` |
| `RenderOptions`'s fields end with `motion` (or `occlusion` after K); a new field must be appended last to keep positional construction working | `PyAitD/render/render_options.py:47-59` |
| `_MENU_RENDER_FIELDS` gates which fields a settings save persists | `PyAitD/app/shell.py:676` |
| The Realism page fits 8 rows, ending at y=186 inside the 200-row screen | `PyAitD/app/ui.py:693-697`; `tests/test_ui_render.py:823-834` asserts it dynamically |
| The leak test enumerates named attributes plus 4 subpatch buffers and asserts an exact `leak_checked` total (44 before K) | `tests/test_render_gl.py:839-882` |

**Two design decisions this plan makes, and why.**

1. **Depth is graded from the *centre* pixel's own depth, fetched directly — never from blurred depth.** The blur's weights depend on the grade, so grading from a blurred value would be circular. `texelFetch` the centre depth first, derive the grade, then blur.
2. **The depth-graded softness scales `inv_sigma2`, never `radius`.** `radius` is a uniform whose constancy the composite's own comment relies on for uniform control flow; making it per-pixel would make the tap count vary per fragment. Scaling `inv_sigma2` changes the weight falloff within the same taps, which is what "slightly softer with depth" actually needs — and it means the grade can only *soften* within the existing radius, never sharpen beyond it. Say so in the proof document's limitations.

---

### Task 1: the `atmosphere` option, end to end, defaulting off

**Files:**
- Modify: `PyAitD/render/render_options.py` (mode tuple, field, payload, validation, cycle)
- Modify: `PyAitD/app/ui.py` (`REALISM_ROWS`, `REALISM_CYCLES`, `realism_labels`)
- Modify: `PyAitD/app/shell.py` (the CLI flag, `_MENU_RENDER_FIELDS`)
- Test: `tests/test_render_options.py`, `tests/test_ui_reducers.py`, `tests/test_ui_render.py`, `tests/test_main.py`

**Interfaces:**
- Consumes: nothing. Pure plumbing, reviewable on its own.
- Produces:
  - `render_options.ATMOSPHERE_MODES = ("off", "on")`
  - `RenderOptions.atmosphere: str = "off"` — **appended last**
  - `render_options.cycle_atmosphere(options) -> RenderOptions`
  - `--atmosphere {off,on}` on the CLI
  - `REALISM_CYCLES[6] is cycle_atmosphere`, `REALISM_ROWS == 7` (assuming K landed; one lower if not)

- [ ] **Step 1: Write the failing tests**

In `tests/test_render_options.py` (marker `render`):

```python
def test_atmosphere_defaults_off_and_cycles():
    from PyAitD.render.render_options import ATMOSPHERE_MODES, cycle_atmosphere
    options = RenderOptions()
    assert options.atmosphere == "off"
    assert ATMOSPHERE_MODES == ("off", "on")
    assert cycle_atmosphere(options).atmosphere == "on"
    assert cycle_atmosphere(cycle_atmosphere(options)).atmosphere == "off"


def test_atmosphere_is_last_so_positional_construction_still_works():
    options = RenderOptions(4, "smooth", "bilinear", None, "scene", 4, "enhanced", 2)
    assert options.atmosphere == "off"


def test_an_unknown_atmosphere_value_falls_back_alone():
    payload = RenderOptions().to_payload()
    payload["atmosphere"] = "foggy"
    options, errors = validate_render_options(payload)
    assert options.atmosphere == "off"
    assert options.integration == RenderOptions().integration    # neighbour undisturbed
    assert any("atmosphere" in e for e in errors)


def test_a_missing_atmosphere_key_falls_back_with_a_notice():
    """An older settings file has no such key. It must fall back *and say
    so* -- the convention every sibling field follows, and what the spec
    means by "older-file-falls-back-with-notice"."""
    payload = RenderOptions().to_payload()
    del payload["atmosphere"]
    options, errors = validate_render_options(payload)
    assert options.atmosphere == "off"
    assert any("atmosphere" in e for e in errors)


def test_atmosphere_round_trips_through_the_payload():
    options = replace(RenderOptions(), atmosphere="on")
    assert options.to_payload()["atmosphere"] == "on"
    restored, errors = validate_render_options(options.to_payload())
    assert restored.atmosphere == "on" and not errors
```

In `tests/test_ui_reducers.py` (marker `shell`):

```python
def test_the_realism_page_gained_the_atmosphere_row():
    from PyAitD.app.ui import REALISM_CYCLES, REALISM_ROWS
    from PyAitD.render.render_options import cycle_atmosphere
    assert REALISM_ROWS == 7
    assert len(REALISM_CYCLES) == REALISM_ROWS
    assert REALISM_CYCLES[6] is cycle_atmosphere
```

In `tests/test_main.py` (marker `shell`):

```python
def test_the_atmosphere_flag_overrides_only_its_own_field(tmp_path):
    settings = Settings()
    args = parse_args(["--atmosphere", "on"])
    updated, _ = apply_render_overrides(settings, args)
    assert updated.render.atmosphere == "on"
    assert updated.render.integration == settings.render.integration
    assert updated.render.motion == settings.render.motion
```

Match each file's existing imports and fixture names rather than these snippets' — the tests beside yours show the house style. `tests/test_main.py`'s override tests are at `:315-360`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_render_options.py tests/test_ui_reducers.py tests/test_main.py -q`
Expected: FAIL — `ImportError` on `ATMOSPHERE_MODES`, `AttributeError` on `RenderOptions.atmosphere`.

- [ ] **Step 3: Add the option**

In `PyAitD/render/render_options.py`, beside the other mode tuples:

```python
# Depth-driven haze and depth-graded softness and grain on the actor
# layer. "off" runs today's composite verbatim. Applies only under
# integration > 0 and lighting="scene": every term lives in the composite
# pass, and at integration 0 there is no composite to modify.
ATMOSPHERE_MODES = ("off", "on")
```

Append the field after the last existing one:

```python
    atmosphere: str = "off"
```

Add it to `to_payload()` (last key), to `validate_render_options` beside its neighbours:

```python
    # Bare .get(), like every sibling field: a MISSING key must produce a
    # notice before falling back, not fall back silently. The spec calls
    # for "the usual older-file-falls-back-with-notice convention", and
    # every settings file written before this task lacks the key, so the
    # missing case is the common one. The message format matches the
    # siblings too -- `', '.join(MODES)`, not a raw tuple repr.
    atmosphere = payload.get("atmosphere")
    if atmosphere not in ATMOSPHERE_MODES:
        errors.append(f"atmosphere must be one of {', '.join(ATMOSPHERE_MODES)}")
        atmosphere = defaults.atmosphere
```

and as the last positional argument of the final `RenderOptions(...)` construction. Add the cycle:

```python
def cycle_atmosphere(options):
    return replace(options, atmosphere=_cycle(ATMOSPHERE_MODES, options.atmosphere))
```

In `PyAitD/app/ui.py`: bump `REALISM_ROWS`, append `cycle_atmosphere` to `REALISM_CYCLES`, import it, and add the label in the matching slot of `realism_labels`:

```python
        f"Atmosphere: {'On' if render.atmosphere == 'on' else 'Off'}",
```

In `PyAitD/app/shell.py`: add the flag beside the others, extend `apply_render_overrides` with its `if args.atmosphere is not None:` line, and add `"atmosphere"` to `_MENU_RENDER_FIELDS` — without it the menu's change never persists.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_render_options.py tests/test_ui_reducers.py tests/test_ui_render.py tests/test_main.py tests/test_config.py -q`
Expected: PASS. The two Realism-page tests in `tests/test_ui_render.py` compute their bounds dynamically and should pass unedited; if the label/cycle alignment test fails, fix the alignment rather than the test.

- [ ] **Step 5: Full gate, then commit**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
git add PyAitD/render/render_options.py PyAitD/app/ui.py PyAitD/app/shell.py \
        tests/test_render_options.py tests/test_ui_reducers.py tests/test_main.py
git commit -m "feat: the atmosphere option and its Realism row, defaulting off"
```

---

### Task 2: the linear-depth MRT through both resolve paths

**Files:**
- Modify: `PyAitD/render/glsl.py` (`ACTOR_FSH` gains a second output)
- Modify: `PyAitD/render/render_gl.py` (the depth attachment, the MSAA twin, both resolves, `release()`)
- Test: `tests/test_render_gl.py`

**Interfaces:**
- Consumes: `RenderOptions.atmosphere` (Task 1).
- Produces:
  - `GLBackend._actor_depth_tex` — full-resolution R16F (or RGBA16F, see below), carrying **coverage-premultiplied positive linear view depth**
  - `GLBackend._ms_depth_color` — the MSAA renderbuffer twin, allocated only when `self.samples`
  - `_actor_fbo` and `_ms_fbo` each carry two colour attachments
  - `ACTOR_FSH` writes `layout(location = 1) out vec4 f_depth`

**Nothing visible changes in this task.** The composite does not read the new target yet. That is deliberate: the MRT plumbing is where the MSAA resolve can go wrong, and it is worth its own reviewer's gate before any arithmetic depends on it.

**Why premultiplied.** The actor layer is premultiplied throughout — the shader writes alpha 1 and the multisample resolve scales by coverage. Depth has to travel the same way or a partially covered edge pixel's depth would be the full-strength depth of whichever samples happened to be covered, while its colour was scaled. The composite unpremultiplies both with the same `a.a`. Write `depth * 1.0` and let the resolve do the scaling, exactly as colour does.

- [ ] **Step 1: Write the failing tests**

In `tests/test_render_gl.py`:

```python
def test_the_actor_layer_carries_linear_depth(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene",
                                              msaa=0, integration=2, atmosphere="on"))
    try:
        backend.draw(_golden_frame())
        depth = _read_actor_depth(backend)
        colour = np.frombuffer(backend._actor_tex.read(), np.uint8).reshape(
            backend.size[1], backend.size[0], 4)
        covered = colour[..., 3] > 0
        assert covered.any() and not covered.all()
        assert (depth[covered] > 0.0).all(), "a covered pixel must carry a depth"
        assert (depth[~covered] == 0.0).all(), "an uncovered pixel must carry none"
    finally:
        backend.release()


@pytest.mark.parametrize("msaa", [0, 4])
def test_both_resolve_paths_carry_depth(gl_ctx, msaa):
    """The MSAA path resolves two attachments where it used to resolve one;
    a resolve that silently drops attachment 1 is the failure this catches."""
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene",
                                              msaa=msaa, integration=2, atmosphere="on"))
    try:
        backend.draw(_golden_frame())
        depth = _read_actor_depth(backend)
        assert (depth > 0.0).any(), f"no depth survived the resolve at msaa={msaa}"
    finally:
        backend.release()


def test_depth_grows_with_distance(gl_ctx):
    """Two actors at known distances: the far one's depth must exceed the
    near one's. This is what makes the value a depth rather than a number."""
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene",
                                              msaa=0, integration=2, atmosphere="on"))
    try:
        backend.draw(_near_and_far_frame())
        depth = _read_actor_depth(backend)
        near = depth[_near_actor_pixels()]
        far = depth[_far_actor_pixels()]
        assert far[far > 0].mean() > near[near > 0].mean()
    finally:
        backend.release()


def test_the_depth_target_changes_no_pixel_of_the_frame(gl_ctx):
    """The whole point of landing the MRT before the arithmetic: writing a
    second attachment must not disturb the first."""
    frame = _golden_frame()
    assert np.array_equal(_render_with(gl_ctx, frame, atmosphere="on"),
                          _render_with(gl_ctx, frame, atmosphere="off"))
```

`_read_actor_depth(backend)` and `_near_and_far_frame()` are helpers you write beside the existing fixtures in that file. `_read_actor_depth` must unpremultiply — read both `_actor_tex`'s alpha and `_actor_depth_tex`, and divide where alpha is non-zero — so the test asserts on the depth the composite will actually see.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_render_gl.py -q -k "depth and actor"`
Expected: FAIL — `AttributeError: 'GLBackend' object has no attribute '_actor_depth_tex'`.

- [ ] **Step 3: Emit depth from the actor shader**

In `ACTOR_FSH`, change the single output declaration to a pair and write the second at the end:

```glsl
layout(location = 0) out vec4 f_color;
// Positive linear view depth, premultiplied by coverage exactly as colour
// is: the shader writes alpha 1 and the multisample resolve scales both,
// so the composite unpremultiplies both with the same a.a. A depth that
// travelled unpremultiplied would make a half-covered edge pixel report
// the full depth of whichever samples happened to be covered.
//
// Writing this output when the bound framebuffer has only one attachment
// is well defined -- the value is discarded and attachment 0 is
// unaffected -- so lines, points and every single-attachment target keep
// working unchanged. (Verified on this GPU; see the plan's fact table.)
layout(location = 1) out vec4 f_depth;
```

and, beside the existing `f_color = ...` at `glsl.py:299`:

```glsl
    f_depth = vec4(-v_view.z, 0.0, 0.0, 1.0);
```

Confirm `v_view` is camera-space *position* before relying on `-v_view.z`: `grep -n "v_view" PyAitD/render/glsl.py`. If it is a direction rather than a position, build the position from the view matrix instead and record what you found in your report. (Sub-project K's G-buffer pass makes the same assumption; if K has landed, whatever it did is the answer.)

- [ ] **Step 4: Attach the second target through both paths**

In `GLBackend.__init__`, beside `_actor_tex` (`render_gl.py:476-481`):

```python
        # R16F is enough for a linear depth in world units -- half-float
        # holds integers exactly to 2048 and the game's rooms are far
        # smaller than that -- and it keeps the resolve cheap.
        self._actor_depth_tex = ctx.texture(self.size, 1, dtype="f2")
        self._actor_depth_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self._actor_depth_tex.repeat_x = self._actor_depth_tex.repeat_y = False
        self._actor_fbo = ctx.framebuffer(
            color_attachments=[self._actor_tex, self._actor_depth_tex],
            depth_attachment=self._depth)
```

and, in the MSAA branch (`render_gl.py:456-461`), a matching second renderbuffer so the resolve has something to resolve into:

```python
            self._ms_depth_color = ctx.renderbuffer(self.size, 1, samples=self.samples, dtype="f2")
            self._ms_fbo = ctx.framebuffer(
                color_attachments=[self._ms_color, self._ms_depth_color],
                depth_attachment=self._ms_depth)
```

Verify the half-float renderbuffer is multisample-capable on this GPU before building on it — if `ctx.renderbuffer(..., samples=..., dtype="f2")` raises, fall back to a 4-component `f2` renderbuffer and say so in your report; the probe in the fact table used RGBA32F and RGBA8, not R16F, so this specific combination is the one thing here that is assumed rather than measured.

`ctx.copy_framebuffer(dst, src)` resolves both attachments when both framebuffers carry two, so `_resolve_into` (`render_gl.py:1178-1183`) needs no change — but add a comment there saying the resolve now moves two attachments, because the next reader will assume one. If the two-attachment resolve does not work as measured, the fallback is per-attachment single-attachment views, also verified working; take that route and record the deviation.

**The `_ms_fbo` is also the target for the plate pass** (`render_gl.py:618-619,693-703`), which has one attachment on the destination side. Check that `_resolve_into(self._plate_fbo)` at `:694` still works with a two-attachment source and a one-attachment destination — if `copy_framebuffer` refuses the mismatch, give `_plate_fbo` a matching dummy attachment or resolve through a single-attachment view. This is the single most likely place this task breaks; test it at `msaa=4` before moving on.

- [ ] **Step 5: Release and count**

Add `_actor_depth_tex` and `_ms_depth_color` to `release()`'s tuple and to the leak test's attribute tuple, bumping `leak_checked` by exactly what you added. Note that `_ms_depth_color` is `None` when MSAA is off — the leak test constructs its backend with whatever options it uses, so check how it handles the existing `_ms_color` and follow that exactly.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_render_gl.py -q`
Expected: PASS, including the golden identity — nothing reads the new target yet.

- [ ] **Step 7: Full gate, then commit**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
git add PyAitD/render/glsl.py PyAitD/render/render_gl.py tests/test_render_gl.py
git commit -m "feat: carry linear actor depth through both resolve paths"
```

---

### Task 3: haze, the depth grades, and the tunables

**Files:**
- Modify: `PyAitD/render/glsl.py` (`COMPOSITE_FSH`)
- Modify: `PyAitD/render/render_gl.py` (`_composite`'s uniforms)
- Modify: `PyAitD/render/plate.py` (the four tunables)
- Test: `tests/test_render_gl.py`

**Interfaces:**
- Consumes: `_actor_depth_tex` (Task 2), `SceneLight.ambient`, `RenderOptions.atmosphere`.
- Produces:
  - `plate.HAZE_DENSITY`, `plate.HAZE_START`, `plate.SIGMA_DEPTH_SLOPE`, `plate.GRAIN_DEPTH_SLOPE`
  - `COMPOSITE_FSH` uniforms `depth_tex`, `haze_density`, `haze_start`, `haze_tint`, `sigma_depth_slope`, `grain_depth_slope`

**The tunables live in `plate.py`** beside `NEUTRAL_PLATE` and the composite's other constants, not in `render_gl.py`: they are properties of the look, they are settled by eye against the fixtures, and the proof document records them the way G's `TOE`/`SHOULDER`/`GAIN` are recorded.

- [ ] **Step 1: Write the failing tests**

In `tests/test_render_gl.py`:

```python
def test_neutral_tunables_are_an_exact_identity(gl_ctx, monkeypatch):
    """The strongest guarantee in this plan: atmosphere on, every tunable
    zero, and the frame is byte-identical to atmosphere off. Every term is
    built so k=0 collapses it exactly, not nearly."""
    import PyAitD.render.glsl as glsl_module
    frame = _golden_frame()
    off = _render_with(gl_ctx, frame, atmosphere="off", integration=2)
    on = _render_with_tunables(gl_ctx, frame, atmosphere="on", integration=2,
                               haze_density=0.0, sigma_slope=0.0, grain_slope=0.0)
    assert np.array_equal(off, on)


def test_a_far_actor_moves_toward_the_ambient_tone_and_a_near_one_does_not(gl_ctx):
    frame = _near_and_far_frame()
    off = _render_with(gl_ctx, frame, atmosphere="off", integration=2).astype(np.int32)
    on = _render_with(gl_ctx, frame, atmosphere="on", integration=2).astype(np.int32)
    near_delta = np.abs(on[_near_actor_pixels()] - off[_near_actor_pixels()]).mean()
    far_delta = np.abs(on[_far_actor_pixels()] - off[_far_actor_pixels()]).mean()
    assert far_delta > near_delta + 1.0
    # And it moves *toward* the ambient tone, not just anywhere.
    ambient = np.array(frame.light.ambient) * 255.0
    before = np.abs(off[_far_actor_pixels()] - ambient).mean()
    after = np.abs(on[_far_actor_pixels()] - ambient).mean()
    assert after < before


def test_haze_starts_at_zero_before_haze_start(gl_ctx):
    """max(0, depth - HAZE_START) means a small room is untouched by
    construction -- the spec's whole argument for a depth-driven haze
    over the plate-wide one the first roadmap dropped."""
    frame = _all_actors_nearer_than_haze_start()
    assert np.array_equal(_render_with(gl_ctx, frame, atmosphere="on", integration=2),
                          _render_with(gl_ctx, frame, atmosphere="off", integration=2))


def test_zero_coverage_pixels_are_untouched(gl_ctx):
    frame = _golden_frame()
    off = _render_with(gl_ctx, frame, atmosphere="off", integration=2)
    on = _render_with(gl_ctx, frame, atmosphere="on", integration=2)
    bare = _uncovered_pixels(gl_ctx, frame)
    assert np.array_equal(off[bare], on[bare])


def test_softness_and_grain_increase_with_depth(gl_ctx):
    """Measured, not asserted by construction: a far actor's local
    variance falls (softer) and its high-frequency residual rises
    (grainier) relative to a near one, compared against the same frame
    with the two slopes zeroed."""
    frame = _near_and_far_frame()
    flat = _render_with_tunables(gl_ctx, frame, atmosphere="on", integration=2,
                                 sigma_slope=0.0, grain_slope=0.0)
    graded = _render_with(gl_ctx, frame, atmosphere="on", integration=2)
    assert _local_variance(graded, _far_actor_pixels()) < _local_variance(flat, _far_actor_pixels())
    assert _grain_energy(graded, _far_actor_pixels()) > _grain_energy(flat, _far_actor_pixels())
    # The near actor is where the grade is meant to be near-nil.
    assert abs(_local_variance(graded, _near_actor_pixels())
               - _local_variance(flat, _near_actor_pixels())) < _local_variance(flat, _near_actor_pixels()) * 0.1


def test_atmosphere_is_inert_at_integration_zero(gl_ctx):
    frame = _near_and_far_frame()
    assert np.array_equal(_render_with(gl_ctx, frame, atmosphere="on", integration=0),
                          _render_with(gl_ctx, frame, atmosphere="off", integration=0))
```

`_render_with_tunables`, `_local_variance`, `_grain_energy`, `_near_and_far_frame`, `_all_actors_nearer_than_haze_start` and `_uncovered_pixels` are helpers you write. `_render_with_tunables` should set the uniforms through the backend rather than monkeypatching module constants where that is possible — a test that patches a constant proves the constant is read, not that the shader uses it correctly.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_render_gl.py -q -k "haze or atmosphere or tunable"`
Expected: FAIL — the helpers do not exist, and once they do, the renders are identical because nothing reads depth yet.

- [ ] **Step 3: Add the tunables**

In `PyAitD/render/plate.py`, beside `NEUTRAL_PLATE`:

```python
# Atmosphere's four constants, settled by eye against the fixtures and
# recorded in docs/atmosphere-proof.md -- the same standing the
# composite's own TOE/SHOULDER/GAIN have. All four are zero-collapsible:
# with any of them at 0 its term vanishes exactly, which is what makes
# atmosphere="on" an identity before it is a look.
#
# Distances are in the game's world units. AITD1's actors are about 200
# units tall, and a large room is a few thousand across.
HAZE_DENSITY = 0.00035      # per unit beyond HAZE_START
HAZE_START = 900.0          # below this, no haze at all -- a small room is untouched
SIGMA_DEPTH_SLOPE = 0.25    # extra blur sigma per HAZE_START-worth of extra depth
GRAIN_DEPTH_SLOPE = 0.35    # extra grain gain, likewise
```

These are starting values, not measurements. Task 4's proof document is where they are defended or changed; if the fixtures say otherwise, change them there and say what you saw.

- [ ] **Step 4: Read depth in the composite**

In `COMPOSITE_FSH`, add the uniforms beside the existing ones:

```glsl
uniform sampler2D depth_tex;    // coverage-premultiplied linear view depth
uniform float haze_density;     // 0 disables the term exactly
uniform float haze_start;
uniform vec3 haze_tint;         // the room's ambient tone: what an unlit surface looks like
uniform float sigma_depth_slope;
uniform float grain_depth_slope;
```

Replace `sample_actor` with a version that gathers colour and depth **under identical weights** — this is the part that must not be split into two functions:

```glsl
// Colour and depth gathered in one pass with the same weights. Two
// separate loops would drift the moment either changed, and a soft edge
// whose depth came from different taps than its colour hazes by the
// wrong amount along exactly the pixels the eye checks first.
//
// `grade` scales the weight falloff, never the tap count: `radius` is a
// uniform and the loop below depends on that for uniform control flow.
// So the grade can soften within the existing radius and never sharpen
// past it -- a real bound, recorded in the proof document.
void sample_layers(ivec2 p, ivec2 size, float grade, out vec4 rgba, out float depth) {
    if (pixelate != 0) {
        vec2 c = (floor(vec2(p) / cell) + 0.5) * cell;
        ivec2 q = clamp(ivec2(c), ivec2(0), size - 1);
        rgba = texelFetch(actor_tex, q, 0);
        depth = texelFetch(depth_tex, q, 0).r;
        return;
    }
    if (radius <= 0) {
        rgba = texelFetch(actor_tex, p, 0);
        depth = texelFetch(depth_tex, p, 0).r;
        return;
    }
    vec4 sum = vec4(0.0);
    float dsum = 0.0;
    float total = 0.0;
    float inv = inv_sigma2 / max(grade, 1e-6);
    for (int dy = -radius; dy <= radius; dy++) {
        for (int dx = -radius; dx <= radius; dx++) {
            ivec2 q = clamp(p + ivec2(dx, dy), ivec2(0), size - 1);
            float w = exp(-float(dx * dx + dy * dy) * inv);
            sum += texelFetch(actor_tex, q, 0) * w;
            dsum += texelFetch(depth_tex, q, 0).r * w;
            total += w;
        }
    }
    rgba = sum / total;
    depth = dsum / total;
}
```

and rewrite `main` to grade from the centre pixel's own depth:

```glsl
void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    ivec2 size = textureSize(actor_tex, 0);
    // The grade is read from this pixel's own unblurred depth. Grading
    // from the blurred value would be circular: the blur's weights are
    // what the grade sets.
    vec4 centre = texelFetch(actor_tex, p, 0);
    float centre_depth = centre.a > 0.0 ? texelFetch(depth_tex, p, 0).r / centre.a : 0.0;
    float beyond = max(0.0, centre_depth - haze_start) / max(haze_start, 1e-6);
    float grade = 1.0 + sigma_depth_slope * beyond;

    vec4 a;
    float d;
    sample_layers(p, size, grade, a, d);
    vec3 plate = texelFetch(plate_tex, p, 0).rgb;
    vec3 c = vec3(0.0);
    if (a.a > 0.0) {
        c = a.rgb / a.a;
        float depth = d / a.a;                     // unpremultiply with the same coverage
        c = mix(c, min(max(c, plate_black), plate_white), strength);
        // Distance haze. exp(-0) is exactly 1, so haze is exactly 0 both
        // below haze_start and at haze_density 0 -- the identity, by
        // construction rather than by rounding.
        float haze = 1.0 - exp(-haze_density * max(0.0, depth - haze_start));
        c = mix(c, haze_tint, haze * strength);
        c += plate_grain * strength * (1.0 + grain_depth_slope * beyond)
             * dither(gl_FragCoord.xy) * GAIN;
        c = clamp(c, 0.0, 1.0);
    }
    f_color = vec4(plate * (1.0 - a.a) + c * a.a, 1.0);
}
```

Note the haze is scaled by `strength` alongside the toe, shoulder and grain — atmosphere is part of the integration story and grades with it, which is also why the knob is inert at `integration = 0` for free rather than by a second branch.

- [ ] **Step 5: Set the uniforms**

In `_composite` (`render_gl.py:1185-1240`), beside the existing uniform block, and binding the depth target at the next free unit (7 before K, 9 after — read what is actually taken and pick the next):

```python
        on = self._options.atmosphere == "on" and self._options.lighting == "scene"
        self._actor_depth_tex.use(location=9)
        self._composite_prog["depth_tex"].value = 9
        self._composite_prog["haze_density"].value = HAZE_DENSITY if on else 0.0
        self._composite_prog["haze_start"].value = HAZE_START
        self._composite_prog["haze_tint"].value = tuple(float(v) for v in frame.light.ambient)
        self._composite_prog["sigma_depth_slope"].value = SIGMA_DEPTH_SLOPE if on else 0.0
        self._composite_prog["grain_depth_slope"].value = GRAIN_DEPTH_SLOPE if on else 0.0
```

Bind the sampler unconditionally and gate with the *values*, not the binding — the same rule the shadow map follows at `render_gl.py:673`. With the three slopes at zero the shader runs its full arithmetic and lands on exactly the old result, which is what `test_neutral_tunables_are_an_exact_identity` proves.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_render_gl.py -q`
Expected: PASS, including the golden.

If `test_neutral_tunables_are_an_exact_identity` fails by one count on a handful of pixels, the cause is almost certainly `grade` at exactly 1.0 changing `inv_sigma2 / max(grade, 1e-6)` — division by exactly 1.0 is exact in IEEE 754, so if this drifts, the grade is not exactly 1.0 and `beyond` is not exactly 0. Trace `centre_depth` before touching the tolerance; the test asserts byte equality on purpose.

- [ ] **Step 7: Full gate, then commit**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
git add PyAitD/render/glsl.py PyAitD/render/render_gl.py PyAitD/render/plate.py \
        tests/test_render_gl.py
git commit -m "feat: distance haze and the depth-graded softness and grain"
```

---

### Task 4: the default flip, the proof twins, and the documents

**Files:**
- Modify: `PyAitD/render/render_options.py` (the default flip)
- Modify: `tools/prove_graphics.py`, `tests/test_prove_graphics.py`
- Create: `docs/atmosphere-proof.md`
- Modify: `CONTEXT.md`, `AGENTS.md`, `README.md`, `Makefile`
- Test: `tests/test_render_gl.py`, `tests/test_render_options.py`

- [ ] **Step 1: Flip the default and extend the identity net**

```python
    atmosphere: str = "on"
```

Rename and update `test_atmosphere_defaults_off_and_cycles` to expect `"on"`. Add `atmosphere="off"` to the identity net at `tests/test_render_gl.py:972-980` (`test_classic_realism_matches_the_pre_materials_golden`), which already carries the comment "names every roadmap-2 field the identity holds at" — after this task it names every field the roadmap added.

- [ ] **Step 2: Add the twin to the proof tool**

Append `atmosphere=None` to `render_fixture`'s signature and extend the parameter-list pin at `tests/test_prove_graphics.py:132-138` to match. Add one twin row in `output_paths` beside the others:

```python
        rows.append((*base, "nohaze", _path(out_dir, name, mode, realism, "nohaze")))
```

forcing `atmosphere="off"` against a default of `on`, then update `test_output_paths_cover_every_combination_plus_the_twins` — its twin count goes up by one per fixture, and its `expected` set gains a `nohaze` block. That test compares sets with `==`; a duplicate label collapses silently and only the count assertion catches it, so do not weaken the count.

Add `--atmosphere` to `_parse_args` with `default=RenderOptions().atmosphere`, and a difference smoke test:

```python
def test_the_nohaze_twin_differs_from_the_default(tmp_path, gl_ctx, data_dir):
    default = render_fixture(data_dir, "attic", 1, "smooth", gl_ctx)
    nohaze = render_fixture(data_dir, "attic", 1, "smooth", gl_ctx, atmosphere="off")
    assert not np.array_equal(default, nohaze)
```

The attic is a small room, so the haze there may be genuinely near zero — that is the feature working as designed, not a bug. If this test cannot find a difference on either fixture, **do not force one by raising `HAZE_DENSITY`**: report it, and use a fixture with real depth range instead, or assert the difference on the combat venue alone and say why in the proof document.

- [ ] **Step 3: Write the proof document**

Create `docs/atmosphere-proof.md`, following `docs/motion-interpolation-proof.md`, `docs/actor-textures-proof.md` and `docs/light-transport-proof.md` — they are the house style and this one is read beside them.

**Every number and every block of output must come from a command you actually ran, pasted as it came back.** If a gate cannot run here, say so and why. Do not reconstruct output.

Sections:

1. **What changed** — the depth target, haze, and the two grades, each in a paragraph naming the knob that disables it.
2. **Automated gates** — the full gate and the atmosphere tests by name, with real output. Include `test_neutral_tunables_are_an_exact_identity` prominently: it is the claim the rest rests on.
3. **The tunables** — the four constants, their values, and what you saw on the fixtures that settled them. If you kept the plan's starting values unchanged, say that plainly rather than implying they were measured.
4. **Pixel evidence** — the `-nohaze` twin pair on both fixtures with differing-pixel counts, and the near-versus-far measurements from `test_a_far_actor_moves_toward_the_ambient_tone_and_a_near_one_does_not`.
5. **Frame time** — one measured line, mean of at least 16 runs of the attic fixture at scale 4, msaa 4, smoothing 2, atmosphere off versus on, with the ratio. Then the roadmap-level budget: the spec's gate is 1.5x with **all four** sub-projects on versus all four off. This is the last plan of the four, so it is the one that can finally measure that number — measure it, report it, and say whether the roadmap met its own budget.
6. **Manual attestation** — the usual `pending` table: far actors read as further away rather than as washed out; the haze is invisible in a small room; grain and softness change with depth without the near actor looking touched; nothing crawls as an actor walks toward the camera.
7. **Known limitations** — haze and the grades are tuned by eye; the grade softens within the existing radius and can never sharpen past it (Task 3's `inv_sigma2`-not-`radius` decision); no depth of field, by decision 9; the software backend stays uncomposited and unatmospheric.

- [ ] **Step 4: Update the docs**

- `README.md`: the CLI flag count goes up by one again (twelve → thirteen if K landed first), with `--atmosphere` described; the Realism page listing gains its row.
- `AGENTS.md`: a convention block — the premultiplied-depth contract and why depth travels the same way colour does; the grade-from-centre-depth rule; the `inv_sigma2`-not-`radius` rule and the uniform-control-flow reason behind it; that the tunables live in `plate.py` beside the composite's other constants.
- `CONTEXT.md`: the milestone row, and the roadmap-2 line marked complete once all four sub-projects have landed.
- `Makefile`: `proof-graphics`'s help text gains the `-nohaze` twin and the `atmosphere=` variable; the recipe forwards `$(if $(atmosphere),--atmosphere "$(atmosphere)")`, following the `motion=` line at `Makefile:85-86`.

- [ ] **Step 5: Full gate, then commit**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
git add PyAitD/render/render_options.py tools/prove_graphics.py tests/test_prove_graphics.py \
        tests/test_render_gl.py tests/test_render_options.py docs/atmosphere-proof.md \
        CONTEXT.md AGENTS.md README.md Makefile
git commit -m "docs: default atmosphere on, the nohaze twin, and the atmosphere proof"
```

---

## Plan self-review (record kept)

**Spec coverage.** L's six bullets: the depth target as a second render target resolved alongside colour, identical in structure at `msaa = 0`, with every term gated by coverage (Task 2); distance haze by `1 − exp(−HAZE_DENSITY · max(0, depth − HAZE_START))` toward the scene's ambient tone (Task 3); depth-graded sigma and grain scaling mildly upward with depth (Task 3); no depth of field (nowhere — decision 9 is honoured by omission, and the proof document records it); the `atmosphere` knob mirroring `lighting`, applying only under `integration > 0` and `lighting="scene"`, landing off and flipping in the last task (Tasks 1, 3 and 4); tunables settled by eye against the fixtures and recorded in the proof document like G's constants (Task 3 defines them, Task 4 defends them). The spec's L testing bullets each map to a named test: the golden under neutral tunables, near versus far, softness and grain measurably increasing, zero-coverage pixels untouched, both resolve paths carrying depth, leak counts.

**Three things I checked and changed while writing.** First, I had `ACTOR_FSH` writing depth only under a compile-time variant, which would have doubled the program count; probing showed a two-output shader is fine against a one-attachment FBO, so the second output is unconditional and the plumbing stays simple. Second, I had separate `sample_actor` and `sample_depth` functions; identical weights are load-bearing for edge pixels, so they became one function with two outputs. Third, the depth grade originally read the blurred depth, which is circular — the blur's weights are what the grade sets — so it now reads the centre pixel's own unblurred depth.

**Type consistency.** `atmosphere` is the field name everywhere (`RenderOptions.atmosphere`, `--atmosphere`, `cycle_atmosphere`, `ATMOSPHERE_MODES`, the payload key, `_MENU_RENDER_FIELDS`). `_actor_depth_tex` and `_ms_depth_color` are the two new GL attributes throughout. The four tunables are `HAZE_DENSITY`, `HAZE_START`, `SIGMA_DEPTH_SLOPE`, `GRAIN_DEPTH_SLOPE` in `plate.py` and `haze_density`, `haze_start`, `sigma_depth_slope`, `grain_depth_slope` as uniforms — the CPU/GLSL casing split every other constant in this file follows.

## Known limitations this plan ships with

- **The depth grade softens within the existing radius and can never sharpen past it.** `radius` stays uniform because the composite's blur depends on uniform control flow; only the weight falloff is graded.
- **Haze and the grades are tuned by eye** against two fixtures, like the composite's own toe and shoulder. The starting values in this plan are reasoned from the game's scale, not measured.
- **A small room shows no haze at all**, by construction. That is the design — a depth-driven term on actors only, rather than the plate-wide guesswork the first roadmap dropped — but it means the attic fixture may show almost nothing and the proof must say so rather than tuning until it does.
- **R16F depth** holds integers exactly only to 2048. The game's rooms are far smaller, but a future floor with a longer sight line would quantise; the fix is an R32F target, and the proof document should note the ceiling.
- **The software backend** stays flat, unlit, untextured, tick-stepped, uncomposited and unatmospheric.
