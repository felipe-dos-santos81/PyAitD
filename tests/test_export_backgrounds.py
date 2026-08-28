# SPDX-License-Identifier: GPL-2.0-only
import hashlib
import json
import pathlib

import numpy as np
import pytest

pytestmark = pytest.mark.render


def test_export_alt_backgrounds_writes_five_and_reuses_guides(tmp_path, data_dir):
    from tools.export_backgrounds import export_alt_backgrounds, load_floor
    from PyAitD.games import load_profile
    profile = load_profile("aitd1")
    alt = export_alt_backgrounds(data_dir, tmp_path, guide_scale=4)
    assert len(alt) == 5
    # files exist with shared guide path
    for rec in alt:
        assert (tmp_path / rec["source"]).is_file()
        assert rec["guide"] == "guides/floor{:02d}/camera{:03d}.png".format(rec["floor"], rec["camera"])
        assert rec["itd_entry"] in (15, 16, 17, 18, 19)
    # concrete check: floor07 cam000 is ITD_RESS:15, not CAMERA07:0
    from PyAitD.engine.floor import Floor
    from PyAitD.render.background_export import sha256_rgb
    # ensure alt SHA differs from base
    base_sha = sha256_rgb(Floor(data_dir, 7, profile).camera_image(0))
    alt_sha = [r["sha256"] for r in alt if r["floor"] == 7 and r["camera"] == 0][0]
    assert base_sha != alt_sha


def test_export_palette_writes_256x1(tmp_path, data_dir):
    from tools.export_backgrounds import export_palette
    export_palette(data_dir, tmp_path)
    from PyAitD.render.asset_resolver import load_png_rgb
    pix = load_png_rgb(tmp_path / "palette.png")
    assert pix.shape == (1, 256, 3)


def test_main_respects_floors_filter_and_force(tmp_path, data_dir):
    from tools.export_backgrounds import main
    # export only floor 06 with force, then check manifest alt_cameras subset
    out = tmp_path / "out"
    rc = main([str(data_dir), "--out", str(out), "--floors", "06", "--force"])
    assert rc == 0
    m = json.loads((out / "manifest.json").read_text())
    assert len(m["alt_cameras"]) == 3  # 06/0,06/5,06/8
    assert all(r["floor"] == 6 for r in m["alt_cameras"])
