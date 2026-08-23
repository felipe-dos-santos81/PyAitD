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
make run                # make run floor=3 data="path/to/INDARK" trace=/tmp/t.log
```

Mouse (default): left-click the floor to walk there, left-click an object to
approach and use it. Tab switches to the keyboard scheme (arrows/WASD walk,
Space acts) and back. Menus accept both throughout.

Keyboard: arrows/WASD walk, Space acts, Enter or I opens inventory,
Esc cancels (quits while playing). In menus: arrows move, Enter/Space
accepts, Esc cancels. Mouse: single left click on any large button.
Found objects open a Take/Leave prompt; inventory exposes the object's
own actions; letters and books are readable; pictures play full-screen.

## Tests

```bash
make test               # unit suite (real game data where available)
make prove              # parse-all + headless real-script boot
make prove-m3b          # focused interaction proof, headless
make prove-mouse        # navmesh coverage for every camera-visible room, headless
```

## Status

M1 data layer, M2 actors, M3a LIFE script VM, M3b interaction, M3d
mouse-only input are done: the attic boots from original scripts and is
fully interactive by mouse or keyboard. Combat (M3c) and menus/audio/save
(M4) are next. See `CONTEXT.md` for the architecture map and
`docs/superpowers/` for specs and plans.
