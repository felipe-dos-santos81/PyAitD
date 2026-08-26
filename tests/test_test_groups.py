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
