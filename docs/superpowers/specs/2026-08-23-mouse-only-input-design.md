# Alone in the Dark 1 — Mouse-Only (Point-and-Click) Input Design

Date: 2026-08-23
Status: Approved (design)
Reference: FITD (`/Users/felipe.dos.santos/code/theirs/FITD`, GPLv2) —
`anim.cpp`, `track.cpp`, `main.cpp`, `mainLoop.cpp`, `evalVar.cpp`
Builds on: M1 (data layer), M2 (actors, camera switching, masks),
M3a (LIFE VM + world), M3b (interaction, effects/modal boundary)

## Goal

Add a point-and-click interface so the game is fully playable with a mouse
alone: click the floor to walk there, click an object to approach and
interact with it. Movement stops depending on tank controls (turn-in-place
then walk), which are the primary accessibility barrier in the 1992 scheme.

This extends the existing accessibility contract in
`2026-08-22-aitd1-build-conclusion-design.md`, which already requires that
"every operation has a keyboard route and a large single-click target" and
that no operation require "precise pointing". Mouse-only is the default
route; the keyboard route is retained, not replaced.

## Non-goals

- Removing keyboard input. Keyboard remains available as an opt-in mode
  (user decision); tank controls stay reachable and tested.
- Multi-hop cross-room pathfinding. One room transition per click is in
  scope; chains of rooms are later work.
- Climbable-wall traversal (`hard_col == 255`). Nothing consumes that
  signal today; see Risks.
- Narrowing the global action bit to the targeted actor only (see
  "Fidelity dial not turned").
- Mask-aware picking, per-primitive actor hit-testing, drag, double-click,
  press-and-hold, or any gesture beyond a single left click.

## Context discovered

Established by reading the tree and by four throwaway probes against real
game data (scratchpad only; nothing committed).

### The engine has steering but no planning

- Player movement is `tracks.py:82 _process_track_manual` (`track_mode == 1`),
  which reads only `game.local_joyd` bits (1 fwd, 2 back, 4 left, 8 right).
  That is the entire tank-control input surface.
- There is no navmesh, grid, waypoint graph, or A*. The nearest primitives
  are `tracks.py:149 _turn_toward` + `tracks.py:42 cap_objet` (steer beta
  toward an x/z point) and `realvalue.give_distance_2d` with
  `DISTANCE_TO_POINT_TRESSHOLD = 400`.
- `tracks.py:104 _process_track_follow` already steers toward a target point
  and sets `speed = 4`, including cross-room aiming via
  `tracks.py:70 get_room_link`. A mouse-walk mode is that function with a
  waypoint list in place of a followed actor.
- `process_track` is `LIFETABLE[0]` — **LM_DO_MOVE** (`life.py:264`).
  Movement happens only when the hero's LIFE script asks for it, so the
  mouse cannot move the player during scripted sequences.

### Cover zones are the authored walkable floor

- Cover zone coordinates are **room-scale / 10** (`playworld.py:53` feeds
  `zv/10` into `world.py:160 is_in_poly`); `hard_cols` and `sce_zones` are
  room-scale.
- Probe (`probe_overlay.py`) projected cover polygons onto the real
  backgrounds through the existing `CameraState`/`transform_point`/`project`
  path: the polygons trace the open floorboards, stop at the wall base, and
  exclude furniture. They are authored floor geometry, per camera; the union
  across the cameras viewing a room is that room's floor.
- Floor 0 room 0, with the hero's real ZV (half-extent 266 room units) and
  the engine's blocking rule: 80.1% of cover area walkable, 2 components,
  largest 91.8%, hero start and both `sce_zones` in it.
- Four rooms have no cover zones at all (floor 3 rooms 6/14/15, floor 4
  room 1). All four have `camera_indices == []` — no camera views them, so
  they are never rendered and never clickable.

### Hard-col type semantics (census across all 8 floors)

| type | boxes | overlap hero Y | meaning |
|---|---|---|---|
| 0 | 121 | 91 | blocks |
| 1 | 666 | 638 | wall, blocks |
| 3 | 194 | 193 | **climbable wall** (FITD `anim.cpp:385`), blocks laterally |
| 4 | 95 | **0** | room link — never blocks |
| 9 | 113 | 111 | trigger, blocks and signals |

