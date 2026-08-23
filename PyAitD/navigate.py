# SPDX-License-Identifier: GPL-2.0-only
"""Mouse follower: turns a NavIntent into one tick of steering.

Runs inside playworld.apply_play_input, so the decision is made once per tick
and consumed twice — once as mirrored joystick bits (LIFE scripts read the
joystick through evalVar 0x13 and must not see a dead stick while the player
is walking), and once by tracks._process_track_mouse, which applies it through
the same _turn_toward the engine's follow mode uses.
"""
from PyAitD.effects import NavDecision
from PyAitD.navmesh import find_path
from PyAitD.realvalue import give_distance_2d
from PyAitD.tracks import cap_objet, get_room_link
from PyAitD.world import cdiv

ARRIVE_DISTANCE = 400    # tracks.DISTANCE_TO_POINT_TRESSHOLD [sic], same units
WAYPOINT_DISTANCE = 400  # how close counts as reaching an intermediate hop


def _repath(game, actor, mesh):
    intent = game.nav_intent
    intent.path_room = actor.room
    if intent.room != actor.room:
        # One hop: aim for the centre of the zone linking us to the target room,
        # exactly as _process_track_follow does for a followed actor in another
        # room. gere_dec performs the actual transition when we cross it; the
        # room change then re-paths us to the real destination below.
        # cdiv (C truncation toward zero), same as _process_track_follow uses.
        link = get_room_link(game, actor.room, intent.room)
        intent.waypoints = [(
            link.x1 + cdiv(link.x2 - link.x1, 2),
            link.z1 + cdiv(link.z2 - link.z1, 2),
        )]
        return
    start = (actor.room_x + actor.step_x, actor.room_z + actor.step_z)
    goal = (intent.dest_x, intent.dest_z)
    if mesh is not None:
        path = find_path(mesh, start, goal)
        if path:
            intent.waypoints = list(path)
            return
    # degraded mode: no mesh, hero off-mesh, or no route — steer straight at the
    # click and let the engine's own collision slide do what A* would not
    intent.waypoints = [goal]


def decide(game, actor, mesh):
    """One tick of follower output, or None when there is nothing to follow."""
    intent = game.nav_intent
    if intent is None:
        return None
    if intent.waypoints is None or getattr(intent, "path_room", None) != actor.room:
        _repath(game, actor, mesh)
    here_x = actor.room_x + actor.step_x
    here_z = actor.room_z + actor.step_z
    while len(intent.waypoints) > 1:
        target = intent.waypoints[0]
        if give_distance_2d(here_x, here_z, target[0], target[1]) >= WAYPOINT_DISTANCE:
            break
        intent.waypoints.pop(0)
    target_x, target_z = intent.waypoints[0]
    distance = give_distance_2d(here_x, here_z, target_x, target_z)
    if len(intent.waypoints) == 1 and distance < ARRIVE_DISTANCE:
        return NavDecision(0, target_x, target_z, advance=False, arrived=True)
    joyd = 1  # forward
    modificator = cap_objet(here_x, here_z, actor.beta, target_x, target_z)
    if modificator > 0:
        joyd |= 4   # gere_manual_rot: bit 4 -> direction +1
    elif modificator < 0:
        joyd |= 8   # bit 8 -> direction -1
    return NavDecision(joyd, target_x, target_z, advance=True, arrived=False)
