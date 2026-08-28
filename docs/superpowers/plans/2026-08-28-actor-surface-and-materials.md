# Actor Surface Response and Materials Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give actors and objects a per-material surface — specular, rim, hemisphere ambient, rest-pose occlusion, a contact term at the feet and procedural grain — driven by a committed palette-index → material table that a tool bootstraps, with `realism="classic"` reproducing today's output byte for byte.

**Architecture:** A pure `render/materials.py` owns the material classes, the 256-row `MaterialTable`, the JSON table format and the two `RealismPreset`s; a pure `render/occlusion.py` bakes per-vertex AO once per body; `BodyGeometry` gains `rest` and `ao`; `AssetResolver` memoises the table and the bake per body; `ActorDraw` carries the table; `GLBackend` uploads a 256×2 parameter texture and extends the `scene` fragment shader with terms that all multiply by a preset strength, so `classic` (all zeros) collapses to the existing expression. `tools/bootstrap_materials.py` surveys palette ramps and body usage, optionally asks Gemini through the existing `agy` wrapper, and emits `PyAitD/render/materials.json`.

**Tech Stack:** Python 3.12, pygame-ce, ModernGL (GL 3.3 core), NumPy, pytest.

**Spec:** `docs/superpowers/specs/2026-08-28-actor-surface-and-materials-design.md`

## Global Constraints

- Every Python file starts with `# SPDX-License-Identifier: GPL-2.0-only` as its first line.
- Dependencies are fixed: pygame-ce, ModernGL, NumPy, pytest. Add nothing. No Pillow. Gemini is reached only through the `agy` CLI via `tools.regenerate_backgrounds.agy_structured`; no SDK import anywhere.
- Package layering (`tests/test_layering.py`): `render/` imports only `engine/`; only `GRAPHICS_OWNERS` (`render_gl`, `render_soft`, `render`, `asset_resolver`) may import pygame/moderngl. `render/materials.py` and `render/occlusion.py` are therefore pure numpy. `asset_resolver.py` may touch pygame in exactly one function, `load_png_rgb`.
- Game data is never committed. `PyAitD/render/materials.json` is a classification of 256 integers, not game data, and is committed. `data/aitd1/materials-survey/` (survey output, sheets) is git-ignored.
- Tests run headless: prefix every pytest command with `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`. The interpreter is `.venv/bin/python`.
- Every test file declares exactly one subject marker via a module-level `pytestmark` (`engine`, `render`, `shell`, `tools`, `meta`). `tests/test_test_groups.py` enforces this.
- `realism="classic"` must render pixel-identically to today's `lighting="scene"` output. The shader keeps the existing expression `v_color * (fill_tint + key_tint * wrapped * wrapped)` as a separate `base` term and multiplies/adds the new terms onto it; under `classic` those are exactly `1.0` and `0.0`, which IEEE arithmetic leaves exact.
- `lighting="fixed"` stays untouched: its shader branch is not edited.
- No change to `skel.skin()`, `draw_list`, picking, masks, combat, input, or the UI layer beyond the one CONFIG row.
- `SoftwareBackend` is not touched by this plan.
- Never call `pygame.mouse.set_relative_mode`, `pygame.event.set_grab`, or `pygame.mouse.set_pos` anywhere under `PyAitD/`.

---

## File Structure

| File | Responsibility |
|---|---|
| `PyAitD/render/materials.py` (create) | `MATERIAL_CLASSES`, `Material`, `CLASS_PRESETS`, `MaterialTable`, `parse_assignments`, `parse_table`, `load_table`, `default_table`, `RealismPreset`, `PRESETS`, `REALISM_MODES`. Pure. |
| `PyAitD/render/materials.json` (create, Task 2) | The committed default table, emitted by the tool. |
| `PyAitD/render/occlusion.py` (create) | `hemisphere_directions`, `occlusion_of(vertices, tris, rays)`, `bake_vertex_ao(body, rays)`. Pure numpy. |
| `PyAitD/render/geometry.py` | `BodyGeometry.rest`, `BodyGeometry.ao`; `pose_geometry(..., ao=None)`. |
| `PyAitD/render/asset_resolver.py` | `material_table(num)`, `geometry_ao(num)`, `override_body_material_path`, JSON override loading. |
| `PyAitD/render/scene.py` | `ActorDraw.materials`; `build_frame` wiring. |
| `PyAitD/render/render_gl.py` | Vertex format, material texture, the extended `scene` shader. |
| `PyAitD/render/render_options.py` | `realism` field, `REALISM_MODES`, `cycle_realism`. |
| `PyAitD/render/override_check.py` | `check_body_materials`; `summarize` prints body findings. |
| `PyAitD/app/ui.py`, `PyAitD/app/shell.py` | The Realism CONFIG row, `--realism`, `_MENU_RENDER_FIELDS`. |
| `tools/bootstrap_materials.py` (create) | `survey`, `label`, `emit`, `check` stages. |
| `tools/prove_graphics.py` | A realism axis beside the shading axis. |
| `tests/test_materials.py`, `tests/test_occlusion.py`, `tests/test_bootstrap_materials.py` (create) | Unit tests. |
| `tests/golden/scene_lit_classic.npy` (create) | Pre-change render of a synthetic frame; the byte-identity net. |
| `Makefile`, `.gitignore`, `pyproject.toml`, `README.md`, `CONTEXT.md`, `AGENTS.md`, `docs/graphics-realism-proof.md` | Targets, ignores, package data, docs. |

---

### Task 1: `materials.py` and the `realism` render option

`realism` lands as `"classic"`, so this task changes no rendered pixel.

**Files:**
- Create: `PyAitD/render/materials.py`, `tests/test_materials.py`
- Modify: `PyAitD/render/render_options.py`
- Modify: `PyAitD/app/ui.py:20-29` (imports, `GRAPHICS_ROWS`), `PyAitD/app/ui.py:422` (`cycles`), `PyAitD/app/ui.py:562-570` (`CONFIG_ROWS`), `PyAitD/app/ui.py:1143-1152` (labels)
- Modify: `PyAitD/app/shell.py:78-84` (CLI flag), `PyAitD/app/shell.py:110-113` (`apply_render_overrides`), `PyAitD/app/shell.py:594` (`_MENU_RENDER_FIELDS`)
- Modify: `pyproject.toml`
- Test: `tests/test_render_options.py`, `tests/test_ui_reducers.py`, `tests/test_ui_mouse.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: everything in `materials.py` listed in the File Structure; `REALISM_MODES = ("classic", "enhanced")`; `RenderOptions(scale, shading, background_filter, override_dir, lighting, msaa, realism)`; `cycle_realism(options) -> RenderOptions`.

**Note on field order:** `realism` goes **last**, after `msaa`. Existing tests construct `RenderOptions` positionally with up to six arguments; appending keeps them valid.

**Note on menu geometry:** the CONFIG page holds 14 rows at a 14 px pitch from y=2 (ending y=198) and is full. The 15th row re-pitches it to 13 px from y=2: 15 rows end at y=197. Rows stay ≥ 13 px, above `effective_rects`' 12×12 minimum target, but `tests/test_ui_mouse.py`'s CONFIG assertion (`rect.height >= 14`) has to become `>= 13`. That is a deliberate reduction in visible row height; do not loosen the effective-target contract instead.

**Note on `emissive`:** it is a classification label only; its `Material` equals `matte`'s. No emissive term exists in the shader and none is added by this plan.

- [ ] **Step 1: Write the failing materials tests**

Create `tests/test_materials.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
import json

import numpy as np
import pytest

from PyAitD.render.materials import (
    CLASS_PRESETS, DETAIL_NONE, MATERIAL_CLASSES, PARAMETER_COUNT, PRESETS, REALISM_MODES,
    Material, MaterialTable, RealismPreset, default_table, load_table, parse_assignments, parse_table,
)

pytestmark = pytest.mark.render


def test_every_class_has_a_preset_with_a_positive_detail_scale():
    assert set(CLASS_PRESETS) == set(MATERIAL_CLASSES)
    for name, material in CLASS_PRESETS.items():
        assert isinstance(material, Material)
        assert material.detail_scale > 0, name  # the shader divides by it
        assert 0 <= material.detail_kind <= 4, name


def test_matte_has_no_specular_rim_or_detail():
    matte = CLASS_PRESETS["matte"]
    assert (matte.specular, matte.rim, matte.detail, matte.detail_kind) == (0.0, 0.0, 0.0, DETAIL_NONE)


def test_unmentioned_indices_are_matte_and_ramps_then_indices_apply():
    table = parse_table({"ramps": [{"lo": 16, "hi": 31, "class": "skin"}], "indices": {"20": "metal", "200": "wood"}})
    assert len(table.classes) == 256
    assert table.classes[0] == "matte"
    assert table.classes[16] == "skin" and table.classes[31] == "skin"
    assert table.classes[20] == "metal"      # indices win over ramps
    assert table.classes[200] == "wood"


def test_parse_assignments_returns_only_the_explicit_ones():
    assert parse_assignments({"ramps": [{"lo": 2, "hi": 3, "class": "hair"}], "indices": {"9": "glass"}}) == {
        2: "hair", 3: "hair", 9: "glass"}
    assert parse_assignments({}) == {}


@pytest.mark.parametrize("data, message", [
    ({"ramps": [{"lo": 4, "hi": 6, "class": "velvet"}]}, "ramp 4..6: unknown material class 'velvet'"),
    ({"indices": {"300": "skin"}}, "index 300: outside 0..255"),
    ({"ramps": [{"lo": 9, "hi": 2, "class": "skin"}]}, "ramp 9..2: lo > hi"),
    ({"indices": {"x": "skin"}}, "index 'x': not an integer"),
    ([], "material table must be an object"),
])
def test_invalid_tables_are_rejected_naming_the_entry(data, message):
    with pytest.raises(ValueError, match=message.replace("(", "\\(").replace(")", "\\)")):
        parse_table(data)


def test_remapped_changes_only_the_listed_indices():
    base = parse_table({"ramps": [{"lo": 0, "hi": 255, "class": "cloth"}]})
    out = base.remapped({5: "metal"})
    assert out.classes[5] == "metal"
    assert out.classes[4] == "cloth" and out.classes[6] == "cloth"
    assert base.classes[5] == "cloth"  # immutable


def test_parameters_are_256_by_8_float32_in_range():
    params = parse_table({"ramps": [{"lo": 0, "hi": 255, "class": "metal"}]}).parameters()
    assert params.shape == (256, PARAMETER_COUNT) and params.dtype == np.float32
    assert (params[:, :5] >= 0).all() and (params[:, :5] <= 1).all()   # roughness..detail
    assert (params[:, 5] > 0).all()                                    # detail_scale
    assert (params[:, 6] >= 0).all() and (params[:, 6] <= 4).all()     # detail_kind
    assert (params[:, 7] == 0).all()                                   # padding
    assert np.array_equal(params[7], CLASS_PRESETS["metal"].parameters())


def test_table_round_trips_through_json(tmp_path):
    data = {"ramps": [{"lo": 16, "hi": 31, "class": "skin", "note": "hero"}], "indices": {"3": "wood"}}
    path = tmp_path / "materials.json"
    path.write_text(json.dumps(data))
    assert load_table(path) == parse_table(data)


def test_default_table_is_cached_and_full_length():
    assert default_table() is default_table()
    assert len(default_table().classes) == 256
    assert set(default_table().classes) <= set(MATERIAL_CLASSES)


def test_classic_preset_is_all_zeros_and_enhanced_is_not():
    assert REALISM_MODES == ("classic", "enhanced")
    assert PRESETS["classic"] == RealismPreset(0, 0, 0, 0, 0, 0)
    enhanced = PRESETS["enhanced"]
    assert all(0 < v <= 1 for v in (enhanced.spec, enhanced.rim, enhanced.ao,
                                    enhanced.contact, enhanced.detail, enhanced.hemisphere))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_materials.py -q`
Expected: FAIL — `ModuleNotFoundError: PyAitD.render.materials`.

- [ ] **Step 3: Write `materials.py`**

Create `PyAitD/render/materials.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Per-palette-index material classes and the realism presets.

