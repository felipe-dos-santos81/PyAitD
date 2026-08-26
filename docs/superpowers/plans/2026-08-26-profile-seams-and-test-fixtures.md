# Profile Seams and Test Fixtures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the last two AITD1 hard-codes out of `PyAitD/engine/` into `GameProfile`, give `Game` a floor-loading seam, and finish two test-suite consolidations the engine package reorganization left open.

**Architecture:** Two new required `GameProfile` fields (`palette_entry`, `reduced_allowed`) replace module constants in `engine/floor.py`, `engine/assets.py` and `engine/life.py`. `Floor.__init__` takes the profile as a required third positional parameter; `Game.load_floor(number)` is a convenience for callers that hold a `Game`. Test-side: a `profile` fixture in `conftest.py` replaces 325 direct `AITD1` constructions, and six subprocess purity probes fold into one parametrized table in `tests/test_layering.py`.

**Tech Stack:** Python 3, pytest, pygame-ce, NumPy. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-26-profile-seams-and-test-fixtures-design.md`

## Global Constraints

- Every Python file's first line is exactly `# SPDX-License-Identifier: GPL-2.0-only`. Enforced by `tests/test_layering.py::test_every_python_file_starts_with_the_spdx_line`.
- Package layering is enforced by `tests/test_layering.py`: `engine/` imports no `pygame`, `moderngl`, `PyAitD.render`, `PyAitD.games`, `PyAitD.app`. Never import a profile into `engine/` — the engine reads game facts through `game.profile` / `vm.game.profile` only.
- Every test file carries exactly one subject marker (`engine`, `render`, `shell`, `tools`, `meta`) as a module-level `pytestmark`, plus optionally `journey`. Enforced by `tests/test_test_groups.py`. **This plan adds no markers and changes none.**
- Run the suite with `make test` (it sets `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`). A bare `pytest` invocation for a single test must be prefixed the same way — see each task's Run lines.
- Golden values, `ponytail:` comments and FITD `file:line` citations move **verbatim**. Never re-guess a pinned value; if one disagrees, trace it through `/Users/felipe.dos.santos/code/theirs/FITD/FitdLib/` and cite `file:line`.
- Game data is never committed. `data/aitd1/**` is git-ignored; `git add` only the files each task names.
- Every task ends with the full suite green. Baseline to match, measured at `3d8798c`: **1006 passed, 1 skipped, 1 xfailed**. Re-measure before starting Task 1 and use your own number if unrelated work landed first.

---

## File Structure

| file | responsibility after this plan |
|---|---|
| `PyAitD/games/base.py` | `GameProfile` — now also `palette_entry: int` and `reduced_allowed: frozenset` |
| `PyAitD/games/aitd1/profile.py` | AITD1's values, including the new `REDUCED_ALLOWED` module constant |
| `PyAitD/engine/floor.py` | floor loading; holds **no** AITD1 constants |
| `PyAitD/engine/assets.py` | asset registry; holds **no** palette entry constant |
| `PyAitD/engine/life.py` | VM; the reduced-dispatch guard stays here, its data does not |
| `PyAitD/engine/game.py` | `Game`, plus the new `load_floor` seam |
| `PyAitD/app/shell.py` | asks `game.load_floor(...)`; no longer imports `Floor` |
| `tests/conftest.py` | `data_dir`, `gl_ctx`, and the new `profile` fixture |
| `tests/test_layering.py` | the one place package rules live: static `ast` scan **and** the runtime purity probes |
| `tests/purity.py` | unchanged: `PRESENTATION` + `assert_presentation_free` helper |

---

### Task 1: `reduced_allowed` into `GameProfile`

Moves `engine/life.py`'s `_REDUCED_ALLOWED` set into the profile, beside the `reduced_dispatch` callable it belongs with. The guard and its error message stay in `engine/`.

**Files:**
- Modify: `PyAitD/games/base.py`
- Modify: `PyAitD/games/aitd1/profile.py`
- Modify: `PyAitD/engine/life.py:172`, `PyAitD/engine/life.py:197`
- Modify: `AGENTS.md` (known-seams bullet)
- Test: `tests/test_game_profile.py`, `tests/test_life_vm.py:218-224`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `GameProfile.reduced_allowed: frozenset` — a required field, so every `GameProfile(...)` construction in the repo must pass it. Task 2 adds a second required field the same way.

- [ ] **Step 1: Write the failing pin test**

Add to `tests/test_game_profile.py`, immediately after `test_aitd1_debug_venues_and_reduced_dispatch`:

```python
def test_aitd1_reduced_allowed_pins_the_out_of_floor_opcode_set():
    # life.cpp:522-716: the reduced switch has a case for exactly these 16
    # opcodes; every other opcode on an out-of-floor world object is an error
    # FITD does not reach. The set is AITD1's, so it lives in the profile
    # beside reduced_dispatch, not in engine/life.py.
    assert AITD1.reduced_allowed == frozenset(
        {1, 2, 3, 13, 15, 24, 28, 31, 40, 47, 48, 49, 54, 55, 67, 74}
    )
    assert isinstance(AITD1.reduced_allowed, frozenset)
    assert not hasattr(life, "_REDUCED_ALLOWED")
```

No fixture parameters: this test reads no game data, matching its neighbour `test_aitd1_debug_venues_and_reduced_dispatch`. The file already imports `life` and `AITD1`.

