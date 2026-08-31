# SPDX-License-Identifier: GPL-2.0-only
"""Package rules from docs/superpowers/specs/2026-08-26-engine-package-reorganization-design.md.

engine/  imports no pygame, moderngl, render, games, app
render/  imports engine only (never games or app); only GRAPHICS_OWNERS touch pygame/moderngl
games/   imports engine only
app/     may import everything
"""
import ast
import functools
import pathlib

import pytest

from tests.purity import PRESENTATION, assert_presentation_free

pytestmark = pytest.mark.meta

ROOT = pathlib.Path(__file__).resolve().parents[1] / "PyAitD"

FORBIDDEN = {
    "engine": PRESENTATION + ("PyAitD.games",),
    # Leaf-domain pins (2026-08-31-engine-domain-subpackages-design.md):
    # data is fully closed; space may reach data and nothing else. actor,
    # script and nav carry pre-existing cycles and get no stricter pin.
    "engine/data": PRESENTATION + (
        "PyAitD.games",
        "PyAitD.engine.space", "PyAitD.engine.actor",
        "PyAitD.engine.script", "PyAitD.engine.nav",
    ),
    "engine/space": PRESENTATION + (
        "PyAitD.games",
        "PyAitD.engine.actor", "PyAitD.engine.script", "PyAitD.engine.nav",
    ),
    "render": ("PyAitD.games", "PyAitD.app"),
    "games": ("pygame", "moderngl", "PyAitD.render", "PyAitD.app"),
}
# The only render modules allowed to import a graphics library, and which one.
# Every other module under render/ is pure by construction -- a new
# render/lighting.py that imports pygame fails without being listed anywhere.
GRAPHICS_OWNERS = {
    "render_gl": ("pygame", "moderngl"),
    "render_soft": ("pygame",),
    "render": ("pygame", "moderngl"),
    "asset_resolver": ("pygame",),   # in exactly one function, pinned below
}


