# SPDX-License-Identifier: GPL-2.0-only
"""Foreground mask polygons in 320x200 screen space (pre-rasterization view of
FITD main.cpp createAITD1Mask). Pygame/GL free."""
from dataclasses import dataclass, field
import struct

import numpy as np

from PyAitD.engine.data.formats import _s16


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _point_in_triangle(p, a, b, c):
    # Orientation-independent point-in-triangle test: p is inside (or on
    # the boundary of) triangle a,b,c iff the three edge-cross signs never
    # disagree, regardless of whether a,b,c winds CW or CCW.
    d1, d2, d3 = _cross(a, b, p), _cross(b, c, p), _cross(c, a, p)
    has_neg = d1 < 0 or d2 < 0 or d3 < 0
    has_pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (has_neg and has_pos)


def _dedupe_ring(pts):
    # Drop exact consecutive duplicate points (including the closing
    # wrap-around edge): a zero-length edge has no interior angle and
    # would otherwise stall ear-finding. Returns indices into `pts`.
    keep = []
    for i in range(len(pts)):
        if not keep or not np.array_equal(pts[i], pts[keep[-1]]):
            keep.append(i)
    if len(keep) > 1 and np.array_equal(pts[keep[0]], pts[keep[-1]]):
        keep.pop()
    return keep


def _fan_from(local_n, start=0):
    return [(start, k, k + 1) for k in range(1, local_n - 1) if k != start and k + 1 != start]


def triangulate_polygon(points):
    """Ear-clipping triangulation of a (possibly concave) simple polygon.

    `points` is an (N, 2) array-like of vertex coordinates. Returns an
    (T, 3) int32 array of *index triples into `points`* (not deduped
    copies), so a caller can gather triangle vertex coordinates with
    `np.asarray(points)[triangles]`.

    Handles either winding direction. Degenerate input (fewer than 3
    distinct vertices) yields zero triangles. If ear-finding cannot make
    progress (self-intersecting or otherwise pathological input), the
    remaining vertices are closed off with a simple fan rather than
    raising -- this function must never crash the render loop.
    """
    pts_all = np.asarray(points, dtype=np.float64)
    n_all = len(pts_all)
    if n_all < 3:
        return np.zeros((0, 3), dtype=np.int32)
    try:
        orig_idx = _dedupe_ring(pts_all)
        n = len(orig_idx)
        if n < 3:
            return np.zeros((0, 3), dtype=np.int32)
        if n == 3:
            return np.array([orig_idx], dtype=np.int32)
        pts = pts_all[orig_idx]
        # Normalize winding so a convex vertex always has cross(prev,
        # cur, next) > 0 -- the algorithm itself is orientation-
        # independent, but a single fixed sign convention makes the ear
        # test below simple.
        area2 = float(np.sum(pts[:, 0] * np.roll(pts[:, 1], -1) - np.roll(pts[:, 0], -1) * pts[:, 1]))
        order = list(range(n))
        if area2 < 0:
            order.reverse()
        remaining = order[:]
        triangles = []  # local (deduped-space) index triples
        guard, max_guard = 0, n * n + 8
        while len(remaining) > 3 and guard < max_guard:
            guard += 1
            m = len(remaining)
            ear_found = False
            for i in range(m):
                i_prev, i_cur, i_next = remaining[(i - 1) % m], remaining[i], remaining[(i + 1) % m]
                a, b, c = pts[i_prev], pts[i_cur], pts[i_next]
                if _cross(a, b, c) <= 0:
                    continue  # reflex or colinear: not a candidate ear
                if any(
                    j not in (i_prev, i_cur, i_next) and _point_in_triangle(pts[j], a, b, c)
                    for j in remaining
                ):
                    continue
                triangles.append((i_prev, i_cur, i_next))
                del remaining[i]
                ear_found = True
                break
            if not ear_found:
                # Ear-clipping stalled (self-intersecting or otherwise
                # pathological polygon): close off what's left with a
                # plain fan instead of looping forever or raising.
                triangles.extend((remaining[0], remaining[k], remaining[k + 1]) for k in range(1, m - 1))
                remaining = []
                break
        if len(remaining) == 3:
            triangles.append(tuple(remaining))
        if not triangles:
            return np.zeros((0, 3), dtype=np.int32)
        local = np.array(triangles, dtype=np.int32)
        return np.array(orig_idx, dtype=np.int32)[local]
    except Exception:
        # Defensive fallback: rendering must never crash mid-frame over a
        # malformed mask polygon. A fan from vertex 0 is exactly what the
        # old (buggy) renderer always did, so this is never worse than
        # the pre-fix behaviour for whatever pathological input reached
        # here.
        return np.array(_fan_from(n_all), dtype=np.int32) if n_all >= 3 else np.zeros((0, 3), dtype=np.int32)


