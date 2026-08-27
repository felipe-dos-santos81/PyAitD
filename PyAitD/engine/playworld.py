# SPDX-License-Identifier: GPL-2.0-only
"""PlayWorld simulation tick (FITD mainLoop.cpp:41-281 order).

Imports no pygame, ModernGL or Renderer, so one 50 Hz logic step can be
advanced without a window. Callers still reach `ui.py` for an InputBuffer;
freeing that needs InputBuffer moved out of the presentation layer.
"""
from PyAitD.engine.actors import gere_anim
from PyAitD.engine.anim_action import gere_frappe, refresh_hot_point
from PyAitD.engine.effects import CutsceneFinished, GameMode, GameOver, InputMode, LifeFrame
from PyAitD.engine.formats import parse_cover_zones
from PyAitD.engine.game import (
    AF_ANIMATED, AF_TRIGGER, change_salle, game_step_tick, spawn_stage_actors,
)
from PyAitD.engine.interaction import (
    advance_messages, dispatch_nav_arrival, drain_immediate_effects, execute_found_life,
    gere_dec, run_life, sync_player_track_mode,
)
from PyAitD.engine.life import life_gate
from PyAitD.engine.navigate import WAYPOINT_DISTANCE, decide
from PyAitD.engine.navmesh import agent_extent, find_path, nearest_walkable
from PyAitD.engine.world import find_best_camera, is_in_poly

TICK_MS = 20  # 50 Hz logic tick
NATIVE_ACTION = 0x2000  # mainLoop.cpp:87-101 held-action input
# Melee animation 41 reaches its strike frame well inside this; the budget
# only exists so a LIFE that never returns the hero to idle cannot leave the
# mouse holding a virtual button for the rest of the session.
MOUSE_ATTACK_TICK_BUDGET = 100


def apply_play_input(game, input_buffer):
    # The hero's manual-control track mode belongs to the input mode, and a
    # script can hand it back to tank mode at any time (LM_INIT_DEPLACEMENT),
    # so it is re-asserted here rather than only at init and on the Tab toggle.
    sync_player_track_mode(game)
    if game.input_mode is InputMode.MOUSE:
        input_buffer.action_pulse = False
        _apply_mouse_input(game, input_buffer)
        return
    game.nav_decision = None
    game.local_joyd = input_buffer.held_joyd if input_buffer.focused else 0
    pressed = input_buffer.focused and (input_buffer.action_held or input_buffer.action_pulse)
    game.local_click = 1 if pressed else 0
    game.local_key = 0
    input_buffer.action_pulse = False
    game.action = 0x2000 if game.local_click else 0


def _push_into_target(game):
    """Re-aim an arrived target click at the object itself for the final push.

    FITD fires scripted founds from the collision itself: anim.cpp:381 sets
    HARD_COL from a type-9 hard col's parameter, and watchers such as the
    attic lamp's life 7 call FOUND when the hero grinds into the furniture.
    The snapped approach cell stops one agent-radius short of every hard col,
    so a click that ended there could never reach those scripts. Steer into
    the object instead and let the engine's own collision clamp the hero
    against it — the mouse equivalent of holding the walk key. Foundable
    objects keep the contact-free dispatch at the approach cell, and a second
    arrival at the object's own point dispatches normally, so the push always
    terminates in a dispatch, a modal, or the stall give-up.
    """
    from PyAitD.engine.game import AF_FOUNDABLE
    intent = game.nav_intent
    if intent.target_object_idx == -1:
        return False
    target = game.world_objects[intent.target_object_idx]
    if target.obj_index == -1 or target.found_life == -1:
        return False
    actor = game.actors[target.obj_index]
    if actor.object_type & AF_FOUNDABLE:
        return False
    if (intent.dest_x, intent.dest_z) == (actor.room_x, actor.room_z):
        return False
    intent.dest_x, intent.dest_z = actor.room_x, actor.room_z
    intent.room = actor.room
    intent.waypoints = None
    return True


