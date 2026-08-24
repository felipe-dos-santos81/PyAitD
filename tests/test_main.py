# SPDX-License-Identifier: GPL-2.0-only
import json
import pathlib
from types import SimpleNamespace

import pytest

from PyAitD.__main__ import parse_args
from PyAitD.effects import ChooseCharacter


def test_parse_args_defaults():
    args = parse_args([])
    assert args.floor is None
    assert args.data is not None
    assert args.combat_venue is False
    assert args.mouse_combat_fixture is False


def test_parse_args_distinguishes_normal_boot_from_explicit_floor_zero():
    assert parse_args([]).floor is None
    assert parse_args(["--floor", "0"]).floor == 0


def test_normal_main_opens_character_selection_before_run(monkeypatch, tmp_path):
    import PyAitD.__main__ as main
    game = SimpleNamespace(active_modal=None, open_modal=lambda effect: setattr(game, "active_modal", effect))
    seen = []
    monkeypatch.setattr(main, "init_game", lambda data: game)
    monkeypatch.setattr(main, "load_runtime_session", lambda path: SimpleNamespace())
    monkeypatch.setattr(main, "run", lambda g, trace, session=None: seen.append((g, session)) or 0)
    assert main.main(["--data", str(tmp_path)]) == 0
    assert isinstance(game.active_modal, ChooseCharacter)
    assert seen and seen[0][0] is game


@pytest.mark.parametrize("args", (["--floor", "0"], ["--combat-venue"], ["--mouse-combat-fixture"]))
def test_explicit_debug_starts_bypass_character_selection(monkeypatch, tmp_path, args):
    import PyAitD.__main__ as main
    game = SimpleNamespace(active_modal=None)
    seen = []
    monkeypatch.setattr(main, "init_game", lambda data: game)
    monkeypatch.setattr(main, "enter_combat_venue", lambda value: None)
    monkeypatch.setattr(main, "enter_mouse_combat_fixture", lambda value: None)
    monkeypatch.setattr(main, "load_runtime_session", lambda path: SimpleNamespace())
    monkeypatch.setattr(
        main, "run",
        lambda value, trace, session=None: seen.append((value, session)) or 0,
    )
    assert main.main([*args, "--data", str(tmp_path)]) == 0
    assert game.active_modal is None
    assert seen and seen[0][0] is game


def test_parse_args_overrides():
    args = parse_args(["--floor", "3", "--data", "/tmp/x"])
    assert args.floor == 3
    assert args.data == pathlib.Path("/tmp/x")


def test_main_rejects_nonzero_floor_without_calling_run(monkeypatch, tmp_path):
    import PyAitD.__main__ as main

    monkeypatch.setattr(main, "init_game", lambda data: SimpleNamespace())
    calls = []
    monkeypatch.setattr(main, "run", lambda *args: calls.append("run"))

    exit_code = main.main(["--floor", "5", "--data", str(tmp_path)])

    assert exit_code == 2
    assert calls == []


def test_main_combat_venue_calls_enter_combat_venue_once_before_run(monkeypatch, tmp_path):
    import PyAitD.__main__ as main

    game = SimpleNamespace()
    calls = []
    monkeypatch.setattr(main, "init_game", lambda data: game)
    monkeypatch.setattr(main, "enter_combat_venue", lambda g: calls.append(("venue", g)))
    monkeypatch.setattr(main, "load_runtime_session", lambda path: SimpleNamespace())
    monkeypatch.setattr(main, "run", lambda g, trace, session=None: calls.append(("run", g)))

    main.main(["--combat-venue", "--data", str(tmp_path)])

    assert calls == [("venue", game), ("run", game)]


def test_parse_args_has_a_separate_mouse_combat_start():
    args = parse_args(["--mouse-combat-fixture"])
    assert args.mouse_combat_fixture is True
    assert args.combat_venue is False


def test_main_mouse_combat_fixture_runs_its_own_setup(monkeypatch, tmp_path):
    import PyAitD.__main__ as main

    game = SimpleNamespace()
    calls = []
    monkeypatch.setattr(main, "init_game", lambda data: game)
    monkeypatch.setattr(
        main, "enter_mouse_combat_fixture",
        lambda g: calls.append(("mouse fixture", g)),
    )
    monkeypatch.setattr(main, "load_runtime_session", lambda path: SimpleNamespace())
    monkeypatch.setattr(main, "run", lambda g, trace, session=None: calls.append(("run", g)) or 0)
    assert main.main([
        "--mouse-combat-fixture", "--data", str(tmp_path),
    ]) == 0
    assert calls == [("mouse fixture", game), ("run", game)]


def test_unknown_pygame_key_falls_back_to_defaults_with_a_path_named_notice(tmp_path):
    # load_runtime_session is a JSON-only boot step: a structurally valid file
    # whose key names pygame does not know must load cleanly, and only the
    # input compilation (which owns the pygame key table) may fall back to
    # defaults -- recording a notice that names the offending file.
    from PyAitD.__main__ import configure_session_input, load_runtime_session
    from PyAitD.config import SCHEMA, default_settings
    from PyAitD.ui import InputBuffer

    bindings = {name: list(keys) for name, keys in default_settings().bindings.items()}
    bindings["UP"] = ["not-a-real-pygame-key"]
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "schema": SCHEMA, "sticky_action": False, "bindings": bindings,
    }), encoding="utf-8")

    session = load_runtime_session(path)
    assert session.settings_error is None
    assert session.settings.bindings["UP"] == ("not-a-real-pygame-key",)

    buffer = InputBuffer()
    configure_session_input(session, buffer)

    assert session.settings == default_settings()
    assert str(path) in session.settings_error
    assert buffer.bindings is not None
