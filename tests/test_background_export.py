# SPDX-License-Identifier: GPL-2.0-only
import hashlib

import numpy as np
import pytest

from PyAitD import background_export as be


def _blank(h=20, w=30):
    return np.zeros((h, w, 3), np.uint8)


def test_draw_polyline_sets_endpoints_and_line_pixels():
    img = _blank()
    be.draw_polyline(img, [(2, 3), (10, 3)], (255, 0, 0))
    assert tuple(img[3, 2]) == (255, 0, 0)
    assert tuple(img[3, 10]) == (255, 0, 0)
    assert (img[3, 2:11] == (255, 0, 0)).all()
    assert img[4].sum() == 0 and img[2].sum() == 0


def test_draw_polyline_closed_draws_return_edge():
    img = _blank()
    be.draw_polyline(img, [(2, 2), (8, 2), (8, 8)], (0, 255, 0), closed=True)
    # diagonal return edge (8,8)->(2,2) passes through (5,5)
    assert tuple(img[5, 5]) == (0, 255, 0)


def test_draw_polyline_clips_at_every_edge():
    img = _blank()
    be.draw_polyline(img, [(-50, -50), (100, 100)], (0, 0, 255))
    be.draw_polyline(img, [(15, -40), (15, 60)], (0, 0, 255))
    be.draw_polyline(img, [(-40, 10), (80, 10)], (0, 0, 255))
    assert tuple(img[0, 0]) == (0, 0, 255)
    assert tuple(img[19, 19]) == (0, 0, 255)
    assert tuple(img[0, 15]) == (0, 0, 255) and tuple(img[19, 15]) == (0, 0, 255)
    assert tuple(img[10, 0]) == (0, 0, 255) and tuple(img[10, 29]) == (0, 0, 255)


def test_draw_polyline_degenerate_inputs_do_not_raise():
    img = _blank()
    be.draw_polyline(img, [], (1, 1, 1))
    be.draw_polyline(img, [(5, 5)], (1, 1, 1))
    be.draw_polyline(img, [(5, 5), (5, 5)], (1, 1, 1))
    assert tuple(img[5, 5]) == (1, 1, 1)


def test_draw_polyline_rounds_float_coordinates():
    img = _blank()
    be.draw_polyline(img, [(2.4, 3.6), (2.4, 3.6)], (9, 9, 9))
    assert tuple(img[4, 2]) == (9, 9, 9)


def test_nearest_upscale_repeats_pixels():
    src = np.arange(2 * 3 * 3, dtype=np.uint8).reshape(2, 3, 3)
    out = be.nearest_upscale(src, 4)
    assert out.shape == (8, 12, 3)
    assert (out[0:4, 0:4] == src[0, 0]).all()
    assert (out[4:8, 8:12] == src[1, 2]).all()
    assert out.flags["C_CONTIGUOUS"]


def test_nearest_upscale_scale_one_is_a_copy():
    src = np.zeros((2, 2, 3), np.uint8)
    out = be.nearest_upscale(src, 1)
    out[0, 0] = 7
    assert src[0, 0, 0] == 0


def test_sha256_rgb_matches_hashlib_over_raw_bytes():
    px = np.arange(200 * 320 * 3, dtype=np.uint32).reshape(200, 320, 3) % 256
    px = px.astype(np.uint8)
    assert be.sha256_rgb(px) == hashlib.sha256(px.tobytes()).hexdigest()
    assert be.sha256_rgb(px[:, ::-1]) != be.sha256_rgb(px)  # non-contiguous view hashes its logical order


def test_background_export_is_pure():
    import sys
    for name in ("pygame", "moderngl"):
        sys.modules.pop(name, None)
    import importlib
    importlib.reload(be)
    src = open(be.__file__).read()
    assert "import pygame" not in src and "import moderngl" not in src


from tests.stub_floor import StubFloor, checker_pixels


def test_manifest_record_fields():
    floor = StubFloor(number=3)
    px = checker_pixels()
    rec = be.manifest_record(floor, 0, px)
    assert rec == {
        "floor": 3, "camera": 0,
        "source": "backgrounds/floor03/camera000.png",
        "guide": "guides/floor03/camera000.png",
        "size": [320, 200],
        "viewed_rooms": [0],
        "masks": 1,
        "sha256": be.sha256_rgb(px),
    }


def test_manifest_record_out_of_range_camera_is_null():
    rec = be.manifest_record(StubFloor(), 7, None)
    assert rec["source"] is None and rec["guide"] is None and rec["sha256"] is None
    assert rec["size"] is None and rec["camera"] == 7


def test_export_manifest_envelope():
    floor = StubFloor()
    recs = [be.manifest_record(floor, 0, checker_pixels())]
    m = be.export_manifest(recs, "/data/INDARK", 4)
    assert m["schema"] == be.MANIFEST_SCHEMA == 1
    assert m["data_dir"] == "/data/INDARK"
    assert m["guide_scale"] == 4
    assert m["legend"] == {"red": "masks", "blue": "collision", "green": "walkable"}
    assert m["cameras"] == recs
    import json
    json.dumps(m)  # serialisable


def test_rel_paths_match_asset_resolver_layout(tmp_path):
    from PyAitD.asset_resolver import override_background_path
    assert (tmp_path / be.background_rel_path(5, 12)) == override_background_path(tmp_path, 5, 12)
    assert be.guide_rel_path(5, 12) == "guides/floor05/camera012.png"


def test_manifest_record_missing_image_preserves_metadata():
    rec = be.manifest_record(StubFloor(images={}), 0, None)
    assert rec["source"] is None
    assert rec["guide"] is None
    assert rec["sha256"] is None
    assert rec["size"] is None
    assert rec["viewed_rooms"] == [0]
    assert rec["masks"] == 1
