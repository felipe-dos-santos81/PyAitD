# SPDX-License-Identifier: GPL-2.0-only
import itertools
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pygame
import pytest

from PyAitD.anim_action import HANDLED_ACTIONS, THROW_OBJECT, WAIT_ANIM_THROW
from PyAitD.effects import GameMode
from PyAitD.floor import Floor
from PyAitD.game import AF_ANIMATED, AF_MOVABLE, init_game
from PyAitD.interaction import (
    COMBAT_ACTIONS, _finish_take, choose_inventory_action, inventory_actions,
    inventory_items, PLAYER_PUSH_ANIM,
)
from PyAitD.playworld import play_tick
from PyAitD.scenario import enter_combat_venue, enter_mouse_combat_fixture
from PyAitD.ui import InputBuffer, ModalLayout, PlayLayout
from PyAitD.mouse_contract import (
    ALL_MODES, CAPABILITY_ROUTES, COMMAND_MOUSE_CAPABILITIES,
    KEYBOARD_ONLY_DECISIONS, LEGACY_COMMAND_REPLACEMENTS,
    MODE_MOUSE_CAPABILITIES, MouseRoute, PlayerCapability,
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
    assert all(route.gesture in {"left_click", "left_hold", "window_close"}
               for route in CAPABILITY_ROUTES.values())


def test_hold_push_has_one_declarative_mouse_route():
    route = CAPABILITY_ROUTES[PlayerCapability.HOLD_PUSH_OBJECT]
    assert route == MouseRoute(
        "left_hold", "push-capable scripted actor", frozenset({GameMode.PLAY}),
    )
    assert PlayerCapability.HOLD_PUSH_OBJECT in MODE_MOUSE_CAPABILITIES[GameMode.PLAY]


def test_every_mode_declares_exactly_the_routes_available_in_it():
    assert set(MODE_MOUSE_CAPABILITIES) == set(GameMode)
    for mode in GameMode:
        derived = frozenset(
            capability for capability, route in CAPABILITY_ROUTES.items()
            if mode in route.modes
        )
        assert MODE_MOUSE_CAPABILITIES[mode] == derived


def test_shell_modes_and_the_settings_notice_fulfill_the_mouse_contract():
    # the two shell modes land their pointer routes with the shell rendering
    # task: the derived-route equality above must pin them explicitly
    assert MODE_MOUSE_CAPABILITIES[GameMode.CHARACTER_SELECT] == frozenset({
        PlayerCapability.SELECT_CHARACTER,
        PlayerCapability.CONFIRM_STORY_PAGE,
        PlayerCapability.DISMISS_SETTINGS_ERROR,
        PlayerCapability.QUIT,
    })
    assert MODE_MOUSE_CAPABILITIES[GameMode.SYSTEM_MENU] == frozenset({
        PlayerCapability.MENU_ACTIVATE,
        PlayerCapability.DISMISS_SETTINGS_ERROR,
        PlayerCapability.QUIT,
    })
    # the settings notice is mode-independent: its Dismiss target is one
    # left click away in every mode
    assert CAPABILITY_ROUTES[PlayerCapability.DISMISS_SETTINGS_ERROR].modes == ALL_MODES
    for mode in GameMode:
        assert PlayerCapability.DISMISS_SETTINGS_ERROR in MODE_MOUSE_CAPABILITIES[mode]


def test_remap_capture_is_the_only_keyboard_only_decision():
    assert set(KEYBOARD_ONLY_DECISIONS) == {"REMAP_CAPTURE"}
    decision = KEYBOARD_ONLY_DECISIONS["REMAP_CAPTURE"]
    assert decision.replacement is None
    assert decision.reason == (
        "a keyboard remap must capture one physical key; menu entry, cancel, "
        "and all other configuration decisions remain mouse reachable"
    )


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
    return _left_down(pos)


def _left_down(pos):
    return pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, button=1, pos=tuple(pos),
    )


