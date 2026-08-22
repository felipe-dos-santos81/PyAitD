# SPDX-License-Identifier: GPL-2.0-only
import numpy as np

from maitd.mask import fill_poly


def test_fill_triangle():
    target = np.zeros((10, 10), dtype=np.uint8)
    fill_poly([(2, 2), (7, 2), (2, 7)], target, 255)
    assert target[2, 3] == 255
    assert target[2, 1] == 0
    assert target[3, 3] == 255
    assert target[1, 3] == 0


def test_fill_square_rows():
    target = np.zeros((10, 10), dtype=np.uint8)
    fill_poly([(1, 1), (4, 1), (4, 4), (1, 4)], target, 255)
    assert target[2, 1] == 255
    assert target[2, 4] == 255
    assert target[2, 0] == 0
    assert target[2, 5] == 0
    assert target[0, 2] == 0
    assert target[5, 2] == 0

def test_masks_tagged_with_viewed_room(data_dir):
    # FITD: masks clip actors in OTHER viewed rooms only; player in room 0
    # must not be occluded by camera 0's room-0 masks.
    from maitd.floor import Floor
    from maitd.mask import create_aitd1_mask
    import pathlib
    d = pathlib.Path(data_dir)
    floor = Floor(d, 0)
    masks = create_aitd1_mask(floor.camera_raw, floor.camera_data_offsets[0])
    assert masks
    assert all(m.viewed_room == 0 for m in masks)
