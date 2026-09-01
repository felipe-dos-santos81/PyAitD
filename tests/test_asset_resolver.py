# SPDX-License-Identifier: GPL-2.0-only
import logging
from types import SimpleNamespace

import numpy as np
import pytest

from PyAitD.render.asset_resolver import (
    AssetResolver, ImageAsset, load_png_rgb, texture_background_path, texture_palette_path,
)

pytestmark = pytest.mark.render


def _floor(number=3):
    original = np.full((200, 320, 3), 7, dtype=np.uint8)
    return SimpleNamespace(number=number, palette=np.zeros((256, 3), dtype=np.uint8),
                           camera_image=lambda idx: original)


def test_paths_follow_the_convention(tmp_path):
    assert texture_background_path(tmp_path, 3, 12) == tmp_path / "backgrounds" / "floor03" / "camera012.png"
    assert texture_palette_path(tmp_path) == tmp_path / "palette.png"


def test_texture_alt_background_path(tmp_path):
    from PyAitD.render.asset_resolver import texture_alt_background_path
    from PyAitD.render.texture_export import alt_background_rel_path
    assert tmp_path / alt_background_rel_path(7, 0) == texture_alt_background_path(tmp_path, 7, 0)


def test_background_prefers_alt_when_killed(tmp_path, monkeypatch):
    from pathlib import Path
    import numpy as np
    from PyAitD.render.asset_resolver import AssetResolver
    from tests.stub_floor import StubFloor
    base = np.zeros((200, 320, 3), np.uint8); base[0, 0] = 1
    alt = np.zeros((200, 320, 3), np.uint8); alt[0, 0] = 2
    # stub Floor with one camera, viewed_rooms etc from StubFloor
    floor = StubFloor(number=7)  # cam 0 exists, viewed_rooms=[0]
    # monkeypatch save path to provide files via resolver's load_png override
    def fake_load(path):
        p = str(path)
        if "alt_backgrounds" in p: return alt
        if "backgrounds" in p: return base
        raise FileNotFoundError
    r = AssetResolver(None, tmp_path, load_png=fake_load)
    # manually make both files appear to exist
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    # without killed flag, base wins
    assert r.background(floor, 0, killed_sorcerer=False).pixels[0, 0, 0] == 1
    # with killed flag, alt wins
    assert r.background(floor, 0, killed_sorcerer=True).pixels[0, 0, 0] == 2
    # corrupt alt falls back to base
    def bad_alt(path):
        if "alt_backgrounds" in str(path): raise ValueError("bad")
        if "backgrounds" in str(path): return base
        raise FileNotFoundError
    r2 = AssetResolver(None, tmp_path, load_png=bad_alt)
    assert r2.background(floor, 0, killed_sorcerer=True).pixels[0, 0, 0] == 1
    assert tmp_path / "alt_backgrounds/floor07/camera000.png" in r2.failures


def test_no_texture_dir_returns_original():
    resolver = AssetResolver(SimpleNamespace(body=lambda n: n), None)
    asset = resolver.background(_floor(), 0)
    assert isinstance(asset, ImageAsset) and not asset.is_override and asset.pixels.shape == (200, 320, 3)
    assert resolver.body(5) == 5


def test_texture_dir_set_but_file_absent_falls_back_silently(tmp_path, caplog):
    def fail_if_called(p):
        raise AssertionError("load_png must not be called when the override file is absent")
    resolver = AssetResolver(None, tmp_path, load_png=fail_if_called)
    with caplog.at_level(logging.WARNING, logger="PyAitD.engine.data.assets"):
        asset = resolver.background(_floor(), 0)
    assert not asset.is_override and asset.pixels.shape == (200, 320, 3)
    assert not resolver.failures
    assert not caplog.records


def test_override_png_is_used_at_any_size(tmp_path):
    path = texture_background_path(tmp_path, 3, 0)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"png")
    big = np.zeros((800, 1280, 3), dtype=np.uint8)
    resolver = AssetResolver(None, tmp_path, load_png=lambda p: big)
    asset = resolver.background(_floor(), 0)
    assert asset.is_override and asset.pixels is big


