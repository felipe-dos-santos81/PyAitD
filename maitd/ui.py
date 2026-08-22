# SPDX-License-Identifier: GPL-2.0-only
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto

import pygame


class Command(Enum):
    UP = auto(); DOWN = auto(); LEFT = auto(); RIGHT = auto()
    ACCEPT = auto(); CANCEL = auto(); OPEN_INVENTORY = auto()


@dataclass
class InputBuffer:
    held_joyd: int = 0
    action_held: bool = False
    focused: bool = True
    commands: deque = field(default_factory=deque)


_DIRECTION = {
    pygame.K_UP: (Command.UP, 1), pygame.K_w: (Command.UP, 1),
    pygame.K_DOWN: (Command.DOWN, 2), pygame.K_s: (Command.DOWN, 2),
    pygame.K_LEFT: (Command.LEFT, 4), pygame.K_a: (Command.LEFT, 4),
    pygame.K_RIGHT: (Command.RIGHT, 8), pygame.K_d: (Command.RIGHT, 8),
}


def event_to_input(event, state):
    if event.type == pygame.QUIT:
        return False
    if event.type == pygame.WINDOWFOCUSLOST:
        state.held_joyd = 0
        state.action_held = False
        state.focused = False
        state.commands.clear()
    elif event.type == pygame.WINDOWFOCUSGAINED:
        state.focused = True
    elif event.type == pygame.KEYDOWN:
        repeated = bool(getattr(event, "repeat", False))
        if event.key in _DIRECTION:
            command, bit = _DIRECTION[event.key]
            state.held_joyd |= bit
            if not repeated:
                state.commands.append(command)
        elif event.key == pygame.K_SPACE:
            state.action_held = True
            if not repeated:
                state.commands.append(Command.ACCEPT)
        elif not repeated and event.key in (pygame.K_RETURN, pygame.K_i):
            state.commands.append(Command.OPEN_INVENTORY)
        elif not repeated and event.key == pygame.K_ESCAPE:
            state.commands.append(Command.CANCEL)
    elif event.type == pygame.KEYUP:
        if event.key in _DIRECTION:
            state.held_joyd &= ~_DIRECTION[event.key][1]
        elif event.key == pygame.K_SPACE:
            state.action_held = False
    return True


class FoundResult(Enum):
    TAKE = auto()
    LEAVE = auto()


@dataclass
class FoundPresenter:
    choice: FoundResult = FoundResult.TAKE


@dataclass
class InventoryPresenter:
    object_cursor: int = 0
    action_cursor: int = 0
    choosing_action: bool = False


@dataclass(frozen=True)
class InventoryResult:
    object_idx: int = -1
    action_text_id: int = -1
    cancelled: bool = False


@dataclass
class ReadingPresenter:
    page: int = 0
    elapsed_ms: int = 0


@dataclass(frozen=True)
class ReadingResult:
    dismissed: bool
    page_delta: int = 0


def reduce_found(state, command, *, forced_refuse):
    if forced_refuse:
        state.choice = FoundResult.LEAVE
    elif command is Command.LEFT:
        state.choice = FoundResult.LEAVE
    elif command is Command.RIGHT:
        state.choice = FoundResult.TAKE
    if command is Command.CANCEL:
        return FoundResult.LEAVE
    if command is Command.ACCEPT:
        return state.choice
    return None


def reduce_inventory(state, command, *, object_ids, action_ids):
    if command is Command.CANCEL:
        if state.choosing_action:
            state.choosing_action = False
            state.action_cursor = 0
            return None
        return InventoryResult(cancelled=True)
    if not object_ids:
        return InventoryResult(cancelled=True)
    if command is Command.UP:
        field_name = "action_cursor" if state.choosing_action else "object_cursor"
        setattr(state, field_name, max(0, getattr(state, field_name) - 1))
    elif command is Command.DOWN:
        field_name = "action_cursor" if state.choosing_action else "object_cursor"
        limit = len(action_ids) - 1 if state.choosing_action else len(object_ids) - 1
        setattr(state, field_name, min(limit, getattr(state, field_name) + 1))
    elif command is Command.ACCEPT and not state.choosing_action:
        state.choosing_action = True
        state.action_cursor = 0
    elif command is Command.ACCEPT and action_ids:
        return InventoryResult(object_ids[state.object_cursor], action_ids[state.action_cursor])
    return None
