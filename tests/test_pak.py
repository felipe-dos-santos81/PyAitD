# SPDX-License-Identifier: GPL-2.0-only
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