def test_unreadable_override_logs_once_and_falls_back(tmp_path, caplog):
    path = texture_background_path(tmp_path, 3, 0)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"bad")
    def boom(p):
        raise ValueError("corrupt")
    resolver = AssetResolver(None, tmp_path, load_png=boom)
    with caplog.at_level(logging.WARNING, logger="PyAitD.engine.data.assets"):
        first = resolver.background(_floor(), 0)
        second = resolver.background(_floor(), 0)
    assert not first.is_override and not second.is_override
    assert sum("corrupt" in r.message for r in caplog.records) == 1
    assert path in resolver.failures


def test_palette_override_must_be_256_wide(tmp_path):
    texture_palette_path(tmp_path).write_bytes(b"png")
    resolver = AssetResolver(None, tmp_path, load_png=lambda p: np.ones((1, 256, 3), dtype=np.uint8))
    assert resolver.palette(_floor()).shape == (256, 3) and resolver.palette(_floor())[0].tolist() == [1, 1, 1]
    resolver = AssetResolver(None, tmp_path, load_png=lambda p: np.ones((1, 16, 3), dtype=np.uint8))
    assert resolver.palette(_floor()).tolist() == np.zeros((256, 3), dtype=np.uint8).tolist()


def test_greyscale_override_is_rejected_logged_and_falls_back(tmp_path, caplog):
    path = texture_background_path(tmp_path, 3, 0)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"grey")
    greyscale = np.zeros((200, 320), dtype=np.uint8)  # ndim == 2, no channel axis
    resolver = AssetResolver(None, tmp_path, load_png=lambda p: greyscale)
    with caplog.at_level(logging.WARNING, logger="PyAitD.engine.data.assets"):
        asset = resolver.background(_floor(), 0)
    assert not asset.is_override and asset.pixels.shape == (200, 320, 3)
    assert path in resolver.failures
    assert sum(r.levelno == logging.WARNING for r in caplog.records) == 1


def test_rgba_override_is_rejected_logged_and_falls_back(tmp_path, caplog):
    path = texture_background_path(tmp_path, 3, 0)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"rgba")
    rgba = np.zeros((200, 320, 4), dtype=np.uint8)  # 4 channels, not the required 3
    resolver = AssetResolver(None, tmp_path, load_png=lambda p: rgba)
    with caplog.at_level(logging.WARNING, logger="PyAitD.engine.data.assets"):
        asset = resolver.background(_floor(), 0)
    assert not asset.is_override and asset.pixels.shape == (200, 320, 3)
    assert path in resolver.failures
    assert sum(r.levelno == logging.WARNING for r in caplog.records) == 1


def test_enormous_override_is_rejected_logged_and_falls_back(tmp_path, caplog):
    # Finding 3: an override PNG this large would reach ctx.texture() in
    # render_gl.py and could raise on a driver enforcing a smaller
    # GL_MAX_TEXTURE_SIZE than this host's -- a crash the moment the player
    # enters that camera. _require_rgb rejects it here instead, with a clear
    # message, well before it ever reaches GL.
    path = texture_background_path(tmp_path, 3, 0)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"huge")
    enormous = np.zeros((9000, 320, 3), dtype=np.uint8)
    resolver = AssetResolver(None, tmp_path, load_png=lambda p: enormous)
    with caplog.at_level(logging.WARNING, logger="PyAitD.engine.data.assets"):
        asset = resolver.background(_floor(), 0)
    assert not asset.is_override and asset.pixels.shape == (200, 320, 3)
    assert path in resolver.failures
    assert sum(r.levelno == logging.WARNING for r in caplog.records) == 1
    assert "8192" in resolver.failures[path]


def test_load_png_rgb_axis_order_and_dtype(tmp_path):
    import pygame
    width, height = 5, 3  # deliberately W != H so a transpose bug is detectable
    surface = pygame.Surface((width, height))
    surface.fill((10, 20, 30))
    surface.set_at((width - 1, 0), (200, 150, 50))  # rightmost column, top row
    surface.set_at((0, height - 1), (5, 250, 100))  # leftmost column, bottom row
    path = tmp_path / "axis_check.png"
    pygame.image.save(surface, str(path))

    arr = load_png_rgb(path)

    assert arr.shape == (height, width, 3)
    assert arr.dtype == np.uint8
    assert arr[0, 0].tolist() == [10, 20, 30]
    assert arr[0, width - 1].tolist() == [200, 150, 50]
    assert arr[height - 1, 0].tolist() == [5, 250, 100]


