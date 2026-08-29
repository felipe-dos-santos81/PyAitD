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


def test_emit_table_omits_unused_matte_ramps_and_dangling_note_segments():
    # An unused ramp classified matte is exactly parse_table's implicit
    # default, so emitting it would add a row saying nothing to a file a
    # human hand-edits -- and the row it emitted carried two empty note
    # segments ("bodies ; groups ; heuristic: matte (0.9)").
    data = bm.survey(_palette(), {"0:0": _body([16], groups=12)})
    table = bm.emit_table(data)
    emitted = {(r["lo"], r["hi"]) for r in table["ramps"]}
    assert (16, 21) in emitted                        # used: kept
    assert (22, 22) not in emitted                    # unused + matte: dropped
    assert all("; ;" not in r["note"] and not r["note"].startswith(";") for r in table["ramps"])
    assert all("bodies ;" not in r["note"] and "groups ;" not in r["note"] for r in table["ramps"])
    # dropping those rows cannot move any of the 256 indices: the default covers them
    assert parse_table(table).classes == parse_table(
        {"ramps": [{"lo": r["lo"], "hi": r["hi"], "class": bm.resolve_class(r)} for r in data["ramps"]]}
    ).classes


def test_emit_table_keeps_a_ramp_that_is_matte_only_because_a_body_uses_it():
    # `matte` on a *used* ramp is a real answer about a real surface, not the
    # default filling a hole: the row stays so the note stays.
    data = {"ramps": [{"lo": 0, "hi": 15, "class": "matte", "confidence": 0.3, "reason": "unclassified",
                       "usage": {"bodies": ["0:1"], "triangles": 2, "groups": [0]}}]}
    assert [r["lo"] for r in bm.emit_table(data)["ramps"]] == [0]


def test_the_committed_table_carries_every_index_that_is_not_the_matte_default():
    # The shipped materials.json, parsed: the rows it does carry must be the
    # only ones that move an index off `matte`.
    from PyAitD.render.materials import DEFAULT_TABLE_PATH, PALETTE_SIZE
    committed = json.loads(DEFAULT_TABLE_PATH.read_text())
    classes = parse_table(committed).classes
    assert len(classes) == PALETTE_SIZE
    covered = {i for r in committed["ramps"] for i in range(r["lo"], r["hi"] + 1)}
    assert {i for i, c in enumerate(classes) if c != "matte"} <= covered


def test_survey_carries_a_hand_label_and_a_vision_class_across_a_re_survey():
    # The documented fix for a misclassification is to hand-label a ramp in
    # survey.json and re-run `make bootstrap-materials`, whose first stage is
    # survey: a wholesale overwrite would destroy the label every time.
    bodies = {"0:0": _body([16, 17], groups=12)}
    first = bm.survey(_palette(), bodies)
    by = {(r["lo"], r["hi"]): r for r in first["ramps"]}
    by[(16, 21)]["label"] = "leather"
    by[(0, 15)]["vision_class"] = "stone"
    by[(0, 15)]["vision_reason"] = "looks like flagstones"
    again = {(r["lo"], r["hi"]): r for r in bm.survey(_palette(), bodies, first)["ramps"]}
    assert again[(16, 21)]["label"] == "leather"
    assert again[(0, 15)]["vision_class"] == "stone"
    assert again[(0, 15)]["vision_reason"] == "looks like flagstones"
    assert again[(16, 21)]["class"] == "skin"          # the heuristic is still re-derived
    assert bm.resolve_class(again[(16, 21)]) == "leather"


def test_a_ramp_whose_boundaries_moved_inherits_nothing():
    previous = {"ramps": [{"lo": 16, "hi": 20, "class": "skin", "label": "leather",
                           "vision_class": "wood", "vision_reason": "stale",
                           "usage": {"bodies": [], "triangles": 0, "groups": []}}]}
    again = {(r["lo"], r["hi"]): r for r in
             bm.survey(_palette(), {"0:0": _body([16], groups=12)}, previous)["ramps"]}
    assert (16, 20) not in again and (16, 21) in again
    assert "label" not in again[(16, 21)] and "vision_class" not in again[(16, 21)]


