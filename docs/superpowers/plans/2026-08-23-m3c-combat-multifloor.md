# M3c Combat and Multi-Floor Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make FITD-faithful melee, firearm, and thrown-object combat publish real hits, drive the original hero death script into an accessible game-over restart, and provide one supported floor-5 combat venue.

**Architecture:** Phase A first fixes the out-of-floor evaluator and centralizes stage relocation behind `FloorStart`, then exposes the same floor-5 scenario to the CLI, tests, and proof tool. Phase B adds one pygame-free animation-action module that shares skeletal posing with rendering, followed by a typed game-over modal whose restart remains owned by the outer loop. Existing collision, room, inventory, fixed-point, pygame Surface/font, and single-event-pump paths are reused; no parallel gameplay or UI mechanism is introduced.

**Tech Stack:** Python 3.12, pygame-ce, ModernGL, NumPy, pytest, original AITD1 data, FITD C++ reference.

**Spec:** `docs/superpowers/specs/2026-08-23-m3c-combat-multifloor-design.md`

## Global Constraints

- Dependencies remain exactly pygame-ce, ModernGL, NumPy, and pytest; add nothing.
- Every new Python file starts with `# SPDX-License-Identifier: GPL-2.0-only`.
- `anim_action.py`, `playworld.py`, `life_ops.py`, `interaction.py`, and `effects.py` stay free of pygame, ModernGL, rendering, and event-pump imports.
- `ui.py` presents state only; only `__main__.py` pumps events, replaces a `Game`, loads `Floor`, and presents once per outer frame.
- Preserve FITD action values exactly: melee `1 -> 10 -> 2`, fire `4 -> 5`, throw `6 -> 7 -> 9`, and hit-object `8`; declared-but-unhandled value 3 is rejected.
- Preserve the shooting no-hard-collision termination, crossed `walkStep` outputs, melee state-2 fall-through, and every existing do-not-fix quirk.
- Combat publishes `hit`, `hit_by`, and `hit_force`; it never writes actor `life` or invents health state.
- `LM_THROW` is incomplete until setup, active-list regeneration, launch, flight, reflection, collision, and stopped placement all pass.
- `InitSpecialObjet`, audio, `LM_END_SEQUENCE`, menus, save/load, and generic arbitrary-floor relocation remain out of scope.
- The only supported non-attic debug start is `FloorStart(5, 4, -7800, -4010, -1000, 0)` via `--combat-venue`; non-zero `--floor` exits with status 2.
- GAME_OVER waits `120 * 1000 // 60` ms, keeps the last PLAY frame byte-identical while locked, and accepts any left click across the 320x200 logical frame once ready.
- Rendering tests run with `SDL_VIDEODRIVER=dummy`; after non-trivial changes run `.venv/bin/pytest -q && make prove`.
- Every new test must be observed failing with its corresponding implementation hunk reverted before the task is committed.
- The spec is already modified in the starting worktree. Inspect `git diff` before overlapping edits, preserve unrelated work, and stage only task-owned hunks.

## File Structure and Ownership

| File | M3c responsibility |
|---|---|
| `PyAitD/game.py` | `FloorStart`, relocation/immediate floor-entry services, restart request state |
| `PyAitD/scenario.py` | Pinned combat venue and its one public entry function |
| `PyAitD/eval_var.py` | Correct raw-tag handling for out-of-floor room/stage properties |
| `PyAitD/life_ops.py` | Decode HIT/FIRE/THROW and request stage/game-over state; no combat geometry |
| `PyAitD/skel.py` | One unprojected pose implementation shared by rendering and hot points |
| `PyAitD/anim_action.py` | Pygame-free FITD action runner, line sweep, throw flight and stop placement |
| `PyAitD/playworld.py` | Existing per-actor ordering and game-over flag-to-modal handoff |
| `PyAitD/effects.py` | Frozen `GameOver` effect and `GameMode.GAME_OVER` mapping |
| `PyAitD/ui.py` | Generic modal elapsed time and pure game-over frame composition |
| `PyAitD/__main__.py` | CLI scenario selection, modal routing, restart reconstruction, Floor I/O |
| `tools/prove_combat.py` | Headless shared-venue milestone gate |
| `tests/test_scenario.py` | Phase-A floor-entry and real venue contracts |
| `tests/test_anim_action.py` | Pure action-state, collision, fire, and throw contracts |
| `tests/test_combat_journey.py` | Real-data enemy, hero damage/death, and player-arm journeys |
| `tests/test_game_over.py` | Flag scheduling, modal timing, routing, rendering, and reconstruction |
| `Makefile`, `CONTEXT.md`, `docs/m3c-combat-proof.md` | Operator commands, landed architecture, and manual evidence |

---

### Task 1: Correct out-of-floor `evalVar` raw tags

**Files:**
- Modify: `PyAitD/eval_var.py:168-191`
- Modify: `tests/test_eval_var.py:54-62`

**Interfaces:**
- Consumes: `eval_var(vm)`, the existing `VM` byte cursor, and `WorldObject.obj_index`.
- Produces: raw other-object tags `0x801F -> room` and `0x8026 -> stage`; every other out-of-floor property raises a FITD-specific `ValueError`.

- [ ] **Step 1: Replace the accidentally self-confirming test with raw-tag cases**

```python
def test_other_object_not_in_floor_supports_only_fitd_raw_tags(data_dir):
    game = init_game(data_dir, hero=0)
    widx = next(i for i, w in enumerate(game.world_objects) if w.obj_index == -1)
    world = game.world_objects[widx]
    world.room = 3
    world.stage = 5

    assert eval_var(_vm(game, 0x801F, widx)) == 3
    assert eval_var(_vm(game, 0x8026, widx)) == 5

    with pytest.raises(ValueError, match=r"raw tag 0x8020.*FITD asserts"):
        eval_var(_vm(game, 0x8020, widx))
```

- [ ] **Step 2: Run the focused test and confirm the old decrement order fails**

Run: `.venv/bin/pytest tests/test_eval_var.py::test_other_object_not_in_floor_supports_only_fitd_raw_tags -q`

Expected: FAIL because raw tag `0x801F` becomes code `0x1E`, which the current branch rejects.

- [ ] **Step 3: Compare the decremented code while retaining the raw tag for diagnostics**

```python
def _other_object_property(game, vm, tag, widx, world):
    raw_tag = tag & 0x7FFF
    code = raw_tag - 1
    if world.obj_index != -1:
        return _prop(game, game.actors[world.obj_index], code, vm)
    if code == 0x1E:
        return world.room
    if code == 0x25:
        return world.stage
    raise ValueError(
        f"evalVar: raw tag 0x{raw_tag:04X} on out-of-floor object {widx}; "
        "FITD asserts for this property"
    )
```

- [ ] **Step 4: Run evaluator and full regressions**

Run: `.venv/bin/pytest tests/test_eval_var.py -q && .venv/bin/pytest -q`

Expected: PASS, with the current repository baseline or better.

- [ ] **Step 5: Revert only the `0x1E`/`0x25` comparisons, prove the new test turns red, restore, and commit**

```bash
git add PyAitD/eval_var.py tests/test_eval_var.py
git commit -m "fix: decode out-of-floor evalVar tags"
```

---

### Task 2: Centralize actor relocation and restart boundaries

**Files:**
- Modify: `PyAitD/game.py:38-42,109-167,276-321,529-539`
- Modify: `PyAitD/life_ops.py:276-321`
- Create: `tests/test_floor_start.py`
- Modify: `tests/test_life_ops.py`

**Interfaces:**
- Consumes: `change_salle(game, room)`, `spawn_stage_actors(game)`, `room_delta`, and the current camera-target actor.
- Produces:
  - `FloorStart(stage: int, room: int, x: int, y: int, z: int, camera_slot: int)` frozen dataclass.
  - `relocate_actor(game, actor_idx: int, stage: int, room: int, x: int, y: int, z: int) -> None`.
  - `enter_floor_start(game, floor_start: FloorStart) -> None`, with no `Floor` I/O.
  - `Game.floor_start: FloorStart` and `Game.restart_requested: bool`.

- [ ] **Step 1: Add tests for relocation, one immediate spawn pass, and initial floor recording**

```python
# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.game import FloorStart, enter_floor_start, init_game, relocate_actor


def test_relocate_actor_rebases_zv_and_zeroes_steps(data_dir):
    game = init_game(data_dir)
    idx = game.current_camera_target_actor
    actor = game.actors[idx]
    actor.step_x, actor.step_y, actor.step_z = 11, 12, 13
    old_zv = list(actor.zv)
    old_actual = (actor.room_x + 11, actor.room_y + 12, actor.room_z + 13)

    relocate_actor(game, idx, 5, 4, -7800, -4010, -1000)

    delta = (-7800 - old_actual[0], -4010 - old_actual[1], -1000 - old_actual[2])
    assert actor.zv == [
        old_zv[0] + delta[0], old_zv[1] + delta[0],
        old_zv[2] + delta[1], old_zv[3] + delta[1],
        old_zv[4] + delta[2], old_zv[5] + delta[2],
    ]
    assert (actor.stage, actor.room) == (5, 4)
    assert (actor.room_x, actor.room_y, actor.room_z) == (-7800, -4010, -1000)
    assert (actor.step_x, actor.step_y, actor.step_z) == (0, 0, 0)


def test_enter_floor_start_applies_transition_postconditions(data_dir, monkeypatch):
    import PyAitD.game as game_module
    game = init_game(data_dir)
    calls = []
    real_spawn = game_module.spawn_stage_actors
    monkeypatch.setattr(
        game_module, "spawn_stage_actors",
        lambda current: (calls.append(current.current_floor), real_spawn(current))[1],
    )
    start = FloorStart(5, 4, -7800, -4010, -1000, 0)

    enter_floor_start(game, start)

    assert calls == [5]
    assert (game.current_floor, game.new_num_etage) == (5, 5)
    assert (game.current_room, game.new_num_salle) == (4, 4)
    assert game.new_num_camera == 0
    assert (game.num_camera, game.flag_init_view) == (-1, 2)
    assert (game.flag_change_etage, game.flag_genere_aff_list) == (0, 0)


def test_init_game_records_the_real_hero_start(data_dir):
    game = init_game(data_dir)
    hero = game.actors[game.current_camera_target_actor]
    assert game.floor_start == FloorStart(
        hero.stage, hero.room, hero.room_x, hero.room_y, hero.room_z, 0,
    )
    assert game.restart_requested is False
```

