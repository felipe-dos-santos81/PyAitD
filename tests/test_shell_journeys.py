# SPDX-License-Identifier: GPL-2.0-only
"""M4a1 acceptance journeys: the real run() event pump, the real shell render
dispatch (render_active_mode is NOT patched here), synthetic pygame events."""
from collections import deque
import contextlib
import itertools
import json
from types import SimpleNamespace

import numpy as np
import pygame
import pytest

from PyAitD.app.shell import configure_session_input, load_runtime_session
from PyAitD.app.config import (
    SCHEMA, Control, Settings, default_settings, replace_binding, save_settings,
)
from PyAitD.app.startup import StartupLayout, StartupRow, credits_page_count
from PyAitD.engine.effects import ChooseCharacter, GameMode, InputMode, OpenSystemMenu, ShowTitle
from PyAitD.engine.game import init_game
from PyAitD.engine.playworld import play_tick as real_play_tick
from PyAitD.games.aitd1.profile import AITD1
from PyAitD.app.ui import (
    CharacterLayout, CharacterPhase, Command, InputBuffer, ModalSession,
    SettingsNoticeLayout, SystemMenuLayout, SystemMenuPage, event_to_input,
)


_FRAME = np.zeros((200, 320, 3), dtype=np.uint8)


class _HeadlessRenderer:
    def __init__(self, *_args, **_kwargs):
        self.presented = 0
        self.fallback_notice = None

    def window_to_logical(self, pos):
        return pos

    def present(self, _frame):
        self.presented += 1

    def close(self):
        pass


def _left_click(pos):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=tuple(pos))


def _key(code):
    return pygame.event.Event(pygame.KEYDOWN, key=code, repeat=False)


def _run_shell(monkeypatch, game, session, next_events, *, observe_tick=None, tick_ms=20):
    import PyAitD.app.shell as main
    renderer = _HeadlessRenderer()
    ticks = itertools.count(0, tick_ms)
    monkeypatch.setattr(main, "Renderer", lambda *_a, **_k: renderer)
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (_FRAME, []))
    monkeypatch.setattr(main.pygame.event, "get", next_events)
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(ticks))
    monkeypatch.setattr(main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *args: None))
    monkeypatch.setattr(main.pygame.display, "set_caption", lambda *args: None)
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda *args: None)
    if observe_tick is not None:
        monkeypatch.setattr(main, "play_tick", observe_tick)
    with _pygame_runtime():
        assert main.run(game, session=session) == 0
        assert renderer.presented > 0


def _quit():
    return pygame.event.Event(pygame.QUIT)


def _observe_input_snapshots(monkeypatch):
    """Record the per-tick input snapshot at the apply_play_input seam: after
    the real snapshot is applied, before the rest of the tick consumes it."""
    import PyAitD.engine.playworld as playworld
    snapshots = []
    real_apply = playworld.apply_play_input

    def spy(game, buffer):
        real_apply(game, buffer)
        snapshots.append((game.local_joyd, game.local_click, game.action))

    monkeypatch.setattr(playworld, "apply_play_input", spy)
    return snapshots


@contextlib.contextmanager
def _pygame_runtime():
    # pygame.quit() invalidates ui's module-level font cache; drop it so the
    # next journey re-creates fonts against a fresh pygame init
    from PyAitD.app import ui
    pygame.init()
    try:
        yield
    finally:
        pygame.quit()
        ui._font.cache_clear()


