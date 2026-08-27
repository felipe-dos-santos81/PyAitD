# Background layout fidelity: constrain, gate, judge, retry

Date: 2026-08-27. Status: approved design, awaiting implementation plan.
Amends `docs/superpowers/specs/2026-08-25-gemini-background-regeneration-design.md`
(the tool it extends; that spec's SDK wording is already superseded by the
`agy` CLI, see AGENTS.md).

## Goal

`make regenerate-backgrounds` must produce plates that keep the original
scene: same camera framing; every wall, door, window, stair and piece of
furniture at the same screen position, of the same kind and the same
count — nothing added, nothing removed. Materials, lighting and style may
change. A plate that does not meet this is not written.

## Why (what the last run showed)

`data/aitd1/overrides-b` (144 plates from the current tool) drifts in three
ways: objects moved or re-counted (floor00/camera000: window shifted, extra
pillars, ceiling beam gone); furniture rearranged and invented
(floor00/camera003: cabinet, bookshelf, crate and chest reshuffled, a table
and chair added); guide lines painted into the output (camera003 carries the
red pillar outlines and the blue top edge). Causes:

- `generate()` asks the `agy` agent to "look at" the images and then call
  `generate_image`; whether the original or the guide is actually attached
  is left to the agent. The tool accepts `ImagePaths` (up to 3 references)
  and `AspectRatio` (`3:2` exists; no 16:10) — the instructions never say to
  use them. When the guide is attached the model copies its lines.
- Nothing verifies a result; `check-overrides` checks aspect, size and
  decodability only.
- `--image-model` is dead: `generate_image` has no model parameter and
  `regenerate()` passes `text_model` to `generate()` anyway.

## Decisions (from brainstorming)

- Acceptance = structure **and** identity (position, kind, count, framing);
  style free.
- A camera that fails after the attempt budget is **rejected**: no file, a
  `failed:` log line, exit 1. The game falls back to the original; a rerun
  retries only cameras without an output PNG.
- Verification = a deterministic local gate first, then one vision-model
  judge call, only when the gate passes.
- Generation is constrained (structured inventory, layout sidecar, explicit
  tool-call contract, edit-style instruction) so retries converge.
- Every prompt opens with a fixed game/atmosphere block (`GAME_CONTEXT`).

## Global constraints

- `# SPDX-License-Identifier: GPL-2.0-only` first line of every Python file.
- Dependencies fixed: pygame-ce, ModernGL, NumPy, pytest. No scipy, no
  Pillow, no SDK. `tools/plate_check.py` is numpy only.
- `tools/regenerate_backgrounds.py` stays the only module that talks to an
  AI service, only via `subprocess.run` on the `agy` CLI. Its tests
  monkeypatch `subprocess.run`; no test touches the network except the live
  test gated on `PYAITD_LIVE_AI=1`.
- Engine untouched: `asset_resolver.py`, `render_*.py`, `scene.py`,
  `floor.py`, `__main__.py`, `override_check.py`, `mask_geometry.py` do not
  change. `PyAitD/render/background_export.py` changes only as described
  below and its guide pixels stay byte-identical.
- Manifest schema stays 2; new keys are additive.
- Output directories are git-ignored; nothing under `data/` is committed.
- Nothing in `IN` is ever written. `prompts.json`, `report.json` and every
  PNG are written via `.tmp` + `os.replace`.

## Architecture

