# SPDX-License-Identifier: GPL-2.0-only
import itertools
from types import SimpleNamespace

import numpy as np
import pygame
import pytest

from PyAitD.engine.actor.anim_action import (
    FRAPPE_OK, HANDLED_ACTIONS, WAIT_FRAPPE_ANIM, WAIT_FRAPPE_FRAME,
)
from PyAitD.render.asset_resolver import AssetResolver
from PyAitD.engine.script.effects import GameMode, NavIntent
from PyAitD.engine.data.floor import Floor
from PyAitD.engine.script.game import AF_ANIMATED, AF_MOVABLE, init_game
from PyAitD.engine.script.interaction import (
    _finish_take, choose_inventory_action, inventory_actions, inventory_items,
)
from PyAitD.engine.script.playworld import IDLE, play_tick
from PyAitD.games.aitd1.scenario import enter_combat_venue, enter_mouse_combat_fixture
from PyAitD.app.ui import ModalLayout, PlayLayout
from PyAitD.games.aitd1.mouse_contract import (
    ALL_MODES, CAPABILITY_ROUTES, COMMAND_MOUSE_CAPABILITIES,
    KEYBOARD_ONLY_DECISIONS, LEGACY_COMMAND_REPLACEMENTS,
    MODE_MOUSE_CAPABILITIES, MOUSE_INTERACTION_DECISIONS, MouseRoute,
    PlayerCapability,
)
from PyAitD.app.controls.actions import KEY_BINDABLE
from tests.conftest import painter_from_frame

pytestmark = [pytest.mark.shell, pytest.mark.journey]


def test_every_capability_has_exactly_one_route():
    assert set(CAPABILITY_ROUTES) == set(PlayerCapability)
    assert all(
        route.gesture in {"left_click", "left_hold", "window_close"}
        for route in CAPABILITY_ROUTES.values()
    )


def test_contract_declares_only_the_reviewed_primary_button_gestures():
    hold_capabilities = {
        capability
        for capability, route in CAPABILITY_ROUTES.items()
        if route.gesture == "left_hold"
    }
    # walk and interact became held pointer follow routes
    # (2026-08-26-held-pointer-follow-design.md); push was already held
    assert hold_capabilities == {
        PlayerCapability.WALK_TO_POINT,
        PlayerCapability.INTERACT_WITH_OBJECT,
        PlayerCapability.HOLD_PUSH_OBJECT,
    }
    assert all(
        forbidden not in route.gesture
        for forbidden in ("double_click", "drag", "chord")
        for route in CAPABILITY_ROUTES.values()
    )


def test_contract_declares_hover_touch_and_held_follow_decisions():
    assert set(MOUSE_INTERACTION_DECISIONS) == {
        "hover_preview", "touch_origin", "held_pointer_follow",
        "held_double_press_run", "unreachable_pixel_steers",
    }
    assert MOUSE_INTERACTION_DECISIONS["hover_preview"].decision == "presenter_only"
    assert MOUSE_INTERACTION_DECISIONS["touch_origin"].decision == "same_primary_button_route"
    assert MOUSE_INTERACTION_DECISIONS["held_pointer_follow"].decision == "retarget_on_pointer_motion"
    assert MOUSE_INTERACTION_DECISIONS["held_double_press_run"].decision == "speed_not_capability"
    assert all(decision.reason for decision in MOUSE_INTERACTION_DECISIONS.values())


def test_running_adds_no_capability_and_so_no_double_press_gesture():
    # The forbidden-gesture rule (no double_click, drag or chord) exists so no
    # operation is locked behind a gesture a one-button or Accessibility
    # Keyboard user cannot make. Run is a speed, not an operation: it earns a
    # recorded decision rather than a PlayerCapability, and WALK_TO_POINT
    # keeps its plain left_hold, which still reaches every destination.
    assert not any(
        "RUN" in capability.name for capability in PlayerCapability
    ), "running is a speed, not a capability"
    assert CAPABILITY_ROUTES[PlayerCapability.WALK_TO_POINT].gesture == "left_hold"


