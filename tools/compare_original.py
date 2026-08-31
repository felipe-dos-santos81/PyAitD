# SPDX-License-Identifier: GPL-2.0-only
"""Live mirror: run the original AITD1 in DOSBox-X below our port and
forward our consumed PLAY keyboard input into it (spec:
docs/superpowers/specs/2026-08-30-compare-original-live-mirror-design.md).

Owns every process-shaped thing: the dosbox-x child, the resident Swift
helper, window placement and teardown. The port itself runs in-process so
its mirror sink holds the helper pipe directly.
"""
import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_DATA = (
    REPO / "data" / "aitd1" / "Alone in the Dark 1.app"
    / "Contents" / "Resources" / "game" / "INDARK"
)
HELPER_SRC = REPO / "tools" / "mirror_helper.swift"
HELPER_BIN = REPO / "tools" / ".cache" / "mirror_helper"

CONF_TEMPLATE = """[sdl]
fullscreen=false
autolock=false
windowresolution=640x400

[autoexec]
@echo off
mount C "game"
c:
imgmount D "GAME.INS" -t iso
CD INDARK
INDARK
"""


def generate_conf():
    return CONF_TEMPLATE


def dosbox_position(our_bounds, gap=24):
    x, y, _w, h = our_bounds
    return (x, y + h + gap)


def parse_compare_args(argv):
    p = argparse.ArgumentParser(
        prog="compare_original", description="live mirror: original below the port",
    )
    p.add_argument("--data", type=pathlib.Path, default=DEFAULT_DATA,
                   help="game data dir (same semantics as make run)")
    p.add_argument("--hero", type=int, choices=(0, 1), default=0)
    return p.parse_args(argv)


def ensure_helper():
    if not shutil.which("swiftc"):
        sys.exit("error: swiftc not found (Xcode command line tools)")
    if not HELPER_BIN.exists():
        HELPER_BIN.parent.mkdir(parents=True, exist_ok=True)
        done = subprocess.run(
            ["swiftc", str(HELPER_SRC), "-o", str(HELPER_BIN)],
            capture_output=True, text=True,
        )
        if done.returncode != 0:
            sys.exit(f"error: helper compile failed:\n{done.stderr}")
    return HELPER_BIN


def _window(helper, needle):
    helper.stdin.write(f"window {needle}\n")
    helper.stdin.flush()
    # Async "DEAD <pid>" lines share this stdout; skip anything that parses
    # as neither NONE nor five ints, bounded so a chatty helper cannot wedge
    # us.
    for _ in range(8):
        line = helper.stdout.readline().split()
        if not line or line[0] == "NONE":
            return None
        if len(line) == 5:
            try:
                return tuple(int(v) for v in line)  # pid x y w h
            except ValueError:
                continue
    return None


def _place_below(helper):
    ours = _window(helper, "pyaitd")
    dosbox = _window(helper, "dosbox")
    if not ours or not dosbox:
        print("note: could not find both windows; place the DOSBox-X window "
              "below the PyAitD window by hand")
        return
    x, y = dosbox_position(ours[1:5])
    subprocess.run([
        "osascript", "-e",
        f'tell application "System Events" to tell process "dosbox-x" '
        f"to set position of window 1 to {{{x}, {y}}}",
    ], capture_output=True)


def main(argv=None):
    args = parse_compare_args(argv)
    if not shutil.which("dosbox-x"):
        sys.exit("error: dosbox-x not found on PATH (brew install dosbox-x)")
    for name in ("INDARK.EXE",):
        if not (args.data / name).exists():
            sys.exit(f"error: {args.data / name} missing: not the DOS data dir?")
    # The bundle keeps the disc images beside INDARK/ — the mounted C: the
    # conf's imgmount reads GAME.INS from after `c:` — not at the Resources
    # root (pinned from the real bundle by tests/test_compare_original.py).
    game_dir = args.data.parent
    for name in ("GAME.INS", "GAME.GOG"):
        if not (game_dir / name).exists():
            sys.exit(f"error: {game_dir / name} missing: not the bundle game dir?")
    resources = game_dir.parent
    print("note: the terminal needs macOS Accessibility permission to post "
          "keys; grant it in System Settings if the original ignores input")

    helper_bin = ensure_helper()
    conf_dir = tempfile.mkdtemp(prefix="pyaitd-compare-")
    conf = pathlib.Path(conf_dir) / "windowed.conf"
    conf.write_text(generate_conf(), encoding="ascii")

    dosbox = subprocess.Popen(
        ["dosbox-x", "-conf", str(conf)], cwd=resources,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    helper = subprocess.Popen(
        [str(helper_bin)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        text=True, bufsize=1,
    )
    try:
        for _ in range(75):  # ~15 s for the DOS boot
            if _window(helper, "dosbox"):
                break
            time.sleep(0.2)
        else:
            sys.exit("error: the DOSBox-X window never appeared; see its log")

        os.environ["SDL_VIDEO_WINDOW_POS"] = "100,60"
        os.environ["PYAITD_MIRROR_PID"] = str(dosbox.pid)
        os.environ["PYAITD_MIRROR_FD"] = str(helper.stdin.fileno())

        # shell.main blocks for the whole session, so placement runs in a
        # daemon thread: it polls until BOTH windows answer (ours appears
        # only once the port renders), places once, and exits.
        import threading

        def place_once():
            for _ in range(150):  # ~30 s
                if _window(helper, "pyaitd") and _window(helper, "dosbox"):
                    _place_below(helper)
                    return
                time.sleep(0.2)
            print("note: could not find both windows; place the DOSBox-X "
                  "window below the PyAitD window by hand")

        threading.Thread(target=place_once, daemon=True).start()

        from PyAitD.app import shell
        return shell.main([
            "--data", str(args.data), "--hero", str(args.hero),
            "--render-scale", "2", "--mirror",
        ])
    finally:
        helper.terminate()
        dosbox.terminate()


if __name__ == "__main__":
    sys.exit(main())
