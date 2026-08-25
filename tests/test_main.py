# SPDX-License-Identifier: GPL-2.0-only
import json
import pathlib
import subprocess
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
    assert args.hero == 0


def test_parse_args_distinguishes_normal_boot_from_explicit_floor_zero():
    assert parse_args([]).floor is None
    assert parse_args(["--floor", "0"]).floor == 0


def test_normal_main_opens_character_selection_before_run(monkeypatch, tmp_path):
    import PyAitD.__main__ as main
    game = SimpleNamespace(active_modal=None, open_modal=lambda effect: setattr(game, "active_modal", effect))
    seen = []
    monkeypatch.setattr(main, "init_game", lambda data, hero=0: game)
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
    monkeypatch.setattr(main, "init_game", lambda data, hero=0: game)
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

    monkeypatch.setattr(main, "init_game", lambda data, hero=0: SimpleNamespace())
    calls = []
    monkeypatch.setattr(main, "run", lambda *args: calls.append("run"))

    exit_code = main.main(["--floor", "5", "--data", str(tmp_path)])

    assert exit_code == 2
    assert calls == []


def test_main_combat_venue_calls_enter_combat_venue_once_before_run(monkeypatch, tmp_path):
    import PyAitD.__main__ as main

    game = SimpleNamespace()
    calls = []
    monkeypatch.setattr(main, "init_game", lambda data, hero=0: game)
    monkeypatch.setattr(main, "enter_combat_venue", lambda g: calls.append(("venue", g)))
    monkeypatch.setattr(main, "load_runtime_session", lambda path: SimpleNamespace())
    monkeypatch.setattr(main, "run", lambda g, trace, session=None: calls.append(("run", g)))

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
    import PyAitD.__main__ as main

    game = SimpleNamespace()
    heroes = []
    monkeypatch.setattr(
        main, "init_game",
        lambda data, hero=0: heroes.append(hero) or game,
    )
    monkeypatch.setattr(main, "enter_mouse_combat_fixture", lambda g: None)
    monkeypatch.setattr(main, "load_runtime_session", lambda path: SimpleNamespace())
    monkeypatch.setattr(main, "run", lambda g, trace, session=None: 0)

    assert main.main([
        "--mouse-combat-fixture", "--hero", "1", "--data", str(tmp_path),
    ]) == 0

    assert heroes == [1]


def test_main_mouse_combat_fixture_runs_its_own_setup(monkeypatch, tmp_path):
    import PyAitD.__main__ as main

    game = SimpleNamespace()
    calls = []
    monkeypatch.setattr(main, "init_game", lambda data, hero=0: game)
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
