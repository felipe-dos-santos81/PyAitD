# Test Group Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace nine hand-maintained `prove-*` Make targets with six capability-named `test-*` targets driven by pytest markers, so a test's group travels with the test instead of living in a Makefile recipe.

**Architecture:** Every test file declares one subject marker (`engine`, `render`, `shell`, `tools`, `meta`) plus an optional cross-cutting `journey`, as a module-level `pytestmark`. The Makefile selects with `-m`. A new `tests/test_test_groups.py` parses those markers out of the files with `ast` — no imports, no subprocess — and enforces three properties: the subjects partition the suite, the marker vocabulary matches `pyproject.toml`, and every legacy `prove-*` alias still covers the file list it historically ran.

**Tech Stack:** Python 3.12, pytest 8, `ast` and `re` from the stdlib, GNU make. No new dependency.

**Spec:** `docs/superpowers/specs/2026-08-26-test-group-consolidation-design.md`

## Global Constraints

- `# SPDX-License-Identifier: GPL-2.0-only` first line of every Python file.
- Exactly one subject marker per test file: `engine`, `render`, `shell`, `tools`, `meta`. `journey` is optional and additional.
- Tie-break rule, binding: mark by the layer whose behaviour the test asserts, not by what it imports.
- Markers registered in `pyproject.toml`; `--strict-markers` in `addopts` so a typo fails instead of selecting nothing.
- `HEADLESS = SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy` used by every pytest target, `make test` included.
- All nine `prove-*` names keep working as aliases. The eight proof documents that cite them are NOT edited.
- Alias marker expressions are restricted to a single marker or `or`-joined single markers — no `and`, no `not` — so the pinning test's evaluator stays honest.
- The marker pass must not change the collected test count or any outcome. No test file is moved, renamed, split, or rewritten.
- The test suite is the only gate — no lint/formatter/typecheck is configured. Never mass-reformat.
- Use `.venv/bin/pytest`, not a bare `pytest`.

## A consequence to check, not to hide

Mapping aliases onto marker expressions **widens** what several of them run, because the superset rule permits it:

| alias | ran (files) | becomes | runs (files) |
|---|---|---|---|
| `prove` | 1 | `test-engine` | 46 |
| `prove-m3b` | 7 | `-m "engine or shell"` | 57 |
| `prove-shell` | 12 | `-m "engine or shell"` | 57 |
| `prove-mouse-only` | 1 | `test-shell` | 11 |
| `prove-mouse-accessibility` | 9 | `test-shell` | 11 |

`make prove` is the sharp one: today it runs 4 tests in ~0.2 s. Task 3 measures every alias before and after and records the numbers, so a reviewer can judge whether the widening is acceptable rather than discover it later. If it is not, the fallback is to give the widened aliases explicit file lists again — say so rather than silently narrowing a marker.

## File Structure

| file | responsibility |
|---|---|
| `pyproject.toml` | the marker vocabulary and `--strict-markers` — the single source of truth for which markers exist |
| `tests/test_test_groups.py` | new: the `ast` marker parser and the three enforcement properties |
| `tests/test_*.py` (72) | one `pytestmark` line each; no other change |
| `Makefile` | `HEADLESS`; six `test-*` targets; four `proof-*` targets; nine `prove-*` aliases |
| `AGENTS.md`, `CONTEXT.md` | the marker rule, the tie-break, and where the enforcement lives |

---

### Task 1: Marker vocabulary and the AST parser

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/test_test_groups.py`

**Interfaces:**
- Produces, in `tests/test_test_groups.py`:
  - `SUBJECTS = ("engine", "render", "shell", "tools", "meta")`
  - `CROSS = ("journey",)`
  - `TESTS_DIR = pathlib.Path(__file__).parent`
  - `NON_TEST = {"conftest.py", "purity.py", "stub_floor.py", "__init__.py"}`
  - `all_test_files() -> list[pathlib.Path]` — every `tests/test_*.py`, sorted, excluding `NON_TEST`
  - `markers_of(path) -> set[str]` — marker names from a module-level `pytestmark`, parsed with `ast`, without importing the module
  - `registered_markers() -> set[str]` — marker names parsed out of `pyproject.toml`'s `markers` list

This task does NOT assert that files carry markers — that is Task 2, after the markers exist. Ending this task with the suite green is the point.

- [ ] **Step 1: Write the failing test**

Create `tests/test_test_groups.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""The test suite's own grouping rules: every test file declares exactly one
subject marker, the vocabulary matches pyproject.toml, and every legacy
prove-* alias still covers what it historically ran.

