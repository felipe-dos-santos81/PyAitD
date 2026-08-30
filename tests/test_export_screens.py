# SPDX-License-Identifier: GPL-2.0-only
import json
import os
from types import SimpleNamespace
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np

from PyAitD.render import texture_export as be
from tools import export_textures as xb
import pytest

pytestmark = pytest.mark.tools


def _assets():
    plates = {e: np.full((200, 320, 3), e, np.uint8) for e in be.SCREEN_ENTRIES}
    return SimpleNamespace(resource_screen=lambda e: plates[e])


def test_export_screens_writes_plate_guide_and_records(tmp_path):
    saved = {}
    records = xb.export_screens(_assets(), tmp_path, 2, save=lambda p, rgb: saved.__setitem__(p, rgb.shape))
    assert [r["entry"] for r in records] == list(be.SCREEN_ENTRIES)
    assert saved[tmp_path / "screens" / "ress10.png"] == (200, 320, 3)
    assert saved[tmp_path / "guides" / "screens" / "ress10.png"] == (400 + be.GUIDE_FOOTER, 640, 3)


def test_export_screens_continues_after_a_damaged_entry(tmp_path, capsys):
    """A single damaged ITD_RESS entry must not discard the records/files of
    entries already exported earlier in the loop, nor block the ones after
    it -- the way a whole-loop try/except (which this replaces) would."""
    def resource_screen(entry):
        if entry == 8:
            raise ValueError("ITD_RESS.PAK: entry 8 is 100 bytes; expected 64000")
        return np.full((200, 320, 3), entry, np.uint8)
    assets = SimpleNamespace(resource_screen=resource_screen)
    records = xb.export_screens(assets, tmp_path, 1)
    assert [r["entry"] for r in records] == [e for e in be.SCREEN_ENTRIES if e != 8]
    assert (tmp_path / "screens" / "ress06.png").is_file()       # before the damaged entry: kept
    assert (tmp_path / "screens" / "ress10.png").is_file()       # after the damaged entry: still ran
    assert not (tmp_path / "screens" / "ress08.png").exists()
    assert "screen 8 (CARNET) skipped" in capsys.readouterr().err


def test_merge_keeps_other_kinds_records(tmp_path):
    manifest = be.export_manifest([{"floor": 0, "camera": 0, "sha256": "a"}], "/d", 4,
                                  screens=[{"entry": 10, "sha256": "s"}])
    xb.save_manifest(tmp_path, manifest)
    cams = xb._merge_manifest_records(tmp_path, [{"floor": 1, "camera": 0, "sha256": "b"}])
    assert {(c["floor"], c["camera"]) for c in cams} == {(0, 0), (1, 0)}
    screens = xb._merge_manifest_records(tmp_path, [{"entry": 13, "sha256": "t"}], key="screens")
    assert {s["entry"] for s in screens} == {10, 13}


def test_main_refuses_existing_screens_without_force(tmp_path, monkeypatch):
    (tmp_path / "out" / "screens").mkdir(parents=True)
    assert xb.main([str(tmp_path), "--out", str(tmp_path / "out")]) == 3


def test_main_no_screens_ignores_existing_screens_dir(tmp_path, monkeypatch):
    """--no-screens does not write screens/, so an existing screens/ (e.g.
    from a previous --screens run) must not block it -- only backgrounds/,
    which this run does write, should still be guarded."""
    from tests.stub_floor import StubFloor
    monkeypatch.setattr(xb, "load_floor", lambda data, n: StubFloor(number=n))
    out = tmp_path / "out"
    (out / "screens").mkdir(parents=True)
    assert xb.main([str(tmp_path), "--out", str(out), "--floors", "0", "--no-screens"]) == 0
    assert (out / "backgrounds").is_dir()


def test_main_exports_screens_and_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(xb, "load_floor", lambda data, n: (_ for _ in ()).throw(FileNotFoundError("no floor")))
    monkeypatch.setattr(xb, "load_assets", lambda data: _assets())
    monkeypatch.setattr(xb, "save_png", lambda p, rgb: (p.parent.mkdir(parents=True, exist_ok=True), p.write_bytes(b"png")))
    out = tmp_path / "out"
    assert xb.main([str(tmp_path), "--out", str(out), "--floors", "0"]) == 0
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["schema"] == 3 and manifest["cameras"] == []
    assert [s["entry"] for s in manifest["screens"]] == list(be.SCREEN_ENTRIES)
    assert (out / "screens" / "ress13.png").is_file()


def test_real_screens_export_and_check_round_trip(data_dir, tmp_path):
    from PyAitD.render import texture_check as oc
    from tools.export_textures import load_assets
    assets = load_assets(data_dir)
    records = xb.export_screens(assets, tmp_path, 1)
    assert len(records) == 7 and all(r["size"] == [320, 200] for r in records)
    findings = oc.check_screens(tmp_path, assets)
    assert findings == []            # every exported original loads and is 320x200
    cov = oc.screen_coverage(tmp_path, assets, be.export_manifest([], data_dir, 1, screens=records))
    assert cov == {"regenerated": 0, "original": 7, "missing": 0, "invalid": 0}


def test_export_floor_writes_layout_sidecars(tmp_path):
    from tests.stub_floor import StubFloor
    saved = {}
    records = xb.export_floor(StubFloor(), tmp_path, 2, save=lambda p, rgb: saved.__setitem__(p, rgb.shape))
    path = tmp_path / "guides" / "floor00" / "camera000.json"
    layout = json.loads(path.read_text())
    assert layout["schema"] == 1 and len(layout["masks"]) == 1 and len(layout["collision"]) == 1
    assert records[0]["layout"] == "guides/floor00/camera000.json"
    assert not path.with_name(path.name + ".tmp").exists()
    assert saved[tmp_path / "guides" / "floor00" / "camera000.png"] == (400 + be.GUIDE_FOOTER, 640, 3)


def test_export_floor_skips_the_sidecar_of_a_missing_image(tmp_path):
    from tests.stub_floor import StubFloor
    records = xb.export_floor(StubFloor(images={}), tmp_path, 2, save=lambda p, rgb: None)
    assert records[0]["layout"] is None
    assert not (tmp_path / "guides").exists()


def test_export_screens_writes_layout_sidecars(tmp_path):
    records = xb.export_screens(_assets(), tmp_path, 2, save=lambda p, rgb: None)
    layout = json.loads((tmp_path / "guides" / "screens" / "ress10.json").read_text())
    assert layout == be.screen_layout(10)
    assert records[0]["layout"] == "guides/screens/ress06.json"


def test_save_layout_is_atomic(tmp_path):
    path = tmp_path / "a" / "b.json"
    xb.save_layout(path, {"schema": 1})
    assert json.loads(path.read_text()) == {"schema": 1}
    assert sorted(p.name for p in path.parent.iterdir()) == ["b.json"]
