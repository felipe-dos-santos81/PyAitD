# SPDX-License-Identifier: GPL-2.0-only
import pathlib

from maitd.__main__ import parse_args


def test_parse_args_defaults():
    args = parse_args([])
    assert args.floor == 0
    assert args.data is not None


def test_parse_args_overrides():
    args = parse_args(["--floor", "3", "--data", "/tmp/x"])
    assert args.floor == 3
    assert args.data == pathlib.Path("/tmp/x")
