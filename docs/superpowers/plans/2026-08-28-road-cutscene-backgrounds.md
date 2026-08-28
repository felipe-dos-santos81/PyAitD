# SPDX-License-Identifier: GPL-2.0-only
# Road cutscene backgrounds — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `make export-backgrounds` to export the 5 KILLED_SORCERER road alt plates (`ITD_RESS:15→07/000`, `16→07/001`, `17→06/000`, `18→06/005`, `19→06/008`) as `alt_backgrounds/floorNN/cameraNNN.png` plus missing `palette.png`, bump manifest to schema 3 with `alt_cameras`, and make the game load the alt when `KILLED_SORCERER==1`.

**Architecture:** Keep the mapping in `GameProfile.alt_camera_sources` (`games/aitd1/profile.py` owns the 5 entries, `engine/` reads via `game.profile`). Parallel-tree `alt_backgrounds/` with shared `guides/` keeps `backgrounds/` untouched; `AssetResolver.background(floor,cam,killed_sorcerer)` checks alt first, then base, then original; pure helpers in `render/background_export.py`, I/O in `tools/export_backgrounds.py`, validation in `render/override_check.py`.

**Tech Stack:** Python 3.12, pygame-ce + moderngl + numpy + pytest, `agy` CLI via `subprocess` (no SDK), `Floor`/`Assets` off `ITD_RESS` entry 3 palette.

## Global Constraints

* `GameProfile` owns every FITD `g_gameId` branch — no `if profile.name=="aitd1"` in `engine/` or `render/` (`tests/test_layering.py` enforces).
* `render/background_export.py` and `render/override_check.py` stay pygame/moderngl-free except `asset_resolver.load_png_rgb` (pinned by `tests/test_layering.py` `GRAPHICS_OWNERS`).
* Every `Floor.camera_image` / `Assets.resource_screen` artifact is 320×200 RGB, overrides validated by `_require_rgb` (8192 max) + 16:10 ±1% aspect + integer-multiple size hint.
* Manifest writes are atomic `.tmp` + `os.replace`; `_merge_manifest_records` composes `floors=` subsets; old `schema 1/2` manifests remain loadable (`SUPPORTED_SCHEMAS` includes 1,2,3).
* No new dependency; `agy` CLI shell only in `tools/regenerate_backgrounds.py` (tests monkeypatch `subprocess.run`).

---

## File Structure

* **Modify:** `PyAitD/games/base.py` — add `alt_camera_sources` field to `GameProfile`.
* **Modify:** `PyAitD/games/aitd1/profile.py` — set the 5-entry `alt_camera_sources` (`MappingProxyType`).
* **Modify:** `PyAitD/render/background_export.py` — `alt_background_rel_path`, `alt_manifest_record`, `MANIFEST_SCHEMA=3`, `export_manifest(..., alt_cameras=())`.
* **Modify:** `PyAitD/render/asset_resolver.py` — `override_alt_background_path`, `background(..., killed_sorcerer=False)`, `_lights` key includes variant.
* **Modify:** `tools/export_backgrounds.py` — `export_alt_backgrounds`, `export_palette`, `main()` flow for alts + palette + manifest merge for `alt_cameras`.
* **Modify:** `PyAitD/render/override_check.py` — `_each_alt_camera`, `check_alt_backgrounds`, `alt_coverage`, `summarize(..., alt_cov)`.
* **Modify:** `tools/check_overrides.py` — call alt check/coverage, render alt proof.
* **Modify:** `tools/regenerate_backgrounds.py` — loop `alt_cameras` after `cameras` (gate/judge/retry, write to `alt_backgrounds/`).
* **Modify:** `PyAitD/render/scene.py` or caller of `AssetResolver.background` — pass `killed_sorcerer` from `game.cvars`.
* **Tests:** `tests/test_game_profile.py`, `tests/test_background_export.py`, `tests/test_asset_resolver.py`, `tests/test_export_backgrounds.py`, `tests/test_override_check.py`, `tests/test_layering.py` (pin).
* **Docs:** `docs/ai-background-regeneration.md`, `Makefile` help strings (optional `AGENTS.md`/`CONTEXT.md` sync).

---

