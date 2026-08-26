# SPDX-License-Identifier: GPL-2.0-only
import struct

import numpy as np

from PyAitD.engine.floor import Floor
from PyAitD.engine.mask import create_aitd1_mask, fill_poly
from PyAitD.engine.mask_geometry import MaskDraw, iter_mask_records, mask_polygons, triangulate_polygon
from PyAitD.games.aitd1.profile import AITD1
import pytest

pytestmark = pytest.mark.engine


def _pack_polygon_table(polygons):
    # on-disk layout at the poly_off target: numPolys, then per polygon
    # numPoints followed by that many (x, y) int16 pairs.
    parts = [struct.pack("<H", len(polygons))]
    for poly in polygons:
        parts.append(struct.pack("<H", len(poly)))
        for x, y in poly:
            parts.append(struct.pack("<hh", x, y))
    return b"".join(parts)


def _build_viewed_room_blob(mask_records):
    # mask_records: [(test_rects, polygons), ...]. Lays out the numMask
    # header, then each mask's (numZones, polyOff, test_rects) header
    # back-to-back, then the polygon tables back-to-back -- polyOff points
    # from a mask header into its slot in the trailing polygon-table block,
    # exactly like the real camera data iter_mask_records/create_aitd1_mask
    # walk.
    header_size = 2  # numMask
    for test_rects, _ in mask_records:
        header_size += 4 + len(test_rects) * 8
    poly_tables = [_pack_polygon_table(polys) for _, polys in mask_records]
    poly_offsets = []
    cursor = header_size
    for table in poly_tables:
        poly_offsets.append(cursor)
        cursor += len(table)
    header_parts = [struct.pack("<h", len(mask_records))]
    for (test_rects, _), poly_off in zip(mask_records, poly_offsets):
        header_parts.append(struct.pack("<H", len(test_rects)))
        header_parts.append(struct.pack("<H", poly_off))
        for rect in test_rects:
            header_parts.append(struct.pack("<4h", *rect))
    return b"".join(header_parts) + b"".join(poly_tables)


def _build_camera_raw(viewed_rooms):
    # viewed_rooms: [(vr_room, mask_records), ...]. Builds a full camera
    # record buffer (camera_off == 0) with a real viewed-room table and one
    # mask blob per viewed room, so both iter_mask_records/mask_polygons and
    # create_aitd1_mask can be pointed at it directly.
    camera_off = 0
    num_viewed = len(viewed_rooms)
    header_len = 0x14 + num_viewed * 0x0C
    blobs = [_build_viewed_room_blob(records) for _, records in viewed_rooms]
    buf = bytearray(header_len)
    struct.pack_into("<H", buf, camera_off + 0x12, num_viewed)
    offsets = []
    cursor = header_len
    for blob in blobs:
        offsets.append(cursor)
        cursor += len(blob)
    for i, (vr_room, _) in enumerate(viewed_rooms):
        vr_off = camera_off + 0x14 + i * 0x0C
        struct.pack_into("<h", buf, vr_off, vr_room)
        struct.pack_into("<H", buf, vr_off + 2, offsets[i])
    for blob in blobs:
        buf.extend(blob)
    return bytes(buf), camera_off


def _build_synthetic_camera_raw():
    # One viewed room, one mask record, one zone (test rect), one triangle
    # polygon.
    return _build_camera_raw([
        (5, [([(10, 20, 30, 40)], [[(1, 2), (3, 4), (5, 6)]])]),
    ])


def test_iter_mask_records_walks_a_synthetic_record():
    camera_raw, camera_off = _build_synthetic_camera_raw()
    records = list(iter_mask_records(camera_raw, camera_off))
    assert len(records) == 1
    viewed_room, test_rects, polygons = records[0]
    assert viewed_room == 5
    assert test_rects == ((10, 20, 30, 40),)
    assert polygons == [[(1, 2), (3, 4), (5, 6)]]