@pytest.mark.parametrize("portrait, expected_hero, body_archive, anim_archive", (
    (0, 1, "LISTBOD2", "LISTANI2"),  # left portrait: Emily
    (1, 0, "LISTBODY", "LISTANIM"),  # right portrait: Carnby
))
def test_one_click_hero_journey_through_the_real_loop(
    data_dir, monkeypatch, portrait, expected_hero, body_archive, anim_archive,
):
    import PyAitD.app.shell as main

    game = init_game(data_dir, AITD1)
    game.open_modal(ChooseCharacter())
    session = ModalSession()
    replacements = []
    real_init_game = main.init_game

    def spy_init_game(data, profile, hero=0):
        new_game = real_init_game(data, profile, hero=hero)
        # snapshot at replacement time: the first PLAY tick runs the real boot
        # scripts, which grant an object (the inventory is not empty by then)
        replacements.append((new_game, list(new_game.inventory_count)))
        return new_game

    monkeypatch.setattr(main, "init_game", spy_init_game)

    tick_replacement_counts = []

    def observe(game_arg, floor_arg, buffer_arg):
        tick_replacement_counts.append(len(replacements))
        return real_play_tick(game_arg, floor_arg, buffer_arg)

    state = {"frames": 0}

    def next_events():
        state["frames"] += 1
        assert state["frames"] < 200, "hero journey exceeded its budget"
        if replacements:
            return [_quit()]
        if state["frames"] == 1:
            return [_left_click(CharacterLayout.PORTRAITS[portrait].center)]
        if state["frames"] == 2:
            return [_left_click(CharacterLayout.STORY.center)]
        return []

    _run_shell(monkeypatch, game, session, next_events, observe_tick=observe)

    assert len(replacements) == 1
    new_game, boot_inventory = replacements[0]
    assert new_game.cvars[8] == expected_hero
    assert new_game.assets.body_archive_name == body_archive
    assert new_game.assets.anim_archive_name == anim_archive
    assert boot_inventory == [0, 0]
    assert tick_replacement_counts, "the confirmed hero's game must tick PLAY"
    assert all(count == 1 for count in tick_replacement_counts), (
        "no PLAY tick may run before the hero replacement"
    )


def test_keyboard_hero_journey_backs_out_and_starts_emily(data_dir, monkeypatch):
    # RIGHT, ACCEPT enters Carnby's story; CANCEL returns to the portraits;
    # LEFT, OPEN_INVENTORY enters Emily's story; OPEN_INVENTORY starts her.
    import PyAitD.app.shell as main

    game = init_game(data_dir, AITD1)
    game.open_modal(ChooseCharacter())
    session = ModalSession()
    replacements = []
    real_init_game = main.init_game

    def spy_init_game(data, profile, hero=0):
        new_game = real_init_game(data, profile, hero=hero)
        replacements.append(new_game)
        return new_game

    monkeypatch.setattr(main, "init_game", spy_init_game)

    snapshots = []
    state = {"frames": 0}

    def next_events():
        state["frames"] += 1
        assert state["frames"] < 200, "keyboard journey exceeded its budget"
        if replacements:
            return [_quit()]
        snapshots.append((
            session.character.choice, session.character.phase,
            session.pending_hero,
        ))
        events = {
            1: [pygame.K_RIGHT],
            2: [pygame.K_SPACE],
            3: [pygame.K_ESCAPE],
            4: [pygame.K_LEFT],
            5: [pygame.K_RETURN],
            6: [pygame.K_RETURN],
        }.get(state["frames"], [])
        return [_key(code) for code in events]

    _run_shell(monkeypatch, game, session, next_events)

    assert len(snapshots) == 6
    for before, after in zip(snapshots, snapshots[1:]):
        changed = sum(a != b for a, b in zip(before, after))
        assert changed == 1, (
            f"each event must advance exactly one state, {before} -> {after}"
        )
    assert snapshots[-1] == (0, CharacterPhase.STORY, None)
    assert len(replacements) == 1
    assert replacements[0].cvars[8] == 1, "the final hero must be Emily"
    assert replacements[0].assets.body_archive_name == "LISTBOD2"


