# SPDX-License-Identifier: GPL-2.0-only
import json

import numpy as np
import pytest

from PyAitD.render.materials import (
    CLASS_PRESETS, DETAIL_NONE, MATERIAL_CLASSES, PARAMETER_COUNT, PRESETS, REALISM_MODES,
    Material, MaterialTable, RealismPreset, default_table, load_table, parse_assignments, parse_table,
)

pytestmark = pytest.mark.render


def test_every_class_has_a_preset_with_a_positive_detail_scale():
    assert set(CLASS_PRESETS) == set(MATERIAL_CLASSES)
    for name, material in CLASS_PRESETS.items():
        assert isinstance(material, Material)
        assert material.detail_scale > 0, name  # the shader divides by it
        assert 0 <= material.detail_kind <= 4, name


def test_a_zero_detail_scale_is_rejected_naming_the_field():
    # The shader divides by it; a zero would make the detail noise NaN, and
    # `0.0 * NaN` is NaN, so it would break realism=classic's byte identity.
    with pytest.raises(ValueError, match="detail_scale must be > 0"):
        Material(1.0, 0.0, 0.0, 0.0, 0.0, 0.0, DETAIL_NONE)
    with pytest.raises(ValueError, match="detail_scale must be > 0"):
        Material(1.0, 0.0, 0.0, 0.0, 0.0, -1.0, DETAIL_NONE)


def test_matte_has_no_specular_rim_or_detail():
    matte = CLASS_PRESETS["matte"]
    assert (matte.specular, matte.rim, matte.detail, matte.detail_kind) == (0.0, 0.0, 0.0, DETAIL_NONE)


def test_unmentioned_indices_are_matte_and_ramps_then_indices_apply():
    table = parse_table({"ramps": [{"lo": 16, "hi": 31, "class": "skin"}], "indices": {"20": "metal", "200": "wood"}})
    assert len(table.classes) == 256
    assert table.classes[0] == "matte"
    assert table.classes[16] == "skin" and table.classes[31] == "skin"
    assert table.classes[20] == "metal"      # indices win over ramps
    assert table.classes[200] == "wood"


def test_parse_assignments_returns_only_the_explicit_ones():
    assert parse_assignments({"ramps": [{"lo": 2, "hi": 3, "class": "hair"}], "indices": {"9": "glass"}}) == {
        2: "hair", 3: "hair", 9: "glass"}
    assert parse_assignments({}) == {}


@pytest.mark.parametrize("data, message", [
    ({"ramps": [{"lo": 4, "hi": 6, "class": "velvet"}]}, "ramp 4..6: unknown material class 'velvet'"),
    ({"indices": {"300": "skin"}}, "index 300: outside 0..255"),
    ({"ramps": [{"lo": 9, "hi": 2, "class": "skin"}]}, "ramp 9..2: lo > hi"),
    ({"indices": {"x": "skin"}}, "index 'x': not an integer"),
    ([], "material table must be an object"),
])
def test_invalid_tables_are_rejected_naming_the_entry(data, message):
    with pytest.raises(ValueError, match=message.replace("(", "\\(").replace(")", "\\)")):
        parse_table(data)


def test_remapped_changes_only_the_listed_indices():
    base = parse_table({"ramps": [{"lo": 0, "hi": 255, "class": "cloth"}]})
    out = base.remapped({5: "metal"})
    assert out.classes[5] == "metal"
    assert out.classes[4] == "cloth" and out.classes[6] == "cloth"
    assert base.classes[5] == "cloth"  # immutable


def test_parameters_are_256_by_8_float32_in_range():
    params = parse_table({"ramps": [{"lo": 0, "hi": 255, "class": "metal"}]}).parameters()
    assert params.shape == (256, PARAMETER_COUNT) and params.dtype == np.float32
    assert (params[:, :5] >= 0).all() and (params[:, :5] <= 1).all()   # roughness..detail
    assert (params[:, 5] > 0).all()                                    # detail_scale
    assert (params[:, 6] >= 0).all() and (params[:, 6] <= 4).all()     # detail_kind
    assert (params[:, 7] == 0).all()                                   # padding
    assert np.array_equal(params[7], CLASS_PRESETS["metal"].parameters())


