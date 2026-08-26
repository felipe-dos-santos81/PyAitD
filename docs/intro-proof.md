# Opening cutscene proof

Date: 2026-08-26
Plan: `.superpowers/sdd/2026-08-26-intro-cutscene/`

This document was written and its automated evidence gathered on a machine
*with* real game data and a real GL context, so — unlike some earlier proof
docs in this repo — every command below, including the render, was actually
run here. The "Manual attestation" table is still a checklist for a human at
a keyboard with a real window: rendered PNGs and a headless pytest run are
not the same thing as watching the game play.

## What the cutscene does

Character confirmation stages FITD's scripted opening
(`startAITD1`, `AITD1.cpp:352-361`): `start_game(game, 7, 1)` boots floor 7,
room 1 with `allow_system_menu = False`, and the game plays itself —
the car pulling up to Derceto, a letter (`ShowPicture`), then a walk through
the house from floor 7 down through 3, 2 and 1 — with no player input
required. Any key, click, or touch during the opening sets
`session.skip_cutscene` and ends it immediately (`PlayerCapability.
SKIP_CUTSCENE`, `mainLoop.cpp:71-89`); reaching the end on its own raises
`effects.CutsceneFinished` instead of a real game over, because
`allow_system_menu = False` retargets `flag_game_over`. Either way the
shell hands off to the attic (`startGame(0, 0, 1)`) through the same
`_boot_hero` used for character confirmation. `--skip-intro` is a
development-only flag that skips staging the cutscene altogether.

## Pinned ticks (hero 0, Carnby)

Golden values from `tests/test_intro.py`, run headless via `play_tick` from
`start_game(7, 1)`:

| Event | Tick |
|---|---|
| Letter (`ShowPicture`) | 1081 |
| Floor 7 → 3 | 3217 |
| Floor 3 → 2 | 4919 |
| Floor 2 → 1 | 5652 |
| `CutsceneFinished` (terminal) | 7293 |

These are FITD-script-driven animation timings, not wall-clock; hero 1
(Emily) reaches `CutsceneFinished` at a different tick (7220, pinned in
`tests/test_shell_journeys.py::test_journey_opening_plays_to_the_end_then_the_attic`)
because her animations run on their own timing — only the floor sequence
(7 → 3 → 2 → 1 → attic) and the absence of a real `GameOver` are asserted
for her, not a tick number.

`tools/prove_intro.py` pins a related but distinct signal: *camera* changes,
not floor changes (a floor change and its first new camera are one tick
apart — the camera doesn't become valid until the tick after `start_game`/
`change_salle` stages it). Run on this machine's real data, the opening
visits 20 cameras:

```
0     floor 7 camera 3     954   floor 7 camera 4     1366  floor 7 camera 1
1498  floor 7 camera 0     1595  floor 7 camera 1      2463  floor 7 camera 2
3218  floor 3 camera 3     3745  floor 3 camera 2      4163  floor 3 camera 0
4482  floor 3 camera 1     4784  floor 3 camera 17      4920  floor 2 camera 37
5147  floor 2 camera 28    5653  floor 1 camera 14      6167  floor 1 camera 2
6301  floor 1 camera 3     6511  floor 1 camera 2      6655  floor 1 camera 3
6772  floor 1 camera 1     6876  floor 1 camera 0
```

(Also written to `docs/intro-proof/intro-ticks.txt` by every run — not
committed, see below.)

## `tools/prove_intro.py` / `make prove-intro`

`tools/prove_intro.py <data_dir> [--out docs/intro-proof] [--scale 2]` first
runs the intro headlessly (`visited_cameras`) to collect every `(tick,
floor, cam_idx)` at which the visible camera changes, from boot to
`CutsceneFinished`. It then re-runs the intro from tick 0 once per visited
camera (`render_camera`), building a `FrameDescription`
(`scene.build_frame`) and rendering it on a standalone ModernGL context
(`render_gl.GLBackend`), and writes one PNG per camera —
`intro-<floor>-<cam>-<tick>.png` — plus `intro-ticks.txt` under `--out`.

**Re-simulation cost**: `render_camera` re-runs `play_tick` from tick 0 for
every camera it renders rather than caching intermediate game state — up to
~7300 ticks, once per camera, for ~20 cameras. Measured on this machine:

