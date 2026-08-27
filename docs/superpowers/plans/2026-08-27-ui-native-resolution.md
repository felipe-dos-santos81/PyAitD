# UI Layer at Native Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Draw the whole UI layer at the window's own resolution instead of at 320x200, so text in character selection, the inventory and every other screen is as sharp as the display allows.

**Architecture:** A `UIPainter` owns a pygame surface at `(320*s, 200*s)` and converts logical 320x200 coordinates on every call. Presenters keep authoring in logical coordinates and stop building surfaces themselves. `Renderer` reports the live viewport scale and sizes its UI texture from the canvas it is handed. Hit-testing is untouched and stays logical.

**Tech Stack:** Python 3.12, pygame-ce, ModernGL, NumPy, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-27-ui-native-resolution-design.md`

## Global Constraints

- `# SPDX-License-Identifier: GPL-2.0-only` is the first line of every Python file.
- Dependencies are fixed: pygame-ce, ModernGL, NumPy, pytest. Add nothing.
- Never call `pygame.mouse.set_relative_mode`, `pygame.event.set_grab` or `pygame.mouse.set_pos` anywhere under `PyAitD/`.
- Package layering: `render/` and `games/` import only `engine/`; `engine/` imports none of the others; `app/` may import everything. `tests/test_layering.py` enforces it.
- Every test runs headless: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`.
- **At `scale=1.0` every presenter must produce byte-identical output to today.** This is the safety property the whole plan rests on: the existing render tests keep their current assertions and are the regression net.
- Hit-testing, `window_to_logical`, `PlayLayout`, `ModalLayout`, `CharacterLayout`, `SystemMenuLayout`, `StartupLayout`, `SettingsNoticeLayout` and every `hit_test_*` function stay in logical 320x200 units and are **not** modified by any task.
- Pixel-art rule: art composed at logical size (cadre tiles, sprites, ITD_RESS screens) is built on a logical surface and then scaled once through the painter; text and vector shapes are drawn directly at scale.

---

### Task 1: `UIPainter` core — surface, scale, shapes

**Files:**
- Modify: `PyAitD/app/ui.py` (add `UIPainter` next to `transparent_canvas`, around line 615)
- Test: `tests/test_ui_render.py`

**Interfaces:**
- Produces: `UIPainter(scale=1.0, *, fill=None)` with attributes `.scale: float`, `.surface: pygame.Surface`, `.size -> tuple[int, int]` (the canvas pixel size); methods `rect(colour, rect, width=0, border_radius=0)`, `line(colour, start, end, width=1)`, `circle(colour, centre, radius, width=0)`, `shade(colour)`, `to_frame() -> np.ndarray`.

- [ ] **Step 1: Write the failing test**

```python
def test_painter_at_scale_one_matches_a_transparent_canvas():
    from PyAitD.app.ui import UIPainter, transparent_canvas
    painter = UIPainter()
    assert painter.size == (320, 200)
    assert np.array_equal(painter.to_frame(), transparent_canvas())


def test_painter_scales_shapes_by_its_scale():
    from PyAitD.app.ui import UIPainter
    painter = UIPainter(3)
    assert painter.size == (960, 600)
    painter.rect((255, 0, 0), pygame.Rect(10, 20, 4, 5))
    frame = painter.to_frame()
    # the logical rect (10,20)-(14,25) lands at (30,60)-(42,75)
    assert tuple(frame[61, 31][:3]) == (255, 0, 0)
    assert frame[59, 29][3] == 0, "nothing painted above/left of the scaled rect"
    assert frame[76, 43][3] == 0, "nothing painted below/right of it"


def test_painter_hairlines_survive_scaling_down_to_one_pixel():
    from PyAitD.app.ui import UIPainter
    painter = UIPainter(1)
    painter.rect((255, 255, 255), pygame.Rect(0, 0, 10, 10), width=1)
    assert painter.to_frame()[0, 0, 3] == 255, "a 1px outline must not vanish"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_ui_render.py -q -k painter`
Expected: FAIL with `ImportError: cannot import name 'UIPainter'`

- [ ] **Step 3: Implement `UIPainter`**

Add to `PyAitD/app/ui.py`, immediately after `transparent_canvas`:

```python
class UIPainter:
    """The canvas presenters paint on, in logical 320x200 coordinates.

    The only object that knows the UI's pixel scale. Presenters keep
    authoring against the same 320x200 grid the hit tests use -- every
    PlayLayout/ModalLayout rect is expressed there and is shared with
    `hit_test_*` -- while the surface underneath is as large as the window.
    Drawing and picking a widget in two different coordinate systems is the
    defect this exists to prevent.

    At scale 1 every method must produce exactly what the old
    surface-per-presenter code produced: the existing render tests assert
    those pixels and are what makes this conversion safe.
    """

    def __init__(self, scale=1.0, *, fill=None):
        self.scale = float(scale)
        self.surface = pygame.Surface(self.size, flags=pygame.SRCALPHA)
        if fill is not None:
            self.surface.fill(fill)

    @property
    def size(self):
        return (round(320 * self.scale), round(200 * self.scale))

    def _pt(self, point):
        return (round(point[0] * self.scale), round(point[1] * self.scale))

    def _rect(self, rect):
        rect = pygame.Rect(rect)
        left, top = self._pt(rect.topleft)
        right, bottom = self._pt(rect.bottomright)
        return pygame.Rect(left, top, right - left, bottom - top)

    def _width(self, width):
        # 0 means "filled" to pygame and must stay 0; anything else keeps at
        # least one pixel, so a hairline never scales away to nothing
        return 0 if width == 0 else max(1, round(width * self.scale))

    def rect(self, colour, rect, width=0, border_radius=0):
        pygame.draw.rect(
            self.surface, colour, self._rect(rect), width=self._width(width),
            border_radius=round(border_radius * self.scale),
        )

    def line(self, colour, start, end, width=1):
        pygame.draw.line(
            self.surface, colour, self._pt(start), self._pt(end),
            width=max(1, round(width * self.scale)),
        )

    def circle(self, colour, centre, radius, width=0):
        pygame.draw.circle(
            self.surface, colour, self._pt(centre),
            max(1, round(radius * self.scale)), width=self._width(width),
        )

    def shade(self, colour):
        """A full-canvas wash, the scaled form of blitting a filled SRCALPHA
        surface over the whole 320x200 frame."""
        wash = pygame.Surface(self.size, flags=pygame.SRCALPHA)
        wash.fill(colour)
        self.surface.blit(wash, (0, 0))

    def to_frame(self):
        return _to_frame(self.surface)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_ui_render.py -q -k painter`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the whole suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/ -q`
