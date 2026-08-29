# SPDX-License-Identifier: GPL-2.0-only
"""Rest-pose mesh refinement for the GPU tessellation of a FITD body.

A body is a soup of polygons over a shared vertex list, wound consistently
(measured: every shared edge of every shipped body is walked in opposite
directions by its two faces) but with an unknown inward/outward sign, open
at limb rings, and non-manifold where panels meet. This module plans, once
per body from its rest pose, everything the tessellating vertex shader in
render_gl needs that depends on mesh topology rather than on the pose:

- `orientation`: a sign per face making face normals agree across shared
  edges (breadth-first over two-face edges; a safety net on shipped data);
- `straight`: which of each triangle's three edges is a crease -- sharper
  than `crease_deg` between its two oriented faces, shared by three or more
  faces, or belonging to a zero-area face -- and therefore keeps a straight
  PN control polygon so a smooth patch never opens a crack against a hard
  neighbour. Boundary edges (one face) curve;
- `pairs`: for every triangle corner, the faces that feed its normal: the
  faces reachable from the corner's own face through non-crease edges at
  that vertex -- its smoothing group. Unlike geometry._vertex_normals this
  counts faces that span skeleton groups, which is what leaves a third of
  the hero's vertices with a placeholder normal there.

`corner_normals` then turns posed vertices into one normal per triangle
corner each frame, `subpatch` is the barycentric sub-triangle list one
tessellation level draws, and `evaluate` is the numpy twin of the shader's
PN-triangle formula, for tests. Pure numpy: no pygame, no GL."""
from dataclasses import dataclass
import functools

import numpy as np

from PyAitD.render.geometry import _CAMERA_FACING, pose_geometry

CREASE_DEG = 80.0
MAX_CREASE_DEG = 180.0
_DEGENERATE = 1e-9


@dataclass(frozen=True)
class Refinement:
    orientation: np.ndarray   # (M,) float32 +-1
    pairs: np.ndarray         # (K,2) int32 (corner = 3*face + k, contributing face)
    straight: np.ndarray      # (M,3) float32: 1.0 where edge k (v_k -> v_k+1) is a crease
    crease_deg: float

    def corner_normals(self, vertices, tris):
        return corner_normals(vertices, tris, self)


def _face_normals(vertices, tris):
    """Area-weighted (unnormalised) cross products, in the authored winding."""
    a, b, c = vertices[tris[:, 0]], vertices[tris[:, 1]], vertices[tris[:, 2]]
    return np.cross(b - a, c - a)


def _edges(tris):
    """{(lo, hi): [(face, corner, forward), ...]} over every directed edge
    of every face; `forward` is whether the face walks lo -> hi."""
    edges = {}
    for f, (i, j, k) in enumerate(tris.tolist()):
        for corner, (u, v) in enumerate(((i, j), (j, k), (k, i))):
            key = (u, v) if u < v else (v, u)
            edges.setdefault(key, []).append((f, corner, u < v))
    return edges


def _orient(tris, edges, normals, vertices):
    m = len(tris)
    sign = np.zeros(m, dtype=np.float32)
    neighbours = [[] for _ in range(m)]
    for faces in edges.values():
        if len(faces) == 2:
            (f0, _, fwd0), (f1, _, fwd1) = faces
            # two consistently wound faces walk a shared edge in opposite
            # directions; walking it the same way means one must flip
            neighbours[f0].append((f1, fwd0 == fwd1))
            neighbours[f1].append((f0, fwd0 == fwd1))
    for seed in range(m):
        if sign[seed]:
            continue
        sign[seed] = 1.0
        component = [seed]
        queue = [seed]
        while queue:
            f = queue.pop()
            for g, same in neighbours[f]:
                if not sign[g]:
                    sign[g] = -sign[f] if same else sign[f]
                    component.append(g)
                    queue.append(g)
        # the component's global sign: normals point away from its centroid
        comp = np.array(component)
        centroids = vertices[tris[comp]].mean(axis=1)
        centre = centroids.mean(axis=0)
        outward = float((normals[comp] * sign[comp, None] * (centroids - centre)).sum())
        if outward < 0.0:
            sign[comp] *= -1.0
    return sign