Markers are read with `ast`, never by importing the module: importing every
test file here would double the suite's import cost and could execute
module-level fixtures."""
import ast
import pathlib
import re

import pytest

pytestmark = pytest.mark.meta

SUBJECTS = ("engine", "render", "shell", "tools", "meta")
CROSS = ("journey",)
TESTS_DIR = pathlib.Path(__file__).parent
REPO_ROOT = TESTS_DIR.parent
NON_TEST = {"conftest.py", "purity.py", "stub_floor.py", "__init__.py"}


def all_test_files():
    return sorted(p for p in TESTS_DIR.glob("test_*.py") if p.name not in NON_TEST)


def markers_of(path):
    """Marker names from a module-level `pytestmark`, without importing."""
    tree = ast.parse(pathlib.Path(path).read_text())
    found = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets):
            continue
        values = node.value.elts if isinstance(node.value, (ast.List, ast.Tuple)) else [node.value]
        for value in values:
            # pytest.mark.NAME
            if (isinstance(value, ast.Attribute)
                    and isinstance(value.value, ast.Attribute)
                    and value.value.attr == "mark"):
                found.add(value.attr)
    return found


def registered_markers():
    text = (REPO_ROOT / "pyproject.toml").read_text()
    block = re.search(r"^markers = \[(.*?)^\]", text, re.S | re.M)
    assert block, "pyproject.toml has no [tool.pytest.ini_options] markers list"
    return {m.group(1) for m in re.finditer(r'"(\w+):', block.group(1))}


def test_marker_parser_reads_single_and_list_forms(tmp_path):
    single = tmp_path / "test_single.py"
    single.write_text("import pytest\npytestmark = pytest.mark.engine\n")
    assert markers_of(single) == {"engine"}

    listed = tmp_path / "test_listed.py"
    listed.write_text("import pytest\npytestmark = [pytest.mark.shell, pytest.mark.journey]\n")
    assert markers_of(listed) == {"shell", "journey"}

    bare = tmp_path / "test_bare.py"
    bare.write_text("def test_x():\n    pass\n")
    assert markers_of(bare) == set()


def test_marker_parser_ignores_function_level_marks(tmp_path):
    path = tmp_path / "test_fn.py"
    path.write_text(
        "import pytest\n\n"
        "@pytest.mark.engine\n"
        "def test_x():\n    pass\n"
    )
    assert markers_of(path) == set(), "only module-level pytestmark counts as the file's group"


def test_registered_vocabulary_is_exactly_the_declared_one():
    assert registered_markers() == set(SUBJECTS) | set(CROSS)
```

- [ ] **Step 2: Run to verify it fails**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_test_groups.py -q`
Expected: FAIL — `test_registered_vocabulary_is_exactly_the_declared_one` raises the "no markers list" assertion, because `pyproject.toml` has none yet.

- [ ] **Step 3: Register the vocabulary**

In `pyproject.toml`, replace the `[tool.pytest.ini_options]` block with:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--strict-markers"
markers = [
    "engine: simulation, LIFE VM, formats, actors, animation, tracks, collision, navmesh, picking, AITD1 opcode handlers",
    "render: FrameDescription to pixels: scene, geometry, both backends, asset resolution, override export and check",
    "shell: app/: window, event pump, settings schema and persistence, CLI, UI screens and modals",
    "tools: standalone scripts under tools/",
    "meta: the repo's own rules rather than its behaviour",
    "journey: drives the real run() event pump or a long real-data simulation",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_test_groups.py -q`
Expected: PASS, 4 tests.

Then the full suite, which must be unaffected — `--strict-markers` only rejects *unregistered* markers, and the suite currently uses none:

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q`
Expected: PASS. **Record the exact passed/skipped/xfailed counts in your report — every later task compares against them.**

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/test_test_groups.py
git commit -m "test: marker vocabulary, strict markers, and the AST marker parser"
```

---

### Task 2: Mark all 72 test files and enforce the partition

**Files:**
- Modify: every `tests/test_*.py` (72 files), one line each
- Modify: `tests/test_test_groups.py` (add two enforcement tests)

**Interfaces:**
- Consumes: `markers_of`, `all_test_files`, `SUBJECTS`, `CROSS` from Task 1.
- Produces: every test module carries a module-level `pytestmark`, so `-m engine` and friends select correctly for Task 3.

**The assignment.** Insert `pytestmark = pytest.mark.<subject>` (or a list, where a `journey` marker also applies) at module level, after the imports. Add `import pytest` only if the file does not already import it. Use exactly this table — it is the judgment pass the spec calls the main cost of this work, already made:

**`engine` (46):** `test_actor_contacts`, `test_actors`, `test_anim_action`, `test_anim_player`, `test_assets`, `test_assets_life`, `test_body_anim`, `test_camera_switch`, `test_combat_journey`, `test_cos_table`, `test_effects`, `test_eval_var`, `test_explode`, `test_floor`, `test_floor_start`, `test_formats`, `test_game`, `test_game_over`, `test_game_profile`, `test_gere_dec`, `test_image`, `test_interaction`, `test_intro`, `test_life_continuation`, `test_life_interaction_ops`, `test_life_ops`, `test_life_vm`, `test_m3b_attic`, `test_mask`, `test_mask_geometry`, `test_messages`, `test_modal_results`, `test_navigate`, `test_navmesh`, `test_pak`, `test_pick_venue`, `test_picking`, `test_playworld`, `test_prove_m3a`, `test_realvalue`, `test_scenario`, `test_skel`, `test_text_assets`, `test_tracks`, `test_world`, `test_world_data`

**`render` (9):** `test_asset_resolver`, `test_background_export`, `test_geometry`, `test_override_check`, `test_render`, `test_render_gl`, `test_render_options`, `test_render_soft`, `test_scene`

**`shell` (11):** `test_config`, `test_main`, `test_mouse_only`, `test_play_loop`, `test_runtime_modes`, `test_shell_journeys`, `test_startup`, `test_ui_input`, `test_ui_mouse`, `test_ui_reducers`, `test_ui_render`

**`tools` (5):** `test_export_screens`, `test_prove_graphics`, `test_prove_intro`, `test_regenerate_backgrounds`, `test_tools_graphics_cli`

**`meta` (2):** `test_layering`, `test_test_groups` (already marked in Task 1)

**`journey`, additional to the subject above (7):** `test_combat_journey`, `test_intro`, `test_m3b_attic`, `test_mouse_only`, `test_play_loop`, `test_prove_m3a`, `test_shell_journeys`

So for example `tests/test_mouse_only.py` gets:

```python
pytestmark = [pytest.mark.shell, pytest.mark.journey]
```

and `tests/test_actors.py` gets:

```python
pytestmark = pytest.mark.engine
```

Notes on the four assignments most likely to be questioned, so a reviewer can check the reasoning rather than the import list:
- `test_picking`, `test_playworld`, `test_modal_results` import from `app/` but assert engine behaviour (picking geometry, the playworld tick, `interaction.apply_*_result`) — `engine` by the tie-break rule.
- `test_play_loop` also spans both, but its 57 tests assert the shell's event loop and input routing — `shell`.
- `test_geometry` and `test_scene` import heavily from `engine` but exercise `render/geometry.py` and `render/scene.py` — `render`.
- `test_prove_m3a`, `test_intro`, `test_m3b_attic` and `test_combat_journey` are `engine` journeys: they drive long real-data simulations and assert world state, not routing.

- [ ] **Step 1: Write the failing enforcement tests**

Append to `tests/test_test_groups.py`:

```python
def test_every_test_file_declares_exactly_one_subject():
    missing, multiple = [], []
    for path in all_test_files():
        subjects = markers_of(path) & set(SUBJECTS)
        if not subjects:
            missing.append(path.name)
        elif len(subjects) > 1:
            multiple.append((path.name, sorted(subjects)))
    assert not missing, f"no subject marker: {missing}"
    assert not multiple, f"more than one subject marker: {multiple}"


def test_subjects_partition_the_suite_and_only_known_markers_are_used():
    by_subject = {s: set() for s in SUBJECTS}
    for path in all_test_files():
        used = markers_of(path)
        unknown = used - set(SUBJECTS) - set(CROSS)
        assert not unknown, f"{path.name} uses unregistered marker(s) {sorted(unknown)}"
        for subject in used & set(SUBJECTS):
            by_subject[subject].add(path.name)
    union = set().union(*by_subject.values())
    assert union == {p.name for p in all_test_files()}, "subjects do not cover every file"
    for a in SUBJECTS:
        for b in SUBJECTS:
            if a < b:
                assert not (by_subject[a] & by_subject[b]), f"{a} and {b} overlap"
```

- [ ] **Step 2: Run to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_test_groups.py -q`
Expected: FAIL — `test_every_test_file_declares_exactly_one_subject` lists ~71 files under "no subject marker".

- [ ] **Step 3: Apply the markers**

Work through the table above. For each file: if it does not already `import pytest`, add that import with the others; then add the `pytestmark` line after the import block and before the first definition. Change nothing else — no reordering, no reformatting.

- [ ] **Step 4: Run tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_test_groups.py -q`
Expected: PASS, 6 tests.

Then confirm the marker pass changed no outcome:

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q`
Expected: the same passed/skipped/xfailed counts you recorded in Task 1, plus the 6 new tests in `test_test_groups.py`. **If any pre-existing test's outcome changed, stop and report — the marker pass is supposed to be inert.**

Then check each group selects a non-empty, plausible set:

Run: `for m in engine render shell tools meta journey; do echo -n "$m "; SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -m $m --collect-only -q 2>/dev/null | tail -1; done`
Expected: engine 46 files, render 9, shell 11, tools 5, meta 2, journey 7 — matching the table.

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: declare a subject marker on every test file; enforce the partition"
```

---

### Task 3: Makefile targets, proof renames, and aliases

**Files:**
- Modify: `Makefile:14` (`.PHONY`), `Makefile:50-93` (the `test`/`prove-*` block)

**Interfaces:**
- Consumes: the markers from Task 2.
- Produces: `test`, `test-engine`, `test-render`, `test-shell`, `test-tools`, `test-meta`, `test-journey`; `proof-mouse`, `proof-combat`, `proof-graphics`, `proof-intro`; and nine `prove-*` aliases. Task 4's pinning test parses this file, so the `-m "..."` expressions must be written exactly as shown.

- [ ] **Step 1: Record the baseline**

Before editing, measure what each target runs today, so the widening is documented rather than assumed:

```bash
for t in prove prove-m3b prove-shell prove-mouse-only prove-mouse-accessibility; do
  echo "== $t"; /usr/bin/time -p make $t 2>&1 | tail -4
done
```

Put the numbers in your report.

- [ ] **Step 2: Add the HEADLESS variable**

In `Makefile`, after the `overrides ?= ...` line:

```make
# Every pytest target runs headless: AGENTS.md requires SDL_VIDEODRIVER=dummy
# for any test touching rendering or pygame, and SDL_AUDIODRIVER=dummy keeps
# the mixer from opening a device on machines that have one.
HEADLESS = SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy
```

- [ ] **Step 3: Replace the test/prove block**

Replace everything from `test: install` through the `prove-intro` recipe with:

```make
test: install ## Run the whole pytest suite, headless
	$(HEADLESS) $(PYTHON) -m pytest tests/ -q

test-engine: install ## Engine group: simulation, LIFE VM, formats, actors, anim, tracks, collision, navmesh, picking, opcodes
	$(HEADLESS) $(PYTHON) -m pytest -m engine -q

test-render: install ## Render group: scene, geometry, both backends, asset resolution, override export and check
	$(HEADLESS) $(PYTHON) -m pytest -m render -q

test-shell: install ## Shell group: event pump, settings, CLI, UI screens and modals
	$(HEADLESS) $(PYTHON) -m pytest -m shell -q

test-tools: install ## Tools group: the standalone scripts under tools/
	$(HEADLESS) $(PYTHON) -m pytest -m tools -q

test-meta: install ## Meta group: the repo's own rules (package layering, test grouping)
	$(HEADLESS) $(PYTHON) -m pytest -m meta -q

test-journey: install ## Journey group: real run() event pump and long real-data simulations
	$(HEADLESS) $(PYTHON) -m pytest -m journey -q

# ── Artifact proofs (need GL and real game data) ─────────────────────────────

proof-mouse: install ## Navmesh proof: build it for every camera-visible room, every floor (data="path/to/INDARK")
	$(PYTHON) tools/prove_mouse.py "$(data)"

proof-combat: install ## Combat proof: venue, real enemy damage, player arms, game over
	$(PYTHON) tools/prove_combat.py "$(data)"

proof-graphics: install ## Graphics proof: attic + combat fixtures at scale 4 per shading mode to docs/graphics-proof/
	$(PYTHON) tools/prove_graphics.py "$(data)"

proof-intro: install ## Opening cutscene proof: headless run to CutsceneFinished + one GL render per visited camera to docs/intro-proof/
	$(HEADLESS) $(PYTHON) -m pytest tests/test_intro.py -q && $(PYTHON) tools/prove_intro.py "$(data)"

# ── Legacy milestone gate names, kept so the proof docs keep working ─────────
# Each alias runs a superset of the files it historically ran; the superset
# property is pinned by tests/test_test_groups.py.

prove: test-engine ## Alias of test-engine (was the M3a proof)

prove-m3b: install ## Alias (was the M3b interaction proof)
	$(HEADLESS) $(PYTHON) -m pytest -m "engine or shell" -q

prove-shell: install ## Alias (was the M4a1 shell proof)
	$(HEADLESS) $(PYTHON) -m pytest -m "engine or shell" -q

prove-mouse-only: test-shell ## Alias of test-shell (was the M3e one-button proof)

prove-mouse-accessibility: test-shell ## Alias of test-shell (was the mouse accessibility proof)

prove-mouse: proof-mouse ## Alias of proof-mouse

prove-combat: proof-combat ## Alias of proof-combat

prove-graphics: proof-graphics ## Alias of proof-graphics

prove-intro: proof-intro ## Alias of proof-intro
```

Update `.PHONY` on line 14 to:

```make
.PHONY: help install run run-combat run-mouse-combat test test-engine test-render test-shell test-tools test-meta test-journey proof-mouse proof-combat proof-graphics proof-intro prove prove-m3b prove-shell prove-mouse prove-mouse-only prove-mouse-accessibility prove-combat prove-graphics prove-intro export-backgrounds check-overrides regenerate-backgrounds clean
```

- [ ] **Step 4: Verify every target runs**

```bash
for t in test-engine test-render test-shell test-tools test-meta test-journey; do echo "== $t"; make $t 2>&1 | tail -2; done
for t in prove prove-m3b prove-shell prove-mouse-only prove-mouse-accessibility; do echo "== $t"; make $t 2>&1 | tail -2; done
make proof-intro 2>&1 | tail -3
make help | head -30
```

Expected: every pytest target exits 0; `make help` lists the new targets with their descriptions. Record each target's runtime and compare against the Step 1 baseline — the widening table in this plan predicts `prove` goes from ~0.2 s to roughly the `test-engine` time. **If any alias is now slower than about 60 s, say so in your report; that is the threshold at which the fallback (explicit file lists for the widened aliases) becomes worth raising.**

`make proof-mouse`, `proof-combat` and `proof-graphics` need real game data and GL; run them if this machine has both, and say which you skipped and why if not.

- [ ] **Step 5: Commit**

```bash
git add Makefile
git commit -m "build: marker-driven test-* groups, proof-* artifact targets, prove-* aliases"
```

---

### Task 4: Pin each legacy alias to its historical coverage

**Files:**
- Modify: `tests/test_test_groups.py`

**Interfaces:**
- Consumes: `markers_of`, `all_test_files`, `REPO_ROOT` from Task 1; the Makefile written in Task 3.
- Produces: nothing later tasks depend on. This is the safety net that keeps the eight proof documents' cited gates meaningful.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_test_groups.py`:

```python
# The file list each legacy gate ran before markers replaced its recipe,
# captured from the Makefile at commit 4024b10. THIS DATA IS HISTORICAL.
# If a test below fails, a file's marker is wrong, or a gate's marker
# expression no longer covers what a proof document says it proves --
# fix the marker or the expression. Never edit this table to make a
# failure go away: that silently invalidates the proof docs' evidence.
LEGACY_GATE_FILES = {
    "prove": ["test_prove_m3a"],
    "prove-m3b": [
        "test_life_continuation", "test_interaction", "test_actor_contacts",
        "test_gere_dec", "test_life_interaction_ops", "test_runtime_modes",
        "test_m3b_attic",
    ],
    "prove-shell": [
        "test_config", "test_assets", "test_effects", "test_ui_input",
        "test_ui_reducers", "test_ui_mouse", "test_ui_render",
        "test_runtime_modes", "test_main", "test_mouse_only",
        "test_startup", "test_shell_journeys",
    ],
    "prove-mouse-only": ["test_mouse_only"],
    "prove-mouse-accessibility": [
        "test_ui_input", "test_ui_reducers", "test_ui_mouse", "test_ui_render",
        "test_play_loop", "test_runtime_modes", "test_main", "test_mouse_only",
        "test_shell_journeys",
    ],
}


def _makefile():
    return (REPO_ROOT / "Makefile").read_text()


def _target_block(text, target):
    """The dependency line and recipe of one Make target."""
    match = re.search(rf"^{re.escape(target)}:([^\n]*)\n((?:\t[^\n]*\n)*)", text, re.M)
    assert match, f"Makefile has no target {target}"
    return match.group(1), match.group(2)


def marker_expression(target, _seen=None):
    """The `-m EXPR` a target runs, following one level of alias dependency."""
    _seen = _seen or set()
    assert target not in _seen, f"alias cycle at {target}"
    _seen.add(target)
    deps, recipe = _target_block(_makefile(), target)
    # Anchor on `pytest -m`, not a bare `-m`: the recipe also contains
    # `$(PYTHON) -m pytest`, whose `-m` would otherwise match first.
    found = re.search(r'pytest\s+-m\s+"([^"]+)"|pytest\s+-m\s+(\w+)\b', recipe)
    if found:
        return found.group(1) or found.group(2)
    for dep in deps.split():
        if dep.startswith(("test-", "proof-", "prove")):
            return marker_expression(dep, _seen)
    raise AssertionError(f"{target} runs no -m expression and delegates to nothing")


def selects(expression, markers):
    """Evaluate an or-joined marker expression against a file's markers."""
    parts = [p.strip() for p in expression.split(" or ")]
    assert all(re.fullmatch(r"\w+", p) for p in parts), (
        f"expression {expression!r} is not or-joined single markers; the "
        "spec restricts alias expressions so this evaluator stays honest"
    )
    return any(part in markers for part in parts)


