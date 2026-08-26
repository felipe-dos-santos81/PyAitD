# Startup Menu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Boot like FITD's `startAITD1`: title screen → credits page → main menu (New game / Continue / Quit) → character select → play, with Escape in the selector returning to the menu.

**Architecture:** Two new shell-only modal effects (`ShowTitle`, `OpenStartupMenu`) drive two new `GameMode`s. `app/startup.py` holds the presenters, reducers, hit geometry and renderers (pygame allowed, no world mutation). `app/shell.py` opens the title at boot, routes commands/mouse/hover for the two modes, advances the title by wall-clock, and translates the selector's quit into "back to menu" when a menu was shown. The mouse contract gains two capabilities.

**Tech Stack:** Python 3.12, pygame-ce, NumPy, pytest. No new dependency.

**Spec:** `docs/superpowers/specs/2026-08-26-startup-menu-design.md`

## Global Constraints

- `# SPDX-License-Identifier: GPL-2.0-only` first line of every new Python file.
- `app/startup.py` never mutates world/actor/inventory/LIFE state (same rule as `app/ui.py`); settings live on `ModalSession`, never `Game`.
- Menu strings are the game's own: ENGLISH text 11 "Begin a new game", 12 "Resume a saved game", 13 "Return to DOS" — never paraphrased.
- Geometry from `startupMenu.cpp`: cadre centre (160,100) size (320,80); rows at y = 76, 92, 108, height 16.
- Title timeout 3000 ms (`0x30` chrono units), fade-in over the first 500 ms; the credits page never times out.
- Continue is disabled (drawn muted, never selectable) until M4a2 save/load; enablement is the one function `shell.continue_available(session)`.
- No idle-timeout demo (documented seam).
- Every `GameMode` must appear in `MODE_MOUSE_CAPABILITIES` with routes (`tests/test_mouse_only.py` enforces).
- Any test touching pygame runs with `SDL_VIDEODRIVER=dummy`; game-data tests use the `data_dir` fixture.
- Run `.venv/bin/pytest -q` before every commit; never mass-reformat.
- Depends on the screen-overrides plan: `ui.screen_surface(resolver, entry)` and `render_active_mode(game, session, renderer, resolver=None)` exist.

---

### Task 1: Effects, modes and the mouse contract

**Files:**
- Modify: `PyAitD/engine/effects.py:6-14, 55-110`
- Modify: `PyAitD/games/aitd1/mouse_contract.py`
- Test: `tests/test_effects.py`, `tests/test_mouse_only.py:86-106`

**Interfaces:**
- Produces: `effects.ShowTitle` (frozen dataclass, no fields), `effects.OpenStartupMenu` (no fields), `GameMode.TITLE`, `GameMode.STARTUP_MENU`; `MODAL_MODE` entries; `PlayerCapability.ADVANCE_TITLE`, `PlayerCapability.STARTUP_MENU_ACTIVATE`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_effects.py`:

```python
def test_startup_effects_map_to_their_modes():
    from PyAitD.engine.effects import GameMode, MODAL_MODE, OpenStartupMenu, ShowTitle
    assert MODAL_MODE[ShowTitle] is GameMode.TITLE
    assert MODAL_MODE[OpenStartupMenu] is GameMode.STARTUP_MENU
    assert ShowTitle() == ShowTitle() and OpenStartupMenu() == OpenStartupMenu()
```

In `tests/test_mouse_only.py::test_shell_modes_and_the_settings_notice_fulfill_the_mouse_contract`, add before the settings-notice assertions:

```python
    assert MODE_MOUSE_CAPABILITIES[GameMode.TITLE] == frozenset({
        PlayerCapability.ADVANCE_TITLE,
        PlayerCapability.DISMISS_SETTINGS_ERROR,
        PlayerCapability.QUIT,
    })
    assert MODE_MOUSE_CAPABILITIES[GameMode.STARTUP_MENU] == frozenset({
        PlayerCapability.STARTUP_MENU_ACTIVATE,
        PlayerCapability.DISMISS_SETTINGS_ERROR,
        PlayerCapability.QUIT,
    })
```

- [ ] **Step 2: Run to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_effects.py tests/test_mouse_only.py -q -k "startup or shell_modes or every_mode"`
Expected: FAIL (`ImportError`, then `KeyError: GameMode.TITLE`).

- [ ] **Step 3: Implement**

`PyAitD/engine/effects.py` — add to `GameMode`:

```python
    TITLE = auto()
    STARTUP_MENU = auto()
```

After `OpenSystemMenu`:

```python
@dataclass(frozen=True)
class ShowTitle:
    # startup only: AITD1.cpp:121 makeIntroScreens (title, then credits page)
    pass


@dataclass(frozen=True)
class OpenStartupMenu:
    # startup only: startupMenu.cpp:35 MainMenu
    pass
```

Extend `ModalEffect` with `| ShowTitle | OpenStartupMenu` and `MODAL_MODE` with `ShowTitle: GameMode.TITLE, OpenStartupMenu: GameMode.STARTUP_MENU`.

`PyAitD/games/aitd1/mouse_contract.py` — add to `PlayerCapability`:

```python
    ADVANCE_TITLE = auto()
    STARTUP_MENU_ACTIVATE = auto()
```

`CAPABILITY_ROUTES`:

```python
    PlayerCapability.ADVANCE_TITLE: MouseRoute("left_click", "title or credits page", frozenset({GameMode.TITLE})),
    PlayerCapability.STARTUP_MENU_ACTIVATE: MouseRoute("left_click", "startup menu row", frozenset({GameMode.STARTUP_MENU})),
```

`MODE_MOUSE_CAPABILITIES`:

```python
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
```

`COMMAND_MOUSE_CAPABILITIES["ACCEPT"]` gains `PlayerCapability.ADVANCE_TITLE` and `PlayerCapability.STARTUP_MENU_ACTIVATE`.

- [ ] **Step 4: Run tests**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_effects.py tests/test_mouse_only.py tests/test_runtime_modes.py -q`
Expected: PASS. If `test_runtime_modes` has a test enumerating every `GameMode` through `render_active_mode`/`route_command`, it will now hit the `RuntimeError("unroutable modal ...")` — that is expected until Task 4; mark nothing, just confirm the failure is that one and proceed.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/effects.py PyAitD/games/aitd1/mouse_contract.py tests/test_effects.py tests/test_mouse_only.py
git commit -m "feat: ShowTitle/OpenStartupMenu effects, TITLE and STARTUP_MENU modes, mouse contract"
```

---

### Task 2: Presenters, reducers and hit geometry (`app/startup.py`)

**Files:**
- Create: `PyAitD/app/startup.py`
- Test: `tests/test_startup.py`

**Interfaces:**
- Produces:
  - `TitlePhase = TITLE | CREDITS`; `@dataclass TitlePresenter(phase=TITLE)`; `@dataclass(frozen=True) TitleResult(done: bool)`.
  - `TITLE_TIMEOUT_MS = 3000`, `TITLE_FADE_MS = 500`.
  - `advance_title(presenter, elapsed_ms) -> TitleResult | None` — TITLE phase past the timeout → phase CREDITS, returns `None`; CREDITS never advances by time.
  - `reduce_title(presenter, command) -> TitleResult | None` — any `Command` in TITLE → CREDITS (`None`); any in CREDITS → `TitleResult(True)`.
  - `class StartupRow(Enum): NEW_GAME=0, CONTINUE=1, QUIT=2`; `@dataclass StartupMenuPresenter(cursor=0, hover=None)`; `@dataclass(frozen=True) StartupMenuResult(new_game=False, continue_game=False, quit=False)`.
  - `reduce_startup_menu(presenter, command, *, continue_enabled) -> StartupMenuResult | None`.
  - `StartupLayout.ROWS` (3 `pygame.Rect(10, 76+16*i, 300, 16)`), `StartupLayout.HIT_ROWS = effective_rects(ROWS)`, `StartupLayout.CADRE = ((160, 100), (320, 80))`.
  - `hit_test_startup(pos, *, continue_enabled) -> int | None` (row index; the disabled row returns `None`).
  - `hit_test_title(pos) -> bool` (whole frame).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_startup.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pytest

from PyAitD.app.startup import (
    StartupLayout, StartupMenuPresenter, StartupMenuResult, StartupRow, TITLE_TIMEOUT_MS,
    TitlePhase, TitlePresenter, TitleResult, advance_title, hit_test_startup, hit_test_title,
    reduce_startup_menu, reduce_title,
)
from PyAitD.app.ui import Command


def test_title_advances_by_timeout_then_only_by_input():
    p = TitlePresenter()
    assert advance_title(p, TITLE_TIMEOUT_MS - 1) is None and p.phase is TitlePhase.TITLE
    assert advance_title(p, TITLE_TIMEOUT_MS) is None and p.phase is TitlePhase.CREDITS
    assert advance_title(p, 10 ** 6) is None and p.phase is TitlePhase.CREDITS


def test_title_any_command_pages_then_finishes():
    p = TitlePresenter()
    assert reduce_title(p, Command.LEFT) is None and p.phase is TitlePhase.CREDITS
    assert reduce_title(p, Command.CANCEL) == TitleResult(True)


