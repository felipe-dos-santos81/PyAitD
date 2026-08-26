# Intro Cutscene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After character confirmation, play the script-driven floor-7 opening (car → letter → floors 3, 2, 1) the way FITD's `startGame(7, 1, 0)` does, then hand over to the attic; any key or click skips it.

**Architecture:** Engine: a `start_game` staging primitive (FITD `startGame` minus `PlayWorld`), a one-line spawn-request fix in the reduced `LM_STAGE`, a `Game.allow_system_menu` flag that turns the cutscene's terminal `flag_game_over` into a `CutsceneFinished` effect, and two `GameProfile` fields. App: `_hero_branch` boots the intro instead of the attic, the event loop treats every key/click as a skip while `session.cutscene`, and a new atomic branch replaces the game with the attic start when the cutscene ends.

**Tech Stack:** Python 3.12, NumPy, pygame-ce (app only), pytest. No new dependency.

**Spec:** `docs/superpowers/specs/2026-08-26-intro-cutscene-design.md`

## Global Constraints

- `# SPDX-License-Identifier: GPL-2.0-only` first line of every new Python file.
- Every engine change cites FITD `file:line`; game facts (`(7, 1)`, `(0, 0)`) live in `GameProfile`, never as literals in `engine/`.
- `engine/` and `games/` stay pygame-free (`tests/test_layering.py`, `tests/purity.py`).
- Golden ticks pinned from the 2026-08-26 spike: letter `ShowPicture` at tick 1081; floor changes 7→3 at 3217, 3→2 at 4919, 2→1 at 5652; `flag_game_over` at 7293. A disagreement is traced through FITD, never re-guessed.
- The reduced `LM_STAGE` fix raises the existing spawn request; it does **not** make the scan unconditional (`ponytail:` with `mainLoop.cpp:249` as the upgrade path).
- Skip = any `KEYDOWN`, left `MOUSEBUTTONDOWN` or touch during the cutscene (`mainLoop.cpp:71-89`); `QUIT` and focus events keep their normal handling.
- Audio stays on the M4b stubs.
- Depends on the startup-menu plan (`session.booted_via_menu`, `open_startup_menu`) and the screen-overrides plan (`render_active_mode(..., resolver)`).
- Any test touching pygame runs with `SDL_VIDEODRIVER=dummy`; game-data tests use `data_dir`.
- Run `.venv/bin/pytest -q` before every commit; never mass-reformat.

---

### Task 1: Profile fields `intro_start` and `game_start`

**Files:**
- Modify: `PyAitD/games/base.py:14-25`, `PyAitD/games/aitd1/profile.py:93-108`
- Test: `tests/test_game_profile.py`

**Interfaces:**
- Produces: `GameProfile.intro_start: tuple | None` (default `None`), `GameProfile.game_start: tuple` (default `(0, 0)`); AITD1 values `(7, 1)` and `(0, 0)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_game_profile.py`:

```python
def test_aitd1_start_floors_follow_startAITD1():
    # AITD1.cpp:352-361: startGame(7, 1, 0) is the intro, startGame(0, 0, 1) the game
    assert AITD1.intro_start == (7, 1)
    assert AITD1.game_start == (0, 0)
    fields = {f.name: f for f in dataclasses.fields(AITD1)}
    assert fields["intro_start"].default is None
    assert fields["game_start"].default == (0, 0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_game_profile.py -q`
Expected: FAIL — `AttributeError: 'GameProfile' object has no attribute 'intro_start'`.

- [ ] **Step 3: Implement**

`PyAitD/games/base.py` — add after `debug_venues`:

```python
    # (stage, room) FITD's per-game boot passes to startGame (AITD1.cpp:352-361):
    # the scripted opening with allowSystemMenu=0, or None when the game has
    # none, and the playable start with allowSystemMenu=1.
    intro_start: tuple | None = None
    game_start: tuple = (0, 0)
```

`PyAitD/games/aitd1/profile.py` — add to the `AITD1 = GameProfile(...)` call:

```python
    intro_start=(7, 1),
    game_start=(0, 0),
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/test_game_profile.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/games/base.py PyAitD/games/aitd1/profile.py tests/test_game_profile.py
git commit -m "feat: GameProfile.intro_start/game_start pinned to AITD1's startGame calls"
```

---

### Task 2: `start_game` staging primitive

**Files:**
- Modify: `PyAitD/engine/game.py` (after `enter_floor_start`)
- Test: `tests/test_floor_start.py`

**Interfaces:**
- Produces: `game.start_game(game, stage, room)`; no return. Postconditions: `current_camera_target_actor == current_world_target == -1`; `current_floor == new_num_etage == stage`; `flag_change_etage == 0`; `current_room == room`; `new_num_salle == room`; `new_num_camera == 0`; `flag_init_view == 2`; `num_camera == -1`; `flag_genere_aff_list == 0`; `floor_start is None`; actors respawned for `stage`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_floor_start.py`:

```python
from PyAitD.engine.game import start_game


