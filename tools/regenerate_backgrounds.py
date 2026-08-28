# SPDX-License-Identifier: GPL-2.0-only
"""Regenerate exported backgrounds with Gemini: describe each plate with a
text model into a structured inventory, then run generate -> fit -> gate ->
judge rounds against the original and its layout sidecar, retrying with
corrections up to `--attempts` times. A candidate is written only once the
offline numpy gate and the vision judge both accept it; a camera that never
passes writes nothing, so the game falls back to the original. Every
camera's outcome (attempts, gate scores, judge verdicts) is recorded in
report.json.

docs/superpowers/specs/2026-08-25-gemini-background-regeneration-design.md,
docs/superpowers/specs/2026-08-27-background-layout-fidelity-design.md."""
import argparse
import dataclasses
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from tools.export_backgrounds import parse_floors, save_png  # noqa: E402
from tools.plate_check import fmt_bbox, gate, layout_regions  # noqa: E402

DEFAULT_TEXT_MODEL = "gemini-3.1-pro"
DEFAULT_STYLE = "Dark 1920s Louisiana mansion, moody film lighting, subtle grain."
TARGET_SIZE = (1280, 800)   # 4 x 320x200
GENERATE_ASPECT = "3:2"     # nearest Gemini ratio to 16:10 (3:2 is narrower); extra height is centre-cropped after
PROMPTS_FILE = "prompts.json"
REPORT_FILE = "report.json"
MAX_CONSECUTIVE_FAILURES = 3   # a dead model/key fails every camera: stop early
AGY_OUTPUT_TAIL = 400          # chars of agy's own output kept in an error message
UNCHANGED_TOLERANCE = 2.0      # mean abs channel difference: below it the plate is the reference
UNCHANGED_CORRECTION = ("the last attempt returned the reference image itself, not a new painting: call generate_image and paint the scene, do not copy an attachment to the output path")
MAX_CONSECUTIVE_REJECTS = 5    # a model that cannot keep the layout: stop burning attempts
REJECT_ABORT = ("aborting after 5 consecutive layout mismatches: edit the inventory in prompts.json, "
                "lower --gate-scale, or raise --attempts")
_CAMERA_RE = re.compile(r"floor(\d\d)/camera(\d\d\d)\.png$")
_SCREEN_RE = re.compile(r"screens/ress(\d\d)\.png$")


@dataclasses.dataclass(frozen=True)
class Camera:
    floor: int
    camera: int
    source: pathlib.Path
    guide: pathlib.Path | None
    key: str
    layout: pathlib.Path | None = None


def discover(in_dir, floors, screens=True):
    """Every IN/backgrounds/floorNN/cameraNNN.png, sorted, restricted to
    `floors` (None = all); every IN/alt_backgrounds/floorNN/cameraNNN.png
    (the 5 KILLED_SORCERER road alts, shared guides); then every
    IN/screens/ressNN.png (floor -1, camera = entry) when `screens`.
    Guide and layout-sidecar paths only when the files exist."""
    in_dir = pathlib.Path(in_dir)
    cams = []
    for path in sorted((in_dir / "backgrounds").glob("floor[0-9][0-9]/camera[0-9][0-9][0-9].png")):
        m = _CAMERA_RE.search(path.as_posix())
        floor, cam = int(m.group(1)), int(m.group(2))
        if floors is not None and floor not in floors:
            continue
        key = f"floor{floor:02d}/camera{cam:03d}"
        guide = in_dir / "guides" / f"{key}.png"
        layout = in_dir / "guides" / f"{key}.json"
        cams.append(Camera(floor, cam, path, guide if guide.is_file() else None, key,
                           layout if layout.is_file() else None))
    for path in sorted((in_dir / "alt_backgrounds").glob("floor[0-9][0-9]/camera[0-9][0-9][0-9].png")):
        m = _CAMERA_RE.search(path.as_posix())
        if m is None:
            continue
        floor, cam = int(m.group(1)), int(m.group(2))
        if floors is not None and floor not in floors:
            continue
        base_key = f"floor{floor:02d}/camera{cam:03d}"
        key = f"alt_backgrounds/{base_key}"
        guide = in_dir / "guides" / f"{base_key}.png"
        layout = in_dir / "guides" / f"{base_key}.json"
        cams.append(Camera(floor, cam, path, guide if guide.is_file() else None, key,
                           layout if layout.is_file() else None))
    if screens:
        for path in sorted((in_dir / "screens").glob("ress[0-9][0-9].png")):
            entry = int(_SCREEN_RE.search(path.as_posix()).group(1))
            key = f"screens/ress{entry:02d}"
            guide = in_dir / "guides" / f"{key}.png"
            layout = in_dir / "guides" / f"{key}.json"
            cams.append(Camera(-1, entry, path, guide if guide.is_file() else None, key,
                               layout if layout.is_file() else None))
    return cams


