# Screen Overrides Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export the seven ITD_RESS full-screen images (character select, story, title, letter/book/notebook, dead end) with layout guides, and load regenerated replacements from the override directory at run time.

**Architecture:** `render/asset_resolver.py` gains one path function and one resolver method mirroring the background override contract. `render/background_export.py` (pure NumPy) gains screen records, guide rects and a manifest v2. `app/ui.py` consumers read screens through the resolver and scale any override to 320x200 at composite time. `tools/` scripts learn the `screens` kind; PNG I/O stays there.

**Tech Stack:** Python 3.12, NumPy, pygame-ce (only in `app/` and `tools/`), pytest. No new dependency.

**Spec:** `docs/superpowers/specs/2026-08-26-screen-overrides-design.md`

## Global Constraints

- `# SPDX-License-Identifier: GPL-2.0-only` first line of every new Python file.
- `render/background_export.py` and `render/override_check.py` stay pygame- and moderngl-free (`tests/test_layering.py` enforces).
- `asset_resolver` touches pygame in exactly one function, `load_png_rgb` (layering test pins it).
- Override layout `DIR/screens/ress<NN>.png` is defined by `asset_resolver.override_screen_path`; the export mirrors it — change both or neither.
- Exported screens: entries `(6, 7, 8, 10, 12, 13, 14)`; entry 11 excluded.
- Non-320x200 overrides are scaled to 320x200 at composite time (`pygame.transform.smoothscale`); text/portrait geometry stays in 320x200 space.
- Any test touching pygame runs with `SDL_VIDEODRIVER=dummy`; tests needing game data use the `data_dir` fixture (skips when absent).
- Run `.venv/bin/pytest -q` before every commit; never mass-reformat.
- `MANIFEST_SCHEMA` becomes 2; readers accept 1 and 2.

---

### Task 1: Resolver path and `resource_screen`

**Files:**
- Modify: `PyAitD/render/asset_resolver.py`
- Test: `tests/test_asset_resolver.py`

**Interfaces:**
- Produces: `override_screen_path(override_dir, entry) -> Path` (`DIR/screens/ress<NN>.png`); `AssetResolver.resource_screen(entry) -> ImageAsset`.
- `AssetResolver(assets, override_dir, *, load_png)` — `assets` must expose `resource_screen(entry)` (the existing `engine.assets.Assets` does).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_asset_resolver.py`:

```python
from PyAitD.render.asset_resolver import override_screen_path


def _assets():
    original = np.full((200, 320, 3), 9, dtype=np.uint8)
    return SimpleNamespace(body=lambda n: n, resource_screen=lambda entry: original)


def test_screen_path_follows_the_convention(tmp_path):
    assert override_screen_path(tmp_path, 10) == tmp_path / "screens" / "ress10.png"
    assert override_screen_path(tmp_path, 6) == tmp_path / "screens" / "ress06.png"


def test_resource_screen_without_override_dir_returns_original():
    asset = AssetResolver(_assets(), None).resource_screen(10)
    assert isinstance(asset, ImageAsset) and not asset.is_override
    assert asset.pixels.shape == (200, 320, 3) and asset.pixels[0, 0, 0] == 9


def test_resource_screen_absent_override_falls_back_silently(tmp_path, caplog):
    def fail_if_called(p):
        raise AssertionError("load_png must not be called when the override file is absent")
    resolver = AssetResolver(_assets(), tmp_path, load_png=fail_if_called)
    with caplog.at_level(logging.WARNING, logger="PyAitD.engine.assets"):
        asset = resolver.resource_screen(10)
    assert not asset.is_override and not resolver.failures and not caplog.records


def test_resource_screen_override_is_used_at_any_size_and_cached(tmp_path):
    path = override_screen_path(tmp_path, 14)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"png")
    big = np.zeros((400, 640, 3), dtype=np.uint8)
    calls = []
    resolver = AssetResolver(_assets(), tmp_path, load_png=lambda p: calls.append(p) or big)
    first = resolver.resource_screen(14)
    second = resolver.resource_screen(14)
    assert first.is_override and first.pixels is big and second.pixels is big
    assert len(calls) == 1


def test_resource_screen_invalid_override_warns_once_and_falls_back(tmp_path, caplog):
    path = override_screen_path(tmp_path, 13)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"png")
    resolver = AssetResolver(_assets(), tmp_path, load_png=lambda p: np.zeros((10, 10), dtype=np.uint8))
    with caplog.at_level(logging.WARNING, logger="PyAitD.engine.assets"):
        asset = resolver.resource_screen(13)
        resolver.resource_screen(13)
    assert not asset.is_override
    assert path in resolver.failures
    assert len(caplog.records) == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_asset_resolver.py -q`
Expected: FAIL — `ImportError: cannot import name 'override_screen_path'`.

- [ ] **Step 3: Implement**

In `PyAitD/render/asset_resolver.py`, after `override_palette_path`:

```python
def override_screen_path(override_dir, entry):
    # Full-screen ITD_RESS resources (title, character select, story, letter,
    # book, notebook, dead end). Mirrored by background_export.screen_rel_path.
    return Path(override_dir) / "screens" / f"ress{entry:02d}.png"
```

In `AssetResolver`, after `background`:

```python
    def resource_screen(self, entry):
        if self._override_dir is not None:
            pixels = self._override(override_screen_path(self._override_dir, entry), _require_rgb)
            if pixels is not None:
                return ImageAsset(pixels.astype(np.uint8, copy=False), True)
        return ImageAsset(self._assets.resource_screen(entry), False)
