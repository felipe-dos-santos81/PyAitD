# SPDX-License-Identifier: GPL-2.0-only
import math

import moderngl
import numpy as np
import pygame

import PyAitD.render.render as render
from PyAitD.render.asset_resolver import ImageAsset
from PyAitD.render.render import Renderer, composite_ui, fit_quad
from PyAitD.render.render_gl import GLBackend
from PyAitD.render.render_options import RenderOptions
from PyAitD.render.render_soft import SoftwareBackend
from PyAitD.render.scene import CameraView, FrameDescription
from PyAitD.app.ui import transparent_canvas
from PyAitD.engine.space.world import CameraState
import pytest

pytestmark = pytest.mark.render


def test_fit_quad_exact_multiple():
    assert fit_quad(320, 200, 1280, 800) == (-1.0, -1.0, 1.0, 1.0)


def test_fit_quad_letterbox_wide_window():
    # height-limited: scale = min(1600/320, 800/200) = 4 -> pillarboxed horizontally
    assert fit_quad(320, 200, 1600, 800) == (-0.8, -1.0, 0.8, 1.0)
    # width-limited: scale = min(1000/320, 800/200) = 3.125
    x0, y0, x1, y1 = fit_quad(320, 200, 1000, 800)
    assert math.isclose(x1 - x0, 2.0)        # full width
    assert math.isclose(y1 - y0, 1.5625)     # 2 * 200*3.125/800


def test_fit_quad_centered():
    x0, y0, x1, y1 = fit_quad(320, 200, 1000, 800)
    assert math.isclose(x0, -x1) and math.isclose(y0, -y1)


def test_window_to_logical_rejects_letterbox_and_scales_view(monkeypatch):
    renderer = object.__new__(Renderer)
    monkeypatch.setattr(pygame.display, "get_window_size", lambda: (800, 400))
    assert renderer.window_to_logical((79, 200)) is None
    assert renderer.window_to_logical((80, 0)) == (0, 0)
    assert renderer.window_to_logical((719, 399)) == (319, 199)


def test_composite_ui_blends_alpha_and_replaces_rgb():
    scene = np.full((200, 320, 3), 100, np.uint8)
    canvas = np.zeros((200, 320, 4), np.uint8)
    canvas[10, 10] = (255, 255, 255, 255)
    canvas[20, 20] = (0, 0, 0, 128)
    out = composite_ui(scene, canvas)
    assert tuple(out[10, 10]) == (255, 255, 255)
    assert tuple(out[5, 5]) == (100, 100, 100)
    assert 40 <= out[20, 20][0] <= 60
    opaque = np.full((200, 320, 3), 7, np.uint8)
    assert np.array_equal(composite_ui(scene, opaque), opaque)


def test_renderer_falls_back_to_software_when_gl_fails(monkeypatch):
    renderer = object.__new__(render.Renderer)
    renderer._ctx = object()
    renderer.fallback_notice = None

    def boom(*_a, **_k):
        raise RuntimeError("no stencil")

    monkeypatch.setattr(render, "GLBackend", boom)
    renderer._select_backend(RenderOptions(scale=4))
    assert isinstance(renderer.backend, SoftwareBackend)
    assert renderer.fallback_notice == "Enhanced rendering unavailable"
    assert renderer.options.scale == 1


def test_renderer_selects_gl_backend_when_context_available(gl_ctx):
    renderer = object.__new__(render.Renderer)
    renderer._ctx = gl_ctx
    renderer.fallback_notice = None
    options = RenderOptions(scale=2)
    try:
        renderer._select_backend(options)
        assert isinstance(renderer.backend, GLBackend)
        assert renderer.options == options
        assert renderer.fallback_notice is None
    finally:
        if isinstance(renderer.backend, GLBackend):
            renderer.backend.release()


