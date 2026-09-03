# Content Packs: Foundation and Enemies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load a TOML content pack that adds enemies (pursuer, sentry) to the AITD1 port as appended world objects driven by one Python state machine, with save/load and a `--content` flag, while a game with no pack stays byte-identical.

**Architecture:** A pack compiles to `WorldObject` records appended after the 292 OBJETS.ITD records with `life = BEHAVIOUR_LIFE (-2)`; the existing spawn, collision, animation and hit code treat them as ordinary animated actors. `life_gate` admits only `life >= 0` to the LIFE VM; the per-actor loop in `play_tick` gains one `elif` that runs `run_behaviour` for `-2` actors in the same slot order. Behaviours call only the primitives the opcodes call (`init_deplacement`, `process_track`, `init_anim`, the new `arm_strike` extracted from `op_hit`, `delete_object`).

**Tech Stack:** Python 3.12 (`tomllib` from stdlib), pytest, the existing pygame-free `PyAitD/engine`. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-03-content-packs-foundation-and-enemies-design.md`

## Global Constraints

- `# SPDX-License-Identifier: GPL-2.0-only` is the first line of every new `.py` file (`tests/test_layering.py::test_every_python_file_starts_with_the_spdx_line`).
- Absolute imports only; no relative imports anywhere in `PyAitD/`.
- Every test file declares exactly one subject marker (`engine`, `render`, `shell`, `tools`, `meta`) as module-level `pytestmark`, plus `journey` for long real-data runs.
- Tests take game data from the `data_dir` fixture and the profile from the `profile` fixture; never import `AITD1` directly outside `tests/test_game_profile.py`.
- Run pytest headless: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest ...`. `make test` is the gate after every task.
- No new runtime dependency: pygame-ce + moderngl + numpy stay the whole set.
- `engine/content` may import `PyAitD.engine.data`, `.space`, `.actor`, `.script.game.state`, `.script.game.objects`, `.script.effects`, `.script.eval_var`, `.script.life`. Never `.script.playworld`, `.script.interaction`, `.nav`, `PyAitD.games`, or the presentation layer, and never the `PyAitD.engine.script.game` package itself.
- Never mass-reformat. No lint or typecheck is configured; the suite is the only gate.
- Commit messages end with the session's attribution trailer:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Wr26qgHgbV5RqX5VHn6Tjf
  ```
- Real numbers used throughout come from the real data: OBJETS.ITD has 292 records, `NUM_MAX_OBJECT` is 128, the hero's world index is `game.current_world_target` (1 in the attic), body archives hold 272 bodies and 305 anims for Carnby (`LISTBODY`/`LISTANIM`), the attic is floor 0 room 0, and the stair creature (world 21, body 24) uses anims stand 22 / walk 23 / attack 25 / hurt 21 / death 24 with `LM_HIT(25, frame 1, group 22, radius 400, force 1, next 22)`; it strikes from a Manhattan world distance of about 2000 and its follow gets no closer than about 800.

---

## File map

| File | Responsibility |
|---|---|
| `PyAitD/engine/actor/anim_action.py` | gains `arm_strike(actor, anim, frame, group, radius, force, next_anim) -> int` |
| `PyAitD/games/aitd1/life_ops.py:67-84` | `op_hit` delegates to `arm_strike` |
| `PyAitD/engine/script/life.py:228-229` | `life_gate` admits `life >= 0`; `Trace.log_behaviour` |
| `PyAitD/engine/content/__init__.py` | re-exports `BEHAVIOUR_LIFE`, `PackError`, `Pack`, `read_pack`, `load_pack`, `attach`, `run_behaviour` |
| `PyAitD/engine/content/schema.py` | `BEHAVIOUR_LIFE`, vocabularies, `PackError`, `Anims`, `Attack`, `EnemyRecord`, `parse_enemy` |
| `PyAitD/engine/content/pack.py` | `Pack`, `pack_digest`, `read_pack`, `check_archives`, `load_pack` |
| `PyAitD/engine/content/world.py` | `ContentAttachment`, `compile_record`, `attach` |
| `PyAitD/engine/content/enemies.py` | `enter_phase`, `step_enemy` (the state machine) |
| `PyAitD/engine/content/runner.py` | `run_behaviour(game, slot)` |
| `PyAitD/engine/script/game/state.py` | `Game(..., pack=None)`: `self.pack`, `self.content`, `self.content_state` |
| `PyAitD/engine/script/game/boot.py` | `init_game(..., pack=None)` attaches before spawning |
| `PyAitD/engine/script/playworld/tick.py` | the `elif actor.life == BEHAVIOUR_LIFE` branch |
| `PyAitD/engine/script/save.py` | `SCHEMA = 3`, `source.pack`, `content_state`, `pack=` on `validate_snapshot`/`read_slot`/`restore_game` |
| `PyAitD/app/shell.py` | `--content`, `load_pack` in `main`, `pack=` at the three `init_game` sites and the `restore_game`/`read_slot` sites |
| `packs/example/` | `pack.toml`, `enemies/prowler.toml`, `enemies/watcher.toml` |
| `Makefile`, `README.md`, `AGENTS.md`, `CONTEXT.md` | `content=DIR`, the "Content packs" sections |
| `tests/test_content_pack.py` | schema, reader, digest, archive checks, compile, attach, vanilla pins |
| `tests/test_content_enemies.py` | the state machine and the attic journeys |
| `tests/test_save.py`, `tests/test_main.py`, `tests/test_runtime_modes.py`, `tests/test_layering.py`, `tests/test_life_ops.py`, `tests/test_anim_action.py`, `tests/test_play_loop.py`, `tests/test_world_data.py`, `tests/conftest.py` | pins and fixtures named per task |

---

### Task 1: `arm_strike`, `life_gate >= 0`, and the data pin

Vanilla-only groundwork. After this task no behaviour changes for any original actor.

**Files:**
- Modify: `PyAitD/engine/actor/anim_action.py` (add `arm_strike` after `_publish_hit`, line 48)
- Modify: `PyAitD/games/aitd1/life_ops.py:67-84` (`op_hit`)
- Modify: `PyAitD/engine/script/life.py:228-229` (`life_gate`)
- Test: `tests/test_anim_action.py`, `tests/test_life_ops.py:106-157`, `tests/test_play_loop.py:18-27`, `tests/test_world_data.py`

**Interfaces:**
- Produces: `PyAitD.engine.actor.anim_action.arm_strike(actor, anim, frame, group, radius, force, next_anim) -> int` (1 when `init_anim` accepted and the six fields were written, else 0 and nothing written).
- Produces: `life_gate(actor)` is `actor.life >= 0 and actor.life_mode != -1`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_anim_action.py`:

```python
def test_arm_strike_writes_the_six_melee_fields_when_init_anim_accepts(data_dir, profile):
    from PyAitD.engine.actor.anim_action import arm_strike
    game = init_game(data_dir, profile)
    actor = game.actors[game.current_camera_target_actor]
    # the hero stands in anim 4 (repeat); anim 25 is a different, interruptible anim
    assert arm_strike(actor, 25, 1, 22, 400, 1, 22) == 1
    assert (actor.new_anim, actor.new_anim_type, actor.new_anim_info) == (25, 0, 22)
    assert (actor.anim_action_anim, actor.anim_action_frame, actor.anim_action_type) == (25, 1, 1)
    assert (actor.anim_action_param, actor.hot_point_id, actor.hit_force) == (400, 22, 1)


def test_arm_strike_leaves_every_field_alone_when_init_anim_refuses(data_dir, profile, monkeypatch):
    from PyAitD.engine.actor import anim_action
    game = init_game(data_dir, profile)
    actor = game.actors[game.current_camera_target_actor]
    actor.anim_action_type, actor.anim_action_anim, actor.anim_action_frame = 99, 55, 66
    actor.anim_action_param, actor.hot_point_id, actor.hit_force = 77, 88, 44
    monkeypatch.setattr(anim_action, "init_anim", lambda *args: 0)
    assert anim_action.arm_strike(actor, 25, 1, 22, 400, 1, 22) == 0
    assert (actor.anim_action_type, actor.anim_action_anim, actor.anim_action_frame) == (99, 55, 66)
    assert (actor.anim_action_param, actor.hot_point_id, actor.hit_force) == (77, 88, 44)
```

In `tests/test_life_ops.py`, `test_hit_fire_throw_arm_only_when_init_anim_accepts` (line 106) patches `PyAitD.games.aitd1.life_ops.init_anim`; `op_hit` will now call `init_anim` through `anim_action`. Add a second patch with the same lambda so the hit calls are still recorded:

```python
    accepted = iter((0, 1, 1, 1))
    calls = []
    fake = lambda current, anim, kind, nxt: calls.append((anim, kind, nxt)) or next(accepted)
    monkeypatch.setattr("PyAitD.games.aitd1.life_ops.init_anim", fake)
    monkeypatch.setattr("PyAitD.engine.actor.anim_action.init_anim", fake)
```

In `test_hit_rejected_by_init_anim_consumes_operands_and_leaves_state_alone` (line 136) replace the patch line with:

```python
    monkeypatch.setattr("PyAitD.engine.actor.anim_action.init_anim", lambda *args: 0)
```

In `tests/test_play_loop.py::test_life_gate` append:

```python
    # engine.content.BEHAVIOUR_LIFE: a behaviour-driven actor is not the VM's
    a.life, a.life_mode = -2, 1
    assert not life_gate(a)
```

Append to `tests/test_world_data.py`:

```python
def test_no_original_record_carries_a_life_below_minus_one(data_dir):
    # engine.content reserves life == -2 (BEHAVIOUR_LIFE) for pack actors and
    # life.life_gate admits only life >= 0 to the VM; both rest on this.
    raw = (pathlib.Path(data_dir) / "OBJETS.ITD").read_bytes()
    assert min(o.life for o in parse_objets(raw, has_mark=False)) == -1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_anim_action.py tests/test_life_ops.py tests/test_play_loop.py::test_life_gate tests/test_world_data.py -q`
Expected: the two `arm_strike` tests fail with `ImportError`/`AttributeError`; `test_life_gate` fails on the `-2` assertion; the two `test_life_ops.py` hit tests still pass (the extra patch is harmless); the data pin passes.

- [ ] **Step 3: Implement**

In `PyAitD/engine/actor/anim_action.py`, add to the imports:

```python
from PyAitD.engine.actor.anim import init_anim
```

and after `_publish_hit`:

```python
def arm_strike(actor, anim, frame, group, radius, force, next_anim):
    """main.cpp:4375 hit(): arm a melee strike only when InitAnim accepts the
    anim; a refusal leaves every field alone. Returns InitAnim's verdict.
    The one implementation of a strike, for LIFE's LM_HIT (life_ops.op_hit)
    and for engine.content behaviours alike."""
    accepted = init_anim(actor, anim, 0, next_anim)
    if accepted:
        actor.anim_action_anim = anim
        actor.anim_action_frame = frame
        actor.anim_action_type = 1
        actor.anim_action_param = radius
        actor.hot_point_id = group
        actor.hit_force = force
    return accepted
```

Replace `op_hit` in `PyAitD/games/aitd1/life_ops.py`:

```python
def op_hit(vm):
    # main.cpp:4375 hit(): arm melee only when InitAnim accepts the anim;
    # a rejection still consumes every operand but leaves prior state alone.
    from PyAitD.engine.actor.anim_action import arm_strike  # lazy like op_delete's: anim_action pulls in script.interaction
    anim = read_s16(vm)  # anim
    frame = read_s16(vm)  # startFrame
    group = read_s16(vm)  # groupNumber
    radius = read_s16(vm)  # hitBoxSize
    force = eval_var(vm)  # hitForce
    next_anim = read_s16(vm)  # nextAnim
    arm_strike(vm.actor, anim, frame, group, radius, force, next_anim)
```

Replace `life_gate` in `PyAitD/engine/script/life.py`:

```python
def life_gate(actor):
    # life >= 0 names a LISTLIFE script; -1 is none, and engine.content's
    # BEHAVIOUR_LIFE (-2) marks an actor a pack behaviour drives instead.
    return actor.life >= 0 and actor.life_mode != -1
```

- [ ] **Step 4: Run the tests and the whole suite**

Run: `make test`
Expected: all green (1689 passed / 3 skipped / 1 xfailed before this task, plus the three new tests).

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/actor/anim_action.py PyAitD/games/aitd1/life_ops.py PyAitD/engine/script/life.py tests/test_anim_action.py tests/test_life_ops.py tests/test_play_loop.py tests/test_world_data.py
git commit -m "refactor: extract arm_strike from op_hit; life_gate admits only life >= 0

Groundwork for content packs: one implementation of a melee strike for
scripts and behaviours, and a gate that leaves room for the -2 sentinel.
Pinned: no OBJETS.ITD record carries a life below -1."
```

