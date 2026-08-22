# SPDX-License-Identifier: GPL-2.0-only
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto

import numpy as np
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


def reduce_reading(state, command, *, page_count):
    if command is Command.CANCEL:
        return ReadingResult(True)
    if command in (Command.LEFT, Command.UP):
        state.page = max(0, state.page - 1)
    elif command in (Command.RIGHT, Command.DOWN, Command.ACCEPT):
        if state.page + 1 < page_count:
            state.page += 1
        else:
            return ReadingResult(True)
    return None


class ModalLayout:
    FOUND_LEAVE = pygame.Rect(28, 154, 120, 30)
    FOUND_TAKE = pygame.Rect(172, 154, 120, 30)
    INVENTORY_ROWS = tuple(pygame.Rect(24, 30 + i * 24, 272, 22) for i in range(5))
    INVENTORY_ACTIONS = tuple(pygame.Rect(24, 30 + i * 24, 272, 22) for i in range(5))
    READING_PREV = pygame.Rect(12, 164, 96, 28)
    READING_CLOSE = pygame.Rect(114, 164, 96, 28)
    READING_NEXT = pygame.Rect(216, 164, 96, 28)


def _font(size=16):
    if not pygame.font.get_init():
        pygame.font.init()
    return pygame.font.Font(None, size)


def _to_surface(frame):
    return pygame.surfarray.make_surface(np.ascontiguousarray(frame).swapaxes(0, 1))


def _to_frame(surface):
    return np.ascontiguousarray(pygame.surfarray.array3d(surface).swapaxes(0, 1))


def _button(surface, rect, label, selected=False):
    pygame.draw.rect(surface, (214, 190, 142) if selected else (78, 59, 46), rect, border_radius=3)
    pygame.draw.rect(surface, (245, 226, 178), rect, width=2, border_radius=3)
    glyph = _font(18).render(label, True, (20, 16, 12) if selected else (250, 242, 216))
    surface.blit(glyph, glyph.get_rect(center=rect.center))


def layout_book(tokens, font, width, max_lines):
    pages, lines = [], []
    centered = False
    prefix = ""

    def push_line(text):
        nonlocal centered, prefix, lines
        raw = prefix + text
        prefix = ""
        words = raw.split()
        current = raw[:len(raw) - len(raw.lstrip(" "))]
        for word in words:
            separator = "" if not current or current.endswith(" ") else " "
            candidate = f"{current}{separator}{word}"
            if current.strip() and font.size(candidate)[0] > width:
                lines.append((current, centered))
                current = word
                if len(lines) == max_lines:
                    pages.append(tuple(lines)); lines = []
            else:
                current = candidate
        if current or text.endswith("\n"):
            lines.append((current, centered))
            if len(lines) == max_lines:
                pages.append(tuple(lines)); lines = []
        centered = False

    for token in tokens:
        if token.kind == "page":
            if lines:
                pages.append(tuple(lines)); lines = []
        elif token.kind == "center":
            centered = True
        elif token.kind == "tab":
            prefix += "    "
        elif token.kind == "number":
            prefix += token.text
        elif token.kind == "text":
            chunks = token.text.split("\n")
            for index, chunk in enumerate(chunks):
                if chunk or index < len(chunks) - 1:
                    push_line(chunk + ("\n" if index < len(chunks) - 1 else ""))
    if lines or not pages:
        pages.append(tuple(lines))
    return tuple(pages)


def render_found(effect, presenter, assets, found_name):
    surface = pygame.Surface((320, 200))
    surface.fill((17, 11, 9))
    title = _font(20).render(assets.system_text(20), True, (240, 220, 175))
    name = _font(18).render(found_name, True, (255, 255, 255))
    surface.blit(title, title.get_rect(center=(160, 34)))
    surface.blit(name, name.get_rect(center=(160, 78)))
    _button(surface, ModalLayout.FOUND_LEAVE, assets.system_text(21), presenter.choice is FoundResult.LEAVE)
    _button(surface, ModalLayout.FOUND_TAKE, assets.system_text(22), presenter.choice is FoundResult.TAKE)
    if effect.forced_refuse:
        warning = _font(16).render(assets.system_text(10), True, (255, 192, 128))
        surface.blit(warning, warning.get_rect(center=(160, 126)))
    return _to_frame(surface)


def render_picture(effect, assets):
    return np.ascontiguousarray(assets.resource_screen(effect.resource_index).copy())


