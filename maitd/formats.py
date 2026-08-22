# SPDX-License-Identifier: GPL-2.0-only
"""Binary format parsers for AITD1 floor/room/camera data (AITD1 variants only)."""
import struct
from dataclasses import dataclass, field

import numpy as np


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
        try:
            off = _u32(raw, i * 4)
            if off >= len(raw):
                break
            offset_to_hard_col = _u16(raw, off)
            offset_to_sce_zones = _u16(raw, off + 2)
            num_cameras = _u16(raw, off + 0xA)
            camera_indices = [_u16(raw, off + 0xC + 2 * j) for j in range(num_cameras)]
            rooms.append(
                Room(
                    world_x=_s16(raw, off + 4),
                    world_y=_s16(raw, off + 6),
                    world_z=_s16(raw, off + 8),
                    camera_indices=camera_indices,
                    hard_cols=_parse_zones(raw, off + offset_to_hard_col),
                    sce_zones=_parse_zones(raw, off + offset_to_sce_zones),
                    offset_to_hard_col=offset_to_hard_col,
                    offset_to_sce_zones=offset_to_sce_zones,
                )
            )
        except struct.error:
            raise ValueError(f"corrupt room data entry {i}")
    return rooms


def camera_offsets(raw):
    num_slots = _u32(raw, 0) // 4
    offsets = []
    highest = 0
    for i in range(num_slots):
        off = _u32(raw, i * 4)
        # stop at non-increasing offsets or offsets past the buffer (the table
        # can hold junk slots beyond the valid cameras — floor 0 has one)
        if off <= highest or off >= len(raw):
            break
        highest = off
        offsets.append(off)
    return offsets


