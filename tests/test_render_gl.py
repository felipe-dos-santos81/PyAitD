# SPDX-License-Identifier: GPL-2.0-only
import pathlib

import moderngl
import numpy as np
import pytest

from PyAitD.render.asset_resolver import ImageAsset
from PyAitD.render.geometry import BodyGeometry
from PyAitD.engine.mask_geometry import MaskDraw
from PyAitD.render.render_gl import GLBackend, camera_matrix
from PyAitD.render.render_options import RenderOptions
from PyAitD.render.scene import ActorDraw, CameraView, FrameDescription
from PyAitD.engine.skel import RenderResult
from PyAitD.engine.world import CameraState

pytestmark = pytest.mark.render


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


# zv=(0,)*6 puts plane_y = max(zv[2], zv[3]) = 0 -- the ground plane at
# eye level for this test camera. Every projected shadow vertex collapses
# onto sy=100 (the horizon), so the silhouette is a zero-area triangle
# and the shadow pass rasterises nothing, even under lighting="scene".
# That makes this helper silently shadow-blind: an actor built with it
# renders identically whether or not a shadow pass runs. Use
# _standing_actor (below) instead when a test wants a real, visible
# shadow -- its feet_y sits below the plane so the projection is not
# degenerate.
def _actor(index, geometry, room=0, mask_ids=()):
    return ActorDraw(index, geometry, (0.0, 0.0, 0.0), room, (0,) * 6, RenderResult([], []), mask_ids)


def _frame(actors, masks=(), background=None):
    background = np.zeros((200, 320, 3), np.uint8) if background is None else background
    return FrameDescription(_view(), ImageAsset(background, False), _palette(), tuple(actors), tuple(masks))


def _scene_light(direction):
    from PyAitD.render.lighting import SceneLight
    return SceneLight(direction, (1.0, 1.0, 1.0), (0.1, 0.1, 0.1), 1.0)


def _doubled_tri_geometry(z, color, span):
    """One triangle drawn twice: identical coverage, two overlapping draws."""
    base = _tri_geometry(z, color, span)
    return BodyGeometry(
        base.vertices, base.normals,
        np.array([[0, 1, 2], [0, 1, 2]], np.int32), np.array([color, color], np.uint8),
        base.lines, base.line_colors, base.spheres,
        base.points, base.point_sizes, base.point_colors)


def _plain_background(gl_ctx, plate):
    """The same plate with no actors at all: the baseline a shadow darkens."""
    empty = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene"))
    empty.draw(FrameDescription(_view(), ImageAsset(plate, False), _palette(), (), ()))
    out = empty.read_rgb().astype(int)
    empty.release()
    return out


def _standing_actor(index, geometry, feet_y):
    zv = (0, 0, feet_y - 200, feet_y, 0, 0)
    return ActorDraw(index, geometry, (0.0, 0.0, 0.0), 0, zv, RenderResult([], []), ())


def _lit_scene_backend(gl_ctx):
    return GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene"))


def test_a_shadow_darkens_the_ground_below_the_actor_only(gl_ctx):
    backend = _lit_scene_backend(gl_ctx)
    plate = np.full((200, 320, 3), 200, np.uint8)
    geometry = _tri_geometry(600.0, 1, span=100.0)
    actor = _standing_actor(0, geometry, feet_y=150)
    light = _scene_light((0.0, -1.0, -0.2))
    frame = FrameDescription(_view(), ImageAsset(plate, False), _palette(), (actor,), (), light)
    backend.draw(frame)
    rendered = backend.read_rgb().astype(int)
    plain = _plain_background(gl_ctx, plate)
    # somewhere below the actor's feet the plate got darker...
    assert (rendered[120:, :] < plain[120:, :] - 5).any()
    # ...and nothing above the top of the frame did
    assert (rendered[:5, :] >= plain[:5, :] - 1).all()
    backend.release()


def test_overlapping_shadow_triangles_darken_a_pixel_once(gl_ctx):
    # Coverage is binary: two limbs crossing must not stack into a black
    # blob. This is the whole reason the pass goes through a texture.
    backend = _lit_scene_backend(gl_ctx)
    plate = np.full((200, 320, 3), 200, np.uint8)
    single = _standing_actor(0, _tri_geometry(600.0, 1, span=100.0), feet_y=150)
    doubled = _standing_actor(0, _doubled_tri_geometry(600.0, 1, span=100.0), feet_y=150)
    light = _scene_light((0.0, -1.0, -0.2))
    backend.draw(FrameDescription(_view(), ImageAsset(plate, False), _palette(), (single,), (), light))
    once = backend.read_rgb().astype(int)
    backend.draw(FrameDescription(_view(), ImageAsset(plate, False), _palette(), (doubled,), (), light))
    twice = backend.read_rgb().astype(int)
    assert np.array_equal(once, twice)
    backend.release()


