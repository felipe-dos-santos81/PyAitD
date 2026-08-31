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


def _rotate_span_float(pts, start, count, dx, dy, dz):
    # Float twin of skel._rotate_list: same axis order (y, then x, then
    # z), same pair assignments, exact trigonometry instead of
    # COS_TABLE's >>16 <<1 truncation. COS_TABLE[a] ~= sin(a*pi/512) and
    # the table's paired lookup at a+0x100 is cos(a*pi/512), so the
    # integer formula ((x*s - z*c) >> 16) << 1 is x*cos - z*sin.
    span = pts[start:start + count]
    for rot, (i, j) in (((dy % 1024.0), (0, 2)),
                        ((dx % 1024.0), (1, 2)),
                        ((dz % 1024.0), (0, 1))):
        if rot:
            theta = rot * (np.pi / 512.0)
            c, s = np.cos(theta), np.sin(theta)
            a, b = span[:, i].copy(), span[:, j].copy()
            span[:, i] = a * c - b * s
            span[:, j] = a * s + b * c


def _rotate_group_float(pts, group, groups, dx, dy, dz):
    # InitGroupeRot + RotateGroupe recursion, exactly as skel._rotate_group
    _rotate_span_float(pts, group.start, group.num_vertices, dx, dy, dz)
    for other in groups:
        if other.org_group == group.num_group and other is not group:
            _rotate_group_float(pts, other, groups, dx, dy, dz)


def pose_vertices_float(body, group_states, actor_angles=None):
    """Float64 twin of skel.pose_vertices: same group hierarchy, same
    axis order, real trigonometry and fractional angles. Diverges from
    the integer pose only by its truncation (bounded; pinned by
    tests/test_motion.py), the way CameraView diverges from skel.skin.
    Rendering only -- never picking, masks or combat."""
    pts = np.array(body.vertices, dtype=np.float64).reshape(-1, 3)
    num_points = len(pts)

    if actor_angles is not None:
        if body.group_order:
            # FITD AnimNuage: group 0 delta is the actor's own angles
            group_states = list(group_states)
            group_states[0] = (0, actor_angles)
        else:
            # FITD RotateNuage: non-animated bodies rotate as one model.
            _rotate_span_float(pts, 0, num_points, *actor_angles)

    for order_idx in body.group_order:
        group = body.groups[order_idx]
        gtype, (dx, dy, dz) = group_states[order_idx]
        if dx or dy or dz:
            if gtype == 0:
                _rotate_group_float(pts, group, body.groups, dx, dy, dz)
            elif gtype == 1:
                pts[group.start:group.start + group.num_vertices] += (dx, dy, dz)
            elif gtype == 2:
                pts[group.start:group.start + group.num_vertices] *= (
                    (dx + 256.0) / 256.0, (dy + 256.0) / 256.0, (dz + 256.0) / 256.0)

    for group in body.groups:
        start, count = group.start, group.num_vertices
        base_idx = group.base_vertices
        base = pts[base_idx].copy()
        if start <= base_idx < start + count:
            # skel.pose_vertices holds `base` as a live alias into the list
            # it is mutating: a base vertex inside its own span doubles
            # first, and every vertex after it adds the doubled base.
            pts[start:base_idx] += base
            pts[base_idx] += base
            pts[base_idx + 1:start + count] += 2.0 * base
        else:
            pts[start:start + count] += base
    return pts
