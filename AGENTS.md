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
- GL FBO rows are bottom-up, backgrounds top-down: actor layer flipped on
  read (`layer[::-1]`), mask-erase coords adjusted.
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
- Held mouse actions latch one world object, never publish global Action, and
  cancel on mouse-up or focus loss before animation/collision. Existing LIFE
  and collision code alone move pushable scenery. Keep the both-protagonist
  journey in `tests/test_mouse_only.py` and run `make prove-mouse-only` after
  changing pointer, navigation, animation, modal, or collision behavior.
- Known open regression: mouse-driven inventory entry during an active held
  push can retain the intent until mouse-up. Fix modal-entry cancellation and
  add a real-loop regression before claiming modal takeover is atomic.
- `ponytail:` comments mark deliberate simplifications with upgrade path —
  respect them, don't silently remove.
- Workflow is brainstorm → spec → plan → TDD under `docs/superpowers/`
  (one spec + one task-level plan per milestone); `docs/life-vm-opcodes.md`
  is research only — plan + code are the source of truth.
- Dependencies fixed: pygame-ce, ModernGL, NumPy, pytest. Add nothing.
