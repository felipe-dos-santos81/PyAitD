# AGENTS.md

Python engine rewrite of Alone in the Dark 1, test-driven from the FITD C++
decompilation. `CONTEXT.md` is the living architecture map — read it first,
update it when a milestone lands.

## Commands

```bash
make test          # the whole suite, headless — the gate
make test-engine   # simulation, LIFE VM, formats, actors, anim, tracks, collision, navmesh, picking, opcodes
make test-render   # scene, geometry, both backends, asset resolution, texture export/check
make test-shell    # event pump, settings, CLI, UI screens and modals
make test-tools    # the standalone scripts under tools/
make test-meta     # the repo's own rules (package layering, test grouping)
make test-journey  # real run() event pump and long real-data simulations
make proof-mouse   # navmesh for every camera-visible room, every floor (needs game data)
make proof-combat  # venue, real enemy damage, player arms, game over (needs game data)
make proof-graphics # attic + combat fixtures per shading mode x realism preset x smoothing default, plus a flat-mesh pair, a hard-shadow pair, the integration range's two ends -- an un-composited pair and an over-composited one -- a motion-blended tickmotion pair, a painted pair, an SSAO-off nossao pair, a room-shadow roomshadow pair and an un-hazed nohaze pair (needs GL + game data)
make proof-intro   # opening cutscene: headless gate + one GL render per visited camera
make prove-persistence # M4a2 gate: save schema, slots, restoration, menu pages, loop policy, journeys, mouse contract
make run           # title -> menu -> character select -> opening cutscene (skip with any key/click, or --skip-intro); floor=0 debug bypass, textures=DIR defaults to data/aitd1/textures (textures= disables), data="..." trace=/tmp/t.log optional, content=DIR loads a content pack (packs/example is the in-repo reference)
make compare       # live mirror: original AITD1 in DOSBox-X below the port, PLAY keys forwarded (macOS, needs dosbox-x + Accessibility) — not headless, not a pytest gate
make export-textures # originals + 5 KILLED_SORCERER alts + palette + ITD_RESS screens + guides + layout sidecars + per-body UV sidecars/painter guides + manifest schema 4 to data/aitd1/textures (git-ignored) for the external texture tool, then palette ramps + body usage -> <out>/materials-survey + PyAitD/render/materials.json (out=, floors=, scale=, force=1, screens=0 skips screens, uvs=0 skips the actor UV bake, materials=0 skips materials, vision=1 asks Gemini through agy about uncertain ramps)
make check-textures # validate data/aitd1/textures (or textures=DIR) as the game loads it; proof=1 renders side-by-sides (bases, alts -alt.png, screens)
```

Every pytest target runs headless via the Makefile's `HEADLESS` variable, so
`SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy` is set for `make test` and every
`test-*` group. Running pytest directly still needs them on the command line.

Every file under `tests/` declares exactly one subject marker as a module-level
`pytestmark` — `engine`, `render`, `shell`, `tools` or `meta` — plus an optional
`journey` when it drives the real `run()` loop or a long real-data simulation.
Mark by the layer whose behaviour the test asserts, not by what it imports: a
test that drives `run()` and asserts routing is `shell`, one that asserts world
state is `engine`. `tests/test_test_groups.py` enforces this and fails if a new
file carries no marker. The nine legacy `prove-*` names are aliases of the new
targets; five of them (`prove`, `prove-m3b`, `prove-shell`, `prove-mouse-only`,
`prove-mouse-accessibility`) are pinned by that same test to the exact files
they historically ran, so the proof documents under `docs/` keep citing
meaningful gates — the other four (`prove-mouse`, `prove-combat`,
`prove-graphics`, `prove-intro`) are straight renames of the `proof-*`
artifact targets, which need real game data (and GL, for graphics/intro) so
they aren't part of the pytest-file pinning.

After non-trivial changes run `make test`: headless by construction, and a
superset of `make prove` (now `-m engine`, a strict subset of the full
suite), so nothing is gained by running both. No lint, formatter, or
typecheck is configured — LSP/pyright diagnostics are noise, the test suite
is the only gate. Never mass-reformat.

## Game data + FITD reference

