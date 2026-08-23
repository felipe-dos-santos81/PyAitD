# M3c combat proof

Automated: `make prove-combat`.

Manual: run `make run-combat`; using mouse-only input, confirm obj222 approaches,
attacks, and can kill the hero; wait for the Game Over overlay; click anywhere
with the left button; confirm the same floor-5 venue restarts fresh. Then exercise
one melee item, one firearm, and one thrown item. Record date, hero, observed
weapon object IDs, and pass/fail here.

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
| death LIFE 39 selected | — | tick 2056 (relocated: 1982) |

The "20 -> 10 on a force-10 hit" checkpoint is the same arithmetic seen from the
other side: the hero script subtracts the published `hit_force`, and the real
venue enemy publishes force 1, so the real fight is 20 hits rather than 2.

## Open gap: the real death sequence does not reach GAME_OVER

`tests/test_combat_journey.py::test_real_enemy_damage_reaches_game_over_and_fresh_restart`
is a strict `xfail` recording exactly where the real script stops:

1. `LIFE 39` (death) hands over to `LIFE 555`, which runs a real
   `LM_STAGE(6, 6, -5000, -4000, 11500)` — the death sequence lives on floor 6.
   The next `play_tick` then runs its anim pass with the previous floor's actors
   still in the table and indexes floor 6's 7 rooms with floor-5 room numbers
   (`IndexError`). FITD survives this because `GenereActiveList` only runs at the
   end of the *following* `mainLoop` iteration (mainLoop.cpp:196-199, 249)
   and C++ tolerates the out-of-range read.
2. Past that, the sequence reaches `LIFE 554`, which runs `LM_PICTURE` (resource
   12, 240 units) immediately followed by `LM_GAME_OVER`. The port suspends the
   LIFE frame on the picture, so `LM_GAME_OVER` executes inside the continuation
   `resume_life` runs when the modal is dismissed — outside `play_tick`. Nothing
   consumes that `flag_game_over`: the next tick restarts `LIFE 554` from pc 0 and
   suspends on the picture again, forever.

With both handled (spawn the new floor's actors on the floor swap; hand a pending
`flag_game_over` to `_handoff_game_over` before the next tick's passes) the real
journey reaches `GameOver(delay_units=120)` at tick 4034, measured with the fixes
applied by monkeypatch only. Neither fix is in this task's file scope, so the
journey stays `xfail` until they land.

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
