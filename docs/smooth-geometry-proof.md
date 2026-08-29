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
pixel: 63,031 of 1,024,000 pixels (6.16%) differ, concentrated around
Carnby's head and body (bounding box x 37-1279, y 120-736 of the 1280x800
frame). Cropped to just the head, the jaw and cheeks read as a continuous
curve at smoothing 2 versus the flat mesh's faceted, pointed chin -- a clear
visible difference, not just a pixel-count one. The wardrobe, chair, stool
and window frame in the same frame are pixel-identical in shape between the
two renders (only actor-adjacent shading/AA pixels move); their edges stay
sharp because those bodies' dominant angles fall under the 80° crease
threshold.

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
