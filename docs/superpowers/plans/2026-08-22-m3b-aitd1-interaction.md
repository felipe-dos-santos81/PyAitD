# M3b: AITD1 Interaction, Inventory, and Modal UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the opening attic fully interactive: objects can be found, accepted or refused, carried, selected, used, read, pictured, placed, and dropped without freezing input or restarting LIFE scripts.

**Architecture:** Keep the existing fixed-step game and renderer, and add a small typed boundary around them: `life_ops.py` emits effects, `life.py` suspends after consumed operands, `interaction.py` applies world rules and resumes LIFE frames, and `ui.py` renders modes and returns typed results. The single pygame outer loop remains the only event pump; held PLAY controls and one-shot modal commands are stored separately so catch-up ticks cannot replay an action.

**Tech Stack:** Python 3.12, pygame-ce 2.5.8, NumPy 2, ModernGL 5, pytest 8. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-22-aitd1-build-conclusion-design.md`

## Global Constraints

- Target is the single-player, windowed Apple Silicon application, using user-supplied original data without redistributing it.
- Preserve Python `>=3.12`, pygame-ce, ModernGL, NumPy, pytest, the existing PAK/ITD readers, 320x200 logical frame, fixed 50 Hz PLAY tick, and scalable window presentation.
- Add no dependency, generic scene framework, ECS, pygame sprite conversion, pygame-menu, or pygame_gui.
- Keep `# SPDX-License-Identifier: GPL-2.0-only` at the top of every new or modified Python source and test file.
- FITD at `/Users/felipe.dos.santos/code/theirs/FITD/FitdLib/` is the behavioral reference; relevant sources are `inventory.cpp`, `main.cpp`, `anim.cpp`, `life.cpp`, `mainLoop.cpp`, and `AITD1.cpp`.
- Pump `pygame.event.get()` exactly once per outer frame. Run fixed ticks only in `GameMode.PLAY`; modal modes continue pumping, rendering, quitting, and advancing their own elapsed time.
- Treat movement and held Action as level state. Treat inventory open, selection, acceptance, cancellation, and page navigation as edges consumed once.
- This input split follows current pygame-ce 2.5.8 documentation: the event queue supplies KEYDOWN/KEYUP edge events, while held movement state remains separately queryable. Ignore KEYDOWN events whose `repeat` attribute is true so OS key repeat cannot double-apply modal commands.
- pygame-ce `surfarray.array3d()` is width-major; Task 10 keeps the explicit axis swap at the Surface boundary so every engine-facing frame remains `(height, width, RGB)`.
- Every modal operation must have arrows/WASD plus Enter/Space/Escape routes and large single-left-click targets. Require no drag, double-click, precise pointing, hold, or simultaneous chord.
- `life_ops.py` may decode operands and mutate scalar engine state, but must not render, pump events, or call pygame. `ui.py` must not mutate world objects, actors, inventory membership, LIFE state, or found flags.
- Only one modal effect may be active. Opening a second modal without first suspending the current continuation raises `RuntimeError` naming both effect types.
- A suspended LIFE frame records owner actor, LIFE number, byte PC after the opcode operands, completion action, subject world object, and any temporary actor that must survive nested found-LIFE suspension.
- MESSAGE and MESSAGE_VALUE are immediate effects. FOUND, READ, and PICTURE are modal effects. PICTURE records its sample ID but does not play it; M4b owns audio.
- Port FITD's two inventories of thirty slots, first-object-at-slot-zero insertion rule, later-object-at-slot-one insertion rule, five displayed actions, weight CVar index 2, and found-flag mutations exactly.
- English is the M3b presentation language because `ENGLISH.PAK` is present and the language/configuration screen belongs to M4a. Decode its DOS text with CP437.
- Use ITD_RESS entries 6, 7, and 8 as letter, book, and notebook backgrounds. Use pygame-ce's built-in font for readable text; entry 5's custom bitmap-font renderer is outside this slice.
- Preserve all current user work. The starting tree has edits in `CONTEXT.md`, `maitd/__main__.py`, `maitd/mask.py`, `maitd/render.py`, `maitd/skel.py`, and their tests. Inspect `git diff` before each overlapping edit and stage only new M3b hunks with `git add -p`; never revert or silently include pre-existing hunks.
- Current regression baseline is `.venv/bin/pytest -q`: `187 passed, 1 skipped`. Every task keeps that baseline green in addition to its focused tests.
- `make prove` remains the real-data regression gate. Scene geometry, camera selection, masks, and actor rendering are unchanged except for the minimal `Renderer.compose_scene()` extraction required to add message/UI overlays before the one presentation call.
- Fall behavior remains in M3c, as assigned by the approved conclusion spec. This plan removes only the actor-contact portions of the current M3b simplification note.

## Graphify legacy evidence

The supplied graph at `/Users/felipe.dos.santos/code/theirs/FITD/graphify-out/graph.json` was built from FITD commit `543e22bc78b64405537ae545ecd382dcdf2c12b2`. Its report contains 1,234 nodes, 2,523 edges, and 79 communities; `processLife()` is the second-most-connected node with 57 edges. That fan-out is the reason this plan wraps the existing VM with continuations and typed effects instead of rewriting its dispatch table.

Use Graphify edges as navigation evidence, then verify exact mutation/order semantics at the linked source line. `EXTRACTED` edges are direct syntax evidence; `INFERRED` edges have 0.8 confidence and are not sufficient by themselves to change a golden assertion.

| M3b boundary | Graphify path and source anchors | Plan consequence |
|---|---|---|
| Main loop | `startAITD1()` → `PlayWorld()` (`AITD1.cpp:380`); `PlayWorld()` → `GereAnim()`, `GereDec()`, `processLife()`, `GereSwitchCamera()`, `AllRedraw()` (`mainLoop.cpp:136-270`) | Task 12 preserves this tick order while moving every event read and presentation into one pygame outer loop. |
| Found/take continuation | `GereAnim()` → `FoundObjet()` (`anim.cpp:452`) → `take()` (`inventory.cpp:629`) → `executeFoundLife()` (`main.cpp:3313`) → `processLife()` (`main.cpp:236`) | Tasks 2, 4, 7, and 11 keep the parent LIFE frame below the found-LIFE frame and complete TAKE only after the nested frame returns. |
| Script-driven interaction | `processLife()` → `FoundObjet()`, `take()`, `put()`, `drop()`, `PutAtObjet()`, `processInventory()`, `Lire()` (`life.cpp:1461-2470`) | Task 5 decodes only the interaction opcodes and delegates world/UI work through typed effects and `interaction.py`. |
| Inventory mutation | `processInventory()` → `executeFoundLife()` (`inventory.cpp:443`); `put()` → `DeleteInventoryObjet()` (`life.cpp:53`); `drop()` → `PutAtObjet()` (`life.cpp:63`); `PutAtObjet()` → `DeleteInventoryObjet()` (`main.cpp:3957`) | Task 4 centralizes insertion/removal and found-flag changes so all three legacy entry paths share one tested implementation. |
| Actor contacts | `PlayWorld()` → `GereAnim()` (`mainLoop.cpp:136`) → `CheckObjectCol()` (`anim.cpp:288`); `CheckObjectCol()` → `CopyZV()`, `AdjustZV()`, `CubeIntersect()` (`main.cpp:3262-3266`) | Task 7 adds cross-room ZV adjustment at the existing movement seam and leaves `manageFall()` and `GereFrappe()` to M3c. |
| Scene zones | `PlayWorld()` → `GereDec()` (`mainLoop.cpp:140`); `GereDec()` → `isPointInZV()`, `ChangeSalle()`, `InitView()` (`main.cpp:3769-3809`) | Task 6 preserves first-match AITD1 zone behavior and lets the current loop perform deferred room/view transitions. |
| Reading | `processLife()` → `readBook()` (`life.cpp:1635`) → `Lire()` (`main.cpp:587-610`); `Lire()` → `turnPageForward()` and `turnPageBackward()` (`main.cpp:867-887`) | Tasks 3 and 10 parse the original text controls and expose page edges without recreating FITD's blocking reader loop. |
| Nested event loops | `PlayWorld()`, `FoundObjet()`, `processInventory()`, and `Lire()` each call `process_events()` in the legacy graph (`mainLoop.cpp:47`, `inventory.cpp:248/563`, `main.cpp:647`) | Tasks 9-12 intentionally change the mechanism: reducers return typed results to the sole outer event pump, eliminating the observed freeze while retaining modal state transitions. |

The graph communities reinforce the file split: Life Scripts (14) maps to `life.py`/`life_ops.py`/`interaction.py`; UI Text Rendering (12) and AITD1 Cutscenes (19) map to `text.py`/`ui.py`; Game Flow Control (17) maps to `__main__.py`; Actor Script Evaluation (13) maps to `actors.py` plus contact integration.

## Locked file ownership

| File | Responsibility in M3b |
|---|---|
| `maitd/effects.py` | pygame-free effect records, modal results, and LIFE continuation tokens |
| `maitd/game.py` | active mode/effect, effect queues, continuation stack, inventory arrays, messages |
| `maitd/life.py` | execute from a byte PC and return a continuation after complete operands |
| `maitd/life_ops.py` | decode interaction/text opcodes and emit typed effects |
| `maitd/interaction.py` | found-LIFE execution, inventory/world transitions, `GereDec`, contact results, modal-result application |
| `maitd/actors.py` | cross-room collision query and motion/push primitives used by interaction |
| `maitd/text.py` | pure CP437 system-text and book-markup parsing |
| `maitd/assets.py` | cached ENGLISH and ITD_RESS entry access through the existing loader |
| `maitd/ui.py` | event-to-command mapping, pure presenter reducers, modal/message rendering |
| `maitd/render.py` | return the already-composited scene before presentation |
| `maitd/__main__.py` | sole event pump, input buffer, fixed-step/mode routing, one presentation per frame |

---

### Task 1: Typed effects and authoritative M3b state

**Files:**
- Create: `maitd/effects.py`
- Modify: `maitd/game.py:1-162`
- Test: `tests/test_effects.py`

**Interfaces:**
- Consumes: existing `Game`, `WorldObject`, and `Actor` state.
- Produces:
  - `GameMode`: `PLAY`, `FOUND`, `INVENTORY`, `READING`
  - `AfterLife`: `NONE`, `FINISH_TAKE`
  - `LifeFrame(owner_idx: int, life_num: int, pc: int = 0, after: AfterLife = AfterLife.NONE, subject_idx: int = -1, release_actor_idx: int = -1)`
  - `AddMessage(message_id: int)`
  - `BeginTake(object_idx: int)`
  - `ShowFound(object_idx: int, forced_refuse: bool)`
  - `OpenInventory()`
  - `ReadText(text_index: int, kind: int)`
  - `ShowPicture(resource_index: int, delay_units: int, sample_id: int)`
  - `TimedMessage(message_id: int, age: int = 0)`
  - `Game.open_modal(effect) -> None`, `Game.close_modal() -> None`, `Game.emit(effect) -> None`

- [ ] **Step 1: Write the failing state-contract tests**

```python
# SPDX-License-Identifier: GPL-2.0-only
from collections import deque

import pytest

from maitd.effects import AddMessage, BeginTake, GameMode, LifeFrame, ShowFound
from maitd.game import init_game


def test_game_initializes_fitd_inventory_and_effect_state(data_dir):
    game = init_game(data_dir)
    assert game.mode is GameMode.PLAY
    assert game.active_modal is None
    assert game.life_stack == []
    assert game.immediate_effects == deque()
    assert game.inventory_count == [0, 0]
    assert game.inventory_table == [[-1] * 30, [-1] * 30]
    assert game.in_hand_table == [-1, -1]
    assert game.messages == [None] * 5


def test_game_rejects_two_active_modals(data_dir):
    game = init_game(data_dir)
    game.open_modal(ShowFound(12, False))
    assert game.mode is GameMode.FOUND
    with pytest.raises(RuntimeError, match=r"ShowFound.*ShowFound"):
        game.open_modal(ShowFound(13, False))


def test_immediate_effect_is_fifo(data_dir):
    game = init_game(data_dir)
    game.emit(AddMessage(100))
    game.emit(BeginTake(12))
    assert list(game.immediate_effects) == [AddMessage(100), BeginTake(12)]
    assert LifeFrame(3, 9).pc == 0
```

- [ ] **Step 2: Run the tests and verify the contract is absent**

Run: `.venv/bin/pytest tests/test_effects.py -q`

Expected: collection fails because `maitd.effects` does not exist.

- [ ] **Step 3: Add the pygame-free records**

```python
# maitd/effects.py
# SPDX-License-Identifier: GPL-2.0-only
from dataclasses import dataclass
from enum import Enum, auto


class GameMode(Enum):
    PLAY = auto()
    FOUND = auto()
    INVENTORY = auto()
    READING = auto()


class AfterLife(Enum):
    NONE = auto()
    FINISH_TAKE = auto()


@dataclass(frozen=True)
class LifeFrame:
    owner_idx: int
    life_num: int
    pc: int = 0
    after: AfterLife = AfterLife.NONE
    subject_idx: int = -1
    release_actor_idx: int = -1


@dataclass(frozen=True)
class AddMessage:
    message_id: int


@dataclass(frozen=True)
class BeginTake:
    object_idx: int


@dataclass(frozen=True)
class ShowFound:
    object_idx: int
    forced_refuse: bool


@dataclass(frozen=True)
class OpenInventory:
    pass


@dataclass(frozen=True)
class ReadText:
    text_index: int
    kind: int


@dataclass(frozen=True)
class ShowPicture:
    resource_index: int
    delay_units: int
    sample_id: int


ModalEffect = ShowFound | OpenInventory | ReadText | ShowPicture
ImmediateEffect = AddMessage | BeginTake


@dataclass
class TimedMessage:
    message_id: int
    age: int = 0
```

- [ ] **Step 4: Extend `Game` with exact initial state and transition methods**

```python
# imports in maitd/game.py
from collections import deque

from maitd.effects import (
    AddMessage, BeginTake, OpenInventory, ReadText, ShowFound, ShowPicture,
    GameMode, TimedMessage,
)

# replace the current inventory stub in Game.__init__
self.mode = GameMode.PLAY
self.active_modal = None
self.life_stack = []
self.immediate_effects = deque()
self.inventory_table = [[-1] * 30 for _ in range(2)]
self.inventory_count = [0, 0]
self.in_hand_table = [-1, -1]
self.current_inventory = 0
self.messages = [None] * 5
self.status_screen_allowed = 1

# methods on Game
def open_modal(self, effect):
    if self.active_modal is not None:
        raise RuntimeError(
            f"cannot open {type(effect).__name__} while "
            f"{type(self.active_modal).__name__} is active"
        )
    self.active_modal = effect
    self.mode = {
        ShowFound: GameMode.FOUND,
        OpenInventory: GameMode.INVENTORY,
        ReadText: GameMode.READING,
        ShowPicture: GameMode.READING,
    }[type(effect)]

def close_modal(self):
    self.active_modal = None
    self.mode = GameMode.PLAY

def emit(self, effect):
    if isinstance(effect, (AddMessage, BeginTake)):
        self.immediate_effects.append(effect)
        return
    self.open_modal(effect)
```

- [ ] **Step 5: Run focused and full tests**

Run: `.venv/bin/pytest tests/test_effects.py tests/test_life_ops.py tests/test_play_loop.py -q`