def test_walk_and_interact_are_held_pointer_follow_routes():
    # "anywhere on screen", not "walkable floor": a pixel that names no
    # reachable place steers along its bearing rather than refusing
    assert CAPABILITY_ROUTES[PlayerCapability.WALK_TO_POINT] == MouseRoute(
        "left_hold", "anywhere on screen", frozenset({GameMode.PLAY}),
    )
    assert CAPABILITY_ROUTES[PlayerCapability.INTERACT_WITH_OBJECT] == MouseRoute(
        "left_hold", "interactable actor", frozenset({GameMode.PLAY}),
    )
    # the press-only PLAY routes stay single clicks
    assert CAPABILITY_ROUTES[PlayerCapability.ATTACK_TARGET].gesture == "left_click"
    assert CAPABILITY_ROUTES[PlayerCapability.OPEN_INVENTORY].gesture == "left_click"
    for name in ("UP", "DOWN", "LEFT", "RIGHT"):
        decision = LEGACY_COMMAND_REPLACEMENTS[name]
        assert decision.replacement is PlayerCapability.WALK_TO_POINT
        assert "held pointer follow" in decision.reason


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
    assert MODE_MOUSE_CAPABILITIES[GameMode.TITLE] == frozenset({
        PlayerCapability.ADVANCE_TITLE,
        PlayerCapability.DISMISS_SETTINGS_ERROR,
        PlayerCapability.QUIT,
    })
    assert MODE_MOUSE_CAPABILITIES[GameMode.STARTUP_MENU] == frozenset({
        PlayerCapability.STARTUP_MENU_ACTIVATE,
        PlayerCapability.DISMISS_SETTINGS_ERROR,
        PlayerCapability.QUIT,
    })
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
        PlayerCapability.PICK_REMAP_KEY,
        PlayerCapability.SAVE_MANUAL,
        PlayerCapability.LOAD_MANUAL,
        PlayerCapability.LOAD_QUICK,
        PlayerCapability.QUICK_SAVE,
        PlayerCapability.PERSISTENCE_BACK,
        PlayerCapability.DISMISS_SETTINGS_ERROR,
        PlayerCapability.QUIT,
    })
    # the settings notice is mode-independent: its Dismiss target is one
    # left click away in every mode
    assert CAPABILITY_ROUTES[PlayerCapability.DISMISS_SETTINGS_ERROR].modes == ALL_MODES
    for mode in GameMode:
        assert PlayerCapability.DISMISS_SETTINGS_ERROR in MODE_MOUSE_CAPABILITIES[mode]
    assert MODE_MOUSE_CAPABILITIES[GameMode.CUTSCENE_END] == frozenset({
        PlayerCapability.SKIP_CUTSCENE,
        PlayerCapability.DISMISS_SETTINGS_ERROR,
        PlayerCapability.QUIT,
    })
    assert PlayerCapability.SKIP_CUTSCENE in MODE_MOUSE_CAPABILITIES[GameMode.PLAY]


def test_every_persistence_decision_is_one_forgiving_left_click():
    # M4a2: save, load, quick save and both Back rows are single primary-
    # button clicks inside the system menu, so a touch-origin press reaches
    # every persistence decision the same way a physical click does.
    routes = {
        capability: CAPABILITY_ROUTES[capability]
        for capability in (
            PlayerCapability.SAVE_MANUAL,
            PlayerCapability.LOAD_MANUAL,
            PlayerCapability.LOAD_QUICK,
            PlayerCapability.QUICK_SAVE,
            PlayerCapability.PERSISTENCE_BACK,
        )
    }
    assert all(route.gesture == "left_click" for route in routes.values())
    assert all(route.modes == frozenset({GameMode.SYSTEM_MENU}) for route in routes.values())
    assert all(route.target for route in routes.values())
    for capability in routes:
        assert capability in MODE_MOUSE_CAPABILITIES[GameMode.SYSTEM_MENU]


