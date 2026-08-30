# Actor surface response and materials proof

Date: 2026-08-28
Spec: `docs/superpowers/specs/2026-08-28-actor-surface-and-materials-design.md`

**This document's "Manual attestation" table is a checklist for a human with
real game data and a real window; every row starts `pending` and no claim
about the rendered PNGs should be inferred from this file until a human
fills them in.** Everything under "Automated gates" was actually run, in this
environment, on this branch, and the output shown is the real output of that
run — but a headless pytest run is not the same thing as looking at the
game.

## What changed

Actors now carry a per-material surface under `realism=enhanced` (the
default): a palette-index material table (`PyAitD/render/materials.json`,
bootstrapped by `make bootstrap-materials`, hand-correctable, overridable per
body under `overrides/bodies/body<NNN>.json`) drives specular, a fresnel
rim, a sky/ground hemisphere ambient, rest-pose vertex occlusion, a contact
darkening at the feet and procedural grain glued to each limb.
`realism=classic` at `smoothing=0` reproduces the pre-change output byte for
byte (`tests/golden/scene_lit_classic.npy`, which the test now renders at
that level explicitly -- the golden predates tessellation).

## Automated gates

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest \
    tests/test_materials.py tests/test_occlusion.py tests/test_bootstrap_materials.py \
    tests/test_geometry.py tests/test_asset_resolver.py tests/test_scene.py \
    tests/test_render_gl.py tests/test_override_check.py tests/test_render_options.py -q
........................................................................ [ 43%]
........................................................................ [ 87%]
.....................                                                    [100%]
165 passed in 3.81s
```

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest -q
........................................................................ [  5%]
........................................................................ [ 10%]
..........................x............................................. [ 16%]
............................s........................................... [ 21%]
........................................................................ [ 27%]
........................................................................ [ 32%]
........................................................................ [ 38%]
........................................................................ [ 43%]
........................................................................ [ 49%]
........................................................................ [ 54%]
........................................................................ [ 60%]
........................................................................ [ 65%]
...............s........................................................ [ 71%]
........................................................................ [ 76%]
........................................................................ [ 82%]
........................................................................ [ 87%]
........................................................................ [ 93%]
........................................................................ [ 98%]
...................                                                      [100%]
1312 passed, 2 skipped, 1 xfailed, 26 warnings in 45.34s
```

`tests/test_render_gl.py::test_classic_realism_matches_the_pre_materials_golden`
is the binding one: it asserts `np.array_equal` against
`tests/golden/scene_lit_classic.npy`, captured from the pre-branch backend.

## `make prove-graphics`

Fourteen PNGs under `docs/graphics-proof/` (git-ignored): the twelve
`<attic|combat>-<flat|lambert|smooth>-<classic|enhanced>.png`, plus the
`<attic|combat>-smooth-enhanced-flatmesh.png` pair the later smooth actor
geometry branch added.

Those twelve now render tessellated, at that branch's `smoothing=2`
default, so they are not the pixels this document was written against; the
rows below are still the right checks for the material response, but a
human filling them in is looking at a rounded mesh — and the first row's
byte-identity check now needs `--smoothing 0` to mean what it meant when it
was written. The tessellation itself is attested separately, in
`docs/smooth-geometry-proof.md`.

## Known limitations

Two of the limitations below were **written on 2026-08-28 and superseded
on 2026-08-29** by the materials v2 branch, which carried out the very
hand review this document said had not happened. Each is left in place
with what was true then and what is true now, in the way the
`-flatmesh` attestation row in `docs/smooth-geometry-proof.md` records its
own supersession.

- **Nothing in the game is classified `glass` — and that is now a finding,
  not a gap.** *Then:* the attic window panes and the lantern's glass
  chimney landed on ramps `materials.json` classified as `cloth`, the
  vision pass did not correct it, and the remedy looked like a hand-label
  pass over those ramps. *Now, after the review
  (`docs/materials-v2-proof.md`, "Glass does not exist in this data"):*
  **no ramp among the 23 that any body uses reads as glass**, and the
  chimney was reviewed to `skin`, not `cloth`. The window is largely
  pre-rendered plate rather than body geometry — the striping across its
  panes is present under `realism=classic` too — so the survey, which
  walks bodies, never sees it at all; the panes that *are* geometry read
  `cloth`. A `glass` preset still exists in `CLASS_PRESETS` (low
  roughness, high specular, strong rim) and the shipped table still never
  reaches it. What changed is the remedy: not "re-run the survey and hope",
  but a per-body override (`DIR/bodies/body<NNN>.json`) for a body that
  genuinely wants it. `hair` is absent for the same reason.
- **The shipped classification was an unreviewed model answer; it is not
  one now.** *Then:* of the 23 palette ramps that any body actually uses,
  the vision pass overrode the heuristic on 20 and agreed with it on 3,
  and nothing in the committed table had been checked by a human against
  the game's own art. *Now:* it has. A human reviewed all 23 ramps one at
  a time against the survey's rendered swatches and the bodies that use
  them; the outcome — 15 class values changed across 152 palette indices —
  is what ships, `docs/materials-v2-proof.md`'s "The ramp review" is the
  durable ramp-by-ramp record, and `tests/test_bootstrap_materials.py`'s
  `REVIEWED_RAMPS` pins the resulting per-index mapping. **Read the
  committed table as a human decision, not as disposable model output.**
  A bare `make bootstrap-materials` re-emit, without the survey's `label`
  fields, silently reinstates the model's guesses — which is exactly what
  the review found had already happened to ten ramps — and `REVIEWED_RAMPS`
  is the net that fails when it does. The `note` on each row still records
  the heuristic's answer, the model's and the human's (`label:`), so the
  disagreements stay readable. The 32 ramps no body uses are still not
  emitted at all — `parse_table`'s implicit `matte` default already covers
  them.
- **Escape hatches, if the classification is wrong for you.** `enhanced` is
  user-toggleable at runtime from the Graphics page's Realism row (moved
  there from CONFIG by the smooth actor geometry branch) and at launch with
  `--realism classic`; `classic` with `--smoothing 0` reproduces the
  pre-change output byte for byte, and `classic` on its own reproduces its
  shading while the bodies stay tessellated at the default level.
  For a single asset rather than the whole look, a per-body override
  under `overrides/bodies/body<NNN>.json` remaps palette indices for that
  body only, on top of the committed default table, and is checked by
  `make check-overrides` the way the game loads it.

## Manual attestation

| Check | Status |
|---|---|
| `attic-smooth-classic.png` is identical to the pre-change `attic-smooth.png` | pending |
| Under `enhanced`, skin shows a soft highlight and the hero's clothes read matte | pending |
| Floor objects (wood, metal) carry a highlight that sits on the lit side | pending |
| A faint darkening at the feet and in rest-pose creases; no black blotches | pending |
| Grain is visible at scale 4 on cloth/wood, invisible at scale 1 | pending |
| Graphics page (`Configuration` -> `Graphics...`): Realism sits between AA and Smoothing, 7 rows plus Back, nothing clipped | pending |
| Toggling Realism in the menu changes the look live; Classic looks as before | pending |
