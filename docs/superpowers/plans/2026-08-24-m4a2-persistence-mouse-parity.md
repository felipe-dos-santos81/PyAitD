# M4a2 Persistence and Mouse Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a validated, atomic, versioned JSON save/load path with one manual slot and one deferred quick-save slot, expose every persistence decision through forgiving single-click system-menu targets, and prove restoration in a clean process.

**Architecture:** Put the pygame-free snapshot schema, validation, identity, and atomic files in `save.py`. Restore only into a fresh `Game`, then let `__main__.py` replace game/floor/session/input atomically through the existing hero/restart-shaped branch. Extend the existing system-menu presenter/reducer rather than adding a persistence UI subsystem.

**Tech Stack:** Python 3.12 stdlib (`dataclasses`, `hashlib`, `json`, `os`, `pathlib`, `random`, `tempfile`), pygame-ce 2.5.8, pytest. Add no dependency and never use pickle.

**Spec:** `docs/superpowers/specs/2026-08-24-overall-mouse-accessibility-design.md` and `docs/superpowers/specs/2026-08-22-aitd1-build-conclusion-design.md`

## Global Constraints

- Depends on the mouse-accessibility-hardening plan and reuses effective rectangles, hover, atomic takeover, notice first refusal, and touch parity.
- Ambiguity resolved for minimal blast radius: FITD exposes one `SAVE0.ITD` with silent overwrite (`systemMenu.cpp:100-105`, `save.cpp:42-60`). M4a2 therefore provides one manual JSON slot plus one quick-save JSON slot, with no overwrite-confirmation mode.
- A manual save is allowed only while the stable system menu is active, `life_stack` and platform-effect queues are empty, and no other modal continuation is pending. Quick Save closes the menu, becomes a deferred request, and commits at the first stable end-of-PLAY-tick boundary.
- Loading parses and validates the complete file before constructing a fresh `Game`; failure cannot mutate the live game, settings, input, floor, or active modal.
- Save schema excludes assets, renderer/pygame objects, caches, trace handles, active modals, LIFE continuations, navigation decisions/intents, queued audio, transient inputs, and presentation frames.
- Save schema includes source identity, hero, floor/room/camera, vars/CVars/timers/flags/RNG, all actor/world-object dataclass fields, animation interpolation, inventories/in-hand/action, messages, and control-affecting settings.
- Every load clears transient pointer/action/navigation state before the replacement becomes visible.
- Save writes are `fsync` + `os.replace`; recoverable I/O/schema errors remain visible until the large Dismiss target is clicked.
- All Python files keep the SPDX first line. `save.py` imports no pygame.

## Stable Save Contract

Root JSON keys are exactly:

```text
schema, engine_version, source, hero, game, actors, world_objects,
anim_players, inventory, messages, rng_state, settings
```

`schema` is `1`; `engine_version` is `PyAitD.__version__`; `source` contains archive names plus a SHA-256 over `OBJETS.ITD`, `VARS.ITD`, `DEFINES.ITD`, `LISTLIFE.PAK`, `LISTTRAK.PAK`, and the selected hero body/animation archives in that order. JSON accepts integers only where engine state is integral; booleans never pass as integers. Actor count is 128, world-object count 292, CVars 45, vars 207, inventory shape 2x30.

## File Map

| File | Responsibility |
|---|---|
| `PyAitD/save.py` | Pure schema, source identity, snapshot, validation, atomic slot I/O, fresh-game restoration. |
| `PyAitD/game.py`, `PyAitD/eval_var.py` | Per-game RNG and restorable state only. |
| `PyAitD/ui.py` | SAVE/LOAD pages, presenter/results, layouts, reducer, render/hit/hover. |
| `PyAitD/__main__.py` | Save directory, manual/deferred policy, notices, atomic load branch. |
| `PyAitD/mouse_contract.py` | Save/load/quick-save/slot/back/error capabilities. |
| `tests/test_save.py` | Pure schema, corruption, atomicity, restoration, clean-process proof. |
| `tests/test_ui_reducers.py`, `tests/test_ui_mouse.py` | Persistence pages and single-click routes. |
| `tests/test_runtime_modes.py`, `tests/test_shell_journeys.py` | Loop policy, replacement, failures, touch parity. |
| `Makefile` | `prove-persistence`. |
| `docs/m4a2-persistence-proof.md`, `CONTEXT.md` | Evidence and ownership. |

---

### Task 1: Per-game deterministic RNG