def test_survey_stage_reruns_over_an_existing_survey_without_losing_a_label(tmp_path, monkeypatch):
    palette, bodies = _palette(), {"0:0": _body([16], groups=12)}
    monkeypatch.setattr(bm, "load_game", lambda data_dir: (palette, bodies))
    monkeypatch.setattr(bm, "write_sheets", lambda *a: None)
    data = tmp_path / "data"
    data.mkdir()
    out = tmp_path / "out"
    assert bm.main([str(data), "survey", "--out", str(out)]) == 0
    survey = json.loads((out / "survey.json").read_text())
    for ramp in survey["ramps"]:
        if (ramp["lo"], ramp["hi"]) == (16, 21):
            ramp["label"] = "leather"
    (out / "survey.json").write_text(json.dumps(survey))
    assert bm.main([str(data), "survey", "--out", str(out)]) == 0
    again = {(r["lo"], r["hi"]): r for r in json.loads((out / "survey.json").read_text())["ramps"]}
    assert again[(16, 21)]["label"] == "leather"


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


def _survey_for_labelling():
    return {"ramps": [
        {"lo": 0, "hi": 15, "class": "metal", "confidence": 0.5, "reason": "grey",
         "usage": {"bodies": ["0:1"], "triangles": 2, "groups": [0]},
         "sheet": "sheets/body0-001.png", "highlight": "sheets/ramp000-015.png"},
        {"lo": 16, "hi": 21, "class": "skin", "confidence": 0.8, "reason": "peach",
         "usage": {"bodies": ["0:0"], "triangles": 4, "groups": [1]},
         "sheet": "sheets/body0-000.png", "highlight": "sheets/ramp016-021.png"},
        {"lo": 22, "hi": 22, "class": "matte", "confidence": 0.9, "reason": "unused",
         "usage": {"bodies": [], "triangles": 0, "groups": []}},
        {"lo": 23, "hi": 30, "class": "cloth", "confidence": 0.3, "reason": "blue", "label": "leather",
         "usage": {"bodies": ["0:2"], "triangles": 6, "groups": [2]},
         "sheet": "sheets/body0-002.png", "highlight": "sheets/ramp023-030.png"},
    ]}


def test_label_ramps_asks_only_about_uncertain_unlabelled_ramps_with_sheets():
    data = _survey_for_labelling()
    asked = []

    def ask(sheet, highlight):
        asked.append((sheet, highlight))
        return {"class": "stone", "reason": "it looks like carved stone"}

    assert bm.label_ramps(data, ask, threshold=0.8) == 1
    assert asked == [("sheets/body0-001.png", "sheets/ramp000-015.png")]
    assert data["ramps"][0]["vision_class"] == "stone" and data["ramps"][0]["vision_reason"].startswith("it looks")
    assert "vision_class" not in data["ramps"][1]           # confident enough
    assert "vision_class" not in data["ramps"][2]           # no sheet: nothing to show
    assert data["ramps"][3]["label"] == "leather" and "vision_class" not in data["ramps"][3]   # hand label wins


def test_label_ramps_rejects_a_class_outside_the_vocabulary():
    data = _survey_for_labelling()
    with pytest.raises(ValueError, match="velvet"):
        bm.label_ramps(data, lambda s, h: {"class": "velvet", "reason": ""}, threshold=0.8)


def test_label_instructions_name_both_images_and_every_class():
    text = bm.label_instructions("/a/sheet.png", "/a/high.png")
    assert "/a/sheet.png" in text and "/a/high.png" in text and "magenta" in text
    for name in bm.MATERIAL_CLASSES:
        assert name in text
    assert bm.LABEL_SCHEMA["properties"]["class"]["enum"] == list(bm.MATERIAL_CLASSES)


