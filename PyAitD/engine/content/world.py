# SPDX-License-Identifier: GPL-2.0-only
"""Compile pack records to appended WorldObjects and attach them to a Game.

Imports script.game's leaf modules only: script.game's __init__ imports
boot, and boot imports this module (lazily, inside init_game), so importing
the package back would see it half-initialised."""
from dataclasses import dataclass

from PyAitD.engine.content.schema import BEHAVIOUR_LIFE, KINDS
from PyAitD.engine.data.formats import WorldObject
from PyAitD.engine.script.game.state import AF_ANIMATED, AF_FALLABLE, AF_FOUNDABLE, AF_MOVABLE, AF_SPECIAL

CONTENT_TEXT_BASE = 2000
"""First text id a pack string may take; the vanilla table tops out at 1150
(tests/test_content_pack.py pins it)."""


@dataclass
class ContentAttachment:
    pack: object
    first_index: int   # world index of the first appended record
    records: dict      # world index -> record (enemy or object)
    by_id: dict        # pack id -> world index
    text_ids: dict     # pack string -> text id registered in game.assets
    flags: set         # the pack's named flags currently set

    def record_for(self, world_idx):
        return self.records.get(world_idx)


def allocate_texts(objects):
    """Every distinct pack string -> one text id from CONTENT_TEXT_BASE, in
    first-seen order: per object, the pickup name, its action labels, then
    the messages of its rules in text order. A pure function of the pack,
    so a saved message id names the same string after a load."""
    ids = {}

    def take(string):
        if string not in ids:
            ids[string] = CONTENT_TEXT_BASE + len(ids)

    for record in objects:
        if record.kind == "pickup":
            take(record.name)
            for action in record.actions:
                take(action.label)
        for _key, rule in record.rules():
            for effect in rule.then:
                if effect.op == "message":
                    take(effect.arg)
    return ids


def _compile_enemy(record):
    """Shaped like an original creature's record (world 21: flags 0x21, anim -1
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


def _compile_pickup(record, text_ids):
    """A boot-time vanilla pickup (flags 0xa0, no LIFE). track_number 0, not
    the vanilla -1: request_found refuses the prompt while
    timer - track_number < 300, which would hide a pickup near the start."""
    x, y, z = record.position
    return WorldObject(
        obj_index=-1, body=record.body, flags=AF_FOUNDABLE | AF_SPECIAL, type_zv=record.type_zv,
        found_body=-1, found_name=text_ids[record.name], found_flag=0, found_life=-1,
        x=x, y=y, z=z, alpha=0, beta=record.beta, gamma=0,
        stage=record.stage, room=record.room,
        life_mode=0, life=-1, floor_life=-1,
        anim=-1, frame=0, anim_type=0, anim_info=-1,
        track_mode=0, track_number=0, position_in_track=record.weight, mark=0,
    )


def _compile_scenery(record):
    """A vanilla static (0x20), pushable ones 0x30 like the attic crate."""
    x, y, z = record.position
    return WorldObject(
        obj_index=-1, body=record.body, flags=AF_SPECIAL | (AF_MOVABLE if record.pushable else 0),
        type_zv=record.type_zv,
        found_body=-1, found_name=-1, found_flag=0, found_life=-1,
        x=x, y=y, z=z, alpha=0, beta=record.beta, gamma=0,
        stage=record.stage, room=record.room,
        life_mode=0, life=-1, floor_life=-1,
        anim=-1, frame=0, anim_type=0, anim_info=-1,
        track_mode=0, track_number=-1, position_in_track=0, mark=0,
    )


def _compile_trigger(record):
    """A placeholder that never spawns (stage -1): a body-less actor would
    carry the default volume and block the hero. The box and room live on
    the record; the world index is what by_id and content_state key on."""
    return WorldObject(
        obj_index=-1, body=-1, flags=0, type_zv=0,
        found_body=-1, found_name=-1, found_flag=0, found_life=-1,
        x=0, y=0, z=0, alpha=0, beta=0, gamma=0, stage=-1, room=-1,
        life_mode=0, life=-1, floor_life=-1,
        anim=-1, frame=0, anim_type=0, anim_info=-1,
        track_mode=0, track_number=-1, position_in_track=0, mark=0,
    )


def compile_record(record, text_ids=None):
    """One pack record -> the WorldObject spawn_stage_actors will place."""
    if record.kind in KINDS:
        return _compile_enemy(record)
    if record.kind == "pickup":
        return _compile_pickup(record, text_ids)
    if record.kind == "scenery":
        return _compile_scenery(record)
    return _compile_trigger(record)


def initial_state(record):
    """The content_state entry a fresh game seeds for `record`."""
    if record.kind in KINDS:
        return {"hp": record.hit_points, "phase": "idle"}
    if record.kind == "trigger":
        return {"armed": True, "inside": False}
    return {}


def attach(game, pack):
    """Register the pack's strings, append its records (enemies, then
    objects) to game.world_objects and seed game.content and
    game.content_state. None for pack=None; raises if a pack is already
    attached (a Game is attached exactly once, in init_game)."""
    if pack is None:
        return None
    if game.content is not None:
        raise ValueError("a content pack is already attached to this game")
    text_ids = allocate_texts(pack.objects)
    game.assets.register_texts({text_id: string for string, text_id in text_ids.items()})
    first = len(game.world_objects)
    records, by_id = {}, {}
    for offset, record in enumerate(pack.enemies + pack.objects):
        idx = first + offset
        game.world_objects.append(compile_record(record, text_ids))
        records[idx] = record
        by_id[record.id] = idx
        game.content_state[idx] = initial_state(record)
    game.content = ContentAttachment(pack, first, records, by_id, text_ids, set())
    return game.content
