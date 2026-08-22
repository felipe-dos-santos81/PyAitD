# SPDX-License-Identifier: GPL-2.0-only
import math

import moderngl
import numpy as np

from maitd.render import Renderer, fit_quad
from maitd.render import _ActorLayer
from maitd.mask import Mask
from maitd.skel import PrimEntry, RenderResult


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


def test_compose_scene_returns_rgb_without_presenting(monkeypatch):
    renderer = object.__new__(Renderer)
    expected = np.zeros((200, 320, 3), dtype=np.uint8)
    monkeypatch.setattr(renderer, "_compose_existing_scene", lambda *args: expected)
    assert renderer.compose_scene(None, [], [], None, [], []) is expected


def test_actor_layer_preserves_far_to_near_order_across_rooms():
    ctx = moderngl.create_standalone_context()
    palette = np.zeros((256, 3), dtype=np.uint8)
    palette[1] = (255, 0, 0)
    palette[2] = (0, 255, 0)
    palette[3] = (0, 0, 255)
    layer = _ActorLayer(ctx, palette)
    try:
        # The caller has already sorted these actors far-to-near. Room
        # membership must not regroup them into a different painter order.
        results = [
            RenderResult([], [PrimEntry(2, 1, [(20, 10, 1)])]),
            RenderResult([], [PrimEntry(2, 2, [(20, 10, 1)])]),
            RenderResult([], [PrimEntry(2, 3, [(20, 10, 1)])]),
        ]
        layer.draw(results, [0, 1, 0], [])
        pixels = np.frombuffer(layer._tex.read(), dtype=np.uint8).reshape(200, 320, 4)[::-1]
        assert tuple(pixels[10, 20, :3]) == (0, 0, 255)
    finally:
        layer._fbo.release()
        layer._tex.release()
        layer._prog.release()
        ctx.release()


def test_actor_layer_keeps_near_polygon_when_far_polygon_is_submitted_last():
    ctx = moderngl.create_standalone_context()
    palette = np.zeros((256, 3), dtype=np.uint8)
    palette[1] = (255, 0, 0)
    palette[2] = (0, 0, 255)
    layer = _ActorLayer(ctx, palette)
    try:
        # FITD writes and tests polygon depth. Body primitives are not ordered
        # front-to-back, so a later back face must not cover a nearer front.
        near = PrimEntry(1, 1, [(10, 10, 100), (30, 10, 100), (10, 30, 100)])
        far = PrimEntry(1, 2, [(10, 10, 1000), (30, 10, 1000), (10, 30, 1000)])

        layer.draw([RenderResult([], [near, far])], [0], [])

        pixels = np.frombuffer(layer._tex.read(), dtype=np.uint8).reshape(200, 320, 4)[::-1]
        assert tuple(pixels[15, 15, :3]) == (255, 0, 0)
    finally:
        layer._fbo.release()
        layer._tex.release()
        layer._prog.release()
        ctx.release()


def test_actor_mask_erases_only_actor_inside_spatial_trigger():
    ctx = moderngl.create_standalone_context()
    palette = np.zeros((256, 3), dtype=np.uint8)
    palette[1] = (255, 0, 0)
    palette[2] = (0, 0, 255)
    layer = _ActorLayer(ctx, palette)
    try:
        far = RenderResult([], [PrimEntry(2, 1, [(20, 10, 1)])])
        near = RenderResult([], [PrimEntry(2, 2, [(20, 10, 1)])])
        bitmap = np.zeros((200, 320), dtype=np.uint8)
        bitmap[10, 20] = 255
        mask = Mask(
            20, 10, 20, 10, bitmap,
            viewed_room=0,
            test_rects=((1, 3, 2, 4),),
        )
        far_zv = (1000, 1100, 0, 0, 1000, 1100)
        near_zv = (10, 20, 0, 0, 30, 40)

        layer.draw(
            [far, near], [0, 0], [mask],
            actor_zvs=[far_zv, near_zv],
        )

        pixels = np.frombuffer(layer._tex.read(), dtype=np.uint8).reshape(200, 320, 4)[::-1]
        assert tuple(pixels[10, 20, :3]) == (255, 0, 0)
    finally:
        layer._fbo.release()
        layer._tex.release()
        layer._prog.release()
        ctx.release()
