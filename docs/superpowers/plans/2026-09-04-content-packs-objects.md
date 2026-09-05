# Content Packs: Objects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a content pack place pickups, scenery and trigger zones in the world with pack-supplied strings, each running a five-effect rule vocabulary (message, set flag, clear flag, remove item, delete object) guarded by flag and inventory conditions, with save/load and a key-and-barricade example scene.

**Architecture:** Pickups and scenery compile to ordinary `WorldObject`s with the vanilla flag words and no LIFE, so touch, the found prompt, weight, inventory, push and draw stay vanilla; three guarded delegations in the interaction layer route a pack pickup's take and verbs to `engine/content/objects.py`. Triggers are zones stepped once per tick from never-spawned placeholder records. Pack strings are registered into the assets text table from id 2000, so no UI code changes.

**Tech Stack:** Python 3.12 (`tomllib`), pytest, the pygame-free `PyAitD/engine`. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-04-content-packs-objects-design.md`

## Global Constraints

- `# SPDX-License-Identifier: GPL-2.0-only` is the first line of every new `.py` file (`tests/test_layering.py::test_every_python_file_starts_with_the_spdx_line`).
- Absolute imports only; no relative imports anywhere in `PyAitD/`. No compatibility shims.
- Every test file declares exactly one subject marker (`engine`, `render`, `shell`, `tools`, `meta`) as module-level `pytestmark`, plus `journey` for long real-data runs.
- Tests take game data from the `data_dir` fixture, the profile from the `profile` fixture and the example pack from `example_pack_dir`; never import `AITD1` directly outside `tests/test_game_profile.py`.
- Run pytest headless: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest ...`. `make test` is the gate after every task.
- No new runtime dependency: pygame-ce + moderngl + numpy stay the whole set.
- `engine/content` may import `PyAitD.engine.data`, `.space`, `.actor`, `.script.game.state`, `.script.game.objects`, `.script.effects`, `.script.eval_var`, `.script.life`. Never `.script.playworld`, `.script.interaction`, `.nav`, `PyAitD.games`, the presentation layer, or the `PyAitD.engine.script.game` package itself (`tests/test_layering.py` pins all of it).
- Pack effects reach pack state only: never a vanilla world object, `game.vars`, or a LIFE script.
- Every pack string reaches the screen through `assets.system_text`; UI code never special-cases packs.
- With no pack attached the game ticks and saves byte-identically (`tests/test_content_pack.py::test_an_empty_pack_ticks_identically_to_no_pack`). Never re-record `tests/golden/controls_events.json`.
- Never mass-reformat. No lint or typecheck is configured; the suite is the only gate.
- Commit messages end with the session's attribution trailer:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Wr26qgHgbV5RqX5VHn6Tjf
  ```
- Real numbers used throughout come from the real data: OBJETS.ITD has 292 records, the example pack's enemies are world 292 (prowler) and 293 (watcher), both hero body archives hold 272 bodies, the vanilla text table's highest id is 1150, the attic is floor 0 room 0, the hero starts at room coordinates (3231, 0, −1548) facing −z and walks about 25 units a tick in keyboard mode, body 187 is the oil can (zv x ±43, z ±100) and body 8 the attic crate (zv x −220..240, z ±220), `request_found` refuses the prompt while `timer - track_number < 300`, and `_finish_take` sets `found_flag` bit `0x8000`.

---

## File map

| File | Responsibility |
|---|---|
| `PyAitD/engine/content/schema.py` | gains `OBJECT_KINDS`, `EFFECT_OPS`, `CONDITION_KEYS`, `MAX_ACTIONS`, `Condition`, `ALWAYS`, `Effect`, `Rule`, `Action`, `PickupRecord`, `SceneryRecord`, `TriggerRecord`, `parse_object`; `parse_enemy` shares `_parse_position`/`_parse_beta` |
| `PyAitD/engine/content/pack.py` | `Pack.objects`, `objects/*.toml` in `read_pack`, `check_references`, `check_archives` over objects |
| `PyAitD/engine/content/world.py` | `CONTENT_TEXT_BASE`, `allocate_texts`, `compile_record` per kind, `initial_state`, `ContentAttachment.by_id/text_ids/flags`, `attach` registers texts |
| `PyAitD/engine/content/objects.py` | new: `holds`, `run_rules`, `pickup_at`, `action_ids`, `take`, `use`, `step_triggers` |
| `PyAitD/engine/content/__init__.py` | re-exports the new names |
| `PyAitD/engine/data/assets.py` | `Assets.register_texts(texts)` |
| `PyAitD/engine/script/game/state.py` | `Game.add_message(message_id)` (moved from `life_cont._add_message`) |
| `PyAitD/engine/script/interaction/life_cont.py` | `execute_found_life` delegates a pack pickup's take; `_add_message` removed |
| `PyAitD/engine/script/interaction/inventory.py` | `inventory_actions` and `choose_inventory_action` delegate for pack pickups |
| `PyAitD/engine/script/playworld/tick.py` | `step_triggers(game)` after the per-actor loop |
| `PyAitD/engine/script/save.py` | `SCHEMA = 4`, `content_flags`, per-kind `content_state` validation and restore |
| `packs/example/objects/{attic_key,barricade,gate}.toml` | the key-and-barricade scene |
| `pyproject.toml`, `PyAitD/__init__.py`, `CONTEXT.md`, `README.md`, `AGENTS.md` | version 0.10.0 and the docs |
| `tests/test_content_pack.py` | schema, reader, references, archives, texts, compile, attach |
| `tests/test_content_objects.py` | new: the rule engine on a stub, the pickup/trigger journeys, the mid-scene save |
| `tests/test_content_objects_loop.py` | new: the scene through the real `shell.run` pump |
| `tests/test_save.py`, `tests/test_main.py`, `tests/test_runtime_modes.py` | count and schema pins updated in Task 4 |

---

### Task 1: Object records and `parse_object`

Pure schema work: the three record kinds, rules, conditions and effects, parsed and range-checked. No reader change yet.

**Files:**
- Modify: `PyAitD/engine/content/schema.py`
- Test: `tests/test_content_pack.py`

**Interfaces:**
- Consumes: the existing helpers `_require`, `_s16`, `_non_negative`, `_choice`, `_reject_unknown`, `PackError`, `ZV_TYPES`.
- Produces: `parse_object(table, file) -> PickupRecord | SceneryRecord | TriggerRecord`; `Condition(flag, not_flag, has_item, not_item)`, `ALWAYS`, `Effect(op, arg)`, `Rule(when, then)`, `Action(label, rule)`; every record has `id`, `kind`, `stage`, `room`, `file` and a `rules()` method returning `((dotted_key, Rule), ...)`; constants `OBJECT_KINDS`, `EFFECT_OPS`, `CONDITION_KEYS`, `MAX_ACTIONS`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_content_pack.py`, after the enemy section (before `# ── the directory reader`), importing the new names at the top of the file:

```python
from PyAitD.engine.content.schema import (
    ALWAYS, Action, Condition, Effect, PickupRecord, Rule, SceneryRecord, TriggerRecord, parse_object,
)
```

```python
# ── object records ───────────────────────────────────────────────────────────

KEY = {
    "id": "attic_key", "kind": "pickup", "stage": 0, "room": 0,
    "name": "Attic key", "body": 187, "position": [3231, 0, -2248], "beta": 0,
    "zv": "body", "weight": 1,
    "on_take": [{"then": [{"set_flag": "has_key"}, {"message": "A small brass key."}]}],
    "actions": [{"label": "Look", "then": [{"message": "It is warm to the touch."}]}],
}
BARRICADE = {
    "id": "barricade", "kind": "scenery", "stage": 0, "room": 0,
    "body": 8, "position": [3231, 0, -3400], "beta": 0, "zv": "cube", "pushable": False,
}
GATE = {
    "id": "gate", "kind": "trigger", "stage": 0, "room": 0,
    "box": {"x": [2800, 3700], "y": [-500, 500], "z": [-3100, -2700]},
    "on_enter": [
        {"when": {"has_item": "attic_key"},
         "then": [{"delete_object": "barricade"}, {"message": "The barricade gives way."},
                  {"delete_object": "gate"}]},
        {"then": [{"message": "Something heavy blocks the doorway."}]},
    ],
}


def _object(base, **changes):
    table = copy.deepcopy(base)
    for key, value in changes.items():
        if value is None:
            table.pop(key, None)
        else:
            table[key] = value
    return table


def test_parse_object_builds_each_kind():
    key = parse_object(KEY, "objects/attic_key.toml")
    assert key == PickupRecord(
        id="attic_key", kind="pickup", stage=0, room=0, name="Attic key", body=187,
        position=(3231, 0, -2248), beta=0, type_zv=1, weight=1,
        on_take=(Rule(ALWAYS, (Effect("set_flag", "has_key"), Effect("message", "A small brass key."))),),
        actions=(Action("Look", Rule(ALWAYS, (Effect("message", "It is warm to the touch."),))),),
        file="objects/attic_key.toml",
    )
    assert parse_object(BARRICADE, "b.toml") == SceneryRecord(
        id="barricade", kind="scenery", stage=0, room=0, body=8, position=(3231, 0, -3400),
        beta=0, type_zv=2, pushable=False, file="b.toml",
    )
    gate = parse_object(GATE, "g.toml")
    assert gate == TriggerRecord(
        id="gate", kind="trigger", stage=0, room=0, box=(2800, 3700, -500, 500, -3100, -2700),
        on_enter=(
            Rule(Condition(has_item="attic_key"), (
                Effect("delete_object", "barricade"), Effect("message", "The barricade gives way."),
                Effect("delete_object", "gate"))),
            Rule(ALWAYS, (Effect("message", "Something heavy blocks the doorway."),)),
        ),
        file="g.toml",
    )


def test_parse_object_defaults_beta_zv_weight_rules_and_pushable():
    key = parse_object(_object(KEY, beta=None, zv=None, weight=None, on_take=None, actions=None), "k.toml")
    assert (key.beta, key.type_zv, key.weight, key.on_take, key.actions) == (0, 0, 0, (), ())
    assert parse_object(_object(BARRICADE, pushable=None, beta=None, zv=None), "b.toml").pushable is False


def test_records_enumerate_their_rules_in_text_order():
    key, barricade, gate = (parse_object(t, "f") for t in (KEY, BARRICADE, GATE))
    assert [k for k, _ in key.rules()] == ["on_take[0]", "actions[0]"]
    assert key.rules()[1][1] is key.actions[0].rule
    assert barricade.rules() == ()
    assert [k for k, _ in gate.rules()] == ["on_enter[0]", "on_enter[1]"]


@pytest.mark.parametrize("base, changes, key, message", [
    (KEY, {"kind": "door"}, "kind", "'door' is not one of pickup, scenery, trigger"),
    (KEY, {"extra": 1}, "extra", "unknown key"),
    (KEY, {"pushable": True}, "pushable", "unknown key"),
    (KEY, {"name": ""}, "name", "expected a non-empty string, got ''"),
    (KEY, {"stage": None}, "stage", "missing"),
    (KEY, {"weight": -1}, "weight", "-1 is negative"),
    (KEY, {"position": [1, 2]}, "position", "expected [x, y, z], got [1, 2]"),
    (KEY, {"beta": 1024}, "beta", "1024 is outside 0..1023"),
    (KEY, {"on_take": {"then": []}}, "on_take", "expected an array of tables"),
    (KEY, {"on_take": [{"then": []}]}, "on_take[0].then", "expected a non-empty array of effects, got []"),
    (KEY, {"on_take": [{"then": [{"explode": "x"}]}]}, "on_take[0].then[0].explode",
     "unknown effect; expected one of message, set_flag, clear_flag, remove_item, delete_object"),
    (KEY, {"on_take": [{"then": [{"message": "a", "set_flag": "b"}]}]}, "on_take[0].then[0]",
     "expected a table with exactly one key"),
    (KEY, {"on_take": [{"then": [{"message": ""}]}]}, "on_take[0].then[0].message",
     "expected a non-empty string, got ''"),
    (KEY, {"on_take": [{"when": {"near": "x"}, "then": [{"message": "a"}]}]}, "on_take[0].when.near", "unknown key"),
    (KEY, {"on_take": [{"when": {"flag": 3}, "then": [{"message": "a"}]}]}, "on_take[0].when.flag",
     "expected a non-empty string, got 3"),
    (KEY, {"on_take": [{"label": "x", "then": [{"message": "a"}]}]}, "on_take[0].label", "unknown key"),
    (KEY, {"actions": [{"then": [{"message": "a"}]}]}, "actions[0].label", "missing"),
    (KEY, {"actions": [{"label": "a", "then": [{"message": "a"}]}] * 6}, "actions",
     "6 actions is more than the inventory shows (5)"),
    (BARRICADE, {"pushable": "yes"}, "pushable", "expected true or false, got 'yes'"),
    (BARRICADE, {"name": "x"}, "name", "unknown key"),
    (GATE, {"box": {"x": [0, 1], "y": [0, 1]}}, "box", "expected a table with the keys x, y, z"),
    (GATE, {"box": {"x": [0], "y": [0, 1], "z": [0, 1]}}, "box.x", "expected [min, max], got [0]"),
    (GATE, {"box": {"x": [5, 1], "y": [0, 1], "z": [0, 1]}}, "box.x", "min 5 is above max 1"),
    (GATE, {"box": {"x": [0, 40000], "y": [0, 1], "z": [0, 1]}}, "box.x[1]", "40000 is outside -32768..32767"),
    (GATE, {"on_enter": []}, "on_enter", "expected at least one rule"),
    (GATE, {"body": 3}, "body", "unknown key"),
])
def test_parse_object_names_file_key_and_value_on_every_failure(base, changes, key, message):
    with pytest.raises(PackError) as caught:
        parse_object(_object(base, **changes), "o.toml")
    assert (caught.value.file, caught.value.key) == ("o.toml", key)
    assert message in caught.value.message
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_pack.py -q -k "parse_object or enumerate_their_rules"`
Expected: FAIL at import (`cannot import name 'parse_object'`).

