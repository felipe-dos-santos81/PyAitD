# SPDX-License-Identifier: GPL-2.0-only
from collections import deque
from functools import lru_cache
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from pathlib import Path
from weakref import WeakKeyDictionary

import numpy as np
import pygame

from PyAitD.app.config import (
    Control, REMAPPABLE_CONTROLS, Settings, default_settings, replace_binding,
)
from PyAitD.engine.effects import ChooseCharacter, FoundResult, OpenStartupMenu, OpenSystemMenu, ShowTitle
from PyAitD.render.background_export import (
    PORTRAIT_RECTS, READING_CLOSE_RECT, READING_NEXT_RECT, READING_PREV_RECT,
)
from PyAitD.render.render_options import RenderOptions, cycle_filter, cycle_scale, cycle_shading
from PyAitD.render.asset_resolver import AssetResolver
from PyAitD.engine.text import BookToken

GRAPHICS_ROWS = 3


def config_row_count():
    return 2 + len(REMAPPABLE_CONTROLS) + GRAPHICS_ROWS


class Command(Enum):
    UP = auto(); DOWN = auto(); LEFT = auto(); RIGHT = auto()
    ACCEPT = auto(); CANCEL = auto(); OPEN_INVENTORY = auto()
    TOGGLE_INPUT_MODE = auto()


@dataclass
class InputBuffer:
    held_joyd: int = 0
    action_held: bool = False
    pointer_held: bool = False
    pointer_touch: bool = False
    pointer_pos: tuple[int, int] | None = None
    focused: bool = True
    commands: deque = field(default_factory=deque)
    bindings: dict | None = None
    sticky_action: bool = False
    sticky_armed: bool = False
    action_pulse: bool = False
    # An accepted target click arms FITD's own action input for the next few
    # fixed ticks (mainLoop.cpp:87-101), because one tick of action ends before
    # the melee animation reaches its strike frame. It lives here rather than
    # in Game so every focus, modal and input-mode reset already clears it, and
    # so the simulation never learns that a mouse exists.
    mouse_attack_target: int | None = None
    mouse_attack_ticks: int = 0


_DIRECTION_CONTROL = {
    Control.UP: (Command.UP, 1), Control.DOWN: (Command.DOWN, 2),
    Control.LEFT: (Command.LEFT, 4), Control.RIGHT: (Command.RIGHT, 8),
}

_DEFAULT_CONTROL_BY_KEY = {
    pygame.K_UP: Control.UP, pygame.K_w: Control.UP,
    pygame.K_DOWN: Control.DOWN, pygame.K_s: Control.DOWN,
    pygame.K_LEFT: Control.LEFT, pygame.K_a: Control.LEFT,
    pygame.K_RIGHT: Control.RIGHT, pygame.K_d: Control.RIGHT,
    pygame.K_SPACE: Control.ACTION,
    pygame.K_RETURN: Control.INVENTORY_CONFIRM,
    pygame.K_i: Control.INVENTORY_CONFIRM,
    pygame.K_ESCAPE: Control.CANCEL,
    pygame.K_TAB: Control.TOGGLE_INPUT_MODE,
}


def canonical_key_name(key):
    name = pygame.key.name(key, use_compat=True)
    if not name or name == "unknown key":
        raise ValueError(f"pygame key {key} has no stable name")
    return name


def compile_bindings(settings):
    compiled = {}
    for control in Control:
        for name in settings.bindings[control.name]:
            try:
                code = pygame.key.key_code(name)
            except ValueError as exc:
                raise ValueError(f"unknown pygame key name {name!r}") from exc
            compiled[code] = control
    return compiled


def reset_input(state):
    state.held_joyd = 0
    state.action_held = False
    state.pointer_held = False
    state.pointer_touch = False
    state.pointer_pos = None
    state.sticky_armed = False
    state.action_pulse = False
    state.mouse_attack_target = None
    state.mouse_attack_ticks = 0
    state.commands.clear()


