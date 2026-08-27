# AITD1 UI Layer at Native Resolution Design

Date: 2026-08-27

Status: Approved design — awaiting implementation plan

Builds on: the enhanced graphics scene layer
(`2026-08-25-enhanced-graphics-scene-layer-design.md`), which gave the *scene*
an internal render target at a multiple of 320x200 and left the UI layer at
320x200

Supersedes: nothing. It changes the size of the canvas
`PyAitD/app/ui.py` presenters paint on, and no committed decision fixes that
size.

## Goal

Draw the UI layer — character selection, inventory, the system menu, found
and reading modals, messages, the HUD and the cursor — at the window's own
resolution instead of at 320x200. Text is the visible motivation: every glyph
is currently rendered into a 320x200 canvas and stretched over the window with
nearest filtering, so at a 1280x800 window each text pixel is a 4x4 block.

This is a presentation change. No game state, no input handling and no
simulation code is touched.

## Current state

- `ui.transparent_canvas()` returns a `(200, 320, 4)` uint8 array. Every
  presenter paints on one, via `_to_surface` / `_to_frame` around a pygame
  surface.
- Fonts are `pygame.font.Font(None, size)` at sizes 15 to 20, chosen for a
  320x200 canvas. This is pygame's default font, not AITD1's bitmap font: the
  UI layer is already a modern presentation of the game's text, so sharpening
  it raises no fidelity question.
- `Renderer.present(ui_canvas)` uploads the canvas into `_ui_tex`, a texture
  created once at the module constants `IMG_W, IMG_H = 320, 200` with NEAREST
  filtering, and draws it over the scene on a quad from
  `fit_quad(IMG_W, IMG_H, win_w, win_h)`.
- The software fallback path composites instead: `composite_ui(scene_rgb,
  ui_canvas)` blends the UI over a 320x200 scene thumbnail.
- Hit-testing is entirely logical: `Renderer.window_to_logical` maps a window
  position into 320x200, and every `hit_test_*` function and every
  `PlayLayout` / `ModalLayout` rect is expressed there.

## Decisions taken during brainstorming

1. The whole UI layer moves to the higher resolution, not only its text:
   panels, borders, rules, the cursor and the sprites alike.
2. The canvas is sized from the **live window viewport**, not from the
   existing render-scale setting and not from a new setting of its own. Text
   is then as sharp as the display allows regardless of the scene's internal
   scale.
3. Presenters keep authoring in **logical 320x200 coordinates** through a
   painter that scales on their behalf (approach A). Authoring directly in
   native pixels was rejected: hit-testing must stay logical, and having the
   drawing and picking of one widget use two coordinate systems is a defect
   waiting to happen.
4. A fractional scale is used as-is for text and vector shapes, and rounded to
   an integer for pixel-art sprites, which do not survive fractional
   resampling.
5. The software fallback keeps the UI at scale 1. That path already announces
   itself as degraded through a settings notice; upscaling its 320x200
   thumbnail would make the scene look no sharper while costing the work.

## Architecture

### The painter

A new `UIPainter` in `PyAitD/app/ui.py` is the whole of the new seam. It owns

- `surface`: a `pygame.Surface` with per-pixel alpha, sized
  `(round(320 * s), round(200 * s))`;
- `scale`: the float `s`.

Its API takes logical coordinates and logical font sizes, and is the only
place that knows `s`:

| method | behaviour |
|---|---|
| `rect(colour, logical_rect, width=0)` | scales the rect; `width` scales too, floored at 1 so a hairline never vanishes |
| `line(colour, start, end, width=1)` | as above |
| `circle(colour, centre, radius, width=0)` | as above |
| `text(label, size, colour, *, center=None, topleft=None)` | renders at `round(size * s)` and places the glyph at the scaled anchor |
| `text_size(label, size)` | the *logical* width and height, so wrapping maths stays in logical units |
| `sprite(pixels, logical_rect)` | nearest-upscales the array by `max(1, round(s))`, then blits to the scaled rect |
| `to_frame()` | the RGBA `(h, w, 4)` array `present()` consumes |

`s = 1` must reproduce today's output byte for byte. That is what lets the
existing render tests keep asserting the pixels they assert now.

`transparent_canvas()` is replaced by `UIPainter(scale)`; a painter starts
fully transparent, so the renderer's compositor still only replaces pixels a
presenter actually touched.

### Presenters

