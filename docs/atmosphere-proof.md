# Atmosphere proof

Date: 2026-09-01
Spec: `docs/superpowers/specs/2026-08-31-actor-realism-roadmap-2-design.md` (sub-project L)
Plan: `docs/superpowers/plans/2026-09-01-atmosphere.md`

**This document's "Manual attestation" table is a checklist for a human
with real game data and a real window; every row starts `pending`.**
Everything under "Automated gates", "The tunables", "Pixel evidence" and
"Frame time" was actually run, in this environment, on this branch, and
the output shown is the real output of that run. Sub-project L is the
last of roadmap 2's four, so "Frame time" also carries the roadmap's own
closing budget.

## What changed

**A linear eye-depth target rides alongside the actor layer.** Every
shader that writes the actor layer now writes a second output,
`v_view.z + focal1` — eye distance from the pinhole, this engine's actual
perspective divisor, not bare view `z` and not the depth attachment's
projective value. It lands in `_actor_depth_tex` (R16F), a second
*colour* attachment on the actor FBO, with `_ms_depth_color` as its
multisample twin so both resolve paths carry it. Being a colour
attachment is the point: an MSAA resolve averages it, so a
partially-covered silhouette pixel ends up holding the coverage-weighted
average of the depths that actually covered it — depth premultiplied by
coverage, exactly as colour is, and unpremultiplied by the same `a.a` on
the way out. The attachment is unconditional; it is allocated and written
whatever `atmosphere` says.

**Distance haze.** In the composite, `1 - exp(-HAZE_DENSITY *
max(0, depth - HAZE_START))` mixes each actor pixel toward `haze_tint`,
the room's own ambient tone — what an unlit surface in that room looks
like — rather than toward a picked fog colour. `max(0, ...)` means a
small room is untouched by construction, and `exp(-0)` is exactly 1, so
the term is exactly zero below the threshold rather than nearly zero.
`atmosphere="off"` sets `haze_density` to 0.0, which collapses it the
same exact way.

