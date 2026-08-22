# M3a: AITD1 LIFE VM Core + World Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port FITD's LIFE script VM plus the world model (OBJETS/VARS/DEFINES world objects, CVars, actor table, tracks) so the game boots from its real scripts — intro scene runs, objects spawn, doors open, floor changes work. Player controlled through their own script (script-driven input).

**Architecture:** A table-driven interpreter faithfully ports `life.cpp` processLife (88-entry AITD1 opcode table, evalVar encodings, 0x8000 actor-switch dispatch, no call stack), `track.cpp` processTrack (modes manual/follow/track with TL_* macros), and `mainLoop.cpp` PlayWorld tick order. `Game` owns CVars/vars/world objects/actor table/input snapshot; the VM mutates Game through narrow APIs only. Scripts fetch through the existing assets LRU.

**Tech Stack:** Python 3.12, numpy, pygame-ce, ModernGL, pytest. No new dependencies.

## Research corrections (plan supersedes spec where they conflict)

Research (`docs/life-vm-opcodes.md` + fresh FITD extraction) found four deltas vs the M3a spec. The plan follows research:

1. **87 opcode slots (0..86), not 77, not 88.** `AITD1LifeMacroTable` (AITD1.cpp:30-119) has 87 entries; opcode 87 is out-of-range. Index == macro enum value (life.h). Dead entries (in table, no dispatch case in life.cpp → `default: assert(0)`): **27 LM_CAMERA, 57 LM_STOP_BETA, 61 LM_DO_NORMAL_ZV, 69 LM_SPEED** — raise ValueError. Slots 17-23 are real: LM_MESSAGE(17), LM_MESSAGE_VALUE(18), LM_VAR(19), LM_INC(20), LM_DEC(21), LM_ADD(22), LM_SUB(23).
2. **No call stack, no re-entry guard.** `currentLifePtr` is a plain cursor; `LM_RETURN` ≡ `LM_END` (both exit); `LM_LIFE` only assigns `actor->life` and the next main-loop tick runs it (gate: AITD1 `life != -1 && lifeMode != -1`, mainLoop.cpp:172-174). The spec's "re-entry guard: a script already on the current call stack is skipped" does not exist — drop it.
3. **`LM_READ` AITD1 skips an extra s16** after its 2 args (replicate or scripts desync). **`LM_WAIT_GAME_OVER`** has FITD's bug: second wait `while (!key && !JoyD && Click)` — Click NOT negated. Port both waits bug-for-bug.
4. **DEFINES.ITD stores CVars big-endian** (main.cpp:1151-1154 byteswaps after read). VARS.ITD is a raw s16 array (evalVar tag 0 reads it directly, read-only in AITD1).

## Global Constraints

- Python `>= 3.12`; Apple Silicon, windowed. No new dependencies (pygame-ce, moderngl, numpy, pytest).
- License GPLv2: every new/modified source file keeps `# SPDX-License-Identifier: GPL-2.0-only`.
- Reference implementation: FITD at `/Users/felipe.dos.santos/code/theirs/FITD/FitdLib/` — reproduce its arithmetic exactly. C integer division = truncation toward zero: use `int(v / N)`; shifts use `>>`. `GiveDistance2D` uses C `sqrt()` (double, truncated): `int(math.sqrt(v))`.
- All life/track data is little-endian s16. Script PC counts bytes. Jump offsets are in s16 units: `pc = after_jump_word + jump * 2`.
- Logic tick fixed 50Hz; timer = tick counter (u32, `& 0xFFFF` where FITD masks).
- Errors: unknown opcode / dead opcode / bad evalVar code / unknown track macro raise ValueError with life number, actor, and byte offset (FITD asserts).
- Game data read in place; tests skip when data absent (existing `data_dir` fixture).
- Existing 72 tests stay green; M2's `player_step` direct-input helper is removed (script-driven now) — it has no tests, safe to delete.

## Verified golden values (real game data — do not re-derive)

- `OBJETS.ITD`: 15186 bytes; u16 count 292; 292 records × 52 bytes (26 s16 each, AITD1 has no `mark` field). Record order: objIndex, body, flags, typeZV, foundBody, foundName, foundFlag, foundLife, x, y, z, alpha, beta, gamma, stage, room, lifeMode, life, floorLife, anim, frame, animType, animInfo, trackMode, trackNumber, positionInTrack. Loader sets `flags |= 0x20` per record. Record 0: objIndex -1, body 0, flags 0, typeZV 3, foundBody -1, foundName -1, foundFlag 0, foundLife -1, x -5513, y 0, z -395, alpha 0, beta 768, gamma 0, stage 0, room 0, lifeMode 1, life 0, anim -1, track (0, -1, 20).
- `VARS.ITD`: 414 bytes = 207 s16 script vars.
- `DEFINES.ITD`: 90 bytes = 45 CVars, stored big-endian. Byteswapped first 9: [49, 270, 700, 18, 6, 19, 20, 1, 0] — so CVars[7] (WORLD_NUM_PERSO) = 1, CVars[8] (CHOOSE_PERSO) = 0.
- `PRIORITY.ITD`: 101 bytes (audio sample priority — M3a parses only, semantics M4).
- `LISTLIFE.PAK`: 563 entries. `LISTTRAK.PAK`: 45 entries.
- AITD1 CVar table (index → enum): 0 SAMPLE_PAGE, 1 BODY_FLAMME, 2 MAX_WEIGHT_LOADABLE, 3 TEXTE_CREDITS, 4 SAMPLE_TONNERRE, 5 INTRO_DETECTIVE, 6 INTRO_HERITIERE, 7 WORLD_NUM_PERSO, 8 CHOOSE_PERSO, 9 SAMPLE_CHOC, 10 SAMPLE_PLOUF, 11 REVERSE_OBJECT, 12 KILLED_SORCERER, 13 LIGHT_OBJECT, 14 FOG_FLAG, 15 DEAD_PERSO, 16..44 unused.
- JoyD bits: up=1 (forward), down=2 (backward), left=4, right=8. SPACE → Click=1, ENTER → key 0x1C, ESC → key 0x1B.
- PlayWorld tick order (mainLoop.cpp:41-281): process events → snapshot localKey/localJoyD/localClick → action = 0x2000 if Click else 0 → executeFoundLife(inHand) [M3b stub] → clear per-actor COL_BY/HIT_BY/HIT/HARD_DEC/HARD_COL → per actor: anim advance (AF_ANIMATED), GereDec (AF_TRIGGER, M3b), GereFrappe (animActionType, M3c) → per actor: processLife gate → FlagChangeEtage → LoadEtage → FlagChangeSalle → ChangeSalle + InitView + continue → GereSwitchCamera → InitView if FlagInitView → GenereActiveList → GenereAffList → sortActorList → handleAnim2d → draw.

---

### Task 1: World-data parsers

**Files:**
- Modify: `maitd/formats.py` (append)
- Test: `tests/test_world_data.py`

**Interfaces:**
- Consumes: `data_dir` fixture, `maitd.formats` helpers `_u16`/`_s16` (M1).
- Produces (all pure, no I/O):
  - `@dataclass WorldObject` — 26 s16 fields in FITD order (`obj_index, body, flags, type_zv, found_body, found_name, found_flag, found_life, x, y, z, alpha, beta, gamma, stage, room, life_mode, life, floor_life, anim, frame, anim_type, anim_info, track_mode, track_number, position_in_track`)
  - `def parse_objets(raw: bytes) -> list[WorldObject]` — u16 count header; per-record `flags |= 0x20`
  - `def parse_vars(raw: bytes) -> list[int]` — raw s16 array (207 entries)
  - `def parse_defines(raw: bytes) -> list[int]` — 45 u16 big-endian → byteswapped to ints
  - `def parse_priority(raw: bytes) -> list[int]` — raw s16 array (50 s16 + trailing byte ignored; semantics M4)

- [ ] **Step 1: Write failing tests** `tests/test_world_data.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
import pathlib

from maitd.formats import parse_defines, parse_objets, parse_priority, parse_vars


def test_objets_golden(data_dir):
    raw = (pathlib.Path(data_dir) / "OBJETS.ITD").read_bytes()
    assert len(raw) == 15186
    objs = parse_objets(raw)
    assert len(objs) == 292
    o = objs[0]
    assert (o.obj_index, o.body, o.type_zv, o.found_body, o.found_name) == (-1, 0, 3, -1, -1)
    assert (o.found_flag, o.found_life) == (0, -1)
    assert (o.x, o.y, o.z) == (-5513, 0, -395)
    assert (o.stage, o.room, o.life_mode, o.life, o.anim) == (0, 0, 1, 0, -1)
    assert (o.track_mode, o.track_number, o.position_in_track) == (0, -1, 20)
    assert o.flags & 0x20  # loader ORs 0x20 into every record


def test_vars_golden(data_dir):
    raw = (pathlib.Path(data_dir) / "VARS.ITD").read_bytes()
    assert len(raw) == 414
    vars_ = parse_vars(raw)
    assert len(vars_) == 207


def test_defines_golden(data_dir):
    raw = (pathlib.Path(data_dir) / "DEFINES.ITD").read_bytes()
    assert len(raw) == 90
    cvars = parse_defines(raw)
    assert len(cvars) == 45
    assert cvars[:9] == [49, 270, 700, 18, 6, 19, 20, 1, 0]
    assert cvars[7] == 1   # WORLD_NUM_PERSO
    assert cvars[8] == 0   # CHOOSE_PERSO


def test_priority_golden(data_dir):
    raw = (pathlib.Path(data_dir) / "PRIORITY.ITD").read_bytes()
    assert len(raw) == 101
    assert len(parse_priority(raw)) == 50
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/pytest tests/test_world_data.py -q`
Expected: FAIL, `ImportError: cannot import name 'parse_objets'`.

- [ ] **Step 3: Append to `maitd/formats.py`**

```python
@dataclass
class WorldObject:
    obj_index: int
    body: int
    flags: int
    type_zv: int
    found_body: int
    found_name: int
    found_flag: int
    found_life: int
    x: int
    y: int
    z: int
    alpha: int
    beta: int
    gamma: int
    stage: int
    room: int
    life_mode: int
    life: int
    floor_life: int
    anim: int
    frame: int
    anim_type: int
    anim_info: int
    track_mode: int
    track_number: int
    position_in_track: int


_WORLD_OBJ_FIELDS = (
    "obj_index", "body", "flags", "type_zv", "found_body", "found_name",
    "found_flag", "found_life", "x", "y", "z", "alpha", "beta", "gamma",
    "stage", "room", "life_mode", "life", "floor_life", "anim", "frame",
    "anim_type", "anim_info", "track_mode", "track_number", "position_in_track",
)


def parse_objets(raw):
    # FITD LoadWorld (main.cpp:1005): u16 count + fixed 26-s16 records, flags |= 0x20
    count = _u16(raw, 0)
    p = 2
    out = []
    for _ in range(count):
        values = list(struct.unpack_from("<26h", raw, p))
        p += 52
        values[2] |= 0x20
        out.append(WorldObject(*values))
    return out


def parse_vars(raw):
    # VARS.ITD: raw s16 array read by evalVar tag 0 (read-only in AITD1)
    n = len(raw) // 2
    return list(struct.unpack_from(f"<{n}h", raw, 0))


def parse_defines(raw):
    # DEFINES.ITD: 45 CVars stored big-endian; LoadWorld byteswaps (main.cpp:1151)
    n = len(raw) // 2
    values = list(struct.unpack_from(f"<{n}H", raw, 0))
    return [((v & 0xFF) << 8) | ((v & 0xFF00) >> 8) for v in values]


def parse_priority(raw):
    # PRIORITY.ITD: raw s16 array (odd trailing byte ignored); semantics M4
    n = len(raw) // 2
    return list(struct.unpack_from(f"<{n}h", raw, 0))
```

