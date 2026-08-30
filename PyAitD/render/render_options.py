# SPDX-License-Identifier: GPL-2.0-only
"""Pygame-free rendering options: validation, clamping, and menu cycling."""
from dataclasses import dataclass, replace

from PyAitD.render.materials import REALISM_MODES

SHADING_MODES = ("flat", "lambert", "smooth")
BACKGROUND_FILTERS = ("nearest", "bilinear", "xbr")
SCALE_STEPS = (1, 2, 3, 4, 6, 8)
MIN_SCALE, MAX_SCALE = 1, 8
LIGHTING_MODES = ("fixed", "scene")
MSAA_LEVELS = (0, 2, 4, 8)
SMOOTHING_LEVELS = (0, 1, 2, 3)   # 2**level segments per edge; 0 draws the flat mesh exactly as before
# hard: today's per-actor projected silhouette, thresholded, verbatim.
# soft: a penumbra that hardens at contact, every actor's shadow gathered
# into one pass before any body is drawn, and a light-view depth map that
# lets bodies shadow themselves and each other. Both under lighting="scene"
# only; "fixed" casts nothing either way.
SHADOW_MODES = ("hard", "soft")
# off: today's single-target path -- bodies drawn straight over the plate,
# at the internal resolution, with the plate's tone and dither ignored.
# on: bodies resolved into their own RGBA layer and composited back through
# the plate's softness, tone curve and grain. Under lighting="scene" only;
# "fixed" runs the single-target path either way.
INTEGRATION_MODES = ("off", "on")


@dataclass(frozen=True)
class RenderOptions:
    scale: int = 4
    shading: str = "smooth"
    background_filter: str = "bilinear"
    override_dir: str | None = None
    lighting: str = "scene"
    msaa: int = 4
    realism: str = "enhanced"
    smoothing: int = 2
    shadows: str = "soft"
    integration: str = "off"

    def to_payload(self):
        return {
            "scale": self.scale,
            "shading": self.shading,
            "background_filter": self.background_filter,
            "override_dir": self.override_dir,
            "lighting": self.lighting,
            "msaa": self.msaa,
            "realism": self.realism,
            "smoothing": self.smoothing,
            "shadows": self.shadows,
            "integration": self.integration,
        }


def validate_render_options(payload):
    defaults = RenderOptions()
    if not isinstance(payload, dict):
        return defaults, "render must be an object"
    errors = []
    scale = payload.get("scale")
    if type(scale) is int:
        scale = max(MIN_SCALE, min(MAX_SCALE, scale))
    else:
        errors.append("scale must be an integer")
        scale = defaults.scale
    shading = payload.get("shading")
    if shading not in SHADING_MODES:
        errors.append(f"shading must be one of {', '.join(SHADING_MODES)}")
        shading = defaults.shading
    background_filter = payload.get("background_filter")
    if background_filter not in BACKGROUND_FILTERS:
        errors.append(f"background_filter must be one of {', '.join(BACKGROUND_FILTERS)}")
        background_filter = defaults.background_filter
    override_dir = payload.get("override_dir")
    if override_dir is not None and (not isinstance(override_dir, str) or not override_dir):
        errors.append("override_dir must be null or a non-empty string")
        override_dir = None
    lighting = payload.get("lighting")
    if lighting not in LIGHTING_MODES:
        errors.append(f"lighting must be one of {', '.join(LIGHTING_MODES)}")
        lighting = defaults.lighting
    msaa = payload.get("msaa")
    # `type(x) is int` rejects bools: `False in MSAA_LEVELS` is True, since
    # False == 0. Same guard the scale field above uses, same reason.
    if not (type(msaa) is int and msaa in MSAA_LEVELS):
        errors.append(f"msaa must be one of {', '.join(str(v) for v in MSAA_LEVELS)}")
        msaa = defaults.msaa
    realism = payload.get("realism")
    if realism not in REALISM_MODES:
        errors.append(f"realism must be one of {', '.join(REALISM_MODES)}")
        realism = defaults.realism
    smoothing = payload.get("smoothing")
    # bool-rejecting like msaa: True in (0, 1, 2, 3) is True, and is not a level
    if not (type(smoothing) is int and smoothing in SMOOTHING_LEVELS):
        errors.append(f"smoothing must be one of {', '.join(str(v) for v in SMOOTHING_LEVELS)}")
        smoothing = defaults.smoothing
    shadows = payload.get("shadows")
    if shadows not in SHADOW_MODES:
        errors.append(f"shadows must be one of {', '.join(SHADOW_MODES)}")
        shadows = defaults.shadows
    integration = payload.get("integration")
    if integration not in INTEGRATION_MODES:
        errors.append(f"integration must be one of {', '.join(INTEGRATION_MODES)}")
        integration = defaults.integration
    options = RenderOptions(scale, shading, background_filter, override_dir, lighting, msaa, realism, smoothing, shadows, integration)
    return options, ("; ".join(errors) or None)


def _cycle(values, current):
    return values[(values.index(current) + 1) % len(values)]


def cycle_scale(options):
    current = options.scale if options.scale in SCALE_STEPS else SCALE_STEPS[0]
    return replace(options, scale=_cycle(SCALE_STEPS, current))


def cycle_shading(options):
    return replace(options, shading=_cycle(SHADING_MODES, options.shading))


def cycle_filter(options):
    return replace(options, background_filter=_cycle(BACKGROUND_FILTERS, options.background_filter))


def cycle_lighting(options):
    return replace(options, lighting=_cycle(LIGHTING_MODES, options.lighting))


def cycle_msaa(options):
    current = options.msaa if options.msaa in MSAA_LEVELS else MSAA_LEVELS[0]
    return replace(options, msaa=_cycle(MSAA_LEVELS, current))


def cycle_realism(options):
    return replace(options, realism=_cycle(REALISM_MODES, options.realism))


def cycle_smoothing(options):
    current = options.smoothing if options.smoothing in SMOOTHING_LEVELS else SMOOTHING_LEVELS[0]
    return replace(options, smoothing=_cycle(SMOOTHING_LEVELS, current))


def cycle_shadows(options):
    return replace(options, shadows=_cycle(SHADOW_MODES, options.shadows))


def cycle_integration(options):
    return replace(options, integration=_cycle(INTEGRATION_MODES, options.integration))
