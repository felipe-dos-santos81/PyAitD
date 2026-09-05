# Content packs: objects — design

Date: 2026-09-04. Status: approved design. Sub-project 3 of the content-layer
programme (see `2026-09-03-content-packs-foundation-and-enemies-design.md`,
"The programme this belongs to"). Sub-projects 1 (foundation and enemies)
and 2 (controls refactor, v0.9.0) have landed.

## Goal

Let a pack place three kinds of object in the world with pack-supplied
strings: a **pickup** the hero can take and use from the inventory, a
**trigger** box that reacts when the hero walks into it, and **scenery** that
stands in the way or can be pushed. Each pickup take, inventory action and
trigger entry runs a small, fixed **effect vocabulary** — message, set flag,
clear flag, remove item, delete object — guarded by conditions on pack flags
and the inventory. Sub-project 4 (scenarios) reuses the same rules and
effects unchanged.

Decisions taken during the brainstorm:

- **A small effect vocabulary now**, not inert objects waiting for scenarios
  and not a large one. Defining rules once avoids two vocabularies later.
- **Pack-only reach.** Effects address pack objects by pack id and pack flags
  by name. Vanilla world objects, the hero's `vars`, and LIFE scripts stay
  untouched. A `vanilla:` prefix on object addresses is left open for
  sub-project 4 if scenarios need it.
- **The example pack demonstrates a key and a barricade**: taking a key sets a
  flag; entering a trigger box in front of a barricade with the key deletes
  the barricade and shows a message; without the key it shows a different
  message.

## The facts the design hinges on

Verified against the port and the real data:

- Boot-time vanilla pickups are `WorldObject`s flagged `0xa0`
  (`AF_FOUNDABLE | AF_SPECIAL`), life −1; statics are `0x20`; pushables add
  `AF_MOVABLE` (`0x10`). Touching a foundable actor opens the found modal
  (`interaction/contacts.py` → `request_found`), which already handles the
  player-only rule, the 300-tick cooldown, the weight cap
  (`position_in_track` holds an item's weight) and the inventory-full refusal.
- Taking and every inventory verb run through `execute_found_life`; with
  `found_life == -1` a take finishes directly (`_finish_take`) and nothing else
  runs. `inventory_actions` derives the verb list from `found_flag` bits, and
  `choose_inventory_action` shifts the chosen text id into `game.action`.
- Every string the found modal, the inventory and the timed messages show is
  looked up by id through `assets.system_text`. The found modal shows the
  name only; `found_body` is never rendered. The vanilla text table's highest
  id is 1150.
- Timed messages are saved as text ids. `Assets` is created once per `Game`.
- `spawn_stage_actors` places life −1 records unconditionally on their stage,
  and a record with `room == -1` (deleted or in the inventory) is never placed.
- The tick's behaviour branch (`actor.life == BEHAVIOUR_LIFE` →
  `run_behaviour`) runs in slot order in place of a LIFE, and the content
  layer may import `script.game`'s leaf modules `state` and `objects`, which
  own `delete_object`.
- `Game.content_state` is keyed by world index; the save validates one entry
  per pack record and refuses a save against a different pack digest.
- An actor with no body gets the default 200 x 2000 x 200 volume, and
  `check_object_col` considers every placed actor, so a body-less actor
  blocks the hero like an invisible pillar (probed in the attic: the hero
  stops at it with `col` naming it). Vanilla zones are room data walked by
  the hero's trigger pass, not actors.
- `request_found` refuses the prompt while `timer - track_number < 300` and
  vanilla pickups store `track_number = -1`, so a vanilla pickup cannot be
  taken in the first 300 ticks of a game.
- The hero at the attic start stands at (3231, 0, -1548) facing -z, and the
  corridor ahead is free of hard collision to at least z = -3700.

Consequence: pickups and scenery are ordinary world objects with the vanilla
flag words and no LIFE; touch, modal, weight, inventory, put, push and draw
stay vanilla. Three delegations in the interaction layer route a pack
pickup's take and verbs to the content runner. Triggers are zones stepped
once per tick by the content layer, never actors, so they occupy no volume
and no actor slot. Pack strings are registered into the assets text table
above the vanilla range, so no UI code changes.

## 1. Pack format

A pack gains an `objects/` folder, one TOML file per object, read in sorted
file order. Three kinds share the required keys `id`, `kind`, `stage`,
`room`, as enemies do. Ids are unique across the whole pack, enemies
included.

```toml
# objects/attic_key.toml
id = "attic_key"
kind = "pickup"
stage = 0
room = 0
name = "Attic key"          # shown in the found prompt and the inventory
body = 187                  # validated against both heroes' body archives
position = [3231, 0, -2248] # 700 units ahead of the attic start
beta = 0                    # optional, default 0
zv = "body"                 # max | body | cube | rotated, default "max"
weight = 1                  # optional, default 0; counts against cvars[2]
[[on_take]]                 # rules: the first whose `when` holds fires
then = [{ set_flag = "has_key" }, { message = "A small brass key." }]
[[actions]]                 # inventory verbs, in order, at most five
label = "Look"
then = [{ message = "It is warm to the touch." }]
```