_GUIDE_LEGEND_NOTE = (" Ignore the thin strip of colour swatches along the bottom edge of the "
                      "second image; it is a legend, not part of the scene.")
_GUIDE_DESCRIBE = ("The second image is the same frame with an overlay: red outlines mark "
                   "foreground objects that must stay in front, blue boxes mark walls and solid "
                   "furniture, green polygons mark walkable floor. Describe the scene so those "
                   "structures keep their places." + _GUIDE_LEGEND_NOTE)
_GUIDE_GENERATE = ("The second image marks the layout: red outlines are foreground objects, blue "
                   "boxes are walls and solid furniture, green polygons are walkable floor; keep "
                   "all of them where they are and do not draw the coloured lines." + _GUIDE_LEGEND_NOTE)
_SCREEN_DESCRIBE = ("The second image outlines in blue the regions where the game later draws "
                    "text or portraits; describe the artwork so those regions stay plain and "
                    "uncluttered." + _GUIDE_LEGEND_NOTE)
_SCREEN_GENERATE = ("The second image outlines in blue the regions where text and portraits are "
                    "drawn there by the game: keep those areas plain, without text, and do not "
                    "draw the blue lines." + _GUIDE_LEGEND_NOTE)

GAME_CONTEXT = ("This image depicts a scene from the Alone in the Dark 1 game. Atmosphere notes: The "
                "entire Alone in the Dark 1 game evokes a gothic horror/Lovecraftian mood. The darkness, "
                "somber portraits, and period-appropriate text work together to set the tone before the "
                "player even enters the mansion. The design is effective at establishing dread and mystery.")

INVENTORY_SCHEMA = {
    "type": "object", "required": ["prompt", "camera", "objects"],
    "properties": {
        "prompt": {"type": "string"},
        "camera": {"type": "string"},
        "objects": {"type": "array", "items": {
            "type": "object", "required": ["name", "kind", "count", "bbox"],
            "properties": {"name": {"type": "string"}, "kind": {"type": "string"},
                           "count": {"type": "integer", "minimum": 1},
                           "bbox": {"type": "array", "minItems": 4, "maxItems": 4,
                                    "items": {"type": "integer", "minimum": 0, "maximum": 100}}}}}}}

_CAMERA_RERENDER = ("Re-render the first image as a photorealistic photograph of exactly this scene: same "
                    "camera position, framing and perspective; every wall, door, window, stair and piece "
                    "of furniture stays where it is, same kind and same count — add nothing, remove "
                    "nothing. Change only materials, lighting detail and realism.")
_SCREEN_RERENDER = ("Re-render the first image as a painted illustration of exactly this composition, "
                    "keeping the framing and every element's placement; change only the medium and finish.")
_REGION_LABELS = (("mask", "foreground occluders at "), ("collision", "solid walls and furniture at "),
                  ("walkable", "walkable floor at "))


def describe_prompt(guide_present, screen=False):
    text = (GAME_CONTEXT + " Describe this 320x200 background as a single-paragraph prompt for a "
            "photorealistic image generator. Name the room type, the camera angle and height, every "
            "piece of furniture and architecture with its position in frame, the light sources and "
            "their direction, materials and colours, and the mood. Do not mention pixel art or "
            "resolution. Then list every distinct object with its kind, count and bounding box in "
            "percent of frame (x0, y0, x1, y1; x left to right, y top to bottom).")
    if not guide_present:
        return text
    return text + " " + (_SCREEN_DESCRIBE if screen else _GUIDE_DESCRIBE)


