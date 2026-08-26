# Engine Package Reorganization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the flat `PyAitD/` package into `engine/`, `render/`, `games/aitd1/`, and `app/`, and move every AITD1-specific constant into one `GameProfile`, with zero behavior change.

**Architecture:** Each task is a `git mv` batch plus one scripted import rewrite over `PyAitD/`, `tests/`, and `tools/`, gated by the full test suite. The last code task replaces module-level AITD1 constants (PAK names, hero archives, CVar names, the filled LIFE opcode table, reduced dispatch, debug venues) with a frozen `GameProfile` dataclass that `Assets`, `Game`, and the VM read at runtime. A final AST-based layering test pins the package rules.

**Tech Stack:** Python 3.12, pytest, `ast` (stdlib). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-26-engine-package-reorganization-design.md`

## Global Constraints

- `# SPDX-License-Identifier: GPL-2.0-only` is the first line of every Python file, including every new `__init__.py`.
- Dependencies fixed: pygame-ce, ModernGL, NumPy, pytest; optional extra `ai` (`google-genai`) imported only inside `tools/regenerate_backgrounds.make_client`. Add nothing.
- Every move is `git mv`; no compatibility shims; old `PyAitD.<module>` names disappear.
- Test file names and test function names do not change. Golden values, do-not-fix quirks, `ponytail:` comments, and FITD `file:line` citations move verbatim.
- `make` targets, CLI flags (`python -m PyAitD ...`), `SDL_VIDEODRIVER=dummy` proof suites, settings file format, and the override directory layout are unchanged.
- Gate after every task: `.venv/bin/pytest -q && make prove` green. Any test touching rendering/pygame needs `SDL_VIDEODRIVER=dummy` (the Makefile sets it for the proof targets; `pytest -q` handles it per test).
- Never mass-reformat. No lint/typecheck is configured; the suite is the only gate.
- Two recorded deviations from the spec: (1) `boot_start` is not a profile field — the normal boot start is derived from the hero world object (`game.py` `init_game`, `FloorStart(hero.stage, ...)`), so there is nothing constant to hold; (2) the layering test is Task 7, after the `GameProfile` extraction in Task 6, because until Task 6 `engine/life.py` still imports `games/aitd1/life_ops.py` to fill its table.

---

## The import-rewrite helper

Every move task uses the same throwaway script. Create it once in the scratchpad (not in the repo) as `rewrite_imports.py`:

```python
# rewrite_imports.py  — usage: python rewrite_imports.py old1=new1 old2=new2 ...
# Rewrites `PyAitD.<old>` dotted names and `from PyAitD import <old>` in every
# .py under PyAitD/, tests/, tools/ (including inside string literals such as
# monkeypatch targets and the test_playworld purity probe).
import pathlib, re, sys

pairs = [a.split("=") for a in sys.argv[1:]]
roots = [pathlib.Path("PyAitD"), pathlib.Path("tests"), pathlib.Path("tools")]
for old, new in pairs:
    dotted = re.compile(rf"\bPyAitD\.{re.escape(old)}\b")
    bare = re.compile(rf"^(\s*from PyAitD import ){re.escape(old)}\b", re.M)
    for root in roots:
        for path in root.rglob("*.py"):
            src = path.read_text()
            out = dotted.sub(f"PyAitD.{new}", src)
            out = bare.sub(rf"\1{new}", out)  # temporary; fixed below
            if out != src:
                path.write_text(out)
# `from PyAitD import x as y` becomes `from PyAitD import pkg.x as y`, which is
# invalid; rewrite that form to `from PyAitD.pkg import x as y`.
fix = re.compile(r"^(\s*)from PyAitD import ([a-z_]+)\.([a-z_0-9]+)( as [a-z_]+)?$", re.M)
for root in roots:
    for path in root.rglob("*.py"):
        src = path.read_text()
        out = fix.sub(r"\1from PyAitD.\2 import \3\4", src)
        if out != src:
            path.write_text(out)
```

Run it from the repo root: `python /path/to/scratch/rewrite_imports.py life=engine.life ...`. After running, always `git diff --stat` and `grep -rn "from PyAitD import\b" PyAitD tests tools` to confirm nothing odd remains.

---

### Task 1: Move the engine core into `PyAitD/engine/`

**Files:**
- Create: `PyAitD/engine/__init__.py`
- Move (git mv): `PyAitD/{pak,explode,floor,formats,assets,world,cos_table,skel,mask,anim,actors,tracks,realvalue,eval_var,life,game,playworld,interaction,effects,anim_action,navmesh,picking,navigate,text}.py` → `PyAitD/engine/`
- Modify: every importer under `PyAitD/`, `tests/`, `tools/` (scripted)

**Interfaces:**
- Produces: module paths `PyAitD.engine.<name>` for the 24 modules above. Public names inside each module are unchanged.

- [ ] **Step 1: Confirm the baseline is green**

Run: `.venv/bin/pytest -q && make prove`
Expected: all pass (record the passed count; every later task must match it, plus any tests that task adds).

- [ ] **Step 2: Create the package and move the modules**

```bash
printf '# SPDX-License-Identifier: GPL-2.0-only\n"""Game-neutral engine core: formats, VM, actors, simulation tick. Imports no pygame, moderngl, render, games, or app."""\n' > PyAitD/engine/__init__.py
mkdir -p PyAitD/engine && mv PyAitD/engine/__init__.py PyAitD/engine/__init__.py 2>/dev/null
for m in pak explode floor formats assets world cos_table skel mask anim actors tracks realvalue eval_var life game playworld interaction effects anim_action navmesh picking navigate text; do git mv PyAitD/$m.py PyAitD/engine/$m.py; done
git add PyAitD/engine/__init__.py
```

- [ ] **Step 3: Rewrite imports**

```bash
python "$SCRATCH/rewrite_imports.py" pak=engine.pak explode=engine.explode floor=engine.floor formats=engine.formats assets=engine.assets world=engine.world cos_table=engine.cos_table skel=engine.skel mask=engine.mask anim=engine.anim actors=engine.actors tracks=engine.tracks realvalue=engine.realvalue eval_var=engine.eval_var life=engine.life game=engine.game playworld=engine.playworld interaction=engine.interaction effects=engine.effects anim_action=engine.anim_action navmesh=engine.navmesh picking=engine.picking navigate=engine.navigate text=engine.text
grep -rn "PyAitD\.\(pak\|explode\|floor\|formats\|assets\|world\|cos_table\|skel\|mask\|anim\|actors\|tracks\|realvalue\|eval_var\|life\|game\|playworld\|interaction\|effects\|anim_action\|navmesh\|picking\|navigate\|text\)\b" PyAitD tests tools
```
Expected: the final grep prints nothing. Note `life` must not have matched `life_ops`/`life_reduced` — the `\b` guards that; verify with `grep -rn "engine.life_ops\|engine.life_reduced" PyAitD tests tools` printing nothing.

- [ ] **Step 4: Fix the `_PURITY_PROBE` string in `tests/test_playworld.py`**

The rewrite already changed `PyAitD.playworld` and `PyAitD.anim_action` inside the probe string. Confirm:

