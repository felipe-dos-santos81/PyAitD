# Smooth Actor Geometry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Round the low-poly AITD1 bodies on the GPU — PN-triangle tessellation of every posed triangle through instanced vertex-shader evaluation, crease-aware per-corner normals computed from all faces, a tessellated ground shadow — behind a `smoothing` option whose `0` is byte-identical to today, with the option living on a new Graphics sub-page of the system menu.

**Architecture:** A pure numpy module `render/refine.py` plans each body once from its rest pose (consistent face orientation, crease edges above 80°, per-corner smoothing groups) and computes posed per-corner normals per frame; `BodyGeometry` carries `corner_normals` and `straight`; `AssetResolver` memoises the plan and reads a per-body `crease` override. `GLBackend` gains a tessellating vertex shader: one instance per source triangle (45 packed floats: three corners of position/ao/normal/straight/colour/index/rest), a fixed barycentric sub-patch per level, PN evaluation on the GPU, and a `project` mode that flattens the same patch onto the ground plane for the shadow pass. `smoothing == 0` runs the existing code path verbatim.

**Tech Stack:** Python 3.12, NumPy 2, ModernGL 5.12 (GL 3.3 core; instanced attributes, transform feedback in tests), pygame-ce 2.5, pytest 8.

**Spec:** `docs/superpowers/specs/2026-08-28-smooth-actor-geometry-design.md`

## Global Constraints

- `# SPDX-License-Identifier: GPL-2.0-only` is the first line of every Python file.
- Dependencies are fixed: pygame-ce, ModernGL, NumPy, pytest. Add nothing.
- `PyAitD/render/refine.py` is numpy-only — no pygame, no moderngl, no engine import except through `PyAitD.render.geometry`; `tests/test_layering.py` scans for this. `render_gl.py` alone may touch moderngl.
- `RenderOptions` never reaches `scene.py`: `FrameDescription`/`ActorDraw` stay option-agnostic.
- `skel.skin()`, `draw_list`, picking, masks and the mouse contract are untouched. `SoftwareBackend` is untouched.
- `smoothing=0` must reproduce `tests/golden/scene_lit_classic.npy` byte for byte (`tests/test_render_gl.py::test_classic_realism_matches_the_pre_materials_golden`).
- Crease threshold default `CREASE_DEG = 80.0`; per-body override key `"crease"` in `bodies/body<NNN>.json`, a number in `0..180`.
- `SMOOTHING_LEVELS = (0, 1, 2, 3)`; level `L` means `2**L` segments per edge, `4**L` sub-triangles. Default `0` until Task 7 flips it to `2`.
- Menu labels: `Smoothing: Off / Low / Medium / High` for levels 0–3. Graphics page: `GRAPHICS_ROWS` rows then `Back`, layout `pygame.Rect(16, 12 + i * 22, 288, 20)`; every menu row stays ≥ 13 px tall.
- Every test file carries exactly one subject marker (`pytestmark = pytest.mark.render` / `shell` / `tools`), plus `journey` when it drives `run()`.
- Run tests headless: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest <files> -q`. `make test` is the gate after every task. No linter, no formatter; never mass-reformat.
- Commit messages end with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01CiEbmR6XfbostZiohp1cq4`.

## File Structure

| File | Responsibility |
|---|---|
| `PyAitD/app/ui.py` (modify) | `SystemMenuPage.GRAPHICS`, `GRAPHICS_ROWS`, `GRAPHICS_CYCLES`, `graphics_labels`, `graphics_row_count`, the reducer's page transitions, `SystemMenuLayout.GRAPHICS_PAGE_ROWS`, the menu renderer's per-page labels |
| `PyAitD/app/shell.py` (modify) | `--smoothing` flag, `apply_render_overrides`, `_MENU_RENDER_FIELDS` |
| `PyAitD/render/render_options.py` (modify) | `SMOOTHING_LEVELS`, `RenderOptions.smoothing`, validation, payload, `cycle_smoothing` |
| `PyAitD/render/refine.py` (create) | `Refinement`, `plan_refinement`, `corner_normals`, `subpatch`, `evaluate`, `parse_crease` — pure numpy |
| `PyAitD/render/geometry.py` (modify) | `BodyGeometry.corner_normals` / `.straight`; `pose_geometry(..., refinement=None)` |
| `PyAitD/render/asset_resolver.py` (modify) | `_validate_body_override`, `AssetResolver.refinement`, `material_table` through the shared validator |
| `PyAitD/render/override_check.py` (modify) | `check_body_materials` → `check_bodies`, validating `crease` too |
| `tools/check_overrides.py` (modify) | the rename's call site |
| `PyAitD/render/scene.py` (modify) | `build_frame` passes `refinement=` |
| `PyAitD/render/render_gl.py` (modify) | `_TESS_VSH`, instance layout, `_tess_prog`, `_tess_shadow_prog`, sub-patch buffers, `_set_frame_uniforms`, tessellated actor and shadow draws |
| `tools/prove_graphics.py` (modify) | `--smoothing`, the `-flatmesh` pair |
| `tests/test_refine.py` (create), `tests/test_render_gl.py`, `tests/test_geometry.py`, `tests/test_asset_resolver.py`, `tests/test_override_check.py`, `tests/test_scene.py`, `tests/test_render_options.py`, `tests/test_config.py`, `tests/test_main.py`, `tests/test_ui_reducers.py`, `tests/test_ui_render.py`, `tests/test_ui_mouse.py`, `tests/test_shell_journeys.py`, `tests/test_prove_graphics.py` (modify) | tests per task |
| `docs/smooth-geometry-proof.md` (create), `README.md`, `AGENTS.md`, `CONTEXT.md`, `Makefile` (modify) | Task 7 docs |

---

### Task 1: The Graphics sub-page

**Files:**
- Modify: `PyAitD/app/ui.py` (`GRAPHICS_ROWS`/`config_row_count` near line 25, `SystemMenuPage` line 332, `reduce_system_menu` line 389, `SystemMenuLayout` line 565, `render_system_menu` line 1137)
- Modify: `PyAitD/app/shell.py` (the `_MENU_RENDER_FIELDS` comment, line 594)
- Test: `tests/test_ui_reducers.py`, `tests/test_ui_render.py`, `tests/test_ui_mouse.py`, `tests/test_shell_journeys.py`

**Interfaces:**
- Consumes: `cycle_scale … cycle_realism` from `render_options`, `REMAPPABLE_CONTROLS`, `effective_rects`, `SystemMenuResult`.
- Produces: `SystemMenuPage.GRAPHICS`; `GRAPHICS_ROWS: int` (6 now, 7 after Task 2); `GRAPHICS_CYCLES: tuple[callable, ...]` (one per Graphics row above Back, index = row); `graphics_row_count() -> int` (`GRAPHICS_ROWS + 1`); `config_row_count() -> int` (`3 + len(REMAPPABLE_CONTROLS)`); `graphics_labels(render: RenderOptions) -> list[str]` (`GRAPHICS_ROWS` labels); `SystemMenuLayout.GRAPHICS_PAGE_ROWS`; the CONFIG page's `Graphics...` row at index `config_row_count() - 2`.

- [ ] **Step 1: Write the failing reducer tests**

In `tests/test_ui_reducers.py`, replace `test_graphics_rows_cycle_render_options` with the four tests below (keep every other test):

```python
def test_configuration_graphics_row_opens_the_graphics_page():
    from PyAitD.app.ui import config_row_count
    assert config_row_count() == 3 + len(REMAPPABLE_CONTROLS)
    state = SystemMenuPresenter(page=SystemMenuPage.CONFIG, cursor=config_row_count() - 2, hover=3)
    assert reduce_system_menu(state, Command.ACCEPT, default_settings()) is None
    assert (state.page, state.cursor, state.hover) == (SystemMenuPage.GRAPHICS, 0, None)


def test_graphics_rows_cycle_render_options():
    from PyAitD.app.ui import GRAPHICS_CYCLES, GRAPHICS_ROWS, graphics_row_count
    from PyAitD.render.render_options import RenderOptions
    assert GRAPHICS_ROWS == 6 and len(GRAPHICS_CYCLES) == GRAPHICS_ROWS
    assert graphics_row_count() == GRAPHICS_ROWS + 1
    settings = default_settings()
    state = SystemMenuPresenter(page=SystemMenuPage.GRAPHICS, cursor=0)
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(scale=6)
    state.cursor = 1
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(shading="flat")
    state.cursor = 2
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(background_filter="xbr")
    state.cursor = 3
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(lighting="fixed")
    state.cursor = 4
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(msaa=8)
    state.cursor = 5
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(realism="classic")
    assert state.page is SystemMenuPage.GRAPHICS  # a cycle never leaves the page


def test_graphics_back_and_cancel_return_to_the_graphics_row_saving():
    from PyAitD.app.ui import config_row_count, graphics_row_count
    state = SystemMenuPresenter(page=SystemMenuPage.GRAPHICS, cursor=graphics_row_count() - 1, hover=2)
    assert reduce_system_menu(state, Command.ACCEPT, default_settings()) == SystemMenuResult(save=True)
    assert (state.page, state.cursor, state.hover) == (SystemMenuPage.CONFIG, config_row_count() - 2, None)
    state = SystemMenuPresenter(page=SystemMenuPage.GRAPHICS, cursor=3)
    assert reduce_system_menu(state, Command.CANCEL, default_settings()) == SystemMenuResult(save=True)
    assert (state.page, state.cursor) == (SystemMenuPage.CONFIG, config_row_count() - 2)


def test_graphics_cursor_wraps_across_all_rows():
    from PyAitD.app.ui import graphics_row_count
    state = SystemMenuPresenter(page=SystemMenuPage.GRAPHICS)
    reduce_system_menu(state, Command.UP, default_settings())
    assert state.cursor == graphics_row_count() - 1
    reduce_system_menu(state, Command.DOWN, default_settings())
    assert state.cursor == 0
```

- [ ] **Step 2: Write the failing render and layout tests**

Append to `tests/test_ui_render.py`:

```python
def test_graphics_page_rows_fit_the_screen_and_do_not_overlap():
    from PyAitD.app.ui import SystemMenuLayout, graphics_row_count
    rows = SystemMenuLayout.rows(SystemMenuPage.GRAPHICS)
    assert len(rows) == graphics_row_count()
    assert all(r.bottom <= 200 and r.height >= 13 for r in rows)
    hit = SystemMenuLayout.hit_rows(SystemMenuPage.GRAPHICS)
    for a in range(len(hit)):
        for b in range(a + 1, len(hit)):
            assert not hit[a].colliderect(hit[b])


def test_graphics_labels_match_the_cycles_one_per_row():
    from PyAitD.app.ui import GRAPHICS_CYCLES, GRAPHICS_ROWS, graphics_labels
    labels = graphics_labels(default_settings().render)
    assert len(labels) == GRAPHICS_ROWS == len(GRAPHICS_CYCLES)
    assert labels[0] == "Scale: 4x" and labels[5] == "Realism: Enhanced"


def test_configuration_page_ends_with_graphics_then_back(monkeypatch):
    # The CONFIG label list is hand-built; pin its tail so the reducer's
    # "row_count - 2 is Graphics..." rule and the drawn labels cannot drift.
    from PyAitD.app.ui import _button
    drawn = []
    monkeypatch.setattr("PyAitD.app.ui._button", lambda painter, rect, label, **kw: drawn.append(label))
    fake_sprite = np.zeros((20, 20, 3), dtype=np.uint8)
    fake_assets = SimpleNamespace(cadre_bank=lambda: (fake_sprite,) * 9)
    render_system_menu(UIPainter(), SystemMenuPresenter(page=SystemMenuPage.CONFIG), default_settings(), fake_assets)
    assert drawn[-2:] == ["Graphics...", "Back to Menu"]
    assert not any(label.startswith("Scale") for label in drawn)
    drawn.clear()
    render_system_menu(UIPainter(), SystemMenuPresenter(page=SystemMenuPage.GRAPHICS), default_settings(), fake_assets)
    assert drawn[0] == "Scale: 4x" and drawn[-1] == "Back"
```

- [ ] **Step 3: Write the failing journey test**

In `tests/test_shell_journeys.py`, add `set_options` to `_HeadlessRenderer` (the real Renderer has it; `_apply_system_result` calls it whenever a render field changes):

```python
    def set_options(self, options):
        self.options = options
```

Then append, after `test_menu_remap_sticky_save_and_reload_journey`:

```python
def test_menu_graphics_page_cycle_and_save_journey(data_dir, profile, monkeypatch, tmp_path):
    # ESC -> Configuration -> Graphics... -> Realism (cycles to classic) ->
    # Back -> Back to Menu -> Return to Game -> quit: the cycled field is
    # what the save wrote, and the page transitions happened by mouse.
    game = init_game(data_dir, profile)
    path = tmp_path / "settings.json"
    session = load_runtime_session(path)
    state = {"frames": 0}
    config_rows = SystemMenuLayout.rows(SystemMenuPage.CONFIG)
    graphics_rows = SystemMenuLayout.rows(SystemMenuPage.GRAPHICS)

    def next_events():
        state["frames"] += 1
        frames = state["frames"]
        assert frames < 200, "graphics journey exceeded its budget"
        if frames == 1:
            return [_key(pygame.K_ESCAPE)]
        if frames == 2:
            return [_left_click(SystemMenuLayout.MAIN_ROWS[1].center)]
        if frames == 3:
            return [_left_click(config_rows[-2].center)]          # Graphics...
        if frames == 4:
            assert session.system_menu.page is SystemMenuPage.GRAPHICS, "fixture"
            return [_left_click(graphics_rows[5].center)]         # Realism
        if frames == 5:
            return [_left_click(graphics_rows[-1].center)]        # Back
        if frames == 6:
            assert session.system_menu.page is SystemMenuPage.CONFIG, "fixture"
            return [_left_click(config_rows[-1].center)]          # Back to Menu
        if frames == 7:
            return [_left_click(SystemMenuLayout.MAIN_ROWS[0].center)]
        if frames >= 9:
            return [_quit()]
        return []

    _run_shell(monkeypatch, game, session, next_events)
    assert session.settings.render.realism == "classic"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["render"]["realism"] == "classic"
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_ui_reducers.py tests/test_ui_render.py tests/test_shell_journeys.py -q -k "graphics"`
Expected: FAIL — `AttributeError: GRAPHICS` on `SystemMenuPage`, `ImportError` for `GRAPHICS_CYCLES`/`graphics_row_count`.

