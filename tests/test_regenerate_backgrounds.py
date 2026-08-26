# SPDX-License-Identifier: GPL-2.0-only
import hashlib
import io
import json
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pytest

from PyAitD.asset_resolver import load_png_rgb
from PyAitD.background_export import export_manifest, sha256_rgb
from PyAitD import override_check as oc
from tests.stub_floor import checker_pixels, StubFloor
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


def test_fit_to_target_crops_to_16_10_then_scales():
    assert rb.fit_to_target(png_bytes(np.zeros((1024, 1536, 3), np.uint8))).shape == (800, 1280, 3)
    assert rb.fit_to_target(png_bytes(np.zeros((1000, 1000, 3), np.uint8))).shape == (800, 1280, 3)
    # A 16:10 two-colour image is scaled, not cropped: left stays red, right stays blue.
    rgb = np.zeros((400, 640, 3), np.uint8)
    rgb[:, :320] = (255, 0, 0)
    rgb[:, 320:] = (0, 0, 255)
    out = rb.fit_to_target(png_bytes(rgb))
    assert tuple(out[400, 10]) == (255, 0, 0) and tuple(out[400, 1270]) == (0, 0, 255)
    # A wide image is centre-cropped: red centre column survives, black edges are cut.
    wide = np.zeros((100, 400, 3), np.uint8)
    wide[:, 120:280] = (255, 0, 0)
    out = rb.fit_to_target(png_bytes(wide))
    assert tuple(out[400, 640]) == (255, 0, 0) and tuple(out[400, 5]) == (255, 0, 0)


def _run(tmp_path, client, **kw):
    cams = rb.discover(make_in_dir(tmp_path), None)
    opts = dict(client=client, text_model="gemini-2.5-flash", image_model="gemini-2.5-flash-image",
                style="s.", force=False, dry_run=False, log=lambda *_: None)
    opts.update(kw)
    return rb.regenerate(cams, tmp_path / "out", **opts)


def test_regenerate_writes_fitted_pngs_and_prompt_cache(tmp_path):
    client = FakeClient(png_bytes(np.full((1024, 1536, 3), 7, np.uint8)))
    assert _run(tmp_path, client) == (3, 0)
    out = tmp_path / "out"
    for key in ("floor00/camera000", "floor00/camera001", "floor01/camera000"):
        assert load_png_rgb(out / "backgrounds" / f"{key}.png").shape == (800, 1280, 3)
    prompts = rb.load_prompts(out / rb.PROMPTS_FILE)
    assert set(prompts) == {"floor00/camera000", "floor00/camera001", "floor01/camera000"}
    src = (tmp_path / "in/backgrounds/floor00/camera000.png").read_bytes()
    assert prompts["floor00/camera000"] == {
        "prompt": "a dusty attic under sloped rafters", "model": "gemini-2.5-flash",
        "sha256": hashlib.sha256(src).hexdigest()}
    assert len(client.calls) == 6
    # The generation call carries the cached description and the style.
    gen_prompt = client.calls[1][1][-1]
    assert gen_prompt == rb.generation_prompt("a dusty attic under sloped rafters", "s.", True)


def test_regenerate_resumes_and_force_redoes(tmp_path):
    client = FakeClient(png_bytes(np.zeros((1024, 1536, 3), np.uint8)))
    _run(tmp_path, client)
    client.calls.clear()
    assert _run(tmp_path, client) == (0, 0)
    assert client.calls == []
    # Hand-edited prompt survives a run without --force and is used by it after deleting the png.
    path = tmp_path / "out" / rb.PROMPTS_FILE
    prompts = rb.load_prompts(path)
    prompts["floor00/camera001"]["prompt"] = "EDITED"
    rb.save_prompts(path, prompts)
    (tmp_path / "out/backgrounds/floor00/camera001.png").unlink()
    assert _run(tmp_path, client) == (1, 0)
    assert len(client.calls) == 1 and "EDITED" in client.calls[0][1][-1]
    assert rb.load_prompts(path)["floor00/camera001"]["prompt"] == "EDITED"
    client.calls.clear()
    assert _run(tmp_path, client, force=True) == (3, 0)
    assert len(client.calls) == 6
    assert rb.load_prompts(path)["floor00/camera001"]["prompt"] != "EDITED"


def test_regenerate_continues_after_a_failed_camera(tmp_path):
    logs = []
    client = FakeClient(png_bytes(np.zeros((1024, 1536, 3), np.uint8)), fail_image_calls={2})
    assert _run(tmp_path, client, log=logs.append) == (2, 1)
    assert not (tmp_path / "out/backgrounds/floor00/camera001.png").exists()
    assert any("floor00/camera001: failed: quota" in line for line in logs)