def _refresh_held_target(game, hero, mesh):
    from PyAitD.engine.interaction import (
        PLAYER_PUSH_ANIM, cancel_nav_intent, hold_action_approach,
        is_hold_action_target,
    )
    from PyAitD.engine.anim import init_anim

    intent = game.nav_intent
    world_idx = intent.target_object_idx
    if not 0 <= world_idx < len(game.world_objects):
        cancel_nav_intent(game)
        return False
    world = game.world_objects[world_idx]
    actor_idx = world.obj_index
    if (not 0 <= actor_idx < len(game.actors)
            or game.actors[actor_idx].index_in_world != world_idx
            or not is_hold_action_target(game, actor_idx)
            or game.actors[actor_idx].room != hero.room):
        cancel_nav_intent(game)
        return False
    target = game.actors[actor_idx]
    if not intent.engaged:
        target_pose = (
            target.room, target.room_x, target.room_y, target.room_z,
            target.beta, tuple(target.zv),
        )
        previous_pose = intent.approach_target_pose
        if previous_pose == target_pose:
            return True
        intent.approach_target_pose = target_pose
        payload = hold_action_approach(
            game, game.current_floor_data,
            game.current_camera_target_actor, actor_idx,
        )
        if payload is None:
            cancel_nav_intent(game)
            return False
        dest_x, dest_z, room, _world_idx = payload
        target_moved = previous_pose is not None
        if (target_moved
                or (intent.dest_x, intent.dest_z, intent.room) != (dest_x, dest_z, room)):
            intent.dest_x, intent.dest_z, intent.room = dest_x, dest_z, room
            intent.waypoints = None
            intent.path_room = -1
            intent.stall_target = None
            intent.stall_best = 0
            intent.stall_ticks = 0
        return True
    point = _held_push_point(intent, hero, target, game.current_camera_target_actor)
    if (intent.dest_x, intent.dest_z, intent.room) != (*point, target.room):
        intent.stall_target = None
        intent.stall_best = 0
        intent.stall_ticks = 0
    intent.dest_x, intent.dest_z, intent.room = point[0], point[1], target.room
    if intent.waypoints is not None and len(intent.waypoints) > 1:
        intent.waypoints[-1] = point
    else:
        detour = _held_contact_detour(game, hero, actor_idx, point, mesh)
        intent.waypoints = [*detour, point] if detour is not None else [point]
    intent.path_room = hero.room
    pending = (hero.new_anim, hero.new_anim_type, hero.new_anim_info)
    init_anim(hero, PLAYER_PUSH_ANIM, 1, -1)
    if hero.anim == PLAYER_PUSH_ANIM and pending == (254, 1, -1):
        # The player's LIFE queues its ordinary forward animation after the
        # animation pass.  Keep an already-active push pose advancing instead
        # of alternating back to walk and resetting both animations every tick.
        # Other requests retain init_anim's normal arbitration protections.
        hero.new_anim = -1
        hero.new_anim_type = 0
        hero.new_anim_info = -1
    return True


def _held_push_point(intent, hero, target, hero_idx):
    """Steer an engaged push at the target, then straight into the face it hits.

    Aiming at the target's centre from a corner cell is a diagonal, so once the
    hero touches the target FITD GereCollision's glisser slides it along the
    target's face until it meets whatever sits beside the target. GereAnim
    checks hard cols before actor contacts and never rechecks the reduced step
    (anim.cpp:373-570), so that slide can sink the hero into an adjacent hard
    col, where every later step is zeroed. The centre aim is kept until the
    engine reports first contact (col_by is written by the previous tick's
    animation pass and reset only after this snapshot); from then on the push
    runs along the axis of the touched face with the lateral coordinate
    frozen, so there is no slide.
    """
    if intent.push_axis is None:
        if target.col_by != hero_idx:
            return (target.room_x, target.room_z)
        here_x = hero.room_x + hero.step_x
        here_z = hero.room_z + hero.step_z
        x0, x1, _y0, _y1, z0, z1 = target.zv
        overlaps_x = hero.zv[0] < x1 and x0 < hero.zv[1]
        overlaps_z = hero.zv[4] < z1 and z0 < hero.zv[5]
        if overlaps_x != overlaps_z:
            along_z = overlaps_x
        else:
            along_z = abs(target.room_z - here_z) >= abs(target.room_x - here_x)
        intent.push_axis = "z" if along_z else "x"
        intent.push_lateral = here_x if along_z else here_z
    if intent.push_axis == "z":
        return (intent.push_lateral, target.room_z)
    return (target.room_x, intent.push_lateral)


