# M2: AITD1 Actors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the player character in 3D over M1's 2D backgrounds: body/anim parsing, skinning, tank movement with hard collision, zone-driven camera switching, and mask occlusion, driven by a 50Hz play loop.

**Architecture:** FITD-exact math (fixed-point cos table, Y→X→Z rotations, perspective divide) ported into numpy; ModernGL rasterizes the projected mesh into a 320x200 offscreen actor layer which is mask-composited over the background and upscaled through M1's quad path. All fidelity-critical code is a faithful translation of FITD's `renderer.cpp`, `anim.cpp`, `main.cpp`, `polys.cpp`.

**Tech Stack:** Python 3.12, numpy, pygame-ce, ModernGL, pytest. No new dependencies.

## Global Constraints

- Python `>= 3.12`; Apple Silicon, windowed. No new dependencies beyond M1's (pygame-ce, moderngl, numpy, pytest).
- License GPLv2: every new/modified source file keeps `# SPDX-License-Identifier: GPL-2.0-only`.
- Reference implementation: FITD at `/Users/felipe.dos.santos/code/theirs/FITD/FitdLib/` — the port must reproduce its arithmetic exactly (C integer division = truncation toward zero; `>>16` = floor). Python's `//` floors: use `int(v / N)` for C-division ports, `v >> 16` for shift ports.
- Logic tick fixed 50Hz; render rate independent.
- Renderer draws primitives in body file order (painter's algorithm), no depth test.
- Errors: out-of-range body/anim index raises ValueError with PAK name and index; unknown primitive type raises ValueError naming the type.
- Game data read in place; tests skip when data absent (existing `data_dir` fixture).

## Verified golden values (real game data — do not re-derive)

- `LISTBODY.PAK`: 272 entries. `LISTANIM.PAK`: 305 entries.
- body 0: flags 0x1, zv (-630, 630, -900, 0, -360, 360), scratch 0, 65 vertices, 0 groups, 35 prims, 904 bytes.
- body 1: flags 0x3, zv (-630, 630, -1441, 0, -360, 540), scratch 10, 67 vertices, 2 groups, 47 prims, 1108 bytes.
- body 12: flags has INFO_ANIM, 150 vertices, 17 groups, 222 prims (M2 default player body).
- anim 0: 2 frames, 2 groups, frame0 timestamp 5, step (0,0,0), 52 bytes.
- anim 2: 2 frames, 17 groups, frame0 timestamp 30, step (0,0,-129), 292 bytes (M2 default player anim).
- cos table: 1024 entries; `COS[i] = trunc(sin(i*pi/512)*32768)` clamped to [-32767, 32767], except `COS[0] = 4` (FITD quirk — keep it). Pinned: COS[1]=201, COS[2]=402, COS[256]=32767, COS[512]=0, COS[768]=-32767, COS[1023]=-201.
- Floor 0 room 0: world (0,0,0); room cameras [0,1,2,3,4]. Camera 2: alpha 109, beta 185, gamma 0, x -741 (u16 64795), y 280, z -116 (u16 65420), focal1 300, focal2 189, focal3 158. Camera betas: [954, 152, 185, 390, 213].
- Camera 2 viewed-room 0 cover zone 0 (s16): [(-742,207), (-754,499), (-14,501), (-8,48), (-12,-87), (-655,18)]. Player spawn: world (-3642, 0, 1977) (= zone centroid (-364,198) * 10). `find_best_camera` at spawn with actor beta 0 returns camera 2 (only zone containing the point; angle score 697).
- Body flags: INFO_ANIM = 2, INFO_TORTUE = 4, INFO_OPTIMISE = 8 (M2 implements the non-optimise path only — all AITD1 data).
- Primitive type enum: Line 0, Poly 1, Point 2, Sphere 3, Disk 4, Cylinder 5, BigPoint 6, Zixel 7.

---

### Task 1: Cos table

**Files:**
- Create: `maitd/cos_table.py`
- Test: `tests/test_cos_table.py`

**Interfaces:**
- Produces: `COS_TABLE: list[int]` — 1024 ints, indexed `& 0x3FF` by all rotation code (tasks 4-6).

- [ ] **Step 1: Write failing test** `tests/test_cos_table.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
from maitd.cos_table import COS_TABLE


def test_length():
    assert len(COS_TABLE) == 1024


def test_pinned_values():
    assert COS_TABLE[0] == 4  # FITD quirk: 0 was bumped to 4
    assert COS_TABLE[1] == 201
    assert COS_TABLE[2] == 402
    assert COS_TABLE[256] == 32767
    assert COS_TABLE[512] == 0
    assert COS_TABLE[768] == -32767
    assert COS_TABLE[1023] == -201


def test_formula_consistency():
    import math
    for i in range(1024):
        expected = int(math.sin(i * math.pi / 512) * 32768)  # trunc toward zero
        expected = max(min(expected, 32767), -32767)
        if i == 0:
            continue  # pinned quirk
        assert COS_TABLE[i] == expected, f"index {i}"
```

- [ ] **Step 2: Run test, verify fail**

Run: `.venv/bin/pytest tests/test_cos_table.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'maitd.cos_table'`.

- [ ] **Step 3: Implement** `maitd/cos_table.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
"""1024-entry fixed-point sine table (FITD cosTable.cpp, scale 32768).

COS[i] ~= sin(i * 2*pi/2048) * 32768. Index 0 is 4 in FITD's table (quirk,
kept for byte-exact behavior: rotation code never reads sin(0), but reads
index 0 as cos(3*pi/4) ~ 0).
"""
import math

COS_TABLE = [max(min(int(math.sin(i * math.pi / 512) * 32768), 32767), -32767) for i in range(1024)]
COS_TABLE[0] = 4
```

- [ ] **Step 4: Run test, verify pass**

Run: `.venv/bin/pytest tests/test_cos_table.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add maitd/cos_table.py tests/test_cos_table.py
git commit -m "feat: fixed-point cos table (FITD port)"
```

---

### Task 2: Body and animation parsers

**Files:**
- Modify: `maitd/formats.py` (append)
- Test: `tests/test_body_anim.py`

**Interfaces:**
- Consumes: `maitd.pak.Pak` (M1), real data via `data_dir` fixture.
- Produces (dataclasses, all ints):
  - `@dataclass Primitive: type: int, material: int, color: int, points: list[int], size: int = 0`
  - `@dataclass Group: start: int, num_vertices: int, base_vertices: int, org_group: int, num_group: int, delta_x: int, delta_y: int, delta_z: int`
  - `@dataclass Body: flags: int, zv: tuple[int, ...] (6), scratch: tuple[int, ...], vertices: list[tuple[int, int, int]], groups: list[Group], group_order: list[int], primitives: list[Primitive]`
  - `@dataclass Frame: timestamp: int, anim_step: tuple[int, int, int], group_types: list[int], group_deltas: list[tuple[int, int, int]]`
  - `@dataclass Animation: num_frames: int, num_groups: int, frames: list[Frame]`
  - `def parse_body(raw: bytes) -> Body` — raises ValueError on unknown primitive type
  - `def parse_anim(raw: bytes) -> Animation`
- Layout notes: vertex indices stored *6 (`points[j] / 6`); group offsets stored /0x10 (group_order entries) and /6 (start/base_vertices); primitive point lists *6 → real index `p // 6`; Sphere has extra u16 `size` after `even`.

- [ ] **Step 1: Write failing tests** `tests/test_body_anim.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
import pytest

from maitd.formats import parse_anim, parse_body
from maitd.pak import Pak


def _read(pak_name, index, data_dir):
    return Pak(data_dir / pak_name).read(index)


def test_body0_golden(data_dir):
    body = parse_body(_read("LISTBODY.PAK", 0, data_dir))
    assert body.flags == 0x1
    assert body.zv == (-630, 630, -900, 0, -360, 360)
    assert body.scratch == ()
    assert len(body.vertices) == 65
    assert len(body.groups) == 0
    assert len(body.primitives) == 35


def test_body1_golden(data_dir):
    body = parse_body(_read("LISTBODY.PAK", 1, data_dir))
    assert body.flags == 0x3
    assert body.zv == (-630, 630, -1441, 0, -360, 540)
    assert len(body.scratch) == 10
    assert len(body.vertices) == 67
    assert len(body.groups) == 2
    assert len(body.group_order) == 2
    assert len(body.primitives) == 47


def test_body12_player_default(data_dir):
    body = parse_body(_read("LISTBODY.PAK", 12, data_dir))
    assert body.flags & 0x2  # INFO_ANIM
    assert len(body.vertices) == 150
    assert len(body.groups) == 17
    assert len(body.primitives) == 222
    # vertex indices stored *6 -> real index divides by 6
    for prim in body.primitives:
        assert all(p % 6 == 0 for p in prim.points)


def test_anim_golden(data_dir):
    anim0 = parse_anim(_read("LISTANIM.PAK", 0, data_dir))
    assert anim0.num_frames == 2
    assert anim0.num_groups == 2
    assert anim0.frames[0].timestamp == 5
    assert anim0.frames[0].anim_step == (0, 0, 0)

    anim2 = parse_anim(_read("LISTANIM.PAK", 2, data_dir))
    assert anim2.num_frames == 2
    assert anim2.num_groups == 17
    assert anim2.frames[0].timestamp == 30
    assert anim2.frames[0].anim_step == (0, 0, -129)


def test_parse_anim_rejects_bad_size():
    with pytest.raises(ValueError):
        parse_anim(b"\x00" * 3)
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/pytest tests/test_body_anim.py -q`
Expected: FAIL, `ImportError: cannot import name 'parse_body'`.

- [ ] **Step 3: Append to `maitd/formats.py`**

```python
@dataclass
class Primitive:
    type: int
    material: int
    color: int
    points: list[int]
    size: int = 0


@dataclass
class Group:
    start: int
    num_vertices: int
    base_vertices: int
    org_group: int
    num_group: int
    delta_x: int
    delta_y: int
    delta_z: int


@dataclass
class Body:
    flags: int
    zv: tuple
    scratch: tuple
    vertices: list
    groups: list
    group_order: list
    primitives: list


@dataclass
class Frame:
    timestamp: int
    anim_step: tuple
    group_types: list
    group_deltas: list


@dataclass
class Animation:
    num_frames: int
    num_groups: int
    frames: list


INFO_ANIM = 2

_PRIM_POINT_LIKE = (2, 6, 7)  # Point, BigPoint, Zixel


def parse_body(raw):
    p = 0
    flags = _u16(raw, p)
    p += 2
    zv = tuple(struct.unpack_from("<6h", raw, p))
    p += 12
    scratch_size = _u16(raw, p)
    p += 2
    scratch = tuple(raw[p : p + scratch_size])
    p += scratch_size
    num_vertices = _u16(raw, p)
    p += 2
    vertices = [
        (struct.unpack_from("<h", raw, p + 6 * i)[0],
         struct.unpack_from("<h", raw, p + 6 * i + 2)[0],
         struct.unpack_from("<h", raw, p + 6 * i + 4)[0])
        for i in range(num_vertices)
    ]
    p += num_vertices * 6
    groups = []
    group_order = []
    if flags & INFO_ANIM:
        num_groups = _u16(raw, p)
        p += 2
        group_order = [v // 0x10 for v in struct.unpack_from(f"<{num_groups}H", raw, p)]
        p += num_groups * 2
        for _ in range(num_groups):
            groups.append(
                Group(
                    start=_u16(raw, p) // 6,
                    num_vertices=_u16(raw, p + 2),
                    base_vertices=_u16(raw, p + 4) // 6,
                    org_group=raw[p + 6],
                    num_group=raw[p + 7],
                    delta_x=_s16(raw, p + 8),
                    delta_y=_s16(raw, p + 10),
                    delta_z=_s16(raw, p + 12),
                )
            )
            p += 0x10
    num_primitives = _u16(raw, p)
    p += 2
    primitives = []
    for _ in range(num_primitives):
        prim_type = raw[p]
        p += 1
        if prim_type in (1, 8, 9, 10):  # poly family
            num_points = raw[p]
            p += 1
            material, color = raw[p], raw[p + 1]
            p += 2
            points = list(struct.unpack_from(f"<{num_points}H", raw, p))
            p += num_points * 2
            primitives.append(Primitive(prim_type, material, color, [v // 6 for v in points]))
        elif prim_type == 0:  # line
            material, color = raw[p], raw[p + 1]
            p += 3
            points = list(struct.unpack_from("<2H", raw, p))
            p += 4
            primitives.append(Primitive(prim_type, material, color, [v // 6 for v in points]))
        elif prim_type in _PRIM_POINT_LIKE:  # point / big point / zixel
            material, color = raw[p], raw[p + 1]
            p += 3
            point = _u16(raw, p)
            p += 2
            primitives.append(Primitive(prim_type, material, color, [point // 6]))
        elif prim_type == 3:  # sphere
            material, color = raw[p], raw[p + 1]
            p += 3
            size = _u16(raw, p)
            p += 2
            point = _u16(raw, p)
            p += 2
            primitives.append(Primitive(prim_type, material, color, [point // 6], size=size))
        else:
            raise ValueError(f"body: unknown primitive type {prim_type} at byte {p - 1}")
    return Body(flags, zv, scratch, vertices, groups, group_order, primitives)


def parse_anim(raw):
    if len(raw) < 4:
        raise ValueError(f"anim too small: {len(raw)} bytes")
    num_frames = _u16(raw, 0)
    num_groups = _u16(raw, 2)
    p = 4
    frames = []
    for _ in range(num_frames):
        timestamp = _u16(raw, p)
        step = (struct.unpack_from("<h", raw, p + 2)[0],
                struct.unpack_from("<h", raw, p + 4)[0],
                struct.unpack_from("<h", raw, p + 6)[0])
        p += 8
        types = []
        deltas = []
        for _ in range(num_groups):
            types.append(_s16(raw, p))
            deltas.append((_s16(raw, p + 2), _s16(raw, p + 4), _s16(raw, p + 6)))
            p += 8
        frames.append(Frame(timestamp, step, types, deltas))
    return Animation(num_frames, num_groups, frames)
```

Note: imports `dataclass` and `struct` already exist in `maitd/formats.py` from M1; append only the new code.

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_body_anim.py -q`
Expected: 5 passed. Then full suite: `.venv/bin/pytest -q` — expect 36 passed.

- [ ] **Step 5: Commit**

```bash
git add maitd/formats.py tests/test_body_anim.py
git commit -m "feat: body and animation format parsers"
```

---

### Task 3: Asset registry

**Files:**
- Create: `maitd/assets.py`
- Test: `tests/test_assets.py`

**Interfaces:**
- Consumes: `maitd.floor.load_entry(pak_path: str, index: int) -> bytes` (M1 LRU); `parse_body`, `parse_anim` (task 2).
- Produces:
  - `class Assets` — `Assets(data_dir: pathlib.Path)`
    - `.body(index: int) -> Body` — raises KeyError out of range
    - `.anim(index: int) -> Animation` — raises KeyError out of range
    - `.num_bodies: int`, `.num_anims: int`
    - `.clear()` — clears parse caches

- [ ] **Step 1: Write failing tests** `tests/test_assets.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
import pytest

from maitd.assets import Assets


def test_loads(data_dir):
    assets = Assets(data_dir)
    assert assets.num_bodies == 272
    assert assets.num_anims == 305


def test_body_anim_content(data_dir):
    assets = Assets(data_dir)
    body = assets.body(12)
    assert len(body.vertices) == 150
    anim = assets.anim(2)
    assert anim.num_frames == 2


def test_out_of_range(data_dir):
    assets = Assets(data_dir)
    with pytest.raises(KeyError):
        assets.body(9999)
    with pytest.raises(KeyError):
        assets.anim(9999)


def test_parse_cache(data_dir):
    assets = Assets(data_dir)
    first = assets.body(12)
    second = assets.body(12)
    assert first is second  # parsed once, cached object
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/pytest tests/test_assets.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'maitd.assets'`.

- [ ] **Step 3: Implement** `maitd/assets.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Parsed body/animation asset registry (parse-once caches over the M1 LRU)."""
from maitd.floor import load_entry
from maitd.formats import parse_anim, parse_body
from maitd.pak import Pak, find_pak

BODIES_PAK = "LISTBODY"
ANIMS_PAK = "LISTANIM"


class Assets:
    def __init__(self, data_dir):
        self._bodies_pak = str(find_pak(data_dir, BODIES_PAK))
        self._anims_pak = str(find_pak(data_dir, ANIMS_PAK))
        self.num_bodies = Pak(self._bodies_pak).count
        self.num_anims = Pak(self._anims_pak).count
        self._bodies = {}
        self._anims = {}

    def body(self, index):
        if not 0 <= index < self.num_bodies:
            raise KeyError(f"body {index} out of range (0..{self.num_bodies - 1})")
        if index not in self._bodies:
            self._bodies[index] = parse_body(load_entry(self._bodies_pak, index))
        return self._bodies[index]

    def anim(self, index):
        if not 0 <= index < self.num_anims:
            raise KeyError(f"anim {index} out of range (0..{self.num_anims - 1})")
        if index not in self._anims:
            self._anims[index] = parse_anim(load_entry(self._anims_pak, index))
        return self._anims[index]

    def clear(self):
        self._bodies.clear()
        self._anims.clear()
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_assets.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add maitd/assets.py tests/test_assets.py
git commit -m "feat: body/anim asset registry"
```

---

### Task 4: Camera transform math

**Files:**
- Create: `maitd/world.py`
- Test: `tests/test_world.py`

**Interfaces:**
- Consumes: `COS_TABLE` (task 1).
- Produces:
  - `@dataclass CameraState: alpha: int, beta: int, gamma: int, x: int, y: int, z: int, focal1: int, focal2: int, focal3: int`
    - `CameraState.from_camera(camera: Camera) -> CameraState` (room-space → world offsets: `x = (camera.x - room.world_x) * 10`, `y = (room.world_y - camera.y) * 10`, `z = (room.world_z - camera.z) * 10`)
    - `.angles()` — sets rotation state (returns self)
    - `.project(x: int, y: int, z: int) -> tuple[float, float, float]` — camera-space point → (screen_x, screen_y, depth); depth <= 50 returns (-10000, -10000, -10000); height clamp y > 10000 → same sentinel
  - `def transform_point(x: int, y: int, z: int, angles: CameraState) -> tuple[int, int, int]` — Y→X→Z fixed-point rotation (truncating division)
  - `def rotate_step(angle: int, x: int, z: int) -> tuple[int, int]` — FITD `Rotate` port, returns (x_out, z_out) where out x uses cos*... exact port: `x_out = (v2 >> 16), z_out = (v1 >> 16)` with the `& 0xFFFF0000` masking
- C-division semantics: `int(v / 65536)` for transform_point; `(v >> 16) << 1` patterns stay as written (`v >> 16` floor).

- [ ] **Step 1: Write failing tests** `tests/test_world.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
from maitd.world import CameraState, rotate_step, transform_point


def test_identity_camera_no_rotation():
    cam = CameraState(0, 0, 0, 0, 0, 0, 300, 100, 100)
    cam.angles()
    assert transform_point(100, 50, 200, cam) == (100, 50, 200)


def test_rotate_90_degrees():
    # angle 0x100 = 90 deg. FITD Rotate: z_out = cos*y - sin*z ; x_out = sin*y + cos*z
    # (cos(90)=COS[0x200]=0-ish via quirk 4, sin(90)=32767 -> truncation gives -19, not -20)
    assert rotate_step(0x100, 10, 20) == (10, -19)
    assert rotate_step(0x100, 10, 0)[0] == 10
    assert rotate_step(0x100, 0, 10)[1] == -10


def test_rotate_step_identity():
    assert rotate_step(0, 10, 20) == (20, 10)  # angle==0 branch: x_out = z, z_out = y


def test_camera_from_room_coords():
    from maitd.formats import Camera
    cam = Camera(109, 185, 0, -741, 280, -116, 300, 189, 158)
    state = CameraState.from_camera(cam, world_x=0, world_y=0, world_z=0)
    assert (state.x, state.y, state.z) == (-7410, -2800, 1160)


def test_projection_center():
    # a point exactly at the camera origin + perspective: Z = focal1 -> X/Z*fov + center == center
    cam = CameraState(0, 0, 0, 0, 0, 0, 300, 189, 158)
    cam.angles()
    px, py, depth = cam.project(0, 0, 0)
    assert px == 160.0 and py == 100.0 and depth == 300
    # depth clip: Z + perspective <= 50 -> sentinel
    px2, py2, d2 = cam.project(0, 0, -290)
    assert (px2, py2, d2) == (-10000.0, -10000.0, -10000.0)
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/pytest tests/test_world.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'maitd.world'`.

- [ ] **Step 3: Implement** `maitd/world.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Camera math ports from FITD main.cpp/renderer.cpp (fixed point, exact)."""
from dataclasses import dataclass

from maitd.cos_table import COS_TABLE
from maitd.formats import Camera

SCREEN_CENTER_X = 160
SCREEN_CENTER_Y = 100


@dataclass
class CameraState:
    alpha: int
    beta: int
    gamma: int
    x: int
    y: int
    z: int
    focal1: int
    focal2: int
    focal3: int

    @classmethod
    def from_camera(cls, camera, world_x, world_y, world_z):
        return cls(
            camera.alpha,
            camera.beta,
            camera.gamma,
            (camera.x - world_x) * 10,
            (world_y - camera.y) * 10,
            (world_z - camera.z) * 10,
            camera.focal1,
            camera.focal2,
            camera.focal3,
        )

    def angles(self):
        self._use_x = self.alpha & 0x3FF
        self._use_y = self.beta & 0x3FF
        self._use_z = self.gamma & 0x3FF
        return self

    def project(self, x, y, z):
        if y > 10000:
            return (-10000.0, -10000.0, -10000.0)
        y -= self.y
        x, y, z = transform_point(x, y, z, self)
        depth = z + self.focal1
        if depth <= 50:
            return (-10000.0, -10000.0, -10000.0)
        sx = (x * self.focal2) / depth + SCREEN_CENTER_X
        sy = (y * self.focal3) / depth + SCREEN_CENTER_Y
        return (sx, sy, depth)


def _trunc_div(v):
    return int(v / 65536)  # C integer division: truncation toward zero


def transform_point(x, y, z, angles):
    ax, bx, cx = x, y, z
    if angles._use_y:
        s = COS_TABLE[angles._use_y]
        c = COS_TABLE[(angles._use_y + 0x100) & 0x3FF]
        x = (_trunc_div(ax * s - cx * c)) << 1
        z = (_trunc_div(ax * c + cx * s)) << 1
    else:
        x, z = ax, cx
    if angles._use_x:
        s = COS_TABLE[angles._use_x]
        c = COS_TABLE[(angles._use_x + 0x100) & 0x3FF]
        temp_y = bx
        temp_z = z
        y = (_trunc_div(temp_y * s - temp_z * c)) << 1
        z = (_trunc_div(temp_y * c + temp_z * s)) << 1
    else:
        y = bx
    if angles._use_z:
        s = COS_TABLE[angles._use_z]
        c = COS_TABLE[(angles._use_z + 0x100) & 0x3FF]
        temp_x = x
        temp_y = y
        x = (_trunc_div(temp_x * s - temp_y * c)) << 1
        y = (_trunc_div(temp_x * c + temp_y * s)) << 1
    return (x, y, z)


def rotate_step(angle, x, z):
    # FITD Rotate() port: xOut/zOut are y/z in FITD terms; here (x, z) vector
    if angle:
        sinv = COS_TABLE[angle & 0x3FF]
        cosv = COS_TABLE[(angle + 0x100) & 0x3FF]
        v1 = ((cosv * x) << 1) & 0xFFFF0000
        v2 = ((sinv * x) << 1) & 0xFFFF0000
        v1 -= (sinv * z) << 1 & 0xFFFF0000
        v2 += (cosv * z) << 1 & 0xFFFF0000
        z_out = v1 >> 16
        x_out = v2 >> 16
    else:
        x_out = z
        z_out = x
    return (x_out, z_out)
```

Operator precedence note: `(sinv * z) << 1 & 0xFFFF0000` — Python parses `((sinv * z) << 1) & 0xFFFF0000`; matches C `((cosTable * z) << 1) & 0xFFFF0000`. Keep the parentheses exactly as written above.

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_world.py -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add maitd/world.py tests/test_world.py
git commit -m "feat: camera transform math (FITD fixed-point port)"
```

---

### Task 5: Skinning and projection

**Files:**
- Create: `maitd/skel.py`
- Test: `tests/test_skel.py`

**Interfaces:**
- Consumes: `Body`, `Primitive` (task 2), `CameraState`, `transform_point` (task 4), `COS_TABLE` (task 1).
- Produces:
  - `@dataclass PrimEntry: type: int, color: int, points: list[tuple[float, float, float]], size: float = 0` — screen-space points (x, y, depth), culled if min depth <= 100. For spheres (type 3), `size` = screen-space radius `prim.size * camera.focal2 / depth` of its point.
  - `@dataclass RenderResult: points: list[tuple[float, float, float]], primitives: list[PrimEntry]`
  - `def skin(body: Body, group_states: list[tuple[int, tuple[int, int, int]]], position: tuple[int, int, int], camera: CameraState) -> RenderResult` — group_states = per-group (type, (dx, dy, dz)) from the anim player; AITD1 (non-optimise) path of FITD `AnimNuage` only.
- Port semantics (FITD renderer.cpp AnimNuage): copy vertices; groups applied in `group_order` order — type 0 rotate (InitGroupeRot from state delta + recursive RotateGroupe over children), type 1 translate group verts, type 2 zoom (`v * (d + 256) / 256`, truncating); then every group's vertices += base vertex; add render offsets (x - cam.x, y, z - cam.z); height clamp; subtract cam.y; transform_point; project.

- [ ] **Step 1: Write failing tests** `tests/test_skel.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
from maitd.formats import Body, Group, Primitive
from maitd.skel import skin
from maitd.world import CameraState


def _cube_body():
    return Body(
        flags=0,
        zv=(0, 0, 0, 0, 0, 0),
        scratch=(),
        vertices=[(0, 0, 0), (100, 0, 0), (100, 100, 0), (0, 100, 0)],
        groups=[],
        group_order=[],
        primitives=[Primitive(1, 0, 42, [0, 1, 2, 3])],
    )


def test_static_prim_projects():
    cam = CameraState(0, 0, 0, 0, 0, 0, 300, 100, 100).angles()
    result = skin(_cube_body(), [], (0, 0, 300), cam)
    assert len(result.primitives) == 1
    prim = result.primitives[0]
    assert prim.color == 42
    # point 0 at camera center-ish: world (0,0,300) - cam (0,0,0) => Z=300 -> depth 600
    px, py, depth = prim.points[0]
    assert px == 160.0 and py == 100.0
    assert depth == 600


def test_depth_cull():
    cam = CameraState(0, 0, 0, 0, 0, 0, 300, 100, 100).angles()
    # Z = -290 => depth 10 <= 50 -> sentinel -> culled
    result = skin(_cube_body(), [], (0, 0, -290), cam)
    assert result.primitives == []


def test_translate_group():
    body = Body(
        flags=2,
        zv=(0, 0, 0, 0, 0, 0),
        scratch=(0,),
        vertices=[(0, 0, 0), (10, 0, 0)],
        groups=[Group(0, 2, 0, 0, 0, 0, 0, 0)],
        group_order=[0],
        primitives=[Primitive(1, 0, 1, [0, 1])],
    )
    cam = CameraState(0, 0, 0, 0, 0, 0, 300, 100, 100).angles()
    states = [(1, (50, 0, 0))]
    result = skin(body, states, (0, 0, 300), cam)
    x0 = result.points[0][0]
    assert x0 == 160.0 + (50 * 100) / 600  # 168.33...
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/pytest tests/test_skel.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'maitd.skel'`.

- [ ] **Step 3: Implement** `maitd/skel.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Skinning port of FITD renderer.cpp AnimNuage (AITD1 non-optimise path)."""
from dataclasses import dataclass

from maitd.cos_table import COS_TABLE
from maitd.world import transform_point


@dataclass
class PrimEntry:
    type: int
    color: int
    points: list
    size: float = 0


@dataclass
class RenderResult:
    points: list
    primitives: list


def _trunc_div(v, n):
    return int(v / n)


def skin(body, group_states, position, camera):
    pts = [list(v) for v in body.vertices]
    num_points = len(pts)

    for order_idx in body.group_order:
        group = body.groups[order_idx]
        gtype, (dx, dy, dz) = group_states[order_idx]
        if dx or dy or dz:
            if gtype == 0:
                _rotate_group(pts, group, body.groups, dx, dy, dz)
            elif gtype == 1:
                for i in range(group.num_vertices):
                    p = pts[group.start + i]
                    p[0] += dx
                    p[1] += dy
                    p[2] += dz
            elif gtype == 2:
                for i in range(group.num_vertices):
                    p = pts[group.start + i]
                    p[0] = _trunc_div(p[0] * (dx + 256), 256)
                    p[1] = _trunc_div(p[1] * (dy + 256), 256)
                    p[2] = _trunc_div(p[2] * (dz + 256), 256)

    for group in body.groups:
        base = pts[group.base_vertices]
        for i in range(group.num_vertices):
            p = pts[group.start + i]
            p[0] += base[0]
            p[1] += base[1]
            p[2] += base[2]

    px, py, pz = position
    projected = []
    for p in pts:
        x = p[0] + px - camera.x
        y = p[1] + py
        z = p[2] + pz - camera.z
        if y > 10000:
            projected.append((-10000.0, -10000.0, -10000.0))
            continue
        y -= camera.y
        x, y, z = transform_point(x, y, z, camera)
        sx, sy, depth = camera.project(x, y, z)
        projected.append((sx, sy, depth))

    primitives = []
    for prim in body.primitives:
        depth_min = 32000.0
        entries = []
        for idx in prim.points:
            e = projected[idx]
            entries.append(e)
            if e[2] < depth_min:
                depth_min = e[2]
        if depth_min > 100:
            size = 0.0
            if prim.type == 3:  # sphere: screen-space radius (FITD renderer.cpp)
                size = (prim.size * camera.focal2) / depth_min
            primitives.append(PrimEntry(prim.type, prim.color, entries, size))
    return RenderResult(projected, primitives)


def _rotate_group(pts, group, groups, dx, dy, dz):
    # InitGroupeRot + RotateGroupe (recursive over children) port
    _rotate_list(pts, group.start, group.num_vertices, dx, dy, dz)
    for other in groups:
        if other.org_group == group.num_group and other is not group:
            _rotate_group(pts, other, groups, dx, dy, dz)


def _rotate_list(pts, start, count, dx, dy, dz):
    rot_y = dy & 0x3FF
    rot_x = dx & 0x3FF
    rot_z = dz & 0x3FF
    for i in range(start, start + count):
        x, y, z = pts[i]
        if rot_y:
            s = COS_TABLE[rot_y]
            c = COS_TABLE[(rot_y + 0x100) & 0x3FF]
            x, z = ((x * s - z * c) >> 16) << 1, ((x * c + z * s) >> 16) << 1
        if rot_x:
            s = COS_TABLE[rot_x]
            c = COS_TABLE[(rot_x + 0x100) & 0x3FF]
            y, z = ((y * s - z * c) >> 16) << 1, ((y * c + z * s) >> 16) << 1
        if rot_z:
            s = COS_TABLE[rot_z]
            c = COS_TABLE[(rot_z + 0x100) & 0x3FF]
            x, y = ((x * s - y * c) >> 16) << 1, ((x * c + y * s) >> 16) << 1
        pts[i] = [x, y, z]
```

Note: `camera.project` already adds focal1 to Z; the transform above subtracts camera.y before `transform_point` and the height clamp runs before it — matching AnimNuage's ordering. Depth semantics (Z after transform + perspective) live in `project`, so `skin` passes already-rotated camera-space coords.

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_skel.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add maitd/skel.py tests/test_skel.py
git commit -m "feat: body skinning and projection (AnimNuage port)"
```

---

### Task 6: Animation player

**Files:**
- Create: `maitd/anim.py`
- Test: `tests/test_anim_player.py`

**Interfaces:**
- Consumes: `Animation`, `Body` (task 2).
- Produces:
  - `class AnimPlayer` — `AnimPlayer(body: Body, anim: Animation, start_tick: int)`
    - `.group_states() -> list[tuple[int, tuple[int, int, int]]]` — current per-group (type, delta) interpolated states
    - `.advance(tick: int) -> bool` — updates to tick; returns True when the animation looped (frame wrapped)
    - `.set_anim(anim, start_tick)` — switch animation (SetAnimObjet port)
  - `def patch_inter_angle(value: int, previous: int, next_: int, bp: int, bx: int) -> int` (FITD PatchInterAngle port)
  - `def patch_inter_step(value: int, previous: int, next_: int, bp: int, bx: int) -> int` (FITD PatchInterStep port; returns computed value)

- [ ] **Step 1: Write failing tests** `tests/test_anim_player.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
from maitd.anim import patch_inter_angle, patch_inter_step


def test_patch_angle_equal():
    assert patch_inter_angle(0, 100, 100, 5, 10) == 100


def test_patch_angle_small_diff():
    assert patch_inter_angle(0, 100, 200, 5, 10) == 150


def test_patch_angle_wrap_positive():
    # diff > 0x200: previous += 0x400, then next - previous (truncating mid)
    assert patch_inter_angle(0, 0, 0x300, 5, 10) == 0x380


def test_patch_angle_wrap_negative():
    assert patch_inter_angle(0, 0x300, 0, 5, 10) == 0x380


def test_patch_step():
    assert patch_inter_step(0, 10, 30, 5, 10) == 20
    assert patch_inter_step(0, 30, 10, 5, 10) == 20
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/pytest tests/test_anim_player.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'maitd.anim'`.

- [ ] **Step 3: Implement** `maitd/anim.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Animation state machine port (FITD anim.cpp SetAnimObjet/SetInterAnimObjet)."""


def _trunc_div(v, n):
    return int(v / n)


def patch_inter_angle(value, previous, next_, bp, bx):
    diff = next_ - previous
    if diff == 0:
        return next_
    if diff <= 0x200:
        if diff >= -0x200:
            return _trunc_div(diff * bp, bx) + previous
        next_ += 0x400
        next_ -= previous
        return _trunc_div(next_ * bp, bx) + previous
    previous += 0x400
    next_ -= previous
    return _trunc_div(next_ * bp, bx) + previous


def patch_inter_step(value, previous, next_, bp, bx):
    if next_ == previous:
        return next_
    return _trunc_div((next_ - previous) * bp, bx) + previous


class AnimPlayer:
    def __init__(self, body, anim, start_tick):
        self.body = body
        self.anim = anim
        self.frame = 0
        self.start_tick = start_tick
        self.prev_frame = None  # last committed keyframe (FITD startAnim)
        self._states = [(0, (0, 0, 0))] * len(body.groups)

    def set_anim(self, anim, start_tick):
        # SetAnimObjet port (AITD1: keep current frame, apply keyframe 0 states)
        self.anim = anim
        self.start_tick = start_tick
        self.prev_frame = None
        self.frame = 0
        keyframe = anim.frames[0]
        n = min(anim.num_groups, len(self.body.groups))
        self._states = list(
            zip(keyframe.group_types[:n], keyframe.group_deltas[:n])
        ) + [(0, (0, 0, 0))] * (len(self.body.groups) - n)

    def group_states(self):
        return self._states

    def advance(self, tick):
        # SetInterAnimObjet port (non-optimise branch)
        n = min(self.anim.num_groups, len(self.body.groups))
        frame = self.frame % self.anim.num_frames
        keyframe = self.anim.frames[frame]
        keyframe_length = keyframe.timestamp
        time = (tick - self.start_tick) & 0xFFFF
        bp, bx = time, keyframe_length
        prev = self.prev_frame if self.prev_frame is not None else keyframe
        if time < keyframe_length:
            states = []
            for i in range(n):
                gtype = keyframe.group_types[i]
                pd = prev.group_deltas[i]
                nd = keyframe.group_deltas[i]
                if gtype == 0:
                    delta = (
                        patch_inter_angle(0, pd[0], nd[0], bp, bx),
                        patch_inter_angle(0, pd[1], nd[1], bp, bx),
                        patch_inter_angle(0, pd[2], nd[2], bp, bx),
                    )
                else:
                    delta = (
                        patch_inter_step(0, pd[0], nd[0], bp, bx),
                        patch_inter_step(0, pd[1], nd[1], bp, bx),
                        patch_inter_step(0, pd[2], nd[2], bp, bx),
                    )
                states.append((gtype, delta))
            self._states = states + [(0, (0, 0, 0))] * (len(self.body.groups) - n)
            return False
        # keyframe complete: commit and advance
        self._states = list(
            zip(keyframe.group_types[:n], keyframe.group_deltas[:n])
        ) + [(0, (0, 0, 0))] * (len(self.body.groups) - n)
        self.prev_frame = keyframe
        self.start_tick = tick
        self.frame = (self.frame + 1) % self.anim.num_frames
        return self.frame == 0
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_anim_player.py -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add maitd/anim.py tests/test_anim_player.py
git commit -m "feat: animation state machine with keyframe interpolation"
```

---

### Task 7: Mask rasterization

**Files:**
- Create: `maitd/mask.py`
- Test: `tests/test_mask.py`

**Interfaces:**
- Consumes: camera raw bytes (via `Pak`), `data_dir` fixture.
- Produces:
  - `@dataclass Mask: x1: int, y1: int, x2: int, y2: int, bitmap: numpy.ndarray` — bitmap is (200, 320) uint8 (0 = visible, 255 = occluded), coordinates relative to bitmap
  - `def fill_poly(points: list[tuple[int, int]], target: numpy.ndarray, value: int)` — FITD polys.cpp `fillpoly` port (scanline edge-dot fill); points = flat s16 pairs
  - `def create_aitd1_mask(camera_raw: bytes, camera_off: int) -> list[Mask]` — FITD `createAITD1Mask` port: per viewed room, per mask zone: skip 2-byte numMask, then `num_mask_zone = u16`, polygon list at `camera_off + u16(+2)`; per poly: `num_points u16` then s16 pairs → fill_poly; track min/max bounds; returns one Mask per (room, zone)

- [ ] **Step 1: Write failing tests** `tests/test_mask.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
import numpy as np

from maitd.mask import fill_poly


def test_fill_triangle():
    target = np.zeros((10, 10), dtype=np.uint8)
    fill_poly([(2, 2), (7, 2), (2, 7)], target, 255)
    assert target[2, 3] == 255
    assert target[2, 1] == 0
    assert target[3, 3] == 255
    assert target[1, 3] == 0


def test_fill_square_rows():
    target = np.zeros((10, 10), dtype=np.uint8)
    fill_poly([(1, 1), (4, 1), (4, 4), (1, 4)], target, 255)
    assert target[2, 1] == 255
    assert target[2, 4] == 255
    assert target[2, 0] == 0
    assert target[2, 5] == 0
    assert target[0, 2] == 0
    assert target[5, 2] == 0
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/pytest tests/test_mask.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'maitd.mask'`.

- [ ] **Step 3: Implement** `maitd/mask.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Mask rasterization port of FITD polys.cpp fillpoly + main.cpp createAITD1Mask."""
import struct
from dataclasses import dataclass

import numpy as np

SCREEN_W, SCREEN_H = 320, 200


@dataclass
class Mask:
    x1: int
    y1: int
    x2: int
    y2: int
    bitmap: np.ndarray  # (200, 320) uint8, 255 = occluded


def fill_poly(points, target, value):
    # scanline edge-dot fill (FITD fillpoly): collect edge crossings per row,
    # sort, fill pairs. Horizontal edges contribute their endpoints.
    h, w = target.shape
    dots = [[] for _ in range(h)]
    n = len(points)
    if n <= 1:
        return
    x2, y2 = points[-1]
    for i in range(n):
        x1, y1 = x2, y2
        x2, y2 = points[i]
        if y1 == y2:
            continue
        step = (x2 - x1) / (y2 - y1)
        curx = x1
        if y1 < y2:
            for j in range(y1, y2):
                if 0 <= j < h:
                    dots[j].append(int(curx + 0.5))
                curx += step
        else:
            for j in range(y1, y2, -1):
                if 0 <= j < h:
                    dots[j].append(int(curx + 0.5))
                curx -= step
    # closing-edge endpoint (FITD adds it under direction conditions; union-fill
    # of polygon masks only needs even-pair fill, endpoints already covered)
    for y in range(h):
        row = sorted(dots[y])
        for j in range(0, len(row) - 1, 2):
            x_a, x_b = row[j], row[j + 1]
            x_a = max(0, min(w - 1, x_a))
            x_b = max(0, min(w - 1, x_b))
            if x_a <= x_b:
                target[y, x_a : x_b + 1] = value


def _s16(buf, off):
    v = struct.unpack_from("<H", buf, off)[0]
    return v - 0x10000 if v & 0x8000 else v


def create_aitd1_mask(camera_raw, camera_off):
    masks = []
    num_viewed = struct.unpack_from("<H", camera_raw, camera_off + 0x12)[0]
    for viewed in range(num_viewed):
        vr_off = camera_off + 0x14 + viewed * 0x0C
        data2 = camera_raw[camera_off + struct.unpack_from("<H", camera_raw, vr_off + 2)[0] :]
        base = camera_off + struct.unpack_from("<H", camera_raw, vr_off + 2)[0]
        num_mask = struct.unpack_from("<h", data2, 0)[0]
        data = 2  # skip numMask
        for _ in range(num_mask):
            num_zones = struct.unpack_from("<H", data2, data)[0]
            # FITD: src = data2 + u16(data+2) — the offset value is relative to data2
            poly_off = struct.unpack_from("<H", data2, data + 2)[0]
            src = camera_raw[base + poly_off :]
            num_polys = struct.unpack_from("<H", src, 0)[0]
            off = 2
            min_x, max_x, min_y, max_y = 319, 0, 199, 0
            bitmap = np.zeros((SCREEN_H, SCREEN_W), dtype=np.uint8)
            for _ in range(num_polys):
                num_points = struct.unpack_from("<H", src, off)[0]
                off += 2
                points = [
                    (_s16(src, off + k * 4), _s16(src, off + k * 4 + 2))
                    for k in range(num_points)
                ]
                off += num_points * 4
                fill_poly(points, bitmap, 255)
                for px, py in points:
                    min_x, max_x = min(min_x, px), max(max_x, px)
                    min_y, max_y = min(min_y, py), max(max_y, py)
            masks.append(Mask(min_x, min_y, max_x, max_y, bitmap))
            # advance to next mask zone header: skip overlay rects (unused in AITD1)
            data += 2 + ((num_zones * 4 + 1) * 2)
    return masks
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_mask.py -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add maitd/mask.py tests/test_mask.py
git commit -m "feat: mask rasterization (fillpoly + createAITD1Mask ports)"
```

---

### Task 8: Cover zones and camera switching

**Files:**
- Modify: `maitd/formats.py` (append `parse_cover_zones`)
- Modify: `maitd/world.py` (append zone + camera-selection functions)
- Test: `tests/test_camera_switch.py`

**Interfaces:**
- Consumes: camera raw bytes, `CameraState` (task 4), camera dataclasses (M1).
- Produces:
  - `def parse_cover_zones(camera_raw: bytes, camera_off: int, viewed_idx: int) -> list[list[tuple[int, int]]]` in `maitd/formats.py` — s16 polygons for a viewed room's cover zones
  - `def test_cross_product(x1, z1, x2, z2, x3, z3, x4, z4) -> bool` in `maitd/world.py`
  - `def is_in_poly(x1: int, x2: int, z1: int, z2: int, zones: list[list[tuple[int, int]]]) -> bool` in `maitd/world.py` — actor box center ray-cast per FITD
  - `def find_best_camera(actor_x1, actor_x2, actor_z1, actor_z2, actor_beta, room_cameras: list[Camera], zones_by_camera: list[list[list[tuple[int, int]]]]) -> int` in `maitd/world.py` — returns camera slot index or -1

- [ ] **Step 1: Write failing tests** `tests/test_camera_switch.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
import struct

from maitd.formats import parse_cover_zones
from maitd.pak import Pak
from maitd.world import find_best_camera, is_in_poly


def test_cover_zones_real_data(data_dir):
    cam_raw = Pak(data_dir / "ETAGE00.PAK").read(1)
    zones = parse_cover_zones(cam_raw, 1300, 0)  # camera 2, viewed room 0
    assert len(zones) == 1
    assert zones[0][0] == (-742, 207)
    assert zones[0][-1] == (-655, 18)


def test_spawn_in_camera2_zone(data_dir):
    cam_raw = Pak(data_dir / "ETAGE00.PAK").read(1)
    zones = parse_cover_zones(cam_raw, 1300, 0)
    # spawn point is the zone centroid
    assert is_in_poly(-364, -364, 198, 198, zones)


def test_spawn_outside_camera0_zone(data_dir):
    cam_raw = Pak(data_dir / "ETAGE00.PAK").read(1)
    zones = parse_cover_zones(cam_raw, 24, 0)
    assert not is_in_poly(-364, -364, 198, 198, zones)


def test_synthetic_zone_contains_point():
    square = [[(0, 0), (100, 0), (100, 100), (0, 100)]]
    assert is_in_poly(50, 50, 50, 50, square)
    assert not is_in_poly(150, 150, 50, 50, square)


def test_find_best_camera_real_data(data_dir):
    from maitd.formats import parse_cameras
    cam_raw = Pak(data_dir / "ETAGE00.PAK").read(1)
    cameras = parse_cameras(cam_raw)
    zones_by_camera = [parse_cover_zones(cam_raw, off, 0) for off in (24, 858, 1300, 2240, 2834)]
    best = find_best_camera(-364, -364, 198, 198, 0, cameras, zones_by_camera)
    assert best == 2
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/pytest tests/test_camera_switch.py -q`
Expected: FAIL, `ImportError: cannot import name 'parse_cover_zones'`.

- [ ] **Step 3: Append to `maitd/formats.py`**

```python
def parse_cover_zones(camera_raw, camera_off, viewed_idx):
    vr_off = camera_off + 0x14 + viewed_idx * 0x0C
    cover_off = camera_off + _u16(camera_raw, vr_off + 4)
    num_zones = _u16(camera_raw, cover_off)
    p = cover_off + 2
    zones = []
    for _ in range(num_zones):
        num_points = _u16(camera_raw, p)
        p += 2
        points = [(_s16(camera_raw, p + 4 * k), _s16(camera_raw, p + 4 * k + 2)) for k in range(num_points)]
        p += num_points * 4
        zones.append(points)
    return zones
```

- [ ] **Step 4: Append to `maitd/world.py`**

```python
def test_cross_product(x1, z1, x2, z2, x3, z3, x4, z4):
    x_ab = x1 - x2
    z_ab = z1 - z2
    x_cd = x3 - x4
    z_cd = z3 - z4
    x_ac = x1 - x3
    z_ac = z1 - z3
    dot = (x_ab * z_cd) - (x_cd * z_ac)
    if dot == 0:
        return False
    dda = x_ac * z_cd - x_cd * z_ac
    dmu = -x_ab * z_ac + x_ac * z_ab
    if dot < 0:
        dot = -dot
        dda = -dda
        dmu = -dmu
    return dda >= 0 and dmu >= 0 and dot >= dda and dot >= dmu


def is_in_poly(x1, x2, z1, z2, zones):
    x_mid = (x1 + x2) // 2
    z_mid = (z1 + z2) // 2
    for poly in zones:
        flag = 0
        for j in range(len(poly)):
            zx1, zz1 = poly[j]
            zx2, zz2 = poly[(j + 1) % len(poly)]
            if test_cross_product(x_mid, z_mid, x_mid - 10000, z_mid, zx1, zz1, zx2, zz2):
                flag |= 1
            if test_cross_product(x_mid, z_mid, x_mid + 10000, z_mid, zx1, zz1, zx2, zz2):
                flag |= 2
        if flag == 3:
            return True
    return False


def find_best_camera(actor_x1, actor_x2, actor_z1, actor_z2, actor_beta, room_cameras, zones_by_camera):
    found_angle = 32000
    found_camera = -1
    for i, cam in enumerate(room_cameras):
        if is_in_poly(actor_x1, actor_x2, actor_z1, actor_z2, zones_by_camera[i]):
            new_angle = actor_beta + ((cam.beta + 0x200) & 0x3FF)
            if new_angle < 0:
                new_angle = -new_angle
            if new_angle < found_angle:
                found_angle = new_angle
                found_camera = i
    return found_camera
```

- [ ] **Step 5: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_camera_switch.py -q`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add maitd/formats.py maitd/world.py tests/test_camera_switch.py
git commit -m "feat: cover zones, is_in_poly, find_best_camera"
```

---

### Task 9: Actor state, movement, collision

**Files:**
- Create: `maitd/actors.py`
- Test: `tests/test_actors.py`

**Interfaces:**
- Consumes: `Assets` (task 3), `Floor` (M1), `rotate_step` (task 4), `Body` (task 2).
- Produces:
  - `@dataclass Actor: body_idx: int, anim_idx: int, x: int, y: int, z: int, beta: int, room_idx: int, tick: int`
  - `def spawn_player(assets: Assets, floor: Floor) -> Actor` — body 12, anim 2, world (-3642, 0, 1977), beta 0, room 0
  - `def actor_zv(actor: Actor, body: Body) -> tuple[int, ...]` — body zv + (x, y, z)
  - `def player_step(actor: Actor, body: Body, joyd: int, hard_cols: list[Zone], speed: int = 60) -> None` — tank movement: up=1/down=2 move along beta (stepZ = ±speed, forward direction resolved empirically — negative Z is forward, see note), left=4/right=8 rotate beta ∓0x80 per tick; collision resolution via `gere_collision`
  - `def gere_collision(old_zv, animated_zv, fix_zv) -> tuple[int, int]` — FITD GereCollision port, returns (step_x, step_z)
  - `def cube_intersect(zv1, zv2) -> bool`
  - `def check_hard_col(zv, hard_cols) -> list[Zone]` — FITD AsmCheckListCol port

Movement forward-direction note: FITD `walkStep(0, animStepZ, beta)` with `rotate_step(beta, 0, step_z)` — anim 2's step is (0, 0, -129), so forward = negative Z in actor space. If the model visually walks backward, negate `speed` in `spawn_player` (one-line empirical fix, decided at smoke test in task 11).

- [ ] **Step 1: Write failing tests** `tests/test_actors.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
from maitd.actors import actor_zv, check_hard_col, cube_intersect, gere_collision, spawn_player
from maitd.assets import Assets


def test_spawn_player(data_dir):
    assets = Assets(data_dir)
    floor = None  # Floor(data_dir, 0) — import if needed
    from maitd.floor import Floor
    actor = spawn_player(assets, Floor(data_dir, 0))
    assert (actor.x, actor.y, actor.z) == (-3642, 0, 1977)
    assert actor.beta == 0
    assert actor.body_idx == 12
    assert actor.anim_idx == 2


def test_actor_zv(data_dir):
    from maitd.floor import Floor
    assets = Assets(data_dir)
    actor = spawn_player(assets, Floor(data_dir, 0))
    zv = actor_zv(actor, assets.body(12))
    assert len(zv) == 6
    assert zv[0] <= zv[1] and zv[4] <= zv[5]


def test_cube_intersect():
    a = (0, 10, 0, 10, 0, 10)
    assert cube_intersect(a, (5, 15, 5, 15, 5, 15))
    assert not cube_intersect(a, (11, 20, 5, 15, 5, 15))


def test_check_hard_col():
    from maitd.formats import Zone
    cols = [Zone(0, 10, 0, 100, 0, 10, 0, 0), Zone(50, 60, 0, 100, 0, 10, 0, 0)]
    assert len(check_hard_col((0, 10, 0, 10, 0, 10), cols)) == 1


def test_gere_collision_side_push():
    # old box left of wall; step pushes right into it -> x blocked, z kept
    old = (0, 20, 0, 20, 0, 20)
    animated = (10, 30, 0, 20, 0, 20)
    wall = (30, 40, 0, 100, 0, 40)
    sx, sz = gere_collision(old, animated, wall, 10, 10)
    assert sx == 0 and sz == 10  # step preserved on z, cancelled on x
```

- [ ] **Step 2: Run tests, verify fail**

Run: `.venv/bin/pytest tests/test_actors.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'maitd.actors'`.

- [ ] **Step 3: Implement** `maitd/actors.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Actor state, tank movement, and hard-col collision (FITD ports)."""
from dataclasses import dataclass

from maitd.world import rotate_step

PLAYER_BODY = 12
PLAYER_ANIM = 2
SPAWN_POS = (-3642, 0, 1977)


@dataclass
class Actor:
    body_idx: int
    anim_idx: int
    x: int
    y: int
    z: int
    beta: int
    room_idx: int
    tick: int = 0


def spawn_player(assets, floor):
    return Actor(PLAYER_BODY, PLAYER_ANIM, SPAWN_POS[0], SPAWN_POS[1], SPAWN_POS[2], 0, 0)


def actor_zv(actor, body):
    bx = body.zv
    return (
        bx[0] + actor.x, bx[1] + actor.x,
        bx[2] + actor.y, bx[3] + actor.y,
        bx[4] + actor.z, bx[5] + actor.z,
    )


def cube_intersect(zv1, zv2):
    return not (
        zv1[0] >= zv2[1] or zv2[0] >= zv1[1]
        or zv1[2] >= zv2[3] or zv2[2] >= zv1[3]
        or zv1[4] >= zv2[5] or zv2[4] >= zv1[5]
    )


def check_hard_col(zv, hard_cols):
    out = []
    for col in hard_cols:
        f = (col.x1, col.x2, col.y1, col.y2, col.z1, col.z2)
        if (
            f[0] < zv[1] and zv[0] < f[1]
            and f[2] < zv[3] and zv[2] < f[3]
            and f[4] < zv[5] and zv[4] < f[5]
        ):
            out.append(col)
    return out


def _glisser(flag, step_x, step_z):
    if flag in (1, 2):
        step_z = 0
    elif flag in (4, 8):
        step_x = 0
    return step_x, step_z


def gere_collision(old_zv, animated_zv, fix_zv, step_x, step_z):
    # FITD GereCollision port: zeroes out the attempted step components that
    # would push the actor through fix_zv
    if old_zv[1] > fix_zv[0]:
        oldpos = 8 if fix_zv[1] <= old_zv[0] else 0
    else:
        oldpos = 4
    if old_zv[5] > fix_zv[4]:
        oldpos |= 2 if old_zv[4] >= fix_zv[5] else 0
    else:
        oldpos |= 1

    if oldpos in (5, 9, 6, 10):
        oldtype = 2
    elif oldpos == 0:
        return (step_x, step_z)  # actor was already inside: no adjustment
    else:
        oldtype = 1

    half_x = (animated_zv[0] + animated_zv[1]) // 2
    half_z = (animated_zv[4] + animated_zv[5]) // 2
    pos = 4 if fix_zv[0] > half_x else (0 if fix_zv[1] < half_x else 8)
    pos |= 1 if fix_zv[4] > half_z else (0 if fix_zv[5] < half_z else 2)

    if pos in (5, 9, 6, 10):
        type_ = 2
    elif pos == 0:
        type_ = 0
    else:
        type_ = 1

    if oldtype == 1:
        step_x, step_z = _glisser(oldpos, step_x, step_z)
    elif type_ == 1 and (pos & oldpos):
        step_x, step_z = _glisser(pos, step_x, step_z)
    else:
        if (pos == oldpos) or (pos + oldpos == 15):
            x_mod = abs(animated_zv[0] - old_zv[0])
            z_mod = abs(animated_zv[4] - old_zv[4])
            if x_mod > z_mod:
                step_z = 0
            else:
                step_x = 0
        elif type_ == 0 or (type_ == 1 and (pos & oldpos) == 0):
            step_x = 0
            step_z = 0
        else:
            step_x, step_z = _glisser(oldpos & pos, step_x, step_z)
    return (step_x, step_z)


def player_step(actor, body, joyd, hard_cols, speed=60):
    old = actor_zv(actor, body)
    if joyd & 4:
        actor.beta = (actor.beta - 0x80) & 0x3FF
    if joyd & 8:
        actor.beta = (actor.beta + 0x80) & 0x3FF
    step_z = 0
    if joyd & 1:
        step_z = -speed  # forward = negative Z (anim step convention)
    elif joyd & 2:
        step_z = speed
    if step_z:
        # walkStep(0, step_z, beta): dx = cos(beta)*step_z, dz = -sin(beta)*step_z
        step_x, step_z = rotate_step(actor.beta, 0, step_z)
        animated = (
            old[0] + step_x, old[1] + step_x, old[2], old[3],
            old[4] + step_z, old[5] + step_z,
        )
        for col in check_hard_col(animated, hard_cols):
            fix = (col.x1, col.x2, col.y1, col.y2, col.z1, col.z2)
            step_x, step_z = gere_collision(old, animated, fix, step_x, step_z)
            animated = (
                old[0] + step_x, old[1] + step_x, old[2], old[3],
                old[4] + step_z, old[5] + step_z,
            )
        actor.x += step_x
        actor.z += step_z
    actor.tick += 1
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/pytest tests/test_actors.py -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add maitd/actors.py tests/test_actors.py
git commit -m "feat: actor state, tank movement, hard-col collision"
```

---

### Task 10: GL actor rendering and composite

**Files:**
- Modify: `maitd/render.py`
- Test: none (GL paths are manual-smoke; `fit_quad` tests unchanged)

**Interfaces:**
- Consumes: `RenderResult` (task 5), `Mask` list (task 7), M1 `Renderer`.
- Produces (extends `Renderer`):
  - `.present_scene(background: numpy.ndarray (200,320,3), actor_results: list[RenderResult], masks: list[Mask], palette: numpy.ndarray (256,3))` — composites background + actors-with-mask into the upscaled window
  - Internal: 320x200 RGBA FBO; per RenderResult draw primitives in order — type 1 poly (GL_TRIANGLE_FAN), type 0 line (GL_LINES), types 2/6/7 point (GL_POINTS, size 1/2/1), type 3 sphere (screen-space circle via triangle fan, radius `size * focal2 / depth`); color = palette[prim.color]; no depth test; then mask application: for each Mask, zero the alpha inside its rect where bitmap==255; composite actor layer over background; upload to M1 quad and flip.

- [ ] **Step 1: Extend `maitd/render.py`**

Add after the `Renderer` class definition:

```python
# ---- actor layer (M2) ----

_ACTOR_VSH = """
#version 330
in vec2 in_pos;
in vec3 in_color;
out vec3 v_color;
void main() {
    gl_Position = vec4(in_pos, 0.0, 1.0);
    v_color = in_color;
}
"""

_ACTOR_FSH = """
#version 330
in vec3 v_color;
out vec4 f_color;
void main() {
    f_color = vec4(v_color, 1.0);
}
"""


def _ndc(x, y):
    # 320x200 screen space -> NDC for the actor FBO (y flipped)
    return (x / 320.0 * 2.0 - 1.0, 1.0 - y / 200.0 * 2.0)


class _ActorLayer:
    def __init__(self, ctx, palette):
        self._ctx = ctx
        self._prog = ctx.program(vertex_shader=_ACTOR_VSH, fragment_shader=_ACTOR_FSH)
        self._tex = ctx.texture((320, 200), 4)
        self._fbo = ctx.framebuffer(color_attachments=[self._tex])
        self._palette = palette

    def draw(self, results):
        self._fbo.use()
        self._fbo.clear(0.0, 0.0, 0.0, 0.0)
        for result in results:
            for prim in result.primitives:
                color = self._palette[prim.color].astype("f4") / 255.0
                verts = []
                mode = moderngl.TRIANGLES
                if prim.type == 1:  # poly -> triangle fan
                    for i in range(1, len(prim.points) - 1):
                        verts += self._vertex(prim.points[0], color)
                        verts += self._vertex(prim.points[i], color)
                        verts += self._vertex(prim.points[i + 1], color)
                elif prim.type == 0:  # line
                    mode = moderngl.LINES
                    for p in prim.points:
                        verts += self._vertex(p, color)
                elif prim.type == 3:  # sphere: 8-gon fan around center, radius size
                    cx, cy = prim.points[0][0], prim.points[0][1]
                    r = prim.size
                    import math
                    for k in range(8):
                        a0 = k * math.pi / 4
                        a1 = (k + 1) * math.pi / 4
                        verts += self._vertex((cx, cy), color)
                        verts += self._vertex((cx + r * math.cos(a0), cy + r * math.sin(a0)), color)
                        verts += self._vertex((cx + r * math.cos(a1), cy + r * math.sin(a1)), color)
                else:  # point / big point / zixel: 1-2 px quads
                    for p in prim.points:
                        s = 1.0 if prim.type == 2 else 2.0
                        verts += self._point_quad(p, s, color)
                if verts:
                    buf = self._ctx.buffer(np.array(verts, dtype="f4").tobytes())
                    vao = self._ctx.vertex_array(self._prog, [(buf, "2f 3f", "in_pos", "in_color")])
                    vao.render(mode)
                    buf.release()
                    vao.release()

    @staticmethod
    def _vertex(p, color):
        x, y = _ndc(p[0], p[1])
        return [x, y, color[0], color[1], color[2]]

    def _point_quad(self, p, size, color):
        x, y = p[0], p[1]
        out = []
        for dx, dy in ((0, 0), (size, 0), (size, size), (0, 0), (size, size), (0, size)):
            nx, ny = _ndc(x + dx, y + dy)
            out += [nx, ny, color[0], color[1], color[2]]
        return out
```

- [ ] **Step 2: Add composite method to `Renderer`**

```python
    def present_scene(self, background, actor_results, masks, palette):
        if not hasattr(self, "_actor_layer"):
            self._actor_layer = _ActorLayer(self._ctx, palette)
        self._actor_layer.draw(actor_results)
        rgba = np.zeros((200, 320, 4), dtype=np.uint8)
        rgba[:, :, :3] = background
        rgba[:, :, 3] = 255
        layer = np.frombuffer(self._actor_layer._tex.read(), dtype=np.uint8).reshape(200, 320, 4)
        # mask: occlude actor pixels inside mask rects where the mask bit is set
        for mask in masks:
            x1, y1, x2, y2 = max(mask.x1, 0), max(mask.y1, 0), min(mask.x2, 319), min(mask.y2, 199)
            region = mask.bitmap[y1 : y2 + 1, x1 : x2 + 1]
            layer[y1 : y2 + 1, x1 : x2 + 1][region == 255] = 0
        alpha = layer[:, :, 3:4].astype("f4") / 255.0
        composite = (layer[:, :, :3].astype("f4") * alpha + rgba[:, :, :3].astype("f4") * (1.0 - alpha)).astype(np.uint8)
        self.present(composite)
```

- [ ] **Step 3: Run full suite to confirm no regression**

Run: `.venv/bin/pytest -q`
Expected: all tests pass (68 total).

- [ ] **Step 4: Commit**

```bash
git add maitd/render.py
git commit -m "feat: GL actor layer with mask composite"
```

---

### Task 11: Play loop integration

**Files:**
- Modify: `maitd/formats.py` (extract `camera_offsets`)
- Modify: `maitd/floor.py` (expose `camera_raw`, `camera_data_offsets`)
- Modify: `maitd/__main__.py` (rewrite as play loop)
- Test: none (manual smoke; loop logic visually verified)

**Interfaces:**
- Consumes: `Assets` (task 3), `Floor` (M1), `CameraState`, `find_best_camera`, `is_in_poly` (tasks 4, 8), `AnimPlayer` (task 6), `skin` (task 5), `spawn_player`, `player_step`, `actor_zv` (task 9), `create_aitd1_mask` (task 7), `parse_cover_zones` (task 8), `Renderer.present_scene` (task 10).
- Produces:
  - `def camera_offsets(raw: bytes) -> list[int]` in `maitd/formats.py` (extracted from `parse_cameras`' scan; `parse_cameras` refactored to call it — existing tests must stay green)
  - `Floor.camera_raw: bytes` and `Floor.camera_data_offsets: list[int]` (set in `__init__` from `ETAGE{number:02d}.PAK` entry 1)

- [ ] **Step 1: Extract `camera_offsets` in `maitd/formats.py`**

Replace the offset-scan block inside `parse_cameras`:

```python
    num_slots = _u32(raw, 0) // 4
    offsets = []
    highest = 0
    for i in range(num_slots):
        off = _u32(raw, i * 4)
        # stop at non-increasing offsets or offsets past the buffer (the table
        # can hold junk slots beyond the valid cameras — floor 0 has one)
        if off <= highest or off >= len(raw):
            break
        highest = off
        offsets.append(off)
```

with a call to the new function, and add it above `parse_cameras`:

```python
def camera_offsets(raw):
    num_slots = _u32(raw, 0) // 4
    offsets = []
    highest = 0
    for i in range(num_slots):
        off = _u32(raw, i * 4)
        # stop at non-increasing offsets or offsets past the buffer (the table
        # can hold junk slots beyond the valid cameras — floor 0 has one)
        if off <= highest or off >= len(raw):
            break
        highest = off
        offsets.append(off)
    return offsets
```

`parse_cameras` becomes:

```python
def parse_cameras(raw):
    cameras = []
    for off in camera_offsets(raw):
        ...  # unchanged body from M1
```

Run `.venv/bin/pytest tests/test_formats.py tests/test_camera_switch.py -q` — expect 8 passed.

- [ ] **Step 2: Extend `maitd/floor.py`**

In `Floor.__init__`, replace:

```python
        self.rooms = parse_rooms(load_entry(str(etage), 0))
        self.cameras = parse_cameras(load_entry(str(etage), 1))
```

with:

```python
        self.rooms = parse_rooms(load_entry(str(etage), 0))
        self.camera_raw = load_entry(str(etage), 1)
        self.cameras = parse_cameras(self.camera_raw)
        self.camera_data_offsets = camera_offsets(self.camera_raw)
```

and add `camera_offsets` to the imports from `maitd.formats`.

Run `.venv/bin/pytest tests/test_floor.py -q` — expect 5 passed.

- [ ] **Step 3: Rewrite `maitd/__main__.py`**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""AITD1 M2 play viewer: walk the player actor around floor rooms."""
import argparse
import pathlib
import sys

import pygame

from maitd.actors import actor_zv, player_step, spawn_player
from maitd.anim import AnimPlayer
from maitd.assets import Assets
from maitd.floor import Floor
from maitd.formats import parse_cover_zones
from maitd.mask import create_aitd1_mask
from maitd.pak import PakError
from maitd.render import Renderer
from maitd.skel import skin
from maitd.world import CameraState, find_best_camera, is_in_poly

DEFAULT_DATA = (
    pathlib.Path(__file__).resolve().parent.parent
    / "Alone in the Dark 1.app"
    / "Contents"
    / "Resources"
    / "game"
    / "INDARK"
)

TICK_MS = 20  # 50 Hz logic tick


def parse_args(argv):
    p = argparse.ArgumentParser(prog="maitd", description="AITD1 room viewer (M2: actor walk)")
    p.add_argument("--data", type=pathlib.Path, default=DEFAULT_DATA, help="game data dir")
    p.add_argument("--floor", type=int, default=0, help="floor number (default 0)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        floor = Floor(args.data, args.floor)
        assets = Assets(args.data)
    except PakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not any(r.camera_indices for r in floor.rooms):
        print("error: no room with cameras on this floor", file=sys.stderr)
        return 2

    renderer = Renderer()
    clock = pygame.time.Clock()

    actor = spawn_player(assets, floor)
    room_idx = actor.room_idx
    cam_slot = 0
    body = assets.body(actor.body_idx)
    player = AnimPlayer(body, assets.anim(actor.anim_idx), actor.tick)

    def room_zone_lists():
        # per room camera slot: cover zones for the actor's room, [] if the
        # camera does not view that room
        room = floor.rooms[room_idx]
        out = []
        for cam_idx in room.camera_indices:
            cam = floor.cameras[cam_idx]
            viewed = [vr.viewed_room_idx for vr in cam.viewed_rooms]
            if room_idx in viewed:
                vi = viewed.index(room_idx)
                off = floor.camera_data_offsets[cam_idx]
                out.append(parse_cover_zones(floor.camera_raw, off, vi))
            else:
                out.append([])
        return out

    def draw():
        room = floor.rooms[room_idx]
        cam_idx = room.camera_indices[cam_slot % len(room.camera_indices)]
        cam = floor.cameras[cam_idx]
        state = CameraState.from_camera(
            cam, room.world_x, room.world_y, room.world_z
        ).angles()
        result = skin(body, player.group_states(), (actor.x, actor.y, actor.z), state)
        masks = create_aitd1_mask(floor.camera_raw, floor.camera_data_offsets[cam_idx])
        renderer.present_scene(floor.camera_image(cam_idx), [result], masks, floor.palette)
        pygame.display.set_caption(
            f"maitd — floor {floor.number} room {room_idx} camera {cam_idx} "
            f"body {actor.body_idx} anim {actor.anim_idx}"
        )

    def logic_tick():
        nonlocal cam_slot
        joyd = 0
        keys = pygame.key.get_pressed()
        if keys[pygame.K_UP]:
            joyd |= 1
        if keys[pygame.K_DOWN]:
            joyd |= 2
        if keys[pygame.K_LEFT]:
            joyd |= 4
        if keys[pygame.K_RIGHT]:
            joyd |= 8
        player_step(actor, body, joyd, floor.rooms[room_idx].hard_cols)

        # camera switching: still inside current camera's zone?
        room = floor.rooms[room_idx]
        cam_idx = room.camera_indices[cam_slot % len(room.camera_indices)]
        zv = actor_zv(actor, body)
        x1, x2, z1, z2 = zv[0] // 10, zv[1] // 10, zv[4] // 10, zv[5] // 10
        cam = floor.cameras[cam_idx]
        viewed = [vr.viewed_room_idx for vr in cam.viewed_rooms]
        current_zones = []
        if room_idx in viewed:
            vi = viewed.index(room_idx)
            off = floor.camera_data_offsets[cam_idx]
            current_zones = parse_cover_zones(floor.camera_raw, off, vi)
        if not is_in_poly(x1, x2, z1, z2, current_zones):
            room_cameras = [floor.cameras[i] for i in room.camera_indices]
            new_slot = find_best_camera(x1, x2, z1, z2, actor.beta, room_cameras, room_zone_lists())
            if new_slot != -1:
                cam_slot = new_slot

        player.advance(actor.tick)

    draw()
    running = True
    last = pygame.time.get_ticks()
    acc = 0
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
        now = pygame.time.get_ticks()
        acc += now - last
        last = now
        while acc >= TICK_MS:
            logic_tick()
            acc -= TICK_MS
        draw()
        clock.tick(60)
    renderer.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run full suite**

Run: `.venv/bin/pytest -q`
Expected: 68 passed.

- [ ] **Step 5: Manual smoke**

Run: `.venv/bin/python -m maitd --floor 0`
Expected: window opens on floor 0; a humanoid figure visible; arrows walk (Up forward, Left/Right turn); camera switches when walking out of a camera zone; actor occluded when walking behind furniture; Esc quits. If the figure walks backward or is invisible at spawn, adjust `SPAWN_POS` / speed sign / `PLAYER_BODY` in `actors.py` constants and re-run until the figure is visible and walking plausibly; record the final values in the commit message body.

- [ ] **Step 6: Commit**

```bash
git add maitd/formats.py maitd/floor.py maitd/__main__.py
git commit -m "feat: M2 play loop (walk, camera switching, masks)"
```

---

### Task 12: Proof harness extension

**Files:**
- Modify: `scripts/prove_m1.py`
- Test: none (harness itself)

- [ ] **Step 1: Extend `scripts/prove_m1.py`**

Add after the floor loop:

```python
    from maitd.assets import Assets
    assets = Assets(data)
    for i in range(assets.num_bodies):
        body = assets.body(i)
        assert len(body.vertices) > 0
        for prim in body.primitives:
            assert all(p < len(body.vertices) for p in prim.points)
    for i in range(assets.num_anims):
        anim = assets.anim(i)
        assert anim.num_frames > 0
    print(f"OK: parsed {assets.num_bodies} bodies and {assets.num_anims} anims")
```

- [ ] **Step 2: Run proof**

Run: `.venv/bin/python scripts/prove_m1.py`
Expected: floor lines (as M1), then `OK: parsed 272 bodies and 305 anims`, exit 0.

- [ ] **Step 3: Run full suite**

Run: `.venv/bin/pytest -q`
Expected: 68 passed.

- [ ] **Step 4: Commit**

```bash
git add scripts/prove_m1.py
git commit -m "proof: parse all bodies and animations"
```

---

## M2 acceptance checklist

- [ ] `pytest -q` green (68 tests)
- [ ] `scripts/prove_m1.py` exit 0 (floors + 272 bodies + 305 anims)
- [ ] `.venv/bin/python -m maitd --floor 0` shows walking humanoid, camera switches at zones, mask occlusion visible (human-verified)
- [ ] No new dependencies

## Deferred to M3 (explicitly out of M2)

- LIFE script VM (spawns real actors, drives gameplay), other actors, tracks, falling/Y-handler, actor-actor collision, inventory, combat.
- Texture primitives (types 8-10, AITD2+), INFO_OPTIMISE path (AITD2+), INFO_TORTUE.
- Sce-zone linked-room visibility list (`InitViewedRoomList`).