---

### Task 2: The record schema and the package skeleton

**Files:**
- Create: `PyAitD/engine/content/__init__.py`, `PyAitD/engine/content/schema.py`
- Modify: `tests/test_layering.py` (`FORBIDDEN`, `PRESENTATION_FREE`)
- Test: `tests/test_content_pack.py` (new)

**Interfaces:**
- Produces: `schema.BEHAVIOUR_LIFE = -2`, `KINDS`, `ZV_TYPES`, `LIFE_MODES`, `PHASES`, `PackError(file, key, message)` (str is `f"{file}: {key}: {message}"`), frozen dataclasses `Anims(stand, walk, attack, hurt, death)` with `present() -> tuple[(key, int)]`, `Attack(frame, group, radius, force, range)`, `EnemyRecord(id, kind, body, stage, room, position, beta, type_zv, life_mode, falls, hit_points, anims, attack, file)`, and `parse_enemy(table: dict, file: str) -> EnemyRecord`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_content_pack.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""engine.content: pack records, the directory reader, archive checks, and
the world-object attachment (2026-09-03-content-packs-foundation-and-enemies-design.md)."""
import copy

import pytest

from PyAitD.engine.content.schema import (
    BEHAVIOUR_LIFE, PHASES, Anims, Attack, EnemyRecord, PackError, parse_enemy,
)

pytestmark = pytest.mark.engine

PROWLER = {
    "id": "prowler", "kind": "pursuer", "body": 24, "stage": 0, "room": 0,
    "position": [-5600, 0, 1000], "beta": 0, "zv": "max", "life_mode": "room",
    "falls": False, "hit_points": 3,
    "anims": {"stand": 22, "walk": 23, "attack": 25, "hurt": 21, "death": 24},
    "attack": {"frame": 1, "group": 22, "radius": 400, "force": 1, "range": 2000},
}


def _table(**changes):
    table = copy.deepcopy(PROWLER)
    for key, value in changes.items():
        if value is None:
            table.pop(key, None)
        else:
            table[key] = value
    return table


def test_sentinel_and_vocabularies_are_pinned():
    assert BEHAVIOUR_LIFE == -2
    assert PHASES == ("idle", "chase", "attack", "hurt", "dying", "dead")


def test_parse_enemy_builds_a_record_with_compiled_enums():
    record = parse_enemy(PROWLER, "enemies/prowler.toml")
    assert record == EnemyRecord(
        id="prowler", kind="pursuer", body=24, stage=0, room=0,
        position=(-5600, 0, 1000), beta=0, type_zv=0, life_mode=1, falls=False,
        hit_points=3,
        anims=Anims(stand=22, walk=23, attack=25, hurt=21, death=24),
        attack=Attack(frame=1, group=22, radius=400, force=1, range=2000),
        file="enemies/prowler.toml",
    )
    assert record.anims.present() == (("stand", 22), ("walk", 23), ("attack", 25), ("hurt", 21), ("death", 24))


def test_parse_enemy_defaults_beta_zv_life_mode_and_falls():
    record = parse_enemy(_table(beta=None, zv=None, life_mode=None, falls=None), "e.toml")
    assert (record.beta, record.type_zv, record.life_mode, record.falls) == (0, 0, 1, False)


def test_a_sentry_omits_walk_and_a_pursuer_requires_it():
    sentry = _table(kind="sentry", anims={"stand": 22, "attack": 25, "hurt": 21, "death": 24})
    assert parse_enemy(sentry, "e.toml").anims.walk is None
    assert parse_enemy(sentry, "e.toml").anims.present() == (("stand", 22), ("attack", 25), ("hurt", 21), ("death", 24))
    with pytest.raises(PackError, match=r"^e\.toml: anims\.walk: missing"):
        parse_enemy(_table(anims={"stand": 22, "attack": 25, "hurt": 21, "death": 24}), "e.toml")
    with pytest.raises(PackError, match=r"^e\.toml: anims\.walk: a sentry never walks"):
        parse_enemy(_table(kind="sentry"), "e.toml")


@pytest.mark.parametrize("changes, key, message", [
    ({"id": None}, "id", "missing"),
    ({"id": ""}, "id", "expected a non-empty string, got ''"),
    ({"kind": "boss"}, "kind", "'boss' is not one of pursuer, sentry"),
    ({"body": -1}, "body", "-1 is negative"),
    ({"body": 40000}, "body", "40000 is outside -32768..32767"),
    ({"body": "24"}, "body", "expected an integer, got '24'"),
    ({"body": True}, "body", "expected an integer, got True"),
    ({"stage": -1}, "stage", "-1 is negative"),
    ({"room": None}, "room", "missing"),
    ({"position": [1, 2]}, "position", "expected [x, y, z], got [1, 2]"),
    ({"position": [1, 2, 99999]}, "position[2]", "99999 is outside -32768..32767"),
    ({"beta": 1024}, "beta", "1024 is outside 0..1023"),
    ({"zv": "sphere"}, "zv", "'sphere' is not one of max, body, cube, rotated"),
    ({"life_mode": "camera"}, "life_mode", "'camera' is not one of stage, room"),
    ({"falls": 1}, "falls", "expected true or false, got 1"),
    ({"hit_points": 0}, "hit_points", "0 is below 1"),
    ({"anims": None}, "anims", "missing"),
    ({"anims": {"stand": 22, "walk": 23, "attack": 25, "hurt": 21}}, "anims.death", "missing"),
    ({"anims": {"stand": 22, "walk": -3, "attack": 25, "hurt": 21, "death": 24}}, "anims.walk", "-3 is negative"),
    ({"anims": {"stand": 22, "walk": 23, "attack": 25, "hurt": 21, "death": 24, "fly": 1}}, "anims.fly", "unknown key"),
    ({"attack": {"frame": 1, "group": 22, "radius": 400, "force": 1}}, "attack.range", "missing"),
    ({"attack": {"frame": 1, "group": 22, "radius": -1, "force": 1, "range": 2000}}, "attack.radius", "-1 is negative"),
    ({"colour": "red"}, "colour", "unknown key"),
])
def test_parse_enemy_names_file_key_and_value_on_every_failure(changes, key, message):
    with pytest.raises(PackError) as caught:
        parse_enemy(_table(**changes), "enemies/bad.toml")
    assert str(caught.value) == f"enemies/bad.toml: {key}: {message}"
    assert (caught.value.file, caught.value.key, caught.value.message) == ("enemies/bad.toml", key, message)


def test_parse_enemy_rejects_a_non_table():
    with pytest.raises(PackError, match=r"^e\.toml: root: expected a table"):
        parse_enemy(["not", "a", "table"], "e.toml")
```

Add to `tests/test_layering.py` `FORBIDDEN`, after the `"engine/space"` entry:

```python
    # Content packs (2026-09-03-content-packs-foundation-and-enemies-design.md):
    # content sits between script.game (which it imports, leaf modules only)
    # and script.playworld / save (which import it). Never the tick, the
    # interaction layer, navigation, or a game.
    "engine/content": PRESENTATION + (
        "PyAitD.games",
        "PyAitD.engine.script.playworld", "PyAitD.engine.script.interaction",
        "PyAitD.engine.nav",
    ),
```

and a `PRESENTATION_FREE` row before the `PyAitD.games.aitd1.mouse_contract` row:

```python
    ("PyAitD.engine.content", PRESENTATION,
     " — packs must load and their behaviours run headless, like the tick"),
```

Also add, next to `test_pure_render_modules_import_no_graphics_library`, the package-import rule the spec's cycle note requires:

```python
def test_content_never_imports_the_script_game_package_itself():
    # script.game's __init__ imports boot, and boot imports content (lazily,
    # in init_game); content importing the package back would be a partial
    # initialisation at boot time. Leaf modules (state, objects) are fine.
    package = "PyAitD.engine.script.game"
    leaves = {"state", "objects"}

    def offends(name):
        if name == package:
            return True
        if not name.startswith(package + "."):
            return False
        return name[len(package) + 1:].split(".")[0] not in leaves

    bad = [
        f"{path.name}: {name}"
        for path in _modules("engine/content")
        for name in _imports(path)
        if offends(name)
    ]
    assert bad == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_pack.py tests/test_layering.py -q`
Expected: `test_content_pack.py` fails at import (`ModuleNotFoundError: PyAitD.engine.content`); the layering test for `engine/content` fails with "no modules found under PyAitD/engine/content".

- [ ] **Step 3: Create the package and the schema**

`PyAitD/engine/content/__init__.py` (grows in later tasks; keep this exact form now):

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Content packs: TOML-authored enemies (later objects, scenarios, players)
run by a fixed vocabulary of Python behaviours over the same primitives the
LIFE opcodes call. Spec: docs/superpowers/specs/2026-09-03-content-packs-
foundation-and-enemies-design.md."""
from PyAitD.engine.content.schema import BEHAVIOUR_LIFE, PackError
```

`PyAitD/engine/content/schema.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Content pack records: the fixed vocabulary, parsed and range-checked.

