# SPDX-License-Identifier: GPL-2.0-only
"""Floor loading: rooms, cameras, palette, camera background images."""
import functools

from PyAitD.engine.data.formats import camera_offsets, decode_image, decode_palette, parse_cameras, parse_rooms
from PyAitD.engine.data.mask_geometry import mask_polygons
from PyAitD.engine.data.pak import Pak, find_pak


@functools.lru_cache(maxsize=64)
def load_entry(pak_path, index):
    return Pak(pak_path).read(index)


def cache_clear():
    load_entry.cache_clear()


class Floor:
    def __init__(self, data_dir, number, profile):
        self.number = number
        self.profile = profile
        self.viewed_room_record_size = profile.viewed_room_record_size
        etage = find_pak(data_dir, profile.floor_archive_name(number))
        self._images = find_pak(data_dir, profile.camera_archive_name(number))
        self.rooms = parse_rooms(load_entry(str(etage), 0))
        self.camera_raw = load_entry(str(etage), 1)
        self.cameras = parse_cameras(self.camera_raw, profile.viewed_room_record_size)
        self.camera_data_offsets = camera_offsets(self.camera_raw)
        palette_pak = find_pak(data_dir, profile.resource_pak)
        self.palette = decode_palette(load_entry(str(palette_pak), profile.palette_entry))
        self._num_images = Pak(self._images).count
        self._camera_images = {}
        self._masks = {}
        self._mask_draws = {}

    def camera_image(self, camera_idx):
        if not 0 <= camera_idx < self._num_images:
            raise KeyError(f"floor {self.number}: camera image {camera_idx} out of range")
        if camera_idx not in self._camera_images:
            raw = load_entry(str(self._images), camera_idx)
            self._camera_images[camera_idx] = decode_image(raw, self.palette)
        return self._camera_images[camera_idx]

    def masks(self, camera_idx):
        # occlusion masks are static camera data; read-only in the render path
        if camera_idx not in self._masks:
            self._masks[camera_idx] = self.profile.mask_factory(
                self.camera_raw, self.camera_data_offsets[camera_idx],
                self.viewed_room_record_size,
            )
        return self._masks[camera_idx]

    def mask_draws(self, camera_idx):
        # foreground mask polygons in 320x200 screen space; static camera
        # data, read-only in the render path
        if camera_idx not in self._mask_draws:
            self._mask_draws[camera_idx] = mask_polygons(
                self.camera_raw, self.camera_data_offsets[camera_idx],
                self.viewed_room_record_size,
            )
        return self._mask_draws[camera_idx]
