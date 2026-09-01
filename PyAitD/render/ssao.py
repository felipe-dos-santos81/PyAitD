# SPDX-License-Identifier: GPL-2.0-only
"""Screen-space ambient occlusion: the kernel, the rotation tile, and the
numpy twin render_gl's SSAO_FSH is pinned against.

Pure numpy: no pygame, no GL, no engine imports -- the same rule
render/lighting.py follows, and tests/test_layering.py enforces it by
scanning every render/ module that is not a declared graphics owner.

This is *not* render/occlusion.py. That module bakes per-vertex AO into a
body's rest pose once, and cannot see pose or neighbours; this one runs
per frame over the depth the actors actually occupy, which is where
creases, armpits and the gap under a looming monster come from. The two
are additive by design.

Conventions, shared verbatim with SSAO_FSH:

- View space looks down -z, and `depth` is **positive linear distance**
  from the camera, not a projective depth buffer value. The prepass
  writes it into the G-buffer's alpha channel precisely so neither side
  has to invert a projection matrix -- that inversion is where a twin and
  a shader most easily disagree.
- A pixel the prepass never covered carries depth exactly 0.0 and is
  returned unoccluded.
- The result is a *multiplier*: 1.0 means no occlusion, 0.0 means fully
  occluded. The shader multiplies the fill share by it, so the neutral
  value has to be the multiplicative identity.
"""
import numpy as np

SSAO_KERNEL_SIZE = 16
# In view-space units. AITD1's actors stand about 200 units tall, so this
# is roughly a hand's width -- large enough to find the gap between two
# actors, small enough not to darken a whole limb against the torso.
SSAO_RADIUS = 14.0
# Depth slack before a nearer sample counts as an occluder, in the same
# units. Below this, a plane's own sampling noise reads as self-occlusion.
SSAO_BIAS = 0.6


def hemisphere_kernel(count=SSAO_KERNEL_SIZE, seed=7):
    """`(count, 3)` sample offsets in the +z hemisphere, clustered toward
    the origin so near-surface detail gets most of the taps.

    The quadratic ramp is the standard LearnOpenGL-class weighting: it is
    the shape of the kernel that matters, not its provenance."""
    rng = np.random.default_rng(seed)
    v = rng.normal(size=(count, 3)).astype(np.float32)
    v[:, 2] = np.abs(v[:, 2])                     # fold into the +z hemisphere
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    t = (np.arange(count, dtype=np.float32) + 0.5) / count
    v *= (0.1 + 0.9 * t * t)[:, None]             # cluster near the origin
    return np.ascontiguousarray(v, dtype=np.float32)


def noise_rotations(size=4, seed=11):
    """`(size, size, 2)` unit vectors, tiled over the screen to rotate the
    kernel per pixel. Trading banding for high-frequency noise, which the
    blur in Task 4 then removes."""
    rng = np.random.default_rng(seed)
    a = rng.uniform(0.0, 2.0 * np.pi, (size, size)).astype(np.float32)
    return np.ascontiguousarray(np.stack([np.cos(a), np.sin(a)], axis=2), dtype=np.float32)


def _view_position(depth, proj_xy):
    """Back-project every pixel to its view-space position.

    `proj_xy` is the projection's (fx, fy): the same pair the shader gets,
    so both sides run the identical pinhole relation
    `ndc = (x/-z) * f` and neither inverts a matrix."""
    h, w = depth.shape
    ndc_x = (np.arange(w, dtype=np.float32) + 0.5) / w * 2.0 - 1.0
    ndc_y = (np.arange(h, dtype=np.float32) + 0.5) / h * 2.0 - 1.0
    gx, gy = np.meshgrid(ndc_x, ndc_y)
    z = -depth
    return np.stack([gx * depth / proj_xy[0], gy * depth / proj_xy[1], z], axis=2)


def _project(p, proj_xy, shape):
    """View-space points to integer pixel coordinates, clamped in range.

    Returns `(ix, iy, ok)` where `ok` is False for anything behind or on
    the camera plane, which has no screen position at all."""
    h, w = shape
    z = p[..., 2]
    ok = z < -1e-6
    safe = np.where(ok, -z, 1.0)
    ndc_x = p[..., 0] * proj_xy[0] / safe
    ndc_y = p[..., 1] * proj_xy[1] / safe
    ix = np.clip(((ndc_x + 1.0) * 0.5 * w).astype(np.int32), 0, w - 1)
    iy = np.clip(((ndc_y + 1.0) * 0.5 * h).astype(np.int32), 0, h - 1)
    return ix, iy, ok


def ssao_reference(depth, normals, kernel, rotations, proj_xy,
                   radius=SSAO_RADIUS, bias=SSAO_BIAS):
    """`(H, W)` occlusion multiplier in [0, 1]; 1.0 is unoccluded.

    `depth` is positive linear view distance, 0.0 where nothing was drawn.
    `normals` are unit view-space normals. `kernel` and `rotations` come
    from the two builders above. Every step below has a line-for-line
    counterpart in SSAO_FSH."""
    depth = np.asarray(depth, dtype=np.float32)
    normals = np.asarray(normals, dtype=np.float32)
    h, w = depth.shape
    covered = depth > 0.0
    pos = _view_position(depth, proj_xy)

    # Per-pixel kernel basis: Gram-Schmidt against the tiled rotation, so
    # neighbouring pixels sample different directions.
    tile = rotations.shape[0]
    ry, rx = np.meshgrid(np.arange(h) % tile, np.arange(w) % tile, indexing="ij")
    rot = rotations[ry, rx]
    rand = np.stack([rot[..., 0], rot[..., 1], np.zeros((h, w), dtype=np.float32)], axis=2)
    n = normals
    tangent = rand - n * np.sum(rand * n, axis=2, keepdims=True)
    tlen = np.linalg.norm(tangent, axis=2, keepdims=True)
    # A normal parallel to the rotation leaves a zero tangent; any
    # perpendicular direction will do there.
    fallback = np.zeros_like(tangent)
    fallback[..., 1] = 1.0
    tangent = np.where(tlen > 1e-6, tangent / np.maximum(tlen, 1e-6), fallback)
    bitangent = np.cross(n, tangent)

    occluded = np.zeros((h, w), dtype=np.float32)
    for k in kernel:
        offset = (tangent * k[0] + bitangent * k[1] + n * k[2]) * radius
        sample = pos + offset
        ix, iy, ok = _project(sample, proj_xy, (h, w))
        sample_depth = depth[iy, ix]
        sample_dist = -sample[..., 2]
        # An occluder is geometry nearer the camera than the sample point.
        hit = ok & (sample_depth > 0.0) & (sample_depth < sample_dist - bias)
        # Range check: a wall far behind the pixel is not its occluder.
        delta = np.abs(depth - sample_depth)
        weight = np.clip(radius / np.maximum(delta, 1e-6), 0.0, 1.0)
        occluded += np.where(hit, weight, 0.0).astype(np.float32)

    out = 1.0 - occluded / float(len(kernel))
    return np.where(covered, np.clip(out, 0.0, 1.0), 1.0).astype(np.float32)
