# Actor surface response and materials proof

Date: 2026-08-28
Spec: `docs/superpowers/specs/2026-08-28-actor-surface-and-materials-design.md`

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
........................................................................ [ 45%]
........................................................................ [ 91%]
..............                                                           [100%]
158 passed in 3.64s
```

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest -q
........................................................................ [ 27%]
........................................................................ [ 33%]
........................................................................ [ 38%]
........................................................................ [ 44%]
........................................................................ [ 49%]
........................................................................ [ 55%]
........................................................................ [ 60%]
........................................................................ [ 66%]
......s................................................................. [ 71%]
........................................................................ [ 77%]
........................................................................ [ 82%]
........................................................................ [ 88%]
........................................................................ [ 93%]
........................................................................ [ 99%]
..........                                                               [100%]
1303 passed, 2 skipped, 1 xfailed, 26 warnings in 44.51s
```

## `make prove-graphics`

Twelve PNGs under `docs/graphics-proof/` (git-ignored):
`<attic|combat>-<flat|lambert|smooth>-<classic|enhanced>.png`.

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
