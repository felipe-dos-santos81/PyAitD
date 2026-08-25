# SPDX-License-Identifier: GPL-2.0-only
import numpy as np
import pytest

from PyAitD.asset_resolver import ImageAsset
from PyAitD.geometry import BodyGeometry
from PyAitD.mask_geometry import MaskDraw
from PyAitD.render_gl import GLBackend, camera_matrix
from PyAitD.render_options import RenderOptions
from PyAitD.scene import ActorDraw, CameraView, FrameDescription
from PyAitD.skel import RenderResult
from PyAitD.world import CameraState


def _palette():
    palette = np.zeros((256, 3), dtype=np.uint8)
    palette[1], palette[2], palette[3] = (255, 0, 0), (0, 255, 0), (0, 0, 255)
    return palette


def _view():
    return CameraView(CameraState(0, 0, 0, 0, 0, 0, 1000, 320, 320).angles())


def _tri_geometry(z, color, span=400.0):
    v = np.array([[-span, -span, z], [span, -span, z], [-span, span, z]], np.float32)
    n = np.tile([0.0, 0.0, -1.0], (3, 1)).astype(np.float32)
    return BodyGeometry(v, n, np.array([[0, 1, 2]], np.int32), np.array([color], np.uint8),
                        np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), (),
                        np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))


def _actor(index, geometry, room=0, mask_ids=()):
    return ActorDraw(index, geometry, (0.0, 0.0, 0.0), room, (0,) * 6, RenderResult([], []), mask_ids)


def _frame(actors, masks=(), background=None):
    background = np.zeros((200, 320, 3), np.uint8) if background is None else background
    return FrameDescription(_view(), ImageAsset(background, False), _palette(), tuple(actors), tuple(masks))


def test_target_size_follows_scale(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=2, shading="flat"))
    assert backend.size == (640, 400)
    backend.release()


@pytest.mark.parametrize("scale,expected", [(1, (320, 200)), (3, (960, 600)), (4, (1280, 800)), (8, (2560, 1600))])
def test_target_size_for_various_scales(gl_ctx, scale, expected):
    backend = GLBackend(gl_ctx, RenderOptions(scale=scale, shading="flat"))
    assert backend.size == expected
    backend.release()


def test_background_fills_target_and_thumbnail_round_trips(gl_ctx):
    background = np.zeros((200, 320, 3), np.uint8)
    background[:, :160] = (200, 0, 0)
    backend = GLBackend(gl_ctx, RenderOptions(scale=2, shading="flat", background_filter="nearest"))
    backend.draw(_frame([], background=background))
    rgb = backend.read_rgb()
    assert rgb.shape == (400, 640, 3)
    assert tuple(rgb[10, 10]) == (200, 0, 0) and tuple(rgb[10, 630]) == (0, 0, 0)
    assert tuple(backend.thumbnail()[5, 5]) == (200, 0, 0)
    backend.release()


def test_background_filter_nearest_never_blends(gl_ctx):
    # Nearest sampling must reproduce only source colours -- never a value
    # in between -- regardless of internal scale.
    background = np.zeros((200, 320, 3), np.uint8)
    background[:, :160] = (200, 0, 0)
    backend = GLBackend(gl_ctx, RenderOptions(scale=3, shading="flat", background_filter="nearest"))
    backend.draw(_frame([], background=background))
    rgb = backend.read_rgb()
    colors = {tuple(c) for c in rgb.reshape(-1, 3)}
    assert colors <= {(200, 0, 0), (0, 0, 0)}
    backend.release()


def test_background_filter_bilinear_blends_at_the_boundary(gl_ctx):
    # At scale=2, the internal-target pixel column 320's fragment centre is
    # at window x=320.5, i.e. u=320.5/640=0.5008 in the source texture's
    # normalised coordinates. GL_LINEAR samples at texel-space s = u*320 -
    # 0.5 = 159.75, i.e. 75% of the way from texel159 (centre 159.5, red)
    # to texel160 (centre 160.5, black): the standard lerp is (1-frac)*t0 +
    # frac*t1 = 0.25*red + 0.75*black = (50, 0, 0). Derived from GL_LINEAR's
    # documented texel-centre sampling rule, independent of render_gl.py.
    background = np.zeros((200, 320, 3), np.uint8)
    background[:, :160] = (200, 0, 0)
    backend = GLBackend(gl_ctx, RenderOptions(scale=2, shading="flat", background_filter="bilinear"))
    backend.draw(_frame([], background=background))
    rgb = backend.read_rgb()
    pixel = rgb[200, 320]
    assert abs(int(pixel[0]) - 50) <= 3
    assert pixel[1] == 0 and pixel[2] == 0
    backend.release()


