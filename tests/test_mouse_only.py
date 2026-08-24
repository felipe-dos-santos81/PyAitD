# SPDX-License-Identifier: GPL-2.0-only
import itertools
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pygame

from PyAitD.anim_action import HANDLED_ACTIONS, THROW_OBJECT, WAIT_ANIM_THROW
from PyAitD.effects import GameMode
from PyAitD.floor import Floor
from PyAitD.game import AF_ANIMATED, init_game
from PyAitD.interaction import (
    COMBAT_ACTIONS, _finish_take, choose_inventory_action, inventory_actions,
    inventory_items,
)
from PyAitD.playworld import play_tick
from PyAitD.scenario import enter_combat_venue, enter_mouse_combat_fixture
from PyAitD.ui import InputBuffer, ModalLayout, PlayLayout
from PyAitD.mouse_contract import (
    CAPABILITY_ROUTES, COMMAND_MOUSE_CAPABILITIES,
    LEGACY_COMMAND_REPLACEMENTS, MODE_MOUSE_CAPABILITIES, PlayerCapability,
)
from PyAitD.ui import Command


_PURITY_PROBE = r"""
import sys
import PyAitD.mouse_contract
leaked = {"pygame", "moderngl", "PyAitD.ui", "PyAitD.render"} & sys.modules.keys()
raise SystemExit(", ".join(sorted(leaked)) if leaked else 0)
"""


def test_mouse_contract_is_presentation_free():
    result = subprocess.run(
        [sys.executable, "-c", _PURITY_PROBE], capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_every_capability_has_exactly_one_route():
    assert set(CAPABILITY_ROUTES) == set(PlayerCapability)
    assert all(route.gesture in {"left_click", "window_close"}
               for route in CAPABILITY_ROUTES.values())


def test_every_mode_declares_exactly_the_routes_available_in_it():
    assert set(MODE_MOUSE_CAPABILITIES) == set(GameMode)
    for mode in GameMode:
        derived = frozenset(
            capability for capability, route in CAPABILITY_ROUTES.items()
            if mode in route.modes
        )
        assert MODE_MOUSE_CAPABILITIES[mode] == derived


def test_every_command_has_a_mouse_capability_or_reviewed_legacy_decision():
    declared = set(COMMAND_MOUSE_CAPABILITIES) | set(LEGACY_COMMAND_REPLACEMENTS)
    assert declared == set(Command.__members__)
    assert set(COMMAND_MOUSE_CAPABILITIES).isdisjoint(LEGACY_COMMAND_REPLACEMENTS)
    assert LEGACY_COMMAND_REPLACEMENTS["TOGGLE_INPUT_MODE"].replacement is None
    assert "leaves the mouse scheme" in LEGACY_COMMAND_REPLACEMENTS[
        "TOGGLE_INPUT_MODE"
    ].reason


def test_real_data_combat_action_set_is_exactly_32(data_dir):
    armed = set()
    baseline = init_game(data_dir)
    offered = [
        (object_idx, action)
        for object_idx, world in enumerate(baseline.world_objects)
        if world.found_life != -1
        for action in inventory_actions(baseline, object_idx)
    ]
    for object_idx, action in offered:
        game = init_game(data_dir)
        enter_combat_venue(game)
        floor = Floor(data_dir, game.current_floor)
        _finish_take(game, object_idx)
        choose_inventory_action(game, object_idx, action)
        hero = game.actors[game.current_camera_target_actor]
        for _ in range(20):
            if hero.anim_action_type in HANDLED_ACTIONS:
                armed.add(action)
                break
            if game.active_modal is not None:
                break
            play_tick(game, floor, InputBuffer())
    assert armed == set(COMBAT_ACTIONS) == {32}


_FRAME = np.zeros((200, 320, 3), dtype=np.uint8)


class _HeadlessRenderer:
    def __init__(self):
        self.presented = 0

    def window_to_logical(self, pos):
        return pos

    def present(self, _frame):
        self.presented += 1

    def close(self):
        pass


def _left_click(pos):
    return pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, button=1, pos=tuple(pos),
    )


def _run_scripted_mouse(monkeypatch, game, draw_list, next_events):
    import PyAitD.__main__ as main

    renderer = _HeadlessRenderer()
    ticks = itertools.count(0, 20)
    monkeypatch.setattr(main, "Renderer", lambda: renderer)
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (_FRAME, draw_list))
    monkeypatch.setattr(main, "render_active_mode", lambda *args: _FRAME)
    monkeypatch.setattr(main.pygame.event, "get", next_events)
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(ticks))
    monkeypatch.setattr(main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *args: None))
    monkeypatch.setattr(main.pygame.display, "set_caption", lambda *args: None)
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda *args: None)
    assert main.run(game) == 0
    assert renderer.presented > 0