from PyAitD.render.asset_resolver import texture_screen_path


def _assets():
    original = np.full((200, 320, 3), 9, dtype=np.uint8)
    return SimpleNamespace(body=lambda n: n, resource_screen=lambda entry: original)


def test_screen_path_follows_the_convention(tmp_path):
    assert texture_screen_path(tmp_path, 10) == tmp_path / "screens" / "ress10.png"
    assert texture_screen_path(tmp_path, 6) == tmp_path / "screens" / "ress06.png"


def test_resource_screen_without_texture_dir_returns_original():
    asset = AssetResolver(_assets(), None).resource_screen(10)
    assert isinstance(asset, ImageAsset) and not asset.is_override
    assert asset.pixels.shape == (200, 320, 3) and asset.pixels[0, 0, 0] == 9


def test_resource_screen_absent_override_falls_back_silently(tmp_path, caplog):
    def fail_if_called(p):
        raise AssertionError("load_png must not be called when the override file is absent")
    resolver = AssetResolver(_assets(), tmp_path, load_png=fail_if_called)
    with caplog.at_level(logging.WARNING, logger="PyAitD.engine.data.assets"):
        asset = resolver.resource_screen(10)
    assert not asset.is_override and not resolver.failures and not caplog.records


def test_resource_screen_override_is_used_at_any_size_and_cached(tmp_path):
    path = texture_screen_path(tmp_path, 14)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"png")
    big = np.zeros((400, 640, 3), dtype=np.uint8)
    calls = []
    resolver = AssetResolver(_assets(), tmp_path, load_png=lambda p: calls.append(p) or big)
    first = resolver.resource_screen(14)
    second = resolver.resource_screen(14)
    assert first.is_override and first.pixels is big and second.pixels is big
    assert len(calls) == 1


def test_resource_screen_invalid_override_warns_once_and_falls_back(tmp_path, caplog):
    path = texture_screen_path(tmp_path, 13)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"png")
    resolver = AssetResolver(_assets(), tmp_path, load_png=lambda p: np.zeros((10, 10), dtype=np.uint8))
    with caplog.at_level(logging.WARNING, logger="PyAitD.engine.data.assets"):
        asset = resolver.resource_screen(13)
        resolver.resource_screen(13)
    assert not asset.is_override
    assert path in resolver.failures
    assert len(caplog.records) == 1


def test_light_is_estimated_once_per_camera():
    calls = []

    class CountingFloor:
        number = 3
        palette = np.zeros((256, 3), dtype=np.uint8)

        def camera_image(self, idx):
            calls.append(idx)
            plate = np.zeros((200, 320, 3), np.uint8)
            plate[:40] = 255
            return plate

    floor = CountingFloor()
    resolver = AssetResolver(SimpleNamespace(body=lambda n: n), None)
    first = resolver.light(floor, 0)
    second = resolver.light(floor, 0)
    assert first is second
    assert calls == [0]                     # one decode, one estimate
    assert first.direction[1] < 0           # a bright ceiling band lights from above


def test_light_follows_an_override_background(tmp_path):
    from PyAitD.render.asset_resolver import texture_background_path
    path = texture_background_path(tmp_path, 3, 0)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"")                   # content comes from the stub loader below
    bright_left = np.zeros((200, 320, 3), np.uint8)
    bright_left[:, :40] = 255
    resolver = AssetResolver(None, tmp_path, load_png=lambda p: bright_left)
    light = resolver.light(_floor(), 0)
    assert light.direction[0] < 0           # estimated from the override, not the flat original


def test_plate_is_estimated_once_per_camera():
    calls = []

    class CountingFloor:
        number = 3
        palette = np.zeros((256, 3), dtype=np.uint8)

        def camera_image(self, idx):
            calls.append(idx)
            plate = np.zeros((200, 320, 3), np.uint8)
            plate[:40] = 255
            return plate

    floor = CountingFloor()
    resolver = AssetResolver(SimpleNamespace(body=lambda n: n), None)
    first = resolver.plate(floor, 0)
    second = resolver.plate(floor, 0)
    assert first is second
    assert calls == [0]                     # one decode, one estimate
    assert first.white[0] > first.black[0]  # estimated, not the neutral default


