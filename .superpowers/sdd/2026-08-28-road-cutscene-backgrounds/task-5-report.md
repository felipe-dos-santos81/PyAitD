# Task 5 Report: check_overrides coverage for alts

## What you implemented
- `PyAitD/render/override_check.py:10-14` — Added `override_alt_background_path` import.
- `PyAitD/render/override_check.py:88-117` — Added `_DEFAULT_ALT_KEYS = [(7,0),(7,1),(6,0),(6,5),(6,8)]` (hard-coded to keep `render/` pure, synced with `games/aitd1/profile.py`) and `_each_alt_camera(override_dir, floors, load_png, *, manifest=None)`:
  - Derives alt tuples from `manifest["alt_cameras"]` when manifest carries that key (schema 3), else fallback to default 5 when `manifest is None`, else `[]` for old schema without key (no alts). Dedup+sorted, filtered to `floor_by_number` (only floors in `floors` list). One `AssetResolver` per floor (cache/failures intact), path via `override_alt_background_path`.
- `PyAitD/render/override_check.py:120-144` — `check_alt_backgrounds(override_dir, floors, manifest=None, *, load_png=load_png_rgb)` mirrors `check_overrides` but over alt paths via `resolver.background(..., killed_sorcerer=True)`:
  - `missing` when `not path.is_file()`.
  - `invalid` when `path in resolver.failures` (corrupt, 8192 oversize, non-RGB via `_require_rgb`) – detects invalid even when base fallback exists, else `not asset.is_override`.
  - `aspect`/`size` same thresholds (`_ASPECT=320/200 ±1%`, `<320` or `%320` etc.), reuses `_ASPECT`/`_ASPECT_TOL`/`_ORDER`.
- `PyAitD/render/override_check.py:147-166` — `alt_coverage(override_dir, floors, manifest, *, load_png=load_png_rgb)` aggregates `{"regenerated","original","missing","invalid"}` for alts:
  - `expected = {(c["floor"],c["camera"]):c["sha256"]}` from `manifest.get("alt_cameras",[])`.
  - Iterates `_each_alt_camera(..., manifest)`, `missing`/`invalid` via same `failures` check, `original` when `sha256_rgb(asset.pixels)==expected`, else `regenerated`.
