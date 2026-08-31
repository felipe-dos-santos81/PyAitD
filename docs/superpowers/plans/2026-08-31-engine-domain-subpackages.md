# Engine Domain Subpackages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure `PyAitD/engine/` into five domain subpackages, split the three oversized modules, and close the AITD1-only seams into `GameProfile` — with zero behavior change.

**Architecture:** S1 moves the 29 flat engine modules into `data/`, `space/`, `actor/`, `script/`, `nav/` via `git mv` + a scripted import rewrite (one task per domain, suite green after each). S2 splits `game`/`interaction`/`playworld` into same-named subpackages whose `__init__.py` re-exports the full original surface. S3 adds 12 `GameProfile` fields and rewires the engine read-sites to them, proven byte-identical by the golden suite. S4 rewrites the living docs.

**Tech Stack:** Python 3.12, pytest, no new dependencies (pygame-ce/ModernGL/NumPy/pytest only).

**Spec:** `docs/superpowers/specs/2026-08-31-engine-domain-subpackages-design.md`

## Global Constraints

- `make test` (headless) is the gate; it must pass at the end of every task before that task's commit. Targeted runs during a task use `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest <files> -q` (direct pytest needs the dummy drivers).
- `# SPDX-License-Identifier: GPL-2.0-only` stays the first line of every Python file, including every new `__init__.py`.
- All imports absolute (`from PyAitD...`); `tests/test_layering.py` rejects relative imports repo-wide.
- Every module move is a `git mv`. No compatibility shims: old flat `PyAitD.engine.X` paths disappear.
- Golden values, do-not-fix quirks, `ponytail:` comments, and FITD `file:line` citations move verbatim. A golden diff means the change is wrong — fix it, never re-derive goldens.
- No renames of functions, classes, or test files beyond what the moves require. Legacy `prove-*` gate pins select test files by stem — test file names do not change.
- Dependency set unchanged. `engine/` stays pygame/GL-free.
- `tests/test_game_profile.py` is the only test file that may contain `from PyAitD.games.aitd1.profile import AITD1`; other tests read profile values through the `profile` fixture.
- Commit message style follows the log: `refactor:`, `test:`, `docs:` prefixes.
- Do not edit `docs/superpowers/specs/**` or `docs/superpowers/plans/**` (dated records), `CONTEXT.md`/`AGENTS.md`/proof docs are living and updated only in S4.

## Domain map (reference for every S1 task)

| domain | modules |
|---|---|
| `data` | pak, explode, formats, floor, assets, text, mask, mask_geometry |
| `space` | cos_table, world, realvalue |
| `actor` | actors, anim, anim_action, tracks, skel |
| `script` | game, interaction, life, eval_var, effects, playworld, save |
| `nav` | navmesh, picking, navigate |

---

## S1 — Domain moves (Tasks 1-6)

Each task moves one domain: `git mv` the modules, run the rewrite script for
exactly that domain's modules, verify no stale references, green suite,
commit. The rewrite script is created once in Task 1 at `/tmp/` (outside the
repo: the SPDX pin and layering scan cover only `PyAitD/`, `tests/`,
`tools/`) and reused by Tasks 2-5.

### Task 1: Rewrite script + move `data/`

**Files:**
- Create: `/tmp/rewrite_engine_paths.py`
- Create: `PyAitD/engine/data/__init__.py`
- Move: `PyAitD/engine/{pak,explode,formats,floor,assets,text,mask,mask_geometry}.py` → `PyAitD/engine/data/`

**Interfaces:**
- Consumes: nothing.
- Produces: `PyAitD.engine.data.<mod>` import paths for the 8 modules; the rewrite script used by Tasks 2-5.

- [ ] **Step 1: Write the rewrite script**

Create `/tmp/rewrite_engine_paths.py`:

```python
import pathlib
import re
import sys

ROOT = pathlib.Path("/Users/felipe.dos.santos/code/mine/m-aitd")
MAP = {
    "pak": "data", "explode": "data", "formats": "data", "floor": "data",
    "assets": "data", "text": "data", "mask": "data", "mask_geometry": "data",
    "cos_table": "space", "world": "space", "realvalue": "space",
    "actors": "actor", "anim": "actor", "anim_action": "actor",
    "tracks": "actor", "skel": "actor",
    "game": "script", "interaction": "script", "life": "script",
    "eval_var": "script", "effects": "script", "playworld": "script",
    "save": "script",
    "navmesh": "nav", "picking": "nav", "navigate": "nav",
}
only = set(sys.argv[1:])
active = {m: d for m, d in MAP.items() if not only or m in only}
if not active:
    sys.exit("no modules selected")

dotted = re.compile(
    r"PyAitD\.engine\.(" + "|".join(sorted(active, key=len, reverse=True)) + r")\b"
)
from_import = re.compile(r"^(?P<indent>[ \t]*)from PyAitD\.engine import (?P<names>[^\n(]+)$", re.MULTILINE)


def rewrite_dotted(match):
    mod = match.group(1)
    return f"PyAitD.engine.{active[mod]}.{mod}"


def rewrite_from(match):
    names = [n.strip() for n in match.group("names").split(",")]
    moved, kept = [], []
    for n in names:
        base = n.split(" as ")[0].strip()
        (moved if base in active else kept).append(n)
    lines = [
        f"{match.group('indent')}from PyAitD.engine.{active[n.split(' as ')[0].strip()]} import {n}"
        for n in moved
    ]
    if kept:
        lines.append(f"{match.group('indent')}from PyAitD.engine import {', '.join(kept)}")
    return "\n".join(lines)


changed, skipped = [], []
for base in ("PyAitD", "tests", "tools"):
    for path in sorted((ROOT / base).rglob("*.py")):
        text = path.read_text()
        if "from PyAitD.engine import (" in text:
            skipped.append(str(path.relative_to(ROOT)))
        new = from_import.sub(rewrite_from, dotted.sub(rewrite_dotted, text))
        if new != text:
            path.write_text(new)
            changed.append(str(path.relative_to(ROOT)))
print(f"rewrote {len(changed)} files")
for path in skipped:
    print(f"WARNING multiline from-import left for hand edit: {path}")
```

- [ ] **Step 2: Move the data modules and create the package init**

```bash
mkdir PyAitD/engine/data
git mv PyAitD/engine/pak.py PyAitD/engine/explode.py PyAitD/engine/formats.py \
       PyAitD/engine/floor.py PyAitD/engine/assets.py PyAitD/engine/text.py \
       PyAitD/engine/mask.py PyAitD/engine/mask_geometry.py PyAitD/engine/data/
```

Create `PyAitD/engine/data/__init__.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Data loading: archive bytes -> parsed records (PAK/HQR, EXPLODE, ETAGE
floors, format parsers, parse-once registries, texts, overlay masks)."""
```

- [ ] **Step 3: Rewrite references to the data modules**

```bash
python /tmp/rewrite_engine_paths.py pak explode formats floor assets text mask mask_geometry
```

Expected: `rewrote N files` (N roughly 60-80), no WARNING lines. If a WARNING
appears, hand-edit the listed file's multiline `from PyAitD.engine import (...)`
to the new domain paths.

- [ ] **Step 4: Verify no stale references to data modules remain**

```bash
grep -rEn "PyAitD\.engine\.(pak|explode|formats|floor|assets|text|mask_geometry|mask)\b" PyAitD tests tools
```

Expected: no output.

- [ ] **Step 5: Run the gate**

Run: `make test`
Expected: PASS (only import paths changed).

- [ ] **Step 6: Commit**

```bash
git add PyAitD/engine/data PyAitD tests tools
git commit -m "refactor: move data-loading modules into engine/data"
```

### Task 2: Move `space/`

**Files:**
- Create: `PyAitD/engine/space/__init__.py`
- Move: `PyAitD/engine/{cos_table,world,realvalue}.py` → `PyAitD/engine/space/`

**Interfaces:**
- Consumes: `/tmp/rewrite_engine_paths.py` (Task 1).
- Produces: `PyAitD.engine.space.{cos_table,world,realvalue}`.

- [ ] **Step 1: Move and create the package init**

```bash
mkdir PyAitD/engine/space
git mv PyAitD/engine/cos_table.py PyAitD/engine/world.py PyAitD/engine/realvalue.py PyAitD/engine/space/
```

Create `PyAitD/engine/space/__init__.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Shared math: fixed-point trig, camera transforms, rotation/speed interpolation."""
```