def test_regenerate_dry_run_makes_no_calls_and_no_files(tmp_path):
    logs = []
    client = FakeClient()
    assert _run(tmp_path, client, dry_run=True, log=logs.append) == (0, 0)
    assert client.calls == [] and not (tmp_path / "out").exists()
    assert any("floor00/camera001" in line and "guide no" in line for line in logs)


def test_regenerate_round_trips_through_check_overrides(tmp_path):
    in_dir = tmp_path / "in"
    floor = StubFloor(number=0)
    recs = xb.export_floor(floor, in_dir, 4)
    manifest = export_manifest(recs, "stub", 4)
    xb.save_manifest(in_dir, manifest)
    cams = rb.discover(in_dir, None)
    client = FakeClient(png_bytes(np.full((1024, 1536, 3), 9, np.uint8)))
    out = tmp_path / "out"
    assert rb.regenerate(cams, out, client=client, text_model="t", image_model="image", style="s",
                         force=False, dry_run=False, log=lambda *_: None) == (1, 0)
    assert json.loads((out / "manifest.json").read_text()) == manifest
    findings = oc.check_overrides(out, [floor], manifest)
    assert [f.kind for f in findings] == []
    assert oc.coverage(out, [floor], manifest)[0]["regenerated"] == 1


def test_main_dry_run_needs_no_key_or_sdk(tmp_path, monkeypatch, capsys):
    in_dir = make_in_dir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(rb, "make_client", lambda: pytest.fail("client created in dry run"))
    assert rb.main([str(in_dir), "--out", str(tmp_path / "out"), "--dry-run"]) == 0
    assert "floor00/camera000" in capsys.readouterr().out
    assert not (tmp_path / "out").exists()


def test_main_exit_codes(tmp_path, monkeypatch, capsys):
    in_dir = make_in_dir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert rb.main([str(tmp_path / "empty"), "--out", str(tmp_path / "out")]) == 2
    assert "no cameras" in capsys.readouterr().err
    assert rb.main([str(in_dir), "--out", str(tmp_path / "out")]) == 2
    assert "GEMINI_API_KEY is not set" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_main_runs_with_injected_client_and_reports_failures(tmp_path, monkeypatch, capsys):
    in_dir = make_in_dir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    client = FakeClient(png_bytes(np.zeros((1024, 1536, 3), np.uint8)), fail_image_calls={3})
    monkeypatch.setattr(rb, "make_client", lambda: client)
    assert rb.main([str(in_dir), "--out", str(tmp_path / "out"), "--floors", "0-7",
                    "--style", "noir.", "--text-model", "t-model", "--image-model", "image-x"]) == 1
    out = capsys.readouterr().out
    assert "floor01/camera000: failed: quota" in out and "done 2, failed 1" in out
    assert client.calls[0][0] == "t-model" and client.calls[1][0] == "image-x"
    assert client.calls[1][1][-1].endswith("noir.")
    client.fail.clear()
    assert rb.main([str(in_dir), "--out", str(tmp_path / "out")]) == 0


def test_make_client_reports_missing_sdk(monkeypatch, capsys):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name.startswith("google"):
            raise ImportError(name)
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(SystemExit) as e:
        rb.make_client()
    assert e.value.code == 2
    assert 'google-genai is not installed: run .venv/bin/pip install -e ".[dev,ai]"' in capsys.readouterr().err


@pytest.mark.skipif(not (os.environ.get("GEMINI_API_KEY") and os.environ.get("PYAITD_LIVE_AI") == "1"),
                    reason="set GEMINI_API_KEY and PYAITD_LIVE_AI=1 to call Gemini")
def test_live_gemini_round_trip(tmp_path):
    in_dir = tmp_path / "in"
    xb.save_png(in_dir / "backgrounds/floor00/camera000.png", checker_pixels(1))
    cams = rb.discover(in_dir, None)
    done, failed = rb.regenerate(cams, tmp_path / "out", client=rb.make_client(),
                                 text_model=rb.DEFAULT_TEXT_MODEL, image_model=rb.DEFAULT_IMAGE_MODEL,
                                 style=rb.DEFAULT_STYLE, force=False, dry_run=False)
    assert (done, failed) == (1, 0)
    assert load_png_rgb(tmp_path / "out/backgrounds/floor00/camera000.png").shape == (800, 1280, 3)
