# Alone in the Dark 1 — M4a1 Shell and Configuration Design

Date: 2026-08-24
Status: Approved — implementation planning authorized
Reference: FITD (`/Users/felipe.dos.santos/code/theirs/FITD`, GPLv2) —
`AITD1.cpp`, `startupMenu.cpp`, `systemMenu.cpp`, `aitdBox.cpp`, `main.cpp`,
`input.cpp`; port: `__main__.py`, `ui.py`, `effects.py`, `assets.py`,
`config.py` (new)
Builds on: M3b (interaction/inventory), M3c (combat), M3d/M3e (point-and-click,
mouse contract). Parent roadmap: `2026-08-22-aitd1-build-conclusion-design.md`.

## Goal

Give the port a real shell: boot into a faithful character-selection screen,
start either protagonist with FITD-correct initial state, and open an honest
in-game system menu on Escape carrying the accessibility configuration —
control remapping and sticky action — persisted to a per-user settings file
in this slice.

This is **M4a1, the first half of M4a**. M4a2 (persistence: save/load core,
slot UI hosted in this menu, quick-save) follows and inserts its rows into the
menu built here. M4b owns audio/sequences, M4c owns playthrough closure.

## Decisions locked during brainstorming

1. **Slice order: shell first, persistence second.** The system menu is the
   host for M4a2's save/load rows; each slice stays M3e-sized.
2. **Boot flow:** the app boots into character selection. An explicitly supplied
   `--floor 0`, `--combat-venue`, or `--mouse-combat-fixture` bypasses the shell
   straight into PLAY. `make run` does not supply `--floor`; `make run floor=0`
   is the explicit floor-zero debug bypass.
3. **Character selection mirrors the original screen** (ITD_RESS art, cadre
   frame, story page) rather than a port-native mock.
4. **System menu ships an honest subset** — Return to Game, Configuration,
   Quit — and grows Save/Load rows in M4a2. FITD's dead option rows
   (Music/Sound/Details, `systemMenu.cpp:93-113`) are not reproduced.
5. **Selection input is hit-tested and the click quirk is fixed** (details
   below); single-button users can reach both heroes and start the game.
6. **Configuration ships in full now:** remap screen, sticky action, and the
   per-user settings file (pulled forward from M4a2). Remapping targets player
   controls, not internal `Command` values.
7. **Architecture: native modes and effects** in the existing mode/effect
   machinery, not a separate shell loop and not modals over PLAY.

## Non-goals

- Save/load slots, quick-save, save format (M4a2).
- Intro tatou/title/credits screens, main menu's "Resume a saved game",
  sequence playback (M4b).
- FITD main menu (`startupMenu.cpp`) — superseded by booting straight into
  character selection; M4a2 revisits a resume path.
- Music/Sound/Details toggles (M4b); FITD displays them without handlers.
- FITD's demo mode (menu timeout → random hero attract loop,
  AITD1.cpp:324-340).

## FITD evidence

### Character selection (`ChoosePerso`, AITD1.cpp:176-302)

- Full-screen 320x200 image `ITD_RESS` entry 10 (`AITD1_PERSO_CHOICE`):
  left portrait x∈[10,149], right x∈[170,309], y∈[10,190]
  (AITD1.cpp:192-194,199,204,232,246).
- Selection indicator is an `AffBigCadre` sprite frame around the current
  portrait (AITD1.cpp:196-205,227-253); default `choice = 0` (left)
  (AITD1.cpp:178).
- Input loop: `JoyD & 4` left / `JoyD & 8` right, Enter (0x1C) or any `Click`
  confirms the framed portrait (AITD1.cpp:222-261). FITD's `Click` is SPACE,
  not a mouse button (input.cpp:111-113).
- Confirmation composes the story page: `ITD_RESS` entry 14
  (`AITD1_FOND_INTRO`) opposite half plus the hero's story text — left choice
  shows the right half with `INTRO_HERITIERE+1` (language entry 21), right
  choice the left half with `INTRO_DETECTIVE+1` (entry 20)
  (AITD1.cpp:266-290).
