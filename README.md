# maitd

Alone in the Dark 1 engine reimplementation in Python (pygame-ce + ModernGL),
driven by the original game data files. Apple Silicon, windowed. GPLv2
(derived from [FITD](https://github.com/yaz0r/FITD)).

You must own the original game — this repo never ships game data.

## Setup

```bash
make install          # or: python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

Data defaults to `Alone in the Dark 1.app/Contents/Resources/game/INDARK`;
override with `--data DIR` or env `M_AITD_DATA`.

## Run (M2: play viewer)

```bash
make run              # or: .venv/bin/python -m maitd --floor 0
```

Keys: arrows walk (Up forward, Left/Right turn), Esc quits. Cameras
switch by zone; actor occluded behind furniture via background masks.

## Tests / proof

```bash
make test             # unit suite
make prove            # walks every floor, decodes every camera image
```

`prove` prints one line per floor; a "room with no cameras (legit in
original data)" line is informational, not a failure.
