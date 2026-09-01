# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.render.render_options import (
    BACKGROUND_FILTERS, SHADING_MODES, RenderOptions, cycle_filter, cycle_scale,
    cycle_shading, validate_render_options,
)
import pytest

pytestmark = pytest.mark.render


def test_defaults():
    assert RenderOptions() == RenderOptions(4, "smooth", "bilinear", None, "scene", 4, "enhanced", 2)
    assert SHADING_MODES == ("flat", "lambert", "smooth")
    assert BACKGROUND_FILTERS == ("nearest", "bilinear", "xbr")


def test_realism_defaults_to_enhanced_and_cycles():
    from PyAitD.render.render_options import REALISM_MODES, cycle_realism
    assert REALISM_MODES == ("classic", "enhanced")
    options = RenderOptions()
    assert options.realism == "enhanced"
    assert cycle_realism(options).realism == "classic"
    assert cycle_realism(cycle_realism(options)).realism == "enhanced"
    assert RenderOptions(realism="classic").to_payload()["realism"] == "classic"


def test_invalid_realism_falls_back_alone():
    payload = RenderOptions().to_payload()
    payload["realism"] = "ultra"
    options, error = validate_render_options(payload)
    assert options == RenderOptions() and "realism" in error


def test_valid_payload_round_trips():
    options = RenderOptions(2, "flat", "xbr", "/tmp/ov")
    assert validate_render_options(options.to_payload()) == (options, None)


def test_each_invalid_field_falls_back_alone():
    options, error = validate_render_options(
        {"scale": 99, "shading": "smooth", "background_filter": "bilinear", "texture_dir": None,
         "lighting": "fixed", "msaa": 0, "realism": "enhanced", "smoothing": 0, "shadows": "soft", "integration": "on", "motion": "tick",
         "occlusion": "off", "atmosphere": "off"})
    assert options == RenderOptions(8, "smooth", "bilinear", None, "fixed", 0, "enhanced", 0, "soft", 2, "tick", "off", "off")  # clamped, not rejected
    assert error is None
    options, error = validate_render_options(
        {"scale": "x", "shading": "neon", "background_filter": "bilinear", "texture_dir": 3,
         "lighting": "fixed", "msaa": 0, "realism": "enhanced", "smoothing": 0, "shadows": "soft", "integration": "on", "motion": "tick",
         "occlusion": "off", "atmosphere": "off"})
    assert options == RenderOptions(4, "smooth", "bilinear", None, "fixed", 0, "enhanced", 0, "soft", 2, "tick", "off", "off")
    assert "scale" in error and "shading" in error and "texture_dir" in error


def test_non_dict_payload_is_all_defaults_with_error():
    assert validate_render_options(None) == (RenderOptions(), "render must be an object")


def test_cycles():
    o = RenderOptions()
    assert cycle_scale(o).scale == 6 and cycle_scale(RenderOptions(scale=8)).scale == 1
    assert cycle_shading(o).shading == "flat"
    assert cycle_filter(o).background_filter == "xbr"


def test_lighting_and_msaa_defaults_and_cycles():
    from PyAitD.render.render_options import (
        LIGHTING_MODES, MSAA_LEVELS, cycle_lighting, cycle_msaa,
    )
    assert LIGHTING_MODES == ("fixed", "scene")
    assert MSAA_LEVELS == (0, 2, 4, 8)
    options = RenderOptions()
    assert options.lighting == "scene" and options.msaa == 4
    assert cycle_lighting(options).lighting == "fixed"
    assert cycle_msaa(options).msaa == 8
    assert cycle_msaa(RenderOptions(msaa=8)).msaa == 0


def test_invalid_lighting_and_msaa_fall_back_alone():
    payload = RenderOptions().to_payload()
    payload["lighting"] = "neon"
    options, error = validate_render_options(payload)
    assert options == RenderOptions() and "lighting" in error
    payload = RenderOptions().to_payload()
    payload["msaa"] = 3
    options, error = validate_render_options(payload)
    assert options == RenderOptions() and "msaa" in error
    # a bool is not an int here: True/False must not slip through as 1/0
    payload = RenderOptions().to_payload()
    payload["msaa"] = False
    options, error = validate_render_options(payload)
    assert options == RenderOptions() and "msaa" in error