Expected: PASS, same count as before plus 3.

- [ ] **Step 6: Commit**

```bash
git add PyAitD/app/ui.py tests/test_ui_render.py
git commit -m "feat: a UI painter that scales logical coordinates"
```

---

### Task 2: Text on the painter

**Files:**
- Modify: `PyAitD/app/ui.py` (`UIPainter`, `layout_book` at line ~728)
- Test: `tests/test_ui_render.py`

**Interfaces:**
- Consumes: `UIPainter` from Task 1.
- Produces: `UIPainter.text(label, size, colour, *, center=None, topleft=None, midtop=None)`, `UIPainter.text_size(label, size) -> tuple[int, int]` in **logical** units; `layout_book(tokens, painter, size, width, max_lines)` replacing the old `(tokens, font, width, max_lines)`.

- [ ] **Step 1: Write the failing test**

```python
def test_painter_text_scales_size_and_anchor():
    from PyAitD.app.ui import UIPainter
    small, large = UIPainter(1), UIPainter(4)
    small.text("Wg", 16, (255, 255, 255), center=(160, 100))
    large.text("Wg", 16, (255, 255, 255), center=(160, 100))
    small_ink = np.argwhere(small.to_frame()[:, :, 3] > 0)
    large_ink = np.argwhere(large.to_frame()[:, :, 3] > 0)
    assert len(large_ink) > 4 * len(small_ink), "4x the scale must draw more ink"
    # both stay centred on the same logical point
    assert abs(small_ink[:, 1].mean() - 160) < 6
    assert abs(large_ink[:, 1].mean() / 4 - 160) < 6


def test_painter_text_size_is_logical_at_every_scale():
    from PyAitD.app.ui import UIPainter
    assert UIPainter(1).text_size("Hello", 16) == UIPainter(3.5).text_size("Hello", 16)


def test_layout_book_breaks_lines_identically_at_every_scale():
    from PyAitD.app.ui import UIPainter, layout_book
    from PyAitD.engine.text import BookToken
    tokens = (BookToken("text", "one two three four five six seven eight nine ten"),)
    pages = [
        layout_book(tokens, UIPainter(s), 15, 150, 12)
        for s in (1, 2.5, 4)
    ]
    assert pages[0] == pages[1] == pages[2], (
        "wrapping must stay logical: a book that re-flowed on resize would "
        "change its page count"
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_ui_render.py -q -k "painter_text or layout_book_breaks"`
Expected: FAIL with `AttributeError: 'UIPainter' object has no attribute 'text'`

- [ ] **Step 3: Add the text methods**

Add to `UIPainter` in `PyAitD/app/ui.py`:

```python
    def text(self, label, size, colour, *, center=None, topleft=None, midtop=None):
        glyph = _font(max(1, round(size * self.scale))).render(label, True, colour)
        if center is not None:
            rect = glyph.get_rect(center=self._pt(center))
        elif midtop is not None:
            rect = glyph.get_rect(midtop=self._pt(midtop))
        else:
            rect = glyph.get_rect(topleft=self._pt(topleft))
        self.surface.blit(glyph, rect)

    def text_size(self, label, size):
        """Logical width and height. Measured at scale 1 rather than by
        dividing a scaled measurement, so line breaking is bit-identical at
        every scale -- see layout_book."""
        return _font(size).size(label)
```

- [ ] **Step 4: Convert `layout_book` to the painter**

In `PyAitD/app/ui.py`, change the signature and the one measurement inside it:

```python
def layout_book(tokens, painter, size, width, max_lines):
    # `painter` and a logical font size rather than a Font: the measurement
    # must stay logical so a window resize cannot re-flow a book and change
    # how many pages it has.
```

and inside `push_line`, replace `font.size(candidate)[0] > width` with:

```python
            if current.strip() and painter.text_size(candidate, size)[0] > width:
```

- [ ] **Step 5: Update the four `layout_book` call sites**

`PyAitD/app/ui.py`:
- `render_settings_notice`: `layout_book((BookToken("text", message),), _font(15), 276, 5)` becomes `layout_book((BookToken("text", message),), painter, 15, 276, 5)`
- `reading_pages`: `layout_book(assets.book_tokens(effect.text_index), _font(16), 190, 8)` becomes `layout_book(assets.book_tokens(effect.text_index), painter, 16, 190, 8)`, and `reading_pages` takes `painter` as a new second parameter
- `render_character_select`: `layout_book(assets.book_tokens(entry), font, 150, 12)` becomes `layout_book(assets.book_tokens(entry), painter, 15, 150, 12)`

`PyAitD/app/startup.py`:
- `_credits_pages`: takes `painter` and passes it through the same way

Because `text_size` measures at scale 1, `assets.book_pages` stays a valid cache across scales and its key does not change.

