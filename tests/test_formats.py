# SPDX-License-Identifier: GPL-2.0-only
from maitd.formats import parse_cameras, parse_rooms
from maitd.pak import Pak


def test_floor0_rooms(data_dir):
    pak = Pak(data_dir / "ETAGE00.PAK")
    rooms = parse_rooms(pak.read(0))
    assert len(rooms) == 1
    room = rooms[0]
    assert (room.world_x, room.world_y, room.world_z) == (0, 0, 0)
    assert room.camera_indices == [0, 1, 2, 3, 4]
    assert len(room.hard_cols) == 33
    # layout invariant: hard col block ends exactly where sce zones start
    assert room.offset_to_hard_col + 2 + len(room.hard_cols) * 16 == room.offset_to_sce_zones
    zv = room.hard_cols[0]
    assert zv.x1 <= zv.x2 and zv.y1 <= zv.y2 and zv.z1 <= zv.z2


def test_floor0_cameras(data_dir):
    pak = Pak(data_dir / "ETAGE00.PAK")
    cameras = parse_cameras(pak.read(1))
    assert len(cameras) == 5
    cam0 = cameras[0]
    assert (cam0.alpha, cam0.beta, cam0.gamma) == (57, 954, 0)
    assert (cam0.x, cam0.y, cam0.z) == (455, 149, 423)
    assert all(cam.viewed_rooms for cam in cameras)


def test_room_camera_cross_reference(data_dir):
    pak = Pak(data_dir / "ETAGE00.PAK")
    rooms = parse_rooms(pak.read(0))
    cameras = parse_cameras(pak.read(1))
    for room_idx, room in enumerate(rooms):
        for cam_idx in room.camera_indices:
            viewed = [vr.viewed_room_idx for vr in cameras[cam_idx].viewed_rooms]
            assert room_idx in viewed
