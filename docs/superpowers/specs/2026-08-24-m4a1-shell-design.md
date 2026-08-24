# Alone in the Dark 1 — M4a1 Shell and Configuration Design

Date: 2026-08-24
Status: Approved — planning input
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
2. **Boot flow:** the app boots into character selection. Debug flags
   (`--floor`, `--combat-venue`, `--mouse-combat-fixture`) bypass the shell
   straight into PLAY as today.
3. **Character selection mirrors the original screen** (ITD_RESS art, cadre
   frame, story page) rather than a port-native mock.
4. **System menu ships an honest subset** — Return to Game, Configuration,
   Quit — and grows Save/Load rows in M4a2. FITD's dead option rows
   (Music/Sound/Details, `systemMenu.cpp:93-113`) are not reproduced.
5. **Selection input is hit-tested and the click quirk is fixed** (details
   below); single-button users can reach both heroes and start the game.
6. **Configuration ships in full now:** remap screen, sticky action, and the
   per-user settings file (pulled forward from M4a2).
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
and presentation owner. Boot enters CHARACTER_SELECT; debug flags bypass to
PLAY exactly as today. Hero confirmation maps to `CVars[CHOOSE_PERSO]` and
starts PLAY with FITD-correct initial state (the plan verifies what
`init_game(hero=)` already parameterizes and reuses it).

### File map

| File | Responsibility in M4a1 |
|---|---|
| `PyAitD/effects.py` | 2 modes, 2 effect dataclasses. |
| `PyAitD/ui.py` | Presenters, reducers, renderers for select/menu/config; cadre renderer; hit geometry. Presentation only. |
| `PyAitD/assets.py` | `cadre_bank()` — ITD_RESS entry 4 sprite parsing. `resource_screen(10/14)` already exists. |
| `PyAitD/config.py` (new, pygame-free) | `Settings`, defaults, JSON load/save (atomic), `settings_path()`. |
| `PyAitD/__main__.py` | Boot into CHARACTER_SELECT; Esc opens menu in PLAY (Quit moves off Esc); shell routing; settings load at boot. |
| `PyAitD/mouse_contract.py` | Capabilities for the two new modes; exhaustiveness gate enforces them. |
| `PyAitD/input` handling (`ui.event_to_input`, `playworld.apply_play_input`) | Binding-table translation; sticky-action reduction. |
| `Makefile` | `prove-shell` focused target. |
| `docs/m4a1-shell-proof.md` | Windowed manual evidence, M3e format. |
| `CONTEXT.md` | Milestone row + shell boundary section. |

### Character selection

- **PORTRAITS phase:** `resource_screen(10)` full frame; cadre frame around
  the selected portrait; default left. Arrows/WASD move the frame,
  Enter/Space confirms it; a left click hit-tests either portrait and chooses
  that hero outright (honest target, one click, both heroes mouse-reachable).
- **STORY phase:** `resource_screen(14)` opposite half plus the hero's story
  text through the existing reading renderer. **Enter or click starts the
  game** — a deliberate, documented fix of FITD's logical-AND quirk
  (AITD1.cpp:292), which would otherwise trap single-button users in a
  portrait loop. Esc: story → portraits; portraits → clean app quit.
- **Start:** set `CVars[CHOOSE_PERSO]` (0 Carnby / 1 Emily), bind the per-hero
  body/anim archives, enter PLAY at floor 0 room 0. Real-data tests pin each
  hero's initial state.

### System menu

- **Trigger:** Esc in PLAY (`Command.CANCEL`) opens `OpenSystemMenu` instead
  of quitting the app; app-quit moves to the Quit row.
- **Pause:** a modal is active so `play_tick` does not run — the port already
  has FITD's `SaveTimerAnim`/`RestoreTimerAnim` semantics by construction.
  The existing modal-entry input flush and post-exit drain are unchanged.
- **Frame:** full-screen cadre frame (320x200) from the new cadre renderer.
- **Rows:** Return to Game / Configuration / Quit. Up/down wrap,
  Enter/Space activates, left-click hit-tests and activates a row, Esc exits
  to PLAY. Quit closes cleanly (OS cursor restored, renderer closed, exit 0).