def test_mask_polygons_wraps_synthetic_record_in_a_maskdraw():
    camera_raw, camera_off = _build_synthetic_camera_raw()
    draws = mask_polygons(camera_raw, camera_off)
    assert len(draws) == 1
    draw = draws[0]
    assert isinstance(draw, MaskDraw)
    assert draw.id == 0
    assert draw.viewed_room == 5
    assert draw.test_rects == ((10, 20, 30, 40),)
    assert draw.bbox == (1, 2, 5, 6)
    assert len(draw.polygons) == 1
    poly = draw.polygons[0]
    assert poly.dtype == np.int16
    assert poly.shape == (3, 2)
    assert poly.tolist() == [[1, 2], [3, 4], [5, 6]]


# Two viewed rooms, two mask records per room, with differing zone counts
# (1, 2, 0, 3) and differing polygon vertex counts (4, {4,3}, 3, none) --
# chosen to exercise the record-advance arithmetic in iter_mask_records
# (`data += 2 + ((num_zones * 4 + 1) * 2)`) and the per-viewed-room table
# stride (`vr_off = camera_off + 0x14 + viewed * 0x0C`) across boundaries a
# single-record fixture can't reach. All expected values below are
# transcribed by hand from this literal fixture, not derived by calling the
# code under test.
_MULTI_RECORD_VIEWED_ROOMS = [
    (5, [
        ([(1, 2, 3, 4)], [[(0, 0), (5, 0), (5, 5), (0, 5)]]),
        (
            [(10, 20, 30, 40), (50, 60, 70, 80)],
            [
                [(20, 20), (25, 20), (25, 25), (20, 25)],
                [(60, 10), (65, 10), (65, 15)],
            ],
        ),
    ]),
    (9, [
        ([], [[(100, 150), (110, 150), (105, 160)]]),
        ([(0, 0, 1, 1), (2, 2, 3, 3), (4, 4, 5, 5)], []),
    ]),
]

_MULTI_RECORD_EXPECTED = [
    (5, ((1, 2, 3, 4),), [[(0, 0), (5, 0), (5, 5), (0, 5)]]),
    (
        5,
        ((10, 20, 30, 40), (50, 60, 70, 80)),
        [[(20, 20), (25, 20), (25, 25), (20, 25)], [(60, 10), (65, 10), (65, 15)]],
    ),
    (9, (), [[(100, 150), (110, 150), (105, 160)]]),
    (9, ((0, 0, 1, 1), (2, 2, 3, 3), (4, 4, 5, 5)), []),
]

_MULTI_RECORD_EXPECTED_BBOX = [
    (0, 0, 5, 5),
    (20, 10, 65, 25),
    (100, 150, 110, 160),
    (319, 199, 0, 0),  # no polygons: default min/max never touched
]


def test_iter_mask_records_walks_multiple_viewed_rooms_and_records():
    camera_raw, camera_off = _build_camera_raw(_MULTI_RECORD_VIEWED_ROOMS)
    records = list(iter_mask_records(camera_raw, camera_off))
    assert records == _MULTI_RECORD_EXPECTED


def test_mask_polygons_matches_hand_computed_records_and_bboxes():
    camera_raw, camera_off = _build_camera_raw(_MULTI_RECORD_VIEWED_ROOMS)
    draws = mask_polygons(camera_raw, camera_off)
    assert [d.id for d in draws] == [0, 1, 2, 3]
    for draw, (room, test_rects, polygons), bbox in zip(
        draws, _MULTI_RECORD_EXPECTED, _MULTI_RECORD_EXPECTED_BBOX
    ):
        assert draw.viewed_room == room
        assert draw.test_rects == test_rects
        assert draw.bbox == bbox
        actual_polygons = [[tuple(pt) for pt in poly.tolist()] for poly in draw.polygons]
        assert actual_polygons == polygons
        for poly in draw.polygons:
            assert poly.dtype == np.int16 and poly.ndim == 2 and poly.shape[1] == 2


