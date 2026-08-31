# SPDX-License-Identifier: GPL-2.0-only
import pytest

from PyAitD.engine.actors import check_object_col
from PyAitD.engine import interaction
from PyAitD.engine.effects import NavIntent, ShowFound
from PyAitD.engine.data.floor import Floor
from PyAitD.engine.game import AF_ANIMATED, init_game, AF_FOUNDABLE
from PyAitD.engine.interaction import (
    COMBAT_ACTIONS, _finish_take, apply_click_intent, attack_in_hand,
    cancel_nav_intent, choose_inventory_action, combat_action_for,
    dispatch_nav_arrival, inventory_actions, inventory_items, inventory_weight,
    hold_action_approach, is_combat_target, is_hold_action_target, put_object,
    PLAYER_STAND_ANIM, remove_from_inventory, request_found,
    resolve_actor_contacts,
)
from PyAitD.engine.world import room_delta

pytestmark = pytest.mark.engine


def _armed_attack_fixture(game):
    # Floor 0 has a single room; the cross-room branch below targets room 7,
    # so use floor 1 (8 rooms in the real ETAGE data) for room_delta to resolve.
    game.current_floor = 1
    hero_idx = game.current_camera_target_actor
    hero = game.actors[hero_idx]
    target_idx = next(
        i for i, actor in enumerate(game.actors)
        if actor.index_in_world >= 0 and i != hero_idx
    )
    target = game.actors[target_idx]
    target.object_type |= AF_ANIMATED
    _finish_take(game, 38)
    game.in_hand_table[game.current_inventory] = 38
    return hero, target_idx, target


def test_attack_stops_faces_without_selecting_throw(data_dir, profile, monkeypatch):
    # ENGLISH.PAK text 32 is "Throw": routing a target click through the
    # inventory action would launch the saber at the floor. FITD's own melee
    # comes from held action input (mainLoop.cpp:87-101), so attack_in_hand
    # only validates, stops and faces; publication is the tick's job.
    game = init_game(data_dir, profile)
    hero, target_idx, target = _armed_attack_fixture(game)
    hero.room, hero.room_x, hero.room_z = 0, 400, -200
    target.room, target.room_x, target.room_z = 7, 300, 500
    hero.speed = 4
    game.nav_intent = NavIntent(100, 200, hero.room)
    game.nav_decision = object()
    faced = []
    monkeypatch.setattr(
        "PyAitD.engine.tracks.face_toward",
        lambda actor, x, z: faced.append((actor, x, z)),
    )
    monkeypatch.setattr(
        "PyAitD.engine.interaction.choose_inventory_action",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("a target click must not choose an inventory action"),
        ),
    )

    assert attack_in_hand(game, target_idx) is True

    dx, _dy, dz = room_delta(game, hero.room, target.room)
    assert faced == [(hero, target.room_x + dx, target.room_z - dz)]
    assert hero.speed == 0
    assert game.nav_intent is None and game.nav_decision is None
    assert game.world_objects[38].obj_index == -1, "the saber must stay in hand"


def test_a_busy_hero_keeps_a_combat_action_offer_for_the_running_strike(data_dir, profile):
    # The tick seam re-validates the latch while the melee animation runs, so
    # the offer lookup must survive a non-idle hero; only the click that starts
    # an attack requires idleness.
    game = init_game(data_dir, profile)
    hero, _target_idx, _target = _armed_attack_fixture(game)
    assert combat_action_for(game, 38) == 32
    hero.anim_action_type = 1
    assert combat_action_for(game, 38) is None
    assert combat_action_for(game, 38, require_idle=False) == 32


def test_invalid_attack_is_a_mutation_free_no_op(data_dir, profile, monkeypatch):
    game = init_game(data_dir, profile)
    hero, target_idx, _target = _armed_attack_fixture(game)
    game.in_hand_table[game.current_inventory] = -1
    hero.speed = 4
    game.nav_intent = NavIntent(100, 200, hero.room)
    before = (hero.beta, hero.speed, game.nav_intent, game.nav_decision)
    monkeypatch.setattr(
        "PyAitD.engine.interaction.choose_inventory_action",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not delegate")),
    )
    assert attack_in_hand(game, target_idx) is False
    assert (hero.beta, hero.speed, game.nav_intent, game.nav_decision) == before


