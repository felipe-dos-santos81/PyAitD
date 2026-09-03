# PyAitD

Python engine reimplementation of **Alone in the Dark 1** (DOS, 1992).
pygame-ce + ModernGL, Apple Silicon, windowed. GPLv2.

Inspired by [FITD](https://github.com/yaz0r/FITD) and
[AloneInTheDarkReHaunted](https://github.com/spacefarergames/AloneInTheDarkReHaunted).
It aims to improve accessibility (mouse-only play, remappable controls, sticky
actions) and is built for **educational purposes only**.

**You must own the original game** — this repo never ships game data.

## Setup

```bash
make install    # .venv + editable install with dev deps
```

Copy the original game's `INDARK` directory (the one holding the `.PAK`
archives) to:

```
data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK
```

Override with `data=DIR` on any make target or `--data DIR`. Tests honor
`PYAITD_DATA` and skip when data is absent.

## Run

```bash
make run             # character selection, then play
make run textures=   # same, with the original 320x200 backgrounds
make run-combat      # floor-5 combat venue (hero=0 Carnby, hero=1 Emily)
make compare         # live mirror: original AITD1 in DOSBox-X below the port (macOS)
```

`make run` loads replacement textures from `data/aitd1/textures` if present
(git-ignored, never shipped); anything missing falls back to the original asset
silently. `textures=DIR` points elsewhere, empty `textures=` disables them.

### Controls

**Mouse (default).** Press and hold the left button — the hero walks toward the
pointer and keeps following it while you hold; release stops immediately. Press
twice quickly and hold the second press to run. Every pixel is walkable: a spot
with no reachable floor under it walks the hero in that *direction* instead of
refusing. Hold over an object to approach and use it. A diamond marks the
destination (faint before you press, solid while you hold) and a ring around the
cursor shows the button is down. Pushable scenery shows an amber opposed-arrow
cursor: hold to approach and push. Armed enemies and the inventory button answer
a single press. A red X is now rare: an attack with an empty hand or mid-swing,
or a pointer with no bearing to take because the hero's feet are off screen. The
OS cursor is never locked or grabbed.

**Keyboard.** Arrows/WASD walk, Space acts, Enter or I opens inventory, Esc
opens the system menu (Return to Game / Save / Load / Quick Save /
Configuration / Quit). Tab switches schemes; menus accept both throughout.

**Menus.** Arrows move, Enter/Space accepts, Esc cancels, or single-click any
button. Configuration offers control remapping, sticky Action (one-finger
Space-then-direction), and the Graphics and Realism renderer pages; settings
persist per user. A key picker accepts a physical key press or a click on an
on-screen key cell, so remapping needs no keyboard at all. Found objects open a
Take/Leave prompt; inventory exposes each object's own actions; letters and
books are readable; pictures play full-screen.

### Save and load

Save writes `save-manual.json`; Quick Save writes `save-quick.json` at the first
stable tick; Load lists both (a missing slot is dimmed and inert). Slots live
beside the settings file (`--save-dir DIR`). A load validates schema, counts and
a digest of the source game data before the live game is touched — any failure
leaves the running session untouched. Manual save is refused while a script
continuation is pending.

## Renderer options

The Configuration screen's **Graphics** page (display knobs) and **Realism**
page (lighting and motion) persist like any other setting. The same knobs are
available as CLI flags for a single session only — never persisted.

| Flag | Values (default **bold**) | Effect |
|---|---|---|
| `--render-scale` | 1–8 (**4**) | internal render resolution, in multiples of 320x200 |
| `--shading` | flat, lambert, **smooth** | where per-actor surface normals come from |
| `--background-filter` | nearest, **bilinear**, xbr | how the 320x200 backgrounds are upscaled |
| `--msaa` | 0, 2, **4**, 8 | multisampling on the internal render target |
| `--lighting` | fixed, **scene** | `scene` estimates each camera's light from its own background and casts a ground shadow |
| `--realism` | classic, **enhanced** | `enhanced` gives every surface a material (specular, rim, occlusion, detail relief, warm skin, emissive flame) |
| `--smoothing` | 0, 1, **2**, 3 | GPU mesh smoothing: 4/16/64 curved sub-triangles per face, edges past 80° stay sharp |
| `--shadows` | hard, **soft**, room | `soft` adds penumbra and inter-actor shadowing; `room` also drapes shadows over floor and collision boxes |
| `--integration` | 0, 1, **2**, 3 | how much of the room's own picture the actors take on (grain, cell, value range) |
| `--motion` | tick, **smooth** | `smooth` blends actor motion between 50 Hz ticks at display rate |
| `--occlusion` | off, **ssao** | half-res screen-space ambient occlusion over the actor layer |
| `--atmosphere` | off, **on** | past 2500 units, fades actors toward the room's ambient tone |
| `--textures` | DIR | replacement asset directory (see below) |

`--integration`'s original `off`/`on` still parse as 0 and 2. `--atmosphere`
applies under `--lighting scene` with `--integration 1` or above. Without a
GL 3.3 context the software backend takes over at scale 1 with a settings
notice; the game always runs. Per-class numbers and trade-offs live in
`docs/materials-v2-proof.md` and the other renderer proofs under `docs/`.

The UI layer — character select, inventory, menus, messages, cursor — is drawn
at the window's resolution so its text stays sharp, but authored in 320x200
coordinates, which keeps mouse targets and what you see in step.

### Texture directories

A texture directory holds `backgrounds/floor<NN>/camera<NNN>.png` (any size),
`palette.png` (256px wide), `bodies/body<NNN>.json` (material remap, optional
`crease` degrees), and `bodies/body<NNN>.png` (a painted albedo atlas sampled in
place of palette-ramp colour, laid out to `bodies/body<NNN>.uv.json`). A missing
file falls back silently; a corrupt one logs a warning and falls back. The game
never crashes on a bad texture file.

```bash
make export-textures      # originals + guides + UV sidecars + manifest.json, then the materials survey
make check-textures       # validate a directory the way the game loads it
```

`out=DIR` chooses the destination, `uvs=0` skips the body guides, `materials=0`
skips the survey half. Painting itself happens outside this repo; play against
the result with `make run textures=DIR`.

## Layout

```
PyAitD/engine/   simulation ported from FITD — no pygame, no GL, no game constants
PyAitD/render/   frame description → pixels (GL and software backends)
PyAitD/games/    per-game GameProfile + opcode handlers; aitd1/ is the only game
PyAitD/app/      window, event pump, settings, CLI
tools/           proofs, texture exporters, materials bootstrap, compare harness
```

`render/` and `games/` import only `engine/`; `engine/` imports none of the
others; `app/` may import everything, and `tests/test_layering.py` enforces it.
`AGENTS.md` says where new code goes; `CONTEXT.md` maps every file.

## Tests

```bash
make test              # whole suite, headless (real game data where available)
make test-engine       # simulation, LIFE VM, formats, actors, anim, collision, navmesh, picking
make test-render       # scene, geometry, both backends, asset resolution, texture export/check
make test-shell        # event pump, settings, CLI, UI screens and modals
make test-tools        # the standalone scripts under tools/
make test-meta         # the repo's own rules (package layering, test grouping)
make test-journey      # real run() event pump and long real-data simulations
```

Proof targets (most need game data, some need GL):

```bash
make proof-mouse           # navmesh coverage for every camera-visible room, every floor
make proof-combat          # real enemy damage, player arms, game over
make proof-graphics        # every shading x realism pair, plus each renderer knob's off/on pair
make proof-intro           # opening cutscene: headless gate + one GL render per camera
make prove-persistence     # save schema, slots, restoration, menu pages, journeys, mouse contract
make check-textures proof=1  # validate a texture directory, side-by-sides to docs/graphics-proof/
```

The nine legacy `prove-*` names remain as aliases; `CONTEXT.md`'s
`## Test grouping` section says what each one maps to.

Mouse accessibility is automated by `make prove-mouse-accessibility` and has
user-attested windowed standard-mouse and macOS Accessibility Keyboard passes
for both heroes — see the
[hardening proof](docs/mouse-accessibility-hardening-proof.md), which
supersedes the pending window checks in the older
[M4a1 shell](docs/m4a1-shell-proof.md) and
[hold-to-push](docs/mouse-hold-push-proof.md) proofs.

## Status

Done: M1 data layer, M2 actors, M3a LIFE script VM, M3b interaction, M3c
combat, M3d/M3e mouse-only input, M4a1 shell, M4a2 save/load, the full
enhanced-rendering roadmap, all four of roadmap 2's sub-projects (motion
interpolation, actor surface textures, light transport, atmosphere), and the
`make compare` live mirror. The game boots into an asset-faithful character
selector, the attic is fully interactive by mouse or keyboard, and progress
persists across sessions. Several renderer-proof attestation rows still await a
human's eye on real fixtures.

Next: M4b audio/sequences, M4c ending.

See `CONTEXT.md` for the architecture map and `docs/superpowers/` for specs and
plans.