```

Update the module docstring's first line to "Visual asset lookup (camera backgrounds, palette, full-screen resources) with an optional user override directory."

- [ ] **Step 4: Run tests**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_asset_resolver.py tests/test_layering.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/render/asset_resolver.py tests/test_asset_resolver.py
git commit -m "feat: AssetResolver.resource_screen with screens/ressNN.png overrides"
```

---

### Task 2: Screen records, guide rects and manifest v2

**Files:**
- Modify: `PyAitD/render/background_export.py`
- Test: `tests/test_background_export.py`

**Interfaces:**
- Produces (all in `background_export`):
  - `SCREEN_ENTRIES = (6, 7, 8, 10, 12, 13, 14)`; `SCREEN_NAMES: dict[int, str]`.
  - `PORTRAIT_RECTS = ((10, 10, 140, 181), (170, 10, 140, 181))`, `STORY_COLUMNS = ((5, 5, 150, 189), (165, 5, 150, 189))`, `CREDITS_BOX = (48, 2, 212, 195)`, `READING_BOX = (60, 20, 200, 160)`, `FULL_FRAME = (0, 0, 320, 200)` — `(x, y, w, h)` ints.
  - `SCREEN_GUIDES: dict[int, tuple[tuple[int,int,int,int], ...]]`.
  - `screen_rel_path(entry) -> str`, `screen_guide_rel_path(entry) -> str`.
  - `screen_record(entry, pixels) -> dict` with keys `entry, name, source, guide, size, sha256, blits`.
  - `screen_guide(pixels, entry, scale) -> np.ndarray` `(200*scale + GUIDE_FOOTER, 320*scale, 3)`.
  - `export_manifest(records, data_dir, guide_scale, screens=())` → adds `"screens": list(screens)`; `MANIFEST_SCHEMA = 2`; `SUPPORTED_SCHEMAS = (1, 2)`.
  - `COLOR_BLIT = COLOR_COLLISION` (blue): "engine draws over this".

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_background_export.py`:

```python
def test_screen_paths_mirror_the_resolver_layout():
    from PyAitD.render.asset_resolver import override_screen_path
    import pathlib
    assert be.screen_rel_path(10) == "screens/ress10.png"
    assert be.screen_guide_rel_path(10) == "guides/screens/ress10.png"
    assert pathlib.Path("/x") / be.screen_rel_path(6) == override_screen_path("/x", 6)


def test_screen_entries_and_guides_are_consistent():
    assert be.SCREEN_ENTRIES == (6, 7, 8, 10, 12, 13, 14)
    assert 11 not in be.SCREEN_ENTRIES
    assert set(be.SCREEN_GUIDES) == set(be.SCREEN_ENTRIES) == set(be.SCREEN_NAMES)
    for entry, rects in be.SCREEN_GUIDES.items():
        assert rects, entry
        for x, y, w, h in rects:
            assert 0 <= x and 0 <= y and x + w <= 320 and y + h <= 200, (entry, (x, y, w, h))


def test_screen_record_fields():
    pixels = np.full((200, 320, 3), 3, np.uint8)
    rec = be.screen_record(10, pixels)
    assert rec["entry"] == 10 and rec["name"] == "PERSO_CHOICE"
    assert rec["source"] == "screens/ress10.png" and rec["guide"] == "guides/screens/ress10.png"
    assert rec["size"] == [320, 200]
    assert rec["sha256"] == hashlib.sha256(pixels.tobytes()).hexdigest()
    assert rec["blits"] == [list(r) for r in be.SCREEN_GUIDES[10]]


def test_screen_guide_draws_blit_rects_and_legend():
    pixels = np.zeros((200, 320, 3), np.uint8)
    img = be.screen_guide(pixels, 10, 2)
    assert img.shape == (400 + be.GUIDE_FOOTER, 640, 3)
    x, y, w, h = be.SCREEN_GUIDES[10][0]
    assert tuple(img[y * 2, x * 2]) == be.COLOR_BLIT            # top-left corner of the first rect
    assert tuple(img[(y + h - 1) * 2, (x + w - 1) * 2]) == be.COLOR_BLIT
    assert tuple(img[400 + 2, 2]) == be.COLOR_MASK             # legend footer, first swatch


def test_manifest_v2_carries_screens_and_accepts_v1():
    m = be.export_manifest([], "/data", 4, screens=[{"entry": 13}])
    assert m["schema"] == 2 and m["screens"] == [{"entry": 13}]
    assert be.export_manifest([], "/data", 4)["screens"] == []
    assert be.SUPPORTED_SCHEMAS == (1, 2)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_background_export.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'screen_rel_path'`.

- [ ] **Step 3: Implement**

In `PyAitD/render/background_export.py`, replace `MANIFEST_SCHEMA = 1` with:

```python
MANIFEST_SCHEMA = 2
SUPPORTED_SCHEMAS = (1, 2)   # 1: cameras only; 2: cameras + screens
```

Change `export_manifest`:

```python
def export_manifest(records, data_dir, guide_scale, screens=()):
    return {
        "schema": MANIFEST_SCHEMA,
        "data_dir": str(data_dir),
        "guide_scale": int(guide_scale),
        "legend": dict(LEGEND),
        "cameras": list(records),
        "screens": list(screens),
    }
```

Append at the end of the module:

```python
# ---- full-screen ITD_RESS resources -------------------------------------
# AITD1.h entry numbers. Entry 11 (GRENOUILLE, copy protection) is never drawn.
SCREEN_ENTRIES = (6, 7, 8, 10, 12, 13, 14)
SCREEN_NAMES = {6: "LETTRE", 7: "LIVRE", 8: "CARNET", 10: "PERSO_CHOICE",
                12: "DEAD_END", 13: "TITRE", 14: "FOND_INTRO"}
