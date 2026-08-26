# SPDX-License-Identifier: GPL-2.0-only
import pytest

from PyAitD.engine.assets import Assets
from PyAitD.games.aitd1.profile import AITD1

pytestmark = pytest.mark.engine


def test_counts(data_dir):
    assets = Assets(data_dir, AITD1)
    assert assets.num_lifes == 563
    assert assets.num_tracks == 45


def test_fetch(data_dir):
    assets = Assets(data_dir, AITD1)
    assert len(assets.life(0)) > 0
    assert assets.life(0) == assets.life(0)
    assert len(assets.track(0)) > 0


def test_out_of_range(data_dir):
    assets = Assets(data_dir, AITD1)
    with pytest.raises(KeyError):
        assets.life(9999)
    with pytest.raises(KeyError):
        assets.track(9999)