def test_start_game_stages_a_floor_like_fitd_startGame(data_dir):
    # main.cpp:4134 startGame + initVars (main.cpp:1235-1236): targets reset,
    # floor and room staged, active list regenerated, hero left where world
    # data put it (stage 0) -- never relocated onto the staged floor.
    game = init_game(data_dir, AITD1, hero=0)
    hero_idx = game.current_camera_target_actor
    assert game.actors[hero_idx].index_in_world == 1
    start_game(game, 7, 1)
    assert (game.current_camera_target_actor, game.current_world_target) == (-1, -1)
    assert (game.current_floor, game.new_num_etage, game.flag_change_etage) == (7, 7, 0)
    assert (game.current_room, game.new_num_salle, game.new_num_camera) == (1, 1, 0)
    assert (game.flag_init_view, game.num_camera, game.flag_genere_aff_list) == (2, -1, 0)
    assert game.floor_start is None
    live = {a.index_in_world for a in game.actors if a.index_in_world != -1}
    assert 1 not in live                       # the hero object stays on stage 0
    assert 286 in live and game.actors[game.world_objects[286].obj_index].life == 546


def test_start_game_on_the_attic_matches_init_game_floor_state(data_dir):
    game = init_game(data_dir, AITD1, hero=1)
    start_game(game, 0, 0)
    assert (game.current_floor, game.current_room) == (0, 0)
    assert game.world_objects[1].obj_index != -1   # hero live on its own floor
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_floor_start.py -q -k start_game`
Expected: FAIL — `ImportError: cannot import name 'start_game'`.

- [ ] **Step 3: Implement**

In `PyAitD/engine/game.py`, after `enter_floor_start`:

```python
def start_game(game, stage, room):
    # startGame (main.cpp:4134) minus PlayWorld: initVars resets the camera
    # and world targets (main.cpp:1235-1236), LoadEtage(stage), NumCamera=-1,
    # ChangeSalle(room), NewNumCamera=0, FlagInitView=2. The hero is NOT
    # relocated: world data decides which objects live on `stage`. A staged
    # start has no restart point (floor_start) until a script sets one.
    game.current_camera_target_actor = -1
    game.current_world_target = -1
    game.current_floor = game.new_num_etage = stage
    game.flag_change_etage = 0
    change_salle(game, room)
    game.new_num_salle = room
    game.new_num_camera = 0
    game.flag_init_view = 2
    spawn_stage_actors(game)
    game.flag_genere_aff_list = 0
    game.num_camera = -1
    game.floor_start = None
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/test_floor_start.py tests/test_game.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/game.py tests/test_floor_start.py
git commit -m "feat: engine.game.start_game, the FITD startGame staging primitive"
```

---

### Task 3: Reduced `LM_STAGE` raises the spawn request

**Files:**
- Modify: `PyAitD/games/aitd1/life_reduced.py:37-42`
- Test: `tests/test_life_ops.py`, `tests/test_intro.py` (new; real-data regression)

**Interfaces:**
- Consumes: `start_game` (Task 2).
- Produces: after a reduced `LM_STAGE` that places a world object on `game.current_floor`, `game.flag_genere_aff_list == 1`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_life_ops.py` (the reduced form is reached through the LIFE `OBJECT` prefix; use the same encoding the existing reduced-form tests in this file use — search for `reduced` — and if none exists, call the dispatcher directly):

```python
def test_reduced_stage_onto_the_current_floor_requests_a_spawn(data_dir):
    # FITD regenerates the active list every frame (mainLoop.cpp:249,
    # GenereActiveList main.cpp:3959), so a world object moved onto the
    # current floor by the reduced LM_STAGE (life.cpp:620) spawns next frame.
    # This port gates the scan on flag_genere_aff_list: the reduced op must
    # raise it.
    from types import SimpleNamespace
    from PyAitD.games.aitd1.life_reduced import reduced_dispatch
    game = init_game(data_dir, AITD1, hero=0)
    game.flag_genere_aff_list = 0
    vm = SimpleNamespace(game=game, script=struct.pack("<5h", 0, 2, 10, 20, 30), pc=0)
    reduced_dispatch(vm, 47, 288)
    w = game.world_objects[288]
    assert (w.stage, w.room, w.x, w.y, w.z) == (0, 2, 10, 20, 30)
    assert game.flag_genere_aff_list == 1
    game.flag_genere_aff_list = 0
    vm = SimpleNamespace(game=game, script=struct.pack("<5h", 5, 0, 0, 0, 0), pc=0)
    reduced_dispatch(vm, 47, 288)
    assert game.flag_genere_aff_list == 0    # another floor: no request
```

`read_s16` (`engine/life.py:43`) reads `vm.script` at `vm.pc`.

