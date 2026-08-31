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
    from PyAitD.engine.script.effects import InputMode, OpenInventory
    from PyAitD.engine.script.game import init_game

    game = init_game(data_dir, profile)
    game.input_mode = InputMode.KEYBOARD
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


def test_the_pump_tap_stays_silent_in_mouse_mode(
    data_dir, profile, monkeypatch,
):
    # MOUSE is the default route and consumes no keyboard movement, so the
    # mirror must stay silent there (spec: "stays silent in mouse mode"):
    # forwarding arrow presses would move the original while ours stands
    # still.
    import itertools
    from types import SimpleNamespace

    import pygame

    import numpy as np

    import PyAitD.app.shell as main
    from PyAitD.app import ui
    from PyAitD.app.ui import ModalSession
    from PyAitD.engine.script.effects import InputMode
    from PyAitD.engine.script.game import init_game

    game = init_game(data_dir, profile)
    game.input_mode = InputMode.MOUSE
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
            # PLAY + mouse mode, arrow held then released -> silent
            return [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP, repeat=False),
                    pygame.event.Event(pygame.KEYUP, key=pygame.K_UP)]
        return [pygame.event.Event(pygame.QUIT)]

    monkeypatch.setattr(main.pygame.event, "get", next_events)

    pygame.init()
    try:
        assert main.run(game, session=session, mirror_sink=sink) == 0
    finally:
        pygame.quit()
        ui._font.cache_clear()

    assert sink.events == []