```toml
# objects/barricade.toml
id = "barricade"
kind = "scenery"
stage = 0
room = 0
body = 8                    # the attic crate's body
position = [3231, 0, -3400]
beta = 0
zv = "cube"
pushable = false            # optional, default false; true adds AF_MOVABLE
```

```toml
# objects/gate.toml
id = "gate"
kind = "trigger"
stage = 0
room = 0
box = { x = [2800, 3700], y = [-500, 500], z = [-3100, -2700] }   # room coords
[[on_enter]]
when = { has_item = "attic_key" }
then = [{ delete_object = "barricade" }, { message = "The barricade gives way." },
        { delete_object = "gate" }]
[[on_enter]]
then = [{ message = "Something heavy blocks the doorway." }]
```

**Rules.** `on_take`, `on_enter` and each entry of `actions` are rules: an
optional `when` table and a required non-empty `then` array. The first rule
whose `when` holds fires; the rest are skipped. A rule with no `when` always
holds. `actions` entries also carry a non-empty `label`.

**Effects** are single-key inline tables, applied in order:

| key | value | effect |
|---|---|---|
| `message` | non-empty string | show as a timed message |
| `set_flag` | flag name | add to the pack's flag set |
| `clear_flag` | flag name | remove from the flag set |
| `remove_item` | pack id of a pickup | take it out of the inventory and delete it |
| `delete_object` | pack id of any object | delete it; a trigger may delete itself, which is how it becomes one-shot |

**Conditions** in `when` are conjunctive, each optional: `flag`, `not_flag`
(flag names), `has_item`, `not_item` (pack ids of pickups). `has_item` means
the pickup has been taken and not since removed, whichever hero's inventory
holds it.

Not in the format: `once` (delete the trigger instead), a drop or throw
verb, vanilla verbs on pack items, a found body, exit or while-inside trigger
events, and any address of a vanilla object or var.

## 2. Records, compilation, attachment

**Schema** (`engine/content/schema.py`). `parse_object(table, file)` returns
one of three frozen dataclasses, all with `id`, `kind`, `stage`, `room`,
`file`:

- `PickupRecord`: `name`, `body`, `position`, `beta`, `type_zv`, `weight`,
  `on_take: tuple[Rule]`, `actions: tuple[Action]` where
  `Action(label, rule)`.
- `SceneryRecord`: `body`, `position`, `beta`, `type_zv`, `pushable`.
- `TriggerRecord`: `box: tuple[int, int, int, int, int, int]` as
  `(x_min, x_max, y_min, y_max, z_min, z_max)`.

`Rule(when: Condition, then: tuple[Effect])`,
`Condition(flag, not_flag, has_item, not_item)` with `None` for absent
parts, and `Effect(op, arg)` with `op` in `EFFECT_OPS = ("message",
"set_flag", "clear_flag", "remove_item", "delete_object")`. Key sets are
exact per kind, as for enemies; unknown or missing keys are `PackError`s
naming the file and dotted key (`on_enter[1].then[0]`).

`Pack` gains `objects: tuple`. `read_pack` reads `objects/*.toml` after
`enemies/*.toml`, sharing the id-ownership table, then runs a pure
cross-reference pass: every `delete_object` names a pack object; every
`remove_item`, `has_item`, `not_item` names a pickup. `check_archives`
extends the both-heroes body check to pickups and scenery and the floor-room
check to every object.

**Compilation** (`engine/content/world.py`, `compile_record` dispatching on
record type). Each record becomes one appended `WorldObject`:

| kind | `flags` | `life` | `body` | other fields |
|---|---|---|---|---|
| pickup | `0xa0` (`AF_FOUNDABLE \| AF_SPECIAL`) | −1 | pack body | `found_life = -1`, `found_flag = 0`, `found_name` = its text id, `position_in_track` = weight, `type_zv` from `zv` |
| scenery | `0x20`, plus `0x10` if pushable | −1 | pack body | `type_zv` from `zv` |
| trigger | `0` | −1 | −1 | a placeholder that never spawns: `stage = -1`, `room = -1`, position 0 |

