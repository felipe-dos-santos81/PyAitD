# SPDX-License-Identifier: GPL-2.0-only
from collections import deque
from types import SimpleNamespace

import numpy as np

from PyAitD.__main__ import route_command, route_mouse
from PyAitD.playworld import apply_play_input
from PyAitD.effects import (
    GameMode, InputMode, NavDecision, NavIntent, OpenInventory, ReadText, ShowPicture,
)
from PyAitD.game import init_game
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