def _held_contact_detour(game, hero, target_idx, point, mesh):
    """One clearance waypoint when a non-target actor blocks contact."""
    hero_idx = game.current_camera_target_actor
    blocker = next((
        actor for idx, actor in enumerate(game.actors)
        if idx != target_idx and actor.index_in_world >= 0
        and actor.room == hero.room and actor.col_by == hero_idx
        and hero.zv[2] < actor.zv[3] and actor.zv[2] < hero.zv[3]
        and _corridor_hits_actor(hero, point, actor.zv)
    ), None)
    if blocker is None or mesh is None:
        return None
    here_x = hero.room_x + hero.step_x
    here_z = hero.room_z + hero.step_z
    half = agent_extent(hero)[0]
    # decide() drops an intermediate waypoint within WAYPOINT_DISTANCE.  Leave
    # that much clearance after snapping to the mesh, otherwise the hero turns
    # back into the blocker before their footprints have actually separated.
    margin = half + WAYPOINT_DISTANCE + mesh.step + 1
    x0, x1, _y0, _y1, z0, z1 = blocker.zv
    if abs(point[0] - here_x) >= abs(point[1] - here_z):
        candidates = ((here_x, z1 + margin), (here_x, z0 - margin))

        def clears(waypoint):
            return (waypoint[1] - WAYPOINT_DISTANCE >= z1 + half
                    or waypoint[1] + WAYPOINT_DISTANCE <= z0 - half)
    else:
        candidates = ((x1 + margin, here_z), (x0 - margin, here_z))

        def clears(waypoint):
            return (waypoint[0] - WAYPOINT_DISTANCE >= x1 + half
                    or waypoint[0] + WAYPOINT_DISTANCE <= x0 - half)
    paths = []
    for candidate in candidates:
        walkable = nearest_walkable(mesh, *candidate)
        if walkable is None or not clears(walkable):
            continue
        path = find_path(mesh, (here_x, here_z), walkable)
        if path:
            paths.append(path)
    if not paths:
        return None
    return min(paths, key=lambda path: _path_distance((here_x, here_z), path))


def _corridor_hits_actor(hero, point, blocker_zv):
    """Whether the direct contact corridor crosses a blocker footprint."""
    half = agent_extent(hero)[0]
    here = (hero.room_x + hero.step_x, hero.room_z + hero.step_z)
    delta = (point[0] - here[0], point[1] - here[1])
    bounds = (
        (blocker_zv[0] - half, blocker_zv[1] + half),
        (blocker_zv[4] - half, blocker_zv[5] + half),
    )
    entry, leave = 0.0, 1.0
    for origin, change, (low, high) in zip(here, delta, bounds):
        if change == 0:
            if not low <= origin <= high:
                return False
            continue
        first, second = (low - origin) / change, (high - origin) / change
        entry = max(entry, min(first, second))
        leave = min(leave, max(first, second))
    return entry <= leave and leave > 0.0 and entry < 1.0


def _path_distance(start, path):
    points = (start, *path)
    return sum(
        abs(next_point[0] - point[0]) + abs(next_point[1] - point[1])
        for point, next_point in zip(points, points[1:])
    )


def _clear_mouse_attack(input_buffer):
    input_buffer.mouse_attack_target = None
    input_buffer.mouse_attack_ticks = 0


def _apply_mouse_attack(game, input_buffer):
    """Publish one tick of FITD's own action input for an accepted click.

    A single tick of action is not enough: the player's LIFE queues the idle
    animation again as soon as the action input drops, so the swing never
    reaches its strike frame. The click therefore holds forward plus action for
    the caller until the melee animation completes -- automatically, and
    bounded, so the player never has to hold or time a button.
    """
    from PyAitD.engine.interaction import combat_action_for, is_combat_target

    target_idx = input_buffer.mouse_attack_target
    if target_idx is None:
        return False
    hero_idx = game.current_camera_target_actor
    inventory = game.current_inventory
    in_hand = (
        game.in_hand_table[inventory]
        if 0 <= inventory < len(game.in_hand_table) else -1
    )
    if (hero_idx == -1 or not is_combat_target(game, target_idx)
            or combat_action_for(game, in_hand, require_idle=False) is None):
        _clear_mouse_attack(input_buffer)
        return False
    ticks = input_buffer.mouse_attack_ticks
    # The first tick is what arms the animation, so it publishes before any
    # completion test; afterwards the hero returning to idle ends the strike.
    if ticks and (game.actors[hero_idx].anim_action_type == 0
                  or ticks >= MOUSE_ATTACK_TICK_BUDGET):
        _clear_mouse_attack(input_buffer)
        return False
    input_buffer.mouse_attack_ticks = ticks + 1
    game.nav_decision = None
    game.local_key = 0
    game.local_joyd = 1
    game.local_click = 1
    game.action = NATIVE_ACTION
    return True