Expected: all selected tests pass.

Run: `.venv/bin/pytest -q`

Expected: `190 passed, 1 skipped` or a higher pass count if the dirty baseline gained tests; no failure.

- [ ] **Step 6: Commit only Task 1 hunks**

```bash
git add maitd/effects.py tests/test_effects.py
git add -p maitd/game.py
git diff --cached --check
git commit -m "feat: add M3b effect and mode state"
```

---

### Task 2: LIFE suspension, resume, and nested found-LIFE frames

**Files:**
- Modify: `maitd/life.py:8-187`
- Create: `maitd/interaction.py`
- Test: `tests/test_life_continuation.py`

**Interfaces:**
- Consumes: `LifeFrame`, `AfterLife`, `Game.open_modal()`, existing `_dispatch()` and LIFE asset access.
- Produces:
  - `VM.suspend(effect) -> None`
  - `process_life(game, actor_idx: int, life_num: int, *, pc: int = 0, after: AfterLife = AfterLife.NONE, subject_idx: int = -1, release_actor_idx: int = -1) -> LifeFrame | None`
  - `run_life(game, frame: LifeFrame) -> bool`
  - `resume_life(game) -> bool`
  - `execute_found_life(game, object_idx: int, *, after: AfterLife = AfterLife.NONE) -> bool`
- Return `True` only when the requested frame and its completion action finish without opening a modal. A returned continuation is appended to `game.life_stack` exactly once.

- [ ] **Step 1: Write failing continuation tests**

```python
# SPDX-License-Identifier: GPL-2.0-only
import struct

from maitd.effects import AfterLife, LifeFrame, ReadText
from maitd.game import init_game
from maitd.interaction import resume_life, run_life


class Scripts:
    def __init__(self, scripts):
        self.scripts = scripts

    def life(self, index):
        return self.scripts[index]


def words(*values):
    return struct.pack(f"<{len(values)}h", *values)


def test_modal_suspends_after_all_read_operands_and_resumes_once(data_dir):
    game = init_game(data_dir)
    # LM_READ 35 consumes kind, entry, and the AITD1 extra word; LM_INC 20; LM_END 12.
    game.assets = Scripts({7: words(35, 1, 4, 99, 20, 6, 12)})
    game.vars[6] = 0
    assert run_life(game, LifeFrame(0, 7)) is False
    assert game.active_modal == ReadText(text_index=5, kind=1)
    assert game.life_stack[-1].pc == 8
    assert game.vars[6] == 0

    game.close_modal()
    assert resume_life(game) is True
    assert game.vars[6] == 1
    assert game.life_stack == []


def test_actor_switch_restores_owner_before_suspension(data_dir):
    game = init_game(data_dir)
    target_world = game.actors[0].index_in_world
    game.assets = Scripts({2: words(0x8000 | 35, target_world, 0, 0, 0, 12)})
    assert run_life(game, LifeFrame(1, 2)) is False
    assert game.life_stack[-1].owner_idx == 1
    assert game.life_stack[-1].pc == 10


def test_resume_keeps_parent_below_nested_frame(data_dir):
    game = init_game(data_dir)
    game.life_stack = [LifeFrame(2, 10, pc=14)]
    game.life_stack.append(LifeFrame(3, 11, pc=8, after=AfterLife.FINISH_TAKE, subject_idx=9))
    assert [frame.life_num for frame in game.life_stack] == [10, 11]
```

- [ ] **Step 2: Run the tests and verify suspension is unsupported**

Run: `.venv/bin/pytest tests/test_life_continuation.py -q`

Expected: import failure for `maitd.interaction` or `TypeError` because `process_life` has no resume PC.

- [ ] **Step 3: Make `VM` resumable and return its post-operand frame**

```python
# imports in maitd/life.py
from maitd.effects import AfterLife, LifeFrame


class VM:
    __slots__ = (
        "script", "pc", "game", "owner_idx", "cur_idx", "switch_val",
        "exit", "suspended", "after", "subject_idx", "release_actor_idx",
    )

    def __init__(self, script, game, owner_idx, *, pc=0, after=AfterLife.NONE,
                 subject_idx=-1, release_actor_idx=-1):
        self.script = script
        self.pc = pc
        self.game = game
        self.owner_idx = owner_idx
        self.cur_idx = owner_idx
        self.switch_val = 0
        self.exit = False
        self.suspended = False
        self.after = after
        self.subject_idx = subject_idx
        self.release_actor_idx = release_actor_idx

    def suspend(self, effect):
        self.game.emit(effect)
        self.suspended = True


def process_life(game, actor_idx, life_num, *, pc=0, after=AfterLife.NONE,
                 subject_idx=-1, release_actor_idx=-1):
    vm = VM(
        game.assets.life(life_num), game, actor_idx, pc=pc, after=after,
        subject_idx=subject_idx, release_actor_idx=release_actor_idx,
    )
    while not vm.exit and not vm.suspended:
        op = read_s16(vm)
        if game.trace is not None:
            game.trace.log(game, actor_idx, life_num, op, vm.pc)
        if op & 0x8000:
            world_idx = read_s16(vm)
            if not 0 <= world_idx < len(game.world_objects):
                raise ValueError(
                    f"world object index {world_idx} out of range "
                    f"0..{len(game.world_objects) - 1} "
                    f"(life {life_num} of actor {vm.owner_idx}, byte {vm.pc - 4})"
                )
            world = game.world_objects[world_idx]
            if world.obj_index != -1:
                vm.cur_idx = world.obj_index
                _dispatch(vm, op)
            else:
                if (op & 0x7FFF) not in _REDUCED_ALLOWED:
                    raise ValueError(
                        f"opcode {op & 0x7FFF} not allowed on out-of-floor "
                        f"object {world_idx} (life of actor {vm.owner_idx}, "
                        f"byte {vm.pc - 4})"
                    )
                _dispatch_reduced(vm, op, world_idx)
            vm.cur_idx = vm.owner_idx
        else:
            _dispatch(vm, op)
    if vm.suspended:
        return LifeFrame(
            vm.owner_idx, life_num, vm.pc, vm.after, vm.subject_idx,
            vm.release_actor_idx,
        )
    return None
```

The actor-switch branch restores `vm.cur_idx = vm.owner_idx` immediately after dispatch, before the loop observes `vm.suspended`.

- [ ] **Step 4: Add frame execution and temporary-actor found-LIFE setup**

```python
# maitd/interaction.py
# SPDX-License-Identifier: GPL-2.0-only
from maitd.effects import AfterLife, LifeFrame
from maitd.life import process_life


def _release_temporary_actor(game, actor_idx):
    if actor_idx != -1:
        game.actors[actor_idx].index_in_world = -1


def _complete_after_life(game, frame):
    _release_temporary_actor(game, frame.release_actor_idx)
    if frame.after is AfterLife.FINISH_TAKE:
        _finish_take(game, frame.subject_idx)


def run_life(game, frame):
    pending = process_life(
        game, frame.owner_idx, frame.life_num, pc=frame.pc, after=frame.after,
        subject_idx=frame.subject_idx, release_actor_idx=frame.release_actor_idx,
    )
    if pending is not None:
        game.life_stack.append(pending)
        return False
    _complete_after_life(game, frame)
    return True


def resume_life(game):
    while game.life_stack and game.active_modal is None:
        frame = game.life_stack.pop()
        if not run_life(game, frame):
            return False
    return game.active_modal is None


def execute_found_life(game, object_idx, *, after=AfterLife.NONE):
    if object_idx == -1:
        return True
    world = game.world_objects[object_idx]
    if world.found_life == -1:
        if after is AfterLife.FINISH_TAKE:
            _finish_take(game, object_idx)
        return True
    release_actor_idx = -1
    actor_idx = world.obj_index
    if actor_idx == -1:
        actor_idx = next(
            (i for i in range(len(game.actors) - 1, -1, -1)
             if game.actors[i].index_in_world == -1),
            len(game.actors) - 1,
        )
        actor = game.actors[actor_idx]
        actor.index_in_world = object_idx
        actor.life = actor.body_num = actor.room = actor.life_mode = actor.anim = -1
        actor.object_type = 0
        actor.track_mode = -1
        release_actor_idx = actor_idx
    return run_life(game, LifeFrame(
        actor_idx, world.found_life, after=after, subject_idx=object_idx,
        release_actor_idx=release_actor_idx,
    ))
```

Task 4 adds `_finish_take()` before Task 5 makes `AfterLife.FINISH_TAKE` reachable from a decoded opcode.

- [ ] **Step 5: Update existing direct `process_life` tests without changing their calls**

Keep the original positional `process_life(game, actor_idx, life_num)` API valid. Add these assertions to `tests/test_life_vm.py`:

```python
def test_completed_script_returns_no_continuation(data_dir):
    game = init_game(data_dir)
    assert process_life(game, 0, game.actors[0].life) is None
```

- [ ] **Step 6: Run focused and full tests**

Run: `.venv/bin/pytest tests/test_life_continuation.py tests/test_life_vm.py tests/test_eval_var.py -q`

Expected: all selected tests pass.

Run: `.venv/bin/pytest -q`

Expected: no regression.

- [ ] **Step 7: Commit Task 2**

```bash
git add maitd/life.py maitd/interaction.py tests/test_life_continuation.py tests/test_life_vm.py
git diff --cached --check
git commit -m "feat: suspend and resume LIFE scripts"
```

---

### Task 3: English text and ITD_RESS screen assets

**Files:**
- Create: `maitd/text.py`
- Modify: `maitd/assets.py:1-52`
- Test: `tests/test_text_assets.py`

**Interfaces:**
- Consumes: `find_pak()`, `Pak`, `load_entry()`, `decode_palette()`, `decode_image()`.
- Produces:
  - `BookToken(kind: str, text: str = "")`, where kind is `text`, `center`, `tab`, `page`, or `number`
  - `parse_system_texts(raw: bytes) -> dict[int, str]`
  - `parse_book_tokens(raw: bytes) -> tuple[BookToken, ...]`
  - `Assets.system_text(message_id: int) -> str`
  - `Assets.book_tokens(entry: int) -> tuple[BookToken, ...]`
  - `Assets.resource_screen(entry: int) -> np.ndarray` with shape `(200, 320, 3)`
- Unknown system-text IDs raise `KeyError("ENGLISH.PAK: text <id> not found")`; a resource shorter than 64,000 bytes raises `ValueError` naming ITD_RESS and the entry.

- [ ] **Step 1: Write parser and real-data golden tests**

```python
# SPDX-License-Identifier: GPL-2.0-only
import numpy as np
import pytest

from maitd.assets import Assets
from maitd.text import BookToken, parse_book_tokens, parse_system_texts


def test_system_text_parser_decodes_ids_and_cp437():
    texts = parse_system_texts(b"@20:You Find\r\n@103:A Photograph\r\n")
    assert texts == {20: "You Find", 103: "A Photograph"}


def test_book_parser_emits_layout_controls():
    tokens = parse_book_tokens(b"#CFragment\r\n#P#TThen\x1a")
    assert tokens == (
        BookToken("center"), BookToken("text", "Fragment\n"),
        BookToken("page"), BookToken("tab"), BookToken("text", "Then"),
    )


def test_english_and_reading_background_goldens(data_dir):
    assets = Assets(data_dir)
    assert assets.system_text(20) == "You Find"
    assert assets.system_text(22) == "Take"
    assert assets.system_text(33) == "Drop/Put"
    assert assets.book_tokens(1)[0].text.startswith("They are coming")
    for entry in (6, 7, 8):
        image = assets.resource_screen(entry)
        assert image.shape == (200, 320, 3)
        assert image.dtype == np.uint8


def test_missing_text_names_archive_and_id(data_dir):
    with pytest.raises(KeyError, match=r"ENGLISH\.PAK: text 9999 not found"):
        Assets(data_dir).system_text(9999)
```

- [ ] **Step 2: Run tests and verify the new readers are absent**

Run: `.venv/bin/pytest tests/test_text_assets.py -q`

Expected: collection fails for `maitd.text`.

- [ ] **Step 3: Implement the pure CP437 parsers**

```python
# maitd/text.py
# SPDX-License-Identifier: GPL-2.0-only
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class BookToken:
    kind: str
    text: str = ""


def parse_system_texts(raw):
    out = {}
    for line in raw.decode("cp437").replace("\r\n", "\n").splitlines():
        match = re.fullmatch(r"@(\d+):(.*)", line)
        if match:
            out[int(match.group(1))] = match.group(2)
    return out


def parse_book_tokens(raw):
    text = raw.split(b"\x1a", 1)[0].decode("cp437").replace("\r\n", "\n")
    controls = {"P": "page", "T": "tab", "C": "center", "G": "number"}
    tokens = []
    plain = []

    def flush():
        if plain:
            tokens.append(BookToken("text", "".join(plain)))
            plain.clear()

    i = 0
    while i < len(text):
        if text[i] == "#" and i + 1 < len(text) and text[i + 1] in controls:
            flush()
            kind = controls[text[i + 1]]
            i += 2
            if kind == "number":
                start = i
                while i < len(text) and text[i].isdigit():
                    i += 1
                tokens.append(BookToken(kind, text[start:i]))
            else:
                tokens.append(BookToken(kind))
            continue
        plain.append(text[i])
        i += 1
    flush()
    return tuple(tokens)
```

- [ ] **Step 4: Extend `Assets` with cached language and resource access**

```python
# additions in maitd/assets.py
from maitd.formats import decode_image, decode_palette, parse_anim, parse_body
from maitd.text import parse_book_tokens, parse_system_texts

TEXT_PAK = "ENGLISH"
RESOURCE_PAK = "ITD_RESS"
GAME_PALETTE_ENTRY = 3

# in Assets.__init__
self._text_pak = str(find_pak(data_dir, TEXT_PAK))
self._resource_pak = str(find_pak(data_dir, RESOURCE_PAK))
self._system_texts = parse_system_texts(load_entry(self._text_pak, 0))
self._book_tokens = {}
self._resource_screens = {}
self._game_palette = decode_palette(load_entry(self._resource_pak, GAME_PALETTE_ENTRY))

def system_text(self, message_id):
    try:
        return self._system_texts[message_id]
    except KeyError:
        raise KeyError(f"ENGLISH.PAK: text {message_id} not found") from None

def book_tokens(self, entry):
    if entry not in self._book_tokens:
        self._book_tokens[entry] = parse_book_tokens(load_entry(self._text_pak, entry))
    return self._book_tokens[entry]

def resource_screen(self, entry):
    if entry not in self._resource_screens:
        raw = load_entry(self._resource_pak, entry)
        if len(raw) < 64000:
            raise ValueError(f"ITD_RESS.PAK: entry {entry} is {len(raw)} bytes; expected 64000")
        self._resource_screens[entry] = decode_image(raw[:64000], self._game_palette)
    return self._resource_screens[entry]
```

Also clear `_book_tokens` and `_resource_screens` in `Assets.clear()`.

- [ ] **Step 5: Run focused, parse-all, and full tests**

Run: `.venv/bin/pytest tests/test_text_assets.py tests/test_assets.py tests/test_pak.py -q`

Expected: all selected tests pass.

Run: `make prove`

Expected: all existing real-data proof checks pass.

Run: `.venv/bin/pytest -q`

Expected: no regression.

- [ ] **Step 6: Commit Task 3**

