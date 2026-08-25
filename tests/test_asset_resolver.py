# SPDX-License-Identifier: GPL-2.0-only
import logging
from types import SimpleNamespace

import numpy as np
import pytest

from PyAitD.asset_resolver import (
    AssetResolver, ImageAsset, load_png_rgb, override_background_path, override_palette_path,
)


def _floor(number=3):
    original = np.full((200, 320, 3), 7, dtype=np.uint8)
    return SimpleNamespace(number=number, palette=np.zeros((256, 3), dtype=np.uint8),
                           camera_image=lambda idx: original)


def test_paths_follow_the_convention(tmp_path):
    assert override_background_path(tmp_path, 3, 12) == tmp_path / "backgrounds" / "floor03" / "camera012.png"
    assert override_palette_path(tmp_path) == tmp_path / "palette.png"


def test_no_override_dir_returns_original():
    resolver = AssetResolver(SimpleNamespace(body=lambda n: n), None)
    asset = resolver.background(_floor(), 0)
    assert isinstance(asset, ImageAsset) and not asset.is_override and asset.pixels.shape == (200, 320, 3)
    assert resolver.body(5) == 5


def test_override_dir_set_but_file_absent_falls_back_silently(tmp_path, caplog):
    def fail_if_called(p):
        raise AssertionError("load_png must not be called when the override file is absent")
    resolver = AssetResolver(None, tmp_path, load_png=fail_if_called)
    with caplog.at_level(logging.WARNING, logger="PyAitD.assets"):
        asset = resolver.background(_floor(), 0)
    assert not asset.is_override and asset.pixels.shape == (200, 320, 3)
    assert not resolver.failures
    assert not caplog.records


def test_override_png_is_used_at_any_size(tmp_path):
    path = override_background_path(tmp_path, 3, 0)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"png")
    big = np.zeros((800, 1280, 3), dtype=np.uint8)
    resolver = AssetResolver(None, tmp_path, load_png=lambda p: big)
    asset = resolver.background(_floor(), 0)
    assert asset.is_override and asset.pixels is big


def test_unreadable_override_logs_once_and_falls_back(tmp_path, caplog):
    path = override_background_path(tmp_path, 3, 0)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"bad")
    def boom(p):
        raise ValueError("corrupt")
    resolver = AssetResolver(None, tmp_path, load_png=boom)
    with caplog.at_level(logging.WARNING, logger="PyAitD.assets"):
        first = resolver.background(_floor(), 0)
        second = resolver.background(_floor(), 0)
    assert not first.is_override and not second.is_override
    assert sum("corrupt" in r.message for r in caplog.records) == 1
    assert path in resolver.failures


def test_palette_override_must_be_256_wide(tmp_path):
    override_palette_path(tmp_path).write_bytes(b"png")
    resolver = AssetResolver(None, tmp_path, load_png=lambda p: np.ones((1, 256, 3), dtype=np.uint8))
    assert resolver.palette(_floor()).shape == (256, 3) and resolver.palette(_floor())[0].tolist() == [1, 1, 1]
    resolver = AssetResolver(None, tmp_path, load_png=lambda p: np.ones((1, 16, 3), dtype=np.uint8))
    assert resolver.palette(_floor()).tolist() == np.zeros((256, 3), dtype=np.uint8).tolist()


def test_greyscale_override_is_rejected_logged_and_falls_back(tmp_path, caplog):
    path = override_background_path(tmp_path, 3, 0)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"grey")
    greyscale = np.zeros((200, 320), dtype=np.uint8)  # ndim == 2, no channel axis
    resolver = AssetResolver(None, tmp_path, load_png=lambda p: greyscale)
    with caplog.at_level(logging.WARNING, logger="PyAitD.assets"):
        asset = resolver.background(_floor(), 0)
    assert not asset.is_override and asset.pixels.shape == (200, 320, 3)
    assert path in resolver.failures
    assert sum(r.levelno == logging.WARNING for r in caplog.records) == 1


def test_rgba_override_is_rejected_logged_and_falls_back(tmp_path, caplog):
    path = override_background_path(tmp_path, 3, 0)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"rgba")
    rgba = np.zeros((200, 320, 4), dtype=np.uint8)  # 4 channels, not the required 3
    resolver = AssetResolver(None, tmp_path, load_png=lambda p: rgba)
    with caplog.at_level(logging.WARNING, logger="PyAitD.assets"):
        asset = resolver.background(_floor(), 0)
    assert not asset.is_override and asset.pixels.shape == (200, 320, 3)
    assert path in resolver.failures
    assert sum(r.levelno == logging.WARNING for r in caplog.records) == 1


def test_load_png_rgb_axis_order_and_dtype(tmp_path):
    import pygame
    width, height = 5, 3  # deliberately W != H so a transpose bug is detectable
    surface = pygame.Surface((width, height))
    surface.fill((10, 20, 30))
    surface.set_at((width - 1, 0), (200, 150, 50))  # rightmost column, top row
    surface.set_at((0, height - 1), (5, 250, 100))  # leftmost column, bottom row
    path = tmp_path / "axis_check.png"
    pygame.image.save(surface, str(path))

    arr = load_png_rgb(path)

    assert arr.shape == (height, width, 3)
    assert arr.dtype == np.uint8
    assert arr[0, 0].tolist() == [10, 20, 30]
    assert arr[0, width - 1].tolist() == [200, 150, 50]
    assert arr[height - 1, 0].tolist() == [5, 250, 100]
