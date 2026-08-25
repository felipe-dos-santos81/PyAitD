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
from PyAitD.cos_table import COS_TABLE
from PyAitD.geometry import BodyGeometry, pose_geometry
from PyAitD.mask_geometry import MaskDraw
from PyAitD.picking import actor_bbox
from PyAitD.skel import RenderResult, skin
from PyAitD.world import SCREEN_CENTER_X, SCREEN_CENTER_Y, CameraState

_SENTINEL = np.array([-10000.0, -10000.0, -10000.0])


def _sin_cos(angle):
    # FITD cosTable.cpp lookup, scaled to a float unit circle (scale 32768).
    a = angle & 0x3FF
    return COS_TABLE[(a + 0x100) & 0x3FF] / 32768.0, COS_TABLE[a] / 32768.0


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
        pts = np.array(world_xyz, dtype=np.float64).reshape(-1, 3).copy()
        pts[:, 0] -= cam.x
        pts[:, 2] -= cam.z
        far = pts[:, 1] > 10000
        pts[:, 1] -= cam.y
        x, y, z = pts[:, 0], pts[:, 1], pts[:, 2]
        if cam._use_y:
            s, c = _sin_cos(cam._use_y)
            x, z = x * s - z * c, x * c + z * s
        if cam._use_x:
            s, c = _sin_cos(cam._use_x)
            y, z = y * s - z * c, y * c + z * s
        if cam._use_z:
            s, c = _sin_cos(cam._use_z)
            x, y = x * s - y * c, x * c + y * s
        return np.stack([x, y, z], axis=1), far

    def project(self, world_xyz):
        """(N,3) world -> (N,3) [sx, sy, depth] logical px; culled vertices
        (far or depth <= 50) become the (-10000, -10000, -10000) sentinel,
        matching skel.skin/CameraState.project exactly."""
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
    position: tuple
    room: int
    zv: tuple
    logical: RenderResult
    mask_ids: tuple


@dataclass(frozen=True)
class FrameDescription:
    camera: CameraView
    background: ImageAsset
    palette: np.ndarray
    actors: tuple
    masks: tuple


def mask_applies_to_actor(mask, actor_room, zv):
    # moved from render._mask_applies_to_actor: same trigger-rectangle rule,
    # shared now that both the legacy compositor and the scene layer need it.
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
            actor.zv,
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