def configure_input(state, settings):
    state.bindings = compile_bindings(settings)
    state.sticky_action = settings.sticky_action
    reset_input(state)


def event_to_input(event, state, logical_pos=None):
    if event.type == pygame.QUIT:
        return False
    if event.type == pygame.WINDOWFOCUSLOST:
        reset_input(state)
        state.focused = False
        return True
    if event.type == pygame.WINDOWFOCUSGAINED:
        state.focused = True
        return True
    if event.type == pygame.MOUSEMOTION:
        state.pointer_touch = bool(getattr(event, "touch", False))
        state.pointer_pos = logical_pos
        return True
    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
        state.pointer_held = True
        state.pointer_touch = bool(getattr(event, "touch", False))
        state.pointer_pos = logical_pos
        return True
    if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
        state.pointer_held = False
        state.pointer_touch = False
        state.pointer_pos = None
        return True
    # bindings=None keeps the pre-settings defaults and never touches
    # pygame.key before initialization; a compiled table is used as-is, even
    # when intentionally empty.
    table = _DEFAULT_CONTROL_BY_KEY if state.bindings is None else state.bindings
    if event.type == pygame.KEYDOWN:
        repeated = bool(getattr(event, "repeat", False))
        control = table.get(event.key)
        if control in _DIRECTION_CONTROL:
            command, bit = _DIRECTION_CONTROL[control]
            state.held_joyd |= bit
            if not repeated:
                state.commands.append(command)
                if state.sticky_armed:
                    state.action_pulse = True
                    state.sticky_armed = False
        elif control is Control.ACTION:
            if state.sticky_action:
                if not repeated:
                    state.sticky_armed = True
                    state.commands.append(Command.ACCEPT)
            else:
                state.action_held = True
                if not repeated:
                    state.commands.append(Command.ACCEPT)
        elif not repeated and control is Control.INVENTORY_CONFIRM:
            state.commands.append(Command.OPEN_INVENTORY)
        elif not repeated and control is Control.CANCEL:
            state.commands.append(Command.CANCEL)
        elif not repeated and control is Control.TOGGLE_INPUT_MODE:
            state.commands.append(Command.TOGGLE_INPUT_MODE)
    elif event.type == pygame.KEYUP:
        control = table.get(event.key)
        if control in _DIRECTION_CONTROL:
            state.held_joyd &= ~_DIRECTION_CONTROL[control][1]
        elif control is Control.ACTION:
            state.action_held = False
    return True


@dataclass
class FoundPresenter:
    choice: FoundResult = FoundResult.TAKE
    hover: object | None = None


@dataclass
class InventoryPresenter:
    object_cursor: int = 0
    action_cursor: int = 0
    choosing_action: bool = False
    hover: object | None = None


@dataclass(frozen=True)
class InventoryResult:
    object_idx: int = -1
    action_text_id: int = -1
    cancelled: bool = False


@dataclass
class ReadingPresenter:
    page: int = 0
    hover: object | None = None


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
    hover: object | None = None


@dataclass(frozen=True)
class CharacterSelectResult:
    hero: int | None = None
    quit: bool = False


class SystemMenuPage(Enum):
    MAIN = auto()
    CONFIG = auto()
    KEY_PICK = auto()


# Mouse-only remap surface: every name round-trips through pygame.key.key_code
# and canonical_key_name, so a picked cell binds exactly like a physical press.
PICKABLE_KEYS = tuple(
    [chr(code) for code in range(ord("a"), ord("z") + 1)]
    + [str(digit) for digit in range(10)]
    + ["up", "down", "left", "right", "space", "return", "tab", "backspace",
       "left shift", "right shift", "left ctrl", "right ctrl", "left alt", "right alt"]
)
PICKABLE_KEY_LABELS = {
    "space": "spc", "return": "ret", "backspace": "bksp",
    "left shift": "lshift", "right shift": "rshift", "left ctrl": "lctrl",
    "right ctrl": "rctrl", "left alt": "lalt", "right alt": "ralt",
}