def test_menu_remap_sticky_save_and_reload_journey(data_dir, monkeypatch, tmp_path):
    game = init_game(data_dir, AITD1)
    path = tmp_path / "settings.json"
    session = load_runtime_session(path)
    assert session.settings_error is None

    # the tick wrapper records the input snapshot the real play_tick consumed
    observed = _observe_input_snapshots(monkeypatch)
    state = {"frames": 0}

    def next_events():
        state["frames"] += 1
        frames = state["frames"]
        assert frames < 200, "menu journey exceeded its budget"
        if frames == 1:
            return [_key(pygame.K_ESCAPE)]
        if frames == 2:
            return [_left_click(SystemMenuLayout.MAIN_ROWS[1].center)]
        if frames == 3:
            return [_left_click(SystemMenuLayout.CONFIG_ROWS[0].center)]
        if frames == 4:
            return [_left_click(SystemMenuLayout.CONFIG_ROWS[1].center)]
        if frames == 5:
            return [_key(pygame.K_q)]
        if frames == 6:
            return [_left_click(SystemMenuLayout.CONFIG_ROWS[-1].center)]
        if frames == 7:
            return [_left_click(SystemMenuLayout.MAIN_ROWS[0].center)]
        if frames == 8:
            return [_key(pygame.K_TAB)]
        if frames == 9:
            return [_key(pygame.K_SPACE)]
        if frames == 10:
            return [_key(pygame.K_q)]
        if frames >= 12:
            return [_quit()]
        return []

    _run_shell(monkeypatch, game, session, next_events)

    # sticky arm -> one direction key produces exactly one action pulse
    assert observed.count((1, 1, 0x2000)) == 1
    pulse_at = observed.index((1, 1, 0x2000))
    assert observed[pulse_at + 1][1] == 0, "the pulse lasts exactly one tick"
    assert game.input_mode is InputMode.KEYBOARD

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == SCHEMA
    assert payload["bindings"]["UP"] == ["q"]
    assert payload["sticky_action"] is True

    # a fresh boot loads the same settings off disk and compiles the same
    # behavior: q walks, sticky arm stays sequential and keyboard-only
    with _pygame_runtime():
        reloaded = load_runtime_session(path)
        assert reloaded.settings_error is None
        buffer = InputBuffer()
        configure_session_input(reloaded, buffer)
        assert buffer.bindings[pygame.K_q] is Control.UP
        assert buffer.sticky_action is True
        event_to_input(_key(pygame.K_SPACE), buffer)
        assert buffer.sticky_armed is True
        event_to_input(_key(pygame.K_q), buffer)
        assert buffer.held_joyd == 1
        assert buffer.action_pulse is True
        assert buffer.sticky_armed is False


def test_capture_consumes_the_captured_key_exclusively(data_dir, monkeypatch):
    # During ACTION capture a Return press becomes the binding; it must not
    # also reach the reducer and activate/toggle a row in the same frame.
    game = init_game(data_dir, AITD1)
    session = ModalSession()
    state = {"frames": 0}

    def next_events():
        state["frames"] += 1
        frames = state["frames"]
        assert frames < 200, "capture journey exceeded its budget"
        if frames == 1:
            return [_key(pygame.K_ESCAPE)]
        if frames == 2:
            return [_left_click(SystemMenuLayout.MAIN_ROWS[1].center)]
        if frames == 3:
            # CONFIG row 5: Sticky (0) then UP/DOWN/LEFT/RIGHT (1-4), ACTION
            return [_left_click(SystemMenuLayout.CONFIG_ROWS[5].center)]
        if frames == 4:
            assert session.system_menu.capture == "ACTION", "fixture"
            return [_key(pygame.K_RETURN)]
        if frames == 5:
            return [_quit()]
        return []

    _run_shell(monkeypatch, game, session, next_events)

    assert session.settings.bindings["ACTION"] == ("return",)
    # the steal leaves INVENTORY_CONFIRM with its other key
    assert session.settings.bindings["INVENTORY_CONFIRM"] == ("i",)
    assert session.system_menu.capture is None
    # no replay: the menu did not activate or toggle anything that frame
    assert session.system_menu.page is SystemMenuPage.CONFIG
    assert session.system_menu.cursor == 5
    assert session.settings.sticky_action is False
    assert game.mode is GameMode.SYSTEM_MENU
    assert isinstance(game.active_modal, OpenSystemMenu)


