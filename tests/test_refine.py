# SPDX-License-Identifier: GPL-2.0-only
import math

import numpy as np
import pytest

from PyAitD.engine.formats import Body, Primitive
from PyAitD.render.geometry import _CAMERA_FACING, pose_geometry
from PyAitD.render.refine import (
    CREASE_DEG, Refinement, corner_normals, evaluate, parse_crease, plan_refinement, subpatch,
)

pytestmark = pytest.mark.render


def _body(vertices, polys):
    return Body(0, (0,) * 6, (), [tuple(int(c) for c in v) for v in vertices], [], [],
                [Primitive(1, 0, 1, list(p)) for p in polys])


def _cube_body():
    v = [(-100, -100, -100), (100, -100, -100), (100, 100, -100), (-100, 100, -100),
         (-100, -100, 100), (100, -100, 100), (100, 100, 100), (-100, 100, 100)]
    faces = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (0, 3, 7, 4), (1, 2, 6, 5)]
    return _body(v, faces)


def _hex_prism_body(radius=200.0, half_height=150.0, caps=True):
    """A hexagonal prism around the y axis, faces square-on to +-x. Side
    edges meet at 60 degrees, the cap rims at 90."""
    ring = [(round(radius * math.cos(math.radians(30 + 60 * k))), round(radius * math.sin(math.radians(30 + 60 * k))))
            for k in range(6)]
    v = [(x, -half_height, z) for x, z in ring] + [(x, half_height, z) for x, z in ring]
    polys = [(k, (k + 1) % 6, 6 + (k + 1) % 6, 6 + k) for k in range(6)]
    if caps:
        polys += [(0, 1, 2, 3, 4, 5), (6, 7, 8, 9, 10, 11)]
    return _body(v, polys)


def _rest(body):
    return pose_geometry(body, [], None)


def test_a_flipped_face_is_oriented_against_its_neighbour():
    # two triangles sharing edge 1-2; the second walks it in the same
    # direction, i.e. it is wound the other way
    body = _body([(0, 0, 0), (100, 0, 0), (0, 100, 0), (100, 100, 0)], [(0, 1, 2), (1, 2, 3)])
    plan = plan_refinement(body)
    assert plan.orientation.tolist() == [1.0, -1.0] or plan.orientation.tolist() == [-1.0, 1.0]
    geo = _rest(body)
    normals = corner_normals(geo.vertices, geo.tris, plan)
    assert np.allclose(normals[0], normals[1])            # one flat sheet, one normal everywhere
    assert np.allclose(np.abs(normals[0, 0]), [0, 0, 1])


def test_a_three_face_edge_is_a_crease_and_stops_orientation():
    # a flat sheet of two faces plus a fin standing on their shared edge
    # 1-2: three faces on one edge. The edge is straight from all three,
    # and the fin's sign is decided by its own centroid rule, not inherited
    # across the fold.
    body = _body([(0, 0, 0), (100, 0, 0), (0, 100, 0), (100, 100, 0), (50, 50, 100)],
                 [(0, 1, 2), (2, 1, 3), (1, 2, 4)])
    plan = plan_refinement(body)
    assert plan.straight.sum() == 3.0
    assert plan.straight[0, 1] == 1.0 and plan.straight[1, 0] == 1.0 and plan.straight[2, 0] == 1.0


def test_a_cube_is_all_straight_at_80_and_all_smooth_at_100():
    body = _cube_body()
    straight = plan_refinement(body, 80.0).straight
    smooth = plan_refinement(body, 100.0).straight
    # each quad fans into two triangles: its diagonal is a 0-degree edge and stays smooth
    assert straight.sum() == 24.0      # 12 cube edges x 2 triangles touching each
    assert smooth.sum() == 0.0


