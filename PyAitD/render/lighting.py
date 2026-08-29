# SPDX-License-Identifier: GPL-2.0-only
"""A per-camera light estimated from that camera's background image, and the
ground-plane projection the shadow pass uses.

The AITD1 data files carry no light information at all -- a Camera has a
position, three angles and three focal lengths, and nothing else -- so the
only evidence about how a room is lit is the picture of the room. This
module reads that picture.

Conventions, which everything downstream depends on:

- Camera-space y grows *downward* (world.CameraState.project computes
  `sy = y * focal3 / depth + SCREEN_CENTER_Y` with no sign flip), and +z
  points away from the camera into the scene (`depth = z + focal1`).
- `SceneLight.direction` points *from the surface toward the light*, so a
  light above the scene has a negative y and a light in front of it has a
  negative z. The direction light *travels* is `-direction`.

Pure numpy: no pygame, no GL, no engine imports."""
from dataclasses import dataclass

import numpy as np

# Rec. 709 luma weights: perceived brightness, not a channel average.
LUMA = np.array([0.2126, 0.7152, 0.0722])

# The minimum vertical component of a light, as a fraction of its unit
# length. A light level with the floor projects a shadow to the horizon, so
# two independent places force the same cone: estimate_light lifts its own
# camera-space `direction` at least this far above the scene, and
# project_to_plane tips whatever `travel` it is handed at least this far
# below the horizontal. The two are separate enforcements on purpose --
# `direction` is camera space and `travel` is world space, and the rotation
# between them does not preserve a bound on the y component (see
# project_to_plane).
MIN_UP = 0.35
# A fixed toward-the-viewer component, so the light can never degenerate
# into pure sidelight that rakes every surface at once.
FORWARD = 0.8
# What counts as "the lit part" and "the shadowed part" of a plate.
BRIGHT_FRACTION = 0.10
DARK_FRACTION = 0.25
# Below this, the bright centroid is noise (a uniform plate's brightest
# decile is whichever pixels the partition happened to put last), so it is
# discarded in favour of a frontal light.
CONTRAST_FLOOR = 0.02


@dataclass(frozen=True)
class SceneLight:
    direction: tuple    # unit, camera space, pointing from surface toward light
    key: tuple          # 0..1 linear RGB: what a lit surface in this room looks like
    ambient: tuple      # 0..1 linear RGB: what an unlit one looks like
    contrast: float     # 0..1: how directional this room's light is


def _unit(vec):
    vec = np.asarray(vec, dtype=np.float64)
    length = float(np.linalg.norm(vec))
    return tuple(vec / length) if length else (0.0, -1.0, 0.0)


# The rig GLBackend used before this module existed. Its y is negative, so by
# the convention above it was already an "above the scene" light -- but the
# old shader took abs() of the dot product, so the sign never actually
# mattered, which is exactly why the old lighting had no lit and dark side.
# Kept as FrameDescription.light's default so frames built without a resolver
# still carry a usable light.
LEGACY_LIGHT = SceneLight(_unit((-0.3, -0.5, -0.8)), (0.45,) * 3, (0.55,) * 3, 0.45)


def estimate_light(pixels):
    """A SceneLight for a camera, read off its background image."""
    image = np.asarray(pixels)
    height, width = image.shape[:2]
    rgb = image.reshape(-1, 3).astype(np.float64) / 255.0
    luma = rgb @ LUMA

    # argpartition, not argsort: only the two quantile boundaries matter,
    # and a full sort is O(N log N) over every pixel. Shipped plates are
    # 320x200, but overrides -- including AI-regenerated ones -- can be any
    # size, and the sort took this function to 83 ms at 1280x800 and 211 ms
    # at 1920x1200 against a 20 ms tick -- ~10 dropped ticks on first entry
    # to a camera with a 1080p override. Now 19 ms and 49 ms. Both
    # routines break equal-luma ties arbitrarily and neither documents an
    # order, so the two disagree about *which* of the tied pixels land in
    # each set; over the 144 shipped plates that leaves key, ambient and
    # contrast identical to float summation noise (<= 1e-13) and moves the
    # bright centroid by at most 0.04 of its +-1 range -- a light direction
    # 0.06 degrees different at the median and 1.8 degrees at the worst,
    # well inside the noise an estimate off a picture is already making.
    count = luma.size
    num_bright = max(1, int(count * BRIGHT_FRACTION))
    num_dark = max(1, int(count * DARK_FRACTION))
    order = np.argpartition(luma, (num_dark - 1, count - num_bright))
    bright = order[count - num_bright:]
    dark = order[:num_dark]

    key = tuple(rgb[bright].mean(axis=0))
    ambient = tuple(rgb[dark].mean(axis=0))

    bright_luma = float(luma[bright].mean())
    dark_luma = float(luma[dark].mean())
    contrast = (0.0 if bright_luma <= 0.0
                else float(np.clip((bright_luma - dark_luma) / bright_luma, 0.0, 1.0)))

    weights = luma[bright]
    total = float(weights.sum())
    if contrast < CONTRAST_FLOOR or total <= 0.0:
        offset_x = offset_y = 0.0
    else:
        rows, cols = np.divmod(bright, width)
        offset_x = float((cols * weights).sum() / total) / width * 2.0 - 1.0
        offset_y = float((rows * weights).sum() / total) / height * 2.0 - 1.0

    # min(), not max(): y grows downward, so "at least MIN_UP above" is
    # "no greater than -MIN_UP".
    direction = _unit((offset_x, min(offset_y, -MIN_UP), -FORWARD))
    # Clamping offset_y alone isn't sufficient: a large offset_x can push the
    # combined vector's norm above 1, and normalising then dilutes the
    # clamped y back above -MIN_UP. When that happens, pull the vector back
    # down onto the y == -MIN_UP cone, keeping its azimuth (the x:z ratio)
    # unchanged, so the elevation floor holds for every estimated light.
    if direction[1] > -MIN_UP:
        dx, _, dz = direction
        horizontal = float(np.hypot(dx, dz))
        scale = float(np.sqrt(1.0 - MIN_UP ** 2)) / horizontal
        direction = (dx * scale, -MIN_UP, dz * scale)
    return SceneLight(direction, key, ambient, contrast)


