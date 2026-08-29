# Soft shadows proof

Date: 2026-08-29
Spec: `docs/superpowers/specs/2026-08-29-actor-realism-roadmap-design.md` (sub-project F)

**This document's "Manual attestation" table is a checklist for a human
with real game data and a real window; every row started `pending` and no
claim about the rendered PNGs should be inferred from this file until a
human fills them in.** (One row has since been partly answered by a
measurement rather than by a human at a window; it says exactly which half
it answers and which half is still `pending`.) Everything under "Automated
gates" was actually run, in this environment, on this branch, and the
output shown is the real output of that run.

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

`R_MAX_PER_SCALE` (the widest penumbra radius the blur honours, in pixels
per unit of render scale) is 4 in the shipped code, not the plan's 6: the
frame-time measurement below came in over budget at 6 and the plan's own
sanctioned remedy -- lower it to 4 and re-measure -- brought it back under.
See "Frame time" and "Deviations from the plan".

## Automated gates

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_lighting.py tests/test_render_gl.py tests/test_render_options.py tests/test_layering.py tests/test_ui_reducers.py tests/test_ui_render.py tests/test_prove_graphics.py -q
285 passed in 6.66s
```

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest -q
1407 passed, 2 skipped, 1 xfailed, 26 warnings in 49.29s
```

`tests/test_render_gl.py::test_classic_realism_matches_the_pre_materials_golden`
(now naming `shadows="hard"`), `test_soft_with_nothing_to_shadow_is_byte_identical_to_hard`
(the plumbing identity) and `test_the_soft_blur_matches_the_numpy_twin`
(the shader against `lighting.soften`) are the binding ones.

`test_the_penumbra_hardens_toward_the_feet` casts from an upright flat quad
(one drop per shadow row, not the hex prism the plan described -- see
"Deviations from the plan") and measures, at `R_MAX_PER_SCALE=4`, a 5.2 px
edge width near the feet (rows 140-144) versus 20.3 px far from them (rows
156-161) -- a 3.9x ratio, comfortably past the test's `> 2.0x` bound -- and
0 px on every row under `hard`.

## `make proof-graphics`

Sixteen PNGs under `docs/graphics-proof/` (git-ignored): the twelve
`<attic|combat>-<flat|lambert|smooth>-<classic|enhanced>.png` at the
defaults, `<fixture>-smooth-enhanced-flatmesh.png` at smoothing 0, and
`<fixture>-smooth-enhanced-hardshadow.png` at `shadows=hard`.

Comparing `attic-smooth-enhanced.png` against its `-hardshadow` twin pixel
by pixel: 42,658 of 1,024,000 pixels (4.17%) differ, in a bounding box (x
0-1163, y 120-709 of the 1280x800 frame) that spans the lantern's shadow on
the tablecloth, Carnby's own shadow region, and the rocking horse's shadow
-- not just a tight band under one actor's feet. Cropped to the lantern
(whose base sits on the green tablecloth): under `hard` its shadow is a
sharp-edged dark-green wedge with a crisp diagonal boundary; under `soft`
the same wedge is visibly blurred with soft edges throughout, and darkest
where the lantern's base actually touches the cloth. Cropped to the area
behind Carnby's legs (where his arm's shadow falls, well above the floor):
under `hard` it is a solid, sharply-edged dark shape; under `soft` it is
barely visible at all, spread out and faded almost into the floor colour --
consistent with the model (a caster far above its plane gets a penumbra
radius near `R_MAX`, spreading the same coverage over a much wider, much
fainter area). The rocking horse's leg, which touches the floor directly,
looks close to identical between the two crops, consistent with
contact-hardening leaving a near-zero-height shadow effectively sharp
either way.

## Frame time

Attic fixture, scale 4, msaa 4, smoothing 2, enhanced, 20 frames after 3
warm-ups, `ctx.finish()` after each:

```
$ SDL_VIDEODRIVER=dummy .venv/bin/python scratch_timing.py
hard 3.92 ms
soft 5.67 ms
```