- [ ] **Step 5: Implement the page in `PyAitD/app/ui.py`**

Replace the `GRAPHICS_ROWS`/`config_row_count` block near line 25 with:

```python
GRAPHICS_ROWS = 6          # rows on the Graphics page above Back, in GRAPHICS_CYCLES order


def config_row_count():
    # Sticky Action, one row per remappable control, "Graphics...", "Back to Menu"
    return 3 + len(REMAPPABLE_CONTROLS)


def graphics_row_count():
    return GRAPHICS_ROWS + 1   # plus Back
```

Add `GRAPHICS = auto()` to `SystemMenuPage` between `CONFIG` and `KEY_PICK`.

Directly above `reduce_system_menu`, add:

```python
# One cycle per Graphics-page row above Back; graphics_labels draws them in
# the same order, and tests pin that the two never drift apart.
GRAPHICS_CYCLES = (cycle_scale, cycle_shading, cycle_filter, cycle_lighting, cycle_msaa, cycle_realism)


def _leave_graphics(state):
    state.page = SystemMenuPage.CONFIG
    state.cursor = config_row_count() - 2   # back on the Graphics... row
    state.hover = None
```

Replace the body of `reduce_system_menu` with:

```python
def reduce_system_menu(state, command, settings):
    if state.capture is not None:
        return None
    command = Command.ACCEPT if command is Command.OPEN_INVENTORY else command
    if state.page is SystemMenuPage.MAIN:
        row_count = 3
    elif state.page is SystemMenuPage.GRAPHICS:
        row_count = graphics_row_count()
    else:
        row_count = config_row_count()
    if command is Command.UP:
        state.cursor = (state.cursor - 1) % row_count
    elif command is Command.DOWN:
        state.cursor = (state.cursor + 1) % row_count
    elif command is Command.CANCEL:
        if state.page is SystemMenuPage.GRAPHICS:
            _leave_graphics(state)
            return SystemMenuResult(save=True)
        if state.page is SystemMenuPage.CONFIG:
            state.page = SystemMenuPage.MAIN
            state.cursor = 0
            return SystemMenuResult(save=True)
        return SystemMenuResult(close=True, save=True)
    elif command is Command.ACCEPT and state.page is SystemMenuPage.MAIN:
        if state.cursor == 0:
            return SystemMenuResult(close=True, save=True)
        if state.cursor == 1:
            state.page = SystemMenuPage.CONFIG
            state.cursor = 0
        else:
            return SystemMenuResult(quit=True, save=True)
    elif command is Command.ACCEPT and state.page is SystemMenuPage.GRAPHICS:
        if state.cursor == row_count - 1:
            _leave_graphics(state)
            return SystemMenuResult(save=True)
        cycle = GRAPHICS_CYCLES[state.cursor]
        return SystemMenuResult(settings=replace(settings, render=cycle(settings.render)))
    elif (command is Command.ACCEPT and state.page is SystemMenuPage.CONFIG
          and state.cursor == row_count - 1):
        state.page = SystemMenuPage.MAIN
        state.cursor = 0
        return SystemMenuResult(save=True)
    elif command is Command.ACCEPT and state.cursor == row_count - 2:
        # the Graphics... row, just above Back
        state.page = SystemMenuPage.GRAPHICS
        state.cursor = 0
        state.hover = None
    elif command is Command.ACCEPT and state.cursor == 0:
        return SystemMenuResult(
            settings=replace(settings, sticky_action=not settings.sticky_action),
        )
    elif command is Command.ACCEPT:
        state.capture = REMAPPABLE_CONTROLS[state.cursor - 1].name
        state.page = SystemMenuPage.KEY_PICK
        state.hover = None
    return None
```

In `SystemMenuLayout`, after `CONFIG_ROWS`, add the page's rows and teach `rows()` about them:

```python
    # graphics_row_count() rows at a 22 px pitch, 20 px tall: the page is
    # not squeezed the way CONFIG's 13 px rows are, and ends at y=186.
    GRAPHICS_PAGE_ROWS = tuple(
        pygame.Rect(16, 12 + i * 22, 288, 20)
        for i in range(graphics_row_count())
    )
```

and in `rows(cls, page)` insert before the `return cls.KEY_PICK_ROWS` fallthrough:

```python
        if page is SystemMenuPage.GRAPHICS:
            return cls.GRAPHICS_PAGE_ROWS
```

Above `render_system_menu`, add:

```python
def graphics_labels(render):
    """One label per Graphics-page row above Back, in GRAPHICS_CYCLES order."""
    return [
        f"Scale: {render.scale}x",
        f"Shading: {render.shading.title()}",
        f"Filter: {render.background_filter.title()}",
        f"Lighting: {render.lighting.title()}",
        # "up to", because this row shows the *option*, and GLBackend clamps
        # it to ctx.max_samples at construction (many drivers cap at 4). The
        # menu has no handle on the live backend to read the real count off,
        # so the label states the request honestly rather than claiming a
        # sample count the GPU may not be giving.
        f"AA: up to {render.msaa}x" if render.msaa else "AA: Off",
        f"Realism: {render.realism.title()}",
    ]
```

In `render_system_menu`, replace the label construction (`if presenter.page is SystemMenuPage.MAIN: … labels.append("Back to Menu")`) with:

```python
    if presenter.page is SystemMenuPage.MAIN:
        labels = ["Return to Game", "Configuration", "Quit"]
    elif presenter.page is SystemMenuPage.GRAPHICS:
        labels = graphics_labels(settings.render) + ["Back"]
    else:
        labels = [f"Sticky Action: {'On' if settings.sticky_action else 'Off'}"]
        for control in REMAPPABLE_CONTROLS:
            labels.append(f"{control.name}: {', '.join(settings.bindings[control.name])}")
        labels.append("Graphics...")
        labels.append("Back to Menu")
    selection = presenter.hover if presenter.hover is not None else presenter.cursor
    button_size = 12 if presenter.page in (SystemMenuPage.CONFIG, SystemMenuPage.GRAPHICS) else 18
```

(the `rows = zip(...)` / `_button` loop below it stays as it is). Remove the six `labels.append(f"Scale: …")` … `labels.append(f"Realism: …")` lines that used to sit in the CONFIG branch — `graphics_labels` now owns them.

In `PyAitD/app/shell.py`, update the comment above `_MENU_RENDER_FIELDS` to name the new page: `(SystemMenuPage.GRAPHICS's Scale/Shading/Filter/Lighting/AA/Realism rows, via GRAPHICS_CYCLES in ui.reduce_system_menu)`.

In `tests/test_ui_mouse.py`, the CONFIG comment in `test_story_whole_frame_confirms_and_menu_rows_are_large` ("the 15-row CONFIG page packs at a 13 px pitch to fit Scale, … above Back") becomes: `# CONFIG keeps its 13 px pitch from when it held the graphics rows; effective_rects still pads every row past the 12x12 minimum target size`. No assertion changes: the GRAPHICS page's 288x20 rows satisfy the `else` branch.

- [ ] **Step 6: Run the UI groups**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_ui_reducers.py tests/test_ui_render.py tests/test_ui_mouse.py tests/test_ui_input.py tests/test_shell_journeys.py tests/test_main.py -q`
Expected: all pass (the journey test skips without game data).

- [ ] **Step 7: Run the whole suite and commit**

Run: `make test`
Expected: green.

```bash
git add PyAitD/app/ui.py PyAitD/app/shell.py tests/test_ui_reducers.py tests/test_ui_render.py tests/test_ui_mouse.py tests/test_shell_journeys.py
git commit -m "feat: move the graphics rows to a Graphics sub-page of the system menu" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CiEbmR6XfbostZiohp1cq4"
```

---

### Task 2: The `smoothing` option

**Files:**
- Modify: `PyAitD/render/render_options.py`, `PyAitD/app/ui.py`, `PyAitD/app/shell.py` (`parse_args` line ~85, `apply_render_overrides`, `_MENU_RENDER_FIELDS`)
- Test: `tests/test_render_options.py`, `tests/test_config.py`, `tests/test_main.py`, `tests/test_ui_reducers.py`, `tests/test_ui_render.py`

**Interfaces:**
- Produces: `render_options.SMOOTHING_LEVELS = (0, 1, 2, 3)`; `RenderOptions.smoothing: int = 0` (eighth positional field, after `realism`); `cycle_smoothing(options) -> RenderOptions`; payload key `"smoothing"`; `ui.SMOOTHING_LABELS = ("Off", "Low", "Medium", "High")`; `GRAPHICS_ROWS == 7` with the Smoothing row at index 6; CLI `--smoothing {0,1,2,3}`.

- [ ] **Step 1: Write the failing option tests**

In `tests/test_render_options.py`: change `test_defaults`' first line to
`assert RenderOptions() == RenderOptions(4, "smooth", "bilinear", None, "scene", 4, "enhanced", 0)`;
in `test_each_invalid_field_falls_back_alone` add `"smoothing": 0` to both payload dicts and a trailing `, 0` to both expected `RenderOptions(8, …)` / `RenderOptions(4, …)` tuples. Append:

```python
def test_smoothing_defaults_to_off_and_cycles():
    from PyAitD.render.render_options import SMOOTHING_LEVELS, cycle_smoothing
    assert SMOOTHING_LEVELS == (0, 1, 2, 3)
    options = RenderOptions()
    assert options.smoothing == 0
    assert cycle_smoothing(options).smoothing == 1
    assert cycle_smoothing(RenderOptions(smoothing=3)).smoothing == 0
    assert RenderOptions(smoothing=2).to_payload()["smoothing"] == 2


def test_invalid_smoothing_falls_back_alone():
    for bad in (5, -1, "two", True):
        payload = RenderOptions().to_payload()
        payload["smoothing"] = bad
        options, error = validate_render_options(payload)
        assert options == RenderOptions() and "smoothing" in error, bad
```

In `tests/test_config.py::test_save_writes_schema_2_with_render`, add `"smoothing": 0` to the expected `payload["render"]` dict.

In `tests/test_main.py`, after `test_each_render_flag_overrides_only_its_own_field`, add:

```python
def test_smoothing_flag_overrides_only_its_own_field():
    from dataclasses import replace

    from PyAitD.app.shell import apply_render_overrides, parse_args
    from PyAitD.app.config import default_settings

    base = default_settings()
    only = apply_render_overrides(base, parse_args(["--smoothing", "3"]))
    assert only == replace(base, render=replace(base.render, smoothing=3))
    with pytest.raises(SystemExit):
        parse_args(["--smoothing", "5"])   # argparse choices reject it
```

(`pytest` is already imported at the top of `tests/test_main.py`; add `import pytest` if it is not.)

In `tests/test_ui_reducers.py::test_graphics_rows_cycle_render_options` change the pin to `GRAPHICS_ROWS == 7` and append after the `realism` cycle:

```python
    state.cursor = 6
    assert reduce_system_menu(state, Command.ACCEPT, settings).settings.render == RenderOptions(smoothing=1)
```

In `tests/test_ui_render.py::test_graphics_labels_match_the_cycles_one_per_row` add `assert labels[6] == "Smoothing: Off"`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_options.py tests/test_config.py tests/test_main.py tests/test_ui_reducers.py tests/test_ui_render.py -q`
Expected: FAIL — `TypeError: RenderOptions() takes … positional arguments`, `ImportError: cycle_smoothing`, `GRAPHICS_ROWS == 7` assertion.

- [ ] **Step 3: Implement the option**

`PyAitD/render/render_options.py`:

```python
SMOOTHING_LEVELS = (0, 1, 2, 3)   # 2**level segments per edge; 0 draws the flat mesh exactly as before
```

Add `smoothing: int = 0` after `realism` in `RenderOptions`, `"smoothing": self.smoothing` to `to_payload`, and in `validate_render_options`, after the `realism` block:

```python
    smoothing = payload.get("smoothing")
    # bool-rejecting like msaa: True in (0, 1, 2, 3) is True, and is not a level
    if not (type(smoothing) is int and smoothing in SMOOTHING_LEVELS):
        errors.append(f"smoothing must be one of {', '.join(str(v) for v in SMOOTHING_LEVELS)}")
        smoothing = defaults.smoothing
    options = RenderOptions(scale, shading, background_filter, override_dir, lighting, msaa, realism, smoothing)
```

and at the end:

```python
def cycle_smoothing(options):
    current = options.smoothing if options.smoothing in SMOOTHING_LEVELS else SMOOTHING_LEVELS[0]
    return replace(options, smoothing=_cycle(SMOOTHING_LEVELS, current))
```

`PyAitD/app/ui.py`: import `cycle_smoothing` alongside the other cycles; `GRAPHICS_ROWS = 7`; `GRAPHICS_CYCLES = (…, cycle_realism, cycle_smoothing)`; add

```python
SMOOTHING_LABELS = ("Off", "Low", "Medium", "High")   # index = smoothing level
```

and append `f"Smoothing: {SMOOTHING_LABELS[render.smoothing]}"` to the list in `graphics_labels`.

`PyAitD/app/shell.py`: import `SMOOTHING_LEVELS` from `render_options`; in `parse_args` after `--realism`:

```python
    p.add_argument(
        "--smoothing", type=int, choices=SMOOTHING_LEVELS, default=None,
        help="GPU mesh smoothing level: 0 draws the flat 1992 mesh, 1-3 round it with 4/16/64 sub-triangles",
    )
```

in `apply_render_overrides` after the `realism` line: `if args.smoothing is not None: payload["smoothing"] = args.smoothing`; and `_MENU_RENDER_FIELDS = ("scale", "shading", "background_filter", "lighting", "msaa", "realism", "smoothing")`.

