# Alone in the Dark 1 — Build Conclusion Design

Date: 2026-08-22

Status: Approved design; implementation plans not yet written

Target: single-player, windowed Apple Silicon application

Reference: FITD at `/Users/felipe.dos.santos/code/theirs/FITD`

## Goal

Conclude the Python/pygame-ce rewrite as a modernized but behavior-faithful
Alone in the Dark 1 engine. The finished application must run from character
selection through the ending using the original user-supplied data, without
debug bypasses, reachable opcode stubs, control freezes, or soft locks.

Completion includes both protagonists, all floors, inventory, interaction,
combat, text and books, death/game-over, menus, save/load, samples, music,
intro/ending sequences, configuration, and windowed macOS packaging.

## Existing baseline

M1, M2, and M3a are complete. The current engine already provides:

- original PAK/ITD parsing and real-data golden tests;
- fixed-camera room rendering, masks, and depth-tested 3D actors;
- body and animation decoding, movement, collision, and camera switching;
- the 87-slot AITD1 LIFE table, variable evaluation, movement tracks, and the
  fixed 50 Hz gameplay loop;
- a responsive outer render loop decoupled from catch-up simulation ticks.

The remaining work is concentrated in the documented M3b/M3c/M4 stubs and
known simplifications: interaction and inventory, `GereDec`, actor collision,
combat `animAction` processing, fall behavior, modal text/pictures, game over,
menus, persistence, audio, and sequences.

## Chosen approach

Finish through small vertical gameplay slices. Each slice crosses state,
LIFE behavior, input, presentation, and tests, and ends in a playable journey.
This is preferred over completing opcodes in isolation or bulk-porting FITD
subsystems because it has the smallest blast radius and exposes integration
errors sooner.

Existing renderer, format parsers, VM tables, `Game`, and fixed-step loop stay
in place. Rendering changes are out of scope unless a slice's acceptance
journey proves one is required.

## Assumptions

- Save files are native to this port; FITD/DOS save interoperability is not
  required.
- Original music may be converted locally into a cacheable mixer format; live
  OPL emulation is not a fidelity requirement.
- Original game data remains user-owned and is never redistributed.
- Both hero choices are release paths even though the application is
  single-player.
- The modernized target permits scalable window presentation, remappable
  controls, and an optional sticky-action accessibility mode.

## Runtime architecture

### Modes

The runtime has one outer event/render loop and an explicit mode:

- `PLAY`
- `FOUND`
- `INVENTORY`
- `READING`
- `SYSTEM_MENU`
- `SEQUENCE`
- `GAME_OVER`

Every outer frame performs this order:

1. Pump pygame events exactly once.
2. Update held movement and edge-triggered commands.
3. Route commands to the active mode.
4. Run fixed 50 Hz gameplay ticks only while gameplay is active.
5. Advance mode-local animation or media time.
6. Render the active mode and present once.

FITD's modal nested loops are behavior references, not a structure to copy.
Inventory, reading, found-object, sequence, and system-menu screens remain
states inside the existing outer loop. Gameplay time pauses in these modes,
while window events, quitting, rendering, and audio continue normally.

Held inputs may be observed by every catch-up tick. Edge-triggered commands
are consumed once, preventing one key press from selecting or dismissing
multiple modal entries.

### Module ownership

| Module | Ownership |
|---|---|
| `game.py` | Authoritative mutable session state, inventory state, active mode, and saveable values |
| `life.py` | VM execution and suspended LIFE continuations |
| `life_ops.py` | Operand decoding plus pure state mutations or typed effect emission |
| `interaction.py` | `GereDec`, actor/object contact, found/take/drop/put, in-hand actions, and found-LIFE execution |
| `combat.py` | `GereFrappe`, hit/fire/throw actions, damage, projectile stopping, and death transitions |
| `actors.py` | Shared animation, motion, collision primitives, and fall integration used by interaction/combat |
| `effects.py` | Typed immediate/modal effect records and continuation tokens; no pygame imports |
| `ui.py` | ITD_RESS-backed modal presenters and command production; no gameplay rules |
| `audio.py` | pygame mixer adapter, sound cache, music state, and silent fallback |
| `save.py` | Snapshot schema, validation, atomic slot storage, and restoration |
| `sequence.py` | Pure PRESENT/ENDSEQ decoding and sequence timing |
| `__main__.py` | Sole event pump, input routing, fixed-step scheduling, mode dispatch, and presentation |

Core state, VM, interaction, combat, persistence, and sequence decoding must
remain testable without initializing pygame or ModernGL. UI and audio consume
typed state/effects at the boundary.

No generic scene framework, ECS, pygame sprite conversion, pygame-menu, or
pygame_gui dependency is introduced. Those abstractions do not match the
original asset-driven screens closely enough to offset their integration cost.

## Effect and continuation boundary

`life_ops.py` must never render, play audio, or pump events. Handlers either
mutate engine state or emit one of two effect families:

- Immediate: play/stop/queue sample or music, change fade/priority, shake, or
  show a timed non-blocking message.