- Tests use the user's original game data via the `data_dir` fixture and
  skip when absent. `*.app/` is git-ignored: never commit game data.
- The `GameProfile` comes from the `profile` fixture, never a direct `AITD1`
  import — pinned by `tests/test_test_groups.py`; `tests/test_game_profile.py`
  is the sole exception.
- Behavioral authority is FITD at
  `/Users/felipe.dos.santos/code/theirs/FITD/FitdLib/` (`AITD1.cpp`,
  `life.cpp`, `main.cpp`, `anim.cpp`, `inventory.cpp`, `mainLoop.cpp`).
  When behavior is unclear, trace FITD source, not prose.
- Opcode dispatch indexes `AITD1LifeMacroTable` (AITD1.cpp) by bytecode —
  NOT the `life.h` enum values. Dead slots {27, 57, 61, 69} raise.
- Golden test values are pinned from real data. If one disagrees, trace the
  same path through FITD, fix the expectation, cite FITD file:line in a
  comment. Never re-derive goldens by guessing.

## Do-not-fix quirks (FITD-faithful, all verified)

- Painter's algorithm sorts farthest-first (comparator returns -1 when
  distance1 > distance2) — do not reverse.
- GL FBO rows are bottom-up, backgrounds and CPU-uploaded textures top-down.
  `render_gl.read_rgb()`/`thumbnail()` flip on read (`[::-1]`); `render.py`
  presents the backend's GL texture with `flip_v=False` and CPU-uploaded UI
  or software-backend textures with `flip_v=True`. Swapping those two renders
  every frame upside-down and no unit test outside
  `test_render.py`'s orientation test will notice.
- Actor coords are room-scale; camera translate is `(cam - room.world) * 10`.
- Actor angles always write skeleton group 0 (FITD AnimNuage), regardless
  of body group order.
- GiveDistance2D is Manhattan with s16-cast saturation; LM_READ consumes an
  extra s16; `walkStep` outputs are crossed (xOut→animMoveZ); FITD's
  preserved bugs (e.g. LM_WAIT_GAME_OVER second wait) stay.

## Package layout

`tests/test_layering.py` enforces the import rules below by AST scan (every
file under a package, subpackages included); `tests/purity.py` re-checks the
headless ones at runtime. A rule that is not in one of those two files is not
a rule — add the test with the rule.

| Package | Owns | May import |
|---|---|---|
| `PyAitD/engine/` | The simulation, ported from FITD with `file:line` citations, in five domain subpackages: `data/` (formats, PAK/floor data, masks), `space/` (fixed-point math), `actor/` (actors, animation, tracks, skel), `script/` (`Game` state, LIFE VM, interaction, `playworld` tick, `save.py`), `nav/` (navmesh, picking, pointer steering). Game-neutral: reads per-game facts from `game.profile`. | stdlib, NumPy, `engine` |
| `PyAitD/render/` | `FrameDescription` → pixels: scene description, geometry, both backends, asset resolution, texture export/check. | `engine` |
| `PyAitD/games/<id>/` | Everything FITD branches on `g_gameId`: the `GameProfile` instance, the game's opcode handlers and reduced dispatch, debug venues, the mouse contract. `games/base.py` holds the dataclass. | `engine` |
| `PyAitD/app/` | Window, the single event pump, settings schema/persistence, CLI, UI screens; `app/controls/` is the input package (vocabulary, bindings, gesture state, routing). | everything |
| `tools/` | Standalone scripts: PNG encoding, proofs, the one AI-service caller. | everything |

`__main__.py` owns nothing but the re-export of `app.shell.main`.

**Where new code goes**

- Ports FITD behaviour (cite `file:line`) and does not depend on which game is
  loaded → `engine/`. Pick the domain that owns the knowledge: data parsing →
  `engine/data/`, shared math → `engine/space/`, actor/animation behavior →
  `engine/actor/`, game state/scripting/tick → `engine/script/`, pointer
  navigation → `engine/nav/`. `data` and `space` are pinned leafward in
  `tests/test_layering.py`.
- Depends on the game — a PAK name, CVar name, opcode number, hero archive,
  debug venue, anything FITD guards with `g_gameId` → `games/<id>/`, exposed
  through a `GameProfile` field the engine reads via `game.profile`. Never an
  `engine/` module constant, never `if profile.name == "aitd1"` in `engine/`.
