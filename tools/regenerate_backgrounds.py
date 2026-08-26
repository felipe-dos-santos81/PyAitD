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

DEFAULT_TEXT_MODEL = "gemini-3.1-pro"
DEFAULT_IMAGE_MODEL = "gemini-3-pro-image"
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


def discover(in_dir, floors, screens=True):
    """Every IN/backgrounds/floorNN/cameraNNN.png, sorted, restricted to
    `floors` (None = all); then every IN/screens/ressNN.png (floor -1,
    camera = entry) when `screens`. Guide path only when the file exists."""
    in_dir = pathlib.Path(in_dir)
    cams = []
    for path in sorted((in_dir / "backgrounds").glob("floor[0-9][0-9]/camera[0-9][0-9][0-9].png")):
        m = _CAMERA_RE.search(path.as_posix())
        floor, cam = int(m.group(1)), int(m.group(2))
        if floors is not None and floor not in floors:
            continue
        key = f"floor{floor:02d}/camera{cam:03d}"
        guide = in_dir / "guides" / f"{key}.png"
        cams.append(Camera(floor, cam, path, guide if guide.is_file() else None, key))
    if screens:
        for path in sorted((in_dir / "screens").glob("ress[0-9][0-9].png")):
            entry = int(_SCREEN_RE.search(path.as_posix()).group(1))
            key = f"screens/ress{entry:02d}"
            guide = in_dir / "guides" / f"{key}.png"
            cams.append(Camera(-1, entry, path, guide if guide.is_file() else None, key))
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


def describe_prompt(guide_present, screen=False):
    text = ("Describe this 320x200 pixel-art background from a 1992 adventure game as a "
            "single-paragraph prompt for a photorealistic image generator. Name the room type, "
            "the camera angle and height, every piece of furniture and architecture with its "
            "position in frame, the light sources and their direction, materials and colours, "
            "and the mood. Do not mention pixel art, the game, or resolution. Output only the prompt.")
    if not guide_present:
        return text
    return text + " " + (_SCREEN_DESCRIBE if screen else _GUIDE_DESCRIBE)


def generation_prompt(description, style, guide_present, screen=False):
    if screen:
        text = ("Recreate the first image as a painted illustration of the same composition, "
                "keeping the framing and every element's placement. ")
    else:
        text = ("Recreate the first image as a photorealistic photograph of the same scene, keeping "
                "the exact camera position, framing, perspective and the placement of every wall, "
                "door, window, stair and piece of furniture. ")
    if guide_present:
        text += (_SCREEN_GENERATE if screen else _GUIDE_GENERATE) + " "
    return text + description.strip() + " " + style


def load_prompts(path):
    path = pathlib.Path(path)
    return json.loads(path.read_text()) if path.is_file() else {}


def save_prompts(path, prompts):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(prompts, indent=1, sort_keys=True))
    os.replace(tmp, path)


def describe(model, cam):
    """One text-model call via agy CLI: original (+ guide) -> scene prompt."""
    prompt = describe_prompt(cam.guide is not None, screen=cam.floor == -1)
    instructions = f"Look at the image at {cam.source.absolute()}. "
    if cam.guide:
        instructions += f"Also look at the guide image at {cam.guide.absolute()}. "
    instructions += f"Then output ONLY the prompt: {prompt}"
    
    cmd = [
        "agy", "-p", instructions,
        "--dangerously-skip-permissions",
        "--effort", "low",
        "--model", model
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    text = result.stdout.strip()
    if not text:
        raise RuntimeError("empty description from text model")
    return text


def generate(model, cam, prompt):
    """One image-model call via agy CLI: original (+ guide) + prompt -> image bytes."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name
        
    instructions = f"Look at the image at {cam.source.absolute()}. "
    if cam.guide:
        instructions += f"Also look at the guide image at {cam.guide.absolute()}. "
    instructions += (f"Use the generate_image tool to recreate the first image based on "
                     f"this prompt: {prompt} "
                     f"Once you generate the image, copy the resulting image artifact to exactly "
                     f"this path: {tmp_path}. Then output ONLY 'SUCCESS'.")
    
    cmd = [
        "agy", "-p", instructions,
        "--dangerously-skip-permissions",
        "--effort", "low",
        "--model", model
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    
    with open(tmp_path, "rb") as f:
        image_bytes = f.read()
    os.remove(tmp_path)
    
    if not image_bytes:
        raise RuntimeError("no image generated or copied by agent")
    return image_bytes


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


def regenerate(cams, out_dir, *, text_model, image_model, style, force, dry_run, log=print):
    """Describe + generate every camera into out_dir. Returns (done, failed).
    Existing outputs are skipped unless force; cached prompts are reused
    unless force; prompts.json is saved after every camera."""
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
        cached = "yes" if cam.key in prompts else "no"
        if dry_run:
            log(f"{cam.key}: would regenerate (guide {guide}, prompt cached {cached})")
            continue
        try:
            source_sha = hashlib.sha256(cam.source.read_bytes()).hexdigest()
            stale = cam.key in prompts and prompts[cam.key].get("sha256") != source_sha
            if cam.key not in prompts or force or stale:
                text = describe(text_model, cam)
                prompts[cam.key] = {"prompt": text, "model": text_model, "sha256": source_sha}
                save_prompts(prompts_path, prompts)
            prompt = generation_prompt(prompts[cam.key]["prompt"], style, cam.guide is not None,
                                       screen=cam.floor == -1)
            image = generate(text_model, cam, prompt)
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
    p.add_argument("--image-model", default=DEFAULT_IMAGE_MODEL)
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
    
    done, failed = regenerate(cams, args.out, text_model=args.text_model,
                              image_model=args.image_model, style=args.style,
                              force=args.force, dry_run=args.dry_run)
    print(f"done {done}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
