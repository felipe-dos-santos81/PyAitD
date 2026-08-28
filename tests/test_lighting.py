# SPDX-License-Identifier: GPL-2.0-only
import numpy as np
import pytest

from PyAitD.engine.world import CameraState
from PyAitD.render.lighting import (
    FORWARD, LEGACY_LIGHT, MIN_UP, SceneLight, estimate_light, project_to_plane,
    shading_terms,
)

pytestmark = pytest.mark.render


def _plate(fill=(0, 0, 0)):
    return np.full((200, 320, 3), fill, dtype=np.uint8)


def test_bright_region_top_left_puts_the_light_up_and_left():
    plate = _plate()
    plate[10:50, 10:60] = (255, 250, 230)
    light = estimate_light(plate)
    assert light.direction[0] < 0      # the light is to the left
    assert light.direction[1] < 0      # and above: screen y grows downward
    assert light.direction[2] < 0      # and in front of the scene
    assert np.isclose(np.linalg.norm(light.direction), 1.0)


def test_bright_region_bottom_right_puts_the_light_right_but_still_above():
    plate = _plate()
    plate[150:190, 260:310] = (255, 250, 230)
    light = estimate_light(plate)
    assert light.direction[0] > 0
    # a floor-lit room would cast an unusable upward shadow, so the
    # estimator clamps the light to always sit above the scene
    assert light.direction[1] <= -MIN_UP


def test_key_and_ambient_are_the_bright_and_dark_means():
    plate = _plate((20, 20, 40))
    plate[:20] = (200, 180, 160)
    light = estimate_light(plate)
    assert light.key[0] > light.ambient[0]
    assert light.ambient[2] > light.ambient[0]      # the dark region's blue cast survives
    assert 0.0 <= light.contrast <= 1.0
    assert light.contrast > 0.5                     # a bright band on a dark field


def test_uniform_plate_is_low_contrast_and_frontal():
    light = estimate_light(_plate((128, 128, 128)))
    assert light.contrast == pytest.approx(0.0, abs=1e-6)
    # with no contrast the centroid carries no information, so it is
    # discarded rather than read off argsort's arbitrary tie order
    assert light.direction[0] == pytest.approx(0.0)
    assert light.direction == pytest.approx(
        tuple(np.array([0.0, -MIN_UP, -FORWARD]) / np.linalg.norm([0.0, MIN_UP, FORWARD])))


@pytest.mark.parametrize("fill", [(0, 0, 0), (255, 255, 255)])
def test_degenerate_plates_still_produce_a_usable_light(fill):
    light = estimate_light(_plate(fill))
    assert np.isclose(np.linalg.norm(light.direction), 1.0)
    assert light.direction[1] <= -MIN_UP
    assert light.direction[2] < 0
    assert light.contrast == pytest.approx(0.0, abs=1e-6)


def test_shading_terms_are_unit_mean_tints_split_by_contrast():
    flat = SceneLight((0.0, -1.0, 0.0), (0.5, 0.5, 0.5), (0.2, 0.2, 0.2), 0.0)
    key, ambient = shading_terms(flat)
    assert np.mean(key) == pytest.approx(0.25)
    assert np.mean(ambient) == pytest.approx(0.75)
    assert np.mean(key) + np.mean(ambient) == pytest.approx(1.0)

    harsh = SceneLight((0.0, -1.0, 0.0), (0.5, 0.5, 0.5), (0.2, 0.2, 0.2), 1.0)
    key, ambient = shading_terms(harsh)
    assert np.mean(key) == pytest.approx(0.75)
    assert np.mean(ambient) == pytest.approx(0.25)


def test_shading_terms_keep_the_rooms_hue():
    warm = SceneLight((0.0, -1.0, 0.0), (0.6, 0.5, 0.4), (0.1, 0.1, 0.3), 0.5)
    key, ambient = shading_terms(warm)
    assert key[0] > key[2]          # a warm key stays warm
    assert ambient[2] > ambient[0]  # a cold fill stays cold


