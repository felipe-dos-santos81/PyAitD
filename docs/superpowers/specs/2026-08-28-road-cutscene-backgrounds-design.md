# SPDX-License-Identifier: GPL-2.0-only
# Road cutscene backgrounds — export + override for the KILLED_SORCERER alts

*Date: 2026-08-28*
*Status: spec — approved in brainstorm chat*
*Scope: `make export-backgrounds` not exporting the 5 road/ending plates that FITD swaps in when `KILLED_SORCERER==1`.*

## 1. Summary

FITD `loadCamera` (`FitdLib/main.cpp:1243–1292`, `AITD1.h:15–19`) swaps 5 camera backgrounds for alternate `ITD_RESS` plates when `CVars[KILLED_SORCERER]==1`:

| floor | cam | alt `ITD_RESS` entry | macro |
|------:|----:|---------------------:|-------|
| 7 | 0 | 15 | `AITD1_CAM07000` |
| 7 | 1 | 16 | `AITD1_CAM07001` |
| 6 | 0 | 17 | `AITD1_CAM06000` |
| 6 | 5 | 18 | `AITD1_CAM06005` |
| 6 | 8 | 19 | `AITD1_CAM06008` |

Each entry is a 64 000-byte 320×200 image (verified: decode via `raw[:64000]` + `ITD_RESS:3` palette, SHA distinct from the base `CAMERA0x.PAK` image for the same floor/cam). Today `PyAitD/engine/floor.py` only reads `CAMERAxx.PAK`, and `tools/export_backgrounds.py` only exports 144 `CAMERA` images + 7 `ITD_RESS` screens (6,7,8,10,12,13,14) + guides/manifest. The 5 road alts and `palette.png` are never written, and `render/asset_resolver.py` never selects them.

Fix: export the 5 alts as a second copy with the same filename in a parallel tree (`alt_backgrounds/floorNN/cameraNNN.png`), share the base guides/layouts, bump the manifest to schema 3 with an `alt_cameras` list, and teach `AssetResolver` to select the alt when the game state demands it. Also add the missing `palette.png` export that `override_palette_path` already expects. All changes stay behind the `GameProfile` seam — `engine/` reads the mapping, `games/aitd1/profile.py` owns the 5-entry table.

## 2. Goals / non-goals

**Goals**

* `make export-backgrounds` writes every plate the game can show: 144 bases + 5 road alts + 7 screens + `palette.png` + guides/layouts + `manifest.json` (schema 3).
* `AssetResolver` can load the alt at play time when `KILLED_SORCERER==1`, with silent fallback to base/original on missing/corrupt alt.
* `make check-overrides` and `make regenerate-backgrounds` cover the alts (validation, coverage, gate/judge, retry) without breaking old `schema 1/2` manifests or existing `overrides/` dirs.
* Game-neutral `engine/` — new code reads `game.profile.alt_camera_sources`; game-specific numbers live only in `games/aitd1/profile.py`.

**Non-goals**

* No change to `Floor` PAK names or room/camera parsing.
* No `PRESENT.PAK` / `ENDSEQ.PAK` slideshow export (those frames are not camera backgrounds and are not loaded via `loadCamera`).
* No new dependency, no SDK — `regenerate_backgrounds` still shells to `agy` only.
* No re-design of the guide geometry; alts reuse the base camera's masks/collision/walkable (same `ETAGEnn` camera definition, different pixels).

## 3. Architecture & ownership

```
games/base.py      GameProfile.alt_camera_sources: Mapping[(floor,cam) -> itd_entry]
games/aitd1/profile.py  AITD1.alt_camera_sources = {(7,0):15, (7,1):16, (6,0):17, (6,5):18, (6,8):19}
render/background_export.py  pure: alt_background_rel_path, alt_manifest_record, export_manifest schema 3
render/asset_resolver.py     lookup: override_alt_background_path + selection in background()
tools/export_backgrounds.py  I/O: export_alt_backgrounds + export_palette, manifest merge for alt_cameras
render/override_check.py     pure validation: check_alt_backgrounds / alt_coverage, summarize
tools/check_overrides.py     CLI: include alt_cameras in findings/coverage/proof
tools/regenerate_backgrounds.py  loop over manifest.alt_cameras like cameras + screens
```

Layering: `engine/` never imports `games/`; it reads `game.profile.alt_camera_sources` (or `assets.profile`). `render/` never imports `pygame`/`moderngl` except `asset_resolver.load_png_rgb` (pinned by `tests/test_layering.py`). New code follows the same split as the existing `screens` addition (`docs/superpowers/specs/2026-08-26-screen-overrides-design.md`).

## 4. Components & data structures

### 4.1 `GameProfile` (`games/base.py`)

Add field:

