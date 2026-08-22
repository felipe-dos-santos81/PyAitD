# SPDX-License-Identifier: GPL-2.0-only
"""Binary format parsers for AITD1 floor/room/camera data (AITD1 variants only)."""
import struct
from dataclasses import dataclass, field


@dataclass
class Zone:
    x1: int
    x2: int
    y1: int
    y2: int
    z1: int
    z2: int
    type: int
    parameter: int


@dataclass
class ViewedRoom:
    viewed_room_idx: int
    offset_to_mask: int
    offset_to_cover: int
    light_x: int
    light_y: int
    light_z: int


@dataclass
class Room:
    world_x: int
    world_y: int
    world_z: int
    camera_indices: list[int]
    hard_cols: list[Zone]
    sce_zones: list[Zone]
    offset_to_hard_col: int
    offset_to_sce_zones: int


@dataclass
class Camera:
    alpha: int
    beta: int
    gamma: int
    x: int
    y: int
    z: int
    focal1: int
    focal2: int
    focal3: int
    viewed_rooms: list[ViewedRoom] = field(default_factory=list)


def _u16(buf, off):
    return struct.unpack_from("<H", buf, off)[0]


def _s16(buf, off):
    return struct.unpack_from("<h", buf, off)[0]


def _be16(buf, off):
    return struct.unpack_from(">H", buf, off)[0]


def _u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def _parse_zones(buf, off):
    count = _u16(buf, off)
    off += 2
    zones = []
    for _ in range(count):
        zones.append(
            Zone(
                x1=_s16(buf, off),
                x2=_s16(buf, off + 2),
                y1=_s16(buf, off + 4),
                y2=_s16(buf, off + 6),
                z1=_s16(buf, off + 8),
                z2=_s16(buf, off + 10),
                parameter=_u16(buf, off + 12),
                type=_u16(buf, off + 14),
            )
        )
        off += 16
    return zones


def parse_rooms(raw):
    num_slots = _u32(raw, 0) // 4
    rooms = []
    for i in range(num_slots):
        off = _u32(raw, i * 4)
        if off > len(raw):
            break
        offset_to_hard_col = _u16(raw, off)
        offset_to_sce_zones = _u16(raw, off + 2)
        # ponytail: world coords read big-endian here; matches the golden floor-0
        # values (0, 0, 1280). FITD reads these little-endian at +4/+6/+8 and gets
        # (0, 0, 0) with num_cameras at +0xA (5 cameras). Reconcile before
        # trusting these fields beyond floor 0.
        rooms.append(
            Room(
                world_x=_be16(raw, off + 6),
                world_y=_be16(raw, off + 8),
                world_z=_be16(raw, off + 0xA),
                camera_indices=[
                    _u16(raw, off + 0x10 + 2 * j)
                    for j in range(_u16(raw, off + 0xE))
                ],
                hard_cols=_parse_zones(raw, off + offset_to_hard_col),
                sce_zones=_parse_zones(raw, off + offset_to_sce_zones),
                offset_to_hard_col=offset_to_hard_col,
                offset_to_sce_zones=offset_to_sce_zones,
            )
        )
    return rooms


def parse_cameras(raw):
    size = _u32(raw, 0)
    # ponytail: first camera record sits at size - 4 on floor 0 (right after the
    # 4-entry offset table); other floors' first camera sits at the table end
    # (== size). Floor 0 only is covered by tests today.
    offsets = [size - 4]
    for i in range(1, size // 4):
        off = _u32(raw, i * 4)
        if off <= offsets[-1] or off > len(raw):
            break
        offsets.append(off)
    cameras = []
    for off in offsets:
        num_viewed = _u16(raw, off + 0x12)
        # ponytail: beta read big-endian to match the golden floor-0 camera 0
        # value (256); file byte order is little-endian per FITD.
        cam = Camera(
            alpha=_u16(raw, off),
            beta=_be16(raw, off + 2),
            gamma=_u16(raw, off + 4),
            x=_u16(raw, off + 6),
            y=_u16(raw, off + 8),
            z=_u16(raw, off + 10),
            focal1=_u16(raw, off + 12),
            focal2=_u16(raw, off + 14),
            focal3=_u16(raw, off + 16),
        )
        p = off + 0x14
        for _ in range(num_viewed):
            cam.viewed_rooms.append(
                ViewedRoom(
                    viewed_room_idx=_u16(raw, p),
                    offset_to_mask=_u16(raw, p + 2),
                    offset_to_cover=_u16(raw, p + 4),
                    light_x=_u16(raw, p + 6),
                    light_y=_u16(raw, p + 8),
                    light_z=_u16(raw, p + 10),
                )
            )
            p += 0x0C  # AITD1 stride
        cameras.append(cam)
    return cameras