- FITD applies `GereCollision` to **every** type (`anim.cpp:396-415`), so the
  port at `actors.py:113` is faithful. Type 3 sets `HARD_COL = 255` as a
  signal for scripts, but still blocks lateral movement.
- All 95 type-4 room links sit entirely outside the hero's `[-1777, 0]` Y
  band, so the engine's own 3D `cube_intersect` keeps doorways open with no
  special-casing.
- 18 boxes carry nonsense type values (`1000`, `64436`, `64536`, `13`, `24`).
  None overlap the hero Y band, so they are inert; this may indicate that
  field is misread for some records. Not addressed here.

### Interaction is contact-driven with no target identity

- `interaction.py:210 resolve_actor_contacts` raises `ShowFound` when the
  moving actor's ZV intersects an `AF_FOUNDABLE` actor **and**
  `actor.track_mode == 1` (`interaction.py:220`).
- The action button is a global flag: `playworld.py:27` sets
  `game.action = 0x2000` from `local_click`; scripts read it via `eval_var`
  code `0x11`. Nothing records which object the player meant.
- Facing, where it matters, is script-side only: `eval_var.py:21 get_pos_rel`
  (code `0x12`) buckets beta into quadrants. The engine never enforces it.
- There is no interaction radius as data anywhere.

### Event loop

`__main__.py:222 run()` owns the single pump. Mouse `MOUSEBUTTONDOWN` is
routed through `render.py:77 window_to_logical` into `__main__.py:137
route_mouse`, which returns immediately when `game.active_modal is None` —
so clicks during PLAY are currently discarded. That is the insertion point.

## Decisions (agreed with user)

1. **Cover-zone navmesh**, not steering-only and not a blocked-progress
   hybrid. The data is already parsed and the probe confirms it is floor.
2. **Explicit `pending_target`** for object interaction, not
   walk-to-contact-and-hope. This is the accessibility win.
3. **Mouse-only by default, keyboard opt-in.** Both input paths coexist;
   tank controls remain live and tested.
4. **New `track_mode == 4`**, plus a joyd mirror. Mode 4 is a generalization
   of the existing follow mode (turn *while* walking), not invented movement.
   Approach 2 (synthesizing joyd into `_process_track_manual`) was rejected:
   `gere_manual_rot` pivots at the tank rotation rate before forward motion
   accumulates, producing autopilot-driving-a-tank, which is the wrong feel
   for an accessibility refactor.

## Architecture

Three new modules, all pygame-free, so the `AGENTS.md` layer rule holds by
construction.

### `PyAitD/navmesh.py`

- `build_room_mesh(floor, room_idx, agent_half) -> RoomMesh` — union the
  cover polygons from every camera viewing the room (x10 into room-scale),
  rasterize at `GRID_STEP`, mark a cell walkable when its centre is inside
  the union **and** the agent ZV centred there clears every hard col by
  `cube_intersect` on all three axes, with no type filtering.
- No type filtering is deliberate: it makes the mesh unable to disagree with
  `actors.py:17 check_hard_col` about what is solid, and doorways stay open
  for free (all 95 type-4 boxes miss the hero Y band).
- Hero ZV and hard cols are both AABBs, so expanding the box by the agent
  half-extent is **exact**, not conservative. Match `cube_intersect`'s strict
  inequalities at the edges.
- Agent footprint is `max(x_half, z_half)` = 266. The hero ZV is
  beta-dependent (`life_ops.py:273` rebuilds it via `_zv_rot`), so a
  rotation-invariant extent gives one mesh per room instead of one per facing.
- `GRID_STEP = 100` room units (~5 cells across the hero), a tunable constant
  with a floor-0 golden.
