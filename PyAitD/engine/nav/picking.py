# SPDX-License-Identifier: GPL-2.0-only
"""Screen -> world picking for mouse input. Pure math: no pygame, no Renderer.

The floor is a plane and CameraState.project is a real pinhole projection
(anisotropic focals, divide by z + focal1), so plane -> screen is a homography.
It is *fitted* from four points pushed through the engine's own forward path
rather than derived from alpha/beta/gamma and COS_TABLE, so it cannot drift
from the fixed-point pipeline it has to agree with.
"""
from collections import namedtuple

import numpy as np

from PyAitD.engine.nav.navmesh import COVER_SCALE, cover_polys
from PyAitD.engine.space.world import CameraState, transform_point


def project_floor_point(state, wx, wy, wz):
    """World point -> logical 320x200 screen, via the real skin() path."""
    x = wx - state.x
    y = wy
    z = wz - state.z
    if y > 10000:
        return None
    y -= state.y
    x, y, z = transform_point(x, y, z, state)
    sx, sy, depth = state.project(x, y, z)
    if depth <= 50:
        return None
    return (sx, sy)


def _homography(src, dst):
    # 8-parameter fit from four correspondences, solved by SVD
    rows = []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    _u, _s, vt = np.linalg.svd(np.array(rows, dtype=float))
    matrix = vt[-1].reshape(3, 3)
    if abs(matrix[2, 2]) < 1e-12:
        return None
    return matrix / matrix[2, 2]


def _quad_of(poly_world, state, floor_y):
    # Any four non-collinear coplanar points define the same homography (a
    # pinhole projection of a plane is a genuine projective map), so the
    # selection exists only for conditioning: farthest-point sampling in
    # WORLD space (world coords don't suffer near-clip projection blowups)
    # picks a well-spread quad for any polygon shape. The old heuristic —
    # vertices nearest the world-bbox extreme corners — collapsed on
    # L-shaped/hexagonal polygons, where two bbox corners snap to the same
    # vertex and the polygon was skipped entirely.
    projected = [
        (world, project_floor_point(state, world[0], floor_y, world[1]))
        for world in poly_world
    ]
    usable = [(w, s) for w, s in projected if s is not None]
    if len(usable) < 4:
        return None
    chosen = [usable[0]]
    while len(chosen) < 4:
        pick = max(
            (ws for ws in usable if ws not in chosen),
            key=lambda ws: min(
                (ws[0][0] - c[0][0]) ** 2 + (ws[0][1] - c[0][1]) ** 2
                for c in chosen
            ),
            default=None,
        )
        if pick is None:
            return None  # degenerate polygon: fewer than four distinct vertices
        chosen.append(pick)
    return [w for w, _s in chosen], [s for _w, s in chosen]


def floor_homography(state, poly_world, floor_y):
    """3x3 mapping (world_x, world_z) on the floor plane -> logical screen."""
    quad = _quad_of(poly_world, state, floor_y)
    if quad is None:
        return None
    return _homography(quad[0], quad[1])


def _apply(matrix, x, y):
    vec = matrix @ np.array([x, y, 1.0])
    if abs(vec[2]) < 1e-12:
        return None
    return (vec[0] / vec[2], vec[1] / vec[2])


def _camera_state_global(floor, room_idx, global_cam_idx):
    # the camera is addressed globally, but the transform is built from the
    # ORIGIN OF THE ROOM BEING PICKED — each room has its own coordinate space
    room = floor.rooms[room_idx]
    camera = floor.cameras[global_cam_idx]
    return CameraState.from_camera(
        camera, room.world_x, room.world_y, room.world_z,
    ).angles()


def ray_box_hit(origin, point, box):
    """Parametric t in (0, 1) where the segment origin -> point first enters
    the axis-aligned box, or None. A slab test per axis; an origin already
    inside the box is not an occlusion (t would be 0), a point inside it is
    (the segment enters before reaching it)."""
    t_in, t_out = 0.0, 1.0
    for o, p, lo, hi in (
        (origin[0], point[0], box.x1, box.x2),
        (origin[1], point[1], box.y1, box.y2),
        (origin[2], point[2], box.z1, box.z2),
    ):
        d = p - o
        if abs(d) < 1e-9:
            if o < lo or o > hi:
                return None
            continue
        t0, t1 = (lo - o) / d, (hi - o) / d
        if t0 > t1:
            t0, t1 = t1, t0
        t_in, t_out = max(t_in, t0), min(t_out, t1)
        if t_in > t_out:
            return None
    return t_in if 0.0 < t_in < 1.0 else None


