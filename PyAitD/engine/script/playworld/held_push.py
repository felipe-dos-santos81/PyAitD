# SPDX-License-Identifier: GPL-2.0-only
"""Held-push follower geometry: retarget, push point, contact detour, corridor helpers."""
from PyAitD.engine.nav.navigate import WAYPOINT_DISTANCE
from PyAitD.engine.nav.navmesh import agent_extent, find_path, nearest_walkable


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
    from PyAitD.engine.script.game import AF_FOUNDABLE
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
    from PyAitD.engine.script.interaction import (
        PLAYER_PUSH_ANIM, cancel_nav_intent, hold_action_approach,
        is_hold_action_target,
    )
    from PyAitD.engine.actor.anim import init_anim

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