The game files say nothing about what a polygon is made of; a body is
vertices and palette-indexed primitives. This module classifies the 256
palette indices into material classes (a committed JSON table, bootstrapped
by tools/bootstrap_materials.py and hand-corrected), turns a class into the
shader's numeric parameters, and holds the two global presets that scale
every new shading term -- `classic` is all zeros so it renders exactly as
before. Pure: no pygame, no GL, no engine imports."""
from dataclasses import dataclass
import functools
import json
from pathlib import Path

import numpy as np

MATERIAL_CLASSES = ("matte", "skin", "cloth", "leather", "hair",
                    "wood", "stone", "metal", "glass", "emissive")
REALISM_MODES = ("classic", "enhanced")
PALETTE_SIZE = 256
PARAMETER_COUNT = 8   # 7 Material fields + one padding float: two RGBA texels per index
DETAIL_NONE, DETAIL_GRAIN, DETAIL_WEAVE, DETAIL_STREAK, DETAIL_BRUSHED = range(5)
DEFAULT_TABLE_PATH = Path(__file__).with_name("materials.json")


@dataclass(frozen=True)
class Material:
    roughness: float     # 0..1: specular exponent and spread
    specular: float      # 0..1: highlight strength
    metallic: float      # 0..1: highlight takes the surface colour, not the key's
    rim: float           # 0..1: fresnel rim strength
    detail: float        # 0..1: procedural grain amount
    detail_scale: float  # FITD units per noise cell; always > 0, the shader divides by it
    detail_kind: int     # DETAIL_NONE .. DETAIL_BRUSHED

    def parameters(self):
        return np.array([self.roughness, self.specular, self.metallic, self.rim,
                         self.detail, self.detail_scale, float(self.detail_kind), 0.0], dtype=np.float32)


# Starting values; task 4 of the plan tunes them against the proof fixtures.
CLASS_PRESETS = {
    "matte":    Material(1.0, 0.0, 0.0, 0.0, 0.0, 1.0, DETAIL_NONE),
    "skin":     Material(0.7, 0.15, 0.0, 0.25, 0.15, 40.0, DETAIL_GRAIN),
    "cloth":    Material(0.9, 0.05, 0.0, 0.35, 0.25, 12.0, DETAIL_WEAVE),
    "leather":  Material(0.5, 0.35, 0.0, 0.3, 0.2, 30.0, DETAIL_GRAIN),
    "hair":     Material(0.6, 0.3, 0.0, 0.4, 0.3, 8.0, DETAIL_STREAK),
    "wood":     Material(0.6, 0.2, 0.0, 0.1, 0.35, 60.0, DETAIL_STREAK),
    "stone":    Material(0.85, 0.05, 0.0, 0.05, 0.3, 50.0, DETAIL_GRAIN),
    "metal":    Material(0.25, 0.8, 0.9, 0.2, 0.15, 25.0, DETAIL_BRUSHED),
    "glass":    Material(0.1, 0.9, 0.0, 0.6, 0.0, 1.0, DETAIL_NONE),
    # A label only: no emissive term exists in the shader, so it shades as matte.
    "emissive": Material(1.0, 0.0, 0.0, 0.0, 0.0, 1.0, DETAIL_NONE),
}


def _check_class(name, where):
    if name not in MATERIAL_CLASSES:
        raise ValueError(f"{where}: unknown material class {name!r}")


def _check_index(index, where):
    if not 0 <= index < PALETTE_SIZE:
        raise ValueError(f"{where}: outside 0..{PALETTE_SIZE - 1}")


@dataclass(frozen=True)
class MaterialTable:
    classes: tuple   # PALETTE_SIZE class names, index = palette index

    def __post_init__(self):
        if len(self.classes) != PALETTE_SIZE:
            raise ValueError(f"material table must have {PALETTE_SIZE} entries, got {len(self.classes)}")
        for index, name in enumerate(self.classes):
            _check_class(name, f"index {index}")

    def parameters(self):
        """(256, 8) float32: what the GL backend uploads as a 256x2 RGBA texture."""
        out = np.zeros((PALETTE_SIZE, PARAMETER_COUNT), dtype=np.float32)
        for index, name in enumerate(self.classes):
            out[index] = CLASS_PRESETS[name].parameters()
        return out

    def remapped(self, overrides):
        """A new table with `overrides` ({index: class}) applied on top."""
        classes = list(self.classes)
        for index, name in overrides.items():
            _check_index(index, f"index {index}")
            _check_class(name, f"index {index}")
            classes[index] = name
        return MaterialTable(tuple(classes))


def parse_assignments(data):
    """The explicit {index: class} assignments a table file makes: `ramps`
    in order, then `indices`. Unmentioned indices are absent, which is what
    lets a per-body override leave the default alone everywhere else."""
    if not isinstance(data, dict):
        raise ValueError("material table must be an object")
    out = {}
    for ramp in data.get("ramps", ()):
        lo, hi, name = ramp.get("lo"), ramp.get("hi"), ramp.get("class")
        where = f"ramp {lo}..{hi}"
        if type(lo) is not int or type(hi) is not int:
            raise ValueError(f"{where}: lo and hi must be integers")
        if lo > hi:
            raise ValueError(f"{where}: lo > hi")
        _check_index(lo, where)
        _check_index(hi, where)
        _check_class(name, where)
        for index in range(lo, hi + 1):
            out[index] = name
    for key, name in data.get("indices", {}).items():
        try:
            index = int(key)
        except (TypeError, ValueError):
            raise ValueError(f"index {key!r}: not an integer") from None
        _check_index(index, f"index {index}")
        _check_class(name, f"index {index}")
        out[index] = name
    return out


def parse_table(data):
    return MaterialTable(("matte",) * PALETTE_SIZE).remapped(parse_assignments(data))


def load_table(path):
    return parse_table(json.loads(Path(path).read_text(encoding="utf-8")))


@functools.lru_cache(maxsize=1)
def default_table():
    """The committed PyAitD/render/materials.json. Cached: GLBackend skips
    the parameter upload when an actor hands it the same table object."""
    return load_table(DEFAULT_TABLE_PATH)


@dataclass(frozen=True)
class RealismPreset:
    spec: float
    rim: float
    ao: float
    contact: float
    detail: float
    hemisphere: float


PRESETS = {
    "classic": RealismPreset(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    "enhanced": RealismPreset(spec=1.0, rim=0.6, ao=0.7, contact=1.0, detail=1.0, hemisphere=1.0),
}
```

`default_table()` needs a file to exist before Task 2 emits the real one. Create a placeholder `PyAitD/render/materials.json` now, replaced in Task 2:

```json
{"ramps": [], "indices": {}}
```

- [ ] **Step 4: Run the materials tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_materials.py -q`
Expected: PASS.

- [ ] **Step 5: Write the failing option tests**

In `tests/test_render_options.py`, update `test_defaults`' first line and add a test:

```python
def test_defaults():
    assert RenderOptions() == RenderOptions(4, "smooth", "bilinear", None, "scene", 4, "classic")
    assert SHADING_MODES == ("flat", "lambert", "smooth")
    assert BACKGROUND_FILTERS == ("nearest", "bilinear", "xbr")


def test_realism_defaults_to_classic_and_cycles():
    from PyAitD.render.render_options import REALISM_MODES, cycle_realism
    assert REALISM_MODES == ("classic", "enhanced")
    options = RenderOptions()
    assert options.realism == "classic"
    assert cycle_realism(options).realism == "enhanced"
    assert cycle_realism(cycle_realism(options)).realism == "classic"
    assert RenderOptions(realism="enhanced").to_payload()["realism"] == "enhanced"


def test_invalid_realism_falls_back_alone():
    payload = RenderOptions().to_payload()
    payload["realism"] = "ultra"
    options, error = validate_render_options(payload)
    assert options == RenderOptions() and "realism" in error
```

In `tests/test_render_options.py::test_each_invalid_field_falls_back_alone`, both payload dicts gain `"realism": "classic"` and the expected `RenderOptions(...)` calls gain a trailing `"classic"`.

In `tests/test_config.py::test_save_writes_schema_2_with_render`, the expected payload gains `"realism": "classic"`.

In `tests/test_ui_reducers.py::test_graphics_rows_cycle_render_options`, change the first assertion and append a row check:

```python
    assert GRAPHICS_ROWS == 6 and config_row_count() == 2 + len(REMAPPABLE_CONTROLS) + 6
```
and, after the `first + 2` block:
```python
    state.cursor = first + 5
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(realism="enhanced")
```

In `tests/test_ui_mouse.py:180-185`, the CONFIG branch becomes:

```python
        elif page is SystemMenuPage.CONFIG:
            # the 15-row CONFIG page packs at a 13 px pitch to fit Scale,
            # Shading, Filter, Lighting, AA and Realism above Back without
            # overflowing the screen; effective_rects still pads every row
            # past the 12x12 minimum target size
            assert all(rect.width >= 224 and rect.height >= 13 for rect in rows)
```

- [ ] **Step 6: Run the option tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_options.py tests/test_config.py tests/test_ui_reducers.py tests/test_ui_mouse.py -q`
Expected: FAIL — no `realism` field, `GRAPHICS_ROWS == 5`.

- [ ] **Step 7: Add the option**

In `PyAitD/render/render_options.py`:

```python
from PyAitD.render.materials import REALISM_MODES
```
(after the `dataclasses` import), and:

```python
@dataclass(frozen=True)
class RenderOptions:
    scale: int = 4
    shading: str = "smooth"
    background_filter: str = "bilinear"
    override_dir: str | None = None
    lighting: str = "scene"
    msaa: int = 4
    realism: str = "classic"

    def to_payload(self):
        return {
            "scale": self.scale,
            "shading": self.shading,
            "background_filter": self.background_filter,
            "override_dir": self.override_dir,
            "lighting": self.lighting,
            "msaa": self.msaa,
            "realism": self.realism,
        }
```

In `validate_render_options`, after the `msaa` block and before `options = ...`:

```python
    realism = payload.get("realism")
    if realism not in REALISM_MODES:
        errors.append(f"realism must be one of {', '.join(REALISM_MODES)}")
        realism = defaults.realism
    options = RenderOptions(scale, shading, background_filter, override_dir, lighting, msaa, realism)
```

At the end of the module:

```python
def cycle_realism(options):
    return replace(options, realism=_cycle(REALISM_MODES, options.realism))
```

In `PyAitD/app/ui.py`: add `cycle_realism` to the `render_options` import; `GRAPHICS_ROWS = 6`; the `cycles` tuple becomes `(cycle_scale, cycle_shading, cycle_filter, cycle_lighting, cycle_msaa, cycle_realism)`; `CONFIG_ROWS` becomes

```python
    # 15 rows at a 13 px pitch from y=2 ends at y=197. The 14 px pitch fitted
    # exactly 14 rows and had no room for the Realism row. Rows stay >= 13 px
    # tall, so effective_rects' 12x12 minimum target contract still holds.
    CONFIG_ROWS = tuple(
        pygame.Rect(16, 2 + i * 13, 288, 13)
        for i in range(config_row_count())
    )
```

and, after the AA label and before `labels.append("Back to Menu")`:

```python
        labels.append(f"Realism: {settings.render.realism.title()}")
```

In `PyAitD/app/shell.py`: add `REALISM_MODES` to the `render_options` import; after the `--msaa` argument:

```python
    p.add_argument(
        "--realism", choices=REALISM_MODES, default=None,
        help="classic (today's look) or enhanced (per-material specular, rim, occlusion and grain)",
    )
```

in `apply_render_overrides`, after the `msaa` block:

```python
    if args.realism is not None:
        payload["realism"] = args.realism
```

and

```python
_MENU_RENDER_FIELDS = ("scale", "shading", "background_filter", "lighting", "msaa", "realism")
```

with its comment's row list extended to `Scale/Shading/Filter/Lighting/AA/Realism` and `cycle_realism`.

In `pyproject.toml`, after `[tool.setuptools.packages.find]`:

```toml
[tool.setuptools.package-data]
PyAitD = ["render/*.json"]
```

- [ ] **Step 8: Run the shell and render groups**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest -m "render or shell or meta" -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add PyAitD/render/materials.py PyAitD/render/materials.json PyAitD/render/render_options.py PyAitD/app/ui.py PyAitD/app/shell.py pyproject.toml tests/test_materials.py tests/test_render_options.py tests/test_config.py tests/test_ui_reducers.py tests/test_ui_mouse.py
git commit -m "feat: material classes, the material table, and a realism render option defaulting to classic"
```

---

### Task 2: `tools/bootstrap_materials.py` — `survey`, `emit`, `check`; the committed table

**Files:**
- Create: `tools/bootstrap_materials.py`, `tests/test_bootstrap_materials.py`
- Modify: `Makefile:19` (`.PHONY`), `Makefile:121` (after `regenerate-backgrounds`), `.gitignore`
- Replace: `PyAitD/render/materials.json`

**Interfaces:**
- Consumes: `PyAitD.render.materials` (`MATERIAL_CLASSES`, `DEFAULT_TABLE_PATH`, `parse_table`), `PyAitD.engine.assets.Assets`, `PyAitD.engine.floor.Floor`, `PyAitD.render.geometry.vertex_groups`, `PyAitD.engine.skel.skin`, `PyAitD.render.render_soft.SoftwareBackend`, `PyAitD.render.scene.ActorDraw/CameraView/FrameDescription`, `tools.export_backgrounds.save_png`.
- Produces: `split_ramps(palette) -> list[tuple[int, int]]`, `body_usage(bodies) -> dict[int, dict]`, `propose(lo, hi, palette, usage) -> tuple[str, float, str]`, `survey(palette, bodies) -> dict`, `resolve_class(ramp) -> str`, `emit_table(survey_data) -> dict`, `contact_sheet(body, palette, highlight=None) -> np.ndarray`, `main(argv) -> int`. `bodies` everywhere is `dict[str, Body]` keyed `"<hero>:<num>"`.

**Survey JSON shape** (one ramp per entry, `label`/`vision_class` absent until set):

```json
{"ramps": [{"lo": 16, "hi": 31, "class": "skin", "confidence": 0.7,
            "reason": "peach hue; used only by bodies with >= 8 groups",
            "usage": {"bodies": ["0:0", "0:1"], "triangles": 140, "groups": [1, 5, 6]},
            "sheet": "sheets/body0-000.png", "highlight": "sheets/ramp016-031.png"}]}
```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bootstrap_materials.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
import json
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pytest

from PyAitD.engine.formats import Body, Group, Primitive
from PyAitD.render.materials import parse_table
from tools import bootstrap_materials as bm

pytestmark = pytest.mark.tools


def _palette():
    """Two ramps and a singleton: a 16-step grey ramp at 0..15, a 6-step
    peach ramp at 16..21 (hue ~0.07, saturation ~0.5, rising luminance),
    and one bright isolated entry at 22; everything else black."""
    pal = np.zeros((256, 3), np.uint8)
    for i in range(16):
        pal[i] = (i * 16, i * 16, i * 16)
    for j in range(6):
        l = 90 + j * 20            # r = l + 60 stays under 255
        pal[16 + j] = (l + 60, l, l - 40)
    pal[22] = (250, 250, 200)
    return pal


def _body(colors, groups=0, prim_type=1):
    v = [(-100, -100, 0), (100, -100, 0), (100, 100, 0), (-100, 100, 0)]
    prims = [Primitive(prim_type, 0, c, [0, 1, 2, 3]) for c in colors]
    gs = [Group(0, 4, 0, 0xFF, 0, 0, 0, 0)] + [Group(4, 0, 0, 0xFF, i, 0, 0, 0) for i in range(1, groups)]
    return Body(0, (-100, 100, -100, 100, -10, 10), (), v, gs, list(range(len(gs))), prims)


def test_split_ramps_finds_two_ramps_and_a_singleton():
    ramps = bm.split_ramps(_palette())
    assert (0, 15) in ramps
    assert (16, 21) in ramps
    assert (22, 22) in ramps
    # every index is in exactly one ramp
    covered = sorted(i for lo, hi in ramps for i in range(lo, hi + 1))
    assert covered == list(range(256))


def test_body_usage_counts_triangles_bodies_and_groups():
    bodies = {"0:0": _body([16, 16, 20], groups=9), "1:3": _body([16], groups=1), "0:5": _body([0], groups=1, prim_type=0)}
    usage = bm.body_usage(bodies)
    assert usage[16]["bodies"] == ["0:0", "1:3"]
    assert usage[16]["triangles"] == 2 * 2 + 1 * 2   # quads fan into two triangles
    assert usage[20]["bodies"] == ["0:0"]
    assert 0 not in usage                             # lines are not surfaces
    assert usage[16]["groups"] == [0]


def test_propose_reads_skin_off_a_peach_ramp_on_a_many_group_body():
    bodies = {"0:0": _body([16, 17, 18], groups=12)}
    name, confidence, reason = bm.propose(16, 21, _palette(), bm.body_usage(bodies))
    assert name == "skin" and confidence >= 0.7 and "peach" in reason


def test_propose_reads_metal_off_a_long_grey_ramp_on_a_one_group_body():
    bodies = {"0:7": _body([3, 4, 5], groups=1)}
    name, confidence, _ = bm.propose(0, 15, _palette(), bm.body_usage(bodies))
    assert name == "metal" and 0 < confidence < 0.8


def test_propose_marks_an_unused_ramp_matte_with_high_confidence():
    name, confidence, reason = bm.propose(22, 22, _palette(), {})
    assert name == "matte" and confidence >= 0.9 and "unused" in reason


def test_survey_lists_every_ramp_with_usage_and_proposal():
    bodies = {"0:0": _body([16, 17], groups=12), "0:1": _body([4], groups=1)}
    data = bm.survey(_palette(), bodies)
    ramps = {(r["lo"], r["hi"]): r for r in data["ramps"]}
    assert ramps[(16, 21)]["class"] == "skin"
    assert ramps[(16, 21)]["usage"]["bodies"] == ["0:0"]
    assert ramps[(0, 15)]["usage"]["triangles"] == 2
    assert set(ramps[(16, 21)]) >= {"lo", "hi", "class", "confidence", "reason", "usage"}


def test_resolve_class_prefers_label_then_vision_then_heuristic():
    assert bm.resolve_class({"class": "cloth"}) == "cloth"
    assert bm.resolve_class({"class": "cloth", "vision_class": "leather"}) == "leather"
    assert bm.resolve_class({"class": "cloth", "vision_class": "leather", "label": "skin"}) == "skin"


def test_emit_table_writes_load_table_shape_with_evidence_notes():
    data = {"ramps": [
        {"lo": 16, "hi": 21, "class": "skin", "confidence": 0.7, "reason": "peach",
         "usage": {"bodies": ["0:0"], "triangles": 4, "groups": [1, 5]}},
        {"lo": 0, "hi": 15, "class": "metal", "vision_class": "stone", "confidence": 0.4, "reason": "grey",
         "usage": {"bodies": ["0:1"], "triangles": 2, "groups": [0]}},
    ]}
    table = bm.emit_table(data)
    assert table["indices"] == {}
    by = {(r["lo"], r["hi"]): r for r in table["ramps"]}
    assert by[(16, 21)]["class"] == "skin" and by[(0, 15)]["class"] == "stone"
    assert "bodies 0:0" in by[(16, 21)]["note"] and "heuristic: skin" in by[(16, 21)]["note"]
    assert "vision: stone" in by[(0, 15)]["note"]
    parsed = parse_table(table)                       # the game can load it
    assert parsed.classes[18] == "skin" and parsed.classes[3] == "stone"


def test_contact_sheet_renders_the_body_and_highlights_a_ramp():
    body = _body([16], groups=1)
    plain = bm.contact_sheet(body, _palette())
    assert plain.shape == (200, 320, 3)
    assert plain.std() > 0                             # something was drawn
    lit = bm.contact_sheet(body, _palette(), highlight=(16, 21))
    magenta = (lit == (255, 0, 255)).all(axis=2)
    assert magenta.any() and not (plain == (255, 0, 255)).all(axis=2).any()


def test_check_fails_on_a_drifted_table_and_passes_on_a_fresh_emit(tmp_path):
    data = {"ramps": [{"lo": 16, "hi": 21, "class": "skin", "confidence": 0.7, "reason": "",
                       "usage": {"bodies": [], "triangles": 0, "groups": []}}]}
    (tmp_path / "survey.json").write_text(json.dumps(data))
    table = tmp_path / "materials.json"
    table.write_text(json.dumps(bm.emit_table(data)))
    assert bm.main(["unused", "check", "--out", str(tmp_path), "--table", str(table)]) == 0
    table.write_text(json.dumps({"ramps": [], "indices": {}}))
    assert bm.main(["unused", "check", "--out", str(tmp_path), "--table", str(table)]) == 1


def test_emit_stage_writes_the_table_from_the_survey(tmp_path):
    data = bm.survey(_palette(), {"0:0": _body([16], groups=12)})
    (tmp_path / "survey.json").write_text(json.dumps(data))
    table = tmp_path / "materials.json"
    assert bm.main(["unused", "emit", "--out", str(tmp_path), "--table", str(table)]) == 0
    assert parse_table(json.loads(table.read_text())).classes[16] == "skin"


def test_main_exits_2_without_data_for_survey(tmp_path, capsys):
    assert bm.main([str(tmp_path / "missing"), "survey", "--out", str(tmp_path)]) == 2
    assert "missing" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_bootstrap_materials.py -q`
Expected: FAIL — `ModuleNotFoundError: tools.bootstrap_materials`.

- [ ] **Step 3: Write the tool**

Create `tools/bootstrap_materials.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Bootstrap PyAitD/render/materials.json: classify the 256 palette indices
into material classes from the palette's own ramps and from which bodies use
them, optionally ask a vision model about the uncertain ramps, and emit the
table the game loads.

    survey  palette ramps + body usage + heuristic proposal -> OUT/survey.json, OUT/sheets/
    label   (--vision, needs the `agy` CLI) vision_class for ramps under --threshold
    emit    survey.json -> materials.json, precedence: hand `label` > vision_class > heuristic
    check   exit 1 when the committed table differs from a fresh emit of survey.json

Only `label` touches a model, and only through regenerate_backgrounds'
agy_structured. survey.json and sheets/ are git-ignored; the emitted table
is the one committed file. Spec:
docs/superpowers/specs/2026-08-28-actor-surface-and-materials-design.md."""
import argparse
import json
import pathlib
import shutil
import sys

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from PyAitD.render.geometry import POLY_TYPES, pose_geometry, vertex_groups  # noqa: E402
from PyAitD.render.materials import DEFAULT_TABLE_PATH, MATERIAL_CLASSES  # noqa: E402
from tools.export_backgrounds import save_png  # noqa: E402