def to_room_frame(floor, from_room, to_room, x, y, z):
    """Re-frame a room-scale point from one room's origin to another's, with
    FITD's asymmetric signs (x minus, y plus, z plus -- world.room_delta)."""
    src, dst = floor.rooms[from_room], floor.rooms[to_room]
    dx = 10 * (dst.world_x - src.world_x)
    dy = 10 * (dst.world_y - src.world_y)
    dz = 10 * (dst.world_z - src.world_z)
    return (x - dx, y + dy, z + dz)


def _in_band(box, agent):
    if agent is None:
        return True
    _half, y0, y1 = agent
    return y0 < box.y2 and box.y1 < y1


_Volume = namedtuple("_Volume", "x1 x2 y1 y2 z1 z2")
_ENTRY_EPS = 1e-9   # a box flush with the volume's own face is entered at
                    # exactly the entry parameter; it is the shell, not an
                    # occluder inside it


def room_volume(floor, room_idx):
    """The room's own axis-aligned volume: the bounding box of its hard cols.

    A room's perimeter walls ARE hard cols, so this box is the room's shell,
    outer faces included -- which is what makes it the right clip for
    floor_point_visible: the wall the camera looks over is entered exactly
    where the segment enters this volume, and everything strictly deeper is
    inside the room. None when the room carries no hard cols at all.
    """
    boxes = floor.rooms[room_idx].hard_cols
    if not boxes:
        return None
    return _Volume(
        min(b.x1 for b in boxes), max(b.x2 for b in boxes),
        min(b.y1 for b in boxes), max(b.y2 for b in boxes),
        min(b.z1 for b in boxes), max(b.z2 for b in boxes),
    )


def floor_point_visible(floor, global_cam_idx, room_idx, x, y, z, agent=None):
    """True when no hard col of any room this camera views lies on the
    segment from the camera to the point (given in room_idx's frame), AFTER
    that segment has entered room_idx's own volume.

    Each viewed room's boxes are tested in that room's own frame: the camera
    is rebuilt there (its position is (state.x, state.y, state.z), what
    project_floor_point subtracts) and the point is re-framed with
    to_room_frame. `agent` = (half, y0, y1) keeps only boxes overlapping the
    agent's Y band, navmesh._subtract_hard_cols's rule, so a room link the
    hero can walk through is not a wall.

    The clip at room_volume is what keeps the test sound for a camera placed
    OUTSIDE the room it films -- which is most of this game's cameras: they
    sit behind or above the perimeter wall, so the segment to ANY point in
    the room crosses that wall (and often a neighbouring room's wall) before
    it reaches the floor. Counting those boxes refused every pixel of 87 of
    the 274 camera slots that have pickable floor. Boxes entered strictly
    after the volume -- interior furniture, an inner wall -- still occlude.
    The parametric t is comparable across rooms because every room's frame is
    the same segment translated.
    """
    entry = 0.0
    volume = room_volume(floor, room_idx)
    if volume is not None:
        state = _camera_state_global(floor, room_idx, global_cam_idx)
        hit = ray_box_hit((state.x, state.y, state.z), (x, y, z), volume)
        if hit is not None:
            entry = hit
    viewed = [vr.viewed_room_idx for vr in floor.cameras[global_cam_idx].viewed_rooms]
    rooms = [room_idx] + [r for r in viewed if r != room_idx and r < len(floor.rooms)]
    for other in rooms:
        state = _camera_state_global(floor, other, global_cam_idx)
        origin = (state.x, state.y, state.z)
        target = to_room_frame(floor, room_idx, other, x, y, z)
        for box in floor.rooms[other].hard_cols:
            if not _in_band(box, agent):
                continue
            hit = ray_box_hit(origin, target, box)
            if hit is not None and hit > entry + _ENTRY_EPS:
                return False
    return True


def pick_floor_in_room(logical_pos, floor, room_idx, global_cam_idx, floor_y):
    """Logical click -> room-scale (x, z) in room_idx's own coordinate space.

    Only the current camera's polygons are on screen. When a click falls inside
    more than one, the recovered point is tested against the polygon it came
    from, and self-consistency picks the right one at no extra cost.
    """
    state = _camera_state_global(floor, room_idx, global_cam_idx)
    for poly in cover_polys(floor, room_idx):
        world = [(x * COVER_SCALE, z * COVER_SCALE) for x, z in poly]
        matrix = floor_homography(state, world, floor_y)
        if matrix is None:
            continue
        try:
            inverse = np.linalg.inv(matrix)
        except np.linalg.LinAlgError:
            continue
        recovered = _apply(inverse, float(logical_pos[0]), float(logical_pos[1]))
        if recovered is None:
            continue
        wx, wz = int(round(recovered[0])), int(round(recovered[1]))
        forward = _apply(matrix, wx, wz)
        if forward is None:
            continue
        if abs(forward[0] - logical_pos[0]) > 2 or abs(forward[1] - logical_pos[1]) > 2:
            continue  # the fit does not explain this pixel
        if _point_in_world_poly(wx, wz, world):
            return (wx, wz)
    return None


