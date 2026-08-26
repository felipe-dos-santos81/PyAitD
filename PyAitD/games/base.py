# SPDX-License-Identifier: GPL-2.0-only
"""GameProfile: the per-game constants the engine reads at runtime.

FITD branches on g_gameId in boot (main.cpp), opcode semantics (life.cpp),
getCVarsIdx, and a few format variants. This holds the per-game constants
extracted so far; engine/ still encodes AITD1 opcode numbering (life.py's
NUM_OPCODES and core_table() slots) and record layouts (formats.py), so a
second game will need further seams."""
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class GameProfile:
    name: str
    lifes_pak: str
    tracks_pak: str
    text_pak: str
    resource_pak: str
    heroes: tuple            # ((body_archive, anim_archive), ...) indexed by hero
    cvar_names: tuple
    defines_big_endian: bool
    opcode_table: tuple      # index == opcode; every slot callable(vm)
    reduced_dispatch: object # callable(vm, opcode, world_idx): not-in-floor ops
    debug_venues: Mapping    # CLI venue name -> callable(game)
    # (stage, room) FITD's per-game boot passes to startGame (AITD1.cpp:352-361):
    # the scripted opening with allowSystemMenu=0, or None when the game has
    # none, and the playable start with allowSystemMenu=1.
    intro_start: tuple | None = None
    game_start: tuple = (0, 0)

    def cvar_index(self, name):
        return self.cvar_names.index(name)

    def hero_archives(self, hero):
        if not 0 <= hero < len(self.heroes):
            raise ValueError(f"hero must be 0..{len(self.heroes) - 1}, got {hero}")
        return self.heroes[hero]
