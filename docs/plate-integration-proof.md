# Plate integration proof

Date: 2026-08-30
Spec: `docs/superpowers/specs/2026-08-29-actor-realism-roadmap-design.md` (sub-project G)

**This document's "Manual attestation" table is a checklist for a human
with real game data and a real window; every row started `pending` and no
claim about the rendered PNGs should be inferred from this file until a
human fills them in.** Everything under "Automated gates", "`make
proof-graphics`" and "Frame time" was actually run, in this environment, on
this branch, against real game data, and the output shown is the real
output of that run. Where a paragraph describes what a rendered PNG *looks
like*, it is describing a crop that was actually opened and read — but a
human at a window is still the authority, and the attestation rows below
say which of those readings are the ones that most need checking.

## What changed

`integration` defaults to `on`. Under `lighting="scene"` the frame is now
assembled in two layers instead of one: the background and the gathered
shadow pass render into `_plate_tex`, the bodies are cleared to transparent
and rendered into `_actor_tex`, and one full-target pass (`COMPOSITE_FSH`)
puts the second back onto the first. Between the two, the actor layer is
matched to the room it is standing in, using four quantities read off the
camera's own background image by `PyAitD/render/plate.py`:

- **Sharpness.** `softness(background_filter, src_size, target_size)`
  returns `(sigma_px, cell_px, pixelate)`. One plate pixel covers
  `cell = target_w / src_w` target pixels; `bilinear` left the plate soft
  over `0.35 * cell`, `xbr` over `0.15 * cell`, and the actor layer is
  sampled through a Gaussian of that sigma so its edge is no crisper than
  the room's. Under `nearest` the actor is instead fetched once at the
  centre of its plate cell, so a blocky plate gets blocky actors on the
  same grid.
- **Tone.** `estimate_plate` takes the mean colour of the darkest and
  brightest 1% of the plate by luma as the room's `black` and `white`. The
  composite lifts the actor's darks by `black * (1 - luma)^4 * TOE` and
  pulls its brights down by `(1 - white) * luma^4 * SHOULDER`, so the actor
  meets the plate exactly at both extremes and its midtones are barely
  touched (at luma 0.5 only 1/16 of either offset applies).
- **Grain.** `estimate_plate`'s `grain` is the RMS of the plate's luma
  residual against its own 3x3 box mean, and `grain_retention` is the
  fraction of it the background filter leaves once the plate is magnified.
  The composite adds
  `grain * retention * (hash(floor(gl_FragCoord.xy / cell)) - 0.5) * GAIN`,
  hashed on the screen cell alone so it sits still like the plate's dither
  rather than crawling between frames. The retention factor is the one
  correction this task made to the shipped model; its derivation and the
  measurement that forced it are the next section.
- **Coverage.** `out = plate * (1 - a) + c * a`, on premultiplied values
  throughout, so a soft edge cannot bleed the actor's interior colour into
  fully transparent pixels.

`integration="off"` keeps the previous single-target path, byte for byte,
and is a row on the Graphics page and a `--integration` CLI flag.
`lighting="fixed"` runs the single-target path whatever `integration`
says. `smoothing=0` with `shadows="hard"`, `realism="classic"` and
`integration="off"` still reproduces `tests/golden/scene_lit_classic.npy`
byte for byte.

`TOE` and `SHOULDER` are 1.0 and `GAIN` is `sqrt(12)`, and all three are
derived rather than tuned. `TOE = SHOULDER = 1` is what makes the curve
meet the plate *exactly* at the extremes: at luma 0 the whole of `black` is
added, at luma 1 the whole of `1 - white` is subtracted. `GAIN` follows
from the hash: `hash - 0.5` is uniform on [-0.5, 0.5], whose RMS is
`1/sqrt(12)`, so multiplying by `sqrt(12)` makes the composited residual's
RMS equal whatever amplitude it is handed. None of the three was changed
by the fixture pass. The fixture pass did, however, show that the
amplitude `GAIN` was being handed was the wrong one — the plate's dither
as *stored*, not as *displayed* — which the next section fixes without
touching any of the three.

### The grain is matched to the plate as displayed, not as stored

The first pass of this task shipped the grain at `estimate_plate`'s raw
amplitude, and looking at the rendered fixtures is what caught the problem:
the composited actor was visibly noisier than the room it was being joined
to, in hard `cell`-sized blocks. The cause is that `grain` is a *source*
amplitude — measured on the 320x200 image — while what the actor stands
next to is that image after `background_filter` has magnified it, and a
smoothing filter attenuates dither on the way. Measured on the attic plate
at scale 4: 8.48 counts of luma residual on the source against 5.05 counts
still carried per plate cell by the plate as displayed. The actor was
receiving 1.68x the room's own amplitude.

`plate.grain_retention(background_filter, src_size, target_size)` closes
that gap, and it is derived rather than fitted. Under GL_LINEAR
magnification by an integer `cell`, target pixel `j` samples the source at
`x = (j + 0.5) / cell - 0.5`, so the `cell` target pixels covering source
pixel `m` interpolate between `m` and one of its neighbours. Summing their
weights and dividing by `cell`, the mean of one cell is
`v*s[m-1] + (1 - 2v)*s[m] + v*s[m+1]` with

```
v = (cell**2 - cell % 2) / (8 * cell**2)
```

— exactly **1/8 for every even cell**, 1/9 at cell 3, and 0 at cell 1. For
a dither modelled as white, which is precisely what `_grain`'s
residual-against-the-3x3-mean estimator already assumes it is, a separable
2D kernel scales the RMS by the sum of its squared 1D weights, so

```
retention = 2*v**2 + (1 - 2*v)**2
```

| cell | 1 | 2 | 3 | 4 | 6 | 8 |
|---|---|---|---|---|---|---|
| retention | 1.0 | 0.59375 | 0.62963 | 0.59375 | 0.59375 | 0.59375 |

`nearest` and `xbr` both retain 1.0, and for the same reason rather than by
coincidence: both sample with GL_NEAREST and never average two texels, so
every displayed pixel *is* some source texel and the dither arrives intact.
`BG_FSH`'s xbr is a selection — it returns either the nearest texel or a
neighbour, never a blend — and its branch is gated on finding an edge
(`distance(h, v) < 0.05` with `distance(h, c) > 0.1`), which dither does
not produce. The xBR-only-at-320x200 fallback is shared with `softness`
and must be: `_draw_background` runs the xbr shader only when the source
really is `CLASSIC_PLATE_SIZE` and uses GL_LINEAR anywhere else, so at any
other size a model claiming xbr's retention would be describing a filter
that did not run.

The derivation's evidence is a synthetic check, not the attic:
`tests/test_plate.py::test_grain_retention_predicts_a_synthetic_upscale`
builds a white-noise plate, magnifies it with an independently written
GL_LINEAR upscale, averages each cell back down, and asserts the measured
RMS ratio matches `grain_retention` within 2%. Measured against predicted:

| cell | 2 | 3 | 4 | 6 | 8 |
|---|---|---|---|---|---|
| predicted | 0.59375 | 0.62963 | 0.59375 | 0.59375 | 0.59375 |
| measured on synthetic noise | 0.59683 | 0.63242 | 0.59683 | 0.59683 | 0.59683 |

— agreement to about 0.5% at every cell, the excess being the edge-clamped
border. A hardcoded constant would pass at cell 4 and fail at cell 3.

Real data then agrees independently: the attic's `grain` of 0.0332 times
0.59375 is **5.03 counts**, against the **5.05 counts** measured directly
off the displayed plate. Those are different measurements of the same
quantity — one predicted from the filter, one read off the frame — and they
land 0.4% apart.

`GAIN` is untouched at `sqrt(12)`, and so is its derivation: the bug was
never in the calibration from a uniform hash to unit RMS, only in which
amplitude that unit was being multiplied by. `TOE` and `SHOULDER` stay 1.0.
At `cell == 1` retention is 1.0, so
`test_grain_lands_at_the_plates_own_amplitude`, which renders at scale 1,
passes unchanged — if it had moved, the retention would have been wrong at
cell 1.

One non-obvious guard is worth naming here because it is easy to delete by
accident: `render_gl._composite` divides every fragment by `cell`, so a
`cell` of 0 would give `floor(inf)` and a NaN grain seed, and `0.0 * NaN`
is NaN, not 0 — the `a.a > 0.0` branch would not contain it. `cell` can
never be 0 only because `plate.softness` computes
`cell = target_w / src_w if src_w > 0.0 else 1.0`. That `else 1.0` is
load-bearing, not defensive noise.

## Automated gates

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_plate.py -q
32 passed in 0.11s
```

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_plate.py tests/test_render_gl.py tests/test_render_options.py tests/test_layering.py tests/test_ui_reducers.py tests/test_ui_render.py tests/test_prove_graphics.py tests/test_config.py tests/test_main.py -q
347 passed, 2 warnings in 10.95s
```

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest -q
1492 passed, 2 skipped, 1 xfailed, 26 warnings in 55.12s
```

