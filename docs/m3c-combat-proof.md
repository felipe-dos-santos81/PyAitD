# M3c combat proof

Automated: `make prove-combat`.

Manual: run `make run-combat`; using mouse-only input, confirm obj222 approaches,
attacks, and can kill the hero; the death sequence plays (floor 6 + death
picture); wait for the Game Over overlay; click anywhere with the left button;
confirm a fresh session restarts. Then exercise one melee item, one firearm, and
one thrown item. Record date, hero, observed weapon object IDs, and pass/fail
here. Note: until the restart-boundary ruling below, the restart lands in the
death stage rather than the floor-5 venue.

| Date | Hero | Weapon object IDs | Result |
|---|---|---|---|
| | | | |

## Observed real-data values (floor-5 venue, `enter_combat_venue`)

| Value | Expected | Observed |
|---|---|---|
| hero body / anim / frame | 12 / 4 / — | 12 / 4 / 0 |
| target object / body | 222 / 234 | 222 / 234 |
| thrown object / body | 13 / 9 | 13 / 9 |
| hero LIFE on taking a hit | 549 -> 553 -> 549 | 549 -> 553 -> 549 |
| script var 21 (health) at boot | 20 | 20 |
| var 21 per landed hit | -force | -1 (obj222's real `LM_HIT` carries force 1) |
| var 21 after the last hit | 0 | 0 |
| transient var 24 | 0 -> 1 | 0 -> 1 |
| hero LIFE at var 21 == 0 | 39 | 39 |
| first hit, enemy left to itself | — | tick 102 |
| first hit, enemy relocated onto the hero | — | tick 23 |
| death LIFE 39 selected | — | tick 2056 (relocated: 1983) |
| `GameOver(120)` opened | — | play tick 3958 (relocated run) |

The "20 -> 10 on a force-10 hit" checkpoint is the same arithmetic seen from the
other side: the hero script subtracts the published `hit_force`, and the real
venue enemy publishes force 1, so the real fight is 20 hits rather than 2.

## Resolved: carrying the real death script into GAME_OVER

The real sequence is `LIFE 39` (death) -> `LIFE 555` (`LM_STAGE(6, 6, -5000,
-4000, 11500)` -- the death cinematic lives on floor 6) -> `LIFE 558` -> `LIFE
554` (`LM_PICTURE(12, 240, 6)` immediately followed by `LM_GAME_OVER`). Two port
gaps stopped it; both are fixed in `playworld.py`.

**Gap A — the floor swap left the previous floor's actors in the table.** The
next tick's anim pass indexed floor 6's 7 rooms with floor-5 room numbers
(`IndexError` at `actors.py:203`). FITD survives the same stale pass: mainLoop
consumes `FlagChangeSalle` in the swap iteration and `continue`s past
`GenereActiveList` (mainLoop.cpp:189-199), so the regeneration only happens at
the end of the *following* iteration (mainLoop.cpp:249) and C++ tolerates the
out-of-range `roomDataTable` read. The port now consumes the room change in the
same tick, exactly as mainLoop does, then raises its existing
`flag_genere_aff_list` request and lets the one `_genere_active_list` gate
regenerate before any pass indexes the new floor. No second spawn path: the gate
is the same one the end of the tick uses.

**Gap B — a `flag_game_over` raised outside the LIFE pass was never consumed.**
The port suspends the LIFE frame on `LM_PICTURE`, so `LM_GAME_OVER` runs in the
continuation `interaction.resume_life` executes when the modal closes — after
the raising tick's LIFE loop finished. FITD never sees this: its `LM_PICTURE`
blocks inside `processLife`, so the flag lands in the same pass mainLoop.cpp:185
checks. Without the fix the next tick restarted `LIFE 554` from pc 0 and
suspended on the picture again: an endless death-picture loop with
`flag_game_over` set. `play_tick` now consumes a pending flag through the
existing `_handoff_game_over` before any pass re-runs that LIFE. Task 9's
contract is untouched: the in-pass check still runs after the complete LIFE
actor loop, still precedes floor/room/camera/spawn handling, still returns
`False`.

Measured after both fixes, from the real venue with no synthetic writes: death
LIFE 39 at play tick 1983, floor swap at 2400, `GameOver(delay_units=120)` at
**play tick 3958**.

### Revert-red for each fix

| Reverted | Observed |
|---|---|
| gap A (same-tick room change + `_genere_active_list` on the swap) | `IndexError: list index out of range` (`actors.py:203`) in `test_real_enemy_damage_reaches_game_over_and_fresh_restart` |
| gap B (pending `flag_game_over` handoff) | same test fails at `assert game.active_modal == GameOver(120)`, stuck on `ShowPicture(12, 240, 6)` |

## Open: the restart boundary after the death cinematic

`test_restart_after_death_returns_to_the_venue_that_was_played` is a strict
`xfail`. `LIFE 555`'s `LM_STAGE` is a hero transition like any other, so
`op_stage` records `FloorStart(6, 6, -5000, -4000, 11500, 0)` as the new restart
boundary; restarting after death therefore rebuilds the session in the death
stage rather than the floor-5 venue the player was fighting in. The spec's
restart design ("restart the current floor") predates the observation that the
hero's own death script relocates him, and there is more than one defensible
answer (ignore the recording once the hero is dead, snapshot the boundary at the
last player-controlled transition, or accept the cinematic stage as the restart
point). It needs a design ruling, not a guess.

## Revert-red audit

Each new test observed failing with the exact branch it protects reverted, then
restored (`make prove-combat` green again afterwards).

| Reverted branch | Observed failing test |
|---|---|
| `anim_action._publish_hit`: `attacker.hit = victim_idx` | `test_obj222_real_script_hits_and_hero_consumes_same_tick` |
| `life_ops.op_hit`: `vm.actor.hit_force = force` | `test_real_enemy_damage_empties_health_and_selects_the_death_life` |
| `anim_action.gere_frappe`: `WAIT_FRAPPE_ANIM -> WAIT_FRAPPE_FRAME` | `test_player_melee_executes_opcode_and_runner` |
| `anim_action._gere_fire`: `DO_TIR`'s `_publish_hit` | `test_player_fire_executes_opcode_and_runner` |
| `anim_action._launch_throw`: `thrown.anim_action_type = THROW_OBJECT` | `test_player_throw_executes_setup_launch_and_flight` |
| `life_ops.op_stage`: `game.floor_start = FloorStart(...)` | `test_natural_lm_stage_records_a_reenterable_floor_start` |

## Natural `LM_STAGE` entry camera

The spec's assumption holds: a natural floor change enters at camera slot 0.
`LoadEtage` sets `NumCamera = -1` (floor.cpp:39), so `ChangeSalle` finds no camera
continuity, and its `int newNumCamera = 0` (room.cpp:112) is what reaches
`NewNumCamera` (room.cpp:193). `op_stage` and the spec are unchanged.

The port's *settled* camera differs: `change_salle` does not port that
`NewNumCamera` assignment, so after a natural transition the ordinary
camera-switch pass decides the slot (slot 9 for the death sequence's floor 6 /
room 6 entry). Only `enter_floor_start` — the debug venue and restart path —
selects the recorded slot.