```bash
grep -n "PURITY_PROBE" -A5 tests/test_playworld.py | grep import
```
Expected: `import sys, PyAitD.engine.playworld, PyAitD.engine.anim_action`.

- [ ] **Step 5: Run the gate**

Run: `.venv/bin/pytest -q && make prove`
Expected: same pass count as Step 1.

- [ ] **Step 6: Commit**

```bash
git add -A PyAitD tests tools
git commit -m "refactor: move the engine core into PyAitD/engine/"
```

---

### Task 2: Move the rendering layer into `PyAitD/render/`

**Files:**
- Create: `PyAitD/render/__init__.py`
- Move: `PyAitD/{scene,geometry,mask_geometry,asset_resolver,render_options,render_gl,render_soft,render,background_export,override_check}.py` → `PyAitD/render/`
- Modify: importers (scripted)

**Interfaces:**
- Produces: `PyAitD.render.<name>` for the 10 modules. Note `PyAitD.render.render` is the window/`Renderer` module.

- [ ] **Step 1: Create the package and move**

```bash
mkdir -p PyAitD/render
printf '# SPDX-License-Identifier: GPL-2.0-only\n"""Frame description and both backends. May import engine; never games or app."""\n' > PyAitD/render/__init__.py
for m in scene geometry mask_geometry asset_resolver render_options render_gl render_soft render background_export override_check; do git mv PyAitD/$m.py PyAitD/render/$m.py; done
git add PyAitD/render/__init__.py
```

- [ ] **Step 2: Rewrite imports** — order matters: `render_gl`, `render_soft`, `render_options` first so the bare `render` pattern (which is `\b`-guarded, so `render_gl` will not match it anyway) is unambiguous.

```bash
python "$SCRATCH/rewrite_imports.py" render_gl=render.render_gl render_soft=render.render_soft render_options=render.render_options scene=render.scene geometry=render.geometry mask_geometry=render.mask_geometry asset_resolver=render.asset_resolver background_export=render.background_export override_check=render.override_check render=render.render
grep -rn "PyAitD\.\(scene\|geometry\|mask_geometry\|asset_resolver\|render_options\|render_gl\|render_soft\|background_export\|override_check\)\b" PyAitD tests tools
grep -rn "PyAitD\.render\b[^.]" PyAitD tests tools
```
Expected: both greps print nothing (every `PyAitD.render` is now followed by a dot).

- [ ] **Step 3: Fix the purity-probe leak set in `tests/test_playworld.py`**

The probe's leak set was `{"PyAitD.ui", "PyAitD.render", ...}`; the rewrite turned it into `"PyAitD.render.render"`. Change that string to the package name so any render module counts as a leak:

```python
leaked = {"PyAitD.ui", "PyAitD.render.render", "pygame", "moderngl", "OpenGL"} & sys.modules.keys()
```
becomes
```python
leaked = {m for m in sys.modules if m == "PyAitD.ui" or m.startswith("PyAitD.render") or m in ("pygame", "moderngl", "OpenGL")}
```

- [ ] **Step 4: Run the gate**

Run: `.venv/bin/pytest -q && make prove`
Expected: same pass count as Task 1 Step 1.

- [ ] **Step 5: Commit**

```bash
git add -A PyAitD tests tools
git commit -m "refactor: move the rendering layer into PyAitD/render/"
```

---

### Task 3: Move the application shell into `PyAitD/app/` and `FoundResult` into `effects`

**Files:**
- Create: `PyAitD/app/__init__.py`
- Move: `PyAitD/ui.py` → `PyAitD/app/ui.py`; `PyAitD/config.py` → `PyAitD/app/config.py`; `PyAitD/__main__.py` → `PyAitD/app/shell.py`
- Create: new `PyAitD/__main__.py` (re-export)
- Modify: `PyAitD/engine/effects.py` (add `FoundResult`), `PyAitD/app/ui.py` (remove it, import it), `PyAitD/engine/interaction.py:387`, tests that import `FoundResult` from `ui`
- Modify: importers (scripted)

**Interfaces:**
- Produces: `PyAitD.app.shell.main(argv=None) -> int`, `PyAitD.app.shell.run(...)`, `PyAitD.app.ui`, `PyAitD.app.config`; `PyAitD.engine.effects.FoundResult` (Enum with `TAKE`, `LEAVE`).

- [ ] **Step 1: Move the three modules**

```bash
mkdir -p PyAitD/app
printf '# SPDX-License-Identifier: GPL-2.0-only\n"""Process shell: event pump, settings, UI presenters and reducers. May import everything."""\n' > PyAitD/app/__init__.py
git mv PyAitD/ui.py PyAitD/app/ui.py
git mv PyAitD/config.py PyAitD/app/config.py
git mv PyAitD/__main__.py PyAitD/app/shell.py
git add PyAitD/app/__init__.py
```