SURVEY_FILE = "survey.json"
DEFAULT_OUT = pathlib.Path("data/aitd1/materials-survey")
RAMP_HUE_TOLERANCE = 0.06   # hue drift (0..1 circle) allowed inside one ramp
GREY_SATURATION = 0.12      # below this an entry has no usable hue
CONFIDENT = 0.8             # ramps at or above this skip the vision pass
HEROES = (0, 1)             # both hero body archives: Carnby's and Emily's
MAGENTA = (255, 0, 255)


# ---- colour ----

def rgb_to_hsl(rgb):
    """(N,3) uint8 -> (hue, saturation, lightness) float arrays in 0..1."""
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    r, g, b = c[:, 0], c[:, 1], c[:, 2]
    hi, lo = c.max(axis=1), c.min(axis=1)
    light = (hi + lo) / 2.0
    delta = hi - lo
    sat = np.where(delta > 0, delta / (1.0 - np.abs(2.0 * light - 1.0) + 1e-9), 0.0)
    hue = np.zeros_like(light)
    m = delta > 0
    rm, gm, bm = (hi == r) & m, (hi == g) & m & (hi != r), (hi == b) & m & (hi != r) & (hi != g)
    hue[rm] = ((g - b)[rm] / delta[rm]) % 6.0
    hue[gm] = (b - r)[gm] / delta[gm] + 2.0
    hue[bm] = (r - g)[bm] / delta[bm] + 4.0
    return hue / 6.0, sat, light


def _hue_distance(a, b):
    d = abs(a - b) % 1.0
    return min(d, 1.0 - d)


def split_ramps(palette):
    """Runs of indices whose lightness is monotone and whose hue stays
    near the run's first saturated entry. Every index lands in exactly one
    ramp; an entry that fits nowhere is a ramp of its own."""
    hue, sat, light = rgb_to_hsl(palette)
    ramps = []
    start = 0
    direction = 0
    while start < len(palette):
        end = start
        anchor = hue[start] if sat[start] >= GREY_SATURATION else None
        direction = 0
        while end + 1 < len(palette):
            nxt = end + 1
            step = np.sign(light[nxt] - light[end])
            if step == 0:
                break
            if direction == 0:
                direction = step
            elif step != direction:
                break
            if sat[nxt] >= GREY_SATURATION:
                if anchor is None:
                    anchor = hue[nxt]
                elif _hue_distance(hue[nxt], anchor) > RAMP_HUE_TOLERANCE:
                    break
            elif anchor is not None and sat[end] >= GREY_SATURATION:
                break   # a coloured ramp does not continue into grey
            end = nxt
        ramps.append((start, end))
        start = end + 1
    return ramps


# ---- usage ----

def body_usage(bodies):
    """{palette index: {"bodies": [...], "triangles": n, "groups": [...]}}
    over every polygon primitive of every body; lines and points are not
    surfaces and are skipped."""
    out = {}
    for key in sorted(bodies):
        body = bodies[key]
        groups = vertex_groups(body)
        for prim in body.primitives:
            if prim.type not in POLY_TYPES or len(prim.points) < 3:
                continue
            entry = out.setdefault(prim.color, {"bodies": [], "triangles": 0, "groups": set()})
            if key not in entry["bodies"]:
                entry["bodies"].append(key)
            entry["triangles"] += len(prim.points) - 2
            entry["groups"].update(int(groups[p]) for p in prim.points if 0 <= p < len(groups))
    for entry in out.values():
        entry["groups"] = sorted(entry["groups"])
    return out


def _ramp_usage(lo, hi, usage):
    bodies, triangles, groups = [], 0, set()
    for index in range(lo, hi + 1):
        entry = usage.get(index)
        if entry is None:
            continue
        bodies += [b for b in entry["bodies"] if b not in bodies]
        triangles += entry["triangles"]
        groups.update(entry["groups"])
    return {"bodies": sorted(bodies), "triangles": triangles, "groups": sorted(groups)}


def propose(lo, hi, palette, usage, bodies=None):
    """(class, confidence, reason) for one ramp. `bodies` (the survey's
    dict) lets the rule read group counts; without it every body counts as
    one-group scenery."""
    used = _ramp_usage(lo, hi, usage)
    if not used["bodies"]:
        return "matte", 0.9, "unused by any body"
    hue, sat, light = rgb_to_hsl(palette[lo:hi + 1])
    h, s, l, n = float(np.median(hue)), float(sat.mean()), float(light.mean()), hi - lo + 1
    group_counts = [len(bodies[b].groups) if bodies and b in bodies else 1 for b in used["bodies"]]
    many_groups = bool(group_counts) and min(group_counts) >= 8
    scenery = bool(group_counts) and max(group_counts) <= 1
    if s < GREY_SATURATION:
        if n >= 8:
            return "metal", 0.5, f"long grey ramp ({n} steps)"
        return "stone", 0.4, f"short grey ramp ({n} steps)"
    if 0.02 <= h <= 0.11 and 0.2 <= s <= 0.75 and l > 0.35:
        conf = 0.6 + (0.2 if many_groups else 0.0)
        return "skin", conf, "peach hue" + ("; used only by bodies with >= 8 groups" if many_groups else "")
    if 0.03 <= h <= 0.13 and s > 0.3 and l <= 0.4:
        if scenery:
            return "wood", 0.5, "dark saturated brown on one-group scenery"
        return "leather", 0.5, "dark saturated brown on articulated bodies"
    if n <= 2 and l > 0.8:
        return "emissive", 0.5, "very short, very bright ramp"
    if 0.25 <= h <= 0.75:
        return "cloth", 0.5, "green/blue hue"
    if many_groups:
        return "cloth", 0.3, "unclassified hue on articulated bodies"
    return "matte", 0.3, "unclassified hue on scenery"


def survey(palette, bodies):
    usage = body_usage(bodies)
    ramps = []
    for lo, hi in split_ramps(palette):
        name, confidence, reason = propose(lo, hi, palette, usage, bodies)
        ramps.append({"lo": lo, "hi": hi, "class": name, "confidence": round(confidence, 2),
                      "reason": reason, "usage": _ramp_usage(lo, hi, usage)})
    return {"ramps": ramps}


# ---- sheets ----

def contact_sheet(body, palette, highlight=None):
    """A flat 320x200 render of the body in rest pose on a black plate
    through SoftwareBackend; `highlight=(lo, hi)` paints that ramp magenta."""
    from PyAitD.render.asset_resolver import ImageAsset
    from PyAitD.render.render_soft import SoftwareBackend
    from PyAitD.render.scene import ActorDraw, CameraView, FrameDescription
    from PyAitD.engine.skel import skin
    from PyAitD.engine.world import CameraState
    pal = np.array(palette, dtype=np.uint8, copy=True)
    if highlight is not None:
        pal[highlight[0]:highlight[1] + 1] = MAGENTA
    states = [(0, (0, 0, 0))] * len(body.groups)
    rest = np.array(body.vertices, dtype=np.float64).reshape(-1, 3)
    extent = float(np.abs(rest).max()) if len(rest) else 100.0
    depth = max(0.0, extent * 320.0 / 90.0 - 1000.0)
    y_mid = float((rest[:, 1].min() + rest[:, 1].max()) / 2.0) if len(rest) else 0.0
    position = (0.0, -y_mid, depth)
    state = CameraState(0, 0, 0, 0, 0, 0, 1000, 320, 320).angles()
    logical = skin(body, states, position, state, actor_angles=(0, 0, 0))
    actor = ActorDraw(0, pose_geometry(body, states, (0, 0, 0)), position, 0, tuple(body.zv), logical, ())
    frame = FrameDescription(CameraView(state), ImageAsset(np.zeros((200, 320, 3), np.uint8), False),
                             pal, (actor,), ())
    return SoftwareBackend().draw(frame)


def write_sheets(out_dir, data, palette, bodies):
    sheets = pathlib.Path(out_dir) / "sheets"
    for key, body in bodies.items():
        hero, num = key.split(":")
        save_png(sheets / f"body{hero}-{int(num):03d}.png", contact_sheet(body, palette))
    for ramp in data["ramps"]:
        used = ramp["usage"]["bodies"]
        if not used:
            continue
        top = max(used, key=lambda k: sum(1 for p in bodies[k].primitives if p.color in range(ramp["lo"], ramp["hi"] + 1)))
        hero, num = top.split(":")
        ramp["sheet"] = f"sheets/body{hero}-{int(num):03d}.png"
        ramp["highlight"] = f"sheets/ramp{ramp['lo']:03d}-{ramp['hi']:03d}.png"
        save_png(sheets / f"ramp{ramp['lo']:03d}-{ramp['hi']:03d}.png",
                 contact_sheet(bodies[top], palette, highlight=(ramp["lo"], ramp["hi"])))


# ---- emit ----

def resolve_class(ramp):
    return ramp.get("label") or ramp.get("vision_class") or ramp["class"]


def emit_table(data):
    ramps = []
    for ramp in data["ramps"]:
        used = ramp["usage"]
        note = [f"bodies {', '.join(used['bodies'][:6])}" + (" ..." if len(used["bodies"]) > 6 else ""),
                f"groups {', '.join(str(g) for g in used['groups'][:8])}",
                f"heuristic: {ramp['class']} ({ramp.get('confidence', 0)})"]
        if ramp.get("vision_class"):
            note.append(f"vision: {ramp['vision_class']}")
        if ramp.get("label"):
            note.append(f"label: {ramp['label']}")
        ramps.append({"lo": ramp["lo"], "hi": ramp["hi"], "class": resolve_class(ramp), "note": "; ".join(note)})
    return {"ramps": ramps, "indices": {}}


# ---- data loading ----

def load_game(data_dir):
    """(palette, bodies) from real game data: the floor-0 palette and every
    body of both hero archives, keyed '<hero>:<num>'."""
    from PyAitD.engine.assets import Assets
    from PyAitD.engine.floor import Floor
    from PyAitD.games.aitd1.profile import AITD1
    palette = Floor(data_dir, 0, AITD1).palette
    bodies = {}
    for hero in HEROES:
        assets = Assets(data_dir, AITD1, hero=hero)
        for num in range(assets.num_bodies):
            try:
                bodies[f"{hero}:{num}"] = assets.body(num)
            except (ValueError, KeyError, IndexError):
                continue   # an entry that is not a body (real archives carry a few)
    return palette, bodies


def _read_json(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _write_json(path, data):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")


# ---- CLI ----

def _parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("data", type=pathlib.Path, help="game data directory (e.g. .../INDARK); unused by emit/check")
    p.add_argument("stage", choices=("survey", "label", "emit", "check"))
    p.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT, help="survey directory")
    p.add_argument("--table", type=pathlib.Path, default=DEFAULT_TABLE_PATH, help="materials.json to emit/check")
    p.add_argument("--model", default="gemini-3.1-pro", help="vision model for the label stage")
    p.add_argument("--threshold", type=float, default=CONFIDENT, help="label ramps below this confidence")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    survey_path = args.out / SURVEY_FILE
    if args.stage == "survey":
        if not args.data.is_dir():
            print(f"error: game data directory not found: {args.data}", file=sys.stderr)
            return 2
        palette, bodies = load_game(args.data)
        data = survey(palette, bodies)
        write_sheets(args.out, data, palette, bodies)
        _write_json(survey_path, data)
        print(f"{survey_path}: {len(data['ramps'])} ramps over {len(bodies)} bodies")
        return 0
    if not survey_path.is_file():
        print(f"error: no {survey_path}; run the survey stage first", file=sys.stderr)
        return 2
    data = _read_json(survey_path)
    if args.stage == "label":
        return label_stage(data, args, survey_path)
    table = emit_table(data)
    if args.stage == "emit":
        _write_json(args.table, table)
        print(f"{args.table}: {len(table['ramps'])} ramps")
        return 0
    committed = _read_json(args.table) if args.table.is_file() else None
    if committed != table:
        print(f"{args.table} differs from a fresh emit of {survey_path}", file=sys.stderr)
        return 1
    print(f"{args.table} is up to date")
    return 0


