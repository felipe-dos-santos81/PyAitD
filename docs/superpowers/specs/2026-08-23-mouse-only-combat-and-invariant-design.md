# Alone in the Dark 1 — Mouse-Only Combat and the Mouse-Only Invariant

Date: 2026-08-23
Status: Approved (design)
Reference: FITD (`/Users/felipe.dos.santos/code/theirs/FITD`, GPLv2) —
`inventory.cpp`, `mainLoop.cpp`, `main.cpp`, `animAction.cpp`
Builds on: M3b (interaction, inventory), M3c (combat runner, venue),
M3d (mouse-only point-and-click input)

## Goal

Make the game playable to completion with a mouse alone, and make that
property *enforced* rather than asserted. Two halves: give combat a mouse
route (click a hostile to attack it with what is in hand), and add a gate
that fails the build when a capability ships without one.

## The finding that motivates this

M3d's spec claims mouse-only play. The claim is false today, and nothing
detected it:

**`Command.OPEN_INVENTORY` is reachable only from `Return` or `i`
(`ui.py:54-55`). There is no mouse route into the inventory at all.**

Because the inventory is the only way to put an object in hand, and an
in-hand object's `found_life` is what issues every combat opcode, a
mouse-only player cannot equip, cannot throw, and cannot attack. The
existing `make prove-mouse` did not catch this: it proves navmesh coverage
per floor, not that a player can reach anything.

This is the motivating case for the invariant. A one-off fix to the
inventory would restore the claim and leave it just as unguarded.

## Scope

- **B — Mouse combat.** Clicking a hostile actor attacks it with the in-hand
  object, from where the hero stands.
- **C — The mouse-only invariant.** A capability registry plus a mouse-only
  playthrough, behind `make prove-mouse-only`.
- **The inventory HUD hotspot**, without which neither half is reachable.

## Non-goals

- Melee and firearm player routes. Measurement (below) found none, and
  inventing one would be fabrication. The design extends to cover them by
  adding one set member when the route is found.
- Menus, save/load, audio, and the ending (M4). The invariant constrains
  them when they are built; it does not build them.
- Any gesture beyond a single left click. M3d's constraint is preserved
  deliberately — see Decisions.
- Narrowing the action bit to the targeted actor. M3d deferred this; it
  stays deferred.

## Context discovered

Measured against the original game data, not inferred.

### Attacking is an inventory action, not a button

FITD sets the action bitfield from the inventory action menu
(`inventory.cpp:362`):

```c
action = 1 << (inventoryActionTable[selectedActions] - 23);
```

`0x2000` (`mainLoop.cpp:94`) is the generic action button — one bit among
many — and `0x800` (`main.cpp:3311`) marks a fresh pickup. The port already
implements the inventory-action route correctly at
`interaction.py:240`: `game.action = 1 << (action_text_id - 23)`, with
`inventory_actions` deriving the offered ids from the object's `found_flag`
bits.

Holding the generic action button therefore never arms a weapon: with it
held for 900 consecutive ticks at the venue, the hero armed nothing.

### What the real data supports

Driving all 71 objects that carry a `found_life` through
`choose_inventory_action`, at the combat venue:

| Inventory action id | Objects offering it | Arms |
|---|---|---|
| 32 | 63 | `WAIT_ANIM_THROW` (state 6) — **throw works** |
| 33 | 70 | nothing within 20 ticks |
| 23 | 30 | nothing |
| 25 | 19 | nothing |
| 24, 26, 27, 29, 30, 31 | 1–4 each | nothing |

**Throw is the only player arm reachable from the data.** No inventory
action armed melee (state 1) or fire (state 4).

Tracing 1200 ticks at the venue, the only actor to execute `LM_HIT` is
actor 12 (world object 222) running LIFE 467, 11 times. The hero ran only
LIFE 549 and 553, neither of which contains a combat opcode. Melee
therefore lives behind a mechanism that selects a different hero LIFE —
most likely AITD1's fight stance — which this port has not identified.

### Hostiles are cleanly identifiable

At the combat venue, of 48 live actors exactly **one** is `AF_ANIMATED` and
not the hero: actor 12, world object 222. It is also the only actor with
`track_mode == 2`. `AF_ANIMATED and live and not the hero` selects
creatures with no scenery false positives.

### Layout facts

