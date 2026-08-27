# SPDX-License-Identifier: GPL-2.0-only
import pygame
import pytest

from PyAitD.app.config import (
    Control, Settings, default_settings, replace_binding,
)
from PyAitD.app.ui import (
    Command, InputBuffer, canonical_key_name, compile_bindings,
    configure_input, event_to_input, reset_input,
)

pytestmark = pytest.mark.shell


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


def test_inventory_shortcuts_are_single_edges():
    state = InputBuffer()
    event_to_input(key(pygame.KEYDOWN, pygame.K_RETURN), state)
    event_to_input(key(pygame.KEYDOWN, pygame.K_RETURN, repeat=True), state)
    event_to_input(key(pygame.KEYDOWN, pygame.K_i), state)
    assert list(state.commands) == [Command.OPEN_INVENTORY, Command.OPEN_INVENTORY]


def test_tab_requests_an_input_mode_toggle():
    state = InputBuffer()
    event_to_input(key(pygame.KEYDOWN, pygame.K_TAB), state)
    assert Command.TOGGLE_INPUT_MODE in state.commands


def test_pygame_key_names_round_trip_through_compat_adapter():
    assert canonical_key_name(pygame.K_RETURN) == "return"
    assert pygame.key.key_code(canonical_key_name(pygame.K_w)) == pygame.K_w


def test_unknown_persisted_key_name_is_rejected():
    settings = default_settings()
    bindings = dict(settings.bindings)
    bindings["ACTION"] = ("definitely-not-a-pygame-key",)
    with pytest.raises(ValueError, match="definitely-not-a-pygame-key"):
        compile_bindings(Settings(bindings, False))


def test_remapped_table_drives_commands_and_held_bits():
    settings = default_settings()
    settings = replace_binding(settings, Control.UP, "q")
    state = InputBuffer()
    configure_input(state, settings)
    event_to_input(key(pygame.KEYDOWN, pygame.K_q), state)
    assert (state.held_joyd, list(state.commands)) == (1, [Command.UP])
    event_to_input(key(pygame.KEYUP, pygame.K_q), state)
    assert state.held_joyd == 0
    event_to_input(key(pygame.KEYDOWN, pygame.K_w), state)
    assert state.held_joyd == 0


def test_sticky_action_arms_then_pulses_on_the_next_direction_only_once():
    settings = Settings(default_settings().bindings, sticky_action=True)
    state = InputBuffer()
    configure_input(state, settings)
    event_to_input(key(pygame.KEYDOWN, pygame.K_SPACE), state)
    assert (state.sticky_armed, state.action_held, state.action_pulse) == (True, False, False)
    event_to_input(key(pygame.KEYDOWN, pygame.K_UP), state)
    assert (state.sticky_armed, state.action_pulse) == (False, True)


def test_repeat_focus_loss_and_reconfiguration_cannot_leave_sticky_state():
    state = InputBuffer(sticky_armed=True, action_pulse=True, held_joyd=1, action_held=True)
    event_to_input(pygame.event.Event(pygame.WINDOWFOCUSLOST), state)
    assert (state.held_joyd, state.action_held, state.sticky_armed, state.action_pulse) == (0, False, False, False)
    configure_input(state, default_settings())
    assert not state.sticky_action


def test_reset_input_clears_native_mouse_combat():
    # Focus loss, modal takeover, restart and hero replacement all funnel
    # through reset_input, so clearing the transient combat latch here is what
    # makes it impossible for an old click to resume a swing later.
    state = InputBuffer(mouse_attack_target=7, mouse_attack_ticks=12)
    reset_input(state)
    assert (state.mouse_attack_target, state.mouse_attack_ticks) == (None, 0)


def test_reset_input_clears_the_follow_latch():
    # the held pointer follow's latch lives in the buffer so every existing
    # focus, modal and input-mode reset seam clears it for free
    state = InputBuffer(follow_last=(1, 2, 0, -1), follow_spent=True)
    reset_input(state)
    assert (state.follow_last, state.follow_spent) == (None, False)
