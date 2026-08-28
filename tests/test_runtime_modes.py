# SPDX-License-Identifier: GPL-2.0-only
from collections import deque
from copy import deepcopy
from dataclasses import replace
import itertools
from types import SimpleNamespace

import numpy as np
import pygame
import pytest

from PyAitD.app.shell import (
    _apply_system_result, _capture_keydown, continue_available, open_startup_menu,
    replacement_session, restart_session,
    route_command, render_active_mode, route_hover, route_mouse,
)
from PyAitD.app.config import (
    REMAPPABLE_CONTROLS, Control, Settings, default_settings, load_settings,
)
from PyAitD.render.render_options import RenderOptions
from PyAitD.engine.playworld import apply_play_input
from PyAitD.engine.effects import (
    ChooseCharacter, FoundResult, GameMode, GameOver, InputMode, NavDecision, NavIntent,
    OpenInventory, OpenStartupMenu, OpenSystemMenu, ReadText, ShowFound, ShowPicture, ShowTitle,
)
from PyAitD.engine.game import init_game
from PyAitD.games.aitd1.scenario import COMBAT_VENUE, enter_combat_venue
from PyAitD.app.startup import StartupLayout, StartupRow, TitlePhase, TITLE_TIMEOUT_MS
from PyAitD.app.ui import (
    CharacterLayout, CharacterPhase, CharacterSelectPresenter, Command,
    InputBuffer, ModalLayout, ModalSession, ReadingResult, SettingsNoticeLayout,
    SystemMenuLayout, SystemMenuPage, SystemMenuPresenter, SystemMenuResult,
)

from tests.conftest import painter_from_frame, stub_renderer

pytestmark = pytest.mark.shell


def _hover_game_snapshot(game):
    return (
        deepcopy(game.vars), deepcopy(game.cvars), deepcopy(game.actors),
        deepcopy(game.world_objects), deepcopy(game.inventory_table),
        deepcopy(game.inventory_count), deepcopy(game.life_stack),
        game.active_modal, game.mode, deepcopy(game.nav_intent),
    )


@pytest.mark.parametrize("effect", (ShowPicture(10, 60, 4), GameOver(120)))
def test_route_hover_leaves_non_preview_modal_timing_and_presenters_untouched(effect):
    session = ModalSession(elapsed_ms=37)
    observed_effect = object()
    session.last_effect = observed_effect
    presenters = (
        session.found, session.inventory, session.reading,
        session.character, session.system_menu,
    )

    route_hover(SimpleNamespace(active_modal=effect), session, (160, 100))

    assert (session.last_effect, session.elapsed_ms) == (observed_effect, 37)
    assert presenters == (
        session.found, session.inventory, session.reading,
        session.character, session.system_menu,
    )


def test_render_active_mode_resets_a_replaced_system_menu_preview(monkeypatch):
    old_effect = OpenSystemMenu()
    replacement = OpenSystemMenu()
    session = ModalSession()
    session.reset_for(old_effect)
    old_presenter = session.system_menu
    old_presenter.hover = 2
    game = SimpleNamespace(active_modal=replacement, assets=object())
    # render_system_menu now paints on the painter in place instead of
    # returning a frame, so render_active_mode's own painter.to_frame() is
    # what's asserted below, not this stub's return value.
    monkeypatch.setattr("PyAitD.app.ui.render_system_menu", lambda *args: None)

    renderer = stub_renderer()
    frame = render_active_mode(game, session, renderer).to_frame()
    assert frame.shape == (200, 320, 4)
    assert session.last_effect is replacement
    assert session.system_menu is not old_presenter
    assert session.system_menu.hover is None


def test_render_active_mode_returns_a_transparent_rgba_canvas_with_no_modal():
    """render_active_mode's no-modal contract (task 9): it returns a
    UIPainter whose canvas is the RGBA UI layer -- overlay_messages painted
    on an otherwise untouched painter -- not the opaque scene_frame it used
    to paint messages onto directly. Asserted on the painter's actual
    to_frame() shape/dtype/content, not on a stubbed presenter's return
    string, so a regression back to the old overlay_messages(scene_frame,
    ...) call -- which would carry a 3-channel opaque frame instead -- fails
    this test."""
    game = SimpleNamespace(active_modal=None, messages=(), assets=object())
    session = ModalSession()
    renderer = stub_renderer()

    result = render_active_mode(game, session, renderer).to_frame()

    assert result.shape == (200, 320, 4)
    assert result.dtype == np.uint8
    assert result.max() == 0  # no messages: transparent_canvas() untouched

    pygame.font.init()

    class _FakeAssets:
        def system_text(self, _message_id):
            return "hello"

    game_with_message = SimpleNamespace(
        active_modal=None, assets=_FakeAssets(),
        messages=[SimpleNamespace(message_id=0)],
    )
    with_message = render_active_mode(game_with_message, session, renderer).to_frame()
    assert with_message.shape == (200, 320, 4)
    assert with_message[:, :, 3].max() > 0  # the message glyph painted real alpha


def test_route_hover_previews_every_enabled_modal_and_shell_target_without_game_mutation(
    data_dir, profile, monkeypatch,
):
    from PyAitD.engine.effects import OpenInventory, OpenSystemMenu, ReadText, ShowFound

    game = init_game(data_dir, profile)
    session = ModalSession()

    game.open_modal(ShowFound(13, False))
    before = _hover_game_snapshot(game)
    for target in (FoundResult.LEAVE, FoundResult.TAKE):
        route_hover(game, session, {
            FoundResult.LEAVE: ModalLayout.FOUND_LEAVE.center,
            FoundResult.TAKE: ModalLayout.FOUND_TAKE.center,
        }[target])
        assert session.found.hover is target
        assert session.found.choice is FoundResult.TAKE
        assert _hover_game_snapshot(game) == before
    route_hover(game, session, None)
    assert session.found.hover is None

    game.close_modal()
    game.inventory_table[0][0] = 13
    game.inventory_table[0][1] = 38
    game.inventory_count[0] = 2
    game.open_modal(OpenInventory())
    monkeypatch.setattr(
        "PyAitD.app.shell._inventory_view", lambda game, session: ((13, 38), (23, 24)),
    )
    before = _hover_game_snapshot(game)
    for row, target in enumerate((0, 1)):
        route_hover(game, session, ModalLayout.INVENTORY_ROWS[row].center)
        assert session.inventory.hover == target
        assert (session.inventory.object_cursor, session.inventory.action_cursor,
                session.inventory.choosing_action) == (0, 0, False)
        assert session.found.hover is None
        assert _hover_game_snapshot(game) == before
    session.inventory.choosing_action = True
    for row in range(2):
        route_hover(game, session, ModalLayout.INVENTORY_ROWS[row].center)
        assert session.inventory.hover == row
        assert (session.inventory.object_cursor, session.inventory.action_cursor,
                session.inventory.choosing_action) == (0, 0, True)
        assert _hover_game_snapshot(game) == before

    game.close_modal()
    game.open_modal(ReadText(1, 0))
    monkeypatch.setattr(
        "PyAitD.app.ui.reading_pages", lambda effect, assets: (("one",), ("two",)),
    )
    before = _hover_game_snapshot(game)
    for page, expected_reading in (
        (0, ((ModalLayout.READING_NEXT.center, ReadingResult(False, 1)),
             (ModalLayout.READING_CLOSE.center, ReadingResult(True)))),
        (1, ((ModalLayout.READING_PREV.center, ReadingResult(False, -1)),
        (ModalLayout.READING_CLOSE.center, ReadingResult(True)),
        )),
    ):
        session.reading.page = page
        for point, target in expected_reading:
            route_hover(game, session, point)
            assert session.reading.hover == target
            assert session.reading.page == page
            assert _hover_game_snapshot(game) == before

    game.close_modal()
    game.open_modal(ChooseCharacter())
    before = _hover_game_snapshot(game)
    for target, rect in enumerate(CharacterLayout.PORTRAITS):
        route_hover(game, session, rect.center)
        assert session.character.hover == target
        assert (session.character.choice, session.character.phase) == (0, CharacterPhase.PORTRAITS)
        assert _hover_game_snapshot(game) == before
    session.character.phase = CharacterPhase.STORY
    route_hover(game, session, (0, 0))
    assert (session.character.hover, session.character.choice, session.character.phase) == (
        0, 0, CharacterPhase.STORY,
    )

    game.close_modal()
    game.open_modal(OpenSystemMenu())
    before = _hover_game_snapshot(game)
    for target, rect in enumerate(SystemMenuLayout.MAIN_ROWS):
        route_hover(game, session, rect.center)
        assert session.system_menu.hover == target
        assert session.system_menu.cursor == 0
        assert _hover_game_snapshot(game) == before
    session.system_menu.page = SystemMenuPage.CONFIG
    for target, rect in enumerate(SystemMenuLayout.CONFIG_ROWS):
        route_hover(game, session, rect.center)
        assert session.system_menu.hover == target
        assert session.system_menu.cursor == 0
        assert _hover_game_snapshot(game) == before
    route_hover(game, session, (0, 0))
    assert session.system_menu.hover is None


