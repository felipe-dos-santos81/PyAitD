# SPDX-License-Identifier: GPL-2.0-only
"""Export the original camera backgrounds for external (AI) regeneration.

Pure numpy: no pygame, no moderngl. PNG encoding lives in
tools/export_backgrounds.py. See docs/ai-background-regeneration.md.
"""
import hashlib

import numpy as np

from PyAitD.engine.formats import parse_cover_zones
from PyAitD.engine.navmesh import COVER_SCALE
from PyAitD.scene import CameraView
from PyAitD.engine.world import CameraState

W, H = 320, 200


def draw_polyline(img, points, rgb, closed=False):
    """Draw 1px Bresenham segments through `points` ((x, y) floats, rounded)
    into `img` (H, W, 3) in place, clipping every pixel to the image."""
    pts = [(int(round(x)), int(round(y))) for x, y in points]
    if not pts:
        return
    if closed and len(pts) > 1:
        pts = pts + [pts[0]]
    if len(pts) == 1:
        pts = pts + [pts[0]]
    h, w = img.shape[:2]
    color = np.array(rgb, dtype=np.uint8)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        x, y = x0, y0
        while True:
            if 0 <= x < w and 0 <= y < h:
                img[y, x] = color
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy


def nearest_upscale(img, scale):
    """Integer nearest-neighbour upscale; always returns a fresh C-contiguous array."""
    out = np.repeat(np.repeat(img, scale, axis=0), scale, axis=1)
    return np.ascontiguousarray(out)


def sha256_rgb(pixels):
    """Hex digest over the raw (H, W, 3) uint8 bytes in row-major order --
    independent of the PNG encoder that later wrote or read them."""
    return hashlib.sha256(np.ascontiguousarray(pixels, dtype=np.uint8).tobytes()).hexdigest()


MANIFEST_SCHEMA = 1
LEGEND = {"red": "masks", "blue": "collision", "green": "walkable"}


def background_rel_path(floor_number, cam_idx):
    # Must stay identical to asset_resolver.override_background_path's tail:
    # the export directory is used directly as --overrides DIR.
    return f"backgrounds/floor{floor_number:02d}/camera{cam_idx:03d}.png"


def guide_rel_path(floor_number, cam_idx):
    return f"guides/floor{floor_number:02d}/camera{cam_idx:03d}.png"


def manifest_record(floor, cam_idx, pixels):
    """One manifest entry. `pixels` is the exported (H, W, 3) array, or None
    when Floor.camera_image raised KeyError (image missing from CAMERAnn.PAK)."""
    rec = {
        "floor": floor.number,
        "camera": cam_idx,
        "source": None,
        "guide": None,
        "size": None,
        "viewed_rooms": [],
        "masks": 0,
        "sha256": None,
    }
    # Populate camera metadata only if camera exists (valid index)
    if cam_idx < len(floor.cameras):
        cam = floor.cameras[cam_idx]
        rec["viewed_rooms"] = [vr.viewed_room_idx for vr in cam.viewed_rooms]
        rec["masks"] = len(floor.mask_draws(cam_idx))
    # Populate image-derived fields only if pixels available
    if pixels is not None:
        rec["source"] = background_rel_path(floor.number, cam_idx)
        rec["guide"] = guide_rel_path(floor.number, cam_idx)
        rec["size"] = [int(pixels.shape[1]), int(pixels.shape[0])]
        rec["sha256"] = sha256_rgb(pixels)
    return rec


def export_manifest(records, data_dir, guide_scale):
    return {
        "schema": MANIFEST_SCHEMA,
        "data_dir": str(data_dir),
        "guide_scale": int(guide_scale),
        "legend": dict(LEGEND),
        "cameras": list(records),
    }


GUIDE_FOOTER = 12
COLOR_MASK = (255, 0, 0)
COLOR_COLLISION = (0, 128, 255)
COLOR_WALKABLE = (0, 200, 0)
_SWATCH_W, _SWATCH_STRIDE = 40, 48
_CULLED = -9999.0


