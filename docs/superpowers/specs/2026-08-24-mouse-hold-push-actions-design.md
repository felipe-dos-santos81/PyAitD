# AITD1 Mouse Hold-to-Push Actions Design

Date: 2026-08-24

Status: Approved design — awaiting implementation plan

Reference: FITD `mainLoop.cpp`, `anim.cpp`, `main.cpp`, and `life.cpp`

Builds on: M3e mouse-only combat and invariants; M4a1 shell, configuration, and mouse contract

## Goal

Make push interactions available to a one-button mouse user. When the pointer is over a push-capable world actor, such as the wooden wardrobe against the left wall in the opening room, the cursor must advertise the action instead of showing a red blocked X. Pressing and holding the left button makes the hero approach and engage the actor through the normal movement, collision, animation, and LIFE systems. Releasing the button cancels the entire held movement immediately, including while the hero is still approaching.

This is an input and navigation adapter. It must expose FITD's existing push behavior without directly moving scenery or manufacturing push state.

## Scope

This milestone adds:

- runtime classification of actors that can receive a held push action;
- a distinct push cursor and mouse capability contract;
- left-button hold state owned by the input layer;
- a two-phase held navigation intent: approach, then engage;
- immediate, idempotent cancellation on button release and other input-invalidating transitions;
- focused unit, headless, and real-data coverage for the opening-room wardrobe;
- mouse-only journey evidence for both protagonists.

The feature applies to body-bearing, collidable world actors whose runtime state indicates movable or active scripted furniture. It does not make arbitrary background pixels, decorative bodies, or inert scenery interactive.

## Non-goals

- Rewriting actor collision, push physics, LIFE bytecode, or animation processing.
- Directly changing a target actor's position, `AF_MOVABLE` flag, collision fields, or LIFE variables from the mouse adapter.
- Adding drag-to-steer, right-button actions, pointer-lock controls, or configurable push gestures.
- Turning ordinary click-to-walk, found-object, inventory, or combat actions into held actions.
- Expanding save/load work or other M4 milestones.
- Adding dependencies.

## Evidence and Constraints

### Why the wardrobe currently shows a red X

The play cursor currently recognizes only foundable actors or actors with a `found_life` entry as interactable. The opening-room wardrobe is world object 4 (zero-based `obj_index == 3`, body 2). In real data it is visible and collidable, has active LIFE, is not foundable, and has `found_life == -1`. It therefore falls through to the blocked cursor even though FITD can drive it through collision and LIFE.

The same opening stage contains inert body-bearing scenery with neither active LIFE nor `AF_MOVABLE`. The new classification must continue to reject that scenery. It may also recognize actors already carrying `AF_MOVABLE`; those are explicit push candidates.

### Existing engine behavior remains authoritative

The rewrite already resolves actor contacts and can transfer movement to actors carrying `AF_MOVABLE` when the destination is clear. FITD's corresponding authority remains:

- `mainLoop.cpp`: frame input snapshot and action signal;
- `anim.cpp`: animation movement and collision progression;
- `main.cpp`: object collision and collision response;
- `life.cpp`: LIFE execution that decides when scripted furniture changes behavior.

The mouse feature supplies sustained forward intent and target tracking. Collision, animation, and LIFE decide whether the object actually moves.

### Holding Action is not pushing

The global Action signal is not held during push navigation. A runtime probe showed that combining held Action with movement freezes the hero in this path, and FITD does not define pushing as a continuous generic Action command. Existing click interactions may still emit their one-shot arrival Action; the push route must bypass that dispatch.

## Interaction Contract

### Target eligibility

`interaction.py` owns a pygame-free predicate:

```text
is_hold_action_target(game, actor_idx) -> bool
```

An actor is eligible only when all of these are true:

- it exists and is not the hero;
- it has a live world-object identity (`index_in_world >= 0`);
- it has a visible body (`body_num != -1`);
- collision is enabled in its dynamic flags;
- it is not a foundable pickup;
- it is not selected by the higher-priority combat route; and
- it either carries `AF_MOVABLE` or has active LIFE (`life != -1`).

Active LIFE is intentionally a capability proxy for scripted collision furniture, not a claim that every such actor must move. The approach resolver must also be able to produce a valid adjacent destination. If it cannot, the cursor remains blocked. A target that accepts the gesture but cannot move must stop through the bounded stall policy without corrupting state.

The existing interaction resolver remains the only hover and mouse-down authority. Its priority stays deterministic:

