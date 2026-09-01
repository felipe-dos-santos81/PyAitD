# Actor surface textures proof

Date: 2026-09-01
Spec: `docs/superpowers/specs/2026-08-31-actor-realism-roadmap-2-design.md` (sub-project J)
Plan: `docs/superpowers/plans/2026-08-31-actor-textures.md`

**This document's "Manual attestation" table is a checklist for a human
with real game data and a real window; every row starts `pending`.**
Everything under "Automated gates" and "The bake" was actually run, in
this environment, on this branch, and the output shown is the real
output of that run.

## What changed

Bodies can carry a painted albedo atlas. `make export-textures` bakes a
per-corner UV sidecar and a painter's guide per body; an external painter
produces `bodies/body<NNN>.png`; the runtime samples it in place of the
ramp colour while the palette-index material table still drives every
physical term. A body with no paint renders exactly as before, and
`realism=classic` ignores paints entirely.

Task 6 adds the proof-tool half of that story: `tools/prove_graphics.py`
cannot ship a real paint (this repo ships no game data, let alone a
painted one), so `render_fixture(..., painted=True)` synthesises one —
a generated checker atlas plus a per-triangle UV keyed to each triangle's
own index, via `dataclasses.replace` on the frame's `ActorDraw`s, the
same construction the `-tickmotion` twin already uses for its synthetic
snapshot. `output_paths` gained a `-painted` pair after the `-tickmotion`
pair, carrying its own `"painted"` label.

## Automated gates

The new pair's own focused suite (Step 1 of the task brief):

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_prove_graphics.py -q
..........                                                               [100%]
10 passed in 1.99s
```

The full set of suites this task's own diff and Tasks 1-5's actor-texture
work touch (`test_layering` for the import/licence bans,
`test_export_actor_uvs` for the xatlas bake, `test_export_textures` and
`test_texture_export` for the manifest/pipeline, `test_texture_check` for
`check_textures`, `test_asset_resolver` for `body_texture`, `test_render_gl`
for the GL sampling path, `test_prove_graphics` for this task's twin):

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_asset_resolver.py tests/test_export_actor_uvs.py tests/test_export_textures.py tests/test_layering.py tests/test_prove_graphics.py tests/test_render_gl.py tests/test_texture_check.py tests/test_texture_export.py -q
........................................................................ [ 27%]
........................................................................ [ 54%]
........................................................................ [ 81%]
.................................................                        [100%]
265 passed in 21.45s
```

The full gate:

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
1576 passed, 1 skipped, 1 xfailed, 26 warnings in 59.98s
```

**Re-run after the 2026-09-01 whole-branch-review fix wave** (the two
counts above were 261 and 1570 before it): the fix wave's own final report,
`.superpowers/sdd/2026-08-31-actor-textures/final-fix-report.md`, adds six
tests — the guide<->runtime orientation contract
(`test_guide_orientation_matches_the_runtimes_top_down_upload`), the
mismatched-sidecar-does-not-crash guard at both the geometry and the
render level, the attribute-budget tripwire's GL-less half, a direct test
of `_merge_manifest_records(..., key="bodies")`, and a test pinning that
an unrelated `ImportError` inside the bake is not mislabeled as a missing
tools extra — which is exactly the +4 and +6 the two counts above show.
`1576` is the new baseline the fix wave's own report cites; it does not
match the `1570` figure quoted just above from before that wave, and that
is expected, not a discrepancy to chase.

**The `-painted` pair actually renders differently from the plain
`-smooth-enhanced` render, and `realism=classic` ignores it**, confirmed
by a pixel diff rather than by eye alone, at the same scale
`tools/prove_graphics.py` uses by default (4):

```
$ SDL_VIDEODRIVER=dummy .venv/bin/python -c "
import moderngl, numpy as np, pathlib
from tools.prove_graphics import render_fixture
data = pathlib.Path('data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK')
ctx = moderngl.create_standalone_context(require=330)
try:
    for fixture in ('attic', 'combat'):
        plain = render_fixture(data, fixture, 4, 'smooth', ctx)
        painted = render_fixture(data, fixture, 4, 'smooth', ctx, painted=True)
        diff = np.abs(plain.astype(int) - painted.astype(int))
        npix = int((diff.max(axis=2) > 0).sum())
        print(fixture, 'enhanced: equal?', bool(np.array_equal(plain, painted)), 'pixels differing:', npix, '/', plain.shape[0]*plain.shape[1])
        classic_plain = render_fixture(data, fixture, 4, 'smooth', ctx, realism='classic')
        classic_painted = render_fixture(data, fixture, 4, 'smooth', ctx, realism='classic', painted=True)
        print(fixture, 'classic: equal?', bool(np.array_equal(classic_plain, classic_painted)))
