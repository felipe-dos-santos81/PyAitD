# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.engine.script.effects import AfterLife, FoundResult
from PyAitD.engine.script.interaction.life_cont import execute_found_life, resume_life

INVENTORY_SIZE = 30
MAX_VISIBLE_ACTIONS = 5


def inventory_items(game, inventory_idx=None):
    inv = game.current_inventory if inventory_idx is None else inventory_idx
    return tuple(game.inventory_table[inv][:game.inventory_count[inv]])


def find_in_inventory(game, object_idx):
    try:
        return inventory_items(game).index(object_idx)
    except ValueError:
        return -1


def inventory_weight(game):
    return sum(game.world_objects[i].position_in_track for i in inventory_items(game))


def inventory_actions(game, object_idx):
    from PyAitD.engine.content.objects import action_ids, pickup_at   # content reaches interaction through actor.anim_action: lazy
    if pickup_at(game, object_idx) is not None:
        return action_ids(game, object_idx)   # at most MAX_VISIBLE_ACTIONS, checked at load
    flags = game.world_objects[object_idx].found_flag
    return tuple(23 + bit for bit in range(11) if flags & (1 << bit))[:MAX_VISIBLE_ACTIONS]


def request_found(game, object_idx, parameter):
    from PyAitD.engine.script.effects import ShowFound
    if object_idx < 0:
        return None
    world = game.world_objects[object_idx]
    if parameter != 0 and world.found_flag & 0xC000:
        return None
    if world.track_number and game.timer - world.track_number < 300:
        return None
    world.track_number = 0
    forced = (
        world.position_in_track + inventory_weight(game) > game.cvars[2]
        or game.inventory_count[game.current_inventory] + 1 == INVENTORY_SIZE
    )
    return ShowFound(object_idx, forced)


def remove_from_inventory(game, object_idx):
    inv = game.current_inventory
    slot = find_in_inventory(game, object_idx)
    if slot == -1:
        game.world_objects[object_idx].found_flag &= 0x7FFF
        return False
    count = game.inventory_count[inv]
    table = game.inventory_table[inv]
    table[slot:count - 1] = table[slot + 1:count]
    table[count - 1] = -1
    game.inventory_count[inv] -= 1
    game.world_objects[object_idx].found_flag &= 0x7FFF
    return True


def _finish_take(game, object_idx):
    inv = game.current_inventory
    count = game.inventory_count[inv]
    if count >= INVENTORY_SIZE - 1:
        raise ValueError(f"inventory {inv} is full at {count} objects")
    table = game.inventory_table[inv]
    if count == 0:
        table[0] = object_idx
    else:
        for i in range(count, 0, -1):
            table[i + 1] = table[i]
        table[1] = object_idx
    game.inventory_count[inv] += 1
    world = game.world_objects[object_idx]
    if world.obj_index != -1:
        game.actors[world.obj_index].index_in_world = -1
        world.obj_index = -1
    world.found_flag = (world.found_flag & 0xBFFF) | 0x8000
    world.room = world.stage = -1
    game.flag_genere_aff_list = 1


def begin_take(game, object_idx):
    game.action = 0x800
    return execute_found_life(game, object_idx, after=AfterLife.FINISH_TAKE)


def put_object(game, object_idx, x, y, z, room, stage, alpha, beta, gamma):
    world = game.world_objects[object_idx]
    world.x, world.y, world.z = x, y, z
    world.room, world.stage = room, stage
    world.alpha, world.beta, world.gamma = alpha, beta, gamma
    remove_from_inventory(game, object_idx)
    world.found_flag |= 0x4000
    game.flag_genere_aff_list = 1


def drop_object(game, object_idx, source_idx):
    from PyAitD.engine.script.game import put_at_objet
    put_at_objet(game, object_idx, source_idx)
    game.flag_genere_aff_list = 1


def choose_inventory_action(game, object_idx, action_text_id):
    from PyAitD.engine.content.objects import pickup_at, use   # lazy, as above
    if action_text_id not in inventory_actions(game, object_idx):
        raise ValueError(f"object {object_idx} does not expose inventory action {action_text_id}")
    game.in_hand_table[game.current_inventory] = object_idx
    if pickup_at(game, object_idx) is not None:
        use(game, object_idx, action_text_id)   # a pack verb is a rule, not a LIFE with game.action set
        return True
    game.action = 1 << (action_text_id - 23)
    return execute_found_life(game, object_idx)


def apply_found_result(game, result):
    from PyAitD.engine.script.effects import ShowFound
    effect = game.active_modal
    if not isinstance(effect, ShowFound):
        raise RuntimeError(f"found result applied to {type(effect).__name__}")
    game.close_modal()
    if result is FoundResult.TAKE and not effect.forced_refuse:
        completed = begin_take(game, effect.object_idx)
        if not completed:
            return False
    else:
        game.world_objects[effect.object_idx].track_number = game.timer
    return resume_life(game)


def apply_inventory_result(game, result):
    from PyAitD.engine.script.effects import OpenInventory
    if not isinstance(game.active_modal, OpenInventory):
        raise RuntimeError(f"inventory result applied to {type(game.active_modal).__name__}")
    game.close_modal()
    if not result.cancelled:
        if not choose_inventory_action(game, result.object_idx, result.action_text_id):
            return False
    return resume_life(game)


def apply_reading_result(game, result):
    from PyAitD.engine.script.effects import ReadText, ShowPicture
    if not isinstance(game.active_modal, (ReadText, ShowPicture)):
        raise RuntimeError(f"reading result applied to {type(game.active_modal).__name__}")
    if not result.dismissed:
        return False
    game.close_modal()
    game.flag_init_view = 1
    return resume_life(game)
