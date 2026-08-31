# SPDX-License-Identifier: GPL-2.0-only
"""Neutral filler for the per-game seam fields, for tests that build a
minimal GameProfile and never exercise them."""


def neutral_seam_fields():
    """kwargs for every GameProfile seam field, at neutral values.

    mask_factory takes the documented 3-arg contract but returns None:
    these stubs never load a Floor.
    """
    return dict(
        debug_venues={}, generation=0,
        floor_archive_name=lambda n: "E", camera_archive_name=lambda n: "C",
        mask_factory=lambda raw, off, stride: None, cadre_bank=(0, 0),
        core_slots={}, combat_action_text_ids=frozenset(),
        player_stand_anim=0, player_push_anim=0, player_track_modes=(),
        viewed_room_record_size=0x0C, world_object_has_mark=False,
    )