Pure -- no archive access. `parse_enemy` turns one enemy TOML table into an
EnemyRecord or raises PackError naming the file, the key and the value.
Archive-dependent checks (body/anim counts, floor rooms) live in pack.py."""
from dataclasses import dataclass

BEHAVIOUR_LIFE = -2
"""WorldObject.life / Actor.life of a behaviour-driven actor. Every original
OBJETS.ITD record has life >= -1 (tests/test_world_data.py pins it) and
script.life.life_gate admits only life >= 0 to the VM, so -2 collides with
nothing and the VM never fetches it."""

KINDS = ("pursuer", "sentry")
ZV_TYPES = {"max": 0, "body": 1, "cube": 2, "rotated": 3}   # WorldObject.type_zv
LIFE_MODES = {"stage": 0, "room": 1}                         # WorldObject.life_mode
PHASES = ("idle", "chase", "attack", "hurt", "dying", "dead")
S16_MIN, S16_MAX = -32768, 32767
ENEMY_KEYS = frozenset({
    "id", "kind", "body", "stage", "room", "position", "beta", "zv",
    "life_mode", "falls", "hit_points", "anims", "attack",
})
ANIM_KEYS = ("stand", "walk", "attack", "hurt", "death")
ATTACK_KEYS = ("frame", "group", "radius", "force", "range")


class PackError(Exception):
    """A pack could not be read or validated: `file` is the path inside the
    pack, `key` the dotted TOML key (or `root`), `message` says what was
    wrong with the value."""

    def __init__(self, file, key, message):
        super().__init__(f"{file}: {key}: {message}")
        self.file = file
        self.key = key
        self.message = message


@dataclass(frozen=True)
class Anims:
    stand: int
    walk: int | None
    attack: int
    hurt: int
    death: int

    def present(self):
        """(key, anim) for every anim the record names, in ANIM_KEYS order."""
        return tuple((key, getattr(self, key)) for key in ANIM_KEYS if getattr(self, key) is not None)


@dataclass(frozen=True)
class Attack:
    frame: int
    group: int
    radius: int
    force: int
    range: int


@dataclass(frozen=True)
class EnemyRecord:
    id: str
    kind: str
    body: int
    stage: int
    room: int
    position: tuple
    beta: int
    type_zv: int
    life_mode: int
    falls: bool
    hit_points: int
    anims: Anims
    attack: Attack
    file: str


def _require(table, key, file, prefix=""):
    if key not in table:
        raise PackError(file, f"{prefix}{key}", "missing")
    return table[key]


def _s16(value, file, key):
    if type(value) is not int:
        raise PackError(file, key, f"expected an integer, got {value!r}")
    if not S16_MIN <= value <= S16_MAX:
        raise PackError(file, key, f"{value} is outside {S16_MIN}..{S16_MAX}")
    return value


def _non_negative(value, file, key):
    value = _s16(value, file, key)
    if value < 0:
        raise PackError(file, key, f"{value} is negative")
    return value


def _choice(value, choices, file, key):
    if value not in choices:
        raise PackError(file, key, f"{value!r} is not one of {', '.join(choices)}")
    return value


def _reject_unknown(table, allowed, file, prefix=""):
    unknown = sorted(set(table) - set(allowed))
    if unknown:
        raise PackError(file, f"{prefix}{unknown[0]}", "unknown key")


def _parse_anims(table, kind, file):
    if not isinstance(table, dict):
        raise PackError(file, "anims", f"expected a table, got {table!r}")
    _reject_unknown(table, ANIM_KEYS, file, "anims.")
    values = {}
    for key in ANIM_KEYS:
        if key == "walk":
            if kind == "sentry":
                if "walk" in table:
                    raise PackError(file, "anims.walk", "a sentry never walks")
                values["walk"] = None
                continue
        values[key] = _non_negative(_require(table, key, file, "anims."), file, f"anims.{key}")
    return Anims(**values)


def _parse_attack(table, file):
    if not isinstance(table, dict):
        raise PackError(file, "attack", f"expected a table, got {table!r}")
    _reject_unknown(table, ATTACK_KEYS, file, "attack.")
    return Attack(**{
        key: _non_negative(_require(table, key, file, "attack."), file, f"attack.{key}")
        for key in ATTACK_KEYS
    })


def parse_enemy(table, file):
    """One enemy TOML table -> EnemyRecord, or PackError(file, key, message)."""
    if not isinstance(table, dict):
        raise PackError(file, "root", "expected a table")
    _reject_unknown(table, ENEMY_KEYS, file)
    ident = _require(table, "id", file)
    if type(ident) is not str or not ident:
        raise PackError(file, "id", f"expected a non-empty string, got {ident!r}")
    kind = _choice(_require(table, "kind", file), KINDS, file, "kind")
    body = _non_negative(_require(table, "body", file), file, "body")
    stage = _non_negative(_require(table, "stage", file), file, "stage")
    room = _non_negative(_require(table, "room", file), file, "room")
    position = _require(table, "position", file)
    if not isinstance(position, list) or len(position) != 3:
        raise PackError(file, "position", f"expected [x, y, z], got {position!r}")
    position = tuple(_s16(value, file, f"position[{i}]") for i, value in enumerate(position))
    beta = _s16(table.get("beta", 0), file, "beta")
    if not 0 <= beta <= 1023:
        raise PackError(file, "beta", f"{beta} is outside 0..1023")
    type_zv = ZV_TYPES[_choice(table.get("zv", "max"), tuple(ZV_TYPES), file, "zv")]
    life_mode = LIFE_MODES[_choice(table.get("life_mode", "room"), tuple(LIFE_MODES), file, "life_mode")]
    falls = table.get("falls", False)
    if type(falls) is not bool:
        raise PackError(file, "falls", f"expected true or false, got {falls!r}")
    hit_points = _s16(_require(table, "hit_points", file), file, "hit_points")
    if hit_points < 1:
        raise PackError(file, "hit_points", f"{hit_points} is below 1")
    anims = _parse_anims(_require(table, "anims", file), kind, file)
    attack = _parse_attack(_require(table, "attack", file), file)
    return EnemyRecord(
        id=ident, kind=kind, body=body, stage=stage, room=room, position=position,
        beta=beta, type_zv=type_zv, life_mode=life_mode, falls=falls,
        hit_points=hit_points, anims=anims, attack=attack, file=file,
    )
```

- [ ] **Step 4: Run the tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_pack.py tests/test_layering.py -q`
Expected: PASS. Then `make test`: green.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/content tests/test_content_pack.py tests/test_layering.py
git commit -m "feat(content): pack record schema with file/key/value errors; layering pins for engine/content"
```

---

### Task 3: The pack directory reader, the digest, and the example pack

**Files:**
- Create: `PyAitD/engine/content/pack.py`, `packs/example/pack.toml`, `packs/example/enemies/prowler.toml`, `packs/example/enemies/watcher.toml`
- Modify: `PyAitD/engine/content/__init__.py`, `tests/conftest.py`
- Test: `tests/test_content_pack.py`

**Interfaces:**
- Produces: `pack.Pack(name, version, game, enemies: tuple[EnemyRecord], digest: str, path: Path)` with `identity() -> {"name", "version", "digest"}`; `pack_digest(root) -> str`; `read_pack(path) -> Pack` (no archive access); `PACK_FILE = "pack.toml"`.
- Produces: conftest fixture `example_pack_dir` -> `Path` of `packs/example`.

- [ ] **Step 1: Write the example pack**

`packs/example/pack.toml`:

```toml
name = "example"
version = "1"
game = "aitd1"
```

`packs/example/enemies/prowler.toml`:

```toml
# A third attic creature: the stair creature's body (world object 21, body
# 24) and its own animation set, placed where the window creature's entry
# track ends. Strike operands copied from LISTLIFE 21's LM_HIT (anim 25,
# frame 1, group 22, radius 400, force 1, next 22); it strikes from a
# Manhattan distance of about 2000 in the original, hence `range`.
id = "prowler"
kind = "pursuer"
body = 24
stage = 0
room = 0
position = [-5600, 0, 1000]
beta = 0
zv = "max"
life_mode = "room"
falls = false
hit_points = 3

[anims]
stand = 22
walk = 23
attack = 25
hurt = 21
death = 24

[attack]
frame = 1
group = 22
radius = 400
force = 1
range = 2000
```

`packs/example/enemies/watcher.toml`:

```toml
# The same creature standing guard in the attic's north-east, turning to
# face the hero and striking only when the hero walks into range.
id = "watcher"
kind = "sentry"
body = 24
stage = 0
room = 0
position = [2500, 0, 3500]
beta = 512
zv = "max"
life_mode = "room"
falls = false
hit_points = 2

[anims]
stand = 22
attack = 25
hurt = 21
death = 24

[attack]
frame = 1
group = 22
radius = 400
force = 1
range = 1500
```

Add to `tests/conftest.py` after the `profile` fixture:

```python
@pytest.fixture
def example_pack_dir():
    """The in-repo example content pack (packs/example), used by the
    content-pack tests and by `make run content=packs/example`."""
    return REPO_ROOT / "packs" / "example"
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_content_pack.py`:

```python
# ── the directory reader ─────────────────────────────────────────────────────

PACK_TOML = 'name = "t"\nversion = "1"\ngame = "aitd1"\n'
PROWLER_TOML = """
id = "prowler"
kind = "pursuer"
body = 24
stage = 0
room = 0
position = [-5600, 0, 1000]
hit_points = 3
[anims]
stand = 22
walk = 23
attack = 25
hurt = 21
death = 24
[attack]
frame = 1
group = 22
radius = 400
force = 1
range = 2000
"""


def _write_pack(root, enemies=(), manifest=PACK_TOML):
    root.mkdir(parents=True, exist_ok=True)
    (root / "pack.toml").write_text(manifest)
    if enemies:
        (root / "enemies").mkdir(exist_ok=True)
    for name, text in enemies:
        (root / "enemies" / name).write_text(text)
    return root


def test_read_pack_reads_the_manifest_and_every_enemy_in_name_order(tmp_path):
    from PyAitD.engine.content.pack import Pack, read_pack
    root = _write_pack(tmp_path / "p", [
        ("b.toml", PROWLER_TOML.replace('"prowler"', '"second"')),
        ("a.toml", PROWLER_TOML),
    ])
    pack = read_pack(root)
    assert isinstance(pack, Pack)
    assert (pack.name, pack.version, pack.game, pack.path) == ("t", "1", "aitd1", root)
    assert [e.id for e in pack.enemies] == ["prowler", "second"]
    assert [e.file for e in pack.enemies] == ["enemies/a.toml", "enemies/b.toml"]
    assert pack.identity() == {"name": "t", "version": "1", "digest": pack.digest}


def test_an_empty_pack_is_a_manifest_alone(tmp_path):
    from PyAitD.engine.content.pack import read_pack
    pack = read_pack(_write_pack(tmp_path / "p"))
    assert pack.enemies == ()


def test_read_pack_errors_name_the_file_and_key(tmp_path):
    from PyAitD.engine.content.pack import read_pack
    with pytest.raises(PackError, match=r"^pack\.toml: root: not found in "):
        read_pack(tmp_path / "missing")
    with pytest.raises(PackError, match=r"^pack\.toml: root: cannot parse: "):
        read_pack(_write_pack(tmp_path / "p1", manifest="name = \n"))
    with pytest.raises(PackError, match=r"^pack\.toml: root: expected exactly the keys \['game', 'name', 'version'\], got \['name'\]"):
        read_pack(_write_pack(tmp_path / "p2", manifest='name = "t"\n'))
    with pytest.raises(PackError, match=r"^pack\.toml: version: expected a non-empty string, got 1"):
        read_pack(_write_pack(tmp_path / "p3", manifest='name = "t"\nversion = 1\ngame = "aitd1"\n'))
    with pytest.raises(PackError, match=r"^enemies/x\.toml: root: cannot parse: "):
        read_pack(_write_pack(tmp_path / "p4", [("x.toml", "id = \n")]))
    with pytest.raises(PackError, match=r"^enemies/x\.toml: hit_points: missing"):
        read_pack(_write_pack(tmp_path / "p5", [("x.toml", PROWLER_TOML.replace("hit_points = 3\n", ""))]))
    with pytest.raises(PackError, match=r"^enemies/b\.toml: id: 'prowler' is already used by enemies/a\.toml"):
        read_pack(_write_pack(tmp_path / "p6", [("a.toml", PROWLER_TOML), ("b.toml", PROWLER_TOML)]))


def test_pack_digest_covers_every_toml_by_relative_path_and_is_order_free(tmp_path):
    from PyAitD.engine.content.pack import pack_digest
    a = _write_pack(tmp_path / "a", [("x.toml", PROWLER_TOML), ("y.toml", PROWLER_TOML.replace('"prowler"', '"y"'))])
    b = _write_pack(tmp_path / "b", [("y.toml", PROWLER_TOML.replace('"prowler"', '"y"')), ("x.toml", PROWLER_TOML)])
    assert pack_digest(a) == pack_digest(b)
    (a / "enemies" / "x.toml").write_text(PROWLER_TOML.replace("range = 2000", "range = 2001"))
    assert pack_digest(a) != pack_digest(b)
    (b / "enemies" / "x.toml").rename(b / "enemies" / "z.toml")
    assert pack_digest(a) != pack_digest(b)


def test_the_example_pack_reads(example_pack_dir):
    from PyAitD.engine.content.pack import read_pack
    pack = read_pack(example_pack_dir)
    assert (pack.name, pack.version, pack.game) == ("example", "1", "aitd1")
    assert [(e.id, e.kind) for e in pack.enemies] == [("prowler", "pursuer"), ("watcher", "sentry")]
    prowler, watcher = pack.enemies
    assert (prowler.body, prowler.position, prowler.hit_points) == (24, (-5600, 0, 1000), 3)
    assert (prowler.anims, prowler.attack) == (
        Anims(stand=22, walk=23, attack=25, hurt=21, death=24),
        Attack(frame=1, group=22, radius=400, force=1, range=2000),
    )
    assert (watcher.position, watcher.beta, watcher.anims.walk, watcher.attack.range) == ((2500, 0, 3500), 512, None, 1500)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_pack.py -q`
Expected: the new tests fail with `ModuleNotFoundError: PyAitD.engine.content.pack`.

- [ ] **Step 4: Implement the reader**

`PyAitD/engine/content/pack.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Pack directory reader: pack.toml + enemies/*.toml, the identity digest,
and the archive-dependent checks (body/anim counts for every hero, floor
rooms). `read_pack` needs no game data; `load_pack` needs it."""
import hashlib
import pathlib
import tomllib
from dataclasses import dataclass

from PyAitD.engine.content.schema import PackError, parse_enemy
from PyAitD.engine.data.floor import Floor
from PyAitD.engine.data.pak import Pak, PakError, find_pak

PACK_FILE = "pack.toml"
PACK_KEYS = ("game", "name", "version")


@dataclass(frozen=True)
class Pack:
    name: str
    version: str
    game: str
    enemies: tuple
    digest: str
    path: pathlib.Path

    def identity(self):
        """What a save records to refuse loading against another pack."""
        return {"name": self.name, "version": self.version, "digest": self.digest}


def _toml_files(root):
    return sorted(p for p in root.rglob("*.toml") if p.is_file())


