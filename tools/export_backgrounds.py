# SPDX-License-Identifier: GPL-2.0-only
"""Export every camera background for external (AI) regeneration.

Writes, under --out DIR:

    manifest.json
    backgrounds/floorNN/cameraNNN.png   320x200 originals -- overwrite these in place
    guides/floorNN/cameraNNN.png        upscaled originals with masks (red),
                                        collision (blue) and walkable (green) drawn on
    screens/ressNN.png                  320x200 ITD_RESS full-screen originals
    guides/screens/ressNN.png           upscaled originals with the engine's
                                        blit rects drawn on (blue)

DIR is directly usable as `--overrides DIR` / `make run overrides=DIR`.
See docs/ai-background-regeneration.md. This repo never ships game data:
never commit the output.
"""
import argparse
import json
import os
import pathlib
import sys

import numpy as np

from PyAitD.render.background_export import (
    SCREEN_ENTRIES, SUPPORTED_SCHEMAS, background_rel_path, export_manifest, guide_overlay, guide_rel_path,
    manifest_record, screen_guide, screen_guide_rel_path, screen_record, screen_rel_path,
)
from PyAitD.engine.assets import Assets
from PyAitD.engine.floor import Floor
from PyAitD.engine.pak import PakError
from PyAitD.games import load_profile


def load_floor(data_dir, number):
    return Floor(data_dir, number)


def load_assets(data_dir):
    return Assets(data_dir, load_profile("aitd1"))


def parse_floors(text):
    out = []
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return out


def save_png(path, rgb):
    """Encode via pygame to `<path>.tmp` (PNG format forced by namehint --
    pygame.image.save only honours namehint for a file object, not a string
    path, so the temp file is opened explicitly), then atomically rename, so
    an interrupted run never leaves a truncated PNG that AssetResolver would
    reject."""
    import pygame
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    surface = pygame.surfarray.make_surface(np.ascontiguousarray(rgb.swapaxes(0, 1)))
    with open(tmp, "wb") as f:
        pygame.image.save(surface, f, "png")
    os.replace(tmp, path)


def _merge_manifest_records(out_dir, new_records, key="cameras"):
    """Merge `new_records` over out_dir/manifest.json's existing `key` list
    (cameras keyed by (floor, camera), screens by entry), new records
    winning, so a --force re-export of a subset does not lose the rest.
    Falls back to `new_records` alone when there is no readable,
    schema-supported manifest to merge onto."""
    def ident(rec):
        return rec["entry"] if key == "screens" else (rec["floor"], rec["camera"])
    manifest_path = pathlib.Path(out_dir) / "manifest.json"
    if not manifest_path.is_file():
        return list(new_records)
    try:
        existing = json.loads(manifest_path.read_text())
    except (OSError, ValueError):
        return list(new_records)
    if not isinstance(existing, dict) or existing.get("schema") not in SUPPORTED_SCHEMAS:
        return list(new_records)
    merged = {ident(c): c for c in existing.get(key, [])}
    for rec in new_records:
        merged[ident(rec)] = rec
    return list(merged.values())


def save_manifest(out_dir, manifest):
    """Write manifest.json via `.tmp` + os.replace, like save_png, so an
    interrupted run never leaves a truncated manifest.json behind."""
    path = pathlib.Path(out_dir) / "manifest.json"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=1))
    os.replace(tmp, path)
    return path


def export_floor(floor, out_dir, guide_scale, save=save_png):
    out_dir = pathlib.Path(out_dir)
    records = []
    for cam_idx in range(len(floor.cameras)):
        try:
            pixels = floor.camera_image(cam_idx)
        except KeyError:
            records.append(manifest_record(floor, cam_idx, None))
            continue
        save(out_dir / background_rel_path(floor.number, cam_idx), pixels)
        save(out_dir / guide_rel_path(floor.number, cam_idx), guide_overlay(floor, cam_idx, guide_scale))
        records.append(manifest_record(floor, cam_idx, pixels))
    return records


def export_screens(assets, out_dir, guide_scale, save=save_png):
    out_dir = pathlib.Path(out_dir)
    records = []
    for entry in SCREEN_ENTRIES:
        pixels = assets.resource_screen(entry)
        save(out_dir / screen_rel_path(entry), pixels)
        save(out_dir / screen_guide_rel_path(entry), screen_guide(pixels, entry, guide_scale))
        records.append(screen_record(entry, pixels))
    return records


def _parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("data", type=pathlib.Path, help="game data directory (e.g. .../INDARK)")
    p.add_argument("--out", type=pathlib.Path, required=True, help="override directory to create")
    p.add_argument("--floors", default="0-7", help="floors to export, e.g. 0-7 or 0,3,5 (default 0-7)")
    p.add_argument("--guide-scale", type=int, default=4, help="guide image scale (default 4)")
    p.add_argument("--screens", action=argparse.BooleanOptionalAction, default=True,
                    help="also export the ITD_RESS full-screen resources (default on)")
    p.add_argument("--force", action="store_true",
                    help="re-export even if --out already holds backgrounds/ (overwrites regenerated files)")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    if not args.data.is_dir():
        print(f"error: game data directory not found: {args.data}", file=sys.stderr)
        return 2
    if args.guide_scale < 1:
        print("error: --guide-scale must be >= 1", file=sys.stderr)
        return 2
    try:
        floors = parse_floors(args.floors)
    except ValueError:
        print(f"error: bad --floors {args.floors!r}", file=sys.stderr)
        return 2
    for sub in ("backgrounds", "screens"):
        if (args.out / sub).exists() and not args.force:
            print(f"error: {args.out / sub} exists; pass --force to overwrite "
                  "(this discards regenerated images)", file=sys.stderr)
            return 3

    records, exported = [], 0
    for number in floors:
        try:
            floor = load_floor(args.data, number)
        except (PakError, FileNotFoundError, OSError, ValueError) as exc:
            print(f"warning: floor {number:02d} skipped: {exc}", file=sys.stderr)
            continue
        records.extend(export_floor(floor, args.out, args.guide_scale))
        exported += 1
        print(f"floor {number:02d}: {len(floor.cameras)} cameras")

    screens = []
    if args.screens:
        try:
            screens = export_screens(load_assets(args.data), args.out, args.guide_scale)
            print(f"screens: {len(screens)}")
        except (PakError, FileNotFoundError, OSError, ValueError) as exc:
            print(f"warning: screens skipped: {exc}", file=sys.stderr)
    if not exported and not screens:
        print("error: nothing exported", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    records = _merge_manifest_records(args.out, records)
    screens = _merge_manifest_records(args.out, screens, key="screens")
    manifest = export_manifest(records, args.data.resolve(), args.guide_scale, screens=screens)
    print(save_manifest(args.out, manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