def label_stage(data, args, survey_path):
    print("the label stage lands in a later task", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

`shutil` and `MATERIAL_CLASSES` are used by Task 7's label stage; keep the imports.

- [ ] **Step 4: Run the tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_bootstrap_materials.py -q`
Expected: PASS. If `test_split_ramps_finds_two_ramps_and_a_singleton` fails on the boundary between 15 and 16 (grey → peach), the `elif anchor is not None and sat[end] >= GREY_SATURATION` guard is the rule to adjust: a coloured entry following a grey run starts a new ramp because the grey run's `anchor` is `None` and the lightness step from 240 to 150 reverses direction. Check the direction reversal is what splits them; do not weaken the test.

- [ ] **Step 5: Wire the Makefile and gitignore**

`Makefile:19` `.PHONY` gains `bootstrap-materials`. After the `regenerate-backgrounds` target:

```make
bootstrap-materials: install ## Survey palette ramps + body usage into data/aitd1/materials-survey, then emit PyAitD/render/materials.json (out=, vision=1 runs the agy labelling stage in between, model=, threshold=0.8)
	$(PYTHON) tools/bootstrap_materials.py "$(data)" survey --out "$(or $(survey_out),data/aitd1/materials-survey)"
	$(if $(vision),$(PYTHON) tools/bootstrap_materials.py "$(data)" label --out "$(or $(survey_out),data/aitd1/materials-survey)" $(if $(model),--model "$(model)") $(if $(threshold),--threshold "$(threshold)"))
	$(PYTHON) tools/bootstrap_materials.py "$(data)" emit --out "$(or $(survey_out),data/aitd1/materials-survey)"
```

(`out` is already the export directory variable at `Makefile:11`, hence `survey_out`.)

`.gitignore` gains a line:

```
materials-survey/
```

- [ ] **Step 6: Run the survey and emit against the local data, replace the placeholder table**

```bash
make bootstrap-materials
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python tools/bootstrap_materials.py unused check
git diff --stat PyAitD/render/materials.json
```

Expected: `check` prints `PyAitD/render/materials.json is up to date`; the diff replaces the empty placeholder with a few dozen ramps, each carrying a `note`. Open `data/aitd1/materials-survey/survey.json` and glance at the sheets; a hand pass (setting `"label"` on ramps and re-running `emit`) is the user's, later. `tests/test_materials.py::test_default_table_is_cached_and_full_length` must still pass on the emitted file.

- [ ] **Step 7: Run the tools and render groups**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest -m "tools or render or meta" -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add tools/bootstrap_materials.py tests/test_bootstrap_materials.py Makefile .gitignore PyAitD/render/materials.json
git commit -m "feat: bootstrap the material table from palette ramps and body usage"
```

---

### Task 3: `occlusion.py` — rest-pose vertex AO

**Files:**
- Create: `PyAitD/render/occlusion.py`, `tests/test_occlusion.py`

**Interfaces:**
- Consumes: `PyAitD.render.geometry.pose_geometry`, `PyAitD.render.geometry._vertex_normals`.
- Produces: `hemisphere_directions(count) -> (count, 3) float64 unit vectors over the whole sphere`, `occlusion_of(vertices, tris, rays=32) -> (N,) float32 in 0..1 (1 = open)`, `bake_vertex_ao(body, rays=32) -> (N,) float32`, `DEFAULT_RAYS = 32`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_occlusion.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
import numpy as np
import pytest

from PyAitD.engine.formats import Body, Group, Primitive
from PyAitD.render.occlusion import DEFAULT_RAYS, bake_vertex_ao, hemisphere_directions, occlusion_of

pytestmark = pytest.mark.render


def _box(size=100.0):
    """A closed cube as (8,3) vertices and (12,3) triangles, winding mixed
    on purpose: FITD polygons have no consistent orientation."""
    s = size
    v = np.array([[-s, -s, -s], [s, -s, -s], [s, s, -s], [-s, s, -s],
                  [-s, -s, s], [s, -s, s], [s, s, s], [-s, s, s]], np.float32)
    quads = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (0, 3, 7, 4), (1, 2, 6, 5)]
    tris = []
    for i, (a, b, c, d) in enumerate(quads):
        if i % 2:
            tris += [(a, b, c), (a, c, d)]
        else:
            tris += [(c, b, a), (d, c, a)]
    return v, np.array(tris, np.int32)


def test_hemisphere_directions_are_unit_and_spread():
    d = hemisphere_directions(64)
    assert d.shape == (64, 3)
    assert np.allclose(np.linalg.norm(d, axis=1), 1.0)
    assert np.abs(d.mean(axis=0)).max() < 0.15      # not bunched on one side


def test_a_lone_triangle_is_fully_open():
    v = np.array([[0, 0, 0], [100, 0, 0], [0, 100, 0]], np.float32)
    ao = occlusion_of(v, np.array([[0, 1, 2]], np.int32))
    assert ao.dtype == np.float32 and ao.shape == (3,)
    assert np.array_equal(ao, np.ones(3, np.float32))   # its own triangle never occludes it


def test_a_vertex_inside_a_closed_box_is_fully_occluded():
    v, tris = _box()
    v = np.vstack([v, [[0.0, 0.0, 0.0]]]).astype(np.float32)   # an unreferenced centre vertex
    ao = occlusion_of(v, tris)
    assert ao[8] == 0.0


def test_the_outside_of_a_box_is_open():
    v, tris = _box()
    ao = occlusion_of(v, tris)
    # whichever way a corner's mixed-winding normal points, the bake keeps
    # the open hemisphere; a few grazing rays may still clip a face
    assert (ao > 0.6).all(), ao


def test_a_floor_vertex_beside_a_wall_is_about_half_occluded():
    s = 1000.0
    floor = np.array([[-s, 0, -s], [s, 0, -s], [s, 0, s], [-s, 0, s]], np.float32)
    # a wall through the floor at x=100, spanning y in [-s, s] (y grows
    # downward in FITD): whichever hemisphere the bake picks, half of it
    # looks into the wall
    wall = np.array([[100, s, -s], [100, s, s], [100, -s, s], [100, -s, -s]], np.float32)
    v = np.vstack([floor, wall, [[0.0, 0.0, 0.0]]]).astype(np.float32)
    tris = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]], np.int32)
    # give the probe vertex a floor triangle so its normal is the floor's
    tris = np.vstack([tris, [[8, 1, 2]]]).astype(np.int32)
    ao = occlusion_of(v, tris, rays=256)
    assert 0.3 < ao[8] < 0.7, ao[8]


def test_bake_is_deterministic_and_handles_a_triangle_less_body():
    v, tris = _box()
    a = occlusion_of(v, tris)
    b = occlusion_of(v, tris)
    assert np.array_equal(a, b)
    body = Body(0, (0,) * 6, (), [(0, 0, 0), (10, 0, 0)], [], [], [Primitive(0, 0, 1, [0, 1])])
    assert np.array_equal(bake_vertex_ao(body), np.ones(2, np.float32))


def test_bake_uses_the_assembled_rest_pose():
    # Two groups: group 1's vertices are stored relative to its base vertex
    # in group 0 (skel.pose_vertices adds the base). A bake on the raw
    # vertices would see the box and the probe in the wrong places; a bake
    # on the assembled rest pose puts the probe inside the box.
    s = 100
    box = [(-s, -s, -s), (s, -s, -s), (s, s, -s), (-s, s, -s), (-s, -s, s), (s, -s, s), (s, s, s), (-s, s, s)]
    verts = box + [(500, 0, 0)] + [(-500, 0, 0)]   # probe stored relative to vertex 8 -> lands at the origin
    quads = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (0, 3, 7, 4), (1, 2, 6, 5)]
    prims = [Primitive(1, 0, 1, list(q)) for q in quads]
    groups = [Group(0, 9, 0, 0xFF, 0, 0, 0, 0), Group(9, 1, 8, 0xFF, 1, 0, 0, 0)]
    body = Body(0, (0,) * 6, (), verts, groups, [0, 1], prims)
    ao = bake_vertex_ao(body, rays=DEFAULT_RAYS)
    assert ao.shape == (10,)
    assert ao[9] == 0.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_occlusion.py -q`
Expected: FAIL — `ModuleNotFoundError: PyAitD.render.occlusion`.

- [ ] **Step 3: Write `occlusion.py`**

Create `PyAitD/render/occlusion.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Rest-pose per-vertex ambient occlusion for a FITD body.

Baked once per body (AssetResolver.geometry_ao memoises it) on the
assembled rest pose, then interpolated by the GL backend as a darkening
factor. Hemisphere rays around each vertex normal are intersected with
every triangle of the same body; the open fraction is the vertex's AO.
Rest-pose only: limbs pressed together by an animation do not darken each
other (spec, Limitations). Pure numpy."""
import numpy as np

from PyAitD.render.geometry import _vertex_normals, pose_geometry

DEFAULT_RAYS = 32
_CHUNK = 4096          # rays per intersection batch: caps the (rays, tris) broadcast
_RELATIVE_EPSILON = 1e-3


def hemisphere_directions(count):
    """`count` unit vectors spread over the whole sphere (Fibonacci
    lattice); occlusion_of mirrors each into a vertex's own hemisphere."""
    i = np.arange(count, dtype=np.float64) + 0.5
    phi = np.arccos(1.0 - 2.0 * i / count)
    theta = np.pi * (1.0 + 5 ** 0.5) * i
    return np.stack([np.cos(theta) * np.sin(phi), np.sin(theta) * np.sin(phi), np.cos(phi)], axis=1)


def _any_hit(origins, directions, a, b, c):
    """Möller-Trumbore over every (ray, triangle) pair; True where a ray
    hits any triangle in front of it. Both facings count: FITD polygons
    have no consistent winding."""
    e1, e2 = b - a, c - a                                     # (M,3)
    hits = np.zeros(len(origins), dtype=bool)
    for start in range(0, len(origins), _CHUNK):
        o = origins[start:start + _CHUNK][:, None, :]         # (R,1,3)
        d = directions[start:start + _CHUNK][:, None, :]
        p = np.cross(d, e2[None, :, :])                        # (R,M,3)
        det = np.einsum("rmk,mk->rm", p, e1)
        valid = np.abs(det) > 1e-9
        inv = np.where(valid, 1.0 / np.where(valid, det, 1.0), 0.0)
        t_vec = o - a[None, :, :]
        u = np.einsum("rmk,rmk->rm", t_vec, p) * inv
        q = np.cross(t_vec, e1[None, :, :])
        v = np.einsum("rmk,rmk->rm", d, q) * inv
        t = np.einsum("mk,rmk->rm", e2, q) * inv
        hit = valid & (u >= 0.0) & (v >= 0.0) & (u + v <= 1.0) & (t > 0.0)
        hits[start:start + _CHUNK] = hit.any(axis=1)
    return hits


def occlusion_of(vertices, tris, rays=DEFAULT_RAYS):
    """(N,) float32, 1 = fully open, for `vertices` against `tris`: the
    more open of the two hemispheres about each vertex's normal."""
    vertices = np.asarray(vertices, dtype=np.float64).reshape(-1, 3)
    tris = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    if len(tris) == 0 or len(vertices) == 0:
        return np.ones(len(vertices), dtype=np.float32)
    normals = _vertex_normals(vertices.astype(np.float32), tris.astype(np.int32),
                              np.zeros(len(vertices), dtype=np.int32)).astype(np.float64)
    extent = np.ptp(vertices, axis=0).max()
    epsilon = max(extent, 1.0) * _RELATIVE_EPSILON
    base = hemisphere_directions(rays)                        # (R,3)
    # mirror each direction into the hemisphere around this vertex's normal
    dots = normals @ base.T                                   # (N,R)
    dirs = np.where(dots[:, :, None] < 0.0, -base[None, :, :], base[None, :, :])   # (N,R,3)
    a, b, c = vertices[tris[:, 0]], vertices[tris[:, 1]], vertices[tris[:, 2]]
    # FITD winding cannot say which side of a surface is outside, so the
    # accumulated normal may point into the body. Cast both hemispheres
    # and keep the more open one: outside a closed body that is the real
    # outside; inside it both are shut; on a single-sided polygon the far
    # side is open, which is the safe answer (no false darkening).
    open_fraction = np.zeros(len(vertices))
    for sign in (1.0, -1.0):
        d = dirs * sign
        origins = vertices[:, None, :] + normals[:, None, :] * (epsilon * sign) + d * epsilon
        hits = _any_hit(origins.reshape(-1, 3), d.reshape(-1, 3), a, b, c).reshape(len(vertices), rays)
        open_fraction = np.maximum(open_fraction, 1.0 - hits.mean(axis=1))
    return open_fraction.astype(np.float32)


def bake_vertex_ao(body, rays=DEFAULT_RAYS):
    """AO for every vertex of `body` in its assembled rest pose: zero
    animation deltas, no actor rotation, group base offsets applied --
    what skel.pose_vertices produces for an idle actor."""
    geometry = pose_geometry(body, [(0, (0, 0, 0))] * len(body.groups))
    return occlusion_of(geometry.vertices, geometry.tris, rays)
```

- [ ] **Step 4: Run the tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_occlusion.py -q`
Expected: PASS. A corner whose three mixed-winding faces cancel gets `_CAMERA_FACING` as its normal; the two-hemisphere rule still finds its open side, which is why the box test passes without any orientation heuristic.

- [ ] **Step 5: Time the bake on real data (data present)**

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python - <<'EOF'
import time
from PyAitD.engine.assets import Assets
from PyAitD.games.aitd1.profile import AITD1
from PyAitD.render.occlusion import bake_vertex_ao
a = Assets("data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK", AITD1)
worst = 0.0
for n in range(a.num_bodies):
    try:
        body = a.body(n)
    except Exception:
        continue
    t = time.perf_counter(); bake_vertex_ao(body); worst = max(worst, time.perf_counter() - t)
print(f"worst bake {worst * 1000:.1f} ms over {a.num_bodies} bodies")
EOF
```

Expected: worst case well under 100 ms (two hemispheres × 32 rays × every triangle). If a body exceeds that, lowering `_CHUNK` is not the fix (it trades memory for time); halve `DEFAULT_RAYS` to 16 and note it in the commit message.

- [ ] **Step 6: Commit**

```bash
git add PyAitD/render/occlusion.py tests/test_occlusion.py
git commit -m "feat: rest-pose per-vertex ambient occlusion bake"
```

---

### Task 4: `rest`, `ao`, the resolver, and the frame

Carries the bake and the table to where the backend can reach them. No backend change yet, so no pixel changes.

**Files:**
- Modify: `PyAitD/render/geometry.py:20-31` (`BodyGeometry`), `PyAitD/render/geometry.py:101-105` (`pose_geometry`)
- Modify: `PyAitD/render/asset_resolver.py:43-53` (`__init__`, `body`)
- Modify: `PyAitD/render/scene.py:97-105` (`ActorDraw`), `PyAitD/render/scene.py:143-171` (`build_frame`)
- Test: `tests/test_geometry.py`, `tests/test_asset_resolver.py`, `tests/test_scene.py`

**Interfaces:**
- Consumes: `occlusion.bake_vertex_ao`, `materials.MaterialTable`, `materials.default_table`.
- Produces: `BodyGeometry.rest: (N,3) float32`, `BodyGeometry.ao: (N,) float32` (both filled in `__post_init__` when constructed without them); `pose_geometry(body, group_states, actor_angles=None, ao=None)`; `AssetResolver.material_table(num) -> MaterialTable`, `AssetResolver.geometry_ao(num) -> np.ndarray`; `ActorDraw.materials: MaterialTable` (default `default_table()`).

- [ ] **Step 1: Write the failing geometry tests**

Append to `tests/test_geometry.py`:

```python
def test_rest_is_the_raw_body_vertices_whatever_the_pose():
    body = _cube_body()
    posed = pose_geometry(body, [], (100, 200, 300))
    assert np.array_equal(posed.rest, np.array(body.vertices, np.float32))
    assert not np.array_equal(posed.rest, posed.vertices)   # the actor rotation moved the pose, not the rest


