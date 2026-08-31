# SPDX-License-Identifier: GPL-2.0-only
"""Float mesh view of a posed FITD body for the enhanced renderer.

Shares skel.pose_vertices with the logical projection, so pose can never
disagree; only projection differs. Pygame/GL free."""
from dataclasses import dataclass
import functools

import numpy as np

from PyAitD.engine.data.formats import _PRIM_POINT_LIKE
from PyAitD.engine.actor.skel import pose_vertices

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
    rest: np.ndarray = None   # (N,3) float32, the body's raw vertices: stable per vertex across poses
    ao: np.ndarray = None     # (N,) float32 rest-pose occlusion, 1 = open
    _corner_normals: np.ndarray = None  # (M,3,3) float32 backing store; read the `corner_normals` property
    straight: np.ndarray = None         # (M,3) float32, 1.0 where a triangle edge keeps a straight PN control polygon
    refinement: object = None           # refine.Refinement or None: the plan `corner_normals` evaluates on demand

    def __post_init__(self):
        # Both default from `vertices` so every positional constructor
        # (tests, tools) keeps working: rest = the posed vertices (only
        # wrong for an animated body, and only for detail placement), ao =
        # fully open.
        if self.rest is None:
            object.__setattr__(self, "rest", self.vertices)
        if self.ao is None:
            object.__setattr__(self, "ao", np.ones(len(self.vertices), dtype=np.float32))
        # Without a plan a corner takes its vertex's normal and no edge is a
        # crease -- the tessellator then rounds exactly what smooth shading
        # already rounds -- and that is a plain gather, so do it now. With a
        # plan it is real per-body-per-frame arithmetic that only the
        # tessellated path in render_gl ever reads, so it waits: see the
        # `corner_normals` property.
        if self._corner_normals is None and self.refinement is None:
            object.__setattr__(self, "_corner_normals",
                               np.asarray(self.normals, dtype=np.float32)[self.tris].reshape(-1, 3, 3))
        if self.straight is None:
            object.__setattr__(self, "straight", np.zeros((len(self.tris), 3), dtype=np.float32))

    @property
    def corner_normals(self):
        """(M,3,3) float32, one normal per triangle corner: refine's
        crease-aware normals when this geometry was posed with a plan, the
        vertex normals gathered per corner otherwise.

        Computed on first read and cached, because building a plan's corner
        normals costs about a fifth of a frame's build_frame time and
        nothing but render_gl's tessellated path reads them: a frame drawn
        at smoothing 0, or drawn by SoftwareBackend, never asks and never
        pays."""
        normals = self._corner_normals
        if normals is None:
            normals = self.refinement.corner_normals(self.vertices, self.tris)
            object.__setattr__(self, "_corner_normals", normals)
        return normals


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


def pose_geometry(body, group_states, actor_angles=None, ao=None, refinement=None):
    vertices = np.array(pose_vertices(body, group_states, actor_angles), dtype=np.float32).reshape(-1, 3)
    tris, tri_colors, lines, line_colors, spheres, points, point_sizes, point_colors = _triangulate(body)
    normals = _vertex_normals(vertices, tris, vertex_groups(body))
    rest = np.array(body.vertices, dtype=np.float32).reshape(-1, 3)
    if ao is None:
        ao = np.ones(len(vertices), dtype=np.float32)
    else:
        ao = np.asarray(ao, dtype=np.float32).reshape(-1)
        if len(ao) != len(vertices):
            raise ValueError(f"ao has {len(ao)} entries for {len(vertices)} vertices")
    straight = None
    if refinement is not None:
        # duck-typed on purpose: refine imports this module to build its plan,
        # so geometry never imports refine. `straight` is a free alias; the
        # corner normals are not, so the plan rides along instead and
        # BodyGeometry.corner_normals evaluates it if anyone asks.
        straight = refinement.straight
    return BodyGeometry(vertices, normals, tris, tri_colors, lines, line_colors,
                        spheres, points, point_sizes, point_colors, rest, ao, None, straight,
                        refinement)


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

    verts_array = np.array(verts, dtype=np.float32)
    tris_array = np.array(tris, dtype=np.int32)
    # lru_cache-shared with every caller: nothing mutates these today, but
    # mark them read-only so an accidental future write fails loudly instead
    # of silently corrupting every sphere-shaped actor drawn afterward.
    verts_array.setflags(write=False)
    tris_array.setflags(write=False)
    return verts_array, tris_array
