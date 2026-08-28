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
`realism=classic` reproduces the pre-change output byte for byte
(`tests/golden/scene_lit_classic.npy`).

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

Twelve PNGs under `docs/graphics-proof/` (git-ignored):
`<attic|combat>-<flat|lambert|smooth>-<classic|enhanced>.png`.

## Known limitations

- **Nothing in the game is classified `glass`.** The attic window panes and
  the lantern's glass chimney land on ramps `materials.json` classifies as
  `cloth`, and the vision pass did not correct it: no ramp anywhere in the
  shipped table is `glass`. A `glass` preset exists in `CLASS_PRESETS` (low
  roughness, high specular, strong rim) and the table simply never reaches
  it, so those surfaces shade as fabric. The remedy is the documented
  hand-label loop: set `"label": "glass"` on the ramp in
  `data/aitd1/materials-survey/survey.json` and re-run
  `make bootstrap-materials`, whose survey stage carries hand labels forward
  before the table is re-emitted.
- **The shipped classification is largely an unreviewed model answer.** Of
  the 23 palette ramps that any body actually uses, the vision pass
  overrode the heuristic on 20 and agreed with it on 3. Nothing in the
  committed table has yet been checked by a human against the game's own
  art; the `note` on each row records both the heuristic's answer and the
  model's so a reviewer can see where they disagreed. The 32 ramps no body
  uses are not emitted at all — `parse_table`'s implicit `matte` default
  already covers them.
- **Escape hatches, if the classification is wrong for you.** `enhanced` is
  user-toggleable at runtime from the CONFIG menu's Realism row and at
  launch with `--realism classic`; `classic` reproduces the pre-change
  output byte for byte. For a single asset rather than the whole look, a
  per-body override under `overrides/bodies/body<NNN>.json` remaps palette
  indices for that body only, on top of the committed default table, and is
  checked by `make check-overrides` the way the game loads it.

## Manual attestation

| Check | Status |
|---|---|
| `attic-smooth-classic.png` is identical to the pre-change `attic-smooth.png` | pending |
| Under `enhanced`, skin shows a soft highlight and the hero's clothes read matte | pending |
| Floor objects (wood, metal) carry a highlight that sits on the lit side | pending |
| A faint darkening at the feet and in rest-pose creases; no black blotches | pending |
| Grain is visible at scale 4 on cloth/wood, invisible at scale 1 | pending |
| Configuration screen: 15 rows, Realism between AA and Back, nothing clipped | pending |
| Toggling Realism in the menu changes the look live; Classic looks as before | pending |
