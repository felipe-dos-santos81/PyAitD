# SPDX-License-Identifier: GPL-2.0-only
import pygame
import pytest

from PyAitD.app.config import Settings, default_settings, replace_binding
from PyAitD.app.controls.actions import Action
from PyAitD.app.controls.bindings import compile_bindings
from PyAitD.app.controls.keyboard import KeyboardState, feed_key_event, reset_keyboard

pytestmark = pytest.mark.shell


def key(kind, value, *, repeat=False):
    return pygame.event.Event(kind, key=value, repeat=repeat)


def test_held_movement_survives_queue_consumption_and_action_is_edge_free():
    state = KeyboardState()
    feed_key_event(state, key(pygame.KEYDOWN, pygame.K_UP))
    feed_key_event(state, key(pygame.KEYDOWN, pygame.K_SPACE))
    assert (state.held_joyd, state.action_held) == (1, True)
    assert list(state.queue) == [Action.UP, Action.ACTION]
    state.queue.popleft()
    assert (state.held_joyd, state.action_held) == (1, True)


def test_keyup_and_reset_release_without_a_new_action():
    state = KeyboardState(held_joyd=1, action_held=True)
    feed_key_event(state, key(pygame.KEYUP, pygame.K_UP))
    assert state.held_joyd == 0
    state.queue.append(Action.ACTION)
    reset_keyboard(state)
    assert (state.held_joyd, state.action_held, list(state.queue)) == (0, False, [])


def test_inventory_shortcuts_are_single_edges():
    state = KeyboardState()
    feed_key_event(state, key(pygame.KEYDOWN, pygame.K_RETURN))
    feed_key_event(state, key(pygame.KEYDOWN, pygame.K_RETURN, repeat=True))
    feed_key_event(state, key(pygame.KEYDOWN, pygame.K_i))
    assert list(state.queue) == [Action.INVENTORY_CONFIRM, Action.INVENTORY_CONFIRM]


def test_tab_requests_an_input_mode_toggle():
    state = KeyboardState()
    feed_key_event(state, key(pygame.KEYDOWN, pygame.K_TAB))
    assert Action.TOGGLE_INPUT_MODE in state.queue


def test_remapped_table_drives_actions_and_held_bits():
    state = KeyboardState(table=compile_bindings(replace_binding(default_settings(), Action.UP, "q")))
    feed_key_event(state, key(pygame.KEYDOWN, pygame.K_q))
    assert (state.held_joyd, list(state.queue)) == (1, [Action.UP])
    feed_key_event(state, key(pygame.KEYUP, pygame.K_q))
    assert state.held_joyd == 0
    feed_key_event(state, key(pygame.KEYDOWN, pygame.K_w))
    assert state.held_joyd == 0


def test_sticky_action_arms_then_pulses_on_the_next_direction_only_once():
    state = KeyboardState(sticky_action=True)
    feed_key_event(state, key(pygame.KEYDOWN, pygame.K_SPACE))
    assert (state.sticky_armed, state.action_held, state.action_pulse) == (True, False, False)
    assert list(state.queue) == [Action.ACTION]
    feed_key_event(state, key(pygame.KEYDOWN, pygame.K_UP))
    assert (state.sticky_armed, state.action_pulse) == (False, True)
    feed_key_event(state, key(pygame.KEYDOWN, pygame.K_UP, repeat=True))
    assert (state.sticky_armed, state.action_pulse) == (False, True)


def test_reset_cannot_leave_sticky_state_but_keeps_the_table_and_the_setting():
    table = compile_bindings(default_settings())
    state = KeyboardState(sticky_action=True, sticky_armed=True, action_pulse=True, held_joyd=1, action_held=True, table=table)
    reset_keyboard(state)
    assert (state.held_joyd, state.action_held, state.sticky_armed, state.action_pulse) == (0, False, False, False)
    assert state.table is table and state.sticky_action is True
