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
# decile is whichever pixels argsort happened to put last), so it is
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

    order = np.argsort(luma)
    count = len(order)
    bright = order[-max(1, int(count * BRIGHT_FRACTION)):]
    dark = order[:max(1, int(count * DARK_FRACTION))]

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
