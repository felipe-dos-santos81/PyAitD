# Motion Interpolation (Roadmap 2, Sub-project I) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render-frame interpolation of actor pose, angles and position between 50 Hz simulation ticks, behind a `motion ∈ ("tick", "smooth")` knob, plus the Graphics → Realism system-menu page split that hosts its row.

**Architecture:** A pure `render/motion.py` module snapshots per-actor state before each tick and blends it toward the live state at render time (`alpha = accumulator / TICK_MS`), feeding a float twin of `skel.pose_vertices` into `pose_geometry` — the `CameraView` precedent: the integer path stays the sole authority for picking, masks, `draw_list` and the logical projection. The shell passes the blend into `build_frame`; snap rules (camera cut, floor change, spawn, anim change, teleport) render an actor unblended rather than smearing.

**Tech Stack:** Python 3.12, numpy (no new dependencies; the slerp is ~30 lines of in-repo numpy). pygame-ce/moderngl untouched by the math — the GL backend consumes the same `BodyGeometry` it always did.

**Spec:** `docs/superpowers/specs/2026-08-31-actor-realism-roadmap-2-design.md` (sub-project I, plus its "Options, UI and tooling" page-split section). Read the spec's I section before starting.

## Global Constraints

- Runtime dependencies stay exactly pygame-ce + moderngl + numpy; this plan adds none.
- `motion="tick"` runs today's code verbatim; the option lands as `"tick"` and flips to `"smooth"` only in Task 6.
- `skel.skin()`, `draw_list`, picking, masks, the mouse contract, and all simulation code are untouched. `logical = skin(...)` in `build_frame` always receives the integer, current-tick states.
- `tests/golden/scene_lit_classic.npy` must keep passing throughout (GL tests call `build_frame` without `blend`, so they are unaffected by construction — verify anyway).
- Interpolation, never extrapolation: blending runs from the pre-tick snapshot toward the live state; rendered pose may lag the simulation by up to one tick (20 ms).
- Every new test file carries exactly one subject marker (`pytestmark = pytest.mark.render` for `tests/test_motion.py`); edits to existing test files keep their existing marker.
- Run the full gate before calling any task done: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q` (the repo's authoritative gate is `make test`).
- Commit after every task with a `feat:`/`test:`/`docs:` message as shown.

---

### Task 1: `render/motion.py` — snapshot and blend math

**Files:**
- Create: `PyAitD/render/motion.py`
- Create: `tests/test_motion.py`

**Interfaces:**
- Consumes: `game.actors` (fields `index_in_world`, `body_num`, `anim`, `room`, `world_x/y/z`, `step_x/y/z`, `alpha`, `beta`, `gamma`), `game.anim_players` (dict actor_idx → `AnimPlayer`, whose `group_states()` returns `[(gtype, (dx, dy, dz)), ...]`), `game.current_floor`, `game.num_camera`.
- Produces (Tasks 5–6 rely on these exact names):
  - `ActorMotion` frozen dataclass: `body_num: int, room: int, anim: int, position: tuple, angles: tuple, states: tuple`
  - `MotionSnapshot` frozen dataclass: `floor: int, camera: int, actors: dict`
  - `TELEPORT_LIMIT = 500` (world units per tick)
  - `snapshot(game) -> MotionSnapshot`
  - `blend_angle(prev, cur, alpha) -> float`
  - `blend_states(prev_states, cur_states, alpha) -> tuple`
  - `blend_actor(prev, body_num, room, anim, states, angles, position, alpha) -> (states, angles, position, pose_fn)`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_motion.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""render/motion.py: inter-tick blending — pure math, no pygame, no GL."""
import pytest

pytestmark = pytest.mark.render


def test_blend_angle_endpoints_and_lerp():
    from PyAitD.render.motion import blend_angle
    assert blend_angle(100.0, 200.0, 0.0) == pytest.approx(100.0)
    assert blend_angle(100.0, 200.0, 1.0) == pytest.approx(200.0)
    assert blend_angle(100.0, 200.0, 0.5) == pytest.approx(150.0)


def test_blend_angle_wraps_through_the_short_arc():
    from PyAitD.render.motion import blend_angle
    # 1000 -> 20 is 44 units forward through 0, not 980 backward
    assert blend_angle(1000.0, 20.0, 0.5) == pytest.approx(1010.0)
    # 20 -> 1000 is 44 units backward through 0
    assert blend_angle(20.0, 1000.0, 0.5) == pytest.approx(10.0)
    # exactly opposite (512 apart) is a defined, finite answer
    assert 0.0 <= blend_angle(0.0, 512.0, 0.5) < 1024.0


def test_blend_states_by_group_type():
    from PyAitD.render.motion import blend_states
    prev = ((0, (0.0, 1000.0, 0.0)), (1, (10.0, 0.0, 0.0)))
    cur = ((0, (0.0, 20.0, 0.0)), (1, (30.0, 0.0, 0.0)))
    out = blend_states(prev, cur, 0.5)
    assert out[0][0] == 0 and out[0][1][1] == pytest.approx(1010.0)  # rotation: short arc
    assert out[1][0] == 1 and out[1][1][0] == pytest.approx(20.0)    # translate: plain lerp


def test_blend_states_gtype_mismatch_takes_cur_verbatim():
    from PyAitD.render.motion import blend_states
    prev = ((0, (0.0, 1000.0, 0.0)),)
    cur = ((1, (30.0, 0.0, 0.0)),)
    assert blend_states(prev, cur, 0.5) == ((1, (30.0, 0.0, 0.0)),)


def _actor_motion(**overrides):
    from PyAitD.render.motion import ActorMotion
    fields = dict(body_num=1, room=0, anim=2,
                  position=(0.0, 0.0, 0.0), angles=(0.0, 100.0, 0.0),
                  states=((0, (0.0, 0.0, 0.0)),))
    fields.update(overrides)
    return ActorMotion(**fields)


def test_blend_actor_blends_a_matching_actor():
    from PyAitD.render.motion import blend_actor, pose_vertices_float
    prev = _actor_motion()
    states, angles, position, pose_fn = blend_actor(
        prev, 1, 0, 2, ((0, (0, 64, 0)),), (0, 200, 0), (100.0, 0.0, 0.0), 0.5)
    assert angles[1] == pytest.approx(150.0)
    assert position[0] == pytest.approx(50.0)
    assert states[0][1][1] == pytest.approx(32.0)
    assert pose_fn is pose_vertices_float


def test_blend_actor_snaps_on_identity_change_or_teleport():
    from PyAitD.render.motion import TELEPORT_LIMIT, blend_actor
    cur = (((0, (0, 64, 0)),), (0, 200, 0), (100.0, 0.0, 0.0))
    for prev in (
        None,
        _actor_motion(body_num=9),
        _actor_motion(room=5),
        _actor_motion(anim=7),
        _actor_motion(position=(100.0 + TELEPORT_LIMIT + 1, 0.0, 0.0)),
    ):
        states, angles, position, pose_fn = blend_actor(prev, 1, 0, 2, *cur, 0.5)
        assert (states, angles, position) == cur
        assert pose_fn is None


def test_blend_actor_state_length_mismatch_blends_pose_but_not_states():
    from PyAitD.render.motion import blend_actor
    prev = _actor_motion(states=())   # snapshot saw no AnimPlayer (static body)
    states, angles, position, pose_fn = blend_actor(
        prev, 1, 0, 2, ((0, (0, 64, 0)),), (0, 200, 0), (100.0, 0.0, 0.0), 0.5)
    assert states == ((0, (0, 64, 0)),)        # cur states verbatim
    assert angles[1] == pytest.approx(150.0)   # angles still blend
    assert pose_fn is not None


def test_snapshot_reads_live_actors_and_players():
    from PyAitD.render.motion import snapshot

    class _Actor:
        def __init__(self, index_in_world, body_num, anim, room=0):
            self.index_in_world = index_in_world
            self.body_num = body_num
            self.anim = anim
            self.room = room
            self.world_x, self.world_y, self.world_z = 10, 20, 30
            self.step_x, self.step_y, self.step_z = 1, 2, 3
            self.alpha, self.beta, self.gamma = 0, 256, 0

    class _Player:
        def group_states(self):
            return [(0, (1, 2, 3))]

    class _Game:
        current_floor = 4
        num_camera = 2
        actors = [_Actor(0, 12, 5), _Actor(-1, 12, 5), _Actor(3, -1, 5), _Actor(7, 4, -1)]
        anim_players = {0: _Player()}

    snap = snapshot(_Game())
    assert snap.floor == 4 and snap.camera == 2
    assert set(snap.actors) == {0, 3}          # dead slot and body -1 skipped
    entry = snap.actors[0]
    assert entry.position == (11.0, 22.0, 33.0)
    assert entry.angles == (0.0, 256.0, 0.0)
    assert entry.states == ((0, (1.0, 2.0, 3.0)),)
    assert snap.actors[3].states == ()          # anim -1: no player consulted
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_motion.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'PyAitD.render.motion'`

