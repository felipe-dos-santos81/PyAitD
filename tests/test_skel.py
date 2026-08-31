# SPDX-License-Identifier: GPL-2.0-only
import pytest

from PyAitD.engine.data.formats import Body, Group, Primitive
from PyAitD.engine.script.game import init_game
from PyAitD.engine.actor.skel import hot_point, pose_vertices, skin
from PyAitD.engine.space.world import CameraState

pytestmark = pytest.mark.engine


def _cube_body():
    return Body(
        flags=0,
        zv=(0, 0, 0, 0, 0, 0),
        scratch=(),
        vertices=[(0, 0, 0), (100, 0, 0), (100, 100, 0), (0, 100, 0)],
        groups=[],
        group_order=[],
        primitives=[Primitive(1, 0, 42, [0, 1, 2, 3])],
    )


def test_static_prim_projects():
    cam = CameraState(0, 0, 0, 0, 0, 0, 300, 100, 100).angles()
    result = skin(_cube_body(), [], (0, 0, 300), cam)
    assert len(result.primitives) == 1
    prim = result.primitives[0]
    assert prim.color == 42
    # point 0 at camera center-ish: world (0,0,300) - cam (0,0,0) => Z=300 -> depth 600
    px, py, depth = prim.points[0]
    assert px == 160.0 and py == 100.0
    assert depth == 600


def test_depth_cull():
    cam = CameraState(0, 0, 0, 0, 0, 0, 300, 100, 100).angles()
    # Z = -290 => depth 10 <= 50 -> sentinel -> culled
    result = skin(_cube_body(), [], (0, 0, -290), cam)
    assert result.primitives == []


def test_actor_rotation_rotates_static_body_as_one_model():
    cam = CameraState(0, 0, 0, 0, 0, 0, 300, 100, 100).angles()

    result = skin(
        _cube_body(),
        [],
        (0, 0, 300),
        cam,
        actor_angles=(0, 0x100, 0),
    )

    assert result.points[1] == pytest.approx((160.0, 100.0, 698.0))


def test_translate_group():
    # base vertex OUTSIDE the group (real-body layout: base is the parent's origin)
    body = Body(
        flags=2,
        zv=(0, 0, 0, 0, 0, 0),
        scratch=(0,),
        vertices=[(0, 0, 0), (10, 0, 0), (5, 0, 0)],
        groups=[Group(0, 2, 2, 0, 0, 0, 0, 0)],
        group_order=[0],
        primitives=[Primitive(1, 0, 1, [0, 1])],
    )
    cam = CameraState(0, 0, 0, 0, 0, 0, 300, 100, 100).angles()
    states = [(1, (50, 0, 0))]
    result = skin(body, states, (0, 0, 300), cam)
    # verts after translate: (50,0,0),(60,0,0); +base(5,0,0) -> (55,0,0),(65,0,0)
    x0 = result.points[0][0]
    assert x0 == 160.0 + (55 * 100) / 600  # 169.166...


def test_actor_rotation_uses_group_zero_not_first_group_in_order():
    body = Body(
        flags=2,
        zv=(0, 0, 0, 0, 0, 0),
        scratch=(),
        vertices=[(100, 0, 0), (0, 0, 100), (0, 0, 0), (0, 0, 0)],
        groups=[
            Group(0, 1, 2, 0xFF, 0, 0, 0, 0),
            Group(1, 1, 3, 0xFF, 1, 0, 0, 0),
        ],
        group_order=[1, 0],
        primitives=[Primitive(1, 0, 1, [0, 1])],
    )
    cam = CameraState(0, 0, 0, 0, 0, 0, 300, 100, 100).angles()

    result = skin(
        body,
        [(0, (0, 0, 0)), (0, (0, 0, 0))],
        (0, 0, 300),
        cam,
        actor_angles=(0, 0x100, 0),
    )

    assert result.points[0] == pytest.approx((160.0, 100.0, 698.0))
    assert result.points[1] == pytest.approx((160.0, 100.0, 700.0))


def test_hot_point_is_the_shared_posed_base_vertex():
    body = Body(
        flags=2, zv=(0, 0, 0, 0, 0, 0), scratch=(),
        vertices=[(100, 0, 0), (0, 0, 0)],
        groups=[Group(0, 1, 1, 0xFF, 0, 0, 0, 0)], group_order=[0],
        primitives=[],
    )
    states = [(0, (0, 0x100, 0))]
    posed = pose_vertices(body, states, actor_angles=(0, 0x100, 0))
    assert hot_point(body, states, (0, 0x100, 0), 0) == tuple(posed[1])


def test_real_combat_bodies_share_the_named_base_vertex(data_dir, profile):
    game = init_game(data_dir, profile)
    for body_num in (234, game.actors[game.current_camera_target_actor].body_num):
        body = game.assets.body(body_num)
        states = [(0, (0x20, 0x40, 0x10)) for _ in body.groups]
        posed = pose_vertices(body, states, actor_angles=(0x10, 0x80, 0x20))
        assert hot_point(body, states, (0x10, 0x80, 0x20), 0) == tuple(
            posed[body.groups[0].base_vertices]
        )


def test_hot_point_zero_and_bad_group_contracts(data_dir, profile):
    plain = _cube_body()
    assert hot_point(plain, [], (0, 0, 0), 0) == (0, 0, 0)
    # A group the body does not have reads as no hot point rather than
    # raising: real AITD1 scripts ask for one (the saber's LIFE 49 arms group
    # 18 on the hero's 17-group body 12), and getHotPoint indexes the array
    # unchecked, so the original reads past it and swings on.
    body = init_game(data_dir, profile).assets.body(234)
    states = [(0, (0, 0, 0))] * len(body.groups)
    assert hot_point(body, states, (0, 0, 0), len(body.groups)) == (0, 0, 0)
    assert hot_point(body, states, (0, 0, 0), -1) == (0, 0, 0)
