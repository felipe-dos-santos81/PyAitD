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
