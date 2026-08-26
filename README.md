# PyAitD

Python engine reimplementation of **Alone in the Dark 1** (DOS, 1992).
pygame-ce + ModernGL, Apple Silicon, windowed. GPLv2.

**You must own the original game** — this repo never ships game data.

## Setup

```bash
make install            # .venv + editable install with dev deps
```

Game data defaults to `data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK`
at the repo root; override with `data=` on any make target or `--data DIR`.
Tests honor env `PYAITD_DATA` and skip when data is absent.

## Layout

```
PyAitD/engine/   simulation ported from FITD — no pygame, no GL, no game constants
PyAitD/render/   frame description → pixels (GL and software backends)
PyAitD/games/    per-game GameProfile + opcode handlers; aitd1/ is the only game
PyAitD/app/      window, event pump, settings, CLI
tools/           proofs, exporters, the AI regeneration script
```

`render/` and `games/` import only `engine/`; `engine/` imports none of the
others; `app/` may import everything. `tests/test_layering.py` enforces it. `AGENTS.md` says where new
code goes and how to split a module; `CONTEXT.md` maps every file.

## Run

```bash
make run                # boots into character selection (floor=0 bypasses it for debugging)
make run overrides=     # same, but with the original 320x200 backgrounds
make run-combat         # floor-5 combat venue (hero=0 Carnby, hero=1 Emily)
```

`make run` loads replacement backgrounds from `data/aitd1/overrides` by
default. That directory is git-ignored and this repo never ships it: if it is
absent, or a camera is missing from it, the game falls back to the original
asset silently. Point elsewhere with `overrides=DIR`, or pass an empty
`overrides=` to disable overrides for the run.

Pick Emily or Carnby by mouse or keyboard, then play. Mouse (default):
left-click the floor to walk there, left-click an object to approach and use
it. Pushable scenery shows an amber opposed-arrow cursor: press and hold the
left button to approach and push, then release to stop immediately. Moving the
pointer while holding does not change the target. Tab switches to the keyboard
scheme (arrows/WASD walk, Space acts) and back. Menus accept both throughout.

Keyboard: arrows/WASD walk, Space acts, Enter or I opens inventory,
Esc cancels — while playing it opens the system menu (Return / Configuration
/ Quit). Configuration offers control remapping and sticky Action
(one-finger sequential Space-then-direction); settings persist per user.
Choosing a control opens a key picker: press the physical key, or click one
of the on-screen key cells (or Cancel) so remapping needs no keyboard at all.
In menus: arrows move, Enter/Space accepts, Esc cancels. Mouse: single left
click on any large button. Found objects open a Take/Leave prompt; inventory
exposes the object's own actions; letters and books are readable; pictures
play full-screen.

The in-game Configuration screen's Graphics rows, and four CLI flags for a
single session, control the enhanced renderer: `--render-scale N` (1-8, the
internal render resolution as a multiple of 320x200), `--shading
{flat,lambert,smooth}` (per-actor lighting), `--background-filter
{nearest,bilinear,xbr}` (how the original 320x200 backgrounds are upscaled),
and `--overrides DIR` (a user-supplied replacement asset directory; this repo
still ships no game data — `make run` passes `data/aitd1/overrides` unless you
override or clear `overrides=`). An override directory holds
`DIR/backgrounds/floor<NN>/camera<NNN>.png` (any size) per camera and
`DIR/palette.png` (256 pixels wide) for the palette; a missing override file
falls back to the original asset silently, while one that exists but fails
to load logs a warning and falls back — the game never crashes on a bad
override. CLI flags apply only to the current session and are not persisted;
the Configuration screen's Graphics rows persist like every other setting.
If no GL 3.3 context is available, rendering falls back to the software
backend at scale 1 with a settings notice; the game always runs.

To regenerate the backgrounds with an external AI tool, `make
export-backgrounds` writes the originals plus structure guides and a
manifest into `data/aitd1/overrides` (git-ignored; `out=DIR` to choose another), and `make check-overrides`
validates the results the way the game loads them. `make regenerate-backgrounds`
(optional; needs the `agy` CLI on `PATH`, which it invokes once per camera for
the description and once for the image) does the
regeneration with Gemini into `data/aitd1/overrides-ai` (git-ignored, resumable; `dry=1` lists work). See
[docs/ai-background-regeneration.md](docs/ai-background-regeneration.md).

## Tests

```bash
make test               # unit suite (real game data where available)
make prove              # parse-all + headless real-script boot
make prove-m3b          # focused interaction proof, headless
make prove-combat       # combat venue proof (M3c)
make prove-mouse        # navmesh coverage for every camera-visible room, headless
make prove-mouse-only   # one-button accessibility contract + journeys (M3e)
make prove-shell        # shell, configuration, mouse contract, real-loop journeys (M4a1)
make prove-mouse-accessibility # focused effective-target, hover, touch, and takeover gate
make prove-graphics     # render attic + combat fixtures at every shading mode to docs/graphics-proof/
make check-overrides proof=1  # validate data/aitd1/overrides (or overrides=DIR); side-by-sides to docs/graphics-proof/overrides/
make regenerate-backgrounds dry=1  # list cameras the Gemini regeneration would process; no API calls
```

Mouse accessibility hardening is automated by `make prove-mouse-accessibility`
and has user-attested windowed standard-mouse and macOS Accessibility Keyboard
passes for Emily and Carnby. The current evidence in
the [mouse accessibility hardening proof](docs/mouse-accessibility-hardening-proof.md)
supersedes the older pending window checks in the
[M4a1 shell](docs/m4a1-shell-proof.md) and
[mouse hold-to-push](docs/mouse-hold-push-proof.md) proofs; the held-push
inventory takeover regression is covered and closed.

## Status

M1 data layer, M2 actors, M3a LIFE script VM, M3b interaction, M3c combat,
M3d/M3e mouse-only input (including held scenery pushing), M4a1 shell
(character select, system menu, remappable controls, settings persistence),
and the enhanced graphics scene layer (integer-scaled internal render target,
per-vertex shading, filtered backgrounds, override assets) are done: the game
boots into an asset-faithful character selector and the attic is fully
interactive by mouse or keyboard. Next: M4a2 save/load, M4b audio/sequences,
M4c ending.
See `CONTEXT.md` for the architecture map and `docs/superpowers/` for specs
and plans.
