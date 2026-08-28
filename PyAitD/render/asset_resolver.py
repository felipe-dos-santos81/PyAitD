# SPDX-License-Identifier: GPL-2.0-only
"""Visual asset lookup (camera backgrounds, palette, full-screen resources) with an optional user override directory.

Only load_png_rgb touches pygame; everything else is pure so headless tests
inject a loader."""
from dataclasses import dataclass
import logging
from pathlib import Path

import numpy as np

from PyAitD.render.lighting import estimate_light

log = logging.getLogger("PyAitD.engine.assets")


@dataclass(frozen=True)
class ImageAsset:
    pixels: np.ndarray
    is_override: bool


def override_background_path(override_dir, floor_number, cam_idx):
    return Path(override_dir) / "backgrounds" / f"floor{floor_number:02d}" / f"camera{cam_idx:03d}.png"


def override_palette_path(override_dir):
    return Path(override_dir) / "palette.png"


def override_screen_path(override_dir, entry):
    # Full-screen ITD_RESS resources (title, character select, story, letter,
    # book, notebook, dead end). Mirrored by background_export.screen_rel_path.
    return Path(override_dir) / "screens" / f"ress{entry:02d}.png"


def load_png_rgb(path):
    import pygame
    surface = pygame.image.load(str(path))
    return np.ascontiguousarray(pygame.surfarray.array3d(surface).swapaxes(0, 1)).astype(np.uint8)


class AssetResolver:
    def __init__(self, assets, override_dir=None, *, load_png=load_png_rgb):
        self._assets = assets
        self._override_dir = Path(override_dir) if override_dir else None
        self._load_png = load_png
        self._cache = {}
        self._lights = {}
        self.failures = {}

    def body(self, num):
        return self._assets.body(num)

    def _override(self, path, validate):
        if self._override_dir is None or path in self.failures:
            return None
        if path in self._cache:
            return self._cache[path]
        if not path.is_file():
            # A normal override directory leaves most floor/camera combinations
            # un-overridden, so a plain absence is expected steady-state, not a
            # failure: fall back silently, with no log and no failures entry.
            # Only an override that exists but is unreadable or invalid logs.
            return None
        try:
            pixels = self._load_png(path)
            validate(pixels)
        except Exception as exc:  # any loader/validation failure degrades, never crashes
            self.failures[path] = str(exc)
            log.warning("override %s ignored: %s", path, exc)
            return None
        self._cache[path] = pixels
        return pixels

    def background(self, floor, cam_idx):
        if self._override_dir is not None:
            pixels = self._override(
                override_background_path(self._override_dir, floor.number, cam_idx),
                _require_rgb,
            )
            if pixels is not None:
                return ImageAsset(pixels.astype(np.uint8, copy=False), True)
        return ImageAsset(floor.camera_image(cam_idx), False)

    def palette(self, floor):
        if self._override_dir is not None:
            pixels = self._override(override_palette_path(self._override_dir), _require_palette)
            if pixels is not None:
                return np.ascontiguousarray(pixels[0, :256, :3]).astype(np.uint8)
        return floor.palette

    def light(self, floor, cam_idx):
        """The SceneLight for a camera, estimated from whatever background
        that camera actually resolves to -- an override, including an
        AI-regenerated plate, is estimated from the override rather than
        from the original.

        Memoised per (floor, camera) exactly as backgrounds are: a camera's
        light is a property of a static image, so one estimate per camera
        per session is all this can ever need."""
        key = (floor.number, cam_idx)
        if key not in self._lights:
            self._lights[key] = estimate_light(self.background(floor, cam_idx).pixels)
        return self._lights[key]

    def resource_screen(self, entry):
        if self._override_dir is not None:
            pixels = self._override(override_screen_path(self._override_dir, entry), _require_rgb)
            if pixels is not None:
                return ImageAsset(pixels.astype(np.uint8, copy=False), True)
        return ImageAsset(self._assets.resource_screen(entry), False)


# Below every GL 3.3 core implementation's guaranteed GL_MAX_TEXTURE_SIZE
# floor (the spec requires >=1024, but every real driver we've seen goes far
# higher; this stays conservative), so an override this size or smaller can
# never be the reason ctx.texture() raises in render_gl.py. A crash from an
# enormous-but-otherwise-valid override PNG is exactly the failure mode
# render.Renderer.compose_scene's draw-failure fallback exists to catch --
# this is a second, earlier line of defence with a clearer error message.
_MAX_OVERRIDE_DIMENSION = 8192


def _require_rgb(pixels):
    if pixels.ndim != 3 or pixels.shape[2] != 3 or pixels.shape[0] < 1 or pixels.shape[1] < 1:
        raise ValueError(f"expected an RGB image, got shape {pixels.shape}")
    if pixels.shape[0] > _MAX_OVERRIDE_DIMENSION or pixels.shape[1] > _MAX_OVERRIDE_DIMENSION:
        raise ValueError(
            f"image {pixels.shape[1]}x{pixels.shape[0]} exceeds the "
            f"{_MAX_OVERRIDE_DIMENSION}x{_MAX_OVERRIDE_DIMENSION} override limit"
        )


def _require_palette(pixels):
    _require_rgb(pixels)
    if pixels.shape[1] != 256:
        raise ValueError(f"palette must be 256 pixels wide, got {pixels.shape[1]}")