```bash
git add maitd/text.py maitd/assets.py tests/test_text_assets.py
git diff --cached --check
git commit -m "feat: load AITD1 text and modal screens"
```

---

### Task 4: FITD inventory and world-object transitions

**Files:**
- Modify: `maitd/interaction.py`
- Modify: `maitd/game.py:164-end`
- Test: `tests/test_interaction.py`

**Interfaces:**
- Consumes: two 30-slot inventories, `AfterLife.FINISH_TAKE`, existing actor/world fields and `put_at_objet()` placement arithmetic.
- Produces:
  - `inventory_items(game, inventory_idx: int | None = None) -> tuple[int, ...]`
  - `inventory_actions(game, object_idx: int) -> tuple[int, ...]` returning text IDs 23 through 33, capped at five
  - `inventory_weight(game) -> int`
  - `find_in_inventory(game, object_idx: int) -> int`
  - `remove_from_inventory(game, object_idx: int) -> bool`
  - `begin_take(game, object_idx: int) -> bool`
  - `_finish_take(game, object_idx: int) -> None`
  - `put_object(game, object_idx: int, x: int, y: int, z: int, room: int, stage: int, alpha: int, beta: int, gamma: int) -> None`
  - `drop_object(game, object_idx: int, source_idx: int) -> None`
  - `choose_inventory_action(game, object_idx: int, action_text_id: int) -> bool`
  - `request_found(game, object_idx: int, parameter: int) -> ShowFound | None`

- [ ] **Step 1: Write failing FITD transition tests**

```python
# SPDX-License-Identifier: GPL-2.0-only
from maitd.effects import ShowFound
from maitd.game import init_game
from maitd.interaction import (
    _finish_take, choose_inventory_action, inventory_actions, inventory_items,
    inventory_weight, put_object, remove_from_inventory, request_found,
)


def test_take_keeps_first_item_at_zero_and_inserts_later_items_at_one(data_dir):
    game = init_game(data_dir)
    for object_idx in (10, 11, 12):
        _finish_take(game, object_idx)
    assert inventory_items(game) == (10, 12, 11)
    assert game.inventory_count[0] == 3
    assert game.world_objects[12].found_flag & 0x8000
    assert not game.world_objects[12].found_flag & 0x4000
    assert (game.world_objects[12].room, game.world_objects[12].stage) == (-1, -1)


def test_remove_and_put_match_found_flags(data_dir):
    game = init_game(data_dir)
    _finish_take(game, 10)
    assert remove_from_inventory(game, 10) is True
    assert not game.world_objects[10].found_flag & 0x8000
    _finish_take(game, 10)
    put_object(game, 10, 1, 2, 3, 4, 5, 6, 7, 8)
    world = game.world_objects[10]
    assert (world.x, world.y, world.z, world.room, world.stage) == (1, 2, 3, 4, 5)
    assert (world.alpha, world.beta, world.gamma) == (6, 7, 8)
    assert world.found_flag & 0x4000
    assert not world.found_flag & 0x8000


def test_weight_and_first_five_found_flag_actions(data_dir):
    game = init_game(data_dir)
    game.world_objects[10].position_in_track = 7
    _finish_take(game, 10)
    game.world_objects[10].found_flag = 0x8000 | sum(1 << bit for bit in (0, 2, 4, 6, 8, 10))
    assert inventory_weight(game) == 7
    assert inventory_actions(game, 10) == (23, 25, 27, 29, 31)


def test_found_request_applies_flags_debounce_weight_and_capacity(data_dir):
    game = init_game(data_dir)
    game.timer = 300
    world = game.world_objects[10]
    world.position_in_track = game.cvars[2] + 1
    assert request_found(game, 10, 1) == ShowFound(10, True)
    world.found_flag = 0x8000
    assert request_found(game, 10, 1) is None
    assert request_found(game, 10, 0) == ShowFound(10, True)
    world.found_flag = 0
    world.track_number = game.timer - 20
    assert request_found(game, 10, 0) is None


def test_inventory_choice_sets_action_and_in_hand_before_found_life(data_dir, monkeypatch):
    game = init_game(data_dir)
    _finish_take(game, 10)
    called = []
    monkeypatch.setattr("maitd.interaction.execute_found_life", lambda g, i, **kw: called.append(i) or True)
    assert choose_inventory_action(game, 10, 25) is True
    assert game.in_hand_table[0] == 10
    assert game.action == 1 << 2
    assert called == [10]
```

- [ ] **Step 2: Run tests and verify the inventory service is absent**

Run: `.venv/bin/pytest tests/test_interaction.py -q`

Expected: import errors for the new functions.

- [ ] **Step 3: Implement inventory queries and exact insertion/removal**

```python
# additions in maitd/interaction.py
INVENTORY_SIZE = 30
MAX_VISIBLE_ACTIONS = 5


def inventory_items(game, inventory_idx=None):
    inv = game.current_inventory if inventory_idx is None else inventory_idx
    return tuple(game.inventory_table[inv][:game.inventory_count[inv]])


def find_in_inventory(game, object_idx):
    try:
        return inventory_items(game).index(object_idx)
    except ValueError:
        return -1


def inventory_weight(game):
    return sum(game.world_objects[i].position_in_track for i in inventory_items(game))


def inventory_actions(game, object_idx):
    flags = game.world_objects[object_idx].found_flag
    return tuple(23 + bit for bit in range(11) if flags & (1 << bit))[:MAX_VISIBLE_ACTIONS]


def request_found(game, object_idx, parameter):
    from maitd.effects import ShowFound
    if object_idx < 0:
        return None
    world = game.world_objects[object_idx]
    if parameter != 0 and world.found_flag & 0xC000:
        return None
    if world.track_number and game.timer - world.track_number < 300:
        return None
    world.track_number = 0
    forced = (
        world.position_in_track + inventory_weight(game) > game.cvars[2]
        or game.inventory_count[game.current_inventory] + 1 == INVENTORY_SIZE
    )
    return ShowFound(object_idx, forced)


def remove_from_inventory(game, object_idx):
    inv = game.current_inventory
    slot = find_in_inventory(game, object_idx)
    if slot == -1:
        game.world_objects[object_idx].found_flag &= 0x7FFF
        return False
    count = game.inventory_count[inv]
    table = game.inventory_table[inv]
    table[slot:count - 1] = table[slot + 1:count]
    table[count - 1] = -1
    game.inventory_count[inv] -= 1
    game.world_objects[object_idx].found_flag &= 0x7FFF
    return True


def _finish_take(game, object_idx):
    inv = game.current_inventory
    count = game.inventory_count[inv]
    if count >= INVENTORY_SIZE - 1:
        raise ValueError(f"inventory {inv} is full at {count} objects")
    table = game.inventory_table[inv]
    if count == 0:
        table[0] = object_idx
    else:
        for i in range(count, 0, -1):
            table[i + 1] = table[i]
        table[1] = object_idx
    game.inventory_count[inv] += 1
    world = game.world_objects[object_idx]
    if world.obj_index != -1:
        game.actors[world.obj_index].index_in_world = -1
        world.obj_index = -1
    world.found_flag = (world.found_flag & 0xBFFF) | 0x8000
    world.room = world.stage = -1
    game.flag_genere_aff_list = 1
```

- [ ] **Step 4: Implement take completion, put/drop, and inventory action dispatch**

```python
def begin_take(game, object_idx):
    game.action = 0x800
    return execute_found_life(game, object_idx, after=AfterLife.FINISH_TAKE)


def put_object(game, object_idx, x, y, z, room, stage, alpha, beta, gamma):
    world = game.world_objects[object_idx]
    world.x, world.y, world.z = x, y, z
    world.room, world.stage = room, stage
    world.alpha, world.beta, world.gamma = alpha, beta, gamma
    remove_from_inventory(game, object_idx)
    world.found_flag |= 0x4000
    game.flag_genere_aff_list = 1


def drop_object(game, object_idx, source_idx):
    from maitd.game import put_at_objet
    put_at_objet(game, object_idx, source_idx)
    game.flag_genere_aff_list = 1


def choose_inventory_action(game, object_idx, action_text_id):
    if action_text_id not in inventory_actions(game, object_idx):
        raise ValueError(f"object {object_idx} does not expose inventory action {action_text_id}")
    game.in_hand_table[game.current_inventory] = object_idx
    game.action = 1 << (action_text_id - 23)
    return execute_found_life(game, object_idx)
```

Replace the two M3b skip comments in `maitd/game.py` with the same local inventory-removal call:

```python
def delete_object(game, obj_idx):
    obj = game.world_objects[obj_idx]
    actor_idx = obj.obj_index
    if actor_idx != -1:
        actor = game.actors[actor_idx]
        actor.room = -1
        actor.stage = -1
        actor.index_in_world = -1
    obj.obj_index = -1
    obj.room = -1
    obj.stage = -1
    from maitd.interaction import remove_from_inventory
    remove_from_inventory(game, obj_idx)


def put_at_objet(game, obj_idx, obj_idx_to_put_at):
    obj = game.world_objects[obj_idx]
    put_at = game.world_objects[obj_idx_to_put_at]
    if put_at.obj_index != -1:
        src = game.actors[put_at.obj_index]
        x, y, z = src.room_x, src.room_y, src.room_z
        room, stage = src.room, src.stage
        alpha, beta, gamma = src.alpha, src.beta, src.gamma
    else:
        x, y, z = put_at.x, put_at.y, put_at.z
        room, stage = put_at.room, put_at.stage
        alpha, beta, gamma = put_at.alpha, put_at.beta, put_at.gamma
    if obj.obj_index == -1:
        obj.x, obj.y, obj.z = x, y, z
        obj.room, obj.stage = room, stage
        obj.alpha, obj.beta, obj.gamma = alpha, beta, gamma
        obj.found_flag |= 0x4000
        obj.flags |= 0x80
    else:
        actor = game.actors[obj.obj_index]
        actor.room_x, actor.room_y, actor.room_z = x, y, z
        actor.room, actor.stage = room, stage
        actor.alpha, actor.beta, actor.gamma = alpha, beta, gamma
        game.world_objects[actor.index_in_world].found_flag |= 0x4000
        game.world_objects[actor.index_in_world].flags |= 0x80
    from maitd.interaction import remove_from_inventory
    remove_from_inventory(game, obj_idx)
```

Do not clear `in_hand_table`: Graphify confirms `put()` and `PutAtObjet()` converge on `DeleteInventoryObjet()`, while FITD leaves held-object changes to LM_IN_HAND in object LIFE.

- [ ] **Step 5: Run focused and full tests**

Run: `.venv/bin/pytest tests/test_interaction.py tests/test_life_ops.py -q`

Expected: all selected tests pass.

Run: `.venv/bin/pytest -q`

Expected: no regression.

- [ ] **Step 6: Commit Task 4 hunks**

```bash
git add maitd/interaction.py tests/test_interaction.py
git add -p maitd/game.py
git diff --cached --check
git commit -m "feat: port AITD1 inventory transitions"
```

---

### Task 5: Interaction and text LIFE opcodes

**Files:**
- Modify: `maitd/life_ops.py:150-430`
- Test: `tests/test_life_interaction_ops.py`

**Interfaces:**
- Consumes: `VM.suspend()`, `AddMessage`, `ShowFound`, `ReadText`, `ShowPicture`, and Task 4 interaction functions.
- Produces working AITD1 semantics for opcode indices 17, 18, 30, 33, 34, 35, 48, 49, 50, 52, 56, 60, 67, 68, 70, and 79.
- LM_READ emits `ReadText(text_index=raw_index + 1, kind=raw_kind)` after consuming the AITD1 extra s16. LM_PICTURE suspends after all three raw operands. Audio state is untouched.

- [ ] **Step 1: Write failing opcode-effect tests**

```python
# SPDX-License-Identifier: GPL-2.0-only
import struct

from maitd.effects import AddMessage, BeginTake, ReadText, ShowFound, ShowPicture
from maitd.game import init_game
from maitd.life import process_life


class Scripts:
    def __init__(self, script):
        self.script = script

    def life(self, index):
        return self.script


def run(game, *words):
    game.assets = Scripts(struct.pack(f"<{len(words)}h", *words))
    return process_life(game, 0, 0)


def test_message_effect_is_immediate_and_script_finishes(data_dir):
    game = init_game(data_dir)
    assert run(game, 17, 100, 18, 101, 999, 12) is None
    assert list(game.immediate_effects) == [AddMessage(100), AddMessage(101)]


def test_found_read_and_picture_suspend_at_next_opcode(data_dir):
    game = init_game(data_dir)
    game.timer = 300
    frame = run(game, 30, 44, 20, 1, 12)
    assert game.active_modal == ShowFound(44, False)
    assert frame.pc == 4

    game.close_modal()
    game.life_stack.clear()
    frame = run(game, 35, 2, 3, 77, 20, 1, 12)
    assert game.active_modal == ReadText(4, 2)
    assert frame.pc == 8

    game.close_modal()
    frame = run(game, 79, 10, 120, 6, 20, 1, 12)
    assert game.active_modal == ShowPicture(10, 120, 6)
    assert frame.pc == 8


def test_found_metadata_preserves_high_flag_bits(data_dir):
    game = init_game(data_dir)
    world_idx = game.actors[0].index_in_world
    world = game.world_objects[world_idx]
    world.found_flag = 0xE000
    run(game, 48, 222, 49, 0x35, 50, 7, 56, 19, 68, 4, 12)
    assert (world.found_name, world.found_flag, world.found_life) == (222, 0xE035, 7)
    assert (world.found_body, world.position_in_track) == (19, 4)
```

- [ ] **Step 2: Run tests and verify current stubs fail assertions**

Run: `.venv/bin/pytest tests/test_life_interaction_ops.py -q`

Expected: effects are missing and modal assertions fail.

- [ ] **Step 3: Replace message/found/read/picture stubs with typed emission**

```python
# imports in maitd/life_ops.py
from maitd.effects import AddMessage, BeginTake, ReadText, ShowPicture


def op_message(vm):
    vm.game.emit(AddMessage(read_s16(vm)))


def op_message_value(vm):
    message_id = read_s16(vm)
    read_s16(vm)
    vm.game.emit(AddMessage(message_id))


def op_found(vm):
    from maitd.interaction import request_found
    effect = request_found(vm.game, read_s16(vm), parameter=1)
    if effect is not None:
        vm.suspend(effect)


def op_read(vm):
    kind = read_s16(vm)
    index = read_s16(vm)
    read_s16(vm)
    vm.suspend(ReadText(index + 1, kind))


def op_picture(vm):
    picture = read_s16(vm)
    delay = read_s16(vm)
    sample = read_s16(vm)
    vm.suspend(ShowPicture(picture, delay, sample))
```

- [ ] **Step 4: Wire inventory/world mutation opcodes to Task 4**