def test_shading_terms_survive_a_black_plate():
    black = SceneLight((0.0, -1.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 0.0)
    key, ambient = shading_terms(black)
    assert key == (0.0, 0.0, 0.0) and ambient == (0.0, 0.0, 0.0)


def test_project_to_plane_lands_every_vertex_on_the_plane():
    verts = np.array([[0.0, -100.0, 0.0], [50.0, -40.0, 20.0], [-30.0, 0.0, 10.0]])
    out = project_to_plane(verts, (0.0, 1.0, 0.0), 0.0)
    assert np.allclose(out[:, 1], 0.0)
    # a straight-down light drops each vertex straight down
    assert np.allclose(out[:, [0, 2]], verts[:, [0, 2]])


def test_project_to_plane_throws_the_shadow_along_the_light():
    verts = np.array([[0.0, -100.0, 0.0]])
    travel = np.array([1.0, 1.0, 0.0]) / np.sqrt(2.0)
    out = project_to_plane(verts, travel, 0.0)
    assert out[0] == pytest.approx([100.0, 0.0, 0.0])


# The horizontal throw project_to_plane guarantees for a 100-unit drop.
_BOUND = 100.0 * np.sqrt(1 - MIN_UP ** 2) / MIN_UP


@pytest.mark.parametrize("travel", [
    (1.0, 0.0, 0.0),        # level with the ground: would project to infinity
    (1.0, -0.2, 0.0),       # travelling upward: would throw behind the caster
    (0.6, 0.05, -0.8),      # a shallow but downward light
    (0.0, 0.0, 0.0),        # degenerate
    (30.0, 1.0, -40.0),     # not unit length
])
def test_project_to_plane_bounds_the_throw_for_any_travel(travel):
    # The bound is enforced here, not inherited from estimate_light: this
    # function is called with world-space travel, and no invariant on a
    # camera-space direction survives an arbitrary camera rotation.
    verts = np.array([[0.0, -100.0, 0.0]])
    out = project_to_plane(verts, travel, 0.0)
    assert np.allclose(out[:, 1], 0.0)
    assert np.linalg.norm(out[0, [0, 2]]) <= _BOUND + 1e-9


def test_project_to_plane_drops_an_upward_light_along_its_own_azimuth():
    # A light that ends up below the ground plane still casts downward, and
    # on the side the light travels toward -- not behind the caster.
    verts = np.array([[0.0, -100.0, 0.0]])
    out = project_to_plane(verts, (1.0, -0.2, 0.0), 0.0)
    assert out[0, 0] > 0.0
    assert out[0, 2] == pytest.approx(0.0)


def test_a_rotated_camera_still_lands_inside_the_bounded_throw():
    # The regression this whole clamp exists for. estimate_light guarantees
    # direction[1] <= -MIN_UP in *camera* space; the shadow pass consumes
    # -(rot.T @ direction) in *world* space. A yaw-only camera maps world y
    # onto camera y exactly, so it cannot see the difference -- but 139 of
    # AITD1's 144 shipped cameras carry a pitch or a roll, and those do
    # destroy the invariant. floor 3 camera 14's angles below take the
    # world-space travel *upward*.
    from PyAitD.render.render_gl import rotation_matrix

    plate = _plate()
    plate[100:110, 300:320] = 255
    direction = np.array(estimate_light(plate).direction)
    assert direction[1] <= -MIN_UP          # the camera-space guarantee holds
    verts = np.array([[0.0, -100.0, 0.0]])
    angles = [
        (0, 256, 0),        # yaw only: the one case in which travel[1] == -direction[1]
        (947, 821, 24),     # floor 3 camera 14, the worst shipped pair
        (895, 0, 0),        # floor 7 camera 5: pure pitch
        (608, 0, 128),      # pitch and roll together
    ]
    escaped = False
    for alpha, beta, gamma in angles:
        state = CameraState(alpha, beta, gamma, 0, 0, 0, 1, 1, 1).angles()
        travel = -(rotation_matrix(state).T @ direction)
        escaped |= travel[1] < MIN_UP       # the raw travel leaves the cone
        out = project_to_plane(verts, travel, 0.0)
        assert np.allclose(out[:, 1], 0.0)
        assert np.linalg.norm(out[0, [0, 2]]) <= _BOUND + 1e-9
    # ...and the assertions above are not vacuous: without the clamp, at
    # least one of these rotations really does escape the cone.
    assert escaped


def test_legacy_light_is_the_old_hard_coded_rig():
    assert np.isclose(np.linalg.norm(LEGACY_LIGHT.direction), 1.0)
    assert LEGACY_LIGHT.key == (0.45, 0.45, 0.45)
    assert LEGACY_LIGHT.ambient == (0.55, 0.55, 0.55)