- [ ] **Step 2: Run it to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_game_profile.py::test_aitd1_reduced_allowed_pins_the_out_of_floor_opcode_set -q`

Expected: FAIL with `AttributeError: 'GameProfile' object has no attribute 'reduced_allowed'`.

- [ ] **Step 3: Add the field to `GameProfile`**

In `PyAitD/games/base.py`, insert one line immediately after the `reduced_dispatch` field so the data sits beside its dispatch:

```python
    reduced_dispatch: object # callable(vm, opcode, world_idx): not-in-floor ops
    reduced_allowed: frozenset  # opcodes reduced_dispatch has a case for (life.cpp:522-716)
    debug_venues: Mapping    # CLI venue name -> callable(game)
```

It is a **required** field (no default) and must be placed before the defaulted `intro_start` / `game_start` — a dataclass rejects a non-default field after a defaulted one.

- [ ] **Step 4: Give AITD1 its value**

In `PyAitD/games/aitd1/profile.py`, add a module-level constant directly below `CVAR_NAMES`:

```python
# life.cpp:522-716: the opcodes FITD's reduced (out-of-floor) switch has a
# case for. Anything else on a world object whose obj_index is -1 is an error.
REDUCED_ALLOWED = frozenset({1, 2, 3, 13, 15, 24, 28, 31, 40, 47, 48, 49, 54, 55, 67, 74})
```

and pass it in the `AITD1 = GameProfile(...)` call, immediately after `reduced_dispatch=reduced_dispatch,`:

```python
    reduced_dispatch=reduced_dispatch,
    reduced_allowed=REDUCED_ALLOWED,
```

- [ ] **Step 5: Read the data from the profile in the VM**

In `PyAitD/engine/life.py`, delete these two lines (currently at 171-172):

```python
# Reduced dispatch (world object not in floor, life.cpp:522-716): allowed set only.
_REDUCED_ALLOWED = {1, 2, 3, 13, 15, 24, 28, 31, 40, 47, 48, 49, 54, 55, 67, 74}
```

and change the guard inside `process_life` (currently line 197) from:

```python
                if (op & 0x7FFF) not in _REDUCED_ALLOWED:
```

to:

```python
                # the allowed set is the game's (profile.reduced_allowed); the
                # guard is the engine's -- a second game inherits the raise
                if (op & 0x7FFF) not in game.profile.reduced_allowed:
```

Leave the `raise ValueError(...)` message that follows **byte-for-byte unchanged**.

- [ ] **Step 6: Fix the stub profile**

`tests/test_life_vm.py`'s `test_vm_dispatches_through_the_game_profile` builds a `GameProfile` by keyword and now misses a required field. Change:

```python
        reduced_dispatch=lambda vm, op, w: None, debug_venues={},
```

to:

```python
        reduced_dispatch=lambda vm, op, w: None, reduced_allowed=frozenset(),
        debug_venues={},
```

- [ ] **Step 7: Run the new test and the two suites that exercise the VM**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_game_profile.py tests/test_life_vm.py tests/test_life_ops.py -q`

Expected: PASS, no failures.

- [ ] **Step 8: Update the known-seams bullet in `AGENTS.md`**

`AGENTS.md` currently reads (around line 130):

```
- Known seams still hard-coded to AITD1 inside `engine/`, listed so nobody
  closes them ad hoc: `floor.py` resolves `ITD_RESS`/palette entry 3 itself;
  `life.py` fixes `NUM_OPCODES`, the `core_table()` slot numbers and
  `_REDUCED_ALLOWED`; `formats.py` record layouts; `interaction.py`'s
```

Change only the `life.py` clause (Task 2 removes the `floor.py` clause):

```
- Known seams still hard-coded to AITD1 inside `engine/`, listed so nobody
  closes them ad hoc: `floor.py` resolves `ITD_RESS`/palette entry 3 itself;
  `life.py` fixes `NUM_OPCODES` and the `core_table()` slot numbers;
  `formats.py` record layouts; `interaction.py`'s
```

- [ ] **Step 9: Run the full suite**

Run: `make test`

Expected: the same counts as the baseline recorded in Global Constraints.

- [ ] **Step 10: Commit**

```bash
git add PyAitD/games/base.py PyAitD/games/aitd1/profile.py PyAitD/engine/life.py \
        tests/test_game_profile.py tests/test_life_vm.py AGENTS.md
git commit -m "refactor: move the reduced-dispatch opcode set into GameProfile"
```

---

### Task 2: `palette_entry` into `GameProfile`, and `Floor` takes a profile

Deletes `engine/floor.py`'s `PALETTE_PAK`/`PALETTE_ENTRY` and `engine/assets.py`'s duplicate `GAME_PALETTE_ENTRY`. `Floor.__init__` grows a required third positional parameter. Every one of the ~20 call sites passes a profile explicitly in this task; Task 3 then introduces the `Game.load_floor` convenience for the subset that holds a `Game`.

**Files:**
- Modify: `PyAitD/games/base.py`, `PyAitD/games/aitd1/profile.py`
- Modify: `PyAitD/engine/floor.py:10-11`, `PyAitD/engine/floor.py:32-33`
- Modify: `PyAitD/engine/assets.py:10`, `PyAitD/engine/assets.py:33`
- Modify: `PyAitD/engine/game.py:182`
- Modify: `PyAitD/app/shell.py:939`, `:1004`, `:1031`, `:1192`
- Modify: `tools/export_backgrounds.py:36-41`, `:173`, `:184`
- Modify: `tools/prove_mouse.py:30`, `tools/prove_intro.py:38`, `:44`, `tools/prove_graphics.py:38`
- Modify: `AGENTS.md` (drop the `floor.py` clause)
- Test: `tests/test_game_profile.py`, `tests/test_life_vm.py`, `tests/test_mask.py:34`, `:45`, `tests/test_mask_geometry.py:193`, `:211`, `tests/test_render_gl.py:291`, `tests/test_floor_start.py:77`, `:104`, `tests/test_game_over.py:22`, `:105`

