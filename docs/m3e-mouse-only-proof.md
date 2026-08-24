# M3e Mouse-Only Reachability and Combat Proof

Date: 2026-08-24
Spec: `docs/superpowers/specs/2026-08-23-mouse-only-combat-and-invariant-design.md`
Plan: `docs/superpowers/plans/2026-08-23-m3e-mouse-reachability-and-combat.md`

## Automated evidence

- `make prove-mouse-only`: PASS — `8 passed in 5.97s` (`tests/test_mouse_only.py`,
  run under `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`).
- `make test`: PASS — `445 passed, 1 skipped, 1 xfailed in 13.17s`.
- `make prove`: PASS — `4 passed in 0.21s` (`tests/test_prove_m3a.py`).

## Windowed one-button evidence

Run 2026-08-24 with the real game data via `make run` and
`make run-mouse-combat`, one physical left button, no keyboard.

| Route | Result | Observation |
|---|---|---|
| Attic found/take/HUD/inventory/action | PASS | Lamp click paths to it, Take fires, INV HUD opens, lamp selected, action chosen — one click per decision |
| Reading page/back/close | PASS | Visible buttons page and close without keys |
| Venue click-to-walk | PASS | Fixed during this run: `_quad_of` rejected non-bbox-friendly cover polygons as degenerate, leaving the venue floor unpickable (commit 9eaaa7b, `tests/test_pick_venue.py`); hero now paths to clicked floor |
| Combat stop/face/force-2 throw | PASS | INV -> saber -> Use puts it in hand; clicking obj222 stops and faces the hero and throws without approach walking |
| Game-over restart | PASS | One click after the prompt restarts |
| Window close | PASS | Window chrome quits |
| Four HUD corners | PASS | Clicks near all four corners of the 28x20 target register |
| HUD/letterbox isolation | PASS | HUD clicks never create navigation; letterbox clicks do nothing |
| Five honest cursor states | PASS | One visible cursor each for inventory, attack, target, walk, blocked |
| Modal pointer visibility | PASS | OS pointer visible over FOUND/INVENTORY/READING buttons; hidden only where the software cursor owns PLAY mouse mode (per-frame toggle, commit bf89845) |
| Keyboard-mode hiding | PASS | No software cursor or clickable HUD advertised |
| Ten-second modal responsiveness | PASS | Every modal left open ~10s, window stays responsive |

## Scope ruling

M3e proves the implemented M3 surface only. M4a, M4b, and M4c must extend the
capability registry and record both complete protagonist journeys before the
engine can claim start-to-ending mouse-only completion. M4 owns start-to-ending
completion for both protagonists.