- [ ] **Step 4: Run the tests to verify they pass, then the whole suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_options.py tests/test_config.py tests/test_main.py tests/test_ui_reducers.py tests/test_ui_render.py -q` then `make test`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/render/render_options.py PyAitD/app/ui.py PyAitD/app/shell.py tests/test_render_options.py tests/test_config.py tests/test_main.py tests/test_ui_reducers.py tests/test_ui_render.py
git commit -m "feat: a smoothing render option, default off, on the Graphics page and the CLI" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CiEbmR6XfbostZiohp1cq4"
```

---

### Task 3: `refine.py` and the geometry fields

**Files:**
- Create: `PyAitD/render/refine.py`
- Modify: `PyAitD/render/geometry.py` (`BodyGeometry`, `pose_geometry`)
- Test: `tests/test_refine.py` (create), `tests/test_geometry.py`

**Interfaces:**
- Consumes: `geometry.pose_geometry`, `geometry._CAMERA_FACING`, `formats.Body`.
- Produces:
  - `refine.CREASE_DEG = 80.0`, `refine.MAX_CREASE_DEG = 180.0`
  - `refine.Refinement(orientation: (M,) float32, pairs: (K,2) int32, straight: (M,3) float32, crease_deg: float)` with method `corner_normals(vertices, tris) -> (M,3,3) float32`
  - `refine.plan_refinement(body, crease_deg=CREASE_DEG) -> Refinement`
  - `refine.corner_normals(vertices, tris, refinement) -> (M,3,3) float32`
  - `refine.subpatch(level) -> (3 * 4**level, 3) float32`, read-only, cached
  - `refine.evaluate(corners (M,3,3), normals (M,3,3), straight (M,3), bary (S,3)) -> (positions (M,S,3) float32, normals (M,S,3) float32)`
  - `refine.parse_crease(data: dict) -> float | None`
  - `BodyGeometry.corner_normals: (M,3,3) float32` (defaults to `normals[tris]`), `BodyGeometry.straight: (M,3) float32` (defaults to zeros)
  - `pose_geometry(body, group_states, actor_angles=None, ao=None, refinement=None)`

- [ ] **Step 1: Write the failing refine tests**

Create `tests/test_refine.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
import math

import numpy as np
import pytest

from PyAitD.engine.formats import Body, Primitive
from PyAitD.render.geometry import _CAMERA_FACING, pose_geometry
from PyAitD.render.refine import (
    CREASE_DEG, Refinement, corner_normals, evaluate, parse_crease, plan_refinement, subpatch,
)

pytestmark = pytest.mark.render


def _body(vertices, polys):
    return Body(0, (0,) * 6, (), [tuple(int(c) for c in v) for v in vertices], [], [],
                [Primitive(1, 0, 1, list(p)) for p in polys])


def _cube_body():
    v = [(-100, -100, -100), (100, -100, -100), (100, 100, -100), (-100, 100, -100),
         (-100, -100, 100), (100, -100, 100), (100, 100, 100), (-100, 100, 100)]
    faces = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (0, 3, 7, 4), (1, 2, 6, 5)]
    return _body(v, faces)


def _hex_prism_body(radius=200.0, half_height=150.0, caps=True):
    """A hexagonal prism around the y axis, faces square-on to +-x. Side
    edges meet at 60 degrees, the cap rims at 90."""
    ring = [(round(radius * math.cos(math.radians(30 + 60 * k))), round(radius * math.sin(math.radians(30 + 60 * k))))
            for k in range(6)]
    v = [(x, -half_height, z) for x, z in ring] + [(x, half_height, z) for x, z in ring]
    polys = [(k, (k + 1) % 6, 6 + (k + 1) % 6, 6 + k) for k in range(6)]
    if caps:
        polys += [(0, 1, 2, 3, 4, 5), (6, 7, 8, 9, 10, 11)]
    return _body(v, polys)


def _rest(body):
    return pose_geometry(body, [], None)


def test_a_flipped_face_is_oriented_against_its_neighbour():
    # two triangles sharing edge 1-2; the second walks it in the same
    # direction, i.e. it is wound the other way
    body = _body([(0, 0, 0), (100, 0, 0), (0, 100, 0), (100, 100, 0)], [(0, 1, 2), (1, 2, 3)])
    plan = plan_refinement(body)
    assert plan.orientation.tolist() == [1.0, -1.0] or plan.orientation.tolist() == [-1.0, 1.0]
    geo = _rest(body)
    normals = corner_normals(geo.vertices, geo.tris, plan)
    assert np.allclose(normals[0], normals[1])            # one flat sheet, one normal everywhere
    assert np.allclose(np.abs(normals[0, 0]), [0, 0, 1])


def test_a_three_face_edge_is_a_crease_and_stops_orientation():
    # a flat sheet of two faces plus a fin standing on their shared edge
    # 1-2: three faces on one edge. The edge is straight from all three,
    # and the fin's sign is decided by its own centroid rule, not inherited
    # across the fold.
    body = _body([(0, 0, 0), (100, 0, 0), (0, 100, 0), (100, 100, 0), (50, 50, 100)],
                 [(0, 1, 2), (2, 1, 3), (1, 2, 4)])
    plan = plan_refinement(body)
    assert plan.straight.sum() == 3.0
    assert plan.straight[0, 1] == 1.0 and plan.straight[1, 0] == 1.0 and plan.straight[2, 0] == 1.0


def test_a_cube_is_all_straight_at_80_and_all_smooth_at_100():
    body = _cube_body()
    straight = plan_refinement(body, 80.0).straight
    smooth = plan_refinement(body, 100.0).straight
    # each quad fans into two triangles: its diagonal is a 0-degree edge and stays smooth
    assert straight.sum() == 24.0      # 12 cube edges x 2 triangles touching each
    assert smooth.sum() == 0.0


def test_a_hex_prism_rounds_its_sides_and_keeps_its_rims():
    plan = plan_refinement(_hex_prism_body())
    geo = _rest(_hex_prism_body())
    normals = corner_normals(geo.vertices, geo.tris, plan)
    # side faces are the first 12 triangles (6 quads); a side corner's normal
    # is the mean of its two side faces -- radial, never tilted toward a cap
    for f in range(12):
        for k in range(3):
            assert abs(normals[f, k, 1]) < 1e-6, (f, k)
    # a cap corner's normal is the cap's own: the rim is a crease
    cap = normals[12:]
    assert np.allclose(np.abs(cap[..., 1]), 1.0)
    # the radial side normals point outward from the axis
    v = geo.vertices[geo.tris[:12]]
    outward = (normals[:12] * np.stack([v[..., 0], np.zeros_like(v[..., 0]), v[..., 2]], axis=-1)).sum(axis=-1)
    assert (outward > 0).all()


def test_boundary_edges_are_not_creases():
    plan = plan_refinement(_hex_prism_body(caps=False))
    assert plan.straight.sum() == 0.0        # 60-degree side edges smooth, open rims curve


def test_a_degenerate_face_is_straight_and_its_corners_never_nan():
    body = _cube_body()
    body.primitives.append(Primitive(1, 0, 9, [0, 0, 0]))
    plan = plan_refinement(body)
    geo = _rest(body)
    normals = corner_normals(geo.vertices, geo.tris, plan)
    assert not np.isnan(normals).any()
    assert np.allclose(np.linalg.norm(normals, axis=2), 1.0, atol=1e-5)
    assert plan.straight[-1].tolist() == [1.0, 1.0, 1.0]


def test_a_lone_degenerate_triangle_falls_back_to_camera_facing():
    body = _body([(0, 0, 0), (0, 0, 0), (0, 0, 0)], [(0, 1, 2)])
    geo = _rest(body)
    normals = corner_normals(geo.vertices, geo.tris, plan_refinement(body))
    assert np.array_equal(normals[0], np.tile(_CAMERA_FACING, (3, 1)))


def test_subpatch_levels():
    for level in (0, 1, 2, 3):
        bary = subpatch(level)
        assert bary.shape == (3 * 4 ** level, 3) and bary.dtype == np.float32
        assert (bary >= 0).all() and np.allclose(bary.sum(axis=1), 1.0)
        for corner in np.eye(3):
            assert (np.abs(bary - corner).sum(axis=1) < 1e-6).any()
    assert subpatch(2) is subpatch(2)
    with pytest.raises(ValueError):
        subpatch(2)[0, 0] = 5.0


def _patch(normals, straight=(0, 0, 0)):
    corners = np.array([[[0, 0, 0], [300, 0, 0], [0, 300, 0]]], np.float64)
    n = np.array([normals], np.float64)
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    return corners, n, np.array([straight], np.float64)


def test_evaluate_leaves_a_flat_patch_flat_and_its_corners_exact():
    corners, n, s = _patch([[0, 0, 1]] * 3)
    pos, nrm = evaluate(corners, n, s, subpatch(2))
    assert np.allclose(pos[0, :, 2], 0.0, atol=1e-4)
    assert np.allclose(nrm[0], [0, 0, 1])
    bary = subpatch(2)
    for k in range(3):
        at_corner = np.abs(bary - np.eye(3)[k]).sum(axis=1) < 1e-6
        assert np.allclose(pos[0][at_corner], corners[0, k], atol=1e-4)


def test_evaluate_bulges_along_tilted_normals():
    tilted = [[-0.5, -0.5, 1], [0.5, -0.5, 1], [-0.5, 0.5, 1]]
    corners, n, s = _patch(tilted)
    pos, _ = evaluate(corners, n, s, subpatch(2))
    centre = np.abs(subpatch(2) - 1 / 3).sum(axis=1).argmin()
    assert pos[0, centre, 2] > 5.0         # lifted toward +z, the mean normal


def test_evaluate_keeps_a_straight_edge_straight():
    tilted = [[-0.5, -0.5, 1], [0.5, -0.5, 1], [-0.5, 0.5, 1]]
    corners, n, s = _patch(tilted, straight=(1, 0, 0))
    pos, _ = evaluate(corners, n, s, subpatch(3))
    on_edge = subpatch(3)[:, 2] < 1e-6         # w == 0: the 0-1 edge
    assert np.allclose(pos[0][on_edge, 1:], 0.0, atol=1e-4)   # y == z == 0 along it
    corners, n, s = _patch(tilted)
    pos, _ = evaluate(corners, n, s, subpatch(3))
    assert not np.allclose(pos[0][on_edge, 2], 0.0, atol=1e-2)  # and it curves when smooth


def test_adjacent_patches_agree_on_their_shared_edge():
    # patch A (0,1,2) and patch B (1,0,3) share corners 0 and 1 with the
    # same corner normals, so their shared edge must evaluate identically
    p0, p1, p2, p3 = [0, 0, 0], [300, 0, 0], [0, 300, 0], [300, -300, 0]
    n0, n1 = [-0.3, 0.2, 1], [0.4, -0.1, 1]
    a_c, a_n, a_s = _patch([n0, n1, [0, 0, 1]])
    b = np.array([[p1, p0, p3]], np.float64)
    b_n = np.array([[n1, n0, [0, 0, 1]]], np.float64)
    b_n /= np.linalg.norm(b_n, axis=2, keepdims=True)
    b_s = np.zeros((1, 3))
    samples = np.array([[t, 1 - t, 0.0] for t in np.linspace(0, 1, 9)])
    a_pos, a_nrm = evaluate(a_c, a_n, a_s, samples)
    b_pos, b_nrm = evaluate(b, b_n, b_s, samples[:, [1, 0, 2]])   # B walks the edge the other way
    assert np.allclose(a_pos[0], b_pos[0], atol=1e-4)
    assert np.allclose(a_nrm[0], b_nrm[0], atol=1e-5)


def test_parse_crease():
    assert parse_crease({}) is None
    assert parse_crease({"crease": 60}) == 60.0
    assert parse_crease({"crease": 12.5}) == 12.5
    for bad in ({"crease": True}, {"crease": "soft"}, {"crease": 181}, {"crease": -1}):
        with pytest.raises(ValueError, match="crease"):
            parse_crease(bad)
    with pytest.raises(ValueError):
        parse_crease([])


def test_every_body_in_the_data_plans(data_dir, profile):
    from PyAitD.engine.assets import Assets
    assets = Assets(data_dir, profile)
    for num in range(assets.num_bodies):
        body = assets.body(num)
        plan = plan_refinement(body)
        geo = pose_geometry(body, [(0, (0, 0, 0))] * len(body.groups), (0, 0, 0))
        m = len(geo.tris)
        assert plan.orientation.shape == (m,) and set(np.unique(plan.orientation)) <= {-1.0, 1.0}
        assert plan.straight.shape == (m, 3) and set(np.unique(plan.straight)) <= {0.0, 1.0}
        if m:
            assert plan.pairs[:, 0].max() < 3 * m and plan.pairs[:, 1].max() < m
            assert len(np.unique(plan.pairs[:, 0])) == 3 * m     # every corner lists at least its own face


def test_the_hero_body_corner_normals_agree_with_their_faces(data_dir, profile):
    # The defect this module exists to fix: geometry._vertex_normals lets a
    # face feed a vertex only when the whole face lies in that vertex's
    # skeleton group, and 46 of the hero's 131 mesh vertices touch only
    # faces that span two groups -- they get the camera-facing placeholder,
    # which disagrees with most of the faces it is drawn on. Every corner
    # normal here comes from the corner's own face plus its smoothing group,
    # so it agrees with its face -- bar a handful of corners at fans that
    # wrap past 90 degrees (4 of 642 on this body). Measured against the
    # face's own oriented normal, not against the placeholder vector: a
    # face that genuinely faces -z has a genuine (0, 0, -1) normal.
    from PyAitD.engine.assets import Assets
    body = Assets(data_dir, profile).body(12)
    plan = plan_refinement(body)
    geo = pose_geometry(body, [(0, (0, 0, 0))] * len(body.groups), (0, 0, 0), refinement=plan)
    v = geo.vertices.astype(np.float64)
    t = geo.tris
    face = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]]) * plan.orientation[:, None]
    real = np.linalg.norm(face, axis=1) > 1e-9
    agree = np.einsum("mc,mkc->mk", face, geo.corner_normals.astype(np.float64)) > 0
    legacy = np.einsum("mc,mkc->mk", face, geo.normals[t].astype(np.float64)) > 0
    assert (~agree[real]).mean() < 0.02
    assert (~legacy[real]).mean() > 0.5
```

