# SPDX-License-Identifier: GPL-2.0-only
import math
import pathlib

import moderngl
import numpy as np
import pytest

from PyAitD.engine.data.formats import Body, Primitive
from PyAitD.render.asset_resolver import ImageAsset
from PyAitD.render.geometry import BodyGeometry
from PyAitD.engine.data.mask_geometry import MaskDraw
from PyAitD.render.render_gl import GLBackend, camera_matrix, projection_matrix, view_matrix
from PyAitD.render.render_options import RenderOptions
from PyAitD.render.scene import ActorDraw, CameraView, FrameDescription
from PyAitD.engine.actor.skel import RenderResult
from PyAitD.engine.space.world import CameraState

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


def _plain_background(gl_ctx, plate, shadows="soft"):
    """The same plate with no actors at all: the baseline a shadow darkens.

    `shadows` cannot change what this renders -- an actor-less frame casts
    nothing under either mode -- but a caller that compares a shadowed
    frame against this one byte for byte passes its own mode through, so
    the two backends differ in nothing at all."""
    empty = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene", shadows=shadows))
    empty.draw(FrameDescription(_view(), ImageAsset(plate, False), _palette(), (), ()))
    out = empty.read_rgb().astype(int)
    empty.release()
    return out


def _standing_actor(index, geometry, feet_y):
    zv = (0, 0, feet_y - 200, feet_y, 0, 0)
    return ActorDraw(index, geometry, (0.0, 0.0, 0.0), 0, zv, RenderResult([], []), ())


# `shadows` is required, never defaulted. The option's default has already
# moved once (hard -> soft), and while this helper inherited it, every test
# built on it silently left the hard path: neither `_rasterize_shadow` nor
# `_rasterize_shadow_tessellated` ran anywhere in this file, and deleting
# the `_shadow_fbo.clear()` from both left the whole file green. So callers
# name the pipeline they mean, and the properties below -- which hold under
# either -- are parametrized over both.
def _lit_scene_backend(gl_ctx, shadows):
    return GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene", shadows=shadows))


@pytest.mark.parametrize("shadows", ["hard", "soft"])
def test_a_shadow_darkens_the_ground_below_the_actor_only(gl_ctx, shadows):
    backend = _lit_scene_backend(gl_ctx, shadows)
    plate = np.full((200, 320, 3), 200, np.uint8)
    geometry = _tri_geometry(600.0, 1, span=100.0)
    actor = _standing_actor(0, geometry, feet_y=150)
    light = _scene_light((0.0, -1.0, -0.2))
    frame = FrameDescription(_view(), ImageAsset(plate, False), _palette(), (actor,), (), light)
    backend.draw(frame)
    rendered = backend.read_rgb().astype(int)
    plain = _plain_background(gl_ctx, plate, shadows)
    # somewhere below the actor's feet the plate got darker...
    assert (rendered[120:, :] < plain[120:, :] - 5).any()
    # ...and nothing above the top of the frame did
    assert (rendered[:5, :] >= plain[:5, :] - 1).all()
    backend.release()


@pytest.mark.parametrize("shadows", ["hard", "soft"])
def test_overlapping_shadow_triangles_darken_a_pixel_once(gl_ctx, shadows):
    # Coverage never stacks: two limbs crossing must not darken into a
    # black blob. This is the whole reason both passes go through a
    # texture -- hard writes binary coverage, soft MAX-blends it -- rather
    # than compositing each triangle straight onto the plate.
    backend = _lit_scene_backend(gl_ctx, shadows)
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


@pytest.mark.parametrize("shadows", ["hard", "soft"])
def test_a_foreground_mask_erases_the_shadow_under_it(gl_ctx, shadows):
    backend = _lit_scene_backend(gl_ctx, shadows)
    plate = np.full((200, 320, 3), 200, np.uint8)
    actor = _standing_actor(0, _tri_geometry(600.0, 1, span=100.0), feet_y=150)
    masked = ActorDraw(actor.index, actor.geometry, actor.position, actor.room, actor.zv,
                       actor.logical, (0,))
    full = MaskDraw(0, (np.array([[0, 0], [320, 0], [320, 200], [0, 200]], np.int16),),
                    (0, 0, 320, 200), 0, ())
    light = _scene_light((0.0, -1.0, -0.2))
    frame = FrameDescription(_view(), ImageAsset(plate, False), _palette(), (masked,), (full,), light)
    backend.draw(frame)
    assert np.array_equal(backend.read_rgb(), _plain_background(gl_ctx, plate, shadows))
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
    # pinned under shadows="hard": the centroid tolerance below is tight
    # enough that soft's penumbra shifts it past the bound on its own.
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene", shadows="hard"))
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


@pytest.mark.parametrize("shadows", ["hard", "soft"])
def test_a_triangle_less_actor_leaves_no_shadow_and_does_not_disturb_another_actors(gl_ctx, shadows):
    """Smoke case only -- see test_two_different_casters_do_not_share_leftover_shadow_coverage
    below for the test that actually pins the per-actor coverage reset.
    Because a triangle-less actor never composites at all (under `hard`,
    `if scene_lit and self._rasterize_shadow(...)` short-circuits for it;
    under `soft`, `_gather_shadows` skips it on `inst is None`), pairing
    one with a real caster is a no-op by construction: it cannot fail
    whether or not the shadow texture is reset between actors, so it does
    NOT pin the reset, the guard's position relative to the clear, or
    painter order. What it does verify is narrower: a triangle-less actor
    renders nothing of its own and does not change the caster's own
    output, regardless of draw order. Its `hard` case is also the only
    test in this file that reaches the `if not len(geometry.tris): return
    False` guard's return path at all -- the soft path has no such guard,
    so the `soft` case does not stand in for it."""
    backend = _lit_scene_backend(gl_ctx, shadows)
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


@pytest.mark.parametrize("smoothing", [0, 2])
def test_two_different_casters_do_not_share_leftover_shadow_coverage(gl_ctx, smoothing):
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

    `hard` only, and deliberately: the per-actor reset it pins exists only
    on that path. Under `soft` there is no per-actor clear to break --
    `_gather_shadows` clears the coverage texture once per frame and
    MAX-blends every actor into it on purpose, so an actor inheriting the
    previous one's coverage is the intended behaviour there, not the bug.
    Both rasterisers' clears are covered: level 0 goes through
    `_rasterize_shadow` and level 2 through `_rasterize_shadow_tessellated`.

    Measured on this implementation: removing the `_shadow_fbo.clear()` in
    `_rasterize_shadow` turns 0 differing pixels in the annulus (7058 of
    them) into 160, and removing the one in `_rasterize_shadow_tessellated`
    turns 0 into 159 (of 7057)."""
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
        backend = GLBackend(gl_ctx, RenderOptions(
            scale=1, shading="smooth", lighting="scene", shadows="hard", smoothing=smoothing))
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


def test_draw_leaves_blend_equation_alpha_capable_for_the_ui_composite(gl_ctx):
    """draw()'s postcondition names blend_equation, and Renderer.present() is
    what leans on it: the moment draw() returns, present() composites the
    UI canvas over the scene with SRC_ALPHA/ONE_MINUS_SRC_ALPHA
    (render.py's present(), pinned by test_render.py's
    test_present_gl_path_blends_ui_canvas_alpha_over_the_scene). The
    equation is context state, not per-draw state, and blend factors are
    ignored under MAX -- so a MAX left behind by the gathered cast would
    silently turn every UI overlay into a componentwise max of canvas and
    scene, blowing it out to white wherever the canvas is bright.

    So: draw a frame, then blend a known half-alpha quad over a known
    destination and check the arithmetic, exactly as the present() test
    does. Two frames, because the postcondition is held up by two
    independently removable lines:

      * the frame with a real caster is the hazard end to end -- MAX is
        genuinely set during it, since `_gather_shadows` blends every cast
        with it, so this is the state present() would inherit in the live
        pipeline. Two lines stand between that MAX and the UI composite
        (`_gather_shadows`'s own in-loop reset and draw()'s `finally`), and
        this half holds while either survives;
      * the caster-less frame isolates the `finally`. Nothing in it enters
        the cast loop, so the MAX set here before draw() can only be undone
        there. Delete that one line and this half fails while the half
        above still passes -- which is precisely the gap that let the
        postcondition ship untested.
    """
    dst = (0.4, 0.6, 0.8)
    prog = gl_ctx.program(
        vertex_shader="#version 330\nin vec2 in_pos;\nvoid main() { gl_Position = vec4(in_pos, 0.0, 1.0); }",
        fragment_shader="#version 330\nuniform vec4 src;\nout vec4 f_color;\nvoid main() { f_color = src; }")
    quad = gl_ctx.buffer(np.array([-1, -1, 3, -1, -1, 3], "f4").tobytes())
    vao = gl_ctx.vertex_array(prog, [(quad, "2f", "in_pos")])
    probe_tex = gl_ctx.texture((16, 16), 4)
    probe_fbo = gl_ctx.framebuffer(color_attachments=[probe_tex])
    plate = np.full((200, 320, 3), 200, np.uint8)
    light = _scene_light((0.0, -1.0, -0.2))
    caster = _standing_actor(0, _tri_geometry(600.0, 1, span=100.0), feet_y=150)

    def blend_half_alpha_over_dst():
        """SRC_ALPHA/ONE_MINUS_SRC_ALPHA white at 50% over `dst`, with the
        equation left exactly as draw() returned it."""
        probe_fbo.use()
        gl_ctx.viewport = (0, 0, 16, 16)
        gl_ctx.clear(*dst, 1.0)
        gl_ctx.enable(moderngl.BLEND)
        gl_ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        prog["src"].value = (1.0, 1.0, 1.0, 0.5)
        vao.render(moderngl.TRIANGLES)
        gl_ctx.disable(moderngl.BLEND)
        return np.frombuffer(probe_tex.read(), np.uint8).reshape(16, 16, 4)[8, 8, :3].astype(int)

    # out = src*a + dst*(1-a) = 0.5 + dst/2. Under a leaked MAX the factors
    # are ignored and out = max(src, dst) = (255, 255, 255).
    expected = np.array([round((0.5 + c / 2) * 255) for c in dst])
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene", shadows="soft"))
    try:
        backend.draw(FrameDescription(_view(), ImageAsset(plate, False), _palette(), (caster,), (), light))
        cast_frame = blend_half_alpha_over_dst()
        assert np.abs(cast_frame - expected).max() <= 1, cast_frame

        gl_ctx.blend_equation = moderngl.MAX
        backend.draw(FrameDescription(_view(), ImageAsset(plate, False), _palette(), (), (), light))
        empty_frame = blend_half_alpha_over_dst()
        assert np.abs(empty_frame - expected).max() <= 1, empty_frame
    finally:
        gl_ctx.blend_equation = moderngl.FUNC_ADD
        backend.release()
        probe_fbo.release()
        probe_tex.release()
        vao.release()
        quad.release()
        prog.release()


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


def test_view_matrix_is_camera_matrixs_view_half():
    # `view_matrix` feeds the bump's `dFdx(v_view)`/`dFdy(v_view)` and
    # nothing else, and that consumer cannot detect it being wrong: the
    # distance fade reads `fwidth(nc)` rather than `v_view`, and
    # `k = abs(det) / length(cross(sx, sy))` is invariant to a uniform scale
    # on `v_view`. A transposed rotation or a scale error would tilt or
    # deepen relief on every actor with the whole render suite still green,
    # so the relationship is asserted here instead: recombined with
    # `projection_matrix`, the view half must reproduce `camera_matrix`.
    #
    # The same rotated-camera sweep as the parity test above -- at
    # alpha=beta=gamma=0 `rotation_matrix` is the identity and a transposed
    # rotation block is invisible. `allclose`, not `array_equal`: the two
    # sides group the same products differently and `view_matrix` rounds to
    # float32 before the projection is applied. Measured worst-case
    # discrepancy over these 50 cameras is 2.9e-04 absolute, 7.2e-06
    # relative -- both far inside allclose's default rtol of 1e-05, and both
    # far under what a transposed or rescaled view half produces.
    rng = np.random.default_rng(0)
    for _ in range(50):
        alpha, beta, gamma = (int(v) for v in rng.integers(1, 1024, size=3))
        x, y, z = (int(v) for v in rng.integers(-2000, 2000, size=3))
        view = CameraView(CameraState(alpha, beta, gamma, x, y, z, 1000, 320, 320).angles())
        recombined = projection_matrix(view.state) @ view_matrix(view)
        assert np.allclose(recombined, camera_matrix(view, scale=1))
    # and the mutations it has to catch, on one of those cameras
    view = CameraView(CameraState(300, 700, 120, 50, -90, 400, 1000, 320, 320).angles())
    projection, half = projection_matrix(view.state), view_matrix(view)
    transposed = half.copy()
    transposed[:3, :3] = half[:3, :3].T
    assert not np.allclose(projection @ transposed, camera_matrix(view, scale=1))
    assert not np.allclose(projection @ (half * 1.001), camera_matrix(view, scale=1))


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
    from PyAitD.engine.data.floor import Floor
    from PyAitD.engine.data.mask import create_aitd1_mask
    floor = Floor(data_dir, 0, profile)
    draws = floor.mask_draws(0)
    bitmaps = create_aitd1_mask(floor.camera_raw, floor.camera_data_offsets[0], 0x0C)
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
        "_tess_prog", "_tess_shadow_prog",
        "_shadow_blur_tex", "_shadow_blur_fbo", "_cast_prog", "_blur_prog", "_blur_quad_vao",
        "_shadow_map", "_shadow_map_fbo",
        "_plate_tex", "_plate_fbo", "_actor_tex", "_actor_fbo",
        "_composite_prog", "_composite_vao",
    ):
        resource = getattr(backend, attr)
        assert resource is not None, f"{attr} was never allocated before the failure"
        assert isinstance(resource.mglo, moderngl.InvalidObject), f"{attr} leaked (not released)"
        leak_checked += 1
    assert sorted(backend._subpatch_bufs) == [0, 1, 2, 3]
    for level, buf in backend._subpatch_bufs.items():
        assert isinstance(buf.mglo, moderngl.InvalidObject), f"subpatch buffer {level} leaked"
        leak_checked += 1
    assert leak_checked == 44  # every GL resource __init__ allocates, none skipped
    assert backend._sphere is None
    backend.release()  # must still be safe to call again


def test_a_mid_loop_raise_releases_every_already_built_instance_buffer(gl_ctx, monkeypatch):
    # Task 3 moved every actor's instance buffer to be built up front, all
    # before the per-actor loop runs, so they can outlive the whole frame
    # (a later soft-shadow pass will read every actor's before any body is
    # drawn). That means a raise partway through the per-actor loop must
    # release *every* already-built buffer -- including a later actor's,
    # which was already built even though its own turn in the loop never
    # came -- not just the one actor whose own call raised. This guards
    # against a future edit that narrows the `finally` back to "this
    # actor's buffer only" or moves construction back inside the loop.
    backend = _flat_backend(gl_ctx, level=1)
    geometry = _planned_geometry(_closed_cube_body())
    actors = [_actor(0, geometry), _actor(1, geometry)]
    frame = _frame(actors)

    built = []
    real_buffer = backend._ctx.buffer

    def tracking_buffer(*a, **k):
        buf = real_buffer(*a, **k)
        built.append(buf)
        return buf

    monkeypatch.setattr(backend._ctx, "buffer", tracking_buffer)

    def boom(*_a, **_k):
        raise RuntimeError("mid-loop failure")

    monkeypatch.setattr(backend, "_draw_actor_tessellated", boom)

    with pytest.raises(RuntimeError, match="mid-loop failure"):
        backend.draw(frame)

    assert len(built) == 2, "both actors' instance buffers should be built before the loop, not one"
    for buf in built:
        assert isinstance(buf.mglo, moderngl.InvalidObject), "an already-built instance buffer leaked"
    backend.release()


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
    # smoothing=0, shadows="hard" and integration=0 name the legacy
    # paths explicitly: the golden predates tessellation, the gathered
    # soft-shadow pass and the plate composite.
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene", msaa=0,
                                              realism="classic", smoothing=0, shadows="hard",
                                              integration=0,
                                              # names every roadmap-2 field the identity holds at
                                              motion="tick"))
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
    """A material table that classifies every one of the 256 palette indices
    as `name`: whatever a fixture draws, it draws in that one class."""
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


def test_metal_is_brighter_than_matte_under_enhanced(gl_ctx):
    # n = l = view = the half-vector: the highlight lands dead centre.
    #
    # Two CLASS_PRESETS constants bound this, in opposite directions. The
    # triangle is drawn in palette index 1, a saturated red, whose red
    # channel is already at the ceiling: the specular term is
    # `mix(vec3(1), v_color, metallic)`, so the metallic part of the
    # highlight lands almost entirely on a channel that clamps and
    # contributes nothing measurable. The whole of the margin below comes
    # from the *non*-metallic part, scaled by `metal.specular`. So raising
    # `metal.metallic` toward 1.0 shrinks the measured delta (it fails
    # above ~0.843, measured below) and lowering `metal.specular` shrinks it too --
    # and in both cases the failure would read as if the specular term had
    # broken. It has not; the test simply cannot see a highlight that has
    # been tinted entirely into a clamped channel. Re-tune against a
    # desaturated palette entry before touching either constant.
    #
    # After the Task 5 retune (metal at roughness 0.4 / specular 0.15 /
    # bump 0.08) this fixture's centre pixel is matte (255, 0, 0) vs.
    # metal (255, 20, 20): a margin of 40 against the 30 this assertion
    # requires -- not the 510 an earlier draft of this comment claimed.
    # Sweeping `metal.metallic` alone (specular and roughness held at
    # their shipped values) finds the margin falls in lockstep -- 0.80:40,
    # 0.85:30 (fails), 0.87:26 -- and crosses the 30-margin bound between
    # 0.842 (margin 32, passes) and 0.843 (margin 30, fails). The argument
    # is unchanged -- what is visible is still the non-metallic part, on
    # the two channels red does not clamp -- but the headroom above that
    # crossing from the shipped metallic (0.8) is about 0.04, not the
    # ~0.19 the old ~0.993 figure implied.
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


def _body_of(vertices, polys, color=1):
    return Body(0, (0,) * 6, (), [tuple(int(c) for c in v) for v in vertices], [], [],
                [Primitive(1, 0, color, list(p)) for p in polys])


def _hex_prism_body(z=600.0, radius=200.0, half_height=150.0):
    """An open hexagonal prism around the y axis at depth z, two faces
    square-on to +-x: its flat silhouette is 2 R cos 30 wide, its rounded
    one closer to 2 R."""
    ring = [(round(radius * math.cos(math.radians(30 + 60 * k))), round(z + radius * math.sin(math.radians(30 + 60 * k))))
            for k in range(6)]
    v = [(x, -half_height, zz) for x, zz in ring] + [(x, half_height, zz) for x, zz in ring]
    return _body_of(v, [(k, (k + 1) % 6, 6 + (k + 1) % 6, 6 + k) for k in range(6)])


def _closed_cube_body():
    v = [(-100, -100, -100), (100, -100, -100), (100, 100, -100), (-100, 100, -100),
         (-100, -100, 100), (100, -100, 100), (100, 100, 100), (-100, 100, 100)]
    return _body_of(v, [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (0, 3, 7, 4), (1, 2, 6, 5)])


def _planned_geometry(body):
    from PyAitD.render.geometry import pose_geometry
    from PyAitD.render.refine import plan_refinement
    return pose_geometry(body, [], (0, 0, 0), refinement=plan_refinement(body))


def _flat_backend(gl_ctx, level, scale=1):
    return GLBackend(gl_ctx, RenderOptions(scale=scale, shading="flat", lighting="fixed", msaa=0, smoothing=level))


def _instance_rows(corners, normals, straight, uv=None):
    """(M,51) float32 rows in GLBackend._instance_data's layout -- per corner
    (pos.xyz, ao), (normal.xyz, straight), (rgb, index), rest, uv -- with
    ao=1, black, index 0 and rest 0: only positions, normals, flags and
    (when given) uv matter to the tessellation itself. `uv` is (M,3,2);
    omitted, every corner's uv is 0."""
    m = len(corners)
    if uv is None:
        uv = np.zeros((m, 3, 2))
    parts = []
    for k in range(3):
        parts += [corners[:, k], np.ones((m, 1)), normals[:, k], straight[:, k:k + 1],
                  np.zeros((m, 3)), np.zeros((m, 1)), np.zeros((m, 3)), uv[:, k]]
    return np.concatenate(parts, axis=1).astype("f4")


