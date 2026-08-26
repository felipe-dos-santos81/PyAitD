# SPDX-License-Identifier: GPL-2.0-only
from PyAitD.engine.effects import (
    AddMessage, AfterLife, BeginTake, FoundResult, InputMode, LifeFrame, TimedMessage,
)
from PyAitD.engine.life import process_life
from PyAitD.engine.world import adjust_zv_between_rooms, room_delta, shifted_zv

INVENTORY_SIZE = 30
MAX_VISIBLE_ACTIONS = 5
# Inventory action text ids that arm combat (32 == "Fight" bit 9 of found_flag).
COMBAT_ACTIONS = frozenset({32})
PLAYER_STAND_ANIM = 4
PLAYER_PUSH_ANIM = 5
# FITD gates found-contact on trackMode == 1, meaning "manually controlled".
# Mode 4 (mouse follower) is equally player-controlled, so it belongs here too.
PLAYER_TRACK_MODES = (1, 4)


def player_track_mode(input_mode):
    """The track mode that means 'the player drives this actor', per input mode."""
    return 4 if input_mode is InputMode.MOUSE else 1


def sync_player_track_mode(game):
    """Keep the hero's manual-control mode in step with the input mode.

    Mouse mode is useless unless the hero is actually in mode 4: mode 1 would
    consume the follower's mirrored joyd as if it were the keyboard, which is
    the autopilot-driving-a-tank approach the spec rejected. Object data spawns
    the hero in mode 1 (game.spawn_stage_actors -> tracks.init_deplacement), so
    init_game and every input snapshot re-assert this.

    The translation is deliberately conditional, 1 <-> 4 only: a script that
    parks the hero on a scripted track (mode 2/3) or freezes it (mode 0) keeps
    what it asked for, so cutscenes are unaffected. It is re-asserted rather
    than set once because LM_INIT_DEPLACEMENT can put the hero back in mode 1
    at any time, and a one-shot at init would silently lose the mouse there.
    """
    hero_idx = game.current_camera_target_actor
    if hero_idx == -1:
        return
    hero = game.actors[hero_idx]
    wanted = player_track_mode(game.input_mode)
    if hero.track_mode in PLAYER_TRACK_MODES and hero.track_mode != wanted:
        hero.track_mode = wanted


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


def _add_message(game, message_id):
    for message in game.messages:
        if message is not None and message.message_id == message_id:
            message.age = 0
            return
    for slot, message in enumerate(game.messages):
        if message is None:
            game.messages[slot] = TimedMessage(message_id)
            return


def drain_immediate_effects(game):
    completed = True
    while game.immediate_effects:
        effect = game.immediate_effects.popleft()
        if isinstance(effect, AddMessage):
            _add_message(game, effect.message_id)
        elif isinstance(effect, BeginTake):
            completed = begin_take(game, effect.object_idx)
            if completed and game.active_modal is None:
                completed = resume_life(game)
            if not completed:
                break
        else:
            raise RuntimeError(f"unknown immediate effect {type(effect).__name__}")
    return completed


def advance_messages(game):
    for slot, message in enumerate(game.messages):
        if message is None:
            continue
        message.age += 1
        if message.age > 55:
            game.messages[slot] = None


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


def is_combat_target(game, actor_idx):
    from PyAitD.engine.game import AF_ANIMATED
    if actor_idx < 0 or actor_idx >= len(game.actors):
        return False
    if actor_idx == game.current_camera_target_actor:
        return False
    actor = game.actors[actor_idx]
    return actor.index_in_world >= 0 and bool(actor.object_type & AF_ANIMATED)


def is_hold_action_target(game, actor_idx):
    from PyAitD.engine.game import AF_FOUNDABLE, AF_MOVABLE
    if actor_idx < 0 or actor_idx >= len(game.actors):
        return False
    if actor_idx == game.current_camera_target_actor:
        return False
    actor = game.actors[actor_idx]
    if (not 0 <= actor.index_in_world < len(game.world_objects)
            or actor.body_num == -1 or not (actor.dyn_flags & 1)):
        return False
    world = game.world_objects[actor.index_in_world]
    if world.obj_index != actor_idx or world.stage != game.current_floor:
        return False
    if actor.object_type & AF_FOUNDABLE:
        return False
    return bool(actor.object_type & AF_MOVABLE) or actor.life != -1


