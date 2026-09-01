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


def test_the_strong_twin_composites_harder_than_the_default(gl_ctx, data_dir):
    # The `-strong` render is the only place the proof shows a level above
    # the default, so it has to actually differ from it.
    full = render_fixture(data_dir, "attic", scale=2, shading="smooth", ctx=gl_ctx)
    strong = render_fixture(data_dir, "attic", scale=2, shading="smooth", ctx=gl_ctx,
                            integration=3)
    assert not np.array_equal(full, strong)


def test_the_default_composites_and_nocomposite_does_not(gl_ctx, data_dir):
    rgb = render_fixture(data_dir, "attic", scale=2, shading="smooth", ctx=gl_ctx)
    plain = render_fixture(data_dir, "attic", scale=2, shading="smooth", ctx=gl_ctx,
                           integration=0)
    assert not np.array_equal(rgb, plain)   # the default composites, and it shows


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
    assert len(paths) == len(FIXTURES) * len(SHADING_MODES) * len(REALISM_MODES) + 9 * len(FIXTURES)
    default = RenderOptions()
    # keyed on `label`, not `motion_blend` -- Minor 8: motion_blend alone
    # collides between the plain smooth-enhanced main row and the
    # -tickmotion row whenever motion_blend is False (--motion tick), which
    # a set keyed on the other seven fields would silently collapse -- and
    # the -painted row's motion_blend is always False too, so it needs the
    # same distinct-label treatment to avoid colliding with either
    names = {(name, mode, realism, level, shadows, integration, occlusion, atmosphere, label)
             for name, mode, realism, level, shadows, integration, occlusion, atmosphere,
             _motion_blend, label, _ in paths}
    expected = {(n, m, r, default.smoothing, default.shadows, default.integration,
                 default.occlusion, default.atmosphere, "")
                for n in FIXTURES for m in SHADING_MODES for r in REALISM_MODES}
    expected |= {(n, "smooth", "enhanced", 0, default.shadows, default.integration, default.occlusion,
                  default.atmosphere, "flatmesh")
                 for n in FIXTURES}
    expected |= {(n, "smooth", "enhanced", default.smoothing, "hard", default.integration,
                  default.occlusion, default.atmosphere, "hardshadow")
                 for n in FIXTURES}
    expected |= {(n, "smooth", "enhanced", default.smoothing, default.shadows, 0, default.occlusion,
                  default.atmosphere, "nocomposite")
                 for n in FIXTURES}
    expected |= {(n, "smooth", "enhanced", default.smoothing, default.shadows, 3, default.occlusion,
                  default.atmosphere, "strong")
                 for n in FIXTURES}
    expected |= {(n, "smooth", "enhanced", default.smoothing, default.shadows, default.integration,
                  default.occlusion, default.atmosphere, "tickmotion")
                 for n in FIXTURES}
    expected |= {(n, "smooth", "enhanced", default.smoothing, default.shadows, default.integration,
                  default.occlusion, default.atmosphere, "painted")
                 for n in FIXTURES}
    expected |= {(n, "smooth", "enhanced", default.smoothing, default.shadows, default.integration,
                  "off", default.atmosphere, "nossao")
                 for n in FIXTURES}
    expected |= {(n, "smooth", "enhanced", default.smoothing, "room", default.integration,
                  default.occlusion, default.atmosphere, "roomshadow")
                 for n in FIXTURES}
    expected |= {(n, "smooth", "enhanced", default.smoothing, default.shadows, default.integration,
                  default.occlusion, "off", "nohaze")
                 for n in FIXTURES}
    assert names == expected
    # Each twin forces the *non-default* value of the field it is named
    # for, or it renders the same image twice and proves nothing (the
    # mistake -roomshadow's first draft made). `nohaze` is the newest and
    # the one whose default moved in this very task.
    assert default.atmosphere == "on"
    assert {a for *_r, a, _b, label, _p in paths if label == "nohaze"} == {"off"}
    # the -tickmotion row's motion_blend still tracks the "smooth" default
    # regardless of its distinct label
    tickmotion_blends = {motion_blend
                         for *_, motion_blend, label, _ in paths if label == "tickmotion"}
    assert tickmotion_blends == {default.motion == "smooth"}
    # the -painted row never motion-blends, regardless of --motion
    painted_blends = {motion_blend
                      for *_, motion_blend, label, _ in paths if label == "painted"}
    assert painted_blends == {False}
    for (name, mode, realism, level, shadows, integration, occlusion, atmosphere, motion_blend,
         label, path) in paths:
        suffix = f"-{label}" if label else ""
        assert path == pathlib.Path("docs/graphics-proof") / f"{name}-{mode}-{realism}{suffix}.png"