- [ ] **Step 2: Run the new test and verify the interfaces are absent**

Run: `.venv/bin/pytest tests/test_floor_start.py -q`

Expected: collection FAIL because `FloorStart` is not defined.

- [ ] **Step 3: Add the frozen value and extract the exact `op_stage` mutation**

```python
@dataclass(frozen=True)
class FloorStart:
    stage: int
    room: int
    x: int
    y: int
    z: int
    camera_slot: int


def relocate_actor(game, actor_idx, stage, room, x, y, z):
    actor = game.actors[actor_idx]
    actual_x = actor.room_x + actor.step_x
    actual_y = actor.room_y + actor.step_y
    actual_z = actor.room_z + actor.step_z
    actor.zv[0] += x - actual_x
    actor.zv[1] += x - actual_x
    actor.zv[2] += y - actual_y
    actor.zv[3] += y - actual_y
    actor.zv[4] += z - actual_z
    actor.zv[5] += z - actual_z
    actor.stage, actor.room = stage, room
    actor.room_x = actor.world_x = x
    actor.room_y = actor.world_y = y
    actor.room_z = actor.world_z = z
    actor.step_x = actor.step_y = actor.step_z = 0
```

Replace only the duplicated coordinate block in `op_stage` with:

```python
relocate_actor(game, vm.cur_idx, new_stage, new_room, x, y, z)
if game.current_camera_target_actor == vm.cur_idx:
    if new_stage != game.current_floor:
        game.floor_start = FloorStart(new_stage, new_room, x, y, z, 0)
        game.flag_change_etage = 1
        game.new_num_etage = new_stage
        game.new_num_salle = new_room
    elif game.current_room != new_room:
        game.flag_change_salle = 1
        game.new_num_salle = new_room
elif game.current_room != new_room:
    actor = game.actors[vm.cur_idx]
    dx, dy, dz = room_delta(game, new_room, game.current_room)
    actor.world_x -= dx
    actor.world_y += dy
    actor.world_z += dz
```

- [ ] **Step 4: Add the one immediate floor-entry service and initialize session state**

```python
def enter_floor_start(game, floor_start):
    relocate_actor(
        game, game.current_camera_target_actor,
        floor_start.stage, floor_start.room,
        floor_start.x, floor_start.y, floor_start.z,
    )
    game.current_floor = game.new_num_etage = floor_start.stage
    game.flag_change_etage = 0
    change_salle(game, floor_start.room)
    game.new_num_salle = floor_start.room
    game.new_num_camera = floor_start.camera_slot
    game.flag_init_view = 2
    spawn_stage_actors(game)
    game.flag_genere_aff_list = 0
    game.num_camera = -1
```

In `Game.__init__`, initialize `floor_start = None` and `restart_requested = False`. At the end of `init_game`, construct the initial `FloorStart` from the spawned hero after `change_salle` and camera-slot setup.

- [ ] **Step 5: Pin `op_stage` decoding and natural restart-point recording**

```python
def test_hero_stage_opcode_records_destination(data_dir):
    game = init_game(data_dir)
    hero_idx = game.current_camera_target_actor
    actor = _run(game, 47, 5, 4, -7800, -4010, -1000, 11, actor=hero_idx)
    assert game.floor_start == FloorStart(5, 4, -7800, -4010, -1000, 0)
    assert game.flag_change_etage == 1
    assert game.new_num_etage == 5
    assert (actor.stage, actor.room) == (5, 4)
```

- [ ] **Step 6: Run focused and full tests, perform the revert-red check, and commit**

Run: `.venv/bin/pytest tests/test_floor_start.py tests/test_life_ops.py -q && .venv/bin/pytest -q`

```bash
git add PyAitD/game.py PyAitD/life_ops.py tests/test_floor_start.py tests/test_life_ops.py
git commit -m "feat: centralize floor start transitions"
```

---

### Task 3: Expose the shared floor-5 combat venue

**Files:**
- Create: `PyAitD/scenario.py`
- Create: `tests/test_scenario.py`
- Create: `tools/prove_combat.py`
- Modify: `PyAitD/__main__.py:36-41,414-426`
- Modify: `Makefile`

**Interfaces:**
- Consumes: `FloorStart`, `enter_floor_start`, `Floor`, `play_tick`, `InputBuffer`, and `give_distance_2d`.
- Produces: `COMBAT_VENUE`, `enter_combat_venue(game)`, CLI `--combat-venue`, `make run-combat`, and the Phase-A form of `make prove-combat`.

- [ ] **Step 1: Write the real-data venue postcondition test**

```python
# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.game import init_game
from PyAitD.scenario import COMBAT_VENUE, enter_combat_venue


def test_combat_venue_uses_the_supported_floor_start(data_dir):
    game = init_game(data_dir)
    enter_combat_venue(game)
    enemy_idx = game.world_objects[222].obj_index
    enemy = game.actors[enemy_idx]

    assert game.floor_start == COMBAT_VENUE
    assert (game.current_floor, game.current_room) == (5, 4)
    assert (game.num_camera, game.new_num_camera, game.flag_init_view) == (-1, 0, 2)
    assert sum(actor.index_in_world >= 0 for actor in game.actors) == 48
    assert enemy.index_in_world == 222
    assert (enemy.track_mode, enemy.track_number, enemy.object_type) == (2, 1, 0x0141)
```

- [ ] **Step 2: Run the test and verify the scenario module is absent**

Run: `.venv/bin/pytest tests/test_scenario.py -q`

Expected: collection FAIL for missing `PyAitD.scenario`.

- [ ] **Step 3: Add the data-only scenario wrapper**

```python
# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.game import FloorStart, enter_floor_start

COMBAT_VENUE = FloorStart(5, 4, -7800, -4010, -1000, 0)


def enter_combat_venue(game):
    enter_floor_start(game, COMBAT_VENUE)
    game.floor_start = COMBAT_VENUE
```

- [ ] **Step 4: Add the honest CLI contract**

Add `p.add_argument("--combat-venue", action="store_true", help="start at the supported floor-5 combat venue")`. In `main` use:

```python
def main(argv=None):
    args = parse_args(argv)
    game = init_game(args.data)
    if args.floor != 0:
        print(
            "error: non-zero --floor has no safe room/coordinate mapping; "
            "use --combat-venue",
            file=sys.stderr,
        )
        return 2
    if args.combat_venue:
        enter_combat_venue(game)
    return run(game, args.trace)
```

Add tests that `main(["--floor", "5", "--data", str(data_dir)]) == 2` without calling `run`, and that `main(["--combat-venue", "--data", str(data_dir)])` calls `enter_combat_venue` exactly once before `run`.

- [ ] **Step 5: Add one headless proof implementation and two Make targets**

```python
# tools/prove_combat.py
# SPDX-License-Identifier: GPL-2.0-only
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PyAitD.effects import GameMode
from PyAitD.floor import Floor
from PyAitD.game import init_game
from PyAitD.playworld import play_tick
from PyAitD.realvalue import give_distance_2d
from PyAitD.scenario import enter_combat_venue
from PyAitD.ui import InputBuffer


def main(argv):
    data = pathlib.Path(argv[0])
    game = init_game(data)
    enter_combat_venue(game)
    floor = Floor(data, game.current_floor)
    hero = game.actors[game.current_camera_target_actor]
    enemy = game.actors[game.world_objects[222].obj_index]
    start = give_distance_2d(hero.room_x, hero.room_z, enemy.room_x, enemy.room_z)
    closest = start
    for _ in range(1200):
        play_tick(game, floor, InputBuffer())
        if game.mode is not GameMode.PLAY:
            raise AssertionError(f"venue opened unexpected mode {game.mode}")
        closest = min(
            closest,
            give_distance_2d(hero.room_x, hero.room_z, enemy.room_x, enemy.room_z),
        )
    if closest >= start:
        raise AssertionError(f"obj222 did not pursue: start={start}, closest={closest}")
    print(f"venue pursuit: start={start}, closest={closest}")
    print("combat arms: pending Phase B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

```make
run-combat: install ## Run the supported floor-5 combat venue
	$(PYTHON) -m PyAitD --combat-venue --data $(data) $(if $(trace),--trace $(trace))

prove-combat: install ## M3c proof: shared floor-5 venue and combat journeys
	SDL_VIDEODRIVER=dummy $(PYTHON) tools/prove_combat.py $(data)