- [ ] **Step 3: Add the vocabulary, the records and the parsers**

In `PyAitD/engine/content/schema.py`, after `ATTACK_KEYS`:

```python
OBJECT_KINDS = ("pickup", "scenery", "trigger")
EFFECT_OPS = ("message", "set_flag", "clear_flag", "remove_item", "delete_object")
CONDITION_KEYS = ("flag", "not_flag", "has_item", "not_item")
MAX_ACTIONS = 5          # interaction.inventory.MAX_VISIBLE_ACTIONS: the inventory shows no more
_COMMON_OBJECT_KEYS = ("id", "kind", "stage", "room")
OBJECT_KEYS = {
    "pickup": frozenset(_COMMON_OBJECT_KEYS + ("name", "body", "position", "beta", "zv", "weight", "on_take", "actions")),
    "scenery": frozenset(_COMMON_OBJECT_KEYS + ("body", "position", "beta", "zv", "pushable")),
    "trigger": frozenset(_COMMON_OBJECT_KEYS + ("box", "on_enter")),
}
RULE_KEYS = ("when", "then")
ACTION_KEYS = ("label", "when", "then")
```

After `EnemyRecord`:

```python
@dataclass(frozen=True)
class Condition:
    """A rule's `when`: every named part must hold (conjunction)."""
    flag: str | None = None
    not_flag: str | None = None
    has_item: str | None = None
    not_item: str | None = None


ALWAYS = Condition()


@dataclass(frozen=True)
class Effect:
    op: str      # one of EFFECT_OPS
    arg: str     # the message string, the flag name or the pack id


@dataclass(frozen=True)
class Rule:
    when: Condition
    then: tuple  # of Effect, never empty


@dataclass(frozen=True)
class Action:
    label: str   # the inventory verb the pack shows
    rule: Rule


@dataclass(frozen=True)
class PickupRecord:
    id: str
    kind: str
    stage: int
    room: int
    name: str
    body: int
    position: tuple
    beta: int
    type_zv: int
    weight: int
    on_take: tuple   # of Rule
    actions: tuple   # of Action
    file: str

    def rules(self):
        """(dotted key, Rule) for every rule the record holds, in text order."""
        return tuple(
            [(f"on_take[{i}]", rule) for i, rule in enumerate(self.on_take)]
            + [(f"actions[{i}]", action.rule) for i, action in enumerate(self.actions)]
        )


@dataclass(frozen=True)
class SceneryRecord:
    id: str
    kind: str
    stage: int
    room: int
    body: int
    position: tuple
    beta: int
    type_zv: int
    pushable: bool
    file: str

    def rules(self):
        return ()


@dataclass(frozen=True)
class TriggerRecord:
    id: str
    kind: str
    stage: int
    room: int
    box: tuple       # (x_min, x_max, y_min, y_max, z_min, z_max), room coordinates
    on_enter: tuple  # of Rule, never empty
    file: str

    def rules(self):
        return tuple((f"on_enter[{i}]", rule) for i, rule in enumerate(self.on_enter))
```

After `_reject_unknown`, the shared and object parsers:

```python
def _string(value, file, key):
    if type(value) is not str or not value:
        raise PackError(file, key, f"expected a non-empty string, got {value!r}")
    return value


def _parse_position(value, file):
    if not isinstance(value, list) or len(value) != 3:
        raise PackError(file, "position", f"expected [x, y, z], got {value!r}")
    return tuple(_s16(v, file, f"position[{i}]") for i, v in enumerate(value))


def _parse_beta(value, file):
    beta = _s16(value, file, "beta")
    if not 0 <= beta <= 1023:
        raise PackError(file, "beta", f"{beta} is outside 0..1023")
    return beta


def _parse_condition(table, file, key):
    if not isinstance(table, dict):
        raise PackError(file, key, f"expected a table, got {table!r}")
    _reject_unknown(table, CONDITION_KEYS, file, key + ".")
    return Condition(**{
        name: _string(table[name], file, f"{key}.{name}") for name in CONDITION_KEYS if name in table
    })


def _parse_effect(table, file, key):
    if not isinstance(table, dict) or len(table) != 1:
        raise PackError(file, key, f"expected a table with exactly one key, got {table!r}")
    (op, arg), = table.items()
    if op not in EFFECT_OPS:
        raise PackError(file, f"{key}.{op}", f"unknown effect; expected one of {', '.join(EFFECT_OPS)}")
    return Effect(op, _string(arg, file, f"{key}.{op}"))


def _parse_rule(table, file, key, allowed):
    if not isinstance(table, dict):
        raise PackError(file, key, f"expected a table, got {table!r}")
    _reject_unknown(table, allowed, file, key + ".")
    when = _parse_condition(table["when"], file, f"{key}.when") if "when" in table else ALWAYS
    then = _require(table, "then", file, key + ".")
    if not isinstance(then, list) or not then:
        raise PackError(file, f"{key}.then", f"expected a non-empty array of effects, got {then!r}")
    return Rule(when, tuple(_parse_effect(e, file, f"{key}.then[{i}]") for i, e in enumerate(then)))


def _parse_rules(value, file, key):
    if not isinstance(value, list):
        raise PackError(file, key, f"expected an array of tables, got {value!r}")
    return tuple(_parse_rule(t, file, f"{key}[{i}]", RULE_KEYS) for i, t in enumerate(value))


def _parse_actions(value, file):
    if not isinstance(value, list):
        raise PackError(file, "actions", f"expected an array of tables, got {value!r}")
    if len(value) > MAX_ACTIONS:
        raise PackError(file, "actions", f"{len(value)} actions is more than the inventory shows ({MAX_ACTIONS})")
    actions = []
    for i, table in enumerate(value):
        key = f"actions[{i}]"
        rule = _parse_rule(table, file, key, ACTION_KEYS)
        label = _string(_require(table, "label", file, key + "."), file, f"{key}.label")
        actions.append(Action(label, rule))
    return tuple(actions)


def _parse_box(table, file):
    if not isinstance(table, dict) or sorted(table) != ["x", "y", "z"]:
        raise PackError(file, "box", f"expected a table with the keys x, y, z, got {table!r}")
    bounds = []
    for axis in ("x", "y", "z"):
        pair = table[axis]
        if not isinstance(pair, list) or len(pair) != 2:
            raise PackError(file, f"box.{axis}", f"expected [min, max], got {pair!r}")
        low, high = (_s16(v, file, f"box.{axis}[{i}]") for i, v in enumerate(pair))
        if low > high:
            raise PackError(file, f"box.{axis}", f"min {low} is above max {high}")
        bounds += [low, high]
    return tuple(bounds)


def parse_object(table, file):
    """One object TOML table -> PickupRecord | SceneryRecord | TriggerRecord,
    or PackError(file, key, message). The key set is exact per kind."""
    if not isinstance(table, dict):
        raise PackError(file, "root", "expected a table")
    kind = _choice(_require(table, "kind", file), OBJECT_KINDS, file, "kind")
    _reject_unknown(table, OBJECT_KEYS[kind], file)
    ident = _string(_require(table, "id", file), file, "id")
    stage = _non_negative(_require(table, "stage", file), file, "stage")
    room = _non_negative(_require(table, "room", file), file, "room")
    if kind == "trigger":
        box = _parse_box(_require(table, "box", file), file)
        on_enter = _parse_rules(_require(table, "on_enter", file), file, "on_enter")
        if not on_enter:
            raise PackError(file, "on_enter", "expected at least one rule")
        return TriggerRecord(id=ident, kind=kind, stage=stage, room=room, box=box, on_enter=on_enter, file=file)
    body = _non_negative(_require(table, "body", file), file, "body")
    position = _parse_position(_require(table, "position", file), file)
    beta = _parse_beta(table.get("beta", 0), file)
    type_zv = ZV_TYPES[_choice(table.get("zv", "max"), tuple(ZV_TYPES), file, "zv")]
    if kind == "scenery":
        pushable = table.get("pushable", False)
        if type(pushable) is not bool:
            raise PackError(file, "pushable", f"expected true or false, got {pushable!r}")
        return SceneryRecord(id=ident, kind=kind, stage=stage, room=room, body=body, position=position,
                             beta=beta, type_zv=type_zv, pushable=pushable, file=file)
    return PickupRecord(
        id=ident, kind=kind, stage=stage, room=room,
        name=_string(_require(table, "name", file), file, "name"),
        body=body, position=position, beta=beta, type_zv=type_zv,
        weight=_non_negative(table.get("weight", 0), file, "weight"),
        on_take=_parse_rules(table.get("on_take", []), file, "on_take"),
        actions=_parse_actions(table.get("actions", []), file),
        file=file,
    )
```

In `parse_enemy`, replace the position and beta blocks with the shared helpers (same messages, so the enemy failure table stays green):

```python
    position = _parse_position(_require(table, "position", file), file)
    beta = _parse_beta(table.get("beta", 0), file)
```

- [ ] **Step 4: Run the tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_pack.py -q`
Expected: PASS, including the enemy table.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/content/schema.py tests/test_content_pack.py
git commit -m "feat(content): object records — pickup, scenery, trigger with rules"
```

---

### Task 2: The reader reads `objects/`, checks references and archives

**Files:**
- Modify: `PyAitD/engine/content/pack.py`
- Modify: `PyAitD/engine/content/__init__.py`
- Test: `tests/test_content_pack.py`

**Interfaces:**
- Consumes: `parse_object`, the record classes and `rules()` from Task 1; `EnemyRecord`.
- Produces: `Pack(name, version, game, enemies, objects, digest, path)` (new positional field `objects` between `enemies` and `digest`); `check_references(pack)` (pure, raises `PackError`); `read_pack`/`load_pack` accept packs with an `objects/` folder.

