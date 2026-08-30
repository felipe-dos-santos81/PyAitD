# SPDX-License-Identifier: GPL-2.0-only
"""What the room's own picture says about tone, dither and sharpness.

The actors are rendered clean: full contrast down to black and up to white,
a crisp edge at the internal resolution, no film grain. The plate they stand
on is none of those things -- it is a 320x200 image with a lifted black, a
capped white, an ordered dither, and, once the background filter has blown
it up to the target size, an edge that spans several pixels. Reading those
four quantities off the plate is what lets the composite put the actor
inside the room rather than on top of it.

Pure numpy: no pygame, no GL, no engine imports."""
from dataclasses import dataclass

import numpy as np

from PyAitD.render.lighting import LUMA

# The size at which render_gl._draw_background actually runs xBR. Any other
# source falls back to GL_LINEAR there, and `softness` falls back with it:
# a model that claimed the xBR sigma for a 640x400 override would be
# describing a filter that did not run.
CLASSIC_PLATE_SIZE = (320, 200)

# Sigma per plate cell, by filter. Bilinear spreads a source texel's
# influence across its whole cell; xBR reconstructs edges and leaves them
# far crisper; nearest leaves none at all and is handled by `pixelate`.
BILINEAR_SIGMA = 0.35
XBR_SIGMA = 0.15

# The share of pixels at each end of the luma order that defines the room's
# floor and ceiling. Deliberately tighter than lighting.BRIGHT_FRACTION /
# DARK_FRACTION: those two want the *lit* and *shadowed* parts of a room, a
# broad statement about where the light is. These two want the extremes the
# tone curve has to land on, which is a much smaller set of pixels.
TAIL_FRACTION = 0.01


@dataclass(frozen=True)
class PlateProfile:
    black: tuple    # 0..1 linear RGB: the room's floor
    white: tuple    # 0..1 linear RGB: the room's ceiling
    grain: float    # 0..1: RMS luma residual against the plate's own 3x3 mean


# What a frame built without a resolver carries, and what makes the whole
# composite an identity: a black of 0 adds nothing at the toe, a white of 1
# subtracts nothing at the shoulder, and a grain of 0 adds no noise. Every
# term vanishes by construction, not by rounding.
NEUTRAL_PLATE = PlateProfile((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), 0.0)


def estimate_plate(pixels):
    """A PlateProfile for a camera, read off its background image.

    Deterministic and total: an all-black plate yields a black white and
    zero grain, and a uniform plate yields zero grain."""
    image = np.asarray(pixels)
    rgb = image.reshape(-1, 3).astype(np.float64) / 255.0
    luma = rgb @ LUMA

    # argpartition, not argsort: only the two quantile boundaries matter.
    # Same selection lighting.estimate_light uses, and the same reason --
    # a full sort over a 1080p override costs ~200 ms against a 20 ms tick.
    count = luma.size
    tail = max(1, int(count * TAIL_FRACTION))
    order = np.argpartition(luma, (tail - 1, count - tail))
    black = tuple(rgb[order[:tail]].mean(axis=0))
    white = tuple(rgb[order[count - tail:]].mean(axis=0))
    return PlateProfile(black, white, _grain(image))


def _grain(image):
    """RMS of the plate's luma residual against its own 3x3 box mean: the
    amplitude of its dither, at the plate's own resolution.

    Edge-padded rather than cropped, so the residual is defined for every
    pixel and a 1x1 plate is still total (its own mean, residual zero)."""
    luma = (image.astype(np.float64) / 255.0) @ LUMA
    height, width = luma.shape
    padded = np.pad(luma, 1, mode="edge")
    mean = sum(padded[dy:dy + height, dx:dx + width]
               for dy in range(3) for dx in range(3)) / 9.0
    return float(np.clip(np.sqrt(np.mean((luma - mean) ** 2)), 0.0, 1.0))


