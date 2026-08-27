# SPDX-License-Identifier: GPL-2.0-only
import hashlib
import io
import json
import os
import pathlib
import re
import subprocess
import tempfile
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

pytestmark = pytest.mark.tools


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


INVENTORY = {"prompt": "a dusty attic under sloped rafters", "camera": "eye level, wide, from the stairs",
             "objects": [{"name": "window", "kind": "small square window", "count": 1, "bbox": [45, 12, 52, 25]},
                         {"name": "barrels", "kind": "wooden barrels", "count": 3, "bbox": [55, 22, 66, 34]}]}


def envelope(obj):
    return json.dumps({"status": "SUCCESS", "structured_output": obj})


class FakeSubprocess:
    """Stands in for the agy CLI. `describe` is the structured output for
    describe calls (None -> an envelope without structured_output); `judge`
    is a list of verdicts handed out in order (Task 7); `image_png` is what
    a generate call copies to the requested path."""

    def __init__(self, image_png=None, fail_image_calls=(), no_image=False, describe=INVENTORY, judge=()):
        self.image_png = image_png
        self.fail = set(fail_image_calls)
        self.no_image = no_image
        self.describe = describe
        self.judge = list(judge)
        self.calls = []
        self.image_calls = 0

    def run(self, cmd, capture_output=True, text=True, check=True):
        self.calls.append(cmd)
        prompt = cmd[2]
        if "--json-schema" in cmd:
            if "For every inventory object" in prompt:
                verdict = self.judge.pop(0)
                return _t.SimpleNamespace(stdout=envelope(verdict), returncode=0)
            if self.describe is None:
                return _t.SimpleNamespace(stdout=json.dumps({"status": "SUCCESS"}), returncode=0)
            return _t.SimpleNamespace(stdout=envelope(self.describe), returncode=0)
        self.image_calls += 1
        if self.image_calls in self.fail:
            raise subprocess.CalledProcessError(1, cmd, output="quota")
        if not self.no_image and self.image_png:
            m = re.search(r"this path: (.*?)\. Output ONLY the word SUCCESS", prompt)
            if m:
                with open(m.group(1), "wb") as f:
                    f.write(self.image_png)
        return _t.SimpleNamespace(stdout="SUCCESS\n", returncode=0)


def test_discover_finds_layout_sidecars(tmp_path):
    in_dir = make_in_dir(tmp_path)
    (in_dir / "guides" / "floor00").mkdir(parents=True, exist_ok=True)
    (in_dir / "guides" / "floor00" / "camera000.json").write_text(json.dumps({"schema": 1}))
    cams = rb.discover(in_dir, None)
    assert cams[0].layout == in_dir / "guides" / "floor00" / "camera000.json"
    assert cams[1].layout is None


def test_describe_prompt_opens_with_game_context_and_asks_for_objects():
    text = rb.describe_prompt(True)
    assert text.startswith(rb.GAME_CONTEXT)
    assert "Alone in the Dark 1" in rb.GAME_CONTEXT and "Lovecraftian" in rb.GAME_CONTEXT
    assert "second image" in text and "bounding box" in text
    assert "the game" not in text.replace(rb.GAME_CONTEXT, "")
    assert "second image" not in rb.describe_prompt(False)


def test_describe_returns_the_inventory_and_sends_schema(tmp_path, monkeypatch):
    cam = rb.discover(make_in_dir(tmp_path), None)[0]
    fake = FakeSubprocess()
    monkeypatch.setattr(subprocess, "run", fake.run)
    assert rb.describe("gemini-3.1-pro", cam) == INVENTORY
    cmd = fake.calls[0]
    assert cmd[0] == "agy" and "gemini-3.1-pro" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == rb.INVENTORY_SCHEMA
    assert str(cam.source.absolute()) in cmd[2] and str(cam.guide.absolute()) in cmd[2]


def test_describe_without_guide_sends_no_guide_prompt(tmp_path, monkeypatch):
    cam = rb.discover(make_in_dir(tmp_path), None)[1]
    fake = FakeSubprocess()
    monkeypatch.setattr(subprocess, "run", fake.run)
    rb.describe("gemini-3.1-pro", cam)
    assert "guide image" not in fake.calls[0][2] and "second image" not in fake.calls[0][2]


