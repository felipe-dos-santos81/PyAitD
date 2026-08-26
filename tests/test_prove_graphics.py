# SPDX-License-Identifier: GPL-2.0-only
"""tools/prove_graphics.py: data-free coverage (argument parsing, output path
construction, the exit-3-without-GL path, mode iteration) plus the one
data-dependent render, which skips without real game data (see data_dir)."""
import pathlib

import numpy as np
import pytest

from PyAitD.render.render_options import SHADING_MODES
from tools.prove_graphics import FIXTURES, _parse_args, main, output_paths, render_fixture

pytestmark = pytest.mark.tools


def test_render_fixture_produces_scaled_frames(data_dir, gl_ctx):
    rgb = render_fixture(data_dir, "attic", scale=2, shading="smooth", ctx=gl_ctx)
    assert rgb.shape == (400, 640, 3)
    assert rgb.std() > 10  # not a blank frame


def test_parse_args_defaults():
    args = _parse_args(["some/data/dir"])
    assert args.data == pathlib.Path("some/data/dir")
    assert args.out == pathlib.Path("docs/graphics-proof")
    assert args.scale == 4


def test_parse_args_overrides():
    args = _parse_args(["some/data/dir", "--out", "/tmp/out", "--scale", "2"])
    assert args.out == pathlib.Path("/tmp/out")
    assert args.scale == 2


def test_output_paths_covers_every_fixture_and_shading_mode():
    paths = output_paths("docs/graphics-proof")
    assert len(paths) == len(FIXTURES) * len(SHADING_MODES)
    names = {(name, mode) for name, mode, _ in paths}
    assert names == {(name, mode) for name in FIXTURES for mode in SHADING_MODES}
    for name, mode, path in paths:
        assert path == pathlib.Path("docs/graphics-proof") / f"{name}-{mode}.png"


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
    assert params == ["data_dir", "name", "scale", "shading", "ctx"]
