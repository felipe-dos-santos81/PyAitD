# SPDX-License-Identifier: GPL-2.0-only
"""GameProfile holds every AITD1-specific constant the engine reads."""
import dataclasses

import pytest

from PyAitD.games import PROFILES, load_profile
from PyAitD.games.aitd1.profile import AITD1
from PyAitD.games.base import GameProfile


def test_aitd1_profile_is_registered():
    assert load_profile("aitd1") is AITD1
    assert PROFILES == {"aitd1": AITD1}
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
    assert AITD1.dead_opcodes == frozenset({27, 57, 61, 69})
    assert all(callable(h) for h in AITD1.opcode_table)
    assert not any(h.__qualname__.startswith("_op_not_implemented") for h in AITD1.opcode_table)
    assert dataclasses.is_dataclass(GameProfile) and GameProfile.__dataclass_params__.frozen
    with pytest.raises(dataclasses.FrozenInstanceError):
        AITD1.name = "x"


def test_aitd1_debug_venues_and_reduced_dispatch():
    from PyAitD.games.aitd1 import life_reduced, scenario
    assert AITD1.reduced_dispatch is life_reduced.reduced_dispatch
    assert AITD1.debug_venues == {
        "combat-venue": scenario.enter_combat_venue,
        "mouse-combat-fixture": scenario.enter_mouse_combat_fixture,
    }
