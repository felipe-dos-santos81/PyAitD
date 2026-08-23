# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.cos_table import COS_TABLE


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
