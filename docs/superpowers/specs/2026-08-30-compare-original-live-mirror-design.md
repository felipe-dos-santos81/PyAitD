# Compare-With-Original Live Mirror — Design

Date: 2026-08-30
Status: approved in brainstorming (2026-08-30), pending spec review
Scope: one milestone-sized feature; a permanent comparison tool, not a game
behaviour change.

## Purpose

Run the original DOS Alone in the Dark 1 (bundled inside the Mac game-data
`.app`) in a DOSBox-X window stacked below our port's window, and forward the
keyboard input our port actually consumes into the original, live, so a human
can watch both and compare. The mirror is qualitative: both runtimes are
real-time and independent; small drift over long sessions is expected and
accepted.

Decisions taken in brainstorming:

- Live mirror (not scripted replay).
- PLAY-only forwarding: movement/action keys forward only while our port is
  in PLAY with no modal; menus, modals and cutscenes in the original are
  navigated by hand, and the player aligns both games to the same starting
  point before playing (alignment automation is out of scope).
- Permanent deliverable: a `make compare` target, tested where headless
  testing is possible, documented like the other proofs.

## Verified environment facts (spike, 2026-08-30)

- `/opt/homebrew/bin/dosbox-x` boots the bundled original windowed from
  `data/aitd1/Alone in the Dark 1.app/Contents/Resources` (CWD), mounting
  `game/` as `C:` and `GAME.INS` as `D:`; the bundled conf is defaults-only,
  so a small generated conf with `fullscreen=false`,
  `windowresolution=640x400` and an autoexec that skips the interactive
  launcher (`CD INDARK` + `INDARK`) is all that is needed. The window title
  becomes `DOSBox-X <ver>: INDARK - …` once `INDARK.EXE` runs.
- `CGEventPostToPid` delivers synthetic key events to the unfocused DOSBox-X
  window and drives the game (proven by a before/after screenshot diff of the
  intro: three down-arrows + Return advanced the intro page).
- `CGWindowListCopyWindowInfo` still enumerates windows (pid/bounds) without
  TCC grants; ScreenCaptureKit `SCScreenshotManager` can capture the DOSBox-X
  window in this user context (Screen Recording), but capture is NOT a
  runtime dependency of this milestone. `CGWindowListCreateImage` is
  unavailable in current macOS SDKs.
- The original's keyboard layout, per the FITD authority
  (`FitdLib/input.cpp` `readKeyboard`): arrows drive `JoyD`, Space drives
  `Click`, Return drives key `0x1C`, Escape drives `0x1B`.

## Components

Four units, each with one purpose. Layering follows AGENTS.md: process
spawning lives in `tools/`; the per-game key fact lives in `games/aitd1/`;
the pump tap and sink live in `app/` (which may import everything); the
Swift helper owns CGEvents.

### `tools/mirror_helper.swift` — the OS bridge

Compiled once on first run with `swiftc` (cached under a git-ignored
`tools/.cache/`; compiler output surfaced on failure). Resident process
reading lines from stdin:

- `post <mac_keycode> <down|up> <pid>` — posts a `CGEvent` keyboard pair via
  `CGEventPostToPid`. A dead pid is reported once on stdout
  (`DEAD <pid>`) and further posts are no-ops.
- `window <needle>` — prints `pid x y w h` of the first on-screen window
  whose owner or title contains the needle (CoreGraphics window list).

No new Python dependencies; `swiftc` ships with Xcode CLT.

### `PyAitD/games/aitd1/mirror.py` — the translation table

The AITD1-specific fact, keyed by control NAME strings (the `Control` enum
lives in `app/config.py`, so this module imports nothing from `app/`):

| control name | original key | macOS virtual keycode |
|---|---|---|
| `UP` / `DOWN` / `LEFT` / `RIGHT` | arrows (`JoyD`) | 126 / 125 / 123 / 124 |
| `ACTION` | Space (`Click`) | 49 |
| `INVENTORY_CONFIRM` | Return (`0x1C`) | 36 |