- [ ] **Step 2: Rewrite references**

```bash
python /tmp/rewrite_engine_paths.py cos_table world realvalue
```

- [ ] **Step 3: Verify no stale references**

```bash
grep -rEn "PyAitD\.engine\.(cos_table|world|realvalue)\b" PyAitD tests tools
```

Expected: no output.

- [ ] **Step 4: Run the gate**

Run: `make test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/space PyAitD tests tools
git commit -m "refactor: move spatial-math modules into engine/space"
```

### Task 3: Move `actor/`

**Files:**
- Create: `PyAitD/engine/actor/__init__.py`
- Move: `PyAitD/engine/{actors,anim,anim_action,tracks,skel}.py` → `PyAitD/engine/actor/`

**Interfaces:**
- Consumes: `/tmp/rewrite_engine_paths.py` (Task 1).
- Produces: `PyAitD.engine.actor.{actors,anim,anim_action,tracks,skel}`.

- [ ] **Step 1: Move and create the package init**

```bash
mkdir PyAitD/engine/actor
git mv PyAitD/engine/actors.py PyAitD/engine/anim.py PyAitD/engine/anim_action.py \
       PyAitD/engine/tracks.py PyAitD/engine/skel.py PyAitD/engine/actor/
```

Create `PyAitD/engine/actor/__init__.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Actors: tObject state, keyframe animation, combat actions, movement tracks, skinning."""
```

- [ ] **Step 2: Rewrite references**

```bash
python /tmp/rewrite_engine_paths.py actors anim anim_action tracks skel
```

- [ ] **Step 3: Verify no stale references**

```bash
grep -rEn "PyAitD\.engine\.(actors|anim_action|anim|tracks|skel)\b" PyAitD tests tools
```

Expected: no output.

- [ ] **Step 4: Run the gate**

Run: `make test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/actor PyAitD tests tools
git commit -m "refactor: move actor/animation modules into engine/actor"
```

### Task 4: Move `nav/`

**Files:**
- Create: `PyAitD/engine/nav/__init__.py`
- Move: `PyAitD/engine/{navmesh,picking,navigate}.py` → `PyAitD/engine/nav/`

**Interfaces:**
- Consumes: `/tmp/rewrite_engine_paths.py` (Task 1).
- Produces: `PyAitD.engine.nav.{navmesh,picking,navigate}`.

- [ ] **Step 1: Move and create the package init**

```bash
mkdir PyAitD/engine/nav
git mv PyAitD/engine/navmesh.py PyAitD/engine/picking.py PyAitD/engine/navigate.py PyAitD/engine/nav/
```

Create `PyAitD/engine/nav/__init__.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Pointer navigation: walkable navmesh, screen->world picking, NavIntent steering."""
```

- [ ] **Step 2: Rewrite references**

```bash
python /tmp/rewrite_engine_paths.py navmesh picking navigate
```

- [ ] **Step 3: Verify no stale references**

```bash
grep -rEn "PyAitD\.engine\.(navmesh|picking|navigate)\b" PyAitD tests tools
```

Expected: no output.

- [ ] **Step 4: Run the gate**

Run: `make test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/nav PyAitD tests tools
git commit -m "refactor: move navigation modules into engine/nav"
```

### Task 5: Move `script/`

**Files:**
- Create: `PyAitD/engine/script/__init__.py`
- Move: `PyAitD/engine/{game,interaction,life,eval_var,effects,playworld,save}.py` → `PyAitD/engine/script/`

**Interfaces:**
- Consumes: `/tmp/rewrite_engine_paths.py` (Task 1).
- Produces: `PyAitD.engine.script.<mod>` for the 7 modules. After this task the flat engine is gone; `PyAitD/engine/` holds only `__init__.py` and the five domains.

- [ ] **Step 1: Move and create the package init**

```bash
mkdir PyAitD/engine/script
git mv PyAitD/engine/game.py PyAitD/engine/interaction.py PyAitD/engine/life.py \
       PyAitD/engine/eval_var.py PyAitD/engine/effects.py PyAitD/engine/playworld.py \
       PyAitD/engine/save.py PyAitD/engine/script/
```

Create `PyAitD/engine/script/__init__.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Game state and scripting: Game, LIFE VM, interaction, effects, the 50 Hz tick, saves."""
```

- [ ] **Step 2: Rewrite references**

```bash
python /tmp/rewrite_engine_paths.py game interaction life eval_var effects playworld save
```

Note: this also rewrites the string rows of `PRESENTATION_FREE` in
`tests/test_layering.py` (they are raw text like every other reference).

- [ ] **Step 3: Verify the flat engine is gone**

```bash
grep -rEn "PyAitD\.engine\.(game|interaction|life|eval_var|effects|playworld|save)\b" PyAitD tests tools
ls PyAitD/engine/*.py
```

Expected: no grep output; `ls` shows only `PyAitD/engine/__init__.py`.

- [ ] **Step 4: Run the gate**

Run: `make test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/script PyAitD tests tools
git commit -m "refactor: move game-state and scripting modules into engine/script"
```

### Task 6: Domain layering pins

**Files:**
- Modify: `tests/test_layering.py:21-25` (the `FORBIDDEN` dict)

**Interfaces:**
- Consumes: the five domains (Tasks 1-5).
- Produces: `FORBIDDEN["engine/data"]` and `FORBIDDEN["engine/space"]` pins; existing `test_package_imports_only_what_the_layering_allows` parametrizes over them unchanged.

- [ ] **Step 1: Add the two domain pins**

Replace the `FORBIDDEN` dict in `tests/test_layering.py` with:

```python
FORBIDDEN = {
    "engine": PRESENTATION + ("PyAitD.games",),
    # Leaf-domain pins (2026-08-31-engine-domain-subpackages-design.md):
    # data is fully closed; space may reach data and nothing else. actor,
    # script and nav carry pre-existing cycles and get no stricter pin.
    "engine/data": PRESENTATION + (
        "PyAitD.games",
        "PyAitD.engine.space", "PyAitD.engine.actor",
        "PyAitD.engine.script", "PyAitD.engine.nav",
    ),
    "engine/space": PRESENTATION + (
        "PyAitD.games",
        "PyAitD.engine.actor", "PyAitD.engine.script", "PyAitD.engine.nav",
    ),
    "render": ("PyAitD.games", "PyAitD.app"),
    "games": ("pygame", "moderngl", "PyAitD.render", "PyAitD.app"),
}
```

- [ ] **Step 2: Run the meta group**

Run: `make test-meta`
Expected: PASS. These pins are a ratchet, not red-green: exploration verified
the graph is already closed (`data`'s edges stay in `data`; `space` reaches
only `data`), so the new pins pass on first run. A failure here means a move
task left a cross-domain edge — find it with
`grep -rn "PyAitD.engine.\(space\|actor\|script\|nav\)" PyAitD/engine/data PyAitD/engine/space`
and fix the import, not the pin.

- [ ] **Step 3: Run the full gate plus journeys**

Run: `make test && make test-journey`
Expected: PASS (real game data present).

- [ ] **Step 4: Delete the rewrite script and commit**

```bash
rm /tmp/rewrite_engine_paths.py
git add tests/test_layering.py
git commit -m "test: pin the leaf engine domains in the layering scan"
```

---

## S2 — Oversized splits (Tasks 7-9)

Each task converts one flat `engine/script/<mod>.py` into a same-named
subpackage whose `__init__.py` re-exports the **complete** original module
surface (every top-level name, underscore names included), so no importer
changes. Rules that apply to all three tasks:

- Move definitions **verbatim** — code, comments, FITD citations, blank-line
  style. Line ranges below are from the pre-split file and shift as you cut;
  go by definition name.
- Distribute the original module's imports: each new file imports only what
  its own definitions use. The suite surfaces a miss immediately
  (`NameError`/`ImportError`).
- **Sibling imports inside the package use full dotted module paths, never
  the package itself** — `from PyAitD.engine.script.game.state import Actor`
  in `objects.py`, never `from PyAitD.engine.script.game import Actor`
  (that routes through `__init__.py` and circular-imports).
- Lazy (function-level) imports stay lazy, in the file whose code runs them.
- These tasks are behavior-preserving rewrites, not red-green: the suite
  (goldens included) is the proof, run before commit.

### Task 7: Split `game.py` into `engine/script/game/`

**Files:**
- Move: `PyAitD/engine/script/game.py` → `PyAitD/engine/script/game/state.py` (then split)
- Create: `PyAitD/engine/script/game/{zv,objects,boot}.py`, `PyAitD/engine/script/game/__init__.py`