def test_mouse_journey_attic_take_hud_inventory_action(data_dir, monkeypatch):
    game = init_game(data_dir)
    game.timer = 300
    lamp_idx = 13
    actor_idx = game.world_objects[lamp_idx].obj_index
    state = {"step": "lamp", "frames": 0}

    def next_events():
        state["frames"] += 1
        assert state["frames"] < 2500, "attic mouse journey exceeded its budget"
        if state["step"] == "lamp":
            state["step"] = "found"
            return [_left_click((150, 100))]
        if state["step"] == "found" and game.mode is GameMode.FOUND:
            state["step"] = "hud"
            return [_left_click(ModalLayout.FOUND_TAKE.center)]
        if (state["step"] == "hud" and game.mode is GameMode.PLAY
                and lamp_idx in inventory_items(game)):
            state["step"] = "object"
            return [_left_click(PlayLayout.INVENTORY.center)]
        if state["step"] == "object" and game.mode is GameMode.INVENTORY:
            state["step"] = "action"
            # The lamp is row 1, not row 0: the boot scripts grant object 2
            # first, and FITD take() inserts a second item at index 1
            # (main.cpp:3294-3307).
            return [_left_click(ModalLayout.INVENTORY_ROWS[1].center)]
        if state["step"] == "action" and game.mode is GameMode.INVENTORY:
            state["step"] = "quit"
            return [_left_click(ModalLayout.INVENTORY_ROWS[0].center)]
        if (state["step"] == "quit" and game.mode is GameMode.PLAY
                and game.in_hand_table[0] == lamp_idx):
            return [pygame.event.Event(pygame.QUIT)]
        return []

    _run_scripted_mouse(
        monkeypatch, game, [(actor_idx, (100, 60, 200, 160))], next_events,
    )
    assert lamp_idx in inventory_items(game)
    assert game.in_hand_table[0] == lamp_idx


def test_mouse_journey_inventory_attack_publishes_real_throw(data_dir, monkeypatch):
    import PyAitD.playworld as playworld_module

    game = init_game(data_dir)
    # This call is the documented pre-audit fixture boundary. Every player
    # decision after it enters through the synthetic pygame event stream.
    enter_mouse_combat_fixture(game)
    hero_idx = game.current_camera_target_actor
    enemy_idx = game.world_objects[222].obj_index
    hero = game.actors[hero_idx]
    enemy = game.actors[enemy_idx]

    observed = {"wait": False, "flight": False, "hit": None}
    original_gere_frappe = playworld_module.gere_frappe

    def observe_action(g, actor_idx):
        actor = g.actors[actor_idx]
        observed["wait"] |= actor_idx == hero_idx and actor.anim_action_type == WAIT_ANIM_THROW
        observed["flight"] |= actor.anim_action_type == THROW_OBJECT
        result = original_gere_frappe(g, actor_idx)
        thrown_idx = g.world_objects[38].obj_index
        if thrown_idx != -1 and enemy.hit_by == thrown_idx:
            observed["hit"] = (thrown_idx, enemy.hit_force)
        return result

    monkeypatch.setattr(playworld_module, "gere_frappe", observe_action)
    state = {"step": "hud", "frames": 0}

    def next_events():
        state["frames"] += 1
        assert state["frames"] < 500, "combat mouse journey exceeded its budget"
        if state["step"] == "hud":
            state["step"] = "object"
            return [_left_click(PlayLayout.INVENTORY.center)]
        if state["step"] == "object" and game.mode is GameMode.INVENTORY:
            state["step"] = "equip"
            return [_left_click(ModalLayout.INVENTORY_ROWS[0].center)]
        if state["step"] == "equip" and game.mode is GameMode.INVENTORY:
            state["step"] = "attack"
            return [_left_click(ModalLayout.INVENTORY_ROWS[0].center)]
        if (state["step"] == "attack" and game.mode is GameMode.PLAY
                and game.in_hand_table[0] == 38):
            state["step"] = "wait"
            return [_left_click((150, 100))]
        if observed["hit"] is not None:
            return [pygame.event.Event(pygame.QUIT)]
        return []

    _run_scripted_mouse(
        monkeypatch, game, [(enemy_idx, (100, 60, 200, 160))], next_events,
    )
    thrown_idx, force = observed["hit"]
    assert observed["wait"]
    assert observed["flight"]
    assert force == 2
    assert thrown_idx != hero_idx


def test_mouse_journey_game_over_restart_uses_a_left_click(data_dir, monkeypatch):
    import PyAitD.__main__ as main
    from tests.test_combat_journey import _journey_to_game_over

    game, saw_death_life = _journey_to_game_over(data_dir)
    assert saw_death_life
    assert game.mode is GameMode.GAME_OVER
    restarted = []
    real_restart = main.restart_session

    def capture_restart(old_game):
        new_game = real_restart(old_game)
        restarted.append(new_game)
        return new_game

    monkeypatch.setattr(main, "restart_session", capture_restart)
    frames = 0

    def next_events():
        nonlocal frames
        frames += 1
        assert frames < 140, "game-over click did not request restart"
        if restarted:
            return [pygame.event.Event(pygame.QUIT)]
        if frames == 1:
            # The headless harness patches out render_active_mode, the only
            # per-frame ModalSession.reset_for caller, so the modal-entry
            # elapsed reset is deferred to this first click; the 2-second
            # accessibility gate swallows it exactly as designed.
            return [_left_click((160, 100))]
        if frames == 105:
            return [_left_click((160, 100))]
        return []

    _run_scripted_mouse(monkeypatch, game, [], next_events)
    assert len(restarted) == 1
    assert restarted[0].active_modal is None
    assert restarted[0].vars[21] == 20