def test_combat_target_is_a_live_animated_non_hero(data_dir, profile):
    game = init_game(data_dir, profile)
    hero_idx = game.current_camera_target_actor
    target_idx = next(
        i for i, actor in enumerate(game.actors)
        if actor.index_in_world >= 0 and i != hero_idx
    )
    target = game.actors[target_idx]
    target.object_type |= AF_ANIMATED
    assert is_combat_target(game, target_idx)
    assert not is_combat_target(game, hero_idx)
    target.index_in_world = -1
    assert not is_combat_target(game, target_idx)


def test_real_wardrobe_is_a_hold_action_target_but_inert_scenery_is_not(data_dir, profile):
    game = init_game(data_dir, profile)
    wardrobe_idx = game.world_objects[4].obj_index
    inert_idx = game.world_objects[8].obj_index
    assert is_hold_action_target(game, wardrobe_idx) is True
    assert is_hold_action_target(game, inert_idx) is False


def test_hold_action_target_rejects_an_out_of_range_world_backlink(data_dir, profile):
    game = init_game(data_dir, profile)
    wardrobe_idx = game.world_objects[4].obj_index
    game.actors[wardrobe_idx].index_in_world = len(game.world_objects)

    assert is_hold_action_target(game, wardrobe_idx) is False


def test_hold_action_approach_is_outside_the_wardrobe_footprint(data_dir, profile):
    game = init_game(data_dir, profile)
    floor = Floor(data_dir, game.current_floor, profile)
    hero_idx = game.current_camera_target_actor
    wardrobe_idx = game.world_objects[4].obj_index
    result = hold_action_approach(game, floor, hero_idx, wardrobe_idx)
    assert result is not None
    x, z, room, world_idx = result
    wardrobe = game.actors[wardrobe_idx]
    assert (room, world_idx) == (wardrobe.room, 4)
    assert (x, z) != (wardrobe.room_x, wardrobe.room_z)


def test_combat_action_requires_an_idle_held_inventory_object(data_dir, profile):
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    _finish_take(game, 38)
    assert COMBAT_ACTIONS == frozenset({32})
    assert combat_action_for(game, 38) == 32
    hero.anim_action_type = 6
    assert combat_action_for(game, 38) is None
    hero.anim_action_type = 0
    remove_from_inventory(game, 38)
    assert combat_action_for(game, 38) is None
    assert combat_action_for(game, -1) is None


def test_take_keeps_first_item_at_zero_and_inserts_later_items_at_one(data_dir, profile):
    game = init_game(data_dir, profile)
    for object_idx in (10, 11, 12):
        _finish_take(game, object_idx)
    assert inventory_items(game) == (10, 12, 11)
    assert game.inventory_count[0] == 3
    assert game.world_objects[12].found_flag & 0x8000
    assert not game.world_objects[12].found_flag & 0x4000
    assert (game.world_objects[12].room, game.world_objects[12].stage) == (-1, -1)


def test_remove_and_put_match_found_flags(data_dir, profile):
    game = init_game(data_dir, profile)
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


def test_weight_and_first_five_found_flag_actions(data_dir, profile):
    game = init_game(data_dir, profile)
    game.world_objects[10].position_in_track = 7
    _finish_take(game, 10)
    game.world_objects[10].found_flag = 0x8000 | sum(1 << bit for bit in (0, 2, 4, 6, 8, 10))
    assert inventory_weight(game) == 7
    assert inventory_actions(game, 10) == (23, 25, 27, 29, 31)


def test_found_request_applies_flags_debounce_weight_and_capacity(data_dir, profile):
    game = init_game(data_dir, profile)
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


def test_inventory_choice_sets_action_and_in_hand_before_found_life(data_dir, profile, monkeypatch):
    game = init_game(data_dir, profile)
    _finish_take(game, 10)
    game.world_objects[10].found_flag |= 1 << 2
    called = []
    monkeypatch.setattr("PyAitD.engine.interaction.execute_found_life", lambda g, i, **kw: called.append(i) or True)
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
    # Cross the preserved FoundObjet track_number == -1 post-load debounce by
    # advancing the clock, not by rewriting the object's data — same idiom as
    # test_arrival_at_a_foundable_target_opens_that_object_s_prompt below.
    game.timer = 300
    return hero_idx, hero, other_idx


