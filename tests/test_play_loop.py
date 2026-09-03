# SPDX-License-Identifier: GPL-2.0-only
from types import SimpleNamespace

import numpy as np
import pytest

from PyAitD.engine.data.floor import Floor
from PyAitD.engine.script.game import init_game
from PyAitD.engine.script.life import life_gate
from PyAitD.engine.nav.navmesh import agent_extent
from PyAitD.engine.nav.picking import STEER_DISTANCE, project_floor_point

from tests.conftest import painter_from_frame

pytestmark = [pytest.mark.shell, pytest.mark.journey]


def test_life_gate(data_dir, profile):
    game = init_game(data_dir, profile, hero=0)
    a = game.actors[0]
    a.life, a.life_mode = -1, -1
    assert not life_gate(a)
    a.life, a.life_mode = 3, 0
    assert life_gate(a)
    a.life, a.life_mode = 3, -1
    assert not life_gate(a)
    a.life, a.life_mode = -1, 0
    assert not life_gate(a)


def test_apply_play_input_mapping(data_dir, profile):
    from PyAitD.engine.script.effects import InputMode
    from PyAitD.engine.script.playworld import apply_play_input
    from PyAitD.app.ui import InputBuffer
    game = init_game(data_dir, profile)
    # this asserts the keyboard mapping specifically; mouse is the default
    # input_mode (task 9: playworld — wire the follower into the input
    # snapshot), so it must be selected explicitly to exercise this path.
    game.input_mode = InputMode.KEYBOARD
    state = InputBuffer(held_joyd=9, action_held=True)
    apply_play_input(game, state)
    assert game.local_joyd == 9
    assert game.local_click == 1
    assert game.action == 0x2000


def test_sticky_action_pulse_is_visible_for_exactly_one_keyboard_tick(data_dir, profile):
    from PyAitD.engine.script.effects import InputMode
    from PyAitD.engine.script.playworld import apply_play_input
    game = init_game(data_dir, profile)
    game.input_mode = InputMode.KEYBOARD
    state = InputBuffer(action_pulse=True)
    apply_play_input(game, state)
    assert (game.local_click, game.action, state.action_pulse) == (1, 0x2000, False)
    apply_play_input(game, state)
    assert (game.local_click, game.action, state.action_pulse) == (0, 0, False)


def test_mouse_mode_ignores_and_consumes_a_stale_sticky_pulse(data_dir, profile):
    from PyAitD.engine.script.playworld import apply_play_input
    game = init_game(data_dir, profile)
    state = InputBuffer(action_pulse=True)
    apply_play_input(game, state)
    assert state.action_pulse is False


def test_run_coalesces_catch_up_ticks_into_one_present_per_frame(profile, monkeypatch, tmp_path):
    import PyAitD.app.shell as main
    from PyAitD.engine.script.effects import GameMode, InputMode

    calls = []
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    event_batches = iter(
        [[], [SimpleNamespace(type=main.pygame.QUIT)]]
    )
    times = iter([0, 100, 100])

    monkeypatch.setattr(
        main, "Renderer",
        lambda *_a, **_k: SimpleNamespace(
            fallback_notice=None,
            present=lambda image: calls.append("present"), close=lambda: None,
        ),
    )
    monkeypatch.setattr(
        main, "play_tick", lambda *args: calls.append("tick") or True
    )
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

    game = SimpleNamespace(
        _data_dir=tmp_path, current_floor=0, trace=None, mode=GameMode.PLAY,
        num_camera=-1, new_num_camera=0, flag_init_view=0, current_room=0,
        actors=[], active_modal=None, input_mode=InputMode.MOUSE,
        restart_requested=False,
        current_camera_target_actor=-1,
        inventory_count=[0, 0], inventory_table=[[-1] * 30, [-1] * 30],
        current_inventory=0, status_screen_allowed=1, assets=object(),
        load_floor=lambda number: SimpleNamespace(
            number=0, rooms=[SimpleNamespace(camera_indices=[0])],
        ),
        profile=profile,
    )
    assert main.run(game) == 0
    assert calls == ["tick"] * 5 + ["present", "present"]


def test_the_loop_paints_one_canvas_at_the_renderer_scale(data_dir, profile, monkeypatch):
    # Task 9: render_active_mode builds exactly one UIPainter, at the live
    # Renderer's ui_scale(), and hands it back directly -- no per-branch
    # painter and no separate bridge painter in run().
    import PyAitD.app.shell as main
    game = init_game(data_dir, profile)
    renderer = SimpleNamespace(ui_scale=lambda: 4.0)
    painter = main.render_active_mode(game, ModalSession(), renderer)
    assert painter.scale == 4.0
    assert painter.to_frame().shape[:2] == (800, 1280)


def test_run_latches_a_hit_erased_by_a_later_catch_up_tick(data_dir, profile, monkeypatch):
    import PyAitD.app.shell as main
    from PyAitD.engine.script.game import Game

    source = np.full((200, 320, 3), 80, dtype=np.uint8)
    presented = []
    event_batches = iter([[], [main.pygame.event.Event(main.pygame.QUIT)]])
    times = iter([0, 40, 40])
    game = init_game(data_dir, profile)
    hit_actor_idx = game.current_camera_target_actor
    hit_actor = game.actors[hit_actor_idx]
    ticks = []

    def publish_then_clear(_game, _floor, _input_buffer):
        ticks.append(1)
        hit_actor.hit_by = 17 if len(ticks) == 1 else -1

    monkeypatch.setattr(
        Game, "load_floor",
        lambda self, number: SimpleNamespace(number=0, rooms=[SimpleNamespace(camera_indices=[0])]),
    )
    monkeypatch.setattr(main, "Renderer", lambda *_a, **_k: SimpleNamespace(
        fallback_notice=None, ui_scale=lambda: 1.0,
        present=lambda ui: presented.append(ui.to_frame()), close=lambda: None,
    ))
    monkeypatch.setattr(main, "play_tick", publish_then_clear)
    monkeypatch.setattr(
        main, "_scene_frame",
        lambda *_args: (source, [(hit_actor_idx, (100, 60, 200, 160))]),
    )
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda _value: None)
    monkeypatch.setattr(main.pygame.display, "set_caption", lambda *_args: None)
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(times))
    monkeypatch.setattr(
        main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *_args: None),
    )

    assert main.run(game) == 0
    assert len(ticks) == 2
    assert hit_actor.hit_by == -1, "the second catch-up tick did not erase the pulse"
    # present() now receives the 320x200 RGBA UI-overlay canvas (transparent
    # until a presenter draws on it), not a composite with the scene baked
    # in -- see PyAitD.app.ui.transparent_canvas. A pixel only "reached
    # presentation" if it is both the expected colour and fully opaque.
    assert np.any(
        np.all(presented[0][:, :, :3] == (255, 255, 255), axis=2) & (presented[0][:, :, 3] == 255)
    )
    assert np.any(
        (presented[0][:, :, 0] == 255)
        & (presented[0][:, :, 1] <= 64)
        & (presented[0][:, :, 2] <= 64)
        & (presented[0][:, :, 3] == 255)
    ), "the erased hit never reached presentation"


def test_run_expires_hit_feedback_instead_of_latching_forever(data_dir, profile, monkeypatch):
    import PyAitD.app.shell as main
    from PyAitD.engine.script.game import Game

    source = np.full((200, 320, 3), 80, dtype=np.uint8)
    presented = []
    event_batches = iter([
        [], [], [main.pygame.event.Event(main.pygame.QUIT)],
    ])
    times = iter([0, 20, 200, 1000])
    game = init_game(data_dir, profile)
    hit_actor_idx = game.current_camera_target_actor
    hit_actor = game.actors[hit_actor_idx]
    ticks = []

    def publish_once(_game, _floor, _input_buffer):
        ticks.append(1)
        hit_actor.hit_by = 17 if len(ticks) == 1 else -1

    monkeypatch.setattr(
        Game, "load_floor",
        lambda self, number: SimpleNamespace(number=0, rooms=[SimpleNamespace(camera_indices=[0])]),
    )
    monkeypatch.setattr(main, "Renderer", lambda *_a, **_k: SimpleNamespace(
        fallback_notice=None, ui_scale=lambda: 1.0,
        present=lambda ui: presented.append(ui.to_frame()), close=lambda: None,
    ))
    monkeypatch.setattr(main, "play_tick", publish_once)
    monkeypatch.setattr(
        main, "_scene_frame",
        lambda *_args: (source, [(hit_actor_idx, (100, 60, 200, 160))]),
    )
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda _value: None)
    monkeypatch.setattr(main.pygame.display, "set_caption", lambda *_args: None)
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(times))
    monkeypatch.setattr(
        main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *_args: None),
    )

    from PyAitD.app.ui import transparent_canvas

    assert main.run(game) == 0
    # present() now receives the 320x200 RGBA UI-overlay canvas (transparent
    # until a presenter draws on it), not a composite with the scene baked
    # in -- see PyAitD.app.ui.transparent_canvas. A pixel only "shows" the
    # feedback if it is both the expected colour and fully opaque; once the
    # feedback expires with nothing else drawn (no HUD, no cursor -- hover
    # never moves in this test), the overlay reverts to fully transparent.
    assert np.any(
        np.all(presented[1][:, :, :3] == (255, 255, 255), axis=2) & (presented[1][:, :, 3] == 255)
    ), (
        "feedback expired before a later frame could show it"
    )
    assert np.array_equal(presented[-1], transparent_canvas()), (
        "feedback was still visible almost a second after the hit"
    )


def test_escape_opens_the_system_menu_and_pauses_play_ticks(data_dir, profile, monkeypatch):
    # Escape in PLAY opens the paused system menu instead of quitting: no
    # fixed-step tick runs while the menu is up, and the loop still presents
    # exactly once per frame.
    import PyAitD.app.shell as main
    from PyAitD.engine.script.game import Game

    calls = []
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    escape = SimpleNamespace(type=main.pygame.KEYDOWN, key=main.pygame.K_ESCAPE)
    event_batches = iter(
        [[escape], [], [], [SimpleNamespace(type=main.pygame.QUIT)]]
    )
    times = iter([0] * 8)

    monkeypatch.setattr(
        Game, "load_floor",
        lambda self, number: SimpleNamespace(number=0, rooms=[SimpleNamespace(camera_indices=[0])]),
    )
    monkeypatch.setattr(
        main, "Renderer",
        lambda *_a, **_k: SimpleNamespace(
            fallback_notice=None,
            present=lambda image: calls.append("present"), close=lambda: None,
        ),
    )
    monkeypatch.setattr(
        main, "play_tick", lambda *args: calls.append("tick") or True
    )
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
    assert main.run(game) == 0
    assert game.mode is GameMode.SYSTEM_MENU
    assert "tick" not in calls, "PLAY ticks must pause while the menu is open"
    assert calls == ["present"] * 4


def test_motion_prev_does_not_survive_a_play_to_menu_to_play_round_trip(
    data_dir, profile, monkeypatch,
):
    # Minor 6: the non-PLAY branch (the system menu here) resets accumulator
    # to 0 but must also drop motion_prev, or the resume frame -- if no new
    # tick runs before the next present -- blends against the stale,
    # pre-menu snapshot and the actor pops backward by up to one tick.
    import PyAitD.app.shell as main
    from PyAitD.app.config import default_settings
    from PyAitD.engine.script.game import Game

    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    blends = []

    def spy_scene_frame(_g, _f, _r, _resolver, blend=None):
        blends.append(blend)
        return frame, []

    escape = SimpleNamespace(type=main.pygame.KEYDOWN, key=main.pygame.K_ESCAPE)
    # frame 1: PLAY, elapsed 25ms -- one tick runs, motion_prev is set.
    # frame 2: escape opens the system menu (not PLAY this frame).
    # frame 3: escape closes it (PLAY again), elapsed 5ms -- no new tick.
    # frame 4: quit.
    event_batches = iter([[], [escape], [escape], [SimpleNamespace(type=main.pygame.QUIT)]])
    times = iter([0, 25, 30, 35, 35])

    monkeypatch.setattr(
        Game, "load_floor",
        lambda self, number: SimpleNamespace(number=0, rooms=[SimpleNamespace(camera_indices=[0])]),
    )
    monkeypatch.setattr(main, "Renderer", lambda *_a, **_k: SimpleNamespace(
        fallback_notice=None, present=lambda image: None, close=lambda: None,
    ))
    monkeypatch.setattr(main, "play_tick", lambda *args: True)
    monkeypatch.setattr(main, "_scene_frame", spy_scene_frame)
    monkeypatch.setattr(main, "render_active_mode", lambda *args: painter_from_frame(frame))
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda value: None)
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(times))
    monkeypatch.setattr(
        main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *args: None)
    )

    game = init_game(data_dir, profile)
    session = ModalSession(settings=default_settings())
    assert session.settings.render.motion == "smooth"          # the shipped default
    with _pygame_runtime():
        assert main.run(game, session=session) == 0

    # scene_frame is only called in PLAY frames: pre-loop, frame 1, frame 3
    # (the menu-open frame skips it entirely) and frame 4.
    assert len(blends) == 4
    assert blends[2] is None, (
        "the resume frame must not blend against the pre-menu snapshot"
    )


def test_run_skips_scene_recompute_and_caption_on_transition_frames(profile, monkeypatch, tmp_path):
    # M3a draw_ready gate: a floor/room-change tick leaves num_camera == -1
    # with current_room stale until the next tick's change_salle, so the loop
    # must reuse the previous frame instead of recomputing the scene or
    # indexing floor.rooms[current_room] (IndexError / wrong camera).
    import PyAitD.app.shell as main
    from PyAitD.engine.script.effects import GameMode, InputMode

    scene_calls = []
    presented = []
    frame = np.zeros((200, 320, 3), dtype=np.uint8)

    def scene_frame(*args):
        scene_calls.append(1)
        return frame, []

    def tick(game, floor, input_buffer):
        game.num_camera = -1  # floor-change tick: change_salle pending
        return False

    event_batches = iter(
        [[], [SimpleNamespace(type=main.pygame.QUIT)]]
    )
    times = iter([0, 100, 100])

    monkeypatch.setattr(
        main, "Renderer",
        lambda *_a, **_k: SimpleNamespace(
            fallback_notice=None, present=lambda ui: presented.append(ui.to_frame()),
            close=lambda: None,
        ),
    )
    monkeypatch.setattr(main, "play_tick", tick)
    monkeypatch.setattr(main, "_scene_frame", scene_frame)
    monkeypatch.setattr(main, "render_active_mode", lambda *args: painter_from_frame(frame))
    monkeypatch.setattr(
        main.pygame.mouse, "set_visible", lambda value: None
    )
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(times))
    monkeypatch.setattr(
        main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *args: None)
    )

    game = SimpleNamespace(
        _data_dir=tmp_path, current_floor=0, trace=None, mode=GameMode.PLAY,
        num_camera=0, new_num_camera=0, flag_init_view=0, current_room=0,
        actors=[], active_modal=None, input_mode=InputMode.MOUSE,
        restart_requested=False,
        current_camera_target_actor=-1,
        inventory_count=[0, 0], inventory_table=[[-1] * 30, [-1] * 30],
        current_inventory=0, status_screen_allowed=1, assets=object(),
        load_floor=lambda number: SimpleNamespace(number=0, rooms=[]),
        profile=profile,
    )
    assert main.run(game) == 0
    assert len(scene_calls) == 1  # only the pre-loop frame, reused after
    assert len(presented) == 2


