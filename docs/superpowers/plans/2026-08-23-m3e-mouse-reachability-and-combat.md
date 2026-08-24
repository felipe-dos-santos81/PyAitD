# M3e Mouse Reachability and Combat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every implemented M3 player capability reachable with one left mouse button, including inventory entry and the measured force-2 throw at the supported combat venue.

**Architecture:** Keep simulation changes in the existing pygame-free owners: `tracks.py` performs bounded direct facing, `interaction.py` validates and delegates attacks, and `game.py` exposes the existing single-object activation body needed by throw release. `ui.py` only draws and hit-tests the HUD/cursors; `__main__.py` owns the shared availability predicate, unified pointer resolver, routing, event pump, and presentation order. A new pygame-free contract module plus real-data event-pump journeys enforce the mouse routes without adding a dependency.

**Tech Stack:** Python 3.12, pygame-ce 2.5.8, ModernGL, NumPy, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-23-mouse-only-combat-and-invariant-design.md`

## Global Constraints

- `# SPDX-License-Identifier: GPL-2.0-only` is the first line of every Python file.
- Dependencies remain fixed: pygame-ce, ModernGL, NumPy, pytest. Add nothing.
- This plan implements M3e only. Do not fold M4 menus, persistence, audio, sequences, packaging, or ending closure into it.
- FITD behavior is authoritative at `/Users/felipe.dos.santos/code/theirs/FITD/FitdLib/`; cite the exact source line in a test comment when correcting a golden.
- Preserve `_turn_toward` and all five existing callers unchanged.
- Combat must be armed through `choose_inventory_action`; pointer code never writes animation-action, hit, health, or LIFE state directly.
- `interaction.py`, `mouse_contract.py`, `playworld.py`, `anim_action.py`, `life_ops.py`, and `effects.py` import no pygame, ModernGL, rendering, or event-pump modules. Do not widen `interaction.py`'s deferred `FoundResult` type import into UI behavior.
- `ui.py` never mutates game, world, actor, inventory, navigation, or LIFE state.
- `__main__.py` remains the only event pump, game/floor replacement authority, and presentation owner.
- One top-level resolver drives PLAY hover and PLAY clicks, including the inventory HUD.
- Every player decision requires at most one left click. Add no right-click, double-click, drag, hold, timing gesture, or key-and-mouse chord.
- Tests touching pygame/rendering run with `SDL_VIDEODRIVER=dummy`; the focused proof also sets `SDL_AUDIODRIVER=dummy`.
- Real-data probes use a fresh game per object/action and the `data_dir` fixture; never derive a golden by guessing.
- Never mass-reformat. The test suite is the only code-quality gate.
- After every task run its focused test and `.venv/bin/pytest -q`; after non-trivial production changes also run `make prove`.

## File map

| File | Responsibility in M3e |
|---|---|
| `PyAitD/tracks.py` | Add the isolated, bounded `face_toward` helper; leave interpolated track turning intact. |
| `PyAitD/interaction.py` | Own combat-target validation, action discovery, and the stop/face/delegate attack transaction. |
| `PyAitD/game.py` | Extract the current one-object activation body so normal regeneration and throw release share it. |
| `PyAitD/anim_action.py` | Activate a released thrown object before later LIFE evaluation in the same tick. |
| `PyAitD/scenario.py` | Provide the deterministic object-38 mouse-combat proof start without changing the M3c venue. |
| `PyAitD/ui.py` | Own `PlayLayout`, HUD drawing, HUD hit geometry, and five distinct cursor presentations. |
| `PyAitD/__main__.py` | Own HUD availability, unified resolution/routing, event-pump wiring, and HUD/cursor presentation order. |
| `PyAitD/mouse_contract.py` | Declare current player capabilities, one mouse route each, mode coverage, and legacy command decisions without importing pygame. |
| `tests/test_tracks.py` | Exhaustive direct-facing and convergence-bound tests. |
| `tests/test_interaction.py` | Combat predicate, discovery, revalidation, conversion, and delegation tests. |
| `tests/test_game.py` | Single-object activation extraction tests. |
| `tests/test_anim_action.py` | Throw release activates its object without manual spawning. |
| `tests/test_scenario.py`, `tests/test_main.py` | Pin the separate mouse-combat fixture and CLI route. |
| `tests/test_ui_mouse.py` | HUD rectangle and exclusive-edge hit tests. |
| `tests/test_ui_render.py` | Pure HUD rendering and five distinct cursor outputs. |
| `tests/test_play_loop.py` | Resolver priority/payloads, HUD routing, attack routing, and existing click-regression coverage. |
| `tests/test_runtime_modes.py` | Shared HUD availability and run-loop presentation/pointer behavior. |
| `tests/test_mouse_only.py` | Registry exhaustiveness, purity, real-data action measurement, and three synthetic-mouse event-pump journeys. |
| `Makefile` | Add `run-mouse-combat` and the distinct `prove-mouse-only` pytest target. |
| `docs/m3e-mouse-only-proof.md` | Record automated results and the required windowed single-button evidence. |
| `CONTEXT.md` | Mark M3e landed and document its module/proof boundaries. |

---

### Task 1: Bounded direct facing without track-runner impact

**Files:**
- Modify: `PyAitD/tracks.py:42-49`
- Test: `tests/test_tracks.py:1-260`

**Interfaces:**
- Consumes: `cap_objet(x1, z1, beta, x2, z2) -> int`, `Actor.rotate`, and room-space actor coordinates.
- Produces: `face_toward(actor, x: int, z: int, *, max_steps: int = 256) -> None`.

- [ ] **Step 1: Write exhaustive failing facing tests**

Add `face_toward` to the imports and add these tests:

```python
from PyAitD.tracks import (
    cap_objet, face_toward, get_room_link, init_deplacement, process_track,
)


@pytest.mark.parametrize(
    "target",
    ((0, 1000), (1000, 0), (0, -1000), (-1000, 0),
     (700, 700), (700, -700), (-700, 700), (-700, -700),
     (123, 987), (-821, 349)),
)
def test_face_toward_converges_from_every_beta(target):
    for beta in range(1024):
        actor = _actor()
        actor.beta = beta
        actor.rotate.num_steps = 60
        face_toward(actor, *target)
        assert cap_objet(
            actor.room_x + actor.step_x,
            actor.room_z + actor.step_z,
            actor.beta,
            *target,
        ) == 0
        assert actor.direction == 0
        assert actor.rotate.num_steps == 0


def test_face_toward_raises_at_its_bound(monkeypatch):
    actor = _actor()
    monkeypatch.setattr("PyAitD.tracks.cap_objet", lambda *args: 1)
    with pytest.raises(
        RuntimeError,
        match=r"beta=0 target=\(100, 200\) did not converge in 256 steps",
    ):
        face_toward(actor, 100, 200)
```

- [ ] **Step 2: Run the tests and verify the missing interface fails**

Run:

```bash
.venv/bin/pytest tests/test_tracks.py::test_face_toward_converges_from_every_beta tests/test_tracks.py::test_face_toward_raises_at_its_bound -q
```

Expected: collection fails with `ImportError: cannot import name 'face_toward'`.

- [ ] **Step 3: Add the minimal bounded implementation next to `cap_objet`**

```python
def face_toward(actor, x, z, *, max_steps=256):
    """Instantly face a clicked point without changing track interpolation."""
    for _ in range(max_steps):
        direction = cap_objet(
            actor.room_x + actor.step_x,
            actor.room_z + actor.step_z,
            actor.beta,
            x,
            z,
        )
        if direction == 0:
            actor.direction = 0
            actor.rotate.num_steps = 0
            return
        actor.direction = direction
        actor.beta = (actor.beta - direction * 4) & 0x3FF
    raise RuntimeError(
        f"face_toward beta={actor.beta} target={(x, z)} "
        f"did not converge in {max_steps} steps"
    )
```

Do not rename, call, or edit `_turn_toward`.

- [ ] **Step 4: Run focused and regression tests**

Run:

```bash
.venv/bin/pytest tests/test_tracks.py -q
.venv/bin/pytest -q
make prove
```

Expected: all commands pass; the existing follow, scripted, stairs, and mouse-track tests remain green.

- [ ] **Step 5: Commit the facing helper**

```bash
git add PyAitD/tracks.py tests/test_tracks.py
git commit -m "feat: add bounded mouse combat facing"
```

---

### Task 2: Combat intent discovery and delegation

**Files:**
- Modify: `PyAitD/interaction.py:8-12,140-158,236-241,343-346`
- Test: `tests/test_interaction.py:1-245`

**Interfaces:**
- Consumes: Task 1 `face_toward(actor, x, z, *, max_steps=256)`, `inventory_items`, `inventory_actions`, `cancel_nav_intent`, `room_delta`, and `choose_inventory_action`.
- Produces: `COMBAT_ACTIONS: frozenset[int]`, `is_combat_target(game, actor_idx: int) -> bool`, `combat_action_for(game, object_idx: int) -> int | None`, and `attack_in_hand(game, target_actor_idx: int) -> bool`.

- [ ] **Step 1: Write failing target and action-discovery tests**

Extend the imports and add:

```python
from PyAitD.effects import NavIntent
from PyAitD.game import AF_ANIMATED, init_game, AF_FOUNDABLE
from PyAitD.interaction import (
    COMBAT_ACTIONS, _finish_take, apply_click_intent, attack_in_hand,
    cancel_nav_intent, choose_inventory_action, combat_action_for,
    dispatch_nav_arrival, inventory_actions, inventory_items, inventory_weight,
    is_combat_target, put_object, remove_from_inventory, request_found,
    resolve_actor_contacts,
)
from PyAitD.world import room_delta


def test_combat_target_is_a_live_animated_non_hero(data_dir):
    game = init_game(data_dir)
    hero_idx = game.current_camera_target_actor
    target_idx = next(
        i for i, actor in enumerate(game.actors)
        if actor.index_in_world >= 0 and i != hero_idx
    )
    target = game.actors[target_idx]
    target.object_type |= AF_ANIMATED
    assert is_combat_target(game, target_idx)
    assert not is_combat_target(game, hero_idx)
    target.index_in_world = -1
    assert not is_combat_target(game, target_idx)


def test_combat_action_requires_an_idle_held_inventory_object(data_dir):
    game = init_game(data_dir)
    hero = game.actors[game.current_camera_target_actor]
    _finish_take(game, 38)
    assert COMBAT_ACTIONS == frozenset({32})
    assert combat_action_for(game, 38) == 32
    hero.anim_action_type = 6
    assert combat_action_for(game, 38) is None
    hero.anim_action_type = 0
    remove_from_inventory(game, 38)
    assert combat_action_for(game, 38) is None
    assert combat_action_for(game, -1) is None
```

- [ ] **Step 2: Run the discovery tests and verify failure**

Run:

```bash
.venv/bin/pytest tests/test_interaction.py::test_combat_target_is_a_live_animated_non_hero tests/test_interaction.py::test_combat_action_requires_an_idle_held_inventory_object -q
```

Expected: collection fails because the four combat interfaces do not exist.

- [ ] **Step 3: Implement target and action discovery**

Add near the inventory constants and helpers:

```python
COMBAT_ACTIONS = frozenset({32})


def is_combat_target(game, actor_idx):
    from PyAitD.game import AF_ANIMATED
    if actor_idx < 0 or actor_idx >= len(game.actors):
        return False
    if actor_idx == game.current_camera_target_actor:
        return False
    actor = game.actors[actor_idx]
    return actor.index_in_world >= 0 and bool(actor.object_type & AF_ANIMATED)


def combat_action_for(game, object_idx):
    if object_idx not in inventory_items(game):
        return None
    hero_idx = game.current_camera_target_actor
    if hero_idx == -1 or game.actors[hero_idx].anim_action_type != 0:
        return None
    return next(
        (action for action in inventory_actions(game, object_idx)
         if action in COMBAT_ACTIONS),
        None,
    )
```

- [ ] **Step 4: Write failing attack transaction tests**

```python
def _armed_attack_fixture(game):
    hero_idx = game.current_camera_target_actor
    hero = game.actors[hero_idx]
    target_idx = next(
        i for i, actor in enumerate(game.actors)
        if actor.index_in_world >= 0 and i != hero_idx
    )
    target = game.actors[target_idx]
    target.object_type |= AF_ANIMATED
    _finish_take(game, 38)
    game.in_hand_table[game.current_inventory] = 38
    return hero, target_idx, target


def test_attack_stops_faces_in_hero_room_and_delegates(data_dir, monkeypatch):
    game = init_game(data_dir)
    hero, target_idx, target = _armed_attack_fixture(game)
    hero.room, hero.room_x, hero.room_z = 0, 400, -200
    target.room, target.room_x, target.room_z = 7, 300, 500
    hero.speed = 4
    game.nav_intent = NavIntent(100, 200, hero.room)
    game.nav_decision = object()
    faced = []
    chosen = []
    monkeypatch.setattr(
        "PyAitD.tracks.face_toward",
        lambda actor, x, z: faced.append((actor, x, z)),
    )
    monkeypatch.setattr(
        "PyAitD.interaction.choose_inventory_action",
        lambda g, obj, action: chosen.append((g, obj, action)) or True,
    )

    assert attack_in_hand(game, target_idx) is True

    dx, _dy, dz = room_delta(game, hero.room, target.room)
    assert faced == [(hero, target.room_x + dx, target.room_z - dz)]
    assert chosen == [(game, 38, 32)]
    assert hero.speed == 0
    assert game.nav_intent is None and game.nav_decision is None


def test_invalid_attack_is_a_mutation_free_no_op(data_dir, monkeypatch):
    game = init_game(data_dir)
    hero, target_idx, _target = _armed_attack_fixture(game)
    game.in_hand_table[game.current_inventory] = -1
    hero.speed = 4
    game.nav_intent = NavIntent(100, 200, hero.room)
    before = (hero.beta, hero.speed, game.nav_intent, game.nav_decision)
    monkeypatch.setattr(
        "PyAitD.interaction.choose_inventory_action",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not delegate")),
    )
    assert attack_in_hand(game, target_idx) is False
    assert (hero.beta, hero.speed, game.nav_intent, game.nav_decision) == before
```

- [ ] **Step 5: Run the transaction tests and verify failure**

Run:

```bash
.venv/bin/pytest tests/test_interaction.py::test_attack_stops_faces_in_hero_room_and_delegates tests/test_interaction.py::test_invalid_attack_is_a_mutation_free_no_op -q
```

Expected: FAIL because `attack_in_hand` is not defined.

- [ ] **Step 6: Implement the attack transaction**

```python
def attack_in_hand(game, target_actor_idx):
    from PyAitD.tracks import face_toward

    hero_idx = game.current_camera_target_actor
    if hero_idx == -1 or not is_combat_target(game, target_actor_idx):
        return False
    object_idx = game.in_hand_table[game.current_inventory]
    action_id = combat_action_for(game, object_idx)
    if action_id is None:
        return False

    hero = game.actors[hero_idx]
    target = game.actors[target_actor_idx]
    target_x, target_z = target.room_x, target.room_z
    if hero.room != target.room:
        dx, _dy, dz = room_delta(game, hero.room, target.room)
        target_x += dx
        target_z -= dz

    cancel_nav_intent(game)
    hero.speed = 0
    face_toward(hero, target_x, target_z)
    return choose_inventory_action(game, object_idx, action_id)
```

- [ ] **Step 7: Run focused and full gates**

Run:

```bash
.venv/bin/pytest tests/test_interaction.py -q
.venv/bin/pytest -q
make prove
```

Expected: all commands pass.

- [ ] **Step 8: Commit the combat transaction**

```bash
git add PyAitD/interaction.py tests/test_interaction.py
git commit -m "feat: delegate mouse attacks through inventory actions"
```

---

### Task 3: Activate released thrown objects at the narrow ownership seam

**Files:**
- Modify: `PyAitD/game.py:481-529`
- Modify: `PyAitD/anim_action.py:10-15,80-109`
- Modify: `tests/test_game.py:1-90`
- Modify: `tests/test_anim_action.py:1-360`

**Interfaces:**
- Consumes: existing `add_actor(game, world_idx) -> int`, `init_deplacement`, and `_prepare_throw` release state.
- Produces: `activate_world_object(game, world_idx: int) -> int`; `spawn_stage_actors` and `_prepare_throw` both use it.

- [ ] **Step 1: Write the failing single-object activation test**

```python
def test_activate_world_object_initializes_one_released_item(data_dir):
    from PyAitD.game import activate_world_object
    from PyAitD.interaction import _finish_take

    game = init_game(data_dir)
    _finish_take(game, 38)
    world = game.world_objects[38]
    world.stage = game.current_floor
    world.room = game.current_room
    assert world.obj_index == -1

    actor_idx = activate_world_object(game, 38)

    assert actor_idx != -1
    assert world.obj_index == actor_idx
    assert game.actors[actor_idx].index_in_world == 38
    assert activate_world_object(game, 38) == actor_idx
```

- [ ] **Step 2: Run the activation test and verify failure**

Run:

```bash
.venv/bin/pytest tests/test_game.py::test_activate_world_object_initializes_one_released_item -q
```

Expected: FAIL with `ImportError: cannot import name 'activate_world_object'`.

- [ ] **Step 3: Extract the current activation body and delegate normal regeneration to it**

Add before `spawn_stage_actors`:

```python
def activate_world_object(game, world_idx):
    """Initialize one staged world object, or return its existing actor."""
    from PyAitD.tracks import init_deplacement

    obj = game.world_objects[world_idx]
    if obj.obj_index != -1:
        return obj.obj_index
    obj.obj_index = add_actor(game, world_idx)
    if obj.obj_index == -1:
        return -1

    actor = game.actors[obj.obj_index]
    if game.current_world_target == world_idx:
        game.current_camera_target_actor = obj.obj_index
    actor.dyn_flags = (obj.flags & 0x20) // 0x20
    actor.life = obj.life
    actor.life_mode = obj.life_mode
    actor.index_in_world = world_idx
    init_deplacement(actor, obj.track_mode, obj.track_number)
    actor.position_in_track = obj.position_in_track
    game.flag_genere_aff_list = 1
    return obj.obj_index
```