**Interfaces:**
- Consumes: `GameProfile.reduced_allowed` exists (Task 1) — any new `GameProfile(...)` construction must pass it.
- Produces:
  - `GameProfile.palette_entry: int` — required field, AITD1 value `3`.
  - `Floor(data_dir, number, profile)` — `profile` is required and positional. Task 3 wraps this in `Game.load_floor`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_game_profile.py`, after the test Task 1 added:

```python
def test_aitd1_palette_entry_pins_the_resource_palette_slot():
    # ITD_RESS entry 3 is the 768-byte VGA palette (6 bits per channel).
    # Both engine/floor.py and engine/assets.py used to hardcode the 3.
    assert AITD1.palette_entry == 3
    from PyAitD.engine import assets, floor
    assert not hasattr(floor, "PALETTE_PAK")
    assert not hasattr(floor, "PALETTE_ENTRY")
    assert not hasattr(assets, "GAME_PALETTE_ENTRY")
```

Add to `tests/test_floor_start.py` — a test that `Floor` refuses to be built without a profile, so nobody reintroduces a default:

```python
def test_floor_requires_a_profile(data_dir):
    # No default: a default palette pak/entry inside engine/ would be the
    # AITD1 hardcode this seam exists to remove.
    with pytest.raises(TypeError):
        Floor(data_dir, 0)
```

`tests/test_floor_start.py` already imports `pytest`; verify with `grep -n "^import pytest" tests/test_floor_start.py` and add the import if missing.

- [ ] **Step 2: Run them to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_game_profile.py::test_aitd1_palette_entry_pins_the_resource_palette_slot "tests/test_floor_start.py::test_floor_requires_a_profile" -q`

Expected: the first FAILs with `AttributeError: 'GameProfile' object has no attribute 'palette_entry'`; the second FAILs with `Failed: DID NOT RAISE <class 'TypeError'>`.

- [ ] **Step 3: Add the field**

In `PyAitD/games/base.py`, insert immediately after `resource_pak`:

```python
    resource_pak: str
    palette_entry: int       # resource_pak entry holding the 768-byte VGA palette
```

In `PyAitD/games/aitd1/profile.py`, in the `GameProfile(...)` call, immediately after `resource_pak="ITD_RESS",`:

```python
    resource_pak="ITD_RESS",
    palette_entry=3,
```

In `tests/test_life_vm.py`'s stub profile, add `palette_entry=3` — the line Task 1 edited becomes:

```python
        name="stub", lifes_pak="", tracks_pak="", text_pak="", resource_pak="",
        palette_entry=3,
        heroes=(), cvar_names=(), defines_big_endian=True,
        opcode_table=tuple(table),
        reduced_dispatch=lambda vm, op, w: None, reduced_allowed=frozenset(),
        debug_venues={},
```

- [ ] **Step 4: Rewrite `Floor.__init__`**

In `PyAitD/engine/floor.py`, delete these two module constants (lines 10-11):

```python
PALETTE_PAK = "ITD_RESS"
PALETTE_ENTRY = 3
```

and change the constructor signature and the palette lines:

```python
class Floor:
    def __init__(self, data_dir, number, profile):
        self.number = number
        etage = find_pak(data_dir, f"ETAGE{number:02d}")
        self._images = find_pak(data_dir, f"CAMERA{number:02d}")
        self.rooms = parse_rooms(load_entry(str(etage), 0))
        self.camera_raw = load_entry(str(etage), 1)
        self.cameras = parse_cameras(self.camera_raw)
        self.camera_data_offsets = camera_offsets(self.camera_raw)
        palette_pak = find_pak(data_dir, profile.resource_pak)
        self.palette = decode_palette(load_entry(str(palette_pak), profile.palette_entry))
```

Everything below (`self._num_images` onward) is unchanged. Do **not** store `profile` on the instance — nothing reads it.

- [ ] **Step 5: Delete the duplicate constant in `assets.py`**

In `PyAitD/engine/assets.py`, delete line 10:

```python
GAME_PALETTE_ENTRY = 3
```

and change line 33 from:

```python
        self._game_palette = decode_palette(load_entry(self._resource_pak, GAME_PALETTE_ENTRY))
```

to:

```python
        self._game_palette = decode_palette(load_entry(self._resource_pak, profile.palette_entry))
```

- [ ] **Step 6: Update `Game.rooms_of_floor`**

In `PyAitD/engine/game.py`, line 182 becomes:

```python
            self._rooms_by_floor[floor_number] = Floor(self._data_dir, floor_number, self.profile).rooms
```

Keep this as a direct `Floor(...)` call. Task 3 adds `Game.load_floor`, and `rooms_of_floor` deliberately does **not** use it — see Task 3, Step 3.

- [ ] **Step 7: Update the four `app/shell.py` call sites**