**Interfaces:**
- Consumes: `PyAitD.engine.script.game` module path (S1).
- Produces: identical `PyAitD.engine.script.game.<name>` import surface via the package; internal modules `state`/`zv`/`objects`/`boot` that S3 Task 11 rewires.

- [ ] **Step 1: Convert the module to a package**

```bash
mkdir PyAitD/engine/script/game
git mv PyAitD/engine/script/game.py PyAitD/engine/script/game/state.py
```

- [ ] **Step 2: Cut the four modules**

`state.py` keeps: module docstring, `NUM_MAX_OBJECT`, the nine `AF_*` flag
constants, `RealValue`, `Actor`, `FloorStart`, `Game` (pre-split lines 1-235).
It imports neither `interaction` nor `tracks`.

Create `PyAitD/engine/script/game/zv.py` (SPDX first line, one-line docstring
`"""ZV box geometry: fixed-point rotation helpers (pure)."""`) with, moved
verbatim from `state.py`: `_zv_default`, `_zv_max`, `_zv_cube`,
`_point_rotate`, `_zv_rot`, `_hard_zv` (pre-split lines 238-306).

Create `PyAitD/engine/script/game/objects.py` (docstring `"""World object <->
actor slot lifecycle (InitObjet/DeleteObjet/PutAtObjet/GenereActiveList)."""`)
with: `add_actor`, `_delete_objet`, `delete_object`, `put_at_objet`,
`activate_world_object`, `spawn_stage_actors` (pre-split lines 309-557).
`add_actor` reads `Actor`/flags from `state` and the `_zv_*` helpers from
`zv` via full dotted sibling imports; the lazy `tracks.init_deplacement`
import (pre-split line 499) and the lazy `interaction.remove_from_inventory`
imports (pre-split lines 463, 493) stay function-level in this file.

Create `PyAitD/engine/script/game/boot.py` (docstring `"""Boot and floor
transitions: startGame/initGame/ChangeSalle/floor starts."""`) with:
`change_salle`, `relocate_actor`, `enter_floor_start`, `start_game`,
`game_step_tick`, `init_game` (pre-split lines 560-649). The lazy
`interaction.sync_player_track_mode` import (pre-split line 632) stays
function-level here.

- [ ] **Step 3: Write the re-export `__init__.py`**

Create `PyAitD/engine/script/game/__init__.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Game state, world-object lifecycle and boot (subpackage split of the
former engine.game module; every name re-exported for importers)."""
from PyAitD.engine.script.game.state import (
    AF_ANIMATED, AF_BOXIFY, AF_DRAWABLE, AF_FALLABLE, AF_FOUNDABLE, AF_MASK,
    AF_MOVABLE, AF_SPECIAL, AF_TRIGGER, NUM_MAX_OBJECT, Actor, FloorStart,
    Game, RealValue,
)
from PyAitD.engine.script.game.zv import (
    _hard_zv, _point_rotate, _zv_cube, _zv_default, _zv_max, _zv_rot,
)
from PyAitD.engine.script.game.objects import (
    _delete_objet, activate_world_object, add_actor, delete_object,
    put_at_objet, spawn_stage_actors,
)
from PyAitD.engine.script.game.boot import (
    change_salle, enter_floor_start, game_step_tick, init_game,
    relocate_actor, start_game,
)
```

- [ ] **Step 4: Run the gate**