# (x, y, w, h) in 320x200 space: the regions app/ui.py draws over. ui.py's
# layouts import these so the guide and the UI can never drift apart.
PORTRAIT_RECTS = ((10, 10, 140, 181), (170, 10, 140, 181))       # ui.CharacterLayout.PORTRAITS
STORY_COLUMNS = ((5, 5, 150, 189), (165, 5, 150, 189))           # AITD1.cpp Lire(...,5,5,154,194) / (165,5,314,194)
CREDITS_BOX = (48, 2, 212, 195)                                  # AITD1.cpp:159 Lire(TEXTE_CREDITS, 48,2,260,197)
READING_BOX = (60, 20, 200, 160)                                 # ui.render_reading text area
FULL_FRAME = (0, 0, 320, 200)
SCREEN_GUIDES = {
    6: (READING_BOX,),
    7: (READING_BOX, CREDITS_BOX),
    8: (READING_BOX,),
    10: PORTRAIT_RECTS,
    12: (FULL_FRAME,),
    13: (FULL_FRAME,),
    14: STORY_COLUMNS,
}
COLOR_BLIT = COLOR_COLLISION   # blue: "the engine draws over this"


def screen_rel_path(entry):
    # Must stay identical to asset_resolver.override_screen_path's tail.
    return f"screens/ress{entry:02d}.png"


def screen_guide_rel_path(entry):
    return f"guides/screens/ress{entry:02d}.png"


def screen_record(entry, pixels):
    return {
        "entry": int(entry),
        "name": SCREEN_NAMES[entry],
        "source": screen_rel_path(entry),
        "guide": screen_guide_rel_path(entry),
        "size": [int(pixels.shape[1]), int(pixels.shape[0])],
        "sha256": sha256_rgb(pixels),
        "blits": [list(r) for r in SCREEN_GUIDES[entry]],
    }


def screen_guide(pixels, entry, scale):
    """The screen upscaled x`scale` with every blit rect outlined in blue
    and the same legend footer as guide_overlay."""
    base = nearest_upscale(pixels, scale)
    h, w = base.shape[:2]
    img = np.zeros((h + GUIDE_FOOTER, w, 3), np.uint8)
    img[:h] = base
    for x, y, rw, rh in SCREEN_GUIDES[entry]:
        pts = [(x * scale, y * scale), ((x + rw - 1) * scale, y * scale),
               ((x + rw - 1) * scale, (y + rh - 1) * scale), (x * scale, (y + rh - 1) * scale)]
        draw_polyline(img, pts, COLOR_BLIT, closed=True)
    for k, color in enumerate((COLOR_MASK, COLOR_COLLISION, COLOR_WALKABLE)):
        x0 = k * _SWATCH_STRIDE
        img[h:, x0:x0 + _SWATCH_W] = color
    return img
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/test_background_export.py tests/test_regenerate_backgrounds.py tests/test_override_check.py -q`
Expected: PASS (existing tests that compare `manifest["schema"]` to `MANIFEST_SCHEMA` keep passing because they read the constant). If a test asserts the literal `1`, update it to `be.MANIFEST_SCHEMA`.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/render/background_export.py tests/test_background_export.py
git commit -m "feat: screen records, blit-rect guides and manifest v2 in background_export"
```

---

### Task 3: UI consumers read screens through the resolver

**Files:**
- Modify: `PyAitD/app/ui.py` (`CharacterLayout`, `render_character_select`, `render_reading`, `render_picture`)
- Modify: `PyAitD/app/shell.py:747-790` (`render_active_mode`)
- Test: `tests/test_ui_render.py`, `tests/test_runtime_modes.py`

**Interfaces:**
- Consumes: `AssetResolver.resource_screen(entry) -> ImageAsset` (Task 1); `background_export.PORTRAIT_RECTS` (Task 2).
- Produces:
  - `ui.screen_surface(resolver, entry) -> pygame.Surface` (320x200, override scaled with `smoothscale`).
  - `render_character_select(presenter, assets, resolver=None)`, `render_reading(effect, presenter, assets, resolver=None)`, `render_picture(effect, assets, resolver=None)` — `resolver=None` means `AssetResolver(assets, None)` (originals).
  - `shell.render_active_mode(game, session, renderer, resolver=None)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui_render.py`:

```python
from PyAitD.render.asset_resolver import AssetResolver, override_screen_path
from PyAitD.render import background_export as be


def test_character_layout_portraits_come_from_the_export_guide_rects():
    assert tuple(tuple(r) for r in CharacterLayout.PORTRAITS) == be.PORTRAIT_RECTS


def test_character_select_uses_a_screen_override_outside_the_portraits(data_dir, tmp_path):
    pygame.font.init()
    game = init_game(data_dir, AITD1)
    path = override_screen_path(tmp_path, 10)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"png")
    plate = np.zeros((400, 640, 3), np.uint8)
    plate[:, :, 1] = 255                                     # solid green at 2x
    resolver = AssetResolver(game.assets, tmp_path, load_png=lambda p: plate)
    frame = render_character_select(CharacterSelectPresenter(), game.assets, resolver)
    assert frame.shape == (200, 320, 3)
    assert tuple(frame[195, 160]) == (0, 255, 0)             # between the portraits: the override
    original = render_character_select(CharacterSelectPresenter(), game.assets)
    x, y, w, h = be.PORTRAIT_RECTS[1]
    assert (frame[y + 5:y + 20, x + 5:x + 20] == original[y + 5:y + 20, x + 5:x + 20]).all()  # unhovered portrait crop stays original


def test_reading_and_picture_accept_a_resolver(data_dir):
    pygame.font.init()
    game = init_game(data_dir, AITD1)
    resolver = AssetResolver(game.assets, None)
    a = render_reading(ReadText(1, 0), ReadingPresenter(), game.assets, resolver)
    b = render_picture(ShowPicture(10, 60, 4), game.assets, resolver)
    assert a.shape == (200, 320, 3) and b.shape == (200, 320, 3)
```

