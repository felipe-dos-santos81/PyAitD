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


@dataclass(frozen=True)
class RenderOptions:
    scale: int = 4
    shading: str = "smooth"
    background_filter: str = "bilinear"
    override_dir: str | None = None
    lighting: str = "scene"
    msaa: int = 4
    realism: str = "enhanced"

    def to_payload(self):
        return {
            "scale": self.scale,
            "shading": self.shading,
            "background_filter": self.background_filter,
            "override_dir": self.override_dir,
            "lighting": self.lighting,
            "msaa": self.msaa,
            "realism": self.realism,
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
    options = RenderOptions(scale, shading, background_filter, override_dir, lighting, msaa, realism)
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