```python
alt_camera_sources: Mapping[tuple[int,int], int] = field(default_factory=dict)
# (floor, camera) -> ITD_RESS entry index that overrides CAMERA{NN}.PAK entry
# when the profile's alternate condition holds. For AITD1 the condition is
# CVar KILLED_SORCERER==1 (FitdLib/main.cpp:1253). Empty means no alts.
```

Document next to `resource_pak`/`palette_entry`/`intro_start`.

`games/aitd1/profile.py` sets:

```python
alt_camera_sources=MappingProxyType({(7,0):15, (7,1):16, (6,0):17, (6,5):18, (6,8):19}),
```

Citation: `AITD1.h:15–19` and `FitdLib/main.cpp:1243–1292`. Keep the mapping as `ITD_RESS` entry numbers so `Assets.resource_screen` palette logic (`raw[:64000]` + `ITD_RESS:3` palette) is reused.

### 4.2 `render/background_export.py` (pure)

* `alt_background_rel_path(floor,cam)` → `alt_backgrounds/floor{floor:02d}/camera{cam:03d}.png`
  Must stay byte-identical to `asset_resolver.override_alt_background_path` tail (same invariant as `background_rel_path` / `override_background_path`).
* `MANIFEST_SCHEMA = 3`, `SUPPORTED_SCHEMAS = (1,2,3)`.
* `alt_manifest_record(floor,cam,pixels,itd_entry,viewed_rooms,masks)` — shape:
  ```json
  {"floor":7,"camera":0,"source":"alt_backgrounds/floor07/camera000.png",
   "guide":"guides/floor07/camera000.png","layout":"guides/floor07/camera000.json",
   "size":[320,200],"viewed_rooms":[…],"masks":N,"sha256":"…",
   "itd_entry":15,"variant":"killed_sorcerer"}
  ```
  `guide`/`layout` point to the **base** `guides/` (shared geometry). `itd_entry`+`variant` are the only fields not in a base `manifest_record`.
* `export_manifest(records, data_dir, guide_scale, screens=(), alt_cameras=())` → `{schema:3, data_dir, guide_scale, legend, cameras:[144], alt_cameras:[5], screens:[7]}`. Default `alt_cameras=()` keeps schema-2 call sites working.
* No `alt_guide_rel_path` / `alt_layout_rel_path` — reuse base. `layout_geometry(floor,cam)` is identical for base and alt (same camera definition).

### 4.3 `render/asset_resolver.py`

* `override_alt_background_path(dir,floor,cam)` → `Path(dir)/alt_backgrounds/floor{NN:02d}/camera{NNN:03d}.png`
* `background(self, floor, cam_idx, *, killed_sorcerer: bool = False) -> ImageAsset` (caller reads `game.cvars[game.profile.cvar_index("KILLED_SORCERER")]` and passes the bool; no `game` object enters the resolver).

  Selection, with existing `self._override` cache/failures/log-once:

  ```
  if killed_sorcerer and (floor.number,cam_idx) in alt_map:
      asset = self._override(alt_path, _require_rgb)
      if asset is not None: return ImageAsset(asset, True)
  asset = self._override(base_path, _require_rgb)
  if asset is not None: return ImageAsset(asset, True)
  return ImageAsset(floor.camera_image(cam_idx), False)
  ```

  Alt and base validated by same `_require_rgb` (8192 limit). `_lights` memo keys become `(floor.number,cam_idx,killed_sorcerer)` so alt and base lights don't alias.
* `palette()` unchanged (`override_palette_path` at `palette.png`).

### 4.4 `tools/export_backgrounds.py` (I/O)

* New `export_alt_backgrounds(data_dir, alt_map, out_dir, guide_scale)` — for each `(floor,cam)->entry` in `alt_map`:
  1. `floor = Floor(data_dir, floor, PROFILE)` (cached per floor),
  2. `pixels = decode_image(load_entry(find_pak(data_dir,"ITD_RESS"), entry)[:64000], Floor(data_dir,0,PROFILE).palette)` — same `raw[:64000]` + `ITD_RESS:3` palette path as `Assets.resource_screen`,
  3. `save(out_dir/alt_background_rel_path(floor,cam), pixels)` (atomic `.tmp` + `os.replace`),
  4. `alt_manifest_record(...)` (guide/layout point at base; no guide write).
* New `export_palette(data_dir, out_dir)` — single `palette.png` at `override_palette_path` (256×1 RGB) from `Floor(data_dir,0,PROFILE).palette` written via `save_png`; overwrites on `--force`, never blocks the run on failure (warn + skip). Path must stay identical to `asset_resolver.override_palette_path` tail.
* `main()` flow: `records = export_floor` (144) → `alt_records = export_alt_backgrounds` (5) → `screens = export_screens` (7) → `export_palette`. Respect `floors=` filter for alts (only export alts whose floor is in the requested subset) and `force=` gates for `alt_backgrounds/` like `backgrounds/`.
* Manifest merge: existing `_merge_manifest_records(out,key="cameras")` generalized to `key="alt_cameras"` (`ident = lambda r: (r["floor"], r["camera"])`) so `floors=` subsets compose.