**Files:**
- Modify: `PyAitD/game.py:119-181`
- Modify: `PyAitD/eval_var.py:1-4,153-156`
- Create: `tests/test_game_rng.py`

**Interfaces:**
- `Game.rng: random.Random` is the only gameplay RNG.
- evalVar code `0x1C` calls `vm.game.rng.randrange(n)`.

- [ ] **Step 1: Write a failing isolation test**

Construct two games, seed each `game.rng` equally, perturb module-global `random`, execute the same synthetic evalVar, and assert identical results and restorable `getstate()`.

- [ ] **Step 2: Observe the global-RNG failure**

Run: `.venv/bin/pytest tests/test_game_rng.py -q`

- [ ] **Step 3: Move randomness behind `Game`**

Import `random` in `game.py`, initialize `self.rng = random.Random()`, remove `import random` from `eval_var.py`, and use `game.rng`.

- [ ] **Step 4: Verify and commit**

Run: `.venv/bin/pytest tests/test_game_rng.py tests/test_eval_var.py -q && .venv/bin/pytest -q`

```bash
git add PyAitD/game.py PyAitD/eval_var.py tests/test_game_rng.py
git commit -m "refactor: own gameplay rng on the game session"
```

---

### Task 2: Source identity and structural snapshot

**Files:**
- Create: `PyAitD/save.py`
- Create: `tests/test_save.py`
- Modify: `PyAitD/__init__.py`

**Interfaces:**
- Produces `SCHEMA = 1`, `SaveError`, `source_identity(data_dir, hero)`, `snapshot_game(game, settings) -> dict`, and `validate_snapshot(payload, data_dir) -> dict`.
- Uses `dataclasses.fields(Actor)` and the existing WorldObject dataclass fields as the authoritative field sets; rejects missing/extra fields.

- [ ] **Step 1: Write failing shape and identity tests**

Pin root keys, counts, hero archive names, digest stability, all Actor/WorldObject field names, and exclusion of every transient/cache field. Mutate one byte in a copied identity input and assert mismatch. Add wrong-type, bool-as-int, range/count, missing/extra-key, and unknown-schema cases with JSON-path error context.

- [ ] **Step 2: Verify missing module**

Run: `.venv/bin/pytest tests/test_save.py -q`

Expected: `ModuleNotFoundError: No module named 'PyAitD.save'`.

- [ ] **Step 3: Implement the schema helpers**

Encode `RealValue` as its four integer fields. Encode `FloorStart` or `null`. Encode `TimedMessage` as `{message_id, age}`. Convert RNG tuple state recursively to JSON lists and back only after full numeric/list validation. Add `__version__ = "0.1.0"` to `PyAitD/__init__.py` and keep it aligned with `pyproject.toml`.

- [ ] **Step 4: Verify and commit**

Run: `.venv/bin/pytest tests/test_save.py -q && .venv/bin/pytest -q`

```bash
git add PyAitD/save.py PyAitD/__init__.py tests/test_save.py
git commit -m "feat: define versioned save snapshot schema"
```

---

### Task 3: Animation state and fresh-game restoration

**Files:**
- Modify: `PyAitD/save.py`
- Modify: `tests/test_save.py`

**Interfaces:**
- Produces `restore_game(data_dir, payload) -> tuple[Game, Settings]`.
- `anim_players[str(actor_idx)]` stores `frame`, `start_tick`, `prev_frame_index|null`, `states`, `anim_step`, and `wrapped`; body/animation identities are resolved from restored actor fields and `Assets`.
- Restoration always resets modal/navigation/input/restart/platform queues, creates a fresh `MeshCache`, sets `flag_init_view=2` and `flag_genere_aff_list=1`, and preserves the snapshot's stable floor/room/camera target.

- [ ] **Step 1: Add a round-trip state test**

Mutate representatives of every field family, advance a real animation between keyframes, populate inventory/messages, save RNG state, snapshot, restore, and compare a second snapshot. Then run one identical `play_tick` and one RNG read on original/restored games and compare results.

- [ ] **Step 2: Observe missing restoration**

Run: `.venv/bin/pytest tests/test_save.py -k 'restore or round_trip' -q`

- [ ] **Step 3: Restore into a new object graph**

Call `init_game(data_dir, hero=payload["hero"])`, replace validated dataclass/list/scalar state, reconstruct `AnimPlayer` objects from `assets.body/anim`, and never mutate an input `Game`. Reject a live actor whose body/anim/player references are inconsistent.