- Output: `CVars[CHOOSE_PERSO]` — **left → 1 (Emily Hartwood), right → 0
  (Edward Carnby)** (AITD1.cpp:276,287). `LoadWorld` backs up and restores
  this CVar across the DEFINES.ITD reload (main.cpp:1133,1160); per-hero
  body/anim archives come from `listBodySelect[CHOOSE_PERSO]` /
  `listAnimSelect[CHOOSE_PERSO]` — LISTBODY/LISTANIM vs LISTBOD2/LISTANI2
  (main.cpp:1173-1174, vars.cpp:247-255).
- Quirks: Esc-cancel checks dead scancode 1 (input.cpp:93-95 maps Esc→0x1B),
  so cancel never fires in FITD; `if (localKey && 0x1C)` at AITD1.cpp:292 is
  a logical AND, so dismissing the story page by click alone returns to the
  portraits instead of starting.

### System menu (`processSystemMenu`, systemMenu.cpp:53-160)

- Opened by Escape in `PlayWorld` (mainLoop.cpp:53-67); blocking modal loop —
  simulation does not run while open; `SaveTimerAnim`/`RestoreTimerAnim`
  freeze game time (systemMenu.cpp:59,107,160, gameTime.cpp:6-24).
- Full-screen `AffBigCadre(160,100,320,200)` (systemMenu.cpp:22-51);
  `NB_OPTIONS = 7` rows centered x=160, y=43+16n, wrap 0↔6, Enter/click
  confirms, Esc exits; only rows 0-2 (Return/Save/Load) have handlers.
- Save/load is single-slot `SAVE0.ITD`, no picker (`parseAllSaves` is a stub,
  main.cpp:4157-4161); silent overwrite, errors ignored. M4a2 replaces this
  wholesale with the conclusion design's versioned JSON.

### Boot state to mirror

Both protagonists share: initial floor/room (intro 7,1 → 0,0 — the intro is
M4b; M4a1 starts at 0,0 directly), position from OBJETS.ITD, empty
inventories with `inHandTable[i] = -1` (main.cpp:1210-1216), VARS.ITD, and
all CVars from DEFINES.ITD except `CHOOSE_PERSO`. Per-hero difference is
exactly the CVar plus the body/anim archive pair (above).

## Architecture

### Modes and effects

Two new modes in `effects.py`, each driven by a typed effect in
`active_modal` — the same pattern as `ShowFound`/`OpenInventory`/`ReadText`:

- `GameMode.CHARACTER_SELECT` with `ChooseCharacter`; session gains
  `CharacterSelectPresenter(choice: int, phase: PORTRAITS | STORY)`.
- `GameMode.SYSTEM_MENU` with `OpenSystemMenu`; session gains
  `SystemMenuPresenter(page: MAIN | CONFIG, cursor: int, capture: str | None)`.

`__main__.py` remains the sole event pump, game/floor replacement authority,
and presentation owner. Normal boot creates a fresh floor-zero staging `Game`,
opens `ChooseCharacter` before the first gameplay tick, and renders the shell
instead of PLAY. Debug starts do not open that effect. Hero confirmation always
replaces the staging game and floor atomically through a restart-style branch
that calls `init_game(hero=)`; no staging-world state can leak into PLAY.

The replacement branch carries the loaded settings object and any recoverable
settings error into the new `ModalSession`. Death restart does the same. This
keeps settings at the application-session boundary instead of adding them to
saveable `Game` state.

### File map

| File | Responsibility in M4a1 |
|---|---|
| `PyAitD/effects.py` | 2 modes, 2 effect dataclasses. |
| `PyAitD/ui.py` | Presenters, reducers, renderers for select/menu/config/settings notice; cadre renderer; hit geometry; pygame key-name adapter. Presentation only. |
| `PyAitD/assets.py` | Hero-specific body/anim archives; `cadre_bank()` for ITD_RESS entry 4. `resource_screen(10/14)` already exists. |
| `PyAitD/config.py` (new, pygame-free) | `Control`, `Settings`, defaults, structural validation, atomic JSON load/save, `settings_path()`. |
| `PyAitD/__main__.py` | Staging-game boot, hero replacement, system-menu routing, raw remap capture, settings lifetime and load. |
| `PyAitD/mouse_contract.py` | Capabilities for the two new modes; exhaustiveness gate enforces them. |
| `PyAitD/input` handling (`ui.event_to_input`, `playworld.apply_play_input`) | Compiled binding translation; held-state reset; one-tick sticky-action pulse. |
| `Makefile` | Default `run` enters the shell; explicit floor bypass; `prove-shell` focused target. |
| `docs/m4a1-shell-proof.md` | Windowed manual evidence, M3e format. |
| `CONTEXT.md` | Milestone row + shell boundary section. |

