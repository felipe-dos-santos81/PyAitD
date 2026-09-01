# Light transport proof

Date: 2026-09-01
Spec: `docs/superpowers/specs/2026-08-31-actor-realism-roadmap-2-design.md` (sub-project K)
Plan: `docs/superpowers/plans/2026-09-01-light-transport.md`

**This document's "The fixture-review gate" and "Manual attestation" tables
are checklists for a human with real game data and a real window; every
row starts `pending`.** Everything under "Automated gates", "The twin",
"Attenuation", "Pixel evidence" and "Frame time" was actually run, in this
environment, on this branch, and the output shown is the real output of
that run.

## What changed

Actors under `lighting="scene"` now get screen-space ambient occlusion
that sees pose and neighbours every frame, not just their own rest pose.
A half-resolution G-buffer prepass writes view normals plus linear view
depth for every actor; the SSAO pass samples a 16-tap hemisphere kernel
against it, a bilateral blur removes the per-pixel noise, and the result
attenuates the fill light's share in `ACTOR_FSH` -- the key share and
specular are untouched, so a shadowed limb still falls to the room's fill
colour, never to black. `occlusion="off"` (the CLI/menu escape hatch;
`RenderOptions.occlusion` defaults to `"ssao"`) skips the prepass and the
two passes entirely and runs today's renderer verbatim.

`shadows` gains a third value, `"room"`, alongside the existing `"hard"`
and `"soft"` (the default, unmoved by this task). `"room"` does
everything `"soft"` does -- one gathered ground cast, the light-view
shadow map, self/inter-actor shadowing -- and adds a receiver pass that
rasterises the current room's floor plane and the top faces of its
`hard_col` collision boxes, sampling that same shadow map to darken them
after the gathered shadow composites and before any body draws. Passing
`shadows="soft"` (or leaving it at the default) skips the receiver pass
entirely and reproduces `"soft"`'s output.

`tools/prove_graphics.py` gained `--occlusion` and a `-nossao` /
`-roomshadow` twin pair (Task 6), following the shape of the existing
twins.

## Automated gates

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_ssao.py -q
.........                                                                [100%]
9 passed in 0.05s
```

The named SSAO-twin and receiver tests:

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest \
    tests/test_render_gl.py::test_the_ssao_pass_matches_the_numpy_twin \
    tests/test_render_gl.py::test_ssao_attenuates_the_fill_share_and_leaves_key_and_specular_alone \
    tests/test_render_gl.py::test_a_caster_over_a_box_top_darkens_it_through_the_shadow_map \
    tests/test_render_gl.py::test_the_room_receiver_pass_leaves_soft_output_untouched \
    tests/test_render_gl.py::test_a_mask_erases_the_receiver_pass \
    tests/test_render_gl.py::test_room_with_no_hard_col_in_view_matches_soft \
    -v
============================= test session starts ==============================
collected 6 items

tests/test_render_gl.py::test_the_ssao_pass_matches_the_numpy_twin PASSED [ 16%]
tests/test_render_gl.py::test_ssao_attenuates_the_fill_share_and_leaves_key_and_specular_alone PASSED [ 33%]
tests/test_render_gl.py::test_a_caster_over_a_box_top_darkens_it_through_the_shadow_map PASSED [ 50%]
tests/test_render_gl.py::test_the_room_receiver_pass_leaves_soft_output_untouched PASSED [ 66%]
tests/test_render_gl.py::test_a_mask_erases_the_receiver_pass PASSED     [ 83%]
tests/test_render_gl.py::test_room_with_no_hard_col_in_view_matches_soft PASSED [100%]

============================== 6 passed in 0.58s ===============================
```

