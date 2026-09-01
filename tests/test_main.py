# SPDX-License-Identifier: GPL-2.0-only
import json
import pathlib
import subprocess
from types import SimpleNamespace

import pytest

from PyAitD.app.shell import parse_args
from PyAitD.app.config import default_settings
from PyAitD.engine.script.effects import ShowTitle
from tests.conftest import painter_from_frame

pytestmark = pytest.mark.shell


def test_parse_args_defaults():
    args = parse_args([])
    assert args.floor is None
    assert args.data is not None
    assert args.combat_venue is False
    assert args.mouse_combat_fixture is False
    assert args.hero == 0


def test_parse_args_distinguishes_normal_boot_from_explicit_floor_zero():
    assert parse_args([]).floor is None
    assert parse_args(["--floor", "0"]).floor == 0


def test_parse_args_skip_intro():
    assert parse_args([]).skip_intro is False
    assert parse_args(["--skip-intro"]).skip_intro is True


def test_main_skip_intro_produces_a_session_whose_hero_boot_is_not_a_cutscene(monkeypatch, data_dir, profile):
    # --skip-intro's only real effect in main() is `session.skip_intro =
    # args.skip_intro`; _hero_branch reads it to decide `cutscene=False`
    # (straight to the attic) instead of `cutscene=True` (the floor-7
    # opening) -- see AITD1.cpp:352-361 / shell._hero_branch. Boot for real
    # through main() with --skip-intro, capture the session it produces,
    # then drive the real character-confirmation branch with that exact
    # session and prove the hero boot it stages is NOT a cutscene. Deleting
    # `session.skip_intro = args.skip_intro` leaves skip_intro at its False
    # default and this assertion fails, since profile.intro_start is set.
    import numpy as np

    import PyAitD.app.shell as main
    from PyAitD.app.config import default_settings
    from PyAitD.app.ui import ModalSession

    captured = {}

    def fake_run(game, trace, session=None, mirror_sink=None):
        captured["session"] = session
        return 0

    monkeypatch.setattr(main, "run", fake_run)
    monkeypatch.setattr(
        main, "load_runtime_session",
        lambda path, save_directory=None: ModalSession(settings=default_settings()),
    )
    assert main.main(["--data", str(data_dir), "--skip-intro"]) == 0

    session = captured["session"]
    assert session.skip_intro is True

    from PyAitD.engine.script.game import init_game

    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (frame, []))
    game = init_game(data_dir, profile)
    assert game.profile.intro_start is not None   # precondition: profile HAS an intro
    session.pending_hero = 0

    from types import SimpleNamespace
    from PyAitD.app.ui import InputBuffer

    replaced = main._hero_branch(game, SimpleNamespace(), session, InputBuffer())
    assert replaced is not None
    new_session = replaced[2]
    assert new_session.cutscene is False


def test_normal_main_opens_the_title_before_run(monkeypatch, tmp_path):
    import PyAitD.app.shell as main
    game = SimpleNamespace(active_modal=None, open_modal=lambda effect: setattr(game, "active_modal", effect))
    seen = []
    monkeypatch.setattr(main, "init_game", lambda data, profile, hero=0: game)
    monkeypatch.setattr(main, "load_runtime_session", lambda path, save_directory=None: SimpleNamespace(settings=default_settings()))
    monkeypatch.setattr(main, "run", lambda g, trace, session=None, mirror_sink=None: seen.append((g, session)) or 0)
    assert main.main(["--data", str(tmp_path)]) == 0
    assert isinstance(game.active_modal, ShowTitle)
    assert seen and seen[0][0] is game