1. active modal or inventory behavior;
2. combat target;
3. foundable or ordinary scripted interaction;
4. held push target;
5. walk destination;
6. blocked.

The new resolver result kind is `push`. It contains the latched world-object index and the approach destination needed to start navigation.

### Mouse capability contract

`mouse_contract.py` adds a play-mode capability for pushing a world actor. Its gesture is `left_hold`, its target is a push-capable scripted actor, and its visible affordance is the push cursor. This is a separate capability from one-shot object interaction so the contract describes the release semantics honestly.

No keyboard command is added. Keyboard play continues to use the existing movement, collision, and LIFE path.

## Input and Navigation State

### Input ownership

`ui.InputBuffer` gains a `pointer_held` boolean. The pygame event layer changes it only for the primary mouse button:

- left `MOUSEBUTTONDOWN`: set it true before resolving and starting a push;
- left `MOUSEBUTTONUP`: set it false and cancel any hold-required navigation intent;
- focus loss or `reset_input`: set it false.

`InputBuffer` remains UI input state and does not mutate game state. `__main__.py`, which owns the event pump and game/session replacement, coordinates the corresponding navigation cancellation.

### Held navigation intent

`effects.NavIntent` gains two explicit booleans:

- `requires_hold`: this intent is valid only while the primary button remains held;
- `engaged`: the hero has completed the approach and is now sustaining contact with the target.

The existing target world-object index is the stable identity. Actor slots are transient, so each simulation tick resolves the current actor from that world-object index before reading its position or eligibility.

The two booleans extend the existing intent without introducing a second navigation state machine. Non-held click-to-walk and click-to-interact intents keep their current behavior.

## Data Flow

```text
pointer hover
    -> resolve_play_click
    -> push eligibility + adjacent approach cell
    -> amber push cursor

left button down
    -> InputBuffer.pointer_held = true
    -> latch target world-object index
    -> NavIntent(requires_hold=true, engaged=false)

simulation ticks while held
    -> resolve target's live actor and position
    -> approach through the existing path follower
    -> on adjacent arrival, set engaged=true
    -> sustain ordinary forward movement/contact toward the live target
    -> collision + animation + LIFE remain authoritative

left button up or invalidation
    -> InputBuffer.pointer_held = false
    -> clear held NavIntent, decision, arrival, movement, click, and action state
    -> hero stops within the same input/simulation tick
```

### Approach phase

On left-button down over a `push` result, `__main__.py` latches the world-object index and creates a hold-required intent. The existing path follower drives the hero to a valid adjacent position. The target is re-resolved every tick, and the destination is refreshed if the target moves before engagement.

Releasing during approach cancels the entire route immediately. The hero does not continue to the wardrobe, complete the old path, or emit an arrival Action pulse.

### Engage phase

At adjacent arrival, the intent becomes engaged instead of completing. The hero faces the target and the follower continuously supplies the normal forward movement needed to maintain contact. It does not set the global Action signal.

If collision and LIFE move the target, the intent follows its current position and continues while the button remains held. If the target is blocked, the normal collision result wins; the adapter must never force movement through geometry.

If the real-data wardrobe remains at `object_type == 0` after held collision, the implementation must correct the mouse follower's player animation/input projection so it produces the same LIFE-visible animation state as FITD forward pushing. The allowed production changes are limited to hero input, navigation, facing, or animation selection through existing engine contracts such as `init_anim`. Direct wardrobe flag, variable, collision, or position writes are forbidden.

### Release and cancellation

Cancellation is immediate and idempotent. Repeated cancellation calls produce the same cleared state. A held intent is cancelled when any of these occurs:

- the primary button is released anywhere on screen;
- the window loses focus or input is reset;
- a modal session takes control;
- the game is replaced or the current floor or room changes;
- the world object despawns, loses its live actor, or stops satisfying eligibility;
- pathfinding abandons the route or the existing bounded stall threshold is reached.

Cancellation clears the navigation intent, cached click decision, pending arrival target, local movement, local click, and Action signal. It does not cancel ordinary non-held click-to-walk intents on mouse-up.

If a held route stalls while the button is still down, it ends. The player must release and press again to retry; there is no hidden auto-restart loop.

## Cursor and Accessibility

The push cursor is a distinct amber, high-contrast primitive, visually separate from the red blocked X, walk cursor, target cursor, and attack cursor. An opposed-arrow or braced-motion shape communicates pushing without relying on text or color alone.