def test_smoothing_defaults_to_medium_and_cycles():
    from PyAitD.render.render_options import SMOOTHING_LEVELS, cycle_smoothing
    assert SMOOTHING_LEVELS == (0, 1, 2, 3)
    options = RenderOptions()
    assert options.smoothing == 2
    assert cycle_smoothing(options).smoothing == 3
    assert cycle_smoothing(RenderOptions(smoothing=3)).smoothing == 0
    assert RenderOptions(smoothing=2).to_payload()["smoothing"] == 2


def test_invalid_smoothing_falls_back_alone():
    for bad in (5, -1, "two", True):
        payload = RenderOptions().to_payload()
        payload["smoothing"] = bad
        options, error = validate_render_options(payload)
        assert options == RenderOptions() and "smoothing" in error, bad


def test_shadows_defaults_to_soft_and_cycles():
    from PyAitD.render.render_options import SHADOW_MODES, cycle_shadows
    assert SHADOW_MODES == ("hard", "soft", "room")
    options = RenderOptions()
    assert options.shadows == "soft"
    assert cycle_shadows(options).shadows == "room"
    assert cycle_shadows(RenderOptions(shadows="room")).shadows == "hard"
    assert cycle_shadows(RenderOptions(shadows="hard")).shadows == "soft"
    assert RenderOptions(shadows="hard").to_payload()["shadows"] == "hard"
    assert RenderOptions(shadows="room").to_payload()["shadows"] == "room"


def test_invalid_shadows_falls_back_alone():
    for bad in ("penumbra", 1, None, True):
        payload = RenderOptions().to_payload()
        payload["shadows"] = bad
        options, error = validate_render_options(payload)
        assert options == RenderOptions() and "shadows" in error, bad


def test_integration_defaults_to_the_full_level():
    from PyAitD.render.render_options import INTEGRATION_LEVELS
    assert INTEGRATION_LEVELS == (0, 1, 2, 3)
    assert RenderOptions().integration == 2


def test_a_settings_file_written_before_the_levels_still_means_what_it_said():
    # "off" and "on" are what this option shipped as; someone who turned the
    # composite off keeps it off, and neither spelling is worth an error.
    for legacy, level in (("off", 0), ("on", 2)):
        options, error = validate_render_options({**RenderOptions().to_payload(),
                                                  "integration": legacy})
        assert (options.integration, error) == (level, None), legacy


def test_an_unknown_integration_clamps_to_the_default_with_an_error():
    # The list is not idle: the legacy-string lookup below is a dict get,
    # and an unhashable payload value would raise straight through the
    # per-field fallback into config's blanket except, resetting every
    # other render option with it.
    for bad in ("sometimes", 4, -1, None, True, 1.0, []):
        options, error = validate_render_options({**RenderOptions().to_payload(),
                                                  "integration": bad})
        assert options.integration == RenderOptions().integration, bad
        assert "integration must be one of 0, 1, 2, 3" in error, bad


def test_integration_round_trips_through_the_payload():
    for level in (0, 1, 2, 3):
        payload = RenderOptions(integration=level).to_payload()
        assert payload["integration"] == level
        assert validate_render_options(payload) == (RenderOptions(integration=level), None)


def test_integration_cycles_through_every_level():
    from PyAitD.render.render_options import cycle_integration
    seen = [RenderOptions().integration]
    options = RenderOptions()
    for _ in range(4):
        options = cycle_integration(options)
        seen.append(options.integration)
    assert seen == [2, 3, 0, 1, 2]