- [ ] **Step 3: Write the implementation**

Create `PyAitD/render/motion.py`. `pose_vertices_float` is Task 2; give it a stub here so `blend_actor` can reference it, and mark the stub clearly:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Inter-tick motion blending for the enhanced renderer.

Presentation-only, on the CameraView precedent: a float twin beside the
authoritative integer path. The shell snapshots per-actor state before
each 50 Hz tick; build_frame blends snapshot -> live state at
alpha = accumulator / TICK_MS. Interpolation, never extrapolation: the
rendered pose lags the simulation by up to one tick. skel.skin, the
draw_list, picking and masks always read the integer, current-tick
state. Pure and pygame/GL free."""
from dataclasses import dataclass

import numpy as np

# The largest per-tick movement still treated as motion. The fastest
# legitimate travel (run, speed 5) moves well under 100 world units per
# 20 ms tick; anything past this is a script teleport and snaps.
TELEPORT_LIMIT = 500


@dataclass(frozen=True)
class ActorMotion:
    body_num: int
    room: int
    anim: int
    position: tuple   # (x, y, z) floats, world + step
    angles: tuple     # (alpha, beta, gamma) floats, 0..1024 units
    states: tuple     # ((gtype, (dx, dy, dz)), ...) floats; () when no player


@dataclass(frozen=True)
class MotionSnapshot:
    floor: int
    camera: int
    actors: dict      # actor index -> ActorMotion


def snapshot(game):
    """Per-actor motion state as of the last committed tick.

    Reads game.anim_players directly instead of anim_player_for so a
    snapshot never creates a player; an actor without one (static body,
    or first frame of a new anim) carries empty states and blend_actor
    falls back to the live states for the pose while still blending
    angles and position."""
    actors = {}
    for index, actor in enumerate(game.actors):
        if actor.index_in_world < 0 or actor.body_num == -1:
            continue
        player = game.anim_players.get(index) if actor.anim != -1 else None
        states = ()
        if player is not None:
            states = tuple(
                (gtype, (float(d[0]), float(d[1]), float(d[2])))
                for gtype, d in player.group_states()
            )
        actors[index] = ActorMotion(
            body_num=actor.body_num,
            room=actor.room,
            anim=actor.anim,
            position=(
                float(actor.world_x + actor.step_x),
                float(actor.world_y + actor.step_y),
                float(actor.world_z + actor.step_z),
            ),
            angles=(float(actor.alpha), float(actor.beta), float(actor.gamma)),
            states=states,
        )
    return MotionSnapshot(
        floor=game.current_floor, camera=game.num_camera, actors=actors,
    )


def blend_angle(prev, cur, alpha):
    """Shortest-arc interpolation on the 0..1024 rotation circle — the
    continuous float twin of patch_inter_angle's ±0x200 wrap rule."""
    delta = ((cur - prev + 512.0) % 1024.0) - 512.0
    return (prev + delta * alpha) % 1024.0


def blend_states(prev_states, cur_states, alpha):
    """Blend group states index-by-index; a gtype mismatch takes the
    current entry verbatim (a group that changed kind mid-anim has no
    meaningful in-between)."""
    out = []
    for (pg, pd), (cg, cd) in zip(prev_states, cur_states):
        if pg != cg:
            out.append((cg, cd))
        elif cg == 0:
            out.append((cg, tuple(blend_angle(p, c, alpha) for p, c in zip(pd, cd))))
        else:
            out.append((cg, tuple(p + (c - p) * alpha for p, c in zip(pd, cd))))
    return tuple(out)


def blend_actor(prev, body_num, room, anim, states, angles, position, alpha):
    """(states, angles, position, pose_fn) for one actor's geometry.

    Blended through the float pose twin when `prev` is blendable;
    verbatim with pose_fn None otherwise. The snap rules: no snapshot
    entry, a different body, room or anim, or a teleport past
    TELEPORT_LIMIT."""
    if (prev is None or prev.body_num != body_num or prev.room != room
            or prev.anim != anim
            or max(abs(p - c) for p, c in zip(prev.position, position)) > TELEPORT_LIMIT):
        return states, angles, position, None
    if len(prev.states) == len(states):
        out_states = blend_states(prev.states, states, alpha)
    else:
        out_states = states
    out_angles = tuple(blend_angle(p, c, alpha) for p, c in zip(prev.angles, angles))
    out_position = tuple(p + (c - p) * alpha for p, c in zip(prev.position, position))
    return out_states, out_angles, out_position, pose_vertices_float


def pose_vertices_float(body, group_states, actor_angles=None):
    # Task 2 replaces this stub with the real float twin of
    # skel.pose_vertices. blend_actor only hands it out; nothing calls
    # it until build_frame's blend wiring lands in Task 5.
    raise NotImplementedError("pose_vertices_float lands in Task 2")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_motion.py -q`
Expected: PASS (all 8)

- [ ] **Step 5: Full gate, then commit**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
git add PyAitD/render/motion.py tests/test_motion.py
git commit -m "feat: motion snapshot and inter-tick blend math (roadmap 2 I)"
```

---

### Task 2: `pose_vertices_float` and the `pose_geometry` seam

**Files:**
- Modify: `PyAitD/render/motion.py` (replace the Task 1 stub)
- Modify: `PyAitD/render/geometry.py:140-160` (`pose_geometry` gains `pose_fn`)
- Test: `tests/test_motion.py`, `tests/test_geometry.py`