- [ ] **Step 2: Run to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_render.py -q -k "screen_override or export_guide_rects or accept_a_resolver"`
Expected: FAIL (`TypeError: render_character_select() takes 2 positional arguments`).

- [ ] **Step 3: Implement**

In `PyAitD/app/ui.py`:

Add to the imports: `from PyAitD.render.background_export import PORTRAIT_RECTS` and `from PyAitD.render.asset_resolver import AssetResolver`.

Replace `CharacterLayout.PORTRAITS`:

```python
class CharacterLayout:
    PORTRAITS = tuple(pygame.Rect(*rect) for rect in PORTRAIT_RECTS)
    PORTRAIT_HIT_ROWS = effective_rects(PORTRAITS)
    STORY = pygame.Rect(0, 0, 320, 200)
```

Add after `_to_frame`:

```python
def screen_surface(resolver, entry):
    """An ITD_RESS full-screen resource as a 320x200 surface. An override of
    any other size is smooth-scaled down/up here so every rect the callers
    blit over (portraits, text columns, cadre) stays in 320x200 space.
    ponytail: compositing at override resolution is the upgrade path."""
    asset = resolver.resource_screen(entry)
    surface = _to_surface(np.ascontiguousarray(asset.pixels))
    if surface.get_size() != (320, 200):
        surface = pygame.transform.smoothscale(surface, (320, 200))
    return surface


def _resolver_or_originals(assets, resolver):
    return resolver if resolver is not None else AssetResolver(assets, None)
```

Change `render_picture`:

```python
def render_picture(effect, assets, resolver=None):
    resolver = _resolver_or_originals(assets, resolver)
    return _to_frame(screen_surface(resolver, effect.resource_index))
```

Change `render_reading`'s first two lines:

```python
def render_reading(effect, presenter, assets, resolver=None):
    resolver = _resolver_or_originals(assets, resolver)
    surface = screen_surface(resolver, {0: 6, 1: 7, 2: 8}[effect.kind])
```

Change `render_character_select`:

```python
def render_character_select(presenter, assets, resolver=None):
    # FITD character select: resource 10 background, cadre around the hovered
    # portrait (left choice 0 = Emily hero 1, right choice 1 = Carnby hero 0);
    # STORY copies the opposite half of resource 14 plus book text 20/21.
    resolver = _resolver_or_originals(assets, resolver)
    surface = screen_surface(resolver, 10)
    base = surface.copy()
    choice = (presenter.hover if presenter.hover is not None
              and presenter.phase is CharacterPhase.PORTRAITS else presenter.choice)
    center = ((80, 100), (240, 100))[choice]
    draw_big_cadre(surface, assets.cadre_bank(), center, (160, 200))
    portrait = CharacterLayout.PORTRAITS[choice]
    surface.blit(base, portrait.topleft, portrait)
    if presenter.phase is CharacterPhase.PORTRAITS:
        return _to_frame(surface)
    intro = screen_surface(resolver, 14)
    # ... rest unchanged (the `if presenter.choice == 0:` block onward)
