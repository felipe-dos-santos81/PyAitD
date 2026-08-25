# SPDX-License-Identifier: GPL-2.0-only
"""Per-frame scene description: the layer between game assets and any renderer.

Pure and pygame/GL free. The logical FITD projection (skel.skin) is kept for
picking, masks and every simulation contract; float geometry is added beside
it so the new backends can rasterise at an integer-scaled internal
resolution with smooth shading."""
from dataclasses import dataclass

import numpy as np

from PyAitD.actors import anim_player_for, sort_actor_indices
from PyAitD.asset_resolver import ImageAsset
from PyAitD.cos_table import sin_cos
from PyAitD.geometry import BodyGeometry, pose_geometry
from PyAitD.mask_geometry import MaskDraw
from PyAitD.picking import actor_bbox
from PyAitD.skel import RenderResult, skin
from PyAitD.world import SCREEN_CENTER_X, SCREEN_CENTER_Y, CameraState

_SENTINEL = np.array([-10000.0, -10000.0, -10000.0])


@dataclass(frozen=True)
class CameraView:
    """Float twin of skel.skin's per-vertex path (world.transform_point +
    CameraState.project), for the new backends to rasterise at high
    resolution. `state` must already have `.angles()` applied."""
    state: CameraState

    def camera_space(self, world_xyz):
        """(N,3) world -> ((N,3) camera-space, (N,) far-culled) before projection.

        Mirrors skel.skin: the y > 10000 cull is evaluated on world y, before
        camera.y is subtracted."""
        cam = self.state
        pts = np.array(world_xyz, dtype=np.float64).reshape(-1, 3)
        pts[:, 0] -= cam.x
        pts[:, 2] -= cam.z
        far = pts[:, 1] > 10000
        pts[:, 1] -= cam.y
        x, y, z = pts[:, 0], pts[:, 1], pts[:, 2]
        if cam._use_y:
            s, c = sin_cos(cam._use_y)
            x, z = x * s - z * c, x * c + z * s
        if cam._use_x:
            s, c = sin_cos(cam._use_x)
            y, z = y * s - z * c, y * c + z * s
        if cam._use_z:
            s, c = sin_cos(cam._use_z)
            x, y = x * s - y * c, x * c + y * s
        return np.stack([x, y, z], axis=1), far

    def project(self, world_xyz):
        """(N,3) world -> (N,3) [sx, sy, depth] logical px; culled vertices
        (far or depth <= 50) become the (-10000, -10000, -10000) sentinel.

        This is a continuous float twin of skel.skin, not a bit-exact
        reproduction of it. skel.skin's Y/X/Z rotation chain (via
        world.transform_point) truncates at each stage through
        `trunc_div(..., 65536) << 1`; that truncation is bounded by a
        small, roughly depth-independent number of FITD world units
        (measured max ~6 across a wide distance sweep -- see
        test_camera_view_project_parity_scales_with_distance in
        tests/test_scene.py), but perspective division amplifies it as
        roughly (world_error * focal) / depth, so the on-screen pixel
        divergence from skel.skin shrinks as distance from the camera
        grows: measured worst case ~12px within ~100 units of the camera,
        well under 1px beyond ~2000 units. This is intended and is not a
        formula bug -- the float path is the more numerically accurate of
        the two. skel.skin (and its bbox-derived draw_list) stays the
        sole authority for picking, masks and the mouse contract;
        CameraView is a parallel, higher-precision path for rendering
        only (tasks 6-8), and the two can legitimately disagree on
        whether a vertex right at the depth<=50 cull boundary is visible
        at all."""
        cam = self.state
        pts, far = self.camera_space(world_xyz)
        depth = pts[:, 2] + cam.focal1
        culled = far | (depth <= 50)
        safe_depth = np.where(culled, 1.0, depth)
        sx = pts[:, 0] * cam.focal2 / safe_depth + SCREEN_CENTER_X
        sy = pts[:, 1] * cam.focal3 / safe_depth + SCREEN_CENTER_Y
        out = np.stack([sx, sy, depth], axis=1)
        out[culled] = _SENTINEL
        return out


@dataclass(frozen=True)
class ActorDraw:
    index: int
    geometry: BodyGeometry
    position: tuple[float, float, float]
    room: int
    zv: tuple
    logical: RenderResult
    mask_ids: tuple[int, ...]


@dataclass(frozen=True)
class FrameDescription:
    """The dataclass itself is immutable -- its fields can't be reassigned
    -- but some payloads are mutable arrays that alias shared, cached
    state: `palette` aliases `Floor.palette`, and `background.pixels`
    aliases `Floor._camera_images[cam_idx]`'s cached decode (see
    AssetResolver.background/.palette). Treat every array reachable from
    a FrameDescription as read-only: a backend writing into either would
    corrupt the cache for every later frame that reuses it."""
    camera: CameraView
    background: ImageAsset
    palette: np.ndarray
    actors: tuple[ActorDraw, ...]
    masks: tuple[MaskDraw, ...]


def mask_applies_to_actor(mask, actor_room, zv):
    # Task 8 deleted render.py's _mask_applies_to_actor; this is now the
    # only copy of the rule. It stays in scene.py rather than moving to
    # render.py because the scene layer can't import from render.py
    # without pulling in pygame/moderngl.
    if zv is None or mask.viewed_room != actor_room:
        return False
    x1, x2 = int(zv[0] / 10), int(zv[1] / 10)
    z1, z2 = int(zv[4] / 10), int(zv[5] / 10)
    return any(
        x1 >= zone_x1 and z1 >= zone_z1 and x2 <= zone_x2 and z2 <= zone_z2
        for zone_x1, zone_z1, zone_x2, zone_z2 in mask.test_rects
    )


def build_frame(game, floor, resolver):
    """The per-frame scene: a float FrameDescription for the new renderers,
    and the unchanged draw_list (from the logical skin() bbox) so picking,
    the mouse contract and combat keep working byte-identically."""
    room = floor.rooms[game.current_room]
    cam_idx = room.camera_indices[game.num_camera]
    state = CameraState.from_camera(
        floor.cameras[cam_idx], room.world_x, room.world_y, room.world_z,
    ).angles()
    masks = tuple(floor.mask_draws(cam_idx))
    actors = []
    draw_list = []
    for index in sort_actor_indices(game, state.x, state.y, state.z):
        actor = game.actors[index]
        body = resolver.body(actor.body_num)
        if actor.anim == -1:
            states = [(0, (0, 0, 0))] * len(body.groups)
        else:
            states = anim_player_for(game, index).group_states()
        position = (
            actor.world_x + actor.step_x,
            actor.world_y + actor.step_y,
            actor.world_z + actor.step_z,
        )
        angles = (actor.alpha, actor.beta, actor.gamma)
        logical = skin(body, states, position, state, actor_angles=angles)
        draw_list.append((index, actor_bbox(logical)))
        actors.append(ActorDraw(
            index,
            pose_geometry(body, states, angles),
            position,
            actor.room,
            tuple(actor.zv),
            logical,
            tuple(m.id for m in masks if mask_applies_to_actor(m, actor.room, actor.zv)),
        ))
    frame = FrameDescription(
        CameraView(state),
        resolver.background(floor, cam_idx),
        resolver.palette(floor),
        tuple(actors),
        masks,
    )
    return frame, draw_list