def test_no_operation_remains_keyboard_only():
    # the remap key picker closed the last keyboard-only decision
    assert KEYBOARD_ONLY_DECISIONS == {}
    route = CAPABILITY_ROUTES[PlayerCapability.PICK_REMAP_KEY]
    assert route.gesture == "left_click"
    assert route.target == "key-picker cell or Cancel button"
    assert route.modes == frozenset({GameMode.SYSTEM_MENU})


def test_every_command_has_a_mouse_capability_or_reviewed_legacy_decision():
    # mouse_contract.py's dict keys are frozen to the pre-refactor naming;
    # ACCEPT and OPEN_INVENTORY are what Action.ACTION and
    # Action.INVENTORY_CONFIRM used to be called, so they translate back for
    # a like-for-like comparison against the key-bindable half of Action.
    legacy_names = {"ACTION": "ACCEPT", "INVENTORY_CONFIRM": "OPEN_INVENTORY"}
    declared = set(COMMAND_MOUSE_CAPABILITIES) | set(LEGACY_COMMAND_REPLACEMENTS)
    assert declared == {legacy_names.get(action.name, action.name) for action in KEY_BINDABLE}
    assert set(COMMAND_MOUSE_CAPABILITIES).isdisjoint(LEGACY_COMMAND_REPLACEMENTS)
    assert all(decision.reason for decision in LEGACY_COMMAND_REPLACEMENTS.values())
    assert LEGACY_COMMAND_REPLACEMENTS["TOGGLE_INPUT_MODE"].replacement is None
    assert "leaves the mouse scheme" in LEGACY_COMMAND_REPLACEMENTS[
        "TOGGLE_INPUT_MODE"
    ].reason


def test_real_data_combat_action_set_is_exactly_32(data_dir, profile):
    armed = set()
    baseline = init_game(data_dir, profile)
    offered = [
        (object_idx, action)
        for object_idx, world in enumerate(baseline.world_objects)
        if world.found_life != -1
        for action in inventory_actions(baseline, object_idx)
    ]
    for object_idx, action in offered:
        game = init_game(data_dir, profile)
        enter_combat_venue(game)
        floor = Floor(data_dir, game.current_floor, profile)
        _finish_take(game, object_idx)
        choose_inventory_action(game, object_idx, action)
        hero = game.actors[game.current_camera_target_actor]
        for _ in range(20):
            if hero.anim_action_type in HANDLED_ACTIONS:
                armed.add(action)
                break
            if game.active_modal is not None:
                break
            play_tick(game, floor, IDLE)
    assert armed == set(profile.combat_action_text_ids) == {32}


_FRAME = np.zeros((200, 320, 3), dtype=np.uint8)


class _HeadlessRenderer:
    # _scene_frame reads shadows off renderer.options (task-5 fix-1):
    # a stub without one raises before build_frame ever runs.
    options = SimpleNamespace(shadows="soft")

    def __init__(self, *_args, **_kwargs):
        self.presented = 0
        self.fallback_notice = None

    def window_to_logical(self, pos):
        return pos

    def present(self, _frame):
        self.presented += 1

    def compose_scene(self, *_args):
        return _FRAME

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


def _effective_position(actor):
    return (
        actor.room_x + actor.step_x,
        actor.room_y + actor.step_y,
        actor.room_z + actor.step_z,
    )


def _run_scripted_mouse(monkeypatch, game, draw_list, next_events):
    import PyAitD.app.shell as main

    renderer = _HeadlessRenderer()
    ticks = itertools.count(0, 20)
    monkeypatch.setattr(main, "Renderer", lambda *_a, **_k: renderer)
    if draw_list is not None:
        monkeypatch.setattr(main, "_scene_frame", lambda *args: (_FRAME, draw_list))
    monkeypatch.setattr(main, "render_active_mode", lambda *args: painter_from_frame(_FRAME))
    monkeypatch.setattr(main.pygame.event, "get", next_events)
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(ticks))
    monkeypatch.setattr(main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *args: None))
    monkeypatch.setattr(main.pygame.display, "set_caption", lambda *args: None)
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda *args: None)
    assert main.run(game) == 0
    assert renderer.presented > 0


