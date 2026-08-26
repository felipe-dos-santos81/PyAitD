# SPDX-License-Identifier: GPL-2.0-only
from hashlib import sha256

import pytest

from PyAitD.engine.assets import Assets
from PyAitD.engine.floor import load_entry


def test_loads(data_dir):
    assets = Assets(data_dir)
    assert assets.num_bodies == 272
    assert assets.num_anims == 305


def test_body_anim_content(data_dir):
    assets = Assets(data_dir)
    body = assets.body(12)
    assert len(body.vertices) == 150
    anim = assets.anim(2)
    assert anim.num_frames == 2


def test_out_of_range(data_dir):
    assets = Assets(data_dir)
    with pytest.raises(KeyError):
        assets.body(9999)
    with pytest.raises(KeyError):
        assets.anim(9999)


def test_parse_cache(data_dir):
    assets = Assets(data_dir)
    first = assets.body(12)
    second = assets.body(12)
    assert first is second  # parsed once, cached object


@pytest.mark.parametrize(
    ("hero", "body_name", "anim_name", "body_hash", "anim_hash", "vertices", "groups"),
    (
        (0, "LISTBODY", "LISTANIM",
         "6bc39ca43fa8660bf1a09801168d350245873bb698523df3299b0b6727fdc1cd",
         "9ab655b4e211ce3f8b973344d7386b56fc8538b0390dc501ce2234994f9e682c",
         150, 20),
        (1, "LISTBOD2", "LISTANI2",
         "bcdb6d5f4a3bb8449100af2768fa0fe518fcbc65da5b28cecf528d48438c1c0c",
         "a4605893cac129ab9c8715cf5adcec83bb1a8004e02d50096a02f982b2899e56",
         164, 18),
    ),
)
def test_hero_archives_and_representative_content(
    data_dir, hero, body_name, anim_name, body_hash, anim_hash, vertices, groups,
):
    assets = Assets(data_dir, hero=hero)
    assert (assets.body_archive_name, assets.anim_archive_name) == (body_name, anim_name)
    assert (assets.num_bodies, assets.num_anims) == (272, 305)
    assert len(assets.body(12).vertices) == vertices
    assert assets.anim(4).num_groups == groups
    assert sha256(load_entry(assets._bodies_pak, 12)).hexdigest() == body_hash
    assert sha256(load_entry(assets._anims_pak, 4)).hexdigest() == anim_hash


@pytest.mark.parametrize(
    ("index", "shape", "digest"),
    (
        (0, (20, 20, 3), "cbb42c0d68cd9be12cb0b35885c27e93b5aa6df599a9864688d92c721fe5bc45"),
        (1, (20, 20, 3), "1dfb52dee2a7edff7a3245a685226a64de764ae2f5ef187a0a13163f23f1f59c"),
        (2, (20, 20, 3), "117532107f0fc661324cb25f3f6b65debbc134a3fd1577fd80a2c30c6e47aa77"),
        (3, (20, 20, 3), "1685163a31472bb8552df364e0a81e018f4b8ad32b48f9089a2b25a8c3b7fe50"),
        (4, (8, 20, 3), "130aafa9f4583e25a0718590f2978c171fcb03f4762f4bbf7afb87d1e6feb99c"),
        (5, (8, 20, 3), "756891ee5f09119cd5ed2e401a39acef10d9f9b98cbde882af20170d0a8409f0"),
        (6, (20, 8, 3), "a78732fcdebb80bbd1407ce1923e23b89edbaec030e2d48b1f6796eef16d86fb"),
        (7, (20, 8, 3), "cf23f9480178db0042889850345b65f4f585de67244b3b9758a2197ebe707b3c"),
        (8, (8, 44, 3), "aacf9f1337451f8eb9a613726718a2f2e5121617ef4fddfd1b904de8206109fa"),
    ),
)
def test_cadre_bank_real_data(data_dir, index, shape, digest):
    sprite = Assets(data_dir).cadre_bank()[index]
    assert sprite.shape == shape
    assert sha256(sprite.tobytes()).hexdigest() == digest


def _cadre_raw(bad_index, bad_offset, payload=b""):
    # nine-entry u16 LE offset table; sprites before bad_index point at a
    # valid 1x1 sprite (4-byte prefix + width + height + 1 pixel) at offset 18
    sprite = (1).to_bytes(4, "little") + (1).to_bytes(2, "little") * 2 + b"\x00"
    offsets = bytearray(18)
    for i in range(bad_index):
        offsets[i * 2:i * 2 + 2] = (18).to_bytes(2, "little")
    offsets[bad_index * 2:bad_index * 2 + 2] = bad_offset.to_bytes(2, "little")
    return bytes(offsets) + sprite + payload


@pytest.mark.parametrize(
    ("raw", "bad_index"),
    (
        (b"\x00" * 10, None),  # short offset table
        (_cadre_raw(3, 0x7FFF), "3"),  # out-of-range offset
        (_cadre_raw(1, 21), "1"),  # truncated dimensions (offset 21: dims at 25, 27-byte raw)
        (_cadre_raw(4, 27, b"\x00" * 4 + (20).to_bytes(2, "little") * 2 + b"\x00" * 8), "4"),
        # truncated pixel block: sprite 4 declares 20x20 but only 8 pixels follow
    ),
)
def test_cadre_bank_malformed(data_dir, monkeypatch, raw, bad_index):
    assets = Assets(data_dir)
    monkeypatch.setattr("PyAitD.engine.assets.load_entry", lambda pak, entry: raw)
    with pytest.raises(ValueError) as excinfo:
        assets.cadre_bank()
    message = str(excinfo.value)
    assert "ITD_RESS.PAK" in message
    assert "entry 4" in message
    if bad_index is not None:
        assert f"sprite {bad_index}" in message
