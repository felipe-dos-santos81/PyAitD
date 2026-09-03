# Mouse Fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the held pointer follow go where the player points (no floor behind walls, bounded snapping, the right depth in neighbouring rooms, visible approach cells), survive a camera cut without redirecting on hand jitter, and show the player where the hero is heading.

**Architecture:** Picking gains an occlusion filter in `engine/nav/picking.py`: a floor hit whose camera ray crosses a hard collision box is discarded, and snapping is accepted only inside a screen-pixel budget. `follow_pointer` in `app/shell.py` opens a pointer dead zone after a camera cut. `render_cursor` in `app/ui.py` grows a destination marker, a hover preview and a press ring. No gesture, engine simulation, or mouse-contract change.

**Tech Stack:** Python 3.12, numpy, pygame-ce, pytest. Headless tests run with `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`.

**Spec:** `docs/superpowers/specs/2026-09-02-mouse-fidelity-design.md`

## Global Constraints

- Dependencies stay pygame-ce, moderngl, numpy, pytest. Nothing new.
- `engine/` modules stay pygame-free (`tests/test_layering.py` enforces it).
- Every test file declares exactly one subject marker as module-level `pytestmark` (`engine`, `render`, `shell`, `tools`, `meta`), pinned by `tests/test_test_groups.py`. New tests go in existing files here, so no new marker is needed.
- Tests take the `data_dir` and `profile` fixtures from `tests/conftest.py`; never import `AITD1` directly in a test.
- The hero never moves under mouse control unless the left button is down.
- `pick_floor_any_room(logical_pos, floor, hero_room, cam_slot, floor_y)` keeps its positional signature and `(x, z, room) | None` return; new parameters are keyword-only with defaults.
- Constants: `SNAP_BUDGET_PX = 8`, `CUT_DEAD_ZONE_PX = 6`.
- Never mass-reformat. No lint or formatter is configured; `make test` is the only gate.
- Run tests as `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest <path> -q`.
- Commit messages end with:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_017fx74B23f5ptB2gUFRz9KE
  ```

## File Structure

| File | Responsibility after this plan |
|---|---|
| `PyAitD/engine/nav/picking.py` | Screen to world picking. Gains `ray_box_hit`, `to_room_frame`, `floor_point_visible`, `viewed_floor_y`, `project_room_point`, `snap_accept`, `visible_accept`, and the `occlude` / `agent` keywords on `pick_floor_any_room`. |
| `PyAitD/engine/nav/navmesh.py` | Walkable grid. `nearest_walkable` and `approach_cell` take an optional `accept(x, z) -> bool` filter. |
| `PyAitD/app/shell.py` | `resolve_play_click` threads the accept predicates and viewed-room floor height; `follow_pointer` gets the cut dead zone; the cursor site passes marker, preview, held and settling. |
| `PyAitD/app/ui.py` | `InputBuffer` gains `follow_camera` and `follow_settle_origin`; `reset_input` clears them; `render_cursor` draws marker, preview and ring. |
| `tools/prove_mouse.py` | Adds a per-camera count of attic pixels that occlusion now refuses. |
| `docs/mouse-fidelity-proof.md` | Automated gates and the windowed attestation rows. |
| `tests/test_picking.py`, `tests/test_navmesh.py`, `tests/test_play_loop.py`, `tests/test_ui_input.py`, `tests/test_ui_render.py` | The tests below, by layer. |

Coordinate facts every task relies on:

- Room-scale units are world units times 10. `Zone` hard cols (`PyAitD/engine/data/formats.py`) are axis-aligned boxes `x1, x2, y1, y2, z1, z2` in the owning room's frame.
- `CameraState.from_camera(camera, room.world_x, room.world_y, room.world_z).angles()` builds the camera in a room's frame. The camera position in that frame is `(state.x, state.y, state.z)`: `project_floor_point` subtracts exactly those before rotating.
- Moving a point from room P's frame to room R's frame is `(x - dx, y + dy, z + dz)` with `(dx, dy, dz) = 10 * (R.world - P.world)`, the asymmetric signs FITD's `AdjustZV` uses and `room_delta` documents.

---

### Task 1: Ray-box intersection and floor-point visibility

**Files:**
- Modify: `PyAitD/engine/nav/picking.py` (append after `_camera_state_global`, line 91-98)
- Test: `tests/test_picking.py`

**Interfaces:**
- Produces:
  - `ray_box_hit(origin, point, box) -> float | None`: parametric `t` in `(0, 1)` where the segment `origin -> point` first enters `box` (an object with `x1, x2, y1, y2, z1, z2`), else None. An origin inside the box yields None (the camera cannot be occluded by a box it sits in).
  - `to_room_frame(floor, from_room, to_room, x, y, z) -> (x, y, z)`.
  - `floor_point_visible(floor, global_cam_idx, room_idx, x, y, z, agent=None) -> bool`: True when no hard col of any room the camera views lies between the camera and the point. `agent=(half, y0, y1)` restricts the boxes to those overlapping the agent's Y band, the same rule `navmesh._subtract_hard_cols` uses so room-link zones do not count as walls.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_picking.py`:

```python
from types import SimpleNamespace

from PyAitD.engine.nav.picking import (
    floor_point_visible, ray_box_hit, to_room_frame,
)


def _box(x1, x2, y1, y2, z1, z2):
    return SimpleNamespace(x1=x1, x2=x2, y1=y1, y2=y2, z1=z1, z2=z2, type=0, parameter=0)


def test_ray_box_hit_reports_the_entry_parameter():
    box = _box(400, 600, -1000, 0, -100, 100)
    t = ray_box_hit((0, -500, 0), (1000, -500, 0), box)
    assert t is not None and abs(t - 0.4) < 1e-9


def test_ray_box_hit_misses_a_box_beside_the_segment():
    box = _box(400, 600, -1000, 0, 300, 500)
    assert ray_box_hit((0, -500, 0), (1000, -500, 0), box) is None


def test_ray_box_hit_ignores_a_box_past_the_point():
    box = _box(1200, 1400, -1000, 0, -100, 100)
    assert ray_box_hit((0, -500, 0), (1000, -500, 0), box) is None


def test_ray_box_hit_ignores_a_box_the_origin_sits_in():
    box = _box(-100, 100, -1000, 0, -100, 100)
    assert ray_box_hit((0, -500, 0), (1000, -500, 0), box) is None


def test_ray_box_hit_treats_a_point_inside_the_box_as_occluded():
    box = _box(800, 1200, -1000, 0, -100, 100)
    t = ray_box_hit((0, -500, 0), (1000, -500, 0), box)
    assert t is not None and abs(t - 0.8) < 1e-9


def test_to_room_frame_uses_the_asymmetric_signs(data_dir, profile):
    floor = Floor(data_dir, 0, profile)
    src, dst = floor.rooms[0], floor.rooms[1]
    dx = 10 * (dst.world_x - src.world_x)
    dy = 10 * (dst.world_y - src.world_y)
    dz = 10 * (dst.world_z - src.world_z)
    assert to_room_frame(floor, 0, 1, 100, 200, 300) == (100 - dx, 200 + dy, 300 + dz)


def test_floor_point_visible_rejects_a_point_behind_a_hard_col(data_dir, profile):
    # The camera sits at (state.x, state.y, state.z) in room frame. A box
    # placed on the segment from there to a floor point must hide the point;
    # the same box moved off the segment must not.
    floor = Floor(data_dir, 0, profile)
    room = floor.rooms[0]
    cam = room.camera_indices[0]
    state = _state(floor, 0, 0)
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    point = (hero.room_x, hero.world_y, hero.room_z)
    mid = tuple((a + b) / 2 for a, b in zip((state.x, state.y, state.z), point))
    saved = list(room.hard_cols)
    try:
        room.hard_cols = saved + [_box(
            mid[0] - 50, mid[0] + 50, mid[1] - 50, mid[1] + 50, mid[2] - 50, mid[2] + 50,
        )]
        assert floor_point_visible(floor, cam, 0, *point) is False
        room.hard_cols = saved + [_box(
            mid[0] + 5000, mid[0] + 5100, mid[1] - 50, mid[1] + 50, mid[2] - 50, mid[2] + 50,
        )]
        assert floor_point_visible(floor, cam, 0, *point) is True
    finally:
        room.hard_cols = saved


def test_floor_point_visible_skips_boxes_outside_the_agent_band(data_dir, profile):
    floor = Floor(data_dir, 0, profile)
    room = floor.rooms[0]
    cam = room.camera_indices[0]
    state = _state(floor, 0, 0)
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    point = (hero.room_x, hero.world_y, hero.room_z)
    mid = tuple((a + b) / 2 for a, b in zip((state.x, state.y, state.z), point))
    saved = list(room.hard_cols)
    try:
        room.hard_cols = saved + [_box(
            mid[0] - 50, mid[0] + 50, mid[1] - 50, mid[1] + 50, mid[2] - 50, mid[2] + 50,
        )]
        # a band that cannot overlap the box: entirely above it
        band = (0, mid[1] - 10000, mid[1] - 9000)
        assert floor_point_visible(floor, cam, 0, *point, agent=band) is True
    finally:
        room.hard_cols = saved
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_picking.py -q -k "ray_box or to_room_frame or floor_point_visible"`
Expected: FAIL with `ImportError: cannot import name 'ray_box_hit'`.

