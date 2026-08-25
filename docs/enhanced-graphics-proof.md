# Enhanced graphics scene layer proof

Date: 2026-08-25
Spec: `docs/superpowers/specs/2026-08-25-enhanced-graphics-scene-layer-design.md`

**This document was written by an agent with no game data and no display on
this machine.** Everything under "Automated evidence" was actually run, in
this environment, on this branch, and the output shown is the real output of
that run. The "Manual attestation" table below is a checklist for a human
with real game data and a real window; every row starts `pending` and no
claim about the rendered PNGs should be inferred from this file until a human
fills them in.

## What the layer is

The enhanced graphics layer sits between game asset data and presentation:
`scene.build_frame` turns an actor's pose, camera, background and masks into
an immutable `FrameDescription`, keeping the original FITD integer projection
(`skel.skin`) as the sole authority for picking, masks and the mouse contract
while a parallel float `CameraView` feeds the new renderers. Two
interchangeable backends consume that same `FrameDescription`:
`SoftwareBackend` (numpy/pygame, headless, GL-free) and `GLBackend`
(ModernGL, per-actor depth and mask-texture erasure, `flat`/`lambert`/
`smooth` shading, and a configurable background upscale filter). Everything
is optional and additive: `RenderOptions` (scale, shading, background filter,
override directory) is validated, persisted in settings v2, overridable per
session on the CLI, and reachable from the in-game Configuration screen; a
missing or failing GL context falls back to the software backend at scale 1
so the game always runs.

## Automated gates

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest \
    tests/test_scene.py tests/test_geometry.py tests/test_mask_geometry.py \
    tests/test_render_soft.py tests/test_render_gl.py tests/test_render.py \
    tests/test_config.py tests/test_render_options.py -q
ssss..............s.....ss................................s............. [ 63%]
..........................................                               [100%]
106 passed, 8 skipped in 1.78s
```

The 8 skips are the data-gated goldens and parity sweeps (projection parity
against real body data, GL mask-vs-bitmap comparison against real masks) —
this machine has no game data and no way to change that from inside this
worktree, so they skip rather than fail; a machine with real data under
`Alone in the Dark 1.app/Contents/Resources/game/INDARK` (or `PYAITD_DATA`)
runs all of them.

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest -q
331 passed, 464 skipped, 8 warnings in 4.06s
```

The 8 warnings are pre-existing (`pygame.key.key_code` called before
`pygame.init()` in two input-remapping tests) and unrelated to this task.

### `tools/prove_graphics.py` / `make prove-graphics`

`tools/prove_graphics.py <data_dir> [--out docs/graphics-proof] [--scale 4]`
boots the attic and the shared floor-5 combat venue
(`scenario.enter_combat_venue`), builds a `FrameDescription` for each with
`scene.build_frame`, renders each at every shading mode (`flat`, `lambert`,
`smooth`) on a standalone ModernGL context, and writes
`attic-<mode>.png` / `combat-<mode>.png` under `--out`, printing one line per
file written. It exits `3` with a message if no standalone GL 3.3 context can
be created, and `2` with a message if the data directory does not exist —
neither path dumps a Python traceback.