def test_plate_follows_an_override_background(tmp_path):
    from PyAitD.render.asset_resolver import texture_background_path
    path = texture_background_path(tmp_path, 3, 0)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"")                   # content comes from the stub loader below
    bright = np.full((200, 320, 3), 200, np.uint8)
    resolver = AssetResolver(None, tmp_path, load_png=lambda p: bright)
    # _floor()'s own plate is flat black; the override's is flat 200.
    assert resolver.plate(_floor(), 0).white[0] == pytest.approx(200 / 255)


def test_material_table_is_the_default_and_memoised():
    from PyAitD.render.materials import default_table
    resolver = AssetResolver(SimpleNamespace(body=lambda n: n), None)
    assert resolver.material_table(3) is default_table()
    assert resolver.material_table(3) is resolver.material_table(3)


def test_geometry_ao_bakes_once_per_body():
    from PyAitD.engine.data.formats import Body, Primitive
    calls = []
    body = Body(0, (0,) * 6, (), [(0, 0, 0), (100, 0, 0), (0, 100, 0)], [], [], [Primitive(1, 0, 1, [0, 1, 2])])

    def counting_body(num):
        calls.append(num)
        return body

    resolver = AssetResolver(SimpleNamespace(body=counting_body), None)
    first = resolver.geometry_ao(7)
    second = resolver.geometry_ao(7)
    assert first is second and calls == [7]
    assert np.array_equal(first, np.ones(3, np.float32))


def test_body_material_path_follows_the_convention(tmp_path):
    from PyAitD.render.asset_resolver import texture_body_material_path
    assert texture_body_material_path(tmp_path, 7) == tmp_path / "bodies" / "body007.json"


def test_material_table_follows_a_per_body_override(tmp_path):
    from PyAitD.render.asset_resolver import texture_body_material_path
    from PyAitD.render.materials import default_table
    path = texture_body_material_path(tmp_path, 7)
    path.parent.mkdir(parents=True)
    path.write_text('{"indices": {"5": "metal"}, "ramps": [{"lo": 40, "hi": 41, "class": "glass"}]}')
    resolver = AssetResolver(SimpleNamespace(body=lambda n: n), tmp_path)
    table = resolver.material_table(7)
    assert table.classes[5] == "metal" and table.classes[40] == "glass"
    assert table.classes[6] == default_table().classes[6]      # everything else untouched
    assert resolver.material_table(7) is table                 # memoised
    assert resolver.material_table(8) is default_table()       # no file, no change


