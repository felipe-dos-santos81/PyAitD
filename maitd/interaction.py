# SPDX-License-Identifier: GPL-2.0-only
from maitd.effects import AfterLife, LifeFrame
from maitd.life import process_life

INVENTORY_SIZE = 30
MAX_VISIBLE_ACTIONS = 5


def _release_temporary_actor(game, actor_idx):
    if actor_idx != -1:
        game.actors[actor_idx].index_in_world = -1


def _complete_after_life(game, frame):
    _release_temporary_actor(game, frame.release_actor_idx)
    if frame.after is AfterLife.FINISH_TAKE:
        _finish_take(game, frame.subject_idx)


def run_life(game, frame):
    pending = process_life(
        game, frame.owner_idx, frame.life_num, pc=frame.pc, after=frame.after,
        subject_idx=frame.subject_idx, release_actor_idx=frame.release_actor_idx,
    )
    if pending is not None:
        game.life_stack.append(pending)
        return False
    _complete_after_life(game, frame)
    return True


def resume_life(game):
    while game.life_stack and game.active_modal is None:
        frame = game.life_stack.pop()
        if not run_life(game, frame):
            return False
    return game.active_modal is None


def execute_found_life(game, object_idx, *, after=AfterLife.NONE):
    if object_idx == -1:
        return True
    world = game.world_objects[object_idx]
    if world.found_life == -1:
        if after is AfterLife.FINISH_TAKE:
            _finish_take(game, object_idx)
        return True
    release_actor_idx = -1
    actor_idx = world.obj_index
    if actor_idx == -1:
        actor_idx = next(
            (i for i in range(len(game.actors) - 1, -1, -1)
             if game.actors[i].index_in_world == -1),
            len(game.actors) - 1,
        )
        actor = game.actors[actor_idx]
        actor.index_in_world = object_idx
        actor.life = actor.body_num = actor.room = actor.life_mode = actor.anim = -1
        actor.object_type = 0
        actor.track_mode = -1
        release_actor_idx = actor_idx
    return run_life(game, LifeFrame(
        actor_idx, world.found_life, after=after, subject_idx=object_idx,
        release_actor_idx=release_actor_idx,
    ))


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
    flags = game.world_objects[object_idx].found_flag
    return tuple(23 + bit for bit in range(11) if flags & (1 << bit))[:MAX_VISIBLE_ACTIONS]


def request_found(game, object_idx, parameter):
    from maitd.effects import ShowFound
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
    from maitd.game import put_at_objet
    put_at_objet(game, object_idx, source_idx)
    game.flag_genere_aff_list = 1


def choose_inventory_action(game, object_idx, action_text_id):
    if action_text_id not in inventory_actions(game, object_idx):
        raise ValueError(f"object {object_idx} does not expose inventory action {action_text_id}")
    game.in_hand_table[game.current_inventory] = object_idx
    game.action = 1 << (action_text_id - 23)
    return execute_found_life(game, object_idx)