def parse_cameras(raw):
    cameras = []
    for off in camera_offsets(raw):
        try:
            num_viewed = _u16(raw, off + 0x12)
            cam = Camera(
                alpha=_u16(raw, off),
                beta=_u16(raw, off + 2),
                gamma=_u16(raw, off + 4),
                x=_s16(raw, off + 6),
                y=_s16(raw, off + 8),
                z=_s16(raw, off + 10),
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
        except struct.error:
            raise ValueError(f"corrupt camera data offset {off}")
    return cameras


def decode_palette(raw):
    if len(raw) != 768:
        raise ValueError(f"palette must be 768 bytes, got {len(raw)}")
    # game palettes are stored 8-bit (verified: 470/768 values above 63 in
    # ITD_RESS entry 3); FITD copies them raw and divides by 255 in the shader
    return np.frombuffer(raw, dtype=np.uint8).reshape(256, 3).copy()


def decode_image(raw, palette):
    if len(raw) != 64000:
        raise ValueError(f"image must be 64000 bytes, got {len(raw)}")
    indices = np.frombuffer(raw, dtype=np.uint8).reshape(200, 320)
    return palette[indices]


@dataclass
class Primitive:
    type: int
    material: int
    color: int
    points: list[int]
    size: int = 0


@dataclass
class Group:
    start: int
    num_vertices: int
    base_vertices: int
    org_group: int
    num_group: int
    delta_x: int
    delta_y: int
    delta_z: int


@dataclass
class Body:
    flags: int
    zv: tuple
    scratch: tuple
    vertices: list
    groups: list
    group_order: list
    primitives: list


@dataclass
class Frame:
    timestamp: int
    anim_step: tuple
    group_types: list
    group_deltas: list


@dataclass
class Animation:
    num_frames: int
    num_groups: int
    frames: list


INFO_ANIM = 2

_PRIM_POINT_LIKE = (2, 6, 7)  # Point, BigPoint, Zixel


def parse_body(raw):
    p = 0
    flags = _u16(raw, p)
    p += 2
    zv = tuple(struct.unpack_from("<6h", raw, p))
    p += 12
    scratch_size = _u16(raw, p)
    p += 2
    scratch = tuple(raw[p : p + scratch_size])
    p += scratch_size
    num_vertices = _u16(raw, p)
    p += 2
    vertices = [
        (struct.unpack_from("<h", raw, p + 6 * i)[0],
         struct.unpack_from("<h", raw, p + 6 * i + 2)[0],
         struct.unpack_from("<h", raw, p + 6 * i + 4)[0])
        for i in range(num_vertices)
    ]
    p += num_vertices * 6
    groups = []
    group_order = []
    if flags & INFO_ANIM:
        num_groups = _u16(raw, p)
        p += 2
        group_order = [v // 0x10 for v in struct.unpack_from(f"<{num_groups}H", raw, p)]
        p += num_groups * 2
        for _ in range(num_groups):
            groups.append(
                Group(
                    start=_u16(raw, p) // 6,
                    num_vertices=_u16(raw, p + 2),
                    base_vertices=_u16(raw, p + 4) // 6,
                    org_group=raw[p + 6],
                    num_group=raw[p + 7],
                    delta_x=_s16(raw, p + 10),
                    delta_y=_s16(raw, p + 12),
                    delta_z=_s16(raw, p + 14),
                )
            )
            p += 0x10
    num_primitives = _u16(raw, p)
    p += 2
    primitives = []
    for _ in range(num_primitives):
        prim_type = raw[p]
        p += 1
        if prim_type in (1, 8, 9, 10):  # poly family
            num_points = raw[p]
            p += 1
            material, color = raw[p], raw[p + 1]
            p += 2
            points = list(struct.unpack_from(f"<{num_points}H", raw, p))
            p += num_points * 2
            primitives.append(Primitive(prim_type, material, color, [v // 6 for v in points]))
        elif prim_type == 0:  # line
            material, color = raw[p], raw[p + 1]
            p += 3
            points = list(struct.unpack_from("<2H", raw, p))
            p += 4
            primitives.append(Primitive(prim_type, material, color, [v // 6 for v in points]))
        elif prim_type in _PRIM_POINT_LIKE:  # point / big point / zixel
            material, color = raw[p], raw[p + 1]
            p += 3
            point = _u16(raw, p)
            p += 2
            primitives.append(Primitive(prim_type, material, color, [point // 6]))
        elif prim_type == 3:  # sphere
            material, color = raw[p], raw[p + 1]
            p += 3
            size = _u16(raw, p)
            p += 2
            point = _u16(raw, p)
            p += 2
            primitives.append(Primitive(prim_type, material, color, [point // 6], size=size))
        else:
            raise ValueError(f"body: unknown primitive type {prim_type} at byte {p - 1}")
    return Body(flags, zv, scratch, vertices, groups, group_order, primitives)


def parse_anim(raw):
    if len(raw) < 4:
        raise ValueError(f"anim too small: {len(raw)} bytes")
    num_frames = _u16(raw, 0)
    num_groups = _u16(raw, 2)
    p = 4
    frames = []
    for _ in range(num_frames):
        timestamp = _u16(raw, p)
        step = (struct.unpack_from("<h", raw, p + 2)[0],
                struct.unpack_from("<h", raw, p + 4)[0],
                struct.unpack_from("<h", raw, p + 6)[0])
        p += 8
        types = []
        deltas = []
        for _ in range(num_groups):
            types.append(_s16(raw, p))
            deltas.append((_s16(raw, p + 2), _s16(raw, p + 4), _s16(raw, p + 6)))
            p += 8
        frames.append(Frame(timestamp, step, types, deltas))
    return Animation(num_frames, num_groups, frames)


@dataclass
class WorldObject:
    obj_index: int
    body: int
    flags: int
    type_zv: int
    found_body: int
    found_name: int
    found_flag: int
    found_life: int
    x: int
    y: int
    z: int
    alpha: int
    beta: int
    gamma: int
    stage: int
    room: int
    life_mode: int
    life: int
    floor_life: int
    anim: int
    frame: int
    anim_type: int
    anim_info: int
    track_mode: int
    track_number: int
    position_in_track: int


_WORLD_OBJ_FIELDS = (
    "obj_index", "body", "flags", "type_zv", "found_body", "found_name",
    "found_flag", "found_life", "x", "y", "z", "alpha", "beta", "gamma",
    "stage", "room", "life_mode", "life", "floor_life", "anim", "frame",
    "anim_type", "anim_info", "track_mode", "track_number", "position_in_track",
)


def parse_objets(raw):
    # FITD LoadWorld (main.cpp:1005): u16 count + fixed 26-s16 records, flags |= 0x20
    count = _u16(raw, 0)
    p = 2
    out = []
    for _ in range(count):
        values = list(struct.unpack_from("<26h", raw, p))
        p += 52
        values[2] |= 0x20
        out.append(WorldObject(*values))
    return out


def parse_vars(raw):
    # VARS.ITD: raw s16 array read by evalVar tag 0 (read-only in AITD1)
    n = len(raw) // 2
    return list(struct.unpack_from(f"<{n}h", raw, 0))


def parse_defines(raw):
    # DEFINES.ITD: 45 CVars stored big-endian; LoadWorld byteswaps (main.cpp:1151)
    n = len(raw) // 2
    values = list(struct.unpack_from(f"<{n}H", raw, 0))
    return [((v & 0xFF) << 8) | ((v & 0xFF00) >> 8) for v in values]


def parse_priority(raw):
    # PRIORITY.ITD: raw s16 array (odd trailing byte ignored); semantics M4
    n = len(raw) // 2
    return list(struct.unpack_from(f"<{n}h", raw, 0))


def parse_cover_zones(camera_raw, camera_off, viewed_idx):
    vr_off = camera_off + 0x14 + viewed_idx * 0x0C
    cover_off = camera_off + _u16(camera_raw, vr_off + 4)
    num_zones = _u16(camera_raw, cover_off)
    p = cover_off + 2
    zones = []
    for _ in range(num_zones):
        num_points = _u16(camera_raw, p)
        p += 2
        points = [(_s16(camera_raw, p + 4 * k), _s16(camera_raw, p + 4 * k + 2)) for k in range(num_points)]
        p += num_points * 4
        zones.append(points)
    return zones