def _straight_flags(tris, edges, normals, sign, crease_deg):
    lengths = np.linalg.norm(normals, axis=1)
    unit = np.zeros_like(normals)
    ok = lengths > _DEGENERATE
    unit[ok] = normals[ok] / lengths[ok][:, None]
    unit *= sign[:, None]
    straight = np.zeros((len(tris), 3), dtype=np.float32)
    creases = set()
    for key, faces in edges.items():
        if len(faces) == 1:
            continue                                   # boundary: curves
        if len(faces) == 2:
            f0, f1 = faces[0][0], faces[1][0]
            if ok[f0] and ok[f1]:
                angle = np.degrees(np.arccos(np.clip(float(np.dot(unit[f0], unit[f1])), -1.0, 1.0)))
                if angle <= crease_deg:
                    continue                           # smooth
        creases.add(key)
        for f, corner, _ in faces:
            straight[f, corner] = 1.0
    return straight, creases


def _corner_pairs(tris, edges, creases):
    """(corner, face) pairs: for corner (f, k) at vertex v, every face that
    reaches f through non-crease two-face edges incident to v."""
    around = {}                      # v -> {face: [faces adjacent through a smooth edge at v]}
    for key, faces in edges.items():
        if key in creases or len(faces) != 2:
            continue
        (f0, _, _), (f1, _, _) = faces
        for v in key:
            adjacency = around.setdefault(v, {})
            adjacency.setdefault(f0, []).append(f1)
            adjacency.setdefault(f1, []).append(f0)
    pairs = []
    for f, corners in enumerate(tris.tolist()):
        for k, v in enumerate(corners):
            group = {f}
            stack = [f]
            adjacency = around.get(v, {})
            while stack:
                g = stack.pop()
                for h in adjacency.get(g, ()):
                    if h not in group:
                        group.add(h)
                        stack.append(h)
            pairs.extend((3 * f + k, g) for g in sorted(group))
    return np.array(pairs, dtype=np.int32).reshape(-1, 2)


def plan_refinement(body, crease_deg=CREASE_DEG):
    """The pose-independent plan for `body`, from its assembled rest pose:
    zero animation deltas, no actor rotation, group base offsets applied --
    the same pose occlusion.bake_vertex_ao reads."""
    geometry = pose_geometry(body, [(0, (0, 0, 0))] * len(body.groups))
    tris = geometry.tris
    if len(tris) == 0:
        return Refinement(np.zeros(0, np.float32), np.zeros((0, 2), np.int32),
                          np.zeros((0, 3), np.float32), float(crease_deg))
    vertices = geometry.vertices.astype(np.float64)
    normals = _face_normals(vertices, tris)
    edges = _edges(tris)
    orientation = _orient(tris, edges, normals, vertices)
    straight, creases = _straight_flags(tris, edges, normals, orientation, float(crease_deg))
    pairs = _corner_pairs(tris, edges, creases)
    return Refinement(orientation, pairs, straight, float(crease_deg))


def corner_normals(vertices, tris, refinement):
    """(M,3,3) float32: one unit normal per triangle corner of the posed
    mesh, each the area-weighted mean of its smoothing group's oriented
    face normals. A corner whose sum vanishes (degenerate geometry) gets
    the camera-facing placeholder, as geometry._vertex_normals does."""
    tris = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    if len(tris) == 0:
        return np.zeros((0, 3, 3), dtype=np.float32)
    face = _face_normals(np.asarray(vertices, dtype=np.float64).reshape(-1, 3), tris)
    face *= refinement.orientation.astype(np.float64)[:, None]
    out = np.zeros((len(tris) * 3, 3), dtype=np.float64)
    np.add.at(out, refinement.pairs[:, 0], face[refinement.pairs[:, 1]])
    length = np.linalg.norm(out, axis=1)
    valid = length > _DEGENERATE
    out[valid] /= length[valid][:, None]
    out[~valid] = _CAMERA_FACING
    return out.reshape(-1, 3, 3).astype(np.float32)