- [ ] **Step 2: Write the failing geometry tests**

Append to `tests/test_geometry.py`:

```python
def test_corner_normals_default_to_the_vertex_normals_and_straight_to_zeros():
    geo = pose_geometry(_cube_body(), [], None)
    assert geo.corner_normals.shape == (12, 3, 3) and geo.corner_normals.dtype == np.float32
    assert np.array_equal(geo.corner_normals, geo.normals[geo.tris])
    assert geo.straight.shape == (12, 3) and not geo.straight.any()


def test_a_refinement_fills_corner_normals_and_straight_but_leaves_normals_alone():
    from PyAitD.render.refine import plan_refinement
    body = _cube_body()
    plain = pose_geometry(body, [], None)
    plan = plan_refinement(body)
    geo = pose_geometry(body, [], None, refinement=plan)
    assert geo.straight is plan.straight
    assert np.array_equal(geo.normals, plain.normals)
    assert geo.corner_normals.shape == (12, 3, 3)
    assert not np.array_equal(geo.corner_normals, plain.corner_normals)   # creased corners take their face normal
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_refine.py tests/test_geometry.py -q`
Expected: FAIL — `ModuleNotFoundError: PyAitD.render.refine`, `AttributeError: corner_normals`.

- [ ] **Step 4: Create `PyAitD/render/refine.py`**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Rest-pose mesh refinement for the GPU tessellation of a FITD body.

A body is a soup of polygons over a shared vertex list, wound consistently
(measured: every shared edge of every shipped body is walked in opposite
directions by its two faces) but with an unknown inward/outward sign, open
at limb rings, and non-manifold where panels meet. This module plans, once
per body from its rest pose, everything the tessellating vertex shader in
render_gl needs that depends on mesh topology rather than on the pose:

- `orientation`: a sign per face making face normals agree across shared
  edges (breadth-first over two-face edges; a safety net on shipped data);
- `straight`: which of each triangle's three edges is a crease -- sharper
  than `crease_deg` between its two oriented faces, shared by three or more
  faces, or belonging to a zero-area face -- and therefore keeps a straight
  PN control polygon so a smooth patch never opens a crack against a hard
  neighbour. Boundary edges (one face) curve;
- `pairs`: for every triangle corner, the faces that feed its normal: the
  faces reachable from the corner's own face through non-crease edges at
  that vertex -- its smoothing group. Unlike geometry._vertex_normals this
  counts faces that span skeleton groups, which is what leaves a third of
  the hero's vertices with a placeholder normal there.

