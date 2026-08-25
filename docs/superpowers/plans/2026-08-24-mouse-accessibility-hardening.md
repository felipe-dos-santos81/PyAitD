# Mouse Accessibility Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every currently implemented UI and gameplay operation forgiving, hover-previewable, touch-origin compatible, and safe across modal takeover, then record single-button windowed evidence for Emily and Carnby.

**Architecture:** Extend the existing `ui.py` layouts and hit tests with one shared effective-rectangle helper; keep visible rectangles unchanged. Add one idempotent PLAY-input takeover helper in `__main__.py` and call it at every PLAY-to-modal boundary before another tick. Preserve the current resolver, event pump, simulation boundaries, and pygame-free mouse registry.

**Tech Stack:** Python 3.12, pygame-ce 2.5.8, ModernGL, NumPy, pytest. Reuse pygame-ce mouse/focus events and `pygame.Rect`; add no dependency.

**Spec:** `docs/superpowers/specs/2026-08-24-overall-mouse-accessibility-design.md`

## Global Constraints

- This is milestone 1 only. Do not add persistence, audio, sequences, ending behavior, a router framework, or a separate touch-event path.
- `# SPDX-License-Identifier: GPL-2.0-only` remains the first line of every Python file.
- `playworld.py`, `life_ops.py`, `interaction.py`, and `effects.py` remain pygame-free. `ui.py` never mutates game/world/LIFE state. `__main__.py` remains the only event pump.
- Visible art rectangles stay byte-for-byte unchanged. Effective hit rectangles use two logical pixels of padding, a 12x12 logical minimum, frame clamp, and midpoint partitioning for adjacent UI controls.
- World target expansion preserves the existing frontmost `draw_list` winner and the resolver priority: notice -> inventory -> attack -> interact -> push -> walk -> blocked.
- `MOUSEBUTTONDOWN/UP` with `touch=True` follow the same path as physical mouse events. Do not handle `FINGERDOWN/FINGERUP`, which would duplicate SDL synthesized events.
- Press-and-hold is permitted only for pushing. No other route may require holding, dragging, double-clicking, timing, or a chord.
- Rendering tests use `SDL_VIDEODRIVER=dummy`; focused real-loop tests also use `SDL_AUDIODRIVER=dummy`.
- Every task follows red -> minimal implementation -> focused green -> `.venv/bin/pytest -q`. After non-trivial changes also run `make prove`.

## File Map

| File | Responsibility |
|---|---|
| `PyAitD/ui.py` | Effective hit geometry, pointer provenance/position, presenter hover, hit tests, drawing. |
| `PyAitD/__main__.py` | Atomic modal takeover, world hit padding, hover routing, event ordering. |
| `PyAitD/mouse_contract.py` | Explicit gestures, hover/touch decisions, exhaustive current-mode surface. |
| `tests/test_ui_input.py` | Physical/touch event parity and focus clearing. |
| `tests/test_ui_mouse.py` | Geometry and hover purity. |
| `tests/test_picking.py` | Expanded world-target precedence. |
| `tests/test_play_loop.py` | Same-pump modal takeover regression and touch parity. |
| `tests/test_mouse_only.py` | Contract and both-protagonist bounded journeys. |
| `Makefile` | Focused hardening proof target. |
| `docs/mouse-accessibility-hardening-proof.md` | Automated and windowed evidence. |
| `CONTEXT.md` | Landed ownership and release-gate status. |

---

### Task 1: Effective UI hit geometry

**Files:**
- Modify: `PyAitD/ui.py:341-375,658-743`
- Modify: `tests/test_ui_mouse.py`

**Interfaces:**
- Produces `effective_rects(rects, *, pad=2, minimum=12, bounds=pygame.Rect(0, 0, 320, 200)) -> tuple[pygame.Rect, ...]`.
- Each layout exposes visible rectangles unchanged and `hit_rows(...)` computed from them.
- All modal/shell hit tests consume effective rectangles; disabled reading buttons remain non-targets.

- [ ] **Step 1: Add failing geometry tests**

Add tests that pin: `PlayLayout.INVENTORY == Rect(4,4,28,20)` while its hit rect is `(2,2,32,24)`; a synthetic 4x6 target expands to 12x12 and clamps at `(0,0)`; adjacent targets split their gap at the midpoint and never overlap; `right`/`bottom` edges remain exclusive.