Note: `dataclass` and `struct` already imported in `maitd/formats.py`; `_u16` exists from M1. Append only.

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_world_data.py -q`
Expected: 4 passed. Then full suite: `.venv/bin/pytest -q` — expect 76 passed.

- [ ] **Step 5: Commit**

```bash
git add maitd/formats.py tests/test_world_data.py
git commit -m "feat: world-data parsers (OBJETS/VARS/DEFINES/PRIORITY)"
```

---

### Task 2: Script and track asset registry

**Files:**
- Modify: `maitd/assets.py` (append)
- Test: `tests/test_assets_life.py`

**Interfaces:**
- Consumes: `maitd.floor.load_entry` (M1 LRU), `find_pak`.
- Produces (append to `Assets`):
  - `.num_lifes: int` (563), `.num_tracks: int` (45)
  - `.life(index: int) -> bytes`, `.track(index: int) -> bytes` — KeyError out of range

- [ ] **Step 1: Write failing tests** `tests/test_assets_life.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
import pytest

from maitd.assets import Assets


def test_counts(data_dir):
    assets = Assets(data_dir)
    assert assets.num_lifes == 563
    assert assets.num_tracks == 45


def test_fetch(data_dir):
    assets = Assets(data_dir)
    assert len(assets.life(0)) > 0
    assert assets.life(0) == assets.life(0)
    assert len(assets.track(0)) > 0


def test_out_of_range(data_dir):
    assets = Assets(data_dir)
    with pytest.raises(KeyError):
        assets.life(9999)
    with pytest.raises(KeyError):
        assets.track(9999)
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/pytest tests/test_assets_life.py -q`
Expected: FAIL, `AttributeError: 'Assets' object has no attribute 'num_lifes'`.

- [ ] **Step 3: Append to `maitd/assets.py`**

```python
LIFES_PAK = "LISTLIFE"
TRACKS_PAK = "LISTTRAK"


class Assets:
    # (append to existing __init__:)
    def __init__(self, data_dir):
        # ... existing M2 lines ...
        self._lifes_pak = str(find_pak(data_dir, LIFES_PAK))
        self._tracks_pak = str(find_pak(data_dir, TRACKS_PAK))
        self.num_lifes = Pak(self._lifes_pak).count
        self.num_tracks = Pak(self._tracks_pak).count

    def life(self, index):
        if not 0 <= index < self.num_lifes:
            raise KeyError(f"life {index} out of range (0..{self.num_lifes - 1})")
        return load_entry(self._lifes_pak, index)

    def track(self, index):
        if not 0 <= index < self.num_tracks:
            raise KeyError(f"track {index} out of range (0..{self.num_tracks - 1})")
        return load_entry(self._tracks_pak, index)
```

Note: implementer adapts to the existing `__init__` body — do not duplicate it.

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_assets_life.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add maitd/assets.py tests/test_assets_life.py
git commit -m "feat: LISTLIFE/LISTTRAK asset registry"
```

---

### Task 3: Game state and init

**Files:**
- Create: `maitd/game.py`
- Test: `tests/test_game.py`

**Interfaces:**
- Consumes: `parse_objets/parse_vars/parse_defines` (task 1), `Assets` (task 2), `WorldObject` (task 1), M2 `Floor` for stage data.
- Produces:
  - `NUM_MAX_OBJECT = 128`
  - `@dataclass Actor` — full tObject port (vars.h:109-180): `index_in_world=-1, body_num=0, object_type=0, dyn_flags=0, zv=(0,0,0,0,0,0), room_x=0, room_y=0, room_z=0, world_x=0, world_y=0, world_z=0, alpha=0, beta=0, gamma=0, chrono=0, room_chrono=0, anim=-1, anim_type=0, anim_info=0, new_anim=-1, new_anim_type=0, new_anim_info=0, frame=0, num_of_frames=0, end_frame=0, flag_end_anim=0, track_mode=0, track_number=0, mark=-1, position_in_track=0, step_x=0, step_y=0, step_z=0, y_handler=RealValue(), falling=0, rotate=RealValue(), direction=0, speed=0, col=(-1,-1,-1), col_by=-1, hard_dec=-1, hard_col=-1, hit=-1, hit_by=-1, anim_action_type=0, anim_action_anim=-1, anim_action_frame=0, anim_action_param=0, hit_force=0, hot_point_id=-1, hot_point=(0,0,0), stage=0, room=0, life=-1, life_mode=-1, hit_actor=... placeholder list for COL/HIT tracking` — implementer uses dataclass field defaults with `field(default_factory=...)` for mutable members.
  - `class Game` — `Game(data_dir, hero=0)`:
    - `.assets: Assets`, `.world_objects: list[WorldObject]` (292), `.actors: list[Actor]` (128 slots, index_in_world -1), `.cvars: list[int]` (45 from DEFINES + CHOOSE_PERSO forced `hero`), `.vars: list[int]` (207), `.timer: int = 0`
    - input snapshot: `.local_joyd=0, .local_key=0, .local_click=0, .action=0`
    - globals: `.current_floor=0, .current_room=0, .current_stage=0, .num_camera=-1, .new_num_camera=0, .current_camera_target_actor=-1, .current_world_target=1` (CVars[WORLD_NUM_PERSO]), flags `.flag_change_etage=0, .new_num_etage=0, .flag_change_salle=0, .new_num_salle=0, .flag_init_view=2, .flag_game_over=0, .flag_genere_aff_list=1`
    - inventory stubs: `.in_hand_table=[-1]*..., .current_inventory=0, .status_screen_allowed=1`, audio stubs: `.current_music=-1, .next_music=-1, .light_off=0`
  - `def init_game(data_dir, hero=0) -> Game` — startGame order: LoadWorld → initVars → `currentWorldTarget = CVars[7]` → spawn stage actors (`GenereActiveList` port below) → `num_camera=-1` → `ChangeSalle(0)` → `new_num_camera=0`, `flag_init_view=2`
  - `def spawn_stage_actors(game)` — GenereActiveList port (main.cpp:1990-2130): delete out-of-scope actors (DeleteObjet → actor.index_in_world=-1, world obj.obj_index=-1, found_flag clearing); for each world obj with `obj_index == -1` and `stage == current_floor` and lifeMode gate (life != -1: mode -1 skip, 0 pass, 1 require `room == current_room`, 2 require room in view list — M3a: accept room; else: pass), `obj_index = add_actor(...)` — port of `InitObjet` (main.cpp ~1930-1985): copy world fields into actor (body, type_zv, flags & ~AF_SPECIAL, x/y/z, stage, room, alpha/beta/gamma, anim, frame, anim_type, anim_info), set `dyn_flags = (flags & 0x20) / 0x20`, `life`, `life_mode`, `track_mode/track_number/position_in_track`, `zv = body.zv + (x,y,z)` via `GiveZVObjet` (M2 `actor_zv`), `worldX/Y/Z` set from room offsets (M1 room world coords ×10); if world obj index == `current_world_target`: `current_camera_target_actor = actor_idx`. (No foundFlag writes here — FITD sets foundFlag |= 0x4000 in life opcodes, task 8.)
  - `def game_step_tick(game)` — `game.timer += 1`

- [ ] **Step 1: Write failing tests** `tests/test_game.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
from maitd.game import NUM_MAX_OBJECT, Game, init_game


def test_init_golden(data_dir):
    game = init_game(data_dir, hero=0)
    assert len(game.world_objects) == 292
    assert len(game.actors) == NUM_MAX_OBJECT
    assert len(game.cvars) == 45
    assert len(game.vars) == 207
    assert game.cvars[7] == 1 and game.cvars[8] == 0
    assert game.current_world_target == 1


def test_stage_actors_spawned(data_dir):
    game = init_game(data_dir, hero=0)
    spawned = [a for a in game.actors if a.index_in_world != -1]
    assert len(spawned) > 0
    for a in spawned:
        assert game.world_objects[a.index_in_world].obj_index == game.actors.index(a)
    # player world object is the camera target
    assert game.current_camera_target_actor != -1


def test_tick(data_dir):
    game = init_game(data_dir, hero=0)
    game.timer = 0
    game_step_tick(game)
    assert game.timer == 1
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/pytest tests/test_game.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'maitd.game'`.

- [ ] **Step 3: Implement** `maitd/game.py`