def test_run_routes_motion_once_and_focus_loss_clears_the_modal_preview(data_dir, profile, monkeypatch):
    import PyAitD.app.shell as main
    from PyAitD.engine.effects import ShowFound

    game = init_game(data_dir, profile)
    game.open_modal(ShowFound(13, False))
    session = ModalSession()
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    positions, events = [], iter((
        [pygame.event.Event(pygame.MOUSEMOTION, pos=ModalLayout.FOUND_TAKE.center)],
        [pygame.event.Event(pygame.WINDOWFOCUSLOST)],
        [pygame.event.Event(pygame.QUIT)],
    ))
    ticks = itertools.count(0, 20)
    monkeypatch.setattr(main, "Renderer", lambda *_a, **_k: SimpleNamespace(
        fallback_notice=None,
        window_to_logical=lambda pos: positions.append(pos) or pos,
        present=lambda image: None,
        close=lambda: None,
    ))
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (frame, []))
    monkeypatch.setattr(main, "render_active_mode", lambda *args: painter_from_frame(frame))
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(events))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(ticks))
    monkeypatch.setattr(main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *args: None))
    monkeypatch.setattr(main.pygame.display, "set_caption", lambda *args: None)
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda *args: None)

    assert main.run(game, session=session) == 0
    assert positions == [ModalLayout.FOUND_TAKE.center]
    assert session.found.hover is None


def _left_click(pos):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=tuple(pos))


def _run_notice_script(monkeypatch, game, session, next_events, draw_list=()):
    # Same headless run() harness as the modal-entry/restart tests above,
    # with a caller-supplied session so the settings notice can be staged.
    import PyAitD.app.shell as main

    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    ticks = itertools.count(0, 20)
    monkeypatch.setattr(main, "Renderer", lambda *_a, **_k: SimpleNamespace(
        fallback_notice=None,
        window_to_logical=lambda pos: pos,
        present=lambda image: None,
        close=lambda: None,
    ))
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (frame, list(draw_list)))
    monkeypatch.setattr(main, "render_active_mode", lambda *args: painter_from_frame(frame))
    monkeypatch.setattr(main, "play_tick", lambda *args: True)
    monkeypatch.setattr(main.pygame.event, "get", next_events)
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(ticks))
    monkeypatch.setattr(
        main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *args: None)
    )
    monkeypatch.setattr(main.pygame.display, "set_caption", lambda *args: None)
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda *args: None)
    assert main.run(game, session=session) == 0


def test_settings_notice_dismiss_click_has_first_refusal_in_play(data_dir, profile, monkeypatch):
    game = init_game(data_dir, profile)
    session = ModalSession(settings_error="Could not load settings from /x: corrupt")
    lamp_idx = 13
    actor_idx = game.world_objects[lamp_idx].obj_index
    observed = {}
    state = {"frames": 0}

    def next_events():
        state["frames"] += 1
        frames = state["frames"]
        assert frames < 10, "PLAY notice script exceeded its budget"
        if frames == 1:
            # outside the Dismiss rect the click passes straight through to
            # the lamp target, and the notice stays up
            return [_left_click((150, 100))]
        if frames == 2:
            observed["passthrough"] = (session.settings_error, game.nav_intent)
            return [_left_click(SettingsNoticeLayout.DISMISS.center)]
        if frames == 3:
            observed["dismissed"] = (
                session.settings_error, game.mode, game.active_modal,
                game.nav_intent,
            )
            return [pygame.event.Event(pygame.QUIT)]
        return []

    _run_notice_script(
        monkeypatch, game, session, next_events,
        draw_list=[(actor_idx, (100, 60, 200, 160))],
    )
    error, intent = observed["passthrough"]
    assert error == "Could not load settings from /x: corrupt"
    assert intent is not None, "a click outside Dismiss must reach the mode"
    assert observed["dismissed"] == (None, GameMode.PLAY, None, intent)


def test_settings_notice_first_refusal_in_character_select(data_dir, profile, monkeypatch):
    game = init_game(data_dir, profile)
    game.open_modal(ChooseCharacter())
    effect = game.active_modal
    session = ModalSession(settings_error="Could not load settings from /x: corrupt")
    observed = {}
    state = {"frames": 0}

    def next_events():
        state["frames"] += 1
        frames = state["frames"]
        assert frames < 12, "character-select notice script exceeded its budget"
        if frames == 1:
            return [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN)]
        if frames == 2:
            observed["open_inventory"] = (
                session.settings_error, session.character.phase,
            )
            session.settings_error = "again"
            return [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)]
        if frames == 3:
            observed["accept"] = (session.settings_error, session.character.phase)
            session.settings_error = "again"
            return [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT)]
        if frames == 4:
            # a direction command passes through to the selector and leaves
            # the notice up
            observed["direction"] = (
                session.settings_error, session.character.choice,
            )
            return [_left_click(CharacterLayout.PORTRAITS[0].center)]
        if frames == 5:
            # a click outside Dismiss also passes through, selecting the hero
            observed["outside_click"] = (
                session.settings_error, session.character.phase,
            )
            return [_left_click(SettingsNoticeLayout.DISMISS.center)]
        if frames == 6:
            observed["dismissed"] = (
                session.settings_error, session.character.phase,
                session.pending_hero,
            )
            return [pygame.event.Event(pygame.QUIT)]
        return []

    _run_notice_script(monkeypatch, game, session, next_events)
    assert observed["open_inventory"] == (None, CharacterPhase.PORTRAITS)
    assert observed["accept"] == (None, CharacterPhase.PORTRAITS)
    assert observed["direction"] == ("again", 1)
    assert observed["outside_click"] == ("again", CharacterPhase.STORY)
    assert observed["dismissed"] == (None, CharacterPhase.STORY, None)
    assert game.active_modal is effect
    assert game.mode is GameMode.CHARACTER_SELECT


def test_character_routes_reach_story_back_and_pending_hero(data_dir, profile):
    game = init_game(data_dir, profile)
    game.open_modal(ChooseCharacter())
    session = ModalSession()
    assert route_command(game, session, Command.ACCEPT)
    assert session.character.phase is CharacterPhase.STORY
    assert route_command(game, session, Command.CANCEL)
    assert session.character.phase is CharacterPhase.PORTRAITS
    assert route_mouse(game, session, CharacterLayout.PORTRAITS[1].center)
    assert session.character.phase is CharacterPhase.STORY
    assert route_mouse(game, session, (160, 100))
    assert session.pending_hero == 0


