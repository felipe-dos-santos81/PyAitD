# SPDX-License-Identifier: GPL-2.0-only
"""Package rules from docs/superpowers/specs/2026-08-26-engine-package-reorganization-design.md.

engine/  imports no pygame, moderngl, render, games, app
render/  imports engine only (never games or app); its pure modules import neither pygame nor moderngl
games/   imports engine only
app/     may import everything
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1] / "PyAitD"

FORBIDDEN = {
    "engine": ("pygame", "moderngl", "PyAitD.render", "PyAitD.games", "PyAitD.app"),
    "render": ("PyAitD.games", "PyAitD.app"),
    "games": ("pygame", "moderngl", "PyAitD.render", "PyAitD.app"),
    "app": (),
}
# render modules that must stay free of both graphics libraries
PURE_RENDER = ("scene", "geometry", "render_options", "background_export", "override_check")
NO_MODERNGL = ("render_soft", "asset_resolver")


def _package_of(path):
    """The dotted PyAitD.<...> package that directly contains this module —
    i.e. its __package__ at runtime, whether the file is a regular module
    or an __init__.py. Used to resolve relative imports below without
    actually importing anything."""
    return ".".join(path.relative_to(ROOT.parent).with_suffix("").parts[:-1])


def _imports(path):
    """Every dotted name imported anywhere in the module, deferred imports included."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # A relative import (`from .foo import bar` / `from ..foo
                # import bar`) carries no dotted absolute name in
                # node.module -- left alone, "render" (say) matches none of
                # the PyAitD.-prefixed FORBIDDEN entries and a future
                # cross-layer `from ..render import scene` inside engine/
                # would slip past every rule below. Resolve it to its real
                # absolute name the same way Python resolves it at import
                # time (package.rsplit(".", level - 1)[0]), so it is
                # checked exactly like an equivalent absolute import.
                bits = _package_of(path).rsplit(".", node.level - 1)
                base = bits[0] + (f".{node.module}" if node.module else "")
            else:
                base = node.module
            if not base:
                continue
            yield base
            for alias in node.names:
                yield f"{base}.{alias.name}"


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


@pytest.mark.parametrize("module", PURE_RENDER)
def test_pure_render_modules_import_no_graphics_library(module):
    names = set(_imports(ROOT / "render" / f"{module}.py"))
    assert not any(n.startswith(("pygame", "moderngl")) for n in names), names


@pytest.mark.parametrize("module", NO_MODERNGL)
def test_software_side_never_imports_moderngl(module):
    names = set(_imports(ROOT / "render" / f"{module}.py"))
    assert not any(n.startswith("moderngl") for n in names), names


def test_asset_resolver_touches_pygame_in_exactly_one_function():
    tree = ast.parse((ROOT / "render" / "asset_resolver.py").read_text())
    owners = set()
    for func in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        for node in ast.walk(func):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
                if any(m and m.startswith("pygame") for m in mods):
                    owners.add(func.name)
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not any(
        (isinstance(n, ast.Import) and any(a.name.startswith("pygame") for a in n.names))
        or (isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("pygame"))
        for n in top
    ), "pygame must not be imported at module scope"
    assert owners == {"load_png_rgb"}, owners


def test_only_the_regeneration_tool_may_import_an_ai_sdk():
    # The AI-service boundary: no module but the regeneration tool may import an AI SDK.
    # It currently reaches Gemini through the `agy` CLI (subprocess), so this set is empty
    # today; the assertion is a subset so it pins the boundary, not the current mechanism.
    tools = pathlib.Path(__file__).resolve().parents[1] / "tools"
    hits = {
        p.name for p in list(tools.glob("*.py")) + list(ROOT.rglob("*.py"))
        if any(n.startswith("google") for n in _imports(p))
    }
    assert hits <= {"regenerate_backgrounds.py"}, hits


def test_every_python_file_starts_with_the_spdx_line():
    repo = ROOT.parent
    missing = [
        str(p.relative_to(repo))
        for d in ("PyAitD", "tests", "tools")
        for p in (repo / d).rglob("*.py")
        if p.read_text().splitlines()[:1] != ["# SPDX-License-Identifier: GPL-2.0-only"]
    ]
    assert not missing, missing
