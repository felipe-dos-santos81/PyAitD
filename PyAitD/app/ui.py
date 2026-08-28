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
from PyAitD.render.render_options import (
    RenderOptions, cycle_filter, cycle_lighting, cycle_msaa, cycle_realism, cycle_scale, cycle_shading,
)
from PyAitD.render.asset_resolver import AssetResolver
from PyAitD.engine.text import BookToken

GRAPHICS_ROWS = 6          # rows on the Graphics page above Back, in GRAPHICS_CYCLES order


def config_row_count():
    # Sticky Action, one row per remappable control, "Graphics...", "Back to Menu"
    return 3 + len(REMAPPABLE_CONTROLS)


def graphics_row_count():
    return GRAPHICS_ROWS + 1   # plus Back


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
    # Held pointer follow: the last (dest_x, dest_z, room, object_idx) the
    # shell issued as an intent during this hold. shell.follow_pointer
    # re-issues only when the resolution differs, which is also the one-shot
    # latch after an arrival. Lives here so every reset_input seam clears it.
    follow_last: tuple | None = None
    # The logical pixel follow_last was resolved at. shell.follow_pointer
    # re-resolves only when the pointer has moved off it, so a camera cut with
    # a still hand cannot retarget: the same pixel means a different world
    # point under every camera, and a cut is not a gesture the player made.
    # None means "resolve on the next frame regardless" -- what a floor change
    # leaves behind, its old destination being an index into the old floor.
    follow_pos: tuple[int, int] | None = None
    # True once this hold's press resolved to anything other than walk/target
    # (attack, inventory, push): the spec forbids resuming a follow on that
    # hold even after the underlying latch (mouse_attack_target, a push's
    # requires_hold intent) dies mid-hold. Cleared alongside follow_last on
    # release, so a fresh press is what restarts the follow.
    follow_spent: bool = False
    # A press landing within DOUBLE_PRESS_TICKS of the previous one runs
    # instead of walks, the mouse's answer to FITD's double-tap forward
    # (tracks._process_track_manual). Cleared by reset_input like every other
    # hold state, so a run never outlives the hold that started it.
    pointer_run: bool = False
    last_press_tick: int | None = None


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


# How long after a press a second one still reads as a double press, in game
# ticks (50Hz, so 25 is half a second). Deliberately NOT the keyboard's
# tracks.DOUBLE_TAP_TICKS, though the two gestures mean the same thing: a
# double tap on a held movement key is a fast repeat, while a double click is
# one motion of one finger that every desktop times at around half a second
# -- macOS defaults to 500ms. Sharing the keyboard's 10 ticks put the window
# under 180ms, which is quicker than most people can click twice, so the
# gesture almost never fired.
#
# The unit is still game ticks rather than wall-clock milliseconds, because
# the tick clock stops while a modal has the game paused: a press before the
# inventory and one after it are never a double press, however long the
# player spent in there.
DOUBLE_PRESS_TICKS = 25


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
    state.follow_last = None
    state.follow_pos = None
    state.follow_spent = False
    state.pointer_run = False
    state.last_press_tick = None
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
    GRAPHICS = auto()
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


# One cycle per Graphics-page row above Back; graphics_labels draws them in
# the same order, and tests pin that the two never drift apart.
GRAPHICS_CYCLES = (cycle_scale, cycle_shading, cycle_filter, cycle_lighting, cycle_msaa, cycle_realism)


def _leave_graphics(state):
    state.page = SystemMenuPage.CONFIG
    state.cursor = config_row_count() - 2   # back on the Graphics... row
    state.hover = None