def test_a_foreground_mask_erases_the_shadow_under_it(gl_ctx):
    backend = _lit_scene_backend(gl_ctx)
    plate = np.full((200, 320, 3), 200, np.uint8)
    actor = _standing_actor(0, _tri_geometry(600.0, 1, span=100.0), feet_y=150)
    masked = ActorDraw(actor.index, actor.geometry, actor.position, actor.room, actor.zv,
                       actor.logical, (0,))
    full = MaskDraw(0, (np.array([[0, 0], [320, 0], [320, 200], [0, 200]], np.int16),),
                    (0, 0, 320, 200), 0, ())
    light = _scene_light((0.0, -1.0, -0.2))
    frame = FrameDescription(_view(), ImageAsset(plate, False), _palette(), (masked,), (full,), light)
    backend.draw(frame)
    assert np.array_equal(backend.read_rgb(), _plain_background(gl_ctx, plate))
    backend.release()


def test_fixed_lighting_casts_no_shadow(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="fixed"))
    plate = np.full((200, 320, 3), 200, np.uint8)
    actor = _standing_actor(0, _tri_geometry(600.0, 1, span=100.0), feet_y=150)
    light = _scene_light((0.0, -1.0, -0.2))
    with_light = FrameDescription(_view(), ImageAsset(plate, False), _palette(), (actor,), (), light)
    backend.draw(with_light)
    lit = backend.read_rgb().copy()
    backend.draw(_frame([actor], background=plate))
    assert np.array_equal(backend.read_rgb(), lit)
    backend.release()


def test_shadow_lands_where_the_light_direction_says_under_a_rotated_camera(gl_ctx):
    # _view()'s camera has every angle zero, so rotation_matrix returns the
    # identity and rot == rot.T: a bug that used rot where rot.T belongs (or
    # vice versa) would still pass every other shadow test in this file. A
    # rotated camera makes the two genuinely different matrices, and the
    # shadow's on-screen centroid is re-derived here independently (same
    # formula as _draw_frame, but computed in the test, not trusted from
    # it) and pinned tightly enough that swapping rot for rot.T moves the
    # expected centroid by ~7.4px against a 2.5px tolerance (checked by
    # hand). The centroid, not a vertex-projection bounding box, is what's
    # compared: at this rotation the flattened triangle is a thin sliver in
    # screen space (~2px tall), so its topmost vertex's x barely survives
    # rasterisation at all -- a raw vertex bbox overstates the actual
    # rasterised coverage by ~11px and would make this test flaky for the
    # wrong reason. The centroid of actual dark pixels does not have that
    # problem and still moves the ~7.4px a rot/rot.T swap requires.
    from PyAitD.render.render_gl import rotation_matrix
    from PyAitD.render.lighting import project_to_plane

    state = CameraState(0, 90, 0, 0, 0, 0, 1000, 320, 320).angles()
    view = CameraView(state)
    backend = _lit_scene_backend(gl_ctx)
    plate = np.full((200, 320, 3), 200, np.uint8)
    span = 100.0
    geometry = _tri_geometry(600.0, 1, span=span)
    actor = _standing_actor(0, geometry, feet_y=150)
    direction = (0.0, -1.0, -0.2)
    light = _scene_light(direction)
    frame = FrameDescription(view, ImageAsset(plate, False), _palette(), (actor,), (), light)
    backend.draw(frame)
    rendered = backend.read_rgb().astype(int)

    empty = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene"))
    empty.draw(FrameDescription(view, ImageAsset(plate, False), _palette(), (), ()))
    plain = empty.read_rgb().astype(int)
    empty.release()
    backend.release()

    # The actor's own body projects to rows ~78..122 at this rotation; only
    # below that can the shadow -- and nothing else -- appear.
    dark = np.any(rendered[125:, :] < plain[125:, :] - 5, axis=2)
    rows_idx, cols_idx = np.where(dark)
    assert rows_idx.size, "no shadow pixels found below the actor"
    rendered_centroid = np.array([cols_idx.mean(), rows_idx.mean() + 125])

    # Independently re-derive where the shadow belongs: same formula
    # _draw_frame uses (rot.T, then project_to_plane, then the logical
    # camera projection), computed fresh here rather than trusted from the
    # implementation under test.
    rot = rotation_matrix(state)
    travel = -(rot.T @ np.asarray(direction, np.float64))
    world = np.array([[-span, -span, 600.0], [span, -span, 600.0], [-span, span, 600.0]])
    plane_y = float(max(actor.zv[2], actor.zv[3]))
    flat = project_to_plane(world, travel, plane_y)
    expected_centroid = view.project(flat)[:, :2].mean(axis=0)

    assert np.linalg.norm(rendered_centroid - expected_centroid) <= 2.5