```

Add both names to `.PHONY`.

- [ ] **Step 6: Close Phase A with focused, proof, and regression gates**

Run: `.venv/bin/pytest tests/test_eval_var.py tests/test_floor_start.py tests/test_scenario.py -q && make prove-combat && .venv/bin/pytest -q && make prove`

Expected: all PASS; `prove-combat` reports pursuit plus the explicit Phase-B pending line.

- [ ] **Step 7: Revert `enter_combat_venue`, confirm both venue test and proof fail, restore, and commit**

```bash
git add PyAitD/scenario.py PyAitD/__main__.py tests/test_scenario.py tools/prove_combat.py Makefile
git commit -m "feat: add shared combat venue"
```

---

### Task 4: Share skeletal posing with combat hot points

**Files:**
- Modify: `PyAitD/skel.py:23-91`
- Modify: `tests/test_skel.py`

**Interfaces:**
- Consumes: parsed `Body`, animation `group_states`, and actor `(alpha, beta, gamma)`.
- Produces:
  - `pose_vertices(body, group_states, actor_angles=None) -> list[tuple[int, int, int]]`.
  - `hot_point(body, group_states, actor_angles, hot_point_id) -> tuple[int, int, int]`.
  - `skin(body, group_states, position, camera, actor_angles=None)` delegates its unprojected transform to `pose_vertices`.

- [ ] **Step 1: Add synthetic and real-body hot-point tests**

```python
from PyAitD.skel import hot_point, pose_vertices, skin


def test_hot_point_is_the_shared_posed_base_vertex():
    body = Body(
        flags=2, zv=(0, 0, 0, 0, 0, 0), scratch=(),
        vertices=[(100, 0, 0), (0, 0, 0)],
        groups=[Group(0, 1, 1, 0xFF, 0, 0, 0, 0)], group_order=[0],
        primitives=[],
    )
    states = [(0, (0, 0x100, 0))]
    posed = pose_vertices(body, states, actor_angles=(0, 0x100, 0))
    assert hot_point(body, states, (0, 0x100, 0), 0) == tuple(posed[1])


def test_real_combat_bodies_share_the_named_base_vertex(data_dir):
    game = init_game(data_dir)
    for body_num in (234, game.actors[game.current_camera_target_actor].body_num):
        body = game.assets.body(body_num)
        states = [(0, (0x20, 0x40, 0x10)) for _ in body.groups]
        posed = pose_vertices(body, states, actor_angles=(0x10, 0x80, 0x20))
        assert hot_point(body, states, (0x10, 0x80, 0x20), 0) == tuple(
            posed[body.groups[0].base_vertices]
        )


def test_hot_point_zero_and_bad_group_contracts(data_dir):
    plain = _cube_body()
    assert hot_point(plain, [], (0, 0, 0), 0) == (0, 0, 0)
    body = init_game(data_dir).assets.body(234)
    with pytest.raises(ValueError, match=r"body 234.*group"):
        hot_point(body, [(0, (0, 0, 0))] * len(body.groups), (0, 0, 0), len(body.groups))
```

- [ ] **Step 2: Run the tests and verify both exports are missing**

Run: `.venv/bin/pytest tests/test_skel.py -q`

Expected: collection FAIL importing `pose_vertices` and `hot_point`.

- [ ] **Step 3: Extract the existing transform without changing projection**

```python
def pose_vertices(body, group_states, actor_angles=None):
    pts = [list(vertex) for vertex in body.vertices]
    if actor_angles is not None:
        if body.group_order:
            group_states = list(group_states)
            group_states[0] = (0, actor_angles)
        else:
            _rotate_list(pts, 0, len(pts), *actor_angles)
    for order_idx in body.group_order:
        group = body.groups[order_idx]
        group_type, (dx, dy, dz) = group_states[order_idx]
        if not (dx or dy or dz):
            continue
        if group_type == 0:
            _rotate_group(pts, group, body.groups, dx, dy, dz)
        elif group_type == 1:
            for index in range(group.num_vertices):
                point = pts[group.start + index]
                point[0] += dx; point[1] += dy; point[2] += dz
        elif group_type == 2:
            for index in range(group.num_vertices):
                point = pts[group.start + index]
                point[0] = _trunc_div(point[0] * (dx + 256), 256)
                point[1] = _trunc_div(point[1] * (dy + 256), 256)
                point[2] = _trunc_div(point[2] * (dz + 256), 256)
    for group in body.groups:
        base = pts[group.base_vertices]
        for index in range(group.num_vertices):
            point = pts[group.start + index]
            point[0] += base[0]; point[1] += base[1]; point[2] += base[2]
    return pts


def hot_point(body, group_states, actor_angles, hot_point_id):
    if not body.flags & 2:
        return (0, 0, 0)
    if not 0 <= hot_point_id < len(body.groups):
        raise ValueError(
            f"body with {len(body.groups)} groups has hot-point group {hot_point_id}"
        )
    points = pose_vertices(body, group_states, actor_angles)
    return tuple(points[body.groups[hot_point_id].base_vertices])
```

At the top of `skin`, replace the duplicated pose block with `pts = pose_vertices(body, group_states, actor_angles)` and leave every camera/projection/primitive line unchanged.

- [ ] **Step 4: Run all skeleton/render goldens under dummy SDL**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_skel.py tests/test_render.py tests/test_picking.py -q`

Expected: PASS with unchanged projected points and pixels.

- [ ] **Step 5: Re-inline the old pose block temporarily, confirm the new hot-point tests fail to import, restore, and commit**

```bash
git add PyAitD/skel.py tests/test_skel.py
git commit -m "refactor: share posed skeleton vertices"
```

---

### Task 5: Port hot-point timing and melee publication

**Files:**
- Create: `PyAitD/anim_action.py`
- Create: `tests/test_anim_action.py`
- Modify: `PyAitD/playworld.py:66-77`
- Modify: `tests/test_playworld.py:1-29`

**Interfaces:**
- Consumes: `anim_player_for`, `check_object_col`, `skel.hot_point`, actor fields, and `AF_ANIMATED`/`AF_TRIGGER`.
- Produces: `refresh_hot_point(game, actor_idx)`, `gere_frappe(game, actor_idx)`, and constants `WAIT_FRAPPE_ANIM=1`, `FRAPPE_OK=2`, `WAIT_TIR_ANIM=4`, `DO_TIR=5`, `WAIT_ANIM_THROW=6`, `WAIT_FRAME_THROW=7`, `HIT_OBJECT=8`, `THROW_OBJECT=9`, `WAIT_FRAPPE_FRAME=10`.

- [ ] **Step 1: Write melee state, publication, fall-through, and ordering tests**

```python
def _live_actors(data_dir, count):
    game = init_game(data_dir)
    live = [i for i, actor in enumerate(game.actors) if actor.index_in_world >= 0]
    assert len(live) >= count
    selected = live[:count]
    room = game.actors[selected[0]].room
    for index in selected:
        game.actors[index].room = room
    return (game, *selected)


def test_melee_waits_for_animation_then_frame(data_dir):
    game, attacker_idx, _victim_idx = _live_actors(data_dir, 2)
    actor = game.actors[attacker_idx]
    actor.anim_action_type = WAIT_FRAPPE_ANIM
    actor.anim_action_anim = actor.anim
    actor.anim_action_frame = actor.frame + 1
    gere_frappe(game, attacker_idx)
    assert actor.anim_action_type == WAIT_FRAPPE_FRAME
    actor.frame += 1
    gere_frappe(game, attacker_idx)
    assert actor.anim_action_type == FRAPPE_OK


def test_frappe_ok_mismatch_still_hit_tests(monkeypatch, data_dir):
    game, attacker_idx, victim_idx = _live_actors(data_dir, 2)
    attacker = game.actors[attacker_idx]
    attacker.anim_action_type = FRAPPE_OK
    attacker.anim_action_anim = attacker.anim + 1
    attacker.anim_action_param = 50
    attacker.hit_force = 10
    monkeypatch.setattr("PyAitD.anim_action.check_object_col", lambda *args: (victim_idx,))
    gere_frappe(game, attacker_idx)
    assert attacker.anim_action_type == 0
    assert attacker.hit == victim_idx
    assert game.actors[victim_idx].hit_by == attacker_idx
    assert game.actors[victim_idx].hit_force == 10


def test_melee_stops_at_first_animated_victim(monkeypatch, data_dir):
    game, attacker_idx, first_idx, second_idx = _live_actors(data_dir, 3)
    game.actors[first_idx].object_type |= AF_ANIMATED
    monkeypatch.setattr(
        "PyAitD.anim_action.check_object_col", lambda *args: (first_idx, second_idx)
    )
    game.actors[attacker_idx].anim_action_type = FRAPPE_OK
    game.actors[attacker_idx].anim_action_param = 100
    gere_frappe(game, attacker_idx)
    assert game.actors[attacker_idx].hit == first_idx
    assert game.actors[second_idx].hit_by == -1


def test_anim_pass_refreshes_before_anim_and_strikes_after_dec(monkeypatch, data_dir):
    game = init_game(data_dir)
    idx = game.current_camera_target_actor
    game.actors[idx].anim_action_type = WAIT_FRAPPE_ANIM
    game.actors[idx].hot_point_id = 0
    calls = []
    monkeypatch.setattr("PyAitD.playworld.refresh_hot_point", lambda *args: calls.append("hot"))
    monkeypatch.setattr("PyAitD.playworld.gere_anim", lambda *args: calls.append("anim"))
    monkeypatch.setattr("PyAitD.playworld.gere_dec", lambda *args: calls.append("dec"))
    monkeypatch.setattr("PyAitD.playworld.gere_frappe", lambda *args: calls.append("hit"))
    _anim_pass(game)
    assert calls[:4] == ["hot", "anim", "dec", "hit"]
```

- [ ] **Step 2: Run the new tests and confirm `anim_action.py` is absent**

Run: `.venv/bin/pytest tests/test_anim_action.py tests/test_playworld.py -q`

Expected: collection FAIL for the missing module.