def hold_action_approach(game, floor, hero_idx, target_idx):
    from PyAitD.engine.navmesh import agent_extent, nearest_walkable

    if not is_hold_action_target(game, target_idx):
        return None
    hero = game.actors[hero_idx]
    target = game.actors[target_idx]
    if hero.room != target.room:
        return None
    mesh = game.nav_meshes.mesh_for(floor, target.room, agent_extent(hero))
    if mesh is None:
        return None
    half = agent_extent(hero)[0]
    clearance = half + mesh.step
    x0, x1, _y0, _y1, z0, z1 = target.zv
    from_x = hero.room_x + hero.step_x
    from_z = hero.room_z + hero.step_z
    clamp = lambda value, low, high: max(low, min(value, high))
    candidates = (
        (x0 - clearance, clamp(from_z, z0, z1)),
        (x1 + clearance, clamp(from_z, z0, z1)),
        (clamp(from_x, x0, x1), z0 - clearance),
        (clamp(from_x, x0, x1), z1 + clearance),
    )
    walkable = []
    for x, z in candidates:
        spot = nearest_walkable(mesh, x, z)
        if spot is not None:
            walkable.append(spot)
    if not walkable:
        return None
    x, z = min(
        walkable,
        key=lambda point: abs(point[0] - from_x) + abs(point[1] - from_z),
    )
    return (x, z, target.room, target.index_in_world)


def combat_action_for(game, object_idx, *, require_idle=True):
    """The combat action the in-hand object offers, or None.

    `require_idle` is the difference between starting a strike and keeping one
    alive: a click may only start combat from an idle hero, but the tick seam
    re-validates the same weapon while the melee animation is still running.
    """
    if object_idx not in inventory_items(game):
        return None
    hero_idx = game.current_camera_target_actor
    if hero_idx == -1:
        return None
    if require_idle and game.actors[hero_idx].anim_action_type != 0:
        return None
    return next(
        (action for action in inventory_actions(game, object_idx)
         if action in COMBAT_ACTIONS),
        None,
    )


def request_found(game, object_idx, parameter):
    from PyAitD.engine.effects import ShowFound
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
    from PyAitD.engine.game import put_at_objet
    put_at_objet(game, object_idx, source_idx)
    game.flag_genere_aff_list = 1


def choose_inventory_action(game, object_idx, action_text_id):
    if action_text_id not in inventory_actions(game, object_idx):
        raise ValueError(f"object {object_idx} does not expose inventory action {action_text_id}")
    game.in_hand_table[game.current_inventory] = object_idx
    game.action = 1 << (action_text_id - 23)
    return execute_found_life(game, object_idx)


