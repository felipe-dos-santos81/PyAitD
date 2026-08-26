# Gemini Background Regeneration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A repo tool that turns `./overrides` (originals + guides + manifest) into `./overrides-ai` by asking Gemini to describe each background and then render a photorealistic 1280×800 version, resumable and reviewable per camera.

**Architecture:** One module `tools/regenerate_backgrounds.py` with pure helpers (discover, prompts, prompt cache, fit-to-target) and two thin client-facing functions (`describe`, `generate`) whose `client` is duck-typed so tests inject a fake. `google-genai` is imported lazily in `make_client` only. Post-processing uses pygame + numpy; PNG writing reuses `tools/export_backgrounds.save_png`.

**Tech Stack:** Python 3.12, pygame-ce, NumPy, pytest; `google-genai>=1.0` as the optional extra `ai`.

**Spec:** `docs/superpowers/specs/2026-08-25-gemini-background-regeneration-design.md`

## Global Constraints

- `# SPDX-License-Identifier: GPL-2.0-only` first line of every Python file.
- Engine modules untouched: `asset_resolver.py`, `render_*.py`, `scene.py`, `floor.py`, `__main__.py`, `background_export.py`, `override_check.py` do not change.
- `google-genai` is imported only inside `tools/regenerate_backgrounds.py`, lazily, in one function (`make_client`). Importing the module without the SDK installed succeeds; a real run without it prints exactly `google-genai is not installed: run .venv/bin/pip install -e ".[dev,ai]"` and exits 2.
- No Pillow. Decoding/crop/scale/encode via pygame + numpy + `tools/export_backgrounds.save_png`.
- Unit suite never touches the network; the live test is skipped unless both `GEMINI_API_KEY` and `PYAITD_LIVE_AI=1` are set.
- `overrides-ai/` is git-ignored; no game data or generated art is committed.
- API key only from `GEMINI_API_KEY`; never logged.
- Any test touching pygame sets `SDL_VIDEODRIVER=dummy` (put `os.environ.setdefault("SDL_VIDEODRIVER", "dummy")` before importing pygame, as `tests/test_tools_graphics_cli.py` does).
- Never mass-reformat. Test suite is the only gate: `.venv/bin/pytest -q`.
- Contents and config passed to the client are plain dicts (`{"inline_data": {"mime_type": ..., "data": ...}}`, `{"response_modalities": ["IMAGE"], "image_config": {"aspect_ratio": "3:2"}}`) — the SDK accepts dict forms, and it keeps the module free of SDK imports.

**Plan deviation from spec (ruled here):** `fit_to_target` returns a `(800, 1280, 3)` uint8 ndarray, not a `pygame.Surface`, because `save_png(path, rgb)` takes an ndarray.

---

### Task 1: Scaffold, discovery, prompt text, prompt cache

**Files:**
- Create: `tools/regenerate_backgrounds.py`
- Create: `tests/test_regenerate_backgrounds.py`
- Modify: `pyproject.toml` (optional-dependencies)
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `tools/export_backgrounds.save_png(path, rgb)`, `tests/stub_floor.checker_pixels(seed)`.
- Produces: `Camera` dataclass, `discover(in_dir, floors) -> list[Camera]`, `describe_prompt(guide_present) -> str`, `generation_prompt(description, style, guide_present) -> str`, `load_prompts(path) -> dict`, `save_prompts(path, prompts)`, constants `DEFAULT_TEXT_MODEL`, `DEFAULT_IMAGE_MODEL`, `DEFAULT_STYLE`, `TARGET_SIZE`, `GENERATE_ASPECT`, `PROMPTS_FILE`.

- [ ] **Step 1: Add the extra and the ignore entry**

`pyproject.toml`:
```toml
[project.optional-dependencies]
dev = ["pytest>=8"]
ai = ["google-genai>=1.0"]
```
`.gitignore`: append a line `overrides-ai/`.

- [ ] **Step 2: Write the failing tests**