`tests/test_prove_graphics.py` pins everything that does not need game data:
argument parsing and its defaults, the six fixture x shading-mode output
paths, the exit-2 (missing data directory) and exit-3 (no GL context) paths,
and `render_fixture`'s signature. The one test that needs real data
(`test_render_fixture_produces_scaled_frames`) skips here:

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_prove_graphics.py -q
s......                                                                  [100%]
6 passed, 1 skipped in 0.17s
```

```
$ make prove-graphics
.venv/bin/python tools/prove_graphics.py "Alone in the Dark 1.app/Contents/Resources/game/INDARK"
error: game data directory not found: Alone in the Dark 1.app/Contents/Resources/game/INDARK
make: *** [prove-graphics] Error 2
```

**The proof PNGs were not generated on this machine** — there is no game
data available to this worktree. A user with the real game data runs:

```
make prove-graphics data="path/to/INDARK"
```

which writes `attic-flat.png`, `attic-lambert.png`, `attic-smooth.png`,
`combat-flat.png`, `combat-lambert.png`, `combat-smooth.png` to
`docs/graphics-proof/` (never committed — see below) and prints each path.
`data=` and `--scale` behave like the other `prove-*` targets.

## Manual attestation

None of the following has been performed. Each requires a human with real
game data and a real window.

| Check | Status |
|---|---|
| attic 4x smooth | pending |
| combat 4x smooth | pending |
| configuration graphics rows (mouse) | pending |
| --overrides with a 1280x800 PNG | pending |
| GL fallback | not attested |

Notes for whoever performs these:

- **attic 4x smooth** / **combat 4x smooth**: run `make prove-graphics
  data="path/to/INDARK"`, open `docs/graphics-proof/attic-smooth.png` and
  `docs/graphics-proof/combat-smooth.png`. Confirm the attic's rocking horse
  sits behind the right support beam (mask) and the attic wardrobe's doors
  read as facing the camera (per-actor depth), not side-on.
- **configuration graphics rows (mouse)**: `make run`, open the system menu
  → Configuration, and confirm the three graphics rows (scale, shading,
  background filter) are mouse-reachable and cycle their values.
- **--overrides with a 1280x800 PNG**: place a 1280x800 PNG at
  `<override_dir>/backgrounds/floor00/camera000.png` (see "Override
  directory convention" below), run `make run data="..." ` with
  `--overrides <override_dir>`, and confirm the attic's first camera shows
  the override image instead of the original background.
- **GL fallback**: this is *not* a manual check. `--render-scale 1` only
  changes the internal render scale — it does not disable GL, so it cannot
  be used to force the fallback path by hand. The only way this codebase
  forces "no GL context" is by monkeypatching `moderngl.create_standalone_
  context` in a test, which a human at a keyboard cannot do to a running
  game. `tests/test_render.py` covers the fallback path itself. This row
  exists in the table for completeness and is marked `not attested` rather
  than `pending`.

### Override directory convention

`AssetResolver` (`PyAitD/asset_resolver.py`) looks for overrides at:

- `<override_dir>/backgrounds/floor<NN>/camera<NNN>.png` — any size, RGB.
  `<NN>` is the two-digit floor number, `<NNN>` is the three-digit camera
  index within that floor (both zero-padded).
- `<override_dir>/palette.png` — 256 pixels wide, RGB.

A **missing** override file is expected steady-state (most floor/camera
combinations will have no override) and falls back to the original asset
silently: no log line, no error. An override file that **exists but is
unreadable or fails validation** (wrong shape, wrong width for the palette,
corrupt PNG) logs a warning naming the path and the failure, then falls back
to the original — so a typo'd filename that almost matches the convention
produces silence (it's treated as "no override here"), while a filename that
matches but whose contents are bad produces a log line. The game never
crashes on a bad override.

## Spec corrections made in this pass

`docs/superpowers/specs/2026-08-25-enhanced-graphics-scene-layer-design.md`
was corrected to match what tasks 1-11 actually built, not what the original
design called for:

1. **Stencil buffer → per-actor mask texture.** ModernGL exposes no combined
   depth+stencil framebuffer attachment, so `render_gl.py` rasterises each
   actor's applicable masks into a small offscreen R8 texture and the actor
   fragment shader `discard`s any fragment the mask marks covered, instead of
   using a hardware stencil test.
2. **`render_soft.py` touches pygame.** It calls `pygame.draw.*` on a
   `pygame.Surface` to rasterise primitives — still GL-free and headless
   (works with the SDL dummy driver), but not pygame-free the way the
   original architecture table claimed.
3. **`build_frame` signature.** It is `build_frame(game, floor, resolver)` —
   three arguments, not four. `RenderOptions` affects how a backend
   rasterises a `FrameDescription`, not how the frame is described, so it
   never reaches `scene.py`.
4. **Camera parity is not a flat 0.5px bound.** The float `CameraView`
   projection and the integer `skel.skin` projection diverge by an amount
   that shrinks with distance, not a constant: measured on-screen divergence
   is ~9.6px at depth 50-150, ~7.1px at 150-500, ~1.6px at 500-1500, ~0.34px
   at 1500-4000, and ~0.13px beyond 4000 (FITD world units from the camera).
   The divergence comes from the *integer* path's chained truncation
   (`skel.skin`'s rotation chain truncates at each stage); the float path is
   the more numerically accurate of the two, and `skel.skin` stays
   authoritative for picking, masks and the mouse contract regardless.
5. **`SoftwareBackend` is not byte-identical to the old GL compositor.** It
   paints primitives within one actor far-to-near by minimum depth (a
   software stand-in for the per-actor GL depth buffer) rather than
   reproducing the old compositor byte-for-byte; it is pinned by behavioural
   goldens in `tests/test_render_soft.py` (painter order, mask erasure,
   primitive shapes), not a byte-identical comparison.