The two skips and the xfail are the suite's standing ones, unrelated to
this change; the baseline before the default flip was 1474 passed, 2
skipped, 1 xfailed, 26 warnings. The 18 added are
`tests/test_prove_graphics.py::test_the_default_composites_and_nocomposite_does_not`,
16 `grain_retention` cases in `tests/test_plate.py`, and
`test_grain_lands_at_the_plates_displayed_amplitude_once_magnified`.

The binding tests are
`tests/test_render_gl.py::test_integration_on_with_a_neutral_plate_reproduces_the_golden`
(the plumbing identity: with `NEUTRAL_PLATE` every composite term vanishes
by construction, so `on` must reproduce the pre-change golden exactly),
`test_integration_on_matches_off_pixel_for_pixel_at_msaa_zero` (the same
identity on a real cast shadow under both shadow modes, over a plate every
column of which differs),
`test_nothing_is_softened_when_the_plate_is_already_target_resolution`,
`test_integration_leaves_fixed_lighting_untouched`, and
`test_classic_realism_matches_the_pre_materials_golden`, which now names
`integration="off"` alongside `smoothing=0` and `shadows="hard"`.

For the grain, three tests hold the model between them and none of the
three is redundant:
`tests/test_plate.py::test_grain_retention_predicts_a_synthetic_upscale`
(the derivation, against an independently written upscale),
`tests/test_render_gl.py::test_grain_lands_at_the_plates_own_amplitude`
(the composited residual at `cell == 1`, unchanged by this task), and
`test_grain_lands_at_the_plates_displayed_amplitude_once_magnified` (the
composited residual at `cell == 4`, which is the one that would catch a
regression to the source amplitude). Removing the retention factor from
`_composite` makes the last of these fail with 20.41 counts measured
against 12.11 expected — a 1.69x miss, not a tolerance nudge.