Replace lines 518-529 of `spawn_stage_actors` with:

```python
        activate_world_object(game, i)
```

Remove the now-unused local `init_deplacement` import from `spawn_stage_actors`.

- [ ] **Step 4: Run the game activation regressions**

Run:

```bash
.venv/bin/pytest tests/test_game.py tests/test_floor_start.py tests/test_scenario.py -q
```

Expected: PASS; normal stage regeneration still initializes the same actors.

- [ ] **Step 5: Change the existing throw test to require automatic activation**

In `test_player_throw_executes_setup_launch_and_flight`, remove the direct `spawn_stage_actors(game)` call and replace that sequence with:

```python
    gere_frappe(game, hero_idx)
    thrown_idx = game.world_objects[object_idx].obj_index
    assert thrown_idx != -1, "throw release must activate its own world object"
    assert game.actors[thrown_idx].index_in_world == object_idx
    gere_frappe(game, hero_idx)
    assert game.actors[thrown_idx].anim_action_type == THROW_OBJECT
```

Remove `spawn_stage_actors` from this test module's imports when it becomes unused.

- [ ] **Step 6: Run the throw test and verify it fails before production wiring**

Run:

```bash
.venv/bin/pytest tests/test_anim_action.py::test_player_throw_executes_setup_launch_and_flight -q
```

Expected: FAIL at `thrown_idx != -1` because `_prepare_throw` has not activated the released object.

- [ ] **Step 7: Activate only the released object in `_prepare_throw`**

Add `activate_world_object` to the `PyAitD.game` import and call it after the release fields are published:

```python
    world.flags |= 0x85
    world.flags &= ~AF_SPECIAL
    activate_world_object(game, object_idx)
```

Delete the obsolete comment and assignment that used `flag_genere_aff_list` as a deferred throw-spawn request. `activate_world_object` preserves that flag for the existing end-of-tick regeneration gate.

- [ ] **Step 8: Run combat and full regressions**

Run:

```bash
.venv/bin/pytest tests/test_game.py tests/test_anim_action.py tests/test_combat_journey.py -q
.venv/bin/pytest -q
make prove
```

Expected: all commands pass, including the existing synthetic throw collision assertions.

- [ ] **Step 9: Commit the activation repair**

```bash
git add PyAitD/game.py PyAitD/anim_action.py tests/test_game.py tests/test_anim_action.py
git commit -m "fix: activate objects at throw release"
```

---

### Task 4: Inventory HUD and honest cursor presentation

**Files:**
- Modify: `PyAitD/ui.py:100-171,259-394`
- Modify: `tests/test_ui_mouse.py:1-34`
- Modify: `tests/test_ui_render.py:1-67`

**Interfaces:**
- Consumes: pygame-ce `Rect.collidepoint`, `_button`, `_to_surface`, and `_to_frame`.
- Produces: `PlayLayout.INVENTORY`, `render_play_hud(frame, *, inventory_available) -> np.ndarray`, and distinct `render_cursor` output for `inventory|attack|target|walk|blocked`.

- [ ] **Step 1: Write failing HUD geometry tests**

```python
from PyAitD.ui import (
    FoundResult, InventoryPresenter, ModalLayout, PlayLayout, ReadingResult,
    hit_test_found, hit_test_inventory, hit_test_reading,
)


def test_inventory_hud_target_has_pinned_exclusive_edges():
    rect = PlayLayout.INVENTORY
    assert rect == pygame.Rect(4, 4, 28, 20)
    assert rect.collidepoint(rect.left, rect.top)
    assert rect.collidepoint(rect.right - 1, rect.bottom - 1)
    assert not rect.collidepoint(rect.right, rect.bottom - 1)
    assert not rect.collidepoint(rect.right - 1, rect.bottom)
```

Add `import pygame` to `tests/test_ui_mouse.py`.

- [ ] **Step 2: Run the geometry test and verify failure**

Run:

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_mouse.py::test_inventory_hud_target_has_pinned_exclusive_edges -q
```

Expected: collection fails because `PlayLayout` does not exist.

- [ ] **Step 3: Add the presentation-only layout constant**

```python
class PlayLayout:
    INVENTORY = pygame.Rect(4, 4, 28, 20)
```

Place it immediately before `ModalLayout`.

- [ ] **Step 4: Write failing HUD and five-cursor render tests**

Add `render_play_hud` to the imports and replace the two-kind cursor assertion with:

```python
def test_play_hud_draws_only_when_available_without_mutating_input():
    source = np.zeros((200, 320, 3), dtype=np.uint8)
    unavailable = render_play_hud(source, inventory_available=False)
    available = render_play_hud(source, inventory_available=True)
    assert unavailable is source
    assert np.array_equal(unavailable, source)
    assert not np.array_equal(available, source)
    assert int(source.sum()) == 0


def test_all_pointer_kinds_have_distinct_pixel_output():
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    rendered = {
        kind: render_cursor(frame, (160, 100), kind)
        for kind in ("inventory", "attack", "target", "walk", "blocked")
    }
    assert len({image.tobytes() for image in rendered.values()}) == 5
```

- [ ] **Step 5: Run render tests and verify failure**

Run:

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_render.py::test_play_hud_draws_only_when_available_without_mutating_input tests/test_ui_render.py::test_all_pointer_kinds_have_distinct_pixel_output -q
```

Expected: collection fails for `render_play_hud`; after that import exists, the cursor assertion fails until both new kinds are drawn distinctly.

- [ ] **Step 6: Implement HUD rendering and the two cursor shapes**

```python
def render_play_hud(frame, *, inventory_available):
    if not inventory_available:
        return frame
    surface = _to_surface(frame.copy())
    _button(surface, PlayLayout.INVENTORY, "INV", selected=True)
    return _to_frame(surface)


_CURSOR_COLORS = {
    "walk": (200, 230, 170),
    "target": (255, 220, 130),
    "attack": (255, 96, 72),
    "inventory": (120, 210, 255),
    "blocked": (190, 90, 80),
}
```

Extend the `render_cursor` branch before `target`:

```python
    if kind == "inventory":
        pygame.draw.rect(surface, color, pygame.Rect(x - 5, y - 4, 11, 9), width=2)
        pygame.draw.line(surface, color, (x - 2, y - 6), (x + 2, y - 6), width=2)
    elif kind == "attack":
        pygame.draw.circle(surface, color, (x, y), 6, width=1)
        pygame.draw.line(surface, color, (x - 8, y), (x + 8, y), width=1)
        pygame.draw.line(surface, color, (x, y - 8), (x, y + 8), width=1)
    elif kind == "target":
        pygame.draw.rect(surface, color, pygame.Rect(x - 5, y - 5, 11, 11), width=1)
```

Keep the existing `blocked` and `walk` branches after it.

- [ ] **Step 7: Run presentation and full gates**

Run:

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_mouse.py tests/test_ui_render.py -q
.venv/bin/pytest -q
```

Expected: all commands pass and the source frame remains unchanged.

- [ ] **Step 8: Commit the HUD presentation**

```bash
git add PyAitD/ui.py tests/test_ui_mouse.py tests/test_ui_render.py
git commit -m "feat: draw inventory hud and combat cursors"
```

---

### Task 5: Unified HUD/world resolver and run-loop routing

**Files:**
- Modify: `PyAitD/__main__.py:16-18,86-163,410-500`
- Modify: `tests/test_play_loop.py:232-515`
- Modify: `tests/test_runtime_modes.py:1-330`

**Interfaces:**
- Consumes: Task 2 `is_combat_target`, `combat_action_for`, `attack_in_hand`; Task 4 `PlayLayout`, `render_play_hud`; existing `route_command` and `apply_click_intent`.
- Produces: `inventory_hud_available(game) -> bool`, `resolve_play_click(...) -> tuple[str, object]` with all five payload contracts, and `route_play_click(game, session, floor, logical_pos, draw_list) -> None`.

- [ ] **Step 1: Write failing shared-availability tests**

Add to `tests/test_runtime_modes.py`:

```python
def test_inventory_hud_availability_is_the_complete_shared_policy(data_dir):
    from PyAitD.__main__ import inventory_hud_available

    game = init_game(data_dir)
    game.num_camera = game.new_num_camera
    game.inventory_table[0][0] = 38
    game.inventory_count[0] = 1
    assert inventory_hud_available(game)

    mutations = (
        ("input_mode", InputMode.KEYBOARD),
        ("status_screen_allowed", 0),
        ("num_camera", -1),
        ("current_camera_target_actor", -1),
    )
    for field, value in mutations:
        old = getattr(game, field)
        setattr(game, field, value)
        assert not inventory_hud_available(game), field
        setattr(game, field, old)

    game.inventory_count[0] = 0
    assert not inventory_hud_available(game)
    game.inventory_count[0] = 1
    game.open_modal(OpenInventory())
    assert not inventory_hud_available(game)
```

- [ ] **Step 2: Run the availability test and verify failure**

Run:

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_runtime_modes.py::test_inventory_hud_availability_is_the_complete_shared_policy -q
```

