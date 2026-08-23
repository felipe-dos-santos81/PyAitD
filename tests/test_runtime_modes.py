# SPDX-License-Identifier: GPL-2.0-only
from collections import deque
from types import SimpleNamespace

import numpy as np

from PyAitD.__main__ import restart_session, route_command, route_mouse
from PyAitD.playworld import apply_play_input
from PyAitD.effects import (
    GameMode, InputMode, NavDecision, NavIntent, OpenInventory, ReadText, ShowPicture,
)
from PyAitD.game import init_game
from PyAitD.scenario import COMBAT_VENUE, enter_combat_venue
from PyAitD.ui import Command, InputBuffer, ModalLayout, ModalSession


def test_play_input_reads_held_state_without_consuming_edges(data_dir):
    game = init_game(data_dir)
    # this asserts the keyboard mapping specifically; mouse is the default
    # input_mode (task 9: playworld — wire the follower into the input
    # snapshot), so it must be selected explicitly to exercise this path.
    game.input_mode = InputMode.KEYBOARD
    state = InputBuffer(held_joyd=5, action_held=True, commands=deque([Command.OPEN_INVENTORY]))
    apply_play_input(game, state)
    assert (game.local_joyd, game.local_click, game.action) == (5, 1, 0x2000)
    assert list(state.commands) == [Command.OPEN_INVENTORY]


def test_inventory_edge_opens_once_and_play_ticks_pause(data_dir):
    game = init_game(data_dir)
    game.inventory_count[0] = 1
    game.inventory_table[0][0] = 13
    session = ModalSession()
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    assert route_command(game, session, Command.OPEN_INVENTORY) is True
    assert game.mode is GameMode.INVENTORY
    assert isinstance(game.active_modal, OpenInventory)
    assert route_command(game, session, Command.OPEN_INVENTORY) is True
    assert isinstance(game.active_modal, OpenInventory)


def test_toggle_input_mode_flips_track_mode_and_cancels_intent(data_dir):
    # Command.TOGGLE_INPUT_MODE's mutation (input_mode, hero track_mode,
    # nav_intent cancellation) is route_command's job, not ui.py's — this
    # exercises route_command directly, the same way
    # test_inventory_edge_opens_once_and_play_ticks_pause does for
    # OPEN_INVENTORY, rather than only proving Tab enqueues a Command.
    game = init_game(data_dir)
    session = ModalSession()
    hero = game.actors[game.current_camera_target_actor]

    game.input_mode = InputMode.MOUSE
    hero.track_mode = 4
    game.nav_intent = NavIntent(dest_x=100, dest_z=200, room=hero.room)
    assert route_command(game, session, Command.TOGGLE_INPUT_MODE) is True
    assert game.input_mode is InputMode.KEYBOARD
    assert hero.track_mode == 1
    assert game.nav_intent is None

    game.nav_intent = NavIntent(dest_x=300, dest_z=400, room=hero.room)
    assert route_command(game, session, Command.TOGGLE_INPUT_MODE) is True
    assert game.input_mode is InputMode.MOUSE
    assert hero.track_mode == 4
    assert game.nav_intent is None


def test_picture_dismiss_does_not_leave_stale_movement_or_replay_command(data_dir):
    game = init_game(data_dir)
    game.open_modal(ShowPicture(10, 0, -1))
    session = ModalSession()
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    assert route_command(game, session, Command.ACCEPT) is True
    assert game.mode is GameMode.PLAY


def test_mouse_reading_next_changes_page_without_resuming_life(data_dir, monkeypatch):
    game = init_game(data_dir)
    game.open_modal(ReadText(1, 0))
    session = ModalSession()
    monkeypatch.setattr(
        "PyAitD.ui.reading_pages", lambda effect, assets: (("one",), ("two",))
    )
    logical = ModalLayout.READING_NEXT.center
    assert route_mouse(game, session, logical)
    assert session.reading.page == 1
    assert game.mode is GameMode.READING


