# SPDX-License-Identifier: GPL-2.0-only
from collections import deque
from functools import lru_cache
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

import numpy as np
import pygame

from PyAitD.config import (
    Control, REMAPPABLE_CONTROLS, Settings, default_settings, replace_binding,
)
from PyAitD.effects import ChooseCharacter, OpenSystemMenu


class Command(Enum):
    UP = auto(); DOWN = auto(); LEFT = auto(); RIGHT = auto()
    ACCEPT = auto(); CANCEL = auto(); OPEN_INVENTORY = auto()
    TOGGLE_INPUT_MODE = auto()


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
        elif not repeated and event.key == pygame.K_TAB:
            state.commands.append(Command.TOGGLE_INPUT_MODE)
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
    if command in (Command.UP, Command.DOWN):
        cursor = state.action_cursor if state.choosing_action else state.object_cursor
        if command is Command.UP:
            cursor = max(0, cursor - 1)
        else:
            cursor = min(len(action_ids if state.choosing_action else object_ids) - 1, cursor + 1)
        if state.choosing_action:
            state.action_cursor = cursor
        else:
            state.object_cursor = cursor
    elif command is Command.ACCEPT and not state.choosing_action:
        state.choosing_action = True
        state.action_cursor = 0
    elif command is Command.ACCEPT and action_ids:
        return InventoryResult(object_ids[state.object_cursor], action_ids[state.action_cursor])
    return None


def turn_page(state, delta, page_count):
    state.page = min(page_count - 1, max(0, state.page + delta))


def reduce_reading(state, command, *, page_count):
    if command is Command.CANCEL:
        return ReadingResult(True)
    if command in (Command.LEFT, Command.UP):
        turn_page(state, -1, page_count)
    elif command in (Command.RIGHT, Command.DOWN, Command.ACCEPT):
        if state.page + 1 >= page_count:
            return ReadingResult(True)
        turn_page(state, 1, page_count)
    return None


class CharacterPhase(Enum):
    PORTRAITS = auto()
    STORY = auto()


@dataclass
class CharacterSelectPresenter:
    choice: int = 0
    phase: CharacterPhase = CharacterPhase.PORTRAITS


@dataclass(frozen=True)
class CharacterSelectResult:
    hero: int | None = None
    quit: bool = False


class SystemMenuPage(Enum):
    MAIN = auto()
    CONFIG = auto()


@dataclass
class SystemMenuPresenter:
    page: SystemMenuPage = SystemMenuPage.MAIN
    cursor: int = 0
    capture: str | None = None


@dataclass(frozen=True)
class SystemMenuResult:
    settings: Settings | None = None
    close: bool = False
    quit: bool = False
    save: bool = False


def reduce_character_select(state, command):
    command = Command.ACCEPT if command is Command.OPEN_INVENTORY else command
    if command is Command.CANCEL:
        if state.phase is CharacterPhase.STORY:
            state.phase = CharacterPhase.PORTRAITS
            return None
        return CharacterSelectResult(quit=True)
    if state.phase is CharacterPhase.PORTRAITS:
        if command in (Command.LEFT, Command.UP):
            state.choice = 0
        elif command in (Command.RIGHT, Command.DOWN):
            state.choice = 1
        elif command is Command.ACCEPT:
            state.phase = CharacterPhase.STORY
        return None
    if command is Command.ACCEPT:
        return CharacterSelectResult(hero=1 if state.choice == 0 else 0)
    return None