Expected: FAIL with `ImportError: cannot import name 'inventory_hud_available'`.

- [ ] **Step 3: Implement the shared predicate**

```python
def inventory_hud_available(game):
    return (
        game.mode is GameMode.PLAY
        and game.active_modal is None
        and game.input_mode is InputMode.MOUSE
        and game.num_camera != -1
        and game.current_camera_target_actor != -1
        and bool(game.status_screen_allowed)
        and bool(game.inventory_count[game.current_inventory])
    )
```

- [ ] **Step 4: Write resolver priority and payload tests**

Import `ModalSession` and `PlayLayout` into the existing direct-router test area, update every direct call to use one session as the second argument, and add:

```python
def test_inventory_hud_wins_before_world_resolution(data_dir, monkeypatch):
    import PyAitD.picking as picking

    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.num_camera = game.new_num_camera
    _finish_take(game, 38)
    monkeypatch.setattr(
        picking,
        "pick_floor_any_room",
        lambda *args: (_ for _ in ()).throw(AssertionError("HUD leaked to world picking")),
    )
    assert resolve_play_click(
        game, floor, PlayLayout.INVENTORY.center, [],
    ) == ("inventory", None)


def test_inventory_hud_right_edge_is_world_not_hud(data_dir, monkeypatch):
    import PyAitD.picking as picking

    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.num_camera = game.new_num_camera
    _finish_take(game, 38)
    calls = []
    monkeypatch.setattr(
        picking, "pick_floor_any_room",
        lambda *args: calls.append(args) or None,
    )
    point = (PlayLayout.INVENTORY.right, PlayLayout.INVENTORY.centery)
    assert resolve_play_click(game, floor, point, []) == ("blocked", None)
    assert len(calls) == 1


def test_combat_actor_resolves_attack_or_blocked_not_walk(data_dir):
    game = init_game(data_dir)
    enter_combat_venue(game)
    floor = Floor(data_dir, game.current_floor)
    game.num_camera = game.new_num_camera
    enemy_idx = game.world_objects[222].obj_index
    draw_list = [(enemy_idx, (100, 60, 200, 160))]
    point = (150, 100)

    assert resolve_play_click(game, floor, point, draw_list) == ("blocked", None)
    _finish_take(game, 38)
    game.in_hand_table[game.current_inventory] = 38
    assert resolve_play_click(game, floor, point, draw_list) == ("attack", enemy_idx)


def test_topmost_union_uses_one_pick_actor_call(data_dir, monkeypatch):
    import PyAitD.picking as picking

    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.num_camera = game.new_num_camera
    hero_idx = game.current_camera_target_actor
    candidates = [
        i for i, actor in enumerate(game.actors)
        if actor.index_in_world >= 0 and i != hero_idx
    ][:2]
    game.actors[candidates[0]].object_type |= AF_FOUNDABLE
    game.actors[candidates[1]].object_type |= AF_ANIMATED
    _finish_take(game, 38)
    game.in_hand_table[game.current_inventory] = 38
    seen = []
    monkeypatch.setattr(
        picking,
        "pick_actor",
        lambda point, entries: seen.append(tuple(entries)) or candidates[1],
    )
    kind, payload = resolve_play_click(
        game, floor, (150, 100),
        [(candidates[0], (0, 0, 10, 10)), (candidates[1], (0, 0, 10, 10))],
    )
    assert (kind, payload) == ("attack", candidates[1])
    assert [idx for idx, _box in seen[0]] == candidates
```

Add these imports in the direct-router section:

```python
from PyAitD.effects import GameMode
from PyAitD.game import AF_ANIMATED, AF_FOUNDABLE
from PyAitD.interaction import _finish_take
from PyAitD.scenario import enter_combat_venue
from PyAitD.ui import ModalSession, PlayLayout
```

- [ ] **Step 5: Run resolver tests and verify the missing kinds fail**

Run:

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_play_loop.py::test_inventory_hud_wins_before_world_resolution tests/test_play_loop.py::test_inventory_hud_right_edge_is_world_not_hud tests/test_play_loop.py::test_combat_actor_resolves_attack_or_blocked_not_walk tests/test_play_loop.py::test_topmost_union_uses_one_pick_actor_call -q
```

Expected: FAIL because the existing resolver does not know HUD or combat candidates.

- [ ] **Step 6: Replace split actor filtering with one candidate union**

Replace `_interactable_targets` with:

```python
def _pointer_actor_targets(game, draw_list, hero_idx):
    from PyAitD.interaction import is_combat_target
    return [
        (idx, box) for idx, box in draw_list
        if idx != hero_idx
        and (_is_interactable(game, idx) or is_combat_target(game, idx))
    ]
```

Replace `resolve_play_click` with the complete five-kind implementation:

```python
def resolve_play_click(game, floor, logical_pos, draw_list):
    """Resolve inventory, attack, target, walk, or blocked plus its payload."""
    from PyAitD.interaction import combat_action_for, is_combat_target
    from PyAitD.navmesh import agent_extent, approach_cell, nearest_walkable
    from PyAitD.picking import pick_actor, pick_floor_any_room
    from PyAitD.ui import PlayLayout
    from PyAitD.world import room_delta

    if (logical_pos is None or game.active_modal is not None
            or game.input_mode is not InputMode.MOUSE or game.num_camera == -1):
        return ("blocked", None)
    hero_idx = game.current_camera_target_actor
    if hero_idx == -1:
        return ("blocked", None)
    if (inventory_hud_available(game)
            and PlayLayout.INVENTORY.collidepoint(logical_pos)):
        return ("inventory", None)

    hero = game.actors[hero_idx]
    agent = agent_extent(hero)
    actor_idx = pick_actor(
        logical_pos, _pointer_actor_targets(game, draw_list, hero_idx),
    )
    if actor_idx is not None and is_combat_target(game, actor_idx):
        object_idx = game.in_hand_table[game.current_inventory]
        if combat_action_for(game, object_idx) is None:
            return ("blocked", None)
        return ("attack", actor_idx)
    if actor_idx is not None:
        target = game.actors[actor_idx]
        dest_x, dest_z = target.room_x, target.room_z
        mesh = game.nav_meshes.mesh_for(floor, target.room, agent)
        if mesh is not None:
            from_x, from_z = hero.room_x, hero.room_z
            if hero.room != target.room:
                dx, _dy, dz = room_delta(game, hero.room, target.room)
                from_x, from_z = from_x - dx, from_z + dz
            spot = approach_cell(mesh, dest_x, dest_z, from_x, from_z)
            if spot is not None:
                dest_x, dest_z = spot
        return (
            "target",
            (dest_x, dest_z, target.room, target.index_in_world),
        )

    picked = pick_floor_any_room(
        logical_pos, floor, hero.room, game.num_camera, hero.world_y,
    )
    if picked is None:
        return ("blocked", None)
    dest_x, dest_z, dest_room = picked
    mesh = game.nav_meshes.mesh_for(floor, dest_room, agent)
    if mesh is not None and mesh.walkable.any():
        snapped = nearest_walkable(mesh, dest_x, dest_z)
        if snapped is None:
            return ("blocked", None)
        dest_x, dest_z = snapped
    return ("walk", (dest_x, dest_z, dest_room, -1))
```

- [ ] **Step 7: Write failing route-dispatch tests**

```python
def test_hud_click_opens_inventory_without_navigation(data_dir):
    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.num_camera = game.new_num_camera
    _finish_take(game, 38)
    session = ModalSession()
    route_play_click(game, session, floor, PlayLayout.INVENTORY.center, [])
    assert game.mode is GameMode.INVENTORY
    assert game.nav_intent is None


def test_attack_click_delegates_actor_index(data_dir, monkeypatch):
    game = init_game(data_dir)
    enter_combat_venue(game)
    floor = Floor(data_dir, game.current_floor)
    game.num_camera = game.new_num_camera
    _finish_take(game, 38)
    game.in_hand_table[game.current_inventory] = 38
    enemy_idx = game.world_objects[222].obj_index
    calls = []
    monkeypatch.setattr(
        "PyAitD.interaction.attack_in_hand",
        lambda g, idx: calls.append((g, idx)) or True,
    )
    route_play_click(
        game, ModalSession(), floor, (150, 100),
        [(enemy_idx, (100, 60, 200, 160))],
    )
    assert calls == [(game, enemy_idx)]
    assert game.nav_intent is None
```

- [ ] **Step 8: Run route tests and verify failure**

Run:

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_play_loop.py::test_hud_click_opens_inventory_without_navigation tests/test_play_loop.py::test_attack_click_delegates_actor_index -q
```

Expected: FAIL because `route_play_click` still has four parameters and only creates navigation intents.

- [ ] **Step 9: Implement the five-kind router and update direct callers**

```python
def route_play_click(game, session, floor, logical_pos, draw_list):
    """Route one resolved PLAY click; HUD and world share the resolver."""
    from PyAitD.interaction import apply_click_intent, attack_in_hand

    kind, payload = resolve_play_click(game, floor, logical_pos, draw_list)
    if kind == "inventory":
        route_command(game, session, Command.OPEN_INVENTORY)
        return
    if kind == "attack":
        attack_in_hand(game, payload)
        return
    if kind == "blocked":
        return
    dest_x, dest_z, room, object_idx = payload
    apply_click_intent(game, dest_x, dest_z, room, target_object_idx=object_idx)
```

