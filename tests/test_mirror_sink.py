# SPDX-License-Identifier: GPL-2.0-only
"""MirrorSink: translate consumed controls into helper lines, nothing else."""
import pytest

from PyAitD.app.mirror import MirrorSink

pytestmark = pytest.mark.shell


def _sink():
    lines = []
    return MirrorSink(lines.append, pid=4242), lines


def test_forwarded_controls_emit_down_up_pairs():
    sink, lines = _sink()
    sink.key_down("UP")
    sink.key_up("UP")
    sink.key_down("ACTION")
    sink.key_up("ACTION")
    assert lines == [
        "post 126 down 4242",
        "post 126 up 4242",
        "post 49 down 4242",
        "post 49 up 4242",
    ]


def test_untabled_controls_are_ignored():
    sink, lines = _sink()
    sink.key_down("CANCEL")
    sink.key_down("OPEN_INVENTORY")
    sink.key_up("CANCEL")
    assert lines == []