def test_a_triangle_less_actor_leaves_no_shadow_and_does_not_disturb_another_actors(gl_ctx):
    """Smoke case only -- see test_two_different_casters_do_not_share_leftover_shadow_coverage
    below for the test that actually pins the per-actor coverage reset.
    Because a triangle-less actor never composites at all (`if scene_lit
    and self._rasterize_shadow(...)`  short-circuits for it), pairing one
    with a real caster is a no-op by construction: it cannot fail whether
    or not the shadow texture is reset between actors, so it does NOT pin
    the reset, the guard's position relative to the clear, or painter
    order. What it does verify is narrower: a triangle-less actor renders
    nothing of its own and does not change the caster's own output,
    regardless of draw order. It's kept because it's the only test in this
    file that exercises the `if not len(geometry.tris): return False`
    guard's return path at all."""
    backend = _lit_scene_backend(gl_ctx)
    plate = np.full((200, 320, 3), 200, np.uint8)
    light = _scene_light((0.0, -1.0, -0.2))
    caster = _standing_actor(0, _tri_geometry(600.0, 1, span=100.0), feet_y=150)
    empty_geometry = BodyGeometry(
        np.zeros((0, 3), np.float32), np.zeros((0, 3), np.float32),
        np.zeros((0, 3), np.int32), np.zeros(0, np.uint8),
        np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), (),
        np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))
    triangle_less = ActorDraw(1, empty_geometry, (500.0, 0.0, 0.0), 0, (0, 0, -50, 150, 0, 0),
                              RenderResult([], []), ())

    solo = FrameDescription(_view(), ImageAsset(plate, False), _palette(), (caster,), (), light)
    backend.draw(solo)
    solo_result = backend.read_rgb().copy()

    for order in ((triangle_less, caster), (caster, triangle_less)):
        backend.draw(FrameDescription(_view(), ImageAsset(plate, False), _palette(), order, (), light))
        assert np.array_equal(backend.read_rgb(), solo_result)

    backend.release()


def test_two_different_casters_do_not_share_leftover_shadow_coverage(gl_ctx):
    """This is the test that actually pins the per-actor coverage reset.
    Both actors here have real triangles, so neither one's composite is
    ever skipped -- unlike the triangle-less smoke case above, this cannot
    pass by construction; it has to actually reset the shared shadow
    texture between actors to come out right.

    Two actors share one position: `large` (span=300) draws first, then
    `small` (span=60) draws on top of it. `small`'s own shadow/body can
    only affect pixels within its own (smaller) footprint. So consider the
    annulus -- pixels `large` alone darkens that `small` alone never
    touches: under a correct per-actor reset, only `large`'s own composite
    ever reaches those pixels, so a frame with both actors must match a
    frame with `large` alone there, exactly. Without the reset, `small`'s
    rasterize call would draw its own (small) triangle over `large`'s
    still-resident (large) coverage rather than a cleared texture, so
    `small`'s composite would incorrectly darken that whole annulus a
    second time.

    Measured on this implementation: removing the `_shadow_fbo.clear()` in
    `_rasterize_shadow` turns 0 differing pixels in the annulus into 160."""
    plate = np.full((200, 320, 3), 200, np.uint8)
    light = _scene_light((0.0, -1.0, -0.2))
    large = _standing_actor(0, _tri_geometry(600.0, 1, span=300.0), feet_y=150)
    small = _standing_actor(1, _tri_geometry(600.0, 1, span=60.0), feet_y=150)

    def render(actors):
        # A fresh backend per frame: the shadow texture is a scratch
        # resource that persists across draw() calls on the same backend,
        # and reusing one backend for the reference renders below would
        # let an earlier frame's leftover coverage contaminate them --
        # exactly the bug this test exists to catch, just relocated to the
        # test's own reference images instead of the thing under test.
        backend = _lit_scene_backend(gl_ctx)
        backend.draw(FrameDescription(_view(), ImageAsset(plate, False), _palette(), actors, (), light))
        image = backend.read_rgb().astype(int)
        backend.release()
        return image

    solo_large = render((large,))
    solo_small = render((small,))
    paired = render((large, small))
    plain = render(())

    dark_large = np.any(solo_large < plain - 5, axis=2)
    affected_by_small = np.any(solo_small != plain, axis=2)
    annulus = dark_large & ~affected_by_small
    assert annulus.sum() > 1000, "the annulus is too small to be a meaningful check"

    assert np.array_equal(paired[annulus], solo_large[annulus])


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


