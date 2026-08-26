# Gemini background regeneration: describe, generate, check

Date: 2026-08-25. Status: approved design, awaiting implementation plan.

## Goal

Close the loop that `docs/superpowers/specs/2026-08-25-ai-background-regeneration-design.md`
deliberately left open: a repo tool that takes the exported override
directory (originals + guides + manifest), asks a Gemini text model to
describe each 320×200 background as a photorealistic scene prompt, then
asks a Gemini image model to render that prompt with the original and its
guide as references, and writes the result into a second override
directory the game and `make check-overrides` already understand.

## Decisions (from brainstorming)

- Lives in this repo under `tools/`, using the official `google-genai`
  SDK. This amends two standing rules, both updated by this work:
  - `AGENTS.md` "Dependencies fixed … Add nothing" gains one exception:
    the optional extra `ai = ["google-genai>=1.38"]`. The engine, the test
    suite and every other tool still import nothing new.
  - The earlier spec's non-goal "Calling any AI service from this repo"
    is superseded for this one tool; that spec's text gets a one-line
    pointer here.
- Provider: Google Gemini. Text model default `gemini-2.5-flash`, image
  model default `gemini-2.5-flash-image`; both overridable by flag.
- Two explicit steps with a persisted prompt file, not one edit call:
  the prompt is reviewable and editable per camera.
- Inputs per camera: the original PNG plus the matching guide PNG when it
  exists.
- Output: a separate `--out` directory in the override layout; input
  directory never modified.

## Global constraints

- `# SPDX-License-Identifier: GPL-2.0-only` first line of every Python file.
- Engine modules untouched: `asset_resolver.py`, `render_*.py`, `scene.py`,
  `floor.py`, `__main__.py`, `background_export.py`, `override_check.py`
  do not change.
- `google-genai` is imported only inside `tools/regenerate_backgrounds.py`,
  lazily, in one function (`make_client`). Importing the module without the
  SDK installed succeeds; only a real run without it fails, with the exact
  message `google-genai is not installed: run .venv/bin/pip install -e ".[dev,ai]"`
  and exit 2.
- No Pillow. Decoding and scaling go through pygame (`pygame.image.load`
  from a `BytesIO`, `pygame.transform.smoothscale`); the crop is numpy
  array slicing on the decoded pixels, and
  `tools/export_backgrounds.save_png` writes the result.
- The unit suite never touches the network: every test injects a fake
  client. The one live test is skipped unless both `GEMINI_API_KEY` and
  `PYAITD_LIVE_AI=1` are set.
- Output directories are git-ignored (`overrides-ai/` added to
  `.gitignore`); this repo still ships no game data and no generated art.
- The API key comes only from the environment (`GEMINI_API_KEY`); no flag,
  no config file, never logged.

## Architecture

| Unit | Role | Deps |
|---|---|---|
| `tools/regenerate_backgrounds.py` | Everything: discovery, prompt cache, the two Gemini calls, post-processing, CLI. Pure helpers are module-level functions so tests reach them without a client. | pygame (post-processing), `google-genai` (lazy, `make_client` only) |
| `Makefile` `regenerate-backgrounds` | `in=overrides out=overrides-ai floors= style= force=1 dry=1 text_model= image_model=` | — |
| `pyproject.toml` | `[project.optional-dependencies] ai = ["google-genai>=1.38"]` | — |
| `docs/ai-background-regeneration.md` | New section "2b. Regenerate with Gemini" between Regenerate and Check | — |
| `README.md`, `AGENTS.md` | One line each: the target and the dependency exception | — |
| `tests/test_regenerate_backgrounds.py` | Unit tests with a fake client; one live test | pygame |

### Module interface (`tools/regenerate_backgrounds.py`)

