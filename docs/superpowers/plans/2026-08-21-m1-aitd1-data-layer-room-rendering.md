# M1: AITD1 Data Layer + Room Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load original AITD1 data files (PAK archives, explode/RLE compression, floor/camera formats, images/palettes) and render every camera background of every floor in a window.

**Architecture:** Pure data pipeline (`pak` → `explode` → `formats` → `floor`) feeding a ModernGL renderer hosted in a pygame-ce window. No game logic yet; a debug viewer with room/camera cycling keys is the M1 executable. Formats were reverse-engineered against FITD (`/Users/felipe.dos.santos/code/theirs/FITD`, GPLv2) and validated against the real game data shipped in the local `Alone in the Dark 1.app` bundle.

**Tech Stack:** Python 3.12 (arm64), pygame-ce, ModernGL, numpy, pytest.

## Global Constraints

- Python `>= 3.12`; target platform Apple Silicon (arm64), windowed mode only.
- Dependencies: `pygame-ce`, `moderngl`, `numpy` (runtime); `pytest` (dev). No other dependencies.
- License: GPLv2 (FITD-derived); every source file starts with an SPDX header `# SPDX-License-Identifier: GPL-2.0-only` (task 1 sets this pattern).
- Original game data is read in place, never copied into the repo. Default data dir: `Alone in the Dark 1.app/Contents/Resources/game/INDARK` relative to repo root; override via `--data` CLI or env `M_AITD_DATA`.
- Unknown compression flag / corrupt archive / out-of-range entry: raise with file name and entry index. Never silent skip.
- Tests requiring game data skip automatically when data dir absent (`pytest.skip`).
- FitD reference for format questions: `/Users/felipe.dos.santos/code/theirs/FITD/FitdLib/` (`pak.cpp`, `unpack.cpp`, `floor.cpp`, `room.cpp`, `main.cpp`, `palette.cpp`).

## PAK format facts (verified against real data — do not re-derive)