### The default flip broke exactly one test

`tests/test_render_gl.py::test_a_gathered_shadow_never_darkens_an_earlier_actor`.
It asserts that under `shadows="hard"` a nearer actor's projected
silhouette still paints over a farther body — the ordering artefact of
the per-actor full-target multiply, which `shadows="soft"` was introduced
to fix and which `hard` keeps verbatim — and it got `integration="off"`
from the default rather than naming it. Under `integration="on"` the hard
casts have to reach the *plate* layer, so they all run before any body is
drawn, and the artefact goes with them. `_render_overlap` now takes
`integration` and defaults it to `"off"` explicitly, and the test gained
two lines that render the same pair at `integration="on"` and assert the
artefact is *absent* there, so the behaviour difference is pinned by a test
rather than only described in this document. It is recorded under "Known
limitations" as a deliberate difference from `off`.

No test failed for the second anticipated reason (an exact pixel at
`msaa > 0` landing a count apart across the 8-bit round trip). That case
was already covered before this task, with a tolerance and a comment, by
`test_integration_on_still_resolves_msaa_into_the_same_texture`.

## `make proof-graphics`

```
$ make proof-graphics
.venv/bin/python tools/prove_graphics.py "data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK"
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
```

Eighteen PNGs under `docs/graphics-proof/` (git-ignored): the twelve
`<attic|combat>-<flat|lambert|smooth>-<classic|enhanced>.png` at the
defaults, `<fixture>-smooth-enhanced-flatmesh.png` at smoothing 0,
`<fixture>-smooth-enhanced-hardshadow.png` at `shadows=hard`, and the pair
this sub-project adds, `<fixture>-smooth-enhanced-nocomposite.png` at
`integration=off`.