Pickups and scenery keep `obj_index = -1`, `anim = -1`, `track_mode = 0`.
Pickups carry `track_number = 0`, not the vanilla −1, so the found prompt
is not refused during the first 300 ticks of a game (see the facts above);
scenery keeps `track_number = -1`. Life −1 records ride the existing spawn
rule that places them unconditionally on their stage. A trigger's world
record exists only so that every pack object has a world index (`by_id`,
`content_state`, the save's per-record entries); its stage −1 keeps it out
of every spawn pass, and its box and room live on the record.

**Texts.** `Assets.register_texts(mapping)` adds ids to the system text
table and raises `ValueError` on any id already present. `CONTENT_TEXT_BASE
= 2000`. `allocate_texts(objects)` gives every distinct string one id,
consecutive from the base in first-seen order: for each object in pack
order, the pickup name, then each action label, then each message string
of its rules in rule order (`on_take` rules, then each action's rule, or
`on_enter` rules). A string seen twice keeps its first id. Attach registers
the table and keeps the string-to-id map as `ContentAttachment.text_ids`;
compilation sets `found_name` from it and `message` effects look their
string up at run time. Because the order is a pure function of the pack, a
saved timed-message id resolves to the same string after a load.

**Attachment.** `attach` appends enemies then objects. `ContentAttachment`
keeps `records` (world index → record) and gains `by_id` (pack id → world
index), `text_ids` (string → text id) and `flags: set[str]`, seeded empty.
`content_state` per record: enemies `{"hp", "phase"}` as today; triggers
`{"armed": True, "inside": False}`; pickups and scenery `{}`.

## 3. Runtime

**`engine/content/objects.py`** owns the vocabulary at run time:

- `holds(game, condition) -> bool`. Flags come from `game.content.flags`.
  `has_item`/`not_item` read the world record's in-inventory bit
  (`found_flag & 0x8000`), which `_finish_take` sets and
  `remove_from_inventory` clears, so content never touches the inventory
  table.
- `run_rules(game, rules) -> bool` applies the first matching rule's effects
  in order and reports whether one fired. `message` calls
  `game.add_message(text_ids[string])`; `set_flag`/`clear_flag` edit the
  flag set; `remove_item` and `delete_object` on a pickup or scenery call
  `script.game.objects.delete_object` on the target's world index, which
  un-places the record (room and stage −1, actor released) and pulls it
  from the inventory. A deleted record never respawns and needs no separate
  state; deleting an already-deleted record is a no-op. `delete_object` on a
  trigger sets its `armed` state to false.
- `step_triggers(game)`: once per tick, for every armed trigger: take the
  camera-target hero; no hero, another floor or another room counts as
  outside. Inside means the hero's `room_x/room_y/room_z` lie within the
  box, bounds inclusive. Fire `on_enter` only on the edge from outside to
  inside; store the new value in `state["inside"]` before running the
  rules. A disarmed trigger is skipped and keeps its `inside` value.
- `pickup_at(game, world_idx) -> PickupRecord | None` is the single test
  the interaction hooks use.
- `action_ids(game, world_idx) -> tuple[int]`: the pickup's action text ids
  in file order.
- `take(game, world_idx)`: run `on_take`.
- `use(game, world_idx, text_id)`: set `in_hand_table[current_inventory]`,
  run the matching action's rule; `ValueError` for an id the pickup does not
  expose.

**Three delegations in `engine/script/interaction`**, each guarded by
`pickup_at`:

1. `execute_found_life`: for a pack pickup, on `AfterLife.FINISH_TAKE` call
   `_finish_take` then `take`; otherwise nothing. Returns `True` (no LIFE
   frame, no modal). `on_take` therefore sees the item in the inventory.
2. `inventory_actions`: a pack pickup lists `action_ids`.
3. `choose_inventory_action`: a pack pickup routes to `use` and returns
   `True`.

**The tick.** `play_tick` calls `step_triggers` right after the per-actor
LIFE and behaviour loop, when no floor change is pending, so a trigger fires
in the same tick as the step that entered it and before the game-over
handoff. `run_behaviour` is unchanged: only enemies have behaviour actors.
The trace logs a trigger transition through `log_behaviour` with the
trigger's world index in the actor column and `enter` or `leave` in the
phase column.

**Message primitive.** `_add_message` moves from
`interaction/life_cont.py` to `Game.add_message(message_id)` in
`script/game/state.py`, unchanged in behaviour (refresh the age of a
duplicate, else fill the first free slot). The LIFE effect drain calls the
method.

Touch, the found modal, weight refusal, the cooldown, pushing and drawing
are untouched vanilla code.

## 4. Save and load, validation, errors

**Save schema 4.** The world-object array already carries every pack
record's position, room and in-inventory bit. Additions:

- `content_state` validated per record type: enemies `hp` (int) and `phase`
  (in `PHASES`); triggers exactly `armed` and `inside` (bools); pickups and
  scenery an empty object. The count check becomes one entry per pack record, enemies
  and objects together (`first_index .. first_index + len(enemies) +
  len(objects) - 1`).
- New top-level key `content_flags`: the sorted list of set flag names, `[]`
  without a pack. Load rejects a non-empty list without a pack, non-string
  entries and duplicates. Flag names are free strings and are not checked
  against the pack.

A schema-3 save is refused by the existing schema check. The pack digest
check already refuses a save against a changed pack, so saved text ids stay
valid.

**Load-time validation** raises `PackError(file, key, message)` in this
order: TOML shape and exact key sets per kind; ranges (int16 positions and
box bounds, `min <= max` on each box axis, `weight >= 0`, at most five
actions, non-empty `name`, `label`, `message`, `then`; a pickup's action
labels must be unique); effects and
conditions are single-key tables from the fixed vocabulary; then the
cross-reference pass over the whole pack. Archive checks follow as in
section 2. `register_texts` collisions raise at attach; a test pins that no
vanilla text id reaches 2000.

**Runtime errors.** `run_rules` and `step_triggers` never raise on game
state. `use` with an unknown id raises `ValueError`, matching the vanilla
inventory's contract.

## 5. Example pack and tests

**Example pack** adds `objects/attic_key.toml`, `objects/barricade.toml`,
`objects/gate.toml` as in section 1, all on stage 0 room 0 beside the two
enemies, on the straight walk ahead of the attic start (facing −z): the key
700 units ahead, the gate box from 1150 to 1550 ahead, the barricade 1850
ahead. World indices: 292–293 enemies, 294 key, 295 barricade, 296 gate
(sorted file order: `attic_key`, `barricade`, `gate`). The enemy tests keep
their indices; object journeys delete both enemies at boot so the prowler
cannot reach the hero mid-scene.

**Unit tests** (`tests/test_content_objects.py`, extensions of
`tests/test_content_pack.py`), no game data:

- parse each kind, defaults, exact key sets; every failure names file, key
  and value (parametrised like the enemy table);
- cross-reference failures: unknown `delete_object`, `has_item` naming
  scenery, an id shared with an enemy, six actions;
- `holds` over every condition and `run_rules` first-match semantics on a
  stub game;
- compile shapes per kind: flag words, life values, weight in
  `position_in_track`, trigger at the box centre;
- text registration: ids from 2000 in pack order, duplicate message strings
  share an id, refusal on collision; the vanilla-below-2000 pin (real data).

**Journey tests** (real data, the existing `_boot`/`_tick_until` helpers):

- touching the key opens the found modal whose name resolves to "Attic key";
  accepting takes it, sets `has_key`, and leaves a timed message whose id
  resolves to the pack string;
- the inventory lists the pack action; choosing it shows its message;
- entering the gate box without the key shows the blocking message; a
  unit-stepped test with the hero relocated proves it fires again on
  re-entry and never while standing inside;
- with the key, entering deletes the barricade and the gate: both records
  have room −1 and no actor;
- one real-loop test through `shell.run()` with the monkeypatched event
  pump, as the controls golden does, drives the key-and-barricade scene by
  pointer clicks;
- save round trip mid-scene: schema 4, `content_flags` and the trigger's
  `armed`/`inside` restore, a schema-3 save is refused, the key stays in
  the inventory after load.

**Existing tests touched**: the save-schema constant and the content-state
fixtures in `tests/test_save*.py`; the Makefile test list gains the new file
(the path-exists check covers it). The layering forbidden list is unchanged.

## 6. Docs, version, layering

- Version 0.10.0 in `pyproject.toml`, `PyAitD/__init__.py` and
  `CONTEXT.md`.
- README: the pack section grows the `objects/` folder, the three kinds and
  the example scene. AGENTS.md: one convention bullet (pack strings live in
  the assets text table from id 2000; UI code never special-cases packs).
  CONTEXT.md records the pack-only reach decision.
- Seams for sub-project 4: `run_rules`, `holds`, `Effect`, `Condition` and
  `ContentAttachment.by_id`/`flags` are the director's building blocks; the
  `vanilla:` address prefix is reserved, not implemented.
- Layering: no new forbidden-list entries. The one new import direction,
  `script.interaction` → `content`, matches what `script.playworld.tick`
  already does (the tick also gains the `step_triggers` call); `content` still imports only `script.game.state` and
  `script.game.objects` from the game package, and `data.assets` for text
  registration.

## Invariants

- With no pack attached the game ticks and saves byte-identically to today
  (the existing empty-pack and no-pack equivalence tests extend to objects).
- Vanilla objects, `vars`, LIFE and TRACK scripts are never read or written
  by pack effects.
- Every pack string reaches the screen through `assets.system_text`.
- A pack loads fully or not at all; every failure names file, key and value.
- No new runtime dependency; SPDX first line on new files; absolute imports;
  no compatibility shims.

## Out of scope

Dropping or throwing pack items; vanilla verbs on pack items; found bodies;
triggers firing on exit or while inside; effects on vanilla objects or
vars; any change to the enemy vocabulary; pack-supplied bodies or
animations (bodies are indices into the game's archives, as for enemies).
