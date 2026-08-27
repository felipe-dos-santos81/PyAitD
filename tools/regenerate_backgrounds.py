# SPDX-License-Identifier: GPL-2.0-only
"""Regenerate exported backgrounds with Gemini: describe each plate with a
text model, render the description with an image model using the original
and its guide as references, fit to 1280x800 and write an override dir.

docs/superpowers/specs/2026-08-25-gemini-background-regeneration-design.md."""
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
from tools.plate_check import fmt_bbox, layout_regions  # noqa: E402

DEFAULT_TEXT_MODEL = "gemini-3.1-pro"
DEFAULT_STYLE = "Dark 1920s Louisiana mansion, moody film lighting, subtle grain."
TARGET_SIZE = (1280, 800)   # 4 x 320x200
GENERATE_ASPECT = "3:2"     # nearest Gemini ratio to 16:10 (3:2 is narrower); extra height is centre-cropped after
PROMPTS_FILE = "prompts.json"
MAX_CONSECUTIVE_FAILURES = 3   # a dead model/key fails every camera: stop early
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
    `floors` (None = all); then every IN/screens/ressNN.png (floor -1,
    camera = entry) when `screens`. Guide and layout-sidecar paths only
    when the files exist."""
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


def agy_structured(model, instructions, schema):
    """One agy call with an enforced JSON schema; returns structured_output."""
    cmd = ["agy", "-p", instructions, "--dangerously-skip-permissions", "--effort", "low",
           "--model", model, "--output-format", "json", "--json-schema", json.dumps(schema)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
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


def temp_png():
    """An empty temp file with a .png suffix; the caller unlinks it."""
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    return pathlib.Path(path)


def make_reference(cam):
    """The original upscaled 4x (nearest) as a temp PNG: the first reference
    image of every generate call, at the guide's scale. Caller unlinks on
    success; a failure partway through here unlinks its own partial file."""
    from PyAitD.render.asset_resolver import load_png_rgb
    from PyAitD.render.background_export import nearest_upscale
    path = temp_png()
    try:
        save_png(path, nearest_upscale(load_png_rgb(cam.source), 4))
    except BaseException:
        path.unlink(missing_ok=True)
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
    (references, aspect, name, prompt) and read the copied result."""
    paths = ", ".join(f'"{pathlib.Path(p).absolute()}"' for p in attached)
    instructions = (
        f"Call the generate_image tool exactly once with these arguments: ImagePaths = [{paths}]; "
        f'AspectRatio = "{GENERATE_ASPECT}"; ImageName = "{image_name(cam)}"; Prompt = the text between '
        f"the markers below. Then copy the generated image file to exactly this path: {out_path}. "
        f"Output ONLY the word SUCCESS.\n---PROMPT---\n{prompt}\n---END---")
    cmd = ["agy", "-p", instructions, "--dangerously-skip-permissions", "--effort", "low", "--model", model]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    out_path = pathlib.Path(out_path)
    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise RuntimeError("no image generated or copied by agent")
    return out_path.read_bytes()


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


def regenerate(cams, out_dir, *, text_model, style, force, dry_run, log=print):
    """Describe + generate every camera into out_dir. Returns (done, failed).
    Existing outputs are skipped unless force; cached inventories are reused
    unless force or the source sha changed; prompts.json is saved after every camera."""
    out_dir = pathlib.Path(out_dir)
    prompts_path = out_dir / PROMPTS_FILE
    prompts = load_prompts(prompts_path)
    done = failed = streak = 0
    for cam in cams:
        target = out_dir / (f"backgrounds/{cam.key}.png" if cam.floor >= 0 else f"{cam.key}.png")
        if target.is_file() and not force:
            log(f"{cam.key}: exists, skipped")
            continue
        guide = "yes" if cam.guide is not None else "no"
        cached = "yes" if cam.key in prompts and "inventory" in prompts[cam.key] else "no"
        if dry_run:
            log(f"{cam.key}: would regenerate (guide {guide}, prompt cached {cached})")
            continue
        try:
            source_sha = hashlib.sha256(cam.source.read_bytes()).hexdigest()
            entry = prompts.get(cam.key)
            stale = entry is None or "inventory" not in entry or entry.get("sha256") != source_sha
            if stale or force:
                inventory = describe(text_model, cam)
                prompts[cam.key] = {"inventory": inventory, "model": text_model, "sha256": source_sha}
                save_prompts(prompts_path, prompts)
            inventory = prompts[cam.key]["inventory"]
            layout = json.loads(cam.layout.read_text()) if cam.layout else None
            ref = make_reference(cam)
            try:
                attached = attachments(cam, ref, leaked=False)
                prompt = generation_prompt(inventory, style, layout_regions(layout),
                                           guide_attached=len(attached) > 1, screen=cam.floor == -1)
                out = temp_png()
                try:
                    image = generate(text_model, cam, prompt, attached, out)
                finally:
                    out.unlink(missing_ok=True)
            finally:
                ref.unlink(missing_ok=True)
            save_png(target, fit_to_target(image))
        except Exception as exc:  # per-camera: SDK error types are not imported here
            failed += 1
            streak += 1
            log(f"{cam.key}: failed: {exc}")
            if streak >= MAX_CONSECUTIVE_FAILURES:
                log(f"aborting after {streak} consecutive failures")
                break
            continue
        done += 1
        streak = 0
        log(f"{cam.key}: ok (guide {guide}, prompt cached {cached})")
    if not dry_run:
        _copy_manifest(cams, out_dir)
    return done, failed


def _parse_args(argv):
    p = argparse.ArgumentParser(description="Regenerate exported backgrounds with Gemini.")
    p.add_argument("in_dir", help="override dir from `make export-backgrounds` (originals + guides)")
    p.add_argument("--out", required=True, help="output override dir (same layout)")
    p.add_argument("--floors", default="0-7")
    p.add_argument("--style", default=DEFAULT_STYLE)
    p.add_argument("--text-model", default=DEFAULT_TEXT_MODEL)
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
                              force=args.force, dry_run=args.dry_run)
    print(f"done {done}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