def key_weight(contrast):
    """The directional share of an actor's shading: how much of the light on
    a body comes from the key rather than from the fill.

    One of the two curves `contrast` drives; `shadow_opacity` is the other.
    They live side by side because they are easy to mistake for one map of
    one quantity, and are not: this one splits a *normalised* pair of tints
    whose lit sum is pinned to 1.0, so it can run the full 0.25..0.75 range
    without ever darkening or brightening the scene overall. The shadow's
    opacity multiplies the background by an *absolute* reflectance, so its
    range is deliberately shallower -- an opaque shadow at high contrast
    would drop a real room's plate to near black. Rebalancing one of them
    is not automatically a reason to move the other, but seeing only one of
    them is how they drifted apart in the first place."""
    return 0.25 + 0.5 * float(np.clip(contrast, 0.0, 1.0))


def shadow_opacity(contrast):
    """How strongly a ground shadow multiplies the background toward the
    room's raw ambient reflectance. See key_weight for why the two curves
    differ."""
    return 0.25 + 0.45 * float(np.clip(contrast, 0.0, 1.0))


# The widest per-channel ratio either shading tint is allowed: the room's
# hue survives, its saturation does not run away.
#
# The bound is set just under the brightness modulation the game already
# had. The fixed rig ran an actor's shade over 0.55..1.0 across one body, a
# 1.82:1 spread, so holding the *chromatic* spread below that keeps light
# and shade reading louder than hue -- a tint, not a recolour. The plates
# themselves are far more saturated than that: over the 144 shipped
# cameras the lit-side ratio of the un-capped tints reached 3.97, and the
# dark quartiles of unlit rooms are close to mono-channel (ratios in the
# thousands). At 3.97 a white palette entry rendered (255, 189, 117) and
# the opening room's blue-glass lantern came out bright orange; at 1.5 the
# same entry renders (255, 192, 170) and the lantern stays blue-grey.
MAX_TINT_RATIO = 1.5


def _tint(colour):
    """`colour` as a unit-mean hue, desaturated until its per-channel ratio
    is within MAX_TINT_RATIO. A colour with no light in it stays black
    rather than being normalised into a division by zero."""
    colour = np.asarray(colour, dtype=np.float64)
    mean = float(colour.mean())
    if mean <= 0.0:
        return np.zeros(3)
    colour = colour / mean
    hi, lo = float(colour.max()), float(colour.min())
    if hi <= MAX_TINT_RATIO * lo:
        return colour
    # Blend toward the colour's own mean -- 1.0, since it is unit-mean now
    # -- by exactly the amount that lands the ratio on the bound. Solving
    # ((1-t)hi + t) == R((1-t)lo + t) for t; the denominator is positive
    # whenever the numerator is, and t < 1 strictly even for a mono-channel
    # colour (lo == 0), so the hue's *direction* always survives.
    numerator = hi - MAX_TINT_RATIO * lo
    t = numerator / (numerator + (MAX_TINT_RATIO - 1.0))
    return colour * (1.0 - t) + t


