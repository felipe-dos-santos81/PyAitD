# SPDX-License-Identifier: GPL-2.0-only
"""PLAY input snapshot: track-mode re-assert, mouse follower decision, bounded attack publishing."""
from dataclasses import dataclass

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


@dataclass(frozen=True)
class PlayInput:
    """What the engine reads from the player each tick, and nothing else.

    Built once per tick by app.controls.snapshot; the app keeps every piece
    of gesture state (hold-follow, double press, cut settling) on its side of
    this boundary. Frozen so the engine cannot write back into it: the
    sticky-action pulse is consumed by the app when it builds the snapshot.
    """
    joyd: int = 0
    action_held: bool = False
    action_pulse: bool = False
    pointer_held: bool = False
    focused: bool = True


IDLE = PlayInput()


def arm_mouse_attack(game, target_idx):
    """An accepted target click holds FITD's own action input for the next
    few ticks (mainLoop.cpp:87-101); the engine owns the countdown because
    the engine is what ends it (the hero back to idle, or the budget)."""
    game.mouse_attack_target = target_idx
    game.mouse_attack_ticks = 0


def clear_mouse_attack(game):
    game.mouse_attack_target = None
    game.mouse_attack_ticks = 0


def apply_play_input(game, play_input):
    # The hero's manual-control track mode belongs to the input mode, and a
    # script can hand it back to tank mode at any time (LM_INIT_DEPLACEMENT),
    # so it is re-asserted here rather than only at init and on the Tab toggle.
    sync_player_track_mode(game)
    if game.input_mode is InputMode.MOUSE:
        _apply_mouse_input(game, play_input)
        return
    game.nav_decision = None
    game.local_joyd = play_input.joyd if play_input.focused else 0
    pressed = play_input.focused and (play_input.action_held or play_input.action_pulse)
    game.local_click = 1 if pressed else 0
    game.local_key = 0
    game.action = 0x2000 if game.local_click else 0


def _apply_mouse_attack(game):
    """Publish one tick of FITD's own action input for an accepted click.

    A single tick of action is not enough: the player's LIFE queues the idle
    animation again as soon as the action input drops, so the swing never
    reaches its strike frame. The click therefore holds forward plus action for
    the caller until the melee animation completes -- automatically, and
    bounded, so the player never has to hold or time a button.
    """
    from PyAitD.engine.script.interaction import can_strike, is_combat_target

    target_idx = game.mouse_attack_target
    if target_idx is None:
        return False
    hero_idx = game.current_camera_target_actor
    if (not is_combat_target(game, target_idx)
            or not can_strike(game, require_idle=False)):
        clear_mouse_attack(game)
        return False
    ticks = game.mouse_attack_ticks
    # The first tick is what arms the animation, so it publishes before any
    # completion test; afterwards the hero returning to idle ends the strike.
    if ticks and (game.actors[hero_idx].anim_action_type == 0
                  or ticks >= MOUSE_ATTACK_TICK_BUDGET):
        clear_mouse_attack(game)
        return False
    game.mouse_attack_ticks = ticks + 1
    game.nav_decision = None
    game.local_key = 0
    game.local_joyd = 1
    game.local_click = 1
    game.action = NATIVE_ACTION
    return True


def _apply_mouse_input(game, play_input):
    # The follower decision is made here, in the input snapshot, so the tick
    # order stays exactly FITD's mainLoop order and the mouse is a peer of the
    # keyboard rather than a bolt-on.
    game.local_key = 0
    game.local_click = 0
    game.action = 0
    # An accepted target click outranks navigation: attack_in_hand already
    # cancelled the intent, and the strike owns the hero until it finishes.
    if _apply_mouse_attack(game):
        return
    hero_idx = game.current_camera_target_actor
    intent = game.nav_intent
    if hero_idx == -1 or intent is None:
        game.nav_decision = None
        game.local_joyd = 0
        return
    from PyAitD.engine.script.interaction import cancel_nav_intent
    if not play_input.focused or not play_input.pointer_held:
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
