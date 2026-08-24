# SPDX-License-Identifier: GPL-2.0-only
"""Declared one-button mouse surface for the implemented M3 game modes."""
from dataclasses import dataclass
from enum import Enum, auto

from PyAitD.effects import GameMode


class PlayerCapability(Enum):
    WALK_TO_POINT = auto()
    INTERACT_WITH_OBJECT = auto()
    TAKE_FOUND_OBJECT = auto()
    LEAVE_FOUND_OBJECT = auto()
    OPEN_INVENTORY = auto()
    SELECT_INVENTORY_OBJECT = auto()
    SELECT_INVENTORY_ACTION = auto()
    PAGE_READING = auto()
    CLOSE_READING = auto()
    DISMISS_PICTURE = auto()
    ATTACK_TARGET = auto()
    HOLD_PUSH_OBJECT = auto()
    RESTART_GAME_OVER = auto()
    QUIT = auto()
    SELECT_CHARACTER = auto()
    CONFIRM_STORY_PAGE = auto()
    MENU_ACTIVATE = auto()
    DISMISS_SETTINGS_ERROR = auto()


@dataclass(frozen=True)
class MouseRoute:
    gesture: str
    target: str
    modes: frozenset[GameMode]


@dataclass(frozen=True)
class LegacyCommandDecision:
    replacement: PlayerCapability | None
    reason: str


ALL_MODES = frozenset(GameMode)
CAPABILITY_ROUTES = {
    PlayerCapability.WALK_TO_POINT: MouseRoute("left_click", "walkable floor", frozenset({GameMode.PLAY})),
    PlayerCapability.INTERACT_WITH_OBJECT: MouseRoute("left_click", "interactable actor", frozenset({GameMode.PLAY})),
    PlayerCapability.TAKE_FOUND_OBJECT: MouseRoute("left_click", "Take button", frozenset({GameMode.FOUND})),
    PlayerCapability.LEAVE_FOUND_OBJECT: MouseRoute("left_click", "Leave button", frozenset({GameMode.FOUND})),
    PlayerCapability.OPEN_INVENTORY: MouseRoute("left_click", "inventory HUD", frozenset({GameMode.PLAY})),
    PlayerCapability.SELECT_INVENTORY_OBJECT: MouseRoute("left_click", "inventory object row", frozenset({GameMode.INVENTORY})),
    PlayerCapability.SELECT_INVENTORY_ACTION: MouseRoute("left_click", "inventory action row", frozenset({GameMode.INVENTORY})),
    PlayerCapability.PAGE_READING: MouseRoute("left_click", "Previous or Next button", frozenset({GameMode.READING})),
    PlayerCapability.CLOSE_READING: MouseRoute("left_click", "Close button", frozenset({GameMode.READING})),
    PlayerCapability.DISMISS_PICTURE: MouseRoute("left_click", "picture", frozenset({GameMode.READING})),
    PlayerCapability.ATTACK_TARGET: MouseRoute("left_click", "armed combat actor", frozenset({GameMode.PLAY})),
    PlayerCapability.HOLD_PUSH_OBJECT: MouseRoute(
        "left_hold", "push-capable scripted actor", frozenset({GameMode.PLAY}),
    ),
    PlayerCapability.RESTART_GAME_OVER: MouseRoute("left_click", "game-over frame", frozenset({GameMode.GAME_OVER})),
    PlayerCapability.QUIT: MouseRoute("window_close", "window close control", ALL_MODES),
    PlayerCapability.SELECT_CHARACTER: MouseRoute(
        "left_click", "character portrait", frozenset({GameMode.CHARACTER_SELECT}),
    ),
    PlayerCapability.CONFIRM_STORY_PAGE: MouseRoute(
        "left_click", "character story page", frozenset({GameMode.CHARACTER_SELECT}),
    ),
    PlayerCapability.MENU_ACTIVATE: MouseRoute(
        "left_click", "system menu row", frozenset({GameMode.SYSTEM_MENU}),
    ),
    PlayerCapability.DISMISS_SETTINGS_ERROR: MouseRoute(
        "left_click", "settings error Dismiss button", ALL_MODES,
    ),
}


