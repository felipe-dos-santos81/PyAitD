# SPDX-License-Identifier: GPL-2.0-only
"""Runtime twin of tests/test_layering.py: import a module in a fresh
interpreter and assert nothing from the presentation layer landed in
sys.modules. Out-of-process because pytest itself has pygame loaded."""
import subprocess
import sys

# What the simulation side must stay importable without. test_layering.py's
# FORBIDDEN["engine"] is this plus PyAitD.games.
PRESENTATION = ("pygame", "moderngl", "OpenGL", "PyAitD.render", "PyAitD.app")

_PROBE = """
import sys
for m in {modules!r}:
    __import__(m)
leaked = sorted(m for m in sys.modules if m.startswith({forbidden!r}))
sys.exit(", ".join(leaked) or None)
"""


def assert_presentation_free(*modules, forbidden=PRESENTATION, why=""):
    probe = _PROBE.format(modules=list(modules), forbidden=tuple(forbidden))
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert out.returncode == 0, f"{', '.join(modules)} pulled in {out.stderr.strip()}{why}"