Create `tests/test_intro.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""The floor-7 opening: FITD startGame(7, 1, 0) (AITD1.cpp:356). Real data;
golden ticks pinned from the 2026-08-26 headless spike."""
import pytest

from PyAitD.engine.floor import Floor
from PyAitD.engine.game import init_game, start_game
from PyAitD.engine.interaction import apply_reading_result
from PyAitD.engine.playworld import play_tick
from PyAitD.app.ui import InputBuffer, ReadingResult
from PyAitD.games.aitd1.profile import AITD1


def boot_intro(data_dir, hero=0):
    game = init_game(data_dir, AITD1, hero=hero)
    start_game(game, *AITD1.intro_start)
    return game, Floor(data_dir, game.current_floor)


def run_intro(data_dir, game, floor, ticks, on_modal=None):
    """Tick the cutscene, swapping Floor on floor changes like shell.run and
    auto-dismissing pictures. Returns (last_tick, floor, events)."""
    buf = InputBuffer()
    events = []
    t = -1
    for t in range(ticks):
        play_tick(game, floor, buf)
        if floor.number != game.current_floor:
            floor = Floor(data_dir, game.current_floor)
            events.append((t, "floor", game.current_floor, game.current_room))
        if game.mode.name != "PLAY":
            events.append((t, type(game.active_modal).__name__))
            if on_modal is not None and on_modal(game):
                break
            apply_reading_result(game, ReadingResult(True))
    return t, floor, events


def test_director_places_object_288_and_it_spawns(data_dir):
    game, floor = boot_intro(data_dir)
    run_intro(data_dir, game, floor, 1597)
    w = game.world_objects[288]
    assert (w.stage, w.room) == (7, 0)
    assert w.obj_index != -1 and game.actors[w.obj_index].life == 537
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_life_ops.py -q -k reduced_stage; .venv/bin/pytest tests/test_intro.py -q`
Expected: both FAIL (`flag_genere_aff_list == 0`; `obj_index == -1`).

- [ ] **Step 3: Implement**

`PyAitD/games/aitd1/life_reduced.py`, the `opcode == 47` branch:

```python
    elif opcode == 47:  # LM_STAGE
        w.stage = read_s16(vm)
        w.room = read_s16(vm)
        w.x = read_s16(vm)
        w.y = read_s16(vm)
        w.z = read_s16(vm)
        # FITD's GenereActiveList runs every frame (mainLoop.cpp:249; spawn
        # scan main.cpp:3959), so an object moved onto the current floor is
        # live next frame. This port gates that scan on flag_genere_aff_list
        # (playworld._genere_active_list): raise it here or the intro's
        # director (life 547 -> object 288) never spawns its next act.
        # ponytail: an unconditional per-frame scan is the faithful upgrade;
        # it changes spawn timing everywhere and the goldens pinned on it.
        if w.stage == vm.game.current_floor:
            vm.game.flag_genere_aff_list = 1
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/test_life_ops.py tests/test_intro.py tests/test_prove_m3a.py tests/test_m3b_attic.py tests/test_combat_journey.py -q`
Expected: PASS (attic and combat goldens unaffected: no reduced `LM_STAGE` onto the current floor occurs there — if one does and a golden moves, stop and trace it through FITD before touching the expectation).

- [ ] **Step 5: Commit**

```bash
git add PyAitD/games/aitd1/life_reduced.py tests/test_life_ops.py tests/test_intro.py
git commit -m "fix: reduced LM_STAGE onto the current floor requests the active-list spawn"
```

---

### Task 4: `allow_system_menu` and `CutsceneFinished`; headless intro journey

**Files:**
- Modify: `PyAitD/engine/game.py:135-150` (`Game.__init__`), `PyAitD/engine/effects.py`, `PyAitD/engine/playworld.py:438-447` (`_handoff_game_over`)
- Test: `tests/test_effects.py`, `tests/test_game_over.py`, `tests/test_intro.py`

**Interfaces:**
- Produces: `Game.allow_system_menu: bool = True`; `effects.CutsceneFinished` (frozen dataclass, no fields) → `GameMode.CUTSCENE_END`; `_handoff_game_over` opens `CutsceneFinished()` when `allow_system_menu` is False.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_effects.py`:

```python
def test_cutscene_finished_maps_to_its_mode():
    from PyAitD.engine.effects import CutsceneFinished, GameMode, MODAL_MODE
    assert MODAL_MODE[CutsceneFinished] is GameMode.CUTSCENE_END
```

Append to `tests/test_game_over.py`:

```python
def test_game_over_during_a_cutscene_is_cutscene_finished(data_dir, monkeypatch):
    from PyAitD.engine.effects import CutsceneFinished
    import PyAitD.engine.playworld as playworld
    game = init_game(data_dir, AITD1)
    game.allow_system_menu = False      # PlayWorld(allowSystemMenu=0): mainLoop.cpp:185 break, not death
    floor = Floor(data_dir, game.current_floor)
    monkeypatch.setattr(playworld, "run_life", lambda current, frame: setattr(current, "flag_game_over", 1) or True)
    monkeypatch.setattr(playworld, "life_gate", lambda actor: actor.index_in_world >= 0)
    assert play_tick(game, floor, InputBuffer()) is False
    assert game.active_modal == CutsceneFinished() and game.mode is GameMode.CUTSCENE_END
    assert game.flag_game_over == 0
```

Append to `tests/test_intro.py`:

```python
LETTER_TICK = 1081
FLOOR_TICKS = ((3217, 3, 1), (4919, 2, 2), (5652, 1, 7))
END_TICK = 7293