- Touches pygame or moderngl → `render/` (only `GRAPHICS_OWNERS` in
  `tests/test_layering.py` may import them) or `app/`.
- Input → `app/controls/` (actions, bindings, pointer/keyboard state, routing);
  menus and settings → `app/ui.py`/`app/config.py`; CLI flags → `app/shell.py`.
- Writes PNGs, spawns processes, calls an external service → `tools/`.

**Growing the engine**

- A module that outgrows one responsibility becomes a subpackage inside its
  domain: `engine/script/game/{state,zv,objects,boot}.py` is the landed
  example, with the public names re-exported from
  `engine/script/game/__init__.py` so every importer and test keeps
  `from PyAitD.engine.script.game import init_game`. Move with `git mv`; the
  layering scan covers subpackages automatically. Split by responsibility,
  not by size.
- A new engine capability (audio, sequences next) is a new `engine/`
  module that takes its game facts through new `GameProfile` fields, with the
  AITD1 values in `games/aitd1/profile.py` and a pin in
  `tests/test_game_profile.py`; `save.py` is the first example of the
  pattern. Effects the app must react to are `effects.py`
  dataclasses emitted through `game.emit`, never a callback into `app/`.
- A second game is `games/<id>/profile.py` plus a `PROFILES` entry in
  `games/__init__.py`. If the engine needs a branch to support it, the branch
  belongs in a profile field (data or callable), and the seam is documented in
  `games/base.py`'s docstring.
- Seams the engine once hard-coded to AITD1 are now GameProfile fields
  (docs/superpowers/specs/2026-08-31-engine-domain-subpackages-design.md):
  archive naming (`floor_archive_name`/`camera_archive_name`), overlay
  strategy (`mask_factory`), cadre bank, VM-control opcode numbering
  (`core_slots`), player-control indices, record layouts
  (`viewed_room_record_size`, `world_object_has_mark`), and the FITD
  gameTypeEnum ordinal (`generation`).

## Content packs

New enemies, objects or scenarios belong in a content pack under
`packs/<name>/` — TOML in a fixed vocabulary, compiled and run by
`PyAitD/engine/content/` — never as edits to the original game data or new
LIFE bytecode. `engine/content` keeps to the layering rule like every other
engine domain: it may import `data`, `space`, `actor`, and the
`script.game.state`/`objects` leaf modules, never `script.playworld`,
`script.interaction`, `nav`, `games`, or the presentation layer. Tests for
packs split the same way the engine does: `tests/test_content_pack.py`
covers the schema, reader and attach step; `tests/test_content_enemies.py`
covers the behaviour journeys. A pack-free game must stay byte-identical to
before content packs existed — `test_an_empty_pack_ticks_identically_to_no_pack`
is the pin.

## Conventions