@dataclass
class SystemMenuPresenter:
    page: SystemMenuPage = SystemMenuPage.MAIN
    cursor: int = 0
    capture: str | None = None
    hover: object | None = None


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
    row_count = 3 if state.page is SystemMenuPage.MAIN else config_row_count()
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
            settings=replace(settings, sticky_action=not settings.sticky_action),
        )
    elif command is Command.ACCEPT and state.cursor > len(REMAPPABLE_CONTROLS):
        cycles = (cycle_scale, cycle_shading, cycle_filter)
        cycle = cycles[state.cursor - 1 - len(REMAPPABLE_CONTROLS)]
        return SystemMenuResult(settings=replace(settings, render=cycle(settings.render)))
    elif command is Command.ACCEPT:
        state.capture = REMAPPABLE_CONTROLS[state.cursor - 1].name
        state.page = SystemMenuPage.KEY_PICK
        state.hover = None
    return None


def capture_system_key(state, settings, key_name):
    """Finish a remap with a physical or picked key; ``escape`` cancels.

    Leaves the key picker either way; the configuration row that was being
    bound stays selected.
    """
    if state.capture is None:
        return None
    control = state.capture
    state.capture = None
    state.page = SystemMenuPage.CONFIG
    state.hover = None
    if key_name == "escape":
        return None
    return SystemMenuResult(settings=replace_binding(settings, Control[control], key_name))


def pick_system_key(state, settings, index):
    """Mouse route for the key picker: cell ``index`` binds, the last cell cancels."""
    name = "escape" if index >= len(PICKABLE_KEYS) else PICKABLE_KEYS[index]
    return capture_system_key(state, settings, name)


def effective_rects(
    rects, *, pad=2, minimum=12, bounds=pygame.Rect(0, 0, 320, 200),
):
    """Return forgiving, non-overlapping hit rectangles for visible targets.

    The input rectangles are presentation geometry and are never mutated. Each
    target is expanded around its original center, clamped to the logical
    frame, and then any expansion overlap between adjacent targets is divided
    at its midpoint. ``pygame.Rect`` keeps the right and bottom edges
    exclusive for the returned hit boxes as well.
    """
    visible = tuple(pygame.Rect(rect) for rect in rects)
    if not visible:
        return ()
    frame = pygame.Rect(bounds)
    hits = []
    for rect in visible:
        width = min(frame.width, max(rect.width + 2 * pad, minimum))
        height = min(frame.height, max(rect.height + 2 * pad, minimum))
        hit = pygame.Rect(
            rect.centerx - width // 2,
            rect.centery - height // 2,
            width,
            height,
        )
        hit.clamp_ip(frame)
        hits.append(hit)

    # Divide expanded overlap between geometric neighbours on a row or
    # column. Resolve the nearest neighbour on each side from geometry rather
    # than relying on the caller's tuple order; the result tuple still keeps
    # the caller's order.
    def _neighbor_pairs(horizontal):
        nearest = {}
        for first, first_visible in enumerate(visible):
            for second in range(first + 1, len(visible)):
                second_visible = visible[second]
                axis_delta = abs(
                    (first_visible.centerx if horizontal else first_visible.centery)
                    - (second_visible.centerx if horizontal else second_visible.centery)
                )
                other_delta = abs(
                    (first_visible.centery if horizontal else first_visible.centerx)
                    - (second_visible.centery if horizontal else second_visible.centerx)
                )
                if axis_delta == 0 or axis_delta < other_delta:
                    continue
                if horizontal:
                    overlaps_other = not (
                        first_visible.bottom <= second_visible.top
                        or second_visible.bottom <= first_visible.top
                    )
                    first_axis, second_axis = first_visible.centerx, second_visible.centerx
                else:
                    overlaps_other = not (
                        first_visible.right <= second_visible.left
                        or second_visible.right <= first_visible.left
                    )
                    first_axis, second_axis = first_visible.centery, second_visible.centery
                if not overlaps_other or first_axis == second_axis:
                    continue
                left, right = (first, second) if first_axis < second_axis else (second, first)
                distance = abs(first_axis - second_axis)
                for key, value in (((left, 1), (distance, right)), ((right, -1), (distance, left))):
                    previous = nearest.get(key)
                    if previous is None or value < previous:
                        nearest[key] = value
        return {(value[1], key[0]) if key[1] == -1 else (key[0], value[1])
                for key, value in nearest.items()}

    for horizontal in (True, False):
        pairs = sorted(_neighbor_pairs(horizontal))
        for first, second in pairs:
            first_visible, second_visible = visible[first], visible[second]
            if horizontal:
                if first_visible.left > second_visible.left:
                    first, second = second, first
                if hits[first].right > hits[second].left:
                    split = (hits[first].right + hits[second].left) // 2
                    hits[first].width = max(0, split - hits[first].left)
                    far_edge = hits[second].right
                    hits[second].x = split
                    hits[second].width = max(0, far_edge - split)
            else:
                if first_visible.top > second_visible.top:
                    first, second = second, first
                if hits[first].bottom > hits[second].top:
                    split = (hits[first].bottom + hits[second].top) // 2
                    hits[first].height = max(0, split - hits[first].top)
                    far_edge = hits[second].bottom
                    hits[second].y = split
                    hits[second].height = max(0, far_edge - split)
    return tuple(hits)