finally:
    ctx.release()
"
attic enhanced: equal? False pixels differing: 75428 / 1024000
attic classic: equal? True
combat enhanced: equal? False pixels differing: 4729 / 1024000
combat classic: equal? True
```

`make proof-graphics` itself ran clean and wrote the `-painted` pair
alongside the other 24 files (git-ignored; see "Known limitations" of
`docs/motion-interpolation-proof.md` and the file header for why none of
these are committed):

```
$ make proof-graphics
.venv/bin/python tools/prove_graphics.py "data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK"
pygame-ce 2.5.8 (SDL 2.32.10, Python 3.12.12)
...
docs/graphics-proof/attic-smooth-enhanced-tickmotion.png
docs/graphics-proof/combat-smooth-enhanced-tickmotion.png
docs/graphics-proof/attic-smooth-enhanced-painted.png
docs/graphics-proof/combat-smooth-enhanced-painted.png
```

24 PNGs total (twelve mode combinations plus five variant pairs —
flatmesh, hardshadow, nocomposite, strong, tickmotion — plus the new
painted pair). Diffing the two files written by that run against their
plain twins reproduces the same pixel counts as the direct `render_fixture`
call above (75,428 / 1,024,000 for attic, 4,729 / 1,024,000 for combat),
confirming `main()`'s own path (argument parsing, `output_paths`, the
`label == "painted"` wiring) produces the identical frame the direct call
does, not just a different code path that happens to also differ from
plain.

## The bake

Every command below ran against the real game data at
`data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK`. The
`tools` extra (`xatlas`, `libigl`) is installed in `.venv` (confirmed via
`import xatlas, igl`, both resolving to real modules under
`.venv/lib/python3.12/site-packages/`).

Direct `tools/export_actor_uvs.py` run, timed:

```
$ time .venv/bin/python tools/export_actor_uvs.py \
    "data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK" \
    --out data/aitd1/textures
