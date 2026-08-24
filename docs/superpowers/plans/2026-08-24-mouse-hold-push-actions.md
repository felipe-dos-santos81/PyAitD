# Mouse Hold-to-Push Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a one-button mouse user hold the primary button to approach and push the opening-room wardrobe, with release cancelling movement immediately.

**Architecture:** The existing play-click resolver gains a `push` result backed by a pygame-free runtime capability predicate and an adjacent approach point. A hold-required `NavIntent` approaches normally, then continuously retargets the live world actor while projecting FITD's player push animation through the existing animation, collision, and LIFE paths; mouse-up and every invalidation route use one idempotent cancellation boundary.

**Tech Stack:** Python 3.12, pygame-ce, NumPy, pytest, existing FITD-derived LIFE/animation/collision engine; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-24-mouse-hold-push-actions-design.md`

## Global Constraints

- Every new Python file starts with `# SPDX-License-Identifier: GPL-2.0-only`.
- `playworld.py`, `life_ops.py`, `interaction.py`, and `effects.py` remain pygame/rendering/event free.
- `ui.py` never mutates world, actor, inventory, or LIFE state; `__main__.py` owns the single event pump and game/session replacement.
- Pushing is a held forward/navigation operation. It never continuously asserts global Action or `local_click`.
- The mouse adapter must never write the wardrobe's position, `AF_MOVABLE`, collision fields, or LIFE variables. Only existing animation, collision, and LIFE code may move or enable it.
- World object 4, actor slot 3, body 2, LIFE 1 is the real-data opening-room wardrobe. LIFE 1 enables `AF_MOVABLE` only while the colliding hero exposes animation 5; both protagonist archives use animation 5 for the push pose and animation 4 for stand.
- The latched target identity is the world-object index. Actor slots must be resolved again every tick.
- Releasing the primary button during approach or engagement stops the hero in the same input/simulation tick. Mouse-up must not cancel ordinary click-to-walk.
- Foundable, inventory, combat, ordinary target, walk, and blocked behavior keep their existing priority and semantics.
- Rendering tests use `SDL_VIDEODRIVER=dummy`; final gates are `make prove-mouse-only`, `.venv/bin/pytest -q`, and `make prove`.

## File Map

| File | Responsibility in this change |
|---|---|
| `PyAitD/effects.py` | Hold-required and engaged fields on `NavIntent`. |
| `PyAitD/interaction.py` | Push constants, target predicate, adjacent approach selection, intent creation, and idempotent cancellation. |
| `PyAitD/mouse_contract.py` | Declarative `HOLD_PUSH_OBJECT` / `left_hold` capability. |
| `PyAitD/ui.py` | Primary-pointer held state, focus reset, amber push cursor. |
| `PyAitD/navigate.py` | Optional contact steering that does not stop at ordinary arrival distance but retains stall detection. |
| `PyAitD/playworld.py` | Approach-to-engage transition, live retargeting, push-animation projection, defensive cancellation. |
| `PyAitD/__main__.py` | Push click routing, mouse-up/focus cancellation, latched cursor display. |
| `tests/test_effects.py` | Neutral held-intent defaults. |
| `tests/test_interaction.py` | Eligibility, adjacent approach, and cancellation contracts. |
| `tests/test_ui_input.py` | Pointer down/up/focus lifecycle. |
| `tests/test_ui_render.py` | Distinct push cursor output. |
| `tests/test_navigate.py` | Contact steering and bounded stall behavior. |
| `tests/test_play_loop.py` | Resolver priority, push routing, cursor latch, event cancellation. |
| `tests/test_playworld.py` | Held follower phases, live retarget, no Action, invalidation. |
| `tests/test_mouse_only.py` | Both-protagonist real-loop wardrobe journey and mouse contract. |
| `docs/mouse-hold-push-proof.md` | Automated evidence and manual accessibility checklist. |
| `CONTEXT.md` | Landed architecture boundary and proof command. |

---

### Task 1: Define the held-action domain contracts

**Files:**
- Modify: `PyAitD/effects.py:113-126`
- Modify: `PyAitD/interaction.py:8-19,361-365`
- Modify: `PyAitD/mouse_contract.py:9-136`
- Test: `tests/test_effects.py`
- Test: `tests/test_interaction.py`
- Test: `tests/test_mouse_only.py:37-98`

**Interfaces:**
- Consumes: existing `NavIntent`, `AF_FOUNDABLE`, `AF_MOVABLE`, `agent_extent`, `nearest_walkable`, `room_delta`, and mouse contract tables.
- Produces: `PLAYER_STAND_ANIM = 4`, `PLAYER_PUSH_ANIM = 5`, `is_hold_action_target(game, actor_idx) -> bool`, `hold_action_approach(game, floor, hero_idx, target_idx) -> tuple[int, int, int, int] | None`, `apply_click_intent(..., requires_hold=False)`, and `NavIntent.requires_hold` / `NavIntent.engaged`.

- [ ] **Step 1: Write failing contract tests**

Add these focused assertions, using `WorldObject 4` and inert `WorldObject 8` from the real opening stage:

```python
# tests/test_effects.py
def test_nav_intent_defaults_to_a_non_held_approach():
    intent = NavIntent(10, 20, 0)
    assert intent.requires_hold is False
    assert intent.engaged is False


# tests/test_interaction.py
def test_real_wardrobe_is_a_hold_action_target_but_inert_scenery_is_not(data_dir):
    game = init_game(data_dir)
    wardrobe_idx = game.world_objects[4].obj_index
    inert_idx = game.world_objects[8].obj_index
    assert is_hold_action_target(game, wardrobe_idx) is True
    assert is_hold_action_target(game, inert_idx) is False


def test_hold_action_approach_is_outside_the_wardrobe_footprint(data_dir):
    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    hero_idx = game.current_camera_target_actor
    wardrobe_idx = game.world_objects[4].obj_index
    result = hold_action_approach(game, floor, hero_idx, wardrobe_idx)
    assert result is not None
    x, z, room, world_idx = result
    wardrobe = game.actors[wardrobe_idx]
    assert (room, world_idx) == (wardrobe.room, 4)
    assert (x, z) != (wardrobe.room_x, wardrobe.room_z)


# tests/test_mouse_only.py
def test_hold_push_has_one_declarative_mouse_route():
    route = CAPABILITY_ROUTES[PlayerCapability.HOLD_PUSH_OBJECT]
    assert route == MouseRoute(
        "left_hold", "push-capable scripted actor", frozenset({GameMode.PLAY}),
    )
    assert PlayerCapability.HOLD_PUSH_OBJECT in MODE_MOUSE_CAPABILITIES[GameMode.PLAY]
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest -q \
  tests/test_effects.py::test_nav_intent_defaults_to_a_non_held_approach \
  tests/test_interaction.py::test_real_wardrobe_is_a_hold_action_target_but_inert_scenery_is_not \
  tests/test_interaction.py::test_hold_action_approach_is_outside_the_wardrobe_footprint \
  tests/test_mouse_only.py::test_hold_push_has_one_declarative_mouse_route
```

Expected: FAIL because the fields, capability, predicate, and approach helper do not exist.

- [ ] **Step 3: Add the minimal domain implementation**

Extend `NavIntent` after `target_object_idx`:

```python
requires_hold: bool = False
engaged: bool = False
```

Add to `interaction.py`:

```python
PLAYER_STAND_ANIM = 4
PLAYER_PUSH_ANIM = 5


def is_hold_action_target(game, actor_idx):
    from PyAitD.game import AF_FOUNDABLE, AF_MOVABLE
    if actor_idx < 0 or actor_idx >= len(game.actors):
        return False
    if actor_idx == game.current_camera_target_actor:
        return False
    actor = game.actors[actor_idx]
    if actor.index_in_world < 0 or actor.body_num == -1 or not (actor.dyn_flags & 1):
        return False
    world = game.world_objects[actor.index_in_world]
    if world.obj_index != actor_idx or world.stage != game.current_floor:
        return False
    if actor.object_type & AF_FOUNDABLE:
        return False
    return bool(actor.object_type & AF_MOVABLE) or actor.life != -1


def hold_action_approach(game, floor, hero_idx, target_idx):
    from PyAitD.navmesh import agent_extent, nearest_walkable

    if not is_hold_action_target(game, target_idx):
        return None
    hero = game.actors[hero_idx]
    target = game.actors[target_idx]
    if hero.room != target.room:
        return None
    mesh = game.nav_meshes.mesh_for(floor, target.room, agent_extent(hero))
    if mesh is None:
        return None
    half = agent_extent(hero)[0]
    clearance = half + mesh.step
    x0, x1, _y0, _y1, z0, z1 = target.zv
    from_x = hero.room_x + hero.step_x
    from_z = hero.room_z + hero.step_z
    clamp = lambda value, low, high: max(low, min(value, high))
    candidates = (
        (x0 - clearance, clamp(from_z, z0, z1)),
        (x1 + clearance, clamp(from_z, z0, z1)),
        (clamp(from_x, x0, x1), z0 - clearance),
        (clamp(from_x, x0, x1), z1 + clearance),
    )
    walkable = []
    for x, z in candidates:
        spot = nearest_walkable(mesh, x, z)
        if spot is not None:
            walkable.append(spot)
    if not walkable:
        return None
    x, z = min(
        walkable,
        key=lambda point: abs(point[0] - from_x) + abs(point[1] - from_z),
    )
    return (x, z, target.room, target.index_in_world)
```

Extend `apply_click_intent` without changing existing callers:

```python
def apply_click_intent(
        game, dest_x, dest_z, room, target_object_idx=-1, *, requires_hold=False,
):
    from PyAitD.effects import NavIntent
    game.nav_intent = NavIntent(
        dest_x, dest_z, room, target_object_idx,
        requires_hold=requires_hold,
    )
    game.nav_decision = None
```

Add `HOLD_PUSH_OBJECT = auto()`, its `MouseRoute("left_hold", ...)`, and the capability to `GameMode.PLAY`. Do not add it to `COMMAND_MOUSE_CAPABILITIES`: it has no keyboard command replacement.