Skeleton (implementer completes `add_actor`/`spawn_stage_actors` per the FITD references in Interfaces; RealValue import from task 6 — if task 6 lands first, import `maitd.realvalue`; otherwise define `RealValue` here and have task 6 move it, keeping import compatible):

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Game state: CVars, script vars, world objects, actor table (FITD main.cpp ports)."""
from dataclasses import dataclass, field

from maitd.assets import Assets
from maitd.formats import parse_defines, parse_objets, parse_vars

NUM_MAX_OBJECT = 128
NUM_CVARS = 45

AF_ANIMATED = 0x0001
AF_DRAWABLE = 0x0004
AF_SPECIAL = 0x0020
AF_TRIGGER = 0x0040
AF_FOUNDABLE = 0x0080
AF_MASK = AF_ANIMATED + 0x10 + AF_TRIGGER + AF_FOUNDABLE + 0x100 + 0x400

AITD1_CVAR_NAMES = (
    "SAMPLE_PAGE", "BODY_FLAMME", "MAX_WEIGHT_LOADABLE", "TEXTE_CREDITS",
    "SAMPLE_TONNERRE", "INTRO_DETECTIVE", "INTRO_HERITIERE", "WORLD_NUM_PERSO",
    "CHOOSE_PERSO", "SAMPLE_CHOC", "SAMPLE_PLOUF", "REVERSE_OBJECT",
    "KILLED_SORCERER", "LIGHT_OBJECT", "FOG_FLAG", "DEAD_PERSO",
)


@dataclass
class RealValue:
    start_value: int = 0
    end_value: int = 0
    num_steps: int = 0
    memo_ticks: int = 0


@dataclass
class Actor:
    index_in_world: int = -1
    body_num: int = 0
    object_type: int = 0
    dyn_flags: int = 0
    zv: list = field(default_factory=lambda: [0, 0, 0, 0, 0, 0])
    room_x: int = 0
    room_y: int = 0
    room_z: int = 0
    world_x: int = 0
    world_y: int = 0
    world_z: int = 0
    alpha: int = 0
    beta: int = 0
    gamma: int = 0
    chrono: int = 0
    room_chrono: int = 0
    anim: int = -1
    anim_type: int = 0
    anim_info: int = 0
    new_anim: int = -1
    new_anim_type: int = 0
    new_anim_info: int = 0
    frame: int = 0
    num_of_frames: int = 0
    end_frame: int = 0
    flag_end_anim: int = 0
    track_mode: int = 0
    track_number: int = 0
    mark: int = -1
    position_in_track: int = 0
    step_x: int = 0
    step_y: int = 0
    step_z: int = 0
    y_handler: RealValue = field(default_factory=RealValue)
    falling: int = 0
    rotate: RealValue = field(default_factory=RealValue)
    direction: int = 0
    speed: int = 0
    col: list = field(default_factory=lambda: [-1, -1, -1])
    col_by: int = -1
    hard_dec: int = -1
    hard_col: int = -1
    hit: int = -1
    hit_by: int = -1
    anim_action_type: int = 0
    anim_action_anim: int = -1
    anim_action_frame: int = 0
    anim_action_param: int = 0
    hit_force: int = 0
    hot_point_id: int = -1
    hot_point: list = field(default_factory=lambda: [0, 0, 0])
    stage: int = 0
    room: int = 0
    life: int = -1
    life_mode: int = -1


class Game:
    def __init__(self, data_dir, hero=0):
        self.assets = Assets(data_dir)
        self.world_objects = parse_objets((data_dir / "OBJETS.ITD").read_bytes())
        self.actors = [Actor() for _ in range(NUM_MAX_OBJECT)]
        self.cvars = parse_defines((data_dir / "DEFINES.ITD").read_bytes())
        self.cvars[8] = hero  # CHOOSE_PERSO (startGame backs up and restores it)
        self.vars = parse_vars((data_dir / "VARS.ITD").read_bytes())
        self.timer = 0
        # input snapshot
        self.local_joyd = 0
        self.local_key = 0
        self.local_click = 0
        self.action = 0
        # world / camera state
        self.current_floor = 0
        self.current_room = 0
        self.current_stage = 0
        self.num_camera = -1
        self.new_num_camera = 0
        self.current_camera_target_actor = -1
        self.current_world_target = self.cvars[7]
        self.flag_change_etage = 0
        self.new_num_etage = 0
        self.flag_change_salle = 0
        self.new_num_salle = 0
        self.flag_init_view = 2
        self.flag_game_over = 0
        self.flag_genere_aff_list = 1
        # M3b/M4 stubs (audio, inventory)
        self.in_hand_table = [-1] * 256
        self.current_inventory = 0
        self.status_screen_allowed = 1
        self.current_music = -1
        self.next_music = -1
        self.light_off = 0
        self.last_sample = -1
        self.next_sample = -1
        self.last_priority = -1


def add_actor(game, world_idx):
    # InitObjet port (main.cpp ~1930-1985): copies tWorldObject -> tObject slot.
    # Returns the actor slot idx or -1. Sets: body_num, object_type (flags & ~AF_SPECIAL),
    # room/world coords (room offsets x10 per M1), zv = body.zv + (x, y, z) (M2 actor_zv),
    # stage, room, alpha/beta/gamma, anim, frame, anim_type, anim_info, dyn_flags from flags,
    # life, life_mode, track_mode/track_number/position_in_track.
    ...


def spawn_stage_actors(game):
    # GenereActiveList port (main.cpp:1990-2130). Phase 1: DeleteObjet for actors out of
    # scope (life/lifeMode/room gates per Interfaces; DeleteObjet resets the actor slot to
    # defaults, sets world obj.obj_index=-1, clears foundFlag bits). Phase 2: for each world
    # obj with obj_index == -1 passing the spawn gates, obj_index = add_actor(...); if it is
    # current_world_target, current_camera_target_actor = actor idx.
    ...


def change_salle(game, room):
    # ChangeSalle port (M3a subset): current_room = room; num_camera = -1; flag_init_view = 2
    ...


def game_step_tick(game):
    game.timer += 1


def init_game(data_dir, hero=0):
    game = Game(data_dir, hero=hero)
    spawn_stage_actors(game)
    change_salle(game, 0)
    game.new_num_camera = 0
    game.flag_init_view = 2
    return game
```

Implementer notes:
- `add_actor` fills every actor field InitObjet touches; consult `main.cpp` InitObjet (lines ~1930-1985) and the task-9 M2 precedent (`actor_zv` in `maitd/actors.py`).
- `spawn_stage_actors` gates (main.cpp:2053-2086): skip if `obj_index != -1`; `stage != current_floor` skip; if `life != -1`: life_mode -1 skip, 0 pass, 1 pass iff `room == current_room`, 2 pass iff room in camera view list (M3a simplification: pass — attic boot needs room 0 only; `ponytail:` note the simplification), else (life == -1): pass (M3a: accept; FITD checks isInViewList).
- `Game` needs `data_dir` only in `__init__` (parsers + Assets); play-loop code holds its own `Floor` (M1).

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_game.py -q`
Expected: 3 passed. Then full suite: `.venv/bin/pytest -q` — expect 79 passed.

- [ ] **Step 5: Commit**

```bash
git add maitd/game.py tests/test_game.py
git commit -m "feat: game state, actor table, world init (FITD LoadWorld/GenereActiveList ports)"
```

---

### Task 4: RealValue and chrono math

**Files:**
- Create: `maitd/realvalue.py`
- Test: `tests/test_realvalue.py`

**Interfaces:**
- Consumes: `Game.timer` (game_step_tick).
- Produces:
  - `def init_real_value(start_value, end_value, time, real_value, timer)` — main.cpp:2277 port (sets start/end/num_steps/memo_ticks)
  - `def update_actor_rotation(rotate_ptr, timer) -> int` — main.cpp:2285 port (angle interpolation with 0x400 wrap, C truncating division `int(v / N)`)
  - `def start_chrono(chrono_slot, timer)` — FITD startChrono: `*chrono = timer`
  - `def eval_chrono(chrono_value, timer) -> int` — FITD evalChrono: `timer - *chrono`
  - `def give_distance_2d(x1, z1, x2, z2) -> int` — `int(math.sqrt((x1-x2)**2 + (z1-z2)**2))`

- [ ] **Step 1: Write failing tests** `tests/test_realvalue.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
from maitd.realvalue import (
    eval_chrono, give_distance_2d, init_real_value, start_chrono, update_actor_rotation,
)
from maitd.game import RealValue


def test_update_rotation_identity():
    rv = init_real_value(0x100, 0x100, 60, RealValue(), timer=0)
    assert update_actor_rotation(rv, timer=0) == 0x100


def test_update_rotation_linear():
    rv = init_real_value(0, 0x200, 4, RealValue(), timer=10)
    assert update_actor_rotation(rv, timer=12) == 0x100


def test_update_rotation_overshoot():
    rv = init_real_value(0, 0x200, 4, RealValue(), timer=10)
    assert update_actor_rotation(rv, timer=99) == 0x200
    assert rv.num_steps == 0


def test_update_rotation_wrap():
    # angleDif = 0x0C0 - 0x300 = -0x240 < -0x200 -> +0x400 wrap branch
    # (C check is inclusive: -0x200 goes through the normal branch, not here)
    rv = init_real_value(0x300, 0x0C0, 2, RealValue(), timer=0)
    assert update_actor_rotation(rv, timer=1) == 0x3E0


def test_chrono():
    from maitd.game import Actor
    actor = Actor()
    start_chrono(actor, "chrono", timer=10)
    assert eval_chrono(actor.chrono, timer=30) == 20


def test_distance():
    # Manhattan: |3| + |4| = 7 (FITD GiveDistance2D is not euclidean)
    assert give_distance_2d(0, 0, 3, 4) == 7
    assert give_distance_2d(0, 0, 0, 0) == 0
    assert give_distance_2d(0, 0, -3, 4) == 7
    assert give_distance_2d(80000, 0, 0, 80000) == 0x7D00  # saturation
    # (40000-style inputs cannot saturate: (s16) cast keeps them positive)
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/pytest tests/test_realvalue.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'maitd.realvalue'`.

- [ ] **Step 3: Implement** `maitd/realvalue.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
"""RealValue interpolation + chrono ports (FITD main.cpp:2277-2321, evalChrono)."""
import math


def init_real_value(start_value, end_value, time, real_value, timer):
    real_value.start_value = start_value
    real_value.end_value = end_value
    real_value.num_steps = time
    real_value.memo_ticks = timer
    return real_value


def update_actor_rotation(rotate_ptr, timer):
    if not rotate_ptr.num_steps:
        return rotate_ptr.end_value
    time_dif = timer - rotate_ptr.memo_ticks
    if time_dif > rotate_ptr.num_steps:
        rotate_ptr.num_steps = 0
        return rotate_ptr.end_value
    angle_dif = (rotate_ptr.end_value & 0x3FF) - (rotate_ptr.start_value & 0x3FF)
    if angle_dif <= 0x200:
        if angle_dif >= -0x200:
            angle = (rotate_ptr.end_value & 0x3FF) - (rotate_ptr.start_value & 0x3FF)
            return (rotate_ptr.start_value & 0x3FF) + int((angle * time_dif) / rotate_ptr.num_steps)
        else:
            angle = ((rotate_ptr.end_value & 0x3FF) + 0x400) - (rotate_ptr.start_value & 0x3FF)
            return (rotate_ptr.start_value & 0x3FF) + int((angle * time_dif) / rotate_ptr.num_steps)
    else:
        angle = (rotate_ptr.end_value & 0x3FF) - ((rotate_ptr.start_value & 0x3FF) + 0x400)
        return int((angle * time_dif) / rotate_ptr.num_steps) + (rotate_ptr.start_value & 0x3FF)


def start_chrono(actor, field, timer):
    # C startChrono(chronoPtr) mutates the pointee; Python: set the actor field
    setattr(actor, field, timer)


def eval_chrono(chrono_value, timer):
    return timer - chrono_value


def give_distance_2d(x1, z1, x2, z2):
    # FITD GiveDistance2D (main.cpp:2252): MANHATTAN with 0x7D00 saturation, not euclidean
    x1 -= x2
    if (x1 & 0xFFFF) > 0x7FFF:
        x1 = -(x1 & 0xFFFF)  # C: (s16)x1 < 0 -> negate truncated s16
    z1 -= z2
    if (z1 & 0xFFFF) > 0x7FFF:
        z1 = -(z1 & 0xFFFF)
    if x1 + z1 > 0xFFFF:
        return 0x7D00
    return x1 + z1
```

Note: callers pass the actor and field name — `start_chrono(actor, "chrono", game.timer)`, and read with `eval_chrono(actor.chrono, game.timer)`.

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_realvalue.py -q`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add maitd/realvalue.py tests/test_realvalue.py
git commit -m "feat: RealValue interpolation and chrono ports"
```

---

### Task 5: VM core — fetch loop and control flow

**Files:**
- Create: `maitd/life.py`
- Test: `tests/test_life_vm.py`

**Interfaces:**
- Consumes: `Game` (task 3), `Assets.life` (task 2), `RealValue` (task 4).
- Produces:
  - `class VM` — one processLife invocation: `.script: bytes`, `.pc: int` (byte offset), `.game: Game`, `.owner_idx: int` (life owner actor slot), `.cur_idx: int` (current actor slot, actor-switch aware), `.switch_val: int`, `.exit: bool = False`
  - `def read_s16(vm) -> int` — fetch raw s16 at pc, advance 2 (vars.cpp readNextArgument port)
  - `LIFETABLE: list[callable]` — 87 entries (opcode 0..86 → handler, index == enum value per life.h); handlers `(vm) -> None`. Dead opcodes 27 LM_CAMERA, 57 LM_STOP_BETA, 61 LM_DO_NORMAL_ZV, 69 LM_SPEED raise ValueError. Entries not yet implemented raise NotImplementedError until tasks 7-8 land. Opcode >= 87 raises ValueError (out of range).
  - `def process_life(game, actor_idx, life_num)` — life.cpp:453 port:
    - fetch script via `game.assets.life(life_num)`; owner = actor_idx; cur = actor_idx
    - loop: `op = read_s16(vm)`; if `op & 0x8000`: read world-obj idx arg; `world = game.world_objects[idx]`; if `world.obj_index != -1`: `vm.cur_idx = world.obj_index`, full dispatch; else: reduced dispatch (world-object ops only, see below); after the opcode, restore `vm.cur_idx = vm.owner_idx`. Else: full dispatch.
    - exit when `vm.exit` or handler sets it.
  - Control-flow + var handlers: LM_IF_EGAL/DIFFERENT/SUP_EGAL/SUP/INF_EGAL/INF (4-9), LM_GOTO (10), LM_RETURN (11), LM_END (12), LM_VAR (19), LM_INC (20), LM_DEC (21), LM_ADD (22), LM_SUB (23), LM_LIFE_MODE (24), LM_SWITCH (25), LM_CASE (26), LM_START_CHRONO (28), LM_MULTI_CASE (29) — exact jump math: condition true → `pc += 2` (skip jump word); false → `pc += jump * 2`. GOTO: `pc += off * 2`. RETURN/END: `vm.exit = True`. Var ops write `game.vars[idx]` per FITD life.cpp:2194-2237 (VAR: raw idx + eval_var; INC/DEC: raw idx; ADD/SUB: raw idx + eval_var). LM_START_CHRONO = `start_chrono(vm.actor, "chrono", vm.game.timer)`.
  - Reduced (not-in-floor) dispatch set — handlers operate on `game.world_objects[idx]` fields: LM_BODY (3, uses eval_var), LM_TYPE (40, `TYPE_MASK` on flags), LM_ANIM_ONCE (1), LM_ANIM_REPEAT (13), LM_ANIM_ALL_ONCE (2), LM_MOVE (15), LM_ANGLE (74), LM_STAGE (47), LM_TEST_COL (54), LM_LIFE (31), LM_LIFE_MODE (24), LM_FOUND_NAME (48), LM_FOUND_BODY (55), LM_FOUND_FLAG (49), LM_FOUND_WEIGHT (67), LM_START_CHRONO (28 — no-op). Everything else in the reduced path raises ValueError (FITD prints + assert).
  - `MAIN_LOOP_GATE` helper: `def life_gate(actor) -> bool` — `actor.life != -1 and actor.life_mode != -1`.

- [ ] **Step 1: Write failing tests** `tests/test_life_vm.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
import struct

import pytest

from maitd.game import Game, init_game
from maitd.life import process_life, read_s16, VM


def _script(*words):
    return struct.pack(f"<{len(words)}h", *words)


def _make_game(data_dir):
    game = init_game(data_dir, hero=0)
    return game


def test_goto_loop_exits(data_dir):
    # script: LM_GOTO -1 -> RET; trace of pc never used, just terminates
    game = _make_game(data_dir)
    actor = game.current_camera_target_actor
    game.actors[actor].life = 0
    game.assets = _FakeAssets(script=_script(10, -1, 11))
    process_life(game, actor, 0)


def test_conditionals(data_dir):
    # synthetic: evalVar literal forms only
    # IF_EGAL a==b -> skip jump (2-byte jump word), else jump
    game = init_game(data_dir, hero=0)
    game.assets = _FakeAssets(script=_script(
        4, -1, 7, -1, 7, 2,    # IF_EGAL 7==7, jump +2 (skipped)
        10, 1,                 # GOTO +1 (skips the END)
        12,                    # LM_END
        11,                    # LM_RETURN (target of the goto)
        12,
    ))
    game.actors[0].life = 0
    process_life(game, 0, 0)
    # reaching here without error = if-branch taken, goto executed, return hit
    assert True


def test_if_false_jumps(data_dir):
    game = init_game(data_dir, hero=0)
    game.assets = _FakeAssets(script=_script(
        4, -1, 7, -1, 6, 1,    # IF_EGAL 7==6 false -> jump +1 word: skips RET, hits END
        11,
        12,
    ))
    game.actors[0].life = 0
    process_life(game, 0, 0)


def test_return_and_end_equivalent(data_dir):
    game = init_game(data_dir, hero=0)
    game.assets = _FakeAssets(script=_script(11))
    game.actors[0].life = 0
    process_life(game, 0, 0)
    game.assets = _FakeAssets(script=_script(12))
    process_life(game, 0, 0)


def test_switch_case(data_dir):
    game = init_game(data_dir, hero=0)
    game.assets = _FakeAssets(script=_script(
        25, -1, 2,     # SWITCH evalVar -> 2
        26, 1, 1,      # CASE 1: no match, jump +1 word -> skips END, hits RET
        12,
        11,
    ))
    game.actors[0].life = 0
    process_life(game, 0, 0)


def test_actor_switch_flag(data_dir):
    game = init_game(data_dir, hero=0)
    # find a spawned actor (in floor -> full dispatch on the switched actor)
    spawned = next(i for i, a in enumerate(game.actors) if a.index_in_world != -1)
    world_idx = game.actors[spawned].index_in_world
    game.assets = _FakeAssets(script=_script(
        0x8000 | 11, world_idx,   # LM_RETURN with switch flag: dispatch on switched actor
    ))
    game.actors[spawned].life = 0
    process_life(game, spawned, 0)


def test_unknown_opcode_raises(data_dir):
    game = init_game(data_dir, hero=0)
    game.assets = _FakeAssets(script=_script(90))
    game.actors[0].life = 0
    with pytest.raises(ValueError):
        process_life(game, 0, 0)


def test_dead_opcode_raises(data_dir):
    game = init_game(data_dir, hero=0)
    game.assets = _FakeAssets(script=_script(69))  # LM_SPEED: no dispatch case in FITD
    game.actors[0].life = 0
    with pytest.raises(ValueError):
        process_life(game, 0, 0)


class _FakeAssets:
    def __init__(self, script):
        self._script = script

    def life(self, index):
        return self._script

    def track(self, index):
        return b""
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/pytest tests/test_life_vm.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'maitd.life'`.

- [ ] **Step 3: Implement** `maitd/life.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
"""LIFE script VM — faithful port of FITD life.cpp processLife (AITD1)."""
import struct


class VM:
    __slots__ = ("script", "pc", "game", "owner_idx", "cur_idx", "switch_val", "exit")

    def __init__(self, script, game, owner_idx):
        self.script = script
        self.pc = 0
        self.game = game
        self.owner_idx = owner_idx
        self.cur_idx = owner_idx
        self.switch_val = 0
        self.exit = False

    @property
    def actor(self):
        return self.game.actors[self.cur_idx]

    @property
    def owner(self):
        return self.game.actors[self.owner_idx]


def read_s16(vm):
    value = struct.unpack_from("<h", vm.script, vm.pc)[0]
    vm.pc += 2
    return value


def _op_end(vm):
    vm.exit = True


def _op_goto(vm):
    offset = read_s16(vm)
    vm.pc += offset * 2


def _make_if(op):  # condition functions over (a, b)
    def handler(vm):
        a = eval_var(vm)
        b = eval_var(vm)
        jump = read_s16(vm)
        if not op(a, b):
            vm.pc += jump * 2
    return handler


def _op_switch(vm):
    vm.switch_val = eval_var(vm)


def _op_case(vm):
    case = read_s16(vm)
    jump = read_s16(vm)
    if case != vm.switch_val:
        vm.pc += jump * 2


def _op_multi_case(vm):
    count = read_s16(vm)
    values = [read_s16(vm) for _ in range(count)]
    jump = read_s16(vm)
    if vm.switch_val not in values:
        vm.pc += jump * 2


# Dead in AITD1: LM_STOP_BETA(58), LM_DO_NORMAL_ZV(62), LM_SPEED(70) — assert in FITD.
# (LM_CAMERA is not part of the AITD1 88-entry table.)
def _op_dead(vm):
    raise ValueError(
        f"dead opcode {struct.unpack_from('<h', vm.script, vm.pc - 2)[0] & 0x7FFF} "
        f"in life of actor {vm.owner_idx} at byte {vm.pc - 2} (FITD asserts here)"
    )


def _op_var(vm):
    idx = read_s16(vm)
    vm.game.vars[idx] = eval_var(vm)


def _make_var_op(fn):
    def handler(vm):
        idx = read_s16(vm)
        vm.game.vars[idx] = fn(vm.game.vars[idx])
    return handler


def _op_add(vm):
    idx = read_s16(vm)
    vm.game.vars[idx] += eval_var(vm)


def _op_sub(vm):
    idx = read_s16(vm)
    vm.game.vars[idx] -= eval_var(vm)


def _op_life_mode(vm):
    vm.actor.life_mode = read_s16(vm)


def _op_start_chrono(vm):
    from maitd.realvalue import start_chrono
    start_chrono(vm.actor, "chrono", vm.game.timer)


def _op_not_implemented(name):
    def handler(vm):
        raise NotImplementedError(f"opcode {name} not implemented yet")
    return handler


# Reduced dispatch (world object not in floor, life.cpp:693-712): allowed set only.
_REDUCED_ALLOWED = {1, 2, 3, 13, 15, 24, 28, 31, 40, 47, 48, 49, 54, 55, 67, 74}


def process_life(game, actor_idx, life_num):
    vm = VM(game.assets.life(life_num), game, actor_idx)
    while not vm.exit:
        op = read_s16(vm)
        if op & 0x8000:
            world_idx = read_s16(vm)
            world = game.world_objects[world_idx]
            if world.obj_index != -1:
                vm.cur_idx = world.obj_index
                _dispatch(vm, op)
            else:
                if (op & 0x7FFF) not in _REDUCED_ALLOWED:
                    raise ValueError(
                        f"opcode {op & 0x7FFF} not allowed on out-of-floor object "
                        f"{world_idx} (life of actor {vm.owner_idx}, byte {vm.pc - 4})"
                    )
                _dispatch_reduced(vm, op, world_idx)
            vm.cur_idx = vm.owner_idx
        else:
            _dispatch(vm, op)


def _dispatch(vm, op):
    index = op & 0x7FFF
    if index >= len(LIFETABLE):
        raise ValueError(f"opcode {index} out of range (life of actor {vm.owner_idx}, byte {vm.pc - 2})")
    LIFETABLE[index](vm)


def _dispatch_reduced(vm, op, world_idx):
    # world-object-field ops on game.world_objects[world_idx]; implemented in task 7.
    from maitd.life_reduced import reduced_dispatch  # noqa: F401  (task 7 fills this in)
    reduced_dispatch(vm, op & 0x7FFF, world_idx)


def life_gate(actor):
    return actor.life != -1 and actor.life_mode != -1


# eval_var imported lazily to avoid a cycle (task 6); handlers need it:
def eval_var(vm):
    from maitd.eval_var import eval_var as _eval
    return _eval(vm)


LIFETABLE = [_op_not_implemented("")] * 87
LIFETABLE[4] = _make_if(lambda a, b: a == b)   # LM_IF_EGAL
LIFETABLE[5] = _make_if(lambda a, b: a != b)   # LM_IF_DIFFERENT
LIFETABLE[6] = _make_if(lambda a, b: a >= b)   # LM_IF_SUP_EGAL
LIFETABLE[7] = _make_if(lambda a, b: a > b)    # LM_IF_SUP
LIFETABLE[8] = _make_if(lambda a, b: a <= b)   # LM_IF_INF_EGAL
LIFETABLE[9] = _make_if(lambda a, b: a < b)    # LM_IF_INF
LIFETABLE[10] = _op_goto                       # LM_GOTO
LIFETABLE[11] = _op_end                        # LM_RETURN
LIFETABLE[12] = _op_end                        # LM_END
LIFETABLE[19] = _op_var                        # LM_VAR
LIFETABLE[20] = _make_var_op(lambda v: v + 1)  # LM_INC
LIFETABLE[21] = _make_var_op(lambda v: v - 1)  # LM_DEC
LIFETABLE[22] = _op_add                        # LM_ADD
LIFETABLE[23] = _op_sub                        # LM_SUB
LIFETABLE[24] = _op_life_mode                  # LM_LIFE_MODE
LIFETABLE[25] = _op_switch                     # LM_SWITCH
LIFETABLE[26] = _op_case                       # LM_CASE
LIFETABLE[27] = _op_dead                       # LM_CAMERA
LIFETABLE[28] = _op_start_chrono               # LM_START_CHRONO
LIFETABLE[29] = _op_multi_case                 # LM_MULTI_CASE
LIFETABLE[57] = _op_dead                       # LM_STOP_BETA
LIFETABLE[61] = _op_dead                       # LM_DO_NORMAL_ZV
LIFETABLE[69] = _op_dead                       # LM_SPEED
```

Note: `eval_var` lives in its own module (task 6) so `life.py` imports it lazily; `life_reduced.py` is filled by task 7. Both land before any real script runs.

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_life_vm.py -q`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add maitd/life.py tests/test_life_vm.py
git commit -m "feat: LIFE VM core — fetch loop, actor switch, control flow"
```

---

### Task 6: evalVar port

**Files:**
- Create: `maitd/eval_var.py`
- Test: `tests/test_eval_var.py`

**Interfaces:**
- Consumes: `VM`, `read_s16` (task 5), `Game` (task 3), `RealValue`/chronos (task 4).
- Produces:
  - `def eval_var(vm) -> int` — evalVar.cpp:148 AITD1 port. Owner = `vm.owner` (NOT `vm.actor` — FITD reads the life owner). Encodings:
    - tag -1: next s16 literal
    - tag 0: `game.vars[<next s16>]`
    - tag 0x8000+: other object — next s16 = world idx; actor = `game.actors[world.obj_index]` if in floor else None; prop code = `(tag & 0x7FFF) - 1`; if not in floor: only 0x1F → `world.room`, 0x26 → `world.stage`, else ValueError
    - else: prop code = `tag - 1`
  - Property table (codes 0x00-0x26; owner actor `a`, game `g`):

| code | value | extra payload |
|---|---|---|
| 0x00 | `game.actors[a.col[0]].index_in_world` if `a.col[0] != -1` else -1 (FITD maps actor slot → world index) | — |
| 0x01 | `a.hard_dec` | — |
| 0x02 | `a.hard_col` | — |
| 0x03 | `game.actors[a.hit].index_in_world` if `a.hit != -1` else -1 | — |
| 0x04 | `game.actors[a.hit_by].index_in_world` if `a.hit_by != -1` else -1 (verify case 0x4 against evalVar.cpp:258-268) | — |
| 0x05 | `a.anim` | — |
| 0x06 | `a.flag_end_anim` | — |
| 0x07 | `a.frame` | — |
| 0x08 | `a.end_frame` | — |
| 0x09 | `a.body_num` | — |
| 0x0A | `a.mark` | — |
| 0x0B | `a.track_number` | — |
| 0x0C | `eval_chrono(a.chrono, g.timer) // 60` (C: `evalChrono(...)/60`, trunc) | — |
| 0x0D | `eval_chrono(a.room_chrono, g.timer) // 60` | — |
| 0x0E | FITD `calcDist` — 3D Manhattan over worldX/worldY/worldZ: `abs(a.world_x - t.world_x) + abs(a.world_y - t.world_y) + abs(a.world_z - t.world_z)` (evalVar.cpp:97-104), 32000 if not in floor | +1 s16 world idx |
| 0x0F | `game.actors[a.col_by].index_in_world` if `a.col_by != -1` else -1 | — |
| 0x10 | `1 if g.world_objects[widx].found_flag & 0x8000 else 0` | +1 nested eval_var → world idx |
| 0x11 | `g.action` | — |
| 0x12 | FITD `getPosRel` (evalVar.cpp:22-95): beta-quadrant counter (3/2/1/0), other actor's zv copied, AdjustZV when rooms differ, center tests on ZVZ/ZVX, lookup `getPosRelTable = {4,1,8,2,4,1,8,0}` | +1 s16 world idx |
| 0x13 | `g.local_joyd` → first set of 4/8/1/2 else 0 | — |
| 0x14 | `g.local_click` | — |
| 0x15 | `game.actors[t].index_in_world` where t = `a.col[0]` if != -1 else `a.col_by`, else -1 | — |
| 0x16 | `a.alpha` | — |
| 0x17 | `a.beta` | — |
| 0x18 | `a.gamma` | — |
| 0x19 | `g.in_hand_table[g.current_inventory]` | — |
| 0x1A | `a.hit_force` | — |
| 0x1B | camera value — M1/M2 camera table: read u16 at `camera_base + (g.num_camera + 6) * 2` (FITD expression verbatim; implementer maps to the M2 parsed room-camera struct, field order alpha/beta/gamma/x/y/z/focal1/focal2/focal3 — slot 6 = focal1 of camera g.num_camera) | — |
| 0x1C | `random.randrange(n)` (FITD `rand() % n`) | +1 s16 n |
| 0x1D | `a.falling` | — |
| 0x1E | `a.room` | — |
| 0x1F | `a.life` | — |
| 0x20 | `1 if w.found_flag & 0xC000 else 0` | +1 s16 world idx |
| 0x21 | `a.room_y` | — |
| 0x22 | TEST_ZV_END_ANIM: M3a stub — consume 2 s16, return 0 (combat/test walk sim, M3c) | +2 s16 (anim, param) |
| 0x23 | `g.current_music` | — |
| 0x24 | `g.cvars[<raw s16>]` | +1 s16 |
| 0x25 | `a.stage` | — |
| 0x26 | `1 if w.found_flag & 0x1000 else 0` | +1 s16 world idx |
| other | ValueError (FITD printf + assert) | — |

- [ ] **Step 1: Write failing tests** `tests/test_eval_var.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
import struct

import pytest

from maitd.eval_var import eval_var
from maitd.game import init_game
from maitd.life import VM


def _vm(game, *words):
    script = struct.pack(f"<{len(words)}h", *words)
    return VM(script, game, game.current_camera_target_actor)


def test_literal(data_dir):
    game = init_game(data_dir, hero=0)
    vm = _vm(game, -1, 1234)
    assert eval_var(vm) == 1234


def test_script_var(data_dir):
    game = init_game(data_dir, hero=0)
    game.vars[3] = 77
    vm = _vm(game, 0, 3)
    assert eval_var(vm) == 77


def test_actor_property(data_dir):
    game = init_game(data_dir, hero=0)
    owner = game.current_camera_target_actor
    game.actors[owner].beta = 0x2A0
    vm = _vm(game, 0x17 + 1)  # tag = code+1, beta
    assert eval_var(vm) == 0x2A0


def test_other_object_property(data_dir):
    game = init_game(data_dir, hero=0)
    spawned = next(i for i, a in enumerate(game.actors) if a.index_in_world != -1)
    widx = game.actors[spawned].index_in_world
    game.actors[spawned].life = 42
    vm = _vm(game, 0x8000 | (0x1F + 1), widx)  # life of other object
    assert eval_var(vm) == 42


def test_other_object_not_in_floor(data_dir):
    game = init_game(data_dir, hero=0)
    widx = next(i for i, w in enumerate(game.world_objects) if w.obj_index == -1)
    game.world_objects[widx].room = 3
    vm = _vm(game, 0x8000 | (0x1F + 1), widx)  # room allowed when not in floor
    assert eval_var(vm) == 3
    game.world_objects[widx].stage = 1
    vm = _vm(game, 0x8000 | (0x26 + 1), widx)  # stage allowed when not in floor
    assert eval_var(vm) == 1


def test_nested_eval_var_found_flag(data_dir):
    game = init_game(data_dir, hero=0)
    widx = next(i for i, w in enumerate(game.world_objects) if w.found_flag & 0x8000 == 0)
    game.world_objects[widx].found_flag |= 0x8000
    vm = _vm(game, 0x10 + 1, -1, widx)  # found test: +1 nested evalVar (literal widx)
    assert eval_var(vm) == 1


def test_cvar_index(data_dir):
    game = init_game(data_dir, hero=0)
    vm = _vm(game, 0x24 + 1, 2)  # CVars[2] = MAX_WEIGHT_LOADABLE = 700
    assert eval_var(vm) == 700


def test_rand_range(data_dir):
    game = init_game(data_dir, hero=0)
    vm = _vm(game, 0x1C + 1, 5)
    assert 0 <= eval_var(vm) < 5


def test_unknown_code_raises(data_dir):
    game = init_game(data_dir, hero=0)
    vm = _vm(game, 0x27 + 1)
    with pytest.raises(ValueError):
        eval_var(vm)
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/pytest tests/test_eval_var.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'maitd.eval_var'`.

- [ ] **Step 3: Implement** `maitd/eval_var.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
"""evalVar port (FITD evalVar.cpp:148, AITD1 path). Owner = life owner actor."""
import random

from maitd.life import read_s16
from maitd.realvalue import eval_chrono


def _prop(game, a, code, vm):
    if code == 0x00:
        return _world_idx(game, a.col[0])
    if code == 0x01:
        return a.hard_dec
    if code == 0x02:
        return a.hard_col
    if code == 0x03:
        return _world_idx(game, a.hit)
    if code == 0x04:
        return _world_idx(game, a.hit_by)
    if code == 0x05:
        return a.anim
    if code == 0x06:
        return a.flag_end_anim
    if code == 0x07:
        return a.frame
    if code == 0x08:
        return a.end_frame
    if code == 0x09:
        return a.body_num
    if code == 0x0A:
        return a.mark
    if code == 0x0B:
        return a.track_number
    if code == 0x0C:
        return int(eval_chrono(a.chrono, game.timer) / 60)
    if code == 0x0D:
        return int(eval_chrono(a.room_chrono, game.timer) / 60)
    if code == 0x0E:
        widx = read_s16(vm)
        w = game.world_objects[widx]
        if w.obj_index == -1:
            return 32000
        b = game.actors[w.obj_index]
        return calc_dist(a.world_x, a.world_y, a.world_z, b.world_x, b.world_y, b.world_z)
    if code == 0x0F:
        return _world_idx(game, a.col_by)
    if code == 0x10:
        widx = eval_var(vm)  # nested!
        return 1 if game.world_objects[widx].found_flag & 0x8000 else 0
    if code == 0x11:
        return game.action
    if code == 0x12:
        widx = read_s16(vm)
        w = game.world_objects[widx]
        if w.obj_index == -1:
            return 0
        return get_pos_rel(game, a, game.actors[w.obj_index])
    if code == 0x13:
        j = game.local_joyd
        if j & 4:
            return 4
        if j & 8:
            return 8
        if j & 1:
            return 1
        if j & 2:
            return 2
        return 0
    if code == 0x14:
        return game.local_click
    if code == 0x15:
        t = a.col[0] if a.col[0] != -1 else a.col_by
        return _world_idx(game, t) if t != -1 else -1
    if code == 0x16:
        return a.alpha
    if code == 0x17:
        return a.beta
    if code == 0x18:
        return a.gamma
    if code == 0x19:
        return game.in_hand_table[game.current_inventory]
    if code == 0x1A:
        return a.hit_force
    if code == 0x1B:
        return game.camera_param(game.num_camera)  # see note
    if code == 0x1C:
        n = read_s16(vm)
        return random.randrange(n)
    if code == 0x1D:
        return a.falling
    if code == 0x1E:
        return a.room
    if code == 0x1F:
        return a.life
    if code == 0x20:
        widx = read_s16(vm)
        return 1 if game.world_objects[widx].found_flag & 0xC000 else 0
    if code == 0x21:
        return a.room_y
    if code == 0x22:
        read_s16(vm)
        read_s16(vm)
        return 0  # M3a stub: TEST_ZV_END_ANIM (M3c)
    if code == 0x23:
        return game.current_music
    if code == 0x24:
        return game.cvars[read_s16(vm)]
    if code == 0x25:
        return a.stage
    if code == 0x26:
        widx = read_s16(vm)
        return 1 if game.world_objects[widx].found_flag & 0x1000 else 0
    raise ValueError(f"evalVar: unknown property code {code} (FITD asserts here)")


def _world_idx(game, slot):
    return -1 if slot == -1 else game.actors[slot].index_in_world


def calc_dist(x1, y1, z1, x2, y2, z2):
    return abs(x1 - x2) + abs(y1 - y2) + abs(z1 - z2)


_GET_POS_REL_TABLE = (4, 1, 8, 2, 4, 1, 8, 0)


def get_pos_rel(game, actor1, actor2):
    # FITD evalVar.cpp:22-95 port
    beta1 = actor1.beta
    counter = 3
    if 0x80 <= beta1 < 0x180:
        counter = 2
    if 0x180 <= beta1 < 0x280:
        counter = 1
    if 0x280 <= beta1 < 0x380:
        counter = 0
    zv = list(actor2.zv)
    if actor1.room != actor2.room:
        _adjust_zv(game, zv, actor2.room, actor1.room)  # room world-offset adjust
    center_x = int((zv[0] + zv[1]) / 2)
    center_z = int((zv[4] + zv[5]) / 2)
    if actor1.zv[5] >= center_z and actor1.zv[4] <= center_z:
        if actor1.zv[1] < center_x:
            counter += 1
        else:
            if actor1.zv[0] <= center_x:
                return 0
            counter += 3
    else:
        if actor1.zv[1] >= center_x or actor1.zv[0] <= center_x:
            if actor1.zv[5] < center_z:
                counter += 2
            else:
                if actor1.zv[4] <= center_z:
                    return 0
        else:
            return 0
    return _GET_POS_REL_TABLE[counter]


def _adjust_zv(game, zv, from_room, to_room):
    # FITD AdjustZV: shift by (room world-coord delta) * 10 (M1 room offsets)
    ...


def eval_var(vm):
    tag = read_s16(vm)
    game = vm.game
    if tag == -1:
        return read_s16(vm)
    if tag == 0:
        return game.vars[read_s16(vm)]
    if tag & 0x8000:
        widx = read_s16(vm)
        w = game.world_objects[widx]
        code = (tag & 0x7FFF) - 1
        if w.obj_index != -1:
            return _prop(game, game.actors[w.obj_index], code, vm)
        if code == 0x1F:
            return w.room
        if code == 0x26:
            return w.stage
        raise ValueError(f"evalVar: code {code} on out-of-floor object {widx}")
    return _prop(game, vm.owner, tag - 1, vm)
```

Note: `game.camera_param` — add to `Game` in task 8 (needs the M2 room camera table): returns `camera.focal1` of camera slot `num_camera` (M2 `Camera` field order matches FITD's `(NumCamera+6)*2` read only if the parsed table is per-slot; implementer verifies against FITD `cameraPtr` and pins it with a real-data test in task 8).

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_eval_var.py -q`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add maitd/eval_var.py tests/test_eval_var.py
git commit -m "feat: evalVar encodings port (AITD1)"
```

---

### Task 7: Track runner

**Files:**
- Create: `maitd/tracks.py`
- Test: `tests/test_tracks.py`

**Interfaces:**
- Consumes: `Game`/`Actor` (task 3), `RealValue` + `give_distance_2d` (task 4), `rotate_step` (M2), `Assets.track` (task 2).
- Produces:
  - `def init_deplacement(actor, mode, number)` — track.cpp InitDeplacement port (mode 2: track_number=number, mark=-1; mode 3: track_number=number, position_in_track=0, mark=-1; mode 1/0: track_mode only)
  - `def cap_objet(x1, z1, beta, x2, z2) -> int` — track.cpp:68 port (+ `compute_angle_modificator_to_position_sub1` with global angleCompX/Z per FITD — port as module state or explicit args; prefer explicit args)
  - `def gere_manual_rot(actor, param, joyd, timer)` — track.cpp:90 port (left/right rotation via RealValue, direction reset)
  - `def process_track(game, actor)` — track.cpp:184 port:
    - mode 1 (manual): GereManualRot(60); joyd&1 forward speed accel (5 if rapid re-press within 10 ticks, else 4) / decel; joyd&2 backward (-1)
    - mode 2 (follow): follow target world obj (track_number); if target not in floor → speed 0, direction 0; else AITD1 room-link retarget (`get_room_link` zone type-4 port from M1 room zone data), `CapObjet`, rotate via RealValue(60), speed 4
    - mode 3 (track): read `track_number` entry; macro at `position_in_track`; switch over TL_*:
      - TL_INIT_COOR (0): warp — room change → flag_change_salle if camera target; zv -= old pos; set room/world x,y,z (+ room world-offset adjust); zv += new pos; speed 0, direction 0, rotate reset; `position_in_track += 5`
      - TL_GOTO (1): room + x + z (y=0); room-diff world adjust; distance >= 400 → CapObjet rotate (RealValue 15 ticks, angleModif*64), else `position_in_track += 4`
      - TL_GOTO_3D (15): room, x, y, z, time; reached (y match + dist < 400) → `+= 6`; else YHandler init to y-delta over time, rotate toward target
      - TL_END (2): speed 0, track_number=-1, `init_deplacement(0, 0)`
      - TL_REPEAT (3): `position_in_track = 0`
      - TL_MARK (4): `mark = raw`; `+= 2`
      - TL_WALK (5): speed 4, `+= 1`
      - TL_RUN (6): speed 5, `+= 1`
      - TL_STOP (7): AITD1: speed 0, `+= 1`
      - TL_SET_ANGLE (9): beta rotate toward raw via RealValue(120); direction by wrap compare; on arrival `+= 2`
      - TL_COL_OFF (10) / TL_COL_ON (11): `dyn_flags &= ~1` / `|= 1`; `+= 1`
      - TL_DEC_OFF (13) / TL_DEC_ON (14): `object_type &= ~AF_TRIGGER` / `|= AF_TRIGGER`; `+= 1`
      - TL_MEMO_COOR (16): world obj x/y/z = room + step; `+= 1`
      - TL_GOTO_3DX (17) / TL_GOTO_3DZ (18): stairs walk (makeProportional Y interpolation, CapObjet rotate; arrival `+= 4`)
      - TL_ANGLE (19): 3 raw → alpha/beta/gamma; direction 0; `+= 4`
      - TL_BACK (8), TL_CLOSE (20): no case in FITD → raise ValueError
    - final: `actor.beta &= 0x3FF`
  - `def get_room_link(game, room1, room2)` — zone type-4 link search port (room zone table from M1 parsed room data)

- [ ] **Step 1: Write failing tests** `tests/test_tracks.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
import struct

from maitd.game import Actor, Game, init_game
from maitd.tracks import init_deplacement, process_track


def _actor():
    return Actor(index_in_world=0, room=0, room_x=0, room_y=0, room_z=0, life=0, life_mode=1)


def test_init_deplacement_track_mode(data_dir):
    game = init_game(data_dir, hero=0)
    a = _actor()
    init_deplacement(a, 3, 7)
    assert (a.track_mode, a.track_number, a.position_in_track, a.mark) == (3, 7, 0, -1)


def test_track_end_stops(data_dir):
    game = init_game(data_dir, hero=0)
    a = _actor()
    init_deplacement(a, 3, 0)
    a.speed = 4
    game.assets = _FakeAssets(track=struct.pack("<h", 2))  # TL_END
    process_track(game, a)
    assert a.speed == 0
    assert a.track_number == -1
    assert a.track_mode == 0


def test_track_walk_and_repeat(data_dir):
    game = init_game(data_dir, hero=0)
    a = _actor()
    init_deplacement(a, 3, 0)
    game.assets = _FakeAssets(track=struct.pack("<hh", 5, 3))  # TL_WALK, TL_REPEAT
    process_track(game, a)
    assert a.speed == 4
    assert a.position_in_track == 1
    process_track(game, a)
    assert a.position_in_track == 0


def test_track_init_coor_warps(data_dir):
    game = init_game(data_dir, hero=0)
    a = _actor()
    init_deplacement(a, 3, 0)
    game.assets = _FakeAssets(track=struct.pack("<hhhhh", 0, 0, 100, 50, 200))
    process_track(game, a)
    assert (a.room_x, a.room_y, a.room_z) == (100, 50, 200)
    assert a.position_in_track == 5
    assert a.speed == 0


def test_track_manual_forward(data_dir):
    game = init_game(data_dir, hero=0)
    a = _actor()
    init_deplacement(a, 1, 0)
    game.local_joyd = 1
    game.assets = _FakeAssets(track=b"")
    process_track(game, a)
    assert a.speed == 4
    game.local_joyd = 0
    process_track(game, a)
    assert a.speed == 3


class _FakeAssets:
    def __init__(self, track=b""):
        self._track = track

    def life(self, index):
        return b""

    def track(self, index):
        return self._track
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/pytest tests/test_tracks.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'maitd.tracks'`.

- [ ] **Step 3: Implement** `maitd/tracks.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Track runner port (FITD track.cpp processTrack, AITD1 macro set)."""
import struct