def test_intro_runs_to_cutscene_finished_at_the_pinned_ticks(data_dir):
    from PyAitD.engine.effects import CutsceneFinished
    game, floor = boot_intro(data_dir)
    game.allow_system_menu = False
    last, floor, events = run_intro(
        data_dir, game, floor, END_TICK + 50,
        on_modal=lambda g: isinstance(g.active_modal, CutsceneFinished),
    )
    assert (LETTER_TICK, "ShowPicture") in events
    assert [e for e in events if e[1] == "floor"] == [(t, "floor", f, r) for t, f, r in FLOOR_TICKS]
    assert last == END_TICK and isinstance(game.active_modal, CutsceneFinished)
    assert not any(e[1] == "GameOver" for e in events)


@pytest.mark.parametrize("hero", (0, 1))
def test_intro_boots_for_both_heroes(data_dir, hero):
    game, floor = boot_intro(data_dir, hero)
    game.allow_system_menu = False
    run_intro(data_dir, game, floor, 200)
    assert game.current_floor == 7 and game.mode.name == "PLAY"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_effects.py tests/test_game_over.py tests/test_intro.py -q`
Expected: FAIL (`ImportError: CutsceneFinished`).

- [ ] **Step 3: Implement**

`PyAitD/engine/effects.py` — `GameMode` gains `CUTSCENE_END = auto()`; after `GameOver`:

```python
@dataclass(frozen=True)
class CutsceneFinished:
    # PlayWorld(allowSystemMenu=0) breaks on FlagGameOver (mainLoop.cpp:185):
    # the scripted opening's terminal, not a death. The app replaces the game.
    pass
```

`ModalEffect` adds `| CutsceneFinished`; `MODAL_MODE[CutsceneFinished] = GameMode.CUTSCENE_END`.

`PyAitD/engine/game.py` `Game.__init__`, next to `self.status_screen_allowed = 1`:

```python
        # startGame's allowSystemMenu (main.cpp:4134): False for the scripted
        # opening, where FlagGameOver ends the sequence (CutsceneFinished)
        # instead of killing the player, and any input ends it early.
        self.allow_system_menu = True
```

`PyAitD/engine/playworld.py` `_handoff_game_over`:

```python
    game.flag_game_over = 0
    if not game.allow_system_menu:
        game.open_modal(CutsceneFinished())
        return False
    game.open_modal(GameOver())
    return False
```

(import `CutsceneFinished` alongside `GameOver`.)

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/test_effects.py tests/test_game_over.py tests/test_intro.py tests/test_mouse_only.py -q`
Expected: the first three PASS; `tests/test_mouse_only.py::test_every_mode_declares_exactly_the_routes_available_in_it` FAILS on `CUTSCENE_END` — fixed in Task 5 (the contract entry belongs with the shell route). Confirm that is the only failure.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/effects.py PyAitD/engine/game.py PyAitD/engine/playworld.py tests/test_effects.py tests/test_game_over.py tests/test_intro.py
git commit -m "feat: Game.allow_system_menu; a cutscene's game-over is CutsceneFinished"
```

---

### Task 5: Shell — cutscene boot, skip input, attic hand-over, `--skip-intro`

**Files:**
- Modify: `PyAitD/app/shell.py` (`parse_args`, `main`, `_hero_branch`, new `_cutscene_end_branch`, `run`, `route_command`, `route_mouse`, `render_active_mode`, `replacement_session`), `PyAitD/app/ui.py` (`ModalSession`), `PyAitD/games/aitd1/mouse_contract.py`
- Test: `tests/test_runtime_modes.py`, `tests/test_main.py`, `tests/test_mouse_only.py`, `tests/test_shell_journeys.py`

**Interfaces:**
- Consumes: Tasks 1–4; `session.booted_via_menu`, `open_startup_menu` (startup-menu plan).
- Produces:
  - `ModalSession.cutscene: bool = False`, `ModalSession.skip_cutscene: bool = False`, `ModalSession.skip_intro: bool = False` (CLI, carried across `replacement_session`).
  - `parse_args`: `--skip-intro` (store_true).
  - `shell._boot_hero(game, renderer, session, input_buffer, hero, *, cutscene) -> tuple` — the replace tuple `_hero_branch` returns today; `cutscene=True` calls `start_game(new_game, *profile.intro_start)` and sets `new_game.allow_system_menu = False`, `new_session.cutscene = True`.
  - `shell._cutscene_end_branch(game, renderer, session, input_buffer) -> tuple | None` — when `session.cutscene and (session.skip_cutscene or isinstance(game.active_modal, CutsceneFinished))`, returns `_boot_hero(..., hero=current CHOOSE_PERSO, cutscene=False)`.
  - `PlayerCapability.SKIP_CUTSCENE` routed in `GameMode.PLAY` and `GameMode.CUTSCENE_END`; `MODE_MOUSE_CAPABILITIES[GameMode.CUTSCENE_END] = {SKIP_CUTSCENE, DISMISS_SETTINGS_ERROR, QUIT}`; `COMMAND_MOUSE_CAPABILITIES["ACCEPT"]` and `["CANCEL"]` gain it.

- [ ] **Step 1: Write the failing tests**

`tests/test_main.py` — add:

```python
def test_parse_args_skip_intro():
    assert parse_args([]).skip_intro is False
    assert parse_args(["--skip-intro"]).skip_intro is True
