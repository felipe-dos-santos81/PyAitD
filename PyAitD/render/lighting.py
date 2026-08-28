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


def shading_terms(light):
    """`(key, ambient)` multipliers for the shader: unit-mean tints carrying
    the room's hue, split by contrast into a directional share and a fill
    share that sum to roughly 1.

    Keeping the sum near 1 is what stops a lit surface from drifting far
    from its palette colour: a fully lit face lands near `ambient + key == 1`
    and an unlit one falls to the fill share alone, which is the same
    0.55-to-1.0 band the old fixed rig produced."""
    weight = 0.25 + 0.5 * float(np.clip(light.contrast, 0.0, 1.0))
    key = np.asarray(light.key, dtype=np.float64)
    ambient = np.asarray(light.ambient, dtype=np.float64)
    key_mean = float(key.mean())
    ambient_mean = float(ambient.mean())
    # A pitch-black plate has no hue to preserve and no light to give: it
    # stays black rather than being normalised into a division by zero.
    key = key / key_mean * weight if key_mean > 0.0 else key
    ambient = ambient / ambient_mean * (1.0 - weight) if ambient_mean > 0.0 else ambient
    return tuple(key), tuple(ambient)


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
