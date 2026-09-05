# SPDX-License-Identifier: GPL-2.0-only
"""The example pack's key-and-barricade scene played through the real
shell.run event pump: keyboard mode, walk, take the key from the found
prompt, walk on through the gate and past where the barricade stood."""
import itertools
from types import SimpleNamespace

import pygame
import pytest

from PyAitD.app.ui import ModalSession
from PyAitD.engine.content import load_pack
from PyAitD.engine.script.game import init_game
from PyAitD.engine.script.game.objects import delete_object
from tests.test_controls_golden import _FRAME, _HeadlessRenderer, _key_down, _key_up, _pygame_runtime

pytestmark = [pytest.mark.shell, pytest.mark.journey]

KEY_IDX, BARRICADE_IDX, GATE_IDX = 294, 295, 296


def _script():
    """One list of events per pumped frame (one 20 ms tick each)."""
    frames = []

    def quiet(n):
        frames.extend([[] for _ in range(n)])

    quiet(5)
    frames.append([_key_down(pygame.K_TAB)])      # keyboard mode
    quiet(3)
    frames.append([_key_down(pygame.K_UP)])       # the key is 700 units ahead: prompt around tick 15
    quiet(60)
    frames.append([_key_up(pygame.K_UP)])
    frames.append([_key_down(pygame.K_RIGHT)])    # highlight Take
    frames.append([_key_up(pygame.K_RIGHT)])
    frames.append([_key_down(pygame.K_RETURN)])   # confirm
    frames.append([_key_up(pygame.K_RETURN)])
    quiet(5)
    frames.append([_key_down(pygame.K_UP)])       # on through the gate and past the barricade
    quiet(150)
    frames.append([_key_up(pygame.K_UP)])
    frames.append([pygame.event.Event(pygame.QUIT)])
    return frames


def test_the_scene_plays_through_the_real_loop(data_dir, profile, example_pack_dir, monkeypatch, tmp_path):
    import PyAitD.app.shell as main

    pack = load_pack(example_pack_dir, data_dir, profile)
    game = init_game(data_dir, profile, pack=pack)
    game.num_camera = game.new_num_camera
    game.rng.seed(7)
    delete_object(game, 292)   # the prowler would reach the hero mid-scene
    delete_object(game, 293)
    session = ModalSession(settings_path=tmp_path / "settings.json")
    frames = iter(_script())
    ticks = itertools.count(0, 20)
    seen = set()
    hero_idx = game.current_camera_target_actor
    real_play_tick = main.play_tick

    def spy(current, floor, snapshot):
        result = real_play_tick(current, floor, snapshot)
        seen.update(m.message_id for m in current.messages if m is not None)
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

    texts = game.content.text_ids
    assert game.world_objects[KEY_IDX].found_flag & 0x8000, "the key was not taken"
    assert "has_key" in game.content.flags
    assert texts["A small brass key."] in seen
    assert texts["The barricade gives way."] in seen
    assert texts["Something heavy blocks the doorway."] not in seen
    assert game.world_objects[BARRICADE_IDX].room == -1
    assert game.content_state[GATE_IDX] == {"armed": False, "inside": True}   # disarmed: keeps its last value
    assert game.actors[hero_idx].room_z < -3600, "the hero did not walk past the barricade"
