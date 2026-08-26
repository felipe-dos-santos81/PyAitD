# SPDX-License-Identifier: GPL-2.0-only
import struct

from PyAitD.engine.explode import explode, ExplodeError


def _entry_payload(data, off):
    add = struct.unpack_from("<I", data, off)[0]
    p = off + 4 + (add - 4 if add else 0)
    disc, uncomp = struct.unpack_from("<II", data, p)
    flag, info5, name_len = struct.unpack_from("<BBH", data, p + 8)
    payload = data[p + 12 + name_len : p + 12 + name_len + disc]
    return disc, uncomp, flag, info5, payload


def test_explode_etage00_rooms(data_dir):
    raw = (data_dir / "ETAGE00.PAK").read_bytes()
    disc, uncomp, flag, info5, payload = _entry_payload(raw, 12)
    assert (disc, uncomp, flag, info5) == (380, 594, 1, 0)
    out = explode(payload, uncomp, info5)
    assert len(out) == 594
    assert out[:32].hex() == "080000000c008700160028020000000000000500000001000200030004002100"


def test_explode_etage00_cameras(data_dir):
    raw = (data_dir / "ETAGE00.PAK").read_bytes()
    disc, uncomp, flag, info5, payload = _entry_payload(raw, 424)
    assert (uncomp, flag) == (3072, 1)
    out = explode(payload, uncomp, info5)
    assert len(out) == 3072
    assert struct.unpack_from("<I", out, 0)[0] == 24  # camera offset table end


def test_explode_rejects_truncated_tree():
    import pytest
    with pytest.raises(ExplodeError):
        explode(b"\x00", 64, 0)