```

In `PyAitD/app/shell.py` `render_active_mode(game, session, renderer)` becomes `render_active_mode(game, session, renderer, resolver=None)` and passes `resolver` to `render_character_select(session.character, game.assets, resolver)`, `render_reading(effect, session.reading, game.assets, resolver)`, `render_picture(effect, game.assets, resolver)`. In `run()`, change the call to `render_active_mode(game, session, renderer, resolver)`.

- [ ] **Step 4: Run tests**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_render.py tests/test_runtime_modes.py tests/test_shell_journeys.py tests/test_layering.py -q`
Expected: PASS. `test_layering` still passes because `app/` may import everything.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/app/ui.py PyAitD/app/shell.py tests/test_ui_render.py
git commit -m "feat: character select, reading and picture screens load through AssetResolver"
```

---

### Task 4: Export tool writes screens

**Files:**
- Modify: `tools/export_backgrounds.py`
- Test: `tests/test_regenerate_backgrounds.py` (export round-trip tests live there alongside `xb`) — add a new file `tests/test_export_screens.py`

**Interfaces:**
- Consumes: Task 2 names.
- Produces: `export_screens(assets, out_dir, guide_scale, save=save_png) -> list[dict]`; CLI `--screens/--no-screens` (default on); `main` refuses when `DIR/screens` exists without `--force`; `_merge_manifest_records(out_dir, new_records, key="cameras")` generalised so screens merge too (`key="screens"`, keyed by `entry`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_export_screens.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
import json
import os
from types import SimpleNamespace
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np

from PyAitD.render import background_export as be
from tools import export_backgrounds as xb


def _assets():
    plates = {e: np.full((200, 320, 3), e, np.uint8) for e in be.SCREEN_ENTRIES}
    return SimpleNamespace(resource_screen=lambda e: plates[e])


def test_export_screens_writes_plate_guide_and_records(tmp_path):
    saved = {}
    records = xb.export_screens(_assets(), tmp_path, 2, save=lambda p, rgb: saved.__setitem__(p, rgb.shape))
    assert [r["entry"] for r in records] == list(be.SCREEN_ENTRIES)
    assert saved[tmp_path / "screens" / "ress10.png"] == (200, 320, 3)
    assert saved[tmp_path / "guides" / "screens" / "ress10.png"] == (400 + be.GUIDE_FOOTER, 640, 3)


def test_merge_keeps_other_kinds_records(tmp_path):
    manifest = be.export_manifest([{"floor": 0, "camera": 0, "sha256": "a"}], "/d", 4,
                                  screens=[{"entry": 10, "sha256": "s"}])
    xb.save_manifest(tmp_path, manifest)
    cams = xb._merge_manifest_records(tmp_path, [{"floor": 1, "camera": 0, "sha256": "b"}])
    assert {(c["floor"], c["camera"]) for c in cams} == {(0, 0), (1, 0)}
    screens = xb._merge_manifest_records(tmp_path, [{"entry": 13, "sha256": "t"}], key="screens")
    assert {s["entry"] for s in screens} == {10, 13}


def test_main_refuses_existing_screens_without_force(tmp_path, monkeypatch):
    (tmp_path / "out" / "screens").mkdir(parents=True)
    assert xb.main([str(tmp_path), "--out", str(tmp_path / "out")]) == 3


def test_main_exports_screens_and_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(xb, "load_floor", lambda data, n: (_ for _ in ()).throw(FileNotFoundError("no floor")))
    monkeypatch.setattr(xb, "load_assets", lambda data: _assets())
    monkeypatch.setattr(xb, "save_png", lambda p, rgb: (p.parent.mkdir(parents=True, exist_ok=True), p.write_bytes(b"png")))
    out = tmp_path / "out"
    assert xb.main([str(tmp_path), "--out", str(out), "--floors", "0"]) == 0
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["schema"] == 2 and manifest["cameras"] == []
    assert [s["entry"] for s in manifest["screens"]] == list(be.SCREEN_ENTRIES)
    assert (out / "screens" / "ress13.png").is_file()
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_export_screens.py -q`
Expected: FAIL — `AttributeError: ... has no attribute 'export_screens'`.

- [ ] **Step 3: Implement**

In `tools/export_backgrounds.py`:

Extend the docstring's file list with `screens/ressNN.png` and `guides/screens/ressNN.png`.

Imports: add `SCREEN_ENTRIES, screen_guide, screen_guide_rel_path, screen_record, screen_rel_path` to the `background_export` import; add `from PyAitD.engine.assets import Assets` and `from PyAitD.games import load_profile`.

Add after `load_floor`:

```python
def load_assets(data_dir):
    return Assets(data_dir, load_profile("aitd1"))
```

Generalise the merge:

```python
def _merge_manifest_records(out_dir, new_records, key="cameras"):
    """Merge `new_records` over out_dir/manifest.json's existing `key` list
    (cameras keyed by (floor, camera), screens by entry), new records
    winning, so a --force re-export of a subset does not lose the rest."""
    def ident(rec):
        return rec["entry"] if key == "screens" else (rec["floor"], rec["camera"])
    manifest_path = pathlib.Path(out_dir) / "manifest.json"
    if not manifest_path.is_file():
        return list(new_records)
    try:
        existing = json.loads(manifest_path.read_text())
    except (OSError, ValueError):
        return list(new_records)
    if not isinstance(existing, dict) or existing.get("schema") not in SUPPORTED_SCHEMAS:
        return list(new_records)
    merged = {ident(c): c for c in existing.get(key, [])}
    for rec in new_records:
        merged[ident(rec)] = rec
    return list(merged.values())
```

(import `SUPPORTED_SCHEMAS` alongside `MANIFEST_SCHEMA`.)

Add:

```python
def export_screens(assets, out_dir, guide_scale, save=save_png):
    out_dir = pathlib.Path(out_dir)
    records = []
    for entry in SCREEN_ENTRIES:
        pixels = assets.resource_screen(entry)
        save(out_dir / screen_rel_path(entry), pixels)
        save(out_dir / screen_guide_rel_path(entry), screen_guide(pixels, entry, guide_scale))
        records.append(screen_record(entry, pixels))
    return records
```

In `_parse_args` add:

```python
    p.add_argument("--screens", action=argparse.BooleanOptionalAction, default=True,
                    help="also export the ITD_RESS full-screen resources (default on)")
```

In `main`: the refusal check becomes

```python
    for sub in ("backgrounds", "screens"):
        if (args.out / sub).exists() and not args.force:
            print(f"error: {args.out / sub} exists; pass --force to overwrite "
                  "(this discards regenerated images)", file=sys.stderr)
            return 3
```

After the floor loop, replace the `if not exported:` block and manifest assembly with:

```python
    screens = []
    if args.screens:
        try:
            screens = export_screens(load_assets(args.data), args.out, args.guide_scale)
            print(f"screens: {len(screens)}")
        except (PakError, FileNotFoundError, OSError, ValueError) as exc:
            print(f"warning: screens skipped: {exc}", file=sys.stderr)
    if not exported and not screens:
        print("error: nothing exported", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    records = _merge_manifest_records(args.out, records)
    screens = _merge_manifest_records(args.out, screens, key="screens")
    manifest = export_manifest(records, args.data.resolve(), args.guide_scale, screens=screens)
    print(save_manifest(args.out, manifest))
    return 0
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/test_export_screens.py tests/test_regenerate_backgrounds.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/export_backgrounds.py tests/test_export_screens.py
git commit -m "feat: export-backgrounds writes ITD_RESS screens, guides and manifest v2"
```