def shading_terms(light):
    """`(key_tint, fill_tint)` multipliers for the actor shader: the room's
    hue as a directional share and a fill share, scaled so that a fully lit
    surface's `fill_tint + key_tint` peaks at exactly 1.0 in its strongest
    channel and no channel of it ever exceeds 1.0.

    These are *tints*, not reflectances: each carries only the hue of
    `light.key` / `light.ambient`, never their absolute brightness, so a
    dark room shades an actor with its colour without dimming it into
    invisibility. (`SceneLight.ambient` is also consumed raw, as an
    absolute reflectance, by the shadow composite -- a different quantity
    under a similar name.)

    Three properties the shader depends on, in order of how they are built:

    - **Bounded saturation.** Each tint is capped at MAX_TINT_RATIO between
      its own strongest and weakest channel. Since `max(u + v) <= max u +
      max v <= R(min u + min v) <= R * min(u + v)`, the lit multiplier and
      every wrapped value between it and the fill inherit the same bound.
    - **No clipping.** A single shared divisor -- the peak channel of the
      summed lit multiplier -- scales both terms, so `fill + key <= 1.0`
      per channel by construction. Sharing the divisor is what preserves
      the two terms' relationship; dividing each by its own mean, as this
      function once did, amplified a dark tinted room into a multiplier
      with channels up to 1.81 and clipped in 95% of shipped cameras.
    - **A predictable band.** For a neutral room this is exactly the old
      split: the lit side lands on 1.0 and the unlit side on
      `1 - key_weight(contrast)` -- 0.75 at zero contrast, 0.25 at full
      contrast, 0.40 at the 0.69 median contrast of the shipped plates. A
      tinted room's unlit side is that value reshaped by the fill's hue
      and by the shared divisor. Measured over the 144 shipped cameras:
      the lit side runs 0.667..1.0 per channel, and the unlit side
      0.170..0.542 -- except for the eight rooms whose darkest quartile is
      literally black, which have no fill colour at all and whose unlit
      side is therefore black, as it was before this function was
      rewritten."""
    weight = key_weight(light.contrast)
    key = _tint(light.key) * weight
    fill = _tint(light.ambient) * (1.0 - weight)
    peak = float((key + fill).max())
    if peak > 0.0:
        key, fill = key / peak, fill / peak
    return tuple(key), tuple(fill)


def _clamp_downward(travel):
    """`travel` as a unit vector whose y is at least MIN_UP, keeping its
    azimuth (the x:z ratio) unchanged.

    y grows downward, so "at least MIN_UP downward" is "no less than
    +MIN_UP" -- the mirror of the cone estimate_light forces on its
    upward-pointing `direction`. A vector already inside the cone is only
    normalised; one outside it (level with the ground, or travelling
    upward because the light ended up below the plane) is tipped down onto
    the cone's surface."""
    travel = np.asarray(travel, dtype=np.float64).reshape(3)
    length = float(np.linalg.norm(travel))
    if not length:
        return np.array([0.0, 1.0, 0.0])
    travel = travel / length
    if travel[1] >= MIN_UP:
        return travel
    horizontal = float(np.hypot(travel[0], travel[2]))
    if not horizontal:
        return np.array([0.0, 1.0, 0.0])
    scale = float(np.sqrt(1.0 - MIN_UP ** 2)) / horizontal
    return np.array([travel[0] * scale, MIN_UP, travel[2] * scale])


def project_to_plane(vertices, travel, plane_y):
    """Slide each vertex along `travel` onto the horizontal plane `y == plane_y`.

    `travel` is the direction light *travels* (`-SceneLight.direction`), in
    the same space as `vertices`. Whatever is handed in is first tipped onto
    the MIN_UP cone (see _clamp_downward), which is what bounds the
    horizontal throw at sqrt(1 - MIN_UP^2) / MIN_UP times the drop -- about
    2.7x -- for *any* input, and gives a level or upward-travelling light a
    downward shadow rather than none or one thrown behind the caster.

    The clamp lives here rather than being inherited from estimate_light
    because the guarantee estimate_light makes is a camera-space one. The
    shadow pass rotates `direction` into world space through an arbitrary
    camera rotation (`render_gl._draw_frame`), and a rotation with any pitch
    or roll does not preserve a bound on the y component: measured over
    every shipped (room, camera) pair, the unclamped world-space travel ran
    to 1.3M units of throw and pointed *upward* for four of them."""
    verts = np.asarray(vertices, dtype=np.float64).reshape(-1, 3)
    travel = _clamp_downward(travel)
    steps = (plane_y - verts[:, 1]) / travel[1]
    return verts + steps[:, None] * travel


# The light-view depth map every actor is rendered into under
# shadows="soft": one square map per frame, fitted to the frame's actors.
SHADOW_MAP_SIZE = 2048


