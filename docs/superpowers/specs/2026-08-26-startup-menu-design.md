# Startup menu and title screen — design

Date: 2026-08-26. Status: approved design. Part 2 of 3 (screen overrides →
startup menu → intro cutscene). Depends on nothing; the intro cutscene spec
builds on the boot flow defined here.

## Goal

Boot the way `startAITD1` does (`AITD1.cpp:307`): title screen, then the
three-row main menu (`startupMenu.cpp:35 MainMenu`), then character select,
then play. Today `shell.main` opens `ChooseCharacter` directly and Escape in
the selector quits the process.

FITD flow, and what this milestone keeps:

| FITD | this milestone |
|---|---|
| `make3dTatou()` (3D logo) | skipped (no data on disk for the port; noted seam) |
| `makeIntroScreens()`: `AITD1_TITRE` (13) fade-in, wait 0x30 chrono units or key/click, then the credits page (`Lire(TEXTE_CREDITS)` over `AITD1_LIVRE`) | title screen kept: 3 s (`0x30` units at 16 ms) or any key/click. Credits page kept as a second static page (text `TEXTE_CREDITS` CVar over screen 7), dismissed the same way. |
| `MainMenu()`: big cadre (160,100,320,80), rows at y 76/92/108 with texts 11/12/13, up/down wrap, Enter/click selects, 0x10000-unit timeout starts a demo with a random hero | menu kept with the same geometry; **no timeout demo** (documented seam, needs the cutscene + AI demo which are out of scope) |
| `case 0` new game → `ChoosePerso()` (−1 = Escape back to the menu) | kept: selector Escape returns to the menu |
| `case 1` continue → `restoreSave(12, 0)` | row drawn disabled, not selectable, until M4a2 save/load exists |
| `case 2` exit → fade out, quit | kept |

Text ids (ENGLISH.PAK, verified): 11 "Begin a new game", 12 "Resume a saved
game", 13 "Return to DOS". They are drawn as-is (the game's own strings),
not paraphrased.

## Components (all `app/`)

`PyAitD/app/startup.py` (pygame allowed, no world/actor/LIFE mutation — same
rule as `ui.py`):

- `TitlePhase = TITLE | CREDITS`; `TitlePresenter(phase, elapsed_ms)`.
  `advance_title(presenter, elapsed_ms) -> bool` returns True when the page
  has timed out (title: 3000 ms; credits: no timeout — FITD waits for input
  via `Lire`). `reduce_title(presenter, command) -> TitleResult(done)`: any
  command (or click) moves TITLE → CREDITS → done.
- `StartupMenuPresenter(cursor=0, hover=None)`; rows are an enum
  `StartupRow = NEW_GAME | CONTINUE | QUIT`. `reduce_startup_menu(presenter,
  command, *, continue_enabled) -> StartupMenuResult | None` with fields
  `new_game`, `continue_game`, `quit`. UP/DOWN wrap and skip disabled rows;
  ACCEPT/OPEN_INVENTORY selects; CANCEL is a no-op (FITD has no back).
- `StartupLayout`: `ROWS` = three `pygame.Rect(10, 76 + 16*i, 300, 16)`;
  `HIT_ROWS = effective_rects(ROWS)`; `hit_test_startup(pos, presenter)`.
- `render_title(presenter, resolver, elapsed_ms)`: screen 13 with a linear
  fade-in over the first 500 ms (`FadeInPhys(8, 0)`); CREDITS renders screen
  7 with `layout_book(TEXTE_CREDITS)` in the box (48,2)-(260,197) using the
  existing book layout helper.
- `render_startup_menu(presenter, resolver, *, continue_enabled)`: black
  frame, `draw_big_cadre` at (160,100) size (320,80), rows via `_button`
  with the selected row highlighted; the disabled row drawn in the muted
  colour and never highlighted.

Screens load through the `AssetResolver` (screen overrides spec) so the
title and credits plates are overridable.

Effects and modes (`engine/effects.py`): two new modal effects
`ShowTitle` and `OpenStartupMenu`, mapped to `GameMode.TITLE` and
`GameMode.STARTUP_MENU`. They are opened only by the shell, never by LIFE.

Shell (`app/shell.py`):

- `main` opens `ShowTitle()` on a normal boot (debug starts unchanged).
- `route_command`/`route_mouse`/`route_hover` gain the two modes.
  `TitleResult(done)` → `game.close_modal(); game.open_modal(OpenStartupMenu())`.
  `StartupMenuResult.new_game` → `open_modal(ChooseCharacter())`;
  `.quit` → the existing quit path (fade is a 250 ms black overlay, the same
  helper the system menu Quit will share); `.continue_game` cannot be
  produced while disabled.
- Character select CANCEL in the PORTRAITS phase → `OpenStartupMenu()`
  instead of `CharacterSelectResult(quit=True)`; `reduce_character_select`
  returns a new `back=True` result and the shell reopens the menu. Debug
  starts that never showed the menu keep quitting on CANCEL (the shell
  checks whether a startup menu was ever shown: `session.booted_via_menu`).
- The title's timeout is driven from the frame loop with
  `session.elapsed_ms`, like `_auto_dismiss_picture`.
- `ModalSession` gets `title: TitlePresenter` and `startup: StartupMenuPresenter`.

Mouse contract (`games/aitd1/mouse_contract.py`): capabilities
`ADVANCE_TITLE` (any click, both title pages) and `STARTUP_MENU_ACTIVATE`
(row click, hover parity) with `MouseRoute`s in the two new modes; the
existing contract test that every mode has at least one route covers them.

Settings: none added. `Continue` enablement is a constant `False` in this
milestone, exposed as one `shell.continue_available(session)` function that
M4a2 replaces.

## Testing

- Reducers: cursor wrap, disabled-row skip, ACCEPT on each row, CANCEL
  no-op, title advance by time and by command, credits never time out.
- Hit geometry: `hit_test_startup` maps each row and rejects gaps; hover
  parity with the keyboard cursor (same pattern as `test_mouse_only.py`'s
  system menu cases).
- Shell routing (`test_runtime_modes.py` style, headless): boot opens
  `ShowTitle`; title → credits → menu; New game → `ChooseCharacter`; Escape
  in the selector → menu again; Quit exits `run` with the existing code;
  Continue click is ignored.
- Journey added to `make prove-shell`: title → menu → Emily → PLAY first
  tick, via both keyboard and mouse.
- Render: `render_title` at 0 ms is black, at 500 ms equals the plate;
  `render_startup_menu` highlights only the cursor row (pixel probes).

## Files

| file | change |
|---|---|
| `PyAitD/app/startup.py` | new: presenters, reducers, layout, renderers |
| `PyAitD/app/ui.py` | `CharacterSelectResult.back`, `ModalSession` fields |
| `PyAitD/app/shell.py` | boot opens the title; routing for two modes; quit fade helper; `continue_available` |
| `PyAitD/engine/effects.py` | `ShowTitle`, `OpenStartupMenu`, two `GameMode`s |
| `PyAitD/games/aitd1/mouse_contract.py` | two capabilities, routes |
| `tests/test_startup.py`, `tests/test_runtime_modes.py`, `tests/test_mouse_only.py` | tests + journey |
| `Makefile`, `AGENTS.md`, `CONTEXT.md`, `docs/m4a1-shell-proof.md` | docs; the M4a1 boundary note gains "the startup menu precedes the selector" |
