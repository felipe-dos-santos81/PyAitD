# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.engine.actor.actors import check_hard_col, cube_intersect, gere_collision
import pytest

pytestmark = pytest.mark.engine


def test_cube_intersect():
    a = (0, 10, 0, 10, 0, 10)
    assert cube_intersect(a, (5, 15, 5, 15, 5, 15))
    assert not cube_intersect(a, (11, 20, 5, 15, 5, 15))


def test_check_hard_col():
    from PyAitD.engine.data.formats import Zone
    cols = [Zone(0, 10, 0, 100, 0, 10, 0, 0), Zone(50, 60, 0, 100, 0, 10, 0, 0)]
    assert len(check_hard_col((0, 10, 0, 10, 0, 10), cols)) == 1


def test_gere_collision_side_push():
    # old box left of wall; step pushes right into it -> x blocked, z kept
    old = (0, 20, 0, 20, 0, 20)
    animated = (10, 30, 0, 20, 0, 20)
    wall = (30, 40, 0, 100, 0, 40)
    sx, sz = gere_collision(old, animated, wall, 10, 10)
    assert sx == 0 and sz == 10  # step preserved on z, cancelled on x
