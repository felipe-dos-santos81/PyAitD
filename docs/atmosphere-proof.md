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
| `HAZE_DENSITY` | 0.00035 | **0.000035** | Measured fixture depths (below), then measured pixel deltas (review round 1) |
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
attic max (deepest visible)      12840    0.980    2.756    3.459
attic actor 12, off-camera       15366    0.992    3.151    4.011
combat min                       22128    0.999    4.207    5.490
combat median                    24912    1.000    4.643    6.099
combat max                       29488    1.000    5.357    7.100

=== Task 4 first pass (superseded): HAZE_START=2500.0 HAZE_DENSITY=1.2e-05 SIGMA_DEPTH_SLOPE=0.03 GRAIN_DEPTH_SLOPE=0.04
depth sample                     depth     haze  sigma x  grain x
attic near actor 10 (mean)        1600    0.000    1.000    1.000
attic p05                         1518    0.000    1.000    1.000
attic median                      4780    0.027    1.027    1.036
attic p95                        11848    0.106    1.112    1.150
attic max (deepest visible)      12840    0.117    1.124    1.165
attic actor 12, off-camera       15366    0.143    1.154    1.206
combat min                       22128    0.210    1.236    1.314
combat median                    24912    0.236    1.269    1.359
combat max                       29488    0.277    1.324    1.432

=== shipped: HAZE_START=2500.0 HAZE_DENSITY=3.5e-05 SIGMA_DEPTH_SLOPE=0.03 GRAIN_DEPTH_SLOPE=0.04
depth sample                     depth     haze  sigma x  grain x
attic near actor 10 (mean)        1600    0.000    1.000    1.000
attic p05                         1518    0.000    1.000    1.000
attic median                      4780    0.077    1.027    1.036
attic p95                        11848    0.279    1.112    1.150
attic max (deepest visible)      12840    0.304    1.124    1.165
attic actor 12, off-camera       15366    0.363    1.154    1.206
combat min                       22128    0.497    1.236    1.314
combat median                    24912    0.544    1.269    1.359
combat max                       29488    0.611    1.324    1.432
```

**All three settings are kept side by side on purpose.** The pending
manual attestation can move this either way — up toward the plan's
saturation or back down toward the first pass — without anyone
re-measuring anything. `HAZE_DENSITY` is the only constant to turn;
`HAZE_START` and the two slopes are settled.

`attic max (deepest visible)` is the depth of the deepest pixel the
attic frame actually *renders* (12840 at scale 4). The row below it,
actor 12 at 15366, is the frame's farthest actor by position but it is
**not covered in the rendered image** — it is listed because the
per-actor survey names it, not as evidence a reader can see. Where this
document quotes one number for "the attic's far end", it quotes the
visible 12840 / 0.304.

At the plan's values the *median* attic actor pixel is 67% of the way to
flat ambient tone with 1.7x grain, and **every single covered pixel in the
combat fixture is at haze 1.000** — the entire visible cast rendered as
featureless ambient colour, with up to 7x grain on top. That is precisely
the "far actors read as washed out" failure the manual attestation table
below exists to catch, and it would have shipped on by default.

At the values now in `plate.py`, the deepest visible attic pixel reaches
0.304, the deepest pixel in either fixture (combat's) reaches 0.611, and
the nearest actor in each fixture is at exactly 0.

`HAZE_DENSITY` was itself corrected once more, in review round 1. This
task first shipped 0.000012, which is a defensible *shape* — near actor
untouched, no saturation anywhere — but the wrong *amount*: measured, it
moved the attic's affected pixels by a mean of 1.71 counts and a maximum
of 10, which is below what an eye reliably resolves on a dithered actor.
A knob that is on by default and changes nothing anyone can see is an
inert feature wearing a different hat, which is this project's dominant
defect class. 0.000035 is the measured replacement: it lands the attic's
far end at 0.30 rather than 0.12, still nowhere near the 1.000 that made
the plan's value unshippable, and the pixel counts below show what it
buys.

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
at eye depth 2400 and `_far_flat_actor_frame`'s at 2500 — **both at or
below the new `HAZE_START` of 2500, so both would have hazed by exactly
zero.** Not weakened: inert. `test_neutral_tunables_are_an_exact_identity`'s
second half, `test_a_far_actor_moves_toward_the_ambient_tone_and_a_near_one_does_not`,
`test_softness_and_grain_increase_with_depth` and
`test_haze_unpremultiplies_depth_at_partially_covered_edges` would all
have been comparing two identical unhazed renders while still passing.
Both fixtures now sit at eye depth 15000. `_far_flat_actor_frame` got
there with a lengthened lens (`focal2 = focal3 = 3200`) rather than a
scaled-up triangle, because the enhanced material's detail field is
world-space and a 6x larger triangle alone moved that test's measured
edge-vs-interior gap from 0.3 counts to 20, past its own 6.0 threshold,
with no bug present. The lens grew 10x against a 6x depth change, so
that silhouette is about 1.67x larger on screen than before (64 edge and
1540 interior pixels, against 114 and 435), which is harmless for a test
that compares two means and asserts a 20-pixel floor on each region
first.

One thing the tunables are **not**: pinned by a test at their tuned
value. Reverting `HAZE_DENSITY` from 0.000035 to the superseded 0.000012
leaves the whole suite green, because the suite asserts that the haze is
nonzero and directional, never that it has a particular magnitude — and
that is the right call, since a magnitude assertion would freeze a taste
decision the attestation table is meant to be able to revisit. What the
suite does now carry is an anti-collapse floor in
`test_the_nohaze_twin_differs_from_the_default`: the twin's peak channel
delta must reach 6 counts on both fixtures. Measured sweep at scale 1 —
3.5e-5 gives attic 22 / combat 34, 1.2e-5 gives 9 / 16, 4e-6 gives 5 / 8,
and 0.0 still gives 3 / 4. That residual is the **grain grade alone**, not
"the two grades" as this document first said: these renders are scale 1,
where by the limitation above the sigma grade contributes exactly nothing.
Decomposed directly, at the floor test's own scale:

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python scratch_decomp.py
  attic: all three live            peak  22
  attic: haze 0, sigma+grain live  peak   3
  attic: haze 0, grain only        peak   3
  attic: haze 0, sigma only        peak   0
  attic: all three zero            peak   0
  combat: all three live            peak  34
  combat: haze 0, sigma+grain live  peak   4
  combat: haze 0, grain only        peak   4
  combat: haze 0, sigma only        peak   0
  combat: all three zero            peak   0
```