`tests/test_regenerate_backgrounds.py`:
```python
# SPDX-License-Identifier: GPL-2.0-only
import io
import json
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pytest

from tests.stub_floor import checker_pixels
from tools import export_backgrounds as xb
from tools import regenerate_backgrounds as rb


def make_in_dir(root):
    """floor00: camera000 (with guide), camera001 (no guide); floor01: camera000 (with guide)."""
    in_dir = root / "in"
    for key, guide in (("floor00/camera000", True), ("floor00/camera001", False), ("floor01/camera000", True)):
        xb.save_png(in_dir / "backgrounds" / f"{key}.png", checker_pixels(hash(key) % 100))
        if guide:
            xb.save_png(in_dir / "guides" / f"{key}.png", np.zeros((812, 1280, 3), np.uint8))
    return in_dir


def test_discover_lists_cameras_sorted_with_optional_guides(tmp_path):
    in_dir = make_in_dir(tmp_path)
    cams = rb.discover(in_dir, None)
    assert [c.key for c in cams] == ["floor00/camera000", "floor00/camera001", "floor01/camera000"]
    assert cams[0].floor == 0 and cams[0].camera == 0
    assert cams[0].guide == in_dir / "guides/floor00/camera000.png"
    assert cams[1].guide is None
    assert cams[2].source == in_dir / "backgrounds/floor01/camera000.png"


def test_discover_filters_floors_and_handles_missing_dir(tmp_path):
    in_dir = make_in_dir(tmp_path)
    assert [c.key for c in rb.discover(in_dir, {1})] == ["floor01/camera000"]
    assert rb.discover(tmp_path / "nowhere", None) == []


def test_prompts_mention_guide_only_when_present():
    assert "second image" in rb.describe_prompt(True)
    assert "second image" not in rb.describe_prompt(False)
    g = rb.generation_prompt("a dusty attic", "film grain.", True)
    assert "a dusty attic" in g and g.endswith("film grain.") and "second image" in g
    assert "second image" not in rb.generation_prompt("x", "s", False)


def test_prompt_cache_round_trip_is_atomic(tmp_path):
    path = tmp_path / rb.PROMPTS_FILE
    assert rb.load_prompts(path) == {}
    rb.save_prompts(path, {"floor00/camera000": {"prompt": "p", "model": "m", "sha256": "s"}})
    assert rb.load_prompts(path)["floor00/camera000"]["prompt"] == "p"
    assert sorted(p.name for p in tmp_path.iterdir()) == [rb.PROMPTS_FILE]
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/pytest tests/test_regenerate_backgrounds.py -q`
Expected: ImportError / AttributeError on `rb`.

- [ ] **Step 4: Implement**

`tools/regenerate_backgrounds.py`:
```python
# SPDX-License-Identifier: GPL-2.0-only
"""Regenerate exported backgrounds with Gemini: describe each plate with a
text model, render the description with an image model using the original
and its guide as references, fit to 1280x800 and write an override dir.

google-genai is imported only in make_client(); everything else runs
without it so tests use a fake client. See
docs/superpowers/specs/2026-08-25-gemini-background-regeneration-design.md."""
import argparse
import dataclasses
import hashlib
import json
import os
import pathlib
import re
import shutil
import sys

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from tools.export_backgrounds import parse_floors, save_png  # noqa: E402

DEFAULT_TEXT_MODEL = "gemini-2.5-flash"
DEFAULT_IMAGE_MODEL = "gemini-2.5-flash-image"
DEFAULT_STYLE = "Dark 1920s Louisiana mansion, moody film lighting, subtle grain."
TARGET_SIZE = (1280, 800)   # 4 x 320x200
GENERATE_ASPECT = "3:2"     # nearest Gemini ratio wider than 16:10; cropped after
PROMPTS_FILE = "prompts.json"
_SDK_MISSING = 'google-genai is not installed: run .venv/bin/pip install -e ".[dev,ai]"'
_CAMERA_RE = re.compile(r"floor(\d\d)/camera(\d\d\d)\.png$")


@dataclasses.dataclass(frozen=True)
class Camera:
    floor: int
    camera: int
    source: pathlib.Path
    guide: pathlib.Path | None
    key: str


def discover(in_dir, floors):
    """Every IN/backgrounds/floorNN/cameraNNN.png, sorted, restricted to
    `floors` (None = all); guide path only when the file exists."""
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
    return cams


_GUIDE_DESCRIBE = ("The second image is the same frame with an overlay: red outlines mark "
                   "foreground objects that must stay in front, blue boxes mark walls and solid "
                   "furniture, green polygons mark walkable floor. Describe the scene so those "
                   "structures keep their places.")
_GUIDE_GENERATE = ("The second image marks the layout: red outlines are foreground objects, blue "
                   "boxes are walls and solid furniture, green polygons are walkable floor; keep "
                   "all of them where they are and do not draw the coloured lines.")


def describe_prompt(guide_present):
    text = ("Describe this 320x200 pixel-art background from a 1992 adventure game as a "
            "single-paragraph prompt for a photorealistic image generator. Name the room type, "
            "the camera angle and height, every piece of furniture and architecture with its "
            "position in frame, the light sources and their direction, materials and colours, "
            "and the mood. Do not mention pixel art, the game, or resolution. Output only the prompt.")
    return text + (" " + _GUIDE_DESCRIBE if guide_present else "")


def generation_prompt(description, style, guide_present):
    text = ("Recreate the first image as a photorealistic photograph of the same scene, keeping "
            "the exact camera position, framing, perspective and the placement of every wall, "
            "door, window, stair and piece of furniture. ")
    if guide_present:
        text += _GUIDE_GENERATE + " "
    return text + description.strip() + " " + style


def load_prompts(path):
    path = pathlib.Path(path)
    return json.loads(path.read_text()) if path.is_file() else {}


def save_prompts(path, prompts):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(prompts, indent=1, sort_keys=True))
    os.replace(tmp, path)
```