def _write_if_present(prog, name, matrix):
    try:
        prog[name].write(matrix.tobytes())
    except KeyError:      # a uniform the linker dropped as unused
        pass


def test_tessellation_shader_matches_the_numpy_reference(gl_ctx):
    from PyAitD.render import refine
    from PyAitD.render.lighting import project_to_plane, _clamp_downward
    from PyAitD.render.render_gl import _TESS_VSH, instance_layout
    rng = np.random.default_rng(7)
    corners = rng.uniform(-300.0, 300.0, (4, 3, 3))
    normals = rng.normal(size=(4, 3, 3))
    normals /= np.linalg.norm(normals, axis=2, keepdims=True)
    straight = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 1], [1, 1, 1]], np.float64)
    bary = refine.subpatch(2)
    ref_pos, ref_nrm = refine.evaluate(corners, normals, straight, bary)

    prog = gl_ctx.program(vertex_shader=_TESS_VSH, varyings=["v_world", "v_normal"])
    _write_if_present(prog, "rot", np.eye(3, dtype="f4"))
    _write_if_present(prog, "mvp", np.eye(4, dtype="f4"))
    prog["project"].value = 0
    prog["travel"].value = (0.0, 1.0, 0.0)
    prog["plane_y"].value = 0.0
    bary_buf = gl_ctx.buffer(np.ascontiguousarray(bary, dtype="f4").tobytes())
    inst_buf = gl_ctx.buffer(_instance_rows(corners, normals, straight).tobytes())
    fmt, names = instance_layout(prog)
    vao = gl_ctx.vertex_array(prog, [(bary_buf, "3f", "in_bary"), (inst_buf, fmt, *names)])
    out = gl_ctx.buffer(reserve=len(corners) * len(bary) * 6 * 4)
    vao.transform(out, moderngl.POINTS, vertices=len(bary), instances=len(corners))
    got = np.frombuffer(out.read(), "f4").reshape(len(corners), len(bary), 6)
    assert np.allclose(got[..., :3], ref_pos, atol=0.05)      # 1e-4 of a 600-unit patch
    assert np.allclose(got[..., 3:], ref_nrm, atol=1e-3)

    # The shadow mode is project_to_plane's math for an ALREADY-CLAMPED
    # travel (see _TESS_VSH's comment on the `project` uniform block): the
    # shader itself never tips travel onto the MIN_UP cone, so this proves
    # equivalence only once the uniform actually carries the clamped
    # vector, exactly as render_gl (task 6) will write it. (0.3, 0.8, 0.2)'s
    # unit y is ~0.91, already inside the cone -- its own clamp is a no-op,
    # so on its own it cannot distinguish a clamped shader input from an
    # unclamped one. (1.0, 0.1, 0.0) sits outside the cone (unit y ~0.10 <
    # MIN_UP), so _clamp_downward genuinely changes it, and its case alone
    # pins the precondition: feed the shader the pre-clamped uniform,
    # compare against project_to_plane's *raw* input (which reaches the
    # same clamped vector internally), and they must still agree.
    for travel in ((0.3, 0.8, 0.2), (1.0, 0.1, 0.0)):
        clamped = tuple(float(v) for v in _clamp_downward(travel))
        prog["project"].value = 1
        prog["travel"].value = clamped
        prog["plane_y"].value = 250.0
        vao.transform(out, moderngl.POINTS, vertices=len(bary), instances=len(corners))
        projected = np.frombuffer(out.read(), "f4").reshape(len(corners), len(bary), 6)[..., :3]
        expected = project_to_plane(ref_pos.reshape(-1, 3), travel, 250.0).reshape(ref_pos.shape)
        assert np.allclose(projected, expected, atol=0.05)
    for resource in (vao, out, inst_buf, bary_buf, prog):
        resource.release()


def test_tess_vsh_blends_uv_by_the_same_corner_order_as_position_and_normal(gl_ctx):
    """Round 2 of the task-5 review: a pixel test comparing a painted
    render against a fully unpainted one cannot catch a scrambled corner
    order in TESS_VSH's `v_uv = in_uv0 * u + in_uv1 * v + in_uv2 * w` --
    painting with the wrong corner order still differs from painting
    nothing at all, by the same pixel count as painting it right (verified
    directly: swapping in_uv0/in_uv1 left the painted-vs-plain pixel count
    exactly unchanged at 12793, while it moved 8333 of those 12793 pixels
    relative to the correctly-ordered render -- see task-5-report.md, fix
    round 2). That is a defect in what a before/after pixel comparison can
    see, not something a stronger atlas fixes: no atlas or per-corner uv
    choice changes which pixels a "differs from unpainted" assertion looks
    at.

    This test instead reads v_uv straight off the GPU via transform
    feedback -- the same mechanism
    test_tessellation_shader_matches_the_numpy_reference already uses for
    v_world/v_normal, extended to the third instance-buffer varying this
    task added -- and compares it to the identical barycentric blend
    computed independently in numpy. A scrambled corner order cannot
    survive that: the two blends are different functions of (u, v, w)
    whenever the three corner uv values differ, which random per-corner
    uv guarantees with probability 1."""
    from PyAitD.render import refine
    from PyAitD.render.render_gl import _TESS_VSH, instance_layout
    rng = np.random.default_rng(11)
    corners = rng.uniform(-300.0, 300.0, (4, 3, 3))
    normals = rng.normal(size=(4, 3, 3))
    normals /= np.linalg.norm(normals, axis=2, keepdims=True)
    straight = np.zeros((4, 3))
    uv = rng.uniform(0.0, 1.0, (4, 3, 2))
    bary = refine.subpatch(2)                      # (P,3): u, v, w per subpatch vertex
    expected = np.einsum("ick,pc->ipk", uv, bary)   # same blend TESS_VSH computes for v_uv

    prog = gl_ctx.program(vertex_shader=_TESS_VSH, varyings=["v_uv"])
    _write_if_present(prog, "rot", np.eye(3, dtype="f4"))
    _write_if_present(prog, "mvp", np.eye(4, dtype="f4"))
    prog["project"].value = 0
    prog["travel"].value = (0.0, 1.0, 0.0)
    prog["plane_y"].value = 0.0
    bary_buf = gl_ctx.buffer(np.ascontiguousarray(bary, dtype="f4").tobytes())
    inst_buf = gl_ctx.buffer(_instance_rows(corners, normals, straight, uv).tobytes())
    fmt, names = instance_layout(prog)
    vao = gl_ctx.vertex_array(prog, [(bary_buf, "3f", "in_bary"), (inst_buf, fmt, *names)])
    out = gl_ctx.buffer(reserve=len(corners) * len(bary) * 2 * 4)
    vao.transform(out, moderngl.POINTS, vertices=len(bary), instances=len(corners))
    got = np.frombuffer(out.read(), "f4").reshape(len(corners), len(bary), 2)
    assert np.allclose(got, expected, atol=1e-5)
    for resource in (vao, out, inst_buf, bary_buf, prog):
        resource.release()


def _row_width(rgb, row):
    return int((rgb[row].astype(int).sum(axis=1) > 0).sum())


def test_a_hexagonal_prism_is_wider_at_mid_face_once_rounded(gl_ctx):
    # At scale 4 so the bow shows: PN under-bulges a 60-degree facet (the
    # cubic reaches ~0.06 R past the chord, not the circle's 0.13 R), which
    # is 296 -> 308 px here and only 74 -> 76 px at scale 1.
    geometry = _planned_geometry(_hex_prism_body())
    widths = {}
    for level in (0, 2):
        backend = _flat_backend(gl_ctx, level, scale=4)
        backend.draw(_frame([_actor(0, geometry)]))
        widths[level] = _row_width(backend.read_rgb(), 400)
        backend.release()
    assert widths[0] >= 280                   # ~296 px: 2 R cos 30 at depth 1500, times 4
    assert widths[2] >= widths[0] + 8         # ~308 px: the faces bow out toward the circle


def test_a_creased_cube_renders_the_same_rounded_or_not(gl_ctx):
    # Every cube edge is a 90-degree crease, so each face is a flat PN
    # patch: the sub-triangles tile the original exactly. Sub-vertices on a
    # straight edge are collinear to ~1e-5 px, so a pixel centre that close
    # to an edge can still flip -- hence a tolerance rather than equality.
    geometry = _planned_geometry(_closed_cube_body())
    frames = {}
    for level in (0, 2):
        backend = _flat_backend(gl_ctx, level)
        backend.draw(_frame([_actor(0, geometry)]))
        frames[level] = backend.read_rgb()
        backend.release()
    assert (frames[0].astype(int).sum(axis=2) > 0).sum() > 500     # the cube is really drawn
    assert int(np.any(frames[0] != frames[2], axis=2).sum()) <= 2


