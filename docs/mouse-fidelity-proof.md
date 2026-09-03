# Mouse fidelity proof

Spec: `docs/superpowers/specs/2026-09-02-mouse-fidelity-design.md`
Plan: `docs/superpowers/plans/2026-09-02-mouse-fidelity.md`

## What ships, and the one thing that does not

Five of the six pieces ship live: the ray-box occlusion primitives, viewed
rooms picked at their own depth, the eight-pixel snap budget, the six-pixel
camera-cut dead zone, and the cursor's destination marker, hover preview and
press ring.

**The occlusion FILTER on the floor pick ships OFF**
(`picking.OCCLUDE_BY_DEFAULT is False`). The census below is why. Hard cols
are collision proxies, not the painted scene — whole rooms are modelled as a
handful of chunky full-height blocks — and this game's cameras mostly sit
OUTSIDE the room they film, behind or above the perimeter wall. With the
filter on, 87 of the game's 274 camera slots had no clickable floor pixel at
all: every press resolved `blocked`, and because the approach-cell filter
shares the test, every object click in those rooms went with it. Clipping the
occlusion segment at the picked room's own volume (`picking.room_volume`, used
by `floor_point_visible`) fixes the camera-outside-the-room case and takes
that from 87 down to 14. Fourteen dead cameras is still fourteen places the
player cannot walk with the mouse, which is worse than the "the floor behind
that crate is clickable" the filter buys, so the filter stays off.

Nothing was deleted for it. `ray_box_hit`, `room_volume`,
`floor_point_visible`, `occlude=True` and `visible_accept(..., occlude=True)`
are all here and tested, and the census gate below fails the moment the flag
turns on while any camera slot would go dark. Turning it back on is a data job
— real occluder volumes for the painted scene — not a flag flip.

## Automated gates

| Gate | Command | Result |
|---|---|---|
| Picking: ray-box, room volume, visibility clip, viewed-room depth, occlusion subset, snap budget, shipped default | `make test-engine` | green — `543 passed, 1 skipped, 1144 deselected, 1 xfailed in 13.27s` (2026-09-02) |
| Follow: cut dead zone, cut back closes it, release and floor change clear it, arrival while settling | `make test-shell` | green — `479 passed, 1210 deselected, 26 warnings in 14.73s` (2026-09-02) |
| Cursor: marker, preview, ring, dashed ring, defaults | `make test-shell` | green — `479 passed, 1210 deselected, 26 warnings in 14.73s` (2026-09-02) |
| Contract unchanged | `make test-shell` | green — `479 passed, 1210 deselected, 26 warnings in 14.73s` (2026-09-02) |
| **Census gate: no camera slot on any floor loses all its clickable floor** | `make test-tools` | green — `100 passed, 1589 deselected in 41.13s` (2026-09-02) |
| Whole-game floor-pick census | `make proof-mouse` | green (exit 0) — see below |

Full suite, `make test` (2026-09-02):

```
1687 passed, 1 skipped, 1 xfailed, 26 warnings in 96.18s (0:01:36)
```

### The census gate

`tests/test_prove_mouse.py::test_no_camera_slot_on_any_floor_loses_all_its_clickable_floor`
sweeps **all eight floors**, every room, every camera slot, at a 16-pixel
stride, and calls `pick_floor_any_room` the way the shell calls it — no
`occlude=` — so it measures what ships. A slot with pickable floor before the
filter and none after fails it.

It runs over all eight floors on purpose. Floor 0, the attic, is the ONE floor
whose cameras sit inside the room they film. The first version of this census
covered floor 0 alone; it stayed green while 87 of 274 camera slots were
completely dark, which is exactly how that shipped and had to be caught in
review instead.

### Whole-game census (`make proof-mouse`)

Every floor, every room, every camera slot, 10-pixel stride, hero agent band,
`floor_y = 0`:

