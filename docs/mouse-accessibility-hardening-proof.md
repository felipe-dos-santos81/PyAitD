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
