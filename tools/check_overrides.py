# SPDX-License-Identifier: GPL-2.0-only
"""Check an override directory the way the game loads it.

    check_overrides.py DATA DIR [--floors 0-7] [--proof OUT]

Prints one line per invalid/aspect/size finding and a per-floor coverage
summary (when DIR/manifest.json exists). Exit 1 on any `invalid` or
`aspect` finding -- those would be silently ignored or stretched in-game.
--proof renders original|override side by side through the GL backend at
scale 4 to OUT (default docs/graphics-proof/overrides/, git-ignored).
"""
import argparse
import json
import pathlib
import sys

import numpy as np

from PyAitD.asset_resolver import AssetResolver
from PyAitD.background_export import MANIFEST_SCHEMA
from PyAitD.override_check import check_overrides, coverage, has_errors, summarize
from PyAitD.pak import PakError
from PyAitD.render_gl import GLBackend
from PyAitD.render_options import RenderOptions
from PyAitD.scene import CameraView, FrameDescription
from PyAitD.world import CameraState
# Run as a script (`python tools/check_overrides.py`), sys.path[0] is tools/,
# not the repo root, so the sibling module is only reachable through the
# package when the root is added explicitly.
if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from tools.export_backgrounds import load_floor, parse_floors, save_png  # noqa: E402

DEFAULT_PROOF_DIR = pathlib.Path("docs/graphics-proof/overrides")


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


def render_proof(ctx, floor, cam_idx, override_dir, out_dir, scale=4, save=save_png):
    """original | override for one camera, or None if no loadable override."""
    resolver = AssetResolver(None, override_dir)
    override = resolver.background(floor, cam_idx)
    if not override.is_override:
        return None
    original = AssetResolver(None, None).background(floor, cam_idx)
    left = _plate(ctx, floor, cam_idx, original, scale)
    right = _plate(ctx, floor, cam_idx, override, scale)
    path = pathlib.Path(out_dir) / f"floor{floor.number:02d}-camera{cam_idx:03d}.png"
    save(path, np.concatenate([left, right], axis=1))
    return path


def _parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("data", type=pathlib.Path)
    p.add_argument("overrides", type=pathlib.Path)
    p.add_argument("--floors", default="0-7")
    p.add_argument("--proof", type=pathlib.Path, nargs="?", const=DEFAULT_PROOF_DIR, default=None,
                    help=f"render original|override proofs to this directory (default {DEFAULT_PROOF_DIR})")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    if not args.data.is_dir():
        print(f"error: game data directory not found: {args.data}", file=sys.stderr)
        return 2
    if not args.overrides.is_dir():
        print(f"error: override directory not found: {args.overrides}", file=sys.stderr)
        return 2
    try:
        numbers = parse_floors(args.floors)
    except ValueError:
        print(f"error: bad --floors {args.floors!r}", file=sys.stderr)
        return 2
    manifest = None
    manifest_path = args.overrides / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, ValueError) as exc:
            print(f"error: unreadable manifest {manifest_path}: {exc}", file=sys.stderr)
            return 2
        if (not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA
                or not isinstance(manifest.get("cameras"), list)):
            print(f"error: unreadable manifest {manifest_path}: unsupported schema/shape", file=sys.stderr)
            return 2

    floors = []
    for number in numbers:
        try:
            floors.append(load_floor(args.data, number))
        except (PakError, FileNotFoundError, OSError, ValueError) as exc:
            print(f"warning: floor {number:02d} skipped: {exc}", file=sys.stderr)

    findings = check_overrides(args.overrides, floors, manifest)
    cov = coverage(args.overrides, floors, manifest) if manifest is not None else None
    print(summarize(findings, cov))

    if args.proof is not None:
        try:
            ctx = create_context()
        except Exception as exc:
            print(f"proof skipped: no standalone GL 3.3 context: {exc}", file=sys.stderr)
        else:
            try:
                for floor in floors:
                    for cam_idx in range(len(floor.cameras)):
                        path = render_proof(ctx, floor, cam_idx, args.overrides, args.proof)
                        if path is not None:
                            print(path)
            finally:
                ctx.release()
    return 1 if has_errors(findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