**Interfaces:**
- Consumes: `body.vertices`, `body.groups` (each with `start`, `num_vertices`, `num_group`, `org_group`, `base_vertices`), `body.group_order` — the exact structures `PyAitD/engine/actor/skel.py:pose_vertices` reads.
- Produces: `pose_vertices_float(body, group_states, actor_angles=None) -> np.ndarray (N, 3) float64`; `pose_geometry(body, group_states, actor_angles=None, ao=None, refinement=None, pose_fn=None)` where `pose_fn=None` means `skel.pose_vertices` (today's behaviour, byte-identical).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_motion.py`:

```python
def _stub_body():
    """Two vertices, one root group — the shape stub bodies use across
    the suite (see tests/test_skel.py for the field meanings)."""
    from types import SimpleNamespace
    group = SimpleNamespace(start=0, num_vertices=2, num_group=0, org_group=-1,
                            base_vertices=0)
    return SimpleNamespace(vertices=[[0, 0, 0], [100, 0, 0]], groups=[group],
                           group_order=[0], flags=2, primitives=[])


def test_pose_vertices_float_matches_integer_pose_on_translation():
    from PyAitD.engine.actor.skel import pose_vertices
    from PyAitD.render.motion import pose_vertices_float
    body = _stub_body()
    states = [(1, (10, 20, 30))]
    integer = pose_vertices(body, states)
    floats = pose_vertices_float(body, states)
    for i in range(2):
        assert tuple(floats[i]) == pytest.approx(tuple(integer[i]))


def test_pose_vertices_float_rotation_is_exact_where_the_table_truncates():
    import math
    from PyAitD.render.motion import pose_vertices_float
    body = _stub_body()
    # 256 units = 90 degrees about y: (100, 0, 0) -> (0, 0, 100)
    floats = pose_vertices_float(body, [(0, (0, 256, 0))])
    assert tuple(floats[1]) == pytest.approx((0.0, 0.0, 100.0), abs=1e-9)
    # fractional angle (impossible on the integer path): 45 degrees
    floats = pose_vertices_float(body, [(0, (0.0, 128.0, 0.0))])
    assert floats[1][0] == pytest.approx(100 * math.cos(math.pi / 4))
    assert floats[1][2] == pytest.approx(100 * math.sin(math.pi / 4))


def test_pose_vertices_float_actor_angles_group0_and_whole_model():
    from PyAitD.engine.actor.skel import pose_vertices
    from PyAitD.render.motion import pose_vertices_float
    body = _stub_body()
    # group_order non-empty: actor angles override group 0's delta
    a = pose_vertices_float(body, [(1, (5, 5, 5))], actor_angles=(0, 256, 0))
    assert tuple(a[1]) == pytest.approx((0.0, 0.0, 100.0), abs=1e-9)
    # group_order empty: RotateNuage whole-model path
    body.group_order = []
    b = pose_vertices_float(body, [(0, (0, 0, 0))], actor_angles=(0, 256, 0))
    i = pose_vertices(body, [(0, (0, 0, 0))], actor_angles=(0, 256, 0))
    for k in range(2):
        assert tuple(b[k]) == pytest.approx(tuple(i[k]), abs=8.0)


@pytest.mark.parametrize("body_num", [1, 12])
def test_pose_vertices_float_parity_on_real_bodies(data_dir, body_num):
    """Divergence from the integer pose is truncation-bounded, the way
    CameraView's divergence from skel.skin is (~6 world units measured)."""
    import numpy as np
    from PyAitD.engine.data.assets import GameAssets
    from PyAitD.engine.actor.skel import pose_vertices
    from PyAitD.render.motion import pose_vertices_float
    from PyAitD.games.aitd1.profile import AITD1
    assets = GameAssets(data_dir, AITD1)
    body = assets.body(body_num)
    states = [(0, (0, 0, 0))] * len(body.groups)
    integer = np.array(pose_vertices(body, states, actor_angles=(0, 300, 0)), dtype=np.float64)
    floats = pose_vertices_float(body, states, actor_angles=(0, 300, 0))
    assert float(np.max(np.abs(floats - integer))) <= 16.0
```

Append to `tests/test_geometry.py` (its `pytestmark` is `render`; keep it):

```python
def test_pose_geometry_pose_fn_seam_defaults_to_the_integer_pose():
    import numpy as np
    from PyAitD.render.geometry import pose_geometry
    from tests.test_motion import _stub_body
    body = _stub_body()
    default = pose_geometry(body, [(1, (10, 0, 0))])
    swapped = pose_geometry(
        body, [(1, (10, 0, 0))],
        pose_fn=lambda b, s, a=None: np.zeros((2, 3), dtype=np.float64),
    )
    assert default.vertices[1][0] == 110.0
    assert np.all(swapped.vertices == 0.0)
```

(If `tests/test_geometry.py` imports at module level rather than in-function, follow the file's local style; the assertion content is what matters.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_motion.py tests/test_geometry.py -q`
Expected: FAIL — `NotImplementedError` from the stub and `TypeError: pose_geometry() got an unexpected keyword argument 'pose_fn'`

- [ ] **Step 3: Implement the float twin**

Replace the stub in `PyAitD/render/motion.py` with (delete the stub entirely):

```python
def _rotate_span_float(pts, start, count, dx, dy, dz):
    # Float twin of skel._rotate_list: same axis order (y, then x, then
    # z), same pair assignments, exact trigonometry instead of
    # COS_TABLE's >>16 <<1 truncation. COS_TABLE[a] ~= sin(a*pi/512) and
    # the table's paired lookup at a+0x100 is cos(a*pi/512), so the
    # integer formula ((x*s - z*c) >> 16) << 1 is x*cos - z*sin.
    span = pts[start:start + count]
    for rot, (i, j) in (((dy % 1024.0), (0, 2)),
                        ((dx % 1024.0), (1, 2)),
                        ((dz % 1024.0), (0, 1))):
        if rot:
            theta = rot * (np.pi / 512.0)
            c, s = np.cos(theta), np.sin(theta)
            a, b = span[:, i].copy(), span[:, j].copy()
            span[:, i] = a * c - b * s
            span[:, j] = a * s + b * c


def _rotate_group_float(pts, group, groups, dx, dy, dz):
    # InitGroupeRot + RotateGroupe recursion, exactly as skel._rotate_group
    _rotate_span_float(pts, group.start, group.num_vertices, dx, dy, dz)
    for other in groups:
        if other.org_group == group.num_group and other is not group:
            _rotate_group_float(pts, other, groups, dx, dy, dz)


def pose_vertices_float(body, group_states, actor_angles=None):
    """Float64 twin of skel.pose_vertices: same group hierarchy, same
    axis order, real trigonometry and fractional angles. Diverges from
    the integer pose only by its truncation (bounded; pinned by
    tests/test_motion.py), the way CameraView diverges from skel.skin.
    Rendering only — never picking, masks or combat."""
    pts = np.array(body.vertices, dtype=np.float64).reshape(-1, 3)
    num_points = len(pts)

    if actor_angles is not None:
        if body.group_order:
            group_states = list(group_states)
            group_states[0] = (0, actor_angles)
        else:
            _rotate_span_float(pts, 0, num_points, *actor_angles)

    for order_idx in body.group_order:
        group = body.groups[order_idx]
        gtype, (dx, dy, dz) = group_states[order_idx]
        if dx or dy or dz:
            if gtype == 0:
                _rotate_group_float(pts, group, body.groups, dx, dy, dz)
            elif gtype == 1:
                pts[group.start:group.start + group.num_vertices] += (dx, dy, dz)
            elif gtype == 2:
                pts[group.start:group.start + group.num_vertices] *= (
                    (dx + 256.0) / 256.0, (dy + 256.0) / 256.0, (dz + 256.0) / 256.0)

    offsets = np.zeros_like(pts)
    for group in body.groups:
        offsets[group.start:group.start + group.num_vertices] = pts[group.base_vertices]
    return pts + offsets
```

Note the base-vertex step: `skel.pose_vertices` adds each group's `base_vertices` point *as mutated so far, in a single pass where earlier groups' additions are visible to later reads of `pts`*. Look at `PyAitD/engine/actor/skel.py:57-63`: the integer loop reads `pts[group.base_vertices]` while mutating `pts` in the same loop, so a group whose base vertex belongs to an earlier-offset group compounds. The `offsets` array above reads all bases *before* any addition, which is NOT the same for chained groups. Match the integer semantics exactly instead:

```python
    for group in body.groups:
        base = pts[group.base_vertices].copy()
        pts[group.start:group.start + group.num_vertices] += base
    return pts
```

(`.copy()` because the base vertex may lie inside the span being incremented — the integer path reads the list element once per component before writing, and a group's base vertex can be inside its own span, where numpy's in-place add would otherwise alias.) Use this second form; delete the `offsets` draft.

In `PyAitD/render/geometry.py`, change the `pose_geometry` signature and first line:

```python
def pose_geometry(body, group_states, actor_angles=None, ao=None, refinement=None, pose_fn=None):
    pose = pose_vertices if pose_fn is None else pose_fn
    vertices = np.array(pose(body, group_states, actor_angles), dtype=np.float32).reshape(-1, 3)
```

(the rest of the function is unchanged).

- [ ] **Step 4: Run tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_motion.py tests/test_geometry.py -q`
Expected: PASS (real-body parity tests skip without game data; run with data present if available)

- [ ] **Step 5: Full gate, then commit**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
git add PyAitD/render/motion.py PyAitD/render/geometry.py tests/test_motion.py tests/test_geometry.py
git commit -m "feat: float pose twin and the pose_geometry pose_fn seam"
```

---

### Task 3: the `motion` option — validation, settings, CLI

**Files:**
- Modify: `PyAitD/render/render_options.py`
- Modify: `PyAitD/app/shell.py:119-131` (CLI flag), `:149-178` (`apply_render_overrides`), `:656` (`_MENU_RENDER_FIELDS`)
- Test: `tests/test_render_options.py`, `tests/test_main.py`

**Interfaces:**
- Produces: `MOTION_MODES = ("tick", "smooth")`, `RenderOptions.motion: str = "tick"` (last field, after `integration`), `cycle_motion(options)`, `--motion {tick,smooth}` CLI flag, `"motion"` in `_MENU_RENDER_FIELDS`. Task 4's UI imports `cycle_motion`; Task 5 reads `session.settings.render.motion`.
- Settings files need no schema change: `validate_render_options` degrades a missing/invalid `motion` per-field to the default with an error string, which `load_settings` surfaces as the usual notice (the same path `shadows` and `integration` used when they landed).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_render_options.py`:

```python
def test_motion_defaults_to_tick_and_cycles():
    from PyAitD.render.render_options import MOTION_MODES, RenderOptions, cycle_motion
    assert MOTION_MODES == ("tick", "smooth")
    options = RenderOptions()
    assert options.motion == "tick"
    assert cycle_motion(options).motion == "smooth"
    assert cycle_motion(cycle_motion(options)).motion == "tick"
    assert RenderOptions(motion="smooth").to_payload()["motion"] == "smooth"


def test_invalid_or_missing_motion_falls_back_alone():
    from PyAitD.render.render_options import RenderOptions, validate_render_options
    payload = RenderOptions(scale=2).to_payload()
    payload["motion"] = "cinematic"
    options, error = validate_render_options(payload)
    assert options.motion == "tick" and options.scale == 2
    assert "motion" in error
    del payload["motion"]   # a settings file from before this option
    options, error = validate_render_options(payload)
    assert options.motion == "tick" and "motion" in error
```

Append to `tests/test_main.py`, beside the existing `apply_render_overrides` tests (`tests/test_main.py:316-345`):

```python
def test_motion_cli_override_is_session_only_and_alone():
    from dataclasses import replace
    from PyAitD.app.config import default_settings
    from PyAitD.app.shell import apply_render_overrides, parse_args
    base = default_settings()
    only = apply_render_overrides(base, parse_args(["--motion", "smooth"]))
    # exactly the motion field moved, nothing else
    assert only.render == replace(base.render, motion="smooth")
    assert apply_render_overrides(base, parse_args([])).render.motion == "tick"


def test_menu_render_fields_cover_motion():
    from PyAitD.app.shell import _MENU_RENDER_FIELDS
    assert "motion" in _MENU_RENDER_FIELDS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_render_options.py tests/test_main.py -q`
Expected: FAIL with `ImportError: cannot import name 'MOTION_MODES'` and `argparse` error for `--motion`

- [ ] **Step 3: Implement**

`PyAitD/render/render_options.py` — add after the `LEGACY_INTEGRATION` block:

```python
# tick: one pose per 50 Hz simulation tick, rendered as-is — today's
# behaviour, byte for byte. smooth: build_frame blends the previous
# tick's snapshot toward the live state at the accumulator's leftover
# fraction, through the float pose twin (render/motion.py). Rendering
# only: picking, masks and the logical projection always read the tick
# pose.
MOTION_MODES = ("tick", "smooth")
```

Add the field (after `integration`), the payload entry, validation, and the cycle:

```python
    integration: int = 2
    motion: str = "tick"
```

```python
            "integration": self.integration,
            "motion": self.motion,
```

In `validate_render_options`, after the `integration` block and before the `options = RenderOptions(...)` line:

```python
    motion = payload.get("motion")
    if motion not in MOTION_MODES:
        errors.append(f"motion must be one of {', '.join(MOTION_MODES)}")
        motion = defaults.motion
    options = RenderOptions(scale, shading, background_filter, texture_dir, lighting, msaa, realism, smoothing, shadows, integration, motion)
```

(replace the existing `options = RenderOptions(...)` call). At the bottom:

```python
def cycle_motion(options):
    return replace(options, motion=_cycle(MOTION_MODES, options.motion))
```

`PyAitD/app/shell.py` — import `MOTION_MODES` where the other mode tuples are imported from `render_options`; add after the `--integration` argument:

```python
    p.add_argument(
        "--motion", choices=MOTION_MODES, default=None,
        help="tick: one pose per 50 Hz tick; smooth: blend between ticks "
             "at the display rate (rendering only, up to one tick behind)",
    )
```

In `apply_render_overrides`, after the `integration` branch:

```python
    if args.motion is not None:
        payload["motion"] = args.motion
```

Change `_MENU_RENDER_FIELDS` to:

```python
_MENU_RENDER_FIELDS = ("scale", "shading", "background_filter", "lighting", "msaa", "realism", "smoothing", "shadows", "integration", "motion")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_render_options.py tests/test_main.py tests/test_config.py -q`
Expected: PASS (test_config exercises the settings round-trip through `to_payload`, which now carries `motion`)

- [ ] **Step 5: Full gate, then commit**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
git add PyAitD/render/render_options.py PyAitD/app/shell.py tests/test_render_options.py tests/test_main.py
git commit -m "feat: the motion render option (tick/smooth), CLI flag and menu field"
```

---

### Task 4: the Graphics → Realism page split

**Files:**
- Modify: `PyAitD/app/ui.py` (`GRAPHICS_ROWS`/`REALISM_ROWS`, `config_row_count`, `SystemMenuPage`, `GRAPHICS_CYCLES`/`REALISM_CYCLES`, `_leave_graphics`/`_leave_realism`, `reduce_system_menu`, `SystemMenuLayout`, `graphics_labels`/`realism_labels`, `system_menu_labels`, `render_system_menu`)
- Test: `tests/test_ui_reducers.py`, `tests/test_ui_render.py`

**Interfaces:**
- Consumes: `cycle_motion` from Task 3.
- Produces: `SystemMenuPage.REALISM`; `GRAPHICS_ROWS = 5`, `REALISM_ROWS = 5`, `realism_row_count()`, `REALISM_CYCLES`, `realism_labels(render)`, `SystemMenuLayout.REALISM_PAGE_ROWS`; `config_row_count() == 4 + len(REMAPPABLE_CONTROLS)` (= 11). Configuration row order becomes: Sticky Action, the 7 controls, `Graphics...`, `Realism...`, `Back to Menu`. Sub-projects K and L later append their rows to `REALISM_CYCLES`/`realism_labels`.

- [ ] **Step 1: Update the pinned tests to the split (failing first)**

In `tests/test_ui_reducers.py`:
- `:173-176` — change the pin to:

```python
    from PyAitD.app.ui import (
        GRAPHICS_CYCLES, GRAPHICS_ROWS, REALISM_CYCLES, REALISM_ROWS,
        graphics_row_count, realism_row_count,
    )
    assert GRAPHICS_ROWS == 5 and len(GRAPHICS_CYCLES) == GRAPHICS_ROWS
    assert REALISM_ROWS == 5 and len(REALISM_CYCLES) == REALISM_ROWS
    assert graphics_row_count() == GRAPHICS_ROWS + 1
    assert realism_row_count() == REALISM_ROWS + 1
```

- `:198-200` — the cycle-position pin becomes:

```python
    from PyAitD.app.ui import GRAPHICS_CYCLES, REALISM_CYCLES
    from PyAitD.render.render_options import cycle_motion, cycle_smoothing
    assert GRAPHICS_CYCLES[4] is cycle_smoothing
    assert REALISM_CYCLES[3] is cycle_integration
    assert REALISM_CYCLES[4] is cycle_motion
```

(keep the file's existing import of `cycle_integration`). Add new reducer tests to the same file:

```python
def test_config_navigates_to_both_pages_and_back():
    from PyAitD.app.config import default_settings
    from PyAitD.app.ui import (
        Command, SystemMenuPage, SystemMenuPresenter, config_row_count,
        reduce_system_menu,
    )
    settings = default_settings()
    state = SystemMenuPresenter(page=SystemMenuPage.CONFIG,
                                cursor=config_row_count() - 3)
    assert reduce_system_menu(state, Command.ACCEPT, settings) is None
    assert state.page is SystemMenuPage.GRAPHICS and state.cursor == 0
    result = reduce_system_menu(state, Command.CANCEL, settings)
    assert result.save and state.page is SystemMenuPage.CONFIG
    assert state.cursor == config_row_count() - 3   # back on Graphics...
    state.cursor = config_row_count() - 2
    assert reduce_system_menu(state, Command.ACCEPT, settings) is None
    assert state.page is SystemMenuPage.REALISM and state.cursor == 0
    result = reduce_system_menu(state, Command.CANCEL, settings)
    assert result.save and state.page is SystemMenuPage.CONFIG
    assert state.cursor == config_row_count() - 2   # back on Realism...


def test_realism_page_cycles_motion_and_backs_out():
    from PyAitD.app.config import default_settings
    from PyAitD.app.ui import (
        Command, SystemMenuPage, SystemMenuPresenter, realism_row_count,
        reduce_system_menu,
    )
    settings = default_settings()
    state = SystemMenuPresenter(page=SystemMenuPage.REALISM, cursor=4)
    result = reduce_system_menu(state, Command.ACCEPT, settings)
    assert result.settings.render.motion == "smooth"
    state.cursor = realism_row_count() - 1
    result = reduce_system_menu(state, Command.ACCEPT, settings)
    assert result.save and state.page is SystemMenuPage.CONFIG
```

In `tests/test_ui_render.py`:
- `:825-827` — assert both layouts:

```python
    from PyAitD.app.ui import SystemMenuLayout, graphics_row_count, realism_row_count
    assert len(SystemMenuLayout.rows(SystemMenuPage.GRAPHICS)) == graphics_row_count()
    assert len(SystemMenuLayout.rows(SystemMenuPage.REALISM)) == realism_row_count()
```

(import `SystemMenuPage` per the file's local style). Every row of both pages must end above y=200; add beside it:

```python
    for page in (SystemMenuPage.GRAPHICS, SystemMenuPage.REALISM):
        for rect in SystemMenuLayout.rows(page):
            assert rect.bottom <= 200 and rect.height >= 13
```

- `:835-856` — the labels/cycles pin becomes two: `graphics_labels` has `GRAPHICS_ROWS` entries in `GRAPHICS_CYCLES` order (Scale, Shading, Filter, AA, Smoothing), `realism_labels` has `REALISM_ROWS` entries (Lighting, Shadows, Realism, Integration, Motion); the integration-label parametrisation at `:854-856` switches from `graphics_labels(...)[8]` to `realism_labels(...)[3]`; add:

```python
def test_motion_label_titles_the_mode():
    from dataclasses import replace
    from PyAitD.app.config import default_settings
    from PyAitD.app.ui import realism_labels
    render = default_settings().render
    assert realism_labels(render)[4] == "Motion: Tick"
    assert realism_labels(replace(render, motion="smooth"))[4] == "Motion: Smooth"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_reducers.py tests/test_ui_render.py -q`
Expected: FAIL — `ImportError: cannot import name 'REALISM_CYCLES'` and pin mismatches

- [ ] **Step 3: Implement the split in `PyAitD/app/ui.py`**

1. Import `cycle_motion` in the `render_options` import block.
2. Constants and counters (replacing `PyAitD/app/ui.py:27-36`):

```python
GRAPHICS_ROWS = 5          # rows on the Graphics page above Back, in GRAPHICS_CYCLES order
REALISM_ROWS = 5           # rows on the Realism page above Back, in REALISM_CYCLES order


def config_row_count():
    # Sticky Action, one row per remappable control, "Graphics...",
    # "Realism...", "Back to Menu"
    return 4 + len(REMAPPABLE_CONTROLS)


def graphics_row_count():
    return GRAPHICS_ROWS + 1   # plus Back


def realism_row_count():
    return REALISM_ROWS + 1    # plus Back
```

3. `SystemMenuPage` gains `REALISM = auto()` after `GRAPHICS`.
4. The cycles (replacing `:410-413`) — display knobs stay on Graphics, lighting/realism knobs move:

```python
GRAPHICS_CYCLES = (cycle_scale, cycle_shading, cycle_filter, cycle_msaa, cycle_smoothing)
REALISM_CYCLES = (cycle_lighting, cycle_shadows, cycle_realism, cycle_integration, cycle_motion)
```

5. Leave-helpers (replacing `_leave_graphics`):

```python
def _leave_graphics(state):
    state.page = SystemMenuPage.CONFIG
    state.cursor = config_row_count() - 3   # back on the Graphics... row
    state.hover = None


def _leave_realism(state):
    state.page = SystemMenuPage.CONFIG
    state.cursor = config_row_count() - 2   # back on the Realism... row
    state.hover = None
```

6. `reduce_system_menu` changes, each mirroring the existing GRAPHICS handling:
   - row_count: add `elif state.page is SystemMenuPage.REALISM: row_count = realism_row_count()` beside the GRAPHICS branch.
   - CANCEL: add before the CONFIG branch:

```python
        if state.page is SystemMenuPage.REALISM:
            _leave_realism(state)
            return SystemMenuResult(save=True)
```

   - ACCEPT on the page: add after the GRAPHICS ACCEPT branch:

```python
    elif command is Command.ACCEPT and state.page is SystemMenuPage.REALISM:
        if state.cursor == row_count - 1:
            _leave_realism(state)
            return SystemMenuResult(save=True)
        cycle = REALISM_CYCLES[state.cursor]
        return SystemMenuResult(settings=replace(settings, render=cycle(settings.render)))
```

   - CONFIG navigation rows (replacing the branch at `:500-504`):

```python
    elif command is Command.ACCEPT and state.cursor == row_count - 3:
        # the Graphics... row
        state.page = SystemMenuPage.GRAPHICS
        state.cursor = 0
        state.hover = None
    elif command is Command.ACCEPT and state.cursor == row_count - 2:
        # the Realism... row
        state.page = SystemMenuPage.REALISM
        state.cursor = 0
        state.hover = None
```

7. `SystemMenuLayout` (replacing `GRAPHICS_PAGE_ROWS` and its comment at `:663-672`):

```python
    # Both option pages at a 22 px pitch from y=12, rows 20 px tall — the
    # split gave each page its room back. Graphics (6 rows) ends at y=142;
    # Realism holds 6 now and 8 when roadmap-2 K and L add their rows
    # (y=186), all inside the 200-row screen, and 20 >= 13 keeps
    # effective_rects' 12x12 target contract.
    GRAPHICS_PAGE_ROWS = tuple(
        pygame.Rect(16, 12 + i * 22, 288, 20)
        for i in range(graphics_row_count())
    )
    REALISM_PAGE_ROWS = tuple(
        pygame.Rect(16, 12 + i * 22, 288, 20)
        for i in range(realism_row_count())
    )
```

   and in `rows()` add `if page is SystemMenuPage.REALISM: return cls.REALISM_PAGE_ROWS` beside the GRAPHICS branch.
8. Labels (replacing `graphics_labels` at `:1253-1270`; keep the AA "up to" comment with its row):

```python
def graphics_labels(render):
    """One label per Graphics-page row above Back, in GRAPHICS_CYCLES order."""
    return [
        f"Scale: {render.scale}x",
        f"Shading: {render.shading.title()}",
        f"Filter: {render.background_filter.title()}",
        f"AA: up to {render.msaa}x" if render.msaa else "AA: Off",
        f"Smoothing: {SMOOTHING_LABELS[render.smoothing]}",
    ]


def realism_labels(render):
    """One label per Realism-page row above Back, in REALISM_CYCLES order."""
    return [
        f"Lighting: {render.lighting.title()}",
        f"Shadows: {render.shadows.title()}",
        f"Realism: {render.realism.title()}",
        f"Integration: {INTEGRATION_LABELS[render.integration]}",
        f"Motion: {render.motion.title()}",
    ]
```

9. `system_menu_labels`: add `if page is SystemMenuPage.REALISM: return realism_labels(settings.render) + ["Back"]` beside the GRAPHICS branch, and change the CONFIG tail to append `"Graphics..."`, `"Realism..."`, `"Back to Menu"` in that order.
10. `render_system_menu:1307`: the small-button set becomes `(SystemMenuPage.CONFIG, SystemMenuPage.GRAPHICS, SystemMenuPage.REALISM)`.

The mouse route needs no change: `route_mouse` sets `cursor = hit` and replays `Command.ACCEPT` through `reduce_system_menu` for whatever page the presenter is on (`PyAitD/app/shell.py`, the `hit_test_system_menu` branch), and `SystemMenuLayout.hit_rows` derives from `rows(page)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_reducers.py tests/test_ui_render.py -q`
Expected: PASS

- [ ] **Step 5: Full gate (shell journeys walk these menus — fix any pin this split breaks the same way Step 1 fixed the direct pins), then commit**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
git add PyAitD/app/ui.py tests/test_ui_reducers.py tests/test_ui_render.py
git commit -m "feat: split the Graphics page into Graphics and Realism sub-pages"
```

---

### Task 5: `build_frame` blending and the shell wiring

**Files:**
- Modify: `PyAitD/render/scene.py:181-229` (`build_frame`)
- Modify: `PyAitD/app/shell.py` (`_scene_frame` at `:242`, a new `_motion_blend` helper beside it, and `run()`'s tick loop and scene refresh at `:1391`, `:1546-1572`)
- Test: `tests/test_scene.py`, `tests/test_main.py`

**Interfaces:**
- Consumes: `snapshot`, `blend_actor` from Task 1 (`from PyAitD.render.motion import blend_actor` in scene.py; `from PyAitD.render.motion import snapshot as motion_snapshot` in shell.py), `pose_geometry(..., pose_fn=...)` from Task 2, `session.settings.render.motion` from Task 3, `TICK_MS` (already imported by shell.py).
- Produces: `build_frame(game, floor, resolver, blend=None)` where `blend = (MotionSnapshot, alpha: float)`; `_scene_frame(game, floor, renderer, resolver, blend=None)`; `_motion_blend(session, motion_prev, accumulator) -> tuple | None`. Task 6's proof tool calls `build_frame(..., blend=...)` directly.

- [ ] **Step 1: Write the failing tests**

`tests/test_scene.py` builds frames from stub games (see the file's existing `build_frame` tests for the stub game/floor/resolver shapes — reuse the same helpers). Append, following the file's local stub conventions:

```python
def test_build_frame_blend_moves_geometry_but_not_the_logical_projection():
    # Build the file's standard one-actor stub game, then:
    from PyAitD.render.motion import snapshot
    game, floor, resolver = _stub_scene()   # use the file's existing helper name
    snap = snapshot(game)
    plain, plain_draw = build_frame(game, floor, resolver)
    # move the live actor a full step after the snapshot
    game.actors[hero_index].world_x += 100      # hero_index per the helper
    blended, blended_draw = build_frame(game, floor, resolver, blend=(snap, 0.5))
    moved, moved_draw = build_frame(game, floor, resolver)
    # position blends halfway
    assert blended.actors[0].position[0] == pytest.approx(moved.actors[0].position[0] - 50)
    # the logical projection and draw_list ignore the blend entirely
    assert blended_draw == moved_draw
    assert blended.actors[0].logical.points == moved.actors[0].logical.points


def test_build_frame_blend_snaps_on_a_camera_or_floor_mismatch():
    from dataclasses import replace as _replace
    from PyAitD.render.motion import snapshot
    game, floor, resolver = _stub_scene()
    snap = snapshot(game)
    stale = _replace(snap, camera=snap.camera + 1)
    game.actors[hero_index].world_x += 100
    unblended, _ = build_frame(game, floor, resolver)
    frame, _ = build_frame(game, floor, resolver, blend=(stale, 0.5))
    assert frame.actors[0].position == unblended.actors[0].position
    stale = _replace(snap, floor=snap.floor + 1)
    frame, _ = build_frame(game, floor, resolver, blend=(stale, 0.5))
    assert frame.actors[0].position == unblended.actors[0].position


def test_build_frame_without_blend_is_bytewise_todays_path():
    game, floor, resolver = _stub_scene()
    a, draw_a = build_frame(game, floor, resolver)
    b, draw_b = build_frame(game, floor, resolver, blend=None)
    assert draw_a == draw_b
    assert np.array_equal(a.actors[0].geometry.vertices, b.actors[0].geometry.vertices)
```

Adapt `_stub_scene()`/`hero_index` to the helper names actually present in `tests/test_scene.py` — the assertions are the contract; the stub plumbing follows the file. Append to `tests/test_main.py`:

```python
def test_motion_blend_helper_gates_on_mode_and_snapshot():
    from PyAitD.app.config import default_settings
    from PyAitD.app.shell import _motion_blend
    from PyAitD.engine.script.playworld import TICK_MS

    class _Session:
        settings = default_settings()   # motion="tick" until Task 6

    session = _Session()
    sentinel = object()
    assert _motion_blend(session, sentinel, 10) is None      # tick mode: never
    from dataclasses import replace
    session.settings = replace(session.settings,
                               render=replace(session.settings.render, motion="smooth"))
    assert _motion_blend(session, None, 10) is None          # no snapshot yet
    snap, alpha = _motion_blend(session, sentinel, 10)
    assert snap is sentinel and alpha == pytest.approx(10 / TICK_MS)
    _, alpha = _motion_blend(session, sentinel, TICK_MS * 3)
    assert alpha == 1.0                                      # clamped, never extrapolates
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_scene.py tests/test_main.py -q`
Expected: FAIL — `build_frame() got an unexpected keyword argument 'blend'`, `ImportError: cannot import name '_motion_blend'`

- [ ] **Step 3: Implement**

`PyAitD/render/scene.py` — add `from PyAitD.render.motion import blend_actor` to the imports. Change `build_frame`:

```python
def build_frame(game, floor, resolver, blend=None):
    """The per-frame scene: a float FrameDescription for the new renderers,
    and the unchanged draw_list (from the logical skin() bbox) so picking,
    the mouse contract and combat keep working byte-identically.

    `blend` is (MotionSnapshot, alpha) under motion="smooth": geometry,
    angles and position interpolate snapshot -> live state through the
    float pose twin. The logical projection below never blends."""
    room = floor.rooms[game.current_room]
    cam_idx = room.camera_indices[game.num_camera]
    state = CameraState.from_camera(
        floor.cameras[cam_idx], room.world_x, room.world_y, room.world_z,
    ).angles()
    snap, alpha = (None, 0.0)
    if blend is not None:
        snap, alpha = blend
        if snap.floor != game.current_floor or snap.camera != game.num_camera:
            # a camera cut or floor change since the snapshot: every actor
            # renders unblended this frame rather than smearing across it
            snap = None
    masks = tuple(floor.mask_draws(cam_idx))
    actors = []
    draw_list = []
    for index in sort_actor_indices(game, state.x, state.y, state.z):
        actor = game.actors[index]
        body = resolver.body(actor.body_num)
        if actor.anim == -1:
            states = [(0, (0, 0, 0))] * len(body.groups)
        else:
            states = anim_player_for(game, index).group_states()
        position = (
            actor.world_x + actor.step_x,
            actor.world_y + actor.step_y,
            actor.world_z + actor.step_z,
        )
        angles = (actor.alpha, actor.beta, actor.gamma)
        logical = skin(body, states, position, state, actor_angles=angles)
        draw_list.append((index, actor_bbox(logical)))
        draw_states, draw_angles, draw_position, pose_fn = states, angles, position, None
        if snap is not None:
            draw_states, draw_angles, draw_position, pose_fn = blend_actor(
                snap.actors.get(index), actor.body_num, actor.room, actor.anim,
                states, angles, position, alpha,
            )
        actors.append(ActorDraw(
            index,
            pose_geometry(body, draw_states, draw_angles,
                          ao=resolver.geometry_ao(actor.body_num),
                          refinement=resolver.refinement(actor.body_num),
                          pose_fn=pose_fn),
            draw_position,
            actor.room,
            tuple(actor.zv),
            logical,
            tuple(m.id for m in masks if mask_applies_to_actor(m, actor.room, actor.zv)),
            resolver.material_table(actor.body_num),
        ))
```

(the tail of the function — `killed`, `FrameDescription`, `return` — is unchanged).

`PyAitD/app/shell.py`:
1. Import: `from PyAitD.render.motion import snapshot as motion_snapshot`.
2. `_scene_frame` gains the pass-through:

```python
def _scene_frame(game, floor, renderer, resolver, blend=None):
    # (keep the existing comment block)
    frame, draw_list = build_frame(game, floor, resolver, blend)
    return renderer.compose_scene(frame), draw_list
```

3. New helper beside it:

```python
def _motion_blend(session, motion_prev, accumulator):
    """build_frame's blend argument for this frame, or None.

    Smooth motion only, with a snapshot taken before this game's most
    recent tick; alpha is the accumulator's leftover fraction of the
    next tick, clamped so a stalled frame holds the tick pose instead
    of extrapolating past it."""
    if motion_prev is None or session.settings.render.motion != "smooth":
        return None
    return motion_prev, min(accumulator / TICK_MS, 1.0)
```

4. In `run()`: initialise `motion_prev = None` beside `accumulator = 0` (`:1391`); inside the tick loop, first line of the body (before `play_tick`):

```python
            while accumulator >= TICK_MS and game.mode is GameMode.PLAY:
                motion_prev = motion_snapshot(game)
                play_tick(game, floor, input_buffer)
```

5. The PLAY scene refresh (`:1571-1572`) becomes:

```python
            if game.num_camera != -1:
                scene_frame, draw_list = _scene_frame(
                    game, floor, renderer, resolver,
                    _motion_blend(session, motion_prev, accumulator),
                )
```

6. In the `replaced is not None` adoption block (after `resolver = new_resolver`), add `motion_prev = None` — a hero swap, restart, cutscene hand-over or load must never blend from the old game's snapshot.

Every other `_scene_frame` caller stays blend-free (boot, branches, non-PLAY refreshes) — they render the tick pose, which is correct at those boundaries.

- [ ] **Step 4: Run tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_scene.py tests/test_main.py -q`
Expected: PASS

- [ ] **Step 5: Full gate (the journey tests drive `run()` with `motion="tick"`, exercising the None path), then commit**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
git add PyAitD/render/scene.py PyAitD/app/shell.py tests/test_scene.py tests/test_main.py
git commit -m "feat: blend actor motion between ticks in build_frame and the play loop"
```

---

### Task 6: flip the default, proof tooling, proof doc, docs

**Files:**
- Modify: `PyAitD/render/render_options.py:42-51` (default), `tests/test_render_options.py`, `tests/test_render_gl.py` (the classic-identity constructor), `tests/test_main.py` (the no-flag default assertion from Task 3 flips to `"smooth"`)
- Modify: `tools/prove_graphics.py`, `tests/test_prove_graphics.py`
- Create: `docs/motion-interpolation-proof.md`
- Modify: `CONTEXT.md`, `AGENTS.md`, `README.md`

**Interfaces:**
- Consumes: everything above. After this task `RenderOptions().motion == "smooth"`; `motion="tick"` is the escape hatch on the Realism page.

- [ ] **Step 1: Flip the default and update the pins (failing first)**

- `PyAitD/render/render_options.py`: `motion: str = "smooth"`.
- `tests/test_render_options.py`: `test_motion_defaults_to_tick_and_cycles` becomes `test_motion_defaults_to_smooth_and_cycles` (`options.motion == "smooth"`, first cycle → `"tick"`); the fallback test's expectations become `"smooth"`.
- `tests/test_main.py`: the Task 3 no-flag assertion becomes `.render.motion == "smooth"`; the Task 5 `_motion_blend` test's first assertion re-arms by building a `motion="tick"` settings explicitly (the default no longer is).
- `tests/test_render_gl.py:972` `test_classic_realism_matches_the_pre_materials_golden`: add `motion="tick"` to the `RenderOptions(...)` constructor the test builds, with the one-line comment `# names every roadmap-2 field the identity holds at` — the backend ignores `motion`, but the identity test documents the full all-off combination (spec: "names the two new fields explicitly once the defaults flip").
- `tests/test_ui_render.py`: `test_motion_label_titles_the_mode` — the default row now reads `"Motion: Smooth"`; keep both assertions by building each mode explicitly.

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_render_options.py tests/test_main.py tests/test_ui_render.py -q` — fix exactly the pins above until green.

- [ ] **Step 2: `prove_graphics --motion` and the `-tickmotion` twin**

In `tools/prove_graphics.py`:
- Imports: add `MOTION_MODES` to the `render_options` import; add `import dataclasses` and `from PyAitD.render.motion import MotionSnapshot, snapshot as motion_snapshot`.
- `render_fixture` gains `motion_blend=False`; when true, rebuild the frame blended at alpha 0.5 against a synthetic quarter-turn-back snapshot, so a still PNG shows the midpoint:

```python
def render_fixture(data_dir, name, scale, shading, ctx, realism="enhanced", smoothing=None,
                   shadows=None, integration=None, motion_blend=False):
    game, floor = _boot(data_dir, name)
    resolver = AssetResolver(game.assets)
    frame, _ = build_frame(game, floor, resolver)
    if motion_blend:
        # a synthetic "previous tick" 64 rotation units back: the blended
        # frame renders every actor 32 units (11 degrees) short of its
        # live beta, which is visibly between the two, deterministically
        snap = motion_snapshot(game)
        shifted = MotionSnapshot(snap.floor, snap.camera, {
            index: dataclasses.replace(
                entry, angles=(entry.angles[0], (entry.angles[1] - 64.0) % 1024.0, entry.angles[2]))
            for index, entry in snap.actors.items()
        })
        frame, _ = build_frame(game, floor, resolver, blend=(shifted, 0.5))
    options = RenderOptions(scale=scale, shading=shading, realism=realism)
    ...
```

(the rest unchanged; keep passing `resolver` where the old call built `AssetResolver(game.assets)` inline).
- `output_paths` rows grow a seventh `motion_blend` field (False everywhere), plus one new twin pair after the `-strong` pair:

```python
    paths += [(name, "smooth", "enhanced", level, mode_shadows, mode_integration, blend,
               out_dir / f"{name}-smooth-enhanced-tickmotion.png")
              for name in FIXTURES]
```

  where `blend = (motion == "smooth")` from a new `motion=None` parameter defaulting to `RenderOptions().motion` — under `--motion tick` the twin renders unblended, showing the escape hatch. All pre-existing rows append `False` before their path element; `main()`'s unpacking and `render_fixture` call add the field.
- `_parse_args` gains:

```python
    p.add_argument("--motion", choices=MOTION_MODES, default=RenderOptions().motion,
                   help="smooth renders the -tickmotion pair mid-blend (alpha 0.5); "
                        "tick renders it unblended")
```

- `tests/test_prove_graphics.py`: extend the `output_paths` pin (`:57-76`) for the seventh field and the `-tickmotion` suffix, following the pattern the `-hardshadow` rows use.

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_prove_graphics.py -q` — PASS.

- [ ] **Step 3: Write the proof document**

Create `docs/motion-interpolation-proof.md` in the repo's proof-doc shape (see `docs/soft-shadows-proof.md` for the template):

```markdown
# Motion interpolation proof

Date: <run date>
Spec: `docs/superpowers/specs/2026-08-31-actor-realism-roadmap-2-design.md` (sub-project I)
Plan: `docs/superpowers/plans/2026-08-31-motion-interpolation.md`

**This document's "Manual attestation" table is a checklist for a human
with real game data and a real window; every row starts `pending`.**

## What changed

Actors interpolate between 50 Hz simulation ticks at the display rate
under `motion=smooth` (the default): `render/motion.py` blends the
pre-tick snapshot toward the live state through a float twin of the
integer pose. `motion=tick` renders exactly the pre-change frames.
Picking, masks, the draw_list and the mouse contract read the tick pose
throughout. Rendered motion lags the simulation by up to one tick.

## Automated gates

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest \
    tests/test_motion.py tests/test_geometry.py tests/test_scene.py \
    tests/test_render_options.py tests/test_ui_reducers.py \
    tests/test_ui_render.py tests/test_main.py tests/test_prove_graphics.py -q
<paste the real output>

$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
<paste the real output>
```

## Frame time

<attic fixture, scale 4, msaa 4, smoothing 2: motion=smooth vs
motion=tick, measured the way the soft-shadows proof measured its
line, with the command shown. The budget gate is the roadmap's 1.5x
across all four sub-projects; record I's share here.>

## Manual attestation

| Check | Result |
|---|---|
| Walk the attic at 120 Hz: movement is stepless under `smooth`, visibly 50 Hz under `tick` | pending |
| Camera cut mid-walk: no smear, no double image on the cut frame | pending |
| Restart / load / hero swap: first frame shows no blend from the old game | pending |
| Realism page: Motion row cycles by keyboard and mouse; persists from the menu; `--motion tick` overrides for the session only | pending |
| `-tickmotion` proof pair: the blended render sits between the tick poses | pending |
```

Fill the two gate blocks by actually running the commands and pasting real output; leave the frame-time line's placeholders only if no GL/game data is available in the environment, and say so in the doc.

- [ ] **Step 4: Update the three docs**

- `CONTEXT.md`: add to the milestone table, after the Materials v2 row: `| Motion interpolation (roadmap 2 I) | Inter-tick pose/position blending behind a Motion knob, float pose twin, Graphics/Realism menu split | automated gates green; windowed attestation pending (docs/motion-interpolation-proof.md) |`. Add to the render-module table: `| render/motion.py | snapshot/blend_states/blend_actor + pose_vertices_float: inter-tick blending for build_frame, the float twin of skel.pose_vertices; pygame/GL-free |`. In the roadmap-2 spec row of the specs list nothing changes (the spec already exists).
- `AGENTS.md`: in the `make proof-graphics` line, mention the `-tickmotion` pair alongside the existing pairs.
- `README.md`: beside the `--shadows` flag documentation (`README.md:125`), document `--motion {tick,smooth}` with one line: smooth (default) blends actor motion between simulation ticks at the display rate; tick renders one pose per 50 Hz tick.

- [ ] **Step 5: Full gate, then commit**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
git add -A
git commit -m "feat: default motion=smooth; -tickmotion proof twin, proof doc, docs"
```

---

## Plan self-review (record kept)

- **Spec coverage:** I's design points all land: `render/motion.py` snapshot/blend/pose twin (Tasks 1–2), `CameraView`-style divergence bound pinned (Task 2), the knob with full plumbing (Task 3), the page split hosting its row (Task 4), `build_frame(blend=)` + snap rules + shell alpha (Task 5), default flip, `-tickmotion` twin, proof doc, doc updates (Task 6). The spec's snap rules list camera cut, floor change, spawn, body/room/anim change and teleport — all tested; "anim restarted" is covered by the anim-number check (a same-anim restart re-keys the AnimPlayer via `anim_player_for`, whose fresh `group_states` still blend continuously from the last committed pose, which is the desired look, not a smear).
- **Placeholders:** none; every step carries runnable content. Two deliberately file-local adaptations are called out as such (test_scene stub helper names, test_geometry import style) with the contract stated exactly.
- **Type consistency:** `blend = (MotionSnapshot, alpha)` everywhere; `blend_actor` returns the 4-tuple `(states, angles, position, pose_fn)` in Tasks 1, 2 and 5; `pose_fn=None` means integer pose in both `blend_actor` and `pose_geometry`; `REALISM_CYCLES[4] is cycle_motion` matches `realism_labels[4]`.