def test_background_filter_xbr_matches_nearest_at_scale_one(gl_ctx):
    # The xbr fragment shader samples fragment centres that always land
    # exactly on a source texel centre at scale=1 (uv*src_size has zero
    # fractional part everywhere), so its edge-blend condition
    # (abs(f.x)+abs(f.y) > 0.5) is 0 > 0.5, always false: at scale=1 xbr
    # is provably identical to a plain nearest sample of the source.
    background = np.zeros((200, 320, 3), np.uint8)
    background[:, :160] = (200, 0, 0)
    background[100:, 160:] = (0, 0, 255)
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat", background_filter="xbr"))
    backend.draw(_frame([], background=background))
    rgb = backend.read_rgb()
    assert np.array_equal(rgb, background)
    backend.release()


def test_camera_matrix_projects_like_the_logical_camera():
    view = _view()
    m = camera_matrix(view, scale=1)
    world = np.array([[100.0, -50.0, 500.0, 1.0]])
    clip = world @ m.T
    ndc = clip[0, :3] / clip[0, 3]
    sx, sy = (ndc[0] + 1) * 160, (1 - ndc[1]) * 100
    logical = view.project(world[:, :3])[0]
    assert abs(sx - logical[0]) < 0.01 and abs(sy - logical[1]) < 0.01


