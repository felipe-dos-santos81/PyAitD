# M4a2 Persistence Proof

Date: 2026-08-30
Spec: `docs/superpowers/specs/2026-08-24-overall-mouse-accessibility-design.md`,
`docs/superpowers/specs/2026-08-22-aitd1-build-conclusion-design.md`
Plan: `docs/superpowers/plans/2026-08-24-m4a2-persistence-mouse-parity.md`
(the plan carries a 2026-08-30 addendum translating its pre-reorganization file
map to the engine/render/games/app split; this proof records the post-split
paths).

## Automated evidence

Run 2026-08-30 on macOS 26.6.2 (arm64) with the real game data
(`Alone in the Dark 1.app/Contents/Resources/game/INDARK`), branch
`feat/m4a2-persistence` (`cb34d88`..`3b6695c`).

- `make prove-persistence`: PASS — `345 passed in 13.23s`
  (`tests/test_save.py`, `tests/test_game_rng.py`,
  `tests/test_ui_reducers.py`, `tests/test_ui_mouse.py`,
  `tests/test_ui_render.py`, `tests/test_runtime_modes.py`,
  `tests/test_shell_journeys.py`, `tests/test_mouse_only.py`,
  `tests/test_main.py`, `tests/test_config.py`; run under
  `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`).
- `make prove-mouse-accessibility`: PASS — `434 passed, 1047 deselected in
  14.07s` (the persistence pages did not regress the one-button shell gate).
- `make test` (`.venv/bin/pytest -q`): PASS — `1479 passed, 1 skipped, 1
  xfailed in 44.14s`. The single xfail remains the M3c death-cinematic
  restart boundary that M4c owns.

## What the gate pins

Schema and identity (`tests/test_save.py`, `PyAitD/engine/save.py`):

- Root keys, schema 1, actor count 128, world-object count 292, 45 CVars,
  207 vars, inventory shape 2x30, five message slots — pinned from real data.
- `source_identity` hashes `OBJETS.ITD`, `VARS.ITD`, `DEFINES.ITD`,
  `LISTLIFE.PAK`, `LISTTRAK.PAK` and the selected hero's body/anim paks in
  order; a one-byte mutation of any input changes the digest.
- Bools never pass as ints; wrong-type, missing/extra-key, count/shape,
  unknown-schema and corrupt-RNG cases all fail with the JSON path of the
  offending value.

Restoration:

- `test_restore_round_trip_state` snapshots a mutated world, restores into a
  fresh `Game` through a JSON round trip, and the second snapshot is byte
  identical.
- `test_restored_game_ticks_and_draws_like_the_original` runs one identical
  `play_tick` on original and restored games and asserts equal snapshots and
  equal next RNG draws.
- `test_clean_process_restores_the_identical_world` spawns a fresh
  interpreter that reads the slot off disk and rebuilds the identical world
  and RNG stream.
- Restoration forces fresh-boot semantics (`flag_init_view=2`,
  `flag_genere_aff_list=1`, empty modal/continuation/effect queues, fresh
  `MeshCache`) and rejects a player entry whose actor has no animation.

Atomic slots (`write_slot`/`read_slot`):

- Darwin and Linux slot directories sit beside the settings file.
- Simulated `json.dump`, `fsync` and `os.replace` failures leave a prior
  valid slot byte-identical and no temp file behind.
- A missing slot is not an error; a malformed or identity-mismatched one is.

Loop policy (`tests/test_runtime_modes.py`, `tests/test_shell_journeys.py`):

- Manual save is refused while a LIFE continuation or platform effect is
  pending; the refusal surfaces as the dismissible runtime notice.
- Quick Save closes the menu and commits only after a stable end-of-PLAY-tick
  boundary — never before it.
- A load click reads and validates the slot, stages `pending_load`, and
  `_load_branch` replaces game/floor/session/input in one tuple, landing in
  PLAY with clean pointer/action state. Every failure path leaves the live
  game, settings, input, floor and modal untouched.
- `replacement_session` carries `save_directory` across hero/restart/load
  replacements and drops the persistence transients.

Mouse parity (`tests/test_mouse_only.py`,
`PyAitD/games/aitd1/mouse_contract.py`):

- Five new capabilities (`SAVE_MANUAL`, `LOAD_MANUAL`, `LOAD_QUICK`,
  `QUICK_SAVE`, `PERSISTENCE_BACK`) are single forgiving `left_click` routes
  in `SYSTEM_MENU`, so physical and touch origins reach every persistence
  decision identically. The derived-mode equality test pins them.
- An unavailable load slot renders dimmed and is a no-op that cannot fall
  through to Back.

## Windowed attestation

Pending. The one-button persistence pass (per hero: manual save, mutate, load;
quick save, mutate, load quick; exercise the missing/corrupt slot notice and
Dismiss; quit, relaunch, load) needs a human in front of a window and is
recorded here when it lands. The automated gates above are green in the
meantime.