def reduce_system_menu(state, command, settings):
    if state.capture is not None:
        return None
    command = Command.ACCEPT if command is Command.OPEN_INVENTORY else command
    row_count = 3 if state.page is SystemMenuPage.MAIN else 2 + len(REMAPPABLE_CONTROLS)
    if command is Command.UP:
        state.cursor = (state.cursor - 1) % row_count
    elif command is Command.DOWN:
        state.cursor = (state.cursor + 1) % row_count
    elif command is Command.CANCEL:
        if state.page is SystemMenuPage.CONFIG:
            state.page = SystemMenuPage.MAIN
            state.cursor = 0
            return SystemMenuResult(save=True)
        return SystemMenuResult(close=True, save=True)
    elif command is Command.ACCEPT and state.page is SystemMenuPage.MAIN:
        if state.cursor == 0:
            return SystemMenuResult(close=True, save=True)
        if state.cursor == 1:
            state.page = SystemMenuPage.CONFIG
            state.cursor = 0
        else:
            return SystemMenuResult(quit=True, save=True)
    elif (command is Command.ACCEPT and state.page is SystemMenuPage.CONFIG
          and state.cursor == row_count - 1):
        state.page = SystemMenuPage.MAIN
        state.cursor = 0
        return SystemMenuResult(save=True)
    elif command is Command.ACCEPT and state.cursor == 0:
        return SystemMenuResult(
            settings=Settings(dict(settings.bindings), not settings.sticky_action),
        )
    elif command is Command.ACCEPT:
        state.capture = REMAPPABLE_CONTROLS[state.cursor - 1].name
    return None


def capture_system_key(state, settings, key_name):
    if state.capture is None:
        return None
    if key_name == "escape":
        state.capture = None
        return None
    control = Control[state.capture]
    state.capture = None
    return SystemMenuResult(settings=replace_binding(settings, control, key_name))


class PlayLayout:
    INVENTORY = pygame.Rect(4, 4, 28, 20)


class CharacterLayout:
    PORTRAITS = (
        pygame.Rect(10, 10, 140, 181),
        pygame.Rect(170, 10, 140, 181),
    )
    STORY = pygame.Rect(0, 0, 320, 200)


class SystemMenuLayout:
    MAIN_ROWS = tuple(pygame.Rect(48, 45 + i * 42, 224, 32) for i in range(3))
    CONFIG_ROWS = tuple(
        pygame.Rect(16, 8 + i * 20, 288, 20)
        for i in range(2 + len(REMAPPABLE_CONTROLS))
    )

    @classmethod
    def rows(cls, page):
        return cls.MAIN_ROWS if page is SystemMenuPage.MAIN else cls.CONFIG_ROWS


class ModalLayout:
    FOUND_LEAVE = pygame.Rect(28, 154, 120, 30)
    FOUND_TAKE = pygame.Rect(172, 154, 120, 30)
    INVENTORY_ROWS = tuple(pygame.Rect(24, 30 + i * 24, 272, 22) for i in range(5))
    READING_PREV = pygame.Rect(12, 164, 96, 28)
    READING_CLOSE = pygame.Rect(114, 164, 96, 28)
    READING_NEXT = pygame.Rect(216, 164, 96, 28)


@lru_cache(maxsize=8)
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


def draw_big_cadre(surface, sprites, center, size):
    # FITD AffBigCadre placement (FitdLib/aitdBox.cpp:92-178); pygame clips the
    # full-screen cadre at the surface edge, matching FITD's 320x200 SetClip.
    x, y = center
    width, height = size
    left, top = x - width // 2, y - height // 2
    right, bottom = x + width // 2, y + height // 2
    sprite = tuple(_to_surface(image) for image in sprites)
    current_x, current_y = left, top
    surface.blit(sprite[0], (current_x, current_y))
    while True:
        current_x += 20
        if right - 20 <= current_x:
            break
        surface.blit(sprite[4], (current_x, current_y))
    surface.blit(sprite[1], (current_x, current_y))
    current_x = left
    while True:
        current_y += 20
        if bottom - 20 <= current_y:
            break
        surface.blit(sprite[6], (current_x, current_y))
    current_x, current_y = right - 8, top + 20
    while bottom - 20 > current_y:
        surface.blit(sprite[7], (current_x, current_y))
        current_y += 20
    current_x = left
    surface.blit(sprite[2], (current_x, current_y))
    while True:
        current_x += 20
        if right - 20 <= current_x:
            break
        surface.blit(sprite[5], (current_x, current_y + 12))
    surface.blit(sprite[3], (current_x, current_y))
    surface.blit(sprite[8], (x - 20, current_y + 12))
    interior = pygame.Rect(left + 8, top + 8, width - 16, height - 16)
    surface.fill((0, 0, 0), interior)
    return interior


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
    if all(message is None for message in messages):
        return frame
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