def _left_up(pos):
    return pygame.event.Event(
        pygame.MOUSEBUTTONUP, button=1, pos=tuple(pos),
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


@pytest.mark.parametrize("hero_id", (0, 1))
def test_mouse_hold_push_wardrobe_release_and_retry(data_dir, monkeypatch, hero_id):
    import PyAitD.__main__ as main

    game = init_game(data_dir, hero=hero_id)
    floor = Floor(data_dir, game.current_floor)
    # Opening LIFE performs an unrelated begin_take(object 2), which publishes
    # Action 0x800 on its first boot tick.  Complete that real bootstrap before
    # measuring the held path; do not hide an Action emitted while held.
    play_tick(game, floor, InputBuffer())
    play_tick(game, floor, InputBuffer())
    assert game.action == game.local_click == 0
    game.timer = 300

    hero = game.actors[game.current_camera_target_actor]
    world = game.world_objects[4]
    wardrobe = game.actors[world.obj_index]
    assert (
        world.obj_index, wardrobe.index_in_world, wardrobe.body_num,
        wardrobe.life, world.stage, world.room, world.found_life,
    ) == (3, 4, 2, 1, 0, 0, -1)
    wardrobe_start = (wardrobe.room_x, wardrobe.room_z)
    state = {
        "phase": "hover", "frames": 0,
        "hero_start": (hero.room_x, hero.room_z), "released_at": None,
        "still_frames": 0, "hover_push_seen": False,
        "drift_cursor_seen": False, "engaged_seen": False,
        "push_anim_seen": False, "movable_seen": False,
        "hero_push_released_at": None, "wardrobe_released_at": None,
    }

    real_play_tick = main.play_tick

    def observe_play_tick(current_game, current_floor, input_buffer):
        held = input_buffer.pointer_held
        if held:
            assert input_buffer.action_held is False
            assert current_game.action == current_game.local_click == 0
            intent = current_game.nav_intent
            assert intent is not None and intent.requires_hold
            assert intent.target_object_idx == 4
            assert world.obj_index == 3
        result = real_play_tick(current_game, current_floor, input_buffer)
        if held:
            assert input_buffer.action_held is False
            assert current_game.action == current_game.local_click == 0
            intent = current_game.nav_intent
            if intent is not None and intent.engaged:
                state["engaged_seen"] = True
                state["push_anim_seen"] |= hero.anim == PLAYER_PUSH_ANIM
        if state["phase"] in {"released", "push_released"}:
            assert (hero.room_x, hero.room_z) == (
                state["released_at"] if state["phase"] == "released"
                else state["hero_push_released_at"]
            )
            if state["phase"] == "push_released":
                assert (wardrobe.room_x, wardrobe.room_z) == (
                    state["wardrobe_released_at"]
                )
        return result

    real_cursor_kind = main._play_cursor_kind

    def observe_cursor_kind(current_game, current_floor, hover, draw_list, input_buffer):
        kind = real_cursor_kind(
            current_game, current_floor, hover, draw_list, input_buffer,
        )
        if state["phase"] == "hover" and hover == (150, 100):
            state["hover_push_seen"] = kind == "push"
        if (input_buffer.pointer_held and hover == (10, 10)
                and current_game.nav_intent is not None):
            assert kind == "push"
            state["drift_cursor_seen"] = True
        return kind

    monkeypatch.setattr(main, "play_tick", observe_play_tick)
    monkeypatch.setattr(main, "_play_cursor_kind", observe_cursor_kind)

    def next_events():
        state["frames"] += 1
        assert state["frames"] < 5000, "wardrobe hold journey exceeded its budget"
        if state["phase"] == "hover":
            if state["hover_push_seen"]:
                state["phase"] = "approaching"
                return [_left_down((150, 100))]
            return [pygame.event.Event(
                pygame.MOUSEMOTION, pos=(150, 100), rel=(0, 0), buttons=(0, 0, 0),
            )]
        if (state["phase"] == "approaching"
                and (hero.room_x, hero.room_z) != state["hero_start"]):
            state["phase"] = "drifted"
            return [pygame.event.Event(
                pygame.MOUSEMOTION, pos=(10, 10), rel=(-140, -90), buttons=(1, 0, 0),
            )]
        if state["phase"] == "drifted" and state["drift_cursor_seen"]:
            state["phase"] = "released"
            state["released_at"] = (hero.room_x, hero.room_z)
            return [_left_up((10, 10))]
        if state["phase"] == "released":
            assert (hero.room_x, hero.room_z) == state["released_at"]
            state["still_frames"] += 1
            if state["still_frames"] == 5:
                state["phase"] = "holding"
                return [_left_down((150, 100))]
        if state["phase"] == "holding":
            state["movable_seen"] |= bool(wardrobe.object_type & AF_MOVABLE)
            assert game.action == game.local_click == 0
            if (wardrobe.room_x, wardrobe.room_z) != wardrobe_start:
                assert game.nav_intent is not None and game.nav_intent.engaged
                assert hero.anim == PLAYER_PUSH_ANIM
                state["phase"] = "push_released"
                state["hero_push_released_at"] = (hero.room_x, hero.room_z)
                state["wardrobe_released_at"] = (wardrobe.room_x, wardrobe.room_z)
                state["still_frames"] = 0
                return [_left_up((10, 10))]
        if state["phase"] == "push_released":
            assert (hero.room_x, hero.room_z) == state["hero_push_released_at"]
            assert (wardrobe.room_x, wardrobe.room_z) == state["wardrobe_released_at"]
            state["still_frames"] += 1
            if state["still_frames"] == 5:
                return [pygame.event.Event(pygame.QUIT)]
        return []

    _run_scripted_mouse(
        monkeypatch, game,
        [(world.obj_index, (100, 60, 200, 160))],
        next_events,
    )
    assert state["hover_push_seen"] is True
    assert state["drift_cursor_seen"] is True
    assert state["engaged_seen"] is True
    assert state["push_anim_seen"] is True
    assert state["movable_seen"] is True
    assert (wardrobe.room_x, wardrobe.room_z) != wardrobe_start
    assert game.nav_intent is None
    assert game.action == game.local_click == game.local_joyd == 0


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