def test_character_quit_at_portraits_returns_false(data_dir, profile):
    # CANCEL at the portrait phase is the selector's quit result -- run() must
    # see False and stop; CANCEL at the story phase only steps back.
    game = init_game(data_dir, profile)
    game.open_modal(ChooseCharacter())
    session = ModalSession()
    assert route_command(game, session, Command.CANCEL) is False
    assert session.pending_hero is None


@pytest.mark.parametrize("portrait, opposite_half, hero", (
    (0, (300, 100), 1),  # left portrait (Emily, choice 0) -> hero 1
    (1, (20, 100), 0),   # right portrait (Carnby, choice 1) -> hero 0
))
def test_story_click_confirms_the_selected_portrait_not_the_click_side(
    data_dir, profile, portrait, opposite_half, hero,
):
    # hit_test_character treats the story page as a whole-frame confirm, so
    # the click's x position carries no left/right meaning; the hero must come
    # from the selected portrait, agreeing with the keyboard path.
    game = init_game(data_dir, profile)
    game.open_modal(ChooseCharacter())
    session = ModalSession()
    assert route_mouse(game, session, CharacterLayout.PORTRAITS[portrait].center)
    assert session.character.phase is CharacterPhase.STORY
    assert session.character.choice == portrait
    assert route_mouse(game, session, opposite_half)
    assert session.pending_hero == hero


def test_replacement_session_carries_only_application_settings(tmp_path):
    settings = Settings(default_settings().bindings, True)
    old = ModalSession(settings=settings, settings_path=tmp_path / "settings.json",
                       settings_error="named error", settings_dirty=True)
    old.character.choice = 1
    old.character.hover = 0
    old.system_menu.hover = 2
    new = replacement_session(old)
    assert (new.settings, new.settings_path, new.settings_error, new.settings_dirty) == (
        settings, old.settings_path, "named error", True,
    )
    assert new.character == CharacterSelectPresenter()
    assert new.system_menu == SystemMenuPresenter()


def test_hero_branch_replaces_game_floor_session_and_input_atomically(data_dir, profile, monkeypatch):
    import PyAitD.app.shell as main
    from PyAitD.engine.game import Game

    staging = init_game(data_dir, profile)
    staging.open_modal(ChooseCharacter())
    staging.trace = object()
    staging.nav_intent = NavIntent(dest_x=100, dest_z=200, room=0)
    staging.local_joyd, staging.local_click, staging.action = (8, 1, 0x2000)
    session = ModalSession(settings_error="named error", settings_dirty=True)
    session.pending_hero = 1
    old_buffer = InputBuffer(
        pointer_held=True, action_held=True, held_joyd=8,
        commands=deque([Command.ACCEPT]),
    )

    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    init_calls, floor_calls, ticked = [], [], []
    real_init_game = main.init_game

    def spy_init_game(data, profile, hero=0):
        init_calls.append((data, hero))
        return real_init_game(data, profile, hero=hero)

    monkeypatch.setattr(main, "init_game", spy_init_game)
    monkeypatch.setattr(
        Game, "load_floor",
        lambda self, number: floor_calls.append((self, number)) or SimpleNamespace(number=0),
    )
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (frame, ["draw"]))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: 4321)
    monkeypatch.setattr(main, "play_tick", lambda *args: ticked.append(1))

    result = main._hero_branch(staging, SimpleNamespace(), session, old_buffer)

    assert result is not None
    (new_game, new_floor, new_session, new_buffer, accumulator,
     draw_list, hover, scene_frame, last, exit_status, new_resolver) = result
    from PyAitD.render.asset_resolver import AssetResolver
    assert isinstance(new_resolver, AssetResolver)
    assert new_resolver._assets is new_game.assets
    assert init_calls == [(staging._data_dir, 1)]
    assert new_game is not staging
    assert new_game.trace is staging.trace
    assert floor_calls == [(new_game, new_game.current_floor)]
    assert isinstance(new_buffer, InputBuffer) and new_buffer.bindings is not None
    assert (new_session.settings_error, new_session.settings_dirty) == (
        "named error", True,
    )
    assert new_session.pending_hero is None
    assert (accumulator, draw_list, hover, scene_frame, last, exit_status) == (
        0, ["draw"], None, frame, 4321, 0,
    )
    assert ticked == [], "the old staging game must not be ticked"
    assert staging.nav_intent is None
    assert (staging.local_joyd, staging.local_click, staging.action) == (0, 0, 0)
    assert (old_buffer.pointer_held, old_buffer.action_held,
            old_buffer.held_joyd, list(old_buffer.commands)) == (
        False, False, 0, [],
    )


def test_hero_branch_is_inert_without_a_pending_hero(data_dir, profile):
    import PyAitD.app.shell as main
    game = init_game(data_dir, profile)
    assert main._hero_branch(game, SimpleNamespace(), ModalSession()) is None


def test_restart_branch_carries_application_settings(data_dir, profile, monkeypatch):
    import PyAitD.app.shell as main
    from PyAitD.engine.game import Game

    game = init_game(data_dir, profile, hero=1)
    game.restart_requested = True
    game.nav_intent = NavIntent(dest_x=100, dest_z=200, room=0)
    game.local_joyd, game.local_click, game.action = (8, 1, 0x2000)
    session = ModalSession(settings_error="named error", settings_dirty=True)
    session.character.choice = 1
    old_buffer = InputBuffer(
        pointer_held=True, action_held=True, held_joyd=8,
        commands=deque([Command.ACCEPT]),
    )
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    monkeypatch.setattr(Game, "load_floor", lambda self, number: SimpleNamespace(number=0))
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (frame, []))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: 0)

    result = main._restart_branch(game, SimpleNamespace(), session, old_buffer)

    assert result is not None
    new_session, new_buffer = result[2], result[3]
    assert (new_session.settings_error, new_session.settings_dirty) == (
        "named error", True,
    )
    assert new_session.character == CharacterSelectPresenter()
    assert isinstance(new_buffer, InputBuffer) and new_buffer.bindings is not None
    assert game.nav_intent is None
    assert (game.local_joyd, game.local_click, game.action) == (0, 0, 0)
    assert (old_buffer.pointer_held, old_buffer.action_held,
            old_buffer.held_joyd, list(old_buffer.commands)) == (
        False, False, 0, [],
    )


def test_inventory_hud_availability_is_the_complete_shared_policy(data_dir, profile):
    from PyAitD.app.shell import inventory_hud_available

    game = init_game(data_dir, profile)
    game.num_camera = game.new_num_camera
    game.inventory_table[0][0] = 38
    game.inventory_count[0] = 1
    assert inventory_hud_available(game)

    mutations = (
        ("input_mode", InputMode.KEYBOARD),
        ("status_screen_allowed", 0),
        ("num_camera", -1),
        ("current_camera_target_actor", -1),
    )
    for field, value in mutations:
        old = getattr(game, field)
        setattr(game, field, value)
        assert not inventory_hud_available(game), field
        setattr(game, field, old)

    game.inventory_count[0] = 0
    assert not inventory_hud_available(game)
    game.inventory_count[0] = 1
    game.open_modal(OpenInventory())
    assert not inventory_hud_available(game)


def test_play_input_reads_held_state_without_consuming_edges(data_dir, profile):
    game = init_game(data_dir, profile)
    # this asserts the keyboard mapping specifically; mouse is the default
    # input_mode (task 9: playworld — wire the follower into the input
    # snapshot), so it must be selected explicitly to exercise this path.
    game.input_mode = InputMode.KEYBOARD
    state = InputBuffer(held_joyd=5, action_held=True, commands=deque([Command.OPEN_INVENTORY]))
    apply_play_input(game, state)
    assert (game.local_joyd, game.local_click, game.action) == (5, 1, 0x2000)
    assert list(state.commands) == [Command.OPEN_INVENTORY]