- [ ] **Step 6: Run the tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/ -q`
Expected: PASS. Call sites that have not been converted yet still pass a painter into `layout_book`; if a presenter has no painter in scope yet, pass `UIPainter()` there and let Tasks 4-7 replace it.

- [ ] **Step 7: Commit**

```bash
git add PyAitD/app/ui.py PyAitD/app/startup.py tests/test_ui_render.py
git commit -m "feat: painter text, and logical measurement for book layout"
```

---

### Task 3: Sprites, and ITD_RESS screens at canvas size

**Files:**
- Modify: `PyAitD/app/ui.py` (`UIPainter`, `screen_surface` at line ~655)
- Test: `tests/test_ui_render.py`, `tests/test_asset_resolver.py`

**Interfaces:**
- Consumes: `UIPainter` from Tasks 1-2.
- Produces: `UIPainter.sprite(source, logical_dest, area=None)` (source is logical-size art, nearest-upscaled by `max(1, round(scale))`); `UIPainter.blit(surface, logical_dest, area=None)` (source is **already** canvas-scale); `screen_surface(resolver, entry, size=(320, 200))`.

> **Spec addendum this task carries.** The spec's sprite rule — nearest-upscale logical art by an integer — is right for cadre tiles and portraits, but `screen_surface` currently smooth-scales every ITD_RESS override *down* to 320x200 before anything is drawn on it. An override background larger than 320x200 (which the AI regeneration pipeline produces) would then be upscaled again for the canvas, throwing away the resolution it came with. The existing code carries a note calling compositing at override resolution "the upgrade path". This task takes it: `screen_surface` scales to the requested target instead of always to 320x200. Without it, the character-selection screen — one of the two the request named — keeps a 320x200 background under sharp text.

- [ ] **Step 1: Write the failing test**

```python
def test_painter_sprite_upscales_pixel_art_by_an_integer():
    from PyAitD.app.ui import UIPainter
    art = np.zeros((2, 2, 4), np.uint8)
    art[0, 0] = (255, 0, 0, 255)
    painter = UIPainter(3)
    painter.sprite(art, (0, 0))
    frame = painter.to_frame()
    for y in range(3):
        for x in range(3):
            assert tuple(frame[y, x][:3]) == (255, 0, 0), "each source pixel is a 3x3 block"
    assert frame[0, 3, 3] == 0, "and nothing bleeds past it"


def test_screen_surface_returns_the_requested_size_and_caches_per_size():
    from PyAitD.app.ui import screen_surface
    resolver = AssetResolver(_assets(), None)
    small = screen_surface(resolver, 10)
    big = screen_surface(resolver, 10, size=(1280, 800))
    assert small.get_size() == (320, 200)
    assert big.get_size() == (1280, 800)
    assert screen_surface(resolver, 10, size=(1280, 800)) is big, "cached per size"
    assert screen_surface(resolver, 10) is small, "and the old size still cached"
```

Use the existing fixture helper in `tests/test_ui_render.py` for `_assets()`; if that file has none, build one with `init_game(data_dir, profile).assets` and mark the test with the `data_dir` fixture.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_ui_render.py -q -k "sprite or screen_surface_returns"`
Expected: FAIL — `UIPainter` has no `sprite`, and `screen_surface` takes no `size`.

- [ ] **Step 3: Add the blit methods**

Add to `UIPainter`:

```python
    def blit(self, surface, logical_dest, area=None):
        """Blit a surface that is ALREADY at canvas scale, positioning it by
        logical coordinates. `area` is a logical sub-rect of the source."""
        self.surface.blit(
            surface, self._pt(logical_dest),
            None if area is None else self._rect(area),
        )

    def sprite(self, source, logical_dest, area=None):
        """Blit logical-size art, nearest-upscaled by an integer factor.

        Game pixel art does not survive fractional resampling, so the factor
        is rounded and the art stays exact and blocky; the fractional
        remainder shows as at most a pixel of placement, never as filtering.
        """
        surface = source if isinstance(source, pygame.Surface) else _to_surface(source)
        factor = max(1, round(self.scale))
        if factor != 1:
            width, height = surface.get_size()
            surface = pygame.transform.scale(surface, (width * factor, height * factor))
        dest = self._pt(logical_dest)
        if area is None:
            self.surface.blit(surface, dest)
        else:
            area = pygame.Rect(area)
            self.surface.blit(surface, dest, pygame.Rect(
                area.left * factor, area.top * factor,
                area.width * factor, area.height * factor,
            ))
```

- [ ] **Step 4: Give `screen_surface` a target size**

Replace the body of `screen_surface` in `PyAitD/app/ui.py`:

```python
def screen_surface(resolver, entry, size=(320, 200)):
    """An ITD_RESS full-screen resource as a Surface at `size`, cached per
    (resolver, entry, size).

    The target is the canvas size, not always 320x200: an override larger
    than the logical frame keeps the resolution it came with instead of being
    scaled down and then back up for a high-resolution canvas. Scaling is
    nearest when the target is an exact integer multiple of the source, so
    original 320x200 art stays blocky, and smooth otherwise, where nearest
    would only add ragged edges.

    The returned Surface is SHARED across calls: callers that draw on it
    directly must `.copy()` it first, or the drawing bleeds into every later
    call for that entry."""
    asset = resolver.resource_screen(entry)
    per_entry = _SCREEN_SURFACE_CACHE.setdefault(resolver, {})
    key = (entry, size)
    cached = per_entry.get(key)
    if cached is not None and cached[0] is asset.pixels:
        return cached[1]
    surface = _to_surface(np.ascontiguousarray(asset.pixels))
    source = surface.get_size()
    if source != size:
        exact = (size[0] % source[0] == 0 and size[1] % source[1] == 0
                 and size[0] // source[0] == size[1] // source[1])
        scaler = pygame.transform.scale if exact else pygame.transform.smoothscale
        surface = scaler(surface, size)
    per_entry[key] = (asset.pixels, surface)
    return surface
```

- [ ] **Step 5: Run the tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/ -q`
Expected: PASS. Existing callers pass no `size` and get 320x200 exactly as before.

- [ ] **Step 6: Commit**

```bash
git add PyAitD/app/ui.py tests/test_ui_render.py
git commit -m "feat: painter sprites, and ITD_RESS screens at the canvas size"
```

---

### Task 4: The overlay presenters

**Files:**
- Modify: `PyAitD/app/ui.py` (`_button` ~681, `overlay_messages` ~796, `render_play_hud` ~814, `render_hit_feedback` ~822, `render_settings_notice` ~836, `render_cursor` ~1126)
- Test: `tests/test_ui_render.py`

**Interfaces:**
- Consumes: `UIPainter` with `rect`, `text`, `shade`, `blit`, `sprite`.
- Produces: `_button(painter, rect, label, selected=False, size=18)`, `overlay_messages(painter, messages, assets)`, `render_play_hud(painter, *, inventory_available)`, `render_hit_feedback(painter, rects)`, `render_settings_notice(painter, message)`, `render_cursor(painter, logical_pos, kind)` — all returning `None` and painting in place.

- [ ] **Step 1: Write the failing test**

```python
def test_overlays_paint_in_place_and_match_the_old_canvas_at_scale_one():
    from PyAitD.app.ui import UIPainter, render_cursor, render_play_hud
    painter = UIPainter()
    render_play_hud(painter, inventory_available=True)
    render_cursor(painter, (100, 50), "attack")
    frame = painter.to_frame()
    assert frame[50, 100, 3] > 0, "the cursor painted at its logical point"
    assert frame[PlayLayout.INVENTORY.centery, PlayLayout.INVENTORY.centerx, 3] > 0