def test_ao_defaults_to_ones_and_takes_a_baked_array():
    body = _cube_body()
    geo = pose_geometry(body, [], None)
    assert geo.ao.dtype == np.float32 and np.array_equal(geo.ao, np.ones(8, np.float32))
    baked = np.linspace(0, 1, 8).astype(np.float32)
    assert np.array_equal(pose_geometry(body, [], None, ao=baked).ao, baked)
    with pytest.raises(ValueError, match="ao"):
        pose_geometry(body, [], None, ao=np.ones(3, np.float32))


def test_body_geometry_constructed_positionally_fills_rest_and_ao():
    v = np.zeros((3, 3), np.float32)
    n = np.zeros((3, 3), np.float32)
    geo = BodyGeometry(v, n, np.zeros((0, 3), np.int32), np.zeros(0, np.uint8),
                       np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), (),
                       np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))
    assert geo.rest is v and np.array_equal(geo.ao, np.ones(3, np.float32))
```

- [ ] **Step 2: Run to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_geometry.py -q`
Expected: FAIL — `BodyGeometry` has no `rest`.

- [ ] **Step 3: Extend `BodyGeometry` and `pose_geometry`**

In `PyAitD/render/geometry.py`, the dataclass becomes:

```python
@dataclass(frozen=True)
class BodyGeometry:
    vertices: np.ndarray      # (N,3) float32, posed model space (FITD units)
    normals: np.ndarray       # (N,3) float32 unit
    tris: np.ndarray          # (M,3) int32 indices into vertices
    tri_colors: np.ndarray    # (M,) uint8
    lines: np.ndarray         # (L,2) int32
    line_colors: np.ndarray   # (L,) uint8
    spheres: tuple            # ((centre_idx:int, radius:float, color:int), ...)
    points: np.ndarray        # (P,) int32
    point_sizes: np.ndarray   # (P,) uint8: 1 (type 2/7) or 2 (others)
    point_colors: np.ndarray  # (P,) uint8
    rest: np.ndarray = None   # (N,3) float32, the body's raw vertices: stable per vertex across poses
    ao: np.ndarray = None     # (N,) float32 rest-pose occlusion, 1 = open

    def __post_init__(self):
        # Both default from `vertices` so every positional constructor
        # (tests, tools) keeps working: rest = the posed vertices (only
        # wrong for an animated body, and only for detail placement), ao =
        # fully open.
        if self.rest is None:
            object.__setattr__(self, "rest", self.vertices)
        if self.ao is None:
            object.__setattr__(self, "ao", np.ones(len(self.vertices), dtype=np.float32))
```

and `pose_geometry`:

```python
def pose_geometry(body, group_states, actor_angles=None, ao=None):
    vertices = np.array(pose_vertices(body, group_states, actor_angles), dtype=np.float32).reshape(-1, 3)
    tris, tri_colors, lines, line_colors, spheres, points, point_sizes, point_colors = _triangulate(body)
    normals = _vertex_normals(vertices, tris, vertex_groups(body))
    rest = np.array(body.vertices, dtype=np.float32).reshape(-1, 3)
    if ao is None:
        ao = np.ones(len(vertices), dtype=np.float32)
    else:
        ao = np.asarray(ao, dtype=np.float32).reshape(-1)
        if len(ao) != len(vertices):
            raise ValueError(f"ao has {len(ao)} entries for {len(vertices)} vertices")
    return BodyGeometry(vertices, normals, tris, tri_colors, lines, line_colors,
                        spheres, points, point_sizes, point_colors, rest, ao)
```

- [ ] **Step 4: Run the geometry tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_geometry.py -q`
Expected: PASS.

- [ ] **Step 5: Write the failing resolver and scene tests**

Append to `tests/test_asset_resolver.py`:

```python
def test_material_table_is_the_default_and_memoised():
    from PyAitD.render.materials import default_table
    resolver = AssetResolver(SimpleNamespace(body=lambda n: n), None)
    assert resolver.material_table(3) is default_table()
    assert resolver.material_table(3) is resolver.material_table(3)


def test_geometry_ao_bakes_once_per_body():
    from PyAitD.engine.formats import Body, Primitive
    calls = []
    body = Body(0, (0,) * 6, (), [(0, 0, 0), (100, 0, 0), (0, 100, 0)], [], [], [Primitive(1, 0, 1, [0, 1, 2])])

    def counting_body(num):
        calls.append(num)
        return body

    resolver = AssetResolver(SimpleNamespace(body=counting_body), None)
    first = resolver.geometry_ao(7)
    second = resolver.geometry_ao(7)
    assert first is second and calls == [7]
    assert np.array_equal(first, np.ones(3, np.float32))
```

In `tests/test_scene.py`, `_StubResolver` gains:

```python
    def material_table(self, num):
        from PyAitD.render.materials import default_table
        return default_table()

    def geometry_ao(self, num):
        return np.full(len(self._bodies[num].vertices), 0.5, np.float32)
```

and `test_build_frame_assembles_frame_description_from_stubs` gains, after the `mask_ids` assertions:

```python
    # the resolver's bake and table ride on each ActorDraw
    from PyAitD.render.materials import default_table
    for actor in frame.actors:
        assert actor.materials is default_table()
        assert (actor.geometry.ao == 0.5).all()
```

- [ ] **Step 6: Run to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_asset_resolver.py tests/test_scene.py -q`
Expected: FAIL — `AssetResolver` has no `material_table`; `ActorDraw` has no `materials`.

- [ ] **Step 7: Wire the resolver and the frame**

In `PyAitD/render/asset_resolver.py`, imports gain:

```python
from PyAitD.render.materials import default_table
from PyAitD.render.occlusion import bake_vertex_ao
```

`__init__` gains `self._material_tables = {}` and `self._aos = {}`; after `body`:

```python
    def material_table(self, num):
        """The MaterialTable for body `num`: the committed default. (A
        per-body override lands in a later task.) Memoised per body."""
        if num not in self._material_tables:
            self._material_tables[num] = default_table()
        return self._material_tables[num]

    def geometry_ao(self, num):
        """Rest-pose vertex AO for body `num`, baked once per session."""
        if num not in self._aos:
            self._aos[num] = bake_vertex_ao(self.body(num))
        return self._aos[num]
```

In `PyAitD/render/scene.py`: import `from dataclasses import dataclass, field` and `from PyAitD.render.materials import MaterialTable, default_table`; `ActorDraw` gains a last field:

```python
    materials: MaterialTable = field(default_factory=default_table)
```

`build_frame`'s `ActorDraw(...)` call becomes:

```python
        actors.append(ActorDraw(
            index,
            pose_geometry(body, states, angles, ao=resolver.geometry_ao(actor.body_num)),
            position,
            actor.room,
            tuple(actor.zv),
            logical,
            tuple(m.id for m in masks if mask_applies_to_actor(m, actor.room, actor.zv)),
            resolver.material_table(actor.body_num),
        ))
```

- [ ] **Step 8: Run the render group**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest -m "render or meta" -q`
Expected: PASS, including every existing GL test (the backend ignores the new fields for now).

- [ ] **Step 9: Commit**

```bash
git add PyAitD/render/geometry.py PyAitD/render/asset_resolver.py PyAitD/render/scene.py tests/test_geometry.py tests/test_asset_resolver.py tests/test_scene.py
git commit -m "feat: carry rest-pose vertices, baked AO and the material table through the frame"
```

---

### Task 5: The material texture and the extended `scene` shader

The heart of the plan. Step 1 captures a golden render with the **unchanged** backend before any shader edit; every later step must keep `realism="classic"` equal to it.

**Files:**
- Create: `tests/golden/scene_lit_classic.npy`, `tests/golden/__init__.py` (empty apart from the SPDX line — `tests/test_test_groups.py` only scans `test_*.py`, but the SPDX scan in `tests/test_layering.py` covers every `.py` under `tests/`)
- Modify: `PyAitD/render/render_gl.py:68-118` (`_ACTOR_VSH`, `_ACTOR_FSH`), `:120-124` (`_SCREEN_VSH`), `:216-247` (`__init__` attributes), `:310-330` (`release`), `:433-476` (`_draw_frame` uniforms), `:498-520` (the per-actor loop), `:647-686` (`_draw_actor`, `_triangle_data`, `_render_triangles`)
- Test: `tests/test_render_gl.py`

**Interfaces:**
- Consumes: `BodyGeometry.rest/.ao`, `ActorDraw.materials`, `MaterialTable.parameters()`, `materials.PRESETS`, `RenderOptions.realism`.
- Produces: `GLBackend._material_tex` (256×2 RGBA32F), `CONTACT_HEIGHT = 150.0`, the 14-float vertex layout `3f 3f 3f 3f 1f 1f` (`in_pos in_normal in_color in_rest in_ao in_index`).

- [ ] **Step 1: Capture the golden render with the pre-change backend**

Add these helpers and test to `tests/test_render_gl.py` (after `_facing_tri`):

```python
def _golden_frame():
    """A fixed synthetic scene-lit frame: two facing triangles, one sphere,
    a slanted light. Rendered once by the pre-materials backend into
    tests/golden/scene_lit_classic.npy; realism="classic" must reproduce
    it byte for byte forever after."""
    from PyAitD.render.lighting import SceneLight
    light = SceneLight((0.3, -0.5, -0.8), (0.9, 0.8, 0.7), (0.2, 0.2, 0.3), 0.7)
    body = _facing_tri(600.0, 1, (0.0, -0.6, -0.8))
    sphere = BodyGeometry(
        np.array([[300.0, 0.0, 700.0]], np.float32), np.array([[0.0, 0.0, -1.0]], np.float32),
        np.zeros((0, 3), np.int32), np.zeros(0, np.uint8),
        np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), ((0, 120.0, 2),),
        np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))
    actors = (_standing_actor(0, body, 400.0), _standing_actor(1, sphere, 400.0))
    return FrameDescription(_view(), ImageAsset(np.full((200, 320, 3), 40, np.uint8), False),
                            _palette(), actors, (), light)


GOLDEN = pathlib.Path(__file__).parent / "golden" / "scene_lit_classic.npy"


def test_classic_realism_matches_the_pre_materials_golden(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene", msaa=0, realism="classic"))
    backend.draw(_golden_frame())
    out = backend.read_rgb()
    backend.release()
    if not GOLDEN.is_file():
        pytest.skip(f"{GOLDEN} not captured yet")
    assert np.array_equal(out, np.load(GOLDEN))
```

Add `import pathlib` to the test file's imports. Then capture the golden with the current backend:

```bash
mkdir -p tests/golden && printf '# SPDX-License-Identifier: GPL-2.0-only\n' > tests/golden/__init__.py
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python - <<'EOF'
import numpy as np, moderngl
import tests.test_render_gl as t
from PyAitD.render.render_gl import GLBackend
from PyAitD.render.render_options import RenderOptions
ctx = moderngl.create_standalone_context(require=330)
b = GLBackend(ctx, RenderOptions(scale=1, shading="smooth", lighting="scene", msaa=0, realism="classic"))
b.draw(t._golden_frame()); np.save(t.GOLDEN, b.read_rgb()); b.release(); ctx.release()
print(t.GOLDEN, np.load(t.GOLDEN).shape)
EOF
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -k golden -q
```

Expected: `(200, 320, 3)` printed, the test PASSES. Commit this alone so the golden's provenance is a commit with no shader change:

```bash
git add tests/golden tests/test_render_gl.py
git commit -m "test: golden render of a scene-lit frame, the realism=classic identity net"
```

- [ ] **Step 2: Write the failing shader tests**

Append to `tests/test_render_gl.py`:

```python
def _table_of(name):
    from PyAitD.render.materials import parse_table
    return parse_table({"ramps": [{"lo": 0, "hi": 255, "class": name}]})


def _material_actor(index, geometry, table, feet_y=400.0):
    zv = (0, 0, feet_y - 200, feet_y, 0, 0)
    return ActorDraw(index, geometry, (0.0, 0.0, 0.0), 0, zv, RenderResult([], []), (), table)


def _enhanced_backend(gl_ctx):
    return GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene", msaa=0, realism="enhanced"))


def _centre(rgb):
    # _facing_tri projects to the upper-left half of the 80..240 x 20..180
    # square (its hypotenuse is x + y = 260); (130, 80) is well inside it.
    return rgb[80, 130].astype(int)


def test_classic_ignores_the_material_table(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene", msaa=0, realism="classic"))
    tri = _facing_tri(600.0, 1, (0.0, 0.0, -1.0))
    backend.draw(_lit_frame([_material_actor(0, tri, _table_of("metal"))], (0.0, 0.0, -1.0)))
    metal = backend.read_rgb().copy()
    backend.draw(_lit_frame([_material_actor(0, tri, _table_of("matte"))], (0.0, 0.0, -1.0)))
    assert np.array_equal(backend.read_rgb(), metal)
    backend.release()


def test_metal_is_brighter_than_matte_under_enhanced(gl_ctx):
    # n = l = view = the half-vector: the highlight lands dead centre.
    backend = _enhanced_backend(gl_ctx)
    tri = _facing_tri(600.0, 1, (0.0, 0.0, -1.0))
    backend.draw(_lit_frame([_material_actor(0, tri, _table_of("matte"))], (0.0, 0.0, -1.0)))
    matte = _centre(backend.read_rgb())
    backend.draw(_lit_frame([_material_actor(0, tri, _table_of("metal"))], (0.0, 0.0, -1.0)))
    metal = _centre(backend.read_rgb())
    assert metal.sum() > matte.sum() + 30
    backend.release()


def test_rim_brightens_the_silhouette_edge_not_the_centre(gl_ctx, monkeypatch):
    from PyAitD.render import materials
    monkeypatch.setitem(materials.CLASS_PRESETS, "glass", materials.Material(1.0, 0.0, 0.0, 1.0, 0.0, 1.0, 0))
    sphere = BodyGeometry(
        np.array([[0.0, 0.0, 600.0]], np.float32), np.array([[0.0, 0.0, -1.0]], np.float32),
        np.zeros((0, 3), np.int32), np.zeros(0, np.uint8),
        np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), ((0, 300.0, 1),),
        np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))
    backend = _enhanced_backend(gl_ctx)
    backend.draw(_lit_frame([_material_actor(0, sphere, _table_of("matte"))], (0.0, 0.0, -1.0)))
    plain = backend.read_rgb().astype(int)
    backend.draw(_lit_frame([_material_actor(0, sphere, _table_of("glass"))], (0.0, 0.0, -1.0)))
    rimmed = backend.read_rgb().astype(int)
    backend.release()
    # sphere radius 300 at depth 1600 with focal 320 -> ~60 px on screen
    edge = (100, 160 + 55)
    assert rimmed[edge].sum() > plain[edge].sum() + 30
    assert abs(rimmed[100, 160].sum() - plain[100, 160].sum()) <= 6