```python
def test_effective_rects_expand_clamp_and_partition_without_changing_art():
    visible = (pygame.Rect(0, 0, 4, 6), pygame.Rect(16, 0, 4, 6))
    hit = effective_rects(visible)
    assert visible == (pygame.Rect(0, 0, 4, 6), pygame.Rect(16, 0, 4, 6))
    assert all(rect.w >= 12 and rect.h >= 12 for rect in hit)
    assert hit[0].right <= hit[1].left
    assert hit[0].collidepoint(hit[0].right, hit[0].centery) is False
```

- [ ] **Step 2: Run the focused test and verify import failure**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_mouse.py -q`

Expected: collection fails because `effective_rects` and layout hit rows do not exist.

- [ ] **Step 3: Implement the helper and migrate hit tests**

Implement expansion from rectangle centers, clamp to `bounds`, then trim any overlap at `floor((left.right + right.left) / 2)` on the relevant axis. Add `PlayLayout.INVENTORY_HIT`; `SystemMenuLayout.hit_rows`; effective modal/notice rows; and make every `hit_test_*` use them. Keep `CharacterLayout.STORY` and whole-frame picture/game-over targets unchanged.

- [ ] **Step 4: Run focused and full tests**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_mouse.py tests/test_ui_render.py -q && .venv/bin/pytest -q`

Expected: all pass; render goldens and visible rectangles are unchanged.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/ui.py tests/test_ui_mouse.py
git commit -m "feat: add forgiving pointer hit geometry"
```

---

### Task 2: Presenter-only hover previews

**Files:**
- Modify: `PyAitD/ui.py:149-176,241-270,487-634,703-733`
- Modify: `PyAitD/__main__.py:459-590,694-794`
- Modify: `tests/test_ui_mouse.py`
- Modify: `tests/test_ui_render.py`
- Modify: `tests/test_runtime_modes.py`

**Interfaces:**
- Adds `hover: object | None` to `FoundPresenter`, `InventoryPresenter`, `ReadingPresenter`, `CharacterSelectPresenter`, and `SystemMenuPresenter`.
- Produces `route_hover(game, session, logical_pos) -> None`; it may set presenter preview only.
- Renderers select `presenter.hover` when non-`None`, otherwise the keyboard cursor/choice.

- [ ] **Step 1: Write failing hover purity tests**

Snapshot `vars`, `cvars`, actors, world objects, inventory, active modal, and LIFE stack; hover every enabled target and outside the frame; assert only the owning presenter's `hover` changes and outside clears it. Assert keyboard cursor stays unchanged.

- [ ] **Step 2: Verify the tests fail**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_mouse.py tests/test_runtime_modes.py -q`

Expected: `route_hover` is missing and render selection does not follow hover.

- [ ] **Step 3: Implement preview routing and rendering**

Use the same `hit_test_*` functions as activation. In the event pump, translate every `MOUSEMOTION` once, store `hover`, and call `route_hover` only for modal/shell modes. A mouse-down must work without prior motion. Clear preview on `None`, focus loss, modal replacement, and session replacement.

- [ ] **Step 4: Run focused and full tests**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_mouse.py tests/test_ui_render.py tests/test_runtime_modes.py -q && .venv/bin/pytest -q`

- [ ] **Step 5: Commit**

```bash
git add PyAitD/ui.py PyAitD/__main__.py tests/test_ui_mouse.py tests/test_ui_render.py tests/test_runtime_modes.py
git commit -m "feat: preview mouse targets on hover"
```

---

### Task 3: Physical and touch-origin mouse parity

**Files:**
- Modify: `PyAitD/ui.py:24-141`
- Modify: `PyAitD/__main__.py:694-723`
- Modify: `tests/test_ui_input.py`
- Modify: `tests/test_play_loop.py`

**Interfaces:**
- Adds `pointer_touch: bool = False` and `pointer_pos: tuple[int, int] | None = None` to `InputBuffer`.
- `event_to_input` stores `bool(getattr(event, "touch", False))` as provenance only; down/up semantics are identical.
- Window-to-logical conversion remains owned by `run` and happens once per pointer event.

- [ ] **Step 1: Add paired event-script tests**

Parameterize mouse down/up events with `touch=False` and `touch=True`; assert identical `pointer_held`, command routing, modal result, and cancellation, with only `pointer_touch` differing while held. Assert focus loss clears both.

- [ ] **Step 2: Observe failure**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_ui_input.py tests/test_play_loop.py -q`

