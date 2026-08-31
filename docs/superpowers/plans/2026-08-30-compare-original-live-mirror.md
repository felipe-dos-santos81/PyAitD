# Compare-With-Original Live Mirror Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the original DOS AITD1 in a DOSBox-X window below our port and live-forward our consumed keyboard input into it, behind `make compare`.

**Architecture:** Four units: a string-keyed key translation table (`games/aitd1/mirror.py`), a forwarding sink (`app/mirror.py`) tapped by the shell pump only in PLAY, a resident Swift helper (`tools/mirror_helper.swift`) that posts CGEvents to the DOSBox-X pid, and an orchestrator (`tools/compare_original.py`) that owns both processes, window placement and teardown.

**Tech Stack:** Python (stdlib only — pygame-ce/NumPy/pytest stay the fixed deps), Swift (Xcode CLT `swiftc`), DOSBox-X (homebrew), macOS CoreGraphics/ScreenCaptureKit-free (posting only), System Events via `osascript`.

**Spec:** `docs/superpowers/specs/2026-08-30-compare-original-live-mirror-design.md`

## Global Constraints

- Dependencies fixed: pygame-ce, ModernGL, NumPy, pytest. Add nothing. `swiftc`/`dosbox-x`/`osascript` are system tools, not Python deps.
- `# SPDX-License-Identifier: GPL-2.0-only` first line of every Python file (and the Swift file's header comment).
- Every new test file declares exactly one subject marker as module-level `pytestmark`: `shell` for the mirror table/sink/tap tests (app-layer behaviour, same convention as the mouse-contract tests), `tools` for the orchestrator tests.
- Layering: `games/aitd1/mirror.py` imports nothing from `app/` (the `Control` enum lives in `app/config.py`; the table is keyed by control NAME strings). `app/` may import everything. Process spawning lives in `tools/`.
- The mirror tap must never alter game behaviour: it only observes consumed events.
- macOS-only; the gate stays headless-green everywhere (mirror tests never launch DOSBox or post events).
- Frequent commits: one per task, message style `feat:`/`test:`/`docs:`.

## File Structure

| File | Responsibility |
|---|---|
| `PyAitD/games/aitd1/mirror.py` | `MIRROR_KEYCODES`: control name → macOS virtual keycode, pinned from `FitdLib/input.cpp` |
| `PyAitD/app/mirror.py` | `MirrorSink(write_line, pid)`: translate + emit helper lines |
| `PyAitD/app/shell.py` | `--mirror` flag, sink construction from `PYAITD_MIRROR_FD`/`PYAITD_MIRROR_PID`, `run(..., mirror_sink=...)` pump tap |
| `tools/mirror_helper.swift` | resident stdin reader: `post <keycode> <down\|up> <pid>` (CGEventPostToPid, DEAD-once on dead pid), `window <needle>` (prints `pid x y w h`) |
| `tools/compare_original.py` | startup checks, conf generation, dosbox/helper lifecycle, placement, in-process port run, teardown; pure parts importable for tests |
| `Makefile` | `compare` target |
| `tests/test_mirror_table.py` | table pins |
| `tests/test_mirror_sink.py` | sink + shell tap tests |
| `tests/test_compare_original.py` | orchestrator pure parts |
| `docs/compare-original-proof.md` | evidence doc |

---

### Task 1: The translation table

**Files:**
- Create: `PyAitD/games/aitd1/mirror.py`
- Test: `tests/test_mirror_table.py`

**Interfaces:**
- Produces: `MIRROR_KEYCODES: dict[str, int]`

- [ ] **Step 1: Write the failing test**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""The live mirror's key table: the original AITD1 layout, FITD-pinned."""
import pytest

from PyAitD.games.aitd1.mirror import MIRROR_KEYCODES

pytestmark = pytest.mark.shell


def test_every_forwarded_control_has_a_mac_keycode():
    assert set(MIRROR_KEYCODES) == {
        "UP", "DOWN", "LEFT", "RIGHT", "ACTION", "INVENTORY_CONFIRM",
    }


def test_keycodes_match_the_original_layout():
    # FitdLib/input.cpp readKeyboard: arrows -> JoyD, Space -> Click,
    # Return -> 0x1C. macOS virtual keycodes (kVK_ constants).
    assert MIRROR_KEYCODES["UP"] == 126
    assert MIRROR_KEYCODES["DOWN"] == 125
    assert MIRROR_KEYCODES["LEFT"] == 123
    assert MIRROR_KEYCODES["RIGHT"] == 124
    assert MIRROR_KEYCODES["ACTION"] == 49
    assert MIRROR_KEYCODES["INVENTORY_CONFIRM"] == 36


def test_no_menu_key_is_forwarded():
    # Escape (system menu) and the inventory open key stay manual in the
    # original: forwarding them would desync the two menus.
    assert "CANCEL" not in MIRROR_KEYCODES
    assert "OPEN_INVENTORY" not in MIRROR_KEYCODES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_mirror_table.py -q`
Expected: FAIL — `ModuleNotFoundError: PyAitD.games.aitd1.mirror`.

- [ ] **Step 3: Write minimal implementation**

```python
# SPDX-License-Identifier: GPL-2.0-only
"""The original AITD1 keyboard layout as forwarded by the live mirror.

Keyed by control NAME strings: the Control enum lives in app/config.py,
so this module imports nothing from the app layer. Pinned from the FITD
authority, FitdLib/input.cpp readKeyboard: arrows drive JoyD, Space
drives Click, Return drives key 0x1C. Values are macOS virtual keycodes
(kVK_ constants)."""

MIRROR_KEYCODES = {
    "UP": 126,
    "DOWN": 125,
    "LEFT": 123,
    "RIGHT": 124,
    "ACTION": 49,               # Space -> Click
    "INVENTORY_CONFIRM": 36,    # Return -> 0x1C
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_mirror_table.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add PyAitD/games/aitd1/mirror.py tests/test_mirror_table.py
git commit -m "feat: pin the live mirror key translation table"
```

---

### Task 2: The sink

**Files:**
- Create: `PyAitD/app/mirror.py`
- Test: `tests/test_mirror_sink.py`

**Interfaces:**
- Consumes: `MIRROR_KEYCODES` (Task 1)
- Produces: `MirrorSink(write_line, pid)` with `key_down(name)` / `key_up(name)`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_mirror_sink.py -q`
Expected: FAIL — `ModuleNotFoundError: PyAitD.app.mirror`.

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_mirror_sink.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add PyAitD/app/mirror.py tests/test_mirror_sink.py
git commit -m "feat: add the live mirror sink"
```

---

### Task 3: The shell pump tap

**Files:**
- Modify: `PyAitD/app/shell.py` (parse_args ~line 65; `run()` signature ~line 1247 and the event loop right after `running = event_to_input(...)`; `main()` final `return run(...)`)
- Test: `tests/test_mirror_sink.py` (append)

**Interfaces:**
- Consumes: `MirrorSink` (Task 2); `input_buffer.bindings` (pygame key → `Control`, from `app/ui.py`)
- Produces: `run(game, trace_path=None, session=None, resolver=None, mirror_sink=None)`; `--mirror` CLI flag; sink built in `main()` from `PYAITD_MIRROR_FD` + `PYAITD_MIRROR_PID`

- [ ] **Step 1: Write the failing test** (append to `tests/test_mirror_sink.py`)

```python
class _FakeSink:
    def __init__(self):
        self.events = []

    def key_down(self, name):
        self.events.append(("down", name))

    def key_up(self, name):
        self.events.append(("up", name))


def test_the_pump_tap_forwards_play_keyboard_events_only(
    data_dir, profile, monkeypatch,
):
    import itertools
    from types import SimpleNamespace

    import pygame

    import numpy as np

    import PyAitD.app.shell as main
    from PyAitD.app import ui
    from PyAitD.app.ui import ModalSession
    from PyAitD.engine.effects import OpenInventory
    from PyAitD.engine.game import init_game

    game = init_game(data_dir, profile)
    session = ModalSession()
    sink = _FakeSink()
    frame = np.zeros((200, 320, 3), dtype=np.uint8)

    renderer = SimpleNamespace(
        presented=0, fallback_notice=None,
        window_to_logical=lambda pos: pos, ui_scale=lambda: 1.0,
        scene_thumbnail=lambda: frame,
        present=lambda painter: None, set_options=lambda options: None,
        close=lambda: None,
    )
    ticks = itertools.count(0, 20)
    monkeypatch.setattr(main, "Renderer", lambda *_a, **_k: renderer)
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (frame, []))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(ticks))
    monkeypatch.setattr(main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *args: None))
    monkeypatch.setattr(main.pygame.display, "set_caption", lambda *args: None)
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda *args: None)

    state = {"frame": 0}

    def next_events():
        state["frame"] += 1
        if state["frame"] == 1:
            # PLAY, arrow held then released -> forwarded
            return [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP, repeat=False),
                    pygame.event.Event(pygame.KEYUP, key=pygame.K_UP)]
        if state["frame"] == 2:
            # same key while a modal is open -> silent
            game.open_modal(OpenInventory())
            return [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP, repeat=False),
                    pygame.event.Event(pygame.KEYUP, key=pygame.K_UP)]
        if state["frame"] == 3:
            # an untabled key (Escape) back in PLAY -> sink filters it
            game.close_modal()
            return [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, repeat=False),
                    pygame.event.Event(pygame.KEYUP, key=pygame.K_ESCAPE)]
        return [pygame.event.Event(pygame.QUIT)]

    monkeypatch.setattr(main.pygame.event, "get", next_events)

    pygame.init()
    try:
        assert main.run(game, session=session, mirror_sink=sink) == 0
    finally:
        pygame.quit()
        ui._font.cache_clear()

    assert ("down", "UP") in sink.events
    assert ("up", "UP") in sink.events
    assert sink.events.count(("down", "UP")) == 1, "the modal frame must not forward"
    assert not any(name == "CANCEL" for _, name in sink.events)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_mirror_sink.py -q`
Expected: FAIL — `run() got an unexpected keyword argument 'mirror_sink'`.

- [ ] **Step 3: Implement the tap in `app/shell.py`**

Add `import os` to the imports. In `parse_args`:

```python
    p.add_argument(
        "--mirror", action="store_true",
        help="forward consumed PLAY keyboard input to the live-mirror helper "
             "(set up by tools/compare_original.py)",
    )
