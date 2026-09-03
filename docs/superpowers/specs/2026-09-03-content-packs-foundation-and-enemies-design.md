# Content packs: foundation and enemies — design

Date: 2026-09-03. Status: approved design. Sub-project 1 of the content-layer
programme below.

## Goal

Let new gameplay content be added to the AITD1 port without editing the
engine or the original game data: enemies, objects, scenarios and player
variants authored as data files with a fixed vocabulary, run by Python
behaviours that call the same primitives the LIFE opcodes call. The original
LIFE and TRACK scripts stay authoritative for every original actor; with no
pack attached the game is byte-identical to today.

This sub-project builds the foundation (pack format, loader, world-object
attachment, the behaviour pass, save/load, CLI) and the first vocabulary:
two enemy kinds.

## The programme this belongs to

Chosen shape: **content is more world objects, plus one behaviour branch**.
Rejected: compiling packs to LIFE bytecode (capped at the 87 AITD1 opcodes,
no home for player variants or controls) and a separate content simulation
(two collision worlds).

Build order, each with its own spec, plan and green `make test`:

1. **Foundation + enemies** — this document.
2. **Controls refactor** — move pointer, cursor, bindings and event routing
   out of `app/shell.py` (1976 lines) and `app/ui.py` (1613) into
   `app/controls/`. Independent of content.
3. **Objects** — `pickup`, `trigger`, `scenery`, with pack-supplied names.
4. **Scenarios** — a director running `when -> then` rules; alternate starts.
5. **Player variants**, then **pack-contributed bindings** (needs 2 and 5).

The five names appear twice, mirrored: as the engine's fixed vocabulary
(`engine/content/{enemies,objects,scenarios,players}.py`, `app/controls/`)
and as a pack's folders (`enemies/ objects/ scenarios/ players/ controls/`).

## The fact the design hinges on

Every opcode that makes an actor *do* something is a thin wrapper over an
engine primitive: `op_move` is `init_deplacement`, `op_anim_repeat` is
`init_anim`, `op_hit` and `op_fire` set six fields after `init_anim`
accepts, `LM_DO_MOVE` is `process_track`. A data-driven behaviour calls the
same primitives, so content actors ride the same collision, animation,
camera and spawn code as the originals. There is no second physics or
animation path to drift.

## 1. Pack format

A pack is one directory. Only TOML, read with the stdlib `tomllib`
(`requires-python >= 3.12`), so no new dependency.

```
packs/example/
  pack.toml
  enemies/prowler.toml      one enemy per file
  enemies/watcher.toml
```

`pack.toml`:

```toml
name = "example"
version = "1"
game = "aitd1"        # must equal profile.name
```

An enemy record. Every number is in the units OBJETS.ITD already uses, so an
author can copy from an original creature:

```toml
id = "prowler"                 # unique in the pack
kind = "pursuer"               # v1 vocabulary: pursuer | sentry
body = 24                      # body index in the loaded body archive
stage = 0
room = 0
position = [1500, 0, -3000]    # room-local, s16
beta = 0                       # facing, 0..1023
zv = "max"                     # max | body | cube | rotated  -> type_zv 0..3
life_mode = "room"             # room | stage                 -> 1 | 0
falls = false                  # AF_FALLABLE, as floor 5's enemy 222 has
hit_points = 4

[anims]                        # anim indices in the loaded anim archive
stand = 19
walk = 23                      # a sentry omits walk
attack = 17
hurt = 20
death = 22

[attack]                       # the six HIT operands, plus when to use it
frame = 3
group = 1
radius = 1000
force = 1
range = 1200                   # calc_dist to the hero below which the strike is armed
```

Validation happens at load, before anything touches a `Game`: unique ids,
enum spellings, s16 ranges, `body < num_bodies` and every anim `< num_anims`
for **both** hero archives (Carnby's and Emily's paks differ in count, and a
character switch must not fail later), and stage and room existing in the
floor archive. Each failure names the file, the key and the offending value.

Not in v1, each a future vocabulary word rather than a schema change:
sounds, messages, randomness, custom bodies, per-frame scripting.

