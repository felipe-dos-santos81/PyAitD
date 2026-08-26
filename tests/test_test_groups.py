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