```python
DEFAULT_TEXT_MODEL = "gemini-2.5-flash"
DEFAULT_IMAGE_MODEL = "gemini-2.5-flash-image"
TARGET_SIZE = (1280, 800)            # 4 × 320×200
GENERATE_ASPECT = "3:2"              # nearest Gemini ratio to 16:10 (3:2 is narrower); extra height is centre-cropped after
PROMPTS_FILE = "prompts.json"

@dataclasses.dataclass(frozen=True)
class Camera:
    floor: int
    camera: int
    source: pathlib.Path          # IN/backgrounds/floorNN/cameraNNN.png
    guide: pathlib.Path | None    # IN/guides/floorNN/cameraNNN.png if it exists
    key: str                      # "floorNN/cameraNNN"

def discover(in_dir: pathlib.Path, floors: set[int] | None) -> list[Camera]
def describe_prompt(guide_present: bool) -> str
def generation_prompt(description: str, style: str, guide_present: bool) -> str
def describe(client, model: str, cam: Camera) -> str
def generate(client, model: str, cam: Camera, prompt: str) -> bytes
def fit_to_target(png_bytes: bytes) -> np.ndarray  # (800, 1280, 3) uint8
def load_prompts(path) -> dict; def save_prompts(path, prompts) -> None   # atomic
def make_client() -> object
def regenerate(cams, out_dir, *, client, text_model, image_model, style,
               force, dry_run, log=print) -> tuple[int, int]   # (done, failed)
def main(argv=None) -> int
```

`client` is duck-typed: the only method used is
`client.models.generate_content(model=..., contents=[...], config=...)`
returning an object whose `.text` (describe) or
`.candidates[0].content.parts[i].inline_data.data` (generate) is read. The
fake client in tests implements exactly that.

## Data flow

1. **Discover.** Recursively glob `IN/backgrounds/floor[0-9][0-9]/camera[0-9][0-9][0-9].png`,
   sorted; keep floors in `--floors`. Each `Camera` records the guide path
   only if the file exists. Zero cameras → message and exit 2.
2. **Resume filter.** A camera whose `OUT/backgrounds/<key>.png` exists is
   skipped ("exists, skipped") unless `--force`. Cloud calls cost money;
   an interrupted run picks up where it stopped.
3. **Describe.** If `prompts[key]` exists and `--force` is not set, reuse
   it. Otherwise send `[original PNG part, guide PNG part (if any),
   describe_prompt(...)]` to the text model and store
   `{"prompt": text.strip(), "model": text_model, "sha256": <sha256 of the
   source file bytes>}`. `prompts.json` is saved after every camera so a
   crash loses at most one description. The user may hand-edit a prompt
   and re-run with `--force` on a `--floors` subset; edited prompts are
   never overwritten without `--force`.
4. **Generate.** Send `[original PNG part, guide PNG part (if any),
   generation_prompt(prompt, style, guide_present)]` to the image model
   with `response_modalities=["TEXT", "IMAGE"]` (image-only is rejected by
   some image models) and
   `image_config=ImageConfig(aspect_ratio=GENERATE_ASPECT)` — `ImageConfig`
   first shipped in `google-genai` 1.38, hence the `>=1.38` floor. Take the
   first `inline_data` part with non-empty data whose `mime_type` starts
   with `image/`; none → that camera fails ("no image in response").
5. **Fit.** `fit_to_target`: decode with `pygame.image.load`, convert to an
   `(h, w, 3)` uint8 array with `pygame.surfarray.array3d`; center-crop to
   the largest 16:10 rectangle with numpy slicing (exact integer maths:
   `if w*10 > h*16: new_w = h*16//10 else new_h = w*10//16`); `smoothscale`
   to `TARGET_SIZE` and convert back to an array. Always yields 1280×800
   uint8, so `check-overrides` reports neither `aspect` nor `size`.
6. **Write.** `save_png(surface, OUT/backgrounds/<key>.png)` (temp +
   `os.replace`, from `tools/export_backgrounds`). After the run, copy
   `IN/manifest.json` to `OUT/manifest.json` if present and not already
   there, so coverage counts these as `regenerated`.
7. **Dry run.** `--dry-run` performs discovery and the resume filter, then
   prints one line per camera that would be processed (`key`, guide
   yes/no, prompt cached yes/no) and exits 0 without creating a client.

### Prompts

`describe_prompt(guide_present)`:

> Describe this 320x200 pixel-art background from a 1992 adventure game as
> a single-paragraph prompt for a photorealistic image generator. Name the
> room type, the camera angle and height, every piece of furniture and
> architecture with its position in frame, the light sources and their
> direction, materials and colours, and the mood. Do not mention pixel art,
> the game, or resolution. Output only the prompt.

with, when `guide_present`, the sentence: "The second image is the same
frame with an overlay: red outlines mark foreground objects that must stay
in front, blue boxes mark walls and solid furniture, green polygons mark
walkable floor. Describe the scene so those structures keep their places."

`generation_prompt(description, style, guide_present)`:

> Recreate the first image as a photorealistic photograph of the same
> scene, keeping the exact camera position, framing, perspective and the
> placement of every wall, door, window, stair and piece of furniture.
> `<description>` `<style>`