@pytest.mark.parametrize("args", (["--floor", "0"], ["--combat-venue"], ["--mouse-combat-fixture"]))
def test_explicit_debug_starts_bypass_character_selection(monkeypatch, tmp_path, args):
    import PyAitD.app.shell as main
    game = SimpleNamespace(active_modal=None)
    seen = []
    monkeypatch.setattr(main, "init_game", lambda data, profile, hero=0: game)
    monkeypatch.setattr(
        main, "load_profile",
        lambda name: SimpleNamespace(debug_venues={
            "combat-venue": lambda value: None,
            "mouse-combat-fixture": lambda value: None,
        }),
    )
    monkeypatch.setattr(main, "load_runtime_session", lambda path, save_directory=None: SimpleNamespace(settings=default_settings()))
    monkeypatch.setattr(
        main, "run",
        lambda value, trace, session=None, mirror_sink=None: seen.append((value, session)) or 0,
    )
    assert main.main([*args, "--data", str(tmp_path)]) == 0
    assert game.active_modal is None
    assert seen and seen[0][0] is game


def test_parse_args_overrides():
    args = parse_args(["--floor", "3", "--data", "/tmp/x"])
    assert args.floor == 3
    assert args.data == pathlib.Path("/tmp/x")


def test_parse_args_save_dir():
    assert parse_args([]).save_dir is None
    args = parse_args(["--save-dir", "/tmp/saves"])
    assert args.save_dir == pathlib.Path("/tmp/saves")


def test_load_runtime_session_takes_the_save_directory(tmp_path):
    from PyAitD.app.shell import load_runtime_session
    session = load_runtime_session(tmp_path / "settings.json", save_directory=tmp_path / "saves")
    assert session.save_directory == tmp_path / "saves"


def test_main_rejects_nonzero_floor_without_calling_run(monkeypatch, tmp_path):
    import PyAitD.app.shell as main

    monkeypatch.setattr(main, "init_game", lambda data, profile, hero=0: SimpleNamespace())
    calls = []
    monkeypatch.setattr(main, "run", lambda *args: calls.append("run"))

    exit_code = main.main(["--floor", "5", "--data", str(tmp_path)])

    assert exit_code == 2
    assert calls == []


def test_main_combat_venue_calls_enter_combat_venue_once_before_run(monkeypatch, tmp_path):
    import PyAitD.app.shell as main

    game = SimpleNamespace()
    calls = []
    monkeypatch.setattr(main, "init_game", lambda data, profile, hero=0: game)
    monkeypatch.setattr(
        main, "load_profile",
        lambda name: SimpleNamespace(debug_venues={
            "combat-venue": lambda g: calls.append(("venue", g)),
        }),
    )
    monkeypatch.setattr(main, "load_runtime_session", lambda path, save_directory=None: SimpleNamespace(settings=default_settings()))
    monkeypatch.setattr(main, "run", lambda g, trace, session=None, mirror_sink=None: calls.append(("run", g)))

    main.main(["--combat-venue", "--data", str(tmp_path)])

    assert calls == [("venue", game), ("run", game)]


def test_parse_args_has_a_separate_mouse_combat_start():
    args = parse_args(["--mouse-combat-fixture"])
    assert args.mouse_combat_fixture is True
    assert args.combat_venue is False


def test_parse_args_selects_a_fixture_hero():
    # The debug starts bypass the character selector, so the only way to prove
    # the mouse contract for both heroes in a real window is to name one.
    assert parse_args(["--mouse-combat-fixture", "--hero", "1"]).hero == 1
    assert parse_args(["--combat-venue", "--hero", "0"]).hero == 0
    with pytest.raises(SystemExit):
        parse_args(["--hero", "2"])


def test_main_mouse_combat_fixture_uses_the_requested_hero(monkeypatch, tmp_path):
    import PyAitD.app.shell as main

    game = SimpleNamespace()
    heroes = []
    monkeypatch.setattr(
        main, "init_game",
        lambda data, profile, hero=0: heroes.append(hero) or game,
    )
    monkeypatch.setattr(
        main, "load_profile",
        lambda name: SimpleNamespace(debug_venues={"mouse-combat-fixture": lambda g: None}),
    )
    monkeypatch.setattr(main, "load_runtime_session", lambda path, save_directory=None: SimpleNamespace(settings=default_settings()))
    monkeypatch.setattr(main, "run", lambda g, trace, session=None, mirror_sink=None: 0)

    assert main.main([
        "--mouse-combat-fixture", "--hero", "1", "--data", str(tmp_path),
    ]) == 0

    assert heroes == [1]