def test_inventory_edge_opens_once_and_play_ticks_pause(data_dir, profile):
    game = init_game(data_dir, profile)
    game.inventory_count[0] = 1
    game.inventory_table[0][0] = 13
    session = ModalSession()
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    assert route_command(game, session, Command.OPEN_INVENTORY) is True
    assert game.mode is GameMode.INVENTORY
    assert isinstance(game.active_modal, OpenInventory)
    assert route_command(game, session, Command.OPEN_INVENTORY) is True
    assert isinstance(game.active_modal, OpenInventory)


def test_toggle_input_mode_flips_track_mode_and_cancels_intent(data_dir, profile):
    # Command.TOGGLE_INPUT_MODE's mutation (input_mode, hero track_mode,
    # nav_intent cancellation) is route_command's job, not ui.py's — this
    # exercises route_command directly, the same way
    # test_inventory_edge_opens_once_and_play_ticks_pause does for
    # OPEN_INVENTORY, rather than only proving Tab enqueues a Command.
    game = init_game(data_dir, profile)
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


def test_picture_dismiss_does_not_leave_stale_movement_or_replay_command(data_dir, profile):
    game = init_game(data_dir, profile)
    game.open_modal(ShowPicture(10, 0, -1))
    session = ModalSession()
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    assert route_command(game, session, Command.ACCEPT) is True
    assert game.mode is GameMode.PLAY


def test_mouse_reading_next_changes_page_without_resuming_life(data_dir, profile, monkeypatch):
    game = init_game(data_dir, profile)
    game.open_modal(ReadText(1, 0))
    session = ModalSession()
    monkeypatch.setattr(
        "PyAitD.app.ui.reading_pages", lambda effect, assets: (("one",), ("two",))
    )
    logical = ModalLayout.READING_NEXT.center
    assert route_mouse(game, session, logical)
    assert session.reading.page == 1
    assert game.mode is GameMode.READING


def test_apply_system_result_pushes_a_changed_render_option_to_the_renderer():
    pygame.init()
    session = ModalSession()
    calls = []
    renderer = SimpleNamespace(set_options=lambda options: calls.append(options))
    changed = replace(session.settings, render=RenderOptions(scale=6))
    result = SystemMenuResult(settings=changed)

    assert _apply_system_result(object(), session, InputBuffer(), result, renderer=renderer) is True
    assert calls == [RenderOptions(scale=6)]
    assert session.settings.render == RenderOptions(scale=6)


def test_apply_system_result_does_not_push_a_non_render_setting_change():
    pygame.init()
    session = ModalSession()
    calls = []
    renderer = SimpleNamespace(set_options=lambda options: calls.append(options))
    changed = replace(session.settings, sticky_action=not session.settings.sticky_action)
    result = SystemMenuResult(settings=changed)

    assert _apply_system_result(object(), session, InputBuffer(), result, renderer=renderer) is True
    assert calls == []
    assert session.settings.sticky_action == changed.sticky_action


def test_apply_system_result_tolerates_a_missing_renderer():
    pygame.init()
    session = ModalSession()
    changed = replace(session.settings, render=RenderOptions(scale=8))
    result = SystemMenuResult(settings=changed)

    assert _apply_system_result(object(), session, InputBuffer(), result) is True
    assert session.settings.render == RenderOptions(scale=8)


def test_system_menu_subview_transitions_clear_keyboard_and_mouse_hover(data_dir, profile):
    effect = OpenSystemMenu()
    game = init_game(data_dir, profile)
    game.open_modal(effect)
    session = ModalSession()
    session.reset_for(effect)
    session.system_menu.cursor = 1
    session.system_menu.hover = 2

    assert route_command(game, session, Command.ACCEPT, InputBuffer())
    assert (session.system_menu.page, session.system_menu.cursor) == (
        SystemMenuPage.CONFIG, 0,
    )
    assert session.system_menu.hover is None

    route_hover(game, session, SystemMenuLayout.CONFIG_ROWS[-1].center)
    assert session.system_menu.hover == len(SystemMenuLayout.CONFIG_ROWS) - 1
    assert route_mouse(
        game, session, SystemMenuLayout.CONFIG_ROWS[-1].center, InputBuffer(),
    )
    assert (session.system_menu.page, session.system_menu.cursor) == (
        SystemMenuPage.MAIN, 0,
    )
    assert session.system_menu.hover is None


def test_inventory_subview_transitions_clear_keyboard_and_mouse_hover(
    data_dir, profile, monkeypatch,
):
    effect = OpenInventory()
    game = init_game(data_dir, profile)
    game.open_modal(effect)
    session = ModalSession()
    session.reset_for(effect)
    monkeypatch.setattr(
        "PyAitD.app.shell._inventory_view", lambda game, session: ((13, 38), (23, 24)),
    )
    session.inventory.hover = 1

    assert route_command(game, session, Command.ACCEPT, InputBuffer())
    assert (session.inventory.choosing_action, session.inventory.action_cursor) == (True, 0)
    assert session.inventory.hover is None

    session.inventory.choosing_action = False
    route_hover(game, session, ModalLayout.INVENTORY_HIT_ROWS[1].center)
    assert session.inventory.hover == 1
    assert route_mouse(
        game, session, ModalLayout.INVENTORY_HIT_ROWS[1].center, InputBuffer(),
    )
    assert (session.inventory.object_cursor, session.inventory.choosing_action,
            session.inventory.action_cursor) == (1, True, 0)
    assert session.inventory.hover is None


def test_reading_page_transitions_clear_hover_and_disable_the_new_page_target(
    data_dir, profile, monkeypatch,
):
    effect = ReadText(1, 0)
    game = init_game(data_dir, profile)
    game.open_modal(effect)
    session = ModalSession()
    session.reset_for(effect)
    monkeypatch.setattr(
        "PyAitD.app.ui.reading_pages", lambda effect, assets: (("one",), ("two",)),
    )
    next_page = ReadingResult(False, 1)
    session.reading.hover = next_page

    assert route_command(game, session, Command.RIGHT, InputBuffer())
    assert session.reading.page == 1
    assert session.reading.hover is None

    session.reading.page = 0
    route_hover(game, session, ModalLayout.READING_NEXT.center)
    assert session.reading.hover == next_page
    assert route_mouse(game, session, ModalLayout.READING_NEXT.center, InputBuffer())
    assert session.reading.page == 1
    assert session.reading.hover is None

    route_hover(game, session, ModalLayout.READING_NEXT.center)
    assert session.reading.hover is None