def _apply_mouse_input(game, input_buffer):
    # The follower decision is made here, in the input snapshot, so the tick
    # order stays exactly FITD's mainLoop order and the mouse is a peer of the
    # keyboard rather than a bolt-on.
    game.local_key = 0
    game.local_click = 0
    game.action = 0
    # An accepted target click outranks navigation: attack_in_hand already
    # cancelled the intent, and the strike owns the hero until it finishes.
    if _apply_mouse_attack(game, input_buffer):
        return
    hero_idx = game.current_camera_target_actor
    intent = game.nav_intent
    if hero_idx == -1 or intent is None:
        game.nav_decision = None
        game.local_joyd = 0
        return
    from PyAitD.engine.interaction import cancel_nav_intent
    if not input_buffer.focused or not input_buffer.pointer_held:
        # Held pointer follow: every intent is hold-bound, plain walks
        # included. Enforced here, at the tick where FITD reads input, so a
        # release stops the hero on the very next tick, between frames too.
        cancel_nav_intent(game)
        return
    hero = game.actors[hero_idx]
    if intent.requires_hold:
        if intent.origin_floor is None:
            intent.origin_floor = game.current_floor
        if intent.origin_room is None:
            intent.origin_room = hero.room
        if (game.current_floor != intent.origin_floor
                or hero.room != intent.origin_room):
            cancel_nav_intent(game)
            return
    mesh = game.nav_meshes.mesh_for(game.current_floor_data, hero.room, agent_extent(hero))
    if intent.requires_hold:
        if not _refresh_held_target(game, hero, mesh):
            return
    decision = decide(
        game, hero, mesh, stop_at_destination=not intent.engaged,
    )
    game.nav_decision = decision
    game.local_joyd = decision.joyd if decision is not None else 0
    if decision is None or not (decision.arrived or decision.abandoned):
        return
    if intent.requires_hold:
        if decision.arrived and not decision.abandoned and not intent.engaged:
            intent.engaged = True
            if _refresh_held_target(game, hero, mesh):
                game.nav_decision = None
                game.local_joyd = 0
            return
        cancel_nav_intent(game)
        return
    if decision.arrived and not decision.abandoned and _push_into_target(game):
        game.nav_decision = None
        game.local_joyd = 0
        return
    if decision.arrived:
        game.nav_arrived_target = intent.target_object_idx
    game.nav_intent = None
    game.nav_decision = None
    game.local_joyd = 0


def _run_actor_action(game, index, actor, flags):
    # animAction.cpp's GereFrappe consumes the *previous* pose's hot point
    # inside AllRedraw; this port refreshes it here, immediately before
    # gere_anim advances that pose, to reproduce the same value headlessly.
    if actor.anim_action_type and actor.hot_point_id != -1:
        refresh_hot_point(game, index)
    if flags & AF_ANIMATED:
        gere_anim(game, index)
        if game.mode is not GameMode.PLAY:
            return False
    if flags & AF_TRIGGER:
        gere_dec(game, index)
    if actor.anim_action_type:
        gere_frappe(game, index)
    return game.mode is GameMode.PLAY


def _anim_pass(game):
    for index, actor in enumerate(game.actors):
        if actor.index_in_world < 0:
            continue
        if not _run_actor_action(game, index, actor, actor.object_type):
            return False
    return game.mode is GameMode.PLAY


def _cover_zones(floor, cam_idx, room_idx):
    # cover zones of camera cam_idx for room_idx; [] when it does not view it
    viewed = [vr.viewed_room_idx for vr in floor.cameras[cam_idx].viewed_rooms]
    if room_idx not in viewed:
        return []
    off = floor.camera_data_offsets[cam_idx]
    return parse_cover_zones(floor.camera_raw, off, viewed.index(room_idx))


def _camera_switch(game, floor):
    # main.cpp:3654 GereSwitchCamera port: hero out of the current camera's
    # cover zones -> findBestCamera among the hero-room's cameras.
    if game.current_camera_target_actor == -1:
        return
    actor = game.actors[game.current_camera_target_actor]
    room = floor.rooms[actor.room]
    room_cameras = [floor.cameras[i] for i in room.camera_indices]
    zv = actor.zv
    x1, x2 = int(zv[0] / 10), int(zv[1] / 10)
    z1, z2 = int(zv[4] / 10), int(zv[5] / 10)
    if game.num_camera != -1:
        current = _cover_zones(floor, room.camera_indices[game.num_camera], actor.room)
        if current and is_in_poly(x1, x2, z1, z2, current):
            return
    zones_by_camera = [
        _cover_zones(floor, cam_idx, actor.room) for cam_idx in room.camera_indices
    ]
    new_camera = find_best_camera(x1, x2, z1, z2, actor.beta, room_cameras, zones_by_camera)
    if new_camera != -1 and game.num_camera != new_camera:
        game.new_num_camera = new_camera
        game.flag_init_view = 1