def test_ask_vision_dictates_the_agy_call(tmp_path, monkeypatch):
    import json as _json
    import subprocess
    import types
    calls = []

    def fake_run(cmd, capture_output=True, text=True, check=True):
        calls.append(cmd)
        return types.SimpleNamespace(
            stdout=_json.dumps({"status": "SUCCESS", "structured_output": {"class": "wood", "reason": "grain"}}),
            stderr="", returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    ask = bm.ask_vision("gemini-3.1-pro", tmp_path)
    assert ask("sheets/body0-001.png", "sheets/ramp000-015.png") == {"class": "wood", "reason": "grain"}
    cmd = calls[0]
    assert cmd[0] == "agy" and "gemini-3.1-pro" in cmd
    assert _json.loads(cmd[cmd.index("--json-schema") + 1]) == bm.LABEL_SCHEMA
    assert str((tmp_path / "sheets/body0-001.png").resolve()) in cmd[2]


def test_label_stage_without_agy_exits_2_and_leaves_the_survey(tmp_path, monkeypatch, capsys):
    import shutil
    data = _survey_for_labelling()
    survey = tmp_path / "survey.json"
    survey.write_text(json.dumps(data))
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert bm.main(["unused", "label", "--out", str(tmp_path)]) == 2
    assert "agy" in capsys.readouterr().err
    assert json.loads(survey.read_text()) == data


def test_label_stage_writes_vision_classes_back(tmp_path, monkeypatch):
    import shutil
    data = _survey_for_labelling()
    (tmp_path / "survey.json").write_text(json.dumps(data))
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/agy")
    monkeypatch.setattr(bm, "ask_vision", lambda model, out: (lambda s, h: {"class": "stone", "reason": "r"}))
    assert bm.main(["unused", "label", "--out", str(tmp_path)]) == 0
    out = json.loads((tmp_path / "survey.json").read_text())
    assert out["ramps"][0]["vision_class"] == "stone"


# The 23 ramps any body actually uses, hand-reviewed against the sheets in
# data/aitd1/materials-survey/sheets/ -- see docs/materials-v2-proof.md for
# the decisions. This is the only in-repo record: the survey holding the
# hand labels is git-ignored, so a re-emit that silently dropped a label
# back to its stale vision_class or heuristic guess would otherwise be
# invisible until someone re-reviewed the renders by eye.
REVIEWED_RAMPS = {
    (0, 1): "matte", (2, 3): "metal", (14, 14): "emissive",
    (15, 31): "skin", (32, 47): "skin", (48, 63): "matte",
    (64, 68): "stone", (69, 74): "leather", (75, 79): "cloth",
    (80, 95): "matte", (96, 107): "cloth", (108, 111): "cloth",
    (112, 127): "skin", (128, 143): "leather", (144, 159): "skin",
    (160, 175): "cloth", (176, 191): "metal", (192, 197): "cloth",
    (198, 201): "wood", (202, 204): "metal", (205, 207): "wood",
    (208, 217): "cloth", (218, 223): "cloth",
}


def test_the_committed_table_matches_the_reviewed_survey():
    """`check` is the gate that stops materials.json drifting from the
    survey it was emitted from at bootstrap time -- this test is what
    stops it drifting afterward, since nothing else in the repo re-derives
    the survey. A class assertion is not enough: the table already
    contained skin/wood/emissive/metal *before* the review (from an
    earlier vision pass), so this pins the actual per-ramp mapping the
    review decided, not just which class names appear somewhere in it."""
    from PyAitD.render.materials import default_table
    classes = default_table().classes
    for (lo, hi), expected in REVIEWED_RAMPS.items():
        for index in range(lo, hi + 1):
            assert classes[index] == expected, (
                f"palette index {index} (ramp {lo}-{hi}): "
                f"expected reviewed class {expected!r}, got {classes[index]!r}"
            )