- [ ] **Step 2: Write the new `PyAitD/__main__.py`**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""`python -m PyAitD` entry point; the shell lives in PyAitD.app.shell."""
from PyAitD.app.shell import main

if __name__ == "__main__":
    raise SystemExit(main())
```

Then delete the trailing `if __name__ == "__main__": raise SystemExit(main())` block at the end of `PyAitD/app/shell.py` (it is the last three lines of the file) so the entry point exists in exactly one place.

- [ ] **Step 3: Rewrite imports**

```bash
python "$SCRATCH/rewrite_imports.py" ui=app.ui config=app.config __main__=app.shell
grep -rn "PyAitD\.\(ui\|config\|__main__\)\b" PyAitD tests tools
```
Expected: nothing. Tests that did `from PyAitD import __main__ as m` or `import PyAitD.__main__` now read `from PyAitD.app import shell as m` / `import PyAitD.app.shell`; check with `grep -rn "app.shell" tests | head` and fix any `PyAitD.app.shell` used as an attribute chain on a bare `import PyAitD` (there are none expected; the grep confirms).

- [ ] **Step 4: Move `FoundResult` to `effects.py`**

In `PyAitD/engine/effects.py`, after `class GameMode`, add:

```python
class FoundResult(Enum):
    # the Take/Leave prompt's answer; consumed by interaction.apply_found_result
    TAKE = auto()
    LEAVE = auto()
```

In `PyAitD/app/ui.py` delete the `class FoundResult(Enum): TAKE/LEAVE` definition (lines ~172-175) and add `FoundResult` to the module's existing `from PyAitD.engine.effects import ...` line so `ui.FoundResult` still resolves for the reducers.

In `PyAitD/engine/interaction.py` replace the deferred import at line ~387:
```python
    from PyAitD.app.ui import FoundResult
```
with a top-level import: add `FoundResult` to the module's existing `from PyAitD.engine.effects import ...` line and delete the deferred line.

Then update the tests that import it from `ui`:
```bash
grep -rln "from PyAitD.app.ui import .*FoundResult" tests
```
For each hit, move `FoundResult` out of that import and add `from PyAitD.engine.effects import FoundResult` (these are `test_m3b_attic.py`, `test_modal_results.py`, `test_playworld.py`, `test_runtime_modes.py`, `test_ui_mouse.py`, `test_ui_reducers.py`, `test_ui_render.py`; any that use `ui.FoundResult` as an attribute keep working).

- [ ] **Step 5: Fix the purity-probe leak set again**

In `tests/test_playworld.py` the leak set names `"PyAitD.ui"`; it is now `"PyAitD.app.ui"`. Make the probe treat the whole app package as a leak:

```python
leaked = {m for m in sys.modules if m.startswith(("PyAitD.app", "PyAitD.render")) or m in ("pygame", "moderngl", "OpenGL")}
```

Also delete the now-stale comment above `_PURITY_PROBE` that says a static walk "reports pygame reachable through interaction.apply_found_result's deferred `from PyAitD.ui import FoundResult`" — that import no longer exists. Keep the sentence about pygame being loaded in-process.

- [ ] **Step 6: Run the gate, including the entry point**

```bash
.venv/bin/pytest -q && make prove
SDL_VIDEODRIVER=dummy .venv/bin/python -m PyAitD --help | head -3
```
Expected: same pass count; `--help` prints the usage line.

- [ ] **Step 7: Commit**

```bash
git add -A PyAitD tests tools
git commit -m "refactor: move ui/config/shell into PyAitD/app/; FoundResult lives in effects"
```

---

### Task 4: Move AITD1-specific modules into `PyAitD/games/aitd1/` and `init_anim` into the engine

**Files:**
- Create: `PyAitD/games/__init__.py`, `PyAitD/games/aitd1/__init__.py`
- Move: `PyAitD/{life_ops,life_reduced,scenario,mouse_contract}.py` → `PyAitD/games/aitd1/`
- Modify: `PyAitD/engine/anim.py` (add `ANIM_ONCE`, `ANIM_REPEAT`, `ANIM_UNINTERRUPTABLE`, `init_anim`), `PyAitD/games/aitd1/life_ops.py`, `PyAitD/games/aitd1/life_reduced.py`, `PyAitD/engine/{actors,interaction,playworld}.py`, tests importing `ANIM_*`/`init_anim` from `life_ops`
- Modify: importers (scripted)

**Interfaces:**
- Produces: `PyAitD.engine.anim.init_anim(actor, anim_num, anim_type, anim_info) -> int` and `PyAitD.engine.anim.ANIM_ONCE = 0`, `ANIM_REPEAT = 1`, `ANIM_UNINTERRUPTABLE = 2`; module paths `PyAitD.games.aitd1.{life_ops,life_reduced,scenario,mouse_contract}`.
- Consumes: `PyAitD.engine.game.AF_ANIMATED`.

- [ ] **Step 1: Create packages and move**

```bash
mkdir -p PyAitD/games/aitd1
printf '# SPDX-License-Identifier: GPL-2.0-only\n"""Per-game profiles. May import engine only."""\n' > PyAitD/games/__init__.py
printf '# SPDX-License-Identifier: GPL-2.0-only\n"""Alone in the Dark 1 (DOS, 1992): opcode handlers, reduced dispatch, debug venues, mouse contract."""\n' > PyAitD/games/aitd1/__init__.py
for m in life_ops life_reduced scenario mouse_contract; do git mv PyAitD/$m.py PyAitD/games/aitd1/$m.py; done
git add PyAitD/games
python "$SCRATCH/rewrite_imports.py" life_ops=games.aitd1.life_ops life_reduced=games.aitd1.life_reduced scenario=games.aitd1.scenario mouse_contract=games.aitd1.mouse_contract
grep -rn "PyAitD\.\(life_ops\|life_reduced\|scenario\|mouse_contract\)\b" PyAitD tests tools
```
Expected: nothing.

- [ ] **Step 2: Write the failing test for `init_anim` in the engine**

Append to `tests/test_anim_player.py`:

```python
def test_init_anim_lives_in_the_engine():
    # engine modules (actors, interaction, playworld) call init_anim; it must
    # not live in the game-specific opcode module or the engine would import games
    from PyAitD.engine.anim import ANIM_REPEAT, ANIM_UNINTERRUPTABLE, init_anim
    from PyAitD.engine.game import AF_ANIMATED, Actor
    actor = Actor()
    assert init_anim(actor, 3, ANIM_REPEAT, -1) == 1
    assert actor.object_type & AF_ANIMATED and actor.new_anim == 3
    actor.new_anim_type = ANIM_UNINTERRUPTABLE
    assert init_anim(actor, 4, ANIM_REPEAT, -1) == 0
```

Run: `.venv/bin/pytest tests/test_anim_player.py::test_init_anim_lives_in_the_engine -q`
Expected: FAIL with `ImportError: cannot import name 'init_anim' from 'PyAitD.engine.anim'`.

- [ ] **Step 3: Move `init_anim` and the `ANIM_*` constants**

Cut lines `ANIM_ONCE = 0` … end of `def init_anim` (the three constants and the whole function, with its `# anim.cpp:51 InitAnim` comment) out of `PyAitD/games/aitd1/life_ops.py` and paste them verbatim into `PyAitD/engine/anim.py` below its imports. `init_anim` needs `AF_ANIMATED`: add `from PyAitD.engine.game import AF_ANIMATED` to `anim.py` **only if** `anim.py` does not already import `game` — check `grep -n "^from\|^import" PyAitD/engine/anim.py` first; if `game.py` imports `anim.py` at module level (circular), instead place the deferred `from PyAitD.engine.game import AF_ANIMATED` inside `init_anim`'s body, matching how `actors.py:253` already defers imports.

In `life_ops.py` add `from PyAitD.engine.anim import ANIM_ONCE, ANIM_REPEAT, ANIM_UNINTERRUPTABLE, init_anim` (the module uses all four). In `life_reduced.py` replace its local `ANIM_ONCE = 0` / `ANIM_REPEAT = 1` with `from PyAitD.engine.anim import ANIM_ONCE, ANIM_REPEAT` and keep `ANIM_ALL_ONCE = ANIM_ONCE | 2` local.

Rewrite the engine's deferred imports:
```bash
grep -rn "from PyAitD.games.aitd1.life_ops import init_anim" PyAitD/engine
```
Expected three hits (`actors.py`, `interaction.py`, `playworld.py`); change each to `from PyAitD.engine.anim import init_anim`.

Rewrite tests:
```bash
grep -rn "life_ops import .*ANIM_\|life_ops.init_anim" tests
```
Change `from PyAitD.games.aitd1.life_ops import ANIM_REPEAT, ANIM_UNINTERRUPTABLE` (in `test_interaction.py`, `test_playworld.py`) to import from `PyAitD.engine.anim`. In `tests/test_life_ops.py` the monkeypatch strings `"PyAitD.games.aitd1.life_ops.init_anim"` must stay pointed at the name the ops module *looks up*: because `life_ops` now does `from PyAitD.engine.anim import init_anim`, the patched name is still `PyAitD.games.aitd1.life_ops.init_anim` — leave those strings as the rewrite produced them. But `actors.py`/`interaction.py`/`playworld.py` now look the name up in `PyAitD.engine.anim`; grep the tests for monkeypatches meant for those callers:
```bash
grep -rn "monkeypatch.setattr(\"PyAitD" tests | grep init_anim
```
For any test whose subject is `actors`/`interaction`/`playworld` (not `life_ops`), change the target to `"PyAitD.engine.anim.init_anim"`.

- [ ] **Step 4: Run the new test, then the gate**

Run: `.venv/bin/pytest tests/test_anim_player.py::test_init_anim_lives_in_the_engine -q` → PASS.
Run: `.venv/bin/pytest -q && make prove` → previous pass count + 1.

- [ ] **Step 5: Commit**

```bash
git add -A PyAitD tests tools
git commit -m "refactor: AITD1 opcode handlers, venues, mouse contract under games/aitd1; init_anim in engine.anim"
```

---

### Task 5: `GameProfile` dataclass and the AITD1 profile (no consumers yet)

**Files:**
- Create: `PyAitD/games/base.py`, `PyAitD/games/aitd1/profile.py`, `tests/test_game_profile.py`
- Modify: `PyAitD/games/__init__.py` (registry), `PyAitD/engine/life.py` (expose `core_table()`)

**Interfaces:**
- Produces:
  ```python
  # PyAitD/games/base.py
  @dataclass(frozen=True)
  class GameProfile:
      name: str
      lifes_pak: str
      tracks_pak: str
      text_pak: str
      resource_pak: str
      heroes: tuple[tuple[str, str], ...]   # (body_archive, anim_archive) per hero index
      cvar_names: tuple[str, ...]
      defines_big_endian: bool
      opcode_table: tuple                    # 87 callables (vm) -> None for AITD1
      dead_opcodes: frozenset[int]
      reduced_dispatch: object               # callable (vm, opcode, world_idx)
      debug_venues: Mapping[str, object]     # name -> callable(game)
      def cvar_index(self, name: str) -> int
      def hero_archives(self, hero: int) -> tuple[str, str]   # raises ValueError out of range
  # PyAitD/games/aitd1/profile.py
  AITD1: GameProfile
  # PyAitD/games/__init__.py
  PROFILES: dict[str, GameProfile]; load_profile(name: str) -> GameProfile
  # PyAitD/engine/life.py
  core_table() -> list   # 87 slots: control flow / var / chrono / switch ops filled, dead + unimplemented placeholders elsewhere
  ```

- [ ] **Step 1: Write the failing tests**

`tests/test_game_profile.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""GameProfile holds every AITD1-specific constant the engine reads."""
import dataclasses

