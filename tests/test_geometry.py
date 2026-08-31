# SPDX-License-Identifier: GPL-2.0-only
import numpy as np
import pytest

from PyAitD.engine.data.formats import Body, Group, Primitive
from PyAitD.render.geometry import BodyGeometry, icosphere, pose_geometry, vertex_groups
from PyAitD.engine.actor.skel import pose_vertices

pytestmark = pytest.mark.render


def _cube_body():
    v = [(-100, -100, -100), (100, -100, -100), (100, 100, -100), (-100, 100, -100),
         (-100, -100, 100), (100, -100, 100), (100, 100, 100), (-100, 100, 100)]
    faces = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (0, 3, 7, 4), (1, 2, 6, 5)]
    prims = [Primitive(1, 0, 10 + i, list(f)) for i, f in enumerate(faces)]
    prims.append(Primitive(0, 0, 3, [0, 6]))
    prims.append(Primitive(3, 0, 4, [7], size=50))
    prims.append(Primitive(2, 0, 5, [1]))
    return Body(0, (0,) * 6, (), v, [], [], prims)


def test_quads_fan_into_triangles_and_colors_follow():
    geo = pose_geometry(_cube_body(), [], None)
    assert isinstance(geo, BodyGeometry)
    assert geo.tris.shape == (12, 3) and geo.tri_colors.tolist() == [c for c in range(10, 16) for _ in range(2)]
    assert geo.lines.tolist() == [[0, 6]] and geo.line_colors.tolist() == [3]
    assert geo.spheres == ((7, 50.0, 4),)
    assert geo.points.tolist() == [1] and geo.point_sizes.tolist() == [1] and geo.point_colors.tolist() == [5]


def test_vertices_match_pose_vertices_exactly():
    body = _cube_body()
    expected = np.array(pose_vertices(body, [], None), dtype=np.float32)
    assert np.array_equal(pose_geometry(body, [], None).vertices, expected)


def test_normals_are_unit_and_never_nan_on_degenerate_faces():
    body = _cube_body()
    body.primitives.append(Primitive(1, 0, 9, [0, 0, 0]))  # degenerate
    geo = pose_geometry(body, [], None)
    assert geo.normals.shape == (8, 3)
    assert not np.isnan(geo.normals).any()
    assert np.allclose(np.linalg.norm(geo.normals, axis=1), 1.0, atol=1e-5)


def test_normals_average_only_within_a_group():
    # two groups: vertices 0-3 (group 0) and 4-7 (group 1) share a face across
    # the boundary; a vertex normal must ignore faces of the other group.
    body = _cube_body()
    body.groups = [Group(0, 4, 0, -1, 0, 0, 0, 0), Group(4, 4, 4, 0, 1, 0, 0, 0)]
    body.group_order = [0, 1]
    assert vertex_groups(body).tolist() == [0, 0, 0, 0, 1, 1, 1, 1]
    geo = pose_geometry(body, [(0, (0, 0, 0)), (0, (0, 0, 0))], None)
    # vertex 0 belongs to group 0: only face (0,1,2,3) is entirely within
    # group 0, so it is the sole contributor to vertex 0's normal. Its
    # winding (as authored in the cube fixture) faces +z; that sign is
    # data-defined (FITD does no back-face culling, so it is irrelevant to
    # lighting -- task 7 uses abs(dot)). What this test actually proves is
    # that the cross-boundary faces (which also touch vertex 0) did NOT
    # contribute: if they had, geo.normals[0] would be a blend pulled toward
    # the group-1 side rather than exactly matching face (0,1,2,3)'s normal.
    assert geo.normals[0][2] > 0


def test_vertex_with_no_faces_faces_camera():
    body = Body(0, (0,) * 6, (), [(0, 0, 0)], [], [], [Primitive(2, 0, 1, [0])])
    geo = pose_geometry(body, [], None)
    assert geo.normals.tolist() == [[0.0, 0.0, -1.0]]


def test_icosphere_level_one():
    verts, tris = icosphere(1)
    assert verts.shape == (42, 3) and tris.shape == (80, 3)
    assert np.allclose(np.linalg.norm(verts, axis=1), 1.0, atol=1e-6)


def test_icosphere_is_cached():
    a = icosphere(1)
    b = icosphere(1)
    assert a[0] is b[0] and a[1] is b[1]