### Character selection

- **PORTRAITS phase:** `resource_screen(10)` full frame; cadre frame around
  the selected portrait; default left. Direction controls move the frame;
  Action or Inventory/Confirm confirms it (defaults: arrows/WASD and
  Space/Return/I). A left click hit-tests either portrait and chooses that hero
  outright (honest target, one click, both heroes mouse-reachable).
- **STORY phase:** start from `resource_screen(10)`, copy the hero-opposite half
  from `resource_screen(14)`, and lay out the story with the existing
  `book_tokens`/`layout_book`/font helpers. Emily uses x=160..319 with text
  entry 21 in x=165..314; Carnby uses x=0..159 with entry 20 in x=5..154.
  This is a small character-story renderer, not a parameter expansion of the
  existing book renderer and its resource entries 6-8. **Action,
  Inventory/Confirm, or click starts the game** — a deliberate, documented fix
  of FITD's logical-AND quirk
  (AITD1.cpp:292), which would otherwise trap single-button users in a
  portrait loop. Esc: story → portraits; portraits → clean app quit.
- **Start:** call `init_game(hero=)` with `CVars[CHOOSE_PERSO]` 0 for Carnby or
  1 for Emily. `Assets(data_dir, hero=)` selects LISTBODY/LISTANIM for Carnby
  and LISTBOD2/LISTANI2 for Emily before any actor body or animation loads.
  Enter PLAY at floor 0 room 0. Real-data tests pin each hero's initial state.

### System menu

- **Trigger:** Esc in PLAY (`Command.CANCEL`) opens `OpenSystemMenu` instead
  of quitting the app; app-quit moves to the Quit row.
- **Pause:** a modal is active so `play_tick` does not run — the port already
  has FITD's `SaveTimerAnim`/`RestoreTimerAnim` semantics by construction.
  Keep the existing modal-entry command flush and add a matching exit drain.
  Both transitions clear queued commands, held controls, and sticky-action
  state, so opening or closing the menu cannot replay input into PLAY.
- **Frame:** full-screen cadre frame (320x200) from the new cadre renderer.
- **Rows:** Return to Game / Configuration / Quit. Up/down wrap,
  Action or Inventory/Confirm activates, left-click hit-tests and activates a
  row, and Esc exits to PLAY. Quit closes cleanly when settings are clean or
  save succeeds (OS cursor restored, renderer closed, exit 0).
- **Configuration page:** Sticky-action toggle row, one row per remappable
  `Control`, and a final **Back to Menu** navigation row so a single-button
  player can leave Configuration. Back is not a remappable CANCEL control;
  Escape remains the fixed keyboard shortcut. Activating a remap row enters
  capture state ("press a key…"). The
  next non-repeat KEYDOWN replaces that control's complete binding list with
  the captured key. Binding an already-bound key removes it from the previous
  control. CANCEL is the one fixed control: Escape always cancels capture and
  opens/closes the system menu, so Configuration does not offer a CANCEL row.
  Changes apply immediately. Leaving Configuration, returning to PLAY, or
  choosing Quit saves dirty settings once. A failed save keeps the changes in
  memory and leaves a persistent named error; Quit stays in the menu after such
  a failure so the error is visible.

### Configuration model and settings file (`config.py`, pygame-free)

- `Control` has eight stable values: UP, DOWN, LEFT, RIGHT, ACTION,
  INVENTORY_CONFIRM, CANCEL, and TOGGLE_INPUT_MODE. `Command` remains an
  internal edge-event type and is not serialized. Seven controls are
  remappable; CANCEL must remain bound only to Escape so capture and menu exit
  always have a recovery key.
