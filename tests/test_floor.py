# SPDX-License-Identifier: GPL-2.0-only
import numpy as np
import pytest

from PyAitD.engine import floor as floormod
from PyAitD.engine.floor import Floor
from PyAitD.engine.pak import PakError


def test_floor0_loads(data_dir):
    f = Floor(data_dir, 0)
    assert f.number == 0
    assert len(f.rooms) == 1
    assert len(f.cameras) == 5
    assert f.palette.shape == (256, 3)


def test_camera_image(data_dir):
    f = Floor(data_dir, 0)
    img = f.camera_image(2)  # room 0's camera
    assert img.shape == (200, 320, 3)
    assert img.dtype == np.uint8


def test_camera_image_out_of_range(data_dir):
    f = Floor(data_dir, 0)
    with pytest.raises(KeyError):
        f.camera_image(99)


def test_missing_floor_raises(data_dir):
    with pytest.raises(PakError):
        Floor(data_dir, 97)


def test_cache_hits(data_dir):
    floormod.cache_clear()
    f = Floor(data_dir, 0)
    raw_path = str(f._images)
    floormod.load_entry(raw_path, 0)
    info_before = floormod.load_entry.cache_info()
    floormod.load_entry(raw_path, 0)
    assert floormod.load_entry.cache_info().hits > info_before.hits


def test_camera_image_decoded_once(data_dir):
    f = Floor(data_dir, 0)
    assert f.camera_image(0) is f.camera_image(0)
