# SPDX-License-Identifier: GPL-2.0-only
"""engine.content objects: the rule engine unit-stepped on a stub game, and
the key-and-barricade journeys of the example pack against the real attic
(2026-09-04-content-packs-objects-design.md, sections 3 and 5)."""
import copy
import json
from types import SimpleNamespace

import pytest

import PyAitD.engine.content.objects as objects_module
from PyAitD.engine.content.objects import (
    action_ids, holds, pickup_at, run_rules, step_triggers, take, use,
)
from PyAitD.engine.content.schema import Condition, Effect, Rule, parse_object
from PyAitD.engine.content.world import ContentAttachment, allocate_texts, compile_record, initial_state
from PyAitD.engine.content import load_pack
from PyAitD.engine.data.floor import Floor
from PyAitD.engine.script.effects import FoundResult, InputMode, ShowFound
from PyAitD.engine.script.game import init_game, relocate_actor
from PyAitD.engine.script.game.objects import delete_object
from PyAitD.engine.script.interaction import (
    apply_found_result, choose_inventory_action, inventory_actions, inventory_items,
)
from PyAitD.engine.script.playworld import IDLE, PlayInput, play_tick
from PyAitD.engine.script.save import SaveError, restore_game, snapshot_game, validate_snapshot

pytestmark = [pytest.mark.engine, pytest.mark.journey]

SETTINGS = {"schema": 2, "sticky_action": False, "bindings": {}, "render": {}}

KEY = {
    "id": "attic_key", "kind": "pickup", "stage": 0, "room": 0,
    "name": "Attic key", "body": 187, "position": [3231, 0, -2248], "zv": "body", "weight": 1,
    "on_take": [{"then": [{"set_flag": "has_key"}, {"message": "A small brass key."}]}],
    "actions": [{"label": "Look", "then": [{"message": "It is warm to the touch."}]}],
}
BARRICADE = {
    "id": "barricade", "kind": "scenery", "stage": 0, "room": 0,
    "body": 8, "position": [3231, 0, -3400], "zv": "cube",
}
GATE = {
    "id": "gate", "kind": "trigger", "stage": 0, "room": 0,
    "box": {"x": [2800, 3700], "y": [-500, 500], "z": [-3100, -2700]},
    "on_enter": [
        {"when": {"has_item": "attic_key"},
         "then": [{"delete_object": "barricade"}, {"message": "The barricade gives way."},
                  {"delete_object": "gate"}]},
        {"then": [{"message": "Something heavy blocks the doorway."}]},
    ],
}
K, B, G = 0, 1, 2   # world indices in the stub


def _stub(hero=None):
    """A game with just the three scene records attached at world 0..2, a
    message sink instead of the timed-message table, and an optional hero
    actor in slot 0."""
    records = [parse_object(t, "f") for t in (KEY, BARRICADE, GATE)]
    text_ids = allocate_texts(records)
    content = ContentAttachment(
        pack=None, first_index=0, records=dict(enumerate(records)),
        by_id={r.id: i for i, r in enumerate(records)}, text_ids=text_ids, flags=set(),
    )
    game = SimpleNamespace(
        content=content, content_state={i: initial_state(r) for i, r in enumerate(records)},
        world_objects=[compile_record(r, text_ids) for r in records],
        shown=[], trace=None, current_floor=0,
        actors=[hero] if hero is not None else [],
        current_camera_target_actor=0 if hero is not None else -1,
        in_hand_table=[-1, -1], current_inventory=0,
    )
    game.add_message = game.shown.append
    return game


def _hero(x, y, z, room=0):
    return SimpleNamespace(room=room, room_x=x, room_y=y, room_z=z)


def _held(game, idx):
    game.world_objects[idx].found_flag |= 0x8000


def test_holds_checks_flags_and_the_in_inventory_bit():
    game = _stub()
    assert holds(game, Condition())
    assert not holds(game, Condition(flag="has_key"))
    assert holds(game, Condition(not_flag="has_key"))
    game.content.flags.add("has_key")
    assert holds(game, Condition(flag="has_key")) and not holds(game, Condition(not_flag="has_key"))
    assert not holds(game, Condition(has_item="attic_key")) and holds(game, Condition(not_item="attic_key"))
    _held(game, K)
    assert holds(game, Condition(has_item="attic_key")) and not holds(game, Condition(not_item="attic_key"))
    assert not holds(game, Condition(flag="has_key", not_item="attic_key"))   # conjunction