- [ ] **Step 3: Add the pygame-free cache and melee runner**

```python
# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.actors import anim_player_for, check_object_col
from PyAitD.game import AF_ANIMATED
from PyAitD.skel import hot_point

WAIT_FRAPPE_ANIM = 1
FRAPPE_OK = 2
WAIT_TIR_ANIM = 4
DO_TIR = 5
WAIT_ANIM_THROW = 6
WAIT_FRAME_THROW = 7
HIT_OBJECT = 8
THROW_OBJECT = 9
WAIT_FRAPPE_FRAME = 10
HANDLED_ACTIONS = {1, 2, 4, 5, 6, 7, 8, 9, 10}


def refresh_hot_point(game, actor_idx):
    actor = game.actors[actor_idx]
    body = game.assets.body(actor.body_num)
    states = (
        [(0, (0, 0, 0))] * len(body.groups)
        if actor.anim == -1 else anim_player_for(game, actor_idx).group_states()
    )
    actor.hot_point[:] = hot_point(
        body, states, (actor.alpha, actor.beta, actor.gamma),
        actor.hot_point_id,
    )


def _publish_hit(game, attacker_idx, victim_idx):
    attacker = game.actors[attacker_idx]
    victim = game.actors[victim_idx]
    attacker.hit = victim_idx
    victim.hit_by = attacker_idx
    victim.hit_force = attacker.hit_force


def gere_frappe(game, actor_idx):
    actor = game.actors[actor_idx]
    action = actor.anim_action_type
    if action not in HANDLED_ACTIONS:
        raise ValueError(f"actor {actor_idx} has unsupported anim action {action}")
    if action == WAIT_FRAPPE_ANIM:
        if actor.anim == actor.anim_action_anim:
            actor.anim_action_type = WAIT_FRAPPE_FRAME
        action = actor.anim_action_type
    if action == WAIT_FRAPPE_FRAME:
        if actor.anim != actor.anim_action_anim:
            actor.anim_action_type = 0
            return
        if actor.frame == actor.anim_action_frame:
            actor.anim_action_type = FRAPPE_OK
        return
    if action == FRAPPE_OK:
        if actor.anim != actor.anim_action_anim:
            actor.anim_action_type = 0
        x = actor.room_x + actor.hot_point[0] + actor.step_x
        y = actor.room_y + actor.hot_point[1] + actor.step_y
        z = actor.room_z + actor.hot_point[2] + actor.step_z
        radius = actor.anim_action_param
        cube = [x-radius, x+radius, y-radius, y+radius, z-radius, z+radius]
        for victim_idx in check_object_col(game, actor_idx, cube):
            _publish_hit(game, actor_idx, victim_idx)
            if game.actors[victim_idx].object_type & AF_ANIMATED:
                actor.anim_action_type = 0
                return
        return
    if action == HIT_OBJECT:
        return
```

Later tasks extend the same function with the already-declared fire and throw arms; they do not create another dispatcher.

- [ ] **Step 4: Insert the cache/animation/trigger/action order into the existing actor loop**

```python
def _run_actor_action(game, index, actor, flags):
    if actor.anim_action_type and actor.hot_point_id != -1:
        refresh_hot_point(game, index)
    if flags & AF_ANIMATED:
        gere_anim(game, index)
        if game.mode is not GameMode.PLAY:
            return False
    if flags & AF_TRIGGER:
        gere_dec(game, index)
    if actor.anim_action_type:
        gere_frappe(game, index)
    return game.mode is GameMode.PLAY
```

Extend `_PURITY_PROBE` to import `PyAitD.anim_action` and keep the same forbidden-module set.

- [ ] **Step 5: Run pure combat, ordering, and layer tests**

Run: `.venv/bin/pytest tests/test_anim_action.py tests/test_playworld.py -q`

Expected: PASS, including action `3` and `11` rejection tests and state-8 no-op.

- [ ] **Step 6: Revert the runner call from `_anim_pass`, confirm timing/publication integration turns red, restore, and commit**

```bash
git add PyAitD/anim_action.py PyAitD/playworld.py tests/test_anim_action.py tests/test_playworld.py
git commit -m "feat: publish melee animation hits"
```

---

### Task 6: Arm HIT/FIRE/THROW and launch thrown actors

**Files:**
- Modify: `PyAitD/life_ops.py:102-110,373-377,516-520`
- Modify: `PyAitD/anim_action.py`
- Modify: `tests/test_life_ops.py`
- Modify: `tests/test_anim_action.py`

**Interfaces:**
- Consumes: `init_anim`, `read_s16`, `eval_var`, `check_hard_col`, `put_at_objet`, `remove_from_inventory`, `spawn_stage_actors` through the existing request flag, and `init_real_value`.
- Produces: exact opcode setup plus throw states 6 and 7. State 6 sets `flag_genere_aff_list=1`; the normal end-of-tick spawn pass creates the actor consumed by state 7.

- [ ] **Step 1: Add accepted/rejected opcode tests with exact byte consumption**

```python
def test_hit_fire_throw_arm_only_when_init_anim_accepts(data_dir, monkeypatch):
    game = init_game(data_dir)
    actor_idx = game.current_camera_target_actor
    actor = game.actors[actor_idx]

    accepted = iter((0, 1, 1, 1))
    calls = []
    monkeypatch.setattr(
        "PyAitD.life_ops.init_anim",
        lambda current, anim, kind, nxt: calls.append((anim, kind, nxt)) or next(accepted),
    )

    _run(game, 16, 100, 2, 3, 40, -1, 10, 101, 11, actor=actor_idx)
    assert actor.anim_action_type == 0
    _run(game, 16, 100, 2, 3, 40, -1, 10, 101, 11, actor=actor_idx)
    assert (actor.anim_action_type, actor.anim_action_anim, actor.anim_action_frame) == (1, 100, 2)
    assert (actor.hot_point_id, actor.anim_action_param, actor.hit_force) == (3, 40, 10)

    _run(game, 53, 200, 4, 5, 60, 12, 201, 11, actor=actor_idx)
    assert (actor.anim_action_type, actor.hot_point_id, actor.hit_force) == (4, 5, 12)

    thrown_idx = 13
    gamma = game.world_objects[thrown_idx].gamma
    _run(game, 76, 300, 6, 7, thrown_idx, 0, 14, 301, 11, actor=actor_idx)
    assert (actor.anim_action_type, actor.anim_action_param) == (6, thrown_idx)
    assert game.world_objects[thrown_idx].gamma == gamma - 0x100
    assert game.world_objects[thrown_idx].found_flag & 0x1000
    assert calls == [(100, 0, 101), (100, 0, 101), (200, 2, 201), (300, 2, 301)]
```

Use a separate rejected case for each opcode and assert all operands were consumed by placing `LM_END` immediately after them.

- [ ] **Step 2: Run the opcode tests and confirm current stubs fail state assertions**

Run: `.venv/bin/pytest tests/test_life_ops.py -q`

Expected: FAIL because the stubs never arm fire or throw.

- [ ] **Step 3: Replace the three stubs with exact setup code**

```python
def op_hit(vm):
    anim = read_s16(vm); frame = read_s16(vm); group = read_s16(vm)
    radius = read_s16(vm); force = eval_var(vm); next_anim = read_s16(vm)
    if init_anim(vm.actor, anim, 0, next_anim):
        vm.actor.anim_action_anim = anim
        vm.actor.anim_action_frame = frame
        vm.actor.anim_action_type = 1
        vm.actor.anim_action_param = radius
        vm.actor.hot_point_id = group
        vm.actor.hit_force = force


def op_fire(vm):
    anim, frame, group, radius, force, next_anim = (read_s16(vm) for _ in range(6))
    if init_anim(vm.actor, anim, 2, next_anim):
        vm.actor.anim_action_anim = anim
        vm.actor.anim_action_frame = frame
        vm.actor.anim_action_type = 4
        vm.actor.anim_action_param = radius
        vm.actor.hot_point_id = group
        vm.actor.hit_force = force


def op_throw(vm):
    anim, frame, group, object_idx, rotated, force, next_anim = (
        read_s16(vm) for _ in range(7)
    )
    if init_anim(vm.actor, anim, 2, next_anim):
        vm.actor.anim_action_anim = anim
        vm.actor.anim_action_frame = frame
        vm.actor.anim_action_type = 6
        vm.actor.anim_action_param = object_idx
        vm.actor.hot_point_id = group
        vm.actor.hit_force = force
        if rotated == 0:
            vm.game.world_objects[object_idx].gamma -= 0x100
        vm.game.world_objects[object_idx].found_flag |= 0x1000
```

- [ ] **Step 4: Add tests for obstructed placement and state 6 -> spawn -> state 7 launch**

```python
def test_throw_setup_requests_normal_spawn_then_launches(data_dir, monkeypatch):
    game = init_game(data_dir)
    thrower_idx = game.current_camera_target_actor
    thrower = game.actors[thrower_idx]
    object_idx = 13
    world = game.world_objects[object_idx]
    world.body = 1
    thrower.anim_action_type = WAIT_ANIM_THROW
    thrower.anim_action_anim = thrower.anim
    thrower.anim_action_frame = thrower.frame
    thrower.anim_action_param = object_idx
    thrower.hot_point[:] = [0, 0, 0]

    monkeypatch.setattr("PyAitD.anim_action.check_hard_col", lambda *args: [])
    gere_frappe(game, thrower_idx)
    assert thrower.anim_action_type == WAIT_FRAME_THROW
    assert game.flag_genere_aff_list == 1
    assert (world.stage, world.room) == (thrower.stage, thrower.room)

    spawn_stage_actors(game)
    game.flag_genere_aff_list = 0
    gere_frappe(game, thrower_idx)
    thrown = game.actors[world.obj_index]
    assert thrower.anim_action_type == 0
    assert thrown.anim_action_type == THROW_OBJECT
    assert (thrown.speed, thrown.hit_force, thrown.hot_point_id) == (3000, thrower.hit_force, -1)
    assert thrown.speed_change.num_steps == 60
    assert world.alpha == thrower.index_in_world
```