- [ ] **Step 4: Verify and commit**

Run: `.venv/bin/pytest tests/test_save.py tests/test_anim_player.py tests/test_playworld.py -q && make prove`

```bash
git add PyAitD/save.py tests/test_save.py
git commit -m "feat: restore validated saves into fresh games"
```

---

### Task 4: Atomic manual and quick slot storage

**Files:**
- Modify: `PyAitD/save.py`
- Modify: `tests/test_save.py`

**Interfaces:**
- Produces `save_dir(*, platform=None, home=None)`, `slot_path(directory, kind)`, `write_slot(path, payload) -> str|None`, and `read_slot(path, data_dir) -> tuple[dict|None, str|None]`.
- `kind` is exactly `"manual"` or `"quick"`; filenames are `save-manual.json` and `save-quick.json`.

- [ ] **Step 1: Add failing path/I/O tests**

Pin Darwin and Linux paths beside the existing settings location. Cover missing slot, malformed/truncated JSON, incompatible source, unwritable directory, simulated `json.dump`, `flush`, `fsync`, and `os.replace` failures. Assert an existing valid slot remains byte-identical and temp files are removed after every failure.

- [ ] **Step 2: Observe failure**

Run: `.venv/bin/pytest tests/test_save.py -k 'slot or atomic' -q`

- [ ] **Step 3: Implement strict read and atomic write**

Write UTF-8 JSON with sorted keys and compact separators to a same-directory named temp file, flush/fsync, replace, and best-effort cleanup. Never swallow programmer exceptions from snapshot construction; convert filesystem/JSON/schema failures to a contextual visible error string.

- [ ] **Step 4: Verify and commit**

Run: `.venv/bin/pytest tests/test_save.py -q && .venv/bin/pytest -q`

```bash
git add PyAitD/save.py tests/test_save.py
git commit -m "feat: persist save slots atomically"
```

---

### Task 5: Persistence pages in the existing system menu

**Files:**
- Modify: `PyAitD/ui.py:253-338,353-375,620-634,675-700,703-733`
- Modify: `tests/test_ui_reducers.py`
- Modify: `tests/test_ui_mouse.py`
- Modify: `tests/test_ui_render.py`

**Interfaces:**
- Extends `SystemMenuPage` with `SAVE` and `LOAD`.
- MAIN rows become `Return`, `Save`, `Load`, `Quick Save`, `Configuration`, `Quit`.
- SAVE rows are `Manual Slot`, `Back`; LOAD rows are `Manual Slot`, `Quick Save`, `Back`.
- Extends `SystemMenuResult` with `save_slot: str|None`, `load_slot: str|None`, and `quick_save: bool`.
- `ModalSession` adds `save_directory`, `runtime_error`, `pending_load`, and `quick_save_requested`.

- [ ] **Step 1: Add failing reducer/render/hit tests**

Pin keyboard and mouse navigation, wrap counts, unavailable load-row disabled behavior, Back, hover, effective rectangles, six MAIN labels, and result values. A disabled missing slot is a no-op and cannot fall through to Back.

- [ ] **Step 2: Observe failure**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_reducers.py tests/test_ui_mouse.py tests/test_ui_render.py -q`

- [ ] **Step 3: Extend the existing presenter only**

Pass `available_slots: frozenset[str]` into reducer/render/hit functions. Reuse `_button`, effective rows, hover, and the current presenter lifetime. Do not create a new game mode: SAVE/LOAD are pages of `SYSTEM_MENU`.

- [ ] **Step 4: Verify and commit**

Run: `SDL_VIDEODRIVER=dummy .venv/bin/pytest tests/test_ui_reducers.py tests/test_ui_mouse.py tests/test_ui_render.py -q && .venv/bin/pytest -q`

```bash
git add PyAitD/ui.py tests/test_ui_reducers.py tests/test_ui_mouse.py tests/test_ui_render.py
git commit -m "feat: add accessible persistence menu pages"
```

---

### Task 6: Manual save, deferred quick save, and atomic load replacement

**Files:**
- Modify: `PyAitD/__main__.py:42-87,320-368,613-811,814-841`
- Modify: `tests/test_runtime_modes.py`
- Modify: `tests/test_shell_journeys.py`
- Modify: `tests/test_main.py`

**Interfaces:**
- Adds CLI `--save-dir` and `load_runtime_session(..., save_directory=...)`.
- Produces `_manual_save`, `_request_quick_save`, `_commit_quick_save`, and `_load_branch`.
- `_load_branch` returns the same full loop-local tuple shape as `_hero_branch`/`_restart_branch`.

- [ ] **Step 1: Add failing real-loop scripts**

Cover: manual save; mutate then load; missing/corrupt/incompatible load; click Dismiss; deferred quick save does not write before a stable tick; refusal with a LIFE continuation; clean input/nav after load; physical/touch parity; and no mutation on every error. Bound each script to fewer than 20 event frames.

- [ ] **Step 2: Confirm failures**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_runtime_modes.py tests/test_shell_journeys.py tests/test_main.py -k 'save or load or quick' -q`