from maitd.realvalue import give_distance_2d, init_real_value, update_actor_rotation
from maitd.world import rotate_step

TL_INIT_COOR, TL_GOTO, TL_END, TL_REPEAT, TL_MARK = 0, 1, 2, 3, 4
TL_WALK, TL_RUN, TL_STOP, TL_BACK, TL_SET_ANGLE = 5, 6, 7, 8, 9
TL_COL_OFF, TL_COL_ON, TL_SET_DIST, TL_DEC_OFF, TL_DEC_ON = 10, 11, 12, 13, 14
TL_GOTO_3D, TL_MEMO_COOR, TL_GOTO_3DX, TL_GOTO_3DZ, TL_ANGLE, TL_CLOSE = 15, 16, 17, 18, 19, 20

DISTANCE_TO_POINT_TRESSHOLD = 400  # [sic] FITD spelling kept


def _read_s16(buf, off):
    return struct.unpack_from("<h", buf, off)[0]


def _rotate(x, z, beta):
    # Rotate port via M2 rotate_step (x_out, z_out)
    return rotate_step(beta, x, z)


def init_deplacement(actor, mode, number):
    actor.track_mode = mode
    if mode == 2:
        actor.track_number = number
        actor.mark = -1
    elif mode == 3:
        actor.track_number = number
        actor.position_in_track = 0
        actor.mark = -1


