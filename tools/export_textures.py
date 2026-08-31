# SPDX-License-Identifier: GPL-2.0-only
"""Export every camera background for the external texture tool.

Writes, under --out DIR:

    manifest.json
    backgrounds/floorNN/cameraNNN.png   320x200 originals -- overwrite these in place
    guides/floorNN/cameraNNN.png        upscaled originals with masks (red),
                                        collision (blue) and walkable (green) drawn on
    guides/floorNN/cameraNNN.json       the same structures as JSON (320x200 px)
    screens/ressNN.png                  320x200 ITD_RESS full-screen originals
    guides/screens/ressNN.png           upscaled originals with the engine's
                                        blit rects drawn on (blue)
    guides/screens/ressNN.json          the blit rects as JSON

DIR is directly usable as `--textures DIR` / `make run textures=DIR`.
This repo never ships game data: never commit the output.
"""
import argparse
import json
import os
import pathlib
import sys

import numpy as np

from PyAitD.render.texture_export import (
    SCREEN_ENTRIES, SCREEN_NAMES, SUPPORTED_SCHEMAS, alt_background_rel_path, alt_manifest_record,
    background_rel_path, export_manifest, guide_overlay, guide_rel_path, layout_geometry, layout_rel_path,
    manifest_record, screen_guide, screen_guide_rel_path, screen_layout, screen_layout_rel_path,
    screen_record, screen_rel_path,
)
from PyAitD.engine.data.assets import Assets
from PyAitD.engine.data.floor import Floor, load_entry
from PyAitD.engine.data.formats import SCREEN_PIXELS, decode_image
from PyAitD.engine.data.pak import PakError, find_pak
from PyAitD.games import load_profile
from PyAitD.render.asset_resolver import texture_palette_path


# This tool exports AITD1 data and has no Game to take a profile from, so it
# resolves the profile itself -- the one place the game id is named here.
PROFILE = load_profile("aitd1")


def load_floor(data_dir, number):
    return Floor(data_dir, number, PROFILE)


def load_assets(data_dir):
    return Assets(data_dir, PROFILE)


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


