# SPDX-License-Identifier: GPL-2.0-only
"""The fixed vocabulary every key, gesture and (later) pack binds to.

The eight key-bindable members keep the names and values settings schema v1
stores under "bindings", so a settings file written before this package
existed still loads. The pointer-only members are produced by
controls.pointer and consumed by controls.router; nothing in settings names
them yet.
"""
from enum import Enum


class Action(str, Enum):
    UP = "UP"; DOWN = "DOWN"; LEFT = "LEFT"; RIGHT = "RIGHT"
    ACTION = "ACTION"; INVENTORY_CONFIRM = "INVENTORY_CONFIRM"
    CANCEL = "CANCEL"; TOGGLE_INPUT_MODE = "TOGGLE_INPUT_MODE"
    WALK = "WALK"; RUN = "RUN"; TARGET = "TARGET"; PUSH = "PUSH"
    USE = "USE"; MENU_CLICK = "MENU_CLICK"


KEY_BINDABLE = (
    Action.UP, Action.DOWN, Action.LEFT, Action.RIGHT, Action.ACTION,
    Action.INVENTORY_CONFIRM, Action.CANCEL, Action.TOGGLE_INPUT_MODE,
)

# FITD's joystick direction bits (mainLoop.cpp): up 1, down 2, left 4, right 8
DIRECTION_BITS = {Action.UP: 1, Action.DOWN: 2, Action.LEFT: 4, Action.RIGHT: 8}
