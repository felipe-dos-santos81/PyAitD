# SPDX-License-Identifier: GPL-2.0-only
"""GameProfile holds every AITD1-specific constant the engine reads."""
import dataclasses

import pytest

from PyAitD.engine import life
from PyAitD.games import PROFILES, load_profile
from PyAitD.games.aitd1.profile import AITD1

pytestmark = pytest.mark.engine


def test_aitd1_profile_is_registered():
    assert load_profile("aitd1") is AITD1
    assert PROFILES == {"aitd1": ("PyAitD.games.aitd1.profile", "AITD1")}
    with pytest.raises(KeyError):
        load_profile("aitd2")


def test_aitd1_profile_pins_the_pak_and_hero_names():
    assert (AITD1.lifes_pak, AITD1.tracks_pak, AITD1.text_pak, AITD1.resource_pak) == (
        "LISTLIFE", "LISTTRAK", "ENGLISH", "ITD_RESS"
    )
    assert AITD1.hero_archives(0) == ("LISTBODY", "LISTANIM")
    assert AITD1.hero_archives(1) == ("LISTBOD2", "LISTANI2")
    with pytest.raises(ValueError):
        AITD1.hero_archives(2)


def test_aitd1_cvars_and_defines():
    assert len(AITD1.cvar_names) == 16
    assert AITD1.cvar_index("CHOOSE_PERSO") == 8
    assert AITD1.cvar_index("FOG_FLAG") == 14
    assert AITD1.defines_big_endian is True


def test_aitd1_opcode_table_is_complete_and_immutable():
    # AITD1LifeMacroTable (AITD1.cpp:30-119): 87 entries; dead slots raise
    assert len(AITD1.opcode_table) == 87
    assert all(callable(h) for h in AITD1.opcode_table)
    with pytest.raises(dataclasses.FrozenInstanceError):
        AITD1.name = "x"


def test_aitd1_opcode_table_pins_handler_identity_per_slot():
    # Not just completeness -- which handler sits in which slot, per
    # AITD1LifeMacroTable (AITD1.cpp:30-119). Guards against a refactor
    # that silently shuffles two handlers between opcode numbers.
    from PyAitD.games.aitd1 import life_ops as ops

    assert AITD1.opcode_table[41] is ops.op_game_over        # LM_GAME_OVER
    assert AITD1.opcode_table[86] is ops.op_wait_game_over   # LM_WAIT_GAME_OVER
    # LM_CAMERA, LM_STOP_BETA, LM_DO_NORMAL_ZV, LM_SPEED: dead in AITD1, FITD asserts
    dead = {i for i, h in enumerate(AITD1.opcode_table) if h is life._op_dead}
    assert dead == {27, 57, 61, 69}


def test_aitd1_debug_venues_and_reduced_dispatch():
    from PyAitD.games.aitd1 import life_reduced, scenario
    assert AITD1.reduced_dispatch is life_reduced.reduced_dispatch
    assert AITD1.debug_venues == {
        "combat-venue": scenario.enter_combat_venue,
        "mouse-combat-fixture": scenario.enter_mouse_combat_fixture,
    }


def test_aitd1_reduced_allowed_pins_the_out_of_floor_opcode_set():
    # life.cpp:522-716: the reduced switch has a case for exactly these 16
    # opcodes; every other opcode on an out-of-floor world object is an error
    # FITD does not reach. The set is AITD1's, so it lives in the profile
    # beside reduced_dispatch, not in engine/life.py.
    assert AITD1.reduced_allowed == frozenset(
        {1, 2, 3, 13, 15, 24, 28, 31, 40, 47, 48, 49, 54, 55, 67, 74}
    )
    assert isinstance(AITD1.reduced_allowed, frozenset)
    assert not hasattr(life, "_REDUCED_ALLOWED")

    # Nothing else ties reduced_allowed to reduced_dispatch's elif chain -- a
    # dispatch case added without its opcode in reduced_allowed (or vice
    # versa) would go unnoticed by the literal-set pin above. reduced_dispatch
    # (life_reduced.py) falls through an unhandled opcode to
    # `raise ValueError(f"opcode {opcode} has no reduced handler")`, so every
    # opcode in reduced_allowed must reach a real elif branch instead of that
    # fallback. Operands are all-zero bytes: every handler in the reduced set
    # only reads s16 words (read_s16) or, for LM_BODY, one evalVar immediate
    # (tag 0 -> game.vars[0]), so a zero-filled script satisfies every case
    # without needing real actor/world data.
    from PyAitD.games.aitd1 import life_reduced

    class _World:
        def __init__(self):
            self.flags = 0
            self.found_flag = 0
            self.life_mode = 0

    class _Game:
        def __init__(self):
            self.vars = [0]
            self.world_objects = [_World()]
            self.current_floor = 0
            self.flag_genere_aff_list = 0

    class _Vm:
        def __init__(self, game):
            self.script = bytes(32)
            self.pc = 0
            self.game = game

    game = _Game()
    for opcode in AITD1.reduced_allowed:
        try:
            life_reduced.reduced_dispatch(_Vm(game), opcode, 0)
        except ValueError as exc:
            if "has no reduced handler" in str(exc):
                pytest.fail(f"opcode {opcode} is in reduced_allowed but reduced_dispatch has no handler for it")
            raise


def test_aitd1_start_floors_follow_startAITD1():
    # AITD1.cpp:352-361: startGame(7, 1, 0) is the intro, startGame(0, 0, 1) the game
    assert AITD1.intro_start == (7, 1)
    assert AITD1.game_start == (0, 0)
    fields = {f.name: f for f in dataclasses.fields(AITD1)}
    assert fields["intro_start"].default is None
    assert fields["game_start"].default == (0, 0)


def test_aitd1_palette_entry_pins_the_resource_palette_slot():
    # ITD_RESS entry 3 is the 768-byte VGA palette (6 bits per channel).
    # Both engine/floor.py and engine/assets.py used to hardcode the 3.
    assert AITD1.palette_entry == 3
    from PyAitD.engine import assets, floor
    assert not hasattr(floor, "PALETTE_PAK")
    assert not hasattr(floor, "PALETTE_ENTRY")
    assert not hasattr(assets, "GAME_PALETTE_ENTRY")
