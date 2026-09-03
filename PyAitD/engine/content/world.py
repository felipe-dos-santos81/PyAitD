# SPDX-License-Identifier: GPL-2.0-only
"""Compile pack records to appended WorldObjects and attach them to a Game.

Imports script.game's leaf modules only: script.game's __init__ imports
boot, and boot imports this module (lazily, inside init_game), so importing
the package back would see it half-initialised."""
from dataclasses import dataclass

from PyAitD.engine.content.schema import BEHAVIOUR_LIFE
from PyAitD.engine.data.formats import WorldObject
from PyAitD.engine.script.game.state import AF_ANIMATED, AF_FALLABLE, AF_SPECIAL


@dataclass
class ContentAttachment:
    pack: object
    first_index: int   # world index of the first appended record
    records: dict      # world index -> EnemyRecord

    def record_for(self, world_idx):
        return self.records.get(world_idx)


def compile_record(record):
    """One EnemyRecord -> the WorldObject spawn_stage_actors will place.
    Shaped like an original creature's record (world 21: flags 0x21, anim -1
    until its LIFE dresses it) except that it spawns already standing, the
    way floor 5's enemy 222 is stored (anim 199, repeat)."""
    flags = AF_ANIMATED | AF_SPECIAL      # AF_SPECIAL (0x20): dyn_flags collision on
    if record.falls:
        flags |= AF_FALLABLE
    x, y, z = record.position
    return WorldObject(
        obj_index=-1, body=record.body, flags=flags, type_zv=record.type_zv,
        found_body=-1, found_name=-1, found_flag=0, found_life=-1,
        x=x, y=y, z=z, alpha=0, beta=record.beta, gamma=0,
        stage=record.stage, room=record.room,
        life_mode=record.life_mode, life=BEHAVIOUR_LIFE, floor_life=-1,
        anim=record.anims.stand, frame=0, anim_type=1, anim_info=-1,
        track_mode=0, track_number=-1, position_in_track=0, mark=0,
    )


def attach(game, pack):
    """Append the pack's records to game.world_objects and seed game.content
    and game.content_state. None for pack=None; raises if a pack is already
    attached (a Game is attached exactly once, in init_game)."""
    if pack is None:
        return None
    if game.content is not None:
        raise ValueError("a content pack is already attached to this game")
    first = len(game.world_objects)
    records = {}
    for offset, record in enumerate(pack.enemies):
        idx = first + offset
        game.world_objects.append(compile_record(record))
        records[idx] = record
        game.content_state[idx] = {"hp": record.hit_points, "phase": "idle"}
    game.content = ContentAttachment(pack, first, records)
    return game.content