Comparing each `-smooth-enhanced.png` against its `-nocomposite` twin pixel
by pixel, at scale 4 (a 1280x800 frame over a 320x200 plate, so `cell` is
4 and `sigma` is 1.4 px):

| | differing pixels | bounding box | max channel delta | mean delta where differing |
|---|---|---|---|---|
| attic | 76,111 of 1,024,000 (7.43%) | x 36-1279, y 117-738 | 115 | 8.99 |
| combat | 4,937 of 1,024,000 (0.48%) | x 399-655, y 261-292 | 57 | 8.30 |

(Before the grain retention factor the attic's mean delta was 10.32 and the
combat's 8.59, on the same pixel counts: the composite touches the same
pixels either way and moves them less far now.)

The attic frame draws 10 actors, covering 88,589 pixels. Of the 76,124
that the composite moves, 68,267 are pixels a body was drawn on and 7,857
are not: the softening Gaussian (sigma 1.4, radius 3) carries the actor
layer's coverage up to three pixels past each silhouette, which is exactly
what matching the plate's edge width means and is the only way a
composited pixel lands where no body was. Beyond that band the plate is
untouched, which is what the "over" formula promises. The combat fixture
has only the one plank actor visible from its camera, which is why its
bounding box is a 257x32 band.

The attic pair is the one worth attesting against: it draws 10 actors,
while the combat fixture's camera shows only the plank. The `-nocomposite`
twin is rendered at `shadows=soft`, the default, so it isolates the
composite from the shadow mode; the `shadows=hard` ordering difference is
covered by a test rather than by a PNG pair.

Read as pictures rather than as counts, cropping the attic pair around
Carnby's head and shoulders at 3x: `-nocomposite` gives a crisp,
high-contrast figure that plainly sits *in front of* the room rather than
in it. The composited render is visibly softer — the edge ramp matches the
bilinear plate's, the face's darks are lifted toward the room's warm floor,
and the figure stops looking cut out. That is the feature working.

The same frame was rendered four ways to judge the grain: `off`, `on` at
the source amplitude (what the first pass shipped), `on` with `grain`
forced to 0, and `on` with the retention factor live. At the source
amplitude the figure is dithered by a visibly coarser process than the one
that dithered the room — Carnby's face loses its features and the window
panes behind him checkerboard. With the retention factor the amplitude
drops by the derived 0.594 and the crop reads as a shaded surface carrying
a light dither rather than as damage; on the trousers at 5x, beside the
floor's own texture, the two now look like the same kind of noise.

Honestly stated, the fix does not make the term invisible, and the residual
is structural rather than a matter of amplitude. Measured on the injected
field alone (the difference between two otherwise identical renders):

| | injected grain, after the fix | the displayed plate |
|---|---|---|
| RMS per plate cell | 5.04 counts | 5.05 counts |
| 3x3 residual per target pixel | 2.32 counts | 1.40 counts |

At the cell scale — the scale the term is *for* — the actor now carries
exactly the room's amplitude. At the target-pixel scale it still carries
1.66x the room's, because the injected field is a hard block across each
cell while the plate's dither arrives as a smooth bilinear ramp across the
same cell. Before the fix that figure was about 2.8x. So: the amplitude
error is closed, a smaller shape difference remains, and it is recorded as
a limitation rather than claimed away. At 3x zoom on the face you can still
find cell-sized blocks.

## Frame time

