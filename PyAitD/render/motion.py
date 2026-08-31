# SPDX-License-Identifier: GPL-2.0-only
"""Inter-tick motion blending for the enhanced renderer.

Presentation-only, on the CameraView precedent: a float twin beside the
authoritative integer path. The shell snapshots per-actor state before
each 50 Hz tick; build_frame blends snapshot -> live state at
alpha = accumulator / TICK_MS. Interpolation, never extrapolation: the
rendered pose lags the simulation by up to one tick. skel.skin, the
draw_list, picking and masks always read the integer, current-tick
state. Pure and pygame/GL free."""
from dataclasses import dataclass

import numpy as np

# The largest per-tick movement still treated as motion. The fastest
# legitimate travel (run, speed 5) moves well under 100 world units per
# 20 ms tick; anything past this is a script teleport and snaps.
TELEPORT_LIMIT = 500


@dataclass(frozen=True)
class ActorMotion:
    body_num: int
    room: int
    anim: int
    position: tuple   # (x, y, z) floats, world + step
    angles: tuple     # (alpha, beta, gamma) floats, 0..1024 units
    states: tuple     # ((gtype, (dx, dy, dz)), ...) floats; () when no player


@dataclass(frozen=True)
class MotionSnapshot:
    floor: int
    camera: int
    actors: dict      # actor index -> ActorMotion


def snapshot(game):
    """Per-actor motion state as of the last committed tick.

    Reads game.anim_players directly instead of anim_player_for so a
    snapshot never creates a player; an actor without one (static body,
    or first frame of a new anim) carries empty states and blend_actor
    falls back to the live states for the pose while still blending
    angles and position."""
    actors = {}
    for index, actor in enumerate(game.actors):
        if actor.index_in_world < 0 or actor.body_num == -1:
            continue
        player = game.anim_players.get(index) if actor.anim != -1 else None
        states = ()
        if player is not None:
            states = tuple(
                (gtype, (float(d[0]), float(d[1]), float(d[2])))
                for gtype, d in player.group_states()
            )
        actors[index] = ActorMotion(
            body_num=actor.body_num,
            room=actor.room,
            anim=actor.anim,
            position=(
                float(actor.world_x + actor.step_x),
                float(actor.world_y + actor.step_y),
                float(actor.world_z + actor.step_z),
            ),
            angles=(float(actor.alpha), float(actor.beta), float(actor.gamma)),
            states=states,
        )
    return MotionSnapshot(
        floor=game.current_floor, camera=game.num_camera, actors=actors,
    )


def blend_angle(prev, cur, alpha):
    """Shortest-arc interpolation on the 0..1024 rotation circle — the
    continuous float twin of patch_inter_angle's ±0x200 wrap rule."""
    delta = ((cur - prev + 512.0) % 1024.0) - 512.0
    return (prev + delta * alpha) % 1024.0


def blend_states(prev_states, cur_states, alpha):
    """Blend group states index-by-index; a gtype mismatch takes the
    current entry verbatim (a group that changed kind mid-anim has no
    meaningful in-between)."""
    out = []
    for (pg, pd), (cg, cd) in zip(prev_states, cur_states):
        if pg != cg:
            out.append((cg, cd))
        elif cg == 0:
            out.append((cg, tuple(blend_angle(p, c, alpha) for p, c in zip(pd, cd))))
        else:
            out.append((cg, tuple(p + (c - p) * alpha for p, c in zip(pd, cd))))
    return tuple(out)


def blend_actor(prev, body_num, room, anim, states, angles, position, alpha):
    """(states, angles, position, pose_fn) for one actor's geometry.

    Blended through the float pose twin when `prev` is blendable;
    verbatim with pose_fn None otherwise. The snap rules: no snapshot
    entry, a different body, room or anim, or a teleport past
    TELEPORT_LIMIT."""
    if (prev is None or prev.body_num != body_num or prev.room != room
            or prev.anim != anim
            or max(abs(p - c) for p, c in zip(prev.position, position)) > TELEPORT_LIMIT):
        return states, angles, position, None
    if len(prev.states) == len(states):
        out_states = blend_states(prev.states, states, alpha)
    else:
        out_states = states
    out_angles = tuple(blend_angle(p, c, alpha) for p, c in zip(prev.angles, angles))
    out_position = tuple(p + (c - p) * alpha for p, c in zip(prev.position, position))
    return out_states, out_angles, out_position, pose_vertices_float


def pose_vertices_float(body, group_states, actor_angles=None):
    # Task 2 replaces this stub with the real float twin of
    # skel.pose_vertices. blend_actor only hands it out; nothing calls
    # it until build_frame's blend wiring lands in Task 5.
    raise NotImplementedError("pose_vertices_float lands in Task 2")
