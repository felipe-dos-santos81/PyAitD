# SPDX-License-Identifier: GPL-2.0-only
from collections import deque
from types import SimpleNamespace

import numpy as np

from PyAitD.__main__ import route_command, route_mouse
from PyAitD.playworld import apply_play_input
from PyAitD.effects import GameMode, OpenInventory, ReadText, ShowPicture
from PyAitD.game import init_game
from PyAitD.ui import Command, InputBuffer, ModalLayout, ModalSession


def test_play_input_reads_held_state_without_consuming_edges(data_dir):
    game = init_game(data_dir)
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