- [ ] **Step 3: Implement the helpers**

In `PyAitD/engine/nav/picking.py`, after `_camera_state_global` add:

```python
def ray_box_hit(origin, point, box):
    """Parametric t in (0, 1) where the segment origin -> point first enters
    the axis-aligned box, or None. A slab test per axis; an origin already
    inside the box is not an occlusion (t would be 0), a point inside it is
    (the segment enters before reaching it)."""
    t_in, t_out = 0.0, 1.0
    for o, p, lo, hi in (
        (origin[0], point[0], box.x1, box.x2),
        (origin[1], point[1], box.y1, box.y2),
        (origin[2], point[2], box.z1, box.z2),
    ):
        d = p - o
        if abs(d) < 1e-9:
            if o < lo or o > hi:
                return None
            continue
        t0, t1 = (lo - o) / d, (hi - o) / d
        if t0 > t1:
            t0, t1 = t1, t0
        t_in, t_out = max(t_in, t0), min(t_out, t1)
        if t_in > t_out:
            return None
    return t_in if 0.0 < t_in < 1.0 else None


def to_room_frame(floor, from_room, to_room, x, y, z):
    """Re-frame a room-scale point from one room's origin to another's, with
    FITD's asymmetric signs (x minus, y plus, z plus -- world.room_delta)."""
    src, dst = floor.rooms[from_room], floor.rooms[to_room]
    dx = 10 * (dst.world_x - src.world_x)
    dy = 10 * (dst.world_y - src.world_y)
    dz = 10 * (dst.world_z - src.world_z)
    return (x - dx, y + dy, z + dz)


def _in_band(box, agent):
    if agent is None:
        return True
    _half, y0, y1 = agent
    return y0 < box.y2 and box.y1 < y1


def floor_point_visible(floor, global_cam_idx, room_idx, x, y, z, agent=None):
    """True when no hard col of any room this camera views lies on the
    segment from the camera to the point (given in room_idx's frame).

    Each viewed room's boxes are tested in that room's own frame: the camera
    is rebuilt there (its position is (state.x, state.y, state.z), what
    project_floor_point subtracts) and the point is re-framed with
    to_room_frame. `agent` = (half, y0, y1) keeps only boxes overlapping the
    agent's Y band, navmesh._subtract_hard_cols's rule, so a room link the
    hero can walk through is not a wall.
    """
    viewed = [vr.viewed_room_idx for vr in floor.cameras[global_cam_idx].viewed_rooms]
    rooms = [room_idx] + [r for r in viewed if r != room_idx and r < len(floor.rooms)]
    for other in rooms:
        state = _camera_state_global(floor, other, global_cam_idx)
        origin = (state.x, state.y, state.z)
        target = to_room_frame(floor, room_idx, other, x, y, z)
        for box in floor.rooms[other].hard_cols:
            if not _in_band(box, agent):
                continue
            if ray_box_hit(origin, target, box) is not None:
                return False
    return True
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_picking.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/nav/picking.py tests/test_picking.py
git commit -m "feat: ray-box occlusion and floor-point visibility for picking"
```

---

### Task 2: Occlusion and viewed-room depth in `pick_floor_any_room`

**Files:**
- Modify: `PyAitD/engine/nav/picking.py:138-153` (`pick_floor_any_room`)
- Test: `tests/test_picking.py`

**Interfaces:**
- Consumes: `floor_point_visible` (Task 1).
- Produces:
  - `viewed_floor_y(floor, hero_room, room_idx, floor_y) -> int`: the floor plane height for `room_idx` when the hero stands at `floor_y` in `hero_room`; `floor_y` itself for the hero's room.
  - `pick_floor_any_room(logical_pos, floor, hero_room, cam_slot, floor_y, *, occlude=True, agent=None)`: with `occlude=False` behaves exactly as before this plan (the tool and tests use it as the baseline).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_picking.py`:

```python
from PyAitD.engine.nav.navmesh import agent_extent
from PyAitD.engine.nav.picking import viewed_floor_y


def _attic_pixels():
    return [(x, y) for y in range(199, 40, -5) for x in range(2, 320, 5)]


def test_viewed_floor_y_is_the_hero_height_in_the_hero_room(data_dir, profile):
    floor = Floor(data_dir, 0, profile)
    assert viewed_floor_y(floor, 0, 0, -1234) == -1234


def test_viewed_floor_y_follows_the_other_room_s_origin(data_dir, profile):
    floor = Floor(data_dir, 0, profile)
    dy = 10 * (floor.rooms[1].world_y - floor.rooms[0].world_y)
    assert viewed_floor_y(floor, 0, 1, 500) == 500 + dy


def test_occlusion_only_removes_picks_and_removes_some(data_dir, profile):
    # Under every attic camera the occluded pick is a subset of the old one:
    # a pixel that still picks lands on the same point, and at least one
    # camera has a pixel that used to fall through a wall onto the floor
    # behind it and no longer does.
    floor = Floor(data_dir, 0, profile)
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    agent = agent_extent(hero)
    refused_anywhere = 0
    for cam_slot in range(len(floor.rooms[hero.room].camera_indices)):
        for pixel in _attic_pixels():
            old = pick_floor_any_room(
                pixel, floor, hero.room, cam_slot, hero.world_y, occlude=False,
            )
            new = pick_floor_any_room(
                pixel, floor, hero.room, cam_slot, hero.world_y, agent=agent,
            )
            if new is not None:
                assert new == old, f"camera {cam_slot} pixel {pixel} moved"
            elif old is not None:
                refused_anywhere += 1
    assert refused_anywhere > 0, "no attic pixel was ever occluded"


def test_occlude_false_is_the_pre_occlusion_baseline(data_dir, profile):
    # occlude=False must ignore hard cols entirely: adding a box in front of
    # every point changes nothing for it, while the default pick refuses.
    floor = Floor(data_dir, 0, profile)
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    slot = game.new_num_camera
    pixel = next(
        p for p in _attic_pixels()
        if (hit := pick_floor_any_room(p, floor, hero.room, slot, hero.world_y)) is not None
        and hit[2] == hero.room
    )
    baseline = pick_floor_any_room(pixel, floor, hero.room, slot, hero.world_y, occlude=False)
    assert baseline is not None
    # a box half-way along the camera ray to the picked point (the box must
    # not contain the camera: an origin inside a box is never an occlusion)
    x, z, room_idx = baseline
    state = _state(floor, room_idx, slot)
    mid = ((state.x + x) / 2, (state.y + hero.world_y) / 2, (state.z + z) / 2)
    room = floor.rooms[room_idx]
    saved = list(room.hard_cols)
    try:
        room.hard_cols = saved + [_box(
            mid[0] - 50, mid[0] + 50, mid[1] - 50, mid[1] + 50, mid[2] - 50, mid[2] + 50,
        )]
        assert pick_floor_any_room(
            pixel, floor, hero.room, slot, hero.world_y, occlude=False,
        ) == baseline
        assert pick_floor_any_room(pixel, floor, hero.room, slot, hero.world_y) is None
    finally:
        room.hard_cols = saved
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_picking.py -q -k "viewed_floor_y or occlusion or occlude_false"`
Expected: FAIL with `ImportError: cannot import name 'viewed_floor_y'`.

- [ ] **Step 3: Implement**

Replace `pick_floor_any_room` in `PyAitD/engine/nav/picking.py` with:

```python
def viewed_floor_y(floor, hero_room, room_idx, floor_y):
    """The floor plane height to pick room_idx at when the hero stands at
    floor_y in hero_room: the hero's own height in the hero's room, and that
    height re-framed into a viewed room's origin otherwise, so a lower or
    higher neighbouring room is picked at its own depth."""
    if room_idx == hero_room:
        return floor_y
    return to_room_frame(floor, hero_room, room_idx, 0, floor_y, 0)[1]


def pick_floor_any_room(
        logical_pos, floor, hero_room, cam_slot, floor_y, *, occlude=True, agent=None,
):
    """Pick across every room this camera views. Returns (x, z, room) or None.

    The hero's own room is tried first: walking inside the current room never
    needs a transition, so it wins any overlap. With `occlude` a floor hit
    whose camera ray crosses a hard col (a wall, a piece of furniture) is
    refused rather than returned as "the floor behind it"; `occlude=False`
    is the pre-occlusion pick, kept as the baseline the proof tool and the
    tests compare against.
    """
    global_cam_idx = floor.rooms[hero_room].camera_indices[cam_slot]
    viewed = [vr.viewed_room_idx for vr in floor.cameras[global_cam_idx].viewed_rooms]
    ordered = [hero_room] + [r for r in viewed if r != hero_room]
    for room_idx in ordered:
        if room_idx >= len(floor.rooms):
            continue
        room_floor_y = viewed_floor_y(floor, hero_room, room_idx, floor_y)
        hit = pick_floor_in_room(logical_pos, floor, room_idx, global_cam_idx, room_floor_y)
        if hit is None:
            continue
        if occlude and not floor_point_visible(
                floor, global_cam_idx, room_idx, hit[0], room_floor_y, hit[1], agent,
        ):
            return None
        return (hit[0], hit[1], room_idx)
    return None