def test_create_aitd1_mask_matches_hand_computed_bitmaps_and_bboxes():
    camera_raw, camera_off = _build_camera_raw(_MULTI_RECORD_VIEWED_ROOMS)
    masks = create_aitd1_mask(camera_raw, camera_off)
    assert len(masks) == len(_MULTI_RECORD_EXPECTED)
    for mask, (room, test_rects, polygons), bbox in zip(
        masks, _MULTI_RECORD_EXPECTED, _MULTI_RECORD_EXPECTED_BBOX
    ):
        assert mask.viewed_room == room
        assert mask.test_rects == test_rects
        assert (mask.x1, mask.y1, mask.x2, mask.y2) == bbox
        expected_bitmap = np.zeros((200, 320), dtype=np.uint8)
        for points in polygons:
            fill_poly(points, expected_bitmap, 255)
        assert np.array_equal(mask.bitmap, expected_bitmap)


def test_polygons_rasterize_to_the_bitmap_masks(data_dir):
    floor = Floor(data_dir, 0, AITD1)
    for cam_idx in range(len(floor.cameras)):
        off = floor.camera_data_offsets[cam_idx]
        bitmaps = create_aitd1_mask(floor.camera_raw, off)
        draws = mask_polygons(floor.camera_raw, off)
        assert len(draws) == len(bitmaps)
        for draw, mask in zip(draws, bitmaps):
            assert isinstance(draw, MaskDraw)
            assert (draw.viewed_room, draw.test_rects) == (mask.viewed_room, mask.test_rects)
            assert draw.bbox == (mask.x1, mask.y1, mask.x2, mask.y2)
            bitmap = np.zeros((200, 320), dtype=np.uint8)
            for poly in draw.polygons:
                assert poly.dtype == np.int16 and poly.ndim == 2 and poly.shape[1] == 2
                fill_poly([tuple(p) for p in poly.tolist()], bitmap, 255)
            assert np.array_equal(bitmap, mask.bitmap)


def test_ids_are_positional_and_floor_caches(data_dir):
    floor = Floor(data_dir, 0, AITD1)
    draws = floor.mask_draws(0)
    assert [d.id for d in draws] == list(range(len(draws)))
    assert floor.mask_draws(0) is draws


# ---- triangulate_polygon: the ear-clipping regression guard ----
#
# These tests deliberately re-implement point-in-polygon (ray casting) and
# point-in-triangle-list checks independently of anything in mask_geometry
# or render_gl -- they are ground truth, not a restatement of the code
# under test.