def pick_floor(logical_pos, floor, room_idx, cam_slot, floor_y):
    """Room-slot form. Kept for callers that already know the room."""
    global_cam_idx = floor.rooms[room_idx].camera_indices[cam_slot]
    return pick_floor_in_room(logical_pos, floor, room_idx, global_cam_idx, floor_y)


def viewed_floor_y(floor, hero_room, room_idx, floor_y):
    """The floor plane height to pick room_idx at when the hero stands at
    floor_y in hero_room: the hero's own height in the hero's room, and that
    height re-framed into a viewed room's origin otherwise, so a lower or
    higher neighbouring room is picked at its own depth."""
    if room_idx == hero_room:
        return floor_y
    return to_room_frame(floor, hero_room, room_idx, 0, floor_y, 0)[1]


OCCLUDE_BY_DEFAULT = False
"""Whether the shipped floor pick refuses hits hidden behind a hard col.

OFF, and the census in tools/prove_mouse.py is why. Hard cols are collision
proxies, not the painted scene: whole rooms are modelled as a handful of
chunky full-height blocks, and this game's cameras mostly sit outside the
room they film. Clipping the occlusion segment at the room's own volume (see
floor_point_visible) fixed the camera-outside-the-room case and took the
camera slots with NO clickable floor pixel at all from 87 of 274 down to 14 --
but 14 dead cameras is 14 places the player cannot walk with the mouse, and
that is worse than the "the floor behind that crate is clickable" it buys.

Everything the filter needs stays here, tested and one flag from live:
ray_box_hit, room_volume, floor_point_visible, `occlude=True`, and the
whole-game census gate in tests/test_prove_mouse.py, which fails the moment
this flag turns on while any camera slot would go dark. Turning it on again
is a data job -- real occluder volumes for the painted scene -- not a flag
flip.
"""


def pick_floor_any_room(
        logical_pos, floor, hero_room, cam_slot, floor_y, *,
        occlude=OCCLUDE_BY_DEFAULT, agent=None,
):
    """Pick across every room this camera views. Returns (x, z, room) or None.

    The hero's own room is tried first: walking inside the current room never
    needs a transition, so it wins any overlap. With `occlude` a floor hit
    whose camera ray crosses a hard col (a wall, a piece of furniture) is
    refused rather than returned as "the floor behind it"; `occlude=False`
    is the pre-occlusion pick, the baseline the proof tool and the tests
    compare against, and -- see OCCLUDE_BY_DEFAULT -- what ships.
    """
    global_cam_idx = floor.rooms[hero_room].camera_indices[cam_slot]
    viewed = [vr.viewed_room_idx for vr in floor.cameras[global_cam_idx].viewed_rooms]
    ordered = [hero_room] + [r for r in viewed if r != hero_room]
    for room_idx in ordered:
        if room_idx >= len(floor.rooms):
            continue
        room_floor_y = viewed_floor_y(floor, hero_room, room_idx, floor_y)
        hit = pick_floor_in_room(logical_pos, floor, room_idx, global_cam_idx, room_floor_y)
        if hit is None:
            continue
        if occlude and not floor_point_visible(
                floor, global_cam_idx, room_idx, hit[0], room_floor_y, hit[1], agent,
        ):
            return None
        return (hit[0], hit[1], room_idx)
    return None


def _point_in_world_poly(x, z, world_poly):
    # even-odd test in room-scale, used only to attribute a click to the polygon
    # whose homography produced it; the mesh, not this, decides walkability
    inside = False
    count = len(world_poly)
    for k in range(count):
        x1, z1 = world_poly[k]
        x2, z2 = world_poly[(k + 1) % count]
        if (z1 > z) != (z2 > z) and z1 != z2:
            crossing = (x2 - x1) * (z - z1) / (z2 - z1) + x1
            if x < crossing:
                inside = not inside
    return inside


ACTOR_PICK_PAD = 3       # logical pixels of slack; the accessibility contract
                         # forbids requiring precise pointing
_CULL_MAGNITUDE = 9000   # skel.skin writes -10000 for culled vertices, but
                         # CameraState.project can also emit legitimately huge
                         # values of EITHER sign near depth <= 50 (it divides
                         # by depth), so the test must be symmetric, not a
                         # one-sided floor
_LOGICAL_W = 320         # the logical surface pick_floor/render also target
_LOGICAL_H = 200


def _clamp(value, lo, hi):
    return max(lo, min(value, hi))