pygame-ce 2.5.8 (SDL 2.32.10, Python 3.12.12)
bodies/body000.uv.json  612x562  15 charts
bodies/body001.uv.json  592x584  31 charts
...
bodies/body270.uv.json  669x705  4 charts
bodies/body271.uv.json  644x645  53 charts
267 bodies
.venv/bin/python tools/export_actor_uvs.py ... 7.88s user 1.65s system 116% cpu 8.200 total
```

267 bodies baked. Cross-checked against `body_numbers()` (the probe list
before the no-triangle skip) directly:

```
$ .venv/bin/python -c "
import pathlib
from tools.export_actor_uvs import body_numbers
from PyAitD.games import load_profile
data = pathlib.Path('data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK')
nums = set(body_numbers(data, load_profile('aitd1')))
print('probed', len(nums))
"
probed 272
```

272 probed, 267 baked — the 5 skipped are exactly the bodies with vertices
but no triangles, computed by diffing the probed set against the baked
output:

```
skipped [85, 142, 156, 158, 160]
```

`make export-textures uvs=1 force=1` (the full pipeline: backgrounds,
alts, screens, palette, the UV bake, then the materials survey/emit
stages, which regenerate `PyAitD/render/materials.json` from the
un-reviewed heuristic/vision survey — this run's incidental clobber of
that hand-reviewed, committed file was caught by the full gate below and
reverted with `git checkout -- PyAitD/render/materials.json` before
anything was staged; a repeat run for this bake only would want
`materials=0`):

```
$ make export-textures uvs=1 force=1
.venv/bin/python tools/export_textures.py "data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK" --out "data/aitd1/textures" --floors "0-7" --guide-scale "4" --force
pygame-ce 2.5.8 (SDL 2.32.10, Python 3.12.12)
floor 00: 5 cameras
floor 01: 15 cameras
floor 02: 39 cameras
floor 03: 25 cameras
floor 04: 5 cameras
floor 05: 34 cameras
floor 06: 14 cameras
floor 07: 7 cameras
screens: 7
body uvs: 267
alt_backgrounds: 5
palette: 1
data/aitd1/textures/manifest.json
.venv/bin/python tools/bootstrap_materials.py "data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK" survey --out "data/aitd1/textures/materials-survey"
pygame-ce 2.5.8 (SDL 2.32.10, Python 3.12.12)
data/aitd1/textures/materials-survey/survey.json: 55 ramps over 544 bodies
.venv/bin/python tools/bootstrap_materials.py "data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK" emit --out "data/aitd1/textures/materials-survey"
/Users/felipe.dos.santos/code/mine/m-aitd/PyAitD/render/materials.json: 23 ramps
```

Manifest schema and body-record shape, read back directly:

```
$ .venv/bin/python -c "
import json
m = json.load(open('data/aitd1/textures/manifest.json'))
print('schema', m['schema'])
print('num bodies entries', len(m['bodies']))
print(json.dumps(m['bodies'][0], indent=2))
"
schema 4
num bodies entries 267
{
  "body": 0,
  "uv": "bodies/body000.uv.json",
  "guide": "bodies/body000-guide.png",
  "texture": "bodies/body000.png",
  "size": [612, 562],
  "charts": 15,
  "tris_sha256": "0a0388695d82fb36a3ca177dab3864244e1f27ae86901c1933c47921ece02cd8"
}
```

Chart-count and atlas-size range, computed the same way (min/max over every
body record's own `charts` and `size` fields, not eyeballed from the
elided run above):

```
$ .venv/bin/python -c "
import json
m = json.load(open('data/aitd1/textures/manifest.json'))
bodies = m['bodies']
charts = [b['charts'] for b in bodies]
print('charts: min', min(charts), 'max', max(charts))
by_area = sorted(bodies, key=lambda b: b['size'][0]*b['size'][1])
lo, hi = by_area[0], by_area[-1]
print('smallest atlas: body', lo['body'], tuple(lo['size']))
print('largest atlas: body', hi['body'], tuple(hi['size']))
"
charts: min 1 max 109
smallest atlas: body 16 (488, 418)
largest atlas: body 56 (1182, 487)
```

`make check-textures` against the freshly-baked directory — with no
`bodies/body<NNN>.png` painted yet, `bodies: 0 finding(s)` is exactly the
steady state (a missing paint is not a finding, only a stale sidecar or
corrupt paint is):

```
$ make check-textures
.venv/bin/python tools/check_textures.py "data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK" "data/aitd1/textures" --floors "0-7"
pygame-ce 2.5.8 (SDL 2.32.10, Python 3.12.12)
floor 00: regenerated 0 / original 5 / missing 0 / invalid 0 / aspect 0
floor 01: regenerated 0 / original 15 / missing 0 / invalid 0 / aspect 0
floor 02: regenerated 0 / original 39 / missing 0 / invalid 0 / aspect 0
floor 03: regenerated 0 / original 25 / missing 0 / invalid 0 / aspect 0
floor 04: regenerated 0 / original 5 / missing 0 / invalid 0 / aspect 0
floor 05: regenerated 0 / original 34 / missing 0 / invalid 0 / aspect 0
floor 06: regenerated 0 / original 14 / missing 0 / invalid 0 / aspect 0
floor 07: regenerated 0 / original 7 / missing 0 / invalid 0 / aspect 0
total: regenerated 0 / original 144 / missing 0 / invalid 0 / aspect 0
screens: regenerated 0 / original 7 / missing 0 / invalid 0
alt_backgrounds: regenerated 0 / original 5 / missing 0 / invalid 0
bodies: 0 finding(s)
```

`data/aitd1/textures/` is git-ignored throughout; nothing under `data/`
was staged or committed, and `PyAitD/render/materials.json` was confirmed
reverted (`git status --porcelain` showed it clean) before the full gate
below ran.

## Attribute budget

The tessellated actor path now packs 16 of the 16 vertex attributes GL 3.3
guarantees (12 pre-existing per-corner attribute slots — position+AO,
normal+straight, color+index and rest, 4 attributes x 3 corners — plus
the new 3 per-corner UV attributes, 15 slots total, + the per-vertex
barycentric), measured at `GL_MAX_VERTEX_ATTRIBS = 16` on this machine's
GPU:

```
$ SDL_VIDEODRIVER=dummy .venv/bin/python -c "
import moderngl
ctx = moderngl.create_standalone_context(require=330)
print('GL_MAX_VERTEX_ATTRIBS', ctx.info['GL_MAX_VERTEX_ATTRIBS'])
print('GL_RENDERER', ctx.info['GL_RENDERER'])
print('GL_VENDOR', ctx.info['GL_VENDOR'])
print('GL_VERSION', ctx.info['GL_VERSION'])
ctx.release()
"
GL_MAX_VERTEX_ATTRIBS 16
GL_RENDERER Apple M3 Max
GL_VENDOR Apple
GL_VERSION 4.1 Metal - 90.5
```

GPU: **Apple M3 Max** (`4.1 Metal - 90.5`, Apple's GL-over-Metal driver).
Record the number, because the next per-corner attribute does not fit —
`tests/test_render_gl.py::test_instance_layout_uses_no_more_than_the_guaranteed_attribute_slots`
pins exactly this ceiling.

## Frame time

Attic fixture, scale 4, msaa 4, smoothing 2, enhanced, unpainted vs.
painted, timing `backend.draw()` + `ctx.finish()` (one `GLBackend`,
frames alternated between the two variants rather than drawn with one
backend each in sequence, to avoid a shader-compile / driver-cache order
bias favouring whichever variant draws second) — a scratch script (not
part of the shipped repo, the same convention `docs/soft-shadows-proof.md`'s
`scratch_timing.py` and `docs/motion-interpolation-proof.md`'s
`scratch_timing_motion.py` used), built on the same `render_fixture`
construction `tools/prove_graphics.py` uses for the `-painted` pair — a
generated checker atlas and a per-triangle synthetic UV, so `enhanced`
actually samples a texture every frame rather than falling back to the
untextured branch:

```
$ SDL_VIDEODRIVER=dummy .venv/bin/python scratch_timing_textures.py \
    "data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK" 20 3