## 2. Engine attachment

**Appended world objects.** `Game.__init__` gains `pack=None` and only
stores it; `init_game` calls `content.attach(game, pack)`, which compiles
each enemy record to one `WorldObject` appended after the OBJETS records
(292 for AITD1):

| field | value |
|---|---|
| `obj_index` | -1 |
| `body`, `x`, `y`, `z`, `beta`, `stage`, `room`, `type_zv`, `life_mode` | from the record |
| `flags` | `AF_ANIMATED \| 0x20`, plus `AF_FALLABLE` when `falls` |
| `anim`, `anim_type`, `anim_info` | `anims.stand`, 1 (repeat), -1 — spawns standing, as enemy 222 is stored |
| `track_mode`, `track_number`, `position_in_track` | 0, -1, 0 |
| `life` | `BEHAVIOUR_LIFE = -2` |
| everything else (`found_*`, `floor_life`, `alpha`, `gamma`, `frame`, `mark`) | -1 / 0 as an inert original record has |

`game.content` is a `ContentAttachment(pack, records)` with `records` keyed
by world index; `None` when no pack is attached. Every original record has
`life >= -1` (pinned by a test over the real OBJETS.ITD), so the sentinel
collides with nothing.

**Spawn, collision, camera, rendering: untouched.** `spawn_stage_actors`
keys on `life != -1` and `life_mode` to decide stage-kept versus room-kept,
so a content enemy spawns and despawns exactly like world object 21 does.
`add_actor`, `gere_anim`, `gere_collision`, `gere_frappe`, `_camera_switch`
and both renderers see an ordinary animated actor.

**One gate change.** `life_gate` becomes
`actor.life >= 0 and actor.life_mode != -1`, so the VM never fetches script
`-2`. The per-actor loop in `play_tick` gains one branch, in the same slot
order:

```python
if life_gate(actor):
    if not run_life(game, LifeFrame(index, actor.life)): ...
elif actor.life == BEHAVIOUR_LIFE:
    run_behaviour(game, index)
```

Slot order, not a separate pass: a content enemy sees `hit_by` and `col_by`
at the same point in the tick a scripted enemy at that slot would.

**Primitives, not new mechanics.** A behaviour calls only what opcodes call:
`init_deplacement(actor, 2, game.current_world_target)` and `process_track`
for the chase (the pair `LM_MOVE` + `LM_DO_MOVE` make), `init_anim` for
stand/walk/hurt/death, `eval_var.calc_dist` for range (the DISTANCE tag's
own function), `delete_object` for the corpse, and the turn
`_process_track_follow` uses for facing.

