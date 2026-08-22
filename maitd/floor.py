# SPDX-License-Identifier: GPL-2.0-only
"""Floor loading: rooms, cameras, palette, camera background images."""
import functools

from maitd.formats import decode_image, decode_palette, parse_cameras, parse_rooms
from maitd.pak import Pak, find_pak

PALETTE_PAK = "ITD_RESS"
PALETTE_ENTRY = 3


@functools.lru_cache(maxsize=64)
def load_entry(pak_path, index):
    return Pak(pak_path).read(index)


def cache_clear():
    load_entry.cache_clear()


class Floor:
    def __init__(self, data_dir, number):
        self.number = number
        etage = find_pak(data_dir, f"ETAGE{number:02d}")
        self._images = find_pak(data_dir, f"CAMERA{number:02d}")
        self.rooms = parse_rooms(load_entry(str(etage), 0))
        self.cameras = parse_cameras(load_entry(str(etage), 1))
        palette_pak = find_pak(data_dir, PALETTE_PAK)
        self.palette = decode_palette(load_entry(str(palette_pak), PALETTE_ENTRY))
        self._num_images = Pak(self._images).count

    def camera_image(self, camera_idx):
        if not 0 <= camera_idx < self._num_images:
            raise KeyError(f"floor {self.number}: camera image {camera_idx} out of range")
        raw = load_entry(str(self._images), camera_idx)
        return decode_image(raw, self.palette)