def test_detail_varies_across_a_flat_face_only_under_enhanced(gl_ctx, monkeypatch):
    from PyAitD.render import materials
    monkeypatch.setitem(materials.CLASS_PRESETS, "wood", materials.Material(1.0, 0.0, 0.0, 0.0, 1.0, 50.0, 1))
    tri = _facing_tri(600.0, 1, (0.0, 0.0, -1.0))
    frame = _lit_frame([_material_actor(0, tri, _table_of("wood"))], (0.0, 0.0, -1.0))
    backend = _enhanced_backend(gl_ctx)
    backend.draw(frame)
    grained = backend.read_rgb()[60:100, 100:150, 0].astype(int)   # inside the triangle
    backend.release()
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene", msaa=0, realism="classic"))
    backend.draw(frame)
    flat = backend.read_rgb()[60:100, 100:150, 0].astype(int)
    backend.release()
    assert grained.std() > 2.0
    assert flat.std() == 0.0


def test_occluded_vertices_are_darker_under_enhanced(gl_ctx):
    base = _facing_tri(600.0, 1, (0.0, 0.0, -1.0))
    shut = BodyGeometry(base.vertices, base.normals, base.tris, base.tri_colors, base.lines, base.line_colors,
                        base.spheres, base.points, base.point_sizes, base.point_colors,
                        base.rest, np.zeros(3, np.float32))
    backend = _enhanced_backend(gl_ctx)
    backend.draw(_lit_frame([_material_actor(0, base, _table_of("matte"))], (0.0, 0.0, -1.0)))
    open_ = _centre(backend.read_rgb())
    backend.draw(_lit_frame([_material_actor(0, shut, _table_of("matte"))], (0.0, 0.0, -1.0)))
    closed = _centre(backend.read_rgb())
    backend.release()
    assert closed.sum() < open_.sum() - 30


def test_contact_darkens_toward_the_feet_under_enhanced(gl_ctx):
    # feet at y=400 (the zv lower bound); the triangle spans y in -400..400,
    # so its bottom rows sit at the plane and its top rows are far above it.
    tri = _facing_tri(600.0, 1, (0.0, 0.0, -1.0))
    backend = _enhanced_backend(gl_ctx)
    backend.draw(_lit_frame([_material_actor(0, tri, _table_of("matte"), feet_y=400.0)], (0.0, 0.0, -1.0)))
    rgb = backend.read_rgb().astype(int)
    backend.release()
    # (120, 60) is high on the face (world y = -200, above contact_height:
    # no darkening); (85, 170) is 50 world units above the feet (world y =
    # 350), inside the hypotenuse x + y < 260, and inside the contact fade.
    top, bottom = rgb[60, 120], rgb[170, 85]
    assert bottom.sum() < top.sum() - 20
```

Also, in `test_init_failure_releases_every_already_allocated_gl_object`, add `"_material_tex"` to the attribute tuple and change the count:

```python
    assert leak_checked == 25  # every GL resource __init__ allocates, none skipped
```

- [ ] **Step 3: Run to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q`
Expected: the six new tests and the leak test FAIL; everything else passes.

- [ ] **Step 4: The shaders**

In `PyAitD/render/render_gl.py`, replace `_ACTOR_VSH`:

```python
_ACTOR_VSH = """
#version 330
uniform mat4 mvp; uniform mat3 rot;
in vec3 in_pos; in vec3 in_normal; in vec3 in_color; in vec3 in_rest; in float in_ao; in float in_index;
out vec3 v_color; out vec3 v_normal; out vec3 v_rest; out float v_ao; flat out float v_index; out float v_world_y;
void main() {
    gl_Position = mvp * vec4(in_pos, 1.0);
    v_color = in_color; v_normal = rot * in_normal;
    v_rest = in_rest; v_ao = in_ao; v_index = in_index;
    v_world_y = in_pos.y;   // in_pos is already world space: the actor position was added on the CPU
}
"""
```

Replace `_ACTOR_FSH`'s declarations and the `lighting == 1` tail. The whole shader becomes:

```python
_ACTOR_FSH = """
#version 330
uniform int shading; uniform int lighting;
// key_tint/fill_tint are shading_terms()'s *normalised tints*, not
// reflectances: they carry the room's hue and sum to a peak of 1.0. The
// shadow composite's `shadow_color` is the other thing -- SceneLight's raw
// ambient, an absolute reflectance. Same room, two different quantities.
uniform vec3 light; uniform vec3 key_tint; uniform vec3 fill_tint;
uniform sampler2D mask_tex; uniform vec2 target_size;
// Materials (scene lighting only). material_tex is 256x2 RGBA32F: row 0 is
// (roughness, specular, metallic, rim), row 1 (detail, detail_scale,
// detail_kind, 0) for the palette index in v_index. preset_a/preset_b are
// the RealismPreset strengths (spec, rim, ao) and (contact, detail,
// hemisphere); under realism=classic all six are 0 and every term below
// is exactly 1.0 or 0.0, leaving `base` untouched.
uniform sampler2D material_tex;
uniform vec3 preset_a; uniform vec3 preset_b;
uniform float plane_y; uniform float contact_height;
in vec3 v_color; in vec3 v_normal; in vec3 v_rest; in float v_ao; flat in float v_index; in float v_world_y;
out vec4 f_color;

float hash3(vec3 p) {
    p = fract(p * 0.3183099 + vec3(0.1, 0.2, 0.3));
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}
float value_noise(vec3 p) {   // -1..1, C1 continuous
    vec3 i = floor(p); vec3 f = fract(p); f = f * f * (3.0 - 2.0 * f);
    float n = mix(mix(mix(hash3(i), hash3(i + vec3(1, 0, 0)), f.x),
                      mix(hash3(i + vec3(0, 1, 0)), hash3(i + vec3(1, 1, 0)), f.x), f.y),
                  mix(mix(hash3(i + vec3(0, 0, 1)), hash3(i + vec3(1, 0, 1)), f.x),
                      mix(hash3(i + vec3(0, 1, 1)), hash3(i + vec3(1, 1, 1)), f.x), f.y), f.z);
    return n * 2.0 - 1.0;
}
float detail_noise(vec3 p, int kind) {
    if (kind == 1) return value_noise(p);                                                        // grain
    if (kind == 2) return sin(p.x * 6.2832) * sin(p.z * 6.2832) * (0.5 + 0.5 * value_noise(p));  // weave
    if (kind == 3) return value_noise(vec3(p.x * 4.0, p.y * 0.25, p.z * 4.0));                   // streak along y, the limb axis
    if (kind == 4) return value_noise(vec3(p.x * 0.25, p.y * 6.0, p.z * 0.25));                  // brushed across it
    return 0.0;
}

void main() {
    if (texture(mask_tex, gl_FragCoord.xy / target_size).r > 0.5) discard;
    if (shading == 0) {
        // unshaded: flat palette colour, and the only path lines and points take
        f_color = vec4(v_color, 1.0);
        return;
    }
    vec3 n = (shading == 1)
        ? normalize(cross(dFdx(gl_FragCoord.xyz), dFdy(gl_FragCoord.xyz)))
        : normalize(v_normal);
    vec3 l = normalize(light);
    if (lighting == 0) {
        // the pre-scene-light rig, kept byte-identical: abs() because FITD
        // polygons have no consistent winding
        f_color = vec4(v_color * (0.55 + 0.45 * abs(dot(n, l))), 1.0);
        return;
    }
    // Orient rather than fold: -z is toward the camera, so a normal with a
    // positive z faces away from the viewer and is pointing into the body.
    //
    // NOT dead code under shading == 1. There the normal is
    // normalize(cross(dFdx(gl_FragCoord.xyz), dFdy(gl_FragCoord.xyz))),
    // whose z is algebraically a constant +1 before normalisation
    // (dFdx(gl_FragCoord.xy) == (1,0) and dFdy == (0,1) at every
    // fragment), so this branch fires for *every* lambert fragment. That
    // is the point: it makes the derivative normal a camera-facing one,
    // which is what removes the winding dependence FITD geometry cannot
    // provide. Deleting the flip inverts every lambert normal.
    if (n.z > 0.0) n = -n;
    // Half-Lambert: the lit side reaches fill_tint + key_tint, the shadow
    // side falls to fill_tint rather than to black. `base` is the whole of
    // realism=classic's answer and must stay this exact expression.
    float wrapped = clamp(dot(n, l) * 0.5 + 0.5, 0.0, 1.0);
    vec3 base = v_color * (fill_tint + key_tint * wrapped * wrapped);

    int index = int(v_index + 0.5);
    vec4 m0 = texelFetch(material_tex, ivec2(index, 0), 0);
    vec4 m1 = texelFetch(material_tex, ivec2(index, 1), 0);
    vec3 view = vec3(0.0, 0.0, -1.0);                 // from the surface toward the viewer
    vec3 h = normalize(l + view);
    // Camera-space y grows downward, so "up" (the sky half of the
    // hemisphere ambient) is -n.y.
    float hemi = mix(1.0 - 0.3 * preset_b.z, 1.0 + 0.3 * preset_b.z, clamp(-n.y * 0.5 + 0.5, 0.0, 1.0));
    // World y grows downward too: the feet are at plane_y and everything
    // above them has a smaller y. Darkens by up to half at the plane.
    float height = clamp((plane_y - v_world_y) / contact_height, 0.0, 1.0);
    float contact = 1.0 - preset_b.x * 0.5 * (1.0 - height);
    float occl = mix(1.0, v_ao, preset_a.z) * contact;
    float gloss = exp2(1.0 + 10.0 * (1.0 - m0.x));
    vec3 spec = key_tint * mix(vec3(1.0), v_color, m0.z) * pow(max(dot(n, h), 0.0), gloss) * m0.y * preset_a.x;
    vec3 rim = key_tint * pow(1.0 - max(dot(n, view), 0.0), 3.0) * m0.w * preset_a.y;
    float grain = 1.0 + preset_b.y * m1.x * detail_noise(v_rest / m1.y, int(m1.z + 0.5));
    f_color = vec4(base * (grain * hemi * occl) + spec + rim, 1.0);
}
"""
```

`_SCREEN_VSH` (lines/points share `_ACTOR_FSH` with `shading == 0`) must declare the new varyings so the program links on every driver:

```python
_SCREEN_VSH = """
#version 330
in vec3 in_ndc; in vec3 in_color;
out vec3 v_color; out vec3 v_normal; out vec3 v_rest; out float v_ao; flat out float v_index; out float v_world_y;
void main() {
    gl_Position = vec4(in_ndc, 1.0); v_color = in_color; v_normal = vec3(0.0, 0.0, 1.0);
    v_rest = vec3(0.0); v_ao = 1.0; v_index = 0.0; v_world_y = 0.0;
}
"""
```

- [ ] **Step 5: The material texture, the uniforms, the vertex format**

Module level, after `_SHADING_INDEX`:

```python
from PyAitD.render.materials import PALETTE_SIZE, PRESETS
CONTACT_HEIGHT = 150.0   # FITD units over which the contact term fades, roughly shin height
```

In `__init__`'s attribute pre-declaration, after `self._sphere = None`:

```python
        self._material_tex = None
        self._material_key = None
```

Inside the `try`, after `self._stencil_prog = ...`:

```python
            # 256 palette indices x 2 rows of 4 float parameters; uploaded
            # whenever an actor hands over a table object we have not seen.
            self._material_tex = ctx.texture((PALETTE_SIZE, 2), 4, dtype="f4")
            self._material_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
```

In `release()`'s tuple, add `self._material_tex,` after `self._stencil_prog, self._screen_prog, self._actor_prog, self._bg_prog,`, and reset `self._material_key = None` beside `self._bg_key = None`.

In `_draw_frame`, inside the `if scene_lit:` branch after `fill_tint`:

```python
            preset = PRESETS[self._options.realism]
            self._actor_prog["preset_a"].value = (preset.spec, preset.rim, preset.ao)
            self._actor_prog["preset_b"].value = (preset.contact, preset.detail, preset.hemisphere)
            self._actor_prog["contact_height"].value = CONTACT_HEIGHT
            self._material_tex.use(location=3)
            self._actor_prog["material_tex"].value = 3
```

and in the `else:` branch:

```python
            self._actor_prog["preset_a"].value = (0.0, 0.0, 0.0)
            self._actor_prog["preset_b"].value = (0.0, 0.0, 0.0)
```

In the per-actor loop, just before `self._draw_actor(actor, frame, palette)`:

```python
            if scene_lit:
                self._actor_prog["plane_y"].value = float(max(actor.zv[2], actor.zv[3]))
                self._upload_materials(actor.materials)
```

Add the method after `_composite_shadow`:

```python
    def _upload_materials(self, table):
        """Write `table.parameters()` into the material texture unless it is
        the table object uploaded last time (default_table() is cached, so
        every actor on the default shares one object and one upload)."""
        if table is self._material_key:
            return
        params = table.parameters()                      # (256, 8)
        rows = np.stack([params[:, :4], params[:, 4:]], axis=0)   # (2, 256, 4): texture row 0, row 1
        self._material_tex.write(np.ascontiguousarray(rows, dtype="f4").tobytes())
        self._material_key = table
```

`_triangle_data` becomes:

```python
    def _triangle_data(self, geometry, position, palette):
        parts = []
        if len(geometry.tris):
            idx = geometry.tris.reshape(-1)
            pos = geometry.vertices[idx].astype(np.float64) + position
            norm = geometry.normals[idx]
            colors = geometry.tri_colors.repeat(3)
            col = palette[colors]
            rest = geometry.rest[idx]
            ao = geometry.ao[idx][:, None]
            index = colors.astype("f4")[:, None]
            parts.append(np.concatenate(
                [pos.astype("f4"), norm.astype("f4"), col.astype("f4"),
                 rest.astype("f4"), ao.astype("f4"), index], axis=1))
        if geometry.spheres:
            sphere_verts, sphere_tris = self._sphere  # cached, lru_cache-shared: never mutated
            idx = sphere_tris.reshape(-1)
            unit = sphere_verts[idx]  # fancy indexing copies
            for centre_idx, radius, color in geometry.spheres:
                centre = geometry.vertices[centre_idx].astype(np.float64) + position
                pos = (unit.astype(np.float64) * radius + centre).astype("f4")
                norm = unit.astype("f4")
                col = np.tile(palette[color], (len(pos), 1)).astype("f4")
                # rest = the sphere's own surface about its rest centre, so
                # grain is fixed to the ball; ao = open (nothing is baked for
                # spheres, which FITD uses for heads and hands)
                rest = (unit.astype(np.float64) * radius + geometry.rest[centre_idx]).astype("f4")
                ao = np.ones((len(pos), 1), "f4")
                index = np.full((len(pos), 1), float(color), "f4")
                parts.append(np.concatenate([pos, norm, col, rest, ao, index], axis=1))
        if not parts:
            return np.zeros((0, 14), dtype="f4")
        return np.concatenate(parts, axis=0)
```

and `_render_triangles`' vertex array:

```python
        vao = self._ctx.vertex_array(
            self._actor_prog,
            [(buf, "3f 3f 3f 3f 1f 1f", "in_pos", "in_normal", "in_color", "in_rest", "in_ao", "in_index")])
```