def light_view_matrix(travel, corners, pad=0.0):
    """(matrix, extent): an orthographic light-view matrix over `corners`.

    `travel` is the direction light travels, in world space; it is tipped
    onto the MIN_UP cone exactly as project_to_plane does, so the map and
    the ground shadow always agree about where the light goes. `corners`
    is (K, 3) world points -- every actor's bounding-box corners; `pad`
    widens the box by that many world units on every side before the
    one-texel margin, so a receiver the shader pushes along its normal
    still lands inside the map.

    The matrix is column-vector, like camera_matrix: `matrix @ (x, y, z,
    1)` is clip space, x and y across the map and z growing along
    `travel`, so the depth test keeps what is nearest the light. Every
    corner lands strictly inside [-1, 1] on all three axes. `extent` is
    the (3,) light-space size of the box mapped onto [-1, 1]; its z is
    what turns a bias in world units into map depth. A single point still
    gives a finite, invertible matrix: every axis is at least one unit
    wide."""
    forward = _clamp_downward(travel)
    corners = np.asarray(corners, dtype=np.float64).reshape(-1, 3)
    # World y grows downward, so "up" is -y. When the light travels almost
    # straight down the vertical is no use as a hint: fall back to world x.
    up_hint = np.array([0.0, -1.0, 0.0])
    if abs(float(np.dot(forward, up_hint))) > 0.99:
        up_hint = np.array([1.0, 0.0, 0.0])
    right = np.cross(up_hint, forward)
    right /= np.linalg.norm(right)
    up = np.cross(forward, right)
    basis = np.stack([right, up, forward])              # rows: the light-space axes
    local = corners @ basis.T
    lo, hi = local.min(axis=0) - pad, local.max(axis=0) + pad
    centre = (lo + hi) / 2.0
    half = np.maximum((hi - lo) / 2.0, 0.5)             # at least one unit wide
    half += 2.0 * half / SHADOW_MAP_SIZE                 # one texel of margin per side
    extent = 2.0 * half
    view = np.eye(4)
    view[:3, :3] = basis
    ortho = np.eye(4)
    ortho[0, 0], ortho[1, 1], ortho[2, 2] = 1.0 / half
    ortho[:3, 3] = -centre / half
    return (ortho @ view).astype(np.float32), extent


def _shift(array, d, axis):
    """`out[p] = array[p + d]` along `axis`, zero beyond the edge."""
    out = np.zeros_like(array)
    n = array.shape[axis]
    if abs(d) >= n:
        return out
    src = [slice(None)] * array.ndim
    dst = [slice(None)] * array.ndim
    if d >= 0:
        src[axis], dst[axis] = slice(d, n), slice(0, n - d)
    else:
        src[axis], dst[axis] = slice(0, n + d), slice(-d, n)
    out[tuple(dst)] = array[tuple(src)]
    return out


def soften(coverage, radius, r_max):
    """The numpy twin of render_gl's two-pass penumbra blur (SHADOW_BLUR_FSH),
    which the GL test pins the shader against.

    `coverage` and `radius` are (H, W): coverage 0..1 and a per-pixel
    penumbra radius in pixels. A radius above `r_max` is outside the
    contract -- the loop only reaches that far, so the 1 / (2r + 1) weights
    would no longer sum to one -- and callers keep it in range rather than
    this clamping it, which would hide the mistake. The shader stores the
    radius as its complement, 1 - r / r_max, so that MAX blending keeps the
    smallest; that encoding is the texture's, not this function's, and the
    radius arrives here plain. Each covered pixel is spread over
    a box of *its own* radius -- (2r + 1) pixels per axis, weight
    1 / (2r + 1) each -- horizontally, then vertically, carrying the
    largest radius that reached a pixel into the second pass. Written as a
    gather (each output pixel asks which neighbours reach it), which is
    the form a fragment shader can take. A radius-0 pixel spreads nowhere:
    a foot on the plane stays sharp while the head's shadow goes soft.
    Coverage is clamped to 1.0 after each pass."""
    cover = np.asarray(coverage, dtype=np.float64)
    reach = np.floor(np.asarray(radius, dtype=np.float64) + 0.5)
    for axis in (1, 0):
        out = np.zeros_like(cover)
        carried = np.zeros_like(cover)
        for d in range(-r_max, r_max + 1):
            shifted_cover = _shift(cover, d, axis)
            shifted_reach = _shift(reach, d, axis)
            hits = (shifted_cover > 0.0) & (abs(d) <= shifted_reach)
            out += np.where(hits, shifted_cover / (2.0 * shifted_reach + 1.0), 0.0)
            carried = np.where(hits, np.maximum(carried, shifted_reach), carried)
        cover, reach = np.minimum(out, 1.0), carried
    return cover.astype(np.float32)
