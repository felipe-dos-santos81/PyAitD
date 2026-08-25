# Mouse Accessibility Hardening Proof

Date: 2026-08-25
Spec: `docs/superpowers/specs/2026-08-24-overall-mouse-accessibility-design.md`
Plan: `docs/superpowers/plans/2026-08-24-mouse-accessibility-hardening.md`

## Evidence identity

- Implementation commit under test: `97039ced1ed58a08471f7cde1cbe0c25497dd29e`
- Environment: macOS 26.6.2 (build 25G83), Apple Silicon `arm64`
- Real-data identity: `INDARK`, 51 regular files; SHA-256 of the sorted
  per-file SHA-256 manifest:
  `3c4dabcb58ad82dbdbda697c7a372136b8597939136df503a65b3b946c8c22c2`.
  This identifies the supplied data set without copying its contents.

## Automated evidence

All commands below were run on 2026-08-25 with
`PYAITD_DATA='/Users/felipe.dos.santos/code/mine/m-aitd/Alone in the Dark 1.app/Contents/Resources/game/INDARK'`.

| Command | Result |
|---|---|
| `make prove-mouse-accessibility` | PASS — `188 passed, 27 warnings in 10.72s` |
| `make prove-mouse-only` | PASS — `15 passed, 5 warnings in 9.14s` |
| `make prove-shell` | PASS — `192 passed, 20 warnings in 10.37s` |
| `.venv/bin/pytest -q` | PASS — `640 passed, 1 skipped, 1 xfailed, 27 warnings in 17.90s` |
| `make prove` | PASS — `4 passed in 0.19s` |

The focused Make targets ran with `SDL_VIDEODRIVER=dummy` and
`SDL_AUDIODRIVER=dummy`. The warnings are pygame key-name calls before
`pygame.init()` in the existing input/loop tests; no command failed.

These headless, real-data tests cover the current hit geometry, hover purity,
physical/touch semantic parity, world-target precedence, modal-entry
held-push cancellation, shell journeys, and held-push/restart journeys. They
do not demonstrate physical one-button or on-screen-keyboard operation in a
visible window.

## Windowed one-button and on-screen-keyboard evidence

The following is user-attested physical evidence, not headless test evidence.
The user operated two visible fresh processes with the real data above, using
only the primary pointer button for decisions; holding it was used only for
pushing. The controller started the equivalent direct entrypoint below rather
than literal `make run`, because Makefile's unquoted `data=` expansion cannot
handle the supplied data path's spaces:

```text
.venv/bin/python -m PyAitD --data '/Users/felipe.dos.santos/code/mine/m-aitd/Alone in the Dark 1.app/Contents/Resources/game/INDARK'
```

Both processes exited cleanly with exit code 0.

### Operator setup record

| Field | Result |
|---|---|
| Physical primary-button pointer device | PASS — standard mouse |
| On-screen keyboard product and enabled configuration | PASS — macOS Accessibility Keyboard |
| OSK single-finger operation observed where keyboard input is required | PASS — user confirmed checklist setup, option 1 |
| Game-data identity matched to the digest above | PASS — same worktree/build/data supplied for this evidence |

### Emily route

| Checkpoint | Result | Observation |
|---|---|---|
| Select Emily portrait and story; verify one replacement and no premature PLAY frame | PASS | User completed the displayed checklist |
| Walk and interact; take and leave an object | PASS | User completed the displayed checklist |
| Open inventory; choose object and action | PASS | User completed the displayed checklist |
| Open reading; previous, next, and close | PASS | User completed the displayed checklist |
| Open system menu and navigate Configuration, including OSK-required control input | PASS | User completed the displayed checklist |
| Target combat and perform the supported attack/throw route | PASS | User completed the displayed checklist |
| Hold-push the supported object; release during approach/contact | PASS | User completed the displayed checklist |
| Lose and recover window focus; verify the pending action is cancelled | PASS | User completed the displayed checklist |
| Reach game over and restart | PASS | User completed the displayed checklist |
| Quit cleanly from the window | PASS | User selected `Emily PASS`; process exit code 0 |

### Carnby route

