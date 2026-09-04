# SPDX-License-Identifier: GPL-2.0-only
"""The controls refactor's invariance golden.

A scripted event stream (keys, presses, drags, a double press, focus loss,
the system menu) replays through the real shell.run pump against the real
attic, and the per-tick engine input plus the hero's motion are pinned.
Recorded on the code before the refactor; every task of the refactor must
keep it byte-identical. Re-record only with PYAITD_RECORD_GOLDEN=1 and a
reason in the commit message.
"""
import contextlib
import itertools
import json
import os
import pathlib
from types import SimpleNamespace

import numpy as np
import pygame
import pytest

from PyAitD.engine.script.game import init_game
from PyAitD.app.ui import ModalSession

pytestmark = [pytest.mark.shell, pytest.mark.journey]

GOLDEN = pathlib.Path(__file__).parent / "golden" / "controls_events.json"
_FRAME = np.zeros((200, 320, 3), dtype=np.uint8)


class _HeadlessRenderer:
    def __init__(self, *_args, **_kwargs):
        self.presented = 0
        self.fallback_notice = None

    def window_to_logical(self, pos):
        return pos

    def ui_scale(self):
        return 1.0

    def scene_thumbnail(self):
        return _FRAME

    def present(self, _frame):
        self.presented += 1

    def set_options(self, options):
        self.options = options

    def close(self):
        pass


@contextlib.contextmanager
def _pygame_runtime():
    from PyAitD.app import ui
    pygame.init()
    try:
        yield
    finally:
        pygame.quit()
        ui._font.cache_clear()


def _key_down(code):
    return pygame.event.Event(pygame.KEYDOWN, key=code, repeat=False)


def _key_up(code):
    return pygame.event.Event(pygame.KEYUP, key=code)


def _motion(pos, touch=False):
    return pygame.event.Event(pygame.MOUSEMOTION, pos=pos, touch=touch)


def _down(pos, touch=False):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos, touch=touch)


def _up(touch=False):
    return pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, touch=touch)


def _script():
    """One list of events per pumped frame; [] is a frame with no events.
    One frame is one 20 ms tick, so 25 frames is the double-press window."""
    frames = []

    def quiet(n):
        frames.extend([[] for _ in range(n)])

    quiet(5)
    # keyboard: toggle, walk forward, action, walk left, toggle back
    frames.append([_key_down(pygame.K_TAB)])
    quiet(3)
    frames.append([_key_down(pygame.K_UP)])
    quiet(40)
    frames.append([_key_down(pygame.K_SPACE)])
    frames.append([_key_up(pygame.K_SPACE)])
    quiet(10)
    frames.append([_key_up(pygame.K_UP), _key_down(pygame.K_LEFT)])
    quiet(20)
    frames.append([_key_up(pygame.K_LEFT)])
    frames.append([_key_down(pygame.K_TAB)])
    quiet(5)
    # mouse: hold-follow with a drag, release
    frames.append([_motion((160, 150))])
    frames.append([_down((160, 150))])
    quiet(40)
    frames.append([_motion((200, 150))])
    quiet(40)
    frames.append([_motion((60, 120))])
    quiet(30)
    frames.append([_up()])
    quiet(10)
    # double press: run, and resume the same destination
    frames.append([_down((200, 150))])
    frames.append([_up()])
    quiet(3)
    frames.append([_down((201, 150))])
    quiet(60)
    frames.append([_motion((240, 140))])
    quiet(30)
    frames.append([_up()])
    quiet(10)
    # a press far from any floor: steer, then focus loss ends the hold.
    # (10, 10) sits inside PlayLayout.INVENTORY_HIT and opens the inventory
    # instead, so this uses the opposite corner, which is on no HUD hotspot.
    frames.append([_down((310, 195))])
    quiet(20)
    frames.append([pygame.event.Event(pygame.WINDOWFOCUSLOST)])
    quiet(5)
    frames.append([pygame.event.Event(pygame.WINDOWFOCUSGAINED)])
    quiet(5)
    # a touch-origin press, then the system menu opens and closes on Escape
    frames.append([_down((160, 150), touch=True)])
    quiet(20)
    frames.append([_up(touch=True)])
    frames.append([_key_down(pygame.K_ESCAPE)])
    quiet(5)
    frames.append([_key_down(pygame.K_ESCAPE)])
    quiet(20)
    frames.append([pygame.event.Event(pygame.QUIT)])
    return frames


def _intent_summary(game):
    intent = game.nav_intent
    if intent is None:
        return None
    return [intent.dest_x, intent.dest_z, intent.room, intent.target_object_idx,
            bool(intent.requires_hold), bool(intent.run), bool(intent.steering),
            bool(intent.engaged)]


def _record(data_dir, profile, monkeypatch, tmp_path):
    import PyAitD.app.shell as main

    game = init_game(data_dir, profile)
    game.num_camera = game.new_num_camera
    game.rng.seed(7)
    session = ModalSession(settings_path=tmp_path / "settings.json")
    frames = iter(_script())
    ticks = itertools.count(0, 20)
    rows = []
    real_play_tick = main.play_tick

    def spy(current, floor, snapshot):
        hero_idx = current.current_camera_target_actor
        result = real_play_tick(current, floor, snapshot)
        hero = current.actors[hero_idx]
        rows.append([
            current.timer, current.input_mode.name,
            current.local_joyd, current.local_click, current.action,
            hero.room, hero.room_x, hero.room_z, hero.beta,
            hero.anim, hero.track_mode, _intent_summary(current),
        ])
        return result

    renderer = _HeadlessRenderer()
    monkeypatch.setattr(main, "Renderer", lambda *_a, **_k: renderer)
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (_FRAME, []))
    monkeypatch.setattr(main, "play_tick", spy)
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(frames))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(ticks))
    monkeypatch.setattr(main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *args: None))
    monkeypatch.setattr(main.pygame.display, "set_caption", lambda *args: None)
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda *args: None)
    with _pygame_runtime():
        assert main.run(game, session=session) == 0
    assert renderer.presented > 0
    return {"ticks": rows}


def test_the_scripted_event_stream_replays_identically(data_dir, profile, monkeypatch, tmp_path):
    recorded = _record(data_dir, profile, monkeypatch, tmp_path)
    assert len(recorded["ticks"]) > 300, "the script did not reach the play loop"
    if os.environ.get("PYAITD_RECORD_GOLDEN") == "1":
        GOLDEN.write_text(json.dumps(recorded, indent=0) + "\n")
    expected = json.loads(GOLDEN.read_text())
    assert recorded == expected, (
        "the controls refactor changed what the engine saw or how the hero moved; "
        "diff tests/golden/controls_events.json against a re-record to find the tick"
    )