- [ ] **Step 4: Run focused tests and the existing contract suite**

Run:

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest -q tests/test_effects.py tests/test_interaction.py tests/test_mouse_only.py
```

Expected: PASS, including exactly-one-route and per-mode capability invariants.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/effects.py PyAitD/interaction.py PyAitD/mouse_contract.py \
  tests/test_effects.py tests/test_interaction.py tests/test_mouse_only.py
git commit -m "feat: define held push contracts"
```

---

### Task 2: Track the primary-button lifecycle and make cancellation atomic

**Files:**
- Modify: `PyAitD/ui.py:25-33,73-133`
- Modify: `PyAitD/interaction.py:368-371`
- Test: `tests/test_ui_input.py:30-37`
- Test: `tests/test_interaction.py:215-220`

**Interfaces:**
- Consumes: Task 1's `NavIntent.requires_hold` and `PLAYER_STAND_ANIM`.
- Produces: `InputBuffer.pointer_held: bool`, `cancel_held_nav_intent(game) -> bool`, and an expanded idempotent `cancel_nav_intent(game)`.

- [ ] **Step 1: Write failing input and cancellation tests**

```python
def test_primary_pointer_down_up_and_focus_loss_are_held_state():
    state = InputBuffer()
    event_to_input(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1), state)
    assert state.pointer_held is True
    event_to_input(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1), state)
    assert state.pointer_held is False
    state.pointer_held = True
    event_to_input(pygame.event.Event(pygame.WINDOWFOCUSLOST), state)
    assert state.pointer_held is False


def test_cancel_held_intent_stops_and_rearms_stand_idempotently(data_dir):
    game = init_game(data_dir)
    hero = game.actors[game.current_camera_target_actor]
    apply_click_intent(game, 100, 200, hero.room, 4, requires_hold=True)
    game.nav_arrived_target = 4
    game.local_joyd = 1
    game.local_click = 1
    game.action = 0x2000
    hero.speed = 4
    hero.direction = 1
    assert cancel_held_nav_intent(game) is True
    assert (game.nav_intent, game.nav_decision) == (None, None)
    assert (game.nav_arrived_target, game.local_joyd, game.local_click, game.action) == (-1, 0, 0, 0)
    assert (hero.speed, hero.direction, hero.rotate.num_steps) == (0, 0, 0)
    assert hero.new_anim == PLAYER_STAND_ANIM
    assert cancel_held_nav_intent(game) is False
```

- [ ] **Step 2: Verify RED**

Run:

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest -q \
  tests/test_ui_input.py::test_primary_pointer_down_up_and_focus_loss_are_held_state \
  tests/test_interaction.py::test_cancel_held_intent_stops_and_rearms_stand_idempotently
```

Expected: FAIL because `pointer_held` and `cancel_held_nav_intent` are missing.

- [ ] **Step 3: Implement held state and cancellation**

Add `pointer_held: bool = False` to `InputBuffer`. Clear it in `reset_input`. In `event_to_input`, before keyboard dispatch, handle primary down/up:

```python
if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
    state.pointer_held = True
    return True
if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
    state.pointer_held = False
    return True
```

Replace the cancellation helper with:

```python
def cancel_nav_intent(game):
    intent = game.nav_intent
    held = intent is not None and intent.requires_hold
    game.nav_intent = None
    game.nav_decision = None
    game.nav_arrived_target = -1
    game.local_joyd = 0
    game.local_click = 0
    game.local_key = 0
    game.action = 0
    if not held:
        return
    hero_idx = game.current_camera_target_actor
    if hero_idx == -1:
        return
    from PyAitD.life_ops import init_anim
    hero = game.actors[hero_idx]
    hero.speed = 0
    hero.direction = 0
    hero.rotate.num_steps = 0
    init_anim(hero, PLAYER_STAND_ANIM, 0, PLAYER_STAND_ANIM)


def cancel_held_nav_intent(game):
    intent = game.nav_intent
    if intent is None or not intent.requires_hold:
        return False
    cancel_nav_intent(game)
    return True
```

- [ ] **Step 4: Run the focused and interaction regression tests**

Run:

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest -q tests/test_ui_input.py tests/test_interaction.py
```

Expected: PASS. Existing ordinary cancellation tests remain green.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/ui.py PyAitD/interaction.py tests/test_ui_input.py tests/test_interaction.py
git commit -m "feat: cancel held pointer actions atomically"
```

---

### Task 3: Resolve and render an honest push action

**Files:**
- Modify: `PyAitD/__main__.py:143-258`
- Modify: `PyAitD/ui.py:738-768`
- Test: `tests/test_play_loop.py:319-709`
- Test: `tests/test_ui_render.py:74-80`

**Interfaces:**
- Consumes: Task 1's `is_hold_action_target`, `hold_action_approach`, and `apply_click_intent(..., requires_hold=)`.
- Produces: resolver kind `("push", (dest_x, dest_z, room, world_idx))`; push clicks create hold-required intents; cursor kind `push` is amber and shape-distinct.

- [ ] **Step 1: Write failing resolver, priority, and cursor tests**

```python
def test_opening_wardrobe_resolves_and_routes_as_a_held_push(data_dir):
    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.num_camera = game.new_num_camera
    actor_idx = game.world_objects[4].obj_index
    draw = [(actor_idx, (100, 60, 200, 160))]
    kind, payload = resolve_play_click(game, floor, (150, 100), draw)
    assert kind == "push"
    assert payload[3] == 4
    route_play_click(game, ModalSession(), floor, (150, 100), draw)
    assert game.nav_intent.requires_hold is True
    assert game.nav_intent.engaged is False