def _bbox_list(bbox):
    x0, y0, x1, y1 = bbox
    return fmt_bbox((x0, y0, x1, y1))


def generation_prompt(inventory, style, regions=(), corrections=(), rejected_attempt=0,
                      guide_attached=False, screen=False):
    """The Prompt argument of the generate_image call, in the spec's order:
    game context, re-render instruction, guide sentence, layout from the
    inventory and the sidecar regions, corrections from the last rejected
    attempt, the inventory's camera and prose, then `style` verbatim."""
    parts = [GAME_CONTEXT, _SCREEN_RERENDER if screen else _CAMERA_RERENDER]
    if guide_attached:
        parts.append(_SCREEN_GENERATE if screen else _GUIDE_GENERATE)
    objects = "; ".join(f"{o['count']} {o['kind']} {_bbox_list(o['bbox'])}" for o in inventory["objects"])
    parts.append("Layout (percent of frame, x left→right, y top→bottom): " + objects + ".")
    by_kind = {}
    for region in regions:
        by_kind.setdefault(region.kind, []).append(fmt_bbox(region.bbox_pct))
    if screen:
        if by_kind.get("blit"):
            parts.append("Regions that must stay plain: " + "; ".join(by_kind["blit"]) + ".")
    else:
        clauses = [label + ", ".join(by_kind[kind]) for kind, label in _REGION_LABELS if by_kind.get(kind)]
        if clauses:
            sentence = "; ".join(clauses)
            parts.append(sentence[0].upper() + sentence[1:] + ".")
    if corrections:
        parts.append(f"Attempt {rejected_attempt} was rejected: " + "; ".join(corrections) + ".")
    parts.append(inventory["camera"].strip())
    parts.append(inventory["prompt"].strip())
    return " ".join(p for p in parts if p) + " " + style


def load_json(path):
    path = pathlib.Path(path)
    return json.loads(path.read_text()) if path.is_file() else {}


def save_json(path, data):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
    os.replace(tmp, path)


load_prompts = load_json
save_prompts = save_json


def _agy_tail(result):
    """The tail of what agy printed. agy's own words are the only evidence of
    why a call produced nothing, and a report entry without them cannot be
    diagnosed. Trimmed so a chatty run does not bloat report.json."""
    text = ((result.stderr or "") + (result.stdout or "")).strip()
    return text[-AGY_OUTPUT_TAIL:] if text else "no output"


def _run_agy(cmd):
    """Run an agy call and return it, having raised on a non-zero exit.
    check=True would raise CalledProcessError, whose message carries the whole
    argv -- the entire prompt -- and none of agy's stderr."""
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"agy exited {result.returncode}: {_agy_tail(result)}")
    return result


GENERATE_REPORT_SCHEMA = {
    "type": "object",
    "properties": {"generated": {"type": "boolean"},
                   "error": {"type": "string"}},
    "required": ["generated", "error"],
    "additionalProperties": False,
}


def agy_structured(model, instructions, schema):
    """One agy call with an enforced JSON schema; returns structured_output."""
    cmd = ["agy", "-p", instructions, "--dangerously-skip-permissions", "--effort", "low",
           "--model", model, "--output-format", "json", "--json-schema", json.dumps(schema)]
    result = _run_agy(cmd)
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        payload = None
    out = payload.get("structured_output") if isinstance(payload, dict) else None
    if not isinstance(out, dict):
        raise RuntimeError("agy returned no structured output")
    return out


def describe(model, cam):
    """One text-model call via agy: original (+ guide) -> inventory dict."""
    instructions = f"Look at the image at {cam.source.absolute()}. "
    if cam.guide:
        instructions += f"Also look at the guide image at {cam.guide.absolute()}. "
    instructions += describe_prompt(cam.guide is not None, screen=cam.floor == -1)
    inventory = agy_structured(model, instructions, INVENTORY_SCHEMA)
    if not str(inventory.get("prompt", "")).strip():
        raise RuntimeError("empty description from text model")
    if not inventory.get("objects"):
        raise RuntimeError("empty inventory from text model")
    return inventory