def overlay_messages(frame, messages, assets):
    surface = _to_surface(frame.copy())
    y = 184
    font = _font(16)
    for message in messages:
        if message is None:
            continue
        glyph = font.render(assets.system_text(message.message_id), True, (255, 240, 185))
        shadow = font.render(assets.system_text(message.message_id), True, (0, 0, 0))
        rect = glyph.get_rect(center=(160, y))
        surface.blit(shadow, rect.move(1, 1))
        surface.blit(glyph, rect)
        y -= 16
    return _to_frame(surface)


def reading_pages(effect, assets):
    return layout_book(assets.book_tokens(effect.text_index), _font(16), 190, 8)


def render_reading(effect, presenter, assets):
    surface = _to_surface(assets.resource_screen({0: 6, 1: 7, 2: 8}[effect.kind]).copy())
    pages = reading_pages(effect, assets)
    presenter.page = min(presenter.page, len(pages) - 1)
    y = 20
    font = _font(16)
    for text, centered in pages[presenter.page]:
        glyph = font.render(text, True, (43, 31, 22))
        x = 160 - glyph.get_width() // 2 if centered else 60
        surface.blit(glyph, (x, y))
        y += 16
    _button(surface, ModalLayout.READING_PREV, "Previous", presenter.page > 0)
    _button(surface, ModalLayout.READING_CLOSE, "Close", True)
    _button(surface, ModalLayout.READING_NEXT, "Next", presenter.page + 1 < len(pages))
    return _to_frame(surface)


def render_inventory(object_ids, action_ids, presenter, assets, scene_frame,
                     object_names, action_names):
    surface = _to_surface((scene_frame.astype("f4") * 0.45).astype(np.uint8))
    rows = action_names if presenter.choosing_action else object_names
    cursor = presenter.action_cursor if presenter.choosing_action else presenter.object_cursor
    start = visible_start(cursor, len(rows))
    title_id = 200 if presenter.choosing_action else 20
    title = _font(20).render(assets.system_text(title_id), True, (255, 238, 198))
    surface.blit(title, title.get_rect(center=(160, 16)))
    for visible, rect in enumerate(ModalLayout.INVENTORY_ROWS):
        index = start + visible
        if index >= len(rows):
            break
        _button(surface, rect, rows[index], selected=index == cursor)
    return _to_frame(surface)


def visible_start(cursor, total):
    return min(max(0, cursor - 4), max(0, total - 5))


def hit_test_found(pos):
    if ModalLayout.FOUND_LEAVE.collidepoint(pos):
        return FoundResult.LEAVE
    if ModalLayout.FOUND_TAKE.collidepoint(pos):
        return FoundResult.TAKE
    return None


def hit_test_inventory(pos, presenter, object_ids, action_ids):
    rows = action_ids if presenter.choosing_action else object_ids
    cursor = presenter.action_cursor if presenter.choosing_action else presenter.object_cursor
    start = visible_start(cursor, len(rows))
    for visible, rect in enumerate(
        ModalLayout.INVENTORY_ACTIONS if presenter.choosing_action else ModalLayout.INVENTORY_ROWS
    ):
        index = start + visible
        if index < len(rows) and rect.collidepoint(pos):
            if presenter.choosing_action:
                presenter.action_cursor = index
                return InventoryResult(object_ids[presenter.object_cursor], action_ids[index])
            presenter.object_cursor = index
            presenter.choosing_action = True
            presenter.action_cursor = 0
            return None
    return None


@dataclass
class ModalSession:
    found: FoundPresenter = field(default_factory=FoundPresenter)
    inventory: InventoryPresenter = field(default_factory=InventoryPresenter)
    reading: ReadingPresenter = field(default_factory=ReadingPresenter)
    last_effect: object = field(default=None, repr=False)

    def reset_for(self, effect):
        if effect is self.last_effect:
            return
        self.last_effect = effect
        self.found = FoundPresenter(
            FoundResult.LEAVE if getattr(effect, "forced_refuse", False) else FoundResult.TAKE
        )
        self.inventory = InventoryPresenter()
        self.reading = ReadingPresenter()


def hit_test_reading(pos, page, page_count):
    if ModalLayout.READING_CLOSE.collidepoint(pos):
        return ReadingResult(True)
    if page > 0 and ModalLayout.READING_PREV.collidepoint(pos):
        return ReadingResult(False, -1)
    if page + 1 < page_count and ModalLayout.READING_NEXT.collidepoint(pos):
        return ReadingResult(False, 1)
    return None