import pytest

from PyAitD.games import PROFILES, load_profile
from PyAitD.games.aitd1.profile import AITD1
from PyAitD.games.base import GameProfile


def test_aitd1_profile_is_registered():
    assert load_profile("aitd1") is AITD1
    assert PROFILES == {"aitd1": AITD1}
    with pytest.raises(KeyError):
        load_profile("aitd2")


def test_aitd1_profile_pins_the_pak_and_hero_names():
    assert (AITD1.lifes_pak, AITD1.tracks_pak, AITD1.text_pak, AITD1.resource_pak) == (
        "LISTLIFE", "LISTTRAK", "ENGLISH", "ITD_RESS"
    )
    assert AITD1.hero_archives(0) == ("LISTBODY", "LISTANIM")
    assert AITD1.hero_archives(1) == ("LISTBOD2", "LISTANI2")
    with pytest.raises(ValueError):
        AITD1.hero_archives(2)


def test_aitd1_cvars_and_defines():
    assert len(AITD1.cvar_names) == 16
    assert AITD1.cvar_index("CHOOSE_PERSO") == 8
    assert AITD1.cvar_index("FOG_FLAG") == 14
    assert AITD1.defines_big_endian is True


def test_aitd1_opcode_table_is_complete_and_immutable():
    # AITD1LifeMacroTable (AITD1.cpp:30-119): 87 entries; dead slots raise
    assert len(AITD1.opcode_table) == 87
    assert AITD1.dead_opcodes == frozenset({27, 57, 61, 69})
    assert all(callable(h) for h in AITD1.opcode_table)
    assert not any(h.__qualname__.startswith("_op_not_implemented") for h in AITD1.opcode_table)
    assert dataclasses.is_dataclass(GameProfile) and GameProfile.__dataclass_params__.frozen
    with pytest.raises(dataclasses.FrozenInstanceError):
        AITD1.name = "x"


def test_aitd1_debug_venues_and_reduced_dispatch():
    from PyAitD.games.aitd1 import life_reduced, scenario
    assert AITD1.reduced_dispatch is life_reduced.reduced_dispatch
    assert AITD1.debug_venues == {
        "combat-venue": scenario.enter_combat_venue,
        "mouse-combat-fixture": scenario.enter_mouse_combat_fixture,
    }
```

Run: `.venv/bin/pytest tests/test_game_profile.py -q`
Expected: FAIL with `ImportError` (no `PyAitD.games.base`).

- [ ] **Step 2: Expose `core_table()` in `engine/life.py`**

Replace the module-level table construction (from `LIFETABLE = [_op_not_implemented(i) for i in range(87)]` through the `_install_handlers()` call and the trailing "slot left unimplemented" loop) with:

```python
# AITD1LifeMacroTable (AITD1.cpp:30-119, life.h:7-93): 87 entries, index == enum value.
# The engine fills only the game-neutral slots; a GameProfile installs the rest.
NUM_OPCODES = 87


def core_table():
    table = [_op_not_implemented(i) for i in range(NUM_OPCODES)]
    table[4] = _make_if(lambda a, b: a == b)   # LM_IF_EGAL
    table[5] = _make_if(lambda a, b: a != b)   # LM_IF_DIFFERENT
    table[6] = _make_if(lambda a, b: a >= b)   # LM_IF_SUP_EGAL
    table[7] = _make_if(lambda a, b: a > b)    # LM_IF_SUP
    table[8] = _make_if(lambda a, b: a <= b)   # LM_IF_INF_EGAL
    table[9] = _make_if(lambda a, b: a < b)    # LM_IF_INF
    table[10] = _op_goto                       # LM_GOTO
    table[11] = _op_end                        # LM_RETURN
    table[12] = _op_end                        # LM_END
    table[19] = _op_var                        # LM_VAR
    table[20] = _op_inc                        # LM_INC
    table[21] = _op_dec                        # LM_DEC
    table[22] = _op_add                        # LM_ADD
    table[23] = _op_sub                        # LM_SUB
    table[24] = _op_life_mode                  # LM_LIFE_MODE
    table[25] = _op_switch                     # LM_SWITCH
    table[26] = _op_case                       # LM_CASE
    table[27] = _op_dead                       # LM_CAMERA
    table[28] = _op_start_chrono               # LM_START_CHRONO
    table[29] = _op_multi_case                 # LM_MULTI_CASE
    table[57] = _op_dead                       # LM_STOP_BETA
    table[61] = _op_dead                       # LM_DO_NORMAL_ZV
    table[69] = _op_dead                       # LM_SPEED
    return table