The full gate:

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
........................................................................ [ 40%]
........................................................................ [ 44%]
........................................................................ [ 48%]
........................................................................ [ 53%]
........................................................................ [ 57%]
........................................................................ [ 62%]
........................................................................ [ 66%]
........................................................................ [ 71%]
........................................................................ [ 75%]
........................................................................ [ 80%]
........................................................................ [ 84%]
........................................................................ [ 89%]
........................................................................ [ 93%]
........................................................................ [ 97%]
.................................                                        [100%]
1615 passed, 1 skipped, 1 xfailed, 26 warnings in 64.39s
```

This is 2 above the branch's last recorded green (1613): Task 6 adds
`test_the_nossao_twin_differs_from_the_default` and
`test_the_roomshadow_twin_differs_from_the_default` to
`tests/test_prove_graphics.py`. No skip, xfail or warning count moved.

## The twin

`tests/test_render_gl.py::test_the_ssao_pass_matches_the_numpy_twin`
seeds the backend's own G-buffer with a fixed-seed random depth/normal
field, runs `_render_ssao_with`, and compares the read-back texture
against `render/ssao.py`'s `ssao_reference` over the same inputs.
Reproducing the test's own measurement directly:

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -c "
import moderngl, numpy as np
from PyAitD.render.render_gl import GLBackend
from PyAitD.render.render_options import RenderOptions
from PyAitD.render.ssao import (SSAO_BIAS, SSAO_KERNEL_SIZE, SSAO_RADIUS,
                                hemisphere_kernel, noise_rotations, ssao_reference)
ctx = moderngl.create_standalone_context(require=330)
backend = GLBackend(ctx, RenderOptions(scale=1, shading='flat', lighting='scene', msaa=0, occlusion='ssao'))
try:
    w, h = backend._gbuf_size
    rng = np.random.default_rng(23)
    depth = rng.uniform(300.0, 700.0, (h, w)).astype(np.float32)
    depth[: h // 4, :] = 0.0
    n = rng.normal(size=(h, w, 3)).astype(np.float32)
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    gbuf = np.concatenate([n, depth[..., None]], axis=2).astype(np.float16)
    backend._gbuf_tex.write(np.ascontiguousarray(gbuf).tobytes())
    proj_xy = (2.0, 2.0)
    backend._render_ssao_with(proj_xy)
    out = np.frombuffer(backend._ssao_tex.read(), np.uint8).reshape(h, w) / 255.0
    rot = noise_rotations().astype(np.float16).astype(np.float32)
    expected = ssao_reference(gbuf[..., 3].astype(np.float32),
                              gbuf[..., :3].astype(np.float32),
                              hemisphere_kernel(), rot, proj_xy,
                              SSAO_RADIUS, SSAO_BIAS)
    diff = np.abs(out - expected)
    p995 = np.percentile(diff, 99.5)
    dmax = diff.max()
    tol_p995 = 4.0/255
    tol_max = 1.0/SSAO_KERNEL_SIZE + 2.0/255
    print(f'99.5th percentile diff: {p995:.4f} (tolerance <= {tol_p995:.4f})')
    print(f'max diff: {dmax:.4f} (tolerance <= {tol_max:.4f})')
finally:
    backend.release()
    ctx.release()
"
99.5th percentile diff: 0.0019 (tolerance <= 0.0157)
max diff: 0.0637 (tolerance <= 0.0703)
```

The bulk of the frame agrees far inside its 4/255 (0.0157) tolerance (measured
99.5th percentile 0.0019); the single worst pixel sits at 0.0637 against a
0.0703 ceiling -- inside the one-kernel-sample-plus-encode-noise bound the
test's own comment derives (`1/16 + 2/255 = 0.0703`), consistent with a
binary hit test whose per-pixel disagreement is bounded by one kernel
sample's weight, not with a systematically wrong basis or sample count.

## Attenuation

`tests/test_render_gl.py::test_ssao_attenuates_the_fill_share_and_leaves_key_and_specular_alone`
renders a two-sphere frame twice: once with the key light switched off
entirely (pure fill) and once with the fill switched off entirely (pure
key + specular), each under `occlusion="off"` and `occlusion="ssao"`.
Reproducing its own summed-absolute-difference measurement directly:

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -c "
import moderngl, numpy as np, sys
sys.path.insert(0, '.')
from tests.test_render_gl import _frame_with_light, _render_with
ctx = moderngl.create_standalone_context(require=330)
try:
    fill_only = _frame_with_light(key=(0.0, 0.0, 0.0), fill=(0.5, 0.5, 0.5))
    key_only = _frame_with_light(key=(0.8, 0.8, 0.8), fill=(0.0, 0.0, 0.0))
    for label, frame in (('fill_only', fill_only), ('key_only', key_only)):
        off = _render_with(ctx, frame, occlusion='off')
        on = _render_with(ctx, frame, occlusion='ssao')
        total = int(np.abs(off.astype(np.int32) - on.astype(np.int32)).sum())
        print(label, 'summed abs diff:', total)
finally:
    ctx.release()