class PlayLayout:
    INVENTORY = pygame.Rect(4, 4, 28, 20)
    INVENTORY_HIT = effective_rects((INVENTORY,))[0]


class CharacterLayout:
    PORTRAITS = tuple(pygame.Rect(*rect) for rect in PORTRAIT_RECTS)
    PORTRAIT_HIT_ROWS = effective_rects(PORTRAITS)
    STORY = pygame.Rect(0, 0, 320, 200)


class SystemMenuLayout:
    MAIN_ROWS = tuple(pygame.Rect(48, 45 + i * 42, 224, 32) for i in range(3))
    CONFIG_ROWS = tuple(
        pygame.Rect(16, 4 + i * 16, 288, 16)
        for i in range(config_row_count())
    )
    # 8 columns x 7 rows of key cells under a one-line header, then a wide
    # Cancel button. The 4 px gaps absorb effective_rects' 2 px padding on
    # each side, so padded cells touch but never overlap -- including on the
    # diagonals and against the wide Cancel row, which the midpoint partition
    # does not cover.
    KEY_PICK_ROWS = tuple(
        pygame.Rect(10 + (i % 8) * 38, 22 + (i // 8) * 22, 34, 18)
        for i in range(len(PICKABLE_KEYS))
    ) + (pygame.Rect(10, 22 + 7 * 22, 300, 18),)

    @classmethod
    def rows(cls, page):
        if page is SystemMenuPage.MAIN:
            return cls.MAIN_ROWS
        if page is SystemMenuPage.CONFIG:
            return cls.CONFIG_ROWS
        return cls.KEY_PICK_ROWS

    @classmethod
    def hit_rows(cls, page):
        return effective_rects(cls.rows(page))


class ModalLayout:
    FOUND_LEAVE = pygame.Rect(28, 154, 120, 30)
    FOUND_TAKE = pygame.Rect(172, 154, 120, 30)
    INVENTORY_ROWS = tuple(pygame.Rect(24, 30 + i * 24, 272, 22) for i in range(5))
    # Pinned to background_export.READING_*_RECT (the same convention
    # CharacterLayout.PORTRAITS follows for PORTRAIT_RECTS) so the screen
    # guides for entries 6/7/8 can never drift from where these buttons draw.
    READING_PREV = pygame.Rect(*READING_PREV_RECT)
    READING_CLOSE = pygame.Rect(*READING_CLOSE_RECT)
    READING_NEXT = pygame.Rect(*READING_NEXT_RECT)
    FOUND_HIT_ROWS = effective_rects((FOUND_LEAVE, FOUND_TAKE))
    INVENTORY_HIT_ROWS = effective_rects(INVENTORY_ROWS)
    READING_HIT_ROWS = effective_rects((READING_PREV, READING_CLOSE, READING_NEXT))


class SettingsNoticeLayout:
    DISMISS = pygame.Rect(72, 154, 176, 34)
    DISMISS_HIT = effective_rects((DISMISS,))[0]


@lru_cache(maxsize=8)
def _font(size=16):
    if not pygame.font.get_init():
        pygame.font.init()
    return pygame.font.Font(None, size)


def transparent_canvas():
    """The 320x200 RGBA canvas presenters paint on: fully clear until drawn,
    so the renderer's UI/scene compositor only replaces the pixels a
    presenter actually touched."""
    return np.zeros((200, 320, 4), dtype=np.uint8)


def _to_surface(frame):
    frame = np.ascontiguousarray(frame)
    if frame.shape[2] == 3:
        return pygame.surfarray.make_surface(frame.swapaxes(0, 1))
    surface = pygame.Surface((frame.shape[1], frame.shape[0]), flags=pygame.SRCALPHA)
    pygame.surfarray.pixels3d(surface)[:] = frame[:, :, :3].swapaxes(0, 1)
    pygame.surfarray.pixels_alpha(surface)[:] = frame[:, :, 3].swapaxes(0, 1)
    return surface


def _to_frame(surface):
    rgb = pygame.surfarray.array3d(surface).swapaxes(0, 1)
    if surface.get_flags() & pygame.SRCALPHA:
        alpha = pygame.surfarray.array_alpha(surface).swapaxes(0, 1)
        return np.ascontiguousarray(np.dstack([rgb, alpha]))
    return np.ascontiguousarray(rgb)


# Per-resolver cache of the scaled 320x200 Surface for each ITD_RESS entry,
# so the character-select/STORY/reading screens (rendered every frame by
# shell.py's render loop) don't redo _to_surface + smoothscale from scratch
# at 60 Hz. Keyed weakly on the resolver so the cache dies with it; each
# entry's cache slot holds the pixels array alongside the surface (a strong
# reference) and is only reused when that pixels object is still the one
# AssetResolver.resource_screen returns for the entry -- guaranteed stable
# across calls for the same entry (test_resource_screen_override_is_used_at_
# any_size_and_cached), but invalidated by e.g. Assets.clear(). Comparing the
# held array by identity, rather than caching under some derived key like
# id(pixels), means a garbage-collected-and-reused id can never produce a
# false hit.
_SCREEN_SURFACE_CACHE = WeakKeyDictionary()


def screen_surface(resolver, entry):
    """An ITD_RESS full-screen resource as a 320x200 surface, cached per
    (resolver, entry). An override of any other size is smooth-scaled
    down/up here so every rect the callers blit over (portraits, text
    columns, cadre) stays in 320x200 space.
    ponytail: compositing at override resolution is the upgrade path.

    The returned Surface is SHARED across calls: callers that draw on it
    directly (blit, _button, draw_big_cadre...) must `.copy()` it first, or
    the drawing bleeds into every later call for that entry."""
    asset = resolver.resource_screen(entry)
    per_entry = _SCREEN_SURFACE_CACHE.setdefault(resolver, {})
    cached = per_entry.get(entry)
    if cached is not None and cached[0] is asset.pixels:
        return cached[1]
    surface = _to_surface(np.ascontiguousarray(asset.pixels))
    if surface.get_size() != (320, 200):
        surface = pygame.transform.smoothscale(surface, (320, 200))
    per_entry[entry] = (asset.pixels, surface)
    return surface


def _resolver_or_originals(assets, resolver):
    return resolver if resolver is not None else AssetResolver(assets, None)


def _button(surface, rect, label, selected=False, size=18):
    pygame.draw.rect(surface, (214, 190, 142) if selected else (78, 59, 46), rect, border_radius=3)
    pygame.draw.rect(surface, (245, 226, 178), rect, width=2, border_radius=3)
    glyph = _font(size).render(label, True, (20, 16, 12) if selected else (250, 242, 216))
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
    choice = presenter.hover if presenter.hover is not None else presenter.choice
    _button(surface, ModalLayout.FOUND_LEAVE, assets.system_text(21), choice is FoundResult.LEAVE)
    _button(surface, ModalLayout.FOUND_TAKE, assets.system_text(22), choice is FoundResult.TAKE)
    if effect.forced_refuse:
        warning = _font(16).render(assets.system_text(10), True, (255, 192, 128))
        surface.blit(warning, warning.get_rect(center=(160, 126)))
    return _to_frame(surface)


def render_picture(effect, assets, resolver=None):
    resolver = _resolver_or_originals(assets, resolver)
    return _to_frame(screen_surface(resolver, effect.resource_index))


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


def render_hit_feedback(frame, rects):
    """Outline supplied actor rectangles without reading simulation state."""
    if not rects:
        return frame
    surface = _to_surface(frame.copy())
    for rect in rects:
        target = pygame.Rect(rect)
        if target.width <= 0 or target.height <= 0:
            continue
        pygame.draw.rect(surface, (255, 255, 255), target.inflate(4, 4), width=2)
        pygame.draw.rect(surface, (255, 32, 32), target, width=2)
    return _to_frame(surface)


def render_settings_notice(frame, message):
    if message is None:
        return frame
    surface = _to_surface(frame.copy())
    shade = pygame.Surface((320, 200), flags=pygame.SRCALPHA)
    shade.fill((0, 0, 0, 190))
    surface.blit(shade, (0, 0))
    title = _font(20).render("Settings error", True, (255, 220, 170))
    surface.blit(title, title.get_rect(center=(160, 38)))
    lines = layout_book((BookToken("text", message),), _font(15), 276, 5)[0]
    for index, (text, _centered) in enumerate(lines):
        glyph = _font(15).render(text, True, (255, 255, 255))
        surface.blit(glyph, glyph.get_rect(center=(160, 65 + index * 16)))
    _button(surface, SettingsNoticeLayout.DISMISS, "Dismiss", selected=True)
    return _to_frame(surface)


def reading_pages(effect, assets):
    pages = assets.book_pages.get(effect.text_index)
    if pages is None:
        pages = layout_book(assets.book_tokens(effect.text_index), _font(16), 190, 8)
        assets.book_pages[effect.text_index] = pages
    return pages


def render_reading(effect, presenter, assets, resolver=None):
    resolver = _resolver_or_originals(assets, resolver)
    # screen_surface's Surface is shared/cached: copy before drawing on it.
    surface = screen_surface(resolver, {0: 6, 1: 7, 2: 8}[effect.kind]).copy()
    pages = reading_pages(effect, assets)
    y = 20
    font = _font(16)
    for text, centered in pages[presenter.page]:
        glyph = font.render(text, True, (43, 31, 22))
        x = 160 - glyph.get_width() // 2 if centered else 60
        surface.blit(glyph, (x, y))
        y += 16
    hover = presenter.hover
    _button(
        surface, ModalLayout.READING_PREV, "Previous",
        hover == ReadingResult(False, -1) if hover is not None else presenter.page > 0,
    )
    _button(
        surface, ModalLayout.READING_CLOSE, "Close",
        hover == ReadingResult(True) if hover is not None else True,
    )
    _button(
        surface, ModalLayout.READING_NEXT, "Next",
        hover == ReadingResult(False, 1) if hover is not None else presenter.page + 1 < len(pages),
    )
    return _to_frame(surface)


def render_inventory(presenter, assets, scene_frame, object_names, action_names):
    surface = _to_surface((scene_frame.astype("f4") * 0.45).astype(np.uint8))
    rows = action_names if presenter.choosing_action else object_names
    cursor = presenter.action_cursor if presenter.choosing_action else presenter.object_cursor
    selection = presenter.hover if presenter.hover is not None else cursor
    start = visible_start(cursor, len(rows))
    title_id = 200 if presenter.choosing_action else 20
    title = _font(20).render(assets.system_text(title_id), True, (255, 238, 198))
    surface.blit(title, title.get_rect(center=(160, 16)))
    for visible, rect in enumerate(ModalLayout.INVENTORY_ROWS):
        index = start + visible
        if index >= len(rows):
            break
        _button(surface, rect, rows[index], selected=index == selection)
    return _to_frame(surface)


def render_character_select(presenter, assets, resolver=None):
    # FITD character select: resource 10 background, cadre around the hovered
    # portrait (left choice 0 = Emily hero 1, right choice 1 = Carnby hero 0);
    # STORY copies the opposite half of resource 14 plus book text 20/21.
    resolver = _resolver_or_originals(assets, resolver)
    # screen_surface's Surface is shared/cached: copy before drawing on it.
    surface = screen_surface(resolver, 10).copy()
    base = surface.copy()
    choice = (presenter.hover if presenter.hover is not None
              and presenter.phase is CharacterPhase.PORTRAITS else presenter.choice)
    center = ((80, 100), (240, 100))[choice]
    draw_big_cadre(surface, assets.cadre_bank(), center, (160, 200))
    portrait = CharacterLayout.PORTRAITS[choice]
    surface.blit(base, portrait.topleft, portrait)
    if presenter.phase is CharacterPhase.PORTRAITS:
        return _to_frame(surface)
    intro = screen_surface(resolver, 14)
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
    if presenter.page is SystemMenuPage.KEY_PICK:
        return _render_key_picker(surface, presenter)
    if presenter.page is SystemMenuPage.MAIN:
        labels = ["Return to Game", "Configuration", "Quit"]
    else:
        labels = [f"Sticky Action: {'On' if settings.sticky_action else 'Off'}"]
        for control in REMAPPABLE_CONTROLS:
            labels.append(f"{control.name}: {', '.join(settings.bindings[control.name])}")
        labels.append(f"Scale: {settings.render.scale}x")
        labels.append(f"Shading: {settings.render.shading.title()}")
        labels.append(f"Filter: {settings.render.background_filter.title()}")
        labels.append("Back to Menu")
    selection = presenter.hover if presenter.hover is not None else presenter.cursor
    button_size = 13 if presenter.page is SystemMenuPage.CONFIG else 18
    rows = zip(SystemMenuLayout.rows(presenter.page), labels, strict=True)
    for index, (rect, label) in enumerate(rows):
        _button(surface, rect, label, selected=index == selection, size=button_size)
    return _to_frame(surface)


def _render_key_picker(surface, presenter):
    header = _font(14).render(
        f"{presenter.capture}: press a key or click one", True, (250, 242, 216),
    )
    surface.blit(header, header.get_rect(midtop=(160, 4)))
    labels = [PICKABLE_KEY_LABELS.get(name, name) for name in PICKABLE_KEYS] + ["Cancel"]
    for index, (rect, label) in enumerate(zip(SystemMenuLayout.KEY_PICK_ROWS, labels)):
        _button(surface, rect, label, selected=index == presenter.hover, size=12)
    return _to_frame(surface)


def render_game_over(canvas, scene_frame, ready):
    # LM_GAME_OVER's wall-clock wait (life.cpp:2438-2450) freezes the last PLAY
    # frame -- locked, this returns the caller's canvas untouched, byte-identical,
    # not recomposed, so the modal appears to hold the moment of death still.
    if not ready:
        return canvas
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
    if ModalLayout.FOUND_HIT_ROWS[0].collidepoint(pos):
        return FoundResult.LEAVE
    if ModalLayout.FOUND_HIT_ROWS[1].collidepoint(pos):
        return FoundResult.TAKE
    return None


def hit_test_character(pos, presenter):
    if presenter.phase is CharacterPhase.STORY:
        return 0 if CharacterLayout.STORY.collidepoint(pos) else None
    for choice, rect in enumerate(CharacterLayout.PORTRAIT_HIT_ROWS):
        if rect.collidepoint(pos):
            return choice
    return None


def hit_test_system_menu(pos, presenter):
    for index, rect in enumerate(SystemMenuLayout.hit_rows(presenter.page)):
        if rect.collidepoint(pos):
            return index
    return None


def hit_test_settings_notice(pos):
    return SettingsNoticeLayout.DISMISS_HIT.collidepoint(pos)


def hit_test_inventory(pos, presenter, object_ids, action_ids, *, preview=False):
    rows = action_ids if presenter.choosing_action else object_ids
    cursor = presenter.action_cursor if presenter.choosing_action else presenter.object_cursor
    start = visible_start(cursor, len(rows))
    for visible, rect in enumerate(ModalLayout.INVENTORY_HIT_ROWS):
        index = start + visible
        if index < len(rows) and rect.collidepoint(pos):
            if preview:
                return index
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
    title: "TitlePresenter" = None
    startup: "StartupMenuPresenter" = None
    booted_via_menu: bool = False
    settings: Settings = field(default_factory=default_settings)
    settings_path: Path | None = None
    settings_error: str | None = None
    settings_dirty: bool = False
    # The render options as last loaded from (or defaulted for) the settings
    # file, before any session-only CLI override was applied to `settings`.
    # A save writes this, with only the render fields the player actually
    # touched via a CONFIG menu cycle (`render_touched`) overlaid on top --
    # never a CLI-set value the player never saw a menu row for. See
    # __main__._save_session_settings.
    disk_render: RenderOptions = field(default_factory=RenderOptions)
    render_touched: frozenset = frozenset()
    pending_hero: int | None = None
    elapsed_ms: int = 0
    last_effect: object = field(default=None, repr=False)
    # PlayWorld(allowSystemMenu=0): while cutscene is True, input skips the
    # opening instead of routing to PLAY (mainLoop.cpp:71-89).
    cutscene: bool = False
    skip_cutscene: bool = False
    # --skip-intro: a development convenience (not FITD behaviour) that boots
    # the attic directly after character select, skipping the floor-7 opening.
    skip_intro: bool = False

    def __post_init__(self):
        from PyAitD.app.startup import StartupMenuPresenter, TitlePresenter
        if self.title is None:
            self.title = TitlePresenter()
        if self.startup is None:
            self.startup = StartupMenuPresenter()

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
        elif isinstance(effect, ShowTitle):
            from PyAitD.app.startup import TitlePresenter
            self.title = TitlePresenter()
        elif isinstance(effect, OpenStartupMenu):
            from PyAitD.app.startup import StartupMenuPresenter
            self.startup = StartupMenuPresenter()


def hit_test_reading(pos, page, page_count):
    if ModalLayout.READING_HIT_ROWS[1].collidepoint(pos):
        return ReadingResult(True)
    if page > 0 and ModalLayout.READING_HIT_ROWS[0].collidepoint(pos):
        return ReadingResult(False, -1)
    if page + 1 < page_count and ModalLayout.READING_HIT_ROWS[2].collidepoint(pos):
        return ReadingResult(False, 1)
    return None


_CURSOR_COLORS = {
    "walk": (200, 230, 170),
    "target": (255, 220, 130),
    "attack": (255, 96, 72),
    "push": (255, 178, 56),
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
    elif kind == "push":
        pygame.draw.line(surface, color, (x - 7, y), (x + 7, y), width=2)
        pygame.draw.line(surface, color, (x - 7, y), (x - 3, y - 3), width=2)
        pygame.draw.line(surface, color, (x - 7, y), (x - 3, y + 3), width=2)
        pygame.draw.line(surface, color, (x + 7, y), (x + 3, y - 3), width=2)
        pygame.draw.line(surface, color, (x + 7, y), (x + 3, y + 3), width=2)
    elif kind == "blocked":
        pygame.draw.line(surface, color, (x - 4, y - 4), (x + 4, y + 4))
        pygame.draw.line(surface, color, (x - 4, y + 4), (x + 4, y - 4))
    else:
        pygame.draw.circle(surface, color, (x, y), 4, width=1)
    return _to_frame(surface)
