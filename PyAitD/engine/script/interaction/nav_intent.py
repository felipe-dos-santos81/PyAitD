# SPDX-License-Identifier: GPL-2.0-only
"""NavIntent record/drop and follower arrival dispatch."""
from PyAitD.engine.script.interaction.inventory import request_found


def apply_click_intent(
        game, dest_x, dest_z, room, target_object_idx=-1, *, requires_hold=False,
        run=False, steering=False,
):
    """Record where the player clicked. A new click replaces any previous one."""
    from PyAitD.engine.script.effects import NavIntent
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
        # a held push is always a walk: leaning on furniture at a run is not
        # a speed FITD's push animation has
        run=run and not requires_hold,
        # a held push leans on one named piece of furniture, and held_push
        # rewrites its destination every tick: there is no bearing to keep
        steering=steering and not requires_hold,
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
    from PyAitD.engine.actor.anim import init_anim
    hero = game.actors[hero_idx]
    hero.speed = 0
    hero.direction = 0
    hero.rotate.num_steps = 0
    # GereAnim owns the pending step: when it applies this stand transition it
    # commits step_x/step_z into the base coordinates without moving the ZV
    # again (FITD anim.cpp:238-253).  Leaving the step intact preserves the
    # actor's already-rendered effective position across release.
    init_anim(hero, game.profile.player_stand_anim, 0, game.profile.player_stand_anim)
    hero.new_anim, hero.new_anim_type, hero.new_anim_info = (
        game.profile.player_stand_anim, 0, game.profile.player_stand_anim,
    )


def cancel_held_nav_intent(game):
    """Cancel a held navigation intent without disturbing ordinary clicks.

    No production caller since held pointer follow landed: the release path
    now runs through PyAitD/app/shell.py::_cancel_follow, which cancels any
    live intent rather than only held ones. Kept for its own test coverage.
    """
    intent = game.nav_intent
    if intent is None or not intent.requires_hold:
        return False
    cancel_nav_intent(game)
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
    from PyAitD.engine.script.game import AF_FOUNDABLE
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
