# SPDX-License-Identifier: GPL-2.0-only
"""Rest-pose per-vertex ambient occlusion for a FITD body.

Baked once per body (AssetResolver.geometry_ao memoises it) on the
assembled rest pose, then interpolated by the GL backend as a darkening
factor. Hemisphere rays around each vertex normal are intersected with
every triangle of the same body; the open fraction is the vertex's AO.
Rest-pose only: limbs pressed together by an animation do not darken each
other (spec, Limitations). Pure numpy."""
import numpy as np

from PyAitD.render.geometry import _vertex_normals, pose_geometry

DEFAULT_RAYS = 16      # 32 measured ~500ms worst-case on real body data (379 verts/570 tris,
                        # AITD1 body 266); halved per the brief's guidance to bring the
                        # worst case down to ~240ms with a median of ~9ms across 272 bodies
_CHUNK = 4096          # rays per intersection batch: caps the (rays, tris) broadcast
_RELATIVE_EPSILON = 1e-3


def hemisphere_directions(count):
    """`count` unit vectors spread over the whole sphere (Fibonacci
    lattice); occlusion_of mirrors each into a vertex's own hemisphere."""
    i = np.arange(count, dtype=np.float64) + 0.5
    phi = np.arccos(1.0 - 2.0 * i / count)
    theta = np.pi * (1.0 + 5 ** 0.5) * i
    return np.stack([np.cos(theta) * np.sin(phi), np.sin(theta) * np.sin(phi), np.cos(phi)], axis=1)


def _any_hit(origins, directions, a, b, c):
    """Möller-Trumbore over every (ray, triangle) pair; True where a ray
    hits any triangle in front of it. Both facings count: FITD polygons
    have no consistent winding."""
    e1, e2 = b - a, c - a                                     # (M,3)
    hits = np.zeros(len(origins), dtype=bool)
    for start in range(0, len(origins), _CHUNK):
        o = origins[start:start + _CHUNK][:, None, :]         # (R,1,3)
        d = directions[start:start + _CHUNK][:, None, :]
        p = np.cross(d, e2[None, :, :])                        # (R,M,3)
        det = np.einsum("rmk,mk->rm", p, e1)
        valid = np.abs(det) > 1e-9
        inv = np.where(valid, 1.0 / np.where(valid, det, 1.0), 0.0)
        t_vec = o - a[None, :, :]
        u = np.einsum("rmk,rmk->rm", t_vec, p) * inv
        q = np.cross(t_vec, e1[None, :, :])
        v = np.einsum("rmk,rmk->rm", d, q) * inv
        t = np.einsum("mk,rmk->rm", e2, q) * inv
        hit = valid & (u >= 0.0) & (v >= 0.0) & (u + v <= 1.0) & (t > 0.0)
        hits[start:start + _CHUNK] = hit.any(axis=1)
    return hits


def occlusion_of(vertices, tris, rays=DEFAULT_RAYS):
    """(N,) float32, 1 = fully open, for `vertices` against `tris`: the
    more open of the two hemispheres about each vertex's normal."""
    vertices = np.asarray(vertices, dtype=np.float64).reshape(-1, 3)
    tris = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    if len(tris) == 0 or len(vertices) == 0:
        return np.ones(len(vertices), dtype=np.float32)
    normals = _vertex_normals(vertices.astype(np.float32), tris.astype(np.int32),
                              np.zeros(len(vertices), dtype=np.int32)).astype(np.float64)
    extent = np.ptp(vertices, axis=0).max()
    epsilon = max(extent, 1.0) * _RELATIVE_EPSILON
    base = hemisphere_directions(rays)                        # (R,3)
    # mirror each direction into the hemisphere around this vertex's normal
    dots = normals @ base.T                                   # (N,R)
    dirs = np.where(dots[:, :, None] < 0.0, -base[None, :, :], base[None, :, :])   # (N,R,3)
    a, b, c = vertices[tris[:, 0]], vertices[tris[:, 1]], vertices[tris[:, 2]]
    # FITD winding cannot say which side of a surface is outside, so the
    # accumulated normal may point into the body. Cast both hemispheres
    # and keep the more open one: outside a closed body that is the real
    # outside; inside it both are shut; on a single-sided polygon the far
    # side is open, which is the safe answer (no false darkening).
    open_fraction = np.zeros(len(vertices))
    for sign in (1.0, -1.0):
        d = dirs * sign
        origins = vertices[:, None, :] + normals[:, None, :] * (epsilon * sign) + d * epsilon
        hits = _any_hit(origins.reshape(-1, 3), d.reshape(-1, 3), a, b, c).reshape(len(vertices), rays)
        open_fraction = np.maximum(open_fraction, 1.0 - hits.mean(axis=1))
    return open_fraction.astype(np.float32)


def bake_vertex_ao(body, rays=DEFAULT_RAYS):
    """AO for every vertex of `body` in its assembled rest pose: zero
    animation deltas, no actor rotation, group base offsets applied --
    what skel.pose_vertices produces for an idle actor."""
    geometry = pose_geometry(body, [(0, (0, 0, 0))] * len(body.groups))
    return occlusion_of(geometry.vertices, geometry.tris, rays)