def test_set_options_rebuilds_and_releases_gl_backend(gl_ctx):
    renderer = object.__new__(render.Renderer)
    renderer._ctx = gl_ctx
    renderer.fallback_notice = None
    renderer._select_backend(RenderOptions(scale=2))
    old_backend = renderer.backend
    released = []
    old_release = old_backend.release
    old_backend.release = lambda: (released.append(True), old_release())[0]

    try:
        renderer.set_options(RenderOptions(scale=3))
        assert released == [True]
        assert renderer.backend is not old_backend
        assert renderer.options.scale == 3
    finally:
        if isinstance(renderer.backend, GLBackend):
            renderer.backend.release()


def test_set_options_is_a_noop_when_options_are_unchanged(gl_ctx):
    renderer = object.__new__(render.Renderer)
    renderer._ctx = gl_ctx
    renderer.fallback_notice = None
    options = RenderOptions(scale=2)
    renderer._select_backend(options)
    backend = renderer.backend
    try:
        renderer.set_options(RenderOptions(scale=2))
        assert renderer.backend is backend
    finally:
        backend.release()


def test_select_backend_resets_the_stale_thumbnail(gl_ctx):
    # A rebuilt backend starts undrawn: a present() that lands before the next
    # compose_scene() must not show the previous backend's cached frame.
    renderer = object.__new__(render.Renderer)
    renderer._ctx = gl_ctx
    renderer.fallback_notice = None
    renderer._select_backend(RenderOptions(scale=2))
    renderer._thumbnail_cache = np.zeros((200, 320, 3), np.uint8)
    try:
        renderer._select_backend(RenderOptions(scale=3))
        assert renderer._thumbnail_cache is None
    finally:
        if isinstance(renderer.backend, GLBackend):
            renderer.backend.release()


def test_set_options_resets_the_stale_thumbnail(gl_ctx):
    renderer = object.__new__(render.Renderer)
    renderer._ctx = gl_ctx
    renderer.fallback_notice = None
    renderer._select_backend(RenderOptions(scale=2))
    renderer._thumbnail_cache = np.zeros((200, 320, 3), np.uint8)
    try:
        renderer.set_options(RenderOptions(scale=3))
        assert renderer._thumbnail_cache is None
    finally:
        if isinstance(renderer.backend, GLBackend):
            renderer.backend.release()


def test_compose_scene_draws_but_does_not_compute_a_thumbnail(monkeypatch):
    # Finding 1: compose_scene must not pay for a thumbnail that most frames
    # (no modal open) never display -- it only draws and invalidates the
    # cache. scene_thumbnail() is the only thing that ever calls
    # backend.thumbnail(), and only when something actually asks for it.
    renderer = object.__new__(render.Renderer)
    renderer.fallback_notice = None
    calls = []

    class Backend:
        def draw(self, frame):
            calls.append(("draw", frame))

        def thumbnail(self):
            calls.append("thumbnail")
            return np.zeros((200, 320, 3), np.uint8)

    renderer.backend = Backend()
    renderer._thumbnail_cache = "stale"
    result = renderer.compose_scene("frame")
    assert result is None
    assert calls == [("draw", "frame")]
    assert renderer._thumbnail_cache is None


def test_scene_thumbnail_computes_once_and_caches(monkeypatch):
    renderer = object.__new__(render.Renderer)
    renderer.fallback_notice = None
    calls = []
    expected = np.zeros((200, 320, 3), np.uint8)

    class Backend:
        def draw(self, frame):
            pass

        def thumbnail(self):
            calls.append("thumbnail")
            return expected

    renderer.backend = Backend()
    renderer.compose_scene("frame")
    first = renderer.scene_thumbnail()
    second = renderer.scene_thumbnail()
    assert first is expected and second is expected
    assert calls == ["thumbnail"]  # only one real backend.thumbnail() call


