# AGENTS.md

Python engine rewrite of Alone in the Dark 1, test-driven from the FITD C++
decompilation. `CONTEXT.md` is the living architecture map — read it first,
update it when a milestone lands.

## Commands

```bash
make test          # .venv/bin/pytest -q — the gate
make prove         # parse-all + headless real-script boot (real data)
make prove-m3b     # focused interaction suite, runs headless itself
make prove-mouse-only # one-button contract + real mouse journeys, including held pushing
make prove-shell   # M4a1 shell/config/mouse-contract + real-loop journeys
make prove-mouse-accessibility # focused effective-target/hover/touch/takeover gate
make prove-graphics # render attic + combat fixtures at every shading mode to docs/graphics-proof/
make export-backgrounds # originals + guides + manifest to ./overrides (git-ignored) for external AI regeneration (out=, floors=, scale=, force=1)
make check-overrides # validate ./overrides (or overrides=DIR) as the game loads it; proof=1 renders side-by-sides
make run           # play via character select; floor=0 debug bypass, data="..." trace=/tmp/t.log optional
```

Any test touching rendering/pygame needs `SDL_VIDEODRIVER=dummy`. After
non-trivial changes run `.venv/bin/pytest -q && make prove`. No lint,
formatter, or typecheck is configured — LSP/pyright diagnostics are noise,
the test suite is the only gate. Never mass-reformat.

## Game data + FITD reference

- Tests use the user's original game data via the `data_dir` fixture and
  skip when absent. `*.app/` is git-ignored: never commit game data.
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

## Conventions

- `# SPDX-License-Identifier: GPL-2.0-only` first line of every Python file.
- Layer boundary: `playworld.py`/`life_ops.py`/`interaction.py`/`effects.py`
  never touch pygame/rendering/events; `config.py` is pygame-free settings
  schema/persistence; `ui.py` never mutates world/actor/inventory/LIFE state;
  `__main__.py` owns the single event pump, the settings lifecycle, game/floor
  replacement, and one present per frame. Settings live on `ModalSession`,
  never `Game`. `tests/test_playworld.py` enforces the playworld half.
- Graphics layering: `scene.py`, `geometry.py`, `mask_geometry.py` and
  `render_options.py` import neither pygame nor moderngl — keep them pure.
  `asset_resolver.py` touches pygame in exactly one function (`load_png_rgb`);
  `render_soft.py` uses `pygame.draw` but never moderngl; `render_gl.py` owns
  all moderngl; `render.py` owns the window and both. `scene.build_frame`
  returns an immutable `FrameDescription` whose `palette` and
  `background.pixels` alias shared decode caches — read them, never write.
- `background_export.py` and `override_check.py` are pure like `scene.py`;
  PNG encoding lives only in `tools/`. The export directory layout is
  `asset_resolver.override_background_path`'s — change both or neither.
- `skel.skin`'s integer projection stays authoritative for picking, masks and
  the mouse contract; `draw_list` entries must stay byte-identical.
  `scene.CameraView` is a parallel float path for rendering only and is
  deliberately not bit-identical — it diverges by ~9.6px near the camera and
  ~0.13px far away, because the integer path truncates. Never "fix" that
  divergence by projecting `draw_list` through the float path.
- Held mouse actions latch one world object, never publish global Action, and
  cancel on mouse-up or focus loss before animation/collision. Existing LIFE
  and collision code alone move pushable scenery. Keep the both-protagonist
  journey in `tests/test_mouse_only.py` and run `make prove-mouse-only` after
  changing pointer, navigation, animation, modal, or collision behavior.
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
- Dependencies fixed: pygame-ce, ModernGL, NumPy, pytest. Add nothing.
