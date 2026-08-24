# SPDX-License-Identifier: GPL-2.0-only
import subprocess
import sys

from PyAitD.effects import GameMode
from PyAitD.mouse_contract import (
    CAPABILITY_ROUTES, COMMAND_MOUSE_CAPABILITIES,
    LEGACY_COMMAND_REPLACEMENTS, MODE_MOUSE_CAPABILITIES, PlayerCapability,
)
from PyAitD.ui import Command


_PURITY_PROBE = r"""
import sys
import PyAitD.mouse_contract
leaked = {"pygame", "moderngl", "PyAitD.ui", "PyAitD.render"} & sys.modules.keys()
raise SystemExit(", ".join(sorted(leaked)) if leaked else 0)
"""


def test_mouse_contract_is_presentation_free():
    result = subprocess.run(
        [sys.executable, "-c", _PURITY_PROBE], capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_every_capability_has_exactly_one_route():
    assert set(CAPABILITY_ROUTES) == set(PlayerCapability)
    assert all(route.gesture in {"left_click", "window_close"}
               for route in CAPABILITY_ROUTES.values())


def test_every_mode_declares_exactly_the_routes_available_in_it():
    assert set(MODE_MOUSE_CAPABILITIES) == set(GameMode)
    for mode in GameMode:
        derived = frozenset(
            capability for capability, route in CAPABILITY_ROUTES.items()
            if mode in route.modes
        )
        assert MODE_MOUSE_CAPABILITIES[mode] == derived


def test_every_command_has_a_mouse_capability_or_reviewed_legacy_decision():
    declared = set(COMMAND_MOUSE_CAPABILITIES) | set(LEGACY_COMMAND_REPLACEMENTS)
    assert declared == set(Command.__members__)
    assert set(COMMAND_MOUSE_CAPABILITIES).isdisjoint(LEGACY_COMMAND_REPLACEMENTS)
    assert LEGACY_COMMAND_REPLACEMENTS["TOGGLE_INPUT_MODE"].replacement is None
    assert "leaves the mouse scheme" in LEGACY_COMMAND_REPLACEMENTS[
        "TOGGLE_INPUT_MODE"
    ].reason