def compute_angle_modificator_to_position_sub1(ax, angle_comp_x, angle_comp_z):
    x_out, z_out = _rotate(0, 1000, ax)
    z_out *= angle_comp_z
    x_out *= angle_comp_x
    z_out -= x_out
    if z_out == 0:
        return 0
    return 1 if z_out > 0 else -1


def cap_objet(x1, z1, beta, x2, z2):
    angle_comp_x = x2 - x1
    angle_comp_z = z2 - z1
    result_min = compute_angle_modificator_to_position_sub1(beta - 4, angle_comp_x, angle_comp_z)
    result_max = compute_angle_modificator_to_position_sub1(beta + 4, angle_comp_x, angle_comp_z)
    if result_max == -1 and result_min == 1:
        return compute_angle_modificator_to_position_sub1(beta, angle_comp_x, angle_comp_z)
    return int((result_max + result_min + 1) / 2)


def gere_manual_rot(actor, param, joyd, timer):
    if joyd & 4:
        if actor.direction != 1:
            actor.rotate.num_steps = 0
        actor.direction = 1
        if actor.rotate.num_steps == 0:
            old_beta = actor.beta
            if actor.speed == 0:
                init_real_value(old_beta, old_beta + 0x100, int(param / 2), actor.rotate, timer)
            else:
                init_real_value(old_beta, old_beta + 0x100, param, actor.rotate, timer)
        actor.beta = update_actor_rotation(actor.rotate, timer)
    if joyd & 8:
        if actor.direction != -1:
            actor.rotate.num_steps = 0
        actor.direction = -1
        if actor.rotate.num_steps == 0:
            old_beta = actor.beta
            if actor.speed == 0:
                init_real_value(old_beta, old_beta - 0x100, int(param / 2), actor.rotate, timer)
            else:
                init_real_value(old_beta, old_beta - 0x100, param, actor.rotate, timer)
        actor.beta = update_actor_rotation(actor.rotate, timer)
    if not (joyd & 0xC):
        actor.direction = 0
        actor.rotate.num_steps = 0