- [ ] **Step 3: Implement provenance without a second router**

Set provenance/position on primary down and motion, clear provenance/position on up/focus loss/reset, and keep the existing single mouse-down route. Do not branch behavior on `touch` and do not subscribe to `FINGER*`.

- [ ] **Step 4: Verify**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_ui_input.py tests/test_play_loop.py -q && .venv/bin/pytest -q`

- [ ] **Step 5: Commit**

```bash
git add PyAitD/ui.py PyAitD/__main__.py tests/test_ui_input.py tests/test_play_loop.py
git commit -m "test: prove touch-origin mouse parity"
```

---

### Task 4: Expanded world hit targets with stable precedence

**Files:**
- Modify: `PyAitD/__main__.py:143-239`
- Modify: `PyAitD/picking.py`
- Modify: `tests/test_picking.py`
- Modify: `tests/test_play_loop.py`

**Interfaces:**
- Produces `expand_actor_targets(targets, *, pad=2, minimum=12) -> list[(actor_idx, pygame.Rect)]` in `__main__.py`; keep pygame out of `picking.py` by passing rectangle-like boxes into existing `pick_actor`.
- Original visible-bound hits are resolved first. Only if none match are expanded bounds considered, in existing frontmost `draw_list` order.

- [ ] **Step 1: Add failing precedence tests**

Cover a tiny actor, overlap between two expanded actors, and a point inside actor A's original box but actor B's expanded box. Pin A for the original-bound case and the current topmost ordering for expansion-only overlap. Pin resolver priority over floor walking.

- [ ] **Step 2: Observe failure**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_picking.py tests/test_play_loop.py -q`

- [ ] **Step 3: Implement two-pass actor picking**

Do not alter actor rendering bounds or `pick_floor_any_room`. Run `pick_actor` once with original targets and once with expanded targets. Preserve the current blocked-combat and held-push rules.

- [ ] **Step 4: Verify**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_picking.py tests/test_play_loop.py tests/test_mouse_only.py -q && make prove-mouse-only`

- [ ] **Step 5: Commit**

```bash
git add PyAitD/__main__.py PyAitD/picking.py tests/test_picking.py tests/test_play_loop.py
git commit -m "feat: enlarge world pointer targets safely"
```

---

### Task 5: Atomic PLAY-to-modal takeover

**Files:**
- Modify: `PyAitD/__main__.py:371-405,670-776`
- Modify: `tests/test_play_loop.py`
- Modify: `tests/test_runtime_modes.py`
- Modify: `tests/test_mouse_only.py`

**Interfaces:**
- Produces `_take_over_play_input(game, session, input_buffer) -> None`.
- The helper calls `reset_input`, `cancel_nav_intent`, clears hover/queued decisions through their owners, and is idempotent.
- Every transition whose pre-state is PLAY invokes it before modal routing, rendering, load/replacement, or a subsequent `play_tick`.

- [ ] **Step 1: Add the exact held-push inventory regression**

Create both approach and engaged `NavIntent(requires_hold=True)` cases. Feed inventory-HUD mouse down while the pointer remains held; patch `play_tick` to fail if it observes navigation/local action after the modal opens. Also cover keyboard system menu, found contact during `play_tick`, game over, and repeated takeover.

```python
def assert_modal_tick_is_clean(game, _floor, buffer):
    assert game.nav_intent is None
    assert (game.local_joyd, game.local_click, game.action) == (0, 0, 0)
    assert not buffer.pointer_held
```

- [ ] **Step 2: Confirm the known regression fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_play_loop.py -k 'modal_takeover or held_push_inventory' -q`

Expected: the inventory route opens before the existing end-of-frame cleanup and stale held state is observable.

- [ ] **Step 3: Implement one takeover seam**