```

Note the occluded case returns `None` rather than trying the next room: the pixel is on a wall, and the next room's plane would be an even farther fall-through.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_picking.py tests/test_mouse_only.py tests/test_play_loop.py -q`
Expected: all PASS. If a `test_play_loop.py` or `test_mouse_only.py` test that scans real pixels now fails because its chosen pixel is refused, read its fixture: the scans (`_sampled_pixels`, `_cut_fixture`) search for a pixel that resolves `walk`, so they self-adjust; a hard-coded pixel must be replaced by a scanned one, following `_cut_fixture`'s pattern.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/nav/picking.py tests/test_picking.py
git commit -m "feat: refuse floor picks hidden behind hard cols, pick viewed rooms at their own depth"
```

---

### Task 3: Snap budget and visible approach cells

**Files:**
- Modify: `PyAitD/engine/nav/navmesh.py:171-228` (`approach_cell`, `nearest_walkable`)
- Modify: `PyAitD/engine/nav/picking.py` (append `project_room_point`, `snap_accept`, `visible_accept`)
- Modify: `PyAitD/app/shell.py:364-450` (`resolve_play_click`)
- Test: `tests/test_navmesh.py`, `tests/test_picking.py`, `tests/test_play_loop.py`

**Interfaces:**
- Consumes: `floor_point_visible`, `viewed_floor_y` (Tasks 1-2).
- Produces:
  - `nearest_walkable(mesh, x, z, max_cells=6, accept=None)` and `approach_cell(mesh, x, z, from_x, from_z, max_cells=TARGET_SNAP_CELLS, accept=None)`: `accept(x, z) -> bool` filters ring candidates; None keeps today's behaviour. A walkable `(x, z)` itself is returned without consulting `accept`.
  - `SNAP_BUDGET_PX = 8` in `picking.py`.
  - `project_room_point(floor, hero_room, cam_slot, room_idx, x, y, z) -> (sx, sy) | None`: a room-frame point on screen under the hero room's camera slot, None when unprojectable or outside the 320x200 frame.
  - `snap_accept(floor, hero_room, cam_slot, room_idx, floor_y, logical_pos, agent=None, budget=SNAP_BUDGET_PX)` and `visible_accept(floor, hero_room, cam_slot, room_idx, floor_y, agent=None)`: predicates for the two searches.

- [ ] **Step 1: Write the failing navmesh tests**

Append to `tests/test_navmesh.py`:

```python
def test_nearest_walkable_honours_the_accept_filter(data_dir, profile):
    _game, hero = _hero_agent(data_dir, profile)
    mesh = build_room_mesh(Floor(data_dir, 0, profile), 0, agent_extent(hero))
    blocked = next(
        mesh.center_of(i, j)
        for i in range(mesh.shape[0]) for j in range(mesh.shape[1])
        if not mesh.walkable[i, j] and 20 < i < 130 and 20 < j < 120
    )
    unfiltered = nearest_walkable(mesh, *blocked)
    assert unfiltered is not None
    assert nearest_walkable(mesh, *blocked, accept=lambda x, z: False) is None
    seen = []
    filtered = nearest_walkable(
        mesh, *blocked, accept=lambda x, z: seen.append((x, z)) or (x, z) != unfiltered,
    )
    assert filtered is not None and filtered != unfiltered
    assert unfiltered in seen, "the filter saw the candidate it rejected"


def test_nearest_walkable_returns_a_walkable_point_without_asking(data_dir, profile):
    _game, hero = _hero_agent(data_dir, profile)
    mesh = build_room_mesh(Floor(data_dir, 0, profile), 0, agent_extent(hero))
    walkable = next(
        mesh.center_of(i, j)
        for i in range(mesh.shape[0]) for j in range(mesh.shape[1])
        if mesh.walkable[i, j]
    )
    assert nearest_walkable(mesh, *walkable, accept=lambda x, z: False) == walkable


def test_approach_cell_honours_the_accept_filter(data_dir, profile):
    game, hero = _hero_agent(data_dir, profile)
    mesh = build_room_mesh(Floor(data_dir, 0, profile), 0, agent_extent(hero))
    target = game.actors[10]
    spot = approach_cell(mesh, target.room_x, target.room_z, hero.room_x, hero.room_z)
    assert spot == (4060, -3870)
    assert approach_cell(
        mesh, target.room_x, target.room_z, hero.room_x, hero.room_z,
        accept=lambda x, z: False,
    ) is None
    other = approach_cell(
        mesh, target.room_x, target.room_z, hero.room_x, hero.room_z,
        accept=lambda x, z: (x, z) != spot,
    )
    assert other is not None and other != spot and mesh.is_walkable(*other)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_navmesh.py -q -k accept`
Expected: FAIL with `TypeError: ... unexpected keyword argument 'accept'`.

- [ ] **Step 3: Add the filter to both searches**

In `PyAitD/engine/nav/navmesh.py`, change `approach_cell`'s signature and ring body:

```python
def approach_cell(mesh, x, z, from_x, from_z, max_cells=TARGET_SNAP_CELLS, accept=None):
    """Where to stand to reach (x, z), coming from (from_x, from_z).

    Rings outward from the target and takes the first ring's cell closest to the
    approaching actor, so the hero stops on its own side of the object instead
    of walking around it. Unlike nearest_walkable this accepts a target outside
    the grid (an object can sit past the cover-zone bounds) by clamping the
    search origin. `accept(x, z)` vetoes candidates (the caller's visibility
    rule); None accepts every walkable cell. None when no walkable, accepted
    cell is within max_cells.
    """
    if mesh.is_walkable(x, z):
        return (x, z)
    nx, nz = mesh.shape
    origin_i = _clamp_cell(round((x - mesh.x0) / mesh.step), nx)
    origin_j = _clamp_cell(round((z - mesh.z0) / mesh.step), nz)
    from_i = (from_x - mesh.x0) / mesh.step
    from_j = (from_z - mesh.z0) / mesh.step
    for radius in range(0, max_cells + 1):
        best = None
        for di in range(-radius, radius + 1):
            for dj in range(-radius, radius + 1):
                if max(abs(di), abs(dj)) != radius:
                    continue
                i, j = origin_i + di, origin_j + dj
                if not (0 <= i < nx and 0 <= j < nz) or not mesh.walkable[i, j]:
                    continue
                if accept is not None and not accept(*mesh.center_of(i, j)):
                    continue
                score = (i - from_i) ** 2 + (j - from_j) ** 2
                if best is None or score < best[0]:
                    best = (score, (i, j))
        if best is not None:
            return mesh.center_of(*best[1])
    return None
```

Keep whatever the function's tail was after the loop (read lines 201-205 before replacing; the `return mesh.center_of(...)` / `return None` pair is the whole tail). Then `nearest_walkable`:

```python
def nearest_walkable(mesh, x, z, max_cells=6, accept=None):
    """Closest walkable cell centre to (x, z), searching outward in rings.
    `accept(x, z)` vetoes candidates; a walkable (x, z) itself is returned
    without asking, since it is exactly what was pointed at."""
    if mesh.is_walkable(x, z):
        return (x, z)
    origin = mesh.cell_of(x, z)
    if origin is None:
        return None
    nx, nz = mesh.shape
    for radius in range(1, max_cells + 1):
        best = None
        for di in range(-radius, radius + 1):
            for dj in range(-radius, radius + 1):
                if max(abs(di), abs(dj)) != radius:
                    continue
                i, j = origin[0] + di, origin[1] + dj
                if not (0 <= i < nx and 0 <= j < nz) or not mesh.walkable[i, j]:
                    continue
                if accept is not None and not accept(*mesh.center_of(i, j)):
                    continue
                dist = di * di + dj * dj
                if best is None or dist < best[0]:
                    best = (dist, (i, j))
        if best is not None:
            return mesh.center_of(*best[1])
    return None
```

- [ ] **Step 4: Run the navmesh tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_navmesh.py -q`
Expected: all PASS.

- [ ] **Step 5: Write the failing picking tests for the predicates**

Append to `tests/test_picking.py`:

```python
from PyAitD.engine.nav.picking import (
    SNAP_BUDGET_PX, project_room_point, snap_accept, visible_accept,
)


def test_project_room_point_matches_project_floor_point_in_the_hero_room(data_dir, profile):
    floor = Floor(data_dir, 0, profile)
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    slot = game.new_num_camera
    state = _state(floor, hero.room, slot)
    expected = project_floor_point(state, hero.room_x, hero.world_y, hero.room_z)
    got = project_room_point(floor, hero.room, slot, hero.room, hero.room_x, hero.world_y, hero.room_z)
    assert got is not None and expected is not None
    assert abs(got[0] - expected[0]) < 1e-9 and abs(got[1] - expected[1]) < 1e-9


def test_project_room_point_is_none_off_the_frame(data_dir, profile):
    floor = Floor(data_dir, 0, profile)
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    slot = game.new_num_camera
    # far enough along +x that no attic camera keeps it in 320x200
    assert project_room_point(
        floor, hero.room, slot, hero.room, hero.room_x + 200000, hero.world_y, hero.room_z,
    ) is None


def test_snap_accept_bounds_candidates_in_screen_pixels(data_dir, profile):
    floor = Floor(data_dir, 0, profile)
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    slot = game.new_num_camera
    here = project_room_point(floor, hero.room, slot, hero.room, hero.room_x, hero.world_y, hero.room_z)
    pointer = (int(here[0]), int(here[1]))
    accept = snap_accept(floor, hero.room, slot, hero.room, hero.world_y, pointer)
    assert accept(hero.room_x, hero.room_z) is True
    # walk +x until the projection leaves the budget; that candidate is refused
    step = 100
    while True:
        x = hero.room_x + step
        screen = project_room_point(floor, hero.room, slot, hero.room, x, hero.world_y, hero.room_z)
        if screen is None or max(abs(screen[0] - pointer[0]), abs(screen[1] - pointer[1])) > SNAP_BUDGET_PX:
            break
        step += 100
    assert accept(x, hero.room_z) is False
    assert SNAP_BUDGET_PX == 8


def test_visible_accept_is_floor_point_visible_under_the_hero_camera(data_dir, profile):
    floor = Floor(data_dir, 0, profile)
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    slot = game.new_num_camera
    cam = floor.rooms[hero.room].camera_indices[slot]
    accept = visible_accept(floor, hero.room, slot, hero.room, hero.world_y)
    assert accept(hero.room_x, hero.room_z) == floor_point_visible(
        floor, cam, hero.room, hero.room_x, hero.world_y, hero.room_z,
    )
```

- [ ] **Step 6: Run them to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_picking.py -q -k "project_room_point or snap_accept or visible_accept"`
Expected: FAIL with `ImportError: cannot import name 'SNAP_BUDGET_PX'`.

- [ ] **Step 7: Implement the predicates**

Append to `PyAitD/engine/nav/picking.py`:

```python
SNAP_BUDGET_PX = 8   # how far, on screen, a snapped walk may land from the
                     # pointer: past this the pick is refused, never a surprise


def project_room_point(floor, hero_room, cam_slot, room_idx, x, y, z):
    """A room-frame point on the logical screen under the hero room's camera
    slot, or None when it is behind the near clip or off the 320x200 frame."""
    global_cam_idx = floor.rooms[hero_room].camera_indices[cam_slot]
    state = _camera_state_global(floor, room_idx, global_cam_idx)
    screen = project_floor_point(state, x, y, z)
    if screen is None:
        return None
    if not (0 <= screen[0] < _LOGICAL_W and 0 <= screen[1] < _LOGICAL_H):
        return None
    return screen


def visible_accept(floor, hero_room, cam_slot, room_idx, floor_y, agent=None):
    """Candidate filter: the cell must be visible from the camera on screen."""
    global_cam_idx = floor.rooms[hero_room].camera_indices[cam_slot]

    def accept(x, z):
        return floor_point_visible(floor, global_cam_idx, room_idx, x, floor_y, z, agent)
    return accept


def snap_accept(
        floor, hero_room, cam_slot, room_idx, floor_y, logical_pos, agent=None,
        budget=SNAP_BUDGET_PX,
):
    """Candidate filter for a snapped walk: on screen within `budget` logical
    pixels of the pointer on both axes, and visible from the camera."""
    visible = visible_accept(floor, hero_room, cam_slot, room_idx, floor_y, agent)

    def accept(x, z):
        screen = project_room_point(floor, hero_room, cam_slot, room_idx, x, floor_y, z)
        if screen is None:
            return False
        if (abs(screen[0] - logical_pos[0]) > budget
                or abs(screen[1] - logical_pos[1]) > budget):
            return False
        return visible(x, z)
    return accept
```

`_LOGICAL_W` and `_LOGICAL_H` are already defined further down the module (line 178-179); Python resolves them at call time, so the order is fine.

- [ ] **Step 8: Run the picking tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_picking.py -q`
Expected: all PASS.

- [ ] **Step 9: Write the failing resolver test**

Append to `tests/test_play_loop.py` (near the other `resolve_play_click` tests around line 875):

```python
def test_a_snap_past_the_budget_is_blocked_not_a_far_walk(data_dir, profile, monkeypatch):
    # A pointer on a blocked cell whose only walkable neighbours project more
    # than SNAP_BUDGET_PX away must resolve blocked: the hero never heads for
    # somewhere visibly away from the pointer. nearest_walkable is replaced
    # by a stand-in that refuses whenever a filter is given, which is exactly
    # what the real search does when every ring candidate fails the budget.
    import PyAitD.app.shell as main
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    hero = game.actors[game.current_camera_target_actor]
    agent = main.agent_extent(hero)
    pixel = next(
        p for p in _sampled_pixels()
        if (hit := main.pick_floor_any_room(p, floor, hero.room, game.num_camera, hero.world_y, agent=agent)) is not None
        and not game.nav_meshes.mesh_for(floor, hit[2], agent).is_walkable(hit[0], hit[1])
    )
    assert resolve_play_click(game, floor, pixel, [])[0] == "walk", "the real snap accepts this pixel"

    seen = {}

    def refusing(mesh, x, z, max_cells=6, accept=None):
        seen["accept"] = accept
        return None
    monkeypatch.setattr(main, "nearest_walkable", refusing)
    assert resolve_play_click(game, floor, pixel, [])[0] == "blocked"
    assert callable(seen["accept"]), "the resolver did not hand nearest_walkable a filter"


def test_object_approach_uses_a_visibility_filter(data_dir, profile, monkeypatch):
    import PyAitD.app.shell as main
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    seen = {}
    real = main.approach_cell

    def spy(mesh, x, z, from_x, from_z, max_cells=main.TARGET_SNAP_CELLS, accept=None):
        seen["accept"] = accept
        return real(mesh, x, z, from_x, from_z, max_cells, accept)
    monkeypatch.setattr(main, "approach_cell", spy)
    # world object 13 (actor 10) is floor 0's clickable interactable; hand the
    # resolver its bbox so the click lands on it
    target = game.actors[10]
    draw_list = [(10, (0, 0, 319, 199))]
    kind, _payload = resolve_play_click(game, floor, (160, 100), draw_list)
    assert kind in ("target", "blocked")
    assert callable(seen.get("accept")), "the resolver did not hand approach_cell a filter"
```

`main.TARGET_SNAP_CELLS` requires adding `TARGET_SNAP_CELLS` to the navmesh import in step 11. If the first test's pixel scan finds nothing (every pickable attic pixel is already walkable under the opening camera), loop `game.num_camera` over the room's camera slots inside the scan until one qualifies.

- [ ] **Step 10: Run it to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_play_loop.py -q -k snap_past_the_budget`
Expected: FAIL with `AttributeError: module 'PyAitD.app.shell' has no attribute 'snap_accept'` (or `nearest_walkable` not a module attribute: `resolve_play_click` imports both locally today, so the monkeypatch targets do not exist yet).

- [ ] **Step 11: Wire the resolver**

In `PyAitD/app/shell.py`, move the two navmesh imports used by `resolve_play_click` to module level so tests can monkeypatch them, and thread the predicates. At the top of `shell.py` (with the other module-level imports; check it does not create an import cycle by running the tests) add:

```python
from PyAitD.engine.nav.navmesh import (
    TARGET_SNAP_CELLS, agent_extent, approach_cell, nearest_walkable,
)
from PyAitD.engine.nav.picking import (
    pick_actor, pick_floor_any_room, snap_accept, viewed_floor_y, visible_accept,
)
```

and delete the matching names from the local import inside `resolve_play_click`. Then change the body from `agent = agent_extent(hero)` onward so the object branch reads:

```python
        mesh = game.nav_meshes.mesh_for(floor, target.room, agent)
        if mesh is not None:
            from_x, from_z = hero.room_x, hero.room_z
            if hero.room != target.room:
                dx, _dy, dz = room_delta(game, hero.room, target.room)
                from_x, from_z = from_x - dx, from_z + dz
            spot = approach_cell(
                mesh, dest_x, dest_z, from_x, from_z,
                accept=visible_accept(
                    floor, hero.room, game.num_camera, target.room,
                    viewed_floor_y(floor, hero.room, target.room, hero.world_y), agent,
                ),
            )
            if spot is not None:
                dest_x, dest_z = spot
            else:
                return ("blocked", None)