@pytest.mark.parametrize("hero_id", (0, 1))
def test_mouse_hold_push_wardrobe_release_and_retry(data_dir, profile, monkeypatch, hero_id):
    import PyAitD.app.shell as main

    game = init_game(data_dir, profile, hero=hero_id)
    floor = Floor(data_dir, game.current_floor, profile)
    # Opening LIFE performs an unrelated begin_take(object 2), which publishes
    # Action 0x800 on its first boot tick.  Complete that real bootstrap before
    # measuring the held path; do not hide an Action emitted while held.
    play_tick(game, floor, IDLE)
    play_tick(game, floor, IDLE)
    assert game.action == game.local_click == 0
    game.timer = 300

    hero = game.actors[game.current_camera_target_actor]
    world = game.world_objects[4]
    wardrobe = game.actors[world.obj_index]
    assert (
        world.obj_index, wardrobe.index_in_world, wardrobe.body_num,
        wardrobe.life, world.stage, world.room, world.found_life,
    ) == (3, 4, 2, 1, 0, 0, -1)
    wardrobe_start = _effective_position(wardrobe)
    state = {
        "phase": "hover", "frames": 0,
        "hero_start": _effective_position(hero),
        "approach_release": None,
        "still_frames": 0, "hover_push_seen": False,
        "drift_cursor_seen": False, "engaged_samples": 0,
        "movable_seen": False,
        "push_release": None,
        "wardrobe_released_at": None, "wardrobe_released_zv": None,
    }

    real_play_tick = main.play_tick

    def capture_release():
        pending = (hero.step_x, hero.step_z)
        assert pending != (0, 0), "release fixture must carry an X/Z pending step"
        base = (hero.room_x, hero.room_z)
        return {
            "effective": _effective_position(hero),
            "zv": tuple(hero.zv),
            "base": base,
            "pending": pending,
            "committed": (base[0] + pending[0], base[1] + pending[1]),
            "ticks": 0,
        }

    def observe_play_tick(current_game, current_floor, input_buffer):
        held = input_buffer.pointer_held
        if held:
            assert input_buffer.action_held is False
            assert current_game.action == current_game.local_click == 0
            intent = current_game.nav_intent
            assert intent is not None and intent.requires_hold
            assert intent.target_object_idx == 4
            assert world.obj_index == 3
        release = None
        if state["phase"] in {"released", "push_released"}:
            release = (
                state["approach_release"] if state["phase"] == "released"
                else state["push_release"]
            )
            assert _effective_position(hero) == release["effective"]
            assert tuple(hero.zv) == release["zv"]
            if release["ticks"] == 0:
                assert (hero.room_x, hero.room_z) == release["base"]
                assert (hero.step_x, hero.step_z) == release["pending"]
            else:
                assert (hero.room_x, hero.room_z) == release["committed"]
                assert (hero.step_x, hero.step_z) == (0, 0)
        result = real_play_tick(current_game, current_floor, input_buffer)
        if held:
            assert input_buffer.action_held is False
            assert current_game.action == current_game.local_click == 0
            intent = current_game.nav_intent
            if intent is not None and intent.engaged:
                assert hero.anim == profile.player_push_anim
                state["engaged_samples"] += 1
        if state["phase"] in {"released", "push_released"}:
            release["ticks"] += 1
            assert _effective_position(hero) == release["effective"]
            assert tuple(hero.zv) == release["zv"]
            assert (hero.room_x, hero.room_z) == release["committed"]
            assert (hero.step_x, hero.step_y, hero.step_z) == (0, 0, 0)
            if state["phase"] == "push_released":
                assert _effective_position(wardrobe) == state["wardrobe_released_at"]
                assert tuple(wardrobe.zv) == state["wardrobe_released_zv"]
        return result

    # _render_play_cursor calls _play_cursor_state directly (kind, payload
    # together, one resolve), not _play_cursor_kind -- so the observer sits
    # on _play_cursor_state and unwraps the tuple; every assertion below is
    # unchanged from when this observed _play_cursor_kind's return value.
    real_cursor_state = main._play_cursor_state

    def observe_cursor_state(current_game, current_floor, hover, draw_list, input_buffer):
        kind, payload = real_cursor_state(
            current_game, current_floor, hover, draw_list, input_buffer,
        )
        if state["phase"] == "hover" and hover == (150, 100):
            state["hover_push_seen"] = kind == "push"
        if (input_buffer.pointer.held and hover == (10, 10)
                and current_game.nav_intent is not None):
            assert kind == "push"
            state["drift_cursor_seen"] = True
        return kind, payload

    monkeypatch.setattr(main, "play_tick", observe_play_tick)
    monkeypatch.setattr(main, "_play_cursor_state", observe_cursor_state)

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
                and _effective_position(hero) != state["hero_start"]):
            assert game.nav_intent is not None and not game.nav_intent.engaged
            state["phase"] = "drifted"
            return [pygame.event.Event(
                pygame.MOUSEMOTION, pos=(10, 10), rel=(-140, -90), buttons=(1, 0, 0),
            )]
        if state["phase"] == "drifted" and state["drift_cursor_seen"]:
            assert game.nav_intent is not None and not game.nav_intent.engaged
            state["approach_release"] = capture_release()
            state["phase"] = "released"
            return [_left_up((10, 10))]
        if state["phase"] == "released":
            assert _effective_position(hero) == state["approach_release"]["effective"]
            assert tuple(hero.zv) == state["approach_release"]["zv"]
            state["still_frames"] += 1
            if state["still_frames"] == 5:
                state["phase"] = "holding"
                return [_left_down((150, 100))]
        if state["phase"] == "holding":
            state["movable_seen"] |= bool(wardrobe.object_type & AF_MOVABLE)
            assert game.action == game.local_click == 0
            if (_effective_position(wardrobe) != wardrobe_start
                    and state["engaged_samples"] >= 3):
                assert game.nav_intent is not None and game.nav_intent.engaged
                assert hero.anim == profile.player_push_anim
                state["push_release"] = capture_release()
                state["phase"] = "push_released"
                state["wardrobe_released_at"] = _effective_position(wardrobe)
                state["wardrobe_released_zv"] = tuple(wardrobe.zv)
                state["still_frames"] = 0
                return [_left_up((10, 10))]
        if state["phase"] == "push_released":
            assert _effective_position(hero) == state["push_release"]["effective"]
            assert tuple(hero.zv) == state["push_release"]["zv"]
            assert _effective_position(wardrobe) == state["wardrobe_released_at"]
            assert tuple(wardrobe.zv) == state["wardrobe_released_zv"]
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
    assert state["engaged_samples"] >= 3
    assert state["movable_seen"] is True
    assert state["approach_release"]["ticks"] >= 2
    assert state["push_release"]["ticks"] >= 2
    assert _effective_position(wardrobe) != wardrobe_start
    assert game.nav_intent is None
    assert game.action == game.local_click == game.local_joyd == 0


