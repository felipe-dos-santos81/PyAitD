# SPDX-License-Identifier: GPL-2.0-only
"""Synthetic Floor stand-in for the export/check tests (no game data)."""
import numpy as np

from PyAitD.engine.data.formats import Camera, Room, ViewedRoom, Zone
from PyAitD.engine.data.mask_geometry import MaskDraw

W, H = 320, 200


def checker_pixels(seed=0):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(H, W, 3), dtype=np.uint8)


class StubFloor:
    """One room, one camera at the origin looking down +z, one mask, one
    hard-col box. `cover_zones` is what the export module reads instead of
    parse_cover_zones when the floor object provides it."""

    def __init__(self, number=0, images=None):
        self.number = number
        self.palette = np.zeros((256, 3), np.uint8)
        self.rooms = [Room(
            world_x=0, world_y=0, world_z=0, camera_indices=[0],
            hard_cols=[Zone(x1=-100, x2=100, y1=-50, y2=0, z1=0, z2=1000, type=0, parameter=0)],
            sce_zones=[], offset_to_hard_col=0, offset_to_sce_zones=0,
        )]
        cam = Camera(alpha=0, beta=0, gamma=0, x=0, y=0, z=0,
                     focal1=1000, focal2=1000, focal3=1000)
        cam.viewed_rooms.append(ViewedRoom(0, 0, 0, 0, 0, 0))
        self.cameras = [cam]
        self.camera_raw = b""
        self.camera_data_offsets = [0]
        self.viewed_room_record_size = 0x0C
        self._images = {0: checker_pixels()} if images is None else images
        # (x, z) in cover units: 10x smaller than room scale
        self._cover = {(0, 0): [[(-5, 0), (5, 0), (5, 50), (-5, 50)]]}

    def camera_image(self, cam_idx):
        if cam_idx not in self._images:
            raise KeyError(f"floor {self.number}: camera image {cam_idx} out of range")
        return self._images[cam_idx]

    def mask_draws(self, cam_idx):
        poly = np.array([[10, 10], [50, 10], [50, 40]], np.int16)
        return [MaskDraw(0, (poly,), (10, 10, 50, 40), 0, ())]

    def cover_zones(self, cam_idx, viewed_idx):
        return self._cover.get((cam_idx, viewed_idx), [])