- Modal: found-object decision, read text/book, show picture, open inventory,
  play sequence, or enter game over.

Immediate effects are drained in order without pausing gameplay. Only one
modal effect may be active; later effects remain queued.

When a LIFE opcode opens a modal effect, the VM records a continuation after
all operands have been consumed. A continuation frame contains the owner actor,
LIFE number, and next bytecode position. A small continuation stack covers the
special nested found-LIFE path. Actor-switch dispatch always returns to the
owner before a suspension point.

The current gameplay tick stops before the next game-clock increment. When the
modal result is applied, the suspended LIFE frame resumes before another 50 Hz
tick begins. If the resumed script opens another modal, the same mechanism
suspends it again. This avoids both nested event loops and replaying the script
from byte zero.

UI code emits typed results such as accept/refuse found object, choose inventory
action, dismiss page, load slot, or restart. Interaction/game services apply
those results; presenters never mutate world state directly.

## Completion slices

### M3b — Interaction

Scope:

- introduce runtime modes, effects, and LIFE continuation;
- port FITD `GereDec` and complete actor/object collision writes;
- implement found/take/drop/put and inventory membership/weight/flags;
- run found-LIFE behavior and maintain the selected in-hand object/action;
- implement inventory selection and available actions from `foundFlag`;
- implement MESSAGE, MESSAGE_VALUE, READ, and PICTURE presentation.

Acceptance journey:

- In the opening attic, the player can discover, accept/refuse, inspect, use,
  and drop applicable objects.
- Inventory and reading screens dismiss cleanly, restore the scene, and neither
  repeat LIFE work nor stall held movement afterward.
- World object, actor, inventory, in-hand, and found flags match FITD at each
  transition.

### M3c — Combat and survival

Scope:

- port FITD `GereFrappe` action types and required collision helpers;
- implement HIT, FIRE, THROW, HIT_OBJECT, STOP_HIT_OBJECT, and
  TEST_ZV_END_ANIM semantics;
- implement melee volumes, hot points, projectile/thrown-object motion,
  stopping placement, damage, HIT/HIT_BY state, and relevant sample triggers;
- complete reachable fall management;
- implement death and game-over/restart transitions.

Acceptance journey:

- Deterministic scenarios cover melee, firearm, thrown object, projectile stop,
  enemy damage, player damage, death, and restart.
- Animation frame/action timing and actor/world flags match FITD checkpoints.

### M4a — Shell and persistence

Scope:

- startup and character selection;
- pause/system menu and configuration;
- save-slot and quick-save UI;
- versioned port-native save/load;
- control remapping and sticky-action setting.

Acceptance journey:

- Both protagonists start with the correct initial state.
- A save restored in a new process reproduces floor, room, camera, variables,
  actors, world objects, LIFE/track state, inventory, in-hand state, timers,
  and required configuration.
- Invalid saves leave the running session unchanged and show a recoverable
  error.

### M4b — Audio and sequences

Scope:

- load LISTSAMP entries through pygame mixer and apply PRIORITY semantics;
- implement SAMPLE, ANIM_SAMPLE, SAMPLE_THEN, SAMPLE_THEN_REPEAT, REP_SAMPLE,
  STOP_SAMPLE, MUSIC, NEXT_MUSIC, FADE_MUSIC, and related timing;
- decode PRESENT/ENDSEQ data and connect sequence sound cues;
- build the local LISTMUS conversion/cache path;
- provide a silent audio adapter when no device is available.

Acceptance journey:

- Every referenced sample and sequence entry decodes.
- Playback ordering, interruption, fades, sequence timing, and sequence skip
  match FITD checkpoints without blocking input.
- Missing audio hardware remains playable; malformed required media names the
  failing archive and entry.

### M4c — Playthrough closure

Scope:

- audit every remaining stub, `ponytail:` simplification, and unreachable-case
  assumption against AITD1 scripts and FITD;
- implement only differences reachable in the two complete game paths;
- close view-list lifetime, SPECIAL/WATER/SHAKING/RND_FREQ, sequence-boundary,
  and other remaining effects when reachability proves they matter;
- package and smoke-test the windowed Apple Silicon application.

Acceptance journey:

- Recorded journeys complete both protagonists from selection to ending.
- No reachable stub, exception, soft lock, frozen control, or manual debug
  bypass remains.

## Persistence design

Save files use explicit, versioned JSON rather than pickle. The root records:

- schema and engine version;
- source-data identity sufficient to reject an incompatible INDARK set;
- current floor/room/camera, variables, CVars, timers, flags, and RNG state;
- all mutable actor and world-object fields;
- LIFE/track/animation interpolation state;
- inventory tables, current inventory, in-hand selection, and action;
- settings that affect control interpretation.

Immutable parsed assets, renderer resources, pygame objects, caches, queued
audio, active modal screens, and transient continuation frames are not saved.
Ordinary slot saving is enabled only from a stable system-menu boundary. A
quick-save command becomes a deferred request and commits only at the next
stable end-of-tick boundary; it is rejected while a modal continuation exists.