- `# SPDX-License-Identifier: GPL-2.0-only` first line of every Python file.
- Inside `render/`: every module is pygame- and moderngl-free except the
  `GRAPHICS_OWNERS` — `asset_resolver` touches pygame in exactly one function
  (`load_png_rgb`); `render_soft` uses `pygame.draw` but never moderngl;
  `render_gl` owns all moderngl; `render` owns the window and both. `scene.build_frame` returns an
  immutable `FrameDescription` whose `palette` and `background.pixels` alias
  shared decode caches — read them, never write. `refine` is pure numpy: the
  tessellation plan, the per-corner normals and the numpy twin of `_TESS_VSH`
  that the transform-feedback test pins the GPU against — change the formula
  in both or neither. `plate` is pure numpy too: `PlateProfile`,
  `estimate_plate`, `softness`, `grain_retention` and
  `dither_arrives_smoothed` — what the room's own
  picture says about its black, its white, its dither and its cell size,
  read off the background image. Not consumed only by the composite:
  `asset_resolver` calls `estimate_plate`, `scene` carries `PlateProfile`
  and `NEUTRAL_PLATE` on the frame, and `render_gl` reads `softness` and
  `dither_arrives_smoothed` to drive the composite. `grain_retention`
  derives the attenuation of a plate *cell mean*, which is the right
  question for a grain laid down one flat value per cell and the wrong one
  for the field the composite now builds: the shader magnifies its own
  dither the way the filter magnified the room's, which attenuates it in
  the same step, so `plate_grain` reaches it uncorrected and scaling by the
  factor as well would attenuate twice. The factor keeps its derivation and
  its tests and answers the predicate instead — a filter attenuates the
  dither exactly when it smooths it, which is `dither_arrives_smoothed`.
  Under
  any `integration` level above 0 (2 is the default) `render_gl` splits the
  frame into a plate layer and an actor layer, resolves each, and composites
  the second back through the first in one full-target pass
  (`COMPOSITE_FSH`); `integration=0` keeps the single-target path. The level
  indexes `render_options.INTEGRATION_STRENGTHS`, and that strength grades
  the range clamp and the grain in the shader and the softness sigma
  in `_composite` before the blur radius is derived from it — three terms,
  one multiplier, and level 2 is 1.0 — the full match, and what every
  golden and identity test is pinned at. (It reproduced the pre-grading
  composite pixel for pixel when the levels landed; the dither rebuild
  since has moved those pixels on purpose.) `pixelate` is deliberately
  outside the multiplier: which plate cell a pixel falls in has no
  half-measure.
  `glsl` is strings only — every GLSL source the backend
  compiles, no imports (`test_layering` pins it). `lighting.soften` is the numpy
  twin of the penumbra blur (`SHADOW_BLUR_FSH`), pinned like
  `refine.evaluate` — change the formula in both or neither. The twin
  takes the radius plain; the coverage texture stores it as `1 - r/R_MAX`
  so that MAX blending keeps the smallest, and the shader alone decodes
  and re-encodes. That encoding is the texture's, not the formula's, so
  the parity test complements its own upload rather than `soften`.
  `lighting.light_view_matrix` is *not* a twin: it is the shadow-map
  projection itself, called straight from `render_gl._render_shadow_map`
  with no GL copy to keep in step, so editing it moves shipped pixels
  rather than a test oracle. `materials` owns the twelve per-index shader
  parameters (`Material`'s ten fields plus two padding floats,
  `PARAMETER_COUNT`, uploaded as a 256x3 RGBA texture) and the two realism
  presets; `preset_c` is the `(bump, sss, emissive)` half of the
  classic/enhanced switch, and `classic` being all zeros is what makes
  every material term collapse to the pre-materials expression byte for
  byte — so a term must be written `1 + strength * ...` or
  `mix(x, y, strength)`, never a form that only *probably* reduces at
  zero. Tuning `CLASS_PRESETS` changes how a class looks; changing which
  palette index *is* that class means `materials.json` and
  `tests/test_bootstrap_materials.py`'s `REVIEWED_RAMPS`, which is a
  reviewed, human decision (`docs/materials-v2-proof.md`). A body's paint
  (`bodies/body<NNN>.png` + its `.uv.json` sidecar, resolved through
  `AssetResolver.body_texture`) changes albedo only: `ACTOR_FSH` substitutes
  the sampled `albedo` for `v_color` at exactly the three sites that read
  it (`base`, the `spec` tint mix, the emissive `mix`), and the material
  table still drives every physical term (roughness, specular, sss,
  emissive...) from the same palette-index lookup either way. Lines, points
  and spheres never sample the atlas — spheres are excluded through the
  same `-1.0` UV sentinel that shares their per-corner attribute slots with
  triangles, not a separate code path. `realism=classic` ignores paints
  outright, through the same `has_body_texture` branch that keeps
  classic's byte-identical golden. The tessellated actor instance layout
  (`INSTANCE_FLOATS`, `_INSTANCE_NAMES`) is now full: 16 of the 16 vertex
  attributes GL 3.3 guarantees (4 pre-existing per-corner attributes —
  position+AO, normal+straight, color+index, rest — plus the new
  per-corner UV, 5 x 3 corners = 15, + the per-vertex barycentric) — the
  next per-corner attribute does not fit on the target GPU and must pack
  into an existing slot instead (`docs/actor-textures-proof.md`).
  `render/ssao.py` is pure numpy — `hemisphere_kernel`, `noise_rotations`,
  `ssao_reference` — and stays that way, unlike `render/occlusion.py`'s
  baked rest-pose vertex AO: the two are additive, not alternatives, one
  seeing pose and neighbours every frame and the other seeing neither, ever.
  The half-resolution G-buffer `_render_gbuffer` writes (`GBUFFER_FSH`)
  carries view normals plus *linear view depth in alpha*, never the depth
  attachment's projective value — a projection inverse is the easiest place
  for `ssao_reference` and the shader to disagree by a hair, so depth is
  written once, straight, as `v_view.z + focal1` (this engine's actual
  perspective divisor, not bare `z`), and the depth attachment itself is
  read by nothing, only used to depth-test the pass against itself. Screen-space
  occlusion attenuates `fill_tint` alone, never `key_tint`, `occl` or `hemi`:
  those three already gate or scale the key share (the shadow map's `vis`,
  the baked AO, the ambient hemisphere term), and folding SSAO into any of
  them would darken the key light a second time — the same "a shadowed limb
  falls to fill, never to black" rule F's shadow map set. Do not "simplify"
  `ACTOR_FSH`'s `fill_tint * ssao` term into `occl` or `hemi`; that reads
  like a cleanup and is a double-darkening regression. `shadows="room"`
  structurally implies everything `shadows="soft"` does (one gathered cast,
  the light-view shadow map, self/inter-actor shadowing) and adds a receiver
  pass that rasterises the room's floor and its `hard_col` tops through that
  same depth map, MAX'd into the same coverage texture the gathered cast
  already softened, *before* the frame's one `_composite_shadow` and before
  any body draws — never a second composite after receivers. A second
  `_composite_shadow` there double-darkens every floor pixel under an
  actor's ground cast that a room receiver also covers (measured
  54/46/43/40/45 versus the correct 74, the coverage texture's own MAX
  rule); `hard_cols` are collision proxies, not painted furniture, so `room`
  stays a menu choice behind `RenderOptions.shadows`, which still defaults
  to `"soft"` pending a human's eye on real fixtures.