- [ ] **Step 5: Run tests, commit**

Run: `.venv/bin/pytest tests/test_regenerate_backgrounds.py -q` → 4 passed.
```bash
git add pyproject.toml .gitignore tools/regenerate_backgrounds.py tests/test_regenerate_backgrounds.py
git commit -m "feat: scaffold Gemini background regeneration tool (discover, prompts, cache)"
```

---

### Task 2: `describe` and `generate` against a duck-typed client

**Files:**
- Modify: `tools/regenerate_backgrounds.py`
- Modify: `tests/test_regenerate_backgrounds.py`

**Interfaces:**
- Consumes: `Camera`, `describe_prompt`, `generation_prompt` (Task 1).
- Produces: `image_part(path) -> dict`, `describe(client, model, cam) -> str`, `generate(client, model, cam, prompt) -> bytes`, `FakeClient`/`png_bytes` test helpers reused by Task 3.

- [ ] **Step 1: Write the failing tests** (append to the test file)

```python
import types as _t


def png_bytes(rgb):
    import pygame
    surf = pygame.surfarray.make_surface(np.ascontiguousarray(rgb.swapaxes(0, 1)))
    buf = io.BytesIO()
    pygame.image.save(surf, buf, "png")
    return buf.getvalue()


def _response(text=None, image=None, mime="image/png"):
    if image is None:
        part = _t.SimpleNamespace(inline_data=None, text=text)
    else:
        part = _t.SimpleNamespace(inline_data=_t.SimpleNamespace(data=image, mime_type=mime), text=None)
    return _t.SimpleNamespace(text=text, candidates=[_t.SimpleNamespace(content=_t.SimpleNamespace(parts=[part]))])


class FakeClient:
    """Records calls; image models return `image_png`, text models a fixed
    description. The Nth image call (1-based) in `fail_image_calls` raises."""

    def __init__(self, image_png=None, fail_image_calls=(), no_image=False):
        self.image_png = image_png
        self.fail = set(fail_image_calls)
        self.no_image = no_image
        self.calls = []
        self.image_calls = 0
        self.models = self

    def generate_content(self, *, model, contents, config=None):
        self.calls.append((model, contents, config))
        if "image" in model:
            self.image_calls += 1
            if self.image_calls in self.fail:
                raise RuntimeError("quota")
            if self.no_image:
                return _response(text="sorry")
            return _response(image=self.image_png)
        return _response(text="  a dusty attic under sloped rafters  ")


def test_describe_sends_source_guide_and_prompt(tmp_path):
    in_dir = make_in_dir(tmp_path)
    cam = rb.discover(in_dir, None)[0]
    client = FakeClient()
    assert rb.describe(client, "gemini-2.5-flash", cam) == "a dusty attic under sloped rafters"
    model, contents, config = client.calls[0]
    assert model == "gemini-2.5-flash"
    assert contents[0] == {"inline_data": {"mime_type": "image/png", "data": cam.source.read_bytes()}}
    assert contents[1] == {"inline_data": {"mime_type": "image/png", "data": cam.guide.read_bytes()}}
    assert contents[2] == rb.describe_prompt(True)


def test_describe_without_guide_sends_two_parts(tmp_path):
    cam = rb.discover(make_in_dir(tmp_path), None)[1]
    client = FakeClient()
    rb.describe(client, "gemini-2.5-flash", cam)
    contents = client.calls[0][1]
    assert len(contents) == 2 and contents[1] == rb.describe_prompt(False)


def test_generate_requests_image_and_returns_first_image_part(tmp_path):
    cam = rb.discover(make_in_dir(tmp_path), None)[0]
    png = png_bytes(np.zeros((1024, 1536, 3), np.uint8))
    client = FakeClient(png)
    assert rb.generate(client, "gemini-2.5-flash-image", cam, "desc") == png
    model, contents, config = client.calls[0]
    assert config == {"response_modalities": ["IMAGE"], "image_config": {"aspect_ratio": "3:2"}}
    assert contents[2] == "desc"


def test_generate_without_image_part_raises(tmp_path):
    cam = rb.discover(make_in_dir(tmp_path), None)[0]
    with pytest.raises(RuntimeError, match="no image in response"):
        rb.generate(FakeClient(no_image=True), "gemini-2.5-flash-image", cam, "desc")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_regenerate_backgrounds.py -q` → 4 fail with AttributeError.

