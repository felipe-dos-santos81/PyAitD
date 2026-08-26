# SPDX-License-Identifier: GPL-2.0-only
import hashlib
import io
import json
import os
import pathlib
import re
import subprocess
import types as _t
import zlib
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pytest

from PyAitD.render.asset_resolver import load_png_rgb
from PyAitD.render.background_export import export_manifest
from PyAitD.render import override_check as oc
from tests.stub_floor import checker_pixels, StubFloor
from tools import export_backgrounds as xb
from tools import regenerate_backgrounds as rb


def make_in_dir(root):
    """floor00: camera000 (with guide), camera001 (no guide); floor01: camera000 (with guide)."""
    in_dir = root / "in"
    for key, guide in (("floor00/camera000", True), ("floor00/camera001", False), ("floor01/camera000", True)):
        xb.save_png(in_dir / "backgrounds" / f"{key}.png", checker_pixels(zlib.crc32(key.encode()) % 100))
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


def png_bytes(rgb):
    import pygame
    surf = pygame.surfarray.make_surface(np.ascontiguousarray(rgb.swapaxes(0, 1)))
    buf = io.BytesIO()
    pygame.image.save(surf, buf, "png")
    return buf.getvalue()


class FakeSubprocess:
    def __init__(self, image_png=None, fail_image_calls=(), no_image=False,
                 describe_text="  a dusty attic under sloped rafters  "):
        self.image_png = image_png
        self.fail = set(fail_image_calls)
        self.no_image = no_image
        self.describe_text = describe_text
        self.calls = []
        self.image_calls = 0

    def run(self, cmd, capture_output=True, text=True, check=True):
        self.calls.append(cmd)
        prompt = cmd[2]
        if "generate_image tool" in prompt:
            self.image_calls += 1
            if self.image_calls in self.fail:
                raise subprocess.CalledProcessError(1, cmd, output="quota")
            
            if not self.no_image and self.image_png:
                m = re.search(r"exactly this path: (.*?). Then output", prompt)
                if m:
                    path = m.group(1)
                    with open(path, "wb") as f:
                        f.write(self.image_png)
            
            return _t.SimpleNamespace(stdout="SUCCESS\n", returncode=0)
        else:
            if not self.describe_text:
                return _t.SimpleNamespace(stdout="", returncode=0)
            return _t.SimpleNamespace(stdout=self.describe_text, returncode=0)


def test_describe_sends_source_guide_and_prompt(tmp_path, monkeypatch):
    in_dir = make_in_dir(tmp_path)
    cam = rb.discover(in_dir, None)[0]
    fake = FakeSubprocess()
    monkeypatch.setattr(subprocess, "run", fake.run)
    
    assert rb.describe("gemini-3.1-pro", cam) == "a dusty attic under sloped rafters"
    cmd = fake.calls[0]
    assert cmd[0] == "agy"
    assert "--model" in cmd and "gemini-3.1-pro" in cmd
    prompt = cmd[2]
    assert str(cam.source.absolute()) in prompt
    assert str(cam.guide.absolute()) in prompt
    assert rb.describe_prompt(True) in prompt


def test_describe_without_guide_sends_no_guide_prompt(tmp_path, monkeypatch):
    cam = rb.discover(make_in_dir(tmp_path), None)[1]
    fake = FakeSubprocess()
    monkeypatch.setattr(subprocess, "run", fake.run)
    
    rb.describe("gemini-3.1-pro", cam)
    prompt = fake.calls[0][2]
    assert str(cam.source.absolute()) in prompt
    assert "guide image" not in prompt
    assert rb.describe_prompt(False) in prompt


@pytest.mark.parametrize("text", [None, "", "   "])
def test_describe_raises_on_empty_text(tmp_path, text, monkeypatch):
    cam = rb.discover(make_in_dir(tmp_path), None)[0]
    fake = FakeSubprocess(describe_text=text)
    monkeypatch.setattr(subprocess, "run", fake.run)
    
    with pytest.raises(RuntimeError, match="empty description from text model"):
        rb.describe("gemini-3.1-pro", cam)


def test_generate_requests_image_and_returns_bytes(tmp_path, monkeypatch):
    cam = rb.discover(make_in_dir(tmp_path), None)[0]
    png = png_bytes(np.zeros((1024, 1536, 3), np.uint8))
    fake = FakeSubprocess(png)
    monkeypatch.setattr(subprocess, "run", fake.run)
    
    assert rb.generate("gemini-3.1-pro", cam, "desc") == png
    cmd = fake.calls[0]
    assert "--model" in cmd and "gemini-3.1-pro" in cmd
    assert "desc" in cmd[2]


