# SPDX-License-Identifier: GPL-2.0-only
"""Alone in the Dark 1 profile: PAK names, hero archives, CVars, the filled
AITD1LifeMacroTable (AITD1.cpp:30-119), reduced dispatch, debug venues."""
from types import MappingProxyType

from PyAitD.engine.data.mask import create_aitd1_mask
from PyAitD.engine.script import life
from PyAitD.engine.actor.tracks import process_track
from PyAitD.games.aitd1 import life_ops as ops
from PyAitD.games.aitd1 import scenario
from PyAitD.games.aitd1.life_reduced import reduced_dispatch
from PyAitD.games.base import GameProfile

CVAR_NAMES = (
    "SAMPLE_PAGE", "BODY_FLAMME", "MAX_WEIGHT_LOADABLE", "TEXTE_CREDITS",
    "SAMPLE_TONNERRE", "INTRO_DETECTIVE", "INTRO_HERITIERE", "WORLD_NUM_PERSO",
    "CHOOSE_PERSO", "SAMPLE_CHOC", "SAMPLE_PLOUF", "REVERSE_OBJECT",
    "KILLED_SORCERER", "LIGHT_OBJECT", "FOG_FLAG", "DEAD_PERSO",
)

# life.cpp:522-716: the opcodes FITD's reduced (out-of-floor) switch has a
# case for. Anything else on a world object whose obj_index is -1 is an error.
REDUCED_ALLOWED = frozenset({1, 2, 3, 13, 15, 24, 28, 31, 40, 47, 48, 49, 54, 55, 67, 74})

# AITD1LifeMacroTable (AITD1.cpp:30-119): slot count, the VM-control
# numbering within it, and the holes in FITD's dispatch switch.
NUM_OPCODES = 87
CORE_SLOTS = MappingProxyType({
    "IF_EGAL": 4, "IF_DIFFERENT": 5, "IF_SUP_EGAL": 6, "IF_SUP": 7,
    "IF_INF_EGAL": 8, "IF_INF": 9, "GOTO": 10, "RETURN": 11, "END": 12,
    "VAR": 19, "INC": 20, "DEC": 21, "ADD": 22, "SUB": 23,
    "LIFE_MODE": 24, "SWITCH": 25, "CASE": 26, "START_CHRONO": 28,
    "MULTI_CASE": 29,
})
DEAD_OPCODES = frozenset({27, 57, 61, 69})


def floor_archive_name(number):  # floor.cpp:26-28
    return f"ETAGE{number:02d}"


def camera_archive_name(number):
    return f"CAMERA{number:02d}"

def _opcode_table():
    # opcode numbers per AITD1LifeMacroTable (AITD1.cpp:30-119)
    table = life.core_table()
    table[0] = lambda vm: process_track(vm.game, vm.actor)  # LM_DO_MOVE
    table[1] = ops.op_anim_once
    table[2] = ops.op_anim_all_once
    table[3] = ops.op_body
    table[13] = ops.op_anim_repeat
    table[14] = ops.op_anim_move
    table[15] = ops.op_move
    table[16] = ops.op_hit
    table[17] = ops.op_message
    table[18] = ops.op_message_value
    table[30] = ops.op_found
    table[31] = ops.op_life
    table[32] = ops.op_delete
    table[33] = ops.op_take
    table[34] = ops.op_in_hand
    table[35] = ops.op_read
    table[36] = ops.op_anim_sample
    table[37] = ops.op_special
    table[38] = ops.op_do_real_zv
    table[39] = ops.op_sample
    table[40] = ops.op_type
    table[41] = ops.op_game_over
    table[42] = ops.op_manual_rot
    table[43] = ops.op_rnd_freq
    table[44] = ops.op_music
    table[45] = ops.op_set_beta
    table[46] = ops.op_do_rot_zv
    table[47] = ops.op_stage
    table[48] = ops.op_found_name
    table[49] = ops.op_found_flag
    table[50] = ops.op_found_life
    table[51] = ops.op_camera_target
    table[52] = ops.op_drop
    table[53] = ops.op_fire
    table[54] = ops.op_test_col
    table[55] = ops.op_found_body
    table[56] = ops.op_set_alpha
    table[58] = ops.op_do_max_zv
    table[59] = ops.op_put
    table[60] = ops.op_c_var
    table[62] = ops.op_do_carre_zv
    table[63] = ops.op_sample_then
    table[64] = ops.op_light
    table[65] = ops.op_shaking
    table[66] = ops.op_inventory
    table[67] = ops.op_found_weight
    table[68] = ops.op_up_coor_y
    table[70] = ops.op_put_at
    table[71] = ops.op_def_zv
    table[72] = ops.op_hit_object
    table[73] = ops.op_get_hard_clip
    table[74] = ops.op_angle
    table[75] = ops.op_rep_sample
    table[76] = ops.op_throw
    table[77] = ops.op_water
    table[78] = ops.op_picture
    table[79] = ops.op_stop_sample
    table[80] = ops.op_next_music
    table[81] = ops.op_fade_music
    table[82] = ops.op_stop_hit_object
    table[83] = ops.op_copy_angle
    table[84] = ops.op_end_sequence
    table[85] = ops.op_sample_then_repeat
    table[86] = ops.op_wait_game_over
    for i, h in enumerate(table):
        if h.__qualname__.startswith("_op_not_implemented"):
            raise RuntimeError(f"AITD1 opcode table slot {i} left unimplemented")
    return tuple(table)


AITD1 = GameProfile(
    name="aitd1",
    lifes_pak="LISTLIFE",
    tracks_pak="LISTTRAK",
    text_pak="ENGLISH",
    resource_pak="ITD_RESS",
    palette_entry=3,
    heroes=(("LISTBODY", "LISTANIM"), ("LISTBOD2", "LISTANI2")),
    cvar_names=CVAR_NAMES,
    defines_big_endian=True,
    opcode_table=_opcode_table(),
    reduced_dispatch=reduced_dispatch,
    reduced_allowed=REDUCED_ALLOWED,
    debug_venues=MappingProxyType({
        "combat-venue": scenario.enter_combat_venue,
        "mouse-combat-fixture": scenario.enter_mouse_combat_fixture,
    }),
    generation=0,
    floor_archive_name=floor_archive_name,
    camera_archive_name=camera_archive_name,
    mask_factory=create_aitd1_mask,
    cadre_bank=(4, 9),
    core_slots=CORE_SLOTS,
    combat_action_text_ids=frozenset({32}),
    player_stand_anim=4,
    player_push_anim=5,
    player_track_modes=(1, 4),
    viewed_room_record_size=0x0C,
    world_object_has_mark=False,
    intro_start=(7, 1),
    game_start=(0, 0),
    alt_camera_sources=MappingProxyType({(7, 0): 15, (7, 1): 16, (6, 0): 17, (6, 5): 18, (6, 8): 19}),
)