- [ ] **Step 5: Implement states 6 and 7 using the thrown world's body**

Add these helpers and dispatch state 6 to `_prepare_throw` only when the throw
animation matches, then state 7 to `_launch_throw`:

```python
def _raw_body_zv(game, object_idx):
    world = game.world_objects[object_idx]
    if world.body == -1:
        raise ValueError(f"thrown object {object_idx} has no body")
    return list(game.assets.body(world.body).zv)


def _place_thrown_actor(game, actor_idx, x, y, z, raw):
    actor = game.actors[actor_idx]
    actor.room_x = actor.world_x = x
    actor.room_y = actor.world_y = y
    actor.room_z = actor.world_z = z
    actor.zv = [raw[0]+x, raw[1]+x, raw[2]+y, raw[3]+y, raw[4]+z, raw[5]+z]


def _prepare_throw(game, thrower_idx):
    thrower = game.actors[thrower_idx]
    object_idx = thrower.anim_action_param
    world = game.world_objects[object_idx]
    raw = _raw_body_zv(game, object_idx)
    x = thrower.room_x + thrower.hot_point[0] + thrower.step_x
    y = thrower.room_y + thrower.hot_point[1] + thrower.step_y
    z = thrower.room_z + thrower.hot_point[2] + thrower.step_z
    cube = [raw[0]+x, raw[1]+x, raw[2]+y, raw[3]+y, raw[4]+z, raw[5]+z]
    room = game.rooms_of_floor(game.current_floor)[thrower.room]
    if check_hard_col(cube, room.hard_cols):
        thrower.anim_action_type = 0
        put_at_objet(game, object_idx, thrower.index_in_world)
        return
    if thrower.frame != thrower.anim_action_frame:
        return
    thrower.anim_action_type = WAIT_FRAME_THROW
    remove_from_inventory(game, object_idx)
    world.x, world.y, world.z = x, y, z
    world.room, world.stage = thrower.room, thrower.stage
    world.alpha, world.beta = thrower.alpha, thrower.beta + 0x200
    world.found_flag &= ~0x4000
    world.flags |= 0x85
    world.flags &= ~AF_SPECIAL
    game.flag_genere_aff_list = 1


def _launch_throw(game, thrower_idx):
    thrower = game.actors[thrower_idx]
    thrower.anim_action_type = 0
    object_idx = thrower.anim_action_param
    world = game.world_objects[object_idx]
    if world.obj_index == -1:
        return
    x = thrower.room_x + thrower.hot_point[0] + thrower.step_x
    y = thrower.room_y + thrower.hot_point[1] + thrower.step_y
    z = thrower.room_z + thrower.hot_point[2] + thrower.step_z
    thrown = game.actors[world.obj_index]
    _place_thrown_actor(game, world.obj_index, x, y, z, _raw_body_zv(game, object_idx))
    thrown.object_type |= AF_ANIMATED
    thrown.object_type &= ~AF_BOXIFY
    world.x, world.y, world.z = x, y, z
    world.alpha = thrower.index_in_world
    thrown.dyn_flags = 0
    thrown.anim_action_type = THROW_OBJECT
    thrown.anim_action_param = 100
    thrown.hit_force = thrower.hit_force
    thrown.hot_point_id = -1
    thrown.speed = 3000
    init_real_value(0, thrown.speed, 60, thrown.speed_change, game.timer)
```

Do not call `spawn_stage_actors` from `gere_frappe`; the existing end-of-tick gate owns it.

- [ ] **Step 6: Run setup/launch tests, perform revert-red checks, and commit**

Run: `.venv/bin/pytest tests/test_life_ops.py tests/test_anim_action.py -q`

```bash
git add PyAitD/life_ops.py PyAitD/anim_action.py tests/test_life_ops.py tests/test_anim_action.py
git commit -m "feat: arm combat and launch thrown objects"
```

---

### Task 7: Port the FITD firearm volume sweep

**Files:**
- Modify: `PyAitD/anim_action.py`
- Modify: `tests/test_anim_action.py`

**Interfaces:**
- Consumes: `rotate_step`, `check_hard_col`, `adjust_zv_between_rooms`, `cube_intersect`, current-floor room hard columns, and actor slot order.
- Produces: `check_line_projection_with_actors(game, actor_idx, x, y, z, beta, room, param) -> tuple[int, int, int, int]` and fire states 4/5.

- [ ] **Step 1: Add sweep termination, slot order, cross-room, and impact tests**

```python
def test_fire_sweep_preserves_no_hard_collision_termination(monkeypatch, data_dir):
    game, shooter_idx, victim_idx = _live_actors(data_dir, 2)
    monkeypatch.setattr("PyAitD.anim_action.check_hard_col", lambda *args: [])
    result = check_line_projection_with_actors(game, shooter_idx, 0, 0, 0, 0, 0, 50)
    assert result[0] == -1
    assert result[1:] == (0, 0, 0)
    assert game.actors[victim_idx].hit_by == -1


def test_fire_sweep_returns_first_live_non_special_slot(monkeypatch, data_dir):
    game, shooter_idx, first_idx, second_idx = _live_actors(data_dir, 3)
    monkeypatch.setattr("PyAitD.anim_action.check_hard_col", lambda *args: [object()])
    game.actors[first_idx].object_type |= AF_SPECIAL
    game.actors[second_idx].zv = [-100, 100, -100, 100, -100, 100]
    hit, x, y, z = check_line_projection_with_actors(
        game, shooter_idx, 0, 0, -100, 0, game.actors[shooter_idx].room, 50,
    )
    assert hit == second_idx
    assert (x, y, z) == (0, 0, -100)
```

Add a parameterized boundary test that exits at both `20001` and `-20001`, plus a two-room case that asserts `adjust_zv_between_rooms` is called before intersection.

- [ ] **Step 2: Run sweep tests and verify the helper is absent**

Run: `.venv/bin/pytest tests/test_anim_action.py -k 'fire or line_projection' -q`

Expected: collection or assertion FAIL.

- [ ] **Step 3: Implement the integer room-space sweep**

```python
def check_line_projection_with_actors(game, actor_idx, x, y, z, beta, room, param):
    local = [x-param, x+param, y-param, y+param, z-param, z+param]
    move_z, move_x = rotate_step(beta, param * 2, 0)
    impact_x, impact_z = x, z
    while True:
        local[0] += move_x; local[1] += move_x
        local[4] += move_z; local[5] += move_z
        impact_x, impact_z = x, z
        x += move_x; z += move_z
        if x > 20000 or x < -20000 or z > 20000 or z < -20000:
            return (-1, impact_x, y, impact_z)
        hard_cols = game.rooms_of_floor(game.current_floor)[room].hard_cols
        if not check_hard_col(local, hard_cols):
            return (-1, impact_x, y, impact_z)
        for other_idx, other in enumerate(game.actors):
            if other.index_in_world == -1 or other_idx == actor_idx:
                continue
            if other.object_type & AF_SPECIAL:
                continue
            candidate = local if other.room == room else adjust_zv_between_rooms(
                game, local, room, other.room,
            )
            if cube_intersect(candidate, other.zv):
                return (other_idx, impact_x, y, impact_z)
```

- [ ] **Step 4: Add fire states 4 and 5 to the existing dispatcher**

Add these branches to `gere_frappe`; do not add muzzle-flash or impact actors:

```python
def _gere_fire(game, actor_idx, actor, action):
    if action == WAIT_TIR_ANIM:
        if actor.anim == actor.anim_action_anim and actor.frame == actor.anim_action_frame:
            actor.anim_action_type = DO_TIR
        return
    if action == DO_TIR:
        victim_idx, impact_x, impact_y, impact_z = check_line_projection_with_actors(
            game, actor_idx,
            actor.room_x + actor.hot_point[0],
            actor.room_y + actor.hot_point[1],
            actor.room_z + actor.hot_point[2],
            actor.beta - 0x100, actor.room, actor.anim_action_param,
        )
        if victim_idx != -1:
            actor.hot_point[:] = [
                impact_x - actor.room_x,
                impact_y - actor.room_y,
                impact_z - actor.room_z,
            ]
            _publish_hit(game, actor_idx, victim_idx)
        actor.anim_action_type = 0
```

- [ ] **Step 5: Run combat and fixed-point regressions, revert the no-hard-col branch to prove its test red, restore, and commit**

Run: `.venv/bin/pytest tests/test_anim_action.py tests/test_world.py tests/test_actors.py -q`

```bash
git add PyAitD/anim_action.py tests/test_anim_action.py
git commit -m "feat: port firearm collision sweep"
```

---

### Task 8: Complete in-flight throw and stopped placement

**Files:**
- Modify: `PyAitD/anim_action.py`
- Modify: `tests/test_anim_action.py`

**Interfaces:**
- Consumes: `check_object_col`, `check_hard_col`, `point_in_zone`, `rotate_step`, raw body ZV, room scene zones, and CVar index 11 (`REVERSE_OBJECT`).
- Produces: `throw_stopped_at(game, actor_idx, x, z) -> None` and complete action state 9.

- [ ] **Step 1: Add stopped-placement and flight collision tests**