def test_overlays_scale_with_the_painter():
    from PyAitD.app.ui import UIPainter, render_cursor
    painter = UIPainter(4)
    render_cursor(painter, (100, 50), "attack")
    assert painter.to_frame()[200, 400, 3] > 0, "the cursor tracks the scaled point"
```

- [ ] **Step 2: Run to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_ui_render.py -q -k overlays`
Expected: FAIL — the presenters still expect a numpy frame and return one.

- [ ] **Step 3: Convert `_button`**

```python
def _button(painter, rect, label, selected=False, size=18):
    painter.rect((214, 190, 142) if selected else (78, 59, 46), rect, border_radius=3)
    painter.rect((245, 226, 178), rect, width=2, border_radius=3)
    painter.text(label, size, (20, 16, 12) if selected else (250, 242, 216),
                 center=pygame.Rect(rect).center)
```

Convert `_disabled_button` in `PyAitD/app/startup.py` the same way, keeping its own colours.

- [ ] **Step 4: Convert the four frame-taking overlays**

```python
def overlay_messages(painter, messages, assets):
    if all(message is None for message in messages):
        return
    y = 184
    for message in messages:
        if message is None:
            continue
        label = assets.system_text(message.message_id)
        painter.text(label, 16, (0, 0, 0), center=(161, y + 1))
        painter.text(label, 16, (255, 240, 185), center=(160, y))
        y -= 16


def render_play_hud(painter, *, inventory_available):
    if not inventory_available:
        return
    _button(painter, PlayLayout.INVENTORY, "INV", selected=True)


def render_hit_feedback(painter, rects):
    """Outline supplied actor rectangles without reading simulation state."""
    for rect in rects:
        target = pygame.Rect(rect)
        if target.width <= 0 or target.height <= 0:
            continue
        painter.rect((255, 255, 255), target.inflate(4, 4), width=2)
        painter.rect((255, 32, 32), target, width=2)


def render_settings_notice(painter, message):
    if message is None:
        return
    painter.shade((0, 0, 0, 190))
    painter.text("Settings error", 20, (255, 220, 170), center=(160, 38))
    lines = layout_book((BookToken("text", message),), painter, 15, 276, 5)[0]
    for index, (text, _centered) in enumerate(lines):
        painter.text(text, 15, (255, 255, 255), center=(160, 65 + index * 16))
    _button(painter, SettingsNoticeLayout.DISMISS, "Dismiss", selected=True)
```

- [ ] **Step 5: Convert `render_cursor`**

Replace its surface plumbing; the shape code becomes painter calls with the same numbers:

```python
def render_cursor(painter, logical_pos, kind):
    """Draw the pick cursor. Pure presentation: never touches world state."""
    if logical_pos is None:
        return
    colour = _CURSOR_COLORS.get(kind, _CURSOR_COLORS["walk"])
    x, y = int(logical_pos[0]), int(logical_pos[1])
    if kind == "inventory":
        painter.rect(colour, pygame.Rect(x - 5, y - 4, 11, 9), width=2)
        painter.line(colour, (x - 2, y - 6), (x + 2, y - 6), width=2)
    elif kind == "attack":
        painter.circle(colour, (x, y), 6, width=1)
        painter.line(colour, (x - 8, y), (x + 8, y), width=1)
        painter.line(colour, (x, y - 8), (x, y + 8), width=1)
    elif kind == "target":
        painter.rect(colour, pygame.Rect(x - 5, y - 5, 11, 11), width=1)
    elif kind == "push":
        painter.line(colour, (x - 7, y), (x + 7, y), width=2)
        painter.line(colour, (x - 7, y), (x - 3, y - 3), width=2)
        painter.line(colour, (x - 7, y), (x - 3, y + 3), width=2)
        painter.line(colour, (x + 7, y), (x + 3, y - 3), width=2)
        painter.line(colour, (x + 7, y), (x + 3, y + 3), width=2)
    elif kind == "blocked":
        painter.line(colour, (x - 4, y - 4), (x + 4, y + 4))
        painter.line(colour, (x - 4, y + 4), (x + 4, y - 4))
    else:
        painter.circle(colour, (x, y), 4, width=1)
```

- [ ] **Step 6: Update the existing tests that call these with a frame**

Every existing assertion keeps its expected pixels. Only the construction changes:

```python
# before
frame = render_play_hud(transparent_canvas(), inventory_available=True)
assert frame[PlayLayout.INVENTORY.centery, PlayLayout.INVENTORY.centerx, 3] > 0

# after
painter = UIPainter()
render_play_hud(painter, inventory_available=True)
frame = painter.to_frame()
assert frame[PlayLayout.INVENTORY.centery, PlayLayout.INVENTORY.centerx, 3] > 0
```

Apply that shape to every test in `tests/test_ui_render.py` and `tests/test_ui_mouse.py` that calls one of the six presenters this task converts.

- [ ] **Step 7: Run the suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/ -q`
Expected: PASS. `shell.py` still calls these with a frame and will fail to import until Task 9 — if that breaks the run, convert `shell.py`'s five call sites in this task's Step 8 rather than leaving the tree red.

- [ ] **Step 8: Commit**

```bash
git add PyAitD/app/ui.py PyAitD/app/startup.py tests/
git commit -m "refactor: overlays and buttons paint on the UI painter"
```

---

### Task 5: The modal presenters — found, picture, inventory, game over

**Files:**
- Modify: `PyAitD/app/ui.py` (`render_found` ~775, `render_picture` ~791, `render_inventory` ~889, `render_game_over` ~974)
- Test: `tests/test_ui_render.py`, `tests/test_modal_results.py`

**Interfaces:**
- Consumes: `UIPainter` (Tasks 1-3), `_button` (Task 4).
- Produces: `render_found(painter, effect, presenter, assets, found_name)`, `render_picture(painter, effect, assets, resolver=None)`, `render_inventory(painter, presenter, assets, scene_frame, object_names, action_names)`, `render_game_over(painter, scene_frame, ready)` — all painting in place, returning `None`.

- [ ] **Step 1: Write the failing test**

```python
def test_found_modal_fills_its_own_background_at_any_scale():
    from PyAitD.app.ui import UIPainter, render_found
    for scale in (1, 4):
        painter = UIPainter(scale)
        render_found(painter, _found_effect(), _found_presenter(), _assets(), "Lamp")
        frame = painter.to_frame()
        assert frame[:, :, 3].min() == 255, "the found modal owns the whole frame"
        assert tuple(frame[2, 2][:3]) == (17, 11, 9), "its fill colour"
