# SPDX-License-Identifier: GPL-2.0-only
import struct

import numpy as np

from PyAitD.floor import Floor
from PyAitD.mask import create_aitd1_mask, fill_poly
from PyAitD.mask_geometry import MaskDraw, iter_mask_records, mask_polygons


def _build_synthetic_camera_raw():
    # One viewed room, one mask record, one zone (test rect), one triangle
    # polygon -- laid out by hand to match the FITD camera-data mask format
    # that iter_mask_records walks.
    camera_off = 0
    base = 32
    buf = bytearray(64)
    struct.pack_into("<H", buf, camera_off + 0x12, 1)  # num_viewed
    vr_off = camera_off + 0x14
    struct.pack_into("<h", buf, vr_off, 5)  # viewed_room
    struct.pack_into("<H", buf, vr_off + 2, base)  # mask_off
    struct.pack_into("<h", buf, base + 0, 1)  # num_mask
    struct.pack_into("<H", buf, base + 2, 1)  # num_zones
    struct.pack_into("<H", buf, base + 4, 14)  # poly_off, relative to base
    struct.pack_into("<4h", buf, base + 6, 10, 20, 30, 40)  # test_rects[0]
    struct.pack_into("<H", buf, base + 14, 1)  # num_polys
    struct.pack_into("<H", buf, base + 16, 3)  # num_points
    struct.pack_into("<6h", buf, base + 18, 1, 2, 3, 4, 5, 6)  # points
    return bytes(buf), camera_off


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


def test_polygons_rasterize_to_the_bitmap_masks(data_dir):
    floor = Floor(data_dir, 0)
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
    floor = Floor(data_dir, 0)
    draws = floor.mask_draws(0)
    assert [d.id for d in draws] == list(range(len(draws)))
    assert floor.mask_draws(0) is draws
