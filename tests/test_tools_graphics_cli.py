# SPDX-License-Identifier: GPL-2.0-only
import json
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pytest

from PyAitD.asset_resolver import load_png_rgb
from tests.stub_floor import StubFloor, checker_pixels
from tools import check_overrides as co
from tools import export_backgrounds as xb


def test_parse_floors():
    assert xb.parse_floors("0-7") == [0, 1, 2, 3, 4, 5, 6, 7]
    assert xb.parse_floors("0,3,5") == [0, 3, 5]
    assert xb.parse_floors("2") == [2]
    with pytest.raises(ValueError):
        xb.parse_floors("a")


def test_save_png_round_trips_and_leaves_no_temp(tmp_path):
    rgb = checker_pixels(3)
    path = tmp_path / "sub" / "x.png"
    xb.save_png(path, rgb)
    assert (load_png_rgb(path) == rgb).all()
    assert sorted(p.name for p in path.parent.iterdir()) == ["x.png"]


def test_export_floor_writes_layout_and_records(tmp_path):
    floor = StubFloor(number=2)
    recs = xb.export_floor(floor, tmp_path, 4)
    assert (tmp_path / "backgrounds/floor02/camera000.png").is_file()
    assert (tmp_path / "guides/floor02/camera000.png").is_file()
    assert load_png_rgb(tmp_path / "guides/floor02/camera000.png").shape == (812, 1280, 3)
    assert (load_png_rgb(tmp_path / "backgrounds/floor02/camera000.png") == floor.camera_image(0)).all()
    assert recs[0]["source"] == "backgrounds/floor02/camera000.png"


def test_export_floor_records_missing_image_as_null(tmp_path):
    floor = StubFloor(number=0, images={})
    recs = xb.export_floor(floor, tmp_path, 1)
    assert recs[0]["source"] is None
    assert not (tmp_path / "backgrounds").exists()


def _patch_floors(monkeypatch, numbers):
    def load_floor(data_dir, number):
        if number not in numbers:
            raise FileNotFoundError(f"ETAGE{number:02d}")
        return StubFloor(number=number, images={0: checker_pixels(number)})
    monkeypatch.setattr(xb, "load_floor", load_floor)


def test_main_exports_requested_floors_and_manifest(tmp_path, monkeypatch, capsys):
    _patch_floors(monkeypatch, {0, 1})
    out = tmp_path / "ov"
    rc = xb.main([str(tmp_path), "--out", str(out), "--floors", "0-1", "--guide-scale", "2"])
    assert rc == 0
    m = json.loads((out / "manifest.json").read_text())
    assert m["schema"] == 1 and m["guide_scale"] == 2 and m["data_dir"] == str(tmp_path.resolve())
    assert [(c["floor"], c["camera"]) for c in m["cameras"]] == [(0, 0), (1, 0)]
    assert load_png_rgb(out / "guides/floor01/camera000.png").shape == (412, 640, 3)


def test_main_skips_missing_floor_with_warning(tmp_path, monkeypatch, capsys):
    _patch_floors(monkeypatch, {0})
    rc = xb.main([str(tmp_path), "--out", str(tmp_path / "ov"), "--floors", "0-1"])
    assert rc == 0
    assert "floor 01" in capsys.readouterr().err


def test_main_exit_2_when_nothing_exported(tmp_path, monkeypatch):
    _patch_floors(monkeypatch, set())
    assert xb.main([str(tmp_path), "--out", str(tmp_path / "ov"), "--floors", "0-1"]) == 2


def test_main_exit_2_for_missing_data_dir(tmp_path):
    assert xb.main([str(tmp_path / "nope"), "--out", str(tmp_path / "ov")]) == 2