def test_missing_body_override_is_silent(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        AssetResolver(SimpleNamespace(body=lambda n: n), tmp_path).material_table(3)
    assert caplog.records == []


def test_invalid_body_override_logs_once_and_falls_back(tmp_path, caplog):
    from PyAitD.render.asset_resolver import texture_body_material_path
    from PyAitD.render.materials import default_table
    path = texture_body_material_path(tmp_path, 2)
    path.parent.mkdir(parents=True)
    path.write_text('{"indices": {"5": "velvet"}}')
    resolver = AssetResolver(SimpleNamespace(body=lambda n: n), tmp_path)
    with caplog.at_level(logging.WARNING):
        assert resolver.material_table(2) is default_table()
        assert resolver.material_table(2) is default_table()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "velvet" in warnings[0].getMessage()
    assert path in resolver.failures


def _triangle_body():
    from PyAitD.engine.data.formats import Body, Primitive
    return Body(0, (0,) * 6, (), [(0, 0, 0), (100, 0, 0), (0, 100, 0)], [], [], [Primitive(1, 0, 1, [0, 1, 2])])


def test_refinement_plans_once_per_body():
    from PyAitD.render.refine import CREASE_DEG, Refinement
    calls = []
    body = _triangle_body()

    def counting_body(num):
        calls.append(num)
        return body

    resolver = AssetResolver(SimpleNamespace(body=counting_body), None)
    first = resolver.refinement(7)
    second = resolver.refinement(7)
    assert isinstance(first, Refinement) and first is second and calls == [7]
    assert first.crease_deg == CREASE_DEG and first.straight.tolist() == [[0.0, 0.0, 0.0]]


def test_refinement_follows_a_per_body_crease_override(tmp_path):
    from PyAitD.render.asset_resolver import texture_body_material_path
    path = texture_body_material_path(tmp_path, 7)
    path.parent.mkdir(parents=True)
    path.write_text('{"crease": 45, "indices": {"5": "metal"}}')
    resolver = AssetResolver(SimpleNamespace(body=lambda n: _triangle_body()), tmp_path)
    assert resolver.refinement(7).crease_deg == 45.0
    assert resolver.material_table(7).classes[5] == "metal"    # the same file feeds both
    assert resolver.refinement(8).crease_deg == 80.0            # no file, the default


def test_an_invalid_crease_rejects_the_whole_body_file_once(tmp_path, caplog):
    from PyAitD.render.asset_resolver import texture_body_material_path
    from PyAitD.render.materials import default_table
    path = texture_body_material_path(tmp_path, 2)
    path.parent.mkdir(parents=True)
    path.write_text('{"crease": "soft", "indices": {"5": "metal"}}')
    resolver = AssetResolver(SimpleNamespace(body=lambda n: _triangle_body()), tmp_path)
    with caplog.at_level(logging.WARNING):
        assert resolver.refinement(2).crease_deg == 80.0
        assert resolver.material_table(2) is default_table()    # one file, one verdict
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "crease" in warnings[0].getMessage()
    assert path in resolver.failures


def test_body_texture_is_none_without_a_texture_dir_and_when_the_paint_is_missing(tmp_path):
    from PyAitD.render.asset_resolver import AssetResolver
    assert AssetResolver(None).body_texture(12) is None
    assert AssetResolver(None, tmp_path).body_texture(12) is None
    # a plain absence never lands in failures: missing is the steady state
    assert AssetResolver(None, tmp_path).failures == {}


def test_body_texture_returns_uvs_and_pixels_and_memoises(tmp_path):
    import json
    import numpy as np
    from PyAitD.render.asset_resolver import AssetResolver
    from PyAitD.render.texture_export import body_texture_rel_path, body_uv_rel_path
    from tools.export_textures import save_png
    (tmp_path / "bodies").mkdir(parents=True)
    uvs = np.full((2, 3, 2), 0.5, dtype=np.float32)
    (tmp_path / body_uv_rel_path(12)).write_text(json.dumps({
        "schema": 1, "size": [8, 8], "chart_count": 1,
        "tris_sha256": "0" * 64, "uvs": uvs.tolist(),
    }), encoding="utf-8")
    save_png(tmp_path / body_texture_rel_path(12), np.zeros((8, 8, 3), np.uint8))
    resolver = AssetResolver(None, tmp_path)
    first = resolver.body_texture(12)
    assert first is not None
    got_uvs, asset = first
    assert got_uvs.shape == (2, 3, 2) and got_uvs.dtype == np.float32
    assert asset.pixels.shape == (8, 8, 3)
    assert resolver.body_texture(12) is first      # memoised per body


def test_a_corrupt_body_texture_warns_once_and_falls_back(tmp_path, caplog):
    import json
    import numpy as np
    from PyAitD.render.asset_resolver import AssetResolver
    from PyAitD.render.texture_export import body_texture_rel_path, body_uv_rel_path
    (tmp_path / "bodies").mkdir(parents=True)
    (tmp_path / body_uv_rel_path(12)).write_text(json.dumps({
        "schema": 1, "size": [8, 8], "chart_count": 1,
        "tris_sha256": "0" * 64,
        "uvs": np.full((2, 3, 2), 0.5, dtype=np.float32).tolist(),
    }), encoding="utf-8")
    (tmp_path / body_texture_rel_path(12)).write_bytes(b"not a png")
    resolver = AssetResolver(None, tmp_path)
    assert resolver.body_texture(12) is None
    assert any(rec.levelname == "WARNING" for rec in caplog.records)
    assert resolver.failures                       # corrupt is recorded, missing is not