def pack_digest(root):
    """SHA-256 over every TOML file's relative path and bytes, in sorted
    path order: a renamed, added or edited file changes it."""
    root = pathlib.Path(root)
    digest = hashlib.sha256()
    for path in _toml_files(root):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _load_toml(path, rel):
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise PackError(rel, "root", f"cannot parse: {exc}") from None


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
    enemies = []
    owner = {}
    folder = root / "enemies"
    for file in sorted(folder.glob("*.toml")) if folder.is_dir() else ():
        rel = file.relative_to(root).as_posix()
        record = parse_enemy(_load_toml(file, rel), rel)
        if record.id in owner:
            raise PackError(rel, "id", f"{record.id!r} is already used by {owner[record.id]}")
        owner[record.id] = rel
        enemies.append(record)
    return Pack(table["name"], table["version"], table["game"], tuple(enemies), pack_digest(root), root)
```

Update `PyAitD/engine/content/__init__.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Content packs: TOML-authored enemies (later objects, scenarios, players)
run by a fixed vocabulary of Python behaviours over the same primitives the
LIFE opcodes call. Spec: docs/superpowers/specs/2026-09-03-content-packs-
foundation-and-enemies-design.md."""
from PyAitD.engine.content.pack import PACK_FILE, Pack, pack_digest, read_pack
from PyAitD.engine.content.schema import BEHAVIOUR_LIFE, PackError
```

- [ ] **Step 5: Run the tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_pack.py tests/test_layering.py -q`
Expected: PASS. Then `make test`: green.

- [ ] **Step 6: Commit**

```bash
git add PyAitD/engine/content packs tests/conftest.py tests/test_content_pack.py
git commit -m "feat(content): pack directory reader, identity digest, and the example pack"
```

---

### Task 4: Archive checks and `load_pack`

**Files:**
- Modify: `PyAitD/engine/content/pack.py`, `PyAitD/engine/content/__init__.py`
- Test: `tests/test_content_pack.py`

**Interfaces:**
- Produces: `check_archives(pack, data_dir, profile) -> None` (raises `PackError`), `load_pack(path, data_dir, profile) -> Pack`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_content_pack.py`:

```python
# ── archive checks (need game data) ──────────────────────────────────────────


def test_load_pack_accepts_the_example_pack_against_real_data(data_dir, profile, example_pack_dir):
    from PyAitD.engine.content.pack import load_pack
    pack = load_pack(example_pack_dir, data_dir, profile)
    assert [e.id for e in pack.enemies] == ["prowler", "watcher"]


def test_check_archives_names_the_offending_key_exactly(tmp_path, data_dir, profile):
    from PyAitD.engine.content.pack import load_pack
    cases = [
        ("body = 24", "body = 272", "body", "272 is not below 272 (LISTBODY)"),
        ("walk = 23", "walk = 305", "anims.walk", "305 is not below 305 (LISTANIM)"),
        ("stage = 0", "stage = 40", "stage", "40: PAK not found"),
        ("room = 0", "room = 99", "room", "99 is not below 1 on stage 0"),
    ]
    for i, (old, new, key, message) in enumerate(cases):
        root = _write_pack(tmp_path / f"p{i}", [("x.toml", PROWLER_TOML.replace(old, new))])
        with pytest.raises(PackError) as caught:
            load_pack(root, data_dir, profile)
        assert (caught.value.file, caught.value.key) == ("enemies/x.toml", key)
        assert caught.value.message.startswith(message), caught.value.message


def test_check_archives_refuses_another_game(tmp_path, data_dir, profile):
    from PyAitD.engine.content.pack import load_pack
    root = _write_pack(tmp_path / "p", manifest=PACK_TOML.replace('"aitd1"', '"aitd2"'))
    with pytest.raises(PackError, match=r"^pack\.toml: game: 'aitd2' is not 'aitd1'"):
        load_pack(root, data_dir, profile)


def test_check_archives_validates_against_both_hero_archives(tmp_path, data_dir, profile, monkeypatch):
    # Carnby's and Emily's paks are validated in turn; a record that fits the
    # first must still fail if it does not fit the second.
    from PyAitD.engine.content import pack as pack_module
    counts = {"LISTBODY": 300, "LISTBOD2": 25, "LISTANIM": 400, "LISTANI2": 400}
    monkeypatch.setattr(pack_module, "_pak_count", lambda data_dir, name: counts[name])
    root = _write_pack(tmp_path / "p", [("x.toml", PROWLER_TOML.replace("body = 24", "body = 30"))])
    with pytest.raises(PackError, match=r"^enemies/x\.toml: body: 30 is not below 25 \(LISTBOD2\)"):
        pack_module.load_pack(root, data_dir, profile)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_pack.py -q -k "archives or load_pack"`
Expected: `ImportError: cannot import name 'load_pack'`.

- [ ] **Step 3: Implement**

Append to `PyAitD/engine/content/pack.py`:

```python
def _pak_count(data_dir, name):
    return Pak(str(find_pak(data_dir, name))).count


def check_archives(pack, data_dir, profile):
    """Every body and anim must exist in *both* hero archives (Carnby's and
    Emily's paks differ in count, and a character switch must not fail
    later), and every stage/room must exist in the floor archive."""
    if pack.game != profile.name:
        raise PackError(PACK_FILE, "game", f"{pack.game!r} is not {profile.name!r}")
    archives = []
    for hero in range(len(profile.heroes)):
        body_pak, anim_pak = profile.hero_archives(hero)
        archives.append((body_pak, _pak_count(data_dir, body_pak), anim_pak, _pak_count(data_dir, anim_pak)))
    rooms = {}
    for record in pack.enemies:
        for body_pak, num_bodies, anim_pak, num_anims in archives:
            if record.body >= num_bodies:
                raise PackError(record.file, "body", f"{record.body} is not below {num_bodies} ({body_pak})")
            for key, anim in record.anims.present():
                if anim >= num_anims:
                    raise PackError(record.file, f"anims.{key}", f"{anim} is not below {num_anims} ({anim_pak})")
        if record.stage not in rooms:
            try:
                rooms[record.stage] = len(Floor(data_dir, record.stage, profile).rooms)
            except PakError as exc:
                raise PackError(record.file, "stage", f"{record.stage}: {exc}") from None
        if record.room >= rooms[record.stage]:
            raise PackError(record.file, "room", f"{record.room} is not below {rooms[record.stage]} on stage {record.stage}")


def load_pack(path, data_dir, profile):
    """read_pack + check_archives: the only entry point the app uses."""
    pack = read_pack(path)
    check_archives(pack, data_dir, profile)
    return pack
```

Update the import line in `PyAitD/engine/content/__init__.py`:

```python
from PyAitD.engine.content.pack import PACK_FILE, Pack, check_archives, load_pack, pack_digest, read_pack
```

- [ ] **Step 4: Run the tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_pack.py -q`
Expected: PASS (the attic floor 0 has exactly one room, so "99 is not below 1 on stage 0" holds). Then `make test`: green.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/content tests/test_content_pack.py
git commit -m "feat(content): load_pack validates bodies and anims for both heroes and rooms per floor"
```

---

### Task 5: Attachment — appended world objects, `Game(pack=)`, `init_game(pack=)`, vanilla pins

**Files:**
- Create: `PyAitD/engine/content/world.py`
- Modify: `PyAitD/engine/content/__init__.py`, `PyAitD/engine/script/game/state.py:109-120,181-195`, `PyAitD/engine/script/game/boot.py:78-96`
- Test: `tests/test_content_pack.py`, `tests/test_game.py`

**Interfaces:**
- Produces: `world.ContentAttachment(pack, first_index: int, records: dict[int, EnemyRecord])` with `record_for(world_idx) -> EnemyRecord | None`; `compile_record(record) -> WorldObject`; `attach(game, pack) -> ContentAttachment | None`.
- Produces: `Game.__init__(self, data_dir, profile, hero=0, pack=None)` sets `self.pack = pack`, `self.content = None`, `self.content_state = {}`; `init_game(data_dir, profile, hero=0, pack=None)` attaches before `spawn_stage_actors`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_content_pack.py`:

```python
# ── attachment ───────────────────────────────────────────────────────────────


def test_compile_record_is_an_inert_original_record_with_the_sentinel_life():
    from PyAitD.engine.content.world import compile_record
    from PyAitD.engine.data.formats import WorldObject
    record = parse_enemy(PROWLER, "enemies/prowler.toml")
    assert compile_record(record) == WorldObject(
        obj_index=-1, body=24, flags=0x21, type_zv=0,
        found_body=-1, found_name=-1, found_flag=0, found_life=-1,
        x=-5600, y=0, z=1000, alpha=0, beta=0, gamma=0, stage=0, room=0,
        life_mode=1, life=BEHAVIOUR_LIFE, floor_life=-1,
        anim=22, frame=0, anim_type=1, anim_info=-1,
        track_mode=0, track_number=-1, position_in_track=0, mark=0,
    )
    falls = compile_record(parse_enemy(_table(falls=True, zv="cube", life_mode="stage", beta=512), "e.toml"))
    assert (falls.flags, falls.type_zv, falls.life_mode, falls.beta) == (0x121, 2, 0, 512)


def test_init_game_appends_the_pack_after_the_original_records(data_dir, profile, example_pack_dir):
    from PyAitD.engine.content import load_pack
    from PyAitD.engine.script.game import init_game
    pack = load_pack(example_pack_dir, data_dir, profile)
    game = init_game(data_dir, profile, pack=pack)
    assert game.pack is pack
    assert len(game.world_objects) == 294
    assert game.content.first_index == 292
    assert [r.id for r in game.content.records.values()] == ["prowler", "watcher"]
    assert game.content.record_for(292).id == "prowler"
    assert game.content.record_for(9) is None
    assert game.content_state == {292: {"hp": 3, "phase": "idle"}, 293: {"hp": 2, "phase": "idle"}}
    # both spawned into the attic by the ordinary spawn pass, standing
    for idx in (292, 293):
        world = game.world_objects[idx]
        slot = world.obj_index
        assert slot != -1
        actor = game.actors[slot]
        assert (actor.index_in_world, actor.life, actor.life_mode, actor.room) == (idx, BEHAVIOUR_LIFE, 1, 0)
        assert (actor.body_num, actor.anim, actor.anim_type, actor.dyn_flags) == (24, 22, 1, 1)
    prowler = game.actors[game.world_objects[292].obj_index]
    assert (prowler.room_x, prowler.room_y, prowler.room_z) == (-5600, 0, 1000)


def test_attach_is_a_no_op_without_a_pack_and_refuses_a_second_pack(data_dir, profile, example_pack_dir):
    from PyAitD.engine.content import attach, load_pack
    from PyAitD.engine.script.game import init_game
    game = init_game(data_dir, profile)
    assert (game.pack, game.content, game.content_state) == (None, None, {})
    assert attach(game, None) is None
    pack = load_pack(example_pack_dir, data_dir, profile)
    with_pack = init_game(data_dir, profile, pack=pack)
    with pytest.raises(ValueError, match="already attached"):
        attach(with_pack, pack)


def test_an_empty_pack_changes_nothing_but_the_identity(data_dir, profile, tmp_path):
    from PyAitD.engine.content import load_pack
    from PyAitD.engine.script.game import init_game
    empty = load_pack(_write_pack(tmp_path / "empty"), data_dir, profile)
    game = init_game(data_dir, profile, pack=empty)
    assert len(game.world_objects) == 292
    assert (game.content.first_index, game.content.records, game.content_state) == (292, {}, {})
```

Append to `tests/test_game.py`:

```python
def test_a_pack_free_game_has_no_content(data_dir, profile):
    game = init_game(data_dir, profile, hero=0)
    assert (game.pack, game.content, game.content_state) == (None, None, {})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_pack.py tests/test_game.py -q`
Expected: failures on `PyAitD.engine.content.world` import, on `init_game(..., pack=)` (unexpected keyword), and on `game.pack`.

- [ ] **Step 3: Implement**

`PyAitD/engine/content/world.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Compile pack records to appended WorldObjects and attach them to a Game.

Imports script.game's leaf modules only: script.game's __init__ imports
boot, and boot imports this module (lazily, inside init_game), so importing
the package back would see it half-initialised."""
from dataclasses import dataclass

from PyAitD.engine.content.schema import BEHAVIOUR_LIFE
from PyAitD.engine.data.formats import WorldObject
from PyAitD.engine.script.game.state import AF_ANIMATED, AF_FALLABLE, AF_SPECIAL


@dataclass
class ContentAttachment:
    pack: object
    first_index: int   # world index of the first appended record
    records: dict      # world index -> EnemyRecord

    def record_for(self, world_idx):
        return self.records.get(world_idx)