def test_run_flushes_leftover_command_edges_on_modal_entry(data_dir, monkeypatch, tmp_path):
    # FITD flushes input on modal entry: one pump can queue two edges, but the
    # loop routes one per frame; the leftover must not be routed next frame
    # into the new modal, where OPEN_INVENTORY maps to ACCEPT (would flip the
    # inventory session into action selection).
    import PyAitD.__main__ as main

    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    buffer = InputBuffer(commands=deque([Command.OPEN_INVENTORY, Command.OPEN_INVENTORY]))
    session = ModalSession()
    event_batches = iter([[], [SimpleNamespace(type=main.pygame.QUIT)]])
    times = iter([0, 0, 0])

    monkeypatch.setattr(main, "InputBuffer", lambda: buffer)
    monkeypatch.setattr(main, "ModalSession", lambda: session)
    monkeypatch.setattr(
        main, "Floor",
        lambda *args: SimpleNamespace(number=0, rooms=[SimpleNamespace(camera_indices=[0])]),
    )
    monkeypatch.setattr(
        main, "Renderer",
        lambda: SimpleNamespace(present=lambda image: None, close=lambda: None),
    )
    monkeypatch.setattr(main, "play_tick", lambda *args: True)
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (frame, []))
    monkeypatch.setattr(main, "render_active_mode", lambda *args: frame)
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(times))
    monkeypatch.setattr(
        main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *args: None)
    )

    game = init_game(data_dir)
    game.inventory_count[0] = 1
    game.inventory_table[0][0] = 13
    game.num_camera = -1
    game.new_num_camera = 0
    assert main.run(game) == 0
    assert game.mode is GameMode.INVENTORY
    assert isinstance(game.active_modal, OpenInventory)
    assert session.inventory.choosing_action is False
    assert list(buffer.commands) == []


def test_game_starts_in_mouse_mode_with_no_intent(data_dir):
    game = init_game(data_dir)
    assert game.input_mode is InputMode.MOUSE
    assert game.nav_intent is None
    assert game.nav_decision is None
    assert game.nav_arrived_target == -1


def test_a_fresh_game_puts_the_hero_in_the_mode_its_input_mode_needs(data_dir):
    # Object data spawns the hero in track mode 1 (tank) via init_deplacement,
    # and nothing in the hero's LIFE script changes that. With mouse as the
    # default input mode, a hero left in mode 1 makes process_track hand the
    # follower's mirrored joyd to the *keyboard* path — the "autopilot driving
    # a tank" the spec rejected — so init_game must translate it.
    game = init_game(data_dir)
    assert game.actors[game.current_camera_target_actor].track_mode == 4


def test_the_input_snapshot_re_asserts_the_follower_mode(data_dir):
    # a script can call LM_INIT_DEPLACEMENT and hand the hero back to mode 1 at
    # any time; the next input snapshot must take it back for the mouse
    game = init_game(data_dir)
    hero = game.actors[game.current_camera_target_actor]
    hero.track_mode = 1
    apply_play_input(game, InputBuffer())
    assert hero.track_mode == 4


def test_a_scripted_track_survives_the_input_snapshot(data_dir):
    # the translation is 1 <-> 4 only: a cutscene that parks the hero on a
    # scripted track (mode 3) or freezes it (mode 0) keeps what it asked for
    game = init_game(data_dir)
    hero = game.actors[game.current_camera_target_actor]
    for mode in (0, 2, 3):
        hero.track_mode = mode
        apply_play_input(game, InputBuffer())
        assert hero.track_mode == mode


def test_keyboard_mode_hands_the_hero_back_to_tank_controls(data_dir):
    game = init_game(data_dir)
    game.input_mode = InputMode.KEYBOARD
    hero = game.actors[game.current_camera_target_actor]
    assert hero.track_mode == 4, "fixture: init_game starts in mouse mode"
    apply_play_input(game, InputBuffer())
    assert hero.track_mode == 1


def test_nav_intent_defaults_to_a_bare_destination():
    intent = NavIntent(dest_x=100, dest_z=200, room=0)
    assert intent.target_object_idx == -1
    assert intent.waypoints is None


def test_nav_decision_carries_the_mirrored_joystick_bits():
    decision = NavDecision(joyd=5, target_x=1, target_z=2, advance=True, arrived=False)
    assert decision.joyd == 5 and decision.advance is True


def test_restart_session_rebuilds_state_and_preserves_session_choices(data_dir):
    old = init_game(data_dir, hero=1)
    enter_combat_venue(old)
    old.input_mode = InputMode.KEYBOARD
    old.trace = object()
    old.vars[21] = 0
    old.inventory_count[0] = 1
    old.restart_requested = True

    new = restart_session(old)

    assert new is not old
    assert new.floor_start == COMBAT_VENUE
    assert new.cvars[8] == 1
    assert new.input_mode is InputMode.KEYBOARD
    assert new.trace is old.trace
    assert new.vars[21] == 20
    assert new.inventory_count == [0, 0]
    assert new.active_modal is None
    assert new.restart_requested is False
    assert (new.current_floor, new.current_room, new.num_camera) == (5, 4, -1)