def cover_zones_for(floor, cam_idx, viewed_idx):
    """Cover polygons ((x, z) in cover units) of `viewed_idx` as seen from
    `cam_idx`. Real Floors go through parse_cover_zones exactly as
    navmesh.cover_polys does; a floor object exposing `cover_zones` (test
    stubs) is asked directly."""
    if hasattr(floor, "cover_zones"):
        return floor.cover_zones(cam_idx, viewed_idx)
    return parse_cover_zones(floor.camera_raw, floor.camera_data_offsets[cam_idx], viewed_idx)


def _draw_projected(img, view, world_pts, edges, rgb, scale):
    """Project `world_pts` and draw each (i, j) edge whose endpoints both
    survived culling, scaled by `scale`."""
    proj = view.project(world_pts)
    for i, j in edges:
        a, b = proj[i], proj[j]
        if a[2] <= _CULLED or b[2] <= _CULLED:
            continue
        draw_polyline(img, [(a[0] * scale, a[1] * scale), (b[0] * scale, b[1] * scale)], rgb)


_BOX_EDGES = (
    (0, 1), (1, 2), (2, 3), (3, 0),   # bottom rectangle (y2, the floor edge)
    (4, 5), (5, 6), (6, 7), (7, 4),   # top rectangle (y1)
    (0, 4), (1, 5), (2, 6), (3, 7),   # verticals
)


def _box_corners(z):
    return [
        (z.x1, z.y2, z.z1), (z.x2, z.y2, z.z1), (z.x2, z.y2, z.z2), (z.x1, z.y2, z.z2),
        (z.x1, z.y1, z.z1), (z.x2, z.y1, z.z1), (z.x2, z.y1, z.z2), (z.x1, z.y1, z.z2),
    ]


def guide_overlay(floor, cam_idx, scale):
    """The original background upscaled x`scale` (nearest neighbour) with
    mask polygons (red), hard-collision boxes (blue) and cover polygons
    (green) drawn over it, plus a GUIDE_FOOTER-px legend strip.

    Room-space coordinates are passed to CameraView as-is: the room's world
    offset is already folded into CameraState.from_camera, exactly as actor
    positions reach CameraView in scene.build_frame."""
    base = nearest_upscale(floor.camera_image(cam_idx), scale)
    h, w = base.shape[:2]
    img = np.zeros((h + GUIDE_FOOTER, w, 3), np.uint8)
    img[:h] = base

    for mask in floor.mask_draws(cam_idx):
        for poly in mask.polygons:
            pts = [(float(x) * scale, float(y) * scale) for x, y in np.asarray(poly).reshape(-1, 2)]
            draw_polyline(img, pts, COLOR_MASK, closed=True)

    camera = floor.cameras[cam_idx]
    for viewed_idx, vr in enumerate(camera.viewed_rooms):
        room = floor.rooms[vr.viewed_room_idx]
        view = CameraView(CameraState.from_camera(camera, room.world_x, room.world_y, room.world_z).angles())
        for box in room.hard_cols:
            _draw_projected(img, view, _box_corners(box), _BOX_EDGES, COLOR_COLLISION, scale)
        for poly in cover_zones_for(floor, cam_idx, viewed_idx):
            pts = [(x * COVER_SCALE, 0, z * COVER_SCALE) for x, z in poly]
            n = len(pts)
            if n < 2:
                continue
            edges = [(k, (k + 1) % n) for k in range(n)]
            _draw_projected(img, view, pts, edges, COLOR_WALKABLE, scale)

    for k, color in enumerate((COLOR_MASK, COLOR_COLLISION, COLOR_WALKABLE)):
        x0 = k * _SWATCH_STRIDE
        img[h:, x0:x0 + _SWATCH_W] = color
    return img
