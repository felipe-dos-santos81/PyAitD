# AITD1 Mouse Fidelity Design

Date: 2026-09-02

Status: Approved design — awaiting implementation plan

Reference: FITD `mainLoop.cpp` (input snapshot), `zv.cpp` (cube_intersect)

Builds on: M3d mouse-only input; M3e combat and invariants; mouse hold-to-push
actions; overall mouse accessibility hardening; held pointer follow
(`2026-08-26-held-pointer-follow-design.md`)

## Goal

Make the held pointer follow go where the player points and show them where it
is going. Three complaints drive this: the hero heads for a spot the player did
not point at (a floor point behind a wall or object, a snap several cells away,
the wrong depth in a neighbouring room, an approach cell on the far side of an
object), a camera cut redirects or stops the hero while the hand is still, and
the cursor gives too little feedback to tell what a press will do.

The gesture model is unchanged: PLAY movement stays hold-only, and the hero
never moves under mouse control unless the left button is down. This design
fixes what a press resolves to and what the player sees, not how they press.

## Decisions taken during brainstorming

1. Keep hold-only; no tap-to-walk, no click-vs-hold discriminator.
2. Fix picking in the engine (occlusion-aware ray pick, approach A) rather
   than a per-camera screen-space walkable map (B) or feedback alone (C).
3. Snapping is bounded in screen pixels, not grid cells.
4. A camera cut opens a pointer dead zone; a still pointer is never
   re-resolved.
5. Feedback is a projected destination marker, a hover preview of the same
   marker, and a press ring; cursor shapes stay, colours tighten.

## Scope

- `engine/nav/picking.py`: hard-col occlusion of floor hits, per-room floor
  height for viewed rooms, a screen-space snap budget, visibility of approach
  cells. `pick_floor_any_room` keeps its signature and return shape.
- `engine/nav/navmesh.py`: `nearest_walkable` and `approach_cell` grow an
  optional acceptance predicate so the caller can reject candidates.
- `app/shell.py` `follow_pointer` and `InputBuffer`: the cut dead zone.
- `app/ui.py`: destination marker, hover preview, press ring, colour tweaks.
- Tests, a proof document, and the entry-point docs.

## Non-goals

> **Amendment (2026-09-03, post-implementation).** The first non-goal below was
> overtaken by play testing. One follow-up change landed on the gesture and
> stands: the second press of a double press resumes the first press's
> destination instead of re-picking (735a980), answering "it always starts to
> walk when I double-click to start running". A second attempt at the same
> report -- holding the hero still for 200ms at press time so the double press
> could land as a run with no walking step (20a09ac) -- was reverted a day
> later: it made an ordinary-length click move the hero nowhere, since the
> release cancels the intent and a click is shorter than the wait. The walking
> step in front of a double press is accepted as intrinsic. See CONTEXT.md.

- Any change to the gesture: tap-to-walk, timing thresholds, right-click,
  double-click semantics, pointer lock or grab.
- Changing `NavIntent`, `navigate.decide`, `apply_click_intent`, arrival
  dispatch, LIFE, collision, or animation.
- A per-camera screen-space pick cache (approach B). It can be layered on
  later if profiling asks for it.
- New mouse contract capabilities or routes.
- Keyboard-mode cursor or feedback.

## Section 1: picking (`engine/nav/picking.py`)

> **Amendment (2026-09-02, post-implementation review).** The occlusion test
> below is implemented, tested and SHIPS OFF (`picking.OCCLUDE_BY_DEFAULT`).
> Two things this section assumes are not true of the data. It assumes the
> camera sits inside the room's volume, so that "every hard col of every room
> the camera views" is a sound occluder set; most of this game's cameras sit
> outside, behind or above the perimeter wall, so the segment to any floor
> point crosses that wall first. `floor_point_visible` now clips the segment
> at the picked room's own volume (`room_volume`) and counts only boxes
> entered after it. That took camera slots with NO clickable floor pixel from
> 87 of 274 down to 14 — not to zero, because the second assumption also
> fails: hard cols approximate collision, not the painted scene, and some
> rooms are a handful of chunky full-height blocks that hide everything the
> camera can pick. Fourteen dead cameras being worse than the mis-picks the
> filter prevents, the filter is off and a whole-game census gates it. See
> `docs/mouse-fidelity-proof.md`.

### Occlusion test

After a cover polygon's homography recovers a floor point `(wx, wz)` at height
`floor_y`, build the ray in room space from the camera position (`CameraState`
gives it) to that point. Intersect it with every hard collision box of every
room the camera views, each box offset by its room's world origin relative to
the picked room (`room_delta`, the same re-framing `resolve_play_click` uses).
Hard cols are axis-aligned boxes `(x1, x2, y1, y2, z1, z2)`, so this is a
slab test per box; a room has a few dozen.

If any box is hit strictly nearer than the floor point, the floor hit is
discarded and the pixel resolves to that box:

- A box belonging to a world object is already handled by actor picking, which
  runs first in `resolve_play_click`; nothing changes there.
- Any other box (walls are hard cols in these floors) returns `None`, which
  the resolver reports as `blocked`.

