# SPDX-License-Identifier: GPL-2.0-only
"""PLAY input snapshot: track-mode re-assert, mouse follower decision, bounded attack publishing."""
from PyAitD.engine.script.effects import InputMode
from PyAitD.engine.script.interaction import sync_player_track_mode
from PyAitD.engine.nav.navigate import decide
from PyAitD.engine.nav.navmesh import agent_extent
from PyAitD.engine.script.playworld.held_push import (
    _push_into_target, _refresh_held_target,
)

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
    from PyAitD.engine.script.interaction import can_strike, is_combat_target

    target_idx = input_buffer.mouse_attack_target
    if target_idx is None:
        return False
    hero_idx = game.current_camera_target_actor
    if (not is_combat_target(game, target_idx)
            or not can_strike(game, require_idle=False)):
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
    from PyAitD.engine.script.interaction import cancel_nav_intent
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
