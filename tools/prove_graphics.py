# SPDX-License-Identifier: GPL-2.0-only
"""Render fixed fixtures through the enhanced pipeline for the manual proof.

Boots two fixtures on a standalone ModernGL context and writes one PNG per
fixture per shading mode to `--out` (default `docs/graphics-proof/`):

- `attic`: the M1/M2 attic debug start (`init_game`, floor 0).
- `combat`: the shared floor-5 debug venue (`scenario.enter_combat_venue`).

This repo never ships game data, so the PNGs are never committed --
`docs/graphics-proof/` keeps only a `.gitkeep`. See
`docs/enhanced-graphics-proof.md` for the manual attestation these renders
feed.
"""
import argparse
import pathlib
import sys

import numpy as np

from PyAitD.render.asset_resolver import AssetResolver
from PyAitD.engine.floor import Floor
from PyAitD.engine.game import init_game
from PyAitD.render.render_gl import GLBackend
from PyAitD.render.render_options import SHADING_MODES, RenderOptions
from PyAitD.scenario import enter_combat_venue
from PyAitD.render.scene import build_frame

FIXTURES = ("attic", "combat")


def _boot(data_dir, name):
    game = init_game(data_dir)
    if name == "combat":
        enter_combat_venue(game)
    game.num_camera = game.new_num_camera
    return game, Floor(data_dir, game.current_floor)


def render_fixture(data_dir, name, scale, shading, ctx):
    game, floor = _boot(data_dir, name)
    frame, _ = build_frame(game, floor, AssetResolver(game.assets))
    backend = GLBackend(ctx, RenderOptions(scale=scale, shading=shading))
    try:
        backend.draw(frame)
        return backend.read_rgb()
    finally:
        backend.release()


def output_paths(out_dir):
    """(name, mode, path) for every fixture x shading-mode combination, in
    the order rendered and printed by `main`."""
    out_dir = pathlib.Path(out_dir)
    return [
        (name, mode, out_dir / f"{name}-{mode}.png")
        for name in FIXTURES
        for mode in SHADING_MODES
    ]


def _parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("data", type=pathlib.Path, help="game data directory (e.g. .../INDARK)")
    p.add_argument("--out", type=pathlib.Path, default=pathlib.Path("docs/graphics-proof"),
                    help="output directory for the rendered PNGs")
    p.add_argument("--scale", type=int, default=4, help="internal render scale (default 4)")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)

    if not args.data.is_dir():
        print(f"error: game data directory not found: {args.data}", file=sys.stderr)
        return 2

    import moderngl
    import pygame
    try:
        ctx = moderngl.create_standalone_context(require=330)
    except Exception as exc:
        print(f"error: no standalone GL 3.3 context: {exc}", file=sys.stderr)
        return 3

    try:
        args.out.mkdir(parents=True, exist_ok=True)
        for name, mode, path in output_paths(args.out):
            rgb = render_fixture(args.data, name, args.scale, mode, ctx)
            surface = pygame.surfarray.make_surface(np.ascontiguousarray(rgb.swapaxes(0, 1)))
            pygame.image.save(surface, str(path))
            print(path)
    finally:
        ctx.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