Run: `make test`
Expected: PASS. An `ImportError` naming a missing symbol means a definition
stayed behind or an import was not distributed — fix the split, not the test.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/script/game
git commit -m "refactor: split engine/script/game into a subpackage"
```

### Task 8: Split `interaction.py` into `engine/script/interaction/`

**Files:**
- Move: `PyAitD/engine/script/interaction.py` → `PyAitD/engine/script/interaction/inventory.py` (then split)
- Create: `PyAitD/engine/script/interaction/{track_mode,life_cont,combat,contacts,nav_intent}.py`, `PyAitD/engine/script/interaction/__init__.py`

**Interfaces:**
- Consumes: `PyAitD.engine.script.interaction` module path (S1).
- Produces: identical import surface via the package; internal modules S3 Task 14 rewires (`combat`, `track_mode`, `contacts`, `nav_intent`).

- [ ] **Step 1: Convert the module to a package**

```bash
mkdir PyAitD/engine/script/interaction
git mv PyAitD/engine/script/interaction.py PyAitD/engine/script/interaction/inventory.py
```

- [ ] **Step 2: Cut the six modules**

`inventory.py` keeps: module docstring, `INVENTORY_SIZE`,
`MAX_VISIBLE_ACTIONS`, `inventory_items`, `find_in_inventory`,
`inventory_weight`, `inventory_actions`, `request_found`,
`remove_from_inventory`, `_finish_take`, `begin_take`, `put_object`,
`drop_object`, `choose_inventory_action`, `apply_found_result`,
`apply_inventory_result`, `apply_reading_result` (pre-split lines 1-17,
144-162, 278-358, 411-445). The `apply_*_result` functions call
`resume_life` — import it as
`from PyAitD.engine.script.interaction.life_cont import resume_life`.

Create `track_mode.py` (docstring `"""Player track-mode sync between input
modes."""`) with: `PLAYER_TRACK_MODES`, `player_track_mode`,
`sync_player_track_mode` (pre-split lines 16, 19-45).

Create `life_cont.py` (docstring `"""LIFE continuation stack, found-LIFE
execution, and the message/immediate-effect pump."""`) with:
`_release_temporary_actor`, `_complete_after_life`, `run_life`,
`resume_life`, `_add_message`, `drain_immediate_effects`,
`advance_messages`, `execute_found_life` (pre-split lines 48-141).

Create `combat.py` (docstring `"""In-hand combat gating and held/push
approach."""`) with: `COMBAT_ACTIONS`, `PLAYER_STAND_ANIM`,
`PLAYER_PUSH_ANIM`, `is_combat_target`, `is_hold_action_target`,
`hold_action_approach`, `combat_action_for`, `can_strike`,
`attack_in_hand` (pre-split lines 11-13, 165-275, 522-552).

Create `contacts.py` (docstring `"""Object-collision resolution and zone
walks (GereDec)."""`) with: `resolve_actor_contacts`, `point_in_zone`,
`gere_dec` (pre-split lines 361-408, 448-449, 586-617).

Create `nav_intent.py` (docstring `"""NavIntent record/drop and follower
arrival dispatch."""`) with: `apply_click_intent`, `cancel_nav_intent`,
`cancel_held_nav_intent`, `dispatch_nav_arrival` (pre-split lines 452-519,
555-583). `cancel_nav_intent` uses `PLAYER_STAND_ANIM` — import it as
`from PyAitD.engine.script.interaction.combat import PLAYER_STAND_ANIM`.

- [ ] **Step 3: Write the re-export `__init__.py`**

Create `PyAitD/engine/script/interaction/__init__.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""Inventory/world interaction, contacts and nav intents (subpackage split
of the former engine.interaction module; every name re-exported)."""
from PyAitD.engine.script.interaction.track_mode import (
    PLAYER_TRACK_MODES, player_track_mode, sync_player_track_mode,
)
from PyAitD.engine.script.interaction.life_cont import (
    _add_message, _complete_after_life, _release_temporary_actor,
    advance_messages, drain_immediate_effects, execute_found_life,
    resume_life, run_life,
)
from PyAitD.engine.script.interaction.inventory import (
    INVENTORY_SIZE, MAX_VISIBLE_ACTIONS, _finish_take, apply_found_result,
    apply_inventory_result, apply_reading_result, begin_take,
    choose_inventory_action, drop_object, find_in_inventory,
    inventory_actions, inventory_items, inventory_weight, put_object,
    remove_from_inventory, request_found,
)
from PyAitD.engine.script.interaction.combat import (
    COMBAT_ACTIONS, PLAYER_PUSH_ANIM, PLAYER_STAND_ANIM, attack_in_hand,
    can_strike, combat_action_for, hold_action_approach,
    is_combat_target, is_hold_action_target,
)
from PyAitD.engine.script.interaction.contacts import (
    gere_dec, point_in_zone, resolve_actor_contacts,
)
from PyAitD.engine.script.interaction.nav_intent import (
    apply_click_intent, cancel_held_nav_intent, cancel_nav_intent,
    dispatch_nav_arrival,
)
```

- [ ] **Step 4: Run the gate**

Run: `make test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/script/interaction
git commit -m "refactor: split engine/script/interaction into a subpackage"
```

### Task 9: Split `playworld.py` into `engine/script/playworld/`

**Files:**
- Move: `PyAitD/engine/script/playworld.py` → `PyAitD/engine/script/playworld/tick.py` (then split)
- Create: `PyAitD/engine/script/playworld/{input,held_push,passes}.py`, `PyAitD/engine/script/playworld/__init__.py`

**Interfaces:**
- Consumes: `PyAitD.engine.script.playworld` module path (S1).
- Produces: identical import surface via the package (`TICK_MS` and `play_tick` are the names outsiders import); `held_push.py` is what S3 Task 14 rewires for `PLAYER_PUSH_ANIM`.

- [ ] **Step 1: Convert the module to a package**

```bash
mkdir PyAitD/engine/script/playworld
git mv PyAitD/engine/script/playworld.py PyAitD/engine/script/playworld/tick.py
```

- [ ] **Step 2: Cut the four modules**

`tick.py` keeps: module docstring, `TICK_MS`, `NATIVE_ACTION`,
`MOUSE_ATTACK_TICK_BUDGET`, `play_tick` (pre-split lines 1-29, 450-525).
`play_tick` calls into the sibling modules via full dotted imports
(`from PyAitD.engine.script.playworld.input import apply_play_input`, etc.).

Create `input.py` (docstring `"""PLAY input snapshot: track-mode re-assert,
mouse follower decision, bounded attack publishing."""`) with:
`apply_play_input`, `_clear_mouse_attack`, `_apply_mouse_attack`,
`_apply_mouse_input` (pre-split lines 32-47, 262-364).
`_apply_mouse_input` uses `_refresh_held_target` — import it as
`from PyAitD.engine.script.playworld.held_push import _refresh_held_target`.

Create `held_push.py` (docstring `"""Held-push follower geometry: retarget,
push point, contact detour, corridor helpers."""`) with:
`_push_into_target`, `_refresh_held_target`, `_held_push_point`,
`_held_contact_detour`, `_corridor_hits_actor`, `_path_distance`
(pre-split lines 50-259). The `PLAYER_PUSH_ANIM` import (pre-split line 84)
stays here — S3 Task 14 rewires it.

Create `passes.py` (docstring `"""Per-actor anim/LIFE passes, cover-zone
camera switch, active-list regen, game-over handoff."""`) with:
`_run_actor_action`, `_anim_pass`, `_cover_zones`, `_camera_switch`,
`_genere_active_list`, `_handoff_game_over` (pre-split lines 367-447).

- [ ] **Step 3: Write the re-export `__init__.py`**

Create `PyAitD/engine/script/playworld/__init__.py`:

```python
# SPDX-License-Identifier: GPL-2.0-only
"""The fixed 50 Hz PLAY tick in FITD mainLoop order (subpackage split of
the former engine.playworld module; every name re-exported)."""
from PyAitD.engine.script.playworld.tick import (
    MOUSE_ATTACK_TICK_BUDGET, NATIVE_ACTION, TICK_MS, play_tick,
)
from PyAitD.engine.script.playworld.input import (
    _apply_mouse_attack, _apply_mouse_input, _clear_mouse_attack,
    apply_play_input,
)
from PyAitD.engine.script.playworld.held_push import (
    _corridor_hits_actor, _held_contact_detour, _held_push_point,
    _path_distance, _push_into_target, _refresh_held_target,
)
from PyAitD.engine.script.playworld.passes import (
    _anim_pass, _camera_switch, _cover_zones, _genere_active_list,
    _handoff_game_over, _run_actor_action,
)
```

- [ ] **Step 4: Run the gate**

Run: `make test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/script/playworld
git commit -m "refactor: split engine/script/playworld into a subpackage"
```

---

## S3 — Seam closing (Tasks 10-16)

**Deviation from the spec, decided here with evidence:** the spec's table
lists `actor_has_hard_mat`. Exploration found **no read-site** in the Python
engine — nothing parses or reads `hardMat` (AITD1 has no zone type 8;
FITD `vars.h:179-181` gates it behind generation predicates our AITD1 code
never reaches). A field with no consumer is dead weight, so this plan
implements **12 fields** and drops `actor_has_hard_mat`; it arrives with its
first consumer when AITD2 work begins. The other 12 match the spec exactly.

Task order: Task 10 lands all 12 fields with AITD1 values and value-pins
(engine still reads its old literals — the fields are inert until their
cluster task). Tasks 11-15 rewire one cluster each; each deletes its engine
literals and adds its absence-pin (red → rewire → green). Task 16 rewrites
the seam-status docstring and sweeps for leftovers.

### Task 10: GameProfile gains the 12 fields

**Files:**
- Modify: `PyAitD/games/base.py` (field declarations)
- Modify: `PyAitD/games/aitd1/profile.py` (AITD1 values)
- Test: `tests/test_game_profile.py`

**Interfaces:**
- Consumes: existing `GameProfile` (frozen dataclass) and the AITD1 instance.
- Produces: `GameProfile.generation`, `.floor_archive_name`, `.camera_archive_name`, `.mask_factory`, `.cadre_bank`, `.core_slots`, `.combat_action_text_ids`, `.player_stand_anim`, `.player_push_anim`, `.player_track_modes`, `.viewed_room_record_size`, `.world_object_has_mark`; `games.aitd1.profile.{NUM_OPCODES, CORE_SLOTS, DEAD_OPCODES, floor_archive_name, camera_archive_name}` module constants used by Tasks 11-15.

- [ ] **Step 1: Write the failing value-pin tests**

Append to `tests/test_game_profile.py`:

```python
def test_aitd1_generation_is_the_fitd_game_type_ordinal():
    # FITD vars.h:5-12 gameTypeEnum { AITD1, JACK, AITD2, AITD3, TIMEGATE }
    assert AITD1.generation == 0


def test_aitd1_archive_naming_and_overlay_strategy():
    # floor.cpp:26-28; AITD1 computes masks, JACK+ loads MASK%02d PAKs
    # (main.cpp:2178-2190) — the strategy is the profile's, the name is the game's
    assert AITD1.floor_archive_name(5) == "ETAGE05"
    assert AITD1.camera_archive_name(12) == "CAMERA12"
    from PyAitD.engine.data.mask import create_aitd1_mask
    assert AITD1.mask_factory is create_aitd1_mask


def test_aitd1_cadre_bank_pins_the_cadre_sprite_source():
    # ITD_RESS entry 4, nine sprites (aitdBox.cpp AffCadre sprite layout)
    assert AITD1.cadre_bank == (4, 9)


def test_aitd1_core_slots_pin_the_vm_control_numbering():
    # AITD1LifeMacroTable (AITD1.cpp:30-119): the game-neutral op slots
    assert len(AITD1.core_slots) == 19
    assert AITD1.core_slots["IF_EGAL"] == 4
    assert AITD1.core_slots["MULTI_CASE"] == 29


def test_aitd1_player_control_indices():
    assert AITD1.combat_action_text_ids == frozenset({32})
    assert AITD1.player_stand_anim == 4
    assert AITD1.player_push_anim == 5
    assert AITD1.player_track_modes == (1, 4)


def test_aitd1_record_layouts():
    # floor.cpp:367-375 (0x0C AITD1, 0x10 JACK+); main.cpp:1117-1121 (mark)
    assert AITD1.viewed_room_record_size == 0x0C
    assert AITD1.world_object_has_mark is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_game_profile.py -q`
Expected: the six new tests FAIL with `AttributeError: 'GameProfile' object
has no attribute 'generation'` (and likewise for the other fields); the
pre-existing tests still pass.

- [ ] **Step 3: Add the fields to `GameProfile`**

In `PyAitD/games/base.py`, insert these declarations after `debug_venues`
and before the `intro_start` comment block (required fields must precede
the defaulted ones):

```python
    generation: int            # FITD gameTypeEnum ordinal (vars.h:5-12): AITD1=0, JACK=1, AITD2=2, AITD3=3, TIMEGATE=4
    floor_archive_name: object # callable(floor_number) -> PAK base name (floor.cpp:26-28)
    camera_archive_name: object # callable(floor_number) -> PAK base name
    mask_factory: object       # callable(camera_raw, offset) -> mask bitmap; AITD1 computes (createAITD1Mask), JACK+ loads MASK%02d PAKs (main.cpp:2178-2190)
    cadre_bank: tuple          # (ITD_RESS entry, sprite count) of the cadre sprite bank
    core_slots: Mapping        # semantic VM-control op name -> bytecode slot, per the game's life macro table
    combat_action_text_ids: frozenset  # inventory action text ids that arm combat
    player_stand_anim: int     # hero anim index: stand
    player_push_anim: int      # hero anim index: push
    player_track_modes: tuple  # track_mode values meaning player-controlled
    viewed_room_record_size: int  # viewed-room record stride (floor.cpp:367-375): 0x0C AITD1, 0x10 JACK+
    world_object_has_mark: bool    # OBJETS.ITD records carry a trailing mark s16 (main.cpp:1117-1121)
```

- [ ] **Step 4: Add the AITD1 values**

In `PyAitD/games/aitd1/profile.py`, add the import at the top:

```python
from PyAitD.engine.data.mask import create_aitd1_mask
```

and after the `REDUCED_ALLOWED` definition:

```python
# AITD1LifeMacroTable (AITD1.cpp:30-119): slot count, the VM-control
# numbering within it, and the holes in FITD's dispatch switch.
NUM_OPCODES = 87
CORE_SLOTS = MappingProxyType({
    "IF_EGAL": 4, "IF_DIFFERENT": 5, "IF_SUP_EGAL": 6, "IF_SUP": 7,
    "IF_INF_EGAL": 8, "IF_INF": 9, "GOTO": 10, "RETURN": 11, "END": 12,
    "VAR": 19, "INC": 20, "DEC": 21, "ADD": 22, "SUB": 23,
    "LIFE_MODE": 24, "SWITCH": 25, "CASE": 26, "START_CHRONO": 28,
    "MULTI_CASE": 29,
})
DEAD_OPCODES = frozenset({27, 57, 61, 69})


def floor_archive_name(number):  # floor.cpp:26-28
    return f"ETAGE{number:02d}"


def camera_archive_name(number):
    return f"CAMERA{number:02d}"
```

Then add to the `AITD1 = GameProfile(...)` call, after `debug_venues=...`:

```python
    generation=0,
    floor_archive_name=floor_archive_name,
    camera_archive_name=camera_archive_name,
    mask_factory=create_aitd1_mask,
    cadre_bank=(4, 9),
    core_slots=CORE_SLOTS,
    combat_action_text_ids=frozenset({32}),
    player_stand_anim=4,
    player_push_anim=5,
    player_track_modes=(1, 4),
    viewed_room_record_size=0x0C,
    world_object_has_mark=False,
```

- [ ] **Step 5: Fix the base-profile constructor test**

In `tests/test_game_profile.py::test_base_profile_alt_camera_sources_defaults_empty`,
add the new required kwargs to the `GameProfile(...)` call:

```python
                            debug_venues={}, generation=0,
                            floor_archive_name=lambda n: "E", camera_archive_name=lambda n: "C",
                            mask_factory=lambda raw, off: None, cadre_bank=(0, 0),
                            core_slots={}, combat_action_text_ids=frozenset(),
                            player_stand_anim=0, player_push_anim=0, player_track_modes=(),
                            viewed_room_record_size=0x0C, world_object_has_mark=False)
```

- [ ] **Step 6: Run the profile tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_game_profile.py -q`
Expected: PASS.

- [ ] **Step 7: Run the gate and commit**

Run: `make test`
Expected: PASS (the fields are inert; no engine read-site changed yet).

```bash
git add PyAitD/games tests/test_game_profile.py
git commit -m "feat: add the 12 per-game seam fields to GameProfile"
```

### Task 11: Rewire `floor.py` + camera-record parsers

**Files:**
- Modify: `PyAitD/engine/data/floor.py`
- Modify: `PyAitD/engine/data/formats.py:134-166` (`parse_cameras`), `:399-411` (`parse_cover_zones`)
- Modify: `PyAitD/engine/nav/navmesh.py:33`, `PyAitD/engine/script/playworld/passes.py` (the `_cover_zones` helper, pre-split `playworld.py:399`), `PyAitD/render/texture_export.py:155`
- Modify: `tests/stub_floor.py`, `tests/test_camera_switch.py`, `tests/test_formats.py`, `tests/test_texture_export.py:213`

**Interfaces:**
- Consumes: `profile.floor_archive_name`, `.camera_archive_name`, `.mask_factory`, `.viewed_room_record_size` (Task 10).
- Produces: `Floor.profile`; `Floor.viewed_room_record_size`; `parse_cameras(raw, viewed_room_record_size)`; `parse_cover_zones(camera_raw, camera_off, viewed_idx, viewed_room_record_size)` — every caller passes the profile value, tests pass `0x0C`.

This task is a behavior-preserving rewire: the existing floor/camera/
navmesh/texture tests (goldens included) are the proof, no new red test.

- [ ] **Step 1: Rewire `Floor`**

In `PyAitD/engine/data/floor.py`, `Floor.__init__` becomes:

```python
    def __init__(self, data_dir, number, profile):
        self.number = number
        self.profile = profile
        self.viewed_room_record_size = profile.viewed_room_record_size
        etage = find_pak(data_dir, profile.floor_archive_name(number))
        self._images = find_pak(data_dir, profile.camera_archive_name(number))
        self.rooms = parse_rooms(load_entry(str(etage), 0))
        self.camera_raw = load_entry(str(etage), 1)
        self.cameras = parse_cameras(self.camera_raw, profile.viewed_room_record_size)
        self.camera_data_offsets = camera_offsets(self.camera_raw)
        palette_pak = find_pak(data_dir, profile.resource_pak)
        self.palette = decode_palette(load_entry(str(palette_pak), profile.palette_entry))
        self._num_images = Pak(self._images).count
        self._camera_images = {}
        self._masks = {}
        self._mask_draws = {}
```

and `masks()` uses the profile strategy:

```python
        if camera_idx not in self._masks:
            self._masks[camera_idx] = self.profile.mask_factory(
                self.camera_raw, self.camera_data_offsets[camera_idx],
            )
```

Delete the now-unused `from PyAitD.engine.data.mask import create_aitd1_mask`
import.

- [ ] **Step 2: Parameterize the camera-record parsers**

In `PyAitD/engine/data/formats.py`:

```python
def parse_cameras(raw, viewed_room_record_size):
```

with the stride line changed to `p += viewed_room_record_size` (keep the
comment, reworded: `# per-game stride (floor.cpp:367-375)`).

```python
def parse_cover_zones(camera_raw, camera_off, viewed_idx, viewed_room_record_size):
    vr_off = camera_off + 0x14 + viewed_idx * viewed_room_record_size
```

- [ ] **Step 3: Update every caller**

- `PyAitD/engine/nav/navmesh.py:33`:
  `out.extend(parse_cover_zones(floor.camera_raw, offset, viewed.index(room_idx), floor.viewed_room_record_size))`
- `PyAitD/engine/script/playworld/passes.py` (`_cover_zones`):
  `return parse_cover_zones(floor.camera_raw, off, viewed.index(room_idx), floor.viewed_room_record_size)`
- `PyAitD/render/texture_export.py:155`:
  `return parse_cover_zones(floor.camera_raw, floor.camera_data_offsets[cam_idx], viewed_idx, floor.viewed_room_record_size)`
- `tests/stub_floor.py`: add the attribute `viewed_room_record_size = 0x0C`
  to the stub (it stands in for real floors on the `parse_cover_zones` path).
- `tests/test_camera_switch.py`: the four `parse_cover_zones(cam_raw, off, 0)` calls gain `, 0x0C`; the `parse_cameras(cam_raw)` call gains `, 0x0C`.
- `tests/test_formats.py:25,36`: `parse_cameras(pak.read(1))` → `parse_cameras(pak.read(1), 0x0C)`.
- `tests/test_texture_export.py:213`: the monkeypatch lambda becomes
  `lambda raw, off, vi, rs: calls.append((raw, off, vi)) or [[(1, 2)]]`.

- [ ] **Step 4: Run the affected tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_floor.py tests/test_formats.py tests/test_camera_switch.py tests/test_navmesh.py tests/test_texture_export.py -q`
Expected: PASS.

- [ ] **Step 5: Run the gate and commit**

Run: `make test`
Expected: PASS.

```bash
git add PyAitD tests
git commit -m "refactor: read floor archive naming, mask strategy and viewed-room stride from GameProfile"
```

### Task 12: Rewire `assets.py` (cadre bank + SCREEN_PIXELS)

**Files:**
- Modify: `PyAitD/engine/data/assets.py`

**Interfaces:**
- Consumes: `profile.cadre_bank` (Task 10).
- Produces: `assets.SCREEN_PIXELS = 64000` (module constant with FITD citation); `Assets` reads the cadre entry/sprite count from the profile at init.

- [ ] **Step 1: Write the failing pin**

Append to `tests/test_game_profile.py`:

```python
def test_screen_pixels_is_a_named_constant_not_a_per_game_field():
    # FITD vars.h:272 fixes 320x200 for all five games — the seam closes by
    # evidence: a named constant, not a profile field.
    from PyAitD.engine.data import assets
    assert assets.SCREEN_PIXELS == 64000
```

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_game_profile.py -q -k screen_pixels`
Expected: FAIL — `AttributeError: module 'PyAitD.engine.data.assets' has no
attribute 'SCREEN_PIXELS'`.

- [ ] **Step 2: Rewire `assets.py`**

Add the constant after the imports:

```python
# FITD vars.h:272: frontBuffer[320*200] for every game — 320x200 is an engine
# invariant, so it is a named constant here, not a GameProfile field.
SCREEN_PIXELS = 64000
```

In `Assets.__init__`, after `self._resource_screens = {}`:

```python
        self._cadre_entry, self._cadre_sprite_count = profile.cadre_bank
```

In `resource_screen`, replace both `64000` literals with `SCREEN_PIXELS`
(size check and `raw[:SCREEN_PIXELS]`; the error message renders identically).

In `cadre_bank()`, replace the hardcoded entry and count: `raw =
load_entry(self._resource_pak, self._cadre_entry)`, the short-table check
becomes `if len(raw) < self._cadre_sprite_count * 2:`, the loop is
`for index in range(self._cadre_sprite_count):`, and the error messages use
`self._cadre_entry` in place of the literal `4` (they render identically for
AITD1). Keep the sprite-layout comment, reworded to describe the format
rather than the entry number.

- [ ] **Step 3: Run the pin and the gate**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_game_profile.py -q`
Expected: PASS.

Run: `make test`
Expected: PASS (cadre sprites and resource screens byte-identical).

- [ ] **Step 4: Commit**

```bash
git add PyAitD/engine/data/assets.py tests/test_game_profile.py
git commit -m "refactor: read the cadre bank from GameProfile; name SCREEN_PIXELS"
```

### Task 13: Rewire `life.py` (core table from profile numbering)

**Files:**
- Modify: `PyAitD/engine/script/life.py:232-262` (replace `NUM_OPCODES` + `core_table()`)
- Modify: `PyAitD/games/aitd1/profile.py:26` (the `core_table()` call)
- Modify: `tests/test_life_vm.py:214-217`
- Test: `tests/test_game_profile.py`

**Interfaces:**
- Consumes: `games.aitd1.profile.{NUM_OPCODES, CORE_SLOTS, DEAD_OPCODES}` (Task 10).
- Produces: `life.core_table(size, core_slots, dead_slots)` and the `life._CORE` semantic-handler dict; `life.NUM_OPCODES` and the zero-arg `core_table()` are gone.

- [ ] **Step 1: Write the failing absence pin**

Append to `tests/test_game_profile.py`:

```python
def test_engine_life_owns_no_aitd1_table_facts():
    # The VM-control numbering is the game's macro table (profile.core_slots);
    # engine/life.py keeps only the semantic handlers. NUM_OPCODES is deleted,
    # not moved: runtime bounds come from len(profile.opcode_table).
    from PyAitD.engine.script import life
    assert not hasattr(life, "NUM_OPCODES")
```

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_game_profile.py -q -k no_aitd1_table_facts`
Expected: FAIL (`assert not hasattr(life, "NUM_OPCODES")` — it still exists).

- [ ] **Step 2: Replace `NUM_OPCODES`/`core_table()` in `life.py`**

Delete `NUM_OPCODES = 87` and the old `core_table()` (with its comment
block). In their place:

```python
# The semantic VM-control handlers, keyed by name. FITD shares these
# enumLifeMacro semantics across games while each game's macro table maps
# them onto its own bytecode slots (AITD1.cpp:30-119, AITD2.cpp:48-171) —
# the numbering is the profile's core_slots, not this module's.
_CORE = {
    "IF_EGAL": _make_if(lambda a, b: a == b),
    "IF_DIFFERENT": _make_if(lambda a, b: a != b),
    "IF_SUP_EGAL": _make_if(lambda a, b: a >= b),
    "IF_SUP": _make_if(lambda a, b: a > b),
    "IF_INF_EGAL": _make_if(lambda a, b: a <= b),
    "IF_INF": _make_if(lambda a, b: a < b),
    "GOTO": _op_goto,
    "RETURN": _op_end,
    "END": _op_end,
    "VAR": _op_var,
    "INC": _op_inc,
    "DEC": _op_dec,
    "ADD": _op_add,
    "SUB": _op_sub,
    "LIFE_MODE": _op_life_mode,
    "SWITCH": _op_switch,
    "CASE": _op_case,
    "START_CHRONO": _op_start_chrono,
    "MULTI_CASE": _op_multi_case,
}


def core_table(size, core_slots, dead_slots):
    # size and dead_slots are the game's macro-table facts. Slots left
    # _op_not_implemented are for the game profile to fill or reject.
    table = [_op_not_implemented(i) for i in range(size)]
    for name, slot in core_slots.items():
        table[slot] = _CORE[name]
    for slot in dead_slots:
        table[slot] = _op_dead
    return table
```

- [ ] **Step 3: Update the two `core_table()` callers**

`PyAitD/games/aitd1/profile.py` `_opcode_table()`:

```python
    table = life.core_table(NUM_OPCODES, CORE_SLOTS, DEAD_OPCODES)
```

`tests/test_life_vm.py` (around line 214):

```python
    from PyAitD.engine.script import life
    from PyAitD.games.aitd1.profile import CORE_SLOTS, DEAD_OPCODES, NUM_OPCODES
    table = life.core_table(NUM_OPCODES, CORE_SLOTS, DEAD_OPCODES)
```

(Importing the constants from the profile module is allowed — the
test-groups pin forbids only `from PyAitD.games.aitd1.profile import AITD1`
outside `test_game_profile.py`.)

- [ ] **Step 4: Run the pin and the gate**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_game_profile.py tests/test_life_vm.py -q`
Expected: PASS. Note the existing handler-identity pin (`opcode_table[41] is
ops.op_game_over`, dead slots `{27, 57, 61, 69}`) now proves the new
builder produces the identical table.

Run: `make test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add PyAitD/engine/script/life.py PyAitD/games/aitd1/profile.py tests/test_life_vm.py tests/test_game_profile.py
git commit -m "refactor: build the LIFE core table from profile.core_slots"
```

### Task 14: Rewire the player-control indices (interaction + held_push)

**Files:**
- Modify: `PyAitD/engine/script/interaction/combat.py` (`combat_action_for`; delete `COMBAT_ACTIONS`, `PLAYER_STAND_ANIM`, `PLAYER_PUSH_ANIM`)
- Modify: `PyAitD/engine/script/interaction/track_mode.py` (`sync_player_track_mode`; delete `PLAYER_TRACK_MODES`)
- Modify: `PyAitD/engine/script/interaction/contacts.py` (`resolve_actor_contacts`)
- Modify: `PyAitD/engine/script/interaction/nav_intent.py` (`cancel_nav_intent`; drop its `PLAYER_STAND_ANIM` import)
- Modify: `PyAitD/engine/script/playworld/held_push.py` (`_refresh_held_target`; drop its `PLAYER_PUSH_ANIM` import)
- Modify: `PyAitD/engine/script/interaction/__init__.py` (drop the four constants)
- Test: `tests/test_game_profile.py`, `tests/test_interaction.py`, `tests/test_mouse_only.py`, `tests/test_playworld.py`

**Interfaces:**
- Consumes: `profile.combat_action_text_ids`, `.player_stand_anim`, `.player_push_anim`, `.player_track_modes` (Task 10).
- Produces: the four engine constants deleted; every use site reads `game.profile.*` (each use site's function already takes `game`).

- [ ] **Step 1: Write the failing absence pins**

Extend `test_aitd1_player_control_indices` in `tests/test_game_profile.py`:

```python
    from PyAitD.engine.script import interaction
    assert not hasattr(interaction, "COMBAT_ACTIONS")
    assert not hasattr(interaction, "PLAYER_STAND_ANIM")
    assert not hasattr(interaction, "PLAYER_PUSH_ANIM")
    assert not hasattr(interaction, "PLAYER_TRACK_MODES")
```

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_game_profile.py -q -k player_control`
Expected: FAIL (the constants still exist and are re-exported).

- [ ] **Step 2: Rewire the five use sites**

- `combat.py`, in `combat_action_for`: `if action in game.profile.combat_action_text_ids)` (was `COMBAT_ACTIONS`).
- `track_mode.py`, in `sync_player_track_mode`: `if hero.track_mode in game.profile.player_track_modes and hero.track_mode != wanted:` (was `PLAYER_TRACK_MODES`).
- `contacts.py`, in `resolve_actor_contacts`: `if actor.track_mode in game.profile.player_track_modes and game.active_modal is None:` (was `PLAYER_TRACK_MODES`).
- `nav_intent.py`, in `cancel_nav_intent`: both `PLAYER_STAND_ANIM` occurrences become `game.profile.player_stand_anim`; delete the `from PyAitD.engine.script.interaction.combat import PLAYER_STAND_ANIM` line.
- `held_push.py`, in `_refresh_held_target`: `init_anim(hero, game.profile.player_push_anim, 1, -1)` and `if hero.anim == game.profile.player_push_anim and pending == (254, 1, -1):`; delete the `PLAYER_PUSH_ANIM` import.

- [ ] **Step 3: Delete the constants and their re-exports**

Delete `COMBAT_ACTIONS`, `PLAYER_STAND_ANIM`, `PLAYER_PUSH_ANIM` from
`combat.py` and `PLAYER_TRACK_MODES` from `track_mode.py`. In
`interaction/__init__.py` remove the four names from the import lists.

- [ ] **Step 4: Update the three affected test files**

- `tests/test_interaction.py`: remove `COMBAT_ACTIONS` and
  `PLAYER_STAND_ANIM` from the import block; delete the
  `assert COMBAT_ACTIONS == frozenset({32})` line (its value-pin moved to
  `test_game_profile.py` in Task 10); the two `PLAYER_STAND_ANIM` uses
  become `profile.player_stand_anim` (add the `profile` fixture parameter
  to those test functions if absent).
- `tests/test_mouse_only.py`: remove `COMBAT_ACTIONS` and
  `PLAYER_PUSH_ANIM` from the import block;
  `assert armed == set(COMBAT_ACTIONS) == {32}` becomes
  `assert armed == set(profile.combat_action_text_ids) == {32}`;
  the two `hero.anim == PLAYER_PUSH_ANIM` asserts become
  `hero.anim == profile.player_push_anim`.
- `tests/test_playworld.py`: remove the
  `from PyAitD.engine.script.interaction import PLAYER_PUSH_ANIM` line; the
  three uses become `profile.player_push_anim` (add the `profile` fixture
  parameter where absent).

- [ ] **Step 5: Run the affected tests**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_game_profile.py tests/test_interaction.py tests/test_mouse_only.py tests/test_playworld.py -q`
Expected: PASS.

- [ ] **Step 6: Run the gate and commit**

Run: `make test`
Expected: PASS.

```bash
git add PyAitD tests
git commit -m "refactor: read the player-control indices from GameProfile"
```

### Task 15: Rewire `parse_objets` (world-object `mark` layout)

**Files:**
- Modify: `PyAitD/engine/data/formats.py:338-378` (`WorldObject`, `parse_objets`)
- Modify: `PyAitD/engine/script/game/state.py` (the `parse_objets` call in `Game.__init__`, pre-split `game.py:117`)
- Modify: `PyAitD/engine/script/save.py:375`
- Test: `tests/test_world_data.py`, `tests/test_prove_m3a.py`

**Interfaces:**
- Consumes: `profile.world_object_has_mark` (Task 10).
- Produces: `parse_objets(raw, *, has_mark)`; `WorldObject.mark: int = 0` (final field).

- [ ] **Step 1: Write the failing pin**

In `tests/test_world_data.py`, extend the `parse_objets` test with a mark
assertion:

```python
    assert all(obj.mark == 0 for obj in objs)  # AITD1 records carry no mark
```

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_world_data.py -q`
Expected: FAIL (`AttributeError: 'WorldObject' object has no attribute 'mark'`).

- [ ] **Step 2: Parameterize the parser**

In `PyAitD/engine/data/formats.py`, add `mark: int = 0` as the final field of
`WorldObject` and replace `parse_objets`:

```python
def parse_objets(raw, *, has_mark):
    # FITD LoadWorld (main.cpp:1005): u16 count + fixed s16 records, flags |= 0x20;
    # AITD2+ appends a trailing mark s16 per record (main.cpp:1117-1121).
    count = _u16(raw, 0)
    p = 2
    out = []
    fmt, size = ("<27h", 54) if has_mark else ("<26h", 52)
    for _ in range(count):
        values = list(struct.unpack_from(fmt, raw, p))
        p += size
        values[2] |= 0x20
        out.append(WorldObject(*values))
    return out
```

- [ ] **Step 3: Update every caller**

- `Game.__init__` (`state.py`): `self.world_objects =
  parse_objets((data_dir / "OBJETS.ITD").read_bytes(), has_mark=profile.world_object_has_mark)`
  (use the `profile` argument the constructor already receives).
- `PyAitD/engine/script/save.py`: `read_slot` already receives `profile`
  (line 115). Thread it through: line 181 becomes
  `_validate_world_objects(payload["world_objects"], data_dir, profile.world_object_has_mark)`;
  `_validate_world_objects(world_objects, data_dir)` (line 374) gains a
  third parameter `has_mark`; line 375 becomes
  `expected = len(parse_objets((pathlib.Path(data_dir) / "OBJETS.ITD").read_bytes(), has_mark=has_mark))`.
- `tests/test_world_data.py`: `parse_objets(raw, has_mark=False)`.
- `tests/test_prove_m3a.py:34`: `parse_objets((d / "OBJETS.ITD").read_bytes(), has_mark=False)`.

- [ ] **Step 4: Run the pin and the gate**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/pytest tests/test_world_data.py tests/test_prove_m3a.py -q`
Expected: PASS.

Run: `make test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add PyAitD tests
git commit -m "refactor: parameterize the world-object mark layout in parse_objets"
```

### Task 16: Seam-status docstring + leftover sweep

**Files:**
- Modify: `PyAitD/games/base.py:1-8` (module docstring)

**Interfaces:**
- Consumes: Tasks 10-15.
- Produces: the closed-seam statement; proof that no AITD1 literal remains in `engine/`.

- [ ] **Step 1: Rewrite the `games/base.py` docstring**

Replace the module docstring with:

```python
"""GameProfile: the per-game constants the engine reads at runtime.