def test_compose_scene_falls_back_to_software_when_the_backend_draw_raises(gl_ctx):
    # Finding 3: the spec's "GL failure ... or the backend otherwise raises"
    # fallback was only implemented for construction failures (_select_backend
    # above); a raise from draw() itself had no handling at all and would
    # kill the play loop. compose_scene must catch it, swap to a software
    # backend at scale 1, set the settings notice, and retry the draw once.
    renderer = object.__new__(render.Renderer)
    renderer._ctx = gl_ctx
    renderer.fallback_notice = None
    renderer._select_backend(RenderOptions(scale=4))
    assert isinstance(renderer.backend, GLBackend)
    released = []
    original_release = renderer.backend.release
    renderer.backend.release = lambda: (released.append(True), original_release())[0]

    def boom(_frame):
        raise RuntimeError("driver rejected an oversized texture")

    renderer.backend.draw = boom  # instance-level shadow, not a bound method

    frame = _minimal_gl_frame(np.zeros((200, 320, 3), np.uint8))
    renderer.compose_scene(frame)

    assert released == [True]
    assert isinstance(renderer.backend, SoftwareBackend)
    assert renderer.options.scale == 1
    assert renderer.fallback_notice == "Enhanced rendering unavailable"
    # The retry on the fresh SoftwareBackend must have actually drawn: the
    # thumbnail is real content, not the backend's blank startup frame.
    thumb = renderer.scene_thumbnail()
    assert thumb.shape == (200, 320, 3)


def _minimal_gl_frame(background):
    palette = np.zeros((256, 3), np.uint8)
    view = CameraView(CameraState(0, 0, 0, 0, 0, 0, 1000, 320, 320).angles())
    return FrameDescription(view, ImageAsset(background, False), palette, (), ())


def test_present_orientation_matches_source_for_gl_and_cpu_paths(gl_ctx):
    """Pins the V-flip convention `present()` depends on for both texture
    kinds it draws, using render.py's *actual* fit_quad/_quad_verts/_VSH/
    _FSH -- not a reimplementation -- rendered into an offscreen target FBO
    so the pygame window (unbuildable under a headless SDL driver) is never
    needed. A GL-rendered FBO texture (bottom-up) and a CPU-uploaded
    top-down texture need opposite flip_v values; a swapped/wrong flag on
    either must fail this test loudly."""
    ctx = gl_ctx
    prog = ctx.program(vertex_shader=render._VSH, fragment_shader=render._FSH)
    x0, y0, x1, y1 = render.fit_quad(render.IMG_W, render.IMG_H, 1280, 800)
    vbo_scene = ctx.buffer(render._quad_verts(x0, y0, x1, y1, flip_v=False).tobytes())
    vao_scene = ctx.vertex_array(prog, [(vbo_scene, "2f 2f", "in_pos", "in_uv")])
    vbo_ui = ctx.buffer(render._quad_verts(x0, y0, x1, y1, flip_v=True).tobytes())
    vao_ui = ctx.vertex_array(prog, [(vbo_ui, "2f 2f", "in_pos", "in_uv")])

    target_tex = ctx.texture((320, 200), 4)
    target_fbo = ctx.framebuffer(color_attachments=[target_tex])

    def _read_topdown():
        target_fbo.use()
        data = np.frombuffer(target_tex.read(), dtype=np.uint8).reshape(200, 320, 4)
        return data[::-1]  # GL readback is bottom-up; flip to top-down for assertions

    try:
        # --- GL-backed scene texture (bottom-up FBO texture): top row red,
        # bottom row blue in source data -> must land top red / bottom blue
        # on screen, which needs flip_v=False (_vao_scene's convention).
        background = np.zeros((200, 320, 3), np.uint8)
        background[0] = (255, 0, 0)
        background[-1] = (0, 0, 255)
        backend = GLBackend(ctx, RenderOptions(scale=1, shading="flat"))
        try:
            backend.draw(_minimal_gl_frame(background))
            target_fbo.use()
            ctx.viewport = (0, 0, 320, 200)
            ctx.clear(0.0, 0.0, 0.0, 1.0)
            backend.texture.use(location=0)
            vao_scene.render()
            pixels = _read_topdown()
            assert tuple(pixels[0, 160, :3]) == (255, 0, 0), "top row should be red"
            assert tuple(pixels[199, 160, :3]) == (0, 0, 255), "bottom row should be blue"
        finally:
            backend.release()

        # --- CPU-uploaded top-down texture (the UI canvas / software-path
        # composite): same source convention, needs flip_v=True (_vao_ui's).
        cpu_tex = ctx.texture((320, 200), 4)
        cpu_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        cpu_rgba = np.zeros((200, 320, 4), np.uint8)
        cpu_rgba[0] = (255, 0, 0, 255)
        cpu_rgba[-1] = (0, 0, 255, 255)
        cpu_tex.write(np.ascontiguousarray(cpu_rgba).tobytes())
        try:
            target_fbo.use()
            ctx.viewport = (0, 0, 320, 200)
            ctx.clear(0.0, 0.0, 0.0, 1.0)
            cpu_tex.use(location=0)
            vao_ui.render()
            pixels = _read_topdown()
            assert tuple(pixels[0, 160, :3]) == (255, 0, 0), "top row should be red"
            assert tuple(pixels[199, 160, :3]) == (0, 0, 255), "bottom row should be blue"
        finally:
            cpu_tex.release()
    finally:
        vao_scene.release()
        vbo_scene.release()
        vao_ui.release()
        vbo_ui.release()
        prog.release()
        target_fbo.release()
        target_tex.release()