Attic fixture, msaa 4, smoothing 2, enhanced, `shadows=soft`,
`ctx.finish()` after each frame, warmed up with 3 frames before each timed
run — `docs/soft-shadows-proof.md`'s script with `shadows` swapped for
`integration`.

### `integration` alone, on against off

Scale 4, 20 frames per run, 12 runs:

```
$ SDL_VIDEODRIVER=dummy .venv/bin/python scratch_timing_integration.py 4 20 12
scale 4  off 5.29 ms  on 5.85 ms  ratio 1.11x
scale 4  off 5.20 ms  on 6.55 ms  ratio 1.26x
scale 4  off 5.00 ms  on 6.26 ms  ratio 1.25x
scale 4  off 5.06 ms  on 6.73 ms  ratio 1.33x
scale 4  off 4.94 ms  on 5.92 ms  ratio 1.20x
scale 4  off 5.31 ms  on 6.10 ms  ratio 1.15x
scale 4  off 5.57 ms  on 5.59 ms  ratio 1.00x
scale 4  off 6.29 ms  on 5.82 ms  ratio 0.93x
scale 4  off 4.83 ms  on 6.06 ms  ratio 1.25x
scale 4  off 7.88 ms  on 4.91 ms  ratio 0.62x
scale 4  off 4.61 ms  on 5.03 ms  ratio 1.09x
scale 4  off 5.42 ms  on 8.20 ms  ratio 1.51x
```

off 4.61-7.88 ms (mean 5.45), on 4.91-8.20 ms (mean 6.08), **ratio of means
1.12x**, per-run 0.62x to 1.51x. Scale 4 is as noisy on this shared machine
as `docs/soft-shadows-proof.md` found it — two runs came in with `on`
*faster* than `off`, which is scheduling jitter, not a result.

Scale 8, 15 frames per run, 13 runs:

```
$ SDL_VIDEODRIVER=dummy .venv/bin/python scratch_timing_integration.py 8 15 13
scale 8  off 13.40 ms  on 15.37 ms  ratio 1.15x
scale 8  off 13.42 ms  on 16.13 ms  ratio 1.20x
scale 8  off 13.82 ms  on 15.73 ms  ratio 1.14x
scale 8  off 13.78 ms  on 15.93 ms  ratio 1.16x
scale 8  off 13.67 ms  on 16.17 ms  ratio 1.18x
scale 8  off 13.22 ms  on 15.42 ms  ratio 1.17x
scale 8  off 13.23 ms  on 15.88 ms  ratio 1.20x
scale 8  off 13.08 ms  on 15.77 ms  ratio 1.21x
scale 8  off 13.64 ms  on 15.65 ms  ratio 1.15x
scale 8  off 13.18 ms  on 16.61 ms  ratio 1.26x
scale 8  off 13.24 ms  on 15.44 ms  ratio 1.17x
scale 8  off 13.29 ms  on 15.54 ms  ratio 1.17x
scale 8  off 13.97 ms  on 15.56 ms  ratio 1.11x
```

off 13.08-13.97 ms (mean 13.46), on 15.37-16.61 ms (mean 15.78), **ratio of
means 1.17x**, per-run 1.11x to 1.26x, no run over 1.5x. As in the soft
shadows measurement, scale 8's contribution is a *tighter* estimate than
scale 4's, not a worse one: the per-frame cost is large enough there for
scheduling jitter to stop dominating. Taken on its own, `integration` is
comfortably inside the 1.5x budget at both scales.

### The spec's actual budget: F, H and G all on against all three off

The roadmap spec states the budget as "with F, H and G all on, the attic
frame at those settings renders in at most 1.5x the time it takes with all
three off" — that is `shadows=soft, realism=enhanced, integration=on`
against `shadows=hard, realism=classic, integration=off`, not the
one-feature comparison above. Measured the same way, 8 runs each:

```
$ SDL_VIDEODRIVER=dummy .venv/bin/python scratch_timing_roadmap.py 4 20 8
scale 4  all off 5.37 ms  all on 6.95 ms  ratio 1.29x
scale 4  all off 5.43 ms  all on 6.65 ms  ratio 1.22x
scale 4  all off 5.01 ms  all on 6.19 ms  ratio 1.24x
scale 4  all off 4.91 ms  all on 7.66 ms  ratio 1.56x
scale 4  all off 4.84 ms  all on 6.55 ms  ratio 1.36x
scale 4  all off 6.09 ms  all on 6.71 ms  ratio 1.10x
scale 4  all off 4.30 ms  all on 5.66 ms  ratio 1.32x
scale 4  all off 4.88 ms  all on 5.32 ms  ratio 1.09x

$ SDL_VIDEODRIVER=dummy .venv/bin/python scratch_timing_roadmap.py 8 15 8
scale 8  all off 10.28 ms  all on 15.60 ms  ratio 1.52x
scale 8  all off  9.96 ms  all on 16.00 ms  ratio 1.61x
scale 8  all off  9.76 ms  all on 15.85 ms  ratio 1.62x
scale 8  all off  9.67 ms  all on 15.89 ms  ratio 1.64x
scale 8  all off  9.78 ms  all on 15.52 ms  ratio 1.59x
scale 8  all off  9.66 ms  all on 15.68 ms  ratio 1.62x
scale 8  all off 10.03 ms  all on 15.82 ms  ratio 1.58x
scale 8  all off 10.20 ms  all on 16.54 ms  ratio 1.62x
```

Scale 4: all-off 4.30-6.09 ms (mean 5.10), all-on 5.32-7.66 ms (mean 6.46),
**ratio of means 1.27x**, per-run 1.09x to 1.56x — one of eight runs over
the budget, the rest inside it. Inside budget on the ratio of means.

Scale 8: all-off 9.66-10.28 ms (mean 9.92), all-on 15.52-16.54 ms (mean
15.86), **ratio of means 1.60x**, per-run 1.52x to 1.64x. **This is over
the spec's 1.5x budget, and every one of the eight runs is individually
over it.** It is not noise: the per-run spread is 1.52-1.64x, tighter than
the margin by which it misses. Stated plainly rather than retuned away —
neither `MAX_BLUR_RADIUS` nor `R_MAX_PER_SCALE` nor the composite's blur
radius was touched to make this number look better. It is recorded under
"Known limitations".

Where the 1.60x comes from is worth separating, because it is not mostly
this sub-project: at scale 8 `integration` alone costs 1.17x, and
`docs/soft-shadows-proof.md` measured `soft` alone at 1.44-1.46x there. The
stack is multiplicative, so soft shadows and the composite together already
account for roughly 1.7x of raw cost against a `hard`/`off` baseline before
`enhanced` materials are counted; the measured 1.60x is that stack against
a *classic* baseline that is itself cheaper. G is the increment that pushed
a stack already near the line over it, but it is not the largest term in
it. Lowering the budget's pressure would mean revisiting F's blur, not this
composite.

Absolute numbers, which the ratio hides: at scale 8 the fully-enabled attic
frame renders in 15.5-16.6 ms of pure render time, about 60-64 fps, on a
2560x1600 internal target. That leaves far less headroom
than scale 4's 6.5 ms, and it is render time only — no input, LIFE, UI
composite or window present.

## Deviations from the plan

