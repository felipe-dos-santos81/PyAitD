# SPDX-License-Identifier: GPL-2.0-only
import pytest

from PyAitD.assets import Assets


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
