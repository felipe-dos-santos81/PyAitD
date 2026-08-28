# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.render.render_options import (
    BACKGROUND_FILTERS, SHADING_MODES, RenderOptions, cycle_filter, cycle_scale,
    cycle_shading, validate_render_options,
)
import pytest

pytestmark = pytest.mark.render


def test_defaults():
    assert RenderOptions() == RenderOptions(4, "smooth", "bilinear", None, "scene", 4, "enhanced", 0)
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
        {"scale": 99, "shading": "smooth", "background_filter": "bilinear", "override_dir": None,
         "lighting": "fixed", "msaa": 0, "realism": "enhanced", "smoothing": 0})
    assert options == RenderOptions(8, "smooth", "bilinear", None, "fixed", 0, "enhanced", 0)  # clamped, not rejected
    assert error is None
    options, error = validate_render_options(
        {"scale": "x", "shading": "neon", "background_filter": "bilinear", "override_dir": 3,
         "lighting": "fixed", "msaa": 0, "realism": "enhanced", "smoothing": 0})
    assert options == RenderOptions(4, "smooth", "bilinear", None, "fixed", 0, "enhanced", 0)
    assert "scale" in error and "shading" in error and "override_dir" in error


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


def test_smoothing_defaults_to_off_and_cycles():
    from PyAitD.render.render_options import SMOOTHING_LEVELS, cycle_smoothing
    assert SMOOTHING_LEVELS == (0, 1, 2, 3)
    options = RenderOptions()
    assert options.smoothing == 0
    assert cycle_smoothing(options).smoothing == 1
    assert cycle_smoothing(RenderOptions(smoothing=3)).smoothing == 0
    assert RenderOptions(smoothing=2).to_payload()["smoothing"] == 2


def test_invalid_smoothing_falls_back_alone():
    for bad in (5, -1, "two", True):
        payload = RenderOptions().to_payload()
        payload["smoothing"] = bad
        options, error = validate_render_options(payload)
        assert options == RenderOptions() and "smoothing" in error, bad