def test_inert_body_intercepts_the_floor_and_stays_blocked(data_dir):
    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.num_camera = game.new_num_camera
    actor_idx = game.world_objects[8].obj_index
    assert resolve_play_click(
        game, floor, (150, 100), [(actor_idx, (100, 60, 200, 160))],
    ) == ("blocked", None)


def test_push_cursor_is_a_sixth_distinct_pointer():
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    kinds = ("inventory", "attack", "target", "push", "walk", "blocked")
    rendered = {kind: render_cursor(frame, (160, 100), kind) for kind in kinds}
    assert len({image.tobytes() for image in rendered.values()}) == len(kinds)
```

Retain the existing tests for combat-before-push, inventory-before-world, and cursor/click agreement.

- [ ] **Step 2: Verify RED**

Run:

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest -q \
  tests/test_play_loop.py::test_opening_wardrobe_resolves_and_routes_as_a_held_push \
  tests/test_play_loop.py::test_inert_body_intercepts_the_floor_and_stays_blocked \
  tests/test_ui_render.py::test_push_cursor_is_a_sixth_distinct_pointer
```

Expected: FAIL because the wardrobe is filtered out and `push` has no renderer.

- [ ] **Step 3: Implement resolver priority and held routing**

Change `_pointer_actor_targets` to include every live, body-bearing, non-hero draw-list actor. This lets inert scenery block a floor click instead of disappearing from hit testing:

```python
def _pointer_actor_targets(game, draw_list, hero_idx):
    return [
        (idx, box) for idx, box in draw_list
        if idx != hero_idx
        and game.actors[idx].index_in_world >= 0
        and game.actors[idx].body_num != -1
    ]
```

In `resolve_play_click`, keep combat first. Replace the start of the existing generic actor branch with this classification, then leave its current approach-cell and room-frame code in place for `target`:

```python
if actor_idx is not None:
    if not _is_interactable(game, actor_idx):
        if not is_hold_action_target(game, actor_idx):
            return ("blocked", None)
        payload = hold_action_approach(game, floor, hero_idx, actor_idx)
        return ("push", payload) if payload is not None else ("blocked", None)
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
```

Update the resolver docstring with all six kinds. In `route_play_click`, route `push` using `requires_hold=(kind == "push")`; inventory, attack, blocked, target, and walk stay unchanged.

- [ ] **Step 4: Add the amber non-color-only cursor**

Add `"push": (255, 178, 56)` to `_CURSOR_COLORS`. Render two opposing arrows with short vertical braces:

```python
elif kind == "push":
    pygame.draw.line(surface, color, (x - 7, y), (x + 7, y), width=2)
    pygame.draw.line(surface, color, (x - 7, y), (x - 3, y - 3), width=2)
    pygame.draw.line(surface, color, (x - 7, y), (x - 3, y + 3), width=2)
    pygame.draw.line(surface, color, (x + 7, y), (x + 3, y - 3), width=2)
    pygame.draw.line(surface, color, (x + 7, y), (x + 3, y + 3), width=2)
```

- [ ] **Step 5: Run resolver/render regressions**

Run:

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest -q tests/test_play_loop.py tests/test_ui_render.py
```

Expected: PASS, including combat and inventory priority tests.

- [ ] **Step 6: Commit**

```bash
git add PyAitD/__main__.py PyAitD/ui.py tests/test_play_loop.py tests/test_ui_render.py
git commit -m "feat: resolve and render held push actions"
```

---

### Task 4: Sustain contact through the existing follower, animation, collision, and LIFE paths

**Files:**
- Modify: `PyAitD/navigate.py:60-110`
- Modify: `PyAitD/playworld.py:15-103`
- Test: `tests/test_navigate.py`
- Test: `tests/test_playworld.py`

**Interfaces:**
- Consumes: `NavIntent.requires_hold`, `NavIntent.engaged`, `PLAYER_PUSH_ANIM`, `is_hold_action_target`, `cancel_nav_intent`, `InputBuffer.pointer_held`, and the existing `decide`/stall state.
- Produces: `decide(game, actor, mesh, *, stop_at_destination=True)` and held approach/engage processing in `apply_play_input(game, input_buffer)`.

- [ ] **Step 1: Write failing contact-steering tests**

Add a navigate test proving ordinary arrival still stops while contact steering advances and eventually stalls:

```python
def test_contact_steering_advances_inside_the_ordinary_arrival_radius():
    intent = NavIntent(200, 0, 0, waypoints=[(200, 0)])
    intent.path_room = 0
    game = _Game(intent)
    actor = _actor(0, 0)
    assert decide(game, actor, None).arrived is True
    decision = decide(game, actor, None, stop_at_destination=False)
    assert decision.advance is True
    assert decision.joyd & 1
    for _tick in range(STALL_TICKS):
        decision = decide(game, actor, None, stop_at_destination=False)
    assert decision.arrived is True
    assert decision.advance is False
