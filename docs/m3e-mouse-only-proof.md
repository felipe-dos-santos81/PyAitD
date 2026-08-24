# M3e Mouse-Only Reachability and Combat Proof

Date: 2026-08-24
Spec: `docs/superpowers/specs/2026-08-23-mouse-only-combat-and-invariant-design.md`
Plan: `docs/superpowers/plans/2026-08-23-m3e-mouse-reachability-and-combat.md`

## Automated evidence

- `make prove-mouse-only`: PASS — `8 passed in 5.60s` (`tests/test_mouse_only.py`,
  run under `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`).
- `make test`: PASS — `443 passed, 1 skipped, 1 xfailed in 12.22s`.
- `make prove`: PASS — `4 passed in 0.19s` (`tests/test_prove_m3a.py`).

## Windowed one-button evidence

| Route | Result | Observation |
|---|---|---|
| Attic found/take/HUD/inventory/action | PENDING | awaiting human windowed run (make run / make run-mouse-combat) |
| Reading page/back/close | PENDING | awaiting human windowed run (make run / make run-mouse-combat) |
| Combat stop/face/force-2 throw | PENDING | awaiting human windowed run (make run / make run-mouse-combat) |
| Game-over restart | PENDING | awaiting human windowed run (make run / make run-mouse-combat) |
| Window close | PENDING | awaiting human windowed run (make run / make run-mouse-combat) |
| Four HUD corners | PENDING | awaiting human windowed run (make run / make run-mouse-combat) |
| HUD/letterbox isolation | PENDING | awaiting human windowed run (make run / make run-mouse-combat) |
| Five honest cursor states | PENDING | awaiting human windowed run (make run / make run-mouse-combat) |
| Keyboard-mode hiding | PENDING | awaiting human windowed run (make run / make run-mouse-combat) |
| Ten-second modal responsiveness | PENDING | awaiting human windowed run (make run / make run-mouse-combat) |

## Scope ruling

M3e proves the implemented M3 surface only. M4a, M4b, and M4c must extend the
capability registry and record both complete protagonist journeys before the
engine can claim start-to-ending mouse-only completion. M4 owns start-to-ending
completion for both protagonists.
