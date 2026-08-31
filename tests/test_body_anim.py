# SPDX-License-Identifier: GPL-2.0-only
import pytest

from PyAitD.engine.data.formats import parse_anim, parse_body
from PyAitD.engine.data.pak import Pak

pytestmark = pytest.mark.engine


def _read(pak_name, index, data_dir):
    return Pak(data_dir / pak_name).read(index)


def test_body0_golden(data_dir):
    body = parse_body(_read("LISTBODY.PAK", 0, data_dir))
    assert body.flags == 0x1
    assert body.zv == (-630, 630, -900, 0, -360, 360)
    assert body.scratch == ()
    assert len(body.vertices) == 65
    assert len(body.groups) == 0
    assert len(body.primitives) == 35


def test_body1_golden(data_dir):
    body = parse_body(_read("LISTBODY.PAK", 1, data_dir))
    assert body.flags == 0x3
    assert body.zv == (-630, 630, -1441, 0, -360, 540)
    assert len(body.scratch) == 10
    assert len(body.vertices) == 67
    assert len(body.groups) == 2
    assert len(body.group_order) == 2
    assert len(body.primitives) == 47


def test_body12_player_default(data_dir):
    body = parse_body(_read("LISTBODY.PAK", 12, data_dir))
    assert body.flags & 0x2  # INFO_ANIM
    assert len(body.vertices) == 150
    assert len(body.groups) == 17
    assert len(body.primitives) == 222
    # stored *6 -> parser yields real vertex index
    for prim in body.primitives:
        assert all(0 <= p < len(body.vertices) for p in prim.points)


def test_anim_golden(data_dir):
    anim0 = parse_anim(_read("LISTANIM.PAK", 0, data_dir))
    assert anim0.num_frames == 2
    assert anim0.num_groups == 2
    assert anim0.frames[0].timestamp == 5
    assert anim0.frames[0].anim_step == (0, 0, 0)

    anim2 = parse_anim(_read("LISTANIM.PAK", 2, data_dir))
    assert anim2.num_frames == 2
    assert anim2.num_groups == 17
    assert anim2.frames[0].timestamp == 30
    assert anim2.frames[0].anim_step == (0, 0, -129)


def test_parse_anim_rejects_bad_size():
    with pytest.raises(ValueError):
        parse_anim(b"\x00" * 3)
