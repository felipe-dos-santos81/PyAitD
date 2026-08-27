# AGENTS.md

Python engine rewrite of Alone in the Dark 1, test-driven from the FITD C++
decompilation. `CONTEXT.md` is the living architecture map — read it first,
update it when a milestone lands.

## Commands

```bash
make test          # the whole suite, headless — the gate
make test-engine   # simulation, LIFE VM, formats, actors, anim, tracks, collision, navmesh, picking, opcodes
make test-render   # scene, geometry, both backends, asset resolution, override export/check
make test-shell    # event pump, settings, CLI, UI screens and modals
make test-tools    # the standalone scripts under tools/
make test-meta     # the repo's own rules (package layering, test grouping)
make test-journey  # real run() event pump and long real-data simulations
make proof-mouse   # navmesh for every camera-visible room, every floor (needs game data)
make proof-combat  # venue, real enemy damage, player arms, game over (needs game data)
make proof-graphics # attic + combat fixtures per shading mode (needs GL + game data)
make proof-intro   # opening cutscene: headless gate + one GL render per visited camera
make run           # title -> menu -> character select -> opening cutscene (skip with any key/click, or --skip-intro); floor=0 debug bypass, overrides=DIR defaults to data/aitd1/overrides (overrides= disables), data="..." trace=/tmp/t.log optional
make export-backgrounds # originals + ITD_RESS screens + guides + layout sidecars + manifest to data/aitd1/overrides (git-ignored) for external AI regeneration (out=, floors=, scale=, force=1, screens=0 to skip)
make check-overrides # validate data/aitd1/overrides (or overrides=DIR) as the game loads it; proof=1 renders side-by-sides
make regenerate-backgrounds # Gemini describe+render+verify data/aitd1/overrides -> data/aitd1/overrides-ai (dry=1, floors=, style=, force=1, attempts=3, gate_scale=1.0); rejects drifted plates; needs the `agy` CLI on PATH
```

Every pytest target runs headless via the Makefile's `HEADLESS` variable, so
`SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy` is set for `make test` and every
`test-*` group. Running pytest directly still needs them on the command line.

Every file under `tests/` declares exactly one subject marker as a module-level
`pytestmark` — `engine`, `render`, `shell`, `tools` or `meta` — plus an optional
`journey` when it drives the real `run()` loop or a long real-data simulation.
Mark by the layer whose behaviour the test asserts, not by what it imports: a
test that drives `run()` and asserts routing is `shell`, one that asserts world
state is `engine`. `tests/test_test_groups.py` enforces this and fails if a new
file carries no marker. The nine legacy `prove-*` names are aliases of the new
targets; five of them (`prove`, `prove-m3b`, `prove-shell`, `prove-mouse-only`,
`prove-mouse-accessibility`) are pinned by that same test to the exact files
they historically ran, so the proof documents under `docs/` keep citing
meaningful gates — the other four (`prove-mouse`, `prove-combat`,
`prove-graphics`, `prove-intro`) are straight renames of the `proof-*`
artifact targets, which need real game data (and GL, for graphics/intro) so
they aren't part of the pytest-file pinning.

After non-trivial changes run `make test`: headless by construction, and a
superset of `make prove` (now `-m engine`, a strict subset of the full
suite), so nothing is gained by running both. No lint, formatter, or
typecheck is configured — LSP/pyright diagnostics are noise, the test suite
is the only gate. Never mass-reformat.

## Game data + FITD reference

- Tests use the user's original game data via the `data_dir` fixture and
  skip when absent. `*.app/` is git-ignored: never commit game data.
- The `GameProfile` comes from the `profile` fixture, never a direct `AITD1`
  import — pinned by `tests/test_test_groups.py`; `tests/test_game_profile.py`
  is the sole exception.
- Behavioral authority is FITD at
  `/Users/felipe.dos.santos/code/theirs/FITD/FitdLib/` (`AITD1.cpp`,
  `life.cpp`, `main.cpp`, `anim.cpp`, `inventory.cpp`, `mainLoop.cpp`).
  When behavior is unclear, trace FITD source, not prose.
- Opcode dispatch indexes `AITD1LifeMacroTable` (AITD1.cpp) by bytecode —
  NOT the `life.h` enum values. Dead slots {27, 57, 61, 69} raise.
- Golden test values are pinned from real data. If one disagrees, trace the
  same path through FITD, fix the expectation, cite FITD file:line in a
  comment. Never re-derive goldens by guessing.

## Do-not-fix quirks (FITD-faithful, all verified)