def test_scene_frame_delegates_to_build_frame_and_compose_scene(monkeypatch):
    """_scene_frame's own contract (task 9, updated by task-5 fix-1): call
    build_frame(game, floor, resolver, blend, shadows=renderer.options.shadows),
    hand its FrameDescription -- and nothing else -- to renderer.compose_scene,
    and return (that thumbnail, build_frame's own draw_list) unmodified.
    build_frame's own draw_list correctness is test_scene.py's job; this pins
    the wiring around it and needs no game data, unlike the old 6-arg
    compose_scene call this replaced. The `shadows` keyword is read off
    renderer.options rather than threaded through _scene_frame's own
    parameters: renderer.options is the authoritative post-set_options
    value, so reading it there instead of adding a parameter (and threading
    it through every _scene_frame call site) is the only way the frame and
    the backend can't disagree about the mode -- the fake renderer below
    stands in for that authoritative value."""
    import PyAitD.app.shell as main

    game = SimpleNamespace(assets="assets-marker")
    floor = SimpleNamespace()
    sentinel_frame = SimpleNamespace(marker="frame")
    sentinel_draw_list = [(0, (1, 2, 3, 4))]
    calls = {}

    def fake_build_frame(passed_game, passed_floor, passed_resolver, passed_blend, shadows):
        calls["build_frame"] = (passed_game, passed_floor, passed_resolver, passed_blend, shadows)
        return sentinel_frame, sentinel_draw_list

    monkeypatch.setattr(main, "build_frame", fake_build_frame)

    class FakeRenderer:
        options = SimpleNamespace(shadows="room")

        def compose_scene(self, frame):
            calls["compose_scene"] = frame
            return "thumbnail"

    resolver = object()
    composed, draw_list = main._scene_frame(game, floor, FakeRenderer(), resolver)

    assert calls["build_frame"] == (game, floor, resolver, None, "room")
    assert calls["compose_scene"] is sentinel_frame
    assert composed == "thumbnail"
    assert draw_list is sentinel_draw_list


def test_scene_frame_requires_a_resolver_instead_of_silently_defaulting_one(monkeypatch):
    """_scene_frame must never build its own AssetResolver(game.assets) as a
    fallback: that would silently drop whatever texture_dir the caller's
    resolver was configured with. Every real call site (run()'s pre-loop and
    per-frame calls, both branch functions) always has a resolver in hand and
    passes it explicitly -- this pins that resolver stays a required
    parameter, not a defaulted one, so a future edit can't reintroduce the
    silent-degradation path."""
    import inspect

    import PyAitD.app.shell as main

    parameters = inspect.signature(main._scene_frame).parameters
    assert parameters["resolver"].default is inspect.Parameter.empty

    with pytest.raises(TypeError):
        main._scene_frame(SimpleNamespace(), SimpleNamespace(), SimpleNamespace())


import contextlib


@contextlib.contextmanager
def _pygame_runtime():
    # A real Renderer calls pygame.init() before configure_session_input
    # ever runs; every stub Renderer in this file skips that, and
    # configure_session_input's key-binding validation still reaches
    # pygame.key.key_code, which warns without it. Same helper as
    # tests/test_shell_journeys.py's _pygame_runtime -- pygame.quit() also
    # invalidates ui's module-level font cache, so that is dropped too.
    import pygame

    from PyAitD.app import ui
    pygame.init()
    try:
        yield
    finally:
        pygame.quit()
        ui._font.cache_clear()


def _fake_game(tmp_path, profile, **overrides):
    """A minimal stand-in for a real Game, shaped exactly like the one
    test_run_coalesces_catch_up_ticks_into_one_present_per_frame and
    test_run_skips_scene_recompute_and_caption_on_transition_frames already
    drive main.run() with -- reused here so the six run()-level behaviours
    below (Renderer construction, fallback_notice propagation, resolver
    default/threading) can each get a synthetic, no-game-data test that
    actually drives the real run() loop."""
    from PyAitD.engine.script.effects import GameMode, InputMode

    fields = dict(
        _data_dir=tmp_path, current_floor=0, trace=None, mode=GameMode.PLAY,
        num_camera=-1, new_num_camera=0, flag_init_view=0, current_room=0,
        actors=[], active_modal=None, input_mode=InputMode.MOUSE,
        restart_requested=False,
        current_camera_target_actor=-1,
        inventory_count=[0, 0], inventory_table=[[-1] * 30, [-1] * 30],
        current_inventory=0, status_screen_allowed=1, assets=object(),
        messages=(),
        load_floor=lambda number: SimpleNamespace(
            number=0, rooms=[SimpleNamespace(camera_indices=[0])],
        ),
        profile=profile,
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_run_constructs_renderer_with_the_session_s_render_options(monkeypatch, tmp_path, profile):
    """run()'s Renderer(session.settings.render) call (task 9 review finding
    2): every existing Renderer stub is `lambda *_a, **_k: ...`, so nothing
    else asserts the options object actually reaches the constructor."""
    import PyAitD.app.shell as main
    from dataclasses import replace as dc_replace
    from PyAitD.app.config import default_settings
    from PyAitD.render.render_options import RenderOptions

    render_options = RenderOptions(scale=6, shading="flat", background_filter="xbr")
    settings = dc_replace(default_settings(), render=render_options)
    session = ModalSession(settings=settings)

    seen_options = []
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    event_batches = iter([[SimpleNamespace(type=main.pygame.QUIT)]])
    times = iter([0, 0])

    def spy_renderer(options):
        seen_options.append(options)
        return SimpleNamespace(
            fallback_notice=None, present=lambda image: None, close=lambda: None,
        )

    monkeypatch.setattr(main, "Renderer", spy_renderer)
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (frame, []))
    monkeypatch.setattr(main, "render_active_mode", lambda *args: painter_from_frame(frame))
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda value: None)
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(times))
    monkeypatch.setattr(main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *a: None))

    with _pygame_runtime():
        assert main.run(_fake_game(tmp_path, profile), session=session) == 0
    assert seen_options == [render_options]


def test_run_propagates_renderer_fallback_notice_into_settings_error(monkeypatch, tmp_path, profile):
    """run()'s `if renderer.fallback_notice and session.settings_error is
    None: session.settings_error = renderer.fallback_notice` (task 9 review
    finding 2): every existing Renderer stub hardcodes fallback_notice=None,
    so nothing exercises the propagation, or the "don't clobber an existing
    error" guard on the same line."""
    import PyAitD.app.shell as main

    frame = np.zeros((200, 320, 3), dtype=np.uint8)

    def _run_once(session):
        event_batches = iter([[SimpleNamespace(type=main.pygame.QUIT)]])
        times = iter([0, 0])
        monkeypatch.setattr(main, "Renderer", lambda *_a, **_k: SimpleNamespace(
            fallback_notice="Enhanced rendering unavailable",
            present=lambda image: None, close=lambda: None,
        ))
        monkeypatch.setattr(main, "_scene_frame", lambda *args: (frame, []))
        monkeypatch.setattr(main, "render_active_mode", lambda *args: painter_from_frame(frame))
        monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda value: None)
        monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
        monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(times))
        monkeypatch.setattr(main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *a: None))
        with _pygame_runtime():
            return main.run(_fake_game(tmp_path, profile), session=session)

    fresh_session = ModalSession()
    assert fresh_session.settings_error is None
    assert _run_once(fresh_session) == 0
    assert fresh_session.settings_error == "Enhanced rendering unavailable"

    session_with_error = ModalSession(settings_error="an existing error")
    assert _run_once(session_with_error) == 0
    assert session_with_error.settings_error == "an existing error"


def test_run_builds_one_resolver_and_threads_it_through_scene_frame_calls(monkeypatch, tmp_path, profile):
    """run()'s `resolver = resolver or AssetResolver(game.assets,
    session.settings.render.texture_dir)` and its threading into every
    _scene_frame call (task 9 review finding 2): exactly one AssetResolver
    gets built for a run with no hero swap or restart, carrying the
    session's texture_dir, and the *same* instance reaches both the
    pre-loop and the per-frame _scene_frame call."""
    import PyAitD.app.shell as main
    from dataclasses import replace as dc_replace
    from PyAitD.app.config import default_settings
    from PyAitD.render.render_options import RenderOptions

    settings = dc_replace(
        default_settings(), render=RenderOptions(texture_dir="/tmp/custom-override"),
    )
    session = ModalSession(settings=settings)
    game = _fake_game(tmp_path, profile)

    built = []

    class SpyAssetResolver:
        def __init__(self, assets, texture_dir):
            self.assets = assets
            self.texture_dir = texture_dir
            built.append(self)

    seen_resolvers = []
    blends_seen = []
    frame = np.zeros((200, 320, 3), dtype=np.uint8)

    def spy_scene_frame(_g, _f, _r, resolver, blend=None):
        seen_resolvers.append(resolver)
        blends_seen.append(blend)
        return frame, []

    event_batches = iter([[], [SimpleNamespace(type=main.pygame.QUIT)]])
    times = iter([0, 20, 20])

    monkeypatch.setattr(main, "Renderer", lambda *_a, **_k: SimpleNamespace(
        fallback_notice=None, present=lambda image: None, close=lambda: None,
    ))
    monkeypatch.setattr(main, "AssetResolver", SpyAssetResolver)
    monkeypatch.setattr(main, "_scene_frame", spy_scene_frame)
    monkeypatch.setattr(main, "render_active_mode", lambda *args: painter_from_frame(frame))
    monkeypatch.setattr(main, "play_tick", lambda *a: True)
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda value: None)
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(times))
    monkeypatch.setattr(main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *a: None))

    with _pygame_runtime():
        assert main.run(game, session=session) == 0
    assert len(built) == 1
    assert built[0].assets is game.assets
    assert built[0].texture_dir == "/tmp/custom-override"
    assert len(seen_resolvers) >= 2  # the pre-loop call and at least one per-frame call
    assert all(resolver is built[0] for resolver in seen_resolvers)
    # the pre-loop call never blends (no prior tick to blend from), but a
    # PLAY-loop call must receive the tick's blend argument -- pins that
    # run() actually threads it through rather than regressing to
    # `_scene_frame(game, floor, renderer, resolver)` with no blend at all
    assert blends_seen[0] is None
    assert any(b is not None for b in blends_seen[1:])


def test_resolver_for_wraps_new_assets_with_the_given_texture_dir():
    """_resolver_for (task 9 review finding 2): a brand-new helper with no
    test at all before this. Pins that it wraps the *given* assets object
    with the *given* texture_dir string -- nothing more, no reach into
    another resolver's private state (the review's ruling against the old
    `getattr(resolver, "_texture_dir", None)` design)."""
    import PyAitD.app.shell as main
    from pathlib import Path
    from PyAitD.render.asset_resolver import AssetResolver

    resolver = main._resolver_for("assets-marker", "/custom/override")
    assert isinstance(resolver, AssetResolver)
    assert resolver._assets == "assets-marker"
    assert resolver._texture_dir == Path("/custom/override")

    none_resolver = main._resolver_for("assets-marker", None)
    assert none_resolver._texture_dir is None


def test_hero_branch_builds_its_resolver_from_the_session_s_texture_dir(monkeypatch, profile):
    """The override-survives-a-hero-swap behaviour _resolver_for exists for
    (task 9 review finding 2): _hero_branch must build the new game's
    resolver from session.settings.render.texture_dir, not silently drop
    it. No game data needed -- init_game/Floor/_take_over_play_input/
    _scene_frame are all stubbed so only the resolver-building line is
    exercised for real."""
    import PyAitD.app.shell as main
    from dataclasses import replace as dc_replace
    from PyAitD.engine.script.effects import InputMode
    from PyAitD.render.asset_resolver import AssetResolver
    from PyAitD.app.config import default_settings
    from PyAitD.render.render_options import RenderOptions
    from pathlib import Path

    new_game = SimpleNamespace(
        _data_dir="ignored", current_floor=0, trace=None, new_num_camera=0,
        assets="new-assets-marker", profile=profile,
        load_floor=lambda number: SimpleNamespace(number=0),
    )
    monkeypatch.setattr(main, "init_game", lambda data, profile, hero: new_game)
    monkeypatch.setattr(main, "_take_over_play_input", lambda *a: None)
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (None, []))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: 0)

    settings = dc_replace(default_settings(), render=RenderOptions(texture_dir="/custom/dir"))
    session = ModalSession(settings=settings)
    session.pending_hero = 1
    # skip_intro: this test exercises only the resolver-building line with a
    # bare SimpleNamespace new_game -- the real intro cutscene's start_game
    # needs a real Game (actors, world state, ...), which is out of scope here
    session.skip_intro = True
    old_game = SimpleNamespace(
        _data_dir="ignored", trace=None, profile=profile, input_mode=InputMode.MOUSE,
    )

    with _pygame_runtime():
        result = main._hero_branch(old_game, SimpleNamespace(), session, InputBuffer())

    new_resolver = result[-1]
    assert isinstance(new_resolver, AssetResolver)
    assert new_resolver._assets == "new-assets-marker"
    assert new_resolver._texture_dir == Path("/custom/dir")


def test_restart_branch_builds_its_resolver_from_the_session_s_texture_dir(monkeypatch, profile):
    """Same override-survives-a-restart behaviour as the hero-swap test
    above, for _restart_branch."""
    import PyAitD.app.shell as main
    from dataclasses import replace as dc_replace
    from PyAitD.render.asset_resolver import AssetResolver
    from PyAitD.app.config import default_settings
    from PyAitD.render.render_options import RenderOptions
    from pathlib import Path

    new_game = SimpleNamespace(
        _data_dir="ignored", current_floor=0, new_num_camera=0,
        assets="restarted-assets-marker", profile=profile,
        load_floor=lambda number: SimpleNamespace(number=0),
    )
    monkeypatch.setattr(main, "restart_session", lambda game: new_game)
    monkeypatch.setattr(main, "_take_over_play_input", lambda *a: None)
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (None, []))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: 0)

    settings = dc_replace(default_settings(), render=RenderOptions(texture_dir="/another/dir"))
    session = ModalSession(settings=settings)
    old_game = SimpleNamespace(restart_requested=True)

    with _pygame_runtime():
        result = main._restart_branch(old_game, SimpleNamespace(), session, InputBuffer())

    new_resolver = result[-1]
    assert isinstance(new_resolver, AssetResolver)
    assert new_resolver._assets == "restarted-assets-marker"
    assert new_resolver._texture_dir == Path("/another/dir")


class _FakeAssets:
    def __init__(self, real_assets, anim):
        self._real = real_assets
        self._anim = anim

    def body(self, index):
        return self._real.body(index)

    def anim(self, index):
        return self._anim

    def life(self, index):
        return self._real.life(index)

    def track(self, index):
        return self._real.track(index)


def test_gere_anim_walk_step(data_dir, profile):
    # GereAnim movement port: walk anim with a 20-tick keyframe stepping
    # (0, 0, 4); each keyframe commit moves the actor +4 in X (beta 0x300:
    # walkStep outputs crossed, animMoveZ = cos*step, animMoveX = -sin*step).
    # First tick is bp=0 (inter), so the first commit lands on tick 21.
    from PyAitD.engine.actor.actors import gere_anim
    from PyAitD.engine.data.formats import Animation, Frame

    game = init_game(data_dir, profile, hero=0)
    actor = game.actors[game.current_camera_target_actor]
    actor.beta = 0x300
    actor.anim = 0
    actor.anim_type = 1  # repeat: no one-shot re-arm at end of anim
    actor.new_anim = -1
    actor.num_of_frames = 1
    game.assets = _FakeAssets(
        game.assets, Animation(num_frames=1, num_groups=0, frames=[Frame(20, (0, 0, 4), [], [])])
    )
    for speed in (1, 2, 3, 4, 5, -1, 0):
        actor.speed = speed
        actor.room_x = 0
        actor.room_z = 0
        for _ in range(21):
            game.timer += 1
            gere_anim(game, game.current_camera_target_actor)
        assert actor.room_x == 4
        assert actor.room_z == 0