@pytest.mark.parametrize("bad, message", [
    (None, "no structured output"),
    ({"prompt": "  ", "camera": "c", "objects": [{"name": "x", "kind": "x", "count": 1, "bbox": [0, 0, 1, 1]}]},
     "empty description from text model"),
    ({"prompt": "p", "camera": "c", "objects": []}, "empty inventory from text model"),
])
def test_describe_rejects_bad_inventories(tmp_path, bad, message, monkeypatch):
    cam = rb.discover(make_in_dir(tmp_path), None)[0]
    fake = FakeSubprocess(describe=bad)
    monkeypatch.setattr(subprocess, "run", fake.run)
    with pytest.raises(RuntimeError, match=message):
        rb.describe("gemini-3.1-pro", cam)


def test_generation_prompt_order_and_contents():
    from tools.plate_check import Region
    regions = [Region("mask", ((0, 0),), (10, 20, 30, 40)), Region("collision", ((0, 0),), (50, 60, 70, 80)),
               Region("walkable", ((0, 0),), (0, 75, 100, 100))]
    text = rb.generation_prompt(INVENTORY, "film grain.", regions, ["window drawn at x 60–68"],
                                rejected_attempt=1, guide_attached=True)
    assert text.startswith(rb.GAME_CONTEXT)
    i = {s: text.index(s) for s in (
        "Re-render the first image as a photorealistic photograph",
        "second image marks the layout",
        "Layout (percent of frame, x left→right, y top→bottom): 1 small square window x 45–52 y 12–25; 3 wooden barrels x 55–66 y 22–34.",
        "Foreground occluders at x 10–30 y 20–40; solid walls and furniture at x 50–70 y 60–80; walkable floor at x 0–100 y 75–100.",
        "Attempt 1 was rejected: window drawn at x 60–68.",
        "eye level, wide, from the stairs", "a dusty attic under sloped rafters")}
    order = sorted(i, key=i.get)
    assert order == list(i)
    assert text.endswith(" film grain.")
    plain = rb.generation_prompt(INVENTORY, "s.", guide_attached=False)
    assert "second image" not in plain and "Attempt" not in plain and "occluders" not in plain


def test_screen_generation_prompt_uses_illustration_wording():
    from tools.plate_check import Region
    text = rb.generation_prompt(INVENTORY, "", [Region("blit", ((0, 0),), (3, 5, 47, 95))],
                                guide_attached=True, screen=True)
    assert "painted illustration of exactly this composition" in text
    assert "Regions that must stay plain: x 3–47 y 5–95." in text
    assert "drawn there by the game" in text and "walkable" not in text


def test_generate_dictates_the_tool_call(tmp_path, monkeypatch):
    cam = rb.discover(make_in_dir(tmp_path), None)[0]
    png = png_bytes(np.zeros((1024, 1536, 3), np.uint8))
    fake = FakeSubprocess(png)
    monkeypatch.setattr(subprocess, "run", fake.run)
    ref, out = tmp_path / "ref.png", tmp_path / "out.png"
    ref.write_bytes(b"x")
    assert rb.generate("gemini-3.1-pro", cam, "the prompt", [ref, cam.guide], out) == png
    cmd = fake.calls[0]
    assert cmd[0] == "agy" and "gemini-3.1-pro" in cmd and "--json-schema" not in cmd
    text = cmd[2]
    assert f'ImagePaths = ["{ref.absolute()}", "{cam.guide.absolute()}"]' in text
    assert 'AspectRatio = "3:2"' in text and 'ImageName = "plate_f00_c000"' in text
    assert f"copy the generated image file to exactly this path: {out}. Output ONLY the word SUCCESS" in text
    assert "---PROMPT---\nthe prompt\n---END---" in text
    assert "Look at the image" not in text


def test_generate_raises_when_nothing_was_copied(tmp_path, monkeypatch):
    cam = rb.discover(make_in_dir(tmp_path), None)[0]
    fake = FakeSubprocess(no_image=True)
    monkeypatch.setattr(subprocess, "run", fake.run)
    out = rb.temp_png()
    try:
        with pytest.raises(RuntimeError, match="no image generated or copied by agent"):
            rb.generate("gemini-3.1-pro", cam, "p", [tmp_path / "ref.png"], out)
    finally:
        out.unlink(missing_ok=True)


