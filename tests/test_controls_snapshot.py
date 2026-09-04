# SPDX-License-Identifier: GPL-2.0-only
from collections import deque

import pygame
import pytest

from PyAitD.app.config import Settings, default_settings, replace_binding
from PyAitD.app.controls.actions import Action
from PyAitD.app.controls.keyboard import KeyboardState
from PyAitD.app.controls.pointer import PointerState
from PyAitD.app.controls.snapshot import (
    ControlsState, build_play_input, configure, feed_event, reset,
)
from PyAitD.engine.script.playworld import IDLE, PlayInput

pytestmark = pytest.mark.shell


@pytest.fixture(autouse=True)
def _pygame_initialized():
    # configure() -> compile_bindings() calls pygame.key.key_code, which warns
    # "pygame.init() has not been called" otherwise -- the same init/quit
    # pairing tests/test_controls_keyboard.py and tests/test_controls_bindings.py
    # apply, as an autouse fixture so it holds regardless of what an
    # earlier-running test module left pygame's init state in, and quit so a
    # later module is not left seeing an initialized pygame it didn't ask for.
    pygame.init()
    yield
    pygame.quit()


def test_an_untouched_controls_state_snapshots_to_idle():
    assert build_play_input(ControlsState()) == IDLE


def test_the_snapshot_copies_the_five_engine_fields_and_consumes_the_pulse():
    controls = ControlsState(
        keyboard=KeyboardState(held_joyd=3, action_held=True, action_pulse=True),
        pointer=PointerState(held=True, pos=(1, 2)), focused=False,
    )
    first = build_play_input(controls)
    assert first == PlayInput(joyd=3, action_held=True, action_pulse=True, pointer_held=True, focused=False)
    assert controls.keyboard.action_pulse is False
    assert build_play_input(controls).action_pulse is False


def test_quit_and_focus_flow_through_feed_event():
    controls = ControlsState(keyboard=KeyboardState(held_joyd=1, queue=deque([Action.ACTION])),
                             pointer=PointerState(held=True, pos=(5, 5)))
    assert feed_event(controls, pygame.event.Event(pygame.WINDOWFOCUSLOST)) is True
    assert (controls.focused, controls.keyboard.held_joyd, list(controls.keyboard.queue)) == (False, 0, [])
    assert (controls.pointer.held, controls.pointer.pos) == (False, None)
    assert feed_event(controls, pygame.event.Event(pygame.WINDOWFOCUSGAINED)) is True
    assert controls.focused is True
    assert feed_event(controls, pygame.event.Event(pygame.QUIT)) is False


@pytest.mark.parametrize("touch", (False, True), ids=("physical", "touch-origin"))
def test_primary_pointer_events_preserve_provenance_only_while_held(touch):
    controls = ControlsState()
    feed_event(controls, pygame.event.Event(pygame.MOUSEMOTION, touch=touch), (12, 34))
    assert (controls.pointer.held, controls.pointer.touch, controls.pointer.pos) == (False, touch, (12, 34))
    feed_event(controls, pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, touch=touch), (56, 78))
    assert (controls.pointer.held, controls.pointer.touch, controls.pointer.pos) == (True, touch, (56, 78))
    feed_event(controls, pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, touch=touch))
    assert (controls.pointer.held, controls.pointer.touch, controls.pointer.pos) == (False, False, None)


def test_keys_reach_the_keyboard_state_through_feed_event():
    controls = ControlsState()
    feed_event(controls, pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP, repeat=False))
    assert (controls.keyboard.held_joyd, list(controls.keyboard.queue)) == (1, [Action.UP])


def test_configure_compiles_the_table_sets_sticky_and_resets():
    controls = ControlsState(keyboard=KeyboardState(held_joyd=1), pointer=PointerState(held=True, spent=True))
    configure(controls, Settings(replace_binding(default_settings(), Action.UP, "q").bindings, sticky_action=True))
    assert controls.keyboard.table[pygame.K_q] is Action.UP
    assert controls.keyboard.sticky_action is True
    assert (controls.keyboard.held_joyd, controls.pointer.held, controls.pointer.spent) == (0, False, False)
    configure(controls, default_settings())
    assert controls.keyboard.sticky_action is False


def test_reset_clears_both_states_and_the_game_latch(data_dir, profile):
    from PyAitD.engine.script.game import init_game
    from PyAitD.engine.script.playworld import arm_mouse_attack
    game = init_game(data_dir, profile)
    arm_mouse_attack(game, 7)
    controls = ControlsState(
        keyboard=KeyboardState(held_joyd=9, action_held=True, sticky_armed=True, action_pulse=True),
        pointer=PointerState(held=True, pos=(1, 1), follow_last=(1, 2, 0, -1), follow_pos=(10, 20),
                             follow_camera=2, settle_origin=(10, 10), spent=True, run=True,
                             last_press_tick=7, resume_last=(1, 2, 0, -1), resume_pos=(10, 20)),
    )
    reset(controls, game)
    assert controls.keyboard == KeyboardState()
    assert controls.pointer == PointerState()
    assert (game.mouse_attack_target, game.mouse_attack_ticks) == (None, 0)
    reset(ControlsState(), None)   # callers without a game