def test_gere_anim_one_shot_rearm(data_dir, profile):
    # FITD anim.cpp:654-660: one-shot (non-repeat) anim wrap with no pending
    # anim clears ANIM_UNINTERRUPTABLE and restarts the anim as ANIM_REPEAT
    from PyAitD.engine.actor.actors import gere_anim
    from PyAitD.engine.data.formats import Animation, Frame

    game = init_game(data_dir, profile, hero=0)
    actor = game.actors[game.current_camera_target_actor]
    actor.anim = 0
    actor.anim_type = 2  # not repeat (bit 0 clear) + uninterruptable
    actor.anim_info = 0  # same anim
    actor.new_anim = -1
    actor.num_of_frames = 1
    game.assets = _FakeAssets(
        game.assets, Animation(num_frames=1, num_groups=0, frames=[Frame(20, (0, 0, 0), [], [])])
    )
    for _ in range(21):
        game.timer += 1
        gere_anim(game, game.current_camera_target_actor)
    assert actor.flag_end_anim == 1
    assert actor.anim_type == 1
    assert actor.anim_info == -1
    assert actor.new_anim == -1


def test_depth_sort_far_first():
    # FITD sortActorList: farther actors draw first (painter's algorithm)
    from PyAitD.engine.actor.actors import sort_actor_indices
    from PyAitD.engine.script.game import Actor, Game
    game = Game.__new__(Game)
    game.actors = [Actor(index_in_world=-1) for _ in range(4)]
    game.current_room = 0
    game.actors[1] = Actor(index_in_world=1, body_num=1, zv=[100, 200, 0, 100, 100, 200])
    game.actors[2] = Actor(index_in_world=2, body_num=1, zv=[150, 250, 0, 100, 300, 400])
    # actor 2 is farther from the camera -> must draw FIRST (painter's algorithm)
    assert sort_actor_indices(game, 0, 0, 0) == [2, 1]


def test_depth_sort_y_bands():
    # different y bands: compare translateY - 2000 - y (no XZ overlap logic)
    from PyAitD.engine.actor.actors import sort_actor_indices
    from PyAitD.engine.script.game import Actor, Game
    game = Game.__new__(Game)
    game.actors = [Actor(index_in_world=-1) for _ in range(4)]
    game.current_room = 0
    game.actors[1] = Actor(index_in_world=1, body_num=1, zv=[0, 10, 0, 10, 0, 10])
    game.actors[2] = Actor(index_in_world=2, body_num=1, zv=[0, 10, 5000, 5010, 0, 10])
    order = sort_actor_indices(game, 0, 0, 0)
    assert len(order) == 2


from PyAitD.app.shell import _is_interactable, resolve_play_click, route_play_click
from PyAitD.engine.script.effects import GameMode, InputMode
from PyAitD.engine.script.game import AF_ANIMATED, AF_FOUNDABLE
from PyAitD.engine.script.interaction import _finish_take, inventory_items
from PyAitD.games.aitd1.scenario import enter_combat_venue
from PyAitD.app.ui import InputBuffer, ModalSession, PlayLayout
from tests.conftest import held_pointer


def _state_for(floor, room_idx, cam_slot):
    # test scaffolding: route_play_click's floor path goes through
    # pick_floor, which builds its own camera state internally, so this
    # has no production caller — it exists only to reproduce a click's
    # screen coordinates for project_floor_point in the test below.
    from PyAitD.engine.space.world import CameraState
    room = floor.rooms[room_idx]
    camera = floor.cameras[room.camera_indices[cam_slot]]
    return CameraState.from_camera(
        camera, room.world_x, room.world_y, room.world_z,
    ).angles()


def test_a_floor_click_becomes_a_walk_intent(data_dir, profile):
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    hero = game.actors[game.current_camera_target_actor]
    screen = project_floor_point(
        _state_for(floor, hero.room, game.num_camera),
        hero.room_x + 1500, hero.world_y, hero.room_z,
    )
    route_play_click(game, ModalSession(), floor, (int(screen[0]), int(screen[1])), [])
    assert game.nav_intent is not None
    assert game.nav_intent.target_object_idx == -1


def test_a_click_on_an_actor_becomes_a_target_intent(data_dir, profile):
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    # The draw list only contains body-bearing actors. The target itself must
    # be interactable; plain scenery is handled as a blocked occluder.
    other_idx = next(
        i for i, a in enumerate(game.actors)
        if a.index_in_world >= 0 and a.body_num != -1
        and i != game.current_camera_target_actor
        and _is_interactable(game, i)
    )
    draw_list = [(other_idx, (100, 60, 200, 160))]
    route_play_click(game, ModalSession(), floor, (150, 100), draw_list)
    assert game.nav_intent is not None
    assert game.nav_intent.target_object_idx == game.actors[other_idx].index_in_world


def test_opening_wardrobe_resolves_and_routes_as_a_held_push(data_dir, profile):
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    actor_idx = game.world_objects[4].obj_index
    draw = [(actor_idx, (100, 60, 200, 160))]

    kind, payload = resolve_play_click(game, floor, (150, 100), draw)

    assert kind == "push"
    assert payload[3] == 4
    route_play_click(game, ModalSession(), floor, (150, 100), draw)
    assert game.nav_intent.requires_hold is True
    assert game.nav_intent.engaged is False


def test_a_pixel_with_no_floor_under_it_steers_instead_of_refusing(
        data_dir, profile):
    """Walking is always possible: a wall, a ceiling or the sky steers.

    The old answer was `blocked` and a red X, which left whole screenfuls of
    pixels doing nothing at all. A pixel that names no reachable place still
    names a direction, and that is what it now means -- the destination sits
    far along the bearing from the hero through the pointer, and the engine's
    own collision decides where he actually stops.
    """
    from PyAitD.engine.nav.picking import STEER_DISTANCE, project_floor_point
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    hero = game.actors[game.current_camera_target_actor]
    here = (hero.room_x + hero.step_x, hero.room_z + hero.step_z)
    pixel = (0, 0)
    assert main_pick_floor_any_room(game, floor, pixel) is None, (
        "the fixture pixel must be one the floor pick refuses"
    )

    kind, payload = resolve_play_click(game, floor, pixel, [])

    assert kind == "steer"
    dest_x, dest_z, room, object_idx = payload
    assert (room, object_idx) == (hero.room, -1)
    reach = ((dest_x - here[0]) ** 2 + (dest_z - here[1]) ** 2) ** 0.5
    assert abs(reach - STEER_DISTANCE) < 2, "the destination is a bearing, not a place"
    state = _state_for(floor, hero.room, game.num_camera)
    feet = project_floor_point(state, here[0], hero.world_y, here[1])
    step = (
        here[0] + (dest_x - here[0]) * 400 / reach,
        here[1] + (dest_z - here[1]) * 400 / reach,
    )
    walked = project_floor_point(state, step[0], hero.world_y, step[1])
    assert walked is not None and walked[1] < feet[1], (
        "a step along the steer must head up-screen, toward the pixel"
    )


def test_a_steer_press_walks_while_held_and_stops_on_release(data_dir, profile):
    """The whole point of the change: an unreachable pixel still walks.

    Asserted on the follower's own output rather than on displacement,
    because a steer aimed at a wall is *supposed* to end with the hero
    pressed against it -- collision deciding where he stops is the design.
    Walking is what the decision says, and the release still ends it.
    """
    import PyAitD.app.shell as main
    from PyAitD.engine.script.playworld import play_tick
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    game.current_floor_data = floor
    hero = game.actors[game.current_camera_target_actor]
    buf = held_pointer((0, 0))

    route_play_click(game, ModalSession(), floor, (0, 0), [], buf)

    assert game.nav_intent is not None and game.nav_intent.steering is True
    for _ in range(4):
        play_tick(game, floor, buf)
    assert game.nav_decision is not None and game.nav_decision.advance is True
    assert hero.speed == 4, "a steer walks; only a double press runs"

    buf.pointer_held = False
    play_tick(game, floor, buf)

    assert game.nav_intent is None, "the release still ends the intent"


def test_a_cell_that_cannot_be_snapped_walks_the_hero_toward_it(
        data_dir, profile, monkeypatch):
    """A steer really moves the hero, not just the decision.

    The pixel is an ordinary walkable one whose snap is refused, which is what
    the snap budget does to a cell whose walkable neighbours all project too
    far away. Before, that was a red X and a hero who stayed put; now he walks
    that way, and this measures the ground he covers.
    """
    import PyAitD.app.shell as main
    from PyAitD.engine.script.playworld import play_tick
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    game.current_floor_data = floor
    hero = game.actors[game.current_camera_target_actor]
    screen = _floor_screen_point(game, floor, 1500, 0)
    pixel = (int(screen[0]), int(screen[1]))
    assert resolve_play_click(game, floor, pixel, [])[0] == "walk", (
        "the fixture pixel must be an ordinary walkable one"
    )
    monkeypatch.setattr(main, "nearest_walkable", lambda *a, **k: None)
    start = (hero.room_x + hero.step_x, hero.room_z + hero.step_z)
    buf = held_pointer(pixel)

    route_play_click(game, ModalSession(), floor, pixel, [], buf)
    assert game.nav_intent.steering is True
    for _ in range(8):
        play_tick(game, floor, buf)

    moved = (hero.room_x + hero.step_x, hero.room_z + hero.step_z)
    assert moved != start, "the unsnappable pixel left the hero standing still"
    assert moved[0] > start[0], f"the hero walked {start} -> {moved}, not toward the pixel"


def main_pick_floor_any_room(game, floor, pixel):
    import PyAitD.app.shell as main
    hero = game.actors[game.current_camera_target_actor]
    return main.pick_floor_any_room(
        pixel, floor, hero.room, game.num_camera, hero.world_y,
        agent=main.agent_extent(hero),
    )


def test_a_snap_past_the_budget_steers_instead_of_walking_somewhere_else(
        data_dir, profile, monkeypatch):
    # A pointer on a blocked cell whose only walkable neighbours project more
    # than SNAP_BUDGET_PX away must not walk to one of them: the hero never
    # heads for somewhere visibly away from the pointer. It steers along the
    # bearing through the pointer instead, which is the one direction that
    # cannot surprise the player. nearest_walkable is replaced by a stand-in
    # that refuses whenever a filter is given, which is exactly what the real
    # search does when every ring candidate fails the budget.
    import PyAitD.app.shell as main
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    hero = game.actors[game.current_camera_target_actor]
    agent = main.agent_extent(hero)
    # Bottom-of-screen pixels foreshorten so hard that even a blocked cell's
    # nearest walkable neighbour can project dozens of pixels away -- past
    # any camera slot's budget. Loop slots inside the pixel scan (as the task
    # brief anticipates) to find a pixel/slot pair where a blocked cell's
    # snap genuinely lands inside SNAP_BUDGET_PX under the real resolver.
    found = None
    for p in _sampled_pixels():
        for slot in range(len(floor.rooms[hero.room].camera_indices)):
            hit = main.pick_floor_any_room(p, floor, hero.room, slot, hero.world_y, agent=agent)
            if hit is None or game.nav_meshes.mesh_for(floor, hit[2], agent).is_walkable(hit[0], hit[1]):
                continue
            game.num_camera = slot
            if resolve_play_click(game, floor, p, [])[0] == "walk":
                found = p
                break
        if found is not None:
            break
    assert found is not None, "no attic pixel/camera pair snaps a blocked cell within budget"
    pixel = found
    assert resolve_play_click(game, floor, pixel, [])[0] == "walk", "the real snap accepts this pixel"

    seen = {}

    def refusing(mesh, x, z, max_cells=6, accept=None):
        seen["accept"] = accept
        return None
    monkeypatch.setattr(main, "nearest_walkable", refusing)
    kind, payload = resolve_play_click(game, floor, pixel, [])
    assert kind == "steer"
    assert callable(seen["accept"]), "the resolver did not hand nearest_walkable a filter"
    hero = game.actors[game.current_camera_target_actor]
    here = (hero.room_x + hero.step_x, hero.room_z + hero.step_z)
    reach = ((payload[0] - here[0]) ** 2 + (payload[1] - here[1]) ** 2) ** 0.5
    assert abs(reach - STEER_DISTANCE) < 2, "a bearing, not the nearest cell"


def test_object_approach_uses_a_visibility_filter(data_dir, profile, monkeypatch):
    import PyAitD.app.shell as main
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    seen = {}
    real = main.approach_cell

    def spy(mesh, x, z, from_x, from_z, max_cells=main.TARGET_SNAP_CELLS, accept=None):
        seen["accept"] = accept
        return real(mesh, x, z, from_x, from_z, max_cells, accept)
    monkeypatch.setattr(main, "approach_cell", spy)
    # world object 13 (actor 10) is floor 0's clickable interactable; hand the
    # resolver its bbox so the click lands on it
    target = game.actors[10]
    draw_list = [(10, (0, 0, 319, 199))]
    kind, _payload = resolve_play_click(game, floor, (160, 100), draw_list)
    assert kind in ("target", "blocked")
    assert callable(seen.get("accept")), "the resolver did not hand approach_cell a filter"


def test_an_object_with_no_visible_approach_cell_retries_unfiltered(data_dir, profile,
                                                                    monkeypatch):
    # The visibility filter is a preference, never a veto. A camera that can
    # see no approach cell must not make the object unreachable: the search
    # runs again with no filter, and the click is still a target.
    import PyAitD.app.shell as main
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    real = main.approach_cell
    calls = []

    def spy(mesh, x, z, from_x, from_z, max_cells=main.TARGET_SNAP_CELLS, accept=None):
        calls.append(accept)
        if accept is not None:
            return None      # the filtered search finds nothing
        return real(mesh, x, z, from_x, from_z, max_cells, accept)
    monkeypatch.setattr(main, "approach_cell", spy)
    target = game.actors[10]
    draw_list = [(10, (0, 0, 319, 199))]
    kind, payload = resolve_play_click(game, floor, (160, 100), draw_list)

    assert [call is None for call in calls] == [False, True], (
        "the filtered search must run first and the unfiltered one only after it"
    )
    assert kind == "target"
    assert payload[:2] != (target.room_x, target.room_z), (
        "the unfiltered retry produced no approach cell"
    )


def test_an_object_with_no_approach_cell_at_all_still_targets_its_centre(
        data_dir, profile, monkeypatch,
):
    # The base behaviour, preserved: with no walkable neighbour anywhere the
    # destination is the object's own centre and find_path deals with it.
    # Returning "blocked" here made every object click on 87 camera slots
    # unusable, because the filter refused every cell in those rooms.
    import PyAitD.app.shell as main
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    monkeypatch.setattr(main, "approach_cell", lambda *_args, **_kwargs: None)
    target = game.actors[10]
    kind, payload = resolve_play_click(game, floor, (160, 100), [(10, (0, 0, 319, 199))])

    assert kind == "target"
    assert payload == (
        target.room_x, target.room_z, target.room, target.index_in_world,
    )


def test_latched_push_cursor_survives_pointer_drift(data_dir, profile):
    # A held push must remain visually unambiguous while the pointer moves
    # elsewhere; resolving current hover here would advertise another action.
    from PyAitD.app.shell import _play_cursor_kind
    from PyAitD.engine.script.interaction import apply_click_intent

    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    apply_click_intent(game, 10, 20, 0, 4, requires_hold=True)

    assert _play_cursor_kind(
        game, floor, (0, 0), [], InputBuffer(pointer_held=True),
    ) == "push"
    assert _play_cursor_kind(game, floor, (0, 0), [], InputBuffer()) == "steer", (
        "with no hold the resolver answers for itself, and a pixel over "
        "nothing steers rather than refusing"
    )


def test_mouseup_cancels_only_a_hold_required_intent(data_dir, profile):
    from PyAitD.engine.script.interaction import apply_click_intent, cancel_held_nav_intent

    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    apply_click_intent(game, 100, 200, hero.room)
    assert cancel_held_nav_intent(game) is False
    assert game.nav_intent is not None

    apply_click_intent(game, 100, 200, hero.room, 4, requires_hold=True)
    assert cancel_held_nav_intent(game) is True
    assert game.nav_intent is None


def test_pointer_invalidation_routes_mouseup_and_focus_loss(data_dir, profile):
    import PyAitD.app.shell as main
    from PyAitD.engine.script.interaction import apply_click_intent

    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    for event in (
        main.pygame.event.Event(main.pygame.MOUSEBUTTONUP, button=1),
        main.pygame.event.Event(main.pygame.WINDOWFOCUSLOST),
    ):
        apply_click_intent(game, 100, 200, hero.room, 4, requires_hold=True)
        assert main._cancel_pointer_invalidation(game, event, InputBuffer()) is True
        assert game.nav_intent is None