plain 7.02 ms  (min 5.49, max 9.18)
painted 7.24 ms  (min 5.44, max 9.02)
```

This machine is shared and noisy (the soft-shadows and motion proofs
record the same thing about their own timing runs). Sixteen back-to-back
invocations of the same script (unmodified, same arguments) gave:

```
plain means (ms):    8.10 6.09 5.02 5.66 5.00 6.38 6.53 5.26 6.02 6.74 6.60 6.10 6.63 6.19 6.73 5.71
painted means (ms):  8.20 6.06 5.07 5.48 4.98 6.45 6.57 5.29 6.13 6.80 6.89 5.84 6.65 6.32 6.69 5.27
```

plain ranged 5.00-8.10 ms (mean of means 6.17 ms), painted ranged
4.98-8.20 ms (mean of means 6.17 ms). Per-run ratio (painted/plain) ranged
**0.92x to 1.04x** across the sixteen runs, **ratio of means 1.00x**, and
none of the sixteen runs came anywhere near the 1.5x budget. Sampling an
already-bound, already-mipmapped texture and branching on
`has_body_texture` in the fragment shader costs essentially nothing next
to the rest of the frame — asset resolution, GPU upload and the draw call
itself — on this two-actor attic fixture. **Record J's share of the
roadmap's cross-sub-project 1.5x budget: effectively zero, not close to
the ceiling.**

The scratch script lived at `scratch_timing_textures.py` for this
measurement and is not part of the shipped repo.

## Manual attestation

| Check | Result |
|---|---|
| Paint one body, run the game: the paint appears on that actor and no other | pending |
| Delete the paint, keep the sidecar: the actor falls back silently, no notice | pending |
| Corrupt the paint: one warning, the actor falls back, the game keeps running | pending |
| Re-export UVs after a triangulation change: `make check-textures` reports the stale paint | pending |
| `realism=classic`: the paint is ignored | pending |
| A painted body at distance: chart gutters do not bleed (mips + anisotropy) | pending |

## Known limitations

- **Body numbers are archive-scoped.** Bodies live in per-hero archives and
  the same number can name a different body for Carnby and Emily, while a
  paint is keyed by number alone (`bodies/body<NNN>.png`). A paint made for
  one hero's body 12 will be applied to the other hero's body 12 as well.
  This is inherited from the existing per-body material override, which keys
  the same way; fixing it would mean a hero-qualified path for both, and is
  out of scope here. Record which hero's archive each paint was authored
  against.
- **The bake covers every body the archives expose (272 per hero), not just
  the ones a floor can show.** That is deliberate — the archive is the unit
  the game loads from — but it means a full bake writes a guide per body.
- **Five real aitd1 bodies (85, 142, 156, 158, 160) have vertices but no
  triangle primitives** — point/sprite entries, valid `Body`s with nothing
  for xatlas to unwrap or a painter to paint. `export_bodies` skips them
  (see "The bake" above, `probed 272` vs. `267 baked`), and they never get
  a `bodies/body<NNN>.uv.json`, guide, or manifest record; a paint dropped
  at one of those five numbers is simply never read.
- **The guide's vertical orientation is pinned by a test.** The painter's
  guide and the runtime's texture upload must agree on which row `v = 0`
  lands on, or every paint ships mirrored. `_bbox_fill` maps `v = 0` to row
  0 (top), matching the runtime's own top-down `ctx.texture(...)` upload
  (`PyAitD/render/render_gl.py:918`); the guide<->runtime orientation
  contract is pinned by
  `tests/test_export_actor_uvs.py::test_guide_orientation_matches_the_runtimes_top_down_upload`,
  so the two conventions cannot silently drift apart again.