- [ ] **Step 1: Write the failing tests**

In `tests/test_content_pack.py`, extend `_write_pack` and add TOML fixtures and tests to the reader section:

```python
KEY_TOML = """
id = "attic_key"
kind = "pickup"
stage = 0
room = 0
name = "Attic key"
body = 187
position = [3231, 0, -2248]
zv = "body"
weight = 1
[[on_take]]
then = [{ set_flag = "has_key" }, { message = "A small brass key." }]
[[actions]]
label = "Look"
then = [{ message = "It is warm to the touch." }]
"""
BARRICADE_TOML = """
id = "barricade"
kind = "scenery"
stage = 0
room = 0
body = 8
position = [3231, 0, -3400]
zv = "cube"
"""
GATE_TOML = """
id = "gate"
kind = "trigger"
stage = 0
room = 0
box = { x = [2800, 3700], y = [-500, 500], z = [-3100, -2700] }
[[on_enter]]
when = { has_item = "attic_key" }
then = [{ delete_object = "barricade" }, { message = "The barricade gives way." }, { delete_object = "gate" }]
[[on_enter]]
then = [{ message = "Something heavy blocks the doorway." }]
"""
SCENE = (("attic_key.toml", KEY_TOML), ("barricade.toml", BARRICADE_TOML), ("gate.toml", GATE_TOML))


def _write_pack(root, enemies=(), objects=(), manifest=PACK_TOML):
    root.mkdir(parents=True, exist_ok=True)
    (root / "pack.toml").write_text(manifest)
    for folder, files in (("enemies", enemies), ("objects", objects)):
        if files:
            (root / folder).mkdir(exist_ok=True)
        for name, text in files:
            (root / folder / name).write_text(text)
    return root


def test_read_pack_reads_objects_in_name_order_after_the_enemies(tmp_path):
    from PyAitD.engine.content.pack import read_pack
    pack = read_pack(_write_pack(tmp_path / "p", enemies=(("z.toml", PROWLER_TOML),), objects=SCENE))
    assert [e.id for e in pack.enemies] == ["prowler"]
    assert [(o.id, o.kind, o.file) for o in pack.objects] == [
        ("attic_key", "pickup", "objects/attic_key.toml"),
        ("barricade", "scenery", "objects/barricade.toml"),
        ("gate", "trigger", "objects/gate.toml"),
    ]
    assert read_pack(_write_pack(tmp_path / "q")).objects == ()


def test_an_object_id_may_not_repeat_an_enemy_id(tmp_path):
    from PyAitD.engine.content.pack import read_pack
    clash = KEY_TOML.replace('id = "attic_key"', 'id = "prowler"')
    root = _write_pack(tmp_path / "p", enemies=(("a.toml", PROWLER_TOML),), objects=(("k.toml", clash),))
    with pytest.raises(PackError) as caught:
        read_pack(root)
    assert (caught.value.file, caught.value.key, caught.value.message) == (
        "objects/k.toml", "id", "'prowler' is already used by enemies/a.toml")


@pytest.mark.parametrize("edit, file, key, message", [
    (lambda t: t.replace('delete_object = "barricade"', 'delete_object = "wall"'),
     "objects/gate.toml", "on_enter[0].then[0].delete_object", "'wall' is not an object of this pack"),
    (lambda t: t.replace('has_item = "attic_key"', 'has_item = "barricade"'),
     "objects/gate.toml", "on_enter[0].when.has_item", "'barricade' is not a pickup of this pack"),
    (lambda t: t.replace('delete_object = "gate"', 'remove_item = "gate"'),
     "objects/gate.toml", "on_enter[0].then[2].remove_item", "'gate' is not a pickup of this pack"),
])
def test_read_pack_checks_every_cross_reference(tmp_path, edit, file, key, message):
    from PyAitD.engine.content.pack import read_pack
    objects = tuple((name, edit(text) if name == "gate.toml" else text) for name, text in SCENE)
    with pytest.raises(PackError) as caught:
        read_pack(_write_pack(tmp_path / "p", objects=objects))
    assert (caught.value.file, caught.value.key, caught.value.message) == (file, key, message)
```

And in the archive section:

```python
@pytest.mark.parametrize("name, edit, key, message", [
    ("barricade.toml", lambda t: t.replace("body = 8", "body = 272"), "body", "272 is not below 272"),
    ("attic_key.toml", lambda t: t.replace("room = 0", "room = 99"), "room", "99 is not below"),
    ("gate.toml", lambda t: t.replace("stage = 0", "stage = 40"), "stage", "40:"),
])
def test_check_archives_covers_object_bodies_and_rooms(tmp_path, data_dir, profile, name, edit, key, message):
    from PyAitD.engine.content.pack import load_pack
    objects = tuple((n, edit(t) if n == name else t) for n, t in SCENE)
    with pytest.raises(PackError) as caught:
        load_pack(_write_pack(tmp_path / "p", objects=objects), data_dir, profile)
    assert (caught.value.file, caught.value.key) == (f"objects/{name}", key)
    assert message in caught.value.message


def test_load_pack_accepts_the_scene_against_real_data(tmp_path, data_dir, profile):
    from PyAitD.engine.content.pack import load_pack
    pack = load_pack(_write_pack(tmp_path / "ok", objects=SCENE), data_dir, profile)
    assert [o.id for o in pack.objects] == ["attic_key", "barricade", "gate"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_pack.py -q -k "objects or cross_reference or repeat_an_enemy"`
Expected: FAIL (`Pack` has no `objects`; `objects/` ignored).

- [ ] **Step 3: Implement**

In `PyAitD/engine/content/pack.py`:

```python
from PyAitD.engine.content.schema import EnemyRecord, PackError, parse_enemy, parse_object
```

```python
@dataclass(frozen=True)
class Pack:
    name: str
    version: str
    game: str
    enemies: tuple
    objects: tuple
    digest: str
    path: pathlib.Path
```

Replace the enemies loop in `read_pack` with a folder reader and the reference pass:

```python
def _read_folder(root, folder, parse, owner):
    """Every *.toml under `folder`, in name order; `owner` maps ids already
    taken (across folders) to the file that took them."""
    records = []
    path = root / folder
    for file in sorted(path.glob("*.toml")) if path.is_dir() else ():
        rel = file.relative_to(root).as_posix()
        record = parse(_load_toml(file, rel), rel)
        if record.id in owner:
            raise PackError(rel, "id", f"{record.id!r} is already used by {owner[record.id]}")
        owner[record.id] = rel
        records.append(record)
    return tuple(records)


def check_references(pack):
    """Every pack id a rule names must exist with the right kind: items are
    pickups, deletions are objects (never enemies). Pure."""
    kinds = {record.id: record.kind for record in pack.objects}
    for record in pack.objects:
        for key, rule in record.rules():
            for name in ("has_item", "not_item"):
                target = getattr(rule.when, name)
                if target is not None and kinds.get(target) != "pickup":
                    raise PackError(record.file, f"{key}.when.{name}", f"{target!r} is not a pickup of this pack")
            for i, effect in enumerate(rule.then):
                if effect.op == "remove_item" and kinds.get(effect.arg) != "pickup":
                    raise PackError(record.file, f"{key}.then[{i}].remove_item",
                                    f"{effect.arg!r} is not a pickup of this pack")
                if effect.op == "delete_object" and effect.arg not in kinds:
                    raise PackError(record.file, f"{key}.then[{i}].delete_object",
                                    f"{effect.arg!r} is not an object of this pack")


def read_pack(path):
    """Read a pack directory into a Pack. Raises PackError; touches no game data."""
    root = pathlib.Path(path)
    manifest = root / PACK_FILE
    if not manifest.is_file():
        raise PackError(PACK_FILE, "root", f"not found in {root}")
    table = _load_toml(manifest, PACK_FILE)
    if sorted(table) != list(PACK_KEYS):
        raise PackError(PACK_FILE, "root", f"expected exactly the keys {list(PACK_KEYS)}, got {sorted(table)}")
    for key in PACK_KEYS:
        if type(table[key]) is not str or not table[key]:
            raise PackError(PACK_FILE, key, f"expected a non-empty string, got {table[key]!r}")
    owner = {}
    enemies = _read_folder(root, "enemies", parse_enemy, owner)
    objects = _read_folder(root, "objects", parse_object, owner)
    pack = Pack(table["name"], table["version"], table["game"], enemies, objects, pack_digest(root), root)
    check_references(pack)
    return pack
```

In `check_archives`, replace the record loop:

```python
    rooms = {}
    placed = list(pack.enemies) + [record for record in pack.objects if record.kind != "trigger"]
    for record in placed:
        for body_pak, num_bodies, anim_pak, num_anims in archives:
            if record.body >= num_bodies:
                raise PackError(record.file, "body", f"{record.body} is not below {num_bodies} ({body_pak})")
            if isinstance(record, EnemyRecord):
                for key, anim in record.anims.present():
                    if anim >= num_anims:
                        raise PackError(record.file, f"anims.{key}", f"{anim} is not below {num_anims} ({anim_pak})")
    for record in list(pack.enemies) + list(pack.objects):
        if record.stage not in rooms:
            try:
                rooms[record.stage] = len(Floor(data_dir, record.stage, profile).rooms)
            except PakError as exc:
                raise PackError(record.file, "stage", f"{record.stage}: {exc}") from None
        if record.room >= rooms[record.stage]:
            raise PackError(record.file, "room", f"{record.room} is not below {rooms[record.stage]} on stage {record.stage}")
```

In `PyAitD/engine/content/__init__.py` add `check_references` to the pack import line and the new schema names:

```python
from PyAitD.engine.content.pack import PACK_FILE, Pack, check_archives, check_references, load_pack, pack_digest, read_pack
from PyAitD.engine.content.schema import (
    BEHAVIOUR_LIFE, PackError, PickupRecord, SceneryRecord, TriggerRecord, parse_enemy, parse_object,
)
```

Grep for every `Pack(` construction outside `read_pack` (`rg -n "Pack\(" PyAitD tests`) and add the `objects` argument if any exists.

- [ ] **Step 4: Run the tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_pack.py tests/test_content_enemies.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/content/pack.py PyAitD/engine/content/__init__.py tests/test_content_pack.py
git commit -m "feat(content): read objects/, check cross-references and object archives"
```

---

### Task 3: Texts, compilation and attachment

**Files:**
- Modify: `PyAitD/engine/data/assets.py`
- Modify: `PyAitD/engine/content/world.py`
- Modify: `PyAitD/engine/content/__init__.py`
- Test: `tests/test_content_pack.py`

**Interfaces:**
- Consumes: the record classes and `rules()`; `KINDS` (the enemy kinds) from schema.
- Produces: `Assets.register_texts(texts: dict[int, str])`; `CONTENT_TEXT_BASE = 2000`; `allocate_texts(objects) -> dict[str, int]`; `compile_record(record, text_ids=None) -> WorldObject`; `initial_state(record) -> dict`; `ContentAttachment(pack, first_index, records, by_id, text_ids, flags)` with `record_for(world_idx)`; `attach(game, pack)` appends enemies then objects.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_content_pack.py` (attach section):