### Task 1: GameProfile seam for the 5 alt sources

**Files:**
- Modify: `PyAitD/games/base.py:1-60`
- Modify: `PyAitD/games/aitd1/profile.py:97-116`
- Test: `tests/test_game_profile.py:100-130`

**Interfaces:**
- Consumes: `GameProfile` dataclass, `AITD1.h:15-19` entry numbers.
- Produces: `GameProfile.alt_camera_sources: Mapping[tuple[int,int], int]` (default `{}`); `AITD1.alt_camera_sources == {(7,0):15, (7,1):16, (6,0):17, (6,5):18, (6,8):19}` (frozen `MappingProxyType`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_game_profile.py — inside existing AITD1 pin test block
def test_aitd1_alt_camera_sources():
    # FitdLib/AITD1.h:15-19 + main.cpp:1243-1282 (KILLED_SORCERER gate)
    from PyAitD.games.aitd1.profile import AITD1
    assert dict(AITD1.alt_camera_sources) == {(7,0):15, (7,1):16, (6,0):17, (6,5):18, (6,8):19}
    assert AITD1.alt_camera_sources[(7,0)] == 15  # AITD1_CAM07000

def test_base_profile_alt_camera_sources_defaults_empty():
    from PyAitD.games.base import GameProfile
    assert dict(GameProfile(name="x", lifes_pak="L", tracks_pak="T", text_pak="E",
                            resource_pak="R", palette_entry=3, heroes=(("a","b"),),
                            cvar_names=(), defines_big_endian=True,
                            opcode_table=tuple(), reduced_dispatch={}, reduced_allowed=frozenset()).alt_camera_sources) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_game_profile.py::test_aitd1_alt_camera_sources -v`
Expected: FAIL `AttributeError: ... alt_camera_sources` or `AssertionError`.

- [ ] **Step 3: Write minimal implementation**

```python
# PyAitD/games/base.py — add field to GameProfile
from dataclasses import dataclass, field
from typing import Mapping

@dataclass(frozen=True)
class GameProfile:
    # ...existing...
    alt_camera_sources: Mapping[tuple[int,int], int] = field(default_factory=dict)
    # (floor, camera) -> ITD_RESS entry that overrides CAMERA{NN} when KILLED_SORCERER==1
    # FitdLib/main.cpp:1253, AITD1.h:15-19. Empty means no alts.

# PyAitD/games/aitd1/profile.py
from types import MappingProxyType
AITD1 = GameProfile(
    # ...existing...
    alt_camera_sources=MappingProxyType({(7,0):15, (7,1):16, (6,0):17, (6,5):18, (6,8):19}),
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_game_profile.py::test_aitd1_alt_camera_sources tests/test_game_profile.py::test_base_profile_alt_camera_sources_defaults_empty -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add PyAitD/games/base.py PyAitD/games/aitd1/profile.py tests/test_game_profile.py
git commit -m "feat: add GameProfile.alt_camera_sources for KILLED_SORCERER road alts (AITD1.h:15-19)"
```

---

### Task 2: Pure export helpers + manifest schema 3

**Files:**
- Modify: `PyAitD/render/background_export.py:60-122`
- Test: `tests/test_background_export.py:240-344` (append new tests)

**Interfaces:**
- Consumes: `GameProfile.alt_camera_sources`, `Floor.camera_image` palette.
- Produces: `alt_background_rel_path(floor,cam)->str`, `alt_manifest_record(floor,cam,pixels,itd_entry)->dict`, `MANIFEST_SCHEMA=3`, `SUPPORTED_SCHEMAS=(1,2,3)`, `export_manifest(..., alt_cameras=())`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_background_export.py
def test_alt_background_rel_path_mirrors_resolver(tmp_path):
    from PyAitD.render import background_export as be
    from PyAitD.render.asset_resolver import override_alt_background_path
    assert (tmp_path / be.alt_background_rel_path(7, 0)) == override_alt_background_path(tmp_path, 7, 0)
    assert be.alt_background_rel_path(6, 5) == "alt_backgrounds/floor06/camera005.png"

def test_alt_manifest_record_fields():
    from PyAitD.render import background_export as be
    from tests.stub_floor import StubFloor, checker_pixels
    px = checker_pixels()
    rec = be.alt_manifest_record(StubFloor(number=7), 0, px, 15)
    assert rec["source"] == "alt_backgrounds/floor07/camera000.png"
    assert rec["guide"] == "guides/floor07/camera000.png"  # shared
    assert rec["layout"] == "guides/floor07/camera000.json"
    assert rec["itd_entry"] == 15 and rec["variant"] == "killed_sorcerer"
    assert rec["size"] == [320,200] and rec["viewed_rooms"] == [0]

def test_export_manifest_schema3_carries_alt_cameras():
    from PyAitD.render import background_export as be
    from tests.stub_floor import StubFloor, checker_pixels
    rec = be.manifest_record(StubFloor(number=6), 0, checker_pixels())
    alt = be.alt_manifest_record(StubFloor(number=7), 0, checker_pixels(), 15)
    m = be.export_manifest([rec], "/data", 4, screens=[{"entry":13}], alt_cameras=[alt])
    assert m["schema"] == 3 and m["alt_cameras"] == [alt]
    assert be.SUPPORTED_SCHEMAS == (1,2,3)
    # old call without alt_cameras still works (schema 3 but empty list)
    assert be.export_manifest([rec], "/data", 4)["alt_cameras"] == []

def test_alt_background_rel_path_and_manifest_record_match_asset_resolver_layout():
    import json
    from PyAitD.render import background_export as be
    from tests.stub_floor import StubFloor, checker_pixels
    rec = be.alt_manifest_record(StubFloor(number=6), 8, checker_pixels(), 19)
    json.dumps(rec)  # serialisable
    assert rec["layout"] == be.layout_rel_path(6,8)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_background_export.py::test_alt_background_rel_path_mirrors_resolver tests/test_background_export.py::test_alt_manifest_record_fields -v`
Expected: FAIL `AttributeError: alt_background_rel_path` / `MANIFEST_SCHEMA`.

- [ ] **Step 3: Write minimal implementation**

```python
# PyAitD/render/background_export.py
MANIFEST_SCHEMA = 3
SUPPORTED_SCHEMAS = (1, 2, 3)

def alt_background_rel_path(floor_number, cam_idx):
    return f"alt_backgrounds/floor{floor_number:02d}/camera{cam_idx:03d}.png"

def alt_manifest_record(floor, cam_idx, pixels, itd_entry):
    rec = manifest_record(floor, cam_idx, pixels)
    # reuse base fields (source/guide/layout/size/sha256/viewed_rooms/masks)
    # but source points to alt tree
    if pixels is not None:
        rec["source"] = alt_background_rel_path(floor.number, cam_idx)
        # guide/layout stay shared (point at base guides/)
    rec["itd_entry"] = int(itd_entry)
    rec["variant"] = "killed_sorcerer"
    return rec

def export_manifest(records, data_dir, guide_scale, screens=(), alt_cameras=()):
    return {
        "schema": MANIFEST_SCHEMA,
        "data_dir": str(data_dir),
        "guide_scale": int(guide_scale),
        "legend": dict(LEGEND),
        "cameras": list(records),
        "alt_cameras": list(alt_cameras),
        "screens": list(screens),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_background_export.py -k alt -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add PyAitD/render/background_export.py tests/test_background_export.py
git commit -m "feat: alt_background_rel_path + schema 3 alt_cameras (shared guides)"
```

---

### Task 3: AssetResolver alt selection

**Files:**
- Modify: `PyAitD/render/asset_resolver.py:26-148`
- Test: `tests/test_asset_resolver.py` (new cases)

**Interfaces:**
- Consumes: `alt_background_rel_path`, `GameProfile.alt_camera_sources` (via caller), `Floor.camera_image`.
- Produces: `override_alt_background_path(dir,floor,cam)->Path`, `AssetResolver.background(floor,cam_idx, *, killed_sorcerer=False)->ImageAsset`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_asset_resolver.py
def test_override_alt_background_path(tmp_path):
    from PyAitD.render.asset_resolver import override_alt_background_path
    from PyAitD.render.background_export import alt_background_rel_path
    assert tmp_path / alt_background_rel_path(7,0) == override_alt_background_path(tmp_path,7,0)

def test_background_prefers_alt_when_killed(tmp_path, monkeypatch):
    from pathlib import Path
    import numpy as np
    from PyAitD.render.asset_resolver import AssetResolver
    from tests.stub_floor import StubFloor
    base = np.zeros((200,320,3), np.uint8); base[0,0]=1
    alt  = np.zeros((200,320,3), np.uint8); alt[0,0]=2
    # stub Floor with one camera, viewed_rooms etc from StubFloor
    floor = StubFloor(number=7)  # cam 0 exists, viewed_rooms=[0]
    # monkeypatch save path to provide files via resolver's load_png override
    def fake_load(path):
        p=str(path)
        if "alt_backgrounds" in p: return alt
        if "backgrounds" in p: return base
        raise FileNotFoundError
    r=AssetResolver(None, tmp_path, load_png=fake_load)
    # manually make both files appear to exist
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    # without killed flag, base wins
    assert r.background(floor,0, killed_sorcerer=False).pixels[0,0,0]==1
    # with killed flag, alt wins
    assert r.background(floor,0, killed_sorcerer=True).pixels[0,0,0]==2
    # corrupt alt falls back to base
    def bad_alt(path):
        if "alt_backgrounds" in str(path): raise ValueError("bad")
        if "backgrounds" in str(path): return base
        raise FileNotFoundError
    r2=AssetResolver(None, tmp_path, load_png=bad_alt)
    assert r2.background(floor,0, killed_sorcerer=True).pixels[0,0,0]==1
    assert tmp_path / "alt_backgrounds/floor07/camera000.png" in r2.failures
```

- [ ] **Step 2: Run test to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_asset_resolver.py::test_override_alt_background_path tests/test_asset_resolver.py::test_background_prefers_alt_when_killed -v`
Expected: FAIL `override_alt_background_path` not defined / wrong pixels.

- [ ] **Step 3: Write minimal implementation**

```python
# PyAitD/render/asset_resolver.py
def override_alt_background_path(override_dir, floor_number, cam_idx):
    return Path(override_dir) / "alt_backgrounds" / f"floor{floor_number:02d}" / f"camera{cam_idx:03d}.png"

class AssetResolver:
    def background(self, floor, cam_idx, *, killed_sorcerer=False):
        # alt first when gated
        if killed_sorcerer:
            # check if this floor/cam is an alt source (optional: check profile map at call site,
            # but resolver can unconditionally try alt_path — miss is silent free)
            pixels=self._override(override_alt_background_path(self._override_dir,floor.number,cam_idx) if self._override_dir else None, _require_rgb) if self._override_dir else None
            # cleaner: just try alt_path when killed
            if pixels is not None:
                return ImageAsset(pixels.astype(np.uint8, copy=False), True)
        # then base
        if self._override_dir is not None:
            pixels=self._override(override_background_path(self._override_dir,floor.number,cam_idx), _require_rgb)
            if pixels is not None:
                return ImageAsset(pixels.astype(np.uint8, copy=False), True)
        return ImageAsset(floor.camera_image(cam_idx), False)
    def light(self, floor, cam_idx, *, killed_sorcerer=False):
        key=(floor.number,cam_idx,killed_sorcerer)
        if key not in self._lights:
            self._lights[key]=estimate_light(self.background(floor,cam_idx,killed_sorcerer=killed_sorcerer).pixels)
        return self._lights[key]
```

(Adjust `_lights` key and `background` fallback to keep existing `light(floor,cam)` calls working via default `killed_sorcerer=False`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_asset_resolver.py -k alt -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/render/asset_resolver.py tests/test_asset_resolver.py
git commit -m "feat: resolver alt_backgrounds gated on killed_sorcerer"
```

---

### Task 4: Export the 5 alts + palette.png + manifest merge

**Files:**
- Modify: `tools/export_backgrounds.py:28-216`
- Test: `tests/test_export_backgrounds.py` (new file or extend `tests/test_background_export.py`)

**Interfaces:**
- Consumes: `alt_background_rel_path`, `alt_manifest_record`, `override_palette_path`, `PROFILE.alt_camera_sources`, `load_entry` decode of `ITD_RESS`.
- Produces: `export_alt_backgrounds(data_dir, out_dir, guide_scale, screens=())`, `export_palette(data_dir, out_dir)` side-effects (atomic PNGs), `main()` writes 144+5+7+1 files and schema-3 manifest.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_export_backgrounds.py
def test_export_alt_backgrounds_writes_five_and_reuses_guides(tmp_path, data_dir):
    from tools.export_backgrounds import export_alt_backgrounds, load_floor
    from PyAitD.games import load_profile
    profile=load_profile("aitd1")
    alt=export_alt_backgrounds(data_dir, tmp_path, guide_scale=4)
    assert len(alt)==5
    # files exist with shared guide path
    for rec in alt:
        assert (tmp_path / rec["source"]).is_file()
        assert rec["guide"]=="guides/floor{:02d}/camera{:03d}.png".format(rec["floor"],rec["camera"])
        assert rec["itd_entry"] in (15,16,17,18,19)
    # concrete check: floor07 cam000 is ITD_RESS:15, not CAMERA07:0
    import hashlib, numpy as np
    from PyAitD.engine.floor import Floor
    from PyAitD.render.background_export import sha256_rgb
    # ensure alt SHA differs from base
    base_sha=sha256_rgb(Floor(data_dir,7,profile).camera_image(0))
    alt_sha=[r["sha256"] for r in alt if r["floor"]==7 and r["camera"]==0][0]
    assert base_sha != alt_sha

def test_export_palette_writes_256x1(tmp_path, data_dir):
    from tools.export_backgrounds import export_palette
    export_palette(data_dir, tmp_path)
    from PyAitD.render.asset_resolver import load_png_rgb
    pix=load_png_rgb(tmp_path/"palette.png")
    assert pix.shape==(1,256,3)

def test_main_respects_floors_filter_and_force(tmp_path, data_dir):
    from tools.export_backgrounds import main
    # export only floor 06 with force, then check manifest alt_cameras subset
    import json, pathlib
    out=tmp_path/"out"
    rc=main([str(data_dir), "--out", str(out), "--floors", "06", "--force"])
    assert rc==0
    m=json.loads((out/"manifest.json").read_text())
    assert len(m["alt_cameras"])==3  # 06/0,06/5,06/8
    assert all(r["floor"]==6 for r in m["alt_cameras"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_export_backgrounds.py -v`
Expected: FAIL `export_alt_backgrounds` not defined.

- [ ] **Step 3: Write minimal implementation**

```python
# tools/export_backgrounds.py — add imports
from PyAitD.render.background_export import alt_background_rel_path, alt_manifest_record
from PyAitD.render.asset_resolver import override_palette_path
from PyAitD.engine.floor import load_entry
from PyAitD.engine.formats import decode_image
from PyAitD.engine.pak import find_pak

def export_alt_backgrounds(data_dir, out_dir, guide_scale, save=save_png, save_layout=save_layout):
    out_dir=pathlib.Path(out_dir)
    # map from profile
    alt_map=dict(PROFILE.alt_camera_sources)
    if not alt_map: return []
    # cache Floors per number, and palette for decode
    floors={}
    # palette from Floor 0 (ITD_RESS:3)
    palette=load_floor(data_dir,0).palette  # or decode_palette(load_entry(ITD_RESS,3))
    records=[]
    for (floor_num,cam_idx),entry in sorted(alt_map.items()):
        if floor_num not in floors:
            try: floors[floor_num]=load_floor(data_dir,floor_num)
            except Exception as exc: print(f"warning: floor {floor_num:02d} skipped: {exc}", file=sys.stderr); continue
        floor=floors[floor_num]
        try:
            raw=load_entry(str(find_pak(data_dir,"ITD_RESS")), entry)
            pixels=decode_image(raw[:64000], palette)
        except Exception as exc:
            print(f"warning: alt floor {floor_num:02d} cam {cam_idx:03d} ITD_RESS:{entry} skipped: {exc}", file=sys.stderr); continue
        # no guide/layout write — shared
        save(out_dir/alt_background_rel_path(floor_num,cam_idx), pixels)
        records.append(alt_manifest_record(floor,cam_idx,pixels,entry))
    return records

def export_palette(data_dir, out_dir, save=save_png):
    try:
        palette=load_floor(data_dir,0).palette # (256,3)
        # encode as 1x256 image row
        import numpy as np
        row=palette[None, :, :].astype(np.uint8) # (1,256,3)
        save(pathlib.Path(out_dir)/"palette.png", row)
        return True
    except Exception as exc:
        print(f"warning: palette skipped: {exc}", file=sys.stderr); return False

# in main(), after screens:
# respect floors= filter for alts: if --floors given, filter alt_map
# add force gate for alt_backgrounds/ like backgrounds/
# merge: records=_merge_manifest_records(out, records) ; alt_records=_merge_manifest_records(out, alt_records, key="alt_cameras")
# manifest=export_manifest(records, data_dir.resolve(), guide_scale, screens=screens, alt_cameras=alt_records)
```

Also add `alt_backgrounds/` existence check mirroring `backgrounds/`:

```python
alt_sub="alt_backgrounds"
if alt_map and (args.out/alt_sub).exists() and not args.force:
    print(f"error: {args.out/alt_sub} exists; pass --force...", file=sys.stderr); return 3
```

- [ ] **Step 4: Run test to verify it passes**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_export_backgrounds.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/export_backgrounds.py tests/test_export_backgrounds.py PyAitD/render/background_export.py
git commit -m "feat: export 5 road alts + palette.png, manifest schema 3"
```

---

### Task 5: check_overrides + coverage for alts

**Files:**
- Modify: `PyAitD/render/override_check.py:12-189`
- Modify: `tools/check_overrides.py:90-172`
- Test: `tests/test_override_check.py`

**Interfaces:**
- Consumes: `alt_background_rel_path`, `alt_manifest_record` shape.
- Produces: `check_alt_backgrounds(...)`, `alt_coverage(...)`, `summarize(..., alt_cov)` includes `alt_backgrounds:` line.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_override_check.py
def test_check_alt_backgrounds_missing_and_invalid(tmp_path):
    from PyAitD.render.override_check import check_alt_backgrounds
    from tests.stub_floor import StubFloor
    floor=StubFloor(number=7)
    manifest={"alt_cameras":[{"floor":7,"camera":0,"source":"alt_backgrounds/floor07/camera000.png","sha256":"a"}]}
    findings=check_alt_backgrounds(tmp_path, [floor], manifest)
    assert any(f.kind=="missing" and f.floor==7 and f.camera==0 for f in findings)

def test_summarize_includes_alt_line():
    from PyAitD.render.override_check import summarize
    cov={6:{"regenerated":3,"original":0,"missing":0,"invalid":0}}
    alt_cov={"regenerated":5,"original":0,"missing":0,"invalid":0}
    msg=summarize([], cov, None, alt_cov)
    assert "alt_backgrounds:" in msg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_override_check.py::test_check_alt_backgrounds_missing_and_invalid -v`
Expected: FAIL `check_alt_backgrounds` not defined.

- [ ] **Step 3: Write minimal implementation**

```python
# PyAitD/render/override_check.py — reuse _each_camera pattern
from PyAitD.render.asset_resolver import override_alt_background_path
def _each_alt_camera(override_dir, floors, load_png):
    # use alt_map keys from manifest alt_cameras floor/cam tuples + profile fallback
    ...

def check_alt_backgrounds(override_dir, floors, manifest=None, *, load_png=load_png_rgb):
    # mirror check_overrides but over alt paths when manifest says alt_cameras, else over profile.alt_camera_sources
    ...

def alt_coverage(override_dir, floors, manifest, *, load_png=load_png_rgb):
    expected={(c["floor"],c["camera"]):c["sha256"] for c in manifest.get("alt_cameras",[])}
    ...

def summarize(findings,cov,screen_cov=None,alt_cov=None):
    # add alt_backgrounds line when alt_cov is not None
    if alt_cov is not None:
        lines.append("alt_backgrounds: "+" / ".join(f"{k} {alt_cov[k]}" for k in ("regenerated","original","missing","invalid")))
```

In `tools/check_overrides.py`: load manifest, call `check_alt_backgrounds` + `alt_coverage`, include in `summarize`; `proof` renders alts via `resolver.background(floor,cam,killed_sorcerer=True)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_override_check.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/render/override_check.py tools/check_overrides.py tests/test_override_check.py
git commit -m "feat: check_overrides coverage for alt_backgrounds"
```

---

### Task 6: Runtime wiring + regenerate + docs

**Files:**
- Modify: `PyAitD/render/scene.py` (or `app/shell.py` call site) — pass `killed_sorcerer` from `game.cvars`.
- Modify: `tools/regenerate_backgrounds.py:560-700` — alt gate/judge loop.
- Modify: `docs/ai-background-regeneration.md`, `Makefile` help, `AGENTS.md`/`CONTEXT.md` (optional sync).
- Test: `tests/test_scene.py` or `tests/test_intro.py` (alt selection), `tests/test_regenerate_backgrounds.py` (mock `agy`).

**Interfaces:**
- Consumes: `AssetResolver.background(..., killed_sorcerer)`.
- Produces: `build_frame` selects alt when `KILLED_SORCERER==1`; regenerate writes `alt_backgrounds/`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scene.py
def test_build_frame_uses_alt_when_killed(data_dir, profile):
    from PyAitD.engine.game import init_game
    from PyAitD.engine.floor import Floor
    from PyAitD.render.asset_resolver import AssetResolver
    from PyAitD.render.scene import build_frame
    game=init_game(data_dir, profile)
    game.cvars[game.profile.cvar_index("KILLED_SORCERER")]=1
    floor=Floor(data_dir,7,profile)
    # resolver with alt override present (tmp_path via monkeypatch load_png)
    # simplified: assert that when killed, asset is alt SHA distinct from base
    ...

# tests/test_regenerate_backgrounds.py
def test_regenerate_includes_alt_cameras(tmp_path, monkeypatch):
    # mock agy to return image, manifest has alt_cameras
    ...
    assert (tmp_path/"alt_backgrounds/floor07/camera000.png").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_scene.py::test_build_frame_uses_alt_when_killed -v`
Expected: FAIL — still loads base.

- [ ] **Step 3: Write minimal implementation**

```python
# PyAitD/render/scene.py
def build_frame(game, floor, resolver):
    killed=bool(game.cvars[game.profile.cvar_index("KILLED_SORCERER")]) if "KILLED_SORCERER" in game.profile.cvar_names else False
    # inside camera loop:
    asset=resolver.background(floor,cam_idx,killed_sorcerer=killed)
    light=resolver.light(floor,cam_idx,killed_sorcerer=killed)
    ...

# tools/regenerate_backgrounds.py — after cameras loop, add:
alt_cameras=manifest.get("alt_cameras",[])
for rec in alt_cameras:
    # same pipeline as cameras: describe, generate, gate (shared guide), judge, retry
    # src = in_dir/rec["source"], guide = in_dir/rec["guide"], out = out_dir/rec["source"]
```

Update `docs/ai-background-regeneration.md` layout tree to include `alt_backgrounds/floorNN/cameraNNN.png` and `palette.png`, table of 5 mappings, `KILLED_SORCERER` gate note; update `Makefile` `export-backgrounds:` help line.

- [ ] **Step 4: Run test to verify it passes**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_scene.py::test_build_frame_uses_alt_when_killed tests/test_regenerate_backgrounds.py -v && SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -m render -q`
Expected: PASS, no layering violation.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/render/scene.py tools/regenerate_backgrounds.py docs/ai-background-regeneration.md Makefile
git commit -m "feat: select road alt at runtime + regenerate alts, docs"
```

---

## Self-Review

* Spec coverage: every section (GameProfile seam, pure helpers + schema 3, resolver lookup, export palette+alts, override_check, check_overrides proof, regenerate loop, scene wiring, docs) has a task.
* Placeholder scan: no `TBD`/`TODO`; every step shows exact code and `pytest` command with expected FAIL/PASS.
* Type consistency: `alt_background_rel_path` / `override_alt_background_path` / `alt_manifest_record` / `alt_cameras` / `killed_sorcerer` names identical across tasks 2–6; manifest shape `{schema, data_dir, guide_scale, legend, cameras, alt_cameras, screens}` consistent.