### 4.5 `render/override_check.py`

* New `_each_alt_camera(dir, floors, alt_map, load_png)` yielding `(floor,cam,path,resolver)`.
* `check_alt_backgrounds(dir, floors, manifest, alt_map, ...)` — at most one `Finding` per alt camera (`missing` | `invalid` | `aspect` | `size`), with `floor`/`camera` and `path` like `check_overrides`.
* `alt_coverage(dir, floors, manifest, alt_map, ...)` → `{"regenerated":…, "original":…, "missing":…, "invalid":…}` (keyed by `alt_cameras` expected hashes).
* `summarize(findings, cov, screen_cov, alt_cov)` adds `alt_backgrounds: regenerated / original / missing / invalid` line; `has_errors` still watches only `invalid`/`aspect`.

### 4.6 CLI surfaces

* `make export-backgrounds` help text updated: `out= alt_backgrounds/ + palette.png + manifest schema 3 (alt_cameras 5)`.
* `make check-overrides` help adds `alt_backgrounds:` coverage line.
* `tools/regenerate_backgrounds.py` help: `in=`/`out_ai=` dirs carry `alt_backgrounds/`; new manifest key.

## 5. Data flow

### 5.1 Export

```
Floors 0–7 (144 cams) ──► backgrounds/floorNN/cameraNNN.png + guides/floorNN/*.{png,json}  (existing)
alt_camera_sources (5) ─► alt_backgrounds/floorNN/cameraNNN.png (new, no duplicate guide)
ITD_RESS:3 palette     ─► palette.png (new, 256×1)
ITD_RESS 6,7,8,10,12,13,14 ─► screens/ressNN.png + guides/screens/*  (existing)
                               │
                               ▼
                      manifest.json schema 3  {cameras:[144], alt_cameras:[5], screens:[7]}
```

Partial `floors=6` or `floors=7` only writes base + alt entries whose floor is in the set; `_merge_manifest_records` keeps the rest.

### 5.2 Play

```
scene.build_frame(game,floor,resolver):
    killed = bool(game.cvars[game.profile.cvar_index("KILLED_SORCERER")])
    asset = resolver.background(floor,cam_idx, killed_sorcerer=killed)
    # asset.pixels is alt PNG when killed and valid, else base override, else original
    light = resolver.light(...)  # estimate_light on whatever background() returned
    frame = FrameDescription(CameraView(...), asset, palette, ...)
```

No `Floor` change; `playworld` already advances `game.cvars` via LIFE, so the swap happens the tick after the flag flips (matches FITD `loadCamera` next-camera load).

### 5.3 Check & regenerate

* `check_overrides.py` loads manifest, calls `check_overrides` (base), `check_alt_backgrounds` (alt), `check_screens`, `check_body_materials`; prints one line per `invalid`/`aspect`/`size` and coverage for `floor NN`, `total`, `screens:`, `alt_backgrounds:`.
* `regenerate_backgrounds.py` iterates `manifest["cameras"]`, then `manifest["alt_cameras"]` (if present), then `screens` — each with description → image → `plate_check` gate → text-model judge → retry, writing to `out_ai/alt_backgrounds/...` like `out_ai/backgrounds/...` and reusing shared guides for alt gate lines.

## 6. Error handling, fallback & compatibility

* **Condition:** alt considered only when the profile's alt condition holds (`KILLED_SORCERER==1` for AITD1). When false, an `alt_backgrounds/` file on disk is ignored (no ragged state).
* **Fallback chain:** valid alt override → valid base override → original. Corrupt/oversized/unreadable alt → `AssetResolver.failures[path]` warning once, degrade to base (same as every other override; never crash in `build_frame`).
* **Manifest compat:** `SUPPORTED_SCHEMAS=(1,2,3)`. Old `schema 1/2` manifests (144 cameras, no `alt_cameras`) still load; `alt_cameras` defaults to `[]`, old `overrides/` dirs keep working. New code writes `3`; old `check_overrides` that doesn't know `3` still validates `cameras`/`screens`.
* **Atomic writes:** every PNG/layout/`manifest.json` via `.tmp` + `os.replace` so interrupted runs never leave truncated files.
* **`out/` / `floors=` / `force=` / `screens=` preserved:** `backgrounds/` existence gates without `force` as today; new `alt_backgrounds/` gated the same way — existing regenerated road plates not clobbered unless `force`. `--no-screens` still skips only screens.
* **Size/aspect guards:** same `_require_rgb` (8192), 16:10 ±1% stretch warning, integer-multiple 320×200 size hint, for alt + base + screens + palette (palette must be 256 wide).
* **Palette export:** if `ITD_RESS:3` decode fails, `export_backgrounds` warns and skips `palette.png` rather than failing the run.