```

Keep the existing per-slot comments exactly. **Temporarily** keep the old behaviour alive for this task only, so the suite stays green before consumers switch in Task 6: below `core_table()` add

```python
# ponytail: removed in the GameProfile switch-over (Task 6); until then the VM
# still dispatches through this module-level table.
def _install_handlers():
    from PyAitD.games.aitd1 import life_ops as ops
    from PyAitD.engine.tracks import process_track
    table = core_table()
    table[0] = lambda vm: process_track(vm.game, vm.actor)  # LM_DO_MOVE
    ... (the existing 63 `LIFETABLE[n] = ops.op_*` lines, each as `table[n] = ops.op_*`)
    return table


LIFETABLE = _install_handlers()
```

and leave `_dispatch` reading `LIFETABLE`. Do not yet touch `_dispatch_reduced`.

- [ ] **Step 3: Write `games/base.py`**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""GameProfile: the per-game constants the engine reads at runtime.

FITD branches on g_gameId in boot (main.cpp), opcode semantics (life.cpp),
getCVarsIdx, and a few format variants. Everything that is AITD1-specific
today lives here; nothing else is abstracted."""
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class GameProfile:
    name: str
    lifes_pak: str
    tracks_pak: str
    text_pak: str
    resource_pak: str
    heroes: tuple            # ((body_archive, anim_archive), ...) indexed by hero
    cvar_names: tuple
    defines_big_endian: bool
    opcode_table: tuple      # index == opcode; every slot callable(vm)
    dead_opcodes: frozenset  # slots whose handler raises (FITD dead macros)
    reduced_dispatch: object # callable(vm, opcode, world_idx): not-in-floor ops
    debug_venues: Mapping    # CLI venue name -> callable(game)

    def cvar_index(self, name):
        return self.cvar_names.index(name)

    def hero_archives(self, hero):
        if not 0 <= hero < len(self.heroes):
            raise ValueError(f"hero must be 0..{len(self.heroes) - 1}, got {hero}")
        return self.heroes[hero]
```

- [ ] **Step 4: Write `games/aitd1/profile.py`**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Alone in the Dark 1 profile: PAK names, hero archives, CVars, the filled
AITD1LifeMacroTable (AITD1.cpp:30-119), reduced dispatch, debug venues."""
from types import MappingProxyType

from PyAitD.engine import life
from PyAitD.engine.tracks import process_track
from PyAitD.games.aitd1 import life_ops as ops
from PyAitD.games.aitd1 import scenario
from PyAitD.games.aitd1.life_reduced import reduced_dispatch
from PyAitD.games.base import GameProfile

CVAR_NAMES = (
    "SAMPLE_PAGE", "BODY_FLAMME", "MAX_WEIGHT_LOADABLE", "TEXTE_CREDITS",
    "SAMPLE_TONNERRE", "INTRO_DETECTIVE", "INTRO_HERITIERE", "WORLD_NUM_PERSO",
    "CHOOSE_PERSO", "SAMPLE_CHOC", "SAMPLE_PLOUF", "REVERSE_OBJECT",
    "KILLED_SORCERER", "LIGHT_OBJECT", "FOG_FLAG", "DEAD_PERSO",
)

DEAD_OPCODES = frozenset({27, 57, 61, 69})  # LM_CAMERA, LM_STOP_BETA, LM_DO_NORMAL_ZV, LM_SPEED


def _opcode_table():
    # opcode numbers per AITD1LifeMacroTable (AITD1.cpp:30-119)
    table = life.core_table()
    table[0] = lambda vm: process_track(vm.game, vm.actor)  # LM_DO_MOVE
    table[1] = ops.op_anim_once
    table[2] = ops.op_anim_all_once
    table[3] = ops.op_body
    table[13] = ops.op_anim_repeat
    table[14] = ops.op_anim_move
    table[15] = ops.op_move
    table[16] = ops.op_hit
    table[17] = ops.op_message
    table[18] = ops.op_message_value
    table[30] = ops.op_found
    table[31] = ops.op_life
    table[32] = ops.op_delete
    table[33] = ops.op_take
    table[34] = ops.op_in_hand
    table[35] = ops.op_read
    table[36] = ops.op_anim_sample
    table[37] = ops.op_special
    table[38] = ops.op_do_real_zv
    table[39] = ops.op_sample
    table[40] = ops.op_type
    table[41] = ops.op_game_over
    table[42] = ops.op_manual_rot
    table[43] = ops.op_rnd_freq
    table[44] = ops.op_music
    table[45] = ops.op_set_beta
    table[46] = ops.op_do_rot_zv
    table[47] = ops.op_stage
    table[48] = ops.op_found_name
    table[49] = ops.op_found_flag
    table[50] = ops.op_found_life
    table[51] = ops.op_camera_target
    table[52] = ops.op_drop
    table[53] = ops.op_fire
    table[54] = ops.op_test_col
    table[55] = ops.op_found_body
    table[56] = ops.op_set_alpha
    table[58] = ops.op_do_max_zv
    table[59] = ops.op_put
    table[60] = ops.op_c_var
    table[62] = ops.op_do_carre_zv
    table[63] = ops.op_sample_then
    table[64] = ops.op_light
    table[65] = ops.op_shaking
    table[66] = ops.op_inventory
    table[67] = ops.op_found_weight
    table[68] = ops.op_up_coor_y
    table[70] = ops.op_put_at
    table[71] = ops.op_def_zv
    table[72] = ops.op_hit_object
    table[73] = ops.op_get_hard_clip
    table[74] = ops.op_angle
    table[75] = ops.op_rep_sample
    table[76] = ops.op_throw
    table[77] = ops.op_water
    table[78] = ops.op_picture
    table[79] = ops.op_stop_sample
    table[80] = ops.op_next_music
    table[81] = ops.op_fade_music
    table[82] = ops.op_stop_hit_object
    table[83] = ops.op_copy_angle
    table[84] = ops.op_end_sequence
    table[85] = ops.op_sample_then_repeat
    table[86] = ops.op_wait_game_over
    for i, h in enumerate(table):
        if h.__qualname__.startswith("_op_not_implemented"):
            raise RuntimeError(f"AITD1 opcode table slot {i} left unimplemented")
    return tuple(table)


AITD1 = GameProfile(
    name="aitd1",
    lifes_pak="LISTLIFE",
    tracks_pak="LISTTRAK",
    text_pak="ENGLISH",
    resource_pak="ITD_RESS",
    heroes=(("LISTBODY", "LISTANIM"), ("LISTBOD2", "LISTANI2")),
    cvar_names=CVAR_NAMES,
    defines_big_endian=True,
    opcode_table=_opcode_table(),
    dead_opcodes=DEAD_OPCODES,
    reduced_dispatch=reduced_dispatch,
    debug_venues=MappingProxyType({
        "combat-venue": scenario.enter_combat_venue,
        "mouse-combat-fixture": scenario.enter_mouse_combat_fixture,
    }),
)
```

The `table[n] = ops.op_*` lines are the 63 lines from `life.py`'s old `_install_handlers`, verbatim except `LIFETABLE` → `table`. Copy them from the git history (`git show HEAD~1:PyAitD/life.py`) rather than retyping.

- [ ] **Step 5: Write the registry in `games/__init__.py`**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Per-game profiles. May import engine only."""
from PyAitD.games.aitd1.profile import AITD1

PROFILES = {"aitd1": AITD1}


def load_profile(name):
    return PROFILES[name]
