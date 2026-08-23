# SPDX-License-Identifier: GPL-2.0-only
import pathlib
from types import SimpleNamespace

from PyAitD.__main__ import parse_args


def test_parse_args_defaults():
    args = parse_args([])
    assert args.floor == 0
    assert args.data is not None
    assert args.combat_venue is False


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
    monkeypatch.setattr(main, "run", lambda g, trace: calls.append(("run", g)))

    main.main(["--combat-venue", "--data", str(tmp_path)])

    assert calls == [("venue", game), ("run", game)]