```

Add playworld tests with real object 4:

```python
@pytest.mark.parametrize("hero_id", (0, 1))
def test_held_wardrobe_engages_retargets_and_never_asserts_action(data_dir, hero_id):
    game = init_game(data_dir, hero=hero_id)
    floor = Floor(data_dir, game.current_floor)
    hero = game.actors[game.current_camera_target_actor]
    target = game.actors[game.world_objects[4].obj_index]
    game.current_floor_data = floor
    game.nav_intent = NavIntent(
        hero.room_x, hero.room_z, hero.room, 4,
        requires_hold=True, engaged=False,
        waypoints=[(hero.room_x, hero.room_z)], path_room=hero.room,
    )
    buf = InputBuffer(pointer_held=True)
    apply_play_input(game, buf)
    assert game.nav_intent.engaged is True
    assert game.action == game.local_click == 0
    old = (target.room_x, target.room_z)
    target.room_x += 20
    target.room_z += 30
    apply_play_input(game, buf)
    assert (game.nav_intent.dest_x, game.nav_intent.dest_z) == (old[0] + 20, old[1] + 30)
    assert hero.new_anim == PLAYER_PUSH_ANIM


def test_held_intent_cancels_when_release_is_observed(data_dir):
    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.current_floor_data = floor
    target = game.actors[game.world_objects[4].obj_index]
    game.nav_intent = NavIntent(
        target.room_x, target.room_z, target.room, 4,
        requires_hold=True, engaged=True, waypoints=[(target.room_x, target.room_z)],
        path_room=target.room,
    )
    apply_play_input(game, InputBuffer(pointer_held=False))
    assert game.nav_intent is None
    assert (game.local_joyd, game.local_click, game.action) == (0, 0, 0)


@pytest.mark.parametrize("invalidation", ("despawn", "room", "floor"))
def test_engaged_intent_cancels_when_the_live_target_is_invalid(data_dir, invalidation):
    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.current_floor_data = floor
    world = game.world_objects[4]
    target = game.actors[world.obj_index]
    game.nav_intent = NavIntent(
        target.room_x, target.room_z, target.room, 4,
        requires_hold=True, engaged=True, waypoints=[(target.room_x, target.room_z)],
        path_room=target.room,
    )
    if invalidation == "despawn":
        world.obj_index = -1
    elif invalidation == "room":
        target.room += 1
    else:
        game.current_floor += 1
    apply_play_input(game, InputBuffer(pointer_held=True))
    assert game.nav_intent is None
    assert (game.local_joyd, game.local_click, game.action) == (0, 0, 0)
```

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest -q \
  tests/test_navigate.py::test_contact_steering_advances_inside_the_ordinary_arrival_radius \
  tests/test_playworld.py::test_held_wardrobe_engages_retargets_and_never_asserts_action \
  tests/test_playworld.py::test_held_intent_cancels_when_release_is_observed \
  tests/test_playworld.py::test_engaged_intent_cancels_when_the_live_target_is_invalid
```

Expected: FAIL on the new keyword argument and held-state transitions.

- [ ] **Step 3: Extend navigation without changing ordinary arrival**

Give `decide` the keyword-only `stop_at_destination=True`. Guard only the existing early-arrival branch:

```python
if (stop_at_destination and intent.room == actor.room
        and len(intent.waypoints) == 1 and distance < ARRIVE_DISTANCE):
    return NavDecision(0, target_x, target_z, advance=False, arrived=True)
```

Do not bypass `_stalled`; a blocked contact still abandons through the existing bounded counter.

- [ ] **Step 4: Implement held target refresh and engage**

Change `_apply_mouse_input(game)` to `_apply_mouse_input(game, input_buffer)` and pass the buffer from `apply_play_input`.

Add a pygame-free helper in `playworld.py`:

```python
def _refresh_held_target(game, hero):
    from PyAitD.interaction import (
        PLAYER_PUSH_ANIM, cancel_nav_intent, is_hold_action_target,
    )
    from PyAitD.life_ops import init_anim

    intent = game.nav_intent
    world_idx = intent.target_object_idx
    if not 0 <= world_idx < len(game.world_objects):
        cancel_nav_intent(game)
        return False
    world = game.world_objects[world_idx]
    actor_idx = world.obj_index
    if (actor_idx == -1 or not is_hold_action_target(game, actor_idx)
            or game.actors[actor_idx].room != hero.room):
        cancel_nav_intent(game)
        return False
    target = game.actors[actor_idx]
    point = (target.room_x, target.room_z)
    if (intent.dest_x, intent.dest_z, intent.room) != (*point, target.room):
        intent.stall_target = None
        intent.stall_best = 0
        intent.stall_ticks = 0
    intent.dest_x, intent.dest_z, intent.room = point[0], point[1], target.room
    intent.waypoints = [point]
    intent.path_room = hero.room
    init_anim(hero, PLAYER_PUSH_ANIM, 1, -1)
    return True
```

