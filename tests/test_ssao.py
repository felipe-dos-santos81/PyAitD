# SPDX-License-Identifier: GPL-2.0-only
"""render/ssao.py: the screen-space ambient occlusion twin.

Pure numpy -- the GL pass in render_gl.py is pinned against these same
functions by tests/test_render_gl.py, exactly as `soften` pins the
penumbra blur."""
import numpy as np
import pytest

from PyAitD.render.ssao import (
    SSAO_BIAS, SSAO_KERNEL_SIZE, SSAO_RADIUS,
    hemisphere_kernel, noise_rotations, ssao_reference,
)

pytestmark = pytest.mark.render


def _flat_plate(h=32, w=32, depth=500.0):
    """A wall square-on to the camera: constant depth, normals toward it.

    View space looks down -z, so a surface *facing* the camera has its
    normal pointing back along +z. Getting this sign wrong is not a
    cosmetic error: the hemisphere would push every sample away from the
    camera instead of toward it, and a flat plate would occlude itself
    (measured: min occlusion 0.125 with the sign flipped, 1.0 with it
    right)."""
    d = np.full((h, w), depth, dtype=np.float32)
    n = np.zeros((h, w, 3), dtype=np.float32)
    n[..., 2] = 1.0
    return d, n


def test_the_kernel_is_a_clustered_plus_z_hemisphere():
    k = hemisphere_kernel()
    assert k.shape == (SSAO_KERNEL_SIZE, 3)
    assert k.dtype == np.float32
    assert (k[:, 2] > 0.0).all()                 # every sample in the +z hemisphere
    lengths = np.linalg.norm(k, axis=1)
    assert (lengths <= 1.0 + 1e-6).all()
    # Clustered toward the origin: more than half the samples inside the
    # half-radius, which a uniform ball would not give (that is 12.5%).
    assert (lengths < 0.5).sum() > SSAO_KERNEL_SIZE // 2


def test_the_kernel_is_deterministic_for_a_seed():
    assert np.array_equal(hemisphere_kernel(seed=3), hemisphere_kernel(seed=3))
    assert not np.array_equal(hemisphere_kernel(seed=3), hemisphere_kernel(seed=4))


def test_the_rotation_tile_is_unit_vectors():
    r = noise_rotations()
    assert r.shape == (4, 4, 2)
    assert np.allclose(np.linalg.norm(r, axis=2), 1.0, atol=1e-6)


def test_a_flat_plate_occludes_nothing():
    d, n = _flat_plate()
    out = ssao_reference(d, n, hemisphere_kernel(), noise_rotations(), (2.0, 2.0))
    assert out.shape == (32, 32)
    # A plane cannot occlude itself: every sample lands in front of it.
    assert out.min() > 0.98


def test_occlusion_is_bounded_to_the_unit_range():
    rng = np.random.default_rng(5)
    d = rng.uniform(200.0, 900.0, (24, 24)).astype(np.float32)
    n = rng.normal(size=(24, 24, 3)).astype(np.float32)
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    out = ssao_reference(d, n, hemisphere_kernel(), noise_rotations(), (2.0, 2.0))
    assert out.min() >= 0.0 and out.max() <= 1.0


def test_a_nearby_step_occludes_the_pixels_beside_it():
    """A wall with a block of columns standing 10 units nearer the camera.

    Wall pixels next to that step have most of their hemisphere blocked by
    it and must come out darker; pixels far from it must not. Ten units
    against a 14-unit radius is deliberate -- the range check discards an
    occluder much further away than the radius, so a step of 200 units
    would (correctly) occlude nothing at all."""
    h = w = 48
    d = np.full((h, w), 500.0, dtype=np.float32)
    d[:, :8] = 490.0
    n = np.zeros((h, w, 3), dtype=np.float32)
    n[..., 2] = 1.0
    out = ssao_reference(d, n, hemisphere_kernel(), noise_rotations(), (2.0, 2.0))
    beside = out[:, 8:11].mean()
    far = out[:, 30:40].mean()
    # Measured on the reference implementation: 0.9219 and 1.0000.
    assert beside < 0.96, beside
    assert far > 0.99, far


def test_zero_radius_occludes_nothing():
    """The neutral identity the GL pass leans on: with the radius at zero
    every sample lands on the pixel itself, and nothing is occluded."""
    rng = np.random.default_rng(9)
    d = rng.uniform(200.0, 900.0, (16, 16)).astype(np.float32)
    n = np.zeros((16, 16, 3), dtype=np.float32)
    n[..., 2] = 1.0
    out = ssao_reference(d, n, hemisphere_kernel(), noise_rotations(), (2.0, 2.0), radius=0.0)
    assert np.allclose(out, 1.0)


def test_background_pixels_are_untouched():
    """Depth exactly 0.0 marks a pixel the prepass never wrote. It must
    come back fully unoccluded, not darkened by whatever the neighbouring
    geometry happens to be."""
    d, n = _flat_plate()
    d[:8, :] = 0.0
    out = ssao_reference(d, n, hemisphere_kernel(), noise_rotations(), (2.0, 2.0))
    assert np.allclose(out[:8, :], 1.0)


def test_the_defaults_are_the_documented_constants():
    assert SSAO_KERNEL_SIZE == 16
    assert SSAO_RADIUS == 14.0
    assert SSAO_BIAS == 0.6