---

### Task 5: Check and regenerate learn the screens kind

**Files:**
- Modify: `PyAitD/render/override_check.py`, `tools/check_overrides.py`, `tools/regenerate_backgrounds.py`
- Test: `tests/test_override_check.py`, `tests/test_regenerate_backgrounds.py`

**Interfaces:**
- Produces:
  - `override_check.check_screens(override_dir, assets, *, load_png) -> list[Finding]` (`Finding.floor = -1`, `Finding.camera = entry`, `Finding.kind` in `missing|invalid|aspect|size`).
  - `override_check.screen_coverage(override_dir, assets, manifest, *, load_png) -> dict` with keys `regenerated, original, missing, invalid`.
  - `summarize(findings, cov, screen_cov=None)` prints a `screens: ...` line when given.
  - `check_overrides.render_screen_proof(assets, entry, override_dir, out_dir, save=save_png) -> Path | None` (original | override side by side, no GL).
  - `regenerate_backgrounds.discover` also yields `Camera(floor=-1, camera=entry, source=IN/screens/ressNN.png, guide=IN/guides/screens/ressNN.png|None, key="screens/ressNN")` when `--screens` (new `screens=True` parameter); `regenerate` writes screen targets to `out_dir / f"{key}.png"` (already `key`-based — verify) and its prompts use `_SCREEN_GENERATE` when `cam.floor == -1`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_override_check.py`:

```python
from types import SimpleNamespace
from PyAitD.render.asset_resolver import override_screen_path
from PyAitD.render.background_export import SCREEN_ENTRIES, export_manifest, screen_record, sha256_rgb


def _screen_assets():
    plates = {e: np.full((200, 320, 3), e, np.uint8) for e in SCREEN_ENTRIES}
    return SimpleNamespace(resource_screen=lambda e: plates[e]), plates


def test_check_screens_reports_missing_invalid_and_aspect(tmp_path):
    assets, _ = _screen_assets()
    bad = override_screen_path(tmp_path, 10); bad.parent.mkdir(parents=True); bad.write_bytes(b"x")
    wide = override_screen_path(tmp_path, 13); wide.write_bytes(b"x")
    images = {bad: np.zeros((2, 2), np.uint8), wide: np.zeros((200, 640, 3), np.uint8)}
    findings = oc.check_screens(tmp_path, assets, load_png=lambda p: images[p])
    by_entry = {f.camera: f.kind for f in findings}
    assert by_entry[10] == "invalid" and by_entry[13] == "aspect" and by_entry[6] == "missing"
    assert all(f.floor == -1 for f in findings)


def test_screen_coverage_distinguishes_original_from_regenerated(tmp_path):
    assets, plates = _screen_assets()
    manifest = export_manifest([], "/d", 4, screens=[screen_record(e, plates[e]) for e in SCREEN_ENTRIES])
    same = override_screen_path(tmp_path, 10); same.parent.mkdir(parents=True); same.write_bytes(b"x")
    new = override_screen_path(tmp_path, 14); new.write_bytes(b"x")
    images = {same: plates[10], new: np.ones((200, 320, 3), np.uint8)}
    cov = oc.screen_coverage(tmp_path, assets, manifest, load_png=lambda p: images[p])
    assert cov == {"regenerated": 1, "original": 1, "missing": 5, "invalid": 0}
    text = oc.summarize([], {}, cov)
    assert "screens: regenerated 1 / original 1 / missing 5 / invalid 0" in text
```

Append to `tests/test_regenerate_backgrounds.py`:

```python
def test_discover_includes_screens_after_cameras(tmp_path):
    in_dir = make_in_dir(tmp_path)
    xb.save_png(in_dir / "screens" / "ress10.png", checker_pixels(1))
    xb.save_png(in_dir / "guides" / "screens" / "ress10.png", np.zeros((412, 640, 3), np.uint8))
    xb.save_png(in_dir / "screens" / "ress13.png", checker_pixels(2))
    items = rb.discover(in_dir, None)
    assert [c.key for c in items][-2:] == ["screens/ress10", "screens/ress13"]
    assert items[-2].floor == -1 and items[-2].camera == 10
    assert items[-2].guide == in_dir / "guides" / "screens" / "ress10.png" and items[-1].guide is None
    assert all(c.floor >= 0 for c in rb.discover(in_dir, None, screens=False))


def test_screen_prompts_ask_for_plain_blit_regions():
    cam = rb.Camera(-1, 10, pathlib.Path("s.png"), pathlib.Path("g.png"), "screens/ress10")
    text = rb.generation_prompt("a hall", "", True, screen=True)
    assert "blue" in text and "drawn there by the game" in text
    assert "walkable" not in text
```

(`import pathlib` at the top of that test file if missing.)

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_override_check.py tests/test_regenerate_backgrounds.py -q`
Expected: FAIL on the new tests only.

- [ ] **Step 3: Implement `override_check`**

Add to the imports: `override_screen_path` and `from PyAitD.render.background_export import SCREEN_ENTRIES, sha256_rgb`.

Append:

```python
def _each_screen(override_dir, assets, load_png):
    resolver = AssetResolver(assets, override_dir, load_png=load_png)
    for entry in SCREEN_ENTRIES:
        yield entry, override_screen_path(override_dir, entry), resolver


def check_screens(override_dir, assets, *, load_png=load_png_rgb):
    """At most one Finding per screen; `floor` is -1, `camera` is the entry."""
    findings = []
    for entry, path, resolver in _each_screen(override_dir, assets, load_png):
        if not path.is_file():
            findings.append(Finding(-1, entry, path, "missing", "original will be used"))
            continue
        asset = resolver.resource_screen(entry)
        if not asset.is_override:
            findings.append(Finding(-1, entry, path, "invalid", resolver.failures.get(path, "rejected")))
            continue
        h, w = asset.pixels.shape[:2]
        if abs(w / h - _ASPECT) > _ASPECT * _ASPECT_TOL:
            findings.append(Finding(-1, entry, path, "aspect",
                                    f"{w}x{h} is not 16:10 within 1% -- the game would stretch it"))
            continue
        if w < 320 or h < 200 or w % 320 or h % 200:
            findings.append(Finding(-1, entry, path, "size",
                                    f"{w}x{h} is not an integer multiple of 320x200"))
    return findings


def screen_coverage(override_dir, assets, manifest, *, load_png=load_png_rgb):
    expected = {s["entry"]: s["sha256"] for s in manifest.get("screens", [])}
    counts = {"regenerated": 0, "original": 0, "missing": 0, "invalid": 0}
    for entry, path, resolver in _each_screen(override_dir, assets, load_png):
        if not path.is_file():
            counts["missing"] += 1
            continue
        asset = resolver.resource_screen(entry)
        if not asset.is_override:
            counts["invalid"] += 1
        elif sha256_rgb(asset.pixels) == expected.get(entry):
            counts["original"] += 1
        else:
            counts["regenerated"] += 1
    return counts
```

Change `summarize(findings, cov)` to `summarize(findings, cov, screen_cov=None)`; its finding line prints `screen ress{f.camera:02d}` instead of `floor .. camera ..` when `f.floor == -1`; before the final `return`, add:

```python
    if screen_cov is not None:
        lines.append("screens: " + " / ".join(f"{k} {screen_cov[k]}" for k in ("regenerated", "original", "missing", "invalid")))
```

- [ ] **Step 4: Implement `tools/check_overrides.py`**

Imports: `from PyAitD.render.override_check import check_overrides, check_screens, coverage, has_errors, screen_coverage, summarize`, `from PyAitD.render.background_export import SCREEN_ENTRIES, SUPPORTED_SCHEMAS`, and `from tools.export_backgrounds import load_assets, load_floor, parse_floors, save_png`.

Manifest validation: `manifest.get("schema") not in SUPPORTED_SCHEMAS`.

Add:

```python
def render_screen_proof(assets, entry, override_dir, out_dir, save=save_png):
    """original | override for one screen, both fitted to 320x200 x4 by
    nearest repeat (no GL needed)."""
    from PyAitD.render.background_export import nearest_upscale
    resolver = AssetResolver(assets, override_dir)
    override = resolver.resource_screen(entry)
    if not override.is_override:
        return None
    left = nearest_upscale(assets.resource_screen(entry), 4)
    right = override.pixels
    if right.shape[:2] != left.shape[:2]:
        import pygame
        surface = pygame.surfarray.make_surface(np.ascontiguousarray(right.swapaxes(0, 1)))
        surface = pygame.transform.smoothscale(surface, (left.shape[1], left.shape[0]))
        right = np.ascontiguousarray(pygame.surfarray.array3d(surface).swapaxes(0, 1))
    path = pathlib.Path(out_dir) / f"screen-ress{entry:02d}.png"
    save(path, np.concatenate([left, right], axis=1))
    return path
```

In `main`, after the floors loop:

```python
    assets = load_assets(args.data)
    findings = check_overrides(args.overrides, floors, manifest) + check_screens(args.overrides, assets)
    cov = coverage(args.overrides, floors, manifest) if manifest is not None else None
    screen_cov = screen_coverage(args.overrides, assets, manifest) if manifest is not None else None
    print(summarize(findings, cov, screen_cov))
```

and inside the proof branch, after the floor loop: `for entry in SCREEN_ENTRIES: path = render_screen_proof(assets, entry, args.overrides, args.proof); if path is not None: print(path)` (screen proofs do not need `ctx`; run them before the `create_context()` try so a missing GL context still produces them).

- [ ] **Step 5: Implement `tools/regenerate_backgrounds.py`**

Add `_SCREEN_RE = re.compile(r"screens/ress(\d\d)\.png$")` and change `discover`:

```python
def discover(in_dir, floors, screens=True):
    """Every IN/backgrounds/floorNN/cameraNNN.png, sorted, restricted to
    `floors` (None = all); then every IN/screens/ressNN.png (floor -1,
    camera = entry) when `screens`. Guide path only when the file exists."""
    in_dir = pathlib.Path(in_dir)
    cams = []
    for path in sorted((in_dir / "backgrounds").glob("floor[0-9][0-9]/camera[0-9][0-9][0-9].png")):
        m = _CAMERA_RE.search(path.as_posix())
        floor, cam = int(m.group(1)), int(m.group(2))
        if floors is not None and floor not in floors:
            continue
        key = f"floor{floor:02d}/camera{cam:03d}"
        guide = in_dir / "guides" / f"{key}.png"
        cams.append(Camera(floor, cam, path, guide if guide.is_file() else None, key))
    if screens:
        for path in sorted((in_dir / "screens").glob("ress[0-9][0-9].png")):
            entry = int(_SCREEN_RE.search(path.as_posix()).group(1))
            key = f"screens/ress{entry:02d}"
            guide = in_dir / "guides" / f"{key}.png"
            cams.append(Camera(-1, entry, path, guide if guide.is_file() else None, key))
    return cams
```