| Unit | Role | Deps |
|---|---|---|
| `PyAitD/render/background_export.py` | `layout_geometry(floor, cam_idx)` and `screen_layout(entry)`: the primitives the guides draw, as JSON-able dicts in 320×200 pixel space. `guide_overlay` / `screen_guide` draw from them. `manifest_record` / `screen_record` gain `"layout"`. | numpy |
| `tools/export_backgrounds.py` | Writes `guides/floorNN/cameraNNN.json` and `guides/screens/ressNN.json` beside each guide PNG. | — |
| `tools/plate_check.py` (new) | `layout_regions(layout)` and the local gate `gate(candidate, original, layout, scale=1.0) -> GateResult`. Pure, offline, unit-testable. | numpy |
| `tools/regenerate_backgrounds.py` | Structured describe, generation contract, judge, attempt loop, `report.json`, CLI. | pygame (decode/scale), `plate_check` |
| `Makefile` | `attempts=`, `gate_scale=`; `image_model=` removed. | — |
| Docs | `docs/ai-background-regeneration.md` §2b rewritten; one-liners in `README.md`, `AGENTS.md`, `CONTEXT.md`. | — |

### Per-camera data flow

1. Load the original (320×200), the guide PNG and the layout JSON. Missing
   sidecar: log `floorNN/cameraNNN: no layout: framing gate only` once and
   continue (same pattern as a missing guide).
2. **Describe** (cached by source sha256 in `prompts.json`, schema 2): one
   text-model call returns the inventory. A cached entry that has only
   `"prompt"` (schema 1) is re-described.
3. **Attempt loop**, `attempts` times (default 3):
   `generate` → `fit_to_target` → `gate` → (gate passed) `judge` → accept
   (`save_png`) or collect corrections and go again.
4. Out of attempts → `failed: layout mismatch after N attempts (last: …)`,
   nothing written.
5. `report.json` updated after every camera; `manifest.json` copied as
   today.

## Layout sidecar

`layout_geometry(floor, cam_idx)` returns (floats, one decimal, may fall
outside the frame — consumers clip):

```json
{"schema": 1, "size": [320, 200],
 "masks":     [[[x, y], "..."], "..."],
 "collision": [[[x, y], null, "... 8 slots"], "..."],
 "walkable":  [[[x, y], "..."], "..."]}
```

- `masks`: one closed polygon per `floor.mask_draws(cam_idx)` polygon.
- `collision`: one entry per hard-collision box of every viewed room, its 8
  projected corners in `_box_corners` order, `null` where `view.project`
  culled the corner (`z <= _CULLED`).
- `walkable`: one closed polygon per cover polygon, projected.

`screen_layout(entry)` returns
`{"schema": 1, "size": [320, 200], "blit": [[x, y, w, h], "..."]}` from
`SCREEN_GUIDES[entry]`.

`guide_overlay` draws masks as closed red polylines, collision via
`_BOX_EDGES` over the 8 slots skipping any edge with a `null` end, walkable
as closed green polylines, all scaled by `scale`; `screen_guide` draws the
blit rects. Pixels are unchanged; the existing guide tests pin that.

`export_floor` / `export_screens` write the sidecars via `.tmp` +
`os.replace`. `manifest_record` gains
`"layout": "guides/floorNN/cameraNNN.json"`, `screen_record` gains
`"layout": "guides/screens/ressNN.json"`; `None` when the image was missing.

On the regenerate side `Camera` gains `layout: pathlib.Path | None` (set
only when the file exists). `plate_check.layout_regions(layout) -> list[Region]`
— one helper, used by both the prompt builder and the gate — turns a
layout into regions: `Region(kind, polygon, bbox_pct)` where
`kind ∈ {"mask", "collision", "walkable", "blit"}`, `polygon` is the mask
polygon, the convex hull of the non-null collision corners, the walkable
polygon, or the rect; `bbox_pct` is the polygon's bbox clipped to the frame
in whole percent `(x0, y0, x1, y1)`. Regions whose clipped area is under
0.5 % of the frame are dropped.

## Prompts and the `agy` contract

`GAME_CONTEXT` (verbatim; first sentence of every describe, generate and
judge prompt):

> This image depicts a scene from the Alone in the Dark 1 game. Atmosphere
> notes: The entire Alone in the Dark 1 game evokes a gothic
> horror/Lovecraftian mood. The darkness, somber portraits, and
> period-appropriate text work together to set the tone before the player
> even enters the mansion. The design is effective at establishing dread
> and mystery.