def test_menu_cursor_wraps_and_skips_the_disabled_row():
    p = StartupMenuPresenter()
    reduce_startup_menu(p, Command.DOWN, continue_enabled=False)
    assert p.cursor == StartupRow.QUIT.value
    reduce_startup_menu(p, Command.DOWN, continue_enabled=False)
    assert p.cursor == StartupRow.NEW_GAME.value
    reduce_startup_menu(p, Command.UP, continue_enabled=False)
    assert p.cursor == StartupRow.QUIT.value
    reduce_startup_menu(p, Command.UP, continue_enabled=True)
    assert p.cursor == StartupRow.CONTINUE.value


@pytest.mark.parametrize("command", (Command.ACCEPT, Command.OPEN_INVENTORY))
def test_menu_accept_selects_the_cursor_row(command):
    p = StartupMenuPresenter(cursor=StartupRow.QUIT.value)
    assert reduce_startup_menu(p, command, continue_enabled=False) == StartupMenuResult(quit=True)
    p.cursor = StartupRow.NEW_GAME.value
    assert reduce_startup_menu(p, command, continue_enabled=False) == StartupMenuResult(new_game=True)
    p.cursor = StartupRow.CONTINUE.value
    assert reduce_startup_menu(p, command, continue_enabled=False) is None
    assert reduce_startup_menu(p, command, continue_enabled=True) == StartupMenuResult(continue_game=True)


def test_menu_cancel_is_a_no_op():
    p = StartupMenuPresenter(cursor=2)
    assert reduce_startup_menu(p, Command.CANCEL, continue_enabled=False) is None and p.cursor == 2


def test_layout_matches_fitd_geometry():
    assert [tuple(r) for r in StartupLayout.ROWS] == [(10, 76, 300, 16), (10, 92, 300, 16), (10, 108, 300, 16)]
    assert StartupLayout.CADRE == ((160, 100), (320, 80))


def test_hit_tests():
    assert hit_test_startup((100, 80), continue_enabled=False) == 0
    assert hit_test_startup((100, 96), continue_enabled=False) is None
    assert hit_test_startup((100, 96), continue_enabled=True) == 1
    assert hit_test_startup((100, 112), continue_enabled=False) == 2
    assert hit_test_startup((100, 10), continue_enabled=False) is None
    assert hit_test_title((0, 0)) and hit_test_title((319, 199)) and not hit_test_title((320, 200))
```

- [ ] **Step 2: Run to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_startup.py -q`
Expected: FAIL — `ModuleNotFoundError: PyAitD.app.startup`.

- [ ] **Step 3: Implement**

Create `PyAitD/app/startup.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Startup flow presenters, reducers, geometry and drawing: title screen and
credits page (AITD1.cpp:121 makeIntroScreens) and the main menu
(startupMenu.cpp:35 MainMenu). Same rules as app/ui.py: pygame allowed,
never mutates world/actor/inventory/LIFE state."""
from dataclasses import dataclass
from enum import Enum, auto

import numpy as np
import pygame

from PyAitD.app.ui import Command, _button, _font, _to_frame, draw_big_cadre, effective_rects, layout_book, screen_surface

TITLE_TIMEOUT_MS = 3000        # 0x30 chrono units of 1/16 s (AITD1.cpp:143)
TITLE_FADE_MS = 500            # FadeInPhys(8, 0) (AITD1.cpp:129)
MENU_TEXT_IDS = (11, 12, 13)   # "Begin a new game" / "Resume a saved game" / "Return to DOS"


class TitlePhase(Enum):
    TITLE = auto()
    CREDITS = auto()


@dataclass
class TitlePresenter:
    phase: TitlePhase = TitlePhase.TITLE


@dataclass(frozen=True)
class TitleResult:
    done: bool


def advance_title(presenter, elapsed_ms):
    # the title times out; the credits page waits for input like FITD's Lire
    if presenter.phase is TitlePhase.TITLE and elapsed_ms >= TITLE_TIMEOUT_MS:
        presenter.phase = TitlePhase.CREDITS
    return None


def reduce_title(presenter, command):
    if presenter.phase is TitlePhase.TITLE:
        presenter.phase = TitlePhase.CREDITS
        return None
    return TitleResult(True)


class StartupRow(Enum):
    NEW_GAME = 0
    CONTINUE = 1
    QUIT = 2


@dataclass
class StartupMenuPresenter:
    cursor: int = 0
    hover: int | None = None


@dataclass(frozen=True)
class StartupMenuResult:
    new_game: bool = False
    continue_game: bool = False
    quit: bool = False


def _enabled_rows(continue_enabled):
    return [row.value for row in StartupRow if continue_enabled or row is not StartupRow.CONTINUE]


def reduce_startup_menu(presenter, command, *, continue_enabled):
    rows = _enabled_rows(continue_enabled)
    if presenter.cursor not in rows:
        presenter.cursor = rows[0]
    command = Command.ACCEPT if command is Command.OPEN_INVENTORY else command
    if command in (Command.UP, Command.LEFT):
        presenter.cursor = rows[(rows.index(presenter.cursor) - 1) % len(rows)]
    elif command in (Command.DOWN, Command.RIGHT):
        presenter.cursor = rows[(rows.index(presenter.cursor) + 1) % len(rows)]
    elif command is Command.ACCEPT:
        row = StartupRow(presenter.cursor)
        if row is StartupRow.NEW_GAME:
            return StartupMenuResult(new_game=True)
        if row is StartupRow.CONTINUE:
            return StartupMenuResult(continue_game=True)
        return StartupMenuResult(quit=True)
    return None


class StartupLayout:
    ROWS = tuple(pygame.Rect(10, 76 + 16 * i, 300, 16) for i in range(3))   # startupMenu.cpp:24 AffRect(10, y, 309, y+16)
    HIT_ROWS = effective_rects(ROWS)
    CADRE = ((160, 100), (320, 80))                                          # AffBigCadre(160, 100, 320, 80)
    FRAME = pygame.Rect(0, 0, 320, 200)


def hit_test_startup(pos, *, continue_enabled):
    for index, rect in enumerate(StartupLayout.HIT_ROWS):
        if rect.collidepoint(pos):
            return index if index in _enabled_rows(continue_enabled) else None
    return None


def hit_test_title(pos):
    return StartupLayout.FRAME.collidepoint(pos)
```

