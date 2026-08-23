# SPDX-License-Identifier: GPL-2.0-only
"""Headless M3c proof: the shared floor-5 venue and every combat journey.

Runs the focused suite against the real game data with a dummy video driver,
and returns its status. Unlike the Phase-A version this reports nothing on its
own: a missing venue, a missing player arm, or a dead enemy script fails here.
"""
import os
import pathlib
import subprocess
import sys


def main(argv):
    data = pathlib.Path(argv[0])
    env = dict(os.environ, PYAITD_DATA=str(data), SDL_VIDEODRIVER="dummy")
    return subprocess.run(
        [
            sys.executable, "-m", "pytest", "-q",
            "tests/test_scenario.py",
            "tests/test_anim_action.py",
            "tests/test_game_over.py",
            "tests/test_combat_journey.py",
        ],
        cwd=pathlib.Path(__file__).resolve().parent.parent,
        env=env,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
