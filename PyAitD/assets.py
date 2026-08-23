# SPDX-License-Identifier: GPL-2.0-only
"""Parsed body/animation asset registry (parse-once caches over the M1 LRU)."""
from PyAitD.floor import load_entry
from PyAitD.formats import decode_image, decode_palette, parse_anim, parse_body
from PyAitD.pak import Pak, find_pak
from PyAitD.text import parse_book_tokens, parse_system_texts

BODIES_PAK = "LISTBODY"
ANIMS_PAK = "LISTANIM"
LIFES_PAK = "LISTLIFE"
TRACKS_PAK = "LISTTRAK"
TEXT_PAK = "ENGLISH"
RESOURCE_PAK = "ITD_RESS"
GAME_PALETTE_ENTRY = 3


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
        self._text_pak = str(find_pak(data_dir, TEXT_PAK))
        self._resource_pak = str(find_pak(data_dir, RESOURCE_PAK))
        self._system_texts = parse_system_texts(load_entry(self._text_pak, 0))
        self._book_tokens = {}
        self.book_pages = {}  # ui-layer wrapped page layout, keyed by text entry
        self._resource_screens = {}
        self._game_palette = decode_palette(load_entry(self._resource_pak, GAME_PALETTE_ENTRY))

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

    def system_text(self, message_id):
        try:
            return self._system_texts[message_id]
        except KeyError:
            raise KeyError(f"ENGLISH.PAK: text {message_id} not found") from None

    def book_tokens(self, entry):
        if entry not in self._book_tokens:
            self._book_tokens[entry] = parse_book_tokens(load_entry(self._text_pak, entry))
        return self._book_tokens[entry]

    def resource_screen(self, entry):
        if entry not in self._resource_screens:
            raw = load_entry(self._resource_pak, entry)
            if len(raw) < 64000:
                raise ValueError(f"ITD_RESS.PAK: entry {entry} is {len(raw)} bytes; expected 64000")
            self._resource_screens[entry] = decode_image(raw[:64000], self._game_palette)
        return self._resource_screens[entry]

    def clear(self):
        self._bodies.clear()
        self._anims.clear()
        self._book_tokens.clear()
        self.book_pages.clear()
        self._resource_screens.clear()