def test_menu_entry_and_exit_never_replay_held_input(data_dir, monkeypatch):
    import PyAitD.engine.playworld as playworld

    game = init_game(data_dir, AITD1)
    game.input_mode = InputMode.KEYBOARD
    session = ModalSession()

    observed = []
    state = {"frames": 0, "close_frame": None}
    real_apply = playworld.apply_play_input

    def observe(game_arg, buffer_arg):
        snapshot = (
            buffer_arg.held_joyd, buffer_arg.action_held,
            buffer_arg.sticky_armed, buffer_arg.action_pulse,
        )
        real_apply(game_arg, buffer_arg)
        observed.append({
            "frame": state["frames"],
            "buffer": snapshot,
            "tick": (game_arg.local_joyd, game_arg.local_click, game_arg.action),
        })

    monkeypatch.setattr(playworld, "apply_play_input", observe)

    def next_events():
        state["frames"] += 1
        frames = state["frames"]
        assert frames < 200, "drain journey exceeded its budget"
        if frames == 1:
            return [_key(pygame.K_UP), _key(pygame.K_SPACE)]
        if frames == 3:
            assert game.mode is GameMode.PLAY, "fixture"
            return [_key(pygame.K_ESCAPE)]
        if frames == 4:
            assert game.mode is GameMode.SYSTEM_MENU, "the menu must be open"
            state["close_frame"] = frames
            return [
                _key(pygame.K_DOWN), _key(pygame.K_SPACE),
                _left_click(SystemMenuLayout.MAIN_ROWS[0].center),
            ]
        if frames == 5:
            assert game.mode is GameMode.PLAY, "Return must close the menu"
            return [_quit()]
        return []

    _run_shell(monkeypatch, game, session, next_events)

    assert observed[0]["tick"] == (1, 1, 0x2000), (
        "fixture: held movement/action really drives PLAY ticks before the menu"
    )
    resumed = [entry for entry in observed if entry["frame"] == state["close_frame"]]
    assert resumed, "the close frame must tick PLAY once"
    assert resumed[0]["buffer"] == (0, False, False, False), (
        "held and sticky state must be drained at the menu boundary"
    )
    assert resumed[0]["tick"] == (0, 0, 0), (
        "the first resumed PLAY tick must not replay held movement or action"
    )


