# SPDX-License-Identifier: GPL-2.0-only
"""Render fixed fixtures through the enhanced pipeline for the manual proof.

Boots two fixtures on a standalone ModernGL context and writes one PNG per
fixture per shading mode per realism preset to `--out` (default
`docs/graphics-proof/`), plus one flat-mesh (smoothing 0), one
hard-shadow (`shadows=hard`), one un-composited (`integration=0`), one
over-composited (`integration=3`), one motion-blended (mid-tick,
alpha 0.5), one synthetically-painted (a generated checker atlas
sampled non-uniformly per triangle, since this repo never ships a real
body paint), one SSAO-off (`occlusion=off`), one room-shadow
(`shadows=room`) and one un-hazed (`atmosphere=off`) PNG per fixture
beside the smooth-enhanced render:

- `attic`: the M1/M2 attic debug start (`init_game`, floor 0).
- `combat`: the shared floor-5 debug venue (`scenario.enter_combat_venue`).

This repo never ships game data, so the PNGs are never committed --
`docs/graphics-proof/` keeps only a `.gitkeep`. See
`docs/graphics-realism-proof.md` for the manual attestation the twelve
per-mode renders feed, `docs/smooth-geometry-proof.md` for the one the two
`-flatmesh` files feed, `docs/soft-shadows-proof.md` for the one the
two `-hardshadow` files feed, `docs/plate-integration-proof.md` for the
one the two `-nocomposite` files feed, `docs/materials-v2-proof.md`
for the per-material-class one the `-enhanced` renders feed,
`docs/motion-interpolation-proof.md` for the one the two `-tickmotion`
files feed, `docs/actor-textures-proof.md` for the one the two
`-painted` files feed, and `docs/light-transport-proof.md` for the one
the `-nossao` and `-roomshadow` pairs feed, and
`docs/atmosphere-proof.md` for the one the two `-nohaze` files feed.
The two `-strong` files are the top of the integration range, which the
`-nocomposite` pair floors and the default renders sit between.
"""
import argparse
import dataclasses
import pathlib
import sys
from dataclasses import replace

import numpy as np

from PyAitD.render.asset_resolver import AssetResolver, ImageAsset
from PyAitD.engine.script.game import init_game
from PyAitD.render.motion import MotionSnapshot, snapshot as motion_snapshot
from PyAitD.render.render_gl import GLBackend
from PyAitD.render.render_options import (
    ATMOSPHERE_MODES, INTEGRATION_LEVELS, MOTION_MODES, OCCLUSION_MODES, REALISM_MODES,
    SHADING_MODES, SHADOW_MODES, SMOOTHING_LEVELS, RenderOptions,
)
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