```python
def op_take(vm):
    vm.suspend(BeginTake(read_s16(vm)))


def op_drop(vm):
    from maitd.interaction import drop_object
    object_idx = eval_var(vm)
    source_idx = read_s16(vm)
    drop_object(vm.game, object_idx, source_idx)


def op_put(vm):
    from maitd.interaction import put_object
    object_idx = read_s16(vm)
    x, y, z = read_s16(vm), read_s16(vm), read_s16(vm)
    room, stage = read_s16(vm), read_s16(vm)
    alpha, beta, gamma = read_s16(vm), read_s16(vm), read_s16(vm)
    put_object(vm.game, object_idx, x, y, z, room, stage, alpha, beta, gamma)


def op_put_at(vm):
    from maitd.interaction import drop_object
    drop_object(vm.game, read_s16(vm), read_s16(vm))


def op_inventory(vm):
    vm.game.status_screen_allowed = read_s16(vm)


def op_in_hand(vm):
    vm.game.in_hand_table[vm.game.current_inventory] = read_s16(vm)


def op_found_name(vm):
    vm.game.world_objects[vm.actor.index_in_world].found_name = read_s16(vm)


def op_found_flag(vm):
    world = vm.game.world_objects[vm.actor.index_in_world]
    world.found_flag = (world.found_flag & 0xE000) | read_s16(vm)


def op_found_life(vm):
    vm.game.world_objects[vm.actor.index_in_world].found_life = read_s16(vm)


def op_found_body(vm):
    vm.game.world_objects[vm.actor.index_in_world].found_body = read_s16(vm)


def op_found_weight(vm):
    vm.game.world_objects[vm.actor.index_in_world].position_in_track = read_s16(vm)
```

Keep these handlers registered at the current dispatch-table indices; the only dispatch-table changes in this task replace the interaction/text stubs listed in the interface.

- [ ] **Step 5: Run focused, full, and script-fetch tests**

Run: `.venv/bin/pytest tests/test_life_interaction_ops.py tests/test_life_ops.py tests/test_life_vm.py -q`

Expected: all selected tests pass.

Run: `.venv/bin/pytest -q`

Expected: no regression.

- [ ] **Step 6: Commit Task 5**

```bash
git add maitd/life_ops.py tests/test_life_interaction_ops.py
git diff --cached --check
git commit -m "feat: connect interaction LIFE opcodes"
```

---

### Task 6: `GereDec` scene-zone behavior

**Files:**
- Modify: `maitd/interaction.py`
- Test: `tests/test_gere_dec.py`

**Interfaces:**
- Consumes: `Room.sce_zones`, actor room/step/ZV fields, world `floor_life`, and existing room-change flags.
- Produces:
  - `point_in_zone(x: int, y: int, z: int, zone: Zone) -> bool`
  - `gere_dec(game, actor_idx: int) -> None`
- AITD1 stops after the first containing scene zone. Type 0 changes actor room coordinates and requests view/list regeneration; type 9 writes `hard_dec`; type 10 writes `life` from `floor_life` and `hard_dec`. Other types make no M3b mutation.

- [ ] **Step 1: Write failing scene-zone tests**

```python
# SPDX-License-Identifier: GPL-2.0-only
from types import SimpleNamespace

from maitd.formats import Zone
from maitd.interaction import gere_dec


def room(wx, wy, wz, zones=()):
    return SimpleNamespace(world_x=wx, world_y=wy, world_z=wz, sce_zones=list(zones))


def test_room_zone_rebases_room_coordinates_and_requests_camera_change(monkeypatch, data_dir):
    from maitd.game import init_game
    game = init_game(data_dir)
    actor_idx = game.current_camera_target_actor
    actor = game.actors[actor_idx]
    actor.room = 0
    actor.room_x = actor.room_y = actor.room_z = 0
    actor.step_x = actor.step_y = actor.step_z = 0
    actor.zv = [-1, 1, -1, 1, -1, 1]
    zones = [Zone(-2, 2, -2, 2, -2, 2, 0, 1)]
    monkeypatch.setattr(game, "rooms_of_floor", lambda floor: [room(0, 0, 0, zones), room(2, 1, -3)])
    gere_dec(game, actor_idx)
    assert actor.room == 1
    assert (actor.room_x, actor.room_y, actor.room_z) == (-20, 10, -30)
    assert actor.zv == [-21, -19, 9, 11, -31, -29]
    assert (game.flag_change_salle, game.new_num_salle) == (1, 1)


def test_scenario_and_floor_life_zones_write_fitd_fields(monkeypatch, data_dir):
    from maitd.game import init_game
    game = init_game(data_dir)
    actor = game.actors[0]
    actor.room = 0
    actor.room_x = actor.room_y = actor.room_z = 0
    actor.step_x = actor.step_y = actor.step_z = 0
    actor.zv = [-1, 1, -1, 1, -1, 1]
    world = game.world_objects[actor.index_in_world]
    world.floor_life = 55
    monkeypatch.setattr(game, "rooms_of_floor", lambda floor: [room(0, 0, 0, [Zone(-2, 2, -2, 2, -2, 2, 9, 44)])])
    gere_dec(game, 0)
    assert actor.hard_dec == 44
    monkeypatch.setattr(game, "rooms_of_floor", lambda floor: [room(0, 0, 0, [Zone(-2, 2, -2, 2, -2, 2, 10, 66)])])
    gere_dec(game, 0)
    assert (actor.life, actor.hard_dec) == (55, 66)
```

- [ ] **Step 2: Run tests and verify `gere_dec` is absent**

Run: `.venv/bin/pytest tests/test_gere_dec.py -q`

Expected: import failure for `gere_dec`.

- [ ] **Step 3: Port the AITD1 zone switch**

```python
def point_in_zone(x, y, z, zone):
    return zone.x1 <= x <= zone.x2 and zone.y1 <= y <= zone.y2 and zone.z1 <= z <= zone.z2


def gere_dec(game, actor_idx):
    actor = game.actors[actor_idx]
    rooms = game.rooms_of_floor(game.current_floor)
    room = rooms[actor.room]
    x = actor.room_x + actor.step_x
    y = actor.room_y + actor.step_y
    z = actor.room_z + actor.step_z
    for zone in room.sce_zones:
        if not point_in_zone(x, y, z, zone):
            continue
        if zone.type == 0:
            old_room = actor.room
            actor.room = zone.parameter
            dx = (rooms[actor.room].world_x - rooms[old_room].world_x) * 10
            dy = (rooms[actor.room].world_y - rooms[old_room].world_y) * 10
            dz = (rooms[actor.room].world_z - rooms[old_room].world_z) * 10
            actor.room_x -= dx
            actor.room_y += dy
            actor.room_z += dz
            actor.zv[0] -= dx
            actor.zv[1] -= dx
            actor.zv[2] += dy
            actor.zv[3] += dy
            actor.zv[4] += dz
            actor.zv[5] += dz
            if actor_idx == game.current_camera_target_actor:
                game.flag_change_salle = 1
                game.new_num_salle = actor.room
            else:
                game.flag_genere_aff_list = 1
        elif zone.type == 9:
            actor.hard_dec = zone.parameter
        elif zone.type == 10:
            world = game.world_objects[actor.index_in_world]
            if world.floor_life == -1:
                return
            actor.life = world.floor_life
            actor.hard_dec = zone.parameter
        return
```

- [ ] **Step 4: Run focused and full tests**

Run: `.venv/bin/pytest tests/test_gere_dec.py tests/test_tracks.py tests/test_camera_switch.py -q`

Expected: all selected tests pass.

Run: `.venv/bin/pytest -q`

Expected: no regression.

- [ ] **Step 5: Commit Task 6**

```bash
git add maitd/interaction.py tests/test_gere_dec.py
git diff --cached --check
git commit -m "feat: port AITD1 scene zones"
```

---

### Task 7: Cross-room actor contacts, foundable objects, and push movement

**Files:**
- Modify: `maitd/game.py:1-20`
- Modify: `maitd/actors.py:1-260`
- Modify: `maitd/interaction.py`
- Test: `tests/test_actor_contacts.py`

**Interfaces:**
- Consumes: `cube_intersect()`, `check_hard_col()`, `gere_collision()`, `request_found()`, `Actor.col`, `Actor.col_by`, room origins, and the attempted movement ZV.
- Produces:
  - constants `AF_MOVABLE = 0x0010`, `AF_FALLABLE = 0x0100`
  - `adjust_zv_between_rooms(game, zv: list[int], start_room: int, dest_room: int) -> list[int]`
  - `check_object_col(game, actor_idx: int, zv: list[int]) -> tuple[int, ...]`
  - `resolve_actor_contacts(game, actor_idx: int, old_zv: list[int], attempted_zv: list[int], step_x: int, step_z: int) -> tuple[list[int], int, int]`
- `check_object_col` resets all three COL slots and stores at most three live intersecting actor indices. Every touched actor gets `col_by = actor_idx`. Foundable contact may open FOUND and does not block movement. A pushable actor moves only if its attempted ZV intersects neither hard geometry nor another actor.

- [ ] **Step 1: Write failing contact tests**

```python
# SPDX-License-Identifier: GPL-2.0-only
from types import SimpleNamespace

from maitd.actors import check_object_col
from maitd.game import AF_FOUNDABLE, AF_MOVABLE, init_game
from maitd.interaction import resolve_actor_contacts


def live_actor(game, index, room, zv, flags=0, world_idx=0):
    actor = game.actors[index]
    actor.index_in_world = world_idx
    actor.room = room
    actor.zv = list(zv)
    actor.object_type = flags
    return actor


def test_check_object_col_adjusts_candidate_to_other_room(data_dir, monkeypatch):
    game = init_game(data_dir)
    for actor in game.actors:
        actor.index_in_world = -1
    live_actor(game, 0, 0, (0, 10, 0, 10, 0, 10), world_idx=1)
    live_actor(game, 1, 1, (-20, -10, 0, 10, 0, 10), world_idx=2)
    rooms = [SimpleNamespace(world_x=0, world_y=0, world_z=0), SimpleNamespace(world_x=2, world_y=0, world_z=0)]
    monkeypatch.setattr(game, "rooms_of_floor", lambda floor: rooms)
    assert check_object_col(game, 0, [0, 10, 0, 10, 0, 10]) == (1,)
    assert game.actors[0].col == [1, -1, -1]


def test_foundable_contact_opens_modal_without_blocking_step(data_dir, monkeypatch):
    game = init_game(data_dir)
    game.timer = 300
    for actor in game.actors:
        actor.index_in_world = -1
    mover = live_actor(game, 0, 0, (0, 10, 0, 10, 0, 10), world_idx=1)
    mover.track_mode = 1
    item = live_actor(game, 1, 0, (8, 18, 0, 10, 0, 10), AF_FOUNDABLE, world_idx=2)
    game.world_objects[2].position_in_track = 0
    monkeypatch.setattr(game, "rooms_of_floor", lambda floor: [SimpleNamespace(world_x=0, world_y=0, world_z=0, hard_cols=[])])
    zv, sx, sz = resolve_actor_contacts(game, 0, mover.zv, [8, 18, 0, 10, 0, 10], 8, 0)
    assert (sx, sz, zv) == (8, 0, [8, 18, 0, 10, 0, 10])
    assert item.col_by == 0
    assert game.active_modal.object_idx == 2


def test_movable_contact_pushes_when_destination_is_clear(data_dir, monkeypatch):
    game = init_game(data_dir)
    for actor in game.actors:
        actor.index_in_world = -1
    mover = live_actor(game, 0, 0, (0, 10, 0, 10, 0, 10), world_idx=1)
    pushed = live_actor(game, 1, 0, (8, 18, 0, 10, 0, 10), AF_MOVABLE, world_idx=2)
    monkeypatch.setattr(game, "rooms_of_floor", lambda floor: [SimpleNamespace(world_x=0, world_y=0, world_z=0, hard_cols=[])])
    resolve_actor_contacts(game, 0, mover.zv, [8, 18, 0, 10, 0, 10], 8, 0)
    assert pushed.zv == [16, 26, 0, 10, 0, 10]
    assert pushed.world_x == 8
    assert pushed.room_x == 8
```

- [ ] **Step 2: Run tests and verify collision interfaces are absent**

Run: `.venv/bin/pytest tests/test_actor_contacts.py -q`

Expected: imports fail for `AF_MOVABLE`, `check_object_col`, or `resolve_actor_contacts`.

- [ ] **Step 3: Add flags and cross-room collision query**

```python
# maitd/game.py constants
AF_MOVABLE = 0x0010
AF_FALLABLE = 0x0100


# maitd/actors.py
def adjust_zv_between_rooms(game, zv, start_room, dest_room):
    rooms = game.rooms_of_floor(game.current_floor)
    dx = 10 * (rooms[dest_room].world_x - rooms[start_room].world_x)
    dy = 10 * (rooms[dest_room].world_y - rooms[start_room].world_y)
    dz = 10 * (rooms[dest_room].world_z - rooms[start_room].world_z)
    return [zv[0] - dx, zv[1] - dx, zv[2] + dy, zv[3] + dy, zv[4] + dz, zv[5] + dz]


def check_object_col(game, actor_idx, zv):
    actor = game.actors[actor_idx]
    actor.col[:] = [-1, -1, -1]
    found = []
    for other_idx, other in enumerate(game.actors):
        if other.index_in_world == -1 or other_idx == actor_idx:
            continue
        local = zv if other.room == actor.room else adjust_zv_between_rooms(
            game, zv, actor.room, other.room,
        )
        if cube_intersect(local, other.zv):
            found.append(other_idx)
            if len(found) == 3:
                break
    actor.col[:len(found)] = found
    return tuple(found)
```

- [ ] **Step 4: Implement contact resolution in `interaction.py`**

```python
def resolve_actor_contacts(game, actor_idx, old_zv, attempted_zv, step_x, step_z):
    from maitd.actors import (
        adjust_zv_between_rooms, check_hard_col, check_object_col,
        gere_collision,
    )
    from maitd.game import AF_ANIMATED, AF_BOXIFY, AF_FOUNDABLE, AF_MOVABLE

    actor = game.actors[actor_idx]
    room = game.rooms_of_floor(game.current_floor)[actor.room]
    for touched_idx in check_object_col(game, actor_idx, attempted_zv):
        touched = game.actors[touched_idx]
        touched.col_by = actor_idx
        if touched.object_type & AF_FOUNDABLE:
            if actor.track_mode == 1 and game.active_modal is None:
                effect = request_found(game, touched.index_in_world, parameter=0)
                if effect is not None:
                    game.open_modal(effect)
            continue

        touched_zv = touched.zv
        if touched.room != actor.room:
            touched_zv = adjust_zv_between_rooms(game, touched_zv, touched.room, actor.room)
        if touched.object_type & AF_MOVABLE:
            pushed_zv = [
                touched_zv[0] + step_x, touched_zv[1] + step_x,
                touched_zv[2], touched_zv[3],
                touched_zv[4] + step_z, touched_zv[5] + step_z,
            ]
            blocked = bool(check_hard_col(pushed_zv, room.hard_cols))
            if not blocked:
                original_room = touched.room
                touched.room = actor.room
                blocked = bool(check_object_col(game, touched_idx, pushed_zv))
                touched.room = original_room
            if not blocked:
                touched.object_type |= AF_ANIMATED
                touched.object_type &= ~AF_BOXIFY
                touched.world_x += step_x
                touched.world_z += step_z
                touched.room_x += step_x
                touched.room_z += step_z
                touched.zv = pushed_zv
                continue
        if actor.dyn_flags & 1 and (step_x or step_z):
            step_x, step_z = gere_collision(old_zv, attempted_zv, touched_zv, step_x, step_z)
            attempted_zv = [
                old_zv[0] + step_x, old_zv[1] + step_x,
                attempted_zv[2], attempted_zv[3],
                old_zv[4] + step_z, old_zv[5] + step_z,
            ]
    return attempted_zv, step_x, step_z
```

