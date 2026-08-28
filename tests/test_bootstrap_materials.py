# SPDX-License-Identifier: GPL-2.0-only
import json
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pytest

from PyAitD.engine.formats import Body, Group, Primitive
from PyAitD.render.materials import parse_table
from tools import bootstrap_materials as bm

pytestmark = pytest.mark.tools


def _palette():
    """Two ramps and a singleton: a 16-step grey ramp at 0..15, a 6-step
    peach ramp at 16..21 (hue ~0.07, saturation ~0.5, rising luminance),
    and one bright isolated entry at 22; everything else black."""
    pal = np.zeros((256, 3), np.uint8)
    for i in range(16):
        pal[i] = (i * 16, i * 16, i * 16)
    for j in range(6):
        l = 90 + j * 20            # r = l + 60 stays under 255
        pal[16 + j] = (l + 60, l, l - 40)
    pal[22] = (250, 250, 200)
    return pal


def _body(colors, groups=0, prim_type=1):
    v = [(-100, -100, 0), (100, -100, 0), (100, 100, 0), (-100, 100, 0)]
    prims = [Primitive(prim_type, 0, c, [0, 1, 2, 3]) for c in colors]
    gs = [Group(0, 4, 0, 0xFF, 0, 0, 0, 0)] + [Group(4, 0, 0, 0xFF, i, 0, 0, 0) for i in range(1, groups)]
    return Body(0, (-100, 100, -100, 100, -10, 10), (), v, gs, list(range(len(gs))), prims)


def test_split_ramps_finds_two_ramps_and_a_singleton():
    ramps = bm.split_ramps(_palette())
    assert (0, 15) in ramps
    assert (16, 21) in ramps
    assert (22, 22) in ramps
    # every index is in exactly one ramp
    covered = sorted(i for lo, hi in ramps for i in range(lo, hi + 1))
    assert covered == list(range(256))


def test_body_usage_counts_triangles_bodies_and_groups():
    bodies = {"0:0": _body([16, 16, 20], groups=9), "1:3": _body([16], groups=1), "0:5": _body([0], groups=1, prim_type=0)}
    usage = bm.body_usage(bodies)
    assert usage[16]["bodies"] == ["0:0", "1:3"]
    assert usage[16]["triangles"] == 2 * 2 + 1 * 2   # quads fan into two triangles
    assert usage[20]["bodies"] == ["0:0"]
    assert 0 not in usage                             # lines are not surfaces
    assert usage[16]["groups"] == [0]


def test_propose_reads_skin_off_a_peach_ramp_on_a_many_group_body():
    bodies = {"0:0": _body([16, 17, 18], groups=12)}
    name, confidence, reason = bm.propose(16, 21, _palette(), bm.body_usage(bodies))
    assert name == "skin" and confidence >= 0.7 and "peach" in reason


def test_propose_reads_metal_off_a_long_grey_ramp_on_a_one_group_body():
    bodies = {"0:7": _body([3, 4, 5], groups=1)}
    name, confidence, _ = bm.propose(0, 15, _palette(), bm.body_usage(bodies))
    assert name == "metal" and 0 < confidence < 0.8


def test_propose_marks_an_unused_ramp_matte_with_high_confidence():
    name, confidence, reason = bm.propose(22, 22, _palette(), {})
    assert name == "matte" and confidence >= 0.9 and "unused" in reason


def test_survey_lists_every_ramp_with_usage_and_proposal():
    bodies = {"0:0": _body([16, 17], groups=12), "0:1": _body([4], groups=1)}
    data = bm.survey(_palette(), bodies)
    ramps = {(r["lo"], r["hi"]): r for r in data["ramps"]}
    assert ramps[(16, 21)]["class"] == "skin"
    assert ramps[(16, 21)]["usage"]["bodies"] == ["0:0"]
    assert ramps[(0, 15)]["usage"]["triangles"] == 2
    assert set(ramps[(16, 21)]) >= {"lo", "hi", "class", "confidence", "reason", "usage"}


def test_resolve_class_prefers_label_then_vision_then_heuristic():
    assert bm.resolve_class({"class": "cloth"}) == "cloth"
    assert bm.resolve_class({"class": "cloth", "vision_class": "leather"}) == "leather"
    assert bm.resolve_class({"class": "cloth", "vision_class": "leather", "label": "skin"}) == "skin"


def test_emit_table_writes_load_table_shape_with_evidence_notes():
    data = {"ramps": [
        {"lo": 16, "hi": 21, "class": "skin", "confidence": 0.7, "reason": "peach",
         "usage": {"bodies": ["0:0"], "triangles": 4, "groups": [1, 5]}},
        {"lo": 0, "hi": 15, "class": "metal", "vision_class": "stone", "confidence": 0.4, "reason": "grey",
         "usage": {"bodies": ["0:1"], "triangles": 2, "groups": [0]}},
    ]}
    table = bm.emit_table(data)
    assert table["indices"] == {}
    by = {(r["lo"], r["hi"]): r for r in table["ramps"]}
    assert by[(16, 21)]["class"] == "skin" and by[(0, 15)]["class"] == "stone"
    assert "bodies 0:0" in by[(16, 21)]["note"] and "heuristic: skin" in by[(16, 21)]["note"]
    assert "vision: stone" in by[(0, 15)]["note"]
    parsed = parse_table(table)                       # the game can load it
    assert parsed.classes[18] == "skin" and parsed.classes[3] == "stone"


def test_contact_sheet_renders_the_body_and_highlights_a_ramp():
    body = _body([16], groups=1)
    plain = bm.contact_sheet(body, _palette())
    assert plain.shape == (200, 320, 3)
    assert plain.std() > 0                             # something was drawn
    lit = bm.contact_sheet(body, _palette(), highlight=(16, 21))
    magenta = (lit == (255, 0, 255)).all(axis=2)
    assert magenta.any() and not (plain == (255, 0, 255)).all(axis=2).any()


def test_check_fails_on_a_drifted_table_and_passes_on_a_fresh_emit(tmp_path):
    data = {"ramps": [{"lo": 16, "hi": 21, "class": "skin", "confidence": 0.7, "reason": "",
                       "usage": {"bodies": [], "triangles": 0, "groups": []}}]}
    (tmp_path / "survey.json").write_text(json.dumps(data))
    table = tmp_path / "materials.json"
    table.write_text(json.dumps(bm.emit_table(data)))
    assert bm.main(["unused", "check", "--out", str(tmp_path), "--table", str(table)]) == 0
    table.write_text(json.dumps({"ramps": [], "indices": {}}))
    assert bm.main(["unused", "check", "--out", str(tmp_path), "--table", str(table)]) == 1


def test_emit_stage_writes_the_table_from_the_survey(tmp_path):
    data = bm.survey(_palette(), {"0:0": _body([16], groups=12)})
    (tmp_path / "survey.json").write_text(json.dumps(data))
    table = tmp_path / "materials.json"
    assert bm.main(["unused", "emit", "--out", str(tmp_path), "--table", str(table)]) == 0
    assert parse_table(json.loads(table.read_text())).classes[16] == "skin"


def test_main_exits_2_without_data_for_survey(tmp_path, capsys):
    assert bm.main([str(tmp_path / "missing"), "survey", "--out", str(tmp_path)]) == 2
    assert "missing" in capsys.readouterr().err