def resolve_actor_contacts(game, actor_idx, old_zv, attempted_zv, step_x, step_z):
    from PyAitD.engine.actors import check_hard_col, check_object_col, gere_collision
    from PyAitD.engine.game import AF_ANIMATED, AF_BOXIFY, AF_FOUNDABLE, AF_MOVABLE

    actor = game.actors[actor_idx]
    room = game.rooms_of_floor(game.current_floor)[actor.room]
    for touched_idx in check_object_col(game, actor_idx, attempted_zv):
        touched = game.actors[touched_idx]
        touched.col_by = actor_idx
        if touched.object_type & AF_FOUNDABLE:
            if actor.track_mode in PLAYER_TRACK_MODES and game.active_modal is None:
                effect = request_found(game, touched.index_in_world, parameter=0)
                if effect is not None:
                    game.open_modal(effect)
            continue

        touched_zv = touched.zv
        if touched.room != actor.room:
            touched_zv = adjust_zv_between_rooms(game, touched_zv, touched.room, actor.room)
        if touched.object_type & AF_MOVABLE:
            pushed_zv = [
                touched_zv[0] + step_x, touched_zv[1] + step_x,
                touched_zv[2], touched_zv[3],
                touched_zv[4] + step_z, touched_zv[5] + step_z,
            ]
            blocked = bool(check_hard_col(pushed_zv, room.hard_cols))
            if not blocked:
                original_room = touched.room
                touched.room = actor.room
                blocked = bool(check_object_col(game, touched_idx, pushed_zv))
                touched.room = original_room
            if not blocked:
                touched.object_type |= AF_ANIMATED
                touched.object_type &= ~AF_BOXIFY
                touched.world_x += step_x
                touched.world_z += step_z
                touched.room_x += step_x
                touched.room_z += step_z
                touched.zv = pushed_zv
                continue
        if actor.dyn_flags & 1 and (step_x or step_z):
            step_x, step_z = gere_collision(old_zv, attempted_zv, touched_zv, step_x, step_z)
            attempted_zv = [
                old_zv[0] + step_x, old_zv[1] + step_x,
                attempted_zv[2], attempted_zv[3],
                old_zv[4] + step_z, old_zv[5] + step_z,
            ]
    return attempted_zv, step_x, step_z


def apply_found_result(game, result):
    from PyAitD.engine.effects import ShowFound
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
    from PyAitD.engine.effects import OpenInventory
    if not isinstance(game.active_modal, OpenInventory):
        raise RuntimeError(f"inventory result applied to {type(game.active_modal).__name__}")
    game.close_modal()
    if not result.cancelled:
        if not choose_inventory_action(game, result.object_idx, result.action_text_id):
            return False
    return resume_life(game)


def apply_reading_result(game, result):
    from PyAitD.engine.effects import ReadText, ShowPicture
    if not isinstance(game.active_modal, (ReadText, ShowPicture)):
        raise RuntimeError(f"reading result applied to {type(game.active_modal).__name__}")
    if not result.dismissed:
        return False
    game.close_modal()
    game.flag_init_view = 1
    return resume_life(game)


def point_in_zone(x, y, z, zone):
    return zone.x1 <= x <= zone.x2 and zone.y1 <= y <= zone.y2 and zone.z1 <= z <= zone.z2


def apply_click_intent(
        game, dest_x, dest_z, room, target_object_idx=-1, *, requires_hold=False,
):
    """Record where the player clicked. A new click replaces any previous one."""
    from PyAitD.engine.effects import NavIntent
    hero_idx = game.current_camera_target_actor
    origin_room = None
    if requires_hold:
        origin_room = (
            game.actors[hero_idx].room
            if 0 <= hero_idx < len(game.actors) else room
        )
    game.nav_intent = NavIntent(
        dest_x, dest_z, room, target_object_idx,
        requires_hold=requires_hold,
        origin_floor=game.current_floor if requires_hold else None,
        origin_room=origin_room,
    )
    game.nav_decision = None


def cancel_nav_intent(game):
    """Drop the current intent. Used on modal entry and on a stop click."""
    intent = game.nav_intent
    held = intent is not None and intent.requires_hold
    game.nav_intent = None
    game.nav_decision = None
    game.nav_arrived_target = -1
    game.local_joyd = 0
    game.local_click = 0
    game.local_key = 0
    game.action = 0
    if not held:
        return
    hero_idx = game.current_camera_target_actor
    if hero_idx == -1:
        return
    from PyAitD.engine.anim import init_anim
    hero = game.actors[hero_idx]
    hero.speed = 0
    hero.direction = 0
    hero.rotate.num_steps = 0
    # GereAnim owns the pending step: when it applies this stand transition it
    # commits step_x/step_z into the base coordinates without moving the ZV
    # again (FITD anim.cpp:238-253).  Leaving the step intact preserves the
    # actor's already-rendered effective position across release.
    init_anim(hero, PLAYER_STAND_ANIM, 0, PLAYER_STAND_ANIM)
    hero.new_anim, hero.new_anim_type, hero.new_anim_info = (
        PLAYER_STAND_ANIM, 0, PLAYER_STAND_ANIM,
    )


