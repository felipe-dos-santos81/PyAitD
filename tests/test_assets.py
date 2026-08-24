# SPDX-License-Identifier: GPL-2.0-only
from hashlib import sha256

import pytest

from PyAitD.assets import Assets
from PyAitD.floor import load_entry


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