`corner_normals` then turns posed vertices into one normal per triangle
corner each frame, `subpatch` is the barycentric sub-triangle list one
tessellation level draws, and `evaluate` is the numpy twin of the shader's
PN-triangle formula, for tests. Pure numpy: no pygame, no GL."""
from dataclasses import dataclass
import functools

import numpy as np

from PyAitD.render.geometry import _CAMERA_FACING, pose_geometry

CREASE_DEG = 80.0
MAX_CREASE_DEG = 180.0
_DEGENERATE = 1e-9


@dataclass(frozen=True)
class Refinement:
    orientation: np.ndarray   # (M,) float32 +-1
    pairs: np.ndarray         # (K,2) int32 (corner = 3*face + k, contributing face)
    straight: np.ndarray      # (M,3) float32: 1.0 where edge k (v_k -> v_k+1) is a crease
    crease_deg: float

    def corner_normals(self, vertices, tris):
        return corner_normals(vertices, tris, self)


def _face_normals(vertices, tris):
    """Area-weighted (unnormalised) cross products, in the authored winding."""
    a, b, c = vertices[tris[:, 0]], vertices[tris[:, 1]], vertices[tris[:, 2]]
    return np.cross(b - a, c - a)


def _edges(tris):
    """{(lo, hi): [(face, corner, forward), ...]} over every directed edge
    of every face; `forward` is whether the face walks lo -> hi."""
    edges = {}
    for f, (i, j, k) in enumerate(tris.tolist()):
        for corner, (u, v) in enumerate(((i, j), (j, k), (k, i))):
            key = (u, v) if u < v else (v, u)
            edges.setdefault(key, []).append((f, corner, u < v))
    return edges


def _orient(tris, edges, normals, vertices):
    m = len(tris)
    sign = np.zeros(m, dtype=np.float32)
    neighbours = [[] for _ in range(m)]
    for faces in edges.values():
        if len(faces) == 2:
            (f0, _, fwd0), (f1, _, fwd1) = faces
            # two consistently wound faces walk a shared edge in opposite
            # directions; walking it the same way means one must flip
            neighbours[f0].append((f1, fwd0 == fwd1))
            neighbours[f1].append((f0, fwd0 == fwd1))
    for seed in range(m):
        if sign[seed]:
            continue
        sign[seed] = 1.0
        component = [seed]
        queue = [seed]
        while queue:
            f = queue.pop()
            for g, same in neighbours[f]:
                if not sign[g]:
                    sign[g] = -sign[f] if same else sign[f]
                    component.append(g)
                    queue.append(g)
        # the component's global sign: normals point away from its centroid
        comp = np.array(component)
        centroids = vertices[tris[comp]].mean(axis=1)
        centre = centroids.mean(axis=0)
        outward = float((normals[comp] * sign[comp, None] * (centroids - centre)).sum())
        if outward < 0.0:
            sign[comp] *= -1.0
    return sign


def _straight_flags(tris, edges, normals, sign, crease_deg):
    lengths = np.linalg.norm(normals, axis=1)
    unit = np.zeros_like(normals)
    ok = lengths > _DEGENERATE
    unit[ok] = normals[ok] / lengths[ok][:, None]
    unit *= sign[:, None]
    straight = np.zeros((len(tris), 3), dtype=np.float32)
    creases = set()
    for key, faces in edges.items():
        if len(faces) == 1:
            continue                                   # boundary: curves
        if len(faces) == 2:
            f0, f1 = faces[0][0], faces[1][0]
            if ok[f0] and ok[f1]:
                angle = np.degrees(np.arccos(np.clip(float(np.dot(unit[f0], unit[f1])), -1.0, 1.0)))
                if angle <= crease_deg:
                    continue                           # smooth
        creases.add(key)
        for f, corner, _ in faces:
            straight[f, corner] = 1.0
    return straight, creases


def _corner_pairs(tris, edges, creases):
    """(corner, face) pairs: for corner (f, k) at vertex v, every face that
    reaches f through non-crease two-face edges incident to v."""
    around = {}                      # v -> {face: [faces adjacent through a smooth edge at v]}
    for key, faces in edges.items():
        if key in creases or len(faces) != 2:
            continue
        (f0, _, _), (f1, _, _) = faces
        for v in key:
            adjacency = around.setdefault(v, {})
            adjacency.setdefault(f0, []).append(f1)
            adjacency.setdefault(f1, []).append(f0)
    pairs = []
    for f, corners in enumerate(tris.tolist()):
        for k, v in enumerate(corners):
            group = {f}
            stack = [f]
            adjacency = around.get(v, {})
            while stack:
                g = stack.pop()
                for h in adjacency.get(g, ()):
                    if h not in group:
                        group.add(h)
                        stack.append(h)
            pairs.extend((3 * f + k, g) for g in sorted(group))
    return np.array(pairs, dtype=np.int32).reshape(-1, 2)


def plan_refinement(body, crease_deg=CREASE_DEG):
    """The pose-independent plan for `body`, from its assembled rest pose:
    zero animation deltas, no actor rotation, group base offsets applied --
    the same pose occlusion.bake_vertex_ao reads."""
    geometry = pose_geometry(body, [(0, (0, 0, 0))] * len(body.groups))
    tris = geometry.tris
    if len(tris) == 0:
        return Refinement(np.zeros(0, np.float32), np.zeros((0, 2), np.int32),
                          np.zeros((0, 3), np.float32), float(crease_deg))
    vertices = geometry.vertices.astype(np.float64)
    normals = _face_normals(vertices, tris)
    edges = _edges(tris)
    orientation = _orient(tris, edges, normals, vertices)
    straight, creases = _straight_flags(tris, edges, normals, orientation, float(crease_deg))
    pairs = _corner_pairs(tris, edges, creases)
    return Refinement(orientation, pairs, straight, float(crease_deg))


def corner_normals(vertices, tris, refinement):
    """(M,3,3) float32: one unit normal per triangle corner of the posed
    mesh, each the area-weighted mean of its smoothing group's oriented
    face normals. A corner whose sum vanishes (degenerate geometry) gets
    the camera-facing placeholder, as geometry._vertex_normals does."""
    tris = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    if len(tris) == 0:
        return np.zeros((0, 3, 3), dtype=np.float32)
    face = _face_normals(np.asarray(vertices, dtype=np.float64).reshape(-1, 3), tris)
    face *= refinement.orientation.astype(np.float64)[:, None]
    out = np.zeros((len(tris) * 3, 3), dtype=np.float64)
    np.add.at(out, refinement.pairs[:, 0], face[refinement.pairs[:, 1]])
    length = np.linalg.norm(out, axis=1)
    valid = length > _DEGENERATE
    out[valid] /= length[valid][:, None]
    out[~valid] = _CAMERA_FACING
    return out.reshape(-1, 3, 3).astype(np.float32)


@functools.lru_cache(maxsize=4)
def subpatch(level):
    """The barycentric triangle list of one triangle split into 2**level
    segments per edge: (3 * 4**level, 3) float32 rows of (u, v, w), u the
    weight of corner 0. Corners appear exactly. Read-only and shared, like
    geometry.icosphere."""
    n = 2 ** level
    index = {}
    bary = []
    for i in range(n + 1):
        for j in range(n + 1 - i):
            index[(i, j)] = len(bary)
            bary.append((i / n, j / n, (n - i - j) / n))
    tris = []
    for i in range(n):
        for j in range(n - i):
            tris.append((index[(i, j)], index[(i + 1, j)], index[(i, j + 1)]))
            if j < n - i - 1:
                tris.append((index[(i + 1, j)], index[(i + 1, j + 1)], index[(i, j + 1)]))
    out = np.array(bary, dtype=np.float32)[np.array(tris, dtype=np.int64).reshape(-1)]
    out.setflags(write=False)
    return out


def evaluate(corners, normals, straight, bary):
    """PN-triangle positions and normals: the numpy twin of render_gl's
    _TESS_VSH, evaluated for every patch at every barycentric.

    corners, normals: (M,3,3); straight: (M,3), 1.0 where edge k (corner k
    to k+1) keeps a straight control polygon; bary: (S,3) -> two (M,S,3)."""
    P = np.asarray(corners, np.float64)
    N = np.asarray(normals, np.float64)
    S = np.asarray(straight, np.float64)
    B = np.asarray(bary, np.float64)

    def edge_point(i, j, k):
        # a third of the way from corner i toward j, projected onto i's
        # tangent plane -- or left on the chord when edge k is a crease
        w = np.einsum("mc,mc->m", P[:, j] - P[:, i], N[:, i])[:, None]
        return (2 * P[:, i] + P[:, j]) / 3 - (1 - S[:, k, None]) * w * N[:, i] / 3

    def edge_normal(i, j, k):
        d = P[:, j] - P[:, i]
        h = N[:, i] + N[:, j]
        dd = np.einsum("mc,mc->m", d, d)
        v = np.where(dd > 1e-12, 2 * np.einsum("mc,mc->m", d, h) / np.maximum(dd, 1e-12), 0.0)
        h = h - (1 - S[:, k, None]) * v[:, None] * d
        return h / np.maximum(np.linalg.norm(h, axis=1), 1e-12)[:, None]

    b210, b120 = edge_point(0, 1, 0), edge_point(1, 0, 0)
    b021, b012 = edge_point(1, 2, 1), edge_point(2, 1, 1)
    b102, b201 = edge_point(2, 0, 2), edge_point(0, 2, 2)
    E = (b210 + b120 + b021 + b012 + b102 + b201) / 6
    V = (P[:, 0] + P[:, 1] + P[:, 2]) / 3
    b111 = E + (E - V) / 2
    u, v, w = B[:, 0], B[:, 1], B[:, 2]

    def term(control, weight):
        return control[:, None, :] * weight[None, :, None]

    pos = (term(P[:, 0], u ** 3) + term(P[:, 1], v ** 3) + term(P[:, 2], w ** 3)
           + term(b210, 3 * u * u * v) + term(b120, 3 * u * v * v) + term(b201, 3 * u * u * w)
           + term(b021, 3 * v * v * w) + term(b102, 3 * u * w * w) + term(b012, 3 * v * w * w)
           + term(b111, 6 * u * v * w))
    n110, n011, n101 = edge_normal(0, 1, 0), edge_normal(1, 2, 1), edge_normal(2, 0, 2)
    nrm = (term(N[:, 0], u * u) + term(N[:, 1], v * v) + term(N[:, 2], w * w)
           + term(n110, u * v) + term(n011, v * w) + term(n101, w * u))
    nrm /= np.maximum(np.linalg.norm(nrm, axis=2), 1e-12)[:, :, None]
    return pos.astype(np.float32), nrm.astype(np.float32)


def parse_crease(data):
    """The optional `crease` degrees of a bodies/body<NNN>.json: None when
    absent, a float in 0..MAX_CREASE_DEG otherwise. Anything else raises
    ValueError naming the key, like materials.parse_assignments does."""
    if not isinstance(data, dict):
        raise ValueError("body override must be an object")
    if "crease" not in data:
        return None
    value = data["crease"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"crease: must be a number of degrees, got {value!r}")
    if not 0.0 <= value <= MAX_CREASE_DEG:
        raise ValueError(f"crease: must be within 0..{MAX_CREASE_DEG:g} degrees, got {value!r}")
    return float(value)
```

- [ ] **Step 5: Extend `BodyGeometry` and `pose_geometry` in `PyAitD/render/geometry.py`**

Add two fields after `ao` and extend `__post_init__`:

```python
    corner_normals: np.ndarray = None   # (M,3,3) float32, one per triangle corner: refine's crease-aware normals
    straight: np.ndarray = None         # (M,3) float32, 1.0 where a triangle edge keeps a straight PN control polygon

    def __post_init__(self):
        # Both default from `vertices` so every positional constructor
        # (tests, tools) keeps working: rest = the posed vertices (only
        # wrong for an animated body, and only for detail placement), ao =
        # fully open.
        if self.rest is None:
            object.__setattr__(self, "rest", self.vertices)
        if self.ao is None:
            object.__setattr__(self, "ao", np.ones(len(self.vertices), dtype=np.float32))
        # Without a plan a corner takes its vertex's normal and no edge is a
        # crease -- the tessellator then rounds exactly what smooth shading
        # already rounds.
        if self.corner_normals is None:
            object.__setattr__(self, "corner_normals",
                               np.asarray(self.normals, dtype=np.float32)[self.tris].reshape(-1, 3, 3))
        if self.straight is None:
            object.__setattr__(self, "straight", np.zeros((len(self.tris), 3), dtype=np.float32))
```

Change `pose_geometry`'s signature and tail to:

```python
def pose_geometry(body, group_states, actor_angles=None, ao=None, refinement=None):
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
    corner_normals = straight = None
    if refinement is not None:
        # duck-typed on purpose: refine imports this module to build its plan,
        # so geometry never imports refine
        corner_normals = refinement.corner_normals(vertices, tris)
        straight = refinement.straight
    return BodyGeometry(vertices, normals, tris, tri_colors, lines, line_colors,
                        spheres, points, point_sizes, point_colors, rest, ao, corner_normals, straight)
```

- [ ] **Step 6: Run the tests to verify they pass, then the layering and full suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_refine.py tests/test_geometry.py tests/test_layering.py tests/test_test_groups.py -q` then `make test`
Expected: green (the two data-gated refine tests run on this machine; they skip without game data).

- [ ] **Step 7: Commit**

```bash
git add PyAitD/render/refine.py PyAitD/render/geometry.py tests/test_refine.py tests/test_geometry.py
git commit -m "feat: rest-pose refinement plans, crease-aware corner normals, the PN reference" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CiEbmR6XfbostZiohp1cq4"
```

---

### Task 4: The resolver, the per-body `crease` override and `build_frame`

**Files:**
- Modify: `PyAitD/render/asset_resolver.py`, `PyAitD/render/override_check.py` (`check_body_materials`, line 132), `tools/check_overrides.py` (lines 22 and 140), `PyAitD/render/scene.py` (`build_frame`)
- Test: `tests/test_asset_resolver.py`, `tests/test_override_check.py`, `tests/test_scene.py`

**Interfaces:**
- Consumes: `refine.plan_refinement`, `refine.parse_crease`, `refine.CREASE_DEG`, `materials.parse_assignments`.
- Produces: `asset_resolver._validate_body_override(data) -> None` (raises `ValueError`); `AssetResolver.refinement(num) -> Refinement` (memoised in `self._refinements`); `override_check.check_bodies(override_dir) -> list[Finding]` (replaces `check_body_materials`); `build_frame` handing `refinement=resolver.refinement(actor.body_num)` to `pose_geometry`.

- [ ] **Step 1: Write the failing resolver tests**

Append to `tests/test_asset_resolver.py`:

```python
def _triangle_body():
    from PyAitD.engine.formats import Body, Primitive
    return Body(0, (0,) * 6, (), [(0, 0, 0), (100, 0, 0), (0, 100, 0)], [], [], [Primitive(1, 0, 1, [0, 1, 2])])


def test_refinement_plans_once_per_body():
    from PyAitD.render.refine import CREASE_DEG, Refinement
    calls = []
    body = _triangle_body()

    def counting_body(num):
        calls.append(num)
        return body

    resolver = AssetResolver(SimpleNamespace(body=counting_body), None)
    first = resolver.refinement(7)
    second = resolver.refinement(7)
    assert isinstance(first, Refinement) and first is second and calls == [7]
    assert first.crease_deg == CREASE_DEG and first.straight.tolist() == [[0.0, 0.0, 0.0]]


def test_refinement_follows_a_per_body_crease_override(tmp_path):
    from PyAitD.render.asset_resolver import override_body_material_path
    path = override_body_material_path(tmp_path, 7)
    path.parent.mkdir(parents=True)
    path.write_text('{"crease": 45, "indices": {"5": "metal"}}')
    resolver = AssetResolver(SimpleNamespace(body=lambda n: _triangle_body()), tmp_path)
    assert resolver.refinement(7).crease_deg == 45.0
    assert resolver.material_table(7).classes[5] == "metal"    # the same file feeds both
    assert resolver.refinement(8).crease_deg == 80.0            # no file, the default


def test_an_invalid_crease_rejects_the_whole_body_file_once(tmp_path, caplog):
    from PyAitD.render.asset_resolver import override_body_material_path
    from PyAitD.render.materials import default_table
    path = override_body_material_path(tmp_path, 2)
    path.parent.mkdir(parents=True)
    path.write_text('{"crease": "soft", "indices": {"5": "metal"}}')
    resolver = AssetResolver(SimpleNamespace(body=lambda n: _triangle_body()), tmp_path)
    with caplog.at_level(logging.WARNING):
        assert resolver.refinement(2).crease_deg == 80.0
        assert resolver.material_table(2) is default_table()    # one file, one verdict
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "crease" in warnings[0].getMessage()
    assert path in resolver.failures
```

In `tests/test_override_check.py`: rename every `oc.check_body_materials(` call to `oc.check_bodies(` (three sites) and append:

```python
def test_an_invalid_crease_is_a_body_finding(tmp_path):
    from PyAitD.render.asset_resolver import override_body_material_path
    bad = override_body_material_path(tmp_path, 4)
    bad.parent.mkdir(parents=True)
    bad.write_text('{"crease": "soft"}')
    override_body_material_path(tmp_path, 5).write_text('{"crease": 30}')
    f = oc.check_bodies(tmp_path)
    assert [(x.camera, x.kind) for x in f] == [(4, "invalid")]
    assert "crease" in f[0].detail
```

In `tests/test_scene.py`: give `_StubResolver` a plan and pin that it rides on the geometry —

```python
    def refinement(self, num):
        from PyAitD.render.refine import plan_refinement
        return plan_refinement(self._bodies[num])
```

and, in `test_build_frame_assembles_frame_description_from_stubs`, extend the "the resolver's bake and table ride on each ActorDraw" loop:

```python
    for actor in frame.actors:
        assert actor.materials is default_table()
        assert (actor.geometry.ao == 0.5).all()
        assert actor.geometry.corner_normals.shape == (len(actor.geometry.tris), 3, 3)
        assert actor.geometry.straight is resolver.refinement(game.actors[actor.index].body_num).straight or (
            actor.geometry.straight.shape == (len(actor.geometry.tris), 3))
```

(the stub re-plans on every call, so identity is not guaranteed; the shape check is the contract).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_asset_resolver.py tests/test_override_check.py tests/test_scene.py -q`
Expected: FAIL — `AttributeError: refinement`, `AttributeError: check_bodies`.

- [ ] **Step 3: Implement**

`PyAitD/render/asset_resolver.py` — imports:

```python
from PyAitD.render.materials import default_table, parse_assignments
from PyAitD.render.occlusion import bake_vertex_ao
from PyAitD.render.refine import CREASE_DEG, parse_crease, plan_refinement
```

Above `class AssetResolver`:

```python
def _validate_body_override(data):
    """One verdict per bodies/body<NNN>.json: its material assignments and
    its optional crease must both parse, or the whole file is ignored."""
    parse_assignments(data)
    parse_crease(data)
```

In `__init__` add `self._refinements = {}`. Change `material_table` to validate through the shared function:

```python
                data = self._override(override_body_material_path(self._override_dir, num),
                                      _validate_body_override, load=load_json)
```

and add after `geometry_ao`:

```python
    def refinement(self, num):
        """The tessellation plan for body `num` (refine.plan_refinement),
        made once per session at the crease threshold its override file
        sets, or refine.CREASE_DEG. Read through the same cached, once-
        validated file as material_table: an invalid crease rejects the
        materials too, and vice versa."""
        if num not in self._refinements:
            crease = CREASE_DEG
            if self._override_dir is not None:
                data = self._override(override_body_material_path(self._override_dir, num),
                                      _validate_body_override, load=load_json)
                if data is not None:
                    value = parse_crease(data)
                    if value is not None:
                        crease = value
            self._refinements[num] = plan_refinement(self.body(num), crease)
        return self._refinements[num]
```

`PyAitD/render/override_check.py`: rename `check_body_materials` to `check_bodies`, update its docstring's first line to "One Finding per file under bodies/ the game would not load — a material remap or a crease it rejects, or a body*.json whose name the resolver would never ask for", and replace the `resolver.material_table(num)` call with:

```python
        resolver.material_table(num)
        resolver.refinement(num)      # same file, same verdict; kept explicit so a future split still checks both
```

`tools/check_overrides.py`: rename the import (line 22) and the call (line 140) to `check_bodies`.

`PyAitD/render/scene.py`, in `build_frame`:

```python
            pose_geometry(body, states, angles, ao=resolver.geometry_ao(actor.body_num),
                          refinement=resolver.refinement(actor.body_num)),
```

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_asset_resolver.py tests/test_override_check.py tests/test_scene.py tests/test_tools_graphics_cli.py -q` then `make test`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/render/asset_resolver.py PyAitD/render/override_check.py tools/check_overrides.py PyAitD/render/scene.py tests/test_asset_resolver.py tests/test_override_check.py tests/test_scene.py
git commit -m "feat: memoised refinement plans per body with a crease override, checked like every other override" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CiEbmR6XfbostZiohp1cq4"
```

---

### Task 5: GPU tessellation of the actor draw

**Files:**
- Modify: `PyAitD/render/render_gl.py` (imports; new `_TESS_VSH` after `_ACTOR_VSH`; `__init__`; `release`; `_draw_frame`; new `_set_frame_uniforms`, `_instance_data`, `_render_instanced`, `_draw_actor_tessellated`)
- Test: `tests/test_render_gl.py`

**Interfaces:**
- Consumes: `refine.subpatch`, `render_options.SMOOTHING_LEVELS`, `BodyGeometry.corner_normals` / `.straight`.
- Produces: `render_gl._TESS_VSH: str`; `render_gl._INSTANCE_ATTRIBUTES = ("4f", "4f", "4f", "3f") * 3`; `render_gl._INSTANCE_NAMES` (12 attribute names); `render_gl.INSTANCE_FLOATS = 45`; `render_gl.instance_layout(prog) -> (format: str, names: tuple[str, ...])`; `GLBackend._tess_prog`, `._tess_shadow_prog`, `._tess_layout`, `._tess_shadow_layout`, `._subpatch_bufs: dict[int, Buffer]` (levels 1–3); `GLBackend._instance_data(geometry, position, palette) -> (M', 45) float32`; `GLBackend._render_instanced(prog, layout, buf, count, level)`; `GLBackend._set_frame_uniforms(prog, frame, mvp, rot, scene_lit)`. Task 6 uses `_tess_shadow_prog`, `_tess_shadow_layout`, `_instance_data`, `_render_instanced`.

- [ ] **Step 1: Write the failing GL tests**

Append to `tests/test_render_gl.py` (add `import math` and `from PyAitD.engine.formats import Body, Primitive` at the top):

```python
def _body_of(vertices, polys, color=1):
    return Body(0, (0,) * 6, (), [tuple(int(c) for c in v) for v in vertices], [], [],
                [Primitive(1, 0, color, list(p)) for p in polys])


def _hex_prism_body(z=600.0, radius=200.0, half_height=150.0):
    """An open hexagonal prism around the y axis at depth z, two faces
    square-on to +-x: its flat silhouette is 2 R cos 30 wide, its rounded
    one closer to 2 R."""
    ring = [(round(radius * math.cos(math.radians(30 + 60 * k))), round(z + radius * math.sin(math.radians(30 + 60 * k))))
            for k in range(6)]
    v = [(x, -half_height, zz) for x, zz in ring] + [(x, half_height, zz) for x, zz in ring]
    return _body_of(v, [(k, (k + 1) % 6, 6 + (k + 1) % 6, 6 + k) for k in range(6)])


def _closed_cube_body():
    v = [(-100, -100, -100), (100, -100, -100), (100, 100, -100), (-100, 100, -100),
         (-100, -100, 100), (100, -100, 100), (100, 100, 100), (-100, 100, 100)]
    return _body_of(v, [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (0, 3, 7, 4), (1, 2, 6, 5)])


def _planned_geometry(body):
    from PyAitD.render.geometry import pose_geometry
    from PyAitD.render.refine import plan_refinement
    return pose_geometry(body, [], (0, 0, 0), refinement=plan_refinement(body))


def _flat_backend(gl_ctx, level, scale=1):
    return GLBackend(gl_ctx, RenderOptions(scale=scale, shading="flat", lighting="fixed", msaa=0, smoothing=level))


def _instance_rows(corners, normals, straight):
    """(M,45) float32 rows in GLBackend._instance_data's layout -- per corner
    (pos.xyz, ao), (normal.xyz, straight), (rgb, index), rest -- with ao=1,
    black, index 0 and rest 0: only positions, normals and flags matter to
    the tessellation itself."""
    m = len(corners)
    parts = []
    for k in range(3):
        parts += [corners[:, k], np.ones((m, 1)), normals[:, k], straight[:, k:k + 1],
                  np.zeros((m, 3)), np.zeros((m, 1)), np.zeros((m, 3))]
    return np.concatenate(parts, axis=1).astype("f4")


def _write_if_present(prog, name, matrix):
    try:
        prog[name].write(matrix.tobytes())
    except KeyError:      # a uniform the linker dropped as unused
        pass


def test_tessellation_shader_matches_the_numpy_reference(gl_ctx):
    from PyAitD.render import refine
    from PyAitD.render.lighting import project_to_plane
    from PyAitD.render.render_gl import _TESS_VSH, instance_layout
    rng = np.random.default_rng(7)
    corners = rng.uniform(-300.0, 300.0, (4, 3, 3))
    normals = rng.normal(size=(4, 3, 3))
    normals /= np.linalg.norm(normals, axis=2, keepdims=True)
    straight = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 1], [1, 1, 1]], np.float64)
    bary = refine.subpatch(2)
    ref_pos, ref_nrm = refine.evaluate(corners, normals, straight, bary)

    prog = gl_ctx.program(vertex_shader=_TESS_VSH, varyings=["v_world", "v_normal"])
    _write_if_present(prog, "rot", np.eye(3, dtype="f4"))
    _write_if_present(prog, "mvp", np.eye(4, dtype="f4"))
    prog["project"].value = 0
    prog["travel"].value = (0.0, 1.0, 0.0)
    prog["plane_y"].value = 0.0
    bary_buf = gl_ctx.buffer(np.ascontiguousarray(bary, dtype="f4").tobytes())
    inst_buf = gl_ctx.buffer(_instance_rows(corners, normals, straight).tobytes())
    fmt, names = instance_layout(prog)
    vao = gl_ctx.vertex_array(prog, [(bary_buf, "3f", "in_bary"), (inst_buf, fmt, *names)])
    out = gl_ctx.buffer(reserve=len(corners) * len(bary) * 6 * 4)
    vao.transform(out, moderngl.POINTS, vertices=len(bary), instances=len(corners))
    got = np.frombuffer(out.read(), "f4").reshape(len(corners), len(bary), 6)
    assert np.allclose(got[..., :3], ref_pos, atol=0.05)      # 1e-4 of a 600-unit patch
    assert np.allclose(got[..., 3:], ref_nrm, atol=1e-3)

    # the shadow mode is project_to_plane's twin
    travel = (0.3, 0.8, 0.2)
    prog["project"].value = 1
    prog["travel"].value = travel
    prog["plane_y"].value = 250.0
    vao.transform(out, moderngl.POINTS, vertices=len(bary), instances=len(corners))
    projected = np.frombuffer(out.read(), "f4").reshape(len(corners), len(bary), 6)[..., :3]
    expected = project_to_plane(ref_pos.reshape(-1, 3), travel, 250.0).reshape(ref_pos.shape)
    assert np.allclose(projected, expected, atol=0.05)
    for resource in (vao, out, inst_buf, bary_buf, prog):
        resource.release()


def _row_width(rgb, row):
    return int((rgb[row].astype(int).sum(axis=1) > 0).sum())


def test_a_hexagonal_prism_is_wider_at_mid_face_once_rounded(gl_ctx):
    # At scale 4 so the bow shows: PN under-bulges a 60-degree facet (the
    # cubic reaches ~0.06 R past the chord, not the circle's 0.13 R), which
    # is 296 -> 308 px here and only 74 -> 76 px at scale 1.
    geometry = _planned_geometry(_hex_prism_body())
    widths = {}
    for level in (0, 2):
        backend = _flat_backend(gl_ctx, level, scale=4)
        backend.draw(_frame([_actor(0, geometry)]))
        widths[level] = _row_width(backend.read_rgb(), 400)
        backend.release()
    assert widths[0] >= 280                   # ~296 px: 2 R cos 30 at depth 1500, times 4
    assert widths[2] >= widths[0] + 8         # ~308 px: the faces bow out toward the circle


def test_a_creased_cube_renders_the_same_rounded_or_not(gl_ctx):
    # Every cube edge is a 90-degree crease, so each face is a flat PN
    # patch: the sub-triangles tile the original exactly. Sub-vertices on a
    # straight edge are collinear to ~1e-5 px, so a pixel centre that close
    # to an edge can still flip -- hence a tolerance rather than equality.
    geometry = _planned_geometry(_closed_cube_body())
    frames = {}
    for level in (0, 2):
        backend = _flat_backend(gl_ctx, level)
        backend.draw(_frame([_actor(0, geometry)]))
        frames[level] = backend.read_rgb()
        backend.release()
    assert (frames[0].astype(int).sum(axis=2) > 0).sum() > 500     # the cube is really drawn
    assert int(np.any(frames[0] != frames[2], axis=2).sum()) <= 2


def test_a_sphere_gets_rounder_with_smoothing(gl_ctx):
    sphere = BodyGeometry(
        np.array([[0.0, 0.0, 600.0]], np.float32), np.array([[0.0, 0.0, -1.0]], np.float32),
        np.zeros((0, 3), np.int32), np.zeros(0, np.uint8),
        np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), ((0, 300.0, 1),),
        np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))
    counts = {}
    for level in (0, 2):
        backend = _flat_backend(gl_ctx, level)
        backend.draw(_frame([_actor(0, sphere)]))
        counts[level] = int((backend.read_rgb().astype(int).sum(axis=2) > 0).sum())
        backend.release()
    # the level-1 icosphere's silhouette is a ~12-gon inscribed in the disc;
    # PN patches bow it back out toward the circle
    assert counts[2] > counts[0] + 100


def test_smoothing_zero_draws_through_the_legacy_path(gl_ctx, monkeypatch):
    backend = _flat_backend(gl_ctx, 0)
    monkeypatch.setattr(backend, "_render_instanced", lambda *a, **k: (_ for _ in ()).throw(AssertionError("tessellated")))
    backend.draw(_frame([_actor(0, _planned_geometry(_closed_cube_body()))]))
    backend.release()
```

Then edit `test_init_failure_releases_every_already_allocated_gl_object`: add `"_tess_prog", "_tess_shadow_prog"` to the attribute tuple (after `"_material_tex"`), and before `assert leak_checked == 25` insert

```python
    assert sorted(backend._subpatch_bufs) == [1, 2, 3]
    for level, buf in backend._subpatch_bufs.items():
        assert isinstance(buf.mglo, moderngl.InvalidObject), f"subpatch buffer {level} leaked"
        leak_checked += 1
```

and change the count to `assert leak_checked == 30`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q -k "tessellation or prism or creased_cube or sphere_gets or legacy_path or init_failure"`
Expected: FAIL — `ImportError: _TESS_VSH`, `AttributeError: _subpatch_bufs`, prism widths equal.

- [ ] **Step 3: Implement in `PyAitD/render/render_gl.py`**

Imports: add `from PyAitD.render.refine import subpatch` and `from PyAitD.render.render_options import SMOOTHING_LEVELS`.

Constants, after `CONTACT_HEIGHT`:

```python
# One instance per source triangle for the tessellating programs: per
# corner k, (pos.xyz, ao), (normal.xyz, straight of edge k -> k+1),
# (rgb, palette index), rest.xyz -- 15 floats, 45 per triangle, twelve
# packed attributes plus the per-vertex barycentric: 13 of the 16 slots
# GL 3.3 guarantees.
INSTANCE_FLOATS = 45
_INSTANCE_ATTRIBUTES = ("4f", "4f", "4f", "3f") * 3
_INSTANCE_NAMES = ("in_p0", "in_n0", "in_c0", "in_r0",
                   "in_p1", "in_n1", "in_c1", "in_r1",
                   "in_p2", "in_n2", "in_c2", "in_r2")


def instance_layout(prog):
    """(format, names) that bind an INSTANCE_FLOATS-wide buffer to `prog`.
    A linker may drop an attribute a program never ends up reading (a
    shadow program discards colour, a transform-feedback test captures two
    varyings), and ModernGL refuses to bind a name the program lacks: a
    dropped attribute becomes padding of the same width, so the buffer's
    stride never changes."""
    present = set(prog)
    tokens, names = [], []
    for name, fmt in zip(_INSTANCE_NAMES, _INSTANCE_ATTRIBUTES):
        if name in present:
            tokens.append(fmt)
            names.append(name)
        else:
            tokens.append(f"{fmt[0]}x4")
    return " ".join(tokens) + "/i", tuple(names)
```

The shader, after `_ACTOR_VSH`:

```python
_TESS_VSH = """
#version 330
// PN-triangle tessellation, one instance per source triangle (see
// _INSTANCE_ATTRIBUTES), evaluated at the sub-patch barycentric in in_bary.
// Emits exactly _ACTOR_VSH's varyings so _ACTOR_FSH is reused unchanged;
// refine.evaluate is the numpy twin the parity test pins this against.
uniform mat4 mvp; uniform mat3 rot;
// project == 1 is the shadow mode: the evaluated point slides along
// `travel` onto the plane y == plane_y before mvp -- lighting.project_to_plane.
uniform int project; uniform vec3 travel; uniform float plane_y;
in vec3 in_bary;
in vec4 in_p0; in vec4 in_n0; in vec4 in_c0; in vec3 in_r0;
in vec4 in_p1; in vec4 in_n1; in vec4 in_c1; in vec3 in_r1;
in vec4 in_p2; in vec4 in_n2; in vec4 in_c2; in vec3 in_r2;
out vec3 v_color; out vec3 v_normal; out vec3 v_rest; out float v_ao; flat out float v_index; out float v_world_y;
out vec3 v_world;   // the evaluated world position: read back by transform feedback in tests, unused by the fragment shader

