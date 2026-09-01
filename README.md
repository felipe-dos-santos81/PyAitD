# PyAitD

Python engine reimplementation of **Alone in the Dark 1** (DOS, 1992).
pygame-ce + ModernGL, Apple Silicon, windowed. GPLv2.

This port is inspired by [FITD](https://github.com/yaz0r/FITD) and
[AloneInTheDarkReHaunted](https://github.com/spacefarergames/AloneInTheDarkReHaunted).
It aims to improve the game's accessibility (mouse-only play, remappable
controls, sticky actions) and is built for **educational purposes only**.

**You must own the original game** — this repo never ships game data.

## Setup

```bash
make install            # .venv + editable install with dev deps
```

Add your legally owned base game files to
`data/aitd1/Alone in the Dark 1.app/Contents/Resources/game/INDARK`
at the repo root — i.e. copy the original game's `INDARK` directory (the one
holding the `.PAK` archives) into that path, keeping the `.app` folder
structure shown. If your copy lives elsewhere, override with `data=` on any
make target or `--data DIR`.
Tests honor env `PYAITD_DATA` and skip when data is absent.

## Layout

```
PyAitD/engine/   simulation ported from FITD — no pygame, no GL, no game constants
PyAitD/render/   frame description → pixels (GL and software backends)
PyAitD/games/    per-game GameProfile + opcode handlers; aitd1/ is the only game
PyAitD/app/      window, event pump, settings, CLI
tools/           proofs, texture exporters, the materials bootstrap,
                 the compare-with-original harness (DOSBox-X + CGEvent helper)
```

`render/` and `games/` import only `engine/`; `engine/` imports none of the
others; `app/` may import everything. `tests/test_layering.py` enforces it. `AGENTS.md` says where new
code goes and how to split a module; `CONTEXT.md` maps every file.

## Run

```bash
make run                # boots into character selection (floor=0 bypasses it for debugging)
make run textures=      # same, but with the original 320x200 backgrounds
make run-combat         # floor-5 combat venue (hero=0 Carnby, hero=1 Emily)
make compare            # live mirror: original AITD1 in DOSBox-X below the port (macOS)
```

`make run` loads replacement textures from `data/aitd1/textures` by
default. That directory is git-ignored and this repo never ships it: if it is
absent, or a camera is missing from it, the game falls back to the original
asset silently. Point elsewhere with `textures=DIR`, or pass an empty
`textures=` to disable replacement textures for the run.

Pick Emily or Carnby by mouse or keyboard, then play. Mouse (default): press
and hold the left button — the hero walks toward the pointer and keeps
following it while you hold; press twice in quick succession and hold the
second press to run instead of walk (the mouse's reading of the keyboard's
double-tap forward); hold over an object to approach and use it;
release to stop immediately. Pushable scenery shows an amber opposed-arrow
cursor: press and hold to approach and push (the push target stays latched
while you hold), release to stop. Armed enemies and the inventory button
answer a single press. The OS cursor is never locked or grabbed. Tab switches
to the keyboard scheme (arrows/WASD walk, Space acts) and back. Menus accept
both throughout.

Keyboard: arrows/WASD walk, Space acts, Enter or I opens inventory,
Esc cancels — while playing it opens the system menu (Return to Game /
Save / Load / Quick Save / Configuration / Quit). Configuration offers
control remapping and sticky Action
(one-finger sequential Space-then-direction); settings persist per user.
Choosing a control opens a key picker: press the physical key, or click one
of the on-screen key cells (or Cancel) so remapping needs no keyboard at all.
In menus: arrows move, Enter/Space accepts, Esc cancels. Mouse: single left
click on any large button. Found objects open a Take/Leave prompt; inventory
exposes the object's own actions; letters and books are readable; pictures
play full-screen.

Save and load: the system menu's Save writes `save-manual.json`; Load lists
`save-manual.json` and `save-quick.json` (a missing slot's row is dimmed and
inert); Quick Save closes the menu and writes `save-quick.json` at the first
stable tick. Slots live beside the settings file (`--save-dir DIR` points
elsewhere). A load validates the whole file — schema, counts, and a digest of
the game data it was written from — before the live game is touched, and the
restored session lands back in play with clean pointer state; any failure
leaves the running game untouched and raises the dismissible notice. Manual
save is refused while a script continuation is pending.

`make compare` runs the original DOS game (bundled inside the Mac `.app`) in
DOSBox-X in a window stacked below ours and live-forwards every keyboard
control the port consumes while playing (keyboard input mode) into it, for
side-by-side comparison. macOS only; needs `dosbox-x` and a one-time
Accessibility grant; see `docs/compare-original-proof.md`.