- Containment uses FITD's own predicate. The union is rasterized by
  **vectorizing `world.py:141 test_cross_product` itself** — the two-ray
  test `is_in_poly` is built from — not by a generic even-odd polygon fill.
  This is not a performance detail: a generic fill was measured against
  `is_in_poly` on the floor-0 grid and disagreed on 64 of 21291 cells,
  in both directions, all on boundary cells, because FITD's `flag == 3`
  two-ray test has its own degenerate-case behaviour. Vectorizing the real
  predicate makes agreement exact by construction; measured 0 mismatches on
  floors 0, 2 and 6, with a 51 ms build for the largest room in the game
  (floor 6 room 6, 281x243 cells). Blocking is O(boxes) NumPy masking;
  only the union fill touches every cell.
- `find_path(mesh, start, goal) -> [waypoints]` — A* then string-pull, so
  the follower receives a handful of waypoints rather than a staircase.
- Meshes cached per `(floor, room)`, built on room entry.

### `PyAitD/picking.py`

- The floor plane under a pinhole projection maps to the image by a
  homography; `CameraState.project` is a genuine pinhole (anisotropic
  `focal2`/`focal3`, divide by `z + focal1`). The fixed-point path quantizes
  it only at sub-pixel scale.
- The homography is **fitted from four projected correspondences** using the
  engine's own forward path, not derived analytically from `alpha/beta/gamma`
  and `COS_TABLE`. Deriving it means re-implementing the `>>16 ... <<1`
  composition in float and risking a silent mismatch; fitting uses the real
  pipeline as ground truth. The cover vertices are projected anyway for the
  point-in-polygon test, so the four extreme valid projected vertices give a
  well-conditioned quad at no extra cost.
- **The floor plane is the hero's current `world_y`, not `y = 0`.** The hero
  stands at 0 on floors 0 and 2 but at -1250 on floor 1 and -4010 on floor 6.
  Cover zones carry no Y, so the mesh is a single-height surface per room;
  the homography cache keys on `(camera, room, floor_y)`.
- `pick_floor(logical_pos, ...) -> (world_x, world_z) | None`. Only the
  current camera's polygons are on screen. If a click falls inside two,
  recover the world point and test it against that polygon with `is_in_poly`
  — self-consistency disambiguates at no cost.
- A floor click landing on a blocked cell **snaps to the nearest walkable
  cell** within a radius rather than being rejected.
- `pick_actor(logical_pos, draw_list) -> actor_idx | None` consumes what the
  renderer already computed: `_scene_frame` additionally returns
  `[(actor_idx, screen_bbox)]` in painter order (farthest first), so the last
  hit is topmost and nearest. `picking.py` stays pure — it consumes bboxes
  rather than re-skinning.
- **Padded bounding boxes, deliberately**, not per-primitive polygon tests:
  a larger forgiving target is the point, and the accessibility contract
  forbids requiring precise pointing. The padding is a tunable constant
  pinned by a golden, like `GRID_STEP` and the snap radius.
- Filter to genuinely interactable actors (`AF_FOUNDABLE`, or a world object
  with a `found_life`); exclude the hero.
- Click priority: interactable actor -> floor polygon -> no-op.

### `PyAitD/navigate.py`

The per-tick follower: read intent, re-path if stale, decide steering,
mirror the joyd bits. Consumed by `process_track`'s new mode 4.

### Changed modules

- `tracks.py` — `process_track` gains a `track_mode == 4` branch applying the
  follower's decision through `_turn_toward` / `speed`. Mode 1 is untouched.
- `effects.py` — `NavIntent(dest_x, dest_z, room, target_object_idx,
  waypoints)`, typed and on the pure side.
- `playworld.py:23 apply_play_input` — computes the follower decision once
  per tick and writes both the mirrored `local_joyd` (for scripts reading
  `eval_var` code `0x13`) and the stored steering decision that mode 4
  applies. **No tick-order change**, so the FITD `mainLoop` ordering claim in
  `playworld.py` stays true.
- `interaction.py` — `apply_click_intent` and the arrival dispatch, next to
  `apply_found_result`, which already owns "UI result becomes world
  transition". Also the gate widening below.
- `__main__.py` — route `MOUSEBUTTONDOWN` during PLAY (today dropped),
  and return the actor draw list from `_scene_frame`.
- `ui.py` — hover/cursor feedback only, driven by a per-motion pick. No
  state mutation, per the layer rule.

### The gate that would otherwise break silently

