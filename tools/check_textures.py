# SPDX-License-Identifier: GPL-2.0-only
"""Check a texture directory the way the game loads it.

    check_textures.py DATA DIR [--floors 0-7] [--proof OUT]

Prints one line per invalid/aspect/size finding and a per-floor coverage
summary (when DIR/manifest.json exists). Exit 1 on any `invalid` or
`aspect` finding -- those would be silently ignored or stretched in-game.
--proof renders original|texture side by side through the GL backend at
scale 4 to OUT (default docs/graphics-proof/textures/, git-ignored).
"""
import argparse
import json
import pathlib
import sys

import numpy as np

from PyAitD.render.asset_resolver import AssetResolver, texture_alt_background_path
from PyAitD.render.texture_export import SCREEN_ENTRIES, SUPPORTED_SCHEMAS
from PyAitD.render.texture_check import (
    alt_coverage, check_alt_backgrounds, check_bodies, check_body_textures, check_screens, check_textures, coverage,
    has_errors, screen_coverage, summarize,
)
from PyAitD.engine.data.pak import PakError
from PyAitD.render.render_gl import GLBackend
from PyAitD.render.render_options import RenderOptions
from PyAitD.render.scene import CameraView, FrameDescription
from PyAitD.engine.space.world import CameraState
# Run as a script (`python tools/check_textures.py`), sys.path[0] is tools/,
# not the repo root, so the sibling module is only reachable through the
# package when the root is added explicitly.
if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from tools.export_textures import PROFILE, load_assets, load_floor, parse_floors, save_png  # noqa: E402

DEFAULT_PROOF_DIR = pathlib.Path("docs/graphics-proof/textures")


def create_context():
    import moderngl
    return moderngl.create_standalone_context(require=330)


def _plate(ctx, floor, cam_idx, asset, scale):
    room = floor.rooms[floor.cameras[cam_idx].viewed_rooms[0].viewed_room_idx]
    state = CameraState.from_camera(floor.cameras[cam_idx], room.world_x, room.world_y, room.world_z).angles()
    frame = FrameDescription(CameraView(state), asset, floor.palette, (), ())
    backend = GLBackend(ctx, RenderOptions(scale=scale))
    try:
        backend.draw(frame)
        return backend.read_rgb()
    finally:
        backend.release()


def render_proof(ctx, floor, cam_idx, texture_dir, out_dir, scale=4, save=save_png, *, killed_sorcerer=False):
    """original | texture for one camera, or None if no loadable texture.

    When `killed_sorcerer` is True, the alt_backgrounds path is checked via
    `resolver.background(..., killed_sorcerer=True)` and the output filename
    is suffixed with ``-alt`` to avoid colliding with the base proof."""
    resolver = AssetResolver(None, texture_dir)
    override = resolver.background(floor, cam_idx, killed_sorcerer=killed_sorcerer)
    if not override.is_override:
        return None
    if killed_sorcerer:
        alt_path = texture_alt_background_path(texture_dir, floor.number, cam_idx)
        if alt_path in resolver.failures or not alt_path.is_file():
            return None
    original = AssetResolver(None, None).background(floor, cam_idx)
    left = _plate(ctx, floor, cam_idx, original, scale)
    right = _plate(ctx, floor, cam_idx, override, scale)
    suffix = "-alt" if killed_sorcerer else ""
    path = pathlib.Path(out_dir) / f"floor{floor.number:02d}-camera{cam_idx:03d}{suffix}.png"
    save(path, np.concatenate([left, right], axis=1))
    return path


def render_screen_proof(assets, entry, texture_dir, out_dir, save=save_png):
    """original | texture for one screen, both fitted to 320x200 x4 by
    nearest repeat (no GL needed)."""
    from PyAitD.render.texture_export import nearest_upscale
    resolver = AssetResolver(assets, texture_dir)
    override = resolver.resource_screen(entry)
    if not override.is_override:
        return None
    left = nearest_upscale(assets.resource_screen(entry), 4)
    right = override.pixels
    if right.shape[:2] != left.shape[:2]:
        import pygame
        surface = pygame.surfarray.make_surface(np.ascontiguousarray(right.swapaxes(0, 1)))
        surface = pygame.transform.smoothscale(surface, (left.shape[1], left.shape[0]))
        right = np.ascontiguousarray(pygame.surfarray.array3d(surface).swapaxes(0, 1))
    path = pathlib.Path(out_dir) / f"screen-ress{entry:02d}.png"
    save(path, np.concatenate([left, right], axis=1))
    return path