```
$ time make prove-intro
...
make prove-intro  16.53s user 0.41s system 95% cpu 17.702 total
```

Under 18 seconds wall-clock for the full 20-camera render — acceptable for a
tool run on demand, not part of the test suite. If a future intro is longer
or has many more camera changes, the brief flagged this re-simulation
strategy as the first thing to reconsider; it was not necessary to change it
here.

It exits `3` with a message and no traceback if no standalone GL 3.3
context can be created (the CI path — `tests/test_prove_intro.py` does not
require GL, only `data_dir`).

`tests/test_prove_intro.py` covers the data-free argument parsing and its
defaults, and the one data-dependent check (`visited_cameras` covers every
intro floor in tick order, and `output_paths` matches the exact naming the
tool writes) which skips without real game data.

```
$ SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_prove_intro.py -q
..
2 passed in 2.12s
```

Both tests passed for real (not skipped) on this machine, since real game
data is present.

## Automated evidence

```
$ SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_prove_intro.py tests/test_layering.py -q
.............
13 passed in 1.51s
```

```
$ make prove-intro
SDL_VIDEODRIVER=dummy .venv/bin/python -m pytest tests/test_intro.py -q && .venv/bin/python tools/prove_intro.py "data/aitd1/.../INDARK"
....
4 passed in 1.40s
docs/intro-proof/intro-07-003-00000.png
docs/intro-proof/intro-07-004-00954.png
... (20 paths total, one per visited camera, see the tick table above)
```

```
$ SDL_VIDEODRIVER=dummy .venv/bin/pytest -q
990 passed, 1 skipped, 1 xfailed in 34.75s
```

The 1 skip and 1 xfail are pre-existing and unrelated to this task (a
combat-restart known limitation documented in `docs/m3c-combat-proof.md`;
this machine has no other data-gated skips because real game data is
present).

```
$ make prove && make prove-shell && make prove-mouse-only
4 passed
278 passed
16 passed
```

All green, including the two real-loop opening journeys in
`tests/test_shell_journeys.py` exercised by `prove-shell`
(`test_journey_opening_plays_to_the_end_then_the_attic`,
`test_journey_a_click_skips_the_opening`).

I opened two of the rendered PNGs to confirm the tool renders real frames,
not blanks: `intro-07-003-00000.png` (tick 0, floor 7 camera 3) is the
opening road/marsh view with the car in the distance; `intro-01-000-06876.png`
(tick 6876, floor 1 camera 0) is a Derceto interior stairwell near the end
of the walk. Both are real 640x400 (scale 2) renders with visible detail,
not blank frames.

## Manual attestation

None of the following has been performed by a human watching the real
window. Fill in `status` after doing so.

| Check | Status |
|---|---|
| Full opening plays start to finish (no input) | pending |
| Any key or click during the opening skips to the attic | pending |
| `--skip-intro` boots straight to the attic | pending |
| Rendered camera PNGs match what plays on screen | pending |

Notes for whoever performs these:

- **Full opening plays start to finish**: `make run data="path/to/INDARK"`,
  confirm a character, then wait without touching the keyboard or mouse.
  Confirm the car/road opening, the letter, and the walk down through
  floors 7 → 3 → 2 → 1 all play, ending in the attic with a game-over-free
  hand-off (no death/restart screen).
- **Any key or click skips**: repeat, but press any key or click partway
  through. Confirm the opening ends immediately and the attic loads.
- **`--skip-intro`**: `make run data="..." ` isn't enough — pass
  `--skip-intro` through the CLI (e.g. run `.venv/bin/python -m PyAitD
  --skip-intro --data "path/to/INDARK"`) and confirm character confirmation
  goes straight to the attic with no opening at all.
- **Rendered PNGs match**: open a few files from `docs/intro-proof/` after
  `make prove-intro data="..."` and compare them against what actually
  played during the full-opening check above — same locations, same camera
  angles, at the tick each was captured.

## PNGs are never committed

`docs/intro-proof/*.png` and `docs/intro-proof/intro-ticks.txt` are
git-ignored (`.gitignore`) — this repo never ships game data. Only
`docs/intro-proof/.gitkeep` is tracked, so the directory exists on a fresh
clone.
