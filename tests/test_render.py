# SPDX-License-Identifier: GPL-2.0-only
import math

import numpy as np

from maitd.render import Renderer, fit_quad


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
