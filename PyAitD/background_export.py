# SPDX-License-Identifier: GPL-2.0-only
"""Export the original camera backgrounds for external (AI) regeneration.

Pure numpy: no pygame, no moderngl. PNG encoding lives in
tools/export_backgrounds.py. See docs/ai-background-regeneration.md.
"""
import hashlib

import numpy as np

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