def _ray_cast_inside(x, y, poly):
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def _cross2(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _inside_any_triangle(x, y, poly, tri_indices):
    p = (x, y)
    for a, b, c in tri_indices:
        A, B, C = poly[a], poly[b], poly[c]
        d1, d2, d3 = _cross2(A, B, p), _cross2(B, C, p), _cross2(C, A, p)
        has_neg = d1 < 0 or d2 < 0 or d3 < 0
        has_pos = d1 > 0 or d2 > 0 or d3 > 0
        if not (has_neg and has_pos):
            return True
    return False


def _sample_disagreements(poly, tri_indices, bounds, step=0.2):
    # Sample off a half-integer grid (all these fixtures use integer
    # vertex coordinates) so no probe point ever lands exactly on an edge
    # or vertex, where inclusion is a convention, not a correctness
    # question.
    lo_x, lo_y, hi_x, hi_y = bounds
    mismatches = 0
    for x in np.arange(lo_x, hi_x, step) + step / 2 + 0.013:
        for y in np.arange(lo_y, hi_y, step) + step / 2 + 0.017:
            truth = _ray_cast_inside(x, y, poly)
            got = _inside_any_triangle(x, y, poly, tri_indices)
            if truth != got:
                mismatches += 1
    return mismatches


# A concave dart / arrowhead: vertex 3, (1, 2), is a reflex vertex that
# points back *into* the shape defined by the other three points. A
# GL_TRIANGLE_FAN from vertex 0 draws triangles (0,1,2) and (0,2,3) --
# together these are exactly the *convex hull* triangle (0,1,2), because
# (0,2,3) is a subset of it: the fan over-fills the notch the dart
# actually excludes. This is the same over-occlusion failure mode as the
# real mask polygons (verified against real game data separately), shrunk
# to four hand-picked points.
_DART = [(0, 0), (4, 2), (0, 4), (1, 2)]


def test_ear_clip_and_naive_fan_disagree_on_a_concave_dart():
    # Establishes the premise: this fixture actually exercises the bug
    # class under test. If a future edit to _DART made the fan agree with
    # the true interior everywhere, this test (not the one below) is the
    # one that would catch it -- the exactness assertion below alone
    # would still pass on a polygon that happened to be star-shaped.
    naive_fan = [(0, i, i + 1) for i in range(1, len(_DART) - 1)]
    fan_mismatches = _sample_disagreements(_DART, naive_fan, (-1, -1, 5, 5))
    assert fan_mismatches > 0


def test_ear_clip_triangulation_covers_exactly_the_concave_polygons_interior():
    tris = triangulate_polygon(_DART).tolist()
    assert len(tris) == len(_DART) - 2  # a simple polygon always triangulates to n-2 triangles
    mismatches = _sample_disagreements(_DART, tris, (-1, -1, 5, 5))
    assert mismatches == 0


def test_ear_clip_triangulation_is_winding_direction_robust():
    reversed_dart = list(reversed(_DART))
    tris = triangulate_polygon(reversed_dart).tolist()
    assert len(tris) == len(reversed_dart) - 2
    mismatches = _sample_disagreements(reversed_dart, tris, (-1, -1, 5, 5))
    assert mismatches == 0


def test_ear_clip_triangulation_of_a_larger_concave_comb_matches_ray_casting():
    # A five-pronged comb: deeply concave, more points than the minimal
    # dart above, and -- unlike the dart -- not star-shaped from *any*
    # single vertex, so no fan origin could accidentally get this right.
    comb = [
        (0, 0), (10, 0), (10, 10), (8, 10), (8, 3), (6, 3), (6, 10),
        (4, 10), (4, 3), (2, 3), (2, 10), (0, 10),
    ]
    tris = triangulate_polygon(comb).tolist()
    assert len(tris) == len(comb) - 2
    mismatches = _sample_disagreements(comb, tris, (-1, -1, 11, 11))
    assert mismatches == 0


def test_triangulate_polygon_degenerate_inputs_fall_back_gracefully():
    assert triangulate_polygon([]).shape == (0, 3)
    assert triangulate_polygon([(0, 0)]).shape == (0, 3)
    assert triangulate_polygon([(0, 0), (1, 1)]).shape == (0, 3)
    # A duplicated closing vertex (first == last) collapses to a triangle
    # once deduped, rather than raising or leaving a degenerate 0-area
    # sliver triangle in the output.
    tris = triangulate_polygon([(0, 0), (4, 0), (0, 4), (0, 0)])
    assert tris.tolist() == [[0, 1, 2]]


def test_triangulate_polygon_output_indexes_the_original_points():
    # MaskDraw.triangles / render_gl gather triangle vertices with
    # poly[tris.reshape(-1)] against the *original* (undeduped) points
    # array -- every emitted index must be a valid position in `points`.
    tris = triangulate_polygon(_DART)
    assert tris.dtype == np.int32
    assert tris.shape[1] == 3
    assert set(tris.reshape(-1).tolist()) <= set(range(len(_DART)))


def test_mask_draw_caches_a_triangulation_per_polygon():
    poly = np.array(_DART, dtype=np.int16)
    draw = MaskDraw(0, (poly,), (0, 0, 4, 4), 0, ())
    assert len(draw.triangles) == 1
    assert draw.triangles[0].shape == (len(_DART) - 2, 3)
