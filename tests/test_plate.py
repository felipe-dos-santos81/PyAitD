# SPDX-License-Identifier: GPL-2.0-only
import numpy as np
import pytest

from PyAitD.render.plate import (
    CLASSIC_PLATE_SIZE, NEUTRAL_PLATE, PlateProfile, estimate_plate, grain_retention,
    softness,
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


def _gl_linear_upscale(src, cell):
    """One channel magnified by an integer `cell` the way GL_LINEAR does:
    target pixel `j` samples the source at `(j + 0.5) / cell - 0.5`, with
    the two straddling texels weighted by the fractional part and the
    border clamped. This is the operation `grain_retention` models, written
    out independently so the test is evidence about the derivation rather
    than a restatement of it."""
    height, width = src.shape

    def taps(count):
        x = (np.arange(count * cell) + 0.5) / cell - 0.5
        lo = np.floor(x).astype(int)
        return np.clip(lo, 0, count - 1), np.clip(lo + 1, 0, count - 1), x - lo

    x0, x1, fx = taps(width)
    y0, y1, fy = taps(height)
    rows = src[:, x0] * (1.0 - fx) + src[:, x1] * fx
    return rows[y0, :] * (1.0 - fy)[:, None] + rows[y1, :] * fy[:, None]


@pytest.mark.parametrize("cell", [2, 3, 4, 6, 8])
def test_grain_retention_predicts_a_synthetic_upscale(cell):
    # The derivation's evidence, on synthetic noise rather than on game
    # data: `grain` models the plate's dither as white, so a white field is
    # exactly the input the retention factor claims to be right about.
    # Upscale it the way the filter does, average each cell back down --
    # the cell mean is what the composite's one-value-per-cell grain has to
    # match -- and compare the RMS before and after.
    rng = np.random.default_rng(7)
    src = rng.normal(0.0, 1.0, (200, 320))
    up = _gl_linear_upscale(src, cell)
    cells = up.reshape(200, cell, 320, cell).mean(axis=(1, 3))
    measured = cells.std() / src.std()
    predicted = grain_retention("bilinear", CLASSIC_PLATE_SIZE, (320 * cell, 200 * cell))
    # 2% covers the edge-clamped border and the finite sample; the two
    # agree to about 0.5% at every cell above. A hardcoded constant would
    # pass this test at one cell and fail it at cell 3, where the odd-cell
    # kernel is [1/9, 7/9, 1/9] rather than [1/8, 3/4, 1/8].
    assert measured == pytest.approx(predicted, rel=0.02)


def test_grain_retention_is_five_eighths_ish_at_every_even_cell():
    # The closed form, stated as numbers so a later edit cannot drift it:
    # 2v^2 + (1 - 2v)^2 with v = 1/8 is 0.59375, independent of cell, and
    # cell 3's v = 1/9 makes it 51/81.
    for cell in (2, 4, 6, 8):
        assert grain_retention("bilinear", CLASSIC_PLATE_SIZE,
                               (320 * cell, 200 * cell)) == pytest.approx(0.59375)
    assert grain_retention("bilinear", CLASSIC_PLATE_SIZE, (960, 600)) == pytest.approx(51 / 81)


@pytest.mark.parametrize("filter_name", ["bilinear", "xbr", "nearest"])
@pytest.mark.parametrize("target", [(320, 200), (160, 100)])
def test_nothing_is_lost_at_or_below_cell_one(filter_name, target):
    # No magnification, so no attenuation -- and this is the case
    # test_grain_lands_at_the_plates_own_amplitude renders at, which is why
    # that test's numbers are unmoved by the retention factor.
    assert grain_retention(filter_name, CLASSIC_PLATE_SIZE, target) == 1.0


@pytest.mark.parametrize("filter_name", ["nearest", "xbr"])
def test_the_nearest_sampled_filters_keep_the_whole_dither(filter_name):
    # Both sample with GL_NEAREST and never average two texels, so every
    # displayed pixel is some source texel and the dither arrives intact.
    assert grain_retention(filter_name, CLASSIC_PLATE_SIZE, (1280, 800)) == 1.0


def test_xbr_falls_back_to_the_bilinear_retention_off_the_classic_size():
    # The same fallback softness makes, for the same reason:
    # _draw_background runs the xbr shader only at 320x200 and uses
    # GL_LINEAR anywhere else, so off that size the linear attenuation is
    # the one that actually happened.
    assert grain_retention("xbr", (640, 400), (1280, 800)) == pytest.approx(0.59375)
    assert grain_retention("nearest", (640, 400), (1280, 800)) == 1.0


def test_a_fractional_cell_is_charged_the_even_cell_attenuation():
    # An override plate at an awkward size: cell 1.42 rounds to 2 rather
    # than to 1, so the grain comes out weaker than the plate's rather
    # than stronger. The safe direction, and the docstring says so.
    assert grain_retention("bilinear", (900, 563), (1280, 800)) == pytest.approx(0.59375)