- **The plan's msaa claim needed a qualification, and the test that
  carries it needed a different plate.** The plan says `on` and `off`
  agree at `msaa > 0` up to 8-bit quantisation. That is true only where
  `cell <= 1`. Task 4's softening makes the two differ *by design*
  wherever one plate pixel covers more than one target pixel — which is
  every shipped 320x200 plate at scale > 1, i.e. the normal case.
  Measured on the gradient plate at scale 2, actor over a real cast:

  | | `cell == 1` (plate upscaled to target) | `cell == 2` (shipped 320x200 plate) |
  |---|---|---|
  | msaa 0 | 0 counts, 0.00% of pixels differ | 61 counts, 1.58% |
  | msaa 2 | 0 counts, 0.00% | 61 counts, 1.58% |
  | msaa 4 | 1 count, 0.09% | 61 counts, 1.58% |
  | msaa 8 | 1 count, 0.09% | 61 counts, 1.58% |

  So at `cell == 1` the claim holds exactly as written (identical at msaa
  0 and 2; one count on 0.09% of pixels at msaa 4 and 8, from the 8-bit
  round trip through `_plate_tex` and `_actor_tex`), and at `cell > 1` it
  does not hold at all, at any msaa level — the difference there is the
  feature, not an error term.
  `test_integration_on_still_resolves_msaa_into_the_same_texture` therefore
  renders on a plate upscaled to the target resolution, so that the msaa
  resolve is the only thing it is measuring. Its `<= 2` tolerance is
  driver headroom on sample weighting above the measured 1; tightening it
  to 1 is not the safe-looking edit it appears to be.
- **The composite's exactness claim is exact only at `a.a == 1.0`.** At
  full coverage (msaa 0, unblurred) `plate * (1 - a) + c * a` is `c`, with
  no arithmetic in between — that is the identity the golden tests pin. At
  fractional coverage the shader computes
  `clamp(rgb / a, 0, 1) * a` rather than `rgb`, because it unpremultiplies
  to tone-match and clamps before re-premultiplying. Measured
  exhaustively over every 8-bit `(rgb, a)` pair with `rgb <= a` (which is
  every pair the actor layer can produce, since the actor shader writes
  alpha 1 and a resolve is a convex average), in float32: the largest
  deviation is 3.0e-8, i.e. 7.6e-6 of a count, and **0 counts** after
  8-bit rounding. Well inside the 1/255 the plan allowed for; recorded
  because the clamp is a real branch, not because it costs anything.
- **`test_a_gathered_shadow_never_darkens_an_earlier_actor` gained an
  `integration` parameter and two assertions.** See "The default flip
  broke exactly one test" above. It is a repin plus new coverage, not a
  loosening: the original claim is unchanged and still asserted, at the
  `integration="off"` it always meant.
- **`TOE`, `SHOULDER` and `GAIN` were not changed by the fixture pass;
  `plate.grain_retention` was added instead.** The plan called all three
  constants tunables to be settled against the fixtures. They are left at
  their derived values (1.0, 1.0, `sqrt(12)`) because each follows from a
  stated requirement rather than from taste. What the fixture pass found
  was not a miscalibration of `GAIN` but a wrong *target*: `GAIN` converts
  a uniform hash to unit RMS correctly, and was then being asked to hit an
  amplitude measured on the source plate rather than on the plate as
  displayed. Moving `GAIN` would have fixed the symptom at one cell while
  silently contradicting the derivation its own comment states. The
  retention factor fixes the target instead, is derived rather than fitted,
  and is 1.0 wherever nothing is lost — so no existing test's numbers
  moved. See "The grain is matched to the plate as displayed, not as
  stored".

## Known limitations

- **The grain's amplitude now matches the room; its shape does not.**
  `grain_retention` lands the injected field at 5.04 counts per plate cell
  against the displayed plate's 5.05, but the field is a hard block across
  each cell while the plate's dither is a smooth bilinear ramp across the
  same cell. At the target-pixel scale the actor therefore still carries
  2.32 counts of 3x3 residual against the room's 1.40 — 1.66x, down from
  about 2.8x before the retention factor. Closing that would mean giving
  the grain the filter's own reconstruction shape rather than a per-cell
  constant, which is a larger change than this plan's scope; the term is
  now weak enough to read as dither rather than as damage, and erring weak
  is the deliberate direction.
- **`_grain` does not separate the plate's dither from its image content,
  so a busy plate reads as a grainy one.** Per 20x20 block of the attic
  plate the luma residual ranges from **1.74 to 18.72 counts** (median
  7.87), and from 0.00 to 9.64 (median 4.83) on the combat plate — a
  spread that is mostly *content*, not dither, and the whole-plate average
  is what every actor in the frame receives. Changing the estimator is a
  design change and is deliberately out of this plan's scope. The
  retention factor bounds how much damage it can do: whatever `_grain`
  over-reads, the actor now receives only the fraction of it the room
  itself still shows.