- Painter's algorithm sorts farthest-first (comparator returns -1 when
  distance1 > distance2) — do not reverse.
- GL FBO rows are bottom-up, backgrounds and CPU-uploaded textures top-down.
  `render_gl.read_rgb()`/`thumbnail()` flip on read (`[::-1]`); `render.py`
  presents the backend's GL texture with `flip_v=False` and CPU-uploaded UI
  or software-backend textures with `flip_v=True`. Swapping those two renders
  every frame upside-down and no unit test outside
  `test_render.py`'s orientation test will notice.
- Actor coords are room-scale; camera translate is `(cam - room.world) * 10`.
- Actor angles always write skeleton group 0 (FITD AnimNuage), regardless
  of body group order.
- GiveDistance2D is Manhattan with s16-cast saturation; LM_READ consumes an
  extra s16; `walkStep` outputs are crossed (xOut→animMoveZ); FITD's
  preserved bugs (e.g. LM_WAIT_GAME_OVER second wait) stay.

## Package layout

`tests/test_layering.py` enforces the import rules below by AST scan (every
file under a package, subpackages included); `tests/purity.py` re-checks the
headless ones at runtime. A rule that is not in one of those two files is not
a rule — add the test with the rule.

| Package | Owns | May import |
|---|---|---|
| `PyAitD/engine/` | The simulation, ported from FITD with `file:line` citations: formats, PAK/floor data, `Game` state, LIFE VM core, actors, animation, tracks, collision, navmesh, picking, `playworld` tick. Game-neutral: reads per-game facts from `game.profile`. | stdlib, NumPy, `engine` |
| `PyAitD/render/` | `FrameDescription` → pixels: scene description, geometry, both backends, asset resolution, override export/check. | `engine` |
| `PyAitD/games/<id>/` | Everything FITD branches on `g_gameId`: the `GameProfile` instance, the game's opcode handlers and reduced dispatch, debug venues, the mouse contract. `games/base.py` holds the dataclass. | `engine` |
| `PyAitD/app/` | Window, the single event pump, settings schema/persistence, CLI, UI screens. | everything |
| `tools/` | Standalone scripts: PNG encoding, proofs, the one AI-service caller. | everything |

`__main__.py` owns nothing but the re-export of `app.shell.main`.

**Where new code goes**

- Ports FITD behaviour (cite `file:line`) and does not depend on which game is
  loaded → `engine/`.
- Depends on the game — a PAK name, CVar name, opcode number, hero archive,
  debug venue, anything FITD guards with `g_gameId` → `games/<id>/`, exposed
  through a `GameProfile` field the engine reads via `game.profile`. Never an
  `engine/` module constant, never `if profile.name == "aitd1"` in `engine/`.
- Touches pygame or moderngl → `render/` (only `GRAPHICS_OWNERS` in
  `tests/test_layering.py` may import them) or `app/`.
- Input, menus, settings, CLI flags → `app/`.
- Writes PNGs, spawns processes, calls an external service → `tools/`.

**Growing the engine**

- A module that outgrows one responsibility (`game.py`, `interaction.py`,
  `playworld.py` are the candidates, ~500-600 lines each) becomes a
  subpackage: `engine/game/{state,boot,objects}.py` with the public names
  re-exported from `engine/game/__init__.py` so every importer and test keeps
  `from PyAitD.engine.game import init_game`. Move with `git mv`; the layering
  scan covers subpackages automatically. Split by responsibility, not by size.
- A new engine capability (save/load, audio, sequences) is a new `engine/`
  module that takes its game facts through new `GameProfile` fields, with the
  AITD1 values in `games/aitd1/profile.py` and a pin in
  `tests/test_game_profile.py`. Effects the app must react to are `effects.py`
  dataclasses emitted through `game.emit`, never a callback into `app/`.
- A second game is `games/<id>/profile.py` plus a `PROFILES` entry in
  `games/__init__.py`. If the engine needs a branch to support it, the branch
  belongs in a profile field (data or callable), and the seam is documented in
  `games/base.py`'s docstring.
- Known seams still hard-coded to AITD1 inside `engine/`, listed so nobody
  closes them ad hoc: `floor.py` names the ETAGE/CAMERA archives and calls
  `create_aitd1_mask`; `assets.py` fixes the cadre-bank entry/sprite count
  and the 320x200 screen size; `life.py` fixes `NUM_OPCODES` and the
  `core_table()` slot numbers; `formats.py` record layouts; `interaction.py`'s
  `COMBAT_ACTIONS`/`PLAYER_*_ANIM`/`PLAYER_TRACK_MODES` indices. Close one by
  moving it into `GameProfile` with a test, not by adding a second copy.

