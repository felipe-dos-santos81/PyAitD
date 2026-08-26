# SPDX-License-Identifier: GPL-2.0-only
"""Regenerate exported backgrounds with Gemini: describe each plate with a
text model, render the description with an image model using the original
and its guide as references, fit to 1280x800 and write an override dir.

google-genai is imported only in make_client(); everything else runs
without it so tests use a fake client. See
docs/superpowers/specs/2026-08-25-gemini-background-regeneration-design.md."""
import argparse
import dataclasses
import hashlib
import json
import os
import pathlib
import re
import shutil
import sys

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from tools.export_backgrounds import parse_floors, save_png  # noqa: E402

DEFAULT_TEXT_MODEL = "gemini-2.5-flash"
DEFAULT_IMAGE_MODEL = "gemini-2.5-flash-image"
DEFAULT_STYLE = "Dark 1920s Louisiana mansion, moody film lighting, subtle grain."
TARGET_SIZE = (1280, 800)   # 4 x 320x200
GENERATE_ASPECT = "3:2"     # nearest Gemini ratio wider than 16:10; cropped after
PROMPTS_FILE = "prompts.json"
_SDK_MISSING = 'google-genai is not installed: run .venv/bin/pip install -e ".[dev,ai]"'
_CAMERA_RE = re.compile(r"floor(\d\d)/camera(\d\d\d)\.png$")


@dataclasses.dataclass(frozen=True)
class Camera:
    floor: int
    camera: int
    source: pathlib.Path
    guide: pathlib.Path | None
    key: str


def discover(in_dir, floors):
    """Every IN/backgrounds/floorNN/cameraNNN.png, sorted, restricted to
    `floors` (None = all); guide path only when the file exists."""
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
    return cams


_GUIDE_DESCRIBE = ("The second image is the same frame with an overlay: red outlines mark "
                   "foreground objects that must stay in front, blue boxes mark walls and solid "
                   "furniture, green polygons mark walkable floor. Describe the scene so those "
                   "structures keep their places.")
_GUIDE_GENERATE = ("The second image marks the layout: red outlines are foreground objects, blue "
                   "boxes are walls and solid furniture, green polygons are walkable floor; keep "
                   "all of them where they are and do not draw the coloured lines.")


def describe_prompt(guide_present):
    text = ("Describe this 320x200 pixel-art background from a 1992 adventure game as a "
            "single-paragraph prompt for a photorealistic image generator. Name the room type, "
            "the camera angle and height, every piece of furniture and architecture with its "
            "position in frame, the light sources and their direction, materials and colours, "
            "and the mood. Do not mention pixel art, the game, or resolution. Output only the prompt.")
    return text + (" " + _GUIDE_DESCRIBE if guide_present else "")


def generation_prompt(description, style, guide_present):
    text = ("Recreate the first image as a photorealistic photograph of the same scene, keeping "
            "the exact camera position, framing, perspective and the placement of every wall, "
            "door, window, stair and piece of furniture. ")
    if guide_present:
        text += _GUIDE_GENERATE + " "
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


def image_part(path):
    return {"inline_data": {"mime_type": "image/png", "data": pathlib.Path(path).read_bytes()}}


def _reference_parts(cam):
    parts = [image_part(cam.source)]
    if cam.guide is not None:
        parts.append(image_part(cam.guide))
    return parts


def describe(client, model, cam):
    """One text-model call: original (+ guide) -> scene prompt."""
    contents = _reference_parts(cam) + [describe_prompt(cam.guide is not None)]
    response = client.models.generate_content(model=model, contents=contents)
    return (response.text or "").strip()


def generate(client, model, cam, prompt):
    """One image-model call: original (+ guide) + prompt -> image bytes.
    `prompt` is the full generation prompt (caller composes it)."""
    contents = _reference_parts(cam) + [prompt]
    config = {"response_modalities": ["IMAGE"], "image_config": {"aspect_ratio": GENERATE_ASPECT}}
    response = client.models.generate_content(model=model, contents=contents, config=config)
    for candidate in response.candidates or ():
        content = getattr(candidate, "content", None)
        if content is None:
            continue
        for part in getattr(content, "parts", None) or ():
            data = getattr(part, "inline_data", None)
            if data is not None and (data.mime_type or "").startswith("image/"):
                return data.data
    raise RuntimeError("no image in response")
