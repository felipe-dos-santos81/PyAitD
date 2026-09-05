# SPDX-License-Identifier: GPL-2.0-only
"""The object vocabulary at run time: conditions, rules and effects for
pickups and triggers (spec section 3). Reads world records and the pack's
flags only; the one primitive it calls is delete_object, as LM_DELETE does.
`run_rules` and `step_triggers` never raise on game state; the pickup
helpers (`action_ids`, `take`, `use`) expect a pack pickup index and
dereference `pickup_at(...)` without a None guard -- their call sites in
the interaction layer guard with `pickup_at` first."""
from PyAitD.engine.content.schema import TriggerRecord
from PyAitD.engine.script.game.objects import delete_object

IN_INVENTORY = 0x8000   # WorldObject.found_flag bit _finish_take sets and remove_from_inventory clears


def _in_inventory(game, pack_id):
    return bool(game.world_objects[game.content.by_id[pack_id]].found_flag & IN_INVENTORY)


def holds(game, condition):
    """Whether a rule's `when` holds: every named part, conjunctively."""
    flags = game.content.flags
    if condition.flag is not None and condition.flag not in flags:
        return False
    if condition.not_flag is not None and condition.not_flag in flags:
        return False
    if condition.has_item is not None and not _in_inventory(game, condition.has_item):
        return False
    if condition.not_item is not None and _in_inventory(game, condition.not_item):
        return False
    return True


def _apply(game, effect):
    content = game.content
    if effect.op == "message":
        game.add_message(content.text_ids[effect.arg])
    elif effect.op == "set_flag":
        content.flags.add(effect.arg)
    elif effect.op == "clear_flag":
        content.flags.discard(effect.arg)
    else:   # remove_item, delete_object
        idx = content.by_id[effect.arg]
        if isinstance(content.records[idx], TriggerRecord):
            game.content_state[idx]["armed"] = False   # a trigger has no actor to delete
        else:
            delete_object(game, idx)                   # un-places, releases the actor, leaves the inventory


def run_rules(game, rules):
    """Apply the first rule whose condition holds; True if one fired."""
    for rule in rules:
        if holds(game, rule.when):
            for effect in rule.then:
                _apply(game, effect)
            return True
    return False


def pickup_at(game, world_idx):
    """The PickupRecord behind a world index, or None for anything else
    (vanilla objects, other pack kinds, no pack)."""
    content = game.content
    if content is None:
        return None
    record = content.record_for(world_idx)
    return record if record is not None and record.kind == "pickup" else None


def action_ids(game, world_idx):
    """The pickup's inventory verbs as text ids, in pack order."""
    return tuple(game.content.text_ids[action.label] for action in pickup_at(game, world_idx).actions)


def take(game, world_idx):
    """Run on_take; the caller has already finished the vanilla take, so
    has_item conditions see the item."""
    run_rules(game, pickup_at(game, world_idx).on_take)


def use(game, world_idx, text_id):
    """Run the action whose label carries `text_id`."""
    for action in pickup_at(game, world_idx).actions:
        if game.content.text_ids[action.label] == text_id:
            run_rules(game, (action.rule,))
            return
    raise ValueError(f"object {world_idx} does not expose inventory action {text_id}")


def _hero_inside(game, hero, record):
    if game.current_floor != record.stage or hero.room != record.room:
        return False
    x0, x1, y0, y1, z0, z1 = record.box
    return x0 <= hero.room_x <= x1 and y0 <= hero.room_y <= y1 and z0 <= hero.room_z <= z1


def step_triggers(game):
    """Once per tick: every armed trigger fires on_enter on the edge from
    outside to inside, tracked in content_state[idx]["inside"]."""
    content = game.content
    if content is None:
        return
    hero_idx = game.current_camera_target_actor
    hero = None if hero_idx == -1 else game.actors[hero_idx]
    for idx, record in content.records.items():
        if not isinstance(record, TriggerRecord):
            continue
        state = game.content_state[idx]
        if not state["armed"]:
            continue
        inside = hero is not None and _hero_inside(game, hero, record)
        if inside == state["inside"]:
            continue
        state["inside"] = inside
        if game.trace is not None:
            game.trace.log_behaviour(game, idx, "enter" if inside else "leave")
        if inside:
            run_rules(game, record.on_enter)