def test_table_round_trips_through_json(tmp_path):
    data = {"ramps": [{"lo": 16, "hi": 31, "class": "skin", "note": "hero"}], "indices": {"3": "wood"}}
    path = tmp_path / "materials.json"
    path.write_text(json.dumps(data))
    assert load_table(path) == parse_table(data)


def test_default_table_is_cached_and_full_length():
    assert default_table() is default_table()
    assert len(default_table().classes) == 256
    assert set(default_table().classes) <= set(MATERIAL_CLASSES)


def test_classic_preset_is_all_zeros_and_enhanced_is_not():
    assert REALISM_MODES == ("classic", "enhanced")
    assert PRESETS["classic"] == RealismPreset(0, 0, 0, 0, 0, 0)
    enhanced = PRESETS["enhanced"]
    assert all(0 < v <= 1 for v in (enhanced.spec, enhanced.rim, enhanced.ao,
                                    enhanced.contact, enhanced.detail, enhanced.hemisphere))


def test_the_three_new_fields_default_to_zero_and_validate():
    from PyAitD.render.materials import Material
    m = Material(1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0)
    assert (m.bump, m.sss, m.emissive) == (0.0, 0.0, 0.0)
    for field in ("bump", "sss", "emissive"):
        with pytest.raises(ValueError, match=field):
            Material(1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0, **{field: 1.5})
        with pytest.raises(ValueError, match=field):
            Material(1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0, **{field: -0.1})


def test_parameters_are_twelve_wide_and_in_range():
    from PyAitD.render.materials import PARAMETER_COUNT, default_table
    assert PARAMETER_COUNT == 12
    params = default_table().parameters()
    assert params.shape == (256, 12)
    assert params.dtype == np.float32
    # every field is 0..1 except detail_scale (FITD units) and detail_kind
    scaleless = np.delete(params, [5, 6], axis=1)
    assert scaleless.min() >= 0.0 and scaleless.max() <= 1.0
    assert (params[:, 5] > 0.0).all()


def test_classic_zeroes_every_preset_field_including_the_new_ones():
    from PyAitD.render.materials import PRESETS
    classic = PRESETS["classic"]
    assert (classic.spec, classic.rim, classic.ao) == (0.0, 0.0, 0.0)
    assert (classic.contact, classic.detail, classic.hemisphere) == (0.0, 0.0, 0.0)
    assert (classic.bump, classic.sss, classic.emissive) == (0.0, 0.0, 0.0)


# ---- the retune (materials v2, task 5)


def test_every_class_keeps_its_parameters_in_range_after_the_retune():
    # The retune moved every specular value and three detail_scales at
    # once. `Material.__post_init__` only guards bump/sss/emissive and the
    # positive detail_scale, so a fat-fingered specular of 1.5 or a
    # negative rim would ship: the shader multiplies each of these by a
    # preset strength and a lighting term, and outside 0..1 they stop
    # being a fraction of anything.
    for name, material in CLASS_PRESETS.items():
        for field in ("roughness", "specular", "metallic", "rim", "detail", "bump", "sss", "emissive"):
            value = getattr(material, field)
            assert 0.0 <= value <= 1.0, f"{name}.{field} = {value}"
        assert material.detail_scale > 0.0, name


def test_only_emissive_emits():
    # `emissive` replaces a fragment's whole colour -- mix(shaded, v_color,
    # preset_c.z * m2.z) is exactly v_color at 1.0 -- so it is the one
    # parameter a stray non-zero would take a body completely out of the
    # lighting. Ramp 14's flames are the only thing in the reviewed table
    # that asked for it.
    emitting = {n for n, m in CLASS_PRESETS.items() if m.emissive > 0.0}
    assert emitting == {"emissive"}