```

Change the `run()` signature to
`def run(game, trace_path=None, session=None, resolver=None, mirror_sink=None):`
and insert, directly after `running = event_to_input(event, input_buffer, logical_pos) and running`:

```python
            if (mirror_sink is not None
                    and event.type in (pygame.KEYDOWN, pygame.KEYUP)
                    and not bool(getattr(event, "repeat", False))
                    and game.mode is GameMode.PLAY
                    and game.active_modal is None):
                control = input_buffer.bindings.get(event.key)
                if control is not None:
                    if event.type == pygame.KEYDOWN:
                        mirror_sink.key_down(control.name)
                    else:
                        mirror_sink.key_up(control.name)
```

In `main()`, before the final `return run(...)`:

```python
    mirror_sink = None
    if args.mirror:
        fd = os.environ.get("PYAITD_MIRROR_FD")
        pid = os.environ.get("PYAITD_MIRROR_PID")
        if fd is not None and pid is not None:
            from PyAitD.app.mirror import MirrorSink
            stream = os.fdopen(int(fd), "w", encoding="ascii", buffering=1)
            mirror_sink = MirrorSink(lambda line: stream.write(line + "\n"), int(pid))
    return run(game, args.trace, session=session, mirror_sink=mirror_sink)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_mirror_sink.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the shell group for regressions**