```python
def test_allocate_texts_gives_every_distinct_string_one_id_in_first_seen_order():
    from PyAitD.engine.content.world import CONTENT_TEXT_BASE, allocate_texts
    records = [parse_object(t, "f") for t in (KEY, BARRICADE, GATE)]
    assert CONTENT_TEXT_BASE == 2000
    assert allocate_texts(records) == {
        "Attic key": 2000, "Look": 2001, "A small brass key.": 2002, "It is warm to the touch.": 2003,
        "The barricade gives way.": 2004, "Something heavy blocks the doorway.": 2005,
    }
    twice = parse_object(_object(KEY, name="Look", actions=[
        {"label": "Look", "then": [{"message": "Look"}]}]), "f")
    assert allocate_texts([twice]) == {"Look": 2000, "A small brass key.": 2001}
    assert allocate_texts([]) == {}


def test_compile_record_shapes_each_object_kind():
    from PyAitD.engine.content.world import allocate_texts, compile_record
    from PyAitD.engine.data.formats import WorldObject
    records = [parse_object(t, "f") for t in (KEY, BARRICADE, GATE)]
    text_ids = allocate_texts(records)
    key, barricade, gate = (compile_record(r, text_ids) for r in records)
    assert key == WorldObject(
        obj_index=-1, body=187, flags=0xA0, type_zv=1,
        found_body=-1, found_name=2000, found_flag=0, found_life=-1,
        x=3231, y=0, z=-2248, alpha=0, beta=0, gamma=0, stage=0, room=0,
        life_mode=0, life=-1, floor_life=-1, anim=-1, frame=0, anim_type=0, anim_info=-1,
        track_mode=0, track_number=0, position_in_track=1, mark=0,
    )
    assert barricade == WorldObject(
        obj_index=-1, body=8, flags=0x20, type_zv=2,
        found_body=-1, found_name=-1, found_flag=0, found_life=-1,
        x=3231, y=0, z=-3400, alpha=0, beta=0, gamma=0, stage=0, room=0,
        life_mode=0, life=-1, floor_life=-1, anim=-1, frame=0, anim_type=0, anim_info=-1,
        track_mode=0, track_number=-1, position_in_track=0, mark=0,
    )
    pushable = compile_record(parse_object(_object(BARRICADE, pushable=True), "f"), text_ids)
    assert pushable.flags == 0x30
    assert gate == WorldObject(
        obj_index=-1, body=-1, flags=0, type_zv=0,
        found_body=-1, found_name=-1, found_flag=0, found_life=-1,
        x=0, y=0, z=0, alpha=0, beta=0, gamma=0, stage=-1, room=-1,
        life_mode=0, life=-1, floor_life=-1, anim=-1, frame=0, anim_type=0, anim_info=-1,
        track_mode=0, track_number=-1, position_in_track=0, mark=0,
    )


def test_initial_state_per_kind():
    from PyAitD.engine.content.world import initial_state
    assert initial_state(parse_enemy(PROWLER, "e")) == {"hp": 3, "phase": "idle"}
    assert initial_state(parse_object(KEY, "f")) == {}
    assert initial_state(parse_object(BARRICADE, "f")) == {}
    assert initial_state(parse_object(GATE, "f")) == {"armed": True, "inside": False}


def test_register_texts_refuses_any_id_already_present(data_dir, profile):
    from PyAitD.engine.content.world import CONTENT_TEXT_BASE
    from PyAitD.engine.script.game import init_game
    assets = init_game(data_dir, profile).assets
    # the vanilla table tops out below the pack range (the design's precondition)
    assert max(assets._system_texts) == 1150 < CONTENT_TEXT_BASE
    assets.register_texts({2000: "Attic key"})
    assert assets.system_text(2000) == "Attic key"
    with pytest.raises(ValueError, match=r"already present: \[2000\]"):
        assets.register_texts({2000: "Again"})
    with pytest.raises(ValueError, match=r"already present: \[20\]"):
        assets.register_texts({20: "Found"})


def test_attach_places_pickups_and_scenery_but_never_a_trigger(tmp_path, data_dir, profile):
    from PyAitD.engine.content import load_pack
    from PyAitD.engine.script.game import init_game
    pack = load_pack(_write_pack(tmp_path / "scene", objects=SCENE), data_dir, profile)
    game = init_game(data_dir, profile, pack=pack)
    assert len(game.world_objects) == 295
    assert game.content.first_index == 292
    assert [r.id for r in game.content.records.values()] == ["attic_key", "barricade", "gate"]
    assert game.content.by_id == {"attic_key": 292, "barricade": 293, "gate": 294}
    assert game.content.text_ids["Attic key"] == 2000 and game.content.flags == set()
    assert game.content_state == {292: {}, 293: {}, 294: {"armed": True, "inside": False}}
    assert game.assets.system_text(game.world_objects[292].found_name) == "Attic key"
    assert game.assets.system_text(2005) == "Something heavy blocks the doorway."
    key = game.actors[game.world_objects[292].obj_index]
    barricade = game.actors[game.world_objects[293].obj_index]
    assert (key.index_in_world, key.body_num, key.object_type, key.room) == (292, 187, 0x80, 0)
    assert (barricade.index_in_world, barricade.body_num, barricade.object_type) == (293, 8, 0)
    assert (barricade.room_x, barricade.room_y, barricade.room_z) == (3231, 0, -3400)
    assert game.world_objects[294].obj_index == -1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_pack.py -q -k "allocate_texts or shapes_each_object or initial_state or register_texts or never_a_trigger"`
Expected: FAIL (no `allocate_texts`, `register_texts`).

- [ ] **Step 3: Implement**

`PyAitD/engine/data/assets.py`, after `system_text`:

```python
    def register_texts(self, texts):
        """Add strings to the system text table under new ids (content packs
        from CONTENT_TEXT_BASE up). Refuses an id already present, vanilla
        or pack, so a pack can never shadow a game string."""
        taken = sorted(set(texts) & set(self._system_texts))
        if taken:
            raise ValueError(f"text ids already present: {taken}")
        self._system_texts.update(texts)
```

`PyAitD/engine/content/world.py`: replace the module body below the docstring with:

```python
from dataclasses import dataclass

from PyAitD.engine.content.schema import BEHAVIOUR_LIFE, KINDS
from PyAitD.engine.data.formats import WorldObject
from PyAitD.engine.script.game.state import AF_ANIMATED, AF_FALLABLE, AF_FOUNDABLE, AF_MOVABLE, AF_SPECIAL

CONTENT_TEXT_BASE = 2000
"""First text id a pack string may take; the vanilla table tops out at 1150
(tests/test_content_pack.py pins it)."""


@dataclass
class ContentAttachment:
    pack: object
    first_index: int   # world index of the first appended record
    records: dict      # world index -> record (enemy or object)
    by_id: dict        # pack id -> world index
    text_ids: dict     # pack string -> text id registered in game.assets
    flags: set         # the pack's named flags currently set

    def record_for(self, world_idx):
        return self.records.get(world_idx)


def allocate_texts(objects):
    """Every distinct pack string -> one text id from CONTENT_TEXT_BASE, in
    first-seen order: per object, the pickup name, its action labels, then
    the messages of its rules in text order. A pure function of the pack,
    so a saved message id names the same string after a load."""
    ids = {}

    def take(string):
        if string not in ids:
            ids[string] = CONTENT_TEXT_BASE + len(ids)

    for record in objects:
        if record.kind == "pickup":
            take(record.name)
            for action in record.actions:
                take(action.label)
        for _key, rule in record.rules():
            for effect in rule.then:
                if effect.op == "message":
                    take(effect.arg)
    return ids


def _compile_enemy(record):
    """Shaped like an original creature's record (world 21: flags 0x21, anim -1
    until its LIFE dresses it) except that it spawns already standing, the
    way floor 5's enemy 222 is stored (anim 199, repeat)."""
    flags = AF_ANIMATED | AF_SPECIAL      # AF_SPECIAL (0x20): dyn_flags collision on
    if record.falls:
        flags |= AF_FALLABLE
    x, y, z = record.position
    return WorldObject(
        obj_index=-1, body=record.body, flags=flags, type_zv=record.type_zv,
        found_body=-1, found_name=-1, found_flag=0, found_life=-1,
        x=x, y=y, z=z, alpha=0, beta=record.beta, gamma=0,
        stage=record.stage, room=record.room,
        life_mode=record.life_mode, life=BEHAVIOUR_LIFE, floor_life=-1,
        anim=record.anims.stand, frame=0, anim_type=1, anim_info=-1,
        track_mode=0, track_number=-1, position_in_track=0, mark=0,
    )


def _compile_pickup(record, text_ids):
    """A boot-time vanilla pickup (flags 0xa0, no LIFE). track_number 0, not
    the vanilla -1: request_found refuses the prompt while
    timer - track_number < 300, which would hide a pickup near the start."""
    x, y, z = record.position
    return WorldObject(
        obj_index=-1, body=record.body, flags=AF_FOUNDABLE | AF_SPECIAL, type_zv=record.type_zv,
        found_body=-1, found_name=text_ids[record.name], found_flag=0, found_life=-1,
        x=x, y=y, z=z, alpha=0, beta=record.beta, gamma=0,
        stage=record.stage, room=record.room,
        life_mode=0, life=-1, floor_life=-1,
        anim=-1, frame=0, anim_type=0, anim_info=-1,
        track_mode=0, track_number=0, position_in_track=record.weight, mark=0,
    )


def _compile_scenery(record):
    """A vanilla static (0x20), pushable ones 0x30 like the attic crate."""
    x, y, z = record.position
    return WorldObject(
        obj_index=-1, body=record.body, flags=AF_SPECIAL | (AF_MOVABLE if record.pushable else 0),
        type_zv=record.type_zv,
        found_body=-1, found_name=-1, found_flag=0, found_life=-1,
        x=x, y=y, z=z, alpha=0, beta=record.beta, gamma=0,
        stage=record.stage, room=record.room,
        life_mode=0, life=-1, floor_life=-1,
        anim=-1, frame=0, anim_type=0, anim_info=-1,
        track_mode=0, track_number=-1, position_in_track=0, mark=0,
    )


def _compile_trigger(record):
    """A placeholder that never spawns (stage -1): a body-less actor would
    carry the default volume and block the hero. The box and room live on
    the record; the world index is what by_id and content_state key on."""
    return WorldObject(
        obj_index=-1, body=-1, flags=0, type_zv=0,
        found_body=-1, found_name=-1, found_flag=0, found_life=-1,
        x=0, y=0, z=0, alpha=0, beta=0, gamma=0, stage=-1, room=-1,
        life_mode=0, life=-1, floor_life=-1,
        anim=-1, frame=0, anim_type=0, anim_info=-1,
        track_mode=0, track_number=-1, position_in_track=0, mark=0,
    )


def compile_record(record, text_ids=None):
    """One pack record -> the WorldObject spawn_stage_actors will place."""
    if record.kind in KINDS:
        return _compile_enemy(record)
    if record.kind == "pickup":
        return _compile_pickup(record, text_ids)
    if record.kind == "scenery":
        return _compile_scenery(record)
    return _compile_trigger(record)


def initial_state(record):
    """The content_state entry a fresh game seeds for `record`."""
    if record.kind in KINDS:
        return {"hp": record.hit_points, "phase": "idle"}
    if record.kind == "trigger":
        return {"armed": True, "inside": False}
    return {}


def attach(game, pack):
    """Register the pack's strings, append its records (enemies, then
    objects) to game.world_objects and seed game.content and
    game.content_state. None for pack=None; raises if a pack is already
    attached (a Game is attached exactly once, in init_game)."""
    if pack is None:
        return None
    if game.content is not None:
        raise ValueError("a content pack is already attached to this game")
    text_ids = allocate_texts(pack.objects)
    game.assets.register_texts({text_id: string for string, text_id in text_ids.items()})
    first = len(game.world_objects)
    records, by_id = {}, {}
    for offset, record in enumerate(pack.enemies + pack.objects):
        idx = first + offset
        game.world_objects.append(compile_record(record, text_ids))
        records[idx] = record
        by_id[record.id] = idx
        game.content_state[idx] = initial_state(record)
    game.content = ContentAttachment(pack, first, records, by_id, text_ids, set())
    return game.content
```

Keep the module docstring's import note. In `PyAitD/engine/content/__init__.py`:

```python
from PyAitD.engine.content.world import (
    CONTENT_TEXT_BASE, ContentAttachment, allocate_texts, attach, compile_record, initial_state,
)
```

- [ ] **Step 4: Run the tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_pack.py tests/test_content_enemies.py tests/test_save.py -q`
Expected: PASS (the example pack still has no objects, so every count pin holds).

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/data/assets.py PyAitD/engine/content/world.py PyAitD/engine/content/__init__.py tests/test_content_pack.py
git commit -m "feat(content): register pack texts, compile and attach objects"
```

---

### Task 4: Save schema 4 and the example scene

The save learns the per-kind state and the flag set, and the example pack gains the three object files; every count pin in the suite moves from 294 to 297.

**Files:**
- Modify: `PyAitD/engine/script/save.py`
- Create: `packs/example/objects/attic_key.toml`, `packs/example/objects/barricade.toml`, `packs/example/objects/gate.toml`
- Test: `tests/test_save.py`, `tests/test_content_pack.py`, `tests/test_main.py:758`, `tests/test_runtime_modes.py:1268,1280`

**Interfaces:**
- Consumes: `Pack.objects`, `KINDS`, `PHASES`, `ContentAttachment.flags`.
- Produces: `SCHEMA = 4`; payload key `content_flags` (sorted list); `content_state` entries `{}` for pickups and scenery, `{"armed", "inside"}` for triggers; `restore_game` restores `game.content.flags`.

- [ ] **Step 1: Write the example pack objects**

`packs/example/objects/attic_key.toml`:

```toml
# A key on the floor 700 units ahead of the attic start (the hero faces -z).
# Taking it sets the flag the gate reads; "Look" shows a message from the
# inventory.
id = "attic_key"
kind = "pickup"
stage = 0
room = 0
name = "Attic key"
body = 187
position = [3231, 0, -2248]
zv = "body"
weight = 1

[[on_take]]
then = [{ set_flag = "has_key" }, { message = "A small brass key." }]

[[actions]]
label = "Look"
then = [{ message = "It is warm to the touch." }]
```

`packs/example/objects/barricade.toml`:

```toml
# The attic crate's body, planted across the walk 1850 units ahead of the
# start. Not pushable: only the gate removes it.
id = "barricade"
kind = "scenery"
stage = 0
room = 0
body = 8
position = [3231, 0, -3400]
zv = "cube"
pushable = false
```

`packs/example/objects/gate.toml`:

```toml
# A zone in front of the barricade. With the key the barricade goes and the
# gate deletes itself; without it a message says why the way is blocked.
id = "gate"
kind = "trigger"
stage = 0
room = 0
box = { x = [2800, 3700], y = [-500, 500], z = [-3100, -2700] }

[[on_enter]]
when = { has_item = "attic_key" }
then = [{ delete_object = "barricade" }, { message = "The barricade gives way." }, { delete_object = "gate" }]

[[on_enter]]
then = [{ message = "Something heavy blocks the doorway." }]
```

- [ ] **Step 2: Update the count pins and write the failing save tests**

Update these assertions:
- `tests/test_content_pack.py::test_the_example_pack_reads`: add `assert [(o.id, o.kind) for o in pack.objects] == [("attic_key", "pickup"), ("barricade", "scenery"), ("gate", "trigger")]`.
- `tests/test_content_pack.py::test_init_game_appends_the_pack_after_the_original_records`: `297`, ids `["prowler", "watcher", "attic_key", "barricade", "gate"]`, and `game.content_state == {292: {"hp": 3, "phase": "idle"}, 293: {"hp": 2, "phase": "idle"}, 294: {}, 295: {}, 296: {"armed": True, "inside": False}}`.
- `tests/test_main.py:758`, `tests/test_runtime_modes.py:1268` and `:1280`: `294` → `297`.
- `tests/test_save.py`: line 48 `SCHEMA == 4`; `test_validate_rejects_unknown_schema` sets `payload["schema"] = 5`; `test_snapshot_records_the_pack_identity_and_the_content_state`: `297` and `content_state == {"292": {"hp": 3, "phase": "idle"}, "293": {"hp": 2, "phase": "idle"}, "294": {}, "295": {}, "296": {"armed": True, "inside": False}}`, plus `assert payload["content_flags"] == [] and vanilla["content_flags"] == []`; `test_validate_checks_world_object_count_and_content_state_against_the_pack`: `expected 297 world objects, got 292`, the range message `expected a world index in 292..296`, and add these rows to its table:

```python
        ({"294": {"hp": 1}}, "content_state.294", "unexpected keys: hp"),
        ({"296": {"armed": True}}, "content_state.296", "missing keys: inside"),
        ({"296": {"armed": True, "inside": "no"}}, "content_state.296.inside", "expected a boolean, got str"),
```

(These rows fail before the full-set check because the key loop runs first; the final `expected entries for 292..296` message covers the short table.)

Add to the content section of `tests/test_save.py`:

```python
def test_content_flags_round_trip_and_are_validated(data_dir, profile, example_pack_dir):
    game, pack = _packed(data_dir, profile, example_pack_dir)
    game.content.flags.update({"has_key", "attic_seen"})
    game.content_state[296] = {"armed": False, "inside": True}
    payload = json.loads(json.dumps(snapshot_game(game, SETTINGS)))
    assert payload["content_flags"] == ["attic_seen", "has_key"]
    restored, _ = restore_game(data_dir, profile, payload, pack=pack)
    assert restored.content.flags == {"attic_seen", "has_key"}
    assert restored.content_state[296] == {"armed": False, "inside": True}
    for flags, path, message in [
        ("has_key", "content_flags", "expected a list, got str"),
        (["has_key", 3], "content_flags[1]", "expected a non-empty string, got 3"),
        (["a", "a"], "content_flags", "duplicate flag names"),
    ]:
        bad = copy.deepcopy(payload)
        bad["content_flags"] = flags
        with pytest.raises(SaveError, match=re.escape(f"{path}: {message}")):
            validate_snapshot(bad, data_dir, profile, pack=pack)
    vanilla = _snapshot(data_dir, profile)
    vanilla["content_flags"] = ["has_key"]
    with pytest.raises(SaveError, match=r"content_flags: expected no content flags without a pack"):
        validate_snapshot(vanilla, data_dir, profile)
```

`restore_game` is imported at line 260 of the file; the content section sits after it.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_save.py tests/test_content_pack.py -q`
Expected: FAIL (schema 3, missing `content_flags`, `hp` required on entry 294).

- [ ] **Step 4: Implement the schema change**

In `PyAitD/engine/script/save.py`:

```python
from PyAitD.engine.content.schema import KINDS, PHASES
```

```python
SCHEMA = 4

ROOT_KEYS = (
    "schema", "engine_version", "source", "hero", "game", "actors",
    "world_objects", "anim_players", "inventory", "messages", "rng_state",
    "settings", "content_state", "content_flags",
)
```

Replace `_CONTENT_STATE_KEYS = {"hp", "phase"}` with:

```python
_ENEMY_STATE_KEYS = {"hp", "phase"}
_TRIGGER_STATE_KEYS = {"armed", "inside"}
```

In `snapshot_game`:

```python
        "content_state": {str(idx): dict(state) for idx, state in sorted(game.content_state.items())},
        "content_flags": [] if game.content is None else sorted(game.content.flags),
```

In `validate_snapshot`:

```python
    extra = 0 if pack is None else len(pack.enemies) + len(pack.objects)
    first = _validate_world_objects(payload["world_objects"], data_dir, profile.world_object_has_mark, extra)
    _validate_content_state(payload["content_state"], pack, first)
    _validate_content_flags(payload["content_flags"], pack)
```

Replace `_validate_content_state` and add `_validate_content_flags`:

```python
def _validate_content_state(state, pack, first_index):
    if not isinstance(state, dict):
        _fail("content_state", "expected an object")
    if pack is None:
        if state:
            _fail("content_state", "expected no content state without a pack")
        return
    records = pack.enemies + pack.objects
    last = first_index + len(records) - 1
    for key, entry in state.items():
        path = f"content_state.{key}"
        if not (type(key) is str and key.isascii() and key.isdigit() and first_index <= int(key) <= last):
            _fail(path, f"expected a world index in {first_index}..{last}")
        record = records[int(key) - first_index]
        if record.kind in KINDS:
            _require_keys(entry, _ENEMY_STATE_KEYS, path)
            _require_int(entry["hp"], f"{path}.hp")
            if entry["phase"] not in PHASES:
                _fail(f"{path}.phase", f"expected one of {', '.join(PHASES)}, got {entry['phase']!r}")
        elif record.kind == "trigger":
            _require_keys(entry, _TRIGGER_STATE_KEYS, path)
            for name in sorted(_TRIGGER_STATE_KEYS):
                if type(entry[name]) is not bool:
                    _fail(f"{path}.{name}", f"expected a boolean, got {type(entry[name]).__name__}")
        else:
            _require_keys(entry, set(), path)
    expected = {str(i) for i in range(first_index, last + 1)}
    if set(state) != expected:
        _fail("content_state", f"expected entries for {first_index}..{last}")


def _validate_content_flags(flags, pack):
    if not isinstance(flags, list):
        _fail("content_flags", f"expected a list, got {type(flags).__name__}")
    if pack is None and flags:
        _fail("content_flags", "expected no content flags without a pack")
    for i, flag in enumerate(flags):
        if type(flag) is not str or not flag:
            _fail(f"content_flags[{i}]", f"expected a non-empty string, got {flag!r}")
    if len(set(flags)) != len(flags):
        _fail("content_flags", "duplicate flag names")
```

In `restore_game`, replace the `content_state` rebuild:

```python
    game.content_state = {int(key): dict(entry) for key, entry in payload["content_state"].items()}
    if game.content is not None:
        game.content.flags = set(payload["content_flags"])