def save_layout(path, layout):
    """Write a layout sidecar via `.tmp` + os.replace, like save_manifest."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(layout))
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


def export_floor(floor, out_dir, guide_scale, save=save_png, save_layout=save_layout):
    out_dir = pathlib.Path(out_dir)
    records = []
    for cam_idx in range(len(floor.cameras)):
        try:
            pixels = floor.camera_image(cam_idx)
        except KeyError:
            records.append(manifest_record(floor, cam_idx, None))
            continue
        layout = layout_geometry(floor, cam_idx)
        save(out_dir / background_rel_path(floor.number, cam_idx), pixels)
        save(out_dir / guide_rel_path(floor.number, cam_idx), guide_overlay(floor, cam_idx, guide_scale, layout=layout))
        save_layout(out_dir / layout_rel_path(floor.number, cam_idx), layout)
        records.append(manifest_record(floor, cam_idx, pixels))
    return records


def export_screens(assets, out_dir, guide_scale, save=save_png, save_layout=save_layout):
    # Per-entry, like export_floor's per-camera loop: one damaged ITD_RESS
    # entry must not discard the records for entries already written to
    # disk earlier in the loop (a whole-loop try/except did exactly that).
    out_dir = pathlib.Path(out_dir)
    records = []
    for entry in SCREEN_ENTRIES:
        try:
            pixels = assets.resource_screen(entry)
            save(out_dir / screen_rel_path(entry), pixels)
            save(out_dir / screen_guide_rel_path(entry), screen_guide(pixels, entry, guide_scale))
            save_layout(out_dir / screen_layout_rel_path(entry), screen_layout(entry))
            records.append(screen_record(entry, pixels))
        except (PakError, FileNotFoundError, OSError, ValueError) as exc:
            print(f"warning: screen {entry} ({SCREEN_NAMES[entry]}) skipped: {exc}", file=sys.stderr)
    return records


def export_alt_backgrounds(data_dir, out_dir, guide_scale=4, save=save_png, save_layout=save_layout, floors=None):
    """Export the 5 KILLED_SORCERER road alt plates from ITD_RESS.

    Each entry is decoded via raw[:64000] + Floor(0).palette (same path as
    Assets.resource_screen) and written to alt_backgrounds/floorNN/cameraNNN.png
    with an alt_manifest_record. Guides/layouts are not duplicated -- the alt
    reuses the base guides/ for the same floor/camera. Failures warn and skip.
    When `floors` is not None, only alts whose floor is in that iterable are
    exported (mirrors main()'s --floors filter).
    """
    _ = (guide_scale, save_layout)  # shared guides; kept for caller symmetry
    out_dir = pathlib.Path(out_dir)
    alt_map = dict(PROFILE.alt_camera_sources)
    if not alt_map:
        return []
    if floors is not None:
        floor_set = set(floors)
        alt_map = {k: v for k, v in alt_map.items() if k[0] in floor_set}
        if not alt_map:
            return []
    # Palette for ITD_RESS decode -- same as Assets._game_palette (ITD_RESS:3)
    try:
        palette = load_floor(data_dir, 0).palette  # (256, 3) uint8
    except Exception as exc:
        print(f"warning: palette skipped, alts not exported: {exc}", file=sys.stderr)
        return []
    # Cache Floors per number
    floors_cache: dict[int, Floor] = {}
    records = []
    # Reuse find_pak lookup once
    try:
        itd_ress_pak = str(find_pak(data_dir, "ITD_RESS"))
    except Exception as exc:
        print(f"warning: ITD_RESS PAK not found, alts skipped: {exc}", file=sys.stderr)
        return []
    for (floor_num, cam_idx), entry in sorted(alt_map.items()):
        if floor_num not in floors_cache:
            try:
                floors_cache[floor_num] = load_floor(data_dir, floor_num)
            except Exception as exc:
                print(f"warning: floor {floor_num:02d} skipped: {exc}", file=sys.stderr)
                continue
        floor = floors_cache[floor_num]
        try:
            raw = load_entry(itd_ress_pak, entry)
            pixels = decode_image(raw[:SCREEN_PIXELS], palette)
        except Exception as exc:
            print(f"warning: alt floor {floor_num:02d} cam {cam_idx:03d} ITD_RESS:{entry} skipped: {exc}", file=sys.stderr)
            continue
        # no guide/layout write -- shared with base
        save(out_dir / alt_background_rel_path(floor_num, cam_idx), pixels)
        records.append(alt_manifest_record(floor, cam_idx, pixels, entry))
    return records


def export_palette(data_dir, out_dir, save=save_png):
    """Write palette.png (256x1 RGB) from Floor 0's palette, atomically via save_png.

    Returns True on success, False on failure (warns)."""
    assert pathlib.Path(out_dir) / "palette.png" == texture_palette_path(out_dir)
    try:
        palette = load_floor(data_dir, 0).palette  # (256, 3)
        row = palette[None, :, :].astype(np.uint8)  # (1, 256, 3)
        save(pathlib.Path(out_dir) / "palette.png", row)
        return True
    except Exception as exc:
        print(f"warning: palette skipped: {exc}", file=sys.stderr)
        return False


def _parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("data", type=pathlib.Path, help="game data directory (e.g. .../INDARK)")
    p.add_argument("--out", type=pathlib.Path, required=True, help="texture directory to create")
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
    subs = ("backgrounds", "screens") if args.screens else ("backgrounds",)
    for sub in subs:
        if (args.out / sub).exists() and not args.force:
            print(f"error: {args.out / sub} exists; pass --force to overwrite "
                  "(this discards regenerated images)", file=sys.stderr)
            return 3
    # alt_backgrounds exists check mirrors backgrounds/ (Task 4)
    alt_map = dict(PROFILE.alt_camera_sources)
    if alt_map and (args.out / "alt_backgrounds").exists() and not args.force:
        print(f"error: {args.out / 'alt_backgrounds'} exists; pass --force to overwrite "
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
    # alt_backgrounds: respect --floors filter, warn and continue on failure
    try:
        alt_records = export_alt_backgrounds(args.data, args.out, args.guide_scale, floors=floors)
        if alt_records:
            print(f"alt_backgrounds: {len(alt_records)}")
    except (PakError, FileNotFoundError, OSError, ValueError) as exc:
        print(f"warning: alt_backgrounds skipped: {exc}", file=sys.stderr)
        alt_records = []
    # palette.png: always attempt, warn on failure (never blocks)
    try:
        if export_palette(args.data, args.out):
            print("palette: 1")
    except Exception as exc:
        print(f"warning: palette skipped: {exc}", file=sys.stderr)
    if not exported and not screens and not alt_records:
        print("error: nothing exported", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    records = _merge_manifest_records(args.out, records)
    screens = _merge_manifest_records(args.out, screens, key="screens")
    alt_records = _merge_manifest_records(args.out, alt_records, key="alt_cameras")
    manifest = export_manifest(records, args.data.resolve(), args.guide_scale, screens=screens, alt_cameras=alt_records)
    print(save_manifest(args.out, manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
