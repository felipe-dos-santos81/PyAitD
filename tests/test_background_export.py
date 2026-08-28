# SPDX-License-Identifier: GPL-2.0-only
import hashlib

import numpy as np

from PyAitD.render import background_export as be
import pytest

pytestmark = pytest.mark.render


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


from tests.stub_floor import StubFloor, checker_pixels


def test_manifest_record_fields():
    floor = StubFloor(number=3)
    px = checker_pixels()
    rec = be.manifest_record(floor, 0, px)
    assert rec == {
        "floor": 3, "camera": 0,
        "source": "backgrounds/floor03/camera000.png",
        "guide": "guides/floor03/camera000.png",
        "layout": "guides/floor03/camera000.png".replace(".png", ".json"),
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
    assert m["schema"] == be.MANIFEST_SCHEMA
    assert m["data_dir"] == "/data/INDARK"
    assert m["guide_scale"] == 4
    assert m["legend"] == {"red": "masks", "blue": "collision", "green": "walkable"}
    assert m["cameras"] == recs
    import json
    json.dumps(m)  # serialisable


def test_rel_paths_match_asset_resolver_layout(tmp_path):
    from PyAitD.render.asset_resolver import override_background_path
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
    from PyAitD.engine.formats import Zone
    floor.rooms[0].hard_cols = [Zone(x1=-10, x2=10, y1=-10, y2=0, z1=-5000, z2=-4000, type=0, parameter=0)]
    floor._cover = {}
    g = be.guide_overlay(floor, 0, 1)
    assert not (g[:200] == be.COLOR_COLLISION).all(axis=2).any()


def test_guide_overlay_draws_edge_with_one_far_offscreen_corner():
    """A box whose left corners project far off-screen left (sx << -9999,
    but valid depth) must not cull the edge to its on-screen right corner:
    culling belongs to depth, not to screen-space x (regression for the
    a[0]/b[0] vs a[2]/b[2] cull-test bug)."""
    floor = StubFloor()
    from PyAitD.engine.formats import Zone
    floor.rooms[0].hard_cols = [
        Zone(x1=-1_000_000, x2=100, y1=-50, y2=0, z1=0, z2=10, type=0, parameter=0)
    ]
    g = be.guide_overlay(floor, 0, 1)
    # bottom edge (x1,0,0)->(x2,0,0): left corner sx ~= -999840 (depth 1000,
    # not culled), right corner sx = 260 -> a horizontal line through y=100
    # that must be drawn on its on-screen portion (x=100 sits well clear of
    # the default mask/cover polygons on this StubFloor).
    assert tuple(g[100, 100]) == be.COLOR_COLLISION


def test_cover_zones_for_uses_parse_cover_zones_on_real_floors(monkeypatch):
    calls = []
    monkeypatch.setattr(be, "parse_cover_zones", lambda raw, off, vi: calls.append((raw, off, vi)) or [[(1, 2)]])

    class Plain:
        camera_raw = b"xyz"
        camera_data_offsets = [0, 40]

    assert be.cover_zones_for(Plain(), 1, 0) == [[(1, 2)]]
    assert calls == [(b"xyz", 40, 0)]


def test_guide_overlay_real_camera_matches_integer_projection(data_dir, profile):
    from PyAitD.engine.floor import Floor
    from PyAitD.engine.world import CameraState, transform_point
    floor = Floor(data_dir, 0, profile)
    cam_idx = 0
    room_idx = floor.cameras[cam_idx].viewed_rooms[0].viewed_room_idx
    room = floor.rooms[room_idx]
    state = CameraState.from_camera(floor.cameras[cam_idx], room.world_x, room.world_y, room.world_z).angles()
    box = room.hard_cols[0]
    # integer path, mirroring skel.skin's order (translate, then rotate, then project)
    x, y, z = box.x1 - state.x, box.y2 - state.y, box.z1 - state.z
    ix, iy, idepth = state.project(*transform_point(x, y, z, state))
    assert idepth > 50, "pick a corner in front of the camera for this test"
    from PyAitD.render.scene import CameraView
    fx, fy, fdepth = CameraView(state).project([(box.x1, box.y2, box.z1)])[0]
    tol = 12.0 if fdepth < 2000 else 1.0
    assert abs(fx - ix) <= tol and abs(fy - iy) <= tol
    g = be.guide_overlay(floor, cam_idx, 1)
    assert g.shape == (212, 320, 3)


def test_screen_paths_mirror_the_resolver_layout():
    from PyAitD.render.asset_resolver import override_screen_path
    import pathlib
    assert be.screen_rel_path(10) == "screens/ress10.png"
    assert be.screen_guide_rel_path(10) == "guides/screens/ress10.png"
    assert pathlib.Path("/x") / be.screen_rel_path(6) == override_screen_path("/x", 6)


def test_screen_entries_and_guides_are_consistent():
    assert be.SCREEN_ENTRIES == (6, 7, 8, 10, 12, 13, 14)
    assert 11 not in be.SCREEN_ENTRIES
    assert set(be.SCREEN_GUIDES) == set(be.SCREEN_ENTRIES) == set(be.SCREEN_NAMES)
    for entry, rects in be.SCREEN_GUIDES.items():
        assert rects, entry
        for x, y, w, h in rects:
            assert 0 <= x and 0 <= y and x + w <= 320 and y + h <= 200, (entry, (x, y, w, h))


def test_screen_record_fields():
    pixels = np.full((200, 320, 3), 3, np.uint8)
    rec = be.screen_record(10, pixels)
    assert rec["entry"] == 10 and rec["name"] == "PERSO_CHOICE"
    assert rec["source"] == "screens/ress10.png" and rec["guide"] == "guides/screens/ress10.png"
    assert rec["size"] == [320, 200]
    assert rec["sha256"] == hashlib.sha256(pixels.tobytes()).hexdigest()
    assert rec["blits"] == [list(r) for r in be.SCREEN_GUIDES[10]]


def test_screen_guide_draws_blit_rects_and_legend():
    pixels = np.zeros((200, 320, 3), np.uint8)
    img = be.screen_guide(pixels, 10, 2)
    assert img.shape == (400 + be.GUIDE_FOOTER, 640, 3)
    x, y, w, h = be.SCREEN_GUIDES[10][0]
    assert tuple(img[y * 2, x * 2]) == be.COLOR_BLIT            # top-left corner of the first rect
    assert tuple(img[(y + h - 1) * 2, (x + w - 1) * 2]) == be.COLOR_BLIT
    assert tuple(img[400 + 2, 2]) == be.COLOR_MASK             # legend footer, first swatch


def test_manifest_v2_carries_screens_and_accepts_v1():
    m = be.export_manifest([], "/data", 4, screens=[{"entry": 13}])
    assert m["schema"] == 3 and m["screens"] == [{"entry": 13}]
    assert be.export_manifest([], "/data", 4)["screens"] == []
    assert be.SUPPORTED_SCHEMAS == (1, 2, 3)


def test_layout_geometry_lists_masks_collision_and_walkable():
    layout = be.layout_geometry(StubFloor(), 0)
    assert layout["schema"] == 1 and layout["size"] == [320, 200]
    assert layout["masks"] == [[[10.0, 10.0], [50.0, 10.0], [50.0, 40.0]]]
    assert len(layout["collision"]) == 1 and len(layout["collision"][0]) == 8
    # _box_corners order: 1 = (x2, y2, z1) = (100, 0, 0) -> (260, 100); 5 = (100, -50, 0) -> (260, 50)
    assert layout["collision"][0][1] == pytest.approx([260.0, 100.0], abs=0.6)
    assert layout["collision"][0][5] == pytest.approx([260.0, 50.0], abs=0.6)
    assert len(layout["walkable"]) == 1 and len(layout["walkable"][0]) == 4
    # cover (5, 0) -> room (50, 0, 0) -> (210, 100); (-5, 50) -> (126.67, 100)
    assert layout["walkable"][0][1] == pytest.approx([210.0, 100.0], abs=0.6)
    assert layout["walkable"][0][3] == pytest.approx([126.67, 100.0], abs=0.6)
    import json
    json.dumps(layout)


def test_layout_geometry_nulls_culled_vertices():
    floor = StubFloor()
    from PyAitD.engine.formats import Zone
    floor.rooms[0].hard_cols = [Zone(x1=-10, x2=10, y1=-10, y2=0, z1=-5000, z2=-4000, type=0, parameter=0)]
    floor._cover = {}
    layout = be.layout_geometry(floor, 0)
    assert layout["collision"] == [[None] * 8] and layout["walkable"] == []


def test_layout_segments_skip_null_endpoints_and_close_polygons():
    layout = {"masks": [[[0, 0], [10, 0], [10, 10]]],
              "collision": [[[0, 0], None, [5, 5], [7, 7], None, None, None, None]],
              "walkable": [[[1, 1], [2, 2], None]],
              "blit": [[0, 0, 4, 3]]}
    segs = be.layout_segments(layout)
    assert ((0, 0), (10, 0)) in segs and ((10, 10), (0, 0)) in segs      # mask: closed
    assert ((5, 5), (7, 7)) in segs and ((7, 7), (0, 0)) in segs         # box edges (2,3) and (3,0)
    assert ((1, 1), (2, 2)) in segs                                      # walkable edge (0,1)
    assert ((0, 0), (3, 0)) in segs and ((0, 2), (0, 0)) in segs         # blit rect, inclusive corners
    assert len(segs) == 3 + 2 + 1 + 4
    assert not any(a is None or b is None for a, b in segs)


def test_guide_overlay_accepts_a_precomputed_layout():
    floor = StubFloor()
    layout = be.layout_geometry(floor, 0)
    assert (be.guide_overlay(floor, 0, 2, layout=layout) == be.guide_overlay(floor, 0, 2)).all()


def test_screen_layout_lists_blit_rects():
    assert be.screen_layout(10) == {"schema": 1, "size": [320, 200],
                                    "blit": [list(r) for r in be.SCREEN_GUIDES[10]]}


def test_records_carry_layout_paths():
    assert be.layout_rel_path(3, 0) == "guides/floor03/camera000.json"
    assert be.screen_layout_rel_path(10) == "guides/screens/ress10.json"
    assert be.manifest_record(StubFloor(number=3), 0, checker_pixels())["layout"] == "guides/floor03/camera000.json"
    assert be.manifest_record(StubFloor(), 7, None)["layout"] is None
    assert be.screen_record(10, np.zeros((200, 320, 3), np.uint8))["layout"] == "guides/screens/ress10.json"


def test_alt_background_rel_path_mirrors_resolver(tmp_path):
    from PyAitD.render import background_export as be
    from PyAitD.render.asset_resolver import override_alt_background_path
    assert (tmp_path / be.alt_background_rel_path(7, 0)) == override_alt_background_path(tmp_path, 7, 0)
    assert be.alt_background_rel_path(6, 5) == "alt_backgrounds/floor06/camera005.png"


def test_alt_manifest_record_fields():
    from PyAitD.render import background_export as be
    from tests.stub_floor import StubFloor, checker_pixels
    px = checker_pixels()
    rec = be.alt_manifest_record(StubFloor(number=7), 0, px, 15)
    assert rec["source"] == "alt_backgrounds/floor07/camera000.png"
    assert rec["guide"] == "guides/floor07/camera000.png"  # shared
    assert rec["layout"] == "guides/floor07/camera000.json"
    assert rec["itd_entry"] == 15 and rec["variant"] == "killed_sorcerer"
    assert rec["size"] == [320,200] and rec["viewed_rooms"] == [0]


def test_export_manifest_schema3_carries_alt_cameras():
    from PyAitD.render import background_export as be
    from tests.stub_floor import StubFloor, checker_pixels
    rec = be.manifest_record(StubFloor(number=6), 0, checker_pixels())
    alt = be.alt_manifest_record(StubFloor(number=7), 0, checker_pixels(), 15)
    m = be.export_manifest([rec], "/data", 4, screens=[{"entry":13}], alt_cameras=[alt])
    assert m["schema"] == 3 and m["alt_cameras"] == [alt]
    assert be.SUPPORTED_SCHEMAS == (1,2,3)
    # old call without alt_cameras still works (schema 3 but empty list)
    assert be.export_manifest([rec], "/data", 4)["alt_cameras"] == []


def test_alt_background_rel_path_and_manifest_record_match_asset_resolver_layout():
    import json
    from PyAitD.render import background_export as be
    from tests.stub_floor import StubFloor, checker_pixels
    rec = be.alt_manifest_record(StubFloor(number=6), 8, checker_pixels(), 19)
    json.dumps(rec)  # serialisable
    assert rec["layout"] == be.layout_rel_path(6,8)
