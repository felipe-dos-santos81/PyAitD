# SPDX-License-Identifier: GPL-2.0-only
"""Float mesh view of a posed FITD body for the enhanced renderer.

Shares skel.pose_vertices with the logical projection, so pose can never
disagree; only projection differs. Pygame/GL free."""
from dataclasses import dataclass
import functools

import numpy as np

from PyAitD.formats import _PRIM_POINT_LIKE
from PyAitD.skel import pose_vertices

POLY_TYPES = (1, 8, 9, 10)
POINT_TYPES = tuple(_PRIM_POINT_LIKE)
_CAMERA_FACING = np.array([0.0, 0.0, -1.0], dtype=np.float32)


@dataclass(frozen=True)
class BodyGeometry:
    vertices: np.ndarray      # (N,3) float32, posed model space (FITD units)
    normals: np.ndarray       # (N,3) float32 unit
    tris: np.ndarray          # (M,3) int32 indices into vertices
    tri_colors: np.ndarray    # (M,) uint8
    lines: np.ndarray         # (L,2) int32
    line_colors: np.ndarray   # (L,) uint8
    spheres: tuple            # ((centre_idx:int, radius:float, color:int), ...)
    points: np.ndarray        # (P,) int32
    point_sizes: np.ndarray   # (P,) uint8: 1 (type 2/7) or 2 (others)
    point_colors: np.ndarray  # (P,) uint8


def vertex_groups(body):
    """Group index per vertex; -1 for vertices outside any group (or bodies
    with no groups at all)."""
    groups = np.full(len(body.vertices), -1, dtype=np.int32)
    for index, group in enumerate(body.groups):
        groups[group.start:group.start + group.num_vertices] = index
    return groups


def _triangulate(body):
    tris, tri_colors = [], []
    lines, line_colors = [], []
    spheres = []
    points, point_sizes, point_colors = [], [], []
    for prim in body.primitives:
        if prim.type in POLY_TYPES:
            # fan triangulation of a convex polygon, matching FITD's own
            # rendering of these primitives
            for i in range(1, len(prim.points) - 1):
                tris.append((prim.points[0], prim.points[i], prim.points[i + 1]))
                tri_colors.append(prim.color)
        elif prim.type == 0:
            lines.append((prim.points[0], prim.points[1]))
            line_colors.append(prim.color)
        elif prim.type == 3:
            spheres.append((prim.points[0], float(prim.size), prim.color))
        elif prim.type in POINT_TYPES:
            points.append(prim.points[0])
            point_sizes.append(1 if prim.type in (2, 7) else 2)
            point_colors.append(prim.color)
    return (
        np.array(tris, dtype=np.int32).reshape(-1, 3),
        np.array(tri_colors, dtype=np.uint8),
        np.array(lines, dtype=np.int32).reshape(-1, 2),
        np.array(line_colors, dtype=np.uint8),
        tuple(spheres),
        np.array(points, dtype=np.int32),
        np.array(point_sizes, dtype=np.uint8),
        np.array(point_colors, dtype=np.uint8),
    )


def _vertex_normals(vertices, tris, groups):
    normals = np.zeros_like(vertices)
    if len(tris):
        a, b, c = vertices[tris[:, 0]], vertices[tris[:, 1]], vertices[tris[:, 2]]
        face = np.cross(b - a, c - a)
        length = np.linalg.norm(face, axis=1)
        valid = length > 1e-6
        face[valid] /= length[valid][:, None]
        face[~valid] = 0.0
        # a face contributes to a vertex only when the whole face lies in
        # that vertex's skeleton group: no smearing of shading across joints
        same_group = (groups[tris[:, 0]] == groups[tris[:, 1]]) & (groups[tris[:, 1]] == groups[tris[:, 2]])
        for corner in range(3):
            idx = tris[:, corner]
            np.add.at(normals, idx[same_group], face[same_group])
    length = np.linalg.norm(normals, axis=1)
    valid = length > 1e-6
    normals[valid] /= length[valid][:, None]
    normals[~valid] = _CAMERA_FACING
    return normals.astype(np.float32)


def pose_geometry(body, group_states, actor_angles=None):
    vertices = np.array(pose_vertices(body, group_states, actor_angles), dtype=np.float32).reshape(-1, 3)
    tris, tri_colors, lines, line_colors, spheres, points, point_sizes, point_colors = _triangulate(body)
    normals = _vertex_normals(vertices, tris, vertex_groups(body))
    return BodyGeometry(vertices, normals, tris, tri_colors, lines, line_colors,
                         spheres, points, point_sizes, point_colors)


@functools.lru_cache(maxsize=4)
def icosphere(level=1):
    t = (1.0 + 5 ** 0.5) / 2.0
    base_verts = [
        (-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0),
        (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
        (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1),
    ]
    tris = [
        (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
        (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
        (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
        (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1),
    ]
    verts = [np.array(v, dtype=np.float64) / np.linalg.norm(v) for v in base_verts]

    for _ in range(level):
        cache = {}
        new_tris = []

        def mid(i, j):
            key = (min(i, j), max(i, j))
            cached = cache.get(key)
            if cached is None:
                m = verts[i] + verts[j]
                verts.append(m / np.linalg.norm(m))
                cached = len(verts) - 1
                cache[key] = cached
            return cached

        for a, b, c in tris:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            new_tris += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        tris = new_tris

    return np.array(verts, dtype=np.float32), np.array(tris, dtype=np.int32)
