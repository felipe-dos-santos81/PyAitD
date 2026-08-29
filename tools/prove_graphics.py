# SPDX-License-Identifier: GPL-2.0-only
"""Render fixed fixtures through the enhanced pipeline for the manual proof.

Boots two fixtures on a standalone ModernGL context and writes one PNG per
fixture per shading mode per realism preset to `--out` (default
`docs/graphics-proof/`), plus one flat-mesh (smoothing 0) PNG per fixture
beside the smooth-enhanced render:

- `attic`: the M1/M2 attic debug start (`init_game`, floor 0).
- `combat`: the shared floor-5 debug venue (`scenario.enter_combat_venue`).

This repo never ships game data, so the PNGs are never committed --
`docs/graphics-proof/` keeps only a `.gitkeep`. See
`docs/graphics-realism-proof.md` for the manual attestation the twelve
per-mode renders feed, and `docs/smooth-geometry-proof.md` for the one the
two `-flatmesh` files feed.
"""
import argparse
import pathlib
import sys
from dataclasses import replace

import numpy as np

from PyAitD.render.asset_resolver import AssetResolver
from PyAitD.engine.game import init_game
from PyAitD.render.render_gl import GLBackend
from PyAitD.render.render_options import REALISM_MODES, SHADING_MODES, SMOOTHING_LEVELS, RenderOptions
from PyAitD.games.aitd1.scenario import enter_combat_venue
from PyAitD.render.scene import build_frame
from PyAitD.games.aitd1.profile import AITD1

FIXTURES = ("attic", "combat")


def _boot(data_dir, name):
    game = init_game(data_dir, AITD1)
    if name == "combat":
        enter_combat_venue(game)
    game.num_camera = game.new_num_camera
    return game, game.load_floor(game.current_floor)


def render_fixture(data_dir, name, scale, shading, ctx, realism="enhanced", smoothing=None):
    game, floor = _boot(data_dir, name)
    frame, _ = build_frame(game, floor, AssetResolver(game.assets))
    options = RenderOptions(scale=scale, shading=shading, realism=realism)
    if smoothing is not None:
        options = replace(options, smoothing=smoothing)
    backend = GLBackend(ctx, options)
    try:
        backend.draw(frame)
        return backend.read_rgb()
    finally:
        backend.release()


def output_paths(out_dir, smoothing=None):
    """(name, mode, realism, smoothing, path) for every fixture x shading-mode
    x realism combination at `smoothing` (the RenderOptions default when
    None), then one flat-mesh (smoothing 0) file per fixture beside the
    smooth-enhanced render, in the order rendered and printed by `main`."""
    out_dir = pathlib.Path(out_dir)
    level = RenderOptions().smoothing if smoothing is None else smoothing
    paths = [
        (name, mode, realism, level, out_dir / f"{name}-{mode}-{realism}.png")
        for name in FIXTURES
        for mode in SHADING_MODES
        for realism in REALISM_MODES
    ]
    paths += [(name, "smooth", "enhanced", 0, out_dir / f"{name}-smooth-enhanced-flatmesh.png")
              for name in FIXTURES]
    return paths


def _parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("data", type=pathlib.Path, help="game data directory (e.g. .../INDARK)")
    p.add_argument("--out", type=pathlib.Path, default=pathlib.Path("docs/graphics-proof"),
                    help="output directory for the rendered PNGs")
    p.add_argument("--scale", type=int, default=4, help="internal render scale (default 4)")
    p.add_argument("--smoothing", type=int, choices=SMOOTHING_LEVELS, default=RenderOptions().smoothing,
                   help="mesh smoothing level for the main renders (the -flatmesh pair is always 0)")
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
        for name, mode, realism, level, path in output_paths(args.out, args.smoothing):
            rgb = render_fixture(args.data, name, args.scale, mode, ctx, realism, level)
            surface = pygame.surfarray.make_surface(np.ascontiguousarray(rgb.swapaxes(0, 1)))
            pygame.image.save(surface, str(path))
            print(path)
    finally:
        ctx.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
