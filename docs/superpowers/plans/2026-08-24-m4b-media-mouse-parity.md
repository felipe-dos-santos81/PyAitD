# M4b Media and Mouse Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the audio stubs with non-blocking sample/music behavior, decode PRESENT/ENDSEQ media, provide silent recovery, and make every sequence/error decision usable by one forgiving physical or touch-origin click.

**Architecture:** LIFE handlers emit pygame-free typed media effects. `interaction.py` transfers platform effects without playing them; `__main__.py` drains them through an `AudioSystem` and advances sequence presenters inside the single event loop. Samples and cached music use pygame mixer. A pure sequence parser produces indexed frames. Custom ADLM music is converted offline and cached; the gameplay loop never synthesizes audio.

**Tech Stack:** Python 3.12, pygame-ce 2.5.8, NumPy, stdlib WAV/hash/path APIs, pytest, the existing setuptools build backend, and a narrow bundled adapter over FITD's existing GPL-compatible `fmopl.cpp`. Add no Python/runtime package.

**Spec:** `docs/superpowers/specs/2026-08-24-overall-mouse-accessibility-design.md` and `docs/superpowers/specs/2026-08-22-aitd1-build-conclusion-design.md`

## Global Constraints

- Depends on the hardening and M4a2 plans. Reuse `runtime_error`, Dismiss first refusal, effective hit geometry, hover, touch parity, and atomic takeover.
- Library decision is locked after current research: [libADLMIDI](https://github.com/Wohlstand/libADLMIDI) does not consume this custom ADLM command stream; [PyOPL](https://github.com/Malvineous/pyopl) is GPLv3 and incompatible with GPL-2.0-only; adding either package violates fixed dependencies. Reuse FITD's `music.cpp` ADLM semantics and `fmopl.cpp` core only inside the offline converter boundary.
- Vendored FITD source retains its original notices and is tracked in `vendor/fmopl/PROVENANCE.md`; the Python package list remains pygame-ce, ModernGL, NumPy, pytest.
- `life_ops.py`, `effects.py`, `interaction.py`, and `playworld.py` never import pygame, mixer, renderer, or raw events.
- Playback never blocks or pumps events. `__main__.py` owns the only event pump and updates media once per outer frame.
- `REP_SAMPLE` and `STOP_SAMPLE` remain verified AITD1 no-ops (`life.cpp:1754-1775`). They receive explicit tests and lose the misleading “stub” label; do not invent AITD2 behavior.
- `ANIM_SAMPLE` emits only when `end_frame != 0`, actor animation matches, and actor frame matches (`life.cpp:1685-1728`).
- Samples use all 101 raw priority bytes in `PRIORITY.ITD`; a new sample interrupts the reserved channel only when its priority is greater than or equal to the active priority.
- PRESENT is 15 independent `VP` entries. Each is exactly 64,770 bytes: marker `VP`, 768-byte 8-bit palette, 64,000 indexed pixels.
- ENDSEQ is 32 entries: entry 0 is the same full-frame form; entries 1–31 are complete FITD delta streams. Each delta must consume its complete input, terminate with opcode 0, and advance exactly 64,000 destination pixels.
- Sequence frame cadence is five 60 Hz units (`sequence.cpp:228-235`), represented as 83 ms accumulated in the outer loop. PRESENT click advances one static page; ENDSEQ click skips the remaining cinematic. No click requires prior hover.
- No volume/toggle control is added in M4b; therefore there is no hidden mouse route to implement. If a later milestone exposes one, it must add a contract entry and large target.

## File Map

| File | Responsibility |
|---|---|
| `vendor/fmopl/` | FITD-derived OPL2 core, thin Python extension wrapper, provenance. |
| `PyAitD/adlm.py` | Pure ADLM command parser, deterministic register timeline, WAV cache identity. |
| `PyAitD/audio.py` | pygame mixer sample/music adapter and silent adapter. |
| `PyAitD/sequence.py` | Pure VP and delta parsing into indexed frames/palettes. |
| `PyAitD/assets.py` | LISTSAMP/LISTMUS/PRESENT/ENDSEQ accessors and caches. |
| `PyAitD/effects.py`, `PyAitD/life_ops.py`, `PyAitD/interaction.py` | Typed media effects and faithful opcode emission. |
| `PyAitD/ui.py`, `PyAitD/__main__.py` | Sequence presenter/mode, click/hover, updates, errors, audio lifetime. |
| `PyAitD/mouse_contract.py` | Sequence advance/skip/error capabilities. |
| `tests/test_adlm.py`, `tests/test_audio.py`, `tests/test_sequence.py` | Pure/adapter contracts and real-data goldens. |
| `tests/test_life_ops.py`, `tests/test_runtime_modes.py`, `tests/test_mouse_only.py` | Opcode/order/event-loop/mouse parity. |
| `Makefile` | `prove-media`. |
| `docs/m4b-media-proof.md`, `CONTEXT.md` | Evidence and ownership. |

---

### Task 1: Correct PRIORITY and expose media archives

**Files:**
- Modify: `PyAitD/formats.py:394-397`
- Modify: `PyAitD/assets.py:10-120`
- Modify: `tests/test_world_data.py`
- Modify: `tests/test_assets.py`

**Interfaces:**
- `parse_priority(raw) -> list[int]` returns one unsigned byte per sample.
- Adds `Assets.sample_raw(index)`, `music_raw(index)`, `presentation_raw(index)`, `ending_raw(index)`, plus counts 101/8/15/32.

- [ ] **Step 1: Add failing real-data goldens**

Assert PRIORITY length 101 and exact first/last bytes; archive counts; LISTSAMP entries begin `b"Creative Voice File"`; LISTMUS entries begin `b"ADLM"`; VP and ENDSEQ shapes. Add out-of-range and missing-archive context tests.

- [ ] **Step 2: Confirm the current parser fails at 50 values**

Run: `.venv/bin/pytest tests/test_world_data.py tests/test_assets.py -q`

- [ ] **Step 3: Implement raw-byte priority and cached accessors**

Use existing `find_pak`, `Pak.count`, and `load_entry`; do not add a second archive reader.

- [ ] **Step 4: Verify and commit**

Run: `.venv/bin/pytest tests/test_world_data.py tests/test_assets.py -q && .venv/bin/pytest -q`

```bash
git add PyAitD/formats.py PyAitD/assets.py tests/test_world_data.py tests/test_assets.py
git commit -m "feat: expose AITD1 media archives and priorities"
```

---

### Task 2: Pure PRESENT and ENDSEQ decoders

**Files:**
- Create: `PyAitD/sequence.py`
- Create: `tests/test_sequence.py`

**Interfaces:**
- Produces `IndexedFrame(pixels: np.ndarray, palette: np.ndarray)`, `decode_vp(raw)`, `apply_delta(previous, raw)`, `decode_presentation(assets)`, and `decode_ending(assets)`.
- `apply_delta` implements FITD `unapckSequenceFrame` opcodes: 1 pixel, 2 equal pixels, u8 run, u16 run; color 0 skips while preserving prior pixels.

- [ ] **Step 1: Write failing synthetic and real-data tests**

Cover every opcode/color-zero case, truncation at each operand, missing terminator, overrun/underrun, trailing bytes, input immutability, and prior-frame copy semantics. Real data must decode `(15, 200, 320)` PRESENT and `(32, 200, 320)` ENDSEQ; every ENDSEQ delta consumes all bytes and expands exactly 64,000 pixels.

- [ ] **Step 2: Observe missing module**

Run: `.venv/bin/pytest tests/test_sequence.py -q`

- [ ] **Step 3: Implement strict parsers**

Use `decode_palette(raw[2:770])`; reshape `raw[770:]` to `(200,320)`. For delta, copy the previous indexed array, write/skip by a destination cursor, and raise `ValueError` with archive entry/input offset/output offset context.

- [ ] **Step 4: Verify and commit**

Run: `.venv/bin/pytest tests/test_sequence.py -q && .venv/bin/pytest -q`

```bash
git add PyAitD/sequence.py tests/test_sequence.py
git commit -m "feat: decode PRESENT and ENDSEQ frames"
```

---

### Task 3: Reused OPL core and offline ADLM conversion cache

**Files:**
- Create: `vendor/fmopl/fmopl.cpp`
- Create: `vendor/fmopl/fmopl.h`
- Create: `vendor/fmopl/wrapper.cpp`
- Create: `vendor/fmopl/PROVENANCE.md`
- Create: `PyAitD/adlm.py`
- Create: `tests/test_adlm.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Native wrapper exposes `_fmopl.render(register_events, sample_rate) -> bytes` of signed 16-bit mono PCM.
- `parse_adlm(raw) -> AdlmSong`, `register_timeline(song)`, `music_cache_path(cache_dir, digest, converter_version)`, and `convert_music(raw, cache_dir) -> Path`.
- Cache file is PCM WAV keyed by SHA-256 of source entry plus `CONVERTER_VERSION`; writes are atomic.
- Existing `[tool.setuptools]` adds one `ext-modules` entry named `PyAitD._fmopl`, sources `vendor/fmopl/wrapper.cpp` and `vendor/fmopl/fmopl.cpp`, and language `c++`.

- [ ] **Step 1: Copy and document the reused core**

Copy only FITD `FitdLib/fmopl.cpp/.h` at the pinned source commit recorded in provenance. The wrapper owns allocation/reset/register writes/PCM extraction and no gameplay code. Verify the source checksum in `tests/test_adlm.py` so provenance cannot drift silently.

- [ ] **Step 2: Add failing ADLM parser/timeline tests**

Port goldens from FITD `music.cpp:musicLoad`, `musicStart`, `executeMusicCommand`, `applyMusicCommandToOPL`, and `musicUpdate`. Assert header `ADLM`, every offset/range, command consumption, channel state, termination, bounded duration, and deterministic register timeline for all eight real entries.

- [ ] **Step 3: Declare and build the adapter, then observe the missing parser/converter**

Add the extension to the existing `pyproject.toml` setuptools table. Run: `.venv/bin/pip install -e . && .venv/bin/pytest tests/test_adlm.py -q`. Reinstall after native-source changes because editable installs do not rebuild binary extensions automatically.

- [ ] **Step 4: Implement the smallest ADLM port and cache**

Port command semantics, not FITD global architecture. Feed timestamped register writes to the reused core in offline chunks, write stdlib `wave` output, cap malformed/infinite songs with contextual errors, and atomically cache. Do not synthesize in `run()`.

- [ ] **Step 5: Verify all eight conversions**

Run: `.venv/bin/pytest tests/test_adlm.py -q`

Expected: eight non-empty deterministic WAVs; second conversion is a cache hit and produces no diff.

- [ ] **Step 6: Commit**

```bash
git add vendor/fmopl PyAitD/adlm.py tests/test_adlm.py pyproject.toml
git commit -m "feat: convert ADLM music through reused FITD OPL core"
```

---

### Task 4: Non-blocking audio and silent adapters

**Files:**
- Create: `PyAitD/audio.py`
- Create: `tests/test_audio.py`

**Interfaces:**
- Produces `AudioSystem(assets, cache_dir)`, `SilentAudioSystem(error)`, and `create_audio_system(assets, cache_dir)`.
- Methods: `play_sample`, `queue_sample`, `play_music`, `queue_music`, `fade_to_music`, `update(elapsed_ms)`, `close`.
- Uses one reserved sample channel and `pygame.mixer.music`; returns/retains contextual errors instead of blocking gameplay.

- [ ] **Step 1: Write failing mocked-mixer tests**

Cover 101 VOC loads from `io.BytesIO`, cache hits, priority ignore/equal interrupt/higher interrupt, sample-then, repeat flag, queue completion, music cache conversion, same-track no-op, fade transition, close, mixer-init failure, malformed media, and silent method no-ops.

- [ ] **Step 2: Observe missing module**

Run: `SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_audio.py -q`

- [ ] **Step 3: Implement adapter boundary**

Reserve a mixer channel, track `active_sample/priority/queued_sample`, and poll `channel.get_busy()` in `update`. Use `pygame.mixer.music.load(str(wav))`, `play`, `fadeout`, and update-time start; never wait for completion.

- [ ] **Step 4: Verify and commit**

Run: `SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_audio.py -q && .venv/bin/pytest -q`

```bash
git add PyAitD/audio.py tests/test_audio.py
git commit -m "feat: add non-blocking pygame audio adapters"
```

---

### Task 5: Typed media effects and faithful LIFE handlers

**Files:**
- Modify: `PyAitD/effects.py`
- Modify: `PyAitD/game.py:158-181`
- Modify: `PyAitD/interaction.py:90-104`
- Modify: `PyAitD/life_ops.py:214-264,423-439,502-563,589-599`
- Modify: `tests/test_effects.py`
- Modify: `tests/test_life_ops.py`

**Interfaces:**
- Adds immutable platform effects `PlaySample`, `QueueSample`, `PlayMusic`, `QueueMusic`, and `FadeToMusic`.
- Adds `game.platform_effects: deque`; `drain_immediate_effects` transfers platform effects in FIFO order without importing pygame.
- LIFE handlers update `current_music/next_music/last_sample/next_sample/last_priority` consistently and emit effects.

- [ ] **Step 1: Add failing opcode/order tests**

Pin operand consumption and emitted FIFO effects for SAMPLE, gated ANIM_SAMPLE, SAMPLE_THEN, SAMPLE_THEN_REPEAT (`repeat=True`), MUSIC, NEXT_MUSIC immediate/queued, FADE_MUSIC active/inactive, and verified REP_SAMPLE/STOP_SAMPLE no-ops. Pin no pygame import in a fresh interpreter.

- [ ] **Step 2: Observe stub failures**

Run: `.venv/bin/pytest tests/test_effects.py tests/test_life_ops.py -q`

- [ ] **Step 3: Implement semantic emission**

Keep platform state mutation in handlers and actual playback in `AudioSystem`. Replace stub logging with FITD comments. Do not wire END_SEQUENCE yet; M4c owns the reachable ending trigger.

- [ ] **Step 4: Verify and commit**

Run: `.venv/bin/pytest tests/test_effects.py tests/test_life_ops.py tests/test_playworld.py -q && make prove`

```bash
git add PyAitD/effects.py PyAitD/game.py PyAitD/interaction.py PyAitD/life_ops.py tests/test_effects.py tests/test_life_ops.py
git commit -m "feat: emit faithful LIFE media effects"
```

---

### Task 6: Sequence mode, presenter, and pointer routes

**Files:**
- Modify: `PyAitD/effects.py`
- Modify: `PyAitD/ui.py`
- Modify: `PyAitD/__main__.py`
- Modify: `tests/test_ui_reducers.py`
- Modify: `tests/test_ui_mouse.py`
- Modify: `tests/test_ui_render.py`
- Modify: `tests/test_runtime_modes.py`

**Interfaces:**
- Adds `GameMode.SEQUENCE` and `ShowSequence(archive: str, resume: bool, skippable: bool)`.
- Adds `SequencePresenter(frame=0, elapsed_ms=0, hover=False)` and `SequenceResult(done: bool, skipped: bool)`.
- `advance_sequence(presenter, elapsed_ms, frame_count)`, `hit_test_sequence`, `render_sequence`, and `apply_sequence_result` follow existing modal/result ownership.

- [ ] **Step 1: Add failing timing/input tests**

Pin one 83 ms advance, catch-up without extra presents, focus loss, PRESENT click one-page advance, ENDSEQ click full skip, illegal/non-skippable click no-op, final-frame close/resume, hover purity, large whole-frame target, atomic takeover, and physical/touch parity.

- [ ] **Step 2: Observe missing mode/effect**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_ui_reducers.py tests/test_ui_mouse.py tests/test_ui_render.py tests/test_runtime_modes.py -k sequence -q`

- [ ] **Step 3: Extend the existing modal loop**

Decode frames once through assets/session cache, render indexed pixels through their palette to the standard `(200,320,3)` frame, update elapsed time in the non-PLAY branch, and apply result without a nested loop. Sequence takeover cancels PLAY input/nav before the first frame.

- [ ] **Step 4: Verify and commit**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_ui_reducers.py tests/test_ui_mouse.py tests/test_ui_render.py tests/test_runtime_modes.py -q && .venv/bin/pytest -q`

```bash
git add PyAitD/effects.py PyAitD/ui.py PyAitD/__main__.py tests/test_ui_reducers.py tests/test_ui_mouse.py tests/test_ui_render.py tests/test_runtime_modes.py
git commit -m "feat: add accessible non-blocking sequence mode"
```

---

### Task 7: Runtime media lifetime, errors, and contract

**Files:**
- Modify: `PyAitD/__main__.py`
- Modify: `PyAitD/mouse_contract.py`
- Modify: `tests/test_play_loop.py`
- Modify: `tests/test_mouse_only.py`
- Modify: `Makefile`

**Interfaces:**
- `run` creates one audio adapter after Renderer initialization, drains `game.platform_effects` after each tick, calls `audio.update(elapsed)` each outer frame, and closes it once.
- Adds capabilities `ADVANCE_PRESENTATION`, `SKIP_SEQUENCE`, and existing runtime-error Dismiss coverage for `SEQUENCE`.
- Adds `prove-media`.

- [ ] **Step 1: Add failing lifecycle/error/contract tests**

Mock audio to assert FIFO drain, one update per outer frame, close on every exit/replacement, silent fallback, persistent error first refusal, no replay after Dismiss, mode exhaustiveness, and no undeclared hold gesture.

- [ ] **Step 2: Observe failure**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_play_loop.py tests/test_mouse_only.py -k 'audio or sequence or media' -q`

- [ ] **Step 3: Wire lifecycle and declarations**

Carry the audio adapter across hero/restart/load game replacements because it belongs to the process; clear queued effects from the old game before replacement. A media error sets `session.runtime_error` and continues silently.

- [ ] **Step 4: Verify and commit**

Run: `make prove-media && make prove-mouse-accessibility && make prove-persistence && .venv/bin/pytest -q && make prove`

```bash
git add PyAitD/__main__.py PyAitD/mouse_contract.py tests/test_play_loop.py tests/test_mouse_only.py Makefile
git commit -m "test: gate media lifecycle and mouse parity"
```

---

### Task 8: Windowed evidence and handoff

**Files:**
- Create: `docs/m4b-media-proof.md`
- Modify: `CONTEXT.md`

- [ ] **Step 1: Run all media decode/playback gates**

Run: `make prove-media && .venv/bin/pytest -q && make prove`.

- [ ] **Step 2: Run a windowed one-button media pass**

For both physical audio and forced silent adapter: trigger samples, queued sample, music/fade, PRESENT advance, ENDSEQ skip, focus loss, malformed-media notice, and Dismiss. Confirm the pump and window remain responsive.

- [ ] **Step 3: Record conversion provenance/cache identity and results**

Do not claim audio equivalence from parser tests alone. Record audible/windowed result, eight-cache second-run no-diff, platform, and any failure/rerun.

- [ ] **Step 4: Commit**

```bash
git add docs/m4b-media-proof.md CONTEXT.md
git commit -m "docs: record M4b media proof"
```

## Milestone Acceptance

- [ ] All 101 samples and all PRESENT/ENDSEQ entries decode; eight ADLM entries convert deterministically and cache by digest/version.
- [ ] Audio and sequences never block or pump events; unavailable audio remains playable.
- [ ] LIFE audio ordering/gates match cited FITD behavior, including explicit AITD1 no-ops.
- [ ] Presentation advance, sequence skip, focus loss, and error dismissal work with one physical or touch-origin click and no replay.
- [ ] `prove-media`, earlier focused gates, full pytest, and `make prove` pass; windowed evidence is recorded.