JUDGE_SCHEMA = {
    "type": "object",
    "required": ["camera_same", "guide_lines_visible", "objects", "extra_objects", "corrections"],
    "properties": {
        "camera_same": {"type": "boolean"},
        "guide_lines_visible": {"type": "boolean"},
        "objects": {"type": "array", "items": {
            "type": "object",
            "required": ["name", "present", "same_kind", "same_count", "same_position", "note"],
            "properties": {"name": {"type": "string"}, "present": {"type": "boolean"},
                           "same_kind": {"type": "boolean"}, "same_count": {"type": "boolean"},
                           "same_position": {"type": "boolean"}, "note": {"type": "string"}}}},
        "extra_objects": {"type": "array", "items": {"type": "string"}},
        "corrections": {"type": "array", "items": {"type": "string"}}}}

_OBJECT_FLAGS = ("present", "same_kind", "same_count", "same_position")


def judge(model, cam, inventory, ref_path, candidate_path):
    """One text-model call via agy: original + candidate + inventory -> verdict."""
    instructions = (
        f"Look at the image at {pathlib.Path(ref_path).absolute()} (the original) and the image at "
        f"{pathlib.Path(candidate_path).absolute()} (the candidate). {GAME_CONTEXT} The original's "
        f"inventory is: {json.dumps(inventory['objects'])} For every inventory object report whether it "
        "is present in the candidate, of the same kind, the same count, and at the same position (within "
        "about 5 % of the frame). List objects in the candidate that are not in the inventory. Say whether "
        "the camera position, framing and perspective are the same, and whether any red, blue or green "
        "outline lines are visible. Give one short correction sentence per problem.")
    return agy_structured(model, instructions, JUDGE_SCHEMA)


def _reported(verdict):
    return {o.get("name"): o for o in verdict.get("objects") or []}


def judge_accepts(verdict, inventory):
    if not verdict.get("camera_same") or verdict.get("guide_lines_visible") or verdict.get("extra_objects"):
        return False
    reported = _reported(verdict)
    for obj in inventory["objects"]:
        r = reported.get(obj["name"])
        if r is None or not all(r.get(flag) for flag in _OBJECT_FLAGS):
            return False
    return True


def judge_corrections(verdict, inventory):
    """Corrections for the next attempt: the judge's own sentences, then one
    line per failing or unreported object, extra object and flag."""
    out = list(verdict.get("corrections") or [])
    reported = _reported(verdict)
    for obj in inventory["objects"]:
        r = reported.get(obj["name"])
        if r is None:
            out.append(f"{obj['name']}: not assessed by the judge")
        elif not all(r.get(flag) for flag in _OBJECT_FLAGS):
            out.append(f"{obj['name']}: {r.get('note') or 'differs from the original'}")
    for extra in verdict.get("extra_objects") or []:
        out.append(f"extra object: {extra}")
    if verdict.get("guide_lines_visible"):
        out.append("red, blue or green guide lines are visible: do not draw them")
    if not verdict.get("camera_same"):
        out.append("camera position, framing or perspective differs")
    return out


def temp_png():
    """An empty temp file with a .png suffix; the caller unlinks it."""
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    return pathlib.Path(path)


def make_reference(cam):
    """The original upscaled 4x (nearest) as a temp PNG: the first reference
    image of every generate call, at the guide's scale. Caller unlinks on
    success; a failure partway through here unlinks its own partial file,
    including save_png's sibling `.tmp` file if it died mid-write."""
    from PyAitD.render.asset_resolver import load_png_rgb
    from PyAitD.render.background_export import nearest_upscale
    path = temp_png()
    try:
        save_png(path, nearest_upscale(load_png_rgb(cam.source), 4))
    except BaseException:
        path.unlink(missing_ok=True)
        path.with_name(path.name + ".tmp").unlink(missing_ok=True)
        raise
    return path