def test_a_sphere_gets_rounder_with_smoothing(gl_ctx):
    sphere = BodyGeometry(
        np.array([[0.0, 0.0, 600.0]], np.float32), np.array([[0.0, 0.0, -1.0]], np.float32),
        np.zeros((0, 3), np.int32), np.zeros(0, np.uint8),
        np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), ((0, 300.0, 1),),
        np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))
    counts = {}
    for level in (0, 2):
        backend = _flat_backend(gl_ctx, level)
        backend.draw(_frame([_actor(0, sphere)]))
        counts[level] = int((backend.read_rgb().astype(int).sum(axis=2) > 0).sum())
        backend.release()
    # the level-1 icosphere's silhouette is a ~12-gon inscribed in the disc;
    # PN patches bow it back out toward the circle
    assert counts[2] > counts[0] + 100


def test_smoothing_zero_draws_through_the_legacy_path(gl_ctx, monkeypatch):
    backend = _flat_backend(gl_ctx, 0)
    monkeypatch.setattr(backend, "_render_instanced", lambda *a, **k: (_ for _ in ()).throw(AssertionError("tessellated")))
    backend.draw(_frame([_actor(0, _planned_geometry(_closed_cube_body()))]))
    backend.release()


def test_instance_data_packs_each_corners_own_columns(gl_ctx):
    # Finding 2 (task 5 review): the pixel tests above cannot pin
    # _instance_data's straight-column ordering -- the hex prism's straight
    # is uniformly 0, the cube's patches are planar so edge_point's
    # dot(pj-pi, ni) term vanishes and the chord comes out the same
    # whatever straight says, and the sphere passes np.zeros. A transposed
    # or rolled `geometry.straight[:, :, None]` (or any other column) would
    # pass the entire existing suite. Pin the documented per-corner layout
    # directly instead: per corner k, (pos.xyz, ao), (normal.xyz,
    # straight_k), (rgb, index), rest.xyz, uv.xy -- 17 floats, using a value
    # distinct per corner in every field that varies per corner.
    pos = np.array([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [0.0, 10.0, 0.0]], np.float32)
    normals = np.array([[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]], np.float32)
    straight = np.array([[1.0, 0.0, 1.0]], np.float32)   # distinct per corner: not uniform, not a palindrome
    ao = np.array([0.2, 0.5, 0.9], np.float32)
    rest = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]], np.float32)
    uv = np.array([[[0.1, 0.9], [0.3, 0.7], [0.5, 0.5]]], np.float32)
    geometry = BodyGeometry(
        pos, normals[0], np.array([[0, 1, 2]], np.int32), np.array([2], np.uint8),
        np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), (),
        np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8),
        rest, ao, normals, straight, None, uv)
    palette = _palette().astype("f4") / 255.0
    backend = _flat_backend(gl_ctx, 0)
    row = backend._instance_data(geometry, np.zeros(3, np.float64), palette)[0]
    backend.release()
    for k in range(3):
        block = row[17 * k: 17 * (k + 1)]
        assert np.allclose(block[0:3], pos[k]), f"corner {k} position"
        assert block[3] == pytest.approx(ao[k]), f"corner {k} ao"
        assert np.allclose(block[4:7], normals[0, k]), f"corner {k} normal"
        assert block[7] == pytest.approx(straight[0, k]), f"corner {k} straight"
        assert np.allclose(block[8:11], palette[2]), f"corner {k} colour"
        assert block[11] == pytest.approx(2.0), f"corner {k} palette index"
        assert np.allclose(block[12:15], rest[k]), f"corner {k} rest"
        assert np.allclose(block[15:17], uv[0, k]), f"corner {k} uv"


def test_instance_data_and_triangle_data_agree_column_for_column(gl_ctx):
    # The two carry the same numbers in two shapes -- one row per triangle
    # vs one row per vertex -- and each is pinned on its own, but nothing
    # pinned that they still agree, so either could drift alone. With no
    # refinement corner_normals is exactly normals[tris], which makes the
    # two comparable value for value; the sphere covers the second branch.
    from PyAitD.render.geometry import pose_geometry
    body = _closed_cube_body()
    body.primitives.append(Primitive(3, 0, 5, [0], size=40))
    geometry = pose_geometry(body, [], (0, 0, 0))
    palette = _palette().astype("f4") / 255.0
    position = np.array([3.0, -4.0, 5.0])
    backend = _flat_backend(gl_ctx, 0)
    inst = backend._instance_data(geometry, position, palette)
    tri = backend._triangle_data(geometry, position, palette)
    backend.release()
    assert len(inst) and len(tri) == 3 * len(inst)
    corner = inst.reshape(len(inst), 3, 17)          # pos.xyz, ao, normal.xyz, straight, rgb, index, rest.xyz, uv.xy
    vertex = tri.reshape(len(inst), 3, 16)           # pos.xyz, normal.xyz, rgb, rest.xyz, ao, index, uv.xy
    assert np.allclose(corner[:, :, 0:3], vertex[:, :, 0:3]), "position"
    assert np.allclose(corner[:, :, 3], vertex[:, :, 12]), "ao"
    assert np.allclose(corner[:, :, 4:7], vertex[:, :, 3:6]), "normal"
    assert np.allclose(corner[:, :, 8:11], vertex[:, :, 6:9]), "colour"
    assert np.allclose(corner[:, :, 11], vertex[:, :, 13]), "palette index"
    assert np.allclose(corner[:, :, 12:15], vertex[:, :, 9:12]), "rest"
    assert np.allclose(corner[:, :, 15:17], vertex[:, :, 14:16]), "uv"


def _enhanced_tessellated_backend(gl_ctx, level=2):
    return GLBackend(gl_ctx, RenderOptions(
        scale=2, shading="smooth", lighting="scene", msaa=0, realism="enhanced", smoothing=level))


def test_scene_lit_enhanced_tessellation_shades_a_sphere_nonuniformly(gl_ctx):
    # Finding 3 (task 5 review): every pixel test above runs shading="flat",
    # where _ACTOR_FSH returns the raw palette colour and returns before
    # v_normal, v_ao, v_rest, v_index, plane_y, contact_height or
    # material_tex are ever read on the tessellated path -- so nothing
    # exercised the scene_lit half of _set_frame_uniforms, the tessellated
    # plane_y write, or the ao/rest/index columns of _instance_data. Task 7
    # ships smoothing=2 under exactly shading="smooth"/lighting="scene"/
    # realism="enhanced", so that is the configuration that needs one real
    # picture: a lit sphere, tessellated, must show a genuine range of
    # shading across its surface, not one flat colour.
    sphere = BodyGeometry(
        np.array([[0.0, 0.0, 600.0]], np.float32), np.array([[0.0, 0.0, -1.0]], np.float32),
        np.zeros((0, 3), np.int32), np.zeros(0, np.uint8),
        np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), ((0, 300.0, 1),),
        np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))
    backend = _enhanced_tessellated_backend(gl_ctx)
    actor = _material_actor(0, sphere, _table_of("matte"))
    backend.draw(_lit_frame([actor], (0.3, -0.6, -0.7)))
    rgb = backend.read_rgb().astype(int)
    backend.release()
    lit = rgb[rgb.sum(axis=2) > 0]
    assert len(lit) > 500                  # the sphere is really drawn
    assert lit.std(axis=0).max() > 10      # a real spread of shading, not one flat colour


def _shadow_frame(actor, plate, masks=()):
    # the light sits behind the prism and above it: the shadow falls toward
    # the camera across the ground plane, so it has an area on screen
    # rather than collapsing onto the horizon row
    light = _scene_light((0.0, -0.5, 0.85))
    return FrameDescription(_view(), ImageAsset(plate, False), _palette(), (actor,), tuple(masks), light)


def _darkened_below_the_feet(gl_ctx, level, actor, plate):
    # Pinned under shadows="hard": this helper's callers test the CPU
    # projected-shadow path's tessellation mechanics specifically, and
    # soft's penumbra would blur the exact pixel counts they pin.
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat", lighting="scene", msaa=0,
                                               smoothing=level, shadows="hard"))
    backend.draw(_shadow_frame(actor, plate))
    rendered = backend.read_rgb().astype(int)
    backend.release()
    plain = _plain_background(gl_ctx, plate)
    # rows 137+ are below the prism's nearest foot (row ~134): shadow only
    return int((rendered[137:] < plain[137:] - 5).any(axis=2).sum())


def test_the_tessellated_shadow_is_as_round_as_the_actor(gl_ctx):
    plate = np.full((200, 320, 3), 200, np.uint8)
    actor = _standing_actor(0, _planned_geometry(_hex_prism_body()), feet_y=150)
    flat = _darkened_below_the_feet(gl_ctx, 0, actor, plate)
    rounded = _darkened_below_the_feet(gl_ctx, 2, actor, plate)
    assert flat > 100                     # a real shadow band, ~8 rows x ~69 px
    assert rounded > flat + 40            # ~11 px wider on every row


def test_the_soft_cast_follows_the_tessellated_silhouette_too(gl_ctx):
    # The roundness above is measured on the hard rasteriser. The soft cast
    # projects from the instance buffers instead, so it needs its own
    # witness that smoothing reaches it: the same prism, gathered rather
    # than rasterised, covers more ground rounded than flat (measured 2264
    # against 2028). The margin is smaller than the hard path's because the
    # penumbra blurs both silhouettes outward by the same radius.
    plate = np.full((200, 320, 3), 200, np.uint8)
    actor = _standing_actor(0, _planned_geometry(_hex_prism_body()), feet_y=150)
    plain = _plain_background(gl_ctx, plate)
    below = slice(137, None)
    darkened = []
    for level in (0, 2):
        soft = _soft_frame_render(gl_ctx, "soft", [actor], plate, (0.0, -0.5, 0.85), level=level)
        darkened.append(int((soft[below] < plain[below] - 5).any(axis=2).sum()))
    flat, rounded = darkened
    assert flat > 1000                    # a real gathered shadow band
    assert rounded > flat + 100           # the rounded silhouette casts wider


def test_a_tessellated_shadow_is_still_erased_under_a_mask(gl_ctx):
    # A full-screen mask would erase the actor draw itself (mask_tex is
    # shared by _actor_prog and _tess_prog), so rendered == plain_background
    # would hold even if the shadow pass drew nothing or drew garbage --
    # that version of this test could not fail. Use a partial mask instead,
    # covering only the right half of the shadow's own footprint (measured:
    # for this actor/light, the shadow below the feet -- rows 137-153 --
    # spans columns ~101-216), and assert both halves of the erasure: gone
    # where the mask covers it, still cast where it doesn't.
    plate = np.full((200, 320, 3), 200, np.uint8)
    geometry = _planned_geometry(_hex_prism_body())
    actor = ActorDraw(0, geometry, (0.0, 0.0, 0.0), 0, (0, 0, -50, 150, 0, 0), RenderResult([], []), (0,))
    poly = np.array([[160, 137], [320, 137], [320, 200], [160, 200]], np.int16)
    right_half = MaskDraw(0, (poly,), (160, 137, 320, 200), 0, ())
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat", lighting="scene", msaa=0,
                                               smoothing=2, shadows="hard"))
    backend.draw(_shadow_frame(actor, plate, [right_half]))
    rendered = backend.read_rgb().astype(int)
    backend.release()
    plain = _plain_background(gl_ctx, plate)
    below, right, left = slice(137, None), slice(160, None), slice(0, 160)
    assert np.array_equal(rendered[below, right], plain[below, right])            # masked: shadow erased
    outside = int((rendered[below, left] < plain[below, left] - 5).any(axis=2).sum())
    assert outside > 400                                                          # unmasked: shadow still cast (measured 826)


def test_a_sphere_casts_a_shadow_only_once_tessellated(gl_ctx):
    # The CPU shadow path projects geometry.tris and never saw a sphere
    # primitive; the instance stream carries them, so heads and hands cast
    # shadows under smoothing > 0. Pinned so the change stays deliberate.
    plate = np.full((200, 320, 3), 200, np.uint8)
    sphere = BodyGeometry(
        np.array([[0.0, 0.0, 600.0]], np.float32), np.array([[0.0, 0.0, -1.0]], np.float32),
        np.zeros((0, 3), np.int32), np.zeros(0, np.uint8),
        np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), ((0, 150.0, 1),),
        np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))
    actor = _standing_actor(0, sphere, feet_y=150)
    assert _darkened_below_the_feet(gl_ctx, 0, actor, plate) == 0
    assert _darkened_below_the_feet(gl_ctx, 2, actor, plate) > 50


# ---- soft shadows (roadmap F) ----

# A 200-grey plate under _scene_light (ambient 0.1, contrast 1.0) inside a
# shadow: mix(1, 0.1, shadow_opacity(1.0) = 0.7) * 200 -- measured 74.
FULL_SHADOW_ON_200 = 74


def _soft_frame_render(gl_ctx, shadows, actors, plate, direction, masks=(), level=0, shading="flat",
                       realism="enhanced", palette=None):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading=shading, lighting="scene", msaa=0,
                                              realism=realism, smoothing=level, shadows=shadows))
    backend.draw(FrameDescription(_view(), ImageAsset(plate, False),
                                  _palette() if palette is None else palette,
                                  tuple(actors), tuple(masks), _scene_light(direction)))
    out = backend.read_rgb().astype(int)
    backend.release()
    return out


def _partial_shadow_pixels(rendered, rows):
    """Pixels in `rows` that are darker than the plate but lighter than a full
    shadow: a hard shadow has none (binary coverage), a penumbra has many."""
    green = rendered[rows, :, 1]
    return int(((green > FULL_SHADOW_ON_200 + 2) & (green < 200 - 2)).sum())


def _sphere_at(x, y, z, radius=120.0, color=2):
    return BodyGeometry(np.array([[x, y, z]], np.float32), np.array([[0.0, 0.0, -1.0]], np.float32),
                        np.zeros((0, 3), np.int32), np.zeros(0, np.uint8),
                        np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), ((0, radius, color),),
                        np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))


def _facing_square(z, color, normal, span=400.0):
    v = np.array([[-span, -span, z], [span, -span, z], [-span, span, z], [span, span, z]], np.float32)
    n = np.tile(normal, (4, 1)).astype(np.float32)
    return BodyGeometry(v, n, np.array([[0, 1, 2], [1, 3, 2]], np.int32), np.array([color, color], np.uint8),
                        np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), (),
                        np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))


def test_soft_shadows_have_a_penumbra_and_hard_ones_do_not(gl_ctx):
    plate = np.full((200, 320, 3), 200, np.uint8)
    actor = _standing_actor(0, _planned_geometry(_hex_prism_body()), feet_y=150)
    light = (0.0, -0.5, 0.85)     # _shadow_frame's light: the shadow falls toward the camera, rows 137+
    below = slice(137, 200)
    hard = _soft_frame_render(gl_ctx, "hard", [actor], plate, light)
    soft = _soft_frame_render(gl_ctx, "soft", [actor], plate, light)
    assert _partial_shadow_pixels(hard, below) == 0            # thresholded coverage: all or nothing
    assert _partial_shadow_pixels(soft, below) > 100           # a real penumbra


