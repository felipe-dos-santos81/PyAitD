# SPDX-License-Identifier: GPL-2.0-only
import pygame
import pytest

from PyAitD.app.controls.actions import Action
from PyAitD.app.controls.keyboard import KeyboardState
from PyAitD.app.controls.pointer import PointerState, reset_pointer
from PyAitD.app.controls.snapshot import ControlsState, feed_event

pytestmark = pytest.mark.shell


def key(kind, value, *, repeat=False):
    return pygame.event.Event(kind, key=value, repeat=repeat)


def test_keyup_and_focus_loss_release_controls_without_new_command():
    state = ControlsState(keyboard=KeyboardState(held_joyd=1, action_held=True))
    feed_event(state, key(pygame.KEYUP, pygame.K_UP))
    assert state.keyboard.held_joyd == 0
    state.keyboard.queue.append(Action.ACTION)
    feed_event(state, pygame.event.Event(pygame.WINDOWFOCUSLOST))
    assert (state.keyboard.held_joyd, state.keyboard.action_held, state.focused) == (0, False, False)
    assert list(state.keyboard.queue) == []


def test_reset_pointer_clears_the_follow_latch():
    # the held pointer follow's latch lives in the pointer state so every
    # existing focus, modal and input-mode reset seam clears it for free
    state = PointerState(
        follow_last=(1, 2, 0, -1), follow_pos=(10, 20), spent=True,
        run=True, last_press_tick=7,
    )
    reset_pointer(state)
    assert (state.follow_last, state.follow_pos, state.spent) == (
        None, None, False,
    ), "a stale follow_pos would gate the first resolution after the reset"
    assert (state.run, state.last_press_tick) == (False, None), (
        "a modal or focus loss ends the hold, so it ends the run and the "
        "press clock the next double press would be measured against"
    )


def test_reset_pointer_clears_the_cut_settle_state():
    state = PointerState(follow_camera=2, settle_origin=(10, 10))
    reset_pointer(state)
    assert state.follow_camera is None
    assert state.settle_origin is None
