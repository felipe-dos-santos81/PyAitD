# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.cos_table import COS_TABLE, sin_cos


def test_length():
    assert len(COS_TABLE) == 1024


def test_pinned_values():
    assert COS_TABLE[0] == 4  # FITD quirk: 0 was bumped to 4
    assert COS_TABLE[1] == 201
    assert COS_TABLE[2] == 402
    assert COS_TABLE[256] == 32767
    assert COS_TABLE[512] == 0
    assert COS_TABLE[768] == -32767
    assert COS_TABLE[1023] == -201


def test_formula_consistency():
    import math
    for i in range(1024):
        expected = int(math.sin(i * math.pi / 512) * 32768)  # trunc toward zero
        expected = max(min(expected, 32767), -32767)
        if i == 0:
            continue  # pinned quirk
        assert COS_TABLE[i] == expected, f"index {i}"


def test_scene_and_render_gl_share_the_one_sin_cos_implementation():
    # Parity-critical: render_gl.rotation_matrix must stay term-for-term
    # identical to scene.CameraView.camera_space. Both used to carry their
    # own verbatim copy of this helper -- a real risk that an edit to one
    # copy silently misses the other. They now both import the same
    # function object from here; pin that identity so a reintroduced local
    # copy (in either module) fails this test instead of silently
    # reintroducing the duplication (and the divergence risk).
    import PyAitD.render_gl as render_gl_module
    import PyAitD.scene as scene_module

    assert render_gl_module.sin_cos is sin_cos
    assert scene_module.sin_cos is sin_cos