def _penumbra_width(rendered, row):
    """How many pixels of `row` sit inside a shadow edge: darker than the
    plate, lighter than that same row's darkest pixel. A row's shadow is a
    plateau with a soft edge on each side, so this is the penumbra's width.

    Measured against the row's own floor rather than FULL_SHADOW_ON_200
    deliberately: the blur weights a neighbour by 1 / (2r + 1) and rounds r
    to whole pixels, so at a row where the rounded radius steps the weights
    sum to a little under one and the whole plateau sits a step short of
    full. That is the twin's arithmetic, not an edge, and counting it as
    one would drown the signal this test is after."""
    green = rendered[row, :, 1]
    return int(((green > int(green.min()) + 2) & (green < 198)).sum())


def test_the_penumbra_hardens_toward_the_feet(gl_ctx):
    # An upright flat quad standing on its own plane. Because it has no
    # depth, each row of its ground shadow is cast by exactly one height:
    # the row at its feet by the bottom edge (drop 0, a radius well under a
    # pixel) and the furthest row by the top edge, 400 units up, whose
    # radius saturates at R_MAX. So a row's edge width *is* that height's
    # penumbra, and it must grow with the drop. The ratio is the claim; the
    # counts are this geometry's (measured 5.2 near the feet, 20.3 far, at
    # R_MAX_PER_SCALE=4; see docs/soft-shadows-proof.md).
    #
    # The flat quad isolates one drop per row, which is what makes the
    # numbers above readable as a single height's penumbra. A solid caster
    # mixes many drops into every row and is the harder case; it has its
    # own test in test_a_solid_caster_hardens_under_its_own_feet.
    plate = np.full((200, 320, 3), 200, np.uint8)
    actor = _standing_actor(0, _facing_square(600.0, 1, (0.0, 0.0, -1.0), span=200.0), feet_y=200)
    soft = _soft_frame_render(gl_ctx, "soft", [actor], plate, (0.0, -0.5, 0.85))
    hard = _soft_frame_render(gl_ctx, "hard", [actor], plate, (0.0, -0.5, 0.85))
    near_feet = sum(_penumbra_width(soft, row) for row in range(140, 145)) / 5.0
    far_from_them = sum(_penumbra_width(soft, row) for row in range(156, 162)) / 6.0
    assert near_feet > 0                                    # a penumbra even at the feet, just a narrow one
    assert far_from_them > 2.0 * near_feet
    # A row with no shadow at all has no edge either, so the hard arm needs
    # a witness that there is something to be sharp: 3300 of those pixels
    # sit at the full-shadow floor of 74.
    assert (hard[140:170, :, 1] < 100).sum() > 1000
    assert max(_penumbra_width(hard, row) for row in range(140, 170)) == 0   # hard: every edge sharp


def test_a_solid_caster_hardens_under_its_own_feet(gl_ctx):
    # The property the feature is named for, on the caster shape that
    # actually exposes it: a body with depth. Many of the prism's heights
    # project onto the same ground row -- a low point on its far side and a
    # high one on its near side land together -- so the row's radius is
    # whichever of them the cast pass keeps. Keeping the largest leaves the
    # whole shadow uniformly soft; keeping the smallest lets the blocker
    # nearest the ground decide, which is both the physical rule and the
    # contact hardening the option promises.
    #
    # Rows come from the geometry, not from the result: the prism stands at
    # feet_y=150 and its body ends at row 133, so 134 is the first row of
    # ground shadow and 153 is its last. Measured 42.8 at the feet against
    # 109.2 far from them; keeping the largest radius instead gave 74.8
    # against the same 109.2, a ratio of 1.46 that fails the claim below.
    plate = np.full((200, 320, 3), 200, np.uint8)
    actor = _standing_actor(0, _planned_geometry(_hex_prism_body()), feet_y=150)
    soft = _soft_frame_render(gl_ctx, "soft", [actor], plate, (0.0, -0.5, 0.85))
    hard = _soft_frame_render(gl_ctx, "hard", [actor], plate, (0.0, -0.5, 0.85))
    at_the_feet = sum(_penumbra_width(soft, row) for row in range(134, 139)) / 5.0
    far_from_them = sum(_penumbra_width(soft, row) for row in range(149, 154)) / 5.0
    assert at_the_feet > 0                                  # still a penumbra, just a narrow one
    assert far_from_them > 2.0 * at_the_feet
    assert max(_penumbra_width(hard, row) for row in range(134, 154)) == 0   # hard: every edge sharp


def _overlap_frame(with_caster):
    """The golden frame's light over a facing square, with a sphere placed
    so its ground shadow lands on the square's body (measured: 213 pixels
    at smoothing 2). At smoothing 0 the CPU path projects triangles only,
    so this scene is drawn tessellated."""
    from PyAitD.render.lighting import SceneLight
    light = SceneLight((0.3, -0.5, -0.8), (0.9, 0.8, 0.7), (0.2, 0.2, 0.3), 0.7)
    square = _standing_actor(0, _facing_square(600.0, 1, (0.0, -0.6, -0.8)), 400.0)
    caster = _standing_actor(1, _sphere_at(-200.0, -150.0, 500.0), 400.0)
    actors = (square, caster) if with_caster else (square,)
    return FrameDescription(_view(), ImageAsset(np.full((200, 320, 3), 40, np.uint8), False),
                            _palette(), actors, (), light)


def _render_overlap(gl_ctx, shadows, frame, integration=0):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene", msaa=0,
                                              realism="classic", smoothing=2, shadows=shadows,
                                              integration=integration))
    backend.draw(frame)
    out = backend.read_rgb().astype(int)
    backend.release()
    return out


def test_a_gathered_shadow_never_darkens_an_earlier_actor(gl_ctx):
    # The per-actor composite is a full-target multiply with no depth: a
    # nearer actor's shadow, composited after a farther body was drawn,
    # paints over that body. Gathering every cast before any body is drawn
    # is what `soft` fixes; `hard` keeps the artefact verbatim -- under
    # `integration=0`, which `_render_overlap` now names explicitly.
    # Under `integration=2` the hard casts have to reach the plate layer,
    # so they too run before any body and the artefact goes with them; the
    # last assertion below pins that difference rather than leaving it to
    # the proof document.
    square_only = _overlap_frame(False)
    caster_only = FrameDescription(square_only.camera, square_only.background, square_only.palette,
                                   (_overlap_frame(True).actors[1],), (), square_only.light)
    solo_hard, paired_hard = _render_overlap(gl_ctx, "hard", square_only), _render_overlap(gl_ctx, "hard", _overlap_frame(True))
    solo_soft, paired_soft = _render_overlap(gl_ctx, "soft", square_only), _render_overlap(gl_ctx, "soft", _overlap_frame(True))
    sphere = _render_overlap(gl_ctx, "hard", caster_only)
    body = (solo_hard[..., 1] == 0) & (solo_hard[..., 0] > 0)          # the red square's own pixels...
    body &= ~((sphere[..., 0] == 0) & (sphere[..., 1] > 0))            # ...minus where the green sphere is drawn over it
    # ...and only below row 130: the sphere sits between the light and the
    # square, so from Task 5 on it *legitimately* shadows the square through
    # the depth map around screen (113, 83), rows 57-109. The composite
    # artefact this test is about lands at rows 149-158.
    body[:130] = False
    assert body.sum() > 5000
    wrong = np.any(paired_hard != solo_hard, axis=2) & body
    assert wrong.sum() > 100                                           # hard: the sphere's shadow lands on the square
    assert np.array_equal(paired_soft[body], solo_soft[body])          # soft: the body is untouched
    # hard + integration=2: the casts run ahead of the bodies too, so the
    # artefact is gone here as well. Deliberate, and a behaviour difference
    # from `off` -- see docs/plate-integration-proof.md's known limitations.
    solo_on = _render_overlap(gl_ctx, "hard", square_only, integration=2)
    paired_on = _render_overlap(gl_ctx, "hard", _overlap_frame(True), integration=2)
    assert np.array_equal(paired_on[body], solo_on[body])


def test_two_soft_casters_darken_a_pixel_once(gl_ctx):
    # Overlapping casts blend with MAX, so two shadows on one pixel are one.
    plate = np.full((200, 320, 3), 200, np.uint8)
    geometry = _tri_geometry(600.0, 1, span=100.0)
    one = [_standing_actor(0, geometry, feet_y=150)]
    two = one + [_standing_actor(1, geometry, feet_y=150)]
    assert np.array_equal(_soft_frame_render(gl_ctx, "soft", one, plate, (0.0, -1.0, -0.2)),
                          _soft_frame_render(gl_ctx, "soft", two, plate, (0.0, -1.0, -0.2)))


def test_a_mask_erases_a_soft_cast_beyond_its_penumbra(gl_ctx):
    # The mask discard moved from the composite into the cast, so the
    # coverage texture is already erased where the pillar stands -- and the
    # blur runs afterwards, so a penumbra can bleed up to R_MAX pixels past
    # the mask's edge (the spec's first limitation). Beyond that band the
    # masked half must be the untouched plate.
    plate = np.full((200, 320, 3), 200, np.uint8)
    geometry = _planned_geometry(_hex_prism_body())
    actor = ActorDraw(0, geometry, (0.0, 0.0, 0.0), 0, (0, 0, -50, 150, 0, 0), RenderResult([], []), (0,))
    poly = np.array([[160, 137], [320, 137], [320, 200], [160, 200]], np.int16)
    right_half = MaskDraw(0, (poly,), (160, 137, 320, 200), 0, ())
    rendered = _soft_frame_render(gl_ctx, "soft", [actor], plate, (0.0, -0.5, 0.85), masks=[right_half], level=2)
    plain = _plain_background(gl_ctx, plate)
    r_max = 4                                       # R_MAX_PER_SCALE at scale 1
    inside = (slice(137 + r_max, None), slice(160 + r_max, None))
    assert np.array_equal(rendered[inside], plain[inside])
    unmasked = int((rendered[137:, :160] < plain[137:, :160] - 5).any(axis=2).sum())
    assert unmasked > 300                           # still cast where the mask does not reach


def test_a_mask_erases_only_its_own_actors_cast(gl_ctx):
    # One coverage texture holds every actor's cast, so the mask discard
    # has to remove the fragments of the actor it belongs to and nothing
    # else. Two actors stand in the same place, casting the same shadow;
    # only the second carries the mask, and it is cast second, so a mask
    # that cleared the shared texture rather than discarding its own
    # fragments would wipe the first actor's coverage along with its own.
    plate = np.full((200, 320, 3), 200, np.uint8)
    geometry = _planned_geometry(_hex_prism_body())
    zv = (0, 0, -50, 150, 0, 0)
    poly = np.array([[160, 137], [320, 137], [320, 200], [160, 200]], np.int16)
    right_half = MaskDraw(0, (poly,), (160, 137, 320, 200), 0, ())
    masked = ActorDraw(1, geometry, (0.0, 0.0, 0.0), 0, zv, RenderResult([], []), (0,))
    plain_actor = ActorDraw(0, geometry, (0.0, 0.0, 0.0), 0, zv, RenderResult([], []), ())
    plain = _plain_background(gl_ctx, plate)
    r_max = 4                                       # R_MAX_PER_SCALE at scale 1
    beyond = (slice(137 + r_max, None), slice(160 + r_max, None))

    alone = _soft_frame_render(gl_ctx, "soft", [masked], plate, (0.0, -0.5, 0.85),
                               masks=[right_half], level=2)
    assert np.array_equal(alone[beyond], plain[beyond])          # its own cast: erased
    together = _soft_frame_render(gl_ctx, "soft", [plain_actor, masked], plate, (0.0, -0.5, 0.85),
                                  masks=[right_half], level=2)
    survives = int((together[beyond] < plain[beyond] - 5).any(axis=2).sum())
    assert survives > 300                                        # the other actor's: untouched


def test_soft_with_only_a_geometry_less_actor_renders_the_plain_plate(gl_ctx):
    # The triangle-less pairing test always has a real caster beside it, so
    # a frame whose only actor has no geometry is unreached: this is that
    # frame, and it must come out as the untouched plate at every level.
    #
    # It pins the output, not the short-circuit. `_gather_shadows` leaves
    # `cast` False here and skips the blur and the composite, but running
    # them anyway is invisible -- an empty coverage texture composites to
    # no change -- so replacing `if cast:` with `if True:` keeps this green.
    # The guard is a cost saving; what must never change is the plate.
    plate = np.full((200, 320, 3), 200, np.uint8)
    empty = BodyGeometry(np.zeros((0, 3), np.float32), np.zeros((0, 3), np.float32),
                         np.zeros((0, 3), np.int32), np.zeros(0, np.uint8),
                         np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), (),
                         np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))
    for level in (0, 2):
        rendered = _soft_frame_render(gl_ctx, "soft", [_standing_actor(0, empty, feet_y=150)],
                                      plate, (0.0, -0.5, 0.85), level=level)
        assert np.array_equal(rendered, _plain_background(gl_ctx, plate))


def test_the_soft_blur_matches_the_numpy_twin(gl_ctx):
    from PyAitD.render.lighting import soften
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="flat", lighting="scene", msaa=0, shadows="soft"))
    r_max = backend._r_max()
    assert r_max == 4                               # R_MAX_PER_SCALE at scale 1
    rng = np.random.default_rng(11)
    cover = (rng.random((200, 320)) < 0.02).astype(np.float64)
    radius = np.where(cover > 0, rng.integers(0, r_max + 1, (200, 320)), 0).astype(np.float64)
    rg = np.zeros((200, 320, 2), np.uint8)
    rg[..., 0] = (cover * 255).astype(np.uint8)
    # G holds 1 - r / r_max, the encoding the cast pass writes so that MAX
    # blending keeps the smallest radius; the blur decodes it on the way in
    # and re-encodes on the way out. `soften` takes the plain radius, so
    # only this upload and the shader share the complement.
    rg[..., 1] = np.round((1.0 - radius / r_max) * 255).astype(np.uint8)
    backend._shadow_tex.write(np.ascontiguousarray(rg).tobytes())
    backend._soften_shadows()
    out = np.frombuffer(backend._shadow_tex.read(), np.uint8).reshape(200, 320, 2)[..., 0] / 255.0
    backend.release()
    expected = soften(cover, radius, r_max)
    # the intermediate pass is stored in 8 bits and so is the result: half a
    # step each, plus the twin's own rounding
    assert np.abs(out - expected).max() <= 2.5 / 255