(The last row of each block is also the neutral-tunables identity holding
on real game data rather than on a synthetic frame.) The floor therefore
sits above what the grain grade alone produces and below the
previously-shipped density, catching a collapse toward inertness without
deciding how strong the haze should be.

**That floor lives in a `data_dir`-gated test.**
`test_the_nohaze_twin_differs_from_the_default` needs real game data and
skips without it, so on a machine with no `data/aitd1` the feature's only
magnitude guard silently disappears — the rest of the suite still pins
that the haze is nonzero and directional, but nothing then checks that it
is large enough to see. This repo ships no game data, so that is the
default state for a fresh clone.

Both fixture moves were mutation-checked. With `d / a.a` in `COMPOSITE_FSH`
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
nohaze attic equal? False pixels differing: 56800 / 1024000 max abs diff 22 mean abs diff 0.124765625
nohaze combat equal? False pixels differing: 4423 / 1024000 max abs diff 30 mean abs diff 0.029056966145833335
```

The twin differs on **both** fixtures, which the task brief did not take
for granted — the attic is nominally the small-room case the haze is
built to leave alone. Measured, it is not: the attic's camera has
`focal1 = 1431` and its ten actors spread from eye depth 1503 to 16021
(covered depths 1431 to 12840), so most of its cast is past `HAZE_START`
and only its nearest actor is genuinely untouched. 56,800 pixels move on
the attic — 5.5% of the frame, about seven eighths of its 64,604 covered
actor pixels — by at most 22 counts. The combat venue moves fewer pixels
(its whole cast is small on screen) but harder, at most 30 counts,
because its entire visible cast sits at eye depth 22,128-29,488.

Per-pixel magnitude over the pixels that actually move, taken directly
rather than from the PNGs (this is the max-channel delta at each moved
pixel, averaged):

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python scratch_pixels.py
attic: frame 1280x800  differing pixels 56800 (5.55% of frame)  max channel delta 22  mean |delta| over differing px 3.57
combat: frame 1280x800  differing pixels 4423 (0.43% of frame)  max channel delta 30  mean |delta| over differing px 9.83
```