def test_main_mouse_combat_fixture_runs_its_own_setup(monkeypatch, tmp_path):
    import PyAitD.app.shell as main

    game = SimpleNamespace()
    calls = []
    monkeypatch.setattr(main, "init_game", lambda data, profile, hero=0: game)
    monkeypatch.setattr(
        main, "load_profile",
        lambda name: SimpleNamespace(debug_venues={
            "mouse-combat-fixture": lambda g: calls.append(("mouse fixture", g)),
        }),
    )
    monkeypatch.setattr(main, "load_runtime_session", lambda path, save_directory=None: SimpleNamespace(settings=default_settings()))
    monkeypatch.setattr(main, "run", lambda g, trace, session=None, mirror_sink=None: calls.append(("run", g)) or 0)
    assert main.main([
        "--mouse-combat-fixture", "--data", str(tmp_path),
    ]) == 0
    assert calls == [("mouse fixture", game), ("run", game)]


def test_mirror_sink_write_degrades_once_when_the_helper_dies(
    monkeypatch, data_dir, capsys,
):
    # The helper is a separate process; when it dies the pipe write raises
    # BrokenPipeError. That must degrade the port (one stderr note, then
    # no-op), never crash the run loop.
    import os

    import PyAitD.app.shell as main
    from PyAitD.app.ui import ModalSession

    captured = {}

    def fake_run(game, trace, session=None, mirror_sink=None):
        captured["sink"] = mirror_sink
        return 0

    read_fd, write_fd = os.pipe()
    monkeypatch.setenv("PYAITD_MIRROR_FD", str(write_fd))
    monkeypatch.setenv("PYAITD_MIRROR_PID", "4242")
    monkeypatch.setattr(main, "run", fake_run)
    monkeypatch.setattr(
        main, "load_runtime_session",
        lambda path, save_directory=None: ModalSession(settings=default_settings()),
    )
    assert main.main(["--data", str(data_dir), "--mirror"]) == 0
    sink = captured["sink"]

    # Live pipe: the line reaches the helper.
    sink.key_down("UP")
    assert os.read(read_fd, 4096) == b"post 126 down 4242\n"

    # Helper dies: the next write fails, notes once, then no-ops.
    os.close(read_fd)
    sink.key_down("UP")
    sink.key_down("UP")
    notes = [line for line in capsys.readouterr().err.splitlines()
             if "mirror helper died" in line]
    assert len(notes) == 1


def test_make_run_uses_shell_by_default_and_floor_zero_only_when_explicit():
    plain = subprocess.run(
        ["make", "-n", "run"], capture_output=True, text=True, check=True,
    ).stdout
    explicit = subprocess.run(
        ["make", "-n", "run", "floor=0"],
        capture_output=True, text=True, check=True,
    ).stdout
    plain_run = next(line for line in plain.splitlines() if " -m PyAitD " in line)
    explicit_run = next(line for line in explicit.splitlines() if " -m PyAitD " in line)
    assert "--floor" not in plain_run
    assert '--floor "0"' in explicit_run
    assert '--textures "data/aitd1/textures"' in plain_run