FITD branches on g_gameId in boot (main.cpp), opcode semantics (life.cpp),
getCVarsIdx, and a few format variants. Every seam once hard-coded in
engine/ is now a field here: archive naming and overlay strategy
(floor_archive_name/camera_archive_name/mask_factory), the cadre bank,
VM-control opcode numbering (core_slots; opcode_table itself was already a
field), the player-control indices, the record layouts, and the FITD
gameTypeEnum ordinal (generation). A second game is a new profile instance
plus a PROFILES entry — no engine edits."""
```

- [ ] **Step 2: Sweep for leftovers**

```bash
grep -rn 'f"ETAGE\|f"CAMERA' PyAitD/engine
grep -rn "NUM_OPCODES" PyAitD/engine
grep -rn "COMBAT_ACTIONS\|PLAYER_STAND_ANIM\|PLAYER_PUSH_ANIM\|PLAYER_TRACK_MODES" PyAitD/engine
grep -rn "0x0C" PyAitD/engine
```

Expected: all empty (the `0x14` camera-header offset in `formats.py` stays —
it is not a per-game layout).

- [ ] **Step 3: Run the full gate plus journeys**

Run: `make test && make test-journey`
Expected: PASS — goldens byte-identical is the milestone's proof of zero
behavior change.

- [ ] **Step 4: Commit**

```bash
git add PyAitD/games/base.py
git commit -m "docs: record the closed seams in the GameProfile docstring"
```

---

## S4 — Docs (Tasks 17-19)

`CONTEXT.md`, `AGENTS.md`, and the proof docs are living documents; the
specs/plans under `docs/superpowers/` are dated records and stay untouched.
Note: between S1 and these tasks the file-path citations in `CONTEXT.md`,
`AGENTS.md`, and proof docs are stale — that is accepted by design (the M4a2
addendum precedent), and these three tasks are where they catch up.

### Task 17: Rewrite the engine section of `CONTEXT.md`

**Files:**
- Modify: `CONTEXT.md` (the engine module table/section)

**Interfaces:**
- Consumes: S1-S3 final layout.
- Produces: the living architecture map naming the five domains.

- [ ] **Step 1: Replace the engine section**

In `CONTEXT.md`, replace the engine module table (the rows citing
`engine/pak.py` … `engine/navigate.py`) with a five-domain section using
this content (keeping the file's existing table style and surrounding
sections untouched):

```markdown
| Domain | Modules |
|---|---|
| `engine/data/` | `pak.py` PAK/HQR archives; `explode.py` EXPLODE decompression; `formats.py` pure parsers (bodies, anims, cameras, cover zones, world-object/VARS/DEFINES records — record stride/mark from profile); `floor.py` ETAGE floors (rooms, cameras, masks — archive naming and mask strategy from profile); `assets.py` parse-once registries (bodies, anims, LISTLIFE, LISTTRAK, cadre bank from profile, `SCREEN_PIXELS`); `text.py` system/book text parsers; `mask.py` + `mask_geometry.py` mask rasterization and screen-space polygons |
| `engine/space/` | `cos_table.py` + `world.py` fixed-point rotations, camera transform/projection; `realvalue.py` rotation/speed interpolation, chronos, distances |
| `engine/actor/` | `actors.py` actor fields + GereAnim movement/collision; `anim.py` AnimPlayer; `anim_action.py` combat action runner; `tracks.py` track processor; `skel.py` skinning/projection (integer path, authoritative) |
| `engine/script/` | `game/` (`state.py` Game/Actor/FloorStart, `zv.py` ZV geometry, `objects.py` object-slot lifecycle, `boot.py` boot/transitions); `life.py` VM core (dispatch reads `profile.opcode_table`, core table built from `profile.core_slots`); `eval_var.py` evalVar; `interaction/` (`inventory.py`, `life_cont.py`, `combat.py`, `contacts.py`, `nav_intent.py`, `track_mode.py`); `effects.py` typed effects; `playworld/` (`tick.py`, `input.py`, `held_push.py`, `passes.py`); `save.py` versioned snapshots |
| `engine/nav/` | `navmesh.py` walkable grid + A*; `picking.py` screen->world; `navigate.py` pointer follower |
```

Also update the `engine/life.py` row's old `core_table()` description if it
appears elsewhere in the file, and the milestone table: add
`| Engine domain subpackages | data/space/actor/script/nav + 12 GameProfile seam fields | done — docs/superpowers/specs/2026-08-31-engine-domain-subpackages-design.md |`.

- [ ] **Step 2: Commit**

```bash
git add CONTEXT.md
git commit -m "docs: map the engine domains in CONTEXT.md"
```

### Task 18: Update `AGENTS.md` and add proof-doc addenda

**Files:**
- Modify: `AGENTS.md` (package table engine row, "Where new code goes", "Growing the engine" subpackage bullet, the known-seams bullet)
- Modify: any `docs/*.md` proof doc citing moved engine paths (Step 2's grep)

**Interfaces:**
- Consumes: S1-S3 final layout.
- Produces: the repo rules naming domains and the closed seams.

- [ ] **Step 1: Update the four AGENTS.md blocks**

a. Package layout table, engine row — replace the `Owns` cell with:

```
The simulation, ported from FITD with `file:line` citations, in five domain subpackages: `data/` (formats, PAK/floor data, masks), `space/` (fixed-point math), `actor/` (actors, animation, tracks, skel), `script/` (`Game` state, LIFE VM, interaction, `playworld` tick, `save.py`), `nav/` (navmesh, picking, pointer steering). Game-neutral: reads per-game facts from `game.profile`.
```

b. "Where new code goes", first bullet — append:

```
Pick the domain that owns the knowledge: data parsing → `engine/data/`, shared math → `engine/space/`, actor/animation behavior → `engine/actor/`, game state/scripting/tick → `engine/script/`, pointer navigation → `engine/nav/`. `data` and `space` are pinned leafward in `tests/test_layering.py`.
```

c. "Growing the engine", subpackage bullet — replace the
`engine/game/{state,boot,objects}.py` example with:

```
A module that outgrows one responsibility becomes a subpackage inside its domain: `engine/script/game/{state,zv,objects,boot}.py` is the landed example, with the public names re-exported from `engine/script/game/__init__.py` so every importer and test keeps `from PyAitD.engine.script.game import init_game`. Move with `git mv`; the layering scan covers subpackages automatically. Split by responsibility, not by size.
```

d. The known-seams bullet — replace the whole bullet with:

```
Seams the engine once hard-coded to AITD1 are now GameProfile fields (docs/superpowers/specs/2026-08-31-engine-domain-subpackages-design.md): archive naming (`floor_archive_name`/`camera_archive_name`), overlay strategy (`mask_factory`), cadre bank, VM-control opcode numbering (`core_slots`), player-control indices, record layouts (`viewed_room_record_size`, `world_object_has_mark`), and the FITD gameTypeEnum ordinal (`generation`). A second game is a new profile instance plus a `PROFILES` entry; if the engine needs a branch to support it, the branch belongs in a profile field (data or callable), documented in `games/base.py`'s docstring.
```

- [ ] **Step 2: Add translation addenda to living proof docs**

```bash
grep -rln "engine/\(game\|interaction\|playworld\|life\|formats\|floor\|assets\|pak\|explode\|text\|mask\|mask_geometry\|cos_table\|world\|realvalue\|actors\|anim\|anim_action\|tracks\|skel\|navmesh\|picking\|navigate\|effects\|eval_var\|save\)\.py" docs/*.md
```

For each file listed (proof docs only — skip `docs/superpowers/**`), add at
the top, directly under the title:

```markdown
> Addendum 2026-08-31: engine modules moved into domain subpackages
> (`engine/game.py` -> `engine/script/game/`, `engine/formats.py` ->
> `engine/data/formats.py`, etc. — full map in
> docs/superpowers/specs/2026-08-31-engine-domain-subpackages-design.md).
```

- [ ] **Step 3: Run the gate and commit**

Run: `make test`
Expected: PASS (docs-only, but the meta group reads repo files).

```bash
git add AGENTS.md docs
git commit -m "docs: update AGENTS.md for the domain layout; add proof-doc translation addenda"
```

### Task 19: Final verification

- [ ] **Step 1: Full gate**

Run: `make test && make test-journey`
Expected: PASS.

- [ ] **Step 2: Milestone invariants spot-check**

```bash
ls PyAitD/engine
grep -c "SPDX-License-Identifier" PyAitD/engine/*/__init__.py PyAitD/engine/*/*/__init__.py
```

Expected: `ls` shows only `__init__.py`, `actor`, `data`, `nav`, `script`,
`space`; every `__init__.py` reports the SPDX line.

---

## Plan self-review record

- **Spec coverage:** S1 moves (Tasks 1-5) + layering pins/purity paths
  (Task 6, string rows rewritten by the Task 1 script) cover spec
  "Target layout" and "Package rules". S2 (Tasks 7-9) covers "Splits". S3
  (Tasks 10-16) covers "GameProfile: 13 new fields" — reduced to 12 with the
  documented `actor_has_hard_mat` deviation — and the three non-fields
  (`NUM_OPCODES` deleted in Task 13; `SCREEN_PIXELS` in Task 12; dead slots
  unchanged via `DEAD_OPCODES` at build time). S4 (Tasks 17-18) covers
  "Sequencing" step 4. Task 19 covers the invariants.
- **Type consistency:** profile field names match across Tasks 10-15;
  `core_table(size, core_slots, dead_slots)` signature identical in
  definition (Task 13 Step 2) and both callers (Task 13 Step 3);
  `parse_cameras(raw, viewed_room_record_size)` and
  `parse_cover_zones(camera_raw, camera_off, viewed_idx, viewed_room_record_size)`
  identical in definition and all seven call sites;
  `parse_objets(raw, *, has_mark)` identical in definition and all four
  call sites; `Floor.viewed_room_record_size` defined (Task 11 Step 1) and
  read by navmesh/playworld-passes/texture_export (Task 11 Step 3).