- `Settings` has `bindings: dict[str, tuple[str, ...]]` (control name →
  pygame-compatible key names) and `sticky_action: bool`. Defaults preserve
  arrows plus WASD, Space for Action, Return plus I for Inventory/Confirm,
  Escape for Cancel, and Tab for input-mode toggle. A remap reduces the chosen
  control to one key; adding and removing alternate slots is out of scope.
- `settings_path()`: `~/Library/Application Support/PyAitD/settings.json` on
  macOS, `~/.config/pyaitd/settings.json` elsewhere. No new dependency.
- JSON schema 1 stores every control and its ordered key-name list:

  ```json
  {
    "schema": 1,
    "sticky_action": false,
    "bindings": {
      "UP": ["up", "w"], "DOWN": ["down", "s"],
      "LEFT": ["left", "a"], "RIGHT": ["right", "d"],
      "ACTION": ["space"], "INVENTORY_CONFIRM": ["return", "i"],
      "CANCEL": ["escape"], "TOGGLE_INPUT_MODE": ["tab"]
    }
  }
  ```

  `config.py` validates the schema, exact control names, list shape, non-empty
  strings, uniqueness, and the fixed `CANCEL: ["escape"]` value. The pygame
  boundary converts names with `pygame.key.key_code`; saving obtains stable
  names with `pygame.key.name(key, use_compat=True)`. An unknown key name makes
  the file invalid. This split keeps `config.py` pygame-free.
- Save through a temporary file in the destination directory followed by
  `os.replace`; create the parent directory and remove a leftover temporary
  file after failure. Corrupt, incompatible, or unwritable settings never
  crash. Load falls back to defaults. Every mode renders a persistent named
  settings notice until the player dismisses it.
- Settings live on `ModalSession`, load once at boot, and survive hero and
  death game/floor replacement. Pass them into `event_to_input` and the menu
  reducers; do not add them to `Game`.
- Sticky action defaults off and leaves current held-Action behavior unchanged.
  When enabled in keyboard mode, a non-repeat Action KEYDOWN arms a latch. The
  next non-repeat direction KEYDOWN creates one `action_pulse`; the next PLAY
  tick exposes `local_click=1`/`action=0x2000`, consumes the pulse, and clears
  the latch. It does not require simultaneous keys. Focus loss, remapping,
  modal entry/exit, input-mode changes, and game replacement clear the latch,
  pulse, and held state.

### Pygame reuse

Use pygame-ce's existing event queue, `pygame.key.name`,
`pygame.key.key_code`, `pygame.Rect.collidepoint`, surfaces, fonts, and cursor
visibility. Do not add pygame-menu, pygame_gui, or another dependency. The
asset-driven screens and current outer loop already provide the required
seams.

### Input routing and mouse contract

- At boot and after each remap, the pygame adapter compiles the persisted key
  names into one keycode-to-`Control` table. `event_to_input` translates
  physical keys through that table; unbound controls produce nothing.
  Held-direction state uses the same compiled table.
- While remap capture is active, `__main__.py` intercepts the next non-repeat
  KEYDOWN before `event_to_input`. The captured key cannot also navigate or
  activate the menu. KEYUP and window events continue through the ordinary
  pump. Esc cancels capture without changing settings.
- A settings notice is a non-gameplay overlay with a large Dismiss button.
  Dismiss gets first refusal on a left click in its target or on an activation
  command (`ACCEPT` or `OPEN_INVENTORY`); other inputs continue to the active
  mode. Dismissal clears only the notice. Window close remains available.
- `mouse_contract.py` extends — exhaustiveness tests force declaration:
  - CHARACTER_SELECT: `SELECT_CHARACTER` (left_click, portrait),
    `CONFIRM_STORY_PAGE` (left_click, story page), plus `QUIT`.
  - SYSTEM_MENU: `MENU_ACTIVATE` (left_click, menu row), plus `QUIT`.
  - All modes: `DISMISS_SETTINGS_ERROR` (left_click, Dismiss button) when the
    settings notice is present.
  - Remap capture is keyboard by nature and gets a documented legacy-style
    decision rather than a fake mouse route.