def test_unknown_pygame_key_falls_back_to_defaults_with_a_path_named_notice(tmp_path):
    # load_runtime_session is a JSON-only boot step: a structurally valid file
    # whose key names pygame does not know must load cleanly, and only the
    # input compilation (which owns the pygame key table) may fall back to
    # defaults -- recording a notice that names the offending file.
    from PyAitD.app.shell import configure_session_input, load_runtime_session
    from PyAitD.app.config import SCHEMA, default_settings
    from PyAitD.render.render_options import RenderOptions
    from PyAitD.app.ui import InputBuffer

    bindings = {name: list(keys) for name, keys in default_settings().bindings.items()}
    bindings["UP"] = ["not-a-real-pygame-key"]
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "schema": SCHEMA, "sticky_action": False, "bindings": bindings,
        "render": RenderOptions().to_payload(),
    }), encoding="utf-8")

    session = load_runtime_session(path)
    assert session.settings_error is None
    assert session.settings.bindings["UP"] == ("not-a-real-pygame-key",)

    buffer = InputBuffer()
    configure_session_input(session, buffer)

    assert session.settings == default_settings()
    assert str(path) in session.settings_error
    assert buffer.bindings is not None


def test_render_cli_flags_override_settings_for_the_session():
    from PyAitD.app.shell import apply_render_overrides, parse_args
    from PyAitD.app.config import default_settings
    args = parse_args(["--render-scale", "2", "--shading", "flat", "--textures", "/tmp/ov"])
    settings = apply_render_overrides(default_settings(), args)
    assert (settings.render.scale, settings.render.shading, settings.render.background_filter,
            settings.render.texture_dir) == (2, "flat", "bilinear", "/tmp/ov")
    assert apply_render_overrides(default_settings(), parse_args([])) == default_settings()
    assert apply_render_overrides(default_settings(), parse_args(["--render-scale", "50"])).render.scale == 8


def test_each_render_flag_overrides_only_its_own_field():
    from dataclasses import replace

    from PyAitD.app.shell import apply_render_overrides, parse_args
    from PyAitD.app.config import default_settings

    base = default_settings()

    scale_only = apply_render_overrides(base, parse_args(["--render-scale", "6"]))
    assert scale_only == replace(base, render=replace(base.render, scale=6))

    shading_only = apply_render_overrides(base, parse_args(["--shading", "lambert"]))
    assert shading_only == replace(base, render=replace(base.render, shading="lambert"))

    filter_only = apply_render_overrides(base, parse_args(["--background-filter", "xbr"]))
    assert filter_only == replace(base, render=replace(base.render, background_filter="xbr"))

    overrides_only = apply_render_overrides(base, parse_args(["--textures", "/tmp/only-ov"]))
    assert overrides_only == replace(base, render=replace(base.render, texture_dir="/tmp/only-ov"))


def test_smoothing_flag_overrides_only_its_own_field():
    from dataclasses import replace

    from PyAitD.app.shell import apply_render_overrides, parse_args
    from PyAitD.app.config import default_settings

    base = default_settings()
    only = apply_render_overrides(base, parse_args(["--smoothing", "3"]))
    assert only == replace(base, render=replace(base.render, smoothing=3))
    with pytest.raises(SystemExit):
        parse_args(["--smoothing", "5"])   # argparse choices reject it


def test_no_render_flags_leaves_settings_completely_unchanged():
    from PyAitD.app.shell import apply_render_overrides, parse_args
    from PyAitD.app.config import default_settings

    base = default_settings()
    assert apply_render_overrides(base, parse_args([])) == base


def test_out_of_range_render_scale_is_clamped_not_rejected():
    from PyAitD.app.shell import apply_render_overrides, parse_args
    from PyAitD.app.config import default_settings

    assert apply_render_overrides(default_settings(), parse_args(["--render-scale", "0"])).render.scale == 1
    assert apply_render_overrides(default_settings(), parse_args(["--render-scale", "99"])).render.scale == 8


def test_invalid_shading_and_background_filter_are_rejected_by_argparse_choices():
    from PyAitD.app.shell import parse_args

    with pytest.raises(SystemExit):
        parse_args(["--shading", "cartoon"])
    with pytest.raises(SystemExit):
        parse_args(["--background-filter", "crt"])