def cancel_held_nav_intent(game):
    """Cancel a held navigation intent without disturbing ordinary clicks."""
    intent = game.nav_intent
    if intent is None or not intent.requires_hold:
        return False
    cancel_nav_intent(game)
    return True


def attack_in_hand(game, target_actor_idx):
    """Accept a target click: validate it, stop, and face the target.

    This deliberately stops short of choosing an inventory action. ENGLISH.PAK
    text 32 is "Throw", so `choose_inventory_action(..., 32)` would launch the
    weapon at the floor instead of swinging it. FITD's melee comes from held
    action input (mainLoop.cpp:87-101), which the caller arms on the returned
    True; explicit Throw stays reachable only from the inventory row itself.
    """
    # Imported lazily so tests can monkeypatch PyAitD.engine.tracks.face_toward and
    # this module stays free of track-system imports at module load time.
    from PyAitD.engine.tracks import face_toward

    hero_idx = game.current_camera_target_actor
    if hero_idx == -1 or not is_combat_target(game, target_actor_idx):
        return False
    object_idx = game.in_hand_table[game.current_inventory]
    if combat_action_for(game, object_idx) is None:
        return False

    hero = game.actors[hero_idx]
    target = game.actors[target_actor_idx]
    target_x, target_z = target.room_x, target.room_z
    if hero.room != target.room:
        # track.cpp:265-273 (FITD follow mode) converts the target into the
        # hero's room space: target_x += dx, target_z -= dz.
        dx, _dy, dz = room_delta(game, hero.room, target.room)
        target_x += dx
        target_z -= dz

    cancel_nav_intent(game)
    hero.speed = 0
    face_toward(hero, target_x, target_z)
    return True


def dispatch_nav_arrival(game):
    """Act on a follower arrival. False when a modal was opened (tick suspends).

    Only a *clicked target* dispatches. A bare floor walk ends silently: the
    action bit is global (scripts poll it through evalVar 0x11), and the
    keyboard presses it only when the player presses Space, so pressing it at
    the end of every walk would fire unrequested actions all over the map.
    Mouse-only players still reach Action by clicking the object itself, which
    routes through the target branch below.
    """
    from PyAitD.engine.game import AF_FOUNDABLE
    target = game.nav_arrived_target
    game.nav_arrived_target = -1
    if game.active_modal is not None:
        return True
    if target == -1:
        return True
    world = game.world_objects[target]
    if world.obj_index == -1:
        return True  # taken or despawned while we walked
    actor = game.actors[world.obj_index]
    if actor.object_type & AF_FOUNDABLE:
        effect = request_found(game, target, parameter=0)
        if effect is not None:
            game.open_modal(effect)
            return False
        return True
    game.action = 0x2000
    return True


def gere_dec(game, actor_idx):
    actor = game.actors[actor_idx]
    rooms = game.rooms_of_floor(game.current_floor)
    room = rooms[actor.room]
    x = actor.room_x + actor.step_x
    y = actor.room_y + actor.step_y
    z = actor.room_z + actor.step_z
    for zone in room.sce_zones:
        if not point_in_zone(x, y, z, zone):
            continue
        if zone.type == 0:
            old_room = actor.room
            actor.room = zone.parameter
            dx, dy, dz = room_delta(game, old_room, actor.room)
            actor.room_x -= dx
            actor.room_y += dy
            actor.room_z += dz
            actor.zv = shifted_zv(actor.zv, dx, dy, dz)
            if actor_idx == game.current_camera_target_actor:
                game.flag_change_salle = 1
                game.new_num_salle = actor.room
            else:
                game.flag_genere_aff_list = 1
        elif zone.type == 9:
            actor.hard_dec = zone.parameter
        elif zone.type == 10:
            world = game.world_objects[actor.index_in_world]
            if world.floor_life == -1:
                return
            actor.life = world.floor_life
            actor.hard_dec = zone.parameter
        return