```

- [ ] **Step 5: Run the whole suite**

Run: `make test`
Expected: PASS. The prowler and watcher journeys keep their indices (292, 293); the new objects sit beyond the hero on the walk ahead, out of the prowler's approach. If any enemy journey changes, report `DONE_WITH_CONCERNS` with the failing assertion rather than editing the enemy tests.

- [ ] **Step 6: Commit**

```bash
git add PyAitD/engine/script/save.py packs/example/objects tests/test_save.py tests/test_content_pack.py tests/test_main.py tests/test_runtime_modes.py
git commit -m "feat(content): save schema 4 — per-kind content state and pack flags; example scene"
```

---

### Task 5: `Game.add_message` and the rule engine

Pure engine work, unit-stepped on a stub game: conditions, rules, effects, the pickup helpers and the trigger step. Nothing calls it yet.

**Files:**
- Modify: `PyAitD/engine/script/game/state.py`
- Modify: `PyAitD/engine/script/interaction/life_cont.py:42-60`
- Create: `PyAitD/engine/content/objects.py`
- Modify: `PyAitD/engine/content/__init__.py`
- Test: `tests/test_content_objects.py` (new)

**Interfaces:**
- Consumes: `ContentAttachment`, `allocate_texts`, `compile_record`, `initial_state`, `TriggerRecord`, `delete_object` from `script.game.objects`.
- Produces: `Game.add_message(message_id)`; in `engine/content/objects.py`: `holds(game, condition) -> bool`, `run_rules(game, rules) -> bool`, `pickup_at(game, world_idx) -> PickupRecord | None`, `action_ids(game, world_idx) -> tuple[int, ...]`, `take(game, world_idx)`, `use(game, world_idx, text_id)` (raises `ValueError` for an unknown id), `step_triggers(game)`; `IN_INVENTORY = 0x8000`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_content_objects.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""engine.content objects: the rule engine unit-stepped on a stub game, and
the key-and-barricade journeys of the example pack against the real attic
(2026-09-04-content-packs-objects-design.md, sections 3 and 5)."""
import copy
from types import SimpleNamespace

import pytest

import PyAitD.engine.content.objects as objects_module
from PyAitD.engine.content.objects import (
    action_ids, holds, pickup_at, run_rules, step_triggers, take, use,
)
from PyAitD.engine.content.schema import Condition, Effect, Rule, parse_object
from PyAitD.engine.content.world import ContentAttachment, allocate_texts, compile_record, initial_state

pytestmark = [pytest.mark.engine, pytest.mark.journey]

KEY = {
    "id": "attic_key", "kind": "pickup", "stage": 0, "room": 0,
    "name": "Attic key", "body": 187, "position": [3231, 0, -2248], "zv": "body", "weight": 1,
    "on_take": [{"then": [{"set_flag": "has_key"}, {"message": "A small brass key."}]}],
    "actions": [{"label": "Look", "then": [{"message": "It is warm to the touch."}]}],
}
BARRICADE = {
    "id": "barricade", "kind": "scenery", "stage": 0, "room": 0,
    "body": 8, "position": [3231, 0, -3400], "zv": "cube",
}
GATE = {
    "id": "gate", "kind": "trigger", "stage": 0, "room": 0,
    "box": {"x": [2800, 3700], "y": [-500, 500], "z": [-3100, -2700]},
    "on_enter": [
        {"when": {"has_item": "attic_key"},
         "then": [{"delete_object": "barricade"}, {"message": "The barricade gives way."},
                  {"delete_object": "gate"}]},
        {"then": [{"message": "Something heavy blocks the doorway."}]},
    ],
}
K, B, G = 0, 1, 2   # world indices in the stub


def _stub(hero=None):
    """A game with just the three scene records attached at world 0..2, a
    message sink instead of the timed-message table, and an optional hero
    actor in slot 0."""
    records = [parse_object(t, "f") for t in (KEY, BARRICADE, GATE)]
    text_ids = allocate_texts(records)
    content = ContentAttachment(
        pack=None, first_index=0, records=dict(enumerate(records)),
        by_id={r.id: i for i, r in enumerate(records)}, text_ids=text_ids, flags=set(),
    )
    game = SimpleNamespace(
        content=content, content_state={i: initial_state(r) for i, r in enumerate(records)},
        world_objects=[compile_record(r, text_ids) for r in records],
        shown=[], trace=None, current_floor=0,
        actors=[hero] if hero is not None else [],
        current_camera_target_actor=0 if hero is not None else -1,
        in_hand_table=[-1, -1], current_inventory=0,
    )
    game.add_message = game.shown.append
    return game


def _hero(x, y, z, room=0):
    return SimpleNamespace(room=room, room_x=x, room_y=y, room_z=z)


def _held(game, idx):
    game.world_objects[idx].found_flag |= 0x8000


def test_holds_checks_flags_and_the_in_inventory_bit():
    game = _stub()
    assert holds(game, Condition())
    assert not holds(game, Condition(flag="has_key"))
    assert holds(game, Condition(not_flag="has_key"))
    game.content.flags.add("has_key")
    assert holds(game, Condition(flag="has_key")) and not holds(game, Condition(not_flag="has_key"))
    assert not holds(game, Condition(has_item="attic_key")) and holds(game, Condition(not_item="attic_key"))
    _held(game, K)
    assert holds(game, Condition(has_item="attic_key")) and not holds(game, Condition(not_item="attic_key"))
    assert not holds(game, Condition(flag="has_key", not_item="attic_key"))   # conjunction


def test_run_rules_fires_the_first_matching_rule_only(monkeypatch):
    deleted = []
    monkeypatch.setattr(objects_module, "delete_object", lambda g, idx: deleted.append(idx))
    game = _stub()
    gate = game.content.records[G]
    assert run_rules(game, gate.on_enter) is True
    assert game.shown == [game.content.text_ids["Something heavy blocks the doorway."]]
    assert deleted == [] and game.content_state[G]["armed"] is True
    _held(game, K)
    assert run_rules(game, gate.on_enter) is True
    assert game.shown[1:] == [game.content.text_ids["The barricade gives way."]]
    assert deleted == [B]                                   # scenery: the vanilla primitive
    assert game.content_state[G]["armed"] is False          # a trigger deletes itself by disarming
    assert run_rules(game, (Rule(Condition(flag="never"), (Effect("message", "x"),)),)) is False
    rules = (Rule(Condition(), (Effect("set_flag", "a"), Effect("clear_flag", "a"), Effect("set_flag", "b"))),)
    run_rules(game, rules)
    assert game.content.flags == {"b"}
    run_rules(game, (Rule(Condition(), (Effect("remove_item", "attic_key"),)),))
    assert deleted == [B, K]


def test_pickup_helpers_take_and_use():
    game = _stub()
    assert pickup_at(game, K).id == "attic_key"
    assert pickup_at(game, B) is None and pickup_at(game, G) is None
    assert pickup_at(SimpleNamespace(content=None), 0) is None
    look = game.content.text_ids["Look"]
    assert action_ids(game, K) == (look,)
    take(game, K)
    assert "has_key" in game.content.flags
    assert game.shown == [game.content.text_ids["A small brass key."]]
    use(game, K, look)
    assert game.shown[1] == game.content.text_ids["It is warm to the touch."]
    with pytest.raises(ValueError, match="object 0 does not expose inventory action 23"):
        use(game, K, 23)


def test_step_triggers_fires_on_the_entry_edge_only():
    hero = _hero(3231, 0, -2000)
    game = _stub(hero)
    blocking = game.content.text_ids["Something heavy blocks the doorway."]
    step_triggers(game)
    assert game.shown == [] and game.content_state[G]["inside"] is False
    hero.room_z = -2900                          # in the box
    step_triggers(game)
    step_triggers(game)                          # standing inside: no second firing
    assert game.shown == [blocking] and game.content_state[G]["inside"] is True
    hero.room_z = -2000
    step_triggers(game)
    assert game.content_state[G]["inside"] is False and game.shown == [blocking]
    hero.room_z = -2900
    step_triggers(game)
    assert game.shown == [blocking, blocking]    # re-entry fires again
    hero.room_z = -2000
    step_triggers(game)
    hero.room = 1                                # another room: outside even inside the box
    hero.room_z = -2900
    step_triggers(game)
    assert game.shown == [blocking, blocking]
    hero.room = 0
    game.current_floor = 1
    step_triggers(game)
    assert game.shown == [blocking, blocking]
    game.current_floor = 0
    game.content_state[G]["armed"] = False
    step_triggers(game)
    assert game.shown == [blocking, blocking] and game.content_state[G]["inside"] is False
    game.current_camera_target_actor = -1
    step_triggers(game)                          # no hero: nothing to test, nothing raised
    assert step_triggers(SimpleNamespace(content=None)) is None


def test_the_box_bounds_are_inclusive():
    hero = _hero(2800, -500, -3100)
    game = _stub(hero)
    step_triggers(game)
    assert game.content_state[G]["inside"] is True
    hero.room_x = 3701
    game.content_state[G]["inside"] = False
    step_triggers(game)
    assert game.content_state[G]["inside"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_objects.py -q`
Expected: FAIL at import (`No module named 'PyAitD.engine.content.objects'`).

- [ ] **Step 3: Move the message primitive onto `Game`**

In `PyAitD/engine/script/game/state.py`, extend the effects import and add the method after `close_modal`:

```python
from PyAitD.engine.script.effects import GameMode, ImmediateEffect, InputMode, MODAL_MODE, TimedMessage
```

```python
    def add_message(self, message_id):
        """Show a timed message: refresh the age of one already showing,
        else take the first free slot (FITD's five-line message table)."""
        for message in self.messages:
            if message is not None and message.message_id == message_id:
                message.age = 0
                return
        for slot, message in enumerate(self.messages):
            if message is None:
                self.messages[slot] = TimedMessage(message_id)
                return
```

In `PyAitD/engine/script/interaction/life_cont.py` delete `_add_message` (lines 42-50), drop `TimedMessage` from its import, and change the drain's call to `game.add_message(effect.message_id)`. Run `rg -n "_add_message" PyAitD tests` and update any other caller the same way.

- [ ] **Step 4: Write the rule engine**

Create `PyAitD/engine/content/objects.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""The object vocabulary at run time: conditions, rules and effects for
pickups and triggers (spec section 3). Reads world records and the pack's
flags only; the one primitive it calls is delete_object, as LM_DELETE does.
Never raises on game state."""
from PyAitD.engine.content.schema import TriggerRecord
from PyAitD.engine.script.game.objects import delete_object

IN_INVENTORY = 0x8000   # WorldObject.found_flag bit _finish_take sets and remove_from_inventory clears


def _in_inventory(game, pack_id):
    return bool(game.world_objects[game.content.by_id[pack_id]].found_flag & IN_INVENTORY)


def holds(game, condition):
    """Whether a rule's `when` holds: every named part, conjunctively."""
    flags = game.content.flags
    if condition.flag is not None and condition.flag not in flags:
        return False
    if condition.not_flag is not None and condition.not_flag in flags:
        return False
    if condition.has_item is not None and not _in_inventory(game, condition.has_item):
        return False
    if condition.not_item is not None and _in_inventory(game, condition.not_item):
        return False
    return True


def _apply(game, effect):
    content = game.content
    if effect.op == "message":
        game.add_message(content.text_ids[effect.arg])
    elif effect.op == "set_flag":
        content.flags.add(effect.arg)
    elif effect.op == "clear_flag":
        content.flags.discard(effect.arg)
    else:   # remove_item, delete_object
        idx = content.by_id[effect.arg]
        if isinstance(content.records[idx], TriggerRecord):
            game.content_state[idx]["armed"] = False   # a trigger has no actor to delete
        else:
            delete_object(game, idx)                   # un-places, releases the actor, leaves the inventory


def run_rules(game, rules):
    """Apply the first rule whose condition holds; True if one fired."""
    for rule in rules:
        if holds(game, rule.when):
            for effect in rule.then:
                _apply(game, effect)
            return True
    return False


def pickup_at(game, world_idx):
    """The PickupRecord behind a world index, or None for anything else
    (vanilla objects, other pack kinds, no pack)."""
    content = game.content
    if content is None:
        return None
    record = content.record_for(world_idx)
    return record if record is not None and record.kind == "pickup" else None


def action_ids(game, world_idx):
    """The pickup's inventory verbs as text ids, in pack order."""
    return tuple(game.content.text_ids[action.label] for action in pickup_at(game, world_idx).actions)


def take(game, world_idx):
    """Run on_take; the caller has already finished the vanilla take, so
    has_item conditions see the item."""
    run_rules(game, pickup_at(game, world_idx).on_take)


def use(game, world_idx, text_id):
    """Run the action whose label carries `text_id`."""
    for action in pickup_at(game, world_idx).actions:
        if game.content.text_ids[action.label] == text_id:
            run_rules(game, (action.rule,))
            return
    raise ValueError(f"object {world_idx} does not expose inventory action {text_id}")


def _hero_inside(game, hero, record):
    if game.current_floor != record.stage or hero.room != record.room:
        return False
    x0, x1, y0, y1, z0, z1 = record.box
    return x0 <= hero.room_x <= x1 and y0 <= hero.room_y <= y1 and z0 <= hero.room_z <= z1


def step_triggers(game):
    """Once per tick: every armed trigger fires on_enter on the edge from
    outside to inside, tracked in content_state[idx]["inside"]."""
    content = game.content
    if content is None:
        return
    hero_idx = game.current_camera_target_actor
    hero = None if hero_idx == -1 else game.actors[hero_idx]
    for idx, record in content.records.items():
        if not isinstance(record, TriggerRecord):
            continue
        state = game.content_state[idx]
        if not state["armed"]:
            continue
        inside = hero is not None and _hero_inside(game, hero, record)
        if inside == state["inside"]:
            continue
        state["inside"] = inside
        if game.trace is not None:
            game.trace.log_behaviour(game, idx, "enter" if inside else "leave")
        if inside:
            run_rules(game, record.on_enter)
```