- Pointer: M3e's per-frame visibility rule already shows the OS cursor
  outside PLAY mouse mode, so shell modes get the OS pointer over their
  targets with no new code. Shell clicks route through the modal
  `route_mouse` path with honest hit geometry; the PLAY resolver is
  untouched.

## Error handling

- Settings file corrupt/incompatible/unknown-key → defaults plus a persistent
  named settings notice in every mode. An unwritable save keeps live settings
  and reports the destination and OS error. The error remains until the player
  activates its Dismiss button or keyboard activation route.
- Cadre bank or resource art missing/short → fail fast naming archive and
  entry. `cadre_bank()` parses sprite indices 0-8 from the entry's little-endian
  offset table: skip the four-byte sprite prefix, read u16 width/height, then
  read exactly width×height indexed pixels. Validate every range before the
  renderer uses it and convert with the existing game palette.
- Remap capture: Esc cancels without change; stealing clears the old binding.
- A modal always owns its input; the HUD is neither drawn nor hit-tested
  outside PLAY mouse mode (M3e rule unchanged).

## Automated verification

- Pure: reducers (menu wrap/activate, page transitions, capture/steal/cancel),
  control-list replacement and stealing, settings round-trip/defaults/
  corrupt-file/unwritable-save, compiled binding translation, transition
  drains, and one-tick sticky-action consumption.
- Real-data: cadre sprites 0-8 parse from ITD_RESS entry 4; frame placement and
  story half composition match FITD; both heroes' initial state after selection
  pins `CHOOSE_PERSO`, archive names, representative body/anim content, empty
  inventory, and correct life script. Goldens are measured, never guessed.
- Event-pump journeys (synthetic events through the real `run`, M3e harness
  pattern): boot → choose Emily → PLAY; boot → choose Carnby → story → PLAY;
  PLAY → Esc → menu → toggle sticky → remap a key → Return → new binding
  drives the hero; raw capture does not also activate a row; menu exit replays
  no held/queued input; death restart keeps settings; settings write and reload
  across a second boot. `make run` enters selection; explicit `--floor 0` and
  the two fixture flags bypass it. Corrupt-load and failed-save notices dismiss
  by keyboard and single-button mouse without changing the active mode.
- Mouse-contract exhaustiveness auto-covers the new modes/commands.
- Gates: `.venv/bin/pytest -q`, `make prove`, and a new focused
  `make prove-shell` for the shell journeys under dummy SDL drivers.
- TDD: every implementation task observes its new test failing before the
  production hunk lands.

## Manual windowed evidence

`docs/m4a1-shell-proof.md` in the M3e format, recorded with real data before
merge: both heroes selectable and starting correctly (keyboard and
single-button mouse), story page advance/start, menu open/navigate/config/
quit by mouse and keyboard, remap surviving a process restart, sticky action
in play, settings-error dismissal, modal responsiveness, and one visible cursor
in every mode.

## Assumptions and risks

- The cadre sprite bank layout is traced from `aitdBox.cpp`; the plan pins its
  parse and `AffBigCadre` placement with real-data tests before a renderer uses
  it. Character selection restores the portrait interior after the cadre's
  black fill; the system menu keeps the fill.
- `init_game(hero=)` already sets `CHOOSE_PERSO`, but current `Assets` always
  opens LISTBODY/LISTANIM. M4a1 must make archive selection hero-aware before
  claiming either protagonist path works.
- The settings file is the first persistence in the port; its JSON schema is
  deliberately separate from M4a2's save format so neither constrains the
  other.
- Normal boot uses a staging game to preserve `run(game)` and the current
  renderer/event-loop shape. It may load a hidden floor-zero scene, but it never
  ticks or presents PLAY before selection. This small redundant load is accepted
  to avoid an app-wide optional-`Game`/optional-`Floor` refactor.
- Boot-to-select changes the default startup path. Debug bypass and direct
  `init_game` proof calls keep existing focused proof targets unchanged.

## Planning boundary

This document defines the M4a1 behavior and verification contracts only. The
approved task-level TDD plan is
`docs/superpowers/plans/2026-08-24-m4a1-shell-and-configuration.md`. Do not fold
M4a2 persistence, M4b media, or M4c closure into that plan.
