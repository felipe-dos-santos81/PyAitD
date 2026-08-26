# SPDX-License-Identifier: GPL-2.0-only
import json
import os
from types import SimpleNamespace
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np

from PyAitD.render import background_export as be
from tools import export_backgrounds as xb


def _assets():
    plates = {e: np.full((200, 320, 3), e, np.uint8) for e in be.SCREEN_ENTRIES}
    return SimpleNamespace(resource_screen=lambda e: plates[e])


def test_export_screens_writes_plate_guide_and_records(tmp_path):
    saved = {}
    records = xb.export_screens(_assets(), tmp_path, 2, save=lambda p, rgb: saved.__setitem__(p, rgb.shape))
    assert [r["entry"] for r in records] == list(be.SCREEN_ENTRIES)
    assert saved[tmp_path / "screens" / "ress10.png"] == (200, 320, 3)
    assert saved[tmp_path / "guides" / "screens" / "ress10.png"] == (400 + be.GUIDE_FOOTER, 640, 3)


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


def test_main_exports_screens_and_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(xb, "load_floor", lambda data, n: (_ for _ in ()).throw(FileNotFoundError("no floor")))
    monkeypatch.setattr(xb, "load_assets", lambda data: _assets())
    monkeypatch.setattr(xb, "save_png", lambda p, rgb: (p.parent.mkdir(parents=True, exist_ok=True), p.write_bytes(b"png")))
    out = tmp_path / "out"
    assert xb.main([str(tmp_path), "--out", str(out), "--floors", "0"]) == 0
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["schema"] == 2 and manifest["cameras"] == []
    assert [s["entry"] for s in manifest["screens"]] == list(be.SCREEN_ENTRIES)
    assert (out / "screens" / "ress13.png").is_file()
