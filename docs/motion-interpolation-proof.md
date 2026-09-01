# Motion interpolation proof

Date: 2026-08-31
Spec: `docs/superpowers/specs/2026-08-31-actor-realism-roadmap-2-design.md` (sub-project I)
Plan: `docs/superpowers/plans/2026-08-31-motion-interpolation.md`

**This document's "Manual attestation" table is a checklist for a human
with real game data and a real window; every row starts `pending`.**
Everything under "Automated gates" and "`make proof-graphics`" was
actually run, in this environment, on this branch, and the output shown
is the real output of that run.

## What changed

Actors interpolate between 50 Hz simulation ticks at the display rate
under `motion=smooth` (the default): `render/motion.py` blends the
pre-tick snapshot toward the live state through a float twin of the
integer pose. `motion=tick` renders exactly the pre-change frames.
Picking, masks, the draw_list and the mouse contract read the tick pose
throughout. Rendered motion lags the simulation by up to one tick.

## Float pose divergence

`pose_vertices_float` (render/motion.py) diverges from the authoritative
integer `pose_vertices` only by fixed-point truncation, the way
`CameraView.project` diverges from `skel.skin` by ~6 world units (measured
across a wide distance sweep -- see `render/scene.py`'s `CameraView.project`
docstring). The float pose's own divergence is larger than CameraView's,
because it compounds through the body's group hierarchy -- a limb vertex
rotates once per ancestor group, and each rotation amplifies the previous
one's truncation error by the radius -- rather than through one rotation
chain.

The final whole-branch review found the branch's original parity test
measured the one pose shape that cannot exercise that compounding (every
group's delta zero except the root, which `actor_angles` overrides, so
`pose_vertices`' `if dx or dy or dz` gate skips every other group and each
vertex rotates exactly once). Driving a real `AnimPlayer` over a body's own
animations -- a genuinely hierarchical pose, where group_states carries a
different non-zero delta per group -- measures the real number:

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -c "
import numpy as np
from PyAitD.games.aitd1.profile import AITD1
from PyAitD.engine.data.assets import Assets
from PyAitD.engine.actor.anim import AnimPlayer
from PyAitD.engine.actor.skel import pose_vertices
from PyAitD.render.motion import pose_vertices_float
assets = Assets('data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK', AITD1)
for body_num in (1, 12, 30):
    body = assets.body(body_num)
    worst, worst_anim = 0.0, None
    for anim_num in range(assets.num_anims):
        try:
            anim = assets.anim(anim_num)
        except KeyError:
            continue
        player = AnimPlayer(body, anim, start_tick=0)
        tick = 0
        for _ in range(anim.num_frames * 20):
            player.advance(tick)
            states = player.group_states()
            integer = np.array(pose_vertices(body, states, actor_angles=(0, 300, 0)), dtype=np.float64)
            floats = pose_vertices_float(body, states, actor_angles=(0, 300, 0))
            d = float(np.max(np.abs(floats - integer)))
            if d > worst:
                worst, worst_anim = d, anim_num
            tick += 1
            if player.wrapped:
                break
    print(f'body {body_num} ({len(body.groups)} groups): worst {worst:.4f} (anim {worst_anim})')
"
body 1 (2 groups): worst 5.6189 (anim 119)
body 12 (17 groups, the hero): worst 42.6753 (anim 119)
body 30 (20 groups): worst 50.0407 (anim 11)
```

Sweeping every one of a body's own animations, not just the 0-24 range the
review's own measurement used, does not raise the worst above ~50.04
either. `tests/test_motion.py::test_pose_vertices_float_parity_on_real_animations`
covers the same measurement over the same 0-24 range (fast enough to run
every gate) and is pinned at `_HIERARCHICAL_PARITY_BOUND = 60.0` --
headroom over the measured ~50 units, not the old, honestly-false `16.0`
the single-rotation case could not have exceeded regardless of a real
accumulation defect. The old zero-states case is kept as a cheap,
non-regression-guard floor (`test_pose_vertices_float_parity_zero_states_baseline`,
bound `10.0`, measured ~2.8-7.25 units across bodies 1 and 12).

This divergence is presentation-only and frame-to-frame consistent: it
never reaches `skel.skin`, the `draw_list`, picking, masks or combat, and
it changes smoothly tick to tick along with the blend it comes from. It is
largest at snap boundaries -- a camera cut, room change, floor change,
identity change or teleport -- where `build_frame` flips an actor from the
float pose back to the integer one (or vice versa) rather than blending
across the discontinuity; even there it is bounded by the numbers above,
not by TELEPORT_LIMIT's much larger 500-unit position snap threshold,
which is a different quantity (position, not pose-vertex divergence).

## Automated gates

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest \
    tests/test_motion.py tests/test_geometry.py tests/test_scene.py \
    tests/test_render_options.py tests/test_ui_reducers.py \
    tests/test_ui_render.py tests/test_main.py tests/test_prove_graphics.py -q
........................................................................ [ 30%]
........................................................................ [ 61%]
........................................................................ [ 91%]
...................                                                      [100%]
235 passed, 2 warnings in 5.25s
```

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
1530 passed, 1 skipped, 1 xfailed, 26 warnings in 42.85s
```

This matches the pre-task baseline (`1530 passed, 1 skipped, 1 xfailed,
26 warnings`) exactly — the flip and its dozen-plus pin updates changed
no skip, xfail or warning count.

`tests/test_render_gl.py::test_classic_realism_matches_the_pre_materials_golden`
(now naming `motion="tick"` alongside every other roadmap-2 field the
identity holds at) passed on its own:

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest \
    tests/test_render_gl.py::test_classic_realism_matches_the_pre_materials_golden -q
.                                                                        [100%]
1 passed in 0.17s
```