def reduce_system_menu(state, command, settings):
    if state.capture is not None:
        return None
    command = Command.ACCEPT if command is Command.OPEN_INVENTORY else command
    if state.page is SystemMenuPage.MAIN:
        row_count = 3
    elif state.page is SystemMenuPage.GRAPHICS:
        row_count = graphics_row_count()
    else:
        row_count = config_row_count()
    if command is Command.UP:
        state.cursor = (state.cursor - 1) % row_count
    elif command is Command.DOWN:
        state.cursor = (state.cursor + 1) % row_count
    elif command is Command.CANCEL:
        if state.page is SystemMenuPage.GRAPHICS:
            _leave_graphics(state)
            return SystemMenuResult(save=True)
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
    elif command is Command.ACCEPT and state.page is SystemMenuPage.GRAPHICS:
        if state.cursor == row_count - 1:
            _leave_graphics(state)
            return SystemMenuResult(save=True)
        cycle = GRAPHICS_CYCLES[state.cursor]
        return SystemMenuResult(settings=replace(settings, render=cycle(settings.render)))
    elif (command is Command.ACCEPT and state.page is SystemMenuPage.CONFIG
          and state.cursor == row_count - 1):
        state.page = SystemMenuPage.MAIN
        state.cursor = 0
        return SystemMenuResult(save=True)
    elif command is Command.ACCEPT and state.cursor == row_count - 2:
        # the Graphics... row, just above Back
        state.page = SystemMenuPage.GRAPHICS
        state.cursor = 0
        state.hover = None
    elif command is Command.ACCEPT and state.cursor == 0:
        return SystemMenuResult(
            settings=replace(settings, sticky_action=not settings.sticky_action),
        )
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
    # anchor for the keyboard-mode label; not a mouse target, so it takes no
    # effective rect and never partitions against INVENTORY_HIT
    MODE_LABEL = (160, 4)


class CharacterLayout:
    PORTRAITS = tuple(pygame.Rect(*rect) for rect in PORTRAIT_RECTS)
    PORTRAIT_HIT_ROWS = effective_rects(PORTRAITS)
    STORY = pygame.Rect(0, 0, 320, 200)