def test_motion_defaults_to_smooth_and_cycles():
    from PyAitD.render.render_options import MOTION_MODES, RenderOptions, cycle_motion
    assert MOTION_MODES == ("tick", "smooth")
    options = RenderOptions()
    assert options.motion == "smooth"
    assert cycle_motion(options).motion == "tick"
    assert cycle_motion(cycle_motion(options)).motion == "smooth"
    assert RenderOptions(motion="smooth").to_payload()["motion"] == "smooth"


def test_invalid_or_missing_motion_falls_back_alone():
    from PyAitD.render.render_options import RenderOptions, validate_render_options
    payload = RenderOptions(scale=2).to_payload()
    payload["motion"] = "cinematic"
    options, error = validate_render_options(payload)
    assert options.motion == "smooth" and options.scale == 2
    assert "motion" in error
    del payload["motion"]   # a settings file from before this option
    options, error = validate_render_options(payload)
    assert options.motion == "smooth" and "motion" in error


def test_occlusion_defaults_ssao_and_cycles():
    from PyAitD.render.render_options import OCCLUSION_MODES, cycle_occlusion
    options = RenderOptions()
    assert options.occlusion == "ssao"
    assert OCCLUSION_MODES == ("off", "ssao")
    assert cycle_occlusion(options).occlusion == "off"
    assert cycle_occlusion(cycle_occlusion(options)).occlusion == "ssao"


@pytest.mark.parametrize("field, default", [("occlusion", "ssao"), ("atmosphere", "on")])
def test_appended_fields_are_last_so_positional_construction_still_works(field, default):
    # Every earlier field keeps its slot: this is what stops a new knob
    # from silently shifting an existing caller's arguments. One case per
    # field appended since -- the bodies were identical but for the name.
    options = RenderOptions(4, "smooth", "bilinear", None, "scene", 4, "enhanced", 2)
    assert getattr(options, field) == default


def test_invalid_or_missing_occlusion_falls_back_alone():
    payload = RenderOptions().to_payload()
    payload["occlusion"] = "raytraced"
    options, error = validate_render_options(payload)
    assert options.occlusion == "ssao"
    assert options.motion == "smooth"          # its neighbour is undisturbed
    assert "occlusion" in error
    del payload["occlusion"]   # a settings file from before this option
    options, error = validate_render_options(payload)
    assert options.occlusion == "ssao" and "occlusion" in error


# The *non-default* value for atmosphere, so that case is a round trip and
# not a restatement of the fallback its own falls-back-alone test covers.
@pytest.mark.parametrize("field, value", [("occlusion", "ssao"), ("atmosphere", "off")])
def test_appended_fields_round_trip_through_the_payload(field, value):
    from dataclasses import replace
    options = replace(RenderOptions(), **{field: value})
    assert options.to_payload()[field] == value
    restored, error = validate_render_options(options.to_payload())
    assert getattr(restored, field) == value and error is None


def test_atmosphere_defaults_on_and_cycles():
    # ATMOSPHERE_MODES stays ("off", "on") -- the tuple is the menu's cycle
    # order, not a statement about the default -- so cycling from the "on"
    # default wraps to "off" first, exactly as occlusion's ("off", "ssao")
    # cycles from its "ssao" default.
    from PyAitD.render.render_options import ATMOSPHERE_MODES, cycle_atmosphere
    options = RenderOptions()
    assert options.atmosphere == "on"
    assert ATMOSPHERE_MODES == ("off", "on")
    assert cycle_atmosphere(options).atmosphere == "off"
    assert cycle_atmosphere(cycle_atmosphere(options)).atmosphere == "on"


def test_invalid_or_missing_atmosphere_falls_back_alone():
    payload = RenderOptions().to_payload()
    payload["atmosphere"] = "foggy"
    options, error = validate_render_options(payload)
    assert options.atmosphere == "on"
    assert options.integration == RenderOptions().integration    # neighbour undisturbed
    assert "atmosphere" in error
    del payload["atmosphere"]   # a settings file from before this option
    options, error = validate_render_options(payload)
    assert options.atmosphere == "on" and "atmosphere" in error
