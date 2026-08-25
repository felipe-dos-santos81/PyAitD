# SPDX-License-Identifier: GPL-2.0-only
import json
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pytest

from PyAitD.asset_resolver import load_png_rgb
from tests.stub_floor import StubFloor, checker_pixels
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


def test_makefile_and_gitignore_mention_export():
    mk = open("Makefile").read()
    assert "export-backgrounds:" in mk and "export-backgrounds" in mk.split(".PHONY:")[1].split("\n")[0]
    assert "tools/export_backgrounds.py" in mk
    assert "docs/graphics-proof/overrides/" in open(".gitignore").read()
