# SPDX-License-Identifier: GPL-2.0-only
"""In-hand combat gating and held/push approach."""
from PyAitD.engine.script.interaction.inventory import inventory_actions, inventory_items
from PyAitD.engine.space.world import room_delta


def is_combat_target(game, actor_idx):
    from PyAitD.engine.script.game import AF_ANIMATED
    if actor_idx < 0 or actor_idx >= len(game.actors):
        return False
    if actor_idx == game.current_camera_target_actor:
        return False
    actor = game.actors[actor_idx]
    return actor.index_in_world >= 0 and bool(actor.object_type & AF_ANIMATED)


def is_hold_action_target(game, actor_idx):
    from PyAitD.engine.script.game import AF_FOUNDABLE, AF_MOVABLE
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
    from PyAitD.engine.nav.navmesh import agent_extent, nearest_walkable

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
         if action in game.profile.combat_action_text_ids),
        None,
    )


def can_strike(game, *, require_idle=True):
    """True when a click on a combat target should swing.

    The swing comes from the in-hand object's own LIFE, which play_tick runs
    every tick: no object in hand, no script, no strike. What that object *is*
    is not ours to judge. Equipping a weapon leaves the wielded variant in
    hand, not the inventory entry -- choosing Fight on the attic lamp (13)
    leaves object 2, whose own inventory flags carry no Fight at all -- so
    asking the held object for a Fight action refuses every weapon the player
    actually equipped, while the engine swings perfectly well.

    `require_idle` is the difference between starting a strike and keeping one
    alive: a click may only start combat from an idle hero, but the tick seam
    re-validates while the melee animation is still running.
    """
    hero_idx = game.current_camera_target_actor
    if hero_idx == -1:
        return False
    if require_idle and game.actors[hero_idx].anim_action_type != 0:
        return False
    inventory = game.current_inventory
    if not 0 <= inventory < len(game.in_hand_table):
        return False
    return game.in_hand_table[inventory] != -1


def attack_in_hand(game, target_actor_idx):
    """Accept a target click: validate it, stop, and face the target.

    This deliberately stops short of choosing an inventory action. ENGLISH.PAK
    text 32 is "Throw", so `choose_inventory_action(..., 32)` would launch the
    weapon at the floor instead of swinging it. FITD's melee comes from held
    action input (mainLoop.cpp:87-101), which the caller arms on the returned
    True; explicit Throw stays reachable only from the inventory row itself.
    """
    # Imported lazily so tests can monkeypatch PyAitD.engine.actor.tracks.face_toward and
    # this module stays free of track-system imports at module load time.
    from PyAitD.engine.actor.tracks import face_toward

    if not is_combat_target(game, target_actor_idx) or not can_strike(game):
        return False
    hero_idx = game.current_camera_target_actor

    hero = game.actors[hero_idx]
    target = game.actors[target_actor_idx]
    target_x, target_z = target.room_x, target.room_z
    if hero.room != target.room:
        # track.cpp:265-273 (FITD follow mode) converts the target into the
        # hero's room space: target_x += dx, target_z -= dz.
        dx, _dy, dz = room_delta(game, hero.room, target.room)
        target_x += dx
        target_z -= dz

    # interaction subpackage cycle: lazy
    from PyAitD.engine.script.interaction.nav_intent import cancel_nav_intent
    cancel_nav_intent(game)
    hero.speed = 0
    face_toward(hero, target_x, target_z)
    return True
