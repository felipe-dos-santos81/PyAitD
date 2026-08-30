# SPDX-License-Identifier: GPL-2.0-only
import numpy as np
import pytest

from PyAitD.render.plate import (
    CLASSIC_PLATE_SIZE, NEUTRAL_PLATE, PlateProfile, estimate_plate, softness,
)

pytestmark = pytest.mark.render


def test_black_and_white_are_the_percentile_means_by_construction():
    # 100x100: the darkest and brightest 1% are 100 pixels each, and this
    # plate is built so those two sets are exactly the two painted bands.
    plate = np.full((100, 100, 3), 128, np.uint8)
    plate[0] = (10, 20, 30)      # 100 darkest pixels
    plate[99] = (200, 210, 220)  # 100 brightest
    profile = estimate_plate(plate)
    assert profile.black == pytest.approx((10 / 255, 20 / 255, 30 / 255))
    assert profile.white == pytest.approx((200 / 255, 210 / 255, 220 / 255))


def test_a_uniform_plate_has_zero_grain():
    # Not `== 0.0`: the 3x3 mean of nine identical floats is the same value
    # only up to rounding, so a uniform plate's residual is ~1e-17, not a
    # hard zero. NEUTRAL_PLATE's exact 0.0 is a literal, not this.
    assert estimate_plate(np.full((64, 64, 3), 77, np.uint8)).grain < 1e-12


def test_a_checkerboard_carries_its_dither_amplitude():
    # A 1px checkerboard's 3x3 mean is 5/9 of white at a white pixel and
    # 4/9 at a black one, so every interior residual is 4/9 of white's luma.
    rows, cols = np.indices((64, 64))
    plate = np.zeros((64, 64, 3), np.uint8)
    plate[(rows + cols) % 2 == 0] = 255
    grain = estimate_plate(plate).grain
    assert 0.40 < grain < 0.46


def test_an_all_black_plate_is_total():
    profile = estimate_plate(np.zeros((32, 32, 3), np.uint8))
    assert profile.black == pytest.approx((0.0, 0.0, 0.0))
    assert profile.white == pytest.approx((0.0, 0.0, 0.0))
    assert profile.grain == 0.0        # every term is exactly zero here


def test_an_all_white_plate_is_total():
    profile = estimate_plate(np.full((32, 32, 3), 255, np.uint8))
    assert profile.black == pytest.approx((1.0, 1.0, 1.0))
    assert profile.white == pytest.approx((1.0, 1.0, 1.0))
    assert profile.grain < 1e-12       # float rounding, not a hard zero


def test_the_neutral_plate_is_the_identity_profile():
    assert NEUTRAL_PLATE == PlateProfile((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), 0.0)


@pytest.mark.parametrize("filter_name,sigma,pixelate", [
    ("bilinear", 0.35 * 4, False),
    ("xbr", 0.15 * 4, False),
    ("nearest", 0.0, True),
])
def test_softness_at_cell_four(filter_name, sigma, pixelate):
    got = softness(filter_name, CLASSIC_PLATE_SIZE, (1280, 800))
    assert got[0] == pytest.approx(sigma)
    assert got[1] == pytest.approx(4.0)
    assert got[2] is pixelate


@pytest.mark.parametrize("filter_name", ["bilinear", "xbr", "nearest"])
@pytest.mark.parametrize("target,cell", [((320, 200), 1.0), ((160, 100), 0.5)])
def test_nothing_softens_or_pixelates_at_or_below_cell_one(filter_name, target, cell):
    # An override plate at or above the target resolution: nothing to match.
    assert softness(filter_name, CLASSIC_PLATE_SIZE, target) == (0.0, cell, False)


def test_xbr_falls_back_to_bilinear_softness_off_the_classic_size():
    # _draw_background only runs xBR at exactly 320x200; anywhere else it
    # falls back to GL_LINEAR, and the softness model falls back with it.
    assert softness("xbr", (640, 400), (1280, 800))[0] == pytest.approx(0.35 * 2)