```

- [ ] **Step 2: Run to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_ui_render.py -q -k found_modal`
Expected: FAIL — `render_found` takes `effect` first and returns a frame.

- [ ] **Step 3: Convert the four presenters**

```python
def render_found(painter, effect, presenter, assets, found_name):
    painter.rect((17, 11, 9), pygame.Rect(0, 0, 320, 200))
    painter.text(assets.system_text(20), 20, (240, 220, 175), center=(160, 34))
    painter.text(found_name, 18, (255, 255, 255), center=(160, 78))
    choice = presenter.hover if presenter.hover is not None else presenter.choice
    _button(painter, ModalLayout.FOUND_LEAVE, assets.system_text(21), choice is FoundResult.LEAVE)
    _button(painter, ModalLayout.FOUND_TAKE, assets.system_text(22), choice is FoundResult.TAKE)
    if effect.forced_refuse:
        painter.text(assets.system_text(10), 16, (255, 192, 128), center=(160, 126))


def render_picture(painter, effect, assets, resolver=None):
    resolver = _resolver_or_originals(assets, resolver)
    painter.blit(screen_surface(resolver, effect.resource_index, painter.size), (0, 0))


def render_inventory(painter, presenter, assets, scene_frame, object_names, action_names):
    dimmed = (scene_frame.astype("f4") * 0.45).astype(np.uint8)
    painter.sprite(dimmed, (0, 0))
    rows = action_names if presenter.choosing_action else object_names
    cursor = presenter.action_cursor if presenter.choosing_action else presenter.object_cursor
    selection = presenter.hover if presenter.hover is not None else cursor
    start = visible_start(cursor, len(rows))
    title_id = 200 if presenter.choosing_action else 20
    painter.text(assets.system_text(title_id), 20, (255, 238, 198), center=(160, 16))
    for visible, rect in enumerate(ModalLayout.INVENTORY_ROWS):
        index = start + visible
        if index >= len(rows):
            break
        _button(painter, rect, rows[index], selected=index == selection)


def render_game_over(painter, scene_frame, ready):
    # LM_GAME_OVER's wall-clock wait (life.cpp:2438-2450) freezes the last PLAY
    # frame -- locked, this paints nothing at all, so the caller's canvas
    # reaches present() untouched and the modal holds the moment of death still.
    if not ready:
        return
    painter.sprite(scene_frame, (0, 0))
    painter.shade((0, 0, 0, 170))
    painter.text("Game Over", 40, (255, 238, 198), center=(160, 82))
    painter.text("Click to restart", 18, (255, 255, 255), center=(160, 126))
```

`render_inventory` and `render_game_over` take the 320x200 scene thumbnail through `painter.sprite`, so it nearest-upscales by an integer. The scene behind those two modals therefore stays 320x200-blocky under sharp UI — the spec calls that out as deliberate and out of scope to change.

- [ ] **Step 4: Update the existing tests for these four**

Keep every expected pixel; change construction to `painter = UIPainter()`, call, assert on `painter.to_frame()`.

- [ ] **Step 5: Run the suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add PyAitD/app/ui.py tests/
git commit -m "refactor: found, picture, inventory and game over paint on the painter"
```

---

### Task 6: The modal presenters — reading, system menu, key picker

**Files:**
- Modify: `PyAitD/app/ui.py` (`reading_pages` ~852, `render_reading` ~861, `render_system_menu` ~940, `_render_key_picker` ~966)
- Test: `tests/test_ui_render.py`

**Interfaces:**
- Consumes: `UIPainter`, `_button`, `layout_book`, `screen_surface(…, size)`, `draw_big_cadre` (still surface-based until Task 7).
- Produces: `reading_pages(painter, effect, assets)`, `render_reading(painter, effect, presenter, assets, resolver=None)`, `render_system_menu(painter, presenter, settings, assets)`, `_render_key_picker(painter, presenter)`.

- [ ] **Step 1: Write the failing test**

```python
def test_reading_page_text_is_sharper_at_scale_four():
    from PyAitD.app.ui import UIPainter, render_reading
    ink = []
    for scale in (1, 4):
        painter = UIPainter(scale)
        render_reading(painter, _reading_effect(), _reading_presenter(), _assets())
        frame = painter.to_frame()
        dark = ((frame[:, :, 0] < 80) & (frame[:, :, 1] < 80)).sum()
        ink.append(dark / (scale * scale))
    assert ink[1] > ink[0], (
        "4x the canvas must carry more than 4x the glyph pixels, or the text "
        "was upscaled rather than re-rendered"
    )
```

- [ ] **Step 2: Run to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_ui_render.py -q -k reading_page_text`
Expected: FAIL — `render_reading` takes `effect` first.

- [ ] **Step 3: Convert reading**

```python
def reading_pages(painter, effect, assets):
    pages = assets.book_pages.get(effect.text_index)
    if pages is None:
        pages = layout_book(assets.book_tokens(effect.text_index), painter, 16, 190, 8)
        assets.book_pages[effect.text_index] = pages
    return pages


def render_reading(painter, effect, presenter, assets, resolver=None):
    resolver = _resolver_or_originals(assets, resolver)
    painter.blit(
        screen_surface(resolver, {0: 6, 1: 7, 2: 8}[effect.kind], painter.size), (0, 0),
    )
    pages = reading_pages(painter, effect, assets)
    y = 20
    for text, centered in pages[presenter.page]:
        width = painter.text_size(text, 16)[0]
        x = 160 - width // 2 if centered else 60
        painter.text(text, 16, (43, 31, 22), topleft=(x, y))
        y += 16
    hover = presenter.hover
    _button(painter, ModalLayout.READING_PREV, "Previous",
            hover == ReadingResult(False, -1) if hover is not None else presenter.page > 0)
    _button(painter, ModalLayout.READING_CLOSE, "Close",
            hover == ReadingResult(True) if hover is not None else True)
    _button(painter, ModalLayout.READING_NEXT, "Next",
            hover == ReadingResult(False, 1) if hover is not None else presenter.page + 1 < len(pages))
```