- [ ] **Step 3: Implement** (append after `save_prompts`)

```python
def image_part(path):
    return {"inline_data": {"mime_type": "image/png", "data": pathlib.Path(path).read_bytes()}}


def _reference_parts(cam):
    parts = [image_part(cam.source)]
    if cam.guide is not None:
        parts.append(image_part(cam.guide))
    return parts


def describe(client, model, cam):
    """One text-model call: original (+ guide) -> scene prompt."""
    contents = _reference_parts(cam) + [describe_prompt(cam.guide is not None)]
    response = client.models.generate_content(model=model, contents=contents)
    return (response.text or "").strip()


def generate(client, model, cam, prompt):
    """One image-model call: original (+ guide) + prompt -> image bytes.
    `prompt` is the full generation prompt (caller composes it)."""
    contents = _reference_parts(cam) + [prompt]
    config = {"response_modalities": ["IMAGE"], "image_config": {"aspect_ratio": GENERATE_ASPECT}}
    response = client.models.generate_content(model=model, contents=contents, config=config)
    for candidate in response.candidates or ():
        for part in candidate.content.parts or ():
            data = getattr(part, "inline_data", None)
            if data is not None and (data.mime_type or "").startswith("image/"):
                return data.data
    raise RuntimeError("no image in response")
```

- [ ] **Step 4: Run tests, commit**

Run: `.venv/bin/pytest tests/test_regenerate_backgrounds.py -q` → 8 passed.
```bash
git add tools/regenerate_backgrounds.py tests/test_regenerate_backgrounds.py
git commit -m "feat: describe/generate calls for background regeneration with duck-typed client"
```

---

### Task 3: `fit_to_target` and the `regenerate` orchestrator

**Files:**
- Modify: `tools/regenerate_backgrounds.py`
- Modify: `tests/test_regenerate_backgrounds.py`

**Interfaces:**
- Consumes: Tasks 1–2; `PyAitD.override_check.check_overrides/coverage`; `PyAitD.background_export.export_manifest`; `tools.export_backgrounds.export_floor/save_manifest`; `tests.stub_floor.StubFloor`.
- Produces: `fit_to_target(png_bytes) -> np.ndarray (800,1280,3) uint8`, `regenerate(cams, out_dir, *, client, text_model, image_model, style, force, dry_run, log=print) -> tuple[int, int]`.

- [ ] **Step 1: Write the failing tests**