def render_play_hud(frame, *, inventory_available):
    if not inventory_available:
        return frame
    surface = _to_surface(frame.copy())
    _button(surface, PlayLayout.INVENTORY, "INV", selected=True)
    return _to_frame(surface)


def reading_pages(effect, assets):
    pages = assets.book_pages.get(effect.text_index)
    if pages is None:
        pages = layout_book(assets.book_tokens(effect.text_index), _font(16), 190, 8)
        assets.book_pages[effect.text_index] = pages
    return pages


def render_reading(effect, presenter, assets):
    surface = _to_surface(assets.resource_screen({0: 6, 1: 7, 2: 8}[effect.kind]).copy())
    pages = reading_pages(effect, assets)
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


def render_inventory(presenter, assets, scene_frame, object_names, action_names):
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


def render_character_select(presenter, assets):
    # FITD character select: resource 10 background, cadre around the hovered
    # portrait (left choice 0 = Emily hero 1, right choice 1 = Carnby hero 0);
    # STORY copies the opposite half of resource 14 plus book text 20/21.
    base = assets.resource_screen(10)
    surface = _to_surface(base.copy())
    center = ((80, 100), (240, 100))[presenter.choice]
    draw_big_cadre(surface, assets.cadre_bank(), center, (160, 200))
    portrait = CharacterLayout.PORTRAITS[presenter.choice]
    surface.blit(_to_surface(base[portrait.top:portrait.bottom,
                                  portrait.left:portrait.right]), portrait.topleft)
    if presenter.phase is CharacterPhase.PORTRAITS:
        return _to_frame(surface)
    intro = _to_surface(assets.resource_screen(14))
    if presenter.choice == 0:
        surface.blit(intro, (160, 0), pygame.Rect(160, 0, 160, 200))
        entry, text_x = 21, 165
    else:
        surface.blit(intro, (0, 0), pygame.Rect(0, 0, 160, 200))
        entry, text_x = 20, 5
    font = _font(15)
    page = layout_book(assets.book_tokens(entry), font, 150, 12)[0]
    y = 5
    for text, centered in page:
        glyph = font.render(text, True, (43, 31, 22))
        x = text_x + (150 - glyph.get_width()) // 2 if centered else text_x
        surface.blit(glyph, (x, y))
        y += 15
    return _to_frame(surface)


def render_system_menu(presenter, settings, assets):
    surface = pygame.Surface((320, 200))
    draw_big_cadre(surface, assets.cadre_bank(), (160, 100), (320, 200))
    if presenter.page is SystemMenuPage.MAIN:
        labels = ["Return to Game", "Configuration", "Quit"]
    else:
        labels = [f"Sticky Action: {'On' if settings.sticky_action else 'Off'}"]
        for control in REMAPPABLE_CONTROLS:
            labels.append(f"{control.name}: {', '.join(settings.bindings[control.name])}")
        labels.append("Back to Menu")
        if presenter.capture is not None:
            labels[presenter.cursor] = f"{presenter.capture}: press a key..."
    for index, (rect, label) in enumerate(zip(SystemMenuLayout.rows(presenter.page), labels)):
        _button(surface, rect, label, selected=index == presenter.cursor)
    return _to_frame(surface)


def render_game_over(scene_frame, ready):
    # LM_GAME_OVER's wall-clock wait (life.cpp:2438-2450) freezes the last PLAY
    # frame -- locked, this returns the caller's frame untouched, byte-identical,
    # not recomposed, so the modal appears to hold the moment of death still.
    if not ready:
        return scene_frame
    surface = _to_surface(scene_frame.copy())
    shade = pygame.Surface((320, 200), flags=pygame.SRCALPHA)
    shade.fill((0, 0, 0, 170))
    surface.blit(shade, (0, 0))
    title = _font(40).render("Game Over", True, (255, 238, 198))
    prompt = _font(18).render("Click to restart", True, (255, 255, 255))
    surface.blit(title, title.get_rect(center=(160, 82)))
    surface.blit(prompt, prompt.get_rect(center=(160, 126)))
    return _to_frame(surface)


def visible_start(cursor, total):
    return min(max(0, cursor - 4), max(0, total - 5))