`interaction.py:220` gates contact pickup on `actor.track_mode == 1`. With
the hero in mode 4, `AF_FOUNDABLE` contact stops firing with no error —
pickups just quietly stop working. The gate becomes "is the
player-controlled actor" (`track_mode in (1, 4)`, or compare against
`current_camera_target_actor`). FITD's intent with `== 1` was "manually
controlled", so widening is faithful to intent.

### Arrival dispatch

On arrival, by object kind:

- **Foundable** -> `request_found(game, clicked_idx, 0)` with the *clicked*
  index. `interaction.py:127` already takes an `object_idx`, so this only
  chooses the argument instead of letting ZV overlap choose it. Its debounce
  (`world.track_number`, 300 ticks), weight check and `forced_refuse` carry
  over untouched.
- **Otherwise** -> set `game.action = 0x2000` for one tick, exactly as the
  action button does, and let the target's LIFE script react via `eval_var`
  code `0x11`.

### Fidelity dial not turned

The action bit stays **globally visible**. Making only the targeted actor
see it would change how every script reads `0x11`. The precision bought here
is "the player is standing at the object they actually clicked", which
removes most of the ambiguity without touching script semantics. Narrowing
the bit is a separate, later decision if play shows it is insufficient.

### Cross-room clicks

A camera's `viewed_rooms` can include neighbours, so a click can land in an
adjacent room's cover polygon. One hop: path to the type-0 `sce_zone`
leading toward the clicked room, cross, re-path on arrival — mirroring what
`get_room_link` already does for follow mode.

### Degraded mode

The follower **degrades to direct steering** — straight-line `_turn_toward`
at the click with no path, which is what mode 4 does between waypoints anyway
— in exactly three cases:

1. the room's mesh has zero walkable cells (cave floors, see Risks);
2. the hero's own cell is not walkable (spawned inside a blocked cell);
3. `find_path` returns no route to the goal (the goal is in a different
   component, e.g. a doorway narrower than the agent extent).

The mouse stays usable everywhere; it is just less capable where the mesh is
not. All three are logged conditions, not errors.

## Invariants

- `navmesh.py`, `picking.py`, `navigate.py` import no pygame, ModernGL,
  `PyAitD.ui`, or `PyAitD.render`.
- `ui.py` never mutates world/actor/inventory/LIFE/nav state.
- `__main__.py` keeps one event pump and one present per frame.
- The mesh's notion of "solid" is `cube_intersect` against `room.hard_cols`
  — the same predicate `check_hard_col` uses. It is never allowed to drift.
- `play_tick`'s FITD `mainLoop` ordering is unchanged; the follower runs
  inside the existing input-snapshot step.
- Mode 1 (tank) behaviour is byte-for-byte unchanged; all existing goldens
  hold.

## Error handling

- Mesh build for a room with no cover polygons: return an empty mesh and log
  it. Not an error — four rooms legitimately have no camera.
- Mesh build failure (malformed cover data): raise with floor, room, and
  camera index, per the house fail-fast convention.
- Homography fit with fewer than four validly projecting vertices: return
  `None` from `pick_floor` for that camera and log once; clicks fall through
  to no-op rather than producing a wrong destination.
- Intent invalidation — target taken or despawned (`obj_index == -1`), room
  changed underneath, or a modal open — aborts the dispatch silently. The
  `game.active_modal is None` check is the established pattern.
- Modal opens mid-walk: clear the intent, matching the existing input flush
  at `__main__.py` modal entry. Do **not** auto-resume on dismiss.

## Testing

Layer purity extends the existing subprocess probe at
`tests/test_playworld.py:15` (a static import walk cannot substitute — the
deferred `from PyAitD.ui import FoundResult` in `interaction.py` makes pygame
look statically reachable). `navmesh`, `picking`, `navigate` each get the
same check.

Goldens pinned from real data, never re-derived by guessing:

- **navmesh** — floor 0 room 0 walkable cell count at `GRID_STEP=100` with
  half-extent 266; component count; hero start cell walkable; both
  `sce_zones` in that component.
- **vectorization safety net** — NumPy union fill equals `is_in_poly`
  cell-for-cell across the entire floor-0 grid.
