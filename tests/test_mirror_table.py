# SPDX-License-Identifier: GPL-2.0-only
"""The live mirror's key table: the original AITD1 layout, FITD-pinned."""
import pytest

from PyAitD.games.aitd1.mirror import MIRROR_KEYCODES

pytestmark = pytest.mark.shell


def test_every_forwarded_control_has_a_mac_keycode():
    assert set(MIRROR_KEYCODES) == {
        "UP", "DOWN", "LEFT", "RIGHT", "ACTION", "INVENTORY_CONFIRM",
    }


def test_keycodes_match_the_original_layout():
    # FitdLib/input.cpp readKeyboard: arrows -> JoyD, Space -> Click,
    # Return -> 0x1C. macOS virtual keycodes (kVK_ constants).
    assert MIRROR_KEYCODES["UP"] == 126
    assert MIRROR_KEYCODES["DOWN"] == 125
    assert MIRROR_KEYCODES["LEFT"] == 123
    assert MIRROR_KEYCODES["RIGHT"] == 124
    assert MIRROR_KEYCODES["ACTION"] == 49
    assert MIRROR_KEYCODES["INVENTORY_CONFIRM"] == 36


def test_no_menu_key_is_forwarded():
    # Escape (system menu) and the inventory open key stay manual in the
    # original: forwarding them would desync the two menus.
    assert "CANCEL" not in MIRROR_KEYCODES
    assert "OPEN_INVENTORY" not in MIRROR_KEYCODES