Add to `PyAitD/engine/content/__init__.py`:

```python
from PyAitD.engine.content.objects import action_ids, holds, pickup_at, run_rules, step_triggers, take, use
```

- [ ] **Step 5: Run the tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_objects.py tests/test_interaction.py tests/test_life_interaction_ops.py tests/test_layering.py -q`
Expected: PASS (the layering test confirms `content/objects.py` imports only leaf modules).

- [ ] **Step 6: Commit**

```bash
git add PyAitD/engine/content/objects.py PyAitD/engine/content/__init__.py PyAitD/engine/script/game/state.py PyAitD/engine/script/interaction/life_cont.py tests/test_content_objects.py
git commit -m "feat(content): the rule engine — conditions, effects, pickups, trigger step"
```

---

### Task 6: The interaction hooks and the pickup journey

Three guarded delegations, then the real attic: touch the key, read its pack name in the prompt, take it, use it from the inventory.

**Files:**
- Modify: `PyAitD/engine/script/interaction/life_cont.py:81-90` (`execute_found_life`)
- Modify: `PyAitD/engine/script/interaction/inventory.py:25-27,105-109`
- Test: `tests/test_content_objects.py`

**Interfaces:**
- Consumes: `pickup_at`, `take`, `action_ids`, `use` from Task 5.
- Produces: vanilla objects unchanged; a pack pickup's take runs `on_take`, its inventory lists its pack actions, choosing one runs its rule.

- [ ] **Step 1: Write the failing journey tests**

Append to `tests/test_content_objects.py` (imports at the top of the file):

```python
from PyAitD.engine.content import load_pack
from PyAitD.engine.data.floor import Floor
from PyAitD.engine.script.effects import FoundResult, InputMode, ShowFound
from PyAitD.engine.script.game import init_game, relocate_actor
from PyAitD.engine.script.game.objects import delete_object
from PyAitD.engine.script.interaction import (
    apply_found_result, choose_inventory_action, inventory_actions, inventory_items,
)
from PyAitD.engine.script.playworld import IDLE, PlayInput, play_tick
```

```python
# ── the example scene against the real attic ─────────────────────────────────

PROWLER, WATCHER, KEY_IDX, BARRICADE_IDX, GATE_IDX = 292, 293, 294, 295, 296
FORWARD = PlayInput(joyd=1)   # keyboard mode: bit 0 walks forward, ~25 units a tick, along -z from the start


def _boot(data_dir, profile, example_pack_dir):
    pack = load_pack(example_pack_dir, data_dir, profile)
    game = init_game(data_dir, profile, pack=pack)
    game.num_camera = game.new_num_camera
    game.input_mode = InputMode.KEYBOARD   # the mouse route walks only toward a nav intent
    delete_object(game, PROWLER)           # the pursuer would reach the hero mid-scene
    delete_object(game, WATCHER)
    floor = Floor(data_dir, 0, profile)
    for _ in range(3):
        play_tick(game, floor, IDLE)       # commits the spawn's pending anims
    return game, floor, game.actors[game.current_camera_target_actor]


def _walk_until(game, floor, predicate, *, limit):
    for tick in range(limit):
        play_tick(game, floor, FORWARD)
        if predicate(game):
            return tick
    return -1


def _shown(game):
    return {m.message_id for m in game.messages if m is not None}


def _reach_the_key(game, floor):
    assert _walk_until(game, floor, lambda g: g.active_modal is not None, limit=60) != -1
    assert isinstance(game.active_modal, ShowFound)
    assert (game.active_modal.object_idx, game.active_modal.forced_refuse) == (KEY_IDX, False)


def test_touching_the_key_prompts_with_its_pack_name_and_taking_it_runs_on_take(data_dir, profile, example_pack_dir):
    game, floor, hero = _boot(data_dir, profile, example_pack_dir)
    texts = game.content.text_ids
    _reach_the_key(game, floor)
    assert game.assets.system_text(game.world_objects[KEY_IDX].found_name) == "Attic key"
    assert apply_found_result(game, FoundResult.TAKE) is True
    assert game.active_modal is None
    assert KEY_IDX in inventory_items(game)
    key = game.world_objects[KEY_IDX]
    assert key.found_flag & 0x8000 and (key.room, key.obj_index) == (-1, -1)
    assert "has_key" in game.content.flags
    assert texts["A small brass key."] in _shown(game)
    assert game.assets.system_text(texts["A small brass key."]) == "A small brass key."


def test_the_inventory_lists_the_pack_action_and_choosing_it_runs_its_rule(data_dir, profile, example_pack_dir):
    game, floor, hero = _boot(data_dir, profile, example_pack_dir)
    texts = game.content.text_ids
    _reach_the_key(game, floor)
    apply_found_result(game, FoundResult.TAKE)
    look = texts["Look"]
    assert inventory_actions(game, KEY_IDX) == (look,)
    assert choose_inventory_action(game, KEY_IDX, look) is True
    assert texts["It is warm to the touch."] in _shown(game)
    assert game.in_hand_table[game.current_inventory] == KEY_IDX
    with pytest.raises(ValueError, match="does not expose inventory action 23"):
        choose_inventory_action(game, KEY_IDX, 23)
    before = _shown(game)
    play_tick(game, floor, IDLE)   # the in-hand item's per-tick found-life is a no-op for a pack pickup
    assert _shown(game) == before and game.active_modal is None


def test_leaving_the_key_arms_the_vanilla_cooldown(data_dir, profile, example_pack_dir):
    game, floor, hero = _boot(data_dir, profile, example_pack_dir)
    _reach_the_key(game, floor)
    assert apply_found_result(game, FoundResult.LEAVE) is True
    assert game.world_objects[KEY_IDX].track_number == game.timer
    assert _walk_until(game, floor, lambda g: g.active_modal is not None, limit=20) == -1
    assert KEY_IDX not in inventory_items(game) and "has_key" not in game.content.flags
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_objects.py -q -k "key or inventory_lists"`
Expected: the take test FAILS on `"has_key" in game.content.flags` (the take finishes but no rule runs); the inventory test FAILS on `inventory_actions == (look,)` (returns `()`).

- [ ] **Step 3: Add the three delegations**

Both imports of `engine.content.objects` are lazy, inside the functions:
`engine.content` imports `actor.anim_action`, which imports the interaction
package at module level, so a module-level import here would be a cycle
(the same reason the existing `_finish_take` import is lazy).

`PyAitD/engine/script/interaction/life_cont.py`:

```python
def execute_found_life(game, object_idx, *, after=AfterLife.NONE):
    # interaction subpackage cycle: lazy; content reaches interaction through actor.anim_action
    from PyAitD.engine.script.interaction.inventory import _finish_take
    from PyAitD.engine.content.objects import pickup_at, take
    if object_idx == -1:
        return True
    if pickup_at(game, object_idx) is not None:
        # a pack pickup has no LIFE: finish the vanilla take, then its on_take rules
        if after is AfterLife.FINISH_TAKE:
            _finish_take(game, object_idx)
            take(game, object_idx)
        return True
    world = game.world_objects[object_idx]
    if world.found_life == -1:
        ...
```

`PyAitD/engine/script/interaction/inventory.py`:

```python
def inventory_actions(game, object_idx):
    from PyAitD.engine.content.objects import action_ids, pickup_at   # content reaches interaction through actor.anim_action: lazy
    if pickup_at(game, object_idx) is not None:
        return action_ids(game, object_idx)   # at most MAX_VISIBLE_ACTIONS, checked at load
    flags = game.world_objects[object_idx].found_flag
    return tuple(23 + bit for bit in range(11) if flags & (1 << bit))[:MAX_VISIBLE_ACTIONS]
```

```python
def choose_inventory_action(game, object_idx, action_text_id):
    from PyAitD.engine.content.objects import pickup_at, use   # lazy, as above
    if action_text_id not in inventory_actions(game, object_idx):
        raise ValueError(f"object {object_idx} does not expose inventory action {action_text_id}")
    game.in_hand_table[game.current_inventory] = object_idx
    if pickup_at(game, object_idx) is not None:
        use(game, object_idx, action_text_id)   # a pack verb is a rule, not a LIFE with game.action set
        return True
    game.action = 1 << (action_text_id - 23)
    return execute_found_life(game, object_idx)
```

- [ ] **Step 4: Run the tests and the suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_objects.py -q`, then `make test`.
Expected: PASS. The controls golden is untouched (no pack, so `pickup_at` is `None` everywhere).

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/script/interaction/life_cont.py PyAitD/engine/script/interaction/inventory.py tests/test_content_objects.py
git commit -m "feat(content): pack pickups take and act through the vanilla found and inventory paths"
```

---

### Task 7: Triggers in the tick, the barricade journeys, the mid-scene save

**Files:**
- Modify: `PyAitD/engine/script/playworld/tick.py:10,55-69`
- Test: `tests/test_content_objects.py`

**Interfaces:**
- Consumes: `step_triggers` (Task 5), `Trace.log_behaviour`.
- Produces: `play_tick` steps triggers after the per-actor loop.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_content_objects.py` (add `import json` and these imports at the top):

```python
from PyAitD.engine.script.save import SaveError, restore_game, snapshot_game, validate_snapshot

SETTINGS = {"schema": 2, "sticky_action": False, "bindings": {}, "render": {}}
```

