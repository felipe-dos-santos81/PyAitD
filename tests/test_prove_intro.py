# SPDX-License-Identifier: GPL-2.0-only
import pathlib

from tools.prove_intro import _parse_args, output_paths, visited_cameras
import pytest

pytestmark = pytest.mark.tools


def test_parse_args_defaults():
    args = _parse_args(["some/data"])
    assert args.out == pathlib.Path("docs/intro-proof") and args.scale == 2


def test_visited_cameras_cover_every_intro_floor(data_dir):
    visits = visited_cameras(data_dir)
    assert [f for _, f, _ in visits][0] == 7
    assert {f for _, f, _ in visits} == {7, 3, 2, 1}
    assert visits == sorted(visits)
    for (tick, floor, cam), path in zip(visits, output_paths("x", visits)):
        assert path == pathlib.Path("x") / f"intro-{floor:02d}-{cam:03d}-{tick:05d}.png"