def test_run_rules_fires_the_first_matching_rule_only(monkeypatch):
    deleted = []
    monkeypatch.setattr(objects_module, "delete_object", lambda g, idx: deleted.append(idx))
    game = _stub()
    gate = game.content.records[G]
    assert run_rules(game, gate.on_enter) is True
    assert game.shown == [game.content.text_ids["Something heavy blocks the doorway."]]
    assert deleted == [] and game.content_state[G]["armed"] is True
    _held(game, K)
    assert run_rules(game, gate.on_enter) is True
    assert game.shown[1:] == [game.content.text_ids["The barricade gives way."]]
    assert deleted == [B]                                   # scenery: the vanilla primitive
    assert game.content_state[G]["armed"] is False          # a trigger deletes itself by disarming
    assert run_rules(game, (Rule(Condition(flag="never"), (Effect("message", "x"),)),)) is False
    rules = (Rule(Condition(), (Effect("set_flag", "a"), Effect("clear_flag", "a"), Effect("set_flag", "b"))),)
    run_rules(game, rules)
    assert game.content.flags == {"b"}
    run_rules(game, (Rule(Condition(), (Effect("remove_item", "attic_key"),)),))
    assert deleted == [B, K]


def test_pickup_helpers_take_and_use():
    game = _stub()
    assert pickup_at(game, K).id == "attic_key"
    assert pickup_at(game, B) is None and pickup_at(game, G) is None
    assert pickup_at(SimpleNamespace(content=None), 0) is None
    look = game.content.text_ids["Look"]
    assert action_ids(game, K) == (look,)
    take(game, K)
    assert "has_key" in game.content.flags
    assert game.shown == [game.content.text_ids["A small brass key."]]
    use(game, K, look)
    assert game.shown[1] == game.content.text_ids["It is warm to the touch."]
    with pytest.raises(ValueError, match="object 0 does not expose inventory action 23"):
        use(game, K, 23)


def test_step_triggers_fires_on_the_entry_edge_only():
    hero = _hero(3231, 0, -2000)
    game = _stub(hero)
    blocking = game.content.text_ids["Something heavy blocks the doorway."]
    step_triggers(game)
    assert game.shown == [] and game.content_state[G]["inside"] is False
    hero.room_z = -2900                          # in the box
    step_triggers(game)
    step_triggers(game)                          # standing inside: no second firing
    assert game.shown == [blocking] and game.content_state[G]["inside"] is True
    hero.room_z = -2000
    step_triggers(game)
    assert game.content_state[G]["inside"] is False and game.shown == [blocking]
    hero.room_z = -2900
    step_triggers(game)
    assert game.shown == [blocking, blocking]    # re-entry fires again
    hero.room_z = -2000
    step_triggers(game)
    hero.room = 1                                # another room: outside even inside the box
    hero.room_z = -2900
    step_triggers(game)
    assert game.shown == [blocking, blocking]
    hero.room = 0
    game.current_floor = 1
    step_triggers(game)
    assert game.shown == [blocking, blocking]
    game.current_floor = 0
    game.content_state[G]["armed"] = False
    step_triggers(game)
    assert game.shown == [blocking, blocking] and game.content_state[G]["inside"] is False
    game.current_camera_target_actor = -1
    step_triggers(game)                          # no hero: nothing to test, nothing raised
    assert step_triggers(SimpleNamespace(content=None)) is None


def test_the_box_bounds_are_inclusive():
    hero = _hero(2800, -500, -3100)
    game = _stub(hero)
    step_triggers(game)
    assert game.content_state[G]["inside"] is True
    hero.room_x = 3701
    game.content_state[G]["inside"] = False
    step_triggers(game)
    assert game.content_state[G]["inside"] is False


# ── the example scene against the real attic ─────────────────────────────────

PROWLER, WATCHER, KEY_IDX, BARRICADE_IDX, GATE_IDX = 292, 293, 294, 295, 296
FORWARD = PlayInput(joyd=1)   # keyboard mode: bit 0 walks forward, ~25 units a tick, along -z from the start