@dataclass(frozen=True)
class MaskDraw:
    id: int
    polygons: tuple
    bbox: tuple
    viewed_room: int
    test_rects: tuple
    # Ear-clipped triangulation of each polygon in `polygons`, computed
    # once here (not per GL draw call) since masks are static per camera
    # and Floor.mask_draws already caches the MaskDraw list per camera --
    # this field rides along with that cache for free. Each entry is an
    # (T, 3) int32 array of index triples into the matching polygon.
    triangles: tuple = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(
            self, "triangles", tuple(triangulate_polygon(poly) for poly in self.polygons)
        )


def iter_mask_records(camera_raw, camera_off, viewed_room_record_size):
    num_viewed = struct.unpack_from("<H", camera_raw, camera_off + 0x12)[0]
    for viewed in range(num_viewed):
        vr_off = camera_off + 0x14 + viewed * viewed_room_record_size
        vr_room = struct.unpack_from("<h", camera_raw, vr_off)[0]
        mask_off = struct.unpack_from("<H", camera_raw, vr_off + 2)[0]
        base = camera_off + mask_off
        data2 = camera_raw[base:]
        num_mask = struct.unpack_from("<h", data2, 0)[0]
        data = 2  # skip numMask
        for _ in range(num_mask):
            num_zones = struct.unpack_from("<H", data2, data)[0]
            test_rects = tuple(
                struct.unpack_from("<4h", data2, data + 4 + zone * 8)
                for zone in range(num_zones)
            )
            # FITD: src = data2 + u16(data+2) -- the offset value is relative to data2
            poly_off = struct.unpack_from("<H", data2, data + 2)[0]
            src = camera_raw[base + poly_off :]
            num_polys = struct.unpack_from("<H", src, 0)[0]
            off = 2
            polygons = []
            for _ in range(num_polys):
                num_points = struct.unpack_from("<H", src, off)[0]
                off += 2
                polygons.append([
                    (_s16(src, off + k * 4), _s16(src, off + k * 4 + 2))
                    for k in range(num_points)
                ])
                off += num_points * 4
            yield vr_room, test_rects, polygons
            # advance to the next mask header after its actor trigger rectangles
            data += 2 + ((num_zones * 4 + 1) * 2)


def _polygons_bbox(polygons):
    min_x, max_x, min_y, max_y = 319, 0, 199, 0
    for poly in polygons:
        for px, py in poly:
            min_x, max_x = min(min_x, px), max(max_x, px)
            min_y, max_y = min(min_y, py), max(max_y, py)
    return min_x, min_y, max_x, max_y


def mask_polygons(camera_raw, camera_off, viewed_room_record_size):
    draws = []
    for index, (viewed_room, test_rects, polygons) in enumerate(
        iter_mask_records(camera_raw, camera_off, viewed_room_record_size)
    ):
        draws.append(MaskDraw(
            index,
            tuple(np.array(poly, dtype=np.int16).reshape(-1, 2) for poly in polygons),
            _polygons_bbox(polygons),
            viewed_room,
            test_rects,
        ))
    return draws
