# SPDX-License-Identifier: GPL-2.0-only
import pytest

from maitd.formats import Body, Group, Primitive
from maitd.skel import skin
from maitd.world import CameraState


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