def test_background_filter_xbr_differs_from_nearest_on_a_diagonal_edge(gl_ctx):
    # The scale=1 test above only proves xbr's output equals nearest's in
    # its provably-degenerate case (f is always exactly (0, 0)): a renderer
    # that silently dropped the xbr() branch entirely (mode == 2 always
    # falling through to a plain texture() sample) would still pass it.
    # At scale=4 the sub-pixel offsets are no longer degenerate (see the
    # scale=1 test's derivation), so a real diagonal edge must produce a
    # named pixel where xbr's edge-aware blend disagrees with a plain
    # nearest sample.
    y, x = np.mgrid[0:200, 0:320]
    background = np.zeros((200, 320, 3), np.uint8)
    background[(x + y) < 240] = (200, 0, 0)

    xbr = GLBackend(gl_ctx, RenderOptions(scale=4, shading="flat", background_filter="xbr"))
    xbr.draw(_frame([], background=background))
    xbr_pixel = tuple(xbr.read_rgb()[391, 571])
    xbr.release()

    nearest = GLBackend(gl_ctx, RenderOptions(scale=4, shading="flat", background_filter="nearest"))
    nearest.draw(_frame([], background=background))
    nearest_pixel = tuple(nearest.read_rgb()[391, 571])
    nearest.release()

    assert xbr_pixel != nearest_pixel


def test_camera_matrix_projects_like_the_logical_camera():
    view = _view()
    m = camera_matrix(view, scale=1)
    world = np.array([[100.0, -50.0, 500.0, 1.0]])
    clip = world @ m.T
    ndc = clip[0, :3] / clip[0, 3]
    sx, sy = (ndc[0] + 1) * 160, (1 - ndc[1]) * 100
    logical = view.project(world[:, :3])[0]
    assert abs(sx - logical[0]) < 0.01 and abs(sy - logical[1]) < 0.01


