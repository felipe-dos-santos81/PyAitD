# SPDX-License-Identifier: GPL-2.0-only
"""The enemy vocabulary: pursuer and sentry, one state machine.

Every transition calls only what LIFE opcodes call -- init_deplacement +
process_track (LM_MOVE + LM_DO_MOVE), init_anim (LM_ANIM_*), arm_strike
(LM_HIT), delete_object (LM_DELETE) -- so a pack enemy rides the same
collision, animation and hit code as a scripted one. State is
game.content_state[world_idx] = {"hp", "phase"}; the phase table is the
spec's section 3."""
from PyAitD.engine.actor.anim import ANIM_ONCE, ANIM_REPEAT, ANIM_UNINTERRUPTABLE, init_anim
from PyAitD.engine.actor.anim_action import arm_strike
from PyAitD.engine.actor.tracks import _turn_toward, init_deplacement, process_track
from PyAitD.engine.script.eval_var import calc_dist
from PyAitD.engine.script.game.objects import delete_object

TRACK_FOLLOW = 2   # track_mode 2: follow a world object (track.cpp:230)


def _hero_in_room(game, actor):
    idx = game.current_camera_target_actor
    if idx == -1:
        return None
    hero = game.actors[idx]
    return hero if hero.room == actor.room else None


def _distance(actor, other):
    # the DISTANCE tag's own metric (evalVar): Manhattan, world coordinates
    return calc_dist(actor.world_x, actor.world_y, actor.world_z,
                     other.world_x, other.world_y, other.world_z)


def _stop(actor):
    actor.track_mode = 0
    actor.speed = 0


def _resume_phase(record):
    return "chase" if record.kind == "pursuer" else "idle"


def enter_phase(game, actor, record, state, phase):
    """Set `phase` and issue its entry primitives. `attack` is entered only
    through _try_attack, since arm_strike may refuse."""
    state["phase"] = phase
    anims = record.anims
    if phase == "idle":
        _stop(actor)
        init_anim(actor, anims.stand, ANIM_REPEAT, -1)
    elif phase == "chase":
        init_deplacement(actor, TRACK_FOLLOW, game.current_world_target)
        init_anim(actor, anims.walk, ANIM_REPEAT, -1)
    elif phase == "hurt":
        _stop(actor)
        init_anim(actor, anims.hurt, ANIM_ONCE, anims.stand)
    elif phase == "dying":
        _stop(actor)
        init_anim(actor, anims.death, ANIM_UNINTERRUPTABLE, -1)


def _try_attack(actor, record, state):
    a = record.attack
    if arm_strike(actor, record.anims.attack, a.frame, a.group, a.radius, a.force, record.anims.stand):
        _stop(actor)              # no sliding mid-swing
        state["phase"] = "attack"
        return True
    return False


def step_enemy(game, slot, record, state):
    """One tick of the record's behaviour for the actor in `slot`. Runs at
    the LIFE loop's position, so hit_by reflects this tick's anim pass and a
    phase entered here is committed by the next tick's gere_anim before
    flag_end_anim is consulted again."""
    actor = game.actors[slot]
    phase = state["phase"]
    if phase == "dead":
        return
    if phase == "dying":
        if actor.flag_end_anim:
            delete_object(game, actor.index_in_world)   # stage -1: never respawns
            state["phase"] = "dead"
        return
    if actor.hit_by != -1:
        state["hp"] -= actor.hit_force
        if state["hp"] <= 0:
            enter_phase(game, actor, record, state, "dying")
        elif phase != "hurt":
            enter_phase(game, actor, record, state, "hurt")
        # a hit during hurt or attack counts; the anim is not restarted
        return
    hero = _hero_in_room(game, actor)
    if phase == "idle":
        if record.kind == "pursuer":
            enter_phase(game, actor, record, state, "chase")
            return
        if hero is None:
            return
        distance = _distance(actor, hero)
        if distance < 2 * record.attack.range:
            _turn_toward(game, actor, hero.room_x, hero.room_z)   # the follow track's own turn
            actor.beta &= 0x3FF
        if distance < record.attack.range:
            _try_attack(actor, record, state)
    elif phase == "chase":
        process_track(game, actor)                                # LM_DO_MOVE
        if hero is not None and _distance(actor, hero) < record.attack.range:
            _try_attack(actor, record, state)
    elif phase in ("attack", "hurt"):
        if actor.flag_end_anim:
            enter_phase(game, actor, record, state, _resume_phase(record))
