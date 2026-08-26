# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.render.render_options import (
    BACKGROUND_FILTERS, SHADING_MODES, RenderOptions, cycle_filter, cycle_scale,
    cycle_shading, validate_render_options,
)
import pytest

pytestmark = pytest.mark.render


def test_defaults():
    assert RenderOptions() == RenderOptions(4, "smooth", "bilinear", None)
    assert SHADING_MODES == ("flat", "lambert", "smooth")
    assert BACKGROUND_FILTERS == ("nearest", "bilinear", "xbr")


def test_valid_payload_round_trips():
    options = RenderOptions(2, "flat", "xbr", "/tmp/ov")
    assert validate_render_options(options.to_payload()) == (options, None)


def test_each_invalid_field_falls_back_alone():
    options, error = validate_render_options(
        {"scale": 99, "shading": "smooth", "background_filter": "bilinear", "override_dir": None})
    assert options == RenderOptions(8, "smooth", "bilinear", None)  # clamped, not rejected
    assert error is None
    options, error = validate_render_options(
        {"scale": "x", "shading": "neon", "background_filter": "bilinear", "override_dir": 3})
    assert options == RenderOptions(4, "smooth", "bilinear", None)
    assert "scale" in error and "shading" in error and "override_dir" in error


def test_non_dict_payload_is_all_defaults_with_error():
    assert validate_render_options(None) == (RenderOptions(), "render must be an object")


def test_cycles():
    o = RenderOptions()
    assert cycle_scale(o).scale == 6 and cycle_scale(RenderOptions(scale=8)).scale == 1
    assert cycle_shading(o).shading == "flat"
    assert cycle_filter(o).background_filter == "xbr"