- `PyAitD/render/override_check.py:243-273` — Extended `summarize(findings,cov,screen_cov=None,alt_cov=None)` to append `alt_backgrounds: regenerated X / original X / missing X / invalid X` when `alt_cov is not None` (after `screens:` line, keeps backward compat `alt_cov=None`).
- `tools/check_overrides.py:19-23` — Imports `override_alt_background_path`, `alt_coverage`, `check_alt_backgrounds`.
- `tools/check_overrides.py:57-82` — `render_proof(..., *, killed_sorcerer=False)` now gates on `killed_sorcerer`: tries `resolver.background(..., killed_sorcerer)`, skips when `alt_path in failures` or missing, suffixes output `-alt.png` to avoid colliding with base proof.
- `tools/check_overrides.py:150-159` — `main()` now `findings += check_alt_backgrounds(..., manifest)` and `alt_cov = alt_coverage(..., manifest) if manifest else None`, prints `summarize(..., alt_cov)`.
- `tools/check_overrides.py:178-197` — Proof loop after base cameras renders alt proofs: derives `alt_tuples` from `manifest["alt_cameras"]` when present else `load_profile("aitd1").alt_camera_sources`; filters by `floor_by_number` and `cidx < len(floor.cameras)`, calls `render_proof(..., killed_sorcerer=True)`.
- `tests/test_override_check.py:175-189` — Added brief's two tests `test_check_alt_backgrounds_missing_and_invalid` and `test_summarize_includes_alt_line`.
- `tests/test_tools_graphics_cli.py:99-104` — Updated `test_main_writes_manifest_via_tmp_and_replace` to assert palette.png presence (task 4's `palette.png` now written alongside `backgrounds/`).

## What you tested and test results
- TDD cycle:
  - `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_override_check.py::test_check_alt_backgrounds_missing_and_invalid -v` → before impl: FAIL `check_alt_backgrounds not defined`; after impl: 2 passed.
  - `pytest tests/test_override_check.py -v` → 17 passed (15 existing +2 new).
  - `pytest -m render -q` → 281 passed (279 +2), 1053 deselected.
  - `pytest tests/test_layering.py -v` → 20 passed (no `render`→`games` import).
  - `pytest tests/test_tools_graphics_cli.py -v` → 24 passed (fixed palette expectation).
  - `pytest -m "render or engine or tools or meta" -q` → 929 passed, 2 skipped, 1 xfailed.
- Manual checks (with `load_png` mocks and real `write_png`):
  - Corrupt alt PNG → `invalid` (detail `Unsupported image format`), `alt_coverage invalid 1`.
  - 400x300 alt → `aspect`, 160x100 alt → `size`.
  - Oversized 9000x9000 alt → `invalid` (detail `exceeds 8192x8192`).
  - Valid alt matching manifest SHA → `alt_coverage original 1`; mismatched → `regenerated 1`; fallback with base valid but alt corrupt → `invalid` not `aspect`.
  - Fallback `manifest=None` with floors 6,7 → `check_alt` yields 5 missing sorted [(6,0),(6,5),(6,8),(7,0),(7,1)]; old schema `{"cameras":[]}` → 0; empty `{"alt_cameras":[]}` → 0.
  - `summarize([], {6:...}, None, {"regenerated":5,...})` contains `alt_backgrounds: regenerated 5 / original 0 / missing 0 / invalid 0`.
  - `render_proof` alt valid → `floor07-camera000-alt.png`, corrupt/missing → `None`, base valid not confused.

## TDD Evidence (RED/GREEN)
- RED (before `override_check.py` edits, after adding tests):
  ```
  tests/test_override_check.py::test_check_alt_backgrounds_missing_and_invalid FAILED - ImportError: cannot import name 'check_alt_backgrounds'
  tests/test_override_check.py::test_summarize_includes_alt_line FAILED - TypeError: summarize() got unexpected keyword argument 'alt_cov'
  ```
- GREEN (after `override_check.py:88-273` and `tools/check_overrides.py` edits):
  ```
  tests/test_override_check.py::test_check_alt_backgrounds_missing_and_invalid PASSED
  tests/test_override_check.py::test_summarize_includes_alt_line PASSED
  tests/test_override_check.py -> 17 passed
  ```

## Files changed
- `PyAitD/render/override_check.py` — added import, `_DEFAULT_ALT_KEYS`, `_each_alt_camera`, `check_alt_backgrounds`, `alt_coverage`, extended `summarize`.
- `tools/check_overrides.py` — alt imports, `render_proof` killed flag + `-alt` suffix, `main` alt findings/coverage/summarize/proof.
- `tests/test_override_check.py` — 2 new tests (brief verbatim).
- `tests/test_tools_graphics_cli.py` — relaxed `test_main_writes_manifest_via_tmp_and_replace` to allow `palette.png`.

## Self-review findings
- Reuses `_require_rgb`/`_MAX_OVERRIDE_DIMENSION` (8192) via `AssetResolver._override`/`failures` and `_ASPECT`/`_ASPECT_TOL` exactly as `check_overrides`; no duplicated validation, no new PNG decoder.
- Keeps `render/` pure: hard-coded `_DEFAULT_ALT_KEYS` avoids `PyAitD.games` import (layering test passes). Value pinned to `AITD1.h:15-19` and `profile.py` mapping; fallback only when `manifest is None`, old schema `{"cameras":...}` yields 0 (preserves schema 1/2 compat, tested).
- `check_alt` detects invalid alt even when base override exists (via `path in resolver.failures`) – otherwise `resolver.background(killed=True)` fallback would mask alt corruption as base valid. Verified with base valid + alt corrupt → `invalid`.
- Atomic/manifest compat: `override_check` never writes; `check_overrides` proof respects `manifest["alt_cameras"]` when present else profile fallback, and filters by `floors` (matches `export`'s `--floors` filtered `alt_cameras` merge). `SUPPORTED_SCHEMAS` unchanged (still (1,2,3)) so old manifests load.
- Proof filenames use `-alt` suffix to avoid colliding with base `floorNN-cameraNNN.png` when both base and alt overrides exist for same floor/cam (e.g., 07/0).
- `summarize` signature backward compat: `alt_cov=None` default, existing callers with 2/3 args unchanged.

## Concerns
- `_DEFAULT_ALT_KEYS` duplicates `AITD1.alt_camera_sources` keys; drift would desync `check_overrides` fallback (no manifest) from profile truth. Mitigated by comment and 5-entry pin in `tests/test_game_profile.py`, but no runtime assertion.
- `render_proof` alt original is `plain.background(floor,cam)` (base floor image) not the ITD_RESS alt source; for alt cameras the side-by-side compares base original vs alt override, not alt original vs alt override. Matches brief's `resolver.background(..., killed_sorcerer=True)` proof spec, but visual diff is base-vs-alt, not ITD_RESS-vs-alt.
- `alt_coverage` with `manifest=None` returns `regenerated` for valid alts (expected empty) – tool never calls it without manifest (gated), so informational only; direct callers with `None` see regenerated rather than original, which is correct per missing SHA but maybe surprising.