| Checkpoint | Result | Observation |
|---|---|---|
| Select Carnby portrait and story; verify one replacement and no premature PLAY frame | PASS | User completed the displayed checklist in a fresh process |
| Walk and interact; take and leave an object | PASS | User completed the displayed checklist in a fresh process |
| Open inventory; choose object and action | PASS | User completed the displayed checklist in a fresh process |
| Open reading; previous, next, and close | PASS | User completed the displayed checklist in a fresh process |
| Open system menu and navigate Configuration, including OSK-required control input | PASS | User completed the displayed checklist in a fresh process |
| Target combat and perform the supported attack/throw route | PASS | User completed the displayed checklist in a fresh process |
| Hold-push the supported object; release during approach/contact | PASS | User completed the displayed checklist in a fresh process |
| Lose and recover window focus; verify the pending action is cancelled | PASS | User completed the displayed checklist in a fresh process |
| Reach game over and restart | PASS | User completed the displayed checklist in a fresh process |
| Quit cleanly from the window | PASS | User selected `Carnby PASS`; process exit code 0 |

## Failures, fixes, and reruns

No failure, fix, or rerun was reported for either user-attested windowed pass.

## Current handoff status

Implementation and all bounded automated gates are complete at the commit
above. The Emily and Carnby user-attested human-operated windowed checks both
passed, so the mouse-accessibility hardening milestone and its release gate are
complete.

---

# Native Mouse Melee Correction Proof

Date: 2026-08-25
Spec: `docs/superpowers/specs/2026-08-25-native-mouse-melee-design.md`
Plan: `docs/superpowers/plans/2026-08-25-native-mouse-melee.md`

## Why this section exists

The "Target combat and perform the supported attack/throw route" rows above
were attested honestly, but the route they attested was wrong. ENGLISH.PAK
text 32 is `Throw`, not `Fight`, so a target click called
`choose_inventory_action(..., 32)` and launched the held saber at the floor
instead of swinging it. FITD `mainLoop.cpp:87-101` maps held action input to
`action = 0x2000` and executes the in-hand object's LIFE, which is what arms
melee animation 41. This section records the corrected contract and its
retest. The earlier rows are left unedited as the historical record.

## Evidence identity

- Implementation commit under test: `50490a7a00a64b686e22d826961bc4a421142118`
- Combat-path commits: `5af3370` (native melee route) and `cd30109` (latch
  lifetime coverage). The two later commits under test, `ae73c44` and
  `50490a7`, change only Makefile quoting and debug-start hero selection, so
  the combat path is byte-identical across every observation below.
- Environment: macOS 26.6.2 (build 25G83), Apple Silicon `arm64`
- Real-data identity: `INDARK`, 51 regular files; SHA-256 of the sorted list
  of per-file SHA-256 hashes: `ef1d63ea01882e1688ca3ca34652d5f2f0adcd9c5b63bdf4d82e21702bab1fce`,
  reproduced with:

  ```bash
  find "$PYAITD_DATA" -type f -exec shasum -a 256 {} \; \
    | awk '{print $1}' | sort | shasum -a 256
  ```

  The file count matches the earlier entry. The digest differs because that
  entry's "sorted per-file SHA-256 manifest" does not pin down whether paths
  were included, and no variant tried here reproduced its value; the two
  numbers are therefore not comparable, and this one is defined by the
  command above.

## Automated evidence

Run on 2026-08-25 at `50490a7` with
`PYAITD_DATA='/Users/felipe.dos.santos/code/mine/m-aitd/Alone in the Dark 1.app/Contents/Resources/game/INDARK'`,
`SDL_VIDEODRIVER=dummy` and `SDL_AUDIODRIVER=dummy`.

| Command | Result |
|---|---|
| `make prove-mouse-accessibility` | PASS — `205 passed, 29 warnings in 11.23s` |
| `make prove-mouse-only` | PASS — `16 passed, 5 warnings in 9.80s` |
| `make prove-shell` | PASS — `202 passed, 20 warnings in 10.94s` |
| `.venv/bin/pytest -q` | PASS — `664 passed, 1 skipped, 1 xfailed, 29 warnings in 18.43s` |
| `make prove` | PASS — `4 passed in 0.19s` |
| `git diff --check` | PASS — no output |