vec3 edge_point(vec3 pi, vec3 pj, vec3 ni, float straight) {
    // a third of the way from pi toward pj, projected onto pi's tangent
    // plane -- or left on the chord when the edge is a crease
    return (2.0 * pi + pj) / 3.0 - (1.0 - straight) * dot(pj - pi, ni) * ni / 3.0;
}
vec3 edge_normal(vec3 pi, vec3 pj, vec3 ni, vec3 nj, float straight) {
    vec3 d = pj - pi;
    vec3 h = ni + nj;
    float dd = dot(d, d);
    float v = dd > 1e-12 ? 2.0 * dot(d, h) / dd : 0.0;
    return normalize(h - (1.0 - straight) * v * d);
}
void main() {
    vec3 p0 = in_p0.xyz, p1 = in_p1.xyz, p2 = in_p2.xyz;
    vec3 n0 = in_n0.xyz, n1 = in_n1.xyz, n2 = in_n2.xyz;
    float s01 = in_n0.w, s12 = in_n1.w, s20 = in_n2.w;
    vec3 b210 = edge_point(p0, p1, n0, s01), b120 = edge_point(p1, p0, n1, s01);
    vec3 b021 = edge_point(p1, p2, n1, s12), b012 = edge_point(p2, p1, n2, s12);
    vec3 b102 = edge_point(p2, p0, n2, s20), b201 = edge_point(p0, p2, n0, s20);
    vec3 e = (b210 + b120 + b021 + b012 + b102 + b201) / 6.0;
    vec3 b111 = e + (e - (p0 + p1 + p2) / 3.0) / 2.0;
    float u = in_bary.x, v = in_bary.y, w = in_bary.z;
    vec3 pos = p0 * u*u*u + p1 * v*v*v + p2 * w*w*w
             + b210 * 3.0*u*u*v + b120 * 3.0*u*v*v + b201 * 3.0*u*u*w
             + b021 * 3.0*v*v*w + b102 * 3.0*u*w*w + b012 * 3.0*v*w*w
             + b111 * 6.0*u*v*w;
    vec3 n110 = edge_normal(p0, p1, n0, n1, s01);
    vec3 n011 = edge_normal(p1, p2, n1, n2, s12);
    vec3 n101 = edge_normal(p2, p0, n2, n0, s20);
    vec3 n = normalize(n0 * u*u + n1 * v*v + n2 * w*w + n110 * u*v + n011 * v*w + n101 * w*u);
    if (project == 1) pos += (plane_y - pos.y) / travel.y * travel;
    gl_Position = mvp * vec4(pos, 1.0);
    v_world = pos;
    // the three corners carry the triangle's one colour; blending them keeps
    // every instance attribute referenced, so no driver's linker drops one
    v_color = in_c0.xyz * u + in_c1.xyz * v + in_c2.xyz * w; v_index = in_c0.w;
    v_normal = rot * n;
    v_rest = in_r0 * u + in_r1 * v + in_r2 * w;
    v_ao = in_p0.w * u + in_p1.w * v + in_p2.w * w;
    v_world_y = pos.y;
}
"""
```

In `__init__`, with the other `None` pre-sets add `self._tess_prog = None`, `self._tess_shadow_prog = None`, `self._subpatch_bufs = {}`, `self._tess_layout = self._tess_shadow_layout = None` (plain tuples, not GL objects: nothing to release); inside the `try`, directly before `self._sphere = icosphere(1)`:

```python
            # The tessellating programs and their sub-patch buffers exist
            # whatever `smoothing` says: the option is a per-frame choice
            # (Renderer.set_options rebuilds the backend anyway), and
            # compiling at construction is how every other program fails
            # over to the software backend when a driver rejects it.
            self._tess_prog = ctx.program(vertex_shader=_TESS_VSH, fragment_shader=_ACTOR_FSH)
            self._tess_shadow_prog = ctx.program(vertex_shader=_TESS_VSH, fragment_shader=_STENCIL_FSH)
            self._tess_prog["travel"].value = (0.0, 1.0, 0.0)
            self._tess_layout = instance_layout(self._tess_prog)
            self._tess_shadow_layout = instance_layout(self._tess_shadow_prog)
            for level in SMOOTHING_LEVELS[1:]:
                self._subpatch_bufs[level] = ctx.buffer(np.ascontiguousarray(subpatch(level), dtype="f4").tobytes())
```

In `release()`, extend the tuple with `self._tess_prog, self._tess_shadow_prog, *self._subpatch_bufs.values(),` (after `self._material_tex,`).

Replace the uniform block of `_draw_frame` (from `mvp = camera_matrix(...)` through `self._screen_prog["target_size"].value = self.size`) with:

```python
        mvp = camera_matrix(frame.camera, self._options.scale)
        rot = rotation_matrix(frame.camera.state).astype("f4")
        scene_lit = self._options.lighting == "scene"
        level = self._options.smoothing
        travel = None
        if scene_lit:
            # rotation_matrix maps world -> camera and is orthonormal, so
            # its transpose maps back. `direction` points toward the light;
            # light travels the other way. Computed only here so the
            # byte-for-byte `fixed` escape hatch never touches frame.light.
            travel = -(rot.astype(np.float64).T
                       @ np.asarray(frame.light.direction, np.float64))
            self._material_tex.use(location=3)
        self._set_frame_uniforms(self._actor_prog, frame, mvp, rot, scene_lit)
        if level:
            self._set_frame_uniforms(self._tess_prog, frame, mvp, rot, scene_lit)
        self._screen_prog["target_size"].value = self.size
```

and the per-actor loop body with:

```python
        for actor in frame.actors:
            masks = [mask_by_id[i] for i in actor.mask_ids if i in mask_by_id]
            self._rasterize_masks(masks)  # switches to the mask FBO and disables depth test

            instances = None
            if level:
                data = self._instance_data(actor.geometry, np.asarray(actor.position, np.float64), palette)
                instances = (self._ctx.buffer(data.tobytes()), len(data)) if len(data) else None

            if scene_lit and self._rasterize_shadow(actor, travel, mvp):
                self._composite_shadow(frame.light)

            self._target.use()
            self._ctx.viewport = (0, 0, *self.size)
            self._ctx.enable(moderngl.DEPTH_TEST)
            self._ctx.depth_func = "<="
            # A fresh depth buffer per actor: within one actor's own
            # primitives, depth decides what's in front; across actors,
            # later draws simply paint over earlier ones (painter's order).
            self._target.color_mask = (False, False, False, False)
            self._target.clear(depth=1.0)
            self._target.color_mask = (True, True, True, True)
            # Framebuffer.clear() leaves moderngl's colour-mask state
            # desynced from the GL binding point: re-`use()` the target so
            # the restored mask actually takes effect before the next
            # render.
            self._target.use()

            self._mask_tex.use(location=1)
            self._actor_prog["mask_tex"].value = 1
            self._screen_prog["mask_tex"].value = 1
            if level:
                self._tess_prog["mask_tex"].value = 1

            if scene_lit:
                self._actor_prog["plane_y"].value = _plane_y(actor)
                if level:
                    self._tess_prog["plane_y"].value = _plane_y(actor)
                self._upload_materials(actor.materials)
            if level:
                self._draw_actor_tessellated(actor, frame, palette, instances, level)
                if instances is not None:
                    instances[0].release()
            else:
                self._draw_actor(actor, frame, palette)
            self._ctx.disable(moderngl.DEPTH_TEST)
```

Add the helpers after `_draw_frame`:

```python
    def _set_frame_uniforms(self, prog, frame, mvp, rot, scene_lit):
        """Everything an actor program needs once per frame. Shared by
        _actor_prog and _tess_prog so the two can never disagree about the
        light; the values are exactly what _draw_frame set inline before."""
        prog["mvp"].write(mvp.T.tobytes())
        prog["rot"].write(rot.T.tobytes())
        prog["shading"].value = _SHADING_INDEX[self._options.shading]
        if scene_lit:
            key_tint, fill_tint = shading_terms(frame.light)
            prog["lighting"].value = 1
            prog["light"].value = tuple(float(v) for v in frame.light.direction)
            prog["key_tint"].value = tuple(float(v) for v in key_tint)
            prog["fill_tint"].value = tuple(float(v) for v in fill_tint)
            preset = PRESETS[self._options.realism]
            prog["preset_a"].value = (preset.spec, preset.rim, preset.ao)
            prog["preset_b"].value = (preset.contact, preset.detail, preset.hemisphere)
            prog["contact_height"].value = CONTACT_HEIGHT
            prog["material_tex"].value = 3
        else:
            prog["lighting"].value = 0
            prog["light"].value = LIGHT_DIR
            prog["key_tint"].value = (0.0, 0.0, 0.0)
            prog["fill_tint"].value = (0.0, 0.0, 0.0)
            prog["preset_a"].value = (0.0, 0.0, 0.0)
            prog["preset_b"].value = (0.0, 0.0, 0.0)
        prog["target_size"].value = self.size

    def _instance_data(self, geometry, position, palette):
        """(M', INSTANCE_FLOATS) float32, one row per triangle -- the body's
        triangles then the expanded sphere triangles -- in _INSTANCE_ATTRIBUTES'
        layout. The same numbers _triangle_data gathers, one triangle per row."""
        rows = []
        if len(geometry.tris):
            idx = geometry.tris
            pos = geometry.vertices[idx].astype(np.float64) + position          # (M,3,3)
            ao = geometry.ao[idx][:, :, None]                                   # (M,3,1)
            normal = geometry.corner_normals.astype(np.float64)                 # (M,3,3)
            straight = geometry.straight[:, :, None]                            # (M,3,1)
            col = np.repeat(palette[geometry.tri_colors][:, None, :], 3, axis=1)   # (M,3,3)
            index = np.repeat(geometry.tri_colors.astype("f4")[:, None, None], 3, axis=1)   # (M,3,1)
            rest = geometry.rest[idx]                                           # (M,3,3)
            rows.append(np.concatenate([pos, ao, normal, straight, col, index, rest], axis=2).reshape(len(idx), INSTANCE_FLOATS))
        if geometry.spheres:
            sphere_verts, sphere_tris = self._sphere   # cached, lru_cache-shared: never mutated
            unit = sphere_verts[sphere_tris].astype(np.float64)                 # (80,3,3) fancy-indexed copy
            m = len(unit)
            for centre_idx, radius, color in geometry.spheres:
                centre = geometry.vertices[centre_idx].astype(np.float64) + position
                pos = unit * radius + centre
                # rest = the sphere's own surface about its rest centre, so
                # grain is fixed to the ball; ao = open; the unit vectors
                # are exact sphere normals, which is what lets PN round an
                # 80-triangle icosphere into a sphere; no edge is a crease
                rest = unit * radius + geometry.rest[centre_idx]
                rows.append(np.concatenate([
                    pos, np.ones((m, 3, 1)), unit, np.zeros((m, 3, 1)),
                    np.tile(palette[color], (m, 3, 1)), np.full((m, 3, 1), float(color)), rest,
                ], axis=2).reshape(m, INSTANCE_FLOATS))
        if not rows:
            return np.zeros((0, INSTANCE_FLOATS), dtype="f4")
        return np.ascontiguousarray(np.concatenate(rows, axis=0), dtype="f4")

    def _render_instanced(self, prog, layout, buf, count, level):
        fmt, names = layout
        vao = self._ctx.vertex_array(prog, [
            (self._subpatch_bufs[level], "3f", "in_bary"),
            (buf, fmt, *names),
        ])
        vao.render(moderngl.TRIANGLES, vertices=3 * 4 ** level, instances=count)
        vao.release()

    def _draw_actor_tessellated(self, actor, frame, palette, instances, level):
        if instances is not None:
            self._tess_prog["project"].value = 0
            self._render_instanced(self._tess_prog, self._tess_layout, instances[0], instances[1], level)
        position = np.asarray(actor.position, dtype=np.float64)
        self._draw_lines(actor, frame, palette, position)
        self._draw_points(actor, frame, palette, position)
```

`_draw_actor`, `_triangle_data`, `_render_triangles`, `_rasterize_shadow` and everything else stay untouched — that is the `smoothing == 0` identity.

- [ ] **Step 4: Run the GL tests, then the whole suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py tests/test_render.py -q` then `make test`
Expected: green, including `test_classic_realism_matches_the_pre_materials_golden` (default smoothing is still 0).

- [ ] **Step 5: Commit**

```bash
git add PyAitD/render/render_gl.py tests/test_render_gl.py
git commit -m "feat: GPU PN-triangle tessellation of actors through an instanced vertex shader" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CiEbmR6XfbostZiohp1cq4"
```

---

### Task 6: The tessellated shadow pass

**Files:**
- Modify: `PyAitD/render/render_gl.py` (`_draw_frame`'s shadow call; new `_rasterize_shadow_tessellated`)
- Test: `tests/test_render_gl.py`

**Interfaces:**
- Consumes: `_tess_shadow_prog`, `_tess_shadow_layout`, `_render_instanced`, `lighting._clamp_downward`.
- Produces: `GLBackend._rasterize_shadow_tessellated(instances, travel, mvp, plane_y, level) -> bool`. Consequence to document in Task 7: under `smoothing > 0` sphere primitives cast shadows (the CPU path never projected them).

- [ ] **Step 1: Write the failing shadow tests**

Append to `tests/test_render_gl.py`:

```python
def _shadow_frame(actor, plate, masks=()):
    # the light sits behind the prism and above it: the shadow falls toward
    # the camera across the ground plane, so it has an area on screen
    # rather than collapsing onto the horizon row
    light = _scene_light((0.0, -0.5, 0.85))
    return FrameDescription(_view(), ImageAsset(plate, False), _palette(), (actor,), tuple(masks), light)


def _darkened_below_the_feet(gl_ctx, level, actor, plate):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat", lighting="scene", msaa=0, smoothing=level))
    backend.draw(_shadow_frame(actor, plate))
    rendered = backend.read_rgb().astype(int)
    backend.release()
    plain = _plain_background(gl_ctx, plate)
    # rows 137+ are below the prism's nearest foot (row ~134): shadow only
    return int((rendered[137:] < plain[137:] - 5).any(axis=2).sum())


def test_the_tessellated_shadow_is_as_round_as_the_actor(gl_ctx):
    plate = np.full((200, 320, 3), 200, np.uint8)
    actor = _standing_actor(0, _planned_geometry(_hex_prism_body()), feet_y=150)
    flat = _darkened_below_the_feet(gl_ctx, 0, actor, plate)
    rounded = _darkened_below_the_feet(gl_ctx, 2, actor, plate)
    assert flat > 100                     # a real shadow band, ~8 rows x ~69 px
    assert rounded > flat + 40            # ~11 px wider on every row


def test_a_tessellated_shadow_is_still_erased_under_a_mask(gl_ctx):
    plate = np.full((200, 320, 3), 200, np.uint8)
    geometry = _planned_geometry(_hex_prism_body())
    actor = ActorDraw(0, geometry, (0.0, 0.0, 0.0), 0, (0, 0, -50, 150, 0, 0), RenderResult([], []), (0,))
    full = MaskDraw(0, (np.array([[0, 0], [320, 0], [320, 200], [0, 200]], np.int16),),
                    (0, 0, 320, 200), 0, ())
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat", lighting="scene", msaa=0, smoothing=2))
    backend.draw(_shadow_frame(actor, plate, [full]))
    assert np.array_equal(backend.read_rgb(), _plain_background(gl_ctx, plate))
    backend.release()


def test_a_sphere_casts_a_shadow_only_once_tessellated(gl_ctx):
    # The CPU shadow path projects geometry.tris and never saw a sphere
    # primitive; the instance stream carries them, so heads and hands cast
    # shadows under smoothing > 0. Pinned so the change stays deliberate.
    plate = np.full((200, 320, 3), 200, np.uint8)
    sphere = BodyGeometry(
        np.array([[0.0, 0.0, 600.0]], np.float32), np.array([[0.0, 0.0, -1.0]], np.float32),
        np.zeros((0, 3), np.int32), np.zeros(0, np.uint8),
        np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), ((0, 150.0, 1),),
        np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))
    actor = _standing_actor(0, sphere, feet_y=150)
    assert _darkened_below_the_feet(gl_ctx, 0, actor, plate) == 0
    assert _darkened_below_the_feet(gl_ctx, 2, actor, plate) > 50
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q -k "tessellated_shadow or casts_a_shadow_only"`
Expected: FAIL — `rounded > flat + 40` fails (the CPU shadow is still the flat silhouette), the sphere casts none at level 2.

- [ ] **Step 3: Implement**

In `PyAitD/render/render_gl.py`, import `_clamp_downward` alongside the other `lighting` names:

```python
from PyAitD.render.lighting import _clamp_downward, project_to_plane, shading_terms, shadow_opacity
```

In `_draw_frame`'s per-actor loop, replace

```python
            if scene_lit and self._rasterize_shadow(actor, travel, mvp):
                self._composite_shadow(frame.light)
```

with

```python
            if scene_lit:
                if level:
                    cast = self._rasterize_shadow_tessellated(instances, travel, mvp, _plane_y(actor), level)
                else:
                    cast = self._rasterize_shadow(actor, travel, mvp)
                if cast:
                    self._composite_shadow(frame.light)
```

and add, after `_rasterize_shadow`:

```python
    def _rasterize_shadow_tessellated(self, instances, travel, mvp, plane_y, level):
        """_rasterize_shadow's twin for the tessellated path: the same
        instance buffer the actor is about to be drawn from, evaluated by
        _TESS_VSH in its `project` mode, so the coverage silhouette is
        exactly as round as the actor. `travel` is tipped onto the MIN_UP
        cone here, as project_to_plane does on the CPU, and handed to the
        shader already clamped. Sphere primitives are in the instance
        stream, so unlike the CPU path they cast shadows too."""
        self._shadow_fbo.use()
        self._ctx.viewport = (0, 0, *self.size)
        self._ctx.disable(moderngl.DEPTH_TEST)
        self._shadow_fbo.clear(0.0, 0.0, 0.0, 0.0)
        if instances is None:
            return False
        prog = self._tess_shadow_prog
        prog["mvp"].write(mvp.T.astype("f4").tobytes())
        prog["project"].value = 1
        prog["travel"].value = tuple(float(v) for v in _clamp_downward(travel))
        prog["plane_y"].value = plane_y
        self._render_instanced(prog, self._tess_shadow_layout, instances[0], instances[1], level)
        return True
```

- [ ] **Step 4: Run the GL tests, then the whole suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_gl.py -q` then `make test`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/render/render_gl.py tests/test_render_gl.py
git commit -m "feat: project the tessellated patches for the ground shadow" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CiEbmR6XfbostZiohp1cq4"
```

---

### Task 7: Default on, the proof, the docs

**Files:**
- Modify: `PyAitD/render/render_options.py` (default), `tools/prove_graphics.py`, `Makefile` (line 85), `README.md` (lines 69–93), `AGENTS.md` (the `make proof-graphics` line and the render conventions bullet), `CONTEXT.md` (the milestone table and the render module table)
- Create: `docs/smooth-geometry-proof.md`
- Test: `tests/test_render_options.py`, `tests/test_config.py`, `tests/test_render_gl.py`, `tests/test_prove_graphics.py`

**Interfaces:**
- Produces: `RenderOptions.smoothing` default `2`; `tools.prove_graphics.render_fixture(data_dir, name, scale, shading, ctx, realism="enhanced", smoothing=None)` (`None` = the `RenderOptions` default); `output_paths(out_dir) -> [(name, mode, realism, smoothing, path), ...]` — the 12 existing files at the default level plus `<name>-smooth-enhanced-flatmesh.png` at level 0 for each fixture.

- [ ] **Step 1: Update the tests for the new default**

- `tests/test_render_options.py::test_defaults`: the tuple ends `"enhanced", 2)`. `test_smoothing_defaults_to_off_and_cycles` → rename to `test_smoothing_defaults_to_medium_and_cycles`, assert `options.smoothing == 2`, `cycle_smoothing(options).smoothing == 3`, `cycle_smoothing(RenderOptions(smoothing=3)).smoothing == 0`.
- `tests/test_config.py::test_save_writes_schema_2_with_render`: `"smoothing": 2`.
- `tests/test_render_gl.py::test_classic_realism_matches_the_pre_materials_golden`: the options become `RenderOptions(scale=1, shading="smooth", lighting="scene", msaa=0, realism="classic", smoothing=0)` with the comment `# smoothing=0 names the legacy path explicitly: the golden predates tessellation`. Also `test_smoothing_zero_draws_through_the_legacy_path` already names `smoothing=0` through `_flat_backend`.
- `tests/test_prove_graphics.py`: replace `test_output_paths_covers_every_fixture_shading_mode_and_realism` and the signature test with:

```python
def test_output_paths_cover_every_combination_plus_a_flat_mesh_pair():
    from PyAitD.render.render_options import RenderOptions
    paths = output_paths("docs/graphics-proof")
    assert len(paths) == len(FIXTURES) * len(SHADING_MODES) * len(REALISM_MODES) + len(FIXTURES)
    default = RenderOptions().smoothing
    names = {(name, mode, realism, level) for name, mode, realism, level, _ in paths}
    expected = {(n, m, r, default) for n in FIXTURES for m in SHADING_MODES for r in REALISM_MODES}
    expected |= {(n, "smooth", "enhanced", 0) for n in FIXTURES}
    assert names == expected
    for name, mode, realism, level, path in paths:
        suffix = "-flatmesh" if level == 0 else ""
        assert path == pathlib.Path("docs/graphics-proof") / f"{name}-{mode}-{realism}{suffix}.png"


def test_parse_args_smoothing_defaults_to_the_render_default():
    from PyAitD.render.render_options import RenderOptions
    assert _parse_args(["d"]).smoothing == RenderOptions().smoothing
    assert _parse_args(["d", "--smoothing", "0"]).smoothing == 0


def test_render_fixture_is_importable_with_the_documented_signature():
    import inspect
    params = list(inspect.signature(render_fixture).parameters)
    assert params == ["data_dir", "name", "scale", "shading", "ctx", "realism", "smoothing"]
```

and extend `test_render_fixture_produces_scaled_frames` with:

```python
    flat = render_fixture(data_dir, "attic", scale=2, shading="smooth", ctx=gl_ctx, smoothing=0)
    assert not np.array_equal(rgb, flat)   # the default rounds the bodies, and it shows
```

- [ ] **Step 2: Run them to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render_options.py tests/test_config.py tests/test_prove_graphics.py tests/test_render_gl.py -q -k "defaults or smoothing or schema_2 or output_paths or signature or golden"`
Expected: FAIL on the default and on `output_paths`.

- [ ] **Step 3: Flip the default and extend the proof tool**

`PyAitD/render/render_options.py`: `smoothing: int = 2`.

`tools/prove_graphics.py`:

```python
from PyAitD.render.render_options import REALISM_MODES, SHADING_MODES, SMOOTHING_LEVELS, RenderOptions
```

```python
def render_fixture(data_dir, name, scale, shading, ctx, realism="enhanced", smoothing=None):
    game, floor = _boot(data_dir, name)
    frame, _ = build_frame(game, floor, AssetResolver(game.assets))
    options = RenderOptions(scale=scale, shading=shading, realism=realism)
    if smoothing is not None:
        options = replace(options, smoothing=smoothing)
    backend = GLBackend(ctx, options)
    try:
        backend.draw(frame)
        return backend.read_rgb()
    finally:
        backend.release()


def output_paths(out_dir, smoothing=None):
    """(name, mode, realism, smoothing, path) for every fixture x shading-mode
    x realism combination at `smoothing` (the RenderOptions default when
    None), then one flat-mesh (smoothing 0) file per fixture beside the
    smooth-enhanced render, in the order rendered and printed by `main`."""
    out_dir = pathlib.Path(out_dir)
    level = RenderOptions().smoothing if smoothing is None else smoothing
    paths = [
        (name, mode, realism, level, out_dir / f"{name}-{mode}-{realism}.png")
        for name in FIXTURES
        for mode in SHADING_MODES
        for realism in REALISM_MODES
    ]
    paths += [(name, "smooth", "enhanced", 0, out_dir / f"{name}-smooth-enhanced-flatmesh.png")
              for name in FIXTURES]
    return paths
```

(add `from dataclasses import replace` to the imports). In `_parse_args` add

```python
    p.add_argument("--smoothing", type=int, choices=SMOOTHING_LEVELS, default=RenderOptions().smoothing,
                   help="mesh smoothing level for the main renders (the -flatmesh pair is always 0)")
```

and in `main` change the loop to `for name, mode, realism, level, path in output_paths(args.out, args.smoothing):` calling `render_fixture(args.data, name, args.scale, mode, ctx, realism, level)`. Update the module docstring's file list to mention the two `-flatmesh` files.

`Makefile` line 85 help text: `## Graphics proof: attic + combat fixtures at scale 4 per shading mode x realism preset, plus a flat-mesh pair, to docs/graphics-proof/`.

- [ ] **Step 4: Run the tool and the suite**

Run: `make proof-graphics` (writes 14 PNGs; open `docs/graphics-proof/attic-smooth-enhanced.png` beside `attic-smooth-enhanced-flatmesh.png` and confirm Carnby's limbs and head read round while the wardrobe and chair keep their edges), then `make test`.
Expected: 14 paths printed; suite green.

- [ ] **Step 5: Write the proof document and update the docs**

Create `docs/smooth-geometry-proof.md`:

```markdown
# Smooth actor geometry proof

Date: <today>
Spec: `docs/superpowers/specs/2026-08-28-smooth-actor-geometry-design.md`

**This document's "Manual attestation" table is a checklist for a human with
real game data and a real window; every row starts `pending` and no claim
about the rendered PNGs should be inferred from this file until a human
fills them in.** Everything under "Automated gates" was actually run, in this
environment, on this branch, and the output shown is the real output of that
run.

## What changed

Bodies are tessellated on the GPU under `smoothing` 1-3 (default 2): each
posed triangle becomes a PN patch of 4/16/64 sub-triangles evaluated by an
instanced vertex shader, with crease-aware per-corner normals planned once
per body from its rest pose (`PyAitD/render/refine.py`, 80° threshold,
`"crease"` overridable per body in `bodies/body<NNN>.json`). The ground
shadow projects the same patches, so it is as round as the actor -- and
sphere primitives (heads, hands) now cast shadows too, which the CPU path
never did. The per-corner normals also fix `smooth` shading on every
skeleton-spanning face: 46 of the hero's 131 mesh vertices used to shade
flat. `smoothing=0` reproduces the pre-change output byte for byte
(`tests/golden/scene_lit_classic.npy`). The graphics rows moved from CONFIG
to a Graphics sub-page of the system menu.

## Automated gates

<paste the real output of:>
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_refine.py tests/test_geometry.py tests/test_asset_resolver.py tests/test_override_check.py tests/test_scene.py tests/test_render_gl.py tests/test_render_options.py tests/test_ui_reducers.py tests/test_ui_render.py tests/test_prove_graphics.py -q
$ SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest -q

`tests/test_render_gl.py::test_classic_realism_matches_the_pre_materials_golden`
(now naming `smoothing=0`) and `test_tessellation_shader_matches_the_numpy_reference`
(transform feedback against `refine.evaluate`) are the binding ones.

## `make proof-graphics`

Fourteen PNGs under `docs/graphics-proof/` (git-ignored): the twelve
`<attic|combat>-<flat|lambert|smooth>-<classic|enhanced>.png` at smoothing 2,
plus `<attic|combat>-smooth-enhanced-flatmesh.png` at smoothing 0.

## Known limitations

- PN patches are C0 across edges: faint shading bands can show at patch
  borders on the coarsest bodies.
- Open limb rings curve outward, so the gap at a bent joint can grow by a
  few units.
- 80° is one global threshold: a chamfered 60-75° furniture edge rounds
  (override per body with `"crease"`); a genuinely round 85° facet stays hard.
- Silhouettes grow a few units past the `skel.skin` bbox picking uses;
  masks are unchanged.
- `lambert` shading shows the sub-facets. The software backend is unchanged.

## Manual attestation

| Check | Status |
|---|---|
| `attic-smooth-enhanced-flatmesh.png` is identical to the pre-change `attic-smooth-enhanced.png` | pending |
| Under smoothing 2, Carnby's arms, legs and head read round; the wardrobe, chair and stool keep their edges | pending |
| The rocking horse's body rounds while its rockers and flat head stay slab-like | pending |
| The ground shadow's outline is round where the actor is round | pending |
| Graphics page: Configuration shows `Graphics...` above `Back to Menu`; the page lists 7 rows plus Back, nothing clipped; every row cycles by mouse and keyboard | pending |
| Toggling Smoothing to Off in the menu changes the look live; Off looks as before | pending |
| `--smoothing 3` at scale 8 shows no cracks between patches at a hard edge | pending |
```

`README.md`: in the paragraph starting at line 69, change "Graphics rows, and seven CLI flags" to "Graphics page, and eight CLI flags"; before "`--overrides DIR`" insert `` `--smoothing {0,1,2,3}` (GPU mesh smoothing: `0` draws the flat 1992 mesh, `1`–`3` round every body with 4/16/64 curved sub-triangles per face, keeping edges sharper than 80° — overridable per body with a `"crease"` degrees key in `DIR/bodies/body<NNN>.json`), ``; change "the Configuration screen's Graphics rows persist" (line 93) to "the Graphics page's rows persist"; and where the override-directory paragraph describes `bodies/body<NNN>.json` as "a per-body material remap" add "and, optionally, its `crease` threshold".

`AGENTS.md`: the `make proof-graphics` line gains "x smoothing default, plus a flat-mesh pair"; in the `render/` conventions bullet, after `render_gl` owns all moderngl, add: "`refine` is pure numpy: the tessellation plan, the per-corner normals and the numpy twin of `_TESS_VSH` that the transform-feedback test pins the GPU against — change the formula in both or neither."

`CONTEXT.md`: add a milestone row `| Smooth actor geometry | GPU PN tessellation behind `smoothing`, crease-aware corner normals, tessellated shadow, Graphics sub-page | automated gates green; windowed attestation pending (`docs/smooth-geometry-proof.md`) |` after the "Enhanced graphics scene layer" row; add a module row `| `render/refine.py` | `plan_refinement(body) -> Refinement`, `corner_normals`, `subpatch(level)`, `evaluate`: rest-pose orientation, creases and smoothing groups for the GPU tessellation, and the numpy twin of the shader; pygame/GL-free |` after `render/occlusion.py`; append ", crease-aware per-corner normals and straight-edge flags when handed a refinement" to the `render/geometry.py` row, ", tessellation plan (with the same file's `crease`)" to the `render/asset_resolver.py` row, `smoothing` to the `render/render_options.py` field list, and ", instanced PN tessellation of actors and their shadows" to the `render/render_gl.py` row.

- [ ] **Step 6: Run the whole suite one last time and commit**

Run: `make test`
Expected: green.

```bash
git add PyAitD/render/render_options.py tools/prove_graphics.py Makefile README.md AGENTS.md CONTEXT.md docs/smooth-geometry-proof.md tests/test_render_options.py tests/test_config.py tests/test_render_gl.py tests/test_prove_graphics.py
git commit -m "feat: smoothing on by default, with the proof and docs" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01CiEbmR6XfbostZiohp1cq4"
```

---

## Spec corrections recorded by this plan

- Sphere primitives cast shadows under `smoothing > 0` (they ride in the
  instance stream); the CPU shadow path never projected them. Deliberate,
  pinned by `test_a_sphere_casts_a_shadow_only_once_tessellated`, and
  recorded in the proof document.
- The cube identity test tolerates up to two differing pixels rather than
  demanding pixel equality: sub-vertices on a straight edge are collinear
  only to float precision (a scratch run measured zero).
- The hero-body normal test measures agreement with each corner's own face
  (over 98% agree; the legacy path disagrees on over half) rather than
  "zero fallback normals": a face that genuinely faces -z has a genuine
  (0, 0, -1) normal, indistinguishable from the placeholder, and a few
  corners at fans that wrap past 90 degrees legitimately disagree.
- The prism silhouette test runs at scale 4: PN under-bulges a 60-degree
  facet (measured 74 -> 76 px at scale 1, 296 -> 308 px at scale 4).
- `_TESS_VSH` blends all three corner colours (they are equal) so every
  instance attribute stays referenced, and `instance_layout` pads any
  attribute a linker drops anyway: ModernGL refuses to bind a name the
  program lacks (measured: an unreferenced `in_c1` raised `KeyError`).
- `plan_refinement` treats a zero-area face's edges as creases (the spec
  said so) and additionally gives its corners the camera-facing fallback
  through `corner_normals`, matching `geometry._vertex_normals`.
