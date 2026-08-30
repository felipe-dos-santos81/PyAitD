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
  residual against its own 3x3 box mean. The composite adds
  `grain * (hash(floor(gl_FragCoord.xy / cell)) - 0.5) * GAIN`, hashed on
  the screen cell alone so it sits still like the plate's dither rather
  than crawling between frames.
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
RMS equal the `grain` that `estimate_plate` measured off the plate. None of
the three was changed by the fixture pass; the fixture pass did, however,
produce a measurement that questions what `grain` is being matched *to* —
see "Known limitations", first row, which is the most important row in this
document.

One non-obvious guard is worth naming here because it is easy to delete by
accident: `render_gl._composite` divides every fragment by `cell`, so a
`cell` of 0 would give `floor(inf)` and a NaN grain seed, and `0.0 * NaN`
is NaN, not 0 — the `a.a > 0.0` branch would not contain it. `cell` can
never be 0 only because `plate.softness` computes
`cell = target_w / src_w if src_w > 0.0 else 1.0`. That `else 1.0` is
load-bearing, not defensive noise.

## Automated gates

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_plate.py tests/test_render_gl.py tests/test_render_options.py tests/test_layering.py tests/test_ui_reducers.py tests/test_ui_render.py tests/test_prove_graphics.py tests/test_config.py tests/test_main.py -q
330 passed, 2 warnings in 10.86s
```

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest -q
1475 passed, 2 skipped, 1 xfailed, 26 warnings in 55.29s
```

The two skips and the xfail are the suite's standing ones, unrelated to
this change; the baseline before the default flip was 1474 passed, 2
skipped, 1 xfailed, 26 warnings. The one test the flip added is
`tests/test_prove_graphics.py::test_the_default_composites_and_nocomposite_does_not`.

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
| attic | 76,124 of 1,024,000 (7.43%) | x 36-1279, y 117-738 | 115 | 10.32 |
| combat | 4,937 of 1,024,000 (0.48%) | x 399-655, y 261-292 | 59 | 8.59 |

The attic frame draws 10 actors, covering 88,589 pixels. Of the 76,124
that the composite moves, 68,267 are pixels a body was drawn on and 7,857
are not: the softening Gaussian (sigma 1.4, radius 3) carries the actor
layer's coverage up to three pixels past each silhouette, which is exactly
what matching the plate's edge width means and is the only way a
composited pixel lands where no body was. Beyond that band the plate is
untouched, which is what the "over" formula promises. The combat fixture
has only the one plank actor visible from its camera, which is why its
bounding box is a 257x32 band.

Read as pictures rather than as counts, cropping the attic pair around
Carnby's head and shoulders at 3x: `-nocomposite` gives a crisp,
high-contrast figure that plainly sits *in front of* the room rather than
in it. The composited render is visibly softer — the edge ramp matches the
bilinear plate's, the face's darks are lifted toward the room's warm floor,
and the figure stops looking cut out. That much is the feature working.

**But at full grain the same crop is also visibly noisier than the room it
is standing in**, in hard `cell`-sized blocks. Rendering the same frame
three ways — `off`, `on` with the plate's `grain` forced to 0, and `on` as
shipped — the middle one is the one that looks like an actor standing in a
room; the third looks like an actor standing in a room while being dithered
by a different, coarser process than the one that dithered the room. The
numbers behind that reading are in the first row of "Known limitations",
and the corresponding attestation row is the one to check first.

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
- **`TOE`, `SHOULDER` and `GAIN` were not changed by the fixture pass.**
  The plan called all three tunables to be settled against the fixtures.
  They were left at their derived values (1.0, 1.0, `sqrt(12)`) because
  each follows from a stated requirement rather than from taste, and the
  fixture pass found no reason to move `TOE` or `SHOULDER`. It did find a
  reason to question `GAIN` — or rather, to question the amplitude `GAIN`
  is asked to hit — which is written up as a limitation and an attestation
  row rather than acted on unilaterally, since it is a change to the model
  task 5 shipped and tested, not a calibration within it.

