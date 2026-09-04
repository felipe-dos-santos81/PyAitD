# SPDX-License-Identifier: GPL-2.0-only
import pygame
import pytest

from PyAitD.app.config import default_settings
from PyAitD.app.controls.actions import Action
from PyAitD.app.controls.keyboard import KeyboardState
from PyAitD.app.ui import (
    InputBuffer, configure_input, event_to_input, reset_input,
)

pytestmark = pytest.mark.shell


def key(kind, value, *, repeat=False):
    return pygame.event.Event(kind, key=value, repeat=repeat)


def test_keyup_and_focus_loss_release_controls_without_new_command():
    state = InputBuffer(keyboard=KeyboardState(held_joyd=1, action_held=True))
    event_to_input(key(pygame.KEYUP, pygame.K_UP), state)
    assert state.held_joyd == 0
    state.commands.append(Action.ACTION)
    event_to_input(pygame.event.Event(pygame.WINDOWFOCUSLOST), state)
    assert (state.held_joyd, state.action_held, state.focused) == (0, False, False)
    assert list(state.commands) == []


@pytest.mark.parametrize("touch", (False, True), ids=("physical", "touch-origin"))
def test_primary_pointer_events_preserve_provenance_only_while_held(touch):
    state = InputBuffer()
    event_to_input(
        pygame.event.Event(pygame.MOUSEMOTION, touch=touch), state, (12, 34),
    )
    assert (state.pointer_held, state.pointer_touch, state.pointer_pos) == (
        False, touch, (12, 34),
    )
    event_to_input(
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, touch=touch),
        state,
        (56, 78),
    )
    assert (state.pointer_held, state.pointer_touch, state.pointer_pos) == (
        True, touch, (56, 78),
    )
    event_to_input(
        pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, touch=touch), state,
    )
    assert (state.pointer_held, state.pointer_touch, state.pointer_pos) == (
        False, False, None,
    )
    event_to_input(
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, touch=touch),
        state,
        (90, 12),
    )
    event_to_input(pygame.event.Event(pygame.WINDOWFOCUSLOST), state)
    assert (state.pointer_held, state.pointer_touch, state.pointer_pos) == (
        False, False, None,
    )


def test_repeat_focus_loss_and_reconfiguration_cannot_leave_sticky_state():
    state = InputBuffer(keyboard=KeyboardState(
        sticky_armed=True, action_pulse=True, held_joyd=1, action_held=True,
    ))
    event_to_input(pygame.event.Event(pygame.WINDOWFOCUSLOST), state)
    assert (state.held_joyd, state.action_held, state.sticky_armed, state.action_pulse) == (0, False, False, False)
    configure_input(state, default_settings())
    assert not state.sticky_action


def test_reset_input_clears_the_follow_latch():
    # the held pointer follow's latch lives in the buffer so every existing
    # focus, modal and input-mode reset seam clears it for free
    state = InputBuffer(
        follow_last=(1, 2, 0, -1), follow_pos=(10, 20), follow_spent=True,
        pointer_run=True, last_press_tick=7,
    )
    reset_input(state)
    assert (state.follow_last, state.follow_pos, state.follow_spent) == (
        None, None, False,
    ), "a stale follow_pos would gate the first resolution after the reset"
    assert (state.pointer_run, state.last_press_tick) == (False, None), (
        "a modal or focus loss ends the hold, so it ends the run and the "
        "press clock the next double press would be measured against"
    )


def test_reset_input_clears_the_cut_settle_state():
    state = InputBuffer(follow_camera=2, follow_settle_origin=(10, 10))
    reset_input(state)
    assert state.follow_camera is None
    assert state.follow_settle_origin is None