def test_a_hex_prism_rounds_its_sides_and_keeps_its_rims():
    plan = plan_refinement(_hex_prism_body())
    geo = _rest(_hex_prism_body())
    normals = corner_normals(geo.vertices, geo.tris, plan)
    # side faces are the first 12 triangles (6 quads); a side corner's normal
    # is the mean of its two side faces -- radial, never tilted toward a cap
    for f in range(12):
        for k in range(3):
            assert abs(normals[f, k, 1]) < 1e-6, (f, k)
    # a cap corner's normal is the cap's own: the rim is a crease
    cap = normals[12:]
    assert np.allclose(np.abs(cap[..., 1]), 1.0)
    # the radial side normals point outward from the axis
    v = geo.vertices[geo.tris[:12]]
    outward = (normals[:12] * np.stack([v[..., 0], np.zeros_like(v[..., 0]), v[..., 2]], axis=-1)).sum(axis=-1)
    assert (outward > 0).all()


def test_boundary_edges_are_not_creases():
    plan = plan_refinement(_hex_prism_body(caps=False))
    assert plan.straight.sum() == 0.0        # 60-degree side edges smooth, open rims curve


def test_a_degenerate_face_is_straight_and_its_corners_never_nan():
    body = _cube_body()
    body.primitives.append(Primitive(1, 0, 9, [0, 0, 0]))
    plan = plan_refinement(body)
    geo = _rest(body)
    normals = corner_normals(geo.vertices, geo.tris, plan)
    assert not np.isnan(normals).any()
    assert np.allclose(np.linalg.norm(normals, axis=2), 1.0, atol=1e-5)
    assert plan.straight[-1].tolist() == [1.0, 1.0, 1.0]


def test_a_lone_degenerate_triangle_falls_back_to_camera_facing():
    body = _body([(0, 0, 0), (0, 0, 0), (0, 0, 0)], [(0, 1, 2)])
    geo = _rest(body)
    normals = corner_normals(geo.vertices, geo.tris, plan_refinement(body))
    assert np.array_equal(normals[0], np.tile(_CAMERA_FACING, (3, 1)))


def test_subpatch_levels():
    for level in (0, 1, 2, 3):
        bary = subpatch(level)
        assert bary.shape == (3 * 4 ** level, 3) and bary.dtype == np.float32
        assert (bary >= 0).all() and np.allclose(bary.sum(axis=1), 1.0)
        for corner in np.eye(3):
            assert (np.abs(bary - corner).sum(axis=1) < 1e-6).any()
    assert subpatch(2) is subpatch(2)
    with pytest.raises(ValueError):
        subpatch(2)[0, 0] = 5.0


def _patch(normals, straight=(0, 0, 0)):
    corners = np.array([[[0, 0, 0], [300, 0, 0], [0, 300, 0]]], np.float64)
    n = np.array([normals], np.float64)
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    return corners, n, np.array([straight], np.float64)


def test_evaluate_leaves_a_flat_patch_flat_and_its_corners_exact():
    corners, n, s = _patch([[0, 0, 1]] * 3)
    pos, nrm = evaluate(corners, n, s, subpatch(2))
    assert np.allclose(pos[0, :, 2], 0.0, atol=1e-4)
    assert np.allclose(nrm[0], [0, 0, 1])
    bary = subpatch(2)
    for k in range(3):
        at_corner = np.abs(bary - np.eye(3)[k]).sum(axis=1) < 1e-6
        assert np.allclose(pos[0][at_corner], corners[0, k], atol=1e-4)


def test_evaluate_bulges_along_tilted_normals():
    tilted = [[-0.5, -0.5, 1], [0.5, -0.5, 1], [-0.5, 0.5, 1]]
    corners, n, s = _patch(tilted)
    pos, _ = evaluate(corners, n, s, subpatch(2))
    centre = np.abs(subpatch(2) - 1 / 3).sum(axis=1).argmin()
    assert pos[0, centre, 2] > 5.0         # lifted toward +z, the mean normal


def test_evaluate_keeps_a_straight_edge_straight():
    tilted = [[-0.5, -0.5, 1], [0.5, -0.5, 1], [-0.5, 0.5, 1]]
    corners, n, s = _patch(tilted, straight=(1, 0, 0))
    pos, _ = evaluate(corners, n, s, subpatch(3))
    on_edge = subpatch(3)[:, 2] < 1e-6         # w == 0: the 0-1 edge
    assert np.allclose(pos[0][on_edge, 1:], 0.0, atol=1e-4)   # y == z == 0 along it
    corners, n, s = _patch(tilted)
    pos, _ = evaluate(corners, n, s, subpatch(3))
    assert not np.allclose(pos[0][on_edge, 2], 0.0, atol=1e-2)  # and it curves when smooth