def test_generate_without_image_part_raises(tmp_path, monkeypatch):
    cam = rb.discover(make_in_dir(tmp_path), None)[0]
    fake = FakeSubprocess(no_image=True)
    monkeypatch.setattr(subprocess, "run", fake.run)
    
    with pytest.raises(RuntimeError, match="no image generated or copied by agent"):
        rb.generate("gemini-3.1-pro", cam, "desc")


def test_fit_to_target_crops_to_16_10_then_scales():
    assert rb.fit_to_target(png_bytes(np.zeros((1024, 1536, 3), np.uint8))).shape == (800, 1280, 3)
    assert rb.fit_to_target(png_bytes(np.zeros((1000, 1000, 3), np.uint8))).shape == (800, 1280, 3)
    rgb = np.zeros((400, 640, 3), np.uint8)
    rgb[:, :320] = (255, 0, 0)
    rgb[:, 320:] = (0, 0, 255)
    out = rb.fit_to_target(png_bytes(rgb))
    assert tuple(out[400, 10]) == (255, 0, 0) and tuple(out[400, 1270]) == (0, 0, 255)
    wide = np.zeros((100, 400, 3), np.uint8)
    wide[:, 120:280] = (255, 0, 0)
    out = rb.fit_to_target(png_bytes(wide))
    assert tuple(out[400, 640]) == (255, 0, 0) and tuple(out[400, 5]) == (255, 0, 0)


def _run(tmp_path, fake, **kw):
    cams = rb.discover(make_in_dir(tmp_path), None)
    opts = dict(text_model="gemini-3.1-pro", image_model="gemini-3.1-pro",
                style="s.", force=False, dry_run=False, log=lambda *_: None)
    opts.update(kw)
    return rb.regenerate(cams, tmp_path / "out", **opts)


def test_regenerate_writes_fitted_pngs_and_prompt_cache(tmp_path, monkeypatch):
    fake = FakeSubprocess(png_bytes(np.full((1024, 1536, 3), 7, np.uint8)))
    monkeypatch.setattr(subprocess, "run", fake.run)
    
    assert _run(tmp_path, fake) == (3, 0)
    out = tmp_path / "out"
    for key in ("floor00/camera000", "floor00/camera001", "floor01/camera000"):
        assert load_png_rgb(out / "backgrounds" / f"{key}.png").shape == (800, 1280, 3)
    prompts = rb.load_prompts(out / rb.PROMPTS_FILE)
    assert set(prompts) == {"floor00/camera000", "floor00/camera001", "floor01/camera000"}
    src = (tmp_path / "in/backgrounds/floor00/camera000.png").read_bytes()
    assert prompts["floor00/camera000"] == {
        "prompt": "a dusty attic under sloped rafters", "model": "gemini-3.1-pro",
        "sha256": hashlib.sha256(src).hexdigest()}
    assert len(fake.calls) == 6
    gen_prompt = fake.calls[1][2]
    assert rb.generation_prompt("a dusty attic under sloped rafters", "s.", True) in gen_prompt


def test_regenerate_resumes_and_force_redoes(tmp_path, monkeypatch):
    fake = FakeSubprocess(png_bytes(np.zeros((1024, 1536, 3), np.uint8)))
    monkeypatch.setattr(subprocess, "run", fake.run)
    
    _run(tmp_path, fake)
    fake.calls.clear()
    assert _run(tmp_path, fake) == (0, 0)
    assert fake.calls == []
    
    path = tmp_path / "out" / rb.PROMPTS_FILE
    prompts = rb.load_prompts(path)
    prompts["floor00/camera001"]["prompt"] = "EDITED"
    rb.save_prompts(path, prompts)
    (tmp_path / "out/backgrounds/floor00/camera001.png").unlink()
    
    assert _run(tmp_path, fake) == (1, 0)
    assert len(fake.calls) == 1 and "EDITED" in fake.calls[0][2]
    assert rb.load_prompts(path)["floor00/camera001"]["prompt"] == "EDITED"
    
    fake.calls.clear()
    assert _run(tmp_path, fake, force=True) == (3, 0)
    assert len(fake.calls) == 6
    assert rb.load_prompts(path)["floor00/camera001"]["prompt"] != "EDITED"


