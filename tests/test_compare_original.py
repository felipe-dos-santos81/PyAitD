# SPDX-License-Identifier: GPL-2.0-only
"""The compare orchestrator's pure parts: conf text, placement math, args."""
import pathlib

import pytest

pytestmark = pytest.mark.tools


def _mod():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "compare_original",
        pathlib.Path(__file__).resolve().parent.parent / "tools" / "compare_original.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_conf_is_windowed_and_skips_the_launcher():
    conf = _mod().generate_conf()
    assert "fullscreen=false" in conf
    assert "windowresolution=640x400" in conf
    assert 'mount C "game"' in conf
    assert 'imgmount D "GAME.INS" -t iso' in conf
    assert "CD INDARK" in conf
    assert "INDARK\n" in conf.split("CD INDARK\n", 1)[1]
    assert "choice" not in conf, "the interactive launcher must not run"


def test_dosbox_is_placed_below_our_window():
    assert _mod().dosbox_position((100, 60, 640, 432)) == (100, 60 + 432 + 24)


def test_parse_compare_args_defaults_to_the_bundled_data():
    args = _mod().parse_compare_args([])
    assert args.data.name == "INDARK"
    assert args.hero == 0


def test_the_bundle_keeps_the_disc_images_beside_indark(data_dir):
    # The orchestrator's startup check (and the conf's imgmount, which reads
    # GAME.INS off the mounted C: after `c:`) both rely on the real bundle
    # keeping the DOS disc images beside INDARK/ — not at the Resources root,
    # where an earlier check looked. Pinned from the shipped data.
    assert (data_dir.parent / "GAME.INS").exists()
    assert (data_dir.parent / "GAME.GOG").exists()
