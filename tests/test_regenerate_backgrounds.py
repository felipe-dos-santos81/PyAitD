# SPDX-License-Identifier: GPL-2.0-only
import io
import json
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pytest

from tests.stub_floor import checker_pixels
from tools import export_backgrounds as xb
from tools import regenerate_backgrounds as rb


def make_in_dir(root):
    """floor00: camera000 (with guide), camera001 (no guide); floor01: camera000 (with guide)."""
    in_dir = root / "in"
    for key, guide in (("floor00/camera000", True), ("floor00/camera001", False), ("floor01/camera000", True)):
        xb.save_png(in_dir / "backgrounds" / f"{key}.png", checker_pixels(hash(key) % 100))
        if guide:
            xb.save_png(in_dir / "guides" / f"{key}.png", np.zeros((812, 1280, 3), np.uint8))
    return in_dir


def test_discover_lists_cameras_sorted_with_optional_guides(tmp_path):
    in_dir = make_in_dir(tmp_path)
    cams = rb.discover(in_dir, None)
    assert [c.key for c in cams] == ["floor00/camera000", "floor00/camera001", "floor01/camera000"]
    assert cams[0].floor == 0 and cams[0].camera == 0
    assert cams[0].guide == in_dir / "guides/floor00/camera000.png"
    assert cams[1].guide is None
    assert cams[2].source == in_dir / "backgrounds/floor01/camera000.png"


def test_discover_filters_floors_and_handles_missing_dir(tmp_path):
    in_dir = make_in_dir(tmp_path)
    assert [c.key for c in rb.discover(in_dir, {1})] == ["floor01/camera000"]
    assert rb.discover(tmp_path / "nowhere", None) == []


def test_prompts_mention_guide_only_when_present():
    assert "second image" in rb.describe_prompt(True)
    assert "second image" not in rb.describe_prompt(False)
    g = rb.generation_prompt("a dusty attic", "film grain.", True)
    assert "a dusty attic" in g and g.endswith("film grain.") and "second image" in g
    assert "second image" not in rb.generation_prompt("x", "s", False)


def test_prompt_cache_round_trip_is_atomic(tmp_path):
    path = tmp_path / rb.PROMPTS_FILE
    assert rb.load_prompts(path) == {}
    rb.save_prompts(path, {"floor00/camera000": {"prompt": "p", "model": "m", "sha256": "s"}})
    assert rb.load_prompts(path)["floor00/camera000"]["prompt"] == "p"
    assert sorted(p.name for p in tmp_path.iterdir()) == [rb.PROMPTS_FILE]


import types as _t


def png_bytes(rgb):
    import pygame
    surf = pygame.surfarray.make_surface(np.ascontiguousarray(rgb.swapaxes(0, 1)))
    buf = io.BytesIO()
    pygame.image.save(surf, buf, "png")
    return buf.getvalue()


def _response(text=None, image=None, mime="image/png"):
    if image is None:
        part = _t.SimpleNamespace(inline_data=None, text=text)
    else:
        part = _t.SimpleNamespace(inline_data=_t.SimpleNamespace(data=image, mime_type=mime), text=None)
    return _t.SimpleNamespace(text=text, candidates=[_t.SimpleNamespace(content=_t.SimpleNamespace(parts=[part]))])


class FakeClient:
    """Records calls; image models return `image_png`, text models a fixed
    description. The Nth image call (1-based) in `fail_image_calls` raises."""

    def __init__(self, image_png=None, fail_image_calls=(), no_image=False):
        self.image_png = image_png
        self.fail = set(fail_image_calls)
        self.no_image = no_image
        self.calls = []
        self.image_calls = 0
        self.models = self

    def generate_content(self, *, model, contents, config=None):
        self.calls.append((model, contents, config))
        if "image" in model:
            self.image_calls += 1
            if self.image_calls in self.fail:
                raise RuntimeError("quota")
            if self.no_image:
                return _response(text="sorry")
            return _response(image=self.image_png)
        return _response(text="  a dusty attic under sloped rafters  ")


def test_describe_sends_source_guide_and_prompt(tmp_path):
    in_dir = make_in_dir(tmp_path)
    cam = rb.discover(in_dir, None)[0]
    client = FakeClient()
    assert rb.describe(client, "gemini-2.5-flash", cam) == "a dusty attic under sloped rafters"
    model, contents, config = client.calls[0]
    assert model == "gemini-2.5-flash"
    assert contents[0] == {"inline_data": {"mime_type": "image/png", "data": cam.source.read_bytes()}}
    assert contents[1] == {"inline_data": {"mime_type": "image/png", "data": cam.guide.read_bytes()}}
    assert contents[2] == rb.describe_prompt(True)


def test_describe_without_guide_sends_two_parts(tmp_path):
    cam = rb.discover(make_in_dir(tmp_path), None)[1]
    client = FakeClient()
    rb.describe(client, "gemini-2.5-flash", cam)
    contents = client.calls[0][1]
    assert len(contents) == 2 and contents[1] == rb.describe_prompt(False)


def test_generate_requests_image_and_returns_first_image_part(tmp_path):
    cam = rb.discover(make_in_dir(tmp_path), None)[0]
    png = png_bytes(np.zeros((1024, 1536, 3), np.uint8))
    client = FakeClient(png)
    assert rb.generate(client, "gemini-2.5-flash-image", cam, "desc") == png
    model, contents, config = client.calls[0]
    assert config == {"response_modalities": ["IMAGE"], "image_config": {"aspect_ratio": "3:2"}}
    assert contents[2] == "desc"


def test_generate_without_image_part_raises(tmp_path):
    cam = rb.discover(make_in_dir(tmp_path), None)[0]
    with pytest.raises(RuntimeError, match="no image in response"):
        rb.generate(FakeClient(no_image=True), "gemini-2.5-flash-image", cam, "desc")


def test_generate_skips_candidates_without_content(tmp_path):
    cam = rb.discover(make_in_dir(tmp_path), None)[0]
    response = _t.SimpleNamespace(
        text=None,
        candidates=[
            _t.SimpleNamespace(content=None),
            _t.SimpleNamespace(content=_t.SimpleNamespace(parts=None)),
        ],
    )

    class _NoContentClient:
        def __init__(self):
            self.models = self

        def generate_content(self, *, model, contents, config=None):
            return response

    with pytest.raises(RuntimeError, match="no image in response"):
        rb.generate(_NoContentClient(), "gemini-2.5-flash-image", cam, "desc")