def test_camera_matrix_parity_across_rotated_cameras():
    # The arbiter test above uses CameraState(0, 0, 0, ...): alpha=beta=
    # gamma=0, so rotation_matrix returns the identity there and every
    # other committed test also builds cameras with no rotation -- a
    # transposed block, swapped Y/X/Z composition order or wrong _sin_cos
    # phase in rotation_matrix would still pass the whole suite. This is a
    # pure-numpy sweep (no gl_ctx) over non-zero alpha/beta/gamma cameras,
    # checked directly against CameraView.project -- the same technique
    # used to measure the 0.0152px parity figure in the task report,
    # committed here instead of only run ad hoc.
    rng = np.random.default_rng(0)
    max_err = 0.0
    checked_any = False
    for _ in range(50):
        alpha, beta, gamma = (int(v) for v in rng.integers(1, 1024, size=3))
        x, y, z = (int(v) for v in rng.integers(-2000, 2000, size=3))
        state = CameraState(alpha, beta, gamma, x, y, z, 1000, 320, 320).angles()
        view = CameraView(state)
        m = camera_matrix(view, scale=1)
        world = rng.uniform(-2000.0, 2000.0, size=(20, 3))
        clip = np.hstack([world, np.ones((20, 1))]) @ m.T
        w = clip[:, 3]
        valid = w > 1e-6
        if not valid.any():
            continue
        ndc = clip[valid, :3] / w[valid, None]
        sx = (ndc[:, 0] + 1) * 160
        sy = (1 - ndc[:, 1]) * 100
        logical = view.project(world[valid].astype(np.float64))
        keep = logical[:, 0] != -10000.0
        if not keep.any():
            continue
        checked_any = True
        err = np.abs(np.stack([sx[keep] - logical[keep, 0], sy[keep] - logical[keep, 1]], axis=1))
        max_err = max(max_err, float(err.max()))
    assert checked_any
    assert max_err < 0.05


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
    # far is vstacked first (indices 0-2) but *submitted last* (tris[1]):
    # with depth test off this would paint far (green) over near, so this
    # only reads red if the depth test is genuinely discriminating by
    # depth, not by submission/painter order within the one draw call.
    merged = BodyGeometry(
        np.vstack([far.vertices, near.vertices]), np.vstack([far.normals, near.normals]),
        np.array([[3, 4, 5], [0, 1, 2]], np.int32), np.array([1, 2], np.uint8),
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


def test_actors_and_mask_render_correctly_above_scale_one(gl_ctx):
    # Every other actor+mask test above runs at scale=1, where the internal
    # target equals the logical 320x200 resolution and the mask-polygon ->
    # NDC conversion and the target_size-based mask lookup in the fragment
    # shader happen to be numerically identical to the logical/internal
    # split. At scale=3 the internal target (960x600) genuinely differs
    # from logical space, exercising both of those scale-dependent paths.
    poly = np.array([[160, 0], [319, 0], [319, 199], [160, 199]], np.int16)
    mask = MaskDraw(0, (poly,), (160, 0, 319, 199), 0, ())
    # NOTE: despite the name, this triangle does *not* cover the whole
    # screen -- its hypotenuse is the fixed line sx+sy=260 in logical space
    # regardless of span or depth (a property of _tri_geometry), so at
    # scale=3 the actor only actually covers pixels with sx+sy <~ 780. The
    # (300, 700) probe below used to sit outside that coverage (x+y=1000),
    # so it read background black whether or not the mask erased anything
    # -- an accidental pass. (300, 600) is inside both the mask and the
    # triangle's real coverage (verified against a coverage render with
    # mask_ids=()), so it actually exercises GPU mask erasure.
    geometry = _tri_geometry(1000.0, 1, span=100000.0)
    backend = GLBackend(gl_ctx, RenderOptions(scale=3, shading="flat"))
    backend.draw(_frame([_actor(0, geometry, mask_ids=(0,))], [mask]))
    rgb = backend.read_rgb()
    assert rgb.shape == (600, 960, 3)
    assert tuple(rgb[300, 300]) == (255, 0, 0)  # left of the mask: still visible
    assert tuple(rgb[100, 600]) == (0, 0, 0)    # inside the mask (and the triangle): erased to background
    backend.release()


def test_stencil_mask_matches_bitmap_erase_at_scale_one(gl_ctx, data_dir, profile):
    from PyAitD.engine.floor import Floor
    from PyAitD.engine.mask import create_aitd1_mask
    floor = Floor(data_dir, 0, profile)
    draws = floor.mask_draws(0)
    bitmaps = create_aitd1_mask(floor.camera_raw, floor.camera_data_offsets[0])
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat"))
    # NOTE: despite the name, this triangle does *not* cover the whole
    # screen -- its hypotenuse is the fixed line sx+sy=260 in logical space
    # regardless of span or depth (a property of _tri_geometry), so it only
    # actually covers ~31,900 of the 64,000 logical pixels. Comparing
    # `erased` against `expected` over the *whole* frame (as this test used
    # to) counts every uncovered background pixel as agreement or
    # disagreement by accident, which is not what "mask erasure matches
    # the bitmap" is supposed to mean -- it swamps the signal (tens of
    # thousands of accidental disagreements) with noise from pixels the
    # actor was never drawn on in the first place. Render once with no
    # mask to find where the actor is actually drawn, and restrict the
    # comparison to that coverage.
    full = _tri_geometry(400.0, 1, span=100000.0)
    backend.draw(_frame([_actor(0, full, mask_ids=())], draws))
    coverage = backend.read_rgb()[:, :, 0] != 0
    for draw, mask in zip(draws, bitmaps):
        backend.draw(_frame([_actor(0, full, mask_ids=(draw.id,))], draws))
        erased = backend.read_rgb()[:, :, 0] == 0
        expected = mask.bitmap == 255
        # edges may differ by a pixel between GL rasterisation and fillpoly
        # (measured on real floor-0/camera-0 data, coverage-restricted: 0,
        # 43, 58, 75, 155, 208, 0, 0 disagreeing pixels for the eight masks
        # whose polygons are convex or otherwise star-shaped from their
        # first vertex; worst of those is 208. 312 is 1.5x headroom over
        # that, well clear of ordinary edge noise).
        disagree = (erased != expected) & coverage
        assert disagree.sum() <= max(2 * sum(len(p) for p in draw.polygons) * 4 + 16, 312)
    backend.release()


def test_shading_modes_differ(gl_ctx):
    tilted = _tri_geometry(1000.0, 1)
    tilted = BodyGeometry(tilted.vertices, np.tile([0.6, 0.0, -0.8], (3, 1)).astype(np.float32),
                          tilted.tris, tilted.tri_colors, tilted.lines, tilted.line_colors, (),
                          tilted.points, tilted.point_sizes, tilted.point_colors)
    outputs = {}
    for mode in ("flat", "lambert", "smooth"):
        backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading=mode, lighting="fixed"))
        backend.draw(_frame([_actor(0, tilted)]))
        outputs[mode] = backend.read_rgb()[100, 140].copy()  # see the note in test_depth_test_...
        backend.release()
    assert tuple(outputs["flat"]) == (255, 0, 0)
    assert 0 < outputs["lambert"][0] < 255 and 0 < outputs["smooth"][0] < 255
    assert outputs["smooth"][0] >= int(255 * 0.55) - 1
    assert not np.array_equal(outputs["flat"], outputs["lambert"])
    assert not np.array_equal(outputs["flat"], outputs["smooth"])
    # flat!=lambert and flat!=smooth don't rule out smooth being silently
    # implemented as an alias for lambert (both would read the same and
    # both pass the checks above); pin lambert and smooth apart too.
    assert not np.array_equal(outputs["lambert"], outputs["smooth"])


