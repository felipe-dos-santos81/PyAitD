# SPDX-License-Identifier: GPL-2.0-only
import pygame
import pytest

from PyAitD.app.config import Control, Settings, default_settings, replace_binding
from PyAitD.app.controls.actions import Action, KEY_BINDABLE
from PyAitD.app.controls.bindings import (
    DEFAULT_ACTION_BY_KEY, canonical_key_name, compile_bindings,
)

pytestmark = pytest.mark.shell


@pytest.fixture(autouse=True)
def _pygame_initialized():
    # compile_bindings/canonical_key_name call pygame.key.key_code/
    # pygame.key.name, which warn "pygame.init() has not been called"
    # otherwise -- the same init/quit pairing tests/test_ui_reducers.py's
    # pickable-keys test applies per-test, as an autouse fixture instead of
    # a module-level call so it holds regardless of what an earlier-running
    # test module left pygame's init state in, and quit so a later module
    # is not left seeing an initialized pygame it didn't ask for.
    pygame.init()
    yield
    pygame.quit()


def test_control_is_the_key_bindable_half_of_action():
    assert Control is Action
    assert tuple(action.name for action in KEY_BINDABLE) == (
        "UP", "DOWN", "LEFT", "RIGHT", "ACTION", "INVENTORY_CONFIRM", "CANCEL", "TOGGLE_INPUT_MODE",
    )
    assert set(default_settings().bindings) == {action.name for action in KEY_BINDABLE}


def test_pygame_key_names_round_trip_through_compat_adapter():
    assert canonical_key_name(pygame.K_RETURN) == "return"
    assert pygame.key.key_code(canonical_key_name(pygame.K_w)) == pygame.K_w


def test_unknown_persisted_key_name_is_rejected():
    settings = default_settings()
    bindings = dict(settings.bindings)
    bindings["ACTION"] = ("definitely-not-a-pygame-key",)
    with pytest.raises(ValueError, match="definitely-not-a-pygame-key"):
        compile_bindings(Settings(bindings, False))


def test_the_default_table_matches_the_default_settings():
    compiled = compile_bindings(default_settings())
    assert compiled == DEFAULT_ACTION_BY_KEY


def test_a_remap_moves_the_key_and_nothing_else():
    compiled = compile_bindings(replace_binding(default_settings(), Control.UP, "q"))
    assert compiled[pygame.K_q] is Action.UP
    assert pygame.K_w not in compiled
    assert compiled[pygame.K_SPACE] is Action.ACTION