@pytest.mark.parametrize("gate", sorted(LEGACY_GATE_FILES))
def test_legacy_gate_still_covers_every_file_it_historically_ran(gate):
    expression = marker_expression(gate)
    by_name = {p.stem: markers_of(p) for p in all_test_files()}
    uncovered = [
        name for name in LEGACY_GATE_FILES[gate]
        if not selects(expression, by_name.get(name, set()))
    ]
    assert not uncovered, (
        f"`make {gate}` now runs `-m {expression}`, which no longer covers "
        f"{uncovered} -- a proof document cites this gate as evidence for them"
    )


def test_every_legacy_gate_name_still_exists_in_the_makefile():
    text = _makefile()
    for gate in ("prove", "prove-m3b", "prove-shell", "prove-mouse-only",
                 "prove-mouse-accessibility", "prove-mouse", "prove-combat",
                 "prove-graphics", "prove-intro"):
        assert re.search(rf"^{re.escape(gate)}:", text, re.M), f"missing alias {gate}"
```

- [ ] **Step 2: Run to verify it passes, and prove it can fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_test_groups.py -q`
Expected: PASS, 12 tests (6 from before, 5 parametrized gates, 1 alias-existence).

The test must be shown to have teeth. Temporarily change `tests/test_config.py`'s marker from `shell` to `render`, re-run, and confirm `test_legacy_gate_still_covers_every_file_it_historically_ran[prove-shell]` fails naming `test_config`. Then revert. Put both outputs in your report.