Preserve the actor's COL list from the mover query: the temporary push-block query writes the pushed actor's COL, never the mover's.

- [ ] **Step 5: Call contact resolution from both static and moving paths in `gere_anim`**

```python
# static speed-zero branch
for touched_idx in check_object_col(game, actor_idx, a.zv):
    game.actors[touched_idx].col_by = actor_idx

# moving branch, after hard collision and before assigning a.step_x/a.step_z
from maitd.interaction import resolve_actor_contacts
zv_local, step_x, step_z = resolve_actor_contacts(
    game, actor_idx, list(a.zv), zv_local, step_x, step_z,
)
```

Keep the existing vertical interpolation. Leave the AF_FALLABLE section unchanged for M3c. Preserve current dirty animation and rendering corrections.

- [ ] **Step 6: Run focused, animation, and full tests**

Run: `.venv/bin/pytest tests/test_actor_contacts.py tests/test_actors.py tests/test_play_loop.py -q`

Expected: all selected tests pass.

Run: `.venv/bin/pytest -q`

Expected: no regression.

- [ ] **Step 7: Commit Task 7 hunks**

```bash
git add tests/test_actor_contacts.py maitd/interaction.py
git add -p maitd/game.py maitd/actors.py
git diff --cached --check
git commit -m "feat: port actor object contacts"
```

---

### Task 8: Immediate message queue and pre-present scene composition

**Files:**
- Modify: `maitd/interaction.py`
- Modify: `maitd/render.py:38-94`
- Modify: `tests/test_render.py`
- Test: `tests/test_messages.py`

**Interfaces:**
- Consumes: `AddMessage`, `BeginTake`, `TimedMessage`, current scene-composition body, and `begin_take()`.
- Produces:
  - `drain_immediate_effects(game) -> bool`
  - `advance_messages(game) -> None`
  - `Renderer._compose_existing_scene(...) -> np.ndarray`, a test seam containing the unchanged room-aware composition body
  - `Renderer.compose_scene(background, actor_results, masks, palette, actor_rooms, actor_zvs) -> np.ndarray`
- `drain_immediate_effects` preserves FIFO. AddMessage refreshes a duplicate's age, otherwise uses the first free of five slots. BeginTake starts found-LIFE only after the parent frame has already been stacked. If that call completes immediately, resume the parent before returning.

- [ ] **Step 1: Write failing message and engine-effect tests**

```python
# SPDX-License-Identifier: GPL-2.0-only
from maitd.effects import AddMessage, BeginTake, LifeFrame
from maitd.game import init_game
from maitd.interaction import advance_messages, drain_immediate_effects


def test_messages_refresh_duplicate_fill_five_slots_and_expire(data_dir):
    game = init_game(data_dir)
    for message_id in range(100, 106):
        game.emit(AddMessage(message_id))
    drain_immediate_effects(game)
    assert [m.message_id for m in game.messages] == [100, 101, 102, 103, 104]
    game.messages[2].age = 40
    game.emit(AddMessage(102))
    drain_immediate_effects(game)
    assert game.messages[2].age == 0
    for _ in range(56):
        advance_messages(game)
    assert game.messages == [None] * 5


def test_begin_take_runs_after_parent_frame_is_stacked(data_dir, monkeypatch):
    game = init_game(data_dir)
    game.life_stack.append(LifeFrame(0, 1, pc=6))
    seen = []
    monkeypatch.setattr("maitd.interaction.begin_take", lambda g, i: seen.append((i, len(g.life_stack))) or False)
    game.emit(BeginTake(12))
    assert drain_immediate_effects(game) is False
    assert seen == [(12, 1)]
```

Add to `tests/test_render.py`:

```python
def test_compose_scene_returns_rgb_without_presenting(monkeypatch):
    renderer = object.__new__(Renderer)
    expected = np.zeros((200, 320, 3), dtype=np.uint8)
    monkeypatch.setattr(renderer, "_compose_existing_scene", lambda *args: expected)
    assert renderer.compose_scene(None, [], [], None, [], []) is expected
```

- [ ] **Step 2: Run tests and verify queue draining/composition are absent**

Run: `.venv/bin/pytest tests/test_messages.py tests/test_render.py -q`

Expected: import failure for `drain_immediate_effects` or missing `compose_scene`.

- [ ] **Step 3: Implement FIFO immediate-effect draining and deterministic message ages**

```python
def _add_message(game, message_id):
    for message in game.messages:
        if message is not None and message.message_id == message_id:
            message.age = 0
            return
    for slot, message in enumerate(game.messages):
        if message is None:
            game.messages[slot] = TimedMessage(message_id)
            return


def drain_immediate_effects(game):
    completed = True
    while game.immediate_effects:
        effect = game.immediate_effects.popleft()
        if isinstance(effect, AddMessage):
            _add_message(game, effect.message_id)
        elif isinstance(effect, BeginTake):
            completed = begin_take(game, effect.object_idx)
            if completed and game.active_modal is None:
                completed = resume_life(game)
            if not completed:
                break
        else:
            raise RuntimeError(f"unknown immediate effect {type(effect).__name__}")
    return completed


def advance_messages(game):
    for slot, message in enumerate(game.messages):
        if message is None:
            continue
        message.age += 1
        if message.age > 55:
            game.messages[slot] = None
```

- [ ] **Step 4: Extract scene composition without changing pixels**

```python
# maitd/render.py
def _compose_existing_scene(self, background, actor_results, masks, palette,
                            actor_rooms, actor_zvs):
    if not hasattr(self, "_actor_layer"):
        self._actor_layer = _ActorLayer(self._ctx, palette)
    self._actor_layer.draw(actor_results, actor_rooms, masks, actor_zvs=actor_zvs)
    rgba = np.zeros((200, 320, 4), dtype=np.uint8)
    rgba[:, :, :3] = background
    rgba[:, :, 3] = 255
    layer = np.frombuffer(
        self._actor_layer._tex.read(), dtype=np.uint8,
    ).reshape(200, 320, 4).copy()
    layer = layer[::-1]
    alpha = layer[:, :, 3:4].astype("f4") / 255.0
    composite = (
        layer[:, :, :3].astype("f4") * alpha
        + rgba[:, :, :3].astype("f4") * (1.0 - alpha)
    ).astype(np.uint8)
    self._ctx.screen.use()
    return np.ascontiguousarray(composite[:, :, :3])


def compose_scene(self, background, actor_results, masks, palette, actor_rooms,
                  actor_zvs):
    return self._compose_existing_scene(
        background, actor_results, masks, palette, actor_rooms, actor_zvs,
    )


def present_scene(self, background, actor_results, masks, palette, actor_rooms, actor_zvs):
    self.present(self.compose_scene(
        background, actor_results, masks, palette, actor_rooms, actor_zvs,
    ))
```

The extraction must preserve the dirty worktree's room-aware depth/mask changes. Before editing, save `git diff -- maitd/render.py tests/test_render.py` in the execution transcript; after extraction, run all pixel golden tests.

- [ ] **Step 5: Run message, pixel, and full tests**

Run: `.venv/bin/pytest tests/test_messages.py tests/test_render.py tests/test_mask.py tests/test_skel.py -q`

Expected: all selected tests pass with unchanged pixel assertions.

Run: `.venv/bin/pytest -q`

Expected: no regression.

- [ ] **Step 6: Commit only Task 8 hunks**

```bash
git add maitd/interaction.py tests/test_messages.py
git add -p maitd/render.py tests/test_render.py
git diff --cached --check
git commit -m "feat: queue messages before frame presentation"
```

---

### Task 9: Accessible command buffer and pure modal reducers

**Files:**
- Create: `maitd/ui.py`
- Test: `tests/test_ui_input.py`
- Test: `tests/test_ui_reducers.py`

**Interfaces:**
- Consumes: pygame event constants only at `event_to_input`; reducers consume plain enums/counts and never pygame events.
- Produces:
  - `Command`: `UP`, `DOWN`, `LEFT`, `RIGHT`, `ACCEPT`, `CANCEL`, `OPEN_INVENTORY`
  - `FoundResult`: `TAKE`, `LEAVE`
  - `InventoryResult(object_idx: int = -1, action_text_id: int = -1, cancelled: bool = False)`
  - `ReadingResult(dismissed: bool, page_delta: int = 0)`
  - `InputBuffer(held_joyd: int = 0, action_held: bool = False, focused: bool = True, commands: deque[Command])`
  - `event_to_input(event, input_buffer: InputBuffer) -> bool`, returning `False` only for QUIT
  - `FoundPresenter(choice: FoundResult)`, `InventoryPresenter(object_cursor: int, action_cursor: int, choosing_action: bool)`, `ReadingPresenter(page: int, elapsed_ms: int)`
  - pure `reduce_found`, `reduce_inventory`, and `reduce_reading`
- KEYDOWN arrows/WASD enqueue directional edges for modal use; Enter/I enqueue OPEN_INVENTORY in PLAY; Enter/Space enqueue ACCEPT in modal routing; Escape enqueues CANCEL. KEYUP and focus loss clear held state. A command queue entry is removed only by the active mode router.

- [ ] **Step 1: Write failing input-buffer tests**

```python
# SPDX-License-Identifier: GPL-2.0-only
import pygame

from maitd.ui import Command, InputBuffer, event_to_input


def key(kind, value, *, repeat=False):
    return pygame.event.Event(kind, key=value, repeat=repeat)


def test_held_movement_survives_command_consumption_and_action_is_edge_free():
    state = InputBuffer()
    assert event_to_input(key(pygame.KEYDOWN, pygame.K_UP), state)
    assert event_to_input(key(pygame.KEYDOWN, pygame.K_SPACE), state)
    assert state.held_joyd == 1
    assert state.action_held is True
    assert list(state.commands) == [Command.UP, Command.ACCEPT]
    state.commands.popleft()
    assert state.held_joyd == 1
    assert state.action_held is True


def test_keyup_and_focus_loss_release_controls_without_new_command():
    state = InputBuffer(held_joyd=1, action_held=True)
    event_to_input(key(pygame.KEYUP, pygame.K_UP), state)
    assert state.held_joyd == 0
    state.commands.append(Command.ACCEPT)
    event_to_input(pygame.event.Event(pygame.WINDOWFOCUSLOST), state)
    assert (state.held_joyd, state.action_held, state.focused) == (0, False, False)
    assert list(state.commands) == []


def test_inventory_shortcuts_are_single_edges():
    state = InputBuffer()
    event_to_input(key(pygame.KEYDOWN, pygame.K_RETURN), state)
    event_to_input(key(pygame.KEYDOWN, pygame.K_RETURN, repeat=True), state)
    event_to_input(key(pygame.KEYDOWN, pygame.K_i), state)
    assert list(state.commands) == [Command.OPEN_INVENTORY, Command.OPEN_INVENTORY]
```

- [ ] **Step 2: Write failing pure-reducer tests**

```python
# SPDX-License-Identifier: GPL-2.0-only
from maitd.ui import (
    Command, FoundPresenter, FoundResult, InventoryPresenter,
    reduce_found, reduce_inventory,
)


def test_forced_found_choice_cannot_select_take():
    state = FoundPresenter(FoundResult.LEAVE)
    assert reduce_found(state, Command.LEFT, forced_refuse=True) is None
    assert state.choice is FoundResult.LEAVE
    assert reduce_found(state, Command.ACCEPT, forced_refuse=True) is FoundResult.LEAVE


def test_inventory_two_stage_selection_is_bounded():
    state = InventoryPresenter()
    reduce_inventory(state, Command.DOWN, object_ids=(4, 8), action_ids=(23, 25))
    assert state.object_cursor == 1
    assert reduce_inventory(state, Command.ACCEPT, object_ids=(4, 8), action_ids=(23, 25)) is None
    assert state.choosing_action is True
    reduce_inventory(state, Command.DOWN, object_ids=(4, 8), action_ids=(23, 25))
    result = reduce_inventory(state, Command.ACCEPT, object_ids=(4, 8), action_ids=(23, 25))
    assert (result.object_idx, result.action_text_id) == (8, 25)
```

- [ ] **Step 3: Run tests and verify the UI module is absent**

Run: `.venv/bin/pytest tests/test_ui_input.py tests/test_ui_reducers.py -q`

Expected: collection fails because `maitd.ui` does not exist.

- [ ] **Step 4: Implement command types, input state, and event translation**

```python
# maitd/ui.py
# SPDX-License-Identifier: GPL-2.0-only
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto

import pygame


class Command(Enum):
    UP = auto(); DOWN = auto(); LEFT = auto(); RIGHT = auto()
    ACCEPT = auto(); CANCEL = auto(); OPEN_INVENTORY = auto()


@dataclass
class InputBuffer:
    held_joyd: int = 0
    action_held: bool = False
    focused: bool = True
    commands: deque = field(default_factory=deque)


_DIRECTION = {
    pygame.K_UP: (Command.UP, 1), pygame.K_w: (Command.UP, 1),
    pygame.K_DOWN: (Command.DOWN, 2), pygame.K_s: (Command.DOWN, 2),
    pygame.K_LEFT: (Command.LEFT, 4), pygame.K_a: (Command.LEFT, 4),
    pygame.K_RIGHT: (Command.RIGHT, 8), pygame.K_d: (Command.RIGHT, 8),
}


def event_to_input(event, state):
    if event.type == pygame.QUIT:
        return False
    if event.type == pygame.WINDOWFOCUSLOST:
        state.held_joyd = 0
        state.action_held = False
        state.focused = False
        state.commands.clear()
    elif event.type == pygame.WINDOWFOCUSGAINED:
        state.focused = True
    elif event.type == pygame.KEYDOWN:
        repeated = bool(getattr(event, "repeat", False))
        if event.key in _DIRECTION:
            command, bit = _DIRECTION[event.key]
            state.held_joyd |= bit
            if not repeated:
                state.commands.append(command)
        elif event.key == pygame.K_SPACE:
            state.action_held = True
            if not repeated:
                state.commands.append(Command.ACCEPT)
        elif not repeated and event.key in (pygame.K_RETURN, pygame.K_i):
            state.commands.append(Command.OPEN_INVENTORY)
        elif not repeated and event.key == pygame.K_ESCAPE:
            state.commands.append(Command.CANCEL)
    elif event.type == pygame.KEYUP:
        if event.key in _DIRECTION:
            state.held_joyd &= ~_DIRECTION[event.key][1]
        elif event.key == pygame.K_SPACE:
            state.action_held = False
    return True
```

- [ ] **Step 5: Implement reducer records and bounded transitions**