`ModalLayout` (`ui.py:160-166`) already establishes hit rectangles in the
logical 320x200 frame. The message overlay occupies `y >= 184`
(`ui.py:261`). The top-left corner is free of both.

## Decisions (agreed with user)

1. **Click a hostile to attack it with what is in hand.** Not an aiming
   assist, not a HUD attack button.
2. **Attack from where the hero stands.** The click faces the target and
   triggers; it never walks. Predictable, and correct for the one arm that
   works (throw is ranged). Melee would simply miss at distance.
3. **The gate is both a registry and a playthrough.** The registry forces a
   deliberate decision per capability; the playthrough stops the registry
   becoming a comfortable fiction.
4. **The inventory opens from a persistent on-screen HUD hotspot.** Chosen
   over right-click because M3d's single-left-click contract is preserved
   rather than amended, and over an invisible edge band because an
   undiscoverable affordance is not a mouse route in any meaningful sense.
   It also gives M4's menus and save/load a home.

## Architecture

```
click ─► HUD hit-test (before world routing)
         │  hit  ─► open inventory modal
         │
         └─ miss ─► resolve_play_click ─► kind
                     │
                     ├─ "attack"  (hostile AND in-hand exposes a combat action)
                     │      └─► attack_in_hand(game, target_idx)
                     │             ├─ face target (_turn_toward)
                     │             └─ choose_inventory_action(game, in_hand, action_id)
                     │                   └─► found_life issues LM_THROW
                     │                         └─► gere_frappe publishes the hit
                     ├─ "target"  (unchanged M3d behaviour)
                     ├─ "walk"    (unchanged)
                     └─ "blocked"
```

### New seams

**`_is_attackable(game, actor_idx)`** — `__main__.py`, beside
`_is_interactable`. True when the actor is live, `AF_ANIMATED`, and not the
hero. **Deliberately separate from `_is_interactable`**, which keeps M3d's
"foundable, or a world object with a `found_life`" contract exactly as
specified. Widening that gate would have changed what a click means for
every existing object; this is additive.

**`COMBAT_ACTIONS`** — `interaction.py`. The set of inventory action ids
that arm a combat state. Ships as `{32}`, measured. **This is the extension
point for melee and firearm**: when their route is found, the id joins this
set and nothing else changes.

**`attack_in_hand(game, target_idx)`** — `interaction.py`. Faces the hero at
the target, then delegates to `choose_inventory_action`. It introduces no
second way to arm combat: the inventory route remains the only one, which
is the same one-implementation discipline that governs `skel.pose_vertices`,
`game.enter_floor_start`, and the single `gere_frappe` dispatcher.

The facing step reuses `tracks._turn_toward`, the shared "rotate toward a
target point" block every track mode already uses. It is currently private
to `tracks.py`, so the plan promotes it to a public name rather than
reaching across the module boundary for an underscore — the same rule that
keeps `anim_action.py` off `life_ops.py`'s private VM helpers. Writing a
second rotation is forbidden: the port has exactly one, and combat facing
must be the same turn the follower mode performs.

**`PlayLayout.INVENTORY`** — `ui.py`, `Rect(4, 4, 28, 20)`. Drawn by `ui.py`
(presentation only, no world mutation), hit-tested by `__main__.py` in the
event pump **before** `route_play_click`, so a HUD click is never also a
world click. Rendered only when the mode is PLAY, no modal is active, and
`status_screen_allowed` — the same condition that already gates
`Command.OPEN_INVENTORY`, so the button cannot advertise a click the router
would refuse.

### The cursor may not lie

`resolve_play_click` stays the single resolver behind both the cursor and
the click, so hover feedback cannot differ from what clicking does. The
`"attack"` kind therefore requires **both** conditions:

| Situation | Cursor | Click |
|---|---|---|
| Hostile, in-hand object exposes a combat action | attack | face, then arm |
| Hostile, nothing in hand | blocked | no-op |
| Hostile, in-hand object exposes no combat action | blocked | no-op |
| Non-hostile actor | target / walk, unchanged | unchanged |

Without the second condition, hovering a hostile while holding a lamp would
advertise an attack and `choose_inventory_action` would raise `ValueError`
into the event loop.

### The invariant (C)

**`PyAitD/mouse_contract.py`** — pygame-free. A table mapping every player
capability to the mouse gesture that reaches it, or to `KEYBOARD_ONLY` with
a stated reason. The four tank directions and `TOGGLE_INPUT_MODE` are
legitimately keyboard-only: mouse steering replaces them rather than
duplicating them.

