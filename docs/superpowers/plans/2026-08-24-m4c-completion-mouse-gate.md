# M4c Completion and Mouse Release Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every behavior gap exercised by either protagonist's complete AITD1 path, connect the real ending, prove both paths with one-button pointer events, and smoke-test the windowed Apple Silicon application.

**Architecture:** Keep fixes in their existing owners: actor lifetime and restart checkpoints in `game.py`, animation/fall behavior in `actors.py`, LIFE semantics in `life_ops.py`/`eval_var.py`, and ending/application transitions in `effects.py`/`__main__.py`. Extend the existing per-opcode trace for reachability evidence. Full-journey playback is a test tool that injects raw pygame mouse events into the normal outer loop; it never edits `Game` state or bypasses navigation, collision, LIFE, inventory, combat, persistence, or media.

**Tech Stack:** Python 3.12, pygame-ce 2.5.8, ModernGL, NumPy, pytest, stdlib JSON/plist/path APIs, and the existing Makefile. Add no dependency.

**Spec:** `docs/superpowers/specs/2026-08-24-overall-mouse-accessibility-design.md` and `docs/superpowers/specs/2026-08-22-aitd1-build-conclusion-design.md`

## Global Constraints

- Depends on the hardening, M4a2, and M4b plans. All three focused gates must be green before M4c starts.
- FITD source and the two real-data traces decide behavior. `INFERRED` graph edges and old prose are navigation aids, never behavioral proof. Where FITD itself is unfinished, the plan labels the behavior as an assumption and checks the DOS original plus a pinned secondary GPL-2.0 engine implementation before coding.
- The release condition is path reachability: every opcode and `ponytail:` branch executed by either complete journey is implemented or documented as a verified AITD1 no-op with a FITD file:line anchor.
- `RND_FREQ`, `SHAKING`, `WATER`, `REP_SAMPLE`, and `STOP_SAMPLE` remain no-ops when the AITD1 branch consumes operands and does nothing. Remove “stub” labels and test operand consumption; do not port AITD2/AITD3 behavior.
- FITD leaves modes 1/4 of `InitSpecialObjet` and `AffSpecialObjet` unfinished. For this visual-only gap, use DOS capture as acceptance evidence and the GPL-2.0 [Re-Haunted](https://github.com/spacefarergames/AloneInTheDarkReHaunted) implementation at commit `3c230894e39a70f1822196bd2012eadc61755758` as a secondary implementation reference; copy no framework or asset.
- FITD also leaves `LM_END_SEQUENCE` as a TODO. The locked inference is that the AITD1 `ENDING` opcode hands off to the shipped `ENDSEQ.PAK`; verify the final DOS transition and both completed local journeys rather than claiming FITD code proves that binding.
- The death cinematic may change the displayed floor but must not replace the last playable restart checkpoint. The existing strict xfail must be removed, not weakened.
- Journey fixtures contain only event/timing/checkpoint data. After character selection they may not call `relocate_actor`, change variables, inject inventory, select LIFE scripts, skip required interactions, or use `--floor`, `--combat-venue`, or `--mouse-combat-fixture`.
- Every recorded interaction is primary-button mouse input. Press-and-hold is permitted only for pushing; no other action gains a hold, drag, double-click, precision, timing, key, or chord requirement.
- User-owned INDARK data and generated music/save/cache files stay outside git.
- Packaging assumption: under the fixed no-new-dependency rule, M4c produces a standard macOS `.app` launcher for an installed `PyAitD` package, not a self-contained frozen Python distribution. The package smoke test creates a clean venv, installs the project, then launches the `.app`. A standalone binary is a separate decision requiring an approved bundler.

## File Map

| File | Responsibility |
|---|---|
| `PyAitD/game.py` | Camera view-list lifetime and stable restart checkpoint. |
| `PyAitD/actors.py`, `PyAitD/eval_var.py`, `PyAitD/life_ops.py` | Reachable FITD animation, fall, collision-volume, and effect semantics. |
| `PyAitD/life.py` | Structured opcode reachability trace without gameplay behavior. |
| `PyAitD/effects.py`, `PyAitD/ui.py`, `PyAitD/__main__.py` | Ending effect, terminal result, title return, and mouse route. |
| `tools/audit_completion.py` | Trace/source audit and named exclusion enforcement. |
| `tools/replay_mouse_journey.py` | Raw-event playback against the normal outer loop. |
| `tools/build_macos_app.py` | Dependency-free installed-package `.app` launcher builder. |
| `tests/data/mouse_journeys/*.json` | Emily/Carnby raw mouse timelines and stable checkpoints. |
| `tests/test_completion_audit.py`, `tests/test_completion_journeys.py` | Closure and both-path release gates. |
| `tests/test_game.py`, `tests/test_floor_start.py`, `tests/test_actors.py`, `tests/test_eval_var.py`, `tests/test_life_ops.py` | Narrow FITD regression tests. |
| `Makefile` | `prove-completion` and `package-macos`. |
| `docs/m4c-completion-proof.md`, `CONTEXT.md` | Final evidence and architecture status. |

---

### Task 1: Make completion evidence executable

**Files:**
- Modify: `PyAitD/life.py:48-72,174-210`
- Create: `tools/audit_completion.py`
- Create: `tests/test_completion_audit.py`
- Create: `tests/data/aitd1_completion_exclusions.json`

**Interfaces:**
- `Trace(path, observer=None)` keeps the current text format and additionally calls `observer(timer, actor_idx, life_num, opcode, pc)` when supplied.
- `audit_completion(source_root, trace_paths, exclusions_path) -> CompletionReport` reports executed opcodes, remaining `stub`/`ponytail:` markers, stale exclusions, and unanchored exclusions.
- Each exclusion has exact `id`, `path`, `line_text`, `reason`, and `fitd_anchor`; exclusions are permitted only for verified no-ops or branches absent from both complete traces.

- [ ] **Step 1: Add failing trace-observer and audit tests**

Pin text compatibility, observer order, I/O-failure isolation, union of Emily/Carnby opcode tuples, rejection of an executed stub, rejection of a stale/mismatched exclusion, and rejection of an exclusion without `FitdLib/<file>:<line>`.

- [ ] **Step 2: Observe the current untracked gaps**

Run: `.venv/bin/pytest tests/test_completion_audit.py -q`

Expected initial report includes the four `game.py` view-list ponytails, `actors.py` fall/ANIM_RESET/body handling, `life_ops.py` real-ZV/SPECIAL/effect markers, `eval_var.py` TEST_ZV_END_ANIM, and the death restart xfail. ANIM_RESET is retained only as an anchored exclusion because the AITD1 dispatch table has no such opcode.

- [ ] **Step 3: Implement the observer and strict audit**

Use `tokenize`/line scanning only in the tool; do not import production modules merely to inspect source. Seed exclusions only for claims already proven absent or no-op in AITD1, with exact FITD anchors. Later tasks must delete exclusions when they implement a path.

- [ ] **Step 4: Verify and commit**

Run: `.venv/bin/pytest tests/test_completion_audit.py tests/test_life_vm.py -q`

```bash
git add PyAitD/life.py tools/audit_completion.py tests/test_completion_audit.py tests/data/aitd1_completion_exclusions.json
git commit -m "test: make AITD1 completion gaps auditable"
```

---

### Task 2: Fix camera view-list lifetime and death restart ownership

**Files:**
- Modify: `PyAitD/game.py:505-541,571-588`
- Modify: `PyAitD/life_ops.py:283-308`
- Modify: `tests/test_game.py`
- Modify: `tests/test_floor_start.py`
- Modify: `tests/test_combat_journey.py:126-138`

**Interfaces:**
- Adds `Game.floor_data(number) -> Floor`, reusing one per-floor cache; `rooms_of_floor` delegates to it.
- Adds `camera_visible_rooms(game) -> frozenset[int]`, resolving the selected camera slot from `num_camera`, or `new_num_camera` while a new view is pending, through `Floor.rooms[].camera_indices[]` and `Camera.viewed_rooms`.
- Adds `record_floor_start(game, floor_start)` as the sole checkpoint writer.
- `op_stage` records a player transition only while real-data health variable 21 is positive; a death-script transition still requests the cinematic floor but preserves the prior restart checkpoint.

- [ ] **Step 1: Add failing view-list phase tests**

Use synthetic floors to pin current-room inclusion, viewed-room inclusion, non-view deletion, `life_mode` 0/1/2 gates, `life == -1`, pending camera selection, invalid camera context, and both the delete and activation passes. Add real floor/camera goldens against FITD `isInViewList` (`main.cpp:1611-1625`) and `GenereActiveList` (`main.cpp:1990-2130`).

- [ ] **Step 2: Add failing checkpoint tests and remove strict xfail**

Pin a healthy player `LM_STAGE` replacing the checkpoint, a non-player stage change leaving it alone, and a zero-health death `LM_STAGE` changing floor without changing it. Delete `@pytest.mark.xfail`; the existing real death journey must pass normally.

- [ ] **Step 3: Implement both owner-level fixes**

Replace `_rooms_by_floor` with the existing-shape `_floors_by_number` cache so rooms and cameras share one `Floor` load. Do not create a second cache or load in `spawn_stage_actors`. Centralize all checkpoint writes through `record_floor_start`, including `init_game`, `enter_floor_start`, and scenario setup.

- [ ] **Step 4: Verify and commit**

Run: `.venv/bin/pytest tests/test_game.py tests/test_floor_start.py tests/test_combat_journey.py -q && make prove`

```bash
git add PyAitD/game.py PyAitD/life_ops.py tests/test_game.py tests/test_floor_start.py tests/test_combat_journey.py
git commit -m "fix: preserve AITD1 actor lifetime and restart checkpoints"
```

---

### Task 3: Close reachable fall and collision-volume gaps

**Files:**
- Modify: `PyAitD/actors.py:113-273`
- Modify: `PyAitD/skel.py:23-65`
- Modify: `PyAitD/life_ops.py:227-231`
- Modify: `PyAitD/eval_var.py:75-180`
- Modify: `tests/test_actors.py`
- Modify: `tests/test_skel.py`
- Modify: `tests/test_life_ops.py`
- Modify: `tests/test_eval_var.py`
- Modify: `tests/test_play_loop.py`

**Interfaces:**
- Adds `manage_fall(game, actor_idx)` following FITD `manageFall` (`anim.cpp:165-203`) across all live actor slots with room-coordinate ZV adjustment and `col_by` publication.
- Adds `body_pose_bounds(body, group_state, alpha, beta, gamma) -> list[int]`; `op_do_real_zv` derives the actor ZV from transformed body vertices instead of delegating to rotated raw bounds.
- Implements `TEST_ZV_END_ANIM` with its two consumed operands and cross-room intersection semantics. ANIM_RESET remains excluded because AITD1 cannot dispatch it.

- [ ] **Step 1: Add failing FITD micro-contract tests**

Pin fall support/no-support, cross-room support, first live collision witness, falling-flag transitions, transformed-vertex bounds at identity and quarter-turn, TEST_ZV_END_ANIM hit/miss/deleted-object/cross-room cases, and no rendering/pygame imports.

- [ ] **Step 2: Confirm current ponytails/stub fail**

Run: `.venv/bin/pytest tests/test_actors.py tests/test_skel.py tests/test_life_ops.py tests/test_eval_var.py tests/test_play_loop.py -q`

- [ ] **Step 3: Port only the shared primitives required by the traces**

Reuse `pose_vertices`, existing room deltas/ZV intersection helpers, and current `AnimPlayer`. Preserve per-actor animation -> trigger -> combat order. If the journey audit proves the body `-1` or `RealValue.num_steps == -1` branches absent, retain them only as anchored exclusions rather than inventing behavior.

- [ ] **Step 4: Verify and commit**

Run: `.venv/bin/pytest tests/test_actors.py tests/test_skel.py tests/test_life_ops.py tests/test_eval_var.py tests/test_play_loop.py tests/test_playworld.py -q && make prove`

```bash
git add PyAitD/actors.py PyAitD/skel.py PyAitD/life_ops.py PyAitD/eval_var.py tests/test_actors.py tests/test_skel.py tests/test_life_ops.py tests/test_eval_var.py tests/test_play_loop.py
git commit -m "feat: close reachable AITD1 motion semantics"
```

---

### Task 4: Implement AITD1 SPECIAL modes and certify no-op effects

**Files:**
- Modify: `PyAitD/game.py:120-181`
- Modify: `PyAitD/effects.py`
- Modify: `PyAitD/life_ops.py:214-264,423-439,502-563`
- Modify: `PyAitD/playworld.py`
- Modify: `PyAitD/ui.py`
- Modify: `tests/test_effects.py`
- Modify: `tests/test_life_ops.py`
- Modify: `tests/test_playworld.py`
- Modify: `tests/test_ui_render.py`

**Interfaces:**
- Adds pygame-free immutable `SpecialParticle(x, y, z, velocity, lifetime)` and `SpecialEffect(kind, actor_idx, room, x, y, z, color, particles, started_tick, duration_ticks)` records plus `game.special_effects: list[SpecialEffect]`; this active list is not drained as a one-shot platform effect.
- `op_special` supports the three AITD1 handler modes 0 (evaporate), 1 (blood), and 4 (smoke). Durations are 60/25/50 ticks and particles are seeded by `game.rng`; unsupported reached modes raise with mode/LIFE/actor/pc context.
- `expire_special_effects(game)` runs in the normal simulation tick; `render_special_effects(frame, game, scene)` is presentation-only.

- [ ] **Step 1: Pin the three AITD1 SPECIAL contracts**

Add tests for mode 0 source-ZV particles, mode 1 victim/hit-source hot-point placement, mode 4 source placement, deterministic seeded particles, 60/25/50-tick expiry, floor/room ownership, and contextual rejection of unsupported modes. Cite FITD `life.cpp:1388-1451` for dispatch/placement and the pinned secondary source only for the missing particle/lifetime behavior.

- [ ] **Step 2: Add no-op operand tests**

For RND_FREQ, SHAKING, WATER, REP_SAMPLE, and STOP_SAMPLE, assert exact PC advancement and no mutation/effect, citing their AITD1 `life.cpp` branches. Remove “stub” from their comments and audit entries.

- [ ] **Step 3: Implement SPECIAL through existing effects**

Keep allocation/lifetime in simulation and drawing in `ui.py`; do not create a pygame sprite system or change combat targeting. Reuse `world.transform_point` and the existing indexed-palette drawing boundary. Special effects never become pointer targets or collision participants.

- [ ] **Step 4: Verify and commit**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_effects.py tests/test_life_ops.py tests/test_playworld.py tests/test_ui_render.py -q && make prove`

```bash
git add PyAitD/game.py PyAitD/effects.py PyAitD/life_ops.py PyAitD/playworld.py PyAitD/ui.py tests/test_effects.py tests/test_life_ops.py tests/test_playworld.py tests/test_ui_render.py
git commit -m "feat: close reachable AITD1 visual effects"
```

---

### Task 5: Connect END_SEQUENCE to a terminal, mouse-accessible ending

**Files:**
- Modify: `PyAitD/effects.py`
- Modify: `PyAitD/life_ops.py:589-591`
- Modify: `PyAitD/ui.py`
- Modify: `PyAitD/__main__.py`
- Modify: `PyAitD/mouse_contract.py`
- Modify: `tests/test_life_ops.py`
- Modify: `tests/test_runtime_modes.py`
- Modify: `tests/test_ui_mouse.py`
- Modify: `tests/test_mouse_only.py`

**Interfaces:**
- `op_end_sequence` emits `ShowSequence("ENDSEQ", resume=False, skippable=True)` and suspends after the opcode.
- Adds `GameCompleted(hero: int)` and `EndingPresenter(sequence, complete=False, hover=False)`; natural final-frame completion records the hero and opens a whole-frame single-click “Return to title” action.
- `apply_ending_result` replaces the completed game with character selection through the same application-owned replacement boundary used by restart/load.

- [ ] **Step 1: Pin the inferred DOS ending handoff**

Capture the original DOS final transition: final LIFE/opcode, ENDSEQ first/last frame, audio state, and return destination. Record it in the test comment and `docs/m4c-completion-proof.md`; this is the acceptance anchor because FITD `life.cpp:2186-2191` is a TODO. Confirm the shipped archive is the M4b-decoded 32-frame ENDSEQ before writing the behavior test.

- [ ] **Step 2: Add failing opcode and terminal-state tests**

Pin single emission/suspension, no following LIFE opcode replay, natural ENDSEQ completion, permitted cinematic skip, completed-hero identity, frozen gameplay, audio update continuity, focus loss, atomic input cancellation, return-to-title replacement, and exactly one present per frame.

- [ ] **Step 3: Add mouse contract tests**

Declare `sequence_skip` and `ending_return_to_title`; prove both accept a physical or `touch=True` primary click without hover, while other buttons and out-of-window positions do nothing.

- [ ] **Step 4: Wire the existing sequence mode**

Reuse M4b `ShowSequence`, `SequencePresenter`, decoder, and outer-loop timing. Do not add another sequence player or nested loop. Do not mutate world state from `ui.py`.

- [ ] **Step 5: Verify and commit**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_life_ops.py tests/test_runtime_modes.py tests/test_ui_mouse.py tests/test_mouse_only.py -q && make prove-media`

```bash
git add PyAitD/effects.py PyAitD/life_ops.py PyAitD/ui.py PyAitD/__main__.py PyAitD/mouse_contract.py tests/test_life_ops.py tests/test_runtime_modes.py tests/test_ui_mouse.py tests/test_mouse_only.py
git commit -m "feat: connect the AITD1 ending to the application shell"
```

---

### Task 6: Record and replay both complete one-button journeys

**Files:**
- Create: `tools/replay_mouse_journey.py`
- Create: `tests/data/mouse_journeys/emily.json`
- Create: `tests/data/mouse_journeys/carnby.json`
- Create: `tests/test_completion_journeys.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- `JourneyEvent` JSON records `frame`, pygame mouse event kind, logical `pos`, button, optional `touch`, and optional `checkpoint`.
- `JourneyCheckpoint` records hero, floor, room, camera, LIFE, inventory object IDs, in-hand object, selected vars/CVars, and mode; it contains no mutable replacement state.
- `replay_journey(data_dir, recording, *, windowed=False) -> JourneyReport` feeds events through `run()`'s event source/clock seam and reports frames, ticks, checkpoints, executed opcode tuples, completion, modal budget, and last progress.

- [ ] **Step 1: Build a failing raw-event harness**

Prove the harness rejects direct-state commands, debug starts, keyboard events, non-primary buttons, non-push holds, missing releases, checkpoint mutation, and recordings without character-selection and `GameCompleted` boundaries. Use a short attic fixture to show it traverses the same `event_to_input`, `route_mouse`, `resolve_play_click`, and renderer coordinate path as `run()`.

- [ ] **Step 2: Record Emily from character selection through ending**

Run the real window, record only mouse motion/down/up plus elapsed frames, and checkpoint every room/floor transition, inventory puzzle result, combat survival boundary, persistence round-trip, and ENDSEQ completion. Remove exploratory clicks; replay twice headlessly and require identical checkpoints/opcode coverage.

- [ ] **Step 3: Record Carnby independently**

Repeat from a fresh process and fresh slot directory. Do not derive Carnby by editing Emily's hero field; preserve protagonist-specific scripts, objects, and ending checkpoint.

- [ ] **Step 4: Add bounded regression assertions**

Fail with the last checkpoint and recent trace when no progress occurs for 3,000 gameplay ticks, one modal survives 1,000 outer frames without recorded input, navigation repeats a failed decision, or total playback exceeds the committed frame budget. Assert every press has one release except explicit push spans.

- [ ] **Step 5: Verify and commit**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_completion_journeys.py -q`

```bash
git add tools/replay_mouse_journey.py tests/conftest.py tests/test_completion_journeys.py tests/data/mouse_journeys
git commit -m "test: prove both AITD1 one-button completion paths"
```

---

### Task 7: Build and smoke the installed-package macOS application

**Files:**
- Create: `tools/build_macos_app.py`
- Create: `tests/test_macos_package.py`
- Modify: `Makefile`

**Interfaces:**
- `build_app(output, python_executable) -> Path` creates `PyAitD.app/Contents/Info.plist`, `MacOS/PyAitD`, and `Resources/README-data.txt`.
- The launcher executes the supplied installed interpreter with `-m PyAitD`; INDARK remains external and is selected through the normal `--data`/default path.
- `make package-macos` requires `platform.system() == "Darwin"` and `platform.machine() == "arm64"`, then writes `dist/PyAitD.app`.

- [ ] **Step 1: Add failing bundle-structure tests**

Pin bundle identifier/version, executable bit, argument forwarding with spaces, no committed game data/cache/save, missing-interpreter diagnostic, and rejection of non-macOS/non-arm64 release builds.

- [ ] **Step 2: Implement the minimal launcher bundle**

Use `plistlib`, `pathlib`, and `stat`; generate no shell fragments from user input. The launcher resolves its configured interpreter and runs `-m PyAitD "$@"`. Do not copy `.venv` or claim a frozen artifact.

- [ ] **Step 3: Smoke from a clean installed environment on Apple Silicon**

Create a temporary venv, install `.` from the checkout, build the app against that interpreter, and prove cold start, character-selection frame, resize/focus loss, silent-audio fallback, recoverable missing-data message, external-data launch, and clean click-to-quit. Keep the temporary venv and app outside git.

- [ ] **Step 4: Verify and commit**

Run: `.venv/bin/pytest tests/test_macos_package.py -q`

On Apple Silicon also run: `make package-macos && .venv/bin/pytest tests/test_macos_package.py -q -m package`

```bash
git add tools/build_macos_app.py tests/test_macos_package.py Makefile
git commit -m "build: add installed-package macOS app launcher"
```

---

### Task 8: Lock the release gates and evidence

**Files:**
- Modify: `tools/audit_completion.py`
- Modify: `tests/test_completion_audit.py`
- Modify: `Makefile`
- Create: `docs/m4c-completion-proof.md`
- Modify: `CONTEXT.md`

**Interfaces:**
- Adds `make prove-completion`: audit, both completion journeys, mouse contract, persistence, media, shell, and package-structure tests under dummy SDL.
- Audit fails on a reached stub/ponytail, an unused exclusion, missing FITD anchor, strict xfail, absent hero completion, keyboard event, debug bypass, or mouse-contract omission.

- [ ] **Step 1: Turn both trace unions into the final audit input**

Run both recordings, feed their traces to `audit_completion`, delete resolved exclusions, and keep only exclusions whose branches are absent from both paths or verified AITD1 no-ops. The report must name every retained exclusion and why it cannot affect either release path.

- [ ] **Step 2: Add the focused gate**

Add `prove-completion` to `.PHONY`; include `tests/test_completion_audit.py`, `tests/test_completion_journeys.py`, `tests/test_mouse_only.py`, `tests/test_save.py`, `tests/test_audio.py`, `tests/test_sequence.py`, `tests/test_shell_journeys.py`, and `tests/test_macos_package.py`.

- [ ] **Step 3: Run every automated release gate**

Run: `make prove-mouse-accessibility && make prove-persistence && make prove-media && make prove-completion && .venv/bin/pytest -q && make prove`

Expected: no xfail/xpass, no reachable incomplete marker, both heroes complete, and all earlier gates remain green.

- [ ] **Step 4: Perform the two required windowed walkthroughs**

On Apple Silicon, launch the built `.app` twice with a physical single-button pointer: Emily then Carnby. For each, verify selection, movement, the required hold-to-push, inventory/combat, system save/load, media/sequence interaction, ending, return to title, focus-loss cancellation, and clean quit. Record date, machine architecture, data identity digest, save directory, final checkpoint, and observed issues in `docs/m4c-completion-proof.md`.

- [ ] **Step 5: Update the living architecture map**

Mark M4c complete only after automated and windowed evidence exists. Document trace/audit ownership, ending replacement, journey fixtures, packaging limitation, and final commands. Do not describe planning checks as game verification.

- [ ] **Step 6: Verify documentation and commit**

Run: `git diff --check && make prove-completion && .venv/bin/pytest -q && make prove`

```bash
git add tools/audit_completion.py tests/test_completion_audit.py Makefile docs/m4c-completion-proof.md CONTEXT.md
git commit -m "docs: close the AITD1 completion release gate"
```

## Definition of Done

- Both checked-in recordings begin at character selection and reach `GameCompleted` through raw one-button events with no debug setup or direct state mutation.
- Every behavior executed by either trace is implemented or an anchored verified AITD1 no-op; the audit has no stale or unanchored exclusion.
- The death restart test passes without xfail and returns to the last playable checkpoint.
- Camera-visible actor lifetime, reachable fall/animation/ZV semantics, SPECIAL, and END_SEQUENCE match pinned FITD behavior.
- Every ending/system/media/persistence action has an exhaustive mouse-contract route and forgiving target.
- The complete automated suite and both physical windowed walkthroughs pass.
- The Apple Silicon installed-package `.app` cold-starts and passes focus, resize, missing-data, silent-audio, external-data, and quit smoke checks.
- `CONTEXT.md` and `docs/m4c-completion-proof.md` distinguish automated, windowed, and packaging evidence honestly.