```

`tests/test_mouse_only.py::test_shell_modes_and_the_settings_notice_fulfill_the_mouse_contract` — add:

```python
    assert MODE_MOUSE_CAPABILITIES[GameMode.CUTSCENE_END] == frozenset({
        PlayerCapability.SKIP_CUTSCENE,
        PlayerCapability.DISMISS_SETTINGS_ERROR,
        PlayerCapability.QUIT,
    })
    assert PlayerCapability.SKIP_CUTSCENE in MODE_MOUSE_CAPABILITIES[GameMode.PLAY]
```

`tests/test_runtime_modes.py` — append:

```python
from PyAitD.app.shell import _boot_hero, _cutscene_end_branch
from PyAitD.engine.effects import CutsceneFinished


class _Renderer:
    def scene_thumbnail(self):
        return np.zeros((200, 320, 3), np.uint8)


def test_boot_hero_cutscene_stages_the_intro(data_dir):
    game = init_game(data_dir, AITD1)
    session = ModalSession()
    replaced = _boot_hero(game, _Renderer(), session, InputBuffer(), 1, cutscene=True)
    new_game, new_floor, new_session = replaced[0], replaced[1], replaced[2]
    assert (new_game.current_floor, new_game.current_room) == AITD1.intro_start
    assert new_floor.number == 7
    assert new_game.allow_system_menu is False and new_session.cutscene is True
    assert new_game.cvars[AITD1.cvar_index("CHOOSE_PERSO")] == 1


def test_boot_hero_plain_boots_the_attic(data_dir):
    game = init_game(data_dir, AITD1)
    replaced = _boot_hero(game, _Renderer(), ModalSession(), InputBuffer(), 0, cutscene=False)
    new_game, new_session = replaced[0], replaced[2]
    assert (new_game.current_floor, new_game.current_room) == AITD1.game_start
    assert new_game.allow_system_menu is True and new_session.cutscene is False


def test_cutscene_end_branch_hands_over_to_the_attic_with_the_same_hero(data_dir):
    game = init_game(data_dir, AITD1, hero=1)
    session = ModalSession(cutscene=True)
    assert _cutscene_end_branch(game, _Renderer(), session, InputBuffer()) is None
    game.open_modal(CutsceneFinished())
    replaced = _cutscene_end_branch(game, _Renderer(), session, InputBuffer())
    assert replaced is not None
    new_game, new_session = replaced[0], replaced[2]
    assert new_game.cvars[AITD1.cvar_index("CHOOSE_PERSO")] == 1
    assert (new_game.current_floor, new_game.current_room) == AITD1.game_start
    assert new_session.cutscene is False and new_game.active_modal is None


def test_skip_flag_ends_the_cutscene_from_play(data_dir):
    game = init_game(data_dir, AITD1)
    session = ModalSession(cutscene=True, skip_cutscene=True)
    assert _cutscene_end_branch(game, _Renderer(), session, InputBuffer()) is not None


def test_cutscene_swallows_play_commands_and_marks_skip(data_dir):
    game = init_game(data_dir, AITD1)
    session = ModalSession(cutscene=True)
    assert route_command(game, session, Command.CANCEL) is True
    assert game.active_modal is None and session.skip_cutscene is True   # no system menu opened


def test_cutscene_finished_renders_the_frozen_scene(data_dir):
    pygame.font.init()
    game = init_game(data_dir, AITD1)
    game.open_modal(CutsceneFinished())
    frame = render_active_mode(game, ModalSession(cutscene=True), _Renderer())
    assert frame.shape == (200, 320, 4) and frame[..., 3].max() == 0      # transparent: scene shows through
```

- [ ] **Step 2: Run to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_main.py tests/test_mouse_only.py tests/test_runtime_modes.py -q -k "skip_intro or cutscene or boot_hero or shell_modes"`
Expected: FAIL (`ImportError: _boot_hero`).

- [ ] **Step 3: Implement `ModalSession` and the contract**

`PyAitD/app/ui.py` `ModalSession` — add:

```python
    cutscene: bool = False        # PlayWorld(allowSystemMenu=0): input skips, nothing routes to PLAY
    skip_cutscene: bool = False
    skip_intro: bool = False      # --skip-intro: boot the attic directly after the selector
```

`PyAitD/games/aitd1/mouse_contract.py` — `PlayerCapability.SKIP_CUTSCENE = auto()`; route `MouseRoute("left_click", "anywhere during the opening cutscene", frozenset({GameMode.PLAY, GameMode.CUTSCENE_END}))`; add it to `MODE_MOUSE_CAPABILITIES[GameMode.PLAY]`, define `GameMode.CUTSCENE_END: frozenset({PlayerCapability.SKIP_CUTSCENE, PlayerCapability.DISMISS_SETTINGS_ERROR, PlayerCapability.QUIT})`, and add `SKIP_CUTSCENE` to `COMMAND_MOUSE_CAPABILITIES["ACCEPT"]` and `["CANCEL"]`.

- [ ] **Step 4: Implement the shell**