```python
def _thrown_game(data_dir):
    game = init_game(data_dir)
    actor_idx = next(
        i for i, actor in enumerate(game.actors)
        if actor.index_in_world >= 0 and i != game.current_camera_target_actor
    )
    actor = game.actors[actor_idx]
    actor.anim_action_type = THROW_OBJECT
    game.world_objects[actor.index_in_world].alpha = game.current_world_target
    return game, actor_idx


def test_throw_stopped_at_searches_back_and_commits_found_state(monkeypatch, data_dir):
    game, actor_idx = _thrown_game(data_dir)
    checks = iter(([object()], [object()], []))
    monkeypatch.setattr("PyAitD.anim_action.check_hard_col", lambda *args: next(checks))
    throw_stopped_at(game, actor_idx, 1000, 2000)
    actor = game.actors[actor_idx]
    world = game.world_objects[actor.index_in_world]
    assert actor.anim_action_type == 0
    assert (actor.speed, actor.gamma, actor.step_x, actor.step_z) == (0, 0, 0, 0)
    assert world.found_flag & 0x4000
    assert not world.found_flag & 0x1000


def test_in_flight_ignores_original_thrower(monkeypatch, data_dir):
    game, actor_idx = _thrown_game(data_dir)
    thrown = game.actors[actor_idx]
    original_world = game.world_objects[thrown.index_in_world].alpha
    original_actor = game.world_objects[original_world].obj_index
    monkeypatch.setattr("PyAitD.anim_action.check_object_col", lambda *args: (original_actor,))
    gere_frappe(game, actor_idx)
    assert thrown.hit == -1


def test_in_flight_reflects_from_reverse_object(monkeypatch, data_dir):
    game, actor_idx = _thrown_game(data_dir)
    reverse_world = game.cvars[11]
    reverse_actor = game.world_objects[reverse_world].obj_index
    monkeypatch.setattr("PyAitD.anim_action.check_object_col", lambda *args: (reverse_actor,))
    beta = game.actors[actor_idx].beta
    gere_frappe(game, actor_idx)
    assert game.actors[actor_idx].beta == beta + 0x200
    assert game.world_objects[game.actors[actor_idx].index_in_world].alpha == reverse_world
```

Add separate tests for ordinary actor publication, first containing zone type 0/10, hard collision, the 2,000-unit Y band/reachability adjustment, and the final world-coordinate update when the swept point reaches the actor ZV.

- [ ] **Step 2: Run state-9 tests and confirm they fail**

Run: `.venv/bin/pytest tests/test_anim_action.py -k 'throw or flight or stopped' -q`

Expected: FAIL because state 9 and `throw_stopped_at` are absent.

- [ ] **Step 3: Port backward stopped placement exactly**

```python
def throw_stopped_at(game, actor_idx, x, z):
    actor = game.actors[actor_idx]
    raw = _raw_body_zv(game, actor.index_in_world)
    x2, y2, z2 = x, (actor.room_y // 2000) * 2000, z
    step = 0
    room = game.rooms_of_floor(game.current_floor)[actor.room]
    while True:
        move_z, move_x = rotate_step(actor.beta + 0x200, 0, -step)
        x2, z2 = x + move_x, z + move_z
        cube = [raw[0]+x2, raw[1]+x2, raw[2]+y2, raw[3]+y2, raw[4]+z2, raw[5]+z2]
        if check_hard_col(cube, room.hard_cols):
            step += 100
            continue
        if y2 < -500:
            reachable = list(cube)
            reachable[2] += 100; reachable[3] += 100
            if not check_hard_col(reachable, room.hard_cols):
                y2 += 2000
                continue
        break
    actor.world_x = actor.room_x = x2
    actor.world_y = actor.room_y = y2
    actor.world_z = actor.room_z = z2
    actor.step_x = actor.step_z = 0
    actor.anim_action_type = actor.speed = actor.gamma = 0
    actor.zv = [raw[0]+x2, raw[1]+x2, raw[2]+y2, raw[3]+y2, raw[4]+z2, raw[5]+z2]
    world = game.world_objects[actor.index_in_world]
    world.found_flag |= 0x4000
    world.found_flag &= ~0x1000
```

- [ ] **Step 4: Port state 9 as one helper-backed branch**

Compute the actor's actual position and origin-relative ZV; sweep in 100-unit increments with `move_z, move_x = rotate_step(actor.beta, 0, -step)`. At each cube:

```python
def _check_throw_step(
    game, actor_idx, actor, world, room, cube, x2, y2, z2,
    actual_x, actual_y, actual_z, old_x, old_y, old_z, raw_zv,
):
    collisions = check_object_col(game, actor_idx, cube)
    effective = len(collisions)
    for touched_idx in collisions:
        touched_world = game.actors[touched_idx].index_in_world
        if touched_world == world.alpha:
            effective -= 1
            world.x, world.y, world.z = actual_x, actual_y, actual_z
            return True
        if touched_world == game.cvars[11]:
            world.alpha = game.cvars[11]
            actor.beta += 0x200
            _place_thrown_actor(game, actor_idx, old_x, old_y, old_z, raw_zv)
            world.x, world.y, world.z = actual_x, actual_y, actual_z
            return True
        _publish_hit(game, actor_idx, touched_idx)
    if effective:
        throw_stopped_at(game, actor_idx, old_x, old_z)
        return True
    zone = next(
        (item for item in room.sce_zones if point_in_zone(x2, y2, z2, item)),
        None,
    )
    if zone is not None and zone.type in (0, 10):
        throw_stopped_at(game, actor_idx, old_x, old_z)
        return True
    if check_hard_col(cube, room.hard_cols):
        actor.hot_point[:] = [0, 0, 0]
        throw_stopped_at(game, actor_idx, old_x, old_z)
        return True
    return False
```

The original-thrower branch decrements `effective` before returning, matching FITD's observable result. Continue only while the swept X/Z remains outside the current actor ZV expanded by 100; otherwise commit `world.x/y/z = actual_x/y/z`. Sound calls and background inscription remain omitted.

- [ ] **Step 5: Run the complete throw suite and the shared venue proof**

Run: `.venv/bin/pytest tests/test_anim_action.py -q && make prove-combat`

Expected: PASS; Phase-A proof still reports combat pending until Task 11 upgrades it.

- [ ] **Step 6: Revert reflection and stopped-placement branches independently, confirm their tests turn red, restore, and commit**

```bash
git add PyAitD/anim_action.py tests/test_anim_action.py
git commit -m "feat: complete thrown object flight"
```

---

### Task 9: Convert game-over flags into a timed modal

**Files:**
- Modify: `PyAitD/effects.py:6-75`
- Modify: `PyAitD/game.py:109-205`
- Modify: `PyAitD/playworld.py:113-167`
- Create: `tests/test_game_over.py`

**Interfaces:**
- Consumes: existing modal mapping and `flag_game_over` set by `LM_GAME_OVER`/`LM_WAIT_GAME_OVER`.
- Produces: `GameOver(delay_units: int = 120)`, `GameMode.GAME_OVER`, and end-of-LIFE-pass modal handoff.

- [ ] **Step 1: Test actor-loop completion, handoff position, and later tick pause**

```python
# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.effects import GameMode, GameOver


def test_game_over_finishes_current_life_pass_then_opens_modal(data_dir, monkeypatch):
    import PyAitD.playworld as playworld
    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    live = [i for i, actor in enumerate(game.actors) if actor.index_in_world >= 0]
    seen = []

    def fake_run_life(current, frame):
        seen.append(frame.owner_idx)
        if frame.owner_idx == live[0]:
            current.flag_game_over = 1
        return True

    monkeypatch.setattr(playworld, "run_life", fake_run_life)
    monkeypatch.setattr(playworld, "life_gate", lambda actor: actor.index_in_world >= 0)
    assert play_tick(game, floor, InputBuffer()) is False
    assert seen == live
    assert game.flag_game_over == 0
    assert game.mode is GameMode.GAME_OVER
    assert game.active_modal == GameOver(120)
    timer = game.timer
    assert play_tick(game, floor, InputBuffer()) is False
    assert game.timer == timer
```

- [ ] **Step 2: Run the test and verify the effect is absent**

Run: `.venv/bin/pytest tests/test_game_over.py -q`

Expected: collection FAIL importing `GameOver`.

- [ ] **Step 3: Add the effect, mode, mapping, and request state**

```python
class GameMode(Enum):
    PLAY = auto()
    FOUND = auto()
    INVENTORY = auto()
    READING = auto()
    GAME_OVER = auto()


@dataclass(frozen=True)
class GameOver:
    delay_units: int = 120


ModalEffect = ShowFound | OpenInventory | ReadText | ShowPicture | GameOver
MODAL_MODE[GameOver] = GameMode.GAME_OVER
```

Keep `Game.restart_requested = False` in engine/session state, not in `ui.py`.

- [ ] **Step 4: Insert handoff after the complete LIFE loop and before transitions**

```python
def _handoff_game_over(game):
    if not game.flag_game_over:
        return True
    game.flag_game_over = 0
    game.open_modal(GameOver())
    return False
```

Call `_handoff_game_over(game)` immediately after the existing LIFE actor loop
and return `False` when it does; keep the existing floor-transition branch next.

Do not break the LIFE loop when `flag_game_over` becomes true; FITD checks it only after the loop.

- [ ] **Step 5: Run focused and full headless tests, revert the handoff to prove the scheduling test red, restore, and commit**

Run: `.venv/bin/pytest tests/test_game_over.py tests/test_playworld.py -q && .venv/bin/pytest -q`

```bash
git add PyAitD/effects.py PyAitD/game.py PyAitD/playworld.py tests/test_game_over.py
git commit -m "feat: schedule game over as a modal"
```