```python
class FoundResult(Enum):
    TAKE = auto()
    LEAVE = auto()


@dataclass
class FoundPresenter:
    choice: FoundResult = FoundResult.TAKE


@dataclass
class InventoryPresenter:
    object_cursor: int = 0
    action_cursor: int = 0
    choosing_action: bool = False


@dataclass(frozen=True)
class InventoryResult:
    object_idx: int = -1
    action_text_id: int = -1
    cancelled: bool = False


@dataclass
class ReadingPresenter:
    page: int = 0
    elapsed_ms: int = 0


@dataclass(frozen=True)
class ReadingResult:
    dismissed: bool
    page_delta: int = 0


def reduce_found(state, command, *, forced_refuse):
    if forced_refuse:
        state.choice = FoundResult.LEAVE
    elif command is Command.LEFT:
        state.choice = FoundResult.LEAVE
    elif command is Command.RIGHT:
        state.choice = FoundResult.TAKE
    if command is Command.CANCEL:
        return FoundResult.LEAVE
    if command is Command.ACCEPT:
        return state.choice
    return None


def reduce_inventory(state, command, *, object_ids, action_ids):
    if command is Command.CANCEL:
        if state.choosing_action:
            state.choosing_action = False
            state.action_cursor = 0
            return None
        return InventoryResult(cancelled=True)
    if not object_ids:
        return InventoryResult(cancelled=True)
    if command is Command.UP:
        field_name = "action_cursor" if state.choosing_action else "object_cursor"
        setattr(state, field_name, max(0, getattr(state, field_name) - 1))
    elif command is Command.DOWN:
        field_name = "action_cursor" if state.choosing_action else "object_cursor"
        limit = len(action_ids) - 1 if state.choosing_action else len(object_ids) - 1
        setattr(state, field_name, min(limit, getattr(state, field_name) + 1))
    elif command is Command.ACCEPT and not state.choosing_action:
        state.choosing_action = True
        state.action_cursor = 0
    elif command is Command.ACCEPT and action_ids:
        return InventoryResult(object_ids[state.object_cursor], action_ids[state.action_cursor])
    return None
```

- [ ] **Step 6: Run UI and full tests**

Run: `.venv/bin/pytest tests/test_ui_input.py tests/test_ui_reducers.py -q`

Expected: all selected tests pass.

Run: `.venv/bin/pytest -q`

Expected: no regression.

- [ ] **Step 7: Commit Task 9**

```bash
git add maitd/ui.py tests/test_ui_input.py tests/test_ui_reducers.py
git diff --cached --check
git commit -m "feat: add accessible modal command reducers"
```

---

### Task 10: ITD_RESS-backed modal and message presenters

**Files:**
- Modify: `maitd/ui.py`
- Test: `tests/test_ui_render.py`
- Test: `tests/test_ui_mouse.py`

**Interfaces:**
- Consumes: Task 3 asset methods, Task 9 presenter state, pygame `Surface`, `Font`, `Rect`, and `surfarray.array3d()`.
- Produces:
  - `ModalLayout` with logical-coordinate button/row rectangles
  - `layout_book(tokens, font, width: int, max_lines: int) -> tuple[tuple[tuple[str, bool], ...], ...]`; each line is `(text, centered)`
  - `render_found(effect, presenter, assets, found_name: str) -> np.ndarray`
  - `render_inventory(object_ids, action_ids, presenter, assets, scene_frame, object_names, action_names) -> np.ndarray`
  - `render_reading(effect, presenter, assets) -> np.ndarray`
  - `render_picture(effect, assets) -> np.ndarray`
  - `overlay_messages(frame, messages, assets) -> np.ndarray`
  - `hit_test_found(pos) -> FoundResult | None`
  - `hit_test_inventory(pos, presenter, object_ids, action_ids) -> InventoryResult | None`
  - `hit_test_reading(pos, page: int, page_count: int) -> ReadingResult | None`
- All frames are contiguous `uint8` arrays shaped `(200, 320, 3)`. Buttons are at least 96x28 logical pixels; inventory rows are at least 272x22 and the five-row list is scroll-windowed around the selected object.

- [ ] **Step 1: Write failing render and hit-target tests**

```python
# SPDX-License-Identifier: GPL-2.0-only
import numpy as np
import pygame

from maitd.effects import ReadText, ShowFound, ShowPicture, TimedMessage
from maitd.game import init_game
from maitd.text import BookToken
from maitd.ui import (
    FoundPresenter, FoundResult, InventoryPresenter, ModalLayout,
    ReadingPresenter, hit_test_found, hit_test_inventory, layout_book,
    overlay_messages, render_found, render_picture, render_reading,
)


def test_modal_renderers_return_logical_rgb_frames(data_dir):
    pygame.font.init()
    game = init_game(data_dir)
    frames = [
        render_found(
            ShowFound(13, False), FoundPresenter(), game.assets,
            game.assets.system_text(game.world_objects[13].found_name),
        ),
        render_reading(ReadText(1, 0), ReadingPresenter(), game.assets),
        render_picture(ShowPicture(10, 60, 4), game.assets),
    ]
    assert all(frame.shape == (200, 320, 3) for frame in frames)
    assert all(frame.dtype == np.uint8 for frame in frames)


def test_found_buttons_are_large_and_single_clickable():
    assert ModalLayout.FOUND_LEAVE.width >= 96
    assert ModalLayout.FOUND_LEAVE.height >= 28
    assert ModalLayout.FOUND_TAKE.width >= 96
    assert hit_test_found(ModalLayout.FOUND_LEAVE.center) is FoundResult.LEAVE
    assert hit_test_found(ModalLayout.FOUND_TAKE.center) is FoundResult.TAKE


def test_inventory_mouse_rows_follow_five_row_scroll_window():
    presenter = InventoryPresenter(object_cursor=5)
    object_ids = (10, 11, 12, 13, 14, 15)
    assert hit_test_inventory(
        ModalLayout.INVENTORY_ROWS[0].center,
        presenter,
        object_ids,
        (23,),
    ) is None
    assert presenter.object_cursor == 1
    assert presenter.choosing_action is True


def test_book_layout_preserves_tab_prefix_and_center_flag():
    pygame.font.init()
    pages = layout_book(
        (BookToken("tab"), BookToken("center"), BookToken("text", "Entry")),
        pygame.font.Font(None, 16),
        190,
        8,
    )
    assert pages[0][0] == ("    Entry", True)


def test_message_overlay_does_not_mutate_source_frame(data_dir):
    pygame.font.init()
    game = init_game(data_dir)
    source = np.zeros((200, 320, 3), dtype=np.uint8)
    result = overlay_messages(source, [TimedMessage(100), None, None, None, None], game.assets)
    assert np.count_nonzero(source) == 0
    assert np.count_nonzero(result) > 0
```

- [ ] **Step 2: Run tests and verify presenters are absent**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_render.py tests/test_ui_mouse.py -q`

Expected: imports fail for `ModalLayout` and render functions.

- [ ] **Step 3: Add surface conversion, layout, font, and frame helpers**

```python
import numpy as np


class ModalLayout:
    FOUND_LEAVE = pygame.Rect(28, 154, 120, 30)
    FOUND_TAKE = pygame.Rect(172, 154, 120, 30)
    INVENTORY_ROWS = tuple(pygame.Rect(24, 30 + i * 24, 272, 22) for i in range(5))
    INVENTORY_ACTIONS = tuple(pygame.Rect(24, 30 + i * 24, 272, 22) for i in range(5))
    READING_PREV = pygame.Rect(12, 164, 92, 28)
    READING_CLOSE = pygame.Rect(114, 164, 92, 28)
    READING_NEXT = pygame.Rect(216, 164, 92, 28)


def _font(size=16):
    if not pygame.font.get_init():
        pygame.font.init()
    return pygame.font.Font(None, size)


def _to_surface(frame):
    return pygame.surfarray.make_surface(np.ascontiguousarray(frame).swapaxes(0, 1))


def _to_frame(surface):
    return np.ascontiguousarray(pygame.surfarray.array3d(surface).swapaxes(0, 1))


def _button(surface, rect, label, selected=False):
    pygame.draw.rect(surface, (214, 190, 142) if selected else (78, 59, 46), rect, border_radius=3)
    pygame.draw.rect(surface, (245, 226, 178), rect, width=2, border_radius=3)
    glyph = _font(18).render(label, True, (20, 16, 12) if selected else (250, 242, 216))
    surface.blit(glyph, glyph.get_rect(center=rect.center))
```

- [ ] **Step 4: Implement book layout from FITD control tokens**

```python
def layout_book(tokens, font, width, max_lines):
    pages, lines = [], []
    centered = False
    prefix = ""

    def push_line(text):
        nonlocal centered, prefix, lines
        raw = prefix + text
        prefix = ""
        words = raw.split()
        current = raw[:len(raw) - len(raw.lstrip(" "))]
        for word in words:
            separator = "" if not current or current.endswith(" ") else " "
            candidate = f"{current}{separator}{word}"
            if current.strip() and font.size(candidate)[0] > width:
                lines.append((current, centered))
                current = word
                if len(lines) == max_lines:
                    pages.append(tuple(lines)); lines = []
            else:
                current = candidate
        if current or text.endswith("\n"):
            lines.append((current, centered))
            if len(lines) == max_lines:
                pages.append(tuple(lines)); lines = []
        centered = False

    for token in tokens:
        if token.kind == "page":
            if lines:
                pages.append(tuple(lines)); lines = []
        elif token.kind == "center":
            centered = True
        elif token.kind == "tab":
            prefix += "    "
        elif token.kind == "number":
            prefix += token.text
        elif token.kind == "text":
            chunks = token.text.split("\n")
            for index, chunk in enumerate(chunks):
                if chunk or index < len(chunks) - 1:
                    push_line(chunk + ("\n" if index < len(chunks) - 1 else ""))
    if lines or not pages:
        pages.append(tuple(lines))
    return tuple(pages)
```

- [ ] **Step 5: Implement modal renderers and message overlay**

```python
def render_found(effect, presenter, assets, found_name):
    surface = pygame.Surface((320, 200))
    surface.fill((17, 11, 9))
    title = _font(20).render(assets.system_text(20), True, (240, 220, 175))
    name = _font(18).render(found_name, True, (255, 255, 255))
    surface.blit(title, title.get_rect(center=(160, 34)))
    surface.blit(name, name.get_rect(center=(160, 78)))
    _button(surface, ModalLayout.FOUND_LEAVE, assets.system_text(21), presenter.choice is FoundResult.LEAVE)
    _button(surface, ModalLayout.FOUND_TAKE, assets.system_text(22), presenter.choice is FoundResult.TAKE)
    if effect.forced_refuse:
        warning = _font(16).render(assets.system_text(10), True, (255, 192, 128))
        surface.blit(warning, warning.get_rect(center=(160, 126)))
    return _to_frame(surface)


def render_picture(effect, assets):
    return np.ascontiguousarray(assets.resource_screen(effect.resource_index).copy())


def overlay_messages(frame, messages, assets):
    surface = _to_surface(frame.copy())
    y = 184
    font = _font(16)
    for message in messages:
        if message is None:
            continue
        glyph = font.render(assets.system_text(message.message_id), True, (255, 240, 185))
        shadow = font.render(assets.system_text(message.message_id), True, (0, 0, 0))
        rect = glyph.get_rect(center=(160, y))
        surface.blit(shadow, rect.move(1, 1))
        surface.blit(glyph, rect)
        y -= 16
    return _to_frame(surface)


def reading_pages(effect, assets):
    return layout_book(assets.book_tokens(effect.text_index), _font(16), 190, 8)


def render_reading(effect, presenter, assets):
    surface = _to_surface(assets.resource_screen({0: 6, 1: 7, 2: 8}[effect.kind]).copy())
    pages = reading_pages(effect, assets)
    presenter.page = min(presenter.page, len(pages) - 1)
    y = 20
    font = _font(16)
    for text, centered in pages[presenter.page]:
        glyph = font.render(text, True, (43, 31, 22))
        x = 160 - glyph.get_width() // 2 if centered else 60
        surface.blit(glyph, (x, y))
        y += 16
    _button(surface, ModalLayout.READING_PREV, "Previous", presenter.page > 0)
    _button(surface, ModalLayout.READING_CLOSE, "Close", True)
    _button(surface, ModalLayout.READING_NEXT, "Next", presenter.page + 1 < len(pages))
    return _to_frame(surface)


def render_inventory(object_ids, action_ids, presenter, assets, scene_frame,
                     object_names, action_names):
    surface = _to_surface((scene_frame.astype("f4") * 0.45).astype(np.uint8))
    rows = action_names if presenter.choosing_action else object_names
    cursor = presenter.action_cursor if presenter.choosing_action else presenter.object_cursor
    start = visible_start(cursor, len(rows))
    title_id = 200 if presenter.choosing_action else 20
    title = _font(20).render(assets.system_text(title_id), True, (255, 238, 198))
    surface.blit(title, title.get_rect(center=(160, 16)))
    for visible, rect in enumerate(ModalLayout.INVENTORY_ROWS):
        index = start + visible
        if index >= len(rows):
            break
        _button(surface, rect, rows[index], selected=index == cursor)
    return _to_frame(surface)


def visible_start(cursor, total):
    return min(max(0, cursor - 4), max(0, total - 5))
```

Update the Task 10 test call to `render_found(ShowFound(13, False), FoundPresenter(), game.assets, game.assets.system_text(game.world_objects[13].found_name))`. Passing the already-resolved name keeps world lookup out of `ui.py`.

- [ ] **Step 6: Implement direct, large mouse hit tests**

```python
def hit_test_found(pos):
    if ModalLayout.FOUND_LEAVE.collidepoint(pos):
        return FoundResult.LEAVE
    if ModalLayout.FOUND_TAKE.collidepoint(pos):
        return FoundResult.TAKE
    return None


def hit_test_inventory(pos, presenter, object_ids, action_ids):
    rows = action_ids if presenter.choosing_action else object_ids
    cursor = presenter.action_cursor if presenter.choosing_action else presenter.object_cursor
    start = visible_start(cursor, len(rows))
    for visible, rect in enumerate(
        ModalLayout.INVENTORY_ACTIONS if presenter.choosing_action else ModalLayout.INVENTORY_ROWS
    ):
        index = start + visible
        if index < len(rows) and rect.collidepoint(pos):
            if presenter.choosing_action:
                presenter.action_cursor = index
                return InventoryResult(object_ids[presenter.object_cursor], action_ids[index])
            presenter.object_cursor = index
            presenter.choosing_action = True
            presenter.action_cursor = 0
            return None
    return None


def hit_test_reading(pos, page, page_count):
    if ModalLayout.READING_CLOSE.collidepoint(pos):
        return ReadingResult(True)
    if page > 0 and ModalLayout.READING_PREV.collidepoint(pos):
        return ReadingResult(False, -1)
    if page + 1 < page_count and ModalLayout.READING_NEXT.collidepoint(pos):
        return ReadingResult(False, 1)
    return None
```

- [ ] **Step 7: Run headless UI and full tests**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_render.py tests/test_ui_mouse.py tests/test_ui_reducers.py -q`

Expected: all selected tests pass.

Run: `.venv/bin/pytest -q`

Expected: no regression.

- [ ] **Step 8: Commit Task 10**

```bash
git add maitd/ui.py tests/test_ui_render.py tests/test_ui_mouse.py
git diff --cached --check
git commit -m "feat: render accessible AITD1 modal screens"
```

---

### Task 11: Apply modal results without leaking gameplay rules into UI

**Files:**
- Modify: `maitd/interaction.py`
- Modify: `maitd/ui.py`
- Test: `tests/test_modal_results.py`

**Interfaces:**
- Consumes: `FoundResult`, `InventoryResult`, `ReadingResult`, the active typed modal, `begin_take()`, `choose_inventory_action()`, `resume_life()`, and presenter state.
- Produces:
  - `dismiss_modal(game) -> bool`
  - `apply_found_result(game, result: FoundResult) -> bool`
  - `apply_inventory_result(game, result: InventoryResult) -> bool`
  - `apply_reading_result(game, result: ReadingResult) -> bool`
  - `ModalSession(found: FoundPresenter, inventory: InventoryPresenter, reading: ReadingPresenter)` with `reset_for(effect) -> None`