def test_reference_and_attachment_rules(tmp_path):
    cams = rb.discover(make_in_dir(tmp_path), None)
    ref = rb.make_reference(cams[0])
    try:
        assert load_png_rgb(ref).shape == (800, 1280, 3)
        assert rb.attachments(cams[0], ref, leaked=False) == [ref, cams[0].guide]
        assert rb.attachments(cams[0], ref, leaked=True) == [ref]
        assert rb.attachments(cams[1], ref, leaked=False) == [ref]         # no guide
    finally:
        ref.unlink()
    assert rb.image_name(cams[0]) == "plate_f00_c000"
    assert rb.image_name(rb.Camera(-1, 10, cams[0].source, None, "screens/ress10")) == "screen_ress10"


def test_make_reference_cleans_up_its_own_temp_file_on_failure(tmp_path, monkeypatch):
    cam = rb.discover(make_in_dir(tmp_path), None)[0]
    before = set(pathlib.Path(tempfile.gettempdir()).glob("*.png"))

    def boom(_path):
        raise ValueError("corrupt source")

    monkeypatch.setattr("PyAitD.render.asset_resolver.load_png_rgb", boom)
    with pytest.raises(ValueError, match="corrupt source"):
        rb.make_reference(cam)
    assert set(pathlib.Path(tempfile.gettempdir()).glob("*.png")) == before


def test_regenerate_attaches_reference_and_guide_and_cleans_up(tmp_path, monkeypatch):
    fake = FakeSubprocess(png_bytes(np.zeros((1024, 1536, 3), np.uint8)))
    monkeypatch.setattr(subprocess, "run", fake.run)
    before = set(pathlib.Path(tempfile.gettempdir()).glob("*.png"))
    assert _run(tmp_path, fake) == (3, 0)
    gen = [c[2] for c in fake.calls if "--json-schema" not in c]
    assert gen[0].count(".png") >= 2 and str((tmp_path / "in/guides/floor00/camera000.png").absolute()) in gen[0]
    assert str((tmp_path / "in/guides/floor00/camera000.png").absolute()) not in gen[1]   # camera001 has no guide
    assert set(pathlib.Path(tempfile.gettempdir()).glob("*.png")) == before


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
    opts = dict(text_model="gemini-3.1-pro", style="s.", force=False, dry_run=False, log=lambda *_: None)
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
        "inventory": INVENTORY, "model": "gemini-3.1-pro", "sha256": hashlib.sha256(src).hexdigest()}
    assert len(fake.calls) == 6
    gen_prompt = fake.calls[1][2]
    assert rb.generation_prompt(INVENTORY, "s.", guide_attached=True) in gen_prompt


def test_regenerate_resumes_and_force_redoes(tmp_path, monkeypatch):
    fake = FakeSubprocess(png_bytes(np.zeros((1024, 1536, 3), np.uint8)))
    monkeypatch.setattr(subprocess, "run", fake.run)
    
    _run(tmp_path, fake)
    fake.calls.clear()
    assert _run(tmp_path, fake) == (0, 0)
    assert fake.calls == []
    
    path = tmp_path / "out" / rb.PROMPTS_FILE
    prompts = rb.load_prompts(path)
    prompts["floor00/camera001"]["inventory"]["prompt"] = "EDITED"
    rb.save_prompts(path, prompts)
    (tmp_path / "out/backgrounds/floor00/camera001.png").unlink()

    assert _run(tmp_path, fake) == (1, 0)
    assert len(fake.calls) == 1 and "EDITED" in fake.calls[0][2]
    assert rb.load_prompts(path)["floor00/camera001"]["inventory"]["prompt"] == "EDITED"

    fake.calls.clear()
    assert _run(tmp_path, fake, force=True) == (3, 0)
    assert len(fake.calls) == 6
    assert rb.load_prompts(path)["floor00/camera001"]["inventory"]["prompt"] != "EDITED"


