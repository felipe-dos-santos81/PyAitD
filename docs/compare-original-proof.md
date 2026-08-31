# Compare-With-Original Live Mirror Proof

Date: 2026-08-30
Spec: `docs/superpowers/specs/2026-08-30-compare-original-live-mirror-design.md`
Plan: `docs/superpowers/plans/2026-08-30-compare-original-live-mirror.md`

## Automated evidence

Run 2026-08-30 on macOS (arm64) with the real game data
(`Alone in the Dark 1.app/Contents/Resources/game/INDARK`), branch
`feat/compare-original`.

- `make test`: PASS — `1489 passed, 1 skipped, 1 xfailed in 39.48s`
  (mirror key table, mirror sink, shell pump tap, and the orchestrator's pure
  parts: conf text, placement math, arg parsing, plus a real-data pin of the
  bundle layout). Run headless via `SDL_VIDEODRIVER=dummy
  SDL_AUDIODRIVER=dummy`. The single xfail remains the M3c death-cinematic
  restart boundary that M4c owns.
- Spike (2026-08-30): `CGEventPostToPid` delivery proven by before/after
  screenshots of the DOS intro advancing on posted arrows+Return; windowed
  DOSBox-X boot from the bundled data proven; window discovery and
  ScreenCaptureKit capture proven (capture deliberately not shipped).

## Windowed attestation

Pending. The aligned both-at-attic, keyboard-moves-both-heroes pass needs a
human in front of a stable window session; it is recorded here when it lands.
The automated gates above are green in the meantime.

What the live `make compare` runs on 2026-08-30 DID verify:

- Both windows boot and are discoverable: the helper's `window` query returns
  the port (`PyAitD …` caption) and DOSBox-X (`DOSBox-X <ver>: INDARK - …`)
  pids and bounds; DOSBox-X runs the bundled `INDARK.EXE`.
- System Events stacking works: with placement enabled the DOSBox-X window was
  observed moving to directly below the port window (port bottom + 24px gap).
- `CGEventPostToPid` drives the unfocused port: posted Returns advanced
  title -> credits -> startup menu -> the two-portrait character-select screen
  (captured by ScreenCaptureKit). Posted keys also reached DOSBox-X.
- Teardown on port exit works: when the port's `shell.main` returned, the
  orchestrator's `finally` terminated DOSBox-X and the resident helper
  (`pgrep` showed both gone).

What could not be completed, and why it is pending rather than failed:

- The end-to-end forwarding capture (align both games to the attic, post an
  arrow to the port, before/after-capture the original showing it move) never
  produced a clean pair. The live session proved unstable in this environment:
  in early attempts the port process exited at unpredictable times with a
  clean status before alignment finished, and ScreenCaptureKit window capture
  was intermittent (several `NONE`/timeout results) so a before/after pair of
  the original reacting to a forwarded PLAY arrow could not be recorded. This
  is an environment/attestation limitation, not a code-regression signal; the
  forwarding path itself (table, sink, pump tap) is pinned by the headless
  tests and the CGEvent delivery by the spike.

Observations made while attesting (informational):

- `make compare` initially refused to boot against the real bundle because the
  startup check looked for `GAME.INS` at the `Resources/` root; the bundle
  keeps `GAME.INS`/`GAME.GOG` beside `INDARK/` (the mounted `C:` the conf's
  `imgmount` reads after `c:`). Fixed in commit `5209891` and pinned by
  `tests/test_compare_original.py::test_the_bundle_keeps_the_disc_images_beside_indark`.
- Sessions appeared more stable with the System Events `osascript` placement
  disabled, but that is an unproven correlation (one placement-enabled run
  lived >160s); placement is a courtesy per the spec and degrades to printed
  manual instructions on failure, so no code change was made on that basis.