def test_sphere_and_line_and_point_render(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat", msaa=0))
    # y=2.0 (not 0.0) on both endpoints: a perfectly horizontal line at
    # world y=0 projects to exactly sy=100, so the line's half-width-0.5
    # quad spans logical y [99.5, 100.5] -- both of those are themselves
    # exact pixel-centre sampling positions (row 99's/100's fragment centre
    # is exactly a half-integer, same boundary-tie class as the (110,150)
    # issue elsewhere in this file), so which row reads the line colour is
    # implementation-defined, not guaranteed by the fill convention. y=2.0
    # shifts the whole line to sy=100.32, clearing every nearby half-
    # integer boundary by >=0.3px while leaving the rest of the test
    # (sphere at v0, point at v1) geometrically unchanged in spirit.
    v = np.array([[0.0, 2.0, 1000.0], [300.0, 2.0, 1000.0]], np.float32)
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


def test_msaa_resolves_into_the_same_texture(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat", msaa=4))
    assert backend.size == (320, 200)
    plate = np.full((200, 320, 3), 40, np.uint8)
    backend.draw(_frame([_actor(0, _tri_geometry(600.0, 1))], background=plate))
    rendered = backend.read_rgb()
    assert rendered.shape == (200, 320, 3)
    assert rendered.max() > 0                      # something actually landed
    assert backend.thumbnail().shape == (200, 320, 3)
    backend.release()


def test_msaa_softens_a_diagonal_edge(gl_ctx):
    # The whole point: with multisampling the silhouette gains intermediate
    # values along its diagonal that a single-sampled render cannot produce.
    plate = np.zeros((200, 320, 3), np.uint8)
    frame = _frame([_actor(0, _tri_geometry(600.0, 1))], background=plate)

    def edge_values(msaa):
        backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat", msaa=msaa))
        backend.draw(frame)
        red = backend.read_rgb()[:, :, 0].astype(int)
        backend.release()
        return red

    aliased, smoothed = edge_values(0), edge_values(4)
    partial = ((smoothed > 0) & (smoothed < 255)).sum()
    assert partial > ((aliased > 0) & (aliased < 255)).sum()


def test_msaa_is_clamped_to_what_the_context_supports(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat", msaa=8))
    assert backend.samples <= gl_ctx.max_samples
    backend.release()


def test_msaa_zero_keeps_the_single_sampled_path(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat", msaa=0))
    assert backend.samples == 0
    assert backend._target is backend._fbo
    assert backend._ms_fbo is None
    backend.release()


def test_release_is_safe_to_call_repeatedly(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat"))
    backend.release()
    backend.release()  # must not raise


def test_init_failure_releases_every_already_allocated_gl_object(gl_ctx, monkeypatch):
    # Finding 4: a construction failure partway through __init__ (here, the
    # very last allocation step) must not leak the texture, depth
    # renderbuffer, both FBOs, four programs, buffers and VAOs already
    # created before it -- _select_backend's except clause never gets a
    # live GLBackend reference to release() them through, since the
    # constructor call itself raised.
    import PyAitD.render.render_gl as render_gl_module

    def boom(*_a, **_k):
        raise RuntimeError("icosphere blew up")

    monkeypatch.setattr(render_gl_module, "icosphere", boom)

    backend = object.__new__(GLBackend)
    with pytest.raises(RuntimeError, match="icosphere blew up"):
        backend.__init__(gl_ctx, RenderOptions(scale=8, shading="flat", msaa=4))

    leak_checked = 0
    for attr in (
        "texture", "_depth", "_fbo", "_mask_tex", "_mask_fbo",
        "_shadow_tex", "_shadow_fbo", "_shadow_prog", "_shadow_geom_prog",
        "_shadow_quad", "_shadow_quad_vao",
        "_ms_color", "_ms_depth", "_ms_fbo",
        "_bg_prog", "_actor_prog", "_screen_prog", "_stencil_prog",
        "_quad", "_quad_vao", "_thumb_tex", "_thumb_fbo",
        "_thumb_quad", "_thumb_quad_vao", "_material_tex",
    ):
        resource = getattr(backend, attr)
        assert resource is not None, f"{attr} was never allocated before the failure"
        assert isinstance(resource.mglo, moderngl.InvalidObject), f"{attr} leaked (not released)"
        leak_checked += 1
    assert leak_checked == 25  # every GL resource __init__ allocates, none skipped
    assert backend._sphere is None
    backend.release()  # must still be safe to call again


def test_draw_after_release_raises_a_clear_error(gl_ctx):
    # Finding 3's compose_scene fallback releases a GLBackend and swaps in a
    # SoftwareBackend out from under any caller still holding the old
    # object; a stray draw() on it afterward must fail loudly and clearly,
    # not with an opaque moderngl.InvalidObject error deep inside a GL call.
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat"))
    backend.release()
    with pytest.raises(RuntimeError, match="release"):
        backend.draw(_frame([]))


def _lit_frame(actors, direction):
    from PyAitD.render.lighting import SceneLight
    light = SceneLight(direction, (1.0, 1.0, 1.0), (0.2, 0.2, 0.2), 1.0)
    return FrameDescription(_view(), ImageAsset(np.zeros((200, 320, 3), np.uint8), False),
                            _palette(), tuple(actors), (), light)


def _facing_tri(z, color, normal):
    span = 400.0
    v = np.array([[-span, -span, z], [span, -span, z], [-span, span, z]], np.float32)
    n = np.tile(normal, (3, 1)).astype(np.float32)
    return BodyGeometry(v, n, np.array([[0, 1, 2]], np.int32), np.array([color], np.uint8),
                        np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), (),
                        np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))


def _golden_frame():
    """A fixed synthetic scene-lit frame: two facing triangles, one sphere,
    a slanted light. Rendered once by the pre-materials backend into
    tests/golden/scene_lit_classic.npy; realism="classic" must reproduce
    it byte for byte forever after."""
    from PyAitD.render.lighting import SceneLight
    light = SceneLight((0.3, -0.5, -0.8), (0.9, 0.8, 0.7), (0.2, 0.2, 0.3), 0.7)
    body = _facing_tri(600.0, 1, (0.0, -0.6, -0.8))
    sphere = BodyGeometry(
        np.array([[300.0, 0.0, 700.0]], np.float32), np.array([[0.0, 0.0, -1.0]], np.float32),
        np.zeros((0, 3), np.int32), np.zeros(0, np.uint8),
        np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), ((0, 120.0, 2),),
        np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))
    actors = (_standing_actor(0, body, 400.0), _standing_actor(1, sphere, 400.0))
    return FrameDescription(_view(), ImageAsset(np.full((200, 320, 3), 40, np.uint8), False),
                            _palette(), actors, (), light)


GOLDEN = pathlib.Path(__file__).parent / "golden" / "scene_lit_classic.npy"


def test_classic_realism_matches_the_pre_materials_golden(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene", msaa=0, realism="classic"))
    backend.draw(_golden_frame())
    out = backend.read_rgb()
    backend.release()
    assert GOLDEN.is_file(), f"{GOLDEN} is missing: the realism=classic identity net is disarmed"
    assert np.array_equal(out, np.load(GOLDEN))


def test_fixed_lighting_is_unchanged_by_the_scene_light(gl_ctx):
    # The regression net: with lighting="fixed" the frame's light is ignored
    # entirely, so a wild SceneLight cannot move a single pixel.
    options = RenderOptions(scale=1, shading="smooth", lighting="fixed")
    backend = GLBackend(gl_ctx, options)
    actor = _actor(0, _facing_tri(600.0, 1, (0.0, 0.0, -1.0)))
    backend.draw(_frame([actor]))
    plain = backend.read_rgb().copy()
    backend.draw(_lit_frame([actor], (0.9, -0.3, -0.3)))
    assert np.array_equal(backend.read_rgb(), plain)
    backend.release()


def test_scene_lighting_gives_a_face_a_lit_and_a_dark_side(gl_ctx):
    # What abs(dot(N, L)) could never do: two faces with opposite normals
    # under one light must not come out the same brightness.
    options = RenderOptions(scale=1, shading="smooth", lighting="scene")
    backend = GLBackend(gl_ctx, options)
    toward = _lit_frame([_actor(0, _facing_tri(600.0, 1, (0.0, -1.0, 0.0)))], (0.0, -1.0, 0.0))
    away = _lit_frame([_actor(0, _facing_tri(600.0, 1, (0.0, 1.0, 0.0)))], (0.0, -1.0, 0.0))
    backend.draw(toward)
    lit = backend.read_rgb().astype(int).max()
    backend.draw(away)
    dark = backend.read_rgb().astype(int).max()
    assert lit > dark + 20
    backend.release()


def test_scene_lighting_never_goes_below_the_rooms_ambient(gl_ctx):
    # The dark side falls to the room's fill light, not to black: an actor
    # in shadow is still visible against the plate.
    options = RenderOptions(scale=1, shading="smooth", lighting="scene")
    backend = GLBackend(gl_ctx, options)
    away = _lit_frame([_actor(0, _facing_tri(600.0, 1, (0.0, 1.0, 0.0)))], (0.0, -1.0, 0.0))
    backend.draw(away)
    assert backend.read_rgb().astype(int).max() > 0
    backend.release()


def _table_of(name):
    from PyAitD.render.materials import parse_table
    return parse_table({"ramps": [{"lo": 0, "hi": 255, "class": name}]})


def _material_actor(index, geometry, table, feet_y=400.0):
    zv = (0, 0, feet_y - 200, feet_y, 0, 0)
    return ActorDraw(index, geometry, (0.0, 0.0, 0.0), 0, zv, RenderResult([], []), (), table)


def _enhanced_backend(gl_ctx):
    return GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene", msaa=0, realism="enhanced"))


def _centre(rgb):
    # _facing_tri projects to the upper-left half of the 80..240 x 20..180
    # square (its hypotenuse is x + y = 260); (130, 80) is well inside it.
    return rgb[80, 130].astype(int)


def test_classic_ignores_the_material_table(gl_ctx):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene", msaa=0, realism="classic"))
    tri = _facing_tri(600.0, 1, (0.0, 0.0, -1.0))
    backend.draw(_lit_frame([_material_actor(0, tri, _table_of("metal"))], (0.0, 0.0, -1.0)))
    metal = backend.read_rgb().copy()
    backend.draw(_lit_frame([_material_actor(0, tri, _table_of("matte"))], (0.0, 0.0, -1.0)))
    assert np.array_equal(backend.read_rgb(), metal)
    backend.release()


def test_metal_is_brighter_than_matte_under_enhanced(gl_ctx):
    # n = l = view = the half-vector: the highlight lands dead centre.
    backend = _enhanced_backend(gl_ctx)
    tri = _facing_tri(600.0, 1, (0.0, 0.0, -1.0))
    backend.draw(_lit_frame([_material_actor(0, tri, _table_of("matte"))], (0.0, 0.0, -1.0)))
    matte = _centre(backend.read_rgb())
    backend.draw(_lit_frame([_material_actor(0, tri, _table_of("metal"))], (0.0, 0.0, -1.0)))
    metal = _centre(backend.read_rgb())
    assert metal.sum() > matte.sum() + 30
    backend.release()


def test_rim_brightens_the_silhouette_edge_not_the_centre(gl_ctx, monkeypatch):
    from PyAitD.render import materials
    monkeypatch.setitem(materials.CLASS_PRESETS, "glass", materials.Material(1.0, 0.0, 0.0, 1.0, 0.0, 1.0, 0))
    sphere = BodyGeometry(
        np.array([[0.0, 0.0, 600.0]], np.float32), np.array([[0.0, 0.0, -1.0]], np.float32),
        np.zeros((0, 3), np.int32), np.zeros(0, np.uint8),
        np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), ((0, 300.0, 1),),
        np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))
    backend = _enhanced_backend(gl_ctx)
    backend.draw(_lit_frame([_material_actor(0, sphere, _table_of("matte"))], (0.0, 0.0, -1.0)))
    plain = backend.read_rgb().astype(int)
    backend.draw(_lit_frame([_material_actor(0, sphere, _table_of("glass"))], (0.0, 0.0, -1.0)))
    rimmed = backend.read_rgb().astype(int)
    backend.release()
    # sphere radius 300 at depth 1600 with focal 320 -> ~60 px on screen
    edge = (100, 160 + 55)
    assert rimmed[edge].sum() > plain[edge].sum() + 30
    assert abs(rimmed[100, 160].sum() - plain[100, 160].sum()) <= 6