def _genere_active_list(game):
    # mainLoop.cpp:249 GenereActiveList. FITD calls it unconditionally; this
    # port keeps its flag_genere_aff_list request gate, so this stays the one
    # place the active list is regenerated.
    if not game.flag_genere_aff_list:
        return
    spawn_stage_actors(game)
    game.flag_genere_aff_list = 0


def _handoff_game_over(game):
    # mainLoop.cpp:185,233: FlagGameOver is checked only after the complete
    # LIFE actor loop, never mid-loop, and precedes floor/room/camera/spawn
    # handling. No LIFE continuation is retained: restart is a fresh session.
    if not game.flag_game_over:
        return True
    game.flag_game_over = 0
    if not game.allow_system_menu:
        game.open_modal(CutsceneFinished())
        return False
    game.open_modal(GameOver())
    return False


def play_tick(game, floor, input_buffer):
    # mainLoop.cpp:41-281 PlayWorld, one 50Hz iteration, PLAY mode only.
    # Rendering stays outside this fixed-step function so catch-up ticks
    # cannot block input behind repeated GPU work.
    if game.mode is not GameMode.PLAY:
        return False
    if game.flag_game_over and not _handoff_game_over(game):
        # A LIFE frame suspended on a modal is resumed by interaction.resume_life
        # when that modal closes, outside this function: the real death sequence
        # (LISTLIFE 554) is LM_PICTURE immediately followed by LM_GAME_OVER, so
        # the flag is raised long after the raising tick's LIFE loop finished.
        # FITD never sees a pending flag -- its LM_PICTURE blocks inside
        # processLife, so LM_GAME_OVER lands in the same pass mainLoop.cpp:185
        # checks. Consume it before this tick re-runs that LIFE, which would
        # suspend on the picture again and strand the flag forever.
        return False
    game.current_floor_data = floor   # the mesh cache needs the loaded Floor
    apply_play_input(game, input_buffer)
    if not dispatch_nav_arrival(game):
        return False
    game_step_tick(game)
    in_hand = game.in_hand_table[game.current_inventory]
    if in_hand != -1 and not execute_found_life(game, in_hand):
        return False
    if not drain_immediate_effects(game) or game.mode is not GameMode.PLAY:
        return False
    for actor in game.actors:
        if actor.index_in_world >= 0:
            actor.col_by = actor.hit_by = actor.hit = actor.hard_dec = actor.hard_col = -1
    if not _anim_pass(game):
        return False
    for index, actor in enumerate(game.actors):
        if actor.index_in_world < 0:
            continue
        if life_gate(actor):
            if not run_life(game, LifeFrame(index, actor.life)):
                drain_immediate_effects(game)
                return False
            if not drain_immediate_effects(game):
                return False
        if game.flag_change_etage:
            break
    if not _handoff_game_over(game):
        return False
    if game.flag_change_etage:
        # LoadEtage M3a subset (floor.cpp:7): floor data swap happens in run().
        # LoadEtage raises FlagChangeSalle (floor.cpp:40) and mainLoop consumes
        # it in the same iteration (mainLoop.cpp:189-199), so the room change
        # lands here rather than a tick later.
        game.current_floor = game.new_num_etage
        game.flag_change_etage = 0
        change_salle(game, game.new_num_salle)
        game.flag_change_salle = 0
        # FITD then `continue`s past GenereActiveList, so its next iteration
        # runs the anim pass over the previous floor's actors and only
        # regenerates at the end of it (mainLoop.cpp:249) -- C++ tolerates the
        # out-of-range roomDataTable read that produces, Python raises
        # IndexError. Raise the port's existing spawn request instead, so the
        # one spawn gate regenerates the list here, before any pass indexes the
        # new floor's rooms.
        game.flag_genere_aff_list = 1
        _genere_active_list(game)
        return False
    if game.flag_change_salle:
        # mainLoop.cpp:194-199: ChangeSalle + InitView + continue (no draw)
        change_salle(game, game.new_num_salle)
        game.flag_change_salle = 0
        return False
    _camera_switch(game, floor)
    if game.flag_init_view:
        # InitView M3a subset: camera data is loaded on demand at draw
        game.num_camera = game.new_num_camera
        game.flag_init_view = 0
    _genere_active_list(game)
    advance_messages(game)
    return True