def test_run_flushes_leftover_command_edges_on_modal_entry(data_dir, profile, monkeypatch, tmp_path):
    # FITD flushes input on modal entry: one pump can queue two edges, but the
    # loop routes one per frame; the leftover must not be routed next frame
    # into the new modal, where OPEN_INVENTORY maps to ACCEPT (would flip the
    # inventory session into action selection).
    import PyAitD.app.shell as main
    from PyAitD.engine.game import Game

    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    buffer = InputBuffer()
    session = ModalSession()
    event_batches = iter([[], [SimpleNamespace(type=main.pygame.QUIT)]])
    times = iter([0, 0, 0])

    # run() now configures the session's input buffer before the loop, and
    # configuring resets (clears) queued commands -- so the two edges are
    # seeded right after that boot step, still before the first pump.
    real_configure = main.configure_session_input

    def seed_after_configure(session, input_buffer):
        real_configure(session, input_buffer)
        input_buffer.commands.extend([Command.OPEN_INVENTORY, Command.OPEN_INVENTORY])

    monkeypatch.setattr(main, "configure_session_input", seed_after_configure)
    monkeypatch.setattr(main, "InputBuffer", lambda: buffer)
    monkeypatch.setattr(main, "ModalSession", lambda: session)
    monkeypatch.setattr(
        Game, "load_floor",
        lambda self, number: SimpleNamespace(number=0, rooms=[SimpleNamespace(camera_indices=[0])]),
    )
    monkeypatch.setattr(
        main, "Renderer",
        lambda *_a, **_k: SimpleNamespace(
            fallback_notice=None, present=lambda image: None, close=lambda: None,
        ),
    )
    monkeypatch.setattr(main, "play_tick", lambda *args: True)
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (frame, []))
    monkeypatch.setattr(main, "render_active_mode", lambda *args: painter_from_frame(frame))
    monkeypatch.setattr(
        main.pygame.mouse, "set_visible", lambda value: None
    )
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(times))
    monkeypatch.setattr(
        main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *args: None)
    )

    game = init_game(data_dir, profile)
    game.inventory_count[0] = 1
    game.inventory_table[0][0] = 13
    game.num_camera = -1
    game.new_num_camera = 0
    assert main.run(game) == 0
    assert game.mode is GameMode.INVENTORY
    assert isinstance(game.active_modal, OpenInventory)
    assert session.inventory.choosing_action is False
    assert list(buffer.commands) == []


@pytest.mark.parametrize(
    "effect",
    (ShowFound(13, False), GameOver(120)),
    ids=("found-contact", "game-over"),
)
def test_simulation_raised_modal_takeover_is_clean_before_floor_load_and_render(
        data_dir, profile, monkeypatch, effect,
):
    import PyAitD.app.shell as main
    from PyAitD.engine.game import Game

    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    game = init_game(data_dir, profile)
    game.num_camera = game.new_num_camera
    hero = game.actors[game.current_camera_target_actor]
    game.nav_intent = NavIntent(dest_x=100, dest_z=200, room=hero.room)
    game.nav_decision = NavDecision(
        joyd=8, target_x=100, target_z=200, advance=True, arrived=False,
    )
    game.local_joyd, game.local_click, game.action = (8, 1, 0x2000)
    buffer = InputBuffer(
        pointer_held=True, pointer_pos=(150, 100), action_held=True, held_joyd=8,
    )
    session = ModalSession(last_effect=effect)
    session.found.hover = FoundResult.LEAVE
    boundaries = []
    event_batches = iter([
        [],
        [main.pygame.event.Event(main.pygame.QUIT)],
    ])
    times = iter([0, 20, 20])

    def raise_modal(current_game, _floor, input_buffer):
        input_buffer.commands.append(Command.UP)
        current_game.open_modal(effect)
        current_game.current_floor = 1

    def assert_takeover_clean(boundary):
        assert game.nav_intent is None
        assert game.nav_decision is None
        assert (
            game.local_joyd, game.local_click, game.action,
        ) == (0, 0, 0)
        assert not buffer.pointer_held
        assert list(buffer.commands) == []
        if isinstance(effect, ShowFound):
            assert session.found.hover is None
        boundaries.append(boundary)

    def stub_load_floor(self, number):
        if game.active_modal is not None:
            assert_takeover_clean("floor-load")
        return SimpleNamespace(
            number=number, rooms=[SimpleNamespace(camera_indices=[0])],
        )

    def scene_frame(current_game, _floor, _renderer, *_args):
        if current_game.active_modal is not None:
            assert_takeover_clean("scene-frame")
        return frame, []

    def assert_clean_before_render(_game, _session, _frame, *_args):
        assert_takeover_clean("modal-render")
        return painter_from_frame(frame)

    monkeypatch.setattr(Game, "load_floor", stub_load_floor)
    monkeypatch.setattr(main, "Renderer", lambda *_a, **_k: SimpleNamespace(
        fallback_notice=None,
        present=lambda _image: None, close=lambda: None,
    ))
    monkeypatch.setattr(main, "_scene_frame", scene_frame)
    monkeypatch.setattr(main, "play_tick", raise_modal)
    monkeypatch.setattr(main, "render_active_mode", assert_clean_before_render)
    monkeypatch.setattr(main, "render_play_hud", lambda image, **_kwargs: image)
    monkeypatch.setattr(main, "render_settings_notice", lambda image, *_args: image)
    monkeypatch.setattr(main, "InputBuffer", lambda: buffer)
    monkeypatch.setattr(main, "configure_session_input", lambda *_args: None)
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda _value: None)
    monkeypatch.setattr(main.pygame.display, "set_caption", lambda *_args: None)
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(times))
    monkeypatch.setattr(
        main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *_args: None),
    )

    assert main.run(game, session=session) == 0
    assert boundaries == [
        "floor-load", "scene-frame", "modal-render", "modal-render",
    ]


def test_escape_in_play_opens_system_menu_instead_of_quitting(data_dir, profile):
    game = init_game(data_dir, profile)
    session = ModalSession()
    state = InputBuffer(held_joyd=9, action_held=True, sticky_armed=True,
                        action_pulse=True, commands=deque([Command.UP]))
    assert route_command(game, session, Command.CANCEL, state)
    assert isinstance(game.active_modal, OpenSystemMenu)
    assert game.mode is GameMode.SYSTEM_MENU


def test_keyboard_system_menu_modal_takeover_cleans_play_input(data_dir, profile):
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    game.nav_intent = NavIntent(dest_x=100, dest_z=200, room=hero.room)
    game.nav_decision = NavDecision(
        joyd=8, target_x=100, target_z=200, advance=True, arrived=False,
    )
    game.local_joyd, game.local_click, game.action = (8, 1, 0x2000)
    session = ModalSession()
    session.system_menu.hover = 2
    state = InputBuffer(
        pointer_held=True, pointer_pos=(150, 100), action_held=True, held_joyd=8,
        commands=deque([Command.UP]),
    )

    assert route_command(game, session, Command.CANCEL, state)

    assert isinstance(game.active_modal, OpenSystemMenu)
    assert game.nav_intent is None
    assert game.nav_decision is None
    assert (game.local_joyd, game.local_click, game.action) == (0, 0, 0)
    assert (state.pointer_held, state.pointer_pos, state.action_held,
            state.held_joyd, list(state.commands)) == (
        False, None, False, 0, [],
    )
    assert session.system_menu.hover is None


def test_repeated_modal_takeover_is_idempotent_without_presenter_reset(data_dir, profile):
    import PyAitD.app.shell as main

    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    effect = OpenInventory()
    game.open_modal(effect)
    game.nav_intent = NavIntent(dest_x=100, dest_z=200, room=hero.room)
    game.nav_decision = NavDecision(
        joyd=8, target_x=100, target_z=200, advance=True, arrived=False,
    )
    game.local_joyd, game.local_click, game.action = (8, 1, 0x2000)
    session = ModalSession(elapsed_ms=37)
    session.reset_for(effect)
    session.elapsed_ms = 37
    presenter = session.inventory
    presenter.hover = 0
    state = InputBuffer(
        pointer_held=True, pointer_pos=(150, 100), action_held=True, held_joyd=8,
        commands=deque([Command.UP]),
    )

    main._take_over_play_input(game, session, state)
    main._take_over_play_input(game, session, state)

    assert session.last_effect is effect
    assert session.inventory is presenter
    assert (session.elapsed_ms, presenter.hover) == (37, None)
    assert game.nav_intent is None
    assert game.nav_decision is None
    assert (game.local_joyd, game.local_click, game.action) == (0, 0, 0)
    assert (state.pointer_held, state.pointer_pos, state.action_held,
            state.held_joyd, list(state.commands)) == (
        False, None, False, 0, [],
    )