def test_regenerate_continues_after_a_failed_camera(tmp_path, monkeypatch):
    logs = []
    fake = FakeSubprocess(png_bytes(np.zeros((1024, 1536, 3), np.uint8)), fail_image_calls={2})
    monkeypatch.setattr(subprocess, "run", fake.run)
    
    assert _run(tmp_path, fake, log=logs.append) == (2, 1)
    assert not (tmp_path / "out/backgrounds/floor00/camera001.png").exists()
    assert any("floor00/camera001: failed:" in line for line in logs)


def test_regenerate_counts_empty_description_as_failed(tmp_path, monkeypatch):
    logs = []
    fake = FakeSubprocess(png_bytes(np.zeros((1024, 1536, 3), np.uint8)),
                          describe={"prompt": "", "camera": "c", "objects": []})
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
    opts = dict(text_model="gemini-3.1-pro", style="s.", force=False, dry_run=False, log=lambda *_: None)
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


def test_regenerate_redescribes_a_schema_1_prompt_entry(tmp_path, monkeypatch):
    fake = FakeSubprocess(png_bytes(np.zeros((1024, 1536, 3), np.uint8)))
    monkeypatch.setattr(subprocess, "run", fake.run)
    out = tmp_path / "out"
    cams = rb.discover(make_in_dir(tmp_path), {1})
    sha = hashlib.sha256(cams[0].source.read_bytes()).hexdigest()
    rb.save_prompts(out / rb.PROMPTS_FILE, {"floor01/camera000": {"prompt": "old prose", "model": "m", "sha256": sha}})
    assert rb.regenerate(cams, out, text_model="t", style="s.", force=False, dry_run=False,
                         log=lambda *_: None) == (1, 0)
    assert "--json-schema" in fake.calls[0]                       # re-described despite a matching sha
    assert rb.load_prompts(out / rb.PROMPTS_FILE)["floor01/camera000"]["inventory"] == INVENTORY


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
    
    assert rb.regenerate(cams, out, text_model="t", style="s",
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
    
    assert rb.regenerate(cams, out, text_model="t", style="s",
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
    err = capsys.readouterr().err
    assert "nothing to regenerate" in err
    assert "backgrounds/" in err and "screens/" in err   # --screens defaults on: both are named
    assert not (tmp_path / "out").exists()


def test_main_exit_message_omits_screens_when_disabled(tmp_path, capsys):
    assert rb.main([str(tmp_path / "empty"), "--out", str(tmp_path / "out"), "--no-screens"]) == 2
    err = capsys.readouterr().err
    assert "backgrounds/" in err and "screens/" not in err


def test_main_runs_with_injected_subprocess_and_reports_failures(tmp_path, monkeypatch, capsys):
    in_dir = make_in_dir(tmp_path)
    fake = FakeSubprocess(png_bytes(np.zeros((1024, 1536, 3), np.uint8)), fail_image_calls={3})
    monkeypatch.setattr(subprocess, "run", fake.run)
    
    assert rb.main([str(in_dir), "--out", str(tmp_path / "out"), "--floors", "0-7",
                    "--style", "noir.", "--text-model", "t-model"]) == 1
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


def test_regenerate_screens_land_under_screens_and_copy_manifest(tmp_path, monkeypatch):
    """regenerate()'s `backgrounds/{key}.png` vs `{key}.png` branch is what
    makes the output directory directly usable as --overrides DIR for
    screens too -- nothing exercised regenerate() with a screen item before
    this, so a typo there (e.g. `backgrounds/screens/ress10.png`) would have
    passed every other test silently. This also covers the untested
    _copy_manifest depth arithmetic on a screens-only run (depth=1, not the
    depth=2 every other regenerate() test exercises via cameras)."""
    in_dir = tmp_path / "in"
    xb.save_png(in_dir / "screens" / "ress10.png", checker_pixels(1))
    manifest = export_manifest([], "stub", 4, screens=[{"entry": 10, "sha256": "s"}])
    xb.save_manifest(in_dir, manifest)
    cams = rb.discover(in_dir, None)
    assert [c.key for c in cams] == ["screens/ress10"]
    fake = FakeSubprocess(png_bytes(np.full((1024, 1536, 3), 9, np.uint8)))
    monkeypatch.setattr(subprocess, "run", fake.run)
    out = tmp_path / "out"

    assert rb.regenerate(cams, out, text_model="t", style="s",
                         force=False, dry_run=False, log=lambda *_: None) == (1, 0)
    assert (out / "screens" / "ress10.png").is_file()
    assert not (out / "backgrounds").exists()
    assert json.loads((out / "manifest.json").read_text()) == manifest


GOOD_VERDICT = {"camera_same": True, "guide_lines_visible": False,
                "objects": [{"name": "window", "present": True, "same_kind": True, "same_count": True,
                             "same_position": True, "note": ""},
                            {"name": "barrels", "present": True, "same_kind": True, "same_count": True,
                             "same_position": True, "note": ""}],
                "extra_objects": [], "corrections": []}


def _verdict(**changes):
    v = json.loads(json.dumps(GOOD_VERDICT))
    v.update(changes)
    return v


def test_judge_sends_both_images_the_inventory_and_the_schema(tmp_path, monkeypatch):
    cam = rb.discover(make_in_dir(tmp_path), None)[0]
    fake = FakeSubprocess(judge=[GOOD_VERDICT])
    monkeypatch.setattr(subprocess, "run", fake.run)
    ref, cand = tmp_path / "ref.png", tmp_path / "cand.png"
    assert rb.judge("gemini-3.1-pro", cam, INVENTORY, ref, cand) == GOOD_VERDICT
    cmd = fake.calls[0]
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == rb.JUDGE_SCHEMA
    text = cmd[2]
    assert str(ref.absolute()) in text and str(cand.absolute()) in text
    assert rb.GAME_CONTEXT in text and json.dumps(INVENTORY["objects"]) in text
    assert "For every inventory object" in text and "within about 5 %" in text


def test_judge_accepts_only_a_fully_matching_verdict():
    assert rb.judge_accepts(GOOD_VERDICT, INVENTORY)
    assert not rb.judge_accepts(_verdict(camera_same=False), INVENTORY)
    assert not rb.judge_accepts(_verdict(guide_lines_visible=True), INVENTORY)
    assert not rb.judge_accepts(_verdict(extra_objects=["table"]), INVENTORY)
    bad = _verdict()
    bad["objects"][1]["same_count"] = False
    assert not rb.judge_accepts(bad, INVENTORY)
    unreported = _verdict(objects=GOOD_VERDICT["objects"][:1])
    assert not rb.judge_accepts(unreported, INVENTORY)


def test_judge_corrections_name_every_problem():
    v = _verdict(camera_same=False, guide_lines_visible=True, extra_objects=["table"],
                 corrections=["move the window left"])
    v["objects"][1].update(same_count=False, note="four barrels instead of three")
    v["objects"] = v["objects"][:2]
    out = rb.judge_corrections(v, INVENTORY)
    assert out[0] == "move the window left"
    assert "barrels: four barrels instead of three" in out
    assert "extra object: table" in out
    assert "red, blue or green guide lines are visible: do not draw them" in out
    assert "camera position, framing or perspective differs" in out
    assert rb.judge_corrections(GOOD_VERDICT, INVENTORY) == []
    missing = _verdict(objects=GOOD_VERDICT["objects"][:1])
    assert "barrels: not assessed by the judge" in rb.judge_corrections(missing, INVENTORY)


def test_judge_tolerates_a_null_objects_or_extra_objects_field():
    """A verdict field present but explicitly null (not merely missing) must
    not raise -- it is model misbehaviour to reject and retry, not a crash."""
    null_objects = _verdict(objects=None)
    assert rb.judge_accepts(null_objects, INVENTORY) is False
    assert rb.judge_corrections(null_objects, INVENTORY) == [
        "window: not assessed by the judge", "barrels: not assessed by the judge"]

    null_extra = _verdict(extra_objects=None)
    assert rb.judge_accepts(null_extra, INVENTORY) is True
    assert rb.judge_corrections(null_extra, INVENTORY) == []

    null_corrections = _verdict(corrections=None)   # same list(x.get(..., [])) pattern as extra_objects
    assert rb.judge_accepts(null_corrections, INVENTORY) is True
    assert rb.judge_corrections(null_corrections, INVENTORY) == []

