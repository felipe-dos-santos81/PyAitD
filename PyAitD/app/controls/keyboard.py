# SPDX-License-Identifier: GPL-2.0-only
"""Keys to held direction bits, the action button, the sticky-action pulse
and the queue of one-shot actions the router drains."""
from collections import deque
from dataclasses import dataclass, field

import pygame

from PyAitD.app.controls.actions import Action, DIRECTION_BITS
from PyAitD.app.controls.bindings import DEFAULT_ACTION_BY_KEY


@dataclass
class KeyboardState:
    held_joyd: int = 0
    action_held: bool = False
    action_pulse: bool = False
    sticky_action: bool = False
    sticky_armed: bool = False
    queue: deque = field(default_factory=deque)
    # None keeps the pre-settings defaults; a compiled table is used as-is,
    # even when intentionally empty.
    table: dict | None = None


def reset_keyboard(state):
    state.held_joyd = 0
    state.action_held = False
    state.action_pulse = False
    state.sticky_armed = False
    state.queue.clear()


def feed_key_event(state, event):
    table = DEFAULT_ACTION_BY_KEY if state.table is None else state.table
    if event.type == pygame.KEYDOWN:
        repeated = bool(getattr(event, "repeat", False))
        action = table.get(event.key)
        if action in DIRECTION_BITS:
            state.held_joyd |= DIRECTION_BITS[action]
            if not repeated:
                state.queue.append(action)
                if state.sticky_armed:
                    state.action_pulse = True
                    state.sticky_armed = False
        elif action is Action.ACTION:
            if state.sticky_action:
                if not repeated:
                    state.sticky_armed = True
                    state.queue.append(Action.ACTION)
            else:
                state.action_held = True
                if not repeated:
                    state.queue.append(Action.ACTION)
        elif not repeated and action in (
                Action.INVENTORY_CONFIRM, Action.CANCEL, Action.TOGGLE_INPUT_MODE):
            state.queue.append(action)
    elif event.type == pygame.KEYUP:
        action = table.get(event.key)
        if action in DIRECTION_BITS:
            state.held_joyd &= ~DIRECTION_BITS[action]
        elif action is Action.ACTION:
            state.action_held = False