def attachments(cam, ref, leaked):
    """Reference images for a generate call: [ref, guide] until an attempt
    leaks guide colours into the plate, then [ref] only."""
    if leaked or cam.guide is None:
        return [ref]
    return [ref, cam.guide]


def image_name(cam):
    return f"screen_ress{cam.camera:02d}" if cam.floor == -1 else f"plate_f{cam.floor:02d}_c{cam.camera:03d}"


def generate(model, cam, prompt, attached, out_path):
    """One image-model call via agy: dictate the generate_image tool call
    (references, aspect, name, prompt) and read the copied result. The agent
    reports the tool's own outcome under a schema rather than a fixed success
    word -- asking for one word invites a failed call to print it anyway, and
    that is exactly what an exhausted image quota was observed doing."""
    paths = ", ".join(f'"{pathlib.Path(p).absolute()}"' for p in attached)
    instructions = (
        f"Call the generate_image tool exactly once with these arguments: ImagePaths = [{paths}]; "
        f'AspectRatio = "{GENERATE_ASPECT}"; ImageName = "{image_name(cam)}"; Prompt = the text between '
        f"the markers below. Then copy the generated image file to exactly this path: {out_path}. "
        f"Then report what the tool did: `generated` is true only if generate_image returned an image "
        f"and you copied that image to that path; never copy an input image there instead. If anything "
        f"failed, put the tool's own error text in `error` verbatim.\n---PROMPT---\n{prompt}\n---END---")
    report = agy_structured(model, instructions, GENERATE_REPORT_SCHEMA)
    out_path = pathlib.Path(out_path)
    if not out_path.is_file() or out_path.stat().st_size == 0:
        # The file is the truth; the report only says why there isn't one.
        detail = (report.get("error") or "").strip() or "the agent reported no error"
        raise RuntimeError(f"no image generated or copied by agent: {detail}")
    return out_path.read_bytes()


def is_reference_copy(fitted, original):
    """True when the agent handed back the reference instead of a new plate.
    The gate cannot catch this: the reference is `nearest_upscale(original, 4)`
    and `fit_to_target` inverts that exactly, so a copy scores a perfect 1.00
    on ncc and on every recall by construction."""
    from PyAitD.render.background_export import nearest_upscale
    ref = nearest_upscale(original, 4)
    if ref.shape != fitted.shape:
        return False
    return float(np.abs(fitted.astype(np.int16) - ref.astype(np.int16)).mean()) <= UNCHANGED_TOLERANCE


def fit_to_target(png_bytes):
    """Decode, centre-crop to the largest 16:10 rectangle, smooth-scale to
    TARGET_SIZE. Returns (800, 1280, 3) uint8 so save_png can write it."""
    import io
    import pygame
    surface = pygame.image.load(io.BytesIO(png_bytes))
    rgb = np.ascontiguousarray(pygame.surfarray.array3d(surface).swapaxes(0, 1))
    h, w = rgb.shape[:2]
    if w * 10 > h * 16:
        new_w = h * 16 // 10
        x0 = (w - new_w) // 2
        rgb = rgb[:, x0:x0 + new_w]
    elif w * 10 < h * 16:
        new_h = w * 10 // 16
        y0 = (h - new_h) // 2
        rgb = rgb[y0:y0 + new_h]
    cropped = pygame.surfarray.make_surface(np.ascontiguousarray(rgb.swapaxes(0, 1)))
    scaled = pygame.transform.smoothscale(cropped, TARGET_SIZE)
    return np.ascontiguousarray(pygame.surfarray.array3d(scaled).swapaxes(0, 1)).astype(np.uint8)


@dataclasses.dataclass
class CameraOutcome:
    status: str        # ok | rejected | error
    attempts: list     # report entries, one per attempt (or {"error": msg})
    message: str