- **Depth travels the way colour does: premultiplied by coverage.**
  `atmosphere`'s linear eye depth is a second colour attachment on the same
  FBO as the actor layer (`_actor_depth_tex`, R16F, and `_ms_depth_color`
  on the multisample path), written as `v_view.z + focal1` — eye distance
  from the pinhole, the same quantity `GBUFFER_FSH` writes, never the depth
  attachment's projective value. It is a *colour* attachment on purpose: an
  MSAA resolve averages it, and a partially-covered silhouette pixel must
  end up with the coverage-weighted average of the depths that actually
  covered it. So every read unpremultiplies — `depth = d / a.a`, using the
  same `a.a` that premultiplied it, exactly as the colour term does. At
  `msaa=0` coverage is 0 or 1 and `d / a.a == d` identically, which makes a
  dropped unpremultiply invisible to almost the whole suite; one test
  (`test_haze_unpremultiplies_depth_at_partially_covered_edges`, at msaa 4)
  is the only thing standing between that bug and green. The blur in
  `sample_layers` gathers colour and depth in one loop with identical
  weights for the same reason — two loops drift, and a soft edge whose
  depth came from different taps than its colour hazes by the wrong amount
  along exactly the pixels the eye checks first.
- **The depth grade reads the centre pixel's own unblurred depth**, never
  the blurred one: the blur's weights are what the grade sets, so grading
  from the blurred value is circular. And the grade scales `inv_sigma2`,
  never `radius` — the composite's blur loop depends on `radius` being a
  uniform for uniform control flow, so a per-pixel tap count is not
  available. The consequence is a real, documented bound: the depth grade
  can only soften within the existing radius and can never sharpen past
  it. **Stronger than a bound: whenever `radius <= 0` or `pixelate` is
  set, `sample_layers` takes an early return that never reads `grade` at
  all, so `SIGMA_DEPTH_SLOPE` is not merely limited, it is completely
  inert.** That covers `--render-scale 1` (where `plate.softness` yields
  cell <= 1 and `radius` is 0) and `--background-filter nearest` at any
  scale. Measured on both proof fixtures: sigma-graded-only against
  atmosphere-off moves 0 pixels at scale 1, 0 pixels under `nearest` at
  scale 4, and 6930 (attic) / 2048 (combat) pixels at scale 4 bilinear,
  by at most 2-4 counts even there. Do not reach for `SIGMA_DEPTH_SLOPE`
  to make a depth cue stronger; it does nothing on a large share of the
  supported settings, and `GRAIN_DEPTH_SLOPE` and `HAZE_DENSITY` are the
  two that always act.