@pytest.mark.parametrize(
    ("event_factory", "touch", "expected_input"),
    [
        (
            lambda pygame: pygame.event.Event(
                pygame.MOUSEBUTTONUP, button=1, touch=False,
            ),
            False,
            (False, True, 8, True, False, None),
        ),
        (
            lambda pygame: pygame.event.Event(pygame.WINDOWFOCUSLOST),
            False,
            (False, False, 0, False, False, None),
        ),
        (
            lambda pygame: pygame.event.Event(
                pygame.MOUSEBUTTONUP, button=1, touch=True,
            ),
            True,
            (False, True, 8, True, False, None),
        ),
        (
            lambda pygame: pygame.event.Event(pygame.WINDOWFOCUSLOST),
            True,
            (False, False, 0, False, False, None),
        ),
    ],
    ids=(
        "physical-mouseup", "physical-focus-loss",
        "touch-origin-mouseup", "touch-origin-focus-loss",
    ),
)
def test_run_cancels_held_push_before_the_same_pump_s_play_tick(
    data_dir, profile, monkeypatch, event_factory, touch, expected_input,
):
    import PyAitD.app.shell as main
    from PyAitD.engine.script.interaction import apply_click_intent

    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    apply_click_intent(game, 100, 200, hero.room, 4, requires_hold=True)
    input_buffer = InputBuffer(
        pointer_held=True,
        pointer_touch=touch,
        pointer_pos=(100, 200),
        action_held=True,
        held_joyd=8,
    )
    seen = []
    event_batches = iter([
        [event_factory(main.pygame)],
        [SimpleNamespace(type=main.pygame.QUIT)],
    ])
    times = iter([0, 20, 20])
    monkeypatch.setattr(main, "Renderer", lambda *_a, **_k: SimpleNamespace(
        fallback_notice=None,
        present=lambda image: None, close=lambda: None,
    ))
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (frame, []))
    monkeypatch.setattr(
        main, "play_tick",
        lambda game, _floor, state: seen.append((
            game.nav_intent, state.pointer_held, state.action_held,
            state.held_joyd, state.focused, state.pointer_touch, state.pointer_pos,
        )),
    )
    monkeypatch.setattr(main, "render_active_mode", lambda *_args: painter_from_frame(frame))
    monkeypatch.setattr(main, "render_play_hud", lambda image, **_kwargs: image)
    monkeypatch.setattr(main, "render_settings_notice", lambda image, *_args: image)
    # run() renders the cursor through _render_play_cursor -> _play_cursor_state;
    # patching _play_cursor_kind here would be inert (nothing in run() calls it)
    monkeypatch.setattr(main, "_play_cursor_state", lambda *_args: ("blocked", None))
    monkeypatch.setattr(main, "InputBuffer", lambda: input_buffer)
    monkeypatch.setattr(main, "configure_session_input", lambda *_args: None)
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda _value: None)
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(times))
    monkeypatch.setattr(
        main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *_args: None),
    )

    assert main.run(game) == 0
    assert seen == [(None, *expected_input)]


@pytest.mark.parametrize("engaged", (False, True), ids=("approach", "engaged"))
def test_held_push_inventory_modal_takeover_is_clean_before_play_resumes(
        data_dir, profile, monkeypatch, engaged,
):
    import PyAitD.app.shell as main
    from PyAitD.engine.script.interaction import apply_click_intent

    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    game = init_game(data_dir, profile)
    game.num_camera = game.new_num_camera
    _finish_take(game, 38)
    hero = game.actors[game.current_camera_target_actor]
    apply_click_intent(
        game, 100, 200, hero.room, 4, requires_hold=True,
    )
    game.nav_intent.engaged = engaged
    game.local_joyd, game.local_click, game.action = (8, 1, 0x2000)
    input_buffer = InputBuffer(
        pointer_held=True, pointer_pos=(150, 100), action_held=True, held_joyd=8,
    )
    session = ModalSession()
    event_batches = iter([
        [main.pygame.event.Event(
            main.pygame.MOUSEBUTTONDOWN,
            button=1,
            pos=PlayLayout.INVENTORY.center,
        )],
        [main.pygame.event.Event(
            main.pygame.KEYDOWN, key=main.pygame.K_ESCAPE,
        )],
        [main.pygame.event.Event(main.pygame.QUIT)],
    ])
    times = iter([0, 0, 20, 20])
    observed_ticks = []

    def assert_modal_tick_is_clean(current_game, _floor, buffer):
        assert current_game.nav_intent is None
        assert (
            current_game.local_joyd, current_game.local_click, current_game.action,
        ) == (0, 0, 0)
        assert not buffer.pointer_held
        observed_ticks.append(1)

    monkeypatch.setattr(main, "Renderer", lambda *_a, **_k: SimpleNamespace(
        fallback_notice=None,
        window_to_logical=lambda pos: pos,
        present=lambda _image: None,
        close=lambda: None,
    ))
    monkeypatch.setattr(main, "_scene_frame", lambda *_args: (frame, []))
    monkeypatch.setattr(main, "play_tick", assert_modal_tick_is_clean)
    monkeypatch.setattr(main, "render_active_mode", lambda *_args: painter_from_frame(frame))
    monkeypatch.setattr(main, "render_play_hud", lambda image, **_kwargs: image)
    monkeypatch.setattr(main, "render_settings_notice", lambda image, *_args: image)
    monkeypatch.setattr(main, "render_cursor", lambda image, *_args, **_kwargs: image)
    monkeypatch.setattr(main, "InputBuffer", lambda: input_buffer)
    monkeypatch.setattr(main, "configure_session_input", lambda *_args: None)
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda _value: None)
    monkeypatch.setattr(main.pygame.display, "set_caption", lambda *_args: None)
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(times))
    monkeypatch.setattr(
        main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *_args: None),
    )

    assert main.run(game, session=session) == 0
    assert observed_ticks == [1]


@pytest.mark.parametrize("touch", (False, True), ids=("physical", "touch-origin"))
def test_run_routes_physical_and_touch_down_through_the_same_held_push_path(
        data_dir, profile, monkeypatch, touch,
):
    import PyAitD.app.shell as main
    from PyAitD.engine.script.interaction import is_hold_action_target

    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    game = init_game(data_dir, profile)
    wardrobe_idx = game.world_objects[4].obj_index
    replacement_idx = game.world_objects[6].obj_index
    assert is_hold_action_target(game, replacement_idx) is True
    draw_list = [
        (wardrobe_idx, (100, 60, 200, 160)),
        (replacement_idx, (220, 60, 280, 160)),
    ]
    event_batches = iter([
        [
            main.pygame.event.Event(
                main.pygame.MOUSEBUTTONDOWN, button=1, pos=(150, 100), touch=touch,
            ),
            main.pygame.event.Event(
                main.pygame.MOUSEBUTTONDOWN, button=1, pos=(250, 100), touch=touch,
            ),
        ],
        [main.pygame.event.Event(main.pygame.QUIT)],
    ])
    times = iter([0, 20, 20])
    seen = []
    monkeypatch.setattr(main, "Renderer", lambda *_a, **_k: SimpleNamespace(
        fallback_notice=None,
        window_to_logical=lambda pos: pos,
        present=lambda _image: None,
        close=lambda: None,
    ))
    monkeypatch.setattr(main, "_scene_frame", lambda *_args: (frame, draw_list))
    monkeypatch.setattr(
        main, "play_tick",
        lambda current_game, _floor, state: seen.append((
            current_game.nav_intent.target_object_idx, state.pointer_held,
            state.pointer_touch, state.pointer_pos,
        )),
    )
    monkeypatch.setattr(main, "render_active_mode", lambda *_args: painter_from_frame(frame))
    monkeypatch.setattr(main, "render_play_hud", lambda image, **_kwargs: image)
    monkeypatch.setattr(main, "render_settings_notice", lambda image, *_args: image)
    monkeypatch.setattr(main, "render_cursor", lambda image, *_args, **_kwargs: image)
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda _value: None)
    monkeypatch.setattr(main.pygame.display, "set_caption", lambda *_args: None)
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(times))
    monkeypatch.setattr(
        main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *_args: None),
    )

    assert main.run(game) == 0
    assert seen == [(4, True, touch, (250, 100))]


@pytest.mark.parametrize("touch", (False, True), ids=("physical", "touch-origin"))
def test_run_routes_physical_and_touch_down_to_the_same_inventory_modal(
        data_dir, profile, monkeypatch, touch,
):
    import PyAitD.app.shell as main

    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    game = init_game(data_dir, profile)
    game.num_camera = game.new_num_camera
    _finish_take(game, 38)
    input_buffer = InputBuffer()
    event_batches = iter([
        [main.pygame.event.Event(
            main.pygame.MOUSEBUTTONDOWN,
            button=1,
            pos=PlayLayout.INVENTORY.center,
            touch=touch,
        )],
        [main.pygame.event.Event(
            main.pygame.MOUSEBUTTONUP,
            button=1,
            touch=touch,
        )],
        [SimpleNamespace(type=main.pygame.QUIT)],
    ])
    times = iter([0, 0, 0, 0])
    monkeypatch.setattr(main, "Renderer", lambda *_a, **_k: SimpleNamespace(
        fallback_notice=None,
        window_to_logical=lambda pos: pos,
        present=lambda _image: None,
        close=lambda: None,
    ))
    monkeypatch.setattr(main, "_scene_frame", lambda *_args: (frame, []))
    monkeypatch.setattr(main, "render_active_mode", lambda *_args: painter_from_frame(frame))
    monkeypatch.setattr(main, "render_play_hud", lambda image, **_kwargs: image)
    monkeypatch.setattr(main, "render_settings_notice", lambda image, *_args: image)
    monkeypatch.setattr(main, "InputBuffer", lambda: input_buffer)
    monkeypatch.setattr(main, "configure_session_input", lambda *_args: None)
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda _value: None)
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(times))
    monkeypatch.setattr(
        main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *_args: None),
    )

    assert main.run(game) == 0
    assert game.mode is GameMode.INVENTORY
    assert game.nav_intent is None
    assert (input_buffer.pointer_held, input_buffer.pointer_touch, input_buffer.pointer_pos) == (
        False, False, None,
    )


def _screen_draw_list(game, floor):
    """Every actor of the hero's room as _scene_frame would hand it over."""
    hero = game.actors[game.current_camera_target_actor]
    entries = []
    for idx, actor in enumerate(game.actors):
        if actor.index_in_world < 0 or actor.room != hero.room:
            continue
        if not 0 <= actor.body_num < game.assets.num_bodies:
            continue   # nothing skinned, so nothing in the draw list
        entry = _real_draw_list_entry(game, floor, idx)
        if entry[1] is not None:
            entries.append(entry)
    return entries


def test_no_pixel_of_the_opening_room_refuses_a_click(data_dir, profile):
    """THE gate on "walking is always possible".

    Swept against the real draw list, so actor bounding boxes are in play --
    they are what put the red X back over ordinary floor after steering
    landed: an inert body and one piece of scenery refused 86 of the 4000
    pixels sampled here, the floor around them included.

    Scoped to the opening room, which has no enemy in it. A combat actor
    still refuses an empty hand or a hero mid-swing, and that refusal is
    deliberate -- there the click was aimed at the enemy, not past it.
    """
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    hero = game.actors[game.current_camera_target_actor]
    refused = []
    for slot in range(len(floor.rooms[hero.room].camera_indices)):
        game.num_camera = slot
        draw_list = _screen_draw_list(game, floor)
        for x in range(0, 320, 8):
            for y in range(0, 200, 8):
                kind, _payload = resolve_play_click(game, floor, (x, y), draw_list)
                if kind == "blocked":
                    refused.append((slot, x, y))
    assert refused == [], (
        f"{len(refused)} pixel(s) of the opening room do nothing at all, "
        f"first few: {refused[:8]}"
    )


def test_an_inert_actor_does_not_intercept_the_floor_behind_it(data_dir, profile):
    """An actor with nothing to offer must not swallow the click.

    It used to: an inert body, a piece of scenery with no found_life and no
    push, returned `blocked` before the floor was ever consulted. A draw-list
    entry is a *rectangle* around the skinned model, so that refusal covered
    the floor around the object as well as the object -- 86 of 4000 pixels
    sampled at the opening camera, all of them from two such actors, and none
    of them able to walk anywhere. The pixel now resolves against the floor,
    as though the actor were not there.
    """
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    actor_idx = game.world_objects[8].obj_index
    bare = resolve_play_click(game, floor, (150, 100), [])

    over_body = resolve_play_click(
        game, floor, (150, 100), [(actor_idx, (100, 60, 200, 160))],
    )

    assert over_body == bare, "the inert body changed what the pixel means"
    assert over_body[0] in ("walk", "steer")


def test_a_click_on_nothing_steers_rather_than_doing_nothing(data_dir, profile):
    # It used to leave the intent alone: a pixel with no floor under it was a
    # red X and a hero who stayed put. Walking is always possible now, so the
    # click means the direction it points in.
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    route_play_click(game, ModalSession(), floor, (2, 2), [])
    assert game.nav_intent is not None and game.nav_intent.steering is True


def _real_draw_list_entry(game, floor, actor_idx):
    """The (actor, screen bbox) pair _scene_frame would produce, without a
    Renderer: the same skin() call, the same picking.actor_bbox."""
    from PyAitD.engine.nav.picking import actor_bbox
    from PyAitD.engine.actor.skel import skin
    from PyAitD.engine.space.world import CameraState
    room = floor.rooms[game.current_room]
    camera = floor.cameras[room.camera_indices[game.num_camera]]
    state = CameraState.from_camera(
        camera, room.world_x, room.world_y, room.world_z,
    ).angles()
    actor = game.actors[actor_idx]
    body = game.assets.body(actor.body_num)
    result = skin(
        body, [(0, (0, 0, 0))] * len(body.groups),
        (actor.world_x, actor.world_y, actor.world_z), state,
        actor_angles=(actor.alpha, actor.beta, actor.gamma),
    )
    return (actor_idx, actor_bbox(result))


def test_clicking_floor_zero_s_interactable_walks_there_and_dispatches(data_dir, profile):
    # End to end on the only bootable content: floor 0 has exactly one clickable
    # interactable (actor 10 / world object 13, found_life 9), and its own cell
    # is not walkable — the hard col standing for it plus the 266-unit agent
    # inflation cover it. Aiming at the object's centre makes find_path fail
    # every tick, and the hero grinds into the wall forever (measured: still
    # 875 units short after 6000 ticks). The click must snap to a standing spot
    # instead, so the walk actually finishes and the arrival dispatches.
    from PyAitD.engine.script.effects import GameMode
    from PyAitD.engine.script.playworld import play_tick
    from PyAitD.app.ui import InputBuffer

    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    # the draw list is what a click can hit: only actors with a body are in it
    # (actors.sort_actor_indices skips body_num == -1)
    target_idx = next(
        i for i, a in enumerate(game.actors)
        if a.index_in_world >= 0 and a.body_num != -1
        and i != game.current_camera_target_actor and _is_interactable(game, i)
    )
    entry = _real_draw_list_entry(game, floor, target_idx)
    box = entry[1]
    assert box is not None, "the interactable must be on screen to be clickable"
    click = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)

    route_play_click(game, ModalSession(), floor, click, [entry])
    intent = game.nav_intent
    assert intent is not None and intent.target_object_idx == game.actors[target_idx].index_in_world
    target = game.actors[target_idx]
    assert (intent.dest_x, intent.dest_z) != (target.room_x, target.room_z), (
        "the destination must be a standing spot beside the object, not its own "
        "cell, which is never walkable"
    )
    mesh = game.nav_meshes.mesh_for(floor, target.room, agent_extent(game.actors[
        game.current_camera_target_actor]))
    assert mesh.is_walkable(intent.dest_x, intent.dest_z)

    buf = held_pointer()
    dispatched = False
    for _tick in range(2000):
        play_tick(game, floor, buf)
        if game.mode is not GameMode.PLAY:
            dispatched = True   # a foundable target would open its prompt
            break
        if game.action == 0x2000:
            dispatched = True   # a non-foundable target gets the action bit
            break
        if game.nav_intent is None:
            break
    assert dispatched, "the click never reached a dispatch — the hero is grinding"


