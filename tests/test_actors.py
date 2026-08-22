# SPDX-License-Identifier: GPL-2.0-only
from maitd.actors import actor_zv, check_hard_col, cube_intersect, gere_collision, spawn_player
from maitd.assets import Assets


def test_spawn_player(data_dir):
    assets = Assets(data_dir)
    floor = None  # Floor(data_dir, 0) — import if needed
    from maitd.floor import Floor
    actor = spawn_player(assets, Floor(data_dir, 0))
    assert (actor.x, actor.y, actor.z) == (-3642, 0, 1977)
    assert actor.beta == 0
    assert actor.body_idx == 12
    assert actor.anim_idx == 2


def test_actor_zv(data_dir):
    from maitd.floor import Floor
    assets = Assets(data_dir)
    actor = spawn_player(assets, Floor(data_dir, 0))
    zv = actor_zv(actor, assets.body(12))
    assert len(zv) == 6
    assert zv[0] <= zv[1] and zv[4] <= zv[5]


def test_cube_intersect():
    a = (0, 10, 0, 10, 0, 10)
    assert cube_intersect(a, (5, 15, 5, 15, 5, 15))
    assert not cube_intersect(a, (11, 20, 5, 15, 5, 15))


def test_check_hard_col():
    from maitd.formats import Zone
    cols = [Zone(0, 10, 0, 100, 0, 10, 0, 0), Zone(50, 60, 0, 100, 0, 10, 0, 0)]
    assert len(check_hard_col((0, 10, 0, 10, 0, 10), cols)) == 1


def test_gere_collision_side_push():
    # old box left of wall; step pushes right into it -> x blocked, z kept
    old = (0, 20, 0, 20, 0, 20)
    animated = (10, 30, 0, 20, 0, 20)
    wall = (30, 40, 0, 100, 0, 40)
    sx, sz = gere_collision(old, animated, wall, 10, 10)
    assert sx == 0 and sz == 10  # step preserved on z, cancelled on x