## 7. Testing & proof

**Unit (headless, `pytest -m render/meta`)**

* `tests/test_background_export.py` — `alt_background_rel_path` mirrors `override_alt_background_path`; `alt_manifest_record` fields (`source`, `guide`, `layout`, `size`, `sha256`, `viewed_rooms`, `masks`, `itd_entry`, `variant`); `export_manifest` schema 3 carries `alt_cameras` and round-trips through `(1,2,3)`; `layout_geometry` for alt floor/cam equals base.
* New/extended `tests/test_export_backgrounds.py` — stub `Floor`/`Assets` off real data: `export_alt_backgrounds` writes exactly 5 files under `alt_backgrounds/`, reuses base guides (no duplicate `save_layout` for alts), `palette.png` is 256×1 and matches `decode_palette(ITD_RESS:3)`.
* `tests/test_asset_resolver.py` — precedence: base-only, alt+killed→alt wins, alt+killed==False→base wins, corrupt alt→fallback to base, `light()` memo keys separate per variant, `failures` logged once.
* `tests/test_override_check.py` — `check_alt_backgrounds`/`alt_coverage` (`invalid`/`aspect`/`size`/`missing`) and `summarize` `alt_backgrounds:` line.
* `tests/test_layering.py` — no new `pygame`/`moderngl` in `render/background_export.py` or `render/override_check.py`, no `engine→games` import.
* `tests/test_game_profile.py` — pins `AITD1.alt_camera_sources == {(7,0):15,…}` with `AITD1.h:15–19` citation.

**Integration (needs game data)**

* `make export-backgrounds out=/tmp/overrides force=1` → `backgrounds/` 144, `alt_backgrounds/` 5, `screens/` 7, `palette.png`, `manifest.json` schema 3 with 5 `alt_cameras` hashes distinct from base.
* `make check-overrides overrides=/tmp/overrides` → `alt_backgrounds: regenerated/original/missing/invalid` and no `invalid`/`aspect`.
* `make check-overrides proof=1` → 5 extra `floorNN-cameraNNN.png` side-by-sides for alts.

**Regeneration**

* `make regenerate-backgrounds in=/tmp/overrides out_ai=/tmp/overrides-ai dry=1` lists 5 alt plates alongside base/screens; a run with mocked `agy` exercises gate/judge/retry for alts.

## 8. Migration & docs

* Existing `overrides/` dirs without `alt_backgrounds/` stay valid — `check_overrides` reports `alt_backgrounds: missing 5` (informational), `make run` plays bases.
* Re-export with `force=1` adds `alt_backgrounds/` + `palette.png` and bumps `manifest.json` to schema 3 via merge.
* Update `docs/ai-background-regeneration.md` (layout tree, 5-entry table, `alt_backgrounds/` override name, `KILLED_SORCERER` gate, shared guides), `AGENTS.md`/`CONTEXT.md` `make export-backgrounds` line, and `make help` strings.
* No `PRESENT.PAK`/`ENDSEQ.PAK` handling — those slideshows are not camera overrides and stay out of scope.

## 9. Open decisions (locked during brainstorm)

* Root name `alt_backgrounds/` vs `backgrounds_alt/` — spec picks `alt_backgrounds/` (mirrors `alt_camera_sources`, sorts next to `backgrounds/`). `override_alt_background_path` is the single source of truth.
* Guides shared — alt records point at base `guides/floorNN/cameraNNN.{png,json}` (no duplication). If duplication preferred, add `alt_guide_rel_path` and change manifest pointers — one-line switch.
* `AssetResolver.background` signature locked to `killed_sorcerer: bool` (caller does the CVar read).

## 10. References

* `FitdLib/AITD1.h:15–19` `AITD1_CAM07000…AITD1_CAM06008`
* `FitdLib/main.cpp:1243–1292` `loadCamera` alt branch (`KILLED_SORCERER`, `g_currentFloor`, `cameraIdx` → `ITD_RESS`)
* `PyAitD/render/background_export.py`, `render/asset_resolver.py`, `tools/export_backgrounds.py`, `render/override_check.py`, `tools/check_overrides.py`, `tools/regenerate_backgrounds.py`
* `docs/ai-background-regeneration.md`, `docs/superpowers/specs/2026-08-27-background-layout-fidelity-design.md`, `docs/superpowers/specs/2026-08-26-screen-overrides-design.md`
