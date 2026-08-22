# SPDX-License-Identifier: GPL-2.0-only
import struct

import pytest

from maitd.pak import Pak, PakError, find_pak


def test_entry_counts(data_dir):
    assert Pak(data_dir / "ETAGE00.PAK").count == 2
    assert Pak(data_dir / "CAMERA00.PAK").count == 5
    assert Pak(data_dir / "ITD_RESS.PAK").count == 20


def test_etage00_entry_info(data_dir):
    pak = Pak(data_dir / "ETAGE00.PAK")
    info = pak.info(0)
    assert (info.disc_size, info.uncompressed_size, info.flag, info.info5) == (380, 594, 1, 0)
    assert pak.info(1).uncompressed_size == 3072


def test_read_uncompressed_size_matches_header(data_dir):
    pak = Pak(data_dir / "CAMERA00.PAK")
    for i in range(pak.count):
        data = pak.read(i)
        assert len(data) == 64000


def test_out_of_range_raises(data_dir):
    pak = Pak(data_dir / "ETAGE00.PAK")
    with pytest.raises(PakError):
        pak.read(2)


def test_missing_file_raises(tmp_path):
    with pytest.raises(PakError):
        Pak(tmp_path / "NOPE.PAK")


def test_find_pak(data_dir):
    assert find_pak(data_dir, "ETAGE00").name == "ETAGE00.PAK"
    with pytest.raises(PakError):
        find_pak(data_dir, "NOPE")


def test_truncated_offset_table_raises(tmp_path):
    path = tmp_path / "BAD.PAK"
    path.write_bytes(struct.pack("<II", 0, 12))
    with pytest.raises(PakError, match="BAD\\.PAK"):
        Pak(path)


def test_entry_offset_past_eof_raises(tmp_path):
    path = tmp_path / "BAD.PAK"
    path.write_bytes(
        struct.pack("<II", 0, 12)
        + struct.pack("<I", 999999)
        + struct.pack("<III", 4, 1, 1)
        + struct.pack("<BBH", 0, 0, 0)
        + b"A"
    )
    pak = Pak(path)
    assert pak.read(0) == b"A"
    with pytest.raises(PakError, match="entry 1"):
        pak.read(1)


def test_bad_deflate_payload_raises(tmp_path):
    path = tmp_path / "BAD.PAK"
    path.write_bytes(
        struct.pack("<II", 0, 8)
        + struct.pack("<III", 4, 4, 4)
        + struct.pack("<BBH", 4, 0, 0)
        + b"NOTZ"
    )
    with pytest.raises(PakError, match="entry 0"):
        Pak(path).read(0)