`parse_args`: `p.add_argument("--skip-intro", action="store_true", help="boot the attic directly after character select (skips the floor-7 opening)")`. In `main`, after `session.settings = apply_render_overrides(...)`: `session.skip_intro = args.skip_intro`. `replacement_session` copies `skip_intro=session.skip_intro` (and `booted_via_menu`).

Refactor `_hero_branch` into a reusable boot:

```python
def _boot_hero(game, renderer, session, input_buffer, hero, *, cutscene):
    """Build the replace tuple run() adopts: a fresh game for `hero`, staged
    on profile.intro_start (cutscene, allowSystemMenu=0) or on the attic
    init_game already stages (profile.game_start)."""
    from PyAitD.engine.game import start_game
    _take_over_play_input(game, session, input_buffer)
    try:
        new_game = init_game(game._data_dir, game.profile, hero=hero)
        if cutscene:
            start_game(new_game, *game.profile.intro_start)
            new_game.allow_system_menu = False
        new_floor = Floor(new_game._data_dir, new_game.current_floor)
    except PakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return (None, None, None, None, 0, [], None, None, None, 2, None)
    new_game.trace = game.trace
    new_game.input_mode = game.input_mode
    new_session = replacement_session(session)
    new_session.cutscene = cutscene
    input_buffer = InputBuffer()
    configure_session_input(new_session, input_buffer)
    new_game.num_camera = new_game.new_num_camera
    new_game.flag_init_view = 0
    new_resolver = _resolver_for(new_game.assets, session.settings.render.override_dir)
    scene_frame, draw_list = _scene_frame(new_game, new_floor, renderer, new_resolver)
    return (
        new_game, new_floor, new_session, input_buffer, 0,
        draw_list, None, scene_frame, pygame.time.get_ticks(), 0, new_resolver,
    )


def _hero_branch(game, renderer, session, input_buffer=None):
    if session.pending_hero is None:
        return None
    cutscene = game.profile.intro_start is not None and not session.skip_intro
    return _boot_hero(game, renderer, session, input_buffer, session.pending_hero, cutscene=cutscene)


def _cutscene_end_branch(game, renderer, session, input_buffer=None):
    # PlayWorld(allowSystemMenu=0) returned (FlagGameOver, or any key/click,
    # mainLoop.cpp:71-89): startAITD1 then calls startGame(0, 0, 1) (AITD1.cpp:361).
    from PyAitD.engine.effects import CutsceneFinished
    if not session.cutscene:
        return None
    if not (session.skip_cutscene or isinstance(game.active_modal, CutsceneFinished)):
        return None
    hero = game.cvars[game.profile.cvar_index("CHOOSE_PERSO")]
    return _boot_hero(game, renderer, session, input_buffer, hero, cutscene=False)
```

Note `new_game.num_camera = new_game.new_num_camera` is what today's `_hero_branch` does; for the cutscene `start_game` leaves `num_camera = -1` and `new_num_camera = 0`, so this line stages camera 0 exactly as FITD's `InitView` does after `startGame`.

In `run()`:

- Event loop: right after `captured, capture_running = _capture_keydown(...)` / `continue`, add:

```python
            if session.cutscene and (
                event.type == pygame.KEYDOWN
                or (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1)
                or event.type == pygame.FINGERDOWN
            ):
                session.skip_cutscene = True
                continue
```

- Replace branch: `replaced = _hero_branch(...)`; `if replaced is None: replaced = _cutscene_end_branch(game, renderer, session, input_buffer)`; `if replaced is None: replaced = _restart_branch(...)`.
- Commands: wrap the `if input_buffer.commands:` body so that when `session.cutscene` the command is popped and dropped (`session.skip_cutscene = True` is already set by the KEYDOWN above; commands only come from keys).
- HUD/cursor: `available = inventory_hud_available(game) and not session.cutscene`; `software_cursor = (... and not session.cutscene)`.

`route_command`: at the top, after the `TOGGLE_INPUT_MODE` branch:

```python
    if session.cutscene:
        session.skip_cutscene = True
        return True
```

`route_mouse`: after `if logical_pos is None or game.active_modal is None: return True`, add `if isinstance(effect, CutsceneFinished): session.skip_cutscene = True; return True` (import the effect). `render_active_mode`: `if isinstance(effect, CutsceneFinished): return transparent_canvas()` (the last PLAY frame stays composed underneath, like `render_game_over` before `ready`).

- [ ] **Step 5: Run tests**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_main.py tests/test_mouse_only.py tests/test_runtime_modes.py tests/test_shell_journeys.py -q`
Expected: PASS. Existing journeys that confirm a hero and expect the attic on the first PLAY tick must set `session.skip_intro = True` (or build the session with it) — update each such journey in `tests/test_shell_journeys.py` and `tests/test_mouse_only.py` with a one-line comment "`skip_intro`: this journey tests the attic, not the opening".

- [ ] **Step 6: Commit**

```bash
git add PyAitD/app/shell.py PyAitD/app/ui.py PyAitD/games/aitd1/mouse_contract.py tests/test_main.py tests/test_mouse_only.py tests/test_runtime_modes.py tests/test_shell_journeys.py
git commit -m "feat: play the floor-7 opening after character select; any key or click skips it; --skip-intro"
```

---

### Task 6: Real-loop journeys (full run and skip)

**Files:**
- Modify: `tests/test_shell_journeys.py`

- [ ] **Step 1: Write the journeys**

Append (uses the file's helpers; `_run_shell` monkeypatches `_scene_frame`, so floors 7/3/2/1 never render here — Task 7 covers rendering):

```python
from PyAitD.engine.effects import CutsceneFinished


