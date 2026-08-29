# Smooth actor geometry proof

Date: 2026-08-28
Spec: `docs/superpowers/specs/2026-08-28-smooth-actor-geometry-design.md`

**This document's "Manual attestation" table is a checklist for a human with
real game data and a real window; every row starts `pending` and no claim
about the rendered PNGs should be inferred from this file until a human
fills them in.** Everything under "Automated gates" was actually run, in this
environment, on this branch, and the output shown is the real output of that
run.

## What changed

Bodies are tessellated on the GPU under `smoothing` 1-3 (default 2): each
posed triangle becomes a PN patch of 4/16/64 sub-triangles evaluated by an
instanced vertex shader, with crease-aware per-corner normals planned once
per body from its rest pose (`PyAitD/render/refine.py`, 80° threshold,
`"crease"` overridable per body in `bodies/body<NNN>.json`). The ground
shadow projects the same patches, so it is as round as the actor -- and
sphere primitives (heads, hands) now cast shadows too, which the CPU path
never did. The per-corner normals also fix `smooth` shading on every
skeleton-spanning face: 46 of the hero's 131 mesh vertices used to shade
flat. `smoothing=0` reproduces the pre-change output byte for byte
(`tests/golden/scene_lit_classic.npy`). The graphics rows moved from CONFIG
to a Graphics sub-page of the system menu.

## Automated gates

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_refine.py tests/test_geometry.py tests/test_asset_resolver.py tests/test_override_check.py tests/test_scene.py tests/test_render_gl.py tests/test_render_options.py tests/test_ui_reducers.py tests/test_ui_render.py tests/test_prove_graphics.py -q
262 passed in 6.56s