def test_system_menu_mouse_activates_configuration_and_return(data_dir, profile):
    game = init_game(data_dir, profile)
    game.open_modal(OpenSystemMenu())
    session = ModalSession()
    state = InputBuffer()
    assert route_mouse(
        game, session, SystemMenuLayout.MAIN_ROWS[1].center, state,
    )
    assert session.system_menu.page is SystemMenuPage.CONFIG
    assert route_mouse(
        game, session, SystemMenuLayout.CONFIG_ROWS[-1].center, state,
    )
    assert session.system_menu.page is SystemMenuPage.MAIN
    session.system_menu.page = SystemMenuPage.MAIN
    assert route_mouse(
        game, session, SystemMenuLayout.MAIN_ROWS[0].center, state,
    )
    assert game.mode is GameMode.PLAY


def test_configuration_saves_once_when_leaving_and_applies_immediately(data_dir, profile, tmp_path):
    game = init_game(data_dir, profile)
    game.open_modal(OpenSystemMenu())
    session = ModalSession(settings_path=tmp_path / "settings.json")
    state = InputBuffer()
    session.system_menu.page = SystemMenuPage.CONFIG
    session.system_menu.cursor = 0
    assert route_command(game, session, Command.ACCEPT, state)
    assert session.settings.sticky_action is True
    assert state.sticky_action is True
    assert session.settings_dirty is True
    assert route_command(game, session, Command.CANCEL, state)
    assert session.system_menu.page is SystemMenuPage.MAIN
    assert session.settings_dirty is False
    loaded, error = load_settings(session.settings_path)
    assert error is None and loaded.sticky_action is True


def test_failed_quit_save_stays_in_menu_with_live_settings(data_dir, profile, tmp_path, monkeypatch):
    game = init_game(data_dir, profile)
    game.open_modal(OpenSystemMenu())
    session = ModalSession(settings_path=tmp_path / "settings.json", settings_dirty=True)
    session.settings = Settings(dict(session.settings.bindings), True)
    session.system_menu.cursor = 2
    monkeypatch.setattr("PyAitD.app.shell.save_settings", lambda *args: "Could not save settings to target: read only")
    assert route_command(game, session, Command.ACCEPT, InputBuffer()) is True
    assert game.mode is GameMode.SYSTEM_MENU
    assert session.settings.sticky_action is True
    assert session.settings_dirty is True
    assert "read only" in session.settings_error


def test_clean_quit_saves_nothing_and_returns_false(data_dir, profile, tmp_path):
    game = init_game(data_dir, profile)
    game.open_modal(OpenSystemMenu())
    session = ModalSession(settings_path=tmp_path / "settings.json")
    session.system_menu.cursor = 2
    assert route_command(game, session, Command.ACCEPT, InputBuffer()) is False
    assert not session.settings_path.exists()


def test_dirty_quit_saves_once_then_returns_false(data_dir, profile, tmp_path):
    game = init_game(data_dir, profile)
    game.open_modal(OpenSystemMenu())
    session = ModalSession(settings_path=tmp_path / "settings.json", settings_dirty=True)
    session.system_menu.cursor = 2
    assert route_command(game, session, Command.ACCEPT, InputBuffer()) is False
    loaded, error = load_settings(session.settings_path)
    assert error is None


def test_failed_return_closes_to_play_and_keeps_the_named_error(data_dir, profile, tmp_path, monkeypatch):
    game = init_game(data_dir, profile)
    game.open_modal(OpenSystemMenu())
    session = ModalSession(settings_path=tmp_path / "settings.json", settings_dirty=True)
    session.system_menu.cursor = 0
    monkeypatch.setattr("PyAitD.app.shell.save_settings", lambda *args: "Could not save settings to target: read only")
    assert route_command(game, session, Command.ACCEPT, InputBuffer()) is True
    assert game.mode is GameMode.PLAY
    assert session.settings_dirty is True
    assert "read only" in session.settings_error


def test_successful_save_does_not_clear_an_existing_notice(data_dir, profile, tmp_path):
    game = init_game(data_dir, profile)
    game.open_modal(OpenSystemMenu())
    session = ModalSession(
        settings_path=tmp_path / "settings.json",
        settings_error="old notice", settings_dirty=True,
    )
    assert route_command(game, session, Command.CANCEL, InputBuffer()) is True
    assert game.mode is GameMode.PLAY
    assert session.settings_error == "old notice"
    loaded, error = load_settings(session.settings_path)
    assert error is None


def test_raw_capture_replaces_binding_without_activating_the_same_row(data_dir, profile):
    game = init_game(data_dir, profile)
    game.open_modal(OpenSystemMenu())
    session = ModalSession()
    session.system_menu.page = SystemMenuPage.CONFIG
    session.system_menu.cursor = 1 + REMAPPABLE_CONTROLS.index(Control.ACTION)
    session.system_menu.capture = "ACTION"
    state = InputBuffer()
    handled, running = _capture_keydown(
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_q, repeat=False),
        game, session, state,
    )
    assert (handled, running) == (True, True)
    assert session.settings.bindings["ACTION"] == ("q",)
    assert session.system_menu.capture is None
    assert list(state.commands) == []


def test_capture_escape_cancels_and_repeat_is_swallowed(data_dir, profile):
    game = init_game(data_dir, profile)
    game.open_modal(OpenSystemMenu())
    session = ModalSession()
    session.system_menu.capture = "ACTION"
    state = InputBuffer()
    repeat = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_q, repeat=True)
    assert _capture_keydown(repeat, game, session, state) == (True, True)
    assert session.system_menu.capture == "ACTION"
    escape = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, repeat=False)
    assert _capture_keydown(escape, game, session, state) == (True, True)
    assert session.system_menu.capture is None
    assert session.settings == default_settings()


def test_opening_the_system_menu_drains_held_and_queued_input(data_dir, profile):
    game = init_game(data_dir, profile)
    session = ModalSession()
    state = InputBuffer(held_joyd=9, action_held=True, sticky_armed=True,
                        action_pulse=True, commands=deque([Command.UP]))
    assert route_command(game, session, Command.CANCEL, state)
    assert game.mode is GameMode.SYSTEM_MENU
    assert (state.held_joyd, state.action_held, state.sticky_armed,
            state.action_pulse, list(state.commands)) == (0, False, False, False, [])


def test_leaving_the_system_menu_cannot_replay_input_into_the_first_play_tick(data_dir, profile):
    game = init_game(data_dir, profile)
    game.input_mode = InputMode.KEYBOARD
    game.open_modal(OpenSystemMenu())
    session = ModalSession()
    state = InputBuffer(held_joyd=9, action_held=True, sticky_armed=True,
                        action_pulse=True, commands=deque([Command.ACCEPT, Command.UP]))
    assert route_command(game, session, Command.CANCEL, state)
    assert game.mode is GameMode.PLAY
    assert (state.held_joyd, state.action_held, state.sticky_armed,
            state.action_pulse, list(state.commands)) == (0, False, False, False, [])
    apply_play_input(game, state)
    assert (game.local_joyd, game.local_click, game.action) == (0, 0, 0)


def test_quitting_from_the_system_menu_drains_the_input_buffer(data_dir, profile):
    game = init_game(data_dir, profile)
    game.open_modal(OpenSystemMenu())
    session = ModalSession()
    session.system_menu.cursor = 2
    state = InputBuffer(held_joyd=9, action_held=True, sticky_armed=True,
                        action_pulse=True, commands=deque([Command.ACCEPT]))
    assert route_command(game, session, Command.ACCEPT, state) is False
    assert (state.held_joyd, state.action_held, state.sticky_armed,
            state.action_pulse, list(state.commands)) == (0, False, False, False, [])