def test_corrupt_boot_and_save_failure_notices_dismiss_without_mode_change(
    data_dir, monkeypatch, tmp_path,
):
    import PyAitD.app.shell as main

    path = tmp_path / "settings.json"
    path.write_text("{ definitely not json", encoding="utf-8")
    session = load_runtime_session(path)
    # skip_intro: this journey tests the settings notice and the system
    # menu after the hero replacement, not the opening cutscene
    session.skip_intro = True
    assert session.settings_error is not None
    assert str(path) in session.settings_error

    game = init_game(data_dir, AITD1)
    game.open_modal(ChooseCharacter())

    # the hero replacement swaps run()'s game AND session atomically, so the
    # journey tracks the live pair through the two constructor seams
    live = {"game": game, "session": session}
    real_init_game = main.init_game
    real_modal_session = main.ModalSession

    def spy_init_game(data, profile, hero=0):
        live["game"] = real_init_game(data, profile, hero=hero)
        return live["game"]

    def spy_modal_session(*args, **kwargs):
        live["session"] = real_modal_session(*args, **kwargs)
        return live["session"]

    monkeypatch.setattr(main, "init_game", spy_init_game)
    monkeypatch.setattr(main, "ModalSession", spy_modal_session)

    save_calls = []
    monkeypatch.setattr(
        main, "save_settings",
        lambda *args: save_calls.append(args)
        or f"Could not save settings to {path}: forced failure",
    )

    state = {"frames": 0}

    def next_events():
        state["frames"] += 1
        frames = state["frames"]
        assert frames < 200, "notice journey exceeded its budget"
        game_now, session_now = live["game"], live["session"]
        if frames == 1:
            return [_left_click(SettingsNoticeLayout.DISMISS.center)]
        if frames == 2:
            # the Dismiss click cleared only the notice: same mode, same effect
            assert session_now.settings_error is None
            assert game_now.mode is GameMode.CHARACTER_SELECT
            assert session_now.character.phase is CharacterPhase.PORTRAITS
            assert session_now.pending_hero is None
            return [_left_click(CharacterLayout.PORTRAITS[1].center)]
        if frames == 3:
            return [_left_click(CharacterLayout.STORY.center)]
        if frames == 4:
            # the hero replacement carried the application session forward
            assert live["game"] is not game
            assert game_now.mode is GameMode.PLAY
            return [_key(pygame.K_ESCAPE)]
        if frames == 5:
            assert game_now.mode is GameMode.SYSTEM_MENU
            return [_left_click(SystemMenuLayout.MAIN_ROWS[1].center)]
        if frames == 6:
            return [_left_click(SystemMenuLayout.CONFIG_ROWS[0].center)]
        if frames == 7:
            return [_left_click(SystemMenuLayout.CONFIG_ROWS[-1].center)]
        if frames == 8:
            # the failed save leaves the notice up over the unchanged menu
            assert session_now.settings_error is not None
            assert str(path) in session_now.settings_error
            assert game_now.mode is GameMode.SYSTEM_MENU
            assert session_now.system_menu.page is SystemMenuPage.MAIN
            return [_key(pygame.K_SPACE)]
        if frames == 9:
            # ACCEPT dismissed the notice instead of activating a row
            assert session_now.settings_error is None
            assert game_now.mode is GameMode.SYSTEM_MENU
            assert isinstance(game_now.active_modal, OpenSystemMenu)
            assert session_now.system_menu.page is SystemMenuPage.MAIN
            assert session_now.system_menu.cursor == 0
            return [_quit()]
        return []

    _run_shell(monkeypatch, game, session, next_events)

    assert len(save_calls) == 1, "the Back boundary saves exactly once"


def test_letterbox_click_does_not_crash_or_dismiss_the_notice(
    data_dir, monkeypatch, tmp_path,
):
    # window_to_logical returns None for clicks outside the 320x200 view
    # (letterbox/pillar bands); the notice pre-check must None-guard like
    # route_mouse and resolve_play_click do, and a None click hits no target
    path = tmp_path / "settings.json"
    path.write_text("{ definitely not json", encoding="utf-8")
    session = load_runtime_session(path)
    assert session.settings_error is not None

    game = init_game(data_dir, AITD1)
    game.open_modal(ChooseCharacter())

    monkeypatch.setattr(
        _HeadlessRenderer, "window_to_logical", lambda _self, _pos: None,
    )

    state = {"frames": 0}

    def next_events():
        state["frames"] += 1
        assert state["frames"] < 200, "letterbox journey exceeded its budget"
        if state["frames"] == 1:
            return [_left_click((0, 0))]
        if state["frames"] == 2:
            # no exception, and the None click did NOT dismiss the notice
            assert session.settings_error is not None
            assert game.mode is GameMode.CHARACTER_SELECT
            assert session.character.phase is CharacterPhase.PORTRAITS
            return [_quit()]
        return []

    _run_shell(monkeypatch, game, session, next_events)