## Conventions

- `# SPDX-License-Identifier: GPL-2.0-only` first line of every Python file.
- Inside `render/`: every module is pygame- and moderngl-free except the
  `GRAPHICS_OWNERS` — `asset_resolver` touches pygame in exactly one function
  (`load_png_rgb`); `render_soft` uses `pygame.draw` but never moderngl;
  `render_gl` owns all moderngl; `render` owns the window and both. `scene.build_frame` returns an
  immutable `FrameDescription` whose `palette` and `background.pixels` alias
  shared decode caches — read them, never write.
- `app/ui.py` never mutates world/actor/inventory/LIFE state; `app/config.py`
  is pygame-free settings schema/persistence; `app/shell.py` owns the single
  event pump, the settings lifecycle, game/floor replacement, and one present
  per frame. Settings live on `ModalSession`, never `Game`.
- `render/background_export.py` and `render/override_check.py` are pure like
  `render/scene.py`; PNG encoding lives only in `tools/`. The export
  directory layout is `render/asset_resolver.override_background_path`'s and
  `override_screen_path`'s — change both or neither. `background_export`
  additionally owns the guide and layout-sidecar paths (`layout_rel_path`,
  `screen_layout_rel_path`); a sidecar holds the guide's own geometry, so
  `layout_segments` is the single source both the guide pixels and
  `tools/plate_check.py`'s leak check draw from — never re-derive either.
- `tools/regenerate_backgrounds.py` is the only module that may talk to an
  AI service. It shells out to the `agy` CLI (`subprocess.run`) — it imports no
  SDK — and its unit tests monkeypatch `subprocess.run`, so they never touch the
  network. `tests/test_layering.py` pins that boundary. Credentials belong to
  that CLI, not to this repo (a `.env` is git-ignored); never commit keys or
  generated `overrides*/` output. `tools/plate_check.py` is the offline gate
  (numpy only, no I/O); it never calls anything.
- `skel.skin`'s integer projection stays authoritative for picking, masks and
  the mouse contract; `draw_list` entries must stay byte-identical.
  `scene.CameraView` is a parallel float path for rendering only and is
  deliberately not bit-identical — it diverges by ~9.6px near the camera and
  ~0.13px far away, because the integer path truncates. Never "fix" that
  divergence by projecting `draw_list` through the float path.
- Mouse movement is a held pointer follow: every navigation intent is
  hold-bound (`playworld._apply_mouse_input` cancels an intent whose buffer is
  not held and focused), `app.shell.follow_pointer` re-resolves the held
  pointer on the frames it moved off `InputBuffer.follow_pos` and re-issues an
  intent only when the resolution differs from `InputBuffer.follow_last`, and
  hold-push keeps its latched target. Only pointer motion retargets: the same
  pixel names a different world point under every camera, so re-resolving a
  still pointer at a camera cut would steer or stop the hero on its own. A
  press within `DOUBLE_PRESS_TICKS` of the previous one runs (`NavIntent.run`
  -> `NavDecision.run` -> speed 5), timed on `game.timer` like FITD's own
  double-tap forward; the engine never learns which device asked. Held actions never publish global Action; existing LIFE and
  collision code alone move pushable scenery. Never lock, grab or warp the OS
  cursor (`tests/test_layering.py` gates it, `meta`-marked so `make test` runs
  it, not `make prove-mouse-only`). Keep the both-protagonist journeys in
  `tests/test_mouse_only.py` and run `make prove-mouse-only` after changing
  pointer, navigation, animation, modal, or collision behavior.
- Mouse accessibility hardening closed the held-push inventory takeover
  regression and has user-attested Emily/Carnby window passes. The current
  [hardening proof](docs/mouse-accessibility-hardening-proof.md) supersedes the
  older pending status in the [M4a1 shell](docs/m4a1-shell-proof.md) and
  [mouse hold-to-push](docs/mouse-hold-push-proof.md) proofs.
- `ponytail:` comments mark deliberate simplifications with upgrade path —
  respect them, don't silently remove.
- Workflow is brainstorm → spec → plan → TDD under `docs/superpowers/`
  (one spec + one task-level plan per milestone); `docs/life-vm-opcodes.md`
  is research only — plan + code are the source of truth.
- Dependencies fixed: pygame-ce, ModernGL, NumPy, pytest. Add nothing. The one
  external service, Gemini, is reached through the `agy` CLI, not a Python SDK,
  so it costs this project no dependency at all.