A load is parsed and fully validated into a temporary snapshot before mutating
the running `Game`. Restoration rebuilds derived/transient state and forces
view/actor-list regeneration. Save writes use a temporary file and atomic
replacement. Tests receive an explicit save directory; the packaged default is
the platform-appropriate per-user application-support directory.

## Media design

The shipped data contains 101 Creative Voice File entries in LISTSAMP. Current
pygame-ce loads all 101 directly from in-memory PAK bytes, so sound effects use
`pygame.mixer.Sound` with a small index cache and require no decoder.

LISTMUS contains eight custom `ADLM` entries. pygame mixer cannot consume this
format directly, and a live generated-audio stream would add timing and native
integration risk. M4b therefore begins with a bounded conversion spike:

1. Reuse FITD's ADLM event semantics as the authoritative parser reference.
2. Prefer a license-compatible existing OPL renderer if it builds reliably on
   Apple Silicon.
3. Keep synthesis in an offline converter, not the gameplay loop.
4. Cache converted WAV/OGG files by source-entry digest and converter version.
5. Use `pygame.mixer.music` exclusively for runtime streaming, fades, and queues.

If no suitable renderer survives the spike, only the converter may contain the
minimal FITD-derived OPL synthesis code. The runtime and all other milestones
remain unaffected.

PRESENT/ENDSEQ decoding is a pure parser modeled on FITD `sequence.cpp`.
Decoded indexed frames become existing pygame/renderer-compatible surfaces;
no external video library is needed.

## Accessibility contract

Accessibility is a release criterion from the first interactive slice:

- every operation has a keyboard route and a large single-click target;
- no operation requires double-click, drag, precise pointing, press-and-hold,
  or a mandatory simultaneous key chord;
- optional sticky action lets the player press Action and then a direction;
- menus support arrows/WASD, Enter/Space, Escape, and single-button mouse use;
- held movement and edge-triggered actions remain distinct through catch-up
  ticks and mode transitions;
- focus loss releases held controls; returning focus never repeats an action;
- controls are remappable without editing configuration files.

Manual release evidence covers keyboard-only, on-screen-keyboard, and
single-button-mouse journeys.

## Error handling

Fail fast with archive, entry, opcode, actor, and byte offset context for:

- missing/corrupt required source data;
- unknown compression, primitive, opcode, or sequence command;
- invalid internal mode/effect/continuation transitions.

Recover without altering valid running state for:

- unavailable audio device (select silent adapter);
- invalid, truncated, incompatible, or unwritable save slots;
- missing/stale converted-music cache (regenerate or report in the audio UI);
- user cancellation of modal screens and sequence playback.

Errors must never create a hidden wait state. A recoverable error remains visible
until explicitly dismissed.

## Verification

Each slice follows test-first implementation and adds the narrowest relevant
checks to the existing suite.

1. Pure unit tests: inventory transitions, collision/action helpers, effect
   ordering, VM suspension/resume, serializers, and sequence commands.
2. Real-data goldens: every referenced archive entry and representative fields
   from each implemented FITD behavior family.
3. Headless scenarios: interaction, modal resume, combat, death, and save/load
   journeys driven by recorded commands.
4. FITD parity traces: compare stable checkpoints containing tick, LIFE opcode,
   actor/world IDs, position, room/camera, flags, inventory, and damage.
5. Full journeys: recorded start-to-ending paths for both protagonists, with
   manual confirmation where deterministic automation is impractical.
6. Media proof: all 101 samples load, every referenced sequence decodes, and all
   eight music entries convert or produce a named actionable failure.
7. Accessibility proof: keyboard-only, on-screen-keyboard, sticky-action, and
   single-button-mouse checks begin in M3b and extend with each later screen.
8. Package proof: cold start, save location, window focus/resize, clean quit,
   missing-data diagnostics, and silent-audio fallback from the built app.

The existing parse-all/headless `make prove` remains a regression gate. Later
plans may add focused scenario and packaged-app proof targets without replacing
the fast unit suite.

## Reference map

Authoritative FITD behavior is concentrated in:

- `inventory.cpp`: `processInventory`, `FoundObjet`, drawing/selection;
- `main.cpp`: `take`, `executeFoundLife`, `GereDec`, collision, messages;
- `animAction.cpp`: `GereFrappe`;
- `life.cpp`: HIT/FIRE/THROW opcode setup and remaining LIFE effects;
- `systemMenu.cpp` and `save.cpp`: shell and persistence behavior;
- `tatou.cpp`, `music.cpp`, `osystemAL.cpp`: sample/music behavior;
- `AITD1.cpp`: reading and intro behavior;
- `sequence.cpp`: PRESENT/ENDSEQ decoding and timing.

FITD supplies behavior and data-format truth. The Python architecture above,
especially the outer-loop modes, typed effects, continuation boundary, save
format, and accessibility options, remains native to this port.

## Planning boundary

This document defines the conclusion roadmap and contracts. It does not authorize
implementation. After review, each slice receives a separate task-level plan,
starting with M3b, and implementation proceeds one approved plan at a time.