- [ ] **Step 3: Run the full suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q`
Expected: the Task 1 baseline plus 12 tests in `test_test_groups.py`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_test_groups.py
git commit -m "test: pin each legacy prove-* alias to the files it historically ran"
```

---

### Task 5: Documentation

**Files:**
- Modify: `AGENTS.md` (the Commands block and the testing conventions below it)
- Modify: `CONTEXT.md`

**Interfaces:**
- Consumes: everything above. Nothing depends on this task.

- [ ] **Step 1: Update the AGENTS.md commands block**

Replace the `make test` / `make prove*` lines in the ```bash block with:

```bash
make test          # the whole suite, headless — the gate
make test-engine   # simulation, LIFE VM, formats, actors, anim, collision, navmesh, opcodes
make test-render   # scene, geometry, both backends, asset resolution, override export/check
make test-shell    # event pump, settings, CLI, UI screens and modals
make test-tools    # the standalone scripts under tools/
make test-meta     # the repo's own rules (package layering, test grouping)
make test-journey  # real run() event pump and long real-data simulations
make proof-mouse   # navmesh for every camera-visible room, every floor (needs game data)
make proof-combat  # venue, real enemy damage, player arms, game over (needs game data)
make proof-graphics # attic + combat fixtures per shading mode (needs GL + game data)
make proof-intro   # opening cutscene: headless gate + one GL render per visited camera
```

Keep the existing `make run*`, `make export-backgrounds`, `make check-overrides` and `make regenerate-backgrounds` lines unchanged.

- [ ] **Step 2: State the marker rule in AGENTS.md**

Replace the paragraph beginning "Any test touching rendering/pygame needs `SDL_VIDEODRIVER=dummy`" with:

```markdown
Every pytest target runs headless via the Makefile's `HEADLESS` variable, so
`SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy` is set for `make test` and every
`test-*` group. Running pytest directly still needs them on the command line.