"
fill_only summed abs diff: 130076
key_only summed abs diff: 0
```

With the frame pure fill, SSAO moves 130,076 summed absolute RGB units;
with the frame pure key and specular, SSAO moves exactly zero. This is
Decision 7 (the spec's fill-share-only attenuation) made testable: the
fill share is the one term an occlusion pass may touch, and this
measurement shows it moving that term and nothing else.

## Pixel evidence

`make proof-graphics` (default scale 4) wrote all 28 PNGs, including the
new `-nossao` and `-roomshadow` pairs:

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy make proof-graphics
.venv/bin/python tools/prove_graphics.py "data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK"
pygame-ce 2.5.8 (SDL 2.32.10, Python 3.12.12)
docs/graphics-proof/attic-flat-classic.png
docs/graphics-proof/attic-flat-enhanced.png
docs/graphics-proof/attic-lambert-classic.png
docs/graphics-proof/attic-lambert-enhanced.png
docs/graphics-proof/attic-smooth-classic.png
docs/graphics-proof/attic-smooth-enhanced.png
docs/graphics-proof/combat-flat-classic.png
docs/graphics-proof/combat-flat-enhanced.png
docs/graphics-proof/combat-lambert-classic.png
docs/graphics-proof/combat-lambert-enhanced.png
docs/graphics-proof/combat-smooth-classic.png
docs/graphics-proof/combat-smooth-enhanced.png
docs/graphics-proof/attic-smooth-enhanced-flatmesh.png
docs/graphics-proof/combat-smooth-enhanced-flatmesh.png
docs/graphics-proof/attic-smooth-enhanced-hardshadow.png
docs/graphics-proof/combat-smooth-enhanced-hardshadow.png
docs/graphics-proof/attic-smooth-enhanced-nocomposite.png
docs/graphics-proof/combat-smooth-enhanced-nocomposite.png
docs/graphics-proof/attic-smooth-enhanced-strong.png
docs/graphics-proof/combat-smooth-enhanced-strong.png
docs/graphics-proof/attic-smooth-enhanced-tickmotion.png
docs/graphics-proof/combat-smooth-enhanced-tickmotion.png
docs/graphics-proof/attic-smooth-enhanced-painted.png
docs/graphics-proof/combat-smooth-enhanced-painted.png
docs/graphics-proof/attic-smooth-enhanced-nossao.png
docs/graphics-proof/combat-smooth-enhanced-nossao.png
docs/graphics-proof/attic-smooth-enhanced-roomshadow.png
docs/graphics-proof/combat-smooth-enhanced-roomshadow.png
```

Diffing each twin against the plain `-smooth-enhanced` render on both
fixtures:

```
$ .venv/bin/python -c "
import pygame, numpy as np
for suffix in ('nossao', 'roomshadow'):
    for fixture in ('attic', 'combat'):
        a = pygame.surfarray.array3d(pygame.image.load(f'docs/graphics-proof/{fixture}-smooth-enhanced.png'))
        b = pygame.surfarray.array3d(pygame.image.load(f'docs/graphics-proof/{fixture}-smooth-enhanced-{suffix}.png'))
        diff = np.abs(a.astype(int) - b.astype(int))
        npix = (diff.max(axis=2) > 0).sum()
        print(suffix, fixture, 'equal?', np.array_equal(a, b), 'pixels differing:', npix, '/', a.shape[0]*a.shape[1], 'mean abs diff', diff.mean())
"
nossao attic equal? False pixels differing: 66571 / 1024000 mean abs diff 0.2787154947916667
nossao combat equal? False pixels differing: 3952 / 1024000 mean abs diff 0.01609375
roomshadow attic equal? True pixels differing: 0 / 1024000 mean abs diff 0.0
roomshadow combat equal? False pixels differing: 18397 / 1024000 mean abs diff 0.16794986979166668
```

The `-nossao` pair differs on both fixtures, as expected -- SSAO reads
against every actor's own G-buffer coverage, and both fixtures have
actors in view.

**The `-roomshadow` pair is byte-identical to the default on the attic
fixture (0 pixels differing) and differs on the combat fixture (18,397
pixels).** This is not a bug in the twin: the attic debug start's room
has no `hard_col` whose top face the gathered shadow actually reaches
under this camera and light, so the receiver pass darkens nothing there
-- exactly the neutral identity
`test_room_with_no_hard_col_in_view_matches_soft` pins. The combat venue
does have furniture-proxy boxes in view that catch a shadow, so it is the
fixture that actually demonstrates the feature; both
`tests/test_prove_graphics.py::test_the_roomshadow_twin_differs_from_the_default`
and this section use the combat fixture for that reason, not the attic
fixture the `-nossao` example in the task brief used.

## Frame time

