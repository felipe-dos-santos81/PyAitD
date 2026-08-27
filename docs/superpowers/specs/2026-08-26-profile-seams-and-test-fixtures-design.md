# Profile seams and test fixtures — design

Date: 2026-08-26. Status: approved design.

## Goal

Close two AITD1 hard-codes that the engine package reorganization left inside
`engine/`, and two test-suite seams the same reorg opened but did not finish:

1. `engine/floor.py`'s `PALETTE_PAK = "ITD_RESS"` / `PALETTE_ENTRY = 3` (and
   `engine/assets.py`'s duplicate `GAME_PALETTE_ENTRY = 3`).
2. `engine/life.py`'s `_REDUCED_ALLOWED`, whose dispatch already lives in
   `games/aitd1/life_reduced.py`.
3. The 325 `init_game(data_dir, AITD1)` / `Assets(data_dir, AITD1)` /
   `Game(data_dir, AITD1)` call sites in `tests/`, which import the concrete
   profile instead of taking it as a fixture.
4. The six subprocess purity probes scattered across six test files, which the
   reorg spec asked to fold into `tests/test_layering.py` so "there is one
   place the rules live"
   (`2026-08-26-engine-package-reorganization-design.md:110-113`).

Items 1 and 2 are the same seam listed in `AGENTS.md`'s known-hard-codes
bullet; this design removes both entries from that list. Items 3 and 4 are
test-side only and change no shipped behaviour.

## Non-goals

- `engine/life.py`'s `NUM_OPCODES` and `core_table()` slot numbering,
  `engine/formats.py`'s record layouts, and `engine/interaction.py`'s
  `COMBAT_ACTIONS` / `PLAYER_*_ANIM` / `PLAYER_TRACK_MODES` indices stay
  hard-coded. They remain listed in `AGENTS.md` as open seams.
- The two remaining `game._data_dir` reach-throughs in `app/shell.py` (both
  `init_game` calls). Closing those means a `Game.data_dir` property, which is
  a separate argument.
- No test is moved, renamed, or split, and no new coverage is added, except
  where item 4 explicitly relocates six tests.
- No `Floor` caching. See "Why no cache" below.

## 1 — Threading the profile into `Floor`

### The field

`GameProfile` gains one **required** field, `palette_entry: int`, placed
immediately after `resource_pak` (before the defaulted `intro_start` /
`game_start`). AITD1's value is `3`.

`resource_pak` already exists and is already profile-driven in
`engine/assets.py`; only the entry number was hard-coded, in two places.

### `engine/floor.py`

Delete the module constants `PALETTE_PAK` and `PALETTE_ENTRY`. The
constructor becomes:

```python
class Floor:
    def __init__(self, data_dir, number, profile):
        # ... rooms/cameras unchanged ...
        palette_pak = find_pak(data_dir, profile.resource_pak)
        self.palette = decode_palette(load_entry(str(palette_pak), profile.palette_entry))
```

`profile` is a required third positional parameter — no default, so no AITD1
value survives anywhere in `engine/`. `Floor` does **not** store the profile;
nothing downstream reads it.

### `engine/assets.py`

Delete `GAME_PALETTE_ENTRY = 3`; line 33 reads `profile.palette_entry`.
`Assets` already takes `profile`, so this is a one-line change that removes
the second copy of the same constant. Closing one copy and not the other would
leave the seam half-open, which is the failure mode this design exists to
avoid.

### The factory

`Game` gains:

```python
    def load_floor(self, number):
        """The Floor loader for callers outside Game: threads self.profile so
        they need neither the profile nor self._data_dir. Uncached by design
        -- callers hold their own floor and reload only when current_floor
        changes. Game's own internals (rooms_of_floor) construct Floor
        directly, so a test stubbing load_floor cannot starve them."""
        return Floor(self._data_dir, number, self.profile)
```

`Game.rooms_of_floor` **does not** route through `load_floor`; it keeps
constructing `Floor(self._data_dir, floor_number, self.profile)` itself, with
its `_rooms_by_floor` rooms cache unchanged. This is deliberate. Twenty tests
stub floor loading to keep the shell off real data (see "The cost" below), and
several of them must patch `Game.load_floor` at *class* level because the
shell builds the game internally. Were `rooms_of_floor` to share that method,
a class-level stub would also replace the engine's own room lookups —
coupling that the current `main.Floor` patch point does not have.
`rooms_of_floor` is one line of profile threading inside `Game`, not a caller
that needs the seam.