def test_render_cli_flags_default_to_none_meaning_keep_the_settings_value():
    from PyAitD.app.shell import parse_args

    args = parse_args([])
    assert args.render_scale is None
    assert args.shading is None
    assert args.background_filter is None
    assert args.textures is None


def test_render_cli_overrides_do_not_persist_to_the_settings_file(tmp_path):
    # Session-only: apply_render_overrides must never be written back to the
    # settings file, and must not flip settings_dirty (which is what would
    # cause a later save to pick it up).
    from PyAitD.app.shell import apply_render_overrides, load_runtime_session, parse_args
    from PyAitD.app.config import SCHEMA, default_settings

    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({
        "schema": SCHEMA, "sticky_action": False,
        "bindings": {name: list(keys) for name, keys in default_settings().bindings.items()},
        "render": default_settings().render.to_payload(),
    }), encoding="utf-8")
    before = settings_file.read_text(encoding="utf-8")

    session = load_runtime_session(settings_file)
    args = parse_args(["--render-scale", "7", "--shading", "flat"])
    session.settings = apply_render_overrides(session.settings, args)

    assert session.settings.render.scale == 7
    assert session.settings.render.shading == "flat"
    assert session.settings_dirty is False
    assert settings_file.read_text(encoding="utf-8") == before


def test_config_menu_save_does_not_persist_untouched_cli_render_overrides(tmp_path):
    """Finding 2's full repro: launch with CLI render overrides --
    including --textures, which has no CONFIG menu row at all -- open the
    CONFIG menu, touch only Sticky Action (nothing render-related), and
    leave. The settings file on disk afterward must show the *original*
    render values, not argv's: this is asserted on the settings file's
    actual bytes on disk, not on in-memory session state, so a regression
    that only *looks* right in memory (e.g. session.settings itself) still
    fails this test.
    """
    from dataclasses import replace

    import pygame

    from PyAitD.app.shell import (
        _apply_system_result, apply_render_overrides, load_runtime_session, parse_args,
    )
    from PyAitD.app.config import SCHEMA, default_settings
    from PyAitD.app.ui import InputBuffer, SystemMenuResult

    pygame.init()
    settings_file = tmp_path / "settings.json"
    original_payload = {
        "schema": SCHEMA, "sticky_action": False,
        "bindings": {name: list(keys) for name, keys in default_settings().bindings.items()},
        "render": default_settings().render.to_payload(),
    }
    settings_file.write_text(json.dumps(original_payload), encoding="utf-8")

    session = load_runtime_session(settings_file)
    textures_dir = str(tmp_path / "my-hd-pack")
    args = parse_args([
        "--render-scale", "7", "--shading", "flat", "--textures", textures_dir,
    ])
    session.settings = apply_render_overrides(session.settings, args)
    assert (session.settings.render.scale, session.settings.render.shading,
            session.settings.render.texture_dir) == (7, "flat", textures_dir)

    input_buffer = InputBuffer()
    game = SimpleNamespace(close_modal=lambda: None)
    # The only row actually pressed in CONFIG: Sticky Action.
    toggle = SystemMenuResult(settings=replace(session.settings, sticky_action=True))
    assert _apply_system_result(game, session, input_buffer, toggle) is True
    # Escape back out of the menu: closes and triggers the save.
    leave = SystemMenuResult(close=True, save=True)
    assert _apply_system_result(game, session, input_buffer, leave) is True

    on_disk = json.loads(settings_file.read_text(encoding="utf-8"))
    assert on_disk["sticky_action"] is True  # the one thing actually changed
    assert on_disk["render"] == default_settings().render.to_payload()
    assert on_disk["render"]["texture_dir"] is None

    # The CLI overrides stay in effect in memory for the rest of this run.
    assert session.settings.render.scale == 7
    assert session.settings.render.texture_dir == textures_dir