Every file under `tests/` declares exactly one subject marker as a module-level
`pytestmark` — `engine`, `render`, `shell`, `tools` or `meta` — plus an optional
`journey` when it drives the real `run()` loop or a long real-data simulation.
Mark by the layer whose behaviour the test asserts, not by what it imports: a
test that drives `run()` and asserts routing is `shell`, one that asserts world
state is `engine`. `tests/test_test_groups.py` enforces this and fails if a new
file carries no marker. The nine legacy `prove-*` names are aliases of the new
targets; that same test pins each one to the files it historically ran, so the
proof documents under `docs/` keep citing meaningful gates.

After non-trivial changes run `.venv/bin/pytest -q && make prove`. No lint,
formatter, or typecheck is configured — LSP/pyright diagnostics are noise, the
test suite is the only gate. Never mass-reformat.
```

- [ ] **Step 3: Add the CONTEXT.md section**

Add, after the package-layout table:

```markdown
## Test grouping

`tests/` is partitioned by one module-level subject marker per file — `engine`,
`render`, `shell`, `tools`, `meta` — with an optional cross-cutting `journey`.
The Makefile's `test-*` targets are `pytest -m <marker>`; the vocabulary lives
in `pyproject.toml` and `--strict-markers` rejects anything else.

`tests/test_test_groups.py` owns three properties: the subjects cover every
test file and never overlap, the vocabulary matches `pyproject.toml`, and every
legacy `prove-*` alias still selects each file it ran before markers replaced
its recipe. That last one is why the proof documents can keep citing
`make prove-shell` and friends without being rewritten. Its `LEGACY_GATE_FILES`
table is historical data captured at `4024b10` — fix a marker when it fails,
never the table.

Markers are parsed with `ast`, never by importing the modules, so the
enforcement costs one file read per test file and cannot trigger a module-level
fixture.
```

- [ ] **Step 4: Verify the docs match the code**

Run: `make help` and confirm every target named in `AGENTS.md` appears with a matching description; confirm the marker list in `AGENTS.md` matches `pyproject.toml`'s.

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q && make prove && make test-shell && make test-engine`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add AGENTS.md CONTEXT.md
git commit -m "docs: test group markers, the test-*/proof-* targets, and the alias pinning"
```
