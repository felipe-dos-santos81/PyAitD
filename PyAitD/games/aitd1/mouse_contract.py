# SPDX-License-Identifier: GPL-2.0-only
"""Declared one-button mouse surface for the implemented game modes: single presses, held pointer follow, and latched hold-push."""
from dataclasses import dataclass
from enum import Enum, auto

from PyAitD.engine.script.effects import GameMode


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
    PICK_REMAP_KEY = auto()
    SAVE_MANUAL = auto()
    LOAD_MANUAL = auto()
    LOAD_QUICK = auto()
    QUICK_SAVE = auto()
    PERSISTENCE_BACK = auto()
    DISMISS_SETTINGS_ERROR = auto()
    ADVANCE_TITLE = auto()
    STARTUP_MENU_ACTIVATE = auto()
    SKIP_CUTSCENE = auto()


@dataclass(frozen=True)
class MouseRoute:
    gesture: str
    target: str
    modes: frozenset[GameMode]


@dataclass(frozen=True)
class LegacyCommandDecision:
    replacement: PlayerCapability | None
    reason: str


@dataclass(frozen=True)
class MouseInteractionDecision:
    decision: str
    reason: str


ALL_MODES = frozenset(GameMode)
CAPABILITY_ROUTES = {
    PlayerCapability.WALK_TO_POINT: MouseRoute("left_hold", "anywhere on screen", frozenset({GameMode.PLAY})),
    PlayerCapability.INTERACT_WITH_OBJECT: MouseRoute("left_hold", "interactable actor", frozenset({GameMode.PLAY})),
    PlayerCapability.TAKE_FOUND_OBJECT: MouseRoute("left_click", "Take button", frozenset({GameMode.FOUND})),
    PlayerCapability.LEAVE_FOUND_OBJECT: MouseRoute("left_click", "Leave button", frozenset({GameMode.FOUND})),
    PlayerCapability.OPEN_INVENTORY: MouseRoute("left_click", "inventory HUD", frozenset({GameMode.PLAY})),
    PlayerCapability.SELECT_INVENTORY_OBJECT: MouseRoute("left_click", "inventory object row", frozenset({GameMode.INVENTORY})),
    PlayerCapability.SELECT_INVENTORY_ACTION: MouseRoute("left_click", "inventory action row", frozenset({GameMode.INVENTORY})),
    PlayerCapability.PAGE_READING: MouseRoute("left_click", "Previous or Next button", frozenset({GameMode.READING})),
    PlayerCapability.CLOSE_READING: MouseRoute("left_click", "Close button", frozenset({GameMode.READING})),
    PlayerCapability.DISMISS_PICTURE: MouseRoute("left_click", "picture", frozenset({GameMode.READING})),
    PlayerCapability.ATTACK_TARGET: MouseRoute("left_click", "combat actor, with something in hand", frozenset({GameMode.PLAY})),
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
        "left_click", "system menu row (including graphics rows)", frozenset({GameMode.SYSTEM_MENU}),
    ),
    PlayerCapability.PICK_REMAP_KEY: MouseRoute(
        "left_click", "key-picker cell or Cancel button", frozenset({GameMode.SYSTEM_MENU}),
    ),
    PlayerCapability.SAVE_MANUAL: MouseRoute(
        "left_click", "Save page Manual Slot row", frozenset({GameMode.SYSTEM_MENU}),
    ),
    PlayerCapability.LOAD_MANUAL: MouseRoute(
        "left_click", "Load page Manual Slot row", frozenset({GameMode.SYSTEM_MENU}),
    ),
    PlayerCapability.LOAD_QUICK: MouseRoute(
        "left_click", "Load page Quick Save row", frozenset({GameMode.SYSTEM_MENU}),
    ),
    PlayerCapability.QUICK_SAVE: MouseRoute(
        "left_click", "Quick Save row", frozenset({GameMode.SYSTEM_MENU}),
    ),
    PlayerCapability.PERSISTENCE_BACK: MouseRoute(
        "left_click", "Save or Load page Back row", frozenset({GameMode.SYSTEM_MENU}),
    ),
    PlayerCapability.DISMISS_SETTINGS_ERROR: MouseRoute(
        "left_click", "settings error Dismiss button", ALL_MODES,
    ),
    PlayerCapability.ADVANCE_TITLE: MouseRoute(
        "left_click", "title or credits page", frozenset({GameMode.TITLE}),
    ),
    PlayerCapability.STARTUP_MENU_ACTIVATE: MouseRoute(
        "left_click", "startup menu row", frozenset({GameMode.STARTUP_MENU}),
    ),
    # session-conditional: the contract has no representation for session
    # state, so this route's GameMode.PLAY membership is true only while
    # session.cutscene (shell.py) -- an ordinary PLAY left click walks or
    # interacts instead. GameMode.CUTSCENE_END has no such condition: that
    # mode IS the cutscene's terminal CutsceneFinished modal.
    PlayerCapability.SKIP_CUTSCENE: MouseRoute(
        "left_click", "anywhere during the opening cutscene", frozenset({GameMode.PLAY, GameMode.CUTSCENE_END}),
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
        PlayerCapability.SKIP_CUTSCENE,
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
        PlayerCapability.PICK_REMAP_KEY,
        PlayerCapability.SAVE_MANUAL,
        PlayerCapability.LOAD_MANUAL,
        PlayerCapability.LOAD_QUICK,
        PlayerCapability.QUICK_SAVE,
        PlayerCapability.PERSISTENCE_BACK,
        PlayerCapability.DISMISS_SETTINGS_ERROR,
        PlayerCapability.QUIT,
    }),
    GameMode.TITLE: frozenset({
        PlayerCapability.ADVANCE_TITLE,
        PlayerCapability.DISMISS_SETTINGS_ERROR,
        PlayerCapability.QUIT,
    }),
    GameMode.STARTUP_MENU: frozenset({
        PlayerCapability.STARTUP_MENU_ACTIVATE,
        PlayerCapability.DISMISS_SETTINGS_ERROR,
        PlayerCapability.QUIT,
    }),
    GameMode.CUTSCENE_END: frozenset({
        PlayerCapability.SKIP_CUTSCENE,
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
        PlayerCapability.ADVANCE_TITLE,
        PlayerCapability.STARTUP_MENU_ACTIVATE,
        PlayerCapability.SKIP_CUTSCENE,
    }),
    "CANCEL": frozenset({
        PlayerCapability.LEAVE_FOUND_OBJECT,
        PlayerCapability.CLOSE_READING,
        PlayerCapability.QUIT,
        PlayerCapability.SKIP_CUTSCENE,
    }),
    "OPEN_INVENTORY": frozenset({PlayerCapability.OPEN_INVENTORY}),
}