```

and the floor branch reads:

```python
    picked = pick_floor_any_room(
        logical_pos, floor, hero.room, game.num_camera, hero.world_y, agent=agent,
    )
    if picked is None:
        return ("blocked", None)
    dest_x, dest_z, dest_room = picked
    mesh = game.nav_meshes.mesh_for(floor, dest_room, agent)
    if mesh is not None and mesh.walkable.any():
        snapped = nearest_walkable(
            mesh, dest_x, dest_z,
            accept=snap_accept(
                floor, hero.room, game.num_camera, dest_room,
                viewed_floor_y(floor, hero.room, dest_room, hero.world_y),
                logical_pos, agent,
            ),
        )
        if snapped is None:
            return ("blocked", None)
        dest_x, dest_z = snapped
    return ("walk", (dest_x, dest_z, dest_room, -1))
```

Keep the existing comments above each branch.

- [ ] **Step 12: Run the shell and engine groups**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest -m "engine or shell" -q`
Expected: all PASS. `tests/test_layering.py` will fail if the new module-level imports break the package layering rules; if so, keep the imports local inside `resolve_play_click` and change the test's monkeypatch targets to `PyAitD.engine.nav.picking` and `PyAitD.engine.nav.navmesh` instead.

- [ ] **Step 13: Commit**

```bash
git add PyAitD/engine/nav/navmesh.py PyAitD/engine/nav/picking.py PyAitD/app/shell.py tests/test_navmesh.py tests/test_picking.py tests/test_play_loop.py
git commit -m "feat: bound walk snapping to eight screen pixels and keep approach cells visible"
```

---

### Task 4: The camera-cut dead zone

**Files:**
- Modify: `PyAitD/app/ui.py:48-90` (`InputBuffer`), `PyAitD/app/ui.py:146-161` (`reset_input`)
- Modify: `PyAitD/app/shell.py:453-503` (`route_play_click`), `:525-583` (`follow_pointer`), `:590-640` (`_drop_destination`, `_cancel_follow`, `_rebase_follow`)
- Test: `tests/test_ui_input.py`, `tests/test_play_loop.py`

**Interfaces:**
- Produces:
  - `InputBuffer.follow_camera: int | None` (camera slot of the last resolution) and `InputBuffer.follow_settle_origin: tuple[int, int] | None` (pointer position at the cut while the dead zone is open).
  - `CUT_DEAD_ZONE_PX = 6` in `shell.py`.
  - Dead-zone rule: after a cut (`game.num_camera != follow_camera`), `follow_pointer` re-resolves only once the pointer has moved more than `CUT_DEAD_ZONE_PX` on either axis (Chebyshev) from `follow_settle_origin`.

- [ ] **Step 1: Write the failing input-buffer test**

Append to `tests/test_ui_input.py`:

```python
def test_reset_input_clears_the_cut_settle_state():
    from PyAitD.app.ui import InputBuffer, reset_input
    state = InputBuffer(follow_camera=2, follow_settle_origin=(10, 10))
    reset_input(state)
    assert state.follow_camera is None
    assert state.follow_settle_origin is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_ui_input.py -q -k settle`
Expected: FAIL with `TypeError: InputBuffer.__init__() got an unexpected keyword argument 'follow_camera'`.

- [ ] **Step 3: Add the fields**

In `PyAitD/app/ui.py`, after `follow_pos` in `InputBuffer` add:

```python
    # The camera slot follow_pos was resolved under. When game.num_camera no
    # longer matches, a cut happened: shell.follow_pointer keeps the
    # destination and opens a dead zone instead of re-resolving the first
    # pixel of drift under a camera the hand never aimed at.
    follow_camera: int | None = None
    # Where the pointer was when the cut was noticed. While set, motion
    # within shell.CUT_DEAD_ZONE_PX of it is settling, not a gesture.
    follow_settle_origin: tuple[int, int] | None = None
```

In `reset_input`, after `state.follow_pos = None` add:

```python
    state.follow_camera = None
    state.follow_settle_origin = None
```

- [ ] **Step 4: Run it to verify it passes**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_ui_input.py -q`
Expected: all PASS.

- [ ] **Step 5: Write the failing follow tests**

Append to `tests/test_play_loop.py` after `test_pointer_motion_after_a_cut_still_retargets`:

```python
def test_a_one_pixel_drift_after_a_cut_does_not_retarget(data_dir, profile):
    # The hand did not move; the cut and the pointer's own jitter did. Within
    # CUT_DEAD_ZONE_PX of where the pointer was at the cut, the destination
    # stays and the follow is settling.
    import PyAitD.app.shell as main
    game, floor, buf, pixel, cut_slot, before = _cut_fixture(
        data_dir, profile, "walk",
    )
    assert buf.follow_camera == game.new_num_camera

    game.num_camera = cut_slot
    drifted = (pixel[0] + 1, pixel[1])
    buf.pointer_pos = drifted
    main.follow_pointer(game, ModalSession(), floor, drifted, [], buf)

    assert game.nav_intent is not None, "the drift stopped the hero"
    after = (game.nav_intent.dest_x, game.nav_intent.dest_z, game.nav_intent.room)
    assert after == before, "a one-pixel drift after a cut retargeted"
    assert buf.follow_settle_origin == pixel
    assert main.CUT_DEAD_ZONE_PX == 6


def test_motion_past_the_dead_zone_retargets_and_closes_it(data_dir, profile):
    import PyAitD.app.shell as main
    game, floor, buf, pixel, cut_slot, before = _cut_fixture(
        data_dir, profile, "walk",
    )
    game.num_camera = cut_slot
    # settle first
    drifted = (pixel[0] + 1, pixel[1])
    buf.pointer_pos = drifted
    main.follow_pointer(game, ModalSession(), floor, drifted, [], buf)
    assert buf.follow_settle_origin == pixel
    moved = next(
        candidate
        for candidate in _sampled_pixels()
        if max(abs(candidate[0] - pixel[0]), abs(candidate[1] - pixel[1])) > main.CUT_DEAD_ZONE_PX
        and (resolved := resolve_play_click(game, floor, candidate, []))[0] == "walk"
        and resolved[1][:3] != before
    )
    buf.pointer_pos = moved
    main.follow_pointer(game, ModalSession(), floor, moved, [], buf)

    assert game.nav_intent is not None
    after = (game.nav_intent.dest_x, game.nav_intent.dest_z, game.nav_intent.room)
    assert after != before, "the hand moved past the dead zone and was ignored"
    assert buf.follow_settle_origin is None
    assert buf.follow_camera == cut_slot


def test_release_clears_the_settle_state(data_dir, profile):
    import PyAitD.app.shell as main
    game, floor, buf, pixel, cut_slot, before = _cut_fixture(
        data_dir, profile, "walk",
    )
    game.num_camera = cut_slot
    drifted = (pixel[0] + 1, pixel[1])
    buf.pointer_pos = drifted
    main.follow_pointer(game, ModalSession(), floor, drifted, [], buf)
    assert buf.follow_settle_origin is not None

    up = main.pygame.event.Event(main.pygame.MOUSEBUTTONUP, button=1)
    main._cancel_pointer_invalidation(game, up, buf)
    assert buf.follow_settle_origin is None
    assert buf.follow_camera is None
    assert game.nav_intent is None


def test_a_floor_change_clears_the_settle_state_but_keeps_the_hold(data_dir, profile):
    import PyAitD.app.shell as main
    game, floor, buf, pixel, cut_slot, before = _cut_fixture(
        data_dir, profile, "walk",
    )
    buf.follow_settle_origin = pixel
    buf.follow_camera = cut_slot
    main._rebase_follow(game, buf)
    assert buf.follow_settle_origin is None
    assert buf.follow_camera is None
    assert buf.follow_pos is None
    assert buf.pointer_held is True


def test_arrival_while_settling_leaves_the_follow_live(data_dir, profile):
    # The follower clearing the intent on arrival must not be mistaken for a
    # gesture: the hold stays live, no re-resolution of a still pointer.
    import PyAitD.app.shell as main
    game, floor, buf, pixel, cut_slot, before = _cut_fixture(
        data_dir, profile, "walk",
    )
    game.num_camera = cut_slot
    drifted = (pixel[0] + 1, pixel[1])
    buf.pointer_pos = drifted
    main.follow_pointer(game, ModalSession(), floor, drifted, [], buf)
    game.nav_intent = None   # what an arrival leaves behind
    main.follow_pointer(game, ModalSession(), floor, drifted, [], buf)
    assert game.nav_intent is None, "a still pointer was re-resolved while settling"
    assert buf.follow_last is not None, "the hold died"
    assert buf.pointer_held is True
```

- [ ] **Step 6: Run them to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_play_loop.py -q -k "dead_zone or settle or settling"`
Expected: FAIL. The first fails on `buf.follow_camera == game.new_num_camera` (never set) or on the drift retargeting.

