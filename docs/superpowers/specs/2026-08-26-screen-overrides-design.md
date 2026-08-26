# Full-screen resource overrides (character select and friends) — design

Date: 2026-08-26. Status: approved design. Part 1 of 3 (screen overrides →
startup menu → intro cutscene); independent of the other two.

## Goal

Let the seven 320x200 full-screen images in `ITD_RESS.PAK` be exported with
layout guides, regenerated externally (or by `make regenerate-backgrounds`),
validated, and loaded at run time from the same override directory the
camera backgrounds already use. The character selection screens (entries 10
and 14) are the motivating case; the code path is the same for all seven.

Entries (`AITD1.h`):

| entry | FITD name | used by |
|---|---|---|
| 6 | `AITD1_LETTRE` | reading (letter) |
| 7 | `AITD1_LIVRE` | reading (book), credits page |
| 8 | `AITD1_CARNET` | reading (notebook) |
| 10 | `AITD1_PERSO_CHOICE` | character select, portraits |
| 12 | `AITD1_DEAD_END` | game over |
| 13 | `AITD1_TITRE` | title screen (startup menu spec) |
| 14 | `AITD1_FOND_INTRO` | character select, story page |

Entry 11 (`GRENOUILLE`, copy-protection wheel) is excluded: nothing draws it.

## Non-goals

- No change to how the UI composites text, cadres or portrait crops over a
  screen: an override replaces the plate only. Text stays engine-rendered.
- No palette override for screens (they are decoded with the game palette at
  load; an override PNG is already RGB).
- No new dependency; PNG I/O stays in `tools/`.

## Layout and loading

- Path: `DIR/screens/ress<NN>.png` (`NN` = two-digit entry). Defined once as
  `render/asset_resolver.override_screen_path(override_dir, entry)`; the
  export writes through the matching `background_export.screen_rel_path`.
  Change both or neither (same rule as backgrounds).
- `AssetResolver.resource_screen(entry)` → `ImageAsset(pixels, is_override)`.
  Override present and valid → its pixels (any size, RGB, ≤ 8192 on each
  side, validated by the existing `_require_rgb`); absent → silent fallback
  to `Assets.resource_screen(entry)`; present but unreadable/invalid → one
  warning, recorded in `failures`, fallback. Cached like backgrounds.
- The UI is the consumer. `app/ui.py` functions that call
  `assets.resource_screen(...)` (`render_character_select`,
  `render_reading`/`reading_pages`, `render_game_over`, picture rendering)
  take the resolver the shell already builds instead of `Assets`. Callers
  that receive a non-320x200 override scale it to 320x200 with
  `pygame.transform.smoothscale` at composite time so the existing rect
  geometry (portrait crops, text columns, cadre) stays valid; the renderer
  presents the 320x200 UI frame as today. `ponytail:` composite at override
  resolution is the upgrade path, not this milestone.
- `Assets.resource_screen` is unchanged and remains the raw decode.

## Export

`render/background_export.py` (pure) gains:

- `SCREEN_ENTRIES = (6, 7, 8, 10, 12, 13, 14)` and per-entry guide rects
  (`SCREEN_GUIDES`): the regions the UI blits over, in 320x200 space —
  portrait crops (`CharacterLayout.PORTRAITS`) and cadre centres for 10;
  the two story text columns (x 5..155 and 165..315, y 5..194 — `AITD1.cpp`
  `Lire` calls) for 14; the credits text box (48,2)-(260,197) for 7; the
  reading text area for 6/7/8; the whole frame for 12 and 13. Rect values
  are defined in this module (pygame-free ints), and `app/ui.py`'s layouts
  import them so the two can never drift.
- `screen_record(entry, pixels)` → manifest entry `{entry, name, source,
  guide, sha256, width, height, blits: [...]}`.
- `screen_guide(pixels, entry, scale)` → nearest-upscaled plate with the
  blit rects drawn in the legend's blue ("engine draws over this") and a
  12px legend footer, same style as `guide_overlay`.
- `export_manifest` takes an optional `screens` list; `MANIFEST_SCHEMA`
  becomes 2 with `screens` an array (empty allowed). Readers accept 1.

`tools/export_backgrounds.py`: `--screens/--no-screens` (default on) writes
`screens/ressNN.png` and `guides/screens/ressNN.png`; the `backgrounds/`
refusal-without-`--force` rule extends to `screens/`. Manifest merge keeps
`screens` records across floor-subset runs.

## Check and regenerate

- `render/override_check.py` `check_overrides`/`coverage` gain the screens
  kind: shape/aspect findings identical to backgrounds; coverage reports
  `screens: n/7`. `tools/check_overrides.py --proof` renders a side-by-side
  for each overridden screen (original | override) — no scene render needed.
- `tools/regenerate_backgrounds.py` `discover` yields screen items alongside
  cameras (a `Camera`-like record with `kind="screen"`); prompts describe the
  guide's blue regions as "keep these areas plain, text and portraits are
  drawn there by the game". `--screens/--no-screens`, default on.
- `docs/ai-background-regeneration.md` gains a "Screens" section.

## Testing

- Pure: `screen_record` fields and sha; `screen_guide` size, legend footer,
  and that every blit rect for an entry lies inside 320x200; the manifest
  round-trip with schema 2 and acceptance of schema 1.
- Resolver: override hit, silent absence, invalid-image warning + fallback,
  cache identity, path function pinned to `screens/ress10.png`.
- UI: `render_character_select` with a resolver whose screen 10 is a
  solid-colour 640x400 override renders that colour outside the portrait
  crops (headless, `SDL_VIDEODRIVER=dummy`).
- Tools: export round-trip with monkeypatched `save_png` (files named per
  layout, manifest has 7 screens); check reports coverage; regenerate dry-run
  lists screens and calls no subprocess.
- Layering: no new pygame importer in `render/` (`test_layering.py` already
  enforces); `background_export` stays pure.

## Files

| file | change |
|---|---|
| `PyAitD/render/asset_resolver.py` | `override_screen_path`, `AssetResolver.resource_screen` |
| `PyAitD/render/background_export.py` | screen entries, guide rects, `screen_record`, `screen_guide`, manifest v2 |
| `PyAitD/render/override_check.py` | screens kind in check/coverage |
| `PyAitD/app/ui.py` | screen consumers take the resolver; layouts import guide rects |
| `PyAitD/app/shell.py` | pass the resolver where `assets` was passed for screens |
| `tools/export_backgrounds.py`, `tools/check_overrides.py`, `tools/regenerate_backgrounds.py` | screens kind |
| `docs/ai-background-regeneration.md`, `AGENTS.md`, `CONTEXT.md`, `Makefile` | docs; `screens=0` knob |
| tests listed above | |
