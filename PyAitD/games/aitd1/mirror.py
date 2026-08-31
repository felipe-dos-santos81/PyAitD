# SPDX-License-Identifier: GPL-2.0-only
"""The original AITD1 keyboard layout as forwarded by the live mirror.

Keyed by control NAME strings: the Control enum lives in app/config.py,
so this module imports nothing from the app layer. Pinned from the FITD
authority, FitdLib/input.cpp readKeyboard: arrows drive JoyD, Space
drives Click, Return drives key 0x1C. Values are macOS virtual keycodes
(kVK_ constants)."""

MIRROR_KEYCODES = {
    "UP": 126,
    "DOWN": 125,
    "LEFT": 123,
    "RIGHT": 124,
    "ACTION": 49,               # Space -> Click
    "INVENTORY_CONFIRM": 36,    # Return -> 0x1C
}