def _floor_screen_point(game, floor, dx, dz):
    hero = game.actors[game.current_camera_target_actor]
    return project_floor_point(
        _state_for(floor, hero.room, game.num_camera),
        hero.room_x + dx, hero.world_y, hero.room_z + dz,
    )


def test_a_walk_press_records_the_follow_latch(data_dir, profile):
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    screen = _floor_screen_point(game, floor, 1500, 0)
    buf = InputBuffer(pointer_held=True)
    route_play_click(
        game, ModalSession(), floor, (int(screen[0]), int(screen[1])), [], buf,
    )
    intent = game.nav_intent
    assert intent is not None and intent.target_object_idx == -1
    assert buf.follow_last == (intent.dest_x, intent.dest_z, intent.room, -1)


def test_a_push_press_leaves_no_follow_latch(data_dir, profile):
    # a push is latched and never re-resolved, so a stale latch from an
    # earlier walk must not survive into the hold
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    actor_idx = game.world_objects[4].obj_index
    buf = InputBuffer(pointer_held=True, follow_last=(1, 2, 0, -1))
    route_play_click(
        game, ModalSession(), floor, (150, 100),
        [(actor_idx, (100, 60, 200, 160))], buf,
    )
    assert game.nav_intent.requires_hold is True
    assert buf.follow_last is None


def test_pointer_invalidation_cancels_a_plain_walk_intent(data_dir, profile):
    # today only a hold-required push is cancelled on release; every intent
    # is hold-bound now
    import PyAitD.app.shell as main
    from PyAitD.engine.script.interaction import apply_click_intent

    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    for event in (
        main.pygame.event.Event(main.pygame.MOUSEBUTTONUP, button=1),
        main.pygame.event.Event(main.pygame.WINDOWFOCUSLOST),
    ):
        buf = InputBuffer(pointer_held=True, follow_last=(100, 200, hero.room, -1))
        apply_click_intent(game, 100, 200, hero.room)
        assert main._cancel_pointer_invalidation(game, event, buf) is True
        assert game.nav_intent is None
        assert buf.follow_last is None
    up = main.pygame.event.Event(main.pygame.MOUSEBUTTONUP, button=1)
    assert main._cancel_pointer_invalidation(game, up, InputBuffer()) is False
    assert main._cancel_pointer_invalidation(game, up, buf) is False, (
        "a second release on an already-cleared buffer is a no-op"
    )


def test_a_play_click_is_ignored_in_keyboard_mode(data_dir, profile):
    # Tab hands control back to the tank keys; a click that silently does
    # nothing is worse than no click, so the cursor is hidden in that mode too
    # (run() only renders it in mouse mode) and the resolver refuses outright.
    from PyAitD.engine.script.effects import InputMode
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    screen = _floor_screen_point(game, floor, 1500, 0)
    click = (int(screen[0]), int(screen[1]))
    assert resolve_play_click(game, floor, click, [])[0] != "blocked", "fixture"

    game.input_mode = InputMode.KEYBOARD
    assert resolve_play_click(game, floor, click, [])[0] == "blocked"
    route_play_click(game, ModalSession(), floor, click, [])
    assert game.nav_intent is None


def test_the_cursor_and_the_click_come_from_one_resolution(data_dir, profile):
    # The hover cursor used to resolve the floor with pick_floor (the hero's
    # room only) while the click used pick_floor_any_room, so a neighbouring
    # room's floor drew the red "blocked" X and then walked there anyway. Both
    # now go through resolve_play_click, and this pins the agreement: whatever
    # the cursor shows is exactly what clicking does.
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    points = [(x, y) for x in range(10, 320, 23) for y in range(20, 200, 17)]
    seen = set()
    session = ModalSession()
    for point in points:
        kind, args = resolve_play_click(game, floor, point, [])
        seen.add(kind)
        game.nav_intent = None
        route_play_click(game, session, floor, point, [])
        if kind == "blocked":
            assert game.nav_intent is None, f"{point}: cursor said blocked, click walked"
        else:
            assert game.nav_intent is not None, f"{point}: cursor said {kind}, click did nothing"
            assert (game.nav_intent.dest_x, game.nav_intent.dest_z) == args[:2]
    assert {"walk", "steer"} <= seen, (
        "the sweep must cover both a destination and a bearing"
    )


def test_a_walk_click_always_lands_on_a_walkable_cell(data_dir, profile):
    # the cursor promises "walk", so the destination must really be on the mesh
    from PyAitD.engine.nav.navmesh import agent_extent
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    hero = game.actors[game.current_camera_target_actor]
    mesh = game.nav_meshes.mesh_for(floor, hero.room, agent_extent(hero))
    walks = 0
    for x in range(10, 320, 17):
        for y in range(20, 200, 13):
            kind, args = resolve_play_click(game, floor, (x, y), [])
            if kind != "walk":
                continue
            walks += 1
            assert mesh.is_walkable(args[0], args[1]), f"click at {(x, y)} is not walkable"
    assert walks > 20, "the sweep must actually produce walk clicks"


def _cross_room_target_setup(data_dir, profile):
    """Hero in floor 1 room 0, an interactable actor in room 7 (a 12000-unit
    origin delta), plus a draw list that makes the actor the click target."""
    from PyAitD.engine.script.game import AF_FOUNDABLE
    game = init_game(data_dir, profile)
    game.current_floor = 1
    floor = Floor(data_dir, 1, profile)
    game.num_camera = 0
    hero_idx = game.current_camera_target_actor
    hero = game.actors[hero_idx]
    hero.room, hero.room_x, hero.room_z = 0, 400, -200
    target_idx = next(
        i for i, a in enumerate(game.actors)
        if a.index_in_world >= 0 and i != hero_idx
    )
    target = game.actors[target_idx]
    target.room, target.room_x, target.room_z = 7, 300, 500
    target.object_type |= AF_FOUNDABLE
    return game, floor, hero, target, [(target_idx, (100, 60, 200, 160))]


def test_the_approach_bias_is_converted_into_the_target_room_s_frame(data_dir, profile):
    # approach_cell rings outward from the object and picks the ring cell
    # closest to where the hero is coming from -- but the mesh belongs to the
    # TARGET's room, so a hero standing in another room must be expressed in
    # that room's coordinate frame first. Floor 1 room 0 -> room 7 is a
    # 12000-unit delta on x, 120 grid cells, so an unconverted bias picks the
    # approach side essentially at random.
    import PyAitD.app.shell as main
    from PyAitD.app.shell import resolve_play_click
    from PyAitD.engine.space.world import room_delta

    game, floor, hero, target, draw_list = _cross_room_target_setup(data_dir, profile)

    seen = {}
    original = main.approach_cell

    def spy(mesh, x, z, from_x, from_z, **kwargs):
        seen["from"] = (from_x, from_z)
        return original(mesh, x, z, from_x, from_z, **kwargs)

    main.approach_cell = spy
    try:
        kind, _args = resolve_play_click(game, floor, (150, 100), draw_list)
    finally:
        main.approach_cell = original

    assert kind == "target"
    assert "from" in seen, "approach_cell was never reached"

    # Expectation derived from the ENGINE's own conversion, not from the code
    # under test: gere_dec re-frames a moving actor with room_delta and FITD's
    # asymmetric signs (x minus, z plus).
    dx, _dy, dz = room_delta(game, hero.room, target.room)
    assert seen["from"] == (hero.room_x - dx, hero.room_z + dz)
    assert seen["from"] != (hero.room_x, hero.room_z), (
        "fixture is not exercising a cross-room conversion"
    )


def test_a_same_room_target_passes_the_hero_position_unchanged(data_dir, profile):
    # control: the conversion must be a no-op within one room, or every
    # single-room click would be biased by a spurious offset.
    import PyAitD.app.shell as main
    from PyAitD.app.shell import resolve_play_click

    game, floor, hero, target, draw_list = _cross_room_target_setup(data_dir, profile)
    target.room = hero.room  # same room now
    target.room_x, target.room_z = hero.room_x + 900, hero.room_z + 900

    seen = {}
    original = main.approach_cell

    def spy(mesh, x, z, from_x, from_z, **kwargs):
        seen["from"] = (from_x, from_z)
        return original(mesh, x, z, from_x, from_z, **kwargs)

    main.approach_cell = spy
    try:
        resolve_play_click(game, floor, (150, 100), draw_list)
    finally:
        main.approach_cell = original

    assert seen.get("from") == (hero.room_x, hero.room_z)


def test_inventory_hud_wins_before_world_resolution(data_dir, profile, monkeypatch):
    import PyAitD.app.shell as main

    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    _finish_take(game, 38)
    monkeypatch.setattr(
        main,
        "pick_floor_any_room",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("HUD leaked to world picking")),
    )
    assert resolve_play_click(
        game, floor, PlayLayout.INVENTORY.center, [],
    ) == ("inventory", None)


def test_inventory_hud_effective_padding_has_priority_and_exclusive_far_edges(
    data_dir, profile, monkeypatch,
):
    import PyAitD.app.shell as main

    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    _finish_take(game, 38)
    calls = []
    monkeypatch.setattr(
        main, "pick_floor_any_room",
        lambda *args, **kwargs: calls.append(args) or None,
    )
    padded_points = (
        (PlayLayout.INVENTORY.right, PlayLayout.INVENTORY.centery),
        (PlayLayout.INVENTORY.centerx, PlayLayout.INVENTORY.bottom),
    )
    for point in padded_points:
        assert resolve_play_click(game, floor, point, []) == ("inventory", None)
    assert calls == []

    hit = PlayLayout.INVENTORY_HIT
    exclusive_far_edges = (
        (hit.right, hit.centery),
        (hit.centerx, hit.bottom),
    )
    for point in exclusive_far_edges:
        # outside the hit box, so the world answers -- a steer here, since the
        # HUD corner has no floor under it
        assert resolve_play_click(game, floor, point, [])[0] != "inventory"
    assert len(calls) == 2


def test_combat_actor_resolves_attack_or_blocked_not_walk(data_dir, profile):
    game = init_game(data_dir, profile)
    enter_combat_venue(game)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    enemy_idx = game.world_objects[222].obj_index
    draw_list = [(enemy_idx, (100, 60, 200, 160))]
    point = (150, 100)

    assert resolve_play_click(game, floor, point, draw_list) == ("blocked", None)
    _finish_take(game, 38)
    game.in_hand_table[game.current_inventory] = 38
    assert resolve_play_click(game, floor, point, draw_list) == ("attack", enemy_idx)


def test_a_weapon_equipped_through_the_inventory_can_attack(data_dir, profile):
    # Equipping leaves the *wielded* variant in hand, not the inventory entry:
    # choosing Fight on the attic lamp (13) leaves object 2, whose own
    # inventory flags carry no Fight at all. Gating the click on the held
    # object's Fight action therefore refused every weapon a player actually
    # equipped -- the cursor stayed blocked -- while holding action swung it
    # perfectly well. Equipped here through the real inventory path, never by
    # assigning in_hand_table, which is what hid this from every other test.
    from PyAitD.engine.script.interaction import choose_inventory_action, combat_action_for

    game = init_game(data_dir, profile)
    enter_combat_venue(game)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    enemy_idx = game.world_objects[222].obj_index
    draw_list = [(enemy_idx, (100, 60, 200, 160))]
    hero = game.actors[game.current_camera_target_actor]

    _finish_take(game, 13)
    choose_inventory_action(game, 13, 32)   # 32 == Fight

    held = game.in_hand_table[game.current_inventory]
    assert held not in (-1, 13), "the lamp's LIFE swaps in its wielded variant"
    assert combat_action_for(game, held) is None, (
        "and that variant offers no Fight action of its own -- the premise "
        "this regression exists for"
    )
    hero.anim_action_type = 0   # the equip's own swing has finished
    assert resolve_play_click(game, floor, (150, 100), draw_list) == (
        "attack", enemy_idx,
    )


def _expanded_target_candidates(game):
    hero_idx = game.current_camera_target_actor
    return [
        i for i, actor in enumerate(game.actors)
        if actor.index_in_world >= 0 and actor.body_num != -1 and i != hero_idx
    ][:2]


def test_expansion_only_overlap_keeps_the_frontmost_actor(data_dir, profile):
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    candidates = _expanded_target_candidates(game)
    for actor_idx in candidates:
        game.actors[actor_idx].object_type |= AF_FOUNDABLE

    # Neither original contains (105, 101), but both expanded targets do.
    # Painter order is farthest first, so the later candidate is frontmost.
    kind, payload = resolve_play_click(
        game, floor, (105, 101),
        [(candidates[0], (100, 100, 103, 103)),
         (candidates[1], (107, 100, 110, 103))],
    )
    assert kind == "target"
    assert payload[-1] == game.actors[candidates[1]].index_in_world


def test_original_actor_hit_wins_over_a_frontmost_expanded_actor(data_dir, profile):
    from PyAitD.app.shell import expand_actor_targets
    from PyAitD.engine.nav.picking import pick_actor

    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    candidates = _expanded_target_candidates(game)
    for actor_idx in candidates:
        game.actors[actor_idx].object_type |= AF_FOUNDABLE

    # (105, 101) is inside candidate 0's visible box and only candidate 1's
    # expanded box. Expansion must never steal an original-bound hit.
    targets = [(candidates[0], (100, 100, 105, 105)),
               (candidates[1], (108, 100, 111, 103))]
    assert pick_actor((105, 101), expand_actor_targets(targets)) == candidates[1]
    kind, payload = resolve_play_click(
        game, floor, (105, 101), targets,
    )
    assert kind == "target"
    assert payload[-1] == game.actors[candidates[0]].index_in_world


def test_expanded_actor_target_wins_before_floor_walking(data_dir, profile, monkeypatch):
    import PyAitD.app.shell as main

    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    actor_idx = _expanded_target_candidates(game)[0]
    game.actors[actor_idx].object_type |= AF_FOUNDABLE
    hero = game.actors[game.current_camera_target_actor]
    # the shell imported pick_floor_any_room by name, so it reads its OWN
    # module global; patching engine.nav.picking here would be inert. The
    # stand-in takes **kwargs because the shell passes agent=.
    monkeypatch.setattr(
        main, "pick_floor_any_room",
        lambda *_args, **_kwargs: (0, 0, hero.room),
    )

    kind, payload = resolve_play_click(
        game, floor, (96, 101), [(actor_idx, (100, 100, 103, 103))],
    )

    assert kind == "target"
    assert payload[-1] == game.actors[actor_idx].index_in_world


def test_hud_click_opens_inventory_without_navigation(data_dir, profile):
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    _finish_take(game, 38)
    session = ModalSession()
    route_play_click(game, session, floor, PlayLayout.INVENTORY.center, [])
    assert game.mode is GameMode.INVENTORY
    assert game.nav_intent is None


def test_inventory_click_keeps_priority_over_an_active_held_push(data_dir, profile):
    from PyAitD.engine.script.interaction import apply_click_intent

    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    _finish_take(game, 38)
    apply_click_intent(game, 100, 200, 0, 4, requires_hold=True)

    route_play_click(
        game, ModalSession(), floor, PlayLayout.INVENTORY.center, [],
    )

    assert game.mode is GameMode.INVENTORY


def test_attack_click_delegates_actor_index(data_dir, profile, monkeypatch):
    game = init_game(data_dir, profile)
    enter_combat_venue(game)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    _finish_take(game, 38)
    game.in_hand_table[game.current_inventory] = 38
    enemy_idx = game.world_objects[222].obj_index
    calls = []
    monkeypatch.setattr(
        "PyAitD.engine.script.interaction.attack_in_hand",
        lambda g, idx: calls.append((g, idx)) or True,
    )
    route_play_click(
        game, ModalSession(), floor, (150, 100),
        [(enemy_idx, (100, 60, 200, 160))],
    )
    assert calls == [(game, enemy_idx)]
    assert game.nav_intent is None