def test_mouse_journey_attic_take_by_held_pointer_follow(data_dir, profile, monkeypatch):
    # Press on bare floor, then drag the held pointer onto the lamp: the
    # per-frame follow must retarget from the floor walk to the lamp's
    # approach and use it once, with no second press. Modal clicks release
    # in the same pump so no stray follow starts when PLAY resumes.
    from PyAitD.app.shell import resolve_play_click

    lamp_idx = 13
    lamp_box = (100, 60, 200, 160)
    probe = init_game(data_dir, profile)
    probe.num_camera = probe.new_num_camera
    probe_floor = Floor(data_dir, probe.current_floor, profile)
    actor_idx = probe.world_objects[lamp_idx].obj_index
    draw_list = [(actor_idx, lamp_box)]
    # the first screen point, scanning the bottom of the frame upward, that
    # the real resolver reports as walkable floor with the lamp box in place
    floor_pos = next(
        pos
        for pos in ((x, y) for y in range(199, 100, -10) for x in range(10, 320, 20))
        if resolve_play_click(probe, probe_floor, pos, draw_list)[0] == "walk"
    )
    assert not (lamp_box[0] <= floor_pos[0] < lamp_box[2]
                and lamp_box[1] <= floor_pos[1] < lamp_box[3])

    game = init_game(data_dir, profile)
    game.timer = 300
    hero = game.actors[game.current_camera_target_actor]
    state = {
        "step": "press", "frames": 0, "hero_start": _effective_position(hero),
        "floor_walk_seen": False, "lamp_intent_seen": False,
    }

    def click(pos):
        return [_left_down(pos), _left_up(pos)]

    def next_events():
        state["frames"] += 1
        assert state["frames"] < 2500, "held attic journey exceeded its budget"
        intent = game.nav_intent
        if state["step"] == "press":
            state["step"] = "drag"
            return [_left_down(floor_pos)]
        if state["step"] == "drag":
            if intent is not None and intent.target_object_idx == -1:
                state["floor_walk_seen"] = True
                state["step"] = "lamp"
                return [pygame.event.Event(
                    pygame.MOUSEMOTION, pos=(150, 100),
                    rel=(150 - floor_pos[0], 100 - floor_pos[1]), buttons=(1, 0, 0),
                )]
            return []
        if state["step"] == "lamp":
            if intent is not None and intent.target_object_idx == lamp_idx:
                state["lamp_intent_seen"] = True
            if game.mode is GameMode.FOUND:
                state["step"] = "found"
                return [_left_up((150, 100))]
            return []
        if state["step"] == "found" and game.mode is GameMode.FOUND:
            state["step"] = "hud"
            return click(ModalLayout.FOUND_TAKE.center)
        if (state["step"] == "hud" and game.mode is GameMode.PLAY
                and lamp_idx in inventory_items(game)):
            assert game.nav_intent is None, "no follow may start from a modal click"
            state["step"] = "object"
            return click(PlayLayout.INVENTORY.center)
        if state["step"] == "object" and game.mode is GameMode.INVENTORY:
            state["step"] = "action"
            # The lamp is row 1, not row 0: the boot scripts grant object 2
            # first, and FITD take() inserts a second item at index 1
            # (main.cpp:3294-3307).
            return click(ModalLayout.INVENTORY_ROWS[1].center)
        if state["step"] == "action" and game.mode is GameMode.INVENTORY:
            state["step"] = "quit"
            return click(ModalLayout.INVENTORY_ROWS[0].center)
        if (state["step"] == "quit" and game.mode is GameMode.PLAY
                and game.in_hand_table[0] == lamp_idx):
            return [pygame.event.Event(pygame.QUIT)]
        return []

    _run_scripted_mouse(monkeypatch, game, draw_list, next_events)
    assert state["floor_walk_seen"] is True
    assert state["lamp_intent_seen"] is True, "the follow never retargeted onto the lamp"
    assert _effective_position(hero) != state["hero_start"]
    assert lamp_idx in inventory_items(game)
    assert game.in_hand_table[0] == lamp_idx
    assert game.nav_intent is None