Attic fixture, scale 4, msaa 4, smoothing 2, enhanced, `occlusion="off"`
vs `occlusion="ssao"`, timing `backend.draw()` + `ctx.finish()` (two
`GLBackend`s built once, frames alternated between them rather than
drawn with one backend fully before the other, to avoid a shader-compile
/ driver-cache order bias -- the same precaution
`docs/actor-textures-proof.md`'s script records), with a scratch script
(not part of the shipped repo, the same convention the soft-shadows,
motion and actor-textures proofs used):

```
$ SDL_VIDEODRIVER=dummy .venv/bin/python scratch_timing_ssao.py \
    "data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK" 20 3
off 6.10 ms  (min 5.19, max 7.38)
on 6.28 ms  (min 4.89, max 11.30)
```

This machine is shared and noisy (every prior proof in this repo records
the same thing about its own timing runs). Sixteen back-to-back
invocations (script unmodified, same arguments) gave:

```
off means (ms): 7.20 6.44 6.24 7.08 5.28 5.50 6.25 6.81 6.29 7.38 6.73 5.88 6.55 6.12 7.28 5.62
on means (ms):  7.55 6.95 6.05 7.20 5.42 5.64 6.25 6.27 5.79 7.59 6.78 5.70 6.98 5.84 7.24 5.47
```

off ranged 5.28-7.38 ms (mean of means 6.42 ms), on ranged 5.42-7.59 ms
(mean of means 6.42 ms). Per-run ratio (on/off) ranged **0.92x to 1.08x**
across the sixteen runs, **ratio of means 1.001x**, and none of the
sixteen runs came anywhere near the 1.5x budget. On this two-actor attic
fixture the G-buffer prepass plus the two SSAO passes and their blur cost
essentially nothing next to the rest of the frame -- asset resolution, GPU
upload and the draw call itself. The spec's 1.5x budget applies to the
whole roadmap-2 plan with all four sub-projects (I motion, J textures, K
light transport, and the remaining atmosphere sub-project) on at once,
not to K alone; that is a roadmap-level gate this task does not itself
carry. **Record K's own contribution against this branch's base: roughly
1.0x, not a meaningful draw on the budget.**

The scratch script lived at `scratch_timing_ssao.py` for this measurement
and is not part of the shipped repo.

## The fixture-review gate

The receiver pass rasterises the room's floor plane plus the top face of
every `hard_col` in the current room (`render/scene.py:room_receivers`);
vertical faces are excluded by design (`ReceiverQuad`'s own docstring).
Whether `RenderOptions.shadows` should default to `"room"` is a human
decision on real fixtures, not this task's to make -- Task 5 kept the
default at `"soft"` and this task does not move it either.

| Receiver class | Where it appears in the two fixtures | Looks right? |
|---|---|---|
| Floor only (no `hard_col` in view) | attic debug start, this camera/light | pending |
| Floor + box tops (`hard_col`s in view) | combat venue, this camera/light | pending |

## Manual attestation

| Check | Result |
|---|---|
| SSAO reads as contact shading rather than a dark outline | pending |
| Thin limbs do not halo | pending |
| The receiver shadow lands on furniture rather than beside it | pending |
| A moving actor's occlusion does not crawl or flicker | pending |

## Known limitations

- **SSAO is half resolution.** The G-buffer prepass, the SSAO pass and its
  blur all run at half the internal render resolution; thin limbs can halo
  where the bilateral blur cannot fully bound the resolution mismatch. This
  is the spec's own named trade, not a defect to fix here.
- **`hard_cols` are proxies, not painted furniture.** Vertical faces are
  excluded from the receiver pass entirely (`ReceiverQuad`, `render/scene.py`)
  -- a shadow on a box's side would read as a bug where a shadow on its top
  reads as the top of the thing it stands for. The default stays `"soft"`
  until a human looks at real frames and decides otherwise; if the review in
  "The fixture-review gate" above never resolves in `"room"`'s favour,
  `"room"` stays a complete, shippable menu choice, not a failure of this
  plan.
- **Screen-space occlusion attenuates `fill_tint` alone, on purpose.**
  `ACTOR_FSH` already has two other terms that read as "occlusion" by name
  -- `occl` (`mix(1.0, v_ao, preset_a.z) * contact`, the baked rest-pose AO
  gated by the shadow map's own contact term) and `hemi` (the ambient
  hemisphere term) -- and both multiply the *whole* of `base`, key share
  included. Folding SSAO into either would darken the key light a second
  time, double-counting exactly what the light-view shadow map already
  owns. Do not "simplify" `vec3 base = albedo * (fill_tint * ssao +
  key_tint * wrapped * wrapped * vis);` into a form that routes `ssao`
  through `occl` or `hemi` instead -- it reads like a cleanup and is a
  regression the golden and identity tests will not catch, because neither
  fixture's baseline exercises a scene where the two forms disagree by
  more than a rounding error.