```python
def test_without_the_key_the_gate_explains_and_the_barricade_stands(data_dir, profile, example_pack_dir):
    game, floor, hero = _boot(data_dir, profile, example_pack_dir)
    texts = game.content.text_ids
    _reach_the_key(game, floor)
    apply_found_result(game, FoundResult.LEAVE)
    entered = _walk_until(game, floor, lambda g: g.content_state[GATE_IDX]["inside"], limit=60)
    assert entered != -1
    assert -3100 <= hero.room_z <= -2700
    assert texts["Something heavy blocks the doorway."] in _shown(game)
    assert texts["The barricade gives way."] not in _shown(game)
    assert game.content_state[GATE_IDX]["armed"] is True
    assert game.world_objects[BARRICADE_IDX].room == 0
    barricade_slot = game.world_objects[BARRICADE_IDX].obj_index
    blocked = _walk_until(game, floor, lambda g: barricade_slot in hero.col, limit=60)
    assert blocked != -1, "the hero never met the barricade"
    assert hero.room_z > -3200                    # the crate's near face is at -3160
    assert game.active_modal is None


def test_with_the_key_the_gate_clears_the_barricade_and_disarms_itself(data_dir, profile, example_pack_dir):
    game, floor, hero = _boot(data_dir, profile, example_pack_dir)
    texts = game.content.text_ids
    _reach_the_key(game, floor)
    apply_found_result(game, FoundResult.TAKE)
    entered = _walk_until(game, floor, lambda g: g.content_state[GATE_IDX]["inside"], limit=60)
    assert entered != -1
    assert texts["The barricade gives way."] in _shown(game)
    assert texts["Something heavy blocks the doorway."] not in _shown(game)
    barricade = game.world_objects[BARRICADE_IDX]
    assert (barricade.room, barricade.stage, barricade.obj_index) == (-1, -1, -1)
    assert game.content_state[GATE_IDX] == {"armed": False, "inside": True}
    passed = _walk_until(game, floor, lambda g: hero.room_z < -3600, limit=80)
    assert passed != -1, "the way past the barricade did not open"
    assert hero.col == [-1, -1, -1]


def test_a_trigger_in_the_loop_fires_on_entry_only_and_again_after_leaving(data_dir, profile, example_pack_dir):
    game, floor, hero = _boot(data_dir, profile, example_pack_dir)
    hero_idx = game.current_camera_target_actor
    blocking = game.content.text_ids["Something heavy blocks the doorway."]

    def age():
        return next(m.age for m in game.messages if m is not None and m.message_id == blocking)

    relocate_actor(game, hero_idx, 0, 0, 3231, 0, -2900)
    play_tick(game, floor, IDLE)
    fresh = age()                                 # 0 or 1: advance_messages runs later in the same tick
    assert fresh <= 1 and game.content_state[GATE_IDX]["inside"] is True
    for _ in range(10):
        play_tick(game, floor, IDLE)
    assert age() == fresh + 10                    # standing inside never re-fires
    relocate_actor(game, hero_idx, 0, 0, 3231, 0, -2000)
    play_tick(game, floor, IDLE)
    assert game.content_state[GATE_IDX]["inside"] is False and age() == fresh + 11
    relocate_actor(game, hero_idx, 0, 0, 3231, 0, -2900)
    play_tick(game, floor, IDLE)
    assert age() == fresh                         # re-entry refreshes the message: fired again


def test_the_trace_records_trigger_transitions(data_dir, profile, example_pack_dir, tmp_path):
    from PyAitD.engine.script.life import Trace
    game, floor, hero = _boot(data_dir, profile, example_pack_dir)
    hero_idx = game.current_camera_target_actor
    game.trace = Trace(tmp_path / "t.log")
    relocate_actor(game, hero_idx, 0, 0, 3231, 0, -2900)
    play_tick(game, floor, IDLE)
    entered = game.timer
    relocate_actor(game, hero_idx, 0, 0, 3231, 0, -2000)
    play_tick(game, floor, IDLE)
    game.trace.close()
    lines = (tmp_path / "t.log").read_text().splitlines()
    assert f"{entered} {GATE_IDX} BEHAVIOUR enter" in lines
    assert f"{game.timer} {GATE_IDX} BEHAVIOUR leave" in lines


def test_a_mid_scene_save_round_trips_flags_trigger_state_and_the_inventory(data_dir, profile, example_pack_dir):
    game, floor, hero = _boot(data_dir, profile, example_pack_dir)
    _reach_the_key(game, floor)
    apply_found_result(game, FoundResult.TAKE)
    assert _walk_until(game, floor, lambda g: g.content_state[GATE_IDX]["inside"], limit=60) != -1
    payload = json.loads(json.dumps(snapshot_game(game, SETTINGS)))
    assert payload["schema"] == 4
    assert payload["content_flags"] == ["has_key"]
    assert payload["content_state"]["296"] == {"armed": False, "inside": True}
    restored, _ = restore_game(data_dir, profile, payload, pack=game.pack)
    assert restored.content.flags == {"has_key"}
    assert restored.content_state == game.content_state
    assert KEY_IDX in inventory_items(restored)
    assert restored.world_objects[BARRICADE_IDX].room == -1
    assert restored.assets.system_text(restored.world_objects[KEY_IDX].found_name) == "Attic key"
    assert {m.message_id for m in restored.messages if m} == _shown(game)
    old = copy.deepcopy(payload)
    old["schema"] = 3
    with pytest.raises(SaveError, match="expected schema 4, got 3"):
        validate_snapshot(old, data_dir, profile, pack=game.pack)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_objects.py -q -k "gate or trigger_in_the_loop or trace_records_trigger or mid_scene"`
Expected: FAIL (`inside` never becomes true: nothing steps the triggers).

- [ ] **Step 3: Step the triggers from the tick**

In `PyAitD/engine/script/playworld/tick.py`, extend the content import and add the call after the per-actor loop, before the game-over handoff:

```python
from PyAitD.engine.content import BEHAVIOUR_LIFE, run_behaviour, step_triggers
```

```python
        if game.flag_change_etage:
            break
    if game.content is not None and not game.flag_change_etage:
        step_triggers(game)   # pack zones: same tick as the step that entered them
    if not _handoff_game_over(game):
        return False
```

- [ ] **Step 4: Run the tests and the suite**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_objects.py -q`, then `make test`.
Expected: PASS, including `test_an_empty_pack_ticks_identically_to_no_pack` (an empty pack has no triggers, so the call is a loop over nothing).

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/script/playworld/tick.py tests/test_content_objects.py
git commit -m "feat(content): triggers step from the tick; the barricade journeys and the mid-scene save"
```

---

### Task 8: The scene through the real loop, docs and version

**Files:**
- Create: `tests/test_content_objects_loop.py`
- Modify: `pyproject.toml` (version), `PyAitD/__init__.py` (`__version__`), `CONTEXT.md:13,91,565-578`, `README.md:128-138`, `AGENTS.md:149-163`

**Interfaces:**
- Consumes: the harness helpers of `tests/test_controls_golden.py` (`_HeadlessRenderer`, `_pygame_runtime`, `_key_down`, `_key_up`, `_FRAME`), `ModalSession`.
- Produces: version 0.10.0; docs naming `objects/`, the three kinds, the effect vocabulary and the text-id convention.

- [ ] **Step 1: Write the failing real-loop test**

Create `tests/test_content_objects_loop.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""The example pack's key-and-barricade scene played through the real
shell.run event pump: keyboard mode, walk, take the key from the found
prompt, walk on through the gate and past where the barricade stood."""
import itertools
from types import SimpleNamespace

import pygame
import pytest

from PyAitD.app.ui import ModalSession
from PyAitD.engine.content import load_pack
from PyAitD.engine.script.game import init_game
from PyAitD.engine.script.game.objects import delete_object
from tests.test_controls_golden import _FRAME, _HeadlessRenderer, _key_down, _key_up, _pygame_runtime

pytestmark = [pytest.mark.shell, pytest.mark.journey]

KEY_IDX, BARRICADE_IDX, GATE_IDX = 294, 295, 296


def _script():
    """One list of events per pumped frame (one 20 ms tick each)."""
    frames = []

    def quiet(n):
        frames.extend([[] for _ in range(n)])

    quiet(5)
    frames.append([_key_down(pygame.K_TAB)])      # keyboard mode
    quiet(3)
    frames.append([_key_down(pygame.K_UP)])       # the key is 700 units ahead: prompt around tick 15
    quiet(60)
    frames.append([_key_up(pygame.K_UP)])
    frames.append([_key_down(pygame.K_RIGHT)])    # highlight Take
    frames.append([_key_up(pygame.K_RIGHT)])
    frames.append([_key_down(pygame.K_RETURN)])   # confirm
    frames.append([_key_up(pygame.K_RETURN)])
    quiet(5)
    frames.append([_key_down(pygame.K_UP)])       # on through the gate and past the barricade
    quiet(150)
    frames.append([_key_up(pygame.K_UP)])
    frames.append([pygame.event.Event(pygame.QUIT)])
    return frames


def test_the_scene_plays_through_the_real_loop(data_dir, profile, example_pack_dir, monkeypatch, tmp_path):
    import PyAitD.app.shell as main

    pack = load_pack(example_pack_dir, data_dir, profile)
    game = init_game(data_dir, profile, pack=pack)
    game.num_camera = game.new_num_camera
    game.rng.seed(7)
    delete_object(game, 292)   # the prowler would reach the hero mid-scene
    delete_object(game, 293)
    session = ModalSession(settings_path=tmp_path / "settings.json")
    frames = iter(_script())
    ticks = itertools.count(0, 20)
    seen = set()
    hero_idx = game.current_camera_target_actor
    real_play_tick = main.play_tick

    def spy(current, floor, snapshot):
        result = real_play_tick(current, floor, snapshot)
        seen.update(m.message_id for m in current.messages if m is not None)
        return result

    renderer = _HeadlessRenderer()
    monkeypatch.setattr(main, "Renderer", lambda *_a, **_k: renderer)
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (_FRAME, []))
    monkeypatch.setattr(main, "play_tick", spy)
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(frames))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(ticks))
    monkeypatch.setattr(main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *args: None))
    monkeypatch.setattr(main.pygame.display, "set_caption", lambda *args: None)
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda *args: None)
    with _pygame_runtime():
        assert main.run(game, session=session) == 0
    assert renderer.presented > 0

    texts = game.content.text_ids
    assert game.world_objects[KEY_IDX].found_flag & 0x8000, "the key was not taken"
    assert "has_key" in game.content.flags
    assert texts["A small brass key."] in seen
    assert texts["The barricade gives way."] in seen
    assert texts["Something heavy blocks the doorway."] not in seen
    assert game.world_objects[BARRICADE_IDX].room == -1
    assert game.content_state[GATE_IDX] == {"armed": False, "inside": True}   # disarmed: keeps its last value
    assert game.actors[hero_idx].room_z < -3600, "the hero did not walk past the barricade"
```

- [ ] **Step 2: Run the test to verify it fails or passes for the right reason**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_objects_loop.py -q`
Expected: PASS if Tasks 1–7 are correct. If it fails, the assertion names the stage that broke (key not taken: the modal keys; no gate message: the walk; barricade still placed: the effect). Fix the cause in the engine, never by loosening the assertion.

- [ ] **Step 3: Version and docs**

- `pyproject.toml`: `version = "0.10.0"`. `PyAitD/__init__.py`: `__version__ = "0.10.0"`. `CONTEXT.md:13`: `Version 0.10.0`.
- `CONTEXT.md:91`, the `engine/content/` row: add `objects.py` rules, effects, pickup helpers and the trigger step.
- `CONTEXT.md:565-578`: the pack bullet lists `pack.toml` + `enemies/*.toml` + `objects/*.toml`; the runtime-surface bullet reads `game.content` (records by world index, `by_id`, `text_ids`, `flags`) and `game.content_state[world_idx]` = `{"hp", "phase"}` for an enemy, `{"armed", "inside"}` for a trigger, `{}` otherwise; saves are schema 4 with `content_flags`. Add one bullet: pack effects reach pack state only (objects by pack id, flags by name); a `vanilla:` address prefix is reserved for sub-project 4, not implemented; triggers are zones stepped by `step_triggers` after the actor loop, never actors, because a body-less actor blocks the hero.
- `README.md:128-138` ("Content packs"): replace the paragraph with:

  ```
  A content pack is a directory holding `pack.toml` (`name`, `version`,
  `game = "aitd1"`), `enemies/*.toml` and `objects/*.toml`, one record per
  file. Enemies copy a body and animation set from an original creature:
  `pursuer` chases and strikes, `sentry` stands, turns and strikes in range.
  Objects come in three kinds with pack-supplied strings: a `pickup` the hero
  takes from the found prompt and uses from the inventory, `scenery` that
  blocks or, when `pushable`, is pushed, and a `trigger` box that fires when
  the hero walks in. Takes, inventory verbs and entries run rules — the first
  whose `when` (pack flags, items held) holds — with five effects: `message`,
  `set_flag`, `clear_flag`, `remove_item`, `delete_object`. The original
  scripts stay untouched; with no pack the game is byte-identical.
  `--content DIR` is session-only. A bad pack stops the boot with the file,
  key and value. Saves record the pack's digest and refuse to load against a
  different pack or none. `packs/example/` is the reference pack: two
  enemies and a key-and-barricade scene in the attic, exercised by the test
  suite.
  ```

- `AGENTS.md:149-163` ("Content packs"): add `tests/test_content_objects.py` (rules and object journeys) and `tests/test_content_objects_loop.py` (the scene through `shell.run`) to the test-split sentence, and one convention bullet: pack strings live in the assets text table from id 2000 (`engine/content/world.py:CONTENT_TEXT_BASE`, registered by `attach`); UI code resolves every name, verb and message through `assets.system_text` and never special-cases packs.

- [ ] **Step 4: Run the suite**

Run: `make test`
Expected: PASS (`tests/test_save.py::test_engine_version_matches_pyproject` checks the version pair).

- [ ] **Step 5: Commit**

```bash
git add tests/test_content_objects_loop.py pyproject.toml PyAitD/__init__.py CONTEXT.md README.md AGENTS.md
git commit -m "feat(content): the scene through the real loop; docs and v0.10.0"
```