def _process_track_manual(game, actor):
    joyd = game.local_joyd
    gere_manual_rot(actor, 60, joyd, game.timer)
    if joyd & 1:
        if game.timer - game._last_time_forward < 10 and actor.speed != 4:
            actor.speed = 5
        else:
            if actor.speed == 0 or actor.speed == -1:
                actor.speed = 4
        game._last_time_forward = game.timer
    else:
        if 0 < actor.speed <= 4:
            actor.speed -= 1
        else:
            actor.speed = 0
    if joyd & 2:
        if actor.speed == 0 or actor.speed >= 4:
            actor.speed = -1
        if actor.speed == 5:
            actor.speed = 0


def process_track(game, actor):
    if actor.track_mode == 1:
        _process_track_manual(game, actor)
    elif actor.track_mode == 2:
        _process_track_follow(game, actor)
    elif actor.track_mode == 3:
        _process_track_scripted(game, actor)
    actor.beta &= 0x3FF


# _process_track_follow / _process_track_scripted / get_room_link: implement per
# Interfaces table and FITD track.cpp:234-757, translating C locals to locals,
# `rotate_step` for Rotate(), `update_actor_rotation` for RealValue evaluation.
```

Implementer notes:
- `Game` needs `_last_time_forward` (init 0) — the FITD `lastTimeForward` static.
- `_process_track_scripted` macro dispatch mirrors FITD's switch exactly; `TL_SET_DIST` (12) and `TL_BACK` (8) have no case in FITD's switch — `TL_SET_DIST` is defined but uncased (falls to default assert) — treat identically (raise ValueError).
- Follow mode's room-link retarget uses M1 room zone parsing (`Zone` dataclass, zone type 4 = room link); implement `get_room_link(game, room1, room2)` reading the room's zone table from the already-parsed M1 room data.
- `process_track` is called by LM_DO_MOVE with `vm.actor`; it also runs for ALL actors each tick in the play loop when `track_mode` != 0 (FITD: GereAnim → anim move; M2 already applies anim steps; task 11 wires speed → step).

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_tracks.py -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add maitd/tracks.py maitd/game.py tests/test_tracks.py
git commit -m "feat: track runner (manual/follow/scripted modes, TL_* macros)"
```

---

### Task 8: Movement, state, and world-opcode handlers

**Files:**
- Create: `maitd/life_ops.py` (full-dispatch handlers) and `maitd/life_reduced.py` (not-in-floor dispatch)
- Modify: `maitd/life.py` (wire `LIFETABLE[op] = ...` for implemented opcodes)
- Modify: `maitd/game.py` (add `camera_param`, `hard_clip` state)
- Test: `tests/test_life_ops.py`