Run: `make test-shell`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add PyAitD/app/shell.py tests/test_mirror_sink.py
git commit -m "feat: tap consumed play keys for the live mirror"
```

---

### Task 4: The Swift helper

**Files:**
- Create: `tools/mirror_helper.swift`

**Interfaces:**
- Produces: stdin protocol `post <keycode> <down|up> <pid>` and `window <needle>` → `pid x y w h` (or `NONE`); prints `DEAD <pid>` once when the target pid is gone.

No headless CI test (GUI/TCC-bound); the deliverable is a compiling binary whose `window` subcommand is smoke-checked manually.

- [ ] **Step 1: Write the helper**

```swift
// SPDX-License-Identifier: GPL-2.0-only
// Live-mirror OS bridge: posts synthetic key events to the DOSBox-X pid
// and reports window geometry. Resident; reads lines from stdin.
import Cocoa
import Darwin

var reportedDead = Set<pid_t>()

func postKey(_ pid: pid_t, _ keyCode: CGKeyCode, _ down: Bool) {
    if kill(pid, 0) != 0 {
        if !reportedDead.contains(pid) {
            reportedDead.insert(pid)
            print("DEAD \(pid)")
            fflush(stdout)
        }
        return
    }
    guard let event = CGEvent(keyboardEventSource: nil, virtualKey: keyCode, keyDown: down)
    else { return }
    event.postToPid(pid)
}