**`tests/test_mouse_only.py`** — one integration test driving a real session
from synthetic mouse events only. No `Command` may be injected by hand. It
walks, opens the inventory from the HUD, selects an object, uses it, throws,
attacks a hostile, dies, and restarts. Any step needing a key fails it.

Both behind **`make prove-mouse-only`**, a new target following the repo's
one-proof-per-milestone pattern rather than overloading `prove-mouse`
(navmesh coverage, a different question).

## Invariants

- `interaction.py`, `mouse_contract.py`, `playworld.py`, `anim_action.py`,
  `life_ops.py`, and `effects.py` import no pygame, ModernGL, rendering, or
  event-pump modules.
- `ui.py` presents state only. Only `__main__.py` pumps events, replaces a
  `Game`, loads a `Floor`, and presents once per outer frame.
- `_is_interactable` and M3d's click priority are unchanged. The attack rule
  is additive.
- Combat is armed through `choose_inventory_action` and nowhere else.
- The cursor and the click derive from one `resolve_play_click` call.
- No gesture beyond a single left click.
- Golden values are measured from real game data, never guessed.

## Error handling

- Clicking a hostile with nothing in hand, or with an object exposing no
  combat action, is a no-op; the cursor already showed blocked.
- `choose_inventory_action` keeps raising `ValueError` for an action the
  object does not expose. That path is unreachable from the click route by
  construction (the cursor condition), and the raise stays as the contract
  for direct callers.
- A HUD click while a modal is open routes to the modal, not the HUD; the
  hotspot is not drawn or hit-tested outside PLAY.

## Testing

- **Hostile rule**: at the venue, `_is_attackable` accepts actor 12 and
  rejects the other 47 live actors and the hero.
- **`COMBAT_ACTIONS` is measured**: a test derives which inventory actions
  arm a combat state from real data and asserts the set matches, so the
  constant cannot drift from the data it claims to describe.
- **`attack_in_hand` delegates**: the call into `choose_inventory_action` is
  captured and its arguments asserted; the hero's facing is asserted to
  change toward the target.
- **Real-data journey**: at the venue, equip a throwable, click obj222,
  assert the hero arms `THROW_OBJECT` and the thrown actor publishes
  `hit_by == hero`. Real opcode, real runner, no synthetic LIFE script.
- **Cursor honesty**: each row of the table above is a case; the
  non-weapon-in-hand row would fail if the second condition were dropped.
- **HUD**: a click inside `PlayLayout.INVENTORY` opens the inventory and does
  **not** produce a nav intent; a click one pixel outside does the opposite.
- **C1**: every capability is tagged; an untagged entry fails the test.
- **C2**: the mouse-only playthrough. **It fails on first write, at "open the
  inventory", and passes once the HUD lands** — that failure is the gate
  working, and the plan should expect it rather than treat it as a defect.
- **Regression**: the existing M3d suite is unchanged.
- Every new test is observed failing with its implementation hunk reverted
  before the task is committed.

## Assumptions

- Inventory action 32 is "throw" in AITD1's action table. The behaviour is
  measured (63 objects arm `WAIT_ANIM_THROW`); the *name* is inferred and is
  not relied on by any code.
- Objects offering action 33 (70 of them) do something non-combat; nothing
  in this design depends on what.
- `AF_ANIMATED and not hero` remains a good hostile proxy on floors other
  than 5. It is verified only at the venue, because the venue is the only
  supported non-attic start.

## Risks

- **Melee and firearm stay unreachable.** The milestone delivers mouse-only
  play for every capability that has a route, and throw is the only combat
  arm with one. Anyone reading "mouse-only combat" as "all three arms" will
  be disappointed; the spec says otherwise deliberately.
- **The registry is only as honest as its entries.** C2 is the mitigation,
  and it is the half that must not be dropped if the work is trimmed.
- **The HUD costs frame area.** 28x20 of a 320x200 frame, in the corner
  least used by the existing UI. If it proves intrusive, the placement is a
  constant, not a design change.
- **A hostile proxy verified on one floor.** If another floor has animated
  scenery, clicking it would attempt an attack and no-op. Low cost, and the
  cursor would show blocked rather than misleading the player.