@functools.lru_cache(maxsize=4)
def subpatch(level):
    """The barycentric triangle list of one triangle split into 2**level
    segments per edge: (3 * 4**level, 3) float32 rows of (u, v, w), u the
    weight of corner 0. Corners appear exactly. Read-only and shared, like
    geometry.icosphere."""
    n = 2 ** level
    index = {}
    bary = []
    for i in range(n + 1):
        for j in range(n + 1 - i):
            index[(i, j)] = len(bary)
            bary.append((i / n, j / n, (n - i - j) / n))
    tris = []
    for i in range(n):
        for j in range(n - i):
            tris.append((index[(i, j)], index[(i + 1, j)], index[(i, j + 1)]))
            if j < n - i - 1:
                tris.append((index[(i + 1, j)], index[(i + 1, j + 1)], index[(i, j + 1)]))
    out = np.array(bary, dtype=np.float32)[np.array(tris, dtype=np.int64).reshape(-1)]
    out.setflags(write=False)
    return out


def evaluate(corners, normals, straight, bary):
    """PN-triangle positions and normals: the numpy twin of render_gl's
    _TESS_VSH, evaluated for every patch at every barycentric.

    corners, normals: (M,3,3); straight: (M,3), 1.0 where edge k (corner k
    to k+1) keeps a straight control polygon; bary: (S,3) -> two (M,S,3)."""
    P = np.asarray(corners, np.float64)
    N = np.asarray(normals, np.float64)
    S = np.asarray(straight, np.float64)
    B = np.asarray(bary, np.float64)

    def edge_point(i, j, k):
        # a third of the way from corner i toward j, projected onto i's
        # tangent plane -- or left on the chord when edge k is a crease
        w = np.einsum("mc,mc->m", P[:, j] - P[:, i], N[:, i])[:, None]
        return (2 * P[:, i] + P[:, j]) / 3 - (1 - S[:, k, None]) * w * N[:, i] / 3

    def edge_normal(i, j, k):
        d = P[:, j] - P[:, i]
        h = N[:, i] + N[:, j]
        dd = np.einsum("mc,mc->m", d, d)
        v = np.where(dd > 1e-12, 2 * np.einsum("mc,mc->m", d, h) / np.maximum(dd, 1e-12), 0.0)
        h = h - (1 - S[:, k, None]) * v[:, None] * d
        return h / np.maximum(np.linalg.norm(h, axis=1), 1e-12)[:, None]

    b210, b120 = edge_point(0, 1, 0), edge_point(1, 0, 0)
    b021, b012 = edge_point(1, 2, 1), edge_point(2, 1, 1)
    b102, b201 = edge_point(2, 0, 2), edge_point(0, 2, 2)
    E = (b210 + b120 + b021 + b012 + b102 + b201) / 6
    V = (P[:, 0] + P[:, 1] + P[:, 2]) / 3
    b111 = E + (E - V) / 2
    u, v, w = B[:, 0], B[:, 1], B[:, 2]

    def term(control, weight):
        return control[:, None, :] * weight[None, :, None]

    pos = (term(P[:, 0], u ** 3) + term(P[:, 1], v ** 3) + term(P[:, 2], w ** 3)
           + term(b210, 3 * u * u * v) + term(b120, 3 * u * v * v) + term(b201, 3 * u * u * w)
           + term(b021, 3 * v * v * w) + term(b102, 3 * u * w * w) + term(b012, 3 * v * w * w)
           + term(b111, 6 * u * v * w))
    n110, n011, n101 = edge_normal(0, 1, 0), edge_normal(1, 2, 1), edge_normal(2, 0, 2)
    nrm = (term(N[:, 0], u * u) + term(N[:, 1], v * v) + term(N[:, 2], w * w)
           + term(n110, u * v) + term(n011, v * w) + term(n101, w * u))
    nrm /= np.maximum(np.linalg.norm(nrm, axis=2), 1e-12)[:, :, None]
    return pos.astype(np.float32), nrm.astype(np.float32)


def parse_crease(data):
    """The optional `crease` degrees of a bodies/body<NNN>.json: None when
    absent, a float in 0..MAX_CREASE_DEG otherwise. Anything else raises
    ValueError naming the key, like materials.parse_assignments does."""
    if not isinstance(data, dict):
        raise ValueError("body override must be an object")
    if "crease" not in data:
        return None
    value = data["crease"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"crease: must be a number of degrees, got {value!r}")
    if not 0.0 <= value <= MAX_CREASE_DEG:
        raise ValueError(f"crease: must be within 0..{MAX_CREASE_DEG:g} degrees, got {value!r}")
    return float(value)