MODE_MOUSE_CAPABILITIES = {
    GameMode.PLAY: frozenset({
        PlayerCapability.WALK_TO_POINT,
        PlayerCapability.INTERACT_WITH_OBJECT,
        PlayerCapability.OPEN_INVENTORY,
        PlayerCapability.ATTACK_TARGET,
        PlayerCapability.HOLD_PUSH_OBJECT,
        PlayerCapability.DISMISS_SETTINGS_ERROR,
        PlayerCapability.QUIT,
    }),
    GameMode.FOUND: frozenset({
        PlayerCapability.TAKE_FOUND_OBJECT,
        PlayerCapability.LEAVE_FOUND_OBJECT,
        PlayerCapability.DISMISS_SETTINGS_ERROR,
        PlayerCapability.QUIT,
    }),
    GameMode.INVENTORY: frozenset({
        PlayerCapability.SELECT_INVENTORY_OBJECT,
        PlayerCapability.SELECT_INVENTORY_ACTION,
        PlayerCapability.DISMISS_SETTINGS_ERROR,
        PlayerCapability.QUIT,
    }),
    GameMode.READING: frozenset({
        PlayerCapability.PAGE_READING,
        PlayerCapability.CLOSE_READING,
        PlayerCapability.DISMISS_PICTURE,
        PlayerCapability.DISMISS_SETTINGS_ERROR,
        PlayerCapability.QUIT,
    }),
    GameMode.GAME_OVER: frozenset({
        PlayerCapability.RESTART_GAME_OVER,
        PlayerCapability.DISMISS_SETTINGS_ERROR,
        PlayerCapability.QUIT,
    }),
    GameMode.CHARACTER_SELECT: frozenset({
        PlayerCapability.SELECT_CHARACTER,
        PlayerCapability.CONFIRM_STORY_PAGE,
        PlayerCapability.DISMISS_SETTINGS_ERROR,
        PlayerCapability.QUIT,
    }),
    GameMode.SYSTEM_MENU: frozenset({
        PlayerCapability.MENU_ACTIVATE,
        PlayerCapability.DISMISS_SETTINGS_ERROR,
        PlayerCapability.QUIT,
    }),
}


COMMAND_MOUSE_CAPABILITIES = {
    "ACCEPT": frozenset({
        PlayerCapability.INTERACT_WITH_OBJECT,
        PlayerCapability.TAKE_FOUND_OBJECT,
        PlayerCapability.SELECT_INVENTORY_OBJECT,
        PlayerCapability.SELECT_INVENTORY_ACTION,
        PlayerCapability.PAGE_READING,
        PlayerCapability.CLOSE_READING,
        PlayerCapability.DISMISS_PICTURE,
        PlayerCapability.RESTART_GAME_OVER,
    }),
    "CANCEL": frozenset({
        PlayerCapability.LEAVE_FOUND_OBJECT,
        PlayerCapability.CLOSE_READING,
        PlayerCapability.QUIT,
    }),
    "OPEN_INVENTORY": frozenset({PlayerCapability.OPEN_INVENTORY}),
}


LEGACY_COMMAND_REPLACEMENTS = {
    name: LegacyCommandDecision(
        PlayerCapability.WALK_TO_POINT,
        "point-and-click walking replaces the legacy tank-direction command",
    )
    for name in ("UP", "DOWN", "LEFT", "RIGHT")
}
LEGACY_COMMAND_REPLACEMENTS["TOGGLE_INPUT_MODE"] = LegacyCommandDecision(
    None,
    "this command deliberately leaves the mouse scheme; it is not a missing mouse route",
)


KEYBOARD_ONLY_DECISIONS = {
    "REMAP_CAPTURE": LegacyCommandDecision(
        None,
        "a keyboard remap must capture one physical key; menu entry, cancel, and all other configuration decisions remain mouse reachable",
    ),
}
