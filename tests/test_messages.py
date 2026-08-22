# SPDX-License-Identifier: GPL-2.0-only
from maitd.effects import AddMessage, BeginTake, LifeFrame
from maitd.game import init_game
from maitd.interaction import advance_messages, drain_immediate_effects


def test_messages_refresh_duplicate_fill_five_slots_and_expire(data_dir):
    game = init_game(data_dir)
    for message_id in range(100, 106):
        game.emit(AddMessage(message_id))
    drain_immediate_effects(game)
    assert [m.message_id for m in game.messages] == [100, 101, 102, 103, 104]
    game.messages[2].age = 40
    game.emit(AddMessage(102))
    drain_immediate_effects(game)
    assert game.messages[2].age == 0
    for _ in range(56):
        advance_messages(game)
    assert game.messages == [None] * 5


def test_begin_take_runs_after_parent_frame_is_stacked(data_dir, monkeypatch):
    game = init_game(data_dir)
    game.life_stack.append(LifeFrame(0, 1, pc=6))
    seen = []
    monkeypatch.setattr("maitd.interaction.begin_take", lambda g, i: seen.append((i, len(g.life_stack))) or False)
    game.emit(BeginTake(12))
    assert drain_immediate_effects(game) is False
    assert seen == [(12, 1)]