def test_config_menu_save_persists_a_render_field_the_player_actually_cycled(tmp_path):
    """The flip side of the repro above: a render field the player *did*
    reach through a CONFIG menu row (Scale/Shading/Filter) must still
    persist, even in the same session as an untouched CLI override for a
    different field -- so the fix can't just blanket-refuse to ever save
    render settings.
    """
    from dataclasses import replace

    import pygame

    from PyAitD.app.shell import (
        _apply_system_result, apply_render_overrides, load_runtime_session, parse_args,
    )
    from PyAitD.app.config import SCHEMA, default_settings
    from PyAitD.render.render_options import cycle_shading
    from PyAitD.app.ui import InputBuffer, SystemMenuResult

    pygame.init()
    settings_file = tmp_path / "settings.json"
    original_payload = {
        "schema": SCHEMA, "sticky_action": False,
        "bindings": {name: list(keys) for name, keys in default_settings().bindings.items()},
        "render": default_settings().render.to_payload(),
    }
    settings_file.write_text(json.dumps(original_payload), encoding="utf-8")

    session = load_runtime_session(settings_file)
    textures_dir = str(tmp_path / "cli-only")
    args = parse_args(["--textures", textures_dir])
    session.settings = apply_render_overrides(session.settings, args)

    input_buffer = InputBuffer()
    game = SimpleNamespace(close_modal=lambda: None)
    # The player actually presses the Shading row in CONFIG this time.
    cycled = SystemMenuResult(
        settings=replace(session.settings, render=cycle_shading(session.settings.render)),
    )
    assert _apply_system_result(game, session, input_buffer, cycled) is True
    leave = SystemMenuResult(close=True, save=True)
    assert _apply_system_result(game, session, input_buffer, leave) is True

    on_disk = json.loads(settings_file.read_text(encoding="utf-8"))
    # The explicitly-cycled field persists...
    assert on_disk["render"]["shading"] == cycle_shading(default_settings().render).shading
    # ...but the untouched CLI-only texture_dir still does not leak in.
    assert on_disk["render"]["texture_dir"] is None
    assert on_disk["render"]["scale"] == default_settings().render.scale


def test_main_wires_render_cli_overrides_into_renderer_and_asset_resolver(profile, monkeypatch, tmp_path):
    # Task 9 was sent back for unpinned run() wiring; pin this end to end
    # through main() -- not just apply_render_overrides in isolation -- by
    # spying on the module-level Renderer/AssetResolver constructors that
    # run() actually calls.
    import numpy as np
    import pygame

    import PyAitD.app.shell as main
    from PyAitD.app import ui
    from PyAitD.engine.script.effects import GameMode, InputMode

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
    frame = np.zeros((200, 320, 3), dtype=np.uint8)
    event_batches = iter([[], [SimpleNamespace(type=main.pygame.QUIT)]])
    times = iter([0, 100, 100])
    renderer_options = []
    resolver_calls = []

    monkeypatch.setattr(main, "init_game", lambda data, profile, hero=0: game)
    monkeypatch.setattr(
        main, "load_runtime_session",
        lambda path, save_directory=None: SimpleNamespace(
            settings=default_settings(), settings_path=path, settings_error=None,
            settings_dirty=False, pending_hero=None, cutscene=False,
            pending_load=None, quick_save_requested=False, runtime_error=None,
        ),
    )
    monkeypatch.setattr(
        main, "Renderer",
        lambda options, **kw: renderer_options.append(options) or SimpleNamespace(
            fallback_notice=None, present=lambda image: None, close=lambda: None,
        ),
    )
    monkeypatch.setattr(
        main, "AssetResolver",
        lambda assets, texture_dir=None, **kw: resolver_calls.append(texture_dir) or object(),
    )
    monkeypatch.setattr(main, "play_tick", lambda *args: True)
    monkeypatch.setattr(main, "_scene_frame", lambda *args: (frame, []))
    monkeypatch.setattr(main, "render_active_mode", lambda *args: painter_from_frame(frame))
    monkeypatch.setattr(main.pygame.mouse, "set_visible", lambda value: None)
    monkeypatch.setattr(main.pygame.display, "set_caption", lambda *args: None)
    monkeypatch.setattr(main.pygame.event, "get", lambda: next(event_batches))
    monkeypatch.setattr(main.pygame.time, "get_ticks", lambda: next(times))
    monkeypatch.setattr(
        main.pygame.time, "Clock", lambda: SimpleNamespace(tick=lambda *args: None)
    )

    textures_dir = str(tmp_path / "ov")
    # The stub Renderer above skips the pygame.init() a real Renderer would
    # do before configure_session_input's key-binding validation reaches
    # pygame.key.key_code -- without it that call warns.
    pygame.init()
    try:
        exit_code = main.main([
            "--data", str(tmp_path), "--floor", "0",
            "--render-scale", "2", "--shading", "flat", "--textures", textures_dir,
        ])
    finally:
        pygame.quit()
        ui._font.cache_clear()

    assert exit_code == 0
    assert renderer_options and renderer_options[0].scale == 2
    assert renderer_options[0].shading == "flat"
    assert resolver_calls == [textures_dir]