Call the helper immediately when `route_command` or `route_play_click` opens a modal. Retain the post-tick `was_play` check for simulation-raised modals, but delegate it to the same helper. Replacement branches create fresh buffers and also cancel the old game before tuple replacement. Ensure no modal reset happens twice.

- [ ] **Step 4: Verify all modal paths**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_play_loop.py tests/test_runtime_modes.py tests/test_mouse_only.py -q && make prove-mouse-only && make prove-shell`

- [ ] **Step 5: Commit**

```bash
git add PyAitD/__main__.py tests/test_play_loop.py tests/test_runtime_modes.py tests/test_mouse_only.py
git commit -m "fix: make modal takeover cancel pointer intent atomically"
```

---

### Task 6: Exhaustive accessibility contract and focused gate

**Files:**
- Modify: `PyAitD/mouse_contract.py`
- Modify: `tests/test_mouse_only.py`
- Modify: `Makefile`

**Interfaces:**
- Adds explicit reviewed decisions for `hover_preview`, `touch_origin`, and the sole `left_hold` capability.
- Adds `prove-mouse-accessibility` using dummy video/audio and the focused input, UI, loop, shell, and mouse-only tests.

- [ ] **Step 1: Add failing registry tests**

Assert `set(MODE_MOUSE_CAPABILITIES) == set(GameMode)`, every capability has one route, every non-mouse command has a reviewed decision, only `HOLD_PUSH_OBJECT` uses `left_hold`, and no route uses double-click/drag/chord. Assert provenance and hover decisions exist.

- [ ] **Step 2: Run and observe missing declarations**

Run: `.venv/bin/pytest tests/test_mouse_only.py -k contract -q`

- [ ] **Step 3: Extend declarations and Makefile**

Keep `mouse_contract.py` pygame-free. Add the focused target without replacing `prove-mouse-only` or `prove-shell`.

- [ ] **Step 4: Verify focused and full gates**

Run: `make prove-mouse-accessibility && .venv/bin/pytest -q && make prove`

- [ ] **Step 5: Commit**

```bash
git add PyAitD/mouse_contract.py tests/test_mouse_only.py Makefile
git commit -m "test: gate current mouse accessibility surface"
```

---

### Task 7: Both-protagonist windowed evidence and handoff

**Files:**
- Create: `docs/mouse-accessibility-hardening-proof.md`
- Modify: `CONTEXT.md`

**Interfaces:**
- Evidence records commit, data identity, macOS/Apple Silicon environment, Emily and Carnby route checkpoints, one-button device/on-screen-keyboard setup, failures, fixes, and successful rerun.

- [ ] **Step 1: Run both bounded automated journeys**

Run: `make prove-mouse-accessibility && make prove-mouse-only && make prove-shell`

- [ ] **Step 2: Run the real windowed walkthrough twice**

Run `make run`. For Emily, then Carnby: select portrait/story, walk, interact, take/leave, inventory object/action, reading previous/next/close, system-menu/config navigation, combat targeting, held pushing, focus loss/recovery, game over/restart, and quit. Use only the primary button for decisions; pushing is the only hold.

- [ ] **Step 3: Record evidence honestly**

Do not mark the milestone complete if either pass fails. Record the failed checkpoint, fix it in a new TDD commit, rerun the focused/full gates, then rerun both windowed passes.

- [ ] **Step 4: Update architecture status and final gate**

Run: `.venv/bin/pytest -q && make prove`

- [ ] **Step 5: Commit**

```bash
git add docs/mouse-accessibility-hardening-proof.md CONTEXT.md
git commit -m "docs: record mouse accessibility hardening proof"
```

## Milestone Acceptance

- [ ] Known modal-entry held-push regression is covered by a real-loop test and fixed before the next PLAY tick.
- [ ] Physical and `touch=True` scripts have identical semantic results.
- [ ] Effective UI/world targets meet the locked geometry and precedence rules without changing art.
- [ ] Hover is optional, uses activation geometry, and cannot mutate game state.
- [ ] `make prove-mouse-accessibility`, `make prove-mouse-only`, `make prove-shell`, `.venv/bin/pytest -q`, and `make prove` pass.
- [ ] Windowed single-button evidence passes for Emily and Carnby.