def hit_test_found(pos):
    if ModalLayout.FOUND_LEAVE.collidepoint(pos):
        return FoundResult.LEAVE
    if ModalLayout.FOUND_TAKE.collidepoint(pos):
        return FoundResult.TAKE
    return None


def hit_test_character(pos, presenter):
    if presenter.phase is CharacterPhase.STORY:
        return 0 if CharacterLayout.STORY.collidepoint(pos) else None
    for choice, rect in enumerate(CharacterLayout.PORTRAITS):
        if rect.collidepoint(pos):
            return choice
    return None


def hit_test_system_menu(pos, presenter):
    for index, rect in enumerate(SystemMenuLayout.rows(presenter.page)):
        if rect.collidepoint(pos):
            return index
    return None


def hit_test_inventory(pos, presenter, object_ids, action_ids):
    rows = action_ids if presenter.choosing_action else object_ids
    cursor = presenter.action_cursor if presenter.choosing_action else presenter.object_cursor
    start = visible_start(cursor, len(rows))
    for visible, rect in enumerate(ModalLayout.INVENTORY_ROWS):
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
    character: CharacterSelectPresenter = field(default_factory=CharacterSelectPresenter)
    system_menu: SystemMenuPresenter = field(default_factory=SystemMenuPresenter)
    settings: Settings = field(default_factory=default_settings)
    settings_path: Path | None = None
    settings_error: str | None = None
    settings_dirty: bool = False
    pending_hero: int | None = None
    elapsed_ms: int = 0
    last_effect: object = field(default=None, repr=False)

    def reset_for(self, effect):
        if effect is self.last_effect:
            return
        self.last_effect = effect
        self.elapsed_ms = 0
        self.found = FoundPresenter(
            FoundResult.LEAVE if getattr(effect, "forced_refuse", False) else FoundResult.TAKE
        )
        self.inventory = InventoryPresenter()
        self.reading = ReadingPresenter()
        # shell presenters reset only when their own effect is (re)observed;
        # settings fields belong to the application session, never to an effect
        if isinstance(effect, ChooseCharacter):
            self.character = CharacterSelectPresenter()
        elif isinstance(effect, OpenSystemMenu):
            self.system_menu = SystemMenuPresenter()


def hit_test_reading(pos, page, page_count):
    if ModalLayout.READING_CLOSE.collidepoint(pos):
        return ReadingResult(True)
    if page > 0 and ModalLayout.READING_PREV.collidepoint(pos):
        return ReadingResult(False, -1)
    if page + 1 < page_count and ModalLayout.READING_NEXT.collidepoint(pos):
        return ReadingResult(False, 1)
    return None


_CURSOR_COLORS = {
    "walk": (200, 230, 170),
    "target": (255, 220, 130),
    "attack": (255, 96, 72),
    "inventory": (120, 210, 255),
    "blocked": (190, 90, 80),
}


def render_cursor(frame, logical_pos, kind):
    """Draw the pick cursor. Pure presentation: never touches world state."""
    if logical_pos is None:
        return frame
    surface = _to_surface(frame.copy())
    color = _CURSOR_COLORS.get(kind, _CURSOR_COLORS["walk"])
    x, y = int(logical_pos[0]), int(logical_pos[1])
    if kind == "inventory":
        pygame.draw.rect(surface, color, pygame.Rect(x - 5, y - 4, 11, 9), width=2)
        pygame.draw.line(surface, color, (x - 2, y - 6), (x + 2, y - 6), width=2)
    elif kind == "attack":
        pygame.draw.circle(surface, color, (x, y), 6, width=1)
        pygame.draw.line(surface, color, (x - 8, y), (x + 8, y), width=1)
        pygame.draw.line(surface, color, (x, y - 8), (x, y + 8), width=1)
    elif kind == "target":
        pygame.draw.rect(surface, color, pygame.Rect(x - 5, y - 5, 11, 11), width=1)
    elif kind == "blocked":
        pygame.draw.line(surface, color, (x - 4, y - 4), (x + 4, y + 4))
        pygame.draw.line(surface, color, (x - 4, y + 4), (x + 4, y - 4))
    else:
        pygame.draw.circle(surface, color, (x, y), 4, width=1)
    return _to_frame(surface)