Replace `_apply_mouse_input` with this control flow, retaining `_push_into_target` only in the non-held branch:

```python
def _apply_mouse_input(game, input_buffer):
    from PyAitD.interaction import cancel_nav_intent

    game.local_key = 0
    game.local_click = 0
    game.action = 0
    hero_idx = game.current_camera_target_actor
    intent = game.nav_intent
    if hero_idx == -1 or intent is None:
        game.nav_decision = None
        game.local_joyd = 0
        return
    if intent.requires_hold and (not input_buffer.focused or not input_buffer.pointer_held):
        cancel_nav_intent(game)
        return

    hero = game.actors[hero_idx]
    if intent.requires_hold and intent.engaged:
        if not _refresh_held_target(game, hero):
            return
    mesh = game.nav_meshes.mesh_for(
        game.current_floor_data, hero.room, agent_extent(hero),
    )
    decision = decide(
        game, hero, mesh, stop_at_destination=not intent.engaged,
    )
    game.nav_decision = decision
    game.local_joyd = decision.joyd if decision is not None else 0
    if decision is None or not (decision.arrived or decision.abandoned):
        return

    if intent.requires_hold:
        if decision.arrived and not decision.abandoned and not intent.engaged:
            intent.engaged = True
            if _refresh_held_target(game, hero):
                game.nav_decision = None
                game.local_joyd = 0
            return
        cancel_nav_intent(game)
        return

    if decision.arrived and not decision.abandoned and _push_into_target(game):
        game.nav_decision = None
        game.local_joyd = 0
        return
    if decision.arrived:
        game.nav_arrived_target = intent.target_object_idx
    game.nav_intent = None
    game.nav_decision = None
    game.local_joyd = 0
```

This makes an engaged `arrived` result mean bounded contact stall and cancels it without setting `nav_arrived_target`. Keep `_push_into_target` and `dispatch_nav_arrival` unchanged for non-held ordinary targets.

- [ ] **Step 5: Prove the real LIFE/collision handoff headlessly**

Add a parametrized `play_tick` regression that starts from Task 1's approach point, holds `InputBuffer(pointer_held=True)`, and runs at most 2,500 ticks:

```python
@pytest.mark.parametrize("hero_id", (0, 1))
def test_real_wardrobe_moves_only_after_life_enables_it(data_dir, hero_id):
    from PyAitD.game import AF_MOVABLE
    from PyAitD.interaction import hold_action_approach

    game = init_game(data_dir, hero=hero_id)
    floor = Floor(data_dir, game.current_floor)
    hero_idx = game.current_camera_target_actor
    actor_idx = game.world_objects[4].obj_index
    payload = hold_action_approach(game, floor, hero_idx, actor_idx)
    assert payload is not None
    dest_x, dest_z, room, world_idx = payload
    game.nav_intent = NavIntent(
        dest_x, dest_z, room, world_idx, requires_hold=True,
    )
    wardrobe = game.actors[actor_idx]
    start = (wardrobe.room_x, wardrobe.room_z)
    buffer = InputBuffer(pointer_held=True)
    movable_seen = False
    action_seen = 0
    for _tick in range(2500):
        play_tick(game, floor, buffer)
        action_seen |= game.action | game.local_click
        movable_seen |= bool(wardrobe.object_type & AF_MOVABLE)
        if (wardrobe.room_x, wardrobe.room_z) != start:
            assert movable_seen is True
            break
    assert (wardrobe.room_x, wardrobe.room_z) != start
    assert action_seen == 0
    assert game.nav_intent is not None and game.nav_intent.engaged
```

This test must not assign `wardrobe.object_type`, `wardrobe.room_x`, `wardrobe.room_z`, `wardrobe.world_x`, `wardrobe.world_z`, `wardrobe.col_by`, or `game.vars`; the production LIFE/contact path is the subject under test.

- [ ] **Step 6: Run navigation and headless play regressions**

Run:

```bash
.venv/bin/pytest -q tests/test_navigate.py tests/test_playworld.py tests/test_actor_contacts.py
```

Expected: PASS for both protagonists, contact stall, existing movable contact, and ordinary arrival.

- [ ] **Step 7: Commit**

```bash
git add PyAitD/navigate.py PyAitD/playworld.py tests/test_navigate.py tests/test_playworld.py
git commit -m "feat: sustain held push contact"
```

---

### Task 5: Route mouse-up, focus loss, and the latched cursor through the event owner

**Files:**
- Modify: `PyAitD/__main__.py:637-775`
- Test: `tests/test_play_loop.py:712-793`

**Interfaces:**
- Consumes: `InputBuffer.pointer_held`, `cancel_held_nav_intent`, resolver kind `push`, and held `NavIntent`.
- Produces: `_play_cursor_kind(game, floor, hover, draw_list, input_buffer) -> str`, `_cancel_pointer_invalidation(game, event) -> bool`, and same-event-pump release/focus cancellation.