Each entry cites `FitdLib/input.cpp`. Nothing else forwards: Escape,
inventory open, and every other key stay manual in the original.

### `PyAitD/app/mirror.py` — the sink

`MirrorSink(write_line, pid)`: `key_down(name)` / `key_up(name)` translate
through the table and emit one `post <keycode> <down|up> <pid>` line each;
unknown names are ignored. The sink never blocks on the helper: the pipe is
line-buffered and the helper is a separate process.

### `PyAitD/app/shell.py` — the pump tap (the only in-tree change)

- New CLI flag `--mirror`.
- When set and the env var `PYAITD_MIRROR_FD` names an inherited writable
  fd, `main()` constructs a `MirrorSink` over it; otherwise the flag is
  inert.
- The pump calls `sink.key_down/up(control.name)` exactly where it consumes
  a keyboard event that mapped to a forwarded control, and only while
  `game.mode is GameMode.PLAY` with no active modal. Mouse-mode play,
  mouse action pulses, and double-press run produce no forwarded events
  (run is a speed; the original walks).

### `tools/compare_original.py` — the orchestrator

1. Startup checks with clear messages: `dosbox-x` on PATH; bundled DOS data
   present (`INDARK/`, `GAME.INS`, `GAME.GOG`); helper compiled.
2. Generate the windowed conf in a temp dir; spawn `dosbox-x` with CWD at the
   game-data `Resources` dir; poll `window dosbox` until the window appears.
3. Spawn the helper resident; set `SDL_VIDEO_WINDOW_POS` and default
   `--render-scale 2` for our port (640x400 content, matching the DOSBox
   window width); export `PYAITD_MIRROR_FD`.
4. Once both windows exist, query our real bounds with the helper's
   `window pyaitd` (run() sets the caption prefix `PyAitD`) and place the
   DOSBox window directly below via System Events (`osascript`); on any
   failure print manual placement instructions and continue — placement is
   a courtesy, not a dependency.
5. Run our port in-process (`PyAitD.app.shell.main`); teardown helper +
   dosbox-x in `finally` on any exit path.

### Makefile + proof doc

- `make compare` runs `tools/compare_original.py` with the default data dir
  (not headless — real windows).
- `docs/compare-original-proof.md` records the manual run plus the spike
  evidence (intro before/after frames), like the other proof docs.

## Error handling and permissions

- Posting synthetic keys requires the terminal to hold macOS Accessibility
  (one-time grant); the orchestrator prints the instruction at startup.
  Screen Recording is not required at runtime.
- DOSBox-X boot failure: print the log tail, exit non-zero.
- Helper compile failure: print `swiftc` output, exit non-zero.
- DOSBox-X dying mid-session: helper reports `DEAD <pid>` once; the sink
  degrades to a logged no-op; the port keeps running.

## Testing

Headless, in `make test`:

- `tests/test_mirror_table.py` (engine-marked): every forwarded control name
  has a keycode; the table contents pinned to the FITD citation.
- `tests/test_mirror_sink.py` (shell-marked): sink with a fake writer
  forwards only tabled controls, emits down/up pairs, correct line format;
  the shell tap (fake sink) fires on forwarded keyboard events in PLAY and
  stays silent in mouse mode and with a modal open.
- Orchestrator pure parts (shell-marked): generated conf text (windowed,
  launcher-skipping autoexec), placement math (our rect in, DOSBox rect out),
  arg parsing.

Not CI-able (GUI + permissions): real DOSBox boot, CGEvent delivery, window
stacking — covered by the manual `make compare` proof run.

## Out of scope

Alignment automation between the two games; frame capture / `--verify`
auto-diff (spike proved feasibility, deliberately deferred); audio
comparison; any lockstep or deterministic sync; forwarding of menu/modal
keys.