def compile_record(record):
    """One EnemyRecord -> the WorldObject spawn_stage_actors will place.
    Shaped like an original creature's record (world 21: flags 0x21, anim -1
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


def attach(game, pack):
    """Append the pack's records to game.world_objects and seed game.content
    and game.content_state. None for pack=None; raises if a pack is already
    attached (a Game is attached exactly once, in init_game)."""
    if pack is None:
        return None
    if game.content is not None:
        raise ValueError("a content pack is already attached to this game")
    first = len(game.world_objects)
    records = {}
    for offset, record in enumerate(pack.enemies):
        idx = first + offset
        game.world_objects.append(compile_record(record))
        records[idx] = record
        game.content_state[idx] = {"hp": record.hit_points, "phase": "idle"}
    game.content = ContentAttachment(pack, first, records)
    return game.content
```

In `PyAitD/engine/script/game/state.py`, change the constructor signature and add the three fields right after `self.actors = ...` (line 115):

```python
    def __init__(self, data_dir, profile, hero=0, pack=None):
        ...
        self.actors = [Actor() for _ in range(NUM_MAX_OBJECT)]
        # content packs (engine/content): the Pack this game was built with,
        # its attachment (records appended after the OBJETS ones), and the
        # per-record behaviour state keyed by world index, like vars[]
        self.pack = pack
        self.content = None
        self.content_state = {}
```

In `PyAitD/engine/script/game/boot.py`, replace the head of `init_game`:

```python
def init_game(data_dir, profile, hero=0, pack=None):
    from PyAitD.engine.script.interaction import sync_player_track_mode  # interaction imports game
    from PyAitD.engine.content.world import attach  # content imports game's leaf modules
    game = Game(data_dir, profile, hero=hero, pack=pack)
    attach(game, pack)   # before spawn_stage_actors: the records must exist to be placed
```

(the rest of the function is unchanged.)

Update `PyAitD/engine/content/__init__.py` to add:

```python
from PyAitD.engine.content.world import ContentAttachment, attach, compile_record
```

- [ ] **Step 4: Run the tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_pack.py tests/test_game.py tests/test_layering.py -q`
Expected: PASS. Then `make test`: green (the layering pins from Task 2 now exercise `world.py`'s imports).

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/content PyAitD/engine/script/game/state.py PyAitD/engine/script/game/boot.py tests/test_content_pack.py tests/test_game.py
git commit -m "feat(content): attach a pack as appended world objects with the BEHAVIOUR_LIFE sentinel"
```

---

### Task 6: The enemy state machine, the runner, and the tick branch

**Files:**
- Create: `PyAitD/engine/content/enemies.py`, `PyAitD/engine/content/runner.py`
- Modify: `PyAitD/engine/content/__init__.py`, `PyAitD/engine/script/life.py:49-73` (`Trace`), `PyAitD/engine/script/playworld/tick.py:8-20,58-66`
- Test: `tests/test_content_enemies.py` (new)

**Interfaces:**
- Consumes: `arm_strike` (Task 1), `ContentAttachment.record_for`, `game.content_state` (Task 5).
- Produces: `enemies.enter_phase(game, actor, record, state, phase)`, `enemies.step_enemy(game, slot, record, state)`, `runner.run_behaviour(game, slot)`, `Trace.log_behaviour(game, actor_idx, phase)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_content_enemies.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""engine.content enemies: the pursuer/sentry state machine, unit-stepped
against a real attic boot, and the real-tick journeys of the example pack
(2026-09-03-content-packs-foundation-and-enemies-design.md, section 3)."""
import pytest

from PyAitD.engine.content import BEHAVIOUR_LIFE, load_pack
from PyAitD.engine.content.enemies import step_enemy
from PyAitD.engine.data.floor import Floor
from PyAitD.engine.script.game import init_game, relocate_actor
from PyAitD.engine.script.playworld import play_tick
from PyAitD.app.ui import InputBuffer

pytestmark = [pytest.mark.engine, pytest.mark.journey]

PROWLER, WATCHER = 292, 293


def _boot(data_dir, profile, example_pack_dir):
    pack = load_pack(example_pack_dir, data_dir, profile)
    game = init_game(data_dir, profile, pack=pack)
    floor = Floor(data_dir, 0, profile)
    play_tick(game, floor, InputBuffer())   # commits the spawn's pending anims
    return game, floor


def _actor(game, world_idx):
    slot = game.world_objects[world_idx].obj_index
    return None if slot == -1 else game.actors[slot]


def _slot(game, world_idx):
    return game.world_objects[world_idx].obj_index


def _tick_until(game, floor, predicate, *, limit):
    for tick in range(limit):
        play_tick(game, floor, InputBuffer())
        if predicate(game):
            return tick
    return -1


@pytest.fixture
def quiet_tick(monkeypatch):
    """play_tick's own behaviour branch is silenced so the explicit
    step_enemy calls below are the only thing driving the machine; the
    anim pass, collision and hit publication still run for real."""
    from PyAitD.engine.script.playworld import tick as tick_module
    monkeypatch.setattr(tick_module, "run_behaviour", lambda game, slot: None)


# ── the machine, one step at a time (quiet_tick: play_tick only animates) ────


def test_a_pursuer_leaves_idle_for_chase_on_its_first_step(data_dir, profile, example_pack_dir, quiet_tick):
    game, _ = _boot(data_dir, profile, example_pack_dir)
    record, state = game.content.record_for(PROWLER), game.content_state[PROWLER]
    actor = _actor(game, PROWLER)
    assert state["phase"] == "idle"
    step_enemy(game, _slot(game, PROWLER), record, state)
    assert state["phase"] == "chase"
    # LM_MOVE(2, hero) + LM_ANIM_REPEAT(walk), exactly what LISTLIFE 21 does
    assert (actor.track_mode, actor.track_number) == (2, game.current_world_target)
    assert (actor.new_anim, actor.new_anim_type) == (23, 1)


def test_a_sentry_stays_put_until_the_hero_is_within_twice_its_range(data_dir, profile, example_pack_dir, quiet_tick):
    game, floor = _boot(data_dir, profile, example_pack_dir)
    record, state = game.content.record_for(WATCHER), game.content_state[WATCHER]
    watcher = _actor(game, WATCHER)
    hero_idx = game.current_camera_target_actor
    parked = (watcher.room_x, watcher.room_z, watcher.beta)
    for _ in range(10):
        step_enemy(game, _slot(game, WATCHER), record, state)
    assert state["phase"] == "idle"
    assert (watcher.room_x, watcher.room_z, watcher.beta) == parked
    assert watcher.new_anim == -1
    # hero 2200 units east: inside 2 * 1500, outside 1500 -> turns, no strike
    relocate_actor(game, hero_idx, 0, 0, 2500 + 2200, 0, 3500)
    step_enemy(game, _slot(game, WATCHER), record, state)
    assert state["phase"] == "idle"
    assert watcher.rotate.num_steps > 0 or watcher.beta != parked[2]
    assert (watcher.room_x, watcher.room_z) == parked[:2]
    # hero 1000 units east: inside range -> the strike is armed
    relocate_actor(game, hero_idx, 0, 0, 2500 + 1000, 0, 3500)
    step_enemy(game, _slot(game, WATCHER), record, state)
    assert state["phase"] == "attack"
    assert (watcher.anim_action_type, watcher.anim_action_anim, watcher.anim_action_frame) == (1, 25, 1)
    assert (watcher.hot_point_id, watcher.anim_action_param, watcher.hit_force) == (22, 400, 1)
    assert (watcher.new_anim, watcher.new_anim_info) == (25, 22)
    assert (watcher.track_mode, watcher.speed) == (0, 0)


def test_a_hit_costs_hit_points_then_hurt_then_dying_then_deletion(data_dir, profile, example_pack_dir, quiet_tick):
    game, floor = _boot(data_dir, profile, example_pack_dir)
    record, state = game.content.record_for(PROWLER), game.content_state[PROWLER]
    slot = _slot(game, PROWLER)
    actor = game.actors[slot]
    hero_idx = game.current_camera_target_actor
    step_enemy(game, slot, record, state)      # idle -> chase
    play_tick(game, floor, InputBuffer())      # walk anim commits
    step_enemy(game, slot, record, state)

    actor.hit_by, actor.hit_force = hero_idx, 1
    step_enemy(game, slot, record, state)
    assert (state["hp"], state["phase"]) == (2, "hurt")
    assert (actor.new_anim, actor.new_anim_type, actor.new_anim_info) == (21, 0, 22)
    assert (actor.track_mode, actor.speed) == (0, 0)
    actor.hit_by = -1

    # a second hit while hurt still counts, the anim is not restarted
    play_tick(game, floor, InputBuffer())
    actor.hit_by, actor.hit_force = hero_idx, 1
    step_enemy(game, slot, record, state)
    assert (state["hp"], state["phase"]) == (1, "hurt")
    assert actor.new_anim == -1
    actor.hit_by = -1

    # the hurt anim ends -> a pursuer resumes the chase
    ended = _tick_until(game, floor, lambda g: game.actors[slot].flag_end_anim == 1, limit=200)
    assert ended != -1
    step_enemy(game, slot, record, state)
    assert state["phase"] == "chase"
    assert actor.new_anim == 23

    # the last hit: dying, uninterruptible death anim, no arming left behind
    actor.hit_by, actor.hit_force = hero_idx, 1
    step_enemy(game, slot, record, state)
    assert (state["hp"], state["phase"]) == (0, "dying")
    assert (actor.new_anim, actor.new_anim_type, actor.new_anim_info) == (24, 2, -1)
    actor.hit_by = -1
    play_tick(game, floor, InputBuffer())
    assert actor.anim == 24
    # a hit while dying changes nothing
    actor.hit_by, actor.hit_force = hero_idx, 5
    step_enemy(game, slot, record, state)
    assert (state["hp"], state["phase"]) == (0, "dying")
    actor.hit_by = -1
    ended = _tick_until(game, floor, lambda g: game.actors[slot].flag_end_anim == 1, limit=400)
    assert ended != -1
    step_enemy(game, slot, record, state)
    assert state["phase"] == "dead"
    world = game.world_objects[PROWLER]
    assert (world.obj_index, world.stage, world.room) == (-1, -1, -1)
    assert actor.index_in_world == -1
    step_enemy(game, slot, record, state)      # dead stays dead, no raise
    assert state["phase"] == "dead"


def test_an_attack_returns_a_pursuer_to_chase_and_a_sentry_to_idle(data_dir, profile, example_pack_dir, quiet_tick):
    game, floor = _boot(data_dir, profile, example_pack_dir)
    hero_idx = game.current_camera_target_actor

    def swing_and_finish(world_idx):
        record, state = game.content.record_for(world_idx), game.content_state[world_idx]
        slot = _slot(game, world_idx)
        actor = game.actors[slot]
        relocate_actor(game, hero_idx, 0, 0, actor.room_x + 600, 0, actor.room_z)
        if record.kind == "pursuer":
            step_enemy(game, slot, record, state)   # idle -> chase
        step_enemy(game, slot, record, state)       # in range -> attack (one step: a sentry arms from idle)
        assert state["phase"] == "attack"
        play_tick(game, floor, InputBuffer())
        assert actor.anim == 25
        ended = _tick_until(game, floor, lambda g: game.actors[slot].flag_end_anim == 1, limit=300)
        assert ended != -1
        relocate_actor(game, hero_idx, 0, 0, actor.room_x + 6000, 0, actor.room_z)   # out of range
        step_enemy(game, slot, record, state)
        return state["phase"]

    assert swing_and_finish(PROWLER) == "chase"
    assert swing_and_finish(WATCHER) == "idle"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_enemies.py -q`
Expected: `ModuleNotFoundError: PyAitD.engine.content.enemies`.

- [ ] **Step 3: Implement the machine**

`PyAitD/engine/content/enemies.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""The enemy vocabulary: pursuer and sentry, one state machine.

Every transition calls only what LIFE opcodes call -- init_deplacement +
process_track (LM_MOVE + LM_DO_MOVE), init_anim (LM_ANIM_*), arm_strike
(LM_HIT), delete_object (LM_DELETE) -- so a pack enemy rides the same
collision, animation and hit code as a scripted one. State is
game.content_state[world_idx] = {"hp", "phase"}; the phase table is the
spec's section 3."""
from PyAitD.engine.actor.anim import ANIM_ONCE, ANIM_REPEAT, ANIM_UNINTERRUPTABLE, init_anim
from PyAitD.engine.actor.anim_action import arm_strike
from PyAitD.engine.actor.tracks import _turn_toward, init_deplacement, process_track
from PyAitD.engine.script.eval_var import calc_dist
from PyAitD.engine.script.game.objects import delete_object