Every structured call runs
`agy -p <instructions> --dangerously-skip-permissions --effort low --model <text_model> --output-format json --json-schema <schema>`
and reads `json.loads(stdout)["structured_output"]`; a missing or
non-object `structured_output` is an error for that camera.

### Describe → inventory

Instructions: `GAME_CONTEXT`; view the original (and the guide when
present, with today's `_GUIDE_DESCRIBE` / `_SCREEN_DESCRIBE` sentence);
"Describe this 320x200 background as a single-paragraph prompt for a
photorealistic image generator. Name the room type, the camera angle and
height, every piece of furniture and architecture with its position in
frame, the light sources and their direction, materials and colours, and
the mood. Do not mention pixel art or resolution." Then list every distinct
object. `INVENTORY_SCHEMA`:

```json
{"type": "object", "required": ["prompt", "camera", "objects"],
 "properties": {
   "prompt": {"type": "string"},
   "camera": {"type": "string"},
   "objects": {"type": "array", "items": {"type": "object",
     "required": ["name", "kind", "count", "bbox"],
     "properties": {"name": {"type": "string"}, "kind": {"type": "string"},
                    "count": {"type": "integer", "minimum": 1},
                    "bbox": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 100},
                             "minItems": 4, "maxItems": 4}}}}}}
```

`bbox` is `[x0, y0, x1, y1]` in percent of frame, x left→right, y
top→bottom. Cached as
`prompts[key] = {"inventory": <object>, "model": text_model, "sha256": <source sha>}`.
`describe()` raises on an empty `prompt` or an empty `objects` list.

### Generate — the tool-call contract

`generate(model, cam, prompt, attached, out_path)` where `attached` is the
list of reference PNG paths. Instructions:

> Call the generate_image tool exactly once with these arguments:
> ImagePaths = [<attached, in order>]; AspectRatio = "3:2";
> ImageName = "plate_fNN_cNNN" (screens: "screen_ressNN"); Prompt = the text
> between the markers below. Then copy the generated image file to exactly
> this path: <out_path>. Output ONLY the word SUCCESS.
> ---PROMPT---
> <prompt>
> ---END---

The first attached reference is `ref.png`: the original nearest-upscaled 4×
(`nearest_upscale`) to 1280×800, written to a temp file per camera and
removed afterwards; the second, when present, is the guide PNG (already
4×). Attachment rule: attempts attach `[ref, guide]`; from the first attempt
that fails the gate's `leak` check onward, attempts attach `[ref]` only.
Missing guide → `[ref]` always.

`generation_prompt(inventory, style, regions, corrections, guide_attached, screen)`
builds `Prompt`, in this order:

1. `GAME_CONTEXT`.
2. Cameras: "Re-render the first image as a photorealistic photograph of
   exactly this scene: same camera position, framing and perspective; every
   wall, door, window, stair and piece of furniture stays where it is, same
   kind and same count — add nothing, remove nothing. Change only
   materials, lighting detail and realism." Screens: "Re-render the first
   image as a painted illustration of exactly this composition, keeping the
   framing and every element's placement; change only the medium and
   finish."
3. When the guide is attached: `_GUIDE_GENERATE` / `_SCREEN_GENERATE` as
   today.
4. "Layout (percent of frame, x left→right, y top→bottom): <count> <kind>
   x X0–X1 y Y0–Y1; …" from the inventory objects, then "Foreground
   occluders at …; solid walls and furniture at …; walkable floor at …"
   (screens: "Regions that must stay plain: …") from `regions`, each as
   `x X0–X1 y Y0–Y1` lists.
5. When `corrections` is non-empty: "Attempt <n> was rejected: " + the
   corrections joined by "; ".
6. `inventory["camera"]`, `inventory["prompt"]`, then `style` verbatim.

### Judge

`judge(model, cam, inventory, ref_path, candidate_path) -> dict`.
Instructions: `GAME_CONTEXT`; view `ref.png` (the original) and the
candidate; the inventory as JSON; "For every inventory object report
whether it is present in the candidate, of the same kind, the same count,
and at the same position (within about 5 % of the frame). List objects in
the candidate that are not in the inventory. Say whether the camera
position, framing and perspective are the same, and whether any red, blue
or green outline lines are visible. Give one short correction sentence per
problem." `JUDGE_SCHEMA`:

```json
{"type": "object",
 "required": ["camera_same", "guide_lines_visible", "objects", "extra_objects", "corrections"],
 "properties": {
   "camera_same": {"type": "boolean"},
   "guide_lines_visible": {"type": "boolean"},
   "objects": {"type": "array", "items": {"type": "object",
     "required": ["name", "present", "same_kind", "same_count", "same_position", "note"],
     "properties": {"name": {"type": "string"}, "present": {"type": "boolean"},
                    "same_kind": {"type": "boolean"}, "same_count": {"type": "boolean"},
                    "same_position": {"type": "boolean"}, "note": {"type": "string"}}}},
   "extra_objects": {"type": "array", "items": {"type": "string"}},
   "corrections": {"type": "array", "items": {"type": "string"}}}}
```

`judge_accepts(verdict) -> bool`: `camera_same`, not
`guide_lines_visible`, every inventory object reported with all four flags
true, `extra_objects` empty. When rejected, corrections for the next
attempt = `verdict["corrections"]` plus, for each failing object, `"<name>:
<note>"`, plus `"extra object: <x>"` per extra, plus `"red, blue or green
guide lines are visible: do not draw them"` when flagged.

## Local gate (`tools/plate_check.py`)

`gate(candidate, original, layout, scale=1.0) -> GateResult` with
`candidate` `(800, 1280, 3)` uint8, `original` `(200, 320, 3)` uint8,
`layout` the sidecar dict or `None`. `GateResult(passed: bool, scores: dict,
failures: list[str])`. Steps:

1. Box-downsample the candidate 4× (exact) to 320×200; convert both to
   luminance `0.299 R + 0.587 G + 0.114 B` as float32.
2. Edges: Sobel magnitude on each; each thresholded at 0.25 × its own 95th
   percentile → binary edge maps. The original's map is dilated by 2 px
   (max over shifts).

| Score | Definition | Default threshold |
|---|---|---|
| `ncc` | normalised cross-correlation of the two luminance images after a separable Gaussian blur, σ = 3 px (kernel radius 9) | ≥ 0.50 |
| `edge_recall` | fraction of the original's edge pixels that lie on a candidate edge dilated by 2 px | ≥ 0.60 |
| `regions[i].recall` | `edge_recall` restricted to the pixels of each `mask` and `collision` region (even-odd scanline polygon fill); regions with fewer than 20 original edge pixels are skipped and reported with `recall: null` | each ≥ 0.50 |
| `leak` | the layout's lines (masks, collision edges, walkable edges, blit rects) rasterised 1 px wide at 320×200 with `draw_polyline`, dilated 1 px; fraction of those pixels whose candidate RGB is in a guide band: red `R>180, G<80, B<80`; blue `B>200, 80≤G≤180, R<80`; green `G>150, R<80, B<80` | ≤ 0.02 |
| `leak_frame` | the same band test over every pixel of the frame | ≤ 0.005 |
| `plain[i]` (screens) | edge density (candidate edge pixels / rect pixels) inside each blit rect | each ≤ 0.02 |

`walkable` regions are prompt-only (floor texture makes their recall
noise). Without a layout only `ncc` and `edge_recall` are computed.
`THRESHOLDS` is a module-level dict; `scale` multiplies every threshold
(`scale == 0` passes everything and still reports scores). Failures are
worded as corrections: `"structure missing inside x 45–52 y 12–25 (edge
recall 0.21)"`, `"framing differs (ncc 0.31)"`, `"guide colour on 9 % of
guide-line pixels: do not draw the red, blue or green lines"`, `"text or
clutter inside plain region x 3–47 y 5–95"`.

Calibration is a plan task, not runtime code: run the gate over the 144
originals against themselves (must pass; `leak_frame` < 0.005 despite green
cloths and blue windows), against the 144 `overrides-b` plates (the known
drifts should mostly fail), and against 8 px-shifted copies of the
originals (must fail `regions`), and fix the defaults from that table
before the loop is wired.

## Attempt loop, report, CLI

```python
def regenerate(cams, out_dir, *, text_model, style, attempts, gate_scale, force, dry_run, log=print)
```

Per camera:

1. Skip when the output PNG exists and not `force`.
2. Describe (cache rules above).
3. For `n in 1..attempts`: generate → `fit_to_target` → `gate` → if
   passed, `judge`. Accept → `save_png`, log
   `floorNN/cameraNNN: ok (attempt n/attempts, ncc 0.71, recall 0.83)`.
   Gate failure skips the judge; its `failures` are the corrections.
4. After `attempts` rejections: log
   `floorNN/cameraNNN: failed: layout mismatch after N attempts (last: <corrections joined by "; ">)`;
   nothing written.

Failure classes:

- **Error** — `agy` exit ≠ 0, missing/invalid `structured_output`, no image
  copied, undecodable image, judge call error: the camera fails at once (no
  retry), counted in `MAX_CONSECUTIVE_FAILURES = 3` as today.
- **Rejection** — gate or judge rejection on every attempt: counted in
  `MAX_CONSECUTIVE_REJECTS = 5`; on the fifth consecutive rejected camera the
  run aborts with
  `aborting after 5 consecutive layout mismatches: edit the inventory in prompts.json, lower --gate-scale, or raise --attempts`.
  A rejection resets the error streak and vice versa.

Return `(done, failed)`; `failed` counts both classes; exit 1 when any.

`report.json` in `out_dir`, atomic after every camera, keyed by camera key,
the entry replaced when the camera is reprocessed:

```json
{"floor00/camera000": {"accepted": true, "attempts": [
  {"attached": ["ref", "guide"],
   "gate":  {"passed": true, "scores": {"ncc": 0.71, "edge_recall": 0.83, "leak": 0.0, "leak_frame": 0.0,
                                        "regions": [{"kind": "mask", "bbox_pct": [45, 12, 52, 25], "recall": 0.9}]},
             "failures": []},
   "judge": {"camera_same": true, "guide_lines_visible": false, "objects": [], "extra_objects": [], "corrections": []}}]}}
```

`"judge"` is `null` when the gate failed; an error mid-attempt records
`{"error": "<message>"}` as that attempt.

Dry run lists `floorNN/cameraNNN: would regenerate (guide yes, layout yes, prompt cached no)`
and makes no calls and no files.

CLI: `--attempts N` (3), `--gate-scale F` (1.0); `--image-model` removed
(the parser rejects it). `--text-model` serves describe and judge. Makefile:

```make
regenerate-backgrounds: install ## Regenerate data/aitd1/overrides backgrounds with Gemini into data/aitd1/overrides-ai (in=, out_ai=, floors=0-7, style=, force=1, dry=1, text_model=, attempts=3, gate_scale=1.0, screens=0 to skip screens); rejects plates whose layout drifts; needs the `agy` CLI on PATH
	$(PYTHON) tools/regenerate_backgrounds.py "$(or $(in),data/aitd1/overrides)" --out "$(or $(out_ai),data/aitd1/overrides-ai)" --floors "$(or $(floors),0-7)" $(if $(style),--style "$(style)") $(if $(force),--force) $(if $(dry),--dry-run) $(if $(text_model),--text-model "$(text_model)") $(if $(attempts),--attempts "$(attempts)") $(if $(gate_scale),--gate-scale "$(gate_scale)") $(if $(filter 0,$(screens)),--no-screens)
```

`KeyboardInterrupt` propagates after the current atomic write; a rerun
resumes.

## Error handling

| Condition | Behaviour | Exit |
|---|---|---|
| no cameras/screens under `IN` | message, as today | 2 |
| sidecar missing | `no layout: framing gate only`, judge still runs | — |
| guide missing | `[ref]` only, logged as today | — |
| schema-1 `prompts.json` entry | re-described | — |
| `agy` error, bad structured output, no/undecodable image | camera failed (error class) | 1 |
| every attempt rejected | camera failed (rejection class), nothing written | 1 |
| 3 consecutive error failures | abort | 1 |
| 5 consecutive rejected cameras | abort with hint | 1 |
| interrupted run | atomic files; rerun resumes | — |

## Docs

- `docs/ai-background-regeneration.md` §1 lists the sidecars; §2b is
  rewritten: inventory in `prompts.json` (edit `objects` to steer a
  camera), the generation contract, the gate scores and thresholds, the
  judge, `report.json`, `attempts=` / `gate_scale=`, the two abort limits,
  and that a rejected camera falls back to the original.
- `README.md` target line; `AGENTS.md` (`plate_check.py` is pure and
  offline; `regenerate_backgrounds.py` remains the only AI caller;
  `--image-model` gone); `CONTEXT.md` tool summary; Makefile help text.

## Testing

- `tests/test_background_export.py`: `layout_geometry` on the stub floor
  (mask/collision/walkable counts, `null` for culled corners, one-decimal
  floats); `screen_layout`; guide pixels unchanged (existing golden tests);
  `export_floor` / `export_screens` write sidecars atomically; records carry
  `"layout"` (`None` for a missing image).
- `tests/test_plate_check.py` (new, numpy only, synthetic 320×200 scenes of
  rectangles on a gradient): identical → every score passes; 8 px shift →
  `edge_recall` and `regions` fail with bbox-% wording; guide-coloured lines
  along the layout → `leak` fails; noise in a blit rect → `plain` fails; no
  layout → only `ncc` and `edge_recall`; concave polygon fill; regions with
  < 20 edge pixels reported `null`; `scale=0` passes anything.
- `tests/test_regenerate_backgrounds.py`: `FakeSubprocess` parses the
  contract (`ImagePaths`, `AspectRatio`, the `---PROMPT---` block, the copy
  path) and answers describe/judge with `{"structured_output": …}` envelopes
  scripted per call; `plate_check.gate` monkeypatched where a test needs an
  outcome. Cases: inventory cached as schema 2, schema-1 entry re-described,
  hand-edited inventory survives without `--force`; prompt order
  (`GAME_CONTEXT` first, layout lines, corrections on attempt 2, style
  last); `[ref, guide]` then `[ref]` after a leak failure; gate failure
  skips the judge; accept on attempt 2 writes PNG + report; reject after N
  writes nothing, counts failed, exit 1; error mid-attempt ends the camera
  without retry and feeds the 3-streak; 5 consecutive rejections abort with
  the hint and rejections reset the error streak; report replaced on rerun;
  dry run makes no calls; missing sidecar logs `framing gate only`; screens
  use the illustration wording and `screen_ressNN`; round trip through
  `override_check` still clean; `--image-model` rejected; temp `ref.png`
  removed after each camera.
- Calibration (skipped without `data/aitd1/overrides`, like the other
  game-data tests): every original passes the gate against itself with
  `leak_frame` < 0.005.
- Live (skipped unless `PYAITD_LIVE_AI=1` and `agy` on PATH): one real
  camera through the whole loop, output 1280×800 and a report entry.

## Non-goals

- Regenerating masks, collision or cover zones to match a new plate.
- Choosing the image model (the `agy` tool exposes none).
- A quarantine directory for rejected attempts; keeping attempt images.
- Changing `check-overrides`, the engine loader or the manifest schema
  number.
- Any provider other than the `agy` CLI.