- [ ] **Step 6: Run the GL tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q`
Expected: PASS, including `test_classic_realism_matches_the_pre_materials_golden`, `test_fixed_lighting_is_unchanged_by_the_scene_light` and every shadow test.

If the golden test fails by at most 1 in a few pixels, the compiler reassociated `base * (grain * hemi * occl)`. Do **not** relax the test. Restructure so the classic path is literally the old expression: `vec3 lit = base; if (preset_a.z + preset_b.x + preset_b.y + preset_b.z > 0.0) lit = base * (grain * hemi * occl); f_color = vec4(lit + spec + rim, 1.0);` — under classic the branch is skipped and `spec`/`rim` are exact zeros.

If `test_rim_brightens_the_silhouette_edge_not_the_centre` fails at the edge pixel, print `rimmed[100, 150:230].sum(axis=1)` and pick the last non-background column minus 5; the sphere's projected radius depends on `icosphere(1)`'s silhouette, not on an exact 60 px.

- [ ] **Step 7: Tune the presets on the proof fixtures (data present)**

```bash
for r in classic enhanced; do
  SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python - <<EOF
import moderngl, numpy as np, pygame
from tools.prove_graphics import _boot
from PyAitD.render.asset_resolver import AssetResolver
from PyAitD.render.render_gl import GLBackend
from PyAitD.render.render_options import RenderOptions
from PyAitD.render.scene import build_frame
ctx = moderngl.create_standalone_context(require=330)
for name in ("attic", "combat"):
    game, floor = _boot("data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK", name)
    frame, _ = build_frame(game, floor, AssetResolver(game.assets))
    b = GLBackend(ctx, RenderOptions(scale=4, realism="$r")); b.draw(frame); rgb = b.read_rgb(); b.release()
    pygame.image.save(pygame.surfarray.make_surface(np.ascontiguousarray(rgb.swapaxes(0, 1))), f"docs/graphics-proof/{name}-$r.png")
ctx.release()
EOF
done
```

Open `docs/graphics-proof/attic-classic.png` beside `attic-enhanced.png` (both git-ignored). Adjust `CLASS_PRESETS` values and `PRESETS["enhanced"]` in `materials.py` until: skin has a soft highlight and no visible grain at scale 4; cloth reads matte with a faint weave; the floor object bodies (wood/metal) show a highlight that moves with the camera light; no surface goes white; the feet darken slightly. Keep every `detail_scale > 0` and every other value in 0..1. `tests/test_materials.py` pins those ranges.

- [ ] **Step 8: Run the render and meta groups**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest -m "render or meta" -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add PyAitD/render/render_gl.py PyAitD/render/materials.py tests/test_render_gl.py
git commit -m "feat: per-material specular, rim, hemisphere, occlusion, contact and grain under realism=enhanced"
```

---

### Task 6: Per-body material overrides