Update every existing direct test call from:

```python
route_play_click(game, floor, point, draw_list)
```

to:

```python
route_play_click(game, ModalSession(), floor, point, draw_list)
```

Use one persistent `session = ModalSession()` inside tests that issue more than one click.

- [ ] **Step 10: Wire the session, HUD drawing, and software-pointer ownership into `run`**

Extend the UI imports:

```python
from PyAitD.ui import (
    Command, InputBuffer, ModalSession, event_to_input, render_cursor,
    render_play_hud,
)
```

Immediately after creating the renderer, hide the operating-system cursor:

```python
    renderer = Renderer()
    pygame.mouse.set_visible(False)
```

Pass the live session from the event pump:

```python
                    route_play_click(game, session, floor, logical, draw_list)
```

Draw HUD before resolving/drawing the software cursor:

```python
        composed = render_active_mode(game, session, scene_frame)
        available = inventory_hud_available(game)
        composed = render_play_hud(composed, inventory_available=available)
        if (game.mode is GameMode.PLAY and game.active_modal is None
                and game.input_mode is InputMode.MOUSE):
            kind, _payload = resolve_play_click(game, floor, hover, draw_list)
            composed = render_cursor(composed, hover, kind)
```

Restore the operating-system cursor before closing the renderer:

```python
    pygame.mouse.set_visible(True)
    renderer.close()
```

Add the four inventory fields used by `inventory_hud_available` to every small
`SimpleNamespace` game in `tests/test_play_loop.py` and
`tests/test_runtime_modes.py`: `inventory_count=[0, 0]`,
`inventory_table=[[-1] * 30, [-1] * 30]`, `current_inventory=0`, and
`status_screen_allowed=1`.

- [ ] **Step 11: Add a run-loop presentation-order test**

```python
def test_run_draws_hud_before_cursor_and_owns_the_system_pointer(
    data_dir, monkeypatch,
):
    import PyAitD.__main__ as main

    calls = []
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    event_batches = iter([[], [SimpleNamespace(type=main.pygame.QUIT)]])
    times = iter([0, 0, 0])
    monkeypatch.setattr(main, "Floor", lambda *args: SimpleNamespace(
        number=0, rooms=[SimpleNamespace(camera_indices=[0])],
    ))
    monkeypatch.setattr(main, "Renderer", lambda: SimpleNamespace(
        present=lambda image: calls.append("present"), close=lambda: calls.append("close"),
    ))
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (frame, []))
    monkeypatch.setattr(main, "render_active_mode", lambda *args: frame)
    monkeypatch.setattr(
        main, "render_play_hud",
        lambda image, **kwargs: calls.append("hud") or image,
    )
    monkeypatch.setattr(
        main, "render_cursor",
        lambda image, *args: calls.append("cursor") or image,
    )
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda value: calls.append(("visible", value)))
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(times))
    monkeypatch.setattr(main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *args: None))

    game = init_game(data_dir)
    game.inventory_table[0][0] = 38
    game.inventory_count[0] = 1
    assert main.run(game) == 0
    assert calls.index("hud") < calls.index("cursor") < calls.index("present")
    assert calls[0] == ("visible", False)
    assert ("visible", True) in calls
```

- [ ] **Step 12: Run routing, runtime, and full gates**

Run:

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_play_loop.py tests/test_runtime_modes.py tests/test_ui_render.py -q
.venv/bin/pytest -q
make prove
```

Expected: all commands pass; existing M3d target/floor behavior changes only by the mechanical session argument.

- [ ] **Step 13: Commit the unified pointer route**

```bash
git add PyAitD/__main__.py tests/test_play_loop.py tests/test_runtime_modes.py
git commit -m "feat: route hud and combat through one pointer resolver"
```

---

### Task 6: Exhaustive pygame-free mouse capability contract

**Files:**
- Create: `PyAitD/mouse_contract.py`
- Create: `tests/test_mouse_only.py`

**Interfaces:**
- Consumes: `PyAitD.effects.GameMode`; tests compare declarations to `PyAitD.ui.Command` without importing `Command` into the contract module.
- Produces: `PlayerCapability`, `MouseRoute`, `LegacyCommandDecision`, `CAPABILITY_ROUTES`, `MODE_MOUSE_CAPABILITIES`, `COMMAND_MOUSE_CAPABILITIES`, and `LEGACY_COMMAND_REPLACEMENTS`.

- [ ] **Step 1: Write failing purity and exhaustiveness tests**

```python
# tests/test_mouse_only.py
# SPDX-License-Identifier: GPL-2.0-only
import subprocess
import sys

from PyAitD.effects import GameMode
from PyAitD.mouse_contract import (
    CAPABILITY_ROUTES, COMMAND_MOUSE_CAPABILITIES,
    LEGACY_COMMAND_REPLACEMENTS, MODE_MOUSE_CAPABILITIES, PlayerCapability,
)
from PyAitD.ui import Command


_PURITY_PROBE = r"""
import sys
import PyAitD.mouse_contract
leaked = {"pygame", "moderngl", "PyAitD.ui", "PyAitD.render"} & sys.modules.keys()
raise SystemExit(", ".join(sorted(leaked)) if leaked else 0)
"""