def test_death_restart_keeps_live_settings_and_drops_input_transients(
    data_dir, tmp_path, monkeypatch,
):
    import PyAitD.app.shell as main

    game = init_game(data_dir, AITD1)
    game.restart_requested = True
    remapped = replace_binding(default_settings(), Control.UP, "q")
    settings = Settings(remapped.bindings, True)
    path = tmp_path / "settings.json"
    session = ModalSession(
        settings=settings, settings_path=path,
        settings_error="visible error", settings_dirty=True,
    )
    dirty_buffer = InputBuffer(
        held_joyd=9, action_held=True, sticky_armed=True, action_pulse=True,
        commands=deque([Command.UP]),
    )

    monkeypatch.setattr(main, "InputBuffer", lambda: dirty_buffer)
    monkeypatch.setattr(main, "Floor", lambda *args: SimpleNamespace(number=0))
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (_FRAME, []))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: 0)

    with _pygame_runtime():
        result = main._restart_branch(game, SimpleNamespace(), session)

    assert result is not None
    new_session, new_buffer = result[2], result[3]
    assert new_session.settings == settings
    assert new_session.settings_path == path
    assert new_session.settings_error == "visible error"
    assert new_session.settings_dirty is True
    assert new_buffer is dirty_buffer
    assert (new_buffer.held_joyd, new_buffer.action_held, new_buffer.sticky_armed,
            new_buffer.action_pulse, list(new_buffer.commands)) == (
        0, False, False, False, [],
    )
    assert new_buffer.bindings[pygame.K_q] is Control.UP
    assert new_buffer.sticky_action is True


def test_settings_reload_reads_the_file_fresh(tmp_path):
    # two independent load_runtime_session calls around a real save_settings:
    # the second boot reads bytes off disk, not a reused object
    path = tmp_path / "settings.json"
    first = load_runtime_session(path)
    assert first.settings == default_settings()
    assert first.settings_error is None

    changed = Settings(
        replace_binding(default_settings(), Control.UP, "q").bindings, True,
    )
    assert save_settings(changed, path) is None

    second = load_runtime_session(path)
    assert second.settings_error is None
    assert second.settings == changed
    assert second.settings is not first.settings

    with _pygame_runtime():
        buffer = InputBuffer()
        configure_session_input(second, buffer)
        assert buffer.bindings[pygame.K_q] is Control.UP
        assert pygame.K_w not in buffer.bindings, "the remap steals, not adds"
        assert buffer.sticky_action is True


def test_mouse_only_remap_journey_binds_through_the_key_picker(data_dir, monkeypatch, tmp_path):
    # A pointer-only user rebinds ACTION without any physical key: the control
    # row opens the picker, hover previews a cell, one click binds it, and the
    # menu returns to Configuration with the same row selected.
    from PyAitD.app.ui import PICKABLE_KEYS
    game = init_game(data_dir, AITD1)
    path = tmp_path / "settings.json"
    session = load_runtime_session(path)
    state = {"frames": 0}
    picker_rows = SystemMenuLayout.rows(SystemMenuPage.KEY_PICK)
    q_cell = picker_rows[PICKABLE_KEYS.index("q")]

    def next_events():
        state["frames"] += 1
        frames = state["frames"]
        assert frames < 200, "picker journey exceeded its budget"
        if frames == 1:
            return [_key(pygame.K_ESCAPE)]
        if frames == 2:
            return [_left_click(SystemMenuLayout.MAIN_ROWS[1].center)]
        if frames == 3:
            return [_left_click(SystemMenuLayout.CONFIG_ROWS[5].center)]
        if frames == 4:
            assert session.system_menu.page is SystemMenuPage.KEY_PICK, "fixture"
            assert session.system_menu.capture == "ACTION", "fixture"
            return [pygame.event.Event(pygame.MOUSEMOTION, pos=tuple(q_cell.center))]
        if frames == 5:
            assert session.system_menu.hover == PICKABLE_KEYS.index("q")
            assert session.settings.bindings["ACTION"] == ("space",), "hover never binds"
            return [_left_click(q_cell.center)]
        if frames == 6:
            assert session.system_menu.page is SystemMenuPage.CONFIG
            assert session.system_menu.cursor == 5
            assert session.system_menu.capture is None
            # Cancel path: reopen the picker and click Cancel
            return [_left_click(SystemMenuLayout.CONFIG_ROWS[5].center)]
        if frames == 7:
            return [_left_click(picker_rows[-1].center)]
        if frames == 8:
            assert session.system_menu.page is SystemMenuPage.CONFIG
            return [_left_click(SystemMenuLayout.CONFIG_ROWS[-1].center)]
        if frames == 9:
            return [_left_click(SystemMenuLayout.MAIN_ROWS[0].center)]
        if frames >= 11:
            return [_quit()]
        return []

    _run_shell(monkeypatch, game, session, next_events)

    assert session.settings.bindings["ACTION"] == ("q",)
    assert game.mode is GameMode.PLAY
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["bindings"]["ACTION"] == ["q"]