def test_soft_with_nothing_to_shadow_is_byte_identical_to_hard(gl_ctx):
    # The spec's second identity: soft's plumbing -- the up-front instance
    # buffers, the gathered pass, the blur, the fractional composite (and,
    # from Task 5, the shadow-map lookup at visibility 1.0) -- changes no
    # pixel when there is nothing to shadow. A mask starting below the body
    # (rows 80-120) erases the ground shadow (rows 143-150) at the cast,
    # and nothing occludes the body.
    plate = np.full((200, 320, 3), 40, np.uint8)
    actor = ActorDraw(0, _tri_geometry(600.0, 1, span=100.0), (0.0, 0.0, 0.0), 0, (0, 0, 100, 300, 0, 0),
                      RenderResult([], []), (0,))
    poly = np.array([[0, 125], [320, 125], [320, 200], [0, 200]], np.int16)
    ground = MaskDraw(0, (poly,), (0, 125, 320, 200), 0, ())
    for level in (0, 2):
        hard = _soft_frame_render(gl_ctx, "hard", [actor], plate, (0.3, -0.5, -0.8), masks=[ground], level=level, shading="smooth")
        soft = _soft_frame_render(gl_ctx, "soft", [actor], plate, (0.3, -0.5, -0.8), masks=[ground], level=level, shading="smooth")
        assert np.any(hard != 40), level          # the body is really drawn
        assert np.array_equal(hard, soft), level


def test_fixed_lighting_ignores_the_shadows_option(gl_ctx):
    frame = _overlap_frame(True)
    outs = []
    for shadows in ("hard", "soft"):
        backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="fixed", msaa=0,
                                                  smoothing=0, shadows=shadows))
        backend.draw(frame)
        outs.append(backend.read_rgb().copy())
        backend.release()
    assert np.array_equal(*outs)


def test_a_sphere_casts_a_soft_shadow_even_on_the_flat_mesh(gl_ctx):
    # Under hard, level 0 projects geometry.tris on the CPU and a sphere has
    # none; soft always casts from the instance stream, spheres included.
    plate = np.full((200, 320, 3), 200, np.uint8)
    actor = _standing_actor(0, _sphere_at(0.0, 0.0, 600.0, radius=150.0, color=1), feet_y=150)
    plain = _plain_background(gl_ctx, plate)
    hard = _soft_frame_render(gl_ctx, "hard", [actor], plate, (0.0, -0.5, 0.85))
    soft = _soft_frame_render(gl_ctx, "soft", [actor], plate, (0.0, -0.5, 0.85))
    assert int((hard[137:] < plain[137:] - 5).any(axis=2).sum()) == 0
    assert int((soft[137:] < plain[137:] - 5).any(axis=2).sum()) > 50


def test_world_box_encloses_vertices_and_spheres():
    from PyAitD.render.render_gl import _world_box
    # Both contributors have to show in the answer, so the fixture puts a
    # vertex outside the sphere's extent on every axis: with the sphere
    # alone the box would be 105..115 / 15..25 / 25..35, and with the
    # vertices alone 110..140 / 20..60 / 30..80. Each bound below comes
    # from one or the other, so dropping either contributor moves one.
    geometry = BodyGeometry(np.array([[10.0, 20.0, 30.0], [40.0, 60.0, 80.0]], np.float32),
                            np.tile((0.0, 0.0, -1.0), (2, 1)).astype(np.float32),
                            np.zeros((0, 3), np.int32), np.zeros(0, np.uint8),
                            np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), ((0, 5.0, 2),),
                            np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))
    actor = ActorDraw(0, geometry, (100.0, 0.0, 0.0), 0, (0,) * 6, RenderResult([], []), ())
    corners = np.array(_world_box(actor))
    assert corners.shape == (8, 3)
    assert corners.min(axis=0).tolist() == [105.0, 15.0, 25.0]      # the sphere's low side
    assert corners.max(axis=0).tolist() == [140.0, 60.0, 80.0]      # the far vertex


def test_an_occluder_shadows_the_key_share_of_a_receiver_only_under_soft(gl_ctx):
    # A small triangle held between the light and a big facing one, off to
    # the side so its shadow (measured: screen x 129-145, y 91-115) lands
    # on the receiver away from its own footprint (x 175-194, y 36-66).
    receiver = _standing_actor(0, _facing_tri(600.0, 1, (0.0, 0.0, -1.0)), 400.0)
    occluder_geometry = BodyGeometry(
        np.array([[60.0, -260.0, 300.0], [140.0, -260.0, 300.0], [60.0, -140.0, 300.0]], np.float32),
        np.tile([0.0, 0.0, -1.0], (3, 1)).astype(np.float32),
        np.array([[0, 1, 2]], np.int32), np.array([1], np.uint8),
        np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), (),
        np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))
    occluder = _standing_actor(1, occluder_geometry, 400.0)
    direction = (0.5, -0.5, -0.7)

    def window(shadows, actors):
        backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene", msaa=0,
                                                  realism="classic", smoothing=0, shadows=shadows))
        backend.draw(_lit_frame(actors, direction))
        out = backend.read_rgb().astype(int)[98:106, 132:142]     # inside the occluder's shadow on the receiver
        backend.release()
        return out

    lit_red = int(window("soft", [receiver])[..., 0].mean())
    dark_red = int(window("soft", [receiver, occluder])[..., 0].mean())
    assert dark_red < lit_red - 40                    # the key's share is gone...
    assert dark_red > 30                              # ...and the fill's is not: never black
    assert np.array_equal(window("hard", [receiver, occluder]), window("hard", [receiver]))   # hard never self-shadows


def test_hard_shadows_never_touch_the_shadow_map(gl_ctx, monkeypatch):
    backend = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="scene", msaa=0,
                                              smoothing=2, shadows="hard"))

    def boom(*_a, **_k):
        raise AssertionError("shadow map rendered under shadows=hard")

    monkeypatch.setattr(backend, "_render_shadow_map", boom)
    backend.draw(_overlap_frame(True))
    backend.release()


# ---- derivative bump (materials v2, task 2) ----


KEY_FROM_ABOVE = (0.0, -0.85, -0.5)


def _material_square(gl_ctx, table, z=600.0, realism="enhanced", shading="smooth",
                     normal=(0.0, 0.0, -1.0), palette=None, light=KEY_FROM_ABOVE):
    """A camera-facing square lit by the scene light, with `table` as its
    material table. Returns the rendered frame.

    The key comes from above and in front, not from the shadow tests'
    (0.0, -0.5, 0.85): that direction points *away* from the camera, so it
    backlights a camera-facing square and leaves it standing in its own
    shade. Measured there, the fill supplies 98.6% of the square's
    brightness and `wrapped` is 0.069 -- a surface whose colour barely
    depends on its normal at all, which is the one thing a normal
    perturbation cannot be measured on. A caller that *wants* that -- the
    emissive test, whose whole claim is that the key stops mattering --
    passes its own `light`."""
    plate = np.full((200, 320, 3), 200, np.uint8)
    geometry = _facing_square(z, 1, normal, span=300.0)
    actor = ActorDraw(0, geometry, (0.0, 0.0, 0.0), 0, (0, 0, 0, 200, 0, 0),
                      RenderResult([], []), (), materials=table)
    return _soft_frame_render(gl_ctx, "hard", [actor], plate, light,
                              shading=shading, realism=realism, palette=palette)


def _bump_pair(gl_ctx, name, monkeypatch, **kwargs):
    """The same material class rendered twice, with its bump off and at its
    tabled strength. Everything else -- the grain colour multiply, the
    specular, the rim, the roughness -- is identical between the two
    frames, so the only thing that can separate them is the relief.

    A fresh MaterialTable for each render: _upload_materials caches on the
    table object's identity and reads CLASS_PRESETS at upload time, so
    reusing one table would hand the second frame the first one's
    parameters."""
    import dataclasses

    from PyAitD.render import materials

    tabled = materials.CLASS_PRESETS[name]

    def render(bump):
        monkeypatch.setitem(materials.CLASS_PRESETS, name,
                            dataclasses.replace(tabled, bump=bump))
        return _material_square(gl_ctx, _table_of(name), **kwargs)

    return render(0.0), render(tabled.bump)


def test_bump_is_relief_not_tint(gl_ctx, monkeypatch):
    # The grain multiplies the colour, so it changes a surface's mean
    # brightness. Relief moves light around instead: pixel to pixel it must
    # differ, but the patch's mean luminance must stay put. Both frames
    # carry the same grain, so a mean that moved here would be the bump
    # itself tinting rather than shading.
    body = (slice(70, 130), slice(120, 200))
    flat, relief = _bump_pair(gl_ctx, "stone", monkeypatch)
    flat_patch = flat[body].astype(float)
    relief_patch = relief[body].astype(float)
    assert relief_patch.std() > flat_patch.std() + 1.0          # relief varies
    assert abs(relief_patch.mean() - flat_patch.mean()) < 0.01 * flat_patch.mean()


def test_bump_fades_out_with_distance(gl_ctx, monkeypatch):
    # fwidth of the noise coordinate crosses half a cell as the surface
    # recedes, and `fade` -- 1 - smoothstep(0.25, 0.5, ...) -- takes the
    # perturbation to zero before the relief can alias into shimmer.
    #
    # A fade is a slope, so this measures three distances and not two: an
    # assertion that the bump is visible up close would only repeat
    # test_bump_is_relief_not_tint's first line, on the same class, patch
    # and z. stone's 50-unit cell puts this fixture's sampling rate at
    # (z + 1000) / 16000 cells per pixel, so the ramp's knees are z = 3000
    # (0.25 cells, fade still exactly 1) and z = 7000 (0.5, fade exactly 0),
    # and the three z below straddle it at 0.10, 0.35 and 0.475 cells.
    #
    # One fixed patch at all three: the far square is only ~27 px across, so
    # a patch that grows with the near one would not be comparable -- and
    # what is compared is the bump's own contribution, since a lit red
    # square keeps a patch spread near 79 whatever its normals do.
    core = (slice(95, 105), slice(155, 165))

    def moved(z):
        flat, relief = _bump_pair(gl_ctx, "stone", monkeypatch, z=z)
        return int(np.abs(relief[core].astype(int) - flat[core].astype(int)).max())

    near, mid, far = moved(600.0), moved(4600.0), moved(6600.0)
    assert near > mid > far           # measured 78, 46 and 3 levels
    assert far <= 5                   # and all but gone before half a cell


def test_bump_ramps_out_where_the_shading_normal_lies_in_its_facet(gl_ctx, monkeypatch):
    # det is dot(cross(sx, sy), n), so it passes through zero wherever an
    # authored normal lies in the plane of the facet the pixel covers --
    # which FITD geometry reaches often (_facing_tri(600, 1, (0, -1, 0)) is
    # already one) and which a smoothed normal sweeps through continuously.
    # There `abs(det) * n` vanishes while the height gradient keeps its
    # magnitude, so the perturbed normal degenerates to +-normalize(grad),
    # perpendicular to n. A `det != 0.0` test would be a cliff: measured
    # with one in place, a normal 1e-7 off the plane took the patch's mean
    # from 85.9 to 43.4 and moved pixels by 186 levels. It has to ramp.
    #
    # -tilt, not +tilt: a positive z would trip the `n.z > 0.0` flip above
    # and confound the measurement with a different normal entirely.
    body = (slice(70, 130), slice(120, 200))

    def moved(tilt):
        normal = np.array([0.0, -1.0, -tilt])
        flat, relief = _bump_pair(gl_ctx, "stone", monkeypatch,
                                  normal=tuple(normal / np.linalg.norm(normal)))
        return np.abs(relief[body] - flat[body]).max()

    assert moved(0.0) == 0            # exactly degenerate: no frame to bump against
    # One ULP off it, one pixel in 14400 moves by one level. At tilt 1e-6
    # the two frames' float colours differ by far less than a level, so
    # which of them straddle a rounding boundary depends on the absolute
    # scale of every *other* term: normalising the specular lobe (task 3)
    # rescaled stone's highlight by (5.66 + 8) / 8pi and carried exactly
    # one pixel across one boundary. The cliff this line exists to catch is
    # the 186 levels above, not that, so the bound carries headroom over
    # the measured 1 rather than sitting exactly on it: a second term
    # rescaled the same way would otherwise turn a rounding boundary into a
    # test failure.
    assert moved(1e-6) <= 3           # and no cliff one ULP off it
    assert moved(1e-3) <= 5           # still ramping in
    assert moved(0.5) > 20            # full strength once the normal has a facet


def test_a_streak_material_fades_before_its_cells_go_sub_pixel(gl_ctx, monkeypatch):
    # Every other bump test here uses stone, whose grain samples the noise
    # cell itself -- so its fade read correctly even while `fwidth` measured
    # a coordinate the noise does not sample. streak stretches an axis by 4
    # and brushed by 6, and the fade has to see that stretch or the relief
    # keeps running well past Nyquist. wood's 60-unit cell is 0.33 sampled
    # cells per pixel at z=600 and 0.71 at z=2400: one side of half a cell
    # and the other.
    body = (slice(70, 130), slice(120, 200))
    near_flat, near = _bump_pair(gl_ctx, "wood", monkeypatch, z=600.0)
    far_flat, far = _bump_pair(gl_ctx, "wood", monkeypatch, z=2400.0)
    assert np.abs(near[body] - near_flat[body]).max() > 8      # relief, close up
    # Past half a cell per pixel the fade is exactly 0, so the bump's whole
    # contribution is the zero vector and both frames take the same path
    # through the same branch: equality here, not a bound.
    assert np.array_equal(far, far_flat)


def test_lambert_shading_gets_the_bump_too(gl_ctx, monkeypatch):
    # lambert derives n from gl_FragCoord derivatives; the perturbation is
    # applied after that choice, so it must reach both paths.
    flat, relief = _bump_pair(gl_ctx, "stone", monkeypatch, shading="lambert")
    assert not np.array_equal(flat, relief)


# ---- the sss terminator, emissive, and the normalised specular lobe
# ---- (materials v2, task 3)


def _grey_palette():
    """`_palette()` with index 1 a mid grey instead of a saturated red.

    Two of the three terms below are invisible on that red. SSS_TINT's red
    channel is exactly 1.0, so a warm terminator multiplies (r, 0, 0) by
    (1.0, 0.82, 0.74) and changes nothing at all; and a lit red face
    already reads 255 in the one channel it has, so an emissive surface
    rendering its raw palette colour cannot be told from a shaded one. A
    grey carries all three channels and sits below both rails."""
    palette = _palette()
    palette[1] = (200, 200, 200)
    return palette


