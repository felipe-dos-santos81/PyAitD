# SPDX-License-Identifier: GPL-2.0-only
import numpy as np

from PyAitD.engine.data.mask import fill_poly
import pytest

pytestmark = pytest.mark.engine


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

def test_masks_tagged_with_viewed_room(data_dir, profile):
    from PyAitD.engine.data.floor import Floor
    from PyAitD.engine.data.mask import create_aitd1_mask
    import pathlib
    d = pathlib.Path(data_dir)
    floor = Floor(d, 0, profile)
    masks = create_aitd1_mask(floor.camera_raw, floor.camera_data_offsets[0], 0x0C)
    assert masks
    assert all(m.viewed_room == 0 for m in masks)


def test_masks_retain_actor_trigger_rectangles(data_dir, profile):
    from PyAitD.engine.data.floor import Floor
    from PyAitD.engine.data.mask import create_aitd1_mask
    import pathlib
    d = pathlib.Path(data_dir)
    floor = Floor(d, 0, profile)

    masks = create_aitd1_mask(floor.camera_raw, floor.camera_data_offsets[0], 0x0C)

    assert getattr(masks[4], "test_rects", ()) == (
        (560, -518, 764, 517),
        (-858, -291, 772, 557),
    )