```

(`games/__init__` importing `games.aitd1.profile` is fine: `aitd1/profile.py` imports `PyAitD.games.base`, which does not import `PyAitD.games.__init__`'s names back. Python resolves `PyAitD.games` first, so verify with `.venv/bin/python -c "import PyAitD.games"`.)

- [ ] **Step 6: Run the new tests and the gate**

Run: `.venv/bin/pytest tests/test_game_profile.py -q` → 5 passed.
Run: `.venv/bin/pytest -q && make prove` → previous count + 5.

- [ ] **Step 7: Commit**

```bash
git add PyAitD/games PyAitD/engine/life.py tests/test_game_profile.py
git commit -m "feat: GameProfile dataclass and the AITD1 profile"
```

---

### Task 6: Switch `Assets`, `Game`, the VM, and the shell to the profile

**Files:**
- Modify: `PyAitD/engine/assets.py`, `PyAitD/engine/game.py`, `PyAitD/engine/life.py`, `PyAitD/app/shell.py`, `PyAitD/games/aitd1/life_ops.py` (KILLED_SORCERER), every `init_game(`/`Game(`/`Assets(` call site in `tests/` and `tools/` (scripted)
- Test: `tests/test_game.py`, `tests/test_assets.py`, `tests/test_life_vm.py`

**Interfaces:**
- Produces (the only API changes of the milestone):
  - `Assets(data_dir, profile, hero=0)`; attributes `body_archive_name`, `anim_archive_name` unchanged.
  - `Game(data_dir, profile, hero=0)`; new attribute `game.profile`.
  - `init_game(data_dir, profile, hero=0)`.
  - `life._dispatch` reads `vm.game.profile.opcode_table`; `_dispatch_reduced` calls `vm.game.profile.reduced_dispatch`.
  - `PyAitD.engine.life.LIFETABLE` and `_install_handlers` are deleted.
  - `PyAitD.engine.assets.{BODY_ARCHIVES,ANIM_ARCHIVES,BODIES_PAK,ANIMS_PAK,LIFES_PAK,TRACKS_PAK,TEXT_PAK,RESOURCE_PAK}` and `PyAitD.engine.game.{AITD1_CVAR_NAMES,FOG_FLAG}` are deleted; `GAME_PALETTE_ENTRY` stays (format constant, not game constant).
- Consumes: `PyAitD.games.aitd1.profile.AITD1`, `GameProfile.cvar_index`, `GameProfile.hero_archives`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_assets.py`:

```python
def test_assets_reads_archive_names_from_the_profile(data_dir):
    from PyAitD.engine.assets import Assets
    from PyAitD.games.aitd1.profile import AITD1
    emily = Assets(data_dir, AITD1, hero=1)
    assert (emily.body_archive_name, emily.anim_archive_name) == ("LISTBOD2", "LISTANI2")
    with pytest.raises(ValueError):
        Assets(data_dir, AITD1, hero=2)
```

Append to `tests/test_game.py`:

```python
def test_game_carries_its_profile_and_sets_choose_perso_by_name(data_dir):
    from PyAitD.engine.game import Game
    from PyAitD.games.aitd1.profile import AITD1
    game = Game(data_dir, AITD1, hero=1)
    assert game.profile is AITD1
    assert game.cvars[AITD1.cvar_index("CHOOSE_PERSO")] == 1
```

Append to `tests/test_life_vm.py`:

```python
def test_vm_dispatches_through_the_game_profile():
    # a one-opcode profile proves the VM owns no table of its own
    from types import SimpleNamespace
    from PyAitD.engine import life
    from PyAitD.games.base import GameProfile
    seen = []
    table = life.core_table()
    table[0] = lambda vm: seen.append("hit")
    profile = GameProfile(
        name="stub", lifes_pak="", tracks_pak="", text_pak="", resource_pak="",
        heroes=(), cvar_names=(), defines_big_endian=True,
        opcode_table=tuple(table), dead_opcodes=frozenset(),
        reduced_dispatch=lambda vm, op, w: None, debug_venues={},
    )
    game = SimpleNamespace(profile=profile)
    vm = life.VM(b"", game, 0)
    life._dispatch(vm, 0)
    assert seen == ["hit"]
    assert not hasattr(life, "LIFETABLE")
```

Run: `.venv/bin/pytest tests/test_assets.py tests/test_game.py tests/test_life_vm.py -q`
Expected: the three new tests FAIL (`TypeError` on the constructors; `AssertionError` on `hasattr(life, "LIFETABLE")`).

- [ ] **Step 2: `assets.py`**

Delete the eight module constants `BODY_ARCHIVES` … `RESOURCE_PAK` (keep `GAME_PALETTE_ENTRY = 3`). Change the constructor head to:

```python
class Assets:
    def __init__(self, data_dir, profile, hero=0):
        self.profile = profile
        self.body_archive_name, self.anim_archive_name = profile.hero_archives(hero)
        self._bodies_pak = str(find_pak(data_dir, self.body_archive_name))
        self._anims_pak = str(find_pak(data_dir, self.anim_archive_name))
        self._lifes_pak = str(find_pak(data_dir, profile.lifes_pak))
        self._tracks_pak = str(find_pak(data_dir, profile.tracks_pak))
```
and further down `self._text_pak = str(find_pak(data_dir, profile.text_pak))`, `self._resource_pak = str(find_pak(data_dir, profile.resource_pak))`. Error strings such as `"ENGLISH.PAK: text ... not found"` stay verbatim — they are user-facing messages pinned by tests. Check for any other module using the deleted constants:
```bash
grep -rn "BODY_ARCHIVES\|ANIM_ARCHIVES\|BODIES_PAK\|ANIMS_PAK\|LIFES_PAK\|TRACKS_PAK\|TEXT_PAK\|RESOURCE_PAK" PyAitD tests tools
```
Rewrite each hit to the profile attribute (`AITD1.lifes_pak` etc. in tests; `game.profile.<x>` / `assets.profile.<x>` in code).

- [ ] **Step 3: `game.py`**

Delete `AITD1_CVAR_NAMES` and `FOG_FLAG`. Change `Game.__init__`:

```python
class Game:
    def __init__(self, data_dir, profile, hero=0):
        self.profile = profile
        self._data_dir = data_dir
        self._rooms_by_floor = {}
        self.assets = Assets(data_dir, profile, hero=hero)
        self.world_objects = parse_objets((data_dir / "OBJETS.ITD").read_bytes())
        self.actors = [Actor() for _ in range(NUM_MAX_OBJECT)]
        self.cvars = parse_defines((data_dir / "DEFINES.ITD").read_bytes(), big_endian=profile.defines_big_endian)
        self.cvars[profile.cvar_index("CHOOSE_PERSO")] = hero  # startGame backs up and restores it
```

`parse_defines` in `formats.py` currently hardcodes big-endian; give it a keyword `big_endian=True` that selects `">h"` vs `"<h"` (read the function first — it is a `struct` loop; add the parameter without changing the default path). Change `init_game`:

```python
def init_game(data_dir, profile, hero=0):
    from PyAitD.engine.interaction import sync_player_track_mode  # interaction imports game
    game = Game(data_dir, profile, hero=hero)
```

Then grep for other users of the deleted names and of raw CVar indices:
```bash
grep -rn "AITD1_CVAR_NAMES\|FOG_FLAG\|cvars\[8\]\|cvars\[12\]\|cvars\[14\]" PyAitD tests tools
```
`shell.py:~799` `hero = old_game.cvars[8]` becomes `hero = old_game.cvars[old_game.profile.cvar_index("CHOOSE_PERSO")]`. `life_ops.py` `KILLED_SORCERER = 12` stays (it is inside `games/aitd1`, where AITD1 numbers are allowed) but change its definition to `KILLED_SORCERER = CVAR_NAMES.index("KILLED_SORCERER")` importing `CVAR_NAMES` from `PyAitD.games.aitd1.profile` **only if** that does not create an import cycle (`profile.py` imports `life_ops`); if it does, leave the literal `12` with the comment `# CVAR_NAMES.index("KILLED_SORCERER"); literal to avoid importing profile.py, which imports this module`.

- [ ] **Step 4: `life.py`**

Delete `_install_handlers` and `LIFETABLE`. Rewrite the two dispatchers:

```python
def _dispatch(vm, op):
    table = vm.game.profile.opcode_table
    idx = op & 0x7FFF
    if idx >= len(table):
        raise ValueError(
            f"opcode {idx} out of range 0..{len(table) - 1} "
            f"(life of actor {vm.owner_idx}, byte {vm.pc - 2})"
        )
    table[idx](vm)


def _dispatch_reduced(vm, op, world_idx):
    # world-object-field ops on game.world_objects[world_idx]
    vm.game.profile.reduced_dispatch(vm, op & 0x7FFF, world_idx)
```

Check tests that reached into the old table:
```bash
grep -rn "LIFETABLE\|_install_handlers" PyAitD tests tools
```
Rewrite each test hit to `AITD1.opcode_table` (read-only tuple; a test that *assigned* a slot must build a stub profile as in the Step 1 VM test and pass a game with that profile).

- [ ] **Step 5: `shell.py` — profile selection and venues**

At the top of `PyAitD/app/shell.py` add `from PyAitD.games import load_profile`. In `main()`:

```python
    profile = load_profile("aitd1")
    try:
        game = init_game(args.data, profile, hero=args.hero)
```
Replace the two venue branches with the profile mapping:
```python
    if args.mouse_combat_fixture:
        profile.debug_venues["mouse-combat-fixture"](game)
    elif args.combat_venue:
        profile.debug_venues["combat-venue"](game)
```
and remove the now-unused `from PyAitD.games.aitd1.scenario import enter_combat_venue, enter_mouse_combat_fixture` import if nothing else in `shell.py` uses those names (grep). Every other `init_game(` in `shell.py` (`~804`, `~826`) passes `old_game.profile` / `game.profile` as the second argument.

- [ ] **Step 6: Rewrite the test and tool call sites (scripted)**

```python
# rewrite_init_game.py — run from repo root
import pathlib, re
pat = re.compile(r"\b(init_game|Game|Assets)\((data_dir|data|args\.data|game\._data_dir)\b(?!, (AITD1|profile|old_game\.profile|game\.profile))")
imp = "from PyAitD.games.aitd1.profile import AITD1\n"
for path in list(pathlib.Path("tests").glob("*.py")) + list(pathlib.Path("tools").glob("*.py")):
    src = path.read_text()
    out = pat.sub(r"\1(\2, AITD1", src)
    if out != src:
        if imp not in out:
            # insert after the last top-level `from PyAitD...` import
            lines = out.splitlines(keepends=True)
            idx = max(i for i, l in enumerate(lines) if l.startswith("from PyAitD") or l.startswith("import PyAitD"))
            lines.insert(idx + 1, imp)
            out = "".join(lines)
        path.write_text(out)
```
Then hand-check the few non-matching shapes the earlier survey found — `def spy_init_game(data, hero=0)` / `real_init_game(data, hero=hero)` wrappers in `tests/test_main.py`-style tests must accept and forward `profile` positionally: `def spy_init_game(data, profile, hero=0)` and `real_init_game(data, profile, hero=hero)`. Confirm no stragglers:
```bash
grep -rn "init_game(\|[^_a-z]Game(\|Assets(" tests tools PyAitD | grep -v "AITD1\|profile\|def \|class \|_Game(\|_NavGame(\|#"
```
Expected: nothing.

- [ ] **Step 7: Run the gate**

Run: `.venv/bin/pytest -q && make prove && make prove-combat && SDL_VIDEODRIVER=dummy .venv/bin/python -m PyAitD --help >/dev/null`
Expected: previous count + 3; `prove-combat` and `--help` succeed (they exercise `debug_venues` and `load_profile`).

- [ ] **Step 8: Commit**

```bash
git add -A PyAitD tests tools
git commit -m "refactor: Assets, Game, the VM and the shell read AITD1 constants from GameProfile"
```

---

### Task 7: Layering test

**Files:**
- Create: `tests/test_layering.py`
- Modify: `tests/test_background_export.py:79-80`, `tests/test_override_check.py:107` (delete the per-module `"import pygame" not in src` assertions now covered here; keep everything else in those tests)

**Interfaces:**
- Consumes: package layout from Tasks 1-6.

- [ ] **Step 1: Write the test**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Package rules from docs/superpowers/specs/2026-08-26-engine-package-reorganization-design.md.

engine/  imports no pygame, moderngl, render, games, app
render/  imports engine only (never games or app); its pure modules import neither pygame nor moderngl
games/   imports engine only
app/     may import everything
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "PyAitD"

FORBIDDEN = {
    "engine": ("pygame", "moderngl", "PyAitD.render", "PyAitD.games", "PyAitD.app"),
    "render": ("PyAitD.games", "PyAitD.app"),
    "games": ("pygame", "moderngl", "PyAitD.render", "PyAitD.app"),
    "app": (),
}
# render modules that must stay free of both graphics libraries
PURE_RENDER = ("scene", "geometry", "mask_geometry", "render_options", "background_export", "override_check")
NO_MODERNGL = ("render_soft", "asset_resolver")


def _imports(path):
    """Every dotted name imported anywhere in the module, deferred imports included."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            base = node.module
            yield base
            for alias in node.names:
                yield f"{base}.{alias.name}"


def _modules(package):
    return sorted((ROOT / package).rglob("*.py"))


@pytest.mark.parametrize("package", sorted(FORBIDDEN))
def test_package_imports_only_what_the_layering_allows(package):
    bad = []
    for path in _modules(package):
        for name in _imports(path):
            if name.startswith(FORBIDDEN[package]):
                bad.append(f"{path.relative_to(ROOT)}: {name}")
    assert not bad, "\n".join(bad)


@pytest.mark.parametrize("module", PURE_RENDER)
def test_pure_render_modules_import_no_graphics_library(module):
    names = set(_imports(ROOT / "render" / f"{module}.py"))
    assert not any(n.startswith(("pygame", "moderngl")) for n in names), names


@pytest.mark.parametrize("module", NO_MODERNGL)
def test_software_side_never_imports_moderngl(module):
    names = set(_imports(ROOT / "render" / f"{module}.py"))
    assert not any(n.startswith("moderngl") for n in names), names


def test_asset_resolver_touches_pygame_in_exactly_one_function():
    tree = ast.parse((ROOT / "render" / "asset_resolver.py").read_text())
    owners = set()
    for func in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        for node in ast.walk(func):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
                if any(m and m.startswith("pygame") for m in mods):
                    owners.add(func.name)
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not any(
        (isinstance(n, ast.Import) and any(a.name.startswith("pygame") for a in n.names))
        or (isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("pygame"))
        for n in top
    ), "pygame must not be imported at module scope"
    assert owners == {"load_png_rgb"}, owners


def test_only_the_regeneration_tool_imports_google_genai():
    tools = pathlib.Path(__file__).resolve().parents[1] / "tools"
    hits = {
        p.name for p in list(tools.glob("*.py")) + list(ROOT.rglob("*.py"))
        if any(n.startswith("google") for n in _imports(p))
    }
    assert hits == {"regenerate_backgrounds.py"}, hits


def test_every_python_file_starts_with_the_spdx_line():
    repo = ROOT.parent
    missing = [
        str(p.relative_to(repo))
        for d in ("PyAitD", "tests", "tools")
        for p in (repo / d).rglob("*.py")
        if p.read_text().splitlines()[:1] != ["# SPDX-License-Identifier: GPL-2.0-only"]
    ]
    assert not missing, missing
```

- [ ] **Step 2: Run it and fix what it finds**

Run: `.venv/bin/pytest tests/test_layering.py -q`
Expected: PASS if Tasks 1-6 were done as written. If `engine` fails on a deferred import you missed, the message names `file: dotted.name` — resolve it by moving the imported symbol down a layer (as `FoundResult` and `init_anim` were), never by whitelisting.

- [ ] **Step 3: Remove the now-duplicated source-text checks**

In `tests/test_background_export.py` delete lines 79-80 (`assert "import pygame" not in src ...` and `assert not any(name in vars(be) ...)`); in `tests/test_override_check.py` delete line 107's `assert "import pygame" not in src and "import moderngl" not in src`. If a deleted line was the only statement in its test function, delete that test function too. `tests/test_playworld.py`'s subprocess probe stays — it is a runtime check the AST scan cannot replace.

- [ ] **Step 4: Run the gate**

Run: `.venv/bin/pytest -q && make prove`
Expected: previous count + 10 new − however many single-assert tests Step 3 removed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_layering.py tests/test_background_export.py tests/test_override_check.py
git commit -m "test: package layering rules for engine/render/games/app"
```

---

### Task 8: Documentation

**Files:**
- Modify: `AGENTS.md` (Conventions), `CONTEXT.md` (Architecture table, layer sections), `README.md` (only if it quotes a module path — check with `grep -n "PyAitD/" README.md`)

- [ ] **Step 1: `AGENTS.md`**

Replace the "Layer boundary" and "Graphics layering" bullets under Conventions with:

```markdown
- Package layering (`tests/test_layering.py` enforces it): `PyAitD/engine/`
  imports no pygame, moderngl, `render`, `games`, or `app`; `render/` imports
  `engine` only; `games/` imports `engine` only; `app/` may import everything.
  `__main__.py` owns nothing but the re-export of `app.shell.main`.
- Game-specific constants live in one `GameProfile`
  (`games/base.py`; `games/aitd1/profile.py` is the only instance): PAK names,
  hero archives, CVar names, DEFINES endianness, the filled opcode table,
  dead opcodes, reduced dispatch, debug venues. `Assets`, `Game`, the VM and
  the shell read them from `game.profile` — never re-add module constants.
- Inside `render/`: `scene`, `geometry`, `mask_geometry`, `render_options`,
  `background_export`, `override_check` import neither pygame nor moderngl;
  `asset_resolver` touches pygame in exactly one function (`load_png_rgb`);
  `render_soft` uses `pygame.draw` but never moderngl; `render_gl` owns all
  moderngl; `render` owns the window and both. `scene.build_frame` returns an
  immutable `FrameDescription` whose `palette` and `background.pixels` alias
  shared decode caches — read them, never write.
- `app/ui.py` never mutates world/actor/inventory/LIFE state; `app/config.py`
  is pygame-free settings schema/persistence; `app/shell.py` owns the single
  event pump, the settings lifecycle, game/floor replacement, and one present
  per frame. Settings live on `ModalSession`, never `Game`.
```

Update the two remaining path mentions: `tools/regenerate_backgrounds.py` bullet stays; the "Held mouse actions" bullet's `tests/test_mouse_only.py` stays. Update the Commands block's `make run` line if it named `__main__` (it does not).

- [ ] **Step 2: `CONTEXT.md`**

In "Architecture (PyAitD/)" prefix each module row with its package (`engine/pak.py`, `render/scene.py`, `games/aitd1/life_ops.py`, `app/ui.py`, …), add rows:

```markdown
| `games/base.py` | `GameProfile`: PAK names, hero archives, CVar names, DEFINES endianness, opcode table, dead opcodes, reduced dispatch, debug venues |
| `games/aitd1/profile.py` | The AITD1 instance; `games/__init__.load_profile("aitd1")` |
| `app/shell.py` | The process shell formerly in `__main__.py`; `__main__.py` is now a one-line re-export |
```

and rewrite the "M3b interaction boundary" and "M4a1 shell boundary" bullets that name `ui.py` / `__main__.py` / `effects.py` to their new paths. Add under "Fidelity notes": `FoundResult` moved from `ui.py` to `engine/effects.py` and `init_anim` from `life_ops.py` to `engine/anim.py` so the engine imports no game or app module. In "Where we are" add the row `| Engine package reorganization | engine / render / games / app split + GameProfile | done — tests/test_layering.py |`.

- [ ] **Step 3: Gate and commit**

Run: `.venv/bin/pytest -q && make prove`
```bash
git add AGENTS.md CONTEXT.md README.md
git commit -m "docs: package layering and GameProfile in AGENTS/CONTEXT"
```

---

## Self-review

- **Spec coverage:** layout (T1-T4), no shims + scripted rewrite (helper), `GameProfile` fields (T5; `boot_start` dropped, recorded), signature changes (T6), package rules test folding the old purity checks (T7), invariants (gate in every task, SPDX test in T7), docs (T8). Sequencing deviation (layering after profile) recorded in Global Constraints.
- **Placeholders:** the only elided block is the 63 `table[n] = ops.op_*` lines in T5 Step 4, which are enumerated in full in the same step's listing; T5 Step 2 says "the existing 63 lines" and points at the git history for verbatim copy.
- **Type consistency:** `GameProfile` field names (`lifes_pak`, `heroes`, `cvar_names`, `opcode_table`, `dead_opcodes`, `reduced_dispatch`, `debug_venues`) and methods (`cvar_index`, `hero_archives`) match across T5 tests, T5 implementation, T6 consumers, and T8 docs. `core_table()` is defined in T5 Step 2 and used in T5 Step 4 and T6 Step 1. `init_anim`/`ANIM_*` land in `engine.anim` in T4 and are imported from there in T4 and T6.