def _confirm_emily_events():
    return [
        [_left_click((160, 100))], [_left_click((160, 100))],              # title, credits
        [_left_click(StartupLayout.ROWS[StartupRow.NEW_GAME.value].center)],
        [_left_click(CharacterLayout.PORTRAITS[0].center)],
        [_left_click((160, 100))],
    ]


def test_journey_opening_plays_to_the_end_then_the_attic(data_dir, monkeypatch):
    game = init_game(data_dir, AITD1)
    game.open_modal(ShowTitle())
    session = load_runtime_session(None)
    floors = []
    frames = iter(_confirm_emily_events() + [[]] * 400 + [[_quit()]])
    def next_events():
        return next(frames, [_quit()])
    def observe_tick(game_, floor, buf):
        if not floors or floors[-1] != floor.number:
            floors.append(floor.number)
        return real_play_tick(game_, floor, buf)
    # 400 frames x 250 ms cap = 12.5 game-seconds per frame max; the accumulator
    # runs up to 12 ticks per frame, so 400 frames cover the 7293-tick opening.
    ticks = itertools.count(0, 250)
    import PyAitD.app.shell as main
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(ticks))
    _run_shell(monkeypatch, game, session, next_events, observe_tick=observe_tick)
    assert floors[:4] == [7, 3, 2, 1] and floors[-1] == 0


def test_journey_a_click_skips_the_opening(data_dir, monkeypatch):
    game = init_game(data_dir, AITD1)
    game.open_modal(ShowTitle())
    session = load_runtime_session(None)
    floors = []
    frames = iter(_confirm_emily_events() + [[], [], [_left_click((10, 10))], [], [], [_quit()]])
    def next_events():
        return next(frames, [_quit()])
    def observe_tick(game_, floor, buf):
        floors.append(floor.number)
        return real_play_tick(game_, floor, buf)
    _run_shell(monkeypatch, game, session, next_events, observe_tick=observe_tick)
    assert 7 in floors and floors[-1] == 0
    assert game.mode is not GameMode.GAME_OVER
```

`_run_shell` sets its own `get_ticks` patch; the first journey re-patches it after (monkeypatch order matters: apply the 250 ms counter *inside* a wrapper passed to `_run_shell`, or extend `_run_shell` with a `tick_ms=20` parameter — do the latter and pass `tick_ms=250`).

- [ ] **Step 2: Run**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_shell_journeys.py -q -k opening`
Expected: PASS within ~10 s.

- [ ] **Step 3: Commit**

```bash
git add tests/test_shell_journeys.py
git commit -m "test: opening cutscene journeys — full run and click-to-skip"
```

---

### Task 7: `prove-intro` proof tool and docs

**Files:**
- Create: `tools/prove_intro.py`, `docs/intro-proof.md`, `docs/intro-proof/.gitkeep`
- Modify: `Makefile`, `AGENTS.md`, `CONTEXT.md`, `.gitignore` (add `docs/intro-proof/*.png`)
- Test: `tests/test_prove_intro.py`

**Interfaces:**
- Produces: `prove_intro.visited_cameras(data_dir) -> list[tuple[int, int, int]]` (`(tick, floor, cam_idx)` at every camera change, cutscene run headless to `CutsceneFinished`); `prove_intro.render_camera(data_dir, tick, floor, cam_idx, scale, ctx)` re-runs to `tick` and renders; `main(argv)` writes `intro-<floor>-<cam>.png` per visited camera and `intro-ticks.txt`, exit 3 without GL.

- [ ] **Step 1: Write the tests**

Create `tests/test_prove_intro.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
import pathlib

from tools.prove_intro import _parse_args, output_paths, visited_cameras


def test_parse_args_defaults():
    args = _parse_args(["some/data"])
    assert args.out == pathlib.Path("docs/intro-proof") and args.scale == 2


def test_visited_cameras_cover_every_intro_floor(data_dir):
    visits = visited_cameras(data_dir)
    assert [f for _, f, _ in visits][0] == 7
    assert {f for _, f, _ in visits} == {7, 3, 2, 1}
    assert visits == sorted(visits)
    for (tick, floor, cam), path in zip(visits, output_paths("x", visits)):
        assert path == pathlib.Path("x") / f"intro-{floor:02d}-{cam:03d}-{tick:05d}.png"
```

- [ ] **Step 2: Implement**