The classic golden (`tests/golden/scene_lit_classic.npy`) still passes
byte for byte; the identity net for the whole realism programme is
intact.

## `make proof-graphics`

```
$ make proof-graphics
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
```

Twenty-two PNGs (git-ignored; `docs/graphics-proof/` keeps only a
`.gitkeep`), two more than before this task: the twelve
`<attic|combat>-<flat|lambert|smooth>-<classic|enhanced>.png` at the
defaults, the flat-mesh, hard-shadow, un-composited and over-composited
pairs, and the new `-tickmotion` pair — rendered under this
environment's default `motion=smooth`, so alpha 0.5 against the
synthetic 64-unit-back snapshot `render_fixture` builds.

**The `-tickmotion` pair did render, and it visibly differs from the
plain `-smooth-enhanced` render**, confirmed by a pixel diff rather than
by eye alone:

```
$ .venv/bin/python -c "
import pygame, numpy as np
for fixture in ('attic', 'combat'):
    a = pygame.surfarray.array3d(pygame.image.load(f'docs/graphics-proof/{fixture}-smooth-enhanced.png'))
    b = pygame.surfarray.array3d(pygame.image.load(f'docs/graphics-proof/{fixture}-smooth-enhanced-tickmotion.png'))
    diff = np.abs(a.astype(int) - b.astype(int))
    npix = (diff.max(axis=2) > 0).sum()
    print(fixture, 'equal?', np.array_equal(a, b), 'pixels differing:', npix, '/', a.shape[0]*a.shape[1], 'mean abs diff', diff.mean())
"
attic equal? False pixels differing: 89997 / 1024000 mean abs diff 0.549
combat equal? False pixels differing: 23198 / 1024000 mean abs diff 0.098
```

The escape hatch was checked too: re-running with `--motion tick`
renders the `-tickmotion` pair unblended, and it comes back **byte
identical** to the plain `-smooth-enhanced` render (`np.array_equal`
true on the attic fixture) — `blend = (motion == "smooth")` gates the
pair correctly in both directions.

## Frame time

Attic fixture, scale 4, msaa 4, smoothing 2, enhanced, `motion=smooth`
vs `motion=tick`, timing `build_frame()` (where the blend cost actually
lives — `pose_vertices_float`'s per-actor float trigonometry) together
with `backend.draw()` + `ctx.finish()`, measured the way the
soft-shadows proof measured its line, with a scratch script (not part of
the shipped repo) built on the same `render_fixture` construction
`tools/prove_graphics.py` uses for the `-tickmotion` pair — a synthetic
"previous tick" snapshot shifted 64 rotation units back, so `smooth`
takes the real `blend_actor` -> `pose_vertices_float` path every frame
rather than falling back to the unblended one:

```
$ SDL_VIDEODRIVER=dummy .venv/bin/python scratch_timing_motion.py \
    "data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK" 20 3
tick 18.45 ms  (min 13.31, max 23.96)
smooth 16.99 ms  (min 13.29, max 23.33)
```

This machine is shared and noisy (the soft-shadows proof records the
same thing about its own timing runs). Sixteen back-to-back invocations
(ten at 20 frames/3 warm-ups, six at 30 frames/5 warm-ups) gave:

```
tick means (ms):   11.34 18.45 18.69 17.73 10.48 10.40 10.68 11.38 11.51 11.11
                   11.52 10.51 10.97 11.87 11.18 11.05
smooth means (ms): 10.46 16.99 18.27 16.88 12.20 11.09 11.27 11.62 11.03 12.48
                   12.12 11.63 12.02 11.65 11.57 11.73
```

tick ranged 10.40-18.69 ms (mean of means 12.43 ms), smooth ranged
10.46-18.27 ms (mean of means 12.69 ms). Per-run ratio (smooth/tick)
ranged 0.92x to 1.16x across the sixteen runs, **ratio of means
1.02x**, and none of the sixteen runs crossed even 1.2x, let alone the
1.5x budget. The two paths cost essentially the same: `build_frame`'s
blend arithmetic (shortest-arc angle interpolation, a linear position
lerp and one `pose_vertices_float` pass per actor, all numpy) is a small
fraction of the frame's total cost next to asset resolution, GPU upload
and the draw call itself, on this two-actor attic fixture. **Record I's
share of the roadmap's cross-sub-project 1.5x budget: comfortably
under, at roughly 1.0x rather than close to the ceiling.**

The scratch script lived at
`scratch_timing_motion.py` for this measurement and is not part of the
shipped repo (the same convention `docs/soft-shadows-proof.md` used for
its own `scratch_timing.py`).

## Manual attestation

| Check | Result |
|---|---|
| Walk the attic at 120 Hz: movement is stepless under `smooth`, visibly 50 Hz under `tick` | pending |
| Camera cut mid-walk: no smear, no double image on the cut frame | pending |
| Restart / load / hero swap: first frame shows no blend from the old game | pending |
| Realism page: Motion row cycles by keyboard and mouse; persists from the menu; `--motion tick` overrides for the session only | pending |
| `-tickmotion` proof pair: the blended render sits between the tick poses | pending |
