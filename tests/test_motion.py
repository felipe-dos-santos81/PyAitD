# SPDX-License-Identifier: GPL-2.0-only
"""render/motion.py: inter-tick blending — pure math, no pygame, no GL."""
import pytest

pytestmark = pytest.mark.render


def test_blend_angle_endpoints_and_lerp():
    from PyAitD.render.motion import blend_angle
    assert blend_angle(100.0, 200.0, 0.0) == pytest.approx(100.0)
    assert blend_angle(100.0, 200.0, 1.0) == pytest.approx(200.0)
    assert blend_angle(100.0, 200.0, 0.5) == pytest.approx(150.0)


def test_blend_angle_wraps_through_the_short_arc():
    from PyAitD.render.motion import blend_angle
    # 1000 -> 20 is 44 units forward through 0, not 980 backward
    assert blend_angle(1000.0, 20.0, 0.5) == pytest.approx(1022.0)
    # 20 -> 1000 is 44 units backward through 0
    assert blend_angle(20.0, 1000.0, 0.5) == pytest.approx(1022.0)
    # exactly opposite (512 apart) is a defined, finite answer
    assert 0.0 <= blend_angle(0.0, 512.0, 0.5) < 1024.0


def test_blend_states_by_group_type():
    from PyAitD.render.motion import blend_states
    prev = ((0, (0.0, 1000.0, 0.0)), (1, (10.0, 0.0, 0.0)))
    cur = ((0, (0.0, 20.0, 0.0)), (1, (30.0, 0.0, 0.0)))
    out = blend_states(prev, cur, 0.5)
    assert out[0][0] == 0 and out[0][1][1] == pytest.approx(1022.0)  # rotation: short arc
    assert out[1][0] == 1 and out[1][1][0] == pytest.approx(20.0)    # translate: plain lerp


def test_blend_states_gtype_mismatch_takes_cur_verbatim():
    from PyAitD.render.motion import blend_states
    prev = ((0, (0.0, 1000.0, 0.0)),)
    cur = ((1, (30.0, 0.0, 0.0)),)
    assert blend_states(prev, cur, 0.5) == ((1, (30.0, 0.0, 0.0)),)


def _actor_motion(**overrides):
    from PyAitD.render.motion import ActorMotion
    fields = dict(body_num=1, room=0, anim=2,
                  position=(0.0, 0.0, 0.0), angles=(0.0, 100.0, 0.0),
                  states=((0, (0.0, 0.0, 0.0)),))
    fields.update(overrides)
    return ActorMotion(**fields)


def test_blend_actor_blends_a_matching_actor():
    from PyAitD.render.motion import blend_actor, pose_vertices_float
    prev = _actor_motion()
    states, angles, position, pose_fn = blend_actor(
        prev, 1, 0, 2, ((0, (0, 64, 0)),), (0, 200, 0), (100.0, 0.0, 0.0), 0.5)
    assert angles[1] == pytest.approx(150.0)
    assert position[0] == pytest.approx(50.0)
    assert states[0][1][1] == pytest.approx(32.0)
    assert pose_fn is pose_vertices_float


def test_blend_actor_snaps_on_identity_change_or_teleport():
    from PyAitD.render.motion import TELEPORT_LIMIT, blend_actor
    cur = (((0, (0, 64, 0)),), (0, 200, 0), (100.0, 0.0, 0.0))
    for prev in (
        None,
        _actor_motion(body_num=9),
        _actor_motion(room=5),
        _actor_motion(anim=7),
        _actor_motion(position=(100.0 + TELEPORT_LIMIT + 1, 0.0, 0.0)),
    ):
        states, angles, position, pose_fn = blend_actor(prev, 1, 0, 2, *cur, 0.5)
        assert (states, angles, position) == cur
        assert pose_fn is None


def test_blend_actor_state_length_mismatch_blends_pose_but_not_states():
    from PyAitD.render.motion import blend_actor
    prev = _actor_motion(states=())   # snapshot saw no AnimPlayer (static body)
    states, angles, position, pose_fn = blend_actor(
        prev, 1, 0, 2, ((0, (0, 64, 0)),), (0, 200, 0), (100.0, 0.0, 0.0), 0.5)
    assert states == ((0, (0, 64, 0)),)        # cur states verbatim
    assert angles[1] == pytest.approx(150.0)   # angles still blend
    assert pose_fn is not None


def _stub_body():
    """Two vertices, one root group -- the shape stub bodies use across
    the suite (see tests/test_skel.py for the field meanings)."""
    from types import SimpleNamespace
    group = SimpleNamespace(start=0, num_vertices=2, num_group=0, org_group=-1,
                            base_vertices=0)
    return SimpleNamespace(vertices=[[0, 0, 0], [100, 0, 0]], groups=[group],
                           group_order=[0], flags=2, primitives=[])


def test_pose_vertices_float_matches_integer_pose_on_translation():
    from PyAitD.engine.actor.skel import pose_vertices
    from PyAitD.render.motion import pose_vertices_float
    body = _stub_body()
    states = [(1, (10, 20, 30))]
    integer = pose_vertices(body, states)
    floats = pose_vertices_float(body, states)
    for i in range(2):
        assert tuple(floats[i]) == pytest.approx(tuple(integer[i]))