- [ ] **Step 7: Implement the dead zone**

In `PyAitD/app/shell.py`, next to `DOUBLE_PRESS_TICKS` (or with the other module constants near the top) add:

```python
CUT_DEAD_ZONE_PX = 6   # after a camera cut the pointer must move this far on
                       # an axis before the hold re-resolves; smaller motion is
                       # the hand settling, not a gesture
```

In `route_play_click`, where `follow_pos` is set at the end, add the two lines:

```python
        input_buffer.follow_last = payload if kind != "push" else None
        input_buffer.follow_pos = logical_pos if kind != "push" else None
        input_buffer.follow_camera = game.num_camera if kind != "push" else None
        input_buffer.follow_settle_origin = None
        input_buffer.follow_spent = kind == "push"
```

In `follow_pointer`, replace the two lines

```python
    if logical_pos == input_buffer.follow_pos:
        return  # a still pointer means what it meant last frame
    input_buffer.follow_pos = logical_pos
```

with:

```python
    if logical_pos == input_buffer.follow_pos:
        return  # a still pointer means what it meant last frame
    if (input_buffer.follow_camera is not None
            and input_buffer.follow_camera != game.num_camera):
        # a cut: the pixel now means something else, but the hand has not
        # said so. Keep the destination until the pointer leaves the dead
        # zone around where it was when the cut landed.
        if input_buffer.follow_settle_origin is None:
            input_buffer.follow_settle_origin = (
                input_buffer.follow_pos
                if input_buffer.follow_pos is not None else logical_pos
            )
        ox, oy = input_buffer.follow_settle_origin
        if (abs(logical_pos[0] - ox) <= CUT_DEAD_ZONE_PX
                and abs(logical_pos[1] - oy) <= CUT_DEAD_ZONE_PX):
            return
        input_buffer.follow_settle_origin = None
    input_buffer.follow_pos = logical_pos
    input_buffer.follow_camera = game.num_camera
```

In `_drop_destination`, extend the buffer reset:

```python
    if input_buffer is not None:
        input_buffer.follow_last = None
        input_buffer.follow_pos = None
        input_buffer.follow_camera = None
        input_buffer.follow_settle_origin = None
```

`_cancel_follow` and `_rebase_follow` both call `_drop_destination`, so release, focus loss and a floor change all clear the settle state through the one path. In `test_arrival_while_settling_leaves_the_follow_live` the second call returns early on the dead zone, which is the behaviour wanted; note that `follow_last` survives because nothing cleared it.

- [ ] **Step 8: Run the shell group**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest -m shell -q`
Expected: all PASS, including the three pre-existing cut tests (`_sampled_pixels` has a 7-pixel stride, so `test_pointer_motion_after_a_cut_still_retargets` moves past the 6-pixel zone).

- [ ] **Step 9: Commit**

```bash
git add PyAitD/app/ui.py PyAitD/app/shell.py tests/test_ui_input.py tests/test_play_loop.py
git commit -m "feat: a six-pixel pointer dead zone after a camera cut"
```

---

### Task 5: Destination marker, hover preview and press ring

**Files:**
- Modify: `PyAitD/app/ui.py:1519-1560` (`_CURSOR_COLORS`, `render_cursor`)
- Modify: `PyAitD/app/shell.py:644-650` (`_play_cursor_kind`) and the cursor site at `:1680-1686`
- Test: `tests/test_ui_render.py`, `tests/test_play_loop.py`

**Interfaces:**
- Consumes: `project_room_point`, `viewed_floor_y` (Tasks 2-3); `InputBuffer.follow_settle_origin` (Task 4).
- Produces:
  - `render_cursor(painter, logical_pos, kind, *, held=False, settling=False, destination=None, preview=None)`. `destination` and `preview` are logical `(x, y)` or None.
  - `_play_cursor_state(game, floor, hover, draw_list, input_buffer) -> (kind, payload)` in `shell.py`; `_play_cursor_kind` stays as `_play_cursor_state(...)[0]`.
  - `_marker_for(game, floor, payload) -> (sx, sy) | None` in `shell.py`: projects a `(dest_x, dest_z, room, object_idx)` payload under the current camera.
  - `_intent_marker(game, floor) -> (sx, sy) | None`: the live intent's destination, or None.

- [ ] **Step 1: Write the failing render tests**

Append to `tests/test_ui_render.py`:

```python
def _drawn_outside(frame, centre, radius):
    """True when any pixel outside the square of `radius` around `centre` is lit."""
    x, y = centre
    masked = frame.copy()
    masked[max(0, y - radius):y + radius + 1, max(0, x - radius):x + radius + 1] = 0
    return int(masked.sum()) > 0


def test_cursor_defaults_draw_nothing_beyond_the_cursor():
    painter = UIPainter()
    render_cursor(painter, (160, 100), "walk")
    assert not _drawn_outside(painter.to_frame(), (160, 100), 10)


def test_destination_marker_is_drawn_at_the_destination():
    painter = UIPainter()
    render_cursor(painter, (160, 100), "walk", destination=(40, 150))
    frame = painter.to_frame()
    assert int(frame[145:156, 35:46].sum()) > 0, "no marker at the destination"


def test_no_destination_means_no_marker():
    with_marker = UIPainter()
    render_cursor(with_marker, (160, 100), "walk", destination=(40, 150))
    without = UIPainter()
    render_cursor(without, (160, 100), "walk", destination=None)
    assert int(with_marker.to_frame()[145:156, 35:46].sum()) > 0
    assert int(without.to_frame()[145:156, 35:46].sum()) == 0


def test_preview_is_fainter_than_the_marker():
    marker = UIPainter()
    render_cursor(marker, (160, 100), "walk", destination=(40, 150))
    preview = UIPainter()
    render_cursor(preview, (160, 100), "walk", preview=(40, 150))
    m = marker.to_frame()[145:156, 35:46, 3]
    p = preview.to_frame()[145:156, 35:46, 3]
    assert int(p.sum()) > 0, "the preview drew nothing"
    assert int(p.max()) < int(m.max()), "the preview is not fainter"


def test_press_ring_only_while_held():
    held = UIPainter()
    render_cursor(held, (160, 100), "walk", held=True)
    idle = UIPainter()
    render_cursor(idle, (160, 100), "walk", held=False)
    ring_band = lambda frame: int(frame[89:112, 149:172].sum()) - int(frame[95:106, 155:166].sum())
    assert ring_band(held.to_frame()) > 0
    assert ring_band(idle.to_frame()) == 0


def test_settling_ring_is_distinct_from_the_solid_ring():
    solid = UIPainter()
    render_cursor(solid, (160, 100), "walk", held=True)
    dashed = UIPainter()
    render_cursor(dashed, (160, 100), "walk", held=True, settling=True)
    assert solid.to_frame().tobytes() != dashed.to_frame().tobytes()
    # dashed draws strictly fewer ring pixels than solid
    band = lambda frame: int((frame[89:112, 149:172, 3] > 0).sum()) - int((frame[95:106, 155:166, 3] > 0).sum())
    assert 0 < band(dashed.to_frame()) < band(solid.to_frame())


def test_settling_without_held_draws_no_ring():
    painter = UIPainter()
    render_cursor(painter, (160, 100), "walk", held=False, settling=True)
    band = int(painter.to_frame()[89:112, 149:172].sum()) - int(painter.to_frame()[95:106, 155:166].sum())
    assert band == 0


def test_blocked_and_walk_colours_differ():
    from PyAitD.app.ui import _CURSOR_COLORS
    assert _CURSOR_COLORS["blocked"] != _CURSOR_COLORS["walk"]
    r, g, b = _CURSOR_COLORS["blocked"]
    assert r > g and r > b, "blocked should read as a warning, not as walkable"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_ui_render.py -q -k "marker or preview or ring or blocked_and_walk or defaults_draw"`
Expected: FAIL with `TypeError: render_cursor() got an unexpected keyword argument 'destination'`.

- [ ] **Step 3: Implement the cursor**

In `PyAitD/app/ui.py`, replace `_CURSOR_COLORS` and `render_cursor` with:

```python
_CURSOR_COLORS = {
    "walk": (200, 230, 170),
    "target": (255, 220, 130),
    "attack": (255, 96, 72),
    "push": (255, 178, 56),
    "inventory": (120, 210, 255),
    "blocked": (235, 80, 70),
}
_MARKER_COLOR = (240, 240, 210)
_RING_RADIUS = 9
_RING_DASHES = 8


def _diamond(painter, colour, centre, size, width):
    x, y = centre
    points = [(x, y - size), (x + size, y), (x, y + size), (x - size, y)]
    for k in range(4):
        painter.line(colour, points[k], points[(k + 1) % 4], width=width)


def _dashed_ring(painter, colour, centre, radius):
    import math
    x, y = centre
    for k in range(_RING_DASHES):
        angle = 2 * math.pi * k / _RING_DASHES
        painter.circle(colour, (x + radius * math.cos(angle), y + radius * math.sin(angle)), 1)