def test_journey_title_menu_select_play_by_mouse(data_dir, monkeypatch, tmp_path):
    # title -> credits (all 8 pages) -> menu -> New game -> Emily's portrait
    # -> her story page -> the atomic hero replacement -> PLAY, all through
    # the real run() event pump and the real shell render dispatch.
    game = init_game(data_dir, AITD1)
    game.open_modal(ShowTitle())
    path = tmp_path / "settings.json"
    session = load_runtime_session(path)
    seen = []
    credits_entry = game.cvars[AITD1.cvar_index("TEXTE_CREDITS")] + 1
    page_count = credits_page_count(game.assets, credits_entry)
    frames = iter([
        [_left_click((160, 100))],                                        # title -> credits
        *([[_left_click((160, 100))]] * page_count),                      # page through credits -> menu
        [_left_click(StartupLayout.ROWS[StartupRow.NEW_GAME.value].center)],
        [_left_click(CharacterLayout.PORTRAITS[0].center)],               # Emily portrait -> story
        [_left_click((160, 100))],                                        # story page -> confirm
        [], [],                                                           # hero branch + one PLAY frame
        [_quit()],
    ])

    def next_events():
        return next(frames, [_quit()])

    def observe_tick(game_, floor, buf):
        seen.append(game_.cvars[AITD1.cvar_index("CHOOSE_PERSO")])
        return real_play_tick(game_, floor, buf)

    _run_shell(monkeypatch, game, session, next_events, observe_tick=observe_tick)
    assert seen and seen[0] == 1                                          # Emily is hero 1


def test_journey_title_menu_select_play_by_keyboard(data_dir, monkeypatch, tmp_path):
    # same title -> credits (all pages) -> menu -> New game path, but by
    # keyboard: Return (bound to INVENTORY_CONFIRM, translated to ACCEPT by
    # every non-PLAY modal router) advances the title/credits/menu, Escape
    # bounces out of the selector back to the menu, Right + Return picks
    # Carnby and starts.
    game = init_game(data_dir, AITD1)
    game.open_modal(ShowTitle())
    path = tmp_path / "settings.json"
    session = load_runtime_session(path)
    seen = []
    credits_entry = game.cvars[AITD1.cvar_index("TEXTE_CREDITS")] + 1
    page_count = credits_page_count(game.assets, credits_entry)
    frames = iter([
        [_key(pygame.K_RETURN)],                                          # title -> credits
        *([[_key(pygame.K_RETURN)]] * page_count),                        # page through credits -> menu
        [_key(pygame.K_RETURN)],                                          # New game
        [_key(pygame.K_ESCAPE)],                                          # back to menu
        [_key(pygame.K_RETURN)],                                          # New game again
        [_key(pygame.K_RIGHT)], [_key(pygame.K_RETURN)], [_key(pygame.K_RETURN)],   # Carnby, story, confirm
        [], [],
        [_quit()],
    ])

    def next_events():
        return next(frames, [_quit()])

    def observe_tick(game_, floor, buf):
        seen.append(game_.cvars[AITD1.cvar_index("CHOOSE_PERSO")])
        return real_play_tick(game_, floor, buf)

    _run_shell(monkeypatch, game, session, next_events, observe_tick=observe_tick)
    assert seen and seen[0] == 0                                          # Carnby is hero 0