TRACK_FOLLOW = 2   # track_mode 2: follow a world object (track.cpp:230)


def _hero_in_room(game, actor):
    idx = game.current_camera_target_actor
    if idx == -1:
        return None
    hero = game.actors[idx]
    return hero if hero.room == actor.room else None


def _distance(actor, other):
    # the DISTANCE tag's own metric (evalVar): Manhattan, world coordinates
    return calc_dist(actor.world_x, actor.world_y, actor.world_z,
                     other.world_x, other.world_y, other.world_z)


def _stop(actor):
    actor.track_mode = 0
    actor.speed = 0


def _resume_phase(record):
    return "chase" if record.kind == "pursuer" else "idle"


def enter_phase(game, actor, record, state, phase):
    """Set `phase` and issue its entry primitives. `attack` is entered only
    through _try_attack, since arm_strike may refuse."""
    state["phase"] = phase
    anims = record.anims
    if phase == "idle":
        _stop(actor)
        init_anim(actor, anims.stand, ANIM_REPEAT, -1)
    elif phase == "chase":
        init_deplacement(actor, TRACK_FOLLOW, game.current_world_target)
        init_anim(actor, anims.walk, ANIM_REPEAT, -1)
    elif phase == "hurt":
        _stop(actor)
        init_anim(actor, anims.hurt, ANIM_ONCE, anims.stand)
    elif phase == "dying":
        _stop(actor)
        init_anim(actor, anims.death, ANIM_UNINTERRUPTABLE, -1)


def _try_attack(actor, record, state):
    a = record.attack
    if arm_strike(actor, record.anims.attack, a.frame, a.group, a.radius, a.force, record.anims.stand):
        _stop(actor)              # no sliding mid-swing
        state["phase"] = "attack"
        return True
    return False


def step_enemy(game, slot, record, state):
    """One tick of the record's behaviour for the actor in `slot`. Runs at
    the LIFE loop's position, so hit_by reflects this tick's anim pass and a
    phase entered here is committed by the next tick's gere_anim before
    flag_end_anim is consulted again."""
    actor = game.actors[slot]
    phase = state["phase"]
    if phase == "dead":
        return
    if phase == "dying":
        if actor.flag_end_anim:
            delete_object(game, actor.index_in_world)   # stage -1: never respawns
            state["phase"] = "dead"
        return
    if actor.hit_by != -1:
        state["hp"] -= actor.hit_force
        if state["hp"] <= 0:
            enter_phase(game, actor, record, state, "dying")
        elif phase != "hurt":
            enter_phase(game, actor, record, state, "hurt")
        # a hit during hurt or attack counts; the anim is not restarted
        return
    hero = _hero_in_room(game, actor)
    if phase == "idle":
        if record.kind == "pursuer":
            enter_phase(game, actor, record, state, "chase")
            return
        if hero is None:
            return
        distance = _distance(actor, hero)
        if distance < 2 * record.attack.range:
            _turn_toward(game, actor, hero.room_x, hero.room_z)   # the follow track's own turn
            actor.beta &= 0x3FF
        if distance < record.attack.range:
            _try_attack(actor, record, state)
    elif phase == "chase":
        process_track(game, actor)                                # LM_DO_MOVE
        if hero is not None and _distance(actor, hero) < record.attack.range:
            _try_attack(actor, record, state)
    elif phase in ("attack", "hurt"):
        if actor.flag_end_anim:
            enter_phase(game, actor, record, state, _resume_phase(record))