def test_mouse_combat_fixture_has_a_real_visible_attack_target_after_equip(data_dir, profile):
    import PyAitD.app.shell as main

    game = init_game(data_dir, profile)
    enter_mouse_combat_fixture(game)
    choose_inventory_action(game, 38, 23)
    game.num_camera = game.new_num_camera
    floor = Floor(data_dir, game.current_floor, profile)
    enemy_idx = game.world_objects[222].obj_index

    _frame, draw_list = main._scene_frame(
        game, floor, _HeadlessRenderer(), AssetResolver(game.assets),
    )
    target_box = next(box for index, box in draw_list if index == enemy_idx)
    x0, y0, x1, y1 = target_box
    assert x1 > x0 and y1 > y0, (
        f"mouse combat enemy has no visible target: {target_box}"
    )
    attack_point = ((x0 + x1) // 2, (y0 + y1) // 2)
    assert main.resolve_play_click(
        game, floor, attack_point, draw_list,
    ) == ("attack", enemy_idx)


def test_mouse_journey_one_click_attack_swings_the_held_saber(data_dir, profile, monkeypatch):
    """One click on a visible enemy performs object 38's own melee strike.

    ENGLISH.PAK text 32 is "Throw", so routing the click through the inventory
    action dropped the saber on the floor. FITD mainLoop.cpp:87-101 instead
    turns held action input into action 0x2000 and runs the in-hand object's
    LIFE, which is what arms melee animation 41. The click therefore latches a
    bounded native-input burst; the player never holds or times a button.
    """
    import PyAitD.app.shell as main
    import PyAitD.engine.script.playworld as playworld_module

    game = init_game(data_dir, profile)
    # This call is the documented pre-audit fixture boundary. Every player
    # decision after it enters through the synthetic pygame event stream.
    enter_mouse_combat_fixture(game)
    hero_idx = game.current_camera_target_actor
    enemy_idx = game.world_objects[222].obj_index
    enemy = game.actors[enemy_idx]
    floor = Floor(data_dir, game.current_floor, profile)
    geometry_renderer = _HeadlessRenderer()

    observed = {"states": set(), "hit": None, "target_box": None}
    original_gere_frappe = playworld_module.passes.gere_frappe

    def observe_action(g, actor_idx):
        actor = g.actors[actor_idx]
        if actor_idx == hero_idx:
            observed["states"].add(actor.anim_action_type)
        result = original_gere_frappe(g, actor_idx)
        if enemy.hit_by == hero_idx:
            observed["hit"] = (enemy.hit_by, enemy.hit_force)
        return result

    monkeypatch.setattr(playworld_module.passes, "gere_frappe", observe_action)
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
            _frame, draw_list = main._scene_frame(
                game, floor, geometry_renderer, AssetResolver(game.assets),
            )
            target_box = next(box for index, box in draw_list if index == enemy_idx)
            x0, y0, x1, y1 = target_box
            assert x1 > x0 and y1 > y0, (
                f"mouse combat enemy has no visible target: {target_box}"
            )
            attack_point = ((x0 + x1) // 2, (y0 + y1) // 2)
            assert main.resolve_play_click(
                game, floor, attack_point, draw_list,
            ) == ("attack", enemy_idx)
            observed["target_box"] = target_box
            state["step"] = "swing"
            # exactly one press/release pair: no hold, no repeat
            return [_left_click(attack_point)]
        if observed["hit"] is not None:
            return [pygame.event.Event(pygame.QUIT)]
        return []

    _run_scripted_mouse(monkeypatch, game, None, next_events)

    hitter, force = observed["hit"]
    assert observed["target_box"] is not None
    assert {WAIT_FRAPPE_ANIM, WAIT_FRAPPE_FRAME, FRAPPE_OK} <= observed["states"], (
        f"the hero never ran the native melee states: {sorted(observed['states'])}"
    )
    assert hitter == hero_idx, "the strike must come from the hero, not a projectile"
    assert force == 4
    assert 38 in inventory_items(game), "the saber must stay in inventory"
    assert game.world_objects[38].obj_index == -1, "no saber actor may reach the floor"


def test_mouse_journey_game_over_restart_uses_a_left_click(data_dir, profile, monkeypatch):
    import PyAitD.app.shell as main
    from tests.test_combat_journey import _journey_to_game_over

    game, saw_death_life = _journey_to_game_over(data_dir, profile)
    assert saw_death_life
    assert game.mode is GameMode.GAME_OVER
    hero = game.actors[game.current_camera_target_actor]
    game.nav_intent = NavIntent(
        dest_x=hero.room_x, dest_z=hero.room_z, room=hero.room,
        requires_hold=True,
    )
    game.local_joyd, game.local_click, game.action = (8, 1, 0x2000)
    restarted = []
    real_restart = main.restart_session

    def capture_restart(old_game):
        assert old_game.nav_intent is None
        assert (old_game.local_joyd, old_game.local_click, old_game.action) == (
            0, 0, 0,
        )
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