$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest -q
1361 passed, 2 skipped, 1 xfailed, 26 warnings in 45.94s
```

`tests/test_render_gl.py::test_classic_realism_matches_the_pre_materials_golden`
(now naming `smoothing=0`) and `test_tessellation_shader_matches_the_numpy_reference`
(transform feedback against `refine.evaluate`) are the binding ones.

## `make proof-graphics`

Fourteen PNGs were written under `docs/graphics-proof/` (git-ignored): the
twelve `<attic|combat>-<flat|lambert|smooth>-<classic|enhanced>.png` at
smoothing 2, plus `<attic|combat>-smooth-enhanced-flatmesh.png` at smoothing
0.

Comparing `attic-smooth-enhanced.png` against its `-flatmesh` twin pixel by
pixel: 63,031 of 1,024,000 pixels (6.16%) differ, in a bounding box (x
37-1279, y 120-736 of the 1280x800 frame) that spans almost the whole
frame -- not a neighbourhood of the actor. Cropped to just the head, the
jaw and cheeks read as a continuous curve at smoothing 2 versus the flat
mesh's faceted, pointed chin -- a clear visible difference, not just a
pixel-count one.

The document originally claimed the wardrobe, chair, stool and window frame
were "pixel-identical in shape" with "only actor-adjacent shading/AA
pixels" moving. Isolating each as its own crop and diffing it against the
same crop of the `-flatmesh` render shows that claim does not hold:

| Body (crop) | Differing pixels (any magnitude) |
|---|---|
| Wardrobe | 12,732 / 18,760 (67.9%) |
| Window frame (top corners only, clear of Carnby's head) | 1,095 / 1,360 (80.5%) |
| Lantern (foreground prop) | 12,841 / 35,685 (36.0%) |
| Rocking horse | 7,807 / 35,000 (22.3%) |
| Stool | 1,906 / 5,208 (36.6%) |
| Barrels | 713 / 16,150 (4.4%) |
| Chair | 39 / 32,250 (0.1%) |

Every one of those bodies except the chair differs substantially, and none
of them is adjacent to the actor -- the wardrobe and window frame in
particular sit well away from Carnby and his shadow.

Tracing why: two candidate mechanisms fire under tessellation and neither
depends on the actor's proximity.

1. `_ACTOR_FSH`'s `grain` term (`PyAitD/render/render_gl.py`) multiplies
   each fragment's colour by `detail_noise(v_rest / m1.y, ...)`, a
   deterministic noise function of the *interpolated* rest-pose position
   `v_rest`. `_TESS_VSH` interpolates `v_rest` across each PN sub-triangle
   (`in_r0*u + in_r1*v + in_r2*w`) differently from how the flat mesh's
   `_ACTOR_VSH` passes it straight through (`v_rest = in_rest`), so any
   body whose material carries a nonzero "detail" strength (`m1.x`) samples
   a different noise-field point at `smoothing=2` than at `smoothing=0`,
   at the same screen pixel. This term is gated by `preset_b.y`, which is
   zero under `realism=classic` and nonzero under `realism=enhanced`.
2. The two render paths shade with different normals entirely, independent
   of realism. The legacy path's `_triangle_data` shades with
   `geometry.normals[idx]` -- plain per-vertex normals from
   `geometry._vertex_normals`, which average every adjacent face with no
   crease awareness, so a 90°-cornered body like the wardrobe gets its
   corners Gouraud-smoothed. The tessellated path's `_instance_data` shades
   with `geometry.corner_normals`, the crease-aware plan `refine.py`
   builds (`scene.py`'s `pose_geometry` call passes `refinement=`
   unconditionally, so this plan exists whatever `smoothing` is set to);
   `refine.py` breaks smoothing groups at edges sharper than 80°, so the
   tessellated path keeps those same corners flat. That is a real per-pixel
   lighting difference on any faceted body, with nothing to do with grain
   noise, and it fires under any realism.

Grain is gated by realism, normals are not -- so re-rendering the same
`attic` fixture at `realism="classic"` (`preset_b.y == 0`, `grain` collapses
to exactly `1.0`) isolates the two. If the classic pair's furniture diffs
collapsed to near zero, grain would be the driver; if they stayed close to
the enhanced numbers, the normals difference would be. Measured (same
crops, same two smoothing levels, `realism="classic"` this time):

| Body (crop) | Enhanced diff | Classic diff |
|---|---|---|
| Wardrobe | 12,732 / 18,760 (67.9%) | 12,105 / 18,760 (64.5%) |
| Window frame (top-left corner) | 566 / 714 (79.3%) | 540 / 714 (75.6%) |
| Window frame (top-right corner) | 529 / 646 (81.9%) | 525 / 646 (81.3%) |
| Lantern | 12,841 / 35,685 (36.0%) | 12,306 / 35,685 (34.5%) |
| Rocking horse | 7,807 / 35,000 (22.3%) | 7,757 / 35,000 (22.2%) |
| Stool | 1,906 / 5,208 (36.6%) | 1,850 / 5,208 (35.5%) |
| Barrels | 713 / 16,150 (4.4%) | 712 / 16,150 (4.4%) |
| Chair | 39 / 32,250 (0.1%) | 39 / 32,250 (0.1%) |
| Whole frame | 63,031 / 1,024,000 (6.16%) | 60,991 / 1,024,000 (5.96%) |

Every crop's classic-realism diff is within a few percentage points of its
enhanced-realism diff, and the whole-frame count drops by only 2,040 pixels
(3.2% of the enhanced total) with grain turned off. Grain is not the
driver: disabling it barely moves the numbers. The crease-aware
`corner_normals` versus plain `geometry.normals` difference -- which is
active at every realism level, because `scene.py` always builds the
crease-aware plan -- is the better-supported explanation for the bulk of
this diff, on the wardrobe, stool, lantern, rocking horse and window frame.
Grain is a real, secondary contributor (the enhanced-minus-classic gap),
not the primary one. The chair and barrels differ far less under both
realisms, consistent with those bodies not having a sharp-to-smooth normals
transition (or a "detail" material) that lands where the diff was
measured -- not independently confirmed from the body JSON.

Isolating actual *shape* (not colour) for the wardrobe -- for each row of
its crop, the x position where the pixel first diverges from the wall
colour behind it, scanned from both the left and the right -- lands on the
identical column on 134/140 rows from the left and 116/140 rows from the
right; the remaining rows shift by a few pixels (max 43, one outlier row).
So the wardrobe's outer silhouette is, practically, unchanged: its claimed
sharp corners do survive. What does not survive is "pixel-identical" as a
description of the rendered pixels, or "only actor-adjacent... pixels move"
as a description of where the differences land -- the differences are real,
frame-wide, and mostly a tessellation-dependent shading artifact rather
than a geometry one.

The `combat` fixture's camera does not frame an actor body in view, but its
pair still differs (16,234 / 1,024,000 pixels, 1.59%): a shadow blob in the
bottom-left corner is rounded under smoothing and faceted (a straight
diagonal edge) under the flat mesh -- consistent with task 6's tessellated
shadow.

## Known limitations

- PN patches are C0 across edges: faint shading bands can show at patch
  borders on the coarsest bodies.
- Open limb rings curve outward, so the gap at a bent joint can grow by a
  few units.
- 80° is one global threshold: a chamfered 60-75° furniture edge rounds
  (override per body with `"crease"`); a genuinely round 85° facet stays hard.
- Silhouettes grow a few units past the `skel.skin` bbox picking uses;
  masks are unchanged.
- `lambert` shading shows the sub-facets. The software backend is unchanged.
- Under `smoothing > 0`, any body renders with different per-pixel lighting
  than under `smoothing == 0`, even where its silhouette does not move:
  the tessellated path always shades with `refine.py`'s crease-aware
  `corner_normals`, while the legacy path shades with plain, face-averaging
  `geometry.normals` -- so a faceted body's corners go from Gouraud-smoothed
  to flat the moment `smoothing` turns on, independent of realism. Under
  `realism=enhanced` a second, smaller effect stacks on top: the `grain`
  material term samples the interpolated rest-pose position, which PN
  sub-triangles interpolate differently from the flat parent triangle.
  Measured on the attic fixture's wardrobe, stool, lantern, rocking horse
  and window frame (see "`make proof-graphics`" above, including the
  classic-vs-enhanced measurement that separates the two); neither is a
  shape change.

## Manual attestation

| Check | Status |
|---|---|
| `attic-smooth-enhanced-flatmesh.png` is identical to the pre-change `attic-smooth-enhanced.png` | pending |
| Under smoothing 2, Carnby's arms, legs and head read round; the wardrobe, chair and stool keep their edges | pending |
| The rocking horse's body rounds while its rockers and flat head stay slab-like | pending |
| The ground shadow's outline is round where the actor is round | pending |
| Graphics page: Configuration shows `Graphics...` above `Back to Menu`; the page lists 7 rows plus Back, nothing clipped; every row cycles by mouse and keyboard | pending |
| Toggling Smoothing to Off in the menu changes the look live; Off looks as before | pending |
| `--smoothing 3` at scale 8 shows no cracks between patches at a hard edge | pending |