`screen_surface(..., painter.size)` is why the reading background is sharp too: the page image is fetched at canvas size instead of being upscaled from a 320x200 copy.

- [ ] **Step 4: Convert the system menu and key picker**

```python
def render_system_menu(painter, presenter, settings, assets):
    draw_big_cadre(painter, assets.cadre_bank(), (160, 100), (320, 200))
    if presenter.page is SystemMenuPage.KEY_PICK:
        _render_key_picker(painter, presenter)
        return
    if presenter.page is SystemMenuPage.MAIN:
        labels = ["Return to Game", "Configuration", "Quit"]
    else:
        labels = [f"Sticky Action: {'On' if settings.sticky_action else 'Off'}"]
        for control in REMAPPABLE_CONTROLS:
            labels.append(f"{control.name}: {', '.join(settings.bindings[control.name])}")
        labels.append(f"Scale: {settings.render.scale}x")
        labels.append(f"Shading: {settings.render.shading.title()}")
        labels.append(f"Filter: {settings.render.background_filter.title()}")
        labels.append("Back to Menu")
    selection = presenter.hover if presenter.hover is not None else presenter.cursor
    button_size = 13 if presenter.page is SystemMenuPage.CONFIG else 18
    rows = zip(SystemMenuLayout.rows(presenter.page), labels, strict=True)
    for index, (rect, label) in enumerate(rows):
        _button(painter, rect, label, selected=index == selection, size=button_size)


def _render_key_picker(painter, presenter):
    painter.text(f"{presenter.capture}: press a key or click one", 14,
                 (250, 242, 216), midtop=(160, 4))
    labels = [PICKABLE_KEY_LABELS.get(name, name) for name in PICKABLE_KEYS] + ["Cancel"]
    for index, (rect, label) in enumerate(zip(SystemMenuLayout.KEY_PICK_ROWS, labels)):
        _button(painter, rect, label, selected=index == presenter.hover, size=12)
```

The system menu previously started from an **opaque** `pygame.Surface((320, 200))` whose default fill is black. `draw_big_cadre` covers the frame, but to keep scale-1 output byte-identical, paint the black ground first: `painter.rect((0, 0, 0), pygame.Rect(0, 0, 320, 200))` as the menu's first line.

- [ ] **Step 5: Update the existing tests for these presenters**

Same conversion as Task 5: build a painter, call, assert on `to_frame()`.

- [ ] **Step 6: Run the suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add PyAitD/app/ui.py tests/
git commit -m "refactor: reading and the system menu paint on the painter"
```

---

### Task 7: Character selection, the cadre, and the startup screens

**Files:**
- Modify: `PyAitD/app/ui.py` (`draw_big_cadre` ~689, `render_character_select` ~906), `PyAitD/app/startup.py` (`render_title` ~146, `render_startup_menu` ~170, `_credits_pages`)
- Test: `tests/test_ui_render.py`, `tests/test_main.py`

**Interfaces:**
- Consumes: everything from Tasks 1-6.
- Produces: `draw_big_cadre(painter, sprites, center, size)`, `render_character_select(painter, presenter, assets, resolver=None)`, `render_title(painter, presenter, assets, resolver, elapsed_ms, credits_entry)`, `render_startup_menu(painter, presenter, assets, *, continue_enabled)`.

- [ ] **Step 1: Write the failing test**

```python
def test_character_select_background_is_fetched_at_canvas_size(data_dir, profile):
    from PyAitD.app.ui import UIPainter, render_character_select
    game = init_game(data_dir, profile)
    resolver = AssetResolver(game.assets, None)
    painter = UIPainter(4)
    render_character_select(painter, _character_presenter(), game.assets, resolver)
    frame = painter.to_frame()
    assert frame.shape[:2] == (800, 1280)
    assert frame[:, :, 3].min() == 255, "the selector owns the whole frame"
```

- [ ] **Step 2: Run to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_ui_render.py -q -k character_select_background`
Expected: FAIL — `render_character_select` takes `presenter` first and returns a frame.

- [ ] **Step 3: Convert `draw_big_cadre` to compose logically, then scale once**

The cadre is 20px pixel-art tiles. Keep the tiling arithmetic exactly as it is, on a logical surface, and hand the result to the painter — that is the plan's pixel-art rule, and it keeps the FITD placement port untouched:

```python
def draw_big_cadre(painter, sprites, center, size):
    # FITD AffBigCadre placement (FitdLib/aitdBox.cpp:92-178). The tiling stays
    # on a logical 320x200 surface and is scaled once by the painter: the tiles
    # are pixel art, and an integer upscale of the assembled cadre is exactly
    # what an integer upscale of each tile would produce, with none of the
    # seams that scaling each tile separately would introduce.
    canvas = pygame.Surface((320, 200), flags=pygame.SRCALPHA)
    _tile_big_cadre(canvas, sprites, center, size)
    painter.sprite(canvas, (0, 0))
```

Rename the existing body to `_tile_big_cadre(surface, sprites, center, size)` with no other change.

- [ ] **Step 4: Convert `render_character_select`**

```python
def render_character_select(painter, presenter, assets, resolver=None):
    # FITD character select: resource 10 background, cadre around the hovered
    # portrait (left choice 0 = Emily hero 1, right choice 1 = Carnby hero 0);
    # STORY copies the opposite half of resource 14 plus book text 20/21.
    resolver = _resolver_or_originals(assets, resolver)
    background = screen_surface(resolver, 10, painter.size)
    painter.blit(background, (0, 0))
    choice = (presenter.hover if presenter.hover is not None
              and presenter.phase is CharacterPhase.PORTRAITS else presenter.choice)
    center = ((80, 100), (240, 100))[choice]
    draw_big_cadre(painter, assets.cadre_bank(), center, (160, 200))
    portrait = CharacterLayout.PORTRAITS[choice]
    # the portrait is re-copied from the clean background, over the cadre
    painter.blit(background, portrait.topleft, area=portrait)
    if presenter.phase is CharacterPhase.PORTRAITS:
        return
    intro = screen_surface(resolver, 14, painter.size)
    if presenter.choice == 0:
        painter.blit(intro, (160, 0), area=pygame.Rect(160, 0, 160, 200))
        entry, text_x = 21, 165
    else:
        painter.blit(intro, (0, 0), area=pygame.Rect(0, 0, 160, 200))
        entry, text_x = 20, 5
    page = layout_book(assets.book_tokens(entry), painter, 15, 150, 12)[0]
    y = 5
    for text, centered in page:
        width = painter.text_size(text, 15)[0]
        x = text_x + (150 - width) // 2 if centered else text_x
        painter.text(text, 15, (43, 31, 22), topleft=(x, y))
        y += 15
```

