# SPDX-License-Identifier: GPL-2.0-only
"""The one holder of the app's input state, the pump's event feed, and the
fold into the engine's per-tick PlayInput."""
from dataclasses import dataclass, field

import pygame

from PyAitD.app.controls.bindings import compile_bindings
from PyAitD.app.controls.keyboard import KeyboardState, feed_key_event, reset_keyboard
from PyAitD.app.controls.pointer import PointerState, move, press, release, reset_pointer
from PyAitD.engine.script.playworld import PlayInput, clear_mouse_attack


@dataclass
class ControlsState:
    keyboard: KeyboardState = field(default_factory=KeyboardState)
    pointer: PointerState = field(default_factory=PointerState)
    focused: bool = True


def reset(controls, game):
    """Focus loss, modal takeover, input-mode toggle, restart and hero
    replacement all funnel through here, so an old click can never resume a
    walk or a swing later. `game` may be None for callers that own none."""
    reset_keyboard(controls.keyboard)
    reset_pointer(controls.pointer)
    if game is not None:
        clear_mouse_attack(game)


def configure(controls, settings):
    controls.keyboard.table = compile_bindings(settings)
    controls.keyboard.sticky_action = settings.sticky_action
    reset(controls, None)


def feed_event(controls, event, logical_pos=None):
    """One pygame event into the state. False means QUIT."""
    if event.type == pygame.QUIT:
        return False
    if event.type == pygame.WINDOWFOCUSLOST:
        reset(controls, None)
        controls.focused = False
        return True
    if event.type == pygame.WINDOWFOCUSGAINED:
        controls.focused = True
        return True
    if event.type == pygame.MOUSEMOTION:
        move(controls.pointer, logical_pos, bool(getattr(event, "touch", False)))
        return True
    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
        press(controls.pointer, logical_pos, bool(getattr(event, "touch", False)))
        return True
    if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
        release(controls.pointer)
        return True
    feed_key_event(controls.keyboard, event)
    return True


def build_play_input(controls):
    """The engine's snapshot for one tick. Consumes the sticky pulse: the
    engine no longer writes back into its input, and a pulse raised while a
    modal is open must still fire on the first play tick after it, so it is
    cleared here and nowhere else."""
    keyboard = controls.keyboard
    snapshot = PlayInput(
        joyd=keyboard.held_joyd,
        action_held=keyboard.action_held,
        action_pulse=keyboard.action_pulse,
        pointer_held=controls.pointer.held,
        focused=controls.focused,
    )
    keyboard.action_pulse = False
    return snapshot
