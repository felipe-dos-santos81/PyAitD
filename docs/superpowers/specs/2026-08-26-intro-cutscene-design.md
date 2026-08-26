# Opening story cutscene (floor 7 intro) — design

Date: 2026-08-26. Status: approved design. Part 3 of 3 (screen overrides →
startup menu → intro cutscene). Depends on the startup-menu boot flow.

## Goal

After the player confirms a character, play the script-driven opening the
way `startAITD1` does (`AITD1.cpp:352-361`): `startGame(7, 1, 0)` — the car
arriving at Derceto, the letter, Carnby/Emily walking through floors 3, 2
and 1 — then `startGame(0, 0, 1)`, the attic. Today `_hero_branch` boots the
attic directly.

## What the spike established (2026-08-26, real data, headless)

- FITD's `startGame` (`main.cpp:4134`) is `LoadWorld; initVars; LoadEtage(f);
  NumCamera=-1; ChangeSalle(r); NewNumCamera=0; FlagInitView=2; InitView;
  PlayWorld(allowSystemMenu)`. `initVars` (`main.cpp:1235-1236`) resets
  `currentCameraTargetActor` and `currentWorldTarget` to −1. The hero object
  (world 1) stays on stage 0; it is **not** relocated to floor 7.
  `enter_floor_start` is therefore the wrong primitive: it relocates the
  camera-target actor.
- With that boot the intro runs 7293 ticks (20 ms each, ≈146 s): floor 7
  room 1 → letter (`ShowPicture`, tick 1081) → floor 3 room 1 (tick 3217)
  → floor 2 room 2 (4919) → floor 1 room 7 (5652) → `flag_game_over`
  (7293). That game-over is the cutscene's terminal (`PlayWorld` breaks on
  `FlagGameOver`, `mainLoop.cpp:185`), not a death.
- One engine divergence blocks it: FITD calls `GenereActiveList` every
  frame (`mainLoop.cpp:249`; the spawn scan is `main.cpp:3959`). PyAitD gates
  `_genere_active_list` on `flag_genere_aff_list`, and the reduced-form
  `LM_STAGE` (`life_reduced.py:37`, `life.cpp:620`) never raises it. The
  director script (life 547) uses it to drop world object 288 (life 537)
  onto floor 7 at tick 1596; unspawned, the intro stalls there forever.
- `PlayWorld(allowSystemMenu = 0)` breaks on any key or click
  (`mainLoop.cpp:71-89`): the whole cutscene is skippable.

## Engine changes (`engine/`, FITD-cited)

- `game.start_game(game, stage, room)` — the `startGame` staging minus
  `PlayWorld`: `current_camera_target_actor = current_world_target = -1`
  (`main.cpp:1235`), `current_floor = new_num_etage = stage`,
  `flag_change_etage = 0`, `change_salle(room)`, `new_num_salle = room`,
  `new_num_camera = 0`, `flag_init_view = 2`, `spawn_stage_actors`,
  `flag_genere_aff_list = 0`, `num_camera = -1`, and
  `game.floor_start = None` (a cutscene has no restart point). `init_game`
  keeps its current attic behaviour; `start_game` is what the shell calls on
  a game it has just built.
- Reduced `LM_STAGE` sets `vm.game.flag_genere_aff_list = 1` when the new
  stage equals `current_floor`, with the citation above. Minimal on purpose:
  an unconditional per-frame scan would change spawn timing everywhere and
  the golden tick values pinned in the suite. Recorded as a `ponytail:` with
  the unconditional scan as the upgrade path.
- `Game.allow_system_menu: bool = True` (FITD's `allowSystemMenu`). When
  False, `_handoff_game_over` emits `CutsceneFinished()` instead of
  `GameOver()`; the LIFE side is untouched (`LM_GAME_OVER`'s 120-unit delay
  stays on the effect so the last frame holds like FITD).
- `effects.py`: `CutsceneFinished` modal effect → `GameMode.CUTSCENE_END`.
- `GameProfile` fields: `intro_start: tuple[int, int] | None = (7, 1)`,
  `game_start: tuple[int, int] = (0, 0)`; pinned in `test_game_profile.py`.
  `engine/` reads them through `game.profile`, never the literals.

## App changes (`app/shell.py`)

- `_hero_branch` builds the hero's game as today, then, when
  `profile.intro_start` is set and the boot was not a debug start, calls
  `start_game(game, *profile.intro_start)`, sets `allow_system_menu = False`
  and `session.cutscene = True`. Floor swaps mid-cutscene use the existing
  `floor.number != game.current_floor` reload (`shell.py:1009`).
- Input during the cutscene: every key or click ends it. The event pump
  routes nothing to PLAY while `session.cutscene`; the first KEYDOWN,
  MOUSEBUTTONDOWN or touch sets `session.skip_cutscene`. `ShowPicture` (the
  letter) still auto-dismisses by its own delay; a click on it is a skip
  too, since FITD's `Click` break precedes the picture handling. This is a
  deliberate port divergence, not FITD's behaviour: FITD's 0x1B (Escape)
  calls `processSystemMenu()` unconditionally (`mainLoop.cpp:55-61`),
  *before* any `allowSystemMenu` test, so Escape opens the system menu
  during FITD's own intro rather than skipping it (only 0x1C/0x17 and any
  click break on `allowSystemMenu == 0`, `mainLoop.cpp:69-92`). The port
  chooses the simpler rule instead -- no system menu during the opening,
  every key (Escape included) is a skip -- marked `ponytail:` at the event
  pump with the faithful upgrade path named.
- Ending: on `CutsceneFinished` or `skip_cutscene`, the shell performs the
  existing atomic replace (`_restart_branch` shape): a fresh
  `init_game(hero)`, `start_game(game, *profile.game_start)` — which is the
  attic start `init_game` already stages, kept explicit —
  `allow_system_menu = True`, new floor, new session input. Settings and the
  render options carry over as they do for a death restart.
- Death during the cutscene is impossible by construction (no player
  input); a `GameOver` in cutscene mode is a bug and raises in tests.
- `--floor`/`--combat-venue`/`--mouse-combat-fixture` bypass the cutscene
  exactly as they bypass the selector. A new `--skip-intro` flag does the
  same for a normal boot (fast iteration; not FITD).

## Rendering

The cutscene renders through the ordinary PLAY path: `build_frame` per
camera on floors 7/3/2/1 with the same shading, filter and override options.
No HUD (`render_play_hud` is skipped while `session.cutscene`), no cursor,
no hit feedback. Audio stays on the M4b stubs (music/sample opcodes log).

## Testing

- `start_game` postconditions on real data: targets −1, floor/room/camera
  flags, hero not live on floor 7, object 286 live with life 546/547.
- Regression for the divergence: boot floor 7, tick to 1597, assert world
  object 288 is live (`obj_index != -1`) and its life is 537. This test
  fails on today's code.
- Headless intro journey (`tests/test_intro.py`, real data, ~1 s): boot,
  auto-dismiss the picture, assert the floor sequence 7→3→2→1 at the pinned
  ticks above and `CutsceneFinished` at tick 7293. Golden ticks are pinned
  from this run; a disagreement is traced through FITD, never re-guessed.
- Skip: a KEYDOWN at tick 100 and a click at tick 2000 (mid floor 7) each
  produce the attic on the next frame with the chosen hero and no
  `GameOver`.
- Shell: `--skip-intro` and the debug starts never enter cutscene mode; a
  death after the intro restarts the attic, not the intro.
- Proof `make prove-intro` (`tools/prove_intro.py`, pattern of
  `prove_graphics.py`): renders one PNG per (floor, camera) the cutscene
  visits into `docs/intro-proof/`, plus the tick log; a pytest gate asserts
  every visited camera produced a frame.
- `make prove-mouse-only` and `make prove-shell` stay green (the journeys
  pass `--skip-intro` or run the cutscene to completion — one of each).

## Files

| file | change |
|---|---|
| `PyAitD/engine/game.py` | `start_game`, `allow_system_menu` |
| `PyAitD/engine/playworld.py` | `_handoff_game_over` emits `CutsceneFinished` when `allow_system_menu` is False |
| `PyAitD/engine/effects.py` | `CutsceneFinished`, `GameMode.CUTSCENE_END` |
| `PyAitD/games/aitd1/life_reduced.py` | reduced `LM_STAGE` raises the spawn request |
| `PyAitD/games/base.py`, `PyAitD/games/aitd1/profile.py` | `intro_start`, `game_start` |
| `PyAitD/app/shell.py` | cutscene boot, skip input, end-of-cutscene replace, `--skip-intro`, HUD/cursor suppression |
| `PyAitD/app/ui.py` | `ModalSession.cutscene`, `skip_cutscene` |
| `tools/prove_intro.py`, `Makefile` | proof |
| `tests/test_intro.py`, `tests/test_game.py`, `tests/test_game_profile.py`, `tests/test_life_ops.py`, `tests/test_runtime_modes.py` | tests above |
| `AGENTS.md`, `CONTEXT.md`, `docs/intro-proof.md` | boundary + evidence |