class SystemMenuLayout:
    MAIN_ROWS = tuple(pygame.Rect(48, 45 + i * 42, 224, 32) for i in range(3))
    # 15 rows at a 13 px pitch from y=2 ends at y=197. The 14 px pitch fitted
    # exactly 14 rows and had no room for the Realism row. Rows stay >= 13 px
    # tall, so effective_rects' 12x12 minimum target contract still holds.
    CONFIG_ROWS = tuple(
        pygame.Rect(16, 2 + i * 13, 288, 13)
        for i in range(config_row_count())
    )
    # graphics_row_count() rows at a 22 px pitch, 20 px tall: the page is
    # not squeezed the way CONFIG's 13 px rows are, and ends at y=186.
    GRAPHICS_PAGE_ROWS = tuple(
        pygame.Rect(16, 12 + i * 22, 288, 20)
        for i in range(graphics_row_count())
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
        if page is SystemMenuPage.GRAPHICS:
            return cls.GRAPHICS_PAGE_ROWS
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


def text_size(label, size):
    """A label's logical width and height.

    Measured at scale 1 rather than by dividing a scaled measurement, so line
    breaking is bit-identical at every scale: a book that re-flowed when the
    window resized would change how many pages it has. That independence is
    why this is a module function and not a UIPainter method -- the callers
    that only measure (page counts, wrapping) have no painter, and building
    one to reach a measurement that ignores it only obscured that.
    """
    return _font(size).size(label)


def transparent_canvas():
    """A fully clear 320x200 RGBA array: the golden "nothing was painted"
    frame the tests compare a scale-1 `UIPainter.to_frame()` against.

    Presenters paint on a `UIPainter`, not on this; it survives only as that
    comparison value (test_ui_render, test_play_loop, test_render,
    test_runtime_modes, test_modal_results), and as the shape/dtype the UI
    canvas the compositor blends is defined to have.
    """
    return np.zeros((200, 320, 4), dtype=np.uint8)


class UIPainter:
    """The canvas presenters paint on, in logical 320x200 coordinates.

    The only object that knows the UI's pixel scale. Presenters keep
    authoring against the same 320x200 grid the hit tests use -- every
    PlayLayout/ModalLayout rect is expressed there and is shared with
    `hit_test_*` -- while the surface underneath is as large as the window.
    Drawing and picking a widget in two different coordinate systems is the
    defect this exists to prevent.

    At scale 1 every method must produce exactly what the old
    surface-per-presenter code produced: the existing render tests assert
    those pixels and are what makes this conversion safe.
    """

    def __init__(self, scale=1.0, *, fill=None):
        self.scale = float(scale)
        self.surface = pygame.Surface(self.size, flags=pygame.SRCALPHA)
        if fill is not None:
            self.surface.fill(fill)

    @property
    def size(self):
        return (round(320 * self.scale), round(200 * self.scale))

    def _pt(self, point):
        return (round(point[0] * self.scale), round(point[1] * self.scale))

    def _rect(self, rect):
        rect = pygame.Rect(rect)
        left, top = self._pt(rect.topleft)
        right, bottom = self._pt(rect.bottomright)
        return pygame.Rect(left, top, right - left, bottom - top)

    def _length(self, value):
        """A scaled length that never rounds away to nothing: a hairline, a
        radius or a font size that reached 0 would vanish rather than shrink."""
        return max(1, round(value * self.scale))

    def _width(self, width):
        # 0 means "filled" to pygame and must stay 0; every other width is an
        # ordinary length and keeps at least its one pixel
        return 0 if width == 0 else self._length(width)

    def rect(self, colour, rect, width=0, border_radius=0):
        pygame.draw.rect(
            self.surface, colour, self._rect(rect), width=self._width(width),
            border_radius=round(border_radius * self.scale),
        )

    def line(self, colour, start, end, width=1):
        pygame.draw.line(
            self.surface, colour, self._pt(start), self._pt(end),
            width=self._width(width),
        )

    def circle(self, colour, centre, radius, width=0):
        pygame.draw.circle(
            self.surface, colour, self._pt(centre),
            self._length(radius), width=self._width(width),
        )

    def shade(self, colour):
        """A full-canvas wash, the scaled form of blitting a filled SRCALPHA
        surface over the whole 320x200 frame."""
        wash = pygame.Surface(self.size, flags=pygame.SRCALPHA)
        wash.fill(colour)
        self.surface.blit(wash, (0, 0))

    def text(self, label, size, colour, *, center=None, topleft=None, midtop=None,
             centered_in=None):
        """Draw `label`, anchoring the SCALED glyph.

        Every anchor but `topleft` positions the glyph by measuring the
        surface actually rendered at this scale. Callers must not measure
        with `text_size` (a scale-1 measurement, see there) and then anchor
        by `topleft`: pygame's font metrics are not linear in size, so the
        width measured is not the width drawn and the line lands off centre
        at every scale above 1 -- a centred book line missed by 4.5 logical
        pixels at scale 4.

        `centered_in` is a logical rectangle the glyph is centred inside
        horizontally, its top on the rectangle's top. It exists for the two
        book columns whose own arithmetic was `left + (width - measured) //
        2`: centring inside the scaled column reproduces that expression
        exactly at scale 1 while staying correct above it, where anchoring
        on the column's midpoint would round the other way and move the
        scale-1 pixels.
        """
        glyph = _font(self._length(size)).render(label, True, colour)
        if center is not None:
            rect = glyph.get_rect(center=self._pt(center))
        elif midtop is not None:
            rect = glyph.get_rect(midtop=self._pt(midtop))
        elif centered_in is not None:
            column = self._rect(centered_in)
            rect = glyph.get_rect(topleft=(
                column.left + (column.width - glyph.get_width()) // 2, column.top,
            ))
        else:
            rect = glyph.get_rect(topleft=self._pt(topleft))
        self.surface.blit(glyph, rect)

    def text_size(self, label, size):
        """Logical width and height, for a caller that already holds a
        painter. Scale-independent -- see `text_size`."""
        return text_size(label, size)

    def blit(self, surface, logical_dest, area=None):
        """Blit a surface that is ALREADY at canvas scale, positioning it by
        logical coordinates. `area` is a logical sub-rect of the source."""
        self.surface.blit(
            surface, self._pt(logical_dest),
            None if area is None else self._rect(area),
        )

    def sprite(self, source, logical_dest):
        """Blit logical-size art at the logical rectangle it occupies.

        The destination is `_rect` of that logical rectangle -- the same
        conversion every other primitive uses -- so the art lands exactly
        where the geometry says. Scaling to it is `pygame.transform.scale`,
        which is nearest-neighbour, so pixel art stays blocky: at an integer
        scale each source pixel is an exact NxN block (bit-identical to
        scaling by a rounded factor, which is what scale 1 and scale 4 pin),
        and at a fractional one the blocks are merely uneven.

        Scaling the art by `round(scale)` instead used to shrink it against
        its own destination: at scale 2.5 a full-frame sprite covered 640x400
        of an 800x500 canvas, leaving the last fifth of the screen showing
        whatever was underneath.
        """
        surface = source if isinstance(source, pygame.Surface) else _to_surface(source)
        dest = self._rect(pygame.Rect(logical_dest, surface.get_size()))
        if dest.size != surface.get_size():
            surface = pygame.transform.scale(surface, dest.size)
        self.surface.blit(surface, dest.topleft)

    def to_frame(self):
        """The canvas as a (h, w, 4) uint8 array.

        The numpy contract the software compositor (render.composite_ui) and
        the render tests are written against. `to_bytes` is the same pixels
        for a caller that only needs to upload them; prefer it on the hot
        path -- this round trip costs 18.6 ms at 1280x800 against a 16.7 ms
        frame budget, and tobytes costs 0.7 ms.
        """
        return _to_frame(self.surface)

    def to_bytes(self):
        """The canvas as packed RGBA bytes, row-major top-down.

        Byte-for-byte `to_frame().tobytes()` (pinned by
        test_to_bytes_matches_the_numpy_round_trip), without building the
        intermediate arrays: `Renderer.present`'s GL path only ever wanted
        these bytes to hand to a texture.
        """
        return pygame.image.tobytes(self.surface, "RGBA")


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


# Per-resolver cache of the scaled Surface for each (ITD_RESS entry, target
# size), so the character-select/STORY/reading screens (rendered every frame
# by shell.py's render loop) don't redo _to_surface + scale from scratch at
# 60 Hz. Keyed weakly on the resolver so the cache dies with it; each
# (entry, size) cache slot holds the pixels array alongside the surface (a
# strong reference) and is only reused when that pixels object is still the
# one AssetResolver.resource_screen returns for the entry -- guaranteed
# stable across calls for the same entry (test_resource_screen_override_is_
# used_at_any_size_and_cached), but invalidated by e.g. Assets.clear().
# Comparing the held array by identity, rather than caching under some
# derived key like id(pixels), means a garbage-collected-and-reused id can
# never produce a false hit.
_SCREEN_SURFACE_CACHE = WeakKeyDictionary()


def screen_surface(resolver, entry, size=(320, 200)):
    """An ITD_RESS full-screen resource as a Surface at `size`, cached per
    (resolver, entry, size).

    The target is the canvas size, not always 320x200: an override larger
    than the logical frame keeps the resolution it came with instead of being
    scaled down and then back up for a high-resolution canvas. Scaling is
    nearest when the target is an exact integer multiple of the source, so
    original 320x200 art stays blocky, and smooth otherwise, where nearest
    would only add ragged edges.

    The returned Surface is SHARED across calls: callers that draw on it
    directly must `.copy()` it first, or the drawing bleeds into every later
    call for that entry."""
    asset = resolver.resource_screen(entry)
    per_entry = _SCREEN_SURFACE_CACHE.setdefault(resolver, {})
    key = (entry, size)
    cached = per_entry.get(key)
    if cached is not None and cached[0] is asset.pixels:
        return cached[1]
    surface = _to_surface(np.ascontiguousarray(asset.pixels))
    source = surface.get_size()
    if source != size:
        exact = (size[0] % source[0] == 0 and size[1] % source[1] == 0
                 and size[0] // source[0] == size[1] // source[1])
        scaler = pygame.transform.scale if exact else pygame.transform.smoothscale
        surface = scaler(surface, size)
    per_entry[key] = (asset.pixels, surface)
    return surface


def _resolver_or_originals(assets, resolver):
    return resolver if resolver is not None else AssetResolver(assets, None)


def _button(painter, rect, label, selected=False, size=18):
    painter.rect((214, 190, 142) if selected else (78, 59, 46), rect, border_radius=3)
    painter.rect((245, 226, 178), rect, width=2, border_radius=3)
    painter.text(label, size, (20, 16, 12) if selected else (250, 242, 216),
                 center=pygame.Rect(rect).center)


def _tile_big_cadre(surface, sprites, center, size):
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


def draw_big_cadre(painter, sprites, center, size):
    # FITD AffBigCadre placement (FitdLib/aitdBox.cpp:92-178). The tiling stays
    # on a logical 320x200 surface and is scaled once by the painter: the tiles
    # are pixel art, and an integer upscale of the assembled cadre is exactly
    # what an integer upscale of each tile would produce, with none of the
    # seams that scaling each tile separately would introduce.
    canvas = pygame.Surface((320, 200), flags=pygame.SRCALPHA)
    _tile_big_cadre(canvas, sprites, center, size)
    painter.sprite(canvas, (0, 0))


def layout_book(tokens, size, width, max_lines):
    # `painter` and a logical font size rather than a Font: the measurement
    # must stay logical so a window resize cannot re-flow a book and change
    # how many pages it has.
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
            if current.strip() and text_size(candidate, size)[0] > width:
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


def render_found(painter, effect, presenter, assets, found_name):
    painter.rect((17, 11, 9), pygame.Rect(0, 0, 320, 200))
    painter.text(assets.system_text(20), 20, (240, 220, 175), center=(160, 34))
    painter.text(found_name, 18, (255, 255, 255), center=(160, 78))
    choice = presenter.hover if presenter.hover is not None else presenter.choice
    _button(painter, ModalLayout.FOUND_LEAVE, assets.system_text(21), choice is FoundResult.LEAVE)
    _button(painter, ModalLayout.FOUND_TAKE, assets.system_text(22), choice is FoundResult.TAKE)
    if effect.forced_refuse:
        painter.text(assets.system_text(10), 16, (255, 192, 128), center=(160, 126))


def render_picture(painter, effect, assets, resolver=None):
    resolver = _resolver_or_originals(assets, resolver)
    painter.blit(screen_surface(resolver, effect.resource_index, painter.size), (0, 0))


def overlay_messages(painter, messages, assets):
    if all(message is None for message in messages):
        return
    y = 184
    for message in messages:
        if message is None:
            continue
        label = assets.system_text(message.message_id)
        painter.text(label, 16, (0, 0, 0), center=(161, y + 1))
        painter.text(label, 16, (255, 240, 185), center=(160, y))
        y -= 16


def render_play_hud(painter, *, inventory_available, keyboard_mode=False):
    """Draw the inventory button and, in keyboard mode, name the mode.

    The two are independent: the inventory button follows
    inventory_hud_available(), while the mode label follows the input mode
    alone. In keyboard mode PLAY has no mouse function at all -- no click,
    no hover -- and the shell hides the cursor to match, so this label is
    the only thing on screen that explains why clicking stopped working.
    """
    if inventory_available:
        _button(painter, PlayLayout.INVENTORY, "INV", selected=True)
    if keyboard_mode:
        # top centre: clear of the INV box in the top-left corner, so the
        # label's position does not depend on whether that button is drawn
        painter.text("KEYBOARD", 12, (245, 226, 178), midtop=PlayLayout.MODE_LABEL)


def render_hit_feedback(painter, rects):
    """Outline supplied actor rectangles without reading simulation state."""
    for rect in rects:
        target = pygame.Rect(rect)
        if target.width <= 0 or target.height <= 0:
            continue
        painter.rect((255, 255, 255), target.inflate(4, 4), width=2)
        painter.rect((255, 32, 32), target, width=2)


def render_settings_notice(painter, message):
    if message is None:
        return
    painter.shade((0, 0, 0, 190))
    painter.text("Settings error", 20, (255, 220, 170), center=(160, 38))
    lines = layout_book((BookToken("text", message),), 15, 276, 5)[0]
    for index, (text, _centered) in enumerate(lines):
        painter.text(text, 15, (255, 255, 255), center=(160, 65 + index * 16))
    _button(painter, SettingsNoticeLayout.DISMISS, "Dismiss", selected=True)


def reading_pages(effect, assets):
    pages = assets.book_pages.get(effect.text_index)
    if pages is None:
        pages = layout_book(assets.book_tokens(effect.text_index), 16, 190, 8)
        assets.book_pages[effect.text_index] = pages
    return pages


def render_reading(painter, effect, presenter, assets, resolver=None):
    resolver = _resolver_or_originals(assets, resolver)
    painter.blit(
        screen_surface(resolver, {0: 6, 1: 7, 2: 8}[effect.kind], painter.size), (0, 0),
    )
    pages = reading_pages(effect, assets)
    y = 20
    for text, centered in pages[presenter.page]:
        # the SCALED glyph is anchored, never a scale-1 text_size offset --
        # see UIPainter.text. `midtop` is exactly the old `160 - width // 2`
        # at scale 1, and centred on the same point above it.
        if centered:
            painter.text(text, 16, (43, 31, 22), midtop=(160, y))
        else:
            painter.text(text, 16, (43, 31, 22), topleft=(60, y))
        y += 16
    hover = presenter.hover
    _button(painter, ModalLayout.READING_PREV, "Previous",
            hover == ReadingResult(False, -1) if hover is not None else presenter.page > 0)
    _button(painter, ModalLayout.READING_CLOSE, "Close",
            hover == ReadingResult(True) if hover is not None else True)
    _button(painter, ModalLayout.READING_NEXT, "Next",
            hover == ReadingResult(False, 1) if hover is not None else presenter.page + 1 < len(pages))


def render_inventory(painter, presenter, assets, scene_frame, object_names, action_names):
    dimmed = (scene_frame.astype("f4") * 0.45).astype(np.uint8)
    painter.sprite(dimmed, (0, 0))
    rows = action_names if presenter.choosing_action else object_names
    cursor = presenter.action_cursor if presenter.choosing_action else presenter.object_cursor
    selection = presenter.hover if presenter.hover is not None else cursor
    start = visible_start(cursor, len(rows))
    title_id = 200 if presenter.choosing_action else 20
    painter.text(assets.system_text(title_id), 20, (255, 238, 198), center=(160, 16))
    for visible, rect in enumerate(ModalLayout.INVENTORY_ROWS):
        index = start + visible
        if index >= len(rows):
            break
        _button(painter, rect, rows[index], selected=index == selection)


def render_character_select(painter, presenter, assets, resolver=None):
    # FITD character select: resource 10 background, cadre around the hovered
    # portrait (left choice 0 = Emily hero 1, right choice 1 = Carnby hero 0);
    # STORY copies the opposite half of resource 14 plus book text 20/21.
    resolver = _resolver_or_originals(assets, resolver)
    background = screen_surface(resolver, 10, painter.size)
    painter.blit(background, (0, 0))
    choice = (presenter.hover if presenter.hover is not None
              and presenter.phase is CharacterPhase.PORTRAITS else presenter.choice)
    center = ((80, 100), (240, 100))[choice]
    draw_big_cadre(painter, assets.cadre_bank(), center, (160, 200))
    portrait = CharacterLayout.PORTRAITS[choice]
    # the portrait is re-copied from the clean background, over the cadre
    painter.blit(background, portrait.topleft, area=portrait)
    if presenter.phase is CharacterPhase.PORTRAITS:
        return
    intro = screen_surface(resolver, 14, painter.size)
    if presenter.choice == 0:
        painter.blit(intro, (160, 0), area=pygame.Rect(160, 0, 160, 200))
        entry, text_x = 21, 165
    else:
        painter.blit(intro, (0, 0), area=pygame.Rect(0, 0, 160, 200))
        entry, text_x = 20, 5
    page = layout_book(assets.book_tokens(entry), 15, 150, 12)[0]
    y = 5
    for text, centered in page:
        # `centered_in` is the STORY text column: it anchors the scaled
        # glyph and reproduces the old `text_x + (150 - width) // 2` exactly
        # at scale 1 -- see UIPainter.text.
        if centered:
            painter.text(text, 15, (43, 31, 22),
                         centered_in=pygame.Rect(text_x, y, 150, 15))
        else:
            painter.text(text, 15, (43, 31, 22), topleft=(text_x, y))
        y += 15


def graphics_labels(render):
    """One label per Graphics-page row above Back, in GRAPHICS_CYCLES order."""
    return [
        f"Scale: {render.scale}x",
        f"Shading: {render.shading.title()}",
        f"Filter: {render.background_filter.title()}",
        f"Lighting: {render.lighting.title()}",
        # "up to", because this row shows the *option*, and GLBackend clamps
        # it to ctx.max_samples at construction (many drivers cap at 4). The
        # menu has no handle on the live backend to read the real count off,
        # so the label states the request honestly rather than claiming a
        # sample count the GPU may not be giving.
        f"AA: up to {render.msaa}x" if render.msaa else "AA: Off",
        f"Realism: {render.realism.title()}",
    ]


def render_system_menu(painter, presenter, settings, assets):
    # the old scratch surface here was an OPAQUE pygame.Surface((320, 200)),
    # whose implicit fill is black; paint that ground explicitly so scale-1
    # output stays byte-identical (draw_big_cadre below only overwrites the
    # cadre and its interior, not the full frame).
    painter.rect((0, 0, 0), pygame.Rect(0, 0, 320, 200))
    draw_big_cadre(painter, assets.cadre_bank(), (160, 100), (320, 200))
    if presenter.page is SystemMenuPage.KEY_PICK:
        _render_key_picker(painter, presenter)
        return
    if presenter.page is SystemMenuPage.MAIN:
        labels = ["Return to Game", "Configuration", "Quit"]
    elif presenter.page is SystemMenuPage.GRAPHICS:
        labels = graphics_labels(settings.render) + ["Back"]
    else:
        labels = [f"Sticky Action: {'On' if settings.sticky_action else 'Off'}"]
        for control in REMAPPABLE_CONTROLS:
            labels.append(f"{control.name}: {', '.join(settings.bindings[control.name])}")
        labels.append("Graphics...")
        labels.append("Back to Menu")
    selection = presenter.hover if presenter.hover is not None else presenter.cursor
    button_size = 12 if presenter.page in (SystemMenuPage.CONFIG, SystemMenuPage.GRAPHICS) else 18
    rows = zip(SystemMenuLayout.rows(presenter.page), labels, strict=True)
    for index, (rect, label) in enumerate(rows):
        _button(painter, rect, label, selected=index == selection, size=button_size)


def _render_key_picker(painter, presenter):
    painter.text(f"{presenter.capture}: press a key or click one", 14,
                 (250, 242, 216), midtop=(160, 4))
    labels = [PICKABLE_KEY_LABELS.get(name, name) for name in PICKABLE_KEYS] + ["Cancel"]
    for index, (rect, label) in enumerate(zip(SystemMenuLayout.KEY_PICK_ROWS, labels)):
        _button(painter, rect, label, selected=index == presenter.hover, size=12)


def render_game_over(painter, scene_frame, ready):
    # LM_GAME_OVER's wall-clock wait (life.cpp:2438-2450) freezes the last PLAY
    # frame -- locked, this paints nothing at all, so the caller's canvas
    # reaches present() untouched and the modal holds the moment of death still.
    if not ready:
        return
    painter.sprite(scene_frame, (0, 0))
    painter.shade((0, 0, 0, 170))
    painter.text("Game Over", 40, (255, 238, 198), center=(160, 82))
    painter.text("Click to restart", 18, (255, 255, 255), center=(160, 126))


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


def render_cursor(painter, logical_pos, kind):
    """Draw the pick cursor. Pure presentation: never touches world state."""
    if logical_pos is None:
        return
    colour = _CURSOR_COLORS.get(kind, _CURSOR_COLORS["walk"])
    x, y = int(logical_pos[0]), int(logical_pos[1])
    if kind == "inventory":
        painter.rect(colour, pygame.Rect(x - 5, y - 4, 11, 9), width=2)
        painter.line(colour, (x - 2, y - 6), (x + 2, y - 6), width=2)
    elif kind == "attack":
        painter.circle(colour, (x, y), 6, width=1)
        painter.line(colour, (x - 8, y), (x + 8, y), width=1)
        painter.line(colour, (x, y - 8), (x, y + 8), width=1)
    elif kind == "target":
        painter.rect(colour, pygame.Rect(x - 5, y - 5, 11, 11), width=1)
    elif kind == "push":
        painter.line(colour, (x - 7, y), (x + 7, y), width=2)
        painter.line(colour, (x - 7, y), (x - 3, y - 3), width=2)
        painter.line(colour, (x - 7, y), (x - 3, y + 3), width=2)
        painter.line(colour, (x + 7, y), (x + 3, y - 3), width=2)
        painter.line(colour, (x + 7, y), (x + 3, y + 3), width=2)
    elif kind == "blocked":
        painter.line(colour, (x - 4, y - 4), (x + 4, y + 4))
        painter.line(colour, (x - 4, y + 4), (x + 4, y - 4))
    else:
        painter.circle(colour, (x, y), 4, width=1)
