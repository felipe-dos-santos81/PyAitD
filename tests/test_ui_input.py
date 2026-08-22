# SPDX-License-Identifier: GPL-2.0-only
import pygame

from maitd.ui import Command, InputBuffer, event_to_input


def key(kind, value, *, repeat=False):
    return pygame.event.Event(kind, key=value, repeat=repeat)


def test_held_movement_survives_command_consumption_and_action_is_edge_free():
    state = InputBuffer()
    assert event_to_input(key(pygame.KEYDOWN, pygame.K_UP), state)
    assert event_to_input(key(pygame.KEYDOWN, pygame.K_SPACE), state)
    assert state.held_joyd == 1
    assert state.action_held is True
    assert list(state.commands) == [Command.UP, Command.ACCEPT]
    state.commands.popleft()
    assert state.held_joyd == 1
    assert state.action_held is True


def test_keyup_and_focus_loss_release_controls_without_new_command():
    state = InputBuffer(held_joyd=1, action_held=True)
    event_to_input(key(pygame.KEYUP, pygame.K_UP), state)
    assert state.held_joyd == 0
    state.commands.append(Command.ACCEPT)
    event_to_input(pygame.event.Event(pygame.WINDOWFOCUSLOST), state)
    assert (state.held_joyd, state.action_held, state.focused) == (0, False, False)
    assert list(state.commands) == []


def test_inventory_shortcuts_are_single_edges():
    state = InputBuffer()
    event_to_input(key(pygame.KEYDOWN, pygame.K_RETURN), state)
    event_to_input(key(pygame.KEYDOWN, pygame.K_RETURN, repeat=True), state)
    event_to_input(key(pygame.KEYDOWN, pygame.K_i), state)
    assert list(state.commands) == [Command.OPEN_INVENTORY, Command.OPEN_INVENTORY]