def _swept_normal_quad(z=600.0, color=1, span=300.0, columns=48, arc=85.0):
    """A camera-facing quad, `columns` strips wide, whose vertex normals
    turn with x through `arc` degrees either side of the view axis.

    _material_square's flat quad has a single normal, so every fragment on
    it shares one `wrapped` value and the terminator -- the band where
    `wrapped` is 0.5 -- is not in the frame at all. Here the normal turns
    with x, so under _material_sweep's side key `wrapped` is
    0.5 + 0.5 sin(theta): it runs from ~0 at the left edge, through exactly
    0.5 at the centre column, to ~1 at the right. The light/shade boundary
    and both of the sides a terminator term must vanish on are each a
    column of the image.

    arc < 90, so every normal keeps a negative z and none of them trips the
    shader's `n.z > 0.0` flip; the sweep is monotone across the face."""
    xs = np.linspace(-span, span, columns + 1)
    angles = np.radians(np.linspace(-arc, arc, columns + 1))
    vertices, normals = [], []
    for x, theta in zip(xs, angles):
        vertices += [[x, -span, z], [x, span, z]]
        normals += [[math.sin(theta), 0.0, -math.cos(theta)]] * 2
    tris = [t for i in range(columns)
            for t in ([2 * i, 2 * i + 2, 2 * i + 1], [2 * i + 1, 2 * i + 2, 2 * i + 3])]
    return BodyGeometry(np.array(vertices, np.float32), np.array(normals, np.float32),
                        np.array(tris, np.int32), np.full(len(tris), color, np.uint8),
                        np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), (),
                        np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))


# The swept quad projects to rows 40..159, columns 100..219. These are the
# interior of that: the whole face, then the three columns the terminator
# claim is about -- the unlit side, the boundary itself and the lit side.
SWEEP_ROWS = slice(60, 140)
SWEEP_BODY = (SWEEP_ROWS, slice(102, 218))
SWEEP_UNLIT, SWEEP_BAND, SWEEP_LIT = slice(102, 110), slice(156, 164), slice(210, 218)


def _material_sweep(gl_ctx, table, palette=None, realism="enhanced"):
    """_swept_normal_quad lit from the side, with `table` as its materials.

    The key is (1, 0, 0), square across the view axis rather than
    _material_square's above-and-in-front: dot(n, l) is then exactly the
    normal's x, which puts `wrapped` == 0.5 on the quad's centre column and
    so on image column 160, and the specular half vector at 45 degrees,
    which the sweep reaches inside the face."""
    plate = np.full((200, 320, 3), 200, np.uint8)
    actor = ActorDraw(0, _swept_normal_quad(), (0.0, 0.0, 0.0), 0, (0, 0, 0, 200, 0, 0),
                      RenderResult([], []), (), materials=table)
    return _soft_frame_render(gl_ctx, "hard", [actor], plate, (1.0, 0.0, 0.0),
                              shading="smooth", realism=realism, palette=palette)


def test_skin_warms_at_the_terminator(gl_ctx, monkeypatch):
    # The sss tint peaks where wrapped is 0.5 -- the light/shade boundary --
    # and vanishes on both the fully lit and the fully unlit side, which is
    # what makes it a terminator rather than a flat tint. A flat tint would
    # read the same excess in all three columns below.
    #
    # Measured as R/G on a grey quad: SSS_TINT is (1.0, 0.82, 0.74), so the
    # term takes green and blue away and leaves red exactly alone, and a
    # rising ratio is the tint and nothing else.
    #
    # Against skin with its own sss at zero rather than against matte: skin
    # carries a grain, a bump and a rim that matte does not, and all three
    # are identical between these two frames (sss does not touch the
    # normal). A fresh MaterialTable per render, per _upload_materials.
    import dataclasses

    from PyAitD.render import materials

    tabled = materials.CLASS_PRESETS["skin"]

    def render(sss):
        monkeypatch.setitem(materials.CLASS_PRESETS, "skin",
                            dataclasses.replace(tabled, sss=sss))
        return _material_sweep(gl_ctx, _table_of("skin"), _grey_palette())

    off, on = render(0.0), render(tabled.sss)

    def excess(cols):
        def redness(img):
            patch = img[SWEEP_ROWS, cols].astype(float)
            return patch[..., 0].mean() / patch[..., 1].mean()
        return redness(on) - redness(off)

    band, unlit, lit = excess(SWEEP_BAND), excess(SWEEP_UNLIT), excess(SWEEP_LIT)
    # 1/0.82 - 1 = 0.22 is the whole tint; measured 0.218 at the boundary.
    assert band > 0.15
    # 4w(1-w) is not one number over these columns: across each 8-column
    # band it runs from 0.02 at the outer edge to 0.10 at the inner one
    # (mean 0.057), so what they can carry is a few per cent of the band's
    # tint. Measured 0.016 unlit and 0.013 lit against 0.218 at the
    # boundary -- 7.4% and 6.0% -- so the 6x bound has room to spare.
    assert band > 6 * max(unlit, lit)
    # Warm, not merely dark: measured 0 levels of movement in red against
    # 21 in green.
    assert np.abs(on[..., 0] - off[..., 0]).max() <= 1


# A key that is neither straight down the view axis nor across it: the
# receiver's own `wrapped` is 0.85 under it, so 4w(1-w) is 0.50 -- half the
# full terminator tint, everywhere on the receiver at once -- and an
# occluder placed between it and the key throws a shadow the receiver
# catches. (The same light and the same receiver as
# test_an_occluder_shadows_the_key_share_of_a_receiver_only_under_soft; the
# occluder is wider, for the reason `_wide_occluder` gives.)
SHADOW_KEY = (0.5, -0.5, -0.7)
# Inside the umbra: solid, measured, and 40+ px clear of the penumbra the
# soft pass spreads around the occluder's outline.
UMBRA = (slice(84, 94), slice(109, 119))


def _wide_occluder():
    """A triangle between SHADOW_KEY and the receiver, wide enough that the
    umbra it casts is a region rather than the couple of pixels a small
    caster leaves once the four-tap PCF has spread its edge."""
    v = np.array([[-140.0, -460.0, 300.0], [340.0, -460.0, 300.0], [-140.0, 60.0, 300.0]], np.float32)
    return BodyGeometry(v, np.tile([0.0, 0.0, -1.0], (3, 1)).astype(np.float32),
                        np.array([[0, 1, 2]], np.int32), np.array([1], np.uint8),
                        np.zeros((0, 2), np.int32), np.zeros(0, np.uint8), (),
                        np.zeros(0, np.int32), np.zeros(0, np.uint8), np.zeros(0, np.uint8))


def test_a_key_shadowed_face_takes_no_warm_terminator(gl_ctx, monkeypatch):
    # `wrapped` is the *geometric* half-Lambert wrap and the shadow map does
    # not touch it, so before the sss factor was multiplied by `vis` a face
    # standing fully inside another actor's key shadow still took the whole
    # warm tint -- a lit terminator painted across an unlit face. Subsurface
    # scattering is key light that entered the surface; where the shadow map
    # says no key arrives, there is nothing to scatter.
    #
    # The same patch of the same receiver is measured twice, once with the
    # occluder and once without, so nothing but `vis` differs between the
    # two claims: identical normals, identical `wrapped`, identical grain
    # and bump (sss does not touch the normal), identical everything the
    # skin preset carries. As in test_skin_warms_at_the_terminator the
    # measurement is R/G on a grey quad, since SSS_TINT's red channel is
    # exactly 1.0 and the term can only take green and blue away.
    #
    # Deep in the umbra all four shadow taps read 0, so `vis` is exactly 0,
    # the mix factor is exactly 0 and mix(a, b, 0) is exactly a -- which
    # makes the shadowed half an equality rather than a bound.
    import dataclasses

    from PyAitD.render import materials

    tabled = materials.CLASS_PRESETS["skin"]
    plate = np.full((200, 320, 3), 200, np.uint8)

    def render(sss, occluded):
        monkeypatch.setitem(materials.CLASS_PRESETS, "skin",
                            dataclasses.replace(tabled, sss=sss))
        receiver = ActorDraw(0, _facing_tri(600.0, 1, (0.0, 0.0, -1.0)), (0.0, 0.0, 0.0), 0,
                             (0, 0, 200, 400, 0, 0), RenderResult([], []), (), _table_of("skin"))
        actors = [receiver] + ([_standing_actor(1, _wide_occluder(), 400.0)] if occluded else [])
        return _soft_frame_render(gl_ctx, "soft", actors, plate, SHADOW_KEY,
                                  shading="smooth", realism="enhanced", palette=_grey_palette())

    def warmth(occluded):
        off, on = render(0.0, occluded), render(tabled.sss, occluded)

        def redness(img):
            patch = img[UMBRA].astype(float)
            return patch[..., 0].mean() / patch[..., 1].mean()

        return redness(on) - redness(off), np.array_equal(on[UMBRA], off[UMBRA])

    lit_excess, lit_identical = warmth(occluded=False)
    shadowed_excess, shadowed_identical = warmth(occluded=True)
    # The control: unoccluded, this patch takes a real terminator tint --
    # measured 0.093 of excess redness, and 22 levels of movement.
    assert lit_excess > 0.05 and not lit_identical
    # The claim: shadowed, the same patch is no warmer than it is with skin's
    # own sss at zero. Measured exactly equal, not merely no warmer.
    assert shadowed_excess <= 0.001
    assert shadowed_identical


def test_classic_renders_every_material_class_like_matte(gl_ctx):
    # Every class in CLASS_PRESETS, rather than the one or two a per-term
    # test happens to name: under realism=classic each preset strength is 0
    # and every term the table drives collapses to exactly 1.0 or 0.0 by
    # construction, so no class can move a pixel. The swept-normal quad
    # reaches the whole table at once -- its normals run `wrapped` from 0
    # through the terminator to 1 (sss), turn away from the view axis (rim),
    # sweep through the specular half vector (spec, roughness, metallic) and
    # give the bump a non-degenerate facet (bump, detail, detail_scale) --
    # and `emissive`, the one term that can replace a fragment's colour
    # outright, is in the loop with the rest.
    from PyAitD.render.materials import CLASS_PRESETS

    palette = _grey_palette()

    def sweep(name, realism):
        return _material_sweep(gl_ctx, _table_of(name), palette, realism=realism)

    matte = sweep("matte", "classic")
    for name in CLASS_PRESETS:
        assert np.array_equal(sweep(name, "classic"), matte), \
            f"{name} moved a pixel under realism=classic"
    # The control, or the loop above would pass just as well on a fixture
    # that cannot see a material at all: under enhanced every class that is
    # not matte renders differently from matte on this same quad.
    enhanced = sweep("matte", "enhanced")
    for name in CLASS_PRESETS:
        if name != "matte":
            assert not np.array_equal(sweep(name, "enhanced"), enhanced), \
                f"{name} is indistinguishable from matte under realism=enhanced"


def test_an_emissive_surface_renders_its_palette_colour(gl_ctx):
    # Ramp 14 is a flame: it must not go dark when the key turns away. The
    # claim is stronger than invariance -- the fragment *is* its raw
    # palette colour, since preset_c.z * m2.z is exactly 1.0 and
    # mix(x, y, 1) is exactly y -- so it is asserted as the colour itself
    # and not merely as two frames that agree.
    #
    # A grey palette entry, because a lit red square reads 255 in its one
    # channel whether or not the term exists.
    body = (slice(70, 130), slice(120, 200))
    away = (0.0, -0.5, 0.85)          # behind the square: it stands in its own shade

    def square(name, light):
        return _material_square(gl_ctx, _table_of(name), palette=_grey_palette(), light=light)

    lit, unlit = square("emissive", KEY_FROM_ABOVE), square("emissive", away)
    assert (lit[body] == 200).all() and (unlit[body] == 200).all()
    # The control: the same two lights on a matte square are not the same
    # frame at all, so the invariance above is the term and not the fixture.
    matte_lit, matte_unlit = square("matte", KEY_FROM_ABOVE), square("matte", away)
    assert np.abs(matte_lit[body] - matte_unlit[body]).max() > 20


def test_a_tight_highlight_peaks_brighter_than_a_broad_one(gl_ctx, monkeypatch):
    # Blinn-Phong without its (gloss + 8) / 8pi normalisation spreads a
    # low-roughness lobe so thin it reads no brighter than a broad one,
    # which is backwards: the same energy in a smaller cone must be
    # brighter. Both halves are asserted -- the tight lobe peaks higher
    # *and* covers fewer columns -- because a peak that rose while the lobe
    # widened would be a brightness change, not a normalisation.
    from PyAitD.render import materials
    from PyAitD.render.materials import DETAIL_NONE, Material

    def lobe(roughness):
        # specular 0.05, not the tabled 0.8. The factor spans
        # (512 + 8) / 8pi = 20.7 against (8 + 8) / 8pi = 0.64, a ratio of
        # 32, and at any strength that leaves the broad lobe readable in 8
        # bits the tight one clips at 255 and stops being a measurement.
        monkeypatch.setitem(materials.CLASS_PRESETS, "matte",
                            Material(roughness, 0.05, 0.0, 0.0, 0.0, 1.0, DETAIL_NONE))
        # Green on the red quad is the specular and nothing else: base is
        # v_color * (...) and v_color's green is 0, metallic and rim are 0
        # here, and the grain multiplies a base that is already 0.
        green = _material_sweep(gl_ctx, _table_of("matte"))[SWEEP_BODY][..., 1]
        peak = int(green.max())
        return peak, int((green.max(axis=0) > peak / 2).sum())

    tight_peak, tight_width = lobe(0.2)      # gloss 512
    broad_peak, broad_width = lobe(0.8)      # gloss 8
    assert tight_peak > 4 * broad_peak       # measured 196 against 6
    assert tight_width < broad_width         # measured 4 columns against 30


def _gradient_plate():
    """A plate no composite can be right about by accident: every column a
    different value, so a plate term dropped, halved, or fetched at the
    wrong pixel all show up as a difference rather than as black-on-black.
    `_lit_frame`'s all-black background cannot distinguish
    `plate * (1 - a) + rgb` from `rgb` at all."""
    plate = np.zeros((200, 320, 3), np.uint8)
    plate[:, :, 0] = np.arange(320, dtype=np.uint8)
    plate[:, :, 1] = 90
    plate[:, :, 2] = 200 - np.arange(320, dtype=np.uint8) // 2
    return plate


def _integration_options(**kw):
    base = dict(scale=1, shading="smooth", lighting="scene", msaa=0)
    base.update(kw)
    return RenderOptions(**base)


def test_integration_at_full_with_a_neutral_plate_reproduces_the_golden(gl_ctx):
    # The plumbing identity: `on` changes where the pixels are assembled,
    # never what they are. NEUTRAL_PLATE makes every composite term vanish
    # by construction, and msaa=0 makes coverage exactly 0 or 1.
    backend = GLBackend(gl_ctx, RenderOptions(
        scale=1, shading="smooth", lighting="scene", msaa=0,
        realism="classic", smoothing=0, shadows="hard", integration=2))
    backend.draw(_golden_frame())
    out = backend.read_rgb()
    backend.release()
    assert np.array_equal(out, np.load(GOLDEN))