- **Atmosphere's four tunables live in `render/plate.py`**, beside the
  composite's own toe/shoulder/grain constants, and reach the shader as
  lowercase uniforms (`haze_density`, `haze_start`, `sigma_depth_slope`,
  `grain_depth_slope`) — the same CPU/GLSL casing split every other
  constant in that file follows. All four are zero-collapsible, and the
  `atmosphere="off"` branch works by setting three of them to 0.0 rather
  than by taking a different code path, which is what makes "off" and "on
  with neutral tunables" byte-identical
  (`test_neutral_tunables_are_an_exact_identity`). Two of them —
  `SIGMA_DEPTH_SLOPE` and `GRAIN_DEPTH_SLOPE` — multiply
  `beyond = max(0, depth - HAZE_START) / HAZE_START`, so they are
  denominated in `HAZE_START` and must be rescaled whenever it moves.
  **Tune these against the real fixtures, never against this suite's
  synthetic camera**: the test camera's focal1 is 1000 and its actors sit
  at eye depth 1500-2400, while the game's own rooms measure 1400-30000
  (`docs/atmosphere-proof.md` has the survey). Task 3 settled the constants
  on the synthetic scale and Task 4 found they drove every actor in both
  fixtures to flat ambient tone.
- **To find every test a rendering constant silently holds up, perturb the
  constant and run the whole gate — never grep for an assertion idiom.**
  Sub-project L swept the same net three times by grepping (`array_equal`
  against a golden, `tuple(rgb[y, x]) ==`, ...) and was wrong all three
  times, because each sweep saw only the idiom it searched for. Setting
  `HAZE_START = 1.0` and running `pytest -q` once found all 16 in a minute.
  The same one-line move works for any constant with an off value: set it
  where it cannot possibly be neutral, and every test that depended on it
  without naming it fails. A test that asserts an exact pixel and does not
  name the option that moved it is this project's dominant defect, and
  this is the only sweep that reliably finds one.
- **A new proof twin is one row of `tools/prove_graphics.py`'s `VARIANTS`
  table**, plus one entry in the `base` dict beside it if the option is new.
  Rows are `ProofRow`s carrying the dict of RenderOptions fields they force,
  so nothing downstream unpacks a positional tuple: J, K and L each widened
  one before it was a table, and each paid for it in three consumers and
  nine mirrored blocks in `tests/test_prove_graphics.py`. Every twin must
  force the *non-default* value of the field it is named for, or it renders
  the same image twice and proves nothing — `-roomshadow`'s first draft
  forced `"soft"` against a default that has never moved off `"soft"`.
  `-nocomposite` and `-strong` are the deliberate exception: they bracket
  the default integration level from both ends.
- `scene.box_top_corners` is the single source for a `hard_col`'s top face —
  its corner order and the "world y grows downward, so the top is y1" rule.
  `room_receivers` rasterises it as a shadow receiver and
  `texture_export._box_corners` draws it as the top half of the box
  wireframe; the two held separate copies until it was pulled out.
  `room_receivers` takes only the room: the floor level is a pure function
  of the same `hard_cols` it reads, so a second argument could only ever
  disagree with them.
- The UI layer is painted through `app.ui.UIPainter`, which owns a surface at
  `(320*s, 200*s)` and scales logical coordinates on every call. Presenters
  author in logical 320x200 and never build their own surface; `s` comes from
  `Renderer.ui_scale()`, the same expression `window_to_logical` inverts.
  Pixel art (cadre tiles, sprites, scene thumbnails) goes through
  `painter.sprite`, which nearest-scales the art to its exact scaled
  destination; text and shapes are drawn at scale. Never measure with
  `painter.text_size` (a deliberately scale-1 measurement, for line
  breaking) and then place by `topleft`: anchor the scaled glyph with
  `center`/`midtop`/`centered_in`. Hit-testing stays logical — never scale a
  `hit_test_*` input.