def _parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("data", type=pathlib.Path)
    p.add_argument("textures", type=pathlib.Path)
    p.add_argument("--floors", default="0-7")
    p.add_argument("--proof", type=pathlib.Path, nargs="?", const=DEFAULT_PROOF_DIR, default=None,
                    help=f"render original|texture proofs to this directory (default {DEFAULT_PROOF_DIR})")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    if not args.data.is_dir():
        print(f"error: game data directory not found: {args.data}", file=sys.stderr)
        return 2
    if not args.textures.is_dir():
        print(f"error: texture directory not found: {args.textures}", file=sys.stderr)
        return 2
    try:
        numbers = parse_floors(args.floors)
    except ValueError:
        print(f"error: bad --floors {args.floors!r}", file=sys.stderr)
        return 2
    manifest = None
    manifest_path = args.textures / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, ValueError) as exc:
            print(f"error: unreadable manifest {manifest_path}: {exc}", file=sys.stderr)
            return 2
        if (not isinstance(manifest, dict) or manifest.get("schema") not in SUPPORTED_SCHEMAS
                or not isinstance(manifest.get("cameras"), list)):
            print(f"error: unreadable manifest {manifest_path}: unsupported schema/shape", file=sys.stderr)
            return 2

    floors = []
    for number in numbers:
        try:
            floors.append(load_floor(args.data, number))
        except (PakError, FileNotFoundError, OSError, ValueError) as exc:
            print(f"warning: floor {number:02d} skipped: {exc}", file=sys.stderr)

    assets = None
    try:
        assets = load_assets(args.data)
    except (PakError, FileNotFoundError, OSError, ValueError) as exc:
        print(f"warning: screens skipped: {exc}", file=sys.stderr)

    findings = check_textures(args.textures, floors, manifest)
    findings = findings + check_alt_backgrounds(args.textures, floors, manifest)
    findings = findings + check_bodies(args.textures)
    findings = findings + check_body_textures(args.textures, args.data, PROFILE)
    cov = coverage(args.textures, floors, manifest) if manifest is not None else None
    alt_cov = alt_coverage(args.textures, floors, manifest) if manifest is not None else None
    screen_cov = None
    if assets is not None:
        findings = findings + check_screens(args.textures, assets)
        if manifest is not None:
            screen_cov = screen_coverage(args.textures, assets, manifest)
    print(summarize(findings, cov, screen_cov, alt_cov))

    if args.proof is not None:
        if assets is not None:
            for entry in SCREEN_ENTRIES:
                path = render_screen_proof(assets, entry, args.textures, args.proof)
                if path is not None:
                    print(path)
        try:
            ctx = create_context()
        except Exception as exc:
            print(f"proof skipped: no standalone GL 3.3 context: {exc}", file=sys.stderr)
        else:
            try:
                for floor in floors:
                    for cam_idx in range(len(floor.cameras)):
                        path = render_proof(ctx, floor, cam_idx, args.textures, args.proof)
                        if path is not None:
                            print(path)
                # alt_backgrounds proofs via killed_sorcerer flag
                alt_tuples = []
                if manifest is not None and manifest.get("alt_cameras"):
                    alt_tuples = [(c["floor"], c["camera"]) for c in manifest["alt_cameras"]]
                else:
                    # fallback to profile when no manifest alt_cameras (e.g. old schema or --proof without manifest)
                    try:
                        from PyAitD.games import load_profile
                        alt_tuples = list(load_profile("aitd1").alt_camera_sources.keys())
                    except Exception:
                        alt_tuples = []
                floor_by_number = {f.number: f for f in floors}
                for fnum, cidx in alt_tuples:
                    floor = floor_by_number.get(fnum)
                    if floor is None or cidx >= len(floor.cameras):
                        continue
                    path = render_proof(ctx, floor, cidx, args.textures, args.proof, killed_sorcerer=True)
                    if path is not None:
                        print(path)
            finally:
                ctx.release()
    return 1 if has_errors(findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
