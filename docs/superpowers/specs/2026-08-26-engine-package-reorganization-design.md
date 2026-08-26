# Engine package reorganization — design

Date: 2026-08-26. Status: approved design, pure reorganization (no behavior
change).

## Goal

Split the flat `PyAitD/` package into `engine/`, `render/`, `games/`, and
`app/` so the FITD-faithful core is reusable for other Infogrames-engine
games (AITD2, AITD3, Jack in the Dark, Time Gate) and so game-specific
knowledge lives in one `GameProfile` object instead of module constants.
This milestone lands the seams only; no second game is in scope.

## Why not per-character / per-enemy packages

Emily vs Carnby is one hero index (body/anim archive pair). Enemies, items
and room events are LIFE bytecode in the game's PAK files interpreted by the
VM. FITD's own per-game branching (`g_gameId`) concentrates in boot
(`main.cpp`), opcode semantics (`life.cpp`), `getCVarsIdx`, and format
variants (`inventory.cpp`, `save.cpp`, `track.cpp`, `floor.cpp`) — never per
character. The layout therefore follows engine / game-profile / app.

## Target layout

```
PyAitD/
  __init__.py
  __main__.py                     # `from PyAitD.app.shell import main` — `python -m PyAitD` unchanged
  engine/
    __init__.py
    pak.py explode.py floor.py formats.py assets.py world.py cos_table.py
    skel.py mask.py anim.py actors.py tracks.py realvalue.py eval_var.py
    life.py game.py playworld.py interaction.py effects.py anim_action.py
    navmesh.py picking.py navigate.py text.py
  render/
    __init__.py
    scene.py geometry.py mask_geometry.py asset_resolver.py render_options.py
    render_gl.py render_soft.py render.py background_export.py override_check.py
  games/
    __init__.py                   # PROFILES = {"aitd1": ...}; load_profile(name)
    base.py                       # GameProfile
    aitd1/
      __init__.py
      profile.py                  # AITD1 constants assembled into a GameProfile
      life_ops.py life_reduced.py scenario.py mouse_contract.py
  app/
    __init__.py
    shell.py                      # body of today's __main__.py
    ui.py config.py
```

Every move is a `git mv`. No compatibility shims: the old
`PyAitD.<module>` names disappear and all import sites (package, `tests/`,
`tools/`) are rewritten in one scripted pass. Test file names and test
function names do not change.

## GameProfile

`games/base.py` defines a frozen dataclass holding exactly the values that
are AITD1-specific today:

| Field | Today's location |
|---|---|
| `name` | — (`"aitd1"`) |
| `pak_names`: lifes, tracks, text, resource | `assets.py` `LIFES_PAK`/`TRACKS_PAK`/`TEXT_PAK`/`RESOURCE_PAK` |
| `heroes`: tuple of `(body_archive, anim_archive)` indexed by hero | `assets.py` `BODY_ARCHIVES`/`ANIM_ARCHIVES` and the `hero in (0, 1)` check |
| `cvar_names` | `game.py` `AITD1_CVAR_NAMES` |
| `defines_big_endian` | `game.py` DEFINES parsing (True) |
| `opcode_table` | `life.py` `LIFETABLE` after `life_ops` installation |
| `dead_opcodes` | `{27, 57, 61, 69}` |
| `reduced_ops` | `life_reduced.py` |
| `boot_start` | the intro `FloorStart` used by normal boot |
| `debug_venues` | `scenario.COMBAT_VENUE` and the mouse-combat fixture entry |

`games/aitd1/profile.py` builds the instance; `games/__init__.load_profile`
returns it by name (only `"aitd1"` exists).

Signature changes (the only API changes in the milestone):

- `Assets(data_dir, profile, hero=0)` — archive names and hero validation
  come from `profile`.
- `Game(assets, profile)` — CVar names, DEFINES endianness and the opcode
  table come from `profile`. `Game.profile` is the single place the VM reads
  the table from; `life.py` keeps the game-neutral core ops (control flow,
  var ops, chrono, switch/case) and no longer owns a filled module global.
- `FOG_FLAG`-style CVar index constants become
  `profile.cvar_index("FOG_FLAG")` or a cached lookup on `Game`.

Nothing else is abstracted. No abstract base classes, no per-subsystem
strategy objects: FITD uses flat branches and most abstractions would have
one implementation forever.

## Package rules

Enforced by a new `tests/test_layering.py` that parses every module's
imports with `ast`:

- `engine/` imports nothing from `pygame`, `moderngl`, `render/`, `games/`,
  `app/`.
- `render/` may import `engine/`; never `games/` or `app/`. Within it the
  existing rules hold: `scene`, `geometry`, `mask_geometry`,
  `render_options`, `background_export`, `override_check` import neither
  pygame nor moderngl; `asset_resolver` touches pygame only in
  `load_png_rgb`; `render_soft` never imports moderngl; `render_gl` owns
  moderngl; `render.py` owns the window.
- `games/` may import `engine/` only.
- `app/` may import everything.
- `tools/` may import anything; `tools/regenerate_backgrounds.py` remains the
  only module allowed to import `google.genai`.

The existing pygame-free assertion in `tests/test_playworld.py` and the
scene/geometry purity checks are folded into this test so there is one
place the rules live.

## Invariants

- Every existing test passes with imports rewritten and nothing else.
- Golden values, do-not-fix quirks, `ponytail:` comments, and FITD
  `file:line` citations move verbatim.
- `make` targets, CLI flags, `SDL_VIDEODRIVER=dummy` proof suites, settings
  file format, and the override directory layout are unchanged.
- `# SPDX-License-Identifier: GPL-2.0-only` stays the first line of every
  Python file, including new `__init__.py` files.
- `AGENTS.md` and `CONTEXT.md` layer sections are rewritten to name packages
  instead of files; the architecture table gains the package column.

## Sequencing

Each step ends with `.venv/bin/pytest -q && make prove` green and is its own
commit, so a failure is always attributable to one move:

1. `engine/` moves (pure `git mv` + import rewrite).
2. `render/` moves.
3. `app/` moves; `__main__.py` becomes the one-line re-export.
4. `games/aitd1/` moves for `life_ops`, `life_reduced`, `scenario`,
   `mouse_contract`.
5. `tests/test_layering.py` added and green.
6. `GameProfile` extraction: `base.py`, `aitd1/profile.py`, the `Assets` /
   `Game` signature changes, and removal of the module-level constants —
   the only step that changes call signatures, kept small and reviewable.
7. Docs (`AGENTS.md`, `CONTEXT.md`, `README.md` if any path is quoted).

## Out of scope

Any second game, any new opcode semantics, save/load (M4a2), audio (M4b),
and any renaming of functions or classes beyond what the moves require.