- `app/ui.py` never mutates world/actor/inventory/LIFE state; `app/config.py`
  is pygame-free settings schema/persistence; `app/shell.py` owns the single
  event pump, the settings lifecycle, game/floor replacement, and one present
  per frame. Settings live on `ModalSession`, never `Game`.
- `render/texture_export.py` and `render/texture_check.py` are pure like
  `render/scene.py`; PNG encoding lives only in `tools/`. The export
  directory layout is `render/asset_resolver.texture_background_path`'s and
  `texture_screen_path`'s — change both or neither. `texture_export`
  additionally owns the guide and layout-sidecar paths (`layout_rel_path`,
  `screen_layout_rel_path`); a sidecar holds the guide's own geometry, so
  `layout_segments` is the single source the guide pixels draw from — never
  re-derive it.
- `tools/bootstrap_materials.py` owns the AI-service boundary: it is the
  only module that shells out to the `agy` CLI (its label stage reaches
  Gemini through `agy_structured`). It imports no AI SDK directly — and its
  unit tests monkeypatch `subprocess.run`, so they never touch the network.
  `tests/test_layering.py` pins that boundary. Credentials belong to that
  CLI, not to this repo (a `.env` is git-ignored); never commit keys or
  generated `textures*/` output. Texture regeneration itself lives outside
  this repo: `make export-textures` writes the contract (originals, guides,
  layout sidecars, manifest) and `make check-textures` validates the result.
- `skel.skin`'s integer projection stays authoritative for picking, masks and
  the mouse contract; `draw_list` entries must stay byte-identical. There are
  now two parallel float paths, both for rendering only, both deliberately not
  bit-identical, and neither may ever feed picking:
  `scene.CameraView` (projection) diverges by ~9.6px near the camera and
  ~0.13px far away, and `motion.pose_vertices_float` (posing) diverges by up
  to ~50 world units on a real animated body, because the integer paths
  truncate — `pose_vertices_float`'s error compounds once per ancestor group,
  so it is far larger than the ~7 units a single rotation shows, and
  `tests/test_motion.py`'s `_HIERARCHICAL_PARITY_BOUND` is the guard that
  must keep exercising a hierarchical pose, never an all-zero-states one.
  Never "fix" either divergence by routing `draw_list` or `skin()` through a
  float path.
- Motion interpolation is presentation-only. `scene.build_frame(blend=None)`
  is the identity path and must stay byte-identical to the pre-blend engine;
  only `ActorDraw.geometry` and `ActorDraw.position` ever see blended values,
  while `logical`/`draw_list` are computed from the unblended tick state
  *before* `blend_actor` runs — keep that ordering. Blending interpolates and
  never extrapolates (`alpha = min(accumulator / TICK_MS, 1.0)`), and the
  snapshot is taken before `play_tick`, unconditionally, so it can never go
  stale across a mid-session knob flip. An actor renders unblended rather than
  smearing whenever `motion.blend_actor`'s snap rules fire (no snapshot entry,
  body/room/anim change, or movement past `TELEPORT_LIMIT`) or the whole frame
  snaps on a floor, room or camera change — `MotionSnapshot.camera` is only a
  slot index into `room.camera_indices`, so `room` is what actually catches a
  same-slot cut. Because picking reads the tick pose while the screen shows
  the blended one, a moving actor is drawn up to one tick behind its hitbox;
  that is the accepted trade, not a bug to "fix" by blending `draw_list`.