def test_mouse_contract_is_presentation_free():
    result = subprocess.run(
        [sys.executable, "-c", _PURITY_PROBE], capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_every_capability_has_exactly_one_route():
    assert set(CAPABILITY_ROUTES) == set(PlayerCapability)
    assert all(route.gesture in {"left_click", "window_close"}
               for route in CAPABILITY_ROUTES.values())


def test_every_mode_declares_exactly_the_routes_available_in_it():
    assert set(MODE_MOUSE_CAPABILITIES) == set(GameMode)
    for mode in GameMode:
        derived = frozenset(
            capability for capability, route in CAPABILITY_ROUTES.items()
            if mode in route.modes
        )
        assert MODE_MOUSE_CAPABILITIES[mode] == derived


def test_every_command_has_a_mouse_capability_or_reviewed_legacy_decision():
    declared = set(COMMAND_MOUSE_CAPABILITIES) | set(LEGACY_COMMAND_REPLACEMENTS)
    assert declared == set(Command.__members__)
    assert set(COMMAND_MOUSE_CAPABILITIES).isdisjoint(LEGACY_COMMAND_REPLACEMENTS)
    assert LEGACY_COMMAND_REPLACEMENTS["TOGGLE_INPUT_MODE"].replacement is None
    assert "leaves the mouse scheme" in LEGACY_COMMAND_REPLACEMENTS[
        "TOGGLE_INPUT_MODE"
    ].reason
```

- [ ] **Step 2: Run the contract tests and verify the missing module fails**

Run:

```bash
.venv/bin/pytest tests/test_mouse_only.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'PyAitD.mouse_contract'`.

- [ ] **Step 3: Create the complete contract module**

```python
# PyAitD/mouse_contract.py
# SPDX-License-Identifier: GPL-2.0-only
"""Declared one-button mouse surface for the implemented M3 game modes."""
from dataclasses import dataclass
from enum import Enum, auto

from PyAitD.effects import GameMode


class PlayerCapability(Enum):
    WALK_TO_POINT = auto()
    INTERACT_WITH_OBJECT = auto()
    TAKE_FOUND_OBJECT = auto()
    LEAVE_FOUND_OBJECT = auto()
    OPEN_INVENTORY = auto()
    SELECT_INVENTORY_OBJECT = auto()
    SELECT_INVENTORY_ACTION = auto()
    PAGE_READING = auto()
    CLOSE_READING = auto()
    DISMISS_PICTURE = auto()
    ATTACK_TARGET = auto()
    RESTART_GAME_OVER = auto()
    QUIT = auto()


@dataclass(frozen=True)
class MouseRoute:
    gesture: str
    target: str
    modes: frozenset[GameMode]


@dataclass(frozen=True)
class LegacyCommandDecision:
    replacement: PlayerCapability | None
    reason: str


ALL_MODES = frozenset(GameMode)
CAPABILITY_ROUTES = {
    PlayerCapability.WALK_TO_POINT: MouseRoute("left_click", "walkable floor", frozenset({GameMode.PLAY})),
    PlayerCapability.INTERACT_WITH_OBJECT: MouseRoute("left_click", "interactable actor", frozenset({GameMode.PLAY})),
    PlayerCapability.TAKE_FOUND_OBJECT: MouseRoute("left_click", "Take button", frozenset({GameMode.FOUND})),
    PlayerCapability.LEAVE_FOUND_OBJECT: MouseRoute("left_click", "Leave button", frozenset({GameMode.FOUND})),
    PlayerCapability.OPEN_INVENTORY: MouseRoute("left_click", "inventory HUD", frozenset({GameMode.PLAY})),
    PlayerCapability.SELECT_INVENTORY_OBJECT: MouseRoute("left_click", "inventory object row", frozenset({GameMode.INVENTORY})),
    PlayerCapability.SELECT_INVENTORY_ACTION: MouseRoute("left_click", "inventory action row", frozenset({GameMode.INVENTORY})),
    PlayerCapability.PAGE_READING: MouseRoute("left_click", "Previous or Next button", frozenset({GameMode.READING})),
    PlayerCapability.CLOSE_READING: MouseRoute("left_click", "Close button", frozenset({GameMode.READING})),
    PlayerCapability.DISMISS_PICTURE: MouseRoute("left_click", "picture", frozenset({GameMode.READING})),
    PlayerCapability.ATTACK_TARGET: MouseRoute("left_click", "armed combat actor", frozenset({GameMode.PLAY})),
    PlayerCapability.RESTART_GAME_OVER: MouseRoute("left_click", "game-over frame", frozenset({GameMode.GAME_OVER})),
    PlayerCapability.QUIT: MouseRoute("window_close", "window close control", ALL_MODES),
}


MODE_MOUSE_CAPABILITIES = {
    GameMode.PLAY: frozenset({
        PlayerCapability.WALK_TO_POINT,
        PlayerCapability.INTERACT_WITH_OBJECT,
        PlayerCapability.OPEN_INVENTORY,
        PlayerCapability.ATTACK_TARGET,
        PlayerCapability.QUIT,
    }),
    GameMode.FOUND: frozenset({
        PlayerCapability.TAKE_FOUND_OBJECT,
        PlayerCapability.LEAVE_FOUND_OBJECT,
        PlayerCapability.QUIT,
    }),
    GameMode.INVENTORY: frozenset({
        PlayerCapability.SELECT_INVENTORY_OBJECT,
        PlayerCapability.SELECT_INVENTORY_ACTION,
        PlayerCapability.QUIT,
    }),
    GameMode.READING: frozenset({
        PlayerCapability.PAGE_READING,
        PlayerCapability.CLOSE_READING,
        PlayerCapability.DISMISS_PICTURE,
        PlayerCapability.QUIT,
    }),
    GameMode.GAME_OVER: frozenset({
        PlayerCapability.RESTART_GAME_OVER,
        PlayerCapability.QUIT,
    }),
}


COMMAND_MOUSE_CAPABILITIES = {
    "ACCEPT": frozenset({
        PlayerCapability.INTERACT_WITH_OBJECT,
        PlayerCapability.TAKE_FOUND_OBJECT,
        PlayerCapability.SELECT_INVENTORY_OBJECT,
        PlayerCapability.SELECT_INVENTORY_ACTION,
        PlayerCapability.PAGE_READING,
        PlayerCapability.CLOSE_READING,
        PlayerCapability.DISMISS_PICTURE,
        PlayerCapability.RESTART_GAME_OVER,
    }),
    "CANCEL": frozenset({
        PlayerCapability.LEAVE_FOUND_OBJECT,
        PlayerCapability.CLOSE_READING,
        PlayerCapability.QUIT,
    }),
    "OPEN_INVENTORY": frozenset({PlayerCapability.OPEN_INVENTORY}),
}


LEGACY_COMMAND_REPLACEMENTS = {
    name: LegacyCommandDecision(
        PlayerCapability.WALK_TO_POINT,
        "point-and-click walking replaces the legacy tank-direction command",
    )
    for name in ("UP", "DOWN", "LEFT", "RIGHT")
}
LEGACY_COMMAND_REPLACEMENTS["TOGGLE_INPUT_MODE"] = LegacyCommandDecision(
    None,
    "this command deliberately leaves the mouse scheme; it is not a missing mouse route",
)
```

- [ ] **Step 4: Run contract, purity, and full tests**

Run:

```bash
.venv/bin/pytest tests/test_mouse_only.py -q
.venv/bin/pytest -q
```

Expected: all commands pass. Adding any `PlayerCapability`, `GameMode`, or `Command` without updating the corresponding table must make one of these tests fail.

- [ ] **Step 5: Commit the contract**

```bash
git add PyAitD/mouse_contract.py tests/test_mouse_only.py
git commit -m "test: declare exhaustive mouse capability contract"
```

---

### Task 7: Real-data mouse journeys and focused proof target

**Files:**
- Modify: `tests/test_mouse_only.py`
- Modify: `PyAitD/scenario.py:1-13`
- Modify: `PyAitD/__main__.py:25-42,517-533`
- Modify: `tests/test_scenario.py:1-17`
- Modify: `tests/test_main.py:1-45`
- Modify: `Makefile:1-66`

**Interfaces:**
- Consumes: Tasks 1-6, `__main__.run`, `tests.test_combat_journey._journey_to_game_over`, pygame-ce `pygame.event.Event`, `ModalLayout`, `PlayLayout`, and the real-data `data_dir` fixture.
- Produces: `enter_mouse_combat_fixture(game) -> None`, `--mouse-combat-fixture`, `make run-mouse-combat`, a reusable in-test event-pump harness, isolated combat-action measurement, attic/combat/restart journeys, and `make prove-mouse-only`.

- [ ] **Step 1: Add the failing real-data action-set measurement**

Append these imports and test:

```python
import itertools
from types import SimpleNamespace

import numpy as np
import pygame

from PyAitD.anim_action import HANDLED_ACTIONS, THROW_OBJECT, WAIT_ANIM_THROW
from PyAitD.floor import Floor
from PyAitD.game import AF_ANIMATED, init_game
from PyAitD.interaction import (
    COMBAT_ACTIONS, _finish_take, choose_inventory_action, inventory_actions,
    inventory_items,
)
from PyAitD.playworld import play_tick
from PyAitD.scenario import enter_combat_venue, enter_mouse_combat_fixture
from PyAitD.ui import InputBuffer, ModalLayout, PlayLayout


def test_real_data_combat_action_set_is_exactly_32(data_dir):
    armed = set()
    baseline = init_game(data_dir)
    offered = [
        (object_idx, action)
        for object_idx, world in enumerate(baseline.world_objects)
        if world.found_life != -1
        for action in inventory_actions(baseline, object_idx)
    ]
    for object_idx, action in offered:
        game = init_game(data_dir)
        enter_combat_venue(game)
        floor = Floor(data_dir, game.current_floor)
        _finish_take(game, object_idx)
        choose_inventory_action(game, object_idx, action)
        hero = game.actors[game.current_camera_target_actor]
        for _ in range(20):
            if hero.anim_action_type in HANDLED_ACTIONS:
                armed.add(action)
                break
            if game.active_modal is not None:
                break
            play_tick(game, floor, InputBuffer())
    assert armed == set(COMBAT_ACTIONS) == {32}
```

- [ ] **Step 2: Run the measurement and verify the first missing route or seam**

Run:

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_mouse_only.py::test_real_data_combat_action_set_is_exactly_32 -q
```

Expected after Tasks 1-6: PASS. If it fails, preserve the fresh-game isolation and correct only an evidence mismatch traced to FITD; do not broaden `COMBAT_ACTIONS` from a non-isolated observation.

- [ ] **Step 3: Write failing tests for the shared mouse-combat proof start**

Add to `tests/test_scenario.py`:

```python
from PyAitD.interaction import inventory_items
from PyAitD.scenario import (
    COMBAT_VENUE, enter_combat_venue, enter_mouse_combat_fixture,
)


def test_mouse_combat_fixture_is_deterministic_and_does_not_change_m3c_start(data_dir):
    game = init_game(data_dir)
    enter_mouse_combat_fixture(game)
    hero = game.actors[game.current_camera_target_actor]
    enemy = game.actors[game.world_objects[222].obj_index]
    assert game.floor_start == COMBAT_VENUE
    assert inventory_items(game) == (38,)
    assert (hero.room_x, hero.room_y, hero.room_z) == (-7400, -4010, -1000)
    assert (enemy.room_x, enemy.room_y, enemy.room_z) == (-7400, -4010, -1250)
    assert (enemy.life, enemy.life_mode, enemy.track_mode, enemy.speed) == (-1, -1, 0, 0)

    control = init_game(data_dir)
    enter_combat_venue(control)
    control_enemy = control.actors[control.world_objects[222].obj_index]
    assert inventory_items(control) == ()
    assert (control_enemy.track_mode, control_enemy.track_number) == (2, 1)
```

Extend `tests/test_main.py` with:

```python
def test_parse_args_has_a_separate_mouse_combat_start():
    args = parse_args(["--mouse-combat-fixture"])
    assert args.mouse_combat_fixture is True
    assert args.combat_venue is False


def test_main_mouse_combat_fixture_runs_its_own_setup(monkeypatch, tmp_path):
    import PyAitD.__main__ as main

    game = SimpleNamespace()
    calls = []
    monkeypatch.setattr(main, "init_game", lambda data: game)
    monkeypatch.setattr(
        main, "enter_mouse_combat_fixture",
        lambda g: calls.append(("mouse fixture", g)),
    )
    monkeypatch.setattr(main, "run", lambda g, trace: calls.append(("run", g)) or 0)
    assert main.main([
        "--mouse-combat-fixture", "--data", str(tmp_path),
    ]) == 0
    assert calls == [("mouse fixture", game), ("run", game)]
```

- [ ] **Step 4: Run the fixture/CLI tests and verify missing interfaces fail**

Run:

```bash
.venv/bin/pytest tests/test_scenario.py::test_mouse_combat_fixture_is_deterministic_and_does_not_change_m3c_start tests/test_main.py::test_parse_args_has_a_separate_mouse_combat_start tests/test_main.py::test_main_mouse_combat_fixture_runs_its_own_setup -q
```

Expected: collection fails because `enter_mouse_combat_fixture` and the CLI option do not exist.

- [ ] **Step 5: Implement the shared fixture, CLI option, and manual run target**

In `PyAitD/scenario.py`, import `relocate_actor` and add:

```python
MOUSE_COMBAT_OBJECT = 38
MOUSE_COMBAT_HERO = (-7400, -4010, -1000)
MOUSE_COMBAT_TARGET = (-7400, -4010, -1250)


def enter_mouse_combat_fixture(game):
    """Deterministic object-38 lane for automated and manual mouse proof."""
    from PyAitD.interaction import _finish_take

    enter_combat_venue(game)
    _finish_take(game, MOUSE_COMBAT_OBJECT)
    hero_idx = game.current_camera_target_actor
    enemy_idx = game.world_objects[222].obj_index
    relocate_actor(game, hero_idx, 5, 4, *MOUSE_COMBAT_HERO)
    relocate_actor(game, enemy_idx, 5, 4, *MOUSE_COMBAT_TARGET)
    enemy = game.actors[enemy_idx]
    enemy.life = -1
    enemy.life_mode = -1
    enemy.track_mode = 0
    enemy.speed = 0
```

In `PyAitD.__main__.py`, import the helper and put both debug starts in one
mutually exclusive argparse group:

```python
from PyAitD.scenario import enter_combat_venue, enter_mouse_combat_fixture


    starts = p.add_mutually_exclusive_group()
    starts.add_argument(
        "--combat-venue", action="store_true",
        help="start at the supported floor-5 combat venue",
    )
    starts.add_argument(
        "--mouse-combat-fixture", action="store_true",
        help="start with the deterministic object-38 mouse combat proof fixture",
    )
```

Route it before the existing combat start:

```python
    if args.mouse_combat_fixture:
        enter_mouse_combat_fixture(game)
    elif args.combat_venue:
        enter_combat_venue(game)
```

Update the non-zero-floor error to say
`use --combat-venue or --mouse-combat-fixture`, add
`args.mouse_combat_fixture is False` to `test_parse_args_defaults`, and add to
the Makefile run section:

```make
run-mouse-combat: install ## Run the deterministic object-38 mouse combat proof fixture
	$(PYTHON) -m PyAitD --mouse-combat-fixture --data $(data) $(if $(trace),--trace $(trace))
```

Add `run-mouse-combat` to `.PHONY`.

- [ ] **Step 6: Run fixture, CLI, and scenario regressions**

Run:

```bash
.venv/bin/pytest tests/test_scenario.py tests/test_main.py -q
```

Expected: PASS; `--combat-venue` retains its existing route and state.

- [ ] **Step 7: Add the deterministic event-pump harness**

```python
_FRAME = np.zeros((200, 320, 3), dtype=np.uint8)


class _HeadlessRenderer:
    def __init__(self):
        self.presented = 0

    def window_to_logical(self, pos):
        return pos

    def present(self, _frame):
        self.presented += 1

    def close(self):
        pass


def _left_click(pos):
    return pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, button=1, pos=tuple(pos),
    )


def _run_scripted_mouse(monkeypatch, game, draw_list, next_events):
    import PyAitD.__main__ as main

    renderer = _HeadlessRenderer()
    ticks = itertools.count(0, 20)
    monkeypatch.setattr(main, "Renderer", lambda: renderer)
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (_FRAME, draw_list))
    monkeypatch.setattr(main, "render_active_mode", lambda *args: _FRAME)
    monkeypatch.setattr(main.pygame.event, "get", next_events)
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(ticks))
    monkeypatch.setattr(main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *args: None))
    monkeypatch.setattr(main.pygame.display, "set_caption", lambda *args: None)
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda *args: None)
    assert main.run(game) == 0
    assert renderer.presented > 0
```

- [ ] **Step 8: Add the attic interaction/inventory journey**

```python
def test_mouse_journey_attic_take_hud_inventory_action(data_dir, monkeypatch):
    game = init_game(data_dir)
    game.timer = 300
    lamp_idx = 13
    actor_idx = game.world_objects[lamp_idx].obj_index
    state = {"step": "lamp", "frames": 0}

    def next_events():
        state["frames"] += 1
        assert state["frames"] < 2500, "attic mouse journey exceeded its budget"
        if state["step"] == "lamp":
            state["step"] = "found"
            return [_left_click((150, 100))]
        if state["step"] == "found" and game.mode is GameMode.FOUND:
            state["step"] = "hud"
            return [_left_click(ModalLayout.FOUND_TAKE.center)]
        if (state["step"] == "hud" and game.mode is GameMode.PLAY
                and lamp_idx in inventory_items(game)):
            state["step"] = "object"
            return [_left_click(PlayLayout.INVENTORY.center)]
        if state["step"] == "object" and game.mode is GameMode.INVENTORY:
            state["step"] = "action"
            return [_left_click(ModalLayout.INVENTORY_ROWS[0].center)]
        if state["step"] == "action" and game.mode is GameMode.INVENTORY:
            state["step"] = "quit"
            return [_left_click(ModalLayout.INVENTORY_ROWS[0].center)]
        if (state["step"] == "quit" and game.mode is GameMode.PLAY
                and game.in_hand_table[0] == lamp_idx):
            return [pygame.event.Event(pygame.QUIT)]
        return []

    _run_scripted_mouse(
        monkeypatch, game, [(actor_idx, (100, 60, 200, 160))], next_events,
    )
    assert lamp_idx in inventory_items(game)
    assert game.in_hand_table[0] == lamp_idx
```

- [ ] **Step 9: Run the attic journey and verify it fails at the first missing mouse route**

Run:

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_mouse_only.py::test_mouse_journey_attic_take_hud_inventory_action -q
```

Expected on the pre-M3e baseline: FAIL when the HUD click cannot open inventory. Expected after Tasks 1-6: PASS with no direct `Command` injection.

- [ ] **Step 10: Add the measured object-38 combat journey**

```python
def test_mouse_journey_inventory_attack_publishes_real_throw(data_dir, monkeypatch):
    import PyAitD.playworld as playworld_module

    game = init_game(data_dir)
    # This call is the documented pre-audit fixture boundary. Every player
    # decision after it enters through the synthetic pygame event stream.
    enter_mouse_combat_fixture(game)
    hero_idx = game.current_camera_target_actor
    enemy_idx = game.world_objects[222].obj_index
    hero = game.actors[hero_idx]
    enemy = game.actors[enemy_idx]

    observed = {"wait": False, "flight": False, "hit": None}
    original_gere_frappe = playworld_module.gere_frappe

    def observe_action(g, actor_idx):
        actor = g.actors[actor_idx]
        observed["wait"] |= actor_idx == hero_idx and actor.anim_action_type == WAIT_ANIM_THROW
        observed["flight"] |= actor.anim_action_type == THROW_OBJECT
        result = original_gere_frappe(g, actor_idx)
        thrown_idx = g.world_objects[38].obj_index
        if thrown_idx != -1 and enemy.hit_by == thrown_idx:
            observed["hit"] = (thrown_idx, enemy.hit_force)
        return result

    monkeypatch.setattr(playworld_module, "gere_frappe", observe_action)
    state = {"step": "hud", "frames": 0}

    def next_events():
        state["frames"] += 1
        assert state["frames"] < 500, "combat mouse journey exceeded its budget"
        if state["step"] == "hud":
            state["step"] = "object"
            return [_left_click(PlayLayout.INVENTORY.center)]
        if state["step"] == "object" and game.mode is GameMode.INVENTORY:
            state["step"] = "equip"
            return [_left_click(ModalLayout.INVENTORY_ROWS[0].center)]
        if state["step"] == "equip" and game.mode is GameMode.INVENTORY:
            state["step"] = "attack"
            return [_left_click(ModalLayout.INVENTORY_ROWS[0].center)]
        if (state["step"] == "attack" and game.mode is GameMode.PLAY
                and game.in_hand_table[0] == 38):
            state["step"] = "wait"
            return [_left_click((150, 100))]
        if observed["hit"] is not None:
            return [pygame.event.Event(pygame.QUIT)]
        return []

    _run_scripted_mouse(
        monkeypatch, game, [(enemy_idx, (100, 60, 200, 160))], next_events,
    )
    thrown_idx, force = observed["hit"]
    assert observed["wait"]
    assert observed["flight"]
    assert force == 2
    assert thrown_idx != hero_idx
```

- [ ] **Step 11: Run the combat journey**

Run:

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_mouse_only.py::test_mouse_journey_inventory_attack_publishes_real_throw -q
```

Expected: PASS; the event pump supplies every audited player decision, and the real found LIFE/opcode/action/activation/collision path publishes force `2` from the thrown actor.

- [ ] **Step 12: Add the game-over restart event-pump journey**

```python
def test_mouse_journey_game_over_restart_uses_a_left_click(data_dir, monkeypatch):
    import PyAitD.__main__ as main
    from tests.test_combat_journey import _journey_to_game_over

    game, saw_death_life = _journey_to_game_over(data_dir)
    assert saw_death_life
    assert game.mode is GameMode.GAME_OVER
    restarted = []
    real_restart = main.restart_session

    def capture_restart(old_game):
        new_game = real_restart(old_game)
        restarted.append(new_game)
        return new_game

    monkeypatch.setattr(main, "restart_session", capture_restart)
    frames = 0

    def next_events():
        nonlocal frames
        frames += 1
        assert frames < 140, "game-over click did not request restart"
        if restarted:
            return [pygame.event.Event(pygame.QUIT)]
        if frames == 105:
            return [_left_click((160, 100))]
        return []

    _run_scripted_mouse(monkeypatch, game, [], next_events)
    assert len(restarted) == 1
    assert restarted[0].active_modal is None
    assert restarted[0].vars[21] == 20
```

- [ ] **Step 13: Run the restart journey**

Run:

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_mouse_only.py::test_mouse_journey_game_over_restart_uses_a_left_click -q
```

Expected: PASS; no restart `Command` is injected and the click occurs after the real 2-second gate.

- [ ] **Step 14: Add the focused Make target**

Update `.PHONY` and append:

```make
.PHONY: help install run run-combat run-mouse-combat test prove prove-m3b prove-mouse prove-mouse-only prove-combat clean

prove-mouse-only: install ## M3e proof: exhaustive one-button contract + real-data attic, combat, and restart journeys
	SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy $(PYTHON) -m pytest tests/test_mouse_only.py -q
```

- [ ] **Step 15: Run the focused proof and full regression gate**

Run:

```bash
make prove-mouse-only
.venv/bin/pytest -q
make prove
```

Expected: all commands pass. `make prove-mouse` remains the separate navmesh census and is not changed.

- [ ] **Step 16: Commit the executable mouse proof**

```bash
git add PyAitD/scenario.py PyAitD/__main__.py tests/test_scenario.py tests/test_main.py tests/test_mouse_only.py Makefile
git commit -m "test: prove mouse-only M3 journeys"
```

---

### Task 8: Windowed accessibility evidence and architecture handoff

**Files:**
- Create: `docs/m3e-mouse-only-proof.md`
- Modify: `CONTEXT.md:1-220`

**Interfaces:**
- Consumes: `make run`, `make run-mouse-combat`, `make prove-mouse-only`, `make test`, and `make prove`.
- Produces: an honest M3e evidence record and updated living architecture map; no production interface.

- [ ] **Step 1: Run the complete automated evidence set**

Run:

```bash
make prove-mouse-only
make test
make prove
```

Expected: all three commands pass. Copy their exact pass/skip/xfail counts and date into the proof document created in Step 3.

- [ ] **Step 2: Perform the windowed single-button checks**

Run both entry points with the user's real game data:

```bash
make run
make run-mouse-combat
```

Using one physical left button and no keyboard/gameplay key, verify each item and record `PASS` or `FAIL` with a short observation:

```text
Attic: click the lamp, choose Take, open INV, choose the lamp, choose action 23.
Reading: advance/back where available and close with visible buttons.
Combat: open INV, select object 38/action 23 in the fixture venue, click obj222, observe stop/face/throw without approach walking.
Game over: wait for the prompt and restart with one click.
Quit: close the window through window chrome.
HUD geometry: click near all four corners of the 28x20 logical target.
Isolation: HUD clicks never create navigation; letterbox clicks do nothing.
Cursor: exactly one visible cursor for inventory, attack, target, walk, blocked.
Keyboard mode: no software cursor and no clickable HUD are advertised.
Responsiveness: leave each modal open for ten seconds; the window remains responsive.
```

If any item fails, stop this task, leave M3e status as incomplete, and report the exact failed observation before changing code.

- [ ] **Step 3: Create the evidence document with the observed results**

Use this structure, replacing each result line with the exact command output or manual observation from Steps 1-2:

```markdown
# M3e Mouse-Only Reachability and Combat Proof

Date: 2026-08-23
Spec: `docs/superpowers/specs/2026-08-23-mouse-only-combat-and-invariant-design.md`
Plan: `docs/superpowers/plans/2026-08-23-m3e-mouse-reachability-and-combat.md`

## Automated evidence

- `make prove-mouse-only`: PASS — exact pytest summary recorded from the run.
- `make test`: PASS — exact pytest summary recorded from the run.
- `make prove`: PASS — exact pytest summary recorded from the run.

## Windowed one-button evidence

| Route | Result | Observation |
|---|---|---|
| Attic found/take/HUD/inventory/action | PASS or FAIL | Exact observed behavior |
| Reading page/back/close | PASS or FAIL | Exact observed behavior |
| Combat stop/face/force-2 throw | PASS or FAIL | Exact observed behavior |
| Game-over restart | PASS or FAIL | Exact observed behavior |
| Window close | PASS or FAIL | Exact observed behavior |
| Four HUD corners | PASS or FAIL | Exact observed behavior |
| HUD/letterbox isolation | PASS or FAIL | Exact observed behavior |
| Five honest cursor states | PASS or FAIL | Exact observed behavior |
| Keyboard-mode hiding | PASS or FAIL | Exact observed behavior |
| Ten-second modal responsiveness | PASS or FAIL | Exact observed behavior |

## Scope ruling

M3e proves the implemented M3 surface only. M4a, M4b, and M4c must extend the
capability registry and record both complete protagonist journeys before the
engine can claim start-to-ending mouse-only completion.
```

The `PASS or FAIL` and observation cells are instructions for the evidence run, not acceptable final text: replace every cell with what was actually observed.

- [ ] **Step 4: Update `CONTEXT.md` with the landed boundary**

Apply these exact structural changes:

```markdown
| M3e | Mouse reachability: HUD inventory, clicked force-2 throw, exhaustive mouse contract | done |
```

Add to Commands:

```bash
make run-mouse-combat           # deterministic object-38 mouse combat proof start
make prove-mouse-only         # M3e contract + real-data attic/combat/restart mouse journeys
```

Add to the architecture table:

```markdown
| `mouse_contract.py` | Pygame-free declaration of current player capabilities, per-mode one-button routes, and reviewed legacy command replacements |
```

Add this boundary section:

```markdown
## M3e mouse-reachability boundary

- `tracks.face_toward` is an instantaneous clicked-attack adapter; ordinary
  `_turn_toward` interpolation and its existing callers remain unchanged.
- `interaction.attack_in_hand` stops navigation, faces in the hero's room
  frame, and delegates action 32 through `choose_inventory_action`.
- `game.activate_world_object` is shared by normal active-list regeneration
  and throw release so a released projectile exists before later LIFE reads.
- `scenario.enter_mouse_combat_fixture` owns the deterministic object-38
  automated/manual proof start; the M3c `enter_combat_venue` remains unchanged.
- `__main__.resolve_play_click` is the one HUD/attack/target/walk/blocked
  resolver used by both hover and click routing.
- Focused proof: `make prove-mouse-only`; manual evidence:
  `docs/m3e-mouse-only-proof.md`.
- This milestone does not claim complete-game mouse play; M4 owns that gate.
```

Change the `make test` count comment to `pytest suite — authoritative gate` so the living map does not become stale after each new test.

- [ ] **Step 5: Verify documentation consistency and a clean final gate**

Run:

```bash
rg -n "M3e|prove-mouse-only|mouse_contract|complete-game" CONTEXT.md docs/m3e-mouse-only-proof.md
git diff --check
make prove-mouse-only
.venv/bin/pytest -q
make prove
```

Expected: searches show the new command/boundary/evidence links, `git diff --check` is silent, and all three gates pass.

- [ ] **Step 6: Commit the milestone handoff**

```bash
git add CONTEXT.md docs/m3e-mouse-only-proof.md
git commit -m "docs: record M3e mouse-only proof"
```

---

## Final acceptance checklist

- [ ] `make prove-mouse-only` passes under dummy SDL video/audio.
- [ ] `.venv/bin/pytest -q` and `make prove` pass.
- [ ] `_turn_toward` and its five callers are unchanged.
- [ ] Hover and click consume the same five-kind resolver result.
- [ ] HUD availability includes PLAY, mouse mode, no modal, valid camera/hero, status permission, and non-empty inventory.
- [ ] A blocked combat actor cannot fall through to a floor walk.
- [ ] Attack revalidation fails without mutating navigation, speed, facing, or combat state.
- [ ] Object 38 follows action 23 -> click obj222 -> action 32 -> `WAIT_ANIM_THROW` -> `THROW_OBJECT` -> victim `hit_by` with force `2`.
- [ ] Attic, combat, and restart journeys inject only pygame mouse/window events after their documented fixture boundary.
- [ ] The capability and mode tables are exhaustive against their enums, and the contract subprocess imports no pygame/UI/render module.
- [ ] Windowed evidence records single-button target corners, cursor honesty, modal responsiveness, restart, and quit.
- [ ] Documentation still states that M4 owns start-to-ending completion for both protagonists.