def test_flat_triangle_lands_where_the_logical_projection_says(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat"))
    geometry = _tri_geometry(z=1000.0, color=1)
    backend.draw(_frame([_actor(0, geometry)]))
    rgb = backend.read_rgb()
    centre = _view().project(geometry.vertices.mean(axis=0, keepdims=True).astype(np.float64))[0]
    assert tuple(rgb[int(centre[1]), int(centre[0])]) == (255, 0, 0)
    backend.release()


def test_depth_test_keeps_the_near_face_within_one_actor(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat"))
    near, far = _tri_geometry(500.0, 1), _tri_geometry(3000.0, 2, span=1200.0)
    merged = BodyGeometry(
        np.vstack([far.vertices, near.vertices]), np.vstack([far.normals, near.normals]),
        np.array([[0, 1, 2], [3, 4, 5]], np.int32), np.array([2, 1], np.uint8),
        near.lines, near.line_colors, (), near.points, near.point_sizes, near.point_colors)
    backend.draw(_frame([_actor(0, merged)]))
    rgb = backend.read_rgb()
    # (100, 140) [row, col]: with focal2==focal3==320 every _tri_geometry
    # triangle's hypotenuse projects to exactly sx+sy==260 regardless of
    # span/z, so (110, 150) (sx+sy==260, i.e. exactly ON that edge) is not a
    # safe interior point -- true continuous coverage excludes its pixel
    # centre (verified against CameraView.project by hand and against the
    # actual rendered edge, pixel by pixel). (140, 100) (sx+sy==240) is
    # comfortably inside both triangles, preserving the test's intent.
    assert tuple(rgb[100, 140]) == (255, 0, 0)  # inside both; near wins
    backend.release()


def test_painter_order_across_actors_ignores_depth(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat"))
    near, far = _tri_geometry(500.0, 1), _tri_geometry(3000.0, 2, span=1200.0)
    backend.draw(_frame([_actor(0, near), _actor(1, far)]))  # far drawn last: covers near
    assert tuple(backend.read_rgb()[100, 140]) == (0, 255, 0)
    backend.release()


def test_stencil_mask_erases_only_the_flagged_actor(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat"))
    poly = np.array([[0, 0], [319, 0], [319, 199], [0, 199]], np.int16)
    mask = MaskDraw(0, (poly,), (0, 0, 319, 199), 0, ())
    a, b = _tri_geometry(1000.0, 1), _tri_geometry(900.0, 2)
    backend.draw(_frame([_actor(0, a), _actor(1, b, mask_ids=(0,))], [mask]))
    assert tuple(backend.read_rgb()[100, 140]) == (255, 0, 0)
    backend.release()


def test_stencil_mask_erases_only_the_covered_region(gl_ctx):
    # A mask covering only the right half of the screen must leave the
    # left half of the (otherwise full-screen) actor untouched.
    poly = np.array([[160, 0], [319, 0], [319, 199], [160, 199]], np.int16)
    mask = MaskDraw(0, (poly,), (160, 0, 319, 199), 0, ())
    geometry = _tri_geometry(1000.0, 1, span=100000.0)  # covers the whole screen
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat"))
    backend.draw(_frame([_actor(0, geometry, mask_ids=(0,))], [mask]))
    rgb = backend.read_rgb()
    assert tuple(rgb[100, 50]) == (255, 0, 0)  # left of the mask: still visible
    assert tuple(rgb[100, 250]) == (0, 0, 0)   # inside the mask: erased to background
    backend.release()


def test_stencil_mask_matches_bitmap_erase_at_scale_one(gl_ctx, data_dir):
    from PyAitD.floor import Floor
    from PyAitD.mask import create_aitd1_mask
    floor = Floor(data_dir, 0)
    draws = floor.mask_draws(0)
    bitmaps = create_aitd1_mask(floor.camera_raw, floor.camera_data_offsets[0])
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat"))
    full = _tri_geometry(400.0, 1, span=100000.0)  # covers the whole screen
    for draw, mask in zip(draws, bitmaps):
        backend.draw(_frame([_actor(0, full, mask_ids=(draw.id,))], draws))
        erased = backend.read_rgb()[:, :, 0] == 0
        expected = mask.bitmap == 255
        # edges may differ by a pixel between GL rasterisation and fillpoly
        disagree = erased != expected
        assert disagree.sum() <= 2 * sum(len(p) for p in draw.polygons) * 4 + 16
    backend.release()


def test_shading_modes_differ(gl_ctx):
    tilted = _tri_geometry(1000.0, 1)
    tilted = BodyGeometry(tilted.vertices, np.tile([0.6, 0.0, -0.8], (3, 1)).astype(np.float32),
                          tilted.tris, tilted.tri_colors, tilted.lines, tilted.line_colors, (),
                          tilted.points, tilted.point_sizes, tilted.point_colors)
    outputs = {}
    for mode in ("flat", "lambert", "smooth"):
        backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading=mode))
        backend.draw(_frame([_actor(0, tilted)]))
        outputs[mode] = backend.read_rgb()[100, 140].copy()  # see the note in test_depth_test_...
        backend.release()
    assert tuple(outputs["flat"]) == (255, 0, 0)
    assert 0 < outputs["lambert"][0] < 255 and 0 < outputs["smooth"][0] < 255
    assert outputs["smooth"][0] >= int(255 * 0.55) - 1
    assert not np.array_equal(outputs["flat"], outputs["lambert"])
    assert not np.array_equal(outputs["flat"], outputs["smooth"])


def test_sphere_and_line_and_point_render(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat"))
    v = np.array([[0.0, 0.0, 1000.0], [300.0, 0.0, 1000.0]], np.float32)
    n = np.tile([0.0, 0.0, -1.0], (2, 1)).astype(np.float32)
    geometry = BodyGeometry(v, n, np.zeros((0, 3), np.int32), np.zeros(0, np.uint8),
                            np.array([[0, 1]], np.int32), np.array([2], np.uint8),
                            ((0, 60.0, 3),), np.array([1], np.int32), np.array([2], np.uint8), np.array([1], np.uint8))
    backend.draw(_frame([_actor(0, geometry)]))
    rgb = backend.read_rgb()
    centre = _view().project(v.astype(np.float64))
    assert tuple(rgb[int(centre[0][1]), int(centre[0][0])]) == (0, 0, 255)      # sphere at v0
    assert tuple(rgb[int(centre[1][1]), int(centre[1][0])]) == (255, 0, 0)      # point at v1 (drawn after line)
    mid = (centre[0] + centre[1]) / 2
    assert tuple(rgb[int(mid[1]), int(mid[0])]) == (0, 255, 0)                  # line midpoint
    backend.release()


def test_thumbnail_is_a_true_box_average(gl_ctx):
    # Write a known RGBA pattern directly into the target texture (bypassing
    # draw() entirely) so the expectation is independent of the rendering
    # pipeline: thumbnail()'s scale=2 box must average all 4 source pixels,
    # not just sample a corner.
    backend = GLBackend(gl_ctx, RenderOptions(scale=2, shading="flat"))
    w, h = backend.size
    top_down = np.zeros((h, w, 4), np.uint8)
    top_down[..., 3] = 255
    top_down[0, 0, 0], top_down[0, 1, 0] = 10, 20
    top_down[1, 0, 0], top_down[1, 1, 0] = 30, 40
    backend.texture.write(np.ascontiguousarray(top_down[::-1]).tobytes())  # GL rows are bottom-up
    thumb = backend.thumbnail()
    assert thumb[0, 0, 0] == int((10 + 20 + 30 + 40) / 4)
    backend.release()


def test_release_is_safe_to_call_repeatedly(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat"))
    backend.release()
    backend.release()  # must not raise