```python
from PyAitD.asset_resolver import load_png_rgb
from PyAitD.background_export import export_manifest, sha256_rgb
from PyAitD import override_check as oc
from tests.stub_floor import StubFloor


def test_fit_to_target_crops_to_16_10_then_scales():
    assert rb.fit_to_target(png_bytes(np.zeros((1024, 1536, 3), np.uint8))).shape == (800, 1280, 3)
    assert rb.fit_to_target(png_bytes(np.zeros((1000, 1000, 3), np.uint8))).shape == (800, 1280, 3)
    # A 16:10 two-colour image is scaled, not cropped: left stays red, right stays blue.
    rgb = np.zeros((400, 640, 3), np.uint8)
    rgb[:, :320] = (255, 0, 0)
    rgb[:, 320:] = (0, 0, 255)
    out = rb.fit_to_target(png_bytes(rgb))
    assert tuple(out[400, 10]) == (255, 0, 0) and tuple(out[400, 1270]) == (0, 0, 255)
    # A wide image is centre-cropped: red centre column survives, black edges are cut.
    wide = np.zeros((100, 400, 3), np.uint8)
    wide[:, 120:280] = (255, 0, 0)
    out = rb.fit_to_target(png_bytes(wide))
    assert tuple(out[400, 640]) == (255, 0, 0) and tuple(out[400, 5]) == (255, 0, 0)


def _run(tmp_path, client, **kw):
    cams = rb.discover(make_in_dir(tmp_path), None)
    opts = dict(client=client, text_model="gemini-2.5-flash", image_model="gemini-2.5-flash-image",
                style="s.", force=False, dry_run=False, log=lambda *_: None)
    opts.update(kw)
    return rb.regenerate(cams, tmp_path / "out", **opts)


def test_regenerate_writes_fitted_pngs_and_prompt_cache(tmp_path):
    client = FakeClient(png_bytes(np.full((1024, 1536, 3), 7, np.uint8)))
    assert _run(tmp_path, client) == (3, 0)
    out = tmp_path / "out"
    for key in ("floor00/camera000", "floor00/camera001", "floor01/camera000"):
        assert load_png_rgb(out / "backgrounds" / f"{key}.png").shape == (800, 1280, 3)
    prompts = rb.load_prompts(out / rb.PROMPTS_FILE)
    assert set(prompts) == {"floor00/camera000", "floor00/camera001", "floor01/camera000"}
    src = (tmp_path / "in/backgrounds/floor00/camera000.png").read_bytes()
    assert prompts["floor00/camera000"] == {
        "prompt": "a dusty attic under sloped rafters", "model": "gemini-2.5-flash",
        "sha256": hashlib.sha256(src).hexdigest()}
    assert len(client.calls) == 6
    # The generation call carries the cached description and the style.
    gen_prompt = client.calls[1][1][-1]
    assert gen_prompt == rb.generation_prompt("a dusty attic under sloped rafters", "s.", True)


def test_regenerate_resumes_and_force_redoes(tmp_path):
    client = FakeClient(png_bytes(np.zeros((1024, 1536, 3), np.uint8)))
    _run(tmp_path, client)
    client.calls.clear()
    assert _run(tmp_path, client) == (0, 0)
    assert client.calls == []
    # Hand-edited prompt survives a run without --force and is used by it after deleting the png.
    path = tmp_path / "out" / rb.PROMPTS_FILE
    prompts = rb.load_prompts(path)
    prompts["floor00/camera001"]["prompt"] = "EDITED"
    rb.save_prompts(path, prompts)
    (tmp_path / "out/backgrounds/floor00/camera001.png").unlink()
    assert _run(tmp_path, client) == (1, 0)
    assert len(client.calls) == 1 and "EDITED" in client.calls[0][1][-1]
    assert rb.load_prompts(path)["floor00/camera001"]["prompt"] == "EDITED"
    client.calls.clear()
    assert _run(tmp_path, client, force=True) == (3, 0)
    assert len(client.calls) == 6
    assert rb.load_prompts(path)["floor00/camera001"]["prompt"] != "EDITED"


def test_regenerate_continues_after_a_failed_camera(tmp_path):
    logs = []
    client = FakeClient(png_bytes(np.zeros((1024, 1536, 3), np.uint8)), fail_image_calls={2})
    assert _run(tmp_path, client, log=logs.append) == (2, 1)
    assert not (tmp_path / "out/backgrounds/floor00/camera001.png").exists()
    assert any("floor00/camera001: failed: quota" in line for line in logs)


def test_regenerate_dry_run_makes_no_calls_and_no_files(tmp_path):
    logs = []
    client = FakeClient()
    assert _run(tmp_path, client, dry_run=True, log=logs.append) == (0, 0)
    assert client.calls == [] and not (tmp_path / "out").exists()
    assert any("floor00/camera001" in line and "guide no" in line for line in logs)


def test_regenerate_round_trips_through_check_overrides(tmp_path):
    in_dir = tmp_path / "in"
    floor = StubFloor(number=0)
    recs = xb.export_floor(floor, in_dir, 4)
    manifest = export_manifest(recs, "stub", 4)
    xb.save_manifest(in_dir, manifest)
    cams = rb.discover(in_dir, None)
    client = FakeClient(png_bytes(np.full((1024, 1536, 3), 9, np.uint8)))
    out = tmp_path / "out"
    assert rb.regenerate(cams, out, client=client, text_model="t", image_model="image", style="s",
                         force=False, dry_run=False, log=lambda *_: None) == (1, 0)
    assert json.loads((out / "manifest.json").read_text()) == manifest
    findings = oc.check_overrides(out, [floor], manifest)
    assert [f.kind for f in findings] == []
    assert oc.coverage(out, [floor], manifest)[0]["regenerated"] == 1
```