def _process_camera(cam, target, prompts, prompts_path, *, text_model, style, attempts, gate_scale,
                    force, log):
    """Describe (cached), then up to `attempts` generate -> gate -> judge
    rounds; writes `target` on acceptance. Never raises: errors become an
    "error" outcome with the message."""
    from PyAitD.render.asset_resolver import load_png_rgb
    record = []
    try:
        source_sha = hashlib.sha256(cam.source.read_bytes()).hexdigest()
        entry = prompts.get(cam.key)
        stale = entry is None or "inventory" not in entry or entry.get("sha256") != source_sha
        if stale or force:
            inventory = describe(text_model, cam)
            prompts[cam.key] = {"inventory": inventory, "model": text_model, "sha256": source_sha}
            save_prompts(prompts_path, prompts)
        inventory = prompts[cam.key]["inventory"]
        original = load_png_rgb(cam.source)
        layout = json.loads(cam.layout.read_text()) if cam.layout else None
        if layout is None:
            log(f"{cam.key}: no layout: framing gate only")
        regions = layout_regions(layout)
        screen = cam.floor == -1
        ref = make_reference(cam)
        try:
            leaked, corrections = False, []
            for n in range(1, attempts + 1):
                attached = attachments(cam, ref, leaked)
                prompt = generation_prompt(inventory, style, regions, corrections, rejected_attempt=n - 1,
                                           guide_attached=len(attached) > 1, screen=screen)
                attempt = {"attached": ["ref"] + (["guide"] if len(attached) > 1 else []),
                           "gate": None, "judge": None}
                record.append(attempt)
                out = temp_png()
                try:
                    png = generate(text_model, cam, prompt, attached, out)
                finally:
                    out.unlink(missing_ok=True)
                fitted = fit_to_target(png)
                if is_reference_copy(fitted, original):
                    attempt["gate"] = {"passed": False, "scores": {}, "failures": [UNCHANGED_CORRECTION]}
                    corrections = [UNCHANGED_CORRECTION]
                    continue
                result = gate(fitted, original, layout, gate_scale)
                attempt["gate"] = {"passed": result.passed, "scores": result.scores, "failures": result.failures}
                if not result.passed:
                    leaked = leaked or result.leaked
                    corrections = list(result.failures)
                    continue
                cand = temp_png()
                try:
                    save_png(cand, fitted)
                    verdict = judge(text_model, cam, inventory, ref, cand)
                finally:
                    cand.unlink(missing_ok=True)
                attempt["judge"] = verdict
                if judge_accepts(verdict, inventory):
                    save_png(target, fitted)
                    return CameraOutcome("ok", record, f"attempt {n}/{attempts}, ncc {result.scores['ncc']:.2f}, "
                                                       f"recall {result.scores['edge_recall']:.2f}")
                leaked = leaked or bool(verdict.get("guide_lines_visible"))
                corrections = judge_corrections(verdict, inventory)
            return CameraOutcome("rejected", record,
                                 f"layout mismatch after {attempts} attempts (last: {'; '.join(corrections)})")
        finally:
            ref.unlink(missing_ok=True)
    except Exception as exc:   # per-camera: agy errors, bad JSON, undecodable image
        record.append({"error": str(exc)})
        return CameraOutcome("error", record, str(exc))


def _copy_manifest(cams, out_dir):
    if not cams:
        return
    first = cams[0]
    # IN/backgrounds/floorNN/cameraNNN.png is two levels under IN; IN/screens/ressNN.png
    # is only one -- derive the level from the first camera's own kind so this is
    # correct regardless of whether a background or a screen sorts first.
    depth = 1 if first.floor == -1 else 2
    src = first.source.parents[depth] / "manifest.json"
    dst = pathlib.Path(out_dir) / "manifest.json"
    if src.is_file() and not dst.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".tmp")
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)