def _boot(data_dir, profile, example_pack_dir):
    pack = load_pack(example_pack_dir, data_dir, profile)
    game = init_game(data_dir, profile, pack=pack)
    game.num_camera = game.new_num_camera
    game.input_mode = InputMode.KEYBOARD   # the mouse route walks only toward a nav intent
    delete_object(game, PROWLER)           # the pursuer would reach the hero mid-scene
    delete_object(game, WATCHER)
    floor = Floor(data_dir, 0, profile)
    for _ in range(3):
        play_tick(game, floor, IDLE)       # commits the spawn's pending anims
    return game, floor, game.actors[game.current_camera_target_actor]


def _walk_until(game, floor, predicate, *, limit):
    for tick in range(limit):
        play_tick(game, floor, FORWARD)
        if predicate(game):
            return tick
    return -1


def _shown(game):
    return {m.message_id for m in game.messages if m is not None}


def _reach_the_key(game, floor):
    assert _walk_until(game, floor, lambda g: g.active_modal is not None, limit=60) != -1
    assert isinstance(game.active_modal, ShowFound)
    assert (game.active_modal.object_idx, game.active_modal.forced_refuse) == (KEY_IDX, False)


def test_touching_the_key_prompts_with_its_pack_name_and_taking_it_runs_on_take(data_dir, profile, example_pack_dir):
    game, floor, hero = _boot(data_dir, profile, example_pack_dir)
    texts = game.content.text_ids
    _reach_the_key(game, floor)
    assert game.assets.system_text(game.world_objects[KEY_IDX].found_name) == "Attic key"
    assert apply_found_result(game, FoundResult.TAKE) is True
    assert game.active_modal is None
    assert KEY_IDX in inventory_items(game)
    key = game.world_objects[KEY_IDX]
    assert key.found_flag & 0x8000 and (key.room, key.obj_index) == (-1, -1)
    assert "has_key" in game.content.flags
    assert texts["A small brass key."] in _shown(game)
    assert game.assets.system_text(texts["A small brass key."]) == "A small brass key."


def test_the_inventory_lists_the_pack_action_and_choosing_it_runs_its_rule(data_dir, profile, example_pack_dir):
    game, floor, hero = _boot(data_dir, profile, example_pack_dir)
    texts = game.content.text_ids
    _reach_the_key(game, floor)
    apply_found_result(game, FoundResult.TAKE)
    look = texts["Look"]
    assert inventory_actions(game, KEY_IDX) == (look,)
    assert choose_inventory_action(game, KEY_IDX, look) is True
    assert texts["It is warm to the touch."] in _shown(game)
    assert game.in_hand_table[game.current_inventory] == KEY_IDX
    with pytest.raises(ValueError, match="does not expose inventory action 23"):
        choose_inventory_action(game, KEY_IDX, 23)
    before = _shown(game)
    play_tick(game, floor, IDLE)   # the in-hand item's per-tick found-life is a no-op for a pack pickup
    assert _shown(game) == before and game.active_modal is None


def test_leaving_the_key_arms_the_vanilla_cooldown(data_dir, profile, example_pack_dir):
    game, floor, hero = _boot(data_dir, profile, example_pack_dir)
    _reach_the_key(game, floor)
    assert apply_found_result(game, FoundResult.LEAVE) is True
    assert game.world_objects[KEY_IDX].track_number == game.timer
    assert _walk_until(game, floor, lambda g: g.active_modal is not None, limit=20) == -1
    assert KEY_IDX not in inventory_items(game) and "has_key" not in game.content.flags


def test_without_the_key_the_gate_explains_and_the_barricade_stands(data_dir, profile, example_pack_dir):
    game, floor, hero = _boot(data_dir, profile, example_pack_dir)
    texts = game.content.text_ids
    _reach_the_key(game, floor)
    apply_found_result(game, FoundResult.LEAVE)
    entered = _walk_until(game, floor, lambda g: g.content_state[GATE_IDX]["inside"], limit=60)
    assert entered != -1
    assert -3100 <= hero.room_z <= -2700
    assert texts["Something heavy blocks the doorway."] in _shown(game)
    assert texts["The barricade gives way."] not in _shown(game)
    assert game.content_state[GATE_IDX]["armed"] is True
    assert game.world_objects[BARRICADE_IDX].room == 0
    barricade_slot = game.world_objects[BARRICADE_IDX].obj_index
    blocked = _walk_until(game, floor, lambda g: barricade_slot in hero.col, limit=60)
    assert blocked != -1, "the hero never met the barricade"
    assert hero.room_z > -3200                    # the crate's near face is at -3160
    assert game.active_modal is None