(Renderers are added in Task 3; keep this file's imports as listed so Task 3 only appends.)

- [ ] **Step 4: Run tests**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_startup.py tests/test_layering.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/app/startup.py tests/test_startup.py
git commit -m "feat: startup title/menu presenters, reducers and hit geometry"
```

---

### Task 3: Renderers

**Files:**
- Modify: `PyAitD/app/startup.py` (append)
- Test: `tests/test_startup.py`

**Interfaces:**
- Consumes: `ui.screen_surface(resolver, entry)`, `ui.draw_big_cadre(surface, sprites, center, size)`, `ui._button`, `ui.layout_book`, `assets.cadre_bank()`, `assets.book_tokens(entry)`, `assets.system_text(id)`.
- Produces: `render_title(presenter, assets, resolver, elapsed_ms, credits_entry) -> np.ndarray (200,320,3)`; `render_startup_menu(presenter, assets, resolver, *, continue_enabled) -> np.ndarray (200,320,3)`.
- `credits_entry` = `game.cvars[profile.cvar_index("TEXTE_CREDITS")] + 1` (AITD1.cpp:159) — the shell computes it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_startup.py`:

```python
import numpy as np
from PyAitD.app.startup import render_startup_menu, render_title, TITLE_FADE_MS
from PyAitD.engine.game import init_game
from PyAitD.games.aitd1.profile import AITD1
from PyAitD.render.asset_resolver import AssetResolver


def test_title_fades_in_from_black(data_dir):
    import pygame
    pygame.font.init()
    game = init_game(data_dir, AITD1)
    resolver = AssetResolver(game.assets, None)
    credits = game.cvars[AITD1.cvar_index("TEXTE_CREDITS")] + 1
    black = render_title(TitlePresenter(), game.assets, resolver, 0, credits)
    full = render_title(TitlePresenter(), game.assets, resolver, TITLE_FADE_MS, credits)
    assert black.shape == full.shape == (200, 320, 3)
    assert black.max() == 0
    assert (full == game.assets.resource_screen(13)).all()
    page = render_title(TitlePresenter(TitlePhase.CREDITS), game.assets, resolver, 0, credits)
    assert page.shape == (200, 320, 3) and not (page == game.assets.resource_screen(7)).all()  # text drawn


def test_menu_highlights_only_the_cursor_row(data_dir):
    import pygame
    pygame.font.init()
    game = init_game(data_dir, AITD1)
    resolver = AssetResolver(game.assets, None)
    frame = render_startup_menu(StartupMenuPresenter(cursor=2), game.assets, resolver, continue_enabled=False)
    assert frame.shape == (200, 320, 3)
    rows = StartupLayout.ROWS
    probe = lambda r: tuple(frame[r.y + 2, r.x + 2])
    assert probe(rows[2]) == (214, 190, 142)          # selected fill (ui._button)
    assert probe(rows[0]) == (78, 59, 46)             # unselected fill
    assert probe(rows[1]) == (48, 40, 36)             # disabled fill
```

- [ ] **Step 2: Run to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_startup.py -q -k "fades or highlights"`
Expected: FAIL — `ImportError: cannot import name 'render_title'`.

- [ ] **Step 3: Implement**

Append to `PyAitD/app/startup.py`:

```python
DISABLED_FILL = (48, 40, 36)
DISABLED_TEXT = (140, 128, 110)


def _disabled_button(surface, rect, label, size=18):
    pygame.draw.rect(surface, DISABLED_FILL, rect, border_radius=3)
    pygame.draw.rect(surface, (120, 110, 90), rect, width=2, border_radius=3)
    glyph = _font(size).render(label, True, DISABLED_TEXT)
    surface.blit(glyph, glyph.get_rect(center=rect.center))


def render_title(presenter, assets, resolver, elapsed_ms, credits_entry):
    if presenter.phase is TitlePhase.TITLE:
        surface = screen_surface(resolver, 13)                       # AITD1_TITRE
        alpha = min(255, 255 * max(0, elapsed_ms) // TITLE_FADE_MS)
        if alpha < 255:
            shade = pygame.Surface((320, 200), flags=pygame.SRCALPHA)
            shade.fill((0, 0, 0, 255 - alpha))
            surface.blit(shade, (0, 0))
        return _to_frame(surface)
    surface = screen_surface(resolver, 7)                             # AITD1_LIVRE
    font = _font(15)
    page = layout_book(assets.book_tokens(credits_entry), font, 212, 13)[0]   # Lire(..., 48,2,260,197)
    y = 2
    for text, centered in page:
        glyph = font.render(text, True, (43, 31, 22))
        x = 48 + (212 - glyph.get_width()) // 2 if centered else 48
        surface.blit(glyph, (x, y))
        y += 15
    return _to_frame(surface)


def render_startup_menu(presenter, assets, resolver, *, continue_enabled):
    surface = pygame.Surface((320, 200))
    surface.fill((0, 0, 0))
    center, size = StartupLayout.CADRE
    draw_big_cadre(surface, assets.cadre_bank(), center, size)
    selection = presenter.hover if presenter.hover is not None else presenter.cursor
    for index, (rect, text_id) in enumerate(zip(StartupLayout.ROWS, MENU_TEXT_IDS)):
        label = assets.system_text(text_id)
        if index == StartupRow.CONTINUE.value and not continue_enabled:
            _disabled_button(surface, rect, label, size=14)
        else:
            _button(surface, rect, label, selected=index == selection, size=14)
    return _to_frame(surface)
```

- [ ] **Step 4: Run tests**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_startup.py -q`
Expected: PASS. If the credits assertion fails because `layout_book` produced no lines, print `assets.book_tokens(credits_entry)` and check the CVar (`TEXTE_CREDITS` index in `profile.CVAR_NAMES`) — do not change the entry arithmetic without citing `AITD1.cpp:159`.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/app/startup.py tests/test_startup.py
git commit -m "feat: title fade-in, credits page and startup menu renderers"
```

---

### Task 4: Shell wiring — boot, routing, render, timeout, back-to-menu

**Files:**
- Modify: `PyAitD/app/ui.py` (`ModalSession`), `PyAitD/app/shell.py` (`main`, `route_command`, `route_mouse`, `route_hover`, `render_active_mode`, `run`, `replacement_session`)
- Test: `tests/test_runtime_modes.py`, `tests/test_main.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces:
  - `ModalSession.title: TitlePresenter`, `ModalSession.startup: StartupMenuPresenter`, `ModalSession.booted_via_menu: bool = False`; `reset_for` resets `title`/`startup` when their effect is (re)observed.
  - `shell.continue_available(session) -> bool` (returns `False`; M4a2 replaces it).
  - `shell.open_startup_menu(game, session)`: `game.close_modal(); game.open_modal(OpenStartupMenu()); session.booted_via_menu = True`.
  - `shell.main` opens `ShowTitle()` on a normal boot.
  - Selector CANCEL (`CharacterSelectResult(quit=True)`) → `open_startup_menu` when `session.booted_via_menu`, else quit as today.

- [ ] **Step 1: Write the failing tests**

In `tests/test_main.py`, change `test_normal_main_opens_character_selection_before_run` to assert `isinstance(game.active_modal, ShowTitle)` (import `ShowTitle` from effects) and rename it `test_normal_main_opens_the_title_before_run`.

Append to `tests/test_runtime_modes.py`:

```python
from PyAitD.app.shell import continue_available, open_startup_menu
from PyAitD.app.startup import StartupLayout, StartupRow, TitlePhase, TITLE_TIMEOUT_MS
from PyAitD.engine.effects import OpenStartupMenu, ShowTitle


def _startup_game():
    game = init_game(_DATA, AITD1)   # replace _DATA with the module's existing data fixture usage
    game.open_modal(ShowTitle())
    return game


def test_title_pages_by_command_then_opens_the_menu(data_dir):
    game = init_game(data_dir, AITD1)
    game.open_modal(ShowTitle())
    session = ModalSession()
    assert route_command(game, session, Command.ACCEPT) is True
    assert session.title.phase is TitlePhase.CREDITS and isinstance(game.active_modal, ShowTitle)
    assert route_command(game, session, Command.ACCEPT) is True
    assert isinstance(game.active_modal, OpenStartupMenu) and session.booted_via_menu


def test_title_click_advances_like_a_command(data_dir):
    game = init_game(data_dir, AITD1)
    game.open_modal(ShowTitle())
    session = ModalSession()
    route_mouse(game, session, (5, 5))
    route_mouse(game, session, (5, 5))
    assert isinstance(game.active_modal, OpenStartupMenu)


def test_menu_new_game_opens_the_selector_and_escape_returns(data_dir):
    game = init_game(data_dir, AITD1)
    session = ModalSession()
    open_startup_menu(game, session)
    assert route_command(game, session, Command.ACCEPT) is True
    assert isinstance(game.active_modal, ChooseCharacter)
    assert route_command(game, session, Command.CANCEL) is True          # back, not quit
    assert isinstance(game.active_modal, OpenStartupMenu)


def test_selector_escape_still_quits_without_a_menu(data_dir):
    game = init_game(data_dir, AITD1)
    game.open_modal(ChooseCharacter())
    assert route_command(game, ModalSession(), Command.CANCEL) is False


def test_menu_quit_row_ends_the_loop_and_continue_is_inert(data_dir):
    game = init_game(data_dir, AITD1)
    session = ModalSession()
    open_startup_menu(game, session)
    assert continue_available(session) is False
    row = StartupLayout.ROWS[StartupRow.CONTINUE.value]
    assert route_mouse(game, session, row.center) is True and isinstance(game.active_modal, OpenStartupMenu)
    row = StartupLayout.ROWS[StartupRow.QUIT.value]
    assert route_mouse(game, session, row.center) is False


def test_menu_hover_previews_rows(data_dir):
    game = init_game(data_dir, AITD1)
    session = ModalSession()
    open_startup_menu(game, session)
    route_hover(game, session, StartupLayout.ROWS[2].center)
    assert session.startup.hover == 2
    route_hover(game, session, None)
    assert session.startup.hover is None


def test_render_active_mode_draws_title_and_menu(data_dir):
    pygame.font.init()
    game = init_game(data_dir, AITD1)
    session = ModalSession()
    renderer = SimpleNamespace(scene_thumbnail=lambda: np.zeros((200, 320, 3), np.uint8))
    game.open_modal(ShowTitle())
    assert render_active_mode(game, session, renderer).shape == (200, 320, 3)
    open_startup_menu(game, session)
    assert render_active_mode(game, session, renderer).shape == (200, 320, 3)
```

(Delete the `_startup_game` helper if unused; it is shown only to make the fixture pattern explicit.)

- [ ] **Step 2: Run to verify they fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_runtime_modes.py tests/test_main.py -q -k "title or menu or selector"`
Expected: FAIL (`ImportError: continue_available`).

- [ ] **Step 3: Implement `ModalSession`**

In `PyAitD/app/ui.py`, add fields to `ModalSession` (after `system_menu`):

```python
    title: "TitlePresenter" = None
    startup: "StartupMenuPresenter" = None
    booted_via_menu: bool = False
```

and in `__post_init__` (add one if absent):

```python
    def __post_init__(self):
        from PyAitD.app.startup import StartupMenuPresenter, TitlePresenter
        if self.title is None:
            self.title = TitlePresenter()
        if self.startup is None:
            self.startup = StartupMenuPresenter()
```

In `reset_for`, extend the `elif` chain:

```python
        elif isinstance(effect, ShowTitle):
            from PyAitD.app.startup import TitlePresenter
            self.title = TitlePresenter()
        elif isinstance(effect, OpenStartupMenu):
            from PyAitD.app.startup import StartupMenuPresenter
            self.startup = StartupMenuPresenter()
```

(import `OpenStartupMenu, ShowTitle` from `PyAitD.engine.effects` at the top of `ui.py`; `startup` imports `ui`, so `ui` imports `startup` lazily as shown to avoid the cycle.)

- [ ] **Step 4: Implement the shell**

In `PyAitD/app/shell.py`:

```python
def continue_available(session):
    # M4a2 save/load replaces this with a real check of the save slots.
    return False


def open_startup_menu(game, session):
    from PyAitD.engine.effects import OpenStartupMenu
    game.close_modal()
    game.open_modal(OpenStartupMenu())
    session.booted_via_menu = True
    session.reset_for(game.active_modal)


def _credits_entry(game):
    # AITD1.cpp:159 Lire(CVars[TEXTE_CREDITS] + 1, ...)
    return game.cvars[game.profile.cvar_index("TEXTE_CREDITS")] + 1
```

`main`: replace `game.open_modal(ChooseCharacter())` with `game.open_modal(ShowTitle())` (import from effects).

`replacement_session`: also copy `booted_via_menu=session.booted_via_menu`.

`route_command` — after the `OpenSystemMenu` branch and before `session.reset_for(game.active_modal)`, nothing; after `route_hover(game, session, None)` add, before the `ChooseCharacter` branch:

```python
    if isinstance(game.active_modal, ShowTitle):
        from PyAitD.app.startup import reduce_title
        if reduce_title(session.title, modal_command) is not None:
            open_startup_menu(game, session)
        return True
    if isinstance(game.active_modal, OpenStartupMenu):
        from PyAitD.app.startup import reduce_startup_menu
        result = reduce_startup_menu(session.startup, modal_command, continue_enabled=continue_available(session))
        return _apply_startup_result(game, session, input_buffer, result)
```

and change the `ChooseCharacter` branch's `if result.quit:` to:

```python
            if result.quit:
                if session.booted_via_menu:
                    open_startup_menu(game, session)
                    return True
                return False
```

Add:

```python
def _apply_startup_result(game, session, input_buffer, result):
    if result is None:
        return True
    if result.new_game:
        game.close_modal()
        game.open_modal(ChooseCharacter())
        session.reset_for(game.active_modal)
        if input_buffer is not None:
            reset_input(input_buffer)
        return True
    if result.quit:
        if input_buffer is not None:
            reset_input(input_buffer)
        return False
    return True   # continue_game cannot be produced while continue_available is False
```

`route_mouse` — after the `OpenSystemMenu` branch, before `session.reset_for(effect)`:

```python
    if isinstance(effect, ShowTitle):
        from PyAitD.app.startup import hit_test_title, reduce_title
        if hit_test_title(logical_pos) and reduce_title(session.title, Command.ACCEPT) is not None:
            open_startup_menu(game, session)
        return True
    if isinstance(effect, OpenStartupMenu):
        from PyAitD.app.startup import hit_test_startup, reduce_startup_menu
        enabled = continue_available(session)
        hit = hit_test_startup(logical_pos, continue_enabled=enabled)
        if hit is None:
            return True
        session.startup.cursor = hit
        result = reduce_startup_menu(session.startup, Command.ACCEPT, continue_enabled=enabled)
        return _apply_startup_result(game, session, input_buffer, result)
```

`route_hover` — add:

```python
    elif isinstance(effect, OpenStartupMenu):
        from PyAitD.app.startup import hit_test_startup
        session.startup.hover = (
            hit_test_startup(logical_pos, continue_enabled=continue_available(session))
            if logical_pos is not None else None
        )
```

`render_active_mode` — after the `ChooseCharacter` branch:

```python
    if isinstance(effect, ShowTitle):
        from PyAitD.app.startup import render_title
        return render_title(session.title, game.assets, resolver or AssetResolver(game.assets, None),
                            session.elapsed_ms, _credits_entry(game))
    if isinstance(effect, OpenStartupMenu):
        from PyAitD.app.startup import render_startup_menu
        return render_startup_menu(session.startup, game.assets, resolver or AssetResolver(game.assets, None),
                                   continue_enabled=continue_available(session))
```

`run` — in the non-PLAY branch (`else: accumulator = 0; session.elapsed_ms += elapsed; _auto_dismiss_picture(game, session)`) add:

```python
            if isinstance(game.active_modal, ShowTitle):
                from PyAitD.app.startup import advance_title
                advance_title(session.title, session.elapsed_ms)
```

(`session.reset_for` runs in `render_active_mode` each frame, so `elapsed_ms` counts from the title's first frame; `advance_title` only moves TITLE → CREDITS, which keeps the same effect and therefore the same `elapsed_ms`.)

- [ ] **Step 5: Run tests**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_runtime_modes.py tests/test_main.py tests/test_shell_journeys.py tests/test_mouse_only.py -q`
Expected: PASS. Journeys that started at `ChooseCharacter` by opening it directly on the game are unaffected (`booted_via_menu` stays False there).

- [ ] **Step 6: Commit**

```bash
git add PyAitD/app/ui.py PyAitD/app/shell.py tests/test_runtime_modes.py tests/test_main.py
git commit -m "feat: boot into the title and startup menu; selector Escape returns to the menu"
```

---

### Task 5: Real-loop journey, proof target and docs

**Files:**
- Modify: `tests/test_shell_journeys.py`, `AGENTS.md`, `CONTEXT.md`, `docs/m4a1-shell-proof.md`
- Makefile: `prove-shell` already runs `tests/test_shell_journeys.py` and `tests/test_startup.py` must be added to it.

- [ ] **Step 1: Write the journey**

Append to `tests/test_shell_journeys.py` (uses the file's `_run_shell`, `_left_click`, `_key`, `_quit` helpers):

```python
from PyAitD.app.startup import StartupLayout, StartupRow, TitlePhase
from PyAitD.engine.effects import ShowTitle


def test_journey_title_menu_select_play_by_mouse(data_dir, monkeypatch):
    game = init_game(data_dir, AITD1)
    game.open_modal(ShowTitle())
    session = load_runtime_session(None)
    seen = []
    frames = iter([
        [_left_click((160, 100))],                                        # title -> credits
        [_left_click((160, 100))],                                        # credits -> menu
        [_left_click(StartupLayout.ROWS[StartupRow.NEW_GAME.value].center)],
        [_left_click(CharacterLayout.PORTRAITS[0].center)],               # Emily portrait -> story
        [_left_click((160, 100))],                                        # story page -> confirm
        [], [],                                                           # hero branch + one PLAY frame
        [_quit()],
    ])
    def next_events():
        return next(frames, [_quit()])
    def observe_tick(game_, floor, buf):
        seen.append(game_.cvars[AITD1.cvar_index("CHOOSE_PERSO")])
        return real_play_tick(game_, floor, buf)
    _run_shell(monkeypatch, game, session, next_events, observe_tick=observe_tick)
    assert seen and seen[0] == 1                                          # Emily is hero 1


def test_journey_title_menu_select_play_by_keyboard(data_dir, monkeypatch):
    game = init_game(data_dir, AITD1)
    game.open_modal(ShowTitle())
    session = load_runtime_session(None)
    seen = []
    frames = iter([
        [_key(pygame.K_RETURN)], [_key(pygame.K_RETURN)],                 # title, credits
        [_key(pygame.K_RETURN)],                                          # New game
        [_key(pygame.K_ESCAPE)],                                          # back to menu
        [_key(pygame.K_RETURN)],                                          # New game again
        [_key(pygame.K_RIGHT)], [_key(pygame.K_RETURN)], [_key(pygame.K_RETURN)],   # Carnby, story, confirm
        [], [],
        [_quit()],
    ])
    def next_events():
        return next(frames, [_quit()])
    def observe_tick(game_, floor, buf):
        seen.append(game_.cvars[AITD1.cvar_index("CHOOSE_PERSO")])
        return real_play_tick(game_, floor, buf)
    _run_shell(monkeypatch, game, session, next_events, observe_tick=observe_tick)
    assert seen and seen[0] == 0
```

Check the file's existing journeys for how `load_runtime_session`/settings are built (some pass a `tmp_path` settings file) and mirror that exactly; the key names above assume the default bindings (`return` = ACCEPT, `escape` = CANCEL, arrows = directions) — read `app/config.py` `default_settings` to confirm.

- [ ] **Step 2: Run**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_shell_journeys.py -q -k journey_title`
Expected: PASS. If the journey stalls on the title, one frame is being consumed by `reset_for` before the click — add one `[]` frame after `game.open_modal(ShowTitle())`'s first events entry.

- [ ] **Step 3: Makefile and docs**

Makefile `prove-shell`: add `tests/test_startup.py` to the file list.

`AGENTS.md` Commands: `make run # play via title → menu → character select; ...`. `CONTEXT.md` "M4a1 shell boundary": add "`app/startup.py` owns the title/credits/menu presenters; `shell.open_startup_menu` is the one entry into the menu; `continue_available` is the M4a2 seam; no idle-timeout demo (FITD `MainMenu` 0x10000-unit timeout) — a later milestone adds it with the intro cutscene." `docs/m4a1-shell-proof.md`: add a row "startup menu journeys (mouse, keyboard): automated, `make prove-shell`".

- [ ] **Step 4: Full suite**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest -q && make prove && make prove-shell`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add tests/test_shell_journeys.py Makefile AGENTS.md CONTEXT.md docs/m4a1-shell-proof.md
git commit -m "test: startup menu journeys; docs for the title/menu boot flow"
```