def test_ui_scale_matches_the_inverse_of_window_to_logical(monkeypatch):
    renderer = object.__new__(Renderer)
    renderer.backend = object.__new__(GLBackend)
    monkeypatch.setattr(pygame.display, "get_window_size", lambda: (1280, 800))
    assert renderer.ui_scale() == 4.0
    # the same expression window_to_logical inverts
    assert renderer.window_to_logical((640, 400)) == (160, 100)


def test_the_software_fallback_keeps_the_ui_at_scale_one(monkeypatch):
    # That path composites the UI against a 320x200 scene thumbnail, so a
    # larger canvas would have nothing sharper to sit on.
    renderer = object.__new__(Renderer)
    renderer.backend = SoftwareBackend()
    monkeypatch.setattr(pygame.display, "get_window_size", lambda: (1280, 800))
    assert renderer.ui_scale() == 1.0


def test_ui_texture_follows_the_canvas_and_releases_the_old_one(gl_ctx):
    # present()'s UI texture must track whatever canvas it is handed rather
    # than staying pinned at 320x200, and the texture it replaces must be
    # released -- not leaked -- since present() runs every frame.
    renderer = object.__new__(Renderer)
    renderer._ctx = gl_ctx
    renderer._ui_tex = gl_ctx.texture((render.IMG_W, render.IMG_H), 4)
    renderer._ui_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
    original = renderer._ui_tex
    released = []
    original_release = original.release
    original.release = lambda: (released.append(True), original_release())[0]
    try:
        # Existing behaviour is unchanged for the universal 320x200 case:
        # same size in, same texture object out, no release.
        same = renderer._ui_texture_for((320, 200))
        assert same is original
        assert same.size == (320, 200)
        assert released == []

        resized = renderer._ui_texture_for((1280, 800))
        assert released == [True]
        assert resized is not original
        assert resized.size == (1280, 800)
        assert resized.filter == (moderngl.NEAREST, moderngl.NEAREST)

        # And it must not raise when handed a further different size in
        # succession.
        again = renderer._ui_texture_for((320, 200))
        assert again.size == (320, 200)
    finally:
        renderer._ui_tex.release()