The in-game Configuration screen's Graphics page, and ten CLI flags for a
single session, control the enhanced renderer: `--render-scale N` (1-8, the
internal render resolution as a multiple of 320x200), `--shading
{flat,lambert,smooth}` (the per-actor shading model: where surface normals
come from), `--background-filter {nearest,bilinear,xbr}` (how the original
320x200 backgrounds are upscaled),
`--lighting {fixed,scene}` (`fixed` is the old hard-coded rig; `scene`
estimates each camera's light direction and colour from its own background
image and casts a ground shadow under every actor), `--msaa {0,2,4,8}`
(multisampling on the internal render target),
`--realism {classic,enhanced}` (`classic` is the flat-material look;
`enhanced` gives every surface a material — a normalised specular lobe,
rim, occlusion, and a procedural detail field that is both a colour grain
and real relief, lit by a derivative bump that fades out before it can
alias; skin also gets a warm terminator, and a flame's palette ramp
renders as emissive whatever the light does — from a palette-index table
in `PyAitD/render/materials.json`, which `make export-textures`
regenerates and a texture directory can remap per body under
`DIR/bodies/body<NNN>.json` (re-running the bootstrap without the hand
labels each ramp's `note` records silently reintroduces the survey's
heuristic and vision-model guesses in place of the reviewed class —
`docs/materials-v2-proof.md`'s Known limitations covers this); that
document records the per-class numbers and what each was traded
against),
`--smoothing {0,1,2,3}` (GPU mesh smoothing: `0` draws the flat 1992 mesh,
`1`–`3` round every body with 4/16/64 curved sub-triangles per face, keeping
edges sharper than 80° — overridable per body with a `"crease"` degrees key
in `DIR/bodies/body<NNN>.json`),
`--shadows {hard,soft}` (`hard` is the flat projected silhouette; `soft`
gives every shadow a penumbra that hardens where the actor meets the ground,
composites every actor's shadow once before any body is drawn, and lets
limbs and actors shadow each other through a light-view depth map),
`--motion {tick,smooth}` (`smooth`, the default, blends actor motion between
simulation ticks at the display rate; `tick` renders one pose per 50 Hz
tick),
`--integration {0,1,2,3}` (how much of the room's own picture the actors take
on: any level above 0 resolves the bodies into their own layer and composites
them back — softened or pixelated to the plate's cell, clamped into the
range the room can actually print (nothing darker than its floor, nothing
brighter than its ceiling, and no opinion about a value already in between),
and grained with a dither built the way the background filter built the
room's own — so the actors sit inside the room rather than on top of it. 2 is the full match and the
default, 1 does half of it, 3 half again as much; 0 is the previous
single-target path, which draws the bodies straight over the plate. The
option's original `off` and `on` still parse as 0 and 2),
and `--textures DIR` (a user-supplied replacement asset directory; this repo
still ships no game data — `make run` passes `data/aitd1/textures` unless you
point or clear `textures=`). A texture directory holds
`DIR/backgrounds/floor<NN>/camera<NNN>.png` (any size) per camera and
`DIR/palette.png` (256 pixels wide) for the palette, and `DIR/bodies/body<NNN>.json`
(a per-body material remap and, optionally, its `crease` threshold); a missing texture file
falls back to the original asset silently, while one that exists but fails
to load logs a warning and falls back — the game never crashes on a bad
texture file. CLI flags apply only to the current session and are not persisted;
the Graphics page's rows persist like every other setting.
If no GL 3.3 context is available, rendering falls back to the software
backend at scale 1 with a settings notice; the game always runs.

The UI layer — character selection, the inventory, menus, messages and the
cursor — is drawn at the window's own resolution rather than at 320x200, so
its text stays sharp at any window size. It is authored in 320x200
coordinates regardless, which is what keeps mouse targets and what you see
in step.

To regenerate the backgrounds with an external tool, `make export-textures`
writes the originals plus structure guides, a layout sidecar per camera (the
guide's geometry as JSON, used to describe and verify the scene) and a
manifest (`manifest.json`) into `data/aitd1/textures` (git-ignored; `out=DIR`
to choose another), then surveys palette ramps and body usage into
`materials-survey/` beside them and emits `PyAitD/render/materials.json`
(`materials=0` skips that half), and `make check-textures` validates the results the way
the game loads them. The regeneration itself happens outside this repo;
`make run textures=DIR` plays the game against the directory.

## Tests

```bash
make test                          # whole pytest suite, headless (real game data where available)
make test-engine                   # simulation, LIFE VM, formats, actors, anim, tracks, collision, navmesh, picking, opcodes
make test-render                   # scene, geometry, both backends, asset resolution, texture export/check
make test-shell                    # event pump, settings, CLI, UI screens and modals
make test-tools                    # the standalone scripts under tools/
make test-meta                     # the repo's own rules (package layering, test grouping)
make test-journey                  # real run() event pump and long real-data simulations
make proof-mouse                   # navmesh coverage for every camera-visible room, every floor (needs game data)
make proof-combat                  # combat venue proof: real enemy damage, player arms, game over (needs game data)
make proof-graphics                # render attic + combat fixtures at every shading mode, plus flat-mesh and hard-shadow pairs, to docs/graphics-proof/ (needs GL + game data)
make proof-intro                   # opening cutscene: headless gate + one GL render per visited camera
make prove-persistence             # M4a2 gate: save schema, slots, restoration, menu pages, loop policy, journeys, mouse contract
make check-textures proof=1        # validate data/aitd1/textures (or textures=DIR); side-by-sides to docs/graphics-proof/textures/
```

The nine legacy `prove-*` names (`prove`, `prove-m3b`, `prove-shell`,
`prove-mouse-only`, `prove-mouse`, `prove-mouse-accessibility`,
`prove-combat`, `prove-graphics`, `prove-intro`) remain as aliases of the
targets above -- see `AGENTS.md` and `CONTEXT.md`'s `## Test grouping`
section for exactly what each one aliases.

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
M4a2 save/load (versioned slots, source-identity validation, atomic load
replacement, deferred quick save), the full enhanced-rendering roadmap (soft
shadows, plate integration, materials, integration levels) and the
compare-with-original live mirror (`make compare`) are done: the game boots
into an asset-faithful character selector, the attic is fully interactive by
mouse or keyboard, and progress persists across sessions. Next: M4b
audio/sequences, M4c ending.
See `CONTEXT.md` for the architecture map and `docs/superpowers/` for specs
and plans.
