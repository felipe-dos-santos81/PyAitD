# SPDX-License-Identifier: GPL-2.0-only
"""Parsed body/animation asset registry (parse-once caches over the M1 LRU)."""
from maitd.floor import load_entry
from maitd.formats import parse_anim, parse_body
from maitd.pak import Pak, find_pak

BODIES_PAK = "LISTBODY"
ANIMS_PAK = "LISTANIM"
LIFES_PAK = "LISTLIFE"
TRACKS_PAK = "LISTTRAK"


class Assets:
    def __init__(self, data_dir):
        self._bodies_pak = str(find_pak(data_dir, BODIES_PAK))
        self._anims_pak = str(find_pak(data_dir, ANIMS_PAK))
        self._lifes_pak = str(find_pak(data_dir, LIFES_PAK))
        self._tracks_pak = str(find_pak(data_dir, TRACKS_PAK))
        self.num_bodies = Pak(self._bodies_pak).count
        self.num_anims = Pak(self._anims_pak).count
        self.num_lifes = Pak(self._lifes_pak).count
        self.num_tracks = Pak(self._tracks_pak).count
        self._bodies = {}
        self._anims = {}

    def body(self, index):
        if not 0 <= index < self.num_bodies:
            raise KeyError(f"body {index} out of range (0..{self.num_bodies - 1})")
        if index not in self._bodies:
            self._bodies[index] = parse_body(load_entry(self._bodies_pak, index))
        return self._bodies[index]

    def anim(self, index):
        if not 0 <= index < self.num_anims:
            raise KeyError(f"anim {index} out of range (0..{self.num_anims - 1})")
        if index not in self._anims:
            self._anims[index] = parse_anim(load_entry(self._anims_pak, index))
        return self._anims[index]

    def life(self, index):
        if not 0 <= index < self.num_lifes:
            raise KeyError(f"life {index} out of range (0..{self.num_lifes - 1})")
        return load_entry(self._lifes_pak, index)

    def track(self, index):
        if not 0 <= index < self.num_tracks:
            raise KeyError(f"track {index} out of range (0..{self.num_tracks - 1})")
        return load_entry(self._tracks_pak, index)

    def clear(self):
        self._bodies.clear()
        self._anims.clear()
