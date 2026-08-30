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
Esc cancels — while playing it opens the system menu (Return / Configuration
/ Quit). Configuration offers control remapping and sticky Action
(one-finger sequential Space-then-direction); settings persist per user.
Choosing a control opens a key picker: press the physical key, or click one
of the on-screen key cells (or Cancel) so remapping needs no keyboard at all.
In menus: arrows move, Enter/Space accepts, Esc cancels. Mouse: single left
click on any large button. Found objects open a Take/Leave prompt; inventory
exposes the object's own actions; letters and books are readable; pictures
play full-screen.

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
in `PyAitD/render/materials.json`, which `make bootstrap-materials`
regenerates and an override directory can remap per body under
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
`--integration {off,on}` (`on` resolves the bodies into their own layer and
composites them back through the room's own picture — softened or pixelated
to the plate's cell, lifted to the room's black, pulled to its white, and
grained at the plate's *displayed* amplitude — the source dither scaled by
whatever the background filter actually leaves at the cell size, not the
dither the plate image was stored with — so the actors sit inside the room
rather than on top of it; `off` is the previous single-target path, which
draws the bodies straight over the plate),
and `--overrides DIR` (a user-supplied replacement asset directory; this repo
still ships no game data — `make run` passes `data/aitd1/overrides` unless you
override or clear `overrides=`). An override directory holds
`DIR/backgrounds/floor<NN>/camera<NNN>.png` (any size) per camera and
`DIR/palette.png` (256 pixels wide) for the palette, and `DIR/bodies/body<NNN>.json`
(a per-body material remap and, optionally, its `crease` threshold); a missing override file
falls back to the original asset silently, while one that exists but fails
to load logs a warning and falls back — the game never crashes on a bad
override. CLI flags apply only to the current session and are not persisted;
the Graphics page's rows persist like every other setting.
If no GL 3.3 context is available, rendering falls back to the software
backend at scale 1 with a settings notice; the game always runs.

The UI layer — character selection, the inventory, menus, messages and the
cursor — is drawn at the window's own resolution rather than at 320x200, so
its text stays sharp at any window size. It is authored in 320x200
coordinates regardless, which is what keeps mouse targets and what you see
in step.

To regenerate the backgrounds with an external AI tool, `make
export-backgrounds` writes the originals plus structure guides, a layout
sidecar per camera (the guide's geometry as JSON, used to describe and verify
the scene) and a manifest into `data/aitd1/overrides` (git-ignored; `out=DIR` to choose another), and `make check-overrides`
validates the results the way the game loads them. `make regenerate-backgrounds`
(optional; needs the `agy` CLI on `PATH`; per camera it asks for a structured
inventory, dictates the image call, and verifies every attempt with an offline
gate plus a vision judge, rejecting plates that move or change objects) does
the regeneration with Gemini into `data/aitd1/overrides-ai` (git-ignored, resumable; `dry=1` lists work). See
[docs/ai-background-regeneration.md](docs/ai-background-regeneration.md).

## Tests

```bash
make test                          # whole pytest suite, headless (real game data where available)
make test-engine                   # simulation, LIFE VM, formats, actors, anim, tracks, collision, navmesh, picking, opcodes
make test-render                   # scene, geometry, both backends, asset resolution, override export/check
make test-shell                    # event pump, settings, CLI, UI screens and modals
make test-tools                    # the standalone scripts under tools/
make test-meta                     # the repo's own rules (package layering, test grouping)
make test-journey                  # real run() event pump and long real-data simulations
make proof-mouse                   # navmesh coverage for every camera-visible room, every floor (needs game data)
make proof-combat                  # combat venue proof: real enemy damage, player arms, game over (needs game data)
make proof-graphics                # render attic + combat fixtures at every shading mode, plus flat-mesh and hard-shadow pairs, to docs/graphics-proof/ (needs GL + game data)
make proof-intro                   # opening cutscene: headless gate + one GL render per visited camera
make check-overrides proof=1       # validate data/aitd1/overrides (or overrides=DIR); side-by-sides to docs/graphics-proof/overrides/
make regenerate-backgrounds dry=1  # list cameras the Gemini regeneration would process; no API calls
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
and the enhanced graphics scene layer (integer-scaled internal render target,
per-vertex shading, filtered backgrounds, override assets) are done: the game
boots into an asset-faithful character selector and the attic is fully
interactive by mouse or keyboard. Next: M4a2 save/load, M4b audio/sequences,
M4c ending.
See `CONTEXT.md` for the architecture map and `docs/superpowers/` for specs
and plans.