Add `import hashlib` at the top of the test file.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_regenerate_backgrounds.py -q` → new tests fail with AttributeError.

- [ ] **Step 3: Implement** (append)

```python
def fit_to_target(png_bytes):
    """Decode, centre-crop to the largest 16:10 rectangle, smooth-scale to
    TARGET_SIZE. Returns (800, 1280, 3) uint8 so save_png can write it."""
    import io
    import pygame
    surface = pygame.image.load(io.BytesIO(png_bytes))
    rgb = np.ascontiguousarray(pygame.surfarray.array3d(surface).swapaxes(0, 1))
    h, w = rgb.shape[:2]
    if w * 10 > h * 16:
        new_w = h * 16 // 10
        x0 = (w - new_w) // 2
        rgb = rgb[:, x0:x0 + new_w]
    elif w * 10 < h * 16:
        new_h = w * 10 // 16
        y0 = (h - new_h) // 2
        rgb = rgb[y0:y0 + new_h]
    cropped = pygame.surfarray.make_surface(np.ascontiguousarray(rgb.swapaxes(0, 1)))
    scaled = pygame.transform.smoothscale(cropped, TARGET_SIZE)
    return np.ascontiguousarray(pygame.surfarray.array3d(scaled).swapaxes(0, 1)).astype(np.uint8)


def _copy_manifest(cams, out_dir):
    if not cams:
        return
    src = cams[0].source.parents[2] / "manifest.json"
    dst = pathlib.Path(out_dir) / "manifest.json"
    if src.is_file() and not dst.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)


def regenerate(cams, out_dir, *, client, text_model, image_model, style, force, dry_run, log=print):
    """Describe + generate every camera into out_dir. Returns (done, failed).
    Existing outputs are skipped unless force; cached prompts are reused
    unless force; prompts.json is saved after every camera."""
    out_dir = pathlib.Path(out_dir)
    prompts_path = out_dir / PROMPTS_FILE
    prompts = load_prompts(prompts_path)
    done = failed = 0
    for cam in cams:
        target = out_dir / "backgrounds" / f"{cam.key}.png"
        if target.is_file() and not force:
            log(f"{cam.key}: exists, skipped")
            continue
        guide = "yes" if cam.guide is not None else "no"
        cached = "yes" if cam.key in prompts else "no"
        if dry_run:
            log(f"{cam.key}: would regenerate (guide {guide}, prompt cached {cached})")
            continue
        try:
            if cam.key not in prompts or force:
                text = describe(client, text_model, cam)
                prompts[cam.key] = {"prompt": text, "model": text_model,
                                    "sha256": hashlib.sha256(cam.source.read_bytes()).hexdigest()}
                save_prompts(prompts_path, prompts)
            prompt = generation_prompt(prompts[cam.key]["prompt"], style, cam.guide is not None)
            image = generate(client, image_model, cam, prompt)
            save_png(target, fit_to_target(image))
        except Exception as exc:  # per-camera: SDK error types are not imported here
            failed += 1
            log(f"{cam.key}: failed: {exc}")
            continue
        done += 1
        log(f"{cam.key}: ok (guide {guide}, prompt cached {cached})")
    if not dry_run:
        _copy_manifest(cams, out_dir)
    return done, failed
```

- [ ] **Step 4: Run tests, commit**

Run: `.venv/bin/pytest tests/test_regenerate_backgrounds.py -q` → 14 passed.
```bash
git add tools/regenerate_backgrounds.py tests/test_regenerate_backgrounds.py
git commit -m "feat: fit-to-1280x800 and resumable regenerate orchestrator"
```

---

### Task 4: CLI, `make_client`, Makefile target

**Files:**
- Modify: `tools/regenerate_backgrounds.py`
- Modify: `tests/test_regenerate_backgrounds.py`
- Modify: `Makefile` (`.PHONY` line and after `check-overrides`)

**Interfaces:**
- Consumes: `discover`, `regenerate`, `parse_floors`.
- Produces: `make_client() -> object`, `main(argv=None) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
def test_main_dry_run_needs_no_key_or_sdk(tmp_path, monkeypatch, capsys):
    in_dir = make_in_dir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(rb, "make_client", lambda: pytest.fail("client created in dry run"))
    assert rb.main([str(in_dir), "--out", str(tmp_path / "out"), "--dry-run"]) == 0
    assert "floor00/camera000" in capsys.readouterr().out
    assert not (tmp_path / "out").exists()


def test_main_exit_codes(tmp_path, monkeypatch, capsys):
    in_dir = make_in_dir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert rb.main([str(tmp_path / "empty"), "--out", str(tmp_path / "out")]) == 2
    assert "no cameras" in capsys.readouterr().err
    assert rb.main([str(in_dir), "--out", str(tmp_path / "out")]) == 2
    assert "GEMINI_API_KEY is not set" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_main_runs_with_injected_client_and_reports_failures(tmp_path, monkeypatch, capsys):
    in_dir = make_in_dir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    client = FakeClient(png_bytes(np.zeros((1024, 1536, 3), np.uint8)), fail_image_calls={3})
    monkeypatch.setattr(rb, "make_client", lambda: client)
    assert rb.main([str(in_dir), "--out", str(tmp_path / "out"), "--floors", "0-7",
                    "--style", "noir.", "--text-model", "t-model", "--image-model", "image-x"]) == 1
    out = capsys.readouterr().out
    assert "floor01/camera000: failed: quota" in out and "done 2, failed 1" in out
    assert client.calls[0][0] == "t-model" and client.calls[1][0] == "image-x"
    assert client.calls[1][1][-1].endswith("noir.")
    client.fail.clear()
    assert rb.main([str(in_dir), "--out", str(tmp_path / "out")]) == 0