The homography's own self-consistency check (forward projection within two
pixels, point inside the polygon) is kept; occlusion is an additional filter,
not a replacement.

### Depth

The floor plane stays at the hero's height (`hero.world_y`) for the hero's own
room. For every other viewed room the plane is that room's own floor height,
derived from its world origin, so a pixel on a lower or higher neighbouring
room lands at that room's depth rather than the hero's. Stairs keep working as
today: the hero's height changes while climbing and the plane follows.

### Snap budget

`nearest_walkable` keeps its outward ring search, but each candidate is
projected back to the screen through `project_floor_point` and rejected if it
lies more than `SNAP_BUDGET_PX = 8` logical pixels from the pointer. Beyond
that the pick is `blocked`. The budget is in screen pixels so it means the
same thing near and far from the camera.

`approach_cell` keeps its reach (`TARGET_SNAP_CELLS`), but a candidate must
also pass the occlusion test under the current camera, so the hero does not
aim for a cell behind the object it is approaching.

### Interface

- `pick_floor_any_room(logical_pos, floor, hero_room, cam_slot, floor_y)` is
  unchanged in signature and return shape `(x, z, room) | None`.
- Two new pure, module-level helpers: `ray_box_hit(origin, point, box) ->
  float | None` (the parametric distance of the nearest entry, or None) and
  `floor_point_visible(state, floor, room_idx, x, z, floor_y) -> bool`.
- `nearest_walkable(mesh, x, z, max_cells=6, accept=None)` and
  `approach_cell(..., accept=None)`: `accept(x, z) -> bool` filters
  candidates; None keeps today's behaviour.

## Section 2: the camera cut (`app/shell.py`)

### Dead zone

`follow_pointer` records the camera index each resolution was made under. When
`game.num_camera` differs from that index, the follow enters a settle state:
the current destination is kept and the pointer is not re-resolved until it
has moved more than `CUT_DEAD_ZONE_PX = 6` logical pixels from where it was at
the cut. Hand jitter and the one-pixel drift that arrives with a cut no longer
redirect the hero. Once the hand moves past the zone, the new camera's
resolution takes over exactly as today and the settle state ends.

### Arrival under a new camera

If the kept destination is reached, or the follower gives up, while settling,
the hero stands and the follow stays live, the same as a `blocked` hover
today. A still pointer is never re-resolved.

### State

`InputBuffer` gains `follow_camera` (the camera index of the last resolution,
or None) and `follow_settle_origin` (the logical position at the cut, or
None). Both are cleared by `_cancel_follow` and `_rebase_follow`, the paths
that already clear `follow_pos`, so release, focus loss and a floor change
behave as they do now.

### Invariant

The hero never moves under mouse control unless the left button is down.
Every navigation intent stays hold-bound.

## Section 3: cursor feedback (`app/ui.py`, the shell's cursor site)

Presentation only; nothing here touches world state.

- **Destination marker.** While a walk or target intent is live under mouse
  control, a small diamond is drawn at the intent's destination, projected
  through `project_floor_point` under the current camera. Hidden when the
  projection fails or lands off the logical frame.
- **Hover preview.** Before a press the same diamond is drawn faintly at the
  point the hover would resolve to. `resolve_play_click` already runs every
  frame for the cursor kind, so the preview reuses that result.
- **Press ring.** While the button is held a ring around the cursor marks the
  hold. It disappears on release. While the cut dead zone is active the ring
  is drawn dashed.
- **Shapes and colours.** Kind shapes are kept. `blocked` becomes a clear X in
  a colour distinct from walk; the walk circle gains a centre dot.
- **Keyboard mode.** No cursor, as today.

The renderer signature grows to `render_cursor(painter, logical_pos, kind,
held=False, settling=False, destination=None, preview=None)`, every new
argument defaulting to today's output.

## Section 4: testing and gates

- **Picking** (`engine` marker): ray-box intersection on synthetic boxes; a
  floor point behind a box rejected and one in front accepted; the snap budget
  rejecting a candidate past 8 pixels and accepting one inside; a viewed
  room's own floor height used for its plane. Against real data: for every
  camera in the attic, a pixel on a known wall no longer picks the floor
  behind it, and a pixel on open floor still picks the same point as before.
  `tools/prove_mouse.py` gains a count of wall pixels that used to fall
  through, per camera.
- **Follow** (`shell` marker, `tests/test_play_loop.py`): a cut with a still
  pointer keeps the destination; a one-pixel drift after a cut does not
  redirect; a seven-pixel move does; release and a floor change clear the
  settle state; arrival while settling leaves the follow live.
- **Cursor** (`shell` marker): marker at the projected destination; hidden
  when unprojectable; ring only while held; dashed only while settling;
  default arguments reproduce today's drawing byte for byte.
- **Contract**: `mouse_contract.py` gains no capability or route; the
  exhaustive contract gate is unchanged.
- **Attestation**: `docs/mouse-fidelity-proof.md` records the automated
  gates and a windowed pass row per hero, since the feel of the dead zone and
  the snap budget are not fully provable headless.
- **Gate**: `make test` green, plus `make proof-mouse` with game data.
- **Docs**: CONTEXT.md milestone row, AGENTS.md and README where they describe
  the cursor.