def test_attack_click_latches_native_mouse_combat(data_dir, profile):
    # A validated target click arms FITD's own action input for the following
    # fixed ticks; it never picks the inventory "Throw" row on the player's
    # behalf. The latch lives in the application-owned InputBuffer so every
    # existing focus/modal/input-mode reset already clears it.
    from PyAitD.engine.script.interaction import choose_inventory_action

    game = init_game(data_dir, profile)
    enter_combat_venue(game)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    _finish_take(game, 38)
    game.in_hand_table[game.current_inventory] = 38
    enemy_idx = game.world_objects[222].obj_index
    state = InputBuffer()

    route_play_click(
        game, ModalSession(), floor, (150, 100),
        [(enemy_idx, (100, 60, 200, 160))], state,
    )

    assert state.mouse_attack_target == enemy_idx
    assert state.mouse_attack_ticks == 0
    assert game.nav_intent is None
    assert game.world_objects[38].obj_index == -1, "the saber must stay in hand"
    assert 38 in inventory_items(game)


def test_a_refused_attack_click_leaves_no_latch(data_dir, profile):
    game = init_game(data_dir, profile)
    enter_combat_venue(game)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    _finish_take(game, 38)
    game.in_hand_table[game.current_inventory] = -1  # empty hand: nothing to swing
    enemy_idx = game.world_objects[222].obj_index
    state = InputBuffer()

    route_play_click(
        game, ModalSession(), floor, (150, 100),
        [(enemy_idx, (100, 60, 200, 160))], state,
    )

    assert (state.mouse_attack_target, state.mouse_attack_ticks) == (None, 0)


def _click_to_attack(data_dir, profile):
    """Drive one accepted target click and hand back its latched buffer."""
    game = init_game(data_dir, profile)
    enter_combat_venue(game)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    _finish_take(game, 38)
    game.in_hand_table[game.current_inventory] = 38
    enemy_idx = game.world_objects[222].obj_index
    session = ModalSession()
    state = InputBuffer()
    route_play_click(
        game, session, floor, (150, 100),
        [(enemy_idx, (100, 60, 200, 160))], state,
    )
    assert state.mouse_attack_target == enemy_idx
    return game, session, state


def test_releasing_the_button_does_not_cancel_an_accepted_attack(data_dir, profile):
    # The accessibility contract is one click, not a hold: the swing must
    # outlive the release that always follows the press a moment later.
    import PyAitD.app.shell as main
    from PyAitD.app.shell import pygame
    from PyAitD.app.ui import event_to_input

    game, _session, state = _click_to_attack(data_dir, profile)
    release = pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(150, 100))

    assert main._cancel_pointer_invalidation(game, release, state) is False
    event_to_input(release, state, (150, 100))

    assert state.mouse_attack_target is not None
    assert state.pointer_held is False


def test_modal_takeover_cannot_leave_an_attack_to_resume_later(data_dir, profile):
    # Opening the inventory mid-swing must not park the latch and re-publish
    # action input when PLAY returns.
    import PyAitD.app.shell as main

    game, session, state = _click_to_attack(data_dir, profile)

    main._take_over_play_input(game, session, state)

    assert (state.mouse_attack_target, state.mouse_attack_ticks) == (None, 0)


def test_focus_loss_cannot_leave_an_attack_to_resume_later(data_dir, profile):
    from PyAitD.app.shell import pygame
    from PyAitD.app.ui import event_to_input

    _game, _session, state = _click_to_attack(data_dir, profile)

    event_to_input(pygame.event.Event(pygame.WINDOWFOCUSLOST), state)

    assert (state.mouse_attack_target, state.mouse_attack_ticks) == (None, 0)


def test_attack_click_keeps_priority_over_an_active_held_push(data_dir, profile, monkeypatch):
    from PyAitD.engine.script.interaction import apply_click_intent

    game = init_game(data_dir, profile)
    enter_combat_venue(game)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    _finish_take(game, 38)
    game.in_hand_table[game.current_inventory] = 38
    enemy_idx = game.world_objects[222].obj_index
    apply_click_intent(game, 100, 200, 0, 4, requires_hold=True)
    calls = []
    monkeypatch.setattr(
        "PyAitD.engine.script.interaction.attack_in_hand",
        lambda g, idx: calls.append((g, idx)) or True,
    )

    route_play_click(
        game, ModalSession(), floor, (150, 100),
        [(enemy_idx, (100, 60, 200, 160))],
    )

    assert calls == [(game, enemy_idx)]


def test_world_down_routes_normally_after_a_held_push_is_cancelled(data_dir, profile):
    from PyAitD.engine.script.interaction import apply_click_intent, cancel_held_nav_intent

    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    replacement_idx = game.world_objects[6].obj_index
    apply_click_intent(game, 100, 200, 0, 4, requires_hold=True)
    assert cancel_held_nav_intent(game) is True

    route_play_click(
        game, ModalSession(), floor, (250, 100),
        [(replacement_idx, (220, 60, 280, 160))],
    )

    assert game.nav_intent is not None
    assert game.nav_intent.target_object_idx == 6


def test_run_draws_hud_before_cursor_and_owns_the_system_pointer(
    data_dir, profile, monkeypatch,
):
    import PyAitD.app.shell as main
    from PyAitD.engine.script.game import Game

    calls = []
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    draw_list = []
    event_batches = iter([[], [SimpleNamespace(type=main.pygame.QUIT)]])
    times = iter([0, 0, 0])
    monkeypatch.setattr(
        Game, "load_floor",
        lambda self, number: SimpleNamespace(number=0, rooms=[SimpleNamespace(camera_indices=[0])]),
    )
    monkeypatch.setattr(main, "Renderer", lambda *_a, **_k: SimpleNamespace(
        fallback_notice=None,
        present=lambda image: calls.append("present"), close=lambda: calls.append("close"),
    ))
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (frame, draw_list))
    monkeypatch.setattr(main, "render_active_mode", lambda *args: painter_from_frame(frame))
    monkeypatch.setattr(
        main, "render_hit_feedback",
        lambda image, rects: calls.append(("hit", tuple(rects))) or image,
        raising=False,
    )
    monkeypatch.setattr(
        main, "render_play_hud",
        lambda image, **kwargs: calls.append("hud") or image,
    )
    monkeypatch.setattr(
        main, "render_cursor",
        lambda image, *args, **kwargs: calls.append("cursor") or image,
    )
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda value: calls.append(("visible", value)))
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(times))
    monkeypatch.setattr(main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *args: None))

    game = init_game(data_dir, profile)
    hit_actor_idx = game.current_camera_target_actor
    game.actors[hit_actor_idx].hit_by = 17
    draw_list.append((hit_actor_idx, (100, 60, 200, 160)))
    game.inventory_table[0][0] = 38
    game.inventory_count[0] = 1
    assert main.run(game) == 0
    hit_call = ("hit", (main.pygame.Rect(100, 60, 101, 101),))
    assert calls.index(hit_call) < calls.index("hud") < calls.index("cursor") < calls.index("present")
    # PLAY + mouse + no modal: the OS pointer is hidden once per frame, not
    # once at renderer creation — modals must get it back the frame they open.
    assert calls.count(("visible", False)) == 2
    assert calls[-2:] == [("visible", True), "close"]


def test_run_presents_only_the_selector_until_a_hero_is_chosen(data_dir, profile, monkeypatch):
    # Staging-game rule: a normal boot loads floor zero but must never tick or
    # present PLAY before character confirmation -- every presented frame
    # comes from render_character_select, never from the staged scene array.
    import PyAitD.app.shell as main
    from PyAitD.engine.script.effects import ChooseCharacter
    from PyAitD.engine.script.game import Game
    from PyAitD.app.ui import CharacterSelectPresenter, UIPainter, render_character_select

    calls = []
    presented = []
    sentinel = np.full((200, 320, 3), 255, dtype=np.uint8)
    event_batches = iter([[], [SimpleNamespace(type=main.pygame.QUIT)]])
    times = iter([0, 0, 0])

    monkeypatch.setattr(
        Game, "load_floor",
        lambda self, number: SimpleNamespace(number=0, rooms=[SimpleNamespace(camera_indices=[0])]),
    )
    monkeypatch.setattr(main, "Renderer", lambda *_a, **_k: SimpleNamespace(
        fallback_notice=None, ui_scale=lambda: 1.0,
        present=lambda ui: presented.append(ui.to_frame()), close=lambda: None,
    ))
    monkeypatch.setattr(
        main, "play_tick", lambda *args: calls.append("tick") or True,
    )
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (sentinel, []))
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda value: None)
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(times))
    monkeypatch.setattr(
        main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *args: None)
    )

    game = init_game(data_dir, profile)
    game.open_modal(ChooseCharacter())
    assert main.run(game) == 0

    assert "tick" not in calls, "the staging game must never tick PLAY"
    assert presented, "the selector must present its own frame"
    expected_painter = UIPainter()
    render_character_select(expected_painter, CharacterSelectPresenter(), game.assets)
    expected = expected_painter.to_frame()[:, :, :3]
    for frame in presented:
        # render_active_mode hands run() a painter (Task 9), and
        # painter.to_frame() always carries a fully-opaque alpha channel.
        assert frame.shape == (200, 320, 4)
        assert not np.array_equal(frame[:, :, :3], sentinel), "staged scene leaked to screen"
        assert np.array_equal(frame[:, :, :3], expected)
        assert frame[:, :, 3].min() == 255, "the selector's canvas is fully opaque"


def _resolving(monkeypatch, results):
    """Queue (kind, payload) pairs for shell.resolve_play_click; returns the
    queue so a test can assert how many resolutions were consumed."""
    import PyAitD.app.shell as main
    queue = list(results)
    monkeypatch.setattr(main, "resolve_play_click", lambda *args: queue.pop(0))
    return queue


def _follow_fixture(data_dir, profile):
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    hero = game.actors[game.current_camera_target_actor]
    near = (hero.room_x + 1000, hero.room_z, hero.room, -1)
    far = (hero.room_x + 2000, hero.room_z, hero.room, -1)
    return game, floor, InputBuffer(pointer_held=True), near, far


def _dragged(main, game, floor, buf, frames):
    """Call follow_pointer once per frame with the pointer on a fresh pixel.

    The follow only resolves a pointer that moved, so a test of what it does
    with a *resolution* has to supply motion; holding one pixel would test the
    movement gate instead. The pixels are arbitrary -- every resolver here is
    monkeypatched -- but they must differ frame to frame, as a moving hand's do.
    """
    for frame in range(frames):
        buf.pointer_pos = (10 + frame, 10)
        main.follow_pointer(game, ModalSession(), floor, buf.pointer_pos, [], buf)
        yield frame


def test_follow_reissues_only_when_the_resolution_changes(data_dir, profile, monkeypatch):
    import PyAitD.app.shell as main
    game, floor, buf, near, far = _follow_fixture(data_dir, profile)
    _resolving(monkeypatch, [("walk", near), ("walk", near), ("walk", far)])
    frames = _dragged(main, game, floor, buf, 3)

    next(frames)
    first = game.nav_intent
    assert (first.dest_x, first.dest_z, first.room) == near[:3]
    assert buf.follow_last == near
    first.waypoints = ["sentinel"]
    next(frames)
    assert game.nav_intent is first and first.waypoints == ["sentinel"], (
        "an unchanged resolution is never re-issued even when the pointer "
        "moved: re-pathing would reset the follower's stall bookkeeping and "
        "its waypoints"
    )
    next(frames)
    assert game.nav_intent is not first
    assert (game.nav_intent.dest_x, game.nav_intent.dest_z) == far[:2]
    assert buf.follow_last == far


def test_follow_blocked_stops_the_hero_and_clears_the_latch(data_dir, profile, monkeypatch):
    # Only a pointer the player moved can block: a cut that makes the held
    # pixel unpickable is never resolved at all
    # (test_a_camera_cut_that_blocks_the_pixel_does_not_stop_the_hero).
    import PyAitD.app.shell as main
    game, floor, buf, near, _far = _follow_fixture(data_dir, profile)
    _resolving(monkeypatch, [("walk", near), ("blocked", None), ("walk", near)])
    frames = _dragged(main, game, floor, buf, 3)

    next(frames)
    next(frames)
    assert game.nav_intent is None and buf.follow_last is None
    assert (game.local_joyd, game.nav_decision) == (0, None)
    # dragged back over the floor: the same point is issued again, hold live
    next(frames)
    assert game.nav_intent is not None and buf.follow_last == near