with, when `guide_present`: "The second image marks the layout: red
outlines are foreground objects, blue boxes are walls and solid furniture,
green polygons are walkable floor; keep all of them where they are and do
not draw the coloured lines."

`--style` defaults to `"Dark 1920s Louisiana mansion, moody film lighting, subtle grain."`
and is appended verbatim.

## Error handling

| Condition | Behaviour | Exit |
|---|---|---|
| `IN` has no `backgrounds/` or no matching camera | message | 2 |
| `GEMINI_API_KEY` unset (and not `--dry-run`) | `GEMINI_API_KEY is not set` | 2 |
| `google-genai` missing (and not `--dry-run`) | message from Global constraints | 2 |
| Per-camera API error, no image in response, undecodable image | logged `floorNN/cameraNNN: failed: <msg>`; run continues | 1 if any failed, else 0 |
| Guide missing | camera processed without guide, logged once per camera | — |
| Interrupted run | `prompts.json` and PNGs are atomic; rerun resumes | — |

Nothing in `IN` is ever written. Exceptions from the client are caught
per camera (`Exception`, since the SDK's error types are not imported
at module level); a `KeyboardInterrupt` propagates after the current
atomic write.

## Makefile

```make
regenerate-backgrounds: install ## Regenerate ./overrides backgrounds with Gemini into ./overrides-ai (in=, out=, floors=0-7, style=, force=1, dry=1, text_model=, image_model=)
	$(PYTHON) tools/regenerate_backgrounds.py "$(or $(in),overrides)" --out "$(or $(out_ai),overrides-ai)" --floors "$(or $(floors),0-7)" $(if $(style),--style "$(style)") $(if $(force),--force) $(if $(dry),--dry-run) $(if $(text_model),--text-model "$(text_model)") $(if $(image_model),--image-model "$(image_model)")
```

`out_ai` is used rather than `out` because `out ?= overrides` already
exists for the export target. `install` does not install the `ai` extra;
the doc says to run `.venv/bin/pip install -e ".[dev,ai]"` once.

## Testing (`tests/test_regenerate_backgrounds.py`)

Fixture: a temp `IN` built with `save_png` from numpy arrays: three
cameras — `floor00/camera000` (with guide), `floor00/camera001` (no
guide), `floor01/camera000` (with guide) — plus a `manifest.json`.
A `FakeClient` records every `generate_content` call and returns, per
model, a canned `.text` or a response object carrying a PNG's bytes
(generated in the test at 1536×1024, i.e. 3:2). Tests:

- `discover`: order, floor filter, guide `None` when the file is absent,
  empty result for a dir without `backgrounds/`.
- `describe_prompt`/`generation_prompt`: guide sentences present only when
  `guide_present`; style appended verbatim.
- `describe`: contents contain the source bytes, the guide bytes when
  present, and the text; returns the stripped `.text`.
- `generate`: `response_modalities == ["TEXT", "IMAGE"]`, aspect `3:2`, returns the
  bytes of the first image part; no image part → `RuntimeError`.
- `fit_to_target`: 1536×1024 → 1280×800; a 1000×1000 input crops to
  1000×625 then scales; a 16:10 input is not cropped (pixel check on a
  two-colour image).
- `regenerate` with the fake client: writes `OUT/backgrounds/floorNN/cameraNNN.png`
  of size 1280×800 for every camera; `prompts.json` has one entry per
  camera with `sha256` of the source; second run makes zero client calls
  (resume); `--force` re-calls both models; a hand-edited prompt survives
  a run without `--force`; a client that raises for one camera yields
  `(done=2, failed=1)` and the other two files; `manifest.json` copied.
- `main`: `--dry-run` exits 0 and creates no client and no files; missing
  key → 2; no cameras → 2; failed camera → 1.
- Round trip: `regenerate` output passed to `override_check.check_overrides`
  yields no `aspect`/`size`/`invalid` findings and coverage counts
  `regenerated == cameras`.
- Live (skipped without `GEMINI_API_KEY` and `PYAITD_LIVE_AI=1`): one
  synthetic 320×200 camera through the real models, output is 1280×800.

## Non-goals

- Regenerating masks, collision or cover zones to match a new plate.
- Any provider other than Gemini; any batching, caching or cost control
  beyond the resume filter.
- Persisting the API key or reading it from a file.
- Modifying `check-overrides` or the engine's override loader.