def actor_bbox(result, pad=ACTOR_PICK_PAD):
    """Screen-space bounding box of a skinned actor, or None if fully culled.

    A vertex is unusable when either coordinate is extreme in magnitude on
    either axis: skel.skin's cull sentinel (-10000, -10000, -10000) is one
    such case, but a near-clip projection (depth just above 50) can also
    divide out to a huge value of either sign, so the test can't just be a
    negative floor. Padding is applied before the box is clamped to the
    320x200 logical surface, so the pad can't push it back off-surface, and
    the clamp also backstops any near-clip vertex that slips past the
    magnitude test.
    """
    usable = [
        p for p in result.points
        if abs(p[0]) < _CULL_MAGNITUDE and abs(p[1]) < _CULL_MAGNITUDE
    ]
    if not usable:
        return None
    xs = [p[0] for p in usable]
    ys = [p[1] for p in usable]
    x0 = _clamp(int(min(xs)) - pad, 0, _LOGICAL_W)
    y0 = _clamp(int(min(ys)) - pad, 0, _LOGICAL_H)
    x1 = _clamp(int(max(xs)) + pad, 0, _LOGICAL_W)
    y1 = _clamp(int(max(ys)) + pad, 0, _LOGICAL_H)
    return (x0, y0, x1, y1)


def pick_actor(logical_pos, draw_list):
    """Topmost actor under the click; draw_list is farthest-first painter order.

    Boxes may be the original inclusive (x0, y0, x1, y1) bounds or a
    rectangle-like object with collidepoint(), keeping pygame at the caller.
    """
    x, y = logical_pos
    for actor_idx, box in reversed(draw_list):
        if box is None:
            continue
        if hasattr(box, "collidepoint"):
            hit = box.collidepoint(logical_pos)
        else:
            hit = box[0] <= x <= box[2] and box[1] <= y <= box[3]
        if hit:
            return actor_idx
    return None


SNAP_BUDGET_PX = 8   # how far, on screen, a snapped walk may land from the
                     # pointer: past this the pick is refused, never a surprise


def project_room_point(floor, hero_room, cam_slot, room_idx, x, y, z):
    """A room-frame point on the logical screen under the hero room's camera
    slot, or None when it is behind the near clip or off the 320x200 frame."""
    global_cam_idx = floor.rooms[hero_room].camera_indices[cam_slot]
    state = _camera_state_global(floor, room_idx, global_cam_idx)
    screen = project_floor_point(state, x, y, z)
    if screen is None:
        return None
    if not (0 <= screen[0] < _LOGICAL_W and 0 <= screen[1] < _LOGICAL_H):
        return None
    return screen


def visible_accept(
        floor, hero_room, cam_slot, room_idx, floor_y, agent=None, *,
        occlude=OCCLUDE_BY_DEFAULT,
):
    """Candidate filter: the cell must be visible from the camera on screen.

    `occlude` tracks the shipped floor pick (OCCLUDE_BY_DEFAULT). The two
    must agree: a filter that kept refusing approach cells while floor picks
    ignored occlusion would make objects unreachable in exactly the rooms
    whose floor is freely clickable. With it off every candidate is accepted
    and approach_cell keeps its pre-occlusion reach.

    A camera that never renders room_idx has nothing meaningful to say about
    a point in it: the segment from the camera to a cell in an unrendered
    room crosses whatever hard cols happen to lie between them by
    construction, not because anything actually occludes the view, so every
    candidate would be refused and a real interaction (approaching an object
    in a room the current camera does not view) would turn into blocked.
    Every candidate is accepted in that case; the filter only applies within
    a room the camera actually views.
    """
    if not occlude:
        return lambda x, z: True
    global_cam_idx = floor.rooms[hero_room].camera_indices[cam_slot]
    viewed = [vr.viewed_room_idx for vr in floor.cameras[global_cam_idx].viewed_rooms]
    if room_idx not in viewed:
        return lambda x, z: True

    def accept(x, z):
        return floor_point_visible(floor, global_cam_idx, room_idx, x, floor_y, z, agent)
    return accept


def snap_accept(
        floor, hero_room, cam_slot, room_idx, floor_y, logical_pos, agent=None,
        budget=SNAP_BUDGET_PX,
):
    """Candidate filter for a snapped walk: on screen within `budget` logical
    pixels of the pointer on both axes, and visible from the camera.

    The budget always applies; the visibility half follows visible_accept,
    so while OCCLUDE_BY_DEFAULT is off this is the budget alone."""
    visible = visible_accept(floor, hero_room, cam_slot, room_idx, floor_y, agent)

    def accept(x, z):
        screen = project_room_point(floor, hero_room, cam_slot, room_idx, x, floor_y, z)
        if screen is None:
            return False
        if (abs(screen[0] - logical_pos[0]) > budget
                or abs(screen[1] - logical_pos[1]) > budget):
            return False
        return visible(x, z)
    return accept
