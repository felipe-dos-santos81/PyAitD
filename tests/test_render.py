# SPDX-License-Identifier: GPL-2.0-only
import math

import numpy as np
import pygame

import PyAitD.render as render
from PyAitD.render import Renderer, _rgba, composite_ui, fit_quad
from PyAitD.render_gl import GLBackend
from PyAitD.render_options import RenderOptions
from PyAitD.render_soft import SoftwareBackend


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


def test_rgba_pads_opaque_alpha_and_passes_through_rgba():
    rgb = np.full((200, 320, 3), 9, np.uint8)
    padded = _rgba(rgb)
    assert padded.shape == (200, 320, 4)
    assert tuple(padded[0, 0]) == (9, 9, 9, 255)

    rgba = np.zeros((200, 320, 4), np.uint8)
    rgba[0, 0] = (1, 2, 3, 4)
    assert _rgba(rgba) is rgba or tuple(_rgba(rgba)[0, 0]) == (1, 2, 3, 4)


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


def test_compose_scene_returns_backend_thumbnail(monkeypatch):
    renderer = object.__new__(render.Renderer)
    expected = np.zeros((200, 320, 3), np.uint8)

    class Backend:
        def draw(self, frame):
            self.drawn = frame

        def thumbnail(self):
            return expected

    renderer.backend = Backend()
    result = renderer.compose_scene("frame")
    assert result is expected
    assert result.shape == (200, 320, 3)
    assert renderer.backend.drawn == "frame"