**Two depth grades.** `beyond = max(0, depth - HAZE_START) / HAZE_START`
drives a softness grade (`1 + SIGMA_DEPTH_SLOPE * beyond`, scaling the
composite blur's weight falloff) and a grain grade
(`1 + GRAIN_DEPTH_SLOPE * beyond`, scaling the dither the actor is given
to match the plate's). Both are read from the centre pixel's *own
unblurred* depth — grading from the blurred value would be circular,
since the blur's weights are what the grade sets. The softness grade
scales `inv_sigma2` and never `radius`, because the blur loop needs
`radius` uniform for uniform control flow; `atmosphere="off"` zeroes both
slopes.

All three terms live in `_composite`, so all three apply under
`lighting="scene"` and `integration > 0` only — at integration 0 there is
no composite to modify. `RenderOptions.atmosphere` defaults to `"on"` as
of this task; `--atmosphere off`, or the Realism page's Atmosphere row,
is the escape hatch.

`tools/prove_graphics.py` gained `--atmosphere` and a `-nohaze` twin pair.

## Automated gates

The atmosphere tests by name, plus the two golden identities the whole
feature has to leave alone:

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest \
    tests/test_render_gl.py::test_neutral_tunables_are_an_exact_identity \
    tests/test_render_gl.py::test_a_far_actor_moves_toward_the_ambient_tone_and_a_near_one_does_not \
    tests/test_render_gl.py::test_haze_starts_at_zero_before_haze_start \
    tests/test_render_gl.py::test_softness_and_grain_increase_with_depth \
    tests/test_render_gl.py::test_haze_unpremultiplies_depth_at_partially_covered_edges \
    tests/test_render_gl.py::test_zero_coverage_pixels_are_untouched \
    tests/test_render_gl.py::test_atmosphere_is_inert_at_integration_zero \
    tests/test_render_gl.py::test_integration_at_full_with_a_neutral_plate_reproduces_the_golden \
    tests/test_render_gl.py::test_classic_realism_matches_the_pre_materials_golden \
    tests/test_prove_graphics.py::test_the_nohaze_twin_differs_from_the_default \
    tests/test_render_options.py::test_atmosphere_defaults_on_and_cycles \
    -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.1.1, pluggy-1.6.0 -- /Users/felipe.dos.santos/code/mine/m-aitd/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /Users/felipe.dos.santos/code/mine/m-aitd
configfile: pyproject.toml
plugins: anyio-4.14.2
collecting ... collected 11 items

tests/test_render_gl.py::test_neutral_tunables_are_an_exact_identity PASSED [  9%]
tests/test_render_gl.py::test_a_far_actor_moves_toward_the_ambient_tone_and_a_near_one_does_not PASSED [ 18%]
tests/test_render_gl.py::test_haze_starts_at_zero_before_haze_start PASSED [ 27%]
tests/test_render_gl.py::test_softness_and_grain_increase_with_depth PASSED [ 36%]
tests/test_render_gl.py::test_haze_unpremultiplies_depth_at_partially_covered_edges PASSED [ 45%]
tests/test_render_gl.py::test_zero_coverage_pixels_are_untouched PASSED  [ 54%]
tests/test_render_gl.py::test_atmosphere_is_inert_at_integration_zero PASSED [ 63%]
tests/test_render_gl.py::test_integration_at_full_with_a_neutral_plate_reproduces_the_golden PASSED [ 72%]
tests/test_render_gl.py::test_classic_realism_matches_the_pre_materials_golden PASSED [ 81%]
tests/test_prove_graphics.py::test_the_nohaze_twin_differs_from_the_default PASSED [ 90%]
tests/test_render_options.py::test_atmosphere_defaults_on_and_cycles PASSED [100%]

============================== 11 passed in 1.74s ==============================
```

**`test_neutral_tunables_are_an_exact_identity` is the claim the rest
rests on.** With `atmosphere="on"` and all three tunables monkeypatched
to zero, the frame is byte-identical to `atmosphere="off"`: every term is
built so that k=0 collapses it exactly, not nearly. That alone would
still pass with the whole feature deleted — the "off" branch zeroes the
same three uniforms — so the test's second half renders the same frame at
the *real* tunables and asserts "on" now differs from "off". Both halves
in one test, because either alone is a trap.

The full gate:

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
........................................................................ [  4%]
........................................................................ [  8%]
........x............................................................... [ 13%]
................s....................................................... [ 17%]
........................................................................ [ 21%]
........................................................................ [ 26%]
........................................................................ [ 30%]
........................................................................ [ 35%]
........................................................................ [ 39%]
........................................................................ [ 43%]
........................................................................ [ 48%]
........................................................................ [ 52%]
........................................................................ [ 57%]
........................................................................ [ 61%]
........................................................................ [ 65%]
........................................................................ [ 70%]
........................................................................ [ 74%]
........................................................................ [ 79%]
........................................................................ [ 83%]
........................................................................ [ 87%]
........................................................................ [ 92%]
........................................................................ [ 96%]
.......................................................                  [100%]
1637 passed, 1 skipped, 1 xfailed, 26 warnings in 67.12s (0:01:07)
```

This is 2 above the branch's last recorded green (1635): this task adds
`tests/test_prove_graphics.py::test_the_nohaze_twin_differs_from_the_default`
and `::test_parse_args_atmosphere_defaults_to_the_render_default`. No
skip, xfail or warning count moved.

### What the default flip broke, and what it did not

Flipping `RenderOptions.atmosphere` from `"off"` to `"on"` as a single
one-line change, with nothing else touched, failed 12 tests:

```
FAILED tests/test_config.py::test_save_writes_schema_2_with_render
FAILED tests/test_main.py::test_the_atmosphere_flag_overrides_only_its_own_field
FAILED tests/test_render_gl.py::test_flat_triangle_lands_where_the_logical_projection_says
FAILED tests/test_render_gl.py::test_painter_order_across_actors_ignores_depth
FAILED tests/test_render_gl.py::test_stencil_mask_erases_only_the_flagged_actor
FAILED tests/test_render_gl.py::test_stencil_mask_erases_only_the_covered_region
FAILED tests/test_render_gl.py::test_actors_and_mask_render_correctly_above_scale_one
FAILED tests/test_render_gl.py::test_sphere_and_line_and_point_render
FAILED tests/test_render_gl.py::test_integration_at_full_with_a_neutral_plate_reproduces_the_golden
FAILED tests/test_render_options.py::test_atmosphere_defaults_off_and_cycles
FAILED tests/test_render_options.py::test_atmosphere_is_last_so_positional_construction_still_works
FAILED tests/test_render_options.py::test_invalid_or_missing_atmosphere_falls_back_alone
12 failed, 1623 passed, 1 skipped, 1 xfailed, 26 warnings in 64.64s
```

Four of those are option-default bookkeeping (`test_config`,
`test_main`, and the two `test_render_options` default assertions), and
one is `test_render_options`'s positional-construction pin. The
interesting group is the seven `test_render_gl` failures.

`test_integration_at_full_with_a_neutral_plate_reproduces_the_golden` is
the one that matters, and it is a repeat offence. That test carries a
comment recording sub-project K's C1 defect verbatim: it had to be given
an explicit `occlusion="off"` after a final review found it was passing
only because a defaulted-on feature happened to be inert. One
sub-project later, the same test, the same trap — it did not name
`atmosphere`, and the moment the knob defaulted on, `_golden_frame`'s
actors started to haze and the golden stopped matching. It now names
`atmosphere="off"` too. (Its sibling
`test_classic_realism_matches_the_pre_materials_golden` never failed:
`integration=0` there, so the composite never runs. It names
`atmosphere="off"` anyway, so that its "names every roadmap-2 field the
identity holds at" comment is true again.)

The other six were the *feature working*: exact-primary-colour geometry
and masking tests whose synthetic actors sit past the `HAZE_START` of
1600 Task 3 had settled on, so `(255, 0, 0)` arrived as `(240, ?, 18)`.
Five of the six stopped failing once "The tunables" below moved
`HAZE_START` to 2500, which puts their eye depth of 2000 genuinely
inside the untouched near field. The sixth,
`test_painter_order_across_actors_ignores_depth`, has a deliberately far
triangle (eye depth 4000) and now names `atmosphere="off"`, for the same
reason the golden test does: draw order is what it is about.

## The tunables

There are four, all in `render/plate.py` beside the composite's own
toe/shoulder/grain constants.

| Constant | Plan's value | Shipped | What moved it |
|---|---|---|---|
| `HAZE_DENSITY` | 0.00035 | **0.000012** | Measured fixture depths (below) |
| `HAZE_START` | 900.0 (plan) → 1600.0 (Task 3) | **2500.0** | Measured fixture depths (below) |
| `SIGMA_DEPTH_SLOPE` | 0.25 | **0.03** | Rescaled with `HAZE_START` |
| `GRAIN_DEPTH_SLOPE` | 0.35 | **0.04** | Rescaled with `HAZE_START` |

**None of the plan's four starting values survived, and the story is
worth telling in full, because the same mistake was made twice at two
different scales.**

The plan's `HAZE_START = 900.0` was reasoned in the camera-plane
convention — a threshold on bare view `z`. But the depth the composite
actually reads is `v_view.z + focal1`, eye distance from the pinhole, so
the smallest depth a camera can normally report is `focal1` itself. At
this suite's synthetic camera (`focal1 = 1000`) 900 is below *every*
depth the engine can produce, which would have hazed every pixel
unconditionally and made the planned "a small room is untouched" test
unwritable. Task 3 caught that and recalibrated to 1600 against the test
suite's own frames — near actor at eye depth 1500, far at 2400.

Task 4 then measured the two *real* proof fixtures, reading the actor
layer's depth attachment back directly, and found that the test suite's
scale is nothing like the game's:

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python scratch_depths.py
--- attic: camera focal1=1431 focal2=229 focal3=191
  scale=1 covered=4015 px  depth min=1431.0 p05=1518.0 median=4780.0 p95=11848.0 max=12792.0
    beyond 900.0: 4015 px (100.0%)
    beyond 1600.0: 3273 px (81.5%)
  scale=4 covered=64604 px  depth min=1431.0 p05=1519.0 median=4780.0 p95=11848.0 max=12840.0
    beyond 900.0: 64604 px (100.0%)
    beyond 1600.0: 52713 px (81.6%)
--- combat: camera focal1=141 focal2=273 focal3=228
  scale=1 covered=212 px  depth min=22128.0 p05=22321.6 median=24912.0 p95=28656.0 max=29008.0
    beyond 900.0: 212 px (100.0%)
    beyond 1600.0: 212 px (100.0%)
  scale=4 covered=3429 px  depth min=22128.0 p05=22288.0 median=24352.0 p95=28825.6 max=29488.0
    beyond 900.0: 3429 px (100.0%)
    beyond 1600.0: 3429 px (100.0%)
```

Per actor, so the near/far spread inside one room is visible:

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python scratch_depths2.py
--- attic: camera pos=(4550,-1490,-4230) focal1=1431 actors=10
   actor 7: pos=(-5600, 3000, 2000) verts=141 eye-depth min=11088 mean=11876 max=12505
   actor 6: pos=(-5855, 5, 2475) verts=14 eye-depth min=10544 mean=11234 max=11790
   actor 12: pos=(0, 0, 10000) verts=114 eye-depth min=14714 mean=15366 max=16021
   actor 3: pos=(-2840, 0, 4540) verts=65 eye-depth min=11084 mean=12080 max=12895
   actor 0: pos=(-5513, 0, -395) verts=65 eye-depth min=8228 mean=9022 max=9832
   actor 5: pos=(0, -1400, 5000) verts=25 eye-depth min=10626 mean=11180 max=11636
   actor 8: pos=(1000, 0, 0) verts=81 eye-depth min=6570 mean=6832 max=7073
   actor 4: pos=(5740, 0, 569) verts=98 eye-depth min=5038 mean=5391 max=5785
   actor 1: pos=(3231, 0, -1548) verts=150 eye-depth min=4141 mean=4453 max=4933
   actor 10: pos=(3800, -800, -4600) verts=161 eye-depth min=1503 mean=1600 max=1728
```

And `focal1` — the floor under any depth a camera can report — across
every camera of every floor:

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python scratch_focal.py
floor 0: 5 cameras  focal1 min=300 median=701 max=1431
floor 1: 15 cameras  focal1 min=51 median=191 max=2460
floor 2: 39 cameras  focal1 min=40 median=81 max=1280
floor 3: 25 cameras  focal1 min=81 median=101 max=131
floor 4: 5 cameras  focal1 min=60 median=101 max=251
floor 5: 34 cameras  focal1 min=71 median=101 max=2850
floor 6: 14 cameras  focal1 min=91 median=106 max=1280
floor 7: 7 cameras  focal1 min=101 median=101 max=1280
ALL: n=144 min=40 median=101 p95=1218 max=2850
```

So a room in this game is tens of thousands of world units deep from the
camera's eye, not the "few thousand" the plan (and `plate.py`'s own
header comment, now corrected) assumed. What the plan's constants do at
those depths, against what the shipped ones do:

```
$ .venv/bin/python scratch_tune.py
=== the plan's values (shipped by Task 3): HAZE_START=1600.0 HAZE_DENSITY=0.00035 SIGMA_DEPTH_SLOPE=0.25 GRAIN_DEPTH_SLOPE=0.35
depth sample                     depth     haze  sigma x  grain x
attic near actor 10 (mean)        1600    0.000    1.000    1.000
attic p05                         1518    0.000    1.000    1.000
attic median                      4780    0.671    1.497    1.696
attic p95                        11848    0.972    2.601    3.242
attic far actor 12 (mean)        15366    0.992    3.151    4.011
attic max                        12792    0.980    2.749    3.448
combat min                       22128    0.999    4.207    5.490
combat median                    24912    1.000    4.643    6.099
combat max                       29488    1.000    5.357    7.100

=== candidate: HAZE_START=2500.0 HAZE_DENSITY=1.2e-05 SIGMA_DEPTH_SLOPE=0.03 GRAIN_DEPTH_SLOPE=0.04
depth sample                     depth     haze  sigma x  grain x
attic near actor 10 (mean)        1600    0.000    1.000    1.000
attic p05                         1518    0.000    1.000    1.000
attic median                      4780    0.027    1.027    1.036
attic p95                        11848    0.106    1.112    1.150
attic far actor 12 (mean)        15366    0.143    1.154    1.206
attic max                        12792    0.116    1.124    1.165
combat min                       22128    0.210    1.236    1.314
combat median                    24912    0.236    1.269    1.359
combat max                       29488    0.277    1.324    1.432
```

At the plan's values the *median* attic actor pixel is 67% of the way to
flat ambient tone with 1.7x grain, and **every single covered pixel in the
combat fixture is at haze 1.000** — the entire visible cast rendered as
featureless ambient colour, with up to 7x grain on top. That is precisely
the "far actors read as washed out" failure the manual attestation table
below exists to catch, and it would have shipped on by default. At the
values now in `plate.py`, the attic's farthest actor reaches 0.14 and the
deepest pixel in either fixture reaches 0.28, while the nearest actor in
each fixture is at exactly 0.

`HAZE_START = 2500` was chosen to sit above the attic's nearest actor
(eye depth 1503-1728) with margin and below everything else measured. It
does *not* clear every camera's `focal1`: the one camera at `focal1 =
2850` reports a minimum depth above the threshold, which is a haze of
0.004 at the camera plane — continuous, not a pop, since `exp(-0) = 1`
makes the term exactly 0 at the threshold and it grows smoothly from
there.

`SIGMA_DEPTH_SLOPE` and `GRAIN_DEPTH_SLOPE` both multiply
`beyond = max(0, depth - HAZE_START) / HAZE_START`, so they are
denominated in `HAZE_START` and had to be rescaled with it. This coupling
is now recorded in `plate.py` and in `AGENTS.md`.

Two test fixtures had to move with the constants, and both moves are
recorded in their own docstrings. `_near_and_far_frame`'s far actor sat
at eye depth 2400, which at the recalibrated density is a 0.5% haze —
under one 8-bit count. Left there, `test_neutral_tunables_are_an_exact_identity`'s
second half and `test_a_far_actor_moves_toward_the_ambient_tone_and_a_near_one_does_not`
would both have quietly become inert. It now sits at 15000, the attic's
own far actor. `_far_flat_actor_frame` moved the same way, from 2500 to
15000 — with a lengthened lens (`focal2 = focal3 = 3200`) rather than a
scaled-up triangle, because the enhanced material's detail field is
world-space and a 6x larger triangle alone moved that test's measured
edge-vs-interior gap from 0.3 counts to 20, past its own 6.0 threshold,
with no bug present.

Both moves were mutation-checked. With `d / a.a` in `COMPOSITE_FSH`
mutated to bare `d`, `test_haze_unpremultiplies_depth_at_partially_covered_edges`
is still the only test in the file that fails (`1 failed, 147 passed`),
which is the same unique-catch property Task 3 recorded for it. Zeroing
each tunable in turn in `render_gl.py` fails a named test each time:
`HAZE_DENSITY` fails `test_neutral_tunables_are_an_exact_identity` and
`test_a_far_actor_moves_toward_the_ambient_tone_and_a_near_one_does_not`;
`SIGMA_DEPTH_SLOPE` and `GRAIN_DEPTH_SLOPE` each fail
`test_softness_and_grain_increase_with_depth`.

## Pixel evidence

`make proof-graphics` (default scale 4) wrote all 30 PNGs, including the
new `-nohaze` pair:

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python \
    tools/prove_graphics.py "data/aitd1/.../INDARK"
...
docs/graphics-proof/attic-smooth-enhanced-roomshadow.png
docs/graphics-proof/combat-smooth-enhanced-roomshadow.png
docs/graphics-proof/attic-smooth-enhanced-nohaze.png
docs/graphics-proof/combat-smooth-enhanced-nohaze.png
```

Diffing the twin against the plain `-smooth-enhanced` render on both
fixtures:

```
$ .venv/bin/python -c "
import pygame, numpy as np
for fixture in ('attic', 'combat'):
    a = pygame.surfarray.array3d(pygame.image.load(f'docs/graphics-proof/{fixture}-smooth-enhanced.png'))
    b = pygame.surfarray.array3d(pygame.image.load(f'docs/graphics-proof/{fixture}-smooth-enhanced-nohaze.png'))
    diff = np.abs(a.astype(int) - b.astype(int))
    npix = (diff.max(axis=2) > 0).sum()
    print('nohaze', fixture, 'equal?', np.array_equal(a, b), 'pixels differing:', npix, '/', a.shape[0]*a.shape[1], 'max abs diff', diff.max(), 'mean abs diff', diff.mean())
"
nohaze attic equal? False pixels differing: 48914 / 1024000 max abs diff 10 mean abs diff 0.0494384765625
nohaze combat equal? False pixels differing: 4152 / 1024000 max abs diff 15 mean abs diff 0.0132353515625
```

The twin differs on **both** fixtures, which the task brief did not take
for granted — the attic is nominally the small-room case the haze is
built to leave alone. Measured, it is not: the attic's camera has
`focal1 = 1431` and its ten actors spread from eye depth 1503 to 16021,
so most of its cast is past `HAZE_START` and only its nearest actor is
genuinely untouched. 48,914 pixels move on the attic (4.8% of the frame,
which is about three quarters of its 64,604 covered actor pixels), by at
most 10 counts. The combat venue moves fewer pixels (its whole cast is
small on screen) but harder — at most 15 counts, mean 4.8 over the pixels
that move — because its entire visible cast sits at eye depth
22,128-29,488.

**The effect is genuinely subtle in absolute terms: a maximum of 10
counts on the attic.** That is a deliberate choice over the alternative
documented above, and it is the single thing most worth a human's eye
below. The constant to turn is `HAZE_DENSITY`, and "The tunables" gives
the haze fraction at every fixture depth for two settings of it.

The near-versus-far measurement
`test_a_far_actor_moves_toward_the_ambient_tone_and_a_near_one_does_not`
asserts on, reproduced directly:

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python scratch_pixels.py
near actor (eye depth 1500, under HAZE_START): mean |on-off| = 0.0000 counts over 903 px
far  actor (eye depth 15000):                  mean |on-off| = 12.8053 counts over 351 px
far actor's mean distance from the ambient tone: 91.44 -> 78.64 counts
```

The near actor moves by **exactly zero** counts across 903 pixels — the
"a small room is untouched" guarantee, measured rather than argued. The
far actor moves 12.8 counts on average, and moves *toward* the ambient
tone: its mean distance from it falls from 91.44 to 78.64.

## Frame time

Attic fixture, scale 4, msaa 4, smoothing 2. One frame is `build_frame`
(CPU; where sub-project I's motion interpolation lives) plus
`backend.draw` and `ctx.finish()` (GPU; where J, K and L live).
`ctx.finish()` rather than `read_rgb()`: both drain the GPU before the
clock is read, but `read_rgb` also drags 1280x800x3 bytes back over the
bus — a fixed ~5 ms the real game never pays, since it presents the frame
— which would dilute every ratio toward 1. The two configurations are
interleaved A/B/A/B inside one loop rather than measured in separate
loops, so clock and thermal drift land on both sides.

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python scratch_frametime.py
--- L alone: the atmosphere knob, everything else at its shipping default (n=64 interleaved, attic, scale 4, msaa 4, smoothing 2)
  atmosphere=off                                     cpu   3.41  gpu   8.24  frame  11.66 ms  (median  11.26, min   9.95)
  atmosphere=on (the new default)                    cpu   3.38  gpu   8.45  frame  11.83 ms  (median  11.29, min  10.19)
  ratio b/a = 1.015 whole frame, 1.025 GPU only

--- roadmap 2: I + J + K + L all off versus all on (n=64 interleaved, attic, scale 4, msaa 4, smoothing 2)
  I tick, J unpainted, K occlusion=off, L atmosphere=off cpu   3.46  gpu   8.30  frame  11.76 ms  (median  11.39, min  10.37)
  I smooth, J painted, K ssao, L atmosphere=on       cpu   3.74  gpu   8.53  frame  12.27 ms  (median  11.73, min  10.46)
  ratio b/a = 1.044 whole frame, 1.028 GPU only   budget <= 1.5: MET
```

A second back-to-back run of the same script, unmodified, on this shared
and noisy machine:

```
  ratio b/a = 1.013 whole frame, 1.025 GPU only
  ratio b/a = 1.043 whole frame, 1.027 GPU only   budget <= 1.5: MET
```

**The roadmap's closing budget is met: 1.044x (1.043x on the repeat)
against a 1.5x ceiling.** This is the number the spec asked for at
`docs/superpowers/specs/2026-08-31-actor-realism-roadmap-2-design.md:375-378`,
and sub-project L is the last of the four, so this is the first and only
point at which it could be measured.

Three caveats on that number, all of which cut against it:

1. **Sub-project J has no runtime knob.** Actor textures are data-gated
   on whether a body paint exists, and this repo ships none, so J is off
   on both sides of any ratio built from `RenderOptions` alone. The "on"
   side above therefore renders through the proof tool's synthetic
   checker atlas (`painted=True`, the same one the `-painted` twin uses)
   against `painted=False` on the "off" side. Without that, the headline
   would be a three-sub-project ratio reported as a four.
2. **The depth target is unconditional, so the "off" side already pays
   for part of L.** `atmosphere="off"` still allocates and writes
   `_actor_depth_tex` (and `_ms_depth_color`) every frame; only the
   composite's arithmetic is switched off. This was reviewed and accepted
   in Task 2 — gating it would mean rebuilding framebuffers on an option
   change — but it means the 1.044x above **understates** L's true cost
   against a pre-roadmap baseline that had no second colour attachment at
   all. The honest statement is that the *switchable* part of all four
   sub-projects costs 4.4%, not that all four cost 4.4%.
3. **The attic is a small-actor fixture.** Its ten actors cover 64,604
   of 1,024,000 pixels at scale 4 (6.3%), and every one of roadmap 2's
   GPU-side features acts on the actor layer only. Most of this frame's
   GPU time is the background upscale and the full-screen composite,
   neither of which any of the four touches. A fixture with actors
   filling the frame would show a larger ratio; the spec named this
   fixture, so this is the number the spec asked for, but it is not a
   worst case.

## Manual attestation

| Check | Result |
|---|---|
| Far actors read as further away rather than as washed out | pending |
| The haze is invisible in a small room | pending |
| Grain and softness change with depth without the near actor looking touched | pending |
| Nothing crawls as an actor walks toward the camera | pending |
| The effect is strong enough to be worth having at all (max 10 counts on the attic — see "Pixel evidence") | pending |

## Known limitations

- **Haze and the two grades are tuned by eye, and no eye has seen them
  yet.** The four constants were settled here against *measured* fixture
  depths, which is a real improvement on the plan's reasoning-from-scale,
  but "how much haze looks right" is not a measurable quantity. The
  numbers in "The tunables" are chosen to be conservative — the near
  actor exactly untouched, the deepest pixel in either fixture at 0.28 —
  on the argument that too little is recoverable by turning one constant
  and too much shipped by default is not. The last row of the attestation
  table is the one that closes this.
- **The depth grade softens within the existing radius and can never
  sharpen past it.** `radius` stays a uniform because the composite's
  blur loop depends on uniform control flow; only the weight falloff
  (`inv_sigma2`) is graded. A far actor can be made blurrier up to the
  radius the plate's own softness already set, and a near actor can never
  be made crisper than that radius allows.
- **The two grades interfere, and that is a property of the look, not a
  measurement artifact.** `test_softness_and_grain_increase_with_depth`
  has to isolate the two slopes into separate renders because, graded
  together, the far actor's added grain measurably swamps the blur's
  reduction of local variance. On the fixtures the two are always graded
  together, so what a human sees at depth is the sum of a softer edge and
  a noisier interior, not either alone.
- **R16F holds integers exactly only to 2048, and the game is well past
  that.** Measured spacing at the fixtures' own depths: 4 units at the
  attic's median (4780), 8 at its far actor (15366, which stores as
  15368), and 16 across the whole combat fixture (22128-29488). The
  plan's limitations section claimed the game's rooms are "far smaller"
  than the 2048 knee; they are not, in either fixture. In practice this
  is harmless — a 16-unit quantisation feeds a haze that changes by
  about 0.0001 over that distance — but it is a real quantisation, and the fix
  if one is ever needed is an R32F target. The overflow ceiling is not
  reachable: `float16` goes infinite above 65504, and the projection's
  `FAR` is 40960, so with the largest `focal1` in the game (2850) the
  greatest depth any pixel can report is about 43810. `0.0 * Inf = NaN`
  would break the coverage-premultiply identity if it ever were reached.
- **"The minimum depth is exactly `focal1`" is true of every realistic
  gameplay camera and enforced by nothing.** An actor placed at world
  z = -800 in front of a `focal1 = 1000` camera renders happily, with a
  reported depth of 200:

  ```
  $ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python scratch_near.py
  world z=     500 (focal1 1000 -> nominal depth 1500): covered    861 px, reported depth min 1500 max 1500
  world z=       0 (focal1 1000 -> nominal depth 1000): covered   2016 px, reported depth min 1000 max 1000
  world z=    -800 (focal1 1000 -> nominal depth  200): covered  31900 px, reported depth min 200 max 200
  ```

  The render path does not clip against a near plane that would enforce
  the `focal1` floor. Nothing in the game puts an actor there, and the
  consequence would only ever be *less* haze, but any future reasoning
  that treats `focal1` as a hard lower bound on depth is reasoning about
  a guarantee this code does not make.
- **The composite's `if (a.a > 0.0)` coverage gate is untested.**
  Replacing it with `if (true)` leaves the entire suite green
  (`1637 passed, 1 skipped, 1 xfailed`). This is pre-existing — the gate
  predates this plan and was not introduced by it — and it is benign in
  practice, since at `a.a == 0` the final line
  `plate * (1 - a.a) + c * a.a` multiplies whatever `c` holds by zero.
  It is recorded because a future change that makes `c` non-finite at
  zero coverage (an unguarded divide, an `Inf` depth) would turn a
  currently-untested guard into the only thing preventing NaN pixels.
- **No depth of field.** Decision 9 of the spec rules it out, and it is
  honoured here by omission: the depth grade scales an existing plate-
  matching blur mildly with distance, which is not a focus model and is
  not meant to read as one.
- **The software backend stays flat, unlit, untextured, tick-stepped,
  uncomposited and unatmospheric.** `atmosphere` lives entirely in the GL
  composite pass; the fallback backend has no composite to modify.

The scratch scripts these measurements were taken with
(`scratch_depths.py`, `scratch_depths2.py`, `scratch_focal.py`,
`scratch_tune.py`, `scratch_pixels.py`, `scratch_frametime.py`,
`scratch_near.py`) are not part of the shipped repo; `.gitignore` covers
`scratch_*.py` for exactly this convention.