Every presenter takes a painter instead of creating a surface:
`render_character_select`, `render_inventory`, `render_system_menu`,
`render_found`, `render_reading`, `render_picture`, `render_game_over`,
`render_title`, `render_startup_menu`, `overlay_messages`,
`render_play_hud`, `render_hit_feedback`, `render_cursor`, and the `_button`
helper they share.

Their coordinate literals do not change. `(160, y)`,
`PlayLayout.INVENTORY_HIT`, `ModalLayout.INVENTORY_ROWS` and every other
layout constant stay logical and stay shared with the hit tests that consume
them. Only the drawing calls change, from `surface.blit(...)` /
`pygame.draw.rect(surface, ...)` to the painter's methods.

`layout_book` currently takes a `pygame.font.Font`. It moves to taking the
painter and a logical size, measuring through `painter.text_size`, so line
breaking stays in logical units and produces the same breaks at every scale.
Identical wrapping across scales is a requirement, not an accident: a reading
page that re-flowed when the window resized would change how many pages a book
has.

### Renderer

`render_active_mode` creates one painter per frame from the renderer's current
UI scale and passes it to whichever presenter runs; the render loop's later
overlays (`render_hit_feedback`, `render_play_hud`, `render_cursor`) paint on
that same painter rather than re-wrapping a numpy array between each. It
returns the painter, and the loop calls `to_frame()` once, at the point it
hands the canvas to `present()`. Presenters therefore return nothing; they
paint. That is the one call-signature change outside `ui.py`.

`Renderer` gains `ui_scale()`, returning `min(win_w / 320, win_h / 200)` for
the GL path and `1.0` for the software path. That is the same expression
`window_to_logical` inverts, so the drawn size and the picked size stay
consistent by construction rather than by two constants agreeing.

`present()` sizes `_ui_tex` from the canvas it is handed, recreating the
texture only when the size differs from the current one, and releasing the old
one when it does. `fit_quad` works from the aspect ratio, so the quad, the
letterboxing and the flip are unchanged. `IMG_W, IMG_H` remain the constants
describing the *logical* frame; they stop describing the UI texture.

### Pixel art and the scene thumbnail

Portraits, inventory icons and `render_picture`'s full-screen image are game
pixel art. They go through `painter.sprite`, which nearest-upscales by an
integer, so they stay exact and blocky rather than resampled.

`render_inventory` and `render_game_over` composite a 320x200 scene thumbnail
behind themselves. They nearest-upscale it to the canvas through the same
path. The consequence is deliberate and worth stating: behind those two
modals the *scene* stays 320x200-blocky while the UI over it is sharp. Making
those two sample the full-resolution scene instead is a separate change and is
out of scope here.

## Out of scope

- Sampling the full-resolution scene behind the inventory and game-over
  modals.
- Replacing pygame's default font with AITD1's bitmap font, or any change to
  which font is used.
- Any change to layout, wording, colours or spacing. This design changes
  resolution only; at `s = 1` the output is unchanged.
- Any change to hit-testing, the mouse contract, or input.

## Testing

- Existing render tests build a painter at `s = 1` and keep their current
  pixel assertions. They are the regression net for this change and are not
  rewritten alongside it.
- A painter at `s = 3` places a rect and a glyph at three times the logical
  position, and reports `text_size` in logical units.
- `sprite` at a fractional scale upscales by an integer factor and leaves
  every source pixel exactly representable.
- `layout_book` produces identical line breaks at `s = 1`, `s = 2.5` and
  `s = 4`.
- `present()` accepts canvases of two different sizes in succession, and
  releases the texture it replaces.
- The software fallback path reports `ui_scale() == 1.0`.
- The headless suite runs with `SDL_VIDEODRIVER=dummy`, so painter tests must
  not need a display; `pygame.font` is already initialised on demand by
  `_font`.

## Risks

- **Fractional scales and text placement.** Rounding a scaled centre can move
  a glyph by a pixel relative to the box it sits in. Mitigated by scaling the
  anchor rather than the drawn glyph, and by the `s = 1` byte-for-byte
  requirement pinning the common case.
- **Texture churn on resize.** A window dragged to a new size every frame
  would recreate `_ui_tex` every frame. Mitigated by recreating only on an
  actual size change; a resize drag is already the least performance-critical
  moment in the loop.
- **The change is broad and mechanical.** Around 46 draw sites move. The
  `s = 1` requirement plus the untouched existing assertions are what make
  that safe to do in one pass.