LEGACY_COMMAND_REPLACEMENTS = {
    name: LegacyCommandDecision(
        PlayerCapability.WALK_TO_POINT,
        "held pointer follow replaces the legacy tank-direction command",
    )
    for name in ("UP", "DOWN", "LEFT", "RIGHT")
}
LEGACY_COMMAND_REPLACEMENTS["TOGGLE_INPUT_MODE"] = LegacyCommandDecision(
    None,
    "this command deliberately leaves the mouse scheme; it is not a missing mouse route",
)


# Empty since the remap key picker: a rebind accepts a physical key press or a
# left click on a picker cell, so no configuration decision is keyboard-only.
KEYBOARD_ONLY_DECISIONS = {}


MOUSE_INTERACTION_DECISIONS = {
    "hover_preview": MouseInteractionDecision(
        "presenter_only",
        "hover previews the current effective target of the unheld pointer "
        "without activating or mutating game state",
    ),
    "touch_origin": MouseInteractionDecision(
        "same_primary_button_route",
        "touch-origin pointer events are provenance and use the same primary-button route",
    ),
    "held_pointer_follow": MouseInteractionDecision(
        "retarget_on_pointer_motion",
        "while the left button is held in PLAY the walk or approach destination "
        "follows the pointer; motion with the button down is a gesture, not hover, "
        "and only motion retargets -- a camera cut is not something the player did",
    ),
    "unreachable_pixel_steers": MouseInteractionDecision(
        "direction_not_destination",
        "a PLAY pixel that names no reachable place -- a wall, a ceiling, the "
        "sky, a cell nothing walkable snaps to -- walks the hero along the "
        "bearing through it instead of refusing, so walking is possible from "
        "every pixel of the world. It adds no PlayerCapability: it is the same "
        "WALK_TO_POINT hold, widened from the walkable floor to the whole "
        "screen. An actor with nothing to offer does not intercept it either: "
        "its draw-list entry is a screen rectangle, so refusing there refused "
        "the floor around it. Only a combat actor still refuses, with an empty "
        "hand or a hero mid-swing, because there the click meant the enemy",
    ),
    "held_double_press_run": MouseInteractionDecision(
        "speed_not_capability",
        "a hold whose press followed the previous one within the double-press "
        "window runs instead of walking, the mouse's reading of FITD's "
        "double-tap forward. It adds no PlayerCapability and needs no gesture "
        "route: running is a speed, and every destination stays reachable at a "
        "walk with one plain hold, so a player who cannot double-press loses "
        "no operation",
    ),
}