Add prompts:

```python
_SCREEN_DESCRIBE = ("The second image outlines in blue the regions where the game later draws "
                    "text or portraits; describe the artwork so those regions stay plain and "
                    "uncluttered." + _GUIDE_LEGEND_NOTE)
_SCREEN_GENERATE = ("The second image outlines in blue the regions where text and portraits are "
                    "drawn there by the game: keep those areas plain, without text, and do not "
                    "draw the blue lines." + _GUIDE_LEGEND_NOTE)
```

`describe_prompt(guide_present, screen=False)` appends `_SCREEN_DESCRIBE` instead of `_GUIDE_DESCRIBE` when `screen`; `generation_prompt(description, style, guide_present, screen=False)` uses `_SCREEN_GENERATE` when `screen` and starts with "Recreate the first image as a painted illustration of the same composition, keeping the framing and every element's placement. " instead of the photograph sentence. `describe(model, cam)` and the `regenerate` loop pass `screen=cam.floor == -1`. In `regenerate`, the target path is `out_dir / ("backgrounds" if cam.floor >= 0 else "") / f"{cam.key}.png"` → write it as:

```python
        target = out_dir / (f"backgrounds/{cam.key}.png" if cam.floor >= 0 else f"{cam.key}.png")
```

`_parse_args` gains `--screens` (`argparse.BooleanOptionalAction`, default True); `main` passes `screens=args.screens` to `discover`.

- [ ] **Step 6: Run tests**

Run: `.venv/bin/pytest tests/test_override_check.py tests/test_regenerate_backgrounds.py tests/test_layering.py -q`
Expected: PASS (the layering test still finds only `subprocess` in the regeneration tool).

- [ ] **Step 7: Commit**

```bash
git add PyAitD/render/override_check.py tools/check_overrides.py tools/regenerate_backgrounds.py tests/test_override_check.py tests/test_regenerate_backgrounds.py
git commit -m "feat: check-overrides and regenerate-backgrounds handle ITD_RESS screens"
```

---

### Task 6: Makefile knob, docs, real-data smoke

**Files:**
- Modify: `Makefile:371-378`, `docs/ai-background-regeneration.md`, `AGENTS.md` (Commands + AI background regeneration bullets), `CONTEXT.md` ("AI background regeneration boundary")
- Test: `tests/test_export_screens.py` (one real-data test)

- [ ] **Step 1: Write the real-data test**

Append to `tests/test_export_screens.py`:

```python
def test_real_screens_export_and_check_round_trip(data_dir, tmp_path):
    from PyAitD.render import override_check as oc
    from tools.export_backgrounds import load_assets
    assets = load_assets(data_dir)
    records = xb.export_screens(assets, tmp_path, 1)
    assert len(records) == 7 and all(r["size"] == [320, 200] for r in records)
    findings = oc.check_screens(tmp_path, assets)
    assert findings == []            # every exported original loads and is 320x200
    cov = oc.screen_coverage(tmp_path, assets, be.export_manifest([], data_dir, 1, screens=records))
    assert cov == {"regenerated": 0, "original": 7, "missing": 0, "invalid": 0}
```

- [ ] **Step 2: Run it**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_export_screens.py -q`
Expected: PASS (or SKIP without game data).

- [ ] **Step 3: Makefile and docs**

Makefile `export-backgrounds` line: append ` $(if $(screens),,--no-screens)` guarded the other way round — use:

```make
export-backgrounds: install ## Export every camera background + ITD_RESS screen + guides + manifest for external AI regeneration (out=data/aitd1/overrides, floors=0-7, scale=4, force=1, screens=0 to skip screens)
	$(PYTHON) tools/export_backgrounds.py "$(data)" --out "$(out)" --floors "$(or $(floors),0-7)" --guide-scale "$(or $(scale),4)" $(if $(force),--force) $(if $(filter 0,$(screens)),--no-screens)
```

Same `$(if $(filter 0,$(screens)),--no-screens)` on `regenerate-backgrounds`.

`docs/ai-background-regeneration.md`: in section 1's output listing add `screens/ressNN.png` and `guides/screens/ressNN.png`; add a subsection "Screens" after 2b:

> The seven full-screen ITD_RESS images (6 letter, 7 book/credits, 8 notebook, 10 character portraits, 12 dead end, 13 title, 14 story) export to `screens/ressNN.png`. Their guides outline in blue the regions the game draws over (portrait crops, text columns, cadre): keep those areas plain. Any size loads; non-320x200 overrides are scaled to 320x200 when composited, so text stays aligned. `check-overrides` lists them as `screen ressNN` and reports a `screens:` coverage line; `proof=1` writes `screen-ressNN.png` side-by-sides. `make export-backgrounds screens=0` / `regenerate-backgrounds screens=0` skip them.

`AGENTS.md`: `make export-backgrounds` line mentions screens; the "AI background regeneration" convention bullet: "The export directory layout is `render/asset_resolver.override_background_path`'s and `override_screen_path`'s — change both or neither." `CONTEXT.md` boundary: add "`screens/ressNN.png` overrides full-screen resources; `app/ui.screen_surface` scales them to 320x200 at composite time."

- [ ] **Step 4: Full suite**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest -q && make prove`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add Makefile docs/ai-background-regeneration.md AGENTS.md CONTEXT.md tests/test_export_screens.py
git commit -m "docs: screen overrides in the AI regeneration workflow; screens= knob"
```