def test_main_refuses_to_overwrite_existing_export_without_force(tmp_path, monkeypatch):
    _patch_floors(monkeypatch, {0})
    out = tmp_path / "ov"
    assert xb.main([str(tmp_path), "--out", str(out), "--floors", "0"]) == 0
    regenerated = checker_pixels(42)
    xb.save_png(out / "backgrounds/floor00/camera000.png", regenerated)
    assert xb.main([str(tmp_path), "--out", str(out), "--floors", "0"]) == 3
    assert (load_png_rgb(out / "backgrounds/floor00/camera000.png") == regenerated).all()
    assert xb.main([str(tmp_path), "--out", str(out), "--floors", "0", "--force"]) == 0
    assert (load_png_rgb(out / "backgrounds/floor00/camera000.png") == checker_pixels(0)).all()


def test_main_writes_manifest_via_tmp_and_replace(tmp_path, monkeypatch):
    _patch_floors(monkeypatch, {0})
    out = tmp_path / "ov"
    assert xb.main([str(tmp_path), "--out", str(out), "--floors", "0"]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["backgrounds", "guides", "manifest.json"]


def test_main_force_subset_keeps_other_floors_in_manifest(tmp_path, monkeypatch, capsys):
    """--force on a floor subset must not make untouched floors' originals
    look regenerated: their manifest records have to survive the merge."""
    _patch_floors(monkeypatch, {0, 1})
    monkeypatch.setattr(co, "load_floor", xb.load_floor)
    out = tmp_path / "ov"
    assert xb.main([str(tmp_path), "--out", str(out), "--floors", "0-1"]) == 0
    assert xb.main([str(tmp_path), "--out", str(out), "--floors", "0", "--force"]) == 0
    m = json.loads((out / "manifest.json").read_text())
    assert sorted((c["floor"], c["camera"]) for c in m["cameras"]) == [(0, 0), (1, 0)]
    assert co.main([str(tmp_path), str(out), "--floors", "0-1"]) == 0
    text = capsys.readouterr().out
    assert "floor 01: regenerated 0 / original 1 / missing 0 / invalid 0 / aspect 0" in text


def test_makefile_and_gitignore_mention_export():
    mk = open("Makefile").read()
    assert "export-backgrounds:" in mk and "export-backgrounds" in mk.split(".PHONY:")[1].split("\n")[0]
    assert "tools/export_backgrounds.py" in mk
    assert "docs/graphics-proof/overrides/" in open(".gitignore").read()


def test_check_main_round_trip_reports_zero_regenerated(tmp_path, monkeypatch, capsys):
    _patch_floors(monkeypatch, {0, 1})
    monkeypatch.setattr(co, "load_floor", xb.load_floor)
    out = tmp_path / "ov"
    assert xb.main([str(tmp_path), "--out", str(out), "--floors", "0-1"]) == 0
    assert co.main([str(tmp_path), str(out), "--floors", "0-1"]) == 0
    text = capsys.readouterr().out
    assert "total: regenerated 0 / original 2 / missing 0 / invalid 0 / aspect 0" in text


def test_check_main_counts_regenerated_and_fails_on_invalid(tmp_path, monkeypatch, capsys):
    _patch_floors(monkeypatch, {0, 1})
    monkeypatch.setattr(co, "load_floor", xb.load_floor)
    out = tmp_path / "ov"
    xb.main([str(tmp_path), "--out", str(out), "--floors", "0-1"])
    xb.save_png(out / "backgrounds/floor00/camera000.png", checker_pixels(77))
    assert co.main([str(tmp_path), str(out), "--floors", "0-1"]) == 0
    assert "regenerated 1 / original 1" in capsys.readouterr().out
    (out / "backgrounds/floor01/camera000.png").write_bytes(b"not a png")
    assert co.main([str(tmp_path), str(out), "--floors", "0-1"]) == 1
    assert "invalid floor 01 camera 000" in capsys.readouterr().out


def test_check_main_without_manifest_still_checks(tmp_path, monkeypatch, capsys):
    _patch_floors(monkeypatch, {0})
    monkeypatch.setattr(co, "load_floor", xb.load_floor)
    (tmp_path / "ov").mkdir()
    assert co.main([str(tmp_path), str(tmp_path / "ov"), "--floors", "0"]) == 0
    assert "coverage: no manifest" in capsys.readouterr().out


def test_check_main_usage_errors(tmp_path):
    assert co.main([str(tmp_path / "nope"), str(tmp_path)]) == 2
    assert co.main([str(tmp_path), str(tmp_path / "nope")]) == 2
    assert co.main([str(tmp_path), str(tmp_path), "--floors", "x"]) == 2


def test_check_main_rejects_manifest_with_bad_schema(tmp_path, capsys):
    ov = tmp_path / "ov"
    ov.mkdir()
    (ov / "manifest.json").write_text("{}")
    assert co.main([str(tmp_path), str(ov), "--floors", "0"]) == 2
    assert "unsupported schema/shape" in capsys.readouterr().err


def test_render_proof_writes_side_by_side(gl_ctx, tmp_path, monkeypatch):
    floor = StubFloor(number=0)
    ov = tmp_path / "ov"
    xb.save_png(ov / "backgrounds/floor00/camera000.png", checker_pixels(5))
    path = co.render_proof(gl_ctx, floor, 0, ov, tmp_path / "proof", scale=4)
    assert path == tmp_path / "proof" / "floor00-camera000.png"
    assert load_png_rgb(path).shape == (800, 2 * 1280, 3)
    assert co.render_proof(gl_ctx, floor, 0, tmp_path / "empty", tmp_path / "proof") is None


def test_check_main_proof_without_gl_prints_notice(tmp_path, monkeypatch, capsys):
    _patch_floors(monkeypatch, {0})
    monkeypatch.setattr(co, "load_floor", xb.load_floor)
    monkeypatch.setattr(co, "create_context", lambda: (_ for _ in ()).throw(RuntimeError("no gl")))
    (tmp_path / "ov").mkdir()
    assert co.main([str(tmp_path), str(tmp_path / "ov"), "--floors", "0", "--proof", str(tmp_path / "p")]) == 0
    assert "proof skipped" in capsys.readouterr().err


def test_makefile_mentions_check_and_run_overrides():
    mk = open("Makefile").read()
    assert "check-overrides:" in mk and "tools/check_overrides.py" in mk
    run_target = mk.split("\nrun:")[1].split("\n\n")[0]
    assert "--overrides" in run_target and "$(overrides)" in run_target


def test_exported_originals_render_pixel_identical_through_override_path(data_dir, tmp_path):
    """DIR straight from export, used as --overrides, changes nothing."""
    from PyAitD.floor import Floor
    from PyAitD.asset_resolver import AssetResolver
    out = tmp_path / "ov"
    assert xb.main([str(data_dir), "--out", str(out), "--floors", "0"]) == 0
    floor = Floor(data_dir, 0)
    plain = AssetResolver(None, None)
    overridden = AssetResolver(None, out)
    for cam_idx in range(len(floor.cameras)):
        try:
            floor.camera_image(cam_idx)
        except KeyError:
            continue
        a = plain.background(floor, cam_idx)
        b = overridden.background(floor, cam_idx)
        assert b.is_override
        assert (a.pixels == b.pixels).all()
    assert overridden.failures == {}


def test_docs_reference_the_workflow():
    doc = open("docs/ai-background-regeneration.md").read()
    for needle in ("make export-backgrounds", "make check-overrides", "--overrides", "manifest.json",
                   "red", "blue", "green", "invalid", "aspect", "size", "missing", "16:10"):
        assert needle in doc, needle
    assert "ai-background-regeneration.md" in open("README.md").read()
    assert "make export-backgrounds" in open("AGENTS.md").read()


def test_check_overrides_runs_as_a_plain_script(tmp_path):
    """`make check-overrides` invokes tools/check_overrides.py as a script, so
    sys.path[0] is tools/ and `tools.export_backgrounds` must still import."""
    import subprocess
    import sys
    proc = subprocess.run(
        [sys.executable, "tools/check_overrides.py", str(tmp_path / "nope"), str(tmp_path)],
        capture_output=True, text=True, env={**os.environ, "SDL_VIDEODRIVER": "dummy"},
    )
    assert proc.returncode == 2, proc.stderr
    assert "ModuleNotFoundError" not in proc.stderr