**Interfaces:**
- Consumes: tasks 3-6, `maitd.tracks` (task 7 — process_track is called by LM_DO_MOVE; wiring import is lazy).
- Produces full-path handlers:
  - LM_DO_MOVE (0): `process_track(vm)` on `vm.actor`
  - LM_ANIM_ONCE (1) / LM_ANIM_ALL_ONCE (2) / LM_ANIM_REPEAT (13): M3a — consume args (1: anim, flags; 2: anim, flags; 13: anim), set `a.anim`/`a.new_anim=-2` per FITD InitAnim contract (anim==-1 → anim=-1, new_anim=-2), M2 AnimPlayer switch happens in the play loop (task 11). Log via trace.
  - LM_BODY (3): evalVar; set `a.body_num = v`, world obj `.body = v` (M3a: mesh switch in draw path, task 11)
  - LM_HIT (16): M3c stub — consume raw anim, startFrame, groupNumber, hitBoxSize, evalVar hitForce, raw nextAnim; set `a.anim_action_type = 0` placeholder
  - LM_MOVE (15): raw trackMode, raw trackNumber → `init_deplacement(a, mode, num)` (track.cpp InitDeplacement port: mode 2/3 set track_number + MARK=-1; mode 3 position_in_track=0)
  - LM_LIFE_MODE (25): raw → `a.life_mode = v`
  - LM_LIFE (32): raw → `a.life = v` (effective next tick — main-loop gate)
  - LM_ANIM_MOVE (14): 7 raw (stand, walk, run, stop, backward, turnRight, turnLeft) → store on actor for play loop to pick anim by speed/direction (M2 animMove port); consume + log
  - LM_TYPE (40): raw → `a.object_type = (a.object_type & ~AF_MASK) + (v & AF_MASK)`
  - LM_TEST_COL (55): raw → `a.dyn_flags = v` (set/clear bit 0)
  - LM_ANGLE (74): 3 raw → `a.alpha/a.beta/a.gamma = v`
  - LM_SET_BETA (45): raw beta, raw speed → `init_real_value(a.beta, beta, speed, a.rotate, game.timer)` (rotate to beta)
  - LM_SET_ALPHA (56): raw alpha, raw speed → same on alpha via rotate RealValue
  - LM_MANUAL_ROT (42): no args → `gere_manual_rot(a, 240, game.local_joyd)` (track.cpp:90 port)
  - LM_UP_COOR_Y (68): no args → `init_real_value(0, -2000, -1, a.y_handler, game.timer)`
  - LM_DO_REAL_ZV (38): recompute zv from body (M2 `actor_zv`) + room offsets
  - LM_DO_MAX_ZV (58) / LM_DO_CARRE_ZV (62): M3a — recompute zv using body max/cube bounds (FITD getZvMax/getZvCube semantics; implementer ports from FITD `main.cpp`)
  - LM_DEF_ZV (71): 6 raw → `a.zv = [room+step + arg...]` per research table (room/step offsets)
  - LM_GET_HARD_CLIP (73): no args → set `game.hard_clip` from current room collision box (M1 room data)
  - LM_STAGE (47): 5 raw (stage, room, x, y, z) → if camera target actor: `flag_change_etage`/`flag_change_salle` + new values; else adjust actor world coords (FITD setStage port, main.cpp)
  - LM_CAMERA_TARGET (51): raw target → `game.current_world_target = target`; if its obj is in floor: `game.current_camera_target_actor = world.obj_index`; room-change flag handling AITD1-style
  - LM_START_CHRONO (enum 95, not in AITD1 table — skip; AITD1 uses none)
  - LM_FOUND_NAME (49) / LM_FOUND_BODY (56) / LM_FOUND_FLAG (50) / LM_FOUND_WEIGHT (68) / LM_FOUND_LIFE (51): raw → world obj field (`found_name`, `found_body`, `found_flag = (found_flag & 0xE000) | v`, `position_in_track` (weight), `found_life`)
  - LM_FOUND (30): raw objectId → M3b stub: consume, log (FoundObjet needs inventory)
  - LM_DELETE (32): raw objectId → `delete_object(game, id)` — actor slot reset, world obj.obj_index=-1, foundFlag &= ~0x8000 then |= 0x4000 (AITD1)
  - LM_TAKE (33): raw objectId → M3b stub (consume, log)
  - LM_DROP (52): evalVar worldIdx, raw source → M3b stub (consume, log)
  - LM_PUT (59): 9 raw → set world obj (idx,x,y,z,room,stage,alpha,beta,gamma), foundFlag |= 0x4000 (M3b inventory removal skipped)
  - LM_PUT_AT (70): raw obj1, raw obj2 → `put_at_objet(game, obj1, obj2)` — place obj1 at obj2's coords + foundFlag |= 0x4000
  - LM_IN_HAND (34): raw → `game.in_hand_table[game.current_inventory] = v`
  - LM_INVENTORY (66): raw → `game.status_screen_allowed = v`
  - LM_C_VAR (60): raw idx, evalVar → `game.cvars[idx] = v`
  - LM_LIGHT (64): raw → `game.light_off = 2 - (v << 1)` (skipped if cvars[KILLED_SORCERER])
  - LM_GAME_OVER (41): no args → `game.flag_game_over = 1; vm.exit = True` (M3a: skip music + 120-tick spin)
  - MESSAGE stubs (M3b): LM_MESSAGE (17: 1 raw), LM_MESSAGE_VALUE (18: 2 raw).
  - Stubs (consume args, log only): LM_RND_FREQ (43: 1 raw), LM_SHAKING (65: 1 raw), LM_WATER (77: 1 raw), LM_SAMPLE (39: evalVar), LM_ANIM_SAMPLE (36: evalVar + 2 raw), LM_SPECIAL (37: 1 raw), LM_MUSIC (44: 1 raw), LM_SAMPLE_THEN (63: 2 evalVar), LM_SAMPLE_THEN_REPEAT (85: 2 evalVar), LM_REP_SAMPLE (75: evalVar + 1 raw skipped), LM_STOP_SAMPLE (79: 0), LM_NEXT_MUSIC (80: 1 raw → set next_music if current != -1), LM_FADE_MUSIC (81: 1 raw), LM_PICTURE (78: 3 raw + blocking wait skipped, FlagInitView=1), LM_READ (35: 2 raw + 1 raw SKIPPED — AITD1 extra word, FlagInitView=2), LM_END_SEQUENCE (84: 0), LM_WAIT_GAME_OVER (86: wait for key/JoyD/Click transitions then flag_game_over=1, exit — port both waits bug-for-bug including FITD's non-negated Click in the second wait), LM_THROW (76: 7 raw, M3c stub), LM_FIRE (53: 6 raw, M3c stub), LM_HIT_OBJECT (72: 2 raw, M3c stub), LM_STOP_HIT_OBJECT (82: 0 → if anim_action_type == 8 clear), LM_COPY_ANGLE (83: raw obj → copy alpha/beta/gamma from world obj or its actor)
- Reduced (not-in-floor) handlers on `world = game.world_objects[widx]` (same 16-opcode set as task 5's `_REDUCED_ALLOWED`): LM_BODY (eval_var → `.body`), LM_TYPE (flags `TYPE_MASK`), LM_ANIM_ONCE/ALL_ONCE/REPEAT (consume, set `.anim`/`.anim_info`), LM_MOVE (set `.track_mode/.track_number/.position_in_track`), LM_ANGLE (3 raw → `.alpha/.beta/.gamma`), LM_STAGE (5 raw → `.stage/.room/.x/.y/.z`), LM_TEST_COL (1 raw → flags bit), LM_LIFE (raw → `.life`), LM_LIFE_MODE (raw → `.life_mode`), LM_FOUND_NAME/BODY/FLAG/WEIGHT (raw → field), LM_START_CHRONO (no-op).

- [ ] **Step 1: Write failing tests** `tests/test_life_ops.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
import struct

import pytest

from maitd.game import init_game
from maitd.life import process_life


class _FakeAssets:
    def __init__(self, script):
        self._script = script

    def life(self, index):
        return self._script

    def track(self, index):
        return b"\x02\x00"  # TL_END


def _run(game, *words, actor=None):
    if actor is None:
        actor = next(i for i, a in enumerate(game.actors) if a.index_in_world != -1)
    game.assets = _FakeAssets(struct.pack(f"<{len(words)}h", *words))
    game.actors[actor].life = 0
    process_life(game, actor, 0)
    return game.actors[actor]


def test_angle_sets(data_dir):
    game = init_game(data_dir, hero=0)
    a = _run(game, 74, 0x10, 0x20, 0x30, 11)
    assert (a.alpha, a.beta, a.gamma) == (0x10, 0x20, 0x30)


def test_life_and_life_mode(data_dir):
    game = init_game(data_dir, hero=0)
    a = _run(game, 24, 1, 31, 5, 11)
    assert a.life_mode == 1
    assert a.life == 5


def test_move_init_track(data_dir):
    game = init_game(data_dir, hero=0)
    a = _run(game, 15, 3, 7, 11)
    assert a.track_mode == 3
    assert a.track_number == 7
    assert a.position_in_track == 0
    assert a.mark == -1


def test_c_var_write(data_dir):
    game = init_game(data_dir, hero=0)
    _run(game, 60, 0, -1, 99, 11)  # LM_C_VAR idx 0, evalVar literal 99
    assert game.cvars[0] == 99


def test_found_flag_masked(data_dir):
    game = init_game(data_dir, hero=0)
    actor = next(i for i, a in enumerate(game.actors) if a.index_in_world != -1)
    widx = game.actors[actor].index_in_world
    game.world_objects[widx].found_flag = 0xFFFF
    _run(game, 49, 0x23, 11, actor=actor)  # LM_FOUND_FLAG 0x23
    assert game.world_objects[widx].found_flag == (0xFFFF & 0xE000) | 0x23


def test_delete_object(data_dir):
    game = init_game(data_dir, hero=0)
    actor = next(i for i, a in enumerate(game.actors) if a.index_in_world != -1)
    widx = game.actors[actor].index_in_world
    _run(game, 32, widx, 11, actor=actor)
    assert game.world_objects[widx].obj_index == -1
    assert game.actors[actor].index_in_world == -1


def test_stub_consumes_args(data_dir):
    game = init_game(data_dir, hero=0)
    a = _run(game, 43, 123, 65, 456, 11)  # RND_FREQ + SHAKING stubs, args consumed
    assert a.life == 0  # unchanged; no crash = args consumed correctly


def test_type_mask(data_dir):
    game = init_game(data_dir, hero=0)
    a = _run(game, 40, 0x0020, 11)  # LM_TYPE AF_SPECIAL
    assert a.object_type & 0x0020
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/pytest tests/test_life_ops.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'maitd.life_ops'` (or NotImplementedError from the placeholder table).

- [ ] **Step 3: Implement** `maitd/life_ops.py`, `maitd/life_reduced.py`, wire `maitd/life.py`

Implementer follows the Interfaces table above; every handler is small (`read_s16` + field write + trace line). Structure:

```python
# maitd/life_ops.py
# SPDX-License-Identifier: GPL-2.0-only
"""Full-dispatch opcode handlers (life.cpp switch bodies, AITD1)."""
from maitd.life import read_s16, eval_var
from maitd.realvalue import init_real_value


def op_angle(vm):
    vm.actor.alpha = read_s16(vm)
    vm.actor.beta = read_s16(vm)
    vm.actor.gamma = read_s16(vm)
```

and in `maitd/life.py`:

```python
def _install_handlers():
    from maitd import life_ops as ops
    LIFETABLE[0] = lambda vm: process_track(vm)          # LM_DO_MOVE
    LIFETABLE[1] = ops.op_anim_once
    LIFETABLE[2] = ops.op_anim_all_once
    LIFETABLE[3] = ops.op_body
    LIFETABLE[13] = ops.op_anim_repeat
    LIFETABLE[14] = ops.op_anim_move
    LIFETABLE[15] = ops.op_move
    LIFETABLE[16] = ops.op_hit
    LIFETABLE[17] = ops.op_message
    LIFETABLE[18] = ops.op_message_value
    LIFETABLE[30] = ops.op_found
    LIFETABLE[31] = ops.op_life
    LIFETABLE[32] = ops.op_delete
    LIFETABLE[33] = ops.op_take
    LIFETABLE[34] = ops.op_in_hand
    LIFETABLE[35] = ops.op_read
    LIFETABLE[36] = ops.op_anim_sample
    LIFETABLE[37] = ops.op_special
    LIFETABLE[38] = ops.op_do_real_zv
    LIFETABLE[39] = ops.op_sample
    LIFETABLE[40] = ops.op_type
    LIFETABLE[41] = ops.op_game_over
    LIFETABLE[42] = ops.op_manual_rot
    LIFETABLE[43] = ops.op_rnd_freq
    LIFETABLE[44] = ops.op_music
    LIFETABLE[45] = ops.op_set_beta
    LIFETABLE[46] = ops.op_do_rot_zv
    LIFETABLE[47] = ops.op_stage
    LIFETABLE[48] = ops.op_found_name
    LIFETABLE[49] = ops.op_found_flag
    LIFETABLE[50] = ops.op_found_life
    LIFETABLE[51] = ops.op_camera_target
    LIFETABLE[52] = ops.op_drop
    LIFETABLE[53] = ops.op_fire
    LIFETABLE[54] = ops.op_test_col
    LIFETABLE[55] = ops.op_found_body
    LIFETABLE[56] = ops.op_set_alpha
    LIFETABLE[58] = ops.op_do_max_zv
    LIFETABLE[59] = ops.op_put
    LIFETABLE[60] = ops.op_c_var
    LIFETABLE[62] = ops.op_do_carre_zv
    LIFETABLE[63] = ops.op_sample_then
    LIFETABLE[64] = ops.op_light
    LIFETABLE[65] = ops.op_shaking
    LIFETABLE[66] = ops.op_inventory
    LIFETABLE[67] = ops.op_found_weight
    LIFETABLE[68] = ops.op_up_coor_y
    LIFETABLE[70] = ops.op_put_at
    LIFETABLE[71] = ops.op_def_zv
    LIFETABLE[72] = ops.op_hit_object
    LIFETABLE[73] = ops.op_get_hard_clip
    LIFETABLE[74] = ops.op_angle
    LIFETABLE[75] = ops.op_rep_sample
    LIFETABLE[76] = ops.op_throw
    LIFETABLE[77] = ops.op_water
    LIFETABLE[78] = ops.op_picture
    LIFETABLE[79] = ops.op_stop_sample
    LIFETABLE[80] = ops.op_next_music
    LIFETABLE[81] = ops.op_fade_music
    LIFETABLE[82] = ops.op_stop_hit_object
    LIFETABLE[83] = ops.op_copy_angle
    LIFETABLE[84] = ops.op_end_sequence
    LIFETABLE[85] = ops.op_sample_then_repeat
    LIFETABLE[86] = ops.op_wait_game_over

_install_handlers()
```

All 87 slots must be exactly covered: 0-16 (movement/anim/hit), 17-18 (MESSAGE stubs), 19-29 (var ops + control flow, task 5), 30-56, 58-60, 62-68, 70-86 (task 8), dead 27/57/61/69 (task 5). Any slot left as `_op_not_implemented` raises loudly rather than silently misbehaving.

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_life_ops.py -q`
Expected: 9 passed. Then full suite: `.venv/bin/pytest -q` — all green.

- [ ] **Step 5: Commit**

```bash
git add maitd/life_ops.py maitd/life_reduced.py maitd/life.py maitd/game.py tests/test_life_ops.py
git commit -m "feat: movement/state/object opcode handlers + reduced dispatch"
```

---

### Task 9: Play loop integration (script-driven input)

**Files:**
- Modify: `maitd/__main__.py` (rewrite the loop)
- Modify: `maitd/actors.py` (delete `player_step`; keep `Actor`-related helpers or re-home them into `game.py`)
- Modify: `maitd/game.py` (input mapping, `camera_param`, `hard_clip`)
- Test: `tests/test_play_loop.py`

**Interfaces:**
- Consumes: tasks 3-8, M1 Floor/rendering, M2 anim player/skinning/masks.
- Produces:
  - `def poll_input(game)` — pygame key state → `game.local_joyd` bits (UP=1, DOWN=2, LEFT=4, RIGHT=8), SPACE → `game.local_click`, ENTER → `game.local_key = 0x1C`, ESC → `0x1B`; then `game.action = 0x2000 if game.local_click else 0`
  - `def play_tick(game, floor, renderer)` — one 50Hz logic tick in PlayWorld order (mainLoop.cpp):
    1. `game_step_tick(game)`; `poll_input(game)`
    2. per actor with `index_in_world != -1`: clear `col_by/hit_by/hit/hard_dec/hard_col` to -1
    3. per actor: if `object_type & AF_ANIMATED`: M2 anim advance; if `object_type & AF_TRIGGER`: skip (GereDec — M3b); if `anim_action_type`: skip (GereFrappe — M3c)
    4. per actor: `if life_gate(actor): process_life(game, i, actor.life)`; `if game.flag_change_etage: break`
    5. if `game.flag_change_etage`: M3a: set `current_floor = new_num_etage`, reload stage actors (`spawn_stage_actors`), clear flag
    6. if `game.flag_change_salle`: `change_salle(game, game.new_num_salle)`; clear flag; skip camera pass this tick (`continue` semantics)
    7. camera switch: if `current_camera_target_actor != -1`: M2 `find_best_camera` on that actor → `game.new_num_camera`; if changed → `flag_init_view = 1`
    8. if `flag_init_view`: recompute view (M2) and clear the flag
    9. `spawn_stage_actors(game)` if `flag_genere_aff_list`
    10. draw: M2 pipeline with every live actor (skin + masks), camera `game.num_camera`
  - `def run(data_dir, trace_path=None)` — init `Game`, `Floor`, loop at 50Hz (M2 clock discipline), draw, quit on `pygame.QUIT`; `--trace FILE` writes per-opcode lines (`actor`, `life`, `op`, `pc`, args) — `Trace` helper class in `maitd/life.py` (best-effort IO, never crashes).
- Removed: M2 direct-input movement path (`player_step` calls from `__main__`).

- [ ] **Step 1: Write failing tests** `tests/test_play_loop.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
from maitd.game import init_game
from maitd.life import life_gate


def test_life_gate(data_dir):
    game = init_game(data_dir, hero=0)
    a = game.actors[0]
    a.life, a.life_mode = -1, -1
    assert not life_gate(a)
    a.life, a.life_mode = 3, 0
    assert life_gate(a)
    a.life, a.life_mode = 3, -1
    assert not life_gate(a)
    a.life, a.life_mode = -1, 0
    assert not life_gate(a)


def test_poll_input_mapping(data_dir):
    # pygame not importable headless in all environments: test the pure mapping helper
    from maitd.game import joyd_from_keys
    assert joyd_from_keys(up=True) == 1
    assert joyd_from_keys(down=True) == 2
    assert joyd_from_keys(left=True) == 4
    assert joyd_from_keys(right=True) == 8
    assert joyd_from_keys(up=True, left=True) == 5
    assert joyd_from_keys() == 0
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/pytest tests/test_play_loop.py -q`
Expected: FAIL, `ImportError: cannot import name 'joyd_from_keys'`.

- [ ] **Step 3: Implement** — `game.py` gets:

```python
def joyd_from_keys(up=False, down=False, left=False, right=False):
    joyd = 0
    if up:
        joyd |= 1
    if down:
        joyd |= 2
    if left:
        joyd |= 4
    if right:
        joyd |= 8
    return joyd
```

and `__main__.py` rewires to `poll_input`/`play_tick`/`run` per Interfaces (implementer adapts the existing M2 `__main__.py`; keep the M2 render path untouched except per-actor iteration over `game.actors`).

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_play_loop.py -q`
Expected: 2 passed. Then full suite `.venv/bin/pytest -q` — all green (removing `player_step` must not break any test; verify with `rg player_step tests/` = empty).

- [ ] **Step 5: Commit**

```bash
git add maitd/__main__.py maitd/actors.py maitd/game.py tests/test_play_loop.py
git commit -m "feat: FITD play loop, script-driven input, trace hook"
```

---

### Task 10: Proof — parse-all harness and headless boot

**Files:**
- Modify: `Makefile` (`prove` target), `tests/test_prove_m3a.py`
- Test: `tests/test_prove_m3a.py`

**Interfaces:**
- Consumes: everything above; real game data.
- Produces:
  - `make prove` runs: all 563 LISTLIFE scripts parse (fetch all entries through `Assets.life`), all 45 LISTTRAK entries fetch, OBJETS/VARS/DEFINES/PRIORITY parse, `init_game` spawns actors, and 60 headless ticks execute with trace to `/tmp/m3a_trace.log` (assert: no exception; trace non-empty; game not game-over)
  - Manual proof: `make run` boots to attic — intro script visible in trace (`--trace`), player spawns, camera view correct; user confirms visuals.

- [ ] **Step 1: Write failing tests** `tests/test_prove_m3a.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
import pathlib

from maitd.assets import Assets
from maitd.formats import parse_defines, parse_objets, parse_priority, parse_vars


def test_all_scripts_fetch(data_dir):
    assets = Assets(data_dir)
    assert assets.num_lifes == 563
    for i in range(assets.num_lifes):
        raw = assets.life(i)
        assert len(raw) % 2 == 0  # s16 stream
        assert len(raw) >= 2


def test_all_tracks_fetch(data_dir):
    assets = Assets(data_dir)
    assert assets.num_tracks == 45
    for i in range(assets.num_tracks):
        assert len(assets.track(i)) >= 2


def test_all_tables_parse(data_dir):
    d = pathlib.Path(data_dir)
    assert len(parse_objets((d / "OBJETS.ITD").read_bytes())) == 292
    assert len(parse_vars((d / "VARS.ITD").read_bytes())) == 207
    assert len(parse_defines((d / "DEFINES.ITD").read_bytes())) == 45
    assert len(parse_priority((d / "PRIORITY.ITD").read_bytes())) == 50


def test_headless_boot_ticks(data_dir):
    from maitd.game import init_game
    from maitd.life import process_life
    game = init_game(data_dir, hero=0)
    for tick in range(60):
        game.timer += 1
        for i, a in enumerate(game.actors):
            if a.index_in_world != -1 and a.life != -1 and a.life_mode != -1:
                process_life(game, i, a.life)
    assert game.flag_game_over == 0
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/pytest tests/test_prove_m3a.py -q`
Expected: partial fails until tasks above land; final run: 4 passed.

- [ ] **Step 3: Update `Makefile`**

```makefile
prove:
	.venv/bin/pytest tests/test_prove_m3a.py -q
```

- [ ] **Step 4: Run full suite, verify pass**

Run: `.venv/bin/pytest -q`
Expected: 76 (M1/M2) + 4 + 3 + 3 + 6 + 8 + 10 + 9 + 5 + 2 + 4 = 130 passed.

- [ ] **Step 5: Manual smoke, then commit**

Run: `make run` — attic scene with live scripts; `make run TRACE=/tmp/m3a_trace.log` shows intro flow. User confirms.

```bash
git add Makefile tests/test_prove_m3a.py
git commit -m "feat: M3a proof harness (parse-all + headless boot)"
```

---

## Final verification checklist

- [ ] `.venv/bin/pytest -q` — all green (expect ~130)
- [ ] `make run` — attic boots, player visible, intro script runs (trace)
- [ ] `make prove` — parse-all + headless 60-tick boot clean
- [ ] Trace log shows opcode flow with no NotImplementedError / ValueError lines
- [ ] Branch merged to main per superpowers:subagent-driven-development closing ritual

## Known simplifications (ponytail:)

- Life-mode 2 (camera-scoped) spawn gate accepts any room — tighten when multi-room floors appear (stage 1+ floors).
- `camera_param` (evalVar 0x1B) mapping is pinned in task 8 with a real-data test; revisit if camera switch feels wrong.
- GereDec (zone trigger processing), GereFrappe (combat anims), inventory FoundObjet chain are M3b/M3c — the play loop skips them; scripts touching them take stub paths.
- Audio/inventory/combat/text handlers consume args and log; if the intro stalls on one, promote it (spec's risk section rule).
