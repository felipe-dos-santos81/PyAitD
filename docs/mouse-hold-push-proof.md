# Mouse Hold-to-Push Proof

Date: 2026-08-24

## Automated evidence

- `make prove-mouse-only`: PASS (13 tests), including the opening-room
  wardrobe journey for both protagonists.
- `.venv/bin/pytest -q`: PASS (610 passed, 1 skipped, 1 xfailed).
- `make prove`: PASS (4 tests) against original AITD1 data.
- `make prove-m3b`: PASS (80 tests).
- `make prove-shell`: PASS (172 tests).

The real outer-loop journey proves the push hover, press-and-hold approach,
latched cursor after pointer drift, release while explicitly pre-engagement,
retry, at least three engaged held ticks that each end in player animation 5,
LIFE enabling `AF_MOVABLE`, collision-owned wardrobe movement, no global Action
or local click signal, and release cleanup for Carnby and Emily.

## Fidelity boundary

The adapter latches world object 4 and resolves its live actor again during the
held route. It projects player animation 5 while engaged. LIFE 1 enables
movement, and `resolve_actor_contacts` performs the movement. The mouse path
never assigns the wardrobe's flags, position, collision fields, or variables.

At both release points, the journey snapshots the hero's effective position
(`room + step`), collision box, base X/Z coordinates, and a nonzero pending X/Z
step before mouse-up. It verifies the event-pump cancellation changes none of
those effective values, then proves the first following simulation tick makes
`base_after == base_before + pending` and clears the pending step. A later tick
leaves that committed base unchanged, proving there is no second commit. The
journey continues to five still frames with no hero or wardrobe movement. This
follows FITD `GereAnim` animation-switch ownership (`anim.cpp:238-253`).

The first two opening ticks run before the measured held interval because the
real boot scripts perform an unrelated `begin_take(object 2)` Action pulse. The
journey then asserts that `InputBuffer.action_held`, `Game.action`, and
`local_click` remain clear on every held simulation tick.

## Windowed accessibility check

- Hover the left wardrobe: amber opposed-arrow cursor, never red X.
- Hold the primary button: the hero approaches and pushes without pointer
  tracking.
- Release during approach and during contact: movement stops immediately.
- Repeat with both character selections.

This windowed check remains pending; the automated headless gates above are
complete.