---

### Task 10: Present game over and reconstruct a fresh session

**Files:**
- Modify: `PyAitD/ui.py:70-100,239-360`
- Modify: `PyAitD/__main__.py:183-411`
- Modify: `tests/test_ui_render.py`
- Modify: `tests/test_runtime_modes.py`
- Modify: `tests/test_game_over.py`

**Interfaces:**
- Consumes: pygame-ce `Surface`, `SRCALPHA`, `Font.render`, `Surface.blit`, the existing logical RGB-frame conversion, `FloorStart`, and `enter_floor_start`.
- Produces:
  - `ModalSession.elapsed_ms: int` reset on effect identity change.
  - `render_game_over(scene_frame, ready) -> np.ndarray`.
  - `restart_session(old_game) -> new_game` with no `Floor` I/O.
  - GAME_OVER branches in command, mouse, render, and `run`.

- [ ] **Step 1: Add pure presentation and whole-frame accessibility tests**

```python
def test_game_over_locked_frame_is_identical_and_ready_frame_is_overlayed():
    pygame.font.init()
    source = np.arange(320 * 200 * 3, dtype=np.uint8).reshape((200, 320, 3))
    locked = render_game_over(source, ready=False)
    ready = render_game_over(source, ready=True)
    assert locked is source
    assert np.array_equal(locked, source)
    assert not np.array_equal(ready, source)
    assert np.array_equal(source, locked)


def test_game_over_accepts_any_left_click_only_after_delay(data_dir):
    game = init_game(data_dir)
    game.open_modal(GameOver())
    session = ModalSession()
    session.reset_for(game.active_modal)
    assert route_mouse(game, session, (0, 0))
    assert game.restart_requested is False
    session.elapsed_ms = 120 * 1000 // 60
    assert route_mouse(game, session, (319, 199))
    assert game.restart_requested is True
```

Add command cases for ACCEPT, CANCEL, and OPEN_INVENTORY-as-ACCEPT, plus a locked rejection case for each.

- [ ] **Step 2: Run the UI/runtime tests under dummy SDL and verify missing branches fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_game_over.py tests/test_ui_render.py tests/test_runtime_modes.py -q`

Expected: FAIL because GAME_OVER is unroutable/unrenderable.

- [ ] **Step 3: Move elapsed time to the modal session and add the pure presenter**

```python
@dataclass
class ModalSession:
    found: FoundPresenter = field(default_factory=FoundPresenter)
    inventory: InventoryPresenter = field(default_factory=InventoryPresenter)
    reading: ReadingPresenter = field(default_factory=ReadingPresenter)
    elapsed_ms: int = 0
    last_effect: object = field(default=None, repr=False)

    def reset_for(self, effect):
        if effect is self.last_effect:
            return
        self.last_effect = effect
        self.elapsed_ms = 0
        self.found = FoundPresenter(
            FoundResult.LEAVE if getattr(effect, "forced_refuse", False) else FoundResult.TAKE
        )
        self.inventory = InventoryPresenter()
        self.reading = ReadingPresenter()


def render_game_over(scene_frame, ready):
    if not ready:
        return scene_frame
    surface = _to_surface(scene_frame.copy())
    shade = pygame.Surface((320, 200), flags=pygame.SRCALPHA)
    shade.fill((0, 0, 0, 170))
    surface.blit(shade, (0, 0))
    title = _font(40).render("Game Over", True, (255, 238, 198))
    prompt = _font(18).render("Click to restart", True, (255, 255, 255))
    surface.blit(title, title.get_rect(center=(160, 82)))
    surface.blit(prompt, prompt.get_rect(center=(160, 126)))
    return _to_frame(surface)
```

Update `_auto_dismiss_picture` to read `session.elapsed_ms`, and update the non-PLAY branch in `run` to increment that field.

- [ ] **Step 4: Add explicit GAME_OVER router and renderer branches**

```python
def _route_game_over_command(game, session, modal_command):
    ready = session.elapsed_ms >= game.active_modal.delay_units * 1000 // 60
    if ready and modal_command in (Command.ACCEPT, Command.CANCEL):
        game.restart_requested = True
    return True
```

`route_mouse` uses the same readiness predicate and sets the request for every non-`None` logical position. `render_active_mode` calls `render_game_over(scene_frame, ready)`. These branches precede the final exhaustive `RuntimeError`.

- [ ] **Step 5: Add restart reconstruction tests with fresh-state and identity assertions**

```python
def test_restart_session_rebuilds_state_and_preserves_session_choices(data_dir):
    old = init_game(data_dir, hero=1)
    enter_combat_venue(old)
    old.input_mode = InputMode.KEYBOARD
    old.trace = object()
    old.vars[21] = 0
    old.inventory_count[0] = 1
    old.restart_requested = True

    new = restart_session(old)

    assert new is not old
    assert new.floor_start == COMBAT_VENUE
    assert new.cvars[8] == 1
    assert new.input_mode is InputMode.KEYBOARD
    assert new.trace is old.trace
    assert new.vars[21] == 20
    assert new.inventory_count == [0, 0]
    assert new.active_modal is None
    assert new.restart_requested is False
    assert (new.current_floor, new.current_room, new.num_camera) == (5, 4, -1)
```

Also test initial floor 0. Spy `init_game` and `enter_floor_start` in `restart_session`; assert one call each and no `Floor` construction.

- [ ] **Step 6: Implement the exact reconstruction sequence**

```python
def restart_session(old_game):
    hero = old_game.cvars[8]
    input_mode = old_game.input_mode
    trace = old_game.trace
    data_dir = old_game._data_dir
    floor_start = old_game.floor_start
    new_game = init_game(data_dir, hero=hero)
    new_game.input_mode = input_mode
    new_game.trace = trace
    from PyAitD.interaction import sync_player_track_mode
    sync_player_track_mode(new_game)
    enter_floor_start(new_game, floor_start)
    new_game.floor_start = floor_start
    return new_game
```

- [ ] **Step 7: Make `run` own the atomic restart and Floor load**

Immediately after routing input/commands and before any tick or composition:

```python
def _restart_branch(game, renderer):
    if not game.restart_requested:
        return None
    try:
        new_game = restart_session(game)
        new_floor = Floor(new_game._data_dir, new_game.current_floor)
    except PakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return (None, None, None, None, 0, [], None, None, None, 2)
    game = new_game
    floor = new_floor
    session = ModalSession()
    input_buffer = InputBuffer()
    accumulator = 0
    draw_list = []
    hover = None
    game.num_camera = game.new_num_camera
    game.flag_init_view = 0
    scene_frame, draw_list = _scene_frame(game, floor, renderer)
    last = pygame.time.get_ticks()
    return (
        game, floor, session, input_buffer, accumulator,
        draw_list, hover, scene_frame, last, 0,
    )
```

Inline this branch in `run` so a successful tuple replacement immediately
continues the outer loop. Initialize `exit_status = 0`, return it after the
existing one-time trace/renderer cleanup, and ensure the trace object is neither
closed nor reopened during restart. Add a loop test that spies the sequence as
`restart_session -> Floor -> state reset -> _scene_frame`, with no `play_tick`
or `present` in between.

- [ ] **Step 8: Run dummy-SDL runtime tests, revert ready-click and Floor-load ordering separately, restore, and commit**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_game_over.py tests/test_ui_render.py tests/test_runtime_modes.py tests/test_play_loop.py -q`

```bash
git add PyAitD/ui.py PyAitD/__main__.py tests/test_ui_render.py tests/test_runtime_modes.py tests/test_game_over.py
git commit -m "feat: restart after accessible game over"
```

---

### Task 11: Prove real enemy death, player arms, and final milestone gates

**Files:**
- Create: `tests/test_combat_journey.py`
- Modify: `tools/prove_combat.py`
- Modify: `Makefile`
- Modify: `CONTEXT.md`
- Create: `docs/m3c-combat-proof.md`

**Interfaces:**
- Consumes: the exact shared venue, real LISTLIFE data, real HIT/FIRE/THROW opcodes, action runner, `GameOver`, `restart_session`, and all three player arm paths.
- Produces: a non-reporting `make prove-combat` gate, real health/death checkpoint evidence, updated architecture status, and a short manual checklist.

- [ ] **Step 1: Add the real enemy publication and hero damage checkpoints**

```python
# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.effects import GameMode
from PyAitD.floor import Floor
from PyAitD.game import init_game
from PyAitD.playworld import play_tick
from PyAitD.scenario import enter_combat_venue
from PyAitD.ui import InputBuffer


def _venue(data_dir):
    game = init_game(data_dir)
    enter_combat_venue(game)
    return game, Floor(data_dir, 5), game.world_objects[222].obj_index


def test_obj222_real_script_hits_and_hero_consumes_same_tick(data_dir):
    game, floor, enemy_idx = _venue(data_dir)
    hero_idx = game.current_camera_target_actor
    observed = False
    for _ in range(2400):
        before = game.vars[21]
        play_tick(game, floor, InputBuffer())
        if game.actors[hero_idx].hit_by == enemy_idx:
            observed = True
            assert game.actors[enemy_idx].hit == hero_idx
            assert game.actors[hero_idx].life in (549, 553)
            assert game.vars[21] <= before
            break
    assert observed, "obj222 never published its real scripted melee hit"
```

The pinned real-data damage path is hero LIFE `549 -> 553 -> 549`, variable 21 `20 -> 10`, and transient variable 24 `0 -> 1`. A second force-10 hit drives variable 21 to 0 and the subsequent real script selects death LIFE 39. Assert those exact checkpoints; do not set `flag_game_over` in the test.