Before press, hover resolution determines the cursor. Once a push is latched, the active push cursor remains visible while the button is held even if the physical pointer drifts off the actor. This avoids requiring continuous pointer precision from a one-button or on-screen input user. The latched target, not the moving pointer, controls the operation.

The interaction requires one press-and-hold and one release. It does not require double-clicking, a chord, keyboard input, or pixel-perfect tracking after the initial press.

## Component Ownership

- `PyAitD/interaction.py`: target eligibility, resolver result, approach selection, and shared cancellation helpers; no pygame.
- `PyAitD/ui.py`: `InputBuffer.pointer_held`, reset behavior, and push cursor drawing; no world mutation.
- `PyAitD/mouse_contract.py`: declarative push capability and `left_hold` gesture.
- `PyAitD/effects.py`: the two held-intent fields and their neutral defaults; no pygame.
- `PyAitD/__main__.py`: primary-button down/up routing, event-pump ownership, session invalidation, and immediate game-side cancellation.
- `PyAitD/playworld.py`: defensive hold validation, approach-to-engage transition, live target retargeting, and sustained normal movement; no pygame or event access.

These changes preserve the existing layer boundary: gameplay modules do not read pygame events or render, UI code does not mutate world, actor, inventory, or LIFE state, and `__main__.py` remains the sole event-pump owner.

## Error Handling and Safety

All live target lookups are defensive. A missing actor, invalid world-object index, room mismatch, disabled collision body, or changed eligibility cancels the held intent rather than indexing stale state.

The adapter must not infer success merely because the hero reached the target. Success is observable movement through existing engine state. A target that cannot move remains collision-blocking and eventually reaches the existing stall/abandon path.

No cancellation path may leave `game.action`, `game.local_click`, or directional movement asserted. Focus loss is treated exactly like release so an inaccessible background window cannot keep moving the hero.

## Verification Strategy

### Unit and contract tests

Add deterministic tests proving:

- the opening-room object-4/body-2 shape resolves as `push` when represented with its real runtime flags;
- inert body-bearing scenery without active LIFE or `AF_MOVABLE` remains blocked;
- foundable, combat, ordinary interaction, walk, and blocked priorities are unchanged;
- a push resolver result requires a valid adjacent approach destination;
- the mouse capability advertises `left_hold` in play mode;
- the push cursor is distinct and can be rendered under SDL's dummy video driver;
- mouse-up cancels a held approach within one tick and does not cancel ordinary click-to-walk;
- focus loss, input reset, modal entry, despawn, room invalidation, and stall cancel safely;
- cancellation is idempotent and clears movement, click, Action, arrival, and intent state;
- engage retargets a moving world object by stable world-object identity;
- held pushing never asserts the global Action signal.

### Real-data regression tests

Using the `data_dir` fixture, add a focused headless journey for the wooden wardrobe in the opening room:

1. boot real AITD1 data to the playable opening state;
2. hover the wardrobe and observe the push decision rather than blocked;
3. press and hold from outside contact range;
4. verify the hero approaches through normal navigation;
5. release before arrival and verify all movement stops immediately;
6. start again, keep holding through contact, and verify the existing collision/LIFE path enables and moves the wardrobe;
7. verify the adapter never writes the wardrobe's movement flags or position directly;
8. repeat the successful journey with both protagonists.

The fixture continues to skip when original game data is absent. Any golden value pinned from real data must cite the corresponding FITD source line when its behavior is not self-evident.

### Regression gates

The implementation plan must finish with:

```bash
make prove-mouse-only
.venv/bin/pytest -q
make prove
```

Any rendering test must set `SDL_VIDEODRIVER=dummy`. Existing mouse-only combat, found-object, inventory, floor-navigation, configuration, and shell journeys must remain green.

## Acceptance Criteria

The feature is complete only when all of the following are true:

- Hovering the opening-room wardrobe displays the amber push cursor, not the red blocked X.
- Pressing and holding left mouse starts an approach and latches the wardrobe without requiring continued pointer precision.
- Releasing while approaching cancels the entire movement immediately.
- Holding through contact sustains normal forward collision behavior without holding global Action.
- The wardrobe moves only through existing collision, animation, and LIFE authority.
- A moving target is tracked by its stable world-object identity.
- Inert scenery remains blocked and ordinary mouse actions retain their current semantics.
- Focus loss and every invalidation path leave no stuck movement or action state.
- Both protagonists pass the real-data mouse-only wardrobe journey.
- The focused mouse proof, full pytest suite, and full real-data proof all pass.