def regenerate(cams, out_dir, *, text_model, style, attempts=3, gate_scale=1.0, force, dry_run, log=print):
    """Describe + generate + verify every camera into out_dir. Returns
    (done, failed); failed counts rejected and errored cameras. Existing
    outputs are skipped unless force; cached inventories are reused unless
    force or stale; prompts.json and report.json are saved after every
    camera. Errors abort after MAX_CONSECUTIVE_FAILURES in a row,
    rejections after MAX_CONSECUTIVE_REJECTS in a row."""
    out_dir = pathlib.Path(out_dir)
    prompts_path, report_path = out_dir / PROMPTS_FILE, out_dir / REPORT_FILE
    prompts, report = load_prompts(prompts_path), load_json(report_path)
    done = failed = errors = rejects = 0
    for cam in cams:
        if cam.floor == -1:
            target = out_dir / f"{cam.key}.png"
        elif cam.key.startswith("alt_backgrounds/"):
            target = out_dir / f"{cam.key}.png"
        else:
            target = out_dir / f"backgrounds/{cam.key}.png"
        if target.is_file() and not force:
            log(f"{cam.key}: exists, skipped")
            continue
        guide = "yes" if cam.guide is not None else "no"
        layout = "yes" if cam.layout is not None else "no"
        cached = "yes" if cam.key in prompts and "inventory" in prompts[cam.key] else "no"
        if dry_run:
            log(f"{cam.key}: would regenerate (guide {guide}, layout {layout}, prompt cached {cached})")
            continue
        outcome = _process_camera(cam, target, prompts, prompts_path, text_model=text_model, style=style,
                                  attempts=attempts, gate_scale=gate_scale, force=force, log=log)
        report[cam.key] = {"accepted": outcome.status == "ok", "attempts": outcome.attempts}
        save_json(report_path, report)
        if outcome.status == "ok":
            done += 1
            errors = rejects = 0
            log(f"{cam.key}: ok ({outcome.message})")
            continue
        failed += 1
        log(f"{cam.key}: failed: {outcome.message}")
        if outcome.status == "rejected":
            rejects, errors = rejects + 1, 0
            if rejects >= MAX_CONSECUTIVE_REJECTS:
                log(REJECT_ABORT)
                break
        else:
            errors, rejects = errors + 1, 0
            if errors >= MAX_CONSECUTIVE_FAILURES:
                log(f"aborting after {errors} consecutive failures")
                break
    if not dry_run:
        _copy_manifest(cams, out_dir)
    return done, failed


def _positive_int(text):
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


def _non_negative_float(text):
    value = float(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return value


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Regenerate exported backgrounds with Gemini.")
    p.add_argument("in_dir", help="override dir from `make export-backgrounds` (originals + guides)")
    p.add_argument("--out", required=True, help="output override dir (same layout)")
    p.add_argument("--floors", default="0-7")
    p.add_argument("--style", default=DEFAULT_STYLE)
    p.add_argument("--text-model", default=DEFAULT_TEXT_MODEL)
    p.add_argument("--attempts", type=_positive_int, default=3,
                    help="generate/verify rounds per camera before rejecting it (default 3)")
    p.add_argument("--gate-scale", type=_non_negative_float, default=1.0,
                    help="relax the gate's structure thresholds (ncc, edge recall, region recall) by "
                         "this factor; the guide-colour leak and plainness checks are never relaxed "
                         "(1.0 default, 0 disables the gate entirely)")
    p.add_argument("--force", action="store_true", help="redo existing outputs and cached prompts")
    p.add_argument("--dry-run", action="store_true", help="list what would be processed; no API calls")
    p.add_argument("--screens", action=argparse.BooleanOptionalAction, default=True,
                    help="also regenerate the ITD_RESS full-screen resources (default on)")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    cams = discover(args.in_dir, set(parse_floors(args.floors)), screens=args.screens)
    if not cams:
        # discover() looks under both backgrounds/ and (unless --no-screens)
        # screens/; naming only backgrounds/ here was misleading once a
        # directory with screens but no cameras became a legitimate input.
        print(f"nothing to regenerate under {args.in_dir}: no backgrounds/ cameras"
              + ("" if not args.screens else " and no screens/ plates"), file=sys.stderr)
        return 2

    done, failed = regenerate(cams, args.out, text_model=args.text_model, style=args.style,
                              attempts=args.attempts, gate_scale=args.gate_scale,
                              force=args.force, dry_run=args.dry_run)
    print(f"done {done}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
