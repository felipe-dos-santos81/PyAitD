# Regenerating backgrounds with AI

PyAitD can play with replacement camera backgrounds from an override
directory (`--overrides DIR`, see README). This workflow exports the
originals with structural guides so you can regenerate them in any external
image tool — ControlNet, image-to-image, an upscaler, a paint program — and
checks the results the way the game will load them. Only the optional `make
regenerate-backgrounds` step calls an AI service (Gemini, your key); the
repo ships no model, no key and no game data.

## 1. Export

    make export-backgrounds                                 # all floors, guide scale 4, into data/aitd1/overrides
    make export-backgrounds out=~/aitd-overrides floors=0 scale=2

Produces:

    ~/aitd-overrides/manifest.json
    ~/aitd-overrides/backgrounds/floorNN/cameraNNN.png   the 320x200 originals
    ~/aitd-overrides/guides/floorNN/cameraNNN.png        originals x4 with structure lines
    ~/aitd-overrides/screens/ressNN.png                  the seven ITD_RESS full-screen originals
    ~/aitd-overrides/guides/screens/ressNN.png           originals x4 with blit-rect guides

The export refuses to run into a directory that already has `backgrounds/`
(your regenerated images) unless you pass `force=1`. Pass `screens=0` to
skip the ITD_RESS screens.

## 2. Regenerate

Overwrite `backgrounds/floorNN/cameraNNN.png` in place. Rules the engine
cares about:

- A PNG pygame can decode (RGB, RGBA, palettized and greyscale all load as
  RGB), any size up to 8192x8192.
- Keep the 16:10 aspect (320x200 x N). Anything else is stretched.
- Integer multiples of 320x200 (640x400, 1280x800, ...) map cleanly to the
  internal render target; other sizes work but resample.

Use the guide as a structure reference (ControlNet canny/lineart, or as a
second input layer). The lines mean:

- **red** — foreground occlusion masks: actors walking behind these
  regions are hidden. If a regenerated plate moves a pillar, the mask
  will not follow it.
- **blue** — hard collision boxes: walls and furniture the hero cannot
  walk through. Keep visible geometry inside them.
- **green** — walkable cover polygons: where click-to-walk can send the
  hero. Keep the floor readable here.

The 12px footer strip repeats the three colours in that order. The
mapping is also in `manifest.json` under `legend`.

Masks, collision and walkable areas are engine data, not pixels: they do
not change when the background does. A plate that redraws doors or stairs
elsewhere will look wrong in play even though it loads fine.

## 2b. Regenerate with Gemini (optional, in-repo)

    command -v agy                                # once: the agy CLI must be on PATH
    make regenerate-backgrounds dry=1             # list what would run, no calls
    make regenerate-backgrounds                   # data/aitd1/overrides -> data/aitd1/overrides-ai
    make regenerate-backgrounds floors=0 style="Sunlit, warm, clean." force=1

For each `backgrounds/floorNN/cameraNNN.png` (with its guide when present)
the tool asks `gemini-3.1-pro` (via `agy`) for a scene description, stores it in
`data/aitd1/overrides-ai/prompts.json`, then asks `gemini-3-pro-image` to render
that description with the original and guide as references. The result is
centre-cropped to 16:10 and scaled to 1280x800, so `check-overrides` never
reports `aspect` or `size` for it. `manifest.json` is copied across so
coverage counts every output as `regenerated`.

- Cameras that already exist in the output are skipped; rerun after an
  interruption and it continues. `force=1` redoes them and their prompts.
- Edit a prompt in `prompts.json`, delete that camera's PNG and rerun to
  regenerate only it with your wording.
- A camera that fails (quota, no image returned) is logged and skipped;
  exit status 1 means at least one failed, rerun to retry.
- `text_model=` / `image_model=` override the models; `in=` and `out_ai=`
  the directories.

Then `make check-overrides overrides=overrides-ai proof=1` and
`make run overrides=overrides-ai`.

## Screens

The seven full-screen ITD_RESS images (6 letter, 7 book/credits, 8 notebook,
10 character portraits, 12 dead end, 13 title, 14 story) export to
`screens/ressNN.png`. Their guides outline in blue the regions the game
draws over (portrait crops, text columns, cadre): keep those areas plain.
Any size up to 8192x8192 loads; non-320x200 overrides are scaled to
320x200 when composited, so text stays aligned. `check-overrides` lists
them as `screen ressNN` and reports a `screens:` coverage line; `proof=1`
writes `screen-ressNN.png` side-by-sides. `make export-backgrounds
screens=0` / `regenerate-backgrounds screens=0` skip them.

One of the seven is not yet read at run time: 12 (dead end) is exported for
completeness, but this reimplementation's game-over overlay composes a
shaded scene thumbnail instead of drawing that plate, since `LM_GAME_OVER`
freezes the last PLAY frame rather than showing it. An override for it
loads and passes `check-overrides` cleanly -- it is simply not on screen
yet. (13, title, was in the same boat until the title/menu boot flow
landed; it is drawn on every boot now, by `app/startup.py`'s `render_title`.)

## 3. Check

    make check-overrides                                    # checks ./overrides
    make check-overrides overrides=~/aitd-overrides proof=1   # also renders original|override to docs/graphics-proof/overrides/

Findings, one line each, then a per-floor coverage summary:

| kind | meaning | what to do |
|---|---|---|
| `invalid` | the game would ignore this file and use the original (unreadable/corrupt, or larger than 8192x8192); the detail is the loader's message | re-export from your tool as a plain PNG no larger than 8192x8192 |
| `aspect` | not 16:10 within 1% — the game would stretch it | crop or outpaint to 16:10 |
| `size` | smaller than 320x200 or not an integer multiple of it | fine to play; resize if you want crisp scaling |
| `missing` | counted, not listed: the original is used | nothing |

Exit status is 1 when any `invalid` or `aspect` finding exists. Coverage
(`regenerated / original / missing / invalid / aspect`) compares each file's
pixels with the sha256 recorded in `manifest.json` at export time, so
untouched exports count as `original`.

## 4. Play

    make run overrides=~/aitd-overrides
    .venv/bin/python -m PyAitD --overrides ~/aitd-overrides --background-filter bilinear

`--overrides` applies to the current session only and is never persisted --
there is no Configuration row for it; pass `make run overrides=DIR` (or the
flag) each time.