Archive layout: u32 offset table at file start. `slot[0]` = always 0, `slot[1]` = end of table (= offset of entry 0), `slot[i+1]` = offset of entry `i`. **Entry count = `slot[1]//4 - 1`** (FITD's `PAK_getNumFiles` uses `-2` and undercounts by one — do not copy that).

Entry at offset `off`:
- `u32 additionalDescriptorSize`; if nonzero, skip `additionalDescriptorSize - 4` further bytes
- pakInfo: `u32 disc_size`, `u32 uncompressed_size`, `u8 flag`, `u8 info5`, `u16 name_len`
- `name_len` filename bytes, then payload (`disc_size` bytes)

Flags: `0` = raw, `1` = PKWARE explode (params in `info5`), `4` = raw deflate (`zlib.decompressobj(-15)`). The shipped data uses flag 1 everywhere; implement 0 and 4 too (trivial).

Verified golden values (floor 0):
- `ETAGE00.PAK`: 2 entries. Entry 0 = room data, 594 bytes uncompressed, first 32 bytes hex `080000000c008700160028020000000000000500000001000200030004002100`. Entry 1 = camera data, 3072 bytes uncompressed.
- `CAMERA00.PAK`: 5 entries, each 64000 bytes (320x200 indexed pixels, no palette tail).
- `ITD_RESS.PAK`: 20 entries. Entry 3 = 768-byte VGA palette (6 bits per channel). Entry 0 = black `(0,0,0)`, entry 1 = white `(255,255,255)` after expansion.

Room data (entry 0): u32 offset table; `num_slots = u32@0 // 4`; room `i` at `raw + u32(raw + i*4)`; stop scanning when an offset exceeds buffer size. Room def (all little-endian): `u16 offset_to_hard_col`, `u16 offset_to_sce_zones`, `s16 world_x`, `s16 world_y`, `s16 world_z`, `u16 num_cameras`, then `num_cameras × u16` camera indices. Hard col table at `offset_to_hard_col`: `u16 count` then `count × 16` bytes (`6 × s16` ZV + `u16 parameter` + `u16 type`). Sce zones same layout at `offset_to_sce_zones`. Floor 0: 1 room, world (0, 0, 1280), cameras [2], 33 hard cols, invariant `22 + 2 + 33*16 == 552 == offset_to_sce_zones`.

Camera data (entry 1): u32 offset table; count = number of leading strictly-increasing offsets starting from slot 0 (values: 24, 858, 1300, 2240, 2834 for floor 0 → 5 cameras). Camera def at each offset: `alpha u16@0, beta u16@2, gamma u16@4, x u16@6, y u16@8, z u16@10, focal1 u16@12, focal2 u16@14, focal3 u16@16, num_viewed_rooms u16@18`, then AITD1 viewed-room entries of 12 bytes each: `viewed_room_idx u16, offset_to_mask u16, offset_to_cover u16, light_x u16, light_y u16, light_z u16`. Floor 0 camera 0: alpha 0, beta 256, gamma 57, x 954, y 0, z 455. Camera 2 must list room 0 in its viewed rooms.

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `maitd/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: importable package `maitd`; pytest fixture `data_dir` (`pathlib.Path`, skips test if game data absent) used by all later tests.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "maitd"
version = "0.1.0"
description = "Alone in the Dark 1 engine reimplementation (Python/pygame-ce/ModernGL)"
requires-python = ">=3.12"
dependencies = [
    "pygame-ce>=2.5",
    "moderngl>=5.10",
    "numpy>=2.0",
]

[project.optional-dependencies]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create `maitd/__init__.py`**

```python
# SPDX-License-Identifier: GPL-2.0-only
```

- [ ] **Step 3: Create `tests/__init__.py`** (empty file) and `tests/conftest.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
import os
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_DATA = REPO_ROOT / "Alone in the Dark 1.app" / "Contents" / "Resources" / "game" / "INDARK"


@pytest.fixture
def data_dir():
    path = pathlib.Path(os.environ.get("M_AITD_DATA", DEFAULT_DATA))
    if not path.is_dir():
        pytest.skip(f"game data not found at {path}")
    return path
```

- [ ] **Step 4: Append to `.gitignore`**

```
build/
dist/
*.egg-info/
```

- [ ] **Step 5: Create venv, install, run pytest**

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
```

Expected: `no tests ran` (exit code 5). That is acceptable for this task only.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml maitd tests .gitignore
git commit -m "scaffold: package, deps, pytest fixture for game data"
```

---

### Task 2: PKWARE explode decompressor

**Files:**
- Create: `maitd/explode.py`
- Test: `tests/test_explode.py`

**Interfaces:**
- Produces: `explode(src: bytes, uncompressed_size: int, flags: int) -> bytes` — used by task 3's PAK reader. Raises `ExplodeError` on corrupt streams.

Background: port of FITD `unpack.cpp` (`PAK_explode` + Huffman builder). `flags & 4` = literal tree present, `flags & 2` = 8K window (7 low distance bits) else 4K window (6 bits). Bits are read LSB-first into a bit buffer; Huffman tables are decoded via inverted-bit table lookup (`(~b) & mask`). The code below is a verified faithful translation — do not "simplify" the table construction.

- [ ] **Step 1: Write failing tests** `tests/test_explode.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
import struct

from maitd.explode import explode, ExplodeError


def _entry_payload(data, off):
    add = struct.unpack_from("<I", data, off)[0]
    p = off + 4 + (add - 4 if add else 0)
    disc, uncomp = struct.unpack_from("<II", data, p)
    flag, info5, name_len = struct.unpack_from("<BBH", data, p + 8)
    payload = data[p + 12 + name_len : p + 12 + name_len + disc]
    return disc, uncomp, flag, info5, payload


def test_explode_etage00_rooms(data_dir):
    raw = (data_dir / "ETAGE00.PAK").read_bytes()
    disc, uncomp, flag, info5, payload = _entry_payload(raw, 12)
    assert (disc, uncomp, flag, info5) == (380, 594, 1, 0)
    out = explode(payload, uncomp, info5)
    assert len(out) == 594
    assert out[:32].hex() == "080000000c008700160028020000000000000500000001000200030004002100"


def test_explode_etage00_cameras(data_dir):
    raw = (data_dir / "ETAGE00.PAK").read_bytes()
    disc, uncomp, flag, info5, payload = _entry_payload(raw, 424)
    assert (uncomp, flag) == (3072, 1)
    out = explode(payload, uncomp, info5)
    assert len(out) == 3072
    assert struct.unpack_from("<I", out, 0)[0] == 24  # camera offset table end


def test_explode_rejects_truncated_tree():
    import pytest
    with pytest.raises(ExplodeError):
        explode(b"\x00", 64, 0)
```

- [ ] **Step 2: Run tests, verify fail**

```bash
.venv/bin/pytest tests/test_explode.py -q
```

Expected: FAIL, `ModuleNotFoundError: No module named 'maitd.explode'`.

- [ ] **Step 3: Implement `maitd/explode.py`**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""PKWARE "explode" decompression (PAK compression flag 1).

Faithful translation of FITD FitdLib/unpack.cpp (GPLv2), itself based on
Mark Adler's 1992 unzip code.
"""

BMAX = 16
WSIZE = 0x8000
_MASKS = [(1 << i) - 1 for i in range(17)]
_CPLEN2 = list(range(2, 66))
_CPLEN3 = list(range(3, 67))
_EXTRA = [0] * 63 + [8]
_DIST4 = [1 + 64 * i for i in range(64)]
_DIST8 = [1 + 128 * i for i in range(64)]


class ExplodeError(ValueError):
    pass


def _get_tree(src, pos, n):
    lengths = [0] * n
    pairs = src[pos] + 1
    pos += 1
    k = 0
    while True:
        if pos >= len(src):
            raise ExplodeError("truncated tree")
        j = src[pos]
        pos += 1
        bits = (j & 0x0F) + 1
        count = ((j & 0xF0) >> 4) + 1
        if k + count > n:
            raise ExplodeError("tree overflow")
        for _ in range(count):
            lengths[k] = bits
            k += 1
        pairs -= 1
        if pairs == 0:
            break
    if k != n:
        raise ExplodeError("tree size mismatch")
    return pos, lengths


class _Entry:
    __slots__ = ("b", "e", "v")

    def __init__(self, b, e, v):
        self.b = b
        self.e = e
        self.v = v


def _huft_build(lengths, n, s, d, e, m):
    c = [0] * (BMAX + 1)
    for i in range(n):
        c[lengths[i]] += 1
    if c[0] == n:
        return None, 0
    el = lengths[256] if n > 256 else BMAX
    j = 1
    while c[j] == 0:
        j += 1
    k = j
    m = max(m, j)
    i = BMAX
    while c[i] == 0:
        i -= 1
    g = i
    m = min(m, i)
    y = 1 << j
    while j < i:
        y -= c[j]
        if y < 0:
            raise ExplodeError("more codes than bits")
        j += 1
        y <<= 1
    y -= c[i]
    if y < 0:
        raise ExplodeError("more codes than bits")
    c[i] += y

    x = [0] * (BMAX + 1)
    j = 0
    p = 1
    xp = 2
    i = g
    while i > 1:
        j += c[p]
        x[xp] = j
        p += 1
        xp += 1
        i -= 1

    v = [0] * 288
    i = 0
    while i < n:
        ln = lengths[i]
        if ln != 0:
            v[x[ln]] = i
            x[ln] += 1
        i += 1
    n = x[g]

    x[0] = 0
    i = 0
    h = -1
    lvl = [0] * (BMAX + 1)  # lvl[h+1] == C l[h]
    w = 0
    u = [None] * BMAX
    root = None
    pv = 0
    k2 = k
    while k2 <= g:
        a = c[k2]
        while a > 0:
            a -= 1
            while k2 > w + lvl[h + 1]:
                w += lvl[h + 1]
                h += 1
                z = g - w
                if z > m:
                    z = m
                j2 = k2 - w
                f = 1 << j2
                if f > a + 1:
                    f -= a + 1
                    xp = k2
                    while True:
                        j2 += 1
                        if j2 >= z:
                            break
                        f <<= 1
                        if f <= c[xp + 1]:
                            break
                        f -= c[xp + 1]
                        xp += 1
                if w + j2 > el and w < el:
                    j2 = el - w
                z = 1 << j2
                lvl[h + 1] = j2
                q = [None] * z
                u[h] = q
                if root is None:
                    root = q
                if h:
                    x[h] = i
                    jj = (i & ((1 << w) - 1)) >> (w - lvl[h])
                    u[h - 1][jj] = _Entry(lvl[h], 32 + j2, q)
            r = _Entry(k2 - w, 0, 0)
            if pv >= n:
                r.e = 99
            elif v[pv] < s:
                r.e = 32 if v[pv] < 256 else 31
                r.v = v[pv]
                pv += 1
            else:
                r.e = e[v[pv] - s]
                r.v = d[v[pv] - s]
                pv += 1
            q = u[h]
            f = 1 << (k2 - w)
            jj = i >> w
            while jj < len(q):
                q[jj] = r
                jj += f
            jj = 1 << (k2 - 1)
            while i & jj:
                i ^= jj
                jj >>= 1
            i ^= jj
            while (i & ((1 << w) - 1)) != x[h]:
                h -= 1
                w -= lvl[h + 1]
        k2 += 1
    return root, lvl[1]


def explode(src, uncompressed_size, flags):
    src = bytes(src)
    bl = 7
    bd = 8 if len(src) > 200000 else 7
    if flags & 4:
        pos, lengths = _get_tree(src, 0, 256)
        tb, _ = _huft_build(lengths, 256, 256, None, None, 9)
        pos, lengths = _get_tree(src, pos, 64)
        tl, bl = _huft_build(lengths, 64, 0, _CPLEN3, _EXTRA, bl)
    else:
        tb = None
        pos, lengths = _get_tree(src, 0, 64)
        tl, bl = _huft_build(lengths, 64, 0, _CPLEN2, _EXTRA, bl)
    pos, lengths = _get_tree(src, pos, 64)
    if flags & 2:
        bdl = 7
        td, _ = _huft_build(lengths, 64, 0, _DIST8, _EXTRA, bd)
    else:
        bdl = 6
        td, _ = _huft_build(lengths, 64, 0, _DIST4, _EXTRA, bd)

    bitbuf = 0
    nbits = 0
    spos = pos

    def need(n):
        nonlocal bitbuf, nbits, spos
        while nbits < n:
            if spos < len(src):
                bitbuf |= src[spos] << nbits
                spos += 1
            nbits += 8

    def dump(n):
        nonlocal bitbuf, nbits
        bitbuf >>= n
        nbits -= n

    def decode_huft(table, bits, mask):
        need(bits)
        t = table[(~bitbuf) & mask]
        while True:
            if t is None:
                raise ExplodeError("invalid code")
            dump(t.b)
            e2 = t.e
            if e2 <= 32:
                return e2, t.v
            if e2 == 99:
                raise ExplodeError("invalid code")
            e2 &= 31
            need(e2)
            t = t.v[(~bitbuf) & _MASKS[e2]]

    slide = bytearray(WSIZE)
    out = bytearray()
    w = 0
    unflushed = 1
    remaining = uncompressed_size
    ml = _MASKS[bl]
    md = _MASKS[bd]
    mdl = _MASKS[bdl]
    while remaining > 0:
        need(1)
        if bitbuf & 1:
            dump(1)
            remaining -= 1
            if tb is not None:
                _, val = decode_huft(tb, 9, _MASKS[9])
            else:
                need(8)
                val = bitbuf & 0xFF
                dump(8)
            slide[w] = val
            w += 1
            if w == WSIZE:
                out += slide
                w = 0
                unflushed = 0
        else:
            dump(1)
            need(bdl)
            d = bitbuf & mdl
            dump(bdl)
            _, dhi = decode_huft(td, bd, md)
            d = w - d - dhi
            e2, ln = decode_huft(tl, bl, ml)
            if e2:
                need(8)
                ln += bitbuf & 0xFF
                dump(8)
            remaining = remaining - ln if remaining > ln else 0
            n = ln
            while True:
                d &= WSIZE - 1
                chunk = WSIZE - (d if d > w else w)
                if chunk > n:
                    chunk = n
                n -= chunk
                if unflushed and w <= d:
                    for _ in range(chunk):
                        slide[w] = 0
                        w += 1
                    d += chunk
                elif w - d >= chunk:
                    slide[w : w + chunk] = slide[d : d + chunk]
                    w += chunk
                    d += chunk
                else:
                    for _ in range(chunk):
                        slide[w] = slide[d]
                        w += 1
                        d += 1
                if w == WSIZE:
                    out += slide
                    w = 0
                    unflushed = 0
                if n == 0:
                    break
    out += slide[:w]
    if len(out) != uncompressed_size:
        raise ExplodeError(f"size mismatch: got {len(out)}, want {uncompressed_size}")
    return bytes(out)
```

- [ ] **Step 4: Run tests, verify pass**

```bash
.venv/bin/pytest tests/test_explode.py -q
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add maitd/explode.py tests/test_explode.py
git commit -m "feat: PKWARE explode decompression for PAK flag 1"
```

---

### Task 3: PAK archive reader

**Files:**
- Create: `maitd/pak.py`
- Test: `tests/test_pak.py`

**Interfaces:**
- Consumes: `maitd.explode.explode(src, uncompressed_size, flags) -> bytes`
- Produces:
  - `class PakError(Exception)`
  - `class PakInfo` (dataclass: `disc_size: int`, `uncompressed_size: int`, `flag: int`, `info5: int`, `name: str`)
  - `class Pak` — `Pak(path: pathlib.Path | str)`; `.count -> int`; `.info(index: int) -> PakInfo`; `.read(index: int) -> bytes`. Raises `PakError` for missing file, bad index, unknown flag.
  - `def find_pak(data_dir: pathlib.Path, name: str) -> pathlib.Path` — returns `data_dir / f"{name}.PAK"`, raises `PakError` if absent.

- [ ] **Step 1: Write failing tests** `tests/test_pak.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
import pytest

from maitd.pak import Pak, PakError, find_pak


def test_entry_counts(data_dir):
    assert Pak(data_dir / "ETAGE00.PAK").count == 2
    assert Pak(data_dir / "CAMERA00.PAK").count == 5
    assert Pak(data_dir / "ITD_RESS.PAK").count == 20


def test_etage00_entry_info(data_dir):
    pak = Pak(data_dir / "ETAGE00.PAK")
    info = pak.info(0)
    assert (info.disc_size, info.uncompressed_size, info.flag, info.info5) == (380, 594, 1, 0)
    assert pak.info(1).uncompressed_size == 3072


def test_read_uncompressed_size_matches_header(data_dir):
    pak = Pak(data_dir / "CAMERA00.PAK")
    for i in range(pak.count):
        data = pak.read(i)
        assert len(data) == 64000


def test_out_of_range_raises(data_dir):
    pak = Pak(data_dir / "ETAGE00.PAK")
    with pytest.raises(PakError):
        pak.read(2)


def test_missing_file_raises(tmp_path):
    with pytest.raises(PakError):
        Pak(tmp_path / "NOPE.PAK")


def test_find_pak(data_dir):
    assert find_pak(data_dir, "ETAGE00").name == "ETAGE00.PAK"
    with pytest.raises(PakError):
        find_pak(data_dir, "NOPE")
```

- [ ] **Step 2: Run tests, verify fail**

```bash
.venv/bin/pytest tests/test_pak.py -q
```

Expected: FAIL, `ModuleNotFoundError: No module named 'maitd.pak'`.

- [ ] **Step 3: Implement `maitd/pak.py`**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Reader for AITD .PAK archives (offset table + per-entry compression)."""
import pathlib
import struct
import zlib
from dataclasses import dataclass

from maitd.explode import explode

FLAG_RAW = 0
FLAG_EXPLODE = 1
FLAG_DEFLATE = 4


class PakError(Exception):
    pass


@dataclass
class PakInfo:
    disc_size: int
    uncompressed_size: int
    flag: int
    info5: int
    name: str


class Pak:
    def __init__(self, path):
        self.path = pathlib.Path(path)
        if not self.path.is_file():
            raise PakError(f"PAK not found: {self.path}")
        self._data = self.path.read_bytes()
        if len(self._data) < 8:
            raise PakError(f"PAK too small: {self.path}")
        table_end = struct.unpack_from("<I", self._data, 4)[0]
        self._offsets = [
            struct.unpack_from("<I", self._data, (i + 1) * 4)[0]
            for i in range(table_end // 4 - 1)
        ]

    @property
    def count(self):
        return len(self._offsets)

    def _header(self, index):
        if not 0 <= index < self.count:
            raise PakError(f"{self.path.name}: entry {index} out of range (0..{self.count - 1})")
        off = self._offsets[index]
        data = self._data
        add = struct.unpack_from("<I", data, off)[0]
        p = off + 4 + (add - 4 if add else 0)
        disc, uncomp = struct.unpack_from("<II", data, p)
        flag, info5, name_len = struct.unpack_from("<BBH", data, p + 8)
        name = data[p + 12 : p + 12 + name_len]
        name = name[2:].decode("ascii", "replace") if name_len > 2 else ""
        payload = p + 12 + name_len
        return PakInfo(disc, uncomp, flag, info5, name), payload

    def info(self, index):
        return self._header(index)[0]

    def read(self, index):
        info, payload = self._header(index)
        data = self._data
        raw = data[payload : payload + info.disc_size]
        if len(raw) < info.disc_size:
            raise PakError(f"{self.path.name}: entry {index} truncated")
        if info.flag == FLAG_RAW:
            out = raw
        elif info.flag == FLAG_EXPLODE:
            out = explode(raw, info.uncompressed_size, info.info5)
        elif info.flag == FLAG_DEFLATE:
            out = zlib.decompressobj(-15).decompress(raw)
        else:
            raise PakError(f"{self.path.name}: entry {index} unknown flag {info.flag}")
        if len(out) != info.uncompressed_size:
            raise PakError(
                f"{self.path.name}: entry {index} size {len(out)} != {info.uncompressed_size}"
            )
        return out


def find_pak(data_dir, name):
    path = pathlib.Path(data_dir) / f"{name}.PAK"
    if not path.is_file():
        raise PakError(f"PAK not found: {path}")
    return path
```

- [ ] **Step 4: Run tests, verify pass**

```bash
.venv/bin/pytest tests/test_pak.py -q
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add maitd/pak.py tests/test_pak.py
git commit -m "feat: PAK archive reader (raw, explode, deflate)"
```

---

### Task 4: Floor/room/camera format parsers

**Files:**
- Create: `maitd/formats.py`
- Test: `tests/test_formats.py`

**Interfaces:**
- Consumes: `Pak.read` (task 3) via tests only — parsers take `bytes`.
- Produces:
  - `@dataclass Zone: x1: int, x2: int, y1: int, y2: int, z1: int, z2: int, type: int, parameter: int`
  - `@dataclass ViewedRoom: viewed_room_idx: int, offset_to_mask: int, offset_to_cover: int, light_x: int, light_y: int, light_z: int`
  - `@dataclass Room: world_x: int, world_y: int, world_z: int, camera_indices: list[int], hard_cols: list[Zone], sce_zones: list[Zone], offset_to_hard_col: int, offset_to_sce_zones: int`
  - `@dataclass Camera: alpha: int, beta: int, gamma: int, x: int, y: int, z: int, focal1: int, focal2: int, focal3: int, viewed_rooms: list[ViewedRoom]`
  - `def parse_rooms(raw: bytes) -> list[Room]`
  - `def parse_cameras(raw: bytes) -> list[Camera]`

- [ ] **Step 1: Write failing tests** `tests/test_formats.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
from maitd.formats import parse_cameras, parse_rooms
from maitd.pak import Pak


def test_floor0_rooms(data_dir):
    pak = Pak(data_dir / "ETAGE00.PAK")
    rooms = parse_rooms(pak.read(0))
    assert len(rooms) == 1
    room = rooms[0]
    assert (room.world_x, room.world_y, room.world_z) == (0, 0, 1280)
    assert room.camera_indices == [2]
    assert len(room.hard_cols) == 33
    # layout invariant: hard col block ends exactly where sce zones start
    assert room.offset_to_hard_col + 2 + len(room.hard_cols) * 16 == room.offset_to_sce_zones
    zv = room.hard_cols[0]
    assert zv.x1 <= zv.x2 and zv.y1 <= zv.y2 and zv.z1 <= zv.z2


def test_floor0_cameras(data_dir):
    pak = Pak(data_dir / "ETAGE00.PAK")
    cameras = parse_cameras(pak.read(1))
    assert len(cameras) == 5
    cam0 = cameras[0]
    assert (cam0.alpha, cam0.beta, cam0.gamma) == (0, 256, 57)
    assert (cam0.x, cam0.y, cam0.z) == (954, 0, 455)
    assert all(cam.viewed_rooms for cam in cameras)


def test_room_camera_cross_reference(data_dir):
    pak = Pak(data_dir / "ETAGE00.PAK")
    rooms = parse_rooms(pak.read(0))
    cameras = parse_cameras(pak.read(1))
    for room_idx, room in enumerate(rooms):
        for cam_idx in room.camera_indices:
            viewed = [vr.viewed_room_idx for vr in cameras[cam_idx].viewed_rooms]
            assert room_idx in viewed
```

- [ ] **Step 2: Run tests, verify fail**

```bash
.venv/bin/pytest tests/test_formats.py -q
```

Expected: FAIL, `ModuleNotFoundError: No module named 'maitd.formats'`.

- [ ] **Step 3: Implement `maitd/formats.py`**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Binary format parsers for AITD1 floor/room/camera data (AITD1 variants only)."""
import struct
from dataclasses import dataclass, field


@dataclass
class Zone:
    x1: int
    x2: int
    y1: int
    y2: int
    z1: int
    z2: int
    type: int
    parameter: int


@dataclass
class ViewedRoom:
    viewed_room_idx: int
    offset_to_mask: int
    offset_to_cover: int
    light_x: int
    light_y: int
    light_z: int


@dataclass
class Room:
    world_x: int
    world_y: int
    world_z: int
    camera_indices: list[int]
    hard_cols: list[Zone]
    sce_zones: list[Zone]
    offset_to_hard_col: int
    offset_to_sce_zones: int


@dataclass
class Camera:
    alpha: int
    beta: int
    gamma: int
    x: int
    y: int
    z: int
    focal1: int
    focal2: int
    focal3: int
    viewed_rooms: list[ViewedRoom] = field(default_factory=list)


def _u16(buf, off):
    return struct.unpack_from("<H", buf, off)[0]


def _s16(buf, off):
    return struct.unpack_from("<h", buf, off)[0]


def _u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def _parse_zones(buf, off):
    count = _u16(buf, off)
    off += 2
    zones = []
    for _ in range(count):
        zones.append(
            Zone(
                x1=_s16(buf, off),
                x2=_s16(buf, off + 2),
                y1=_s16(buf, off + 4),
                y2=_s16(buf, off + 6),
                z1=_s16(buf, off + 8),
                z2=_s16(buf, off + 10),
                parameter=_u16(buf, off + 12),
                type=_u16(buf, off + 14),
            )
        )
        off += 16
    return zones


def parse_rooms(raw):
    num_slots = _u32(raw, 0) // 4
    rooms = []
    for i in range(num_slots):
        off = _u32(raw, i * 4)
        if off > len(raw):
            break
        offset_to_hard_col = _u16(raw, off)
        offset_to_sce_zones = _u16(raw, off + 2)
        num_cameras = _u16(raw, off + 0xA)
        camera_indices = [_u16(raw, off + 0xC + 2 * j) for j in range(num_cameras)]
        rooms.append(
            Room(
                world_x=_s16(raw, off + 4),
                world_y=_s16(raw, off + 6),
                world_z=_s16(raw, off + 8),
                camera_indices=camera_indices,
                hard_cols=_parse_zones(raw, off + offset_to_hard_col),
                sce_zones=_parse_zones(raw, off + offset_to_sce_zones),
                offset_to_hard_col=offset_to_hard_col,
                offset_to_sce_zones=offset_to_sce_zones,
            )
        )
    return rooms


def parse_cameras(raw):
    num_slots = _u32(raw, 0) // 4
    offsets = []
    highest = 0
    for i in range(num_slots):
        off = _u32(raw, i * 4)
        if off <= highest:
            break
        highest = off
        offsets.append(off)
    cameras = []
    for off in offsets:
        num_viewed = _u16(raw, off + 0x12)
        cam = Camera(
            alpha=_u16(raw, off),
            beta=_u16(raw, off + 2),
            gamma=_u16(raw, off + 4),
            x=_u16(raw, off + 6),
            y=_u16(raw, off + 8),
            z=_u16(raw, off + 10),
            focal1=_u16(raw, off + 12),
            focal2=_u16(raw, off + 14),
            focal3=_u16(raw, off + 16),
        )
        p = off + 0x14
        for _ in range(num_viewed):
            cam.viewed_rooms.append(
                ViewedRoom(
                    viewed_room_idx=_u16(raw, p),
                    offset_to_mask=_u16(raw, p + 2),
                    offset_to_cover=_u16(raw, p + 4),
                    light_x=_u16(raw, p + 6),
                    light_y=_u16(raw, p + 8),
                    light_z=_u16(raw, p + 10),
                )
            )
            p += 0x0C  # AITD1 stride
        cameras.append(cam)
    return cameras
```

- [ ] **Step 4: Run tests, verify pass**

```bash
.venv/bin/pytest tests/test_formats.py -q
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add maitd/formats.py tests/test_formats.py
git commit -m "feat: room and camera format parsers (AITD1)"
```

---

### Task 5: Palette and image decoding

**Files:**
- Modify: `maitd/formats.py` (append functions)
- Test: `tests/test_image.py`

**Interfaces:**
- Consumes: `Pak.read` (task 3) via tests.
- Produces:
  - `def decode_palette(raw: bytes) -> numpy.ndarray` — input 768 bytes VGA 6-bit; returns `(256, 3)` uint8 RGB. Expansion: `(v << 2) | (v >> 4)`. Raises `ValueError` if `len(raw) != 768`.
  - `def decode_image(raw: bytes, palette: numpy.ndarray) -> numpy.ndarray` — input 64000 bytes indexed pixels; returns `(200, 320, 3)` uint8 RGB. Raises `ValueError` if `len(raw) != 64000`.

- [ ] **Step 1: Write failing tests** `tests/test_image.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
import numpy as np
import pytest

from maitd.formats import decode_image, decode_palette
from maitd.pak import Pak


def test_palette_golden_values(data_dir):
    pak = Pak(data_dir / "ITD_RESS.PAK")
    pal = decode_palette(pak.read(3))
    assert pal.shape == (256, 3)
    assert pal.dtype == np.uint8
    assert tuple(pal[0]) == (0, 0, 0)
    assert tuple(pal[1]) == (255, 255, 255)


def test_palette_vga_expansion():
    raw = bytes([63, 0, 0] + [0] * (768 - 3))
    pal = decode_palette(raw)
    assert tuple(pal[0]) == (255, 0, 0)
    raw = bytes([1, 0, 0] + [0] * (768 - 3))
    assert tuple(decode_palette(raw)[0]) == (4, 0, 0)  # (1<<2)|(1>>4)


def test_palette_rejects_bad_size():
    with pytest.raises(ValueError):
        decode_palette(b"\x00" * 767)


def test_camera_image_decode(data_dir):
    pal = decode_palette(Pak(data_dir / "ITD_RESS.PAK").read(3))
    img_raw = Pak(data_dir / "CAMERA00.PAK").read(0)
    img = decode_image(img_raw, pal)
    assert img.shape == (200, 320, 3)
    first_index = img_raw[0]
    assert tuple(img[0, 0]) == tuple(pal[first_index])
    # every pixel must equal its palette lookup
    indices = np.frombuffer(img_raw, dtype=np.uint8).reshape(200, 320)
    assert (img == pal[indices]).all()


def test_image_rejects_bad_size():
    pal = np.zeros((256, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        decode_image(b"\x00" * 100, pal)
```

- [ ] **Step 2: Run tests, verify fail**

```bash
.venv/bin/pytest tests/test_image.py -q
```

Expected: FAIL, `ImportError: cannot import name 'decode_palette'`.

- [ ] **Step 3: Append to `maitd/formats.py`**

```python
import numpy as np


def decode_palette(raw):
    if len(raw) != 768:
        raise ValueError(f"palette must be 768 bytes, got {len(raw)}")
    v = np.frombuffer(raw, dtype=np.uint8).astype(np.uint16)
    return ((v << 2) | (v >> 4)).astype(np.uint8).reshape(256, 3)


def decode_image(raw, palette):
    if len(raw) != 64000:
        raise ValueError(f"image must be 64000 bytes, got {len(raw)}")
    indices = np.frombuffer(raw, dtype=np.uint8).reshape(200, 320)
    return palette[indices]
```

(Move the `numpy` import to the top of the file with the other imports when appending.)

- [ ] **Step 4: Run tests, verify pass**

```bash
.venv/bin/pytest tests/test_image.py -q
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add maitd/formats.py tests/test_image.py
git commit -m "feat: VGA palette and 320x200 image decoding"
```

---

### Task 6: Floor loader with LRU cache

**Files:**
- Create: `maitd/floor.py`
- Test: `tests/test_floor.py`

**Interfaces:**
- Consumes: `Pak`, `find_pak`, `PakError` (task 3); `parse_rooms`, `parse_cameras`, `decode_palette`, `decode_image` (tasks 4-5).
- Produces:
  - `class Floor` — `Floor(data_dir: pathlib.Path, number: int)`.
    - `.number: int`
    - `.rooms: list[Room]`
    - `.cameras: list[Camera]`
    - `.palette: numpy.ndarray` (256,3)
    - `.camera_image(camera_idx: int) -> numpy.ndarray` (200,320,3) RGB — raises `KeyError` if index out of range
  - Cache: one shared `functools.lru_cache(maxsize=64)`-backed module-level loader keyed by `(pak_path, index)` so repeated `camera_image` calls and cross-floor reloads do not re-decompress. Exposed for tests as `floor.load_entry(path, index) -> bytes` plus `floor.cache_clear()`.
  - File naming: rooms/cameras from `ETAGE{number:02d}.PAK` (entry 0 = rooms, 1 = cameras); images from `CAMERA{number:02d}.PAK`; palette from `ITD_RESS.PAK` entry 3.

- [ ] **Step 1: Write failing tests** `tests/test_floor.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
import numpy as np
import pytest

from maitd import floor as floormod
from maitd.floor import Floor
from maitd.pak import PakError


def test_floor0_loads(data_dir):
    f = Floor(data_dir, 0)
    assert f.number == 0
    assert len(f.rooms) == 1
    assert len(f.cameras) == 5
    assert f.palette.shape == (256, 3)


def test_camera_image(data_dir):
    f = Floor(data_dir, 0)
    img = f.camera_image(2)  # room 0's camera
    assert img.shape == (200, 320, 3)
    assert img.dtype == np.uint8


def test_camera_image_out_of_range(data_dir):
    f = Floor(data_dir, 0)
    with pytest.raises(KeyError):
        f.camera_image(99)


def test_missing_floor_raises(data_dir):
    with pytest.raises(PakError):
        Floor(data_dir, 97)


def test_cache_hits(data_dir):
    floormod.cache_clear()
    f = Floor(data_dir, 0)
    f.camera_image(0)
    info_before = floormod.load_entry.cache_info()
    f.camera_image(0)
    info_after = floormod.load_entry.cache_info()
    assert info_after.hits > info_before.hits
```

- [ ] **Step 2: Run tests, verify fail**

```bash
.venv/bin/pytest tests/test_floor.py -q
```

Expected: FAIL, `ModuleNotFoundError: No module named 'maitd.floor'`.

- [ ] **Step 3: Implement `maitd/floor.py`**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Floor loading: rooms, cameras, palette, camera background images."""
import functools

from maitd.formats import decode_image, decode_palette, parse_cameras, parse_rooms
from maitd.pak import Pak, find_pak

PALETTE_PAK = "ITD_RESS"
PALETTE_ENTRY = 3


@functools.lru_cache(maxsize=64)
def load_entry(pak_path, index):
    return Pak(pak_path).read(index)


def cache_clear():
    load_entry.cache_clear()


class Floor:
    def __init__(self, data_dir, number):
        self.number = number
        etage = find_pak(data_dir, f"ETAGE{number:02d}")
        self._images = find_pak(data_dir, f"CAMERA{number:02d}")
        self.rooms = parse_rooms(load_entry(str(etage), 0))
        self.cameras = parse_cameras(load_entry(str(etage), 1))
        palette_pak = find_pak(data_dir, PALETTE_PAK)
        self.palette = decode_palette(load_entry(str(palette_pak), PALETTE_ENTRY))
        self._num_images = Pak(self._images).count

    def camera_image(self, camera_idx):
        if not 0 <= camera_idx < self._num_images:
            raise KeyError(f"floor {self.number}: camera image {camera_idx} out of range")
        raw = load_entry(str(self._images), camera_idx)
        return decode_image(raw, self.palette)
```

- [ ] **Step 4: Run tests, verify pass**

```bash
.venv/bin/pytest tests/test_floor.py -q
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add maitd/floor.py tests/test_floor.py
git commit -m "feat: floor loader with LRU-cached PAK access"
```

---

### Task 7: ModernGL background renderer

**Files:**
- Create: `maitd/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: image arrays `(200, 320, 3)` uint8 from `Floor.camera_image` (task 6).
- Produces:
  - `class Renderer` — `Renderer(width: int = 1280, height: int = 800, title: str = "maitd")` creates a pygame-ce OPENGL window + ModernGL context; `.present(image: numpy.ndarray)` uploads/updates the texture and flips the window; `.close()`.
  - Pure helper (GL-free, unit tested): `def fit_quad(img_w: int, img_h: int, win_w: int, win_h: int) -> tuple[float, float, float, float]` returning `(x0, y0, x1, y1)` NDC coords that letterbox the image keeping aspect.

- [ ] **Step 1: Write failing tests** `tests/test_render.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
import math

from maitd.render import fit_quad


def test_fit_quad_exact_multiple():
    assert fit_quad(320, 200, 1280, 800) == (-1.0, -1.0, 1.0, 1.0)


def test_fit_quad_letterbox_wide_window():
    # height-limited: scale = min(1600/320, 800/200) = 4 -> pillarboxed horizontally
    assert fit_quad(320, 200, 1600, 800) == (-0.8, -1.0, 0.8, 1.0)
    # width-limited: scale = min(1000/320, 800/200) = 3.125
    x0, y0, x1, y1 = fit_quad(320, 200, 1000, 800)
    assert math.isclose(x1 - x0, 2.0)        # full width
    assert math.isclose(y1 - y0, 1.5625)     # 2 * 200*3.125/800


def test_fit_quad_centered():
    x0, y0, x1, y1 = fit_quad(320, 200, 1000, 800)
    assert math.isclose(x0, -x1) and math.isclose(y0, -y1)
```

- [ ] **Step 2: Run tests, verify fail**

```bash
.venv/bin/pytest tests/test_render.py -q
```

Expected: FAIL, `ModuleNotFoundError: No module named 'maitd.render'`.

- [ ] **Step 3: Implement `maitd/render.py`**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Window + ModernGL renderer for camera background images."""
import moderngl
import numpy as np
import pygame

_VSH = """
#version 330
in vec2 in_pos;
in vec2 in_uv;
out vec2 v_uv;
void main() {
    gl_Position = vec4(in_pos, 0.0, 1.0);
    v_uv = in_uv;
}
"""

_FSH = """
#version 330
uniform sampler2D tex;
in vec2 v_uv;
out vec4 f_color;
void main() {
    f_color = texture(tex, v_uv);
}
"""

IMG_W, IMG_H = 320, 200


def fit_quad(img_w, img_h, win_w, win_h):
    scale = min(win_w / img_w, win_h / img_h)
    w = img_w * scale / win_w
    h = img_h * scale / win_h
    return (-w, -h, w, h)


class Renderer:
    def __init__(self, width=1280, height=800, title="maitd"):
        pygame.init()
        pygame.display.set_caption(title)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
        pygame.display.gl_set_attribute(
            pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE
        )
        self._screen = pygame.display.set_mode((width, height), pygame.OPENGL | pygame.DOUBLEBUF)
        self._ctx = moderngl.create_context()
        self._prog = self._ctx.program(vertex_shader=_VSH, fragment_shader=_FSH)
        self._tex = self._ctx.texture((IMG_W, IMG_H), 3)
        self._tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        x0, y0, x1, y1 = fit_quad(IMG_W, IMG_H, width, height)
        # y flipped: image row 0 is the top of the screen
        verts = np.array(
            [
                x0, y0, 0.0, 1.0,
                x1, y0, 1.0, 1.0,
                x1, y1, 1.0, 0.0,
                x0, y0, 0.0, 1.0,
                x1, y1, 1.0, 0.0,
                x0, y1, 0.0, 0.0,
            ],
            dtype="f4",
        )
        self._vbo = self._ctx.buffer(verts.tobytes())
        self._vao = self._ctx.vertex_array(self._prog, [(self._vbo, "2f 2f", "in_pos", "in_uv")])

    def present(self, image):
        self._tex.write(np.ascontiguousarray(image).astype("uint8").tobytes())
        self._ctx.clear(0.0, 0.0, 0.0, 1.0)
        self._tex.use(location=0)
        self._vao.render()
        pygame.display.flip()

    def close(self):
        self._vbo.release()
        self._tex.release()
        self._prog.release()
        self._ctx.release()
        pygame.quit()
```

- [ ] **Step 4: Run tests, verify pass**

```bash
.venv/bin/pytest tests/test_render.py -q
```

Expected: 3 passed. (Renderer class itself is exercised manually in task 8/9 — GL windows cannot be asserted headless.)

- [ ] **Step 5: Commit**

```bash
git add maitd/render.py tests/test_render.py
git commit -m "feat: pygame/ModernGL background renderer"
```

---

### Task 8: Debug viewer main loop

**Files:**
- Create: `maitd/__main__.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `Floor` (task 6), `Renderer` (task 7), `PakError` (task 3).
- Produces: `def main(argv: list[str] | None = None) -> int` — CLI: `--data PATH` (default `DEFAULT_DATA` from `tests/conftest.py` semantics, i.e. repo-relative bundle path resolved from `maitd/__main__.py`), `--floor N` (default 0). Keys: Left/Right cycle cameras of current room, Up/Down cycle rooms, Escape quits. Returns process exit code (0 normal, 2 bad floor/data).

- [ ] **Step 1: Write failing tests** `tests/test_main.py`

```python
# SPDX-License-Identifier: GPL-2.0-only
from maitd.__main__ import parse_args


def test_parse_args_defaults():
    args = parse_args([])
    assert args.floor == 0
    assert args.data is not None


def test_parse_args_overrides():
    args = parse_args(["--floor", "3", "--data", "/tmp/x"])
    assert args.floor == 3
    assert args.data == "/tmp/x"
```

- [ ] **Step 2: Run tests, verify fail**

```bash
.venv/bin/pytest tests/test_main.py -q
```

Expected: FAIL, `ModuleNotFoundError: No module named 'maitd.__main__'`.

- [ ] **Step 3: Implement `maitd/__main__.py`**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Debug viewer: browse every room/camera background of a floor."""
import argparse
import pathlib
import sys

import pygame

from maitd.floor import Floor
from maitd.pak import PakError
from maitd.render import Renderer

DEFAULT_DATA = (
    pathlib.Path(__file__).resolve().parent.parent
    / "Alone in the Dark 1.app"
    / "Contents"
    / "Resources"
    / "game"
    / "INDARK"
)


def parse_args(argv):
    p = argparse.ArgumentParser(prog="maitd", description="AITD1 room viewer (M1 debug)")
    p.add_argument("--data", type=pathlib.Path, default=DEFAULT_DATA, help="game data dir")
    p.add_argument("--floor", type=int, default=0, help="floor number (default 0)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        floor = Floor(args.data, args.floor)
    except PakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    renderer = Renderer()
    clock = pygame.time.Clock()
    room_idx = 0
    cam_slot = 0

    def show():
        room = floor.rooms[room_idx]
        cam_idx = room.camera_indices[cam_slot % len(room.camera_indices)]
        renderer.present(floor.camera_image(cam_idx))
        pygame.display.set_caption(
            f"maitd — floor {floor.number} room {room_idx} camera {cam_idx}"
        )

    show()
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_RIGHT:
                    cam_slot += 1
                    show()
                elif event.key == pygame.K_LEFT:
                    cam_slot -= 1
                    show()
                elif event.key == pygame.K_UP:
                    room_idx = (room_idx + 1) % len(floor.rooms)
                    cam_slot = 0
                    show()
                elif event.key == pygame.K_DOWN:
                    room_idx = (room_idx - 1) % len(floor.rooms)
                    cam_slot = 0
                    show()
        clock.tick(60)
    renderer.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests, verify pass**

```bash
.venv/bin/pytest tests/test_main.py -q
```

Expected: 2 passed.

- [ ] **Step 5: Manual smoke run**

```bash
.venv/bin/python -m maitd --floor 0
```

Expected: window opens showing floor 0 room 0 camera 2 background (the starting studio/attic view). Left/Right/Up/Down cycle; Escape quits. Verify visually, then close.

- [ ] **Step 6: Commit**

```bash
git add maitd/__main__.py tests/test_main.py
git commit -m "feat: debug viewer main loop with room/camera cycling"
```

---

### Task 9: Full-data proof harness + README

**Files:**
- Create: `scripts/prove_m1.py`
- Create: `README.md`

**Interfaces:**
- Consumes: `Floor`, `Pak`, `pak_info` (tasks 3, 6).
- Produces: runnable proof that every floor's rooms/cameras parse and every camera background decodes to a non-blank image; prints a summary table. Exit code 0 on full pass.

- [ ] **Step 1: Implement `scripts/prove_m1.py`**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""M1 proof: walk every floor, parse rooms/cameras, decode every camera image."""
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from maitd.floor import Floor  # noqa: E402
from maitd.pak import Pak, PakError, find_pak  # noqa: E402


def main():
    data = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else (
        pathlib.Path(__file__).resolve().parent.parent
        / "Alone in the Dark 1.app"
        / "Contents"
        / "Resources"
        / "game"
        / "INDARK"
    )
    failures = 0
    for number in range(0, 20):
        try:
            find_pak(data, f"ETAGE{number:02d}")
        except PakError:
            break
        floor = Floor(data, number)
        images = Pak(find_pak(data, f"CAMERA{number:02d}"))
        bad = 0
        for cam in range(images.count):
            img = floor.camera_image(cam)
            if img.std() < 1.0:  # decoded garbage is near-uniform
                bad += 1
        print(
            f"floor {number:2d}: rooms={len(floor.rooms):2d} "
            f"cameras={len(floor.cameras):2d} images={images.count:2d} blank={bad}"
        )
        failures += bad
        if any(not r.camera_indices for r in floor.rooms):
            print(f"floor {number}: room with no cameras")
            failures += 1
    if failures:
        print(f"FAIL: {failures} problems")
        return 1
    print("OK: all floors parsed, all camera images decode non-blank")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run proof**

```bash
.venv/bin/python scripts/prove_m1.py
```

Expected: one line per floor 0..N (until ETAGE missing), final line `OK: ...`, exit code 0. If any floor reports blank images or parse errors, fix before continuing (formats tasks 2-6 own the fix).

- [ ] **Step 3: Write `README.md`**

```markdown
# maitd

Alone in the Dark 1 engine reimplementation in Python (pygame-ce + ModernGL),
driven by the original game data files. Apple Silicon, windowed.

License: GPLv2 (derived from FITD, https://github.com/yaz0r/FITD, GPLv2).
You must own the original game; this repo never ships game data.

## Setup

    python3 -m venv .venv
    .venv/bin/pip install -e ".[dev]"

Data defaults to `Alone in the Dark 1.app/Contents/Resources/game/INDARK`;
override with `--data DIR` or env `M_AITD_DATA`.

## Run (M1: room viewer)

    .venv/bin/python -m maitd --floor 0

Keys: Left/Right cycle cameras, Up/Down cycle rooms, Esc quits.

## Tests / proof

    .venv/bin/pytest -q
    .venv/bin/python scripts/prove_m1.py
```

- [ ] **Step 4: Run full test suite**

```bash
.venv/bin/pytest -q
```

Expected: all tests pass (24 total across tasks 2-8).

- [ ] **Step 5: Commit**

```bash
git add scripts/prove_m1.py README.md
git commit -m "docs+proof: M1 full-data proof harness and README"
```

---

## M1 acceptance checklist

- [ ] `pytest -q` green (data present) or green-with-skips (data absent)
- [ ] `scripts/prove_m1.py` exits 0
- [ ] `python -m maitd --floor 0` shows a recognizable AITD1 room; cycling reaches every camera of floor 0
- [ ] No new dependencies beyond pygame-ce, moderngl, numpy, pytest

## Deferred to later milestones (explicitly out of M1)

- Actors, bodies, animations (M2); LIFE script VM, inventory, combat (M3); menus, save/load, audio, video, KILLED_SORCERER alternate camera images from ITD_RESS (M4).
- Camera masks/cover zones are parsed only insofar as offsets are carried; mask decoding lands with actor occlusion in M2.
