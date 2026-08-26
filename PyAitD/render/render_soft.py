# SPDX-License-Identifier: GPL-2.0-only
"""GL-free 320x200 backend over the logical FITD projection.

Used headless (tests, proofs) and as the fallback when no GL 3.3 context
exists. Within one actor, primitives are painted far-to-near by their minimum
depth: the software stand-in for the per-actor depth buffer."""
import numpy as np
import pygame

from PyAitD.render.geometry import POLY_TYPES
from PyAitD.engine.mask import fill_poly

W, H = 320, 200


class SoftwareBackend:
    def __init__(self):
        self._last = np.zeros((H, W, 3), dtype=np.uint8)

    def thumbnail(self):
        # A copy: the caller must not be able to corrupt what a later
        # thumbnail() call reports by mutating what an earlier one returned.
        return self._last.copy()

    def draw(self, frame):
        background = frame.background.pixels
        if background.shape[:2] != (H, W):
            background = _nearest_resize(background, W, H)
        composite = np.array(background, dtype=np.uint8, copy=True)
        palette = frame.palette
        mask_bitmaps = {}
        for actor in frame.actors:
            layer = pygame.Surface((W, H), flags=pygame.SRCALPHA)
            for prim in sorted(actor.logical.primitives, key=_depth_min, reverse=True):
                _draw_prim(layer, prim, tuple(int(c) for c in palette[prim.color]))
            rgb = pygame.surfarray.array3d(layer).swapaxes(0, 1)
            alpha = pygame.surfarray.array_alpha(layer).swapaxes(0, 1)
            visible = alpha != 0
            for mask_id in actor.mask_ids:
                if mask_id not in mask_bitmaps:
                    mask_bitmaps[mask_id] = _rasterize(frame.masks[mask_id])
                visible &= mask_bitmaps[mask_id] == 0
            composite[visible] = rgb[visible]
        # Store a private snapshot decoupled from the array handed back:
        # a caller mutating the returned frame in place must not corrupt what
        # a later thumbnail() reports.
        self._last = composite.copy()
        return composite


def _depth_min(prim):
    return min(p[2] for p in prim.points) if prim.points else 0.0


def _draw_prim(surface, prim, color):
    pts = [(int(p[0]), int(p[1])) for p in prim.points]
    if prim.type in POLY_TYPES:
        # Degenerate polygon data (fewer than 3 points) is dropped, matching
        # render.py's _ActorLayer triangle-fan loop, which emits no
        # triangles (and thus nothing) for the same case.
        if len(pts) >= 3:
            pygame.draw.polygon(surface, color, pts)
    elif prim.type == 0 and len(pts) == 2:
        pygame.draw.line(surface, color, pts[0], pts[1])
    elif prim.type == 3 and pts:
        pygame.draw.circle(surface, color, pts[0], max(1, int(prim.size)))
    else:
        size = 1 if prim.type in (2, 7) else 2
        for x, y in pts:
            pygame.draw.rect(surface, color, pygame.Rect(x, y, size, size))


def _rasterize(mask):
    bitmap = np.zeros((H, W), dtype=np.uint8)
    for poly in mask.polygons:
        fill_poly([tuple(p) for p in poly.tolist()], bitmap, 255)
    return bitmap


def _nearest_resize(image, width, height):
    ys = np.arange(height) * image.shape[0] // height
    xs = np.arange(width) * image.shape[1] // width
    return image[ys][:, xs]