def test_make_client_reports_missing_sdk(monkeypatch, capsys):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name.startswith("google"):
            raise ImportError(name)
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(SystemExit) as e:
        rb.make_client()
    assert e.value.code == 2
    assert 'google-genai is not installed: run .venv/bin/pip install -e ".[dev,ai]"' in capsys.readouterr().err
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_regenerate_backgrounds.py -q` → 4 fail (`main`/`make_client` missing).

- [ ] **Step 3: Implement** (append)

```python
def make_client():
    """The only place google-genai is imported. Reads GEMINI_API_KEY itself."""
    try:
        from google import genai
    except ImportError:
        print(_SDK_MISSING, file=sys.stderr)
        raise SystemExit(2)
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Regenerate exported backgrounds with Gemini.")
    p.add_argument("in_dir", help="override dir from `make export-backgrounds` (originals + guides)")
    p.add_argument("--out", required=True, help="output override dir (same layout)")
    p.add_argument("--floors", default="0-7")
    p.add_argument("--style", default=DEFAULT_STYLE)
    p.add_argument("--text-model", default=DEFAULT_TEXT_MODEL)
    p.add_argument("--image-model", default=DEFAULT_IMAGE_MODEL)
    p.add_argument("--force", action="store_true", help="redo existing outputs and cached prompts")
    p.add_argument("--dry-run", action="store_true", help="list what would be processed; no API calls")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    cams = discover(args.in_dir, set(parse_floors(args.floors)))
    if not cams:
        print(f"no cameras under {args.in_dir}/backgrounds", file=sys.stderr)
        return 2
    client = None
    if not args.dry_run:
        if not os.environ.get("GEMINI_API_KEY"):
            print("GEMINI_API_KEY is not set", file=sys.stderr)
            return 2
        client = make_client()
    done, failed = regenerate(cams, args.out, client=client, text_model=args.text_model,
                              image_model=args.image_model, style=args.style,
                              force=args.force, dry_run=args.dry_run)
    print(f"done {done}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Makefile**

Add `regenerate-backgrounds` to the `.PHONY` list and after `check-overrides`:
```make
regenerate-backgrounds: install ## Regenerate ./overrides backgrounds with Gemini into ./overrides-ai (in=, out_ai=, floors=0-7, style=, force=1, dry=1, text_model=, image_model=); needs GEMINI_API_KEY and `pip install -e ".[dev,ai]"`
	$(PYTHON) tools/regenerate_backgrounds.py "$(or $(in),overrides)" --out "$(or $(out_ai),overrides-ai)" --floors "$(or $(floors),0-7)" $(if $(style),--style "$(style)") $(if $(force),--force) $(if $(dry),--dry-run) $(if $(text_model),--text-model "$(text_model)") $(if $(image_model),--image-model "$(image_model)")
```
Verify: `make regenerate-backgrounds dry=1` prints one `would regenerate` line per exported camera (or `no cameras` exit 2 if `./overrides` is absent — acceptable), and `.venv/bin/python tools/regenerate_backgrounds.py overrides --out overrides-ai --dry-run` works as a plain script.

- [ ] **Step 5: Run full suite, commit**

Run: `.venv/bin/pytest -q` → all pass, `make prove` → pass.
```bash
git add tools/regenerate_backgrounds.py tests/test_regenerate_backgrounds.py Makefile
git commit -m "feat: regenerate-backgrounds CLI and make target"
```

---

### Task 5: Docs and live test

**Files:**
- Modify: `docs/ai-background-regeneration.md` (insert section between "## 2. Regenerate" and "## 3. Check")
- Modify: `README.md` (paragraph under Run, lines 58–62; Tests block line 76)
- Modify: `AGENTS.md` (Commands block; Conventions last bullet)
- Modify: `docs/superpowers/specs/2026-08-25-ai-background-regeneration-design.md` (Non-goals)
- Modify: `tests/test_regenerate_backgrounds.py`

- [ ] **Step 1: Live test** (append)

```python
@pytest.mark.skipif(not (os.environ.get("GEMINI_API_KEY") and os.environ.get("PYAITD_LIVE_AI") == "1"),
                    reason="set GEMINI_API_KEY and PYAITD_LIVE_AI=1 to call Gemini")
def test_live_gemini_round_trip(tmp_path):
    in_dir = tmp_path / "in"
    xb.save_png(in_dir / "backgrounds/floor00/camera000.png", checker_pixels(1))
    cams = rb.discover(in_dir, None)
    done, failed = rb.regenerate(cams, tmp_path / "out", client=rb.make_client(),
                                 text_model=rb.DEFAULT_TEXT_MODEL, image_model=rb.DEFAULT_IMAGE_MODEL,
                                 style=rb.DEFAULT_STYLE, force=False, dry_run=False)
    assert (done, failed) == (1, 0)
    assert load_png_rgb(tmp_path / "out/backgrounds/floor00/camera000.png").shape == (800, 1280, 3)
```
Run `.venv/bin/pytest tests/test_regenerate_backgrounds.py -q` → passes with 1 skipped.

- [ ] **Step 2: `docs/ai-background-regeneration.md`** — replace the intro's last sentence "Nothing here calls an AI service; the repo ships no model, no key and no game data." with "Only the optional `make regenerate-backgrounds` step calls an AI service (Gemini, your key); the repo ships no model, no key and no game data." Insert before `## 3. Check`:

```markdown
## 2b. Regenerate with Gemini (optional, in-repo)

    .venv/bin/pip install -e ".[dev,ai]"          # once: google-genai
    export GEMINI_API_KEY=...                     # never stored by the tool
    make regenerate-backgrounds dry=1             # list what would run, no calls
    make regenerate-backgrounds                   # ./overrides -> ./overrides-ai
    make regenerate-backgrounds floors=0 style="Sunlit, warm, clean." force=1

For each `backgrounds/floorNN/cameraNNN.png` (with its guide when present)
the tool asks `gemini-2.5-flash` for a scene description, stores it in
`overrides-ai/prompts.json`, then asks `gemini-2.5-flash-image` to render
that description with the original and guide as references. The result is
centre-cropped to 16:10 and scaled to 1280x800, so `check-overrides` never
reports `aspect` or `size` for it. `manifest.json` is copied across so
coverage counts every output as `regenerated`.

- Cameras that already exist in the output are skipped; rerun after an
  interruption and it continues. `force=1` redoes them and their prompts.
- Edit a prompt in `prompts.json`, delete that camera's PNG and rerun to
  regenerate only it with your wording.
- A camera that fails (quota, no image returned) is logged and skipped;
  exit status 1 means at least one failed, rerun to retry.
- `text_model=` / `image_model=` override the models; `in=` and `out_ai=`
  the directories.

Then `make check-overrides overrides=overrides-ai proof=1` and
`make run overrides=overrides-ai`.
```

- [ ] **Step 3: README** — extend the Run paragraph: after "validates the results the way the game loads them." add "`make regenerate-backgrounds` (optional; needs `pip install -e ".[dev,ai]"` and `GEMINI_API_KEY`) does the regeneration with Gemini into `./overrides-ai`." Tests block: add line `make regenerate-backgrounds dry=1  # list cameras the Gemini regeneration would process; no API calls`.

- [ ] **Step 4: AGENTS.md** — Commands block, after `check-overrides`: `make regenerate-backgrounds # Gemini describe+render ./overrides -> ./overrides-ai (dry=1, floors=, style=, force=1); needs GEMINI_API_KEY + ".[dev,ai]"`. Conventions: change the last bullet to "Dependencies fixed: pygame-ce, ModernGL, NumPy, pytest. Add nothing — the one exception is the optional extra `ai` (`google-genai`), imported only inside `tools/regenerate_backgrounds.make_client`." Add to Graphics layering bullet list: "`tools/regenerate_backgrounds.py` is the only module that may talk to an AI service; its unit tests inject a fake client and never touch the network."

- [ ] **Step 5: Old spec** — in `docs/superpowers/specs/2026-08-25-ai-background-regeneration-design.md` Non-goals, change "Calling any AI service from this repo." to "Calling any AI service from this repo (superseded for one tool by `2026-08-25-gemini-background-regeneration-design.md`)."

- [ ] **Step 6: Commit**

Run: `.venv/bin/pytest -q && make prove`.
```bash
git add docs/ai-background-regeneration.md README.md AGENTS.md docs/superpowers/specs/2026-08-25-ai-background-regeneration-design.md tests/test_regenerate_backgrounds.py
git commit -m "docs: Gemini regeneration workflow, dependency exception, live test"
```