The `base = surface.copy()` of the old code is gone: `background` is the shared cached surface and is never drawn on, so it *is* the clean copy. Do not draw on it.

- [ ] **Step 5: Convert the startup screens**

```python
def render_title(painter, presenter, assets, resolver, elapsed_ms, credits_entry):
    if presenter.phase is TitlePhase.TITLE:
        painter.blit(screen_surface(resolver, 13, painter.size), (0, 0))  # AITD1_TITRE
        alpha = min(255, 255 * max(0, elapsed_ms) // TITLE_FADE_MS)
        if alpha < 255:
            painter.shade((0, 0, 0, 255 - alpha))
        return
    painter.blit(screen_surface(resolver, 7, painter.size), (0, 0))       # AITD1_LIVRE
    pages = _credits_pages(painter, assets, credits_entry)
    page = pages[min(presenter.page, len(pages) - 1)]
    y = 2
    for text, centered in page:
        width = painter.text_size(text, 15)[0]
        x = 48 + (212 - width) // 2 if centered else 48
        painter.text(text, 15, (43, 31, 22), topleft=(x, y))
        y += 15


def render_startup_menu(painter, presenter, assets, *, continue_enabled):
    painter.rect((0, 0, 0), pygame.Rect(0, 0, 320, 200))
    center, size = StartupLayout.CADRE
    draw_big_cadre(painter, assets.cadre_bank(), center, size)
    selection = presenter.hover if presenter.hover is not None else presenter.cursor
    for index, (rect, text_id) in enumerate(zip(StartupLayout.ROWS, MENU_TEXT_IDS)):
        label = assets.system_text(text_id)
        if index == StartupRow.CONTINUE.value and not continue_enabled:
            _disabled_button(painter, rect, label, size=14)
        else:
            _button(painter, rect, label, selected=index == selection, size=14)
```

- [ ] **Step 6: Update the existing tests, run the suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add PyAitD/app/ui.py PyAitD/app/startup.py tests/
git commit -m "refactor: character select and startup screens paint on the painter"
```

---

### Task 8: `Renderer.ui_scale()` and a UI texture that follows the canvas

**Files:**
- Modify: `PyAitD/render/render.py` (`Renderer.__init__` ~97, `present` ~178)
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: nothing from earlier tasks — this is independent of `ui.py` and could be done first.
- Produces: `Renderer.ui_scale() -> float`.

- [ ] **Step 1: Write the failing test**

```python
def test_ui_scale_matches_the_inverse_of_window_to_logical(monkeypatch):
    renderer = _headless_renderer()
    monkeypatch.setattr(pygame.display, "get_window_size", lambda: (1280, 800))
    assert renderer.ui_scale() == 4.0
    # the same expression window_to_logical inverts
    assert renderer.window_to_logical((640, 400)) == (160, 100)


def test_present_accepts_canvases_of_different_sizes_in_succession():
    renderer = _headless_renderer()
    renderer.compose_scene(_frame())
    renderer.present(np.zeros((200, 320, 4), np.uint8))
    renderer.present(np.zeros((800, 1280, 4), np.uint8))   # must not raise
    assert renderer._ui_tex.size == (1280, 800)


def test_the_software_fallback_keeps_the_ui_at_scale_one(monkeypatch):
    # That path composites the UI against a 320x200 scene thumbnail, so a
    # larger canvas would have nothing sharper to sit on.
    renderer = _headless_renderer()
    monkeypatch.setattr(pygame.display, "get_window_size", lambda: (1280, 800))
    renderer.backend = SoftwareBackend(renderer.options)
    assert renderer.ui_scale() == 1.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render.py -q -k "ui_scale or different_sizes"`
Expected: FAIL — `Renderer` has no `ui_scale`, and `present` writes a 320x200 texture.

- [ ] **Step 3: Add `ui_scale` and size the texture from the canvas**

In `PyAitD/render/render.py`:

```python
    def ui_scale(self):
        """The pixel scale the UI layer should paint at.

        The same expression window_to_logical inverts, so what is drawn and
        what is picked stay consistent by construction rather than by two
        constants happening to agree. The software fallback stays at 1: that
        path composites the UI against a 320x200 scene thumbnail, and a
        larger canvas would have nothing sharper to sit on.
        """
        if not isinstance(self.backend, GLBackend):
            return 1.0
        win_w, win_h = pygame.display.get_window_size()
        return min(win_w / IMG_W, win_h / IMG_H)

    def _ui_texture_for(self, canvas):
        size = (canvas.shape[1], canvas.shape[0])
        if self._ui_tex.size != size:
            self._ui_tex.release()
            self._ui_tex = self._ctx.texture(size, 4)
            self._ui_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        return self._ui_tex
```

and in `present`, replace `self._ui_tex.write(...)` with:

```python
            self._ui_texture_for(ui_canvas).write(_rgba(ui_canvas).tobytes())
```

The quad is unchanged: `fit_quad` works from the aspect ratio, which the canvas preserves.

- [ ] **Step 4: Run the tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_render.py -q`
Expected: PASS. Tests needing GL skip themselves through the existing `gl_ctx` fixture if no context is available.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/render/render.py tests/test_render.py
git commit -m "feat: the UI texture follows the canvas it is handed"
```

---

### Task 9: Wire the loop, and the docs

**Files:**
- Modify: `PyAitD/app/shell.py` (`render_active_mode` ~994, the present sequence ~1371-1393), `README.md`, `AGENTS.md`, `CONTEXT.md`
- Test: `tests/test_play_loop.py`

**Interfaces:**
- Consumes: every presenter signature from Tasks 4-7, `Renderer.ui_scale()` from Task 8.
- Produces: `render_active_mode(game, session, renderer, resolver=None) -> UIPainter`.

- [ ] **Step 1: Write the failing test**

```python
def test_the_loop_paints_one_canvas_at_the_renderer_scale(data_dir, profile, monkeypatch):
    import PyAitD.app.shell as main
    game = init_game(data_dir, profile)
    renderer = _fake_renderer(ui_scale=4.0)
    painter = main.render_active_mode(game, ModalSession(), renderer)
    assert painter.scale == 4.0
    assert painter.to_frame().shape[:2] == (800, 1280)
