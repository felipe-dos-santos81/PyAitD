# SPDX-License-Identifier: GPL-2.0-only
"""Settings key names to pygame key codes, and back."""
import pygame

from PyAitD.app.controls.actions import Action, KEY_BINDABLE

# The table the pump uses before settings are loaded, and the one
# default_settings compiles to. Never touches pygame.key before init.
DEFAULT_ACTION_BY_KEY = {
    pygame.K_UP: Action.UP, pygame.K_w: Action.UP,
    pygame.K_DOWN: Action.DOWN, pygame.K_s: Action.DOWN,
    pygame.K_LEFT: Action.LEFT, pygame.K_a: Action.LEFT,
    pygame.K_RIGHT: Action.RIGHT, pygame.K_d: Action.RIGHT,
    pygame.K_SPACE: Action.ACTION,
    pygame.K_RETURN: Action.INVENTORY_CONFIRM,
    pygame.K_i: Action.INVENTORY_CONFIRM,
    pygame.K_ESCAPE: Action.CANCEL,
    pygame.K_TAB: Action.TOGGLE_INPUT_MODE,
}


def canonical_key_name(key):
    name = pygame.key.name(key, use_compat=True)
    if not name or name == "unknown key":
        raise ValueError(f"pygame key {key} has no stable name")
    return name


def compile_bindings(settings):
    compiled = {}
    for action in KEY_BINDABLE:
        for name in settings.bindings[action.name]:
            try:
                code = pygame.key.key_code(name)
            except ValueError as exc:
                raise ValueError(f"unknown pygame key name {name!r}") from exc
            compiled[code] = action
    return compiled