def test_parse_args_smoothing_and_shadows_default_to_the_render_defaults():
    from PyAitD.render.render_options import RenderOptions
    assert _parse_args(["d"]).smoothing == RenderOptions().smoothing
    assert _parse_args(["d", "--smoothing", "0"]).smoothing == 0
    assert _parse_args(["d"]).shadows == RenderOptions().shadows
    assert _parse_args(["d", "--shadows", "hard"]).shadows == "hard"
    assert _parse_args(["d"]).integration == RenderOptions().integration
    assert _parse_args(["d", "--integration", "0"]).integration == 0
    assert _parse_args(["d", "--integration", "3"]).integration == 3


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
    assert params == ["data_dir", "name", "scale", "shading", "ctx", "realism", "smoothing",
                      "shadows", "integration", "motion_blend", "painted", "occlusion",
                      "atmosphere"]


def test_the_nossao_twin_differs_from_the_default(tmp_path, gl_ctx, data_dir):
    default = render_fixture(data_dir, "attic", 1, "smooth", gl_ctx)
    nossao = render_fixture(data_dir, "attic", 1, "smooth", gl_ctx, occlusion="off")
    assert not np.array_equal(default, nossao)


def test_the_nohaze_twin_differs_from_the_default(tmp_path, gl_ctx, data_dir):
    # The attic is the small-room case the haze is designed to leave
    # alone, so this pair was not guaranteed to differ -- but measured, it
    # does: the attic's own camera has focal1 1431 and its covered actor
    # depths run 1431..12840 (median 4780), so most of its cast is past
    # HAZE_START = 2500 and hazes. Only its nearest actor (depth
    # 1503..1728) is genuinely untouched. Asserted on both fixtures
    # because the combat venue -- whose whole visible cast sits at depth
    # 22000..29500 -- is the unambiguous far case, and a twin that held on
    # one fixture only would be worth knowing about.
    for fixture in ("attic", "combat"):
        default = render_fixture(data_dir, fixture, 1, "smooth", gl_ctx)
        nohaze = render_fixture(data_dir, fixture, 1, "smooth", gl_ctx, atmosphere="off")
        assert not np.array_equal(default, nohaze), fixture
        # An anti-collapse floor, deliberately not a pin on the tuned value.
        # `not array_equal` alone is satisfied by a difference no eye could
        # find, which is how an on-by-default knob becomes an inert feature
        # -- the failure class this repo keeps re-learning. Measured peaks
        # at this scale, sweeping HAZE_DENSITY: 3.5e-5 (shipped) gives
        # attic 22 / combat 34; 1.2e-5 gives 9 / 16; 4e-6 gives 5 / 8; and
        # 0.0 still gives 3 / 4 -- from the *grain* grade alone, not from
        # "the two grades" as this comment first claimed. Measured by
        # zeroing each term in turn at this scale: grain-only gives 3 / 4,
        # sigma-only gives 0 / 0, all three zero gives 0 / 0. The sigma
        # grade contributes exactly nothing here because these renders are
        # scale 1, where `plate.softness` yields cell <= 1, `radius` is 0
        # and `sample_layers` takes an early return that never reads
        # `grade` at all (see the same note in docs/atmosphere-proof.md's
        # limitations).
        #
        # So this floor cannot be set at the shipped value's own magnitude
        # without pinning taste, and it is not: 6 sits above the 3-4 the
        # grain grade alone produces and below the 9 the previously-shipped
        # density produced, so a human retuning by eye keeps real room in
        # both directions. Whether 1.2e-5 was *too weak* is a judgement
        # recorded in docs/atmosphere-proof.md and left to the attestation
        # table, not encoded here.
        delta = np.abs(default.astype(np.int32) - nohaze.astype(np.int32)).max()
        assert delta >= 6, f"{fixture}: peak haze is {delta} counts -- all but invisible"


def test_parse_args_atmosphere_defaults_to_the_render_default():
    from PyAitD.render.render_options import RenderOptions
    assert _parse_args(["d"]).atmosphere == RenderOptions().atmosphere == "on"
    assert _parse_args(["d", "--atmosphere", "off"]).atmosphere == "off"


def test_the_roomshadow_twin_differs_from_the_default(tmp_path, gl_ctx, data_dir):
    # Unlike -nossao, this pair is not guaranteed to differ on every
    # fixture: the room receiver pass only darkens pixels a hard_col top
    # actually receives a shadow on (test_room_with_no_hard_col_in_view_
    # matches_soft in tests/test_render_gl.py is the neutral identity for
    # a fixture with no box in view). Measured directly: the attic fixture
    # renders byte-identical under "room" (no hard_col catches a shadow
    # there), while the combat fixture -- which has furniture-proxy boxes
    # in view -- does differ, which is why this test uses "combat" rather
    # than following -nossao's "attic" example.
    default = render_fixture(data_dir, "combat", 1, "smooth", gl_ctx)
    roomshadow = render_fixture(data_dir, "combat", 1, "smooth", gl_ctx, shadows="room")
    assert not np.array_equal(default, roomshadow)