def test_toggle_input_mode_drains_held_and_queued_input(data_dir, profile):
    game = init_game(data_dir, profile)
    session = ModalSession()
    state = InputBuffer(held_joyd=9, action_held=True, sticky_armed=True,
                        action_pulse=True, commands=deque([Command.UP]))
    assert route_command(game, session, Command.TOGGLE_INPUT_MODE, state)
    assert (state.held_joyd, state.action_held, state.sticky_armed,
            state.action_pulse, list(state.commands)) == (0, False, False, False, [])


def test_game_starts_in_mouse_mode_with_no_intent(data_dir, profile):
    game = init_game(data_dir, profile)
    assert game.input_mode is InputMode.MOUSE
    assert game.nav_intent is None
    assert game.nav_decision is None
    assert game.nav_arrived_target == -1


def test_a_fresh_game_puts_the_hero_in_the_mode_its_input_mode_needs(data_dir, profile):
    # Object data spawns the hero in track mode 1 (tank) via init_deplacement,
    # and nothing in the hero's LIFE script changes that. With mouse as the
    # default input mode, a hero left in mode 1 makes process_track hand the
    # follower's mirrored joyd to the *keyboard* path — the "autopilot driving
    # a tank" the spec rejected — so init_game must translate it.
    game = init_game(data_dir, profile)
    assert game.actors[game.current_camera_target_actor].track_mode == 4


def test_the_input_snapshot_re_asserts_the_follower_mode(data_dir, profile):
    # a script can call LM_INIT_DEPLACEMENT and hand the hero back to mode 1 at
    # any time; the next input snapshot must take it back for the mouse
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    hero.track_mode = 1
    apply_play_input(game, InputBuffer())
    assert hero.track_mode == 4


def test_a_scripted_track_survives_the_input_snapshot(data_dir, profile):
    # the translation is 1 <-> 4 only: a cutscene that parks the hero on a
    # scripted track (mode 3) or freezes it (mode 0) keeps what it asked for
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    for mode in (0, 2, 3):
        hero.track_mode = mode
        apply_play_input(game, InputBuffer())
        assert hero.track_mode == mode


def test_keyboard_mode_hands_the_hero_back_to_tank_controls(data_dir, profile):
    game = init_game(data_dir, profile)
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


def test_restart_session_rebuilds_state_and_preserves_session_choices(data_dir, profile):
    old = init_game(data_dir, profile, hero=1)
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


def test_restart_session_rebuilds_state_from_the_initial_floor(data_dir, profile):
    # the combat venue is one supported restart boundary; floor 0 (a fresh
    # game's own floor_start) is the other, and must not be special-cased.
    old = init_game(data_dir, profile, hero=1)
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
    data_dir, profile, monkeypatch,
):
    import PyAitD.app.shell as main
    from PyAitD.engine.game import Game

    old = init_game(data_dir, profile, hero=0)
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

    def refuse_floor(self, number):
        floor_calls.append((self, number))
        raise AssertionError("restart_session must not construct a Floor")

    monkeypatch.setattr(main, "init_game", spy_init_game)
    monkeypatch.setattr(main, "enter_floor_start", spy_enter_floor_start)
    monkeypatch.setattr(Game, "load_floor", refuse_floor)

    new = main.restart_session(old)

    assert len(init_calls) == 1
    assert len(enter_calls) == 1
    assert floor_calls == []
    assert new is not old


def test_run_restart_replaces_game_and_floor_before_any_tick_or_present(monkeypatch, data_dir, profile, tmp_path):
    # Step 7: run() owns the atomic restart -- restart_session and Floor must
    # run, then the per-frame state (session/input buffer) must be reset, then
    # the scene must be recomposed, all before the loop is allowed to tick the
    # world or present a frame for the new game.
    import PyAitD.app.shell as main

    calls = []
    frame = np.zeros((200, 320, 3), dtype=np.uint8)

    old_game = init_game(data_dir, profile)
    old_game.restart_requested = True

    def spy_floor(number):
        calls.append("Floor")
        return SimpleNamespace(number=0, rooms=[SimpleNamespace(camera_indices=[0])])

    new_game = SimpleNamespace(
        _data_dir=tmp_path, current_floor=0, trace=None, mode=GameMode.PLAY,
        num_camera=-1, new_num_camera=0, flag_init_view=2, current_room=0,
        actors=[], active_modal=None, input_mode=InputMode.MOUSE,
        restart_requested=False,
        current_camera_target_actor=-1,
        inventory_count=[0, 0], inventory_table=[[-1] * 30, [-1] * 30],
        current_inventory=0, status_screen_allowed=1, assets=object(),
        load_floor=spy_floor,
        profile=profile,
    )

    def spy_restart_session(game):
        calls.append("restart_session")
        return new_game

    real_modal_session = main.ModalSession

    def spy_modal_session(*args, **kwargs):
        calls.append("ModalSession reset")
        # restart now rebuilds the session via replacement_session (carrying
        # application settings) and configures the fresh input buffer from
        # it, so the spy must produce a fully functional session.
        return real_modal_session(*args, **kwargs)

    def spy_input_buffer():
        calls.append("InputBuffer reset")
        return InputBuffer()

    def spy_scene_frame(*args):
        calls.append("_scene_frame")
        return frame, []

    def spy_play_tick(*args):
        calls.append("play_tick")
        return True

    def spy_present(ui):
        calls.append("present")

    event_batches = iter([[], [SimpleNamespace(type=main.pygame.QUIT)]])
    times = iter([0] * 8)

    monkeypatch.setattr(main, "restart_session", spy_restart_session)
    monkeypatch.setattr(main, "ModalSession", spy_modal_session)
    monkeypatch.setattr(main, "InputBuffer", spy_input_buffer)
    monkeypatch.setattr(main, "_scene_frame", spy_scene_frame)
    monkeypatch.setattr(main, "play_tick", spy_play_tick)
    monkeypatch.setattr(main, "render_active_mode", lambda *a: painter_from_frame(frame))
    monkeypatch.setattr(
        main, "Renderer",
        lambda *_a, **_k: SimpleNamespace(
            fallback_notice=None, present=spy_present, close=lambda: None,
        ),
    )
    monkeypatch.setattr(
        main.pygame.mouse, "set_visible", lambda value: None
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


def test_title_pages_by_command_then_opens_the_menu(data_dir, profile):
    from PyAitD.app.startup import credits_page_count

    game = init_game(data_dir, profile)
    game.open_modal(ShowTitle())
    session = ModalSession()
    page_count = credits_page_count(
        game.assets, game.cvars[game.profile.cvar_index("TEXTE_CREDITS")] + 1,
    )
    assert route_command(game, session, Command.ACCEPT) is True
    assert session.title.phase is TitlePhase.CREDITS and isinstance(game.active_modal, ShowTitle)
    # every page but the last stays on ShowTitle; only the last hands off
    for page in range(1, page_count):
        assert route_command(game, session, Command.ACCEPT) is True
        assert session.title.page == page and isinstance(game.active_modal, ShowTitle)
    assert route_command(game, session, Command.ACCEPT) is True
    assert isinstance(game.active_modal, OpenStartupMenu) and session.booted_via_menu


def test_title_click_advances_like_a_command(data_dir, profile):
    from PyAitD.app.startup import credits_page_count

    game = init_game(data_dir, profile)
    game.open_modal(ShowTitle())
    session = ModalSession()
    page_count = credits_page_count(
        game.assets, game.cvars[game.profile.cvar_index("TEXTE_CREDITS")] + 1,
    )
    for _ in range(page_count + 1):  # TITLE->CREDITS, then every credits page
        if isinstance(game.active_modal, OpenStartupMenu):
            break
        route_mouse(game, session, (5, 5))
    assert isinstance(game.active_modal, OpenStartupMenu)


def test_title_click_survives_the_first_render_active_mode_reset(data_dir, profile):
    # Regression: route_mouse's ShowTitle branch used to call reduce_title
    # BEFORE session.reset_for(effect) ran for the first time against this
    # ShowTitle instance -- unlike route_command, which resets first. Since
    # render_active_mode also calls session.reset_for(effect) every frame,
    # and reset_for only resets an effect the first time it observes that
    # exact identity, the click's TITLE -> CREDITS mutation used to get
    # silently replaced by a fresh TitlePresenter() the moment
    # render_active_mode ran afterwards: the player's first click on the
    # title screen did nothing.
    pygame.font.init()
    game = init_game(data_dir, profile)
    game.open_modal(ShowTitle())
    session = ModalSession()
    renderer = stub_renderer()
    assert session.title.phase is TitlePhase.TITLE
    route_mouse(game, session, (5, 5))
    assert session.title.phase is TitlePhase.CREDITS
    render_active_mode(game, session, renderer)
    assert session.title.phase is TitlePhase.CREDITS, (
        "the click's phase change must survive the first render_active_mode reset"
    )


def test_run_advances_the_title_past_its_timeout_with_no_input(data_dir, profile, monkeypatch):
    # Important 3: run()'s non-PLAY branch calls advance_title every frame,
    # but nothing exercised it through the real event loop -- deleting those
    # lines left the whole suite green. Pump run() with a monkeypatched
    # get_ticks the way the journeys do, but past TITLE_TIMEOUT_MS, and with
    # no input at all: the title must reach CREDITS on the clock alone.
    import PyAitD.app.shell as main

    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    game = init_game(data_dir, profile)
    game.open_modal(ShowTitle())
    session = ModalSession()
    idle_frames = TITLE_TIMEOUT_MS // 20 + 5   # comfortably past the timeout
    event_batches = iter(
        [[] for _ in range(idle_frames)] + [[pygame.event.Event(pygame.QUIT)]]
    )
    ticks = itertools.count(0, 20)
    monkeypatch.setattr(main, "Renderer", lambda *_a, **_k: SimpleNamespace(
        fallback_notice=None,
        present=lambda image: None,
        close=lambda: None,
    ))
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (frame, []))
    monkeypatch.setattr(main, "render_active_mode", lambda *args: painter_from_frame(frame))
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(ticks))
    monkeypatch.setattr(
        main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *args: None)
    )
    monkeypatch.setattr(main.pygame.display, "set_caption", lambda *args: None)
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda *args: None)

    assert main.run(game, session=session) == 0
    assert session.title.phase is TitlePhase.CREDITS
    assert isinstance(game.active_modal, ShowTitle), "the timeout advances the phase, not the modal"


