# PyAitD

Python engine reimplementation of **Alone in the Dark 1** (DOS, 1992).
pygame-ce + ModernGL, Apple Silicon, windowed. GPLv2.

**You must own the original game** — this repo never ships game data.

## Setup

```bash
make install            # .venv + editable install with dev deps
```

Game data defaults to `Alone in the Dark 1.app/Contents/Resources/game/INDARK`
at the repo root; override with `data=` on any make target or `--data DIR`.
Tests honor env `PYAITD_DATA` and skip when data is absent.

## Run

```bash
make run                # boots into character selection (floor=0 bypasses it for debugging)
```

Pick Emily or Carnby by mouse or keyboard, then play. Mouse (default):
left-click the floor to walk there, left-click an object to approach and use
it. Tab switches to the keyboard scheme (arrows/WASD walk, Space acts) and
back. Menus accept both throughout.

Keyboard: arrows/WASD walk, Space acts, Enter or I opens inventory,
Esc cancels — while playing it opens the system menu (Return / Configuration
/ Quit). Configuration offers control remapping and sticky Action
(one-finger sequential Space-then-direction); settings persist per user.
In menus: arrows move, Enter/Space accepts, Esc cancels. Mouse: single left
click on any large button. Found objects open a Take/Leave prompt; inventory
exposes the object's own actions; letters and books are readable; pictures
play full-screen.

## Tests

```bash
make test               # unit suite (real game data where available)
make prove              # parse-all + headless real-script boot
make prove-m3b          # focused interaction proof, headless
make prove-combat       # combat venue proof (M3c)
make prove-mouse        # navmesh coverage for every camera-visible room, headless
make prove-mouse-only   # one-button accessibility contract + journeys (M3e)
make prove-shell        # shell, configuration, mouse contract, real-loop journeys (M4a1)
```

## Status

M1 data layer, M2 actors, M3a LIFE script VM, M3b interaction, M3c combat,
M3d/M3e mouse-only input, and M4a1 shell (character select, system menu,
remappable controls, settings persistence) are done: the game boots into an
asset-faithful character selector and the attic is fully interactive by
mouse or keyboard. Next: M4a2 save/load, M4b audio/sequences, M4c ending.
See `CONTEXT.md` for the architecture map and `docs/superpowers/` for specs
and plans.