def test_regenerate_continues_after_a_failed_camera(tmp_path, monkeypatch):
    logs = []
    fake = FakeSubprocess(png_bytes(np.zeros((1024, 1536, 3), np.uint8)), fail_image_calls={2})
    monkeypatch.setattr(subprocess, "run", fake.run)
    
    assert _run(tmp_path, fake, log=logs.append) == (2, 1)
    assert not (tmp_path / "out/backgrounds/floor00/camera001.png").exists()
    assert any("floor00/camera001: failed:" in line for line in logs)


def test_regenerate_counts_empty_description_as_failed(tmp_path, monkeypatch):
    logs = []
    fake = FakeSubprocess(png_bytes(np.zeros((1024, 1536, 3), np.uint8)), describe_text=None)
    monkeypatch.setattr(subprocess, "run", fake.run)
    
    assert _run(tmp_path, fake, log=logs.append) == (0, 3)
    out = tmp_path / "out"
    for key in ("floor00/camera000", "floor00/camera001", "floor01/camera000"):
        assert not (out / "backgrounds" / f"{key}.png").exists()
    assert rb.load_prompts(out / rb.PROMPTS_FILE) == {}
    assert any("empty description from text model" in line for line in logs)


def test_regenerate_counts_non_png_image_as_failed(tmp_path, monkeypatch):
    logs = []
    fake = FakeSubprocess(b"not a png")
    monkeypatch.setattr(subprocess, "run", fake.run)
    
    assert _run(tmp_path, fake, log=logs.append) == (0, 3)
    out = tmp_path / "out"
    for key in ("floor00/camera000", "floor00/camera001", "floor01/camera000"):
        assert not (out / "backgrounds" / f"{key}.png").exists()
    assert any("floor00/camera000: failed:" in line for line in logs)
    assert [l.split(":")[0] for l in logs[:3]] == ["floor00/camera000", "floor00/camera001", "floor01/camera000"]


def test_regenerate_redescribes_when_source_hash_changes(tmp_path, monkeypatch):
    in_dir = make_in_dir(tmp_path)
    out_dir = tmp_path / "out"
    opts = dict(text_model="gemini-3.1-pro", image_model="gemini-3.1-pro",
                style="s.", force=False, dry_run=False, log=lambda *_: None)
    fake = FakeSubprocess(png_bytes(np.zeros((1024, 1536, 3), np.uint8)))
    monkeypatch.setattr(subprocess, "run", fake.run)
    
    rb.regenerate(rb.discover(in_dir, None), out_dir, **opts)
    fake.calls.clear()
    
    xb.save_png(in_dir / "backgrounds/floor00/camera001.png",
               checker_pixels(zlib.crc32(b"floor00/camera001-changed") % 100))
    (out_dir / "backgrounds/floor00/camera001.png").unlink()
    path = out_dir / rb.PROMPTS_FILE
    old_sha = rb.load_prompts(path)["floor00/camera001"]["sha256"]
    
    assert rb.regenerate(rb.discover(in_dir, None), out_dir, **opts) == (1, 0)
    assert len(fake.calls) == 2
    new_sha = rb.load_prompts(path)["floor00/camera001"]["sha256"]
    assert new_sha != old_sha
    new_source_sha = hashlib.sha256((in_dir / "backgrounds/floor00/camera001.png").read_bytes()).hexdigest()
    assert new_sha == new_source_sha


def test_regenerate_dry_run_makes_no_calls_and_no_files(tmp_path, monkeypatch):
    logs = []
    fake = FakeSubprocess()
    monkeypatch.setattr(subprocess, "run", fake.run)
    
    assert _run(tmp_path, fake, dry_run=True, log=logs.append) == (0, 0)
    assert fake.calls == [] and not (tmp_path / "out").exists()
    assert any("floor00/camera001" in line and "guide no" in line for line in logs)


def test_regenerate_round_trips_through_check_overrides(tmp_path, monkeypatch):
    in_dir = tmp_path / "in"
    floor = StubFloor(number=0)
    recs = xb.export_floor(floor, in_dir, 4)
    manifest = export_manifest(recs, "stub", 4)
    xb.save_manifest(in_dir, manifest)
    cams = rb.discover(in_dir, None)
    fake = FakeSubprocess(png_bytes(np.full((1024, 1536, 3), 9, np.uint8)))
    monkeypatch.setattr(subprocess, "run", fake.run)
    out = tmp_path / "out"
    
    assert rb.regenerate(cams, out, text_model="t", image_model="image", style="s",
                         force=False, dry_run=False, log=lambda *_: None) == (1, 0)
    assert json.loads((out / "manifest.json").read_text()) == manifest
    findings = oc.check_overrides(out, [floor], manifest)
    assert [f.kind for f in findings] == []
    assert oc.coverage(out, [floor], manifest)[0]["regenerated"] == 1


