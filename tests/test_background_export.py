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


def test_guide_overlay_shape_and_footer():
    g = be.guide_overlay(StubFloor(), 0, 4)
    assert g.shape == (200 * 4 + be.GUIDE_FOOTER, 320 * 4, 3)
    footer = g[800:]
    assert (footer[:, 0:40] == be.COLOR_MASK).all()
    assert (footer[:, 48:88] == be.COLOR_COLLISION).all()
    assert (footer[:, 96:136] == be.COLOR_WALKABLE).all()
    assert footer[:, 136:].sum() == 0


def test_guide_overlay_background_is_nearest_upscaled_original():
    floor = StubFloor()
    g = be.guide_overlay(floor, 0, 2)
    src = floor.camera_image(0)
    # a pixel far from every drawn line: bottom-right corner block
    assert (g[398:400, 638:640] == src[199, 319]).all()


def test_guide_overlay_draws_mask_polygon_in_red_at_scaled_vertices():
    g = be.guide_overlay(StubFloor(), 0, 4)
    for x, y in ((10, 10), (50, 10), (50, 40)):
        assert tuple(g[y * 4, x * 4]) == be.COLOR_MASK
    # closed: the (50,40)->(10,10) edge passes through (30,25)
    assert tuple(g[25 * 4, 30 * 4]) == be.COLOR_MASK


def test_guide_overlay_projects_hard_col_corners_in_blue():
    g = be.guide_overlay(StubFloor(), 0, 1)
    # (100, 0, 0) -> (260, 100); top y1=-50 at z=0 -> (260, 50)
    assert tuple(g[100, 260]) == be.COLOR_COLLISION
    # top y1=-50 at z=1000 -> (210, 75); the bottom corner at that same x
    # (100, 0, 1000) -> (210, 100)) also coincides with the cover polygon's
    # (5, 0) -> room (50, 0, 0) vertex on this StubFloor (both the box's
    # floor and the room's cover polygon sit at y=0, level with the
    # camera, so their screen-space rows overlap); check the unambiguous
    # top corner on the same edge instead.
    assert tuple(g[75, 210]) == be.COLOR_COLLISION
    assert tuple(g[50, 260]) == be.COLOR_COLLISION
    # vertical edge between them
    assert tuple(g[75, 260]) == be.COLOR_COLLISION


def test_guide_overlay_projects_cover_polygon_in_green():
    g = be.guide_overlay(StubFloor(), 0, 1)
    # cover (5, 0) -> room (50, 0, 0) -> (210, 100) is also a blue corner; use
    # (-5, 50) -> room (-50, 0, 500) -> (126.67, 100) -> pixel (127, 100)
    assert tuple(g[100, 127]) == be.COLOR_WALKABLE


def test_guide_overlay_skips_culled_edges():
    floor = StubFloor()
    # a hard col entirely behind the camera projects to the sentinel and must not draw
    from PyAitD.formats import Zone
    floor.rooms[0].hard_cols = [Zone(x1=-10, x2=10, y1=-10, y2=0, z1=-5000, z2=-4000, type=0, parameter=0)]
    floor._cover = {}
    g = be.guide_overlay(floor, 0, 1)
    assert not (g[:200] == be.COLOR_COLLISION).all(axis=2).any()


def test_cover_zones_for_uses_parse_cover_zones_on_real_floors(monkeypatch):
    calls = []
    monkeypatch.setattr(be, "parse_cover_zones", lambda raw, off, vi: calls.append((raw, off, vi)) or [[(1, 2)]])

    class Plain:
        camera_raw = b"xyz"
        camera_data_offsets = [0, 40]

    assert be.cover_zones_for(Plain(), 1, 0) == [[(1, 2)]]
    assert calls == [(b"xyz", 40, 0)]


def test_guide_overlay_real_camera_matches_integer_projection(data_dir):
    from PyAitD.floor import Floor
    from PyAitD.world import CameraState, transform_point
    floor = Floor(data_dir, 0)
    cam_idx = 0
    room_idx = floor.cameras[cam_idx].viewed_rooms[0].viewed_room_idx
    room = floor.rooms[room_idx]
    state = CameraState.from_camera(floor.cameras[cam_idx], room.world_x, room.world_y, room.world_z).angles()
    box = room.hard_cols[0]
    # integer path, mirroring skel.skin's order (translate, then rotate, then project)
    x, y, z = box.x1 - state.x, box.y2 - state.y, box.z1 - state.z
    ix, iy, idepth = state.project(*transform_point(x, y, z, state))
    assert idepth > 50, "pick a corner in front of the camera for this test"
    from PyAitD.scene import CameraView
    fx, fy, fdepth = CameraView(state).project([(box.x1, box.y2, box.z1)])[0]
    tol = 12.0 if fdepth < 2000 else 1.0
    assert abs(fx - ix) <= tol and abs(fy - iy) <= tol
    g = be.guide_overlay(floor, cam_idx, 1)
    assert g.shape == (212, 320, 3)