def test_follow_does_not_reissue_an_arrived_or_abandoned_destination(
        data_dir, profile, monkeypatch):
    # the engine clears the intent on arrival or give-up; without the latch
    # the shell would re-issue it every frame -- re-dispatching a used object
    # and grinding at a dead click
    import PyAitD.app.shell as main
    game, floor, buf, _near, _far = _follow_fixture(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    target = (hero.room_x + 1000, hero.room_z, hero.room, 13)
    _resolving(monkeypatch, [("target", target), ("target", target)])

    main.follow_pointer(game, ModalSession(), floor, (10, 10), [], buf)
    assert game.nav_intent.target_object_idx == 13
    game.nav_intent = None   # what playworld does when the follower arrives
    main.follow_pointer(game, ModalSession(), floor, (10, 10), [], buf)
    assert game.nav_intent is None and buf.follow_last == target


@pytest.mark.parametrize("kind", ["inventory", "attack", "push"])
def test_follow_ignores_press_only_kinds(data_dir, profile, monkeypatch, kind):
    import PyAitD.app.shell as main
    game, floor, buf, near, _far = _follow_fixture(data_dir, profile)
    _resolving(monkeypatch, [(kind, near)])
    main.follow_pointer(game, ModalSession(), floor, (10, 10), [], buf)
    assert game.nav_intent is None and buf.follow_last is None


def test_follow_is_skipped_while_a_push_or_attack_latch_lives(data_dir, profile, monkeypatch):
    import PyAitD.app.shell as main
    from PyAitD.engine.script.interaction import apply_click_intent
    game, floor, buf, near, _far = _follow_fixture(data_dir, profile)
    queue = _resolving(monkeypatch, [("walk", near)])

    apply_click_intent(game, 10, 20, 0, 4, requires_hold=True)
    main.follow_pointer(game, ModalSession(), floor, (10, 10), [], buf)
    assert game.nav_intent.requires_hold is True and len(queue) == 1

    game.nav_intent = None
    buf.mouse_attack_target = 3
    main.follow_pointer(game, ModalSession(), floor, (10, 10), [], buf)
    assert game.nav_intent is None and len(queue) == 1


@pytest.mark.parametrize(
    "why", ["released", "unfocused", "modal", "keyboard", "cutscene", "transition"],
)
def test_follow_requires_a_held_pointer_in_live_play(data_dir, profile, monkeypatch, why):
    import PyAitD.app.shell as main
    from PyAitD.engine.script.effects import InputMode
    game, floor, buf, near, _far = _follow_fixture(data_dir, profile)
    session = ModalSession()
    queue = _resolving(monkeypatch, [("walk", near)])
    if why == "released":
        buf.pointer_held = False
    elif why == "unfocused":
        buf.focused = False
    elif why == "modal":
        game.active_modal = SimpleNamespace()
    elif why == "keyboard":
        game.input_mode = InputMode.KEYBOARD
    elif why == "cutscene":
        session.cutscene = True
    elif why == "transition":
        game.num_camera = -1
    main.follow_pointer(game, session, floor, (10, 10), [], buf)
    assert game.nav_intent is None and buf.follow_last is None
    assert len(queue) == 1, "nothing was resolved"


def test_follow_does_not_resume_after_an_attack_latch_clears_within_the_hold(
        data_dir, profile, monkeypatch):
    # Spec Non-goal: "resuming a follow after a strike without a fresh
    # press." mouse_attack_target clears itself inside the engine
    # (playworld._clear_mouse_attack) as soon as the hero returns to idle,
    # but the button never came up -- the still-held press must not let a
    # walk/target resolution start a follow.
    import PyAitD.app.shell as main
    game, _session, state = _click_to_attack(data_dir, profile)
    state.pointer_held = True
    assert state.follow_spent is True, "an attack press spends the hold"
    state.mouse_attack_target = None   # what the engine does on idle/timeout
    state.mouse_attack_ticks = 0

    hero = game.actors[game.current_camera_target_actor]
    would_walk = (hero.room_x + 1000, hero.room_z, hero.room, -1)
    queue = _resolving(monkeypatch, [("walk", would_walk)])
    floor = Floor(data_dir, game.current_floor, profile)

    main.follow_pointer(game, ModalSession(), floor, (10, 10), [], state)

    assert game.nav_intent is None
    assert len(queue) == 1, "nothing was resolved"


def test_follow_does_not_resume_after_a_push_intent_dies_mid_hold(
        data_dir, profile, monkeypatch):
    # Same shape as the attack case: a push's requires_hold intent can die
    # (arrival, give-up) while the button is still down, and today's
    # follow_pointer would happily start walking without a fresh press.
    import PyAitD.app.shell as main
    from PyAitD.engine.script.interaction import cancel_nav_intent
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    actor_idx = game.world_objects[4].obj_index
    buf = InputBuffer(pointer_held=True)
    route_play_click(
        game, ModalSession(), floor, (150, 100),
        [(actor_idx, (100, 60, 200, 160))], buf,
    )
    assert game.nav_intent.requires_hold is True
    assert buf.follow_spent is True, "a push press spends the hold"
    cancel_nav_intent(game)   # what happens when the pushed intent dies
    assert game.nav_intent is None

    hero = game.actors[game.current_camera_target_actor]
    would_walk = (hero.room_x + 1000, hero.room_z, hero.room, -1)
    queue = _resolving(monkeypatch, [("walk", would_walk)])

    main.follow_pointer(game, ModalSession(), floor, (10, 10), [], buf)

    assert game.nav_intent is None
    assert len(queue) == 1, "nothing was resolved"


def test_release_and_a_fresh_press_clears_follow_spent(data_dir, profile, monkeypatch):
    # "released and pressed again" is the only way out of a spent hold:
    # _cancel_pointer_invalidation runs on MOUSEBUTTONUP and delegates to
    # _cancel_follow, which must clear follow_spent alongside follow_last.
    import PyAitD.app.shell as main
    game, _session, state = _click_to_attack(data_dir, profile)
    state.pointer_held = True
    assert state.follow_spent is True

    up = main.pygame.event.Event(main.pygame.MOUSEBUTTONUP, button=1)
    main._cancel_pointer_invalidation(game, up, state)
    assert state.follow_spent is False, "release clears the spent hold"

    hero = game.actors[game.current_camera_target_actor]
    dest = (hero.room_x + 1000, hero.room_z, hero.room, -1)
    state.pointer_held = True
    queue = _resolving(monkeypatch, [("walk", dest)])

    route_play_click(game, ModalSession(), None, (10, 10), [], state)

    assert state.follow_spent is False
    assert game.nav_intent is not None
    assert (game.nav_intent.dest_x, game.nav_intent.dest_z) == dest[:2]
    assert len(queue) == 0


def _sampled_pixels():
    """The logical frame at a stride coarse enough to scan with the real
    resolver, bottom-up: the lower rows are where the attic's floor is."""
    return ((x, y) for y in range(199, 60, -7) for x in range(5, 320, 7))


def _cut_fixture(data_dir, profile, after_cut):
    """A held walk mid-flight plus a camera slot that changes what the
    pointer means.

    Returns (game, floor, buf, pixel, cut_slot, before): the press has already
    been routed, so `before` is the destination the hold is heading for.
    `pixel` is a real floor pixel the resolver reports as "walk" under the
    hero's starting camera and as `after_cut` ("walk" to somewhere else, or
    "blocked") under `cut_slot`. Scanned from real data rather than
    hard-coded: which pixel qualifies is a property of the attic's five
    cameras, not of the test.
    """
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    slots = range(len(floor.rooms[game.actors[
        game.current_camera_target_actor].room].camera_indices))
    for pixel in _sampled_pixels():
        game.num_camera = game.new_num_camera
        kind, payload = resolve_play_click(game, floor, pixel, [])
        if kind != "walk":
            continue
        for slot in slots:
            if slot == game.new_num_camera:
                continue
            game.num_camera = slot
            cut_kind, cut_payload = resolve_play_click(game, floor, pixel, [])
            if cut_kind != after_cut or cut_payload == payload:
                continue
            game.num_camera = game.new_num_camera
            buf = held_pointer(pixel)
            route_play_click(game, ModalSession(), floor, pixel, [], buf)
            intent = game.nav_intent
            before = (intent.dest_x, intent.dest_z, intent.room)
            return game, floor, buf, pixel, slot, before
    raise AssertionError(f"no floor pixel turns {after_cut!r} across a cut")


def test_a_camera_cut_with_a_still_pointer_keeps_the_destination(data_dir, profile):
    # The same pixel projects through the new camera onto a point thousands of
    # units away, so re-resolving it at a cut sends the hero somewhere the
    # player never pointed at. A cut is not a gesture: with the hand still, the
    # destination must not move.
    import PyAitD.app.shell as main
    game, floor, buf, pixel, cut_slot, before = _cut_fixture(
        data_dir, profile, "walk",
    )

    game.num_camera = cut_slot   # what _camera_switch + InitView leave behind
    main.follow_pointer(game, ModalSession(), floor, pixel, [], buf)

    assert game.nav_intent is not None, "the cut stopped the hero"
    after = (game.nav_intent.dest_x, game.nav_intent.dest_z, game.nav_intent.room)
    assert after == before, "the cut retargeted a still pointer"


def test_a_camera_cut_that_unpicks_the_pixel_does_not_retarget_the_hero(data_dir, profile):
    # 386 of the attic floor pixels sampled at 7px are walkable under camera 0
    # and unpickable under another camera. Unpickable now means a steer -- a
    # bearing under a camera the hand never aimed along -- which would fling
    # the hero off somewhere nobody pointed at. The cut freeze is what stops
    # that, exactly as it stopped the old "blocked" from halting him mid-hold.
    import PyAitD.app.shell as main
    game, floor, buf, pixel, cut_slot, before = _cut_fixture(
        data_dir, profile, "steer",
    )

    game.num_camera = cut_slot
    main.follow_pointer(game, ModalSession(), floor, pixel, [], buf)

    assert game.nav_intent is not None, "the cut cancelled the walk"
    assert game.nav_intent.steering is False, "the cut turned a walk into a steer"
    after = (game.nav_intent.dest_x, game.nav_intent.dest_z, game.nav_intent.room)
    assert after == before
    assert buf.follow_last is not None, "the hold is still live"


def test_pointer_motion_after_a_cut_still_retargets(data_dir, profile):
    # The freeze is on the cut, not on the follow: moving the hand after a cut
    # must still aim the hero, resolved against the camera now on screen.
    import PyAitD.app.shell as main
    game, floor, buf, pixel, cut_slot, before = _cut_fixture(
        data_dir, profile, "walk",
    )

    game.num_camera = cut_slot
    moved = next(
        candidate
        for candidate in _sampled_pixels()
        if candidate != pixel
        and (resolved := resolve_play_click(game, floor, candidate, []))[0] == "walk"
        and resolved[1][:3] != before
    )
    buf.pointer_pos = moved
    main.follow_pointer(game, ModalSession(), floor, moved, [], buf)

    assert game.nav_intent is not None
    after = (game.nav_intent.dest_x, game.nav_intent.dest_z, game.nav_intent.room)
    assert after != before, "the follow died at the cut"
    assert after == resolve_play_click(game, floor, moved, [])[1][:3]


def test_a_one_pixel_drift_after_a_cut_does_not_retarget(data_dir, profile):
    # The hand did not move; the cut and the pointer's own jitter did. Within
    # CUT_DEAD_ZONE_PX of where the pointer was at the cut, the destination
    # stays and the follow is settling.
    import PyAitD.app.shell as main
    game, floor, buf, pixel, cut_slot, before = _cut_fixture(
        data_dir, profile, "walk",
    )
    assert buf.follow_camera == game.new_num_camera

    game.num_camera = cut_slot
    drifted = (pixel[0] + 1, pixel[1])
    buf.pointer_pos = drifted
    main.follow_pointer(game, ModalSession(), floor, drifted, [], buf)

    assert game.nav_intent is not None, "the drift stopped the hero"
    after = (game.nav_intent.dest_x, game.nav_intent.dest_z, game.nav_intent.room)
    assert after == before, "a one-pixel drift after a cut retargeted"
    assert buf.follow_settle_origin == pixel
    assert main.CUT_DEAD_ZONE_PX == 6


def test_drift_of_exactly_the_dead_zone_boundary_does_not_retarget(data_dir, profile):
    # <= keeps a boundary drift settled; only motion PAST the zone retargets.
    import PyAitD.app.shell as main
    game, floor, buf, pixel, cut_slot, before = _cut_fixture(
        data_dir, profile, "walk",
    )

    game.num_camera = cut_slot
    at_boundary = (pixel[0] + main.CUT_DEAD_ZONE_PX, pixel[1])
    buf.pointer_pos = at_boundary
    main.follow_pointer(game, ModalSession(), floor, at_boundary, [], buf)

    assert game.nav_intent is not None, "the boundary drift stopped the hero"
    after = (game.nav_intent.dest_x, game.nav_intent.dest_z, game.nav_intent.room)
    assert after == before, "a drift of exactly CUT_DEAD_ZONE_PX retargeted"
    assert buf.follow_settle_origin == pixel


def test_motion_past_the_dead_zone_retargets_and_closes_it(data_dir, profile):
    import PyAitD.app.shell as main
    game, floor, buf, pixel, cut_slot, before = _cut_fixture(
        data_dir, profile, "walk",
    )
    game.num_camera = cut_slot
    # settle first
    drifted = (pixel[0] + 1, pixel[1])
    buf.pointer_pos = drifted
    main.follow_pointer(game, ModalSession(), floor, drifted, [], buf)
    assert buf.follow_settle_origin == pixel
    moved = next(
        candidate
        for candidate in _sampled_pixels()
        if max(abs(candidate[0] - pixel[0]), abs(candidate[1] - pixel[1])) > main.CUT_DEAD_ZONE_PX
        and (resolved := resolve_play_click(game, floor, candidate, []))[0] == "walk"
        and resolved[1][:3] != before
    )
    buf.pointer_pos = moved
    main.follow_pointer(game, ModalSession(), floor, moved, [], buf)

    assert game.nav_intent is not None
    after = (game.nav_intent.dest_x, game.nav_intent.dest_z, game.nav_intent.room)
    assert after != before, "the hand moved past the dead zone and was ignored"
    assert buf.follow_settle_origin is None
    assert buf.follow_camera == cut_slot


def test_a_camera_cut_back_closes_the_dead_zone(data_dir, profile):
    # The camera can return to the slot the follow was resolved under while
    # the dead zone is still open (a doorway the hero steps in and out of).
    # That path skips the cut branch entirely, so the settle origin has to be
    # cleared on the way through: a stale one leaves the cursor drawing its
    # dashed settling ring for the rest of the hold.
    import PyAitD.app.shell as main
    game, floor, buf, pixel, cut_slot, before = _cut_fixture(
        data_dir, profile, "walk",
    )
    original_slot = buf.follow_camera

    game.num_camera = cut_slot
    drifted = (pixel[0] + 1, pixel[1])
    buf.pointer_pos = drifted
    main.follow_pointer(game, ModalSession(), floor, drifted, [], buf)
    assert buf.follow_settle_origin == pixel, "fixture: the dead zone must be open"

    game.num_camera = original_slot           # the camera cuts back
    moved = (pixel[0] + 2, pixel[1])
    buf.pointer_pos = moved
    main.follow_pointer(game, ModalSession(), floor, moved, [], buf)

    assert buf.follow_settle_origin is None, "the settle origin outlived the cut"
    assert buf.follow_camera == original_slot
    assert buf.follow_pos == moved


def test_release_clears_the_settle_state(data_dir, profile):
    import PyAitD.app.shell as main
    game, floor, buf, pixel, cut_slot, before = _cut_fixture(
        data_dir, profile, "walk",
    )
    game.num_camera = cut_slot
    drifted = (pixel[0] + 1, pixel[1])
    buf.pointer_pos = drifted
    main.follow_pointer(game, ModalSession(), floor, drifted, [], buf)
    assert buf.follow_settle_origin is not None

    up = main.pygame.event.Event(main.pygame.MOUSEBUTTONUP, button=1)
    main._cancel_pointer_invalidation(game, up, buf)
    assert buf.follow_settle_origin is None
    assert buf.follow_camera is None
    assert game.nav_intent is None


def test_a_floor_change_clears_the_settle_state_but_keeps_the_hold(data_dir, profile):
    import PyAitD.app.shell as main
    game, floor, buf, pixel, cut_slot, before = _cut_fixture(
        data_dir, profile, "walk",
    )
    buf.follow_settle_origin = pixel
    buf.follow_camera = cut_slot
    main._rebase_follow(game, buf)
    assert buf.follow_settle_origin is None
    assert buf.follow_camera is None
    assert buf.follow_pos is None
    assert buf.pointer_held is True


def test_arrival_while_settling_leaves_the_follow_live(data_dir, profile):
    # The follower clearing the intent on arrival must not be mistaken for a
    # gesture: the hold stays live, no re-resolution of a still pointer.
    import PyAitD.app.shell as main
    game, floor, buf, pixel, cut_slot, before = _cut_fixture(
        data_dir, profile, "walk",
    )
    game.num_camera = cut_slot
    drifted = (pixel[0] + 1, pixel[1])
    buf.pointer_pos = drifted
    main.follow_pointer(game, ModalSession(), floor, drifted, [], buf)
    game.nav_intent = None   # what an arrival leaves behind
    main.follow_pointer(game, ModalSession(), floor, drifted, [], buf)
    assert game.nav_intent is None, "a still pointer was re-resolved while settling"
    assert buf.follow_last is not None, "the hold died"
    assert buf.pointer_held is True


def test_a_floor_change_keeps_the_hold_and_re_resolves_a_still_pointer(
        data_dir, profile, monkeypatch):
    # Stairs mid-hold: the intent's room indexes the floor just unloaded, so
    # the destination has to go -- but the button never came up. Ending the
    # hold here stopped the hero dead on arrival and demanded a fresh press.
    import PyAitD.app.shell as main
    game, floor, buf, near, far = _follow_fixture(data_dir, profile)
    _resolving(monkeypatch, [("walk", near), ("walk", far)])
    buf.pointer_pos = (10, 10)
    main.follow_pointer(game, ModalSession(), floor, buf.pointer_pos, [], buf)
    assert game.nav_intent is not None

    assert main._rebase_follow(game, buf) is True   # what run() does at the swap
    assert game.nav_intent is None, "the old floor's destination is dropped"
    assert buf.pointer_held is True and buf.follow_spent is False, (
        "the hold outlives the floor it started on"
    )

    main.follow_pointer(game, ModalSession(), floor, buf.pointer_pos, [], buf)

    assert game.nav_intent is not None, "the still pointer was never re-resolved"
    assert (game.nav_intent.dest_x, game.nav_intent.dest_z) == far[:2]


def test_release_still_ends_a_hold_rebased_by_a_floor_change(data_dir, profile,
                                                             monkeypatch):
    # _rebase_follow is the narrow exception, not a second way to end a hold:
    # button-up must still spend it, or a hero would walk on after release.
    import PyAitD.app.shell as main
    game, floor, buf, near, _far = _follow_fixture(data_dir, profile)
    _resolving(monkeypatch, [("walk", near)])
    buf.pointer_pos = (10, 10)
    main.follow_pointer(game, ModalSession(), floor, buf.pointer_pos, [], buf)
    main._rebase_follow(game, buf)

    up = main.pygame.event.Event(main.pygame.MOUSEBUTTONUP, button=1)
    main._cancel_pointer_invalidation(game, up, buf)

    assert game.nav_intent is None
    assert (buf.follow_last, buf.follow_pos, buf.follow_spent) == (None, None, False)


def _press(main, game, floor, buf, near, monkeypatch, tick, pixel=(10, 10)):
    """One PLAY press at game.timer == tick, resolving to a walk."""
    game.timer = tick
    _resolving(monkeypatch, [("walk", near)])
    buf.pointer_held = True
    buf.pointer_pos = pixel
    route_play_click(game, ModalSession(), floor, pixel, [], buf)
    return game.nav_intent


def _primed(main, game, floor, buf, near, monkeypatch, tick=100):
    """A hold opened at `tick` and released, so the next press has something
    to be the second half of."""
    intent = _press(main, game, floor, buf, near, monkeypatch, tick)
    main._cancel_follow(game, buf)
    return intent


def test_a_second_press_inside_the_double_press_window_runs(
        data_dir, profile, monkeypatch):
    # The window is the mouse's own: a double click is one motion of one
    # finger, timed at around half a second by every desktop, not the fast key
    # repeat that FITD's double-tap forward reads.
    import PyAitD.app.shell as main
    from PyAitD.app.ui import DOUBLE_PRESS_TICKS
    from PyAitD.engine.script.playworld import TICK_MS
    game, floor, buf, near, far = _follow_fixture(data_dir, profile)
    assert DOUBLE_PRESS_TICKS * TICK_MS >= 400, (
        "a window under 400ms is quicker than most people can click twice"
    )
    assert _primed(main, game, floor, buf, near, monkeypatch).run is False, (
        "a first press walks: there is nothing to be the second half of"
    )

    intent = _press(
        main, game, floor, buf, far, monkeypatch, 100 + DOUBLE_PRESS_TICKS - 1,
    )

    assert intent.run is True
    assert buf.pointer_run is True


def test_a_second_press_outside_the_window_walks(data_dir, profile, monkeypatch):
    import PyAitD.app.shell as main
    from PyAitD.app.ui import DOUBLE_PRESS_TICKS
    game, floor, buf, near, far = _follow_fixture(data_dir, profile)
    _primed(main, game, floor, buf, near, monkeypatch)

    intent = _press(
        main, game, floor, buf, far, monkeypatch, 100 + DOUBLE_PRESS_TICKS,
    )

    assert intent.run is False, "the window is exclusive"
    assert buf.pointer_run is False


def test_a_click_of_ordinary_length_walks_before_the_button_comes_up(
        data_dir, profile, monkeypatch):
    """A press no longer than a real click must move the hero.

    From a traced session (2026-09-03): the player's press and release landed
    on the same game tick, the intent was created and cancelled without ever
    advancing, and the hero never took a step. Only a second press moved him,
    because a double press skips the wait -- "it only works if I double-click
    and do a quick run first".

    A desktop mouse click is 60-120ms down. Any wait long enough to let the
    second press of a double click arrive must outlast the gap between the two
    presses, which is longer still, so a wait that does its job is always
    longer than the gesture it swallows: with hold-bound navigation the two
    cannot coexist. This test is the floor -- a press that a player would call
    a click walks.
    """
    import PyAitD.app.shell as main
    from PyAitD.engine.script.playworld import play_tick
    game, floor, buf, near, _far = _follow_fixture(data_dir, profile)
    game.current_floor_data = floor
    hero = game.actors[game.current_camera_target_actor]
    start = (hero.room_x + hero.step_x, hero.room_z + hero.step_z)

    _press(main, game, floor, buf, near, monkeypatch, 100)
    for _ in range(5):   # 100ms, a short but entirely ordinary click
        play_tick(game, floor, buf)

    assert (hero.room_x + hero.step_x, hero.room_z + hero.step_z) != start, (
        "the click was over before the hero took a step"
    )


def test_a_double_press_never_resumes_a_bearing(data_dir, profile, monkeypatch):
    """A steer is resolved from where the hero stands, so it cannot be reused.

    Resuming exists because two presses of one double click mean one place,
    and re-picking could let a pixel of drift choose a different cell. A steer
    names no place: its destination is a point 12000 units out from wherever
    the hero was standing at the first press, and he has walked since. Reusing
    it would send him along the bearing he had a moment ago, not the one he is
    pointing at now.
    """
    import PyAitD.app.shell as main
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    game.current_floor_data = floor
    hero = game.actors[game.current_camera_target_actor]
    pixel = (2, 2)
    assert resolve_play_click(game, floor, pixel, [])[0] == "steer"
    buf = held_pointer(pixel)
    game.timer = 100
    route_play_click(game, ModalSession(), floor, pixel, [], buf)
    stale = (game.nav_intent.dest_x, game.nav_intent.dest_z)
    main._cancel_follow(game, buf)

    hero.room_x += 900          # he walked while the button was up
    game.timer = 103
    route_play_click(game, ModalSession(), floor, pixel, [], buf)

    assert buf.pointer_run is True, "the fixture must be a double press"
    fresh = resolve_play_click(game, floor, pixel, [])[1]
    assert (game.nav_intent.dest_x, game.nav_intent.dest_z) == fresh[:2]
    assert (game.nav_intent.dest_x, game.nav_intent.dest_z) != stale


def test_the_second_press_of_a_double_press_resumes_the_first_destination(
        data_dir, profile, monkeypatch):
    # A double click is one motion of one finger, and its second press means
    # "there, faster" -- not a fresh pick. Re-resolving it lets a pixel of
    # hand drift choose a different cell halfway through one gesture, so the
    # second press reuses what the first committed to and only raises the
    # speed.
    import PyAitD.app.shell as main
    game, floor, buf, near, far = _follow_fixture(data_dir, profile)
    _primed(main, game, floor, buf, near, monkeypatch)
    assert game.nav_intent is None, (
        "the release still ends the intent: the hero never moves button-up"
    )

    intent = _press(main, game, floor, buf, far, monkeypatch, 103)

    assert (intent.dest_x, intent.dest_z) == near[:2], (
        "the second press resumed the first press's destination"
    )
    assert intent.run is True


def test_a_double_press_that_moved_off_the_first_pixel_picks_the_new_spot(
        data_dir, profile, monkeypatch):
    # Resuming is for the jitter of one finger, not for a deliberate second
    # click somewhere else: past the resume window the new pick wins, and it
    # still runs, because the run belongs to the gesture.
    import PyAitD.app.shell as main
    from PyAitD.app.shell import DOUBLE_PRESS_RESUME_PX
    game, floor, buf, near, far = _follow_fixture(data_dir, profile)
    _primed(main, game, floor, buf, near, monkeypatch)

    intent = _press(
        main, game, floor, buf, far, monkeypatch, 103,
        pixel=(10 + DOUBLE_PRESS_RESUME_PX + 1, 10),
    )

    assert (intent.dest_x, intent.dest_z) == far[:2]
    assert intent.run is True


def test_a_floor_change_drops_the_resumable_destination(
        data_dir, profile, monkeypatch):
    # resume_last carries a room index, and a floor change unloads the floor
    # that index belongs to. The hold survives the stairs; what it was
    # heading for cannot.
    import PyAitD.app.shell as main
    game, floor, buf, near, far = _follow_fixture(data_dir, profile)
    _primed(main, game, floor, buf, near, monkeypatch)
    assert buf.resume_last == near

    main._rebase_follow(game, buf)

    assert (buf.resume_last, buf.resume_pos) == (None, None)
    intent = _press(main, game, floor, buf, far, monkeypatch, 103)
    assert (intent.dest_x, intent.dest_z) == far[:2]


def test_a_retarget_within_a_running_hold_keeps_running(
        data_dir, profile, monkeypatch):
    # The run belongs to the hold, not to the destination: aiming somewhere
    # else without releasing must not drop the hero back to a walk.
    import PyAitD.app.shell as main
    game, floor, buf, near, far = _follow_fixture(data_dir, profile)
    _primed(main, game, floor, buf, near, monkeypatch)
    assert _press(main, game, floor, buf, near, monkeypatch, 105).run is True

    _resolving(monkeypatch, [("walk", far)])
    buf.pointer_pos = (11, 10)
    main.follow_pointer(game, ModalSession(), floor, buf.pointer_pos, [], buf)

    assert (game.nav_intent.dest_x, game.nav_intent.dest_z) == far[:2]
    assert game.nav_intent.run is True


def test_release_ends_the_run_but_keeps_the_press_clock(
        data_dir, profile, monkeypatch):
    # last_press_tick is what the *next* press is measured against, so it has
    # to outlive the release that ends the run it started.
    import PyAitD.app.shell as main
    game, floor, buf, near, _far = _follow_fixture(data_dir, profile)
    _primed(main, game, floor, buf, near, monkeypatch)
    _press(main, game, floor, buf, near, monkeypatch, 105)
    assert buf.pointer_run is True

    up = main.pygame.event.Event(main.pygame.MOUSEBUTTONUP, button=1)
    main._cancel_pointer_invalidation(game, up, buf)

    assert buf.pointer_run is False, "the run ends with the hold"
    assert buf.last_press_tick == 105


def test_a_held_push_never_runs(data_dir, profile, monkeypatch):
    # A push is a lean on furniture; FITD's push animation has no run speed,
    # and apply_click_intent refuses the combination rather than the caller
    # having to remember it.
    import PyAitD.app.shell as main
    from PyAitD.engine.script.interaction import apply_click_intent
    game, floor, buf, near, _far = _follow_fixture(data_dir, profile)
    _primed(main, game, floor, buf, near, monkeypatch)
    game.timer = 105
    _resolving(monkeypatch, [("push", near)])
    route_play_click(game, ModalSession(), floor, (10, 10), [], buf)

    assert buf.pointer_run is True, "the double press was still a double press"
    assert game.nav_intent.requires_hold is True
    assert game.nav_intent.run is False

    apply_click_intent(game, 10, 20, 0, 4, requires_hold=True, run=True)
    assert game.nav_intent.run is False


@pytest.mark.parametrize(
    "input_mode, modal, visible",
    (
        (InputMode.KEYBOARD, None, False),
        (InputMode.MOUSE, None, False),
        (InputMode.KEYBOARD, "modal", True),
        (InputMode.MOUSE, "modal", True),
    ),
    ids=("play-keyboard", "play-mouse", "modal-keyboard", "modal-mouse"),
)
def test_the_os_pointer_shows_only_where_the_mouse_still_does_something(
        profile, monkeypatch, tmp_path, input_mode, modal, visible,
):
    # Exactly one cursor, and none at all where the mouse is inert. PLAY draws
    # its own software cursor in mouse mode and has no mouse function at all in
    # keyboard mode -- neither state wants the OS pointer. Modals keep it in
    # both modes: their buttons stay clickable however the hero is driven.
    import PyAitD.app.shell as main
    from PyAitD.engine.script.effects import GameMode

    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    event_batches = iter([[], [SimpleNamespace(type=main.pygame.QUIT)]])
    times = iter([0, 100, 100])
    visibility = []

    monkeypatch.setattr(
        main, "Renderer",
        lambda *_a, **_k: SimpleNamespace(
            fallback_notice=None, present=lambda _image: None, close=lambda: None,
        ),
    )
    monkeypatch.setattr(main, "play_tick", lambda *_args: True)
    monkeypatch.setattr(main, "_scene_frame", lambda *_args: (frame, []))
    monkeypatch.setattr(
        main, "render_active_mode", lambda *_args: painter_from_frame(frame),
    )
    monkeypatch.setattr(main.pygame.mouse, "set_visible", visibility.append)
    # key_code() warns on a pygame this test never init()s, and the key map is
    # irrelevant to cursor visibility
    monkeypatch.setattr(main, "configure_session_input", lambda *_args: None)
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(times))
    monkeypatch.setattr(
        main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *_args: None),
    )

    game = SimpleNamespace(
        _data_dir=tmp_path, current_floor=0, trace=None, mode=GameMode.PLAY,
        num_camera=-1, new_num_camera=0, flag_init_view=0, current_room=0,
        actors=[], active_modal=SimpleNamespace() if modal else None,
        input_mode=input_mode,
        restart_requested=False,
        current_camera_target_actor=-1,
        inventory_count=[0, 0], inventory_table=[[-1] * 30, [-1] * 30],
        current_inventory=0, status_screen_allowed=1, assets=object(),
        load_floor=lambda number: SimpleNamespace(
            number=0, rooms=[SimpleNamespace(camera_indices=[0])],
        ),
        profile=profile,
    )
    assert main.run(game) == 0
    # run() restores the pointer as it leaves, so the last call is teardown,
    # not a frame's decision -- the per-frame values are everything before it
    assert visibility[-1] is True, visibility
    per_frame = visibility[:-1]
    assert per_frame and all(seen is visible for seen in per_frame), visibility