- Mouse movement is a held pointer follow: every navigation intent is
  hold-bound (`playworld._apply_mouse_input` cancels an intent whose buffer is
  not held and focused), `app.shell.follow_pointer` re-resolves the held
  pointer on the frames it moved off `InputBuffer.follow_pos` and re-issues an
  intent only when the resolution differs from `InputBuffer.follow_last`, and
  hold-push keeps its latched target. Only pointer motion retargets: the same
  pixel names a different world point under every camera, so re-resolving a
  still pointer at a camera cut would steer or stop the hero on its own. A
  press within `ui.DOUBLE_PRESS_TICKS` of the previous one runs
  (`NavIntent.run` -> `NavDecision.run` -> speed 5), timed on `game.timer` so
  a paused modal does not count; the engine never learns which device asked.
  That window is the mouse's own and is deliberately far longer than the
  keyboard's `tracks.DOUBLE_TAP_TICKS` -- see the constant. Held actions never publish global Action; existing LIFE and
  collision code alone move pushable scenery. Never lock, grab or warp the OS
  cursor (`tests/test_layering.py` gates it, `meta`-marked so `make test` runs
  it, not `make prove-mouse-only`). Keep the both-protagonist journeys in
  `tests/test_mouse_only.py` and run `make prove-mouse-only` after changing
  pointer, navigation, animation, modal, or collision behavior.
- Mouse accessibility hardening closed the held-push inventory takeover
  regression and has user-attested Emily/Carnby window passes. The current
  [hardening proof](docs/mouse-accessibility-hardening-proof.md) supersedes the
  older pending status in the [M4a1 shell](docs/m4a1-shell-proof.md) and
  [mouse hold-to-push](docs/mouse-hold-push-proof.md) proofs.
- M4a2 persistence: `engine/script/save.py` validates the complete payload before
  anything live is touched, and the settings block rides through as an
  opaque dict — `app/config.validate_settings` alone owns it, so `engine/`
  never imports `app/` (the addendum in the M4a2 plan records the
  translation). Slots are `save-manual.json` / `save-quick.json` beside the
  settings file, written with `write_slot`'s settings atomic idiom. Manual
  save refuses while a LIFE continuation or platform effect is queued;
  Quick Save commits at the first stable end-of-PLAY-tick boundary, never
  mid-tick; a load stages `session.pending_load` and `_load_branch`
  replaces game/floor/session/input as one tuple (the `_hero_branch`
  shape), forcing fresh-boot flags and clean transient input. Every failure
  path leaves the live game untouched. Schema changes bump `SCHEMA`; never
  migrate in place.
- The compare-with-original live mirror is macOS-only and never a gate:
  `tools/compare_original.py` owns the DOSBox-X child, the resident Swift
  CGEvent helper (`tools/mirror_helper.swift`, compiled once into the
  git-ignored `tools/.cache/`) and window placement; the pump tap in
  `app/shell.py` is observation-only and forwards only keyboard-mode PLAY
  events that mapped to a control in `games/aitd1/mirror.py` (pinned from
  FITD `input.cpp`). The helper's stdout carries async `DEAD <pid>` lines;
  any reader of it must skip non-protocol lines. Never pipe dosbox-x output
  through `head` — SIGPIPE kills the emulator; redirect to a file.
- `ponytail:` comments mark deliberate simplifications with upgrade path —
  respect them, don't silently remove.
- Workflow is brainstorm → spec → plan → TDD under `docs/superpowers/`
  (one spec + one task-level plan per milestone); `docs/life-vm-opcodes.md`
  is research only — plan + code are the source of truth.
- Dependencies: the runtime (`PyAitD/`) is fixed at pygame-ce, ModernGL, NumPy
  (plus pytest for the suite) — add nothing. `tools/` may take PyPI
  dependencies vetted case-by-case (GPL-2.0-compatible, maintained, macOS
  arm64 / CPython 3.12 wheels) in the `tools` extra; today that is `xatlas`
  and `libigl`, and `tests/test_layering.py` fails if `PyAitD/` imports
  either. `igl.copyleft.cgal` (GPL-3) and `igl.copyleft.tetgen` (AGPL-3) are
  banned outright and pinned by the same file. The one external service,
  Gemini, is reached through the `agy` CLI, not a Python SDK, so it costs
  this project no dependency at all.
- A mouse or keyboard behaviour change gets a unit test in
  `tests/test_controls_pointer.py` or `tests/test_controls_keyboard.py` first,
  and must keep `tests/test_controls_golden.py` byte-identical unless the
  change is the point, in which case re-record with
  `PYAITD_RECORD_GOLDEN=1` and say why in the commit.