def test_mouse_mode_hero_still_triggers_found_on_contact(data_dir, profile):
    # the gate was `track_mode == 1`; mode 4 is equally player-controlled
    game = init_game(data_dir, profile)
    hero_idx, hero, _other = _foundable_pair(game)
    hero.track_mode = 4
    resolve_actor_contacts(game, hero_idx, list(hero.zv), list(hero.zv), 0, 0)
    assert isinstance(game.active_modal, ShowFound)


def test_tank_mode_hero_still_triggers_found_on_contact(data_dir, profile):
    game = init_game(data_dir, profile)
    hero_idx, hero, _other = _foundable_pair(game)
    hero.track_mode = 1
    resolve_actor_contacts(game, hero_idx, list(hero.zv), list(hero.zv), 0, 0)
    assert isinstance(game.active_modal, ShowFound)


def test_scripted_actor_does_not_trigger_found(data_dir, profile):
    game = init_game(data_dir, profile)
    hero_idx, hero, _other = _foundable_pair(game)
    hero.track_mode = 3          # scripted track: not player-controlled
    resolve_actor_contacts(game, hero_idx, list(hero.zv), list(hero.zv), 0, 0)
    assert game.active_modal is None


def test_apply_click_intent_replaces_any_previous_intent(data_dir, profile):
    game = init_game(data_dir, profile)
    apply_click_intent(game, 100, 200, 0)
    apply_click_intent(game, 300, 400, 0)
    assert (game.nav_intent.dest_x, game.nav_intent.dest_z) == (300, 400)
    assert game.nav_intent.waypoints is None, "a new click re-paths from scratch"


def test_cancel_clears_intent_and_decision(data_dir, profile):
    game = init_game(data_dir, profile)
    apply_click_intent(game, 100, 200, 0)
    game.nav_decision = object()
    cancel_nav_intent(game)
    assert game.nav_intent is None and game.nav_decision is None


def test_cancel_held_intent_stops_and_rearms_stand_idempotently(data_dir, profile):
    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    apply_click_intent(game, 100, 200, hero.room, 4, requires_hold=True)
    game.nav_arrived_target = 4
    game.local_joyd = 1
    game.local_click = 1
    game.action = 0x2000
    hero.speed = 4
    hero.direction = 1
    assert interaction.cancel_held_nav_intent(game) is True
    assert (game.nav_intent, game.nav_decision) == (None, None)
    assert (game.nav_arrived_target, game.local_joyd, game.local_click, game.action) == (-1, 0, 0, 0)
    assert (hero.speed, hero.direction, hero.rotate.num_steps) == (0, 0, 0)
    assert hero.new_anim == PLAYER_STAND_ANIM
    assert interaction.cancel_held_nav_intent(game) is False


@pytest.mark.parametrize(
    "protected_request", ("current", "pending"),
    ids=("current-uninterruptible", "pending-uninterruptible"),
)
def test_cancel_held_intent_forces_one_coherent_stand_request(
        data_dir, profile, protected_request,
):
    from PyAitD.engine.anim import ANIM_REPEAT, ANIM_UNINTERRUPTABLE

    game = init_game(data_dir, profile)
    hero = game.actors[game.current_camera_target_actor]
    hero.anim = 5
    hero.anim_type = ANIM_REPEAT
    hero.new_anim = 99
    hero.new_anim_type = ANIM_REPEAT
    hero.new_anim_info = 77
    if protected_request == "current":
        hero.anim_type = ANIM_UNINTERRUPTABLE
    else:
        hero.new_anim_type = ANIM_UNINTERRUPTABLE
    apply_click_intent(game, 100, 200, hero.room, 4, requires_hold=True)

    assert interaction.cancel_held_nav_intent(game) is True
    assert (hero.new_anim, hero.new_anim_type, hero.new_anim_info) == (
        PLAYER_STAND_ANIM, 0, PLAYER_STAND_ANIM,
    )


def test_arrival_at_a_foundable_target_opens_that_object_s_prompt(data_dir, profile):
    # the accessibility win: the prompt is for the object that was CLICKED,
    # not for whatever ZV the hero happened to overlap on the way
    game = init_game(data_dir, profile)
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


