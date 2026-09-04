# SPDX-License-Identifier: GPL-2.0-only
"""Render every camera the opening cutscene visits (floor 7 -> 3 -> 2 -> 1)
through the GL backend, one PNG per camera change, to --out (default
docs/intro-proof/). Also writes intro-ticks.txt with the visit list.
Never commit the PNGs: they are game data.

`render_camera` re-simulates from tick 0 up to the requested tick for every
camera it renders (~20 cameras x up to ~7300 ticks each, roughly 30s total
on real data) rather than caching intermediate state -- acceptable for a
proof tool that runs on demand, not in the test suite.
"""
import argparse
import pathlib
import sys

from PyAitD.render.asset_resolver import AssetResolver
from PyAitD.engine.script.effects import CutsceneFinished
from PyAitD.engine.script.game import init_game, start_game
from PyAitD.engine.script.interaction import apply_reading_result
from PyAitD.engine.script.playworld import IDLE, play_tick
from PyAitD.render.render_gl import GLBackend
from PyAitD.render.render_options import RenderOptions
from PyAitD.render.scene import build_frame
from PyAitD.app.ui import ReadingResult
from PyAitD.games.aitd1.profile import AITD1
if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from tools.export_textures import save_png  # noqa: E402

MAX_TICKS = 8000


def _boot(data_dir):
    game = init_game(data_dir, AITD1, hero=0)
    start_game(game, *AITD1.intro_start)
    game.allow_system_menu = False
    return game, game.load_floor(game.current_floor)


def _step(game, floor):
    play_tick(game, floor, IDLE)
    if floor.number != game.current_floor:
        floor = game.load_floor(game.current_floor)
    if game.mode.name != "PLAY" and not isinstance(game.active_modal, CutsceneFinished):
        apply_reading_result(game, ReadingResult(True))
    return floor


def _camera_key(game, floor):
    if game.num_camera == -1:
        return None
    return (floor.number, floor.rooms[game.current_room].camera_indices[game.num_camera])


def visited_cameras(data_dir):
    """(tick, floor, cam_idx) at every camera change from intro boot to
    CutsceneFinished, headless."""
    game, floor = _boot(data_dir)
    visits, last = [], None
    for tick in range(MAX_TICKS):
        floor = _step(game, floor)
        key = _camera_key(game, floor)
        if key is not None and key != last:
            visits.append((tick, key[0], key[1]))
            last = key
        if isinstance(game.active_modal, CutsceneFinished):
            break
    return visits


def render_camera(data_dir, tick, scale, ctx):
    """Re-run the intro from tick 0 through `tick` (inclusive) and render
    the resulting frame. See the module docstring for the re-simulation
    cost this incurs when called once per visited camera."""
    game, floor = _boot(data_dir)
    for _ in range(tick + 1):
        floor = _step(game, floor)
    frame, _ = build_frame(game, floor, AssetResolver(game.assets))
    backend = GLBackend(ctx, RenderOptions(scale=scale))
    try:
        backend.draw(frame)
        return backend.read_rgb()
    finally:
        backend.release()


def output_paths(out_dir, visits):
    out_dir = pathlib.Path(out_dir)
    return [out_dir / f"intro-{floor:02d}-{cam:03d}-{tick:05d}.png" for tick, floor, cam in visits]


def _parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("data", type=pathlib.Path)
    p.add_argument("--out", type=pathlib.Path, default=pathlib.Path("docs/intro-proof"))
    p.add_argument("--scale", type=int, default=2)
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    try:
        import moderngl
        ctx = moderngl.create_standalone_context(require=330)
    except Exception as exc:
        print(f"no standalone GL 3.3 context: {exc}", file=sys.stderr)
        return 3
    try:
        visits = visited_cameras(args.data)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "intro-ticks.txt").write_text("".join(f"{t} floor {f} camera {c}\n" for t, f, c in visits))
        for (tick, floor, cam), path in zip(visits, output_paths(args.out, visits)):
            save_png(path, render_camera(args.data, tick, args.scale, ctx))
            print(path)
    finally:
        ctx.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