def test_copy_manifest_never_overwrites_existing_out_manifest(tmp_path, monkeypatch):
    in_dir = tmp_path / "in"
    floor = StubFloor(number=0)
    recs = xb.export_floor(floor, in_dir, 4)
    manifest = export_manifest(recs, "stub", 4)
    xb.save_manifest(in_dir, manifest)
    out = tmp_path / "out"
    out.mkdir(parents=True)
    sentinel = json.dumps({"hand": "edited"})
    (out / "manifest.json").write_text(sentinel)
    cams = rb.discover(in_dir, None)
    fake = FakeSubprocess(png_bytes(np.full((1024, 1536, 3), 9, np.uint8)))
    monkeypatch.setattr(subprocess, "run", fake.run)
    
    assert rb.regenerate(cams, out, text_model="t", image_model="image", style="s",
                         force=False, dry_run=False, log=lambda *_: None) == (1, 0)
    assert (out / "manifest.json").read_text() == sentinel
    assert not (out / "manifest.json.tmp").exists()


def test_main_dry_run_needs_no_api_calls(tmp_path, capsys):
    in_dir = make_in_dir(tmp_path)
    assert rb.main([str(in_dir), "--out", str(tmp_path / "out"), "--dry-run"]) == 0
    assert "floor00/camera000" in capsys.readouterr().out
    assert not (tmp_path / "out").exists()


def test_main_exit_codes(tmp_path, capsys):
    in_dir = make_in_dir(tmp_path)
    assert rb.main([str(tmp_path / "empty"), "--out", str(tmp_path / "out")]) == 2
    assert "no cameras" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_main_runs_with_injected_subprocess_and_reports_failures(tmp_path, monkeypatch, capsys):
    in_dir = make_in_dir(tmp_path)
    fake = FakeSubprocess(png_bytes(np.zeros((1024, 1536, 3), np.uint8)), fail_image_calls={3})
    monkeypatch.setattr(subprocess, "run", fake.run)
    
    assert rb.main([str(in_dir), "--out", str(tmp_path / "out"), "--floors", "0-7",
                    "--style", "noir.", "--text-model", "t-model", "--image-model", "image-x"]) == 1
    out = capsys.readouterr().out
    assert "floor01/camera000: failed:" in out and "done 2, failed 1" in out
    
    assert "--model" in fake.calls[0] and "t-model" in fake.calls[0]
    assert "--model" in fake.calls[1] and "t-model" in fake.calls[1]
    assert "noir." in fake.calls[1][2]
    
    fake.fail.clear()
    assert rb.main([str(in_dir), "--out", str(tmp_path / "out")]) == 0


def test_regenerate_aborts_after_consecutive_failures(tmp_path, monkeypatch):
    logs = []
    fake = FakeSubprocess(png_bytes(np.zeros((1024, 1536, 3), np.uint8)), fail_image_calls={1, 2, 3, 4})
    monkeypatch.setattr(subprocess, "run", fake.run)

    assert _run(tmp_path, fake, log=logs.append) == (0, 3)
    assert fake.image_calls == 3
    assert logs[-1] == "aborting after 3 consecutive failures"


def test_discover_includes_screens_after_cameras(tmp_path):
    in_dir = make_in_dir(tmp_path)
    xb.save_png(in_dir / "screens" / "ress10.png", checker_pixels(1))
    xb.save_png(in_dir / "guides" / "screens" / "ress10.png", np.zeros((412, 640, 3), np.uint8))
    xb.save_png(in_dir / "screens" / "ress13.png", checker_pixels(2))
    items = rb.discover(in_dir, None)
    assert [c.key for c in items][-2:] == ["screens/ress10", "screens/ress13"]
    assert items[-2].floor == -1 and items[-2].camera == 10
    assert items[-2].guide == in_dir / "guides" / "screens" / "ress10.png" and items[-1].guide is None
    assert all(c.floor >= 0 for c in rb.discover(in_dir, None, screens=False))


def test_screen_prompts_ask_for_plain_blit_regions():
    cam = rb.Camera(-1, 10, pathlib.Path("s.png"), pathlib.Path("g.png"), "screens/ress10")
    text = rb.generation_prompt("a hall", "", True, screen=True)
    assert "blue" in text and "drawn there by the game" in text
    assert "walkable" not in text