**One extraction.** The six-field arming block inside `op_hit` moves to
`engine/actor/anim_action.py` as
`arm_strike(actor, anim, frame, group, radius, force, next_anim) -> bool`
(returns `init_anim`'s acceptance); `op_hit` calls it and its existing tests
keep passing. One implementation of a strike for scripts and packs alike.

**Per-object state.** `game.content_state[world_idx] = {"hp": int, "phase":
str}`, keyed by world index like the original `vars[]`, so it survives the
despawn/respawn a room change causes. Created at attach with `hp =
hit_points`, `phase = "idle"`.

## 3. Behaviour semantics

One state machine for both kinds. Transitions are evaluated once per tick in
this order: damage check, then the phase's own rule.

| Phase | Enters when | Each tick | Leaves when |
|---|---|---|---|
| `idle` | spawn; after `hurt`/`attack` for a sentry | sentry: turn toward the hero with `_process_track_follow`'s turn once the hero is within `2 * attack.range`. pursuer: nothing | pursuer: immediately -> `chase`. sentry: hero within `range` -> `attack` |
| `chase` | pursuer only | on entry `init_deplacement(2, hero)` + walk anim repeating; every tick `process_track`. Crosses rooms only when `life_mode = stage`, via the room-link aim that already exists | `calc_dist(hero) < range` and `arm_strike` accepts -> `attack` |
| `attack` | from `idle` or `chase` | on entry `arm_strike(attack, frame, group, radius, force, next_anim = stand)`, `track_mode = 0`, `speed = 0` (no sliding mid-swing). `gere_frappe` publishes the hit; the hero's own LIFE takes the damage | `flag_end_anim` -> pursuer `chase`, sentry `idle` |
| `hurt` | `hit_by != -1` and `hp` still above 0 | first, from every phase but `dying`: `hp -= actor.hit_force`. A hit during `hurt` or `attack` still counts; the anim is not restarted. Then hurt anim once with next anim stand, `track_mode = 0`, `speed = 0` | `flag_end_anim` -> pursuer `chase`, sentry `idle` (an interrupted strike is not resumed) |
| `dying` | `hp <= 0` | death anim once (`anim_info = -1`), `track_mode = 0`, `speed = 0` | `flag_end_anim` -> `delete_object(game, world_idx)` (sets the record's stage to -1, so it never respawns), phase `dead` |

A hurt or death anim replacing the strike anim disarms the strike on the
next `gere_frappe` (animAction.cpp:25-34, already ported), so neither phase
clears `anim_action_type` by hand.

Hit points and phase both survive a room change and the despawn/respawn it
causes (keyed by world index, like the original `vars[]`); a respawned
enemy resumes the phase it was in. No randomness in v1, so a headless run
is bit-reproducible. The pursuer's follow speed is FITD's fixed 4
(`_process_track_follow`).

## 4. Save and load

- **Schema 3.** `SCHEMA` 2 -> 3. Schema 2 saves are refused with the existing
  "expected schema 3, got 2" message, the policy already applied to a version
  change.
- **Pack identity in `source`.** `source` gains `"pack": null` or
  `{"name", "version", "digest"}`; the digest is SHA-256 over every TOML
  file's bytes in sorted relative-path order. A load requires the attached
  pack to match name and digest exactly. A save made with a pack cannot load
  vanilla, a vanilla save cannot load with a pack, and an edited pack
  invalidates its saves. All three fail in `validate_snapshot`, before
  anything live is touched, naming what differed.
- **World objects.** `_validate_world_objects` expects
  `OBJETS count + pack record count`. Appended records ride in
  `world_objects` like any other, so a killed enemy's `stage = -1` and its
  `life = -2` come back with no special code.
- **New block `content_state`.** `{str(world_idx): {"hp", "phase"}}`,
  validated for keys inside the pack's index range, integer `hp`, and a
  phase from the fixed set. Absent when no pack is attached; its presence
  without a pack, or absence with one, is a validation failure.
- **Restore.** `validate_snapshot`, `read_slot` and `restore_game` each gain
  `pack=None`; `restore_game(data_dir, profile, payload, pack=None)` builds
  `init_game(..., pack=pack)` before applying the snapshot, then assigns
  `content_state`. Anim players for content actors restore by actor slot
  like everyone else's.

## 5. App, CLI and error handling

- **`--content DIR`**: one pack directory holding `pack.toml`;
  `make run content=DIR`. No default; without the flag the game is vanilla.
  CLI-only: never written to settings, no menu row.
- **Loaded before the window opens.** `main()` calls
  `load_pack(path, data_dir, profile)`. Any failure raises
  `PackError(file, key, message)`; `main()` prints
  `content pack error: enemies/prowler.toml: anims.walk: 999 is not below 305`
  to stderr and exits with status 2. A pack is never partially applied and
  never silently ignored: a missing texture has the original asset as a
  complete substitute, a missing enemy has none.
- **The pack rides on the `Game`** as `game.content`, not on the session.
  The shell's three `init_game` sites (restart, character select, boot) and
  its `restore_game` site pass `pack=` from the game being replaced, so new
  game, restart and load keep the process's pack with no session field.
- **Save mismatch** surfaces through the existing path: `read_slot` returns
  the `SaveError` text, the shell shows the existing "Could not load" notice,
  the running game is untouched.
- **Runtime.** Behaviours never raise on game state. Slot exhaustion in
  `add_actor` leaves a record unspawned until the next regeneration, what
  happens to an original record today. The LIFE `Trace` gains one line form,
  `timer actor BEHAVIOUR phase`, so `make run trace=` covers packs.

## 6. Layout, layering, tests, docs

```
PyAitD/engine/content/
  __init__.py   BEHAVIOUR_LIFE, load_pack, attach, PackError, run_behaviour
  schema.py     record types, enums, s16/range validation
  pack.py       directory reader (tomllib), digest, PackError with file + key
  world.py      record -> WorldObject; ContentAttachment
  runner.py     run_behaviour(game, slot) + the trace line
  enemies.py    pursuer and sentry phases
packs/example/  pack.toml, enemies/prowler.toml (pursuer), enemies/watcher.toml (sentry)
```

Dependency direction: `content` imports `data`, `space`, `actor`,
`script.game.state` and `script.game.objects` (the leaf modules, never the
`script.game` package, whose `__init__` imports `boot` and so would be
mid-initialisation when `boot` imports `content`), `script.effects`,
`script.eval_var` (for `calc_dist`), `script.life` (for `Trace`). It may not
import `script.playworld`, `script.interaction`, `nav`, `games`, or the
presentation layer. `script/playworld/tick.py`, `script/game/boot.py` and
`script/save.py` import it. `test_layering.py` gains the `engine/content`
`FORBIDDEN` entry and a `PRESENTATION_FREE` row for `PyAitD.engine.content`.

Tests (markers per `AGENTS.md`; real-data tests skip without data):

- `tests/test_content_pack.py` (engine): a validation matrix where every bad
  record fails naming file, key and value; digest stable under file order;
  field-by-field compile of a record to a `WorldObject`; no real OBJETS
  record carries `life < -1`.
- `tests/test_content_enemies.py` (engine, journey): the example pack on a
  real attic boot. The prowler spawns at its position, enters `chase`,
  closes on the hero, arms a strike inside `range`; a published hit drops
  `hp`, `hurt` plays, the last hit reaches `dying`, deletion sets
  `stage = -1`, and leaving and re-entering the room does not respawn it.
  The watcher never changes position and turns toward the hero. Vanilla
  invariance: no pack gives 292 records; a fixed-length attic run with no
  pack and with an *empty* pack produce identical actor snapshots tick for
  tick.
- `tests/test_save.py`: schema 3, `source.pack`, the three mismatch
  messages, `content_state` round-trip mid-chase.
- Existing `op_hit` tests pass with `op_hit` delegating to `arm_strike`; a
  shell test covers `--content` parsing, the exit-2 path, and that a restart
  keeps the pack.

Docs and build: `Makefile` gains `content=` on `run`; `CONTEXT.md` gets the
`engine/content/` row and a "Content packs boundary" section; `AGENTS.md`
and `README.md` gain the flag and a short "Content packs" section.

## Invariants

- `make test` green after every stage; `make test-journey` with real data.
- With no pack: 292 world objects, `life_gate` behaviour unchanged on every
  real record, goldens verbatim, `ponytail:` comments and FITD citations
  untouched.
- No new dependency (`tomllib` is stdlib). SPDX first line on every new
  file. Absolute imports only. No compatibility shims.
- Behaviours use no RNG in v1; if one is ever needed it is `game.rng`.

## Sequencing

1. **Extraction + gate.** `arm_strike` out of `op_hit`; `life_gate` to
   `>= 0`; the `life < -1` data pin. Vanilla-only, green.
2. **Pack loader.** `schema.py`, `pack.py`, validation matrix, digest,
   example pack files. No engine wiring yet.
3. **Attachment.** `world.py`, `Game(pack=)`, `attach` in `init_game`,
   `content_state`, the 292-vs-appended pins, the empty-pack invariance
   golden.
4. **Behaviours.** `enemies.py`, `runner.py`, the tick branch, the trace
   line; the prowler and watcher journeys.
5. **Save/load.** Schema 3, `source.pack`, `content_state`, mismatch
   messages, round-trip.
6. **App.** `--content`, `make run content=`, exit-2 path, the four
   pass-through sites, docs.