def test_adjacent_patches_agree_on_their_shared_edge():
    # patch A (0,1,2) and patch B (1,0,3) share corners 0 and 1 with the
    # same corner normals, so their shared edge must evaluate identically
    p0, p1, p2, p3 = [0, 0, 0], [300, 0, 0], [0, 300, 0], [300, -300, 0]
    n0, n1 = [-0.3, 0.2, 1], [0.4, -0.1, 1]
    a_c, a_n, a_s = _patch([n0, n1, [0, 0, 1]])
    b = np.array([[p1, p0, p3]], np.float64)
    b_n = np.array([[n1, n0, [0, 0, 1]]], np.float64)
    b_n /= np.linalg.norm(b_n, axis=2, keepdims=True)
    b_s = np.zeros((1, 3))
    samples = np.array([[t, 1 - t, 0.0] for t in np.linspace(0, 1, 9)])
    a_pos, a_nrm = evaluate(a_c, a_n, a_s, samples)
    b_pos, b_nrm = evaluate(b, b_n, b_s, samples[:, [1, 0, 2]])   # B walks the edge the other way
    assert np.allclose(a_pos[0], b_pos[0], atol=1e-4)
    assert np.allclose(a_nrm[0], b_nrm[0], atol=1e-5)


def test_parse_crease():
    assert parse_crease({}) is None
    assert parse_crease({"crease": 60}) == 60.0
    assert parse_crease({"crease": 12.5}) == 12.5
    for bad in ({"crease": True}, {"crease": "soft"}, {"crease": 181}, {"crease": -1}):
        with pytest.raises(ValueError, match="crease"):
            parse_crease(bad)
    with pytest.raises(ValueError):
        parse_crease([])


def test_every_body_in_the_data_plans(data_dir, profile):
    from PyAitD.engine.assets import Assets
    assets = Assets(data_dir, profile)
    for num in range(assets.num_bodies):
        body = assets.body(num)
        plan = plan_refinement(body)
        geo = pose_geometry(body, [(0, (0, 0, 0))] * len(body.groups), (0, 0, 0))
        m = len(geo.tris)
        assert plan.orientation.shape == (m,) and set(np.unique(plan.orientation)) <= {-1.0, 1.0}
        assert plan.straight.shape == (m, 3) and set(np.unique(plan.straight)) <= {0.0, 1.0}
        if m:
            assert plan.pairs[:, 0].max() < 3 * m and plan.pairs[:, 1].max() < m
            assert len(np.unique(plan.pairs[:, 0])) == 3 * m     # every corner lists at least its own face


def test_the_hero_body_corner_normals_agree_with_their_faces(data_dir, profile):
    # The defect this module exists to fix: geometry._vertex_normals lets a
    # face feed a vertex only when the whole face lies in that vertex's
    # skeleton group, and 46 of the hero's 131 mesh vertices touch only
    # faces that span two groups -- they get the camera-facing placeholder,
    # which disagrees with most of the faces it is drawn on. Every corner
    # normal here comes from the corner's own face plus its smoothing group,
    # so it agrees with its face -- bar a handful of corners at fans that
    # wrap past 90 degrees (4 of 642 on this body). Measured against the
    # face's own oriented normal, not against the placeholder vector: a
    # face that genuinely faces -z has a genuine (0, 0, -1) normal.
    from PyAitD.engine.assets import Assets
    body = Assets(data_dir, profile).body(12)
    plan = plan_refinement(body)
    geo = pose_geometry(body, [(0, (0, 0, 0))] * len(body.groups), (0, 0, 0), refinement=plan)
    v = geo.vertices.astype(np.float64)
    t = geo.tris
    face = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]]) * plan.orientation[:, None]
    real = np.linalg.norm(face, axis=1) > 1e-9
    agree = np.einsum("mc,mkc->mk", face, geo.corner_normals.astype(np.float64)) > 0
    legacy = np.einsum("mc,mkc->mk", face, geo.normals[t].astype(np.float64)) > 0
    assert (~agree[real]).mean() < 0.02
    assert (~legacy[real]).mean() > 0.5
