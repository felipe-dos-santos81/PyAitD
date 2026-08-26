# SPDX-License-Identifier: GPL-2.0-only
import pathlib

from PyAitD.engine.formats import parse_defines, parse_objets, parse_priority, parse_vars


def test_objets_golden(data_dir):
    raw = (pathlib.Path(data_dir) / "OBJETS.ITD").read_bytes()
    assert len(raw) == 15186
    objs = parse_objets(raw)
    assert len(objs) == 292
    o = objs[0]
    assert (o.obj_index, o.body, o.type_zv, o.found_body, o.found_name) == (-1, 0, 3, -1, -1)
    assert (o.found_flag, o.found_life) == (0, -1)
    assert (o.x, o.y, o.z) == (-5513, 0, -395)
    assert (o.stage, o.room, o.life_mode, o.life, o.anim) == (0, 0, 1, 0, -1)
    assert (o.track_mode, o.track_number, o.position_in_track) == (0, -1, 20)
    assert o.flags & 0x20  # loader ORs 0x20 into every record


def test_vars_golden(data_dir):
    raw = (pathlib.Path(data_dir) / "VARS.ITD").read_bytes()
    assert len(raw) == 414
    vars_ = parse_vars(raw)
    assert len(vars_) == 207


def test_defines_golden(data_dir):
    raw = (pathlib.Path(data_dir) / "DEFINES.ITD").read_bytes()
    assert len(raw) == 90
    cvars = parse_defines(raw, big_endian=True)
    assert len(cvars) == 45
    assert cvars[:9] == [49, 270, 700, 18, 6, 19, 20, 1, 0]
    assert cvars[7] == 1   # WORLD_NUM_PERSO
    assert cvars[8] == 0   # CHOOSE_PERSO


def test_priority_golden(data_dir):
    raw = (pathlib.Path(data_dir) / "PRIORITY.ITD").read_bytes()
    assert len(raw) == 101
    assert len(parse_priority(raw)) == 50