- [ ] **Step 2: Add the complete real survival-to-restart journey**

Use actor relocation only to remove nondeterministic circling; do not write
`hit`, `hit_by`, `hit_force`, `life`, variable 21, `flag_game_over`, or
`active_modal`:

```python
def test_real_enemy_damage_reaches_game_over_and_fresh_restart(data_dir):
    game, floor, enemy_idx = _venue(data_dir)
    hero_idx = game.current_camera_target_actor
    hero = game.actors[hero_idx]
    saw_death_life = False
    for _ in range(12000):
        if game.vars[21] > 0:
            relocate_actor(
                game, enemy_idx, 5, 4,
                hero.room_x, hero.room_y, hero.room_z + 300,
            )
        play_tick(game, floor, InputBuffer())
        saw_death_life |= hero.life == 39
        if game.mode is GameMode.GAME_OVER:
            break

    assert game.vars[21] == 0
    assert saw_death_life
    assert game.active_modal == GameOver(120)

    session = ModalSession()
    session.reset_for(game.active_modal)
    frozen = np.zeros((200, 320, 3), dtype=np.uint8)
    assert render_game_over(frozen, ready=False) is frozen
    session.elapsed_ms = 1999
    route_mouse(game, session, (0, 0))
    assert game.restart_requested is False
    session.elapsed_ms = 2000
    route_mouse(game, session, (319, 199))
    assert game.restart_requested is True

    restarted = restart_session(game)
    assert restarted.floor_start == COMBAT_VENUE
    assert restarted.vars[21] == 20
    assert restarted.active_modal is None
```

Import `numpy as np`, `route_mouse`, `restart_session`, `GameOver`,
`ModalSession`, `render_game_over`, `relocate_actor`, and `COMBAT_VENUE` in the
same test file.

- [ ] **Step 3: Add deterministic player melee, firearm, and throw journeys**

Use hero body 12/animation 4, target object 222/body 234, and thrown object
13/body 9 from the original data. A local LIFE wrapper supplies one script while
delegating body/animation access to the real registry:

```python
class _OneLife:
    def __init__(self, base, words):
        self.base = base
        self.script = struct.pack(f"<{len(words)}h", *words)

    def life(self, index):
        return self.script if index == 999 else self.base.life(index)

    def __getattr__(self, name):
        return getattr(self.base, name)


def _execute_words(game, actor_idx, words):
    assets = game.assets
    game.assets = _OneLife(assets, words)
    try:
        process_life(game, actor_idx, 999)
    finally:
        game.assets = assets


def test_player_melee_executes_opcode_and_runner(data_dir, monkeypatch):
    game, _floor, victim_idx = _venue(data_dir)
    hero_idx = game.current_camera_target_actor
    hero = game.actors[hero_idx]
    hero.object_type &= ~AF_ANIMATED  # makes same real anim 4 acceptable to InitAnim
    # FITD main.cpp:4375-4386 hit(anim, frame, group, radius, force, next)
    _execute_words(game, hero_idx, [16, 4, 0, 0, 2000, -1, 10, 4, 11])
    monkeypatch.setattr("PyAitD.anim_action.check_object_col", lambda *args: (victim_idx,))
    assert hero.anim_action_type == WAIT_FRAPPE_ANIM
    gere_frappe(game, hero_idx); assert hero.anim_action_type == WAIT_FRAPPE_FRAME
    gere_frappe(game, hero_idx); assert hero.anim_action_type == FRAPPE_OK
    gere_frappe(game, hero_idx)
    assert hero.hit == victim_idx
    assert game.actors[victim_idx].hit_force == 10


def test_player_fire_executes_opcode_and_runner(data_dir, monkeypatch):
    game, _floor, victim_idx = _venue(data_dir)
    hero_idx = game.current_camera_target_actor
    hero = game.actors[hero_idx]
    hero.object_type &= ~AF_ANIMATED
    # FITD life.cpp:66-78 fire(anim, frame, group, radius, force, next)
    _execute_words(game, hero_idx, [53, 4, 0, 0, 50, 12, 4, 11])
    monkeypatch.setattr(
        "PyAitD.anim_action.check_line_projection_with_actors",
        lambda *args: (victim_idx, hero.room_x + 20, hero.room_y, hero.room_z + 30),
    )
    gere_frappe(game, hero_idx); assert hero.anim_action_type == DO_TIR
    gere_frappe(game, hero_idx)
    assert hero.hit == victim_idx
    assert game.actors[victim_idx].hit_force == 12
    assert hero.hot_point == [20, 0, 30]


def test_player_throw_executes_setup_launch_and_flight(data_dir, monkeypatch):
    game, _floor, victim_idx = _venue(data_dir)
    hero_idx = game.current_camera_target_actor
    hero = game.actors[hero_idx]
    object_idx = 13  # real floor-0 inventory candidate, body 9
    hero.object_type &= ~AF_ANIMATED
    game.inventory_table[0][0] = object_idx
    game.inventory_count[0] = 1
    # FITD life.cpp:18-36 throwObj(anim, frame, group, object, rotated, force, next)
    _execute_words(game, hero_idx, [76, 4, 0, 0, object_idx, 1, 14, 4, 11])
    monkeypatch.setattr("PyAitD.anim_action.check_hard_col", lambda *args: [])
    gere_frappe(game, hero_idx)
    spawn_stage_actors(game)
    game.flag_genere_aff_list = 0
    gere_frappe(game, hero_idx)
    thrown_idx = game.world_objects[object_idx].obj_index
    assert game.actors[thrown_idx].anim_action_type == THROW_OBJECT
    monkeypatch.setattr("PyAitD.anim_action.check_object_col", lambda *args: (victim_idx,))
    monkeypatch.setattr("PyAitD.anim_action.throw_stopped_at", lambda *args: None)
    gere_frappe(game, thrown_idx)
    assert game.actors[thrown_idx].hit == victim_idx
    assert game.actors[victim_idx].hit_force == 14
```

Keep the separate Task-8 reflection and stopped-placement tests in the final
proof set; they assert CVar 11 and final found flags without weakening this
opcode-to-runner journey.

- [ ] **Step 4: Replace the Phase-A proof report with a hard pytest gate**

Change `tools/prove_combat.py` to invoke pytest with the exact focused files and return its status:

```python
import subprocess


def main(argv):
    data = pathlib.Path(argv[0])
    env = dict(os.environ, PYAITD_DATA=str(data), SDL_VIDEODRIVER="dummy")
    return subprocess.run(
        [
            sys.executable, "-m", "pytest", "-q",
            "tests/test_scenario.py",
            "tests/test_anim_action.py",
            "tests/test_game_over.py",
            "tests/test_combat_journey.py",
        ],
        cwd=pathlib.Path(__file__).resolve().parent.parent,
        env=env,
        check=False,
    ).returncode
```

Add `import os`. The target now fails for every missing arm; remove the `combat arms: pending Phase B` line.

- [ ] **Step 5: Record the natural camera-slot observation and manual proof**

Extend `tests/test_floor_start.py` with a real hero `LM_STAGE` byte fixture, finish the ordinary floor/room/camera handoff, and assert `game.floor_start.camera_slot == game.num_camera`. Keep the expected value at 0 only if the observed floor data does so; if the real transition selects a different slot, update `op_stage` and the spec assumption with the observed FITD/data anchor.

Create `docs/m3c-combat-proof.md` with these concise operator checks:

```markdown
# M3c combat proof

Automated: `make prove-combat`.

Manual: run `make run-combat`; using mouse-only input, confirm obj222 approaches,
attacks, and can kill the hero; wait for the Game Over overlay; click anywhere
with the left button; confirm the same floor-5 venue restarts fresh. Then exercise
one melee item, one firearm, and one thrown item. Record date, hero, observed
weapon object IDs, and pass/fail here.
```

- [ ] **Step 6: Update the living architecture map only after all proof cases pass**

In `CONTEXT.md`, mark M3c done, add `anim_action.py`, `scenario.py`, `FloorStart`, GAME_OVER/restart ownership, `make run-combat`, and `make prove-combat`; remove the sentence saying combat opcodes are stubs. Keep ending/completability in M3c's successor milestone.

- [ ] **Step 7: Run every release gate and the required revert-red audit**

Run:

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest -q
make prove
make prove-m3b
make prove-mouse
make prove-combat
```

Expected: every command exits 0. For each new journey, revert the exact opcode/runner/modal branch it protects, record the observed failing test name in `docs/m3c-combat-proof.md`, then restore and rerun `make prove-combat`.

- [ ] **Step 8: Commit the completed milestone evidence**

```bash
git add tests/test_combat_journey.py tools/prove_combat.py Makefile CONTEXT.md docs/m3c-combat-proof.md
git commit -m "test: prove M3c combat end to end"
```

---

## Final Self-Review Checklist

- Phase A lands and passes independently before `anim_action.py` exists.
- Every spec requirement maps to a task: evalVar/venue (1-3), shared pose/timing/melee (4-5), opcode/throw setup (6), fire (7), throw flight (8), game over/restart (9-10), real enemy/player/proof (11).
- HIT/FIRE/THROW signatures and action values match FITD; melee uses `1 -> 10 -> 2`, not the earlier incorrect `1 -> 2 -> 3` transcription.
- State 6 raises the port's existing active-list request because FITD calls `GenereActiveList` unconditionally.
- `restart_session` performs no Floor I/O; only `run` loads the floor after replacing the game.
- The locked game-over renderer returns the original frame object and all restart input is whole-frame accessible.
- No task adds pygame to simulation, duplicates skeleton transforms, invents damage, or implements the ending.
- No placeholder instruction or undefined cross-task interface remains.
