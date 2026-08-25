# Native Mouse Melee Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one enemy click perform object 38's native melee strike without implicitly choosing Throw.

**Architecture:** Store a bounded target latch in the existing application-owned `InputBuffer`. The event route validates and faces through `attack_in_hand`; the pygame-free fixed-tick input snapshot publishes FITD's ordinary forward/action fields until the melee animation completes.

**Tech Stack:** Python 3.12, pygame-ce, NumPy, pytest, original AITD1 data, FITD C++ reference.

**Spec:** `docs/superpowers/specs/2026-08-25-native-mouse-melee-design.md`

## Global Constraints

- Minimal blast radius: change the existing resolver, input buffer, and fixed-tick input seam only.
- Dependencies remain pygame-ce, ModernGL, NumPy, and pytest; add nothing.
- `playworld.py` and `interaction.py` remain pygame-free; `ui.py` never mutates game state.
- Explicit inventory Throw and FITD throw placement remain unchanged.
- Use strict RED-GREEN TDD and original-data evidence.
- Run `make prove-mouse-only` after pointer, animation, or modal behavior changes.

---

### Task 1: Route one click through native combat input

**Files:**
- Modify: `PyAitD/ui.py:25-84`
- Modify: `PyAitD/__main__.py:262-300`
- Modify: `PyAitD/interaction.py:231-241,480-506`
- Modify: `PyAitD/playworld.py:27-42,224-279`
- Test: `tests/test_interaction.py`
- Test: `tests/test_play_loop.py`
- Test: `tests/test_mouse_only.py`

**Interfaces:**
- Consumes: `attack_in_hand(game, target_actor_idx) -> bool`, `InputBuffer`, `is_combat_target`, `inventory_items`, and fixed-tick `apply_play_input`.
- Produces: `InputBuffer.mouse_attack_target: int | None`, `InputBuffer.mouse_attack_ticks: int`, and bounded native action publication.

- [x] **Step 1: Write the failing route and reset tests**

Add coverage that passes an `InputBuffer` to `route_play_click`, asserts the
enemy actor slot is latched, asserts `choose_inventory_action` is not called,
and asserts `reset_input` clears both attack fields.

```python
state = InputBuffer()
route_play_click(game, session, floor, point, draw_list, state)
assert state.mouse_attack_target == enemy_idx
assert state.mouse_attack_ticks == 0
reset_input(state)
assert (state.mouse_attack_target, state.mouse_attack_ticks) == (None, 0)
```

- [x] **Step 2: Run the route/reset tests and verify RED**

Run:

```bash
PYAITD_DATA='.../INDARK' SDL_VIDEODRIVER=dummy \
  .venv/bin/pytest -q \
  tests/test_interaction.py::test_attack_stops_faces_without_selecting_throw \
  tests/test_play_loop.py::test_attack_click_latches_native_mouse_combat \
  tests/test_ui_input.py::test_reset_input_clears_native_mouse_combat
```

Expected: FAIL because the fields do not exist and `attack_in_hand` still
chooses inventory action 32.

- [x] **Step 3: Write the failing fixed-tick and real-loop tests**

Pin the first attack tick to `(local_joyd, local_click, action) ==
(1, 1, 0x2000)`, continuation while `anim_action_type != 0`, completion when it
returns to zero, and the 100-tick safety stop. Replace the old mouse throw
journey with a one-click original-data saber journey that observes melee state
1/10/2, `enemy.hit_by == hero_idx`, force 4, and object 38 remaining held.

- [x] **Step 4: Run the fixed-tick/journey tests and verify RED**

Run:

```bash
PYAITD_DATA='.../INDARK' SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
  .venv/bin/pytest -q tests/test_playworld.py tests/test_mouse_only.py
```

Expected: FAIL because mouse mode currently clears action and the journey
still launches `THROW_OBJECT`.

- [x] **Step 5: Implement the minimal input-local latch**

Add the two `InputBuffer` fields and clear them in `reset_input`. Make
`attack_in_hand` validate inventory/idle state, cancel navigation, stop, and
face without calling `choose_inventory_action`. When it succeeds,
`route_play_click` stores the target in the supplied buffer.

At the start of `_apply_mouse_input`, before navigation handling, validate the
latched hero/target/in-hand object. On the first tick and while an animation
action remains active, publish forward plus action and increment the budget.
After at least one tick, clear on idle or at 100 ticks. Do not inspect pygame or
execute LIFE directly from the event route.

- [x] **Step 6: Run focused GREEN tests**

Run:

```bash
PYAITD_DATA='.../INDARK' SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
  .venv/bin/pytest -q tests/test_interaction.py tests/test_playworld.py \
  tests/test_play_loop.py tests/test_ui_input.py tests/test_mouse_only.py
```

Expected: PASS.

- [x] **Step 7: Run repository gates**

Run:

```bash
PYAITD_DATA='.../INDARK' SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy make prove-mouse-only
PYAITD_DATA='.../INDARK' SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
PYAITD_DATA='.../INDARK' SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy make prove
git diff --check
```

Expected: all pass; the existing skip/xfail remain unchanged.

- [x] **Step 8: Commit**

```bash
git add PyAitD/ui.py PyAitD/__main__.py PyAitD/interaction.py \
  PyAitD/playworld.py tests/test_interaction.py tests/test_playworld.py \
  tests/test_play_loop.py tests/test_ui_input.py tests/test_mouse_only.py \
  docs/superpowers/specs/2026-08-25-native-mouse-melee-design.md \
  docs/superpowers/plans/2026-08-25-native-mouse-melee.md
git commit -m "fix: use native melee for mouse attacks"
```

---

### Task 2: Record and verify the corrected windowed contract

**Files:**
- Modify: `docs/mouse-accessibility-hardening-proof.md`
- Modify: `CONTEXT.md`

**Interfaces:**
- Consumes: the Task 1 reviewed commit and green automated gates.
- Produces: honest human evidence for Emily and Carnby; no runtime interface.

- [ ] **Step 1: Run a scoped review of Task 1**

Review only the Task 1 commit against the native-melee spec. Reject any hidden
throw fallback, persistent `Game` combat latch, missing takeover reset, or
simulation/UI boundary violation.

- [ ] **Step 2: Run the windowed fixture for Emily and Carnby**

For each hero: open inventory, select object 38 `Use`, hover obj222, click once,
and observe a saber swing, white/red outline, force-4 hit, and no saber floor
drop. Also verify focus loss or opening inventory does not resume an old attack.

- [ ] **Step 3: Update proof and architecture docs only from observed evidence**

Record the tested commit, exact commands, automated counts, hero names, and
PASS/FAIL observations. Update `CONTEXT.md` to state that target click uses a
bounded input-local native combat latch while explicit Throw remains an
inventory action.

- [ ] **Step 4: Run documentation and final gates, then commit**

```bash
PYAITD_DATA='.../INDARK' SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy make prove-mouse-only
PYAITD_DATA='.../INDARK' SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest -q
PYAITD_DATA='.../INDARK' SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy make prove
git diff --check
git add docs/mouse-accessibility-hardening-proof.md CONTEXT.md
git commit -m "docs: record native mouse melee proof"
```

## Self-review

- Spec coverage: native input publication, one-click latch, completion,
  takeover cancellation, explicit Throw preservation, real-data force-4 hit,
  both-hero window evidence, and gates all map to Tasks 1-2.
- Placeholder scan: no deferred implementation or test placeholder remains.
- Type consistency: both tasks use `mouse_attack_target: int | None` and
  `mouse_attack_ticks: int`; no `Game` field or alternate combat router exists.