def test_arrival_dispatches_the_clicked_target_not_a_proximity_neighbor(data_dir, profile):
    # Regression for the accessibility win itself: with a SINGLE foundable
    # candidate (the test above), dispatch would pass identically whether it
    # used the clicked index or fell back to whatever the hero's box happens
    # to touch. Here two foundable objects both overlap the hero's zv, so
    # both are plausible proximity candidates, and we deliberately click the
    # one a proximity/collision scan would NOT pick first.
    game = init_game(data_dir, profile)
    game.timer = 300  # cross the FoundObjet track_number == -1 debounce
    hero_idx = game.current_camera_target_actor
    hero = game.actors[hero_idx]
    candidates = [
        i for i, w in enumerate(game.world_objects)
        if w.obj_index != -1 and w.obj_index != hero_idx
    ][:2]
    assert len(candidates) == 2, "fixture data needs two other spawned objects"
    for world_idx in candidates:
        actor = game.actors[game.world_objects[world_idx].obj_index]
        actor.object_type |= AF_FOUNDABLE  # matches the _foundable_pair idiom
        actor.room = hero.room
        actor.zv = list(hero.zv)  # identical box: both fully overlap the hero

    # This mirrors how resolve_actor_contacts finds a touched object: walk
    # actors in ascending index order via check_object_col and take the
    # first match. That is what a naive proximity/collision-based dispatch
    # would pick -- and it is deliberately NOT the object we "click" below.
    candidate_actor_idxs = {game.world_objects[w].obj_index for w in candidates}
    touched = check_object_col(game, hero_idx, hero.zv)
    naive_pick_actor_idx = next(a for a in touched if a in candidate_actor_idxs)
    naive_pick_world_idx = next(
        w for w in candidates
        if game.world_objects[w].obj_index == naive_pick_actor_idx
    )
    clicked_world_idx = next(w for w in candidates if w != naive_pick_world_idx)

    game.nav_arrived_target = clicked_world_idx
    completed = dispatch_nav_arrival(game)

    assert completed is False, "opening a modal suspends the tick"
    assert isinstance(game.active_modal, ShowFound)
    assert game.active_modal.object_idx == clicked_world_idx, (
        "the prompt must be for the CLICKED object"
    )
    assert game.active_modal.object_idx != naive_pick_world_idx, (
        "a proximity/collision scan would have picked the other object -- "
        "if this fails, dispatch regressed to proximity"
    )


def test_a_bare_floor_arrival_does_not_press_the_action_bit(data_dir, profile):
    # The action bit is global: scripts poll it through evalVar 0x11, and the
    # keyboard presses it only when the player presses Space. Pressing it at the
    # end of every walk fires unrequested actions everywhere the player goes.
    # Only a clicked, non-foundable target dispatches Action.
    game = init_game(data_dir, profile)
    game.nav_arrived_target = -1
    game.nav_intent = None
    game.action = 0
    assert dispatch_nav_arrival(game) is True
    assert game.action == 0, "walking somewhere is not pressing the action button"


def test_arrival_at_a_clicked_non_foundable_target_presses_the_action_bit(data_dir, profile):
    # the other half of the rule: a clicked target that cannot be picked up
    # gets Action, which is how a mouse-only player operates doors and levers
    game = init_game(data_dir, profile)
    target = next(
        i for i, w in enumerate(game.world_objects)
        if w.obj_index != -1 and not game.actors[w.obj_index].object_type & AF_FOUNDABLE
    )
    game.action = 0
    game.nav_arrived_target = target
    assert dispatch_nav_arrival(game) is True
    assert game.action == 0x2000


def test_arrival_on_a_despawned_target_is_dropped(data_dir, profile):
    game = init_game(data_dir, profile)
    target = next(i for i, w in enumerate(game.world_objects) if w.obj_index == -1)
    game.nav_arrived_target = target
    assert dispatch_nav_arrival(game) is True
    assert game.active_modal is None
    assert game.nav_arrived_target == -1


def test_no_dispatch_while_a_modal_is_open(data_dir, profile):
    game = init_game(data_dir, profile)
    game.open_modal(ShowFound(object_idx=0, forced_refuse=False))
    game.nav_arrived_target = 5
    assert dispatch_nav_arrival(game) is True
    assert game.active_modal.object_idx == 0, "the open modal is untouched"