## Known limitations

- **The grain matches the plate at its own 320x200 resolution, not the
  plate as the viewer actually sees it, and the difference is visible.**
  `estimate_plate` measures the dither on the source image; the composite
  injects that amplitude as one constant per plate cell. But the plate
  reaches the screen through `background_filter`, which smooths it.
  Measured on the attic plate at scale 4:

  | | luma residual RMS |
  |---|---|
  | source plate, 320x200, against its own 3x3 mean (what `grain` is) | 8.48 counts |
  | the same plate as displayed, per plate cell after the bilinear upscale | 5.05 counts |
  | the same plate as displayed, per target pixel | 1.40 counts |
  | what the composite injects, per plate cell, by construction | 8.48 counts |

  So the actor gets 1.68x the per-cell amplitude the room around it has,
  and it gets it as *hard 4x4 blocks* where the displayed plate has smooth
  bilinear ramps — about 6x the room's per-target-pixel amplitude. The
  actor ends up noisier than the room it is being joined to, which is the
  opposite of what the feature is for. A second contribution points the
  same way: `_grain`'s residual-against-3x3-mean does not separate dither
  from image detail, so a busy plate reads as a grainy one. Per 20x20
  block of the attic plate the residual ranges from 1.74 to 18.72 counts
  (median 7.87), and from 0.00 to 9.64 (median 4.83) on the combat plate —
  a spread that is mostly *content*, not dither, and the whole-plate
  average is what every actor in the frame receives. **This is the one
  finding in this document that could warrant a code change rather than a
  note**; it was deliberately not acted on here, because the fix is a
  change to the model (attenuate `grain` by the filter's magnification,
  or estimate it on the plate as composited) rather than a calibration of
  `GAIN`, and it belongs to whoever owns that model. The first two
  attestation rows put the question to a human at a window.
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
  scale 4 and 1.17x at scale 8. See "Frame time".

## Manual attestation

| Check | Status |
|---|---|
| `attic-smooth-enhanced-nocomposite.png` is identical to the pre-change `attic-smooth-enhanced.png` | pending |
| **Does the composited actor look like it belongs in the room, or does it look noisier than the room?** Compare `attic-smooth-enhanced.png` against its `-nocomposite` twin at 1:1, on Carnby's face and coat and on the lantern. The measurement in the first "Known limitations" row predicts the actor carries 1.68x the room's per-cell dither in hard 4x4 blocks. If that reads as wrong at a real window, the grain model needs the change that row describes | pending |
| At scale 8 (`cell` 8, `sigma` 2.8) the same question again: the blocks are twice as wide and the softening twice as strong | pending |
| Under `--background-filter nearest`, the actor is blocky on the same grid as the plate, and its ground shadow — which stays sharp on the plate layer — does not look wrong beside it | pending |
| Under `--background-filter xbr`, the actor's edge is crisper than under `bilinear` and still no crisper than the plate's | pending |
| An override plate at or above the target resolution (`cell <= 1`) composites as an identity: no softening, no pixelation | pending |
| Carnby's darks sit at the room's floor rather than at black, and a white highlight does not punch brighter than anything in the room | pending |
| Graphics page: `Integration: On / Off` is the ninth row; 9 rows plus Back, nothing clipped; every row cycles by mouse and keyboard | pending |
| Toggling Integration to Off in the menu changes the look live; Off looks as before | pending |
| `--integration on` at scale 8 in the floor-5 combat venue keeps a playable frame rate. Measured, not played: 15.5-16.6 ms/frame of pure render time on the attic fixture with F, H and G all on — see "Frame time", and note that this is the configuration that is over the spec's budget | pending |
| Under `--shadows hard --integration on`, no actor's shadow paints over a body in front of it, and that difference from `--integration off` looks like an improvement rather than a missing shadow | pending |