def render_cursor(
        painter, logical_pos, kind, *, held=False, settling=False,
        destination=None, preview=None,
):
    """Draw the pick cursor and its feedback. Pure presentation: never
    touches world state.

    `destination` is where the live intent is heading, projected to the
    logical frame; `preview` is where a press would head, drawn fainter.
    `held` draws the press ring; `settling` (a camera cut's dead zone) draws
    it dashed. Every keyword defaults to the plain cursor.
    """
    if preview is not None and destination is None:
        faint = (*_MARKER_COLOR, 110)
        _diamond(painter, faint, (int(preview[0]), int(preview[1])), 4, 1)
    if destination is not None:
        _diamond(painter, _MARKER_COLOR, (int(destination[0]), int(destination[1])), 4, 2)
    if logical_pos is None:
        return
    colour = _CURSOR_COLORS.get(kind, _CURSOR_COLORS["walk"])
    x, y = int(logical_pos[0]), int(logical_pos[1])
    if kind == "inventory":
        painter.rect(colour, pygame.Rect(x - 5, y - 4, 11, 9), width=2)
        painter.line(colour, (x - 2, y - 6), (x + 2, y - 6), width=2)
    elif kind == "attack":
        painter.circle(colour, (x, y), 6, width=1)
        painter.line(colour, (x - 8, y), (x + 8, y), width=1)
        painter.line(colour, (x, y - 8), (x, y + 8), width=1)
    elif kind == "target":
        painter.rect(colour, pygame.Rect(x - 5, y - 5, 11, 11), width=1)
    elif kind == "push":
        painter.line(colour, (x - 7, y), (x + 7, y), width=2)
        painter.line(colour, (x - 7, y), (x - 3, y - 3), width=2)
        painter.line(colour, (x - 7, y), (x - 3, y + 3), width=2)
        painter.line(colour, (x + 7, y), (x + 3, y - 3), width=2)
        painter.line(colour, (x + 7, y), (x + 3, y + 3), width=2)
    elif kind == "blocked":
        painter.line(colour, (x - 4, y - 4), (x + 4, y + 4), width=2)
        painter.line(colour, (x - 4, y + 4), (x + 4, y - 4), width=2)
    else:
        painter.circle(colour, (x, y), 4, width=1)
        painter.circle(colour, (x, y), 1)
    if held:
        if settling:
            _dashed_ring(painter, colour, (x, y), _RING_RADIUS)
        else:
            painter.circle(colour, (x, y), _RING_RADIUS, width=1)
```

`UIPainter.line` and `.circle` pass through to `pygame.draw` with the painter's scale; an RGBA colour tuple is accepted by both because the surface is `SRCALPHA`.

- [ ] **Step 4: Run the render tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_ui_render.py -q`
Expected: all PASS, including the pre-existing distinct-output tests (the shapes still differ pairwise).

- [ ] **Step 5: Write the failing shell tests**

Append to `tests/test_play_loop.py`:

```python
def test_intent_marker_projects_the_live_destination(data_dir, profile):
    import PyAitD.app.shell as main
    from PyAitD.engine.nav.picking import project_room_point
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    hero = game.actors[game.current_camera_target_actor]
    pixel = next(p for p in _sampled_pixels() if resolve_play_click(game, floor, p, [])[0] == "walk")
    buf = held_pointer(pixel)
    route_play_click(game, ModalSession(), floor, pixel, [], buf)
    intent = game.nav_intent
    expected = project_room_point(
        floor, hero.room, game.num_camera, intent.room,
        intent.dest_x, hero.world_y, intent.dest_z,
    )
    assert main._intent_marker(game, floor) == expected
    assert expected is not None


def test_intent_marker_is_none_without_an_intent_or_on_a_transition_frame(data_dir, profile):
    import PyAitD.app.shell as main
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    assert game.nav_intent is None
    assert main._intent_marker(game, floor) is None
    hero = game.actors[game.current_camera_target_actor]
    from PyAitD.engine.script.interaction import apply_click_intent
    apply_click_intent(game, hero.room_x + 500, hero.room_z, hero.room)
    game.num_camera = -1
    assert main._intent_marker(game, floor) is None


def test_play_cursor_state_returns_kind_and_payload(data_dir, profile):
    import PyAitD.app.shell as main
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    pixel = next(p for p in _sampled_pixels() if resolve_play_click(game, floor, p, [])[0] == "walk")
    buf = InputBuffer()
    kind, payload = main._play_cursor_state(game, floor, pixel, [], buf)
    assert kind == "walk" and payload is not None
    assert main._play_cursor_kind(game, floor, pixel, [], buf) == "walk"
    assert main._marker_for(game, floor, payload) is not None


def test_run_hands_the_cursor_its_marker_ring_and_settle_state(data_dir, profile, monkeypatch):
    # The loop's cursor site passes the live intent's marker, the hold and
    # the dead zone through to render_cursor. Checked by capturing the call.
    import PyAitD.app.shell as main
    calls = []

    def spy(painter, pos, kind, **kw):
        calls.append((pos, kind, kw))
    monkeypatch.setattr(main, "render_cursor", spy)
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    pixel = next(p for p in _sampled_pixels() if resolve_play_click(game, floor, p, [])[0] == "walk")
    buf = held_pointer(pixel)
    buf.follow_settle_origin = pixel
    route_play_click(game, ModalSession(), floor, pixel, [], buf)
    main._render_play_cursor(game, floor, pixel, [], buf, painter=None)
    (pos, kind, kw), = calls
    assert pos == pixel and kind == "walk"
    assert kw["held"] is True
    assert kw["settling"] is True
    assert kw["destination"] == main._intent_marker(game, floor)
    assert kw["preview"] is None, "no preview while a press is held"
```

- [ ] **Step 6: Run them to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_play_loop.py -q -k "intent_marker or cursor_state or hands_the_cursor"`
Expected: FAIL with `AttributeError: module 'PyAitD.app.shell' has no attribute '_intent_marker'`.

- [ ] **Step 7: Implement the shell side**

In `PyAitD/app/shell.py`, replace `_play_cursor_kind` with:

```python
def _play_cursor_state(game, floor, hover, draw_list, input_buffer):
    """(kind, payload) the cursor should show for `hover`: a latched push
    stays "push" whatever the pointer drifts over; otherwise the resolver."""
    intent = getattr(game, "nav_intent", None)
    if (input_buffer.pointer_held and intent is not None
            and intent.requires_hold):
        return "push", None
    return resolve_play_click(game, floor, hover, draw_list)


def _play_cursor_kind(game, floor, hover, draw_list, input_buffer):
    return _play_cursor_state(game, floor, hover, draw_list, input_buffer)[0]


def _marker_for(game, floor, payload):
    """Project a (dest_x, dest_z, room, object_idx) payload to the logical
    frame under the camera on screen, or None."""
    from PyAitD.engine.nav.picking import project_room_point, viewed_floor_y
    if payload is None or game.num_camera == -1:
        return None
    hero_idx = game.current_camera_target_actor
    if hero_idx == -1:
        return None
    hero = game.actors[hero_idx]
    dest_x, dest_z, room, _object_idx = payload
    y = viewed_floor_y(floor, hero.room, room, hero.world_y)
    return project_room_point(floor, hero.room, game.num_camera, room, dest_x, y, dest_z)


def _intent_marker(game, floor):
    """Where the live intent is heading, on screen, or None."""
    intent = getattr(game, "nav_intent", None)
    if intent is None:
        return None
    return _marker_for(game, floor, (intent.dest_x, intent.dest_z, intent.room, -1))


def _render_play_cursor(game, floor, hover, draw_list, input_buffer, painter):
    """The PLAY cursor with its feedback: the live destination, a preview of
    where a press would head while nothing is held, the press ring, and the
    dashed ring while a cut's dead zone is open."""
    kind, payload = _play_cursor_state(game, floor, hover, draw_list, input_buffer)
    destination = _intent_marker(game, floor)
    preview = None
    if (not input_buffer.pointer_held and destination is None
            and kind in ("walk", "target")):
        preview = _marker_for(game, floor, payload)
    render_cursor(
        painter, hover, kind,
        held=input_buffer.pointer_held,
        settling=input_buffer.follow_settle_origin is not None,
        destination=destination,
        preview=preview,
    )
```

If `render_cursor` is imported into `shell.py` inside a function today, hoist that import to module level (the spy test patches `main.render_cursor`). Then at the cursor site in `run` replace:

```python
        if software_cursor:
            kind = _play_cursor_kind(
                game, floor, hover, draw_list, input_buffer,
            )
            render_cursor(painter, hover, kind)
```

with:

```python
        if software_cursor:
            _render_play_cursor(game, floor, hover, draw_list, input_buffer, painter)