At this task's first density (0.000012) those same two lines read 10 /
1.71 and 15 / 4.81 — a shift small enough to be argued away as dither.
At 0.000035 the attic's affected pixels average 3.6 counts and reach 22,
and the combat venue's average 9.8 and reach 30, while the near actor in
each fixture still moves by exactly nothing. That is the trade this
document exists to hand a human: the numbers for three settings are in
"The tunables", and `HAZE_DENSITY` is the only constant to turn.

The near-versus-far measurement
`test_a_far_actor_moves_toward_the_ambient_tone_and_a_near_one_does_not`
asserts on, reproduced directly:

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python scratch_pixels.py
near actor (eye depth 1500, under HAZE_START): mean |on-off| = 0.0000 counts over 903 px
far  actor (eye depth 15000):                  mean |on-off| = 32.3561 counts over 351 px
far actor's mean distance from the ambient tone: 91.44 -> 59.09 counts
```

The near actor moves by **exactly zero** counts across 903 pixels — the
"a small room is untouched" guarantee, measured rather than argued. The
far actor moves 32.4 counts on average, and moves *toward* the ambient
tone: its mean distance from it falls from 91.44 to 59.09.

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

Re-measured at the shipped `HAZE_DENSITY` of 0.000035 — the density does
not change the instruction count (the `exp` runs either way), so this was
not expected to move, but the document must not carry a number taken at a
different setting:

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python scratch_frametime.py
--- L alone: the atmosphere knob, everything else at its shipping default (n=64 interleaved, attic, scale 4, msaa 4, smoothing 2)
  atmosphere=off                                     cpu   3.42  gpu   8.23  frame  11.65 ms  (median  11.22, min  10.09)
  atmosphere=on (the new default)                    cpu   3.38  gpu   8.22  frame  11.60 ms  (median  11.04, min  10.32)
  ratio b/a = 0.995 whole frame, 0.998 GPU only

--- roadmap 2: I + J + K + L all off versus all on (n=64 interleaved, attic, scale 4, msaa 4, smoothing 2)
  I tick, J unpainted, K occlusion=off, L atmosphere=off cpu   3.48  gpu   8.31  frame  11.78 ms  (median  11.45, min   9.90)
  I smooth, J painted, K ssao, L atmosphere=on       cpu   3.72  gpu   8.31  frame  12.03 ms  (median  11.54, min  10.74)
  ratio b/a = 1.021 whole frame, 1.001 GPU only   budget <= 1.5: MET
```

Three further back-to-back runs of the same script, unmodified, on this
shared and noisy machine:

```
run 1:  ratio b/a = 0.993 whole frame (L alone)  |  1.026 whole frame (roadmap)   budget <= 1.5: MET
run 2:  ratio b/a = 0.992 whole frame (L alone)  |  1.052 whole frame (roadmap)   budget <= 1.5: MET
run 3:  ratio b/a = 1.001 whole frame (L alone)  |  1.048 whole frame (roadmap)   budget <= 1.5: MET
```

**L alone is at or below this machine's noise floor.** Across four runs
its ratio was 0.995, 0.993, 0.992, 1.001 — straddling 1.0, which is not a
claim that the composite's extra arithmetic is free, only that it is
smaller than the run-to-run spread of a 11.6 ms frame here. The honest
statement is that L's cost is not measurable on this fixture at this
resolution, not that it is zero.

**The roadmap's closing budget is met with a wide margin: 1.021, 1.026,
1.052 and 1.048 across four runs (mean 1.037), against a 1.5x ceiling.**
This is the number the spec asked for at
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
   change — but it means the ~1.04x above **understates** L's true cost
   against a pre-roadmap baseline that had no second colour attachment at
   all. The honest statement is that the *switchable* part of all four
   sub-projects costs about 4%, not that all four cost about 4%. It also
   explains why "L alone" measures at the noise floor: the allocation and
   the per-fragment depth write, which are the parts with a real cost,
   happen on both sides of that particular ratio, leaving only the
   composite's extra arithmetic to be seen.
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
| The effect is the right strength — not too weak to see, not washed out (attic: mean 3.6 / max 22 counts over the pixels it moves; combat: 9.8 / 30 — see "Pixel evidence", and "The tunables" for two other settings) | pending |

## Known limitations