```

- [ ] **Step 2: Run to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_play_loop.py -q -k one_canvas`
Expected: FAIL — `render_active_mode` returns a numpy array.

- [ ] **Step 3: Convert `render_active_mode`**

Create the painter once at the top and pass it to whichever branch runs; every branch paints and returns the painter:

```python
    painter = UIPainter(renderer.ui_scale())
    effect = game.active_modal
    if effect is None:
        overlay_messages(painter, game.messages, game.assets)
        return painter
    if isinstance(effect, CutsceneFinished):
        # the last PLAY frame stays composed underneath, exactly like
        # render_game_over before its accessibility wait elapses
        return painter
    session.reset_for(effect)
    if isinstance(effect, OpenSystemMenu):
        render_system_menu(painter, session.system_menu, session.settings, game.assets)
        return painter
```

Every remaining branch keeps its order and its arguments, with `painter` inserted first and `return painter` after the call:

```python
    if isinstance(effect, ChooseCharacter):
        # the selector owns the whole frame; the staged PLAY scene is never shown
        render_character_select(painter, session.character, game.assets, resolver)
        return painter
    if isinstance(effect, ShowTitle):
        from PyAitD.app.startup import render_title
        render_title(painter, session.title, game.assets,
                     resolver or AssetResolver(game.assets, None),
                     session.elapsed_ms, _credits_entry(game))
        return painter
    if isinstance(effect, OpenStartupMenu):
        from PyAitD.app.startup import render_startup_menu
        render_startup_menu(painter, session.startup, game.assets,
                            continue_enabled=continue_available(session))
        return painter
    if isinstance(effect, ShowFound):
        world = game.world_objects[effect.object_idx]
        render_found(painter, effect, session.found, game.assets,
                     game.assets.system_text(world.found_name))
        return painter
    if isinstance(effect, OpenInventory):
        object_ids, action_ids = _inventory_view(game, session)
        render_inventory(
            painter, session.inventory, game.assets, renderer.scene_thumbnail(),
            tuple(game.assets.system_text(game.world_objects[i].found_name) for i in object_ids),
            tuple(game.assets.system_text(i) for i in action_ids),
        )
        return painter
    if isinstance(effect, ReadText):
        render_reading(painter, effect, session.reading, game.assets, resolver)
        return painter
    if isinstance(effect, ShowPicture):
        render_picture(painter, effect, game.assets, resolver)
        return painter
    if isinstance(effect, GameOver):
        render_game_over(painter, renderer.scene_thumbnail(),
                         _game_over_ready(session, effect))
        return painter
    raise RuntimeError(f"unrenderable modal {type(effect).__name__}")
```

Replace the three `transparent_canvas()` calls in this function; import `UIPainter` alongside the presenters.

- [ ] **Step 4: Convert the present sequence**

```python
        painter = render_active_mode(game, session, renderer, resolver)
        render_hit_feedback(
            painter, _hit_feedback_rects(game, draw_list, hit_feedback_deadlines),
        )
        available = inventory_hud_available(game) and not session.cutscene
        render_play_hud(painter, inventory_available=available)
        # the settings notice is mode-independent: after the HUD and before
        # the software cursor, so its Dismiss target is visually topmost
        render_settings_notice(painter, session.settings_error)
        software_cursor = (game.mode is GameMode.PLAY
                           and game.active_modal is None
                           and game.input_mode is InputMode.MOUSE
                           and not session.cutscene)
        pygame.mouse.set_visible(not software_cursor)
        if software_cursor:
            kind = _play_cursor_kind(game, floor, hover, draw_list, input_buffer)
            render_cursor(painter, hover, kind)
        renderer.present(painter.to_frame())
```

- [ ] **Step 5: Run the whole suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 6: Update the docs**

`README.md`, in the graphics paragraph, after the sentence about `--render-scale`:

> The UI layer — character selection, the inventory, menus, messages and the cursor — is drawn at the window's own resolution rather than at 320x200, so its text stays sharp at any window size. It is authored in 320x200 coordinates regardless, which is what keeps mouse targets and what you see in step.

`AGENTS.md`, in the rendering section:

> The UI layer is painted through `app.ui.UIPainter`, which owns a surface at `(320*s, 200*s)` and scales logical coordinates on every call. Presenters author in logical 320x200 and never build their own surface; `s` comes from `Renderer.ui_scale()`, the same expression `window_to_logical` inverts. Pixel art (cadre tiles, sprites, scene thumbnails) goes through `painter.sprite`, which upscales by an integer; text and shapes are drawn at scale. Hit-testing stays logical — never scale a `hit_test_*` input.

`CONTEXT.md`, in the app section:

> - `app.ui.UIPainter` is the UI canvas: a surface at `(320*s, 200*s)` plus the scale, and the only object that knows `s`. `shell.render_active_mode` builds one per frame from `Renderer.ui_scale()` and every presenter and overlay paints on it; the loop calls `to_frame()` once, at `present()`. `screen_surface(resolver, entry, size)` fetches ITD_RESS screens at the canvas size, so an override keeps the resolution it came with.

- [ ] **Step 7: Commit**

```bash
git add PyAitD/app/shell.py README.md AGENTS.md CONTEXT.md tests/
git commit -m "feat: draw the UI layer at the window's resolution"
```

---

## Manual verification

Automated tests cannot judge sharpness. After Task 9:

```bash
make run
```

Check, at the default 1280x800 window: the character selector's names and story text, the inventory rows, and the system menu are crisp rather than blocky; the portraits, cadre border and background art still look like pixel art rather than smeared; the cursor still lands exactly where you click; resizing the window keeps text sharp and does not shift any button under the pointer.