Callers that hold a `Game` switch to the factory:

| file | sites |
|---|---|
| `PyAitD/app/shell.py` | 4 (`_boot_hero`, `_restart_branch`, `run`, the floor-change reload) |
| `PyAitD/engine/game.py` | 1 (`rooms_of_floor`) |
| `tools/prove_intro.py` | 2 |
| `tools/prove_graphics.py` | 1 |
| `tools/prove_mouse.py` | 1 (loops floors 0..7 off one game) |
| `tests/test_game_over.py` | 2 |

This also deletes four `game._data_dir` reach-throughs from `app/`.

### `Floor(data_dir, number, profile)` stays public

Four callers have no `Game` in reach and keep constructing `Floor` directly,
passing a profile explicitly:

| file | how it gets the profile |
|---|---|
| `tools/export_backgrounds.py` | already calls `load_profile("aitd1")` for `load_assets`; hoist that to one module-level resolution and pass it to `load_floor(data_dir, number)` |
| `tests/test_mask.py` (2), `tests/test_mask_geometry.py` (2), `tests/test_render_gl.py` (1) | the `profile` fixture from item 3 |
| `tests/test_floor_start.py` (2) | the `profile` fixture; these load floors 5 and 6 while the game is on another floor |

The factory is a convenience for `Game`-holders, not a replacement for the
constructor.

### Why no cache

`Game.load_floor` deliberately does not cache. Today the shell holds one
`Floor` in a local and rebuilds it only when `floor.number != current_floor`;
`prove_mouse` and `export_backgrounds` walk all eight floors and discard each.
A `Game`-held cache would retain every visited floor's decoded camera images
(320x200x3 per camera, many cameras per floor) for the process's lifetime —
a memory regression bought for no measured gain. A size-1 cache would
duplicate the reload check the shell already performs. Uncached keeps
behaviour byte-identical to today.

### The cost: 20 `main.Floor` monkeypatch sites

This is the largest hidden cost in this design and the reason item 1 is
sequenced before the mass edit rather than after.

Twenty tests currently stub the shell's module-level `Floor` symbol —
`monkeypatch.setattr(main, "Floor", ...)` — across `test_play_loop.py` (12),
`test_runtime_modes.py` (6), `test_main.py` (1), `test_shell_journeys.py` (1).
Moving construction onto the game removes that seam. Two migration rules,
chosen per site:

- **The shell operates on a fake game** (a `SimpleNamespace`, as in
  `test_play_loop.py:609`): give the namespace a `load_floor` attribute and
  drop the `main.Floor` patch.
- **The shell builds a real game the test cannot reach before construction**
  (`_hero_branch` / `_restart_branch` call `init_game` internally — the
  original reason `main.Floor` was the patch point): patch the class,
  `monkeypatch.setattr(Game, "load_floor", ...)`, which covers instances
  created later.

