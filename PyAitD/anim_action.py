# SPDX-License-Identifier: GPL-2.0-only
"""Per-actor animation action runner (FITD animAction.cpp GereFrappe et al.).

Consumes the previous tick's cached hot point (refreshed by
`refresh_hot_point`, called just before `gere_anim` in playworld's per-actor
pass) to build a strike cube and publish hits through `check_object_col`.
Never touches actor.life: health lives in script vars, hit/hit_by/hit_force
are the only fields this module writes.
"""
from PyAitD.actors import anim_player_for, check_object_col
from PyAitD.game import AF_ANIMATED
from PyAitD.skel import hot_point

WAIT_FRAPPE_ANIM = 1
FRAPPE_OK = 2
WAIT_TIR_ANIM = 4
DO_TIR = 5
WAIT_ANIM_THROW = 6
WAIT_FRAME_THROW = 7
HIT_OBJECT = 8
THROW_OBJECT = 9
WAIT_FRAPPE_FRAME = 10
HANDLED_ACTIONS = {1, 2, 4, 5, 6, 7, 8, 9, 10}


def refresh_hot_point(game, actor_idx):
    actor = game.actors[actor_idx]
    body = game.assets.body(actor.body_num)
    states = (
        [(0, (0, 0, 0))] * len(body.groups)
        if actor.anim == -1 else anim_player_for(game, actor_idx).group_states()
    )
    actor.hot_point[:] = hot_point(
        body, states, (actor.alpha, actor.beta, actor.gamma),
        actor.hot_point_id,
    )


def _publish_hit(game, attacker_idx, victim_idx):
    attacker = game.actors[attacker_idx]
    victim = game.actors[victim_idx]
    attacker.hit = victim_idx
    victim.hit_by = attacker_idx
    victim.hit_force = attacker.hit_force


def gere_frappe(game, actor_idx):
    actor = game.actors[actor_idx]
    action = actor.anim_action_type
    if action not in HANDLED_ACTIONS:
        raise ValueError(f"actor {actor_idx} has unsupported anim action {action}")
    if action == WAIT_FRAPPE_ANIM:
        if actor.anim == actor.anim_action_anim:
            actor.anim_action_type = WAIT_FRAPPE_FRAME
        action = actor.anim_action_type
    if action == WAIT_FRAPPE_FRAME:
        if actor.anim != actor.anim_action_anim:
            actor.anim_action_type = 0
            return
        if actor.frame == actor.anim_action_frame:
            actor.anim_action_type = FRAPPE_OK
        return
    if action == FRAPPE_OK:
        if actor.anim != actor.anim_action_anim:
            actor.anim_action_type = 0
        # No early return here: FITD animAction.cpp:48-51 hit-tests on this
        # tick even when the anim mismatch just zeroed anim_action_type.
        x = actor.room_x + actor.hot_point[0] + actor.step_x
        y = actor.room_y + actor.hot_point[1] + actor.step_y
        z = actor.room_z + actor.hot_point[2] + actor.step_z
        radius = actor.anim_action_param
        cube = [x-radius, x+radius, y-radius, y+radius, z-radius, z+radius]
        for victim_idx in check_object_col(game, actor_idx, cube):
            _publish_hit(game, actor_idx, victim_idx)
            if game.actors[victim_idx].object_type & AF_ANIMATED:
                actor.anim_action_type = 0
                return
        return
    if action == HIT_OBJECT:
        return
