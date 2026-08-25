# Native Mouse Melee Design

**Status:** Approved by human retest on 2026-08-25.

## Goal

A single click on a visible enemy performs the equipped cavalry saber's native
melee attack. It must not select the inventory `Throw` action or release the
saber onto the floor.

## Evidence and correction

- ENGLISH.PAK text 32 is `Throw`; text 27 is `Fight`.
- The old mouse route treated action 32 as a generic combat action and called
  `choose_inventory_action(..., 32)` after an enemy click.
- FITD `mainLoop.cpp:87-101` instead maps held action input to `action = 0x2000`
  and executes the current in-hand object's LIFE.
- Against original data, object 38 `Use` equips hero body 44. Action `0x2000`
  plus forward input arms melee animation 41, frame 1, range 200, force 4.
- The action and forward inputs must remain asserted until the real animation
  reaches its strike frame. One tick is insufficient because the player's LIFE
  then queues the idle animation. A mouse click therefore needs an automatic,
  bounded input latch; the player must not hold or time a button.

## Design

`InputBuffer` owns the transient mouse attack latch because it already owns
keyboard action state, pointer provenance, focus reset, modal takeover reset,
and replacement-session reset. The simulation receives only ordinary FITD
fields (`local_joyd = 1`, `local_click = 1`, `action = 0x2000`) during fixed
ticks. No mouse or pygame state enters `Game`, `interaction.py`, or
`anim_action.py`.

An enemy click follows the existing resolver and `attack_in_hand` validation:
cancel navigation, stop, and face the target. On success, `route_play_click`
latches the actor slot in the supplied `InputBuffer`. `_apply_mouse_input`
publishes forward plus action on each tick. After the first published tick, the
latch ends when the hero returns to `anim_action_type == 0`, when the target or
in-hand object becomes invalid, on focus/modal/input-mode reset, or at a hard
100-tick safety budget.

Inventory `Throw` remains available only by explicitly choosing that row in
the inventory. Throw setup, flight, collision, and stopped floor placement are
unchanged.

## Boundaries and invariants

- No new dependency.
- `ui.py` mutates only `InputBuffer`; it never reads or mutates world actors.
- `playworld.py` remains pygame-free and is the only owner of fixed-tick input
  publication.
- `interaction.py` remains pygame/UI-free and keeps target validation/facing.
- One physical or touch-origin left-button down uses the same route.
- Mouse-up does not cancel an already accepted one-click attack.
- Focus loss, modal takeover, input-mode toggle, restart, and hero replacement
  clear the latch through existing `reset_input` seams.
- A clicked saber strike publishes `enemy.hit_by == hero_idx` and force 4;
  object 38 stays in inventory with no active world actor.
- Existing explicit throw tests remain valid and unchanged outside the mouse
  journey.

## Non-goals

- Redesigning keyboard combat or FITD animation-action states.
- Target pursuit, combo selection, automatic repeated attacks, damage rules,
  enemy LIFE reactions, audio, or new impact effects.
- Removing explicit inventory `Throw`.

## Acceptance

1. RED-first unit coverage proves an enemy click latches native combat instead
   of calling action 32.
2. A real-loop one-click journey equips object 38 with `Use`, clicks obj222,
   observes melee states, a hero-origin force-4 hit, and the saber still held.
3. Reset/focus coverage proves the transient latch cannot survive takeover.
4. `make prove-mouse-only`, the full suite, and `make prove` pass.
5. A human windowed retest observes a saber swing and visible hit outline with
   no saber floor drop.