def test_intent_marker_projects_the_live_destination(data_dir, profile):
    import PyAitD.app.shell as main
    from PyAitD.engine.nav.picking import project_room_point
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    hero = game.actors[game.current_camera_target_actor]
    pixel = next(p for p in _sampled_pixels() if resolve_play_click(game, floor, p, [])[0] == "walk")
    buf = held_pointer(pixel)
    route_play_click(game, ModalSession(), floor, pixel, [], buf)
    intent = game.nav_intent
    expected = project_room_point(
        floor, hero.room, game.num_camera, intent.room,
        intent.dest_x, hero.world_y, intent.dest_z,
    )
    assert main._intent_marker(game, floor) == expected
    assert expected is not None


def test_intent_marker_is_none_without_an_intent_or_on_a_transition_frame(data_dir, profile):
    import PyAitD.app.shell as main
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    assert game.nav_intent is None
    assert main._intent_marker(game, floor) is None
    hero = game.actors[game.current_camera_target_actor]
    from PyAitD.engine.script.interaction import apply_click_intent
    apply_click_intent(game, hero.room_x + 500, hero.room_z, hero.room)
    game.num_camera = -1
    assert main._intent_marker(game, floor) is None


def test_play_cursor_state_returns_kind_and_payload(data_dir, profile):
    import PyAitD.app.shell as main
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    pixel = next(p for p in _sampled_pixels() if resolve_play_click(game, floor, p, [])[0] == "walk")
    buf = InputBuffer()
    kind, payload = main._play_cursor_state(game, floor, pixel, [], buf)
    assert kind == "walk" and payload is not None
    assert main._play_cursor_kind(game, floor, pixel, [], buf) == "walk"
    assert main._marker_for(game, floor, payload) is not None


def test_run_hands_the_cursor_its_marker_ring_and_settle_state(data_dir, profile, monkeypatch):
    # The loop's cursor site passes the live intent's marker, the hold and
    # the dead zone through to render_cursor. Checked by capturing the call.
    import PyAitD.app.shell as main
    calls = []

    def spy(painter, pos, kind, **kw):
        calls.append((pos, kind, kw))
    monkeypatch.setattr(main, "render_cursor", spy)
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    game.num_camera = game.new_num_camera
    pixel = next(p for p in _sampled_pixels() if resolve_play_click(game, floor, p, [])[0] == "walk")
    buf = held_pointer(pixel)
    route_play_click(game, ModalSession(), floor, pixel, [], buf)
    # route_play_click closes the dead zone as part of committing a fresh
    # press (it is a brand new gesture, not a cut settling) -- reopen it
    # here to simulate a cut landing mid-hold, which is what the dashed
    # ring is meant to reflect.
    buf.follow_settle_origin = pixel
    main._render_play_cursor(game, floor, pixel, [], buf, painter=None)
    (pos, kind, kw), = calls
    assert pos == pixel and kind == "walk"
    assert kw["held"] is True
    assert kw["settling"] is True
    assert kw["destination"] == main._intent_marker(game, floor)
    assert kw["preview"] is None, "no preview while a press is held"