- Closing READ/PICTURE sets `flag_init_view = 1`. LEAVE sets the object's `track_number = game.timer`. TAKE closes FOUND before running found-LIFE. Every completed result resumes the top LIFE continuation before the next fixed tick.

- [ ] **Step 1: Write failing modal-result tests**

```python
# SPDX-License-Identifier: GPL-2.0-only
from maitd.effects import GameMode, LifeFrame, OpenInventory, ReadText, ShowFound
from maitd.game import init_game
from maitd.interaction import apply_found_result, apply_inventory_result, apply_reading_result
from maitd.ui import FoundResult, InventoryResult, ReadingResult


def test_leave_debounces_and_resumes_parent(data_dir, monkeypatch):
    game = init_game(data_dir)
    game.life_stack.append(LifeFrame(0, 1, pc=6))
    game.open_modal(ShowFound(13, False))
    resumed = []
    monkeypatch.setattr("maitd.interaction.resume_life", lambda g: resumed.append(True) or True)
    assert apply_found_result(game, FoundResult.LEAVE) is True
    assert game.world_objects[13].track_number == game.timer
    assert game.mode is GameMode.PLAY
    assert resumed == [True]


def test_take_closes_found_before_nested_found_life(data_dir, monkeypatch):
    game = init_game(data_dir)
    game.open_modal(ShowFound(13, False))
    seen = []
    monkeypatch.setattr("maitd.interaction.begin_take", lambda g, i: seen.append((i, g.active_modal)) or False)
    assert apply_found_result(game, FoundResult.TAKE) is False
    assert seen == [(13, None)]


def test_inventory_cancel_and_read_dismiss_restore_play(data_dir, monkeypatch):
    game = init_game(data_dir)
    monkeypatch.setattr("maitd.interaction.resume_life", lambda g: True)
    game.open_modal(OpenInventory())
    assert apply_inventory_result(game, InventoryResult(cancelled=True)) is True
    game.open_modal(ReadText(1, 0))
    assert apply_reading_result(game, ReadingResult(True)) is True
    assert game.flag_init_view == 1
    assert game.mode is GameMode.PLAY
```

- [ ] **Step 2: Run tests and verify result application is absent**

Run: `.venv/bin/pytest tests/test_modal_results.py -q`

Expected: imports fail for `apply_found_result` and sibling functions.

- [ ] **Step 3: Implement close/resume and modal result services**

```python
def dismiss_modal(game):
    game.close_modal()
    return resume_life(game)


def apply_found_result(game, result):
    from maitd.effects import ShowFound
    from maitd.ui import FoundResult
    effect = game.active_modal
    if not isinstance(effect, ShowFound):
        raise RuntimeError(f"found result applied to {type(effect).__name__}")
    game.close_modal()
    if result is FoundResult.TAKE and not effect.forced_refuse:
        completed = begin_take(game, effect.object_idx)
        if not completed:
            return False
    else:
        game.world_objects[effect.object_idx].track_number = game.timer
    return resume_life(game)


def apply_inventory_result(game, result):
    from maitd.effects import OpenInventory
    if not isinstance(game.active_modal, OpenInventory):
        raise RuntimeError(f"inventory result applied to {type(game.active_modal).__name__}")
    game.close_modal()
    if not result.cancelled:
        if not choose_inventory_action(game, result.object_idx, result.action_text_id):
            return False
    return resume_life(game)


def apply_reading_result(game, result):
    from maitd.effects import ReadText, ShowPicture
    if not isinstance(game.active_modal, (ReadText, ShowPicture)):
        raise RuntimeError(f"reading result applied to {type(game.active_modal).__name__}")
    if not result.dismissed:
        return False
    game.close_modal()
    game.flag_init_view = 1
    return resume_life(game)
```

- [ ] **Step 4: Add resettable presenter session state**

```python
@dataclass
class ModalSession:
    found: FoundPresenter = field(default_factory=FoundPresenter)
    inventory: InventoryPresenter = field(default_factory=InventoryPresenter)
    reading: ReadingPresenter = field(default_factory=ReadingPresenter)
    effect_identity: int = 0

    def reset_for(self, effect):
        identity = id(effect)
        if identity == self.effect_identity:
            return
        self.effect_identity = identity
        self.found = FoundPresenter(
            FoundResult.LEAVE if getattr(effect, "forced_refuse", False) else FoundResult.TAKE
        )
        self.inventory = InventoryPresenter()
        self.reading = ReadingPresenter()
```

- [ ] **Step 5: Run focused, continuation, and full tests**

Run: `.venv/bin/pytest tests/test_modal_results.py tests/test_life_continuation.py tests/test_interaction.py -q`

Expected: all selected tests pass.

Run: `.venv/bin/pytest -q`

Expected: no regression.

- [ ] **Step 6: Commit Task 11**

```bash
git add maitd/interaction.py maitd/ui.py tests/test_modal_results.py
git diff --cached --check
git commit -m "feat: apply modal results and resume LIFE"
```

---

### Task 12: Single event/render loop and freeze-proof mode routing

**Files:**
- Modify: `maitd/__main__.py:1-260`
- Modify: `tests/test_play_loop.py`
- Test: `tests/test_runtime_modes.py`

**Interfaces:**
- Consumes: all earlier M3b interfaces plus existing `_camera_switch()`, `spawn_stage_actors()`, and scene drawing data.
- Produces:
  - `_scene_frame(game, floor, renderer) -> np.ndarray`
  - `apply_play_input(game, input_buffer: InputBuffer) -> None`
  - `route_command(game, session, command, scene_frame) -> bool`
  - `route_mouse(game, session, logical_pos, scene_frame) -> bool`
  - `play_tick(game, floor, input_buffer: InputBuffer) -> bool`
  - `render_active_mode(game, session, scene_frame) -> np.ndarray`
- `run()` calls `pygame.event.get()` once, processes every event, routes at most one queued command, accumulates ticks only in PLAY, resets accumulated PLAY time on modal entry, renders once, and calls `renderer.present()` once per outer frame.
- Existing `poll_input()` is removed after tests migrate to `InputBuffer`. No modal function contains a loop.

- [ ] **Step 1: Write failing runtime-mode tests**

```python
# SPDX-License-Identifier: GPL-2.0-only
from collections import deque

import numpy as np

from maitd.__main__ import apply_play_input, route_command
from maitd.effects import GameMode, OpenInventory, ShowPicture
from maitd.game import init_game
from maitd.ui import Command, InputBuffer, ModalSession


def test_play_input_reads_held_state_without_consuming_edges(data_dir):
    game = init_game(data_dir)
    state = InputBuffer(held_joyd=5, action_held=True, commands=deque([Command.OPEN_INVENTORY]))
    apply_play_input(game, state)
    assert (game.local_joyd, game.local_click, game.action) == (5, 1, 0x2000)
    assert list(state.commands) == [Command.OPEN_INVENTORY]


def test_inventory_edge_opens_once_and_play_ticks_pause(data_dir):
    game = init_game(data_dir)
    game.inventory_count[0] = 1
    game.inventory_table[0][0] = 13
    session = ModalSession()
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    assert route_command(game, session, Command.OPEN_INVENTORY, frame) is True
    assert game.mode is GameMode.INVENTORY
    assert isinstance(game.active_modal, OpenInventory)
    assert route_command(game, session, Command.OPEN_INVENTORY, frame) is True
    assert isinstance(game.active_modal, OpenInventory)


def test_picture_dismiss_does_not_leave_stale_movement_or_replay_command(data_dir):
    game = init_game(data_dir)
    game.open_modal(ShowPicture(10, 0, -1))
    session = ModalSession()
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    assert route_command(game, session, Command.ACCEPT, frame) is True
    assert game.mode is GameMode.PLAY
```

Update `tests/test_play_loop.py` input test:

```python
def test_apply_play_input_mapping(data_dir):
    game = init_game(data_dir)
    state = InputBuffer(held_joyd=9, action_held=True)
    apply_play_input(game, state)
    assert game.local_joyd == 9
    assert game.local_click == 1
    assert game.action == 0x2000
```

- [ ] **Step 2: Run tests and verify old polling/mode behavior fails**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_runtime_modes.py tests/test_play_loop.py -q`

Expected: imports fail for `apply_play_input` or `route_command`.

- [ ] **Step 3: Refactor `_draw` to return a scene frame and apply held input**

```python
# __main__.py import changes
from maitd.effects import GameMode
from maitd.game import AF_ANIMATED, AF_TRIGGER, change_salle, game_step_tick, init_game, spawn_stage_actors
from maitd.ui import Command, InputBuffer, ModalSession, event_to_input


def apply_play_input(game, input_buffer):
    game.local_joyd = input_buffer.held_joyd if input_buffer.focused else 0
    game.local_click = 1 if input_buffer.focused and input_buffer.action_held else 0
    game.local_key = 0
    game.action = 0x2000 if game.local_click else 0


def _scene_frame(game, floor, renderer):
    room = floor.rooms[game.current_room]
    cam_idx = room.camera_indices[game.num_camera]
    cam = floor.cameras[cam_idx]
    state = CameraState.from_camera(
        cam, room.world_x, room.world_y, room.world_z,
    ).angles()
    results = []
    actor_rooms = []
    actor_zvs = []
    translate_x = (cam.x - room.world_x) * 10
    translate_y = (room.world_y - cam.y) * 10
    translate_z = (room.world_z - cam.z) * 10
    draw_order = sort_actor_indices(game, translate_x, translate_y, translate_z)
    for index in draw_order:
        actor = game.actors[index]
        body = game.assets.body(actor.body_num)
        if actor.anim == -1:
            states = [(0, (0, 0, 0))] * len(body.groups)
        else:
            states = anim_player_for(game, index).group_states()
        results.append(skin(
            body,
            states,
            (
                actor.world_x + actor.step_x,
                actor.world_y + actor.step_y,
                actor.world_z + actor.step_z,
            ),
            state,
            actor_angles=(actor.alpha, actor.beta, actor.gamma),
        ))
        actor_rooms.append(actor.room)
        actor_zvs.append(actor.zv)
    masks = create_aitd1_mask(
        floor.camera_raw, floor.camera_data_offsets[cam_idx],
    )
    return renderer.compose_scene(
        floor.camera_image(cam_idx), results, masks, floor.palette,
        actor_rooms, actor_zvs,
    )
```

Delete `_draw()` after moving this exact calculation into `_scene_frame()`. Move caption setting into `run()` after presentation.

- [ ] **Step 4: Integrate interaction into one fixed PLAY tick**

```python
def _anim_pass(game):
    from maitd.interaction import gere_dec
    for index, actor in enumerate(game.actors):
        if actor.index_in_world < 0:
            continue
        flags = actor.object_type
        if flags & AF_ANIMATED:
            gere_anim(game, index)
            if game.mode is not GameMode.PLAY:
                return False
        if flags & AF_TRIGGER:
            gere_dec(game, index)
    return game.mode is GameMode.PLAY


def play_tick(game, floor, input_buffer):
    from maitd.effects import LifeFrame
    from maitd.interaction import (
        advance_messages, drain_immediate_effects, execute_found_life, run_life,
    )
    if game.mode is not GameMode.PLAY:
        return False
    apply_play_input(game, input_buffer)
    game_step_tick(game)
    in_hand = game.in_hand_table[game.current_inventory]
    if in_hand != -1 and not execute_found_life(game, in_hand):
        return False
    if not drain_immediate_effects(game) or game.mode is not GameMode.PLAY:
        return False
    for actor in game.actors:
        if actor.index_in_world >= 0:
            actor.col_by = actor.hit_by = actor.hit = actor.hard_dec = actor.hard_col = -1
    if not _anim_pass(game):
        return False
    for index, actor in enumerate(game.actors):
        if actor.index_in_world < 0:
            continue
        if life_gate(actor):
            if not run_life(game, LifeFrame(index, actor.life)):
                drain_immediate_effects(game)
                return False
            if not drain_immediate_effects(game):
                return False
        if game.flag_change_etage:
            break
    if game.flag_change_etage:
        game.current_floor = game.new_num_etage
        game.flag_change_etage = 0
        game.num_camera = -1
        game.flag_change_salle = 1
        return False
    if game.flag_change_salle:
        change_salle(game, game.new_num_salle)
        game.flag_change_salle = 0
        return False
    _camera_switch(game, floor)
    if game.flag_init_view:
        game.num_camera = game.new_num_camera
        game.flag_init_view = 0
    if game.flag_genere_aff_list:
        spawn_stage_actors(game)
        game.flag_genere_aff_list = 0
    advance_messages(game)
    return True
```

Place `game_step_tick()` after mode validation and input snapshot, as above. A modal result calls `resume_life()` outside this function, so no new game tick or timer increment occurs between dismissal and resumed opcodes.

- [ ] **Step 5: Implement keyboard command routing**

```python
def route_command(game, session, command, scene_frame):
    from maitd.effects import GameMode, OpenInventory, ReadText, ShowFound, ShowPicture
    from maitd.interaction import (
        apply_found_result, apply_inventory_result, apply_reading_result,
        inventory_actions, inventory_items,
    )
    from maitd.ui import (
        Command, ReadingResult, reading_pages, reduce_found, reduce_inventory,
        reduce_reading,
    )
    if game.mode is GameMode.PLAY:
        if command is Command.OPEN_INVENTORY and game.status_screen_allowed:
            if game.inventory_count[game.current_inventory]:
                game.open_modal(OpenInventory())
                session.reset_for(game.active_modal)
        return True

    session.reset_for(game.active_modal)
    modal_command = Command.ACCEPT if command is Command.OPEN_INVENTORY else command
    if isinstance(game.active_modal, ShowFound):
        result = reduce_found(
            session.found, modal_command,
            forced_refuse=game.active_modal.forced_refuse,
        )
        if result is not None:
            apply_found_result(game, result)
        return True
    if isinstance(game.active_modal, OpenInventory):
        object_ids = inventory_items(game)
        selected = object_ids[min(session.inventory.object_cursor, len(object_ids) - 1)]
        actions = inventory_actions(game, selected)
        result = reduce_inventory(
            session.inventory, modal_command,
            object_ids=object_ids, action_ids=actions,
        )
        if result is not None:
            apply_inventory_result(game, result)
        return True
    if isinstance(game.active_modal, ReadText):
        page_count = len(reading_pages(game.active_modal, game.assets))
        result = reduce_reading(session.reading, modal_command, page_count=page_count)
        if result is not None:
            apply_reading_result(game, result)
        return True
    if isinstance(game.active_modal, ShowPicture):
        if modal_command in (Command.ACCEPT, Command.CANCEL):
            apply_reading_result(game, ReadingResult(True))
        return True
    raise RuntimeError(f"unroutable modal {type(game.active_modal).__name__}")
```

Add this exact reading reducer to `maitd/ui.py`:

```python
def reduce_reading(state, command, *, page_count):
    if command is Command.CANCEL:
        return ReadingResult(True)
    if command in (Command.LEFT, Command.UP):
        state.page = max(0, state.page - 1)
    elif command in (Command.RIGHT, Command.DOWN, Command.ACCEPT):
        if state.page + 1 < page_count:
            state.page += 1
        else:
            return ReadingResult(True)
    return None