@pytest.mark.parametrize("shadows", ["hard", "soft"])
def test_integration_at_full_matches_off_pixel_for_pixel_at_msaa_zero(gl_ctx, shadows):
    # Not just the golden scene: a real cast shadow under both shadow modes,
    # over a plate every column of which differs. Built here rather than
    # through _lit_frame -- same actor, same light -- because that helper's
    # background is all black, and against black this assertion cannot tell
    # `plate * (1 - a) + rgb` from `rgb`.
    from PyAitD.render.lighting import SceneLight
    frame = FrameDescription(
        _view(), ImageAsset(_gradient_plate(), False), _palette(),
        (_standing_actor(0, _tri_geometry(600.0, 1), 400.0),), (),
        SceneLight((0.3, -0.6, -0.7), (1.0, 1.0, 1.0), (0.2, 0.2, 0.2), 1.0))
    off = GLBackend(gl_ctx, _integration_options(shadows=shadows, integration=0))
    off.draw(frame)
    expected = off.read_rgb().copy()
    off.release()
    on = GLBackend(gl_ctx, _integration_options(shadows=shadows, integration=2))
    on.draw(frame)
    got = on.read_rgb().copy()
    on.release()
    assert np.array_equal(got, expected)


def test_integration_leaves_fixed_lighting_untouched(gl_ctx):
    # `integration` applies under lighting="scene" only.
    actor = _actor(0, _facing_tri(600.0, 1, (0.0, 0.0, -1.0)))
    off = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="fixed",
                                          integration=0))
    off.draw(_frame([actor]))
    expected = off.read_rgb().copy()
    off.release()
    on = GLBackend(gl_ctx, RenderOptions(scale=1, shading="smooth", lighting="fixed",
                                         integration=2))
    on.draw(_frame([actor]))
    assert np.array_equal(on.read_rgb(), expected)
    on.release()


def test_integration_at_full_still_resolves_msaa_into_the_same_texture(gl_ctx):
    # The two shapes below cannot tell a correct composite from one whose
    # output is thrown away -- appending the single-target resolve to the
    # end of _composite() overwrites the composited frame with the stale
    # multisample buffer, and the shapes are identical either way. So this
    # also holds `on` against `off` on the same frame, over a gradient
    # plate: against an all-black background a discarded composite is
    # indistinguishable from a correct one.
    #
    # The two paths agree mathematically -- the resolve is a linear average
    # and so is "over" -- but _plate_tex and _actor_tex quantise to 8 bits
    # in between, so an antialiased edge can land a bit apart. Measured
    # max=1 at scale 1 and 2, msaa 2, 4 and 8, three repeats each. The 2 is
    # driver headroom on sample weighting, not a measurement: tightening it
    # to the measured 1 is not the safe-looking edit it appears to be.
    #
    # The plate is upscaled to the scale=2 target resolution rather than
    # left at 320x200 -- Task 4 softens or pixelates the actor layer to
    # match a plate cell wider than a target pixel, and at cell==1 that
    # machinery is a no-op, which is what this test needs: it is about the
    # msaa resolve, not about the composite's sharpness matching.
    from PyAitD.render.lighting import SceneLight
    plate = np.repeat(np.repeat(_gradient_plate(), 2, axis=0), 2, axis=1)
    frame = FrameDescription(
        _view(), ImageAsset(plate, False), _palette(),
        (_standing_actor(0, _tri_geometry(600.0, 1), 400.0),), (),
        SceneLight((0.3, -0.6, -0.7), (1.0, 1.0, 1.0), (0.2, 0.2, 0.2), 1.0))
    backend = GLBackend(gl_ctx, RenderOptions(scale=2, shading="smooth", lighting="scene",
                                              msaa=4, integration=2))
    backend.draw(frame)
    on = backend.read_rgb().copy()
    assert on.shape == (400, 640, 3)
    assert backend.thumbnail().shape == (200, 320, 3)
    backend.release()
    direct = GLBackend(gl_ctx, RenderOptions(scale=2, shading="smooth", lighting="scene",
                                             msaa=4, integration=0))
    direct.draw(frame)
    off = direct.read_rgb().copy()
    direct.release()
    assert np.abs(on.astype(int) - off.astype(int)).max() <= 2


def test_integration_at_full_still_darkens_the_ground_under_a_hard_shadow(gl_ctx):
    # The hard cast moved ahead of the bodies to reach the plate layer; it
    # must still land on the plate.
    #
    # Both halves are asserted, and the second is the load-bearing one: a
    # composite that dropped the plate term entirely would turn the frame
    # black, which satisfies "something got darker" *more* easily than a
    # correct render does. Only "and the rest of the plate came through
    # untouched" tells the two apart, which is why the plate is a gradient
    # and why the corner is compared against the baseline render rather
    # than against a colour written down here.
    plate = _gradient_plate()
    baseline = _plain_background(gl_ctx, plate, shadows="hard")
    backend = GLBackend(gl_ctx, _integration_options(shadows="hard", integration=2))
    backend.draw(FrameDescription(
        _view(), ImageAsset(plate, False), _palette(),
        (_standing_actor(0, _tri_geometry(600.0, 1), 400.0),), (),
        _scene_light((0.3, -0.6, -0.7))))
    out = backend.read_rgb().astype(int)
    backend.release()
    assert (out < baseline).any(), "the hard cast never reached the plate layer"
    # Measured: nothing outside rows 20..179, columns 60..238 differs from
    # the baseline at all, so this corner is 42 columns clear of the cast.
    corner = (slice(0, 40), slice(280, 320))
    assert np.array_equal(out[corner], baseline[corner]), \
        "the plate the shadow never reached did not survive the composite"


def _edge_transition_width(rgb, row):
    """How many pixels of the row are strictly between the two extremes:
    the width of the actor's edge ramp."""
    line = rgb[row].astype(int).sum(axis=1)
    lo, hi = line.min(), line.max()
    return int(((line > lo + 4) & (line < hi - 4)).sum())


def _edge_frame(plate):
    # `_actor`, not `_standing_actor`: its zv puts the ground plane on the
    # horizon, so the shadow pass rasterises nothing. A real ground shadow
    # lands on the *plate* layer at target resolution -- it is neither
    # softened nor pixelated -- and would confound both measurements below.
    return FrameDescription(
        _view(), ImageAsset(plate, False), _palette(),
        (_actor(0, _tri_geometry(600.0, 1)),), (),
        _scene_light((0.0, -1.0, 0.0)))


def test_bilinear_softening_widens_an_actor_edge(gl_ctx):
    # At scale 4 over a 320-wide plate each plate pixel became a 4x4 cell,
    # so bilinear left the plate soft over ~1.4 px; the actor is softened
    # to match, and its edge ramp gets wider than the hard `off` one.
    plate = np.zeros((200, 320, 3), np.uint8)
    frame = _edge_frame(plate)
    widths = _edge_widths(gl_ctx, frame, (0, 2))
    assert widths[2] > widths[0]


def _edge_widths(gl_ctx, frame, levels, background_filter="bilinear"):
    """The actor's edge-ramp width at each integration level, everything
    else held fixed."""
    widths = {}
    for level in levels:
        backend = GLBackend(gl_ctx, RenderOptions(
            scale=4, shading="smooth", lighting="scene", msaa=0,
            background_filter=background_filter, integration=level))
        backend.draw(frame)
        widths[level] = _edge_transition_width(backend.read_rgb(), 400)
        backend.release()
    return widths


def test_a_lower_integration_level_softens_the_actor_edge_less(gl_ctx):
    # softness is scaled by the level's strength before the blur radius is
    # derived from it, so the edge ramp narrows toward the hard `off` one as
    # the level drops and widens past `full` at the top.
    widths = _edge_widths(gl_ctx, _edge_frame(np.zeros((200, 320, 3), np.uint8)),
                          (0, 1, 2, 3))
    assert widths[0] < widths[1] < widths[2] < widths[3]


def test_nearest_pixelates_the_actor_to_the_plate_grid(gl_ctx):
    # A constant plate, so the only thing that could vary inside a 4x4 cell
    # is the actor -- and under `nearest` it must not.
    plate = np.full((200, 320, 3), 90, np.uint8)
    backend = GLBackend(gl_ctx, RenderOptions(
        scale=4, shading="smooth", lighting="scene", msaa=0,
        background_filter="nearest", integration=2))
    backend.draw(_edge_frame(plate))
    out = backend.read_rgb()
    backend.release()
    cells = out.reshape(200, 4, 320, 4, 3)
    assert (cells.max(axis=(1, 3)) == cells.min(axis=(1, 3))).all()


def test_nothing_is_softened_when_the_plate_is_already_target_resolution(gl_ctx):
    # cell == 1: an override plate at the target size. Still the identity.
    frame = _edge_frame(np.zeros((200, 320, 3), np.uint8))
    off = GLBackend(gl_ctx, _integration_options(background_filter="bilinear",
                                                 integration=0))
    off.draw(frame)
    expected = off.read_rgb().copy()
    off.release()
    on = GLBackend(gl_ctx, _integration_options(background_filter="bilinear",
                                                integration=2))
    on.draw(frame)
    assert np.array_equal(on.read_rgb(), expected)
    on.release()


def _composited_centre(gl_ctx, profile, palette=None, colour=1, plate_value=0,
                       integration=2):
    """The composited pixel at the centre of one flat, fully-lit triangle,
    under `profile`. Everything except the profile and the integration level
    is held fixed, so two calls differ only by what the tone curve did."""
    from PyAitD.render.scene import FrameDescription as FD
    palette = _palette() if palette is None else palette
    plate = np.full((200, 320, 3), plate_value, np.uint8)
    frame = FD(_view(), ImageAsset(plate, False), palette,
               (_standing_actor(0, _tri_geometry(600.0, colour), 400.0),), (),
               _scene_light((0.0, 0.0, -1.0)), profile)
    backend = GLBackend(gl_ctx, RenderOptions(
        scale=1, shading="smooth", lighting="scene", msaa=0,
        realism="classic", integration=integration))
    backend.draw(frame)
    got = _centre(backend.read_rgb())
    backend.release()
    return got


def test_the_toe_lifts_a_black_actor_to_the_rooms_floor(gl_ctx):
    # palette index 0 is black, and realism="classic" zeroes the specular
    # and rim terms, so the actor's own colour really is (0, 0, 0): the
    # whole of the difference below is the toe.
    from PyAitD.render.plate import NEUTRAL_PLATE, PlateProfile
    black = (30 / 255, 20 / 255, 20 / 255)
    flat = _composited_centre(gl_ctx, NEUTRAL_PLATE, colour=0)
    lifted = _composited_centre(gl_ctx, PlateProfile(black, (1.0, 1.0, 1.0), 0.0), colour=0)
    assert list(flat) == [0, 0, 0]
    assert list(lifted) == pytest.approx([30, 20, 20], abs=1)


def test_the_shoulder_pulls_a_white_actor_to_the_rooms_ceiling(gl_ctx):
    # A white palette entry on a triangle facing the light head-on: the
    # neutral render saturates, and the 0.8 ceiling has to pull it down.
    from PyAitD.render.plate import NEUTRAL_PLATE, PlateProfile
    palette = np.zeros((256, 3), np.uint8)
    palette[1] = (255, 255, 255)
    flat = _composited_centre(gl_ctx, NEUTRAL_PLATE, palette=palette)
    pulled = _composited_centre(
        gl_ctx, PlateProfile((0.0, 0.0, 0.0), (0.8, 0.8, 0.8), 0.0), palette=palette)
    assert flat.max() == 255
    assert pulled.max() < 255
    assert pulled.max() == pytest.approx(204, abs=2)   # 255 * 0.8


def _grey_grain_render(gl_ctx, grain, scale=1, integration=2):
    """One flat mid-grey triangle over a flat plate, at `grain`.

    Mid-grey and realism="classic" together: the actor's composited value
    lands near 128, so a +-0.5 * grain * GAIN excursion (about +-35 at
    grain 0.08) neither clips at 255 nor floors at 0. Measuring the noise
    on a saturated channel would clip half of it and halve the RMS.

    `scale` is 1 -- cell 1, where the plate's dither arrives intact and the
    composite lays down a hard per-pixel field to match -- unless a caller
    asks for the magnified case."""
    from PyAitD.render.plate import PlateProfile
    from PyAitD.render.scene import FrameDescription as FD
    palette = np.zeros((256, 3), np.uint8)
    palette[1] = (128, 128, 128)
    frame = FD(_view(), ImageAsset(np.full((200, 320, 3), 120, np.uint8), False), palette,
               (_actor(0, _tri_geometry(600.0, 1)),), (),
               _scene_light((0.0, 0.0, -1.0)),
               PlateProfile((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), grain))
    backend = GLBackend(gl_ctx, RenderOptions(
        scale=scale, shading="smooth", lighting="scene", msaa=0,
        realism="classic", integration=integration))
    backend.draw(frame)
    out = backend.read_rgb().copy()
    backend.release()
    return out


def test_grain_is_still_and_confined_to_the_actor(gl_ctx):
    quiet = _grey_grain_render(gl_ctx, 0.0)
    first = _grey_grain_render(gl_ctx, 0.08)
    second = _grey_grain_render(gl_ctx, 0.08)
    # Hashed on the screen cell alone, so it sits still like the plate's
    # own dither rather than crawling between frames.
    assert np.array_equal(first, second)
    # Zero where the actor is not: the noise lives inside the `a > 0` branch.
    outside = first != quiet
    assert not outside[10, 10].any()
    assert outside.any(), "grain never moved a pixel at all"


def test_grain_lands_at_the_plates_own_amplitude(gl_ctx):
    # GAIN is sqrt(12) precisely so the composited residual's RMS equals
    # `grain`. Measured as the difference between two otherwise identical
    # renders, which isolates the noise from the actor's own shading.
    quiet = _grey_grain_render(gl_ctx, 0.0).astype(float)
    noisy = _grey_grain_render(gl_ctx, 0.08).astype(float)
    # A patch well inside the triangle (see _centre's note on its extent).
    patch = (noisy - quiet)[60:100, 110:150, 0]
    assert patch.std() == pytest.approx(0.08 * 255, rel=0.05)


def test_grain_lands_at_the_plates_displayed_amplitude_once_magnified(gl_ctx):
    # The test above renders at scale 1, where one plate pixel is one
    # target pixel and there is nothing for the upscale to take away. At
    # scale 4 there is: `grain` is measured on the 320x200 source, but the
    # plate the actor stands next to has been through GL_LINEAR, which
    # attenuates a white dither on the way. The composited amplitude has to
    # track the displayed one, not the source -- matching the source is
    # what made the actor visibly noisier than its own room.
    #
    # The reference is the magnified field itself rather than a factor.
    # `plate.grain_retention` derives the attenuation of a *cell mean*,
    # which is the right question for a grain laid down one flat value per
    # cell and the wrong one for a field that ramps within the cell the way
    # the room's does: per displayed pixel the ramp keeps 0.658 of the
    # source amplitude, not the cell mean's 0.59375.
    from tests.gl_linear import gl_linear_upscale
    quiet = _grey_grain_render(gl_ctx, 0.0, scale=4).astype(float)
    noisy = _grey_grain_render(gl_ctx, 0.08, scale=4).astype(float)
    patch = (noisy - quiet)[240:400, 440:600, 0]
    rng = np.random.default_rng(11)
    source = rng.uniform(-0.5, 0.5, (200, 320)) * np.sqrt(12.0) * 0.08 * 255.0
    displayed = gl_linear_upscale(source, 4)[240:400, 440:600]
    assert patch.std() == pytest.approx(displayed.std(), rel=0.05)
    # And is not the un-attenuated amplitude: 13.4 counts against 20.4, far
    # enough apart that magnifying nothing fails here rather than merely
    # loosening a tolerance.
    assert patch.std() < 0.08 * 255 * 0.8