- [ ] **Step 1: Write failing event-owner tests**

```python
def test_latched_push_cursor_survives_pointer_drift(data_dir):
    game = init_game(data_dir)
    floor = Floor(data_dir, game.current_floor)
    game.num_camera = game.new_num_camera
    apply_click_intent(game, 10, 20, 0, 4, requires_hold=True)
    buf = InputBuffer(pointer_held=True)
    assert _play_cursor_kind(game, floor, (0, 0), [], buf) == "push"


def test_mouseup_cancels_only_a_hold_required_intent(data_dir):
    game = init_game(data_dir)
    hero = game.actors[game.current_camera_target_actor]
    apply_click_intent(game, 100, 200, hero.room)
    assert cancel_held_nav_intent(game) is False
    assert game.nav_intent is not None
    apply_click_intent(game, 100, 200, hero.room, 4, requires_hold=True)
    assert cancel_held_nav_intent(game) is True
    assert game.nav_intent is None


def test_pointer_invalidation_routes_mouseup_and_focus_loss(data_dir):
    game = init_game(data_dir)
    hero = game.actors[game.current_camera_target_actor]
    for event in (
        pygame.event.Event(pygame.MOUSEBUTTONUP, button=1),
        pygame.event.Event(pygame.WINDOWFOCUSLOST),
    ):
        apply_click_intent(game, 100, 200, hero.room, 4, requires_hold=True)
        assert _cancel_pointer_invalidation(game, event) is True
        assert game.nav_intent is None
```

- [ ] **Step 2: Verify RED**

Run:

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest -q \
  tests/test_play_loop.py::test_latched_push_cursor_survives_pointer_drift \
  tests/test_play_loop.py::test_mouseup_cancels_only_a_hold_required_intent \
  tests/test_play_loop.py::test_pointer_invalidation_routes_mouseup_and_focus_loss
```

Expected: FAIL because `_play_cursor_kind` and release routing are absent.

- [ ] **Step 3: Implement event-owner cancellation**

Add the helper and call it immediately after `event_to_input` in `run`:

```python
def _cancel_pointer_invalidation(game, event):
    invalidated = (
        event.type == pygame.MOUSEBUTTONUP and event.button == 1
    ) or event.type == pygame.WINDOWFOCUSLOST
    if not invalidated:
        return False
    from PyAitD.interaction import cancel_held_nav_intent
    return cancel_held_nav_intent(game)


# Inside run(), directly after event_to_input:
_cancel_pointer_invalidation(game, event)
```

Because `event_to_input` runs first, primary down is already latched before `route_play_click`. Existing modal-entry `reset_input` plus `cancel_nav_intent` remains the authority for modal cancellation. Game/floor replacement creates a fresh buffer/game; playworld defensively cancels target/room invalidation.

Add and use:

```python
def _play_cursor_kind(game, floor, hover, draw_list, input_buffer):
    intent = game.nav_intent
    if (input_buffer.pointer_held and intent is not None
            and intent.requires_hold):
        return "push"
    kind, _payload = resolve_play_click(game, floor, hover, draw_list)
    return kind
```

This is an active-latch display override only. Before press, `resolve_play_click` remains the sole hover authority.

- [ ] **Step 4: Run play-loop and runtime-mode regressions**

Run:

```bash
SDL_VIDEODRIVER=dummy .venv/bin/pytest -q tests/test_play_loop.py tests/test_runtime_modes.py
```

Expected: PASS, including modal flush, replacement, combat, inventory, and one-present-per-frame tests.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/__main__.py tests/test_play_loop.py
git commit -m "feat: route held push release events"
```

---

### Task 6: Prove both-protagonist mouse-only journeys and land the milestone record

**Files:**
- Modify: `tests/test_mouse_only.py:131-303`
- Create: `docs/mouse-hold-push-proof.md`
- Modify: `CONTEXT.md`

**Interfaces:**
- Consumes: the complete held push flow from Tasks 1-5 and the existing `_run_scripted_mouse` real-loop harness.
- Produces: a real-data one-button regression for approach cancellation and sustained pushing for hero IDs 0 and 1, plus repository handoff evidence.

- [ ] **Step 1: Add mouse button helpers and the failing journey**