func windows(_ needle: String) -> [(pid_t, CGFloat, CGFloat, CGFloat, CGFloat)] {
    var out: [(pid_t, CGFloat, CGFloat, CGFloat, CGFloat)] = []
    guard let list = CGWindowListCopyWindowInfo(
        [.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID
    ) as? [[String: Any]] else { return out }
    for w in list {
        let name = ((w[kCGWindowName as String] as? String) ?? "").lowercased()
        let owner = ((w[kCGWindowOwnerName as String] as? String) ?? "").lowercased()
        if !needle.isEmpty && !name.contains(needle) && !owner.contains(needle) { continue }
        guard let pid = w[kCGWindowOwnerPID as String] as? pid_t,
              let b = w[kCGWindowBounds as String] as? [String: CGFloat],
              let x = b["X"], let y = b["Y"], let wd = b["Width"], let ht = b["Height"]
        else { continue }
        out.append((pid, x, y, wd, ht))
    }
    return out
}

while let line = readLine() {
    let parts = line.split(separator: " ").map(String.init)
    switch parts.first {
    case "post":
        guard parts.count == 4,
              let keyCode = UInt16(parts[1]),
              let pid = pid_t(parts[3]) else { continue }
        postKey(pid, keyCode, parts[2] == "down")
    case "window":
        let needle = parts.count > 1 ? parts[1].lowercased() : ""
        if let (pid, x, y, wd, ht) = windows(needle).first {
            print("\(pid) \(Int(x)) \(Int(y)) \(Int(wd)) \(Int(ht))")
        } else {
            print("NONE")
        }
    default:
        break
    }
    fflush(stdout)
}
```

- [ ] **Step 2: Compile and smoke-check `window`**

Run:
```bash
mkdir -p tools/.cache && swiftc tools/mirror_helper.swift -o tools/.cache/mirror_helper
echo "window terminal" | tools/.cache/mirror_helper
```
Expected: a line `pid x y w h` for the terminal window (proves enumeration works in this session).

- [ ] **Step 3: Commit**

```bash
git add tools/mirror_helper.swift
git commit -m "feat: add the live mirror CGEvent helper"
```
(`tools/.cache/` stays uncommitted; add it to `.gitignore` in Task 6.)

---

### Task 5: The orchestrator

**Files:**
- Create: `tools/compare_original.py`
- Test: `tests/test_compare_original.py`

**Interfaces:**
- Consumes: helper binary (Task 4), `PyAitD.app.shell.main` (in-process)
- Produces: pure, importable `generate_conf()`, `dosbox_position(our_bounds, gap=24)`, `parse_compare_args(argv)`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_compare_original.py -q`
Expected: FAIL — file not found.

- [ ] **Step 3: Write the orchestrator**

```python
#!/usr/bin/env python3
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
    line = helper.stdout.readline().split()
    if not line or line[0] == "NONE":
        return None
    return tuple(int(v) for v in line)  # pid x y w h


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
    resources = args.data.parent.parent
    if not (resources / "game").is_dir() or not (resources / "GAME.INS").exists():
        sys.exit(f"error: {resources} does not look like the bundle Resources dir")
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python -m pytest tests/test_compare_original.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add tools/compare_original.py tests/test_compare_original.py
git commit -m "feat: add the compare-with-original orchestrator"
```

---

### Task 6: Makefile target, gitignore, full gate

**Files:**
- Modify: `Makefile` (`.PHONY` line + new target near `prove-persistence`)
- Modify: `.gitignore` (add `tools/.cache/`)

- [ ] **Step 1: Add the target**

In `.PHONY`, append `compare`. After the `prove-persistence` target:

```make
compare: install ## Live mirror: original AITD1 in DOSBox-X below the port, PLAY keys forwarded (macOS, needs dosbox-x + Accessibility)
	$(PYTHON) tools/compare_original.py
```

- [ ] **Step 2: Add `tools/.cache/` to `.gitignore`**

- [ ] **Step 3: Run the full gate**

Run: `make test`
Expected: PASS (suite stays headless; compare is never invoked).

- [ ] **Step 4: Commit**

```bash
git add Makefile .gitignore
git commit -m "feat: add the make compare live-mirror target"
```

---

### Task 7: Manual proof run + proof doc

**Files:**
- Create: `docs/compare-original-proof.md`

Not automatable (GUI + Accessibility). The automated evidence is the gate;
the windowed pass is user-attested, same convention as the render proofs.

- [ ] **Step 1: Run `make compare` in a real window session**

Observe: both windows stacked; keyboard-mode play moves both heroes;
mouse mode forwards nothing; Esc in the original stays manual; quitting
the port tears DOSBox-X down.

- [ ] **Step 2: Write the proof doc**

```markdown
# Compare-With-Original Live Mirror Proof

Date: <run date>
Spec: `docs/superpowers/specs/2026-08-30-compare-original-live-mirror-design.md`
Plan: `docs/superpowers/plans/2026-08-30-compare-original-live-mirror.md`

## Automated evidence

- `make test`: PASS (mirror table, sink, pump tap, orchestrator pure parts).
- Spike (2026-08-30): `CGEventPostToPid` delivery proven by before/after
  screenshots of the DOS intro advancing on posted arrows+Return;
  windowed DOSBox-X boot from the bundled data proven; window discovery
  and ScreenCaptureKit capture proven (capture deliberately not shipped).

## Windowed attestation

<record the manual make compare pass per hero, or mark pending>
```

- [ ] **Step 3: Commit**

```bash
git add docs/compare-original-proof.md
git commit -m "docs: record the live mirror proof"
```