**Files:**
- Modify: `PyAitD/render/asset_resolver.py` (`override_body_material_path`, `_override`'s loader, `material_table`)
- Modify: `PyAitD/render/override_check.py` (`check_body_materials`, `summarize`)
- Modify: `tools/check_overrides.py:141` (call it)
- Test: `tests/test_asset_resolver.py`, `tests/test_override_check.py`

**Interfaces:**
- Consumes: `materials.parse_assignments`, `materials.default_table`, `MaterialTable.remapped`.
- Produces: `override_body_material_path(override_dir, num) -> Path` (`<dir>/bodies/body<NNN>.json`), `load_json(path) -> object`, `AssetResolver._override(path, validate, load=None)`, `override_check.check_body_materials(override_dir) -> list[Finding]` (findings carry `floor == -2`, `camera == body number`).

- [ ] **Step 1: Write the failing resolver tests**

Append to `tests/test_asset_resolver.py`:

```python
def test_body_material_path_follows_the_convention(tmp_path):
    from PyAitD.render.asset_resolver import override_body_material_path
    assert override_body_material_path(tmp_path, 7) == tmp_path / "bodies" / "body007.json"


def test_material_table_follows_a_per_body_override(tmp_path):
    from PyAitD.render.asset_resolver import override_body_material_path
    from PyAitD.render.materials import default_table
    path = override_body_material_path(tmp_path, 7)
    path.parent.mkdir(parents=True)
    path.write_text('{"indices": {"5": "metal"}, "ramps": [{"lo": 40, "hi": 41, "class": "glass"}]}')
    resolver = AssetResolver(SimpleNamespace(body=lambda n: n), tmp_path)
    table = resolver.material_table(7)
    assert table.classes[5] == "metal" and table.classes[40] == "glass"
    assert table.classes[6] == default_table().classes[6]      # everything else untouched
    assert resolver.material_table(7) is table                 # memoised
    assert resolver.material_table(8) is default_table()       # no file, no change


def test_missing_body_override_is_silent(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        AssetResolver(SimpleNamespace(body=lambda n: n), tmp_path).material_table(3)
    assert caplog.records == []


def test_invalid_body_override_logs_once_and_falls_back(tmp_path, caplog):
    from PyAitD.render.asset_resolver import override_body_material_path
    from PyAitD.render.materials import default_table
    path = override_body_material_path(tmp_path, 2)
    path.parent.mkdir(parents=True)
    path.write_text('{"indices": {"5": "velvet"}}')
    resolver = AssetResolver(SimpleNamespace(body=lambda n: n), tmp_path)
    with caplog.at_level(logging.WARNING):
        assert resolver.material_table(2) is default_table()
        assert resolver.material_table(2) is default_table()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "velvet" in warnings[0].getMessage()
    assert path in resolver.failures
```

- [ ] **Step 2: Run to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_asset_resolver.py -q`
Expected: FAIL — no `override_body_material_path`.

- [ ] **Step 3: The resolver override**

In `PyAitD/render/asset_resolver.py`: `import json` at the top; imports gain `parse_assignments` from `materials`; after `override_screen_path`:

```python
def override_body_material_path(override_dir, num):
    # Per-body material remaps, applied on top of the committed default
    # table. Same shape as PyAitD/render/materials.json.
    return Path(override_dir) / "bodies" / f"body{num:03d}.json"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
```

`_override` takes a loader:

```python
    def _override(self, path, validate, load=None):
        load = self._load_png if load is None else load
        if self._override_dir is None or path in self.failures:
            return None
        if path in self._cache:
            return self._cache[path]
        if not path.is_file():
            # (existing comment unchanged)
            return None
        try:
            loaded = load(path)
            validate(loaded)
        except Exception as exc:  # any loader/validation failure degrades, never crashes
            self.failures[path] = str(exc)
            log.warning("override %s ignored: %s", path, exc)
            return None
        self._cache[path] = loaded
        return loaded
```

(rename the local `pixels` to `loaded`; the callers are unchanged). `material_table` becomes:

```python
    def material_table(self, num):
        """The MaterialTable for body `num`: the committed default with the
        override directory's bodies/body<NNN>.json remapped on top when one
        exists. A missing file is silent; an unreadable or invalid one logs
        once, lands in `failures`, and leaves the default. Memoised per body."""
        if num not in self._material_tables:
            table = default_table()
            if self._override_dir is not None:
                data = self._override(override_body_material_path(self._override_dir, num),
                                      parse_assignments, load=load_json)
                if data is not None:
                    table = table.remapped(parse_assignments(data))
            self._material_tables[num] = table
        return self._material_tables[num]
```

- [ ] **Step 4: Run the resolver tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_asset_resolver.py tests/test_layering.py -q`
Expected: PASS (`load_json` touches no pygame, so `test_asset_resolver_touches_pygame_in_exactly_one_function` holds).

- [ ] **Step 5: Write the failing override_check tests**

Append to `tests/test_override_check.py`:

```python
def test_body_material_findings_name_the_body_and_the_reason(tmp_path):
    from PyAitD.render.asset_resolver import override_body_material_path
    good = override_body_material_path(tmp_path, 1)
    good.parent.mkdir(parents=True)
    good.write_text('{"indices": {"5": "metal"}}')
    override_body_material_path(tmp_path, 2).write_text('{"indices": {"5": "velvet"}}')
    override_body_material_path(tmp_path, 3).write_text('not json')
    f = oc.check_body_materials(tmp_path)
    assert [(x.floor, x.camera, x.kind) for x in f] == [(-2, 2, "invalid"), (-2, 3, "invalid")]
    assert "velvet" in f[0].detail
    assert oc.has_errors(f)
    assert "invalid body 002" in oc.summarize(f, None)


def test_no_bodies_directory_is_no_finding(tmp_path):
    assert oc.check_body_materials(tmp_path) == []
```

- [ ] **Step 6: Run to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_override_check.py -q`
Expected: FAIL — no `check_body_materials`.

- [ ] **Step 7: The check**

In `PyAitD/render/override_check.py`, import `override_body_material_path` from `asset_resolver` and add after `screen_coverage`:

```python
def check_body_materials(override_dir):
    """One Finding per bodies/body<NNN>.json the resolver would reject;
    `floor` is -2, `camera` is the body number. Loads through
    AssetResolver so acceptance stays identical to the game's."""
    bodies = Path(override_dir) / "bodies"
    findings = []
    for path in sorted(bodies.glob("body*.json")):
        try:
            num = int(path.stem[4:])
        except ValueError:
            continue
        resolver = AssetResolver(None, override_dir)
        resolver.material_table(num)
        if path in resolver.failures:
            findings.append(Finding(-2, num, path, "invalid", resolver.failures[path]))
    return findings
```

In `summarize`, the `if f.floor == -1:` branch becomes a chain:

```python
            if f.floor == -1:
                lines.append(f"{f.kind:<7} screen ress{f.camera:02d}  {f.path}: {f.detail}")
            elif f.floor == -2:
                lines.append(f"{f.kind:<7} body {f.camera:03d}  {f.path}: {f.detail}")
            else:
                lines.append(f"{f.kind:<7} floor {f.floor:02d} camera {f.camera:03d}  {f.path}: {f.detail}")
```

`Finding.kind`'s comment gains nothing; `ERROR_KINDS` already contains `"invalid"`.

In `tools/check_overrides.py`, import `check_body_materials` beside `check_screens`, and after `findings = check_overrides(args.overrides, floors, manifest)`:

```python
    findings = findings + check_body_materials(args.overrides)
```

- [ ] **Step 8: Run the render, tools and meta groups**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest -m "render or tools or meta" -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add PyAitD/render/asset_resolver.py PyAitD/render/override_check.py tools/check_overrides.py tests/test_asset_resolver.py tests/test_override_check.py
git commit -m "feat: per-body material overrides under overrides/bodies, checked like every other override"
```

---

### Task 7: The bootstrap tool's `label` stage

**Files:**
- Modify: `tools/bootstrap_materials.py` (`label_stage`, `label_ramps`, `LABEL_SCHEMA`, `label_instructions`, `ask_vision`)
- Test: `tests/test_bootstrap_materials.py`

**Interfaces:**
- Consumes: `tools.regenerate_backgrounds.agy_structured(model, instructions, schema) -> dict`.
- Produces: `LABEL_SCHEMA`, `label_instructions(sheet, highlight) -> str`, `label_ramps(data, ask, threshold) -> int` (ramps labelled; `ask(sheet_path, highlight_path) -> {"class": str, "reason": str}`), `ask_vision(model, out_dir) -> callable`, `label_stage(data, args, survey_path) -> int`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bootstrap_materials.py`:

```python
def _survey_for_labelling():
    return {"ramps": [
        {"lo": 0, "hi": 15, "class": "metal", "confidence": 0.5, "reason": "grey",
         "usage": {"bodies": ["0:1"], "triangles": 2, "groups": [0]},
         "sheet": "sheets/body0-001.png", "highlight": "sheets/ramp000-015.png"},
        {"lo": 16, "hi": 21, "class": "skin", "confidence": 0.8, "reason": "peach",
         "usage": {"bodies": ["0:0"], "triangles": 4, "groups": [1]},
         "sheet": "sheets/body0-000.png", "highlight": "sheets/ramp016-021.png"},
        {"lo": 22, "hi": 22, "class": "matte", "confidence": 0.9, "reason": "unused",
         "usage": {"bodies": [], "triangles": 0, "groups": []}},
        {"lo": 23, "hi": 30, "class": "cloth", "confidence": 0.3, "reason": "blue", "label": "leather",
         "usage": {"bodies": ["0:2"], "triangles": 6, "groups": [2]},
         "sheet": "sheets/body0-002.png", "highlight": "sheets/ramp023-030.png"},
    ]}


def test_label_ramps_asks_only_about_uncertain_unlabelled_ramps_with_sheets():
    data = _survey_for_labelling()
    asked = []

    def ask(sheet, highlight):
        asked.append((sheet, highlight))
        return {"class": "stone", "reason": "it looks like carved stone"}

    assert bm.label_ramps(data, ask, threshold=0.8) == 1
    assert asked == [("sheets/body0-001.png", "sheets/ramp000-015.png")]
    assert data["ramps"][0]["vision_class"] == "stone" and data["ramps"][0]["vision_reason"].startswith("it looks")
    assert "vision_class" not in data["ramps"][1]           # confident enough
    assert "vision_class" not in data["ramps"][2]           # no sheet: nothing to show
    assert data["ramps"][3]["label"] == "leather" and "vision_class" not in data["ramps"][3]   # hand label wins


def test_label_ramps_rejects_a_class_outside_the_vocabulary():
    data = _survey_for_labelling()
    with pytest.raises(ValueError, match="velvet"):
        bm.label_ramps(data, lambda s, h: {"class": "velvet", "reason": ""}, threshold=0.8)


def test_label_instructions_name_both_images_and_every_class():
    text = bm.label_instructions("/a/sheet.png", "/a/high.png")
    assert "/a/sheet.png" in text and "/a/high.png" in text and "magenta" in text
    for name in bm.MATERIAL_CLASSES:
        assert name in text
    assert bm.LABEL_SCHEMA["properties"]["class"]["enum"] == list(bm.MATERIAL_CLASSES)


def test_ask_vision_dictates_the_agy_call(tmp_path, monkeypatch):
    import json as _json
    import subprocess
    import types
    calls = []

    def fake_run(cmd, capture_output=True, text=True, check=True):
        calls.append(cmd)
        return types.SimpleNamespace(
            stdout=_json.dumps({"status": "SUCCESS", "structured_output": {"class": "wood", "reason": "grain"}}),
            stderr="", returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    ask = bm.ask_vision("gemini-3.1-pro", tmp_path)
    assert ask("sheets/body0-001.png", "sheets/ramp000-015.png") == {"class": "wood", "reason": "grain"}
    cmd = calls[0]
    assert cmd[0] == "agy" and "gemini-3.1-pro" in cmd
    assert _json.loads(cmd[cmd.index("--json-schema") + 1]) == bm.LABEL_SCHEMA
    assert str((tmp_path / "sheets/body0-001.png").resolve()) in cmd[2]


def test_label_stage_without_agy_exits_2_and_leaves_the_survey(tmp_path, monkeypatch, capsys):
    import shutil
    data = _survey_for_labelling()
    survey = tmp_path / "survey.json"
    survey.write_text(json.dumps(data))
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert bm.main(["unused", "label", "--out", str(tmp_path)]) == 2
    assert "agy" in capsys.readouterr().err
    assert json.loads(survey.read_text()) == data


def test_label_stage_writes_vision_classes_back(tmp_path, monkeypatch):
    import shutil
    data = _survey_for_labelling()
    (tmp_path / "survey.json").write_text(json.dumps(data))
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/agy")
    monkeypatch.setattr(bm, "ask_vision", lambda model, out: (lambda s, h: {"class": "stone", "reason": "r"}))
    assert bm.main(["unused", "label", "--out", str(tmp_path)]) == 0
    out = json.loads((tmp_path / "survey.json").read_text())
    assert out["ramps"][0]["vision_class"] == "stone"
```

- [ ] **Step 2: Run to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_bootstrap_materials.py -q`
Expected: the six new tests FAIL (`label_ramps` missing).

- [ ] **Step 3: The label stage**

In `tools/bootstrap_materials.py`, replace the stub `label_stage` with:

```python
LABEL_SCHEMA = {
    "type": "object",
    "required": ["class", "reason"],
    "properties": {"class": {"type": "string", "enum": list(MATERIAL_CLASSES)},
                   "reason": {"type": "string"}},
    "additionalProperties": False,
}


def label_instructions(sheet, highlight):
    return (f"Look at the image at {sheet}. It is a flat-shaded render of a low-polygon character or "
            f"object from the 1992 game Alone in the Dark, on a black background. Then look at {highlight}: "
            "the same render with one of its colour ramps painted magenta. Name the real-world material the "
            "magenta surfaces most plausibly represent on this model. Choose exactly one of: "
            + ", ".join(MATERIAL_CLASSES) + ". Use 'matte' when nothing fits. Give a one-sentence reason.")


def ask_vision(model, out_dir):
    """An `ask(sheet, highlight)` over agy, resolving the survey's relative
    sheet paths against `out_dir`."""
    from tools.regenerate_backgrounds import agy_structured
    out_dir = pathlib.Path(out_dir)

    def ask(sheet, highlight):
        return agy_structured(model, label_instructions(
            (out_dir / sheet).resolve(), (out_dir / highlight).resolve()), LABEL_SCHEMA)
    return ask


def label_ramps(data, ask, threshold):
    """Fill `vision_class`/`vision_reason` on every ramp below `threshold`
    that has sheets and no hand `label`. Returns how many were asked."""
    count = 0
    for ramp in data["ramps"]:
        if ramp.get("label") or ramp.get("confidence", 0.0) >= threshold:
            continue
        if not ramp.get("sheet") or not ramp.get("highlight"):
            continue
        answer = ask(ramp["sheet"], ramp["highlight"])
        name = answer.get("class")
        if name not in MATERIAL_CLASSES:
            raise ValueError(f"ramp {ramp['lo']}..{ramp['hi']}: vision model answered {name!r}, "
                             f"not one of {', '.join(MATERIAL_CLASSES)}")
        ramp["vision_class"] = name
        ramp["vision_reason"] = str(answer.get("reason", ""))
        count += 1
    return count


def label_stage(data, args, survey_path):
    if shutil.which("agy") is None:
        print("error: the `agy` CLI is not on PATH; the label stage needs it (survey.json untouched)",
              file=sys.stderr)
        return 2
    asked = label_ramps(data, ask_vision(args.model, args.out), args.threshold)
    _write_json(survey_path, data)
    print(f"{survey_path}: {asked} ramps labelled by {args.model}")
    return 0
```

- [ ] **Step 4: Run the tools group**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest -m "tools or meta" -q`
Expected: PASS. `tests/test_layering.py::test_only_the_regeneration_tool_may_import_an_ai_sdk` still holds: the tool imports no `google*` module.

- [ ] **Step 5: Optionally run it live (agy on PATH, data present)**

```bash
make bootstrap-materials vision=1
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python tools/bootstrap_materials.py unused check
```

Expected: `survey.json` gains `vision_class` on the low-confidence ramps; `emit` re-writes `materials.json` with `vision: ...` in the notes; `check` passes. Review the diff of `materials.json`; if the model's answers look wrong for a ramp, set a hand `"label"` on it in `survey.json` and re-run `emit`. Commit whatever the table is at this point — the hand pass can continue afterwards.

- [ ] **Step 6: Commit**

```bash
git add tools/bootstrap_materials.py tests/test_bootstrap_materials.py PyAitD/render/materials.json
git commit -m "feat: label uncertain palette ramps with a vision model through agy"
```

---

### Task 8: `enhanced` by default, the proof, and the docs

**Files:**
- Modify: `PyAitD/render/render_options.py` (the default)
- Modify: `tools/prove_graphics.py` (`render_fixture`, `output_paths`)
- Modify: `Makefile:85` (the `proof-graphics` help line)
- Create: `docs/graphics-realism-proof.md`
- Modify: `README.md:69-80` (the CLI flag paragraph), `CONTEXT.md:88-95` (render rows), `CONTEXT.md:109` (tools row), `AGENTS.md:14-24` (make targets), `AGENTS.md:173-177` (the AI-service rule)
- Test: `tests/test_render_options.py`, `tests/test_prove_graphics.py`

**Interfaces:**
- Consumes: everything above.
- Produces: the shipped default; `render_fixture(data_dir, name, scale, shading, ctx, realism="enhanced")`; `output_paths(out_dir)` yielding `(name, mode, realism, path)` with `<name>-<mode>-<realism>.png`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_render_options.py`, update:

```python
def test_defaults():
    assert RenderOptions() == RenderOptions(4, "smooth", "bilinear", None, "scene", 4, "enhanced")
    assert SHADING_MODES == ("flat", "lambert", "smooth")
    assert BACKGROUND_FILTERS == ("nearest", "bilinear", "xbr")


def test_realism_defaults_to_enhanced_and_cycles():
    from PyAitD.render.render_options import REALISM_MODES, cycle_realism
    assert REALISM_MODES == ("classic", "enhanced")
    options = RenderOptions()
    assert options.realism == "enhanced"
    assert cycle_realism(options).realism == "classic"
    assert cycle_realism(cycle_realism(options)).realism == "enhanced"
    assert RenderOptions(realism="classic").to_payload()["realism"] == "classic"
```

(`test_realism_defaults_to_classic_and_cycles` is renamed to the above.) In `test_each_invalid_field_falls_back_alone` and `tests/test_config.py::test_save_writes_schema_2_with_render`, the `"realism"` payload values and expected `RenderOptions` trailing argument become `"enhanced"`. In `tests/test_ui_reducers.py::test_graphics_rows_cycle_render_options`, the last assertion becomes `RenderOptions(realism="classic")`.

In `tests/test_prove_graphics.py`:

```python
from PyAitD.render.render_options import REALISM_MODES, SHADING_MODES


def test_render_fixture_produces_scaled_frames(data_dir, gl_ctx):
    rgb = render_fixture(data_dir, "attic", scale=2, shading="smooth", ctx=gl_ctx)
    assert rgb.shape == (400, 640, 3)
    assert rgb.std() > 10  # not a blank frame
    classic = render_fixture(data_dir, "attic", scale=2, shading="smooth", ctx=gl_ctx, realism="classic")
    assert not np.array_equal(rgb, classic)   # the default is enhanced, and it shows


def test_output_paths_covers_every_fixture_shading_mode_and_realism():
    paths = output_paths("docs/graphics-proof")
    assert len(paths) == len(FIXTURES) * len(SHADING_MODES) * len(REALISM_MODES)
    names = {(name, mode, realism) for name, mode, realism, _ in paths}
    assert names == {(n, m, r) for n in FIXTURES for m in SHADING_MODES for r in REALISM_MODES}
    for name, mode, realism, path in paths:
        assert path == pathlib.Path("docs/graphics-proof") / f"{name}-{mode}-{realism}.png"


def test_render_fixture_is_importable_with_the_documented_signature():
    import inspect
    params = list(inspect.signature(render_fixture).parameters)
    assert params == ["data_dir", "name", "scale", "shading", "ctx", "realism"]
```

(`test_output_paths_covers_every_fixture_and_shading_mode` is replaced by the three-axis version.)

- [ ] **Step 2: Run to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_options.py tests/test_prove_graphics.py tests/test_config.py tests/test_ui_reducers.py -q`
Expected: FAIL — default still `"classic"`, `render_fixture` has no `realism`.

- [ ] **Step 3: Flip the default and extend the proof tool**

`PyAitD/render/render_options.py`: `realism: str = "enhanced"`.

`tools/prove_graphics.py`: import `REALISM_MODES`; docstring line 5 becomes "writes one PNG per fixture per shading mode per realism preset";

```python
def render_fixture(data_dir, name, scale, shading, ctx, realism="enhanced"):
    game, floor = _boot(data_dir, name)
    frame, _ = build_frame(game, floor, AssetResolver(game.assets))
    backend = GLBackend(ctx, RenderOptions(scale=scale, shading=shading, realism=realism))
    try:
        backend.draw(frame)
        return backend.read_rgb()
    finally:
        backend.release()


def output_paths(out_dir):
    """(name, mode, realism, path) for every fixture x shading-mode x realism
    combination, in the order rendered and printed by `main`."""
    out_dir = pathlib.Path(out_dir)
    return [
        (name, mode, realism, out_dir / f"{name}-{mode}-{realism}.png")
        for name in FIXTURES
        for mode in SHADING_MODES
        for realism in REALISM_MODES
    ]
```

and in `main`: `for name, mode, realism, path in output_paths(args.out): rgb = render_fixture(args.data, name, args.scale, mode, ctx, realism)`.

`Makefile:85`'s help text: `## Graphics proof: attic + combat fixtures at scale 4 per shading mode x realism preset to docs/graphics-proof/`.

- [ ] **Step 4: Run the whole suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/ -q`
Expected: PASS. A GL test that asserts specific pixels and did not pin `realism` explicitly now renders enhanced; pin `realism="classic"` in such a test rather than updating its expected pixels — it exists to prove the classic path is unchanged. The golden test already pins it.

- [ ] **Step 5: Render the proof and write the proof doc (data present)**

```bash
make prove-graphics
```

Create `docs/graphics-realism-proof.md`:

```markdown
# Actor surface response and materials proof

Date: 2026-08-28
Spec: `docs/superpowers/specs/2026-08-28-actor-surface-and-materials-design.md`

## What changed

Actors now carry a per-material surface under `realism=enhanced` (the
default): a palette-index material table (`PyAitD/render/materials.json`,
bootstrapped by `make bootstrap-materials`, hand-correctable, overridable per
body under `overrides/bodies/body<NNN>.json`) drives specular, a fresnel
rim, a sky/ground hemisphere ambient, rest-pose vertex occlusion, a contact
darkening at the feet and procedural grain glued to each limb.
`realism=classic` reproduces the pre-change output byte for byte
(`tests/golden/scene_lit_classic.npy`).

## Automated gates

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest \
    tests/test_materials.py tests/test_occlusion.py tests/test_bootstrap_materials.py \
    tests/test_geometry.py tests/test_asset_resolver.py tests/test_scene.py \
    tests/test_render_gl.py tests/test_override_check.py tests/test_render_options.py -q
<paste the real output>
```

```
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest -q
<paste the real output>
```

## `make prove-graphics`

Twelve PNGs under `docs/graphics-proof/` (git-ignored):
`<attic|combat>-<flat|lambert|smooth>-<classic|enhanced>.png`.

## Manual attestation

| Check | Status |
|---|---|
| `attic-smooth-classic.png` is identical to the pre-change `attic-smooth.png` | pending |
| Under `enhanced`, skin shows a soft highlight and the hero's clothes read matte | pending |
| Floor objects (wood, metal) carry a highlight that sits on the lit side | pending |
| A faint darkening at the feet and in rest-pose creases; no black blotches | pending |
| Grain is visible at scale 4 on cloth/wood, invisible at scale 1 | pending |
| Configuration screen: 15 rows, Realism between AA and Back, nothing clipped | pending |
| Toggling Realism in the menu changes the look live; Classic looks as before | pending |
```

Fill the two `<paste the real output>` blocks with the actual pytest output from this machine.

- [ ] **Step 6: Update README, CONTEXT and AGENTS**

`README.md`: the paragraph "The in-game Configuration screen's Graphics rows, and six CLI flags" becomes seven flags; after the `--msaa` clause add:

```
`--realism {classic,enhanced}` (`classic` is the flat-material look;
`enhanced` gives every surface a material — specular, rim, occlusion and
grain — from a palette-index table in `PyAitD/render/materials.json`, which
`make bootstrap-materials` regenerates and an override directory can remap
per body under `DIR/bodies/body<NNN>.json`),
```

and the override-directory sentence gains `and `DIR/bodies/body<NNN>.json` (a per-body material remap)`.

`CONTEXT.md` rows:

```
| `render/materials.py` | `Material`, `CLASS_PRESETS`, `MaterialTable`, `parse_table`/`load_table`/`default_table`, `RealismPreset`/`PRESETS`: palette-index material classes, the committed `materials.json`, the two realism presets; pygame/GL-free |
| `render/occlusion.py` | `bake_vertex_ao(body) -> (N,) float32`: rest-pose hemisphere-ray vertex occlusion, baked once per body; pygame/GL-free |
| `render/geometry.py` | `pose_geometry(..., ao=None) -> BodyGeometry`: float posed vertices, per-vertex normals, rest-pose vertices, baked AO, triangulated/line/point/sphere primitives, shared with `skel.pose_vertices` so pose can never disagree |
| `render/asset_resolver.py` | `AssetResolver(assets, override_dir=None)`: background/palette/light lookup, per-body material table (with `bodies/body<NNN>.json` override) and AO bake, checking an optional override directory first and falling back to the original asset |
| `render/render_options.py` | `RenderOptions(scale, shading, background_filter, override_dir, lighting, msaa, realism)`: validation, clamping, menu-cycle helpers; pygame/GL-free |
| `render/render_gl.py` | `GLBackend(ctx, options)`: ModernGL pipeline, per-actor depth, GPU mask-texture erasure, shading modes, estimated scene lighting, projected ground shadows, per-material surface response, multisampling, background filtering |
```

and the `tools/` row gains `bootstrap_materials` (survey/label/emit/check of the material table; its label stage reaches Gemini through `regenerate_backgrounds.agy_structured`).

`AGENTS.md`: the make-target list gains `make bootstrap-materials # palette ramps + body usage -> PyAitD/render/materials.json (vision=1 asks Gemini through agy about uncertain ramps)`; the rule at line 173 becomes "`tools/regenerate_backgrounds.py` owns the AI-service boundary: it is the only module that shells out to the `agy` CLI, and `tools/bootstrap_materials.py`'s label stage reaches Gemini only through its `agy_structured`."

- [ ] **Step 7: Commit**

```bash
git add PyAitD/render/render_options.py tools/prove_graphics.py Makefile docs/graphics-realism-proof.md README.md CONTEXT.md AGENTS.md tests/test_render_options.py tests/test_prove_graphics.py tests/test_config.py tests/test_ui_reducers.py
git commit -m "feat: enhanced realism on by default, with the proof and docs"
```

---

## Manual verification

No test can judge whether this looks right. After Task 8, with game data present:

```bash
make run
```

1. **Configuration screen.** 15 rows, Realism between AA and Back, nothing clipped, every row clickable at its label.
2. **Realism: Enhanced vs Classic.** Toggle and watch the hero. Enhanced: a soft highlight on skin, matte cloth, a faint darkening at the feet. Classic: exactly the previous look.
3. **Objects.** Walk to a wooden or metal object; its highlight should sit on the side the room's light comes from and move when the camera cuts.
4. **Grain.** At scale 4 cloth and wood carry a fine texture that stays fixed to the limb as the hero walks; at scale 1 it is invisible.
5. **Wrong materials.** Note any surface whose material reads wrong (a skin-coloured chair, a metallic coat). Those are ramps to hand-label in `data/aitd1/materials-survey/survey.json` (then `make bootstrap-materials` again) or bodies to override under `overrides/bodies/`.