def test_restart_session_rebuilds_state_from_the_initial_floor(data_dir):
    # the combat venue is one supported restart boundary; floor 0 (a fresh
    # game's own floor_start) is the other, and must not be special-cased.
    old = init_game(data_dir, hero=1)
    floor_start = old.floor_start
    old.input_mode = InputMode.KEYBOARD
    old.trace = object()
    old.vars[21] = 0
    old.inventory_count[0] = 1
    old.restart_requested = True

    new = restart_session(old)

    assert new is not old
    assert new.floor_start == floor_start
    assert new.cvars[8] == 1
    assert new.input_mode is InputMode.KEYBOARD
    assert new.trace is old.trace
    assert new.vars[21] == 20
    assert new.inventory_count == [0, 0]
    assert new.active_modal is None
    assert new.restart_requested is False
    assert (new.current_floor, new.current_room) == (floor_start.stage, floor_start.room)


def test_restart_session_calls_init_game_and_enter_floor_start_once_and_builds_no_floor(
    data_dir, monkeypatch,
):
    import PyAitD.__main__ as main

    old = init_game(data_dir, hero=0)
    enter_combat_venue(old)
    old.restart_requested = True

    init_calls, enter_calls, floor_calls = [], [], []
    real_init_game, real_enter_floor_start = main.init_game, main.enter_floor_start

    def spy_init_game(*args, **kwargs):
        init_calls.append((args, kwargs))
        return real_init_game(*args, **kwargs)

    def spy_enter_floor_start(*args, **kwargs):
        enter_calls.append((args, kwargs))
        return real_enter_floor_start(*args, **kwargs)

    def refuse_floor(*args, **kwargs):
        floor_calls.append((args, kwargs))
        raise AssertionError("restart_session must not construct a Floor")

    monkeypatch.setattr(main, "init_game", spy_init_game)
    monkeypatch.setattr(main, "enter_floor_start", spy_enter_floor_start)
    monkeypatch.setattr(main, "Floor", refuse_floor)

    new = main.restart_session(old)

    assert len(init_calls) == 1
    assert len(enter_calls) == 1
    assert floor_calls == []
    assert new is not old


def test_run_restart_replaces_game_and_floor_before_any_tick_or_present(monkeypatch, data_dir, tmp_path):
    # Step 7: run() owns the atomic restart -- restart_session and Floor must
    # run, then the per-frame state (session/input buffer) must be reset, then
    # the scene must be recomposed, all before the loop is allowed to tick the
    # world or present a frame for the new game.
    import PyAitD.__main__ as main

    calls = []
    frame = np.zeros((200, 320, 3), dtype=np.uint8)

    old_game = init_game(data_dir)
    old_game.restart_requested = True

    new_game = SimpleNamespace(
        _data_dir=tmp_path, current_floor=0, trace=None, mode=GameMode.PLAY,
        num_camera=-1, new_num_camera=0, flag_init_view=2, current_room=0,
        actors=[], active_modal=None, input_mode=InputMode.MOUSE,
        restart_requested=False,
    )

    def spy_restart_session(game):
        calls.append("restart_session")
        return new_game

    def spy_floor(*args):
        calls.append("Floor")
        return SimpleNamespace(number=0, rooms=[SimpleNamespace(camera_indices=[0])])

    def spy_modal_session():
        calls.append("ModalSession reset")
        # elapsed_ms lives on ModalSession itself (ui.ModalSession), not
        # nested under .reading -- match that shape even though this test's
        # restart path returns before reading it.
        return SimpleNamespace(elapsed_ms=0)

    def spy_input_buffer():
        calls.append("InputBuffer reset")
        return InputBuffer()

    def spy_scene_frame(*args):
        calls.append("_scene_frame")
        return frame, []

    def spy_play_tick(*args):
        calls.append("play_tick")
        return True

    def spy_present(image):
        calls.append("present")

    event_batches = iter([[], [SimpleNamespace(type=main.pygame.QUIT)]])
    times = iter([0] * 8)

    monkeypatch.setattr(main, "restart_session", spy_restart_session)
    monkeypatch.setattr(main, "Floor", spy_floor)
    monkeypatch.setattr(main, "ModalSession", spy_modal_session)
    monkeypatch.setattr(main, "InputBuffer", spy_input_buffer)
    monkeypatch.setattr(main, "_scene_frame", spy_scene_frame)
    monkeypatch.setattr(main, "play_tick", spy_play_tick)
    monkeypatch.setattr(main, "render_active_mode", lambda *a: frame)
    monkeypatch.setattr(
        main, "Renderer",
        lambda: SimpleNamespace(present=spy_present, close=lambda: None),
    )
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(times))
    monkeypatch.setattr(
        main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *a: None)
    )

    assert main.run(old_game) == 0

    start = calls.index("restart_session")
    scene_at = calls.index("_scene_frame", start)
    window = calls[start:scene_at + 1]
    assert window[0] == "restart_session"
    assert window[1] == "Floor"
    assert "ModalSession reset" in window[2:-1]
    assert "InputBuffer reset" in window[2:-1]
    assert window[-1] == "_scene_frame"
    assert "play_tick" not in window
    assert "present" not in window