Create `tools/prove_intro.py` following `tools/prove_graphics.py`'s shape:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Render every camera the opening cutscene visits (floor 7 -> 3 -> 2 -> 1)
through the GL backend, one PNG per camera change, to --out (default
docs/intro-proof/). Also writes intro-ticks.txt with the visit list.
Never commit the PNGs: they are game data."""
import argparse
import pathlib
import sys

from PyAitD.render.asset_resolver import AssetResolver
from PyAitD.engine.effects import CutsceneFinished
from PyAitD.engine.floor import Floor
from PyAitD.engine.game import init_game, start_game
from PyAitD.engine.interaction import apply_reading_result
from PyAitD.engine.playworld import play_tick
from PyAitD.render.render_gl import GLBackend
from PyAitD.render.render_options import RenderOptions
from PyAitD.render.scene import build_frame
from PyAitD.app.ui import InputBuffer, ReadingResult
from PyAitD.games.aitd1.profile import AITD1
if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from tools.export_backgrounds import save_png  # noqa: E402

MAX_TICKS = 8000


def _boot(data_dir):
    game = init_game(data_dir, AITD1, hero=0)
    start_game(game, *AITD1.intro_start)
    game.allow_system_menu = False
    return game, Floor(data_dir, game.current_floor)


def _step(data_dir, game, floor):
    play_tick(game, floor, InputBuffer())
    if floor.number != game.current_floor:
        floor = Floor(data_dir, game.current_floor)
    if game.mode.name != "PLAY" and not isinstance(game.active_modal, CutsceneFinished):
        apply_reading_result(game, ReadingResult(True))
    return floor


def _camera_key(game, floor):
    if game.num_camera == -1:
        return None
    return (floor.number, floor.rooms[game.current_room].camera_indices[game.num_camera])


def visited_cameras(data_dir):
    game, floor = _boot(data_dir)
    visits, last = [], None
    for tick in range(MAX_TICKS):
        floor = _step(data_dir, game, floor)
        key = _camera_key(game, floor)
        if key is not None and key != last:
            visits.append((tick, key[0], key[1]))
            last = key
        if isinstance(game.active_modal, CutsceneFinished):
            break
    return visits


def render_camera(data_dir, tick, scale, ctx):
    game, floor = _boot(data_dir)
    for _ in range(tick + 1):
        floor = _step(data_dir, game, floor)
    frame, _ = build_frame(game, floor, AssetResolver(game.assets))
    backend = GLBackend(ctx, RenderOptions(scale=scale))
    try:
        backend.draw(frame)
        return backend.read_rgb()
    finally:
        backend.release()


def output_paths(out_dir, visits):
    out_dir = pathlib.Path(out_dir)
    return [out_dir / f"intro-{floor:02d}-{cam:03d}-{tick:05d}.png" for tick, floor, cam in visits]


def _parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("data", type=pathlib.Path)
    p.add_argument("--out", type=pathlib.Path, default=pathlib.Path("docs/intro-proof"))
    p.add_argument("--scale", type=int, default=2)
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    try:
        import moderngl
        ctx = moderngl.create_standalone_context(require=330)
    except Exception as exc:
        print(f"no standalone GL 3.3 context: {exc}", file=sys.stderr)
        return 3
    try:
        visits = visited_cameras(args.data)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "intro-ticks.txt").write_text("".join(f"{t} floor {f} camera {c}\n" for t, f, c in visits))
        for (tick, floor, cam), path in zip(visits, output_paths(args.out, visits)):
            save_png(path, render_camera(args.data, tick, args.scale, ctx))
            print(path)
    finally:
        ctx.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`render_camera` re-simulates from the start for every camera (≈20 cameras × ≤7300 ticks ≈ 30 s total); acceptable for a proof tool — note it in the docstring.

Makefile:

```make
prove-intro: install ## Opening cutscene proof: headless run to CutsceneFinished + one GL render per visited camera to docs/intro-proof/
	SDL_VIDEODRIVER=dummy $(PYTHON) -m pytest tests/test_intro.py -q && $(PYTHON) tools/prove_intro.py "$(data)"
```

`docs/intro-proof.md`: what the tool renders, the pinned tick table (1081 letter; 3217/4919/5652 floor changes; 7293 end), how to attest a windowed pass (`make run`, confirm the opening plays and a click skips to the attic), and a "status" line for the user to fill after watching it.

`AGENTS.md` Commands: `make prove-intro`; `make run` line: "title → menu → character select → opening cutscene (skip with any key/click, or `--skip-intro`)". `CONTEXT.md`: new "Opening cutscene boundary" section: `start_game` is the FITD `startGame` staging; `allow_system_menu` turns `flag_game_over` into `CutsceneFinished`; the reduced `LM_STAGE` spawn request and its ponytail; `session.cutscene` owns skip; `_boot_hero` is the one hero boot for both the intro and the attic.

`.gitignore`: `docs/intro-proof/*.png` and `docs/intro-proof/intro-ticks.txt`.

- [ ] **Step 3: Run**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_prove_intro.py tests/test_layering.py -q && make prove-intro`
Expected: tests PASS; the tool prints one path per visited camera (or exits 3 without GL — acceptable on CI, not on the dev machine).

- [ ] **Step 4: Full suite and proofs**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest -q && make prove && make prove-shell && make prove-mouse-only`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add tools/prove_intro.py tests/test_prove_intro.py docs/intro-proof.md docs/intro-proof/.gitkeep Makefile AGENTS.md CONTEXT.md .gitignore
git commit -m "proof: prove-intro renders every camera of the opening; docs for the cutscene boundary"
```