```
camera slots with any pickable floor: 274
slots with NO pickable pixel under the shipped pick: 0
slots that would have none with occlusion forced on: 14  (34315 sampled pixels refused in total)
  would go dark: floor 2 room 0 slot 7 (114 baseline pixels)
  would go dark: floor 5 room 2 slot 4 (108 baseline pixels)
  would go dark: floor 5 room 3 slot 0 (35 baseline pixels)
  would go dark: floor 5 room 4 slot 1 (198 baseline pixels)
  would go dark: floor 5 room 4 slot 3 (91 baseline pixels)
  would go dark: floor 5 room 4 slot 4 (7 baseline pixels)
  would go dark: floor 5 room 4 slot 5 (65 baseline pixels)
  would go dark: floor 5 room 5 slot 2 (108 baseline pixels)
  would go dark: floor 5 room 6 slot 2 (202 baseline pixels)
  would go dark: floor 6 room 6 slot 6 (167 baseline pixels)
  would go dark: floor 6 room 6 slot 7 (257 baseline pixels)
  would go dark: floor 6 room 6 slot 9 (86 baseline pixels)
  would go dark: floor 6 room 6 slot 10 (98 baseline pixels)
  would go dark: floor 7 room 0 slot 2 (488 baseline pixels)

picking.OCCLUDE_BY_DEFAULT is off and every camera slot keeps clickable floor; see the constant for why the filter is where it is.
```

Dead camera slots with the filter forced on, before and after the room-volume
clip:

| | slots with pickable floor | slots with NO pickable pixel |
|---|---|---|
| occlusion on, no clip (as reviewed) | 274 | 87 (32%) |
| occlusion on, clipped at the room volume | 274 | 14 (5%) |
| **shipped (`OCCLUDE_BY_DEFAULT` off)** | **274** | **0** |

Approach cells tell the same story. Walkable cells of the room accepted by
`visible_accept(..., occlude=True)` under four of the camera slots the review
named, plus the attic control:

| camera slot | walkable cells | accepted, no clip | accepted, clipped |
|---|---|---|---|
| floor 5 room 5 slot 0 | 717 | 0 | 249 |
| floor 5 room 2 slot 1 | 64 | 0 | 0 |
| floor 2 room 1 slot 0 | 4421 | 0 | 3587 |
| floor 1 room 4 slot 0 | 1007 | 118 | 913 |
| floor 0 room 0 slot 0 (attic control) | 11120 | 7821 | 7821 |

As shipped (`occlude` off) `visible_accept` stands down and every one of those
cells is accepted, and the object branch never returns `blocked` for want of an
approach cell in any case: it retries unfiltered and then falls through to the
object's own centre.

### Attic occlusion census (`make proof-mouse`)

What the filter would be worth on the one floor where it works — floor 0's
cameras sit inside the room, so the clip changes nothing here and these
numbers are unchanged from the first census:

```
floor 0 camera slot 0: 225 wall/furniture pixels would stop picking the floor behind them
floor 0 camera slot 1: 165 wall/furniture pixels would stop picking the floor behind them
floor 0 camera slot 2: 188 wall/furniture pixels would stop picking the floor behind them
floor 0 camera slot 3: 225 wall/furniture pixels would stop picking the floor behind them
floor 0 camera slot 4: 103 wall/furniture pixels would stop picking the floor behind them
```

## Windowed attestation

Run `make run --skip-intro` and play the attic. Fill in one row per hero.

The "wall pixel refuses" row is now about pixels the pick cannot explain at
all (off the cover polygons, or with no walkable cell inside the snap budget)
— not about walls, which no longer refuse.

| Hero | Unpickable pixel refuses (X cursor, hero stands) | Snap shows marker within the pointer's neighbourhood | Cut with still hand keeps heading | One-pixel jitter after cut does not redirect | Ring while held, dashed while settling, dashed ends when the camera cuts back | Attested by / date |
|---|---|---|---|---|---|---|
| Carnby | pending | pending | pending | pending | pending | |
| Emily | pending | pending | pending | pending | pending | |