```

`PyAitD/engine/content/runner.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""The behaviour branch of the tick: what run_life is to a LIFE actor."""
from PyAitD.engine.content.enemies import step_enemy


def run_behaviour(game, slot):
    """Step the behaviour of the BEHAVIOUR_LIFE actor in `slot`. Never
    raises on game state: an actor with no record (only a corrupt save
    could produce one, and validate_snapshot refuses those) is left alone."""
    actor = game.actors[slot]
    content = game.content
    record = None if content is None else content.record_for(actor.index_in_world)
    if record is None:
        return
    state = game.content_state[actor.index_in_world]
    step_enemy(game, slot, record, state)
    if game.trace is not None:
        game.trace.log_behaviour(game, slot, state["phase"])
```

Add to `Trace` in `PyAitD/engine/script/life.py`, after `log`:

```python
    def log_behaviour(self, game, actor_idx, phase):
        # the content-pack twin of `log`: one line per behaviour step
        if self._file is None:
            return
        try:
            self._file.write(f"{game.timer} {actor_idx} BEHAVIOUR {phase}\n")
        except OSError:
            pass
```

In `PyAitD/engine/script/playworld/tick.py`, add the import (after the `effects` import):

```python
from PyAitD.engine.content import BEHAVIOUR_LIFE, run_behaviour
```

and change the LIFE loop:

```python
    for index, actor in enumerate(game.actors):
        if actor.index_in_world < 0:
            continue
        if life_gate(actor):
            if not run_life(game, LifeFrame(index, actor.life)):
                drain_immediate_effects(game)
                return False
            if not drain_immediate_effects(game):
                return False
        elif actor.life == BEHAVIOUR_LIFE:
            # a pack behaviour in the slot order a LIFE at this slot would run
            run_behaviour(game, index)
        if game.flag_change_etage:
            break
```

Update `PyAitD/engine/content/__init__.py` to add:

```python
from PyAitD.engine.content.enemies import enter_phase, step_enemy
from PyAitD.engine.content.runner import run_behaviour
```

- [ ] **Step 4: Run the tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_enemies.py tests/test_layering.py -q`
Expected: PASS. If `test_a_sentry_stays_put...` fails on the turn assertion, `_turn_toward` initialised `rotate` but `beta` only changes once `update_actor_rotation` advances: the `or` covers both, so a failure there means the hero was not seen in range; check `hero.room == watcher.room` after `relocate_actor`. Then `make test`: green.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/content PyAitD/engine/script/life.py PyAitD/engine/script/playworld/tick.py tests/test_content_enemies.py
git commit -m "feat(content): pursuer and sentry behaviours run in the tick's LIFE loop for BEHAVIOUR_LIFE actors"
```

---

### Task 7: The attic journeys and the vanilla-invariance golden

**Files:**
- Test: `tests/test_content_enemies.py`, `tests/test_content_pack.py`

**Interfaces:**
- Consumes: everything from Tasks 5 and 6; `tests/test_m3b_attic.py`'s `_tick_until` idiom (copied, not imported).

- [ ] **Step 1: Write the journeys**

Append to `tests/test_content_enemies.py`:

```python
# ── the real tick, end to end ────────────────────────────────────────────────


def test_the_prowler_chases_the_hero_across_the_attic_and_arms_a_strike(data_dir, profile, example_pack_dir):
    game, floor = _boot(data_dir, profile, example_pack_dir)
    hero = game.actors[game.current_camera_target_actor]
    prowler = _actor(game, PROWLER)
    assert prowler is not None
    play_tick(game, floor, InputBuffer())
    assert game.content_state[PROWLER]["phase"] == "chase"
    assert (prowler.track_mode, prowler.track_number, prowler.anim) == (2, game.current_world_target, 23)

    def gap(g):
        return abs(prowler.room_x - hero.room_x) + abs(prowler.room_z - hero.room_z)

    start_gap = gap(game)
    moved = _tick_until(game, floor, lambda g: abs(prowler.room_x + 5600) + abs(prowler.room_z - 1000) > 300, limit=200)
    assert moved != -1, "the prowler never left its spawn point"
    armed = _tick_until(game, floor, lambda g: g.content_state[PROWLER]["phase"] == "attack", limit=3000)
    assert armed != -1, f"the prowler never came within range: {start_gap} -> {gap(game)}"
    assert gap(game) < start_gap // 3
    assert (prowler.anim_action_type, prowler.anim_action_anim) == (1, 25)
    # the strike lands through gere_frappe like any scripted one
    landed = _tick_until(game, floor, lambda g: hero.hit_by == g.world_objects[PROWLER].obj_index, limit=1200)
    assert landed != -1, "the armed swing never reached the hero"


def test_hits_in_the_real_loop_take_the_prowler_through_hurt_dying_and_out(data_dir, profile, example_pack_dir, monkeypatch):
    # play_tick resets hit_by before the anim pass; inject the hero's hit
    # right after that pass, where gere_frappe would publish it, so the
    # behaviour sees it at the LIFE loop's position (the same trick
    # tests/test_game_over.py uses on playworld.tick).
    from PyAitD.engine.script.playworld import tick as tick_module
    game, floor = _boot(data_dir, profile, example_pack_dir)
    hero_idx = game.current_camera_target_actor
    pending = {"hits": 0}
    real_anim_pass = tick_module._anim_pass

    def anim_pass_then_hit(g):
        result = real_anim_pass(g)
        if pending["hits"]:
            prowler = _actor(g, PROWLER)
            prowler.hit_by, prowler.hit_force = hero_idx, 1
            pending["hits"] -= 1
        return result

    monkeypatch.setattr(tick_module, "_anim_pass", anim_pass_then_hit)
    _tick_until(game, floor, lambda g: g.content_state[PROWLER]["phase"] == "chase", limit=10)
    _tick_until(game, floor, lambda g: False, limit=60)

    pending["hits"] = 1
    hurt = _tick_until(game, floor, lambda g: g.content_state[PROWLER]["phase"] == "hurt", limit=5)
    assert hurt != -1
    assert game.content_state[PROWLER]["hp"] == 2
    back = _tick_until(game, floor, lambda g: g.content_state[PROWLER]["phase"] == "chase", limit=300)
    assert back != -1, "the hurt anim never handed back to the chase"

    pending["hits"] = 2
    dying = _tick_until(game, floor, lambda g: g.content_state[PROWLER]["phase"] == "dying", limit=10)
    assert dying != -1
    assert game.content_state[PROWLER]["hp"] == 0
    slot = _slot(game, PROWLER)
    dead = _tick_until(game, floor, lambda g: g.content_state[PROWLER]["phase"] == "dead", limit=400)
    assert dead != -1, "the death anim never ended"
    assert game.world_objects[PROWLER].obj_index == -1
    assert game.world_objects[PROWLER].stage == -1
    assert game.actors[slot].index_in_world == -1

    # leaving and re-entering the room regenerates the active list; a dead
    # record has stage -1 and is skipped like a taken object
    game.flag_genere_aff_list = 1
    play_tick(game, floor, InputBuffer())
    assert game.world_objects[PROWLER].obj_index == -1
    assert game.content_state[PROWLER] == {"hp": 0, "phase": "dead"}


def test_the_watcher_never_moves_and_turns_to_face_a_hero_who_comes_close(data_dir, profile, example_pack_dir):
    game, floor = _boot(data_dir, profile, example_pack_dir)
    hero_idx = game.current_camera_target_actor
    watcher = _actor(game, WATCHER)
    parked = (watcher.room_x, watcher.room_y, watcher.room_z, watcher.beta)
    _tick_until(game, floor, lambda g: False, limit=300)
    assert (watcher.room_x, watcher.room_y, watcher.room_z, watcher.beta) == parked
    assert game.content_state[WATCHER]["phase"] == "idle"
    relocate_actor(game, hero_idx, 0, 0, 2500 - 2500, 0, 3500)    # 2500 west: turns, no strike
    turned = _tick_until(game, floor, lambda g: watcher.beta != parked[3], limit=120)
    assert turned != -1, "the watcher never turned toward the hero"
    assert (watcher.room_x, watcher.room_z) == (parked[0], parked[2])
    assert game.content_state[WATCHER]["phase"] == "idle"
    relocate_actor(game, hero_idx, 0, 0, 2500 - 1000, 0, 3500)    # 1000 west: in range
    armed = _tick_until(game, floor, lambda g: g.content_state[WATCHER]["phase"] == "attack", limit=10)
    assert armed != -1
    assert (watcher.room_x, watcher.room_z) == (parked[0], parked[2])


def test_the_trace_records_each_behaviour_step(data_dir, profile, example_pack_dir, tmp_path):
    from PyAitD.engine.script.life import Trace
    game, floor = _boot(data_dir, profile, example_pack_dir)
    game.trace = Trace(tmp_path / "t.log")
    play_tick(game, floor, InputBuffer())
    play_tick(game, floor, InputBuffer())
    game.trace.close()
    lines = (tmp_path / "t.log").read_text().splitlines()
    prowler, watcher = _slot(game, PROWLER), _slot(game, WATCHER)
    behaviour = [line for line in lines if " BEHAVIOUR " in line]
    assert f"{game.timer - 1} {prowler} BEHAVIOUR chase" in behaviour
    assert f"{game.timer - 1} {watcher} BEHAVIOUR idle" in behaviour
    assert f"{game.timer} {prowler} BEHAVIOUR chase" in behaviour
```

Append to `tests/test_content_pack.py`:

```python
# ── vanilla invariance ───────────────────────────────────────────────────────


def test_an_empty_pack_ticks_identically_to_no_pack(data_dir, profile, tmp_path):
    from PyAitD.engine.content import load_pack
    from PyAitD.engine.data.floor import Floor
    from PyAitD.engine.script.game import init_game
    from PyAitD.engine.script.playworld import play_tick
    from PyAitD.engine.script.save import _snapshot_actor
    from PyAitD.app.ui import InputBuffer
    empty = load_pack(_write_pack(tmp_path / "empty"), data_dir, profile)
    vanilla = init_game(data_dir, profile)
    packed = init_game(data_dir, profile, pack=empty)
    for game in (vanilla, packed):
        game.rng.seed(7)
    floor = Floor(data_dir, 0, profile)
    for tick in range(400):
        play_tick(vanilla, floor, InputBuffer())
        play_tick(packed, floor, InputBuffer())
        assert [_snapshot_actor(a) for a in vanilla.actors] == [_snapshot_actor(a) for a in packed.actors], tick
    assert vanilla.timer == packed.timer == 400
```

- [ ] **Step 2: Run the journeys**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_content_enemies.py tests/test_content_pack.py -q`
Expected: PASS. The prowler crosses about 11,000 Manhattan units at roughly 8 units a tick, so `limit=3000` has headroom; the original stair creature arms itself at tick ~3600 and does not interfere. If `landed` fails, the hero is standing in anim 4 and the strike's hot point (group 22, radius 400) must reach the hero's 532-wide cube: check `hero.hit_by` is compared against the prowler's *slot*, not its world index.

- [ ] **Step 3: Run the whole suite and the journeys target**

Run: `make test && make test-journey`
Expected: green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_content_enemies.py tests/test_content_pack.py
git commit -m "test(content): attic journeys for the example pack; an empty pack ticks identically to none"
```

---

### Task 8: Save and load — schema 3, pack identity, `content_state`

**Files:**
- Modify: `PyAitD/engine/script/save.py` (`SCHEMA`, `ROOT_KEYS`, `source_identity`, `snapshot_game`, `validate_snapshot`, `_validate_source`, `_validate_world_objects`, new `_validate_content_state`, `read_slot`, `restore_game`)
- Test: `tests/test_save.py`

**Interfaces:**
- Produces: `source_identity(data_dir, profile, hero, pack=None)` adds `"pack"`; `validate_snapshot(payload, data_dir, profile, pack=None)`; `read_slot(path, data_dir, profile, pack=None)`; `restore_game(data_dir, profile, payload, pack=None) -> (game, settings)`; payload root key `content_state`.

- [ ] **Step 1: Update the existing pins and write the failing tests**

In `tests/test_save.py`:
- Add `import re` to the imports.
- `ROOT_KEYS` at the top: add `"content_state"`.
- `test_snapshot_root_keys_pinned`: `assert payload["schema"] == SCHEMA == 3`.
- `test_validate_rejects_unknown_schema`: `payload["schema"] = 4`.
- `test_source_identity_names_and_digest_stable`: add `assert source["pack"] is None` after the `profile` assertion.

Append:

```python
# ── content packs ────────────────────────────────────────────────────────────


def _packed(data_dir, profile, example_pack_dir):
    from PyAitD.engine.content import load_pack
    pack = load_pack(example_pack_dir, data_dir, profile)
    return init_game(data_dir, profile, pack=pack), pack


def test_snapshot_records_the_pack_identity_and_the_content_state(data_dir, profile, example_pack_dir):
    game, pack = _packed(data_dir, profile, example_pack_dir)
    payload = snapshot_game(game, SETTINGS)
    assert payload["source"]["pack"] == {"name": "example", "version": "1", "digest": pack.digest}
    assert len(payload["world_objects"]) == 294
    assert payload["content_state"] == {"292": {"hp": 3, "phase": "idle"}, "293": {"hp": 2, "phase": "idle"}}
    assert validate_snapshot(json.loads(json.dumps(payload)), data_dir, profile, pack=pack)
    vanilla = _snapshot(data_dir, profile)
    assert vanilla["source"]["pack"] is None
    assert vanilla["content_state"] == {}


def test_validate_refuses_a_pack_mismatch_in_both_directions(data_dir, profile, example_pack_dir):
    game, pack = _packed(data_dir, profile, example_pack_dir)
    packed = snapshot_game(game, SETTINGS)
    vanilla = _snapshot(data_dir, profile)
    with pytest.raises(SaveError, match=r"source\.pack: save was made with content pack example; none is attached"):
        validate_snapshot(packed, data_dir, profile)
    with pytest.raises(SaveError, match=r"source\.pack: save was made without a content pack; example is attached"):
        validate_snapshot(vanilla, data_dir, profile, pack=pack)
    edited = copy.deepcopy(packed)
    edited["source"]["pack"]["digest"] = "0" * 64
    with pytest.raises(SaveError, match=r"source\.pack: content pack mismatch: save has example 1 \(00000000\), attached is example 1 \("):
        validate_snapshot(edited, data_dir, profile, pack=pack)


def test_validate_checks_world_object_count_and_content_state_against_the_pack(data_dir, profile, example_pack_dir):
    game, pack = _packed(data_dir, profile, example_pack_dir)
    payload = snapshot_game(game, SETTINGS)
    short = copy.deepcopy(payload)
    short["world_objects"] = short["world_objects"][:292]
    with pytest.raises(SaveError, match=r"world_objects: expected 294 world objects, got 292"):
        validate_snapshot(short, data_dir, profile, pack=pack)
    for state, path, message in [
        ({"291": {"hp": 3, "phase": "idle"}}, "content_state.291", "expected a world index in 292..293"),
        ({"292": {"hp": 3}}, "content_state.292", "missing keys: phase"),
        ({"292": {"hp": "3", "phase": "idle"}}, "content_state.292.hp", "expected an integer"),
        ({"292": {"hp": 3, "phase": "flying"}}, "content_state.292.phase", "expected one of idle, chase, attack, hurt, dying, dead, got 'flying'"),
        ([], "content_state", "expected an object"),
    ]:
        bad = copy.deepcopy(payload)
        bad["content_state"] = state
        with pytest.raises(SaveError, match=re.escape(f"{path}: {message}")):
            validate_snapshot(bad, data_dir, profile, pack=pack)
    vanilla = _snapshot(data_dir, profile)
    vanilla["content_state"] = {"5": {"hp": 1, "phase": "idle"}}
    with pytest.raises(SaveError, match=r"content_state: expected no content state without a pack"):
        validate_snapshot(vanilla, data_dir, profile)


def test_restore_round_trips_a_pack_game_mid_chase(data_dir, profile, example_pack_dir):
    from PyAitD.engine.data.floor import Floor
    from PyAitD.engine.script.playworld import play_tick
    game, pack = _packed(data_dir, profile, example_pack_dir)
    floor = Floor(data_dir, 0, profile)
    for _ in range(120):
        play_tick(game, floor, _input_buffer())
    assert game.content_state[292]["phase"] == "chase"
    game.content_state[292]["hp"] = 1
    payload = json.loads(json.dumps(snapshot_game(game, SETTINGS)))
    restored, settings = restore_game(data_dir, profile, payload, pack=pack)
    assert settings == SETTINGS
    assert restored.pack is pack
    assert restored.content_state == {292: {"hp": 1, "phase": "chase"}, 293: {"hp": 2, "phase": "idle"}}
    assert snapshot_game(restored, SETTINGS) == payload
    play_tick(game, floor, _input_buffer())
    play_tick(restored, Floor(data_dir, restored.current_floor, profile), _input_buffer())
    assert snapshot_game(game, SETTINGS) == snapshot_game(restored, SETTINGS)


def test_read_slot_reports_a_pack_mismatch_without_touching_anything(tmp_path, data_dir, profile, example_pack_dir):
    from PyAitD.engine.script.save import read_slot, write_slot
    game, pack = _packed(data_dir, profile, example_pack_dir)
    path = tmp_path / "save-manual.json"
    write_slot(path, snapshot_game(game, SETTINGS))
    payload, error = read_slot(path, data_dir, profile)
    assert payload is None
    assert error == "Could not load save-manual.json: source.pack: save was made with content pack example; none is attached"
    payload, error = read_slot(path, data_dir, profile, pack=pack)
    assert error is None and payload["schema"] == 3
```

(`restore_game`, `FloorStart`, `TimedMessage` and `_input_buffer` are already imported or defined in the file; add `from PyAitD.engine.script.save import restore_game` only if it is not present.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_save.py -q`
Expected: the updated pins fail on `SCHEMA == 3`, and the new tests fail on the missing `pack` keyword / `content_state` key.

- [ ] **Step 3: Implement**

In `PyAitD/engine/script/save.py`:

```python
from PyAitD.engine.content.schema import PHASES
...
SCHEMA = 3

ROOT_KEYS = (
    "schema", "engine_version", "source", "hero", "game", "actors",
    "world_objects", "anim_players", "inventory", "messages", "rng_state",
    "settings", "content_state",
)
...
_SOURCE_KEYS = {"profile", "archives", "digest", "pack"}
_PACK_KEYS = {"name", "version", "digest"}
_CONTENT_STATE_KEYS = {"hp", "phase"}
```

`source_identity`:

```python
def source_identity(data_dir, profile, hero, pack=None):
    """The archive names plus one SHA-256 over their bytes, in order: the
    three world files, the life/track paks, then the hero's body/anim paks;
    plus the attached content pack's identity (or None). A save is only
    loadable against the data, and the pack, it came from."""
    archives = source_identity_names(profile, hero)
    digest = hashlib.sha256()
    for name in archives:
        digest.update((pathlib.Path(data_dir) / name).read_bytes())
    return {
        "profile": profile.name, "archives": archives, "digest": digest.hexdigest(),
        "pack": None if pack is None else pack.identity(),
    }
```

`snapshot_game`: pass `game.pack` and add the block:

```python
        "source": source_identity(game._data_dir, profile, hero, game.pack),
        ...
        "content_state": {str(idx): {"hp": s["hp"], "phase": s["phase"]}
                          for idx, s in sorted(game.content_state.items())},
        "settings": settings,
```

`validate_snapshot(payload, data_dir, profile, pack=None)`: change the source and world-object lines and add the content-state line:

```python
    _validate_source(payload["source"], data_dir, profile, hero, pack)
    _validate_state(payload["game"], data_dir, profile)
    _validate_actors(payload["actors"])
    extra = 0 if pack is None else len(pack.enemies)
    first = _validate_world_objects(payload["world_objects"], data_dir, profile.world_object_has_mark, extra)
    _validate_content_state(payload["content_state"], pack, first)
```

`_validate_source`:

```python
def _validate_source(source, data_dir, profile, hero, pack=None):
    _require_keys(source, _SOURCE_KEYS, "source")
    expected = source_identity_names(profile, hero)
    archives = source["archives"]
    if source["profile"] != profile.name or archives != expected:
        _fail("source", "data identity mismatch: archives do not match this game")
    raws = _read_archives(data_dir, expected)
    digest = hashlib.sha256()
    for name in expected:
        digest.update(raws[name])
    if source["digest"] != digest.hexdigest():
        _fail("source", "data identity mismatch: digest does not match this game data")
    saved = source["pack"]
    if saved is not None:
        _require_keys(saved, _PACK_KEYS, "source.pack")
        for key in sorted(_PACK_KEYS):
            if type(saved[key]) is not str:
                _fail(f"source.pack.{key}", f"expected a string, got {type(saved[key]).__name__}")
    attached = None if pack is None else pack.identity()
    if saved is None and attached is not None:
        _fail("source.pack", f"save was made without a content pack; {attached['name']} is attached")
    if saved is not None and attached is None:
        _fail("source.pack", f"save was made with content pack {saved['name']}; none is attached")
    if saved != attached:
        _fail("source.pack",
              f"content pack mismatch: save has {saved['name']} {saved['version']} ({saved['digest'][:8]}), "
              f"attached is {attached['name']} {attached['version']} ({attached['digest'][:8]})")
    return raws
```

`_validate_world_objects` returns the original count:

```python
def _validate_world_objects(world_objects, data_dir, has_mark, extra=0):
    original = len(parse_objets((pathlib.Path(data_dir) / "OBJETS.ITD").read_bytes(), has_mark=has_mark))
    expected = original + extra
    if not isinstance(world_objects, list) or len(world_objects) != expected:
        count = len(world_objects) if isinstance(world_objects, list) else type(world_objects).__name__
        _fail("world_objects", f"expected {expected} world objects, got {count}")
    for i, world in enumerate(world_objects):
        path = f"world_objects[{i}]"
        _require_keys(world, set(_WORLD_FIELDS), path)
        for name in _WORLD_FIELDS:
            _require_int(world[name], f"{path}.{name}")
    return original
```

New validator, after `_validate_world_objects`:

```python
def _validate_content_state(state, pack, first_index):
    if not isinstance(state, dict):
        _fail("content_state", "expected an object")
    if pack is None:
        if state:
            _fail("content_state", "expected no content state without a pack")
        return
    last = first_index + len(pack.enemies) - 1
    for key, entry in state.items():
        path = f"content_state.{key}"
        if not (type(key) is str and key.isdigit() and first_index <= int(key) <= last):
            _fail(path, f"expected a world index in {first_index}..{last}")
        _require_keys(entry, _CONTENT_STATE_KEYS, path)
        _require_int(entry["hp"], f"{path}.hp")
        if entry["phase"] not in PHASES:
            _fail(f"{path}.phase", f"expected one of {', '.join(PHASES)}, got {entry['phase']!r}")
```

`_require_keys` already reports `missing keys: phase` for a missing key (keep its existing wording; if it differs, match the test to the existing wording rather than the other way round).

`read_slot`:

```python
def read_slot(path, data_dir, profile, pack=None):
    ...
        return validate_snapshot(payload, data_dir, profile, pack=pack), None
```

`restore_game`:

```python
def restore_game(data_dir, profile, payload, pack=None):
    payload = validate_snapshot(payload, data_dir, profile, pack=pack)
    game = init_game(data_dir, profile, hero=payload["hero"], pack=pack)
    ...
    for world, entry in zip(game.world_objects, payload["world_objects"]):
        for name in _WORLD_FIELDS:
            setattr(world, name, entry[name])
    game.content_state = {
        int(key): {"hp": entry["hp"], "phase": entry["phase"]}
        for key, entry in payload["content_state"].items()
    }
```

- [ ] **Step 4: Run the tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_save.py tests/test_layering.py -q`
Expected: PASS. Then `make test` and `make prove-persistence`: green.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/script/save.py tests/test_save.py
git commit -m "feat(save): schema 3 carries the content pack identity and per-record behaviour state"
```

---

### Task 9: `--content`, the shell pass-through sites, the Makefile, and the docs

**Files:**
- Modify: `PyAitD/app/shell.py` (`parse_args` line ~159, `main` line ~1905, `restart_session` ~1490, `_boot_hero` ~1512, `_load_branch` ~1001, `_request_load` ~985), `Makefile:45-46`, `README.md`, `AGENTS.md`, `CONTEXT.md`
- Test: `tests/test_main.py`, `tests/test_runtime_modes.py`

**Interfaces:**
- Consumes: `load_pack`, `PackError` (Task 4), `game.pack` (Task 5), `read_slot`/`restore_game` `pack=` (Task 8).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main.py`:

```python
def test_parse_args_content_is_a_path_with_no_default():
    import pathlib
    assert parse_args([]).content is None
    assert parse_args(["--content", "packs/example"]).content == pathlib.Path("packs/example")


def test_main_refuses_a_bad_pack_before_any_window(monkeypatch, tmp_path, capsys, data_dir):
    import PyAitD.app.shell as main
    (tmp_path / "pack.toml").write_text('name = "x"\nversion = "1"\ngame = "aitd1"\n')
    (tmp_path / "enemies").mkdir()
    (tmp_path / "enemies" / "bad.toml").write_text(
        'id = "b"\nkind = "pursuer"\nbody = 24\nstage = 0\nroom = 0\nposition = [0, 0, 0]\nhit_points = 1\n'
        '[anims]\nstand = 22\nwalk = 999\nattack = 25\nhurt = 21\ndeath = 24\n'
        '[attack]\nframe = 1\ngroup = 22\nradius = 400\nforce = 1\nrange = 2000\n'
    )
    monkeypatch.setattr(main, "run", lambda *args, **kwargs: pytest.fail("run() must not start"))
    assert main.main(["--data", str(data_dir), "--content", str(tmp_path)]) == 2
    assert capsys.readouterr().err.strip() == "content pack error: enemies/bad.toml: anims.walk: 999 is not below 305 (LISTANIM)"


def test_main_boots_the_staging_game_with_the_pack(monkeypatch, data_dir, example_pack_dir):
    import PyAitD.app.shell as main
    from PyAitD.app.config import default_settings
    from PyAitD.app.ui import ModalSession
    captured = {}

    def fake_run(game, trace, session=None, mirror_sink=None):
        captured["game"] = game
        return 0

    monkeypatch.setattr(main, "run", fake_run)
    monkeypatch.setattr(main, "load_runtime_session", lambda path, save_directory=None: ModalSession(settings=default_settings()))
    assert main.main(["--data", str(data_dir), "--content", str(example_pack_dir)]) == 0
    game = captured["game"]
    assert game.pack.name == "example"
    assert len(game.world_objects) == 294
```

Append to `tests/test_runtime_modes.py` next to the existing `restart_session` tests (around line 1250):

```python
def test_restart_and_hero_boot_keep_the_content_pack(data_dir, profile, example_pack_dir, monkeypatch):
    from PyAitD.engine.content import load_pack
    pack = load_pack(example_pack_dir, data_dir, profile)
    old = init_game(data_dir, profile, pack=pack)
    new = restart_session(old)
    assert new.pack is pack
    assert len(new.world_objects) == 294
    assert new.content_state == {292: {"hp": 3, "phase": "idle"}, 293: {"hp": 2, "phase": "idle"}}

    import numpy as np
    from types import SimpleNamespace
    import PyAitD.app.shell as main
    from PyAitD.app.ui import InputBuffer, ModalSession
    from PyAitD.app.config import default_settings
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (np.zeros((200, 320, 3), dtype=np.uint8), []))
    session = ModalSession(settings=default_settings())
    replaced = main._boot_hero(old, SimpleNamespace(), session, InputBuffer(), 1, cutscene=False)
    assert replaced[0].pack is pack
    assert len(replaced[0].world_objects) == 294
```

(`init_game` and `restart_session` are already imported in that file.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_main.py tests/test_runtime_modes.py -q -k "content or pack"`
Expected: `parse_args` has no `content`; `main` returns 0 for the bad pack; restart drops the pack.

- [ ] **Step 3: Implement the shell**

`parse_args`, after the `--textures` argument:

```python
    p.add_argument(
        "--content", type=pathlib.Path, default=None,
        help="content pack directory (holds pack.toml); session only, never persisted",
    )
```

`main`, replace the `init_game` block:

```python
    args = parse_args(argv)
    profile = load_profile("aitd1")
    pack = None
    if args.content is not None:
        try:
            pack = load_pack(args.content, args.data, profile)
        except (PackError, PakError) as exc:
            # a pack is applied whole or not at all: no substitute exists
            # for a missing enemy, unlike a missing texture
            print(f"content pack error: {exc}", file=sys.stderr)
            return 2
    try:
        game = init_game(args.data, profile, hero=args.hero, pack=pack)
    except PakError as exc:
```

with the import at the top of `shell.py`:

```python
from PyAitD.engine.content import PackError, load_pack
```

`restart_session`: `new_game = init_game(data_dir, old_game.profile, hero=hero, pack=old_game.pack)`.

`_boot_hero`: `new_game = init_game(game._data_dir, game.profile, hero=hero, pack=game.pack)`.

`_load_branch`: `new_game, settings_dict = restore_game(game._data_dir, game.profile, payload, pack=game.pack)`.

`_request_load`:

```python
    payload, error = read_slot(
        slot_path(session.save_directory, kind), game._data_dir, game.profile, pack=game.pack,
    )
```

`Makefile` line 45-46:

```make
run: install ## Run the game through character selection (floor=0 attic debug bypass, textures=DIR defaults to data/aitd1/textures — pass textures= to play the original backgrounds, content=DIR loads a content pack, trace=FILE)
	$(PYTHON) -m PyAitD $(if $(floor),--floor "$(floor)") --data "$(data)" $(if $(trace),--trace $(trace)) $(if $(textures),--textures "$(textures)") $(if $(content),--content "$(content)")
```

- [ ] **Step 4: Run the tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_main.py tests/test_runtime_modes.py tests/test_layering.py -q`
Expected: PASS. Then `make test`: green. Then a manual smoke: `make run content=packs/example floor=0` — the prowler walks in from the west and attacks; the watcher stands in the north-east.

- [ ] **Step 5: Docs**

`README.md`, in the Run block add `make run content=packs/example   # with the example content pack (a pursuer and a sentry in the attic)`, and after the "Texture directories" section add:

```markdown
### Content packs

A content pack is a directory holding `pack.toml` (`name`, `version`,
`game = "aitd1"`) and `enemies/*.toml`, one enemy per file: a body and
animation set copied from an original creature, a position, hit points, and
the strike operands. `pursuer` chases and strikes; `sentry` stands, turns
toward the hero and strikes in range. The original scripts stay untouched;
with no pack the game is byte-identical. `--content DIR` is session-only.
A bad pack stops the boot with the file, key and value. Saves record the
pack's digest and refuse to load against a different pack or none.
`packs/example/` is the reference pack, exercised by the test suite.
```

`AGENTS.md`: append `content=DIR loads a content pack (packs/example is the in-repo reference)` to the `make run` comment line in the Commands block.

`CONTEXT.md`: add the row to the engine table:

```markdown
| `engine/content/` | `schema.py` pack records + `BEHAVIOUR_LIFE`; `pack.py` reader, digest, archive checks; `world.py` records -> appended `WorldObject`s, `attach`; `enemies.py` pursuer/sentry state machine; `runner.py` the tick's behaviour branch |
```

and, before `## Testing conventions`, a section:

```markdown
## Content packs boundary

- A pack (`packs/example`) is TOML: `pack.toml` + `enemies/*.toml`. Records
  compile to `WorldObject`s appended after the 292 OBJETS ones with
  `life = BEHAVIOUR_LIFE (-2)`; `life_gate` admits only `life >= 0`, and the
  tick's LIFE loop runs `content.run_behaviour` for `-2` actors at the same
  slot position. Behaviours call only what opcodes call (`init_deplacement`
  + `process_track`, `init_anim`, `anim_action.arm_strike`, `delete_object`).
- `game.pack`, `game.content` (records by world index) and
  `game.content_state[world_idx] = {"hp", "phase"}` are the whole runtime
  surface; saves (schema 3) carry `source.pack` and `content_state` and
  refuse a mismatch either way. `--content DIR` is CLI-only; a bad pack exits
  2 before any window. `engine/content` imports `script.game`'s leaf modules
  only (`boot.init_game` imports `attach` lazily); `test_layering.py` pins it.
- Real numbers the example pack rests on: body 24's anims stand 22 / walk 23
  / attack 25 / hurt 21 / death 24, `LM_HIT(25, 1, 22, 400, 1, 22)`, a strike
  from ~2000 Manhattan units, follow no closer than ~800.
```

In `CONTEXT.md`'s M4a2 persistence section (line ~500) change `SCHEMA` (2) to (3) and add `content_state` to the listed root keys and `pack` to the `source` keys.

Run: `make test-meta`
Expected: green (the docs tests still find their pinned strings).

- [ ] **Step 6: Commit**

```bash
git add PyAitD/app/shell.py Makefile README.md AGENTS.md CONTEXT.md tests/test_main.py tests/test_runtime_modes.py
git commit -m "feat(app): --content DIR loads a content pack for the session; restart, hero boot and load keep it"
```

---

## Final verification

- [ ] `make test` green; `make test-journey` green; `make prove-persistence` green; `make proof-combat` green (the floor-5 venue is untouched by packs).
- [ ] `make run content=packs/example floor=0`: the prowler crosses the attic and strikes; the watcher turns and strikes only when approached; Esc → Save, then Load, works; `make run floor=0` (no pack) then Load of that save shows "Could not load save-manual.json: source.pack: save was made with content pack example; none is attached".
- [ ] `git status` clean.
