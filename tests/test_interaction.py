# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.effects import NavIntent, ShowFound
from PyAitD.game import init_game, AF_FOUNDABLE
from PyAitD.interaction import (
    _finish_take, apply_click_intent, cancel_nav_intent, choose_inventory_action,
    dispatch_nav_arrival, inventory_actions, inventory_items, inventory_weight,
    put_object, remove_from_inventory, request_found, resolve_actor_contacts,
)


def test_take_keeps_first_item_at_zero_and_inserts_later_items_at_one(data_dir):
    game = init_game(data_dir)
    for object_idx in (10, 11, 12):
        _finish_take(game, object_idx)
    assert inventory_items(game) == (10, 12, 11)
    assert game.inventory_count[0] == 3
    assert game.world_objects[12].found_flag & 0x8000
    assert not game.world_objects[12].found_flag & 0x4000
    assert (game.world_objects[12].room, game.world_objects[12].stage) == (-1, -1)


def test_remove_and_put_match_found_flags(data_dir):
    game = init_game(data_dir)
    _finish_take(game, 10)
    assert remove_from_inventory(game, 10) is True
    assert not game.world_objects[10].found_flag & 0x8000
    _finish_take(game, 10)
    put_object(game, 10, 1, 2, 3, 4, 5, 6, 7, 8)
    world = game.world_objects[10]
    assert (world.x, world.y, world.z, world.room, world.stage) == (1, 2, 3, 4, 5)
    assert (world.alpha, world.beta, world.gamma) == (6, 7, 8)
    assert world.found_flag & 0x4000
    assert not world.found_flag & 0x8000


def test_weight_and_first_five_found_flag_actions(data_dir):
    game = init_game(data_dir)
    game.world_objects[10].position_in_track = 7
    _finish_take(game, 10)
    game.world_objects[10].found_flag = 0x8000 | sum(1 << bit for bit in (0, 2, 4, 6, 8, 10))
    assert inventory_weight(game) == 7
    assert inventory_actions(game, 10) == (23, 25, 27, 29, 31)


def test_found_request_applies_flags_debounce_weight_and_capacity(data_dir):
    game = init_game(data_dir)
    game.timer = 300
    world = game.world_objects[10]
    world.position_in_track = game.cvars[2] + 1
    assert request_found(game, 10, 1) == ShowFound(10, True)
    world.found_flag = 0x8000
    assert request_found(game, 10, 1) is None
    assert request_found(game, 10, 0) == ShowFound(10, True)
    world.found_flag = 0
    world.track_number = game.timer - 20
    assert request_found(game, 10, 0) is None


def test_inventory_choice_sets_action_and_in_hand_before_found_life(data_dir, monkeypatch):
    game = init_game(data_dir)
    _finish_take(game, 10)
    game.world_objects[10].found_flag |= 1 << 2
    called = []
    monkeypatch.setattr("PyAitD.interaction.execute_found_life", lambda g, i, **kw: called.append(i) or True)
    assert choose_inventory_action(game, 10, 25) is True
    assert game.in_hand_table[0] == 10
    assert game.action == 1 << 2
    assert called == [10]


def _foundable_pair(game):
    hero_idx = game.current_camera_target_actor
    hero = game.actors[hero_idx]
    other_idx = next(
        i for i, a in enumerate(game.actors)
        if a.index_in_world >= 0 and i != hero_idx
    )
    other = game.actors[other_idx]
    other.object_type |= AF_FOUNDABLE
    other.room = hero.room
    other.zv = list(hero.zv)          # overlapping, so contact is guaranteed
    # Initialize world object's debounce counter to allow request_found to proceed
    world = game.world_objects[other.index_in_world]
    world.track_number = 0
    return hero_idx, hero, other_idx


def test_mouse_mode_hero_still_triggers_found_on_contact(data_dir):
    # the gate was `track_mode == 1`; mode 4 is equally player-controlled
    game = init_game(data_dir)
    hero_idx, hero, _other = _foundable_pair(game)
    hero.track_mode = 4
    resolve_actor_contacts(game, hero_idx, list(hero.zv), list(hero.zv), 0, 0)
    assert isinstance(game.active_modal, ShowFound)


def test_tank_mode_hero_still_triggers_found_on_contact(data_dir):
    game = init_game(data_dir)
    hero_idx, hero, _other = _foundable_pair(game)
    hero.track_mode = 1
    resolve_actor_contacts(game, hero_idx, list(hero.zv), list(hero.zv), 0, 0)
    assert isinstance(game.active_modal, ShowFound)


def test_scripted_actor_does_not_trigger_found(data_dir):
    game = init_game(data_dir)
    hero_idx, hero, _other = _foundable_pair(game)
    hero.track_mode = 3          # scripted track: not player-controlled
    resolve_actor_contacts(game, hero_idx, list(hero.zv), list(hero.zv), 0, 0)
    assert game.active_modal is None


def test_apply_click_intent_replaces_any_previous_intent(data_dir):
    game = init_game(data_dir)
    apply_click_intent(game, 100, 200, 0)
    apply_click_intent(game, 300, 400, 0)
    assert (game.nav_intent.dest_x, game.nav_intent.dest_z) == (300, 400)
    assert game.nav_intent.waypoints is None, "a new click re-paths from scratch"


def test_cancel_clears_intent_and_decision(data_dir):
    game = init_game(data_dir)
    apply_click_intent(game, 100, 200, 0)
    game.nav_decision = object()
    cancel_nav_intent(game)
    assert game.nav_intent is None and game.nav_decision is None


def test_arrival_at_a_foundable_target_opens_that_object_s_prompt(data_dir):
    # the accessibility win: the prompt is for the object that was CLICKED,
    # not for whatever ZV the hero happened to overlap on the way
    game = init_game(data_dir)
    # No actor in this floor's initial spawn is naturally AF_FOUNDABLE, so mark
    # one (matching the _foundable_pair idiom above). game.timer = 300 crosses
    # the preserved FoundObjet track_number == -1 post-load debounce quirk.
    game.timer = 300
    target = next(i for i, w in enumerate(game.world_objects) if w.obj_index != -1)
    game.actors[game.world_objects[target].obj_index].object_type |= AF_FOUNDABLE
    game.nav_arrived_target = target
    completed = dispatch_nav_arrival(game)
    assert completed is False, "opening a modal suspends the tick"
    assert isinstance(game.active_modal, ShowFound)
    assert game.active_modal.object_idx == target
    assert game.nav_arrived_target == -1, "arrival is consumed exactly once"


def test_arrival_without_a_target_sets_the_action_bit(data_dir):
    game = init_game(data_dir)
    game.nav_arrived_target = -1
    game.nav_intent = None
    game.nav_arrived_plain = True
    assert dispatch_nav_arrival(game) is True
    assert game.action == 0x2000, "a bare floor arrival presses Action once"


def test_arrival_on_a_despawned_target_is_dropped(data_dir):
    game = init_game(data_dir)
    target = next(i for i, w in enumerate(game.world_objects) if w.obj_index == -1)
    game.nav_arrived_target = target
    assert dispatch_nav_arrival(game) is True
    assert game.active_modal is None
    assert game.nav_arrived_target == -1


def test_no_dispatch_while_a_modal_is_open(data_dir):
    game = init_game(data_dir)
    game.open_modal(ShowFound(object_idx=0, forced_refuse=False))
    game.nav_arrived_target = 5
    assert dispatch_nav_arrival(game) is True
    assert game.active_modal.object_idx == 0, "the open modal is untouched"
