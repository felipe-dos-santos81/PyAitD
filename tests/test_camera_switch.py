# SPDX-License-Identifier: GPL-2.0-only
import struct

from PyAitD.engine.data.formats import parse_cover_zones
from PyAitD.engine.data.pak import Pak
from PyAitD.engine.world import find_best_camera, is_in_poly
import pytest

pytestmark = pytest.mark.engine


def test_cover_zones_real_data(data_dir):
    cam_raw = Pak(data_dir / "ETAGE00.PAK").read(1)
    zones = parse_cover_zones(cam_raw, 1300, 0)  # camera 2, viewed room 0
    assert len(zones) == 1
    assert zones[0][0] == (-742, 207)
    assert zones[0][-1] == (-655, 18)


def test_spawn_in_camera2_zone(data_dir):
    cam_raw = Pak(data_dir / "ETAGE00.PAK").read(1)
    zones = parse_cover_zones(cam_raw, 1300, 0)
    # spawn point is the zone centroid
    assert is_in_poly(-364, -364, 198, 198, zones)


def test_spawn_outside_camera0_zone(data_dir):
    cam_raw = Pak(data_dir / "ETAGE00.PAK").read(1)
    zones = parse_cover_zones(cam_raw, 24, 0)
    assert not is_in_poly(-364, -364, 198, 198, zones)


def test_synthetic_zone_contains_point():
    square = [[(0, 0), (100, 0), (100, 100), (0, 100)]]
    assert is_in_poly(50, 50, 50, 50, square)
    assert not is_in_poly(150, 150, 50, 50, square)


def test_find_best_camera_real_data(data_dir):
    from PyAitD.engine.data.formats import parse_cameras
    cam_raw = Pak(data_dir / "ETAGE00.PAK").read(1)
    cameras = parse_cameras(cam_raw)
    zones_by_camera = [parse_cover_zones(cam_raw, off, 0) for off in (24, 858, 1300, 2240, 2834)]
    best = find_best_camera(-364, -364, 198, 198, 0, cameras, zones_by_camera)
    assert best == 2