```

- [ ] **Step 6: Implement active-mode rendering and one outer loop**

```python
def route_mouse(game, session, logical_pos, scene_frame):
    from maitd.effects import OpenInventory, ReadText, ShowFound, ShowPicture
    from maitd.interaction import (
        apply_found_result, apply_inventory_result, apply_reading_result,
        inventory_actions, inventory_items,
    )
    from maitd.ui import (
        ReadingResult, hit_test_found, hit_test_inventory, hit_test_reading,
        reading_pages,
    )
    if logical_pos is None or game.active_modal is None:
        return True
    effect = game.active_modal
    session.reset_for(effect)
    if isinstance(effect, ShowFound):
        result = hit_test_found(logical_pos)
        if result is not None:
            apply_found_result(game, result)
        return True
    if isinstance(effect, OpenInventory):
        object_ids = inventory_items(game)
        selected = object_ids[min(session.inventory.object_cursor, len(object_ids) - 1)]
        action_ids = inventory_actions(game, selected)
        result = hit_test_inventory(
            logical_pos, session.inventory, object_ids, action_ids,
        )
        if result is not None:
            apply_inventory_result(game, result)
        return True
    if isinstance(effect, ReadText):
        page_count = len(reading_pages(effect, game.assets))
        result = hit_test_reading(
            logical_pos, session.reading.page, page_count,
        )
        if result is None:
            return True
        if result.page_delta:
            session.reading.page = min(
                page_count - 1,
                max(0, session.reading.page + result.page_delta),
            )
            return True
        apply_reading_result(game, result)
        return True
    if isinstance(effect, ShowPicture):
        apply_reading_result(game, ReadingResult(True))
        return True
    raise RuntimeError(f"unroutable modal {type(effect).__name__}")


def _auto_dismiss_picture(game, session):
    from maitd.effects import ShowPicture
    from maitd.interaction import apply_reading_result
    from maitd.ui import ReadingResult
    effect = game.active_modal
    if not isinstance(effect, ShowPicture) or effect.delay_units <= 0:
        return True
    delay_ms = effect.delay_units * 1000 // 60
    if session.reading.elapsed_ms < delay_ms:
        return True
    apply_reading_result(game, ReadingResult(True))
    return True


def render_active_mode(game, session, scene_frame):
    from maitd.effects import OpenInventory, ReadText, ShowFound, ShowPicture
    from maitd.interaction import inventory_actions, inventory_items
    from maitd.ui import (
        overlay_messages, render_found, render_inventory, render_picture,
        render_reading,
    )
    effect = game.active_modal
    if effect is None:
        return overlay_messages(scene_frame, game.messages, game.assets)
    session.reset_for(effect)
    if isinstance(effect, ShowFound):
        world = game.world_objects[effect.object_idx]
        return render_found(effect, session.found, game.assets, game.assets.system_text(world.found_name))
    if isinstance(effect, OpenInventory):
        object_ids = inventory_items(game)
        selected = object_ids[min(session.inventory.object_cursor, len(object_ids) - 1)]
        action_ids = inventory_actions(game, selected)
        return render_inventory(
            object_ids, action_ids, session.inventory, game.assets, scene_frame,
            tuple(game.assets.system_text(game.world_objects[i].found_name) for i in object_ids),
            tuple(game.assets.system_text(i) for i in action_ids),
        )
    if isinstance(effect, ReadText):
        return render_reading(effect, session.reading, game.assets)
    if isinstance(effect, ShowPicture):
        return render_picture(effect, game.assets)
    raise RuntimeError(f"unrenderable modal {type(effect).__name__}")


def run(game, trace_path=None):
    try:
        floor = Floor(game._data_dir, game.current_floor)
    except PakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    game.trace = Trace(trace_path) if trace_path else None
    renderer = Renderer()
    clock = pygame.time.Clock()
    input_buffer = InputBuffer()
    session = ModalSession()
    running = True
    last = pygame.time.get_ticks()
    accumulator = 0
    if game.num_camera == -1:
        game.num_camera = game.new_num_camera
        game.flag_init_view = 0
    scene_frame = _scene_frame(game, floor, renderer)
    while running:
        for event in pygame.event.get():
            running = event_to_input(event, input_buffer) and running
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                logical = renderer.window_to_logical(event.pos)
                running = route_mouse(game, session, logical, scene_frame) and running
        now = pygame.time.get_ticks()
        elapsed = min(now - last, 250)
        last = now
        if input_buffer.commands:
            command = input_buffer.commands.popleft()
            if game.mode is GameMode.PLAY and command is Command.CANCEL:
                running = False
            else:
                route_command(game, session, command, scene_frame)
        if game.mode is GameMode.PLAY:
            accumulator += elapsed
            while accumulator >= TICK_MS and game.mode is GameMode.PLAY:
                play_tick(game, floor, input_buffer)
                accumulator -= TICK_MS
                if floor.number != game.current_floor:
                    floor = Floor(game._data_dir, game.current_floor)
            scene_frame = _scene_frame(game, floor, renderer)
        else:
            accumulator = 0
            session.reading.elapsed_ms += elapsed
            _auto_dismiss_picture(game, session)
        renderer.present(render_active_mode(game, session, scene_frame))
        room = floor.rooms[game.current_room]
        cam_idx = room.camera_indices[game.num_camera]
        live = sum(1 for actor in game.actors if actor.index_in_world >= 0)
        pygame.display.set_caption(
            f"maitd — floor {floor.number} room {game.current_room} "
            f"camera {cam_idx} actors {live}"
        )
        clock.tick(60)
    if game.trace is not None:
        game.trace.close()
    renderer.close()
    return 0
```

The `delay_units * 1000 // 60` conversion is the documented M3b assumption mapping FITD chrono units to 60 Hz wall time while gameplay is paused. A zero delay waits for ACCEPT/CANCEL.

Add the window-to-logical conversion to `Renderer`:

```python
def window_to_logical(self, pos):
    win_w, win_h = pygame.display.get_window_size()
    scale = min(win_w / 320, win_h / 200)
    view_w = 320 * scale
    view_h = 200 * scale
    left = (win_w - view_w) / 2
    top = (win_h - view_h) / 2
    x, y = pos
    if x < left or x >= left + view_w or y < top or y >= top + view_h:
        return None
    return int((x - left) / scale), int((y - top) / scale)
```

Add these cases to `tests/test_runtime_modes.py` and `tests/test_render.py`:

```python
def test_mouse_reading_next_changes_page_without_resuming_life(data_dir, monkeypatch):
    game = init_game(data_dir)
    game.open_modal(ReadText(1, 0))
    session = ModalSession()
    monkeypatch.setattr(
        "maitd.ui.reading_pages", lambda effect, assets: (("one",), ("two",))
    )
    logical = ModalLayout.READING_NEXT.center
    assert route_mouse(game, session, logical, np.zeros((200, 320, 3), dtype=np.uint8))
    assert session.reading.page == 1
    assert game.mode is GameMode.READING


def test_window_to_logical_rejects_letterbox_and_scales_view(monkeypatch):
    renderer = object.__new__(Renderer)
    monkeypatch.setattr(pygame.display, "get_window_size", lambda: (800, 400))
    assert renderer.window_to_logical((79, 200)) is None
    assert renderer.window_to_logical((80, 0)) == (0, 0)
    assert renderer.window_to_logical((719, 399)) == (319, 199)
```

Import `ReadText`, `ModalLayout`, `route_mouse`, `pygame`, and `Renderer` in the corresponding test modules. Preserve all current user-owned render hunks while adding this method.

- [ ] **Step 7: Run runtime, freeze regression, pixel, and full tests**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_runtime_modes.py tests/test_play_loop.py tests/test_ui_input.py tests/test_ui_render.py tests/test_render.py -q`

Expected: all selected tests pass. Specifically, held movement survives modal dismissal, one Enter produces one inventory transition, focus loss clears held controls, and no test pumps a nested event loop.

Run: `.venv/bin/pytest -q`

Expected: no regression.

- [ ] **Step 8: Commit only Task 12 hunks**

```bash
git add tests/test_runtime_modes.py
git add -p maitd/__main__.py maitd/render.py tests/test_play_loop.py tests/test_render.py
git diff --cached --check
git commit -m "feat: route M3b modes through one game loop"
```

---

### Task 13: Real-data attic journey and accessibility proof

**Files:**
- Create: `tests/test_m3b_attic.py`
- Create: `docs/m3b-interaction-proof.md`
- Modify: `Makefile`
- Modify: `CONTEXT.md`

**Interfaces:**
- Consumes: the completed M3b public interfaces and original INDARK fixture.
- Produces: `make prove-m3b`, a deterministic object-13 attic checkpoint, and concise manual keyboard/on-screen-keyboard/single-button evidence instructions.
- The real-data test uses attic object 13: Oil Lamp, `found_name == 201`, `found_life == 9`, initial `found_flag == 1545`, `found_body == 10`, and weight 30.

- [ ] **Step 1: Write the failing real-data attic journey**

```python
# SPDX-License-Identifier: GPL-2.0-only
from maitd.effects import OpenInventory
from maitd.game import init_game
from maitd.interaction import (
    apply_found_result, apply_inventory_result, inventory_actions,
    inventory_items, request_found,
)
from maitd.ui import FoundResult, InventoryResult


def test_attic_lamp_find_take_use_and_drop_checkpoint(data_dir):
    game = init_game(data_dir)
    game.timer = 300
    lamp_idx = 13
    lamp = game.world_objects[lamp_idx]
    assert (lamp.stage, lamp.room, lamp.found_name, lamp.found_life) == (0, 0, 201, 9)
    assert (lamp.found_flag, lamp.found_body, lamp.position_in_track) == (1545, 10, 30)
    assert lamp.track_number == -1

    found = request_found(game, lamp_idx, parameter=0)
    assert found is not None
    game.open_modal(found)
    apply_found_result(game, FoundResult.TAKE)
    assert lamp_idx in inventory_items(game)
    assert lamp.found_flag & 0x8000
    assert (lamp.stage, lamp.room, lamp.obj_index) == (-1, -1, -1)

    game.open_modal(OpenInventory())
    actions = inventory_actions(game, lamp_idx)
    assert 23 in actions
    apply_inventory_result(game, InventoryResult(lamp_idx, 23))
    assert game.in_hand_table[0] == lamp_idx
    assert game.action == 1

    game.open_modal(OpenInventory())
    assert 33 in inventory_actions(game, lamp_idx)
    apply_inventory_result(game, InventoryResult(lamp_idx, 33))
    assert lamp_idx not in inventory_items(game)
    assert lamp.found_flag & 0x4000
```

This test intentionally traverses real lamp LIFE 9 for TAKE, Use, and Drop/Put. Do not bypass found-LIFE or call `_finish_take()` directly in this acceptance test. The initial `0x609` flag exposes system-text actions 23, 26, 32, and 33; FITD `take()` clears the separate in-world bit `0x4000`, so action 33 remains available after TAKE.

The `game.timer = 300` setup crosses FITD `FoundObjet()`'s initial `trackNumber == -1` debounce without changing object data; it is the deterministic equivalent of spending six seconds in the 50 Hz attic before touching the lamp.

- [ ] **Step 2: Run the attic journey and correct only verified FITD differences**

Run: `.venv/bin/pytest tests/test_m3b_attic.py -q -vv`

Expected: the test passes using original data. If a checkpoint differs, trace the same object through FITD `FoundObjet`, `take`, `executeFoundLife`, `processInventory`, and `drop`, update the expected stable checkpoint, and cite the FITD file and line in a test comment.

- [ ] **Step 3: Add a focused proof target**

```makefile
.PHONY: prove-m3b
prove-m3b:
	SDL_VIDEODRIVER=dummy .venv/bin/pytest \
		tests/test_life_continuation.py \
		tests/test_interaction.py \
		tests/test_actor_contacts.py \
		tests/test_gere_dec.py \
		tests/test_life_interaction_ops.py \
		tests/test_runtime_modes.py \
		tests/test_m3b_attic.py -q
```

- [ ] **Step 4: Write the manual accessibility and responsiveness proof**

```markdown
# M3b interaction proof

## Keyboard-only

1. Start with `make run` and walk to the oil lamp with arrows or WASD.
2. In FOUND, use Left/Right and Enter; repeat once with Escape to leave it.
3. Open inventory with Enter or I, choose the lamp and Use with arrows and Enter.
4. Open inventory again, choose Drop/Put, then resume movement immediately.
5. Open and close a readable object; verify the page does not reopen and movement resumes.

## On-screen keyboard

Repeat the journey using only the macOS Accessibility Keyboard: arrows, Enter,
Space, I, and Escape. Record whether every press produces exactly one menu edge.

## Single-button mouse

Repeat FOUND, inventory object/action selection, reading navigation, and close
using only left click. Verify every target accepts a click near each corner and
letterbox clicks do nothing.

## Focus and freeze regression

Hold Up, move focus away from the window, return, release Up, and press Up again.
The actor must stop on focus loss, no modal may dismiss on focus return, and the
new Up press must move without a stall. Leave each modal open for ten seconds;
the window must continue repainting and closing normally.
```

- [ ] **Step 5: Update `CONTEXT.md` with the M3b ownership and verification commands**

Add this section without rewriting the user's existing scene/render notes:

```markdown
## M3b interaction boundary

- `effects.py`: typed immediate/modal effects and resumable LIFE frames.
- `interaction.py`: found-LIFE, inventory/world transitions, contacts, and GereDec.
- `ui.py`: command buffering, modal reducers, mouse targets, and 320x200 presenters.
- `__main__.py`: one event pump, PLAY-only fixed ticks, mode routing, one present.
- Focused proof: `make prove-m3b`.
- Full regression: `.venv/bin/pytest -q && make prove`.
- Manual evidence: `docs/m3b-interaction-proof.md`.
```

- [ ] **Step 6: Run every M3b gate**

Run: `make prove-m3b`

Expected: every focused interaction test passes.

Run: `.venv/bin/pytest -q`

Expected: all tests pass with one existing optional-data skip.

Run: `make prove`

Expected: parse-all and headless real-data checks pass.

Run: `rg -n "M3b stub|M3b skip|blocking wait skipped|CheckObjectCol.*skipped|GereDec.*skipped" maitd tests`

Expected: no match in the M3b-owned interaction/text/runtime paths. Audio references must identify M4b, and fall/combat references must identify M3c.

- [ ] **Step 7: Commit Task 13 without absorbing prior user edits**

```bash
git add tests/test_m3b_attic.py docs/m3b-interaction-proof.md Makefile
git add -p CONTEXT.md
git diff --cached --check
git commit -m "test: prove M3b attic interaction journey"
```

---

## Final verification gate

- [ ] Run `.venv/bin/pytest -q`; require zero failures.
- [ ] Run `make prove-m3b`; require zero failures.
- [ ] Run `make prove`; require zero failures.
- [ ] Run `git diff --check`; require no whitespace errors.
- [ ] Run `git status --short`; verify every remaining dirty hunk is pre-existing user work or an intentionally uncommitted M3b change.
- [ ] Perform the four journeys in `docs/m3b-interaction-proof.md` in the windowed app and record the result in the implementation handoff.
- [ ] Confirm M3c still owns fall/combat/death and M4a/M4b still own system menus/persistence and audio/sequences; no implementation from those slices enters this branch.