def _confirm_emily_events(game):
    # title -> credits (all pages, data-dependent count) -> menu -> New game
    # -> Emily's portrait -> her story page -> confirm. Mirrors the credits
    # paging the other title-menu-select journeys above do, since the credits
    # page count is a property of the installed game data, not a fixed "1".
    credits_entry = game.cvars[AITD1.cvar_index("TEXTE_CREDITS")] + 1
    page_count = credits_page_count(game.assets, credits_entry)
    return [
        [_left_click((160, 100))],                                        # title -> credits
        *([[_left_click((160, 100))]] * page_count),                      # page through credits -> menu
        [_left_click(StartupLayout.ROWS[StartupRow.NEW_GAME.value].center)],
        [_left_click(CharacterLayout.PORTRAITS[0].center)],               # Emily portrait -> story
        [_left_click((160, 100))],                                        # story page -> confirm
    ]


def test_journey_opening_plays_to_the_end_then_the_attic(data_dir, monkeypatch):
    # title -> credits -> menu -> New game -> Emily, then the real floor-7
    # opening ticked entirely through the real run() event pump (not
    # test_intro.py's headless play_tick loop): the letter, the walk through
    # floors 7 -> 3 -> 2 -> 1, CutsceneFinished, then the attic hand-over
    # (startGame(0, 0, 1)). Emily's own animation timing reaches
    # CutsceneFinished at tick 7220 (not the 7293 pinned for Carnby in
    # tests/test_intro.py -- that spike booted hero=0); this journey asserts
    # only the floor sequence and the terminal attic, not a tick number.
    game = init_game(data_dir, AITD1)
    game.open_modal(ShowTitle())
    session = ModalSession()
    floors = []
    # 650 padding frames x up to 12-13 ticks/frame (250 ms cap / 20 ms tick)
    # comfortably clears the ~594 frames empirically needed to reach the
    # attic (game.timer 7220 at CutsceneFinished for Emily); the run ends via
    # the trailing _quit() once floors has already reached the attic.
    frames = iter(_confirm_emily_events(game) + [[]] * 650 + [[_quit()]])

    def next_events():
        return next(frames, [_quit()])

    def observe_tick(game_, floor, buf):
        if not floors or floors[-1] != floor.number:
            floors.append(floor.number)
        return real_play_tick(game_, floor, buf)

    _run_shell(
        monkeypatch, game, session, next_events,
        observe_tick=observe_tick, tick_ms=250,
    )
    assert floors[:4] == [7, 3, 2, 1] and floors[-1] == 0


def test_journey_a_click_skips_the_opening(data_dir, monkeypatch):
    # Same boot as above, but a click partway through the opening ends it
    # early: PlayWorld(allowSystemMenu=0) breaks on any key or click
    # (mainLoop.cpp:71-89), so the shell hands off to the attic without ever
    # reaching CutsceneFinished on its own. Proves the skip actually happened
    # mid-cutscene (floor 7 is reached, then the attic) and that no GameOver
    # modal was ever involved (Emily's own opening runs to a GameOver-shaped
    # CutsceneFinished around tick 7220 if never skipped -- see the journey
    # above -- so skipping this early must never let a real GameOver form).
    game = init_game(data_dir, AITD1)
    game.open_modal(ShowTitle())
    session = ModalSession()
    floors = []
    frames = iter(
        _confirm_emily_events(game)
        + [[], [], [_left_click((10, 10))], [], [], [_quit()]]
    )

    def next_events():
        return next(frames, [_quit()])

    def observe_tick(game_, floor, buf):
        floors.append(floor.number)
        return real_play_tick(game_, floor, buf)

    _run_shell(monkeypatch, game, session, next_events, observe_tick=observe_tick)
    assert 7 in floors and floors[-1] == 0
    assert game.mode is not GameMode.GAME_OVER
