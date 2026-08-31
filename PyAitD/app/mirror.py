# SPDX-License-Identifier: GPL-2.0-only
"""The live-mirror sink: translate consumed controls into helper lines.

The sink only observes; it never blocks: write_line appends to a
line-buffered pipe owned by tools/compare_original.py, and the helper
that reads it is a separate process."""
from PyAitD.games.aitd1.mirror import MIRROR_KEYCODES


class MirrorSink:
    def __init__(self, write_line, pid):
        self._write_line = write_line
        self._pid = pid

    def key_down(self, name):
        self._post(name, "down")

    def key_up(self, name):
        self._post(name, "up")

    def _post(self, name, edge):
        keycode = MIRROR_KEYCODES.get(name)
        if keycode is None:
            return
        self._write_line(f"post {keycode} {edge} {self._pid}")