def test_detail_varies_across_a_flat_face_only_under_enhanced(gl_ctx, monkeypatch):
    from PyAitD.render import materials
    monkeypatch.setitem(materials.CLASS_PRESETS, "wood", materials.Material(1.0, 0.0, 0.0, 0.0, 1.0, 50.0, 1))
    tri = _facing_tri(600.0, 1, (0.0, 0.0, -1.0))
    frame = _lit_frame([_material_actor(0, tri, _table_of("wood"))], (0.0, 0.0, -1.0))
    backend = _enhanced_backend(gl_ctx)
    backend.draw(frame)
    grained = backend.read_rgb()[60:100, 100:150, 0].astype(int)   # inside the triangle
    backend.release()
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene", msaa=0, realism="classic"))
    backend.draw(frame)
    flat = backend.read_rgb()[60:100, 100:150, 0].astype(int)
    backend.release()
    assert grained.std() > 2.0
    assert flat.std() == 0.0


def test_occluded_vertices_are_darker_under_enhanced(gl_ctx):
    base = _facing_tri(600.0, 1, (0.0, 0.0, -1.0))
    shut = BodyGeometry(base.vertices, base.normals, base.tris, base.tri_colors, base.lines, base.line_colors,
                        base.spheres, base.points, base.point_sizes, base.point_colors,
                        base.rest, np.zeros(3, np.float32))
    backend = _enhanced_backend(gl_ctx)
    backend.draw(_lit_frame([_material_actor(0, base, _table_of("matte"))], (0.0, 0.0, -1.0)))
    open_ = _centre(backend.read_rgb())
    backend.draw(_lit_frame([_material_actor(0, shut, _table_of("matte"))], (0.0, 0.0, -1.0)))
    closed = _centre(backend.read_rgb())
    backend.release()
    assert closed.sum() < open_.sum() - 30


def test_contact_darkens_toward_the_feet_under_enhanced(gl_ctx):
    # feet at y=400 (the zv lower bound); the triangle spans y in -400..400,
    # so its bottom rows sit at the plane and its top rows are far above it.
    tri = _facing_tri(600.0, 1, (0.0, 0.0, -1.0))
    backend = _enhanced_backend(gl_ctx)
    backend.draw(_lit_frame([_material_actor(0, tri, _table_of("matte"), feet_y=400.0)], (0.0, 0.0, -1.0)))
    rgb = backend.read_rgb().astype(int)
    backend.release()
    # (120, 60) is high on the face (world y = -200, above contact_height:
    # no darkening); (85, 170) is 50 world units above the feet (world y =
    # 350), inside the hypotenuse x + y < 260, and inside the contact fade.
    top, bottom = rgb[60, 120], rgb[170, 85]
    assert bottom.sum() < top.sum() - 20