- Tone matching is global to the plate, not local to the pixels around
  the actor; grain is luma-only.
- `nearest` pixelates the actor, not its ground shadow, which stays at
  target resolution on the plate layer.
- Softening touches the actor's interior, not just its edge, by
  `sigma <= 0.35 * cell`.
- Cost: two resolves and one full-target composite per frame; `off` is the
  escape hatch, on the Graphics page.
- The software backend stays uncomposited.
- Under `integration="on"`, `shadows="hard"` casts run before the bodies
  rather than interleaved, so a nearer actor's hard silhouette can no
  longer paint over a farther body — a behaviour difference from `off`, in
  the same direction `soft` already went. Pinned by
  `test_a_gathered_shadow_never_darkens_an_earlier_actor`.
- The plate and actor layers quantise to 8 bits between the resolve and
  the composite, so at `msaa > 0` an antialiased edge can differ from
  `off` by 1/255 (measured: 1 count on 0.09% of pixels, at `cell == 1`
  where the two are otherwise identical).
- **With F, H and G all on, the attic frame at scale 8 is over the
  roadmap spec's 1.5x budget: 1.60x (ratio of means over 8 runs), with
  every individual run between 1.52x and 1.64x.** At scale 4 the same
  comparison is 1.27x, inside budget. `integration` alone is 1.12x at
  scale 4 and 1.17x at scale 8, so the composite is not the largest term —
  F's blur is. Nothing was retuned to close it. Both `Integration: Off`
  and `Shadows: Hard` are rows on the Graphics page, so a player on a
  slower machine has two escape hatches without leaving the game. See
  "Frame time".

## Manual attestation

| Check | Status |
|---|---|
| `attic-smooth-enhanced-nocomposite.png` is identical to the pre-change `attic-smooth-enhanced.png` | pending |
| **Does the composited actor look like it belongs in the room?** Compare `attic-smooth-enhanced.png` against its `-nocomposite` twin at 1:1, on Carnby's face and coat and on the lantern. The grain now sits at the room's own per-cell amplitude (5.04 counts against 5.05), but it is still a hard block where the room's is a smooth ramp, so it carries 1.66x the room's per-target-pixel residual. The reading from the crops was "dither, not damage"; a human at a window is the authority on whether that holds | pending |
| At scale 8 (`cell` 8, `sigma` 2.8) the same question again: the blocks are twice as wide and the softening twice as strong, and the retention factor is the same 0.59375 | pending |
| Under `--background-filter nearest` and `--background-filter xbr` (at 320x200), where `grain_retention` is 1.0 by derivation, the actor's grain still looks like the room's rather than stronger than it — the one place the retention model could be wrong in the loud direction | pending |
| Under `--background-filter nearest`, the actor is blocky on the same grid as the plate, and its ground shadow — which stays sharp on the plate layer — does not look wrong beside it | pending |
| Under `--background-filter xbr`, the actor's edge is crisper than under `bilinear` and still no crisper than the plate's | pending |
| An override plate at or above the target resolution (`cell <= 1`) composites as an identity: no softening, no pixelation | pending |
| Carnby's darks sit at the room's floor rather than at black, and a white highlight does not punch brighter than anything in the room | pending |
| Graphics page: `Integration: On / Off` is the ninth row; 9 rows plus Back, nothing clipped; every row cycles by mouse and keyboard | pending |
| Toggling Integration to Off in the menu changes the look live; Off looks as before | pending |
| `--integration on` at scale 8 in the floor-5 combat venue keeps a playable frame rate. Measured, not played: 15.5-16.6 ms/frame of pure render time on the attic fixture with F, H and G all on — see "Frame time", and note that this is the configuration that is over the spec's budget | pending |
| Under `--shadows hard --integration on`, no actor's shadow paints over a body in front of it, and that difference from `--integration off` looks like an improvement rather than a missing shadow | pending |