def _checker_atlas(size=64, squares=8):
    """A generated (size, size, 3) uint8 checker pattern -- this repo never
    ships a real body paint, so the proof synthesises one to sample."""
    step = max(1, size // squares)
    row, col = np.indices((size, size)) // step
    on = (row + col) % 2 == 0
    atlas = np.where(on[..., None], np.uint8(230), np.uint8(30))
    return np.repeat(atlas, 3, axis=-1)


def _triangle_index_uv(num_tris, squares=8):
    """(num_tris, 3, 2) float32 -- one flat (all-three-corners-equal) UV
    per triangle, keyed to the triangle's own index, spread across an
    8x8 grid of texel-centred sample points (never a grid-line
    intersection, so mipmapped bilinear filtering never averages a
    sample into the same mid-grey a flat colour would already give)."""
    idx = np.arange(num_tris, dtype=np.float32)
    u = ((idx % squares) + 0.5) / squares
    v = ((idx // squares % squares) + 0.5) / squares
    pair = np.stack([u, v], axis=-1)[:, None, :]      # (num_tris, 1, 2)
    return np.full((num_tris, 3, 2), pair, dtype=np.float32)


def render_fixture(data_dir, name, scale, shading, ctx, realism="enhanced", smoothing=None,
                   shadows=None, integration=None, motion_blend=False, painted=False,
                   occlusion=None, atmosphere=None):
    # options is built before either build_frame call below and its
    # .shadows read back into them -- the same "read it off the resolved
    # options" shape shell.py's _scene_frame uses against renderer.options
    # -- so the frame's receivers and the backend's shadow-map/gather
    # gating can never disagree about which mode is active. Keep the
    # existing behaviour byte-identical when the mode is not "room": both
    # RenderOptions' and build_frame's own default is "soft", so an unset
    # `shadows` here still resolves to the same mode either call would
    # have used on its own. `occlusion` needs no such threading -- it only
    # ever reaches the backend below, never build_frame. `atmosphere` is
    # the same: it lives entirely in the composite pass.
    # One `replace` over whatever was actually passed, rather than one
    # `if x is not None` block per field: None means "leave the
    # RenderOptions default alone", and the Nth proof option is a tuple
    # entry rather than a sixth near-identical branch.
    forced = {field: value for field, value in (
        ("smoothing", smoothing), ("shadows", shadows), ("integration", integration),
        ("occlusion", occlusion), ("atmosphere", atmosphere)) if value is not None}
    options = replace(RenderOptions(scale=scale, shading=shading, realism=realism), **forced)

    game, floor = _boot(data_dir, name)
    resolver = AssetResolver(game.assets)
    frame, _ = build_frame(game, floor, resolver, shadows=options.shadows)
    if motion_blend:
        # a synthetic "previous tick" 64 rotation units back: the blended
        # frame renders every actor 32 units (11 degrees) short of its
        # live beta, which is visibly between the two, deterministically
        snap = motion_snapshot(game)
        shifted = MotionSnapshot(snap.floor, snap.room, snap.camera, {
            index: dataclasses.replace(
                entry, angles=(entry.angles[0], (entry.angles[1] - 64.0) % 1024.0, entry.angles[2]))
            for index, entry in snap.actors.items()
        })
        frame, _ = build_frame(game, floor, resolver, blend=(shifted, 0.5), shadows=options.shadows)
    if painted:
        # No paint ships with this repo, so synthesise one: a generated
        # checker atlas, sampled non-uniformly across each body by keying
        # every triangle's (flat, all-three-corners-equal) UV to its own
        # index. U and V are independent (U cycles every 8 triangles, V
        # every 64) and offset to texel centres ((k + 0.5) / 8), so
        # triangles land on varied squares across the whole 8x8 grid
        # rather than only its diagonal, and mipmapped bilinear filtering
        # never samples a grid-line intersection -- u == v == k/8 (no
        # offset) would put every non-zero index on a corner shared by
        # two light and two dark squares, which LINEAR_MIPMAP_LINEAR
        # blends to near-uniform mid-grey, defeating the point of a
        # checker over a flat colour.
        texture = ImageAsset(_checker_atlas(), True)
        painted_actors = tuple(
            dataclasses.replace(
                actor,
                geometry=dataclasses.replace(
                    actor.geometry,
                    uv=_triangle_index_uv(len(actor.geometry.tris))),
                texture=texture,
            )
            for actor in frame.actors
        )
        frame = dataclasses.replace(frame, actors=painted_actors)
    backend = GLBackend(ctx, options)
    try:
        backend.draw(frame)
        return backend.read_rgb()
    finally:
        backend.release()


@dataclasses.dataclass(frozen=True)
class ProofRow:
    """One rendered PNG: which fixture, which options force it, where it lands.

    `forced` holds exactly the RenderOptions fields this row pins, ready to
    splat into `render_fixture`. Carrying a dict rather than one positional
    field per option is what keeps a new proof option to one VARIANTS line
    and one `base` entry, instead of widening a tuple in nine places and
    every consumer that unpacks it.
    """
    name: str
    shading: str
    realism: str
    forced: dict
    motion_blend: bool
    painted: bool
    label: str
    path: pathlib.Path


def output_paths(out_dir, smoothing=None, shadows=None, integration=None, motion=None,
                 occlusion=None, atmosphere=None):
    """A ProofRow for every fixture x shading-mode x realism combination at
    `smoothing`, `shadows`, `integration`, `occlusion` and `atmosphere`
    (the RenderOptions defaults when None), then one twin per entry in
    VARIANTS below per fixture, in the order rendered and printed by
    `main`.

    `label` is the row's own identity ("" for a main combination, else the
    filename suffix its variant renders with) -- it is what the filename is
    built from, and it stays distinct per row regardless of what
    `motion_blend` and `forced` happen to hold. Without it, the
    `-tickmotion` row's other fields collide with the plain smooth-enhanced
    main row's whenever `motion_blend` is False (i.e. --motion tick), which
    would silently drop one of the two from any de-duplication keyed on
    those fields alone. `-painted` needs it for the same reason.

    Every twin forces the *non-default* value of the field it is named
    for, or it renders the same image twice and proves nothing -- the
    mistake `-roomshadow`'s first draft made by forcing "soft" against a
    default that has never moved off "soft", and the reason `-nohaze`
    forces "off" against the "on" default rather than the other way round.
    `-nocomposite` and `-strong` are the exception by design: they bracket
    the default integration level from both ends, 0 and 3, so the proof
    shows the grading rather than only its middle."""
    out_dir = pathlib.Path(out_dir)
    defaults = RenderOptions()
    base = {
        "smoothing": defaults.smoothing if smoothing is None else smoothing,
        "shadows": defaults.shadows if shadows is None else shadows,
        "integration": defaults.integration if integration is None else integration,
        "occlusion": defaults.occlusion if occlusion is None else occlusion,
        "atmosphere": defaults.atmosphere if atmosphere is None else atmosphere,
    }
    # The -tickmotion twin renders mid-blend (alpha 0.5) when `motion` is
    # "smooth" and unblended -- the escape hatch -- when it is "tick". The
    # -painted twin renders with a synthetic checker atlas standing in for
    # a real body paint (this repo never ships one) and never blends.
    blend = ((defaults.motion if motion is None else motion) == "smooth")
    # (label, forced-field overrides, motion_blend, painted)
    VARIANTS = (
        ("flatmesh", {"smoothing": 0}, False, False),
        ("hardshadow", {"shadows": "hard"}, False, False),
        ("nocomposite", {"integration": 0}, False, False),
        ("strong", {"integration": 3}, False, False),
        ("tickmotion", {}, blend, False),
        ("painted", {}, False, True),
        ("nossao", {"occlusion": "off"}, False, False),
        ("roomshadow", {"shadows": "room"}, False, False),
        ("nohaze", {"atmosphere": "off"}, False, False),
    )

    def row(name, shading, realism, forced, motion_blend, painted, label):
        suffix = f"-{label}" if label else ""
        return ProofRow(name, shading, realism, forced, motion_blend, painted, label,
                        out_dir / f"{name}-{shading}-{realism}{suffix}.png")

    rows = [row(name, mode, realism, dict(base), False, False, "")
            for name in FIXTURES
            for mode in SHADING_MODES
            for realism in REALISM_MODES]
    rows += [row(name, "smooth", "enhanced", {**base, **forced}, motion_blend, painted, label)
             for label, forced, motion_blend, painted in VARIANTS
             for name in FIXTURES]
    return rows


def _parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("data", type=pathlib.Path, help="game data directory (e.g. .../INDARK)")
    p.add_argument("--out", type=pathlib.Path, default=pathlib.Path("docs/graphics-proof"),
                    help="output directory for the rendered PNGs")
    p.add_argument("--scale", type=int, default=4, help="internal render scale (default 4)")
    p.add_argument("--smoothing", type=int, choices=SMOOTHING_LEVELS, default=RenderOptions().smoothing,
                   help="mesh smoothing level for the main renders (the -flatmesh pair is always 0)")
    p.add_argument("--shadows", choices=SHADOW_MODES, default=RenderOptions().shadows,
                   help="shadow mode for the main renders (the -hardshadow pair is always hard)")
    p.add_argument("--integration", type=int, choices=INTEGRATION_LEVELS,
                   default=RenderOptions().integration,
                   help="plate integration for the main renders (the -nocomposite pair is always 0)")
    p.add_argument("--motion", choices=MOTION_MODES, default=RenderOptions().motion,
                   help="smooth renders the -tickmotion pair mid-blend (alpha 0.5); "
                        "tick renders it unblended")
    p.add_argument("--occlusion", choices=OCCLUSION_MODES, default=RenderOptions().occlusion,
                   help="screen-space ambient occlusion for the main renders "
                        "(the -nossao pair is always off)")
    p.add_argument("--atmosphere", choices=ATMOSPHERE_MODES, default=RenderOptions().atmosphere,
                   help="depth haze and the depth-graded softness and grain for the main "
                        "renders (the -nohaze pair is always off)")
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
        for r in output_paths(args.out, args.smoothing, args.shadows, args.integration,
                              args.motion, args.occlusion, args.atmosphere):
            rgb = render_fixture(args.data, r.name, args.scale, r.shading, ctx, r.realism,
                                 motion_blend=r.motion_blend, painted=r.painted, **r.forced)
            surface = pygame.surfarray.make_surface(np.ascontiguousarray(rgb.swapaxes(0, 1)))
            pygame.image.save(surface, str(r.path))
            print(r.path)
    finally:
        ctx.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