`soft` is 1.45x `hard` on this run -- under the 1.5x budget, but close to
it. This measurement is noisy on this shared machine: 16 back-to-back runs
(script unmodified, `R_MAX_PER_SCALE=4`) ranged from 1.21x to 1.90x per-run,
with a mean of hard=4.12 ms / soft=5.86 ms (ratio of means 1.42x) and 3 of
the 16 runs individually over 1.5x. At the plan's original `R_MAX_PER_SCALE
= 6`, the first measurement was hard=3.53 ms, soft=5.87 ms (1.66x), clearly
over budget, which is why the constant was lowered per the plan's sanctioned
remedy. The honest summary: at scale 4 the soft path centers on roughly
1.4x hard with real run-to-run variance that occasionally crosses 1.5x, not
a comfortable, decisively-under-budget number.

### Scale 8

Scale 4 is not the largest scale the option offers, so the same fixture and
settings were measured again at scale 8. Attic fixture, msaa 4, smoothing
2, enhanced, 15 frames after 3 warm-ups, `ctx.finish()` after each, in one
invocation of the plan's Step-4 script with the scale, frame count and
repeat count taken from argv:

```
$ SDL_VIDEODRIVER=dummy .venv/bin/python scratch_timing.py 8 15 13
scale 8  hard 8.86 ms  soft 12.81 ms  ratio 1.45x
scale 8  hard 8.63 ms  soft 12.69 ms  ratio 1.47x
scale 8  hard 8.80 ms  soft 12.79 ms  ratio 1.45x
scale 8  hard 9.13 ms  soft 13.17 ms  ratio 1.44x
scale 8  hard 9.14 ms  soft 13.76 ms  ratio 1.51x
scale 8  hard 9.45 ms  soft 14.45 ms  ratio 1.53x
scale 8  hard 9.20 ms  soft 13.99 ms  ratio 1.52x
scale 8  hard 8.92 ms  soft 12.78 ms  ratio 1.43x
scale 8  hard 8.59 ms  soft 12.85 ms  ratio 1.49x
scale 8  hard 8.62 ms  soft 12.73 ms  ratio 1.48x
scale 8  hard 8.90 ms  soft 12.69 ms  ratio 1.43x
scale 8  hard 9.82 ms  soft 12.98 ms  ratio 1.32x
scale 8  hard 9.21 ms  soft 13.23 ms  ratio 1.44x
```

hard 8.59-9.82 ms (mean 9.02), soft 12.69-14.45 ms (mean 13.15); per-run
ratios 1.32x to 1.53x, **ratio of means 1.46x**. Three of the thirteen runs
were at or over 1.5x. An earlier sitting of thirteen runs at the same
settings gave hard 8.78-10.08 ms, soft 12.94-15.00 ms, per-run 1.36x to
1.59x, ratio of means 1.44x -- so 1.44-1.46x is the number to carry, with
individual frames crossing 1.5x in both sittings.

Two things this does *not* show, stated plainly because the tempting
readings of it are both wrong:

- **It does not show the soft/hard ratio worsening with scale.** Eight
  scale-4 runs of the same script in the same sitting gave hard 3.65-5.40
  ms, soft 5.84-7.53 ms, per-run 1.15x to 1.80x, ratio of means 1.49x --
  in the same band as scale 8, and far noisier. Scale 8's contribution is
  a *tighter* estimate (1.32-1.53x per run against scale 4's 1.15-1.80x),
  not a worse one: the per-frame cost is large enough there for scheduling
  jitter to stop dominating.
- **It does not show the frame time scaling with pixel count.** Four times
  the pixels cost about twice the time on both paths (hard 4.55 -> 9.02
  ms, soft 6.78 -> 13.15 ms, comparing the scale-4 and scale-8 runs above,
  which were made back to back), so neither path is fill-rate-bound at
  these sizes.

Worth stating precisely, though, because it is the growth term that will
eventually bite: the blur's added work is **not quadratic in render
scale**. It runs over `s^2` more pixels *and* takes a kernel
`R_MAX_PER_SCALE * s` wide in each of its two separable passes, so the
blur alone is `O(s^3)` while the rest of the frame is `O(s^2)`. That term
is not what the measurements above are dominated by -- at scale 8 the
frame is still bound by something else -- but it is why the budget cannot
be assumed to hold at a larger scale just because it holds at scale 4, and
why scale 8, the largest the option offers, is the one that was measured.

## Deviations from the plan

- **`R_MAX_PER_SCALE` is 4, not 6** (see above). This is the plan's own
  sanctioned remedy for an over-budget measurement, applied because the
  measurement needed it, not skipped.
- **The penumbra test's scene differs from the plan.** The plan's
  `test_the_penumbra_hardens_toward_the_feet` cast from a hex prism and
  compared image rows 137-139 against 142-150; that scene has z-depth, so
  under MAX blending every visible shadow row is reached by many drops at
  once and the claim was unattainable. The shipped test keeps the name,
  the claim and the `> 2x` ratio but casts from an upright flat quad (one
  drop per shadow row) and measures per-row edge width against that row's
  own floor.
- **The coverage texture's penumbra-radius (G) channel is MAX-blended**,
  not MIN, because R and G share one colour blend equation with the
  coverage (R) channel, which must be MAX (two casters' shadows must not
  subtract). For a single solid caster this means the shadow is uniformly
  as soft as its softest (highest) part rather than hardening under its
  own footprint -- visible above in the Carnby-arm crop, where the whole
  shape reads at the soft, high radius rather than sharpening toward the
  contact points within it. MIN would be the faithful per-caster rule but
  is wrong the moment two casters' shadows overlap; this is a deliberate,
  ruled-on trade-off, not an oversight.

## Known limitations

- A penumbra can bleed up to `4 * scale` pixels (`R_MAX_PER_SCALE`) across
  a foreground mask's edge: the blur runs after the mask erase.
- The coverage texture's penumbra-radius channel is MAX-blended along with
  the coverage channel (see "Deviations from the plan"): a single solid
  caster's shadow is uniformly as soft as its softest part, not hardened
  under its own footprint.
- One depth map for every actor in the frame: its texel is the frame's
  actor extent over 2048, coarse in the widest caves; single-sided panels
  can show acne bounded by the bias. The bias itself
  (`SHADOW_BIAS_UNITS = 4.0`, unchanged from the plan) is a fixed count of
  world units while the map's texel footprint scales with the union of
  every actor's bounding box, so a scene with actors spread far apart has
  coarser texels -- and thus a less conservative effective bias -- than the
  single-actor scenes the automated tests measure.
- The shadow map and the actor shader disagree about which way the light
  goes. `_render_shadow_map` builds the map through `light_view_matrix`,
  which tips `travel` onto the `MIN_UP` cone (`lighting._clamp_downward`)
  so the map and the ground shadow always agree; `ACTOR_FSH`'s `light`
  uniform, meanwhile, is `SceneLight.direction` raw -- camera space,
  unclamped. For most cameras the clamp is a no-op and the two agree, but
  `project_to_plane`'s docstring records that the unclamped world-space
  travel points *upward* for four shipped (room, camera) pairs; in those
  the frame's `vis` (from the map, clamped) and its `wrapped` diffuse
  term (from `light`, unclamped) are computed from genuinely different
  directions: a fragment's diffuse falloff and its shadow test no longer
  agree about where the key is, so a face can be shaded as lit while the
  map has it occluded, or the reverse.
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
| `--shadows soft` at scale 8 in the floor-5 combat venue keeps a playable frame rate | half answered -- see "Frame time / Scale 8". Scale 8 was **measured, not played**: on the attic fixture, headless, `soft` renders in 12.69-14.45 ms/frame (~69-79 fps of pure render time) against `hard`'s 8.59-9.82 ms. That establishes the render cost at scale 8 and it leaves headroom. It does *not* establish a played-through frame rate in the floor-5 combat venue, which is a busier scene inside a real game loop and a real window, with input, LIFE and the UI composite on the same thread. The playability half of this row is still `pending`. |