def test_pose_vertices_float_rotation_is_exact_where_the_table_truncates():
    import math
    from PyAitD.render.motion import pose_vertices_float
    body = _stub_body()
    # 256 units = 90 degrees about y: (100, 0, 0) -> (0, 0, 100)
    floats = pose_vertices_float(body, [(0, (0, 256, 0))])
    assert tuple(floats[1]) == pytest.approx((0.0, 0.0, 100.0), abs=1e-9)
    # fractional angle (impossible on the integer path): 45 degrees
    floats = pose_vertices_float(body, [(0, (0.0, 128.0, 0.0))])
    assert floats[1][0] == pytest.approx(100 * math.cos(math.pi / 4))
    assert floats[1][2] == pytest.approx(100 * math.sin(math.pi / 4))


def test_pose_vertices_float_actor_angles_group0_and_whole_model():
    from PyAitD.engine.actor.skel import pose_vertices
    from PyAitD.render.motion import pose_vertices_float
    body = _stub_body()
    # group_order non-empty: actor angles override group 0's delta
    a = pose_vertices_float(body, [(1, (5, 5, 5))], actor_angles=(0, 256, 0))
    assert tuple(a[1]) == pytest.approx((0.0, 0.0, 100.0), abs=1e-9)
    # group_order empty: RotateNuage whole-model path
    body.group_order = []
    b = pose_vertices_float(body, [(0, (0, 0, 0))], actor_angles=(0, 256, 0))
    i = pose_vertices(body, [(0, (0, 0, 0))], actor_angles=(0, 256, 0))
    for k in range(2):
        assert tuple(b[k]) == pytest.approx(tuple(i[k]), abs=8.0)


def test_pose_vertices_float_base_vertex_inside_and_outside_span():
    """Pins both branches of the aliasing fix: a group whose base_vertices
    lies inside its own span (the root group in _stub_body), and a second
    group whose base_vertices lies outside its span -- so a later
    "simplification" back to a plain live-alias `.copy()` cannot pass
    either case."""
    from types import SimpleNamespace
    from PyAitD.engine.actor.skel import pose_vertices
    from PyAitD.render.motion import pose_vertices_float

    # Inside-span case: _stub_body's root group, base_vertices=0 inside [0,2).
    body = _stub_body()
    states = [(1, (10, 20, 30))]
    integer = pose_vertices(body, states)
    floats = pose_vertices_float(body, states)
    assert integer == [[20, 40, 60], [130, 60, 90]]
    for i in range(2):
        assert tuple(floats[i]) == pytest.approx(tuple(integer[i]))

    # Outside-span case: group 1's base_vertices=1 lies in group 0's span.
    g0 = SimpleNamespace(start=0, num_vertices=2, num_group=0, org_group=-1,
                         base_vertices=0)
    g1 = SimpleNamespace(start=2, num_vertices=3, num_group=1, org_group=0,
                         base_vertices=1)
    body2 = SimpleNamespace(
        vertices=[[0, 0, 0], [100, 0, 0], [5, 5, 5], [6, 6, 6], [7, 7, 7]],
        groups=[g0, g1], group_order=[0, 1], flags=2, primitives=[])
    states2 = [(1, (10, 20, 30)), (1, (1, 1, 1))]
    integer2 = pose_vertices(body2, states2)
    floats2 = pose_vertices_float(body2, states2)
    expected = [[20, 40, 60], [130, 60, 90], [136, 66, 96], [137, 67, 97], [138, 68, 98]]
    assert integer2 == expected
    for i in range(5):
        assert tuple(floats2[i]) == pytest.approx(tuple(integer2[i]))


@pytest.mark.parametrize("body_num", [1, 12])
def test_pose_vertices_float_parity_on_real_bodies(data_dir, profile, body_num):
    """Divergence from the integer pose is truncation-bounded, the way
    CameraView's divergence from skel.skin is (~6 world units measured)."""
    import numpy as np
    from PyAitD.engine.data.assets import Assets
    from PyAitD.engine.actor.skel import pose_vertices
    from PyAitD.render.motion import pose_vertices_float
    assets = Assets(data_dir, profile)
    body = assets.body(body_num)
    states = [(0, (0, 0, 0))] * len(body.groups)
    integer = np.array(pose_vertices(body, states, actor_angles=(0, 300, 0)), dtype=np.float64)
    floats = pose_vertices_float(body, states, actor_angles=(0, 300, 0))
    assert float(np.max(np.abs(floats - integer))) <= 16.0


def test_snapshot_reads_live_actors_and_players():
    from PyAitD.render.motion import snapshot

    class _Actor:
        def __init__(self, index_in_world, body_num, anim, room=0):
            self.index_in_world = index_in_world
            self.body_num = body_num
            self.anim = anim
            self.room = room
            self.world_x, self.world_y, self.world_z = 10, 20, 30
            self.step_x, self.step_y, self.step_z = 1, 2, 3
            self.alpha, self.beta, self.gamma = 0, 256, 0

    class _Player:
        def group_states(self):
            return [(0, (1, 2, 3))]

    class _Game:
        current_floor = 4
        num_camera = 2
        actors = [_Actor(0, 12, 5), _Actor(-1, 12, 5), _Actor(3, -1, 5), _Actor(7, 4, -1)]
        anim_players = {0: _Player()}

    snap = snapshot(_Game())
    assert snap.floor == 4 and snap.camera == 2
    assert set(snap.actors) == {0, 3}          # dead slot and body -1 skipped
    entry = snap.actors[0]
    assert entry.position == (11.0, 22.0, 33.0)
    assert entry.angles == (0.0, 256.0, 0.0)
    assert entry.states == ((0, (1.0, 2.0, 3.0)),)
    assert snap.actors[3].states == ()          # anim -1: no player consulted