def test_menu_new_game_opens_the_selector_and_escape_returns(data_dir, profile):
    game = init_game(data_dir, profile)
    session = ModalSession()
    open_startup_menu(game, session)
    assert route_command(game, session, Command.ACCEPT) is True
    assert isinstance(game.active_modal, ChooseCharacter)
    assert route_command(game, session, Command.CANCEL) is True          # back, not quit
    assert isinstance(game.active_modal, OpenStartupMenu)


def test_selector_escape_still_quits_without_a_menu(data_dir, profile):
    game = init_game(data_dir, profile)
    game.open_modal(ChooseCharacter())
    assert route_command(game, ModalSession(), Command.CANCEL) is False


def test_menu_quit_row_ends_the_loop_and_continue_is_inert(data_dir, profile):
    game = init_game(data_dir, profile)
    session = ModalSession()
    open_startup_menu(game, session)
    assert continue_available(session) is False
    row = StartupLayout.ROWS[StartupRow.CONTINUE.value]
    assert route_mouse(game, session, row.center) is True and isinstance(game.active_modal, OpenStartupMenu)
    row = StartupLayout.ROWS[StartupRow.QUIT.value]
    assert route_mouse(game, session, row.center) is False


def test_menu_hover_previews_rows(data_dir, profile):
    game = init_game(data_dir, profile)
    session = ModalSession()
    open_startup_menu(game, session)
    route_hover(game, session, StartupLayout.ROWS[2].center)
    assert session.startup.hover == 2
    route_hover(game, session, None)
    assert session.startup.hover is None


def test_render_active_mode_draws_title_and_menu(data_dir, profile):
    pygame.font.init()
    game = init_game(data_dir, profile)
    session = ModalSession()
    renderer = stub_renderer()
    game.open_modal(ShowTitle())
    assert render_active_mode(game, session, renderer).to_frame().shape == (200, 320, 4)
    open_startup_menu(game, session)
    assert render_active_mode(game, session, renderer).to_frame().shape == (200, 320, 4)


from PyAitD.app.shell import _boot_hero, _cutscene_end_branch
from PyAitD.engine.effects import CutsceneFinished


class _Renderer:
    def ui_scale(self):
        return 1.0

    def scene_thumbnail(self):
        return np.zeros((200, 320, 3), np.uint8)

    def compose_scene(self, frame):
        # _boot_hero's own _scene_frame call (unmocked here, unlike the
        # monkeypatched _hero_branch/_restart_branch tests above) needs a
        # real compose_scene stand-in; the returned frame is not asserted on.
        return frame


def test_boot_hero_cutscene_stages_the_intro(data_dir, profile):
    game = init_game(data_dir, profile)
    session = ModalSession()
    replaced = _boot_hero(game, _Renderer(), session, InputBuffer(), 1, cutscene=True)
    new_game, new_floor, new_session = replaced[0], replaced[1], replaced[2]
    assert (new_game.current_floor, new_game.current_room) == profile.intro_start
    assert new_floor.number == 7
    assert new_game.allow_system_menu is False and new_session.cutscene is True
    assert new_game.cvars[profile.cvar_index("CHOOSE_PERSO")] == 1


def test_boot_hero_plain_boots_the_attic(data_dir, profile):
    game = init_game(data_dir, profile)
    replaced = _boot_hero(game, _Renderer(), ModalSession(), InputBuffer(), 0, cutscene=False)
    new_game, new_session = replaced[0], replaced[2]
    assert (new_game.current_floor, new_game.current_room) == profile.game_start
    assert new_game.allow_system_menu is True and new_session.cutscene is False


def test_cutscene_end_branch_hands_over_to_the_attic_with_the_same_hero(data_dir, profile):
    game = init_game(data_dir, profile, hero=1)
    session = ModalSession(cutscene=True)
    assert _cutscene_end_branch(game, _Renderer(), session, InputBuffer()) is None
    game.open_modal(CutsceneFinished())
    replaced = _cutscene_end_branch(game, _Renderer(), session, InputBuffer())
    assert replaced is not None
    new_game, new_session = replaced[0], replaced[2]
    assert new_game.cvars[profile.cvar_index("CHOOSE_PERSO")] == 1
    assert (new_game.current_floor, new_game.current_room) == profile.game_start
    assert new_session.cutscene is False and new_game.active_modal is None


def test_skip_flag_ends_the_cutscene_from_play(data_dir, profile):
    game = init_game(data_dir, profile)
    session = ModalSession(cutscene=True, skip_cutscene=True)
    assert _cutscene_end_branch(game, _Renderer(), session, InputBuffer()) is not None


def test_cutscene_swallows_play_commands_and_marks_skip(data_dir, profile):
    game = init_game(data_dir, profile)
    session = ModalSession(cutscene=True)
    assert route_command(game, session, Command.CANCEL) is True
    assert game.active_modal is None and session.skip_cutscene is True   # no system menu opened


def test_cutscene_finished_renders_the_frozen_scene(data_dir, profile):
    pygame.font.init()
    game = init_game(data_dir, profile)
    game.open_modal(CutsceneFinished())
    frame = render_active_mode(game, ModalSession(cutscene=True), _Renderer()).to_frame()
    assert frame.shape == (200, 320, 4) and frame[..., 3].max() == 0      # transparent: scene shows through