- **Haze and the two grades are tuned by eye, and no eye has seen them
  yet.** The four constants were settled here against *measured* fixture
  depths and *measured* pixel deltas, which is a real improvement on the
  plan's reasoning-from-scale, but "how much haze looks right" is not a
  measurable quantity — measurement can only bound it, by ruling out the
  saturating end (haze 1.000 on the whole combat cast) and the invisible
  end (a 1.7-count mean on the attic). The shipped setting sits between
  those bounds; where exactly it should sit inside them is the last row
  of the attestation table. "The tunables" carries all three settings so
  that decision needs no new measurement, and `HAZE_DENSITY` is the only
  constant that should move.
- **`SIGMA_DEPTH_SLOPE` is entirely inert on a large share of the
  supported settings — not merely bounded.** The documented bound is real:
  `radius` stays a uniform because the composite's blur loop depends on
  uniform control flow, so only the weight falloff (`inv_sigma2`) is
  graded, and the grade can soften within the existing radius but never
  sharpen past it. The stronger fact is that `sample_layers` has two early
  returns — `pixelate != 0`, and `radius <= 0` — and **neither reads
  `grade` at all**. So whenever the plate cell is at most one target pixel
  (`plate.softness` returns `sigma = 0`, hence `radius = 0`) or the
  background filter is `nearest`, the softness grade does nothing
  whatsoever. That includes `--render-scale 1` outright, and
  `--background-filter nearest` at every scale.

  Measured on both fixtures, rendering the sigma grade alone (haze density
  and grain slope zeroed) against `atmosphere="off"`:

  ```
  $ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python scratch_sigma.py
    attic scale=1 filter=bilinear  sigma-grade-only vs off:      0 px differ, peak   0
    attic scale=4 filter=bilinear  sigma-grade-only vs off:   6930 px differ, peak   2
    attic scale=4 filter=nearest   sigma-grade-only vs off:      0 px differ, peak   0
    attic scale=2 filter=bilinear  sigma-grade-only vs off:   2311 px differ, peak   2
   combat scale=1 filter=bilinear  sigma-grade-only vs off:      0 px differ, peak   0
   combat scale=4 filter=bilinear  sigma-grade-only vs off:   2048 px differ, peak   4
   combat scale=4 filter=nearest   sigma-grade-only vs off:      0 px differ, peak   0
   combat scale=2 filter=bilinear  sigma-grade-only vs off:    625 px differ, peak   4
  ```

  Zero pixels at scale 1 and under `nearest`; and even where it does act,
  at most 2-4 counts. Of the three terms this sub-project ships, one of
  them is doing nothing at all for a player at the default scale of 1, and
  very little anywhere. `GRAIN_DEPTH_SLOPE` and `HAZE_DENSITY` are the two
  that always act — anyone reaching for a stronger depth cue should turn
  those, not this.
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
- **The composite's `if (a.a > 0.0)` coverage gate is untested, and on
  this driver untestable.** Replacing it with `if (true)` leaves the entire
  suite green (`1637 passed, 1 skipped, 1 xfailed`) *and* leaves the attic
  fixture byte-identical — verified both ways. Every line inside the gate
  divides by `a.a` (the colour unpremultiply, and the depth one right
  after it), so at zero coverage the guard is what stands between the
  frame and a 0/0; this GPU simply flushes that 0/0 to a finite value,
  and the closing `plate * (1 - a.a) + c * a.a` multiplies it by zero
  regardless. A portable test that fails today therefore cannot be
  written, so the shader now carries a comment saying what the gate is
  for instead. Pre-existing — the gate predates this plan — but recorded
  because a future change that makes `c` non-finite at zero coverage
  would turn an untested guard into the only thing preventing NaN pixels
  on hardware less forgiving than this one.
- **Nothing covers depth on the `_screen_prog` path.** `_SCREEN_VSH`
  writes `v_view = vec3(0.0)`, so lines and points report `depth ==
  focal1` — the nearest depth their camera can produce — via a `focal1`
  uniform bound in `_draw_frame`. `render_gl.py` used to claim that
  binding was load-bearing and that this plan's own test would fail
  without it. It was, at the `HAZE_START` of 1600; at 2500 it is not.
  Zeroing the uniform now leaves all 1637 tests green, because 0 and
  `focal1` are both under the threshold and both haze by exactly nothing.
  The comment is corrected, and the gap recorded: lowering `HAZE_START`
  below some camera's `focal1` makes that binding visible again with
  nothing watching it.
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
`scratch_near.py`, `scratch_floor.py`, `scratch_sigma.py`,
`scratch_decomp.py`) are not part of the shipped repo; `.gitignore` covers
`scratch_*.py` for exactly this convention.
