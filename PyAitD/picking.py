# SPDX-License-Identifier: GPL-2.0-only
"""Screen -> world picking for mouse input. Pure math: no pygame, no Renderer.

The floor is a plane and CameraState.project is a real pinhole projection
(anisotropic focals, divide by z + focal1), so plane -> screen is a homography.
It is *fitted* from four points pushed through the engine's own forward path
rather than derived from alpha/beta/gamma and COS_TABLE, so it cannot drift
from the fixed-point pipeline it has to agree with.
"""
import numpy as np

from PyAitD.navmesh import COVER_SCALE, cover_polys
from PyAitD.world import CameraState, transform_point


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
    # four extreme, validly-projecting vertices give a well-conditioned fit
    projected = [
        (world, project_floor_point(state, world[0], floor_y, world[1]))
        for world in poly_world
    ]
    usable = [(w, s) for w, s in projected if s is not None]
    if len(usable) < 4:
        return None
    xs = [w[0] for w, _s in usable]
    zs = [w[1] for w, _s in usable]
    corners = [
        (min(xs), min(zs)), (max(xs), min(zs)),
        (max(xs), max(zs)), (min(xs), max(zs)),
    ]
    chosen = []
    for target in corners:
        pick = min(
            usable,
            key=lambda ws: (ws[0][0] - target[0]) ** 2 + (ws[0][1] - target[1]) ** 2,
        )
        if pick in chosen:
            return None  # degenerate polygon: fewer than four distinct corners
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


def _camera_state(floor, room_idx, cam_slot):
    room = floor.rooms[room_idx]
    camera = floor.cameras[room.camera_indices[cam_slot]]
    return CameraState.from_camera(
        camera, room.world_x, room.world_y, room.world_z,
    ).angles()


def pick_floor(logical_pos, floor, room_idx, cam_slot, floor_y):
    """Logical 320x200 click -> room-scale (x, z) on the floor, or None.

    Only the current camera's polygons are on screen. When a click falls inside
    more than one, the recovered point is tested against the polygon it came
    from, and self-consistency picks the right one at no extra cost.
    """
    state = _camera_state(floor, room_idx, cam_slot)
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
    """Topmost interactable actor under the click. draw_list is painter order."""
    x, y = logical_pos
    for actor_idx, box in reversed(draw_list):
        if box is None:
            continue
        if box[0] <= x <= box[2] and box[1] <= y <= box[3]:
            return actor_idx
    return None