- **blocking agrees with the engine** — sampled cells match
  `check_hard_col(hero_zv_at_cell, room.hard_cols)`.
- **doorways stay open** — all 95 type-4 boxes are non-blocking under the 3D
  rule, so no future change to the blocking predicate can silently seal every
  door.
- **picking** — round-trip `pick_floor(project(p)) ~= p` for sampled floor
  points across all five floor-0 cameras, pinned tolerance; clicks outside
  every polygon return `None`.
- **navigate** — given a waypoint list and actor pose, the steering decision
  and mirrored joyd bits are deterministic.

Headless integration through `play_tick`, following `test_play_loop.py`'s
patch-the-module-global pattern (no window, no `SDL_VIDEODRIVER`):

- set an intent to a known floor-0 destination, run N ticks, assert arrival
  within threshold and that `local_joyd` was non-zero en route;
- hero in mode 4 walks into the known foundable and `ShowFound` still opens
  — the regression test for the `interaction.py:220` gate;
- click-intent dispatch asserts the modal carries the *clicked* `object_idx`,
  not whatever ZV was touched.

`make prove-mouse`, alongside `prove` and `prove-m3b`: build the mesh for
every camera-visible room on every floor, assert it builds, report walkable
counts. This is the regression net for the hard-col type-semantics class of
bug. It **reports** near-empty cave rooms rather than failing on them.

Not coverable by tests: mode-4 feel (turn-while-walking vs tank pivot) needs
`make run` and a manual evidence doc, following the
`docs/m3b-interaction-proof.md` precedent.

## Assumptions

- The hero's LIFE script calls LM_DO_MOVE every tick during normal play, as
  it does today; mode 4 inherits whatever cadence mode 1 has.
- `GRID_STEP = 100` and the snap radius are tunable constants; their initial
  values are pinned by goldens and may be retuned with the goldens.
- The homography tolerance established on floor 0 generalizes to other
  floors' cameras. Only floor 0 boots in this port today, so this is
  unverified beyond it.
- Keyboard mode remains the fallback anywhere mouse navigation degrades,
  satisfying the accessibility contract's "every operation has a keyboard
  route".

## Risks

- **Climbable-wall floors.** ~~On floors 5 and 6, type-3 slabs tile most of
  the cover area, so a mesh built with the engine's blocking rule comes out
  near-empty on both.~~ **Corrected after implementation, from `make
  prove-mouse` over real data.** The prediction above extrapolated from a
  global box count (194 type-3 boxes, 193 overlapping the hero Y band) and
  was pessimistic. Measured reality: exactly **one** room in the whole game
  builds an empty mesh — floor 5 room 3. Type-3 boxes are genuinely blocked
  on both floors (floor 5: 116 boxes, 115 in the hero Y band; floor 6: 78,
  all 78), verified by independent re-measurement; the difference is
  geometric, not a code defect. Type-3 removes 55-100% of floor 5's cover
  area per room but only 32-65% of floor 6's, so floor 6 stays navigable
  throughout. The degraded direct-steering mitigation still covers the one
  empty room, and climbable-wall traversal remains later `hard_col == 255`
  work.

  The earlier estimate came from a probe that ignored the Y axis and sampled
  at a finer grid step than the shipped `GRID_STEP = 100`; both differences
  pushed it pessimistic.
- **Homography divergence** from the fixed-point path on cameras with
  extreme angles. Bounded by the round-trip test on floor 0; other floors
  are unverified until their rooms boot.
- **Multi-component rooms.** Several rooms split into 2-5 components under
  the engine's blocking rule. Some splits are real walls; others may be
  doorways narrower than the agent extent, where the engine's collision
  slide would let the player through but A* will not route. Mitigation:
  case 3 of degraded mode (direct steering when `find_path` returns no
  route), which lets the engine's own slide do what A* would not; revisit if
  play shows dead ends.
- **Mask-unaware picking.** Clicking a foreground beam that occludes an
  actor still selects the actor. Deferred deliberately.
- **The 18 nonsense-typed hard cols** suggest the type field may be misread
  for some records. Inert for this work (none overlap hero Y), but it is a
  latent parser question.