Both preserve what each test asserts. The error-path tests
(`test_runtime_modes.py:1283`'s `refuse_floor`, which raises `PakError`) and
the reload-counting spies (`:1352`'s `spy_floor`) keep their exact assertions;
only the patch target moves.

## 2 — `_REDUCED_ALLOWED` into the profile

`GameProfile` gains a second **required** field, `reduced_allowed: frozenset`,
placed beside `reduced_dispatch` — the data and its dispatch then live in the
same place. AITD1's value moves verbatim from `engine/life.py:172`:

```python
# life.cpp:522-716: the only opcodes FITD's reduced switch has cases for
REDUCED_ALLOWED = frozenset({1, 2, 3, 13, 15, 24, 28, 31, 40, 47, 48, 49, 54, 55, 67, 74})
```

`engine/life.py` deletes the module constant and reads
`game.profile.reduced_allowed` in `process_life`. **The guard and its error
message stay in `engine/`, verbatim** — the structural invariant ("a
world-object op on an out-of-floor object must be in the allowed set") is the
engine's, only its per-game data moves. A second game inherits the raise for
free.

Pinned in `tests/test_game_profile.py`: the exact 16-element set with the
`life.cpp:522-716` citation, alongside the existing `reduced_dispatch` pin.

### Stub-profile fallout

Both new fields are required, so `tests/test_life_vm.py:221`'s stub
`GameProfile` gains `palette_entry=3, reduced_allowed=frozenset()`. That is
the only stub profile in the suite. Making the fields required rather than
defaulted is deliberate: a default of `3` or of AITD1's opcode set living in
`games/base.py` would be the same hard-code one directory over.

## 3 — The `profile` fixture

`tests/conftest.py` gains:

```python
@pytest.fixture
def profile():
    """The GameProfile under test. AITD1 today; a second game would
    parametrize here. Tests that assert AITD1's *identity* -- its pak names,
    opcode table, CVar list -- import AITD1 directly instead
    (tests/test_game_profile.py)."""
    from PyAitD.games.aitd1.profile import AITD1
    return AITD1
```

### The rewrite

Measured across `tests/`, excluding `test_game_profile.py`: **325**
constructor sites (`init_game(data_dir, AITD1, ...)`,
`Assets(data_dir, AITD1, ...)`, `Game(data_dir, AITD1, ...)`), **17** attribute
reads (12 `AITD1.cvar_index(...)`, 3 `AITD1.intro_start`, 2
`AITD1.game_start`), and 4 further references — 346 in-body occurrences over
**38 files**, plus 40 `from PyAitD.games.aitd1.profile import AITD1` lines to
delete. All become `profile`.

**Three occurrences must not be rewritten:** the `AITD1.cpp` FITD citations in
comments. A naive `s/AITD1/profile/` corrupts them into `profile.cpp`. Any
rewrite must match `AITD1` not followed by `.cpp`, and the diff must be read
for it.

The edit is mechanical because of a structural fact verified by an `ast` scan
of `tests/`: **every** test function that references `AITD1` already takes
`data_dir`, except the seven in `test_game_profile.py` (excluded by design)
and one outlier named below. So the signature rewrite is uniformly
`def test_x(data_dir` → `def test_x(data_dir, profile`, and the
now-unused `from PyAitD.games.aitd1.profile import AITD1` line is dropped
from each rewritten file.

Three groups need individual attention rather than the uniform rule:

- **Fourteen module-level helpers** that take `data_dir` and construct a game
  — `_venue(data_dir)`, `boot_intro(data_dir, hero)`, `_settled_venue`,
  `_live_actors`, `_thrown_game`, `_spawned`, `_game_over_session`,
  `_make_game`, `_hero_agent`, `_cross_room_target_setup`, `_click_to_attack`,
  `_latched_attack`, `_boot`, and `_confirm_emily_events` — gain an explicit
  `profile` parameter, threaded from each caller. They are not test functions,
  so they cannot request the fixture.
- **`test_play_loop.py:589`** (`test_hero_branch_builds_its_resolver_...`)
  takes only `monkeypatch` and needs no game data; it takes `profile` directly
  with no `data_dir` anchor. It is also one of the 20 `main.Floor` sites from
  item 1.
- **Two nested closures** in `test_shell_journeys.py` (`observe_tick`) close
  over the enclosing test's `profile` rather than taking a parameter.

### Excluded

- `tests/test_game_profile.py` — its entire job is pinning AITD1's identity;
  a fixture would make its assertions circular.
- `tests/test_life_vm.py`'s stub `GameProfile` — not AITD1.

### What this does and does not buy

It removes 40 concrete-profile import lines from 38 files and makes the suite's construction
idiom uniform. It does **not** make the tests portable to a second game: they
still assert AITD1-specific golden values (tick numbers, room indices, text
ids). The fixture docstring says so explicitly, so nobody reads `profile` as a
portability claim it does not support.

### Acceptance

Purely mechanical, so the check is mechanical:

- `pytest --collect-only -q` reports an identical test count before and after.
- The full suite reports identical outcome counts before and after
  (re-measured at implementation time, not pinned here, since unrelated work
  may land first).
- `make test-engine`, `test-render`, `test-shell`, `test-tools`, `test-meta`,
  `test-journey` each report the same counts as before.

## 4 — Folding the purity probes

`tests/purity.py` is unchanged: it keeps `PRESENTATION` and
`assert_presentation_free`, which `test_layering.py` already imports
`PRESENTATION` from.

`tests/test_layering.py` gains one parametrized test over a table. Each row
carries its own `forbidden` tuple, because `app/config`'s probe is
pygame-only rather than the full presentation set:

```python
# The runtime twin of the static import scan above: a module that passes the
# ast check can still pull the presentation layer in through a transitive
# import, so each of these is imported in a fresh interpreter.
PRESENTATION_FREE = (
    ("PyAitD.engine.navigate", PRESENTATION, ""),
    ("PyAitD.engine.navmesh", PRESENTATION,
     " — the mesh must stay importable without the presentation layer so it can build headless"),
    ("PyAitD.engine.picking", PRESENTATION,
     " — picking is pure math and must not need a window; the shell passes it logical coordinates"),
    ("PyAitD.engine.playworld,PyAitD.engine.anim_action", PRESENTATION,
     " — the tick must stay importable without the presentation layer so it can run headless"),
    ("PyAitD.games.aitd1.mouse_contract", PRESENTATION, ""),
    ("PyAitD.app.config", ("pygame",), ""),
)


@pytest.mark.parametrize(
    "modules, forbidden, why", PRESENTATION_FREE,
    ids=[row[0] for row in PRESENTATION_FREE],
)
def test_module_imports_stay_presentation_free(modules, forbidden, why):
    assert_presentation_free(*modules.split(","), forbidden=forbidden, why=why)
```

Every `why` string moves verbatim from its current site; the two empty ones
are empty today.

The six tests are deleted from `test_navigate.py`, `test_navmesh.py`,
`test_picking.py`, `test_playworld.py`, `test_mouse_only.py` and
`test_config.py`. Each file keeps its own `from tests.purity import
assert_presentation_free` line only if something else in it still uses the
helper — nothing does, so all six imports go.

### Group-count effect

Six tests move out of the `engine` / `shell` groups into `meta`
(`test_layering.py` is marked `meta`). `make test-shell` and `make
test-engine` lose tests; `make test-meta` gains six parametrized cases. The
group-enforcement pins in `tests/test_test_groups.py` are file-level — they
assert which *files* a legacy alias selects — so moving tests between files
does not touch them. No `pytestmark` changes.

### Why a literal table and not a derived one

Probing every module under `engine/` and `games/` would be exhaustive but
costs roughly sixty subprocess launches per run, seconds added to every `make
test-meta`. The static `ast` scan already covers every module cheaply; the
subprocess probes exist to catch what the static scan cannot — a *transitive*
import — and are worth paying for only on the modules whose headless
importability is load-bearing. The table is that list, and each row says why.

## Sequencing

One branch, four commits, the full suite green between each:

1. **Item 2** (`reduced_allowed`) — smallest, touches one engine module, one
   profile, one pin, one stub.
2. **Item 1** (`palette_entry`, `load_floor`) — the 20 monkeypatch migrations
   make this the largest real-logic change.
3. **Item 4** (purity table) — self-contained test restructuring.
4. **Item 3** (`profile` fixture) — 346 mechanical line changes, landed last
   so its churn never obscures a real diff during review.

## Files

| file | change |
|---|---|
| `PyAitD/games/base.py` | `palette_entry: int`, `reduced_allowed: frozenset`; docstring seam note updated |
| `PyAitD/games/aitd1/profile.py` | `palette_entry=3`, `reduced_allowed=REDUCED_ALLOWED` with the `life.cpp` citation |
| `PyAitD/engine/floor.py` | constants deleted; `Floor(data_dir, number, profile)` |
| `PyAitD/engine/assets.py` | `GAME_PALETTE_ENTRY` deleted; reads `profile.palette_entry` |
| `PyAitD/engine/life.py` | `_REDUCED_ALLOWED` deleted; guard reads `game.profile.reduced_allowed` |
| `PyAitD/engine/game.py` | `Game.load_floor`; `rooms_of_floor` deliberately does not route through it, and keeps constructing `Floor` itself |
| `PyAitD/app/shell.py` | 4 `Floor(...)` sites → `game.load_floor(...)`; `Floor` import dropped |
| `tools/prove_intro.py`, `tools/prove_graphics.py`, `tools/prove_mouse.py` | use `game.load_floor` |
| `tools/export_backgrounds.py` | resolves the profile once, passes it to `Floor` |
| `tests/conftest.py` | `profile` fixture |
| `tests/test_layering.py` | `PRESENTATION_FREE` table + parametrized probe |
| `tests/test_game_profile.py` | pins both new fields |
| `tests/test_life_vm.py` | stub profile gains both fields |
| `tests/test_play_loop.py`, `test_runtime_modes.py`, `test_main.py`, `test_shell_journeys.py` | 20 `main.Floor` patches migrated |
| `tests/test_navigate.py`, `test_navmesh.py`, `test_picking.py`, `test_playworld.py`, `test_mouse_only.py`, `test_config.py` | purity probes removed |
| `tests/` (38 files) | `AITD1` → `profile` fixture |
| `AGENTS.md` | known-seams bullet drops the `floor.py` palette and `_REDUCED_ALLOWED` entries |
| `CONTEXT.md` | `load_floor` named as the floor-loading seam |