def test_shadows_flag_overrides_only_its_own_field():
    from dataclasses import replace

    from PyAitD.app.shell import apply_render_overrides, parse_args
    from PyAitD.app.config import default_settings

    base = default_settings()
    only = apply_render_overrides(base, parse_args(["--shadows", "hard"]))
    assert only == replace(base, render=replace(base.render, shadows="hard"))
    with pytest.raises(SystemExit):
        parse_args(["--shadows", "blurry"])   # argparse choices reject it


def test_integration_flag_overrides_only_its_own_field():
    from dataclasses import replace

    from PyAitD.app.shell import apply_render_overrides, parse_args
    from PyAitD.app.config import default_settings

    base = default_settings()
    assert apply_render_overrides(base, parse_args([])) == base
    only = apply_render_overrides(base, parse_args(["--integration", "1"]))
    assert only == replace(base, render=replace(base.render, integration=1))
    for bad in ("sometimes", "4", "-1", "2.5", ""):
        with pytest.raises(SystemExit):
            parse_args(["--integration", bad])       # the level parser rejects it


def test_the_integration_flag_still_takes_the_words_it_used_to():
    from PyAitD.app.shell import parse_args

    assert parse_args(["--integration", "off"]).integration == 0
    assert parse_args(["--integration", "on"]).integration == 2


def test_motion_cli_override_is_session_only_and_alone():
    from dataclasses import replace
    from PyAitD.app.config import default_settings
    from PyAitD.app.shell import apply_render_overrides, parse_args
    base = default_settings()
    only = apply_render_overrides(base, parse_args(["--motion", "smooth"]))
    # exactly the motion field moved, nothing else
    assert only.render == replace(base.render, motion="smooth")
    assert apply_render_overrides(base, parse_args([])).render.motion == "tick"


def test_menu_render_fields_cover_motion():
    from PyAitD.app.shell import _MENU_RENDER_FIELDS
    assert "motion" in _MENU_RENDER_FIELDS


def test_motion_blend_helper_gates_on_mode_and_snapshot():
    from PyAitD.app.config import default_settings
    from PyAitD.app.shell import _motion_blend
    from PyAitD.engine.script.playworld import TICK_MS

    class _Session:
        settings = default_settings()   # motion="tick" until Task 6

    session = _Session()
    sentinel = object()
    assert _motion_blend(session, sentinel, 10) is None      # tick mode: never
    from dataclasses import replace
    session.settings = replace(session.settings,
                               render=replace(session.settings.render, motion="smooth"))
    assert _motion_blend(session, None, 10) is None          # no snapshot yet
    snap, alpha = _motion_blend(session, sentinel, 10)
    assert snap is sentinel and alpha == pytest.approx(10 / TICK_MS)
    _, alpha = _motion_blend(session, sentinel, TICK_MS * 3)
    assert alpha == 1.0                                      # clamped, never extrapolates