def _names(node):
    """Dotted names an import node brings in. Relative imports are rejected
    outright: every import in PyAitD is absolute, and that is what lets the
    PyAitD.-prefixed FORBIDDEN entries match by prefix."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    assert not node.level, f"relative import at line {node.lineno}"
    return [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]


@functools.lru_cache(maxsize=None)
def _imports(path):
    """Every dotted name imported anywhere in the module, deferred imports included."""
    tree = ast.parse(path.read_text())
    return tuple(
        name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for name in _names(node)
    )


def _modules(package):
    return sorted((ROOT / package).rglob("*.py"))


@pytest.mark.parametrize("package", sorted(FORBIDDEN))
def test_package_imports_only_what_the_layering_allows(package):
    paths = _modules(package)
    assert paths, f"no modules found under PyAitD/{package} — did the package move?"
    bad = []
    for path in paths:
        for name in _imports(path):
            if name.startswith(FORBIDDEN[package]):
                bad.append(f"{path.relative_to(ROOT)}: {name}")
    assert not bad, "\n".join(bad)


def _graphics_imports(path):
    return {n for n in _imports(path) if n.startswith(("pygame", "moderngl"))}


def test_pure_render_modules_import_no_graphics_library():
    bad = {
        path.name: names
        for path in _modules("render")
        if path.stem not in GRAPHICS_OWNERS and path.name != "__init__.py"
        for names in [_graphics_imports(path)]
        if names
    }
    assert not bad, bad


@pytest.mark.parametrize("module", sorted(GRAPHICS_OWNERS))
def test_software_side_never_imports_moderngl(module):
    # each owner touches only the library it is declared for
    names = _graphics_imports(ROOT / "render" / f"{module}.py")
    assert all(n.startswith(GRAPHICS_OWNERS[module]) for n in names), names


def test_asset_resolver_touches_pygame_in_exactly_one_function():
    tree = ast.parse((ROOT / "render" / "asset_resolver.py").read_text())

    def imports_pygame(node):
        return isinstance(node, (ast.Import, ast.ImportFrom)) and any(
            n.startswith("pygame") for n in _names(node)
        )

    owners = {
        func.name
        for func in ast.walk(tree) if isinstance(func, ast.FunctionDef)
        if any(imports_pygame(node) for node in ast.walk(func))
    }
    assert not any(imports_pygame(n) for n in tree.body), "pygame must not be imported at module scope"
    assert owners == {"load_png_rgb"}, owners


def test_no_module_may_import_an_ai_sdk():
    # The AI-service boundary: no module may import an AI SDK. Gemini is
    # reached through the `agy` CLI (subprocess), so this set is empty
    # today; the assertion pins the boundary, not the current mechanism.
    tools = pathlib.Path(__file__).resolve().parents[1] / "tools"
    hits = {
        p.name for p in list(tools.glob("*.py")) + _modules("")
        if any(n.startswith("google") for n in _imports(p))
    }
    assert not hits, hits


def test_only_the_material_bootstrap_may_shell_out_to_the_agy_cli():
    # The other half of the AI-service boundary AGENTS.md states: reaching
    # Gemini through the `agy` CLI is bootstrap_materials' agy_structured
    # alone. Naming the binary in a prompt or a help string is not shelling
    # out, so this looks for it as an argv element -- the first item of a
    # list passed to subprocess.
    tools = pathlib.Path(__file__).resolve().parents[1] / "tools"
    hits = set()
    for path in list(tools.glob("*.py")) + _modules(""):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.List) and node.elts:
                head = node.elts[0]
                if isinstance(head, ast.Constant) and head.value == "agy":
                    hits.add(path.name)
    assert hits <= {"bootstrap_materials.py"}, hits


def test_every_python_file_starts_with_the_spdx_line():
    repo = ROOT.parent
    missing = [
        str(p.relative_to(repo))
        for d in ("PyAitD", "tests", "tools")
        for p in (repo / d).rglob("*.py")
        if p.open().readline().rstrip("\n") != "# SPDX-License-Identifier: GPL-2.0-only"
    ]
    assert not missing, missing


# The runtime twin of the static import scan above: a module can pass the ast
# check and still drag the presentation layer in through a transitive import,
# so each of these is imported in a fresh interpreter. Folded here from six
# separate test files so the package rules live in one place
# (2026-08-26-engine-package-reorganization-design.md:110-113). Rows are the
# modules whose headless importability is load-bearing, each with its reason.
PRESENTATION_FREE = (
    ("PyAitD.engine.nav.navigate", PRESENTATION, ""),
    ("PyAitD.engine.nav.navmesh", PRESENTATION,
     " — the mesh must stay importable without the presentation layer so it can build headless"),
    ("PyAitD.engine.nav.picking", PRESENTATION,
     " — picking is pure math and must not need a window; the shell passes it logical coordinates"),
    ("PyAitD.engine.script.playworld,PyAitD.engine.actor.anim_action", PRESENTATION,
     " — the tick must stay importable without the presentation layer so it can run headless"),
    ("PyAitD.games.aitd1.mouse_contract", PRESENTATION, ""),
    # app/config is allowed the rest of the presentation layer; it must only
    # stay free of pygame so settings can be read and written headless.
    ("PyAitD.app.config", ("pygame",), ""),
)


@pytest.mark.parametrize(
    "modules, forbidden, why", PRESENTATION_FREE,
    ids=[row[0].replace(",", " + ") for row in PRESENTATION_FREE],
)
def test_module_imports_stay_presentation_free(modules, forbidden, why):
    assert_presentation_free(*modules.split(","), forbidden=forbidden, why=why)


def test_no_module_locks_grabs_or_warps_the_pointer():
    # Held pointer follow tracks a free OS cursor: the spec forbids relative
    # mode and grab (2026-08-26-held-pointer-follow-design.md, Non-goals);
    # warping the pointer would be the same control by another name.
    forbidden = ("set_relative_mode", "set_grab", "mouse.set_pos")
    paths = list(ROOT.rglob("*.py"))
    assert paths, "no modules found under PyAitD — did the package move?"
    hits = sorted(
        (str(path.relative_to(ROOT.parent)), name)
        for path in paths
        for name in forbidden
        if name in path.read_text()
    )
    assert hits == []


def test_glsl_is_strings_only():
    """render/glsl.py holds GLSL sources and nothing else -- no imports, no
    functions, no logic -- so it can never become a second graphics owner
    and a shader edit never hides a Python change."""
    tree = ast.parse((ROOT / "render" / "glsl.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Expr):        # the module docstring
            assert isinstance(node.value, ast.Constant) and isinstance(node.value.value, str), node.lineno
            continue
        assert isinstance(node, ast.Assign), f"line {node.lineno}: {type(node).__name__}"
        assert isinstance(node.value, ast.Constant) and isinstance(node.value.value, str), f"line {node.lineno}: not a string"
        assert all(isinstance(t, ast.Name) and t.id == t.id.upper() for t in node.targets), f"line {node.lineno}"
