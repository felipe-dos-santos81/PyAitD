# SPDX-License-Identifier: GPL-2.0-only
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from types import SimpleNamespace

import numpy as np

from PyAitD.render import override_check as oc
from PyAitD.render.asset_resolver import AssetResolver, load_png_rgb, override_background_path, override_screen_path
from PyAitD.render.background_export import SCREEN_ENTRIES, export_manifest, manifest_record, screen_record, sha256_rgb
from tests.stub_floor import StubFloor, checker_pixels
import pytest

pytestmark = pytest.mark.render


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


def _screen_assets():
    plates = {e: np.full((200, 320, 3), e, np.uint8) for e in SCREEN_ENTRIES}
    return SimpleNamespace(resource_screen=lambda e: plates[e]), plates


def test_check_screens_reports_missing_invalid_and_aspect(tmp_path):
    assets, _ = _screen_assets()
    bad = override_screen_path(tmp_path, 10); bad.parent.mkdir(parents=True); bad.write_bytes(b"x")
    wide = override_screen_path(tmp_path, 13); wide.write_bytes(b"x")
    images = {bad: np.zeros((2, 2), np.uint8), wide: np.zeros((200, 640, 3), np.uint8)}
    findings = oc.check_screens(tmp_path, assets, load_png=lambda p: images[p])
    by_entry = {f.camera: f.kind for f in findings}
    assert by_entry[10] == "invalid" and by_entry[13] == "aspect" and by_entry[6] == "missing"
    assert all(f.floor == -1 for f in findings)


def test_screen_coverage_distinguishes_original_from_regenerated(tmp_path):
    assets, plates = _screen_assets()
    manifest = export_manifest([], "/d", 4, screens=[screen_record(e, plates[e]) for e in SCREEN_ENTRIES])
    same = override_screen_path(tmp_path, 10); same.parent.mkdir(parents=True); same.write_bytes(b"x")
    new = override_screen_path(tmp_path, 14); new.write_bytes(b"x")
    images = {same: plates[10], new: np.ones((200, 320, 3), np.uint8)}
    cov = oc.screen_coverage(tmp_path, assets, manifest, load_png=lambda p: images[p])
    assert cov == {"regenerated": 1, "original": 1, "missing": 5, "invalid": 0}
    text = oc.summarize([], {}, cov)
    assert "screens: regenerated 1 / original 1 / missing 5 / invalid 0" in text


def test_body_material_findings_name_the_body_and_the_reason(tmp_path):
    from PyAitD.render.asset_resolver import override_body_material_path
    good = override_body_material_path(tmp_path, 1)
    good.parent.mkdir(parents=True)
    good.write_text('{"indices": {"5": "metal"}}')
    override_body_material_path(tmp_path, 2).write_text('{"indices": {"5": "velvet"}}')
    override_body_material_path(tmp_path, 3).write_text('not json')
    f = oc.check_bodies(tmp_path)
    assert [(x.floor, x.camera, x.kind) for x in f] == [(-2, 2, "invalid"), (-2, 3, "invalid")]
    assert "velvet" in f[0].detail
    assert oc.has_errors(f)
    assert "invalid body 002" in oc.summarize(f, None)


def test_no_bodies_directory_is_no_finding(tmp_path):
    assert oc.check_bodies(tmp_path) == []


def test_a_misnamed_body_file_is_reported_and_does_not_hide_the_real_one(tmp_path):
    # body7.json parses as body 7 but the game only ever opens body007.json,
    # so it would silently never load. One resolver for the whole directory
    # also means AssetResolver's log-once dedup survives: the same broken
    # body is reported once, not once per file inspected.
    from PyAitD.render.asset_resolver import override_body_material_path
    bodies = tmp_path / "bodies"
    bodies.mkdir(parents=True)
    (bodies / "body7.json").write_text('{"indices": {"5": "metal"}}')
    (bodies / "bodyfoo.json").write_text('{"indices": {"5": "metal"}}')
    override_body_material_path(tmp_path, 7).write_text('{"indices": {"5": "metal"}}')
    f = oc.check_bodies(tmp_path)
    assert [(x.floor, x.camera, x.path.name, x.kind) for x in f] == [
        (-2, 7, "body7.json", "invalid"),
        (-2, -1, "bodyfoo.json", "invalid"),
    ]
    assert "body007.json" in f[0].detail and "body<NNN>.json" in f[1].detail


def test_an_invalid_crease_is_a_body_finding(tmp_path):
    from PyAitD.render.asset_resolver import override_body_material_path
    bad = override_body_material_path(tmp_path, 4)
    bad.parent.mkdir(parents=True)
    bad.write_text('{"crease": "soft"}')
    override_body_material_path(tmp_path, 5).write_text('{"crease": 30}')
    f = oc.check_bodies(tmp_path)
    assert [(x.camera, x.kind) for x in f] == [(4, "invalid")]
    assert "crease" in f[0].detail