def grain_retention(background_filter, src_size, target_size):
    """The fraction of the plate's own dither amplitude that survives the
    upscale, at the scale of one plate cell. 1.0 when nothing is lost.

    `estimate_plate.grain` is a *source* amplitude: the RMS residual of the
    320x200 image against its own 3x3 mean. The composite needs a
    *displayed* one -- what the actor is standing next to is the plate
    after `background_filter` has blown it up, and a smoothing filter
    attenuates that dither on the way. Multiplying `grain` by this is what
    makes the two the same quantity; without it the actor is grained at an
    amplitude the room around it no longer has.

    Derivation, for a magnification of an integer `cell` under GL_LINEAR.
    Target pixel `j` samples the source at `x = (j + 0.5) / cell - 0.5`, so
    the `cell` target pixels covering source pixel `m` interpolate between
    `m` and one of its neighbours. Summing their weights and dividing by
    `cell`, the mean of the cell is `v*s[m-1] + (1 - 2v)*s[m] + v*s[m+1]`
    with `v = (cell**2 - cell % 2) / (8 * cell**2)` -- exactly 1/8 for
    every even cell, 1/9 at cell 3, and 0 at cell 1. For a dither modelled
    as white (which is precisely what `_grain`'s residual-against-the-3x3-
    mean estimator already assumes it is), a separable 2D kernel scales
    the RMS by the sum of its squared 1D weights, so the retention is
    `2v**2 + (1 - 2v)**2`: **0.59375 at every even cell**, 0.62963 at cell
    3, 1.0 at cell 1.

    `nearest` and `xbr` both retain 1.0, and for the same reason rather
    than by coincidence: both sample the source with GL_NEAREST and never
    average two texels, so every displayed pixel *is* some source texel and
    the dither arrives intact. `BG_FSH`'s xbr is a selection -- it returns
    either the nearest texel or a neighbour, never a blend -- and its
    branch is gated on finding an edge (`distance(h, v) < 0.05` with
    `distance(h, c) > 0.1`), which dither does not produce.

    The xBR-only-at-320x200 fallback is shared with `softness`, and must
    be: `render_gl._draw_background` runs the xbr shader only when the
    source really is `CLASSIC_PLATE_SIZE` and falls back to GL_LINEAR
    otherwise, so at any other size a model claiming xbr's retention would
    be describing a filter that did not run -- the same sentence, and the
    same bug, as `softness`'s.

    Non-integer cells (an override plate at an awkward size) round to the
    nearest integer cell, floored at 2, so a mild fractional magnification
    is charged the full even-cell attenuation. That errs toward a *weaker*
    grain than the plate's, which is the safe direction: the term is
    meant to sit under the room's own dither, not over it."""
    src_w = float(src_size[0])
    target_w = float(target_size[0])
    cell = target_w / src_w if src_w > 0.0 else 1.0
    if cell <= 1.0:
        return 1.0
    if background_filter == "nearest":
        return 1.0
    if background_filter == "xbr" and tuple(src_size) == CLASSIC_PLATE_SIZE:
        return 1.0
    n = max(2, int(round(cell)))
    v = (n * n - n % 2) / (8.0 * n * n)
    return 2.0 * v * v + (1.0 - 2.0 * v) ** 2


def dither_arrives_smoothed(background_filter, src_size, target_size):
    """True when the filter magnifies the plate by interpolating between
    source texels, so its dither reaches the screen as a ramp across each
    cell rather than as the source's own hard texels.

    Which construction the composite has to build the actor's grain with.
    Stated through `grain_retention` rather than beside it so the two
    cannot drift: a filter attenuates the dither exactly when it smooths
    it, and leaves the amplitude alone exactly when it samples the source
    intact (`nearest`, xbr at the classic size, or no magnification at
    all)."""
    return grain_retention(background_filter, src_size, target_size) < 1.0


def softness(background_filter, src_size, target_size):
    """(sigma_px, cell_px, pixelate) for a plate of `src_size` shown at
    `target_size` through `background_filter`. Both sizes are (width, height).

    `cell` is how many target pixels one plate pixel became. At or below 1 --
    an override plate at or above the target resolution -- there is nothing
    to match: the plate is as sharp as the actors are, so no softening and
    no pixelation. `nearest` leaves hard blocks, so the actor is fetched per
    cell rather than blurred."""
    src_w = float(src_size[0])
    target_w = float(target_size[0])
    cell = target_w / src_w if src_w > 0.0 else 1.0
    if cell <= 1.0:
        return 0.0, cell, False
    if background_filter == "nearest":
        return 0.0, cell, True
    if background_filter == "xbr" and tuple(src_size) == CLASSIC_PLATE_SIZE:
        return XBR_SIGMA * cell, cell, False
    return BILINEAR_SIGMA * cell, cell, False