def test_with_the_key_the_gate_clears_the_barricade_and_disarms_itself(data_dir, profile, example_pack_dir):
    game, floor, hero = _boot(data_dir, profile, example_pack_dir)
    texts = game.content.text_ids
    _reach_the_key(game, floor)
    apply_found_result(game, FoundResult.TAKE)
    entered = _walk_until(game, floor, lambda g: g.content_state[GATE_IDX]["inside"], limit=60)
    assert entered != -1
    assert texts["The barricade gives way."] in _shown(game)
    assert texts["Something heavy blocks the doorway."] not in _shown(game)
    barricade = game.world_objects[BARRICADE_IDX]
    assert (barricade.room, barricade.stage, barricade.obj_index) == (-1, -1, -1)
    assert game.content_state[GATE_IDX] == {"armed": False, "inside": True}
    passed = _walk_until(game, floor, lambda g: hero.room_z < -3600, limit=80)
    assert passed != -1, "the way past the barricade did not open"
    assert hero.col == [-1, -1, -1]


def test_a_trigger_in_the_loop_fires_on_entry_only_and_again_after_leaving(data_dir, profile, example_pack_dir):
    game, floor, hero = _boot(data_dir, profile, example_pack_dir)
    hero_idx = game.current_camera_target_actor
    blocking = game.content.text_ids["Something heavy blocks the doorway."]

    def age():
        return next(m.age for m in game.messages if m is not None and m.message_id == blocking)

    relocate_actor(game, hero_idx, 0, 0, 3231, 0, -2900)
    play_tick(game, floor, IDLE)
    fresh = age()                                 # 0 or 1: advance_messages runs later in the same tick
    assert fresh <= 1 and game.content_state[GATE_IDX]["inside"] is True
    for _ in range(10):
        play_tick(game, floor, IDLE)
    assert age() == fresh + 10                    # standing inside never re-fires
    relocate_actor(game, hero_idx, 0, 0, 3231, 0, -2000)
    play_tick(game, floor, IDLE)
    assert game.content_state[GATE_IDX]["inside"] is False and age() == fresh + 11
    relocate_actor(game, hero_idx, 0, 0, 3231, 0, -2900)
    play_tick(game, floor, IDLE)
    assert age() == fresh                         # re-entry refreshes the message: fired again


def test_the_trace_records_trigger_transitions(data_dir, profile, example_pack_dir, tmp_path):
    from PyAitD.engine.script.life import Trace
    game, floor, hero = _boot(data_dir, profile, example_pack_dir)
    hero_idx = game.current_camera_target_actor
    game.trace = Trace(tmp_path / "t.log")
    relocate_actor(game, hero_idx, 0, 0, 3231, 0, -2900)
    play_tick(game, floor, IDLE)
    entered = game.timer
    relocate_actor(game, hero_idx, 0, 0, 3231, 0, -2000)
    play_tick(game, floor, IDLE)
    game.trace.close()
    lines = (tmp_path / "t.log").read_text().splitlines()
    assert f"{entered} {GATE_IDX} BEHAVIOUR enter" in lines
    assert f"{game.timer} {GATE_IDX} BEHAVIOUR leave" in lines


def test_a_mid_scene_save_round_trips_flags_trigger_state_and_the_inventory(data_dir, profile, example_pack_dir):
    game, floor, hero = _boot(data_dir, profile, example_pack_dir)
    _reach_the_key(game, floor)
    apply_found_result(game, FoundResult.TAKE)
    assert _walk_until(game, floor, lambda g: g.content_state[GATE_IDX]["inside"], limit=60) != -1
    payload = json.loads(json.dumps(snapshot_game(game, SETTINGS)))
    assert payload["schema"] == 4
    assert payload["content_flags"] == ["has_key"]
    assert payload["content_state"]["296"] == {"armed": False, "inside": True}
    restored, _ = restore_game(data_dir, profile, payload, pack=game.pack)
    assert restored.content.flags == {"has_key"}
    assert restored.content_state == game.content_state
    assert KEY_IDX in inventory_items(restored)
    assert restored.world_objects[BARRICADE_IDX].room == -1
    assert restored.assets.system_text(restored.world_objects[KEY_IDX].found_name) == "Attic key"
    assert {m.message_id for m in restored.messages if m} == _shown(game)
    old = copy.deepcopy(payload)
    old["schema"] = 3
    with pytest.raises(SaveError, match="expected schema 4, got 3"):
        validate_snapshot(old, data_dir, profile, pack=game.pack)