```

For the spy test, `painter=None` is passed and only reaches the spied `render_cursor`, so nothing draws.

- [ ] **Step 8: Run the shell group**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest -m shell -q`
Expected: all PASS. If a test monkeypatches `_play_cursor_kind`, it keeps working because the loop no longer calls it directly; if a test asserts that `render_cursor` was called positionally with three arguments, update it to the keyword form above.

- [ ] **Step 9: Commit**

```bash
git add PyAitD/app/ui.py PyAitD/app/shell.py tests/test_ui_render.py tests/test_play_loop.py
git commit -m "feat: destination marker, hover preview and press ring on the PLAY cursor"
```

---

### Task 6: Proof tool count, proof document and entry-point docs

**Files:**
- Modify: `tools/prove_mouse.py`
- Create: `docs/mouse-fidelity-proof.md`
- Modify: `CONTEXT.md` (milestone table, after the "Mouse accessibility hardening" row), `README.md:57-65`, `AGENTS.md` (only if it describes the cursor; grep first)
- Test: `tests/test_tools.py` if it exercises `prove_mouse` (grep `prove_mouse` under `tests/`; if it does, extend that test, otherwise add the test below to the file that covers `tools/`)

**Interfaces:**
- Consumes: `pick_floor_any_room(..., occlude=False)` (Task 2).
- Produces: `count_occluded(floor, hero_room, floor_y, agent, stride=5) -> dict[int, int]` in `tools/prove_mouse.py`: per camera slot, the number of sampled pixels the old pick accepted and the occluded pick refuses.

- [ ] **Step 1: Write the failing tool test**

Find the tools test file: `grep -ln "prove_mouse" tests/*.py`. Append there (or to `tests/test_tools.py` if none names it; keep its `pytestmark = pytest.mark.tools`):

```python
def test_prove_mouse_counts_occluded_pixels_per_camera(data_dir, profile):
    import importlib
    prove_mouse = importlib.import_module("tools.prove_mouse")
    from PyAitD.engine.data.floor import Floor
    from PyAitD.engine.script.game import init_game
    from PyAitD.engine.nav.navmesh import agent_extent
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, 0, profile)
    hero = game.actors[game.current_camera_target_actor]
    counts = prove_mouse.count_occluded(floor, hero.room, hero.world_y, agent_extent(hero))
    assert set(counts) == set(range(len(floor.rooms[hero.room].camera_indices)))
    assert all(count >= 0 for count in counts.values())
    assert sum(counts.values()) > 0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest -m tools -q -k occluded`
Expected: FAIL with `AttributeError: module 'tools.prove_mouse' has no attribute 'count_occluded'`.

- [ ] **Step 3: Implement the count and print it**

In `tools/prove_mouse.py` add the import `from PyAitD.engine.nav.picking import pick_floor_any_room` and:

```python
def count_occluded(floor, hero_room, floor_y, agent, stride=5):
    """Per camera slot of hero_room: how many sampled pixels the pre-occlusion
    pick accepted as floor and the occluded pick now refuses -- the wall and
    furniture pixels that used to fall through onto the floor behind them."""
    counts = {}
    pixels = [(x, y) for y in range(199, 40, -stride) for x in range(2, 320, stride)]
    for slot in range(len(floor.rooms[hero_room].camera_indices)):
        refused = 0
        for pixel in pixels:
            old = pick_floor_any_room(pixel, floor, hero_room, slot, floor_y, occlude=False)
            if old is None:
                continue
            new = pick_floor_any_room(pixel, floor, hero_room, slot, floor_y, agent=agent)
            if new is None:
                refused += 1
        counts[slot] = refused
    return counts
```

In `main`, after the per-room loop for floor 0 (inside `for number in range(8)`, guarded by `if number == 0:`), print:

```python
        if number == 0:
            hero = game.actors[game.current_camera_target_actor]
            for slot, refused in count_occluded(floor, hero.room, hero.world_y, agent).items():
                print(f"floor 0 camera slot {slot}: {refused} wall/furniture pixels no longer pick the floor behind them")
```

- [ ] **Step 4: Run the tools group and the proof**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest -m tools -q`
Expected: all PASS.
Run: `make proof-mouse`
Expected: the five attic camera lines print with non-negative counts, at least one positive. Copy the lines into the proof document in the next step.

- [ ] **Step 5: Write the proof document**

Create `docs/mouse-fidelity-proof.md`:

```markdown
# Mouse fidelity proof

Spec: `docs/superpowers/specs/2026-09-02-mouse-fidelity-design.md`
Plan: `docs/superpowers/plans/2026-09-02-mouse-fidelity.md`

## Automated gates

| Gate | Command | Result |
|---|---|---|
| Picking: ray-box, visibility, viewed-room depth, occlusion subset, snap budget | `make test-engine` | green (date, commit) |
| Follow: cut dead zone, release and floor change clear it, arrival while settling | `make test-shell` | green (date, commit) |
| Cursor: marker, preview, ring, dashed ring, defaults | `make test-shell` | green (date, commit) |
| Contract unchanged | `make test-shell` | green (date, commit) |
| Attic occlusion census | `make proof-mouse` | paste the five `floor 0 camera slot` lines |

## Windowed attestation

Run `make run --skip-intro` and play the attic. Fill in one row per hero.

| Hero | Wall pixel refuses (X cursor, hero stands) | Snap shows marker within the pointer's neighbourhood | Cut with still hand keeps heading | One-pixel jitter after cut does not redirect | Ring while held, dashed while settling | Attested by / date |
|---|---|---|---|---|---|---|
| Carnby | pending | pending | pending | pending | pending | |
| Emily | pending | pending | pending | pending | pending | |
```

Replace the `(date, commit)` placeholders with the real values from the runs in step 4 and a final `make test`.

- [ ] **Step 6: Update the entry-point docs**

`CONTEXT.md`: after the "Mouse accessibility hardening" row add:

```markdown
| Mouse fidelity | Occlusion-aware floor pick (no floor behind walls), viewed rooms picked at their own depth, an eight-pixel snap budget, visible approach cells, a six-pixel dead zone after a camera cut, and a destination marker, hover preview and press ring on the cursor | automated gates green; windowed attestation pending (`docs/mouse-fidelity-proof.md`) |
```

Also in CONTEXT.md's architecture table, extend the `engine/nav/` row: `picking.py screen->world, hard-col occlusion, snap budget, marker projection`.

`README.md` lines 57-65: after "release to stop immediately." add one sentence: "A diamond on the floor marks where the hero is heading (faint before you press, solid while you hold), a ring around the cursor shows the button is down, and a red X means the pointer is on a wall or something the hero cannot reach."

`AGENTS.md`: `grep -n cursor AGENTS.md`; if the cursor is described, add the same sentence, otherwise leave it.

- [ ] **Step 7: Run the whole suite**

Run: `make test`
Expected: green. Paste the summary line's date and `git rev-parse --short HEAD` into the proof document's gate rows.

- [ ] **Step 8: Commit**

```bash
git add tools/prove_mouse.py docs/mouse-fidelity-proof.md CONTEXT.md README.md AGENTS.md tests/
git commit -m "docs: mouse fidelity proof, occlusion census in proof-mouse, entry-point updates"
```

---

## Self-review

**Spec coverage.** Section 1 occlusion: Tasks 1-2. Section 1 depth: Task 2 (`viewed_floor_y`). Section 1 snap budget and visible approach cells: Task 3. Section 1 interface (`accept` on both searches, `pick_floor_any_room` shape): Tasks 2-3. Section 2 dead zone, arrival while settling, state fields, clearing on release and floor change: Task 4. Section 3 marker, preview, ring, dashed ring, colours, keyboard mode untouched: Task 5. Section 4 tests by layer, proof tool count, proof document, docs, `make test` and `make proof-mouse`: Tasks 1-6. The contract is unchanged by construction; Task 6's proof table records that the contract gate ran.

**Type consistency.** `ray_box_hit(origin, point, box)`, `to_room_frame(floor, from_room, to_room, x, y, z)`, `floor_point_visible(floor, global_cam_idx, room_idx, x, y, z, agent=None)`, `viewed_floor_y(floor, hero_room, room_idx, floor_y)`, `project_room_point(floor, hero_room, cam_slot, room_idx, x, y, z)`, `snap_accept(floor, hero_room, cam_slot, room_idx, floor_y, logical_pos, agent=None, budget=SNAP_BUDGET_PX)`, `visible_accept(floor, hero_room, cam_slot, room_idx, floor_y, agent=None)` are used with the same argument order in Tasks 1-6. `InputBuffer.follow_camera` / `follow_settle_origin` names match between Tasks 4 and 5. `render_cursor` keywords match between Task 5's `ui.py` and `shell.py`.

**Known judgement calls for the implementer.** (1) Task 3 step 11 hoists imports to module level for monkeypatching; if `tests/test_layering.py` objects, keep them local and patch the engine modules instead, as the step says. (2) Task 5's spy test calls `_render_play_cursor` with `painter=None`; that is only valid because `render_cursor` is spied, so keep the spy before the call.
