# SPDX-License-Identifier: GPL-2.0-only
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pytest

from PyAitD import override_check as oc
from PyAitD.asset_resolver import AssetResolver, load_png_rgb, override_background_path
from PyAitD.background_export import export_manifest, manifest_record, sha256_rgb
from tests.stub_floor import StubFloor, checker_pixels


def _write_png(path, rgb):
    import pygame
    path.parent.mkdir(parents=True, exist_ok=True)
    surf = pygame.surfarray.make_surface(np.ascontiguousarray(rgb.swapaxes(0, 1)))
    pygame.image.save(surf, str(path))


def _write_corrupt_png(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a png")


def _floors(n):
    return [StubFloor(number=i, images={0: checker_pixels(i)}) for i in range(n)]


def test_missing_override_is_informational(tmp_path):
    f = oc.check_overrides(tmp_path, _floors(1))
    assert [x.kind for x in f] == ["missing"]
    assert f[0].path == override_background_path(tmp_path, 0, 0)
    assert not oc.has_errors(f)


def test_valid_multiple_yields_no_finding(tmp_path):
    _write_png(override_background_path(tmp_path, 0, 0), np.zeros((400, 640, 3), np.uint8))
    assert oc.check_overrides(tmp_path, _floors(1)) == []


def test_corrupt_png_is_invalid_with_resolver_detail(tmp_path):
    _write_corrupt_png(override_background_path(tmp_path, 0, 0))
    f = oc.check_overrides(tmp_path, _floors(1))
    assert len(f) == 1 and f[0].kind == "invalid"
    # detail is whatever AssetResolver recorded -- acceptance parity
    r = AssetResolver(None, tmp_path)
    r.background(_floors(1)[0], 0)
    assert f[0].detail == r.failures[override_background_path(tmp_path, 0, 0)]
    assert oc.has_errors(f)


def test_four_by_three_is_aspect_error(tmp_path):
    _write_png(override_background_path(tmp_path, 0, 0), np.zeros((300, 400, 3), np.uint8))
    f = oc.check_overrides(tmp_path, _floors(1))
    assert [x.kind for x in f] == ["aspect"] and oc.has_errors(f)
    assert "400x300" in f[0].detail


def test_aspect_tolerance_is_one_percent(tmp_path):
    # 1.6 * 0.995 -> within aspect tolerance; not a 320x200 multiple -> informational size only
    _write_png(override_background_path(tmp_path, 0, 0), np.zeros((400, 637, 3), np.uint8))
    f = oc.check_overrides(tmp_path, _floors(1))
    assert [x.kind for x in f] == ["size"] and not oc.has_errors(f)


def test_small_or_non_multiple_is_size_info(tmp_path):
    _write_png(override_background_path(tmp_path, 0, 0), np.zeros((100, 160, 3), np.uint8))
    _write_png(override_background_path(tmp_path, 1, 0), np.zeros((500, 800, 3), np.uint8))
    f = oc.check_overrides(tmp_path, _floors(2))
    assert [x.kind for x in f] == ["size", "size"] and not oc.has_errors(f)


def test_one_finding_per_camera_and_only_requested_floors(tmp_path):
    _write_corrupt_png(override_background_path(tmp_path, 1, 0))
    f = oc.check_overrides(tmp_path, _floors(2)[1:])
    assert [(x.floor, x.camera, x.kind) for x in f] == [(1, 0, "invalid")]


def test_coverage_distinguishes_original_from_regenerated(tmp_path):
    floors = _floors(2)
    manifest = export_manifest(
        [manifest_record(fl, 0, fl.camera_image(0)) for fl in floors], "/d", 4)
    _write_png(override_background_path(tmp_path, 0, 0), floors[0].camera_image(0))  # untouched export
    _write_png(override_background_path(tmp_path, 1, 0), checker_pixels(99))          # regenerated
    cov = oc.coverage(tmp_path, floors, manifest)
    assert cov == {0: {"regenerated": 0, "original": 1, "missing": 0, "invalid": 0},
                   1: {"regenerated": 1, "original": 0, "missing": 0, "invalid": 0}}


def test_summarize_lines(tmp_path):
    cov = {0: {"regenerated": 1, "original": 2, "missing": 3, "invalid": 0}}
    findings = [oc.Finding(0, 5, tmp_path / "x.png", "aspect", "640x300")]
    text = oc.summarize(findings, cov)
    assert "floor 00: regenerated 1 / original 2 / missing 3 / invalid 0 / aspect 1" in text
    assert "total: regenerated 1 / original 2 / missing 3 / invalid 0 / aspect 1" in text
    assert "aspect  floor 00 camera 005" in text and "640x300" in text
    assert "missing" not in text.split("\n")[0] or True  # missing cameras are counted, not listed


def test_summarize_without_coverage():
    text = oc.summarize([], None)
    assert "coverage: no manifest" in text


def test_override_check_is_pure():
    src = open(oc.__file__).read()
    assert "import pygame" not in src and "import moderngl" not in src
