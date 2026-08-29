# SPDX-License-Identifier: GPL-2.0-only
"""tools/prove_graphics.py: data-free coverage (argument parsing, output path
construction, the exit-3-without-GL path, mode iteration) plus the one
data-dependent render, which skips without real game data (see data_dir)."""
import pathlib

import numpy as np
import pytest

from PyAitD.render.render_options import REALISM_MODES, SHADING_MODES
from tools.prove_graphics import FIXTURES, _parse_args, main, output_paths, render_fixture

pytestmark = pytest.mark.tools


def test_render_fixture_produces_scaled_frames(data_dir, gl_ctx):
    rgb = render_fixture(data_dir, "attic", scale=2, shading="smooth", ctx=gl_ctx)
    assert rgb.shape == (400, 640, 3)
    assert rgb.std() > 10  # not a blank frame
    classic = render_fixture(data_dir, "attic", scale=2, shading="smooth", ctx=gl_ctx, realism="classic")
    assert not np.array_equal(rgb, classic)   # the default is enhanced, and it shows
    flat = render_fixture(data_dir, "attic", scale=2, shading="smooth", ctx=gl_ctx, smoothing=0)
    assert not np.array_equal(rgb, flat)   # the default rounds the bodies, and it shows
    hard = render_fixture(data_dir, "attic", scale=2, shading="smooth", ctx=gl_ctx, shadows="hard")
    assert not np.array_equal(rgb, hard)   # the default softens the shadows, and it shows


def test_parse_args_defaults():
    args = _parse_args(["some/data/dir"])
    assert args.data == pathlib.Path("some/data/dir")
    assert args.out == pathlib.Path("docs/graphics-proof")
    assert args.scale == 4


def test_parse_args_overrides():
    args = _parse_args(["some/data/dir", "--out", "/tmp/out", "--scale", "2"])
    assert args.out == pathlib.Path("/tmp/out")
    assert args.scale == 2


def test_output_paths_cover_every_combination_plus_the_twins():
    from PyAitD.render.render_options import RenderOptions
    paths = output_paths("docs/graphics-proof")
    assert len(paths) == len(FIXTURES) * len(SHADING_MODES) * len(REALISM_MODES) + 2 * len(FIXTURES)
    default = RenderOptions()
    names = {(name, mode, realism, level, shadows) for name, mode, realism, level, shadows, _ in paths}
    expected = {(n, m, r, default.smoothing, default.shadows)
                for n in FIXTURES for m in SHADING_MODES for r in REALISM_MODES}
    expected |= {(n, "smooth", "enhanced", 0, default.shadows) for n in FIXTURES}
    expected |= {(n, "smooth", "enhanced", default.smoothing, "hard") for n in FIXTURES}
    assert names == expected
    for name, mode, realism, level, shadows, path in paths:
        suffix = "-flatmesh" if level == 0 else "-hardshadow" if shadows == "hard" else ""
        assert path == pathlib.Path("docs/graphics-proof") / f"{name}-{mode}-{realism}{suffix}.png"


def test_parse_args_smoothing_and_shadows_default_to_the_render_defaults():
    from PyAitD.render.render_options import RenderOptions
    assert _parse_args(["d"]).smoothing == RenderOptions().smoothing
    assert _parse_args(["d", "--smoothing", "0"]).smoothing == 0
    assert _parse_args(["d"]).shadows == RenderOptions().shadows
    assert _parse_args(["d", "--shadows", "hard"]).shadows == "hard"


def test_main_exits_2_when_data_directory_is_absent(tmp_path, capsys):
    missing = tmp_path / "no-such-data"
    code = main([str(missing)])
    assert code == 2
    assert "no-such-data" in capsys.readouterr().err


def test_main_exits_3_when_no_standalone_gl_context(tmp_path, monkeypatch, capsys):
    import moderngl

    def _raise(*a, **k):
        raise RuntimeError("no display")

    monkeypatch.setattr(moderngl, "create_standalone_context", _raise)
    code = main([str(tmp_path)])
    assert code == 3
    err = capsys.readouterr().err
    assert "no display" in err


def test_render_fixture_is_importable_with_the_documented_signature():
    # Purely a signature check -- guards against a stray reorder of
    # positional args in a later edit, without needing GL or game data.
    import inspect
    params = list(inspect.signature(render_fixture).parameters)
    assert params == ["data_dir", "name", "scale", "shading", "ctx", "realism", "smoothing", "shadows"]