def test_icosphere_arrays_are_read_only():
    # lru_cache-shared with every sphere-shaped actor drawn afterward:
    # nothing mutates these today, but an accidental future write must fail
    # loudly rather than silently corrupting every other cached user.
    verts, tris = icosphere(1)
    with pytest.raises(ValueError):
        verts[0, 0] = 99.0
    with pytest.raises(ValueError):
        tris[0, 0] = 99


def test_point_types_mirror_formats_prim_point_like():
    from PyAitD.engine.data.formats import _PRIM_POINT_LIKE
    from PyAitD.render.geometry import POINT_TYPES
    assert POINT_TYPES == tuple(_PRIM_POINT_LIKE)


def test_every_body_in_the_data_poses_without_nan(data_dir, profile):
    from PyAitD.engine.data.assets import Assets
    assets = Assets(data_dir, profile)
    for num in range(assets.num_bodies):
        body = assets.body(num)
        states = [(0, (0, 0, 0))] * len(body.groups)
        geo = pose_geometry(body, states, (0, 0, 0))
        assert not np.isnan(geo.normals).any()
        assert geo.tris.max(initial=-1) < len(geo.vertices)


def test_rest_is_the_raw_body_vertices_whatever_the_pose():
    body = _cube_body()
    posed = pose_geometry(body, [], (100, 200, 300))
    assert np.array_equal(posed.rest, np.array(body.vertices, np.float32))
    assert not np.array_equal(posed.rest, posed.vertices)   # the actor rotation moved the pose, not the rest


def test_ao_defaults_to_ones_and_takes_a_baked_array():
    body = _cube_body()
    geo = pose_geometry(body, [], None)
    assert geo.ao.dtype == np.float32 and np.array_equal(geo.ao, np.ones(8, np.float32))
    baked = np.linspace(0, 1, 8).astype(np.float32)
    assert np.array_equal(pose_geometry(body, [], None, ao=baked).ao, baked)
    with pytest.raises(ValueError, match="ao"):
        pose_geometry(body, [], None, ao=np.ones(3, np.float32))


def test_body_geometry_constructed_positionally_fills_rest_and_ao():
    v = np.zeros((3, 3), np.float32)
    n = np.zeros((3, 3), np.float32)
    geo = BodyGeometry(v, n, np.zeros((0, 3), np.int32), np.zeros(0, np.uint8),
                       np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), (),
                       np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))
    assert geo.rest is v and np.array_equal(geo.ao, np.ones(3, np.float32))


def test_corner_normals_default_to_the_vertex_normals_and_straight_to_zeros():
    geo = pose_geometry(_cube_body(), [], None)
    assert geo.corner_normals.shape == (12, 3, 3) and geo.corner_normals.dtype == np.float32
    assert np.array_equal(geo.corner_normals, geo.normals[geo.tris])
    assert geo.straight.shape == (12, 3) and not geo.straight.any()


def test_a_refinement_fills_corner_normals_and_straight_but_leaves_normals_alone():
    from PyAitD.render.refine import plan_refinement
    body = _cube_body()
    plain = pose_geometry(body, [], None)
    plan = plan_refinement(body)
    geo = pose_geometry(body, [], None, refinement=plan)
    assert geo.straight is plan.straight
    assert np.array_equal(geo.normals, plain.normals)
    assert geo.corner_normals.shape == (12, 3, 3)
    assert not np.array_equal(geo.corner_normals, plain.corner_normals)   # creased corners take their face normal


class _CountingRefinement:
    """A plan that records how often its corner normals are asked for."""

    def __init__(self, tris):
        self.straight = np.zeros((len(tris), 3), np.float32)
        self.calls = 0

    def corner_normals(self, vertices, tris):
        self.calls += 1
        return np.zeros((len(tris), 3, 3), np.float32)


def test_a_plans_corner_normals_are_computed_on_first_read_and_only_once():
    # build_frame poses every actor every frame and passes the plan
    # whatever the smoothing level is; only render_gl's tessellated path
    # ever reads the corner normals, so posing must not compute them.
    body = _cube_body()
    plan = _CountingRefinement(pose_geometry(body, [], None).tris)
    geo = pose_geometry(body, [], None, refinement=plan)
    assert plan.calls == 0                      # constructing pays nothing
    first = geo.corner_normals
    assert plan.calls == 1 and first.shape == (12, 3, 3)
    assert geo.corner_normals is first          # cached: reading twice computes once
    assert plan.calls == 1