- **Configuration page:** Sticky-action toggle row plus one row per
  remappable command. Activating a remap row enters capture state ("press a
  key…"); the next KEYDOWN binds it; Esc cancels. Binding an already-bound
  key steals it — the previous command is cleared (single-binding invariant).
  Changes apply immediately and persist on menu close.

### Configuration model and settings file (`config.py`, pygame-free)

- `Settings` dataclass: `bindings: dict[str, str]` (command name → pygame
  key name), `sticky_action: bool`. `DEFAULT_SETTINGS` matches today's
  hardcoded keys.
- Remap targets: the 8 `Command` members plus `ACTION` (the held Space
  input). Directions keep arrows + WASD as primary/alternate bindings.
- `settings_path()`: `~/Library/Application Support/PyAitD/settings.json` on
  macOS, `~/.config/pyaitd/settings.json` elsewhere. No new dependency.
- JSON: `{"schema": 1, "sticky_action": false, "bindings": {...}}`. Save via
  temp file + `os.replace`. Load validates commands and key names against
  known tables; any corruption → defaults plus a recoverable named error in
  the existing message bar. Never a crash, never a hidden wait.
- Settings live on the session, loaded once at boot, threaded into
  `event_to_input` and the menu reducers.
- Sticky action: tap Action, then a direction applies the action once
  without holding (accessibility contract). Implemented in the input
  reduction, gated by the setting; default off.

### Input routing and mouse contract

- `event_to_input` translates physical keys through
  `session.settings.bindings` instead of the hardcoded map; unbound commands
  produce nothing. Held-direction state keys off the same table.
- `mouse_contract.py` extends — exhaustiveness tests force declaration:
  - CHARACTER_SELECT: `SELECT_CHARACTER` (left_click, portrait),
    `CONFIRM_STORY_PAGE` (left_click, story page), plus `QUIT`.
  - SYSTEM_MENU: `MENU_ACTIVATE` (left_click, menu row), plus `QUIT`.
  - Remap capture is keyboard by nature and gets a documented legacy-style
    decision rather than a fake mouse route.
- Pointer: M3e's per-frame visibility rule already shows the OS cursor
  outside PLAY mouse mode, so shell modes get the OS pointer over their
  targets with no new code. Shell clicks route through the modal
  `route_mouse` path with honest hit geometry; the PLAY resolver is
  untouched.

## Error handling

- Settings file corrupt/incompatible → defaults + visible named error in the
  message bar (recoverable).
- Cadre bank or resource art missing/short → fail fast naming archive and
  entry.
- Remap capture: Esc cancels without change; stealing clears the old binding.
- A modal always owns its input; the HUD is neither drawn nor hit-tested
  outside PLAY mouse mode (M3e rule unchanged).

## Automated verification

- Pure: reducers (menu wrap/activate, page transitions, capture/steal/cancel,
  sticky interpretation), settings round-trip/defaults/corrupt-file, binding
  translation.
- Real-data: cadre bank parses from ITD_RESS entry 4; both heroes' initial
  state after selection (`CHOOSE_PERSO`, per-hero body/anim archives, empty
  inventory, correct life script). Goldens measured, never guessed.
- Event-pump journeys (synthetic events through the real `run`, M3e harness
  pattern): boot → choose Emily → PLAY; boot → choose Carnby → story → PLAY;
  PLAY → Esc → menu → toggle sticky → remap a key → Return → new binding
  drives the hero; settings written and re-loaded across a second boot.
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
in play, modal responsiveness, and one visible cursor in every mode.

## Assumptions and risks

- The cadre sprite bank layout is traced from `aitdBox.cpp`; the plan pins
  its parse with real-data tests before any renderer consumes it.
- `init_game(hero=)` already exists; the plan verifies its semantics cover
  the `CHOOSE_PERSO` archive binding rather than re-deriving it.
- The settings file is the first persistence in the port; its JSON schema is
  deliberately separate from M4a2's save format so neither constrains the
  other.
- Boot-to-select changes the default startup path; debug bypass keeps every
  existing proof target working unchanged.

## Planning boundary

This document defines the M4a1 behavior and verification contracts only.
After review approval, write one task-level TDD implementation plan for
M4a1. Do not fold M4a2 persistence, M4b media, or M4c closure into that plan.
