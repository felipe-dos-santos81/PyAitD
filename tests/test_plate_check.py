# SPDX-License-Identifier: GPL-2.0-only
import numpy as np
import pytest

from PyAitD.render.background_export import nearest_upscale
from tools import plate_check as pc

pytestmark = pytest.mark.tools

LAYOUT = {"schema": 1, "size": [320, 200],
          "masks": [[[100, 60], [160, 60], [160, 140], [100, 140]]],
          "collision": [[[220, 20], [270, 20], [270, 50], [220, 50], None, None, None, None]],
          "walkable": [[[0, 150], [320, 150], [320, 200], [0, 200]]]}


def scene(shift=0):
    """A gradient floor with a bright 'crate' and a dark 'window'; `shift`
    moves both objects right by that many pixels."""
    img = np.zeros((200, 320, 3), np.uint8)
    img[:] = np.linspace(40, 120, 320).astype(np.uint8)[None, :, None]
    img[60:140, 100 + shift:160 + shift] = (200, 180, 160)
    img[20:50, 220 + shift:270 + shift] = (30, 30, 30)
    return img


def test_identical_scene_passes_every_score():
    r = pc.gate(nearest_upscale(scene(), 4), scene(), LAYOUT)
    assert r.passed and r.failures == [] and not r.leaked
    assert r.scores["ncc"] > 0.99 and r.scores["edge_recall"] == 1.0
    assert r.scores["leak"] == 0.0 and r.scores["leak_frame"] == 0.0
    kinds = [reg["kind"] for reg in r.scores["regions"]]
    assert kinds == ["mask", "collision"]                      # walkable is prompt-only
    assert all(reg["recall"] == 1.0 for reg in r.scores["regions"])


def test_shifted_scene_fails_regions_with_bbox_wording():
    r = pc.gate(nearest_upscale(scene(8), 4), scene(), LAYOUT)
    assert not r.passed
    mask_region = r.scores["regions"][0]
    assert mask_region["bbox_pct"] == [31, 30, 50, 70] and mask_region["recall"] < 0.5
    assert any(f.startswith("structure missing inside x 31–50 y 30–70") for f in r.failures)


def test_guide_coloured_lines_fail_leak():
    cand = nearest_upscale(scene(), 4)
    lines = nearest_upscale(pc.guide_lines(LAYOUT)[..., None].astype(np.uint8), 4)[..., 0] > 0
    cand[lines] = (255, 0, 0)
    r = pc.gate(cand, scene(), LAYOUT)
    assert not r.passed and r.leaked and r.scores["leak"] > 0.25   # dilated line pixels dilute it to ~1/3
    assert any("guide colour" in f and "do not draw" in f for f in r.failures)
    clean = pc.gate(nearest_upscale(scene(), 4), scene(), LAYOUT)
    assert not clean.leaked


def test_blit_noise_fails_plain():
    layout = {"schema": 1, "size": [320, 200], "blit": [[20, 20, 100, 60]]}
    cand = nearest_upscale(scene(), 4)
    rng = np.random.default_rng(0)
    cand[80:320, 80:480] = rng.integers(0, 256, size=(240, 400, 3), dtype=np.uint8)
    r = pc.gate(cand, scene(), layout)
    assert any(f.startswith("text or clutter inside plain region x 6–38 y 10–40") for f in r.failures)
    assert pc.gate(nearest_upscale(scene(), 4), scene(), layout).passed


def test_no_layout_reports_only_global_scores():
    r = pc.gate(nearest_upscale(scene(), 4), scene(), None)
    assert set(r.scores) == {"ncc", "edge_recall"} and r.passed and not r.leaked


def test_polygon_mask_fills_concave_polygon():
    L = [(2, 2), (10, 2), (10, 5), (5, 5), (5, 10), (2, 10)]
    m = pc.polygon_mask(L, shape=(12, 12))
    assert m[3, 3] and m[3, 9] and m[8, 3]
    assert not m[8, 8] and not m[0, 0] and not m[11, 11]


def test_flat_regions_report_null_recall_without_failing():
    layout = {"schema": 1, "size": [320, 200], "masks": [[[10, 150], [60, 150], [60, 190], [10, 190]]],
              "collision": [], "walkable": []}
    r = pc.gate(nearest_upscale(scene(), 4), scene(), layout)
    assert r.scores["regions"][0]["recall"] is None and r.passed


def test_scale_zero_passes_anything():
    r = pc.gate(nearest_upscale(scene(40), 4), scene(), LAYOUT, scale=0)
    assert r.passed and r.failures == [] and r.scores["edge_recall"] < 0.6


def test_layout_regions_bboxes_hull_and_filters():
    regions = pc.layout_regions(LAYOUT)
    assert [(r.kind, r.bbox_pct) for r in regions] == [
        ("mask", (31, 30, 50, 70)), ("collision", (69, 10, 84, 25)), ("walkable", (0, 75, 100, 100))]
    assert len(regions[1].polygon) == 4                        # hull of the four live corners
    tiny = {"masks": [[[0, 0], [2, 0], [2, 2]]], "collision": [[None] * 8], "walkable": []}
    assert pc.layout_regions(tiny) == [] and pc.layout_regions(None) == []
    blit = pc.layout_regions({"blit": [[20, 20, 100, 60]]})
    assert blit[0].kind == "blit" and blit[0].bbox_pct == (6, 10, 38, 40)
    assert pc.fmt_bbox((45, 12, 52, 25)) == "x 45–52 y 12–25"


def test_gate_rejects_wrong_shapes():
    with pytest.raises(ValueError):
        pc.gate(np.zeros((400, 640, 3), np.uint8), scene(), LAYOUT)
    with pytest.raises(ValueError):
        pc.gate(nearest_upscale(scene(), 4), np.zeros((100, 160, 3), np.uint8), LAYOUT)


def test_every_original_passes_the_gate_against_itself(data_dir, profile):
    """Calibration guard: the pixel-art originals must never trip the gate
    or the guide-colour bands (green cloths, blue windows) by themselves."""
    from PyAitD.engine.floor import Floor
    from PyAitD.render.background_export import layout_geometry
    failed = []
    for number in range(8):
        floor = Floor(data_dir, number, profile)
        for cam_idx in range(len(floor.cameras)):
            try:
                original = floor.camera_image(cam_idx)
            except KeyError:
                continue
            r = pc.gate(nearest_upscale(original, 4), original, layout_geometry(floor, cam_idx))
            if not r.passed or r.scores["leak_frame"] >= 0.005:
                failed.append((number, cam_idx, r.failures, r.scores["leak_frame"]))
    assert failed == []