Pass `game.profile` (or the new game's profile) positionally. Line 939:

```python
        new_floor = Floor(new_game._data_dir, new_game.current_floor, new_game.profile)
```

Line 1004:

```python
        new_floor = Floor(new_game._data_dir, new_game.current_floor, new_game.profile)
```

Line 1031:

```python
        floor = Floor(game._data_dir, game.current_floor, game.profile)
```

Line 1192:

```python
                    floor = Floor(game._data_dir, game.current_floor, game.profile)
```

The 20 tests that stub `main.Floor` use `lambda *args: ...` / `lambda *a: ...` signatures, so an extra positional argument does not break them. Task 3 migrates those patches.

- [ ] **Step 8: Update the four tools**

`tools/prove_mouse.py:30` — the game is already in scope:

```python
        floor = Floor(data, number, game.profile)
```

`tools/prove_intro.py:38` and `:44`:

```python
    return game, Floor(data_dir, game.current_floor, game.profile)
```

```python
        floor = Floor(data_dir, game.current_floor, game.profile)
```

`tools/prove_graphics.py:38`:

```python
    return game, Floor(data_dir, game.current_floor, game.profile)
```

`tools/export_backgrounds.py` has no `Game`. Resolve the profile once at module level and thread it. Replace lines 36-41:

```python
def load_floor(data_dir, number):
    return Floor(data_dir, number)


def load_assets(data_dir):
    return Assets(data_dir, load_profile("aitd1"))
```

with:

```python
# This tool exports AITD1 data and has no Game to take a profile from, so it
# resolves the profile itself -- the one place the game id is named here.
PROFILE = load_profile("aitd1")


def load_floor(data_dir, number):
    return Floor(data_dir, number, PROFILE)


def load_assets(data_dir):
    return Assets(data_dir, PROFILE)
```

Lines 173 and 184 call these helpers and need no change.

- [ ] **Step 9: Update the nine direct-`Floor` test call sites**

These construct a `Floor` with no `Game` in reach, or for a floor other than the game's. Add the profile as a third argument. Each of these tests already takes `data_dir`; add `profile` to its signature too — the fixture arrives in Task 5, so for now import AITD1 and pass it directly, matching each file's existing style.

`tests/test_mask.py`, `tests/test_mask_geometry.py` and `tests/test_render_gl.py` do **not** currently import AITD1 (verified: `grep -c "import AITD1"` returns 0 for each). Add this line to each file's import block, above the `pytestmark` line:

```python
from PyAitD.games.aitd1.profile import AITD1
```

Task 5 replaces all three with the fixture; this is the intermediate state that keeps the suite green in between.

`tests/test_mask.py:34` and `:45`:

```python
    floor = Floor(d, 0, AITD1)
```

`tests/test_mask_geometry.py:193` and `:211`:

```python
    floor = Floor(data_dir, 0, AITD1)
```

`tests/test_render_gl.py:291`:

```python
    floor = Floor(data_dir, 0, AITD1)
```

`tests/test_floor_start.py:77` and `:104` (this file already imports AITD1):

```python
    floor = Floor(data_dir, 5, AITD1)
```

```python
    floor = Floor(data_dir, 6, AITD1)
```

`tests/test_game_over.py:22` and `:105` (this file already imports AITD1):

```python
    floor = Floor(data_dir, game.current_floor, AITD1)
```

- [ ] **Step 10: Run the new tests plus every touched test file**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_game_profile.py tests/test_life_vm.py tests/test_mask.py tests/test_mask_geometry.py tests/test_render_gl.py tests/test_floor_start.py tests/test_game_over.py tests/test_assets.py -q`

Expected: PASS.

- [ ] **Step 11: Drop the `floor.py` clause from `AGENTS.md`**

After Task 1 the bullet reads:

```
- Known seams still hard-coded to AITD1 inside `engine/`, listed so nobody
  closes them ad hoc: `floor.py` resolves `ITD_RESS`/palette entry 3 itself;
  `life.py` fixes `NUM_OPCODES` and the `core_table()` slot numbers;
  `formats.py` record layouts; `interaction.py`'s
  `COMBAT_ACTIONS`/`PLAYER_*_ANIM`/`PLAYER_TRACK_MODES` indices. Close one by
  moving it into `GameProfile` with a test, not by adding a second copy.
```

Change it to:

```
- Known seams still hard-coded to AITD1 inside `engine/`, listed so nobody
  closes them ad hoc: `life.py` fixes `NUM_OPCODES` and the `core_table()`
  slot numbers; `formats.py` record layouts; `interaction.py`'s
  `COMBAT_ACTIONS`/`PLAYER_*_ANIM`/`PLAYER_TRACK_MODES` indices. Close one by
  moving it into `GameProfile` with a test, not by adding a second copy.
```

- [ ] **Step 12: Run the full suite and the tool proofs**

Run: `make test`

Expected: baseline counts.

Then, on a machine with GL and game data, run: `make proof-graphics && make proof-mouse`

Expected: both exit 0. If the machine has no GL or no game data, say so in the task report rather than reporting a pass.

- [ ] **Step 13: Commit**

```bash
git add PyAitD/games/base.py PyAitD/games/aitd1/profile.py PyAitD/engine/floor.py \
        PyAitD/engine/assets.py PyAitD/engine/game.py PyAitD/app/shell.py \
        tools/export_backgrounds.py tools/prove_mouse.py tools/prove_intro.py \
        tools/prove_graphics.py tests/ AGENTS.md
git commit -m "refactor: Floor takes the GameProfile; palette entry leaves engine/"
```

---

### Task 3: `Game.load_floor` and the monkeypatch migration

Adds the convenience seam and moves every `Game`-holding caller onto it. This is the task that removes `main.Floor` as a patch point, so it also migrates the 20 tests that stub it.

**Files:**
- Modify: `PyAitD/engine/game.py` (new method)
- Modify: `PyAitD/app/shell.py:15` (drop the `Floor` import), `:939`, `:1004`, `:1031`, `:1192`
- Modify: `tools/prove_mouse.py:30`, `tools/prove_intro.py:38`, `:44`, `tools/prove_graphics.py:38`
- Modify: `CONTEXT.md`
- Test: `tests/test_game.py` (new test), `tests/test_game_over.py:22`, `:105`, and the 20 patch sites listed in Step 5

**Interfaces:**
- Consumes: `Floor(data_dir, number, profile)` from Task 2.
- Produces: `Game.load_floor(self, number) -> Floor`. Tests stub it either as a class attribute (`monkeypatch.setattr(Game, "load_floor", lambda self, number: ...)`) or as an attribute on a fake game namespace (`load_floor=lambda number: ...`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_game.py`:

```python
def test_load_floor_threads_the_profile_and_does_not_cache(data_dir):
    # The seam for callers that hold a Game: they need neither the profile
    # nor game._data_dir. Uncached on purpose -- the shell holds its own
    # floor and reloads only when current_floor changes, and a cache would
    # retain every visited floor's decoded camera images for the process.
    game = init_game(data_dir, AITD1)
    first = game.load_floor(0)
    second = game.load_floor(0)
    assert first.number == 0
    assert first is not second
    assert first.palette.shape == second.palette.shape


def test_rooms_of_floor_does_not_go_through_load_floor(data_dir, monkeypatch):
    # Several shell tests stub Game.load_floor at class level because the
    # shell builds its game internally. If rooms_of_floor shared that method,
    # those stubs would also replace the engine's own room lookups.
    game = init_game(data_dir, AITD1)
    monkeypatch.setattr(
        type(game), "load_floor",
        lambda self, number: pytest.fail("rooms_of_floor must not call load_floor"),
    )
    assert game.rooms_of_floor(0)
```

`tests/test_game.py` already imports `pytest` and `AITD1`; confirm with `grep -n "^import pytest\|import AITD1\|from PyAitD.engine.game import" tests/test_game.py` and add what is missing.

- [ ] **Step 2: Run it to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_game.py::test_load_floor_threads_the_profile_and_does_not_cache -q`

Expected: FAIL with `AttributeError: 'Game' object has no attribute 'load_floor'`.

- [ ] **Step 3: Add the method**

In `PyAitD/engine/game.py`, add immediately **above** `rooms_of_floor`:

```python
    def load_floor(self, number):
        """The Floor loader for callers outside Game: threads self.profile so
        they need neither the profile nor self._data_dir. Uncached by design
        -- callers hold their own floor and reload only when current_floor
        changes, and a cache would retain every visited floor's decoded
        camera images for the process's lifetime. Game's own internals
        (rooms_of_floor) construct Floor directly, so a test stubbing
        load_floor cannot starve them."""
        return Floor(self._data_dir, number, self.profile)
```

Leave `rooms_of_floor` exactly as Task 2 left it — constructing `Floor` directly.

- [ ] **Step 4: Move the shell and tools onto the seam**

`PyAitD/app/shell.py` line 939:

```python
        new_floor = new_game.load_floor(new_game.current_floor)
```

Line 1004:

```python
        new_floor = new_game.load_floor(new_game.current_floor)
```

Line 1031:

```python
        floor = game.load_floor(game.current_floor)
```

Line 1192:

```python
                    floor = game.load_floor(game.current_floor)
```

Then delete the now-unused import at line 15:

```python
from PyAitD.engine.floor import Floor
```

Verify nothing else in the file references `Floor`: `grep -n "Floor" PyAitD/app/shell.py` should return only `FloorStart`-style names or comments, if any.

Tools — `tools/prove_mouse.py:30`:

```python
        floor = game.load_floor(number)
```

`tools/prove_intro.py:38` and `:44`:

```python
    return game, game.load_floor(game.current_floor)
```

```python
        floor = game.load_floor(game.current_floor)
```

`tools/prove_graphics.py:38`:

```python
    return game, game.load_floor(game.current_floor)
```

Then drop each tool's now-unused `from PyAitD.engine.floor import Floor` import — check each with `grep -n Floor tools/prove_mouse.py tools/prove_intro.py tools/prove_graphics.py`. **Keep** the import in `tools/export_backgrounds.py`; that tool has no `Game`.

`tests/test_game_over.py:22` and `:105`:

```python
    floor = game.load_floor(game.current_floor)
```

- [ ] **Step 5: Migrate the 20 `main.Floor` monkeypatch sites**

Run `grep -rn 'main, "Floor"' tests` to list them. There are 20, in four files. Two mechanical rules — apply **both** at every site, since doing the unneeded one is harmless:

**Rule A — the shell receives a real `Game`.** Replace the `main.Floor` patch with a class-level patch. Add `from PyAitD.engine.game import Game` to the test's local imports if absent.

```python
    monkeypatch.setattr(
        Game, "load_floor",
        lambda self, number: SimpleNamespace(number=0, rooms=[SimpleNamespace(camera_indices=[0])]),
    )
```

The lambda takes `(self, number)` where the old one took `*args`.

**Rule B — the shell receives a `SimpleNamespace` fake.** Give the namespace the method instead; the lambda takes `(number)` only, because it is a plain attribute, not a bound method.

```python
    game = SimpleNamespace(
        ...,
        load_floor=lambda number: SimpleNamespace(number=0, rooms=[SimpleNamespace(camera_indices=[0])]),
    )
```

Three sites need named handling:

- `tests/test_play_loop.py:407` — `_fake_game(tmp_path, **overrides)` is the shared fake behind the sites at `:455`, `:484` and `:546`. Add one entry to its `fields` dict, keeping it overridable:

```python
        messages=(),
        load_floor=lambda number: SimpleNamespace(
            number=0, rooms=[SimpleNamespace(camera_indices=[0])],
        ),
```

  Then delete the `main.Floor` patch from those three tests entirely.

- `tests/test_runtime_modes.py:1283` — `refuse_floor` exists to assert that `restart_session` performs **no** floor I/O. It becomes a class patch:

```python
    monkeypatch.setattr(Game, "load_floor", refuse_floor)
```

  and `refuse_floor`'s signature gains the bound `self`: change `def refuse_floor(*args)` (or whatever its current shape is — read it) to accept `(self, number)`. Its raising body is unchanged. This preserves exactly what the test asserts.

- `tests/test_runtime_modes.py:1352` — `spy_floor` counts reloads. Class-patch it and widen its signature to `(self, number)`; keep whatever it appends so the ordering assertions below it still hold. The same file's `:871` `load_floor` local function is unrelated to the new method name; leave its name alone or rename it for clarity, but do not let the two confuse you.

The remaining 15 sites are direct substitutions of Rule A or Rule B.

- [ ] **Step 6: Run every touched test file**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_game.py tests/test_game_over.py tests/test_play_loop.py tests/test_runtime_modes.py tests/test_main.py tests/test_shell_journeys.py -q`

Expected: PASS. A failure here means a stub's signature does not match `(self, number)` or `(number)` — read the traceback, do not widen a stub to `*args` to make it go away, because the point of the migration is that the seam has a shape.

- [ ] **Step 7: Update `CONTEXT.md`**

`CONTEXT.md` line 73 currently reads:

```
| `engine/pak.py`, `engine/floor.py`, `engine/explode.py` | PAK/HQR archives, ETAGE floor data, EXPLODE decompression |
```

Change to:

```
| `engine/pak.py`, `engine/floor.py`, `engine/explode.py` | PAK/HQR archives, ETAGE floor data, EXPLODE decompression. `Floor(data_dir, number, profile)` takes the profile for the palette pak/entry; callers holding a `Game` use `game.load_floor(number)` instead (`rooms_of_floor` deliberately does not) |
```

Line 78 currently reads:

```
| `games/base.py` | `GameProfile`: PAK names, hero archives, CVar names, DEFINES endianness, opcode table, reduced dispatch, debug venues |
```

Change to:

```
| `games/base.py` | `GameProfile`: PAK names, palette entry, hero archives, CVar names, DEFINES endianness, opcode table, reduced dispatch + its allowed opcode set, debug venues |
```

- [ ] **Step 8: Run the full suite and the proofs**

Run: `make test`

Expected: baseline counts.

Then, with GL and game data: `make proof-graphics && make proof-mouse && make proof-intro`

Expected: all exit 0. Report honestly if the machine cannot run them.

- [ ] **Step 9: Commit**

```bash
git add PyAitD/engine/game.py PyAitD/app/shell.py tools/prove_mouse.py \
        tools/prove_intro.py tools/prove_graphics.py tests/ CONTEXT.md
git commit -m "refactor: Game.load_floor replaces the shell's Floor construction"
```

---

### Task 4: Fold the purity probes into `test_layering.py`

Six subprocess probes live in six different test files. The engine-package-reorganization spec asked for one place where the package rules live; this is that consolidation.

**Files:**
- Modify: `tests/test_layering.py`
- Modify: `tests/test_navigate.py:17`, `tests/test_navmesh.py:17-20`, `tests/test_picking.py:16-19`, `tests/test_playworld.py:19-22`, `tests/test_mouse_only.py:37-38`, `tests/test_config.py:74`
- Unchanged: `tests/purity.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `tests/test_layering.py::PRESENTATION_FREE`, a tuple of `(modules, forbidden, why)` rows where `modules` is a comma-joined string of dotted module names.

- [ ] **Step 1: Read the six probes and copy their arguments verbatim**

Run: `grep -rn -A4 "assert_presentation_free(" tests/test_navigate.py tests/test_navmesh.py tests/test_picking.py tests/test_playworld.py tests/test_mouse_only.py tests/test_config.py`

Every `why` string and every module name below must match what that command prints, character for character. If it does not, the printed text wins — this plan's copy is the transcription, the source file is the original.

- [ ] **Step 2: Add the table and the parametrized test**

In `tests/test_layering.py`, change the import at line 15 from:

```python
from tests.purity import PRESENTATION
```

to:

```python
from tests.purity import PRESENTATION, assert_presentation_free
```

and add, at the end of the file:

```python
# The runtime twin of the static import scan above: a module can pass the ast
# check and still drag the presentation layer in through a transitive import,
# so each of these is imported in a fresh interpreter. Folded here from six
# separate test files so the package rules live in one place
# (2026-08-26-engine-package-reorganization-design.md:110-113). Rows are the
# modules whose headless importability is load-bearing, each with its reason.
PRESENTATION_FREE = (
    ("PyAitD.engine.navigate", PRESENTATION, ""),
    ("PyAitD.engine.navmesh", PRESENTATION,
     " — the mesh must stay importable without the presentation layer so it can build headless"),
    ("PyAitD.engine.picking", PRESENTATION,
     " — picking is pure math and must not need a window; the shell passes it logical coordinates"),
    ("PyAitD.engine.playworld,PyAitD.engine.anim_action", PRESENTATION,
     " — the tick must stay importable without the presentation layer so it can run headless"),
    ("PyAitD.games.aitd1.mouse_contract", PRESENTATION, ""),
    # app/config is allowed the rest of the presentation layer; it must only
    # stay free of pygame so settings can be read and written headless.
    ("PyAitD.app.config", ("pygame",), ""),
)


@pytest.mark.parametrize(
    "modules, forbidden, why", PRESENTATION_FREE,
    ids=[row[0] for row in PRESENTATION_FREE],
)
def test_module_imports_stay_presentation_free(modules, forbidden, why):
    assert_presentation_free(*modules.split(","), forbidden=forbidden, why=why)
```

- [ ] **Step 3: Run the new test and verify all six rows pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_layering.py -q -k presentation_free -v`

Expected: 6 passed, with ids naming each module.

- [ ] **Step 4: Prove the new test can actually fail**

Temporarily add a row `("PyAitD.app.shell", PRESENTATION, "")` to `PRESENTATION_FREE` and re-run the command from Step 3.

Expected: that row FAILs, naming the leaked modules (`PyAitD.app.shell` imports pygame). Then **remove the temporary row**. This guards against a probe that vacuously passes.

- [ ] **Step 5: Delete the six original probes**

Delete these whole test functions, and each file's now-unused `from tests.purity import assert_presentation_free` import:

- `tests/test_navigate.py` — the test containing `assert_presentation_free("PyAitD.engine.navigate")`
- `tests/test_navmesh.py` — the test containing the `PyAitD.engine.navmesh` probe
- `tests/test_picking.py` — the test containing the `PyAitD.engine.picking` probe
- `tests/test_playworld.py` — the test containing the `PyAitD.engine.playworld` / `anim_action` probe
- `tests/test_mouse_only.py` — `test_mouse_contract_is_presentation_free`
- `tests/test_config.py` — the test containing the `PyAitD.app.config` probe

After each deletion, confirm the import is genuinely unused: `grep -n "assert_presentation_free" tests/<file>` must print nothing.

Do **not** touch `tests/purity.py`, and do **not** change any file's `pytestmark`.

- [ ] **Step 6: Run the six stripped files plus the layering file**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_layering.py tests/test_navigate.py tests/test_navmesh.py tests/test_picking.py tests/test_playworld.py tests/test_mouse_only.py tests/test_config.py -q`

Expected: PASS.

- [ ] **Step 7: Confirm the group accounting**

Run: `make test-meta && make test-engine && make test-shell`

Expected: all three green. `test-meta` gains six cases; `test-engine` and `test-shell` each lose the probes they used to carry. `tests/test_test_groups.py` pins files rather than tests, so it needs no edit — if it fails, stop and read why rather than editing the pinned data.

- [ ] **Step 8: Run the full suite**

Run: `make test`

Expected: the same **total** as the baseline. The count is unchanged because six tests moved rather than disappeared — six single tests become six parametrized cases of one test. If the total drops, a probe was deleted without being re-added; find it before proceeding.

- [ ] **Step 9: Commit**

```bash
git add tests/test_layering.py tests/test_navigate.py tests/test_navmesh.py \
        tests/test_picking.py tests/test_playworld.py tests/test_mouse_only.py \
        tests/test_config.py
git commit -m "test: fold the six runtime purity probes into test_layering"
```

---

### Task 5: The `profile` fixture

The mass edit, landed last so its churn never obscures a real diff. 325 constructor sites, 17 attribute reads and 4 further references across 38 files become the fixture; 40 import lines go.

**Files:**
- Modify: `tests/conftest.py`
- Modify: 38 files under `tests/` (every file that imports `AITD1`, except the two exclusions below)
- Excluded: `tests/test_game_profile.py` only. `tests/test_life_vm.py` migrates like any other file — its stub `GameProfile(...)` construction is not AITD1 and is left alone, but its 17 `init_game(data_dir, AITD1, hero=0)` sites and its AITD1 import do move to the fixture.

**Interfaces:**
- Consumes: `GameProfile.palette_entry` and `.reduced_allowed` exist (Tasks 1-2); `Game.load_floor` exists (Task 3).
- Produces: a `profile` pytest fixture returning the AITD1 `GameProfile`. Module-level helper functions take `profile` as an explicit parameter — fixtures reach test functions only.

- [ ] **Step 1: Record the baseline**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/ -q --collect-only | tail -3`

Write the collected count down. Then run `make test` and write down `N passed, N skipped, N xfailed`. Both must be identical at the end of this task — that is the entire acceptance criterion, because this task changes no behaviour.

- [ ] **Step 2: Add the fixture**

In `tests/conftest.py`, after the `data_dir` fixture:

```python
@pytest.fixture
def profile():
    """The GameProfile under test. AITD1 today; a second game would
    parametrize here. Tests that assert AITD1's *identity* -- its pak names,
    opcode table, CVar list, reduced-opcode set -- import AITD1 directly
    instead (tests/test_game_profile.py). This fixture makes the suite's
    construction idiom uniform; it does NOT make the tests portable, since
    they still assert AITD1-specific golden values."""
    from PyAitD.games.aitd1.profile import AITD1
    return AITD1
```

- [ ] **Step 3: Write the guard test**

Add to `tests/test_test_groups.py` (marked `meta`, and this is a repo-convention assertion, which is what that file is for):

```python
def test_tests_take_the_profile_from_the_fixture():
    """AITD1 is constructed in one place -- conftest's profile fixture --
    except where a test pins AITD1's own identity or builds a stub profile.
    A new test that imports AITD1 to call init_game should take the fixture
    instead."""
    # test_game_profile.py is the only exception: its job is pinning AITD1's
    # own identity, which a fixture would make circular. test_life_vm.py
    # builds a *stub* GameProfile, not AITD1, so it takes the fixture like
    # every other file.
    allowed = {"test_game_profile.py"}
    offenders = sorted(
        p.name for p in all_test_files()
        if p.name not in allowed
        and "from PyAitD.games.aitd1.profile import AITD1" in p.read_text()
    )
    assert not offenders, offenders
```

`all_test_files()` already exists in that file.

- [ ] **Step 4: Run it to verify it fails loudly**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_test_groups.py::test_tests_take_the_profile_from_the_fixture -q`

Expected: FAIL, listing 38 file names. That list is your worklist.

- [ ] **Step 5: Rewrite the call sites, file by file**

Work one file at a time and run that file's tests before moving on. For each file:

1. Delete `from PyAitD.games.aitd1.profile import AITD1` (some files have it twice — once at module level, once inside a function; delete both).
2. Replace `AITD1` with `profile` at every remaining occurrence **except** the FITD citations. There are exactly three `AITD1.cpp` occurrences in comments, and a naive `s/AITD1/profile/` corrupts them into `profile.cpp`. Find them first with `grep -rn "AITD1\.cpp" tests` and leave those lines alone.
3. Add `profile` to each affected test function's signature, immediately after `data_dir`:

```python
def test_something(data_dir, profile):
```

   Every test function that references `AITD1` already takes `data_dir` — verified by an `ast` scan of the suite — with exactly one exception, handled in Step 6.

4. Module-level helper functions cannot request a fixture. Give each an explicit `profile` parameter and thread it from every caller. The fourteen are:

| file | helper |
|---|---|
| `tests/test_anim_action.py` | `_live_actors(data_dir, count)`, `_thrown_game(data_dir)` |
| `tests/test_combat_journey.py` | `_venue(data_dir)` |
| `tests/test_eval_var.py` | `_spawned(data_dir)` |
| `tests/test_game_over.py` | `_game_over_session(data_dir)` |
| `tests/test_intro.py` | `boot_intro(data_dir, hero)` |
| `tests/test_life_vm.py` | `_make_game(data_dir)` |
| `tests/test_navmesh.py` | `_hero_agent(data_dir)` |
| `tests/test_pick_venue.py` | `_settled_venue(data_dir)` |
| `tests/test_play_loop.py` | `_cross_room_target_setup(data_dir)`, `_click_to_attack(data_dir)` |
| `tests/test_playworld.py` | `_latched_attack(data_dir)` |
| `tests/test_scene.py` | `_boot(data_dir)` |
| `tests/test_shell_journeys.py` | `_confirm_emily_events(game)` |

   Each becomes `def _helper(data_dir, profile, ...)`, called as `_helper(data_dir, profile, ...)`. `_confirm_emily_events(game)` takes a game and can read `game.profile` instead of gaining a parameter — prefer that where a game is already in hand.

5. Two nested closures in `tests/test_shell_journeys.py` named `observe_tick` reference `AITD1` inside an enclosing test. They close over the enclosing test's `profile` parameter — no signature change needed once the enclosing test takes the fixture.

6. Attribute reads become fixture reads: `AITD1.cvar_index("TEXTE_CREDITS")` → `profile.cvar_index("TEXTE_CREDITS")` (12 sites), `AITD1.intro_start` → `profile.intro_start` (3), `AITD1.game_start` → `profile.game_start` (2).

Run after each file: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/<file> -q`

- [ ] **Step 6: Handle the one test with no `data_dir`**

`tests/test_play_loop.py::test_hero_branch_builds_its_resolver_from_the_session_s_override_dir` takes only `monkeypatch` — it stubs everything and needs no game data. It takes the fixture directly:

```python
def test_hero_branch_builds_its_resolver_from_the_session_s_override_dir(monkeypatch, profile):
```

and its `old_game = SimpleNamespace(..., profile=AITD1, ...)` becomes `profile=profile`.

- [ ] **Step 7: Verify the citations survived**

Run: `grep -rn "profile\.cpp" tests PyAitD tools`

Expected: no output. Any hit is a corrupted FITD citation — restore it to `AITD1.cpp`.

Run: `grep -rn "AITD1" tests | grep -v test_game_profile`

Expected: only the three `AITD1.cpp` comment citations.

- [ ] **Step 8: Run the guard test and the full suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_test_groups.py -q`

Expected: PASS — the offender list is empty.

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/ -q --collect-only | tail -3`

Expected: **exactly** the collected count from Step 1, plus 1 for the guard test added in Step 3.

Run: `make test`

Expected: the Step 1 counts, plus 1 passed for the guard test.

- [ ] **Step 9: Run every group target**

Run: `make test-engine && make test-render && make test-shell && make test-tools && make test-meta && make test-journey`

Expected: all green. `test-meta` is up by one (the guard test); the rest are unchanged.

- [ ] **Step 10: Commit**

```bash
git add tests/
git commit -m "test: take the GameProfile from a conftest fixture"
```

---

## Verification

After Task 5, the branch as a whole must satisfy:

- [ ] `make test` matches the baseline counts plus exactly **6** added tests: 1 in Task 1 (`reduced_allowed` pin), 2 in Task 2 (`palette_entry` pin, `Floor` requires a profile), 2 in Task 3 (`load_floor` behaviour, `rooms_of_floor` isolation), 1 in Task 5 (the fixture guard). Task 4 is net-zero — six single tests become six parametrized cases of one test.
- [ ] `grep -rn "ITD_RESS" PyAitD/engine` prints nothing.
- [ ] `grep -rn "_REDUCED_ALLOWED\|GAME_PALETTE_ENTRY\|PALETTE_PAK" PyAitD` prints nothing.
- [ ] `grep -rn 'main, "Floor"' tests` prints nothing.
- [ ] `grep -rn "AITD1" tests | grep -v test_game_profile` prints only the three `AITD1.cpp` comment citations.
- [ ] On a machine with GL and game data: `make proof-mouse && make proof-combat && make proof-graphics && make proof-intro` all exit 0.