- [ ] **Step 3: Wire policy through existing seams**

Manual save snapshots `game` plus `session.settings`. Quick Save closes the menu, sets the request, and commits only after `play_tick` returns with PLAY active and empty continuation/effect queues. Load click calls `read_slot` only; a successful payload is assigned to `pending_load`; `_load_branch` restores/loads `Floor`, creates a replacement session/input, performs atomic takeover, then one tuple assignment and `continue`.

- [ ] **Step 4: Verify and commit**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_runtime_modes.py tests/test_shell_journeys.py tests/test_main.py -q && .venv/bin/pytest -q && make prove`

```bash
git add PyAitD/__main__.py tests/test_runtime_modes.py tests/test_shell_journeys.py tests/test_main.py
git commit -m "feat: integrate atomic save and load lifecycle"
```

---

### Task 7: Mouse contract and clean-process proof

**Files:**
- Modify: `PyAitD/mouse_contract.py`
- Modify: `tests/test_mouse_only.py`
- Modify: `tests/test_save.py`
- Modify: `Makefile`

**Interfaces:**
- Adds capabilities `SAVE_MANUAL`, `LOAD_MANUAL`, `LOAD_QUICK`, `QUICK_SAVE`, and `PERSISTENCE_BACK`, all `left_click` in `SYSTEM_MENU`.
- Adds `prove-persistence` focused target.

- [ ] **Step 1: Add failing exhaustiveness and subprocess tests**

Spawn a Python process that loads a real saved slot from an explicit temp directory and emits a compact checkpoint tuple; compare it to the writer process. Assert all persistence results have declared routes and both touch origins match.

- [ ] **Step 2: Observe failure**

Run: `.venv/bin/pytest tests/test_mouse_only.py tests/test_save.py -k 'persistence or process' -q`

- [ ] **Step 3: Extend registry and focused gate**

Keep declarations pygame-free. `prove-persistence` includes save, UI reducer/mouse/render, runtime mode, shell journey, and mouse contract tests under dummy drivers.

- [ ] **Step 4: Verify and commit**

Run: `make prove-persistence && make prove-mouse-accessibility && .venv/bin/pytest -q && make prove`

```bash
git add PyAitD/mouse_contract.py tests/test_mouse_only.py tests/test_save.py Makefile
git commit -m "test: gate persistence and mouse parity"
```

---

### Task 8: Evidence and architecture handoff

**Files:**
- Create: `docs/m4a2-persistence-proof.md`
- Modify: `CONTEXT.md`

- [ ] **Step 1: Run the focused/full gates and a clean-process manual save/load**

Run: `make prove-persistence && .venv/bin/pytest -q && make prove`.

- [ ] **Step 2: Record a windowed one-button persistence pass**

For each hero: manual save, mutate progress, load, quick save, mutate, load quick, exercise missing/corrupt slot notice and Dismiss, then quit/relaunch/load. Record build/data identity and restored checkpoints.

- [ ] **Step 3: Update `CONTEXT.md` only after evidence passes**

- [ ] **Step 4: Commit**

```bash
git add docs/m4a2-persistence-proof.md CONTEXT.md
git commit -m "docs: record M4a2 persistence proof"
```

## Milestone Acceptance

- [ ] Manual and quick slots are versioned JSON, validated completely, and written atomically.
- [ ] Invalid load and write failures leave live state and prior slot bytes unchanged and expose a persistent dismissible notice.
- [ ] Clean-process restoration reproduces all locked state and deterministic next-tick/RNG behavior.
- [ ] Every persistence decision is reachable with one forgiving physical or touch-origin click.
- [ ] Focused, mouse, shell, full pytest, and `make prove` gates pass; windowed evidence covers both heroes.