def test_the_toe_scales_with_the_integration_level(gl_ctx):
    # The level's strength multiplies the toe offset, so at a black actor --
    # where the whole of the difference is the toe -- the lift is exactly
    # half the room's floor at 1, the whole of it at 2, and half again as
    # much at 3. Read against the same NEUTRAL_PLATE flat as the toe test
    # above, and at a floor low enough that 1.5x cannot clip.
    from PyAitD.render.plate import PlateProfile
    black = (60 / 255, 40 / 255, 40 / 255)
    profile = PlateProfile(black, (1.0, 1.0, 1.0), 0.0)
    lifted = {level: list(_composited_centre(gl_ctx, profile, colour=0, integration=level))
              for level in (1, 2, 3)}
    assert lifted[2] == pytest.approx([60, 40, 40], abs=1)
    assert lifted[1] == pytest.approx([30, 20, 20], abs=1)
    assert lifted[3] == pytest.approx([90, 60, 60], abs=1)


def test_the_grain_scales_with_the_integration_level(gl_ctx):
    # Same measurement as test_grain_lands_at_the_plates_own_amplitude, one
    # level down and one up: the composited residual's RMS is the plate's
    # own amplitude times the level's strength.
    quiet = _grey_grain_render(gl_ctx, 0.0).astype(float)
    patch = (slice(60, 100), slice(110, 150), 0)
    for level, strength in ((1, 0.5), (2, 1.0), (3, 1.5)):
        noisy = _grey_grain_render(gl_ctx, 0.08, integration=level).astype(float)
        assert (noisy - quiet)[patch].std() == pytest.approx(0.08 * 255 * strength, rel=0.05), level


def test_nearest_pixelates_at_every_level_that_composites(gl_ctx):
    # `pixelate` is which plate cell a pixel falls in, not an amount, so it
    # is binary: every level that composites at all puts the actor on the
    # plate's grid, and strength grades only the tone and the grain.
    plate = np.full((200, 320, 3), 90, np.uint8)
    for level in (1, 2, 3):
        backend = GLBackend(gl_ctx, RenderOptions(
            scale=4, shading="smooth", lighting="scene", msaa=0,
            background_filter="nearest", integration=level))
        backend.draw(_edge_frame(plate))
        out = backend.read_rgb()
        backend.release()
        cells = out.reshape(200, 4, 320, 4, 3)
        assert (cells.max(axis=(1, 3)) == cells.min(axis=(1, 3))).all(), level


def _residual_rms(field):
    """RMS of a field against its own 3x3 box mean -- `plate._grain`'s
    estimator, at target resolution. What the eye compares the actor's
    dither against is the room's residual, not its variance."""
    padded = np.pad(field, 1, mode="edge")
    mean = sum(padded[dy:dy + field.shape[0], dx:dx + field.shape[1]]
               for dy in range(3) for dx in range(3)) / 9.0
    return float((field - mean).std())


def test_grain_arrives_the_way_the_rooms_own_dither_does(gl_ctx):
    # Amplitude is not character. One constant value per plate cell and a
    # bilinearly magnified white field can share a per-pixel RMS and still
    # read as different processes, because the residual against the local
    # mean -- which is what a dither *looks* like -- differs by 3x between
    # them. So this holds the composited noise against a synthetic upscale
    # of the same dither, built independently the way test_plate builds it,
    # rather than against a variance the block model already satisfies.
    from tests.gl_linear import gl_linear_upscale
    grain, cell = 0.08, 4
    quiet = _grey_grain_render(gl_ctx, 0.0, scale=cell).astype(float)
    noisy = _grey_grain_render(gl_ctx, grain, scale=cell).astype(float)
    added = (noisy - quiet)[240:400, 440:600, 0]

    rng = np.random.default_rng(7)
    source = rng.uniform(-0.5, 0.5, (200, 320)) * np.sqrt(12.0) * grain * 255.0
    room = gl_linear_upscale(source, cell)[240:400, 440:600]

    assert added.std() == pytest.approx(room.std(), rel=0.1)
    assert _residual_rms(added) == pytest.approx(_residual_rms(room), rel=0.15)


def test_the_tone_match_leaves_an_actor_already_inside_the_rooms_range_alone(gl_ctx):
    # The whole of the wash. An actor pixel between the plate's floor and
    # its ceiling is a value the room can already print, so matching the
    # room has nothing to say about it -- and in a dark room that is most
    # of the figure, not an edge case: the attic's range is luma 16..124
    # counts and the actor's median luma is 47.
    #
    # A quartic weighted on absolute luma cannot express that. It was
    # written as an extremes-only correction on the assumption that luma
    # 0.5 is a midtone; at the luma an actor in this game actually sits at,
    # (1 - luma)^4 is still ~0.43, so it lifted the whole figure.
    from PyAitD.render.plate import NEUTRAL_PLATE, PlateProfile
    # The attic camera's own profile, and an actor at the median luma the
    # figure actually renders at there.
    room = PlateProfile((33 / 255, 12 / 255, 8 / 255), (157 / 255, 117 / 255, 98 / 255), 0.0)
    grey = np.zeros((256, 3), np.uint8)
    grey[1] = (60, 60, 60)
    flat = _composited_centre(gl_ctx, NEUTRAL_PLATE, palette=grey)
    matched = _composited_centre(gl_ctx, room, palette=grey)
    assert list(matched) == list(flat)


def test_the_tone_match_still_meets_the_room_at_both_extremes(gl_ctx):
    # What the clamp must not lose: an actor darker than anything the room
    # can print is raised to the room's floor, and one brighter than the
    # room's ceiling is pulled down to it. Same claim the quartic made at
    # luma 0 and luma 1, now made only there.
    from PyAitD.render.plate import PlateProfile
    room = PlateProfile((33 / 255, 12 / 255, 8 / 255), (157 / 255, 117 / 255, 98 / 255), 0.0)
    black = np.zeros((256, 3), np.uint8)
    white = np.zeros((256, 3), np.uint8)
    white[1] = (255, 255, 255)
    assert list(_composited_centre(gl_ctx, room, palette=black, colour=0)) == \
        pytest.approx([33, 12, 8], abs=1)
    assert list(_composited_centre(gl_ctx, room, palette=white)) == \
        pytest.approx([157, 117, 98], abs=1)


def _painted_frame():
    """_golden_frame with every body given a four-quadrant atlas and a
    distinct per-corner UV, so both the tessellated and flat actor paths
    have something to sample -- and so a wrong corner order or a wrong
    barycentric term actually moves pixels instead of landing on the same
    colour everywhere.

    Round 1 of the task-5 review flagged that a *red* atlas is a no-op:
    _golden_frame's textured body is palette index 1, which _palette()
    sets to (255, 0, 0) -- painting it red would land on exactly the value
    the untextured ramp already produces. Round 2 flagged that a *uniform*
    atlas is also a no-op for a different reason: with every corner UV
    equal (as a single np.full(...) fill gave every corner), any set of
    barycentric weights summing to 1 blends three identical values back to
    that same value, so a scrambled corner order or a transposed
    interpolation term is invisible no matter what colour the atlas holds.
    Both defects have to be avoided together: distinct colours across the
    atlas (avoiding _palette()'s red and green, which are unused by the
    tessellated triangle actor but avoided anyway for the same reason as
    red) and distinct UVs per corner, so a corner swap in TESS_VSH's
    `v_uv = in_uv0 * u + in_uv1 * v + in_uv2 * w` relocates which colour
    lands where on screen rather than leaving the picture unchanged."""
    import dataclasses
    frame = _golden_frame()
    atlas = np.zeros((8, 8, 3), np.uint8)
    atlas[:4, :4] = (0, 0, 255)      # low u, low v:  blue
    atlas[:4, 4:] = (0, 255, 255)    # high u, low v: cyan
    atlas[4:, :4] = (255, 0, 255)    # low u, high v: magenta
    atlas[4:, 4:] = (255, 255, 0)    # high u, high v: yellow (unreached by the corner triangle below,
                                      # which is the point: a scrambled order can pull it in)
    texture = ImageAsset(atlas, True)
    # Deep inside three different quadrants -- (0.15, 0.15), (0.85, 0.15),
    # (0.15, 0.85) -- clear of the quadrant boundaries and clear of
    # (0.85, 0.85), which the correct blend never reaches but a scrambled
    # corner order can.
    corner_uv = np.array([[0.15, 0.15], [0.85, 0.15], [0.15, 0.85]], np.float32)
    painted_actors = tuple(
        dataclasses.replace(
            actor,
            geometry=dataclasses.replace(
                actor.geometry,
                uv=np.tile(corner_uv, (len(actor.geometry.tris), 1, 1)).astype(np.float32)),
            texture=texture,
        )
        for actor in frame.actors
    )
    return dataclasses.replace(frame, actors=painted_actors)


def test_instance_layout_uses_no_more_than_the_guaranteed_attribute_slots(gl_ctx):
    """The tessellated actor path packs 12 per-corner attributes plus the
    per-vertex barycentric, and adding the UVs takes it to 16 -- exactly
    GL 3.3's guaranteed minimum. This pin is the tripwire: the next
    per-corner attribute does not fit, and must find room by packing into
    an existing one instead."""
    from PyAitD.render.render_gl import INSTANCE_FLOATS, _INSTANCE_NAMES
    assert INSTANCE_FLOATS == 51
    assert len(_INSTANCE_NAMES) == 15          # 5 per corner x 3 corners
    assert len(_INSTANCE_NAMES) + 1 <= gl_ctx.info["GL_MAX_VERTEX_ATTRIBS"]
    assert gl_ctx.info["GL_MAX_VERTEX_ATTRIBS"] >= 16


def test_drawing_the_same_unpainted_body_twice_is_self_consistent(gl_ctx):
    """NOT the regression net for "unpainted stays unchanged" -- drawing the
    same frame twice agrees with itself whether or not texture substitution
    works at all, so this only pins that compiling the texture-substitution
    code path introduces no per-draw nondeterminism (stale cache state,
    uninitialised uniforms) for a body that never sets has_body_texture.
    The actual byte-for-byte guarantee lives in
    test_classic_realism_matches_the_pre_materials_golden (unmodified,
    still matches tests/golden/scene_lit_classic.npy) and in ACTOR_FSH's
    unconditional `albedo = v_color` whenever has_body_texture == 0."""
    from PyAitD.render.render_gl import GLBackend
    from PyAitD.render.render_options import RenderOptions
    options = RenderOptions(scale=1, shading="smooth", lighting="scene", msaa=0,
                            realism="enhanced", smoothing=0, shadows="hard",
                            integration=0, motion="tick")
    backend = GLBackend(gl_ctx, options)
    try:
        backend.draw(_golden_frame())          # the file's own unpainted fixture
        first = backend.read_rgb()
        backend.draw(_golden_frame())
        assert np.array_equal(first, backend.read_rgb())
    finally:
        backend.release()


def test_a_painted_body_changes_pixels_and_classic_ignores_it(gl_ctx):
    """A four-quadrant atlas over distinct per-corner UVs must move pixels
    under realism=enhanced and move none under realism=classic."""
    from PyAitD.render.render_gl import GLBackend
    from PyAitD.render.render_options import RenderOptions

    plain = _golden_frame()
    painted = _painted_frame()                 # same frame, distinct per-corner uv + atlas (helper above)

    def render(frame, realism):
        options = RenderOptions(scale=1, shading="smooth", lighting="scene", msaa=0,
                                realism=realism, smoothing=0, shadows="hard",
                                integration=0, motion="tick")
        backend = GLBackend(gl_ctx, options)
        try:
            backend.draw(frame)
            return backend.read_rgb()
        finally:
            backend.release()

    assert not np.array_equal(render(plain, "enhanced"), render(painted, "enhanced"))
    assert np.array_equal(render(plain, "classic"), render(painted, "classic"))


def test_a_painted_body_changes_pixels_through_the_tessellated_path_too(gl_ctx):
    """RenderOptions.smoothing defaults to 2, and _draw_frame routes every
    actor through _draw_actor_tessellated whenever smoothing is nonzero --
    the configuration players actually run. The flat-path test above only
    exercised the non-default smoothing=0 fallback
    (test_smoothing_zero_draws_through_the_legacy_path names it as such);
    this pins that the tessellated path -- TESS_VSH's in_uv0/1/2 wiring,
    _draw_actor_tessellated's texture bind, has_body_texture/body_albedo on
    _tess_prog -- is exercised end to end, at exactly 16 of the
    tessellated layout's 16 vertex-attribute slots.

    What this does NOT prove, even with _painted_frame's four-quadrant
    atlas and distinct per-corner UVs: correctness of the corner order in
    `v_uv = in_uv0 * u + in_uv1 * v + in_uv2 * w`. Painting with a
    scrambled corner order still differs from painting nothing at all, by
    the same pixel count as painting it right -- a before/after comparison
    against the unpainted frame cannot see a wrong-but-different paint job
    as wrong. Verified directly (task-5-report.md, fix round 2): swapping
    in_uv0/in_uv1 in TESS_VSH left this test green, with the exact same
    12793-pixel painted-vs-plain diff as the correct shader, even though
    8333 of those 12793 pixels actually changed colour relative to the
    correct render. That gap is closed instead by
    test_tess_vsh_blends_uv_by_the_same_corner_order_as_position_and_normal,
    which reads v_uv back via transform feedback and compares it to an
    independent numpy reference -- the only thing in this suite that a
    scrambled corner order cannot survive."""
    from PyAitD.render.render_gl import GLBackend
    from PyAitD.render.render_options import RenderOptions

    plain = _golden_frame()
    painted = _painted_frame()

    def render(frame, realism):
        options = RenderOptions(scale=1, shading="smooth", lighting="scene", msaa=0,
                                realism=realism, smoothing=2, shadows="hard",
                                integration=0, motion="tick")
        backend = GLBackend(gl_ctx, options)
        try:
            backend.draw(frame)
            return backend.read_rgb()
        finally:
            backend.release()

    assert not np.array_equal(render(plain, "enhanced"), render(painted, "enhanced"))
    assert np.array_equal(render(plain, "classic"), render(painted, "classic"))