def test_present_gl_path_blends_ui_canvas_alpha_over_the_scene(gl_ctx):
    """Pins the property the deferred windowed smoke run was meant to eyeball
    (task 9 review, finding: "a clear canvas leaves the scene pixel-exact, a
    painted one blends"): present()'s GL path draws the scene quad first,
    then the UI quad with SRC_ALPHA/ONE_MINUS_SRC_ALPHA blending on top
    (render.py's present()). A fully transparent ui.transparent_canvas()
    must leave the scene untouched pixel-for-pixel; a canvas with one
    half-alpha pixel painted must blend only that pixel, leaving every other
    pixel still scene-exact. Uses render.py's actual shaders/quads (not a
    reimplementation), rendered into an offscreen FBO so the pygame window
    (unbuildable under a headless SDL driver) is never needed."""
    ctx = gl_ctx
    prog = ctx.program(vertex_shader=render._VSH, fragment_shader=render._FSH)
    x0, y0, x1, y1 = render.fit_quad(render.IMG_W, render.IMG_H, 1280, 800)
    vbo_scene = ctx.buffer(render._quad_verts(x0, y0, x1, y1, flip_v=False).tobytes())
    vao_scene = ctx.vertex_array(prog, [(vbo_scene, "2f 2f", "in_pos", "in_uv")])
    vbo_ui = ctx.buffer(render._quad_verts(x0, y0, x1, y1, flip_v=True).tobytes())
    vao_ui = ctx.vertex_array(prog, [(vbo_ui, "2f 2f", "in_pos", "in_uv")])

    target_tex = ctx.texture((320, 200), 4)
    target_fbo = ctx.framebuffer(color_attachments=[target_tex])
    ui_tex = ctx.texture((render.IMG_W, render.IMG_H), 4)
    ui_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)

    def _read_topdown():
        target_fbo.use()
        data = np.frombuffer(target_tex.read(), dtype=np.uint8).reshape(200, 320, 4)
        return data[::-1]  # GL readback is bottom-up; flip to top-down for assertions

    def _present(ui_canvas):
        # Mirrors Renderer.present()'s GL branch exactly: scene quad first
        # (no blend), then the UI quad with the same blend func present()
        # enables.
        target_fbo.use()
        ctx.viewport = (0, 0, 320, 200)
        ctx.clear(0.0, 0.0, 0.0, 1.0)
        backend.texture.use(location=0)
        vao_scene.render()
        ui_tex.write(np.ascontiguousarray(ui_canvas).tobytes())
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        ui_tex.use(location=0)
        vao_ui.render()
        ctx.disable(moderngl.BLEND)
        return _read_topdown()

    background = np.full((200, 320, 3), (100, 150, 200), np.uint8)
    backend = GLBackend(ctx, RenderOptions(scale=1, shading="flat"))
    try:
        backend.draw(_minimal_gl_frame(background))

        # A fully clear canvas must leave every scene pixel untouched.
        clear_pixels = _present(transparent_canvas())
        assert tuple(clear_pixels[100, 160, :3]) == (100, 150, 200)
        assert tuple(clear_pixels[0, 0, :3]) == (100, 150, 200)
        assert tuple(clear_pixels[199, 319, :3]) == (100, 150, 200)

        # A canvas with one half-alpha pixel painted must blend only that
        # pixel: out = src*a + dst*(1-a), a = 128/255 -- everywhere else
        # must stay scene-exact.
        canvas = transparent_canvas()
        canvas[100, 160] = (255, 255, 255, 128)
        blended_pixels = _present(canvas)
        blended = blended_pixels[100, 160, :3].astype(np.int32)
        expected = np.array([178, 203, 228])
        assert np.abs(blended - expected).max() <= 5, blended
        assert tuple(blended_pixels[100, 161, :3]) == (100, 150, 200)
        assert tuple(blended_pixels[0, 0, :3]) == (100, 150, 200)
        assert tuple(blended_pixels[199, 319, :3]) == (100, 150, 200)
    finally:
        backend.release()
        ui_tex.release()
        vao_scene.release()
        vbo_scene.release()
        vao_ui.release()
        vbo_ui.release()
        prog.release()
        target_fbo.release()
        target_tex.release()