```python
def _left_down(pos):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos)


def _left_up(pos):
    return pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=pos)


@pytest.mark.parametrize("hero_id", (0, 1))
def test_mouse_hold_push_wardrobe_release_and_retry(data_dir, monkeypatch, hero_id):
    game = init_game(data_dir, hero=hero_id)
    game.timer = 300
    hero = game.actors[game.current_camera_target_actor]
    wardrobe = game.actors[game.world_objects[4].obj_index]
    wardrobe_start = (wardrobe.room_x, wardrobe.room_z)
    state = {
        "phase": "press_then_cancel", "frames": 0,
        "hero_start": (hero.room_x, hero.room_z), "released_at": None,
        "still_frames": 0, "movable_seen": False,
        "wardrobe_released_at": None,
    }

    def next_events():
        state["frames"] += 1
        assert state["frames"] < 5000, "wardrobe hold journey exceeded its budget"
        if state["phase"] == "press_then_cancel":
            state["phase"] = "approaching"
            return [_left_down((150, 100))]
        if (state["phase"] == "approaching"
                and (hero.room_x, hero.room_z) != state["hero_start"]):
            state["phase"] = "released"
            state["released_at"] = (hero.room_x, hero.room_z)
            return [_left_up((10, 10))]
        if state["phase"] == "released":
            assert (hero.room_x, hero.room_z) == state["released_at"]
            state["still_frames"] += 1
            if state["still_frames"] == 5:
                state["phase"] = "holding"
                return [_left_down((150, 100))]
        if state["phase"] == "holding":
            state["movable_seen"] |= bool(wardrobe.object_type & AF_MOVABLE)
            assert game.action == 0 and game.local_click == 0
            if (wardrobe.room_x, wardrobe.room_z) != wardrobe_start:
                state["phase"] = "push_released"
                state["wardrobe_released_at"] = (wardrobe.room_x, wardrobe.room_z)
                state["still_frames"] = 0
                return [_left_up((10, 10))]
        if state["phase"] == "push_released":
            assert (wardrobe.room_x, wardrobe.room_z) == state["wardrobe_released_at"]
            state["still_frames"] += 1
            if state["still_frames"] == 5:
                return [pygame.event.Event(pygame.QUIT)]
        return []

    _run_scripted_mouse(
        monkeypatch, game,
        [(game.world_objects[4].obj_index, (100, 60, 200, 160))],
        next_events,
    )
    assert state["movable_seen"] is True
    assert (wardrobe.room_x, wardrobe.room_z) != wardrobe_start
    assert game.nav_intent is None
    assert game.action == game.local_click == game.local_joyd == 0
```

Import `AF_MOVABLE`. The test must not assign any wardrobe movement/type/LIFE field.

- [ ] **Step 2: Verify the journey fails before the complete flow and passes now**

Run:

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q \
  tests/test_mouse_only.py::test_mouse_hold_push_wardrobe_release_and_retry
```

Expected after Tasks 1-5: PASS twice, once per protagonist. If it fails, trace the same path through FITD and correct hero input/facing/animation projection only; never patch the wardrobe.

- [ ] **Step 3: Run all required gates**

Run each command separately:

```bash
make prove-mouse-only
```

```bash
.venv/bin/pytest -q
```

```bash
make prove
```

Expected: all PASS. Do not claim implementation complete from focused tests alone.

- [ ] **Step 4: Write proof and architecture handoff**

Create `docs/mouse-hold-push-proof.md` with:

```markdown
# Mouse Hold-to-Push Proof

Date: 2026-08-24

## Automated evidence

- `make prove-mouse-only`: PASS, including both-protagonist opening-room wardrobe journeys.
- `.venv/bin/pytest -q`: PASS.
- `make prove`: PASS against original AITD1 data.

The journey proves press-and-hold approach, release-before-arrival same-tick stop,
retry, LIFE enabling `AF_MOVABLE`, collision-owned wardrobe movement, no global
Action signal, and release cleanup for Carnby and Emily.

## Fidelity boundary

The adapter latches world object 4 and projects player animation 5 while engaged.
LIFE 1 enables movement; `resolve_actor_contacts` performs the movement. The mouse
path never assigns the wardrobe's flags, position, collision fields, or variables.

## Windowed accessibility check

- Hover the left wardrobe: amber opposed-arrow cursor, never red X.
- Hold the primary button: hero approaches and pushes without pointer tracking.
- Release during approach and during contact: movement stops immediately.
- Repeat with both character selections.
```

Add this row to `CONTEXT.md` after M4a1:

```markdown
| Mouse hold-to-push | Held approach/engage for scripted movable furniture | automated gates green; windowed accessibility pass pending (`docs/mouse-hold-push-proof.md`) |
```

Add this boundary before Testing conventions:

```markdown
## Mouse hold-to-push boundary

- `NavIntent` latches a world-object index and distinguishes held approach from
  engaged contact; transient actor slots are resolved again every tick.
- Engagement projects AITD1 player animation 5 while ordinary follower output
  supplies forward contact. LIFE 1 enables the opening wardrobe's `AF_MOVABLE`;
  `resolve_actor_contacts` alone moves it.
- Mouse release, focus loss, modal entry, target/floor/room invalidation, and
  bounded stall share idempotent cancellation. Pushing never asserts Action.
- Focused proof: `make prove-mouse-only`; evidence:
  `docs/mouse-hold-push-proof.md`.
```

- [ ] **Step 5: Commit the proof and context**

```bash
git add tests/test_mouse_only.py docs/mouse-hold-push-proof.md CONTEXT.md
git commit -m "test: prove mouse hold pushing"
```

- [ ] **Step 6: Verify the final worktree and commit range**

Run:

```bash
git status --short
git log --oneline --decorate -8
```

Expected: clean worktree; the held-push commits are present after the approved spec and plan commits.
