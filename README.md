# maitd

Alone in the Dark 1 engine reimplementation in Python (pygame-ce + ModernGL),
driven by the original game data files. Apple Silicon, windowed.

License: GPLv2 (derived from FITD, https://github.com/yaz0r/FITD, GPLv2).
You must own the original game; this repo never ships game data.

## Setup

    python3 -m venv .venv
    .venv/bin/pip install -e ".[dev]"

Data defaults to `Alone in the Dark 1.app/Contents/Resources/game/INDARK`;
override with `--data DIR` or env `M_AITD_DATA`.

## Run (M1: room viewer)

    .venv/bin/python -m maitd --floor 0

Keys: Left/Right cycle cameras, Up/Down cycle rooms, Esc quits.

## Tests / proof

    .venv/bin/pytest -q
    .venv/bin/python scripts/prove_m1.py
