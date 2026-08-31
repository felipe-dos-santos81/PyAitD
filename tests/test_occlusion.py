# SPDX-License-Identifier: GPL-2.0-only
import numpy as np
import pytest

from PyAitD.engine.data.formats import Body, Group, Primitive
from PyAitD.render.occlusion import DEFAULT_RAYS, bake_vertex_ao, hemisphere_directions, occlusion_of

pytestmark = pytest.mark.render


def _box(size=100.0):
    """A closed cube as (8,3) vertices and (12,3) triangles, winding mixed
    on purpose: FITD polygons have no consistent orientation."""
    s = size
    v = np.array([[-s, -s, -s], [s, -s, -s], [s, s, -s], [-s, s, -s],
                  [-s, -s, s], [s, -s, s], [s, s, s], [-s, s, s]], np.float32)
    quads = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (0, 3, 7, 4), (1, 2, 6, 5)]
    tris = []
    for i, (a, b, c, d) in enumerate(quads):
        if i % 2:
            tris += [(a, b, c), (a, c, d)]
        else:
            tris += [(c, b, a), (d, c, a)]
    return v, np.array(tris, np.int32)


def test_hemisphere_directions_are_unit_and_spread():
    d = hemisphere_directions(64)
    assert d.shape == (64, 3)
    assert np.allclose(np.linalg.norm(d, axis=1), 1.0)
    assert np.abs(d.mean(axis=0)).max() < 0.15      # not bunched on one side


def test_a_lone_triangle_is_fully_open():
    v = np.array([[0, 0, 0], [100, 0, 0], [0, 100, 0]], np.float32)
    ao = occlusion_of(v, np.array([[0, 1, 2]], np.int32))
    assert ao.dtype == np.float32 and ao.shape == (3,)
    assert np.array_equal(ao, np.ones(3, np.float32))   # its own triangle never occludes it


def test_a_vertex_inside_a_closed_box_is_fully_occluded():
    v, tris = _box()
    v = np.vstack([v, [[0.0, 0.0, 0.0]]]).astype(np.float32)   # an unreferenced centre vertex
    ao = occlusion_of(v, tris)
    assert ao[8] == 0.0


def test_the_outside_of_a_box_is_open():
    v, tris = _box()
    ao = occlusion_of(v, tris)
    # whichever way a corner's mixed-winding normal points, the bake keeps
    # the open hemisphere; a few grazing rays may still clip a face
    assert (ao > 0.6).all(), ao


def test_a_floor_vertex_beside_a_wall_is_about_half_occluded():
    s = 1000.0
    floor = np.array([[-s, 0, -s], [s, 0, -s], [s, 0, s], [-s, 0, s]], np.float32)
    # a wall through the floor at x=100, spanning y in [-s, s] (y grows
    # downward in FITD): whichever hemisphere the bake picks, half of it
    # looks into the wall
    wall = np.array([[100, s, -s], [100, s, s], [100, -s, s], [100, -s, -s]], np.float32)
    v = np.vstack([floor, wall, [[0.0, 0.0, 0.0]]]).astype(np.float32)
    tris = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]], np.int32)
    # give the probe vertex a floor triangle so its normal is the floor's
    tris = np.vstack([tris, [[8, 1, 2]]]).astype(np.int32)
    ao = occlusion_of(v, tris, rays=256)
    assert 0.3 < ao[8] < 0.7, ao[8]


def test_bake_is_deterministic_and_handles_a_triangle_less_body():
    v, tris = _box()
    a = occlusion_of(v, tris)
    b = occlusion_of(v, tris)
    assert np.array_equal(a, b)
    body = Body(0, (0,) * 6, (), [(0, 0, 0), (10, 0, 0)], [], [], [Primitive(0, 0, 1, [0, 1])])
    assert np.array_equal(bake_vertex_ao(body), np.ones(2, np.float32))


def test_bake_uses_the_assembled_rest_pose():
    # Two groups: group 1's vertices are stored relative to its base vertex
    # in group 0 (skel.pose_vertices adds the base). A bake on the raw
    # vertices would see the box and the probe in the wrong places; a bake
    # on the assembled rest pose puts the probe inside the box.
    #
    # Group 0's own base vertex must sit OUTSIDE the group it offsets and
    # hold (0, 0, 0) -- skel.pose_vertices adds base = pts[base_vertices]
    # to every vertex in [start, start+num_vertices) by mutating that list
    # entry in place, so a group cannot use one of its own (non-zero)
    # corners as its base without corrupting itself (see test_skel.py's
    # test_translate_group: "base vertex OUTSIDE the group (real-body
    # layout: base is the parent's origin)"). Vertex 8 below is that
    # dedicated zero vertex, outside group 0's own [0, 8) range.
    s = 100
    box = [(-s, -s, -s), (s, -s, -s), (s, s, -s), (-s, s, -s), (-s, -s, s), (s, -s, s), (s, s, s), (-s, s, s)]
    origin = (0, 0, 0)                                      # group 0's own base: outside its range, holds zero
    verts = box + [origin] + [(500, 0, 0)] + [(-500, 0, 0)]  # probe stored relative to vertex 9 -> lands at the origin
    quads = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (0, 3, 7, 4), (1, 2, 6, 5)]
    prims = [Primitive(1, 0, 1, list(q)) for q in quads]
    groups = [Group(0, 8, 8, 0xFF, 0, 0, 0, 0), Group(10, 1, 9, 0xFF, 1, 0, 0, 0)]
    body = Body(0, (0,) * 6, (), verts, groups, [0, 1], prims)
    ao = bake_vertex_ao(body, rays=DEFAULT_RAYS)
    assert ao.shape == (11,)
    assert ao[10] == 0.0