The skip and xfail counts are unchanged from the previous section's run. The
warnings remain pygame key-name calls made before `pygame.init()`.

The real-loop journey `test_mouse_journey_one_click_attack_swings_the_held_saber`
drives `main.run()` with a synthetic event stream and only the renderer
stubbed. It equips object 38 with `Use`, clicks obj222 once, and observes the
hero's native melee states 1 → 10 → 2, `enemy.hit_by == hero_idx` with
`hit_force == 4`, object 38 still in inventory, and `world_objects[38].obj_index
== -1`, meaning no saber actor ever reached the floor. Force 4 is automated
evidence only; it is not a number visible in the window.

## Windowed evidence

User-attested physical evidence, not headless test evidence.

Two invalid attempts preceded the valid runs and are recorded because they
produced the first FAIL report:

| Attempt | Outcome |
|---|---|
| `make run-mouse-combat` from the repository root | INVALID — the root checkout is `main`, which does not contain the fix. Reported "no white/red hit outline, saber dropping to the floor", which is the unfixed Throw behaviour. |
| `make run-mouse-combat data="/abs/path/.../INDARK"` from the worktree | INVALID — never reached the game. `data ?=` carried its own quotes, so `--data $(data)` word-split on the spaces in `Alone in the Dark 1.app`: `PyAitD: error: unrecognized arguments: in the Dark 1.app/...`. Fixed in `ae73c44`. |

Valid runs, from the worktree:

```bash
make run-mouse-combat data="/Users/felipe.dos.santos/code/mine/m-aitd/Alone in the Dark 1.app/Contents/Resources/game/INDARK"
make run-mouse-combat hero=1 data="/Users/felipe.dos.santos/code/mine/m-aitd/Alone in the Dark 1.app/Contents/Resources/game/INDARK"
```

Each run opens the inventory, selects object 38, chooses the first action row
(`Use`, text 23), and clicks obj222 once. The first action row matters: a lower
row is `Throw`, which is preserved and still drops the saber by design.

| Checkpoint | Hero | Result | Observation |
|---|---|---|---|
| One click on obj222 swings the held saber | Carnby | PASS | User reported "the saber swings and hits, no drop" |
| The strike lands a visible hit | Carnby | PASS | Included in the same report |
| The saber stays in hand, never dropping to the floor | Carnby | PASS | Included in the same report |
| White/red hit outline appears | Carnby | PASS | User confirmed when asked directly |
| One click swings, outlines, and does not drop the saber | Emily | PASS | User confirmed all three when asked directly |
| Losing window focus mid-swing does not resume the attack later | both | PASS | User confirmed when asked directly |
| Opening the inventory mid-swing does not resume the attack later | both | PASS | User confirmed when asked directly |

Carnby was observed before `--hero` existed; the fixture built hero 0
unconditionally, so that run is attributable to Carnby. Emily was reached with
`hero=1`, added in `50490a7`.

## Failures, fixes, and reruns

| Failure | Fix | Rerun |
|---|---|---|
| Target click chose inventory action 32 (`Throw`) and dropped the saber | `5af3370` — `attack_in_hand` validates, stops and faces only; the accepted target is latched in `InputBuffer` and the fixed-tick snapshot publishes `local_joyd=1`, `local_click=1`, `action=0x2000` until the melee animation completes, bounded at 100 ticks | Windowed retest above: PASS for both heroes |
| `make run-*` could not accept a `data=` path containing spaces | `ae73c44` — quote every `$(data)` use site and drop the quotes baked into the default | `make prove-mouse` (56 meshes) and `make prove-combat` (`62 passed, 1 xfailed`) both accept the spaced path |
| Emily's copy of the fixture was unreachable in a window | `50490a7` — add `--hero` (0=Carnby, 1=Emily) and a `hero=` passthrough on the run targets | Emily windowed retest above: PASS |

## Current handoff status

The native mouse melee correction is complete at `50490a7`. All bounded
automated gates pass, and both heroes were retested by hand in a visible
window with no failure outstanding. A target click now performs the held
object's own melee strike; explicit inventory `Throw` remains reachable only
by choosing that row.
